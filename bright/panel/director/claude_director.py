"""The Claude director tier: creative choreography, delegated to brAIn.

BRight's container carries no Claude CLI and asks for no second login.
When brAIn is installed on the same Home Assistant, its automation-task
surface (`/config/.brain/tasks/` in, `/config/.brain/task_results/` out —
the same files the `brain.run_task` service rides) is already a logged-in
Claude, so BRight hands it the track digest and the script schema and gets
choreography back. No brAIn, no Claude tier — the algorithmic floor
answers, exactly as `director_mode: auto` promises.

Everything returned is validated by choreographer.validate_script before
the compiler ever sees it. The model writes a SCRIPT — scenes, motifs,
moments — never packets and never device commands: taste is delegated,
the wire budget is not.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from analyzer import library
from stores import effect_presets

from . import room

BRAIN_SHARED = Path(os.environ.get("BRIGHT_BRAIN_SHARED", "/config/.brain"))
TASKS_DIR = BRAIN_SHARED / "tasks"
RESULTS_DIR = BRAIN_SHARED / "task_results"

# A show script is one long considered answer, not a quick reply — and
# now that the panel starts these as jobs rather than awaiting them
# inside a request (`server._claude_job`), the budget is the director's
# to spend rather than whatever an ingress proxy will hold a connection
# open for. It was 240s because a request had to survive it, which is not
# a reason about writing a show; brAIn passes this through as the CLI's
# own process limit, so it is the real ceiling on an answer.
TASK_TIMEOUT_S = 600
POLL_S = 1.0

# Which Claude writes the shows. Creative choreography is the one place
# BRight spends a big model on purpose — the host asked for Opus by name —
# and it is an option (`director_model`) rather than a constant so a
# different account's answer can differ. brAIn's automation listener reads
# the task's `model` field and passes it to the CLI as `--model`.
def _director_model() -> str:
    return (os.environ.get("BRIGHT_DIRECTOR_MODEL") or "opus").strip()

MAX_LYRIC_LINES = 60


def available() -> bool:
    """brAIn's automation listener creates the tasks dir at startup; its
    absence means no brAIn (or its automation face is off)."""
    return TASKS_DIR.is_dir()


# ---------------------------------------------------------------------------
# The digest prompt
# ---------------------------------------------------------------------------
_SCHEMA_CONTRACT = """\
Answer with ONE JSON object and nothing else — no prose, no code fences.

{
  "version": 2,
  "scenes": [
    {
      "start": <seconds>, "end": <seconds>,   // cover the track, in order
      "mood": "<one word>",
      "palette": [[<hue 0-360>, <saturation 0-1>], ...],  // 2-4 pairs
      "brightness": <0-1>,                    // the scene's base level
      "effects": [ <effect>, ... ]            // what MOVES in this scene
    }
  ],
  "moments": [
    {"t": <seconds>, "effect": <effect>}      // one hit, at one instant
  ]
}

An <effect> is:

{
  "type": "<one of the types below>",
  "name": "<short label, shown on every cue it makes>",
  "select": {"roles": [...], "ids": [...], "zones": [...]},  // WHO it drives
  "order": "x" | "-x" | "y" | "-y" | "center_out" | "edges_in" | "snake"
           | "zone" | "random",               // the path it travels
  "params": { ... }                           // see each type
}

`select` decides which lights the effect owns; every light it does not
name is left exactly as the scene put it. An empty `select` means all of
them. Only use roles the fixture list below actually has.

FOUR THINGS THE SHAPE ABOVE DOES NOT SHOW, and every one of them is a
tool you will want:

1. **An effect can carry its own `"start"` and `"end"`** (seconds), and
   then it runs only for that stretch of its scene instead of all of it.
   This is how you write "strobe for the last four bars", "the sweep
   arrives halfway through", "hold, then move". A scene is a container,
   not a straitjacket — without this every scene is one texture from end
   to end, which is the single most common way a show reads as flat.
2. **`"base": false` on a scene** stops it washing every light at its
   start, so the room stays exactly as the previous scene left it and
   your effects layer over that. Use it when a section should evolve out
   of the one before rather than cut.
3. **`"respect_roles": false` on an effect** lets it drive a fixture its
   role would normally protect — a candle in a strobe. It is the
   override for when you mean it. Leaving it out is right nearly always.
4. **A scene's `brightness` is the ground everything moves against**, and
   effects are read relative to it. A scene at 0.9 with a pulse on top
   has nowhere to go; a scene at 0.45 does.

