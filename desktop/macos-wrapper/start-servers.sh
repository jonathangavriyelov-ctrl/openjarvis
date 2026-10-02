#!/bin/bash
# =============================================================================
# Jarvis Desktop Launcher — starts backend (port 8000) + frontend (port 5173)
# =============================================================================
# Fixes over the original:
#   - Auto-detects the repo path (config file → env → common locations)
#   - Checks prerequisites (uv, node, npm) and logs what's missing
#   - Detects git branch and warns if the AI OS code is missing
#   - Cleans up stale PID files and dead processes before starting
#   - Writes a unified launcher log to /tmp/jarvis-launcher.log
#   - Surfaces actual errors instead of failing silently
#
# Servers are fully detached (setsid + nohup) so they keep running after the
# Jarvis app quits.
# =============================================================================

set -uo pipefail

LAUNCHER_LOG="/tmp/jarvis-launcher.log"
BACKEND_LOG="/tmp/jarvis-backend.log"
FRONTEND_LOG="/tmp/jarvis-frontend.log"
BACKEND_PID="/tmp/jarvis-backend.pid"
FRONTEND_PID="/tmp/jarvis-frontend.pid"
BACKEND_PORT=8000
FRONTEND_PORT=5173

# Required branch — the one with the AI OS / Archipelago / Worlds code.
# The desktop app loads /os/world which only exists on this branch.
REQUIRED_BRANCH="cursor/personal-ai-os-133a"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LAUNCHER_LOG"; }

log "=========================================="
log "Jarvis Desktop Launcher starting"
log "=========================================="

# ---------------------------------------------------------------------------
# 1. Resolve the repo path
#    Order: ~/.jarvis/repo-path file → $JARVIS_REPO env → common locations
# ---------------------------------------------------------------------------
REPO=""

# Config file (survives GUI launch — Finder/Launchpad don't inherit shell env)
if [ -f "$HOME/.jarvis/repo-path" ]; then
  REPO="$(cat "$HOME/.jarvis/repo-path" | tr -d '[:space:]')"
  log "repo: from ~/.jarvis/repo-path → $REPO"
fi

# Environment variable
if [ -z "$REPO" ] && [ -n "${JARVIS_REPO:-}" ]; then
  REPO="$JARVIS_REPO"
  log "repo: from JARVIS_REPO env → $REPO"
fi

# Common locations
if [ -z "$REPO" ]; then
  for candidate in \
    "$HOME/openjarvis" \
    "$HOME/OpenJarvis" \
    "$HOME/Developer/openjarvis" \
    "$HOME/Developer/OpenJarvis" \
    "$HOME/Documents/openjarvis" \
    "$HOME/Documents/OpenJarvis" \
    "$HOME/code/openjarvis" \
    "$HOME/projects/openjarvis" \
    "$HOME/Desktop/openjarvis"; do
    if [ -d "$candidate" ] && [ -f "$candidate/pyproject.toml" ]; then
      REPO="$candidate"
      log "repo: auto-detected → $REPO"
      break
    fi
  done
fi

if [ -z "$REPO" ]; then
  log "ERROR: Could not find the OpenJarvis repo."
  log "Create ~/.jarvis/repo-path with the full path, e.g.:"
  log "  mkdir -p ~/.jarvis"
  log "  echo '/Users/yourname/openjarvis' > ~/.jarvis/repo-path"
  exit 1
fi

if [ ! -d "$REPO" ]; then
  log "ERROR: Repo path does not exist: $REPO"
  exit 1
fi

if [ ! -f "$REPO/pyproject.toml" ]; then
  log "ERROR: $REPO does not look like the OpenJarvis repo (no pyproject.toml)"
  exit 1
fi

log "repo: $REPO"

# ---------------------------------------------------------------------------
# 2. Set up PATH (GUI apps don't inherit the user's shell PATH)
# ---------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export npm_config_engine_strict=false

# ---------------------------------------------------------------------------
# 3. Check prerequisites
# ---------------------------------------------------------------------------
MISSING=()

if ! command -v uv >/dev/null 2>&1; then
  MISSING+=("uv (Python package manager)")
fi
if ! command -v node >/dev/null 2>&1; then
  MISSING+=("node (Node.js)")
fi
if ! command -v npm >/dev/null 2>&1; then
  MISSING+=("npm (Node package manager)")
fi
if ! command -v curl >/dev/null 2>&1; then
  MISSING+=("curl")
fi

