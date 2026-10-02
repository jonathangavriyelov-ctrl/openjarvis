# Jarvis Desktop Wrapper

A native macOS app (Swift + WKWebView) that wraps the OpenJarvis AI OS dashboard.

## What It Does

1. Launches the OpenJarvis backend (`uv run jarvis serve` on port 8000)
2. Launches the Vite frontend (`npm run dev` on port 5173)
3. Waits for both to be healthy
4. Loads `http://localhost:5173/os/world` in a native macOS window

## Prerequisites

- macOS 13.0+ (Ventura or later)
- Xcode Command Line Tools: `xcode-select --install`
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js >= 22.22
- The OpenJarvis repo cloned locally with dependencies installed

## Setup (One-Time)

### 1. Set the repo path

macOS GUI apps don't inherit your shell environment, so the launcher can't
use `$JARVIS_REPO`. Instead, write the path to a config file:

```bash
mkdir -p ~/.jarvis
echo "$HOME/openjarvis" > ~/.jarvis/repo-path
```

The launcher also auto-detects common paths:
`~/openjarvis`, `~/Developer/openjarvis`, `~/Documents/openjarvis`,
`~/code/openjarvis`, `~/projects/openjarvis`, `~/Desktop/openjarvis`.

### 2. Ensure you're on the AI OS branch

The desktop app loads `/os/world` which only exists on the Personal AI OS branch:

```bash
cd ~/openjarvis
git checkout cursor/personal-ai-os-133a
```

### 3. Install frontend dependencies

```bash
cd ~/openjarvis/frontend
npm install
```

### 4. Build and install the desktop app

```bash
cd ~/openjarvis/desktop/macos-wrapper
./build.sh
```

This compiles the Swift app, signs it, and installs to `/Applications/Jarvis.app`.

## Running

Launch Jarvis from `/Applications`, Spotlight, or the dock.

The app will:
1. Show a loading screen with live status updates
2. Start the backend and frontend if they're not already running
3. Load the AI OS dashboard once both are healthy

## Troubleshooting

### App shows error after 90 seconds

The loading screen now shows a diagnostics panel with the last 30 lines of
each log file. You can also check the logs manually:

```bash
cat /tmp/jarvis-launcher.log    # launcher diagnostics
cat /tmp/jarvis-backend.log     # backend (Python) output
cat /tmp/jarvis-frontend.log    # frontend (Vite) output
```

### "Could not find the OpenJarvis repo"

The repo path isn't configured. Set it:

```bash
mkdir -p ~/.jarvis
echo "/full/path/to/openjarvis" > ~/.jarvis/repo-path
```

### "/os/world route may not exist"

You're on the wrong git branch. Switch to the AI OS branch:

```bash
cd ~/openjarvis
git checkout cursor/personal-ai-os-133a
```

### Port already in use

If ports 8000 or 5173 are stuck:

```bash
lsof -i :8000    # find the PID
kill <PID>        # kill it
lsof -i :5173
kill <PID>
```

Then retry launching Jarvis.

### Missing prerequisites

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Node.js (needs >= 22.22)
# From https://nodejs.org/ or via nvm:
nvm install 22
```

## Files

| File | Purpose |
|---|---|
| `src/main.swift` | The Swift macOS app (WKWebView wrapper) |
| `src/make_icon.swift` | Icon generation script |
| `start-servers.sh` | Launcher script (starts backend + frontend) |
| `build.sh` | Builds and installs the .app bundle |
| `Jarvis.icns` | Pre-built app icon |

## Architecture

```
┌─────────────────────────────────────────┐
│           Jarvis.app (Swift)            │
│  ┌─────────────────────────────────┐    │
│  │  WKWebView (localhost:5173)     │    │
│  └──────────────┬──────────────────┘    │
│                 │ starts                 │
│  ┌──────────────▼──────────────────┐    │
│  │  start-servers.sh               │    │
│  │  → uv run jarvis serve :8000    │    │
│  │  → npm run dev :5173            │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
         │                    │
   ┌─────▼──────┐      ┌─────▼──────┐
   │  Backend   │      │  Frontend   │
   │  (Python)  │      │  (Vite/React)│
   │  port 8000 │      │  port 5173  │
   └────────────┘      └─────────────┘
```
