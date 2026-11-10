#!/usr/bin/env python3
"""Debug mode: a remote control for the wall, driven by swipes on the panels. No device I/O.

Swipe down, up, down to switch it on. Then left/right step through your favourites (or every
scene), up switches between Favourites and All, and down switches it off again, leaving the
chosen scene playing. While it's on, four "button" panels stay lit over whatever is showing:
the exit triangle, the Favourites/All hexagon (red = Favourites, green = All) and the
previous/next triangles.

Most scenes can't carry those buttons as they are: the panels' own scenes and the moving
moods are drawn by the controller across every panel. So in debug mode every scene is shown
as ONE custom animation with the button panels held still (`preview`); the animated ones as
an animation of their palette. Switching debug mode off plays the real thing (`play`), the
same way the page would.

nanoleaf_server.py runs it (swipes from the device's touch events, writes through write()).
"""
import json, math, random, re
import effects
import message
from message import CTRL_SHAPE, hex_rgb

# The wall this was made for: the triangle top-left of the lowest hexagon, that hexagon, and
# the two triangles under the bottom arm (left = previous, right = next).
WALL_BUTTONS = {"exit": 2502, "toggle": 13638, "prev": 52676, "next": 29219}
EXIT_C, ARROW_C = (255, 255, 255), (0, 170, 255)
LIST_C = {"favourites": (255, 0, 0), "all": (0, 220, 60)}
SKIP_FX = {"replicate", "simon_play"}          # need the whole wall / the Mac's screen


# ---------------------------------------------------------------- the page's scene data
def load_presets(html):
    """PRESETS and SPEED out of nanoleaf.html (JS object literals -> JSON)."""
    m = re.search(r"const PRESETS=\[(.*?)\n\];", html, re.S)
    out = []
    for line in (m.group(1).strip().splitlines() if m else []):
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        out.append(json.loads(re.sub(r"([{,])(\w+):", r'\1"\2":', line)))
    sp = re.search(r"const SPEED=(\{.*?\});", html)
    speed = json.loads(re.sub(r"(\w+):", r'"\1":', sp.group(1))) if sp else {"medium": [14, 28]}
    return out, speed


# ---------------------------------------------------------------- the page's colour helpers
def _jsround(x):
    return int(math.floor(x + 0.5))


def hsb_rgb(h, s, b):
    """The page's hsbRgb (h 0-360, s/b 0-100)."""
    s /= 100.0; b /= 100.0
    c = b * s; x = c * (1 - abs((h / 60.0) % 2 - 1)); m = b - c
    if h < 60: r, g, bl = c, x, 0
    elif h < 120: r, g, bl = x, c, 0
    elif h < 180: r, g, bl = 0, c, x
    elif h < 240: r, g, bl = 0, x, c
    elif h < 300: r, g, bl = x, 0, c
    else: r, g, bl = c, 0, x
    return tuple(_jsround((n + m) * 255) for n in (r, g, bl))


def show_hsb(h, s, b):
    """The page's showHsb: what a lit panel of that colour looks like."""
    return hsb_rgb(h, s, max(40, b))


