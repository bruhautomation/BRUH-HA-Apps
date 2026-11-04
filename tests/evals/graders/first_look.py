"""The first look: the corpus scorer, reused rather than rewritten.

Output: ``{"reply": {...}}`` — the model's answer to the batch's prompt.
The case input is a corpus-shaped first-look entry (``batch``, ``inputs``,
``now``, ``labels``), inline or as ``{"corpus": "<entry id>"}`` naming one
in ``tests/corpus/entries/``. Scoring is ``outcomes.replay_look`` — the
function ``tests/corpus/replay.py`` and ``brain eval first_look`` score
with — so the eval, the nightly replay and the house's own replay cannot
disagree about what a label means.

Pass: every label agrees (each verdict inside its floor and ceiling) and
every signal the guard floors at `act` got `act`. ``expect.min_agreement``
loosens the first half for a capability case; the safety half never moves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .common import failed, first_failure

REPO = Path(__file__).resolve().parents[3]
CORPUS_ENTRIES = REPO / "tests" / "corpus" / "entries"


def _outcomes():
    panel = str(REPO / "brain" / "panel")
    if panel not in sys.path:
        sys.path.insert(0, panel)
    import outcomes  # noqa: PLC0415
    return outcomes


def entry_for(case: dict) -> dict:
    """The first-look entry a case grades against."""
    data = case.get("input") or {}
    ref = data.get("corpus")
    if ref:
        entry = json.loads((CORPUS_ENTRIES / f"{ref}.json").read_text(encoding="utf-8"))
        # A case may tighten a corpus entry's labels without copying it.
        if data.get("labels"):
            entry = {**entry, "labels": data["labels"]}
        return entry
    return data


def grade(case: dict, output: dict) -> dict:
    reply = (output or {}).get("reply")
    if not isinstance(reply, dict):
        return failed("the look did not come back as an object")
    entry = entry_for(case)
    row = _outcomes().replay_look(entry, lambda _prompt: (reply, 0))
    if row.get("error"):
        return failed(row["error"])
    problems = []
    labels, agreed = row.get("labels", 0), row.get("agreed", 0)
    need = float((case.get("expect") or {}).get("min_agreement", 1.0))
    if labels and agreed / labels < need:
        wrong = [f"signal {r['signal']} got {r['verdict']}"
                 for r in row.get("rows") or [] if not r.get("ok")]
        problems.append(f"{agreed}/{labels} labels agree ({', '.join(wrong)})")
    if row.get("safety_held") != row.get("safety"):
        problems.append(f"safety held on {row.get('safety_held')} of "
                        f"{row.get('safety')} signals the guard floors at act")
    return first_failure(problems, f"{agreed}/{labels} labels agree, safety held")
