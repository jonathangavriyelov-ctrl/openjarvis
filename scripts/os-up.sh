#!/usr/bin/env bash
# Start the personal AI OS backend and dashboard, print the URL, and exit.
# The processes stay up after this script returns. No API keys are required.
# Ollama is used when it is already running.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${OS_API_PORT:-8000}"
UI_PORT="${OS_UI_PORT:-5173}"
URL="http://127.0.0.1:${UI_PORT}/os/world"
LOG_DIR="${OS_LOG_DIR:-$HOME/.openjarvis}"
DRY=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY=1
fi

export OPENJARVIS_HERMES_MODEL="${OPENJARVIS_HERMES_MODEL:-hermes3:8b}"
export OPENJARVIS_FALLBACK_MODEL="${OPENJARVIS_FALLBACK_MODEL:-qwen3.5:4b}"
export OPENJARVIS_PERSONAL_OS=1

ollama_up() {
  curl -sf --max-time 2 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1
}

port_open() {
  python3 - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.3)
code = sock.connect_ex(("127.0.0.1", int(sys.argv[1])))
sock.close()
sys.exit(0 if code == 0 else 1)
PY
}

echo "Personal AI OS"
echo "  Dashboard  ${URL}"
echo "  API        http://127.0.0.1:${API_PORT}"
echo "  Assistant  ${OPENJARVIS_HERMES_MODEL} on Ollama, or ${OPENJARVIS_FALLBACK_MODEL}, or another local model"
echo "  Chief      OmniRoute when OMNIROUTE_BASE_URL is set, otherwise local"
echo "No API keys are required."

if [ "$DRY" = "1" ]; then
  if ollama_up; then
    echo "backend=jarvis-serve-ollama"
  else
    echo "backend=local-demo"
  fi
  exit 0
fi

if port_open "$UI_PORT" && port_open "$API_PORT"; then
  echo "Already running: ${URL}"
  exit 0
fi

if port_open "$API_PORT" || port_open "$UI_PORT"; then
  echo "Port ${API_PORT} or ${UI_PORT} is already in use."
  echo "Stop that process, or set OS_API_PORT and OS_UI_PORT."
  exit 1
fi

mkdir -p "$LOG_DIR"
API_LOG="${LOG_DIR}/os-api.log"
UI_LOG="${LOG_DIR}/os-ui.log"
API_PID="${LOG_DIR}/os-api.pid"
UI_PID="${LOG_DIR}/os-ui.pid"

cd "$ROOT"
if ollama_up && command -v uv >/dev/null 2>&1; then
  echo "backend=jarvis-serve-ollama"
  nohup uv run jarvis serve --host 127.0.0.1 --port "$API_PORT" -e ollama \
    >>"$API_LOG" 2>&1 &
else
  echo "backend=local-demo"
  if command -v uv >/dev/null 2>&1; then
    nohup uv run python -m openjarvis.personal.local_app \
      --host 127.0.0.1 --port "$API_PORT" >>"$API_LOG" 2>&1 &
  else
    nohup env PYTHONPATH=src python3 -m openjarvis.personal.local_app \
      --host 127.0.0.1 --port "$API_PORT" >>"$API_LOG" 2>&1 &
  fi
fi
echo $! >"$API_PID"
disown "$!" 2>/dev/null || true

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
nohup env VITE_API_URL="http://127.0.0.1:${API_PORT}" \
  "$ROOT/frontend/node_modules/.bin/vite" \
  --host 127.0.0.1 --port "$UI_PORT" --strictPort \
  >>"$UI_LOG" 2>&1 &
echo $! >"$UI_PID"
disown "$!" 2>/dev/null || true

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 30; do
  if curl -sf --max-time 1 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1 \
    && curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:${UI_PORT}/os/world"; then
    ready=1
    break
  fi
  sleep 0.4
done
if [ "$ready" = "1" ]; then
  echo "Ready: ${URL}"
else
  echo "Started. Open ${URL} in a moment if it is not up yet."
  echo "Logs: ${API_LOG} and ${UI_LOG}"
fi
exit 0