THE ONE HARD LIMIT: a LIFX bulb accepts about 20 messages a second and
BRight refuses to compile a show that exceeds 18 at any single bulb. Only
STEPPING effects spend messages (chase, sparkle, theater, melody, level,
colour_cycle, rainbow, fade, build) — one per light per step. The bulb
routines cost ONE message each however long they run. So: a chase at
`step_beats: 0.125` across three lights at 128bpm is about 21/s at one
bulb and the whole show is REFUSED — not that effect, the show. Keep
`step_beats` at 0.25 or slower unless the selection is wide, and do not
stack three stepping effects on the same light.

TYPES and their params:
%(catalog)s

Types and parameter names are EXACTLY as listed. Out-of-range numbers are
clamped rather than rejected, and any parameter you leave out takes its
default — write the two or three that matter and skip the rest.

ONE RULE ABOUT LAYERING, and it is physics rather than taste. These
effects are run BY THE BULB: %(routines)s. A bulb runs exactly one of them at a
time, so two overlapping on the SAME light is not a layered effect — the
later one cancels the earlier, and from across the room that reads as an
effect that mysteriously does nothing. Give them different lights, or
different windows. Everything else layers freely, and layering a bulb
routine with those is exactly right: a pulse on the lamps under a chase
across them is two different things happening at once.

`colour_drift` and `saturate` are the two that move COLOUR while leaving
the brightness alone, which nothing else here can do. They are what a
quiet section wants — the room changing without anything flickering —
and they are the only motion a candle can join.

The `//` notes above are ANNOTATION, explaining the shape to you. JSON has
no comments: your answer must be strict JSON — no `//`, no `/* */`, no
trailing comma before a `}` or `]`, and no `<angle brackets>`, which mark
where a value goes rather than being one.

ONE SCENE, WRITTEN WELL — not a template to copy, an example of the
density and the thinking. This is a verse in a room with two lamps, a
strip and candles:

{
  "start": 48.0, "end": 76.0, "mood": "simmer", "base": false,
  "palette": [[268, 0.75], [212, 0.6], [318, 0.5]],
  "brightness": 0.42,
  "effects": [
    {"type": "harmony", "name": "chords on the candles",
     "select": {"roles": ["candle"]},
     "params": {"brightness": 0.4, "fade_ms": 1800}},
    {"type": "melody", "name": "the tune, on the lamps",
     "select": {"roles": ["lamp"]},
     "params": {"hue_spread": 0.55, "voices": 1}},
    {"type": "level", "name": "strip breathes with the kick",
     "select": {"roles": ["strip"]},
     "params": {"band": "low", "floor": 0.15, "ceiling": 0.7,
                "gamma": 1.4}},
    {"type": "build", "name": "lift into the chorus",
     "start": 68.0, "end": 76.0,
     "select": {"roles": ["lamp", "strip"]},
     "params": {"from_brightness": 0.35, "to_brightness": 0.9,
                "curve": "exp"}}
  ]
}

Read what that scene is doing. `base: false` — it grows out of the
section before it. Four effects and each one owns DIFFERENT lights, so
nothing is fighting: harmony has the candles, the tune has the lamps, the
kick has the strip. The build is windowed to the last eight seconds, so
the verse is one thing and then becomes another. Nothing steps faster
than the music. And every choice is about this room — it names the roles
that exist in it.

WHAT MAKES A SHOW BAD, so you can avoid it deliberately:
- One texture per section, end to end, changing only at the boundaries.
- Every effect selecting every light, so the room only ever does one
  thing and effects overwrite each other.
- Chases everywhere. A chase is one idea; four chases is one idea four
  times.
- The peaks doing everything and the verses doing nothing. Most of a
  song is not its chorus.
- Colour chosen at random rather than from the scene's palette."""


def _catalog_lines() -> str:
    """The effect vocabulary, generated from the catalog itself.

    Written out rather than summarised because the model has to answer in
    this language exactly, and a hand-maintained copy of the parameter
    list is a second answer that drifts the first time an effect gains a
    parameter."""
    from . import effects as fx

    lines = []
    for name, spec in fx.CATALOG.items():
        params = ", ".join(
            f"{pname} ({rule['kind']}"
            + (f" {rule['min']}..{rule['max']}" if "min" in rule else "")
            + (f" one of {'|'.join(rule['options'])}" if "options" in rule else "")
            + f", default {rule['default']})"
            for pname, rule in spec["params"].items())
        lines.append(f"  {name} [{spec['channel']}] — {spec['blurb']}\n"
                     f"      {params}")
    return "\n".join(lines)



def _routine_names() -> str:
    """The bulb-side effects, named from the set the compiler enforces.

    Written out by hand once, and it drifted the moment two more effects
    joined the class — the brief went on listing seven while the compiler
    warned about nine, so a model following the brief exactly could
    still write a show whose kick silently cancelled its snare. There is
    one list, and this is it.
    """
    from . import effects as fx

    return ", ".join(f"`{name}`" for name in sorted(fx.BULB_ROUTINES))


