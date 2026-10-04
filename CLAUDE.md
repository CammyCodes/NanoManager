# NanoManager / Nanoleaf Shapes — notes for agents

Local control for Nanoleaf light panels (Mac app, Windows launcher, Fire TV app, phone web app). `README.md` is
the public front page (install steps for non-developers; keep that tone), `docs/GUIDE.md` the detailed guide.
This file covers what you need to change the code safely. **Update both when you add or
change a feature.**

- Developed against a Nanoleaf Shapes wall (model NL42, firmware 7.1.6, 9 hexagons + 10 mini triangles + controller). The panel ids in this file and in `glyphs.json` / `effects.py` (Heartbeat) belong to that one wall; everything else is built from the layout the device reports.
- Stack: Python **stdlib only** (no pip), a single HTML page with inline CSS/JS, a Swift/Cocoa wrapper app.
- Auth token is in `token.txt` / `device.json` (both git-ignored). Never paste it into docs, issues, artifacts or anything published, and never commit it.
- A hosted web page (e.g. a claude.ai Artifact) can't reach a LAN device. Control has to run on a computer on the same network.

## Files

| File | Role |
|---|---|
| `nanoleaf_server.py` | HTTP server on `127.0.0.1:8765`: serves the page, proxies to the device through the rate limiter, follows the device SSE stream, pushes snapshots to pages, saves scenes, reconnects and re-pairs |
| `nanoleaf.html` | The whole UI. Tabs: Scenes / Custom / Colour / Paint / Message. Moods are the `PRESETS` array; speeds are `SPEED` |
| `effects.py` | Per-panel keyframe animations (`EFFECTS` registry), served by `/api/effects` and `/api/fx`. Entries with `group:"game"` (Pac-Man, Tetris, Pong, Simon, Light Cycles) show under **Arcade** on the Scenes tab and the TV |
| `replicate.py` | Replicate: screen thumbnail grid → per-panel "mood" colours (`regions`, `mood`, `Mapper`, `changed`, `static_body`). No device I/O |
| `message.py` | Text → one looping `custom` animation from `glyphs.json`; also `wall_shapes()` geometry and `preview_svg()` |
| `glyphs.json` | `glyphs` (char → list of strokes → panel ids) and `aliases` (`<3`, heart emoji → `♥`) |
| `nl.py` | CLI; writes to the device **directly**, not through the proxy |
| `start.sh` | Runs the server and opens the browser |
| `app/NanoManager.swift` | WKWebView window. Starts `/usr/bin/python3 -u nanoleaf_server.py` from the bundle with `NANOLEAF_DATA_DIR` set; stops it on quit. `ScreenMood` class = Replicate's ScreenCaptureKit capture |
| `app/build_app.sh` | swiftc → bundle, copies the server files in, draws the icon, signs, installs to `/Applications/NanoManager.app`; `--release` builds a universal (arm64 + x86_64), ad-hoc-signed zip in `dist/` with no personal data inside |
| `app/make_icon.sh`, `app/Info.plist` | Icon (SVG → icns); bundle id `io.github.cammycodes.nanomanager`, macOS 13+, `NSAllowsLocalNetworking` |
| `palettes.json`, `scenes.json`, `favorites.json`, `ui_state.json`, `device.json`, `token.txt`, `server.log` | Data (see *Server internals*) |

## Hard rules

