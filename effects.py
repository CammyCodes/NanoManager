#!/usr/bin/env python3
"""Animated effects for the Nanoleaf Shapes: Snake, Starlight, Ripple, Rain, Wave…

Each effect is built as ONE custom looping animation for the controller, so once it
is sent the panels play it by themselves. An effect gives every light panel its own
list of keyframes (colour, tenths of a second to fade to it); all panels' lists add
up to the same total so the loop stays in sync.

Used by nanoleaf_server.py (/api/effects, /api/fx) and importable on its own.
"""
import math, random
from message import wall_shapes, CTRL_SHAPE, hex_rgb

# ---------------------------------------------------------------- geometry
def light_shapes(layout_json):
    """[(panel, polygon)] for the light panels, in screen space (y down)."""
    return [(p, pts) for p, pts in wall_shapes(layout_json) if p["shapeType"] != CTRL_SHAPE]


def centre(pts):
    return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))


def adjacency(shapes, tol=3.0):
    """Panels that share an edge (two vertices within tol)."""
    adj = {p["panelId"]: set() for p, _ in shapes}
    for i, (p, a) in enumerate(shapes):
        for q, b in shapes[i + 1:]:
            shared = sum(1 for x1, y1 in a for x2, y2 in b if abs(x1 - x2) < tol and abs(y1 - y2) < tol)
            if shared >= 2:
                adj[p["panelId"]].add(q["panelId"]); adj[q["panelId"]].add(p["panelId"])
    return adj


def euler_tour(adj, start, pos):
    """Walk the whole wall and come back: every edge twice (the wall is a tree).
    Neighbours are taken clockwise-ish so the snake crawls consistently."""
    tour, seen = [], set()
    def visit(u):
        seen.add(u); tour.append(u)
        ux, uy = pos[u]
        for v in sorted(adj[u], key=lambda v: math.atan2(pos[v][1] - uy, pos[v][0] - ux)):
            if v not in seen:
                visit(v)
                tour.append(u)
    visit(start)
    return tour[:-1] if len(tour) > 1 else tour       # last == start; drop for seamless loop


def bfs_dist(adj, start):
    d = {start: 0}; q = [start]
    for u in q:
        for v in adj[u]:
            if v not in d:
                d[v] = d[u] + 1; q.append(v)
    return d


# ---------------------------------------------------------------- colours
def hsv(h, s, v):
    h = h % 360; s /= 100.0; v /= 100.0
    c = v * s; x = c * (1 - abs((h / 60.0) % 2 - 1)); m = v - c
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(int(round((k + m) * 255)) for k in (r, g, b))


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def dim(c, f):
    return tuple(int(round(k * f)) for k in c)


OFF = (0, 0, 0)


# ---------------------------------------------------------------- timelines
def events_to_frames(events, loop, base=OFF):
    """events: [(start_tenths, [(rgb, tenths), ...])] on one panel, sorted, non-overlapping
    -> keyframes covering exactly `loop` tenths, resting on `base` in between."""
    frames, t = [], 0
    for start, segs in sorted(events):
        if start < t:                     # overlap: skip what doesn't fit
            continue
        if start > t:
            frames.append((base, start - t)); t = start
        for rgb, d in segs:
            if t + d > loop:
                d = loop - t
            if d <= 0:
                break
            frames.append((rgb, d)); t += d
    if t < loop:
        frames.append((base, loop - t))
    return frames


def compress(frames, loop_start_colour=None):
    """Merge holds: (A,3),(A,5) -> (A,8) only when the (A,3) was already a hold of A,
    so fade timings are kept. Cuts the frame count a lot for sparse effects."""
    out = []
    for c, t in frames:
        before = out[-1][0] if out else loop_start_colour
        if out and out[-1][0] == c and before == c and (len(out) >= 2 and out[-2][0] == c or (len(out) == 1 and loop_start_colour == c)):
            out[-1] = (c, out[-1][1] + t)
        else:
            out.append((c, t))
    return out


