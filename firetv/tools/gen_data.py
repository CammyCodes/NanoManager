#!/usr/bin/env python3
"""Build the TV app's data.js + config.json.

Two kinds of build:

  default (what the released APK is)   Works with ANY Nanoleaf. Carries the moods, plain colours
        and the panels' own scenes, which don't depend on the shape of the wall. It holds no
        address, token or layout: the app finds the panels, pairs, and reads the layout itself.

  --wall   Also bakes in the Mac app's effects (Snake, Starlight, ...) and messages for ONE
        particular wall, plus its favourites and saved scenes, and that wall's address and token.
        Needs the panels to be reachable from this computer. The APK it makes is yours alone:
        it contains your token, so don't share it.

What goes in (--wall):
- layout: the wall's panels (read live from the device, else the Mac app's cache)
- moods: PRESETS copied out of nanoleaf.html
- effects: effects.build() bodies + a sampled preview (3/10 s steps) for the TV's wall drawing
- messages: message.build() for a few fixed phrases (typing on a remote is no fun)
- palettes: palettes.json (colours for the device's own scenes)
- favorites: the Mac app's favorites.json (only the seed; the TV keeps its own after that)
- config: device IP + token

Writes <outdir>/data.js (window.DATA = ..., read by tv.html) and <outdir>/config.json
(IP + token, read only by the Java side, so the page never holds the token).
Runs on /usr/bin/python3 (3.9). Usage: gen_data.py [--wall] <outdir>
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NL = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, NL)
import effects   # noqa: E402
import message   # noqa: E402

APP_DATA = os.path.expanduser("~/Library/Application Support/NanoManager")
MESSAGES = ["I <3 YOU", "<3", "I <3 U"]


def first(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def load_json(*paths, default=None):
    p = first(*paths)
    if not p:
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def config():
    dev = load_json(os.path.join(APP_DATA, "device.json"), os.path.join(NL, "device.json"), default={}) or {}
    tok = dev.get("token")
    if not tok:
        p = first(os.path.join(APP_DATA, "token.txt"), os.path.join(NL, "token.txt"))
        tok = open(p).read().strip() if p else ""
    ip = dev.get("ip") or os.environ.get("NANOLEAF_IP")
    if not ip:
        sys.exit("--wall needs the panels' address: set NANOLEAF_IP (or run NanoManager once so it learns it).")
    return {"ip": ip, "port": int(dev.get("port") or 16021), "token": tok}


def device_state(cfg):
    url = "http://%s:%d/api/v1/%s/" % (cfg["ip"], cfg["port"], cfg["token"])
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)
    except Exception as e:   # fall back to the Mac app's live cache
        print("  device read failed (%s); trying the Mac app's server" % e)
        with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=5) as r:
            return json.load(r)["device"]


def presets():
    """PRESETS from nanoleaf.html, converted from JS object literals to JSON."""
    src = open(os.path.join(NL, "nanoleaf.html"), encoding="utf-8").read()
    m = re.search(r"const PRESETS=\[(.*?)\n\];", src, re.S)
    out = []
    for line in m.group(1).strip().splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        js = re.sub(r"([{,])(\w+):", r'\1"\2":', line)
        out.append(json.loads(js))
    speed = re.search(r"const SPEED=(\{.*?\});", src).group(1)
    speed = json.loads(re.sub(r"(\w+):", r'"\1":', speed))
    return out, speed


def hexmap(cmap):
    return {str(k): "#%02x%02x%02x" % v for k, v in cmap.items()}


DEFAULT_FAVOURITES = ["mood:Cozy", "mood:Deep Focus", "mood:Lavender", "mood:Aurora"]


def main_generic(outdir):
    moods, speed = presets()
    data = {"layout": None, "moods": moods, "speed": speed, "effects": [], "messages": [],
            "palettes": {}, "favorites": DEFAULT_FAVOURITES, "scenes": []}
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.DATA=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    with open(os.path.join(outdir, "config.json"), "w") as f:
        json.dump({"ip": "", "port": 16021, "token": ""}, f)
    print("  wrote %s: %d moods (generic build: no address, token or layout inside)" % (out, len(moods)))


def main(outdir):
    cfg = config()
    st = device_state(cfg)
    layout = st["panelLayout"]
    moods, speed = presets()
    fx = []
    for item in effects.catalogue():
        r = effects.build(item["name"], st)
        prev = effects.to_json(r, dt=3)
        fx.append(dict(item, seconds=r["seconds"], body=r["body"], preview=prev["frames"]))
        print("  effect %-10s %5.1fs %4d keyframes %6d bytes" % (item["name"], r["seconds"], r["frames"], len(json.dumps(r["body"]))))
    panels = layout["layout"]["positionData"]
    msgs = []
    for text in MESSAGES:
        r = message.build(text, panels)
        msgs.append({"text": text, "label": text.replace("<3", "♥"), "seconds": r["seconds"], "body": r["body"],
                     "preview": [[hexmap(c), t] for c, t in r["frames"]]})
    mine = load_json(os.path.join(APP_DATA, "scenes.json"), os.path.join(NL, "scenes.json"), default=[]) or []
    for sc in mine:   # saved messages need message.py; custom/painted scenes are built by the page
        if sc.get("kind") == "message":
            try:
                opts = {k: sc.get(k) for k in ("color", "heart", "bg", "hold", "gap")}
                sc["body"] = message.build(sc.get("text", ""), panels, **opts)["body"]
            except ValueError as e:
                print("  skipping saved message %r: %s" % (sc.get("name"), e))
    data = {
        "layout": layout,
        "moods": moods,
        "speed": speed,
        "effects": fx,
        "messages": msgs,
        "palettes": load_json(os.path.join(APP_DATA, "palettes.json"), os.path.join(NL, "palettes.json"), default={}),
        "favorites": load_json(os.path.join(APP_DATA, "favorites.json"), os.path.join(NL, "favorites.json"), default=[]),
        "scenes": mine,
    }
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "data.js")
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.DATA=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    with open(os.path.join(outdir, "config.json"), "w") as f:
        json.dump(cfg, f)
    print("  wrote %s (%d KB): %d moods, %d effects, %d messages, %d favourites, %d saved scenes"
          % (out, os.path.getsize(out) // 1024, len(moods), len(fx), len(msgs), len(data["favorites"]), len(mine)))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--wall"]
    (main if "--wall" in sys.argv[1:] else main_generic)(args[0])