def schema_contract() -> str:
    """The contract, with the parts that are generated filled in."""
    return _SCHEMA_CONTRACT % {"catalog": _catalog_lines(),
                               "routines": _routine_names()}

_DIRECTION = """\
You are the lighting director for a home light show. Design the show for
the track below: professional, musical, restrained where the song is and
unleashed where it earns it.

The difference between a show that is SYNCHRONIZED and a show that is
MUSICAL is what it answers. A synchronized show marks the structure —
brighter in the chorus, a hit on the drop, a chase while the energy is
high — and it is what you get by reading only the section map. It looks
correct and it is boring by the second chorus, because the song does a
hundred things in between and the lights do none of them.

A musical show answers what is being PLAYED. Everything you need for that
is measured and listed below:

- **The chord changes** are the single most valuable thing in this brief.
  Harmony turns over every bar or two, on its own clock, almost never
  where the energy changes — so a palette that follows the chords moves
  with the song continuously, in the long stretches where the structure
  is doing nothing. Use the `harmony` effect for this and give it the
  lights that are NOT carrying the beat.
- **The melody** is the line a person in the room is actually listening
  to. `melody` follows it note by note: the pitch picks the colour out of
  your palette and each note lands on the next light along, so a rising
  phrase climbs across the room. Put it on ONE kind of light — the lamps,
  or the strip — and leave the rest to the rhythm, or it turns to mush.
- **The phrases** are where the melody breathes. A gesture that travels
  (a sweep, a build) should start where a phrase starts and end where it
  ends; one that begins mid-phrase reads as an accident.
- **The repeats** are where the song comes back to something. When a
  passage repeats an earlier one, give it the look it had the first time
  — recognition is most of what makes a show feel composed rather than
  reactive. This is the one place you should deliberately NOT invent
  something new.
- **The accents** (below) are the punches. A stab lands on one of those,
  never near one.

So: scenes and drops are the skeleton, and the chords, melody and phrases
are what happens inside them. A verse with a `harmony` ground, the tune on
the lamps and a soft pulse underneath is worth more than any number of
chases.

BUILD THE SHOW OUT OF FOUR LAYERS, ON DIFFERENT LIGHTS
------------------------------------------------------
This is the single most useful structure for this job. A show is four
layers with different time constants, and what makes it read as musical
rather than busy is that they are SEPARATE:

- **ground** — the room's colour, moving with the harmony. Seconds-long.
  This is the only layer that should ever feel like fading. Give it the
  lights that are not keeping time: candles, a strip, whatever is left.
- **pulse** — the beat, on lights doing nothing else. Use `hit`, not
  `pulse`: a hit STRIKES on the beat and decays, a pulse swells. Mostly
  felt rather than watched.
- **hits** — the kick and the snare, as separate instruments on
  different lights. `accent` with `band: "low"` is the kick and
  `band: "mid"` is the snare, and they land on the drums the analyzer
  actually heard rather than on the beat grid, so they catch the fills
  a grid knows nothing about.
- **voice** — the melody, tracking real pitch (`melody`). This is the
  layer that makes a room feel like it is playing along. PUT IT IN THE
  CHORUS TOO. A chorus is the part of a song people know the tune of,
  and a room that stops following it exactly there stops playing along
  where it matters most — it works in a chorus because it owns its own
  lights, not because the chorus is quiet.

Two rules follow, and both are hard:

1. **One fixture, one rhythmic layer.** A LIFX bulb runs ONE waveform at
   a time, so two of the bulb-side effects on one light is the second
   cancelling the first. If the room has fewer kinds of light than you
   have layers, SPLIT a role by naming ids: the left two lamps are the
   kick, the right two are the snare. That is what a designer does with
   six lamps and four ideas, and it is far better than one effect across
   every bulb.
2. **A layer arriving is itself an event.** A chorus does not land
   because it is brighter than the verse. It lands because something NEW
   starts happening on lights that were doing something else a moment
   ago — the strip joins the kick, the lamps stop washing and start
   following the tune. Design the entrances, not just the levels.

Principles:
- The section map and drops are measured from the audio — trust them.
  Scenes should follow the section boundaries (merge or split a little
  where the music narrative wants it).
- Build tension INTO a drop (dim, tighten) so the hit lands.
- Candles are ambience: warm, low, never flashing. Lamps and downlights
  carry the beat. Strips carry motion (sweeps). Party lights and lasers
  are aux switches — save them for peaks and drops or they mean nothing.
- THE ROOM section below is the real floor plan, placed by hand. Every
  light has an id, a name, a role, a zone and an x/y position, and the
  travel orders are worked out for you at the bottom of it. Design for
  that room specifically: "the two lamps either side of the sofa answer
  each other" is a real idea about a real place, and it is available to
  you because the map says where they are.
- Select by ROLE for anything that should keep working when a bulb is
  added ("every candle"), and by ID when the idea is about particular
  lights ("these two, alternating"). Both are honoured; ids are listed in
  THE ROOM and are exact. Zones, where the map defines them, are the
  natural unit for "one area of the house".
- With fewer than three moving lights a chase is a flicker — alternate
  them instead (theater).
- `pulse`, `breathe` and `sweep` are SWELLS: they travel smoothly up to a
  level and back. `hit`, `accent`, `stab` and `strobe` have an ATTACK:
  they are at full brightness the instant they land and decay from
  there. A show made only of swells is what "just a bunch of fading
  lights" means — reach for the second group for anything rhythmic and
  keep the swells for the ground.
- Effects can own different parts of the room at once. A chase across the
  lamps while the strip holds a wash is one scene with two effects and
  two selections, and it reads far better than one effect over everything.
- Pick palettes that fit the song's feel, and CHANGE them meaningfully
  between sections — a chorus should look different from its verse.
- If synced lyrics are given, choose up to 4 lyric_moment features at the
  lines that deserve a visual answer (the title line, the hook, a turn).
- Less is more: one intentional motif per scene beats three busy ones."""


