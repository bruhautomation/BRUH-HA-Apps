# Changelog

All notable changes to the **BRight** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.19.0

Test mode, and a show that never loses the beat.

### Added

- **🧪 Test mode — beats & drops.** The Lab's sync proof grew the other
  half of the question: alongside the beat pulses, every selected bulb
  now goes dark just before each drop the analyzer heard and lands
  full-blast on the drop itself, then returns to the base. One run
  answers both "do the lights ride the beat" and "did the analyzer hear
  the drops where the music has them" — pulses late everywhere means
  nudge the calibration; a flash where the music does nothing means
  re-analyze the track. The Shows tab's per-track button is now labelled
  **🧪 Test** and plays the same thing.

### Changed

- **There is always a beat on some light.** Intros, quiet sections and
  outros now run the pulse layer too, and `plan_layers` guarantees a
  rhythmic layer lands in *every* section: when the taste plan strands
  the pulse (a candles-only room, a one-lamp room whose lamp the ground
  claimed), it shares the roomiest bulb role — or in a room too small to
  share, takes one outright, because if only one thing can happen it
  should be the beat.
- **A drop is the whole room.** The drop's stab used to pick a few roles
  at the drop's own detected strength, which read as one more accent. It
  now selects every bulb, with role manners off (the candles come too)
  and a strength floor of 0.85 — the room goes dark in the last breath
  before the drop and lands together, full on.
- **Shows and Party say which is which.** The Party tab's play card has
  a head like every other card, its Stop matches the Shows tab's
  wording, and both tab intros say what belongs where: build and test on
  Shows, press Play on an evening on Party.

### Fixed

- **The sync proof itself pulsed on the off-beat.** A LIFX sine waveform
  starts at the bulb's current level and peaks half a period in; the
  metronome anchored it ON the beat, so the one show whose job was the
  beat flashed between the beats — the same inversion the compiled
  `pulse` effect was cured of, now cured with the same `peak_shift`.
- **Discover no longer wipes the test's picks.** Rebuilding the Lab's
  lists kept the bulb ticks and forgot the chosen track and player, so
  "pick, pick, Discover, Start" answered "pick an analyzed track".
- **Revisiting the Party tab no longer drops the chosen speaker.** The
  player list rebuilt from scratch on every visit, and a lost pick fell
  back silently to whichever player calibrated best — a different room.
- **A dipped stab no longer strands its lights at 2%.** The stab's wave
  is transient — the bulb returns to its "current" colour when it ends,
  and the pre-stab dip *was* that colour — so every light a drop
  touched sat near-dark until something else happened to name it. The
  stab now hands each light back to the scene's palette at the scene's
  base level after its hold.
- **A candles-only room's peak carries a beat again.** The pulse layer
  picked a chase or theater alternation by fixture *count*, both of
  which the harsh-effect filter keeps candles out of — so the compiled
  beat drove zero lights. A role that does not pulse now takes the
  `hit` form, which candles are allowed to run.

## 0.18.1

The drum detector was returning nothing, on everything.

### Fixed

- **`detect_hits` found ZERO accents in ordinary music.** The peak-picking
  test was `punch > local + 0.10` — an absolute constant — but
  `band_flux` scales both bands by the FULL-band flux peak while `punch`
  sums only the two bands under 2kHz, about a hundred of a thousand FFT
  bins. So punch is structurally a small fraction of 1: measured on a
  clean, loud, isolated kick-and-snare loop it peaks at **0.0795**, and
  the bar it had to clear was 0.10. Not "few hits on quiet music" —
  none, on everything, since ranked accents shipped. Every effect built
  on them rendered nothing, which from a sofa is indistinguishable from
  a feature that does nothing. The threshold is now a percentile spread
  of the track's own punch, which cannot be wrong by a factor nobody
  notices.
- **`band` was decided by the band edges, not by the drum.** Under 250Hz
  is about a dozen FFT bins and 250–2000Hz is nearly a hundred, so
  comparing the raw sums said "mid" for almost every hit whatever it
  was, and `band: "low"` — the kick layer — selected nothing. The bands
  are scaled to each other now. Measured on three synthetic mixes (a
  bare loop, the same over a pad and a bassline, and one with the kick
  replaced by a second snare) every on-beat drum is classified correctly
  in all three.
- **An effect whose selection matched no light said nothing at all.** It
  compiled, it saved, it played, and the room stayed exactly as it was —
  the only trace anywhere was `0 lights` on a list nobody reads. The
  compiler names it on that effect's own row now. Roles and zones are
  also matched trimmed and case-insensitively, because "Inner Kitchen"
  and "inner kitchen" are one room and a capital letter is not a reason
  for a show to do nothing.

### Added

- **The tune runs across the room.** `melody` places each note by its
  PITCH within the track's own range rather than stepping to the next
  light, so a run up the scale is a run of light across the room and
  coming back down runs back — and a repeated note stays where it is
  instead of marching. `follow: "step"` keeps the old behaviour.
- **A party can pin which version of a show each song plays.** The
  default is whatever is live, so the newest is what plays without
  anyone choosing it; the picker on each row of the set is for the
  evening you want last month's version of one track.

### Changed

- **"What it compiled to" is gone.** It listed every effect in the show
  with its fixture and move counts — forty rows of numbers on a real
  show, pushing everything below it off the page. The effect lanes in
  the editor draw the same walk against the song, which is the form that
  answers a question. What is left is the exceptions: an effect that
  drives no lights, one whose analysis is too old, one whose waveform
  another effect cancels. When the show is fine, that block is empty.
- `ANALYSIS_VERSION` is **5**. Every library has to be re-heard — the
  hits in every analysis ever written are empty or near-empty, and the
  band field added in 0.18.0 was decided by a comparison that could not
  see the drum.

## 0.18.0

Lights with an attack, four layers, and the song on screen.

### Fixed

- **The beat pulse peaked on the OFF-beat, in every show BRight has ever
  compiled.** A LIFX waveform runs from the bulb's *current* colour to the
  one in the packet and back, so a sine anchored on the beat is at its
  dimmest exactly where the kick is and brightest halfway to the next one.
  The one effect whose entire job was "the beat" was inverted. Every shape
  now knows where in its cycle it is brightest (`PEAK_PHASE`) and the cue
  goes out that far early, so the room answers the beat on the beat.

### Added

- **`hit` and `accent`: lights with an attack.** Every rhythmic effect
  BRight had was a *swell* — smoothly up to a level and smoothly back —
  which is what "just a bunch of fading lights" describes. A `hit` is full
  brightness the instant the beat lands and decays before the next one.
  `saw` is the only one of LIFX's five shapes that is monotone across a
  cycle, so it is not a parameter here; the others come back up inside the
  cycle and duck rather than decay. Still one packet for eight beats.
