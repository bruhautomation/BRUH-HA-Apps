"""Findings — the things brAIn thinks are broken, and what it did about them.

Memory answers "what is true of this home". A hypothesis answers "am I right
about this home". A **finding** is the third thing neither of those covers:
something that is *wrong* and has an owner. A battery that died, a sensor
that stopped reporting, an automation that can never fire, an entity whose
name means nothing to anyone.

The lifecycle is deliberately short, because a list of problems nobody ever
settles is just a second inbox:

  open ──fix──▶ planning ─▶ planned    a read-only run says what it WOULD
                                       change; nothing has happened yet
  planned ──"Cancel"────────▶ open     the plan stays on the row
  planned ──"Apply"─▶ fixing ─▶ fixed  brAIn made the change; you haven't
                            │          read what it did yet
                            ├─▶ failed      it tried and couldn't
                            └─▶ needs_you   only a human can (the battery)
  fixed ──"Undo"────────────▶ open     the files it wrote are back
       ──"I've handled it"───▶ settled: you fixed it yourself
       ──"Wrong"─────────────▶ settled: it isn't a problem here, and here is
                                        why — in the homeowner's own words
  fixed ──"Got it"────────────▶ settled: you have seen what brAIn changed

**A finding leaves the list when a person ends it, and then it is gone.**
Every ending is a press, and every press deletes the row — there is no
archive of dismissed cards to scroll past, because a list of things nobody
has to look at again is exactly the clutter this tab exists to avoid. Note
that `fixed` is therefore still *live*: brAIn changing something in your
house is news, and news you have not read is not settled.

What survives an ending is the answer, not the row. It goes two places: a
plain line in `memory.md` (this is now true of the home) and a normalised
key in the settled ledger, which is what stops the analyst reporting the
same thing at you next week. The ledger is an index, never a queue —
nothing is swept out of it, because sweeping it is how a problem you
already answered comes back.

**"Wrong" carries a reason, and the reason is the valuable half.** A key
suppresses one wording; "that sensor always reads on, it isn't stuck" tells
the analyst why a whole shape of report is noise in this home, and it is
the difference between a list that gets quieter and one that keeps making
the same mistake in new words. The note rides along on the ledger entry —
there is no second store for it, because a correction with no report to
correct is not a thing anybody wrote — and ``prompt_block`` renders it
under the finding it belongs to. It is not an instruction and is not
phrased as one: the model is handed what the homeowner said and left to
work out what follows from it.

Two producers write here:

  * insight runs — the ``findings`` array of the generation contract, added
    through :func:`add` by the panel
  * study sessions — ``brain learn`` drops JSONL into
    ``/config/.brain/findings/inbox/``, which :func:`sweep_inbox` folds in

Deduplication is by normalized title across *every* status, so a finding
that was fixed or ignored in March cannot come back in April wearing
slightly different words.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations


import functools
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import answers
import atomic_write
import triage

log = logging.getLogger("brain.findings")

FINDINGS_FILE = Path(os.environ.get("BRAIN_FINDINGS_FILE", "/data/findings.json"))
# Where `brain learn` (and anything else on the CLI side) leaves findings it
# discovered. Same hand-off shape as the memory inbox: append-only JSONL on
# the shared volume, swept by whoever reads next.
INBOX_DIR = Path(os.environ.get(
    "BRAIN_FINDINGS_INBOX", "/config/.brain/findings/inbox"))
# The answers, kept after the rows are gone. Not the findings file, because
# this one is an index that is never swept — see settle_and_clear.
SETTLED_FILE = Path(os.environ.get(
    "BRAIN_FINDINGS_SETTLED", "/data/findings-settled.json"))
# A compact mirror on the shared volume, for the HA integration. The store
# itself lives in /data, which Home Assistant cannot see — so a critical
# finding discovered at 3am was invisible until somebody opened the panel.
# This file is what the integration's sensor reads and its event watcher
# diffs; it is derived, never read back, and republished on every write.
STATE_FILE = Path(os.environ.get(
    "BRAIN_FINDINGS_STATE", "/config/.brain/findings_state.json"))
# Plenty for a sensor attribute; the panel remains the place to work a list.
STATE_MAX_ROWS = 50
# Per-row cap on the prose in the mirror. See `_publish_state`.
STATE_MAX_PROSE = 240

MAX_FINDINGS = 200
# Far more than the list, because it is one short line each and losing the
# oldest entry is how a problem you answered in spring comes back in autumn.
MAX_SETTLED = 1000
MAX_TEXT = 200
MAX_DETAIL = 600
MAX_FIX = 600
# Who may have written a row's `fix` — see `_shape`. The rule's own
# sentence is the empty string, which is what every row filed before this
# existed reads as.
FIX_AUTHORS = ("triage", "chat", "resident")
MAX_RESULT = 1500
MAX_CHANGED = 8
# A correction is a sentence, not an essay. Long enough for "that sensor
# always reads on because it watches the fridge compressor", short enough
# that twenty of them still fit in a prompt beside everything else.
MAX_NOTE = 400

# ---------------------------------------------------------------------------
# What a Resident-written row carries, and what every other row does not
# ---------------------------------------------------------------------------
#
# A finding has always been one shape: a sentence, a severity, and the rule
# that said it. A **case** written by the Resident is that row with the
# run's own reasoning on it — what it is claiming, how sure it is, what it
# actually read, and what it proposes doing about it. Those facts exist
# only inside the investigation that produced them, and the row is the one
# thing that outlives the run, so the row is where they go.
#
# Every field below is OPTIONAL and ABSENT by default, which is the whole
# of the compatibility argument: `_shape` adds a key only for a row that
# carries something, so a house check's finding is byte-for-byte the dict
# it has always been — in the store, in the shared-volume mirror, in
# `/api/findings`, in a `todo.brain` item and in every test that pins one.
#
# The kinds live here rather than in `cases.py` because the word is written
# on disk and this is the module that decides what may be: a second copy in
# the reader would be a vocabulary the store refuses and the feed renders.
CASE_KINDS = ("problem", "opportunity", "question", "chore", "change")
STAKES = ("low", "medium", "high")
# One sentence, and deliberately not a second title: `text` is what the
# store dedupes on and what a check reports, where this is what the run
# asserts. A card shows the claim; the ledger keys on the text.
MAX_CLAIM = 240
# What the run READ — the difference between an investigation and an
# opinion, and the thing a person checks a claim against. Capped because a
# card renders every row of it.
MAX_EVIDENCE = 8
MAX_EVIDENCE_ENTITY = 255
MAX_EVIDENCE_VALUE = 120
MAX_EVIDENCE_WHEN = 40
# What it proposes doing. Four, because a case offering five things to
# choose between is not a decision anybody makes on a phone.
MAX_ACTIONS = 4
MAX_ACTION_LABEL = 90
MAX_ACTION_DETAIL = 400
# The consent shapes, from the design page. `consent` is a separate flag
# rather than something a shape implies, because "send a notification" and
# "edit somebody's automations.yaml" are both real actions and only one of
# them needs asking — and which is which is a claim the producer makes,
# not a lookup this module could perform.
ACTION_SHAPES = ("notify", "edit_file", "call_service", "write_automation")
# What an ending ought to teach, in the run's own words. A sentence handed
# to whoever writes the memory line, never a line written here: `memory.md`
# has one writer and this store is not it.
MAX_MEMORY_HINT = 300

# What an ending can say. `fixed` and `ignored` are the two the tab has
# always had; `accepted` is the third and it is a different claim from
# both — the report was right AND the work is not done yet, which is what
# moving a card to the to-do list means. It has to be its own word for two
# reasons: the scorecard counts it as the report being confirmed (agreeing
# to do something is agreeing it is real), and completing the chore later
# re-settles the same key as `fixed`, which is an upgrade a shared word
# could not express.
SETTLE_KINDS = ("fixed", "ignored", "accepted")

SEVERITIES = ("info", "warning", "serious", "critical")
# `triaging` and `held` are `triage.py`'s two words and they bracket
# `open` rather than joining the lifecycle after it: a house check files
# into `triaging` because nothing has looked at its row yet, and a run
# that looked moves it to `open` (real) or `held` (looked at, not worth
# showing). Both are deliberately absent from LIVE_STATUSES and
# UNSETTLED_STATUSES — a row nothing has judged is not work waiting on
# anybody, and a held one is not either — and both are CLEARABLE, because
# a check that stops reporting something has stopped reporting it whether
# or not it ever reached a screen.
# `planning` and `planned` are the two halves of pressing Fix it, and they
# are deliberately two words rather than one. `planning` is a read-only run
# in flight working out what it WOULD change — nothing is waiting on a
# person and nothing has been touched; `planned` is the answer sitting on
# the card with Apply and Cancel under it, which is a decision and the only
# kind of thing a badge may count. Collapsing them into one word would make
# the badge count a run nobody can answer yet, and would make the card say
# "apply this" over a plan that does not exist.
STATUSES = ("triaging", "open", "planning", "planned", "fixing", "fixed",
            "failed", "needs_you", "ignored", "held")
# The statuses a PRODUCER may file into. Everything else is reached by a
# person pressing something or by brAIn acting, so `coerce` takes only
# these two off the wire: a row arriving as `ignored` would be a producer
# settling a finding nobody was ever shown.
PRE_STATUSES = ("open", "triaging")
# Statuses that still want the homeowner's attention on the Findings tab.
# `fixed` is in here: an automated fix changed something in the house, and
# that stays on the list until somebody has read what it did.
LIVE_STATUSES = ("open", "planning", "planned", "fixing", "fixed", "failed",
                 "needs_you")
# ...and the subset the tab badge counts: a fix already running isn't a
# decision anyone has to make, and neither is the read-only run working out
# what it would do. A `planned` row IS one — Apply or Cancel is exactly the
# shape of question this badge exists to count.
UNSETTLED_STATUSES = ("open", "planned", "fixed", "failed", "needs_you")

# What goes back into the analyst's prompt. Ignored findings are the point of
# the block — capped so it can never grow into a wall.
PROMPT_OPEN = 12
PROMPT_IGNORED = 20
PROMPT_FIXED = 20

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Case/punctuation-insensitive form used to dedupe findings."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

# atomic_write makes each individual write atomic; it does nothing for the
# read-modify-write around it. The panel mutates this store from the event
# loop (add_many in _generate, set_status in _run_fix) *and* from request
# threads (the verb handlers run under asyncio.to_thread), so two operations
# could both _load, both mutate, and the last _write wins — a fresh finding
# silently vanishing under a user's "Wrong", or the reverse. Every mutator
# holds this lock across its whole load→mutate→write; an RLock because
# settle_and_clear writes both files through nested helpers.
_LOCK = threading.RLock()


def _mutates(fn):
    """One store operation at a time, whole, whichever thread asks."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapped


def _load() -> list[dict]:
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("findings") if isinstance(data, dict) else None
    return [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []


def _write(items: list[dict]) -> None:
    atomic_write.write_json(FINDINGS_FILE, {"findings": items})
    # Every write republishes the shared-volume mirror, so the two can never
    # drift: there is no code path that changes the store without it.
    _publish_state(items)


def _publish_state(items: list[dict]) -> None:
    """Mirror a summary of the live list onto the shared volume.

    Best-effort by design, with the failure logged rather than raised: the
    mirror is how Home Assistant *sees* findings, but a read-only /config
    must not be able to lose the finding itself, which is already safe in
    /data by the time this runs.

    Skipped entirely when the shared volume's parent directory does not
    exist — that is a dev checkout or a test, not a broken install, and
    creating a stray /config on somebody's laptop would be worse than
    skipping.
    """
    if not STATE_FILE.parent.parent.is_dir():
        return
    now = time.time()
    shaped = [s for s in (_shape(e) for e in items) if s["text"]]
    shaped.sort(key=lambda f: f["ts"], reverse=True)
    live = [s for s in shaped
            if s["status"] in LIVE_STATUSES and not is_snoozed(s, now)]
    open_rows = [s for s in live if s["status"] in UNSETTLED_STATUSES]
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(STATE_FILE, {
            "ts": int(now),
            "open": len(open_rows),
            "by_severity": {sev: len([s for s in open_rows
                                      if s["severity"] == sev])
                            for sev in SEVERITIES},
            "findings": [
                # `detail` and `fix` are cut harder here than in the
                # store: this file is a summary Home Assistant reads on
                # a timer, the panel holds the full text, and a to-do
                # item's description is read on a phone before deciding
                # whether to get up. Fifty rows of 600 characters each
                # would be 60 KB of mirror for two paragraphs nobody
                # scrolls to the end of.
                #
                # `kind` and `claim` are appended LAST and only for a row
                # that carries them, so a mirror of ordinary findings is
                # byte-for-byte the file the integration has always read.
                {**{k: s[k] for k in ("ts", "text", "severity", "status",
                                      "entity_id", "fixable", "source_title")},
                 "detail": s["detail"][:STATE_MAX_PROSE],
                 "fix": s["fix"][:STATE_MAX_PROSE],
                 # The presses this row can be given from outside the
                 # panel, `[{action, label}]`, decided by the same table
                 # the feed renders from. Repairs shows this subset and
                 # a notification's buttons are these, so a battery is
                 # *Add to to-do · Replaced it · Not a problem* on every
                 # surface rather than three different questions.
                 "answers": answers.request_answers(s),
                 **{k: s[k] for k in ("kind", "claim") if s.get(k)}}
                for s in live[:STATE_MAX_ROWS]
            ],
        })
    except OSError as exc:
        log.warning("could not publish findings state to %s: %s",
                    STATE_FILE, exc)


@_mutates
def publish_state() -> None:
    """Republish the mirror from the store as it stands.

    Called at startup so the integration has a current file to read even
    when nothing has changed since the last boot — the alternative is a
    sensor reporting last week until the first new finding lands.
    """
    _publish_state(_load())


def _unique_ts(used: set[int]) -> int:
    """A timestamp no entry already holds — ts doubles as the id the panel
    acts on, and one insight run can report three findings in one second."""
    ts = int(time.time())
    while ts in used:
        ts += 1
    return ts


def _clean_changed(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:200])
        if len(out) >= MAX_CHANGED:
            break
    return out


# What a plan may say, capped. The steps are the load-bearing half — they
# are what somebody reads before consenting to a change in their house — so
# there are enough of them to describe a real fix and few enough that the
# card stays a card.
MAX_PLAN_STEPS = 10
MAX_PLAN_STEP = 200
MAX_PLAN_RISK = 300
MAX_PLAN_SUMMARY = 600


def _clean_plan(value) -> dict:
    """One stored plan, normalized — `{}` when nothing has planned.

    An empty dict rather than a `None` for `_clean_triage`'s reason: every
    reader asks `.get("steps")`, and an absent list is the honest answer
    for a row nothing has looked at. `can_fix` defaults FALSE, because the
    card only offers Apply when a plan says software can do it, and a plan
    this could not read must not be read as permission.
    """
    if not isinstance(value, dict):
        return {}
    steps = []
    for item in value.get("steps") or []:
        if isinstance(item, str) and item.strip():
            steps.append(item.strip()[:MAX_PLAN_STEP])
        if len(steps) >= MAX_PLAN_STEPS:
            break
    needs_you = bool(value.get("needs_you"))
    return {
        # Mutually exclusive by definition, the same way `fixer.parse_result`
        # reads them: a fix that needs hands is not one software can make.
        "can_fix": bool(value.get("can_fix")) and not needs_you,
        "needs_you": needs_you,
        "steps": steps,
        "risk": str(value.get("risk") or "").strip()[:MAX_PLAN_RISK],
        "summary": str(value.get("summary") or "").strip()[:MAX_PLAN_SUMMARY],
        "at": int(value.get("at") or 0),
    }


def _clean_triage(value) -> dict:
    """The triage record on a row, normalized — `{}` when nothing looked.

    An empty dict rather than a `None` because every reader of it asks
    `.get("verdict")` and an absent verdict is the honest answer for a
    row nothing has judged. `triage.VERDICTS` is the closed vocabulary,
    imported lazily so the store keeps no import of the module that
    decides policy about it.
    """
    if not isinstance(value, dict):
        return {}
    verdict = str(value.get("verdict") or "").strip().lower()
    if verdict not in triage.VERDICTS:
        return {}
    return {
        "verdict": verdict,
        "reason": str(value.get("reason") or "").strip()[:triage.MAX_REASON],
        "run_id": str(value.get("run_id") or "").strip()[:64],
        "at": int(value.get("at") or 0),
        # Set when a person pressed "Bring it to the front" on a held row.
        # Kept beside the verdict rather than over it: the verdict is what
        # the run said, and overwriting it would lose the one piece of
        # evidence that triage got this one wrong.
        "elevated_by_person": bool(value.get("elevated_by_person")),
        # Whether the row's `fix` is the run's own sentence rather than
        # the generic one the rule filed. The text itself lives in `fix`,
        # where every reader of a finding already looks; this is the
        # record of who wrote it.
        "wrote_fix": bool(value.get("wrote_fix")),
    }