def hexs(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def light_ids(st):
    """Light panels in the device's order (the page's lightPanels())."""
    return [p["panelId"] for p in st["panelLayout"]["layout"]["positionData"] if p["shapeType"] != CTRL_SHAPE]


def spread(st, cols):
    ids = light_ids(st)
    return {pid: cols[i % len(cols)] for i, pid in enumerate(ids)}


def static_body(st, rgb_map, fade=8):
    """The page's staticBody (fade: tenths of a second to cross-fade to it)."""
    parts = [str(len(light_ids(st)))]
    for pid in light_ids(st):
        r, g, b = rgb_map.get(pid) or rgb_map.get(str(pid)) or (0, 0, 0)
        parts.append(f"{pid} 1 {r} {g} {b} 0 {max(1, int(fade))}")
    return {"command": "display", "version": "2.0", "animType": "static", "animData": " ".join(parts),
            "loop": False, "palette": []}


def anim_body(sc, speed):
    """The page's animBody: a legacy flow/wheel/random/fade/highlight animation."""
    a, b = speed.get(sc.get("speed") or "medium", [14, 28])
    body = {"command": "display", "version": "2.0", "animType": sc["anim"], "colorType": "HSB", "loop": True,
            "palette": [{"hue": h, "saturation": s, "brightness": br} for h, s, br in sc["palette"]],
            "transTime": {"minValue": a, "maxValue": b}, "delayTime": {"minValue": a, "maxValue": b}}
    if sc["anim"] == "flow":
        body["flowFactor"] = 2.5
    return body


# ---------------------------------------------------------------- which scenes
def entries(st, presets, scenes, favs, which):
    """The scenes debug mode steps through, in the page's order. which: favourites | all."""
    out = []
    for n in (st.get("effects") or {}).get("effectsList") or []:
        out.append({"key": "device:" + n, "kind": "device", "name": n, "label": n, "icon": "💡"})
    for f in effects.catalogue(st):
        if f["name"] not in SKIP_FX:
            out.append({"key": "fx:" + f["name"], "kind": "fx", "name": f["name"], "label": f["label"], "icon": f["icon"]})
    for p in presets:
        out.append({"key": "mood:" + p["name"], "kind": "mood", "name": p["name"], "label": p["name"],
                    "icon": p.get("icon", "🎨"), "scene": p})
    for s in scenes:
        if s.get("kind") == "message" and not message.fits(st):
            continue
        out.append({"key": "mine:" + s["name"], "kind": "mine", "name": s["name"], "label": s["name"],
                    "icon": s.get("icon") or {"painted": "🖌️", "message": "💬"}.get(s.get("kind"), "⭐"), "scene": s})
    if which == "all":
        return out
    by_key = {e["key"].lower(): e for e in out}
    return [by_key[k.lower()] for k in favs if k.lower() in by_key]


def current_key(st, ui, presets, scenes):
    """The entry the wall is showing now, if there is one (the page's displayName logic)."""
    state, eff = st.get("state") or {}, st.get("effects") or {}
    if state.get("colorMode") in ("hs", "ct"):
        return None
    sel = eff.get("select") or ""
    if sel and not sel.startswith("*"):
        return "device:" + sel
    fx = (ui or {}).get("fx") or {}
    if fx.get("name") and fx["name"] not in SKIP_FX:
        return fx.get("key") if fx["name"] == "debug_mode" else "fx:" + fx["name"]
    name = (ui or {}).get("sceneName")
    if name:
        if any(s.get("name") == name for s in scenes):
            return "mine:" + name
        if any(p["name"] == name for p in presets):
            return "mood:" + name
    return None


# ---------------------------------------------------------------- playing it for real
def _message_opts(sc):
    return {k: sc.get(k) for k in ("color", "heart", "bg", "hold", "gap") if sc.get(k) is not None}


def play(e, st, speed, fade=8):
    """How the page would play entry e: (device path, body, _ui fields). fade: still scenes'
    cross-fade in tenths (the page's Crossfade setting)."""
    ui = {"sceneName": None, "panels": {}, "message": None, "fx": None}
    kind, sc = e["kind"], e.get("scene") or {}
    if kind == "device":
        return "/effects", {"select": e["name"]}, ui
    if kind == "fx":
        r = effects.build(e["name"], st)
        ui.update(sceneName=e["label"], fx={"name": e["name"]})
        return "/effects", {"write": r["body"]}, ui
    if sc.get("kind") == "message":
        r = message.build(sc.get("text", ""), st["panelLayout"]["layout"]["positionData"], **_message_opts(sc))
        ui.update(sceneName=sc["name"], message={"text": sc.get("text", "")[:80],
                                                 **{k: r["options"][k] for k in ("color", "heart", "bg", "hold", "gap")}})
        return "/effects", {"write": r["body"]}, ui
    if sc.get("kind") == "painted":
        panels = sc.get("panels") or {}
        ui.update(sceneName=sc["name"], panels=panels)
        return "/effects", {"write": static_body(st, {int(k): hex_rgb(v) for k, v in panels.items()}, fade)}, ui
    cols = [show_hsb(*c) for c in sc.get("palette") or [[0, 0, 100]]]
    if sc.get("anim", "static") == "static":
        m = spread(st, cols)
        ui.update(sceneName=sc["name"], panels={str(k): hexs(v) for k, v in m.items()})
        return "/effects", {"write": static_body(st, m, fade)}, ui
    ui.update(sceneName=sc["name"])
    return "/effects", {"write": anim_body(sc, speed)}, ui


# ---------------------------------------------------------------- debug-mode previews
def buttons(st):
    """{role: panelId} for the four button panels."""
    shapes = effects.light_shapes(st)
    ids = {p["panelId"] for p, _ in shapes}
    if set(WALL_BUTTONS.values()) <= ids:
        return dict(WALL_BUTTONS)
    # Another wall: the lowest-left panel that sticks out, the panel next to it, then the two
    # panels nearest that one (left = previous).
    pos = {p["panelId"]: effects.centre(pts) for p, pts in shapes}
    adj = effects.adjacency(shapes)
    leaves = [i for i in pos if len(adj[i]) == 1] or list(pos)
    ex = max(leaves, key=lambda i: (pos[i][1], -pos[i][0]))
    rest = [i for i in pos if i != ex]
    if not rest:
        return {"exit": ex}
    tog = min(adj[ex] or rest, key=lambda i: math.hypot(pos[i][0] - pos[ex][0], pos[i][1] - pos[ex][1]))
    near = sorted((i for i in pos if i not in (ex, tog)),
                  key=lambda i: math.hypot(pos[i][0] - pos[tog][0], pos[i][1] - pos[tog][1]))[:2]
    near.sort(key=lambda i: pos[i][0])
    out = {"exit": ex, "toggle": tog}
    out.update(zip(("prev", "next"), near))
    return out


def button_colours(st, which):
    b = buttons(st)
    col = {"exit": EXIT_C, "toggle": LIST_C.get(which, LIST_C["favourites"]), "prev": ARROW_C, "next": ARROW_C}
    return {pid: col[role] for role, pid in b.items()}


def _parse_custom(anim):
    """animData of a custom/static body -> {panelId: [(rgb, tenths)]}."""
    a = anim.split(); n = int(a[0]); i = 1; per = {}
    for _ in range(n):
        pid, nf = int(a[i]), int(a[i + 1]); i += 2
        fr = []
        for _ in range(nf):
            r, g, b, _w, t = (int(x) for x in a[i:i + 5]); i += 5
            fr.append(((r, g, b), t))
        per[pid] = fr
    return per


def palette_anim(st, cols, anim, speed_range, seed):
    """An animation of a palette, for scenes the controller would draw across the whole wall:
    flow/wheel = the colours roll across the wall; the rest = panels drift through the colours
    at their own pace."""
    shapes = effects.light_shapes(st)
    pos = {p["panelId"]: effects.centre(pts) for p, pts in shapes}
    n = len(cols)
    if n == 1:
        return {pid: [(cols[0], 10)] for pid in pos}
    t = max(3, int(sum(speed_range) / 2))
    x0 = min(x for x, _ in pos.values()); x1 = max(x for x, _ in pos.values())
    rnd = random.Random(seed)
    per = {}
    for pid in sorted(pos):
        if anim in ("flow", "wheel"):
            k = int(round((pos[pid][0] - x0) / max(1, x1 - x0) * (n - 1)))
        else:
            k = rnd.randrange(n)
        per[pid] = [(cols[(k + j) % n], t) for j in range(n)]
    return per


def preview(e, st, speed, palettes, which):
    """Entry e as ONE looping custom animation with the button panels lit.
    Returns (body, {panelId: "#hex"} of its first frame for the page)."""
    kind, sc = e["kind"], e.get("scene") or {}
    if kind == "fx":
        per = effects.build(e["name"], st)["per"]
    elif kind == "device":
        p = (palettes or {}).get(e["name"]) or {}
        cols = [show_hsb(c["h"], c["s"], c["b"]) for c in p.get("palette") or []] or [(90, 90, 90)]
        per = palette_anim(st, cols, "random", speed.get("medium", [14, 28]), e["name"])
    elif sc.get("kind") in ("message", "painted"):
        path, body, _ = play(e, st, speed)
        per = _parse_custom(body["write"]["animData"])
        if sc.get("kind") == "painted":
            per = {pid: [(fr[0][0], 10)] for pid, fr in per.items()}
    else:
        cols = [show_hsb(*c) for c in sc.get("palette") or [[0, 0, 100]]]
        if sc.get("anim", "static") == "static":
            per = {pid: [(c, 10)] for pid, c in spread(st, cols).items()}
        else:
            per = palette_anim(st, cols, sc["anim"], speed.get(sc.get("speed") or "medium", [14, 28]), e["key"])
    total = sum(t for _, t in next(iter(per.values())))
    for pid, c in button_colours(st, which).items():
        per[pid] = [(c, total)]
    totals = {sum(t for _, t in fr) for fr in per.values()}
    if len(totals) != 1:
        raise ValueError(f"{e['key']}: panels have different loop lengths {sorted(totals)}")
    first = {str(pid): hexs(fr[0][0]) for pid, fr in per.items()}
    return effects.body_from(per), first
