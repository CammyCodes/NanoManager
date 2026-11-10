#!/usr/bin/env python3
"""Local control panel for Nanoleaf Shapes.

Serves the control page and proxies to the panels. The proxy is the safety layer:
the Nanoleaf controller falls off the network if it is written to too fast, so every
write is serialised, rate limited, and circuit broken here. No matter what the page
does, the device cannot be flooded.

It also keeps a live copy of the device state. A background thread listens to the
panels' own event stream, so changes made from the Nanoleaf app or HomeKit show up on
the page within a second, and the page is pushed updates over server-sent events
(/api/events) instead of polling.

Config (all optional, sensible defaults):
  NANOLEAF_IP       device address           (default: none, it is found on the network)
  NANOLEAF_PORT     device API port          (default 16021)
  NANOLEAF_TOKEN    auth token               (default: contents of token.txt)
  NANOLEAF_UI_PORT  port this UI listens on  (default 8765)
  NANOLEAF_DATA_DIR where token.txt, scenes.json, favorites.json, ui_state.json and
                    palettes.json live
                    (default: next to this script; the NanoManager app uses
                    ~/Library/Application Support/NanoManager)

Reconnecting: once the panels have been found (or re-paired) their address and token
are remembered in device.json in the data folder, which then takes precedence over
NANOLEAF_IP / token.txt. See reconnect_job() for how a lost device is found again.
"""
import datetime, hashlib, hmac, json, math, os, queue, secrets, socket, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import message                      # spelling messages one character at a time
import routines                     # sunrise alarm, sleep timer, pomodoro, slideshow, schedule
import qr                           # QR codes for opening the page on a phone
import effects                      # Snake, Starlight, Ripple… built as custom animations
import replicate                    # Replicate: the wall mirrors the Mac's screen
import simon                        # Play Simon: a real game, played by swiping on the panels
import remote                       # Debug mode: step through scenes by swiping on the wall
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("NANOLEAF_DATA_DIR") or HERE
os.makedirs(DATA, exist_ok=True)


def _read_token():
    env = os.environ.get("NANOLEAF_TOKEN")
    if env:
        return env.strip()
    for d in (DATA, HERE):
        try:
            with open(os.path.join(d, "token.txt")) as f:
                return f.read().strip()
        except OSError:
            continue
    return ""       # no token: every request will be refused until we pair (see reconnect)


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[save {os.path.basename(path)}] {e}", flush=True)


NANO_PORT = int(os.environ.get("NANOLEAF_PORT", "16021"))
# NANOLEAF_LISTEN=0.0.0.0 lets phones on the Wi-Fi open the page (the NanoManager app does this)
LISTEN = (os.environ.get("NANOLEAF_LISTEN", "127.0.0.1"), int(os.environ.get("NANOLEAF_UI_PORT", "8765")))
MOBILE_DIR = os.path.join(HERE, "mobile")           # phone layout + Home Screen icons
MOBILE_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".png": "image/png", ".webmanifest": "application/manifest+json"}
DEVICE_FILE = os.path.join(DATA, "device.json")     # learned address + token

# Live device config. device.json (what we last found) beats the env/defaults.
_cfg_lock = threading.Lock()
_cfg = {"ip": os.environ.get("NANOLEAF_IP", ""), "token": _read_token()}
_saved = _load_json(DEVICE_FILE, {})
if _saved.get("ip"):
    _cfg["ip"] = _saved["ip"]
if _saved.get("token"):
    _cfg["token"] = _saved["token"]


def cfg():
    with _cfg_lock:
        return dict(_cfg)


def set_cfg(ip=None, token=None):
    with _cfg_lock:
        if ip:
            _cfg["ip"] = ip
        if token:
            _cfg["token"] = token
        _save_json(DEVICE_FILE, dict(_cfg))


def base(ip=None, token=None):
    c = cfg()
    return f"http://{ip or c['ip']}:{NANO_PORT}/api/v1/{token if token is not None else c['token']}"

MIN_WRITE_GAP = 0.6     # seconds between writes to the device (hard ceiling ~1.6/s)
FAIL_LIMIT    = 3       # consecutive failures before the breaker opens
COOLDOWN      = 20.0    # seconds to stop writing after the breaker opens
POLL_EVERY    = 20.0    # safety-net state refresh even if no event arrives

SCENES_FILE = os.path.join(DATA, "scenes.json")     # user-saved scenes
UI_FILE     = os.path.join(DATA, "ui_state.json")   # what the page last wrote

_write_lock = threading.Lock()
_last_write = 0.0
_fails = 0
_breaker_until = 0.0
_last_error = ""


# ----------------------------------------------------------------- device I/O
def _raw(method, path, body=None, timeout=6):
    url = base() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (r.read().decode() or "{}")


def read(path="/"):
    """Reads are cheap; one retry, never trips the breaker."""
    for attempt in (0, 1):
        try:
            return _raw("GET", path)
        except Exception as e:
            if attempt:
                return 502, json.dumps({"error": str(e)})
            time.sleep(0.4)
    return 502, json.dumps({"error": "unreachable"})


def write(path, body):
    """Serialised + rate limited + circuit broken. This is what protects the device."""
    global _last_write, _fails, _breaker_until, _last_error
    now = time.time()
    if now < _breaker_until:
        return 503, json.dumps({
            "error": "paused",
            "detail": f"Panels stopped responding; pausing writes for "
                      f"{int(_breaker_until - now)}s so the controller can recover."})
    with _write_lock:
        gap = time.time() - _last_write
        if gap < MIN_WRITE_GAP:
            time.sleep(MIN_WRITE_GAP - gap)
        try:
            status, body_out = _raw("PUT", path, body)
            _last_write = time.time()
            _fails = 0
            _last_error = ""
            return status, body_out
        except urllib.error.HTTPError as e:
            _last_write = time.time()
            detail = e.read().decode("utf8", "ignore")
            _last_error = f"HTTP {e.code}"
            print(f"[write {path}] HTTP {e.code} detail={detail[:200]!r} "
                  f"body={json.dumps(body)[:300]}", flush=True)
            return e.code, json.dumps({"error": f"HTTP {e.code}", "detail": detail})
        except Exception as e:
            _last_write = time.time()
            _fails += 1
            _last_error = str(e)
            print(f"[write {path}] FAILED {e} (fail {_fails}/{FAIL_LIMIT})", flush=True)
            if _fails >= FAIL_LIMIT:
                _breaker_until = time.time() + COOLDOWN
                _fails = 0
                broadcast_state()
                return 503, json.dumps({
                    "error": "paused",
                    "detail": f"Panels unreachable ({e}); pausing writes {int(COOLDOWN)}s."})
            return 502, json.dumps({"error": str(e)})


# ---------------------------------------------------------------- live state
_state = None            # last successful GET / from the device
_state_ts = 0.0
_reachable = False       # did the last read of the device succeed?
_state_lock = threading.Lock()
_clients = []            # queues of browsers subscribed to /api/events
_clients_lock = threading.Lock()
_refresh_timer = None
_refresh_lock = threading.Lock()

# The device never reports per-panel colours or the name of a custom effect, so the
# page tells us what it wrote and we remember it (survives restarts via ui_state.json).
_ui = _load_json(UI_FILE, {"sceneName": None, "panels": {}, "message": None, "fx": None})
_ui_lock = threading.Lock()


_phone = (0.0, None)


def phone_url():
    """Where a phone on the same Wi-Fi can open this page (only when we listen beyond this computer)."""
    global _phone
    if LISTEN[0] != "0.0.0.0":
        return None
    at, url = _phone
    if time.time() - at > 60:
        ip = local_ip()
        url = f"http://{ip}:{LISTEN[1]}" if ip else None
        _phone = (time.time(), url)
    return url


def snapshot():
    now = time.time()
    with _state_lock:
        st, ts = _state, _state_ts
    with _ui_lock:
        ui = dict(_ui)
    with _rc_lock:
        rc = dict(_rc)
    return {
        "online": st is not None and _reachable,
        "paused": now < _breaker_until,
        "pausedFor": max(0, int(_breaker_until - now)),
        "lastError": _last_error,
        "ts": ts,
        "device": st,
        "deviceIp": cfg()["ip"],
        "reconnect": rc,
        "ui": ui,
        "favorites": favs_list(),
        "replicate": rep_status(),
        "simon": sim_status(),
        "debug": dbg_status(),
        "touch": touch_status(),
        "phoneUrl": phone_url(),
        "glyphsOk": message.fits(st) if st else None,     # False: messages can't be spelled on this layout
        "routine": rt_status(),
        "settings": settings_public(),
    }


def broadcast_state():
    data = json.dumps(snapshot())
    with _clients_lock:
        for q in list(_clients):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def refresh_state():
    """Pull the full state from the device and push it to every open page."""
    global _state, _state_ts, _reachable
    code, body = read("/")
    if code != 200:
        _reachable = False
        broadcast_state()           # tells pages we are offline
        auto_reconnect()            # and quietly go looking for the panels
        return False
    try:
        d = json.loads(body)
    except ValueError:
        return False
    with _state_lock:
        _state, _state_ts = d, time.time()
    _reachable = True
    sel = (d.get("effects") or {}).get("select", "")
    mode = (d.get("state") or {}).get("colorMode", "")
    # A device-saved scene or a plain colour is showing: whatever custom scene the
    # page last wrote is gone, so stop claiming it.
    if (sel and not sel.startswith("*")) or mode in ("hs", "ct"):
        if (sim_active() or dbg_active()) and time.time() - _touch_at < 4:
            # The swipe that was a Simon move / debug-mode button also fired the wall's own
            # touch action (set in the Nanoleaf app) and changed the scene: put ours back.
            (_sim_q if sim_active() else _dbg_q).put(("resync", None))
            broadcast_state()
            return True
        with _ui_lock:
            if _ui.get("sceneName") or _ui.get("panels") or _ui.get("message") or _ui.get("fx"):
                _ui.update({"sceneName": None, "panels": {}, "message": None, "fx": None})
                _save_json(UI_FILE, _ui)
    broadcast_state()
    return True


def schedule_refresh(delay=0.3):
    """Debounced refresh: bursts of device events collapse into one read."""
    global _refresh_timer
    with _refresh_lock:
        if _refresh_timer:
            _refresh_timer.cancel()
        _refresh_timer = threading.Timer(delay, refresh_state)
        _refresh_timer.daemon = True
        _refresh_timer.start()