def _clean_evidence(value) -> list[dict]:
    """`[{entity, value, when}, ...]` — what a run says it read.

    A row naming no entity is DROPPED rather than kept with an empty one.
    The whole claim this field makes is *which* entity was read, so a row
    that names none is an assertion wearing evidence's clothes, and one of
    those under a heading saying "what I looked at" is worse than a short
    list.
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip()[:MAX_EVIDENCE_ENTITY]
        if not entity:
            continue
        out.append({
            "entity": entity,
            "value": str(item.get("value") or "").strip()[:MAX_EVIDENCE_VALUE],
            "when": str(item.get("when") or "").strip()[:MAX_EVIDENCE_WHEN],
        })
        if len(out) >= MAX_EVIDENCE:
            break
    return out


def _clean_actions(value) -> list[dict]:
    """`[{label, shape, consent, detail}, ...]` — what a run proposes doing.

    A shape this does not recognise is dropped, never coerced to the
    nearest one it does: every entry here is something that would happen
    to somebody's house, and reading an unknown word as the closest known
    one is how a `notify` becomes a file edit. `consent` defaults TRUE for
    `_clean_plan`'s reason one field over — an action this could not read
    properly must never be read as permission already given.
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        shape = str(item.get("shape") or "").strip().lower()
        label = str(item.get("label") or "").strip()[:MAX_ACTION_LABEL]
        if shape not in ACTION_SHAPES or not label:
            continue
        out.append({
            "label": label,
            "shape": shape,
            "consent": item.get("consent", True) is not False,
            "detail": str(item.get("detail") or "").strip()[:MAX_ACTION_DETAIL],
        })
        if len(out) >= MAX_ACTIONS:
            break
    return out


def _case_fields(entry: dict) -> dict:
    """The Resident's half of a row — only the keys it actually carries.

    Absent rather than empty, so a row a check filed is the dict it has
    always been and nothing downstream has to learn a new key in order to
    go on rendering it. That is also why this is a separate function
    rather than six more lines in `_shape`: `coerce` needs exactly the
    same answer, and two copies of "what may a case say" is the drift a
    second copy always produces.
    """
    out: dict = {}
    kind = entry.get("kind")
    if kind in CASE_KINDS:
        out["kind"] = kind
    claim = str(entry.get("claim") or "").strip()[:MAX_CLAIM]
    if claim:
        out["claim"] = claim
    confidence = entry.get("confidence")
    # `isinstance(True, int)` is True, and a bool here would render as a
    # confidence of 1.0 — which is the one number this field must not be
    # able to invent.
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        out["confidence"] = round(min(1.0, max(0.0, float(confidence))), 3)
    if entry.get("stakes") in STAKES:
        out["stakes"] = entry["stakes"]
    evidence = _clean_evidence(entry.get("evidence"))
    if evidence:
        out["evidence"] = evidence
    actions = _clean_actions(entry.get("actions"))
    if actions:
        out["actions"] = actions
    hint = str(entry.get("memory_hint") or "").strip()[:MAX_MEMORY_HINT]
    if hint:
        out["memory_hint"] = hint
    investigation = entry.get("investigation")
    if isinstance(investigation, dict):
        run_id = str(investigation.get("run_id") or "").strip()[:64]
        if run_id:
            out["investigation"] = {"run_id": run_id}
    return out


def _shape(entry: dict) -> dict:
    """One stored finding, normalized for the API."""
    status = entry.get("status")
    if status not in STATUSES:
        status = "open"
    severity = entry.get("severity")
    if severity not in SEVERITIES:
        severity = "warning"
    out = {
        "ts": int(entry.get("ts") or 0),
        "text": str(entry.get("text") or "")[:MAX_TEXT],
        "detail": str(entry.get("detail") or "")[:MAX_DETAIL],
        "fix": str(entry.get("fix") or "")[:MAX_FIX],
        # Whose sentence `fix` is: "" for the rule's own, "triage" for the
        # run that looked at the row before it was shown, "chat" for a
        # conversation the homeowner had about it. The card says which.
        "fix_by": (entry.get("fix_by")
                   if entry.get("fix_by") in FIX_AUTHORS else ""),
        "severity": severity,
        "fixable": bool(entry.get("fixable", True)),
        "entity_id": str(entry.get("entity_id") or "")[:255],
        "source": str(entry.get("source") or "")[:64],
        "source_title": str(entry.get("source_title") or "")[:120],
        # Which Claude run raised it, when one did. Empty for a house
        # check, which is the honest answer: nothing was asked. It is
        # what `capture` joins an ENDING back to the prompt that earned
        # it — the label half of the corpus — and it is deliberately not
        # in the shared-volume mirror, because Home Assistant has no use
        # for a session id.
        "run_id": str(entry.get("run_id") or "")[:64],
        "status": status,
        "result": str(entry.get("result") or "")[:MAX_RESULT],
        "changed": _clean_changed(entry.get("changed")),
        "settled_at": int(entry.get("settled_at") or 0),
        # "Not now" is not a decision, so it is not a status. Dismissing is
        # permanent and is fed back into every future analysis; snoozing has
        # to leave the finding exactly as open as it was and just stop it
        # asking. A separate field is the only way to keep those apart.
        "snoozed_until": int(entry.get("snoozed_until") or 0),
        # What looked at this before it was shown, if anything did.
        # `{verdict, reason, run_id, at, elevated_by}` — `run_id` is the
        # triage conversation, which the panel opens as a record through
        # the reader every other engine-store run uses, because "I can see
        # the discussion you had about it" is the half that makes a
        # verdict arguable rather than a word.
        "triage": _clean_triage(entry.get("triage")),
        # What a read-only run said it WOULD change, if Fix it has been
        # pressed. `{can_fix, needs_you, steps, risk, summary, at}` — see
        # `_clean_plan`. It is kept across a Cancel on purpose: the plan
        # cost a Claude run, and a person who wants to look at it again
        # should not have to pay for it twice.
        "plan": _clean_plan(entry.get("plan")),
        # The wall-clock window the tool-enabled run ran in. It is what
        # `unfix` reads the edit journal and the action ledger against, so
        # it is on the row rather than in memory: the Undo button lives for
        # as long as the row says `fixed`, which outlives any process.
        "fix_started": float(entry.get("fix_started") or 0),
        "fix_ended": float(entry.get("fix_ended") or 0),
        # What that run changed, counted when it ended: files it journalled
        # (which an undo puts back) and service calls it made (which an undo
        # lists and never reverses). Two numbers because they are two
        # different claims, and the card says which is which before the
        # press rather than after it.
        "fix_files": int(entry.get("fix_files") or 0),
        "fix_calls": int(entry.get("fix_calls") or 0),
        # When somebody last pressed "Check again" and the check still
        # reported it. Written only by that press, never by the scheduled
        # pass: the schedule confirms every open row every few hours and a
        # stamp that moved on its own would say "checked just now" about a
        # row nobody has looked at, which is the one claim this is for.
        "checked_at": int(entry.get("checked_at") or 0),
    }
    # And the Resident's half, when there is one. Appended rather than
    # declared above so a row that carries none is the dict every existing
    # reader, mirror and test already knows, key for key and order for
    # order — see the block by CASE_KINDS.
    out.update(_case_fields(entry))
    return out


# ---------------------------------------------------------------------------
# Inbox sweep (study sessions and other CLI-side producers)
# ---------------------------------------------------------------------------

