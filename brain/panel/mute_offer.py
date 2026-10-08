"""A rule the scorecard says is wrong about this house, offered for muting.

A producer whose reports are marked Wrong nearly every time is the
household saying the RULE is wrong, and the only answers the Findings tab
had were Wrong one row at a time (which settles one wording) or finding
the scorecard's mute press. Nothing offered it. This reads the scorecard
and files ONE question per producer — "stop raising it?" — whose Yes is
the existing mute (`server._mute_source`).

Never automatic: a mute is the person's decision, so nothing here mutes.
No is remembered, and the same producer is asked again only when its
record has changed materially (at least twice the Wrongs it had when it
was declined). Deterministic and free, so no gate; a producer that
cannot be muted (`cases.UNMUTABLE_SOURCES`, passed in), is already muted,
or is one of the question-asking producers themselves is never asked
about. A pure module: the caller files and records.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.mute_offer")

STORE = Path(os.environ.get("BRAIN_MUTE_OFFERS", "/data/mute-offers.json"))
SOURCE = "mute_offer"
SOURCE_TITLE = "Rule suggestions"

MIN_ENDINGS = 4
MIN_WRONG_SHARE = 0.75
RE_ASK_DAYS = 28
MAX_PER_PASS = 2
MAX_SUBJECTS = 200
# The producers that ask questions of their own are never the subject of one.
SELF_SOURCES = frozenset({SOURCE, "notify_policy"})
TEXT_PREFIX = "Mute suggestion about "


def load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    if not STORE.parent.is_dir():
        return
    if len(data) > MAX_SUBJECTS:
        keep = sorted(data.items(), key=lambda kv: float(
            (kv[1] or {}).get("at") or 0))[-MAX_SUBJECTS:]
        data = dict(keep)
    try:
        atomic_write.write_json(STORE, data)
    except OSError as exc:
        log.info("could not write the mute suggestions: %s", exc)


def qualifies(row: dict) -> bool:
    """Enough endings, mostly Wrong, and the latest one a Wrong — a rule
    somebody last agreed with has changed or been fixed since."""
    total = int(row.get("total") or 0)
    wrong = int(row.get("wrong") or 0)
    return (total >= MIN_ENDINGS and wrong >= MIN_WRONG_SHARE * total
            and row.get("last") == "wrong")


def due(state: dict, row: dict, now: float, live_ts: set[int]) -> bool:
    rec = state.get(row["source"])
    if not isinstance(rec, dict):
        return True
    if rec.get("answer") == "accepted":
        return False
    if isinstance(rec.get("ts"), int) and rec["ts"] in live_ts:
        return False
    if rec.get("answer") == "declined":
        return int(row.get("wrong") or 0) >= 2 * max(1, int(rec.get("wrong") or 0))
    return now - float(rec.get("at") or 0) >= RE_ASK_DAYS * 86400


def plan(scorecard: list[dict], state: dict, now: float, live_ts: set[int],
         muted: set[str], excluded: frozenset | set = frozenset()) -> list[dict]:
    out = []
    for row in scorecard or []:
        source = str(row.get("source") or "")
        if (not source or source in muted or source in excluded
                or source in SELF_SOURCES or not qualifies(row)
                or not due(state, row, now, live_ts)):
            continue
        title = str(row.get("title") or source)
        wrong, total = int(row["wrong"]), int(row["total"])
        out.append({
            "source": source, "wrong": wrong, "total": total,
            "row": {
                # The subject and never the counts, or the store's dedupe
                # would see a new question every time a number moved.
                "text": TEXT_PREFIX + source,
                "claim": (f"{title}: {wrong} of {total} reports were marked "
                          "wrong — stop raising it?"),
                "detail": (f"You have ended {total} reports from this rule and "
                           f"{wrong} of them as wrong, the latest included. "
                           "Yes stops brAIn raising it (and takes what it "
                           "has open off the list); you can start it again "
                           "from the scorecard. No keeps it, and brAIn will "
                           "not ask again unless the record gets much worse."),
                "kind": "question", "severity": "info", "stakes": "low",
                "fixable": False, "source": SOURCE,
                "source_title": SOURCE_TITLE, "entity_id": "", "evidence": [],
            },
        })
        if len(out) >= MAX_PER_PASS:
            break
    return out


def record_asked(state: dict, source: str, ts: int, wrong: int, total: int,
                 now: float) -> dict:
    state[source] = {"ts": int(ts), "at": int(now), "wrong": int(wrong),
                     "total": int(total), "answer": ""}
    return state


def source_for_finding(state: dict, finding: dict) -> str:
    ts = finding.get("ts")
    for source, rec in state.items():
        if isinstance(rec, dict) and rec.get("ts") == ts:
            return source
    text = str(finding.get("text") or "")
    return text[len(TEXT_PREFIX):] if text.startswith(TEXT_PREFIX) else ""
