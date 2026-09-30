"""Higgsfield image and short-video generation for the marketing agent.

This calls the official REST API that the Higgsfield Python SDK wraps
(``subscribe`` submits, then polls ``status_url``). Credentials stay in the
environment or local config. Nothing here is sent to the browser.

Documented credential shapes:

* ``HF_KEY`` or ``HF_CREDENTIALS`` = ``key_id:key_secret``
* ``HF_API_KEY_ID`` and ``HF_API_KEY_SECRET`` as a pair

The image model default is ``higgsfield-ai/soul/v2/standard``. The short-video
default is ``bytedance/seedance-2.0/text-to-video``. Both come from Higgsfield's
public docs and can be overridden. A missing key, or a model the account
cannot use, returns a skipped or failed asset and leaves the written draft.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.higgsfield.ai"
DEFAULT_IMAGE_MODEL = "higgsfield-ai/soul/v2/standard"
DEFAULT_VIDEO_MODEL = "bytedance/seedance-2.0/text-to-video"
_TERMINAL = {"completed", "failed", "nsfw", "canceled"}


def resolve_credentials(config_key: str = "") -> str:
    """Return ``key_id:key_secret``, or an empty string when unset.

    Environment variables win over the config value so a secret in the shell
    is not overwritten by a blank toml field.
    """
    for name in ("HF_KEY", "HF_CREDENTIALS", "HIGGSFIELD_API_KEY"):
        value = os.environ.get(name, "").strip()
        if ":" in value:
            return value
    key_id = os.environ.get("HF_API_KEY_ID", "").strip()
    secret = os.environ.get("HF_API_KEY_SECRET", "").strip()
    if key_id and secret:
        return f"{key_id}:{secret}"
    configured = (config_key or "").strip()
    if ":" in configured:
        return configured
    return ""


class HiggsfieldClient:
    """Submit a generation and poll until it finishes or the budget runs out."""

    def __init__(
        self,
        credentials: str = "",
        *,
        image_model: str = DEFAULT_IMAGE_MODEL,
        video_model: str = DEFAULT_VIDEO_MODEL,
        base_url: str = "",
        http: Callable[..., tuple[int, dict[str, Any]]] | None = None,
        sleeper: Callable[[float], None] | None = None,
        max_polls: int = 6,
    ) -> None:
        self.credentials = credentials or ""
        self.image_model = image_model or DEFAULT_IMAGE_MODEL
        self.video_model = video_model or DEFAULT_VIDEO_MODEL
        configured_base = base_url or os.environ.get("HF_BASE_URL") or DEFAULT_BASE
        self.base_url = configured_base.rstrip("/")
        self._http = http
        self._sleeper = sleeper or time.sleep
        self.max_polls = max_polls

    @property
    def configured(self) -> bool:
        return ":" in self.credentials

    def public_status(self) -> dict[str, Any]:
        """Status safe to show in the dashboard. The key is not included."""
        return {
            "configured": self.configured,
            "image_model": self.image_model,
            "video_model": self.video_model,
        }

    def illustrate(self, prompt: str, *, video: bool = False) -> list[dict[str, Any]]:
        """Make a still, and a short video when the request asks for one."""
        text = " ".join((prompt or "").split())[:500]
        if not text:
            return []
        if not self.configured:
            return [
                _asset(
                    "image",
                    text,
                    "skipped",
                    detail=(
                        "Higgsfield is not connected. Set HF_KEY to "
                        "key_id:key_secret to make pictures and clips."
                    ),
                )
            ]
        assets = [
            self._generate(
                self.image_model,
                {"prompt": text, "aspect_ratio": "4:3", "resolution": "720p"},
                "image",
                text,
            )
        ]
        if video:
            assets.append(
                self._generate(
                    self.video_model,
                    {
                        "prompt": text,
                        "resolution": "720p",
                        "duration": 5,
                        "aspect_ratio": "16:9",
                        "generate_audio": False,
                    },
                    "video",
                    text,
                )
            )
        return assets

    def _generate(
        self,
        model: str,
        payload: dict[str, Any],
        kind: str,
        prompt: str,
    ) -> dict[str, Any]:
        try:
            status, body = self._request("POST", f"{self.base_url}/{model}", payload)
        except Exception:
            logger.debug("Higgsfield submit failed", exc_info=True)
            return _asset(
                kind,
                prompt,
                "failed",
                detail="Higgsfield could not be reached.",
            )
        if status >= 400:
            return _asset(
                kind,
                prompt,
                "failed",
                detail=f"Higgsfield returned {status} for {model}.",
            )
        status_url = str(body.get("status_url") or "")
        request_id = str(body.get("request_id") or "")
        if not _safe_status_url(status_url, self.base_url):
            status_url = ""
            if request_id:
                status_url = f"{self.base_url}/requests/{request_id}/status"
        current = body
        if status_url:
            for _ in range(self.max_polls):
                if str(current.get("status") or "") in _TERMINAL:
                    break
                self._sleeper(0.4)
                try:
                    _, current = self._request("GET", status_url, None)
                except Exception:
                    logger.debug("Higgsfield poll failed", exc_info=True)
                    return _asset(
                        kind,
                        prompt,
                        "failed",
                        request_id=request_id,
                        detail="Higgsfield stopped answering while rendering.",
                    )
        state = str(current.get("status") or "queued")
        url = _first_url(current)
        if state == "completed" and url:
            return _asset(kind, prompt, "completed", url=url, request_id=request_id)
        if state in _TERMINAL:
            return _asset(
                kind,
                prompt,
                state,
                request_id=request_id,
                detail=f"Higgsfield finished with status {state}.",
            )
        return _asset(
            kind,
            prompt,
            state or "queued",
            request_id=request_id,
            detail="Higgsfield is still rendering. Check the dashboard again shortly.",
        )

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        header = f"Key {self.credentials}"
        if self._http is not None:
            return self._http(method, url, payload, header)
        import httpx

        headers = {
            "Authorization": header,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=30) as client:
            response = client.request(method, url, json=payload, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return response.status_code, body


def _safe_status_url(url: str, base: str) -> bool:
    """Only follow a status URL on the Higgsfield host we submitted to."""
    if not url:
        return False
    parsed = urlparse(url)
    expected = urlparse(base)
    return parsed.scheme in {"https", "http"} and parsed.netloc == expected.netloc


def _first_url(body: dict[str, Any]) -> str:
    for image in body.get("images") or []:
        if isinstance(image, dict) and image.get("url"):
            return str(image["url"])
    video = body.get("video") or {}
    if isinstance(video, dict) and video.get("url"):
        return str(video["url"])
    return ""


def _asset(
    kind: str,
    prompt: str,
    status: str,
    *,
    url: str = "",
    request_id: str = "",
    detail: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "prompt": prompt,
        "status": status,
        "url": url,
        "request_id": request_id,
        "detail": detail,
    }