def device_event_loop():
    """Follow the panels' own event stream (state + effect changes) forever."""
    while True:
        try:
            req = urllib.request.Request(base() + "/events?id=1,3,4")
            with urllib.request.urlopen(req, timeout=120) as r:
                refresh_state()
                ev = ""
                for raw in r:
                    line = raw.decode("utf8", "ignore").strip()
                    if line.startswith("id:"):
                        ev = line[3:].strip()
                    elif line.startswith("data:") and ev == "4":
                        on_touch(line[5:])              # a tap on the panels: only Simon listens
                    elif line.startswith("data:"):
                        # Replicate writes about once a second and already knows what it
                        # wrote; re-reading the whole device each time would double the load.
                        if rep_active() and time.time() - _state_ts < 15:
                            continue
                        schedule_refresh(0.3)
        except Exception:
            pass
        time.sleep(5)


# ---------------------------------------------------------------- touch
# Touch events: {"events":[{"panelId":N,"gesture":G}]}. On this wall (Shapes, FW 7.1.6) only
# swipes ever arrive (gesture 2-5, panelId -1, ~0.5 s late); taps (0/1, with a panel id) are
# documented but never sent, holds send nothing, and the UDP touch stream stays silent. Taps
# are still handled in case another firmware sends them. Swipes drive Play Simon and debug
# mode. Directions arrive as seen on the wall (its mounting rotation doesn't apply); the first
# event of a swipe is the real one and an "echo" in the opposite direction often follows
# 0.4-0.6 s later, which SWIPE_GAP drops.
SWIPES = {2: "up", 3: "down", 4: "left", 5: "right"}
SWIPE_GAP = 0.8         # one movement can report more than once: ignore swipes closer than this
DEBUG_PATTERN = ["down", "up", "down"]
DEBUG_GAP = 8.0         # seconds allowed between the swipes of the pattern
TOUCH_FILE = os.path.join(DATA, "touch.json")       # {"rotate": degrees} if swipes come out turned
_touch = {"dir": None, "raw": None, "at": 0.0, "n": 0}
_touch_lock = threading.Lock()
_touch_at = 0.0
_last_swipe = 0.0
_pattern = []


def touch_rotation():
    """Degrees to turn the device's swipe directions by. 0: the wall reports them as seen (checked
    on a wall mounted at 180°); touch.json can turn them if another wall differs."""
    saved = _load_json(TOUCH_FILE, {})
    if isinstance(saved.get("rotate"), (int, float)):
        return saved["rotate"] % 360
    return 0


def touch_status():
    with _touch_lock:
        out = dict(_touch)
    out["rotate"] = touch_rotation()
    return out


def swipe_dir(raw):
    """Reported direction -> the direction to act on, turned clockwise by touch_rotation()."""
    vx, vy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[raw]   # screen space, y down
    r = math.radians(touch_rotation())
    sx, sy = vx * math.cos(r) - vy * math.sin(r), vx * math.sin(r) + vy * math.cos(r)
    if abs(sx) > abs(sy):
        return "right" if sx > 0 else "left"
    return "down" if sy > 0 else "up"


def on_touch(data):
    try:
        events = json.loads(data).get("events") or []
    except (ValueError, AttributeError):
        return
    for e in events:
        pid, gesture = e.get("panelId"), e.get("gesture")
        if gesture in SWIPES:
            on_swipe(SWIPES[gesture])
        elif gesture in (0, 1) and isinstance(pid, int) and pid >= 0:
            for _ in range(2 if gesture == 1 else 1):
                sim_tap(pid, wall=True)


def on_swipe(raw):
    global _touch_at, _last_swipe
    now = time.time()
    if now - _last_swipe < SWIPE_GAP:
        print(f"[touch] {time.strftime('%H:%M:%S')} swipe {raw} ignored (echo / too soon after the last one)", flush=True)
        return
    _last_swipe = _touch_at = now
    d = swipe_dir(raw)
    print(f"[touch] {time.strftime('%H:%M:%S')} swipe {raw}" + (f" -> {d}" if d != raw else ""), flush=True)
    with _touch_lock:
        _touch.update({"dir": d, "raw": raw, "at": now, "n": _touch["n"] + 1})
    if dbg_active():
        _dbg_q.put({"left": ("step", -1), "right": ("step", 1), "up": ("toggle", None), "down": ("exit", None)}[d])
    elif sim_active() and sim_phase() == "input":
        del _pattern[:]                         # the game has the wall: no debug pattern mid-sequence
        _sim_q.put(("swipe", d))
    else:
        _pattern.append((d, now))
        del _pattern[:-len(DEBUG_PATTERN)]
        if [x for x, _ in _pattern] == DEBUG_PATTERN and \
                all(b - a <= DEBUG_GAP for (_, a), (_, b) in zip(_pattern, _pattern[1:])):
            del _pattern[:]
            print("[debug] pattern down-up-down", flush=True)
            dbg_enter()
        elif sim_active():
            _sim_q.put(("swipe", d))            # waiting/game over: a swipe starts a game
    broadcast_state()


def poll_loop():
    """Safety net: reads are cheap, so re-sync every POLL_EVERY seconds regardless."""
    while True:
        time.sleep(POLL_EVERY)
        refresh_state()


# ---------------------------------------------------------------- replicate
# The Mac app (NanoManager.swift) captures a tiny thumbnail of the main screen and
# posts it to /api/replicate/frame while _ui.fx is Replicate. One worker thread turns
# the latest thumbnail into panel colours and writes them, at most once per REP_GAP
# and only when a panel changed visibly, so a still screen means no writes at all.
REP_NAME   = "replicate"
REP_GAP    = 1.0        # seconds between Replicate writes (on top of MIN_WRITE_GAP)
REP_FADE   = 10         # tenths: each write fades over the gap, so changes look smooth
REP_STALE  = 6.0        # no frame for this long = the Mac app isn't capturing
REP_GRID   = (32, 20)   # thumbnail the app is asked for (it adapts h to the screen shape)
_rep = {"grid": None, "gridAt": 0.0, "error": "", "errorAt": 0.0, "sent": {}, "writes": 0}
_rep_lock = threading.Lock()
_rep_wake = threading.Event()
_rep_thread = None


def rep_active():
    with _ui_lock:
        fx = _ui.get("fx") or {}
    return fx.get("name") == REP_NAME


def rep_status():
    now = time.time()
    with _rep_lock:
        err = _rep["error"] if now - _rep["errorAt"] < 30 else ""
        return {"active": rep_active(), "capturing": now - _rep["gridAt"] < REP_STALE,
                "error": err, "writes": _rep["writes"]}


def rep_start():
    global _rep_thread
    with _rep_lock:
        _rep.update({"grid": None, "gridAt": 0.0, "sent": {}})
        if _rep_thread is None:
            _rep_thread = threading.Thread(target=rep_loop, daemon=True)
            _rep_thread.start()
    _rep_wake.set()


def rep_loop():
    global _rep_thread
    while True:
        rep_run()
        with _rep_lock:                         # exit under the lock so rep_start can't miss us leaving
            if not rep_active():
                _rep["grid"] = None
                _rep_thread = None
                return


def rep_run():
    mapper, last_write = replicate.Mapper(), 0.0
    while rep_active():
        _rep_wake.wait(3.0)
        _rep_wake.clear()
        wait = REP_GAP - (time.time() - last_write)
        if wait > 0:
            time.sleep(wait)
        with _rep_lock:
            grid = _rep["grid"]
        with _state_lock:
            st = _state
        if not grid or not st or not rep_active():
            continue
        if not (st.get("state") or {}).get("on", {}).get("value", True):
            continue                            # panels switched off: don't turn them back on
        try:
            colours = mapper.update(st, grid)
        except (ValueError, KeyError) as e:
            print(f"[replicate] bad frame: {e}", flush=True)
            with _rep_lock:
                _rep["grid"] = None
            continue
        with _rep_lock:
            sent = _rep["sent"]
        if not replicate.changed(colours, sent):
            continue                            # settled: sleep until the next frame
        code, _ = write("/effects", {"write": replicate.static_body(colours, REP_FADE)})
        last_write = time.time()
        if not (200 <= code < 300):
            time.sleep(3)                       # breaker/HTTP error: back off, don't hammer
            continue
        with _rep_lock:
            _rep["sent"] = colours
            _rep["writes"] += 1
        with _ui_lock:
            if (_ui.get("fx") or {}).get("name") == REP_NAME:
                _ui["panels"] = {str(k): "#%02x%02x%02x" % v for k, v in colours.items()}
        with _state_lock:                       # we know what the device shows now
            if _state:
                _state["effects"]["select"] = "*Static*"
                _state["state"]["colorMode"] = "effect"
        broadcast_state()
        _rep_wake.set()                         # keep easing towards the target until settled
    with _ui_lock:                              # remember the last colours once, not every second
        _save_json(UI_FILE, _ui)


# ---------------------------------------------------------------- play Simon
# _ui.fx = {name: "simon_play"} while the game is on. One worker thread runs it: each round
# is ONE play-once animation (simon.Board.show_body), each correct tap one short flash, all
# through write(). Taps come from the panels' touch events (on_touch) or from the page
# (PUT /api/simon {"tap": panelId}) and are queued; when taps outrun the rate limiter only
# the newest gets its flash, but every tap still counts. The best score is in games.json.
SIMON_NAME = "simon_play"
SIMON_CARD = {"name": SIMON_NAME, "label": "Play Simon", "icon": "🎮", "group": "game", "play": True,
              "desc": "A real game: watch the colours, then swipe towards the same zones on the wall (or tap them "
                      "here). One more every round, until you slip.",
              "colors": ["#00dc28", "#ff1414", "#1e46ff", "#ffc800"]}
GAMES_FILE = os.path.join(DATA, "games.json")
_sim = {"phase": "idle", "score": 0, "best": 0, "round": 0, "step": 0, "newBest": False,
        "board": {}, "zones": {}, "colours": {}, "dirs": {}, "show": None, "flash": None, "over": None, "id": 0}
_sim_lock = threading.Lock()
_sim_q = queue.Queue()
_sim_thread = None


def sim_active():
    with _ui_lock:
        fx = _ui.get("fx") or {}
    return fx.get("name") == SIMON_NAME


def sim_best():
    return int((_load_json(GAMES_FILE, {}).get("simon") or {}).get("best") or 0)


def sim_status():
    with _sim_lock:
        out = dict(_sim)
    out["active"] = sim_active()
    if not out["active"]:
        out.update({"phase": "idle", "board": {}, "show": None})
    return out


_sim["best"] = sim_best()


def sim_phase():
    with _sim_lock:
        return _sim["phase"]


def sim_tap(pid, wall=False):
    global _touch_at
    if not sim_active():
        return False
    if wall:
        _touch_at = time.time()
    _sim_q.put(("tap", pid))
    return True


