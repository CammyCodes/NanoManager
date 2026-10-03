#!/bin/bash
# Install NanoManager on a Mac:
#   curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-mac.sh | bash
# Downloads the latest release, puts NanoManager.app in /Applications (or ~/Applications), and opens it.
# Files fetched with curl aren't quarantined, so macOS doesn't show the "unidentified developer" warning.
set -euo pipefail
URL="https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-mac.zip"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

[ "$(uname)" = "Darwin" ] || { echo "This installer is for macOS."; exit 1; }
echo "• downloading NanoManager"
curl -fL --progress-bar -o "$TMP/NanoManager-mac.zip" "$URL"
echo "• unpacking"
ditto -x -k "$TMP/NanoManager-mac.zip" "$TMP"

DEST=/Applications
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
if pgrep -xq NanoManager; then osascript -e 'tell application "NanoManager" to quit' >/dev/null 2>&1 || true; sleep 1; fi
rm -rf "$DEST/NanoManager.app"
cp -R "$TMP/NanoManager.app" "$DEST/"
xattr -dr com.apple.quarantine "$DEST/NanoManager.app" 2>/dev/null || true
echo "• installed to $DEST/NanoManager.app"

# The app runs its server with the Mac's built-in python3, which needs the Command Line Tools.
if ! xcode-select -p >/dev/null 2>&1; then
  echo
  echo "macOS needs its free 'Command Line Tools' once (they provide python3)."
  echo "A window is about to ask to install them: click Install, wait a few minutes, then open NanoManager again."
  xcode-select --install 2>/dev/null || true
  exit 0
fi
open "$DEST/NanoManager.app"
echo "Opened. First time: follow the pairing steps in the window (hold the controller's power button for 5-7 seconds)."
