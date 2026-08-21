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

# A show script is one long considered answer, not a quick reply.
TASK_TIMEOUT_S = 240
POLL_S = 1.0

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

TYPES and their params:
%s

Types and parameter names are EXACTLY as listed. Out-of-range numbers are
clamped rather than rejected, and any parameter you leave out takes its
default — write the two or three that matter and skip the rest.

The `//` notes above are ANNOTATION, explaining the shape to you. JSON has
no comments: your answer must be strict JSON — no `//`, no `/* */`, no
trailing comma before a `}` or `]`, and no `<angle brackets>`, which mark
where a value goes rather than being one."""


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


_DIRECTION = """\
You are the lighting director for a home light show. Design the show for
the track below: professional, musical, restrained where the song is and
unleashed where it earns it.

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
- Effects can own different parts of the room at once. A chase across the
  lamps while the strip holds a wash is one scene with two effects and
  two selections, and it reads far better than one effect over everything.
- Pick palettes that fit the song's feel, and CHANGE them meaningfully
  between sections — a chorus should look different from its verse.
- If synced lyrics are given, choose up to 4 lyric_moment features at the
  lines that deserve a visual answer (the title line, the hook, a turn).
- Less is more: one intentional motif per scene beats three busy ones."""


def _digest(analysis: dict, fixtures: list[dict],
            vibe: str | None = None) -> str:
    tags = analysis.get("tags") or {}
    lines = [
        _DIRECTION,
        "",
        _SCHEMA_CONTRACT % _catalog_lines(),
        "",
    ]
    if vibe:
        lines += [f"THE HOST ASKED FOR THIS VIBE: {vibe[:120]}", ""]
    lines += [
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
def _run_task(prompt: str, timeout_s: float,
              sleep=time.sleep, clock=time.monotonic) -> str:
    """One brAIn automation task: write the request, poll for the answer.
    Blocking — build_show already runs in a worker thread."""
    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "prompt": prompt,
        "notify": False,
        "ts": time.time(),
        "timeout": int(timeout_s),
    }
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_path = TASKS_DIR / f"{task_id}.json"
    # Unique-by-id scratch name; same rename discipline as everything else.
    scratch = TASKS_DIR / f".{task_id}.writing"
    scratch.write_text(json.dumps(task))
    scratch.replace(task_path)

    result_path = RESULTS_DIR / f"{task_id}.json"
    deadline = clock() + timeout_s
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
        sleep(POLL_S)
    task_path.unlink(missing_ok=True)  # don't leave a stale ask behind
    raise RuntimeError(f"brAIn did not answer within {int(timeout_s)}s")


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
# One effect, from a sentence
# ---------------------------------------------------------------------------
# A show is four minutes of decisions; an effect is one idea, and people
# have ideas in sentences ("bounce a warm pulse between the two window
# lamps"). Same room description, same catalog, same validator — the only
# difference is the size of the answer, so the two prompts share everything
# that describes the instrument and differ only in what is being asked for.
EFFECT_TIMEOUT_S = 90

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
%s

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
        _EFFECT_CONTRACT % _catalog_lines(),
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
        _EFFECT_CONTRACT % _catalog_lines(),
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
