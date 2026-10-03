#!/bin/bash
# Build dist/NanoManager-windows.zip on any computer (it never runs Windows code).
# The zip carries the official "embeddable" Python from python.org, so people need to install nothing.
#   ./windows/build_windows_zip.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PYVER="${PYVER:-3.12.10}"
[ "$PYVER" = "3.12.10" ] && PYSHA256="${PYSHA256:-4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3}"
PYZIP="python-$PYVER-embed-amd64.zip"
PYURL="https://www.python.org/ftp/python/$PYVER/$PYZIP"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/NanoManager"; mkdir -p "$ROOT/python" "$ROOT/app" dist

echo "• Python $PYVER (embeddable, from python.org)"
curl -fL --progress-bar -o "$STAGE/$PYZIP" "$PYURL"
[ -z "${PYSHA256:-}" ] || echo "$PYSHA256  $STAGE/$PYZIP" | shasum -a 256 -c -
echo "  sha256 $(shasum -a 256 "$STAGE/$PYZIP" | cut -d' ' -f1)"
unzip -q "$STAGE/$PYZIP" -d "$ROOT/python"
# The embeddable build ignores the script's folder; tell it where the app lives.
PTH="$(ls "$ROOT"/python/python3*._pth)"
printf '../app\n' >> "$PTH"

echo "• app files"
cp nanoleaf_server.py nanoleaf.html effects.py message.py replicate.py glyphs.json nl.py "$ROOT/app/"
cp -R mobile "$ROOT/app/mobile"
cp windows/launcher.py "$ROOT/app/"
cp "windows/Start NanoManager.bat" "windows/Start NanoManager (phone access).bat" windows/README.txt windows/NanoManager.ico LICENSE "$ROOT/"
find "$ROOT" -name '.DS_Store' -delete

rm -f dist/NanoManager-windows.zip
(cd "$STAGE" && zip -qr "$OLDPWD/dist/NanoManager-windows.zip" NanoManager)
echo "done: dist/NanoManager-windows.zip ($(du -h dist/NanoManager-windows.zip | cut -f1 | xargs))"
