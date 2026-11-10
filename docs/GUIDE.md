# NanoManager user guide

Everything NanoManager can do, in more detail than the [README](../README.md). The panel's address
shows as `<PANEL-IP>` below: NanoManager finds it for you, or read it from the control page's header.

Run the control page from source (any computer with Python 3.9+, nothing to install):

```bash
python3 nanoleaf_server.py        # then open http://127.0.0.1:8765   (Windows: py nanoleaf_server.py)
```

## The web control panel

```bash
./start.sh
```

Opens <http://127.0.0.1:8765>. Press `Ctrl-C` in the terminal to stop it. To reach it from a
phone on your Wi-Fi too, start it with `NANOLEAF_LISTEN=0.0.0.0 ./start.sh` (anyone on your Wi-Fi
could then control the lights unless you set a PIN in ⚙ Settings).

The page always shows what the panels are actually doing. It reads the real state when it
opens, and the server listens to the panels' own event stream, so if you change something
in the Nanoleaf app or through HomeKit the page updates within about a second. The little
dot in the header says **live** when that stream is connected, **polling** if it has
fallen back to checking every 5 seconds, and **offline** if the panels can't be reached.

| Area | What it does |
|---|---|
| **Now playing** | Name of the scene, whether it's moving or still, brightness slider with quick presets, and **Play** / **Freeze** to switch between the animation and a still version of the same colours. |
| **The wall** | Your real panel layout in the current colours; hover a panel to see its id. Moving scenes drift gently on the preview, and messages and effects play on it in time with the wall. **Flip view** if it looks upside down (remembered). |
| **Scenes** | *Favourites*: every scene card (here and under Custom) has a ♡ in its corner — click it and that scene is kept at the top of this tab, in the order you added them; click the pink ♥ to take it off. *On the panels*: the 16 scenes saved on the device. *Effects*: animations built here (Snake, Starlight, Fairy Dust, Ripple, Ripple In, Rain, Wave, Heartbeat) that the panels then play by themselves, plus **Replicate**, which copies your Mac's screen live. *Ambient*: slow looks to live with (Fireplace, Storm, Ocean Waves, Northern Lights, Lava Lamp, Night Sky, Breathe 4-7-8, Moon Phase, Colour of the Day, Holiday Countdown); see [Ambient](#ambient). *Arcade*: retro games and screensavers the wall plays by itself (Pac-Man, Tetris, Pong, Simon, Light Cycles, Game of Life, Breakout, Space Invaders, Flappy, Noughts & Crosses, Lights Out, Maze, Dice, Coin Toss); see [Arcade](#arcade). *Moods*: 30 scenes designed in this page — moving ones (Aurora, Ocean, Sunrise, Lava, Forest, Candlelight, Galaxy, Synthwave, Cyberpunk, Cherry Blossom, Ice, Rainbow, Christmas, Halloween, Love, Barbie, Pet Calm) and still pastel/cosy ones (Deep Focus, Cozy, Latte, Fireside, Blush, Lavender, Peach, Mint, Sorbet, Seafoam, Honey, Focus, Night Feed). Pet Calm and Night Feed also set the brightness (35% and 8%). Drag a favourite to move it (on a phone: press and hold it first). |
| **Custom** | *My scenes*: the ones you've saved (paintings, messages and your own mixes). *Make your own*: pick up to 7 colours, a motion (Flow, Wheel, Random, Fade, Highlight, or Still) and a speed (Slow 3–6 s, Medium 1.4–2.8 s, Fast 0.4–1 s per change), then **Try it** or **Save**. |
| **Colour** | One colour on every panel, applied as you pick. Plus a warm-to-cool white slider with presets. |
| **Paint** | Choose a brush colour, click panels. Changes go to the wall as you go (untick *Live* to batch them and press **Send to panels**). **Undo**, **Fill all**, **Discard edits**, and **Save scene** to keep a painting. |
| **Message** | Spell something out, e.g. **I ❤ YOU**. The wall shows one character at a time, then loops. Pick letter, heart and background colours and how long each character holds, preview the characters, **Show on panels**, and **Save** it as a scene. See *Spelling messages* below. |
| **Timers** | Sunrise alarm, sleep timer, Pomodoro and slideshow, plus the **schedule**. See [Timers and the schedule](#timers-and-the-schedule). |
| **⚙ Settings** | Theme (match the system, dark, light), **crossfade** (how slowly still scenes fade into each other, 0.1–5 s), the phone page's address and a QR code to scan, the **PIN lock** for phones, and ready-made [links for Shortcuts, Siri and NFC tags](#links-for-shortcuts-siri-and-nfc-tags). |

**↶ Back** under *Now playing* goes back to the scene before (and the one before that…).
On a phone, swipe left or right across the wall preview for the next or previous favourite.

Keyboard: `Space` power, `↑`/`↓` brightness (±5), `[` / `]` previous / next favourite, `Z` back,
`F` favourite what's playing, `P` play, `S` hold still, `1`–`6` switch tabs, `,` settings, `?` the
list of keys. The page also remembers the last tab you had open.

Links into the page: `http://<computer>:8765/#play=mood:Cozy` plays a scene when the page opens
(any favourite key, or just its name), `#tab=routines` opens a tab, `#settings` opens Settings.

Notes:
- The dim triangle on the wall is the **controller** — it has no lights, so it can't be painted.
- Painting always holds the wall still (a per-panel colour is a still image by definition).
- **Freeze** isn't available for messages, effects or things that are already still.
- The panels never report their own per-panel colours, or the name of anything made
  here (they just call it `*Dynamic*` or `*Static*`). The page remembers what *it* sent
  (in `ui_state.json`), so paintings, messages and effects keep their name and preview
  after a reload. As soon as the wall shows one of its own scenes or a plain colour, that
  memory is cleared. If the wall was set from somewhere else, the preview says so and
  shows a neutral grey until you pick a scene.
- Saved scenes live in `scenes.json` next to the server, not on the device, so they don't
  show up in the Nanoleaf app.

---

## Command line

```bash
./nl.py state                              # power, brightness, current scene
./nl.py on                                 # or: off
./nl.py bright 40                          # 0-100
./nl.py scenes                             # list scenes, * marks current
./nl.py scene "Northern Lights"            # play it (animated)
./nl.py freeze "Cocoa Beach"               # same colours, no motion
./nl.py color "#ff8800"                    # solid colour everywhere
./nl.py panels                             # panel ids + positions
./nl.py paint 51229="#00d4ff" --base "Cocoa Beach"
./nl.py say "I <3 YOU"                     # spell it out, one character at a time
./nl.py say "I ❤ U" --color "#ffb6c1" --hold 3
./nl.py say "YOU" --bg "#1a0308" --gap 1   # dim red background, longer blank between letters
./nl.py say --preview letters.svg "YOU"    # picture of each character, nothing sent
./nl.py letters                            # which characters the wall can draw
./nl.py raw GET /                          # any request straight to the device API
./nl.py raw PUT /state '{"ct":{"value":2700}}'
./nl.py --help                             # everything
```

**About `paint`:** a static write has to specify *every* panel, so the panels you don't
list still need a colour. `--base SCENE` fills them from that scene's palette; without it
they go black.

`nl.py` talks to the panels directly (it doesn't need the server running) and keeps its
own 0.6 s gap between writes. It reads `token.txt` and `device.json` from **this**
folder only — not the app's data folder — so if the app's Reconnect found a new address
or token, set `NANOLEAF_IP` / `NANOLEAF_TOKEN` for `nl.py` too.

---

## Effects

Effects are animations made for this wall's exact layout and sent to the controller as
one looping custom animation, so they keep playing with the app closed (like messages).
They're in `effects.py`; each one gives every panel its own list of keyframes.

| Effect | What it does |
|---|---|
| 🐍 Snake | A long round of the game (about 55 s). The snake follows a route round the wall; an apple sits a few panels ahead on a panel that hasn't had one yet, so by the end the apple has been on every panel. Lime head, fading green body, red apples; it grows per apple (up to 7 long) and shrinks back at the end of the round. |
| ✨ Starlight | Random panels twinkle in and fade out, white and ice blue (Razer-style). |
| 🧚 Fairy Dust | Starlight in pastel pink and lilac. |
| 🫧 Ripple | Rings spread out from the centre hexagon every 3 s, alternating colours. |
| 🎯 Ripple In | Ripple in reverse: the rings start at the outermost panels and close in on the centre. |
| 🌧️ Rain | Drops run down the wall's columns over a dark navy base. |
| 🌈 Wave | A rainbow sweeps left to right. |
| 💓 Heartbeat | The heart from the message beats lub-dub. |

### Ambient

Slow, calm looks, in their own **Ambient** section. Like the effects they're one looping
animation, so they keep going with the app closed. The last three are worked out from
today's date when you start them (start them again tomorrow to update).

| Look | What it does |
|---|---|
| 🔥 Fireplace | Every panel flickers on its own: bright orange at the bottom of the wall, dim red embers at the top. |
| ⛈️ Storm | Dark clouds roll left to right; now and then lightning forks through two or three neighbouring panels (never the whole wall). |
| 🌊 Ocean Waves | Waves roll across the wall: deep blue troughs, teal swells, a pale foam crest. |
| 🌌 Northern Lights | Green and teal curtains drift across a dark sky, with violet at the top. |
| 🫠 Lava Lamp | Three warm blobs rise slowly through dark red wax and sink back. |
| 🌠 Night Sky | Faint stars twinkle slowly on deep blue; once a loop a shooting star crosses the top. |
| 🫁 Breathe 4-7-8 | A breathing guide: the wall fills from the bottom for 4 s (breathe in), holds for 7 s, and drains from the top for 8 s (breathe out). |
| 🌙 Moon Phase | A night light shaped like tonight's moon: the lit side of the wall follows the real phase (waxing lights the right, waning the left). At new moon it's almost dark. The card says the phase. |
| 🗓️ Colour of the Day | One colour per weekday (Monday red, Tuesday orange … Sunday violet), breathing slowly. |
| 📅 Holiday Countdown | Fills up from the bottom as the next holiday gets closer, counting from the last one (New Year, Valentine's Day, Easter, Halloween, Bonfire Night, Christmas), in that holiday's colours; on the day the whole wall twinkles. The card says how many days are left. |

### Arcade

Retro games the wall plays by itself, each as one looping round, built from your wall's
layout like the effects above (so they keep playing with the app closed). They're in their
own **Arcade** section on the Scenes tab and can be favourited like any other card.

| Game | What it does |
|---|---|
| 🟡 Pac-Man | Every panel starts with a peach pellet. Pac-Man eats his way round Snake's route with the red ghost a few panels behind, eaten panels turning to dark-blue maze. The panel furthest from the start holds the big power pellet: the ghost turns blue and runs, Pac-Man turns round and eats it, then clears the board. The pellets fade back in for the next round (about 15 s). |
| 🧱 Tetris | Blocks in the seven Tetris colours fall down the wall's columns and stack from the bottom. A full band of panels flashes and clears, and what's above drops down. After a while the stack reaches the top band and the grey game-over curtain comes down (about 26 s). |
| 🏓 Pong | A blue paddle on the left of the wall and a red one on the right, each moving between two spots, and a white ball that speeds up. The paddle flashes pale when it hits; each rally ends with a miss and the wall glows in the scorer's colour. One point each, then it starts again (about 27 s). |
| 🔴 Simon | The wall splits into four dim zones: green, red, blue and yellow. Simon plays a sequence that grows by one every round and the player repeats it a little quicker; after five rounds the zones spin round in a victory lap (about 31 s). |
| 🏍️ Light Cycles | Tron: a cyan bike and an orange bike start far apart and race over the wall leaving light trails, each steering for open space. The first one boxed in flares and de-rezzes; the winner's trail glows. Three rounds from different starts (about 16 s). |
| 🧬 Game of Life | Cells live and die on the panels themselves (neighbours = panels that touch). Panels only have one to three neighbours, so the rules are tuned for that: born next to one or two live panels, survives with exactly two. Newborns are cyan and age to green and blue; when a colony dies out or repeats, a new one starts (about 22 s). |
| 🟥 Breakout | Rainbow bricks along the top of the wall, a cyan paddle along the bottom. The ball knocks out the first brick in its way and comes back; the paddle slides to meet it. When the wall's cleared the bricks come back (about 20 s). |
| 👾 Space Invaders | A wave of green invaders across the top pulses as it marches; the cannon at the bottom moves and fires up the wall, invaders flash orange when hit, and red bombs fall and miss (about 13 s). |
| 🐤 Flappy | A yellow bird on autopilot in a column on the left; green pipes with a gap slide in from the right and it hops up or down to get through. After six pipes it misses one, turns red and drops (about 11 s). Needs a few columns of two or more panels. |
| ⭕ Noughts & Crosses | Two computer players on nine panels (the hexagons on a 9-hexagon wall). Red plays perfectly; blue sometimes slips up, so you see wins and draws. The other panels glow faintly in the colour of whoever's turn it is; a winning line flashes. Three games. |
| 💡 Lights Out | The wall solves its own puzzle: pressing a panel flips it and its neighbours. It works out which panels to press (linear algebra over the wall's layout), shows each press in cyan, and every panel ends up off. Three puzzles. |
| 🌀 Maze | A digger carves a maze through every panel (a random depth-first search, backing up at dead ends), then the route from the green start to the farthest panel lights up gold. |
| 🎲 Dice | The wall tumbles and lands on a number from 1 to 6, shown as white pips on the little triangles over a dark red die; six rolls. |
| 🪙 Coin Toss | Gold and silver spin across the wall, slowing down until it lands heads (gold) or tails (silver). |

## Timers and the schedule

The **Timers** tab. One timer runs at a time; it shows under *Now playing* with what's left
and a **■ Stop** button. The computer running NanoManager runs them, so they keep going with
the page closed, but the computer has to stay awake.

| Timer | What it does | Stops when |
|---|---|---|
| 🌅 Sunrise alarm | Switches the panels on at 1% deep red and over 10–45 minutes brightens through orange and warm white to 100% daylight. | you pick a scene or change the brightness, or switch off |
| 😴 Sleep timer | Fades whatever's playing down to nothing over 10–60 minutes, then switches the panels off. Next time they're switched on (from the page, a link or the schedule) the brightness goes back to where it was. | you turn the brightness up or switch off |
| 🍅 Pomodoro | 25 minutes of focus (or 50 or 15) with the wall in tomato red; the panels go dark one by one from the top as time runs out. A soft chime of pulses starts each part, then a 5-minute green break that drains the same way, then the next round. | you pick a scene, or switch off |
| 🎞️ Slideshow | Plays your favourites (or all the moods) one after another every 2–30 minutes, with a slow 5-second fade between still ones. | you pick something else, or switch off |

**Schedule.** Add entries like *07:00 on weekdays → Sunrise alarm (30 min)*, *sunset − 30 min →
Fireplace*, or *23:30 every day → Switch off*. An entry can play any scene, mood, effect or
favourite, switch the panels on or off, start a timer, or play **🍂 Mood of the season**
(Christmas in December, Halloween late October, Love early February, Ice in the winter,
Cherry Blossom in spring, Seafoam in summer, Honey in September, Fireside in autumn). Pick the
days with the chips (or *Every day*, *Weekdays*, *Weekends*); untick **On** to pause an entry.
Each entry fires once, within five minutes of its time: if the computer was asleep then, it
doesn't catch up later.

*At sunrise / at sunset* needs the wall's location: type its latitude and longitude (decimal
degrees, e.g. 51.51 and -0.13 for London) under the schedule. NanoManager works the times out
itself; nothing is looked up online.

## Links for Shortcuts, Siri and NFC tags

**⚙ Settings → Shortcuts, Siri & NFC tags** lists links like
`http://192.168.1.20:8765/run/Ab12Cd34Ef56?key=mood:Cozy`. Opening one does the thing straight
away and shows a ✓ page. Ways to use them:

- **Shortcuts / Siri:** a shortcut with a *Get contents of URL* action (it runs quietly) or *Open
  URLs*. Name the shortcut "Movie mode" and say "Hey Siri, movie mode".
- **Coming home:** a Shortcuts *personal automation* (*Arrive* at home) that runs that shortcut.
- **NFC tags:** write the link to a tag (e.g. with the NFC Tools app); tap the tag with the phone.
  Or a Shortcuts automation on *NFC* for no browser at all.
- **Home Screen bookmark:** open the link in Safari, then *Add to Home Screen*.

What a link can say: `key=` any scene key (`mood:Cozy`, `fx:aurora`, `device:Northern Lights`,
`mine:My painting`, `auto:season`) or `scene=` just a name; `power=on|off|toggle`;
`bright=1..100`; `next=1` / `prev=1` (favourites); `routine=sunrise|sleep|pomodoro|slideshow`
with `minutes=`; `stop=1`. Add `format=json` for a JSON answer instead of the page.

The long code in the middle is a secret, so another web page can't switch your lights through
your browser. Anyone who has a link can use it (even with a PIN set), so keep them to yourself;
**Make new links** (on the computer) makes new ones and stops the old ones working.

## PIN lock

**⚙ Settings → Lock** on the computer: set a PIN of 4–12 digits and every phone (anything
that isn't the computer itself) gets a PIN screen first; after the right PIN it stays signed in.
The computer running NanoManager never asks. Five wrong tries from one phone means a minute's
wait. Changing or removing the PIN signs every phone out. The PIN can only be set or removed
on the computer. Links from the section above keep working without it.

### 🎮 Play Simon (a real game, played by swiping on the panels)

**Play Simon**, the first card under Arcade, is a game you play yourself:

1. The wall splits into four dim colour zones: green, red, blue and yellow (the same zones as the Simon demo).
   Each zone has a direction, roughly where it sits on the wall. On the wall it was made for: **↑ green, → red,
   ↓ blue, ← yellow**. The app shows the arrows on its picture of the wall and in a legend.
2. **Watch:** Simon lights a zone. **Copy it** by swiping on the wall in that zone's direction (anywhere on the
   wall: a short, quick swipe across two panels works best).
3. Every round Simon replays the whole sequence plus **one new random colour**, and it speeds up as it gets longer.
4. It goes on until you slip: a wrong direction, or more than 8 seconds without a swipe. The whole wall then
   **flashes red** three times and lights the zone you should have picked. Beat your best and it celebrates with a
   flash in all four colours.
5. The dim board stays up afterwards: **swipe on the wall to play again**, so you don't need the phone or computer
   in your hand.

While a game is on, the Now Playing card shows your **Score** (rounds completed) and your **Best**, which is saved
(`games.json` in the data folder) and kept across restarts and updates. The Arcade heading shows your best too.
You can also play in the app (or on your phone): click or tap the zones on the wall picture. **↻ New game** starts
again from round 1, and picking any other scene ends the game.

**Why swipes and not taps?** The panels' local API never reports taps, holds or which panel was touched. That was
checked on a Shapes wall on firmware 7.1.6, and other people report the same. It only reports swipe *directions*,
about half a second late. So everything you do on the wall is a swipe.

- Swipes reach NanoManager from the panels over your Wi-Fi, so the computer running NanoManager must be on (the
  Mac app open, or the Windows launcher running). The TV app doesn't have it.
- Each round is sent to the controller as **one** animation and each correct swipe as one short flash, all through
  the usual rate limit.
- Swipes less than 0.8 s apart count once: the wall often reports a swipe and then a quick "echo" in the opposite
  direction, and the echo is ignored. Now and then the wall misses a swipe or misreads it; just swipe again.
- **Swipes coming out the wrong way round?** The app shows the last swipe it received ("Last swipe: ↑"). If that
  isn't the way you swiped, press **↻ turn them** next to it (each press turns every swipe a quarter turn) until it
  matches. It's remembered (`touch.json` in the data folder).
- If swiping also changes the scene or brightness, those are the wall's own *touch actions* set in the Nanoleaf app.
  NanoManager puts the game board straight back, but turning those actions off in the Nanoleaf app makes it smoother.

### 🛠 Debug mode (a remote control on the wall)

Step through your scenes from the wall itself, without the app:

| On the wall | What it does |
|---|---|
| **Swipe down, up, down** (each within 8 s of the last) | Debug mode on: whatever was playing stops |
| **Swipe right / left** | Next / previous scene |
| **Swipe up** | Switch between your **Favourites** (the default) and **All** scenes |
| **Swipe down** | Debug mode off: the scene you're on keeps playing normally, on the whole wall |

While debug mode is on, four panels at the bottom of the wall stay lit whatever scene is showing, as a reminder:

- the little triangle beside the lowest hexagon (white): debug mode is on;
- that hexagon: **red** while you're stepping through Favourites, **green** for All;
- the two triangles under it (blue): previous and next.

It starts on the scene that was playing, if it's in the list, or else the first one. With no favourites yet it
starts on All. Play Simon and Replicate are left out of the list.

The panels' own scenes and the moving moods are drawn by the controller across *every* panel, so they can't keep the
four lit panels on top of them. In debug mode they show as an animation of their colours. When you switch debug
mode off, the real scene plays.

The app shows debug mode on its Now Playing card ("Favourites · 2 of 6 · 🐍 Snake") with **◀ Previous**,
**Next ▶**, **♥ Favourites / ✱ All** and **✓ Done** buttons that do the same as the swipes. Picking any scene in the
app (or the Nanoleaf app) also ends debug mode. The down-up-down pattern isn't recognised while Play Simon is
waiting for your move, because those swipes are game moves. If the panels are switched off, debug mode ends
(and NanoManager never switches them back on by itself).

On another wall the four panels are picked automatically: the lowest-left panel that sticks out, the panel next to
it, and the two panels nearest that one.

### 🖥️ Replicate (your screen's mood on the wall)

Replicate makes the wall copy the colours of whatever is on your Mac's main screen,
in the same places: the top of the wall takes the top of the screen, the left arm
takes the left side, and so on. It's live, so change what's on screen and the wall
follows within a second or two, fading gently.

- **It needs the NanoManager Mac app open**, because the app is what looks at the screen.
  You can still switch it on from your phone while the Mac app is running.
- **The first time**, macOS asks for permission. Allow it in System Settings ›
  Privacy & Security › Screen & System Audio Recording (turn NanoManager on), then quit and
  reopen NanoManager. If it isn't allowed, the Now Playing card says so. The build script
  signs the app with a certificate kept in your keychain ("NanoManager Local Signing"),
  so the permission sticks when the app is rebuilt.
- While it runs, macOS shows its purple screen-recording icon in the menu bar. That's expected.
- **It's light on your Mac.** It never takes a real screenshot: macOS shrinks the screen to a
  32×20-pixel thumbnail on the graphics chip, at most once a second, and only when something
  on screen changed. NanoManager's own window is left out. When Replicate is off, nothing is captured.
- **It's gentle on the panels.** They get at most one update a second, and none at all while
  the screen stays still.
- Colours follow the *mood*: bright, colourful bits count for more than white or grey, so a
  colourful picture on a white page still tints the wall. A dark screen means a dim wall.
- It stops as soon as you pick anything else (or pick a scene in the Nanoleaf app). Unlike the
  other effects, it doesn't keep going after you quit the Mac app. The wall just holds the last colours.

To add one: write a function in `effects.py` that returns `{panelId: [(rgb, tenths), …]}`
with the same total for every panel, register it in `EFFECTS` (with a label, icon,
description and colours; add `"group": "game"` to put it under Arcade), and it appears on the Scenes tab. Helpers there: `adjacency`
(which panels touch), `euler_tour` (a route round the wall), `bfs_dist` (hops from a
panel), `bfs_path` (the shortest route between two panels), `columns` / `rows` (the wall
sliced vertically / horizontally), `events_to_frames` (sparse flashes on a dark base), `grid_to_panels`
(frame-by-frame designs). Rebuild the app afterwards.

## Spelling messages

The wall is 9 hexagons and 10 mini triangles in a branching shape, so it can't show a
whole word at once. Instead it spells: each character is drawn by lighting some panels
(the others go off, or to a background colour), held for a couple of seconds, then the
next one fades in. `I ❤ YOU` is seven steps (the spaces are short pauses) and loops
every 20 s. The heart beats while it's up.

The whole loop is sent to the controller as **one** custom animation, so the panels play
it by themselves until you choose something else — the page and the server can be
closed and it keeps going. That's also why it's safe under the rate limit: one write.

Characters the wall can draw: `I ♥ Y O U V L 1`, `*` (every panel at once, for a flash)
and space. Type `<3`, `❤️`, `♥` or any heart emoji for the heart. Lower case works.
Anything else (E, for one) is refused with a list of what works — so "I LOVE YOU" can't
be spelled, but `I ❤ YOU`, `I ❤ U` and `YOU` all can.

Defaults: white letters, red heart, other panels off, each character holds 2 s with a
0.5 s blank after it.

The letters stay small and in the middle of the wall on purpose: the wall itself is one
big Y shape, so a letter drawn across all of it just looks like a Y with bits missing.
Each character also **draws itself stroke by stroke** before it holds (the I sweeps top
to bottom, the U goes down one arm and up the other, the O sweeps around its dark
centre), which makes the shapes much easier to read.

Which panels form each character is in **`glyphs.json`**: each character is a list of
strokes, each stroke a list of panel ids (`./nl.py panels` prints them, and the wall
picture in the page shows each id when you hover). The `aliases` section maps things you
can type (like `<3`) to a character. Edit it to change a letter or add new ones; the page
picks the change up on the next preview, and `./nl.py say --preview out.svg TEXT` writes a
picture so you can check without touching the wall.

---

## From your own code

The device speaks plain HTTP + JSON. Base URL:

```
http://<PANEL-IP>:16021/api/v1/<TOKEN>
```

The token is in `token.txt` (or `device.json`, if Reconnect has re-paired).

### curl

```bash
TOKEN=$(cat token.txt)
API="http://<PANEL-IP>:16021/api/v1/$TOKEN"

curl -s "$API/" | python3 -m json.tool          # everything
curl -X PUT "$API/state"   -d '{"on":{"value":true}}'
curl -X PUT "$API/state"   -d '{"brightness":{"value":40}}'
curl -X PUT "$API/state"   -d '{"hue":{"value":220},"sat":{"value":80}}'
curl -X PUT "$API/effects" -d '{"select":"Northern Lights"}'
```

### Python

```python
import json, urllib.request

API = "http://<PANEL-IP>:16021/api/v1/" + open("token.txt").read().strip()

def put(path, body):
    req = urllib.request.Request(API + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="PUT")
    urllib.request.urlopen(req, timeout=8)

put("/state", {"brightness": {"value": 60}})
put("/effects", {"select": "Jungle"})
```

### Through the local proxy (recommended for anything automated)

While the app or `start.sh` is running, everything goes through `http://127.0.0.1:8765`,
where writes are rate limited and circuit broken for you:

```bash
curl -s  http://127.0.0.1:8765/api/state          # live state + what the page last wrote
curl -N  http://127.0.0.1:8765/api/events         # server-sent events, one per change
curl -X PUT http://127.0.0.1:8765/api/state  -d '{"brightness":{"value":30}}'
curl -X PUT http://127.0.0.1:8765/api/effect -d '{"select":"Prism"}'
curl -X PUT http://127.0.0.1:8765/api/fx     -d '{"name":"starlight"}'
curl -X PUT http://127.0.0.1:8765/api/message -d '{"text":"I <3 YOU","hold":2.5}'
curl -X PUT http://127.0.0.1:8765/api/message -d '{"text":"YOU","preview":true}'   # nothing sent
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the control page |
| GET | `/api/state` | snapshot: `online`, `paused`, `pausedFor`, `lastError`, `device` (the device's full `GET /`), `deviceIp`, `reconnect`, `ui` (what the page last wrote), `favorites`, `replicate` (`active`, `capturing`, `error`, `writes`), `simon` (Play Simon: `active`, `phase`, `score`, `best`, `round`, `step`, zones, directions and board colours), `debug` (debug mode: `active`, `list`, `index`, `count`, `key`, `label`, `panels`), `touch` (last swipe: `dir`, `at`, `n`, `rotate`), `routine` (the running timer: `active`, `kind`, `label`, `phase`, `started`, `ends`, `round`, `now`), `settings` (`fade`, `lat`, `lon`, `pin`) |
| GET | `/api/events` | server-sent events: the same snapshot on connect and after every change |
| GET | `/api/health` | fresh check: `online`, `paused`, `pausedFor`, `lastError` |
| GET | `/api/palettes` | colours + motion type of the 16 device scenes (cached in `palettes.json`) |
| GET | `/api/effects` | the effects list (name, label, icon, description, colours) |
| GET | `/api/glyphs` | `glyphs.json` |
| GET | `/api/scenes` | your saved scenes |
| PUT | `/api/scenes` | save a scene (`{"name":…, "kind":…}`; same name replaces it) |
| DELETE | `/api/scenes?name=NAME` | delete a saved scene (and its favourite) |
| GET | `/api/favorites` | hearted scenes as `kind:name` keys — `device:Northern Lights`, `fx:snake`, `mood:Cozy`, `mine:My painting` — in the order they were added |
| PUT | `/api/favorites` | `{"key":"mood:Cozy","on":true}` to add, `"on":false` to remove; `{"order":[…]}` puts the same keys in a new order; returns the new list |
| GET / PUT | `/api/routine` | the running timer; `{"kind":"sunrise","minutes":30}`, `{"kind":"sleep","minutes":20}`, `{"kind":"pomodoro","minutes":25,"break":5}`, `{"kind":"slideshow","minutes":10,"list":"favourites"\|"moods"}`, or `{"kind":"stop"}` |
| GET | `/api/schedule` | `items` (each with `desc` and `next`), `lat`, `lon`, today's `sunrise` / `sunset` |
| PUT | `/api/schedule` | `{"item":{"at":"07:00"\|"sunrise"\|"sunset","offset":-30,"days":[0,1,2,3,4],"action":{…},"on":true}}`; `days` 0 = Monday; `action` is `{"key":"mood:Cozy"}`, `{"power":"on"\|"off"}` or `{"routine":"sleep","minutes":30}`; with an `id` it replaces that entry |
| DELETE | `/api/schedule?id=ID` | remove a schedule entry |
| GET / PUT | `/api/settings` | `fade` (tenths of a second), `lat`, `lon`; GET also answers `local`, `runToken`, `phoneUrl` |
| PUT | `/api/pin` | `{"pin":"1234"}` signs a phone in (sets a cookie); `{"set":"1234"}` / `{"clear":true}` only from the computer itself |
| GET | `/api/qr.svg?text=…` | a QR code (SVG) for up to 213 bytes of text |
| GET | `/run/<token>?…` | the Shortcuts / NFC links (see [above](#links-for-shortcuts-siri-and-nfc-tags)) |
| PUT | `/api/state` | passed to the device's `/state` |
| PUT | `/api/effect` | passed to the device's `/effects` |
| PUT | `/api/fx` | play an effect: `{"name":"snake"}`; add `"preview":true` to get its frames without sending. `{"name":"replicate"}` starts Replicate, `{"name":"simon_play"}` starts a game of Simon |
| PUT | `/api/debug` | debug mode: `{"action":"enter"}`, then `prev`, `next`, `toggle` (Favourites/All), `exit` (play the scene for real); answers the status (also in every snapshot as `debug`) |
| PUT | `/api/touch` | `{"rotate":90}` turns every swipe by that many degrees (`null` = follow the wall's orientation); the last swipe is in every snapshot as `touch` |
| PUT | `/api/simon` | Play Simon: `{"tap":51229}` touches a panel (as if on the wall), `{"action":"new"}` starts a new game; answers the game status (also in every snapshot as `simon`: `phase`, `score`, `best`, `round`, `step`, …) |
| GET | `/api/replicate` | Replicate status plus the thumbnail size the Mac app should capture (`w`, `h`) |
| PUT | `/api/replicate/frame` | from the Mac app: `{"w","h","px"}` (px = hex RGB, 6 characters a pixel); answers `{"active":…}` |
| PUT | `/api/replicate/status` | from the Mac app: `{"error":"…"}` when it can't capture (shown on the page) |
| PUT | `/api/message` | spell text: `{"text", "color", "heart", "bg", "hold", "gap", "name"}` (all but `text` optional); `"preview":true` to only preview |
| PUT | `/api/reconnect` | look for the panels again: `{"pair":false}`; `{"pair":true}` after holding the power button |

`/api/state` and `/api/effect` also accept an optional `"_ui":{"sceneName":"…","panels":{"51229":"#ff0000",…}}`
alongside the device body. It's removed before the request reaches the panels and saved
so the page can show the right name and colours. Error answers: `503` with
`"error":"paused"` while the breaker is open, `502` when the panels can't be reached.

### Useful device endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | full state, scene list, panel layout |
| GET | `/events?id=1,3` | server-sent events for state and effect changes |
| PUT | `/state` | `on`, `brightness`, `hue`, `sat`, `ct` |
| PUT | `/effects` | `{"select":"NAME"}` to play a scene |
| PUT | `/effects` | `{"write":{"command":"request","animName":"NAME"}}` to read a scene's palette |
| PUT | `/effects` | `{"write":{"command":"display","version":"2.0","animType":"static","animData":"...","loop":false,"palette":[]}}` per-panel colours |
| PUT | `/effects` | `{"write":{"command":"display","version":"2.0","animType":"flow","colorType":"HSB","palette":[{"hue":200,"saturation":100,"brightness":100},…],"transTime":{"minValue":14,"maxValue":28},"delayTime":{"minValue":14,"maxValue":28},"loop":true}}` a custom animation |
| PUT | `/effects` | `{"write":{"command":"display","version":"2.0","animType":"custom","animData":"...","loop":true,"palette":[]}}` per-panel keyframes (how messages and effects are sent) |
| POST | `/api/v1/new` (no token) | get a new token while the controller is in pairing mode |

Static `animData` format: panel count, then per panel `id 1 R G B W transitionTime`
(W is always 0; time is in hundredths of a second).

Custom `animData` format: panel count, then per panel `id frameCount` followed by
`R G B W T` for each frame (T in tenths of a second to fade to that colour). Every panel's
times must add up to the same total, or the loop drifts. The controller has
definitely accepted a 310-frame, 4.3 KB animation. Snake is much bigger (about 1,250
frames, 16 KB), so if it ever fails when the others work, size is the likely reason.

Custom animations accept `animType` of `flow` (add `"flowFactor":2.5`), `wheel`, `random`,
`fade`, `highlight` or `custom`. `transTime` / `delayTime` are in tenths of a second. The
device reports these as `*Dynamic*` (or `*Static*` for per-panel writes) — it does not
keep a name.

> `version:"2.0"` is **required** on firmware 7.x. Without it the device rejects the write
> with HTTP 400.

Other answers you might see: `401` = wrong or expired token, `403` from `/api/v1/new` =
the controller isn't in pairing mode.

---

## ⚠️ Don't write too fast

**The controller crashes if you hammer it.** Pushing a full 19-panel effect on every
click took it off the network entirely — it stopped answering ping and needed the power
adapter unplugged for ~10 seconds.

Keep **at least 0.6 seconds** between writes and only one request in flight. The web
panel and `nl.py` already do this; if you write your own script against the device
directly, add the delay yourself, or go through the proxy on port 8765, which enforces it.

What the proxy does: one write at a time, at least 0.6 s apart. If 3 writes in a row fail
to reach the panels it stops writing for 20 seconds (the page shows a *paused* banner) so
the controller can recover. Reading state is cheap and never trips this. It also
re-reads the state every 20 s as a safety net, in case an event was missed.

---

## Reconnecting (new address, or the panels forgot the pairing)

When the page can't reach the panels, a panel appears at the top with a **Reconnect**
button. It also keeps looking by itself about once a minute (it never re-pairs by itself,
because that needs you to press the button). Reconnect does this:

1. Tries the last known address.
2. If nothing answers, scans every device on your network for one answering on the
   Nanoleaf port (takes a few seconds). So a **new IP address is found automatically**
   and remembered.
3. If the panels answer but refuse the saved pairing (after a factory reset, say), it
   says so and shows the fix: **hold the power button on the controller for 5–7 seconds
   until the lights flash white**, then click **Reconnect** within 30 seconds. The page
   then polls the panels until they hand over a new pairing token (it waits up to 90 s),
   saves it, and carries on.

What it learns goes in `device.json` in the data folder (`~/Library/Application
Support/NanoManager` for the app, this folder for `start.sh`), and from then on that
beats `NANOLEAF_IP`, `NANOLEAF_TOKEN` and `token.txt`. Delete `device.json` to go back
to those.

## Troubleshooting

**Panels unresponsive / page shows "offline"** — unplug the controller's power adapter for
~10 seconds and plug it back in. Your token and scenes survive this.

**Page says "paused"** — writes failed three times in a row, so the server is giving the
controller 20 seconds to recover. Wait it out; if it keeps happening, power-cycle as above.

**"No token found"** — `token.txt` is missing. Easiest: click **Reconnect** and follow the
steps. By hand: hold the controller's power button 5–7 seconds until the LED flashes,
then within 30 seconds:

```bash
curl -X POST http://<PANEL-IP>:16021/api/v1/new
```

Put the returned `auth_token` into `token.txt`. Pairing does **not** reset the panels or
disconnect the Nanoleaf app or HomeKit. A token keeps working through reboots and power
cuts; only a factory reset kills it.

**Panels moved to a new IP** — Reconnect finds them by itself. For `nl.py`, find it and
set `NANOLEAF_IP`:

```bash
dns-sd -G v4 <your-panel-name>.local
```

```bash
export NANOLEAF_IP=192.168.1.x
```

**Scene colours look wrong after editing scenes in the app** — delete `palettes.json`; it
rebuilds on next load (takes ~15 seconds).

**Header says "polling" instead of "live"** — the browser lost the event stream; it
reconnects on its own. Nothing is broken, updates just take up to 5 seconds.

**An edit here doesn't show up in NanoManager** — the app runs its own copy. Run
`app/build_app.sh`.

**NanoManager won't quit, or the build script hangs at "installing"** — force it:

```bash
pkill -9 NanoManager
```

## Files

| File | Purpose |
|---|---|
| `nanoleaf_server.py` | Local server, rate-limiting proxy, live state feed, reconnect |
| `nanoleaf.html` | The control page (moods are the `PRESETS` list inside it) |
| `mobile/` | Phone layout, icons and manifest for the Home Screen app |
| `nl.py` | Command line tool |
| `message.py`, `glyphs.json` | The message spelling animation, and which panels light up for each character |
| `effects.py` | Snake, Starlight, Ripple, Rain, Wave... and the Arcade games, built from your wall's layout |
| `replicate.py` | Screen-mood mapping for Replicate (the capture itself is in the Mac app) |
| `simon.py` | Play Simon: the game's rules and the animations it sends (the server runs it) |
| `remote.py` | Debug mode: which scenes to step through, how each is shown with the four lit panels, and how it's played for real |
| `routines.py` | Timers and the schedule: sunrise colours, Pomodoro panels, sunrise/sunset times, when an entry fires |
| `qr.py` | A small QR code maker for the phone page's address |
| `app/` | The Mac app (Swift) and its build script |
| `windows/` | The Windows launcher and zip builder |
| `firetv/` | The Fire TV / Android TV app and its build script |
| `scripts/` | One-line installers |

Your own data (never committed): `token.txt`/`device.json` (pairing), `scenes.json`, `favorites.json`, `games.json` (Simon high score), `touch.json` (swipe direction fix-up),
`ui_state.json`, `palettes.json`, `settings.json` (crossfade, location, the links' secret, the PIN's hash and signed-in phones), `schedules.json`, `server.log`. The Mac app keeps them in
`~/Library/Application Support/NanoManager`, the Windows launcher in `%APPDATA%\NanoManager`, and
running from source keeps them next to the script (or wherever `NANOLEAF_DATA_DIR` points).

Settings via environment variables (all optional):

| Variable | Default | What it sets |
|---|---|---|
| `NANOLEAF_IP` | found automatically | Panels' address |
| `NANOLEAF_PORT` | `16021` | Panels' API port |
| `NANOLEAF_TOKEN` | contents of `token.txt` | Auth token |
| `NANOLEAF_UI_PORT` | `8765` | Port the control page is served on |
| `NANOLEAF_LISTEN` | `127.0.0.1` | `0.0.0.0` lets phones on your Wi-Fi open the page (the Mac app and "phone access" on Windows do this) |
| `NANOLEAF_DATA_DIR` | next to the script | Where the server keeps token, scenes, state and `device.json` |
| `NANOLEAF_PAIR_WINDOW` | `90` | Seconds Reconnect waits for you to hold the power button |

`nl.py` uses `NANOLEAF_IP`, `NANOLEAF_PORT` and `NANOLEAF_TOKEN` only.

## Messages and other layouts

The letters in `glyphs.json` are lists of **panel ids**, and panel ids belong to one particular set of
panels. They were drawn for a Shapes wall of 9 hexagons and 10 mini triangles, so on any other layout
the Message tab hides itself (and the TV app has no Messages). To make messages work on your wall:
run `./nl.py panels` to see your ids and positions, then redraw the strokes in `glyphs.json` and check
them with `./nl.py say --preview out.svg "I <3 U"`. The Heartbeat effect is hidden for the same reason.
All the other effects are built from the layout your panels report, but have only been tried on that
one Shapes wall: if one looks wrong on your shape, please open an issue.