def grid_to_panels(steps, ids):
    """Global steps [(cmap, tenths)] -> per-panel keyframes (compressed)."""
    per = {}
    for pid in ids:
        fr = [(cmap.get(pid, OFF), t) for cmap, t in steps]
        per[pid] = compress(fr, loop_start_colour=fr[-1][0] if fr else None)
    return per


def sample(per, dt=3):
    """Per-panel keyframes -> global frames every dt tenths (with the device's linear
    fades reproduced), for the page's wall preview."""
    loop = max(sum(t for _, t in fr) for fr in per.values())
    n = max(1, int(math.ceil(loop / dt)))
    out = []
    for k in range(n):
        tm = k * dt
        cmap = {}
        for pid, fr in per.items():
            t0 = 0
            prev = fr[-1][0]
            col = prev
            for c, d in fr:
                if tm < t0 + d:
                    f = (tm - t0) / d if d else 1
                    col = mix(prev, c, min(1, max(0, f)))
                    break
                prev = c; t0 += d
            else:
                col = fr[-1][0]
            cmap[pid] = col
        out.append((cmap, dt))
    return out


def body_from(per):
    """The write body for /effects."""
    parts = [str(len(per))]
    for pid, fr in per.items():
        parts.append(f"{pid} {len(fr)}")
        for (r, g, b), t in fr:
            parts.append(f"{r} {g} {b} 0 {max(1, int(t))}")
    return {"command": "display", "version": "2.0", "animType": "custom",
            "animData": " ".join(parts), "loop": True, "palette": []}


