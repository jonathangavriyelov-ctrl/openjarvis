#!/bin/bash
# =============================================================================
# Jarvis Setup Helper — one-time configuration for the desktop app
# =============================================================================
# Run this once after cloning the repo to configure the desktop launcher.
# =============================================================================
set -euo pipefail

echo "Jarvis Desktop Setup"
echo "===================="
echo ""

# 1. Set the repo path
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Walk up to find the repo root (pyproject.toml)
REPO="$SCRIPT_DIR"
while [ "$REPO" != "/" ] && [ ! -f "$REPO/pyproject.toml" ]; do
  REPO="$(dirname "$REPO")"
done

if [ ! -f "$REPO/pyproject.toml" ]; then
  echo "ERROR: Could not find repo root (no pyproject.toml found)"
  echo "Run this script from inside the openjarvis repo."
  exit 1
fi

echo "Repo detected: $REPO"
mkdir -p "$HOME/.jarvis"
echo "$REPO" > "$HOME/.jarvis/repo-path"
echo "  ✓ Written to ~/.jarvis/repo-path"
echo ""

# 2. Check git branch
if command -v git >/dev/null 2>&1 && [ -d "$REPO/.git" ]; then
  BRANCH="$(cd "$REPO" && git branch --show-current 2>/dev/null || echo 'unknown')"
  echo "Current git branch: $BRANCH"
  if [ "$BRANCH" != "cursor/personal-ai-os-133a" ] && [ "$BRANCH" != "fix/jarvis-desktop-launcher" ]; then
    echo "  ⚠ The desktop app needs the AI OS branch."
    echo "  Run: cd $REPO && git checkout cursor/personal-ai-os-133a"
  else
    echo "  ✓ On the correct branch"
  fi
  echo ""
fi

# 3. Check prerequisites
echo "Checking prerequisites..."
echo ""

MISSING=()

if command -v uv >/dev/null 2>&1; then
  echo "  ✓ uv: $(uv --version 2>/dev/null | head -1)"
else
  echo "  ✗ uv: NOT FOUND"
  MISSING+=("uv")
fi

if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node --version 2>/dev/null)"
  echo "  ✓ node: $NODE_VER"
  # Check version >= 22.22
  NODE_MAJOR="$(echo "$NODE_VER" | sed 's/v//' | cut -d. -f1)"
  if [ "$NODE_MAJOR" -lt 22 ] 2>/dev/null; then
    echo "    ⚠ Node >= 22.22 required, found $NODE_VER"
  fi
else
  echo "  ✗ node: NOT FOUND (needs >= 22.22)"
  MISSING+=("node")
fi

if command -v npm >/dev/null 2>&1; then
  echo "  ✓ npm: $(npm --version 2>/dev/null)"
else
  echo "  ✗ npm: NOT FOUND"
  MISSING+=("npm")
fi

if command -v curl >/dev/null 2>&1; then
  echo "  ✓ curl: installed"
else
  echo "  ✗ curl: NOT FOUND"
  MISSING+=("curl")
fi

if command -v lsof >/dev/null 2>&1; then
  echo "  ✓ lsof: installed"
else
  echo "  ⚠ lsof: not found (port detection won't work)"
fi

echo ""

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Missing prerequisites:"
  for m in "${MISSING[@]}"; do
    echo "  - $m"
  done
  echo ""
  echo "Install instructions:"
  echo "  uv:   curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  node: https://nodejs.org/ (needs >= 22.22)"
  echo ""
  exit 1
fi

# 4. Install frontend dependencies
echo "Installing frontend dependencies..."
cd "$REPO/frontend"
if [ ! -d node_modules ]; then
  npm install
  echo "  ✓ Frontend dependencies installed"
else
  echo "  ✓ Frontend dependencies already installed"
fi
echo ""

# 5. Create Python venv
echo "Setting up Python environment..."
cd "$REPO"
if uv run python -c "import openjarvis" 2>/dev/null; then
  echo "  ✓ Python environment ready"
else
  echo "  Installing Python dependencies (this may take a minute)..."
  uv sync 2>&1 | tail -5
  echo "  ✓ Python environment created"
fi
echo ""

echo "===================="
echo "Setup complete!"
echo "===================="
echo ""
echo "To build and install the desktop app:"
echo "  cd $REPO/desktop/macos-wrapper"
echo "  ./build.sh"
echo ""
echo "Then launch Jarvis from /Applications or Spotlight."
echo ""
echo "If something goes wrong, check /tmp/jarvis-launcher.log"
