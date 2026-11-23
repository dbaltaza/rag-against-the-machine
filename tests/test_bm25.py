"""Tests for the BM25 index."""

from src.index.bm25 import BM25Index


def test_relevant_document_ranks_first() -> None:
    index = BM25Index.build(
        [
            "sprockets are installed with pip install sprocket",
            "widgets are loaded from disk",
            "gizmos count the registered widgets",
        ]
    )
    ranked = index.search("how do I install sprockets", 3)
    assert ranked[0][0] == 0
    assert all(score > 0 for _, score in ranked)


def test_unknown_terms_and_zero_k() -> None:
    index = BM25Index.build(["alpha beta", "gamma"])
    assert index.search("zzz", 5) == []
    assert index.search("alpha", 0) == []


def test_empty_index() -> None:
    index = BM25Index.build([])
    assert index.search("anything", 3) == []
