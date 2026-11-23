"""Tests for the local HTTP API (search only, no LLM)."""

from fastapi.testclient import TestClient

from src.api import create_app
from src.pipeline import RagPipeline


def test_health_and_search(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["chunks"] > 0
    response = client.post(
        "/search", json={"query": "install sprockets", "k": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_sources"][0]["file_path"].endswith("sprockets.md")


def test_api_validation(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    empty = client.post("/search", json={"query": "", "k": 2})
    assert empty.status_code == 422
    negative = client.post("/search", json={"query": "x", "k": -1})
    assert negative.status_code == 422
    bad_mode = client.post("/search", json={"query": "x", "mode": "nope"})
    assert bad_mode.status_code == 422
