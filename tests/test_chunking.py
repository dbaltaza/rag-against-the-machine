"""Tests for both chunking strategies."""

from typing import List

from src.chunking import chunk_file, chunk_markdown, chunk_python
from src.chunking.base import split_by_lines
from src.models import Chunk
from tests.conftest import MD_FILE, PY_FILE


def _check_cover(text: str, chunks: List[Chunk], max_size: int) -> None:
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert text[
            chunk.first_character_index:chunk.last_character_index
        ] == chunk.text
        assert len(chunk.text) <= max_size
    for left, right in zip(chunks, chunks[1:]):
        assert left.last_character_index <= right.first_character_index


def test_python_chunks_follow_definitions() -> None:
    chunks = chunk_python("pkg/widgets.py", PY_FILE, 300)
    _check_cover(PY_FILE, chunks, 300)
    starts = [chunk.text.lstrip()[:20] for chunk in chunks]
    assert any(start.startswith("def load_widget") for start in starts)
    assert any(start.startswith("def register_widget") for start in starts)


def test_python_syntax_error_falls_back_to_lines() -> None:
    broken = "def broken(:\n    pass\n" * 40
    chunks = chunk_python("broken.py", broken, 100)
    _check_cover(broken, chunks, 100)


def test_markdown_chunks_follow_headings() -> None:
    chunks = chunk_markdown("docs/sprockets.md", MD_FILE, 2000)
    _check_cover(MD_FILE, chunks, 2000)
    assert [chunk.text.splitlines()[0] for chunk in chunks] == [
        "# Sprocket guide",
        "## Installing sprockets",
        "## Tuning sprockets",
    ]


def test_markdown_heading_inside_fence_is_ignored() -> None:
    chunks = chunk_markdown("docs/sprockets.md", MD_FILE, 2000)
    assert not any(
        chunk.text.startswith("# not a heading") for chunk in chunks
    )


def test_oversized_section_is_split() -> None:
    text = "# Title\n\n" + "\n\n".join(["word " * 50] * 10)
    chunks = chunk_markdown("big.md", text, 600)
    _check_cover(text, chunks, 600)
    assert len(chunks) > 1


def test_split_by_lines_handles_giant_line() -> None:
    text = "x" * 2500 + "\nshort\n"
    spans = split_by_lines(text, 0, len(text), 1000)
    assert spans[0] == (0, 1000)
    assert spans[-1][1] == len(text)


def test_unknown_extension_is_skipped() -> None:
    assert chunk_file("image.png", "binary", 2000) == []
    assert chunk_file("empty.py", "   \n", 2000) == []