def sim_start(play=True):
    """Start the worker (or restart the game if it's already running)."""
    global _sim_thread
    with _sim_lock:
        if _sim_thread is None:
            while not _sim_q.empty():
                _sim_q.get_nowait()
            _sim_thread = threading.Thread(target=sim_loop, args=(play,), daemon=True)
            _sim_thread.start()
            return
    _sim_q.put(("new", None) if play else ("resync", None))


def sim_loop(play):
    global _sim_thread
    while True:
        try:
            sim_run(play)
        except Exception as e:                  # never leave the game wedged
            print(f"[simon] {type(e).__name__}: {e}", flush=True)
            time.sleep(2)
        with _sim_lock:                         # exit under the lock so sim_start can't miss us leaving
            if not sim_active():
                _sim.update({"phase": "idle", "show": None})
                _sim_thread = None
                return
        play = False


def sim_stop():
    with _ui_lock:
        if (_ui.get("fx") or {}).get("name") == SIMON_NAME:
            _ui.update({"sceneName": None, "panels": {}, "message": None, "fx": None})
            _save_json(UI_FILE, _ui)
    broadcast_state()


def sim_run(play):
    with _state_lock:
        st = _state
    if not st:
        time.sleep(1)
        return
    if not (st.get("state") or {}).get("on", {}).get("value", True):
        sim_stop()                              # panels are off: never switch them on by ourselves
        return
    board = simon.Board(st)
    best = sim_best()

    def status(**kw):
        with _sim_lock:
            _sim["id"] += 1
            for k in ("show", "over"):          # tag new animations so each page plays them once
                if kw.get(k):
                    kw[k] = dict(kw[k], id=_sim["id"])
            _sim.update(kw)
        broadcast_state()

    def send(body):
        if not sim_active():                    # another scene was picked: don't paint over it
            return False
        code, _ = write("/effects", {"write": body})
        if 200 <= code < 300:
            with _state_lock:                   # we know what the device shows now
                if _state:
                    _state["effects"]["select"] = "*Dynamic*"
                    _state["state"]["colorMode"] = "effect"
            return True
        return False

    status(phase="waiting", score=0, best=best, round=0, step=0, newBest=False, show=None, flash=None, over=None,
           board=board.hexes(), zones={str(p): z for p, z in board.zone.items()},
           colours={str(z): "#%02x%02x%02x" % c for z, c in board.colour.items()},
           dirs={str(z): d for z, d in board.direction.items()})
    send(board.idle_body())
    game, over_at = simon.Game(board.order), 0.0
    nxt, action = (time.time() + 1.2, "round") if play else (None, None)

    def new_game():
        nonlocal game, nxt, action
        game = simon.Game(board.order)
        status(phase="ready", score=0, round=0, step=0, newBest=False, show=None, over=None)
        nxt, action = time.time() + 1.2, "round"

    def game_over():
        nonlocal best, over_at, nxt
        new_best = game.score > best
        if new_best:
            best = game.score
            data = _load_json(GAMES_FILE, {})
            data["simon"] = {"best": best, "at": int(time.time())}
            _save_json(GAMES_FILE, data)
        wanted = game.wanted
        body, secs = board.over_body(wanted, new_best)
        status(phase="over", score=game.score, best=best, newBest=new_best,
               over={"wanted": wanted, "newBest": new_best, "seconds": secs})
        send(body)
        over_at, nxt = time.time(), None

    while sim_active():
        with _state_lock:
            on = ((_state or {}).get("state") or {}).get("on", {}).get("value", True)
        if not on:                              # switched off at the wall or in the app: game ends
            sim_stop()
            return
        wait = 1.0 if nxt is None else max(0.02, min(1.0, nxt - time.time()))
        try:
            kind, arg = _sim_q.get(timeout=wait)
        except queue.Empty:
            kind, arg = None, None
        if not sim_active():
            return
        now = time.time()
        if kind == "new":
            new_game()
        elif kind == "resync":
            send(board.idle_body(fade=2))
        elif kind in ("tap", "swipe"):
            z = board.zone_of(arg) if kind == "tap" else board.zone_for(arg)
            if z is None:
                continue
            with _sim_lock:
                phase = _sim["phase"]
            if phase in ("over", "waiting"):
                if now - over_at > 1.5:         # swipe on the wall to play (again)
                    new_game()
                continue
            if phase != "input":
                continue                        # watching: taps don't count yet
            result = game.press(z)
            if result == "fail":
                game_over()
                continue
            with _sim_lock:
                flash = {"zone": z, "id": _sim["id"] + 1}
            if result == "round":
                status(phase="good", score=game.score, step=game.step, flash=flash)
                nxt, action = now + 1.3, "round"
            else:
                status(step=game.step, flash=flash)
                nxt, action = now + simon.INPUT_TIMEOUT, "timeout"
            if _sim_q.empty():                  # if more taps are queued, skip to the newest
                send(board.press_body(z))
        elif nxt is not None and now >= nxt:
            if action == "round":
                seq = game.next_round()
                body, secs = board.show_body(seq)
                hold, gap = simon.speed(len(seq))
                if not send(body):
                    game.seq.pop()
                    nxt = time.time() + 2       # breaker/HTTP error: try the round again shortly
                    continue
                status(phase="show", round=len(seq), step=0,
                       show={"seq": seq, "hold": hold, "gap": gap, "lead": simon.LEAD})
                nxt, action = time.time() + secs + 0.2, "input"
            elif action == "input":
                status(phase="input")
                nxt, action = now + simon.INPUT_TIMEOUT, "timeout"
            elif action == "timeout":
                game.time_out()
                game_over()


# ---------------------------------------------------------------- debug mode
# Swipe down, up, down on the wall (or PUT /api/debug {"action":"enter"}): whatever is playing
# stops and the wall becomes a remote. Left/right step through the favourites (or every scene),
# up switches Favourites/All, down leaves debug mode with the chosen scene playing for real.
# _ui.fx = {name: "debug_mode", list, key} while it's on. Each scene is shown as one custom
# animation with the four button panels lit (remote.preview); one worker writes them, and a
# burst of swipes is summed into a single write.
DEBUG_NAME = "debug_mode"
_dbg = {"list": "favourites", "index": 0, "count": 0, "key": None, "label": "", "icon": "", "panels": {},
        "buttons": {}}
_dbg_lock = threading.Lock()
_dbg_q = queue.Queue()
_dbg_thread = None
_presets = None


def presets():
    """PRESETS/SPEED from the page (read once)."""
    global _presets
    if _presets is None:
        try:
            with open(os.path.join(HERE, "nanoleaf.html"), encoding="utf-8") as f:
                _presets = remote.load_presets(f.read())
        except OSError:
            _presets = ([], {"medium": [14, 28]})
    return _presets


def dbg_active():
    with _ui_lock:
        fx = _ui.get("fx") or {}
    return fx.get("name") == DEBUG_NAME


def dbg_status():
    with _dbg_lock:
        out = dict(_dbg)
    out["active"] = dbg_active()
    if not out["active"]:
        out.update({"panels": {}, "count": 0})
    return out


def dbg_enter():
    """Switch debug mode on (from the swipe pattern or the page)."""
    with _state_lock:
        st = _state
    if not st:
        return False
    with _ui_lock:
        already = (_ui.get("fx") or {}).get("name") == DEBUG_NAME
        if not already:
            start_key = remote.current_key(st, _ui, presets()[0], scenes_list())
            _ui.update({"fx": {"name": DEBUG_NAME, "list": "favourites", "key": start_key}})
            _save_json(UI_FILE, _ui)
    if not (st.get("state") or {}).get("on", {}).get("value", True):
        write("/state", {"on": {"value": True}})    # the user asked for it at the wall
        with _state_lock:
            if _state:
                _state["state"]["on"]["value"] = True
    print("[debug] on", flush=True)
    dbg_start()
    return True


def dbg_start():
    global _dbg_thread
    with _dbg_lock:
        if _dbg_thread is None:
            while not _dbg_q.empty():
                _dbg_q.get_nowait()
            _dbg_thread = threading.Thread(target=dbg_loop, daemon=True)
            _dbg_thread.start()
            return
    _dbg_q.put(("resync", None))


def dbg_loop():
    global _dbg_thread
    while True:
        try:
            dbg_run()
        except Exception as e:
            print(f"[debug] {type(e).__name__}: {e}", flush=True)
            time.sleep(2)
        with _dbg_lock:
            if not dbg_active():
                _dbg["panels"] = {}
                _dbg_thread = None
                return


def dbg_leave(ui=None, why=""):
    """Debug mode off. ui: the _ui of the scene now playing (None = just forget debug mode)."""
    with _ui_lock:
        if (_ui.get("fx") or {}).get("name") == DEBUG_NAME:
            _ui.update(ui or {"sceneName": None, "panels": {}, "message": None, "fx": None})
            _save_json(UI_FILE, _ui)
    print(f"[debug] off{why}", flush=True)
    broadcast_state()


