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
import re
from pathlib import Path

import atomic_write
from textclip import clip

from . import data_dir
from .upstream import product_of, running_at_least, running_for

log = logging.getLogger("brain.devloop")

SOURCE = "devloop_verify"
SOURCE_TITLE = "Development loop"
TEXT_PREFIX = "Is this fixed now: "
# How a question was worded before it was named in words: the report's
# fingerprint, then the release. A row filed that way is still found.
LEGACY_TEXT_PREFIX = "Was this fixed: "
_LEGACY_FP_RE = re.compile(r"^[0-9a-f]{8,64}$")
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


def due(items: dict, version: str, state: dict, live_ts: set[int],
        products: dict | None = None) -> list[dict]:
    """The fixed reports whose fix this house now runs and nobody has been
    asked about under that release. A fix whose release is unknown is
    never asked about: "is x.y.z here" has no answer when x.y.z is."""
    out = []
    for entry in sorted((e for e in items.values() if isinstance(e, dict)),
                        key=lambda e: float(e.get("closed_at") or 0)):
        if (entry.get("verdict") != "fixed"
                or str(entry.get("stream") or "") not in VERIFY_STREAMS
                or not entry.get("fixed_in")
                or running_at_least(running_for(entry, version, products),
                                    entry["fixed_in"]) is not True):
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
    """The question, named by the report's own words and where it was.

    It used to be named by the report's fingerprint with the release as
    its subject — "Was this fixed: 70766c7a7025546b (brAIn 3.8.6)" — which
    is the dedupe key on the screen. The fingerprint stays in the ledger
    (`record_asked`); what a person reads is the report.
    """
    fixed_in = str(entry.get("fixed_in") or "")
    product = product_of(entry)
    what = clip(str(entry.get("what") or ""), 160).rstrip(" .")
    where = clip(str(entry.get("where") or ""), 60).strip()
    place = f" ({where})" if where else ""
    return {
        # Stable per fix: the report's words and the release it was fixed
        # in, so the store's dedupe and the settled ledger let the same
        # report be asked about again only under a NEW fix. The release
        # rides at the end, never as the subject.
        "text": f"{TEXT_PREFIX}{what}{place} — after the {product} "
                f"{fixed_in} update",
        "claim": f"Is this fixed now: “{what}”{place}?",
        "detail": (f"The {product} update installed here was meant to fix "
                   "it. Yes tells whoever fixed it that the fix held on "
                   "this house. No sends what you type back with the "
                   "report and reopens it, so the fix is looked at again. "
                   "Nothing is written to memory either way."),
        "kind": "question", "severity": "info", "stakes": "low",
        "fixable": False, "source": SOURCE, "source_title": SOURCE_TITLE,
        "entity_id": "", "evidence": [],
    }


def record_asked(state: dict, fp: str, ts: int, fixed_in: str, now: float,
                 *, text: str = "") -> dict:
    state[fp] = {"ts": int(ts), "at": int(now), "fixed_in": str(fixed_in),
                 "answer": ""}
    if text:
        state[fp]["text"] = str(text)[:400]
    return state


def fp_for_finding(state: dict, finding: dict) -> str:
    """The report a question row is about: by the row's id, then by its
    words, then — for a row filed the old way — the fingerprint its text
    began with."""
    ts = finding.get("ts")
    text = str(finding.get("text") or "")
    for fp, rec in state.items():
        if isinstance(rec, dict) and rec.get("ts") == ts:
            return fp
    for fp, rec in state.items():
        if isinstance(rec, dict) and text and rec.get("text") == text:
            return fp
    if text.startswith(LEGACY_TEXT_PREFIX):
        token = text[len(LEGACY_TEXT_PREFIX):].split(" ", 1)[0]
        if _LEGACY_FP_RE.match(token):
            return token
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
