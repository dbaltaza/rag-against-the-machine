"""Orchestration of the RAG stages: index, retrieve, generate, evaluate."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

from src.cache import QueryCache
from src.evaluation import DEFAULT_KS, evaluate_recall, validate_results
from src.generation import Generator
from src.index import Indexer, IndexStore
from src.index.store import IndexError_
from src.io_utils import InputError, load_model, save_model
from src.models import (
    IndexManifest,
    MinimalAnswer,
    MinimalSearchResults,
    MinimalSource,
    RagDataset,
    ScoredSource,
    StudentSearchResults,
    StudentSearchResultsAndAnswer,
)
from src.retrieval import Retriever


class RagPipeline:
    """Ties the stages together and owns the lazily-loaded components.

    Args:
        raw_directory: Corpus root (``data/raw``).
        processed_directory: Index directory (``data/processed``).
        cache_directory: Where the query cache lives.
        use_cache: Whether query results are cached on disk.
        model_name: Language model used for answers.
    """

    def __init__(
        self,
        raw_directory: str | Path = "data/raw",
        processed_directory: str | Path = "data/processed",
        cache_directory: str | Path = "data/cache",
        use_cache: bool = True,
        model_name: str = "Qwen/Qwen3-0.6B",
    ) -> None:
        self.raw_directory = Path(raw_directory)
        self.processed_directory = Path(processed_directory)
        self.cache_directory = Path(cache_directory)
        self.use_cache = use_cache
        self.model_name = model_name
        self._retriever: Optional[Retriever] = None
        self._generator: Optional[Generator] = None
        self._cache: Optional[QueryCache] = None

    # -- components ------------------------------------------------------

    @property
    def retriever(self) -> Retriever:
        """The retriever, loaded on first access."""
        if self._retriever is None:
            store = IndexStore(self.processed_directory)
            if not store.exists():
                raise InputError(
                    f"No index found under {self.processed_directory}: "
                    "run 'index' first"
                )
            try:
                self._retriever = Retriever(self.processed_directory)
            except IndexError_ as error:
                raise InputError(f"Corrupted index: {error}") from error
        return self._retriever

    @property
    def generator(self) -> Generator:
        """The answer generator, loaded on first access."""
        if self._generator is None:
            self._generator = Generator(model_name=self.model_name)
        return self._generator

    @property
    def cache(self) -> QueryCache:
        """The query cache."""
        if self._cache is None:
            self._cache = QueryCache(
                self.cache_directory / "queries.json", enabled=self.use_cache
            )
        return self._cache

    def index_fingerprint(self) -> str:
        """A string that changes whenever the index is rebuilt."""
        manifest = self.retriever.manifest
        return (
            f"{manifest.chunk_count}:{manifest.file_count}:"
            f"{manifest.max_chunk_size}:{manifest.semantic_model}"
        )

    # -- indexing --------------------------------------------------------

    def index(
        self,
        max_chunk_size: int = 2000,
        incremental: bool = False,
        semantic: bool = False,
        semantic_model: Optional[str] = None,
    ) -> IndexManifest:
        """Build (or update) the index from the raw corpus.

        Args:
            max_chunk_size: Maximum chunk size in characters.
            incremental: Re-index only changed files when possible.
            semantic: Also build the dense embedding index (bonus).
            semantic_model: Sentence encoder used for embeddings.

        Returns:
            The manifest of the written index.
        """
        if not self.raw_directory.is_dir():
            raise InputError(
                f"Raw corpus directory not found: {self.raw_directory}"
            )
        indexer = Indexer(
            self.raw_directory, self.processed_directory, max_chunk_size
        )
        manifest = indexer.update() if incremental else indexer.build()
        self._retriever = None
        self.cache.clear()
        if semantic:
            manifest = self._build_semantic(indexer.store, semantic_model)
        return manifest

    def _build_semantic(
        self, store: IndexStore, model_name: Optional[str]
    ) -> IndexManifest:
        """Embed every chunk and persist the dense index."""
        from src.index.indexer import index_text_for
        from src.index.semantic import DEFAULT_MODEL, build_embeddings

        name = model_name or DEFAULT_MODEL
        chunks = store.load_chunks()
        texts = [index_text_for(chunk, path_weight=1) for chunk in chunks]
        embeddings = build_embeddings(texts, name)
        store.save_embeddings(embeddings)
        manifest = store.load_manifest()
        manifest.semantic_model = name
        store.save(
            chunks, store.load_term_frequencies(), store.load_vocabulary(),
            manifest,
        )
        return manifest

    # -- retrieval -------------------------------------------------------

    def search(
        self, query: str, k: int, mode: str = "lexical"
    ) -> List[ScoredSource]:
        """Retrieve the top-``k`` sources for one query (cached)."""
        if k <= 0 or not query.strip():
            return []
        key = QueryCache.key(query, k, mode, self.index_fingerprint())
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        results = self.retriever.search(query, k, mode)
        self.cache.put(key, results)
        return results

    def search_dataset(
        self,
        dataset_path: str | Path,
        k: int,
        save_directory: str | Path,
        mode: str = "lexical",
    ) -> Path:
        """Search every question of a dataset and write the results.

        Returns:
            The path of the written StudentSearchResults file.
        """
        dataset = load_model(dataset_path, RagDataset)
        entries: List[MinimalSearchResults] = []
        for question in tqdm(
            dataset.rag_questions, desc="Searching", unit="question"
        ):
            hits = self.search(question.question, k, mode)
            entries.append(
                MinimalSearchResults(
                    question_id=question.question_id,
                    question=question.question,
                    retrieved_sources=[
                        MinimalSource(**hit.model_dump(
                            include={
                                "file_path",
                                "first_character_index",
                                "last_character_index",
                            }
                        ))
                        for hit in hits
                    ],
                )
            )
        self.cache.save()
        results = StudentSearchResults(search_results=entries, k=k)
        return save_model(save_directory, Path(dataset_path).name, results)

    # -- generation ------------------------------------------------------

    def answer(
        self, query: str, k: int, mode: str = "lexical"
    ) -> MinimalAnswer:
        """Retrieve sources for a query and generate an answer."""
        hits = self.search(query, k, mode)
        self.cache.save()
        text = self.generator.answer(query, hits)
        return MinimalAnswer(
            question=query,
            retrieved_sources=[
                MinimalSource(
                    file_path=hit.file_path,
                    first_character_index=hit.first_character_index,
                    last_character_index=hit.last_character_index,
                )
                for hit in hits
            ],
            answer=text,
            question_id=_new_id(),
        )

    def answer_dataset(
        self,
        student_search_results_path: str | Path,
        save_directory: str | Path,
        max_sources: Optional[int] = None,
    ) -> Path:
        """Generate an answer for every entry of a search results file.

        Chunk texts are re-read from the corpus files using the spans, so
        the file can come from any retriever.

        Returns:
            The path of the written StudentSearchResultsAndAnswer file.
        """
        results = load_model(student_search_results_path, StudentSearchResults)
        answers: List[MinimalAnswer] = []
        file_cache: Dict[str, Optional[str]] = {}
        for entry in tqdm(
            results.search_results, desc="Answering", unit="question"
        ):
            sources = entry.retrieved_sources
            if max_sources is not None:
                sources = sources[:max_sources]
            scored = [
                ScoredSource(
                    file_path=source.file_path,
                    first_character_index=source.first_character_index,
                    last_character_index=source.last_character_index,
                    score=0.0,
                    text=self._span_text(source, file_cache),
                )
                for source in sources
            ]
            scored = [source for source in scored if source.text]
            text = self.generator.answer(entry.question, scored)
            answers.append(
                MinimalAnswer(
                    question_id=entry.question_id,
                    question=entry.question,
                    retrieved_sources=entry.retrieved_sources,
                    answer=text,
                )
            )
        output = StudentSearchResultsAndAnswer(
            search_results=answers, k=results.k
        )
        return save_model(
            save_directory, Path(student_search_results_path).name, output
        )

    def _span_text(
        self, source: MinimalSource, file_cache: Dict[str, Optional[str]]
    ) -> str:
        """Read the text of a source span from disk (cached per file)."""
        if source.file_path not in file_cache:
            try:
                with open(source.file_path, "r", encoding="utf-8") as f:
                    file_cache[source.file_path] = f.read()
            except (OSError, UnicodeDecodeError):
                file_cache[source.file_path] = None
        content = file_cache[source.file_path]
        if content is None:
            return ""
        return content[
            source.first_character_index:source.last_character_index
        ]

    # -- evaluation ------------------------------------------------------

    def evaluate(
        self,
        student_search_results_path: str | Path,
        dataset_path: str | Path,
        max_context_length: int = 2000,
    ) -> Dict[int, float]:
        """Validate a results file and compute recall@k against a dataset.

        Returns:
            Mapping from k to recall.
        """
        results = load_model(student_search_results_path, StudentSearchResults)
        dataset = load_model(dataset_path, RagDataset)
        problems = validate_results(results, max_context_length)
        print(f"Student data is valid: {not problems}")
        for problem in problems[:10]:
            print(f"  - {problem}")
        if len(problems) > 10:
            print(f"  ... and {len(problems) - 10} more problems")
        recalls = evaluate_recall(results, dataset, DEFAULT_KS)
        return recalls


def _new_id() -> str:
    """Return a fresh question identifier."""
    import uuid

    return str(uuid.uuid4())
