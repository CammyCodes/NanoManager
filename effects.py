#!/usr/bin/env python3
"""Animated effects for the Nanoleaf Shapes: Snake, Starlight, Ripple, Rain, Wave…
and arcade games (Pac-Man, Tetris, Pong, Simon, Light Cycles).

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


def bfs_path(adj, a, b):
    """Shortest route a -> b as a list of panels (both ends included)."""
    prev = {a: None}; q = [a]
    for u in q:
        if u == b:
            break
        for v in sorted(adj[u]):
            if v not in prev:
                prev[v] = u; q.append(v)
    path = [b]
    while prev.get(path[-1]) is not None:
        path.append(prev[path[-1]])
    return path[::-1]


def columns(pos, gap=60):
    """Panels grouped into columns (x within ~half a hexagon), each sorted top to bottom."""
    cols_x, groups = [], []
    for pid in sorted(pos, key=lambda i: pos[i][0]):
        x = pos[pid][0]
        if cols_x and abs(x - cols_x[-1]) < gap:
            groups[-1].append(pid)
        else:
            cols_x.append(x); groups.append([pid])
    for g in groups:
        g.sort(key=lambda i: pos[i][1])
    return groups


def rows(pos, gap=30):
    """Panels grouped into horizontal bands (a new band starts at a vertical gap), top first."""
    bands, last = [], None
    for pid in sorted(pos, key=lambda i: pos[i][1]):
        y = pos[pid][1]
        if last is None or y - last > gap:
            bands.append([])
        bands[-1].append(pid); last = y
    return bands


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
    groups = columns(pos)                                       # each top to bottom
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


# ---------------------------------------------------------------- arcade games
# Each one plays a scripted round of the game frame by frame (grid_to_panels), so it
# loops like the other effects. Random choices use a fixed seed: same wall, same game.
WHITE = (255, 255, 255)


def fx_pacman(shapes, adj, o):
    """Pac-Man clears the wall. Every panel starts with a pellet; Pac-Man eats his way
    round Snake's route with the ghost a few panels behind. The panel furthest from the
    start holds the power pellet: the ghost turns blue and runs, Pac-Man turns round and
    eats it, then finishes the board. The pellets fade back in for the next round."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = list(pos)
    start = min(ids, key=lambda i: (-pos[i][1], pos[i][0]))     # bottom-left, like Snake
    tour = euler_tour(adj, start, pos)
    n = len(tour)
    dist = bfs_dist(adj, start)
    power = max(ids, key=lambda i: (dist.get(i, 0), pos[i][0]))
    pp = tour.index(power)
    pac = (255, 220, 0)
    pellet, power_c, maze = (80, 45, 35), (255, 150, 120), (0, 0, 24)
    ghost_c, scared_c = (255, 20, 20), (40, 60, 255)
    step, gap = 3, 3

    def at(i):
        return tour[i % n]

    eaten, steps = set(), []

    def frame(p, g, gcol, t=step, pac_col=None):
        cmap = {pid: maze if pid in eaten else (power_c if pid == power else pellet) for pid in ids}
        if g is not None:
            cmap[at(g)] = gcol
        cmap[at(p)] = pac_col or pac
        steps.append((cmap, t))

    eaten.add(start)
    frame(0, -gap, ghost_c, t=8)                                 # pellets fade back in
    frame(0, -gap, ghost_c, t=6)                                 # "READY!"
    for p in range(1, pp + 1):                                   # eat up to the power pellet
        eaten.add(at(p)); frame(p, p - gap, ghost_c)
    p, g, k = pp, pp - gap, 0
    while True:                                                  # turn round; the blue ghost runs at half speed
        p -= 1; k += 1
        if k % 2 == 0:
            g -= 1
        if p <= g:
            frame(p, None, None, pac_col=WHITE)                  # gotcha
            break
        frame(p, g, scared_c)
    caught = p
    while p < n - 1:                                             # finish the board; the ghost comes back
        p += 1; eaten.add(at(p))
        frame(p, p - gap if p - gap >= caught else None, ghost_c)
    return grid_to_panels(steps, ids)


TETRIS = [(0, 240, 240), (240, 240, 0), (160, 0, 240), (0, 230, 0), (240, 0, 0), (0, 40, 255), (255, 140, 0)]


def fx_tetris(shapes, adj, o):
    """Tetris. Blocks fall down the wall's columns and stack from the bottom; a full band
    flashes and clears and what's above drops. After a while the stack reaches the top
    band and the grey game-over curtain comes down."""
    rnd = random.Random(o.get("seed", 5))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = list(pos)
    cols, bands = columns(pos), rows(pos)
    top = set(bands[0])
    board = {pid: None for pid in ids}
    steps = []

    def frame(t, extra=None):
        cmap = {pid: board[pid] or OFF for pid in ids}
        cmap.update(extra or {})
        steps.append((cmap, t))

    def target(col):                                             # lowest empty panel (stacks are packed down)
        empty = [pid for pid in col if board[pid] is None]
        return empty[-1] if empty else None

    frame(6)
    pieces = 0
    while True:
        options = [(c, target(c)) for c in cols if target(c) is not None]
        if not options:
            break
        options.sort(key=lambda ct: -pos[ct[1]][1])              # lowest landing spot first
        playing = pieces < 24
        if playing:                                              # decent play: keep it low, out of the top band
            low = [ct for ct in options if ct[1] not in top] or options
            col, land = rnd.choice(low[:3])
        else:
            col, land = options[-1]                              # panic: pile it high
        colour = TETRIS[pieces % len(TETRIS)] if pieces < len(TETRIS) else rnd.choice(TETRIS)
        pieces += 1
        for pid in col[:col.index(land)]:                        # fall
            frame(2, {pid: colour})
        board[land] = colour
        frame(3)
        if land in top:
            break                                                # topped out
        for band in bands[::-1] if playing else []:              # (no clears once it's panicking, so it always tops out)
            if all(board[pid] for pid in band):                  # line clear
                frame(2, {pid: WHITE for pid in band})
                for pid in band:
                    board[pid] = None
                frame(2)
                for c in cols:                                   # gravity, column by column
                    stack = [board[pid] for pid in c if board[pid]]
                    for pid in c:
                        board[pid] = None
                    for pid, colour_ in zip(c[::-1], stack[::-1]):
                        board[pid] = colour_
                frame(3)
                break
    frame(8)
    for band in bands:                                           # game over curtain, top to bottom
        for pid in band:
            board[pid] = (70, 70, 80)
        frame(2)
    frame(12)
    for pid in ids:
        board[pid] = None
    frame(8)
    return grid_to_panels(steps, ids)