def dbg_run():
    with _state_lock:
        st = _state
    if not st:
        time.sleep(1)
        return
    if not (st.get("state") or {}).get("on", {}).get("value", True):
        dbg_leave(why=" (panels are off)")      # never switch them on by ourselves
        return
    pre, speed = presets()
    try:
        with open(os.path.join(DATA, "palettes.json")) as f:
            palettes = json.load(f)
    except (OSError, ValueError):
        palettes = {}
    with _ui_lock:
        fx = dict(_ui.get("fx") or {})
    which, key = fx.get("list") or "favourites", fx.get("key")

    def items(w):
        return remote.entries(st, pre, scenes_list(), favs_list(), w)

    lst = items(which)
    if not lst and which == "favourites":
        which, lst = "all", items("all")
    keys = [e["key"].lower() for e in lst]
    index = keys.index(key.lower()) if key and key.lower() in keys else 0

    def show():
        if not lst or not dbg_active():
            return
        e = lst[index]
        body, first = remote.preview(e, st, speed, palettes, which)
        with _dbg_lock:
            _dbg.update({"list": which, "index": index, "count": len(lst), "key": e["key"], "label": e["label"],
                         "icon": e["icon"], "panels": first,
                         "buttons": {r: str(p) for r, p in remote.buttons(st).items()}})
        with _ui_lock:
            if (_ui.get("fx") or {}).get("name") == DEBUG_NAME:
                _ui["fx"].update({"list": which, "key": e["key"]})
                _ui["sceneName"] = None
                _save_json(UI_FILE, _ui)
        broadcast_state()
        code, _ = write("/effects", {"write": body})
        if 200 <= code < 300:
            with _state_lock:
                if _state:
                    _state["effects"]["select"] = "*Dynamic*"
                    _state["state"]["colorMode"] = "effect"

    show()
    while dbg_active():
        with _state_lock:
            on = ((_state or {}).get("state") or {}).get("on", {}).get("value", True)
        if not on:
            dbg_leave(why=" (panels switched off)")
            return
        try:
            kind, arg = _dbg_q.get(timeout=1.0)
        except queue.Empty:
            continue
        step, toggles, leave, resync = 0, 0, False, False
        while True:                             # sum up everything that queued while we were writing
            if kind == "step":
                step += arg
            elif kind == "toggle":
                toggles += 1
            elif kind == "exit":
                leave = True
            elif kind == "resync":
                resync = True
            try:
                kind, arg = _dbg_q.get_nowait()
            except queue.Empty:
                break
        if not dbg_active():
            return
        if toggles % 2:
            cur = lst[index]["key"].lower() if lst else None
            which = "all" if which == "favourites" else "favourites"
            lst = items(which)
            if not lst:                         # no favourites yet: stay on All
                which, lst = "all", items("all")
            keys = [e["key"].lower() for e in lst]
            index = keys.index(cur) if cur in keys else 0
            print(f"[debug] list: {which}", flush=True)
        if step and lst:
            index = (index + step) % len(lst)
        if leave:
            if lst:
                path, body, ui = remote.play(lst[index], st, speed)
                code, _ = write(path, body)
                if not (200 <= code < 300):         # the controller is sometimes slow to answer: once more
                    time.sleep(1.5)
                    code, _ = write(path, body)
                if not (200 <= code < 300):
                    # Still nothing: stay in debug mode (its panels stay lit) so it's plain on
                    # the wall that it didn't take; swiping down again tries again.
                    print(f"[debug] couldn't play {lst[index]['key']} (HTTP {code}); still in debug mode", flush=True)
                    continue
                dbg_leave(ui, f", playing {lst[index]['key']} (HTTP {code})")
                schedule_refresh(0.5)
            else:
                dbg_leave()
            return
        if step or toggles % 2 or resync:
            show()


# ---------------------------------------------------------------- reconnect
# Phases: idle, checking, searching, not_found, needs_pairing, pairing, connected.
_rc = {"phase": "idle", "detail": "", "ip": None, "until": 0, "at": 0}
_rc_lock = threading.Lock()
_rc_thread = None
_auto_rc_last = 0.0
AUTO_RC_EVERY = 60.0        # while offline, look for the panels this often by itself
PAIR_WINDOW = float(os.environ.get("NANOLEAF_PAIR_WINDOW", "90"))   # seconds to wait for the button


def rc_set(phase, detail="", ip=None, until=0):
    with _rc_lock:
        _rc.update({"phase": phase, "detail": detail, "ip": ip, "until": until, "at": time.time()})
    print(f"[reconnect] {phase} {detail}", flush=True)
    broadcast_state()


