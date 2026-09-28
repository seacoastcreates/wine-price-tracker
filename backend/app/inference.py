"""Online inference: load the active model from the registry and forecast one wine on demand.

Features are built by the same `wineprice` code the training job uses, so online predictions
match the stored batch forecasts exactly (see tests/test_parity.py).
"""

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator
from wineprice.model import WinePriceModel

from app.db import query

REFRESH_SECONDS = float(os.environ.get("MODEL_REFRESH_SECONDS", "60"))


class NoActiveModel(RuntimeError):
    """No model is registered as active yet."""


class Scenario(BaseModel):
    """A what-if applied to the wine's latest price-list entry before predicting."""

    promo: Literal["keep", "none", "sale", "clearance"] = Field(
        "keep", description="keep the current promotion, remove it, or put the wine on sale / clearance")
    discount_pct: float = Field(0, ge=0, le=80, description="Discount for a sale or clearance, in percent")
    list_price: float | None = Field(None, gt=0, description="Override today's list price")

    @model_validator(mode="after")
    def discount_needed(self) -> "Scenario":
        if self.promo in ("sale", "clearance") and self.discount_pct <= 0:
            raise ValueError("a sale or clearance needs discount_pct > 0")
        return self


@dataclass
class Loaded:
    model: WinePriceModel
    version: str
    periods: pd.DatetimeIndex
    checked_at: float


class ModelStore:
    """Holds the active model in memory and swaps it when a new one is activated in the registry."""

    def __init__(self) -> None:
        self._loaded: Loaded | None = None
        self._lock = threading.Lock()

    def get(self) -> Loaded:
        with self._lock:
            if self._loaded and time.monotonic() - self._loaded.checked_at < REFRESH_SECONDS:
                return self._loaded
            rows = query("SELECT model_version, artifact_uri FROM model_runs WHERE is_active")
            if not rows:
                raise NoActiveModel("No active model")
            version, uri = rows[0]["model_version"], rows[0]["artifact_uri"]
            periods = pd.DatetimeIndex(pd.to_datetime(
                [r["d"] for r in query("SELECT DISTINCT observed_on AS d FROM price_observations ORDER BY 1")]))
            if self._loaded is None or self._loaded.version != version:
                model = WinePriceModel.load(fetch_artifact(uri))
                self._loaded = Loaded(model, version, periods, time.monotonic())
            else:
                self._loaded = Loaded(self._loaded.model, version, periods, time.monotonic())
            return self._loaded


def fetch_artifact(uri: str) -> str:
    """Local path as-is; s3://bucket/key is downloaded to a temp file first."""
    if not uri.startswith("s3://"):
        return uri
    import boto3  # only needed when the registry points at S3

    bucket, key = uri[5:].split("/", 1)
    path = os.path.join(tempfile.gettempdir(), key.replace("/", "_"))
    if not os.path.exists(path):
        boto3.client("s3").download_file(bucket, key, path)
    return path


store = ModelStore()


def wine_history(slug: str) -> pd.DataFrame:
    rows = query(
        """
        SELECT p.wine_id, p.observed_on AS date, p.regular_price::float AS price,
               p.promo_price::float AS promo_price, p.promo_type, w.style, w.tier, w.vintage, w.region,
               w.brand, w.grape, w.classification
        FROM price_observations p JOIN wines w ON w.id = p.wine_id
        WHERE w.slug = :slug
        ORDER BY p.observed_on
        """,
        slug=slug,
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def apply_scenario(history: pd.DataFrame, s: Scenario) -> pd.DataFrame:
    h = history.copy()
    last = h.index[-1]
    if s.list_price is not None:
        h.loc[last, "price"] = s.list_price
    if s.promo == "none":
        h.loc[last, ["promo_price", "promo_type"]] = [None, None]
    elif s.promo in ("sale", "clearance"):
        h.loc[last, "promo_price"] = round(h.loc[last, "price"] * (1 - s.discount_pct / 100), 2)
        h.loc[last, "promo_type"] = s.promo
    return h


def points(pred: pd.DataFrame) -> list[dict]:
    cols = ["target_date", "p10", "p50", "p90", "p_up", "p_down", "up_pct", "down_pct"]
    return [{**r, "date": r.pop("target_date")} for r in pred[cols].to_dict("records")]


def predict(slug: str, scenario: Scenario | None = None) -> dict:
    started = time.perf_counter()
    loaded = store.get()
    history = wine_history(slug)
    if history.empty:
        raise KeyError(slug)
    if history["date"].max() != loaded.periods[-1]:
        raise ValueError("This wine is not on the latest price list, so there is nothing to forecast from")
    baseline = loaded.model.forecast(history, loaded.periods)
    result = {"model_version": loaded.version, "baseline": points(baseline), "scenario": None}
    if scenario is not None:
        result["scenario"] = points(loaded.model.forecast(apply_scenario(history, scenario), loaded.periods))
        result["applied"] = scenario.model_dump()
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result
