"""Why did you do that? — the question brAIn spends a Claude run on.

Everything brAIn could say about a house was about something being
*wrong*, and then `routines.py` made it able to say what somebody *does*.
Neither can say **why**, and the why is the fact worth having. A house
knows the sprinklers went on at 19:04 on eleven of the last fourteen
evenings. What it does not know is that the lawn is in full sun until six,
or that the water is metered cheaply after seven, or that a dog was ill in
June — and every one of those changes what an automation built on that
observation should do. An automation written from the *when* alone fires at
seven o'clock for ever and is wrong the first week it rains.

So this is the one producer whose output is an **explanation** rather than
a finding, a proposal or a measurement. It reads a manual action brAIn
cannot account for, spends one Claude run looking at what else was true at
the time, and files either a durable fact or a question.

**The selection is the feature, and it is deterministic.** A house
produces tens of manual actions a day and a run costs real money, so *most
of this module is the decision not to ask*. Nothing here asks a model
which events are interesting — that would be a model call per event to
decide whether to make a model call per event. `worth_asking` is
arithmetic over a ledger, it runs before anything is spawned, and an empty
answer costs nothing at all. It is `brief.worth_saying`'s rule, with more
riding on it: a brief nobody needed is a wasted turn, where a question
nobody needed is a wasted turn *and* a line of somebody's attention.

**A question is asked once about a thing, and never again.** The subject
is settled the moment it is asked — before the answer comes back, the way
`_brief_loop` stamps before the run — so a run that crashes cannot leave
the same question to be asked every six hours for ever. The settling is
what makes the budget a budget rather than a rate limit on a loop.

**But a guard that refuses has to change the next attempt**, or it is the
memory size check again. An `unknown` — a run that looked and could not
tell — is the commonest honest outcome on a thin ledger, and settling it
for ever would mean the one subject brAIn most wants to understand is the
one it has permanently stopped thinking about. So an unknown may be asked
again, and what re-opens it is **more evidence, never the clock**: the
subject has to have accrued `RETRY_EVENTS` further occurrences since. A
retry on a timer would ask the identical question over the identical data
and get the identical answer, on somebody else's money.

**The three answers go to three places that already exist.** A run that
worked out the reason files a fact to the memory inbox — never to
`memory.md`, which has one writer. A run that has a *guess* files a
**hypothesis**, which is precisely what that queue is for: a claim brAIn
believes and wants confirmed, capped at three open, expiring in a
fortnight, appearing on the Findings tab as work waiting on a person, and
becoming a plain memory line the moment somebody ticks it. A run that
cannot tell files nothing. No new store, no new tab, no new badge — and in
particular no new notification, because a question about last Tuesday is
not worth a phone lighting up.

**And some questions a house should not ask.** The domain refusal lives in
`manual_ledger.EXCLUDED` and is a refusal rather than a ranking: see its
header. What lives here is the other half of the same judgement — the
prompt is told to answer about the *house* and not about the person, and
never to speculate about anybody's health, their whereabouts, their
household or their habits as habits. *"Why is somebody up at 3am"* has an
answer this software has no business composing.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

log = logging.getLogger("brain.curiosity")

STORE = os.environ.get("BRAIN_CURIOSITY_STORE", "/data/curiosity.json")

# One a day and three a week. These are the whole safety argument against
# the million conversations this feature could be, and they are numbers
# rather than options for the reason the turn caps are gone: asking
# somebody to choose one offers only two settings, low enough to make the
# feature pointless and high enough that nobody should have been asked.
# A question a day is a conversation; four is an interrogation.
MAX_PER_DAY = 1
MAX_PER_WEEK = 3
# And the floor under the budget: however much a house has been doing,
# one pass asks at most once. The checks pass runs every few hours, so
# this is what stops a restart loop turning the daily cap into a burst.
MAX_PER_PASS = 1

# What a run may spend. The wall clock is the budget and the turn cap is
# only the runaway guard behind it, as everywhere else — but this budget
# is also **how long a checks pass can be held open**, because the asking
# is awaited inside one (which is what keeps one Claude invocation in
# flight across the add-on, and what lets `wondered` in the pass summary
# be an honest number rather than a task nobody read the result of). So
# it is a focused single question's budget rather than a whole card's:
# read the weather and the sun at that moment, the history of one entity
# and of things near it, then one JSON object. A pass held open for eight
# minutes would answer "run the checks now" with a refusal for most of
# them.
TIMEOUT_S = 300
MAX_TURNS = 30

# How many further occurrences re-open a subject a run could not explain.
# The unit is occurrences and not days on purpose — what makes the second
# ask different from the first is that there is more to look at, and a
# week in which nothing happened has added nothing.
RETRY_EVENTS = 6
# Entries kept. An index, not a queue: nothing is drained, because a
# subject forgotten is a subject asked about twice.
MAX_ASKED = 400

# The statuses an asking can settle in. `asked` is written before the run
# and is what a crash leaves behind, which is why it is in the set that
# blocks a re-ask: a run that died having spent the money must not be
# indistinguishable from one that never happened.
STATUSES = ("asked", "explained", "guessed", "unknown", "failed")
# Which of those may be asked again, and under what. `explained` and
# `guessed` are done — the fact is filed or the question is on the list.
RETRYABLE = ("unknown", "failed", "asked")


SYSTEM = """You work out why somebody did something in their own home.

