"""Explanations of each pipeline stage, used by the workbench's guide.

Every function here runs the project's real code on a small input and
returns the intermediate values that are normally thrown away: the tokens
of each word, the chunk boundaries of a file, the BM25 contribution of each
query term, and the prompt handed to the language model.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence

import numpy as np
from pydantic import BaseModel

from src.chunking import chunk_file
from src.chunking.base import strategy_for
from src.generation import Generator
from src.index.bm25 import BM25Index
from src.index.indexer import index_text_for
from src.models import Chunk, ScoredSource
from src.tokenizer import tokenize

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


class WordTokens(BaseModel):
    """One word of the input and the tokens it produced."""

    word: str
    tokens: List[str]


class ChunkSpan(BaseModel):
    """One chunk of a previewed file."""

    first_character_index: int
    last_character_index: int
    size: int


class ChunkPreview(BaseModel):
    """How a file is cut with the given sizes."""

    file_path: str
    strategy: Optional[str]
    length: int
    text: str
    chunks: List[ChunkSpan]


class QueryTerm(BaseModel):
    """A query token and its corpus statistics."""

    term: str
    count: int
    in_vocabulary: bool
    document_frequency: int
    idf: float


class TermScore(BaseModel):
    """The share of a hit's score that one query term contributed."""

    term: str
    tf: int
    weight: float
    contribution: float


class ExplainedHit(BaseModel):
    """A retrieved chunk with its score broken down by term."""

    file_path: str
    first_character_index: int
    last_character_index: int
    score: float
    length: int
    terms: List[TermScore]
    text: str


class BM25Explanation(BaseModel):
    """The full breakdown of a lexical search."""

    k1: float
    b: float
    documents: int
    average_length: float
    terms: List[QueryTerm]
    hits: List[ExplainedHit]


class PromptSource(BaseModel):
    """A retrieved source and whether it fit in the token budget."""

    file_path: str
    first_character_index: int
    last_character_index: int
    tokens: int
    included: bool


class PromptPreview(BaseModel):
    """The prompt the model would receive for a question."""

    prompt: str
    prompt_tokens: int
    budget: int
    sources: List[PromptSource]


def explain_tokens(text: str) -> List[WordTokens]:
    """Tokenize each word separately so the effect of every rule shows.

    ``tokenize`` treats words independently, so the concatenation of the
    per-word tokens equals ``tokenize(text)``.
    """
    return [
        WordTokens(word=match.group(0), tokens=tokenize(match.group(0)))
        for match in _WORD_RE.finditer(text)
    ]


def preview_chunks(
    file_path: str, text: str, max_size: int, min_size: int
) -> ChunkPreview:
    """Chunk a file exactly as the indexer would, with custom sizes."""
    min_size = min(min_size, max_size)
    chunks: List[Chunk] = chunk_file(file_path, text, max_size, min_size)
    return ChunkPreview(
        file_path=file_path,
        strategy=strategy_for(file_path),
        length=len(text),
        text=text,
        chunks=[
            ChunkSpan(
                first_character_index=chunk.first_character_index,
                last_character_index=chunk.last_character_index,
                size=(
                    chunk.last_character_index - chunk.first_character_index
                ),
            )
            for chunk in chunks
        ],
    )


def explain_bm25(
    bm25: BM25Index, chunks: Sequence[Chunk], query: str, k: int
) -> BM25Explanation:
    """Rank chunks for a query and split each score by query term."""
    tf_matrix = bm25.term_frequencies
    lengths = np.asarray(tf_matrix.sum(axis=1)).ravel()
    average = float(lengths.mean()) if lengths.size else 0.0
    doc_count = bm25.document_count
    frequencies = np.diff(bm25.weights.indptr)
    counts = Counter(tokenize(query))
    terms: List[QueryTerm] = []
    for term, count in counts.items():
        column = bm25.vocabulary.get(term)
        df = int(frequencies[column]) if column is not None else 0
        idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
        terms.append(
            QueryTerm(
                term=term,
                count=count,
                in_vocabulary=column is not None,
                document_frequency=df,
                idf=round(idf, 4),
            )
        )
    hits: List[ExplainedHit] = []
    for row, score in bm25.search(query, k):
        parts: List[TermScore] = []
        for query_term in terms:
            column = bm25.vocabulary.get(query_term.term)
            if column is None:
                continue
            tf = int(tf_matrix[row, column])
            weight = float(bm25.weights[row, column])
            if tf == 0:
                continue
            parts.append(
                TermScore(
                    term=query_term.term,
                    tf=tf,
                    weight=round(weight, 4),
                    contribution=round(weight * query_term.count, 4),
                )
            )
        chunk = chunks[row]
        hits.append(
            ExplainedHit(
                file_path=chunk.file_path,
                first_character_index=chunk.first_character_index,
                last_character_index=chunk.last_character_index,
                score=round(score, 4),
                length=int(lengths[row]),
                terms=parts,
                text=index_text_for(chunk),
            )
        )
    return BM25Explanation(
        k1=bm25.k1,
        b=bm25.b,
        documents=doc_count,
        average_length=round(average, 2),
        terms=terms,
        hits=hits,
    )


def preview_prompt(
    generator: Generator, question: str, sources: Sequence[ScoredSource]
) -> PromptPreview:
    """Build the exact prompt and report which sources fit the budget."""
    prompt = generator.build_prompt(question, sources)
    context = generator.build_context(sources)
    rows: List[PromptSource] = []
    for rank, source in enumerate(sources, start=1):
        header = f"[Source {rank}] {source.file_path} "
        block = (
            f"{header}(chars {source.first_character_index}-"
            f"{source.last_character_index})\n{source.text.strip()}\n"
        )
        rows.append(
            PromptSource(
                file_path=source.file_path,
                first_character_index=source.first_character_index,
                last_character_index=source.last_character_index,
                tokens=generator.count_tokens(block),
                included=header in context,
            )
        )
    return PromptPreview(
        prompt=prompt,
        prompt_tokens=generator.count_tokens(prompt),
        budget=generator.context_token_budget,
        sources=rows,
    )


def corpus_files(
    file_hashes: Dict[str, str], needle: str, limit: int
) -> List[str]:
    """Indexed file paths containing ``needle``, shortest first."""
    lowered = needle.lower().strip()
    matches = [
        path for path in file_hashes
        if strategy_for(path) and lowered in path.lower()
    ]
    matches.sort(key=lambda path: (len(path), path))
    return matches[:limit]
