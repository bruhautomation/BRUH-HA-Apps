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

Bulbs discovered in the Lab arrive with **Add discovered bulbs** (it never
overwrites a light you have already placed). Party lights and lasers on
switches are added by entity with **Add a switch light…**.

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

### Shows — compiled choreography

One show per track, compiled ahead of time so playback is nothing but a clock
and a cue list. Compile after changing the Light Map — the show is built for
the lights that existed when it was compiled. Playing needs a calibrated
speaker.

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

### `bright.start_show`

| Field | Required | Meaning |
|---|---|---|
| `track` | yes | Path under `/media` (the panel can also pass a track hash) |
| `media_player` | no | Defaults to the most recently calibrated speaker |

### `bright.stop_show`

Stops the show and restores every light to the state it was in beforehand.

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

### Entities

The integration adds a show-status sensor reporting what is playing, the
media player it is on, and the position within the track. A show that failed
to start reports `error` with the reason in its attributes rather than
claiming to be running.

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

BRight builds `media-source://media_source/local/<path>` from where a file
sits under `/media`. `local` is the default id of Home Assistant's local
media source — but if you set `media_dirs` in `configuration.yaml`, that
default is *replaced*, and the id may be something else entirely. Core then
answers with its own HTTP 500, which used to arrive as a bare number.

**The fix:** keep a `local:` entry pointing at `/media`:

```yaml
homeassistant:
  media_dirs:
    local: /media
    nas: /mnt/nas
```

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

Everything under `/data/shows` and `/data/cache` is regenerable build output
and is excluded from Home Assistant backups deliberately — a backup that
carries them is bigger for nothing.

Nothing BRight does is destructive to your Home Assistant configuration, and
restarting the add-on is always safe.
