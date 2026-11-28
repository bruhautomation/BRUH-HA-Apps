# BRight specifics: history moved out of docs/notes/bright.md

What each rule in `docs/notes/bright.md` cost to learn. None of it is needed to follow the rules; it is here for the next person who wonders why a port, a threshold or a button works the way it does. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold.

## The port and the panel

- **A host-network add-on does not get to choose its port.** BRight shipped `ingress_port: 8095` — picked only to dodge BRUH Minecraft's 8099 — and on a box where something else already had 8095 the add-on could not start at all: `[Errno 98] address in use`, the panel dead before its first request, run.sh's `wait` returning, the container exiting, the Supervisor restarting it, and the next attempt asking the same host for the same taken port.
- **The port is bound before anything claims it is listening.** Every log this add-on ever wrote about 8095 said `listening on 0.0.0.0:8095` immediately above the traceback proving it was not.
- **A dynamic port costs the `watchdog:` URL, so the watch moved inside.** `tests/test_addon_hardening.py` asserted the invariant both ways: every add-on is watched by *something*, and no add-on that gave its port away still names one in a watchdog URL.
- **Nothing on the BRight panel is public.** `/api/health` was the one public prefix, and it was public for exactly one caller: a Supervisor watchdog polling from off-network. Its replacement runs inside the container over loopback, so the exemption lost its caller and went with it.

## Playback and the library

- **A service call that was accepted is not a speaker making a sound, and every layer of this add-on used to report the first as the second.** The panel once said "Running: 412 cues" over a dark room. `homeassistant.local` as an `internal_url` is what a great many installs have.
- **An answer that is dropped is a success nobody earned.** The integration's three services awaited the bridge and ignored what came back, so `bright.party_mode` with nothing analyzed gave an automation a green tick and a dark room while "no analyzed tracks in /media/music — run the Library tab first" was thrown away one line from the person who needed it. The bridge had the same shape one layer out (`panel answered HTTP 409`, with the panel's own body unread), and `h_ha_entities` had it sideways: the picker said "you have none" when the truth was "I could not ask".

## Analysis

- **A version that nothing compares against is not a version, it is a comment.** `ANALYSIS_VERSION` sat at 1 while the analyzer gained fields, and `library.scan` marked a track `analyzed` if an analysis file existed *at all* — so 0.15.0's ranked accents shipped, passed their tests, and reached **nobody with an existing library**: their analyses had no `hits`, so the choreographer placed no accents and the brief carried no accent block, which from the outside is indistinguishable from a feature that does nothing.
- **`detect_hits` returned ZERO accents, on everything, for as long as accents existed.** The peak test was `punch > local + 0.10`, an absolute constant. Measured on a clean, loud, isolated kick-and-snare loop, punch peaks at **0.0795**, against a bar of 0.10. Every effect built on ranked hits rendered nothing, and the suite was green throughout because its only hit fixture was a synthetic stab built out of *twice a kick plus a body* — loud enough to clear an absolute threshold no real mix reaches. Comparing raw band sums said `mid` for nearly every hit and left `band: "low"` — the kick layer — selecting nothing. The ratio guard that was tried classified every kick over a bassline as a snare. `TestWhichDrumWasIt` graded it against three synthetic mixes at ordinary levels. `accent` read an empty list for months because of it.

## Effects

- **A LIFX waveform runs between the bulb's CURRENT colour and the packet's, which is why the beat pulse peaked on the off-beat.** The one effect whose entire job was "the beat" was inverted in every show BRight ever compiled, since the first release. `test_the_table_agrees_with_the_simulator` pinned `PEAK_PHASE` against `_wave_position`.
- **A LIFX bulb runs exactly ONE waveform at a time.** `test_the_catalog_agrees_with_itself_about_which_are_routines` rendered every type and checked the set against what actually emits a wave action.
- **The brief's list of bulb-side effects is generated from `BULB_ROUTINES`.** The hand-written copy had already drifted by two: the brief listed seven while the compiler warned about nine.
- **A swell is not a strike, and every rhythmic effect BRight had was a swell.** An audit of the automatic show found swells in every section.
- **Every effect BRight had was a brightness effect, because `SetWaveform` carries a whole colour and moves all of it.** A measured audit (render each type, simulate it, look at what the ROOM does) found two of seventeen moving brightness past two levels and none able to move colour while holding the level still. `colour_drift` was measured at 356° of travel with the level constant to three decimals. The loudness envelope existed from the first release and was read only to find sections and drops.
- **An effect whose selection matches no light is the one silence with nothing to do with the music.** The only trace was a `0 lights` on a list nobody reads.

## The automatic show

- **The automatic show places them where the song has room.** The first placement of `melody` and `harmony`: harmony on whatever is not carrying the beat (candles, strip), through the calm half; the tune on one kind of light through the verses and quiet sections. **Not in the peaks, deliberately** — a chorus already had a chase across every mover and a stab on every accent, and a third thing competing for the same bulbs on eighth notes was mush. The four-layer show replaced it: the voice layer plays in the chorus, which works because it owns its own lights.
- **The automatic show is four layers on different lights, not a texture per section.** The old shape gave each section one look and ran it end to end, which is structurally incapable of following a song however good the analysis under it is. A six-a-song accent pass is gone: six was never the taste, it was the budget for a stab that owned every mover in the room.

