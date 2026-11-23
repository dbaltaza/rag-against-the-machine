"""Persistence of the index under ``data/processed/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from src.models import Chunk, IndexManifest

CHUNKS_FILE = "chunks.jsonl"
TF_FILE = "term_frequencies.npz"
VOCAB_FILE = "vocabulary.json"
MANIFEST_FILE = "manifest.json"
EMBEDDINGS_FILE = "embeddings.npy"


class IndexError_(Exception):
    """Raised when the index is missing or corrupted."""


class IndexStore:
    """Reads and writes the persisted index files.

    Args:
        directory: The ``data/processed`` directory.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def exists(self) -> bool:
        """Whether a complete lexical index is present."""
        return all(
            (self.directory / name).is_file()
            for name in (CHUNKS_FILE, TF_FILE, VOCAB_FILE, MANIFEST_FILE)
        )

    def save(
        self,
        chunks: List[Chunk],
        term_frequencies: sp.csr_matrix,
        vocabulary: Dict[str, int],
        manifest: IndexManifest,
    ) -> None:
        """Persist every part of the lexical index."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / CHUNKS_FILE).open("w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(chunk.model_dump_json() + "\n")
        sp.save_npz(self.directory / TF_FILE, term_frequencies.tocsr())
        with (self.directory / VOCAB_FILE).open("w", encoding="utf-8") as f:
            json.dump(vocabulary, f)
        with (self.directory / MANIFEST_FILE).open(
            "w", encoding="utf-8"
        ) as f:
            f.write(manifest.model_dump_json(indent=2))

    def load_chunks(self) -> List[Chunk]:
        """Load the chunk list."""
        path = self.directory / CHUNKS_FILE
        chunks: List[Chunk] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        chunks.append(Chunk.model_validate_json(line))
        except (OSError, ValueError) as error:
            raise IndexError_(f"Cannot read {path}: {error}") from error
        return chunks

    def load_term_frequencies(self) -> sp.csr_matrix:
        """Load the term-frequency matrix."""
        path = self.directory / TF_FILE
        try:
            return sp.load_npz(path).tocsr()
        except (OSError, ValueError) as error:
            raise IndexError_(f"Cannot read {path}: {error}") from error

    def load_vocabulary(self) -> Dict[str, int]:
        """Load the term to column mapping."""
        path = self.directory / VOCAB_FILE
        try:
            with path.open("r", encoding="utf-8") as f:
                vocabulary = json.load(f)
        except (OSError, ValueError) as error:
            raise IndexError_(f"Cannot read {path}: {error}") from error
        if not isinstance(vocabulary, dict):
            raise IndexError_(f"{path} does not contain a mapping")
        return {str(term): int(column) for term, column in vocabulary.items()}

    def load_manifest(self) -> IndexManifest:
        """Load the manifest."""
        path = self.directory / MANIFEST_FILE
        try:
            with path.open("r", encoding="utf-8") as f:
                return IndexManifest.model_validate_json(f.read())
        except (OSError, ValueError) as error:
            raise IndexError_(f"Cannot read {path}: {error}") from error

    def save_embeddings(self, embeddings: NDArray[np.float32]) -> None:
        """Persist the dense embedding matrix (semantic bonus)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        np.save(self.directory / EMBEDDINGS_FILE, embeddings)

    def load_embeddings(self) -> Optional[NDArray[np.float32]]:
        """Load the dense embedding matrix, or None if absent."""
        path = self.directory / EMBEDDINGS_FILE
        if not path.is_file():
            return None
        try:
            return np.asarray(np.load(path), dtype=np.float32)
        except (OSError, ValueError) as error:
            raise IndexError_(f"Cannot read {path}: {error}") from error

    def delete_embeddings(self) -> None:
        """Remove a stale embedding matrix."""
        path = self.directory / EMBEDDINGS_FILE
        if path.is_file():
            path.unlink()
