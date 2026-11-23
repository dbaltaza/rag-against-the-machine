"""Command-line interface, exposed through Python Fire.

Every command validates its arguments and raises ``InputError`` with a
distinct message on bad input; ``__main__`` turns those into a clean
error line and a non-zero exit code.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.io_utils import InputError
from src.models import MinimalSearchResults, StudentSearchResults
from src.pipeline import RagPipeline
from src.retrieval.retriever import MODES

MAX_CONTEXT_LENGTH = 2000


def _as_int(value: Any, name: str, minimum: int = 0) -> int:
    """Coerce a CLI value to an int at least ``minimum``."""
    if isinstance(value, bool):
        raise InputError(f"--{name} must be an integer, got '{value}'")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise InputError(
            f"--{name} must be an integer, got '{value}'"
        ) from error
    if number < minimum:
        raise InputError(f"--{name} must be at least {minimum}, got {number}")
    return number


def _as_query(value: Any) -> str:
    """Coerce a CLI value to a non-blank query string."""
    if value is None:
        raise InputError("A query is required")
    query = str(value).strip()
    if not query:
        raise InputError("The query is empty")
    return query


def _as_mode(value: Any) -> str:
    """Validate a retrieval mode name."""
    mode = str(value).lower()
    if mode not in MODES:
        choices = ", ".join(MODES)
        raise InputError(
            f"Unknown retrieval mode '{value}'; choose one of {choices}"
        )
    return mode


def _as_path(value: Any, name: str) -> str:
    """Coerce a CLI value to a non-empty path string."""
    if value is None or not str(value).strip():
        raise InputError(f"--{name} is required")
    return str(value)


class RagCli:
    """RAG against the machine: question answering over the vLLM codebase.

    Run ``uv run python -m src <command> --help`` for the options of a
    command.

    Args:
        raw_directory: Corpus root (default ``data/raw``).
        processed_directory: Index directory (default ``data/processed``).
        cache_directory: Query cache directory (default ``data/cache``).
        use_cache: Enable the on-disk query cache.
        model_name: Language model used for answer generation.
    """

    def __init__(
        self,
        raw_directory: str = "data/raw",
        processed_directory: str = "data/processed",
        cache_directory: str = "data/cache",
        use_cache: bool = True,
        model_name: str = "Qwen/Qwen3-0.6B",
    ) -> None:
        self._pipeline = RagPipeline(
            raw_directory=_as_path(raw_directory, "raw_directory"),
            processed_directory=_as_path(
                processed_directory, "processed_directory"
            ),
            cache_directory=_as_path(cache_directory, "cache_directory"),
            use_cache=bool(use_cache),
            model_name=str(model_name),
        )

    def index(
        self,
        max_chunk_size: int = 2000,
        incremental: bool = False,
        semantic: bool = False,
        semantic_model: Optional[str] = None,
    ) -> None:
        """Ingest the raw corpus and build the index.

        Args:
            max_chunk_size: Maximum chunk size in characters (1..2000).
            incremental: Re-index only the files that changed (bonus).
            semantic: Also build a dense embedding index (bonus).
            semantic_model: Sentence encoder for the embeddings.
        """
        size = _as_int(max_chunk_size, "max_chunk_size", minimum=1)
        if size > MAX_CONTEXT_LENGTH:
            raise InputError(
                f"--max_chunk_size must be at most {MAX_CONTEXT_LENGTH}: the "
                "moulinette rejects longer sources"
            )
        manifest = self._pipeline.index(
            max_chunk_size=size,
            incremental=bool(incremental),
            semantic=bool(semantic),
            semantic_model=semantic_model,
        )
        print(
            f"Ingestion complete! Indices saved under "
            f"{self._pipeline.processed_directory}/ "
            f"({manifest.chunk_count} chunks from {manifest.file_count} files)"
        )

    def search(
        self,
        query: Optional[str] = None,
        k: int = 10,
        mode: str = "lexical",
        as_json: bool = False,
    ) -> None:
        """Return the top-k sources for a single query.

        Args:
            query: The question to search for.
            k: Number of sources to return.
            mode: ``lexical``, ``semantic`` or ``hybrid`` (bonus modes).
            as_json: Print a StudentSearchResults JSON instead of a list.
        """
        text = _as_query(query)
        count = _as_int(k, "k")
        hits = self._pipeline.search(text, count, _as_mode(mode))
        self._pipeline.cache.save()
        if as_json:
            entry = MinimalSearchResults(
                question_id="query",
                question=text,
                retrieved_sources=[hit.to_minimal() for hit in hits],
            )
            print(
                StudentSearchResults(
                    search_results=[entry], k=count
                ).model_dump_json(indent=2)
            )
            return
        if not hits:
            print("No matching source found.")
            return
        for rank, hit in enumerate(hits, start=1):
            preview = " ".join(hit.text.split())[:100]
            print(
                f"{rank:2d}. [{hit.score:6.2f}] {hit.file_path} "
                f"[{hit.first_character_index}:{hit.last_character_index}]"
            )
            print(f"      {preview}")

    def search_dataset(
        self,
        dataset_path: Optional[str] = None,
        k: int = 10,
        save_directory: Optional[str] = None,
        mode: str = "lexical",
    ) -> None:
        """Run search over a whole dataset and write a results JSON file.

        Args:
            dataset_path: Path of a RagDataset JSON file.
            k: Number of sources per question.
            save_directory: Directory receiving the StudentSearchResults
                file (named after the dataset file).
            mode: ``lexical``, ``semantic`` or ``hybrid`` (bonus modes).
        """
        path = self._pipeline.search_dataset(
            _as_path(dataset_path, "dataset_path"),
            _as_int(k, "k"),
            _as_path(save_directory, "save_directory"),
            _as_mode(mode),
        )
        print(f"Saved student_search_results to {path}")

    def answer(
        self,
        query: Optional[str] = None,
        k: int = 5,
        mode: str = "lexical",
        as_json: bool = False,
    ) -> None:
        """Answer a single query using the retrieved context.

        Args:
            query: The question to answer.
            k: Number of sources retrieved as context.
            mode: ``lexical``, ``semantic`` or ``hybrid`` (bonus modes).
            as_json: Print the MinimalAnswer as JSON.
        """
        result = self._pipeline.answer(
            _as_query(query), _as_int(k, "k"), _as_mode(mode)
        )
        if as_json:
            print(result.model_dump_json(indent=2))
            return
        print("Sources:")
        for rank, source in enumerate(result.retrieved_sources, start=1):
            print(
                f"{rank:2d}. {source.file_path} "
                f"[{source.first_character_index}:"
                f"{source.last_character_index}]"
            )
        print("\nAnswer:")
        print(result.answer)

    def answer_dataset(
        self,
        student_search_results_path: Optional[str] = None,
        save_directory: Optional[str] = None,
        max_sources: Optional[int] = None,
    ) -> None:
        """Generate answers for a dataset of search results.

        Args:
            student_search_results_path: A StudentSearchResults JSON file.
            save_directory: Directory receiving the
                StudentSearchResultsAndAnswer file (same file name).
            max_sources: Cap on the sources used per answer.
        """
        limit = (
            None if max_sources is None
            else _as_int(max_sources, "max_sources")
        )
        path = self._pipeline.answer_dataset(
            _as_path(
                student_search_results_path, "student_search_results_path"
            ),
            _as_path(save_directory, "save_directory"),
            limit,
        )
        print(f"Saved student_search_results_and_answer to {path}")

    def evaluate(
        self,
        student_search_results_path: Optional[str] = None,
        dataset_path: Optional[str] = None,
        max_context_length: int = MAX_CONTEXT_LENGTH,
    ) -> None:
        """Report recall@k of a results file against a ground-truth dataset.

        Args:
            student_search_results_path: A StudentSearchResults JSON file.
            dataset_path: The AnsweredQuestions RagDataset file.
            max_context_length: Maximum allowed source width.
        """
        recalls = self._pipeline.evaluate(
            _as_path(
                student_search_results_path, "student_search_results_path"
            ),
            _as_path(dataset_path, "dataset_path"),
            _as_int(max_context_length, "max_context_length", minimum=1),
        )
        print("Evaluation Results")
        print("=" * 40)
        print(
            "  ".join(
                f"Recall@{k}: {value:.3f}" for k, value in recalls.items()
            )
        )

    def clear_cache(self) -> None:
        """Delete the on-disk query cache (bonus)."""
        self._pipeline.cache.clear()
        print("Query cache cleared")

    def serve(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """Expose search and answer over a local HTTP API (bonus).

        Args:
            host: Interface to bind.
            port: TCP port to listen on.
        """
        from src.api import serve

        serve(self._pipeline, str(host), _as_int(port, "port", minimum=1))

    def version(self) -> None:
        """Print the project version."""
        from src import __version__

        print(json.dumps({"version": __version__}))
