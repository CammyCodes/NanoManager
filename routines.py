#!/usr/bin/env python3
"""Routines: timed things the server runs by itself, and the schedule. No device I/O.

- Sunrise alarm: the wall wakes up over N minutes, from a dim deep red through orange to
  bright daylight white (`sunrise_point`).
- Sleep timer: the brightness fades to nothing over N minutes, then the panels switch off.
- Pomodoro: work for 25 minutes while the panels drain one by one, then a 5-minute break in
  green (`pomodoro_map`).
- Slideshow: a new favourite (or mood) every few minutes, with a slow crossfade.
- Schedule: "at 07:00 on weekdays", "at sunset + 15 min", "at 23:00" ... play a scene, switch
  the panels on/off, or start one of the routines above (`fire_time`, `clean_entry`).

nanoleaf_server.py runs them (one routine at a time, every write through write()).
"""
import datetime, math

ROUTINES = ("sunrise", "sleep", "pomodoro", "slideshow")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------- sun
def sun_times(day, lat, lon):
    """(sunrise, sunset) as local naive datetimes for a date at lat/lon (degrees, east +).
    NOAA's sunrise equation; good to a minute or two. None for a time that doesn't happen
    (midnight sun / polar night)."""
    n = (datetime.date(day.year, day.month, day.day) - datetime.date(2000, 1, 1)).days + 0.0008
    js = n - lon / 360.0                                        # mean solar time
    m = math.radians((357.5291 + 0.98560028 * js) % 360)        # solar mean anomaly
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    jt = 2451545.0 + js + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)   # solar transit (Julian)
    dec = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(dec)) / (math.cos(phi) * math.cos(dec))
    if cos_w < -1 or cos_w > 1:
        return None, None
    w = math.degrees(math.acos(cos_w))

    def local(jd):
        ts = (jd - 2440587.5) * 86400.0                         # Julian day -> unix time
        return datetime.datetime.fromtimestamp(ts).replace(second=0, microsecond=0)
    return local(jt - w / 360.0), local(jt + w / 360.0)


# ---------------------------------------------------------------- seasonal mood
def season_mood(day):
    """The page mood (PRESETS name) that fits the time of year."""
    m, d = day.month, day.day
    if m == 12:
        return "Christmas"
    if m == 10 and d >= 15:
        return "Halloween"
    if m == 2 and d <= 14:
        return "Love"
    if m in (1, 2):
        return "Ice"
    if m in (3, 4):
        return "Cherry Blossom"
    if m == 5:
        return "Mint"
    if m in (6, 7, 8):
        return "Seafoam"
    if m == 9:
        return "Honey"
    return "Fireside"                                           # October, November


# ---------------------------------------------------------------- sunrise alarm
SUNRISE = [  # (fraction of the way, colour, brightness)
    (0.00, ("hs", 0, 100), 1),
    (0.30, ("hs", 12, 100), 12),
    (0.55, ("hs", 28, 85), 35),
    (0.75, ("ct", 2200), 60),
    (0.90, ("ct", 3200), 85),
    (1.00, ("ct", 5000), 100),
]


def sunrise_point(f):
    """The wall at fraction f (0..1) of a sunrise alarm: (state body without duration)."""
    f = max(0.0, min(1.0, f))
    for (f0, c0, b0), (f1, c1, b1) in zip(SUNRISE, SUNRISE[1:]):
        if f <= f1:
            t = (f - f0) / (f1 - f0) if f1 > f0 else 1
            break
    bright = int(round(b0 + (b1 - b0) * t))
    if c0[0] == "hs" and c1[0] == "hs":
        col = {"hue": {"value": int(round(c0[1] + (c1[1] - c0[1]) * t))},
               "sat": {"value": int(round(c0[2] + (c1[2] - c0[2]) * t))}}
    elif c1[0] == "ct" and c0[0] == "ct":
        col = {"ct": {"value": int(round(c0[1] + (c1[1] - c0[1]) * t))}}
    else:                                                       # the jump from orange to warm white
        col = {"ct": {"value": c1[1]}} if t >= .5 else {"hue": {"value": c0[1]}, "sat": {"value": c0[2]}}
    return dict(col, brightness={"value": max(1, bright)})


# ---------------------------------------------------------------- pomodoro
WORK_C, WORK_DIM = (255, 70, 30), (40, 6, 2)
BREAK_C, BREAK_DIM = (40, 220, 90), (3, 30, 10)


def drain_order(pos):
    """Panels in the order they go dark: top first, like sand running out."""
    return sorted(pos, key=lambda i: (pos[i][1], pos[i][0]))