if [ ${#MISSING[@]} -gt 0 ]; then
  log "ERROR: Missing prerequisites:"
  for m in "${MISSING[@]}"; do log "  - $m"; done
  log ""
  log "Install instructions:"
  log "  uv:   curl -LsSf https://astral.sh/uv/install.sh | sh"
  log "  node: https://nodejs.org/ (needs >= 22.22)"
  log "  curl: preinstalled on macOS"
  exit 1
fi

log "prerequisites: uv=$(uv --version 2>/dev/null | head -1)  node=$(node --version 2>/dev/null)  npm=$(npm --version 2>/dev/null)"

# ---------------------------------------------------------------------------
# 4. Check git branch — warn if not on the AI OS branch
# ---------------------------------------------------------------------------
if command -v git >/dev/null 2>&1 && [ -d "$REPO/.git" ]; then
  CURRENT_BRANCH="$(cd "$REPO" && git branch --show-current 2>/dev/null || echo 'unknown')"
  log "git branch: $CURRENT_BRANCH"

  if [ "$CURRENT_BRANCH" != "$REQUIRED_BRANCH" ] && [ "$CURRENT_BRANCH" != "fix/jarvis-desktop-launcher" ]; then
    log "WARNING: The desktop app needs the AI OS branch ($REQUIRED_BRANCH)."
    log "         Current branch is '$CURRENT_BRANCH' — /os/world route may not exist."
    log "         To fix: cd $REPO && git checkout $REQUIRED_BRANCH"
  fi
else
  log "git: not a git repo or git not found — skipping branch check"
fi

# ---------------------------------------------------------------------------
# 5. Clean up stale PID files and dead processes
# ---------------------------------------------------------------------------
port_busy()   { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
pid_alive()   { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

# Remove stale PID files (process is dead but PID file remains)
if pid_alive "$BACKEND_PID" 2>/dev/null; then
  log "backend: process $(cat "$BACKEND_PID") still alive"
else
  rm -f "$BACKEND_PID"
fi
if pid_alive "$FRONTEND_PID" 2>/dev/null; then
  log "frontend: process $(cat "$FRONTEND_PID") still alive"
else
  rm -f "$FRONTEND_PID"
fi

# ---------------------------------------------------------------------------
# 6. Health check helpers
# ---------------------------------------------------------------------------
backend_ok()  { curl -fsS -m 3 -o /dev/null http://127.0.0.1:${BACKEND_PORT}/health 2>/dev/null; }
frontend_ok() { curl -fsS -m 3 -o /dev/null http://localhost:${FRONTEND_PORT}/ 2>/dev/null || curl -fsS -m 3 -o /dev/null http://127.0.0.1:${FRONTEND_PORT}/ 2>/dev/null; }

# ---------------------------------------------------------------------------
# 7. Detach helper — starts a process fully detached with setsid
# ---------------------------------------------------------------------------
detach() { # detach <logfile> <pidfile> <cmd...>
  local logf="$1" pidf="$2"; shift 2
  # Use Python's os.setsid as fallback if perl is missing
  if command -v perl >/dev/null 2>&1; then
    nohup perl -e 'use POSIX setsid; setsid; exec @ARGV' "$@" >"$logf" 2>&1 < /dev/null &
  else
    nohup python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" >"$logf" 2>&1 < /dev/null &
  fi
  echo $! > "$pidf"
  log "started PID $(cat "$pidf") → $*"
}

# ---------------------------------------------------------------------------
# 8. Start backend if needed
# ---------------------------------------------------------------------------
if backend_ok; then
  log "backend: already running and healthy"
elif port_busy $BACKEND_PORT || pid_alive "$BACKEND_PID"; then
  log "backend: port $BACKEND_PORT in use but not healthy yet — not starting a duplicate"
  log "  if stuck: lsof -i :$BACKEND_PORT  then  kill <PID>"
else
  log "backend: starting"
  cd "$REPO" && detach "$BACKEND_LOG" "$BACKEND_PID" uv run jarvis serve --port $BACKEND_PORT
fi

# ---------------------------------------------------------------------------
# 9. Start frontend if needed
# ---------------------------------------------------------------------------
if frontend_ok; then
  log "frontend: already running and healthy"
elif port_busy $FRONTEND_PORT || pid_alive "$FRONTEND_PID"; then
  log "frontend: port $FRONTEND_PORT in use but not serving yet — not starting a duplicate"
  log "  if stuck: lsof -i :$FRONTEND_PORT  then  kill <PID>"
else
  log "frontend: starting"
  # Check node_modules
  if [ ! -d "$REPO/frontend/node_modules" ]; then
    log "frontend: node_modules not found — running npm install"
    cd "$REPO/frontend" && npm install >>"$FRONTEND_LOG" 2>&1
  fi
  cd "$REPO/frontend" && detach "$FRONTEND_LOG" "$FRONTEND_PID" npm run dev -- --port $FRONTEND_PORT --strictPort
fi

# ---------------------------------------------------------------------------
# 10. Wait for both to be healthy (max 60 seconds)
# ---------------------------------------------------------------------------
log "waiting for servers to become healthy..."
WAITED=0
while [ $WAITED -lt 60 ]; do
  if backend_ok && frontend_ok; then
    log "both servers healthy after ${WAITED}s"
    log "  backend:  http://127.0.0.1:${BACKEND_PORT}/health"
    log "  frontend: http://localhost:${FRONTEND_PORT}/os/world"
    exit 0
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done

log "TIMEOUT after ${WAITED}s — servers not healthy"
log "  backend_ok=$(backend_ok && echo yes || echo no)  frontend_ok=$(frontend_ok && echo yes || echo no)"
log ""
log "=== Last 20 lines of $BACKEND_LOG ==="
tail -20 "$BACKEND_LOG" 2>/dev/null || log "(no backend log)"
log ""
log "=== Last 20 lines of $FRONTEND_LOG ==="
tail -20 "$FRONTEND_LOG" 2>/dev/null || log "(no frontend log)"
exit 1
