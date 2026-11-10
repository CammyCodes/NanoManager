# NanoManager ideas

Backlog of feature ideas for the NanoManager Nanoleaf controller. Kept ideas are grouped by area.
Playable games are dropped on purpose: only **watch-only** game ideas (no player input) are kept.
Data-driven ideas are parked for later.

Status tags: `idea` (not started), `parked` (later), `watch-only` (game that runs on its own),
`done` (built in 1.3, 2026-11-10, tested offline against a fake controller; not yet played on the wall),
`exists` (was already in the app), `partly` (covered another way, see the note).

---

## 1. Ambient and moods

1. Sunrise alarm that ramps up over 30 minutes — `done`: Timers tab, 10–45 min, and in the schedule
2. Sleep fade-out timer — `done`: Timers tab; brightness comes back on the next switch-on
3. Pomodoro: panels drain colour as the timer runs — `done`: Timers tab, 25+5 / 50+10 / 15+3
4. Weather mood from the local forecast — `parked`: needs an online forecast
5. Moon-phase night light — `done`: Ambient → Moon Phase (worked out locally)
6. Storm mode with random lightning flashes — `done`: Ambient → Storm
7. Per-panel flickering fireplace — `done`: Ambient → Fireplace
8. Ocean waves on a tide schedule — `partly`: Ambient → Ocean Waves; the tide schedule needs tide data (`parked`)
9. Northern lights — `done`: Ambient → Northern Lights
10. Lava lamp blobs — `done`: Ambient → Lava Lamp
11. Starfield twinkle — `done`: Ambient → Night Sky
12. Breathing guide (4-7-8) — `done`: Ambient → Breathe 4-7-8
13. Colours that track the real local sunset — `done`: schedule entries at sunrise/sunset ± offset (location typed in; computed locally)
14. Seasonal auto-mood — `done`: 🍂 Mood of the season (schedule, links)
15. Holiday countdown bar filling the panels — `done`: Ambient → Holiday Countdown
16. Weekly colour rainbow, one colour per day — `done`: Ambient → Colour of the Day
17. Pet-calm mode — `done`: Pet Calm mood (35%)
18. Night-feed nursery light, dim red — `done`: Night Feed mood (8%)
19. Focus mode: one colour, no motion — `done`: Focus mood (Deep Focus already existed)
20. Slow cinematic scene-to-scene fades — `done`: Slideshow timer + Crossfade setting (still scenes only: the panels' own animated scenes switch instantly)

## 2. Control UX

1. iOS home-screen widget — `idea`: needs the native iOS app (Xcode)
2. Apple Watch complication — `partly`: a Shortcut with a /run link runs on the Watch; a real complication needs the native app
3. Shortcuts app actions — `done`: /run links (Settings → Shortcuts, Siri & NFC tags)
4. Siri phrase: "movie mode" — `done`: a Shortcut named "Movie mode" with a /run link
5. Geofence: lights come on when you get home — `done`: Shortcuts *Arrive* automation + a /run link
6. NFC tag scans to trigger a scene — `done`: write a /run link to the tag
7. Phone-side swipe to change scenes — `done`: swipe across the wall preview
8. Long-press to reorder favourites — `done`: drag (mouse) / long-press then drag (touch)
9. Scene scheduler — `done`: Timers → Schedule
10. Adjustable crossfade time — `done`: Settings → Crossfade (still scenes)
11. Multi-wall groups — `idea`: needs a second wall to build and test against
12. On-device voice control — `partly`: Siri via Shortcuts
13. Menu-bar quick toggle on the Mac — `idea`: Swift change, not done this round
14. Keyboard shortcuts for every tab — `done`: 1–6, [ ], Z, F, P, S, `,`, ?
15. Undo history across scenes — `done`: ↶ Back / Z

## 3. Mobile and app

1. Installable PWA with an offline shell — `parked`: service workers need HTTPS; the page is plain http on the LAN
2. Native iOS wrapper using the existing WKWebView setup — `idea`: needs Xcode + an Apple ID
3. Web Push notifications — `parked`: needs HTTPS and a push service
4. Haptics on iPhone (partly there already) — `exists` (+ a tap when a favourite is picked up to drag)
5. Auto light/dark theme — `done`: Settings → Theme (system / dark / light)
6. One-handed layout with large tap targets — `exists`: bottom tab bar on phones
7. QR code in the Mac window to open the phone page — `done`: Settings → On your phone (and the link under the wall)
8. QR code on the wall for pairing — `idea`
9. Bonjour `.local` discovery so no IP address is needed — `exists`: http://<Mac name>.local:8765 already works
10. Deep links to a scene (`nanomanager://scene/...`) — `partly`: `#play=mood:Cozy` page links and /run links; a `nanomanager://` scheme needs the native app
11. Home-screen widget showing the current scene image — `idea`: native app
12. Live Activity showing a countdown — `idea`: native app
13. Service worker caching of scene previews — `parked`: needs HTTPS
14. VoiceOver labels and reduced-motion support — `done`: labels on cards, buttons and the wall, toasts read out, previews hold still with Reduce Motion
15. PIN lock on phone access (the phone page currently has no password) — `done`: Settings → Lock

## 4. Games (watch-only)

Games that run themselves: no player input, just something to watch.

1. Game of Life on the hex grid, restarting when it settles — `done`
2. Snake attract mode: an AI snake wanders the wall — `exists`: Snake
3. Pong demo: two AI paddles rally forever — `exists`: Pong
4. Tetris demo: pieces stack and clear on their own — `exists`: Tetris
5. Breakout demo: an AI paddle keeps the ball in play — `done`
6. Pac-Man ghost chase screensaver — `exists`: Pac-Man
7. Dice roller: triangles show the pips and roll on a timer — `done`
8. Coin flip that lands on a random panel colour — `done`: Coin Toss (lands gold or silver)
9. Tic-tac-toe played by two AIs — `done`: Noughts & Crosses
10. Connect Four played by two AIs — `idea`: this wall's columns are only 1–4 panels tall, so four in a row barely exists
11. Lights Out solver: the wall solves its own puzzle, step by step — `done`
12. Flappy-style demo with an autopilot bird — `done`
13. Simon demo: the wall plays a pattern and shows it, no input — `exists`: Simon
14. Random maze generator that draws itself — `done`
15. Space Invaders attract mode: a wave marches and fires — `done`

## 5. Parked (data-driven, not right now)

1. Battery or CPU meter on the panels
2. Next-meeting countdown colour from your calendar
3. Temperature gauge
4. Stock or crypto display, green up and red down (display only)
5. Air-quality colour
6. Pollen alert
7. Home Assistant bridge (`ha_token.txt` already exists)
8. Door-open alert: a panel turns red
9. Album-art colours from Spotify
10. Music visualiser using audio input
11. TV Ambilight from the screen or Plex
12. Flash when new mail arrives
13. CI build status: green passes, red fails
14. Egg timer
15. Habit tracker: a panel fills for each completed day
16. Water-intake progress
17. Steps progress ring
18. Sleep score colour
19. Kids' chore chart
20. Bin-day reminder

---

## Dropped

- **Playable games** (Breakout, Snake with swipe steering, Whack-a-mole, Reaction timer, Memory match, Two-player Pong, Tic-tac-toe, Connect Four, Space Invaders, Flappy, Lights Out, and similar).
- **Social and fun** (wall inbox, family votes, guest links, Morse messages, emoji bursts, fortune cookie, and similar).
