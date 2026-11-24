"""Tests for the workbench server (no LLM)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.pipeline import RagPipeline
from workbench.server import create_app


def _dataset(tmp_path: Path, corpus: Path) -> Path:
    """Write a one-question ground-truth dataset about sprockets."""
    md = (corpus / "repo" / "docs" / "sprockets.md").as_posix()
    text = (corpus / "repo" / "docs" / "sprockets.md").read_text()
    start = text.index("## Installing")
    answered = tmp_path / "datasets" / "AnsweredQuestions"
    answered.mkdir(parents=True)
    dataset = {
        "rag_questions": [{
            "question_id": "q1",
            "question": "How do I install sprockets?",
            "answer": "pip install sprocket",
            "sources": [{
                "file_path": md,
                "first_character_index": start,
                "last_character_index": start + 60,
            }],
        }]
    }
    (answered / "demo.json").write_text(json.dumps(dataset))
    return tmp_path / "datasets"


def test_workbench_page(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    page = client.get("/")
    assert page.status_code == 200
    assert "RAG Workbench" in page.text


def test_explore_returns_text_and_score(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    hits = client.post(
        "/explore", json={"query": "install sprockets", "k": 2}
    ).json()
    assert hits and hits[0]["score"] > 0
    assert "sprocket" in hits[0]["text"]


def test_file_endpoint_stays_in_corpus(
    pipeline: RagPipeline, corpus: Path, tmp_path: Path
) -> None:
    client = TestClient(create_app(pipeline))
    md = (corpus / "repo" / "docs" / "sprockets.md").as_posix()
    ok = client.get("/file", params={"path": md})
    assert ok.status_code == 200 and "Sprocket guide" in ok.json()["text"]
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    outside = client.get("/file", params={"path": str(secret)})
    assert outside.status_code == 403
    escape = client.get(
        "/file", params={"path": str(corpus / ".." / "secret.txt")}
    )
    assert escape.status_code == 403
    missing = client.get("/file", params={"path": str(corpus / "x.md")})
    assert missing.status_code == 404


def test_evaluate_dataset(
    pipeline: RagPipeline, corpus: Path, tmp_path: Path
) -> None:
    client = TestClient(create_app(pipeline, _dataset(tmp_path, corpus)))
    assert client.get("/datasets").json() == ["demo.json"]
    body = client.post(
        "/evaluate", json={"dataset": "demo.json", "k": 3}
    ).json()
    assert set(body["recall"]) == {"1", "3"}
    question = body["questions"][0]
    assert question["references"][0]["found_at"] == 1
    assert body["recall"]["1"] == 1.0
    unknown = client.post("/evaluate", json={"dataset": "../x.json"})
    assert unknown.status_code == 404


def test_index_and_cache_endpoints(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    body = client.post("/index", json={"incremental": True}).json()
    assert body["chunks"] > 0 and body["max_chunk_size"] == 2000
    too_big = client.post("/index", json={"max_chunk_size": 5000})
    assert too_big.status_code == 422
    assert client.post("/cache/clear").json() == {"status": "cleared"}


def test_static_assets(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_learn_tokenize_and_chunk(
    pipeline: RagPipeline, corpus: Path
) -> None:
    client = TestClient(create_app(pipeline))
    words = client.post(
        "/learn/tokenize", json={"text": "the max_num_seqs"}
    ).json()
    assert words[0] == {"word": "the", "tokens": []}
    assert words[1]["tokens"] == ["max_num_seqs", "max", "num", "seqs"]
    py = (corpus / "repo" / "pkg" / "widgets.py").as_posix()
    preview = client.post(
        "/learn/chunk",
        json={"path": py, "max_chunk_size": 200, "min_chunk_size": 0},
    ).json()
    assert preview["strategy"] == "python"
    assert all(c["size"] <= 200 for c in preview["chunks"])
    assert preview["chunks"][-1]["last_character_index"] <= preview["length"]
    outside = client.post("/learn/chunk", json={"path": "/etc/hosts"})
    assert outside.status_code == 403


def test_learn_bm25_breakdown_adds_up(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    body = client.post(
        "/learn/bm25", json={"query": "register widget gizmo", "k": 3}
    ).json()
    assert body["hits"], body
    for hit in body["hits"]:
        total = sum(term["contribution"] for term in hit["terms"])
        assert abs(total - hit["score"]) < 1e-3
    files = client.get("/learn/files", params={"q": "widgets"}).json()
    assert files and files[0].endswith("widgets.py")


def test_favicon(pipeline: RagPipeline) -> None:
    client = TestClient(create_app(pipeline))
    ico = client.get("/favicon.ico")
    assert ico.status_code == 200
    assert ico.headers["content-type"] == "image/x-icon"
    assert client.get("/static/favicon.svg").status_code == 200
    assert client.get("/static/apple-touch-icon.png").status_code == 200
