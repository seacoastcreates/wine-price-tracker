"""Move data between Postgres and the training job.

    python -m scripts.ml_io export <out.csv>          # weekly series -> CSV for ml/train.py
    python -m scripts.ml_io load <artifacts_dir>      # register model, forecasts -> DB, set active
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db import get_engine

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"
# Local model registry: one immutable folder per model version.
REGISTRY = Path(os.environ.get("MODEL_REGISTRY", Path(__file__).resolve().parents[2] / "ml" / "registry"))


def export(out_csv: str) -> None:
    sql = """
        SELECT p.wine_id, p.observed_on AS date, p.regular_price::float AS price,
               p.promo_price::float AS promo_price, p.promo_type, w.style, w.tier, w.vintage, w.region, w.family,
               w.brand, w.grape, w.classification, w.name, w.size
        FROM price_observations p JOIN wines w ON w.id = p.wine_id
        ORDER BY p.wine_id, p.observed_on
    """
    with get_engine().connect() as conn:
        df = pd.read_sql(text(sql), conn)
    out_dir = Path(out_csv).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    # Context tables for external features travel with the training data.
    with get_engine().connect() as conn:
        pd.read_sql(text("SELECT name, latitude, longitude, hemisphere FROM regions"), conn).to_csv(
            out_dir / "regions.csv", index=False)
    for name in ("region_weather.csv", "ca_supply.csv"):
        src = PROCESSED / name
        if src.exists():
            shutil.copy(src, out_dir / name)
    print(f"Exported {len(df)} rows for {df['wine_id'].nunique()} wines (+ context tables) to {out_dir}")


def load(artifacts_dir: str, artifact_uri: str | None = None) -> None:
    """Register a trained model and load its outputs. With `artifact_uri` (e.g. an s3:// registry path)
    the artifact already lives there; otherwise it is copied into the local registry folder."""
    d = Path(artifacts_dir)
    metrics = json.loads((d / "metrics.json").read_text())
    # Optional extras produced by ablation.py and train_vintage.py.
    for key, name in (("ablation", "ablation.json"), ("vintage_model", "vintage_metrics.json"),
                      ("fair_model", "fair_metrics.json")):
        if (d / name).exists():
            metrics[key] = json.loads((d / name).read_text())
    forecasts = pd.read_csv(d / "forecasts.csv")
    outlook = pd.read_csv(d / "vintage_outlook.csv") if (d / "vintage_outlook.csv").exists() else None
    fair = pd.read_csv(d / "fair_prices.csv") if (d / "fair_prices.csv").exists() else None
    version = metrics["model_version"]
    if artifact_uri is None:
        dest = REGISTRY / version
        shutil.copytree(d, dest, dirs_exist_ok=True)
        artifact_uri = str((dest / "model.joblib").resolve())
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE model_runs SET is_active = FALSE WHERE is_active"))
        conn.execute(
            text(
                "INSERT INTO model_runs (model_version, algorithm, horizon, horizon_unit, metrics, artifact_uri, is_active) "
                "VALUES (:v, :a, :h, :u, CAST(:m AS JSONB), :uri, TRUE)"
            ),
            {"v": version, "a": metrics["algorithm"], "h": metrics["horizon"], "u": metrics["horizon_unit"],
             "m": json.dumps(metrics), "uri": artifact_uri},
        )
        conn.execute(
            text(
                "INSERT INTO forecasts (model_version, wine_id, target_date, p10, p50, p90, p_up, p_down, up_pct, down_pct) "
                "VALUES (:model_version, :wine_id, :target_date, :p10, :p50, :p90, :p_up, :p_down, :up_pct, :down_pct)"
            ),
            forecasts.assign(model_version=version).to_dict("records"),
        )
        if outlook is not None:
            conn.execute(
                text(
                    "INSERT INTO vintage_outlook (model_version, wine_id, next_vintage, p_up, p_down, p10_pct, "
                    "p50_pct, p90_pct) VALUES (:model_version, :wine_id, :next_vintage, :p_up, :p_down, :p10_pct, "
                    ":p50_pct, :p90_pct)"
                ),
                outlook.assign(model_version=version).to_dict("records"),
            )
        if fair is not None:
            conn.execute(
                text(
                    "INSERT INTO fair_prices (model_version, wine_id, fair_p10, fair_p50, fair_p90, value_pct) "
                    "VALUES (:model_version, :wine_id, :fair_p10, :fair_p50, :fair_p90, :value_pct)"
                ),
                fair.assign(model_version=version).to_dict("records"),
            )
    print(f"Registered {version} at {artifact_uri}; loaded {len(forecasts)} forecasts; it is now the active model")


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    {"export": export, "load": load}[cmd](arg)
