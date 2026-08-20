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

## Status

The whole chain is in place and being tuned against real houses: the Lab
(latency probes, waveform demo), phone-mic speaker calibration, the
analyzer (beats, sections, drops, synced lyrics), the light map, the
algorithmic and Claude director tiers, single-track shows, and party mode
end to end. See CHANGELOG.md for the phase-by-phase story — and the
warning above still stands.

## Installation

Add this repository to the Home Assistant add-on store and install BRigt.
The companion integration deploys itself on first start — accept the
discovered integration under Settings → Devices & Services.
