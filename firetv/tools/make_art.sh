#!/bin/bash
# Draw the TV launcher art into $1 (a res/ dir): drawable/banner.png (320x180 Fire TV banner)
# and mipmap-*/ic_launcher.png. Same hexagons + heart as the Mac app icon (app/make_icon.sh).
set -e
RES="$1"; TMP="$(mktemp -d)"
HEX='<g filter="url(#glow)" opacity=".75">
      <polygon points="-96,-244 -224,-170 -224,-22 -96,52 32,-22 32,-170" fill="url(#a)"/>
      <polygon points="192,-244 64,-170 64,-22 192,52 320,-22 320,-170" fill="url(#b)"/>
      <polygon points="48,10 -80,84 -80,232 48,306 176,232 176,84" fill="url(#c)"/>
    </g>
    <polygon points="-96,-244 -224,-170 -224,-22 -96,52 32,-22 32,-170" fill="url(#a)"/>
    <polygon points="192,-244 64,-170 64,-22 192,52 320,-22 320,-170" fill="url(#b)"/>
    <polygon points="48,10 -80,84 -80,232 48,306 176,232 176,84" fill="url(#c)"/>
    <path d="M48 250 C 0 210 -34 184 -34 150 c0 -26 20 -44 44 -44 c 18 0 32 10 38 24 c 6 -14 20 -24 38 -24 c 24 0 44 18 44 44 c 0 34 -34 60 -82 100 z" fill="#fff" opacity=".95"/>'
DEFS='<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#241c48"/><stop offset="1" stop-color="#0b0d14"/></linearGradient>
    <linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00e0ff"/><stop offset="1" stop-color="#0a84ff"/></linearGradient>
    <linearGradient id="b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8b5cff"/><stop offset="1" stop-color="#5e5ce6"/></linearGradient>
    <linearGradient id="c" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff5c8a"/><stop offset="1" stop-color="#ff2d55"/></linearGradient>
    <filter id="glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="18"/></filter>
  </defs>'

# Banner: drawn on a 1280x1280 square (qlmanage thumbnails are square), banner in the middle 720px band, then centre-cropped.
cat > "$TMP/banner.svg" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1280" viewBox="0 0 1280 1280">
  $DEFS
  <rect width="1280" height="1280" fill="#0b0d14"/>
  <g transform="translate(0 280)">
  <rect width="1280" height="720" fill="url(#bg)"/>
  <g transform="translate(290 335) scale(.95)">$HEX</g>
  <text x="575" y="375" font-family="Helvetica Neue, Helvetica, Arial" font-weight="700" font-size="150" fill="#ffffff">Nanoleaf</text>
  <text x="581" y="475" font-family="Helvetica Neue, Helvetica, Arial" font-size="70" fill="#b9b2ff">Shapes</text>
  </g>
</svg>
SVG
cat > "$TMP/icon.svg" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  $DEFS
  <rect x="64" y="64" width="896" height="896" rx="200" fill="url(#bg)"/>
  <g transform="translate(512 470)">$HEX</g>
</svg>
SVG
qlmanage -t -s 1280 -o "$TMP" "$TMP/banner.svg" >/dev/null 2>&1
qlmanage -t -s 1024 -o "$TMP" "$TMP/icon.svg" >/dev/null 2>&1
mkdir -p "$RES/drawable-xhdpi" "$RES/drawable"
sips -c 720 1280 "$TMP/banner.svg.png" --out "$TMP/banner_full.png" >/dev/null
sips -z 180 320 "$TMP/banner_full.png" --out "$RES/drawable/banner.png" >/dev/null
sips -z 360 640 "$TMP/banner_full.png" --out "$RES/drawable-xhdpi/banner.png" >/dev/null
for d in mdpi:48 hdpi:72 xhdpi:96 xxhdpi:144 xxxhdpi:192; do
  mkdir -p "$RES/mipmap-${d%%:*}"
  sips -z "${d##*:}" "${d##*:}" "$TMP/icon.svg.png" --out "$RES/mipmap-${d%%:*}/ic_launcher.png" >/dev/null
done
rm -rf "$TMP"
