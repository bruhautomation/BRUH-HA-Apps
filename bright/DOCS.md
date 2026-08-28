# BRight

> ## ⚠️ Under active development
> **BRight is not finished.** Features described below may be partial,
> missing, or broken, and updates may change behavior without ceremony.
> Treat every release as a preview until this banner goes away.

Music-driven light show director: local music in, compiled light shows out,
everything in sync with the speaker actually playing the music.

Point BRight at your music. It analyzes each track once — tempo, the beat
grid, song sections and drops, synced lyrics where they exist — and compiles
a light show for *your* lights ahead of time. Then it plays the track on your
speaker and runs the show against a clock anchored to that speaker's measured
delay, so the lights land on the beat instead of two seconds behind an
AirPlay buffer.

---

## What you need

| | |
|---|---|
| **Home Assistant** | 2023.6 or newer, with the add-on store (HA OS or Supervised) |
| **Music** | Audio files under Home Assistant's `/media` folder — mp3, m4a, aac, flac, ogg, opus or wav |
| **A speaker** | Any `media_player` entity Home Assistant can send media to: Chromecast/Google, AirPlay, Sonos, DLNA, a wired output |
| **Lights** | LIFX bulbs on the same LAN (driven directly), and/or party lights and lasers on any HA `switch`/`light` entity |
| **Optional** | The [brAIn](../brain) add-on, which lets Claude design the choreography instead of the built-in algorithm |

BRight works with no LIFX bulbs at all (the aux-light channel still runs), and
with no brAIn (the algorithmic director is the floor and always compiles).