You are given ONE thing a person did by hand — an entity, what they
changed it to, and when, with whatever shape brAIn has measured in it.
Your job is to find the *reason*, using the read-only tools you have: the
history of the entity and of related ones, the weather at the time, the
sun, the season, what else was happening in the house, and brAIn's memory
of what is already known about this home.

Answer with ONE JSON object and nothing else:

{
  "confidence": "explained" | "guess" | "unknown",
  "because": "one sentence: the reason, in plain language",
  "fact": "a durable fact about this HOME, or \\"\\"",
  "ask": "one question for the person, or \\"\\"",
  "evidence": ["what you actually read, one short phrase each"]
}

What each confidence means, and the distinction is the whole value here:

- "explained" — you found evidence that accounts for it. Something you
  READ makes the timing or the choice follow. Set "fact".
- "guess" — you have a plausible reason and no evidence that settles it.
  Set "ask" to the question that would settle it. This is a good answer;
  most reasons a person has are not written down anywhere in a house.
- "unknown" — you could not find a reason worth putting to somebody. Set
  neither. This is also a good answer, and far better than a guess
  dressed as an explanation.

Rules that matter more than anything about style:

- NEVER invent a number, a reading or an event. If you did not read it,
  do not cite it. An "explained" with nothing behind it is the worst
  output you can produce, because it goes into this home's memory as a
  fact and nothing will ever question it again.
- "fact" is about the HOUSE and is true next month: "the lawn sprinklers
  are run by hand on summer evenings, after the sun is off the garden" —
  not "the user pressed the sprinkler switch at 19:04". A fact about one
  press is not a fact.
- Do not restate what brAIn already knows. If the memory you were given
  already says it, answer "unknown" with "because" saying so.
- "ask" is ONE short question somebody can answer in a sentence while
  holding a phone. Not a survey, and not a question whose answer you
  could have looked up.
- Say nothing about anybody's health, their whereabouts, who was home,
  their sleep, or their household. If the only reason you can think of is
  about a person rather than about the house, the answer is "unknown".
  This is not a style rule and there is no exception to it.
