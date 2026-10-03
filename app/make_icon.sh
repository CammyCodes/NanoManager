#!/bin/bash
# Draw the app icon (three glowing hexagons and a heart) and write it as .icns to $1.
set -e
OUT="$1"; TMP="$(mktemp -d)"
cat > "$TMP/icon.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b2030"/><stop offset="1" stop-color="#0b0d14"/></linearGradient>
    <linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00e0ff"/><stop offset="1" stop-color="#0a84ff"/></linearGradient>
    <linearGradient id="b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8b5cff"/><stop offset="1" stop-color="#5e5ce6"/></linearGradient>
    <linearGradient id="c" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff5c8a"/><stop offset="1" stop-color="#ff2d55"/></linearGradient>
    <filter id="glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="18"/></filter>
  </defs>
  <rect x="64" y="64" width="896" height="896" rx="200" fill="url(#bg)"/>
  <g transform="translate(512 470)">
    <g filter="url(#glow)" opacity=".75">
      <polygon points="-96,-244 -224,-170 -224,-22 -96,52 32,-22 32,-170" fill="url(#a)"/>
      <polygon points="192,-244 64,-170 64,-22 192,52 320,-22 320,-170" fill="url(#b)"/>
      <polygon points="48,10 -80,84 -80,232 48,306 176,232 176,84" fill="url(#c)"/>
    </g>
    <polygon points="-96,-244 -224,-170 -224,-22 -96,52 32,-22 32,-170" fill="url(#a)"/>
    <polygon points="192,-244 64,-170 64,-22 192,52 320,-22 320,-170" fill="url(#b)"/>
    <polygon points="48,10 -80,84 -80,232 48,306 176,232 176,84" fill="url(#c)"/>
    <path d="M48 250 C 0 210 -34 184 -34 150 c0 -26 20 -44 44 -44 c 18 0 32 10 38 24 c 6 -14 20 -24 38 -24 c 24 0 44 18 44 44 c 0 34 -34 60 -82 100 z" fill="#fff" opacity=".95"/>
  </g>
</svg>
SVG
qlmanage -t -s 1024 -o "$TMP" "$TMP/icon.svg" >/dev/null 2>&1
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 64 128 256 512; do
  sips -z $s $s "$TMP/icon.svg.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); sips -z $d $d "$TMP/icon.svg.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$OUT"
rm -rf "$TMP"
