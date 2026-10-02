#!/bin/bash
# =============================================================================
# Rebuilds and installs /Applications/Jarvis.app
# Swift + WKWebView wrapper around the Jarvis AI OS dashboard at
# http://localhost:5173/os/world
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
BUILD="$ROOT/build"
APP="$BUILD/Jarvis.app"
DEST="/Applications/Jarvis.app"

echo "==> Checking prerequisites"
for cmd in swiftc sips iconutil codesign; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: '$cmd' not found. Install Xcode Command Line Tools: xcode-select --install"
    exit 1
  fi
done

rm -rf "$BUILD"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> Icon"
if [ -f "$ROOT/src/make_icon.swift" ]; then
  swiftc -O -o "$BUILD/make_icon" "$ROOT/src/make_icon.swift"
  "$BUILD/make_icon" "$BUILD/icon_1024.png"
else
  echo "    (skipping custom icon — make_icon.swift not found)"
  # Use the pre-made icon if available
  if [ -f "$ROOT/Jarvis.icns" ]; then
    cp "$ROOT/Jarvis.icns" "$APP/Contents/Resources/Jarvis.icns"
  fi
fi

if [ -f "$BUILD/icon_1024.png" ]; then
  ICONSET="$BUILD/Jarvis.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$BUILD/icon_1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s*2)); sips -z $d $d "$BUILD/icon_1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Jarvis.icns"
fi

echo "==> Compile Swift"
swiftc -O -target arm64-apple-macos13.0 -framework AppKit -framework WebKit \
  -o "$APP/Contents/MacOS/Jarvis" "$ROOT/src/main.swift"

echo "==> Copy launcher script"
cp "$ROOT/start-servers.sh" "$APP/Contents/Resources/start-servers.sh"
chmod +x "$APP/Contents/Resources/start-servers.sh"

echo "==> Write Info.plist"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>com.jonathan.jarvis</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>Jarvis</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>$(date +%Y%m%d%H%M)</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSMicrophoneUsageDescription</key><string>Jarvis uses the microphone for hands-free voice commands.</string>
  <key>NSCameraUsageDescription</key><string>Jarvis may use the camera if a dashboard feature requests it.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>Jarvis uses speech recognition for voice commands.</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

echo "==> Sign"
codesign --force --deep -s - "$APP"

echo "==> Install to $DEST"
if pgrep -x Jarvis >/dev/null; then osascript -e 'quit app "Jarvis"' || true; sleep 1; fi
rm -rf "$DEST"
ditto "$APP" "$DEST"
codesign --force --deep -s - "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" || true
touch "$DEST"
codesign --verify --verbose "$DEST"

echo ""
echo "Installed $DEST"
echo ""
echo "Next steps:"
echo "  1. Set the repo path (one-time):"
echo "     mkdir -p ~/.jarvis && echo '$HOME/openjarvis' > ~/.jarvis/repo-path"
echo "  2. Ensure you're on the AI OS branch:"
echo "     cd ~/openjarvis && git checkout cursor/personal-ai-os-133a"
echo "  3. Install frontend deps (one-time):"
echo "     cd ~/openjarvis/frontend && npm install"
echo "  4. Launch Jarvis from /Applications or Spotlight"
echo ""
echo "If it fails to start, check /tmp/jarvis-launcher.log for diagnostics."
