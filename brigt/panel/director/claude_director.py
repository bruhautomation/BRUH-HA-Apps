"""The Claude director tier: creative choreography, delegated to brAIn.

BRigt's container carries no Claude CLI and asks for no second login.
When brAIn is installed on the same Home Assistant, its automation-task
surface (`/config/.brain/tasks/` in, `/config/.brain/task_results/` out —
the same files the `brain.run_task` service rides) is already a logged-in
Claude, so BRigt hands it the track digest and the script schema and gets
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

BRAIN_SHARED = Path(os.environ.get("BRIGT_BRAIN_SHARED", "/config/.brain"))
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
  "version": 1,
  "scenes": [
    {
      "start": <seconds>, "end": <seconds>,   // cover the track, in order
      "mood": "<one word>",
      "palette": [[<hue 0-360>, <saturation 0-1>], ...],  // 2-4 pairs
      "brightness": <0-1>,                    // the scene's base level
      "motifs": [
        {"type": "beat_pulse", "roles": [...], "depth": <0-1>},
        {"type": "sweep", "roles": [...], "period_beats": <int>},
        {"type": "breathe", "roles": [...], "period_beats": <int>, "depth": <0-1>},
        {"type": "aux_on", "roles": ["party"|"laser"]}
      ]
    }
  ],
  "features": [
    {"t": <seconds>, "type": "drop_hit", "roles": [...], "strength": <0-1>,
     "blackout_before_ms": <int>},
    {"t": <seconds>, "type": "lyric_moment", "roles": [...]}
  ]
}

Motif types and feature types are EXACTLY the ones shown. Roles may only
be roles the fixture list below actually has."""

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
- Pick palettes that fit the song's feel, and CHANGE them meaningfully
  between sections — a chorus should look different from its verse.
- If synced lyrics are given, choose up to 4 lyric_moment features at the
  lines that deserve a visual answer (the title line, the hook, a turn).
- Less is more: one intentional motif per scene beats three busy ones."""


def _digest(analysis: dict, fixtures: list[dict]) -> str:
    tags = analysis.get("tags") or {}
    lines = [
        _DIRECTION,
        "",
        _SCHEMA_CONTRACT,
        "",
        f"TRACK: {tags.get('title') or 'unknown'} — "
        f"{tags.get('artist') or 'unknown artist'}",
        f"bpm={analysis.get('bpm')} duration={tags.get('duration')}s "
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

    roster: dict[str, list] = {}
    for fixture in fixtures:
        roster.setdefault(fixture["role"], []).append(fixture)
    lines.append("")
    lines.append("FIXTURES (role: count, left-to-right x positions):")
    for role, members in sorted(roster.items()):
        xs = ", ".join(f"{m.get('x', 0.5):.2f}" for m in members)
        lines.append(f"  {role}: {len(members)} at x=[{xs}]")

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


def _extract_json(text: str) -> dict:
    """The one JSON object in the answer, fences and prose tolerated —
    models narrate even when told not to, and the validator downstream is
    the real gate."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def write_script(analysis: dict, fixtures: list[dict],
                 timeout_s: float = TASK_TIMEOUT_S) -> dict:
    """The script_writer build.py plugs in. Raises on any failure; the
    caller decides whether that lands on the algorithmic floor."""
    if not available():
        raise RuntimeError("brAIn is not installed (no /config/.brain/tasks) "
                           "— the Claude director needs it")
    answer = _run_task(_digest(analysis, fixtures), timeout_s)
    script = _extract_json(answer)
    script["tier"] = "claude"
    script["track_hash"] = analysis.get("hash")
    script.setdefault("version", 1)
    return script
