#!/bin/bash
# Install the NanoManager TV app on a Fire TV / Android TV from a Mac or Linux computer:
#   curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-firetv.sh | bash -s -- 192.168.1.50
# (use your TV's address). Turn on Settings > My Fire TV > Developer options > ADB debugging first.
# No computer handy? Use the Downloader app on the TV instead (see the README).
set -euo pipefail
TV="${1:?usage: install-firetv.sh <TV address>   e.g. install-firetv.sh 192.168.1.50}"
URL="https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-TV.apk"
command -v adb >/dev/null || { echo "adb isn't installed. Mac: brew install --cask android-platform-tools   Linux: sudo apt install adb"; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "• downloading the app"; curl -fL --progress-bar -o "$TMP/NanoManager-TV.apk" "$URL"
echo "• connecting to $TV (accept 'Allow USB debugging?' on the TV, tick 'Always allow')"
adb connect "$TV:5555" >/dev/null
adb -s "$TV:5555" wait-for-device
adb -s "$TV:5555" install -r "$TMP/NanoManager-TV.apk"
adb -s "$TV:5555" shell am start -n io.github.cammycodes.nanomanager.tv/.MainActivity >/dev/null
echo "Installed and opened. Follow the pairing steps on the TV."
