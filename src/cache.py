"""Small on-disk cache for query results (bonus).

Results are keyed by the query, ``k``, the retrieval mode and a fingerprint
of the index, so a rebuilt index never serves stale hits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from src.models import ScoredSource


class QueryCache:
    """Persisted mapping from query fingerprint to ranked sources.

    Args:
        path: The JSON file backing the cache.
        enabled: Whether the cache is active at all.
    """

    def __init__(self, path: str | Path, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self._entries: Dict[str, List[dict[str, object]]] = {}
        self._dirty = False
        if enabled:
            self._read()

    def _read(self) -> None:
        """Load the cache file, ignoring a missing or corrupted one."""
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._entries = data
        except (OSError, ValueError):
            self._entries = {}

    @staticmethod
    def key(query: str, k: int, mode: str, fingerprint: str) -> str:
        """Stable cache key for a query."""
        raw = json.dumps([query, k, mode, fingerprint])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[List[ScoredSource]]:
        """Return the cached sources for a key, if any."""
        if not self.enabled:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            return [ScoredSource.model_validate(item) for item in entry]
        except ValueError:
            return None

    def put(self, key: str, sources: List[ScoredSource]) -> None:
        """Store sources for a key (flushed by ``save``)."""
        if not self.enabled:
            return
        self._entries[key] = [source.model_dump() for source in sources]
        self._dirty = True

    def save(self) -> None:
        """Write the cache to disk if it changed."""
        if not self.enabled or not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self._entries, f)
            self._dirty = False
        except OSError as error:
            print(f"Warning: could not write query cache: {error}")

    def clear(self) -> None:
        """Delete every cached entry."""
        self._entries = {}
        self._dirty = True
        self.save()
