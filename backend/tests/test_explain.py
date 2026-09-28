"""Explanation endpoints with Bedrock replaced by a fake client (no AWS calls, no cost)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import explain
from app.db import get_engine, query
from app.main import app

client = TestClient(app)
SLUG = "caymus-vineyards-cabernet-sauvignon-napa-valley-750ml-2020"


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": " A grounded explanation. "}]}},
                "usage": {"inputTokens": 400, "outputTokens": 60}}


@pytest.fixture
def fake(monkeypatch):
    fake = FakeBedrock()
    monkeypatch.setattr(explain, "_client", lambda: fake)
    explain._recent.clear()
    wine_id = query("SELECT id FROM wines WHERE slug = :s", s=SLUG)[0]["id"]
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM explanations WHERE wine_id = :w"), {"w": wine_id})
    yield fake
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM explanations WHERE wine_id = :w"), {"w": wine_id})


def test_generate_then_cached(fake):
    assert client.get(f"/wines/{SLUG}/explanation").status_code == 404
    first = client.post(f"/wines/{SLUG}/explanation").json()
    assert first["text"] == "A grounded explanation." and first["cached"] is False
    second = client.post(f"/wines/{SLUG}/explanation").json()
    assert second["cached"] is True and len(fake.calls) == 1
    assert client.get(f"/wines/{SLUG}/explanation").json()["cached"] is True


def test_request_is_grounded_and_bounded(fake):
    client.post(f"/wines/{SLUG}/explanation")
    call = fake.calls[0]
    assert call["inferenceConfig"]["maxTokens"] == 300
    prompt = call["messages"][0]["content"][0]["text"]
    assert "Caymus" in prompt and "Fair price" in prompt and "drinking window" in prompt


def test_rate_limit(fake, monkeypatch):
    monkeypatch.setattr(explain, "MAX_PER_HOUR", 0)
    assert client.post(f"/wines/{SLUG}/explanation").status_code == 429


def test_unknown_wine():
    assert client.post("/wines/not-a-wine/explanation").status_code == 404
