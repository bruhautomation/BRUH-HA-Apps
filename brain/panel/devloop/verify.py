"""The owner's own verdict on a fix, asked once, after the fix has landed.

A fault verifies itself: its fingerprint stops appearing and the house
says "Held". A request somebody typed into *What do you want to fix?*
(and a thing the chat said it could not do) has no fingerprint to stop:
the cloud closes it "Fixed in brAIn x.y.z", the house installs x.y.z,
and nothing on either side ever learns whether the person who asked got
what they asked for. The `Done when:` line was the bar, and nobody held
the fix to it on the house it came from.

So, once the house runs the release the fix shipped in, ONE question
case is filed on Today — "brAIn x.y.z was meant to fix this. Is it fixed
here?" — and the answer goes back on the issue as the comment the cloud
reads: *The owner confirms this is fixed* closes the loop, *Not fixed on
brAIn x.y.z: <their words>* reopens it for the next run's drain. Three
rules. **Asked once per fix**: a report fixed again under a new release
is asked again, and never otherwise. **Only where the owner can answer**
(`VERIFY_STREAMS`): their own requests and the chat's unmet ones, never
a gap or an idea a model wrote, which reads as a quiz about somebody
else's sentence. **Nothing is written to memory either way** — this is a
fact about brAIn, not the house — and the press settles the question
under its own kind so the scorecard does not count it as a rule being
right or wrong. Pure over what it is handed: the server files and
records, `upstream.owner_answer` carries the answer to the queue.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import atomic_write
from textclip import clip

from . import data_dir
from .upstream import running_at_least

log = logging.getLogger("brain.devloop")

SOURCE = "devloop_verify"
SOURCE_TITLE = "Development loop"
TEXT_PREFIX = "Was this fixed: "
VERIFY_STREAMS = frozenset({"look", "unmet"})
MAX_PER_PASS = 1
MAX_STATE = 300


def state_file() -> Path:
    return data_dir() / "verify.json"


def load() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    if len(data) > MAX_STATE:
        keep = sorted(data.items(), key=lambda kv: float(
            (kv[1] or {}).get("at") or 0))[-MAX_STATE:]
        data = dict(keep)
    try:
        atomic_write.write_json(state_file(), data, mode=0o600)
    except OSError as exc:
        log.info("could not write the verify ledger: %s", exc)


def due(items: dict, version: str, state: dict, live_ts: set[int]) -> list[dict]:
    """The fixed reports whose fix this house now runs and nobody has been
    asked about under that release. A fix whose release is unknown is
    never asked about: "is x.y.z here" has no answer when x.y.z is."""
    out = []
    for entry in sorted((e for e in items.values() if isinstance(e, dict)),
                        key=lambda e: float(e.get("closed_at") or 0)):
        if (entry.get("verdict") != "fixed"
                or str(entry.get("stream") or "") not in VERIFY_STREAMS
                or not entry.get("fixed_in")
                or running_at_least(version, entry["fixed_in"]) is not True):
            continue
        rec = state.get(entry["fp"]) or {}
        if rec.get("fixed_in") == entry["fixed_in"]:
            # Asked under this release already, answered or still open.
            continue
        if int(rec.get("ts") or 0) in live_ts:
            continue
        out.append(entry)
        if len(out) >= MAX_PER_PASS:
            break
    return out


def question_row(entry: dict) -> dict:
    fixed_in = str(entry.get("fixed_in") or "")
    what = clip(str(entry.get("what") or ""), 160)
    return {
        # Stable per fix: the fingerprint and the release, so the store's
        # dedupe and the settled ledger let the same report be asked about
        # again only under a NEW fix.
        "text": f"{TEXT_PREFIX}{entry.get('fp', '')} (brAIn {fixed_in})",
        "claim": f"brAIn {fixed_in} was meant to fix this: “{what}”. "
                 "Is it fixed here?",
        "detail": ("Yes tells whoever fixed it that the fix held on this "
                   "house. No sends what you type back with the report and "
                   "reopens it, so the fix is looked at again. Nothing is "
                   "written to memory either way."),
        "kind": "question", "severity": "info", "stakes": "low",
        "fixable": False, "source": SOURCE, "source_title": SOURCE_TITLE,
        "entity_id": "", "evidence": [],
    }


def record_asked(state: dict, fp: str, ts: int, fixed_in: str, now: float) -> dict:
    state[fp] = {"ts": int(ts), "at": int(now), "fixed_in": str(fixed_in),
                 "answer": ""}
    return state


def fp_for_finding(state: dict, finding: dict) -> str:
    ts = finding.get("ts")
    for fp, rec in state.items():
        if isinstance(rec, dict) and rec.get("ts") == ts:
            return fp
    text = str(finding.get("text") or "")
    if text.startswith(TEXT_PREFIX):
        return text[len(TEXT_PREFIX):].split(" ", 1)[0]
    return ""


def record_answer(state: dict, fp: str, accepted: bool, now: float) -> dict:
    rec = dict(state.get(fp) or {})
    rec["answer"] = "held" if accepted else "not_fixed"
    rec["answered_at"] = int(now)
    state[fp] = rec
    return state


def forget_answer(state: dict, fp: str) -> dict:
    """Undo of either answer: the question is open again and the answer
    forgotten. A comment already posted stands — the next answer is
    posted beside it, which is still the truth in order."""
    rec = dict(state.get(fp) or {})
    if rec:
        rec["answer"] = ""
        rec.pop("answered_at", None)
        state[fp] = rec
    return state