@_mutates
def sweep_inbox(shape=None) -> list[dict]:
    """Fold `/config/.brain/findings/inbox/*.jsonl` into the store.

    Same contract as the memory inbox: append-only JSONL, one JSON object
    per line, consumed once. A torn or unparseable line is skipped rather
    than taking the whole file down — a study session that dies mid-write
    must not be able to wedge the Findings tab.

    ``shape`` is `triage.gate`, passed in rather than reached for: this is
    the one producer whose `add_many` call is inside the store, and a
    store that knew the triage policy would be a second place it is
    decided. Passing it is also what closes the bypass the other four do
    not have — a line in the inbox is JSON from another process, so it can
    name its own ``status``, and `coerce` honours one in `PRE_STATUSES`.
    The gate overwrites it.

    Returns the findings that were actually NEW — the callers that log a
    count take a len(), and the notify hook needs the entries themselves,
    because "3 findings arrived" is not a message anyone can act on.
    """
    try:
        files = sorted(INBOX_DIR.glob("*.jsonl"))
    except OSError:
        return []
    pending: list[dict] = []
    swept: list[Path] = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        swept.append(path)
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                pending.append(obj)
    # One write for the whole sweep, not one per finding: a study session
    # that files five would otherwise rewrite the store five times, which on
    # an SD card is five erase cycles for one batch of results.
    added = add_many(shape(pending) if shape else pending)
    for path in swept:
        try:
            path.unlink()
        except OSError:
            # The findings are already filed. An inbox file that will not delete is
            # swept again next pass and deduped by the settled ledger.
            pass
    return added


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def is_snoozed(shaped: dict, now: float | None = None) -> bool:
    """Waiting for its time to come back round."""
    until = shaped.get("snoozed_until") or 0
    return bool(until) and until > (now if now is not None else time.time())


def _matches(shaped: dict, status: str | None) -> bool:
    if status is None:
        return True
    if status == "snoozed":
        return is_snoozed(shaped)
    if status == "live":
        # A snoozed finding is still live — it is just not asking yet, so it
        # stays out of the list you are being shown until it is due.
        return shaped["status"] in LIVE_STATUSES and not is_snoozed(shaped)
    return shaped["status"] == status


def list_all(status: str | None = None) -> list[dict]:
    """Stored findings, newest first. ``status`` may be one status or the
    sentinel ``"live"`` for everything still wanting attention."""
    out = [s for s in (_shape(e) for e in _load())
           if s["text"] and _matches(s, status)]
    out.sort(key=lambda f: f["ts"], reverse=True)
    return out


def listing() -> dict:
    """Everything the Findings tab needs, from ONE read of the file.

    The tab wants the list and the badge count together, and asking for
    them separately meant parsing (and fully shaping) the same file twice
    per request — on a Pi, for a screen that polls.
    """
    shaped = [s for s in (_shape(e) for e in _load()) if s["text"]]
    shaped.sort(key=lambda f: f["ts"], reverse=True)
    now = time.time()
    return {
        "findings": shaped,
        "open": len([f for f in shaped
                     if f["status"] in UNSETTLED_STATUSES
                     and not is_snoozed(f, now)]),
        "snoozed": len([f for f in shaped if is_snoozed(f, now)]),
        # The answers, so the tab can show what it has stopped asking about.
        # Same read, same reply: a second endpoint for it would be a second
        # thing to keep in step with every button that settles something.
        "settled": settled_listing(),
    }


def get(ts: int) -> dict | None:
    for entry in _load():
        if int(entry.get("ts") or 0) == ts:
            return _shape(entry)
    return None


def open_count() -> int:
    """What the Findings tab badge shows: things you haven't settled.

    Counted straight off the raw entries: /api/status polls this every few
    seconds, and shaping 200 findings (slicing every detail, fix and result
    string) to then throw all of it away but the length is real work on a
    Raspberry Pi.
    """
    now = time.time()
    return len([e for e in _load()
                if e.get("status", "open") in UNSETTLED_STATUSES
                and str(e.get("text") or "").strip()
                and not (e.get("snoozed_until") or 0) > now])


def is_known(text: str) -> bool:
    """True when this finding has been reported before in ANY status.

    Reads the settled ledger as well as the list, because settling now
    deletes the row: without the ledger, "you already dealt with this"
    would last exactly as long as the card did.
    """
    key = normalize(text)
    if not key:
        return True
    if any(normalize(f.get("text", "")) == key for f in _load()):
        return True
    return any(e.get("key") == key for e in _load_settled())


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def split_overlong(text: str, detail: str) -> tuple[str, str]:
    """A title over MAX_TEXT is cut at a sentence, and the rest goes to the
    body — never sliced mid-word and dropped.

    The model was told the title is a short statement and routinely wrote
    the whole argument into it; the store then took the first 200
    characters and threw the remainder away, so the card read *"If that
    BLE beacon is something you int"* and the sentence that explained what
    to do was gone for good. Nothing is discarded now: the head is the
    last sentence end inside the cap (the last space failing that), and
    the tail leads the detail, ahead of whatever the model put there.
    """
    if len(text) <= MAX_TEXT:
        return text, detail
    head = text[:MAX_TEXT]
    cut = max(head.rfind(". "), head.rfind("? "), head.rfind("! "),
              head.rfind("; "))
    if cut < MAX_TEXT // 3:
        cut = head.rfind(" ")
        if cut < MAX_TEXT // 3:
            cut = MAX_TEXT
    else:
        cut += 1  # keep the sentence's own full stop on the title
    tail = text[cut:].strip()
    return text[:cut].strip(), (f"{tail}\n{detail}" if detail else tail).strip()


def coerce(obj: dict) -> dict | None:
    """One wire-shaped finding — from a model reply or an inbox line — turned
    into a stored entry, or None if there is nothing there.

    Both producers hand over the same loose shape, so both go through here:
    a second hand-written coercion is how the panel and the CLI drift on what
    "fixable" defaults to.
    """
    if not isinstance(obj, dict):
        return None
    text = str(obj.get("text") or obj.get("finding") or "").strip()
    detail = str(obj.get("detail") or "").strip()
    text, detail = split_overlong(text, detail)
    if not normalize(text):
        return None
    severity = str(obj.get("severity") or "").strip().lower()
    entry = {
        "text": text,
        "detail": detail[:MAX_DETAIL],
        "fix": str(obj.get("fix") or "").strip()[:MAX_FIX],
        "severity": severity if severity in SEVERITIES else "warning",
        # absent means fixable; only an explicit false means hands required
        "fixable": obj.get("fixable", True) is not False,
        "entity_id": str(obj.get("entity_id") or "").strip()[:255],
        "source": str(obj.get("source") or "").strip()[:64],
        "source_title": str(obj.get("source_title") or "").strip()[:120],
        "run_id": str(obj.get("run_id") or "").strip()[:64],
        # A producer may file a row as not-yet-looked-at and nothing else
        # (`PRE_STATUSES`). `triage.gate` is the one caller that does, and
        # an unrecognised status reads as `open` rather than being
        # refused: the safe direction here is the one that shows the
        # finding.
        "status": (obj.get("status")
                   if obj.get("status") in PRE_STATUSES else "open"),
        "result": "",
        "changed": [],
        "settled_at": 0,
    }
    # Whose sentence the `fix` is. A rule's own is the empty string, which
    # is what every row filed before `FIX_AUTHORS` existed reads as; a
    # producer that wrote its own says so, and an author this store cannot
    # name falls back to the rule's rather than being believed.
    if obj.get("fix_by") in FIX_AUTHORS:
        entry["fix_by"] = obj["fix_by"]
    # What looked at it, when the producer IS the thing that looked. Only
    # `add_case` files one — every other producer's rows go through
    # `triage.gate`, which files them as `triaging` for the drain to judge
    # and `record_triage` then overwrites this block whole, so a line in
    # the inbox cannot use it to claim a verdict nothing earned.
    looked = _clean_triage(obj.get("triage"))
    if looked:
        entry["triage"] = looked
    entry.update(_case_fields(obj))
    return entry


def _prune(items: list[dict]) -> list[dict]:
    """Cap the store, dropping oldest SETTLED entries first: an open finding
    is live work, and losing it silently is how a real problem disappears
    without ever being fixed."""
    if len(items) <= MAX_FINDINGS:
        return items
    settled = [f for f in items if f.get("status") in ("fixed", "ignored")]
    settled.sort(key=lambda f: int(f.get("settled_at") or f.get("ts") or 0))
    drop = {id(f) for f in settled[:len(items) - MAX_FINDINGS]}
    return [f for f in items if id(f) not in drop][-MAX_FINDINGS:]


