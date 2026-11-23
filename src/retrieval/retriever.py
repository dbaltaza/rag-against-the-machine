"""Loads the persisted index and answers queries with ranked sources."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from numpy.typing import NDArray

from src.index.bm25 import BM25Index, top_k
from src.index.store import IndexStore
from src.models import Chunk, ScoredSource

MODES: Tuple[str, ...] = ("lexical", "semantic", "hybrid")


class Retriever:
    """Ranks index chunks against a query.

    Args:
        processed_directory: Directory holding the index.
        k1: BM25 saturation parameter.
        b: BM25 length normalisation parameter.
    """

    def __init__(
        self,
        processed_directory: str | Path,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.store = IndexStore(processed_directory)
        self.chunks: List[Chunk] = self.store.load_chunks()
        self.bm25 = BM25Index(
            self.store.load_term_frequencies(),
            self.store.load_vocabulary(),
            k1=k1,
            b=b,
        )
        self.manifest = self.store.load_manifest()
        self._embeddings: Optional[NDArray[np.float32]] = None
        self._embedder: Optional[object] = None

    @property
    def has_semantic_index(self) -> bool:
        """Whether a dense embedding matrix was built for this index."""
        return self.manifest.semantic_model is not None and (
            self.store.directory / "embeddings.npy"
        ).is_file()

    def search(
        self, query: str, k: int, mode: str = "lexical"
    ) -> List[ScoredSource]:
        """Return the top-``k`` sources for a query.

        Args:
            query: The question.
            k: Number of sources wanted.
            mode: ``lexical`` (BM25), ``semantic`` (embeddings) or
                ``hybrid`` (reciprocal rank fusion of both).

        Returns:
            Ranked sources with scores; empty for blank queries or k <= 0.
        """
        if k <= 0 or not query or not query.strip():
            return []
        if mode not in MODES:
            raise ValueError(
                f"Unknown retrieval mode '{mode}', expected one of {MODES}"
            )
        if mode == "lexical":
            ranked = self.bm25.search(query, k)
        elif mode == "semantic":
            ranked = self._semantic_search(query, k)
        else:
            ranked = self._hybrid_search(query, k)
        return [self._scored(row, score) for row, score in ranked]

    def _scored(self, row: int, score: float) -> ScoredSource:
        """Build a ScoredSource from a chunk row and its score."""
        chunk = self.chunks[row]
        return ScoredSource(
            file_path=chunk.file_path,
            first_character_index=chunk.first_character_index,
            last_character_index=chunk.last_character_index,
            score=score,
            text=chunk.text,
        )

    def _load_semantic(self) -> Tuple[NDArray[np.float32], object]:
        """Load the embedding matrix and the sentence encoder lazily."""
        if self._embeddings is None:
            embeddings = self.store.load_embeddings()
            if embeddings is None or self.manifest.semantic_model is None:
                raise RuntimeError(
                    "No semantic index found: run "
                    "'index --semantic True' first"
                )
            self._embeddings = embeddings
        model_name = self.manifest.semantic_model
        if self._embedder is None and model_name is not None:
            from src.index.semantic import load_encoder

            self._embedder = load_encoder(model_name)
        if self._embedder is None:
            raise RuntimeError("No semantic model recorded in the index")
        return self._embeddings, self._embedder

    def _semantic_search(self, query: str, k: int) -> List[Tuple[int, float]]:
        """Rank chunks by cosine similarity of embeddings."""
        from src.index.semantic import encode_texts

        embeddings, encoder = self._load_semantic()
        query_vector = encode_texts(encoder, [query])[0]
        scores = embeddings @ query_vector
        return top_k(scores.astype(np.float32), k)

    def _hybrid_search(self, query: str, k: int) -> List[Tuple[int, float]]:
        """Fuse lexical and semantic rankings with reciprocal rank fusion."""
        depth = max(k * 5, 50)
        lexical = self.bm25.search(query, depth)
        semantic = self._semantic_search(query, depth)
        fused = reciprocal_rank_fusion([lexical, semantic])
        return fused[:k]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Tuple[int, float]]], constant: int = 60
) -> List[Tuple[int, float]]:
    """Merge several rankings into one with reciprocal rank fusion.

    Args:
        rankings: Lists of (document, score) pairs, best first.
        constant: The RRF smoothing constant.

    Returns:
        Fused (document, fused score) pairs, best first.
    """
    fused: Dict[int, float] = {}
    for ranking in rankings:
        for rank, (document, _) in enumerate(ranking):
            fused[document] = fused.get(document, 0.0) + 1.0 / (
                constant + rank + 1
            )
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))
