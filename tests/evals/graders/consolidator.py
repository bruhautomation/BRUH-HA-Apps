"""The consolidator: under its cap, a person's lines kept word for word,
and a contradiction settled toward the newest correction.

Output: what one real ``brain-memory-consolidate.sh --once`` left behind —
``{"rc", "memory", "voice", "memory_before"}``. Graded on the files, not on
the reply, because the script's own guards (size, shrink, empty template)
are part of the job: a pass the script refused leaves the document as it
was, and a case that needed the merge then fails on what it lacks.

expect:
  ``max_bytes``  the memory.md cap (default the case input's ``max_kb``,
                 else the script's 32 KB)
  ``voice_max_bytes``  2048, the script's hard voice.md cap
  ``verbatim``   lines a person wrote, each of which must survive exactly
  ``present``    specs that must be in memory.md after the pass
  ``absent``     specs that must not be (a FORGET, a superseded claim)
  ``newer_wins`` ``[{"new": spec, "old": spec}]``: the newest correction's
                 claim present and the claim it replaced gone
  ``filed``      true when the pass must have run (rc 0, document changed)
"""
from __future__ import annotations

from .common import dated, first_failure, failed, matches

DEFAULT_MAX_KB = 32
VOICE_MAX_BYTES = 2048


def _lines(text: str) -> set[str]:
    return {line.strip() for line in str(text or "").splitlines() if line.strip()}


def grade(case: dict, output: dict) -> dict:
    output = output or {}
    expect = dated(case.get("expect") or {})
    memory = output.get("memory")
    if not isinstance(memory, str):
        return failed("no memory.md after the pass")
    problems = []
    max_kb = int((case.get("input") or {}).get("max_kb") or DEFAULT_MAX_KB)
    cap = int(expect.get("max_bytes") or max_kb * 1024)
    size = len(memory.encode("utf-8"))
    if size > cap:
        problems.append(f"memory.md is {size} bytes, over its {cap} byte cap")
    voice = output.get("voice") or ""
    vcap = int(expect.get("voice_max_bytes") or VOICE_MAX_BYTES)
    if len(voice.encode("utf-8")) > vcap:
        problems.append(f"voice.md is over its {vcap} byte cap")
    if expect.get("filed"):
        if output.get("rc") not in (0, None):
            problems.append(f"the pass did not run (exit {output.get('rc')})")
        elif memory == output.get("memory_before"):
            problems.append("the pass filed nothing")
    have = _lines(memory)
    for line in expect.get("verbatim") or []:
        if line.strip() not in have:
            problems.append(f"a person's line was changed or dropped: {line!r}")
    for spec in expect.get("present") or []:
        if not matches(memory, spec):
            problems.append(f"missing {spec!r}")
    for spec in expect.get("absent") or []:
        if matches(memory, spec):
            problems.append(f"still says {spec!r}")
    for pair in expect.get("newer_wins") or []:
        if not matches(memory, pair.get("new")):
            problems.append(f"the newest correction {pair.get('new')!r} is missing")
        if matches(memory, pair.get("old")):
            problems.append(f"the superseded claim {pair.get('old')!r} survived")
    return first_failure(problems)