**One Home Assistant setting matters and is easy to get wrong** — see
[When nothing plays](#when-nothing-plays). If your speaker is a Chromecast or
a Google/Nest speaker, read that section *before* concluding BRight is broken.

---

## Install

1. Add this repository to **Settings → Add-ons → Add-on store → ⋮ →
   Repositories**.
2. Install **BRight** and start it.
3. Accept the discovered **BRight** integration under **Settings → Devices &
   Services**. The add-on deploys the integration itself and announces it;
   accepting the discovery is what adds the services and the show sensor.
4. Open the panel from the sidebar.

---

## The order things want to happen in

You can wander, but this is the path with the fewest dead ends:

1. **Calibrate → Test playback.** Before anything else, prove your speaker
   can play a file from Home Assistant. It takes ten seconds and it is the
   step everything downstream depends on.
2. **Lab** — discover your bulbs, probe their round-trip times, measure a
   switch's service latency, run the waveform demo.
3. **Calibrate** — measure each speaker's delay, phone in hand.
4. **Library** — pick the folders to scan and analyze the music.
5. **Light Map** — place the lights in the room and give each one a role.
6. **Shows** — compile a track, play it, judge it in the room.
7. **Party** — one button, or one automation.

---

## The tabs

### Lab — measure the house

Nothing here changes your lights permanently; it measures.

- **LIFX bulbs — direct LAN.** Discovers bulbs by UDP broadcast, then
  measures each one's round-trip time with an invisible echo (not a flash),
  ramps its sustained message rate to find its real ceiling, and can fire a
  waveform demo — one packet that makes a bulb pulse on the beat *by itself*,
  which is how shows stay in sync without a packet per beat.
- **Aux lights — through Home Assistant.** Party lights and lasers on smart
  plugs ride HA service calls, which are slower. The probe toggles the device
  a few times, measures the real call-to-state round trip, and puts it back.
  Compiled shows send those cues early by exactly that much.
- **Sync proof — the metronome show.** Plays an analyzed track on a
  calibrated speaker while every discovered bulb pulses on the beat. No
  choreography, just the whole chain end to end. If this hits the beat,
  shows will. Tick which bulbs join in — the proof needs one light you can
  see, not every light in the house blinking at once.
- **Latency report.** Everything measured so far, in one read.

### Light Map — where the lights are

The director's cast list. Drag each light to roughly where it is in the room
(left ↔ right matters most — sweeps travel across x) and give it a **role**:

| Role | What the director does with it |
|---|---|
| `candle` | Glows and drifts. Never strobes. |
| `downlight` | Carries the beat. |
| `lamp` | Carries the beat, with more colour latitude. |
| `strip` | Carries sweeps across the room. |
| `party` | Saved for the moments that earn them (drops, choruses). |
| `laser` | Same, rarer. |

Tap a light to select it: the dot, its row in the list, and the bar above the
floor all highlight together, and the selected light can be re-roled or
removed right there. Every dot carries its name on the map — you never drag
an anonymous circle.

Two ways to get bulbs onto the map, and they are for different moments.
The **picker** below the floor lists every discovered bulb that is not on the
map yet: choose one, give it a role and a room, add it. That is the one to
use after the first run — six bulbs dropped on the middle of the floor
plan named after their serials is not a map. **Add discovered bulbs** adds
every unmapped bulb at once, which is the right button exactly once. Neither
ever overwrites a light you have already placed. Party lights and lasers on
switches are added by entity with **Add a switch light…**.

The map is not decoration: it is what an effect travels *through*. A chase
ordered by `x` runs left to right across the room you drew, `center_out`
starts in the middle, and `zone` walks room by room. Getting the positions
roughly right is what makes the automatic shows look deliberate.

#### Roles and zones are two different questions

A **role** is what a light *is*, and it changes how BRight drives it. A
`candle` stays warm and low (capped at 45%) and is kept out of strobes and
hard pulses however enthusiastic a show gets; a `lamp` or `downlight`
carries the beat at full range; a `strip` is the one that reads best for
motion; `party` and `laser` are switches — on or off, no colour, and sent
early to cover Home Assistant's latency. Getting a role wrong is how a
bedside candle ends up strobing.

A **zone** is just a name you give a group of lights, usually a room. Type
the same word on several lights and they are one zone. There is no list to
maintain and nothing needs a zone — a zone exists exactly as long as a
light is in it, and deleting the last light in one deletes the zone.

What zones buy you is being able to talk about *part* of the house:

- `"select": {"zones": ["kitchen"]}` — this effect owns the kitchen and
  leaves everything else exactly as the scene put it.
- `"order": "zone"` — a chase or a sweep travels zone by zone rather than
  straight across the floor plan, which is what you want in an open-plan
  space where "left to right" crosses three areas.
- A party's allowed-fixture list and the Claude director both read them, so
  "keep it to the lounge after 11" is one word rather than five bulb ids.

Set a zone when you add a bulb, or select any light on the map and type one
into the field beside its role. The box offers the zones you already have
and accepts a new name.

### Effects — what the lights actually do

An **effect** is a thing some of your lights do for a stretch of music: a
chase across the room, a build into the drop, a strobe on the last four bars.
It is the unit everything else in BRight is made of — the automatic director
writes effects, this tab builds them by hand, and a show script is a list of
them. There is no private vocabulary the automatic show can use and you
cannot.

Every effect has four parts:

1. **What it does** — one of the types below, with its own parameters.
2. **Which lights it owns** — ticked individually, or by role. *Everything
   you do not tick is left exactly as the rest of the show left it.* That is
   the whole reason for building effects rather than scenes: most of the room
   is usually meant to stay still.
3. **How it travels** — the order it moves through those lights, taken from
   the Light Map: `x` (left to right), `-x`, `y`, `center_out`, `edges_in`,
   `snake` (reading order through the room), `zone`, `random` (seeded, so it
   is the same every night), or `listed`.
4. **What it locks to** — `beat`, `downbeat`, or plain `time`. Everything
   that steps, steps on the beat grid, which is why a chase stays with the
   music when the tempo is not a round number.

| Effect | What it is for |
|---|---|
| `wash` | Hold a colour. The still ground everything else moves against. |
| `fade` | Travel from one level to another across the window — a section transition that reads as intent rather than a cut. |
| `build` | Tension: climb in stages, optionally lighting one more fixture per stage, so the drop has somewhere to land. |
| `pulse` | The beat itself. One packet carries eight beats of motion. |
| `strobe` | Hard flashing for a short burst — one packet per bulb however fast it runs. |
| `chase` | Jump between bulbs in order. Width and bounce make it a runner, a comet or a ping-pong. |
| `sweep` | One wave travelling across the room, phase-shifted by where each light stands. |
| `breathe` | Slow rise and fall under everything else. |
| `sparkle` | A few random lights catch each beat. Texture, not pattern. |
| `colour_cycle` | Rotate the palette through the lights — motion without brightness. |
| `rainbow` | Hue spread across the room, turning slowly. |
| `theater` | Alternating groups answering each other. |
| `stab` | One hit, at one moment. |
| `blackout` | Take the selected lights down. Silence is a lighting cue. |
| `melody` | Follow the tune. Each note lands on the next light along and its pitch picks the colour, so a rising phrase climbs across the room. |
| `colour_drift` | The colour travels and the brightness never moves — the bulb walks its hue around the wheel on its own. The only motion a candle can join. |
| `saturate` | Saturation breathes: the room washes out toward white and back, with the level untouched. |
| `level` | Brightness follows how loud the song actually **is**, moment to moment — the audio itself, not the beat grid. Pick a band and the lights breathe with the kick, the vocal or the shimmer. |
| `harmony` | The palette follows the chords: the selection crossfades on every harmony change, so the room turns over with the song rather than with its sections. |
| `aux` | Party lights and lasers: on, off, or flashed on the beat. |

**One rule about layering, and it is physics rather than taste.** `pulse`,
`strobe`, `breathe`, `sweep`, `stab`, `colour_drift` and `saturate` are run
*by the bulb* — that is the sync trick, and it is why they cost one packet
however long they run. A LIFX bulb runs exactly **one** of them at a time,
so two overlapping on the same light is not a layered effect: the later one
cancels the earlier, and from across a room that reads as an effect that
mysteriously does nothing. Give them different lights or different windows.
Everything else layers freely — a pulse on the lamps under a chase across
them is two different things at once, which is the good case. The show
editor says so on the effect's own row when a script does it anyway.

`colour_drift` and `saturate` are the only two effects that move **colour
without touching brightness**. Nothing else here can: an ordinary waveform
carries a whole colour and moves all of it, so before these existed every
effect in BRight was ultimately a brightness effect. They are what a quiet
section wants, and the only motion a candle is allowed to join.

`melody` and `harmony` are the two that need the song's *musical* analysis
(see below) rather than just its beat grid. On the Effects tab they preview
against a stand-in tune, because the bench has no track; in a show they use
the real one. On a track analysed by an older version of BRight they render
to nothing, and the effect's row in the show editor says so.

**Preview** renders the effect and shows it two ways: the room, animated on
the same floor plan you placed the lights on, and the whole effect as a
strip — one row per light, time running left to right — which is the view
that tells you whether a chase actually chases. Both are drawn from the same
render the compiler turns into packets, so a preview that looks wrong is an
effect that is wrong. Scrub with the slider; play and pause with ▶.

Underneath, the price: how many cues it costs and the busiest bulb's messages
per second against the 18/s budget. **Run it on the lights** does exactly
that — no music, the real bulbs, restored afterwards.

**Keep role manners** (on by default) is what stops a candle strobing and
holds each light under its role's brightness ceiling. Turn it off when an
effect means to own a fixture outright.

Saved effects keep their **lights** as well as their settings, because
"kitchen chase" is the chase *and* the three lights it runs across — which is
the part that took the time. **Put it in a show** drops the effect into one
scene of one track's show and recompiles.

### What BRight hears in a song

Analysis answers two different questions, and shows need both.

**When it hits** — the beat grid, the sections, the drops, and the ranked
*accents* (the punches that sit exactly on the beat). This is the
skeleton: it tells a show where to be bright, where to build, and where a
stab lands.

**What it is playing** — the harmony (chord changes, and the track's key),
the melody (the dominant line, note by note), the phrases that melody
breathes in, and the passages that repeat. This is the half that lets a
show follow the *song* rather than its structure. Chords in particular
change every bar or two on their own clock, almost never where the energy
changes — so a palette that follows them keeps moving through the long
stretches where the section map is doing nothing at all.

The `melody` and `harmony` effects consume this directly, the automatic
director places both, and Claude gets all of it in its brief.

The accents carry **which drum** as well as how hard: the analyzer compares
the low band against the mid at each hit, so a kick and a snare are
different events and the `accent` effect can put them on different lights.
The two bands are scaled to each other before that comparison, because
they cover very different numbers of frequency bins and comparing them raw
answers a question about the band edges rather than about the drum.

### How a show is built: four layers, on different lights

This is the design the automatic director follows and the one Claude's brief
teaches, and it is worth knowing because it is also how to read a show you
are editing.

A show is four layers with different time constants, and what makes it read
as musical rather than busy is that they are **separate**:

- **ground** — the room's colour, moving with the harmony. Seconds-long.
  The only layer that should feel like fading. Candles, a strip, whatever
  is not keeping time.
- **pulse** — the beat, on lights doing nothing else. A `hit`, not a
  `pulse`: mostly felt rather than watched.
- **hits** — the kick and the snare as different instruments, landing on
  the drums the analyzer actually heard rather than on the beat grid, so
  they catch the fills a grid knows nothing about.
- **voice** — the melody, tracking real pitch. Each note lands on the
  light its pitch points at, so a run up the scale is a run of light
  across the room and coming back down runs back. The layer that makes a
  room feel like it is playing along, and it belongs in the chorus as
  much as anywhere else.

Two rules hold the arrangement together, and the first is physics: **a LIFX
bulb runs one waveform at a time**, so two rhythmic layers on one bulb is
the second cancelling the first. A fixture therefore belongs to exactly one
layer, and where a room has fewer kinds of light than there are layers, the
director **splits a role** — the left lamps are the kick, the right ones the
snare. The second rule is what actually makes a chorus land: **a layer
arriving is itself an event**. A chorus is not brighter than the verse; it
is the strip joining the kick and the lamps switching from washing to
following the tune.

### Swells and strikes

Every effect in the vocabulary is one or the other, and it is the single
biggest difference between "a light show" and "mood lighting".

A **swell** travels smoothly up to a level and smoothly back: `pulse`,
`breathe`, `sweep`, `colour_drift`, `saturate`. A **strike** is at full
brightness the instant it lands and decays from there: `hit`, `accent`,
`stab`, `strobe`. An instrument has an attack; a show made only of swells
does not, and reads as a row of lights fading in and out near the music.

`hit` and `accent` are drawn as a linear decay because `saw` is the only
one of LIFX's five waveform shapes that is monotone across a cycle — the
others come back up inside it, which ducks rather than decays. Both still
cost one message per light however many beats they cover, because the bulb
runs the envelope itself.

### Where the lights land

A LIFX waveform runs between the bulb's **current** colour and the one in
the packet, so a sine anchored on the beat is at its dimmest exactly where
the kick is and brightest halfway to the next one. BRight sends every
rhythmic cue early by that shape's own peak phase, so the brightest instant
falls on the beat. If you are writing effects by hand you do not have to
think about this; it is in the compiler.

**If a track was analysed by an older version of BRight it has none of
this**, and its row in the Library says so (`⟳ analysed by an older
version`). Press **Analyze** — out-of-date tracks are re-heard without
being asked twice, and the status line says how many were refreshed. A
stale track still plays and its shows still run; it is just answering
with less than BRight can now hear.

### Library — the music, analyzed ahead of time

Analysis is the slow part of a show and it happens once per track: tempo and
beat grid, onsets, energy bands, song sections and drops, and time-synced
lyrics from LRCLIB when they exist. Tracks are identified by **content**, not
by path — renaming a file doesn't re-analyze it, and the same track in two
folders is one track.

- **Browse media** lists the folders under Home Assistant's media folder.
  Open one to go into it; tick the ones to scan. Each is scanned all the way
  down, so ticking a parent covers everything under it. Nothing here needs
  the add-on restarted.
- The folders being scanned are listed at the top of the card, and one that
  has gone missing says so rather than silently contributing nothing.
- **Analyze new tracks** works through everything unanalyzed, one at a time
  (analysis is CPU-bound; two at once just thrash), reporting progress per
  track. One bad file is reported and skipped, never the end of the folder.

### Shows — compiled choreography, and the file it comes from

One show per track, compiled ahead of time so playback is nothing but a clock
and a cue list. Compile after changing the Light Map — the show is built for
the lights that existed when it was compiled. Playing needs a calibrated
speaker.

Each track row has two ways to hear it: **▶ Show** runs the compiled
choreography, **♪ Beat sync** runs the metronome — every mapped light
pulsing on the analyzed beat, which is the honest test of whether the sync
is right before you spend an evening on it. While either runs, the same
**±25ms** nudge buttons the party has appear under the list.

**Notes for the director.** Under the show's editor there is a box for
what you noticed watching it — "the chorus needs more movement", "less
strobe, warmer verses" — and **✍ Revise with Claude** sends the whole
script back to the director with your words. The revision goes through the
same validator and compiler as everything else; a failed one costs an
error message and never the show. Needs brAIn, like everything else the
Claude director does, and runs on the `director_model` below.

**The show, as a picture.** Select a track and the show opens as what it is:
your room on the floor plan at the top, the whole song as a strip beneath it
with one row per light, the scenes as blocks across the top of that strip,
and the effects as rows you can press.

Drag the scrub bar and the room shows you that instant. Press ▶ and the show
plays through at real speed — on the screen, not on the bulbs, so you can
read a show at midday without lighting the house up. Press a scene block to
jump to it.

**The song is drawn too, under the same ruler.** Beneath the waveform are
three lanes of what the track is actually playing: the **chord changes** as
labelled blocks, the **melody** as a pitch contour against the song's own
range (a rising line rises), and the **drums** with the kick low in the lane
and everything above it high, each tick as tall as the analyzer ranked it.
Under the strip is one **named row per effect**, drawn from what the
compiler really rendered — so an effect that produced nothing has a visibly
empty row saying so, which is the one thing no other view could tell you. A
line under the transport says what is running at the playhead and what
starts next. Pressing anywhere on the song or its lanes scrubs to that
instant.

**Every show is kept.** *Versions of this show* lists every compile,
revision and hand edit, newest first, with who wrote it and how big it is.
The one marked *playing* is what a party runs; **Play this one** makes an
older version live again. **Name it** keeps a version for good — unnamed
ones are dropped oldest-first past a dozen — so asking Claude to try again
can never cost you the show you spent an evening on.

**Editing is the picture, not the file.** Press **Edit** on any effect row
and you get the same form the Effects tab builds — type, travel order, which
lights it owns (individually, by role, or by room) and every parameter with
its range. **+ Effect** adds one to that scene; **✕** takes one away. The
preview follows every change immediately, because the panel previews the
show *as currently edited* rather than as last saved. If a change would
flood a bulb, you find out there and then, next to the effect you changed,
instead of several presses later.

Nothing is written until you press **Save & compile**, which goes through
exactly the same door the director's own output goes through: validated,
compiled, and checked against the per-bulb message budget before anything is
kept. A script that would flood a bulb is refused with the reason and the
show you had is untouched.

**Code** opens the same show as text — scenes with their palettes,
brightness and effects, and moments pinned to the drops. This is still the
entire show, and the two are one document: type in either and the other
follows. It is there for the edits a form is clumsy at, and for the copy you
keep.

Every compile also writes the script to
`/config/.bright/shows/<track>-<hash>.json`, where the Home Assistant file
editor can open it. Edit it there and press **Reload from file**. The mirror
is a copy, not the record — editing it changes nothing until you import it,
which is deliberate: a half-typed JSON file being picked up by a party at
11pm is not a feature. Broken JSON is reported with the parser's own
complaint, line and all.

**Show the cue list** prints the compiled timeline: when, which light, and
which effect asked for it. Every cue carries the name of the effect that
produced it, which is what makes a two-thousand-cue timeline readable.

A hand-written script is a first-class show. The minimum is a scene with a
window, a palette and a list of effects:

```json
{
  "version": 2,
  "palette_name": "club",
  "scenes": [
    {
      "start": 0, "end": 48, "mood": "roll", "kind": "mid",
      "palette": [[200, 0.9], [300, 0.8]],
      "brightness": 0.5,
      "effects": [
        {"type": "pulse", "name": "beat", "select": {"roles": ["lamp"]},
         "params": {"every_beats": 1, "depth": 0.35}},
        {"type": "chase", "name": "kitchen runner", "order": "x",
         "select": {"zones": ["kitchen"]},
         "params": {"step_beats": 0.5, "width": 2, "bounce": true}}
      ]
    }
  ],
  "moments": [
    {"t": 48, "effect": {"type": "stab", "name": "drop",
                         "select": {"roles": ["lamp", "laser"]},
                         "params": {"strength": 0.9}}}
  ]
}
```

Parameters are forgiving on purpose: anything you leave out takes its
default, and anything out of range is clamped rather than rejected. A show
that refused to compile over `depth: 1.2` would be a worse tool than one that
reads it as `1`. Set `"base": false` on a scene to stop it washing every
light at its start — that is how a scene is written to leave the room where
the last one left it.

### Calibrate — how long your speaker takes

Every speaker adds latency between "play" and audible sound — AirPlay around
two seconds — and no API reports it. There are three ways to fill it in:

1. **Test playback** first. It sends the click track and follows it the whole
   way: whether the file is on disk, whether Home Assistant can resolve it,
   what address Core will hand your speaker, whether the speaker accepted the
   command, and whether it actually started playing. It names the step that
   broke and what to do about it.
2. **Play clicks & listen** — the real measurement. Open the panel *on your
   phone*, in the room with the speaker. BRight plays a 13-second click track;
   the page records it through the microphone; the offset comes out of a
   cross-correlation. The clicks are unevenly spaced on purpose: the pattern
   lines up exactly one way, so the answer cannot be out by a beat.
3. **Play clicks & tap** — for setups where the browser refuses microphone
   access (plain HTTP). You tap along with each click. Coarser, because your
   reaction time rides in (~100 ms), but workable.

**Or type the delay in.** A show will not start without a calibration
profile, so one speaker that refuses to play the click track would otherwise
take the whole add-on with it. The typed profile is stored as *manual* — it
never claims to have been measured. 0 is right for a wired speaker; around
2000 ms is a reasonable guess for AirPlay.

Run the measurement once per speaker, and again if a show ever feels
consistently early or late — speakers renegotiate their buffers between
sessions. The stored profile keeps a median across runs plus a fine-tune
nudge you can set per player.

The click track is written to `/media/bright/calibration.wav`, because your
speaker fetches it from Home Assistant rather than from the add-on: a
Chromecast has no route to BRight's panel and would not be allowed through it
if it did. BRight creates that folder at startup.

### Manual — play the lights yourself

The other kind of evening: you are the director, live, from your phone.
The whole tab is **one screen** — the room, the loop button, both pads
and the effect rack, with nothing to scroll past to reach any of them,
because scrolling to find DROP is the same as not having DROP.

Start a **session** from the row at the top — pick a song and a
calibrated player, or pick nothing and perform to whatever is already
playing — and BRight snapshots every mapped bulb so **Stop** puts the
room back exactly as it found it. Once it is running that row collapses
to Stop and one line saying what is playing.

**The map is the instrument.** The middle of the screen is your light
map, and the lights are where you put them: tap a bulb and *that bulb*
plays, right there, under your finger. It lights up the instant you
touch it — the room's own answer travels over the network and arrives
after your hand has gone, and a control that waits for it feels broken.

- **Tap a rhythm onto the bulbs**, then press **⟳ Loop** on the next
  repeat's first beat — which is how it learns the figure's length —
  and the pattern keeps running on the bulbs you tapped it onto. A
  tapped melody travels the room because you tapped it across the room.
  The loops run on the server, so they hold time even when your phone's
  browser naps. A looping bulb wears a pulsing ring; **hold it** for
  half a second to stop that loop. **✕** forgets the taps.
- **DROP** takes every light to black, right now. **FLASH** pulses every
  light to full white and back — the bulb itself does the returning, so
  a flash can never strand the room bright. Both always take the whole
  room, because a drop that misses the lamps you forgot to pick is not a
  drop, and both are the biggest targets on the panel because they are
  pressed in the dark without looking.
- The **rack** along the bottom scrolls sideways: one-shot effects, then
  your saved effects (★), then a switch per kind of party light. An
  effect fires on **the bulbs in your current taps** — tap two lamps,
  hit Sparkle, and it sparkles on those two — and on the whole room when
  you have not tapped anything. It fires at your tapped tempo, 120 BPM
  until you have tapped one.

Gestures ride a **live socket**, not one web request each. v1 opened an
HTTP round trip per tap — through ingress, from a phone, over wifi — and
somebody tapping sixteenths opened requests faster than they finished, so
the commands backed up and the room fell behind the hand. If the socket
cannot be opened the tab still works, one request per gesture, which is
the old speed rather than nothing.

Semi-manual, semi-automated: you decide *what* and *when*, the bulbs run
the envelopes in between. Starting a show or party — or pressing any
Stop — ends the session, stops every loop, and restores the room.

### Party — the sentence the add-on was built for

One screen: tick the shows you want, pick the speaker, press **Play**.
Nothing ticked plays everything in your music folders. The songs run in the
order you ticked them (each shows its place, `#1`, `#2`), and **Shuffle**
is off unless you ask for it — an order you just chose is a request, not a
default to override.

A song with no show yet gets one written while the party runs, so a set can
mix tracks you have already directed with ones you have not.

The Stop button is not there when nothing is running: a button that is
always present is a button nobody trusts, so it renders only while the
add-on says a run is actually in progress, and the line beside it says what
is playing and how far through the queue it is.

While a party runs, the live view is the transport: **⏮ Prev / ⏭ Next**
move through the queue (previous on the first track replays it), the
**±25ms** buttons trim the sync by ear, and **🎤 Sync by ear** does the same
trim measured — the phone records the room for four seconds, BRight matches
what it heard against the playing track itself, and the lights shift by
exactly the difference. **Keep this trim** folds either kind into the
speaker's calibration so every future show starts in tune.

Each song in the set can also name **which of its shows to play**. The
default is whatever is live — so the newest is what plays without anyone
choosing it — and the picker beside a song is there for the evening you
want last month's version of one track.

**Saved sets** are a name on exactly what is on that screen — the speaker,
the songs, which lights may join in, and what the room should look like when
it stops. **Save as a set** names what you have picked; **Load** puts a saved
one back on screen so you can see what Play would do before pressing it.
Start one from the list, from an automation with `bright.start_party`, or by
voice. Anything given at the time still wins over what the set saved, so
"the usual thing, but on the kitchen speaker" works.

There is no "vibe" here any more, and its absence is deliberate. A vibe
steers the **director**, which is a compile-time decision — and on the Party
tab it only ever reached a track that had no show yet. On a library you had
already built shows for it did nothing at all; on a fresh one it silently
decided what got written to disk, permanently, without saying so; and two
sets naming different vibes over one song gave whichever ran first. It lives
on the **Shows** tab now, in the box above the track list, where it applies
to the next Claude compile and you can see the show it produced.

The **end scene** is the part that is not obvious. Stopping normally restores
every light to what it was before the show started, which is right when the
show interrupted an evening and wrong at 1am — what people want then is
"everything off" or "night lights", which is a Home Assistant scene they
already have. Name one and stopping calls it *instead* of restoring. A scene
that fails to run falls back to restoring, so the room never keeps the party
colours.

A party that names lights uses only those; everything else on the map is left
alone for the night.

Every analyzed track in the scanned folders, shuffled, each played with its
own show and its own clock anchor — playlist sync never depends on predicting
a track boundary through an AirPlay buffer. While one track plays, the next
one's choreography compiles in the background, so a designed show is ready
the moment it is needed; a track whose compile fails simply plays its floor
show, and a track that fails outright skips to the next. One bad file must
not end the night.

---

## Configuration options

### `music_folder`

*Default: `/media/music`.* Where your music lives, under Home Assistant's
`/media` folder. Scanned all the way down, so subfolders are already
included.

### `additional_music_folders`

*Default: empty.* More folders to scan, one per line, e.g. `/media/parties`.
Overlapping folders are fine: a track two folders both reach is listed and
analyzed once, because tracks are identified by content. Folders ticked in
the Library tab's browser are added to these — neither replaces the other.

They must be under `/media`, and that is not an arbitrary restriction. A show
plays its track by handing your media player a media-source link, and Home
Assistant only serves those for files inside its media folder — so a folder
anywhere else would analyze perfectly and then never play a note. If your
music lives elsewhere on the machine, point Home Assistant's own `media_dirs`
at it (and keep a `local:` entry for `/media`, which is what BRight builds its
links from).

### `director_mode`

*Default: `auto`.* Who choreographs each track:

- `auto` — Claude designs the show when **brAIn** is installed (BRight
  delegates through brAIn's task interface, so there is no second login);
  the built-in algorithmic choreographer is the fallback *and* the floor, so
  a show always compiles.
- `algorithmic` — never call Claude.
- `claude` — Claude only; compiling fails with the reason rather than
  silently downgrading.

**What Claude is told.** The whole light map, per light: its id, its name,
its role, its zone, where you put it on the floor plan, and whether it is a
LIFX bulb or a switch. Plus the travel orders already worked out — the
actual left-to-right order of your lights, the front-to-back order, and a
walk around the room from each light to its nearest neighbour — because
sorting a dozen coordinates is exactly the kind of arithmetic a language
model does badly and confidently. It designs for the room you drew, and it
can name a light rather than only a kind of light. It also gets the song's
measured accents — the strongest hits that sit exactly on the beat — and a
`"snap": "beat"` it can put on any moment, so a stab lands where the ear
expects it rather than only at section changes. The algorithmic
choreographer reads the same accents and places up to six of its own.

**Writing a single effect.** The Effects tab has a **Describe it** box:
say what you want in a sentence ("bounce a warm pulse between the two
window lamps") and Claude writes the effect into the form, for this room.
It lands unsaved — preview it, change anything, then save it as a preset or
drop it into a show. This needs brAIn too; everything else in the tab works
without it.

### `director_model`

*Default: `opus`.* Which Claude model writes and revises shows and effects
(any tier alias or model id brAIn's login can run — `opus`, `sonnet`, or a
full model id). Choreography is the one place BRight spends a big model on
purpose: a show is written once and watched many times. This rides into
brAIn's task as its `model` field; everything else brAIn does for you keeps
its own settings.

### `enable_ha_integration`

*Default: on.* Deploys the companion `bright` integration and runs the bridge
that carries service calls: `bright.party_mode`, `bright.start_show`,
`bright.stop_show`, and the show-status sensor. Turn it off and the panel
still works; nothing in Home Assistant can drive it.

### `log_level`

*Default: `info`.* Verbosity of the add-on's own logging. Use `debug` when
diagnosing a problem.

---

## Services

### `bright.party_mode`

Every analyzed track, shuffled, each with its own show.

| Field | Required | Meaning |
|---|---|---|
| `media_player` | no | Defaults to the most recently calibrated speaker |
| `folder` | no | One folder under `/media` for this party; defaults to every scanned folder |
| `party` | no | The name of a saved set; its settings fill in anything not given here |
| `tracks` | no | Exact track hashes, in play order; replaces the folder scan |
| `end_scene` | no | A scene to call when it stops, instead of restoring the lights |
| `shuffle` | no | Play the folder in order instead, with `false` |

### `bright.start_party`

Run a saved set by name. The name is **required** here, which is what makes
an automation fail loudly on a typo instead of quietly playing the default
folder.

| Field | Required | Meaning |
|---|---|---|
| `party` | yes | The saved set's name, as it appears in the Party tab |
| `media_player` | no | Override the speaker this set normally plays on |
| `end_scene` | no | Override the scene called when it stops |

### `bright.start_show`

| Field | Required | Meaning |
|---|---|---|
| `track` | yes | Path under `/media` (the panel can also pass a track hash) |
| `media_player` | no | Defaults to the most recently calibrated speaker |

### `bright.stop_show`

Stops the show and puts the room back.

| Field | Required | Meaning |
|---|---|---|
| `scene` | no | Call this scene instead of restoring the lights |

With no `scene`, every light goes back to the state it was in beforehand —
unless the running party named one, which is then used.

A service that cannot do what you asked **fails with the reason** — "no
analyzed tracks in /media/music — run the Library tab first" appears in the
automation trace, rather than a green tick and a dark room.

```yaml
automation:
  - alias: "Start party mode"
    triggers:
      - trigger: conversation
        command: "start party mode"
    actions:
      - action: bright.party_mode
        data:
          media_player: media_player.living_room
```

```yaml
automation:
  - alias: "Saturday night, and lights out afterwards"
    triggers:
      - trigger: conversation
        command: "start saturday night"
    actions:
      - action: bright.start_party
        data:
          party: "Saturday Night"
```

### Entities

The integration adds a show-status sensor reporting what is playing, the
media player it is on, and the position within the track. A show that failed
to start reports `error` with the reason in its attributes rather than
claiming to be running.

Its attributes are what a dashboard should key on rather than the state
string: `active` is the add-on's own answer to "is a run in progress" and
`lights_busy` to "are cues still going out", so a template button can offer
Stop exactly when the panel does. `party` names the running party,
`queue_left` counts the tracks after this one, `cues_sent`/`cues_total`
track progress, and `parties` lists every saved party's name.

```yaml
type: button
name: Stop the party
tap_action:
  action: perform-action
  perform_action: bright.stop_show
  data:
    scene: scene.good_night
visibility:
  - condition: state
    entity: sensor.bright_show_status
    attribute: active
    state: true
```

---

## When nothing plays

This is the most common problem, it is almost never BRight, and there is one
setting behind most of it.

**Press Test playback on the Calibrate tab first.** It walks the whole chain
and names the step that broke. The rest of this section is what those steps
mean.

### The host step: Chromecast, Google and Nest speakers

Home Assistant does not hand your speaker a file. It hands it a **URL**, and
the speaker fetches it over the network by itself. The address in that URL
comes from **Settings → System → Network → Internal URL**, and:

> Chromecast, Google Home and Nest speakers resolve names using **Google's
> public DNS (8.8.8.8)**, not your router's.

So an internal URL of `http://homeassistant.local:8123` — which a great many
installs have — is a name the speaker asks Google about and is told does not
exist. Nothing plays. Nothing errors. Home Assistant accepted the command and
the speaker quietly failed to fetch anything.

**The fix:** set the internal URL to an IP address —
`http://192.168.1.50:8123` — under Settings → System → Network. Leaving it
*empty* also works: Home Assistant then uses the machine's own IP, which
speakers can fetch.

HTTPS with a certificate the speaker cannot verify (a self-signed one, or one
issued for a name the speaker cannot resolve) fails the same silent way.

### The media step: "Home Assistant will not resolve…"

BRight plays a file by handing Home Assistant a media id built from where
the file sits under `/media` — `media-source://media_source/<source>/<path>`.
That `<source>` is the name Core gives the media directory, and it is
`local` **by default**. Set `media_dirs` in `configuration.yaml` and the
default is *replaced*: the source is called whatever your key says, and
every id built with `local` comes back `Unknown source directory`. Nothing
plays at all — not the click track, not a single song.

BRight works the name out for itself. It writes the click track (a file it
knows is there), then asks Core to resolve it under each media source Core
reports until one answers, and remembers which. Core does not publish the
filesystem path behind a source, so which one is your `/media` is not
something that can be read — only tried.

So on nearly every install this needs nothing from you. Two cases do:

- **You changed `media_dirs` while the add-on was running.** Lab → Test
  playback picks the new name up on the next try; **Look again** under the
  result forces it immediately. No restart.
- **None of Core's media directories is the folder BRight writes to.** Then
  the message names the ones Core does have, and one of them has to point
  at the same folder the add-on sees as `/media`:

  ```yaml
  homeassistant:
    media_dirs:
      local: /media      # BRight writes here; Core has to serve from here
      nas: /mnt/nas
  ```

  The names do not matter — `local` is not required — but one entry has to
  be that folder, or Home Assistant has no way to serve what BRight writes.

### The file step: "could not write the click track"

`/media` belongs to root and the panel runs as a non-root user, so BRight
creates `/media/bright` for itself at startup. If that failed, the message
names the folder. Check that Home Assistant's media folder exists (Settings →
System → Storage, or just look for a **media** folder in the file editor) and
restart the add-on.

### The player step: "does not accept play_media"

Some entities look like media players and cannot be sent media — group
members, some remotes and TV inputs. Pick a different entity.

### It plays, but the lights are early or late

That is calibration, not playback. Re-run **Play clicks & listen**, or use
the per-speaker fine-tune nudge under **Stored profiles** (negative moves the
whole show earlier).

---

## Other things that go wrong

**No bulbs discovered.** LIFX discovery is a UDP broadcast; the bulbs must be
on the same subnet as Home Assistant, and some managed switches and mesh
systems drop broadcast traffic between bands or VLANs. BRight sets
`host_network: true` precisely so the broadcast leaves the machine properly.

**"No LIFX bulbs known — run Lab discovery first."** A compiled show needs to
know which bulbs exist. Discover in the Lab, place them on the Light Map, and
re-compile.

**"Track not analyzed."** Run the Library tab's analysis first; shows compile
from the analysis, not from the audio.

**A track fails to analyze.** The reason is reported per file and the folder
carries on. Corrupt files, zero-length files and formats ffmpeg cannot decode
are the usual causes.

**The add-on will not start: `address in use`.** Fixed in 0.8.1 — the
Supervisor now assigns BRight's panel port. If you are on an older version,
update.

**It will not install: `'AddonManager.install' blocked from execution, no host
internet connection`.** This is not BRight — it is the Supervisor refusing the
install *job* before it reaches the add-on at all. Every install carries an
`internet_host` condition, and when the Supervisor's own connectivity probe
says the host is offline the job is blocked, whether or not the machine really
is. It is a common false negative: people hit it while `ping` and `curl` work
fine from the same box.

DNS is the usual cause — most often when the DNS server is itself an add-on
(Pi-hole, AdGuard) that is down or filtering the check. From the Terminal or
SSH add-on:

```bash
ha network info          # host connectivity
ha supervisor info       # look for  connectivity: false
ha resolution info       # the reasons, named

ha dns reset && ha dns restart          # usual fix
ha supervisor reload                    # re-run the check, then retry
```

If the probe is simply wrong and you want to get on with it, the condition can
be waived for the install and then put back:

```bash
ha jobs options --ignore-conditions internet_host
# install BRight, then restore the protection:
ha jobs reset
```

Since 0.9.1 the install pulls a prebuilt image rather than building the
container on your machine, so once the job is allowed to run it is a download
rather than a long `apk`/`pip` build. That makes the install far less likely
to die partway on a slow or flaky connection — but it does not affect the
block above, which happens first.

---

## Networking, and why the panel is locked down

BRight runs with `host_network: true` — LIFX discovery is a UDP broadcast on
port 56700 whose replies come back to the sender's own address, and a bridged
container never hears them. Cue latency is the product, and host networking
is also what keeps cue packets off a NAT path.

That puts the panel on a real port on your machine, reachable from every
device on the LAN. So the panel **refuses every caller except Home Assistant
itself** — the Supervisor's own networks and loopback, matched on the
connection's real peer address rather than on any header a caller can set.
There is no public endpoint at all. Open the panel from the Home Assistant
sidebar.

The panel's port is assigned by the Supervisor rather than fixed, because a
port written into a manifest is a port something else on your machine may
already own. The startup log names the one it got:

```
Starting BRight panel on 0.0.0.0:8124
```

---

## Where BRight keeps things

| Path | What |
|---|---|
| `/media/<your folders>` | Your music. BRight only ever reads it. |
| `/media/bright/calibration.wav` | The click track, regenerated when missing |
| `/config/.bright/` | The shared folder the integration talks through, plus the mirrored show state |
| `/config/custom_components/bright/` | The companion integration, deployed at startup |
| `/data/shows/<hash>/` | Per-track analysis, script and compiled show |
| `/data/calibration/` | One profile per speaker |
| `/data/light-map.json` | The lights, their roles and positions |
| `/data/music-folders.json` | Folders ticked in the Library tab |
| `/data/effect-presets.json` | Effects saved in the Effects tab |
| `/data/parties.json` | Saved parties |
| `/config/.bright/shows/` | Every show script, mirrored where you can edit it |

Everything under `/data/shows` and `/data/cache` is regenerable build output
and is excluded from Home Assistant backups deliberately — a backup that
carries them is bigger for nothing.

Nothing BRight does is destructive to your Home Assistant configuration, and
restarting the add-on is always safe.