# ---------------------------------------------------------------- effects
def fx_snake(shapes, adj, o):
    """A long round of Snake. The snake follows a route round the wall; an apple sits a
    few panels ahead of it on a panel that hasn't had one yet, so over one loop the
    apple has been on every panel. Eating grows the snake (up to a cap); at the end of
    the round it shrinks back and the loop restarts."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = list(pos)
    start = min(ids, key=lambda i: (-pos[i][1], pos[i][0]))     # bottom-left
    tour = euler_tour(adj, start, pos)
    n = len(tour)
    head_c, body_c, tail_c, apple_c = (190, 255, 90), (30, 200, 70), (0, 70, 25), (255, 40, 40)
    step, base_len, max_len = 3, 3, 7

    def at(i):                                                  # path index -> panel (route repeats)
        return tour[i % n]

    def place_apple(i, length):
        d = 4
        while True:
            pid = at(i + d)
            body = {at(i - k) for k in range(length)}
            if pid not in hosted and pid not in body:
                return i + d
            d += 1

    hosted, length, apple_idx, i, steps = set(), base_len, None, 0, []
    while True:
        head = at(i)
        finished = len(hosted) == len(ids) and apple_idx is None
        if apple_idx is None and not finished:
            apple_idx = place_apple(i, length)
        if apple_idx is not None and i == apple_idx:
            hosted.add(head); length = min(max_len, length + 1); apple_idx = None
        last = finished and i % n == n - 1                       # end of a lap: loop back to the start
        cmap = {pid: OFF for pid in ids}
        for k in range(length):
            pid = at(i - k)
            col = head_c if k == 0 else mix(body_c, tail_c, (k - 1) / max(1, length - 2))
            if cmap[pid] == OFF or k == 0:
                cmap[pid] = col
        if apple_idx is not None and cmap[at(apple_idx)] == OFF:
            cmap[at(apple_idx)] = apple_c
        steps.append((cmap, step))
        if finished and length > base_len:
            length -= 1
        if last:
            break
        i += 1
    return grid_to_panels(steps, ids)


def fx_starlight(shapes, adj, o):
    rnd = random.Random(o.get("seed", 7))
    cols = [hex_rgb(c) for c in o["colors"]]
    loop = 200                                                  # 20 s
    per = {}
    for p, _ in shapes:
        events, t = [], rnd.randint(0, 40)
        while t < loop - 30:
            c = rnd.choice(cols)
            fi, ho, fo = rnd.randint(3, 6), rnd.randint(1, 4), rnd.randint(8, 16)
            peak = dim(c, rnd.uniform(0.55, 1.0))
            events.append((t, [(peak, fi), (peak, ho), (OFF, fo)]))
            t += fi + ho + fo + rnd.randint(8, 45)
        per[p["panelId"]] = events_to_frames(events, loop)
    return per


def fx_ripple(shapes, adj, o):
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    cx = sum(x for x, _ in pos.values()) / len(pos); cy = sum(y for _, y in pos.values()) / len(pos)
    hexes = [p["panelId"] for p, _ in shapes if p["shapeType"] == 7] or list(pos)
    origin = min(hexes, key=lambda i: (pos[i][0] - cx) ** 2 + (pos[i][1] - cy) ** 2)
    dist = bfs_dist(adj, origin)
    if o.get("inward"):                                         # start at the outer panels, close in on the centre
        far = max(dist.values())
        dist = {pid: far - d for pid, d in dist.items()}
    cols = [hex_rgb(c) for c in o["colors"]]
    every, per_ring = 30, 2                                     # new ripple every 3 s
    loop = every * len(cols)
    per = {}
    for pid in pos:
        k = dist.get(pid, 0)
        events = []
        for r, c in enumerate(cols):
            events.append((r * every + k * per_ring, [(c, 2), (c, 1), (dim(c, .15), 6), (OFF, 6)]))
        per[pid] = events_to_frames(events, loop)
    return per


def fx_rain(shapes, adj, o):
    rnd = random.Random(o.get("seed", 3))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    xs = sorted(pos.values(), key=lambda c: c[0])
    # columns: panels whose x is within ~half a hexagon of each other
    cols_x, groups = [], []
    for pid in sorted(pos, key=lambda i: pos[i][0]):
        x = pos[pid][0]
        if cols_x and abs(x - cols_x[-1]) < 60:
            groups[-1].append(pid)
        else:
            cols_x.append(x); groups.append([pid])
    for g in groups:
        g.sort(key=lambda i: pos[i][1])                         # top to bottom
    drop, tail, base = hex_rgb(o["colors"][0]), hex_rgb(o["colors"][1]), hex_rgb(o["colors"][2])
    loop = 120
    events = {pid: [] for pid in pos}
    t = 0
    while t < loop - 20:
        g = rnd.choice(groups)
        for j, pid in enumerate(g):
            events[pid].append((t + j * 2, [(drop, 1), (tail, 2), (base, 6)]))
        t += rnd.randint(4, 12)
    return {pid: events_to_frames(sorted(ev), loop, base=base) for pid, ev in events.items()}


def fx_wave(shapes, adj, o):
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    x0 = min(x for x, _ in pos.values()); x1 = max(x for x, _ in pos.values())
    period, dt = 60, 5                                          # 6 s sweep, keyframe every .5 s
    per = {}
    for pid, (x, _) in pos.items():
        off = (x - x0) / max(1, x1 - x0) * 360
        fr = []
        for k in range(period // dt):
            h = (k * dt / period) * 360 + off
            fr.append((hsv(-h, 100, 100), dt))                  # negative: moves left -> right
        per[pid] = fr
    return per


# Heartbeat lights a heart-shaped set of panels that only exists on the wall this was drawn
# for (one Shapes layout of 9 hexagons + 10 mini triangles). On any other layout it is
# left out of the list instead of lighting nothing.
HEART_PANELS = {53008, 45921, 13856, 40756, 51229, 32012}


def fx_heartbeat(shapes, adj, o):
    heart = HEART_PANELS
    red, bg = hex_rgb(o["colors"][0]), hex_rgb(o["colors"][1])
    beat = [(dim(red, .35), 4), (red, 1), (dim(red, .4), 2), (dim(red, .95), 1), (dim(red, .35), 4)]
    loop = sum(t for _, t in beat)
    per = {}
    for p, _ in shapes:
        pid = p["panelId"]
        per[pid] = list(beat) if pid in heart else [(bg, loop)]
    return per


EFFECTS = {
    "snake":      {"label": "Snake", "icon": "🐍", "fn": fx_snake,
                   "desc": "A snake crawls around the wall eating apples and growing; one round puts an apple on every panel.",
                   "colors": ["#beff5a", "#1ec846", "#ff2828"]},
    "starlight":  {"label": "Starlight", "icon": "✨", "fn": fx_starlight,
                   "desc": "Panels twinkle at random, like a Razer keyboard's starlight.",
                   "colors": ["#ffffff", "#9fd8ff", "#cfe9ff"]},
    "fairydust":  {"label": "Fairy Dust", "icon": "🧚", "fn": fx_starlight,
                   "desc": "Starlight in pastel pink and lilac.",
                   "colors": ["#ffb3d9", "#e0b3ff", "#ffe0f0", "#ffffff"], "seed": 11},
    "ripple":     {"label": "Ripple", "icon": "🫧", "fn": fx_ripple,
                   "desc": "Rings of colour spread out from the centre.",
                   "colors": ["#00e0ff", "#a05cff", "#ff5cc8"]},
    "ripple_in":  {"label": "Ripple In", "icon": "🎯", "fn": fx_ripple, "inward": True,
                   "desc": "Ripple in reverse: rings start at the edges and close in on the centre.",
                   "colors": ["#00e0ff", "#a05cff", "#ff5cc8"]},
    "rain":       {"label": "Rain", "icon": "🌧️", "fn": fx_rain,
                   "desc": "Drops run down the wall.",
                   "colors": ["#dff6ff", "#2a8cff", "#02061a"]},
    "wave":       {"label": "Wave", "icon": "🌈", "fn": fx_wave,
                   "desc": "A rainbow sweeps across the wall.",
                   "colors": ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"]},
    "heartbeat":  {"label": "Heartbeat", "icon": "💓", "fn": fx_heartbeat, "needs": HEART_PANELS,
                   "desc": "The heart beats, lub-dub.",
                   "colors": ["#ff1a3c", "#1a0308"]},
}


def _fits(effect, layout_json):
    """False only when we can see the layout and it lacks panels the effect needs."""
    need = effect.get("needs")
    if not need or not layout_json:
        return True
    try:
        have = {p["panelId"] for p in layout_json["panelLayout"]["layout"]["positionData"]}
    except (KeyError, TypeError):
        return True
    return set(need) <= have


def catalogue(layout_json=None):
    return [{"name": k, "label": v["label"], "icon": v["icon"], "desc": v["desc"], "colors": v["colors"]}
            for k, v in EFFECTS.items() if _fits(v, layout_json)]


def build(name, layout_json):
    if name not in EFFECTS:
        raise ValueError(f"No effect called '{name}'. Try: " + ", ".join(EFFECTS))
    e = EFFECTS[name]
    if not _fits(e, layout_json):
        raise ValueError(f"'{name}' is drawn for one specific wall layout and doesn't fit yours.")
    shapes = light_shapes(layout_json)
    adj = adjacency(shapes)
    per = e["fn"](shapes, adj, e)
    totals = {sum(t for _, t in fr) for fr in per.values()}
    if len(totals) != 1:
        raise ValueError(f"{name}: panels have different loop lengths {sorted(totals)}")
    loop = totals.pop()
    return {"name": name, "per": per, "body": body_from(per), "seconds": loop / 10.0,
            "frames": sum(len(fr) for fr in per.values())}


def to_json(r, dt=3):
    hx = lambda rgb: "#%02x%02x%02x" % rgb
    return {"name": r["name"], "seconds": r["seconds"],
            "frames": [[{str(k): hx(v) for k, v in cmap.items()}, t] for cmap, t in sample(r["per"], dt)]}
