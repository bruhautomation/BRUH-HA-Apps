# Changelog

All notable changes to the **BRigt** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.8.3

No behaviour change. Two code-scanning findings from 0.8.2, closed rather
than left open — an alert nobody intends to act on is what teaches people
to stop reading the list.

### Changed
- `reference.ensure`'s `except OSError: pass` says what it is passing on:
  no file, or nothing readable where one should be, both of which mean
  "write it" — the same answer as a wrong length. A folder that cannot be
  written still raises, from the write below, where the caller expects it.
- The playback test that awaited a deliberately doomed show asserts the
  refusal it was swallowing (`assertRaises`) instead of passing on it.

## 0.8.2

Casting the click track answered `HTTP 500` and played nothing — and music
could only ever live in one folder.

### Fixed
- **The calibration click track can be written again.** `/media` belongs to
  root on a Home Assistant install and BRigt's panel runs as the `brigt`
  user, so creating `/media/brigt` raised a permission error the moment
  anyone pressed **Play clicks & listen**. aiohttp turned that into a bare
  `500 Internal Server Error` with no body, which is all the wizard could
  report — a number, about a folder it never named, for a file that was
  therefore never there to stream. run.sh creates the folder as root at
  startup and hands it to the panel.
- **A click track that still cannot be written says so in a sentence** that
  names the folder and what to do, instead of a traceback. So does a refusal
  from Home Assistant: it now quotes the media id it was asked to play,
  because Core answers an unresolvable media with *its own* HTTP 500, and
  that number arriving as our error message is what made a missing file look
  like a panel crash.
- **The click track is rendered once, not on every press.** It is half a
  million samples through a Python loop — 1.6s on a laptop and several times
  that on a Pi, paid inside the request every time — and the file is a pure
  function of the pattern, so a file that is already the right length is
  already the right file. A short one (a write cut off by a restart) is
  rewritten rather than played. Packing it through `array` instead of
  per-sample `struct.pack` cuts the render itself to a quarter, byte for
  identical byte.

- **A show that cannot start says so.** `start()` answers the request the
  moment the task exists — a show runs for minutes and a request cannot — so
  a play command the speaker refuses raised out of sight, and the panel went
  on reporting "Running: 412 cues" over a dark room. The only trace was
  asyncio's "Task exception was never retrieved" when the dead task was
  collected. The error now lands in the show state the panel polls and the
  HA sensor reads, and the lights are put back: the snapshot was taken
  before the play command, and restoring is the other half of an ending
  nobody watched.

### Added
- **`additional_music_folders`** — more folders to scan for music beside
  `music_folder`, listed one per line. Overlapping folders cost nothing: a
  track two folders both reach is listed and analyzed once, because tracks
  are identified by content rather than by path. Subfolders never needed an
  entry — each folder is scanned all the way down — and the Library tab now
  lists the folders it is scanning, saying which of them are missing.
- Every folder is confined to `/media`, and the docs say why rather than
  just that: a show plays its track by handing the media player a
  media-source link, which Home Assistant only serves for files under its
  media folder. A folder outside it would analyze perfectly and never play.

## 0.8.1

The add-on could not start on a machine where something else already had
port 8095 — and nothing about the failure said so in a sentence.

### Fixed
- **The panel no longer pins a host port.** `host_network: true` means the
  panel binds a *real* port on the machine, not one inside a container, so
  the 8095 written into config.yaml was a number some other service could
  already own. On a machine where one did, every boot ended the same way:
  `[Errno 98] address in use`, the panel dead, the container exited, the
  Supervisor restarting it, and the next attempt asking the same host for
  the same taken port — a refusal that could not change the next attempt.
  `ingress_port: 0` now asks the Supervisor to assign a free port, which is
  what Home Assistant documents for add-ons on the host network, and the
  panel reads the assigned port back from `/addons/self/info` at startup.
- **One port, resolved once** (`panel/panel_port.py`). run.sh logs and
  announces it, the panel binds it, and the HA bridge posts show commands to
  it — a second copy of that lookup is a bridge posting into nothing, so
  there is one, and run.sh exports the answer into `/data/.brigt_env` where a
  `with-contenv` child can still read it.
- **A port that cannot be taken now ends in a sentence naming it**, not an
  aiohttp traceback underneath a log line that had already claimed the panel
  was listening on it. The bind is attempted *before* that line is written,
  and retried a few times first — the one holder worth waiting out is a
  previous panel that has not finished dying.

