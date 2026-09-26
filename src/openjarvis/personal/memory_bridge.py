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
        meta = dict(metadata or {})
        meta.setdefault("source", MEMORY_SOURCE)
        world_id = str(meta.get("world_id") or "")
        stored = f"world:{world_id}\n{content}" if world_id else content
        try:
            return str(
                self.backend.store(
                    stored,
                    source=MEMORY_SOURCE,
                    metadata=meta,
                )
            )
        except Exception:
            logger.debug("Second brain memory store failed", exc_info=True)
            return ""

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        world_id: str | None = None,
    ) -> list[str]:
        if self.backend is None or not query.strip():
            return []
        try:
            results = self.backend.search(query, top_k=top_k)
        except Exception:
            logger.debug("Second brain memory search failed", exc_info=True)
            return []
        hits: list[str] = []
        prefix = f"world:{world_id}\n" if world_id else ""
        for item in results or []:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if not content:
                continue
            text = str(content)
            if world_id:
                if text.startswith(prefix):
                    hits.append(text[len(prefix) :])
                elif not text.startswith("world:"):
                    continue
            else:
                hits.append(text)
        return hits