1. **Rate limit every write.** The controller crashed on 2026-09-15 when it got a full static write on every click. It dropped off the network and needed a physical power cycle. Rules: at least 0.6 s between writes, one in flight, debounce UI input. On the server, every device write goes through `write()` (it serialises writes, enforces `MIN_WRITE_GAP`, and trips the breaker after 3 consecutive network failures for a 20 s cooldown; HTTP error codes don't count toward the breaker). In `nl.py`, go through `call()`. Never add a raw `urllib` PUT. Test scripts should use the proxy on 8765. Reads (`GET`) are cheap and safe.
2. `version:"2.0"` is required on every `display` write. Without it the device returns HTTP 400.
3. `static` and `custom` writes must list **every** light panel (19). Leave out the controller (shapeType 12). To repaint one panel, resend all the others with their current colours.
4. In a `custom` animation, each panel's frame durations must sum to the same total. `effects.build()` raises if they don't.
5. Code must run on `/usr/bin/python3` = **3.9.6** (the app uses it). No `match`, no `X | None`, no 3.10+ APIs.
6. **The app runs a bundled copy.** After editing any of `nanoleaf_server.py nanoleaf.html message.py effects.py replicate.py glyphs.json nl.py`, run `app/build_app.sh` or the app won't see the change. The script quits the running NanoManager and replaces the installed app, so tell the user before you run it. Windows: `windows/build_windows_zip.sh` bundles the same files with an embeddable Python; `windows/launcher.py` is the entry point (`-X utf8` matters: the server prints non-ASCII text). README/CLAUDE.md changes don't need a rebuild (the page never serves them).

## Testing without touching the wall

- `PUT /api/fx {"name":"snake","preview":true}` and `PUT /api/message {"text":"I <3 YOU","preview":true}` return frames and send nothing.
- `./nl.py say --preview out.svg "I <3 YOU"` draws each character to an SVG.
- Build an effect offline, starting from the proxy's cached state:
  ```bash
  curl -s 127.0.0.1:8765/api/state | python3 -c 'import sys,json,effects; st=json.load(sys.stdin)["device"]; r=effects.build("snake", st); print(r["seconds"], "s", r["frames"], "frames", len(json.dumps(r["body"])), "bytes")'
  ```
- After a real write, `/api/state` → `device.effects.select` reads `*Dynamic*` (custom/flow/etc.) or `*Static*` (per-panel static).
- Try page/server changes before rebuilding by running a second server on another port with its own data folder, so the app on 8765 and your real favourites/scenes aren't touched: `NANOLEAF_UI_PORT=8766 NANOLEAF_DATA_DIR=<temp dir> /usr/bin/python3 nanoleaf_server.py`. Sandboxed runners (e.g. the Claude desktop Browser pane's launch config) get "Operation not permitted" reading the Desktop folder, so copy the server files to a temp dir and run that copy. Hearts, previews and GETs never write to the panels; clicking a scene card does.
- Server log: `server.log` next to the script (start.sh), or `~/Library/Application Support/NanoManager/server.log` (app). App log: `~/Library/Logs/NanoManager.log`.

## Device facts (verified on FW 7.1.6)

