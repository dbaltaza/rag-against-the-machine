"""Shared fixtures: a tiny corpus and an index built from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline import RagPipeline

PY_FILE = '''"""A module about widgets."""

import os


def load_widget(path: str) -> str:
    """Load a widget from disk."""
    with open(path) as f:
        return f.read()


class WidgetRegistry:
    """Keeps every registered widget."""

    def __init__(self) -> None:
        self.widgets: dict[str, str] = {}

    def register_widget(self, name: str, body: str) -> None:
        """Register a widget under a name."""
        self.widgets[name] = body

    def gizmo_count(self) -> int:
        """Return how many gizmos were registered."""
        return len([n for n in self.widgets if "gizmo" in n])
'''

MD_FILE = '''# Sprocket guide

Sprockets are configured through the `SPROCKET_LEVEL` variable.

## Installing sprockets

Run `pip install sprocket` to install the sprocket package.

```bash
# not a heading
pip install sprocket
```

## Tuning sprockets

Set the tension with `--tension` on the command line.
'''


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """Write a two-file corpus under ``tmp_path/data/raw``."""
    raw = tmp_path / "data" / "raw" / "repo"
    (raw / "pkg").mkdir(parents=True)
    (raw / "docs").mkdir(parents=True)
    (raw / "pkg" / "widgets.py").write_text(PY_FILE, encoding="utf-8")
    (raw / "docs" / "sprockets.md").write_text(MD_FILE, encoding="utf-8")
    (raw / "image.png").write_bytes(b"\x89PNG\r\n")
    return tmp_path / "data" / "raw"


@pytest.fixture()
def pipeline(corpus: Path, tmp_path: Path) -> RagPipeline:
    """A pipeline whose index was built from the tiny corpus."""
    pipe = RagPipeline(
        raw_directory=corpus,
        processed_directory=tmp_path / "data" / "processed",
        cache_directory=tmp_path / "data" / "cache",
    )
    pipe.index(max_chunk_size=400)
    return pipe
