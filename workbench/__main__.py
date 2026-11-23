"""Start the RAG Workbench: ``uv run python -m workbench``."""

from __future__ import annotations

import sys

import fire

from src.io_utils import InputError
from src.pipeline import RagPipeline


def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    raw_directory: str = "data/raw",
    processed_directory: str = "data/processed",
    cache_directory: str = "data/cache",
    datasets_directory: str = "data/datasets",
) -> None:
    """Serve the workbench at http://host:port/.

    Args:
        host: Interface to bind.
        port: TCP port to listen on.
        raw_directory: Corpus root.
        processed_directory: Index directory.
        cache_directory: Query cache directory.
        datasets_directory: Folder holding ``AnsweredQuestions/*.json``.
    """
    if not isinstance(port, int) or isinstance(port, bool) or port < 1:
        raise InputError("--port must be a positive whole number")
    from workbench.server import serve

    pipeline = RagPipeline(
        raw_directory=raw_directory,
        processed_directory=processed_directory,
        cache_directory=cache_directory,
    )
    serve(pipeline, str(host), port, datasets_directory)


if __name__ == "__main__":
    try:
        fire.Fire(main)
    except InputError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
