#!/usr/bin/env python3
"""nl - command line control for the Nanoleaf Shapes.

Talks straight to the panels, so it works whether or not the web UI is running.
Run `./nl.py --help` for the command list.

Config (optional): NANOLEAF_IP, NANOLEAF_PORT, NANOLEAF_TOKEN (else token.txt).
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL_SHAPE = 12          # the controller: triangular, no LEDs, never paintable
MIN_GAP = 0.6            # never write faster than this; the controller crashes if hammered
_last_write = 0.0


def token():
    env = os.environ.get("NANOLEAF_TOKEN")
    if env:
        return env.strip()
    try:
        with open(os.path.join(HERE, "token.txt")) as f:
            return f.read().strip()
    except OSError:
        sys.exit("No token. Set NANOLEAF_TOKEN or create token.txt (see README.md).")


def _device():
    """Address + token: device.json (written when the page reconnects) beats env/token.txt."""
    try:
        with open(os.path.join(HERE, "device.json")) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    ip = saved.get("ip") or os.environ.get("NANOLEAF_IP")
    if not ip:
        sys.exit("No address for the panels. Set NANOLEAF_IP (the control page's Reconnect finds it for you).")
    return ip, saved.get("token") or token()


_IP, _TOKEN = _device()
BASE = "http://%s:%s/api/v1/%s" % (_IP, os.environ.get("NANOLEAF_PORT", "16021"), _TOKEN)


def call(method, path, body=None):
    global _last_write
    if method != "GET":
        gap = time.time() - _last_write
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            if method != "GET":
                _last_write = time.time()
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Device refused the request (HTTP {e.code}): {e.read().decode()[:200]}")
    except Exception as e:
        sys.exit(f"Cannot reach the panels at {BASE.rsplit('/api', 1)[0]}: {e}\n"
                 "If they are unresponsive, unplug the controller ~10s and plug it back in.")


def full():
    return call("GET", "/")


def hex_rgb(h):
    h = h.lstrip("#")
    if len(h) != 6:
        sys.exit(f"Bad colour '{h}' - use #rrggbb")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hsb_rgb(h, s, b):
    s, b = s / 100.0, b / 100.0
    c = b * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = b - c
    r, g, bl = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(int(round((v + m) * 255)) for v in (r, g, bl))


def light_panels(d=None):
    d = d or full()
    pos = d["panelLayout"]["layout"]["positionData"]
    return [p for p in pos if p["shapeType"] != CTRL_SHAPE]


def static_write(pairs):
    """pairs: list of (panelId, (r,g,b)). A static effect MUST list every panel."""
    parts = [str(len(pairs))]
    for pid, (r, g, b) in pairs:
        parts.append(f"{pid} 1 {r} {g} {b} 0 5")
    return call("PUT", "/effects", {"write": {
        "command": "display", "version": "2.0", "animType": "static",
        "animData": " ".join(parts), "loop": False, "palette": []}})


# ---------------------------------------------------------------- commands
def cmd_state(a):
    d = full()
    print(f"name       {d['name']}  ({d['model']} fw {d['firmwareVersion']})")
    print(f"power      {'on' if d['state']['on']['value'] else 'off'}")
    print(f"brightness {d['state']['brightness']['value']}%")
    print(f"scene      {d['effects']['select']}")
    print(f"colorMode  {d['state']['colorMode']}")
    print(f"panels     {len(light_panels(d))} (+1 controller)")


def cmd_on(a):
    call("PUT", "/state", {"on": {"value": True}});  print("on")


def cmd_off(a):
    call("PUT", "/state", {"on": {"value": False}}); print("off")


def cmd_bright(a):
    v = max(0, min(100, a.level))
    call("PUT", "/state", {"brightness": {"value": v}}); print(f"brightness {v}%")


def cmd_scenes(a):
    d = full()
    cur = d["effects"]["select"]
    for n in d["effects"]["effectsList"]:
        print(("* " if n == cur else "  ") + n)


def cmd_scene(a):
    call("PUT", "/effects", {"select": a.name}); print(f"scene: {a.name} (moving)")


def cmd_freeze(a):
    """Play a scene's colours as a still image instead of an animation."""
    defn = call("PUT", "/effects", {"write": {"command": "request", "animName": a.name}})
    pal = defn.get("palette") or []
    if not pal:
        sys.exit(f"No palette for '{a.name}' - check the name with `nl.py scenes`")
    panels = light_panels()
    pairs = [(p["panelId"], hsb_rgb(c["hue"], c["saturation"], max(35, c["brightness"])))
             for p, c in zip(panels, (pal[i % len(pal)] for i in range(len(panels))))]
    static_write(pairs)
    print(f"scene: {a.name} (frozen, {len(pairs)} panels)")


def cmd_color(a):
    r, g, b = hex_rgb(a.hex)
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        hue = 0
    elif mx == r:
        hue = (60 * ((g - b) / d)) % 360
    elif mx == g:
        hue = 60 * ((b - r) / d) + 120
    else:
        hue = 60 * ((r - g) / d) + 240
    sat = 0 if mx == 0 else int(round(d / mx * 100))
    call("PUT", "/state", {"on": {"value": True}})
    call("PUT", "/state", {"hue": {"value": int(round(hue))}, "sat": {"value": sat}})
    print(f"solid {a.hex} on all panels")


def cmd_panels(a):
    for p in light_panels():
        print(f"{p['panelId']:>6}  x={p['x']:>4} y={p['y']:>4}  "
              f"{'hexagon' if p['shapeType'] == 7 else 'mini-triangle'}")


