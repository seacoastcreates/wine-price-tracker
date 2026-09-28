"""Plain-English explanations of a wine's outlook, written by Amazon Nova on Amazon Bedrock.

The model is given only facts computed by our own models and data (price history, the price-change
forecast, fair price, drinking window, next-vintage outlook) and asked to explain them; it is not
asked to predict anything itself. Explanations are cached per wine and model version, generated only
on request, and capped per hour, so Bedrock cost follows real usage.
"""

import os
import threading
import time
from collections import deque
from functools import lru_cache

import boto3
from botocore.config import Config

from app.db import query

# Amazon Nova Lite: a first-party Amazon model, so no AWS Marketplace subscription is needed (the account's
# Free plan blocks Marketplace model subscriptions). Any Converse-compatible model can be swapped in.
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
MAX_PER_HOUR = int(os.environ.get("EXPLAIN_MAX_PER_HOUR", "60"))

SYSTEM = (
    "You explain wine price forecasts on a retail price-tracking site. Write two or three short sentences in "
    "plain English for a wine buyer. Use only the facts provided; do not invent vintages, scores, producers' "
    "plans or market events. Explain what the numbers mean and the most likely reason behind the outlook "
    "(for example the wine's age relative to its drinking window, a current discount, or how its price compares "
    "with similar wines). Say so when chances are low. Do not give financial advice or tell the reader to buy or "
    "sell. No headings, lists or markdown."
)


class RateLimited(RuntimeError):
    """Too many new explanations generated in the last hour."""


class NoActiveModel(RuntimeError):
    """No model is registered as active yet."""


_recent: deque[float] = deque()
_lock = threading.Lock()


def _take_slot() -> None:
    with _lock:
        now = time.monotonic()
        while _recent and now - _recent[0] > 3600:
            _recent.popleft()
        if len(_recent) >= MAX_PER_HOUR:
            raise RateLimited("Explanation limit reached for this hour; please try again later")
        _recent.append(now)


@lru_cache
def _client():
    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=30),
    )


def _pct(p: float | None) -> str:
    return "unknown" if p is None else ("under 1%" if p < 0.005 else f"{round(p * 100)}%")


