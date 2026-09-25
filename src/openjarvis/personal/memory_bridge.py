"""Second-brain bridge onto OpenJarvis memory.

Notes always live in the personal store, so capture works when the native
memory extension is missing. When a memory backend is configured, the same
note is also written with source ``personal.second_brain`` and later searches
include those hits.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_SOURCE = "personal.second_brain"


class MemoryBridge:
    """Best-effort adapter over a :class:`MemoryBackend`."""

    def __init__(self, backend: Any = None) -> None:
        self.backend = backend

    def store(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        if self.backend is None or not content.strip():
            return ""
        try:
            return str(
                self.backend.store(
                    content,
                    source=MEMORY_SOURCE,
                    metadata=metadata or {"source": MEMORY_SOURCE},
                )
            )
        except Exception:
            logger.debug("Second brain memory store failed", exc_info=True)
            return ""

    def search(self, query: str, top_k: int = 5) -> list[str]:
        if self.backend is None or not query.strip():
            return []
        try:
            results = self.backend.search(query, top_k=top_k)
        except Exception:
            logger.debug("Second brain memory search failed", exc_info=True)
            return []
        hits: list[str] = []
        for item in results or []:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if content:
                hits.append(str(content))
        return hits
