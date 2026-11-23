"""Local HTTP API exposing search and answer generation (bonus)."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.io_utils import InputError
from src.models import MinimalAnswer, MinimalSearchResults
from src.pipeline import RagPipeline
from src.retrieval.retriever import MODES


class QueryRequest(BaseModel):
    """Body of the search and answer endpoints."""

    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=0, le=100)
    mode: str = "lexical"


def create_app(pipeline: RagPipeline) -> FastAPI:
    """Build the FastAPI application around a pipeline."""
    app = FastAPI(title="RAG against the machine", version="1.0.0")

    def check_mode(mode: str) -> str:
        if mode not in MODES:
            raise HTTPException(
                status_code=422,
                detail=f"mode must be one of {list(MODES)}",
            )
        return mode

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
            "semantic": manifest.semantic_model,
        }

    @app.post("/search", response_model=MinimalSearchResults)
    def search(request: QueryRequest) -> MinimalSearchResults:
        """Return the top-k sources for a query."""
        mode = check_mode(request.mode)
        try:
            hits = pipeline.search(request.query.strip(), request.k, mode)
            pipeline.cache.save()
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))
        return MinimalSearchResults(
            question_id="query",
            question=request.query,
            retrieved_sources=[hit.to_minimal() for hit in hits],
        )

    @app.post("/answer", response_model=MinimalAnswer)
    def answer(request: QueryRequest) -> MinimalAnswer:
        """Retrieve sources and generate an answer."""
        mode = check_mode(request.mode)
        try:
            return pipeline.answer(request.query.strip(), request.k, mode)
        except (InputError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error))

    @app.get("/modes")
    def modes() -> List[str]:
        """List the retrieval modes."""
        return list(MODES)

    return app


def serve(pipeline: RagPipeline, host: str, port: int) -> None:
    """Run the API with uvicorn until interrupted."""
    import uvicorn

    uvicorn.run(create_app(pipeline), host=host, port=port, log_level="info")