@_mutates
def add_many(objs: list[dict]) -> list[dict]:
    """Record a batch of wire-shaped findings in ONE read and ONE write.

    Returns only the ones that were new — already-known findings are dropped
    silently, in any status, which is what makes a dismissal permanent.

    "Known" spans the settled ledger as well as the list. It has to: settling
    now deletes the row, so deduping against the list alone would make every
    ending behave like Forget, and the analyst would re-report next week the
    thing you answered today.
    """
    items = _load()
    seen = {normalize(f.get("text", "")) for f in items}
    seen |= {str(e.get("key") or "") for e in _load_settled()}
    used = {int(f.get("ts") or 0) for f in items}
    created = []
    for obj in objs:
        entry = coerce(obj)
        if entry is None or normalize(entry["text"]) in seen:
            continue
        entry["ts"] = _unique_ts(used)
        used.add(entry["ts"])
        seen.add(normalize(entry["text"]))
        items.append(entry)
        created.append(_shape(entry))
    if created:
        _write(_prune(items))
    return created


@_mutates
def add(text: str, **fields) -> tuple[dict | None, bool]:
    """Record one finding. Returns (entry, created); an already-known finding
    returns the existing entry untouched, whatever status it now holds.

    A finding that was settled has no entry left to return, so it comes back
    as (None, False): nothing to show, and nothing created.
    """
    entry = coerce({"text": text, **fields})
    if entry is None:
        return None, False
    key = normalize(entry["text"])
    for existing in _load():
        if normalize(existing.get("text", "")) == key:
            return _shape(existing), False
    created = add_many([{"text": text, **fields}])
    return (created[0], True) if created else (None, False)


# Who the Resident files as. It is a producer like any other — which is
# the point, because `scorecard()` adds endings up per producer and the
# number the design page always wanted is the Resident's own precision.
# The title is what the tab and the scorecard show instead of the id.
RESIDENT_SOURCE = "resident"
RESIDENT_TITLE = "The Resident"


@_mutates
def add_case(row: dict, *, run_id: str = "", when: float | None = None) -> dict | None:
    """File a case an investigation wrote. Returns the row, or None.

    Every other producer files through `triage.gate`, which marks its rows
    `triaging` so the drain can go and look before anybody is shown one.
    This one does not, and the reason is not an exemption: **a case IS the
    look**. The row is written by a run that read the entity's history, the
    area and what the house has already been told, and asking a second run
    to grade it would be paying full price to have a model mark homework
    it has just finished — which is the argument `triage.py`'s fourth rule
    rejects for producers that were doing something *else* and mentioned a
    problem on the way past. Nothing was doing something else here.

    So what keeps the gate's promise — that nothing reaches a person
    unjudged — is written ON the row rather than asserted in prose: the
    verdict, the sentence that earned it and the run that said it go into
    the same `triage` block `record_triage` writes, and the card renders
    them exactly as it renders a drained one. A row with no ``claim`` is
    **refused**, because the claim is the judgement: without it this would
    be a door a producer that had not looked could file straight through,
    which is the one thing the gate exists to prevent.

    ``run_id`` is provenance and is not required. A CLI that refused the
    session id leaves a case with no conversation to open, which costs a
    link; refusing the case over it would throw away an investigation that
    happened, and a guard whose cost is the whole feature is the wrong
    guard — see `engine`'s own fallback for the same flag.

    Deduping, the settled ledger, the unique id, the prune and the mirror
    are `add_many`'s, because they are the store's rules and not this
    door's. A case whose text somebody has already answered is therefore
    dropped silently, in any status, exactly as a check's re-report is.
    """
    if not isinstance(row, dict):
        return None
    claim = str(row.get("claim") or "").strip()[:MAX_CLAIM]
    if not claim:
        return None
    stamp = int(when if when is not None else time.time())
    created = add_many([{
        **row,
        "source": str(row.get("source") or RESIDENT_SOURCE)[:64],
        "source_title": str(row.get("source_title") or RESIDENT_TITLE)[:120],
        "run_id": str(row.get("run_id") or run_id or "")[:64],
        # A case is on the list the moment it is written. `held` is
        # triage's word for "looked at and not worth showing", and a
        # Resident run that judged a signal not worth showing wrote no
        # case at all — so there is no second status to reach from here.
        "status": "open",
        "triage": {"verdict": "elevated", "reason": claim,
                   "run_id": str(row.get("run_id") or run_id or ""),
                   "at": stamp,
                   "wrote_fix": bool(str(row.get("fix") or "").strip())},
        "claim": claim,
    }])
    return created[0] if created else None


@_mutates
def set_status(ts: int, status: str, result: str = "",
               changed: list[str] | None = None) -> dict | None:
    """Move a finding along its lifecycle. Unknown ids return None."""
    if status not in STATUSES:
        raise ValueError(f"unknown finding status: {status}")
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts:
            continue
        entry["status"] = status
        if result:
            entry["result"] = str(result)[:MAX_RESULT]
        if changed is not None:
            entry["changed"] = _clean_changed(changed)
        entry["settled_at"] = (
            0 if status in ("open", "planning", "planned", "fixing")
            else int(time.time()))
        _write(items)
        return _shape(entry)
    return None


@_mutates
def set_plan(ts: int, plan: dict, when: float | None = None) -> dict | None:
    """Write what a read-only run said it would change, and stop there.

    The row moves to `planned`, which is the whole point: pressing Fix it
    now buys a *sentence about a change*, and the change itself waits for
    a second press. A plan that says software cannot do this (`can_fix`
    false, or `needs_you`) is stored exactly the same way and is simply
    not offered an Apply — the card says what it says and offers Cancel,
    because a button that cannot help is worse than the sentence.

    Only a row this run is actually about is touched (`planning`, or the
    `open` a Cancel put it back to): a plan arriving late about a finding
    somebody settled in the meantime must not drag it back onto the list,
    which is `record_triage`'s rule for the same reason. Unknown ids and
    rows that have moved on return None.
    """
    stamp = int(when if when is not None else time.time())
    shaped = _clean_plan({**(plan or {}), "at": stamp})
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        if entry.get("status") not in ("planning", "open"):
            return None
        entry["plan"] = shaped
        entry["status"] = "planned"
        entry["settled_at"] = 0
        _write(items)
        return _shape(entry)
    return None