def pomodoro_map(order, left, phase):
    """{panelId: rgb} with `left` (0..1) of the panels still lit."""
    on, off = (WORK_C, WORK_DIM) if phase == "work" else (BREAK_C, BREAK_DIM)
    n = len(order)
    lit = int(math.ceil(left * n - 1e-9))
    return {pid: (on if k >= n - lit else off) for k, pid in enumerate(order)}


def chime(per_final, colour, pulses=3):
    """A one-shot custom animation: `pulses` soft pulses of colour on every panel, then it
    rests on per_final ({panelId: rgb}). Written with loop:false so the last frame holds."""
    per = {}
    for pid, end in per_final.items():
        fr = [((0, 0, 0), 2)]
        for _ in range(pulses):
            fr += [(colour, 3), (tuple(int(c * .15) for c in colour), 3)]
        fr.append((end, 6))
        per[pid] = fr
    return per


# ---------------------------------------------------------------- schedule
def parse_hhmm(s):
    try:
        h, m = str(s).split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


def clean_entry(e):
    """Validate a schedule entry from the page. Returns the cleaned entry or None.
    {"id", "at": "HH:MM"|"sunrise"|"sunset", "offset": minutes, "days": [0..6] (Mon=0),
     "action": {"key": "mood:Cozy"} | {"power": "on"|"off"} | {"routine": "sunrise"|"sleep"|..., "minutes": n},
     "on": bool, "label": str}"""
    if not isinstance(e, dict):
        return None
    at = str(e.get("at", "")).strip().lower()
    if at not in ("sunrise", "sunset") and not parse_hhmm(at):
        return None
    if at not in ("sunrise", "sunset"):
        at = "%02d:%02d" % parse_hhmm(at)
    try:
        offset = max(-240, min(240, int(e.get("offset") or 0)))
    except (TypeError, ValueError):
        offset = 0
    days = sorted({int(d) for d in (e.get("days") if isinstance(e.get("days"), list) else range(7))
                   if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
    if not days:
        return None
    a = e.get("action") if isinstance(e.get("action"), dict) else {}
    if a.get("key"):
        action = {"key": str(a["key"])[:120]}
    elif a.get("power") in ("on", "off"):
        action = {"power": a["power"]}
    elif a.get("routine") in ROUTINES:
        try:
            mins = max(1, min(180, int(a.get("minutes") or 30)))
        except (TypeError, ValueError):
            mins = 30
        action = {"routine": a["routine"], "minutes": mins}
    else:
        return None
    return {"id": str(e.get("id") or "")[:40], "at": at, "offset": offset if at in ("sunrise", "sunset") else 0,
            "days": days, "action": action, "on": bool(e.get("on", True)), "label": str(e.get("label") or "")[:60]}


def fire_time(e, day, lat=None, lon=None):
    """When entry e fires on date `day` (local naive datetime), or None (not that weekday,
    sunrise/sunset without a location, or the sun doesn't rise/set that day)."""
    if day.weekday() not in e["days"]:
        return None
    if e["at"] in ("sunrise", "sunset"):
        if lat is None or lon is None:
            return None
        rise, set_ = sun_times(day, lat, lon)
        t = rise if e["at"] == "sunrise" else set_
        if t is None:
            return None
        t = t + datetime.timedelta(minutes=e.get("offset") or 0)
        return t if t.date() == day else None
    h, m = parse_hhmm(e["at"])
    return datetime.datetime(day.year, day.month, day.day, h, m)


def due(e, now, last_fired, lat=None, lon=None, window=300):
    """Should e fire now? `last_fired` = the fire time (iso string) it last fired for.
    Fires once per occurrence, and only within `window` seconds after the time (a Mac that
    was asleep at 07:00 doesn't start the alarm at noon)."""
    if not e.get("on", True):
        return None
    for day in (now.date() - datetime.timedelta(days=1), now.date()):
        t = fire_time(e, day, lat, lon)
        if t is None:
            continue
        if 0 <= (now - t).total_seconds() <= window and last_fired != t.isoformat():
            return t
    return None


def next_fire(e, now, lat=None, lon=None):
    """The next time e will fire (for the page), or None."""
    if not e.get("on", True):
        return None
    for k in range(8):
        day = now.date() + datetime.timedelta(days=k)
        t = fire_time(e, day, lat, lon)
        if t is not None and t > now:
            return t
    return None


def describe(e):
    days = e["days"]
    if days == list(range(7)):
        when = "every day"
    elif days == [0, 1, 2, 3, 4]:
        when = "weekdays"
    elif days == [5, 6]:
        when = "weekends"
    else:
        when = ", ".join(DAYS[d] for d in days)
    at = e["at"]
    if at in ("sunrise", "sunset"):
        off = e.get("offset") or 0
        at = at + (f" {'+' if off > 0 else '−'} {abs(off)} min" if off else "")
    return f"{at}, {when}"