- **`accent` follows the record, not the grid.** It lands on the drums the
  analyzer actually heard, at the strength it heard them, so it catches
  the fills a beat grid knows nothing about — and the analyzer now records
  **which band won each hit**, so the kick and the snare are different
  instruments and can drive different lights (`band: "low"` / `"mid"`).
- **The song is drawn.** Three lanes under the waveform, on the same
  ruler: chord changes as labelled blocks, the melody as a pitch contour
  against the track's own range, and the drums with the kick low and
  everything above it high. Until now the panel drew an envelope and the
  sentence `128 bpm · 7 sections · 2 drops`, so a melody layer that
  rendered zero notes looked exactly like one that worked.
- **One named row per effect**, under the strip, drawn from what the
  compiler rendered rather than from the script — an effect that produced
  nothing has a visibly empty row saying so. Plus a line saying what is
  running at the playhead and what starts next.
- **Show versions.** Every compile, revision and hand edit is kept, with
  who wrote it and how big it is; one pointer says which plays. Naming a
  version keeps it for good. A track that predates this is migrated on
  first read, by moving its files rather than copying them.

### Changed

- **The automatic director builds four layers on different lights**
  instead of giving each section a texture and running it end to end — a
  four-minute track used to change about eight times and do nothing in
  between. Ground (the harmony), pulse (the beat), hits (kick and snare)
  and voice (the melody — **in the chorus too**, which the previous rule
  explicitly forbade). A fixture belongs to one layer, which is a
  correctness rule as much as a taste one, and where a room has fewer
  kinds of light than there are layers a role is **split**: the left lamps
  are the kick, the right ones the snare. A layer *arriving* now gets a
  stab of its own, because that is what actually makes a chorus land.
- **Claude's brief teaches the same model**, and its list of bulb-side
  effects is generated from the set the compiler enforces — the
  hand-written copy had already drifted by two, so a model following the
  brief exactly could write a show whose kick cancelled its snare.
- **One party mode.** Tick the shows you want, press Play; nothing ticked
  plays everything. The songs run in the order you ticked them and each
  shows its place. Saved parties are now saved **sets** — a name on
  exactly what is on that screen — and **Load** puts one back so you can
  see what Play would do before pressing it.
- **The vibe field is gone from the Party tab and lives beside Compile.**
  It steers the *director*, which is a compile-time decision, and there it
  only ever reached a track with no show yet: on a library with shows
  already built it did nothing at all, on a fresh one it silently decided
  what went to disk forever, and two parties naming different vibes over
  one song gave whichever ran first.
- `ANALYSIS_VERSION` is **4** — hits carry their band. Existing libraries
  re-analyse themselves on the next **Analyze** pass.

## 0.17.0

Colour that moves without flickering, and lights that follow the audio.

### Added

- **BRight speaks `SetWaveformOptional`** (LIFX message 119), and it
  matters more than a protocol line sounds. Every effect BRight had ran on
  `SetWaveform`, which carries a whole colour and moves all of it — so a
  measured audit of the catalog found **only two of seventeen effects
  moving brightness through more than two levels**, and not one able to
  move colour while leaving the level alone. The vocabulary was "which
  light is bright, and when". This message is the same engine with a
  per-channel mask, and it still runs on the bulb for one packet however
  long it lasts.
- **`colour_drift`** — the bulb walks its hue around the wheel and the
  brightness never moves. Measured on the simulator: 356° of travel with
  the level frozen to three decimal places. The only motion a candle can
  join, and the ground a whole quiet section can sit on.
- **`saturate`** — saturation breathes, washing the room out toward white
  and back with the level untouched. A chorus lifting without getting
  brighter.
- **`level`** — brightness follows how loud the song actually *is*,
  moment to moment. It reads the analyzer's own 20Hz loudness envelope,
  which until now was used only to find where the sections and drops are:
  the song's real shape, instant by instant, and nothing was following it.
  Pick a band and the lights breathe with the kick, the vocal or the
  shimmer; `gamma` decides whether the quiet parts stay alive or fall
  away, which is what turns a meter into a lighting choice.
- **The automatic show uses all three**: colour drift through the intros
  and outros (where nothing else is running a bulb routine to cancel), and
  the strip breathing with the bass through the verses and choruses when
  something else is keeping time.

### Changed

- **The director's brief was audited as a document rather than added to,
  and it was hiding four capabilities and one hard limit.** An effect has
  always been able to carry its own `start`/`end` inside a scene — the
  compiler has supported it from the beginning and the brief never said
  so, which meant every scene the director wrote was one texture from end
  to end. `"base": false` (a scene that layers over the one before rather
  than washing the room) and `"respect_roles": false` were equally
  invisible. And the per-bulb rate budget — 18 messages a second, past
  which BRight **refuses the whole show** and falls back to the
  algorithmic director — was never mentioned at all, so the one constraint
  that can throw the work away was the one thing the model could not see.
  All five are in the contract now, with which effects actually spend
  messages and which cost one however long they run.
- **The brief carries a worked example and a list of anti-patterns.** One
  scene written well — four effects owning four different sets of lights,
  a windowed build in its last eight seconds, `base: false` so it grows
  out of the section before — followed by what the example is doing and
  why. `test_the_worked_example_actually_compiles` pulls that scene back
  out of the live prompt, validates it and compiles it inside the rate
  budget, because a broken example teaches the model to write broken
  scripts and does it convincingly.

### Fixed

- **Two bulb routines on one light silently cancelled each other.** A LIFX
  bulb runs exactly one waveform at a time — sending a second is how you
  end the first, which is precisely how BRight's own "stop the lights"
  works. Stacking `pulse` under `breathe` on the same fixture was
  therefore never a layered effect, and from a sofa it reads as an effect
  that does nothing. The compiler now says so on that effect's row,
  naming what it is replacing, and the Claude director is told the rule in
  its brief. It is reported rather than refused: a stab interrupting a
  pulse on the drop is a real technique.

## 0.16.2

Why it still failed, and a button that answers the question.

### Fixed

- **A stopped brAIn looked exactly like a working one.** `available()` —
  the only thing BRight checked — tests whether `/config/.brain/tasks` is
  a directory, and that directory is created by brAIn's automation
  listener at startup and then **outlives it**. A brAIn that is not
  running, or running with its Automation integration switched off,
  leaves the folder behind, so every Claude compile sailed past the check
  and then sat in silence until the wait expired: ten minutes of spinner
  and a message blaming a timeout, which sends you to look at the slowest
  thing in the system when the truth is that nobody was listening at all.
  The listener CLAIMS a task by renaming it before it does any work, so
  an un-renamed file is proof rather than a guess — that is caught in
  **30 seconds** now and the message names the switch to turn on. A task
  that *was* claimed and never answered is a different sentence pointing
  at brAIn's own log, because it is a different problem.
