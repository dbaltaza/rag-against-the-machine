"""Helpers shared by both chunking strategies."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List, Tuple

from src.models import Chunk

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".rst", ".markdown"})

Span = Tuple[int, int]


def split_by_lines(
    text: str, start: int, end: int, max_size: int
) -> List[Span]:
    """Split ``text[start:end]`` into spans of at most ``max_size``.

    Cuts happen on line boundaries whenever possible.  A single line longer
    than ``max_size`` is cut at character granularity.

    Args:
        text: The full file content.
        start: Start offset of the region to split.
        end: End offset (exclusive) of the region to split.
        max_size: Maximum size of a span, in characters.

    Returns:
        A list of contiguous spans covering ``[start, end)``.
    """
    if end - start <= max_size:
        return [(start, end)] if end > start else []
    spans: List[Span] = []
    cursor = start
    window_start = start
    while cursor < end:
        newline = text.find("\n", cursor, end)
        line_end = end if newline == -1 else newline + 1
        if line_end - window_start > max_size:
            if window_start < cursor:
                spans.append((window_start, cursor))
                window_start = cursor
            while line_end - window_start > max_size:
                spans.append((window_start, window_start + max_size))
                window_start += max_size
        cursor = line_end
    if window_start < end:
        spans.append((window_start, end))
    return spans


def pack_spans(
    spans: List[Span], max_size: int, min_size: int
) -> List[Span]:
    """Greedily merge consecutive spans that are too small.

    Two neighbours are merged when the current accumulated span is still
    shorter than ``min_size`` and the merged span fits in ``max_size``.

    Args:
        spans: Contiguous, ordered spans.
        max_size: Maximum size of a merged span.
        min_size: Size under which a span is considered too small.

    Returns:
        The packed spans, still contiguous and ordered.
    """
    packed: List[Span] = []
    for span in spans:
        if not packed:
            packed.append(span)
            continue
        current_start, current_end = packed[-1]
        if (
            current_end - current_start < min_size
            and span[1] - current_start <= max_size
        ):
            packed[-1] = (current_start, span[1])
        else:
            packed.append(span)
    return packed


def make_chunks(
    file_path: str, text: str, spans: List[Span], kind: str
) -> List[Chunk]:
    """Turn spans into Chunk objects, dropping blank ones."""
    chunks: List[Chunk] = []
    for start, end in spans:
        piece = text[start:end]
        if not piece.strip():
            continue
        chunks.append(
            Chunk(
                file_path=file_path,
                first_character_index=start,
                last_character_index=end,
                text=piece,
                kind=kind,
            )
        )
    return chunks


def strategy_for(file_path: str) -> str | None:
    """Return the chunking strategy name for a path, or None to skip it."""
    suffix = PurePosixPath(file_path).suffix.lower()
    if suffix in PYTHON_SUFFIXES:
        return "python"
    if suffix in TEXT_SUFFIXES:
        return "markdown"
    return None


def chunk_file(
    file_path: str, text: str, max_size: int, min_size: int = 0
) -> List[Chunk]:
    """Chunk a file with the strategy matching its extension.

    Args:
        file_path: Corpus-relative path of the file.
        text: Full content of the file.
        max_size: Maximum chunk size, in characters.
        min_size: Size under which neighbouring chunks are merged.

    Returns:
        The chunks, or an empty list for unsupported file types.
    """
    from src.chunking.markdown import chunk_markdown
    from src.chunking.python import chunk_python

    strategy = strategy_for(file_path)
    if strategy == "python":
        return chunk_python(file_path, text, max_size, min_size)
    if strategy == "markdown":
        return chunk_markdown(file_path, text, max_size, min_size)
    return []