def fx_pong(shapes, adj, o):
    """Pong across the wall. A blue paddle on the left, a red one on the right (each can
    sit on one of two spots on its side) and a white ball that speeds up. Each rally ends
    with a miss and the wall glows in the scorer's colour."""
    rnd = random.Random(o.get("seed", 9))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = list(pos)
    x0 = min(x for x, _ in pos.values()); x1 = max(x for x, _ in pos.values())
    reach = (x1 - x0) * 0.15

    def spots(side):                                             # the two side panels furthest apart vertically
        near = [i for i in ids if (pos[i][0] <= x0 + reach if side == 0 else pos[i][0] >= x1 - reach)]
        if len(near) < 2:
            return near
        a = min(near, key=lambda i: (pos[i][1], abs(pos[i][0] - (x0 if side == 0 else x1))))
        b = max(near, key=lambda i: (pos[i][1], -abs(pos[i][0] - (x0 if side == 0 else x1))))
        return [a, b]

    side_spots = [spots(0), spots(1)]
    colours = [(0, 90, 255), (255, 30, 30)]
    cx = (x0 + x1) / 2; cy = sum(y for _, y in pos.values()) / len(pos)
    centre_pid = min(ids, key=lambda i: (pos[i][0] - cx) ** 2 + (pos[i][1] - cy) ** 2)
    paddle = [0, 0]                                              # index into side_spots, or None (not there)
    steps = []

    def frame(ball, t, hit=None, glow=None):
        cmap = {pid: dim(glow, .3) if glow else OFF for pid in ids}
        for s in (0, 1):
            if paddle[s] is not None and side_spots[s]:
                pid = side_spots[s][paddle[s]]
                cmap[pid] = mix(colours[s], WHITE, .5) if hit == s else dim(colours[s], .7)
        if ball is not None and hit is None:                     # on a hit the paddle lights instead
            cmap[ball] = WHITE
        steps.append((cmap, t))

    frame(None, 6)
    for rally, (returns, loser) in enumerate([(5, 0), (6, 1)]):
        ball, side, hits = centre_pid, 1 - loser, 0              # serve away from the player who'll miss
        frame(ball, 6)
        while True:
            miss = hits >= returns and side == loser
            choice = rnd.randrange(len(side_spots[side])) if side_spots[side] else 0
            goal = side_spots[side][choice] if side_spots[side] else ball
            path = bfs_path(adj, ball, goal)[1:]
            t = 3 if hits < 3 else 2
            for k, pid in enumerate(path):
                if k == len(path) // 2:                          # the paddle moves to meet it (or the wrong way)
                    if miss:
                        paddle[side] = (1 - choice) if len(side_spots[side]) > 1 else None
                    else:
                        paddle[side] = choice
                last = k == len(path) - 1
                frame(pid, t, hit=side if last and not miss else None)
            ball = goal
            if miss:
                break
            hits += 1; side = 1 - side
        scorer = colours[1 - loser]
        frame(None, 4, glow=scorer)                              # point!
        frame(None, 6, glow=scorer)
        paddle[loser] = 0
        frame(None, 6)
    return grid_to_panels(steps, ids)


SIMON_COLOURS = [(0, 220, 40), (255, 20, 20), (30, 70, 255), (255, 200, 0)]   # green, red, blue, yellow