### Changed
- **No `watchdog:` URL** — the Supervisor's placeholder needs a port number
  written into config.yaml, and a watchdog still pinned to 8095 would poll
  whatever service actually holds 8095 and restart BRigt on its behalf.
  run.sh polls `/api/health` on loopback instead, where it knows the real
  port: four consecutive misses, thirty seconds apart, and the panel is
  taken down so the Supervisor's restart-on-stop brings it back. A hung
  panel is still caught; nothing else is.
- **Nothing on the panel is public any more.** `/api/health` was reachable
  without Home Assistant because the Supervisor watchdog polled it from
  off-network. Its replacement runs inside the container, over loopback,
  which the LAN gate already trusts — so the exemption lost its only caller
  and went with it.

## 0.8.0

Party mode — the sentence the whole add-on was built for: "start party
mode", and the house takes it from there.

### Added
- **`brigt.party_mode`, end to end**: every analyzed track in the folder
  (or a given one), shuffled, each played with its own show and its own
  clock anchor — playlist sync never depends on predicting a track
  boundary through an AirPlay buffer. While one track plays, the NEXT
  one's choreography compiles in the background (Claude tier when brAIn
  is there), so a designed show is ready the moment it's needed; a track
  whose compile fails simply plays its floor show. A failed track skips
  to the next — one bad file must not end the night. Optional `vibe`
  ("chill", "rave", "halloween") steers the Claude director.
- **Party tab**: pick a calibrated player, type a vibe, one button — plus
  live show state while it runs. Stop restores every light.
- An example automation in DOCS ("start party mode" as a conversation
  trigger) and "the order things want to happen in" — Lab → Calibrate →
  Library → Map → Shows → Party.

## 0.7.0

The Claude director — creative choreography per track, with the
algorithmic tier as the ever-present floor.

### Added
- **Claude-designed shows through brAIn.** BRigt carries no Claude CLI
  and asks for no second login: when brAIn is installed on the same Home
  Assistant, its automation-task surface is already a signed-in Claude,
  so BRigt hands it the track's digest — sections, drops, BPM, the
  fixture roster with roles and positions, and up to 60 synced lyric
  lines — plus the exact script schema, and gets choreography back.
  The model writes a *script* (scenes, motifs, lyric moments); the wire
  budget stays the compiler's, and every answer passes the same schema
  validator or that track falls back to the algorithmic tier, logged.
- `director_mode` now does what it says: `auto` uses Claude when brAIn is
  there and the floor otherwise (per track — one bad answer never blocks
  a playlist); `claude` is strict and fails with the reason instead of
  downgrading; `algorithmic` never calls anyone.
- Lyric-aware moments: the director is asked to pick up to four
  `lyric_moment` features at lines that deserve a visual answer.

### Fixed
- The light-map loader's silent fallback carries its explanation
  (CodeQL).

## 0.6.0

The director, first tier: a real choreographed show per track, compiled
from the light map.

### Added
- **Light Map tab**: drag each light where it lives (left↔right is what
  sweeps travel across), set its role — candle, downlight, lamp, strip,
  party, laser. Discovered bulbs import with one press and never overwrite
  a placement you've made; switch-driven lights (party light, laser) join
  as HA entities.
- **The algorithmic choreographer**: sections become scenes (palette from
  the track's own brightness, intensity from the section's energy tier),
  beats become on-bulb pulses, peaks earn sweeps across the room and the
  party lights, drops get a blackout-then-hit with the lasers — and it is
  deterministic: the show someone liked on Friday is the show they get on
  Saturday.
- **THE compiler** (one for every future tier): scripts become
  pre-serialized cue timelines — waveforms carry the beats (a pulsing
  scene is ~2 packets a minute per bulb), LIFX leads are half the probed
  RTT, aux leads are the Lab's measured service latency per entity, and
  the 20 msgs/s ceiling is enforced at compile time: a script that asks
  for more motion than the wire carries fails loudly, never at the party.
- **Role rules with taste**: candles cap at 45% and never strobe; lasers
  and party lights only fire for peaks and drops.
- **Shows tab**: compile per track, see tier/palette/cue stats, play on a
  calibrated speaker, stop-and-restore.
- The script schema validator that every future Claude-authored show must
  pass — anything malformed lands on the algorithmic floor per-track
  (or fails honestly in strict `director_mode: claude`).

## 0.5.0

