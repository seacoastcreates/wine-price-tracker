"""Online inference must reproduce the batch forecasts written by the training job.

Both paths call wineprice.WinePriceModel.forecast, so any difference means training/serving
skew (e.g. a feature computed differently, or a stale model/artifact). Requires a loaded DB.
"""

import pytest

from app import inference
from app.db import query

SAMPLE = 40


@pytest.fixture(scope="module")
def sample_wines() -> list[dict]:
    return query(
        """
        SELECT w.slug, w.id FROM wines w
        WHERE w.is_active AND EXISTS (SELECT 1 FROM forecasts f WHERE f.wine_id = w.id)
        ORDER BY md5(w.slug) LIMIT :n
        """,
        n=SAMPLE,
    )


def test_online_matches_batch(sample_wines):
    assert sample_wines, "no forecasts in the database; run the training pipeline first"
    for wine in sample_wines:
        online = inference.predict(wine["slug"])
        batch = query(
            """
            SELECT f.target_date, f.p10::float p10, f.p50::float p50, f.p90::float p90, f.p_up, f.p_down
            FROM forecasts f JOIN model_runs m USING (model_version)
            WHERE m.is_active AND f.wine_id = :id ORDER BY f.target_date
            """,
            id=wine["id"],
        )
        assert [p["date"] for p in online["baseline"]] == [b["target_date"] for b in batch], wine["slug"]
        for o, b in zip(online["baseline"], batch):
            for k in ("p10", "p50", "p90"):
                assert o[k] == pytest.approx(b[k], abs=0.011), (wine["slug"], k)
            for k in ("p_up", "p_down"):
                assert o[k] == pytest.approx(b[k], abs=1e-4), (wine["slug"], k)
