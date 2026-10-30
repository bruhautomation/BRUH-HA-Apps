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


import datetime as dt
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
import house_words
import personality
import textclip
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
# Per-row cap on the prose in the mirror. See `_publish_state`.
STATE_MAX_PROSE = 240

MAX_FINDINGS = 200
# The mirror carries the WHOLE live list, which the store already caps.
# It was the newest 50, which was plenty for a sensor attribute and wrong
# for everything else that reads the file: Repairs raises the OLDEST rows
# waiting on somebody and could never see them on a busy house, and a row
# falling off the cut read to the integration's watcher as a case that had
# ended — `brain_case_ended`, then `brain_case` again when a newer row
# was settled and it came back on. Bounded by the store's own cap rather
# than by a second number, so the two cannot disagree about what is live.
STATE_MAX_ROWS = MAX_FINDINGS
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
# Every item a row about several things names (`items`): the entities, or
# `device:<id>` for a device with none, that one Wrong answers. Kept apart
# from `evidence`, which is what a card shows and is capped at a handful.
MAX_ITEMS = 200
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
# The strings a model row carried that only a developer reads (#563).
MAX_TECHNICAL = 8
MAX_TECHNICAL_CHARS = 200

# The imperative sentence To Do shows for this row ("Replace the battery in
# the hallway motion sensor."): what needs doing, naming the thing — never
# the claim, never a question (Morph's contract B). Written by the producer
# that filed the row when it can (a check, from its `fix` and the friendly
# name; the Resident's case, `todo_text` in its schema, rewritten by
# `refine`), and derived on read when it could not (`todo_text_of`). Absent
# on a row that carries none, `_case_fields`' rule, so a row filed before it
# existed is the dict it always was.
MAX_TODO_TEXT = 200
# A case's conversation (Morph's reply line): the person's words and brAIn's
# answers, newest last. Capped in turns and in each turn's length, because
# the row is rewritten on every store write and a thread is a few lines on
# a card, never a transcript.
MAX_THREAD_TURNS = 12
MAX_THREAD_TEXT = 600
THREAD_WHO = ("you", "brain")
# A Morph suggestion's own key (`morph_case`), kept on the row so Morph can
# find its own suggestion again and be told how it ended.
MAX_MORPH_KEY = 64

# What an ending can say. `fixed` and `ignored` are the two the tab has
# always had; `accepted` is the third and it is a different claim from
# both — the report was right AND the work is not done yet, which is what
# moving a card to the to-do list means. It has to be its own word for two
# reasons: the scorecard counts it as the report being confirmed (agreeing
# to do something is agreeing it is real), and completing the chore later
# re-settles the same key as `fixed`, which is an upgrade a shared word
# could not express.
# `not_applicable` is the fourth and it is no claim at all: a question
# somebody said does not fit this house ("Doesn't apply"). It suppresses the
# same text for good (`_suppresses` reads any word it does not recognise as
# permanent) and labels nothing — the scorecard, the outcome join and History
# all pass over it, because an irrelevant question is neither right nor wrong.
SETTLE_KINDS = ("fixed", "ignored", "accepted", "not_applicable")

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
# The live rows about what a card covers (`prompt_block`'s ``covers``) go
# first, and up to this many of them, whatever else is on the list: the row
# about a card's own device is the one it must agree with.
PROMPT_COVERED = 24
# How much of a live row's detail a card is shown: its figures and window,
# not its whole evidence.
PROMPT_DETAIL = 240
PROMPT_IGNORED = 20
PROMPT_FIXED = 20
# What the household turned down about what a card covers, listed apart
# and outside the newest-twenty cut (`prompt_block`'s ``covers``).
PROMPT_TURNED_DOWN = 12
# A card's finding or opportunity naming the entity of a settled Wrong is
# the same thing said again when it carries this share of that Wrong's
# words (`turned_down`).
TURNED_DOWN_SHARE = 0.5
_TURNED_DOWN_STOP = frozenset(
    "the a an and or of to is it its on in at for from this that with be "
    "been has have was were are by as so if when".split())

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
    if not isinstance(items, list):
        return []
    # A row filed before `as_asked` existed is read the way it would be
    # filed now, so the next write stores it so: the migration is the read.
    return [as_asked(f) for f in items if isinstance(f, dict)]


# ---------------------------------------------------------------------------
# A question brAIn asks
# ---------------------------------------------------------------------------
#
# A model-written row that IS a question the assistant asks — "Vesper asks:
# why does the porch light come on at 3am?", "Still open from an earlier
# conversation" — was filed as a problem: listed among the faults on the
# Findings tab and by `get_findings`, with To Do and Ignore under it and
# nowhere to type an answer. Such a row is filed without its "<name> asks:"
# prefix as a `question`, marked `asked`; Needs you reads it under
# Questions for you with a typed answer that goes to the memory inbox
# (`server.h_question_answer`), and `get_findings` leaves it out.
_ASKS_RE = re.compile(r"^\s*(?P<who>[^:\n]{1,40}?)\s+asks\s*:\s*(?P<q>\S.*)$",
                      re.S)


def _assistant_names() -> set[str]:
    names = {"brain"}
    try:
        # Read per call: the name is a switch the household can flip.
        names.add(str(personality.assistant_name() or "").strip().casefold())
    except Exception:  # noqa: BLE001 — no name is brAIn's own
        pass
    return names - {""}


def asked_question(text) -> str:
    """The question in ``text`` when it is one the assistant asks
    ("<its name> asks: …"), without the prefix; "" otherwise."""
    m = _ASKS_RE.match(str(text or ""))
    if not m or m.group("who").strip().casefold() not in _assistant_names():
        return ""
    return m.group("q").strip()


def as_asked(row: dict) -> dict:
    """``row`` as a question the assistant asks, when its text or claim is
    one; otherwise ``row`` itself, untouched."""
    if not isinstance(row, dict):
        return row
    if row.get("asked") is True:
        return row
    text_q = asked_question(row.get("text"))
    claim_q = asked_question(row.get("claim"))
    if not (text_q or claim_q):
        return row
    out = dict(row)
    if text_q:
        out["text"] = text_q
    if claim_q:
        out["claim"] = claim_q
    out["kind"] = "question"
    out["asked"] = True
    return out


def _write(items: list[dict]) -> None:
    atomic_write.write_json(FINDINGS_FILE, {"findings": items})
    # Every write republishes the shared-volume mirror, so the two can never
    # drift: there is no code path that changes the store without it.
    _publish_state(items)
    _written()


# Told after every store write, for a reader that republishes something of
# its own from the store (the panel's Morph `cases.json`, which cannot be
# built here: it reads all four stores through `cases`, which reads this
# one). A flag-setter, never the publish itself — a write must not wait on
# four stores being read — and never raised: a mirror is not the store.
ON_WRITE = None


def _written() -> None:
    hook = ON_WRITE
    if hook is None:
        return
    try:
        hook()
    except Exception as exc:  # noqa: BLE001
        log.debug("the store's write hook failed: %s", exc)


def _urgent(row: dict) -> bool:
    """`urgency.is_urgent` (a leaf, so no import ring with the notifier),
    never raising: a mirror row that could not be judged is an ordinary
    one."""
    try:
        import urgency  # noqa: PLC0415 — panel-local
        return bool(urgency.is_urgent(row))
    except Exception:  # noqa: BLE001
        return False


# THE count is the queue's (`cases.queue_count`, plus Today's own cards in
# the panel's `_queue_count`): findings, questions and suggestions. This
# module cannot ask it — `cases` reads this store — so the panel hands the
# callable in at import. Unset (a test, a tool), the mirror's `open` is the
# findings alone, which is what it always was; either way the findings
# alone ride beside it as `findings_open`, under their own name.
QUEUE_COUNT = None

# What a producer is CALLED when the title it filed under says nothing. An
# asked card files under its own id (`custom-…`) and, until 2.17.7, under the
# word "Custom" — which is where the card came from and nothing a person
# can find again; rows and ledger entries written then still carry it. The
# panel knows the card (this module does not read insights), so it hands a
# resolver in, `QUEUE_COUNT`'s arrangement: `(source, title) -> title`.
SOURCE_TITLE = None
_NO_TITLE = ("", "Custom")


def _check_title(source: str) -> str:
    """A house check's own catalog title, or "" — the one name a rule has
    (#439). A check row is filed under its GROUP's word ("Device check"),
    which names a dozen rules at once: the useful battery rule and the
    impossible-readings rule read the same, and a question about stopping
    one could not say which."""
    if not str(source or "").startswith("check:"):
        return ""
    try:
        import checks  # noqa: PLC0415 — the catalog, read lazily
        spec = checks.get_check(str(source)[len("check:"):]) or {}
    except Exception:  # noqa: BLE001 — a label, never the read
        return ""
    return str(spec.get("title") or "")


def _rule_titled(source: str, title: str) -> str:
    """`_titled`, with a check named by its own catalog title — what the
    scorecard and `source_titles` (the mute question, the fault list,
    History's muted rows) call a rule."""
    return _check_title(source) or _titled(source, title)


def _titled(source: str, title: str) -> str:
    """The title a reader shows for `source`, never the bare "Custom"."""
    title = str(title or "")
    if title.strip() in _OLD_RESIDENT_TITLES and str(source) == RESIDENT_SOURCE:
        return RESIDENT_TITLE
    if title.strip() not in _NO_TITLE or not str(source).startswith("custom-"):
        return title
    resolver = SOURCE_TITLE
    if resolver is None:
        return title
    try:
        named = resolver(str(source), title)
    except Exception as exc:  # noqa: BLE001 — a label, never the read
        log.debug("could not name %s: %s", source, exc)
        return title
    return str(named or title)[:120]


# A model-written row in the words the house uses (`house_words`): an id
# the house has a name for becomes the name, a UTC time becomes the house's
# local one, the add-on's Supervisor slug becomes "brAIn". The panel holds
# the names map and the zone, so it hands both in, `QUEUE_COUNT`'s
# arrangement: `DISPLAY_NAMES() -> {entity_id: name | {"name": ...}}` and
# `HOUSE_TZ() -> tzinfo`. Unset (a test, a tool), only the slug is changed.
DISPLAY_NAMES = None
HOUSE_TZ = None
# Model-written sources whose words are left alone: a person's correction is
# their words, and the safety lane and the tripwire are written by code
# (the tripwire's card must never name its entity).
PLAIN_EXEMPT = frozenset({"correction", "safety", "security", "self_care"})
# Who brAIn is here, the one stored answer (`personality.identity`):
# `IDENTITY() -> {"name", "voice"}`, handed in by the panel. A model's
# sentence about brAIn's voice reads it (`house_words.self_said`); unset,
# the name is "brAIn" and no voice is recorded.
IDENTITY = None
# A model's row telling the owner to change a line of brAIn's own
# instructions, as the yes/no question brAIn asks itself (`self_care.
# as_question`): `SELF_CARE(obj) -> fields | None`, handed in by the panel.
SELF_CARE = None


def _model_written(source: str) -> bool:
    """A producer whose sentences a model wrote: no colon, not exempt."""
    source = str(source or "")
    return bool(source) and ":" not in source and source not in PLAIN_EXEMPT


def _names_now() -> dict:
    hook = DISPLAY_NAMES
    if hook is None:
        return {}
    try:
        return dict(hook() or {})
    except Exception as exc:  # noqa: BLE001 — a nicer sentence, never the write
        log.debug("could not read the names map: %s", exc)
        return {}


def _tz_now():
    hook = HOUSE_TZ
    if hook is None:
        return None
    try:
        return hook()
    except Exception as exc:  # noqa: BLE001
        log.debug("could not read the house's zone: %s", exc)
        return None


def _identity_now() -> dict:
    hook = IDENTITY
    if hook is None:
        return {"name": "brAIn", "voice": ""}
    try:
        got = hook() or {}
        return {"name": str(got.get("name") or "brAIn"),
                "voice": str(got.get("voice") or "")}
    except Exception as exc:  # noqa: BLE001 — a nicer sentence, never the write
        log.debug("could not read brAIn's identity: %s", exc)
        return {"name": "brAIn", "voice": ""}


def _self_care(obj: dict) -> dict | None:
    hook = SELF_CARE
    if hook is None:
        return None
    try:
        return hook(obj)
    except Exception as exc:  # noqa: BLE001 — the row stays a finding
        log.debug("could not read a row as brAIn's own upkeep: %s", exc)
        return None


def plain(text: str, names: dict | None = None, tz=None) -> str:
    """`house_words.plain` with the panel's names and zone when not handed."""
    if not isinstance(text, str) or not text:
        return text
    return house_words.plain(
        text, names if names is not None else _names_now(),
        tz if tz is not None else _tz_now())


def _plain_row(row: dict, keys=("claim", "detail", "fix", "todo_text")) -> dict:
    """A copy of a model-written row with `keys` in the house's words.

    `text` is in `keys` only where the caller says: it is the dedupe key,
    and for a check — or anything a person or code wrote — it is left
    exactly as its producer wrote it."""
    if not isinstance(row, dict) or not _model_written(row.get("source")
                                                      or RESIDENT_SOURCE):
        return row
    names, tz = _names_now(), _tz_now()
    who = _identity_now()
    # A row about brAIn itself also loses its developer words: a path, a
    # tool, an id, a model id (`house_words.self_said`).
    dev = house_words.about_self(*(row.get(k) for k in
                                   ("text", "claim", "detail", "fix")))
    agree = house_words.readings_agree(row.get("evidence"))
    out = dict(row)
    # What only a developer reads — a path, a tool's name, a hex code, a
    # build string — leaves the sentence for `technical`, which the card
    # shows under Details (#563). Collected off the words as written,
    # before the passes below drop a sentence that held one.
    technical = clean_technical(row.get("technical"))
    for key in keys:
        if isinstance(out.get(key), str) and out[key]:
            for token in house_words.technical(out[key])[1]:
                if token not in technical:
                    technical.append(token)
            out[key] = plain(out[key], names, tz)
            # One narrator, one stored answer for its voice.
            out[key] = house_words.self_said(
                out[key], who["name"], who["voice"], dev=dev,
                keep=key == "text")
            # Urgent only when two readings agree (`house_words.calm`).
            out[key] = house_words.calm(out[key], agree)
            # A step or an account holding a hole where a value belongs
            # ("a template", "<entity>", "TODO") is refused and the row
            # keeps what it had (#446): `refine` writes nothing over an
            # empty value, and a new row simply has none.
            if key in PLACEHOLDER_REFUSED and house_words.placeholder(
                    out[key]):
                out[key] = ""
            # So is a step that hands the choice back ("either … or",
            # "also confirm …", "if asked", #536): the account in `detail`
            # may weigh two causes, the step a person carries out may not.
            if key in FORK_REFUSED and house_words.fork(out[key]):
                out[key] = ""
            out[key] = house_words.technical(out[key])[0]
            # The household is "you", the dashboard the dashboard (#562).
            out[key] = house_words.household(out[key])
    technical = clean_technical(technical)
    if technical:
        out["technical"] = technical
    return out


