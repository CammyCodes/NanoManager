#!/usr/bin/env python3
"""Playable Simon on the wall: the game's rules and the animations it sends. No device I/O.

The wall is split into the same four colour zones as the Simon demo (effects.simon_zones).
Each round adds one random zone and the whole sequence is shown as ONE play-once custom
animation that ends on the dim board, so a round costs a single write. Each zone has a
swipe direction (the panels only report swipes, never taps or which panel); a correct move
(a swipe that way, or a tap on the zone in the app) is answered with one short flash; a
wrong one (or nothing for INPUT_TIMEOUT) ends the game with the whole wall flashing red,
then the zone that was wanted.

nanoleaf_server.py runs the game loop (timing, writes through the rate limiter, swipes
from the device's touch events) and keeps the best score in games.json.
"""
import itertools, math, random
import effects
from effects import OFF, WHITE, dim, events_to_frames

IDLE = 0.15             # brightness of a zone when it isn't lit
INPUT_TIMEOUT = 8.0     # seconds the player gets for each tap before it counts as a miss
LEAD = 4                # tenths of dim board before a sequence starts


def speed(n):
    """(hold, gap) in tenths for the n-th round: it gets quicker as the sequence grows."""
    if n <= 4:
        return 4, 3
    if n <= 8:
        return 3, 2
    if n <= 12:
        return 2, 2
    return 1, 1


class Board:
    """The wall as Simon zones."""

    def __init__(self, layout_json):
        shapes = effects.light_shapes(layout_json)
        self.zone, self.colour, self.order = effects.simon_zones(shapes, effects.adjacency(shapes))
        self.ids = sorted(self.zone)
        self.direction = self._directions({p["panelId"]: effects.centre(pts) for p, pts in shapes})
        self.by_direction = {d: z for z, d in self.direction.items()}

    def _directions(self, pos):
        """{zone: "up"|"right"|"down"|"left"}: the wall only reports swipe directions, so each
        zone is pressed by swiping towards where it sits (best match over all assignments)."""
        cx = sum(x for x, _ in pos.values()) / len(pos); cy = sum(y for _, y in pos.values()) / len(pos)
        vec = {}
        for z in self.colour:
            m = [pos[p] for p in self.ids if self.zone[p] == z]
            dx = sum(x for x, _ in m) / len(m) - cx; dy = sum(y for _, y in m) / len(m) - cy
            n = math.hypot(dx, dy) or 1.0
            vec[z] = (dx / n, dy / n)
        dirs = {"up": (0, -1), "right": (1, 0), "down": (0, 1), "left": (-1, 0)}   # screen space, y down
        zones = list(self.colour)
        best = max(itertools.permutations(dirs, len(zones)),
                   key=lambda ds: sum(vec[z][0] * dirs[d][0] + vec[z][1] * dirs[d][1] for z, d in zip(zones, ds)))
        return dict(zip(zones, best))

    def zone_for(self, direction):
        return self.by_direction.get(direction)

    def zone_of(self, pid):
        try:
            return self.zone.get(int(pid))
        except (TypeError, ValueError):
            return None

    def idle(self, z):
        return dim(self.colour[z], IDLE)

    def hexes(self, lit=None):
        """{panelId: "#rrggbb"} for the page: the dim board, with zone `lit` full on."""
        out = {}
        for pid in self.ids:
            z = self.zone[pid]
            out[str(pid)] = "#%02x%02x%02x" % (self.colour[z] if z == lit else self.idle(z))
        return out

    def _body(self, per):
        totals = {sum(t for _, t in fr) for fr in per.values()}
        assert len(totals) == 1, totals
        body = effects.body_from(per)
        body["loop"] = False                    # play once and stay on the last frame (the dim board)
        return body

    def idle_body(self, fade=6):
        return self._body({pid: [(self.idle(self.zone[pid]), fade)] for pid in self.ids})

    def show_body(self, seq):
        """The whole sequence in one animation. Returns (body, seconds)."""
        hold, gap = speed(len(seq))
        events, t = {z: [] for z in self.colour}, LEAD
        for z in seq:
            c = self.colour[z]
            events[z].append((t, [(c, 1), (c, hold), (self.idle(z), 2)]))
            t += 1 + hold + 2 + gap
        per = {pid: events_to_frames(events[self.zone[pid]], t, base=self.idle(self.zone[pid])) for pid in self.ids}
        return self._body(per), t / 10.0

    def press_body(self, z):
        """The player's press: that zone flashes and fades back."""
        per = {}
        for pid in self.ids:
            q = self.zone[pid]
            per[pid] = [(self.colour[q], 1), (self.colour[q], 2), (self.idle(q), 3)] if q == z else [(self.idle(q), 6)]
        return self._body(per)

    def over_body(self, wanted, new_best):
        """Game over: the whole wall flashes red three times, then shows the zone that was
        wanted; a new best gets an extra flash in all four colours. Returns (body, seconds)."""
        red = (255, 0, 0)
        per = {}
        for pid in self.ids:
            q = self.zone[pid]
            fr = [(red, 1), (red, 2), (OFF, 2)] * 3
            fr += [(self.colour[q], 2), (self.colour[q], 8)] if q == wanted else [(OFF, 2), (OFF, 8)]
            if new_best:
                fr += [(OFF, 2)] + [(self.colour[q], 1), (WHITE, 1), (self.colour[q], 2), (OFF, 2)] * 3
            fr += [(self.idle(q), 6)]
            per[pid] = fr
        return self._body(per), sum(t for _, t in per[self.ids[0]]) / 10.0


class Game:
    """One game of Simon: the sequence, where the player is in it, and the score."""

    def __init__(self, zones, rnd=None):
        self.zones = list(zones)
        self.rnd = rnd or random.Random()
        self.seq, self.step, self.score, self.over = [], 0, 0, False

    def next_round(self):
        self.seq.append(self.rnd.choice(self.zones))
        self.step = 0
        return list(self.seq)

    @property
    def wanted(self):
        return self.seq[self.step] if self.step < len(self.seq) else None

    def press(self, z):
        """'ok' (keep going), 'round' (sequence complete), or 'fail'."""
        if self.over or z != self.wanted:
            self.over = True
            return "fail"
        self.step += 1
        if self.step == len(self.seq):
            self.score = len(self.seq)
            return "round"
        return "ok"

    def time_out(self):
        self.over = True
