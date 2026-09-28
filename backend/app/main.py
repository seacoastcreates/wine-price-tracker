import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from wineprice.windows import drinking_window

from app import explain, inference
from app.db import query

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the active model at startup so the first prediction doesn't pay for it.
    try:
        log.info("Loaded model %s", inference.store.get().version)
    except inference.NoActiveModel:
        log.warning("No active model yet; /predict will return 503 until one is registered")
    yield


app = FastAPI(title="Wine Price Tracker API", version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SOURCE_NAME = "Pennsylvania Liquor Control Board quarterly price lists"


class WineSummary(BaseModel):
    slug: str
    family: str
    name: str
    vintage: str
    region: str | None
    size: str
    style: str
    tier: str
    is_featured: bool
    is_active: bool
    latest_date: date | None
    regular_price: float | None
    promo_price: float | None
    promo_type: str | None
    first_date: date | None
    change_1y_pct: float | None
    change_5y_pct: float | None
    p_up_1y: float | None
    p_down_1y: float | None
    up_pct: float | None
    down_pct: float | None
    fair_price: float | None
    fair_low: float | None
    fair_high: float | None
    value_pct: float | None


class WineList(BaseModel):
    total: int
    items: list[WineSummary]


class PricePoint(BaseModel):
    date: date
    regular_price: float
    promo_price: float | None
    promo_type: str | None


class ForecastPoint(BaseModel):
    date: date
    p10: float
    p50: float
    p90: float
    p_up: float
    p_down: float
    up_pct: float
    down_pct: float


class Forecast(BaseModel):
    model_version: str
    algorithm: str
    points: list[ForecastPoint]


class DrinkingWindow(BaseModel):
    opens: int
    closes: int
    status: Literal["before", "in", "past"]
    basis: str


class NextVintage(BaseModel):
    next_vintage: int
    p_up: float
    p_down: float
    p10_pct: float
    p50_pct: float
    p90_pct: float


class Insights(BaseModel):
    drinking_window: DrinkingWindow | None
    next_vintage: NextVintage | None


class Prediction(BaseModel):
    model_version: str
    latency_ms: float
    baseline: list[ForecastPoint]
    scenario: list[ForecastPoint] | None = None
    applied: inference.Scenario | None = None


class ModelInfo(BaseModel):
    model_version: str
    algorithm: str
    trained_at: str
    horizon: int
    horizon_unit: str
    metrics: dict
    source: str = SOURCE_NAME


SUMMARY_SQL = """
WITH active_model AS (SELECT model_version FROM model_runs WHERE is_active),
year_ahead AS (
    SELECT DISTINCT ON (f.wine_id) f.wine_id, f.p_up, f.p_down, f.up_pct, f.down_pct
    FROM forecasts f JOIN active_model USING (model_version)
    ORDER BY f.wine_id, f.target_date DESC
),
fair AS (
    SELECT fp.wine_id, fp.fair_p10, fp.fair_p50, fp.fair_p90, fp.value_pct
    FROM fair_prices fp JOIN active_model USING (model_version)
),
filtered AS (
    SELECT w.*, ya.p_up AS p_up_1y, ya.p_down AS p_down_1y, ya.up_pct, ya.down_pct,
           fair.fair_p50::float AS fair_price, fair.fair_p10::float AS fair_low, fair.fair_p90::float AS fair_high,
           fair.value_pct
    FROM wines w LEFT JOIN year_ahead ya ON ya.wine_id = w.id
    LEFT JOIN fair ON fair.wine_id = w.id
    WHERE (CAST(:style AS TEXT) IS NULL OR w.style = :style)
      AND (CAST(:tier AS TEXT) IS NULL OR w.tier = :tier)
      AND (CAST(:q AS TEXT) IS NULL OR w.name ILIKE '%' || :q || '%')
      AND (NOT :featured OR w.is_featured)
      AND (NOT :active OR w.is_active)
      AND (CAST(:slug AS TEXT) IS NULL OR w.slug = :slug)
      AND (CAST(:family AS TEXT) IS NULL OR w.family = :family)
      AND (NOT :investor OR (w.vintage <> 'NV' AND w.tier IN ('premium', 'luxury')))
)
SELECT f.slug, f.family, f.name, f.vintage, f.region, f.size, f.style, f.tier, f.is_featured, f.is_active,
       cur.observed_on AS latest_date, cur.regular_price::float AS regular_price,
       cur.promo_price::float AS promo_price, cur.promo_type,
       hist.first_date,
       ROUND((100 * (cur.regular_price / NULLIF(y1.regular_price, 0) - 1))::numeric, 1)::float AS change_1y_pct,
       ROUND((100 * (cur.regular_price / NULLIF(y5.regular_price, 0) - 1))::numeric, 1)::float AS change_5y_pct,
       f.p_up_1y, f.p_down_1y, f.up_pct, f.down_pct,
       f.fair_price, f.fair_low, f.fair_high, f.value_pct,
       COUNT(*) OVER () AS total
FROM filtered f
CROSS JOIN LATERAL (
    SELECT observed_on, regular_price, promo_price, promo_type FROM price_observations
    WHERE wine_id = f.id ORDER BY observed_on DESC LIMIT 1
) cur
CROSS JOIN LATERAL (SELECT MIN(observed_on) AS first_date FROM price_observations WHERE wine_id = f.id) hist
LEFT JOIN LATERAL (
    SELECT regular_price FROM price_observations
    WHERE wine_id = f.id AND observed_on BETWEEN cur.observed_on - INTERVAL '1 year 7 days'
                                             AND cur.observed_on - INTERVAL '1 year' + INTERVAL '7 days'
    LIMIT 1
) y1 ON TRUE
LEFT JOIN LATERAL (
    SELECT regular_price FROM price_observations
    WHERE wine_id = f.id AND observed_on BETWEEN cur.observed_on - INTERVAL '5 years 7 days'
                                             AND cur.observed_on - INTERVAL '5 years' + INTERVAL '7 days'
    LIMIT 1
) y5 ON TRUE
"""

# Sortable columns: SQL expression and the default direction on first click.
SORTS = {
    "name": ("f.name", "asc"),
    "price": ("COALESCE(cur.promo_price, cur.regular_price)", "desc"),  # what the shelf shows
    "change_1y": ("change_1y_pct", "desc"),
    "change_5y": ("change_5y_pct", "desc"),
    "fair": ("f.value_pct", "desc"),
    "likely_up": ("f.p_up_1y", "desc"),
    "likely_down": ("f.p_down_1y", "desc"),
    # Best value: prices below the fair range first, then the biggest discount to fair price.
    "value": ("(cur.regular_price < f.fair_low) DESC, f.value_pct", "asc"),
}


def order_by(sort: str, direction: str | None) -> str:
    expr, default = SORTS[sort]
    d = (direction or default).upper()
    return f" ORDER BY {expr} {d} NULLS LAST, f.name ASC, f.slug ASC"


def summaries(**params) -> list[dict]:
    defaults = dict(style=None, tier=None, q=None, featured=False, active=False, slug=None, family=None,
                    investor=False)
    return query(SUMMARY_SQL + params.pop("tail", ""), **{**defaults, **params})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/wines", response_model=WineList)
def list_wines(
    style: str | None = None,
    tier: str | None = None,
    q: str | None = Query(None, description="Case-insensitive match on the wine name"),
    featured: bool = Query(False, description="Only the curated list of popular wines"),
    investor: bool = Query(False, description="Only vintage-dated premium and luxury wines"),
    active: bool = Query(True, description="Only wines on the latest price list"),
    sort: Literal["name", "price", "change_1y", "change_5y", "fair", "likely_up", "likely_down", "value"] = "name",
    dir: Literal["asc", "desc"] | None = Query(None, description="Sort direction (default depends on the column)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = summaries(style=style, tier=tier, q=q, featured=featured, active=active, investor=investor,
                     tail=order_by(sort, dir) + " LIMIT :limit OFFSET :offset", limit=limit, offset=offset)
    return {"total": rows[0]["total"] if rows else 0, "items": rows}


@app.get("/wines/{slug}", response_model=WineSummary)
def get_wine(slug: str):
    rows = summaries(slug=slug)
    if not rows:
        raise HTTPException(404, "Wine not found")
    return rows[0]


@app.get("/wines/{slug}/vintages", response_model=list[WineSummary])
def get_vintages(slug: str):
    """Every vintage of the same product and size, newest first (including this one)."""
    family = query("SELECT family FROM wines WHERE slug = :slug", slug=slug)
    if not family:
        raise HTTPException(404, "Wine not found")
    return summaries(family=family[0]["family"], tail=" ORDER BY f.vintage = 'NV', f.vintage DESC")


@app.get("/wines/{slug}/insights", response_model=Insights)
def get_insights(slug: str):
    """Typical drinking window (heuristic) and the next-vintage pricing outlook for a wine."""
    rows = query("SELECT id, vintage, region, style, tier FROM wines WHERE slug = :slug", slug=slug)
    if not rows:
        raise HTTPException(404, "Wine not found")
    w = rows[0]
    window = None
    if w["vintage"] != "NV":
        start, end = drinking_window(w["region"], w["style"], w["tier"])
        opens, closes = int(w["vintage"]) + start, int(w["vintage"]) + end
        year = date.today().year
        window = {"opens": opens, "closes": closes,
                  "status": "before" if year < opens else "past" if year > closes else "in",
                  "basis": f"typical for {w['tier']} {w['style']} wine from {w['region'] or 'this category'}"}
    nxt = query(
        """
        SELECT o.next_vintage, o.p_up, o.p_down, o.p10_pct, o.p50_pct, o.p90_pct
        FROM vintage_outlook o JOIN model_runs m USING (model_version)
        WHERE m.is_active AND o.wine_id = :id
        """,
        id=w["id"],
    )
    return {"drinking_window": window, "next_vintage": nxt[0] if nxt else None}


@app.get("/wines/{slug}/prices", response_model=list[PricePoint])
def get_prices(slug: str):
    rows = query(
        """
        SELECT p.observed_on AS date, p.regular_price::float AS regular_price,
               p.promo_price::float AS promo_price, p.promo_type
        FROM price_observations p JOIN wines w ON w.id = p.wine_id
        WHERE w.slug = :slug
        ORDER BY p.observed_on
        """,
        slug=slug,
    )
    if not rows:
        raise HTTPException(404, "No prices for this wine")
    return rows


@app.get("/wines/{slug}/forecast", response_model=Forecast)
def get_forecast(slug: str):
    rows = query(
        """
        SELECT m.model_version, m.algorithm, f.target_date AS date,
               f.p10::float AS p10, f.p50::float AS p50, f.p90::float AS p90,
               f.p_up, f.p_down, f.up_pct, f.down_pct
        FROM forecasts f
        JOIN model_runs m USING (model_version)
        JOIN wines w ON w.id = f.wine_id
        WHERE m.is_active AND w.slug = :slug
        ORDER BY f.target_date
        """,
        slug=slug,
    )
    if not rows:
        raise HTTPException(404, "No forecast available")
    keys = ("date", "p10", "p50", "p90", "p_up", "p_down", "up_pct", "down_pct")
    return {
        "model_version": rows[0]["model_version"],
        "algorithm": rows[0]["algorithm"],
        "points": [{k: r[k] for k in keys} for r in rows],
    }


def run_prediction(slug: str, scenario: inference.Scenario | None) -> dict:
    try:
        return inference.predict(slug, scenario)
    except inference.NoActiveModel as e:
        raise HTTPException(503, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, "Wine not found") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/wines/{slug}/predict", response_model=Prediction)
def predict_live(slug: str):
    """Online inference: run the active model on this wine's current price history."""
    return run_prediction(slug, None)


@app.post("/wines/{slug}/predict", response_model=Prediction)
def predict_scenario(slug: str, scenario: inference.Scenario):
    """What-if: change today's list price or promotion and see how the forecast responds."""
    return run_prediction(slug, scenario)


class Explanation(BaseModel):
    text: str
    model_id: str
    model_version: str
    created_at: str
    cached: bool


@app.get("/wines/{slug}/explanation", response_model=Explanation)
def get_explanation(slug: str):
    """A previously generated explanation for this wine and the active model, if one exists."""
    try:
        hit = explain.get(slug)
    except KeyError as e:
        raise HTTPException(404, "Wine not found") from e
    except explain.NoActiveModel as e:
        raise HTTPException(503, str(e)) from e
    if hit is None:
        raise HTTPException(404, "No explanation yet")
    return hit


@app.post("/wines/{slug}/explanation", response_model=Explanation)
def create_explanation(slug: str):
    """Explain this wine's outlook in plain English (Amazon Nova on Amazon Bedrock); cached per model version."""
    try:
        return explain.generate(slug)
    except KeyError as e:
        raise HTTPException(404, "Wine not found") from e
    except explain.NoActiveModel as e:
        raise HTTPException(503, str(e)) from e
    except explain.RateLimited as e:
        raise HTTPException(429, str(e)) from e
    except (ClientError, BotoCoreError) as e:
        log.exception("Bedrock call failed")
        raise HTTPException(502, "The explanation service is unavailable right now") from e


@app.get("/model", response_model=ModelInfo)
def get_model():
    rows = query(
        "SELECT model_version, algorithm, trained_at::text AS trained_at, horizon, horizon_unit, metrics "
        "FROM model_runs WHERE is_active"
    )
    if not rows:
        raise HTTPException(404, "No active model")
    return rows[0]