def _digest_facts(analysis: dict) -> str:
    """What was measured from the audio — shared by the first draft and
    every revision, because a director with notes still needs the song."""
    tags = analysis.get("tags") or {}
    lines = [
        f"TRACK: {tags.get('title') or 'unknown'} — "
        f"{tags.get('artist') or 'unknown artist'}",
        f"bpm={analysis.get('bpm')} "
        f"duration={library.duration_of(analysis):.0f}s "
        f"brightness_hint={analysis.get('brightness')} (0=dark/warm 1=bright)",
        "",
        "SECTIONS (start-end kind energy):",
    ]
    for section in analysis.get("sections") or []:
        lines.append(f"  {section['start']:.0f}-{section['end']:.0f}s "
                     f"{section['kind']} energy={section['energy']}")
    drops = analysis.get("drops") or []
    lines.append("DROPS: " + (", ".join(
        f"{d['t']:.1f}s (strength {d.get('strength')})" for d in drops)
        if drops else "none detected"))

    hits = sorted((h for h in analysis.get("hits") or []
                   if h.get("on_beat")),
                  key=lambda h: h.get("strength", 0), reverse=True)[:24]
    if hits:
        hits.sort(key=lambda h: h["t"])
        lines.append(
            "STRONGEST HITS (measured accents sitting ON the beat — the "
            "moments a stab lands where the ear expects it; strength is "
            "relative to the track's own loudest hit):")
        lines.append("  " + ", ".join(
            f"{h['t']:.2f}s ({h['strength']:.2f})" for h in hits))
        lines.append(
            '  Put a moment\'s "t" on one of these and add "snap": "beat" '
            "beside it — the compiler then lands it exactly on the "
            "analyzed beat, so a slightly rounded time cannot smear the "
            "hit. Choose a FEW: one intentional accent beats three busy "
            "ones.")
    lines.extend(_musical_lines(analysis))
    return "\n".join(lines)


# How much of each musical list the brief can afford. A four-minute track
# can carry 600 notes and they are the least useful thing here per
# character: the `melody` effect reads the full list at compile time
# straight from the analysis, so the model never needs the notes
# themselves — only enough of the shape to decide WHERE to put a melody
# effect and what it will look like. The chords are the opposite: they
# are the thing to design around, so they get the room.
MAX_BRIEF_CHORDS = 60
MAX_BRIEF_PHRASES = 14
MAX_BRIEF_REPEATS = 8