- "because" is one sentence under 200 characters, no markdown.
"""


# ---------------------------------------------------------------------------
# The store: what has been asked
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    """`{"asked": {subject: entry}, "log": [...]}`, however it failed.

    A failure reads as *nothing has been asked*, which is the expensive
    direction — it costs a repeated question — and is still the right
    one: the alternative is a half-read store read as complete, which
    would silently stop the feature for good the first time a write was
    torn. The budget is what bounds the cost of being wrong here, and it
    is recomputed from the same entries, so a store that cannot be read
    spends at most one run before somebody notices.
    """
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"asked": {}, "log": []}
    if not isinstance(data, dict):
        return {"asked": {}, "log": []}
    asked = data.get("asked")
    log_rows = data.get("log")
    return {
        "asked": {str(k): v for k, v in asked.items() if isinstance(v, dict)}
        if isinstance(asked, dict) else {},
        "log": [r for r in log_rows if isinstance(r, dict)]
        if isinstance(log_rows, list) else [],
    }


def save(payload: dict, path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    asked = payload.get("asked") or {}
    if len(asked) > MAX_ASKED:
        # Oldest first, by when it was asked. A subject dropped from the
        # index can be asked again, which is the right way round: the
        # cost is one repeated question in a year, where dropping the
        # newest would forget what was just asked.
        keep = sorted(asked.items(),
                      key=lambda kv: kv[1].get("asked_at") or 0)[-MAX_ASKED:]
        asked = dict(keep)
    try:
        atomic_write.write_json(target, {
            "asked": asked,
            "log": (payload.get("log") or [])[-MAX_ASKED:],
        })
    except OSError as exc:
        log.warning("could not write the curiosity store: %s", exc)


def _entry(payload: dict, subject: str) -> dict | None:
    entry = (payload.get("asked") or {}).get(subject)
    return entry if isinstance(entry, dict) else None


def may_ask(payload: dict, candidate: dict) -> tuple[bool, str]:
    """Has this subject been asked, and does anything re-open it?

    Returns the reason as well as the verdict, because *"asked in June and
    answered"* and *"asked in June, could not tell, and nothing new has
    happened since"* are different silences, and both of them are read on
    the diagnostics screen by somebody wondering why the feature has
    stopped doing anything.
    """
    entry = _entry(payload, candidate.get("subject") or "")
    if entry is None:
        return True, ""
    status = str(entry.get("status") or "asked")
    if status not in RETRYABLE:
        return False, f"asked already, and {status}"
    seen = int(entry.get("events") or 0)
    now_events = int(candidate.get("events") or 0)
    if now_events - seen < RETRY_EVENTS:
        # A guard that refuses has to change the next attempt. What
        # changes here is the evidence and never the clock: asking again
        # over the same rows would buy the same answer.
        return False, (f"asked already ({status}); {now_events - seen} of "
                       f"{RETRY_EVENTS} further times seen since")
    return True, ""


def spent(payload: dict, now: float | None = None,
          tz=None) -> dict:
    """How much of the budget today and this week have already gone.

    Counted off the same entries that block a re-ask, rather than from a
    counter beside them: a counter is a second answer to "how many have
    been asked", and the one time the two disagree is the one time it
    matters.

    The day is the **local** day, because a budget of one a day whose day
    turns at midnight UTC gives two questions in an evening to half the
    world.
    """
    now = time.time() if now is None else now
    tz = tz or dt.timezone.utc
    today = dt.datetime.fromtimestamp(now, tz).date()
    day = week = 0
    for entry in (payload.get("asked") or {}).values():
        at = entry.get("asked_at")
        if not isinstance(at, (int, float)) or at <= 0:
            continue
        if (now - at) <= 7 * 86400:
            week += 1
        if dt.datetime.fromtimestamp(at, tz).date() == today:
            day += 1
    return {"day": day, "week": week,
            "day_left": max(0, MAX_PER_DAY - day),
            "week_left": max(0, MAX_PER_WEEK - week)}


def budget_reason(payload: dict, now: float | None = None,
                  tz=None) -> str:
    """Why nothing may be asked right now, or `""`.

    A sentence rather than a bool, for `house.py`'s reason: a feature
    that is quiet because it has nothing to ask and one that is quiet
    because it asked this morning look identical from every surface, and
    only one of them is worth waiting for.
    """
    used = spent(payload, now, tz)
    if used["day_left"] <= 0:
        return (f"brAIn has already asked {used['day']} question"
                f"{'' if used['day'] == 1 else 's'} today")
    if used["week_left"] <= 0:
        return (f"brAIn has asked {used['week']} questions this week, which "
                "is its limit")
    return ""


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def worth_asking(candidates: list[dict], payload: dict | None = None,
                 now: float | None = None, tz=None,
                 path: str | None = None) -> list[dict]:
    """Which manual actions are worth a Claude run, best first.

    Deterministic, cheap, and taken BEFORE anything is spawned — the rule
    `brief.worth_saying` carries and the whole reason this feature is not
    a million conversations. Every candidate that survives carries the
    `why` it survived on, because a question brAIn asked for a reason it
    cannot state is one nobody can judge.

    The list is returned whole rather than truncated to the budget: the
    caller takes `MAX_PER_PASS` off the front, and the rest is what the
    diagnostics screen renders as *what brAIn is curious about*. A
    feature whose queue is invisible is one nobody can tell apart from a
    loop that has died.
    """
    payload = load(path) if payload is None else payload
    blocked = budget_reason(payload, now, tz)
    out: list[dict] = []
    for candidate in candidates or []:
        subject = candidate.get("subject") or ""
        if not subject:
            continue
        ok, reason = may_ask(payload, candidate)
        row = dict(candidate)
        if not ok:
            row["skip"] = reason
        elif blocked:
            # Eligible, and not now. Deliberately a different word from
            # the one above: this subject is still going to be asked
            # about, which is what somebody reading the list wants to
            # know.
            row["hold"] = blocked
        else:
            row["why"] = describe(candidate)
        out.append(row)
    # Askable first, then held, then settled — so the front of the list is
    # what will actually happen and the tail is why nothing else will.
    out.sort(key=lambda r: (0 if r.get("why") else
                            1 if r.get("hold") else 2))
    return out


def ready(candidates: list[dict], payload: dict | None = None,
          now: float | None = None, tz=None,
          path: str | None = None) -> list[dict]:
    """The ones that may be asked right now, capped at what a pass may spend."""
    ranked = worth_asking(candidates, payload, now, tz, path)
    return [r for r in ranked if r.get("why")][:MAX_PER_PASS]


def describe(candidate: dict) -> str:
    """Why this one is worth asking about, in a sentence.

    Rendered on the diagnostics screen and handed to the run as its
    framing, so the two cannot disagree about what was interesting.
    """
    name = candidate.get("name") or candidate.get("entity_id") or "something"
    state = candidate.get("state") or ""
    if candidate.get("kind") == "off_pattern":
        return (f"{name} was set to {state} at {candidate.get('at')}, "
                f"which is {candidate.get('away_min')} minutes from the "
                f"{candidate.get('usually_at')} it usually happens at "
                f"across {candidate.get('days')} days")
    return (f"{name} is set to {state} by hand at about "
            f"{candidate.get('at')} on {candidate.get('when_days')}, "
            f"{candidate.get('days')} days out of "
            f"{candidate.get('span_days')}, and nothing explains why")


def frame(candidate: dict, house: str = "", memory: str = "",
          recent: list[dict] | None = None) -> str:
    """The prompt for one asking.

    The house block and the memory excerpt are handed in rather than
    fetched here: this module owns no store and no fetch, and a second
    answer to *what is this house like* is the drift `_CARD_CONTRACT` is
    shared to avoid. The memory is the load-bearing one — without it the
    run happily rediscovers something the document already says, spends a
    question on it, and asks somebody to confirm what they already told
    brAIn once.
    """
    how = ("by voice command" if candidate.get("cause") == "voice"
           else "at a control, signed in")
    lines = [
        "Somebody in this home did something by hand, and brAIn does not "
        + "know why. Work out the reason.",
        "",
        "WHAT THEY DID",
        f"  entity:  {candidate.get('entity_id')}",
        f"  called:  {candidate.get('name')}",
        f"  set to:  {candidate.get('state')}",
        f"  how:     {how}",
    ]
    if candidate.get("kind") == "off_pattern":
        lines += [
            f"  at:      {candidate.get('at')} — and this is the point of "
            + "the question, because it usually happens at "
            + f"{candidate.get('usually_at')}, "
            + f"{candidate.get('away_min')} minutes away, measured over "
            + f"{candidate.get('days')} days",
            "",
            "So the question is not why this happens at all — it happens "
            + "most days. It is what was different about this time.",
        ]
    else:
        lines += [
            f"  at:      about {candidate.get('at')} "
            + f"(give or take {candidate.get('spread_min')} minutes)",
            f"  pattern: {candidate.get('when_days')}, on "
            + f"{candidate.get('days')} of the last "
            + f"{candidate.get('span_days')} days "
            + f"({candidate.get('events')} times in all)",
            "",
            "So the question is why this home does this, and why at that "
            + "time of day rather than another.",
        ]
    if recent:
        lines += ["", "WHEN IT HAPPENED (most recent first)"]
        for row in recent[:8]:
            stamp = dt.datetime.fromtimestamp(
                row.get("ts") or 0, dt.timezone.utc)
            lines.append(f"  {stamp.strftime('%a %d %b %H:%M')} UTC")
    if house:
        lines += ["", "WHAT BRAIN HAS MEASURED ABOUT THIS HOME", house]
    if memory:
        lines += ["",
                  "WHAT BRAIN ALREADY KNOWS (do not repeat any of this "
                  + "back as a discovery)",
                  memory]
    lines += [
        "",
        "Look things up before you answer. The weather and the sun at that "
        + "time of day, the season, the history of this entity and of "
        + "anything near it, and what else in the house moved around then. "
        + "Then answer with the one JSON object.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------

MAX_BECAUSE = 240
MAX_FACT = 400
MAX_ASK = 240
MAX_EVIDENCE = 6
MAX_EVIDENCE_CHARS = 120
CONFIDENCES = ("explained", "guess", "unknown")


def _clean(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


# The answer as the CLI validates it (`--json-schema`); `parse` still
# checks every field, because a schema says the shape is right and not
# that an "explained" came with the fact that makes it one.
SCHEMA = {
    "type": "object",
    "properties": {
        "confidence": {"type": "string", "enum": ["explained", "guess", "unknown"]},
        "because": {"type": "string"},
        "fact": {"type": "string"},
        "ask": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["confidence", "because"],
    "additionalProperties": False,
}


def parse(reply: dict | None) -> dict | None:
    """The reply as a typed answer, or `None` if it is not one.

    `None` is not a failure of the house, it is a failure of the run, and
    the caller records it as such rather than filing anything. The one
    thing this must never do is pass a malformed answer through as an
    `explained`: that writes a sentence into this home's memory that
    nothing will ever question again.
    """
    if not isinstance(reply, dict):
        return None
    confidence = str(reply.get("confidence") or "").strip().lower()
    if confidence not in CONFIDENCES:
        return None
    because = _clean(reply.get("because"), MAX_BECAUSE)
    if not because:
        # An answer with no reason in it is not an answer, whatever it
        # claims about its own confidence.
        return None
    out = {
        "confidence": confidence,
        "because": because,
        "fact": _clean(reply.get("fact"), MAX_FACT),
        "ask": _clean(reply.get("ask"), MAX_ASK),
        "evidence": [
            _clean(e, MAX_EVIDENCE_CHARS)
            for e in (reply.get("evidence") or [])[:MAX_EVIDENCE]
            if _clean(e, MAX_EVIDENCE_CHARS)
        ],
    }
    # A confidence has to come with the thing that makes it actionable, or
    # it is demoted rather than believed. An "explained" with no fact
    # files nothing anywhere, so calling it explained would settle the
    # subject for ever having learned nothing — which is the one outcome
    # worse than not asking.
    if confidence == "explained" and not out["fact"]:
        out["confidence"] = "unknown"
        out["downgraded"] = "explained, but it named no durable fact"
    elif confidence == "guess" and not out["ask"]:
        out["confidence"] = "unknown"
        out["downgraded"] = "a guess, but it named no question to settle it"
    return out


def status_for(answer: dict | None) -> str:
    """The store's word for what an answer was. One mapping, one place."""
    if not answer:
        return "failed"
    return {"explained": "explained", "guess": "guessed",
            "unknown": "unknown"}[answer["confidence"]]