def simon_zones(shapes, adj):
    """Split the wall into (up to) four Simon zones, as far apart as the layout allows.
    Returns ({panelId: zone}, {zone: rgb}, zones in clockwise order from top-left).
    Shared by the Simon demo and the playable game (simon.py)."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    d = {pid: bfs_dist(adj, pid) for pid in ids}
    far = 99
    seeds = [max(ids, key=lambda i: (max(d[i].values()), pos[i][0]))]
    while len(seeds) < min(4, len(ids)):                         # spread four seeds as far apart as the wall allows
        seeds.append(max((i for i in ids if i not in seeds),
                         key=lambda i: (min(d[s].get(i, far) for s in seeds), pos[i][0])))
    zone = {pid: min(range(len(seeds)), key=lambda z: (d[seeds[z]].get(pid, far),
                     math.hypot(pos[pid][0] - pos[seeds[z]][0], pos[pid][1] - pos[seeds[z]][1]))) for pid in ids}
    cx = sum(x for x, _ in pos.values()) / len(pos); cy = sum(y for _, y in pos.values()) / len(pos)

    def angle(z):                                                # clockwise from top-left
        m = [pos[p] for p in ids if zone[p] == z] or [pos[seeds[z]]]
        mx = sum(x for x, _ in m) / len(m); my = sum(y for _, y in m) / len(m)
        return (math.degrees(math.atan2(my - cy, mx - cx)) + 135) % 360
    order = sorted(range(len(seeds)), key=angle)
    colour = {z: SIMON_COLOURS[k] for k, z in enumerate(order)}
    return zone, colour, order


def fx_simon(shapes, adj, o):
    """Simon. The wall splits into four dim zones; Simon plays a sequence that grows by
    one every round and the player repeats it, a little quicker. After five rounds the
    zones spin round in a victory lap."""
    rnd = random.Random(o.get("seed", 4))
    zone, colour, order = simon_zones(shapes, adj)
    ids = sorted(zone)
    rounds = 5
    seq = [rnd.randrange(len(order)) for _ in range(rounds)]
    events = {z: [] for z in colour}
    t = 8

    def press(z, hold, gap):
        nonlocal t
        c = colour[z]
        events[z].append((t, [(c, 1), (c, hold), (dim(c, .12), 2)]))
        t += 1 + hold + 2 + gap

    for r in range(1, rounds + 1):
        for z in seq[:r]:
            press(z, 3, 2)                                       # Simon
        t += 6
        for z in seq[:r]:
            press(z, 1, 1)                                       # the player, quicker
        t += 10
    for lap in range(2):                                         # victory spin
        for z in order:
            press(z, 1, -2)
    loop = t + 12
    return {pid: events_to_frames(events[zone[pid]], loop, base=dim(colour[zone[pid]], .12)) for pid in ids}


def fx_cycles(shapes, adj, o):
    """Tron light cycles. A cyan bike and an orange bike race over the wall leaving light
    trails; each steers for open space. The first one boxed in de-rezzes and the winner's
    trail glows. Three rounds from different starts."""
    rnd = random.Random(o.get("seed", 2))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    d = {pid: bfs_dist(adj, pid) for pid in ids}
    span = max(max(v.values()) for v in d.values())
    pairs = [(a, b) for a in ids for b in ids if a < b and d[a].get(b, 0) >= max(2, span - 2)]
    rnd.shuffle(pairs)
    starts, used = [], set()
    for a, b in sorted(pairs, key=lambda ab: -d[ab[0]][ab[1]]):  # three far-apart pairs, fresh panels where possible
        if a not in used or b not in used or len(starts) >= len(pairs) - 1:
            starts.append((a, b) if rnd.random() < .5 else (b, a)); used |= {a, b}
        if len(starts) == 3:
            break
    if not starts:
        starts = [(ids[0], ids[-1])]
    colours = [(0, 230, 255), (255, 110, 0)]
    steps = []

    def space(frm, blocked):                                     # free panels reachable from frm
        seen, q = {frm}, [frm]
        for u in q:
            for v in adj[u]:
                if v not in seen and v not in blocked:
                    seen.add(v); q.append(v)
        return len(seen)

    def frame(trails, t, look=None):
        cmap = {pid: OFF for pid in ids}
        for b in (0, 1):
            for k, pid in enumerate(trails[b]):
                head = k == len(trails[b]) - 1
                cmap[pid] = mix(colours[b], WHITE, .35) if head else dim(colours[b], .45)
        cmap.update(look or {})
        steps.append((cmap, t))

    for a, b in starts:
        trails = [[a], [b]]
        frame(trails, 6)
        while True:
            taken = set(trails[0]) | set(trails[1])
            moves = []
            for k in (0, 1):
                opts = [v for v in sorted(adj[trails[k][-1]]) if v not in taken]
                rnd.shuffle(opts)
                moves.append(max(opts, key=lambda v: space(v, taken | {v})) if opts else None)
            crashed = [m is None for m in moves]
            if moves[0] is not None and moves[0] == moves[1]:
                crashed = [True, True]                           # head-on
            for k in (0, 1):
                if not crashed[k]:
                    trails[k].append(moves[k])
            frame(trails, 3)
            if any(crashed):
                break
        for k in (0, 1):
            if crashed[k]:                                       # de-rez: flare, then unravel from the head
                frame(trails, 1, {pid: mix(colours[k], WHITE, .6) for pid in trails[k]})
                while trails[k]:
                    trails[k].pop(); frame(trails, 1)
        for k in (0, 1):
            if not crashed[k]:
                frame(trails, 3, {pid: colours[k] for pid in trails[k]})
                frame(trails, 6, {pid: colours[k] for pid in trails[k]})
        frame([[], []], 6)
        frame([[], []], 3)
    return grid_to_panels(steps, ids)


# ---------------------------------------------------------------- ambient
# Calm, slow looks for living with (the "ambient" group). Keyframes are kept sparse so
# every one stays well under the payload sizes the controller is known to accept.
NOW = None                      # tests set this (a time.time() value) to freeze "today"


def _now():
    import time
    return NOW if NOW is not None else time.time()


def _today():
    import datetime
    return datetime.date.fromtimestamp(_now())


def heights(pos):
    """0 at the lowest panel, 1 at the highest (screen y points down)."""
    y0 = min(y for _, y in pos.values()); y1 = max(y for _, y in pos.values())
    return {pid: (y1 - y) / max(1, y1 - y0) for pid, (_, y) in pos.items()}


def widths(pos):
    """0 at the leftmost panel, 1 at the rightmost."""
    x0 = min(x for x, _ in pos.values()); x1 = max(x for x, _ in pos.values())
    return {pid: (x - x0) / max(1, x1 - x0) for pid, (x, _) in pos.items()}


def fx_fireplace(shapes, adj, o):
    """A log fire: every panel flickers on its own; the lowest panels burn yellow-orange,
    the highest are dim red embers."""
    rnd = random.Random(o.get("seed", 17))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    hi = heights(pos)
    loop = 60
    hot, warm, ember = (255, 150, 20), (230, 70, 5), (110, 15, 0)
    per = {}
    for pid in pos:
        h = hi[pid]
        top = mix(hot, warm, min(1, h * 1.3)) if h < .75 else mix(warm, ember, (h - .75) * 4)
        low = dim(mix(warm, ember, h), .45)
        fr, t = [], 0
        while t < loop:
            d = min(loop - t, rnd.randint(2, 5))
            fr.append((mix(low, top, rnd.uniform(.35, 1.0) ** 1.5), d)); t += d
        per[pid] = fr
    return per


def fx_storm(shapes, adj, o):
    """A night storm: dim clouds roll over a dark sky and lightning forks through a few
    neighbouring panels at a time (never the whole wall)."""
    rnd = random.Random(o.get("seed", 23))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    wx = widths(pos)
    sky, cloud, bolt = (6, 8, 24), (34, 40, 78), (200, 215, 255)
    loop = 160
    events = {pid: [] for pid in ids}
    t = rnd.randint(10, 25)
    while t < loop - 20:
        root = rnd.choice(ids)
        fork = [root] + rnd.sample(sorted(adj[root]), min(len(adj[root]), rnd.randint(1, 2)))
        for k, pid in enumerate(fork):
            events[pid].append((t + k, [(bolt, 1), (dim(bolt, .2), 1), (bolt, 1), (sky, 4)]))
        t += rnd.randint(25, 45)
    per = {}
    for pid in ids:
        ph = int(wx[pid] * 40)                                      # clouds drift left to right
        base = [((ph + k) % loop, [(cloud, 20), (sky, 20)]) for k in range(0, loop, 80)]
        ev = sorted(e for e in events[pid])
        ev_t = [(s, s + sum(d for _, d in segs)) for s, segs in ev]
        keep = [b for b in base if all(b[0] + 40 <= s or b[0] >= e for s, e in ev_t) and b[0] + 40 <= loop]
        per[pid] = events_to_frames(sorted(keep + ev), loop, base=sky)
    return per


def fx_ocean(shapes, adj, o):
    """Waves roll in across the wall: deep blue troughs, teal swells and a pale foam crest."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    wx, hi = widths(pos), heights(pos)
    deep, swell, foam = (0, 25, 90), (0, 140, 170), (170, 230, 240)
    period, dt = 80, 5
    per = {}
    for pid in pos:
        off = wx[pid] * .7 + hi[pid] * .3
        fr = []
        for k in range(period // dt):
            ph = (k * dt / period - off) % 1.0
            if ph < .55:
                c = mix(deep, swell, ph / .55)
            elif ph < .7:
                c = mix(swell, foam, (ph - .55) / .15)
            else:
                c = mix(foam, deep, (ph - .7) / .3)
            fr.append((c, dt))
        per[pid] = fr
    return per


def fx_aurora(shapes, adj, o):
    """Northern lights: green and teal curtains with violet edges drift slowly across a dark sky."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    wx, hi = widths(pos), heights(pos)
    green, teal, violet, night = (20, 255, 110), (0, 200, 170), (140, 50, 230), (0, 4, 14)
    period, dt = 140, 7
    per = {}
    for pid in pos:
        x, h = wx[pid], hi[pid]
        fr = []
        for k in range(period // dt):
            a = 2 * math.pi * k * dt / period
            glow = (.5 + .5 * math.sin(a + x * 5.0)) * (.55 + .45 * math.sin(2 * a - x * 3.0 + 1.3))
            glow = max(0.0, min(1.0, glow))
            hue = mix(green, teal, .5 + .5 * math.sin(a + x * 2.0))
            if h > .6:                                              # violet fringe on top
                hue = mix(hue, violet, (h - .6) * 2.0)
            fr.append((mix(night, hue, glow ** 1.4), dt))
        per[pid] = fr
    return per


def fx_lava(shapes, adj, o):
    """A lava lamp: slow warm blobs rise up through dark red wax and sink back."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    wx, hi = widths(pos), heights(pos)
    wax, blob, core = (60, 0, 20), (255, 60, 0), (255, 170, 30)
    period, dt = 150, 6
    blobs = [(.15, 0.0), (.5, .35), (.85, .7)]                       # (x, phase)
    per = {}
    for pid in pos:
        fr = []
        for k in range(period // dt):
            t = k * dt / period
            heat = 0.0
            for bx, ph in blobs:
                by = .5 - .5 * math.cos(2 * math.pi * (t + ph))     # bottom -> top -> bottom
                d = math.hypot((wx[pid] - bx) * 1.6, hi[pid] - by)
                heat = max(heat, max(0.0, 1 - d / .38))
            c = mix(wax, blob, min(1, heat * 1.4)) if heat < .7 else mix(blob, core, (heat - .7) / .3)
            fr.append((c, dt))
        per[pid] = fr
    return per


def fx_nightsky(shapes, adj, o):
    """A starfield: a deep blue night where faint stars twinkle slowly, and now and then a
    shooting star streaks across the top of the wall."""
    rnd = random.Random(o.get("seed", 29))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    night, star, shoot = (2, 4, 22), (150, 170, 220), (230, 235, 255)
    loop = 240
    events = {pid: [] for pid in ids}
    top = rows(pos)[0]
    path = sorted(top, key=lambda i: pos[i][0])
    st = 150
    for k, pid in enumerate(path):                                  # the shooting star, left to right
        events[pid].append((st + k, [(shoot, 1), (dim(shoot, .3), 2), (night, 4)]))
    for pid in ids:
        t = rnd.randint(0, 60)
        while t < loop - 40:
            busy = any(s - 30 <= t <= s + 10 for s, _ in events[pid])
            if not busy:
                peak = dim(star, rnd.uniform(.35, .8))
                events[pid].append((t, [(peak, rnd.randint(8, 14)), (peak, rnd.randint(4, 10)), (night, rnd.randint(10, 18))]))
            t += rnd.randint(40, 90)
    return {pid: events_to_frames(sorted(ev), loop, base=night) for pid, ev in events.items()}


def fx_breathe(shapes, adj, o):
    """A 4-7-8 breathing guide: breathe in for 4 s while the wall fills from the bottom,
    hold for 7 s, breathe out for 8 s while it drains from the top."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    hi = heights(pos)
    peak, low = hex_rgb(o["colors"][0]), hex_rgb(o["colors"][1])
    per = {}
    for pid in pos:
        h = hi[pid]
        a = int(round(h * 25))                                      # inhale: 0..40, bottom first
        b = int(round((1 - h) * 40))                                # exhale: 110..190, top first
        per[pid] = [(low, a or 1), (peak, 15), (peak, 110 - 15 - (a or 1)), (peak, b or 1),
                    (low, 30), (low, 80 - 30 - (b or 1))]
    return per


SYNODIC = 29.530588853
NEW_MOON = 947182440.0          # 2000-01-06 18:14 UTC


def moon_phase(ts=None):
    """(age in days, fraction lit 0..1, name) for a moment (default: now)."""
    age = ((_now() if ts is None else ts) - NEW_MOON) / 86400.0 % SYNODIC
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2
    names = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
             "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"]
    return age, lit, names[int((age / SYNODIC) * 8 + .5) % 8]


def fx_moon(shapes, adj, o):
    """A night light shaped like tonight's moon: the lit side of the wall follows the real
    phase (waxing lights the right, waning the left, as seen from the northern hemisphere)."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    wx = widths(pos)
    age, lit, _ = moon_phase()
    glow, dark = hex_rgb(o["colors"][0]), hex_rgb(o["colors"][1])
    waxing = age < SYNODIC / 2
    per = {}
    for pid in pos:
        x = wx[pid] if waxing else 1 - wx[pid]
        edge = (1 - lit) - x                                        # > 0: in shadow
        f = 1.0 if edge < -.08 else 0.0 if edge > .08 else (.08 - edge) / .16
        per[pid] = [(mix(dark, glow, f), 30), (mix(dark, dim(glow, .85), f), 30)]
    return per


def moon_desc(o):
    _, lit, name = moon_phase()
    return f"Tonight's moon as a night light: {name.lower()}, {int(round(lit * 100))}% lit."


DAY_COLOURS = [("Monday", (255, 40, 40)), ("Tuesday", (255, 130, 0)), ("Wednesday", (255, 210, 0)),
               ("Thursday", (40, 210, 70)), ("Friday", (0, 150, 255)), ("Saturday", (90, 60, 255)),
               ("Sunday", (200, 70, 255))]


def fx_daycolour(shapes, adj, o):
    """One rainbow colour for each day of the week (Monday red ... Sunday violet), breathing slowly."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    wx = widths(pos)
    _, c = DAY_COLOURS[_today().weekday()]
    per = {}
    for pid in pos:
        a = 1 + int(wx[pid] * 28)                                   # 1..29: a slow ripple left to right
        per[pid] = [(dim(c, .55), a), (c, 30), (dim(c, .55), 30), (dim(c, .55), 30 - a)]
    return per


def daycolour_desc(o):
    name, _ = DAY_COLOURS[_today().weekday()]
    return f"One colour for every day of the week. Today is {name}."


def easter(year):
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19; b, c = divmod(year, 100); d, e = divmod(b, 4)
    g = (8 * b + 13) // 25; h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4); l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31; day = (h + l - 7 * m + 114) % 31 + 1
    return month, day


def holidays(year):
    em, ed = easter(year)
    return [(1, 1, "New Year", [(255, 200, 40), (120, 130, 160)]),
            (2, 14, "Valentine's Day", [(255, 20, 60), (255, 120, 170)]),
            (em, ed, "Easter", [(255, 220, 90), (160, 230, 140), (200, 160, 255)]),
            (10, 31, "Halloween", [(255, 110, 0), (130, 0, 200)]),
            (11, 5, "Bonfire Night", [(255, 90, 0), (255, 180, 30)]),
            (12, 25, "Christmas", [(230, 0, 20), (0, 170, 40)])]


def next_holiday(today=None):
    """(previous date, next date, name, colours) around today. On the day itself prev == next."""
    import datetime
    today = today or _today()
    days = []
    for y in (today.year - 1, today.year, today.year + 1):
        for m, d, name, cols in holidays(y):
            days.append((datetime.date(y, m, d), name, cols))
    days.sort(key=lambda x: x[0])
    for k, (day, name, cols) in enumerate(days):
        if day >= today:
            prev = day if day == today else days[k - 1][0]
            return prev, day, name, cols
    raise ValueError("no holiday found")


def fx_countdown(shapes, adj, o):
    """A countdown bar to the next holiday: the wall fills from the bottom as the day gets
    closer (counting from the last one) and twinkles in the holiday's colours once it's here."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    hi = heights(pos)
    today = _today()
    prev, nxt, name, cols = next_holiday(today)
    span = max(1, (nxt - prev).days)
    frac = 1.0 if nxt == today else (today - prev).days / span
    order = sorted(pos, key=lambda i: (-pos[i][1], pos[i][0]))       # bottom first
    n = len(order) if nxt == today else min(len(order) - 1, int(frac * len(order)))
    per = {}
    for k, pid in enumerate(order):
        if k < n:
            a, b = cols[k % len(cols)], cols[(k + 1) % len(cols)]
            per[pid] = [(a, 25), (mix(a, b, .5), 25)]
        elif k == n:                                                # the next panel to fill glows softly
            c = cols[k % len(cols)]
            per[pid] = [(dim(c, .35), 25), (dim(c, .08), 25)]
        else:
            per[pid] = [((6, 6, 10), 50)]
    return per


def countdown_desc(o):
    today = _today()
    _, nxt, name, _ = next_holiday(today)
    left = (nxt - today).days
    when = "today!" if left == 0 else "tomorrow" if left == 1 else f"in {left} days"
    return f"Fills up as the next holiday gets closer: {name} is {when}"


# ---------------------------------------------------------------- watch-only games
# More screensavers in the Arcade: they play themselves, nobody has to touch anything.
def _farthest(ids, pos, n):
    """n panels spread as far apart as possible (greedy), for dice pips etc."""
    if not ids:
        return []
    pick = [min(ids, key=lambda i: (pos[i][0], pos[i][1]))]
    while len(pick) < min(n, len(ids)):
        pick.append(max((i for i in ids if i not in pick),
                        key=lambda i: (min(math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]) for j in pick), -i)))
    return pick


