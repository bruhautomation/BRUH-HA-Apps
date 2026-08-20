# BRigt

> ## ⚠️ Under active development
> **BRigt is not finished.** Features described below may be partial,
> missing, or broken, and updates may change behavior without ceremony.
> Treat every release as a preview until this banner goes away.

Music-driven light show director: local music in, compiled light shows out,
everything in sync with the speaker actually playing the music.

## Options

### `music_folder`

Where your music lives, under Home Assistant's `/media` folder (default
`/media/music`). BRigt scans it — all the way down, so subfolders are
already included — for tracks to analyze, and plays the same files through
your media player during a show.

### `additional_music_folders`

More folders to scan, beside `music_folder`. One per line, e.g.
`/media/parties`. Overlapping folders are fine: a track that two folders
both reach is listed and analyzed once, because BRigt identifies tracks by
their contents rather than by their path.

They must be under `/media`, and that is not an arbitrary restriction. A
show plays its track by handing your media player a media-source link, and
Home Assistant only serves those for files inside its media folder — so a
folder anywhere else would analyze perfectly and then never play a note.
If your music lives elsewhere on the machine, point Home Assistant's own
`media_dirs` at it (or move it under `/media`) and BRigt can use it.

### `director_mode`

Who choreographs each track:

- `auto` (default) — Claude designs the show when **brAIn** is installed
  (BRigt delegates through brAIn's task interface, so there is no second
  login); the built-in algorithmic choreographer is the fallback and the
  floor, so a show always compiles.
- `algorithmic` — never call Claude.
- `claude` — Claude only; compiling fails with the reason rather than
  silently downgrading.

### `enable_ha_integration`

Deploys the companion `brigt` integration: the `brigt.party_mode`,
`brigt.start_show` and `brigt.stop_show` services and a show-status sensor.

### `log_level`

Verbosity of the add-on's own logging.

## Networking

BRigt runs with `host_network: true` — LIFX discovery is a UDP broadcast on
port 56700 and cue latency is the whole product, so the container sits on
the LAN directly. The panel is therefore reachable from the LAN too; it
refuses every caller except Home Assistant itself (the Supervisor's networks
and loopback), so there is nothing to open from the LAN. Open it from the
Home Assistant sidebar.

**The panel's port is not fixed, and does not need to be.** Because the
container is on the host network, the panel's port is a real port on your
machine rather than one inside a container, so any number BRigt picked could
already belong to something else you run — which is what happened: an early
build pinned 8095 and, on a machine where something else already had 8095,
the panel could not start at all. Home Assistant has an arrangement for
exactly this, and BRigt now uses it: the Supervisor assigns a free port when
the add-on is installed, and BRigt asks which one at startup. Nothing to
configure, and nothing to collide with. The startup log names the port it
got:

```
Starting BRigt panel on 0.0.0.0:8124
```

If that port ever does get taken by something else, the log says so in one
sentence naming the port, rather than a Python traceback.

## The Library

Point `music_folder` at your music and press **Analyze new tracks** on the
Library tab. Each track is analyzed once — tempo and beat grid, song
sections and drops, synced lyrics from LRCLIB when they exist — and cached
by content (renaming files doesn't re-analyze). Analysis runs as a
background job with per-track progress; one bad file is reported and
skipped, never the end of the folder.

## Calibration

Every speaker adds latency between "play" and audible sound — AirPlay
around two seconds, and no API reports it. The Calibrate tab measures it:

1. Open the panel **on your phone**, in the room with the speaker.
2. Pick the media player and press **Play clicks & listen**. The add-on
   plays a 13-second click track; your phone records it; the offset is
   computed by cross-correlation and stored for that player.
3. No microphone access (plain-HTTP setups)? Use **Play clicks & tap** and
   tap along — coarser (your reaction time rides in), but workable.

Run it once per speaker, and again if a show ever feels consistently early
or late (speakers can renegotiate their buffers between sessions). The
stored profile keeps a median across runs plus a fine-tune nudge you can
set per player.

The click track is written to `/media/brigt/calibration.wav`, because your
speaker fetches it from Home Assistant rather than from the add-on — a
Chromecast or an AirPlay speaker has no route to BRigt's panel, and would
not be allowed through it if it did. BRigt creates that folder at startup.
If the wizard reports that it could not write the click track, the message
names the folder: check that Home Assistant's media folder exists, and
restart the add-on.

## Services

- `brigt.party_mode` — every analyzed track in the folder, shuffled, each
  with its own show; the next track's choreography compiles while the
  current one plays. Optional `media_player` (defaults to the most
  recently calibrated), `folder` (defaults to the `music_folder` option),
  and `vibe` (a steer for the Claude director, e.g. "halloween").
- `brigt.start_show` — one track (`track` path under /media or, from the
  panel, a track hash; optional `media_player`).
- `brigt.stop_show` — stop and restore every light to its pre-show state.

An automation that starts the party on a voice phrase or a button:

```yaml
automation:
  - alias: "Start party mode"
    triggers:
      - trigger: conversation
        command: "start party mode"
    actions:
      - action: brigt.party_mode
        data:
          media_player: media_player.living_room
```

## The order things want to happen in

1. **Lab** — discover your bulbs, probe their round-trip times, measure a
   switch's service latency, run the waveform demo.
2. **Calibrate** — once per speaker, phone in hand.
3. **Library** — analyze the music folder.
4. **Light Map** — place the lights, set roles.
5. **Shows** — compile, play one, judge it in the room ("Sync proof" in
   the Lab plays a bare metronome show when you want the chain without
   the choreography).
6. **Party** — one button, or one automation.
