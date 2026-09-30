"""Password gate for the personal AI OS.

The desk stores a scrypt hash under the OpenJarvis home (``~/.openjarvis``
by default). Sessions are random tokens in an httpOnly cookie. The phone
bridge and in-process agents never pass through this layer. A configured
``OPENJARVIS_API_KEY`` is still accepted, because those callers already
authenticate with that key.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

COOKIE_NAME = "oj_os_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
MIN_PASSWORD_LENGTH = 8
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_FAIL_LIMIT = 5
_LOCKOUT_SECONDS = 15 * 60

_AUTH_PREFIX = "/v1/personal/auth/"


def _home() -> Path:
    from openjarvis.core.paths import get_config_dir

    return get_config_dir()


def _password_path() -> Path:
    return _home() / "os_password.json"


def _session_path() -> Path:
    return _home() / "os_sessions.json"


def _lockout_path() -> Path:
    return _home() / "os_lockout.json"


def password_is_set() -> bool:
    path = _password_path()
    return path.is_file() and path.stat().st_size > 0


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )


def set_password(password: str) -> None:
    """Replace the desk password and close every session."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    _write_json(
        _password_path(),
        {
            "kdf": "scrypt",
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
            "salt": salt.hex(),
            "hash": digest.hex(),
        },
    )
    clear_sessions()


def verify_password(password: str) -> bool:
    record = _read_json(_password_path())
    salt_hex = str(record.get("salt") or "")
    hash_hex = str(record.get("hash") or "")
    if not salt_hex or not hash_hex or record.get("kdf") != "scrypt":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(record.get("n") or _SCRYPT_N),
            r=int(record.get("r") or _SCRYPT_R),
            p=int(record.get("p") or _SCRYPT_P),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest, expected)


def clear_sessions() -> None:
    path = _session_path()
    if path.exists():
        path.unlink()


def revoke_session(token: str) -> None:
    if not token:
        return
    sessions = _live_sessions()
    sessions.pop(_token_key(token), None)
    if sessions:
        _write_json(_session_path(), sessions)
    else:
        clear_sessions()


def issue_session() -> str:
    token = secrets.token_urlsafe(32)
    sessions = _live_sessions()
    sessions[_token_key(token)] = time.time() + SESSION_SECONDS
    _write_json(_session_path(), sessions)
    return token


def session_valid(token: str) -> bool:
    if not token:
        return False
    expiry = _live_sessions().get(_token_key(token))
    try:
        return float(expiry) > time.time()
    except (TypeError, ValueError):
        return False


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _live_sessions() -> dict:
    now = time.time()
    fresh: dict[str, float] = {}
    for key, expiry in _read_json(_session_path()).items():
        try:
            expires_at = float(expiry)
        except (TypeError, ValueError):
            continue
        if expires_at > now:
            fresh[str(key)] = expires_at
    return fresh


def _client_key(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def register_failure(request: Request) -> None:
    host = _client_key(request)
    state = _read_json(_lockout_path())
    row = state.get(host) if isinstance(state.get(host), dict) else {}
    fails = int(row.get("fails") or 0) + 1
    locked_until = 0.0
    if fails >= _FAIL_LIMIT:
        locked_until = time.time() + _LOCKOUT_SECONDS
        fails = 0
    state[host] = {"fails": fails, "locked_until": locked_until}
    _write_json(_lockout_path(), state)


def clear_failures(request: Request) -> None:
    host = _client_key(request)
    state = _read_json(_lockout_path())
    if host in state:
        state.pop(host, None)
        _write_json(_lockout_path(), state)


def lockout_remaining(request: Request) -> int:
    host = _client_key(request)
    row = _read_json(_lockout_path()).get(host)
    if not isinstance(row, dict):
        return 0
    try:
        remaining = float(row.get("locked_until") or 0) - time.time()
    except (TypeError, ValueError):
        return 0
    if remaining <= 0:
        return 0
    return int(remaining) + 1


def cookie_token(request: Request) -> str:
    return request.cookies.get(COOKIE_NAME, "")


def api_key_matches(request: Request) -> bool:
    """True when the request carries the configured server API key."""
    expected = os.environ.get("OPENJARVIS_API_KEY", "")
    if not expected:
        return False
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return secrets.compare_digest(token, expected)


def request_unlocked(request: Request) -> bool:
    if api_key_matches(request):
        return True
    return session_valid(cookie_token(request))


def broad_gate_enabled() -> bool:
    """Lock the rest of the data API once a password exists, or under make os."""
    if os.environ.get("OPENJARVIS_PERSONAL_OS") == "1":
        return True
    return password_is_set()


def path_requires_session(path: str) -> bool:
    """Personal data always requires a session. Other data does once the gate is on.

    ``/health`` and the auth routes stay open. Webhooks keep their own checks.
    """
    if path == "/health" or path.startswith("/health/"):
        return False
    if path.startswith(_AUTH_PREFIX):
        return False
    if path.startswith("/webhooks"):
        return False
    if path.startswith("/v1/personal"):
        return True
    if not broad_gate_enabled():
        return False
    return (
        path.startswith("/v1/")
        or path.startswith("/api/")
        or path == "/metrics"
        or path.startswith("/metrics/")
        or path in {"/openapi.json", "/docs", "/redoc"}
        or path.startswith("/docs/")
        or path.startswith("/redoc/")
    )


def apply_session_cookie(response, token: str) -> None:  # noqa: ANN001
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session_cookie(response) -> None:  # noqa: ANN001
    response.delete_cookie(COOKIE_NAME, path="/")


class OsGateMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated reads and writes of desk and data routes."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if request.method == "OPTIONS":
            return await call_next(request)
        if path_requires_session(request.url.path) and not request_unlocked(request):
            return JSONResponse({"detail": "Sign in required"}, status_code=401)
        return await call_next(request)
