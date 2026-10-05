"""Cases — one object over four stores, and three ways to end one.

brAIn kept four lists of "something is waiting on you" and gave each its
own tab, its own badge and its own vocabulary: a **finding** is what is
broken, a **proposal** is what could be better, a **hypothesis** is what
brAIn might have wrong, a **chore** is what you agreed to do. Each split
is real and each was argued for. Together they are four inboxes for one
job — a person deciding something — and thirteen verbs between them, which
is a row nobody can hold in their head.

A case is that one job, named once. It is a **read model** and not a fifth
store: every field is derived from the row that already exists in one of
the four, nothing is copied to disk, and there is exactly one thing here
that is written down (a snooze the store underneath cannot hold, below).
That is the whole safety argument for doing this in one release — a second
copy of a finding would be a second answer to "is this still open", and
the one time the two disagree is the one time somebody is looking.

**The id says which store, because two id spaces must not collide.** A
finding's id is a second, a to-do item's is a millisecond, a proposal's is
a millisecond and a hypothesis's is a second, so a bare integer is read as
whichever store is asked first and is right about three houses in four.
`f:`/`p:`/`h:`/`t:` is `todo.py`'s rule, for `todo.py`'s reason.

**Three endings, and only two of them end anything.** *Do it* is yes —
the chore is done, the guess confirmed, the suggestion accepted, and a
problem becomes work on the list rather than a claim that it is finished.
*Wrong, because…* is the correction path, unchanged and still the half
that teaches. *Not now* takes nothing away: the agent picks when the case
comes back and the card says when, which is the only honest form of a
snooze — four sub-choices on a row is asking somebody to do arithmetic
about a battery.

**Do it on a problem is `＋ To-do`, and that is deliberate.** The obvious
mapping is the tab's own *I've fixed it*, and it writes "Fixed by the
homeowner on <date>" into memory — which is a lie at the moment the button
is pressed, because pressing it is agreeing the report is real and not
reporting that the battery is in. `todo_store`'s own docstring is about
exactly this sentence. So *Do it* settles the key as `accepted` (the
scorecard counts it confirmed, which is right: agreeing to do something is
agreeing it was real), puts the work on the list, and writes no memory
line — and the memory line is written when the chore is ticked off, which
is a `chore` case's own *Do it*, and which re-settles the same key as
`fixed`. One press per claim, each claim true when it is made. "I had
already done it" is a different claim and is in `overflow`.

**Nothing here performs an ending.** `end` takes `hooks`, a small object
of callables the server passes in, and every one of them is the door that
surface already used — `_end_finding`, `h_finding_todo`'s creation step,
the hypothesis and proposal settlers, the to-do completion. A second
implementation of an ending would be the same press teaching brAIn two
different things depending on which screen it was given on, which is
`_end_finding`'s whole reason for existing. This module never imports
`server`, for `reports.py`'s reason: it has to be readable and testable
with the panel down.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, NamedTuple

import answers as answers_mod
import atomic_write
import findings_store
import hypotheses
import proposals
import todo_store

# The five kinds, read off the store that writes the word onto disk rather
# than restated here: a vocabulary this module admitted and the store
# refused would be a case the feed renders and nothing can file.
KINDS = findings_store.CASE_KINDS
STAKES = findings_store.STAKES

# Which store a case came out of, and the one letter that says so.
STORES = ("findings", "proposals", "hypotheses", "todo")
PREFIXES = {"findings": "f", "proposals": "p", "hypotheses": "h", "todo": "t"}
_BY_PREFIX = {v: k for k, v in PREFIXES.items()}

# What a case can be in. Four words and not the design page's six, because
# two of those — `dismissed` and `wrong` — are *endings*, and an ended case
# leaves the feed rather than sitting in it under a new name. That is the
# Findings tab's own rule ("a finding leaves the list when a person ends
# it, and then it is gone") and it is the reason there is no archive here
# either: memory is the record of a decision.
STATUSES = ("open", "watching", "acting", "done")
# What the feed shows. A finished chore is a record, not a decision, so it
# is reachable by asking for it and absent from everything that counts.
LIVE_STATUSES = ("open", "watching", "acting")

# What the FEED lists. A chore is out of it on purpose: the Findings feed
# is the list of decisions waiting on a person, and a chore is a decision
# already made — the press that made it was "yes, that is real, I will do
# it", and the To-do tab is where that work lives, with its own badge.
# Rendered beside real findings, an accepted battery came back as a card
# reading *Broken · Device check · battery is low* over *Done · Remove*,
# which is a finding with no way onto the to-do list — the complaint, in
# the words it arrived in: "I don't see ways to move stuff to the to do
# list?" A chore is still a case (`get` answers for it, the To-do tab's
# endings ride `CASE_HOOKS`), so asking for `kinds=KINDS` still lists it.
FEED_KINDS = tuple(k for k in KINDS if k != "chore")

# Which STORES the feed lists. A proposal is out of it for the chore's
# reason one store over: it has a tab of its own with a badge of its own,
# and it was answerable in both places — counted by the Findings badge
# and the Proposals badge at once, two badges about one decision. The
# Proposals tab is the surface that can carry a proposal whole: the
# replay and the before-and-after, a playbook's targets by name, a set of
# scenes drawn as swatches, a trial's week and its grade, Undo on an
# accepted automation and the end of a trial — and the feed's card could
# carry only the first two, sending a playbook or a scene to the tab for
# its evidence anyway. A proposal is still a case (`get` answers for it,
# its endings ride `CASE_HOOKS` for a page served before the change), and
# the Resident's "already said" prompt asks for every store by name.
FEED_STORES = tuple(s for s in STORES if s != "proposals")

VERBS = ("do", "not_now", "wrong")
# And the statuses a verb may be given on. A run is changing the house in
# `acting`, so an ending there would delete the row the fixer is still
# writing to and settle a question nobody has the answer to yet — which is
# why the Findings tab renders no buttons in `fixing` either. A finished
# chore is a record and has been answered once already; its one verb is
# *Put it back*, which is in `overflow`.
ENDABLE_STATUSES = ("open", "watching")

# How a finding's own status reads as a case's. `held` is "something
# looked and did not think it was worth your evening", which is not
# waiting on anybody and is exactly what `watching` means here;
# `planning` and `fixing` are runs in flight, which is `acting`.
#
# `triaging` is deliberately absent, and a row in it is **not a case at
# all**: nothing has looked at it yet, the drain is a minute away, and a
# case is by definition something brAIn is prepared to say. That is also
# what makes `watching` unambiguous on this side of the wall — a watching
# finding is a held one, so `overflow` can offer the press that elevates
# it without having to ask which of two store words it came from.
_FINDING_STATUS = {
    "open": "open", "needs_you": "open", "failed": "open", "planned": "open",
    "fixed": "open", "planning": "acting", "fixing": "acting",
    "held": "watching",
}
# ...and a proposal's. A trial is brAIn watching an automation for a week,
# which is the same claim `watching` makes about a held finding: something
# is happening and nothing is waiting on you yet.
_PROPOSAL_STATUS = {"proposed": "open", "trialling": "watching"}

# A severity is how bad, and stakes are how much it matters — the same
# question asked in the two vocabularies brAIn already had. One derivation,
# here, so the feed's sort and the snooze it earns cannot disagree.
_STAKES_BY_SEVERITY = {"critical": "high", "serious": "high",
                       "warning": "medium", "info": "low"}

# Where each case sits on the feed, top first. Stakes decide it for
# everything but a QUESTION, which has a band of its own just under the
# high-stakes problems: a guess is two taps against a problem's
# read-and-decide, and burying the cheap decisions under every warning —
# which `low` stakes did, and every millisecond-stamped opportunity beside
# them did as well — is how a queue capped at three sat unanswered for a
# fortnight and expired. A freezing pipe still outranks it; a warning
# does not.
_BAND = {"high": 3, "question": 2, "medium": 1, "low": 0}

# ---------------------------------------------------------------------------
# Not now
# ---------------------------------------------------------------------------
#
# How long "not now" buys, keyed on how much the case matters — the more it
# matters, the sooner it comes back. A person who defers a freezing pipe
# means "not this minute"; one who defers a tidy-up means "not this week".
SNOOZE_BY_STAKES = {"high": 86400, "medium": 3 * 86400, "low": 7 * 86400}
# A chore is a week whatever it is about, because that is what "I will get
# to it" means and a chore's stakes are the finding's, which was already
# answered when it was accepted.
CHORE_SNOOZE_S = 7 * 86400
# Whatever else the arithmetic says, a press buys a day of quiet. Without
# it a question already past its expiry, or a case whose own numbers put
# the answer in the past, would come straight back — which reads as the
# button doing nothing, and is how a control stops being pressed.
MIN_SNOOZE_S = 86400

# The snoozes no store underneath can hold. A finding carries its own
# `snoozed_until` field and uses it; a proposal, a hypothesis and a to-do
# item have nowhere to put one, and giving each of those three a column
# for a press this module owns would be three migrations for one feature.
SNOOZE_FILE = Path(os.environ.get("BRAIN_CASES_SNOOZE_FILE",
                                  "/data/cases-snooze.json"))
# Far more than anybody defers at once. Entries whose time has come are
# dropped on every write, so this is a ceiling on a pathological day
# rather than a working limit.
MAX_SNOOZED = 400


class Hooks(NamedTuple):
    """The endings, as the server already performs them.

    Every one is optional and an absent one is a **refusal**, not a silent
    success: `end` answers None and says which hook was missing, because a
    press that appeared to work and changed nothing is the one outcome
    with no way back. The server passes all six.

    Two call shapes, and which one a hook gets is in `_ENDINGS`: the three
    that settle something take `(key, verb, note)`, because the verb is
    the store's own word for the ending and the note is the homeowner's
    reason; the three that do one thing take `(key,)`.
    """

    end_finding: Callable[..., object] | None = None
    finding_todo: Callable[..., object] | None = None
    hypothesis: Callable[..., object] | None = None
    proposal: Callable[..., object] | None = None
    todo_done: Callable[..., object] | None = None
    todo_drop: Callable[..., object] | None = None


# (kind, verb) → (the hook, the store's own word for it).
#
# `not_now` is deliberately absent: it is the one ending that ends nothing,
# so it has no hook and no word — it is a snooze, and the snooze is this
# module's own (see `_snooze_until`).
_ENDINGS: dict[tuple[str, str], tuple[str, str]] = {
    # A problem: yes, that is real and I will do it — which creates the
    # chore and settles the key as `accepted`. See the module docstring
    # for why this is not the tab's "I've fixed it".
    ("problem", "do"): ("finding_todo", ""),
    ("problem", "wrong"): ("end_finding", "wrong"),
    # A change is news to read, and the only honest answer to news brAIn
    # made itself is "I have read it" — the tab's Got it.
    ("change", "do"): ("end_finding", "ack"),
    ("change", "wrong"): ("end_finding", "wrong"),
    ("opportunity", "do"): ("proposal", "accept"),
    ("opportunity", "wrong"): ("proposal", "decline"),
    ("question", "do"): ("hypothesis", "confirm"),
    ("question", "wrong"): ("hypothesis", "reject"),
    ("chore", "do"): ("todo_done", ""),
    ("chore", "wrong"): ("todo_drop", ""),
}

# The same table for a kind that lives in a store other than its usual
# one, which is checked FIRST. The Resident files opportunities and
# questions into the FINDINGS store — an investigation's case is a row
# there whatever its kind — and routing them by kind alone sent "Make the
# change", "Yes" and "No" to the proposal and hypothesis hooks with a
# finding's ts: every press failed with "already answered" (or acted on a
# guess that happened to share the number), and the only answer that
# worked was Dismiss.
_STORE_ENDINGS: dict[tuple[str, str, str], tuple[str, str]] = {
    # An improvement brAIn noticed: yes, I will do it — onto the list,
    # exactly as a problem's *Add to list*.
    ("findings", "opportunity", "do"): ("finding_todo", ""),
    ("findings", "opportunity", "wrong"): ("end_finding", "wrong"),
    # A question only the homeowner can answer: Yes files what the case
    # said it would teach (its `memory_hint`), No is a correction.
    ("findings", "question", "do"): ("end_finding", "confirm"),
    ("findings", "question", "wrong"): ("end_finding", "wrong"),
}


# Producers that are not a RULE, so "Stop raising these" means nothing
# about them. The Resident files whatever an investigation found — one
# source for every kind of judgement — so muting it deleted every open
# Resident case on the list, a live safety case included, while nothing
# on its path ever read the mute and new cases went on arriving. The
# safety lane is the rule that reports leaks, smoke and gas; that is not
# a rule this panel offers a press to silence. What a person means on one
# of these is "not this kind of thing", which is what *Not a problem* and
# its reason box already teach, case by case.
# `security` is the tripwire (`security.py`): a producer nobody should be
# able to silence with one press, any more than the safety lane.
UNMUTABLE_SOURCES = frozenset({"resident", "safety", "security"})


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def case_id(store: str, key) -> str:
    """`f:1737000000` and friends. Refuses a store it does not know rather
    than minting an id nothing can split."""
    if store not in PREFIXES:
        raise ValueError(f"unknown case store: {store}")
    return f"{PREFIXES[store]}:{int(key)}"


def split_id(value: str) -> tuple[str, int] | None:
    """`("findings", 1737000000)`, or None for anything that is not one.

    None rather than a raise because this is handed whatever arrived on
    the wire, and a malformed id is a 404 rather than a 500.
    """
    prefix, _, key = str(value or "").partition(":")
    store = _BY_PREFIX.get(prefix)
    if store is None:
        return None
    try:
        return store, int(key)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The snoozes this module owns
# ---------------------------------------------------------------------------

def _read_snoozes() -> dict[str, int]:
    """`{case id: epoch}`. Every way of failing to read answers "nothing is
    snoozed", which shows a case somebody deferred — the direction in
    which being wrong costs one extra card rather than hiding a problem."""
    try:
        data = json.loads(SNOOZE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("snoozed") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    out: dict[str, int] = {}
    for key, until in rows.items():
        if split_id(key) is None:
            continue
        try:
            out[str(key)] = int(until)
        except (TypeError, ValueError):
            continue
    return out


def _write_snoozes(rows: dict[str, int], now: float) -> None:
    """Keep what has not come round yet, and nothing else.

    Pruned on write rather than on read: a snooze whose time has passed
    has done its whole job, and an entry nobody will ever consult again is
    the sort of thing a store accumulates for years.
    """
    live = {k: v for k, v in rows.items() if v > now}
    if len(live) > MAX_SNOOZED:
        live = dict(sorted(live.items(), key=lambda kv: kv[1])[-MAX_SNOOZED:])
    SNOOZE_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_json(SNOOZE_FILE, {"snoozed": live})


def _snooze_until(case: dict, now: float) -> int:
    """When a "not now" on this case should bring it back.

    Per kind, in that kind's own terms, which is the whole reason the
    agent picks rather than the person: a chore's is a week, and
    everything else is keyed on how much it matters — a question
    included. A question used to go quiet until its own fourteen-day
    expiry, which is the queue retiring it rather than bringing it back:
    the button said "brAIn brings it back later", the toast said "back in
    13 days", and on the thirteenth day it was gone. It is the stakes
    table now and the queue keeps it alive across the snooze
    (`hypotheses.snooze` restarts its clock when it returns).
    """
    kind = case.get("kind")
    if kind == "chore":
        return int(now + CHORE_SNOOZE_S)
    stakes = case.get("stakes") if case.get("stakes") in STAKES else "medium"
    return int(now + max(SNOOZE_BY_STAKES[stakes], MIN_SNOOZE_S))


def snooze_until(case: dict, now: float | None = None) -> int:
    """`_snooze_until`, for the one other door a Dismiss arrives through.

    A notification's Dismiss and the feed's are one press, so they buy one
    length of quiet: a request from Home Assistant that does not name its
    own hours is given this rather than a flat day (`finding_requests`
    leaves `hours` empty for exactly that). Repairs' "Remind me tomorrow"
    names 24 and keeps it, because that one says so on the button.
    """
    return _snooze_until(case, time.time() if now is None else now)


# ---------------------------------------------------------------------------
# The read model
# ---------------------------------------------------------------------------

def _seconds(ts) -> int:
    """A store's stamp as epoch SECONDS.

    A finding's and a guess's ts are seconds, a proposal's and a to-do
    item's id are milliseconds, and sorting the feed on the raw number put
    every proposal above every question whatever their ages — a
    millisecond stamp is a thousand times larger than any second one. A
    seconds epoch passes 1e11 in the year 5138, so anything above it is a
    millisecond one.
    """
    try:
        value = float(ts or 0)
    except (TypeError, ValueError):
        return 0
    return int(value / 1000) if value > 1e11 else int(value)


def _stakes_of(row: dict) -> str:
    """What the row says, or what its severity implies. A Resident case
    states its own stakes, because the run that wrote it weighed them;
    everything else is a severity a rule chose, read through one table."""
    if row.get("stakes") in STAKES:
        return row["stakes"]
    return _STAKES_BY_SEVERITY.get(row.get("severity") or "", "medium")


def _base(store: str, key, *, kind: str, claim: str, detail: str,
          status: str, ts: int, source: str = "", source_title: str = "",
          ) -> dict:
    """The keys every case has, whichever store it came from."""
    return {
        "id": case_id(store, key),
        "kind": kind,
        "claim": claim,
        "detail": detail,
        "confidence": None,
        "stakes": "medium",
        "evidence": [],
        "actions": [],
        "status": status,
        "source": source,
        "source_title": source_title,
        "ts": int(ts or 0),
        # When it was raised, in seconds whatever the store counts in —
        # what the feed sorts on, because `ts` is each store's own id and
        # two of the four count in milliseconds.
        "created_at": _seconds(ts),
        "origin": {"store": store, "key": key},
        "memory_hint": "",
        "investigation": None,
        "ended": None,
        # The five the four stores hold that a feed cannot render without.
        # `severity` is what the notifier already keys on and what sorts
        # the feed; `entity_id` is what a card links to; `fix` is the one
        # sentence a person acts on; `fixable` says WHOSE sentence it is,
        # and the card has nothing else to head it with; `snoozed_until`
        # is what lets the card say when it comes back.
        "severity": "warning",
        "entity_id": "",
        "fix": "",
        # Before this key existed the feed headed every `fix` "You'd need
        # to" — so a row brAIn could act on told somebody to do it by hand
        # while the same card's ⋯ offered to work the change out. False
        # is the safe default rather than merely the common one: a card
        # that says brAIn would do it, on a store where no press will, is
        # a promise nothing can keep.
        "fixable": False,
        "snoozed_until": 0,
    }


def _from_finding(row: dict, snoozes: dict[str, int]) -> dict:
    """A finding, as a case.

    ``snoozes`` is unused and the signature keeps it anyway, because the
    four builders are called the same way from one place and a fifth store
    arriving with its own shape is the moment to notice that this one
    already had somewhere to put a snooze.

    A `fixed` row is a **change** whatever else it says — brAIn altered
    somebody's house and that is news to read, which is a different object
    from a problem however the row was labelled when it was filed. Every
    other row takes the `kind` the Resident wrote on it, and `problem`
    when nothing did, which is what a check's row has always been.
    """
    status = row.get("status") or "open"
    kind = "change" if status == "fixed" else (
        row["kind"] if row.get("kind") in KINDS else "problem")
    case = _base(
        "findings", row["ts"],
        kind=kind,
        claim=row.get("claim") or row.get("text") or "",
        detail=row.get("detail") or "",
        status=_FINDING_STATUS.get(status, "open"),
        ts=row.get("ts") or 0,
        source=row.get("source") or "",
        source_title=row.get("source_title") or "",
    )
    case.update({
        "stakes": _stakes_of(row),
        "severity": row.get("severity") or "warning",
        "entity_id": row.get("entity_id") or "",
        "fix": row.get("fix") or "",
        # Whose sentence the fix is, so the card can say so.
        "fix_by": row.get("fix_by") or "",
        # The store's own status word, beside the case's four. `planned`,
        # `planning` and `fixing` are three different screens — a plan
        # waiting for consent, a read-only run, a run changing the house
        # — and the case status folds two of them into `acting`, so the
        # answers are read off this and the card renders Apply/Cancel
        # from it. It is why the feed used to show *Do it* over a plan.
        "finding_status": status,
        "plan": dict(row.get("plan") or {}),
        "fix_started": float(row.get("fix_started") or 0),
        "fix_ended": float(row.get("fix_ended") or 0),
        "fix_files": int(row.get("fix_files") or 0),
        "fix_calls": int(row.get("fix_calls") or 0),
        # What the fix run said it did, and the list of what it changed —
        # the fixer's own report (`_run_fix`), and on a `needs_you` row the
        # one sentence that matters most: why brAIn concluded a person has
        # to do this, and how. Dropped here, the feed showed a fixed card
        # as two counts under the stale "How brAIn would fix it", and a
        # failed or needs-you one as an ordinary problem whose first button
        # bought another plan run to reach the same conclusion.
        "result": str(row.get("result") or ""),
        "changed": [str(c) for c in row.get("changed") or []
                    if isinstance(c, str)],
        "checked_at": int(row.get("checked_at") or 0),
        "triage": dict(row.get("triage") or {}),
        # The store's own rule, not a second reading of it: absent means
        # fixable and only an explicit false means hands are required, so
        # a row written before the key existed keeps the answer
        # `findings_store` would give it. `_base` defaults the other way
        # because no other store makes that promise.
        "fixable": row.get("fixable", True) is not False,
        "evidence": list(row.get("evidence") or []),
        "actions": list(row.get("actions") or []),
        "memory_hint": row.get("memory_hint") or "",
        "snoozed_until": int(row.get("snoozed_until") or 0),
    })
    if isinstance(row.get("confidence"), (int, float)):
        case["confidence"] = row["confidence"]
    # The run that can be opened as a record. A Resident case names its
    # investigation; a triaged row names the conversation that judged it,
    # which is the same offer — "here is what looked at this" — and the
    # panel already opens both through the same reader.
    run_id = ((row.get("investigation") or {}).get("run_id")
              or (row.get("triage") or {}).get("run_id") or "")
    if run_id:
        case["investigation"] = {"run_id": run_id}
    return case


def _from_proposal(row: dict, snoozes: dict[str, int]) -> dict:
    """A proposal, as a case.

    Its `actions` stay EMPTY. A proposal's whole content is the change and
    *Do it* performs it, so composing an action row here would be this
    module asserting a shape — "edit a file", "write an automation" — that
    nothing in the store wrote down, about somebody's house. The kind and
    the origin are what tell a reader what yes means. The feed is not one
    of those readers any more (`FEED_STORES`); this is what `get` and the
    Resident's "already said" list are handed.
    """
    case = _base(
        "proposals", row.get("ts") or 0,
        kind="opportunity",
        claim=row.get("title") or "",
        detail=row.get("why") or "",
        status=_PROPOSAL_STATUS.get(row.get("status") or "", "open"),
        ts=row.get("ts") or 0,
        source=row.get("source") or "",
        # A proposal carries no producer title, and what sort of change it
        # is — a routine, a playbook, a condition, a scene — is the
        # closest thing it has to one.
        source_title=row.get("kind") or "",
    )
    case["snoozed_until"] = int(snoozes.get(case["id"], 0))
    # An opportunity is never a fault, so its severity is the one the
    # notifier already treats as "a card will do".
    case["severity"] = "info"
    case["stakes"] = "low"
    # No evidence rides here any more. It did while the feed rendered
    # proposals (the replay, the trial's grade, the composed case); the
    # Proposals tab is the one surface for them now and carries all of it
    # off the store row, so a copy on a case nothing renders would be a
    # second shape to keep true.
    return case


def _from_hypothesis(row: dict, snoozes: dict[str, int]) -> dict:
    """An open hypothesis, as a case. Only `open` ones are ever built:
    confirmed ones live in the memory document and rejected ones are a
    dead end a prompt reads, and neither is waiting on anybody."""
    case = _base(
        "hypotheses", row.get("ts") or 0,
        kind="question",
        claim=row.get("text") or "",
        detail="",
        status="open",
        ts=row.get("ts") or 0,
        # The queue is its own producer. Nothing grades it — a guess
        # confirmed becomes a memory line and a rejected one a dead end —
        # so this names where the case came from and nothing more.
        source="hypothesis",
        source_title=row.get("topic") or "",
    )
    # The queue carries its own snooze now (`hypotheses.snooze`), which is
    # the field this reads first; the sidecar is the floor for a guess
    # dismissed by a release before the queue could hold one.
    case["snoozed_until"] = max(int(row.get("snoozed_until") or 0),
                                int(snoozes.get(case["id"], 0)))
    case["severity"] = "info"
    case["stakes"] = "low"
    return case


def _from_todo(item: dict, snoozes: dict[str, int]) -> dict:
    """A to-do item, as a case. A finished one carries its ending, which
    is the one place `ended` is ever set by a read: every other ending
    deletes the row it was given on."""
    case = _base(
        "todo", item.get("id") or 0,
        kind="chore",
        claim=item.get("text") or "",
        detail=item.get("detail") or "",
        status="done" if item.get("status") == "done" else "open",
        ts=int(item.get("added_at") or 0),
        source=item.get("source") or "",
        source_title=item.get("source_title") or "",
    )
    case.update({
        "stakes": _stakes_of(item),
        "severity": item.get("severity") or "warning",
        "entity_id": item.get("entity_id") or "",
        "fix": item.get("fix") or "",
        "snoozed_until": int(snoozes.get(case["id"], 0)),
    })
    if item.get("status") == "done":
        case["ended"] = {"verb": "do", "when": int(item.get("done_at") or 0)}
    if item.get("run_id"):
        case["investigation"] = {"run_id": item["run_id"]}
    return case


def _all_cases(snoozes: dict[str, int], stores=STORES) -> list[dict]:
    """Every case the named stores currently hold, unfiltered and unsorted.

    A store nobody asked for is not read at all: the feed is asked for on
    every visit and a proposals load it would then throw away is a read
    nobody wanted."""
    stores = set(stores)
    out: list[dict] = []
    if "findings" in stores:
        out += [_from_finding(row, snoozes) for row in findings_store.list_all()
                if row.get("text") and row.get("status") in _FINDING_STATUS]
    if "proposals" in stores:
        out += [_from_proposal(row, snoozes) for row in proposals.listing()
                if row.get("status") in proposals.OPEN_STATUSES]
    if "hypotheses" in stores:
        out += [_from_hypothesis(row, snoozes)
                for row in hypotheses.list_all("open")]
    if "todo" in stores:
        listed = todo_store.listing()
        out += [_from_todo(item, snoozes) for item in listed["items"]]
        out += [_from_todo(item, snoozes) for item in listed["done"]]
    return out


def _band(case: dict) -> int:
    """Which band of the feed a case sits in (`_BAND`)."""
    if case.get("kind") == "question":
        return _BAND["question"]
    return _BAND.get(case.get("stakes") or "medium", _BAND["medium"])


def _sort(cases: list[dict]) -> list[dict]:
    """By band, then newest. The feed is read top-down on a phone, so the
    two questions it answers in that order are "what matters most" and
    "what has just happened" — with the cheap decisions, the guesses,
    kept near the top rather than under every warning (`_BAND`).

    Newest is `created_at`, never `ts`: two of the four stores count in
    milliseconds, and a raw-ts sort put every proposal above every
    question whatever their ages."""
    return sorted(cases, key=lambda c: (_band(c), c.get("created_at") or 0),
                  reverse=True)


def list_cases(status: str | None = None, kinds=None,
               now: float | None = None, stores=None) -> list[dict]:
    """The feed.

    ``status`` is one of `STATUSES`, the sentinel ``"snoozed"``, or None
    for everything still live — which is `findings_store.list_all`'s own
    arrangement and means the same thing: a finished chore is a record
    rather than a decision, so asking for nothing in particular does not
    hand you one.

    The feed itself asks for ``"open"``, because that is the set a person
    can do something about; ``None`` is what a Looked-at filter and a
    diagnostics count read, and it carries the held and the in-flight
    cases beside the answerable ones.

    A snoozed case is **hidden until its time**, never dropped: "not now"
    is not a decision, so the case has to come back, and the store rows it
    is built from are untouched throughout.

    ``kinds`` defaults to `FEED_KINDS`, which is every kind but a chore: a
    chore is work already accepted and lives on the To-do tab, so a caller
    that wants one (a diagnostics count, a prompt saying what the house
    already knows about) asks for it by name — `kinds=KINDS`.

    ``stores`` defaults to `FEED_STORES`, every store but the proposals,
    which live on their own tab; a caller that wants them names them —
    `stores=STORES`.
    """
    now = time.time() if now is None else now
    snoozes = _read_snoozes()
    cases = _all_cases(snoozes, stores if stores else FEED_STORES)
    wanted = set(kinds) if kinds else set(FEED_KINDS)
    out = []
    for case in cases:
        if wanted is not None and case["kind"] not in wanted:
            continue
        asleep = case["snoozed_until"] > now
        if status == "snoozed":
            if not asleep:
                continue
        elif asleep:
            continue
        elif status is None:
            if case["status"] not in LIVE_STATUSES:
                continue
        elif case["status"] != status:
            continue
        out.append(case)
    return _sort(out)


def on_feed(case: dict) -> bool:
    """Whether the feed renders this case.

    Everything `list_cases` answers for, less one thing: a finding triage
    HELD. That is `watching` on this side of the wall, and it is a row
    brAIn looked at and decided not to bother anybody with — which is the
    Looked-at filter's whole list and the one place it belongs. On the
    feed it sat under "Needs you" beside the rows that do, with a press
    that put it on the list it was already on: the card stayed where it
    was and grew the ordinary row, so "Show it anyway" read as doing
    nothing. A trial is `watching` too and stays, being a thing brAIn is
    doing that somebody asked for and can end.
    """
    return not ((case.get("origin") or {}).get("store") == "findings"
                and case.get("status") == "watching")


def open_count(now: float | None = None) -> int:
    """What a badge counts: cases waiting on a person, right now.

    `watching` and `acting` are out of it for `UNSETTLED_STATUSES`' reason
    — a run in flight and a guess brAIn is still watching are not
    decisions anybody can make yet — and so is every chore, finished or
    not: accepting a finding is the press that takes it OFF this count,
    and the To-do tab carries its own (`FEED_KINDS`). So is every proposal,
    which the Proposals tab's own badge counts (`FEED_STORES`).
    """
    # And a finding still waiting for its first look past
    # `triage.SHOW_AFTER_S`. It is not a case — nothing has judged it — but
    # it is on the feed beneath the cases (`waiting_look`) and it may be
    # serious, so a badge of 0 over it is the one count that must not be
    # given. Counted, not converted: the look still decides what it is.
    try:
        waiting = findings_store.waiting_look_count(now)
    except Exception:  # noqa: BLE001 — the cases are the badge's floor
        waiting = 0
    return len(list_cases("open", now=now)) + waiting


def get(value: str, now: float | None = None) -> dict | None:
    """One case by id, from the one store its prefix names.

    Reads that store alone rather than filtering `list_cases`, because
    this is asked on every press and three of the four reads are then work
    nobody wanted. A snoozed case still answers here: the id was pressed,
    so somebody is looking at it.
    """
    split = split_id(value)
    if split is None:
        return None
    store, key = split
    snoozes = _read_snoozes()
    if store == "findings":
        row = findings_store.get(key)
        if row is None or row.get("status") not in _FINDING_STATUS:
            return None
        return _from_finding(row, snoozes)
    if store == "proposals":
        row = proposals.get(key)
        if row is None or row.get("status") not in proposals.OPEN_STATUSES:
            return None
        return _from_proposal(row, snoozes)
    if store == "hypotheses":
        for row in hypotheses.list_all("open"):
            if int(row.get("ts") or 0) == key:
                return _from_hypothesis(row, snoozes)
        return None
    item = todo_store.get(key)
    return _from_todo(item, snoozes) if item else None


# ---------------------------------------------------------------------------
# The three endings
# ---------------------------------------------------------------------------

def end(value: str, verb: str, note: str = "", *, hooks: Hooks,
        now: float | None = None) -> dict | None:
    """End a case. Returns what happened, or None if nothing did.

    None for a case that is not there, a verb that is not one of the
    three, a verb that does not apply to that kind, and a hook the server
    did not pass — four different silences, and the returned `None` is the
    same for all of them because every one of them is "this press changed
    nothing" and the caller's job is a 404 or a 409 either way. The
    distinction a caller *can* act on is on the record: `result` is
    whatever the hook answered, so a hook that refused says so in its own
    words rather than through this one.

    Exactly one hook fires per press. `not_now` fires none — it writes a
    snooze, which is the store's own field for a finding and this module's
    sidecar for everything else — and it is the only verb that leaves the
    row exactly as it was, which is the whole of what "not now" means.
    """
    now = time.time() if now is None else now
    if verb not in VERBS:
        return None
    case = get(value)
    if case is None:
        return None
    if case["status"] not in ENDABLE_STATUSES:
        return None
    note = str(note or "").strip()[:findings_store.MAX_NOTE]
    store, key = case["origin"]["store"], case["origin"]["key"]

    if verb == "not_now":
        until = _snooze_until(case, now)
        if store == "findings":
            # The store carries the field and has since "not now" existed,
            # so the sidecar must not shadow it: one answer to "when does
            # this come back", in the place every other reader of a
            # finding already looks.
            findings_store.snooze(int(key), until)
        elif store == "hypotheses" and hypotheses.snooze(int(key), until):
            # The queue holds its own now, for the finding's reason and one
            # more: only the queue can stop a sleeping guess holding one of
            # its three slots, and only the queue can keep it from expiring
            # before it comes back.
            pass
        else:
            rows = _read_snoozes()
            rows[case["id"]] = until
            _write_snoozes(rows, now)
        return {"id": case["id"], "kind": case["kind"], "verb": verb,
                "when": int(now), "snoozed_until": until, "result": None}

    spec = (_STORE_ENDINGS.get((store, case["kind"], verb))
            or _ENDINGS.get((case["kind"], verb)))
    if spec is None:
        return None
    hook_name, word = spec
    hook = getattr(hooks, hook_name, None)
    if hook is None:
        # A hook that is not there is a refusal and never an ending that
        # happened: answering "done" here would delete nothing and settle
        # nothing while the card went away, which is the one outcome with
        # no way back.
        return None
    result = hook(key, word, note) if word else hook(key)
    return {"id": case["id"], "kind": case["kind"], "verb": verb,
            "when": int(now), "snoozed_until": 0, "result": result}


# ---------------------------------------------------------------------------
# The rest of the verbs
# ---------------------------------------------------------------------------

def answers(case: dict) -> list[dict]:
    """The presses this case shows, primary first — `answers.answers`,
    reached through this module so a caller holding a case never has to
    know which module decides. See `answers.py` for the argument."""
    return answers_mod.answers(case)


def situation(case: dict) -> str:
    return answers_mod.situation(case)


def more(case: dict) -> list[dict]:
    """What goes behind the ⋯: *Later* and every rare verb the visible
    row has not already offered. `overflow` is unchanged underneath, so
    a test of what a case CAN do still reads it whole."""
    return answers_mod.more(case, answers(case), overflow(case))


def overflow(case: dict) -> list[dict]:
    """The rare verbs still available for this case, as `{verb, route}`.

    Thirteen verbs on a row is a card nobody can hold in their head, and
    every one of them exists for a documented reason — so they move behind
    a ⋯ rather than going. What this returns is the route each one already
    has, so the feed can render them without knowing that a hypothesis is
    a different store from a finding; `label` and `method` ride along
    because a menu needs a word and a fetch needs a verb, and a second
    table of those in the panel is a second thing to keep in step.

    A verb that cannot work right now is ABSENT rather than disabled: a
    greyed-out row in a menu is a control asking to be understood, which
    is `todo_store`'s Forget rule and BRUH Print's before it.
    """
    if not isinstance(case, dict):
        return []
    kind, status = case.get("kind"), case.get("status")
    store = (case.get("origin") or {}).get("store")
    key = (case.get("origin") or {}).get("key")
    out: list[dict] = []

    def add(verb: str, label: str, route: str, method: str = "POST") -> None:
        out.append({"verb": verb, "label": label, "route": route,
                    "method": method})

    if store == "findings":
        if status == "acting":
            # A run is changing the house. Talking about it is the only
            # thing that does not interfere with what it is doing.
            add("discuss", "Talk about it", f"/api/finding/{key}/discuss")
            return out
        if kind == "problem":
            # The claim *Add to list* deliberately does not make. It is
            # rarer than agreeing to do something and it writes a memory
            # line that is only true once the work is finished.
            add("done", "I've already fixed it", f"/api/finding/{key}/done")
            if status == "open":
                add("fix", "Work out what to change",
                    f"/api/finding/{key}/fix")
            if status == "watching":
                # `elevate` is `unsettle`'s press one lifecycle earlier:
                # it stops the suppression and changes nothing else.
                add("elevate", "Bring it to the front",
                    f"/api/finding/{key}/elevate")
            if str(case.get("source") or "").startswith("check:"):
                add("recheck", "Check again", f"/api/finding/{key}/recheck")
        if kind == "change":
            add("unfix", "Put it back", f"/api/finding/{key}/unfix")
        add("discuss", "Talk about it", f"/api/finding/{key}/discuss")
        add("advice", "Say what to do", f"/api/finding/{key}/advice")
        if case.get("source") and case["source"] not in UNMUTABLE_SOURCES:
            # The press for the RULE rather than for the row. It carries
            # no id because it is about a producer, which is why it is the
            # one route here that is not under `/api/finding/{id}/`.
            add("mute", "Stop raising these", "/api/findings/mute")
    elif store == "proposals":
        if status == "open":
            # A week of the house as it is really lived, replayed and
            # graded — the evidence that makes an accept a different
            # object from a yes to something that sounded reasonable.
            add("trial", "Try it for a week", f"/api/proposal/{key}/trial")
    elif store == "todo" and status == "done":
        add("reopen", "Put it back", f"/api/todo/{key}/reopen")
    return out


__all__ = [
    "CHORE_SNOOZE_S", "Hooks", "KINDS", "FEED_KINDS", "FEED_STORES", "LIVE_STATUSES",
    "MAX_SNOOZED", "UNMUTABLE_SOURCES",
    "MIN_SNOOZE_S", "PREFIXES", "SNOOZE_BY_STAKES", "SNOOZE_FILE", "STAKES",
    "STATUSES", "STORES", "VERBS", "answers", "case_id", "end", "get",
    "list_cases", "more", "open_count", "overflow", "situation",
    "snooze_until", "split_id",
]