## Shows and the editor

- **A track has many shows and one of them plays.** Every compile used to overwrite `show.json`, so asking Claude to try again destroyed the show somebody had spent an evening editing — which made the rewrite button a thing people avoided.
- **The show editor is a picture, and the picture is served by the compiler's own walk.** The extraction was verified against the pre-refactor compiler on a real generated show (898 cues, byte-identical), not argued for.
- **The panel draws what the song is PLAYING, or the musical analysis is invisible.** The editor drew an envelope, section tints, bar lines and `128 bpm · 7 sections · 2 drops`, so a `melody` effect that rendered zero notes looked exactly like one that worked, and a stab 200ms off the hit it answered could not be seen at all. The old "What it compiled to" list was one row of fixture and move counts per effect and ran to forty rows on a real show.
- **A strip column is one instant across the room, never an average and never a per-light peak.** Per-fixture peaks were tried on the theory that a strobe was too short to survive point sampling, and showed one changed column where point sampling showed two. The case that prompted the change was not a sampling failure at all: the effect had been dropped on the same instant as the drop's stab, which owns those lights there, so the show really was identical. The change was reverted rather than kept for its nicer story.
- **An editor may not quietly rewrite what it opens.** Three ways it did, all found by driving it: the effect dialog wrote `select: {ids: [...]}` from its tick-boxes, which turned "every candle" into "these four bulbs"; it defaulted the travel order to `listed` when the compiler's default is `x`, so opening a chase and pressing Apply changed how it crossed the room; and it wrote that default into the file even when nothing was picked.
- **A row that misreads a selection is a row you edit by mistake.** Effect rows said `all lights` for every effect the director wrote, because the label counted `select.ids` and the director names roles.

## Parties

- **The Party tab is one screen and the vibe is not on it.** In a party the vibe reached only a track with no show yet (`preparer` returns early when `load_show` finds one) — so on a library with shows already built it did nothing at all, on a fresh one it silently decided what went to disk forever, and two parties naming different vibes over one track gave whichever ran first.
- **A Stop button that is always there is a button nobody trusts.** Three buttons used to guess at "is a show running" separately.

## Director jobs

- **Asking Claude for something is a job, never a request.** `jobs.py` was written for exactly this and says so in its docstring — the Library's analyze pass had always used it and the Claude routes had not, because when they were written the director was quicker. The model moving to Opus was what made it fail.
- **`available()` answers one of six questions, and the folder outlives the listener that made it.** It tested whether `/config/.brain/tasks` was a directory, so a brAIn that was not running looked *identical* to a working one until the wait expired: ten minutes of spinner, then a message blaming a timeout, which sent somebody to the slowest thing in the system when nobody was listening at all.

## The Light Map and panel rows

- **A dot has to say which light it is.** The Light Map drew a role glyph in a circle with the name in a `title` — a hover tooltip, on the device most likely to be dragging lights around a floor plan, which has no hover — with the role picker and Remove only in a list that had no visible connection to the picture above it. The geometry details were all found by measuring; `measure-lightmap.mjs` found the role picker rendering at the browser's default 19px.
- **Panel rows say plain words, and a pile of lights is one dot.** Label ink that followed the theme was black on near-black in the light scheme. Shows rows once read "Written by Claude · N cues · 3 min ago"; that moved into the ⋯ menu.
- **A ⋯ menu is a row of the list, never a floating box.** `details.more` with an absolutely placed `.more-menu` drew over the next rows' Check, Play and ⋯ on a phone (Lab bulbs, Shows tracks) and could not be fixed per row. Shows rows then said "Ready · played 3 d ago" / "never played" on every row.
- **A list says its verdict first, and a control appears where there is a choice.** Five reports in one batch had one shape: a list repeated the same line on every row (bulbs "Not checked yet", songs "has a show", map rows ids and Remove) and the answer to "is anything wrong?" was nowhere.
- **A pair has to read as two different rows, and a default is a choice made for somebody.** A song kept as a short clip in one folder and as the full song in another showed as two identical rows: no length anywhere, no tags to match, and the lengths too far apart for the same-length rule. The beat test's picker used to start with every bulb in the house.
- **The Shows list folds and says its verdict once; a tap goes where it opened.** It had said "Ready · never played" on every row (#1290).
- **A control that answers on `pointerdown` moves the page under its own tap.** Tapping a Light Map pile drew its pick list on the bar above the floor on `pointerdown`, which pushed the floor down, so the tap's `click` landed on one of the list's own buttons and chose a light: on a phone "2 lights" never showed both.
- **A fold that does not look like one, and a default one tab has and its neighbour does not.** "What do these checks mean?" read as a bold heading with no answer; a tick box sat above its own word; the phone tab strip's fade alone was not cue enough; Shows' speaker picker defaulted differently from Party's.

## Measures

- **`tests/manual/bright_demo_panel.py` + `measure-effects.mjs`.** The registry-shape rule was found by a demo that seeded a shape nothing reads and booted with no bulbs.
