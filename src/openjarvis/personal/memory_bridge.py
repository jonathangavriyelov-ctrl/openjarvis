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
        specialist_id = str(meta.get("specialist_id") or "")
        lines: list[str] = []
        if world_id:
            lines.append(f"world:{world_id}")
        if specialist_id:
            lines.append(f"agent:{specialist_id}")
        stored = "\n".join([*lines, content]) if lines else content
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

    def delete(self, memory_id: str) -> None:
        if not memory_id or self.backend is None:
            return
        delete = getattr(self.backend, "delete", None)
        if delete is None:
            return
        try:
            delete(memory_id)
        except Exception:
            logger.debug("Second brain memory delete failed", exc_info=True)

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        world_id: str | None = None,
        specialist_id: str | None = None,
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
                if not text.startswith(prefix):
                    continue
                text = text[len(prefix) :]
            elif text.startswith("world:"):
                _, _, text = text.partition("\n")
            if text.startswith("agent:"):
                agent, _, rest = text.partition("\n")
                owner = agent.split(":", 1)[1]
                if specialist_id and owner != specialist_id:
                    continue
                text = rest
            if text:
                hits.append(text)
        return hits
