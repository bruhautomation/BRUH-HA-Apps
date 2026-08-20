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
`/media/music`). BRigt scans it for tracks to analyze and plays the same
files through your media player during a show.

### `director_mode`

Who choreographs each track:

- `auto` (default) — Claude designs the show when a Claude Code login is
  available; the built-in algorithmic choreographer is the fallback, so a
  show always compiles.
- `algorithmic` — never call Claude.
- `claude` — Claude only; compiling fails without a working login rather
  than silently downgrading.

### `enable_ha_integration`

Deploys the companion `brigt` integration: the `brigt.party_mode`,
`brigt.start_show` and `brigt.stop_show` services and a show-status sensor.

### `log_level`

Verbosity of the add-on's own logging.

## Networking

BRigt runs with `host_network: true` — LIFX discovery is a UDP broadcast on
port 56700 and cue latency is the whole product, so the container sits on
the LAN directly. The panel (port 8095) is therefore reachable from the LAN
too; it refuses every caller except Home Assistant itself (the Supervisor's
networks and loopback). Open it from the Home Assistant sidebar.

The panel binds 8095 rather than the family's usual 8099 because BRUH
Minecraft also runs on the host network and already owns 8099.

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

## Services

- `brigt.party_mode` — play a folder and run each track's show. Optional
  `media_player`, `folder`, `vibe`.
- `brigt.start_show` — one track (`track`, optional `media_player`).
- `brigt.stop_show` — stop and restore every light to its pre-show state.

In the 0.1.0 skeleton these services answer that shows aren't available
yet; they go live with the playback engine.
