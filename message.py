#!/usr/bin/env python3
"""Spell a message on the Nanoleaf Shapes, one character at a time.

The wall has 9 hexagons and 10 mini triangles, so it cannot show a whole word at
once. Instead the panels cycle through the characters: each one is drawn by turning
a set of panels on (the others off, or a dim background colour). The whole cycle is
sent to the controller as ONE custom looping animation, so the device plays it by
itself forever with no further network traffic.

Which panels make up each character lives in glyphs.json next to this file.

Used by nl.py (`./nl.py say "I <3 YOU"`) and by the web page's Message tab.
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL_SHAPE = 12
HEART = "♥"

DEFAULTS = {
    "color": "#ffffff",     # letters
    "heart": "#ff1a3c",     # the heart (pulses to a lighter tint of this)
    "bg": "#000000",        # panels that are not part of the character (black = off)
    "hold": 2.0,            # seconds each character stays up once fully drawn
    "gap": 0.5,             # seconds of blank between characters
    "fade": 0.3,            # seconds to fade between steps
    "stroke": 0.22,         # seconds per stroke while a character draws itself
}


def strokes_of(glyph):
    """A glyph is a list of strokes (each a list of panel ids); a flat list is one stroke."""
    if glyph and isinstance(glyph[0], list):
        return [list(st) for st in glyph]
    return [list(glyph)]


def load_glyphs():
    with open(os.path.join(HERE, "glyphs.json"), encoding="utf8") as f:
        d = json.load(f)
    return d["glyphs"], d.get("aliases", {})


def glyph_panel_ids(glyphs=None):
    glyphs = glyphs if glyphs is not None else load_glyphs()[0]
    return {pid for g in glyphs.values() if isinstance(g, list) for st in strokes_of(g) for pid in st}


def fits(layout_json):
    """Do glyphs.json's panel ids exist in this device? True/False, or None if the layout is unknown.

    The letters are drawn on specific panel ids of one particular wall, so on anyone
    else's layout messages can't be spelled until glyphs.json is redrawn for it."""
    try:
        have = {p["panelId"] for p in layout_json["panelLayout"]["layout"]["positionData"]}
    except (KeyError, TypeError):
        return None
    return glyph_panel_ids() <= have


def hex_rgb(h):
    h = str(h).lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Bad colour '{h}' - use #rrggbb")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tint(rgb, amount=0.45):
    """Move a colour towards white (for the heart's beat)."""
    return tuple(int(round(c + (255 - c) * amount)) for c in rgb)


def parse(text, glyphs=None, aliases=None):
    """Turn text into a list of characters the wall can draw.

    Returns (tokens, unsupported). tokens are glyph keys or " " for a blank.
    Emoji hearts, "<3" and "❤️" all become the heart glyph.
    """
    if glyphs is None:
        glyphs, aliases = load_glyphs()
    aliases = aliases or {}
    s = text.strip()
    # longest aliases first so "<3" and multi-codepoint emoji match whole
    keys = sorted(aliases, key=len, reverse=True)
    tokens, bad, i = [], [], 0
    while i < len(s):
        hit = None
        for k in keys:
            if s.startswith(k, i):
                hit = k
                break
        if hit:
            tokens.append(aliases[hit]); i += len(hit); continue
        ch = s[i]; i += 1
        if ch == "️":             # stray emoji variation selector
            continue
        if ch.isspace():
            if tokens and tokens[-1] != " ":
                tokens.append(" ")
            continue
        up = ch.upper()
        if up in glyphs:
            tokens.append(up)
        else:
            bad.append(ch)
    return tokens, sorted(set(bad))


def steps_for(token, glyphs, o):
    """The timed steps for one character: list of (lit_panel_set, rgb, tenths_of_sec)
    plus the index of the step where the character is fully drawn.

    A character draws itself stroke by stroke (each stroke adds panels), then holds,
    then fades to blank with a short pause. The heart holds with a heartbeat
    (two quick pulses) instead of sitting still.
    """
    T = lambda sec: max(1, int(round(sec * 10)))
    fade, hold, gap, per = T(o["fade"]), T(o["hold"]), T(o["gap"]), T(o["stroke"])
    off = None                               # None = background colour
    none = frozenset()
    if token == " ":
        return [(none, off, fade), (none, off, hold)], 1
    strokes = strokes_of(glyphs.get(token, []))
    col = hex_rgb(o["heart"] if token == HEART else o["color"])
    steps, lit = [], set()
    for st in strokes:                       # the reveal
        lit |= set(st)
        steps.append((frozenset(lit), col, per))
    full = frozenset(lit)
    key = len(steps)
    if token == HEART:
        pink = tint(col)
        rest = max(2, hold - 8)
        first, second = rest // 2, rest - rest // 2
        steps += [(full, col, first), (full, pink, 2), (full, col, 2), (full, pink, 2),
                  (full, col, 2), (full, col, second)]
    else:
        steps += [(full, col, hold)]
    steps += [(none, off, fade), (none, off, gap)]
    return steps, key


def build(text, panels, **opts):
    """Build the animation for `text`.

    panels: the light panels' positionData (list of dicts with panelId/shapeType).
    Returns dict(tokens, frames, body, seconds) where frames is a list of
    (per-panel {id: rgb}, tenths) suitable for previews and `body` is the JSON to
    PUT to /effects as {"write": body}.
    """
    o = dict(DEFAULTS); o.update({k: v for k, v in opts.items() if v is not None and k in DEFAULTS})
    glyphs, aliases = load_glyphs()
    tokens, bad = parse(text, glyphs, aliases)
    if bad:
        raise ValueError("The wall can't draw: " + " ".join(bad) +
                         "  (it can do: " + " ".join(sorted(glyphs)) + ")")
    if not tokens:
        raise ValueError("Nothing to show")
    bg = hex_rgb(o["bg"])
    ids = [p["panelId"] for p in panels if p["shapeType"] != CTRL_SHAPE]
    if not glyph_panel_ids(glyphs) <= set(ids):
        raise ValueError("Messages are drawn for one specific wall layout and glyphs.json doesn't match "
                         "your panels. Redraw glyphs.json with your panel ids (`./nl.py panels`).")
    frames, keyframes = [], []
    for tok in tokens:
        steps, key = steps_for(tok, glyphs, o)
        keyframes.append(len(frames) + key)        # the step where the character is fully drawn
        for lit, rgb, t in steps:
            frames.append(({pid: (rgb if (rgb is not None and pid in lit) else bg) for pid in ids}, t))
    parts = [str(len(ids))]
    for pid in ids:
        parts.append(f"{pid} {len(frames)}")
        for cmap, t in frames:
            r, g, b = cmap[pid]
            parts.append(f"{r} {g} {b} 0 {t}")
    body = {"command": "display", "version": "2.0", "animType": "custom",
            "animData": " ".join(parts), "loop": True, "palette": []}
    return {"tokens": tokens, "frames": frames, "keyframes": keyframes, "body": body,
            "seconds": sum(t for _, t in frames) / 10.0, "options": o}


def to_json(result):
    """The build result with colours as #hex strings, for the web page."""
    hx = lambda rgb: "#%02x%02x%02x" % rgb
    return {
        "tokens": result["tokens"],
        "frames": [[{str(k): hx(v) for k, v in cmap.items()}, t] for cmap, t in result["frames"]],
        "keyframes": result["keyframes"],
        "seconds": result["seconds"],
        "options": result["options"],
    }


# ------------------------------------------------------------------ preview
def _verts(p):
    RH, RT = 67, 38.7
    o = p.get("o", 0); pts = []
    if p["shapeType"] == 7:
        for k in range(6):
            a = math.radians(k * 60); pts.append((p["x"] + math.cos(a) * RH, p["y"] + math.sin(a) * RH))
    else:
        for k in range(3):
            a = math.radians(90 + o + k * 120); pts.append((p["x"] + math.cos(a) * RT, p["y"] + math.sin(a) * RT))
    return pts


def wall_shapes(layout_json):
    """Panel polygons in screen space (rotation applied, y flipped) -> [(panel, pts)]."""
    pl = layout_json["panelLayout"]; L = pl["layout"]["positionData"]
    rot = math.radians((pl.get("globalOrientation") or {}).get("value", 0))
    cx = sum(p["x"] for p in L) / len(L); cy = sum(p["y"] for p in L) / len(L)
    c, s = math.cos(rot), math.sin(rot)
    def tr(x, y):
        dx, dy = x - cx, y - cy
        return (cx + dx * c - dy * s, -(cy + dx * s + dy * c))
    return [(p, [tr(*v) for v in _verts(p)]) for p in L]


def preview_svg(layout_json, colour_maps, labels=None, cell=260):
    """One SVG showing several colour maps side by side (each a {panelId: rgb})."""
    shapes = wall_shapes(layout_json)
    xs = [x for _, pts in shapes for x, _ in pts]; ys = [y for _, pts in shapes for _, y in pts]
    mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
    w, h = mxx - mnx, mxy - mny
    sc = (cell - 20) / max(w, h)
    cols = min(4, len(colour_maps)); rows = (len(colour_maps) + cols - 1) // cols
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols*cell}" height="{rows*(cell+24)}" '
           f'viewBox="0 0 {cols*cell} {rows*(cell+24)}"><rect width="100%" height="100%" fill="#0d1017"/>']
    for i, cmap in enumerate(colour_maps):
        ox = (i % cols) * cell + 10; oy = (i // cols) * (cell + 24) + 24
        if labels:
            out.append(f'<text x="{ox+ (cell-20)/2}" y="{oy-6}" fill="#9aa3b2" font-size="16" '
                       f'text-anchor="middle" font-family="sans-serif">{labels[i]}</text>')
        for p, pts in shapes:
            if p["shapeType"] == CTRL_SHAPE:        # the controller has no lights: not drawn
                continue
            rgb = cmap.get(p["panelId"])
            if rgb is None or rgb == (0, 0, 0):
                fill = "#1b1f27"
            else:
                fill = "#%02x%02x%02x" % rgb
            pts_s = " ".join(f"{ox+(x-mnx)*sc:.1f},{oy+(y-mny)*sc:.1f}" for x, y in pts)
            out.append(f'<polygon points="{pts_s}" fill="{fill}" stroke="#06080c" stroke-width="2" stroke-linejoin="round"/>')
    out.append("</svg>")
    return "\n".join(out)
