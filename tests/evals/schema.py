"""The case shape, and the one loader every caller reads cases through.

A case is a JSON file under ``cases/<job>/``::

    {"id": "...", "job": "extractor", "kind": "regression",
     "input": {...}, "expect": {...}, "origin": "..."}

``origin`` names the real failure the case came from: an issue, a note's
anecdote, a test that encodes a shipped bug. A case built by hand to probe
a rule nobody has seen fail is ``"synthetic"``, and a synthetic case may
only be a ``capability`` case: the regression suite is the one that blocks
a pull request, and it blocks on things that have happened, never on a
guess about what might. ``rule`` (optional) says in a sentence what the
case holds the job to.

There is no ``jsonschema`` dependency, for the reason ``tests/corpus``
gives: two files agreeing about a shape does not need one. ``validate``
is the schema, and the test suite runs it over every case.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"

JOBS = ("extractor", "consolidator", "reflect", "first_look",
        "morph_learning", "devloop_streams")
KINDS = ("regression", "capability")
REQUIRED = ("id", "job", "kind", "input", "expect", "origin")
OPTIONAL = ("rule", "title", "trials", "notes")
SYNTHETIC = "synthetic"


def validate(case: dict, path: Path | None = None) -> list[str]:
    """Every problem with one case, as sentences. [] is a valid case."""
    where = f"{path.name}: " if path else ""
    if not isinstance(case, dict):
        return [f"{where}a case is a JSON object"]
    problems = []
    for key in REQUIRED:
        if key not in case:
            problems.append(f"{where}missing {key!r}")
    unknown = sorted(set(case) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        problems.append(f"{where}unknown keys {unknown}")
    if case.get("job") not in JOBS:
        problems.append(f"{where}job {case.get('job')!r} is not one of {JOBS}")
    if case.get("kind") not in KINDS:
        problems.append(f"{where}kind {case.get('kind')!r} is not one of {KINDS}")
    for key in ("input", "expect"):
        if key in case and not isinstance(case[key], dict):
            problems.append(f"{where}{key} must be an object")
    origin = case.get("origin")
    if not isinstance(origin, str) or not origin.strip():
        problems.append(f"{where}origin must name where the case came from")
    elif case.get("kind") == "regression" and origin.strip() == SYNTHETIC:
        problems.append(f"{where}a regression case must come from a real "
                        "failure; a synthetic case is a capability case")
    if not isinstance(case.get("id"), str) or not case.get("id"):
        problems.append(f"{where}id must be a non-empty string")
    elif path is not None and path.stem != case["id"]:
        problems.append(f"{where}id {case['id']!r} must match the file name")
    if path is not None and path.parent.name != case.get("job"):
        problems.append(f"{where}lives under cases/{path.parent.name}/ but "
                        f"says job {case.get('job')!r}")
    trials = case.get("trials")
    if trials is not None and (not isinstance(trials, int) or trials < 1):
        problems.append(f"{where}trials must be a positive integer")
    return problems


def case_files(directory: Path = CASES_DIR) -> list[Path]:
    return sorted(directory.glob("*/*.json"))


def load_cases(directory: Path = CASES_DIR, *, jobs=None, kind: str = "",
               only: str = "") -> list[dict]:
    """Every case, validated, sorted by job then id. A bad case is a
    SystemExit naming it rather than a case silently skipped: a suite that
    shrinks without saying so is a gate that opened by itself."""
    out = []
    for path in case_files(directory):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{path}: not readable as JSON — {exc}")
        problems = validate(case, path)
        if problems:
            raise SystemExit("\n".join(problems))
        if jobs and case["job"] not in jobs:
            continue
        if kind and kind != "all" and case["kind"] != kind:
            continue
        if only and case["id"] != only:
            continue
        case["_path"] = str(path)
        out.append(case)
    out.sort(key=lambda c: (JOBS.index(c["job"]), c["id"]))
    return out
