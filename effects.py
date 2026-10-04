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


def fx_simon(shapes, adj, o):
    """Simon. The wall splits into four dim zones; Simon plays a sequence that grows by
    one every round and the player repeats it, a little quicker. After five rounds the
    zones spin round in a victory lap."""
    rnd = random.Random(o.get("seed", 4))
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
    simon = [(0, 220, 40), (255, 20, 20), (30, 70, 255), (255, 200, 0)]   # green, red, blue, yellow
    colour = {z: simon[k] for k, z in enumerate(order)}
    rounds = 5
    seq = [rnd.randrange(len(seeds)) for _ in range(rounds)]
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
    return [{"name": k, "label": v["label"], "icon": v["icon"], "desc": v["desc"], "colors": v["colors"],
             "group": v.get("group", "effect")}
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