def cmd_paint(a):
    """Colour specific panels. Unlisted panels need a colour too (static writes carry
    every panel), so they come from --base, or go black."""
    want = {}
    for item in a.assignment:
        if "=" not in item:
            sys.exit(f"Bad assignment '{item}' - use PANELID=#rrggbb")
        pid, hx = item.split("=", 1)
        want[int(pid)] = hex_rgb(hx)
    panels = light_panels()
    ids = {p["panelId"] for p in panels}
    unknown = set(want) - ids
    if unknown:
        sys.exit(f"Not light panels: {sorted(unknown)} (see `nl.py panels`)")

    base = {}
    if a.base:
        defn = call("PUT", "/effects", {"write": {"command": "request", "animName": a.base}})
        pal = defn.get("palette") or []
        if not pal:
            sys.exit(f"No palette for '{a.base}'")
        for i, p in enumerate(panels):
            c = pal[i % len(pal)]
            base[p["panelId"]] = hsb_rgb(c["hue"], c["saturation"], max(35, c["brightness"]))

    pairs = [(p["panelId"], want.get(p["panelId"], base.get(p["panelId"], (0, 0, 0))))
             for p in panels]
    static_write(pairs)
    print(f"painted {len(want)} panel(s); {len(panels) - len(want)} "
          f"{'kept the ' + a.base + ' palette' if a.base else 'set to black'}")


def cmd_say(a):
    """Spell a message, one character at a time, as a looping animation on the device."""
    import message
    d = full()
    try:
        r = message.build(" ".join(a.text), light_panels(d), color=a.color, heart=a.heart,
                          bg=a.bg, hold=a.hold, gap=a.gap)
    except ValueError as e:
        sys.exit(str(e))
    if a.preview:
        maps = [r["frames"][i][0] for i in r["keyframes"]]
        labels = [t if t != " " else "(space)" for t in r["tokens"]]
        out = a.preview
        with open(out, "w") as f:
            f.write(message.preview_svg(d, maps, labels))
        print(f"preview of {len(labels)} characters written to {out}")
        return
    call("PUT", "/state", {"on": {"value": True}})
    call("PUT", "/effects", {"write": r["body"]})
    print(f"showing: {' '.join(r['tokens']).replace('  ', ' _ ')}   "
          f"({len(r['tokens'])} characters, loops every {r['seconds']:.0f}s, plays on the panels by itself)")


def cmd_letters(a):
    import message
    g, _ = message.load_glyphs()
    print("characters the wall can draw: " + " ".join(sorted(g)))
    print("also: space, <3 / any heart emoji = " + message.HEART)


def cmd_raw(a):
    body = json.loads(a.body) if a.body else None
    out = call(a.method.upper(), a.path, body)
    print(json.dumps(out, indent=2) if out else "(no content)")


def main():
    p = argparse.ArgumentParser(
        prog="nl.py", description="Control the Nanoleaf Shapes from the command line.",
        epilog="Examples:\n"
               "  ./nl.py state\n"
               "  ./nl.py bright 40\n"
               "  ./nl.py scene 'Northern Lights'\n"
               "  ./nl.py freeze 'Cocoa Beach'\n"
               "  ./nl.py color '#ff8800'\n"
               "  ./nl.py paint 51229='#00d4ff' --base 'Cocoa Beach'\n"
               "  ./nl.py say 'I <3 YOU'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state", help="show power, brightness, current scene").set_defaults(fn=cmd_state)
    sub.add_parser("on", help="turn the panels on").set_defaults(fn=cmd_on)
    sub.add_parser("off", help="turn the panels off").set_defaults(fn=cmd_off)

    s = sub.add_parser("bright", help="set brightness 0-100")
    s.add_argument("level", type=int); s.set_defaults(fn=cmd_bright)

    sub.add_parser("scenes", help="list saved scenes (* = current)").set_defaults(fn=cmd_scenes)

    s = sub.add_parser("scene", help="play a scene (animated)")
    s.add_argument("name"); s.set_defaults(fn=cmd_scene)

    s = sub.add_parser("freeze", help="show a scene's colours but still, no motion")
    s.add_argument("name"); s.set_defaults(fn=cmd_freeze)

    s = sub.add_parser("color", help="one solid colour on every panel")
    s.add_argument("hex"); s.set_defaults(fn=cmd_color)

    sub.add_parser("panels", help="list panel ids and positions").set_defaults(fn=cmd_panels)

    s = sub.add_parser("paint", help="colour individual panels")
    s.add_argument("assignment", nargs="+", metavar="PANELID=#RRGGBB")
    s.add_argument("--base", metavar="SCENE",
                   help="colour the other panels from this scene instead of black")
    s.set_defaults(fn=cmd_paint)

    s = sub.add_parser("say", help="spell a message one character at a time, e.g. say 'I <3 YOU'")
    s.add_argument("text", nargs="+")
    s.add_argument("--color", metavar="#RRGGBB", help="letter colour (default white)")
    s.add_argument("--heart", metavar="#RRGGBB", help="heart colour (default red)")
    s.add_argument("--bg", metavar="#RRGGBB", help="colour for the other panels (default off)")
    s.add_argument("--hold", type=float, metavar="SEC", help="seconds per character (default 2)")
    s.add_argument("--gap", type=float, metavar="SEC", help="blank between characters (default 0.5)")
    s.add_argument("--preview", metavar="FILE.svg", help="write a picture of each character instead of sending")
    s.set_defaults(fn=cmd_say)

    sub.add_parser("letters", help="list the characters `say` can draw").set_defaults(fn=cmd_letters)

    s = sub.add_parser("raw", help="send any request to the device API")
    s.add_argument("method"); s.add_argument("path"); s.add_argument("body", nargs="?")
    s.set_defaults(fn=cmd_raw)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
