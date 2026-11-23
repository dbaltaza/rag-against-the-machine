"""Chunking strategies: one for Python code, one for Markdown / text."""

from src.chunking.base import chunk_file, split_by_lines
from src.chunking.markdown import chunk_markdown
from src.chunking.python import chunk_python

__all__ = ["chunk_file", "chunk_markdown", "chunk_python", "split_by_lines"]
