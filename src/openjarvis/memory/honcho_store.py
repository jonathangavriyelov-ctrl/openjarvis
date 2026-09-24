"""Honcho-backed fact store — long-term memory mirrored to Honcho.

`Honcho <https://honcho.dev>`_ is a memory layer that builds a model of a user
from their messages and answers natural-language questions about them.  This
store keeps the local JSONL file as the source of truth (so provenance tiers,
quarantine, ``jarvis memory list`` and ``clear`` behave exactly like the
``local`` backend) and mirrors every *recallable* fact to Honcho as a message
from the user's peer, letting Honcho's reasoning build on it across sessions.

Quarantined (``untrusted``) facts never leave the machine.  Honcho failures are
logged and swallowed: a flaky network must never break local memory.

Configuration (environment)::

    HONCHO_API_KEY        API key (required for the managed service)
    HONCHO_URL            Base URL (self-hosted Honcho); defaults to the SDK's
    HONCHO_WORKSPACE_ID   Workspace; defaults to "openjarvis"
    HONCHO_PEER_ID        Peer the facts describe; defaults to "user"
    HONCHO_SESSION_ID     Session facts are written to; defaults to "jarvis-memory"

Requires the optional ``honcho-ai`` package (``uv pip install honcho-ai``).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from openjarvis.core.registry import FactStoreRegistry
from openjarvis.memory.store import RECALLABLE_TRUST_TIERS, LocalFactStore

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ID = "openjarvis"
DEFAULT_PEER_ID = "user"
DEFAULT_SESSION_ID = "jarvis-memory"


def _build_client(api_key: str, base_url: str, workspace_id: str) -> Any:
    try:
        from honcho import Honcho
    except ImportError as exc:  # pragma: no cover - exercised via message
        raise ImportError(
            "The 'honcho' memory backend requires the honcho-ai package. "
            "Install it with: uv pip install honcho-ai"
        ) from exc
    kwargs: dict[str, Any] = {"workspace_id": workspace_id}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return Honcho(**kwargs)


@FactStoreRegistry.register("honcho")
class HonchoFactStore(LocalFactStore):
    """Local JSONL fact store that also mirrors recallable facts to Honcho."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_facts: int = 1000,
        client: Any = None,
        peer_id: str = "",
        session_id: str = "",
    ) -> None:
        super().__init__(path, max_facts=max_facts)
        self._peer_id = peer_id or os.environ.get("HONCHO_PEER_ID", DEFAULT_PEER_ID)
        self._session_id = session_id or os.environ.get(
            "HONCHO_SESSION_ID", DEFAULT_SESSION_ID
        )
        self._client = client
        self._peer: Any = None
        self._session: Any = None

    # -- Honcho plumbing ----------------------------------------------------

    def _handles(self) -> tuple[Any, Any]:
        """Lazily create the Honcho client, peer and session."""
        if self._client is None:
            self._client = _build_client(
                os.environ.get("HONCHO_API_KEY", ""),
                os.environ.get("HONCHO_URL", ""),
                os.environ.get("HONCHO_WORKSPACE_ID", DEFAULT_WORKSPACE_ID),
            )
        if self._peer is None:
            self._peer = self._client.peer(self._peer_id)
        if self._session is None:
            self._session = self._client.session(self._session_id)
        return self._peer, self._session

    def _mirror(self, text: str, source: str) -> None:
        try:
            peer, session = self._handles()
            session.add_messages(
                [peer.message(text, metadata={"kind": "fact", "source": source})]
            )
        except Exception:  # noqa: BLE001 — remote memory is best-effort
            logger.warning("Honcho: failed to mirror memory fact", exc_info=True)

    # -- FactStore API ------------------------------------------------------

    def add(self, text: str, source: str = "", trust: str = "") -> bool:
        stored = super().add(text, source=source, trust=trust)
        if stored and (trust or "").strip().lower() in RECALLABLE_TRUST_TIERS:
            self._mirror(text.strip(), source)
        return stored

    def ask(self, question: str) -> Optional[str]:
        """Ask Honcho what it has learned about the user.

        Returns ``None`` when Honcho is unreachable, so callers can fall back to
        the local fact list.
        """
        try:
            peer, _ = self._handles()
            answer = peer.chat(question)
        except Exception:  # noqa: BLE001
            logger.warning("Honcho: dialectic query failed", exc_info=True)
            return None
        if answer is None:
            return None
        return str(getattr(answer, "content", answer))


__all__ = ["HonchoFactStore"]
