"""Entry point: ``uv run python -m src <command> [options]``."""

from __future__ import annotations

import sys

import fire

from src.cli import RagCli
from src.io_utils import InputError


def main() -> int:
    """Run the CLI, turning any failure into a clean error line."""
    try:
        fire.Fire(RagCli, name="python -m src")
    except InputError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001 - last line of defence
        print(
            f"Error ({type(error).__name__}): {error}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