def fx_life(shapes, adj, o):
    """Conway's Game of Life on the wall's own panel graph. Panels have only 1-3 neighbours,
    so the rules are tuned for that (B12/S2): a panel comes alive next to one or two live
    neighbours and survives with exactly two. Newborns are cyan and age to green and blue.
    When the colony dies out, freezes or repeats, a new one is seeded."""
    rnd = random.Random(o.get("seed", 31))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    ages = [(0, 255, 230), (60, 255, 120), (0, 150, 255), (40, 70, 220)]
    steps, gens, runs = [], 0, 0
    while gens < 34 and runs < 4:
        alive = {pid: 0 for pid in rnd.sample(ids, max(3, len(ids) * 2 // 5))}
        seen, runs = set(), runs + 1
        while True:
            steps.append(({pid: ages[min(a, 3)] for pid, a in alive.items()}, 5)); gens += 1
            key = frozenset(alive)
            if not alive or key in seen or gens >= 34:
                break
            seen.add(key)
            nxt = {}
            for pid in ids:
                n = sum(1 for v in adj[pid] if v in alive)
                if pid in alive and n == 2:
                    nxt[pid] = alive[pid] + 1
                elif pid not in alive and n in (1, 2):
                    nxt[pid] = 0
            alive = nxt
        steps.append(({pid: dim(ages[min(a, 3)], .3) for pid, a in alive.items()}, 6))
        steps.append(({}, 6))
    return grid_to_panels(steps, ids)


def fx_breakout(shapes, adj, o):
    """Breakout: a row of rainbow bricks across the top, a paddle along the bottom and a ball
    that knocks the bricks out one by one. When the wall is cleared the bricks come back."""
    rnd = random.Random(o.get("seed", 37))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    bands = rows(pos)
    if len(bands) < 3:
        bands = [ids[: len(ids) // 3], ids[len(ids) // 3:]]
    bricks0 = bands[0]
    spots = sorted(bands[-1], key=lambda i: pos[i][0])
    rainbow = [hsv(h, 100, 100) for h in range(0, 360, max(1, 360 // max(1, len(bricks0))))]
    colour = {pid: rainbow[k % len(rainbow)] for k, pid in enumerate(sorted(bricks0, key=lambda i: pos[i][0]))}
    paddle_c, ball_c = (0, 200, 255), (255, 255, 200)
    bricks, steps = set(bricks0), []
    paddle = spots[len(spots) // 2]

    def frame(ball, t, extra=None):
        cmap = {pid: colour[pid] for pid in bricks}
        cmap[paddle] = paddle_c
        if ball is not None:
            cmap[ball] = ball_c
        cmap.update(extra or {})
        steps.append((cmap, t))

    frame(None, 8)
    ball = paddle
    while bricks:
        goal = rnd.choice(sorted(bricks))
        path = bfs_path(adj, ball, goal)[1:]
        hit = next((p for p in path if p in bricks), goal)             # the first brick in the way
        path = path[:path.index(hit) + 1]
        for p in path[:-1]:
            frame(p, 2)
        frame(None, 1, {hit: (255, 255, 255)})                       # only the brick flashes
        bricks.discard(hit)
        frame(path[-2] if len(path) > 1 else None, 2)
        back = rnd.choice(spots)
        route = bfs_path(adj, path[-2] if len(path) > 1 else hit, back)[1:]
        for k, p in enumerate(route):
            if k == len(route) // 2:
                paddle = back                                         # slides over to meet it
            frame(p if p != back else None, 2)
        paddle, ball = back, back
        frame(None, 2, {back: (200, 250, 255)})
    frame(None, 10)
    for pid in sorted(bricks0, key=lambda i: pos[i][0]):              # bricks come back
        bricks.add(pid); frame(None, 1)
    frame(None, 6)
    return grid_to_panels(steps, ids)


def fx_dice(shapes, adj, o):
    """A dice roller: the wall tumbles, then settles with the pips lit on the little
    triangles (any panels on walls without them) over a dark red die. Rolls every few seconds."""
    rnd = random.Random(o.get("seed", 41))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    tri = [p["panelId"] for p, _ in shapes if p["shapeType"] in (8, 9)]
    pip_pool = tri if len(tri) >= 6 else ids
    face, pip = (90, 0, 10), (255, 245, 230)
    rolls = rnd.sample(range(1, 7), 6)
    steps = []
    for n in rolls:
        for d in (1, 1, 1, 2, 2, 3):                                 # tumble, slowing down
            lit = set(rnd.sample(pip_pool, rnd.randint(1, 6)))
            steps.append(({pid: pip if pid in lit else dim(face, .6) for pid in ids}, d))
        sub = [i for i in pip_pool]
        lit = set(_farthest(sub, pos, n))
        steps.append(({pid: pip if pid in lit else face for pid in ids}, 3))
        steps.append(({pid: pip if pid in lit else face for pid in ids}, 25))
    return grid_to_panels(steps, ids)


def fx_coin(shapes, adj, o):
    """A coin toss: gold and silver sweep across the wall as the coin spins, slower and
    slower, until it lands heads (gold) or tails (silver) and rests there."""
    rnd = random.Random(o.get("seed", 43))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    wx = widths(pos)
    gold, silver = (255, 180, 0), (110, 125, 150)
    steps, side = [], 0
    for toss in range(3):
        land = rnd.randrange(2)
        spins = 6 if (side + 6) % 2 == land else 7
        for k in range(spins):
            nxt = 1 - side
            if k < spins - 2:                                        # fast: the whole coin flips
                steps.append(({pid: (gold, silver)[nxt] for pid in ids}, 1 if k < 3 else 2))
            else:                                                    # slowing down: the flip sweeps across
                for edge in (.5, 1.01):
                    steps.append(({pid: (gold, silver)[nxt if wx[pid] < edge else side] for pid in ids}, 2))
            side = nxt
        steps.append(({pid: (gold, silver)[side] for pid in ids}, 25))
        steps.append(({pid: dim((gold, silver)[side], .25) for pid in ids}, 6))
    return grid_to_panels(steps, ids)


TTT_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def _ttt_winner(b):
    for a, c, d in TTT_LINES:
        if b[a] and b[a] == b[c] == b[d]:
            return b[a], (a, c, d)
    return None, None


def _ttt_best(b, me):
    """Perfect play: (score, move) for player me ('X' or 'O') by minimax."""
    w, _ = _ttt_winner(b)
    if w:
        return (1 if w == me else -1), None
    free = [i for i in range(9) if not b[i]]
    if not free:
        return 0, None
    best = (-2, None)
    for i in free:
        b[i] = me
        s = -_ttt_best(b, "O" if me == "X" else "X")[0]
        b[i] = None
        if s > best[0]:
            best = (s, i)
    return best


def fx_tictactoe(shapes, adj, o):
    """Noughts and crosses between two computer players on nine panels (the hexagons
    where there are nine). Red plays perfectly; blue now and then slips up. Winning lines flash."""
    rnd = random.Random(o.get("seed", 47))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    hexes = [p["panelId"] for p, _ in shapes if p["shapeType"] in (7, 15)]
    cx = sum(x for x, _ in pos.values()) / len(pos); cy = sum(y for _, y in pos.values()) / len(pos)
    pool = hexes if len(hexes) >= 9 else ids
    cells = sorted(sorted(pool, key=lambda i: (pos[i][0] - cx) ** 2 + (pos[i][1] - cy) ** 2)[:9],
                   key=lambda i: (round(pos[i][1] / 60), pos[i][0]))
    others = [i for i in ids if i not in cells]
    col = {"X": (255, 30, 30), "O": (30, 90, 255)}
    empty = (14, 14, 20)
    steps = []

    def frame(b, turn, t, extra=None):
        cmap = {cells[k]: col[b[k]] if b[k] else empty for k in range(9)}
        for pid in others:
            cmap[pid] = dim(col[turn], .12) if turn else OFF
        cmap.update(extra or {})
        steps.append((cmap, t))

    for game in range(3):
        b, turn = [None] * 9, "X" if game % 2 == 0 else "O"
        frame(b, turn, 6)
        while True:
            free = [i for i in range(9) if not b[i]]
            if turn == "O" and rnd.random() < .35:
                mv = rnd.choice(free)
            elif len(free) == 9:
                mv = rnd.choice([0, 2, 4, 6, 8])
            else:
                mv = _ttt_best(b, turn)[1]
            b[mv] = turn
            w, line = _ttt_winner(b)
            if w or all(b):
                frame(b, None, 4)
                if w:
                    hi = {cells[k]: mix(col[w], (255, 255, 255), .5) for k in line}
                    for _ in range(3):
                        frame(b, None, 2, hi); frame(b, None, 2)
                    frame(b, None, 12, {cells[k]: col[w] for k in line})
                else:
                    frame(b, None, 12)
                break
            turn = "O" if turn == "X" else "X"
            frame(b, turn, 7)
        frame([None] * 9, None, 6)
    return grid_to_panels(steps, ids)


def lights_out_solve(ids, adj, lit):
    """Which panels to press (each toggles itself and its neighbours) to switch every lit
    panel off: Gaussian elimination over GF(2). None if the pattern can't be solved."""
    n = len(ids); idx = {pid: k for k, pid in enumerate(ids)}
    rows_ = []
    for i, pid in enumerate(ids):
        m = 1 << i
        for v in adj[pid]:
            m |= 1 << idx[v]
        rows_.append([m, 1 if pid in lit else 0])                   # row i: which presses toggle panel i
    piv, r = [], 0
    for c in range(n):
        k = next((k for k in range(r, n) if rows_[k][0] >> c & 1), None)
        if k is None:
            continue
        rows_[r], rows_[k] = rows_[k], rows_[r]
        for k in range(n):
            if k != r and rows_[k][0] >> c & 1:
                rows_[k][0] ^= rows_[r][0]; rows_[k][1] ^= rows_[r][1]
        piv.append(c); r += 1
    if any(m == 0 and v for m, v in rows_[r:]):
        return None
    return [ids[c] for k, c in enumerate(piv) if rows_[k][1]]


def fx_lightsout(shapes, adj, o):
    """Lights Out, solved by the wall itself: pressing a panel flips it and its neighbours.
    The wall works out the presses (linear algebra) and plays them one by one until every
    panel is off; then a new puzzle appears."""
    rnd = random.Random(o.get("seed", 53))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    on_c, off_c, press_c = (255, 190, 50), (6, 8, 26), (0, 230, 255)
    steps = []

    def frame(lit, t, extra=None):
        cmap = {pid: on_c if pid in lit else off_c for pid in ids}
        cmap.update(extra or {})
        steps.append((cmap, t))

    for puzzle in range(3):
        lit = set()
        for pid in rnd.sample(ids, rnd.randint(4, 6)):              # a solvable puzzle: random presses
            lit ^= {pid} | set(adj[pid])
        if not lit:
            continue
        frame(lit, 6); frame(lit, 12)
        plan = lights_out_solve(ids, adj, lit) or []
        plan.sort(key=lambda i: (pos[i][1], pos[i][0]))
        for pid in plan:
            frame(lit, 3, {pid: press_c})
            lit ^= {pid} | set(adj[pid])
            frame(lit, 4)
        frame(lit, 3, {pid: (0, 60, 20) for pid in ids})            # solved: a soft green glow
        frame(lit, 8)
    return grid_to_panels(steps, ids)


def flappy_fits(shapes):
    """Pipes need columns of two or more panels: the bird's and at least two more."""
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    return sum(1 for c in columns(pos) if len(c) >= 2) >= 3


def fx_flappy(shapes, adj, o):
    """A Flappy-style autopilot: green pipes slide in from the right with a gap, and a yellow
    bird near the left hops up and down to fly through. After six pipes it misjudges one,
    turns red and drops, and the flight starts again."""
    rnd = random.Random(o.get("seed", 59))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    cols = columns(pos)
    if len(cols) < 4:
        cols = [[pid] for pid in sorted(ids, key=lambda i: pos[i][0])]
    tall = [k for k, c in enumerate(cols) if len(c) >= 2]
    bird_col = tall[0] if tall else 0
    ys = sorted({round(pos[pid][1]) for pid in cols[bird_col]})
    pipe_c, bird_c, dead_c = (20, 200, 40), (255, 220, 0), (255, 30, 30)
    sky = (0, 10, 30)

    def nearest(col, y):
        return min(cols[col], key=lambda i: abs(pos[i][1] - y))

    steps = []
    for flight in range(1):
        pipes = []                                                   # [column index, gap y]
        bird_y, passed, crash_at = ys[len(ys) // 2], 0, 6
        spawn = 0
        steps.append(({nearest(bird_col, bird_y): bird_c}, 6))
        for _ in range(400):                                         # (it always crashes long before this)
            if spawn <= 0:
                pipes.append([len(cols) - 1, rnd.choice(ys)]); spawn = 3
            spawn -= 1
            ahead = [p for p in pipes if p[0] >= bird_col]
            target = ahead[0][1] if ahead else bird_y
            if passed >= crash_at and ahead and ahead[0][0] <= bird_col + 1:
                target = bird_y                                       # this time it doesn't flap
            if target != bird_y:                                      # one hop per step
                i = ys.index(bird_y); j = ys.index(target)
                bird_y = ys[i + (1 if j > i else -1)]
            cmap = {pid: sky for pid in ids}
            dead = False
            for c, gy in pipes:
                if len(cols[c]) >= 2:
                    gap = nearest(c, gy)
                    for pid in cols[c]:
                        if pid != gap:
                            cmap[pid] = pipe_c
                    if c == bird_col and nearest(bird_col, bird_y) != gap:
                        dead = True
            bird = nearest(bird_col, bird_y)
            cmap[bird] = dead_c if dead else bird_c
            steps.append((cmap, 3))
            if dead:
                for y in ys[ys.index(bird_y):]:                       # falls
                    cm = dict(cmap); cm[bird] = sky if cm[bird] == dead_c else cm[bird]
                    cm[nearest(bird_col, y)] = dead_c
                    steps.append((cm, 2))
                steps.append(({pid: sky for pid in ids}, 8))
                break
            for p in pipes:
                if p[0] == bird_col:
                    passed += 1
                p[0] -= 1
            pipes = [p for p in pipes if p[0] >= 0]
    return grid_to_panels(steps, ids)


def fx_maze(shapes, adj, o):
    """A maze draws itself: a purple digger carves through every panel (a random depth-first
    search, backing up at dead ends), then the route from start to finish lights up gold."""
    rnd = random.Random(o.get("seed", 61))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    carved_c, head_c, route_c, start_c = (60, 20, 120), (180, 120, 255), (255, 190, 0), (0, 220, 120)
    steps = []
    for run in range(2):
        start = rnd.choice(ids)
        carved, stack, parent = {start}, [start], {start: None}

        def frame(t, head=None, route=()):
            cmap = {pid: carved_c for pid in carved}
            for pid in route:
                cmap[pid] = route_c
            cmap[start] = start_c
            if head is not None:
                cmap[head] = head_c
            steps.append((cmap, t))

        frame(4, start)
        while stack:
            u = stack[-1]
            opts = [v for v in sorted(adj[u]) if v not in carved]
            if opts:
                v = rnd.choice(opts)
                carved.add(v); parent[v] = u; stack.append(v)
                frame(2, v)
            else:
                stack.pop()
                if stack:
                    frame(1, stack[-1])
        d = bfs_dist(adj, start)
        end = max(ids, key=lambda i: (d.get(i, 0), i))
        route, p = [], end
        while p is not None:
            route.append(p); p = parent[p]
        route.reverse()
        for k in range(1, len(route) + 1):
            frame(2, None, route[:k])
        frame(15, None, route)
        steps.append(({}, 8))
    return grid_to_panels(steps, ids)


def fx_invaders(shapes, adj, o):
    """Space Invaders attract mode: a wave of green invaders across the top pulses as it
    marches, drops the odd bomb, and the cannon at the bottom picks them off one by one."""
    rnd = random.Random(o.get("seed", 67))
    pos = {p["panelId"]: centre(pts) for p, pts in shapes}
    ids = sorted(pos)
    bands = rows(pos)
    if len(bands) < 3:
        bands = [ids[: len(ids) // 3], ids[len(ids) // 3:]]
    wave0 = sorted(bands[0], key=lambda i: pos[i][0])
    spots = sorted(bands[-1], key=lambda i: pos[i][0])
    inv_a, inv_b, cannon_c, shot_c, bomb_c, boom_c = (40, 255, 60), (10, 140, 30), (0, 200, 255), (255, 255, 160), (255, 40, 40), (255, 140, 0)
    alive, steps, beat = set(wave0), [], [0]
    cannon = spots[len(spots) // 2]

    def frame(t, extra=None):
        beat[0] += 1
        cmap = {pid: (inv_a if beat[0] % 4 < 2 else inv_b) for pid in alive}
        cmap[cannon] = cannon_c
        cmap.update(extra or {})
        steps.append((cmap, t))

    frame(8)
    while alive:
        cannon = rnd.choice(spots)
        frame(2)
        if rnd.random() < .4:                                         # a bomb falls and misses
            src = rnd.choice(sorted(alive))
            miss = [s for s in spots if s != cannon] or spots
            for p in bfs_path(adj, src, rnd.choice(miss))[1:]:
                frame(1, {p: bomb_c})
        target = rnd.choice(sorted(alive))
        path = bfs_path(adj, cannon, target)[1:]
        hit = next((p for p in path if p in alive), target)
        for p in path[:path.index(hit)]:
            frame(1, {p: shot_c})
        alive.discard(hit)
        frame(2, {hit: boom_c}); frame(2, {hit: dim(boom_c, .3)})
    frame(10)
    for pid in wave0:                                                 # the next wave
        alive.add(pid)
    frame(6)
    return grid_to_panels(steps, ids)


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
    # arcade games ("group": "game" puts them in their own section on the Scenes tab)
    "pacman":     {"label": "Pac-Man", "icon": "🟡", "fn": fx_pacman, "group": "game",
                   "desc": "Pac-Man eats the pellets round the wall with a ghost on his tail, grabs the power pellet and turns the tables.",
                   "colors": ["#ffdc00", "#ff1414", "#3c3cff", "#ff9678"]},
    "tetris":     {"label": "Tetris", "icon": "🧱", "fn": fx_tetris, "group": "game",
                   "desc": "Blocks fall and stack up, full lines clear, and in the end it tops out and the curtain comes down.",
                   "colors": ["#00f0f0", "#f0f000", "#a000f0", "#00e600", "#f00000", "#0028ff", "#ff8c00"]},
    "pong":       {"label": "Pong", "icon": "🏓", "fn": fx_pong, "group": "game",
                   "desc": "A ball rallies between a blue and a red paddle, getting faster, until someone misses.",
                   "colors": ["#005aff", "#ffffff", "#ff1e1e"]},
    "simon":      {"label": "Simon", "icon": "🔴", "fn": fx_simon, "group": "game",
                   "desc": "Four colour zones play a sequence that grows every round, then the player copies it.",
                   "colors": ["#00dc28", "#ff1414", "#1e46ff", "#ffc800"]},
    "cycles":     {"label": "Light Cycles", "icon": "🏍️", "fn": fx_cycles, "group": "game",
                   "desc": "Two Tron light cycles race over the wall leaving trails; the first one boxed in de-rezzes.",
                   "colors": ["#00e6ff", "#ff6e00"]},
    # watch-only screensavers (added 1.3): nobody plays, they just run
    "life":       {"label": "Game of Life", "icon": "🧬", "fn": fx_life, "group": "game",
                   "desc": "Cells are born, age and die across the panels; a new colony starts when one dies out or settles.",
                   "colors": ["#00ffe6", "#3cff78", "#0096ff", "#2846dc"]},
    "breakout":   {"label": "Breakout", "icon": "🟥", "fn": fx_breakout, "group": "game",
                   "desc": "A ball knocks out a row of rainbow bricks along the top while the paddle slides to meet it.",
                   "colors": ["#ff0000", "#ffcc00", "#00ff66", "#00c8ff", "#ffffc8"]},
    "invaders":   {"label": "Space Invaders", "icon": "👾", "fn": fx_invaders, "group": "game",
                   "desc": "A wave of invaders marches across the top; the cannon below picks them off while bombs fall.",
                   "colors": ["#28ff3c", "#00c8ff", "#ff2828", "#ff8c00"]},
    "flappy":     {"label": "Flappy", "icon": "🐤", "fn": fx_flappy, "group": "game", "fits_fn": flappy_fits,
                   "desc": "A bird on autopilot hops through the gaps in the pipes, until it misses one.",
                   "colors": ["#ffdc00", "#14c828", "#000a1e"]},
    "tictactoe":  {"label": "Noughts & Crosses", "icon": "⭕", "fn": fx_tictactoe, "group": "game", "min_panels": 9,
                   "desc": "Two computer players take turns on nine panels. Red never loses; blue sometimes slips up.",
                   "colors": ["#ff1e1e", "#1e5aff", "#0e0e14"]},
    "lightsout":  {"label": "Lights Out", "icon": "💡", "fn": fx_lightsout, "group": "game", "min_panels": 6,
                   "desc": "Pressing a panel flips it and its neighbours. The wall works out the solution and plays it.",
                   "colors": ["#ffbe32", "#00e6ff", "#06081a"]},
    "maze":       {"label": "Maze", "icon": "🌀", "fn": fx_maze, "group": "game",
                   "desc": "A maze digs itself through every panel, then the route from start to finish lights up.",
                   "colors": ["#3c1478", "#b478ff", "#ffbe00", "#00dc78"]},
    "dice":       {"label": "Dice", "icon": "🎲", "fn": fx_dice, "group": "game", "min_panels": 6,
                   "desc": "The wall tumbles and lands on a number, shown as pips on the little triangles.",
                   "colors": ["#5a000a", "#fff5e6"]},
    "coin":       {"label": "Coin Toss", "icon": "🪙", "fn": fx_coin, "group": "game",
                   "desc": "Gold and silver spin across the wall, slower and slower, until it lands heads or tails.",
                   "colors": ["#ffb400", "#6e7d96"]},
    # ambient (added 1.3): slow looks to live with
    "fireplace":  {"label": "Fireplace", "icon": "🔥", "fn": fx_fireplace, "group": "ambient",
                   "desc": "Every panel flickers like a log fire: bright at the bottom, embers at the top.",
                   "colors": ["#ff9614", "#e64605", "#6e0f00"]},
    "storm":      {"label": "Storm", "icon": "⛈️", "fn": fx_storm, "group": "ambient",
                   "desc": "Dark clouds roll over and lightning forks through a few panels at a time.",
                   "colors": ["#04060e", "#161a30", "#c8d7ff"]},
    "ocean":      {"label": "Ocean Waves", "icon": "🌊", "fn": fx_ocean, "group": "ambient",
                   "desc": "Waves roll across the wall: deep blue troughs, teal swells and a pale foam crest.",
                   "colors": ["#00195a", "#008caa", "#aae6f0"]},
    "aurora":     {"label": "Northern Lights", "icon": "🌌", "fn": fx_aurora, "group": "ambient",
                   "desc": "Green and teal curtains with violet edges drift slowly across a dark sky.",
                   "colors": ["#14ff6e", "#00c8aa", "#8c32e6"]},
    "lava":       {"label": "Lava Lamp", "icon": "🫠", "fn": fx_lava, "group": "ambient",
                   "desc": "Warm blobs rise slowly through dark red wax and sink back down.",
                   "colors": ["#3c0014", "#ff3c00", "#ffaa1e"]},
    "nightsky":   {"label": "Night Sky", "icon": "🌠", "fn": fx_nightsky, "group": "ambient",
                   "desc": "Faint stars twinkle on a deep blue night, with the odd shooting star across the top.",
                   "colors": ["#020416", "#96aadc", "#e6ebff"]},
    "breathe":    {"label": "Breathe 4-7-8", "icon": "🫁", "fn": fx_breathe, "group": "ambient",
                   "desc": "A breathing guide: in for 4 s as the wall fills, hold for 7, out for 8 as it drains.",
                   "colors": ["#40c8ff", "#03101a"]},
    "moon":       {"label": "Moon Phase", "icon": "🌙", "fn": fx_moon, "group": "ambient", "desc_fn": moon_desc,
                   "desc": "A night light shaped like tonight's moon.",
                   "colors": ["#b4aa82", "#020205"]},
    "daycolour":  {"label": "Colour of the Day", "icon": "🗓️", "fn": fx_daycolour, "group": "ambient",
                   "desc_fn": daycolour_desc, "desc": "One rainbow colour for every day of the week.",
                   "colors": ["#ff2828", "#ff8200", "#ffd200", "#28d246", "#0096ff", "#5a3cff", "#c846ff"]},
    "countdown":  {"label": "Holiday Countdown", "icon": "📅", "fn": fx_countdown, "group": "ambient",
                   "desc_fn": countdown_desc, "desc": "Fills up as the next holiday gets closer.",
                   "colors": ["#e60014", "#00aa28", "#ff6e00", "#8200c8"]},
}


def _fits(effect, layout_json):
    """False only when we can see the layout and it lacks panels the effect needs
    (`needs`: those panel ids; `min_panels`: at least that many light panels;
    `fits_fn(shapes)`: the game's own test, e.g. Flappy needs columns to put pipes in)."""
    if not layout_json:
        return True
    try:
        pd = layout_json["panelLayout"]["layout"]["positionData"]
    except (KeyError, TypeError):
        return True
    need = effect.get("needs")
    if need and not set(need) <= {p["panelId"] for p in pd}:
        return False
    if len([p for p in pd if p["shapeType"] != CTRL_SHAPE]) < effect.get("min_panels", 1):
        return False
    if effect.get("fits_fn"):
        try:
            return bool(effect["fits_fn"](light_shapes(layout_json)))
        except Exception:
            return False
    return True


def catalogue(layout_json=None):
    def desc(v):
        try:
            return v["desc_fn"](v) if v.get("desc_fn") else v["desc"]
        except Exception:
            return v["desc"]
    return [{"name": k, "label": v["label"], "icon": v["icon"], "desc": desc(v), "colors": v["colors"],
             "group": v.get("group", "effect")}
            for k, v in EFFECTS.items() if _fits(v, layout_json)]


def build(name, layout_json):
    if name not in EFFECTS:
        raise ValueError(f"No effect called '{name}'. Try: " + ", ".join(EFFECTS))
    e = EFFECTS[name]
    if not _fits(e, layout_json):
        raise ValueError(f"'{name}' doesn't fit your wall's layout (it needs a different shape or more panels).")
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