def _musical_lines(analysis: dict) -> list[str]:
    """The musical map: harmony, the shape of the tune, and what repeats.

    Everything here is measured. It is rendered as prose-shaped lines
    rather than JSON because the model is being asked to make decisions
    about it, not to parse it — and because a list of 600 note events
    would crowd out the room description, which is the other half of
    every good decision it makes.
    """
    musical = analysis.get("music") or {}
    chords = musical.get("chords") or []
    notes = musical.get("notes") or []
    phrases = musical.get("phrases") or []
    repeats = musical.get("repeats") or []
    if not (chords or notes or phrases or repeats):
        # Said out loud rather than left as four missing sections: a
        # model that is not told the melody is absent will assume it was
        # simply not worth mentioning and write a melody effect anyway,
        # which compiles to nothing.
        return ["", "MUSICAL MAP: not available for this track (it was "
                "analysed by an older version of BRight). Do NOT use the "
                "`melody` or `harmony` effects — they would render to "
                "nothing. Design from the sections, drops and accents."]

    lines = ["", "MUSICAL MAP — what the song is playing:"]
    if musical.get("key"):
        lines.append(f"  key: {musical['key']}")
    if chords:
        shown = chords[:MAX_BRIEF_CHORDS]
        lines.append(f"  chord changes ({len(chords)} in the track, "
                     f"{len(shown)} listed — time: chord):")
        lines.append("    " + ", ".join(
            f"{c['t']:.1f}s {c['name']}" for c in shown))
        if len(chords) > len(shown):
            lines.append(f"    … {len(chords) - len(shown)} more. The "
                         "`harmony` effect reads ALL of them at compile "
                         "time — you are choosing where it runs, not "
                         "listing the chords yourself.")
    if notes:
        pitches = [int(n.get("m", 0)) for n in notes]
        lines.append(
            f"  melody: {len(notes)} notes, from {min(pitches)} to "
            f"{max(pitches)} (MIDI), tracked from the loudest melodic "
            f"voice. The `melody` effect reads them all; you decide which "
            f"lights follow it and where.")
    if phrases:
        shown = phrases[:MAX_BRIEF_PHRASES]
        lines.append(f"  phrases ({len(phrases)}, {len(shown)} listed — a "
                     "gesture that travels should start and end with one):")
        for phrase in shown:
            lines.append(f"    {phrase['start']:.1f}-{phrase['end']:.1f}s "
                         f"{phrase['dir']}, {phrase['notes']} notes")
    if repeats:
        lines.append("  repeats — these passages come back; give a repeat "
                     "the look its original had:")
        for repeat in repeats[:MAX_BRIEF_REPEATS]:
            lines.append(f"    {repeat['start']:.1f}-{repeat['end']:.1f}s "
                         f"repeats {repeat['same_as']:.1f}s")
    return lines


def _digest(analysis: dict, fixtures: list[dict],
            vibe: str | None = None) -> str:
    lines = [
        _DIRECTION,
        "",
        schema_contract(),
        "",
    ]
    if vibe:
        lines += [f"THE HOST ASKED FOR THIS VIBE: {vibe[:120]}", ""]
    lines.append(_digest_facts(analysis))
    lines.append("")
    lines.append(room.describe(fixtures))

    lines.append("")
    lines.append(effect_presets.describe())

    lyrics = analysis.get("lyrics") or {}
    if lyrics.get("synced") and lyrics.get("lines"):
        lines.append("")
        lines.append("SYNCED LYRICS ([seconds] line):")
        for entry in lyrics["lines"][:MAX_LYRIC_LINES]:
            lines.append(f"  [{entry['t']}] {entry['text']}")
        if len(lyrics["lines"]) > MAX_LYRIC_LINES:
            lines.append(f"  … {len(lyrics['lines']) - MAX_LYRIC_LINES} more lines")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The task round-trip
# ---------------------------------------------------------------------------
# How long to wait for brAIn to CLAIM a task before concluding nothing is
# listening. Its listener claims by renaming `<id>.json` to `<id>.work.<pid>`
# the moment it sees the file — inotify when available, a 5s poll otherwise
# — so thirty seconds is six fallback cycles and not a race.
CLAIM_GRACE_S = 30


def _run_task(prompt: str, timeout_s: float,
              sleep=time.sleep, clock=time.monotonic) -> str:
    """One brAIn automation task: write the request, poll for the answer.
    Blocking — build_show already runs in a worker thread.

    Two failures live here and they are NOT the same, which is the whole
    reason this function watches the task file as well as the result
    directory. `available()` only says the tasks directory exists, and
    that directory outlives the listener that made it — so a brAIn whose
    Automation integration is switched off (or which is simply not
    running) looks exactly like a working one until the wait expires. It
    used to cost ten minutes of spinner and then a message blaming a
    timeout, which sends somebody to look at the slowest thing in the
    system when the truth is that nobody was listening at all.

    brAIn's listener CLAIMS a task by renaming it out of the way before
    it does any work, so an un-renamed file is a definitive answer: no
    listener. That one is caught in thirty seconds and says what to
    switch on. A claimed task that never answers is a different sentence,
    and it points at brAIn's own log, where the reason will be.
    """
    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "prompt": prompt,
        "notify": False,
        "ts": time.time(),
        "timeout": int(timeout_s),
    }
    model = _director_model()
    if model:
        task["model"] = model
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_path = TASKS_DIR / f"{task_id}.json"
    # Unique-by-id scratch name; same rename discipline as everything else.
    scratch = TASKS_DIR / f".{task_id}.writing"
    scratch.write_text(json.dumps(task))
    scratch.replace(task_path)

    result_path = RESULTS_DIR / f"{task_id}.json"
    started = clock()
    deadline = started + timeout_s
    claimed = False
    while clock() < deadline:
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text())
            except (OSError, ValueError):
                sleep(POLL_S)
                continue
            result_path.unlink(missing_ok=True)
            text = payload.get("result") or ""
            if payload.get("status") == "completed" and text:
                return text
            raise RuntimeError(
                f"brAIn task ended {payload.get('status')!r}: {text[:200]}")
        if not claimed:
            # Renamed out of the way = the listener has it. Checked before
            # the grace expires so a fast claim is never mistaken for a
            # slow one.
            if not task_path.exists():
                claimed = True
            elif clock() - started > CLAIM_GRACE_S:
                task_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"brAIn never picked this up ({CLAIM_GRACE_S}s). Its "
                    f"task folder is there but nothing is reading it: open "
                    f"the brAIn add-on and check it is running with its "
                    f"Automation integration switched on — that listener is "
                    f"what answers BRight.")
        sleep(POLL_S)
    task_path.unlink(missing_ok=True)  # don't leave a stale ask behind
    raise RuntimeError(
        f"brAIn picked this up but did not answer within {int(timeout_s)}s "
        f"— its own log says why (Settings → Add-ons → brAIn → Log).")


