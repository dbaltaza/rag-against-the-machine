"""Dense embeddings with a small CPU sentence encoder (bonus)."""

from __future__ import annotations

from typing import List, Sequence

import numpy as np
from numpy.typing import NDArray

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_encoder(model_name: str = DEFAULT_MODEL) -> object:
    """Load a sentence-transformers encoder.

    Raises:
        RuntimeError: When the optional dependency is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "sentence-transformers is not installed: run "
            "'uv sync --extra semantic'"
        ) from error
    return SentenceTransformer(model_name)


def encode_texts(
    encoder: object, texts: Sequence[str], batch_size: int = 64,
    show_progress: bool = False,
) -> NDArray[np.float32]:
    """Encode texts into L2-normalised vectors.

    Args:
        encoder: A loaded sentence-transformers model.
        texts: The texts to encode.
        batch_size: Encoding batch size.
        show_progress: Whether to display a progress bar.

    Returns:
        A (texts, dimensions) float32 matrix with unit-norm rows.
    """
    encode = getattr(encoder, "encode")
    vectors = encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=show_progress,
    )
    return np.asarray(vectors, dtype=np.float32)


def build_embeddings(
    texts: List[str], model_name: str = DEFAULT_MODEL
) -> NDArray[np.float32]:
    """Encode every chunk text with the given model."""
    encoder = load_encoder(model_name)
    return encode_texts(encoder, texts, show_progress=True)