def local_ip():
    """This Mac's address on the network the panels should be on."""
    for target in (cfg()["ip"], "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 9))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except OSError:
            continue
    return None


def scan_subnet(my_ip, timeout=0.7):
    """Every host on my_ip's /24 that answers on the Nanoleaf API port."""
    prefix = my_ip.rsplit(".", 1)[0]
    def probe(host):
        try:
            with socket.create_connection((host, NANO_PORT), timeout=timeout):
                return host
        except OSError:
            return None
    with ThreadPoolExecutor(max_workers=64) as ex:
        hits = list(ex.map(probe, [f"{prefix}.{i}" for i in range(1, 255)]))
    return [h for h in hits if h]


def probe_device(ip, token, timeout=4):
    """HTTP status of GET /api/v1/<token>/ on ip (0 = no answer), plus the name."""
    try:
        req = urllib.request.Request(base(ip, token) + "/")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                name = json.loads(r.read().decode()).get("name", "")
            except Exception:
                name = ""
            return r.status, name
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def try_pair(ip, timeout=4):
    """POST /api/v1/new -> token, or None (403 = the panels aren't in pairing mode)."""
    try:
        req = urllib.request.Request(f"http://{ip}:{NANO_PORT}/api/v1/new", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("auth_token")
    except Exception:
        return None


def reconnect_job(pair=False):
    """Find the panels again, even at a new address; re-pair if asked to.

    1. Try the last known address with the saved token.
    2. If nothing answers there, scan the local /24 for anything on port 16021.
    3. Anything that accepts the token wins: remember it, done.
    4. If it answers but refuses the token, we need a new one: report needs_pairing,
       or (pair=True, after the user held the power button) poll /new for a while.
    """
    global _reachable
    c = cfg()
    rc_set("checking", f"Trying the panels at {c['ip']}…", ip=c["ip"])
    status, _ = probe_device(c["ip"], c["token"])
    candidates = [c["ip"]]
    if status == 200:
        _reachable = True
        rc_set("connected", f"The panels are back at {c['ip']}.", ip=c["ip"])
        refresh_state()
        return
    if status == 0:
        me = local_ip()
        rc_set("searching", f"Looking for the panels on your network ({me or '?'})…")
        found = scan_subnet(me) if me else []
        if not found:
            rc_set("not_found", "Nothing on your network is answering like the panels. "
                                "Check they have power and are on the same Wi-Fi.")
            return
        candidates = found
    refused = []
    for ip in candidates:
        st, name = probe_device(ip, c["token"])
        if st == 200:
            set_cfg(ip=ip)
            _reachable = True
            rc_set("connected", f"Found the panels at {ip}" + (f" ({name})" if name else "") + ".", ip=ip)
            refresh_state()
            return
        if st in (401, 403):
            refused.append(ip)
    if not refused:
        rc_set("not_found", "Something answered on the panels' port but it wasn't them. "
                            "Check the panels have power and are on this Wi-Fi.")
        return
    ip = refused[0]
    if not pair:
        rc_set("needs_pairing", (f"Found Nanoleaf panels at {ip}. They need to be paired with this app." if not c["token"]
                                 else f"The panels at {ip} no longer accept this app's pairing."), ip=ip)
        return
    until = time.time() + PAIR_WINDOW
    rc_set("pairing", f"Waiting for the panels at {ip} to accept the pairing…", ip=ip, until=until)
    while time.time() < until:
        tok = try_pair(ip)
        if tok:
            set_cfg(ip=ip, token=tok)
            _reachable = True
            rc_set("connected", f"Paired again with the panels at {ip}.", ip=ip)
            refresh_state()
            return
        time.sleep(2)
    rc_set("needs_pairing", "The panels didn't open for pairing in time.", ip=ip)


def start_reconnect(pair=False):
    """Run reconnect_job in the background unless one is already running."""
    global _rc_thread
    with _rc_lock:
        if _rc_thread and _rc_thread.is_alive():
            return False
        _rc_thread = threading.Thread(target=reconnect_job, kwargs={"pair": pair}, daemon=True)
        _rc_thread.start()
        return True


def auto_reconnect():
    """While offline, go looking by ourselves now and then (never pairs: that needs the button)."""
    global _auto_rc_last
    now = time.time()
    with _rc_lock:
        busy = _rc_thread and _rc_thread.is_alive()
        phase = _rc["phase"]
    if busy or phase in ("needs_pairing", "pairing") or now - _auto_rc_last < AUTO_RC_EVERY:
        return
    _auto_rc_last = now
    start_reconnect(pair=False)


def load_palettes():
    """Scene palettes, cached to palettes.json (building it hits the device 16 times)."""
    path = os.path.join(DATA, "palettes.json")
    for candidate in (path, os.path.join(HERE, "palettes.json")):
        try:
            with open(candidate) as f:
                return f.read()
        except FileNotFoundError:
            pass
    code, body = read("/")
    res = {}
    try:
        names = json.loads(body)["effects"]["effectsList"]
    except Exception:
        return json.dumps(res)
    for n in names:
        c, b = write("/effects", {"write": {"command": "request", "animName": n}})
        try:
            d = json.loads(b)
            res[n] = {
                "animType": d.get("animType", ""),
                "palette": [{"h": x.get("hue", 0), "s": x.get("saturation", 0),
                             "b": x.get("brightness", 100)} for x in d.get("palette", [])],
            }
        except Exception:
            res[n] = {"animType": "", "palette": []}
    out = json.dumps(res)
    try:
        with open(path, "w") as f:
            f.write(out)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- saved scenes
_scenes_lock = threading.Lock()


def scenes_list():
    with _scenes_lock:
        return _load_json(SCENES_FILE, [])


def scenes_upsert(scene):
    name = str(scene.get("name", "")).strip()[:40]
    if not name:
        return None
    scene["name"] = name
    with _scenes_lock:
        items = [s for s in _load_json(SCENES_FILE, [])
                 if s.get("name", "").lower() != name.lower()]
        items.append(scene)
        _save_json(SCENES_FILE, items)
        return items


def scenes_delete(name):
    with _scenes_lock:
        items = [s for s in _load_json(SCENES_FILE, [])
                 if s.get("name", "").lower() != name.lower()]
        _save_json(SCENES_FILE, items)
        return items


# ---------------------------------------------------------------- favourites
# Scenes the user hearted, as "kind:name" keys in the order they were added:
# device:<scene saved on the panels>, fx:<effect name>, mood:<page preset>, mine:<saved scene>.
FAVS_FILE = os.path.join(DATA, "favorites.json")
FAV_KINDS = ("device", "fx", "mood", "mine")
REP_CARD = {"name": "replicate", "label": "Replicate", "icon": "🖥️", "live": True,
            "desc": "The wall copies the mood of your Mac's screen, area by area. Needs the NanoManager Mac app open.",
            "colors": ["#ff7a59", "#7c5cff", "#00d4ff", "#ffd166"]}
_favs_lock = threading.Lock()


def _load_favs():
    d = _load_json(FAVS_FILE, [])
    return [k for k in d if isinstance(k, str)] if isinstance(d, list) else []


_favs = _load_favs()


def favs_list():
    with _favs_lock:
        return list(_favs)


def favs_set(key, on):
    """Add or remove one favourite (names compare case-insensitively, like saved scenes).
    Returns the new list, or None if the key isn't kind:name."""
    key = str(key or "").strip()[:120]
    kind, _, name = key.partition(":")
    if kind not in FAV_KINDS or not name:
        return None
    with _favs_lock:
        idx = next((i for i, k in enumerate(_favs) if k.lower() == key.lower()), None)
        if on and idx is None:
            _favs.append(key)
        elif not on and idx is not None:
            del _favs[idx]
        else:
            return list(_favs)
        _save_json(FAVS_FILE, _favs)
        out = list(_favs)
    broadcast_state()           # every open window updates its hearts
    return out


def favs_reorder(order):
    """Put the favourites in a new order (a drag on the page). The keys must be exactly the
    current ones, in any order and case; returns the new list or None."""
    if not isinstance(order, list):
        return None
    with _favs_lock:
        cur = {k.lower(): k for k in _favs}
        new = [cur.get(str(k).lower()) for k in order]
        if None in new or len(set(k.lower() for k in new)) != len(_favs) or len(new) != len(_favs):
            return None
        _favs[:] = new
        _save_json(FAVS_FILE, _favs)
        out = list(_favs)
    broadcast_state()
    return out


# ---------------------------------------------------------------- settings
# settings.json (data dir): fade (tenths, the crossfade of still scenes), lat/lon (for sunrise/
# sunset schedules), runToken (the secret in /run/<token> links), pin (salted hash; phones
# need it, this computer never does), sessions (signed-in phones), restoreBright (after the
# sleep timer), salt.
SETTINGS_FILE = os.path.join(DATA, "settings.json")
_set_lock = threading.Lock()
_settings = _load_json(SETTINGS_FILE, {})
if not isinstance(_settings, dict):
    _settings = {}
if not _settings.get("runToken"):
    _settings["runToken"] = secrets.token_urlsafe(9)
    _save_json(SETTINGS_FILE, _settings)
DEFAULT_FADE = 8


def setting(key, default=None):
    with _set_lock:
        return _settings.get(key, default)


def set_settings(**kw):
    with _set_lock:
        for k, v in kw.items():
            if v is None:
                _settings.pop(k, None)
            else:
                _settings[k] = v
        _save_json(SETTINGS_FILE, _settings)


def fade():
    try:
        return max(1, min(600, int(setting("fade", DEFAULT_FADE))))
    except (TypeError, ValueError):
        return DEFAULT_FADE


def location():
    lat, lon = setting("lat"), setting("lon")
    return (lat, lon) if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else (None, None)


def settings_public():
    lat, lon = location()
    return {"fade": fade(), "lat": lat, "lon": lon, "pin": bool(setting("pin"))}


# ---------------------------------------------------------------- PIN lock
# Off by default. With a PIN set, every request that doesn't come from this computer needs a
# session cookie (got by typing the PIN on the phone) — except the Home Screen icons and the
# /run/<token> links, which carry their own secret. Five wrong PINs from one address = a minute's wait.
PIN_COOKIE = "nm_session"
_pin_fails = {}
_pin_lock = threading.Lock()


def _pin_hash(pin):
    salt = setting("salt")
    if not salt:
        salt = secrets.token_hex(8)
        set_settings(salt=salt)
    return hashlib.sha256((salt + ":" + str(pin)).encode()).hexdigest()


def pin_check(ip, pin):
    """(ok, wait seconds)."""
    now = time.time()
    with _pin_lock:
        n, until = _pin_fails.get(ip, (0, 0))
        if now < until:
            return False, int(until - now) + 1
    ok = bool(setting("pin")) and hmac.compare_digest(_pin_hash(pin), setting("pin"))
    with _pin_lock:
        if ok:
            _pin_fails.pop(ip, None)
            return True, 0
        n += 1
        _pin_fails[ip] = (0, now + 60) if n >= 5 else (n, 0)
        return False, 60 if n >= 5 else 0


def pin_session_new():
    tok = secrets.token_urlsafe(24)
    with _set_lock:
        s = [t for t in _settings.get("sessions") or [] if isinstance(t, str)][-29:]
        s.append(tok)
        _settings["sessions"] = s
        _save_json(SETTINGS_FILE, _settings)
    return tok


def pin_session_ok(tok):
    return bool(tok) and any(hmac.compare_digest(tok, t) for t in setting("sessions") or [])


PIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="NanoManager">
<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="manifest" href="/manifest.webmanifest">
<title>NanoManager</title><style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0c11;color:#eef1f7;
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
form{width:min(320px,calc(100vw - 32px));text-align:center}h1{font-size:20px;margin:0 0 6px}p{color:#8e97ab;margin:0 0 18px;font-size:14px}
input{width:100%;box-sizing:border-box;font-size:28px;letter-spacing:10px;text-align:center;padding:12px;border-radius:14px;
border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.05);color:inherit;outline:none}
input:focus{border-color:#7c5cff}button{margin-top:14px;width:100%;padding:13px;border:0;border-radius:14px;font:inherit;font-weight:650;
background:linear-gradient(135deg,#7c5cff,#00d4ff);color:#fff}#e{color:#ff5d6c;min-height:24px;margin-top:10px;font-size:14px}
</style></head><body><form id="f"><h1>🔒 NanoManager</h1><p>Type the PIN set on the computer that runs NanoManager.</p>
<input id="p" type="password" inputmode="numeric" autocomplete="one-time-code" maxlength="12" autofocus aria-label="PIN">
<button>Unlock</button><div id="e" role="alert"></div></form><script>
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const p=document.getElementById("p"),m=document.getElementById("e");
const r=await fetch("/api/pin",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({pin:p.value})}).catch(()=>null);
if(r&&r.ok){location.replace("/"+location.hash);return;}const d=r?await r.json().catch(()=>({})):{};
m.textContent=d.wait?"Too many tries. Wait "+d.wait+" s.":"That's not it.";p.value="";p.focus();};
</script></body></html>"""


# ---------------------------------------------------------------- playing by key
# The /run links, the schedule and the slideshow play scenes the same way the page does
# (remote.play), by key: device:<name>, fx:<effect>, mood:<name>, mine:<name>, or just a name.
def _cur_state():
    with _state_lock:
        st = _state
    if st:
        return st
    code, body = read("/")
    if code != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def find_entry(st, key):
    """The scene entry for a key or a plain name (case-insensitive), or None."""
    key = str(key or "").strip()
    if key.lower() in ("auto:season", "season", "seasonal"):
        key = "mood:" + routines.season_mood(datetime.date.today())
    pre, _ = presets()
    lst = remote.entries(st, pre, scenes_list(), favs_list(), "all")
    k = key.lower()
    for e in lst:
        if e["key"].lower() == k:
            return e
    for e in lst:
        if e["label"].lower() == k or e["name"].lower() == k:
            return e
    return None


def _on_body(extra=None):
    """Switch on, restoring the brightness the sleep timer turned down."""
    body = {"on": {"value": True}}
    rb = setting("restoreBright")
    if rb:
        body["brightness"] = {"value": int(rb)}
        set_settings(restoreBright=None)
    body.update(extra or {})
    return body


def play_entry(e, st, who="run"):
    """Write entry e to the panels (switching them on first). Returns the HTTP code."""
    _, speed = presets()
    path, body, ui = remote.play(e, st, speed, fade=fade())
    if not (st.get("state") or {}).get("on", {}).get("value", True):
        write("/state", _on_body())
    code, _ = write(path, body)
    if 200 <= code < 300:
        sc = e.get("scene") or {}
        if e["kind"] == "mood" and sc.get("bright"):
            write("/state", {"brightness": {"value": int(sc["bright"])}})
        with _ui_lock:
            _ui.update(ui)
            _save_json(UI_FILE, _ui)
        print(f"[{who}] playing {e['key']} (HTTP {code})", flush=True)
        schedule_refresh(0.5)
        broadcast_state()
    return code


def step_favourite(st, step):
    """The favourite before/after the one playing (wraps round; all scenes if no favourites)."""
    pre, _ = presets()
    lst = remote.entries(st, pre, scenes_list(), favs_list(), "favourites") or \
        remote.entries(st, pre, scenes_list(), favs_list(), "all")
    if not lst:
        return None
    with _ui_lock:
        ui = dict(_ui)
    cur = (remote.current_key(st, ui, pre, scenes_list()) or "").lower()
    keys = [e["key"].lower() for e in lst]
    i = keys.index(cur) if cur in keys else (-1 if step > 0 else 0)
    return lst[(i + step) % len(lst)]


# ---------------------------------------------------------------- routines
# One at a time: sunrise alarm, sleep timer, pomodoro, slideshow (see routines.py). A worker
# thread owns it; starting another, or stopping, bumps _rt_gen so the old one ends at its next
# check. The page's own writes stop the ones they'd fight with (rt_user_action).
_rt = {"kind": None}
_rt_lock = threading.Lock()
_rt_gen = 0
_rt_wake = threading.Event()


def rt_status():
    with _rt_lock:
        out = dict(_rt)
    out["active"] = bool(out.get("kind"))
    out["now"] = time.time()
    return out


def rt_start(kind, opts=None):
    """Start a routine (replacing any other). Returns (ok, error)."""
    global _rt_gen
    if kind not in routines.ROUTINES:
        return False, "unknown routine"
    opts = dict(opts or {})
    st = _cur_state()
    if not st:
        return False, "Panels unreachable"
    try:
        mins = float(opts.get("minutes") or {"sunrise": 30, "sleep": 30, "pomodoro": 25, "slideshow": 10}[kind])
    except (TypeError, ValueError):
        return False, "minutes must be a number"
    opts["minutes"] = max(0.1, min(240.0, mins))
    with _rt_lock:
        _rt_gen += 1
        gen = _rt_gen
        _rt.clear()
        _rt.update({"kind": kind, "started": time.time(), "minutes": opts["minutes"], "phase": "", "label": ""})
    _rt_wake.set()
    threading.Thread(target=rt_loop, args=(kind, opts, gen), daemon=True).start()
    print(f"[routine] {kind} started ({opts['minutes']:g} min)", flush=True)
    broadcast_state()
    return True, ""


def rt_stop(why=""):
    global _rt_gen
    with _rt_lock:
        was = _rt.get("kind")
        _rt_gen += 1
        _rt.clear()
        _rt["kind"] = None
    _rt_wake.set()
    with _ui_lock:
        if (_ui.get("fx") or {}).get("name") == "pomodoro":
            _ui["fx"] = None
            _save_json(UI_FILE, _ui)
    if was:
        print(f"[routine] {was} stopped{(' (' + why + ')') if why else ''}", flush=True)
        broadcast_state()


def rt_user_action(what):
    """Something else is taking over the panels. what: 'off' | 'bright' | 'scene'."""
    kind = rt_status().get("kind")
    if not kind:
        return
    if what == "off" or (what == "bright" and kind in ("sunrise", "sleep")) or \
            (what == "scene" and kind in ("sunrise", "pomodoro", "slideshow")):
        rt_stop("you changed the panels")


def _rt_alive(gen):
    with _rt_lock:
        return gen == _rt_gen


def _rt_sleep(gen, seconds):
    """Wait, waking early if the routine is replaced. False = stop now."""
    end = time.time() + seconds
    while _rt_alive(gen):
        left = end - time.time()
        if left <= 0:
            return True
        _rt_wake.wait(min(left, 1.0))
        _rt_wake.clear()
    return False


def _rt_set(gen, **kw):
    with _rt_lock:
        if gen == _rt_gen:
            _rt.update(kw)
    broadcast_state()


def _is_on():
    with _state_lock:
        return ((_state or {}).get("state") or {}).get("on", {}).get("value", True)


def _patch_state(on=None, brightness=None):
    """Note what a routine just wrote in the cached state, so its next check doesn't mistake
    the old values for someone else's change before the device's event re-read arrives."""
    with _state_lock:
        s = (_state or {}).get("state")
        if not s:
            return
        if on is not None:
            s.setdefault("on", {})["value"] = on
        if brightness is not None:
            s.setdefault("brightness", {})["value"] = brightness


def rt_loop(kind, opts, gen):
    try:
        {"sunrise": rt_sunrise, "sleep": rt_sleep, "pomodoro": rt_pomodoro, "slideshow": rt_slideshow}[kind](opts, gen)
    except Exception as e:
        print(f"[routine] {kind}: {type(e).__name__}: {e}", flush=True)
    if _rt_alive(gen):
        rt_stop("finished")


def rt_sunrise(opts, gen):
    secs = opts["minutes"] * 60
    steps = int(max(6, min(60, secs // 30)))          # about one write every 30 s
    dt = secs / steps
    t0 = time.time()
    _rt_set(gen, label="Sunrise alarm", phase="rising", ends=t0 + secs)
    with _ui_lock:
        _ui.update({"sceneName": None, "panels": {}, "message": None, "fx": None})
        _save_json(UI_FILE, _ui)
    write("/state", dict(routines.sunrise_point(0), on={"value": True}))
    _patch_state(on=True, brightness=1)
    schedule_refresh(0.5)
    for k in range(1, steps + 1):
        if not _rt_sleep(gen, max(0, t0 + (k - 1) * dt + 1 - time.time())):
            return
        if k > 1 and not _is_on():
            rt_stop("panels switched off")
            return
        body = routines.sunrise_point(k / steps)
        body["brightness"]["duration"] = int(max(1, dt - 1))    # the device fades it smoothly
        write("/state", body)
        schedule_refresh(0.5)
        _rt_set(gen, progress=round(k / steps, 3))
    _rt_sleep(gen, dt)


def rt_sleep(opts, gen):
    secs = opts["minutes"] * 60
    st = _cur_state() or {}
    b0 = int(((st.get("state") or {}).get("brightness") or {}).get("value", 50))
    if not _is_on():
        rt_stop("panels are already off")
        return
    steps = int(max(4, min(60, secs // 30)))
    dt = secs / steps
    t0 = time.time()
    _rt_set(gen, label="Sleep timer", phase="fading", ends=t0 + secs, from_=b0)
    last = b0
    for k in range(1, steps + 1):
        if not _is_on():
            rt_stop("panels switched off")
            return
        with _state_lock:
            now_b = ((_state or {}).get("state") or {}).get("brightness", {}).get("value", last)
        if now_b > last + 10:                         # someone turned it up: they're not asleep
            rt_stop("brightness turned up")
            return
        b = max(1, int(round(b0 * (1 - k / steps))))
        write("/state", {"brightness": {"value": b, "duration": int(max(1, dt - 1))}})
        _patch_state(brightness=b)
        last = b
        _rt_set(gen, progress=round(k / steps, 3))
        if not _rt_sleep(gen, max(0, t0 + k * dt - time.time())):
            return
    write("/state", {"on": {"value": False}})
    _patch_state(on=False)
    set_settings(restoreBright=b0)                    # back to normal next time they're switched on
    schedule_refresh(0.5)


def rt_pomodoro(opts, gen):
    st = _cur_state()
    work = opts["minutes"] * 60
    try:
        brk = max(0.1, min(60.0, float(opts.get("break") or 5))) * 60
    except (TypeError, ValueError):
        brk = 300
    shapes = effects.light_shapes(st)
    pos = {p["panelId"]: effects.centre(pts) for p, pts in shapes}
    order = routines.drain_order(pos)
    rnd = 0
    if not _is_on():
        write("/state", {"on": {"value": True}})
    while _rt_alive(gen):
        rnd += 1
        for phase, length in (("work", work), ("break", brk)):
            t0 = time.time()
            _rt_set(gen, label="Pomodoro", phase=phase, round=rnd, ends=t0 + length, phaseLength=length)
            full = routines.pomodoro_map(order, 1.0, phase)
            chime = routines.chime(full, routines.WORK_C if phase == "work" else routines.BREAK_C)
            body = effects.body_from(chime)
            body["loop"] = False
            write("/effects", {"write": body})
            shown = None
            while True:
                left = 1 - (time.time() - t0) / length
                if left <= 0:
                    break
                cmap = routines.pomodoro_map(order, left, phase)
                if cmap != shown and (shown is not None or time.time() - t0 > 3):
                    hexes = {str(k): remote.hexs(v) for k, v in cmap.items()}
                    with _ui_lock:
                        _ui.update({"sceneName": "Pomodoro", "panels": hexes, "message": None,
                                    "fx": {"name": "pomodoro"}})
                    write("/effects", {"write": remote.static_body(st, cmap, fade=10)})
                    shown = cmap
                    broadcast_state()
                if not _rt_sleep(gen, min(2.0, left * length)):
                    return
                if not _is_on():
                    rt_stop("panels switched off")
                    return


def rt_slideshow(opts, gen):
    every = opts["minutes"] * 60
    which = "moods" if opts.get("list") == "moods" else "favourites"
    k = 0
    while _rt_alive(gen):
        st = _cur_state()
        pre, _ = presets()
        lst = remote.entries(st, pre, scenes_list(), favs_list(), "favourites") if which == "favourites" else []
        if not lst:
            lst = [e for e in remote.entries(st, pre, scenes_list(), favs_list(), "all") if e["kind"] == "mood"]
        if not lst:
            rt_stop("nothing to show")
            return
        e = lst[k % len(lst)]
        k += 1
        _rt_set(gen, label="Slideshow", phase=e["label"], ends=time.time() + every, list=which, index=k, count=len(lst))
        old = fade()
        _, speed = presets()
        path, body, ui = remote.play(e, st, speed, fade=max(old, int(opts.get("fade") or 50)))
        if not (st.get("state") or {}).get("on", {}).get("value", True):
            if k > 1:
                rt_stop("panels switched off")
                return
            write("/state", _on_body())
        write(path, body)
        with _ui_lock:
            _ui.update(ui)
            _save_json(UI_FILE, _ui)
        schedule_refresh(0.5)
        played = e["key"].lower()
        end = time.time() + every
        while time.time() < end:
            if not _rt_sleep(gen, min(5.0, end - time.time())):
                return
            with _state_lock:
                st2 = _state
            with _ui_lock:
                ui2 = dict(_ui)
            cur = remote.current_key(st2 or {}, ui2, pre, scenes_list()) if st2 else None
            if st2 and time.time() - _state_ts < 10 and cur and cur.lower() != played:
                rt_stop("another scene was picked")
                return


# ---------------------------------------------------------------- schedule
# schedules.json (data dir): a list of routines.clean_entry() dicts plus "last" (the fire time
# it last fired for). sched_loop checks every 15 s.
SCHED_FILE = os.path.join(DATA, "schedules.json")
_sched_lock = threading.Lock()


def sched_list():
    with _sched_lock:
        d = _load_json(SCHED_FILE, [])
    return d if isinstance(d, list) else []


def sched_view():
    lat, lon = location()
    now = datetime.datetime.now()
    out = []
    for e in sched_list():
        nf = routines.next_fire(e, now, lat, lon)
        out.append(dict(e, desc=routines.describe(e), next=nf.isoformat() if nf else None))
    today = datetime.date.today()
    rise, set_ = routines.sun_times(today, lat, lon) if lat is not None else (None, None)
    return {"items": out, "lat": lat, "lon": lon,
            "sunrise": rise.strftime("%H:%M") if rise else None, "sunset": set_.strftime("%H:%M") if set_ else None}


def sched_upsert(item):
    e = routines.clean_entry(item)
    if not e:
        return None
    with _sched_lock:
        items = _load_json(SCHED_FILE, [])
        items = items if isinstance(items, list) else []
        if not e["id"]:
            e["id"] = secrets.token_hex(4)
        old = next((x for x in items if x.get("id") == e["id"]), None)
        if old and old.get("last"):
            e["last"] = old["last"]
        items = [x for x in items if x.get("id") != e["id"]] + [e] if not old else \
            [e if x.get("id") == e["id"] else x for x in items]
        if len(items) > 50:
            return None
        _save_json(SCHED_FILE, items)
    return sched_view()


def sched_delete(sid):
    with _sched_lock:
        items = [x for x in _load_json(SCHED_FILE, []) if x.get("id") != sid]
        _save_json(SCHED_FILE, items)
    return sched_view()


def sched_fire(e):
    a = e["action"]
    st = _cur_state()
    if not st:
        print(f"[schedule] {routines.describe(e)}: panels unreachable", flush=True)
        return
    print(f"[schedule] {routines.describe(e)} -> {a}", flush=True)
    if a.get("power") == "off":
        rt_user_action("off")
        write("/state", {"on": {"value": False}})
    elif a.get("power") == "on":
        write("/state", _on_body())
    elif a.get("routine"):
        rt_start(a["routine"], {"minutes": a.get("minutes")})
    elif a.get("key"):
        ent = find_entry(st, a["key"])
        if ent:
            rt_user_action("scene")
            play_entry(ent, st, who="schedule")
        else:
            print(f"[schedule] no scene called {a['key']!r}", flush=True)
    schedule_refresh(0.5)


def sched_loop():
    while True:
        try:
            lat, lon = location()
            now = datetime.datetime.now()
            for e in sched_list():
                t = routines.due(e, now, e.get("last"), lat, lon)
                if t is None:
                    continue
                with _sched_lock:                       # mark first, so a crash can't repeat it
                    items = _load_json(SCHED_FILE, [])
                    for x in items:
                        if x.get("id") == e.get("id"):
                            x["last"] = t.isoformat()
                    _save_json(SCHED_FILE, items)
                sched_fire(e)
        except Exception as ex:
            print(f"[schedule] {type(ex).__name__}: {ex}", flush=True)
        time.sleep(15)


# ---------------------------------------------------------------- /run links
# GET /run/<token>?key=mood:Cozy  (or scene=<name>, power=on|off|toggle, bright=40, next=1,
# prev=1, routine=sleep&minutes=20, stop=1). For Shortcuts / Siri, NFC tags, Home Screen
# bookmarks. The token keeps other web pages from switching the lights through your browser.
def run_action(q):
    """q: {param: value}. Returns (http code, message)."""
    st = _cur_state()
    if not st:
        return 502, "The panels aren't answering."
    on = (st.get("state") or {}).get("on", {}).get("value", True)
    if q.get("stop"):
        rt_stop("stopped from a link")
        return 200, "Stopped."
    if q.get("routine"):
        ok, err = rt_start(q["routine"], {"minutes": q.get("minutes"), "break": q.get("break"), "list": q.get("list")})
        return (200, f"{q['routine'].capitalize()} started.") if ok else (400, err)
    if q.get("power"):
        p = q["power"].lower()
        if p == "toggle":                             # a fresh look: two taps can come close together
            code, body = read("/")
            if code == 200:
                on = (json.loads(body).get("state") or {}).get("on", {}).get("value", on)
        want = (not on) if p == "toggle" else p == "on"
        if not want:
            rt_user_action("off")
        code, _ = write("/state", _on_body() if want else {"on": {"value": False}})
        if code < 300:
            _patch_state(on=want)
        schedule_refresh(0.5)
        return (code if code >= 300 else 200), ("Panels on." if want else "Panels off.")
    if q.get("bright"):
        try:
            b = max(1, min(100, int(q["bright"])))
        except ValueError:
            return 400, "bright must be 1-100"
        rt_user_action("bright")
        code, _ = write("/state", {"brightness": {"value": b}})
        schedule_refresh(0.5)
        return (code if code >= 300 else 200), f"Brightness {b}%."
    if q.get("next") or q.get("prev"):
        e = step_favourite(st, 1 if q.get("next") else -1)
    else:
        e = find_entry(st, q.get("key") or q.get("scene") or "")
    if not e:
        return 404, "No scene called that."
    rt_user_action("scene")
    code = play_entry(e, st)
    return (200 if 200 <= code < 300 else code), (f"{e['icon']} {e['label']}" if 200 <= code < 300 else "The panels didn't take it.")


RUN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NanoManager</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0c11;color:#eef1f7;
font:20px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;text-align:center}p{color:#8e97ab;font-size:14px}</style></head>
<body><div><div style="font-size:44px">%s</div><div>%s</div><p><a href="/" style="color:#8e97ab">Open NanoManager</a></p></div></body></html>"""


# ------------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 200_000:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return None

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _authed(self):
        return not setting("pin") or self._local() or pin_session_ok(self._cookie(PIN_COOKIE))

    OPEN_PATHS = ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/manifest.webmanifest",
                  "/favicon.ico", "/api/pin")

    def _gate(self, path):
        """True if the request may go on; otherwise answers it (PIN page / 401)."""
        if self._authed() or path in self.OPEN_PATHS or path.startswith("/mobile/") or path.startswith("/run/"):
            return True
        if self.command == "GET" and path in ("/", "/index.html"):
            self._send(200, PIN_PAGE, "text/html; charset=utf-8")
        else:
            self._send(401, json.dumps({"error": "pin", "detail": "Locked: type the PIN first."}))
        return False

    def _run(self, path, query):
        tok = path[len("/run/"):].strip("/")
        if not tok or not hmac.compare_digest(tok, setting("runToken") or ""):
            self._send(403, RUN_PAGE % ("🔒", "That link isn't valid any more. Copy a new one from NanoManager."),
                       "text/html; charset=utf-8")
            return
        q = {k: v[-1] for k, v in parse_qs(query).items()}
        code, msg = run_action(q)
        if q.get("format") == "json" or "application/json" in (self.headers.get("Accept") or ""):
            self._send(code, json.dumps({"ok": code == 200, "message": msg}))
        else:
            self._send(code, RUN_PAGE % ("✓" if code == 200 else "⚠", msg.replace("<", "&lt;")), "text/html; charset=utf-8")

    def _events(self):
        q = queue.Queue(maxsize=50)
        with _clients_lock:
            _clients.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(("data: " + json.dumps(snapshot()) + "\n\n").encode())
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(("data: " + data + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if not self._gate(path):
            return
        if path.startswith("/run/"):
            self._run(path, u.query)
        elif path == "/api/settings":
            self._send(200, json.dumps(dict(settings_public(), local=self._local(), runToken=setting("runToken"),
                                            phoneUrl=phone_url())))
        elif path == "/api/schedule":
            self._send(200, json.dumps(sched_view()))
        elif path == "/api/routine":
            self._send(200, json.dumps(rt_status()))
        elif path == "/api/qr.svg":
            text = (parse_qs(u.query).get("text") or [""])[0][:300]
            try:
                self._send(200, qr.svg(text), "image/svg+xml")
            except ValueError as e:
                self._send(400, json.dumps({"error": str(e)}))
        elif path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "nanoleaf.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "page missing", "text/plain")
        elif path == "/api/state":
            if time.time() - _state_ts > 3:
                refresh_state()
            self._send(200, json.dumps(snapshot()))
        elif path == "/api/events":
            self._events()
        elif path == "/api/palettes":
            self._send(200, load_palettes())
        elif path == "/api/scenes":
            self._send(200, json.dumps(scenes_list()))
        elif path == "/api/favorites":
            self._send(200, json.dumps(favs_list()))
        elif path == "/api/effects":
            with _state_lock:
                st = _state
            cat = effects.catalogue(st)
            first_game = next((i for i, e in enumerate(cat) if e.get("group") == "game"), len(cat))
            self._send(200, json.dumps(cat[:first_game] + [SIMON_CARD] + cat[first_game:] + [REP_CARD]))
        elif path == "/api/replicate":
            self._send(200, json.dumps({**rep_status(), "w": REP_GRID[0], "h": REP_GRID[1], "every": REP_GAP}))
        elif path == "/api/glyphs":
            try:
                with open(os.path.join(HERE, "glyphs.json"), "rb") as f:
                    self._send(200, f.read())
            except OSError:
                self._send(404, json.dumps({"error": "glyphs.json missing"}))
        elif path == "/api/health":
            now = time.time()
            code, body = read("/")
            self._send(200, json.dumps({
                "online": code == 200,
                "paused": now < _breaker_until,
                "pausedFor": max(0, int(_breaker_until - now)),
                "lastError": _last_error,
            }))
        elif path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/manifest.webmanifest") \
                or path.startswith("/mobile/"):
            name = os.path.basename(path)
            if path.startswith("/apple-touch-icon"):
                name = "apple-touch-icon.png"
            ext = os.path.splitext(name)[1]
            try:
                with open(os.path.join(MOBILE_DIR, name), "rb") as f:
                    self._send(200, f.read(), MOBILE_TYPES.get(ext, "application/octet-stream"))
            except OSError:
                self._send(404, json.dumps({"error": "not found"}))
        elif path == "/favicon.ico":
            self._send(204, "")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_PUT(self):
        path = urlparse(self.path).path
        if not self._gate(path):
            return
        payload = self._body()
        if payload is None or not isinstance(payload, dict):
            self._send(400, json.dumps({"error": "bad json"}))
            return
        if path == "/api/pin":
            self._pin(payload)
            return
        if path == "/api/settings":
            self._settings(payload)
            return
        if path == "/api/routine":                  # {"kind": "sunrise|sleep|pomodoro|slideshow", "minutes"...} or {"kind": "stop"}
            if payload.get("kind") == "stop":
                rt_stop("stopped on the page")
                self._send(200, json.dumps(rt_status()))
                return
            ok, err = rt_start(payload.get("kind"), payload)
            self._send(200 if ok else 400, json.dumps(rt_status() if ok else {"error": err}))
            return
        if path == "/api/schedule":                 # {"item": {...}} add or change one entry
            v = sched_upsert(payload.get("item"))
            self._send(200 if v else 400, json.dumps(v or {"error": "That schedule entry isn't complete."}))
            return
        if path == "/api/scenes":
            items = scenes_upsert(payload)
            if items is None:
                self._send(400, json.dumps({"error": "scene needs a name"}))
            else:
                self._send(200, json.dumps(items))
            return
        if path == "/api/favorites" and "order" in payload:     # a drag on the page
            items = favs_reorder(payload.get("order"))
            self._send(200 if items is not None else 400,
                       json.dumps(items if items is not None else {"error": "order must list the current favourites"}))
            return
        if path == "/api/favorites":
            p = payload if isinstance(payload, dict) else {}
            items = favs_set(p.get("key"), bool(p.get("on", True)))
            if items is None:
                self._send(400, json.dumps({"error": "key must be device:NAME, fx:NAME, mood:NAME or mine:NAME"}))
            else:
                self._send(200, json.dumps(items))
            return
        if path == "/api/message":
            if not payload.get("preview"):
                rt_user_action("scene")
            self._message(payload)
            return
        if path == "/api/fx":
            if not payload.get("preview"):
                rt_user_action("scene")
            self._fx(payload)
            return
        if path == "/api/debug":                    # {"action": "enter|prev|next|toggle|exit"}
            a = (payload if isinstance(payload, dict) else {}).get("action")
            if a == "enter":
                rt_user_action("scene")
                dbg_enter()
            elif dbg_active() and a in ("prev", "next", "toggle", "exit"):
                _dbg_q.put({"prev": ("step", -1), "next": ("step", 1), "toggle": ("toggle", None),
                            "exit": ("exit", None)}[a])
            self._send(200, json.dumps(dbg_status()))
            return
        if path == "/api/touch":                    # {"rotate": degrees} if swipes come out turned
            p = payload if isinstance(payload, dict) else {}
            data = _load_json(TOUCH_FILE, {})
            if p.get("rotate") is None:
                data.pop("rotate", None)
            else:
                data["rotate"] = int(p["rotate"]) % 360
            _save_json(TOUCH_FILE, data)
            broadcast_state()
            self._send(200, json.dumps(touch_status()))
            return
        if path == "/api/simon":                    # {"tap": panelId} from the page, or {"action": "new"}
            p = payload if isinstance(payload, dict) else {}
            if p.get("action") == "new" and not sim_active():
                self._fx({"name": SIMON_NAME})
                return
            if p.get("action") == "new":
                sim_start(play=True)
            elif "tap" in p:
                sim_tap(p.get("tap"))
            self._send(200, json.dumps(sim_status()))
            return
        if path == "/api/replicate/frame":         # from the Mac app: a screen thumbnail
            if rep_active():
                with _rep_lock:
                    _rep["grid"], _rep["gridAt"], _rep["error"] = payload, time.time(), ""
                _rep_wake.set()
            self._send(200, json.dumps({"active": rep_active()}))
            return
        if path == "/api/replicate/status":        # from the Mac app: why it can't capture
            with _rep_lock:
                _rep["error"], _rep["errorAt"] = str(payload.get("error") or "")[:200], time.time()
            broadcast_state()
            self._send(200, json.dumps({"active": rep_active()}))
            return
        if path == "/api/reconnect":
            started = start_reconnect(pair=bool(payload.get("pair")))
            self._send(200, json.dumps({"started": started, "reconnect": snapshot()["reconnect"]}))
            return
        # The page may attach what it is showing so we can remember it. Stripped
        # before the body goes to the device.
        ui = payload.pop("_ui", None) if isinstance(payload, dict) else None
        if path in ("/api/state", "/api/effect"):
            if path == "/api/state" and payload.get("on", {}).get("value") is False:
                rt_user_action("off")
            elif path == "/api/state" and set(payload) <= {"brightness"}:
                rt_user_action("bright")
            elif path == "/api/effect" or set(payload) & {"hue", "sat", "ct"}:
                rt_user_action("scene")
            if path == "/api/state" and payload.get("on", {}).get("value") is True and "brightness" not in payload:
                payload = _on_body(payload)         # back to the brightness from before the sleep timer
        if path == "/api/state":
            code, body = write("/state", payload)
        elif path == "/api/effect":
            code, body = write("/effects", payload)
        else:
            self._send(404, json.dumps({"error": "not found"}))
            return
        if 200 <= code < 300:
            if isinstance(ui, dict):
                with _ui_lock:
                    _ui["sceneName"] = ui.get("sceneName")
                    _ui["panels"] = ui.get("panels") or {}
                    _ui["message"] = None      # anything else replaces a running message/effect
                    _ui["fx"] = None
                    _save_json(UI_FILE, _ui)
            schedule_refresh(0.5)   # confirm the real state shortly after
        self._send(code, body)

    def _pin(self, p):
        """{"pin"} to sign a phone in; {"set"} / {"clear"} only from this computer."""
        if "set" in p or "clear" in p:
            if not self._local():
                self._send(403, json.dumps({"error": "The PIN can only be changed on the computer running NanoManager."}))
                return
            if p.get("clear"):
                set_settings(pin=None, sessions=[])
            else:
                pin = str(p.get("set") or "").strip()
                if not (pin.isdigit() and 4 <= len(pin) <= 12):
                    self._send(400, json.dumps({"error": "Use 4 to 12 digits."}))
                    return
                set_settings(pin=_pin_hash(pin), sessions=[])
            broadcast_state()
            self._send(200, json.dumps(settings_public()))
            return
        ok, wait = pin_check(self.client_address[0], str(p.get("pin") or ""))
        if not ok:
            self._send(429 if wait else 401, json.dumps({"error": "wrong pin", "wait": wait}))
            return
        tok = pin_session_new()
        self._send(200, json.dumps({"ok": True}), headers={
            "Set-Cookie": f"{PIN_COOKIE}={tok}; Path=/; Max-Age=31536000; SameSite=Strict; HttpOnly"})

    def _settings(self, p):
        """{"fade": tenths, "lat": deg, "lon": deg} (null clears the location)."""
        kw = {}
        if "fade" in p:
            try:
                kw["fade"] = max(1, min(600, int(p["fade"])))
            except (TypeError, ValueError):
                self._send(400, json.dumps({"error": "fade must be a number of tenths"}))
                return
        if "lat" in p or "lon" in p:
            try:
                lat, lon = p.get("lat"), p.get("lon")
                if lat is None or lon is None or lat == "" or lon == "":
                    kw.update(lat=None, lon=None)
                else:
                    lat, lon = float(lat), float(lon)
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError
                    kw.update(lat=round(lat, 4), lon=round(lon, 4))
            except (TypeError, ValueError):
                self._send(400, json.dumps({"error": "latitude -90..90, longitude -180..180"}))
                return
        if p.get("newRunToken") and self._local():
            kw["runToken"] = secrets.token_urlsafe(9)
        set_settings(**kw)
        broadcast_state()
        self._send(200, json.dumps(dict(settings_public(), local=self._local(), runToken=setting("runToken"))))

    def _fx(self, payload):
        """Play one of the built-in animated effects (or preview its frames)."""
        if payload.get("name") == REP_NAME:
            self._replicate(payload)
            return
        if payload.get("name") == SIMON_NAME:
            self._simon(payload)
            return
        with _state_lock:
            st = _state
        if not st:
            code, body = read("/")
            if code != 200:
                self._send(502, json.dumps({"error": "Panels unreachable"}))
                return
            st = json.loads(body)
        try:
            r = effects.build(str(payload.get("name", "")), st)
        except (ValueError, KeyError) as e:
            self._send(400, json.dumps({"error": str(e)}))
            return
        out = effects.to_json(r)
        if payload.get("preview"):
            self._send(200, json.dumps(out))
            return
        if not (st.get("state") or {}).get("on", {}).get("value", True):
            write("/state", {"on": {"value": True}})
        code, body = write("/effects", {"write": r["body"]})
        if 200 <= code < 300:
            with _ui_lock:
                _ui["sceneName"] = effects.EFFECTS[r["name"]]["label"]
                _ui["panels"] = {}
                _ui["message"] = None
                _ui["fx"] = {"name": r["name"]}
                _save_json(UI_FILE, _ui)
            schedule_refresh(0.5)
            self._send(200, json.dumps(out))
        else:
            self._send(code, body)

    def _replicate(self, payload):
        """Start Replicate. Nothing is written here: the worker writes once frames arrive."""
        out = {"name": REP_NAME, "seconds": 0, "frames": []}
        if payload.get("preview"):
            self._send(200, json.dumps(out))
            return
        with _state_lock:
            st = _state
        if st and not (st.get("state") or {}).get("on", {}).get("value", True):
            write("/state", {"on": {"value": True}})
        with _ui_lock:
            _ui.update({"sceneName": REP_CARD["label"], "panels": {}, "message": None, "fx": {"name": REP_NAME}})
            _save_json(UI_FILE, _ui)
        rep_start()
        broadcast_state()
        schedule_refresh(0.5)
        self._send(200, json.dumps(out))

    def _simon(self, payload):
        """Start a game of Simon. The worker writes the board and the first round."""
        out = {"name": SIMON_NAME, "seconds": 0, "frames": []}
        if payload.get("preview"):
            self._send(200, json.dumps(out))
            return
        with _state_lock:
            st = _state
        if not st:
            self._send(502, json.dumps({"error": "Panels unreachable"}))
            return
        if not (st.get("state") or {}).get("on", {}).get("value", True):
            write("/state", {"on": {"value": True}})
            with _state_lock:
                if _state:
                    _state["state"]["on"]["value"] = True
        with _ui_lock:
            _ui.update({"sceneName": SIMON_CARD["label"], "panels": {}, "message": None, "fx": {"name": SIMON_NAME}})
            _save_json(UI_FILE, _ui)
        sim_start(play=True)
        broadcast_state()
        self._send(200, json.dumps(out))

    def _message(self, payload):
        """Spell text on the wall (or just preview it when payload.preview is true).

        Builds one looping custom animation from glyphs.json and sends it in a
        single write, so the device animates by itself afterwards."""
        with _state_lock:
            st = _state
        if not st:
            code, body = read("/")
            if code != 200:
                self._send(502, json.dumps({"error": "Panels unreachable"}))
                return
            st = json.loads(body)
        panels = st["panelLayout"]["layout"]["positionData"]
        opts = {k: payload.get(k) for k in ("color", "heart", "bg", "hold", "gap")}
        try:
            r = message.build(str(payload.get("text", "")), panels, **opts)
        except (ValueError, KeyError) as e:
            self._send(400, json.dumps({"error": str(e)}))
            return
        out = message.to_json(r)
        if payload.get("preview"):
            self._send(200, json.dumps(out))
            return
        if not (st.get("state") or {}).get("on", {}).get("value", True):
            write("/state", {"on": {"value": True}})
        code, body = write("/effects", {"write": r["body"]})
        if 200 <= code < 300:
            name = str(payload.get("name") or "").strip()[:40] or None
            with _ui_lock:
                _ui["sceneName"] = name
                _ui["panels"] = {}
                _ui["message"] = {"text": str(payload.get("text", "")).strip()[:80],
                                  **{k: r["options"][k] for k in ("color", "heart", "bg", "hold", "gap")}}
                _ui["fx"] = None
                _save_json(UI_FILE, _ui)
            schedule_refresh(0.5)
            self._send(200, json.dumps(out))
        else:
            self._send(code, body)

    def do_DELETE(self):
        u = urlparse(self.path)
        if not self._gate(u.path):
            return
        if u.path == "/api/schedule":
            self._send(200, json.dumps(sched_delete(unquote((parse_qs(u.query).get("id") or [""])[0]))))
            return
        if u.path == "/api/scenes":
            name = unquote((parse_qs(u.query).get("name") or [""])[0])
            items = scenes_delete(name)
            favs_set("mine:" + name, False)         # a deleted scene can't stay a favourite
            self._send(200, json.dumps(items))
        else:
            self._send(404, json.dumps({"error": "not found"}))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Browsers drop the event stream on every reload; that is not an error.
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    print(f"Nanoleaf control panel:  http://{LISTEN[0]}:{LISTEN[1]}"
          + (f"  (phones: http://{socket.gethostname().split('.')[0]}.local:{LISTEN[1]})" if LISTEN[0] == "0.0.0.0" else ""))
    print(f"  device: {cfg()['ip'] or '(not found yet - the page searches for it)'}:{NANO_PORT}"
          + ("" if cfg()['token'] else "  (no token yet - pair from the page)"))
    if DATA != HERE:
        print(f"  data:   {DATA}")
    print(f"  safety: >={MIN_WRITE_GAP}s between writes, "
          f"breaker after {FAIL_LIMIT} fails ({COOLDOWN}s cooldown)")
    threading.Thread(target=device_event_loop, daemon=True).start()
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=sched_loop, daemon=True).start()
    if rep_active():
        rep_start()
    if sim_active():
        sim_start(play=False)       # board back up (unless the panels are off); swipe to play
    if dbg_active():
        dbg_start()                 # back on the scene it was showing (unless the panels are off)
    srv = Server(LISTEN, H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
