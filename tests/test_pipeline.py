"""End-to-end tests of the pipeline on a tiny corpus (no LLM)."""

import json
from pathlib import Path

import pytest

from src.io_utils import InputError
from src.models import RagDataset, StudentSearchResults, UnansweredQuestion
from src.pipeline import RagPipeline


def test_index_and_search(pipeline: RagPipeline) -> None:
    hits = pipeline.search("how to install sprockets", 3)
    assert hits and hits[0].file_path.endswith("docs/sprockets.md")
    assert "Installing sprockets" in hits[0].text
    code_hits = pipeline.search("register a widget", 3)
    assert code_hits[0].file_path.endswith("pkg/widgets.py")


def test_degenerate_queries(pipeline: RagPipeline) -> None:
    assert pipeline.search("", 3) == []
    assert pipeline.search("   ", 3) == []
    assert pipeline.search("sprocket", 0) == []
    assert pipeline.search("qqq zzz", 3) == []


def test_search_dataset_and_evaluate(
    pipeline: RagPipeline, tmp_path: Path
) -> None:
    dataset = RagDataset(
        rag_questions=[
            UnansweredQuestion(question_id="1", question="install sprockets"),
            UnansweredQuestion(question_id="2", question="count gizmos"),
        ]
    )
    dataset_path = tmp_path / "dataset_test.json"
    dataset_path.write_text(dataset.model_dump_json())
    out = pipeline.search_dataset(dataset_path, 2, tmp_path / "out")
    assert out == tmp_path / "out" / "dataset_test.json"
    results = StudentSearchResults.model_validate_json(out.read_text())
    assert results.k == 2 and len(results.search_results) == 2
    assert all(
        len(entry.retrieved_sources) <= 2 for entry in results.search_results
    )


def test_missing_and_malformed_inputs(
    pipeline: RagPipeline, tmp_path: Path
) -> None:
    with pytest.raises(InputError, match="File not found"):
        pipeline.search_dataset(tmp_path / "nope.json", 3, tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(InputError, match="RagDataset"):
        pipeline.search_dataset(bad, 3, tmp_path)
    empty = tmp_path / "empty.json"
    empty.write_text("")
    with pytest.raises(InputError, match="empty"):
        pipeline.search_dataset(empty, 3, tmp_path)


def test_missing_index(tmp_path: Path) -> None:
    pipe = RagPipeline(
        raw_directory=tmp_path, processed_directory=tmp_path / "none"
    )
    with pytest.raises(InputError, match="No index found"):
        pipe.search("anything", 3)


def test_incremental_update(pipeline: RagPipeline, corpus: Path) -> None:
    before = pipeline.retriever.manifest.chunk_count
    new_file = corpus / "repo" / "docs" / "flanges.md"
    new_file.write_text("# Flanges\n\nFlanges hold sprockets.\n")
    manifest = pipeline.index(max_chunk_size=400, incremental=True)
    assert manifest.chunk_count == before + 1
    assert pipeline.search("flanges", 1)[0].file_path.endswith("flanges.md")
    new_file.unlink()
    manifest = pipeline.index(max_chunk_size=400, incremental=True)
    assert manifest.chunk_count == before
    assert pipeline.search("flanges", 1) == []


def test_query_cache_roundtrip(pipeline: RagPipeline) -> None:
    first = pipeline.search("install sprockets", 2)
    pipeline.cache.save()
    cache_file = pipeline.cache_directory / "queries.json"
    assert cache_file.is_file()
    data = json.loads(cache_file.read_text())
    assert len(data) == 1
    again = pipeline.search("install sprockets", 2)
    assert [hit.file_path for hit in again] == [hit.file_path for hit in first]