def _decomment(text: str) -> str:
    """JSON with the things models write into JSON taken back out.

    Two of them, and both are here because the schema contract above
    *demonstrates* the first: every field in that example carries a `//`
    note explaining it, so a model imitating the shape it was shown emits
    them too. That is a comment in a format that has none, and
    `json.loads` stops at it with `Expecting ',' delimiter` — the failure
    that sent two real shows to the algorithmic floor before anyone knew
    why. The prompt says not to now; this is what happens when it does
    anyway. Trailing commas are the same class: legal in every language
    the model has read more of than JSON.

    The scan tracks string literals, because both of these are only
    punctuation when they are *outside* one — `"pop // rock"` is a mood
    somebody could reasonably name, and a URL in a label is two slashes
    that must survive. Escapes are honoured so a `\"` cannot end a string
    early and turn the rest of the answer into syntax.
    """
    out: list[str] = []
    in_string = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text):
            following = text[index + 1]
            if following == "/":
                while index < len(text) and text[index] != "\n":
                    index += 1
                continue
            if following == "*":
                end = text.find("*/", index + 2)
                index = len(text) if end < 0 else end + 2
                continue
        if char == ",":
            # A comma is trailing when the next thing that is not
            # whitespace closes the collection it is sitting in.
            look = index + 1
            while look < len(text) and text[look].isspace():
                look += 1
            if look < len(text) and text[look] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _extract_json(text: str) -> dict:
    """The one JSON object in the answer, fences and prose tolerated —
    models narrate even when told not to, and the validator downstream is
    the real gate."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    body = _decomment(text[start:end + 1])
    try:
        return json.loads(body)
    except ValueError as exc:
        # A column number about a document nobody can see is not a
        # diagnosis. `Expecting ',' delimiter: line 1 column 222` was all
        # the log ever said, and the answer it was about had already been
        # thrown away — so the next person to hit it starts where the last
        # one did. Quote what actually broke.
        raise ValueError(f"{exc} — near: {_around(body, exc)}") from None


def _around(body: str, exc: ValueError, span: int = 60) -> str:
    """The text either side of where the parser gave up, on one line."""
    position = getattr(exc, "pos", None)
    if not isinstance(position, int):
        return body[:span].replace("\n", " ")
    start = max(0, position - span // 2)
    excerpt = body[start:position + span // 2].replace("\n", " ")
    return f"...{excerpt}..." if start else f"{excerpt}..."


def digest(analysis: dict, fixtures: list[dict],
           vibe: str | None = None) -> str:
    """The brief, for anyone who wants to read it.

    A public name on the private builder rather than a second rendering:
    the panel shows people exactly what the director is handed, and a
    "roughly what we send" page would be a copy that drifts the first time
    the real prompt gains a section.
    """
    return _digest(analysis, fixtures, vibe)


def write_script(analysis: dict, fixtures: list[dict],
                 timeout_s: float = TASK_TIMEOUT_S,
                 vibe: str | None = None) -> dict:
    """The script_writer build.py plugs in. Raises on any failure; the
    caller decides whether that lands on the algorithmic floor."""
    if not available():
        raise RuntimeError("brAIn is not installed (no /config/.brain/tasks) "
                           "— the Claude director needs it")
    answer = _run_task(_digest(analysis, fixtures, vibe), timeout_s)
    script = _extract_json(answer)
    script["tier"] = "claude"
    script["track_hash"] = analysis.get("hash")
    script.setdefault("version", 1)
    return script

# ---------------------------------------------------------------------------
# A show, revised to a sentence
# ---------------------------------------------------------------------------
# Feedback is a note to the director, not a diff. The whole current script
# goes back with it, because "the chorus is too dark" is about a scene the
# model has to be able to see — and the answer is a complete script again,
# through the same validator and compiler as everything else, so a revision
# gets no privileges a hand edit doesn't.
MAX_FEEDBACK_CHARS = 600

_REVISE_DIRECTION = """\
You are the lighting director for a home light show. You already wrote the
script below, the host watched it run, and they have notes. Revise the
script to LAND their notes.