The playback engine, proven with a metronome. Sync is demonstrated end to
end — calibrated speaker, anchored clock, cues on the wire — before any
choreography exists to blame or credit.

### Added
- **The show clock**: track time 0 = play command + the speaker's measured
  offset, on a monotonic clock. Drift corrections *slew* (max 8ms per
  second) and never step — a step is every light stuttering at once.
- **Drift correction**, gated three ways: only players the calibration
  wizard proved report a usable position, never on a single report, never
  inside a 60ms deadband, and a wildly implausible report is treated as a
  lie (paused player, stale attribute) rather than a drift.
- **The conductor**: one show at a time from a compiled cue list — sleeps
  to each cue's send moment (its `t` minus its own lead time), stamps a
  live sequence number into the pre-built packet, sends fire-and-forget
  (idempotent scene cues go twice, 30ms apart, to survive UDP loss).
  Snapshots every fixture before the show and restores it on stop or end.
- **The metronome show** (Lab → "Sync proof"): every discovered bulb
  pulses on the analyzed beat grid of a real track — one `SetWaveform`
  per 8 beats, so the network carries ~2 packets a minute per bulb while
  the bulb keeps the time. This is the moment to stand in the room and
  judge the whole chain.
- `brigt.start_show` and `brigt.stop_show` are now LIVE end to end (HA
  service → file bridge → panel → lights): `start_show` plays a track's
  show (the metronome until the director lands), `stop_show` stops and
  restores. `party_mode` still answers honestly that it needs the
  director.

## 0.4.0

The analyzer — everything the director will choreograph from, computed
once per track and cached, so a show compiles from answers instead of
listening on the fly.

### Added
- **Beat tracking** (pure numpy — no librosa/numba on musl): spectral-flux
  onset envelope, autocorrelation tempo with octave correction, an
  exhaustive phase/tempo grid fit, and each grid beat snapped onto the
  actual onset under it. The envelope is aligned to audio time at the
  source (spectral flux answers FRAME/HOP bins early — measured, exactly
  2 bins — and every consumer reads the corrected timeline). Verified
  against synthesized drum tracks: tempo within 3%, beats within 40ms.
- **Features**: energy + low/mid/high band envelopes on one shared 20Hz
  grid, and a whole-track brightness hint for palette selection.
- **Sections & drops**: novelty-based boundaries labelled by honest energy
  tier (intro/quiet/mid/peak/outro — not guessed verse/chorus names), and
  drop detection (a sharp sustained jump out of a quieter stretch, led by
  bass).
- **Synced lyrics** from LRCLIB (free, keyless) by artist/title/duration;
  absence is an answer, never an error — instrumentals choreograph from
  the music alone.
- **Library tab**: scan the music folder (content-hashed identity, so a
  renamed file keeps its analysis), analyze new tracks as a background job
  with live per-track progress, per-track summaries (BPM, sections,
  drops, lyrics).
- ffmpeg + mutagen in the image (decode anything, read tags).

### Security
- Entity ids and track hashes are validated at every API boundary before
  they ever shape a filename (CodeQL path-injection findings addressed
  with strict patterns plus containment checks, not best-effort
  sanitizing).

## 0.3.0

Speaker calibration — the number no API reports, measured instead of
guessed. AirPlay buffers roughly two seconds before sound comes out;
every show is anchored at "play command + this measurement".

### Added
- **Calibration reference track**: eight sharp clicks at deliberately
  irregular offsets (a regular train correlates at every multiple of its
  period — the uneven pattern lines up exactly one way), written
  deterministically to `/media/brigt/calibration.wav`.
- **Phone-microphone wizard** on the Calibrate tab: the page syncs its
  clock to the add-on over a few pings, records raw PCM through WebAudio
  while the reference plays on the chosen media player, and uploads a WAV
  it builds itself (no codecs involved). The add-on cross-correlates the
  recording's onset envelope against the click pattern and stores the
  measured offset — with a z-score confidence gate, so a recording that
  didn't actually hear the clicks is refused rather than stored.
- **Tap-along fallback** for browsers that won't share a microphone over
  plain HTTP: tap on each click; the median tap error is the offset
  (reaction time rides along, and the stored run says which method made it).
- **Per-player profiles**: runs accumulate with median + spread, a
  fine-tune nudge rides on top of (never instead of) the measurement, and
  the same run checks whether the player reports a usable `media_position`
  — the drift corrector will only ever trust players that proved it here.
- A prominent **under-active-development notice** at the top of README
  and DOCS.

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
