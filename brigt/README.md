# BRigt — light show director for Home Assistant

> ## ⚠️ Under active development
> **BRigt is being built in the open and is not finished.** Features
> described here may be partial, missing, or broken, and updates may change
> behavior without ceremony. Install it to follow along and experiment —
> not (yet) to run the party. If something misbehaves, restarting the
> add-on is safe: shows and analysis are regenerable, and nothing BRigt
> does is destructive to your Home Assistant config.

Point BRigt at a folder of your music. It analyzes every track — tempo, the
beat grid, onsets, energy, song sections and drops, plus time-synced lyrics —
and a director compiles a choreographed light show for *your* lights ahead of
time. Say "start party mode" and the music plays on your speaker while LIFX
bulbs (driven directly over the LAN, not through service calls) and
switch-driven party lights run the show in sync.

## Why it's built the way it is

- **LIFX over the LAN, not through Home Assistant.** Service calls add more
  latency than a beat can absorb. BRigt speaks the LIFX UDP protocol
  directly, and pushes beat-locked effects *onto the bulbs* (LIFX waveforms),
  so the network only carries scene changes and hits.
- **The speaker is the slow part, and it's measured, not guessed.** AirPlay
  buffers roughly two seconds and no API reports it. BRigt's calibration
  wizard plays a click track and listens through your phone's microphone to
  measure the real offset per media player.
- **Everything expensive happens before the party.** Analysis and
  choreography are compiled to a cue file per track; at show time the engine
  is just a clock and a cue list.

- **Nothing reports a success it cannot know about.** Home Assistant
  accepting a play command is not a speaker making a sound, so BRigt follows
  the command until the player says it is playing — and says so plainly when
  it never does, instead of running a light show at a silent room.

## Status

The whole chain is in place and being tuned against real houses: the Lab
(latency probes, waveform demo), phone-mic speaker calibration, the
analyzer (beats, sections, drops, synced lyrics), the light map, the
algorithmic and Claude director tiers, single-track shows, and party mode
end to end. See CHANGELOG.md for the phase-by-phase story — and the
warning above still stands.

## What you need

Home Assistant 2023.6+ with the add-on store, audio files under `/media`, a
`media_player` entity, and LIFX bulbs and/or party lights on HA switches.
The [brAIn](../brain) add-on is optional and upgrades the choreography from
the built-in algorithm to Claude.

## Installation

Add this repository to the Home Assistant add-on store and install BRigt.
The companion integration deploys itself on first start — accept the
discovered integration under Settings → Devices & Services.

Then open the panel and press **Test playback** on the Calibrate tab. It
walks the whole chain from the file on disk to the speaker actually playing,
and names whatever is in the way — which on a Chromecast is usually Home
Assistant's *Internal URL* being a `.local` name that Google's DNS cannot
resolve. [DOCS.md](DOCS.md) has the full setup, every configuration option,
the services, and a troubleshooting section for when nothing plays.