- **A candle could be asked to follow the melody.** `melody` lands a note
  every few hundred milliseconds with a 90ms fade, which is flickering
  however musical its reason, and a candle is documented as "glows and
  drifts, never strobes". It joins the harsh set that `respect_roles`
  keeps off candles. `harmony` deliberately does not: a crossfade over a
  bar or two is exactly what a candle should do, which is why the
  automatic director gives it the candles on purpose.

### Added

- **"Test the Claude director"** on the Shows tab (`director_check.py`,
  `POST /api/director/check`). The Claude director is a file handed to a
  different add-on, picked up by a shell listener, run through a CLI with
  its own login — six things have to be true and BRight could see one of
  them. This walks the links (brAIn → its task folder → BRight can write
  there → something claims a task → something answers it → there are
  lights to write a show for) and stops at the first one that is broken,
  the same shape `playback_check` uses for audio. It runs a real trivial
  round trip rather than describing one, because a test of the actual
  path is the only kind worth trusting.
- **"Or suggest some" on the Effects tab.** Claude proposing effects
  built for your light map has been implemented, tested and reachable by
  API since it shipped — and had no button anywhere, which is a feature
  nobody can use.

## 0.16.1

Asking Claude for a show is a job, not a request.

### Fixed

- **"failed: load failed" when compiling a show with Claude.** A
  Claude-tier compile was awaited *inside* the HTTP request that asked
  for it, and a show script takes minutes to write — so ingress cut the
  connection first and what reached the browser was not the panel's error
  but the absence of a reply, which Safari renders as `load failed`. The
  director carried on working and saved a show nobody was told about.
  All four routes that ask Claude for something (compile a show, revise
  one, write an effect, invent effects) now start a **job** and hand back
  its id, and the panel polls it — the move `jobs.py` exists for and says
  so in its own docstring, and the one the Library's Analyze pass has
  always used. The spinner counts the seconds while it waits, a second
  press follows the run already going instead of starting another, and a
  refusal still arrives as its own sentence rather than as silence.
  Nothing about the director changed: this was always a latent limit, and
  it became a bug when the brief grew and the model moved to Opus, with
  no line of the code that broke being touched.
- **The director's own budget was 240s because a request had to survive
  it**, which is not a reason about writing a show. Now that the wait
  belongs to a job, a script gets 600s and an effect 180s. brAIn passes
  the number through as the CLI's own process limit, so it is the real
  ceiling on an answer rather than a proxy's patience.

## 0.16.0

The analyzer learns to hear the music, and the reason you could not tell
that it had.

### Fixed

- **An upgraded analyzer never re-heard a library that had already been
  scanned.** `ANALYSIS_VERSION` sat at 1 through every change to the
  analyzer, and `scan` called a track analysed if an analysis file
  existed at all — so 0.15.0's ranked accents shipped, passed their
  tests, and reached **nobody** who had used BRight before: their shows
  had no accents to place because their analyses had no accents in them,
  which from the outside is identical to a feature that does nothing.
  The version is now bumped with every field, `library.is_stale` reads
  it, and the Analyze pass re-runs anything older without being asked
  twice. `analyzed` deliberately stays true for a stale track (it still
  has beats and a duration, and the party queue is built from that flag);
  `stale` is the separate, narrower claim, shown on the track's own row.
- **The show editor pushed a phone 7px sideways.** The mirrored script
  path is one unbreakable token longer than a 390px screen. It was
  invisible to the measure that exists to catch exactly this, because at
  390px the measure had been clicking the row's *middle* — which is a
  button once a row has four of them — so the editor never opened and
  the overflow check passed on a page with no editor on it. The measure
  clicks the track name now, the way a person does.
- **The Lab's beat test ran on every bulb in the house.** Its picker was
  built once when the tab opened, and discovery is the first thing
  anybody does *on* that tab — so the list was usually still empty, an
  empty list sent no selection, and no selection means every bulb. The
  picker reloads after a discovery, remembers what was ticked, and an
  empty selection out of a populated list is now refused rather than
  quietly meaning "all of them".

### Added

- **BRight hears harmony, melody, phrases and repetition**
  (`analyzer/music.py`). Rhythm says when a song hits; this says what it
  is *playing*, which is what the lights had no way to follow:
  - **chords** — a beat-synchronous chromagram against 24 triad
    templates, reported as *changes* only. Harmony turns over every bar
    or two, on its own clock, almost never where the energy changes,
    which is why a palette that follows it moves through the long
    stretches where the structure is doing nothing.
  - **melody** — the dominant pitch in the melodic register, segmented
    into note events with pitch class, octave and strength. Harmonic
    summing picks fundamentals over partials, and a sub-octave penalty
    stops the tracker following the bass up into the melodic range
    whenever the tune rests (measured: without it, a phantom note filled
    every silence).
  - **phrases** — notes grouped into breaths, each with the direction of
    its line, so a gesture that travels can start and end with one.
  - **repeats** — beat-chroma self-similarity, finding the passages that
    come back and what they come back from.
  - Also the track's **key**. All of it pure numpy, from one extra STFT
    pass over audio that is already decoded, and every extractor has a
    floor below which it says nothing rather than guessing.
- **Two effects that follow it**: `melody` (each note lands on the next
  light along, its pitch class picking the colour out of the scene's own
  palette, so a rising phrase climbs across the room) and `harmony` (the
  selection crossfades on every chord change, minor chords shifted
  around the wheel). Both render to nothing on a track with no musical
  analysis — correct, and indistinguishable from broken, so the compiler
  puts the reason on that effect's own row in the editor.
- **The automatic show uses them**: a harmony ground on whatever is not
  carrying the beat, and the tune on one kind of light through the
  verses and quiet sections. Not in the peaks, on purpose — a chorus
  already has a chase across every mover and a stab on every accent, and
  a third thing competing for the same bulbs is not more musical.
- **Claude's brief is rebuilt around all of it.** It now opens with the
  difference between a show that is *synchronized* (marks the structure,
  correct, boring by the second chorus) and one that is *musical*, and
  carries the musical map: the chord changes, the melody's range, the
  phrases, and what repeats — with the instruction to give a repeated
  passage the look its original had. A track whose analysis predates all
  this says so in the brief and tells the model not to reach for the two
  effects that would render to nothing.
- **Select All / None on the Lab's bulb picker**, with a live count of
  how many bulbs the test will actually drive.

## 0.15.0

Stabs on the beat, notes to the director, and a party you can steer.

### Added

