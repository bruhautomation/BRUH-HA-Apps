# Changelog

All notable changes to the **BRigt** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.2.0

The Lab — real latency numbers from the real house, before anything is
built on top of them.

### Added
- **LIFX direct LAN control**, hand-serialized packets pinned byte-for-byte
  against the protocol documentation's own example, plus a discovery
  engine (broadcast `GetService`, then label/product/state per bulb).
- **RTT probe** per bulb: invisible `EchoRequest`s, p50/p95/loss — the
  numbers cue lead-times will be compiled from.
- **Sustained-rate ramp**: what each bulb actually sustains, found by
  stepping echo rates until loss appears (LIFX documents 20 msgs/s).
- **Waveform demo**: one `SetWaveform` packet makes a bulb pulse at a
  chosen BPM entirely on its own — the on-bulb effect mechanism the whole
  sync design rides on, made visible.
- **HA service-call latency probe**: toggles a chosen switch/light a few
  times (and puts it back), measuring call-to-state-change — how early an
  aux light's cues must be sent. Results persist into the Lab report.
- Per-device **rate governor** (token bucket at the documented ceiling)
  that every non-probe send goes through.
- A **Latency report** view assembling everything measured so far.

### Fixed
- CodeQL findings on the panel: the LAN gate's refusal log line now
  flattens line breaks with the same named `replace` chain the Minecraft
  panel uses, and the options reader's silent fallback carries its
  explanation.

## 0.1.0

The installable skeleton — the frame everything else bolts onto.

### Added
- The add-on itself: ingress panel on port 8095 (not 8099 — BRUH Minecraft
  already binds that host port, and both add-ons run `host_network: true`),
  Supervisor watchdog on `/api/health`, AppArmor profile, 6/6 security
  rating.
- `host_network: true` for direct LIFX LAN control (UDP 56700 broadcast
  discovery), with the panel gated to Supervisor networks and loopback —
  the LAN can see the port and may not drive it.
- Panel shell with the six tabs the product grows into: Lab, Light Map,
  Library, Shows, Calibrate, Party.
- Companion `brigt` custom integration (deployed automatically): the
  `brigt.party_mode`, `brigt.start_show` and `brigt.stop_show` services and
  a show-status sensor, over file IPC in `/config/.brigt/`. The services
  answer honestly that this build does not run shows yet.
- Options: `music_folder`, `director_mode` (auto / algorithmic / claude),
  `enable_ha_integration`, `log_level`.
- The BRigt brand set: the family's BR ligature under BRigt's own roof — a
  straight-plane gable with two light-beam knockouts — over IGT light-tube
  caps.