- Layout from `GET /` → `panelLayout.layout.positionData`. shapeType 7 = Hexagon, 9 = Mini Triangle, 12 = controller (no LEDs, can't be painted). The page and SVG previews don't draw the controller (user asked), but it still counts toward the layout centre. Panels get a dark outline (`.outline` layer drawn above the glow, which also carries the hover/painted highlight).
- To render: rotate by `panelLayout.globalOrientation.value` (180° here) about the layout centre, **then** flip Y (the device's y points up). Skip the rotation and the wall draws upside down. `message.wall_shapes()` does this.
- Hexagons form a tree: `53008–45921–51229–13856–40756–7957–16433`, with a branch `51229–32012–13638`. Centre hex = `51229` (Ripple origin; Ripple In = the registry's `inward` flag, `far - dist` from the same origin). The mini triangles make small cycles in the adjacency graph, so graph walks need a visited set.
- Panels (id: x,y): hexagons 13638 (569,348), 32012 (469,290), 51229 (469,174), 45921 (569,116), 53008 (569,0), 13856 (368,116), 40756 (268,58), 7957 (167,116), 16433 (67,58); mini triangles 2502, 6925, 50598, 18694, 21587, 52318, 1378, 31100, 29219, 52676. Check with `./nl.py panels`.
- The device never reports per-panel colours or a custom effect's name, which is why the `_ui` mechanism exists.
- `GET /events?id=1,3` SSE works. `id: 3` events carry `{"attr":1,"value":"<effect>"}`.
- Legacy dynamic `animType`s `flow` (+`flowFactor`), `wheel`, `random`, `fade`, `highlight` take `colorType:"HSB"`, `palette:[{hue,saturation,brightness}]`, `transTime`/`delayTime` as `{minValue,maxValue}` in tenths.
- `custom` animData: `"<n> <panelId> <nFrames> R G B W T …"`, T in tenths, `loop:true`. A 310-keyframe / 4.3 KB payload was confirmed accepted (204). Current sizes: snake 54 s / 1245 frames / 16.5 KB, starlight 310 / 4.4 KB, fairydust 315 / 4.5 KB, ripple 303 / 4.0 KB, ripple_in 299 / 4.0 KB, wave 228 / 3.4 KB, rain 114 / 1.8 KB, heartbeat 43 / 0.8 KB; arcade (1.1): pacman 15 s / 261 / 3.5 KB, tetris 26 s / 321 / 4.1 KB, pong 27 s / 434 / 5.5 KB, simon 31 s / 739 / 9.7 KB, cycles 16 s / 350 / 4.9 KB (all smaller than Snake; not yet played on the wall when written). The 16 KB Snake was confirmed accepted on 2026-10-03 (played from the Fire TV app). If effects start failing with HTTP 400 or the controller gets flaky, suspect payload size.
- Auth: a bad token gets 401. `POST /api/v1/new` returns 403 outside pairing mode. Pairing mode: hold the power button 5–7 s, then there's a ~30 s window. Tokens survive reboots and power cycles; only a factory reset kills them. Pairing doesn't disconnect the Nanoleaf app or HomeKit.
- Scene palettes: `{"write":{"command":"request","animName":N}}`. Reported `animType:"plugin"` means the scene animates. To freeze one, write its palette as a static effect.

## Server internals

- **Config precedence:** `device.json` (in the data dir) > `NANOLEAF_IP` / `NANOLEAF_TOKEN` > `token.txt` (data dir, then script dir). `set_cfg()` writes `device.json`.
- **Dirs:** `DATA = NANOLEAF_DATA_DIR or script dir` holds token/scenes/ui_state/palettes/device.json. `nanoleaf.html` and `glyphs.json` always come from `HERE` (the script dir). `palettes.json` is read from DATA then HERE and written to DATA. Rebuilding it takes 16 rate-limited `request` writes.
- **Live state:** `device_event_loop` (device SSE; reconnects after 5 s) → `schedule_refresh(0.3)` debounce → `refresh_state()` (GET /) → `broadcast_state()` → every `/api/events` client. `poll_loop` re-reads every 20 s. `/api/state` re-reads if the cache is more than 3 s old. If the browser's SSE drops, the page polls `/api/state` every 5 s (header shows "polling").
- **Snapshot:** `{online, paused, pausedFor, lastError, ts, device, deviceIp, reconnect, ui, favorites, replicate}`.
- **Replicate** (added 2026-09-16) isn't a device-side loop: it's `_ui.fx={name:"replicate"}` (started via `PUT /api/fx` → `_replicate()`; listed in `/api/effects` as `REP_CARD` with `live:true`). The Mac app's `ScreenMood` polls `GET /api/replicate` every 2 s; while active it runs an `SCStream` of the main display (own app excluded) at ~32×h px, ≤1 fps, BGRA, skips frames whose mean abs diff < 2, and PUTs `/api/replicate/frame` (one in flight, newest wins). Capture failures → `PUT /api/replicate/status {error}` → `snapshot.replicate.error` → hero text. Server: one `rep_loop` thread (exits when fx changes; `_rep_thread` cleared under `_rep_lock`) maps the latest grid with `replicate.Mapper` (wall bbox stretched over the screen, vivid-weighted mean, sat ×1.35, EMA smoothing, so it re-ticks until settled) and writes a 19-panel static (1 s fade) through `write()` at most every `REP_GAP`=1 s, only if a channel moved >10, never while the panels are off. Per write it updates `_ui.panels` in memory + `broadcast_state()` (ui_state.json saved on stop only) and patches `_state` select to `*Static*`. While active, `device_event_loop` skips re-reads if state is <15 s old (poll_loop still runs). Page: `repActive()` (fx replicate + select `*…`), `REP` from the snapshot; `msgActive()` excludes it. Needs the stable local signing identity (see Lessons) or the Screen Recording grant is lost on every rebuild. Test without the wall: run a fake device on another port (`NANOLEAF_IP=127.0.0.1 NANOLEAF_PORT=…`) and PUT synthetic frames.
- **`_ui`** (`ui_state.json`) = `{sceneName, panels:{id:"#hex"}, message, fx}`. The page attaches `_ui` to `PUT /api/state|effect`. The proxy strips it before forwarding and stores it on success, which also resets `message`/`fx`. `/api/message` sets `message` (drives the stage animation); `/api/fx` sets `fx:{name}`. Everything is cleared when the device shows a named scene (`select` not starting with `*`) or `colorMode` is `hs`/`ct`.
- **Reconnect** (`reconnect_job`): try the last IP → if no answer, scan the /24 for port 16021 (64 threads, ~3 s) → probe `GET /` with the token (200 = connected, save IP; 401/403 = `needs_pairing`) → with `pair=true`, poll `POST /new` every 2 s for `NANOLEAF_PAIR_WINDOW` (90 s). Phases: `idle, checking, searching, not_found, needs_pairing, pairing, connected`. While offline, `auto_reconnect()` runs at most every 60 s and never pairs.
- `/api/fx` and `/api/message` turn the panels on first if they're off.
- **Favourites** (`favorites.json`, data dir): an ordered list of `kind:name` keys, kinds `device` (effectsList name), `fx` (EFFECTS key, not label — "Starlight" is both a device scene and an effect), `mood` (PRESETS name), `mine` (scenes.json name). Keys compare case-insensitively. `favs_set()` validates the kind, saves the file and broadcasts; the list rides in every snapshot as `favorites`, so all open windows stay in sync. `DELETE /api/scenes` also drops `mine:<name>`. Unresolvable keys (e.g. a scene deleted in the Nanoleaf app) are kept but simply not shown. Page: `sceneEntries()` is the single list of every card (key, card data, active, play); `renderScenes()` builds Favourites + all sections from it and **skips the rebuild when its signature is unchanged**, which keeps the heart's pop animation and a pending "Delete?" from being wiped by the constant snapshots. If you add a new kind of card, add it to `sceneEntries()` and to `FAV_KINDS` in the server.
- Saved scenes (`scenes.json`) are a list keyed by case-insensitive name (max 40 chars). Page kinds: `custom` (`anim, speed, palette`), `painted` (`panels`), `message` (`text, color, heart, bg, hold, gap`). `frozen` and `fx` exist only as in-page pseudo-scenes.
- `nl.py` ignores `NANOLEAF_DATA_DIR`. It reads `token.txt`/`device.json` next to itself, so it doesn't see what the app's Reconnect learned.

## Adding things

- **Effect:** `fx_name(shapes, adj, o)` returns `{panelId: [((r,g,b), tenths), …]}` with equal totals. Register it in `EFFECTS` with `label, icon, desc, colors` (plus optional `seed`, and `group:"game"` for the Arcade section); `o` is that registry entry, so `o["colors"]` is available. The page lists it automatically. Helpers: `adjacency`, `euler_tour`, `bfs_dist`, `bfs_path`, `columns` (x-groups, top→bottom), `rows` (y-bands, top first), `events_to_frames`, `grid_to_panels`, `compress`, `hsv`, `mix`, `dim`. Keep frame counts reasonable: 310 keyframes is confirmed OK, and Snake's ~1245 (16 KB) is the biggest in use, confirmed accepted 2026-10-03. Check sizes with `effects.build(...)["frames"]`.
- **Mood:** add to `PRESETS` in `nanoleaf.html`: `{name, icon, anim: flow|wheel|random|fade|highlight|static, speed: slow|medium|fast, palette:[[h,s,b],…]}`. Then update the mood list and count in README.
- **Glyph:** add strokes to `glyphs.json` (and aliases if needed). Preview with `nl.py say --preview`.
- **API route:** add it to `H.do_GET` / `do_PUT` / `do_DELETE`. Send device writes through `write()`, and document the route in README's proxy table.
- **Page:** keyboard handler near the end of `nanoleaf.html` (`Space`, arrows, `1`–`5` → `setTab`). localStorage keys: `nl.tab`, `nl.flip`.

## Design notes (from the original author)

- Terminology: **"mood"** = palette scene (a `PRESETS` entry); **"effect"/"style"** = animation.
- Dim warm and pastel still moods are popular (Cozy is the favourite).
- Keep effects simple. Snake with white level-up flashes was rejected and colour-scheme changes ("too much going on"). The current Snake is plain green with a lime head and red apples, grows up to 7 and shrinks at the end of a round.
- Arcade games (added 1.1) follow the same rule: classic colours, no whole-wall white flashes (Tetris's line clear and Pac-Man's ghost catch flash only the panels involved). They're scripted rounds with seeded randomness, so the same wall always plays the same game. Pac-Man's chomp (yellow/orange toggle) was dropped because the device's fades smeared it into an orange trail.
- Letters must stay small and central. The first versions spanned the whole Y-shaped wall and "looked terrible". Unreadable glyphs (T, -, !) were dropped. E/M/W can't be drawn, so "I LOVE YOU" is impossible; use "I ❤ YOU".

## Lessons / gotchas

- An app that ran the server from the Desktop folder froze in `open()` behind macOS's Desktop-folder permission prompt. That's why the bundle is self-contained and uses Application Support.
- On first run the app seeds `token.txt, scenes.json, ui_state.json, palettes.json` into the data dir **only if missing**. Rebuilds never overwrite user data, and editing `token.txt` here doesn't reach the app afterwards.
- **Signing (2026-09-16):** `build_app.sh` signs with the self-signed "NanoManager Local Signing" identity in the login keychain (untrusted, codeSigning EKU, 20 years) when present, falling back to ad-hoc. Its designated requirement is identifier + certificate leaf, so the Screen Recording grant survives rebuilds; ad-hoc signatures are cdhash-only and lose the grant every build (that's what broke Replicate's first run). Don't delete that keychain identity. The Swift app doesn't gate capture on `CGPreflightScreenCaptureAccess` (it can stay false after the grant); it tries `SCShareableContent` and only uses preflight to explain a failure.
- codesign rejects freshly written bundles as "detritus" (the `com.apple.provenance` xattr). `build_app.sh` strips xattrs and retries up to 3 times.
- `osascript … quit` hangs if the app's main thread is blocked. Use `pkill -9 NanoManager`.
- If something already answers on 8765 (e.g. `start.sh`), the app just loads that page and won't stop it on quit.
- The server listens on `NANOLEAF_LISTEN` (default `127.0.0.1`). The Mac app sets `0.0.0.0` so phones on the LAN can open the page (no auth: anyone on the home Wi-Fi can control the wall).
- Recovering a dead controller: unplug it for ~10 s. Token and saved scenes survive.

## iPhone

Two routes, both sharing `mobile/` (`mobile.css`, `mobile.js`, icons, `manifest.webmanifest`):

- **Home Screen web app (what's shipped).** The Mac app's server serves `/mobile/*`, `/apple-touch-icon.png` and `/manifest.webmanifest`. `nanoleaf.html` loads the mobile CSS/JS when `navigator.standalone` or a coarse pointer under 820px wide (sets `window.NANO_WEB`). URL: the one in the page's "On your phone" line (`phoneUrl` in the snapshot), or `http://<computer name>.local:8765`. The Mac app holds a `PreventUserIdleSystemSleep` assertion while open. `mobile/` edits need `app/build_app.sh` (it copies the folder into the bundle).
- **Native app (`ios/`, not in this repo).** An earlier experiment that needs Xcode + an Apple ID; the notes below are kept for reference. SwiftUI + WKWebView loading the same `nanoleaf.html` via `nano://app/`; `NanoServer.swift` is a Swift port of the server (same rate limiter/breaker, SSE follow, reconnect/subnet scan, favourites/scenes in Application Support, token in the Keychain); `Effects.swift`/`Message.swift` port effects.py/message.py (deterministic effects and messages give byte-identical animData; starlight/fairydust/rain use a different seeded PRNG). `mobile-bridge.js` routes `fetch('/api/..')`/`EventSource` to Swift. Project is generated by `ios/tools/gen_project.py`; `ios/build_ios.sh` seeds data from the Mac app, builds, installs with devicectl. Keep the Swift ports in step with the Python when effects/glyph logic changes.

## Fire TV (`firetv/`, added 2026-10-03)

Standalone Android TV app (developed on a Fire TV Stick running Fire OS 8.1 = Android 11/API 30, 32-bit ARM, 1920x1080 @ 320 dpi so the CSS viewport is 960x540; the APK has no native code so it runs on any ABI). It talks to the panels **directly** (no computer needed). Package `io.github.cammycodes.nanomanager.tv`, label "NanoManager".

| File | Role |
|---|---|
| `firetv/build_tv.sh [--wall] [--install]` | No Gradle: gen_data → make_art → aapt2 compile/link → javac `--release 8` → d8 → zipalign → apksigner → `dist/NanoManager-TV.apk`. Default = **generic** build (moods/colours/device scenes; no address, token or layout inside; the app finds + pairs with the panels and reads the layout live). `--wall` = also bake effects + messages + favourites for one wall (needs `NANOLEAF_IP`; the APK then holds the token, so never share it). `--install` = adb install -r + launch (`FIRETV=<ip>:5555`) |
| `firetv/tools/gen_data.py` | Writes `build/assets/data.js` (`window.DATA`; in a `--wall` build: layout from a live `GET /`, `PRESETS`/`SPEED` regex-parsed out of nanoleaf.html, `effects.build()` bodies + `to_json(dt=3)` preview frames, `message.build()` for `MESSAGES`, palettes.json, the Mac's favorites.json + scenes.json) and `build/assets/config.json` (ip/port/token, read only by Java) |
| `firetv/tools/make_art.sh` | Banner 320x180 (+640x360 xhdpi) and launcher icons via qlmanage + sips, same art as `app/make_icon.sh` |
| `firetv/assets/tv.html` | The whole TV UI (inline CSS/JS, D-pad focus model). Has a mock `NL` when opened in a desktop browser |
| `firetv/src/.../Device.java` | All device I/O. Same limiter rules as the server: one write in flight, `MIN_GAP` 650 ms, latest-wins per key, breaker 3 network failures → 20 s pause (503 to JS). Reconnect/scan/pair job like `reconnect_job`; IP/token saved in SharedPreferences `nanoleaf` (beat config.json) |
| `firetv/src/.../MainActivity.java` | Full-screen WebView on `file:///android_asset/tv.html`, bridge `NL` (`write, read, reconnect, ip, paused, pref, setPref, exit`); callbacks `TV.onWrite/onRead/onStatus`; remote keys → `TV.remote()` (play/pause = power, rewind/ffwd = brightness, menu = favourite); Back → `TV.back()` |
| `firetv/signing/` (git-ignored) | Your signing key (`KEYSTORE`/`KSPASS` env, or generated on first build). **Keep it**: `adb install -r` needs the same key, or the app must be uninstalled first (which loses TV favourites). Never commit it |

Notes:
- Toolchain: `brew` openjdk@17 (keg-only, `/opt/homebrew/opt/openjdk@17`), android-commandlinetools, android-platform-tools (adb); SDK at `~/Library/Android/sdk` with `platforms;android-30` + `build-tools;34.0.0`.
- **The TV app bundles copies.** Changes to moods (`PRESETS`), effects.py, glyphs, palettes need `firetv/build_tv.sh --install` to reach the TV. The build reads the live device, so the wall must be online.
- JS sends every look with the single key `look` (mashing OK sends only the newest), plus `power` and `bright` (brightness debounced 250 ms, ±10 steps). Writes go to the device paths `/state` and `/effects` (no `_ui`; the TV keeps its own `last` look in prefs to label `*Static*`/`*Dynamic*`). It polls `GET /` every 5 s while visible, 0.9 s after a write.
- TV favourites/last/focus live in SharedPreferences (`ui.favs`, `ui.last`, `ui.focus`), seeded from the Mac's favorites.json at build time; extra kinds `colour:` and `msg:`. Not synced with the Mac.
- A `--wall` APK contains the token in `assets/config.json`: don't publish or share it. The generic APK has none.
- ⏻ (U+23FB) has no glyph on Fire OS; use inline SVG icons for symbols. Emoji render fine.
- Testing: `adb -s <tv ip>:5555 exec-out screencap -p > shot.png`; D-pad via `adb shell input keyevent DPAD_DOWN|DPAD_CENTER|MENU`. JS errors show in `adb logcat | grep chromium`., the first `adb connect` needs "Allow USB debugging" accepted on the TV.