def mark_asked(candidate: dict, now: float | None = None,
               path: str | None = None) -> dict:
    """Settle the subject BEFORE the run, and return the stored entry.

    Before, for `_brief_loop`'s reason: a run that takes four minutes must
    not let the next pass start a second one, and a run that crashes
    having spent the money must not leave the identical question to be
    asked again in six hours for ever. The entry is updated in place when
    the answer arrives.
    """
    now = time.time() if now is None else now
    payload = load(path)
    subject = candidate.get("subject") or ""
    entry = {
        "subject": subject,
        "entity_id": candidate.get("entity_id") or "",
        "name": candidate.get("name") or "",
        "state": candidate.get("state") or "",
        "kind": candidate.get("kind") or "",
        "why": candidate.get("why") or describe(candidate),
        "asked_at": int(now),
        "events": int(candidate.get("events") or 0),
        "status": "asked",
        "because": "",
        "fact": "",
        "ask": "",
        "evidence": [],
        "asks": int(((_entry(payload, subject) or {}).get("asks") or 0)) + 1,
    }
    payload.setdefault("asked", {})[subject] = entry
    save(payload, path)
    return entry


def record_answer(subject: str, answer: dict | None, filed: str = "",
                  error: str = "", now: float | None = None,
                  path: str | None = None) -> dict | None:
    """Write what came back onto the entry `mark_asked` left.

    `filed` says where the answer went — a memory line, a hypothesis, or
    nowhere — because a fact that was composed and a fact that reached
    the inbox are different claims, and the second is the one that made
    the run worth its money.
    """
    now = time.time() if now is None else now
    payload = load(path)
    entry = _entry(payload, subject)
    if entry is None:
        return None
    entry["status"] = status_for(answer)
    entry["answered_at"] = int(now)
    entry["filed"] = filed
    entry["error"] = _clean(error, 200)
    if answer:
        entry.update({
            "confidence": answer["confidence"],
            "because": answer["because"],
            "fact": answer["fact"],
            "ask": answer["ask"],
            "evidence": answer["evidence"],
        })
        if answer.get("downgraded"):
            entry["downgraded"] = answer["downgraded"]
    payload["asked"][subject] = entry
    # The log is what the screen renders: a settled entry says only that
    # a subject is done, where this says what brAIn worked out and when.
    payload.setdefault("log", []).append({
        "ts": int(now),
        "subject": subject,
        "name": entry.get("name") or "",
        "status": entry["status"],
        "because": entry.get("because") or "",
        "filed": filed,
        "error": entry.get("error") or "",
    })
    save(payload, path)
    return entry


def recent(payload: dict | None = None, limit: int = 12,
           path: str | None = None) -> list[dict]:
    """What brAIn has worked out lately, newest first."""
    payload = load(path) if payload is None else payload
    rows = sorted(payload.get("log") or [],
                  key=lambda r: r.get("ts") or 0, reverse=True)
    return rows[:limit]


def counts(payload: dict | None = None, path: str | None = None) -> dict:
    """One number per status. What tells a feature that is working and
    finding nothing apart from one that has been failing since March."""
    payload = load(path) if payload is None else payload
    out = {s: 0 for s in STATUSES}
    for entry in (payload.get("asked") or {}).values():
        status = str(entry.get("status") or "asked")
        out[status] = out.get(status, 0) + 1
    return out


__all__ = [
    "CONFIDENCES", "MAX_ASKED", "MAX_PER_DAY", "MAX_PER_PASS",
    "MAX_PER_WEEK", "MAX_TURNS", "RETRYABLE", "RETRY_EVENTS", "STATUSES",
    "STORE", "SYSTEM", "TIMEOUT_S", "budget_reason", "counts", "describe",
    "frame", "load", "mark_asked", "may_ask", "parse", "ready", "recent",
    "record_answer", "save", "spent", "status_for", "worth_asking",
]