- Change what the notes are about, decisively — a revision nobody can see
  is worse than none. If they say the drop was weak, make the drop hit.
- Keep everything the notes are NOT about. The rest of the show is what
  they liked well enough not to mention; a rewrite from scratch throws
  that away.
- The notes are in the host's own words. Read them for intent: "too much
  flashing" is about strobes and pulses wherever they are, not one scene.
- Answer with the COMPLETE revised script in the same JSON shape — scenes
  covering the track, moments, all of it — not a fragment or a diff."""


def revise_script(script: dict, feedback: str, analysis: dict,
                  fixtures: list[dict],
                  timeout_s: float = TASK_TIMEOUT_S) -> dict:
    """The host's notes, applied by the director who wrote the show.

    Raises on any failure — the caller keeps the current script, because a
    revision that failed must never cost the show that was running last
    night."""
    feedback = (feedback or "").strip()
    if not feedback:
        raise ValueError("say what you want changed first")
    if not available():
        raise RuntimeError("brAIn is not installed (no /config/.brain/tasks) "
                           "— revising a show with Claude needs it")
    current = {k: v for k, v in script.items()
               if k not in ("tier", "track_hash")}
    prompt = "\n".join([
        _REVISE_DIRECTION,
        "",
        schema_contract(),
        "",
        _digest_facts(analysis),
        "",
        room.describe(fixtures),
        "",
        effect_presets.describe(),
        "",
        "THE CURRENT SCRIPT (the one they watched):",
        json.dumps(current, indent=1),
        "",
        "THE HOST'S NOTES:",
        feedback[:MAX_FEEDBACK_CHARS],
    ])
    answer = _run_task(prompt, timeout_s)
    revised = _extract_json(answer)
    revised["tier"] = "claude"
    revised["track_hash"] = analysis.get("hash")
    revised.setdefault("version", script.get("version", 2))
    return revised


# ---------------------------------------------------------------------------
# One effect, from a sentence
# ---------------------------------------------------------------------------
# A show is four minutes of decisions; an effect is one idea, and people
# have ideas in sentences ("bounce a warm pulse between the two window
# lamps"). Same room description, same catalog, same validator — the only
# difference is the size of the answer, so the two prompts share everything
# that describes the instrument and differ only in what is being asked for.
EFFECT_TIMEOUT_S = 180

_EFFECT_CONTRACT = """\
Answer with ONE JSON object and nothing else — no prose, no code fences.
It is a single effect:

{
  "type": "<one of the types below>",
  "name": "<short label; it rides on every cue the effect makes>",
  "select": {"roles": [...], "ids": [...], "zones": [...], "exclude": [...]},
  "order": "x" | "-x" | "y" | "-y" | "center_out" | "edges_in" | "snake"
           | "zone" | "listed" | "random",
  "params": { ... }
}

`select` names the lights this effect owns, and **every light it does not
name is left untouched** — that is the whole point of an effect, so select
the few that carry the idea rather than everything. An empty `select` means
all of them. Select by role for an idea about a kind of light, by id for an
idea about particular ones, by zone for an idea about an area.

Timing is in BEATS, not seconds: this will be dropped into a song and the
tempo is not yours to choose.

TYPES and their params:
%(catalog)s

Types and parameter names are EXACTLY as listed. Out-of-range numbers are
clamped rather than rejected, and anything you leave out takes its default
— write the two or three parameters that carry the idea and skip the rest."""

_EFFECT_DIRECTION = """\
You are a lighting designer. Someone has described one effect they want for
the room below. Write it.

- Design for THIS room. The ids and names are real; the positions are where
  the lights actually are.
- One idea, done well. If the description implies two things happening at
  once, pick the one that carries it — a second effect can be added beside
  this one.
