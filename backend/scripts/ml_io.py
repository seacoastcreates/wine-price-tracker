"""Move data between Postgres and the training job.

    python -m scripts.ml_io export <out.csv>          # weekly series -> CSV for ml/train.py
    python -m scripts.ml_io load <artifacts_dir>      # forecasts.csv + metrics.json -> DB, set active
"""

import json
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db import get_engine


def export(out_csv: str) -> None:
    sql = """
        SELECT p.wine_id, p.observed_on AS date, p.regular_price::float AS price,
               p.promo_price::float AS promo_price, p.promo_type, w.style, w.tier
        FROM price_observations p JOIN wines w ON w.id = p.wine_id
        ORDER BY p.wine_id, p.observed_on
    """
    with get_engine().connect() as conn:
        df = pd.read_sql(text(sql), conn)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"Exported {len(df)} rows for {df['wine_id'].nunique()} wines to {out_csv}")


def load(artifacts_dir: str) -> None:
    d = Path(artifacts_dir)
    metrics = json.loads((d / "metrics.json").read_text())
    forecasts = pd.read_csv(d / "forecasts.csv")
    version = metrics["model_version"]
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE model_runs SET is_active = FALSE WHERE is_active"))
        conn.execute(
            text(
                "INSERT INTO model_runs (model_version, algorithm, horizon, horizon_unit, metrics, is_active) "
                "VALUES (:v, :a, :h, :u, CAST(:m AS JSONB), TRUE)"
            ),
            {"v": version, "a": metrics["algorithm"], "h": metrics["horizon"], "u": metrics["horizon_unit"],
             "m": json.dumps(metrics)},
        )
        conn.execute(
            text(
                "INSERT INTO forecasts (model_version, wine_id, target_date, p10, p50, p90, p_up, p_down, up_pct, down_pct) "
                "VALUES (:model_version, :wine_id, :target_date, :p10, :p50, :p90, :p_up, :p_down, :up_pct, :down_pct)"
            ),
            forecasts.assign(model_version=version).to_dict("records"),
        )
    print(f"Loaded {len(forecasts)} forecasts; {version} is now the active model")


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    {"export": export, "load": load}[cmd](arg)
