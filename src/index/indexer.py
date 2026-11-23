"""Walks the raw corpus, chunks every file and builds the index."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import scipy.sparse as sp
from tqdm import tqdm

from src.chunking import chunk_file
from src.chunking.base import strategy_for
from src.index.bm25 import stack_rows, term_frequency_matrix
from src.index.store import IndexStore
from src.models import Chunk, IndexManifest

DEFAULT_EXCLUDED_DIRS: Tuple[str, ...] = (
    ".git",
    ".github",
    ".buildkite",
    "tests",
    "benchmarks",
    "__pycache__",
)


PATH_WEIGHT = 2


def index_text_for(chunk: Chunk, path_weight: int | None = None) -> str:
    """Text actually indexed for a chunk: its path followed by its body.

    Prepending the path lets a question that names a module or a doc page
    (``triton_flash_attention``, ``lora``) match every chunk of that file.
    The path is repeated ``path_weight`` times to boost those terms.
    """
    if path_weight is None:
        path_weight = PATH_WEIGHT
    relative = chunk.file_path.split("/", 2)[-1]
    header = "\n".join([relative] * max(path_weight, 0))
    return f"{header}\n{chunk.text}"


def file_digest(text: str) -> str:
    """Return a stable digest of a file content."""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def read_text(path: Path) -> Optional[str]:
    """Read a file as UTF-8, returning None when it cannot be decoded."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


class Indexer:
    """Builds the lexical index from a raw corpus directory.

    Args:
        raw_directory: Root of the corpus (``data/raw``).
        processed_directory: Where the index is written
            (``data/processed``).
        max_chunk_size: Maximum chunk size in characters.
        min_chunk_size: Size under which neighbouring chunks are merged.
        excluded_dirs: Directory names skipped during the walk.
    """

    def __init__(
        self,
        raw_directory: str | Path,
        processed_directory: str | Path,
        max_chunk_size: int = 2000,
        min_chunk_size: int = 800,
        excluded_dirs: Sequence[str] = DEFAULT_EXCLUDED_DIRS,
    ) -> None:
        self.raw_directory = Path(raw_directory)
        self.store = IndexStore(processed_directory)
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min(min_chunk_size, max_chunk_size)
        self.excluded_dirs: Set[str] = set(excluded_dirs)

    def corpus_files(self) -> List[Path]:
        """List the indexable files of the corpus, sorted."""
        files: List[Path] = []
        for path in self.raw_directory.rglob("*"):
            if not path.is_file() or strategy_for(path.name) is None:
                continue
            relative_parts = path.relative_to(self.raw_directory).parts
            if any(part in self.excluded_dirs for part in relative_parts):
                continue
            files.append(path)
        return sorted(files)

    def corpus_path(self, path: Path) -> str:
        """Corpus-relative path with forward slashes, as graded."""
        return path.as_posix()

    def chunk_paths(
        self, paths: Iterable[Path], description: str
    ) -> Tuple[List[Chunk], Dict[str, str]]:
        """Chunk the given files and return the chunks and their digests."""
        chunks: List[Chunk] = []
        digests: Dict[str, str] = {}
        for path in tqdm(list(paths), desc=description, unit="file"):
            text = read_text(path)
            if text is None:
                continue
            corpus_path = self.corpus_path(path)
            digests[corpus_path] = file_digest(text)
            chunks.extend(
                chunk_file(
                    corpus_path, text, self.max_chunk_size,
                    self.min_chunk_size,
                )
            )
        return chunks, digests

    def build(self) -> IndexManifest:
        """Index the whole corpus from scratch.

        Returns:
            The manifest of the index that was written.
        """
        started = time.perf_counter()
        files = self.corpus_files()
        chunks, digests = self.chunk_paths(files, "Chunking")
        vocabulary: Dict[str, int] = {}
        matrix = term_frequency_matrix(
            tqdm(
                (index_text_for(chunk) for chunk in chunks),
                total=len(chunks),
                desc="Tokenizing",
                unit="chunk",
            ),
            vocabulary,
        )
        manifest = IndexManifest(
            max_chunk_size=self.max_chunk_size,
            raw_directory=self.raw_directory.as_posix(),
            chunk_count=len(chunks),
            file_count=len(digests),
            file_hashes=digests,
        )
        self.store.save(chunks, matrix, vocabulary, manifest)
        self.store.delete_embeddings()
        elapsed = time.perf_counter() - started
        print(
            f"Indexed {len(digests)} files into {len(chunks)} chunks "
            f"in {elapsed:.1f}s"
        )
        return manifest

    def update(self) -> IndexManifest:
        """Re-index only the files that changed since the last build.

        Unchanged files keep their chunks and their rows in the
        term-frequency matrix; new, modified and deleted files are
        re-chunked or dropped.  Falls back to a full build when no index
        exists or its chunk size differs.

        Returns:
            The manifest of the updated index.
        """
        if not self.store.exists():
            print("No existing index: building from scratch")
            return self.build()
        manifest = self.store.load_manifest()
        if manifest.max_chunk_size != self.max_chunk_size:
            print("Chunk size changed: building from scratch")
            return self.build()
        started = time.perf_counter()
        files = self.corpus_files()
        current_paths = {self.corpus_path(path): path for path in files}
        changed: List[Path] = []
        for corpus_path, path in tqdm(
            current_paths.items(), desc="Scanning", unit="file"
        ):
            text = read_text(path)
            if text is None:
                continue
            if manifest.file_hashes.get(corpus_path) != file_digest(text):
                changed.append(path)
        removed = set(manifest.file_hashes) - set(current_paths)
        stale = removed | {self.corpus_path(path) for path in changed}
        if not stale:
            print("Index is up to date")
            return manifest

        old_chunks = self.store.load_chunks()
        old_matrix = self.store.load_term_frequencies()
        vocabulary = self.store.load_vocabulary()
        keep = [
            row for row, chunk in enumerate(old_chunks)
            if chunk.file_path not in stale
        ]
        kept_chunks = [old_chunks[row] for row in keep]
        kept_matrix = old_matrix[keep]
        new_chunks, new_digests = self.chunk_paths(changed, "Re-chunking")
        new_matrix = term_frequency_matrix(
            (index_text_for(chunk) for chunk in new_chunks), vocabulary
        )
        matrix: sp.csr_matrix = stack_rows(
            [kept_matrix, new_matrix], len(vocabulary)
        )
        chunks = kept_chunks + new_chunks
        hashes = {
            path: digest
            for path, digest in manifest.file_hashes.items()
            if path not in stale
        }
        hashes.update(new_digests)
        manifest = IndexManifest(
            max_chunk_size=self.max_chunk_size,
            raw_directory=self.raw_directory.as_posix(),
            chunk_count=len(chunks),
            file_count=len(hashes),
            file_hashes=hashes,
        )
        self.store.save(chunks, matrix, vocabulary, manifest)
        self.store.delete_embeddings()
        elapsed = time.perf_counter() - started
        print(
            f"Re-indexed {len(changed)} changed and dropped {len(removed)} "
            f"removed files in {elapsed:.1f}s ({len(chunks)} chunks)"
        )
        return manifest
