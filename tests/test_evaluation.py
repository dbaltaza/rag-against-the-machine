"""Tests for the recall@k computation."""

from src.evaluation import (
    evaluate_recall,
    interval_iou,
    question_recall,
    validate_results,
)
from src.models import (
    AnsweredQuestion,
    MinimalSearchResults,
    MinimalSource,
    RagDataset,
    StudentSearchResults,
)


def _src(path: str, start: int, end: int) -> MinimalSource:
    return MinimalSource(
        file_path=path, first_character_index=start, last_character_index=end
    )


def test_iou_requires_same_file() -> None:
    assert interval_iou(_src("a", 0, 100), _src("b", 0, 100)) == 0.0
    assert interval_iou(_src("a", 0, 100), _src("a", 50, 150)) == 50 / 150
    assert interval_iou(_src("a", 0, 100), _src("a", 100, 200)) == 0.0


def test_question_recall_uses_top_k_only() -> None:
    reference = [_src("a", 0, 100)]
    retrieved = [_src("b", 0, 10), _src("a", 90, 190)]
    assert question_recall(reference, retrieved, 1) == 0.0
    assert question_recall(reference, retrieved, 2) == 1.0


def test_evaluate_recall_and_validation() -> None:
    dataset = RagDataset(
        rag_questions=[
            AnsweredQuestion(
                question_id="q1", question="?", answer="!",
                sources=[_src("a", 0, 100)],
            ),
            AnsweredQuestion(
                question_id="q2", question="?", answer="!",
                sources=[_src("b", 0, 100)],
            ),
        ]
    )
    results = StudentSearchResults(
        search_results=[
            MinimalSearchResults(
                question_id="q1", question="?",
                retrieved_sources=[_src("a", 10, 60)],
            ),
            MinimalSearchResults(
                question_id="q2", question="?",
                retrieved_sources=[_src("c", 0, 3000)],
            ),
        ],
        k=5,
    )
    recalls = evaluate_recall(results, dataset, ks=(1, 5, 10))
    assert recalls == {1: 0.5, 5: 0.5}
    problems = validate_results(results, 2000)
    assert len(problems) == 1 and "3000" in problems[0]
