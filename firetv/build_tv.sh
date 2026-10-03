#!/bin/bash
# Build the Fire TV / Android TV app (no Gradle: aapt2 + javac + d8 + apksigner) -> ../dist/NanoManager-TV.apk
#   ./build_tv.sh                      the app everyone can use (finds + pairs with the panels itself)
#   ./build_tv.sh --wall               also bake in effects + messages for YOUR wall (needs the panels
#                                      reachable and NANOLEAF_IP set); the APK then holds your token: keep it private
#   ./build_tv.sh --install            install on the TV afterwards:  FIRETV=<tv ip>:5555 ./build_tv.sh --install
# Needs: a JDK 17 (brew install openjdk@17), the Android SDK with platforms;android-30 and build-tools;34.0.0
# (brew install --cask android-commandlinetools, then sdkmanager "platforms;android-30" "build-tools;34.0.0"),
# and adb (brew install --cask android-platform-tools) for --install.
set -euo pipefail
cd "$(dirname "$0")"
WALL=""; INSTALL=""
for a in "$@"; do case "$a" in --wall) WALL=--wall ;; --install) INSTALL=1 ;; *) echo "unknown option $a"; exit 2 ;; esac; done
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BT="$SDK/build-tools/34.0.0"
JAR="$SDK/platforms/android-30/android.jar"
PKG=io.github.cammycodes.nanomanager.tv
OUT=build
KS="${KEYSTORE:-signing/nanoleaf-tv.keystore}"
KSPASS="${KSPASS:-nanoleaf-tv-local}"
if [ -n "$WALL" ]; then APK=../dist/NanoManager-TV-wall.apk; else APK=../dist/NanoManager-TV.apk; fi

rm -rf "$OUT"; mkdir -p "$OUT"/{assets,gen,classes,dex} ../dist

echo "• data ${WALL:+(your wall: effects + messages)}"
/usr/bin/python3 tools/gen_data.py $WALL "$OUT/assets"
cp assets/* "$OUT/assets/"

echo "• art"
tools/make_art.sh "$OUT/res"

echo "• resources"
"$BT/aapt2" compile --dir "$OUT/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$JAR" --manifest AndroidManifest.xml \
  -A "$OUT/assets" "$OUT/res.zip" --java "$OUT/gen" --min-sdk-version 22 --target-sdk-version 30

echo "• java"
"$JAVA_HOME/bin/javac" --release 8 -nowarn -classpath "$JAR" -d "$OUT/classes" \
  $(find src "$OUT/gen" -name '*.java')
"$BT/d8" --release --min-api 22 --lib "$JAR" --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')

echo "• package + sign"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -j ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
if [ ! -f "$KS" ]; then
  mkdir -p "$(dirname "$KS")"
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KS" -storepass "$KSPASS" -keypass "$KSPASS" \
    -alias tv -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=NanoManager TV" >/dev/null 2>&1
  echo "  made a signing key at $KS (keep it: updates must be signed with the same key)"
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$KSPASS" --ks-key-alias tv --out "$APK" "$OUT/aligned.apk"
rm -f "$APK.idsig"
echo "• built $APK ($(du -h "$APK" | cut -f1 | xargs))"

if [ -n "$INSTALL" ]; then
  : "${FIRETV:?set FIRETV to the address of the TV, e.g. FIRETV=192.168.1.50:5555}"
  echo "• installing on $FIRETV"
  adb connect "$FIRETV" >/dev/null
  adb -s "$FIRETV" install -r "$APK"
  adb -s "$FIRETV" shell am start -n "$PKG/.MainActivity" >/dev/null
  echo "  opened on the TV"
fi
