"""What the household's thumbs say about a kind of notification, asked once.

The delivery ledger (`deliveries.py`) records what happened to every
message: answered with a button, swiped away, or left. A producer whose
messages are dismissed or swiped away unanswered nearly every time is the
household telling brAIn something its own sentence did not — that this
kind of thing does not deserve an interruption — and nothing read it.

This reads it, weekly and deterministically, and turns it into a QUESTION
rather than a change: "You dismissed 9 of 10 Garden lights alerts within a
minute — move them to the morning list?" Four rules.

**Never automatic.** A pattern in what somebody swipes is evidence, not
consent. Yes appends one clause to the household's notification sentence,
shown on its own line in ⚙ and removable there, and the toast's Undo takes
it back with the card; No is remembered so the same subject is not asked
again. Nothing about delivery changes until somebody says so.

**Never about a critical or safety message.** Those are excluded from the
counting, so a subject can only qualify on its ordinary rows, and the
clause says so in its own words ("unless it is critical"). The dispatcher
carries the other half in code: no clause can make a critical row
`feed_only`.

**A floor, measured on finished sends.** At least `MIN_SENDS` messages that
have an outcome — a message less than a day old may still be answered, and
counting it as ignored would make a subject qualify on its newest sends —
and `MIN_SHARE` of them dismissed or cleared unanswered. "Ignored" is not
counted as a dismissal: an iPhone never reports a swipe, and a message
nobody touched may have been read.

**One question per subject, ever, unless it vanished unanswered.** The
answer is kept in `/data/notify-suggestions.json`; a question that left
the list without one (it aged out) may be asked again after
`RE_ASK_DAYS`, never sooner.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.notify_learn")

STORE = Path(os.environ.get("BRAIN_NOTIFY_SUGGESTIONS",
                            "/data/notify-suggestions.json"))

# The producer the questions are filed under. Its own name, so the
# scorecard counts its Yes and No like any other producer's, and so
# "Stop raising these" on one of its cards is a mute this module reads.
SOURCE = "notify_policy"
SOURCE_TITLE = "Notifications"

MIN_SENDS = 8
MIN_SHARE = 0.8
WINDOW_DAYS = 30
# A clear inside this is a swipe, not a read.
QUICK_S = 60
# How often the pass runs, and how long a question that aged out
# unanswered waits before it may be asked again.
EVERY_S = 7 * 24 * 60 * 60
RE_ASK_DAYS = 28
# At most this many new questions in one pass: a week that turned up
# five is a week to ask about the worst one or two, not a list of five.
MAX_PER_PASS = 2
MAX_SUBJECTS = 200

# Producers whose messages are never a learned clause's business: the
# safety lane, and the Resident's own cases, which are one producer for
# every kind of judgement (`cases.UNMUTABLE_SOURCES`' reason).
EXCLUDED_SOURCES = frozenset({"safety", "resident"})
# Messages that are not about a single ordinary finding.
COUNTED_KINDS = frozenset({"notify", "held"})


def load() -> dict:
    """The answered and asked subjects. `{}` for an unreadable file — which
    asks again rather than never, the direction in which being wrong costs
    one question."""
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
        log.info("could not write the notification suggestions: %s", exc)


def _subject_key(kind: str, subject: str) -> str:
    return f"{kind}:{subject}"


def tally(folded: list[dict], now: float) -> list[dict]:
    """Every subject's finished sends, dismissals and quick clears.

    Entity first: a message about one device is counted against that
    device, and a producer is counted only over messages its qualifying
    devices have not already claimed, so one garden light that is always
    swiped does not make the whole "device unavailable" producer qualify.
    """
    window = now - WINDOW_DAYS * 86400
    rows = []
    for d in folded or []:
        if float(d.get("at") or 0) < window:
            continue
        if d.get("kind") not in COUNTED_KINDS:
            continue
        if d.get("outcome") in ("pending", "failed"):
            continue
        if d.get("severity") == "critical":
            continue
        if len(d.get("ts") or []) != 1:
            continue
        sources = d.get("sources") or []
        if any(s in EXCLUDED_SOURCES for s in sources):
            continue
        rows.append(d)

    def score(group: list[dict]) -> dict:
        dismissed = sum(1 for d in group if d.get("outcome") == "answered"
                        and d.get("action") in ("snooze", "dismiss"))
        cleared = sum(1 for d in group if d.get("outcome") == "cleared")
        quick = sum(1 for d in group if d.get("outcome") in ("cleared",
                                                              "answered")
                    and d.get("action") in ("", "snooze", "dismiss", None)
                    and int(d.get("after_s") or 1e9) <= QUICK_S)
        return {"sends": len(group), "dismissed": dismissed,
                "cleared": cleared, "negative": dismissed + cleared,
                "quick": quick}

    out = []
    by_entity: dict[str, list[dict]] = {}
    for d in rows:
        ents = d.get("entities") or []
        if len(ents) == 1:
            by_entity.setdefault(ents[0], []).append(d)
    claimed: set[str] = set()
    for eid, group in by_entity.items():
        s = score(group)
        if qualifies(s):
            out.append({"kind": "entity", "subject": eid,
                        "sources": sorted({src for d in group
                                           for src in d.get("sources") or []}),
                        **s})
            claimed |= {str(d.get("id")) for d in group}
    by_source: dict[str, list[dict]] = {}
    for d in rows:
        if str(d.get("id")) in claimed:
            continue
        for src in d.get("sources") or []:
            by_source.setdefault(src, []).append(d)
    for src, group in by_source.items():
        s = score(group)
        if qualifies(s):
            out.append({"kind": "producer", "subject": src,
                        "sources": [src], **s})
    out.sort(key=lambda c: (-c["negative"] / max(1, c["sends"]),
                            -c["sends"], c["subject"]))
    return out


def qualifies(s: dict) -> bool:
    return (s["sends"] >= MIN_SENDS
            and s["negative"] >= MIN_SHARE * s["sends"])


def label_for(candidate: dict, names: dict[str, str],
              titles: dict[str, str] | None = None) -> str:
    """What a person calls the subject: the device's own name, or the
    producer's title."""
    subject = candidate["subject"]
    if candidate["kind"] == "entity":
        return str((names or {}).get(subject) or subject)
    return str((titles or {}).get(subject) or subject)


