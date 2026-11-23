"""Heading-based chunking for Markdown and plain-text files.

A Markdown page is cut on its headings (outside fenced code blocks), so a
chunk is a section: heading plus body.  Sections that exceed the maximum
size are split on paragraph boundaries, keeping fenced code blocks whole
whenever they fit.  Plain-text files have no headings and go straight to
the paragraph splitter.
"""

from __future__ import annotations

import re
from typing import List

from src.chunking.base import Span, make_chunks, pack_spans, split_by_lines
from src.models import Chunk

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _line_starts(text: str) -> List[int]:
    """Return the start offset of every line (plus the text length)."""
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    if starts[-1] != len(text):
        starts.append(len(text))
    return starts


def _section_spans(text: str) -> List[Span]:
    """Cut the text on headings that are outside fenced code blocks."""
    starts = _line_starts(text)
    boundaries: List[int] = [0]
    in_fence = False
    for line_start, line_end in zip(starts, starts[1:]):
        line = text[line_start:line_end]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and _HEADING_RE.match(line) and line_start > 0:
            boundaries.append(line_start)
    boundaries.append(len(text))
    return [
        (start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end > start
    ]


def _paragraph_spans(text: str, start: int, end: int) -> List[Span]:
    """Cut a region on blank lines, keeping fenced code blocks whole."""
    spans: List[Span] = []
    cursor = start
    paragraph_start = start
    in_fence = False
    while cursor < end:
        newline = text.find("\n", cursor, end)
        line_end = end if newline == -1 else newline + 1
        line = text[cursor:line_end]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and not line.strip() and paragraph_start < cursor:
            spans.append((paragraph_start, line_end))
            paragraph_start = line_end
        cursor = line_end
    if paragraph_start < end:
        spans.append((paragraph_start, end))
    return spans


def _split_section(
    text: str, span: Span, max_size: int, min_size: int
) -> List[Span]:
    """Split an oversized section on paragraphs, then on lines."""
    pieces: List[Span] = []
    for paragraph in _paragraph_spans(text, span[0], span[1]):
        if paragraph[1] - paragraph[0] > max_size:
            pieces.extend(
                split_by_lines(text, paragraph[0], paragraph[1], max_size)
            )
        else:
            pieces.append(paragraph)
    return pack_spans(pieces, max_size, max(min_size, max_size // 2))


def chunk_markdown(
    file_path: str, text: str, max_size: int, min_size: int = 0
) -> List[Chunk]:
    """Chunk a Markdown or text file on headings and paragraphs.

    Args:
        file_path: Corpus-relative path of the file.
        text: Full content of the file.
        max_size: Maximum chunk size, in characters.
        min_size: Size under which neighbouring sections are merged.

    Returns:
        The chunks covering the file.
    """
    if not text.strip():
        return []
    spans: List[Span] = []
    for section in _section_spans(text):
        if section[1] - section[0] > max_size:
            spans.extend(_split_section(text, section, max_size, min_size))
        else:
            spans.append(section)
    spans = pack_spans(spans, max_size, min_size)
    return make_chunks(file_path, text, spans, "markdown")
