"""Pydantic data models exchanged between the pipeline stages."""

from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field


class MinimalSource(BaseModel):
    """A single source location inside the indexed corpus.

    Attributes:
        file_path: Path of the file, exactly as written in the corpus
            (for example ``data/raw/vllm-0.10.1/docs/features/lora.md``).
        first_character_index: Index of the first character of the span.
        last_character_index: Index one past the last character of the span.
    """

    file_path: str
    first_character_index: int
    last_character_index: int


class UnansweredQuestion(BaseModel):
    """A question without an answer yet."""

    question_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str


class AnsweredQuestion(UnansweredQuestion):
    """A question with its reference sources and answer."""

    sources: List[MinimalSource]
    answer: str


class RagDataset(BaseModel):
    """A dataset of RAG questions, answered or not."""

    rag_questions: List[AnsweredQuestion | UnansweredQuestion]


class MinimalSearchResults(BaseModel):
    """Search results for a single question."""

    question_id: str
    question: str
    retrieved_sources: List[MinimalSource]


class MinimalAnswer(MinimalSearchResults):
    """Search results for a single question together with an answer."""

    answer: str


class StudentSearchResults(BaseModel):
    """Search results over a whole dataset."""

    search_results: List[MinimalSearchResults]
    k: int


class StudentSearchResultsAndAnswer(BaseModel):
    """Search results with generated answers over a whole dataset."""

    search_results: List[MinimalAnswer]
    k: int


class Chunk(BaseModel):
    """A chunk of text produced by the indexer.

    Attributes:
        file_path: Corpus-relative path of the file the chunk comes from.
        first_character_index: Start offset of the chunk in the file.
        last_character_index: End offset (exclusive) of the chunk.
        text: Raw text of the chunk.
        kind: Chunking strategy that produced the chunk (``python`` or
            ``markdown``).
    """

    file_path: str
    first_character_index: int
    last_character_index: int
    text: str
    kind: str

    def to_source(self) -> MinimalSource:
        """Convert the chunk to a MinimalSource."""
        return MinimalSource(
            file_path=self.file_path,
            first_character_index=self.first_character_index,
            last_character_index=self.last_character_index,
        )


class ScoredSource(MinimalSource):
    """A source with its retrieval score and the chunk text."""

    score: float
    text: str = ""

    def to_minimal(self) -> MinimalSource:
        """Drop the score and text, keeping only the location."""
        return MinimalSource(
            file_path=self.file_path,
            first_character_index=self.first_character_index,
            last_character_index=self.last_character_index,
        )


class IndexManifest(BaseModel):
    """Metadata persisted next to the index."""

    max_chunk_size: int
    raw_directory: str
    chunk_count: int
    file_count: int
    file_hashes: dict[str, str] = Field(default_factory=dict)
    semantic_model: Optional[str] = None
