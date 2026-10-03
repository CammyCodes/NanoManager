#!/usr/bin/env python3
"""Replicate: the wall mirrors the mood of what's on the Mac's main screen.

The NanoManager Mac app captures the screen as a tiny thumbnail (ScreenCaptureKit
scales it on the GPU to ~32x20 pixels, at most once a second, and only when the
screen changes) and posts the pixels to /api/replicate/frame. This module turns
that grid into one colour per panel: the wall's outline is stretched over the
screen, so each panel takes the colours of the same area of the screen (top-left
panel = top-left of the screen).

Colours are "mood" averages, not plain means: vivid pixels count for more than
grey/white/black ones, and saturation gets a small boost, so a colourful picture
on a white page still tints the panels. Nothing here talks to the device; the
server decides when a new frame is different enough to be worth a write.
"""
import colorsys
from effects import light_shapes, centre

GRID_MAX = 64 * 64          # refuse anything bigger than a thumbnail


def _inside(x, y, poly):
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            hit = not hit
        j = i
    return hit


def regions(layout_json, w, h):
    """{panelId: [cell index, ...]}: the grid cells each panel covers once the wall's
    bounding box is stretched over the whole screen."""
    shapes = light_shapes(layout_json)
    xs = [x for _, pts in shapes for x, _ in pts]
    ys = [y for _, pts in shapes for _, y in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = w / max(1e-9, x1 - x0), h / max(1e-9, y1 - y0)
    out = {}
    for p, pts in shapes:
        poly = [((x - x0) * sx, (y - y0) * sy) for x, y in pts]
        cells = [cy * w + cx for cy in range(h) for cx in range(w) if _inside(cx + .5, cy + .5, poly)]
        if not cells:                                   # tiny panel on a coarse grid: nearest cell
            mx, my = centre(poly)
            cells = [min(h - 1, max(0, int(my))) * w + min(w - 1, max(0, int(mx)))]
        out[p["panelId"]] = cells
    return out


def parse_grid(frame):
    """{"w","h","px": hex RGB, 6 chars a pixel} -> (w, h, [(r,g,b), ...])."""
    w, h = int(frame.get("w", 0)), int(frame.get("h", 0))
    px = str(frame.get("px", ""))
    if w < 2 or h < 2 or w * h > GRID_MAX or len(px) != w * h * 6:
        raise ValueError("frame needs w, h and px (6 hex chars per pixel)")
    raw = bytes.fromhex(px)
    return w, h, [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def mood(pixels):
    """One colour for a patch of screen: vivid pixels weigh up to 5x a grey one."""
    tw = r = g = b = 0.0
    for pr, pg, pb in pixels:
        mx, mn = max(pr, pg, pb), min(pr, pg, pb)
        sat = (mx - mn) / mx if mx else 0.0
        wt = 1.0 + 4.0 * sat * (mx / 255.0)
        tw += wt; r += pr * wt; g += pg * wt; b += pb * wt
    if not tw:
        return (0, 0, 0)
    hh, ss, vv = colorsys.rgb_to_hsv(r / tw / 255, g / tw / 255, b / tw / 255)
    ss = min(1.0, ss * 1.35)
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(hh, ss, vv))


class Mapper:
    """Grid -> {panelId: (r,g,b)}, smoothed between frames so flicker doesn't reach the wall."""

    def __init__(self):
        self._key = None
        self._regions = {}
        self.colours = {}

    def update(self, layout_json, frame, smooth=0.35):
        w, h, px = parse_grid(frame)
        pl = layout_json.get("panelLayout") or {}
        key = (repr(pl), w, h)                          # regions only change if the wall is rearranged
        if key != self._key:
            self._regions, self._key = regions(layout_json, w, h), key
        out = {}
        for pid, cells in self._regions.items():
            target = mood([px[i] for i in cells])
            prev = self.colours.get(pid)
            out[pid] = target if prev is None else tuple(
                int(round(p + (t - p) * (1 - smooth))) for p, t in zip(prev, target))
        self.colours = out
        return out


def changed(a, b, tol=10):
    """Is any panel's colour more than tol (0-255, any channel) away from before?"""
    if set(a) != set(b):
        return True
    return any(max(abs(x - y) for x, y in zip(a[k], b[k])) > tol for k in a)


def static_body(colours, fade_tenths=10):
    """One static write that fades every panel to its new colour."""
    parts = [str(len(colours))]
    for pid, (r, g, b) in colours.items():
        parts.append(f"{pid} 1 {r} {g} {b} 0 {fade_tenths}")
    return {"command": "display", "version": "2.0", "animType": "static",
            "animData": " ".join(parts), "loop": False, "palette": []}
