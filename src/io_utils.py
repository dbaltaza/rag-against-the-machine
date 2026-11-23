"""JSON loading and saving with distinct, descriptive error messages."""

from __future__ import annotations

from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class InputError(Exception):
    """Raised for any problem with a user-provided input."""


def load_model(path: str | Path, model: Type[ModelT]) -> ModelT:
    """Load and validate a JSON file against a pydantic model.

    Args:
        path: Path of the JSON file.
        model: The pydantic model to validate against.

    Returns:
        The validated model instance.

    Raises:
        InputError: When the file is missing, unreadable, not JSON, or
            does not match the model.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise InputError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise InputError(f"Not a file: {file_path}")
    try:
        with file_path.open("r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as error:
        raise InputError(f"Cannot read {file_path}: {error}") from error
    except UnicodeDecodeError as error:
        raise InputError(
            f"{file_path} is not valid UTF-8 text: {error}"
        ) from error
    if not raw.strip():
        raise InputError(f"{file_path} is empty")
    try:
        return model.model_validate_json(raw)
    except ValidationError as error:
        details = error.errors()
        detail = details[0]["msg"] if details else "invalid content"
        location = (
            ".".join(str(part) for part in details[0]["loc"])
            if details else ""
        )
        where = f" at '{location}'" if location else ""
        raise InputError(
            f"{file_path} does not match the {model.__name__} format"
            f"{where}: {detail}"
        ) from error


def save_model(directory: str | Path, file_name: str, data: BaseModel) -> Path:
    """Write a pydantic model as indented JSON under a directory.

    Args:
        directory: Target directory, created if needed.
        file_name: Name of the JSON file to write.
        data: The model to serialise.

    Returns:
        The path of the written file.

    Raises:
        InputError: When the directory cannot be created or written.
    """
    target_dir = Path(directory)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / file_name
        with target.open("w", encoding="utf-8") as f:
            f.write(data.model_dump_json(indent=2))
    except OSError as error:
        raise InputError(
            f"Cannot write to {target_dir / file_name}: {error}"
        ) from error
    return target
