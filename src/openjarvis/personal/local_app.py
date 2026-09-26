"""Personal AI OS server that starts with no API keys.

Ollama is used when it is already running. Otherwise the desk still opens
and the agents use their offline notes.
"""

from __future__ import annotations

import argparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openjarvis.personal.gate import OsGateMiddleware
from openjarvis.personal.routes import mount_personal

_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
)


def create_app(*, probe_ollama: bool = True) -> FastAPI:
    """API for the dashboard. Cloud keys are not read."""
    app = FastAPI(title="Personal AI OS")
    # The gate is added first so CORS stays outermost and can label 401s.
    app.add_middleware(OsGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_ORIGINS),
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.engine = _ollama_engine() if probe_ollama else None
    app.state.model = ""
    mount_personal(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _ollama_engine():
    from openjarvis.engine.ollama import OllamaEngine

    candidate = OllamaEngine()
    try:
        if candidate.health():
            return candidate
    except Exception:
        pass
    candidate.close()
    return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Start the personal AI OS without API keys."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