- Restraint reads as intent. Most of a room usually stays still."""


def _effect_prompt(description: str, fixtures: list[dict]) -> str:
    return "\n".join([
        _EFFECT_DIRECTION,
        "",
        _EFFECT_CONTRACT % {"catalog": _catalog_lines()},
        "",
        room.describe(fixtures),
        "",
        effect_presets.describe(),
        "",
        "WHAT THEY ASKED FOR:",
        description.strip()[:400],
    ])


def write_effect(description: str, fixtures: list[dict],
                 timeout_s: float = EFFECT_TIMEOUT_S) -> dict:
    """A sentence becomes one validated effect. Raises on any failure.

    The validator is `effects.clean_effect`, the same one a hand-typed
    effect goes through — a generated effect gets no privileges, and an
    unknown type or a nonsense parameter is caught here rather than at
    compile time in the middle of somebody's evening.
    """
    from . import effects as fx

    if not description.strip():
        raise ValueError("describe the effect you want first")
    if not available():
        raise RuntimeError("brAIn is not installed (no /config/.brain/tasks) "
                           "— writing an effect from a description needs it")
    answer = _run_task(_effect_prompt(description, fixtures), timeout_s)
    raw = _extract_json(answer)
    try:
        effect = fx.clean_effect(raw)
    except fx.EffectError as exc:
        raise ValueError(f"Claude wrote an effect BRight cannot use: {exc}") \
            from None
    effect.setdefault("name", description.strip()[:48])
    return effect


# ---------------------------------------------------------------------------
# Effects nobody had to think of
# ---------------------------------------------------------------------------
MAX_IDEAS = 6

_INVENT_CONTRACT = """\
Answer with ONE JSON object and nothing else — no prose, no code fences:

{"effects": [ {<effect>, "why": "<one sentence>"}, ... ]}

Each <effect> is exactly the object described above, plus a `why`: one
sentence, about THIS room, saying what the idea is and where it happens.
"the two window lamps answer each other across the bay" is a why. "a nice
chase effect" is not — it would be true of any room, and a reason that
would be true anywhere is not a reason for here."""

_INVENT_DIRECTION = """\
You are a lighting designer looking at somebody's actual room. Propose
%(count)d effects worth having in it.

Nobody has asked for anything specific, so the room is the brief:

- Read the map. Where the lights ARE is the material — two lamps facing
  each other across a sofa, a strip along one wall, candles in a corner
  that should stay calm. An idea that ignores the positions could have
  been written without ever seeing this room, and it will look like it.
- Make them DIFFERENT from each other. Six variations on a chase is one
  idea with six sets of parameters. Vary what moves, how much of the room
  is involved, and how loud it is — at least one should be quiet enough
  for a verse and at least one big enough for a drop.
- Most of the room usually stays still. An effect that names three lights
  and leaves the rest alone is generally better than one that takes
  everything, and it can be layered with another.
- Respect what each role is for. Candles are ambience and should not
  strobe; a laser is a moment, not a texture.
- Timing is in BEATS. These will be dropped into songs you have not
  heard."""


def invent_effects(fixtures: list[dict], count: int = 4,
                   timeout_s: float = EFFECT_TIMEOUT_S) -> list[dict]:
    """Effects built for this room, with nothing typed in.

    The other half of `write_effect`. Describing what you want assumes you
    already know what is possible in your own room, which is the thing a
    person with a new light map most reliably does not — and "what would
    look good in here" is a question about a floor plan, which is exactly
    what BRight has and the person is looking at.

    Every idea goes through `effects.clean_effect`, the same validator a
    hand-typed effect meets. One unusable idea costs that idea and not the
    batch: a model asked for six things will occasionally get one wrong,
    and throwing away five good ones to punish it would make the feature
    useless at the moment it is most useful.
    """
    from . import effects as fx

    # The map is checked first, and not for tidiness: an empty map is a
    # complaint about this install that is true whether or not brAIn is
    # here, and sending somebody to install brAIn when what they actually
    # need is to place a light is the wrong errand.
    if not fixtures:
        raise ValueError("no lights on the map yet — the Light Map tab is "
                         "where an effect gets something to drive")
    if not available():
        raise RuntimeError("brAIn is not installed (no /config/.brain/tasks) "
                           "— inventing effects needs it")
    count = max(1, min(MAX_IDEAS, int(count)))
    prompt = "\n".join([
        _INVENT_DIRECTION % {"count": count},
        "",
        _EFFECT_CONTRACT % {"catalog": _catalog_lines()},
        "",
        _INVENT_CONTRACT,
        "",
        room.describe(fixtures),
        "",
        effect_presets.describe(),
    ])
    answer = _run_task(prompt, timeout_s)
    raw = _extract_json(answer)
    ideas = raw.get("effects")
    if not isinstance(ideas, list) or not ideas:
        raise ValueError("Claude answered with no effects")

    kept: list[dict] = []
    for item in ideas[:MAX_IDEAS]:
        if not isinstance(item, dict):
            continue
        # `why` is ours, not the catalog's, so it is lifted out before the
        # validator sees the effect and put back afterwards — `clean_effect`
        # keeps only what an effect is allowed to carry, which is what
        # stops a generated one smuggling in a field the compiler will
        # later trip over.
        why = str(item.get("why", "") or "").strip()[:200]
        try:
            effect = fx.clean_effect({k: v for k, v in item.items()
                                      if k != "why"})
        except fx.EffectError:
            continue
        effect["why"] = why
        kept.append(effect)
    if not kept:
        raise ValueError("Claude's ideas were all effects BRight cannot use")
    return kept
