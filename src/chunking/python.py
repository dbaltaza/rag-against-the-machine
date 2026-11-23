"""AST-based chunking for Python source files.

The file is cut on the boundaries of top-level statements (functions,
classes, import blocks, assignments...).  Small neighbours are merged,
oversized classes are split on their methods, and anything still too large
is cut on line boundaries.  Each boundary is the end of the previous node,
so comments and decorators preceding a definition stay attached to it and
the chunks cover the whole file without gaps.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Sequence, Tuple

from src.chunking.base import Span, make_chunks, pack_spans, split_by_lines
from src.models import Chunk

NodeSpan = Tuple[Optional[ast.stmt], Span]


def _line_offsets(text: str) -> List[int]:
    """Return the character offset at which each 1-based line starts."""
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _line_end_offset(offsets: List[int], line: int, text_len: int) -> int:
    """Return the character offset just after the end of a 1-based line."""
    if line >= len(offsets):
        return text_len
    return offsets[line]


def _node_spans(
    nodes: Sequence[ast.stmt],
    region_start: int,
    region_end: int,
    offsets: List[int],
    text_len: int,
) -> List[NodeSpan]:
    """Cut a region on the end line of each statement it contains.

    Returns:
        (node, span) pairs; the trailing region after the last statement
        is attached to it, or paired with ``None`` when there is none.
    """
    spans: List[NodeSpan] = []
    cursor = region_start
    for node in nodes:
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            continue
        end = _line_end_offset(offsets, end_line, text_len)
        end = min(max(end, cursor), region_end)
        if end > cursor:
            spans.append((node, (cursor, end)))
            cursor = end
    if cursor < region_end:
        if spans:
            last_node, (start, _) = spans[-1]
            spans[-1] = (last_node, (start, region_end))
        else:
            spans.append((None, (region_start, region_end)))
    return spans


def _split_large_span(
    text: str,
    node: Optional[ast.stmt],
    span: Span,
    offsets: List[int],
    max_size: int,
    min_size: int,
) -> List[Span]:
    """Split a span that exceeds ``max_size``.

    Classes are split on their methods; everything else falls back to
    line-based splitting.
    """
    if isinstance(node, ast.ClassDef) and node.body:
        result: List[Span] = []
        for _, member_span in _node_spans(
            node.body, span[0], span[1], offsets, len(text)
        ):
            if member_span[1] - member_span[0] > max_size:
                result.extend(
                    split_by_lines(
                        text, member_span[0], member_span[1], max_size
                    )
                )
            else:
                result.append(member_span)
        return pack_spans(result, max_size, min_size)
    return split_by_lines(text, span[0], span[1], max_size)


def chunk_python(
    file_path: str, text: str, max_size: int, min_size: int = 0
) -> List[Chunk]:
    """Chunk a Python file on statement boundaries.

    Args:
        file_path: Corpus-relative path of the file.
        text: Full content of the file.
        max_size: Maximum chunk size, in characters.
        min_size: Size under which neighbouring chunks are merged.

    Returns:
        The chunks covering the file.  Files that do not parse fall back
        to a plain line-based split.
    """
    if not text.strip():
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        fallback = split_by_lines(text, 0, len(text), max_size)
        return make_chunks(file_path, text, fallback, "python")

    offsets = _line_offsets(text)
    spans: List[Span] = []
    for node, span in _node_spans(
        tree.body, 0, len(text), offsets, len(text)
    ):
        if span[1] - span[0] > max_size:
            spans.extend(
                _split_large_span(
                    text, node, span, offsets, max_size, min_size
                )
            )
        else:
            spans.append(span)
    spans = pack_spans(spans, max_size, min_size)
    return make_chunks(file_path, text, spans, "python")
