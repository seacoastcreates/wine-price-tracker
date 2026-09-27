import os
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import query

app = FastAPI(title="Wine Price Tracker API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)

SOURCE_NAME = "Pennsylvania Liquor Control Board quarterly price lists"


class WineSummary(BaseModel):
    slug: str
    name: str
    size: str
    style: str
    tier: str
    latest_vintage: str | None
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


class WineList(BaseModel):
    total: int
    items: list[WineSummary]


class PricePoint(BaseModel):
    date: date
    regular_price: float
    promo_price: float | None
    promo_type: str | None
    vintage: str | None


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
filtered AS (
    SELECT w.*, ya.p_up AS p_up_1y, ya.p_down AS p_down_1y, ya.up_pct, ya.down_pct
    FROM wines w LEFT JOIN year_ahead ya ON ya.wine_id = w.id
    WHERE (CAST(:style AS TEXT) IS NULL OR w.style = :style)
      AND (CAST(:tier AS TEXT) IS NULL OR w.tier = :tier)
      AND (CAST(:q AS TEXT) IS NULL OR w.name ILIKE '%' || :q || '%')
      AND (NOT :featured OR w.is_featured)
      AND (NOT :active OR w.is_active)
      AND (CAST(:slug AS TEXT) IS NULL OR w.slug = :slug)
)
SELECT f.slug, f.name, f.size, f.style, f.tier, f.latest_vintage, f.is_featured, f.is_active,
       cur.observed_on AS latest_date, cur.regular_price::float AS regular_price,
       cur.promo_price::float AS promo_price, cur.promo_type,
       hist.first_date,
       ROUND((100 * (cur.regular_price / NULLIF(y1.regular_price, 0) - 1))::numeric, 1)::float AS change_1y_pct,
       ROUND((100 * (cur.regular_price / NULLIF(y5.regular_price, 0) - 1))::numeric, 1)::float AS change_5y_pct,
       f.p_up_1y, f.p_down_1y, f.up_pct, f.down_pct,
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

SORTS = {
    "name": "f.name",
    "price": "cur.regular_price DESC",
    "likely_up": "f.p_up_1y DESC NULLS LAST, f.name",
    "likely_down": "f.p_down_1y DESC NULLS LAST, f.name",
    "change_1y": "change_1y_pct DESC NULLS LAST, f.name",
}


def summaries(**params) -> list[dict]:
    defaults = dict(style=None, tier=None, q=None, featured=False, active=False, slug=None)
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
    active: bool = Query(True, description="Only wines on the latest price list"),
    sort: Literal["name", "price", "likely_up", "likely_down", "change_1y"] = "name",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = summaries(style=style, tier=tier, q=q, featured=featured, active=active,
                     tail=f" ORDER BY {SORTS[sort]} LIMIT :limit OFFSET :offset", limit=limit, offset=offset)
    return {"total": rows[0]["total"] if rows else 0, "items": rows}


@app.get("/wines/{slug}", response_model=WineSummary)
def get_wine(slug: str):
    rows = summaries(slug=slug)
    if not rows:
        raise HTTPException(404, "Wine not found")
    return rows[0]


@app.get("/wines/{slug}/prices", response_model=list[PricePoint])
def get_prices(slug: str):
    rows = query(
        """
        SELECT p.observed_on AS date, p.regular_price::float AS regular_price,
               p.promo_price::float AS promo_price, p.promo_type, p.vintage
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


@app.get("/model", response_model=ModelInfo)
def get_model():
    rows = query(
        "SELECT model_version, algorithm, trained_at::text AS trained_at, horizon, horizon_unit, metrics "
        "FROM model_runs WHERE is_active"
    )
    if not rows:
        raise HTTPException(404, "No active model")
    return rows[0]