def question(candidate: dict, label: str) -> str:
    """The card's claim. Quick swipes are named when they are most of
    them, because "within a minute" is the half that says it was not
    read rather than read and put off."""
    n, neg = candidate["sends"], candidate["negative"]
    how = "dismissed" if candidate["dismissed"] >= candidate["cleared"] \
        else "swiped away"
    quick = " within a minute" if candidate["quick"] * 2 >= neg else ""
    return (f"You {how} {neg} of {n} {label} alerts{quick} — "
            "move them to the morning list?")


def clause(candidate: dict, label: str) -> str:
    """The sentence Yes appends to the household's policy. It names the
    subject both ways — the name a person reads, the id a model can match —
    and it carries the critical exception in words, beside the code that
    enforces it."""
    if candidate["kind"] == "entity":
        what = f"{label} ({candidate['subject']})"
    else:
        what = f"“{label}” findings ({candidate['subject']})"
    return (f"Notifications about {what} can wait for the morning list, "
            "unless they are critical.")


def due(state: dict, subject_key: str, now: float, live_ts: set[int]) -> bool:
    """Whether this subject may be asked about now."""
    rec = state.get(subject_key)
    if not isinstance(rec, dict):
        return True
    if rec.get("answer") in ("accepted", "declined"):
        return False
    ts = rec.get("ts")
    if isinstance(ts, int) and ts in live_ts:
        return False            # still on the list, waiting for an answer
    return now - float(rec.get("at") or 0) >= RE_ASK_DAYS * 86400


def plan(folded: list[dict], state: dict, now: float, live_ts: set[int],
         names: dict[str, str], titles: dict[str, str] | None = None,
         muted: bool = False) -> list[dict]:
    """The cases this pass would file. Pure: the caller files and records.

    A muted producer files nothing — "Stop raising these" on one of these
    cards is a mute this module reads, because the door it files through
    (`findings_store.add_case`) is not the gate that reads the setting.
    """
    if muted:
        return []
    out = []
    for cand in tally(folded, now):
        key = _subject_key(cand["kind"], cand["subject"])
        if not due(state, key, now, live_ts):
            continue
        label = label_for(cand, names, titles)
        claim = question(cand, label)
        evidence = [{"entity": cand["subject"] if cand["kind"] == "entity"
                     else "", "value": f"{cand['negative']} of {cand['sends']}"
                     " dismissed or cleared unanswered",
                     "when": f"last {WINDOW_DAYS} days"}]
        out.append({
            "key": key,
            "clause": clause(cand, label),
            "subject": label,
            "row": {
                # The store's dedupe key, so it is the SUBJECT and never
                # the counts: "9 of 10" moves every week, and a key that
                # moved with it would file the same question weekly.
                "text": f"Notification suggestion about {key}",
                "claim": claim,
                "detail": (f"Of the last {cand['sends']} notifications about "
                           f"{label}, {cand['dismissed']} were dismissed and "
                           f"{cand['cleared']} swiped away without an answer. "
                           "Yes adds a line to your notification sentence in "
                           "⚙ Settings; critical alerts are never held."),
                "kind": "question",
                "severity": "info",
                "stakes": "low",
                "fixable": False,
                "source": SOURCE,
                "source_title": SOURCE_TITLE,
                "entity_id": cand["subject"] if cand["kind"] == "entity" else "",
                "evidence": [e for e in evidence if e["entity"]] or [],
            },
        })
        if len(out) >= MAX_PER_PASS:
            break
    return out


def record_asked(state: dict, key: str, ts: int, clause_text: str,
                 subject: str, now: float) -> dict:
    state[key] = {"ts": int(ts), "at": int(now), "clause": clause_text,
                  "subject": subject, "answer": ""}
    return state


def key_for_finding(state: dict, finding: dict) -> str:
    """Which subject a filed question was about: by its row id, then by
    the text it was filed under (stable, and the store's own dedupe key)."""
    ts = finding.get("ts")
    for key, rec in state.items():
        if isinstance(rec, dict) and rec.get("ts") == ts:
            return key
    text = str(finding.get("text") or "")
    prefix = "Notification suggestion about "
    return text[len(prefix):] if text.startswith(prefix) else ""


__all__ = ["EVERY_S", "MIN_SENDS", "MIN_SHARE", "SOURCE", "SOURCE_TITLE",
           "STORE", "clause", "due", "key_for_finding", "load", "plan",
           "qualifies", "question", "record_asked", "save", "tally"]