- **The analyzer ranks the song's hits.** A new low+mid band "punch"
  measure finds the track's accents, scores each against the loudest one,
  and marks which sit exactly on the beat (±70ms). The Claude director's
  brief lists the strongest on-beat hits; the algorithmic choreographer
  places up to six accent stabs of its own on them — only in the loud
  sections, clear of the drops, never closer than eight beats. Shows
  answer the song's punches now, not only its section changes.
- **`"snap": "beat"` on a moment.** The compiler moves the moment onto
  the nearest analyzed beat, so a rounded time in a script cannot smear a
  hit that was meant to land on one.
- **Notes to the director.** The show editor grew a feedback box: say
  what you noticed watching the show ("the chorus needs more movement")
  and **✍ Revise with Claude** hands the whole script back to the
  director with your words (`POST /api/show/{hash}/revise`). Nothing is
  written unless the revision validates and compiles — a failed revision
  costs an error message, never the show.
- **`director_model` option (default `opus`).** Which Claude writes and
  revises shows and effects. Rides brAIn's task `model` field;
  choreography is the one place BRight spends a big model on purpose.
- **Party transport.** ⏮ Prev / ⏭ Next on the party live view
  (`POST /api/party/skip`). A skip ends the track — cue task, its music,
  any waveform still running on a bulb — and never the evening; previous
  on the first track replays it. A stop that races a skip still wins,
  told apart by the party task's own pending cancellation.
- **🎤 Sync by ear, measured.** The phone records the room for four
  seconds and BRight matches what it heard against the playing track
  itself (`POST /api/show/autosync`) — same onset-envelope correlation
  as calibration, with the song as the reference. The measured error is
  applied whole: small corrections slew invisibly, large ones step
  (`ShowClock.step_drift`), because at 8ms/s an 800ms fix would spend
  100 seconds being wrong on purpose. Confidence floor measured against
  synthesized ground truth; a quiet room answers "try again", not a
  wrong number.
- **Lab sync proof picks its lights.** Tick which bulbs join the
  metronome test instead of strobing the whole house; the Shows tab
  splits **▶ Show** (compiled choreography) from **♪ Beat sync** (the
  metronome) per track, with the same ±25ms nudge available while either
  runs.

### Fixed

