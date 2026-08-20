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
  shows will.
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
| `aux` | Party lights and lasers: on, off, or flashed on the beat. |

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

**The show, as a picture.** Select a track and the show opens as what it is:
your room on the floor plan at the top, the whole song as a strip beneath it
with one row per light, the scenes as blocks across the top of that strip,
and the effects as rows you can press.

Drag the scrub bar and the room shows you that instant. Press ▶ and the show
plays through at real speed — on the screen, not on the bulbs, so you can
read a show at midday without lighting the house up. Press a scene block to
jump to it.

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

### Party — the sentence the add-on was built for

Pick a calibrated player, type a vibe if you want one, press the button.
The Stop button is not there when nothing is running: a button that is
always present is a button nobody trusts, so it renders only while the
add-on says a run is actually in progress, and the line beside it says what
is playing and how far through the queue it is.

**Saved parties** are the evening set up once — the speaker, the folder, the
vibe, which lights may join in, and what the room should look like when it
stops. Start one from the list, from an automation with
`bright.start_party`, or by voice. Anything given at the time still wins
over what the party saved, so "the usual thing, but on the kitchen speaker"
works.

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
| `vibe` | no | A steer for the Claude director, e.g. `chill`, `rave`, `halloween` |
| `party` | no | The name of a saved party; its settings fill in anything not given here |
| `end_scene` | no | A scene to call when it stops, instead of restoring the lights |
| `shuffle` | no | Play the folder in order instead, with `false` |

### `bright.start_party`

Run a saved party by name. The name is **required** here, which is what makes
an automation fail loudly on a typo instead of quietly playing the default
folder.

| Field | Required | Meaning |
|---|---|---|
| `party` | yes | The saved party's name, as it appears in the Party tab |
| `media_player` | no | Override the speaker this party normally plays on |
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
          vibe: "rave"
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
