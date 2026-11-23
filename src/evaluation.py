"""Recall@k computation, mirroring the moulinette's rules.

A reference source counts as found when one of the retrieved sources is
in the same file and overlaps it with an intersection-over-union of at
least ``MIN_IOU``.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from src.models import (
    AnsweredQuestion,
    MinimalSearchResults,
    MinimalSource,
    RagDataset,
    StudentSearchResults,
)

MIN_IOU = 0.05
DEFAULT_KS = (1, 3, 5, 10)


def interval_iou(first: MinimalSource, second: MinimalSource) -> float:
    """Intersection over union of two character spans in the same file."""
    if first.file_path != second.file_path:
        return 0.0
    start = max(first.first_character_index, second.first_character_index)
    end = min(first.last_character_index, second.last_character_index)
    intersection = max(0, end - start)
    if intersection == 0:
        return 0.0
    union = (
        first.last_character_index - first.first_character_index
    ) + (
        second.last_character_index - second.first_character_index
    ) - intersection
    return intersection / union if union > 0 else 0.0


def source_found(
    reference: MinimalSource,
    retrieved: Sequence[MinimalSource],
    min_iou: float = MIN_IOU,
) -> bool:
    """Whether a reference source is covered by any retrieved source."""
    return any(interval_iou(reference, hit) >= min_iou for hit in retrieved)


def question_recall(
    references: Sequence[MinimalSource],
    retrieved: Sequence[MinimalSource],
    k: int,
    min_iou: float = MIN_IOU,
) -> float:
    """Share of the reference sources found in the top-``k`` results."""
    if not references:
        return 0.0
    top = list(retrieved)[:k]
    found = sum(
        1 for reference in references
        if source_found(reference, top, min_iou)
    )
    return found / len(references)


def validate_results(
    results: StudentSearchResults, max_context_length: int
) -> List[str]:
    """Return the validation problems of a results file, if any."""
    problems: List[str] = []
    for entry in results.search_results:
        if len(entry.retrieved_sources) > results.k:
            problems.append(
                f"{entry.question_id}: {len(entry.retrieved_sources)} "
                f"sources exceed k={results.k}"
            )
        for source in entry.retrieved_sources:
            width = source.last_character_index - source.first_character_index
            if width > max_context_length:
                problems.append(
                    f"{entry.question_id}: source {source.file_path} is "
                    f"{width} characters wide (max {max_context_length})"
                )
            if width < 0 or source.first_character_index < 0:
                problems.append(
                    f"{entry.question_id}: invalid span in {source.file_path}"
                )
    return problems


def evaluate_recall(
    results: StudentSearchResults,
    dataset: RagDataset,
    ks: Sequence[int] = DEFAULT_KS,
    min_iou: float = MIN_IOU,
) -> Dict[int, float]:
    """Compute mean recall@k over the questions of a ground-truth dataset.

    Questions without reference sources, and questions missing from the
    student results, count as zero recall.

    Args:
        results: The student search results.
        dataset: The ground-truth dataset with answered questions.
        ks: The cut-offs to report.
        min_iou: Minimum overlap for a hit.

    Returns:
        Mapping from k to mean recall.
    """
    by_id: Dict[str, MinimalSearchResults] = {
        entry.question_id: entry for entry in results.search_results
    }
    references = [
        question for question in dataset.rag_questions
        if isinstance(question, AnsweredQuestion)
    ]
    recalls: Dict[int, float] = {}
    for k in ks:
        if k > results.k:
            continue
        total = 0.0
        for question in references:
            entry = by_id.get(question.question_id)
            retrieved = entry.retrieved_sources if entry else []
            total += question_recall(
                question.sources, retrieved, k, min_iou
            )
        recalls[k] = total / len(references) if references else 0.0
    return recalls