@_mutates
def set_fix_window(ts: int, started: float | None = None,
                   ended: float | None = None, files: int | None = None,
                   calls: int | None = None) -> dict | None:
    """Stamp when the tool-enabled run began, when it stopped, and what it did.

    This is what makes the Undo on a fixed card possible at all: the edit
    journal and the action ledger are both append-only files stamped in
    epoch seconds, and "what did THIS fix change" is answerable only as
    "everything either of them recorded between these two instants".
    Written in two calls rather than one because the start has to be on
    disk before the run is spawned — a panel that dies mid-fix must still
    leave a window somebody can ask about.

    ``files`` and ``calls`` are counted ONCE, when the run ends, and
    stored — never re-derived on the tab's own fetch. The two files they
    are counted out of are append-only and the index has no cap, so a
    count taken per fixed row per poll would read the whole of both every
    few seconds; and the claim being made is about what the run DID, which
    stops being true of a live file the moment anything else writes one.
    What the undo actually managed is reported by the undo.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        if started is not None:
            entry["fix_started"] = float(started)
            # A second attempt is a second window. Clearing the end and the
            # counts here rather than leaving the old ones is what stops an
            # Undo after a retry reverting the span between the two runs,
            # and what stops the card describing the run before this one.
            entry["fix_ended"] = 0.0
            entry["fix_files"] = 0
            entry["fix_calls"] = 0
        if ended is not None:
            entry["fix_ended"] = float(ended)
        if files is not None:
            entry["fix_files"] = max(0, int(files))
        if calls is not None:
            entry["fix_calls"] = max(0, int(calls))
        _write(items)
        return _shape(entry)
    return None


@_mutates
def record_triage(verdicts: dict[int, tuple[str, str]], run_id: str = "",
                  when: float | None = None) -> list[dict]:
    """Write what looked at a batch, and move each row to where it belongs.

    ``verdicts`` is ``{ts: (verdict, reason)}`` or ``{ts: (verdict,
    reason, fix)}``. An ``elevated`` or ``untriaged`` row becomes ``open``
    — the second because nothing looked, which surfaces exactly like the
    first and says so on the card — and a ``held`` row becomes ``held``.

    **An elevated row that came with a ``fix`` takes it as its own.** The
    rule that filed the row wrote the same sentence it writes for every
    row of its kind ("check its power and its connection… then reload its
    integration"), which is what the card showed under *What you'd need to
    do* and what a person reading it called generic and useless. The run
    that elevated the row has looked at the entity, its integration and
    its area, so what it says to do is about THIS device in THIS house,
    and the card carries that instead. The generic sentence is not kept:
    it says nothing the check's own docs do not, and a second field for it
    would be one more thing to render. ``refresh_details`` never touches
    ``fix``, so a re-report on the next pass does not put the generic
    sentence back. An empty ``fix`` leaves whatever was there — the run
    wrote none, and the card is then the card it always was.

    Only a row still in ``triaging`` is touched. Everything else is a row
    a person or the fixer has already moved on from, and a verdict
    arriving late about one of those must not drag it back: a run that
    took four minutes can easily be answering about a finding somebody
    settled in the meantime.

    Returns the rows it changed, shaped.
    """
    stamp = int(when if when is not None else time.time())
    items = _load()
    changed: list[dict] = []
    for entry in items:
        ts = int(entry.get("ts") or 0)
        if ts not in verdicts or entry.get("status") != "triaging":
            continue
        verdict, reason, *rest = verdicts[ts]
        if verdict not in triage.VERDICTS:
            continue
        fix = str(rest[0] if rest else "").strip()[:MAX_FIX]
        wrote_fix = bool(fix) and verdict == "elevated"
        if wrote_fix:
            entry["fix"] = fix
            entry["fix_by"] = "triage"
        entry["status"] = "held" if verdict == "held" else "open"
        entry["triage"] = _clean_triage({
            "verdict": verdict, "reason": reason,
            "run_id": run_id, "at": stamp, "wrote_fix": wrote_fix})
        changed.append(_shape(entry))
    if changed:
        _write(items)
    return changed


@_mutates
def statuses(rows: list[int]) -> dict[int, str]:
    """Where each of these rows stands now, from ONE read and no shaping.

    The checks pass files, then a drain judges some of what is waiting —
    including rows other producers filed — so "what happened to the ones
    I filed" is a question only the store can answer afterwards, and it
    is asked once per pass for a summary line.
    """
    want = {int(t) for t in rows}
    return {int(e.get("ts") or 0): str(e.get("status") or "")
            for e in _load() if int(e.get("ts") or 0) in want}


def awaiting_triage() -> list[dict]:
    """Every row still waiting for something to look at it, OLDEST FIRST.

    The drain reads this rather than being handed what a caller just
    filed, because five producers file and one of them is a tab fetch
    that must not spend. A row filed by any of them is picked up by the
    next drain whoever ran it, which is what makes "every finding is
    triaged" true of the producer that cannot triage its own.

    Oldest first is the half that makes `MAX_BATCH` waiting honest: a row
    that did not fit this batch is at the front of the next one, so it
    cannot lose the same lottery twice.
    """
    rows = [s for s in (_shape(e) for e in _load())
            if s["text"] and s["status"] == "triaging"]
    rows.sort(key=lambda f: f["ts"])
    return rows


def stale_triaging(cutoff: float) -> list[int]:
    """The ids of rows left mid-triage before ``cutoff``.

    A panel that died between filing and judging leaves rows nothing will
    ever come back for, and a problem nobody is ever shown is the one
    outcome this whole step must not be able to produce. The caller
    promotes them through :func:`record_triage` with an ``untriaged``
    verdict, so they surface carrying the reason they were never judged.
    """
    return [int(e.get("ts") or 0) for e in _load()
            if e.get("status") == "triaging"
            and int(e.get("ts") or 0) < int(cutoff)]


@_mutates
def elevate(ts: int) -> dict | None:
    """Put a held finding on the list, because a person said to.

    The verdict is kept and flagged rather than erased: what the run said
    is the only evidence that triage was wrong about this house, and it
    is what the scorecard and anybody reading the row afterwards are
    owed. `unsettle`'s rule — the press stops the suppression and changes
    nothing else.

    Refuses anything that is not held: an open row is already on the list
    and a settled one has an answer on it.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts or entry.get("status") != "held":
            continue
        entry["status"] = "open"
        entry["settled_at"] = 0
        record = _clean_triage(entry.get("triage"))
        record["elevated_by_person"] = True
        entry["triage"] = record
        _write(items)
        return _shape(entry)
    return None


@_mutates
def snooze(ts: int, until: int) -> dict | None:
    """Take a finding off the list until ``until`` (epoch seconds).

    Deliberately does NOT touch the status. "Remind me later" and "not a
    problem" are different answers — the second is permanent and teaches
    the analyst never to raise it again, and using it for the first would
    quietly throw away a real problem you meant to come back to.

    ``until <= 0`` brings it back now.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts:
            continue
        entry["snoozed_until"] = max(0, int(until))
        _write(items)
        return _shape(entry)
    return None


@_mutates
def settle_and_clear(ts: int, kind: str, note: str = "") -> dict | None:
    """Finish with a finding: remember the answer, drop the row.

    A settled finding used to sit in the list for good — the tab filled up
    with things nobody had to look at again, and "dismissed" and "fixed"
    read as two kinds of clutter rather than two different answers.

    What has to survive is not the row, it is the ANSWER: that this was
    dealt with, or that it is not a problem in this home. Both of those are
    facts about the house, so they go where facts about the house go (the
    caller writes them into memory), and the record kept here is the small
    thing the analyst needs — a normalised key, so the same problem is never
    reported at you twice.

    That is the same shape as the facts ledger: an index, not a queue.
    Nothing is deleted from it, because deleting is exactly how something
    you already answered comes back.

    ``note`` is the homeowner's reason, kept verbatim on the ledger entry so
    the analyst reads why rather than only what.
    """
    if kind not in SETTLE_KINDS:
        raise ValueError(f"unknown settlement: {kind}")
    items = _load()
    settled = None
    kept = []
    for entry in items:
        if int(entry.get("ts") or 0) == ts:
            settled = _shape(entry)
            continue
        kept.append(entry)
    if settled is None:
        return None
    _write(kept)
    _remember_settled(settled, kind, note=note)
    settled["note"] = str(note or "").strip()[:MAX_NOTE]
    return settled


def _remember_settled(shaped: dict, kind: str, when: int = 0,
                      note: str = "", key: str = "") -> None:
    """Write the answer into the ledger, replacing anything under that key.

    ``key`` is normally derived from the text, which is the only key any
    caller holding a row could have. A caller holding an item whose row
    was deleted weeks ago passes the key it stored then, because deriving
    it a second time from a copy of the text is a second answer to "which
    entry is this" — and the two would agree right up until they did not.
    """
    ledger = _load_settled()
    key = str(key or "").strip() or normalize(shaped["text"])
    ledger = [e for e in ledger if e.get("key") != key]
    ledger.append({
        "key": key,
        "text": shaped["text"],
        "kind": kind,
        "ts": when or int(time.time()),
        "note": str(note or "").strip()[:MAX_NOTE],
        # Who raised it. An ending is a label — "I did it" says the report
        # was right, "Wrong" says it was not — and without the producer on
        # the entry nothing can add those labels up per producer. That sum
        # is the scorecard, and the scorecard is what says which check or
        # which card is worth trusting in this house.
        "source": str(shaped.get("source") or "")[:64],
        "source_title": str(shaped.get("source_title") or "")[:120],
    })
    _write_settled(ledger[-MAX_SETTLED:])


def _load_settled() -> list[dict]:
    try:
        data = json.loads(SETTLED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("settled") if isinstance(data, dict) else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def _write_settled(items: list[dict]) -> None:
    atomic_write.write_json(SETTLED_FILE, {"settled": items})


def scorecard() -> list[dict]:
    """How right each producer has been, from the endings people gave.

    ``[{source, title, confirmed, wrong, total}, ...]``, most-settled first.
    "I did it" and "Got it" after a fix count as confirmed; "Wrong" counts
    as wrong. Snoozes and open rows count as nothing — a decision not yet
    made is not a label. Only settled entries that recorded a producer
    take part, so a ledger from before that field existed simply scores
    nothing rather than scoring everything as one anonymous producer.
    """
    by: dict[str, dict] = {}
    for e in _load_settled():
        src = str(e.get("source") or "")
        if not src:
            continue
        row = by.setdefault(src, {
            "source": src, "title": str(e.get("source_title") or src),
            "confirmed": 0, "wrong": 0})
        # Agreeing to do something is agreeing the report was right, so
        # an accepted row scores exactly as a fixed one. The alternative
        # was to count it as nothing until the chore is done, which would
        # make a producer look worse the more of its reports people took
        # seriously and had not got round to yet.
        if e.get("kind") in ("fixed", "accepted"):
            row["confirmed"] += 1
        elif e.get("kind") == "ignored":
            row["wrong"] += 1
    rows = list(by.values())
    for r in rows:
        r["total"] = r["confirmed"] + r["wrong"]
    rows.sort(key=lambda r: (-r["total"], r["source"]))
    return rows


@_mutates
def remember_answer(key: str, text: str, kind: str, *, note: str = "",
                    source: str = "", source_title: str = "") -> bool:
    """Record an answer for a problem whose row is already gone.

    `settle_and_clear` is the ordinary door and it needs a row to delete.
    A chore completed on the To-do tab has no row — the move deleted it
    weeks ago — and the answer still has to reach the ledger, because the
    entry written then said `accepted` and the truth now is `fixed`.
    `_remember_settled` replaces by key, so this is an upgrade in place
    rather than a second entry, which is what keeps one problem one row of
    the scorecard.

    Returns False for a key it will not write, so a caller cannot read
    "nothing to record" as "recorded".
    """
    key = str(key or "").strip()
    text = str(text or "").strip()
    if not key or not text or kind not in SETTLE_KINDS:
        return False
    _remember_settled({"text": text, "source": source,
                       "source_title": source_title}, kind, note=note, key=key)
    return True


def settled_listing() -> list[dict]:
    """What has been answered, newest first — for the Settled filter."""
    return sorted(_load_settled(), key=lambda e: e.get("ts") or 0, reverse=True)


@_mutates
def unsettle(key: str) -> bool:
    """Put an answered problem back in play.

    Drops it from the ledger, which is the one thing that ever removes an
    entry — and it is a deliberate act by the person it was hidden from,
    which is the only reason good enough.
    """
    ledger = _load_settled()
    kept = [e for e in ledger if e.get("key") != key]
    if len(kept) == len(ledger):
        return False
    _write_settled(kept)
    return True


@_mutates
def merge_rows(rows: list[dict]) -> int:
    """Fold another install's exported findings in — for `brain memory
    import`. Unlike add_many this preserves each row's lifecycle (status,
    result, snooze, settled_at): a migration is moving live work, not
    re-reporting it. Known texts are skipped in any status, and the settled
    ledger still wins — an answer given on THIS install is never undone by
    a row imported from another one."""
    items = _load()
    seen = {normalize(f.get("text", "")) for f in items}
    seen |= {str(e.get("key") or "") for e in _load_settled()}
    used = {int(f.get("ts") or 0) for f in items}
    added = 0
    for row in rows:
        entry = coerce(row)
        if entry is None or normalize(entry["text"]) in seen:
            continue
        status = row.get("status")
        entry["status"] = status if status in STATUSES else "open"
        entry["result"] = str(row.get("result") or "")[:MAX_RESULT]
        entry["changed"] = _clean_changed(row.get("changed"))
        entry["settled_at"] = int(row.get("settled_at") or 0)
        entry["snoozed_until"] = int(row.get("snoozed_until") or 0)
        # The original ts is the id everything exported alongside it refers
        # to, so it is kept where it is free; a collision gets a fresh one.
        ts = int(row.get("ts") or 0)
        entry["ts"] = ts if ts > 0 and ts not in used else _unique_ts(used)
        used.add(entry["ts"])
        seen.add(normalize(entry["text"]))
        items.append(entry)
        added += 1
    if added:
        _write(_prune(items))
    return added


@_mutates
def merge_settled(entries: list[dict]) -> int:
    """Fold another install's settled ledger in — existing entries win.

    The ledger is what stops the analyst re-reporting an answered problem,
    so a migration that dropped it would replay every dismissal the old
    install had already bought off.
    """
    ledger = _load_settled()
    known = {str(e.get("key") or "") for e in ledger}
    added = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = normalize(str(entry.get("key") or entry.get("text") or ""))
        if not key or key in known:
            continue
        kind = entry.get("kind")
        ledger.append({
            "key": key,
            "text": str(entry.get("text") or "")[:MAX_TEXT],
            "kind": kind if kind in ("fixed", "ignored") else "ignored",
            "ts": int(entry.get("ts") or 0) or int(time.time()),
            "note": str(entry.get("note") or "").strip()[:MAX_NOTE],
        })
        known.add(key)
        added += 1
    if added:
        _write_settled(ledger[-MAX_SETTLED:])
    return added


@_mutates
def migrate_settled() -> int:
    """Fold pre-ledger dismissals into the ledger and drop their rows.

    Before the ledger, "Not a problem" left the card in the list forever
    under a Dismissed filter. That filter is gone, so an upgrade would
    otherwise strand every one of those answers somewhere nobody can see —
    still suppressing the finding, with nothing on screen saying so. Run at
    startup; idempotent, because after the first pass there are no rows in
    that status left to move.

    `fixed` rows are deliberately left alone: they are live now, and the
    homeowner reads what brAIn changed and presses Got it.
    """
    items = _load()
    kept, moved = [], []
    for entry in items:
        if entry.get("status") == "ignored":
            moved.append(_shape(entry))
            continue
        kept.append(entry)
    for shaped in moved:
        _remember_settled(shaped, "ignored", when=shaped.get("settled_at") or 0)
    if moved:
        _write(kept)
    return len(moved)


@_mutates
def reconcile_running(reason: str) -> int:
    """Demote findings left mid-fix by a process that is no longer running.

    "fixing" is claimed on disk but owned by an in-memory job, so a restart
    (an add-on update, a crash) orphans it: the row still says fixing, the
    job that would settle it is gone, and the tab offers no buttons in that
    status — the finding becomes permanently unreachable. Called at startup,
    which is the only moment we know for certain that nothing is in flight.

    `planning` is orphaned the same way and does NOT land in the same
    place. That run holds read-only tools, so a plan that died changed
    nothing in the house and there is nothing to report as failed: the row
    goes back to `open` with the button it came from, where `fixing` has to
    say out loud that something may have been half-done. Two statuses, two
    honest answers — the whole reason they are two words.
    """
    items = _load()
    stuck = [f for f in items if f.get("status") in ("fixing", "planning")]
    for entry in stuck:
        if entry.get("status") == "planning":
            entry["status"] = "open"
            entry["settled_at"] = 0
            continue
        entry["status"] = "failed"
        entry["result"] = reason
        entry["settled_at"] = int(time.time())
    if stuck:
        _write(items)
    return len(stuck)


# What the house checks may take back. A row somebody has sent Claude at,
# or that Claude has changed, is theirs to end — a check clears only what
# is still simply *open*, or has not got there: a row waiting on triage
# and one triage held are both rows the homeowner has never answered, so
# a check that no longer reports the problem may take either back.
# `planned` is in here and `planning` is not, for the same reason `fixing`
# is not: a plan is a sentence about a problem, so if the check stops
# reporting the problem the plan is about nothing and the row should go —
# but a run in flight must not have its row deleted out from under it.
CLEARABLE = ("open", "planned", "needs_you", "failed", "triaging", "held")


@_mutates
@_mutates
def clear_source(source: str) -> list[dict]:
    """Take every row a producer has filed off the list, because the
    homeowner has muted that producer.

    The press's half of "Stop raising these": `triage.gate` drops what the
    producer files from now on, and this removes what it has already
    filed. Only rows nobody has acted on — `open`, `triaging`, `held`,
    `needs_you` — and never `fixing` or `fixed`, which are a conversation
    somebody is already having or a change brAIn already made. Nothing is
    settled and no memory line is written: a mute is a statement about
    the RULE and not about the house, which is `clear_resolved`'s reason
    for writing nothing when a problem goes away on its own. Returns the
    rows taken, shaped, so the toast can say how many.
    """
    items = _load()
    taken: list[dict] = []
    kept: list[dict] = []
    for entry in items:
        if (str(entry.get("source") or "") == source
                and entry.get("status") in MUTE_CLEARS):
            taken.append(_shape(entry))
        else:
            kept.append(entry)
    if taken:
        _write(kept)
    return taken


@_mutates
def set_fix(ts: int, fix: str, by: str) -> dict | None:
    """Replace what a row says to do, and record who said it.

    The chat's door onto "What you'd need to do": a discussion that has
    worked out the specific answer offers it as an option, and the press
    lands here. It settles nothing and takes nothing away — the row stays
    exactly where it was with a better sentence on it — which is why it
    hands back no undo token. Refuses an empty sentence and an author the
    row cannot name (`FIX_AUTHORS`); answers None for a row that is gone.
    """
    fix = str(fix or "").strip()[:MAX_FIX]
    if not fix or by not in FIX_AUTHORS:
        return None
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) == int(ts):
            entry["fix"] = fix
            entry["fix_by"] = by
            _write(items)
            return _shape(entry)
    return None


def source_titles() -> dict[str, str]:
    """Every producer this store has seen, id → the title it filed under.

    Live rows first, then the settled ledger, so a muted producer whose
    rows are all gone can still be named on the tab rather than shown as
    `check:dev.frozen`. A producer nothing has recorded a title for is
    simply absent; the caller falls back to the id.
    """
    out: dict[str, str] = {}
    for entry in _load_settled():
        src = str(entry.get("source") or "")
        title = str(entry.get("source_title") or "")
        if src and title and src not in out:
            out[src] = title
    for entry in _load():
        src = str(entry.get("source") or "")
        title = str(entry.get("source_title") or "")
        if src and title:
            out[src] = title
    return out


# What a mute takes off the list: everything nobody has acted on. `fixing`
# and `fixed` are a person's or the fixer's and stay.
MUTE_CLEARS = ("open", "triaging", "held", "needs_you")


def refresh_details(objs: list[dict]) -> int:
    """Update the detail and severity of rows a producer has re-reported.

    A check's finding text is stable on purpose (the store dedupes by it),
    which leaves the number that changes — days left, since when — in
    ``detail``. Re-reporting through :func:`add_many` drops the row as
    known; this is the other half, so a battery forecast filed a week ago
    says "about 2 days" today rather than "about 9". Returns how many rows
    changed.
    """
    items = _load()
    by_key = {normalize(f.get("text", "")): f for f in items}
    changed = 0
    for obj in objs:
        entry = coerce(obj)
        if entry is None:
            continue
        cur = by_key.get(normalize(entry["text"]))
        if cur is None or cur.get("status") not in CLEARABLE:
            continue
        if (cur.get("detail") != entry["detail"]
                or cur.get("severity") != entry["severity"]):
            cur["detail"] = entry["detail"]
            cur["severity"] = entry["severity"]
            changed += 1
    if changed:
        _write(items)
    return changed


@_mutates
def mark_checked(texts, when: float | None = None) -> int:
    """Stamp `checked_at` on the live rows a re-check just re-reported.

    "Check again" had exactly one visible outcome when the answer was
    *still there*: a toast, which is gone in four seconds and leaves the
    card looking untouched — so the press read as having done nothing,
    which is what was reported. The row itself has to carry it, because
    the useful fact is not that a button was pressed but that **this
    problem was true a minute ago**, which is a different claim from a
    row filed on Tuesday and never looked at since.

    Only that press writes it. A scheduled pass re-confirms every open
    row every few hours, so stamping there would put "checked just now"
    under a card nobody has looked at and the line would stop meaning
    anything — the same reason `clear_resolved` writes no memory line.
    """
    when = time.time() if when is None else when
    wanted = {normalize(t) for t in texts if normalize(t)}
    if not wanted:
        return 0
    items = _load()
    changed = 0
    for entry in items:
        if (normalize(entry.get("text", "")) in wanted
                and entry.get("status") in CLEARABLE):
            entry["checked_at"] = int(when)
            changed += 1
    if changed:
        _write(items)
    return changed


def resolve_clear(items: list[dict], sources: set[str],
                  keep_keys: set[str]) -> tuple[list[dict], list[dict]]:
    """Split rows into what survives a pass and what that pass cleared.

    Pure over a list, so the shadow store can hold the *same* rule rather
    than a copy of it: a shadow check earning its place has to clear
    exactly the way a real one does, or the two numbers being compared are
    measuring different lifecycles. :func:`clear_resolved` is this against
    the real store; ``shadow_findings.clear_resolved`` is it against the
    other one.
    """
    kept: list[dict] = []
    gone: list[dict] = []
    for f in items:
        if (f.get("source") in sources
                and f.get("status") in CLEARABLE
                and normalize(f.get("text", "")) not in keep_keys):
            gone.append(_shape(f))
            continue
        kept.append(f)
    return kept, gone


@_mutates
def clear_resolved(sources: set[str], keep_keys: set[str]) -> list[dict]:
    """Drop open rows a producer no longer reports.

    A device that came back, a battery that was changed, an automation
    that was fixed by hand without anyone pressing the button: the check
    that filed it stops finding it, and the row should go rather than sit
    on the list until somebody presses "I did it" about a thing that is
    fine. Only rows from ``sources`` (the checks that actually RAN this
    pass — a check whose data was missing must not clear anything) and
    only rows still in a clearable status.

    Nothing is written to the settled ledger and no memory line is
    queued: a problem that went away on its own is not a fact about the
    house, and if it comes back the check files it again. Returns the
    rows that were removed.
    """
    kept, gone = resolve_clear(_load(), sources, keep_keys)
    if gone:
        _write(kept)
    return gone


@_mutates
def remove(ts: int) -> bool:
    items = _load()
    kept = [f for f in items if int(f.get("ts") or 0) != ts]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True


@_mutates
def restore(shaped: dict) -> dict | None:
    """Put a row back exactly as it was — the undo half of an ending.

    Keyed on the original ``ts``, because that is the id the panel acted on
    and a restored finding that came back under a new one would be a
    different card to everything holding a reference to it (the chat's
    action strip, a pending undo, an open menu).

    Refuses when something already occupies that id: the analyst re-reporting
    the problem in the meantime is the one case where the row on the list is
    newer than the one being restored, and overwriting it would throw away
    whatever has happened since.
    """
    ts = int(shaped.get("ts") or 0)
    if not ts or not str(shaped.get("text") or "").strip():
        return None
    items = _load()
    if any(int(f.get("ts") or 0) == ts for f in items):
        return None
    entry = {k: v for k, v in _shape(shaped).items()}
    items.append(entry)
    _write(_prune(items))
    return _shape(entry)


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def prompt_block() -> str:
    """What the analyst needs to know about findings before it reports more.

    Three lists, all cheap and all load-bearing: what is already reported
    (so three cards don't all raise the same dead battery), what the
    homeowner has explicitly waved off (so it stays waved off), and what
    they have already dealt with (so a finished job is not handed back).

    The last two come from the settled ledger rather than the list, because
    settling deletes the row — plus any legacy row still carrying a settled
    status from before the ledger existed.

    Where a dismissal carries the homeowner's reason, the reason is rendered
    with it. That is the part worth the tokens: a key stops one wording, and
    "the porch sensor watches the compressor, it is meant to sit on" stops
    every report built on the same wrong assumption.
    """
    everything = list_all()
    live = [f for f in everything if f["status"] in LIVE_STATUSES][:PROMPT_OPEN]

    def _settled(kind: str, limit: int) -> list[tuple[str, str]]:
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for text, note in ([(e.get("text", ""), str(e.get("note") or ""))
                            for e in settled_listing() if e.get("kind") == kind]
                           + [(f["text"], "") for f in everything
                              if f["status"] == kind]):
            key = normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append((text, note.strip()[:MAX_NOTE]))
            if len(out) >= limit:
                break
        return out

    ignored = _settled("ignored", PROMPT_IGNORED)
    fixed = _settled("fixed", PROMPT_FIXED)
    parts: list[str] = []
    if live:
        parts.append(
            "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT report these again:")
        parts += [f"- {f['text']}" for f in live]
    if ignored:
        parts.append(
            "\nPROBLEMS THE HOMEOWNER SAID WERE WRONG OR NOT PROBLEMS HERE — "
            "never raise them again, in any wording. Where they said why, that "
            "reason is about this house and holds beyond the one report: take "
            "it into account in what you look at next, rather than only "
            "avoiding these words:")
        parts += [f"- {t}" + (f"\n  They said: {n}" if n else "")
                  for t, n in ignored]
    if fixed:
        parts.append(
            "\nPROBLEMS THE HOMEOWNER HAS ALREADY DEALT WITH — do not raise "
            "them again unless the data shows they have come back:")
        parts += [f"- {t}" for t, _ in fixed]
    return "\n".join(parts)
