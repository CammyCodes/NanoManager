# NanoManager

**Control your Nanoleaf light panels from your Mac, your Windows PC, your phone and your Fire TV, all locally, with no cloud and no account.**

Moods, animated effects (Snake, Starlight, Ripple, Rain...), colours, painting individual panels, and a wall that
copies your Mac's screen. Everything talks straight to the panels over your home Wi-Fi.

| | Download | One-line install |
|---|---|---|
| 🍎 **Mac** (Apple silicon or Intel, macOS 13+) | [NanoManager-mac.zip](https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-mac.zip) | `curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-mac.sh \| bash` |
| 🪟 **Windows** 10 / 11 (nothing else to install) | [NanoManager-windows.zip](https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-windows.zip) | `irm https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-windows.ps1 \| iex` |
| 📺 **Fire TV / Android TV** | [NanoManager-TV.apk](https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-TV.apk) | see [Fire TV](#-fire-tv--android-tv) |
| 📱 **Phone** (iPhone or Android) | nothing to download | open the address NanoManager shows you, then *Add to Home Screen* |

> **Unofficial.** NanoManager isn't made by or connected to Nanoleaf. It uses the local API every Nanoleaf controller has built in.
> It has been tried on a Nanoleaf Shapes (hexagons + mini triangles); other Nanoleaf light panels use the same API, so the basics
> (power, brightness, colours, moods, the panels' own scenes) should work on them. See [Which Nanoleafs work](#which-nanoleafs-work).

**Jump to:** [Mac](#-mac) · [Windows](#-windows) · [Fire TV / Android TV](#-fire-tv--android-tv) · [Phone](#-phone) · [Let an AI agent set it up](#let-an-ai-agent-set-it-up-for-you) · [Troubleshooting](#troubleshooting)

---

## Before you start

1. Your Nanoleaf controller is set up and on your **Wi-Fi** (use the official Nanoleaf app once if it isn't).
2. The computer / TV / phone is on **the same Wi-Fi** as the controller.
3. You're able to press the **power button on the controller**: you do that once to let NanoManager pair with it.

### Pairing (the same on every device, once per device)

The first time NanoManager opens it **looks for your panels by itself** and says *"Found Nanoleaf panels at ... They need to be paired"*.

1. **Hold the controller's power button for 5-7 seconds**, until the lights flash.
2. Click **Reconnect** (on the TV: choose **Pair**) within 30 seconds.

That's it. Pairing doesn't reset your panels or disconnect the Nanoleaf app or HomeKit, and it survives reboots and power cuts.
Each device (Mac, PC, TV) pairs separately, and you can pair as many as you like.

---

## 🍎 Mac

**Easiest:** paste this into Terminal. It downloads the latest release, puts **NanoManager** in your Applications folder and opens it.

```bash
curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-mac.sh | bash
```

**Or by hand:** download [NanoManager-mac.zip](https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-mac.zip),
unzip it, drag **NanoManager** to Applications. macOS will say it can't verify the app (it's free and unsigned, with no Apple developer account behind it).
To open it anyway: **right-click NanoManager → Open → Open**, or run:

```bash
xattr -dr com.apple.quarantine /Applications/NanoManager.app
```

Good to know:
- The first time, macOS may offer to install the **Command Line Tools** (it provides `python3`, which NanoManager's server uses). Click **Install**, wait a few minutes, then open the app again.
- macOS asks to let NanoManager find devices on your **local network**. Say **Allow**; without it the panels can't be reached.
- The screen-mirroring effect (**Replicate**) asks for **Screen & System Audio Recording** permission the first time you use it.
- While it's open, the app keeps your Mac awake so your phone can keep using it; quit it with ⌘Q.
- Your pairing and saved scenes are kept in `~/Library/Application Support/NanoManager`.

## 🪟 Windows

**Easiest:** open **PowerShell** and paste:

```powershell
irm https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-windows.ps1 | iex
```

It downloads the latest release (it carries its own copy of Python, so there is nothing else to install), adds **NanoManager** to your Start menu and Desktop, and starts it.

**Or by hand:** download [NanoManager-windows.zip](https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-windows.zip),
right-click → **Extract All**, open the folder and double-click **Start NanoManager.bat**.

Good to know:
- A black window opens: it's the server. Leave it open (minimised is fine); closing it stops NanoManager.
- Windows may say *"Windows protected your PC"*: choose **More info → Run anyway** (it's free, unsigned, and the source is right here).
- To use it from a phone, start **NanoManager (phone access)** instead; Windows will ask to allow it through the firewall: choose **Private networks**. The window then shows the address to open on your phone.
- Your pairing and saved scenes are kept in `%APPDATA%\NanoManager`.
- Not available on Windows: Replicate (screen mirroring) needs the Mac app.

## 📺 Fire TV / Android TV

A remote-friendly app: moods, colours, the panels' own scenes, favourites, brightness and power. It talks to the panels directly, so no computer needs to stay on.
Tried on a Fire TV Stick; it should work on any Fire TV and on Android TV / Google TV devices.

**On the TV, no computer needed (Downloader):**

1. On the Fire TV, search for **Downloader** (orange icon) in the Amazon app store and install it.
2. **Settings → My Fire TV → Developer options → Install unknown apps → Downloader → ON**. (On older Fire OS: *Apps from unknown sources → ON*. On Android TV the same switch is in the Downloader app's permissions prompt.)
3. Open Downloader and enter this address:

   ```
   https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-TV.apk
   ```

4. Press **Go**, then **Install**, then **Open**.
5. NanoManager looks for your panels by itself. When it says they need pairing, choose **Pair** and hold the controller's power button for 5-7 seconds until the lights flash.

Afterwards it's in **Your Apps & Channels**. On the remote: arrows to move, centre to play, **⏯** turns the lights on/off, **⏪ / ⏩** dim and brighten, **☰ (menu)** adds a card to your favourites, **Back** goes up / closes.

**From a computer instead (adb):** turn on **Settings → My Fire TV → Developer options → ADB debugging**, find the TV's address under **About → Network**, then on a Mac or Linux computer:

```bash
curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-firetv.sh | bash -s -- 192.168.1.50
```

(Use your TV's address. On Windows with `adb` installed: `adb connect 192.168.1.50:5555` then `adb install NanoManager-TV.apk`.) Accept *Allow USB debugging?* on the TV.

The TV app has the moods and the panels' own scenes. The animated effects and messages need to be built for one specific wall's shape, so they're in the Mac and Windows apps (and, for a wall you own, in a TV build you make yourself with `firetv/build_tv.sh --wall`).

## 📱 Phone

No app to install: the Mac and Windows apps serve a phone-friendly page, with big touch controls where you can even paint the panels by dragging your finger.

1. Make sure the computer running NanoManager is **on and NanoManager is open** (on Windows, start **NanoManager (phone access)**).
2. On the computer's NanoManager window, find the line under the wall that says *"On your phone (same Wi-Fi), open http://192.168.x.x:8765"*. (On a Mac the address `http://<your-Mac's-name>.local:8765` works too.)
3. Open that address on your phone's browser, then:
   - **iPhone (Safari):** Share → **Add to Home Screen** → Add.
   - **Android (Chrome):** ⋮ → **Add to Home screen** (or **Install app**).

You get a NanoManager icon that opens full screen. Your favourites and saved scenes are the same ones the computer uses.
Anyone on your Wi-Fi who knows the address can use this page, so only run it on a network you trust.

---

## Let an AI agent set it up for you

Use Claude Code, Codex, Cursor or any agent that can run commands on your computer. Copy everything in the box and paste it into the agent:

````text
You are setting up NanoManager (https://github.com/CammyCodes/NanoManager), an unofficial local controller
for Nanoleaf light panels, on THIS computer. Work step by step, say what you are doing, and stop to ask me
whenever a step needs something only I can do (pressing a button, accepting a permission prompt).

RULES
- Everything stays on my local network. Never upload or paste my Nanoleaf auth token, my IP addresses, or any
  file from the NanoManager data folder anywhere (no issues, pastebins, chats, logs shared outside this machine).
- Never write to the Nanoleaf panels' API directly in a loop. The controller crashes if it is written to faster
  than about 1-2 times per second. Talk to the NanoManager server on http://127.0.0.1:8765 instead: it enforces
  the limit. If the panels stop answering, tell me to unplug the controller for 10 seconds and plug it back in.
- Do not factory-reset the controller and do not remove its existing pairing with the Nanoleaf app or HomeKit.
  Pairing NanoManager adds a new token and breaks nothing.
- Do not install anything I haven't agreed to. The install steps below are the only ones needed.

STEPS
1. Find out my operating system.
2. Install:
   - macOS:   curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-mac.sh | bash
     (If macOS offers to install the Command Line Tools, tell me to click Install, wait, then re-run the
      script. If it asks to allow local network access, tell me to click Allow.)
   - Windows: in PowerShell run
       irm https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-windows.ps1 | iex
   - Linux / anything else (no packaged app): git clone https://github.com/CammyCodes/NanoManager, then in that
     folder run  python3 nanoleaf_server.py  (Python 3.9+, nothing to pip install) and keep it running.
3. Wait until http://127.0.0.1:8765/api/health answers (retry for up to a minute). NanoManager now searches my
   network for the panels by itself; read http://127.0.0.1:8765/api/state and look at "reconnect".phase.
4. If the phase is "needs_pairing": tell me to HOLD THE POWER BUTTON ON THE NANOLEAF CONTROLLER FOR 5-7 SECONDS
   until its lights flash, and to say "done" the moment I've started. Then immediately
     curl -X PUT http://127.0.0.1:8765/api/reconnect -d '{"pair":true}'
   and poll /api/state every 2 seconds until "reconnect".phase is "connected" (it waits up to 90 seconds).
   If it is "not_found", check that the controller has power and is on the same Wi-Fi as this computer, and
   ask me what the controller's address is if a scan still fails (the Nanoleaf app shows it).
5. Verify with me: turn the panels on, then play a mood, then ask me whether the lights changed:
     curl -X PUT http://127.0.0.1:8765/api/state -d '{"on":{"value":true}}'
   (Moods are played from the control page; to test from here, use the device scene
    curl -X PUT http://127.0.0.1:8765/api/effect -d '{"select":"Northern Lights"}'
    after listing the real names from GET /api/state -> device.effects.effectsList.)
6. Phone (optional - ask me): read "phoneUrl" from /api/state. Tell me to open it on my phone on the same
   Wi-Fi, then Share -> Add to Home Screen (iPhone Safari) or the menu -> Add to Home screen (Android Chrome).
   On Windows that needs "NanoManager (phone access)" from the Start menu.
7. Fire TV / Android TV (optional - only if I say I have one): the simplest is the Downloader app on the TV with
   https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-TV.apk ; walk me through it
   (Developer options -> install unknown apps for Downloader). Or, if I give you the TV's address and have turned
   on ADB debugging:
     curl -fsSL https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-firetv.sh | bash -s -- <TV address>
   I have to accept "Allow USB debugging?" on the TV. Then the TV app finds the panels and I choose Pair there.
8. Finish with a short summary: what was installed and where, how to start and stop NanoManager, where my data
   lives (macOS ~/Library/Application Support/NanoManager, Windows %APPDATA%\NanoManager), and anything left for me to do.
````

---

## What it can do

| | Mac | Windows | TV | Phone |
|---|:-:|:-:|:-:|:-:|
| Power, brightness, warm-to-cool white, any colour | ✅ | ✅ | ✅ | ✅ |
| 27 designed **moods** (Aurora, Cozy, Candlelight, Synthwave, Cherry Blossom, ...) | ✅ | ✅ | ✅ | ✅ |
| The panels' own scenes, played or frozen | ✅ | ✅ | ✅ | ✅ |
| Favourites (♡ on any card) | ✅ | ✅ | ✅ | ✅ |
| Animated **effects** (Snake, Starlight, Fairy Dust, Ripple, Rain, Wave) | ✅ | ✅ | ➖ | ✅ |
| **Paint** panels one by one, make and save your own scenes | ✅ | ✅ | ➖ | ✅ |
| **Replicate**: the wall copies your Mac's screen | ✅ | ❌ | ❌ | ➖ start it from the phone |
| Spell short messages like "I ❤ YOU" (only on the wall it was drawn for) | ✅ | ✅ | ➖ | ✅ |
| Command line (`nl.py`) and a local HTTP API for your own scripts | ✅ | ✅ | ❌ | ❌ |

➖ = not in that app (or only with a build for your own wall). Full details are in the **[user guide](docs/GUIDE.md)**.

### Which Nanoleafs work

NanoManager uses the standard local Nanoleaf API (a controller with firmware that supports the OpenAPI: Shapes, Light Panels / Canvas, Hexagons, Elements, Lines...).
It has only been tried on a Nanoleaf Shapes wall with 9 hexagons and 10 mini triangles (firmware 7.1.6).
- **Should work everywhere:** pairing, power, brightness, colours, moods, the panels' own scenes.
- **Built from your layout, so probably fine but untested outside Shapes:** effects, painting, Replicate.
- **Only on the wall it was drawn for:** **messages** and the Heartbeat effect (they use specific panel ids), so they hide themselves on other layouts. See [Messages and other layouts](docs/GUIDE.md#messages-and-other-layouts) if you'd like to draw your own.

### Safe for your controller

A Nanoleaf controller **can crash if it's written to too quickly**. NanoManager sends one change at a time with at least 0.6 s between them, and
pauses for 20 s if the panels stop answering. If you write your own scripts, send them through NanoManager's local API rather than straight to the panels.

### Privacy

Everything is local. NanoManager never contacts Nanoleaf's cloud and sends nothing anywhere. Your pairing token lives only in a file on your own device
(see where above). The phone page has no password, so only enable phone access on a network you trust.

## Troubleshooting

| Problem | Fix |
|---|---|
| *"Couldn't find the panels"* | The controller must be powered and on the **same Wi-Fi** as this device (not a guest network). Some routers isolate Wi-Fi from wired devices ("client isolation"): turn that off. Then click **Reconnect**. |
| *"They need pairing"* but nothing happens | Hold the controller's power button **5-7 s until the lights flash**, *then* press Reconnect / Pair within 30 s. |
| Panels stop answering / page says *offline* | Unplug the controller for ~10 seconds and plug it back in. Your pairing and scenes survive this. |
| Page says *paused* | Writes failed three times in a row, so it's giving the controller 20 s to recover. Wait it out. |
| Mac: *"NanoManager can't be opened"* | Right-click the app → **Open**, or run `xattr -dr com.apple.quarantine /Applications/NanoManager.app`. |
| Mac: window says the server didn't start | Install the Command Line Tools (`xcode-select --install`), then reopen. Details are in `~/Library/Application Support/NanoManager/server.log`. |
| Windows: SmartScreen warning | **More info → Run anyway.** |
| Windows: the phone can't open the address | Start **NanoManager (phone access)** and allow it through the firewall on **Private networks**. |
| TV app won't install | Turn on *Install unknown apps* for **Downloader** (or ADB debugging for the adb route). |
| TV app says *Offline* | Press the **⟳ Connection** button and choose **Search again**. |

Still stuck? [Open an issue](https://github.com/CammyCodes/NanoManager/issues) and say which device you're using. Never paste your token.

## Build it yourself

```bash
git clone https://github.com/CammyCodes/NanoManager && cd NanoManager
python3 nanoleaf_server.py                 # run from source on any computer (Python 3.9+, no packages)
app/build_app.sh                           # build + install the Mac app   (--release: a universal zip in dist/)
firetv/build_tv.sh                         # build the TV app              (--wall to bake in your wall's effects)
windows/build_windows_zip.sh               # assemble the Windows zip
```

Layout of the repo and the internals are in [docs/GUIDE.md](docs/GUIDE.md) and [CLAUDE.md](CLAUDE.md) (notes for AI assistants working on the code).
Contributions are welcome, especially reports and fixes for other Nanoleaf layouts.

MIT licensed. © CammyCodes. "Nanoleaf" is a trademark of its owner; this project is not affiliated with it.
