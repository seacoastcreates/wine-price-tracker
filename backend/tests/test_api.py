from fastapi.testclient import TestClient

from app.db import query
from app.main import app

client = TestClient(app)


def active_slug() -> str:
    return query("SELECT slug FROM wines WHERE is_active AND vintage <> 'NV' ORDER BY slug LIMIT 1")[0]["slug"]


def test_live_prediction_shape():
    r = client.get(f"/wines/{active_slug()}/predict")
    assert r.status_code == 200
    body = r.json()
    assert len(body["baseline"]) == 4 and body["scenario"] is None
    for p in body["baseline"]:
        assert 0 <= p["p_up"] <= 1 and 0 <= p["p_down"] <= 1
        assert p["p10"] <= p["p50"] <= p["p90"]


def test_scenario_changes_prediction():
    slug = active_slug()
    r = client.post(f"/wines/{slug}/predict", json={"promo": "clearance", "discount_pct": 40})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario"] != body["baseline"]
    assert body["applied"]["promo"] == "clearance"


def test_scenario_validation():
    r = client.post(f"/wines/{active_slug()}/predict", json={"promo": "sale"})
    assert r.status_code == 422


def test_delisted_wine_cannot_be_predicted():
    slug = query("SELECT slug FROM wines WHERE NOT is_active LIMIT 1")[0]["slug"]
    assert client.get(f"/wines/{slug}/predict").status_code == 409


def test_unknown_wine():
    assert client.get("/wines/not-a-wine/predict").status_code == 404
