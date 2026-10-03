#!/bin/bash
# Build NanoManager.app.
#   ./build_app.sh            build and install into /Applications (for working on the app)
#   ./build_app.sh --release  build a universal (Apple silicon + Intel) app and zip it to
#                             ../dist/NanoManager-mac.zip, with none of your own data in it
# Needs the Xcode Command Line Tools (xcode-select --install) for swiftc.
set -e
cd "$(dirname "$0")"
MODE="${1:-install}"
SRC_DIR="$(cd .. && pwd)"          # the repo folder with the server in it
APP=NanoManager
BUILD="$PWD/build"
BUNDLE="$BUILD/$APP.app"
rm -rf "$BUILD"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources/nanoleaf"

echo "• compiling"
cp NanoManager.swift "$BUILD/main.swift"
LIBS=(-framework Cocoa -framework WebKit -framework ScreenCaptureKit -framework CoreMedia)
if [ "$MODE" = "--release" ]; then
  for arch in arm64 x86_64; do
    swiftc -O -swift-version 5 -target "$arch-apple-macos13.0" -o "$BUILD/$APP-$arch" "$BUILD/main.swift" "${LIBS[@]}"
  done
  lipo -create -output "$BUNDLE/Contents/MacOS/$APP" "$BUILD/$APP-arm64" "$BUILD/$APP-x86_64"
  rm -f "$BUILD/$APP-arm64" "$BUILD/$APP-x86_64"
else
  swiftc -O -swift-version 5 -o "$BUNDLE/Contents/MacOS/$APP" "$BUILD/main.swift" "${LIBS[@]}"
fi
cp Info.plist "$BUNDLE/Contents/"
echo -n "APPL????" > "$BUNDLE/Contents/PkgInfo"

echo "• bundling the server (the app runs this copy; rebuild after editing the repo)"
FILES="nanoleaf_server.py nanoleaf.html message.py effects.py replicate.py glyphs.json nl.py"
# For yourself the app is seeded with your pairing + saved scenes; a release carries none of that.
[ "$MODE" = "--release" ] || FILES="$FILES token.txt palettes.json scenes.json ui_state.json"
for f in $FILES; do
  [ -f "$SRC_DIR/$f" ] && cp "$SRC_DIR/$f" "$BUNDLE/Contents/Resources/nanoleaf/"
done
# phone layout + Home Screen icons, served to phones on the Wi-Fi
cp -R "$SRC_DIR/mobile" "$BUNDLE/Contents/Resources/nanoleaf/mobile"

echo "• icon"
./make_icon.sh "$BUNDLE/Contents/Resources/AppIcon.icns"

# Signing. A release is signed ad hoc (no Apple Developer account needed; see the README
# for the one-time "open anyway" step). For your own builds, a self-signed identity called
# "NanoManager Local Signing" in your keychain keeps macOS's Screen Recording permission
# across rebuilds (an ad-hoc signature changes every build, which resets it).
SIGN_ID="-"
if [ "$MODE" != "--release" ]; then
  SIGN_ID="$(security find-identity -p codesigning 2>/dev/null | awk -F'"' '/NanoManager Local Signing/{split($1,a," "); print a[2]; exit}')"
  if [ -n "$SIGN_ID" ]; then echo "• signing (NanoManager Local Signing)"; else SIGN_ID="-"; echo "• signing (ad hoc: Screen Recording must be re-allowed after each build)"; fi
else
  echo "• signing (ad hoc)"
fi
# macOS tags freshly written files with metadata that codesign rejects on the first
# pass ("detritus"); signing rewrites the files, so a retry after clearing goes through.
for attempt in 1 2 3; do
  find "$BUNDLE" -name _CodeSignature -prune -exec rm -rf {} + 2>/dev/null
  xattr -cr "$BUNDLE" 2>/dev/null
  if codesign --force --deep -s "$SIGN_ID" "$BUNDLE" >/dev/null 2>"$BUILD/codesign.err"; then
    xattr -cr "$BUNDLE" 2>/dev/null          # signing re-tags files; clear again before verifying
    codesign --verify --deep --strict "$BUNDLE" 2>>"$BUILD/codesign.err" && break
  fi
done
codesign --verify --deep --strict "$BUNDLE" || { cat "$BUILD/codesign.err"; exit 1; }

if [ "$MODE" = "--release" ]; then
  mkdir -p "$SRC_DIR/dist"
  rm -f "$SRC_DIR/dist/NanoManager-mac.zip"
  ditto -c -k --keepParent "$BUNDLE" "$SRC_DIR/dist/NanoManager-mac.zip"
  echo "done: $SRC_DIR/dist/NanoManager-mac.zip ($(du -h "$SRC_DIR/dist/NanoManager-mac.zip" | cut -f1 | xargs))"
  exit 0
fi

echo "• installing to /Applications"
if pgrep -xq "$APP"; then osascript -e "tell application \"$APP\" to quit" >/dev/null 2>&1 || true; sleep 1; fi
rm -rf "/Applications/$APP.app"
cp -R "$BUNDLE" "/Applications/$APP.app"
echo "done: /Applications/$APP.app  (data: ~/Library/Application Support/NanoManager)"
