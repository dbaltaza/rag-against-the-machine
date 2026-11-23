"""A sparse BM25 index built on top of scipy.

The index keeps a term-frequency matrix (documents x vocabulary).  BM25
weights are derived from it at load time, which makes the persisted file
small and lets incremental indexing replace individual rows.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from src.tokenizer import tokenize

FloatArray = NDArray[np.float32]


class BM25Index:
    """BM25 ranking over a sparse term-frequency matrix.

    Args:
        term_frequencies: CSR matrix of shape (documents, terms) with raw
            term counts.
        vocabulary: Mapping from term to column index.
        k1: Term-frequency saturation parameter.
        b: Document-length normalisation parameter.
    """

    def __init__(
        self,
        term_frequencies: sp.csr_matrix,
        vocabulary: Dict[str, int],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.term_frequencies = term_frequencies.tocsr()
        self.vocabulary = vocabulary
        self.k1 = k1
        self.b = b
        self.weights = self._compute_weights().tocsc()

    @property
    def document_count(self) -> int:
        """Number of indexed documents."""
        return int(self.term_frequencies.shape[0])

    @classmethod
    def build(
        cls,
        documents: Iterable[str],
        vocabulary: Dict[str, int] | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "BM25Index":
        """Tokenize documents and build an index from them.

        Args:
            documents: Texts to index, one per document.
            vocabulary: Existing vocabulary to extend (for incremental
                indexing).  A new one is created when omitted.
            k1: BM25 saturation parameter.
            b: BM25 length normalisation parameter.

        Returns:
            The index.
        """
        vocabulary = dict(vocabulary) if vocabulary else {}
        matrix = term_frequency_matrix(documents, vocabulary)
        return cls(matrix, vocabulary, k1=k1, b=b)

    def _compute_weights(self) -> sp.csr_matrix:
        """Compute the BM25 weight of every (document, term) pair."""
        tf = self.term_frequencies.astype(np.float32)
        doc_count = tf.shape[0]
        if doc_count == 0 or tf.nnz == 0:
            return sp.csr_matrix(tf.shape, dtype=np.float32)
        doc_lengths = np.asarray(tf.sum(axis=1)).ravel()
        average_length = float(doc_lengths.mean()) or 1.0
        document_frequency = np.diff(tf.tocsc().indptr)
        idf = np.log(
            (doc_count - document_frequency + 0.5)
            / (document_frequency + 0.5)
            + 1.0
        ).astype(np.float32)
        coo = tf.tocoo()
        length_norm = 1.0 - self.b + self.b * doc_lengths[coo.row] / (
            average_length
        )
        saturated = (
            coo.data * (self.k1 + 1.0) / (coo.data + self.k1 * length_norm)
        )
        weights = saturated * idf[coo.col]
        return sp.csr_matrix(
            (weights.astype(np.float32), (coo.row, coo.col)), shape=tf.shape
        )

    def scores(self, query: str) -> FloatArray:
        """Score every document against a query.

        Args:
            query: The natural-language query.

        Returns:
            A dense vector of BM25 scores, one per document.
        """
        counts = Counter(tokenize(query))
        scores = np.zeros(self.document_count, dtype=np.float32)
        for term, count in counts.items():
            column = self.vocabulary.get(term)
            if column is None:
                continue
            col = self.weights.getcol(column)
            scores[col.indices] += col.data * count
        return scores

    def search(self, query: str, k: int) -> List[Tuple[int, float]]:
        """Return the ``k`` best (document index, score) pairs.

        Documents with a zero score are never returned.
        """
        if k <= 0 or self.document_count == 0:
            return []
        scores = self.scores(query)
        return top_k(scores, k)


def top_k(scores: FloatArray, k: int) -> List[Tuple[int, float]]:
    """Return the indices and values of the ``k`` largest positive scores."""
    k = min(k, scores.shape[0])
    if k <= 0:
        return []
    candidates = np.argpartition(-scores, k - 1)[:k]
    ordered = candidates[np.argsort(-scores[candidates], kind="stable")]
    return [
        (int(index), float(scores[index]))
        for index in ordered
        if scores[index] > 0.0
    ]


def term_frequency_matrix(
    documents: Iterable[str], vocabulary: Dict[str, int]
) -> sp.csr_matrix:
    """Build a CSR term-frequency matrix, extending ``vocabulary`` in place.

    Args:
        documents: Texts to tokenize.
        vocabulary: Term to column mapping; unknown terms are appended.

    Returns:
        The (documents, terms) matrix of raw counts.
    """
    indptr: List[int] = [0]
    indices: List[int] = []
    data: List[int] = []
    row_count = 0
    for document in documents:
        counts = Counter(tokenize(document))
        for term, count in counts.items():
            column = vocabulary.get(term)
            if column is None:
                column = len(vocabulary)
                vocabulary[term] = column
            indices.append(column)
            data.append(count)
        indptr.append(len(indices))
        row_count += 1
    shape = (row_count, len(vocabulary))
    return sp.csr_matrix(
        (
            np.asarray(data, dtype=np.float32),
            np.asarray(indices, dtype=np.int32),
            np.asarray(indptr, dtype=np.int64),
        ),
        shape=shape,
    )


def stack_rows(
    blocks: Sequence[sp.csr_matrix], column_count: int
) -> sp.csr_matrix:
    """Vertically stack CSR blocks, padding each to ``column_count``."""
    padded = []
    for block in blocks:
        if block.shape[1] < column_count:
            block = sp.csr_matrix(
                (block.data, block.indices, block.indptr),
                shape=(block.shape[0], column_count),
            )
        padded.append(block)
    if not padded:
        return sp.csr_matrix((0, column_count), dtype=np.float32)
    return sp.vstack(padded, format="csr")
