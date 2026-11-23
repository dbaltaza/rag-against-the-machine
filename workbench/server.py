"""HTTP server behind the RAG Workbench (an extra, not part of the subject).

It wraps the project's own pipeline: ``GET /`` serves the single-page app
from ``workbench/web/``, and the JSON endpoints let the page search,
answer, explain each pipeline stage, evaluate datasets and rebuild the
index. Nothing in ``src/`` imports this package.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.evaluation import DEFAULT_KS, MIN_IOU, interval_iou, question_recall
from src.io_utils import InputError, load_model
from src.models import (
    AnsweredQuestion,
    MinimalAnswer,
    MinimalSearchResults,
    MinimalSource,
    RagDataset,
    ScoredSource,
)
from src.pipeline import RagPipeline
from src.retrieval.retriever import MODES
from workbench.learn import (
    BM25Explanation,
    ChunkPreview,
    PromptPreview,
    WordTokens,
    corpus_files,
    explain_bm25,
    explain_tokens,
    preview_chunks,
    preview_prompt,
)

WEB_DIRECTORY = Path(__file__).parent / "web"
WEB_PAGE = WEB_DIRECTORY / "index.html"
MAX_FILE_BYTES = 2_000_000


class QueryRequest(BaseModel):
    """Body of the search and answer endpoints."""

    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=0, le=100)
    mode: str = "lexical"


class IndexRequest(BaseModel):
    """Body of the index endpoint."""

    max_chunk_size: int = Field(default=2000, ge=100, le=2000)
    incremental: bool = True
    semantic: bool = False


class EvaluateRequest(BaseModel):
    """Body of the evaluate endpoint."""

    dataset: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    mode: str = "lexical"


class TextRequest(BaseModel):
    """Body of the tokenizer endpoint."""

    text: str = Field(max_length=5000)


class ChunkRequest(BaseModel):
    """Body of the chunk preview endpoint."""

    path: str = Field(min_length=1)
    max_chunk_size: int = Field(default=2000, ge=100, le=2000)
    min_chunk_size: int = Field(default=800, ge=0, le=2000)


class ReferenceResult(BaseModel):
    """A ground-truth source and the rank at which it was first found."""

    source: MinimalSource
    found_at: Optional[int] = None


class QuestionResult(BaseModel):
    """Per-question outcome of an evaluation run."""

    question_id: str
    question: str
    recall: Dict[int, float]
    references: List[ReferenceResult]
    retrieved: List[MinimalSource]


class EvaluateResponse(BaseModel):
    """Mean recall@k plus the per-question detail."""

    dataset: str
    k: int
    mode: str
    seconds: float
    recall: Dict[int, float]
    questions: List[QuestionResult]


def cutoffs(k: int) -> List[int]:
    """The recall cut-offs reported for a run with ``k`` results."""
    return sorted({cut for cut in DEFAULT_KS if cut <= k} | {k})


def first_hit_rank(
    reference: MinimalSource, retrieved: List[MinimalSource]
) -> Optional[int]:
    """1-based rank of the first retrieved source covering a reference."""
    for rank, hit in enumerate(retrieved, start=1):
        if interval_iou(reference, hit) >= MIN_IOU:
            return rank
    return None


def create_app(
    pipeline: RagPipeline, datasets_directory: str | Path = "data/datasets"
) -> FastAPI:
    """Build the workbench application around a pipeline.

    Args:
        pipeline: The pipeline every endpoint delegates to.
        datasets_directory: Folder holding ``AnsweredQuestions/*.json``,
            used by the dataset evaluation endpoints.

    Returns:
        The configured application.
    """
    app = FastAPI(title="RAG Workbench", version="1.0.0")
    if WEB_DIRECTORY.is_dir():
        app.mount(
            "/static", StaticFiles(directory=WEB_DIRECTORY), name="static"
        )
    answered_directory = Path(datasets_directory) / "AnsweredQuestions"
    lock = threading.Lock()

    def check_mode(mode: str) -> str:
        if mode not in MODES:
            raise HTTPException(
                status_code=422,
                detail=f"mode must be one of {list(MODES)}",
            )
        return mode

    def dataset_names() -> List[str]:
        if not answered_directory.is_dir():
            return []
        return sorted(path.name for path in answered_directory.glob("*.json"))

    @app.get("/", response_class=HTMLResponse)
    def workbench() -> HTMLResponse:
        """Serve the single-page web workbench."""
        try:
            with WEB_PAGE.open("r", encoding="utf-8") as f:
                return HTMLResponse(f.read())
        except OSError as error:
            raise HTTPException(
                status_code=404, detail=f"Workbench page missing: {error}"
            )

    @app.get("/health")
    def health() -> Dict[str, Any]:
        """Liveness probe with index statistics."""
        try:
            manifest = pipeline.retriever.manifest
        except InputError as error:
            raise HTTPException(status_code=503, detail=str(error))
        return {
            "status": "ok",
            "chunks": manifest.chunk_count,
            "files": manifest.file_count,
            "max_chunk_size": manifest.max_chunk_size,
            "semantic": manifest.semantic_model,
            "vocabulary": len(pipeline.retriever.bm25.vocabulary),
            "model": pipeline.model_name,
            "raw_directory": str(pipeline.raw_directory),
        }

    @app.post("/search", response_model=MinimalSearchResults)
    def search(request: QueryRequest) -> MinimalSearchResults:
        """Return the top-k sources for a query."""
        mode = check_mode(request.mode)
        try:
            with lock:
                hits = pipeline.search(request.query.strip(), request.k, mode)
                pipeline.cache.save()
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))
        return MinimalSearchResults(
            question_id="query",
            question=request.query,
            retrieved_sources=[hit.to_minimal() for hit in hits],
        )

    @app.post("/explore", response_model=List[ScoredSource])
    def explore(request: QueryRequest) -> List[ScoredSource]:
        """Return the top-k sources with their score and chunk text."""
        mode = check_mode(request.mode)
        try:
            with lock:
                hits = pipeline.search(request.query.strip(), request.k, mode)
                pipeline.cache.save()
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))
        return hits

    @app.post("/answer", response_model=MinimalAnswer)
    def answer(request: QueryRequest) -> MinimalAnswer:
        """Retrieve sources and generate an answer."""
        mode = check_mode(request.mode)
        try:
            with lock:
                return pipeline.answer(request.query.strip(), request.k, mode)
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))

    @app.get("/modes")
    def modes() -> List[str]:
        """List the retrieval modes."""
        return list(MODES)

    def corpus_text(path: str) -> str:
        """Read a corpus file, refusing anything outside the raw corpus."""
        root = pipeline.raw_directory.resolve()
        target = Path(path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(
                status_code=403, detail="Only corpus files can be read"
            )
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"No file: {path}")
        try:
            if target.stat().st_size > MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413, detail=f"{path} is too large to show"
                )
            with target.open("r", encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError) as error:
            raise HTTPException(
                status_code=422, detail=f"Cannot read {path}: {error}"
            )

    @app.get("/file")
    def read_file(path: str) -> Dict[str, str]:
        """Return the text of one corpus file (only under the raw corpus)."""
        return {"file_path": path, "text": corpus_text(path)}

    @app.get("/learn/files")
    def learn_files(q: str = "", limit: int = 30) -> List[str]:
        """Indexed corpus files whose path contains ``q``."""
        try:
            hashes = pipeline.retriever.manifest.file_hashes
        except InputError as error:
            raise HTTPException(status_code=503, detail=str(error))
        return corpus_files(hashes, q, max(1, min(limit, 100)))

    @app.post("/learn/tokenize", response_model=List[WordTokens])
    def learn_tokenize(request: TextRequest) -> List[WordTokens]:
        """Show the tokens each word of a text produces."""
        return explain_tokens(request.text)

    @app.post("/learn/chunk", response_model=ChunkPreview)
    def learn_chunk(request: ChunkRequest) -> ChunkPreview:
        """Chunk one corpus file with custom sizes."""
        text = corpus_text(request.path)
        return preview_chunks(
            request.path, text, request.max_chunk_size,
            request.min_chunk_size,
        )

    @app.post("/learn/bm25", response_model=BM25Explanation)
    def learn_bm25(request: QueryRequest) -> BM25Explanation:
        """Rank chunks for a query and split every score by term."""
        try:
            with lock:
                retriever = pipeline.retriever
                return explain_bm25(
                    retriever.bm25, retriever.chunks,
                    request.query.strip(), request.k,
                )
        except InputError as error:
            raise HTTPException(status_code=503, detail=str(error))

    @app.post("/learn/prompt", response_model=PromptPreview)
    def learn_prompt(request: QueryRequest) -> PromptPreview:
        """Build the exact prompt the model would receive."""
        mode = check_mode(request.mode)
        try:
            with lock:
                hits = pipeline.search(request.query.strip(), request.k, mode)
                return preview_prompt(
                    pipeline.generator, request.query.strip(), hits
                )
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))

    @app.get("/datasets")
    def datasets() -> List[str]:
        """List the ground-truth datasets that can be evaluated."""
        return dataset_names()

    @app.post("/evaluate", response_model=EvaluateResponse)
    def evaluate(request: EvaluateRequest) -> EvaluateResponse:
        """Search every question of a dataset and score it against truth."""
        mode = check_mode(request.mode)
        if request.dataset not in dataset_names():
            raise HTTPException(
                status_code=404, detail=f"Unknown dataset: {request.dataset}"
            )
        started = time.perf_counter()
        try:
            dataset = load_model(
                answered_directory / request.dataset, RagDataset
            )
            with lock:
                questions = _score_questions(
                    pipeline, dataset, request.k, mode
                )
                pipeline.cache.save()
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))
        recall = {
            k: (
                sum(q.recall[k] for q in questions) / len(questions)
                if questions else 0.0
            )
            for k in cutoffs(request.k)
        }
        return EvaluateResponse(
            dataset=request.dataset,
            k=request.k,
            mode=mode,
            seconds=round(time.perf_counter() - started, 3),
            recall=recall,
            questions=questions,
        )

    @app.post("/index")
    def build_index(request: IndexRequest) -> Dict[str, Any]:
        """Rebuild the index, or update only the changed files."""
        started = time.perf_counter()
        try:
            with lock:
                manifest = pipeline.index(
                    max_chunk_size=request.max_chunk_size,
                    incremental=request.incremental,
                    semantic=request.semantic,
                )
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))
        return {
            "chunks": manifest.chunk_count,
            "files": manifest.file_count,
            "max_chunk_size": manifest.max_chunk_size,
            "semantic": manifest.semantic_model,
            "seconds": round(time.perf_counter() - started, 2),
        }

    @app.post("/cache/clear")
    def clear_cache() -> Dict[str, str]:
        """Empty the on-disk query cache."""
        with lock:
            pipeline.cache.clear()
        return {"status": "cleared"}

    return app


def _score_questions(
    pipeline: RagPipeline, dataset: RagDataset, k: int, mode: str
) -> List[QuestionResult]:
    """Search each answered question and record where its sources rank."""
    ks = cutoffs(k)
    results: List[QuestionResult] = []
    for question in dataset.rag_questions:
        if not isinstance(question, AnsweredQuestion):
            continue
        hits = pipeline.search(question.question, k, mode)
        retrieved = [hit.to_minimal() for hit in hits]
        results.append(
            QuestionResult(
                question_id=question.question_id,
                question=question.question,
                recall={
                    cut: question_recall(question.sources, retrieved, cut)
                    for cut in ks
                },
                references=[
                    ReferenceResult(
                        source=source,
                        found_at=first_hit_rank(source, retrieved),
                    )
                    for source in question.sources
                ],
                retrieved=retrieved,
            )
        )
    return results


def serve(
    pipeline: RagPipeline,
    host: str,
    port: int,
    datasets_directory: str | Path = "data/datasets",
) -> None:
    """Run the workbench with uvicorn until interrupted."""
    import uvicorn

    print(f"Workbench: http://{host}:{port}/")
    uvicorn.run(
        create_app(pipeline, datasets_directory),
        host=host,
        port=port,
        log_level="info",
    )