def facts(slug: str) -> tuple[int, str, list[str]]:
    """(wine id, active model version, fact lines) for a wine, from the database."""
    rows = query(
        """
        WITH m AS (SELECT model_version FROM model_runs WHERE is_active)
        SELECT w.id, w.name, w.vintage, w.region, w.style, w.tier, w.grape, w.classification, w.is_active,
               (SELECT model_version FROM m) AS model_version,
               (SELECT count(*) FROM price_observations p WHERE p.wine_id = w.id) AS quarters,
               (SELECT count(*) FROM price_observations p WHERE p.wine_id = w.id AND p.promo_type = 'sale') AS sale_quarters,
               (SELECT min(observed_on) FROM price_observations p WHERE p.wine_id = w.id) AS first_seen,
               cur.regular_price::float AS price, cur.promo_price::float AS promo_price, cur.promo_type,
               first.regular_price::float AS first_price,
               f.p_up, f.p_down, f.up_pct, f.down_pct,
               fp.fair_p10::float AS fair_low, fp.fair_p50::float AS fair, fp.fair_p90::float AS fair_high,
               vo.next_vintage, vo.p_up AS nv_p_up, vo.p50_pct AS nv_p50
        FROM wines w
        CROSS JOIN LATERAL (SELECT regular_price, promo_price, promo_type FROM price_observations
                            WHERE wine_id = w.id ORDER BY observed_on DESC LIMIT 1) cur
        CROSS JOIN LATERAL (SELECT regular_price FROM price_observations
                            WHERE wine_id = w.id ORDER BY observed_on LIMIT 1) first
        LEFT JOIN LATERAL (SELECT p_up, p_down, up_pct, down_pct FROM forecasts
                           WHERE wine_id = w.id AND model_version = (SELECT model_version FROM m)
                           ORDER BY target_date DESC LIMIT 1) f ON TRUE
        LEFT JOIN fair_prices fp ON fp.wine_id = w.id AND fp.model_version = (SELECT model_version FROM m)
        LEFT JOIN vintage_outlook vo ON vo.wine_id = w.id AND vo.model_version = (SELECT model_version FROM m)
        WHERE w.slug = :slug
        """,
        slug=slug,
    )
    if not rows:
        raise KeyError(slug)
    r = rows[0]
    if r["model_version"] is None:
        raise NoActiveModel("No active model")
    title = r["name"] if r["vintage"] == "NV" else f"{r['name']} {r['vintage']}"
    lines = [
        f"Wine: {title} ({r['style']}, {r['region'] or 'region not stated'}"
        f"{', ' + r['grape'] if r['grape'] else ''}{', ' + r['classification'] if r['classification'] else ''}).",
        f"Price tier: {r['tier']}. Current list price ${r['price']:.2f}"
        + (f", currently on {r['promo_type']} at ${r['promo_price']:.2f}" if r["promo_price"] else "") + ".",
        f"Tracked for {r['quarters']} quarters since {r['first_seen']}; first list price ${r['first_price']:.2f}; "
        f"on sale in {r['sale_quarters']} of those quarters.",
    ]
    if r["vintage"] != "NV":
        from datetime import date

        from wineprice.windows import drinking_window

        start, end = drinking_window(r["region"], r["style"], r["tier"])
        opens, closes = int(r["vintage"]) + start, int(r["vintage"]) + end
        status = "before" if date.today().year < opens else "past" if date.today().year > closes else "inside"
        lines.append(f"Typical drinking window for this kind of wine: {opens}-{closes} (rule of thumb); "
                     f"it is currently {status} that window.")
    if r["p_up"] is not None:
        lines.append(f"Model: chance the list price is higher within a year {_pct(r['p_up'])} (typical rise "
                     f"{r['up_pct']:.0f}%); chance it is lower {_pct(r['p_down'])} (typical cut {r['down_pct']:.0f}%).")
    if r["fair"] is not None:
        lines.append(f"Fair price from comparable wines (region, grape, classification, age, producer's other "
                     f"wines): ${r['fair']:.2f}, 80% range ${r['fair_low']:.2f}-${r['fair_high']:.2f}.")
    if r["next_vintage"] is not None:
        lines.append(f"Next vintage ({r['next_vintage']}): {_pct(r['nv_p_up'])} chance it is priced higher than "
                     f"this one; typical change {r['nv_p50']:+.0f}%.")
    lines.append("Across all wines, the strongest drivers of price rises are years until the drinking window "
                 "opens, the size of any current discount, and price level; only about 3% of wines change "
                 "list price in a given quarter.")
    return r["id"], r["model_version"], lines


def cached(wine_id: int, model_version: str) -> dict | None:
    rows = query(
        "SELECT text, model_id, created_at::text AS created_at FROM explanations "
        "WHERE wine_id = :w AND model_version = :v",
        w=wine_id, v=model_version,
    )
    return rows[0] if rows else None


def get(slug: str) -> dict | None:
    wine_id, version, _ = facts(slug)
    hit = cached(wine_id, version)
    return {**hit, "model_version": version, "cached": True} if hit else None


def generate(slug: str) -> dict:
    wine_id, version, lines = facts(slug)
    hit = cached(wine_id, version)
    if hit:
        return {**hit, "model_version": version, "cached": True}
    _take_slot()
    response = _client().converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": "Facts:\n- " + "\n- ".join(lines)}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0.2},
    )
    text = response["output"]["message"]["content"][0]["text"].strip()
    usage = response.get("usage", {})
    from app.db import get_engine
    from sqlalchemy import text as sql

    with get_engine().begin() as conn:
        conn.execute(
            sql("INSERT INTO explanations (model_version, wine_id, text, model_id, input_tokens, output_tokens) "
                "VALUES (:v, :w, :t, :m, :i, :o) ON CONFLICT (model_version, wine_id) DO NOTHING"),
            {"v": version, "w": wine_id, "t": text, "m": MODEL_ID,
             "i": usage.get("inputTokens"), "o": usage.get("outputTokens")},
        )
    return {**cached(wine_id, version), "model_version": version, "cached": False}