- **`band_flux` normalized each band to its own peak**, which amplified
  an empty band's noise floor to full scale — a track with no bass grew
  phantom punch out of silence. Both bands now share one scale (the
  full-band envelope's peak), which is also what makes weighting them
  against each other meaningful.

## 0.14.1

The prose diet.

### Changed

- Every tab opened with a heading repeating the tab strip and an essay
  before its first control — six lines on Party before the Start button,
  a whole first phone screen of words on Effects. Each tab opens with one
  sentence now; the essays live in DOCS, where somebody who wants them is
  somebody who went looking. No control changed and no id changed.

## 0.14.0

Stop means silence, the party shows its work, and a field-test batch of
fixes.

### Fixed

- **Stop stops the music.** The speaker fetches the track and plays it on
  its own, so it outlives every task the conductor cancels — exactly like
  a bulb's waveform outlives the cue that sent it. Stopping a party or a
  show now silences the player it started (only when interrupted: a track
  that ended by itself is not re-stopped), and a failed stop is a warning
  on the run state rather than silence about the silence that didn't
  happen.
- **The calibration sound can be stopped** (■ Stop the sound, on the
  Calibrate tab). Thirteen seconds of clicks is a long time at midnight
  with no way to end it.
- **The 26-minute four-minute songs.** mutagen reads duration from the
  file header, and a VBR file without a proper Xing header lies by whole
  multiples — and that estimate used to win over the length of the PCM
  BRight had just decoded. The measured length is authoritative now, old
  analyses are healed using the beat grid as a witness (the tracker
  walked the whole file, so a claimed duration far past the last beat is
  a lie, not a quiet outro), and already-compiled shows have their baked
  duration checked against the heal — that phantom tail is also what
  parked the party queue for twenty minutes between songs.
- **The sync-proof button plays the sync proof.** It used to start the
  full compiled show the moment one existed — a party out of a button
  labelled as a demo, with no way back short of deleting the show.
- **The live playhead actually follows.** No show start ever carried its
  track identity into the run state, so the editor's follow-the-room mode
  never matched. Both branches carry `track_hash` now.

### Added

- **Party mode shows what it is doing.** While a party runs, the Party
  tab carries the song (waveform, sections, drops) with the room's live
  position on it, the floor plan animating with the colours actually
  being sent (the compiler's own outline, filtered to the lights this
  party is allowed to drive), the queue — now playing, up next — and the
  trim.
- **Live sync trim.** −25ms / +25ms while anything plays, slewed in so
  nothing stutters; the trim carries across a party's tracks so an
  evening stays dialed; **Keep this trim** folds it into the player's
  calibration so every future show starts in tune.
- **Playlists.** A saved party can name its exact songs in an exact
  order, built in the party form from the analyzed library. A playlist
  turns Shuffle off as you start one (order is the request); tracks that
  have lost their analysis are skipped and named, never silently dropped.
- **Calibrated players can be deleted** — a departed speaker was not
  clutter, it was a candidate for every show that names no speaker.

### Changed

- Tabs load their own data: the calibrate players and profiles, the Lab's
  sync choices, and the party pickers appear on open. Four "Load…"
  buttons and the party tab's raw JSON state dump are gone.

## 0.13.1

Find the media source that actually holds the file, and let Home Assistant
say why it refused.

### Fixed

- **A source that could NAME the file was taken for one that HAS it.**
  Discovery probed each of Core's media sources with
  `media_source/resolve_media` and treated a signed URL as proof — but
  Core resolves for any source that exists, whether or not the path under
  it does. On an install whose only media source was
  `media: /config/media`, Core happily signed a URL for
  `media-source://media_source/media/bright/calibration.wav` while the
  click track sat under `/media` and nothing of the sort existed at
  `/config/media/bright/`. BRight took that as the answer, built every
  media id that way, and Core refused the eventual play with an HTTP 500
  about a file that was never there. The resolved URL is now **fetched**:
  a 200 is proof, a 404 is proof of absence, and a fetch that cannot run
  at all is neither — it falls back to the resolve, because a probe that
  cannot run must not veto the only candidate.

### Fixed

- **A failed Core request reported its status code and threw away the
  reason.** `Test playback` walked every link, reached the last one, and
  said `HTTP 500 from /services/media_player/play_media` — which is what
  the red cross beside it had already said. Core puts the reason in the
  response body, and `urllib`'s `HTTPError` **is** that response, so the
  single most useful sentence available was being read and discarded.
  Every Core call BRight makes now carries Home Assistant's own words:
  for a failed service call that is the exception Core raised, by name.
  An empty body stays empty rather than becoming a note about the absence
  of a message, a body that cannot be read leaves the status code alone,
  and a traceback is flattened to one bounded line because it lands in a
  panel row beside five other steps.

## 0.13.0

The effect library is a shared, growing thing that Claude reads and adds to.

### Added

- **Saved effects are in every brief Claude gets.** The library existed and
  was invisible to the one thing most able to use it: BRight held effects
  somebody spent an evening getting right, and then asked Claude to write a
  show from a blank page. Every show started from nothing, so no show could
  be better than the last one — the opposite of what a library is for. The
  show director, the effect writer and the effect inventor are all told
  what is saved, described rather than just named: `"kitchen chase"` is not
  something a model can reason about, but "a chase across the kitchen zone,
  half a beat a step, notes: looks great at 120bpm" is.
- **A script can name a saved effect.** `{"use": "kitchen chase"}` works
  anywhere an effect goes, in a hand-written script and in one Claude
  writes. Override anything alongside it —
  `{"use": "kitchen chase", "params": {"step_beats": 1}}` keeps the
  selection and changes the speed — and parameters *merge*, so changing one
  does not silently drop the rest.
- **＋ Library on every effect in a show.** An effect that turned out well
  is kept with one press, and is then available by name to every future
  show. Before this the only way back to it was finding the show it was in
  and copying the JSON out by hand.

### Notes

Names are resolved once, before a script is compiled or saved, so what
lands on disk is the effect in full. A show that stored the *name* would be
a show that changes when somebody edits the library — silently, and usually
the night after they edited it. The library is a place to copy from, not a
layer a saved show hangs off. Expansion happens on a copy, so a refused
compile leaves the editor holding exactly what was typed.

## 0.12.0

Ask Claude to write one show, read what it was told, and see the song it
is hung off.

### Added

- **"✨ Claude" on every track.** The director tier was a global option, so
  "write this one with Claude" meant a trip to Settings and back. It is a
  button per show now, in both directions — asking for the algorithmic
  director explicitly is the same button, for a show you want rebuilt
  without spending a Claude run. The option stays the default, because it
  is the answer for every show nobody has an opinion about.
- **Every show records who wrote it**, saved beside the show and readable
  later (`GET /api/show/{hash}/director`). A fallback carries the reason it
  fell back, and pressing a button called Claude on an install with no
  brAIn is refused by name rather than quietly downgraded. This is the
  record whose absence let a fortnight of silent fallbacks go unnoticed: a
  show tagged `algorithmic` looked exactly like one nobody had asked
  Claude for.
- **The brief is readable** (`GET /api/show/{hash}/prompt`, and a
  disclosure under the show editor). It is built by the same function a
  real run uses rather than described, so it cannot drift into being a
  nicer story than the truth — and it shows, in the model's own words,
  that the director knows your light ids, roles, zones, positions and the
  travel orders worked out from them. Reading it runs nothing and costs
  nothing, which is the point: it is the cheapest way to find out whether
  a Claude run is worth a couple of minutes.
- **The song, drawn.** Nothing in the panel showed the music at all — a
  show is a list of times, and the only way to know whether the drop
  landed on the drop was to play it in a dark room and watch. The show
  editor now draws the waveform above the timeline, tinted by section,
  with the analyser's drops marked in red and bar lines you can count
  against. It shares a wrapper (and therefore a time axis and a playhead)
  with the light strip, because two pictures of one song that do not line
  up are worse than one. Clicking or dragging it scrubs.
- **The playhead follows a real show.** While a show is actually playing,
  the editor stops animating its own preview and follows the room instead,
  interpolating between the conductor's position stamps so the head moves
  smoothly through a quiet stretch where no cues are dispatched.
- Waveforms are computed once during analysis, beside the decode that has
  already happened. A track analysed before this release has one computed
  on demand from its file, so nobody has to re-analyse a library to get a
  picture — and if that file has since moved, it says so rather than
  drawing a flat line that reads as silence.

## 0.11.1

Stop actually stops the lights, Claude's shows stop falling back, and the
Library tab stops asking to be told to show you your music.

### Fixed

- **Stopping a show left the bulbs running it.** A `SetWaveform` hands the
  bulb a routine it executes on its own — that is the sync trick, and it is
  also why Stop did not work: BRight stops sending, and a bulb three
  seconds into a forty-cycle strobe carries on to the end. Nothing we stop
  *doing* can reach it. Stop now sends a one-cycle, 20ms, transient
  waveform to every bulb the show drove, which replaces the running routine
  and returns the light to the colour it held before. Three separate gaps
  are closed: `SetColor` (what stop used to send) does not end a routine,
  it just moves the light while the routine keeps running underneath; a
  bulb that never answered `GetColor` had no snapshot entry and so was
  never spoken to at all; and a party with an end scene returned before
  sending a single LIFX packet, so the room strobed through the scene and
  past it. Halting is unconditional — `restore=False` means "leave the room
  as it is", not "keep going".
- **Every Claude-written show was silently falling back to the algorithmic
  director.** The schema contract annotates each field with a `//` note, so
  the model wrote those notes back into its answer — and JSON has no
  comments, so `json.loads` stopped at the first one with `Expecting ','
  delimiter`. The prompt now says the annotations are not part of the
  answer, the parser strips comments and trailing commas (string-aware, so
  a mood called `pop // rock` and a URL in a label both survive), and a
  parse failure quotes the text around the break instead of reporting a
  column number about a document that has already been discarded.
- **The Library tab opened empty every time.** `scanLibrary` was bound to
  the Scan button and to nothing else, so every visit started by pressing
  a button to be shown the library you already had — and after an add-on
  restart that is indistinguishable from having lost it. Nothing ever was:
  the analysis lives in `/data` and has always survived. The tab loads
  itself on open now, and re-opening refreshes, so a track added while the
  add-on was running turns up without a restart.

### Changed

- **A library scan is a stat per file, not a megabyte read per file.**
  Track identity is a hash of the first megabyte, and the library is
  scanned far more often than the Library tab suggests — the Shows tab,
  the effect builder and the sync proof all list it, and now so does
  opening the Library tab. Hashes are remembered in
  `/data/track-hashes.json`, keyed on size and mtime, so a rescan re-reads
  only what changed: measured at **48× faster** warm over 60 tracks on a
  local disk, and the saving is larger on a Pi reading a network share,
  which is where this was felt. A track that is touched but not edited is
  read again and keeps its identity, because the hash is of the content.
  Deleted tracks are pruned, and only a scan of *every* folder may prune —
  a single-folder scan has no idea what the others were about to claim.

## 0.11.0

Claude knows what room it is lighting, zones are a thing you can set,
and the LIFX socket no longer trusts a guessable id.

### Added

- **Describe an effect and Claude writes it.** The Effects tab has a
  **Describe it** box: a sentence ("bounce a warm pulse between the two
  window lamps") comes back as a real effect in the builder, for this room,
  with every light named. It lands **unsaved** — an effect you have not
  looked at is not an effect you want — and previews immediately. Validated
  by the same `clean_effect` a hand-typed effect goes through: a generated
  effect gets no privileges, and an unusable one is caught here rather than
  at compile time in the middle of an evening. Needs brAIn, like the show
  director; everything else in the tab works without it.
- **A zone can be set on any light, at any time.** It was settable only
  while *adding* a bulb, so the answer to "these four are the kitchen" was
  to remove them and add them again. The field sits beside the role picker
  on the map's selection bar, offers the zones you already have, and takes
  a new name.
- DOCS.md explains what a role is and what a zone is, because they are two
  different questions and only one of them changes how a light is driven.

### Changed

- **The Claude director is told what room it is designing for.** It used to
  get roles and x positions — no ids, so `select.ids` was in the schema and
  unusable; no names, so one lamp could not be told from another; no y,
  though four travel orders key on it; and no zones, though `select.zones`
  and `order: "zone"` both do. Every generated script selected by role,
  because role was the only thing it had. It now gets a row per light, the
  zones that exist, what each role is *for*, and the travel orders already
  worked out.
- The zones in use ride down with the map, derived on read rather than
  stored — a zone exists exactly as long as a light is in it.
- The effect builder no longer flattens a selection to ids. An effect that
  says "every candle" stays "every candle" until you tick a box; flattening
  it to the candles that exist today is wrong the moment a fifth is added.

## 0.10.1

Nothing played on an install that sets `media_dirs`.

### Fixed

- **BRight now works out what Home Assistant calls its media folder, instead
  of assuming.** Every file BRight plays is handed to Core as
  `media-source://media_source/<source>/<path>`, and `<source>` was written
  as `local` — which is Core's *default* name for its local media source and
  nothing more. An install that sets `media_dirs` in `configuration.yaml`
  renames it, and then every id BRight builds comes back `Unknown source
  directory`: no click track, no calibration, and so no music either. The
  name is discovered now — BRight writes the click track, then asks Core to
  resolve it under each media source Core reports until one answers, and
  remembers which. Core does not publish the path behind a source, so which
  one is our `/media` cannot be read, only tried.
- A media id that fails to resolve **drops the remembered name and goes
  looking again**, so editing `media_dirs` costs one failed play rather than
  a restart — and the Lab's playback test reports what it found. Naming the
  problem and then building the next id the same wrong way was a diagnosis
  that fixed nothing.
- The failure, when BRight genuinely cannot find a match, now names the media
  directories Core *does* have — the person has to be able to recognise
  their own `configuration.yaml` in the answer.

### Changed

- **The Claude director is told what room it is designing for.** It used to
  get roles and x positions (`lamp: 3 at x=[0.10, 0.50, 0.90]`) — no ids, so
  `select.ids` was in the schema and unusable; no names, so one lamp could
  not be told from another; no y, while half the travel orders key on it;
  and no zones, though `select.zones` and `order: "zone"` both need them.
  Every generated script selected by role because role was all it had. It
  now gets every light as a row — id, name, role, zone, x/y, and how it is
  driven — the zones that exist, and the travel orders **already worked
  out**, because sorting a dozen floats by hand is exactly what a language
  model does badly and confidently.

### The LIFX source id is this connection's, and it is unguessable

Two problems met in one field. The engine's socket is bound to every
interface — LIFX discovery is a broadcast and the replies come back to the
sender's own address, which is the whole reason this add-on runs
`host_network` — so anything on the LAN can send to it, and the only thing
separating a bulb's reply from a stranger's datagram is the source id in
the header. That id was `(pid & 0xFFFF) | 0x42420000`: a fixed prefix over
a container pid that is usually a small number. Guessing it bought a
forged `StateService`, which is a phantom device in the registry pointed
at whatever address the sender chose. It is 31 bits from `secrets` now.

Making it unpredictable exposed the second problem: the compiler baked the
id it was handed into every cue packet, and shows are *saved* — so a show
compiled in one process was replayed in the next still carrying the old
id. That was invisible only because a pid-derived id usually survived a
restart. The id is stamped at dispatch now (`packets.with_source`, in
`Engine.send`, the one place every outbound packet passes through), so a
compiled show is portable between runs and between installs, and the id
is free to be drawn fresh each time.

## 0.10.0

The show editor is a picture you can scrub, and editing it is the primary
way to change a show.

### Added

- **A visual show editor.** The Shows tab opens a show as what it is: the
  room on a floor plan, the whole song as a strip with one row per light,
  the scenes as blocks over it, and the effects as rows you press. A scrub
  bar under the picture moves the playhead; ▶ plays the show through at
  real speed without touching a bulb. Pressing a scene block jumps there.
- **Live preview of unsaved edits.** Every preview request carries the
  script currently being edited, so what you are looking at is the show as
  it stands, not the show as last saved. The compiler's own refusals — a
  flooded bulb, an impossible selection — arrive while you are still
  looking at the effect you changed, rather than several presses later at
  save time.
- **An effect dialog built from the catalog**, the same source the Effects
  tab builds its form from, so a new effect type reaches both by existing.
  It edits selection by light, by role and by room, because the automatic
  director selects by role for nearly everything it writes.
- `POST /api/show/{hash}/preview` (a window of frames, for scrubbing) and
  `POST /api/show/{hash}/outline` (the strip, plus the scenes, sections,
  moments and bar lines behind it). Neither writes anything.

### Changed

- **The Code view is a view, not the interface.** The show is still a file
  and still editable as text — it moved behind a `Code` disclosure, and the
  forms and the text are two renderings of one document: type in either and
  the other follows.
- An effect row now says what the effect actually owns. Rows read
  `candles · breathe · candle` where they used to read `all lights`, which
  was wrong for nearly every effect the director writes.
- `compiler.script_actions` is the single walk from a script to actions.
  `compile_show` renders those to packets and the preview simulates the
  same list — the same "one rendering, two consumers" contract effects have
  had, now at the scale of a show. Verified against the old compiler on a
  real generated show: 898 cues, byte-identical.
- The compiler's own defaults (`DEFAULT_ORDER`, `DEFAULT_ALIGN`) ship in
  the effect catalog, so the editor opens an effect at the value the
  compiler would have used. Opening one and pressing Apply leaves the show
  byte-identical, which the editor measure checks at three widths.

### Fixed

- The end-of-show switch-off is an ordinary action rather than a cue
  written straight to the timeline, so the preview shows a laser going out
  at the end of the show — it really does, and the picture used to leave it
  lit.

## 0.9.1

Installs by pulling a prebuilt image instead of building one on your box.

### Changed

- **BRight installs from the registry now.** `config.yaml` gained
  `image: ghcr.io/bruhautomation/{arch}-bright`, which is the second half of
  the two-step cutover 0.9.0 set up: the images were published first, made
  Public, and only now is anything told to pull them. Doing it in the other
  order points every install at a tag that does not exist, and the add-on
  stops installing entirely rather than merely installing slowly.

  What it changes for you: the Supervisor downloads a finished image instead
  of running the whole Dockerfile — the base image, `apk add ffmpeg numpy
  …`, and `pip install`. On a Raspberry Pi that was a long, SD-card-punishing
  build that could fail on any transient network hiccup, and it left every
  install subtly different depending on what each machine resolved that day.

  It does not change the add-on's behaviour, and it does not fix
  `'AddonManager.install' blocked from execution, no host internet
  connection` — that is the Supervisor refusing the install job before it
  reaches any of this, on its own connectivity check. See DOCS.md.

### Added

- A test that an add-on declaring `image:` is actually built and published
  under that name (`tests/test_config_validation.py`). The failure this
  guards against is silent in CI and total on a user's machine: nothing
  before now connected the key that redirects an install to the workflow
  matrix that has to produce what it points at.

## 0.9.0

The add-on's own name, spelled right — and the thing a light show is
actually made of, opened up: effects you build, watch, and edit.

### Changed
- **BRigt is BRight.** The name was misspelled from the first commit. This
  is a new slug, a new integration domain and a new `/data`, because Home
  Assistant identifies an add-on by its slug and there is no renaming an
  installed one: **remove BRigt, install BRight, and set the integration up
  again from its discovery card.** Music and calibration survive (they live
  under `/media` and are re-measured per speaker in a minute); analysis and
  compiled shows are regenerable build output and will rebuild on the next
  scan. On first start BRight removes the old add-on's deployed
  `custom_components/brigt`, which cannot work once BRigt is gone, and
  leaves everything else in `/config` alone.
- **The mark was redrawn, not retitled.** The lockup is the BRUH ligature,
  the family gable, and the app's own small caps — and those caps read
  `IGT`. They are `IGHT` now, drawn to the same rule and laid across the
  same span, so the roof still sits over its word.

### Added
- **An effect builder** (`director/effects.py`, the new Effects tab).
  Fifteen effect types — wash, fade, build, pulse, strobe, chase, sweep,
  breathe, sparkle, colour cycle, rainbow, theater chase, stab, blackout and
  aux — each with typed parameters, a fixture selection, a travel order and
  a beat alignment. **Everything an effect does not select is left exactly
  as the rest of the show left it**, which is the whole reason for building
  effects rather than scenes: most of the room is usually meant to stay
  still.
- **The map is what an effect travels through.** Order comes from the light
  map — left to right, out from the middle, reading-order through the zones,
  or a seeded shuffle that is the same every night. The automatic director
  reads it too: three or more moving lights get a chase, two get alternation,
  because a chase across two bulbs is a flicker.
- **A preview, drawn from the same render as the packets.** The room
  animated on the floor plan you placed the lights on, plus the whole effect
  as a strip — one row per light, time left to right — which is the view
  that says whether a chase actually chases. Both come from ONE render of
  the effect; a preview built from a second implementation of what an effect
  does is a preview of the second implementation. Underneath: the cue count
  and the busiest bulb's messages per second against the budget, before
  anything reaches a bulb. **Run it on the lights** does exactly that, with
  no music, and restores the room afterwards.
- **The show file, opened.** Every show is a script — scenes with palettes
  and effects, moments pinned to the drops — and the Shows tab now opens the
  whole thing as text. Edit and **Save & compile** and it goes through the
  same validator, compiler and per-bulb budget the director's own output
  does; a script that would flood a bulb is refused with the reason and the
  show you had is untouched. Every compile also mirrors the script to
  `/config/.bright/shows/<track>-<hash>.json` for the Home Assistant file
  editor, and **Reload from file** reads it back. Broken JSON is reported
  with the parser's own line number.
- **Every cue names the effect that made it.** `Show the cue list` prints
  when, which light, and which effect asked for it — the only thread from a
  packet in a two-thousand-cue timeline back to the line in the script a
  person wrote.
- **Saved effects and saved parties.** A preset keeps its *lights* as well as
  its settings, because "kitchen chase" is the chase and the three lights it
  runs across. A party keeps the speaker, the folder, the vibe, which lights
  may join in and what the room looks like afterwards — startable from the
  panel, from `bright.start_party`, or by voice.
- **An end scene.** Stopping restores every light to how it was, which is
  right when the show interrupted an evening and wrong at 1am. A party (or a
  `bright.stop_show` call) may name a Home Assistant scene to call instead. A
  scene that fails to run falls back to restoring, so the room never keeps
  the party colours.
- **Bulbs added one at a time.** The Light Map has a picker of every
  discovered bulb that is not on the map yet, with a role and a room chosen
  as it goes on. "Add discovered bulbs" is still there and is still the right
  button exactly once — six lamps dropped on the middle of the floor plan
  named after their serials is not a map.
- `bright.start_party` (a saved party by name, required, so a typo fails
  loudly instead of quietly playing the default folder), and `party`,
  `end_scene` and `shuffle` on `bright.party_mode`. The status sensor now
  carries `active`, `lights_busy`, `party`, `queue_left`, `cues_sent`/
  `cues_total` and the list of saved parties, so a dashboard can key on the
  add-on's own answer rather than on a state string.

### Fixed
- **The Stop button is gone when nothing is running.** All three of them —
  Party, Shows and the Lab's sync proof — used to sit there whatever the
  lights were doing, and a button that is always present is a button nobody
  trusts. They follow `active` in the conductor's own state now, and the
  line beside them says what is playing and how far through the queue it is.

### Internal
- The script language is version 2: scenes carry `effects`, and `moments`
  pin an effect to an instant. Version 1 scripts still compile — `motifs`
  and `features` are translated into their effect equivalents on the way in,
  because scripts are files people keep.
- One rendering, two consumers: every effect renders to *actions*, the
  compiler turns actions into packets and `simulate()` turns the same
  actions into preview frames. Adding an effect type is a catalog entry and
  one render function; it touches neither the compiler nor the UI, which
  builds its whole form from the catalog.
- `tests/manual/bright_demo_panel.py` boots the real panel against a seeded
  house, and `tests/manual/measure-effects.mjs` drives it in a browser —
  the preview is a canvas, and "the timeline painted" is not something a
  server can answer.

## 0.8.4

Why nothing plays, said out loud — plus folders you can pick, a light map
where a dot is a light rather than a circle, and documentation somebody
could actually set the add-on up from.

### Added
- **Test playback** (Calibrate tab). "Nothing plays" has half a dozen causes
  living in different machines, and `media_player.play_media` answers
  "accepted", never "playing": Core resolves the media, signs a path, puts a
  *host* in front of it and hands the result to a speaker that fetches it
  afterwards, on its own, over the network. This walks the chain — the file
  on disk, whether Core resolves the media id, what address it will hand the
  speaker, whether the player accepts media at all, whether the command was
  taken, and whether the player ever actually started — and names the step
  that broke with what to do about it.
- **The host step is the one that took research.** Chromecast, Google and
  Nest speakers resolve names through Google's public DNS rather than your
  router's, so an Internal URL of `http://homeassistant.local:8123` — which
  a great many installs have — is a name the speaker is told does not exist.
  Nothing plays, nothing errors. BRight reads Core's own configuration and
  says so, with the fix.
- **An HA WebSocket client** (`panel/ha_ws.py`), because media sources are
  WebSocket-only and `media_source/resolve_media` is the same call the cast
  integration makes before it hands a URL to a speaker. It also catches the
  case a hardcoded `local` cannot: an install that set `media_dirs` and
  renamed the local source out from under every media id BRight builds.
- **Browse and tick folders** in the Library tab. Everything under Home
  Assistant's media folder, openable, with the tracks in each; ticking one
  scans it, all the way down, with no restart and no YAML. Merged with the
  `additional_music_folders` option rather than competing with it.
- **Type the delay in** (Calibrate tab). A show refuses to start without a
  calibration profile, which is right — and it meant one speaker that would
  not play the click track took the whole add-on with it. A typed profile is
  stored as `manual`, so the record never claims to have been measured.

### Fixed
- **The Light Map's dots say which light they are.** A dot was a role glyph
  with the name in a `title` attribute — a hover tooltip, on the device most
  likely to be dragging lights around a floor plan, which has no hover. Every
  dot carries its name now; tapping one selects it, and the dot, its row in
  the list and a bar above the map all agree on which light that is. The
  selected light can be re-roled and removed from the map itself, instead of
  from a list that had no visible connection to the picture above it.
- A tap is no longer a one-pixel drag: a press that never travels selects and
  saves nothing, so tapping a light to see what it is cannot nudge it.
- A light at the very edge of the room is fully on the map. A 44px dot hangs
  half outside its own coordinate, so a light at x=0 drew half off the floor,
  clipped and hard to grab — which is exactly where people put lights.
- **Every text control is a 44px touch target.** The floor this panel claims
  was set inside one CSS block, so the role picker on each light — a bare
  `<select>` — rendered at the browser's default 19px.
- **A service call that could not do what you asked now fails with the
  reason.** `bright.party_mode` awaited the bridge and dropped what came back,
  so an automation with nothing analyzed got a green tick and a dark room
  while "no analyzed tracks in /media/music — run the Library tab first"
  was thrown away one line from the person who needed it.
- **The bridge relays the panel's sentence rather than its status code.**
  Same failure, one layer out: an automation got "panel answered HTTP 409".
- **A show that could not start says so** rather than reporting "Running:
  412 cues" over a dark room, and the lights are put back.
- **"You have no media players" and "I could not ask Home Assistant" are
  different sentences now.** The entity picker answered both with an empty
  list.
- The calibration wizard no longer says "move the phone closer" when the
  speaker never made a sound — the position poll ran through the same
  seconds and knows which of the two happened.
- A number off the wire that is not a number (`{"count": "lots"}`) is
  clamped rather than answered with a bare HTTP 500.
- The `/media` confinement is one implementation rather than two: the show
  route had its own copy of the string arithmetic.

- **A browse walks real directory entries.** Turning something typed into a
  directory to open is the exact shape a path traversal is written for, and
  checking the string and hoping is the answer everybody writes. Each
  component is matched against what the filesystem actually reports, so the
  path that comes out is built from directory entries rather than from the
  request — and a folder that is not there answers "no such folder" instead
  of listing nothing.
- **The playback check no longer turns a media id into a path.** It statted
  the file behind whatever media id it was handed; Home Assistant's own
  resolve step answers "is the file there" better than a stat does, and a
  media id is not always a local file. The one path it does stat is the
  click track, whose path is the add-on's own.

### Changed
- **The documentation is a rewrite.** DOCS.md now covers what you need,
  install, the order things want to happen in, every tab, every option with
  its default and what it changes, the services with their fields, a
  troubleshooting section built around *when nothing plays*, and where BRight
  keeps its files. BRight is in the repository README and SECURITY.md for the
  first time.
- `tests/manual/measure-lightmap.mjs` measures the map at four widths — names
  present, nothing hanging off the floor, selection agreeing in three places,
  every control a real target — and runs in CI beside the other four.

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
  root on a Home Assistant install and BRight's panel runs as the `bright`
  user, so creating `/media/bright` raised a permission error the moment
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
  there is one, and run.sh exports the answer into `/data/.bright_env` where a
  `with-contenv` child can still read it.
- **A port that cannot be taken now ends in a sentence naming it**, not an
  aiohttp traceback underneath a log line that had already claimed the panel
  was listening on it. The bind is attempted *before* that line is written,
  and retried a few times first — the one holder worth waiting out is a
  previous panel that has not finished dying.

### Changed
- **No `watchdog:` URL** — the Supervisor's placeholder needs a port number
  written into config.yaml, and a watchdog still pinned to 8095 would poll
  whatever service actually holds 8095 and restart BRight on its behalf.
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
- **`bright.party_mode`, end to end**: every analyzed track in the folder
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
- **Claude-designed shows through brAIn.** BRight carries no Claude CLI
  and asks for no second login: when brAIn is installed on the same Home
  Assistant, its automation-task surface is already a signed-in Claude,
  so BRight hands it the track's digest — sections, drops, BPM, the
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
- `bright.start_show` and `bright.stop_show` are now LIVE end to end (HA
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
  deterministically to `/media/bright/calibration.wav`.
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
- Companion `bright` custom integration (deployed automatically): the
  `bright.party_mode`, `bright.start_show` and `bright.stop_show` services and
  a show-status sensor, over file IPC in `/config/.bright/`. The services
  answer honestly that this build does not run shows yet.
- Options: `music_folder`, `director_mode` (auto / algorithmic / claude),
  `enable_ha_integration`, `log_level`.
- The BRight brand set: the family's BR ligature under BRight's own roof — a
  straight-plane gable with two light-beam knockouts — over IGT light-tube
  caps.