def clean_technical(value) -> list[str]:
    """A row's technical details (`house_words.technical`): short strings,
    at most `MAX_TECHNICAL`, or []."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and len(out) < MAX_TECHNICAL:
            token = item.strip()[:MAX_TECHNICAL_CHARS]
            if token not in out:
                out.append(token)
    return out


# The fields a placeholder is refused in.
PLACEHOLDER_REFUSED = ("detail", "fix", "todo_text")
# The fields an unresolved fork is refused in: the steps.
FORK_REFUSED = ("fix", "todo_text")


def _queue_now(now: float) -> int | None:
    counter = QUEUE_COUNT
    if counter is None:
        return None
    try:
        value = counter(now)
    except Exception as exc:  # noqa: BLE001 — a mirror field, not the write
        log.debug("findings mirror could not count the queue: %s", exc)
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


def _outside_view(row: dict, assistant: str) -> dict:
    """What Home Assistant shows of this row so it reads as the card on
    Needs you (#452): the card's own title and its who-acts line
    (`answers.request_view` — one derivation for the card and the dialog).
    The presses ride on the row as `answers`, each label off
    `answers.REQUEST_LABELS`."""
    view = answers.request_view(row, assistant)
    out = {}
    if view["title"]:
        out["title"] = view["title"]
    if view["who"]:
        out["who"] = view["who"]
        out["who_kind"] = view["who_kind"]
    return out


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
    # Snoozed rows ride in a key of their own rather than in `findings`.
    # Every reader of `findings` — the open count, the to-do list, Repairs —
    # is right to leave a dismissed row out, and a reader that predates the
    # key never sees one; what needs them is the watcher, which otherwise
    # reads Dismiss as the case ENDING (`brain_case_ended`) and the row's
    # return a day later as a brand-new problem (`brain_case` and
    # `brain_finding` again, ringing whatever an automation hung off them).
    snoozed = [s for s in shaped
               if s["status"] in LIVE_STATUSES and is_snoozed(s, now)]
    # A row a look has not reached in `triage.SHOW_AFTER_S` is counted
    # with the open ones — the sensor saying 0 over a serious row nothing
    # has looked at for half an hour is the "nothing waiting on you" lie.
    # It is counted and not listed: `findings` is what the watcher fires
    # events and raises Repairs issues from, and those wait for a verdict.
    waiting = [s for s in shaped if triage.waiting_too_long(s, now)]
    open_rows = [s for s in live if s["status"] in UNSETTLED_STATUSES] + waiting
    queue = _queue_now(now)
    assistant = personality.assistant_name()
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(STATE_FILE, {
            "ts": int(now),
            # The household's name for the assistant, for the sentences
            # Home Assistant builds about it (the Repairs dialog), and what
            # every press is called — the one table (`answers.REQUEST_LABELS`)
            # the dialog's menu reads its words from.
            "assistant": assistant,
            "labels": dict(answers.REQUEST_LABELS),
            # How each live row reads on Needs you — its title and its
            # who-acts line — keyed by ts beside the rows rather than in
            # them, so a row keeps the wire shape every reader has read.
            "views": {str(s["ts"]): _outside_view(s, assistant)
                      for s in live[:STATE_MAX_ROWS]},
            "open": len(open_rows) if queue is None else queue,
            "findings_open": len(open_rows),
            "waiting_look": len(waiting),
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
                 "detail": textclip.shorten(s["detail"], STATE_MAX_PROSE),
                 "fix": textclip.shorten(s["fix"], STATE_MAX_PROSE),
                 # The presses this row can be given from outside the
                 # panel, `[{action, label}]`, decided by the same table
                 # the feed renders from. Repairs shows this subset and
                 # a notification's buttons are these, so a battery is
                 # *Add to to-do · Replaced it · Not a problem* on every
                 # surface rather than three different questions.
                 "answers": answers.request_answers(s),
                 **{k: s[k] for k in ("kind", "claim") if s.get(k)},
                 # An Urgent card (`notify_router.is_urgent`): the
                 # integration raises a Repairs entry for it ahead of
                 # anything else on that page. Only on a row that is one,
                 # so an ordinary mirror is the file it always was.
                 **({"urgent": True} if _urgent(s) else {})}
                for s in live[:STATE_MAX_ROWS]
            ],
            # The same compact shape the watcher's events are built from,
            # plus when each comes back. No answers: a dismissed row is not
            # asking anything until it returns to `findings`.
            "snoozed": [
                {**{k: s[k] for k in ("ts", "text", "severity", "status",
                                      "entity_id", "fixable", "source_title")},
                 "snoozed_until": int(s.get("snoozed_until") or 0),
                 **{k: s[k] for k in ("kind", "claim") if s.get(k)}}
                for s in snoozed[:STATE_MAX_ROWS]
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
# A step is an op written out (`plan_ops.describe`), and an agentic step names
# its instruction plus every call and file it may touch — so it is allowed
# the length of the instruction and its reach, not one line.
MAX_PLAN_STEP = 1600
MAX_PLAN_RISK = 300
MAX_PLAN_SUMMARY = 900


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
            steps.append(textclip.clip(item.strip(), MAX_PLAN_STEP))
        if len(steps) >= MAX_PLAN_STEPS:
            break
    needs_you = bool(value.get("needs_you"))
    out = {
        # Mutually exclusive by definition, the same way `fixer.parse_result`
        # reads them: a fix that needs hands is not one software can make.
        "can_fix": bool(value.get("can_fix")) and not needs_you,
        "needs_you": needs_you,
        "steps": steps,
        "risk": textclip.clip(str(value.get("risk") or "").strip(), MAX_PLAN_RISK),
        "summary": textclip.shorten(str(value.get("summary") or "").strip(), MAX_PLAN_SUMMARY),
        "at": int(value.get("at") or 0),
    }
    # The typed half — the ops Apply carries out, re-validated on every
    # read because Apply reads them off this row (`plan_ops.clean_stored`).
    # A plan with no ops that still says `can_fix` was written before plans
    # were contracts: it is not something to approve, and it says why,
    # rather than offering an Apply that would carry out prose.
    import plan_ops  # noqa: PLC0415 — the store keeps no import of policy

    typed = plan_ops.clean_stored(value)
    out.update(typed)
    out.setdefault("ops", [])
    if out["can_fix"] and not typed.get("ops"):
        out["can_fix"] = False
        out["ops_refused"] = typed.get("ops_refused") or plan_ops.LEGACY_PLAN
    return out


def echoes(reason, *texts) -> bool:
    """Whether a look's ``reason`` only repeats the row it is about.

    A reason is what a look CONCLUDED, and the card prints it under
    "brAIn checked". One identical (normalised) to the row's own text or
    claim concluded nothing: it is the finding read back to its reader,
    and printed under that label it says a review happened and wrote a
    conclusion when neither the sentence nor the run said anything new.
    So it is not a reason, and a reader of the block treats it as none.
    """
    said = normalize(str(reason or ""))
    if not said:
        return False
    return any(said == normalize(str(t or "")) for t in texts if t)


def without_echo(record: dict, entry: dict) -> dict:
    """``record`` (a cleaned triage block) with an echoing reason blanked.

    For the surfaces a person reads. Stored rows written before the echo
    rule (a Resident case stamps its claim as the verdict that wrote it)
    keep the field; what is shown is the honest line with no reason.
    """
    if not isinstance(record, dict) or not record.get("reason"):
        return record
    if echoes(record["reason"], (entry or {}).get("text"),
              (entry or {}).get("claim")):
        return {**record, "reason": ""}
    return record


# A look's sentence that describes where the row is rather than the house:
# "already in front of the homeowner", "already on their list", "already
# filed". A real house had five cards saying that under "brAIn checked" —
# brAIn's own routing read back to the one person who can see the row is
# on the list, which is no judgement at all. Whole sentences (and clauses
# after a semicolon) go, so a reason that also says why it can wait keeps
# that half.
_ROUTING_RE = re.compile(
    r"\b(?:in front of (?:the )?(?:homeowner|owner|person|user|them)"
    r"|already (?:(?:been )?(?:filed|raised|reported|listed|surfaced|shown"
    r"|flagged|queued|tracked|known|told)"
    r"|(?:on|in) (?:the|their|your|a) (?:list|queue|feed|tab|screen))"
    r"|(?:is|are|sits?) (?:already )?(?:on|in) (?:the|their|your) "
    r"(?:list|queue|feed)"
    r"|has (?:already )?been told about)\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


def house_reason(reason) -> str:
    """What a look's ``reason`` says about the HOUSE, for a card to show.

    The stock silence sentences (`triage.UNJUDGED`, `RUN_FAILED`,
    `WAITING`) say nothing was concluded, so they are no reason: a card
    carries an "Unchecked" mark instead and the queue counts them once.
    A sentence about where the row is listed is dropped too
    (`_ROUTING_RE`), and what is left is returned as written.
    """
    said = str(reason or "").strip()
    if not said:
        return ""
    if said in (triage.UNJUDGED, triage.RUN_FAILED, triage.WAITING,
                *triage.LEGACY_STOCK):
        return ""
    kept = [s for s in _SENTENCE_SPLIT_RE.split(said)
            if s.strip() and not _ROUTING_RE.search(s)
            and not triage.says_duplicate(s)]
    return " ".join(kept).strip()


_REASON_ENTITY_RE = re.compile(r"(?<![\w.])([a-z_]+)\.([a-z0-9_]+)(?![\w.])")


def _names_another_entity(reason, entry: dict) -> bool:
    """Whether a look's reason names an entity id the row is not about —
    neither its own entity nor one in its evidence. Such a reason was
    written about some other row, so it says nothing about this one. Only
    a token whose domain is one Home Assistant has counts: a file name or a
    version number is not an entity."""
    text = str(reason or "")
    if "." not in text:
        return False
    from checks._util import _CORE_DOMAINS  # noqa: PLC0415 — leaf, lazy
    own = {str(entry.get("entity_id") or "")}
    for ev in entry.get("evidence") or []:
        if isinstance(ev, dict):
            own.add(str(ev.get("entity") or ""))
    for m in _REASON_ENTITY_RE.finditer(text):
        if m.group(1) in _CORE_DOMAINS and m.group(0) not in own:
            return True
    return False


def _names_itself(reason, entry: dict) -> bool:
    """Whether a look's reason contains the row's own sentence — its text
    or claim, three words or more, normalised — rather than a conclusion
    about the house."""
    said = normalize(str(reason or ""))
    if not said:
        return False
    for text in ((entry or {}).get("text"), (entry or {}).get("claim")):
        own = normalize(str(text or ""))
        if len(own.split()) >= 3 and own in said:
            return True
    return False


def shown_look(record: dict, entry: dict) -> dict:
    """``record`` (a cleaned triage block) as a surface a person reads
    shows it: an echo blanked (`without_echo`) and the reason cut to what
    it says about the house (`house_reason`). The stored record is never
    changed — the look still decides what it is."""
    record = without_echo(record, entry)
    if not isinstance(record, dict) or not record.get("reason"):
        return record
    entry = entry if isinstance(entry, dict) else {}
    # A hold's reason argues the row should not be on the list. On a row
    # that stays open (a late verdict about a row silence already showed —
    # `late_verdict_welcome`) it is a sentence telling the reader the card
    # in front of them should not be there, so it is not shown; the
    # verdict stays on the record.
    # A row a PERSON put back is the other case: the hold's reason is what
    # they overruled, and saying it is the point.
    if (record.get("verdict") == "held" and entry.get("status") != "held"
            and not record.get("elevated_by_person")):
        return {**record, "reason": ""}
    if _names_another_entity(record["reason"], entry):
        return {**record, "reason": ""}
    # A reason that names the very row it is on ("<this row's title>, which
    # brAIn is following") reads the finding back with a word added, and
    # says nothing the card does not (#448).
    if _names_itself(record["reason"], entry):
        return {**record, "reason": ""}
    if quotes_other_counts(record["reason"], entry.get("detail")):
        # The check refreshed the row's numbers after the look wrote its
        # reason (`refresh_details`): "49 drops" beside a detail saying 36
        # is two answers on one card (#443). Not shown until a look writes
        # one about the row as it is — which costs no run of its own.
        return {**record, "reason": ""}
    said = house_reason(record["reason"])
    # A look's conclusion is a model's sentence a person reads: "you", and
    # no tool name, hex code or build string (#562, #563). A file name stays
    # (`tests/test_open_row_look_reason.py` holds it on screen).
    said = house_words.household(house_words.technical(said, files=False)[0])
    if said == record["reason"]:
        return record
    return {**record, "reason": said}


# Spelled here as well as in `house_book` because the store may not import
# it (house_book files through the store); a test holds the two equal.
_HOUSE_BOOK_OLD_FIX = "Answer it here and the house book will say so."
_HOUSE_BOOK_FIX = ("Your answer goes into the house book: the plain-language "
                   "guide brAIn writes for anyone looking after this house.")


def shown_fix(entry: dict) -> str:
    """The "what to do" a surface shows for ``entry``.

    A check writes one ``fix`` for every row of its kind, and it is often an
    errand — go and look at what it is measuring, check whether it is
    normal. Once a look has CONCLUDED about the row (a reason that says
    something about the house: not a stock silence, not an echo of the row,
    `shown_look`'s rule) that errand is the question the look already
    answered, and showing it under the look's conclusion sends the person
    off to do brAIn's work again. So a check's own sentence (``fix_by``
    empty) is not shown there: the look's sentence is what the card carries
    — its reason, and a fix only when a look or a person wrote one. The
    stored row is never changed; the rule's sentence stays its own.
    """
    entry = entry if isinstance(entry, dict) else {}
    fix = str(entry.get("fix") or "")
    if not fix or entry.get("fix_by"):
        return fix
    # A house-book question filed before its sentence changed said "Answer
    # it here", which reads as a promise of a box on every surface without
    # one (#502). Read as today's sentence; the row itself is untouched.
    if entry.get("source") == "house_book" and fix == _HOUSE_BOOK_OLD_FIX:
        return _HOUSE_BOOK_FIX
    if not str(entry.get("source") or "").startswith("check:"):
        return fix
    look = shown_look(_clean_triage(entry.get("triage")), entry)
    if isinstance(look, dict) and str(look.get("reason") or "").strip():
        return ""
    return fix


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
        "reason": textclip.shorten(str(value.get("reason") or "").strip(), triage.MAX_REASON),
        "run_id": str(value.get("run_id") or "").strip()[:64],
        "at": int(value.get("at") or 0),
        # Set when a person pressed "Bring it to the front" on a held row.
        # Kept beside the verdict rather than over it: the verdict is what
        # the run said, and overwriting it would lose the one piece of
        # evidence that triage got this one wrong.
        "elevated_by_person": bool(value.get("elevated_by_person")),
        # When the person did, so the card can say "You brought this back
        # on 3 Oct" rather than leaving the verdict's own date to stand in
        # for it. Zero on a row put back before the stamp existed.
        "elevated_at": int(value.get("elevated_at") or 0),
        # Whether the row's `fix` is the run's own sentence rather than
        # the generic one the rule filed. The text itself lives in `fix`,
        # where every reader of a finding already looks; this is the
        # record of who wrote it.
        "wrote_fix": bool(value.get("wrote_fix")),
        # Which look-rules judged it (`triage.LOOK_VERSION`). 0 is a
        # verdict given before the claim rule existed.
        "v": int(value.get("v") or 0),
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
            "value": textclip.clip(str(item.get("value") or "").strip(), MAX_EVIDENCE_VALUE),
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
        label = textclip.clip(str(item.get("label") or "").strip(), MAX_ACTION_LABEL)
        if shape not in ACTION_SHAPES or not label:
            continue
        out.append({
            "label": label,
            "shape": shape,
            "consent": item.get("consent", True) is not False,
            "detail": textclip.clip(str(item.get("detail") or "").strip(), MAX_ACTION_DETAIL),
        })
        if len(out) >= MAX_ACTIONS:
            break
    return out


# A sentence ends at "." or "!" — but not after "e.g.", "i.e.", "etc." or
# "vs.", which cut a fix off mid-thought ("Check the hub, e.").
_TODO_SENTENCE_RE = re.compile(
    r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\betc\.)(?<!\bvs\.)(?<=[.!?])\s+")
# A sentence that says what IS ("The battery is low.", "It is unplugged.")
# rather than what to DO. To Do is a list of errands, so a statement is not
# one: it is put after "Look at <name>:" instead of standing on its own.
_STATEMENT_RE = re.compile(
    r"^(?:the|it|its|it's|this|that|there|these|those|a|an|no|your|my|our)\b"
    r"|^[\w'’-]+(?:\s+[\w'’-]+){0,3}\s+(?:is|are|was|were|has been|have been)"
    r"\b", re.I)
_IMPERATIVE_RE = re.compile(
    r"^(?:add|adjust|ask|call|change|charge|check|clean|clear|close|confirm|"
    r"delete|disable|empty|enable|fill|fix|give|install|let|lock|look|make|"
    r"mark|move|open|pair|plug|power|put|re-?pair|re-?interview|reload|"
    r"remove|rename|replace|reset|restart|run|set|swap|take|tell|test|"
    r"tighten|top|try|turn|unlock|unplug|update|water|wipe|refill|reboot|"
    r"recharge|re-?add|re-?seat|reseat|tidy|top up|book|order|buy)\b", re.I)
_IT_RE = re.compile(r"\bit\b", re.I)
_ITS_RE = re.compile(r"\bits\b", re.I)
_NOTHING_RE = re.compile(r"^(?:nothing|no action|none)\b", re.I)


def clean_todo_text(value) -> str:
    """A To Do sentence as stored, or "" for anything that is not one.

    One line, capped, a capital first letter and a full stop where it had
    none. A question is not a chore — "Is the freezer meant to be off?" on
    a to-do list is a card that should have stayed a question — so a
    sentence ending in "?" is refused rather than stored.
    """
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()).strip(" -—:;,")
    if not text or text.endswith("?"):
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!…":
        text += "."
    return textclip.clip(text, MAX_TODO_TEXT)


def _display_name(entity_id: str, names: dict | None = None) -> str:
    """The friendly name the panel knows for an entity, or ""."""
    if not entity_id:
        return ""
    names = _names_now() if names is None else names
    row = names.get(entity_id)
    if isinstance(row, dict):
        return str(row.get("name") or "").strip()
    return str(row or "").strip() if isinstance(row, str) else ""


def is_statement(text: str) -> bool:
    """Whether a sentence says what is, rather than what to do."""
    text = " ".join(str(text or "").split())
    if not text or _IMPERATIVE_RE.match(text):
        return False
    return bool(_STATEMENT_RE.match(text))


def _with_name(sentence: str, name: str) -> str:
    """The sentence with its first "it"/"its" turned into the thing's name,
    or the name put in front when the sentence names nothing."""
    if not name or name.casefold() in sentence.casefold():
        return sentence
    # A label that already reads "the scene “before movie”" takes no second
    # "the" — "the the scene" was the garble on the house's list.
    the = "" if re.match(r"(?i)^the\b", name) else "the "
    if _ITS_RE.search(sentence):
        return _ITS_RE.sub(f"{the}{name}'s", sentence, count=1)
    if _IT_RE.search(sentence):
        return _IT_RE.sub(f"{the}{name}", sentence, count=1)
    body = sentence.rstrip(" .!")
    if len(body) > 1 and body[1:2].islower():
        body = body[0].lower() + body[1:]
    return f"{name}: {body}"


def derive_todo_text(row: dict, name: str = "") -> str:
    """The To Do sentence for a row that was filed without one.

    Deterministic and cheap, because it runs on every read of a row a
    producer could not word: the first sentence of `fix` that is an errand
    rather than a statement, with the first "it"/"its" turned into the
    thing's name ("Re-pair it" under the hall sensor is "Re-pair the Hall
    sensor."), and the name put in front when the sentence names nothing
    ("Garage node: reset the Z-Wave node."). A fix that says only what is
    wrong becomes "Look at <name>: <what is wrong>"; one that says nothing
    is needed, or none at all, is "Look at <friendly name>." — the one
    errand that is always true — and a row about no entity says what to
    look into in the row's own words.
    """
    if not isinstance(row, dict):
        return ""
    name = str(name or "").strip()
    eid = str(row.get("entity_id") or "").strip()
    fix = " ".join(str(row.get("fix") or "").split())
    sentences = [x.strip() for x in _TODO_SENTENCE_RE.split(fix) if x.strip()] \
        if fix else []
    statement = ""
    for first in sentences:
        if first.endswith("?"):
            continue
        if _NOTHING_RE.match(first):
            break
        if is_statement(first):
            statement = statement or first
            continue
        if statement and _IT_RE.search(first):
            # "The battery is low. Replace it." — the "it" is the battery,
            # not the thing, so the statement rides along to say what.
            body = statement.rstrip(" .!")
            body = body[0].lower() + body[1:] if body[1:2].islower() else body
            act = first.rstrip(" .!")
            if name and act[1:2].islower():
                act = act[0].lower() + act[1:]
            lead = f"{name}: " if name else ""
            cleaned = clean_todo_text(f"{lead}{act} — {body}")
        else:
            cleaned = clean_todo_text(_with_name(first, name))
        if cleaned:
            return cleaned
    what = name or eid
    if statement and what:
        body = statement.rstrip(" .!")
        if len(body) > 1 and body[1:2].islower():
            body = body[0].lower() + body[1:]
        return clean_todo_text(f"Look at {what}: {body}")
    if what:
        return clean_todo_text(f"Look at {what}")
    about = str(row.get("claim") or row.get("text") or "").strip()
    return clean_todo_text(f"Look into: {about}") if about else ""


def todo_item_text(item: dict, names: dict | None = None) -> str:
    """What To Do shows for an item already on the list.

    Items moved before findings carried a To Do sentence were filed under
    the finding's claim ("Hall battery is low"), which is a statement, not
    an errand; those are reworded on read from the item's own fix and the
    thing's name, and the stored text is never touched.
    """
    if not isinstance(item, dict):
        return ""
    text = " ".join(str(item.get("text") or "").split())
    if not text or not is_statement(text) or item.get("origin") == "hand":
        return text
    eid = str(item.get("entity_id") or "")
    better = derive_todo_text(
        {"fix": item.get("fix") or "", "entity_id": eid,
         "claim": item.get("claim") or text},
        _display_name(eid, names))
    if better and not better.startswith("Look at"):
        return better
    name = _display_name(eid, names)
    if name:
        body = text.rstrip(" .!")
        if body.casefold().startswith(name.casefold()):
            rest = body[len(name):].strip(" :-—,")
            return clean_todo_text(f"Look at {name}: it {rest}" if rest else f"Look at {name}") or text
        if len(body) > 1 and body[1:2].islower():
            body = body[0].lower() + body[1:]
        return clean_todo_text(f"Look at {name}: {body}") or text
    return text


def todo_text_of(row: dict, names: dict | None = None) -> str:
    """What To Do shows for this row: the producer's sentence, or one
    derived from its fix and the thing's friendly name."""
    if not isinstance(row, dict):
        return ""
    stored = clean_todo_text(row.get("todo_text"))
    if stored:
        return stored
    return derive_todo_text(
        row, _display_name(str(row.get("entity_id") or ""), names))


def clean_morph_key(value) -> str:
    """A Morph suggestion's key, or "" — letters, digits and `._:-` only,
    because it comes from another add-on and rides back out in a file."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > MAX_MORPH_KEY:
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9._:-]+", value) else ""


def _clean_thread(value) -> list[dict]:
    """A case's conversation as stored: the newest `MAX_THREAD_TURNS`
    turns, each `{who, text, at}` with `who` one of `THREAD_WHO`, plus a
    brAIn turn's optional `tell` — a change it handed to Morph's Tell
    (`{"kind": "dashboard"|"code", "text": ...}`)."""
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for turn in value:
        if not isinstance(turn, dict) or turn.get("who") not in THREAD_WHO:
            continue
        text = textclip.clip(" ".join(str(turn.get("text") or "").split()),
                             MAX_THREAD_TEXT)
        if not text:
            continue
        at = turn.get("at")
        clean = {"who": turn["who"], "text": text,
                 "at": int(at) if isinstance(at, (int, float))
                 and not isinstance(at, bool) else 0}
        tell = turn.get("tell")
        if (turn["who"] == "brain" and isinstance(tell, dict)
                and tell.get("kind") in ("dashboard", "code")):
            words = textclip.clip(" ".join(str(tell.get("text") or "").split()),
                                  MAX_THREAD_TEXT)
            if words:
                clean["tell"] = {"kind": tell["kind"], "text": words}
        out.append(clean)
    return out[-MAX_THREAD_TURNS:]


# The thread's one cleaner, for a reader that keeps a thread of its own (the
# panel's side thread for a case with no findings row).
def clean_thread(value) -> list[dict]:
    return _clean_thread(value)


_INTEGRATION_RE = re.compile(r"^[a-z0-9_]{1,64}$")
MAX_ABOUT = 8


def _subject_fields(entry: dict) -> dict:
    """What a row is about beyond its one entity, only where it says.

    ``integration`` is the domain of an integration the row is about AS A
    WHOLE (the UniFi integration losing its controller, an integration
    logging an error that names nothing of its own) — the key every check
    that saw the same outage is folded on (`_fold_devices`). ``about`` is
    the entities a row names that its evidence does not (the overnight
    check's evidence names its records), which the returned-device sweep
    reads (`clear_returned`). Absent rather than empty, `_case_fields`'
    rule."""
    out: dict = {}
    integration = str(entry.get("integration") or "").strip()
    if _INTEGRATION_RE.match(integration):
        out["integration"] = integration
    about = []
    for e in entry.get("about") or []:
        e = _entity_shaped(e) if isinstance(e, str) else ""
        if e and e not in about:
            about.append(e)
    if about:
        out["about"] = about[:MAX_ABOUT]
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
    # A question the assistant asks (`as_asked`): answered in words.
    if entry.get("asked") is True and kind == "question":
        out["asked"] = True
    # A note (`triage.is_note`): news to read, answered with Got it. Only a
    # literal True, so nothing on the wire can set it by being truthy.
    if entry.get("informational") is True:
        out["informational"] = True
    claim = textclip.shorten(str(entry.get("claim") or "").strip(), MAX_CLAIM)
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
    hint = textclip.clip(str(entry.get("memory_hint") or "").strip(), MAX_MEMORY_HINT)
    if hint:
        out["memory_hint"] = hint
    technical = clean_technical(entry.get("technical"))
    if technical:
        out["technical"] = technical
    investigation = entry.get("investigation")
    if isinstance(investigation, dict):
        run_id = str(investigation.get("run_id") or "").strip()[:64]
        if run_id:
            out["investigation"] = {"run_id": run_id}
    todo = clean_todo_text(entry.get("todo_text"))
    if todo:
        out["todo_text"] = todo
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
        "text": textclip.clip(str(entry.get("text") or ""), MAX_TEXT),
        "detail": textclip.shorten(str(entry.get("detail") or ""), MAX_DETAIL),
        "fix": textclip.shorten(str(entry.get("fix") or ""), MAX_FIX),
        # Whose sentence `fix` is: "" for the rule's own, "triage" for the
        # run that looked at the row before it was shown, "chat" for a
        # conversation the homeowner had about it. The card says which.
        "fix_by": (entry.get("fix_by")
                   if entry.get("fix_by") in FIX_AUTHORS else ""),
        "severity": severity,
        # A row a look set aside offers no Fix: brAIn looked and found
        # nothing to change (often the rule misread the house). The stored
        # claim is kept, so "Let brAIn raise it again" puts it back whole.
        "fixable": bool(entry.get("fixable", True)) and status != "held",
        "entity_id": str(entry.get("entity_id") or "")[:255],
        "source": str(entry.get("source") or "")[:64],
        "source_title": _titled(str(entry.get("source") or ""),
                                str(entry.get("source_title") or ""))[:120],
        # Which Claude run raised it, when one did. Empty for a house
        # check, which is the honest answer: nothing was asked. It is
        # what `capture` joins an ENDING back to the prompt that earned
        # it — the label half of the corpus — and it is deliberately not
        # in the shared-volume mirror, because Home Assistant has no use
        # for a session id.
        "run_id": str(entry.get("run_id") or "")[:64],
        "status": status,
        "result": textclip.clip(str(entry.get("result") or ""), MAX_RESULT),
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
    # The case's conversation and a Morph suggestion's own key, each only on
    # a row that carries one (`_case_fields`' rule).
    thread = _clean_thread(entry.get("thread"))
    if thread:
        out["thread"] = thread
    morph_key = clean_morph_key(entry.get("morph_key"))
    if morph_key:
        out["morph_key"] = morph_key
    items = clean_items(entry.get("items"))
    if items:
        out["items"] = items
    # What ends a "for now" snooze early (`wake_returned`): the entities it
    # is about, which reporting again means the reason it slept is over.
    # Absent on every other row, and only while the snooze is set.
    wake = clean_items(entry.get("snooze_wake"))
    if wake and int(entry.get("snoozed_until") or 0):
        out["snooze_wake"] = wake
    if entry.get("earlier_answer") and not int(entry.get("snoozed_until") or 0):
        out["detail"] = (out["detail"] + " " + EARLIER_ANSWER).strip()
    out.update(_subject_fields(entry))
    # brAIn's own upkeep (`self_care`): the instruction line its Yes takes
    # out. Absent on every other row.
    edit = entry.get("self_edit")
    if isinstance(edit, dict) and edit.get("key") and edit.get("line"):
        out["self_edit"] = {"key": str(edit["key"])[:48],
                            "line": str(edit["line"])[:2000]}
    # When a row brAIn fixed was reopened because its check still saw the
    # fault (`_came_back`). Absent on every other row, for the same reason.
    if entry.get("came_back"):
        out["came_back"] = int(entry["came_back"])
    # When a row sent back to the look started waiting again (`_send_to_look`).
    # Absent on a row that has waited only since it was filed.
    if entry.get("triaging_since") and (status == "triaging"
                                        or late_verdict_welcome(entry)):
        out["triaging_since"] = waiting_since(entry)
    # Still `triaging` past `triage.SHOW_AFTER_S`: shown on the feed with
    # `triage.WAITING` and counted, while the look it is waiting for has
    # still not come. Derived, never stored, and absent otherwise.
    if triage.waiting_too_long({**entry, "status": status}):
        out["waiting_look"] = True
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
    for row in shaped:
        row["fix"] = shown_fix(row)
        if row.get("triage"):
            row["triage"] = shown_look(row["triage"], row)
    shaped.sort(key=lambda f: f["ts"], reverse=True)
    now = time.time()
    return {
        "findings": shaped,
        "open": len([f for f in shaped
                     if (f["status"] in UNSETTLED_STATUSES
                         and not is_snoozed(f, now))
                     or triage.waiting_too_long(f, now)]),
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
                if (e.get("status", "open") in UNSETTLED_STATUSES
                    and str(e.get("text") or "").strip()
                    and not (e.get("snoozed_until") or 0) > now)
                or triage.waiting_too_long(e, now)])


def waiting_look_count(now: float | None = None) -> int:
    """Rows a look has not reached in `triage.SHOW_AFTER_S` — counted by
    every badge beside the open ones, and shown on the feed with
    `triage.WAITING`. Off the raw entries, `open_count`'s reason."""
    now = time.time() if now is None else now
    return len([e for e in _load() if triage.waiting_too_long(e, now)])


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
    return key in suppressing_keys()


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


def clean_items(value) -> list[str]:
    """The item keys a row about several things names, cleaned and capped.

    Strings only, each short, deduplicated in order. Absent from a row that
    names one thing, so every row filed before this existed is unchanged.
    """
    out: list[str] = []
    if not isinstance(value, (list, tuple)):
        return out
    for raw in value:
        if not isinstance(raw, str):
            continue
        item = raw.strip()[:MAX_EVIDENCE_ENTITY]
        if item and item not in out:
            out.append(item)
        if len(out) >= MAX_ITEMS:
            break
    return out


_ITEM_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def item_labels(items) -> tuple[list[str], str]:
    """``(labels, noun)`` for a row's `items`, as a person reads them.

    The card's count line and its Show all (#437): every item by the name
    the house gives it, or — for an entity the house has no name for, a
    reference to one that no longer exists — the id read aloud (`the scene
    “before movie”`), never the id itself. An item that is not an entity
    (a device key) is left out; ``noun`` is "entities" when every item is
    one, else "items"."""
    keys = clean_items(items)
    if not keys:
        return [], ""
    from checks._util import spoken_id  # noqa: PLC0415 — a leaf, lazy
    names = _names_now()
    labels: list[str] = []
    for key in keys:
        if not _ITEM_ENTITY_RE.match(key):
            continue
        named = names.get(key)
        if isinstance(named, dict):
            named = named.get("name")
        labels.append(str(named).strip() if named and str(named).strip()
                      and str(named).strip() != key else spoken_id(key))
    noun = "entities" if len(labels) == len(keys) else "items"
    return labels, noun


def coerce(obj: dict) -> dict | None:
    """One wire-shaped finding — from a model reply or an inbox line — turned
    into a stored entry, or None if there is nothing there.

    Both producers hand over the same loose shape, so both go through here:
    a second hand-written coercion is how the panel and the CLI drift on what
    "fixable" defaults to.
    """
    if not isinstance(obj, dict):
        return None
    obj = as_asked({**obj, "text": str(obj.get("text") or obj.get("finding")
                                        or "").strip()})
    text = str(obj.get("text") or "").strip()
    detail = str(obj.get("detail") or "").strip()
    text, detail = split_overlong(text, detail)
    if not normalize(text):
        return None
    severity = str(obj.get("severity") or "").strip().lower()
    entry = {
        "text": text,
        "detail": textclip.shorten(detail, MAX_DETAIL),
        "fix": textclip.shorten(str(obj.get("fix") or "").strip(), MAX_FIX),
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
    morph_key = clean_morph_key(obj.get("morph_key"))
    if morph_key:
        entry["morph_key"] = morph_key
    items = clean_items(obj.get("items"))
    if items:
        entry["items"] = items
    entry.update(_subject_fields(obj))
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


# A producer whose sentences a model writes rewords the same report every
# time it files it — ten rows over three weeks about one pair of "Cooling
# Time Yesterday" sensors, each worded differently, each passing a dedupe
# keyed on text. For those, the same ENTITY from the same producer is the
# same report: folded into the row already there (any status, a snooze and
# a held verdict included) and into a "Wrong" already given.
#
# Never for a house check — its text is stable by construction, and one
# check may say two different things about one entity (a battery that is
# low, and one that has stopped reporting) — and never for a producer whose
# rows are about an EVENT rather than a subject: the safety lane files one
# row per trip by putting the time in the text, and folding the second
# leak on a sensor into the first is the one fold that loses something
# real. The source is half this key; a second model-written producer about
# the same entity is folded by the narrower rule below
# (`CROSS_FOLD_STATUSES`), against live rows only.
#
# The overnight check (`sre`) is NOT on the list: its rows are about a
# device, and it files each cause under that device's entity
# (`sre.subject_of`), so a cause the run words differently tomorrow is the
# row it already has.
SUBJECT_FOLD_EXCLUDED = frozenset({
    "safety", "security", "correction", "notify_policy",
    "house_book", "healing", "followup", "fix", "doctor", "condition",
    "scene", "morph", "devloop_verify"})


def _folds_by_subject(entry: dict) -> tuple[str, str] | None:
    """The `(entity_id, source)` this row is deduped on besides its text,
    or None when it is deduped on its text alone."""
    eid = str(entry.get("entity_id") or "").strip()
    source = str(entry.get("source") or "").strip()
    if (not eid or not source or ":" in source
            or source in SUBJECT_FOLD_EXCLUDED):
        return None
    return eid, source


# A second model-written producer about the same entity. Two insight cards
# that both read one sensor — the cooling card and the running-cost card —
# each wrote their own wording of the same diagnosis, so the per-producer
# fold above made each card's rewordings one row and still left two cards'
# worth: six rows over ten days about one sensor. So a model-written row
# about an entity that already has a LIVE model-written row about it folds
# into that row whichever producer wrote it, refreshing the row's detail
# rather than filing beside it. Narrower than the per-producer fold on
# purpose: only against `CROSS_FOLD_STATUSES` (a row brAIn fixed is a dated
# event, and a settled "Wrong" was said to ONE producer about ITS claim),
# and never the Resident, whose case is the look itself and refines the row
# it was sent to rather than being a second report about it.
CROSS_FOLD_STATUSES = ("open", "triaging", "held", "needs_you")
# `RESIDENT_SOURCE`, spelled here because it is defined further down; the
# test holds the two equal.
CROSS_FOLD_EXCLUDED = frozenset({"resident"})


def _cross_folds(entry: dict) -> str:
    """The entity a row folds on across producers, or ""."""
    subject = _folds_by_subject(entry)
    if not subject or subject[1] in CROSS_FOLD_EXCLUDED:
        return ""
    return subject[0]


# A question somebody ASKED about an entity a HOUSE CHECK already has a
# live row about is the same problem said twice: "Your question" (an asked
# card, `custom-<id>`, or the chat) filing "the back door battery is flat"
# beside `check:dev.battery_low`'s row about the same sensor was two open
# cards for one battery. Only an asked producer (`ASKED_SOURCE_RE`): a
# scheduled card reading the same sensor makes its own claim about it —
# "reads 0 while the AC ran" is not "frozen", and `test_cross_producer_fold`
# holds that boundary — where a question about a thing somebody was
# looking at is the card the check already filed. It folds
# into the check's row — never the other way, because the check's text is
# the key it re-reports and clears under, and a check row folded into a
# model one would be re-filed by the next pass. The check's detail stands
# (it is rewritten by every pass through `refresh_details`, so anything
# appended would vanish on the next one and read as a flap); the model's
# detail and fix are taken only where the check row has none. Not into a
# security or safety check's row (`CHECK_FOLD_EXCLUDED`): those are the
# family whose rows are about something somebody must see as the rule
# said it, the same reason `SUBJECT_FOLD_EXCLUDED` keeps that family out
# on the model side. The model side is `_cross_folds`', so the Resident
# and that family never fold here either, and only into a live row.
CHECK_FOLD_EXCLUDED = frozenset({"climate.freeze", "safety.tripped"})
CHECK_FOLD_EXCLUDED_PREFIXES = ("sec.",)
# The producers a person asked: an asked card (`custom-<id>`, the shape
# `server._CARD_SOURCE` names it by, or the bare "custom" of an older row)
# and the chat.
ASKED_SOURCE_RE = re.compile(r"^(?:custom(?:-[A-Za-z0-9_-]{1,64})?|chat)$")


def _asked_folds(entry: dict) -> str:
    """The entity an asked report folds into a check's row on, or ""."""
    eid = _cross_folds(entry)
    if not eid or not ASKED_SOURCE_RE.match(str(entry.get("source") or "")):
        return ""
    return eid


def _check_host_key(f: dict) -> str:
    """The entity a live house-check row may take model reports about."""
    source = str(f.get("source") or "")
    eid = str(f.get("entity_id") or "").strip()
    if not eid or not source.startswith("check:"):
        return ""
    if f.get("status") not in CROSS_FOLD_STATUSES:
        return ""
    check = source.split(":", 1)[1]
    if (check in CHECK_FOLD_EXCLUDED
            or check.startswith(CHECK_FOLD_EXCLUDED_PREFIXES)):
        return ""
    return eid


def _fill(host: dict, entry: dict) -> bool:
    """Give a check's row what a model report adds and it lacks."""
    changed = False
    for key in ("detail", "fix"):
        if not str(host.get(key) or "").strip() and entry.get(key):
            host[key] = entry[key]
            if key == "fix" and entry.get("fix_by"):
                host["fix_by"] = entry["fix_by"]
            changed = True
    return changed


def _subjects_answered_wrong() -> set[tuple[str, str]]:
    """The subjects somebody said a model-written report was wrong about.

    Only `ignored`: "not a problem here" is a statement about the house
    that a reworded report does not change, where a fix is a dated event
    and a re-report after it may be news (`_suppresses`'s argument)."""
    out = set()
    for e in _load_settled():
        if e.get("kind") != "ignored":
            continue
        subject = _folds_by_subject(e)
        if subject:
            out.add(subject)
    return out


def _absorb(host: dict | None, entry: dict) -> bool:
    """Fold a re-report into the live row it duplicates. True if it changed.

    The newer detail replaces the old. **A HELD row whose detail changed
    goes back to `triaging`**: a held verdict is a look's answer about the
    row as it stood, and a re-report that carries different evidence is
    the one thing it never saw — four copies of "this window is wrong"
    stayed held as "zero cooling in late September is normal" while a
    later copy's detail proved the window was missing hours of cooling,
    and nothing went back to the verdicts. The first look then judges it
    again under the current claim rule. Never a row a person put back
    (`elevated_by_person`): a person overruling a verdict is not
    overruled back, and a row a person ended is no longer live here.
    """
    if host is None or host.get("status") not in CROSS_FOLD_STATUSES:
        return False
    detail = entry.get("detail")
    if not detail or host.get("detail") == detail:
        return False
    host["detail"] = detail
    if (host.get("status") == "held"
            and not (host.get("triage") or {}).get("elevated_by_person")):
        _send_to_look(host)
    return True


# A report about an entity somebody has already moved to To Do is the chore
# they agreed to, said again: "Add to To Do" settles the finding's key as
# `accepted`, which stops the same TEXT while the chore is open, and a
# model-written producer (the overnight check, the Resident, a card) words
# it differently every pass. So a row whose entity an OPEN to-do item names
# is not filed; the item records that it was seen again instead
# (`todo_store.seen_again`). Completing or dropping the item ends it, as it
# ends the key. Never these: the safety lane, the tripwire and the checks
# about harm — a leak on an entity whose chore is open is still a leak, and
# a card for it is far better than a line on a list — and never a question
# or a suggestion, which asks something the chore does not answer.
TODO_HOLD_EXCLUDED = frozenset({"safety", "security", "check:climate.freeze",
                                "check:safety.tripped"})
TODO_HOLD_KINDS = ("", "problem")
# The house check that reads a detector tripped NOW, and the lane that
# files one the moment it trips. A lane card about the same detector is
# the same trip, so the check's row stands down for it — but only for a
# lane card the list still holds: a sensor still wet a week after its
# card was answered is reported again.
TRIPPED_CHECK_SOURCE = "check:safety.tripped"
SAFETY_LANE_SOURCE = "safety"


def _held_by_todo(entry: dict) -> bool:
    source = str(entry.get("source") or "")
    if source in TODO_HOLD_EXCLUDED:
        return False
    return str(entry.get("kind") or "") in TODO_HOLD_KINDS


def _open_todo_entities() -> dict[str, int]:
    import todo_store  # noqa: PLC0415 — the store imports nothing of ours
    try:
        return todo_store.open_entities()
    except Exception as exc:  # noqa: BLE001 — a list nobody can read holds nothing
        log.debug("could not read the to-do list: %s", exc)
        return {}


def _note_seen_again(held: list[tuple[int, str]]) -> None:
    import todo_store  # noqa: PLC0415
    for item_id, text in held:
        try:
            todo_store.seen_again(item_id, text)
        except OSError as exc:
            log.warning("could not note a report on its to-do item: %s", exc)


# One cause filed as several rows. Two folds over the live list, run after
# every filing (`add_many`, which `add_case` goes through) and after an
# investigation rewrites a row (`refine`), because a case's evidence is what
# says which devices it reaches:
#
#   * a row that DIAGNOSES a shared cause — the Resident's case or the
#     overnight check's (`SHARED_CAUSE_HOSTS`) — whose evidence names two or
#     more devices takes in the live rows filed about each of them ("four
#     Wi-Fi devices are not reachable" beside a row each for two of them);
#   * a model-written row about an automation or a script whose evidence
#     names one device folds into that device's own live row: "the porch
#     automation failed, the light did not respond" is the light being
#     offline, said a second time. Model-written only: a house check about
#     an automation (`auto.trigger_unavailable`) is deliberately its own
#     claim, the one that answers why the automation stopped.
#
# A folded row leaves the list — no memory line, no settled key,
# `clear_resolved`'s ending — and the row it folded into lists the device
# among its evidence and takes the worse severity. A re-report of a folded
# device is folded again on the way in, so it is never announced.
#
# Never a row in the harm family (`SUBJECT_FOLD_EXCLUDED`'s safety,
# security and correction, the harm checks), never a row brAIn fixed
# (`CROSS_FOLD_STATUSES` holds only live ones), never a question or a
# suggestion, never a row somebody has replied under, put back, planned or
# snoozed (`nobody_has_touched`'s rule for a row on screen), and never into
# a row less visible than the one folded: a held cause must not hide an
# open device.
SHARED_CAUSE_HOSTS = frozenset({"resident", "sre"})
SHARED_CAUSE_KINDS = ("", "problem")
AUTOMATION_DOMAINS = ("automation", "script")
_VISIBLE_HOSTS = ("open", "needs_you")


def _devices_named(entry: dict) -> set[str]:
    """The device entities a row is about: its own and its evidence's,
    never an automation or a script."""
    out = {_entity_shaped(entry.get("entity_id"))}
    for ev in entry.get("evidence") or []:
        if isinstance(ev, dict):
            out.add(_entity_shaped(ev.get("entity")))
    out.discard("")
    return {e for e in out if e.split(".", 1)[0] not in AUTOMATION_DOMAINS}


def _may_fold_away(entry: dict) -> bool:
    if entry.get("status") not in CROSS_FOLD_STATUSES:
        return False
    if str(entry.get("kind") or "") not in SHARED_CAUSE_KINDS:
        return False
    source = str(entry.get("source") or "")
    if source in SUBJECT_FOLD_EXCLUDED or source in TODO_HOLD_EXCLUDED:
        return False
    if source.startswith("check:"):
        check = source.split(":", 1)[1]
        if (check in CHECK_FOLD_EXCLUDED
                or check.startswith(CHECK_FOLD_EXCLUDED_PREFIXES)):
            return False
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    if record.get("elevated_by_person") or entry.get("plan"):
        return False
    if int(entry.get("snoozed_until") or 0):
        return False
    return not any(isinstance(t, dict) and t.get("who") == "you"
                   for t in entry.get("thread") or [])


def _may_host(host: dict, entry: dict) -> bool:
    if host is entry or host.get("status") not in CROSS_FOLD_STATUSES:
        return False
    if str(host.get("source") or "") in TODO_HOLD_EXCLUDED:
        return False
    return (host.get("status") in _VISIBLE_HOSTS
            or host.get("status") == entry.get("status"))


def _take_in(host: dict, entry: dict, counts: bool = False) -> None:
    """``entry``'s device and severity onto ``host``. With ``counts``, a
    value that counts what the host's detail counts with another number is
    left out (`quotes_other_counts`): the card keeps one count."""
    evidence = _clean_evidence(host.get("evidence"))
    have = {e["entity"] for e in evidence}
    eid = str(entry.get("entity_id") or "")
    extra = []

    def value(text) -> str:
        text = str(text or "")
        if counts and quotes_other_counts(text, host.get("detail")):
            return ""
        return text

    if eid and eid not in have:
        extra.append({"entity": eid,
                      "value": value(entry.get("claim") or entry.get("text")),
                      "when": ""})
        have.add(eid)
    for ev in _clean_evidence(entry.get("evidence")):
        if ev["entity"] not in have:
            extra.append({**ev, "value": value(ev.get("value"))})
            have.add(ev["entity"])
    if extra:
        host["evidence"] = _clean_evidence(evidence + extra)
    if _severity_rank(entry.get("severity")) > _severity_rank(
            host.get("severity")):
        host["severity"] = entry["severity"]


def _fold_shared(items: list[dict]) -> set[int]:
    """Fold the rows one cause was filed as (above). Returns the ids that
    left the list; ``items`` is changed in place."""
    hosts = []
    for f in items:
        if (str(f.get("source") or "") in SHARED_CAUSE_HOSTS
                and str(f.get("kind") or "") in SHARED_CAUSE_KINDS
                and f.get("status") in CROSS_FOLD_STATUSES):
            devices = _devices_named(f)
            if len(devices) >= 2:
                hosts.append((f, devices))
    # The widest cause first, so a row naming four devices takes in one
    # naming two rather than the other way round.
    hosts.sort(key=lambda h: -len(h[1]))
    by_entity: dict[str, dict] = {}
    for f in items:
        eid = _entity_shaped(f.get("entity_id"))
        if eid and eid.split(".", 1)[0] not in AUTOMATION_DOMAINS \
                and f.get("status") in CROSS_FOLD_STATUSES \
                and str(f.get("kind") or "") in SHARED_CAUSE_KINDS:
            by_entity.setdefault(eid, f)
    gone: set[int] = set()
    for f in items:
        ts = int(f.get("ts") or 0)
        if ts in gone or not _may_fold_away(f):
            continue
        eid = _entity_shaped(f.get("entity_id"))
        host = None
        if eid and eid.split(".", 1)[0] in AUTOMATION_DOMAINS:
            devices = _devices_named(f)
            if len(devices) == 1 and _model_written(f.get("source")):
                host = by_entity.get(next(iter(devices)))
        elif eid:
            mine = len(_devices_named(f))
            for candidate, devices in hosts:
                if (eid in devices and len(devices) > mine
                        and int(candidate.get("ts") or 0) not in gone):
                    host = candidate
                    break
        if host is None or not _may_host(host, f) \
                or int(host.get("ts") or 0) in gone:
            continue
        _take_in(host, f)
        gone.add(ts)
    if gone:
        items[:] = [f for f in items if int(f.get("ts") or 0) not in gone]
        log.info("folded %d finding(s) into the row about their shared cause",
                 len(gone))
    return gone


# One device, one drop card (#440). The folds above key on an ENTITY, and
# one Wi-Fi switch was three open rows: a check's on its switch, a card's
# on its UniFi tracker, and a third inside a four-device "connected but not
# reachable" card — three entities, one box. So a row about a device going
# offline, dropping off or not answering is folded on the DEVICE its
# entities are on (`DISPLAY_NAMES`' ``device``, which the panel fills from
# `checks.network.device_keys`: the registry's device, and for a UniFi
# client's tracker the device it is a client of). A row naming several
# devices takes in a row about any of them; two rows about one device are
# one, the house check's first (its text is the key it re-reports and
# clears under), else the older. And a row about an integration AS A
# WHOLE (``integration``: the UniFi integration losing its controller)
# takes in every other row about that integration as a whole, whichever
# check saw it. The folded row's evidence goes onto the card, less any
# count the card's own detail now contradicts — one device, one count.
# The refusals are `_fold_shared`'s.
DROP_CHECKS = frozenset({
    "check:net.connectivity", "check:dev.unavailable", "check:dev.zha_unseen",
    "check:dev.zwave_dead",
    # The per-device checks `net.connectivity` replaced: rows they filed
    # before the update still fold until the first pass clears them.
    "check:net.wifi_hung", "check:net.wifi_flapping", "check:net.zwave_silent",
    "check:net.zigbee_silent", "check:net.unifi_dropped"})
# A model-written row's claim that something is not there. Read off the
# title or the claim only, for rows no check id can classify.
OFFLINE_RE = re.compile(
    r"\b(?:offline|unavailable|unreachable|not (?:reachable|responding|"
    r"answering|reporting|connected)|stopped (?:reporting|responding|"
    r"answering)|(?:keeps?|kept) (?:dropping|disconnecting|going offline)|"
    r"dropp(?:ing|ed|s) (?:off|out)|drops off|disconnect(?:ed|s|ing)?|"
    r"(?:lost|losing|loses) (?:its |the )?(?:connection|controller)|"
    r"gone (?:quiet|silent)|went (?:quiet|silent))\b", re.I)


def is_drop_report(entry: dict) -> bool:
    """Whether a row reports something being offline or dropping off."""
    source = str(entry.get("source") or "")
    if source in DROP_CHECKS:
        return True
    if source.startswith("check:"):
        return False
    return bool(OFFLINE_RE.search(str(entry.get("claim") or "")
                                  or str(entry.get("text") or "")))


def _row_devices(entry: dict, names: dict) -> set[str]:
    """The keys a row is folded on: ``int:<domain>`` for a row about an
    integration as a whole, else the devices its entities are on."""
    integration = str(entry.get("integration") or "")
    if integration:
        return {f"int:{integration}"}
    if not is_drop_report(entry):
        return set()
    out = set()
    for eid in _devices_named(entry) | set(entry.get("about") or ()):
        row = names.get(eid)
        dev = row.get("device") if isinstance(row, dict) else ""
        if dev:
            out.add(f"dev:{dev}")
    return out


def _fold_devices(items: list[dict]) -> set[int]:
    """Fold the rows one device's (or one integration's) outage was filed
    as (above). Returns the ids that left; ``items`` is changed in place."""
    names = _names_now()
    rows = []
    for f in items:
        if (f.get("status") in CROSS_FOLD_STATUSES
                and str(f.get("kind") or "") in SHARED_CAUSE_KINDS):
            keys = _row_devices(f, names)
            if keys:
                rows.append((f, keys))
    if len(rows) < 2:
        return set()
    # The widest first, then a house check, then the oldest: the order in
    # which a row becomes the card the others are folded into.
    rows.sort(key=lambda r: (-len(r[1]),
                             not str(r[0].get("source") or "").startswith("check:"),
                             int(r[0].get("ts") or 0)))
    hosts: list[tuple[dict, set]] = []
    gone: set[int] = set()
    for f, keys in rows:
        host = next((h for h, hk in hosts if keys <= hk and _may_host(h, f)),
                    None)
        if host is not None and _may_fold_away(f):
            _take_in(host, f, counts=True)
            gone.add(int(f.get("ts") or 0))
            continue
        hosts.append((f, keys))
    if gone:
        items[:] = [f for f in items if int(f.get("ts") or 0) not in gone]
        log.info("folded %d finding(s) into the card about their device",
                 len(gone))
    return gone


# A number and the words after it — "36 separate times", "49 drops" — so a
# sentence's counts can be read against another's by what they count.
_COUNTED_RE = re.compile(r"(?<![\d.:])(\d+(?:\.\d+)?)(?![\d:])"
                         r"((?:\s+[A-Za-z][A-Za-z'-]*){1,2})")


def _counts(text) -> dict[str, set[str]]:
    """``{counted word: {numbers}}`` a sentence carries."""
    out: dict[str, set[str]] = {}
    for m in _COUNTED_RE.finditer(str(text or "")):
        for word in m.group(2).split():
            word = word.lower().strip("'-")
            if len(word) > 3 and word.endswith("s"):
                word = word[:-1]
            if len(word) >= 3:
                out.setdefault(word, set()).add(m.group(1))
    return out


def quotes_other_counts(sentence, detail) -> bool:
    """Whether ``sentence`` counts something the row's ``detail`` counts
    too, with a number the detail does not carry (#443): a look that said
    "49 drops" beside a detail now saying "36 separate times" is two
    answers to one question on one card."""
    said = _counts(sentence)
    if not said:
        return False
    now = _counts(detail)
    for word, numbers in said.items():
        if word in now and not numbers <= now[word]:
            return True
    return False


def _asks_about_own_setup(row: dict) -> bool:
    """Whether ``row`` is an open question to the household about brAIn's
    own setup: `self_care`'s, or any question whose words are about it."""
    if row.get("kind") != "question" or row.get("status") not in CROSS_FOLD_STATUSES:
        return False
    return row.get("source") == "self_care" or house_words.about_own_setup(
        row.get("text"), row.get("claim"))


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
    live = {normalize(f.get("text", "")) for f in items}
    seen = set(live)
    suppressing = suppressing_keys()
    seen |= suppressing
    answered = answered_items()
    subjects = {k for k in (_folds_by_subject(f) for f in items) if k}
    subjects |= _subjects_answered_wrong()
    # entity -> the live model-written row about it (`CROSS_FOLD_STATUSES`),
    # and (entity, source) -> the live row of that producer, so a re-report
    # that is dropped as a duplicate still reaches the row it duplicates.
    across = {}
    live_subject = {}
    checked = {}
    for f in items:
        ck = _check_host_key(f)
        if ck:
            checked.setdefault(ck, f)
        eid = _cross_folds(f)
        if eid and f.get("status") in CROSS_FOLD_STATUSES:
            across.setdefault(eid, f)
        k = _folds_by_subject(f)
        if k and f.get("status") in CROSS_FOLD_STATUSES:
            live_subject.setdefault(k, f)
    used = {int(f.get("ts") or 0) for f in items}
    todo_entities = _open_todo_entities() if objs else {}
    lane_tripped = {str(f.get("entity_id") or "") for f in items
                    if f.get("source") == SAFETY_LANE_SOURCE
                    and f.get("entity_id")}
    # An open question to the household about brAIn's own setup (its
    # instructions, personality, voice): a model's row about the same is
    # that question asked twice, and is folded into it (#563).
    own_question = any(_asks_about_own_setup(f) for f in items)
    held: list[tuple[int, str]] = []
    created = []
    refreshed = False
    for obj in objs:
        entry = coerce(obj)
        care = (_self_care(obj) if entry is not None
                and _model_written(entry.get("source")) else None)
        if entry is not None and _model_written(entry.get("source")):
            # A model's words in the house's own. `text` too, except for
            # the producers whose text is a key code chose (a question's
            # subject, a playbook, a fix's record).
            entry = _plain_row(entry, (
                ("claim", "detail", "fix", "todo_text")
                if entry.get("source") in SUBJECT_FOLD_EXCLUDED
                else ("text", "claim", "detail", "fix", "todo_text")))
        if entry is not None and care:
            # brAIn's own upkeep: its question, not the owner's chore.
            entry.update(care)
        if entry is None:
            continue
        if (own_question and not care and _model_written(entry.get("source"))
                and house_words.about_own_setup(*(entry.get(k) for k in (
                    "text", "claim", "detail", "fix")))):
            continue
        if _asks_about_own_setup(entry):
            own_question = True
        if (_sweepable(entry, None) and is_drop_report(entry)
                and says_recovered(entry.get("detail"))):
            # Its own detail says the trouble has stopped: a card titled as
            # if it were still happening is not filed (#441).
            continue
        if normalize(entry["text"]) in seen and not _names_unanswered(
                entry, live, answered):
            continue
        # A check that reworded its sentence names the words it used to
        # file under (`was`): an answer a person gave to the old wording is
        # an answer to this report, and the new words must not ask again.
        if any(normalize(w) in suppressing for w in (obj.get("was") or ())
               if isinstance(w, str)):
            continue
        about = str(entry.get("entity_id") or "")
        if (about and entry.get("source") == TRIPPED_CHECK_SOURCE
                and about in lane_tripped):
            continue
        if about and about in todo_entities and _held_by_todo(entry):
            held.append((todo_entities[about], entry["text"]))
            continue
        subject = _folds_by_subject(entry)
        if subject and subject in subjects:
            if _absorb(live_subject.get(subject), entry):
                refreshed = True
            continue
        asked = _asked_folds(entry)
        if asked and asked in checked:
            if _fill(checked[asked], entry):
                refreshed = True
            continue
        eid = _cross_folds(entry)
        host = across.get(eid) if eid else None
        if host is not None:
            # Folded: the row already there carries the newer evidence, as
            # a check's re-report does through `refresh_details`, and its
            # status and verdict stand (`_absorb` is the one exception).
            if _absorb(host, entry):
                refreshed = True
            continue
        entry["ts"] = _unique_ts(used)
        used.add(entry["ts"])
        seen.add(normalize(entry["text"]))
        if subject:
            subjects.add(subject)
            if entry.get("status") in CROSS_FOLD_STATUSES:
                live_subject.setdefault(subject, entry)
        if eid and entry.get("status") in CROSS_FOLD_STATUSES:
            across.setdefault(eid, entry)
        ck = _check_host_key(entry)
        if ck:
            checked.setdefault(ck, entry)
        items.append(entry)
        created.append(_shape(entry))
    gone = _fold_shared(items) if created or refreshed else set()
    if created or refreshed:
        gone |= _fold_devices(items)
    if gone:
        created = [c for c in created if int(c.get("ts") or 0) not in gone]
    if created or refreshed or gone:
        _write(_prune(items))
    if held:
        _note_seen_again(held)
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
# Morph's learning suggestions (`morph_case`): a model-written producer like
# an insight card, deduped on its text and never folded across producers.
MORPH_SOURCE = "morph"
RESIDENT_TITLE = "brAIn, watching the house"
# What a Resident row was titled before the title stopped naming an internal
# part. Stored rows and ledger entries still carry it, and `_titled` reads
# them as the new one, so a scorecard row does not split in two.
_OLD_RESIDENT_TITLES = frozenset({"The Resident"})


# An entity id a case may be filed under: a Home Assistant domain, a dot, an
# object id. "the front lock" and "automations.yaml" are not one.
_SUBJECT_RE = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)$")


def _entity_shaped(value) -> str:
    """``value`` when it is an entity id of a domain Home Assistant has,
    else "". A file name or a version number has the shape and no domain."""
    eid = str(value or "").strip()
    m = _SUBJECT_RE.match(eid)
    if not m:
        return ""
    from checks._util import _CORE_DOMAINS  # noqa: PLC0415 — leaf, lazy
    return eid if m.group(1) in _CORE_DOMAINS else ""


def case_subject(row: dict, signal_subject: str = "") -> str:
    """The one entity a case is about, or "" — never invented.

    In order: the case's own ``entity_id``; the subject of the signal the
    investigation was sent to look at; the single device its evidence
    names (two readings of one lock are one device, a lock and a hub are
    two and name nobody). A Resident case was stored with no entity at all,
    so nothing tied "the front lock has been offline since 10:20" to the
    lock coming back, and the row outlived the fault by a day.
    """
    row = row if isinstance(row, dict) else {}
    own = _entity_shaped(row.get("entity_id"))
    if own:
        return own
    subject = _entity_shaped(signal_subject)
    if subject:
        return subject
    named = {_entity_shaped(ev.get("entity")) for ev in row.get("evidence") or []
             if isinstance(ev, dict)}
    named.discard("")
    return named.pop() if len(named) == 1 else ""


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
    # A case is a model's sentence: stored in the house's own words, `text`
    # included where it is the claim (the Resident's), and left alone where
    # code chose it as a key (`SUBJECT_FOLD_EXCLUDED`'s producers).
    row = _plain_row(row, (
        ("claim", "detail", "fix", "todo_text")
        if str(row.get("source") or "") in SUBJECT_FOLD_EXCLUDED
        else ("claim", "detail", "fix", "text", "todo_text")))
    claim = textclip.shorten(str(row.get("claim") or "").strip(), MAX_CLAIM)
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


# What an investigation may rewrite on a row it was sent to look at, and
# the statuses it may do it in — a row a person has moved on (a plan they
# asked for, a fix in flight, a snooze) is theirs, and a run that took
# five minutes must not drag it back.
REFINABLE = ("open", "needs_you", "triaging")


@_mutates
def refine(ts: int, case: dict, run_id: str = "",
           when: float | None = None) -> dict | None:
    """Rewrite a row with what the run that LOOKED found. Returns it, or None.

    The deeper look used to be unable to correct the cheaper one: it was
    told the row it had been sent to investigate was "already in front of
    the homeowner, do not claim it again", so it either abstained — a
    paid run that left no trace — or filed a second, differently worded
    card beside the first. This is the third answer, and the right one.

    **`text` is never touched.** It is the key a check re-reports under, so
    a rewritten `text` would read as a new problem on the next pass and
    file the rule's sentence all over again; what changes is everything a
    card SHOWS — the `claim` (which the feed renders over `text`), the
    detail, the fix and who wrote it, the evidence, the stakes and the
    confidence. Severity only rises: an investigation's stakes top out at
    `serious`, and a rule that filed `critical` (a freeze) must not be
    talked down a tier by a model's own confidence.
    """
    if not isinstance(case, dict):
        return None
    # The run that looked wrote these; `text` is not among them and never is.
    case = _plain_row({**case, "source": RESIDENT_SOURCE})
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        if entry.get("status") not in REFINABLE:
            return None
        merged = {**entry, **{k: case[k] for k in (
            "claim", "kind", "confidence", "stakes", "actions",
            "memory_hint", "technical") if case.get(k) not in (None, "", [])}}
        evidence = list(case.get("evidence") or []) + list(
            entry.get("evidence") or [])
        merged["evidence"] = evidence
        if run_id:
            merged["investigation"] = {"run_id": run_id}
        entry.update(_case_fields(merged))
        detail = str(case.get("detail") or "").strip()
        if detail:
            entry["detail"] = textclip.shorten(detail, MAX_DETAIL)
        fix = str(case.get("fix") or "").strip()
        if fix:
            entry["fix"] = textclip.shorten(fix, MAX_FIX)
            entry["fix_by"] = "resident"
        # And the To Do sentence, in the words of the run that looked.
        todo = clean_todo_text(case.get("todo_text"))
        if todo:
            entry["todo_text"] = todo
        if _severity_rank(case.get("severity")) > _severity_rank(
                entry.get("severity")):
            entry["severity"] = case["severity"]
        if entry.get("status") == "triaging":
            entry["status"] = "open"
        # The reason is what a look CONCLUDED, and the claim is not that:
        # it is the card's title, so writing it here printed the finding
        # back under "brAIn checked". What stands is the reason a look
        # already gave (the first look's sentence), unless that too only
        # repeats the row; otherwise there is none.
        prior = str((entry.get("triage") or {}).get("reason") or "")
        if echoes(prior, entry.get("text"), entry.get("claim"),
                  case.get("claim")) or prior in (
                      triage.UNJUDGED, triage.RUN_FAILED,
                      *triage.LEGACY_STOCK):
            prior = ""
        entry["triage"] = _clean_triage({
            "verdict": "elevated",
            "reason": prior,
            "run_id": run_id,
            "at": int(when if when is not None else time.time()),
            "elevated_by_person": bool(
                (entry.get("triage") or {}).get("elevated_by_person")),
            "elevated_at": int(
                (entry.get("triage") or {}).get("elevated_at") or 0),
            "wrote_fix": bool(fix)})
        # The run that looked may have named every device a cause reaches,
        # or found this row to be one of them — then it is the shared row
        # that carries it, and there is nothing of this one left to show.
        gone = _fold_shared(items) | _fold_devices(items)
        _write(items)
        return None if int(ts) in gone else _shape(entry)
    return None


@_mutates
def hold_after_look(ts: int, reason: str, run_id: str = "",
                    when: float | None = None) -> dict | None:
    """An investigation looked and found nothing: hold the row, saying why.

    The same `held` the first look writes, reached one tier later and only
    by a reply that SAID so (`resident.parse_dismissal` — an empty claim
    with `dismiss`), never by a run that failed or came back empty, which
    leave the row exactly where it was. Never over a person: a row
    somebody put back with "Let brAIn raise it again" (`elevated_by_person`)
    stays up whatever a run says, because a person overruling a verdict is
    the one piece of evidence a second verdict may not overrule back.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        if entry.get("status") not in REFINABLE:
            return None
        if (entry.get("triage") or {}).get("elevated_by_person"):
            return None
        entry["status"] = "held"
        said = str(reason or "").strip()
        if echoes(said, entry.get("text"), entry.get("claim")):
            said = ""
        entry["triage"] = _clean_triage({
            "verdict": "held",
            "reason": textclip.shorten(said, triage.MAX_REASON),
            "run_id": run_id,
            "at": int(when if when is not None else time.time()),
            "wrote_fix": False, "v": triage.LOOK_VERSION})
        _write(items)
        return _shape(entry)
    return None


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
            entry["result"] = textclip.clip(str(result), MAX_RESULT)
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

    ``verdicts`` is ``{ts: (verdict, reason)}``, or ``(verdict, reason,
    True)`` for a hold the look said is NOT NEWS (`resident.ALREADY`), which
    holds a row silence already showed too, while nobody has touched it
    (:func:`nobody_has_touched`). An ``elevated`` or
    ``untriaged`` row becomes ``open`` — the second because nothing looked,
    which surfaces exactly like the first and says so on the card — and a
    ``held`` row becomes ``held``.

    It writes no ``fix``. The retired triage drain could hand one over, and
    the run that writes a specific "what you'd need to do" now is the
    Resident's investigation, through :func:`refine` — the first look that
    calls this answers one word and a sentence, and a sentence about
    whether a row is real is not advice about what to do with it.

    Only a row still in ``triaging`` is touched — or one that silence
    surfaced (:func:`late_verdict_welcome`). Everything else is a row a
    person or the fixer has already moved on from, and a verdict arriving
    late about one of those must not drag it back: a run that took four
    minutes can easily be answering about a finding somebody settled in
    the meantime.

    Returns the rows it MOVED out of ``triaging``, shaped — which is what
    every caller announces. A late verdict on a row silence already showed
    is written but not returned: that row is already on the list and was
    already announced, and returning it rang the phone again on every look.
    """
    stamp = int(when if when is not None else time.time())
    items = _load()
    changed: list[dict] = []
    wrote = False
    for entry in items:
        ts = int(entry.get("ts") or 0)
        if ts not in verdicts:
            continue
        late = entry.get("status") != "triaging"
        verdict, reason = verdicts[ts][:2]
        not_news = len(verdicts[ts]) > 2 and verdicts[ts][2] is True
        if verdict not in triage.VERDICTS:
            continue
        if late and verdict == "held" and (
                look_may_set_aside(entry)
                or (not_news and nobody_has_touched(entry))):
            # A house-book question the look found the house already
            # answers: held with the look's reason, announced to nobody,
            # still in History where it can be put back.
            if echoes(reason, entry.get("text"), entry.get("claim")):
                reason = ""
            entry["status"] = "held"
            entry["triage"] = _clean_triage({
                "verdict": "held", "reason": reason, "run_id": run_id,
                "at": stamp, "wrote_fix": False, "v": triage.LOOK_VERSION})
            wrote = True
            continue
        if late and not late_verdict_welcome(entry):
            continue
        if echoes(reason, entry.get("text"), entry.get("claim")):
            reason = ""
        if late and verdict == "untriaged":
            # "Nothing looked" about a row that already says nothing looked
            # is not a change — and rewriting it would hand the row back to
            # be announced on every look that fails.
            continue
        if not late:
            entry["status"] = "held" if verdict == "held" else "open"
        if verdict != "untriaged":
            # A look answered: the wait is over. "Nothing looked" keeps the
            # stamp, because the row is still waiting for exactly that.
            entry.pop("triaging_since", None)
        entry["triage"] = _clean_triage({
            "verdict": verdict, "reason": reason,
            "run_id": run_id, "at": stamp, "wrote_fix": False,
            "v": triage.LOOK_VERSION})
        wrote = True
        if not late:
            changed.append(_shape(entry))
    if wrote:
        _write(items)
    return changed


def waiting_since(entry: dict) -> int:
    """When this row started waiting for a look: the moment it was last
    sent back to `triaging`, or when it was filed.

    A row's `ts` is its FILING, and three things send an old row back to
    the look long after that — a held row re-reported with a new detail
    (`_absorb`), one whose severity rose (`refresh_details`), the one-time
    re-look at startup (`migrate_folds`). Every clock that asked "has this
    waited too long" read `ts`, so a fortnight-old row sent back to the
    look was "left mid-look past the hour" the very next minute, shown as
    if nothing had looked at it, and — the re-offer reaching back a day
    from the FILING — never offered to a look again (reports #82).
    """
    if not isinstance(entry, dict):
        return 0
    try:
        since = int(entry.get("triaging_since") or 0)
    except (TypeError, ValueError):
        since = 0
    return since or int(entry.get("ts") or 0)


def _send_to_look(entry: dict, now: float | None = None) -> None:
    """Back to the first look, stamped with when — see `waiting_since`."""
    entry["status"] = "triaging"
    entry["triaging_since"] = int(now if now is not None else time.time())


# The one producer whose open row a look's `ignore` may set aside. A
# house-book question is filed open at once (a question is for the person),
# so it never waits in `triaging` for a look — and a question the house
# already answers (the registry places the thing, an automation does it)
# is one brAIn should not have asked. Every other row already on screen
# keeps `late_verdict_welcome`'s rule: it never vanishes into a run.
# `house_book.SOURCE`, spelled here because the store imports no producer;
# the test holds the two equal.
LOOK_MAY_SET_ASIDE = frozenset({"house_book"})


def look_may_set_aside(entry: dict) -> bool:
    """An open house-book question nobody has put back."""
    if not isinstance(entry, dict) or entry.get("status") != "open":
        return False
    if str(entry.get("source") or "") not in LOOK_MAY_SET_ASIDE:
        return False
    if str(entry.get("kind") or "") != "question":
        return False
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    return not record.get("elevated_by_person")


def nobody_has_touched(entry: dict) -> bool:
    """An open row no person has answered, replied under or put back, and
    no run is planning or fixing — the one kind a look may still set aside
    once it is on screen, and only when the look said the row is not news
    (`resident.ALREADY`: already answered, marked wrong before, a duplicate,
    already over, or the thing's ordinary state).

    "A row on screen never vanishes into a run" is about a run overruling
    somebody; a row nobody has done anything with, under a look that says
    the household already answered it, is the list showing what brAIn has
    just said it should not. Held, not deleted: History › Set aside by
    brAIn still has it, and Restore puts it back.
    """
    if not isinstance(entry, dict) or entry.get("status") != "open":
        return False
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    if record.get("elevated_by_person"):
        return False
    if entry.get("plan") or int(entry.get("snoozed_until") or 0):
        return False
    if entry.get("fix_by") in ("chat", "person"):
        return False
    return not any(isinstance(t, dict) and t.get("who") == "you"
                   for t in entry.get("thread") or [])


def late_verdict_welcome(entry: dict) -> bool:
    """A row on the list only because nothing looked at it in time.

    `untriaged` is the record that NOTHING judged a row — the stale sweep
    or a failed look showed it so that silence could not hide it — and it
    is not a decision anybody made. So a look that answers about it later
    is the first verdict it has had, not a late one overriding somebody:
    it replaces the "nothing looked" record with what the look said. The
    STATUS stays `open` whatever the verdict — an `ignore` included —
    because a row already on screen never vanishes into a run; the card
    then says what brAIn had said about it.
    Refusing it was what left rows carrying `triage.UNJUDGED` for the rest
    of their lives on a house where a look did answer about them.

    Never a row a person put back, never one a person or the fixer has
    moved on from (only `open`), and never one a look already judged.
    """
    if not isinstance(entry, dict) or entry.get("status") != "open":
        return False
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    return (record.get("verdict") == "untriaged"
            and not record.get("elevated_by_person"))


def unjudged_open(since: float | None = None) -> list[dict]:
    """Rows silence surfaced and no look has judged since, OLDEST FIRST,
    shaped.

    They are offered to the next look beside `awaiting_triage`'s, because
    the pending list is in memory: a restart after the stale sweep would
    otherwise leave a row marked as never looked at for good, with nothing
    left that could correct it.

    **There is no window on the filing, and there used to be.** A row on
    the list that says nothing looked at it is a claim on screen today
    whatever day it was filed — a check re-reports it every pass, or
    `clear_resolved` takes it off — so it is offered until a look answers
    about it. Bounding it by a day from `ts` is what left a row sent back
    to the look a fortnight after it was filed waiting for good (reports
    #82). ``since``, when given, bounds when the row started WAITING
    (`waiting_since`), never when it was filed.
    """
    rows = [_shape(e) for e in _load()
            if late_verdict_welcome(e)
            and (since is None or waiting_since(e) >= int(since))]
    rows = [r for r in rows if r["text"]]
    rows.sort(key=lambda f: f["ts"])
    return rows


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
    The hour runs from `waiting_since`, never from the filing.
    """
    return [int(e.get("ts") or 0) for e in _load()
            if e.get("status") == "triaging"
            and waiting_since(e) < int(cutoff)]


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
        record["elevated_at"] = int(time.time())
        entry["triage"] = record
        _write(items)
        return _shape(entry)
    return None


@_mutates
def snooze(ts: int, until: int, wake=None, worse=None) -> dict | None:
    """Take a finding off the list until ``until`` (epoch seconds).

    Deliberately does NOT touch the status. "Remind me later" and "not a
    problem" are different answers — the second is permanent and teaches
    the analyst never to raise it again, and using it for the first would
    quietly throw away a real problem you meant to come back to.

    ``until <= 0`` brings it back now. ``wake`` names the entities whose
    return ends the snooze early (`wake_returned`) — the "I'm fixing it"
    snooze, which is over the moment the thing it is about reports again;
    any other snooze clears it.

    ``worse`` (``{"below": 10}``) is the other early end, for "it's on my
    list, don't remind me": the card stays away for the whole period unless
    the thing gets clearly worse (`wake_worse`) — a reading at or under
    ``below``, or the device going unavailable.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts:
            continue
        entry["snoozed_until"] = max(0, int(until))
        if isinstance(worse, dict) and until > 0 and worse.get("entities"):
            entry["snooze_worse"] = {
                "entities": clean_items(worse["entities"]),
                "below": worse.get("below"), "from": {}}
        else:
            entry.pop("snooze_worse", None)
        if until <= 0:
            entry.pop("earlier_answer", None)
        wake = clean_items(wake) if wake and until > 0 else []
        if wake:
            entry["snooze_wake"] = wake
        else:
            entry.pop("snooze_wake", None)
        _write(items)
        return _shape(entry)
    return None


# A state that is not a reading: an entity reporting one has not come back.
_NOT_BACK = frozenset({"", "unavailable", "unknown", "none"})


@_mutates
def wake_returned(states, now: float | None = None) -> list[dict]:
    """End the "for now" snoozes whose entities all report again.

    ``states`` is the snapshot a checks pass already fetched. A row asleep
    with `snooze_wake` whose every entity now has a real state is over
    early: Morph's suggestion to remove that thing's card is dropped (the
    card is kept — the caller tells Morph), and any other row is woken, so
    a check's own pass clears it if the rule no longer finds it and shows
    it again if it does. Returns the rows it ended or woke, shaped.
    """
    if not isinstance(states, dict) or not states:
        return []
    now = time.time() if now is None else now
    items = _load()
    kept, touched, changed = [], [], False
    for entry in items:
        wake = clean_items(entry.get("snooze_wake"))
        if not wake or float(entry.get("snoozed_until") or 0) <= now:
            kept.append(entry)
            continue
        back = all(isinstance(states.get(e), dict)
                   and str(states[e].get("state") or "").lower()
                   not in _NOT_BACK for e in wake)
        if not back:
            kept.append(entry)
            continue
        changed = True
        if str(entry.get("source") or "") == MORPH_SOURCE:
            touched.append(_shape(entry))
            continue
        entry["snoozed_until"] = 0
        entry.pop("snooze_wake", None)
        touched.append(_shape(entry))
        kept.append(entry)
    if changed:
        _write(kept)
    return touched


# How far under where it stood when the card went to sleep a reading must
# fall before "I'll handle it" is no longer enough. A reading that wobbles a
# point or two is the same battery.
WORSE_DROP = 3
EARLIER_ANSWER = ("You said you would handle this, and it has got worse "
                  "since.")


def _numeric(state) -> float | None:
    try:
        return float(str(state).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


@_mutates
def wake_worse(states, now: float | None = None) -> list[dict]:
    """End the "I'll handle it" snoozes whose thing got clearly worse.

    ``states`` is the snapshot a checks pass already fetched. A row asleep
    with `snooze_worse` is woken when one of its entities reads at or under
    the row's ``below`` (and at least `WORSE_DROP` under where it stood on
    the first pass after the answer), or goes unavailable having been
    reporting. Otherwise it sleeps on. A woken row carries
    `EARLIER_ANSWER` in its detail, so the card says the answer was heard.
    """
    if not isinstance(states, dict) or not states:
        return []
    now = time.time() if now is None else now
    items = _load()
    touched, changed = [], False
    for entry in items:
        worse = entry.get("snooze_worse")
        if not isinstance(worse, dict) \
                or float(entry.get("snoozed_until") or 0) <= now:
            continue
        base = worse.setdefault("from", {})
        hit = False
        for eid in clean_items(worse.get("entities")):
            st = states.get(eid)
            raw = str(st.get("state") or "").lower() if isinstance(st, dict) else ""
            if eid not in base:
                base[eid] = raw
                changed = True
            if raw in ("unavailable", "unknown", ""):
                # Only a device that was reporting has "gone".
                hit = hit or base[eid] not in ("unavailable", "unknown", "")
                continue
            level, was = _numeric(raw), _numeric(base[eid])
            below = worse.get("below")
            if level is not None and isinstance(below, (int, float)) \
                    and level <= below \
                    and (was is None or level <= was - WORSE_DROP):
                hit = True
        if hit:
            entry["snoozed_until"] = 0
            entry.pop("snooze_worse", None)
            entry["earlier_answer"] = EARLIER_ANSWER
            touched.append(_shape(entry))
    if changed or touched:
        _write(items)
    return touched


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
    prior = next((e for e in ledger if e.get("key") == key), None)
    ledger = [e for e in ledger if e.get("key") != key]
    # A problem answered again after its earlier answer lapsed has come
    # BACK, and how long it stayed away is the most useful number the
    # ledger can hold about it — a battery that lasts four months is a
    # maintenance interval, not a coincidence. Carried forward rather than
    # computed, because the entry it is measured from is about to be
    # replaced.
    recurrence = {}
    if prior is not None and prior.get("lapsed_at"):
        recurrence = {"recurred": int(prior.get("recurred") or 0) + 1,
                      "previous_at": int(prior.get("ts") or 0)}
    stamp = when or int(time.time())
    ledger.append({
        **recurrence,
        "key": key,
        "text": shaped["text"],
        "kind": kind,
        "ts": stamp,
        # When this key was first answered Wrong. `ts` is when the entry
        # was last WRITTEN, and a key already Wrong is written again by
        # bookkeeping that is not a person saying so again (an answer for a
        # row that is gone, a request applied twice, an old row migrated
        # in) — read as the Wrong's age, it kept a rule nobody had marked
        # Wrong for weeks on the fault list (`scorecard`'s `last_wrong_ts`).
        **({"wrong_at": _wrong_at(prior) or stamp} if kind == "ignored"
           else {}),
        # How many times this exact key was answered Wrong. The entry is
        # replaced on every answer, so without this a third Wrong is
        # indistinguishable from the first (`answered_checks`).
        **({"wrong_count": (int(prior.get("wrong_count") or 1)
                            if _wrong_at(prior) else 0) + 1}
           if kind == "ignored" else {}),
        "note": str(note or "").strip()[:MAX_NOTE],
        # Who raised it. An ending is a label — "I did it" says the report
        # was right, "Wrong" says it was not — and without the producer on
        # the entry nothing can add those labels up per producer. That sum
        # is the scorecard, and the scorecard is what says which check or
        # which card is worth trusting in this house.
        "source": str(shaped.get("source") or "")[:64],
        "source_title": str(shaped.get("source_title") or "")[:120],
        # What it was about, so a reworded report about the same entity
        # from the same producer is recognised as answered
        # (`_subjects_answered_wrong`).
        "entity_id": str(shaped.get("entity_id") or "")[:255],
        # Every item a row about several things named, so the answer covers
        # those and a later row naming something else is news
        # (`answered_items`).
        **({"items": clean_items(shaped.get("items"))}
           if clean_items(shaped.get("items")) else {}),
    })
    # A row that names config entries (`entry:<id>`) keeps one text however
    # many entries it is about, and each answer replaces the entry above:
    # the entries answered before stay answered.
    if prior is not None and kind == "ignored":
        old = [i for i in clean_items(prior.get("items"))
               if i.startswith("entry:")]
        new = clean_items(ledger[-1].get("items"))
        if old and any(i.startswith("entry:") for i in new):
            ledger[-1]["items"] = clean_items(new + old)
    _write_settled(ledger[-MAX_SETTLED:])


def answered_checks() -> dict[str, dict[str, dict]]:
    """What the household has already said about each entity, per check:
    ``{entity_id: {check_id: {"wrong": n, "notes": [reason, …]}}}``.

    Read off the settled ledger for the rows a house check filed, under the
    entity the row was about and every item it named. A check asks this
    (`House.answered_off`) before it files, so a device somebody answered
    Wrong twice, or said they no longer use, is not filed again in new
    words whether or not the rule written then still holds. Never raises.
    """
    out: dict[str, dict[str, dict]] = {}
    try:
        ledger = _load_settled()
    except Exception:  # noqa: BLE001
        return out
    for e in ledger:
        source = str(e.get("source") or "")
        if not source.startswith("check:"):
            continue
        check = source[len("check:"):]
        subjects = [str(e.get("entity_id") or "")] + list(
            clean_items(e.get("items")))
        wrong = 0
        if e.get("kind") == "ignored":
            wrong = max(1, int(e.get("wrong_count") or 1))
        note = str(e.get("note") or "").strip()
        for subject in dict.fromkeys(s for s in subjects if s):
            row = out.setdefault(subject, {}).setdefault(
                check, {"wrong": 0, "notes": []})
            row["wrong"] += wrong
            # When it was last answered, for an answer that holds only
            # until the thing changes (`House.answered_since`).
            row["at"] = max(int(row.get("at") or 0), int(e.get("ts") or 0))
            if note and note not in row["notes"]:
                row["notes"].append(note)
    return out


def _wrong_at(entry: dict | None) -> int:
    """When a ledger entry's Wrong was given, or 0 for one that is not
    Wrong. An entry written before `wrong_at` existed is aged by its `ts`."""
    if not isinstance(entry, dict) or entry.get("kind") != "ignored":
        return 0
    return int(entry.get("wrong_at") or entry.get("ts") or 0)


# Which settled answers stop a problem being raised again, and for how long.
#
# The ledger was permanent for every ending, and the reason given — "the
# analyst would re-report next week the thing you answered today" — is true
# of exactly one of them. `ignored` (Wrong) says the report was wrong about
# this house, and that does not stop being true: it is permanent, and the
# rule it wrote is permanent with it. `fixed` and `accepted` say the report
# was RIGHT, and a problem that was real can come back — a battery runs low
# again next year, a backup goes stale again next month, the disk fills
# again. Suppressing the second occurrence because somebody dealt with the
# first is how a house check went blind for the life of the install, and
# several check texts are one sentence for the whole house ("The newest
# backup is more than a week old"), so one press blinded a whole check.
#
# So a right answer suppresses while it is still the answer:
#
#   * for a house check, until a pass of that check RUNS and no longer
#     reports it (`lapse_settled`) — the problem is over, so the next time
#     it happens is news. A check that could not look lapses nothing,
#     which is `clear_resolved`'s rule for the same reason;
#   * for anything else that was fixed — an analyst's report, a Resident
#     case — for `FIXED_LAPSE_DAYS`, because nothing re-runs a model's
#     judgement to say the problem has gone, and a fix is a dated event.
#     An `accepted` row that is not a check's is a chore still on the
#     list, and it suppresses until the chore is done (which re-settles it
#     as `fixed`, starting that clock).
#
# A lapsed entry is kept, not deleted: it is still a label for the
# scorecard, still listed in the analyst's "already dealt with" block, and
# the entry a recurrence is measured from (`_remember_settled`).
FIXED_LAPSE_DAYS = 90
RIGHT_KINDS = ("fixed", "accepted")


def _suppresses(entry: dict, now: float) -> bool:
    kind = entry.get("kind")
    if kind not in RIGHT_KINDS:
        return True          # Wrong, and anything this does not recognise
    if entry.get("lapsed_at"):
        return False
    if str(entry.get("source") or "").startswith("check:"):
        return True          # until a pass of the check stops reporting it
    if kind == "fixed":
        age = now - float(entry.get("ts") or 0)
        return age < FIXED_LAPSE_DAYS * 86400
    return True


def answered_items(now: float | None = None) -> dict[str, set]:
    """``{key: {items}}`` for the suppressing answers that named items.

    A row about several things (devices in no area, helpers nothing uses)
    has one stable text, so a Wrong on it settled that text for good — and
    the next device to turn up in no area was swallowed by an answer about
    two others. The items the answer covered ride on its ledger entry; a
    row under the same key naming anything outside them is not suppressed
    (`_names_unanswered`). An entry with no items is the old answer and
    suppresses exactly as it always did.
    """
    now = time.time() if now is None else float(now)
    out: dict[str, set] = {}
    for e in _load_settled():
        items = clean_items(e.get("items"))
        if items and _suppresses(e, now):
            out[str(e.get("key") or "")] = set(items)
    return out


def _names_unanswered(entry: dict, live: set, answered: dict) -> bool:
    """A re-report the settled ledger would swallow that names something new.

    Only when the key is not a live row (that one is refreshed in place)
    and the answer recorded which items it covered.
    """
    key = normalize(entry.get("text") or "")
    if key in live or key not in answered:
        return False
    return bool(set(clean_items(entry.get("items"))) - answered[key])


def suppressing_keys(now: float | None = None) -> set[str]:
    """The settled keys that still stop a re-report. One derivation, read
    by `add_many` and `is_known` alike, so the two cannot disagree."""
    now = time.time() if now is None else float(now)
    return {str(e.get("key") or "") for e in _load_settled()
            if _suppresses(e, now)}


def lapse_settled(sources: set[str], keep_keys: set[str],
                  now: float | None = None) -> int:
    """A check that ran and no longer reports a problem ends its answer.

    For every `fixed`/`accepted` entry a check in ``sources`` filed whose
    key that pass did NOT report: the problem is over, so the answer stops
    suppressing it and the next occurrence files again. Only checks that
    RAN, `clear_resolved`'s rule — "I could not look" is not "it went
    away". Returns how many entries lapsed.
    """
    now = time.time() if now is None else float(now)
    ledger = _load_settled()
    lapsed = 0
    for entry in ledger:
        if (entry.get("kind") in RIGHT_KINDS
                and not entry.get("lapsed_at")
                and str(entry.get("source") or "") in sources
                and str(entry.get("key") or "") not in keep_keys):
            entry["lapsed_at"] = int(now)
            lapsed += 1
    if lapsed:
        _write_settled(ledger)
    return lapsed


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
        if not src or e.get("kind") == "not_applicable":
            # "Doesn't apply" is no label: a question that did not fit the
            # house says nothing about whether its producer is right.
            continue
        row = by.setdefault(src, {
            "source": src,
            "title": _rule_titled(src, str(e.get("source_title") or ""))
            or src,
            "confirmed": 0, "wrong": 0, "last": "", "last_ts": 0,
            "last_wrong_ts": 0, "example": "", "example_ts": -1})
        # One report the rule filed, newest first — what the mute question
        # names as an example of what stopping it stops.
        if str(e.get("text") or "").strip() and int(e.get("ts") or 0) >= \
                row["example_ts"]:
            row["example"] = str(e["text"]).strip()[:MAX_TEXT]
            row["example_ts"] = int(e.get("ts") or 0)
        # Agreeing to do something is agreeing the report was right, so
        # an accepted row scores exactly as a fixed one. The alternative
        # was to count it as nothing until the chore is done, which would
        # make a producer look worse the more of its reports people took
        # seriously and had not got round to yet.
        label = ("confirmed" if e.get("kind") in ("fixed", "accepted")
                 else "wrong" if e.get("kind") == "ignored" else "")
        if label:
            row[label] += 1
            # The latest ending, for `mute_offer`: a rule somebody last
            # agreed with is not offered for muting.
            if int(e.get("ts") or 0) >= row["last_ts"]:
                row["last"], row["last_ts"] = label, int(e.get("ts") or 0)
            # The newest Wrong, so a fault about a rule that is often wrong
            # is a fault only while people are still saying so.
            if label == "wrong":
                row["last_wrong_ts"] = max(row["last_wrong_ts"], _wrong_at(e))
    rows = list(by.values())
    for r in rows:
        r["total"] = r["confirmed"] + r["wrong"]
        r.pop("example_ts", None)
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
    seen |= suppressing_keys()
    used = {int(f.get("ts") or 0) for f in items}
    added = 0
    for row in rows:
        entry = coerce(row)
        if entry is None or normalize(entry["text"]) in seen:
            continue
        status = row.get("status")
        entry["status"] = status if status in STATUSES else "open"
        entry["result"] = textclip.clip(str(row.get("result") or ""), MAX_RESULT)
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
            "text": textclip.clip(str(entry.get("text") or ""), MAX_TEXT),
            "kind": kind if kind in ("fixed", "ignored") else "ignored",
            "ts": int(entry.get("ts") or 0) or int(time.time()),
            "note": str(entry.get("note") or "").strip()[:MAX_NOTE],
            **({"wrong_at": _wrong_at(entry) or int(entry.get("ts") or 0)
                or int(time.time())}
               if (kind if kind in ("fixed", "ignored") else "ignored")
               == "ignored" else {}),
        })
        known.add(key)
        added += 1
    if added:
        _write_settled(ledger[-MAX_SETTLED:])
    return added


# A held verdict given before the claim rule (`triage.LOOK_VERSION` 2)
# judged a reason, not the claim; and one fault filed by several cards
# before the cross-fold existed is several rows. Both are repaired ONCE at
# startup, marked on disk, so a restart cannot re-look at the whole store.
MIGRATIONS_FILE = Path(os.environ.get(
    "BRAIN_FINDINGS_MIGRATIONS", "/data/findings-migrations.json"))
MIGRATION_RETRIAGE_MAX = 25


def _migrated() -> dict:
    try:
        data = json.loads(MIGRATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _status_rank(row: dict) -> int:
    # The status a person can see wins: open > needs_you > triaging > held.
    return {"open": 0, "needs_you": 1, "triaging": 2, "held": 3}.get(
        row.get("status"), 9)


@_mutates
def migrate_folds() -> dict:
    """One-time: fold live model-written rows about one entity across
    producers (`_cross_folds`' rule), and give rows held under the old look
    one fresh look. Returns ``{"folded": n, "retriaged": n}``.

    The newest row's detail wins and the row the person can SEE wins the
    status (any open copy keeps the open one); the others are dropped, not
    settled — they are one report, and a settled key for the wording of a
    duplicate would suppress the report that is still true. Never the
    Resident, a fixed/fixing row, or the settled ledger; never a held row a
    person put back. The re-look is bounded to `MIGRATION_RETRIAGE_MAX`
    rows, newest first, and neither half runs twice (the marker is written
    even when nothing changed, so a restart is not a new pass).
    """
    marks = _migrated()
    out = {"folded": 0, "retriaged": 0}
    if marks.get("folds_v1") and marks.get("retriage_v1"):
        return out
    items = _load()
    changed = False
    if not marks.get("folds_v1"):
        groups: dict[str, list[dict]] = {}
        for f in items:
            eid = _cross_folds(f)
            if eid and f.get("status") in CROSS_FOLD_STATUSES:
                groups.setdefault(eid, []).append(f)
        drop: set[int] = set()
        for rows in groups.values():
            if len(rows) < 2:
                continue
            host = min(rows, key=lambda r: (_status_rank(r),
                                            -int(r.get("ts") or 0)))
            newest = max(rows, key=lambda r: int(r.get("ts") or 0))
            if newest.get("detail"):
                host["detail"] = newest["detail"]
            for r in rows:
                if r is not host:
                    drop.add(id(r))
            out["folded"] += len(rows) - 1
        if drop:
            items = [f for f in items if id(f) not in drop]
            changed = True
        marks["folds_v1"] = int(time.time())
    if not marks.get("retriage_v1"):
        old = [f for f in items
               if f.get("status") == "held"
               and _cross_folds(f)
               and not (f.get("triage") or {}).get("elevated_by_person")
               and int((f.get("triage") or {}).get("v") or 0)
               < triage.LOOK_VERSION]
        old.sort(key=lambda f: -int(f.get("ts") or 0))
        for f in old[:MIGRATION_RETRIAGE_MAX]:
            _send_to_look(f)
            out["retriaged"] += 1
            changed = True
        marks["retriage_v1"] = int(time.time())
    if changed:
        _write(items)
    if MIGRATIONS_FILE.parent.is_dir():
        try:
            atomic_write.write_json(MIGRATIONS_FILE, marks)
        except OSError as exc:
            log.info("could not write the findings migration marker: %s", exc)
    return out


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
            # The row's own settled stamp: `_shape` does not carry it, and
            # reading it off the shaped copy stamped every migrated answer
            # with the time of the migration.
            moved.append((_shape(entry), int(entry.get("settled_at") or 0)))
            continue
        kept.append(entry)
    for shaped, when in moved:
        _remember_settled(shaped, "ignored", when=when)
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
    # Every author on `FIX_AUTHORS` is a model, so its sentence is stored
    # in the house's words.
    fix = textclip.shorten(plain(str(fix or "").strip()), MAX_FIX)
    if (not fix or by not in FIX_AUTHORS or house_words.placeholder(fix)
            or house_words.fork(fix)):
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
        title = _rule_titled(src, str(entry.get("source_title") or ""))
        if src and title and src not in out:
            out[src] = title
    for entry in _load():
        src = str(entry.get("source") or "")
        title = _rule_titled(src, str(entry.get("source_title") or ""))
        if src and title:
            out[src] = title
    return out


# What a mute takes off the list: everything nobody has acted on. `fixing`
# and `fixed` are a person's or the fixer's and stay.
MUTE_CLEARS = ("open", "triaging", "held", "needs_you")


@_mutates
def refresh_details(objs: list[dict]) -> int:
    """Update the detail and severity of rows a producer has re-reported.

    A check's finding text is stable on purpose (the store dedupes by it),
    which leaves the number that changes — days left, since when — in
    ``detail``. Re-reporting through :func:`add_many` drops the row as
    known; this is the other half, so a battery forecast filed a week ago
    says "about 2 days" today rather than "about 9". Returns how many rows
    changed.

    **A held row whose severity ROSE goes back to be looked at.** `held` is
    a look's verdict about the row as it stood — a battery at 30% is not
    worth anybody's attention — and a re-report that raises it (the same
    battery at 4%, `warning` to `serious`) is new evidence the verdict was
    never given. It went on climbing off every screen, because a held row
    reaches no badge, no notification and no prompt, and nothing ever
    offered it again. It returns to `triaging`, which is what the
    Resident's sweep reads (`awaiting_triage`), so the next look judges it
    as it is now; a severity that fell, or stayed, leaves the verdict
    standing.

    Locked, like every other mutator here — it was the one that was not,
    and it writes the same file `record_triage` and the endings do from
    other threads.
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
            rose = _severity_rank(entry["severity"]) > _severity_rank(
                cur.get("severity"))
            moved = (str(cur.get("source") or "").startswith("check:")
                     and names_moved(cur.get("detail"), entry["detail"]))
            cur["detail"] = entry["detail"]
            cur["severity"] = entry["severity"]
            if rose and cur.get("status") == "held":
                _send_to_look(cur)
            elif moved:
                _verdict_outdated(cur)
            changed += 1
        new_items = clean_items(entry.get("items"))
        if new_items and clean_items(cur.get("items")) != new_items:
            # What a Wrong pressed on this row will answer is what it names
            # NOW, not what it named when it was filed.
            cur["items"] = new_items
            # And what it shows under Details, and folds other rows into
            # (`_devices_named`): a device that left the list leaves those.
            if str(cur.get("source") or "").startswith("check:") \
                    and "evidence" in entry:
                cur["evidence"] = _clean_evidence(entry.get("evidence"))
            changed += 1
        # A check's own sentence about what to do follows the check, so a
        # reworded rule reaches the rows it already filed. Only while the
        # rule is still the author (`fix_by` empty): a sentence a look, a
        # conversation or a person wrote is never put back.
        new_fix = entry.get("fix") or ""
        if (new_fix and not cur.get("fix_by")
                and str(cur.get("source") or "").startswith("check:")
                and cur.get("fix") != new_fix):
            cur["fix"] = new_fix
            changed += 1
    if changed:
        _write(items)
    return changed


# What a row whose look no longer applies says until the next look does.
LOOK_OUTDATED = ("What this reports has changed since brAIn last looked at "
                 "it, so it is shown as it is now until brAIn looks again.")

_MONTHS_DAYS = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|"
    r"february|march|april|june|july|august|september|october|november|"
    r"december|mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|today|yesterday|tomorrow)\b")


def _named_words(detail) -> set[str]:
    """The words a check's detail is made of, with what moves every pass —
    numbers, dates, a plural that follows a count — taken out."""
    text = _MONTHS_DAYS.sub(" ", str(detail or "").lower())
    words = re.findall(r"[^\W\d_]+", text)
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


def names_moved(old, new) -> bool:
    """Whether a check's re-report names different things, not merely a
    different count or time.

    `sys.entry_failed` is ONE row naming every integration that failed to
    load; a fourth joining the list is new evidence, while "since 3 Sep"
    becoming "since 4 Sep" is the same report. A check's detail is written
    by code, so its words are stable and only what it names moves them.
    """
    return _named_words(old) != _named_words(new)


def _verdict_outdated(entry: dict, now: float | None = None) -> None:
    """A look's verdict about what a row USED to say no longer stands.

    A held row goes back to `triaging`, `_absorb`'s rule. A row already on
    screen keeps its place — a row on the list never vanishes into a run —
    and its verdict is replaced by "nothing has looked at this as it is",
    which is the record the next look is offered (`unjudged_open`) and may
    answer (`late_verdict_welcome`). Never a row a person put back: a
    person overruling a verdict is not overruled back.
    """
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    if not record or record.get("elevated_by_person"):
        return
    stamp = int(now if now is not None else time.time())
    status = entry.get("status")
    if status == "held":
        _send_to_look(entry, stamp)
    elif status == "open" and record.get("verdict") != "untriaged":
        entry["triage"] = _clean_triage({
            "verdict": "untriaged", "reason": LOOK_OUTDATED, "at": stamp,
            "v": record.get("v")})
        entry["triaging_since"] = stamp


def _severity_rank(severity) -> int:
    try:
        return SEVERITIES.index(str(severity or "warning"))
    except ValueError:
        return SEVERITIES.index("warning")


@_mutates
def annotate(ts: int, line: str) -> dict | None:
    """Add one sentence to a row's detail, and nothing else.

    For a fact that arrived after the row did and belongs on the card —
    the safety lane's "the sensor reported dry at 03:14" — where rewriting
    the detail would lose what the row first said and a second row would
    be a second card about one event. Capped at the store's own detail
    limit by dropping from the FRONT of what came after the original, so
    the first sentence (what happened) is the one that survives.
    """
    line = str(line or "").strip()
    if not line:
        return None
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        detail = str(entry.get("detail") or "").strip()
        merged = f"{detail} {line}".strip() if detail else line
        entry["detail"] = textclip.shorten(merged, MAX_DETAIL)
        _write(items)
        return _shape(entry)
    return None


# How long a Resident case may sit unanswered before it is taken off the
# list, by its stakes. A case is a judgement about a moment, and the only
# lifecycle it had was a person ending it — so a low-stakes observation
# from March sat on the feed beside this morning's, and the feed stopped
# reading as now. These are generous on purpose: a person who has not
# answered in a fortnight has answered, and a high-stakes case gets a
# month because being wrong about it costs more than one more day of it.
# Safety cases are absent: what ends a leak is somebody looking.
CASE_TTL_BY_STAKES = {"low": 7 * 86400, "medium": 14 * 86400,
                      "high": 30 * 86400}
CASE_EXPIRES = ("open", "needs_you")


@_mutates
def expire_cases(now: float | None = None,
                 sources: tuple[str, ...] = (RESIDENT_SOURCE,)) -> list[dict]:
    """Take aged-out Resident cases off the list. Returns what went.

    `clear_resolved`'s rule rather than an ending's: no memory line and no
    ledger entry, because nobody said anything about the house — a case
    that expires was a judgement nobody took up, and if the thing it was
    about is still true the next look will say so again in today's words.
    Only `open`/`needs_you`: a plan somebody asked for, a fix in flight and
    a snoozed row are all a person's.
    """
    now = time.time() if now is None else now
    items = _load()
    kept, gone = [], []
    for entry in items:
        src = str(entry.get("source") or "")
        ttl = CASE_TTL_BY_STAKES.get(str(entry.get("stakes") or "medium"),
                                     CASE_TTL_BY_STAKES["medium"])
        if (src in sources and entry.get("status") in CASE_EXPIRES
                and not is_snoozed(_shape(entry), now)
                and now - float(entry.get("ts") or now) > ttl):
            gone.append(_shape(entry))
            continue
        kept.append(entry)
    if gone:
        _write(kept)
    return gone


# The states that are no reading at all, as a case's evidence records them:
# Home Assistant's two, and the word a device's own integration may report.
NO_READING = frozenset({"unavailable", "unknown", "offline"})
# Where a returned device ends a row. `fixing` and `fixed` are a run in
# flight and a change brAIn made, and a person's; `planned` is a plan about a
# fault that is over, which is a plan about nothing.
RETURN_CLEARS = ("open", "needs_you", "planned", "triaging", "held", "failed")


def _no_reading(value) -> bool:
    words = str(value or "").strip().lower().split()
    return bool(words) and words[0].strip(".,;:") in NO_READING


def _reported_missing(entry: dict) -> str:
    """The entity this row reports as giving no reading, or "".

    Read off the row's EVIDENCE — the values the run read — never off the
    claim's words: a sentence saying "offline" is prose, and a gate over
    prose is a name gate. The row's own entity, and an evidence row about
    that entity whose value was no reading."""
    eid = str(entry.get("entity_id") or "").strip()
    if not eid and str(entry.get("source") or "") == RESIDENT_SOURCE:
        # A case filed before its subject was recorded: the one device its
        # own evidence names (`case_subject`), never a guess past that.
        eid = case_subject(entry)
    if not eid:
        return ""
    for ev in entry.get("evidence") or []:
        if (isinstance(ev, dict) and str(ev.get("entity") or "") == eid
                and _no_reading(ev.get("value"))):
            return eid
    return ""


def _person_touched(entry: dict, now: float) -> bool:
    record = entry.get("triage") if isinstance(entry.get("triage"), dict) else {}
    if record.get("elevated_by_person"):
        return True
    if float(entry.get("snoozed_until") or 0) > now:
        return True
    if entry.get("fix_by") == "chat":
        return True
    return any(isinstance(t, dict) and t.get("who") == "you"
               for t in entry.get("thread") or [])


def _changed_at(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.timestamp()


# How long every entity a row names must have been reporting before a row
# saying it is offline comes off (#441): long enough that a device coming
# back for a minute between two drops does not end the card.
RETURN_SETTLE_S = 2 * 3600
# The producers whose rows the sweep never takes: a house check re-checks
# its own rows every pass (`clear_resolved`), and these are about harm or
# are somebody's own words.
RETURN_EXCLUDED = frozenset({"safety", "security", "correction"})

# A detail saying the trouble has stopped: "has reported since Saturday",
# "came back", "is back online". The negation window is read separately
# (`_says_recovered`), so "has not reported since Thursday" is no recovery.
_RECOVERED_RE = re.compile(
    r"\b(?:(?:has|have|had) (?:been )?report(?:ed|ing)(?: again)? since|"
    r"report(?:ed|ing|s) again|came back|come back|comes back|"
    r"(?:is|was|has been|are|were) back(?: online| up)?\b|back online|"
    r"reconnected|recovered|(?:available|online|reachable|responding) again)",
    re.I)
_NEGATION_RE = re.compile(r"\b(?:not|never|no longer|hasn't|haven't|hadn't|"
                          r"didn't|isn't|wasn't)\s+(?:\w+\s+){0,2}$", re.I)


def says_recovered(detail) -> bool:
    """Whether a row's own detail says the problem has stopped: its LAST
    word on the matter is a recovery, unnegated (#441)."""
    text = str(detail or "")
    last_back = -1
    for m in _RECOVERED_RE.finditer(text):
        if not _NEGATION_RE.search(text[max(0, m.start() - 30):m.start()]):
            last_back = m.start()
    if last_back < 0:
        return False
    downs = [m.start() for m in OFFLINE_RE.finditer(text)
             if not _NEGATION_RE.search(text[max(0, m.start() - 30):m.start()])]
    return not downs or max(downs) < last_back


def _sweepable(entry: dict, sources) -> bool:
    source = str(entry.get("source") or "")
    if source in RETURN_EXCLUDED or source.startswith("check:"):
        return False
    return sources is None or source in sources


def _named_entities(entry: dict) -> set[str]:
    """Every entity a row names: its own, its evidence's and ``about``."""
    out = _devices_named(entry) | set(entry.get("about") or ())
    eid = _reported_missing(entry)
    if eid:
        out.add(eid)
    return out


def _all_back(entry: dict, states: dict, now: float) -> bool:
    """Whether every entity a row says is offline has been reporting a real
    state for `RETURN_SETTLE_S` since the row was filed (#441). An entity
    the states do not hold was not looked at, so the row stays."""
    named = _named_entities(entry)
    if not named:
        return False
    filed = float(entry.get("ts") or now)
    for eid in named:
        live = states.get(eid)
        if (not isinstance(live, dict) or live.get("state") in (None, "")
                or _no_reading(live.get("state"))):
            return False
        since = max(_changed_at(live.get("last_changed")), filed)
        if now - since < RETURN_SETTLE_S:
            return False
    return True


@_mutates
def clear_returned(states, now: float | None = None,
                   sources: tuple[str, ...] | None = None) -> list[dict]:
    """Take off the list a row about a device that came back.

    ``states`` is ``{entity_id: {state, last_changed}}`` — the snapshot a
    checks pass already fetched, never a read of its own. Two ways a row
    is over, both `clear_resolved`'s ending (no memory line, no ledger
    entry, and if it goes again the next look says so in today's words):

      * a Resident case whose evidence says its entity gave no reading,
        once that entity reports a real state that CHANGED after the row
        was filed;
      * a row from any producer that does not re-check its own rows — the
        Resident, the overnight check, an insight card (#441) — that says
        something is offline, unavailable or not reachable (its evidence,
        or failing that its title), once EVERY entity it names has
        reported a real state for `RETURN_SETTLE_S` after the filing. A
        house check is left to `clear_resolved`, which re-runs the rule.

    And a row whose own detail says the trouble has stopped while its
    title says it is still happening (`says_recovered`) does not keep that
    title: it is over by its own account. Never `fixing`/`fixed`, never a
    row a person touched (put back, snoozed, a chat's advice, a reply on
    its thread), never the harm family (`RETURN_EXCLUDED`).
    """
    if not isinstance(states, dict):
        states = {}
    now = time.time() if now is None else now
    items = _load()
    kept, gone = [], []
    for entry in items:
        if (entry.get("status") not in RETURN_CLEARS
                or not _sweepable(entry, sources)
                or _person_touched(entry, now)):
            kept.append(entry)
            continue
        over = False
        if str(entry.get("source") or "") == RESIDENT_SOURCE:
            eid = _reported_missing(entry)
            live = states.get(eid) if eid else None
            over = (isinstance(live, dict)
                    and live.get("state") not in (None, "")
                    and not _no_reading(live.get("state"))
                    and _changed_at(live.get("last_changed"))
                    > float(entry.get("ts") or now))
        down = bool(_reported_missing(entry)) or is_drop_report(entry)
        if not over and down and states:
            over = _all_back(entry, states, now)
        if not over and down and says_recovered(entry.get("detail")):
            over = True
        if over:
            gone.append(_shape(entry))
            continue
        kept.append(entry)
    if gone:
        _write(kept)
    return gone


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
    came = _came_back(kept, sources, keep_keys, time.time())
    if gone or came:
        _write(kept)
    # And the answers. The same pass that may clear a row it no longer
    # reports may end an answer about one — see `_suppresses`.
    lapse_settled(sources, keep_keys)
    # And the other half of an answer: a chore ticked off while the check
    # that filed it still reports it is not done, so it goes back on the
    # list and its ledger entry back to `accepted` (the work is waiting
    # again). Here, so the scheduled pass, "Check again" and a delayed
    # verification are one rule with three callers.
    _chores_came_back(sources, keep_keys)
    # And a finding somebody marked fixed by hand: the same claim a ticked
    # chore makes, checked the same way.
    _hand_fixes_came_back(sources, keep_keys)
    return gone


def _hand_fixes_came_back(sources: set[str], keep_keys: set[str],
                          now: float | None = None) -> int:
    """End a person's "I've fixed it" on a check's row that the check still
    reports past `todo_store.CHORE_SETTLE_S`.

    `lapse_settled` ends an answer when the check STOPS reporting; nothing
    ended one whose check went on reporting it, so a fix that did not hold
    was deduped on every pass for the life of the install — the decision
    trail saying "you said you had fixed it" ten times a day about a card
    that never came back. A ticked chore already comes back on exactly this
    evidence (`_chores_came_back`); this is the same rule for the same
    claim made with a different button. The answer LAPSES, so the next
    pass files the row again as a recurrence (`recurred`, `previous_at`)
    through `triage.gate` like any other report — nothing is filed from
    here. Only `fixed` (never Wrong, never a chore waiting as `accepted`),
    only a house check's, only a check that ran. Returns how many lapsed.
    """
    import todo_store  # noqa: PLC0415 — the store imports nothing of ours

    now = time.time() if now is None else float(now)
    ledger = _load_settled()
    lapsed = 0
    for entry in ledger:
        source = str(entry.get("source") or "")
        if (entry.get("kind") == "fixed"
                and not entry.get("lapsed_at")
                and source.startswith("check:") and source in sources
                and str(entry.get("key") or "") in keep_keys
                and now - float(entry.get("ts") or now)
                >= todo_store.CHORE_SETTLE_S):
            entry["lapsed_at"] = int(now)
            entry["came_back_at"] = int(now)
            lapsed += 1
    if lapsed:
        try:
            _write_settled(ledger)
        except OSError as exc:
            log.warning("could not call back a fix a check still reports: "
                        "%s", exc)
            return 0
    return lapsed


def _chores_came_back(sources: set[str], keep_keys: set[str]) -> list[dict]:
    import todo_store  # noqa: PLC0415 — the store imports nothing of ours
    try:
        due = todo_store.still_reported(sources, keep_keys)
        if not due:
            return []
        back = todo_store.came_back([i["id"] for i in due])
    except OSError as exc:
        log.warning("could not reopen chores a check still reports: %s", exc)
        return []
    for item in back:
        if item.get("finding_key"):
            remember_answer(item["finding_key"], item["text"], "accepted",
                            source=item.get("source", ""),
                            source_title=item.get("source_title", ""))
    return back


# How long after a brAIn fix ends before the check that filed the row may
# call it back. A fix that restarts an integration or an add-on takes a
# moment to be visible to a check, and a pass that happened to land inside
# that moment would reopen a row brAIn had just fixed.
FIX_SETTLE_S = 120
CAME_BACK_RESULT = ("Came back: the check that reported this still reports "
                    "it after brAIn's fix, so the fix did not hold.")


def _came_back(items: list[dict], sources: set[str], keep_keys: set[str],
               now: float) -> int:
    """Reopen a row brAIn fixed that its own check still reports.

    `fixed` is set from the fix run's own reading of what it did, and a row
    in `fixed` is in no list a re-report can reach: `add_many` dedupes it,
    `refresh_details` and `clear_resolved` skip it. So a card could sit
    green while the check that filed it saw the fault every pass. The
    check that RAN is the verification: still reported, past the settling
    moment, is a fix that did not hold, and the row goes back to `open`
    saying so — which is a different claim from a new report, and the
    reason it is the same row rather than a second one.

    Only a house check's row, only a row brAIn fixed (a `fix_ended` stamp),
    and only a check that ran. Modifies ``items`` in place; returns how
    many came back.
    """
    came = 0
    for f in items:
        if (f.get("status") != "fixed"
                or f.get("source") not in sources
                or not str(f.get("source") or "").startswith("check:")
                or normalize(f.get("text", "")) not in keep_keys):
            continue
        ended = float(f.get("fix_ended") or 0)
        if not ended or now - ended < FIX_SETTLE_S:
            continue
        f["status"] = "open"
        f["came_back"] = int(now)
        f["result"] = CAME_BACK_RESULT
        came += 1
    return came


@_mutates
def append_thread(ts: int, who: str, text: str, *, when: float | None = None,
                  tell: dict | None = None) -> dict | None:
    """Add one turn to a case's conversation. Returns the row, or None.

    The thread is what was said ABOUT a case — the person's reply typed in
    Morph, and brAIn's answer or one-sentence account of what it did — so
    it rides on the row rather than in a store of its own: it goes when the
    row goes, which is when the case has ended. Capped at
    `MAX_THREAD_TURNS`, oldest first, and each turn at `MAX_THREAD_TEXT`.
    None for a row that is gone (the case ended meanwhile, an ordinary
    race) and for a turn with nothing in it.
    """
    if who not in THREAD_WHO:
        return None
    turn: dict = {"who": who, "text": str(text or ""),
                  "at": int(when if when is not None else time.time())}
    if who == "brain" and isinstance(tell, dict):
        turn["tell"] = tell
    if not _clean_thread([turn]):
        return None
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != int(ts):
            continue
        entry["thread"] = _clean_thread(
            list(entry.get("thread") or []) + [turn])
        _write(items)
        return _shape(entry)
    return None


def by_morph_key(key: str) -> dict | None:
    """The live row Morph filed under this key, or None."""
    key = clean_morph_key(key)
    if not key:
        return None
    for entry in _load():
        if (entry.get("morph_key") == key
                and entry.get("source") == MORPH_SOURCE):
            return _shape(entry)
    return None


@_mutates
def withdraw_morph_key(key: str) -> list[dict]:
    """Take Morph's own suggestion off the list. Returns the rows removed.

    `clear_resolved`'s ending, reached by the producer that filed it: no
    memory line and no ledger entry, because Morph withdrawing a suggestion
    says nothing about the house — if it suggests the same thing again it
    is filed again. Only a `source: morph` row in a status nobody is
    working on is taken.
    """
    key = clean_morph_key(key)
    if not key:
        return []
    items = _load()
    gone = [e for e in items if e.get("morph_key") == key
            and e.get("source") == MORPH_SOURCE
            and e.get("status") in CLEARABLE]
    if not gone:
        return []
    keep = [e for e in items if e not in gone]
    _write(keep)
    return [_shape(e) for e in gone]


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

# A producer's own rows its next run answers for (`own_reports`): the
# statuses nothing but brAIn has moved a row to, and how many a prompt
# lists. A row past the cap is not shown, so it is never cleared by a run
# that could not have answered for it (`clear_unreported`).
OWN_STATUSES = ("open", "triaging", "held")
PROMPT_OWN = 8
# Producers that are not a card's run and must never be cleared by one:
# the subject fold's own exclusions, plus the Resident, whose case IS the
# look and ages out by its own clock (`expire_cases`).
OWN_EXCLUDED = SUBJECT_FOLD_EXCLUDED | {RESIDENT_SOURCE, "resident"}


def _rerun_may_answer(entry: dict) -> bool:
    """Whether a producer's next run may clear this row by not reporting it.

    Only a row nothing but brAIn has moved: a snooze, a person putting a
    held row back, a plan somebody asked for (kept after a Cancel), the
    advice a conversation wrote, a fix in flight or done — each is a person
    in the row's history, and a run reading the house again is not evidence
    about what a person decided.
    """
    if entry.get("status") not in OWN_STATUSES:
        return False
    if int(entry.get("snoozed_until") or 0):
        return False
    if (entry.get("triage") or {}).get("elevated_by_person"):
        return False
    if entry.get("plan") or entry.get("fix_by") == "chat":
        return False
    return True


def own_reports(source: str) -> list[dict]:
    """The live rows ``source`` filed that its next run answers for.

    For a card's run, newest first, capped at `PROMPT_OWN`. Never a check's
    (a check clears through `clear_resolved`) and never one of
    `OWN_EXCLUDED`.
    """
    source = str(source or "")
    if not source or ":" in source or source in OWN_EXCLUDED:
        return []
    rows = [_shape(e) for e in _load()
            if e.get("source") == source and _rerun_may_answer(e)]
    rows = [r for r in rows if r["text"]]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:PROMPT_OWN]


@_mutates
def clear_unreported(source: str, shown, keep_keys,
                     keep_entities=()) -> list[dict]:
    """Drop the rows a card's successful run was shown and did not report.

    `clear_resolved`'s rule for a producer that is a run rather than a
    check: the card read the house again, was shown each of these as its
    own to report again if the data still showed it (`prompt_block`'s
    ``own``), and did not. Only rows it was shown (``shown``, their ids),
    only rows still answerable when the run lands — minutes can pass and a
    person may have pressed something meanwhile — and none it reported
    again, by its words or by the entity it named. Nothing is written to
    the settled ledger and no memory line is queued: a problem the data no
    longer shows is not a fact about the house, and if it comes back the
    card files it again. Returns the rows removed.
    """
    source = str(source or "")
    if not source or ":" in source or source in OWN_EXCLUDED:
        return []
    shown = {int(t) for t in shown or ()}
    keep_keys = set(keep_keys or ())
    keep_entities = {e for e in keep_entities or () if e}
    items = _load()
    kept: list[dict] = []
    gone: list[dict] = []
    for f in items:
        if (int(f.get("ts") or 0) in shown
                and f.get("source") == source
                and _rerun_may_answer(f)
                and normalize(str(f.get("text") or "")) not in keep_keys
                and str(f.get("entity_id") or "") not in keep_entities):
            gone.append(_shape(f))
            continue
        kept.append(f)
    if gone:
        _write(kept)
    return gone


def _covered(row: dict, covers: dict, names: dict) -> bool:
    """Whether a live row is about something a card covers: an entity the
    card named, one of its domains, or one of its device classes. A card
    with no domains (the overview, an asked question) covers everything."""
    eids = {str(row.get("entity_id") or "")}
    for ev in row.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("entity"):
            eids.add(str(ev["entity"]))
    eids.discard("")
    if eids & set(covers.get("entities") or ()):
        return True
    domains = set(covers.get("domains") or ())
    if not domains:
        return True
    classes = set(covers.get("classes") or ())
    for eid in eids:
        if eid.split(".", 1)[0] in domains:
            return True
        row_name = names.get(eid)
        if isinstance(row_name, dict) and row_name.get("class") in classes:
            return True
    return False


def _words(text: str) -> set[str]:
    out = set()
    for w in normalize(text).split():
        if len(w) < 2 or w in _TURNED_DOWN_STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def turned_down(text: str, entities=()) -> dict | None:
    """The settled Wrong a card's finding or suggestion says again, or None.

    The same words are the same report whatever they name; a report naming
    the entity a Wrong was about is the same report when it carries most
    of that Wrong's words ("make the double-tap scene leave the hallway
    light on" after "the hallway double-tap scene turns the hallway light
    off" was waved away). A different problem on the same entity is not:
    "the hallway light has been unavailable since Tue" shares the name and
    nothing else, and still files. Never raises: a ledger that cannot be
    read turns nothing down, the direction in which being wrong shows a
    card."""
    try:
        key = normalize(text)
        if not key:
            return None
        named = {str(e) for e in entities or () if e}
        said = _words(text)
        for entry in _load_settled():
            if entry.get("kind") != "ignored":
                continue
            if entry.get("key") == key or normalize(entry.get("text")) == key:
                return entry
            eid = str(entry.get("entity_id") or "")
            if not eid or eid not in named:
                continue
            theirs = _words(entry.get("text") or "")
            if theirs and len(theirs & said) / len(theirs) >= TURNED_DOWN_SHARE:
                return entry
    except Exception:  # noqa: BLE001 — "could not read" turns nothing down
        return None
    return None


def prompt_block(exclude_sources=(), own=None, figures: bool = False,
                 covers: dict | None = None) -> str:
    """What the analyst needs to know about findings before it reports more.

    ``exclude_sources`` leaves a producer's own live rows out, and exists
    for one reader: a card's refresh gate, which must not read the rows the
    card itself filed as news about the house. A card files its findings as
    `triaging`, which this block does not list, and the moment the Resident
    promoted one to `open` the next fingerprint differed — the card had
    triggered its own refresh.

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
    skip = {str(x) for x in exclude_sources or () if x}
    own = [r for r in own or () if isinstance(r, dict) and r.get("text")]
    own_ts = {int(r.get("ts") or 0) for r in own}
    live = [f for f in everything if f["status"] in LIVE_STATUSES
            and f.get("source") not in skip
            and int(f.get("ts") or 0) not in own_ts]
    if covers is not None:
        # A card's own subject first: the newest twelve of a busy list
        # left out the row about the dehumidifier the climate card then
        # called fine.
        names = _names_now()
        mine = [f for f in live if _covered(f, covers, names)][:PROMPT_COVERED]
        rest = [f for f in live if f not in mine]
        live = mine + rest[:max(0, PROMPT_OPEN - len(mine))]
    else:
        live = live[:PROMPT_OPEN]

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

    # What the household turned down about what this card covers, read off
    # the ledger by entity rather than by age: on a house that answers
    # things, the newest twenty across every device had long since pushed
    # out the one about this card's own light.
    declined: list[dict] = []
    if covers is not None:
        names = _names_now()
        seen_keys: set[str] = set()
        for entry in settled_listing():
            if entry.get("kind") != "ignored" or not entry.get("entity_id"):
                continue
            key = normalize(entry.get("text") or "")
            if not key or key in seen_keys:
                continue
            if _covered(entry, covers, names):
                seen_keys.add(key)
                declined.append(entry)
            if len(declined) >= PROMPT_TURNED_DOWN:
                break
    declined_keys = {normalize(e.get("text") or "") for e in declined}
    ignored = [(t, n) for t, n in _settled("ignored",
                                            PROMPT_IGNORED + len(declined))
               if normalize(t) not in declined_keys][:PROMPT_IGNORED]
    fixed = _settled("fixed", PROMPT_FIXED)
    parts: list[str] = []
    if own:
        # The run's OWN earlier reports, apart from the list it must not
        # repeat: told never to report them again, a run could not say the
        # data still showed one, and the row stayed open for ever after
        # the data stopped supporting it (`clear_unreported`).
        parts.append(
            "WHAT THIS CARD REPORTED BEFORE, still on the findings list. "
            "Report one again in `findings` (its words, or yours with the "
            "same entity_id) ONLY if what you read now still shows it. One "
            "you do not report again is taken off the list as no longer "
            "true — so if you could not check one, report it again rather "
            "than leave it out:")
        parts += [f"- {r['text']}"
                  + (f" ({r['entity_id']})" if r.get("entity_id") else "")
                  for r in own]
        parts.append("")
    if live and figures:
        # A card about a device a live row is about tells one story with
        # the row, so it is handed the row's own name, figures and window
        # (`figures`, the card prompt's call only: a check rewrites its
        # detail every pass, and the refresh fingerprint reads this block
        # without it so a moved number on somebody else's row is not news).
        names = _names_now()
        parts.append(
            "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT report these "
            "again. When this card talks about a device one of them covers, "
            "call it by the name shown, quote that row's figures and time "
            "window rather than working out different ones — a count over a "
            "different window says which window, in words (\"7 since Sat; "
            "the row's 14 is over 7 days\") — and mention it "
            "in one clause rather than retelling it. A card that reads one of "
            "these as already fixed lists its entity_id in `fixed`, and "
            "brAIn asks that row's own check again. Never reach a different "
            "verdict about that device: take that row's conclusion as this "
            "card's own, or, if what you read disagrees with it, say why in "
            "one clause. Never call a device, door or automation fine, safe "
            "or normal while a row here says otherwise about it: mention "
            "that row instead. A figure from a sensor a row calls offline, "
            "stuck, on a dead battery or unreliable is doubtful, and the "
            "card says so wherever it quotes one:")
        for f in live:
            eid = str(f.get("entity_id") or "")
            row = names.get(eid)
            name = (row.get("name") if isinstance(row, dict) else row) or ""
            about = (f" ({name}, {eid})" if name and eid
                     else f" ({eid})" if eid else "")
            detail = textclip.clip(str(f.get("detail") or "").strip(),
                                   PROMPT_DETAIL)
            parts.append(f"- {f['text']}{about}"
                         + (f"\n  {detail}" if detail else ""))
    elif live:
        parts.append(
            "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT report these again:")
        parts += [f"- {f['text']}" for f in live]
    if declined:
        names = _names_now()
        parts.append(
            "\nWHAT THE HOUSEHOLD HAS ALREADY TURNED DOWN ABOUT WHAT THIS CARD "
            "COVERS — do not raise these again, as a finding, an opportunity "
            "or a change suggested in the summary, unless something new "
            "happened; where they said why, that reason stands:")
        for entry in declined:
            eid = str(entry.get("entity_id") or "")
            row = names.get(eid)
            name = (row.get("name") if isinstance(row, dict) else row) or ""
            about = f" ({name}, {eid})" if name else f" ({eid})"
            note = str(entry.get("note") or "").strip()[:MAX_NOTE]
            parts.append(f"- {entry.get('text', '')}{about}"
                         + (f"\n  They said: {note}" if note else ""))
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
