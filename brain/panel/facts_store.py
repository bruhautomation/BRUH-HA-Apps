"""The facts under the memory document — tagged, dated, and traceable.

``memory.md`` stays what it has always been: the human-readable document
the consolidator owns and the homeowner edits. Nothing here writes it.
What this adds is the layer *underneath* it — one row per durable fact,
carrying the three things a paragraph cannot:

* **a subject**, so a fact can be looked up by the thing it is about
  (``sensor.garage_fridge_temp``, ``area:lounge``, ``person:ben``, or
  ``house`` for a standing preference);
* **a predicate**, which is empty for an ordinary fact and
  ``exception:<check_id>`` for the one shape that has to reach code — a
  correction that stops a rule firing on one entity;
* **provenance**, which is the source, the date and the run id, so the
  House view can answer *why do you think that?* with a link to the run
  rather than with a shrug.

Three claims about this store, each of which is why it is a store and
not a second document.

**It is not a second writer of memory.md.** Every fact here arrives
through the memory inbox, which is the queue every writer already uses,
and :func:`ingest_inbox` is a *reader* of that queue: the consolidator
goes on filing the same lines into the document, and neither pass can
see the other's work. A fact filed here and a paragraph filed there are
two renderings of one line, which is the point — the document is what a
person reads and this is what a prompt and a check read.

**Retrieval replaces the whole document in a prompt, not the document
itself.** ``ha_data`` used to paste up to 66 KB of memory into every
insight bundle because there was no way to ask which part of it was
about this run's entities. :func:`retrieval_block` is that question, and
its answer is a couple of kilobytes: the core facts (the standing
preferences, which are subject ``house`` and ``person:*``) plus the
facts about the entities and areas the run is actually reading.

**Nothing here decides anything.** :func:`exceptions` and
:func:`exception_map` answer "has the homeowner said this rule is wrong
about this entity", and the checks decide what to do with the answer —
the same split ``baselines.py`` and ``closures.py`` keep, and for the
same reason: a store that also suppressed findings would be two rules in
one place with the threshold invisible.

The file is ``/config/.brain/memory/facts.json`` rather than ``/data``
for the reason the memory document is: both halves of this add-on read
it and only one of them is the panel. The panel writes it as root and
the consolidator, the study watcher and the terminal read it as the
``claude`` user, so a file created fresh is handed to that user the way
``atomic_write`` hands over a lock — root can give a file away and the
reverse is not true, which is exactly how ``run-sources.jsonl`` went
silently unwritable once before.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import atomic_write
import categories
import ha_data

# Under /config, beside the document it is the other half of. `/data` is
# invisible to Home Assistant and to everything that is not the panel.
FACTS_FILE = Path(os.environ.get(
    "BRAIN_FACTS_FILE", "/config/.brain/memory/facts.json"))
# What `ingest_inbox` has already read. Its own file: the facts store is
# the knowledge and this is bookkeeping about a queue, and a reader that
# had to load one to answer a question about the other would be two
# things kept in one place for no reason.
INGEST_STATE_FILE = Path(os.environ.get(
    "BRAIN_FACTS_INGEST_STATE", "/config/.brain/memory/facts-ingest.json"))

# Enough for years of a talkative house. The cap takes the oldest first,
# and never a correction or an exception before an ordinary fact: those
# are the two kinds somebody TYPED, and dropping one silently restores a
# rule they turned off.
MAX_FACTS = 2000
# How many facts about one subject a retrieval may carry when that
# subject was not asked for by name. Without it a house with forty facts
# about the boiler answers every question with the boiler.
PER_SUBJECT_CAP = 3
MAX_TEXT = 500
MAX_SUBJECT = 255
MAX_PREDICATE = 64
MAX_SUBJECTS = 12
# The default prompt budget. `ha_data` passes its own, which is bounded
# by `memory_budget()` as well — a retrieval is allowed to be smaller
# than the document's cap and never larger.
RETRIEVAL_CHARS = 1500

# Where a fact came from. A source outside this set is kept as itself
# rather than rewritten: a new writer showing its own tag is odd, and
# showing nothing is a lie (`kSourceLabel`'s rule, one surface over).
SOURCES = (
    "correction", "card", "study", "voice", "chat", "terminal", "person",
    "check", "assist", "insights", "panel", "reply", "hook", "homeowner",
    "confirmed", "curiosity", "resident", "feedback", "user", "automation",
)
# A correction is what somebody typed to say brAIn had it wrong, and an
# exception is the machine-readable half of one. Neither may be pruned
# to make room for a fact an analyst discovered.
KEEP_SOURCES = ("correction", "person")
EXCEPTION_PREFIX = "exception:"

# The inbox writes confidence as a word (`_queue_memory_fact`,
# `remember_fact`, the assist reflection). One translation, here, because
# the store's own vocabulary is a number and two spellings of "how sure
# is this" is the drift a second copy always produces.
CONFIDENCE_WORDS = {"high": 0.9, "medium": 0.7, "low": 0.4}
DEFAULT_CONFIDENCE = 0.7

# A line the consolidator reads as "strike this from the document" is an
# instruction rather than a fact, and filing it would make the store
# assert the very thing somebody asked to have removed.
FORGET_PREFIX = "FORGET:"

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")
# Words that carry no signal in a lexical overlap and appear in nearly
# every sentence. Short on purpose: a long stoplist starts removing the
# words a house actually talks about.
_STOPWORDS = frozenset((
    "the", "a", "an", "is", "are", "was", "were", "it", "its", "this",
    "that", "these", "those", "and", "or", "but", "if", "then", "of",
    "in", "on", "at", "to", "for", "with", "by", "from", "as", "be",
    "been", "has", "have", "had", "do", "does", "did", "not", "no",
    "so", "than", "when", "what", "which", "who", "why", "how", "all",
    "any", "my", "our", "their", "there", "here", "about", "into",
))


def normalize(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form, for deduplication.

    The same shape `knowledge_store.normalize` and
    `findings_store.normalize` use: two lines that say the same thing in
    different punctuation are one fact, and a store that thought
    otherwise would announce every correction twice.
    """
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def fact_id(subject: str, text: str, predicate: str = "") -> str:
    """The id of a fact, derived from what it says about what.

    Content, not a stamp: nothing that writes into the memory inbox mints
    an id and `ts` is not unique — one insight run queues three facts
    inside the same second — so two lines that make the same claim about
    the same subject ARE one fact, whichever writer produced them.

    An exception's predicate is part of WHAT it says. Two Wrongs on one
    sensor under two checks carry the same pre-filled reason ("That is
    normal for this sensor.") far more often than not, and keyed on the
    text alone the second overwrote the first's predicate — so the rule
    turned off first quietly came back on. An ordinary fact has no
    predicate and keeps the id it always had.
    """
    tail = f"\x00{predicate}" if predicate else ""
    return hashlib.sha256(
        f"{subject}\x00{normalize(text)}{tail}".encode("utf-8", "replace")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    try:
        with open(FACTS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = data.get("facts") if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _share(path: Path) -> None:
    """Hand a freshly created store to the user that also reads it.

    `atomic_write` preserves an existing file's owner and cannot invent
    one for a file that did not exist, so a store first written by the
    panel (root) is root's — and the consolidator, the study watcher and
    the terminal all run as `claude`. Root can give a file away; the
    reverse is not true, which is why this happens on the way in rather
    than being noticed later as a permission error nothing reports.
    """
    uid, gid = atomic_write._lock_owner(path)
    if uid < 0:
        return                      # a dev checkout: one user owns everything
    try:
        if path.stat().st_uid == uid:
            return
        os.chown(path, uid, gid)
    except OSError:
        # Not root, or a filesystem that will not. The store is written
        # either way; what is lost is the other half being able to read
        # it, and there is nothing this can do about that here.
        pass


def writable() -> bool:
    """The store lives beside the document and never creates its directory.

    `findings_store.publish_state`'s rule: a dev checkout must not grow a
    stray `/config`, and neither may the suite, where the inbox is patched
    to a temp directory far more often than this file is. run.sh creates
    `/config/.brain/memory` before the panel starts, so on a real install
    the parent is always there and a missing one is exactly the checkout.
    """
    try:
        return FACTS_FILE.parent.is_dir()
    except OSError:
        return False


def _write(rows: list[dict]) -> None:
    if not writable():
        return
    existed = FACTS_FILE.exists()
    atomic_write.write_json(FACTS_FILE, {"facts": rows})
    if not existed:
        _share(FACTS_FILE)


def _locked():
    """This store's lock, read off the module attribute at call time.

    `knowledge_store._locked`'s reason exactly: every mutation here is a
    read-modify-write of one JSON file, they run on the panel's thread
    pool, and the consolidator and the study watcher are other processes
    reading the same path.
    """
    return atomic_write.locked(FACTS_FILE)


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------

_SCAN: dict = {}


def _entity_scanner():
    """A *search* form of the repo's own entity-id pattern, or None.

    `ha_data.ENTITY_ID_RE` is the authority on what an entity id looks
    like and it is anchored, because everywhere else in the panel an id
    is validated rather than found. Here it has to be found inside a
    sentence, so the anchors become word boundaries and nothing else: a
    second spelling of the id grammar would be a second answer to "is
    that an entity", and the two would drift the day one moved.
    """
    found = _SCAN.get("re")
    if found is None:
        body = ha_data.ENTITY_ID_RE.pattern
        if body.startswith("^"):
            body = body[1:]
        if body.endswith("$"):
            body = body[:-1]
        found = re.compile(r"(?<![\w.])(?:" + body + r")(?![\w.])")
        _SCAN["re"] = found
    return found


def tag_subjects(text: str, *, known_entities=frozenset(),
                 areas: dict | None = None, person: str = "") -> list[str]:
    """Every subject one fact is about, deterministically.

    No model call, ever: this runs on the panel's minute tick over every
    queued line, and a model asked which entity a sentence is about would
    be a model call per fact to decide how to file a fact.

    Three passes and a fallback. Entity ids written out in the text are
    subjects (filtered by `known_entities` when the caller has a list —
    a sentence about "the light.kitchen automation" names a real entity,
    where `version.2` does not). An area whose NAME appears as whole
    words is `area:<id>`, because people write "the lounge" and not
    "area:lounge". A `person` given by the caller is `person:<id>`. And
    a fact about nothing in particular is about the `house`, which is
    what makes the core-facts half of a retrieval possible at all.
    """
    body = str(text or "")
    low = body.lower()
    out: list[str] = []

    def take(subject: str) -> None:
        if subject and subject not in out and len(out) < MAX_SUBJECTS:
            out.append(subject)

    scanner = _entity_scanner()
    if scanner is not None:
        for eid in scanner.findall(low):
            if known_entities and eid not in known_entities:
                continue
            take(eid[:MAX_SUBJECT])
    for area_id, name in (areas or {}).items():
        label = str(name or "").strip().lower()
        if not label:
            continue
        if re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", low):
            take(f"area:{area_id}"[:MAX_SUBJECT])
    if person:
        take(f"person:{person}"[:MAX_SUBJECT])
    if not out:
        take("house")
    return out


def subject_kind(subject: str) -> str:
    """`entity`, `area`, `person`, `check` or `house` — for the summary."""
    head = str(subject or "").split(":", 1)[0]
    if head in ("area", "person", "check"):
        return head
    return "house" if subject == "house" else "entity"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _clean_confidence(value) -> float:
    if isinstance(value, str):
        return CONFIDENCE_WORDS.get(value.strip().lower(), DEFAULT_CONFIDENCE)
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def add(text: str, *, subject: str = "", source: str = "panel",
        confidence=DEFAULT_CONFIDENCE, run_id: str = "", predicate: str = "",
        expires: str = "", ts: float | None = None,
        extra_subjects=(), about: str = "", finding_key: str = "",
        near_dedupe: bool = False) -> tuple[dict | None, bool]:
    """Record one fact. Returns ``(fact, created)``.

    A re-add is not a second fact: the id is the subject plus the
    normalised text (plus the predicate, for an exception), so the same
    claim from the same subject refreshes `ts` and `observed` — it is
    still true today — and keeps the `first_seen` it already had, which
    is the date that says how long this house has been like this.

    ``near_dedupe`` widens "the same claim" to a paraphrase of it, and is
    what the inbox sweep asks for: the Stop-hook extractor reads
    overlapping windows of one conversation and says the same thing in new
    words on consecutive turns, and every one of those used to become a
    row of its own. See `_near_duplicate` for what counts.

    ``about`` and ``finding_key`` ride only on an exception: the report a
    Wrong was pressed on, so a prompt reading the rule can say what it was
    about, and that report's settled-ledger key, so the press that puts the
    report back in play can also take the rule away.
    """
    text = str(text or "").strip()[:MAX_TEXT]
    if not text or not writable():
        return None, False
    subject = str(subject or "house").strip()[:MAX_SUBJECT] or "house"
    predicate = str(predicate or "").strip()[:MAX_PREDICATE]
    now = time.time() if ts is None else float(ts)
    subjects: list[str] = [subject]
    for extra in extra_subjects or ():
        extra = str(extra or "").strip()[:MAX_SUBJECT]
        if extra and extra not in subjects and len(subjects) < MAX_SUBJECTS:
            subjects.append(extra)
    key = fact_id(subject, text, predicate if _is_exception_predicate(predicate)
                  else "")
    with _locked():
        rows = _load()
        same = None
        for row in rows:
            if row.get("id") == key:
                same = row
                break
        if same is None and near_dedupe and not predicate:
            same = _near_duplicate(rows, text, subjects)
        if same is not None:
            row = same
            row["ts"] = max(int(now), int(row.get("ts") or 0))
            row["observed"] = _day(max(now, float(row.get("ts") or 0)))
            # A later sighting may know more than the first did —
            # a run id, an expiry, a tighter subject list — and may
            # not know less: an empty field is not a correction.
            if run_id:
                row["run_id"] = str(run_id)[:64]
            if predicate:
                row["predicate"] = predicate
            if expires:
                row["expires"] = str(expires)[:10]
            if about:
                row["about"] = str(about)[:MAX_TEXT]
            if finding_key:
                row["finding_key"] = str(finding_key)[:MAX_TEXT]
            # Seen again is seen again, whatever the reconcile last said:
            # a fact somebody re-teaches is pending until the consolidator
            # has had its say about it a second time.
            row.pop("gone_since", None)
            for extra in subjects:
                kept = row.get("subjects")
                if not isinstance(kept, list):
                    kept = [row.get("subject") or subject]
                if extra not in kept and len(kept) < MAX_SUBJECTS:
                    kept.append(extra)
                row["subjects"] = kept
            _write(rows)
            return dict(row), False
        entry = {
            "id": key,
            "subject": subject,
            "subjects": subjects,
            "predicate": predicate,
            "text": text,
            "source": str(source or "panel")[:32],
            "confidence": _clean_confidence(confidence),
            "observed": _day(now),
            "ts": int(now),
            "first_seen": int(now),
            "run_id": str(run_id or "")[:64],
            "expires": str(expires or "")[:10],
        }
        if about:
            entry["about"] = str(about)[:MAX_TEXT]
        if finding_key:
            entry["finding_key"] = str(finding_key)[:MAX_TEXT]
        rows.append(entry)
        _write(_prune(rows))
    return dict(entry), True


def _is_exception_predicate(predicate: str) -> bool:
    return str(predicate or "").startswith(EXCEPTION_PREFIX)


# What makes two sentences one fact, for the inbox sweep. Deliberately a
# lexical test and never a model: it runs on the minute over every queued
# line (`tag_subjects`' reason). The bar is high and the floor is real,
# because the failure in the other direction is worse than a duplicate —
# two claims merged into one is a claim the store no longer holds.
NEAR_DUP_SHARE = 0.8
NEAR_DUP_MIN_TOKENS = 3
# Words the overlap stoplist drops that a SAME-FACT test may not: "the
# porch light is on a timer" and "the porch light is not on a timer" share
# every content word and say opposite things.
_NEGATIONS = frozenset((
    "not", "no", "never", "nor", "without", "cannot", "t", "isn", "aren",
    "wasn", "weren", "don", "doesn", "didn", "won", "can", "shouldn",
    "mustn", "off",
))


def _claim_tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split()
            if w and (w not in _STOPWORDS or w in _NEGATIONS)}


def _near_duplicate(rows: list[dict], text: str,
                    subjects: list[str]) -> dict | None:
    """The row this sentence is a rewording of, or None.

    Same subject (any of them), no predicate, and a Jaccard overlap of the
    claim's own words at `NEAR_DUP_SHARE` or better — with negations kept
    as words, because a dedupe that read "is" and "is not" as the same
    sentence would merge a fact into the correction that replaced it.
    Short sentences are never merged: three words in common is most of a
    four-word sentence and none of its meaning.
    """
    mine = _claim_tokens(text)
    if len(mine) < NEAR_DUP_MIN_TOKENS:
        return None
    wanted = set(subjects)
    best, best_share = None, 0.0
    for row in rows:
        if row.get("predicate"):
            continue
        if not (wanted & set(_subjects_of(row))):
            continue
        theirs = _claim_tokens(row.get("text", ""))
        if len(theirs) < NEAR_DUP_MIN_TOKENS:
            continue
        # The negation guard is a hard one: if one sentence negates and
        # the other does not, they are not the same claim at any overlap.
        if (mine & _NEGATIONS) != (theirs & _NEGATIONS):
            continue
        share = len(mine & theirs) / len(mine | theirs)
        if share >= NEAR_DUP_SHARE and share > best_share:
            best, best_share = row, share
    return best


def _prune(rows: list[dict]) -> list[dict]:
    """Oldest first, and never something somebody typed before something
    an analyst discovered.

    The cap exists so a store cannot grow without bound; what it must not
    do is quietly restore a rule the homeowner turned off, which is what
    dropping an `exception:` fact or a correction does.
    """
    if len(rows) <= MAX_FACTS:
        return rows
    def protected(row: dict) -> bool:
        return (str(row.get("source") or "") in KEEP_SOURCES
                or str(row.get("predicate") or "").startswith(EXCEPTION_PREFIX))
    keep = [r for r in rows if protected(r)]
    rest = sorted((r for r in rows if not protected(r)),
                  key=lambda r: int(r.get("ts") or 0))
    room = max(0, MAX_FACTS - len(keep))
    kept = set(id(r) for r in keep) | set(id(r) for r in rest[len(rest) - room:]
                                          if room)
    # The original order is what the file has always been in, so the cap
    # takes rows out of it rather than re-sorting somebody's store.
    return [r for r in rows if id(r) in kept][-MAX_FACTS:]


def forget(fact_key: str) -> bool:
    """Drop one fact. The ✕ on the House view, and nothing else.

    Unlike `knowledge_store`, this store is not a dedup index — nothing
    re-announces a fact because it left here — so a row somebody has
    looked at and disagreed with may go. What it does NOT do is edit
    `memory.md`: a line already in the document is edited out of the
    document, which is the same admission the inbox's ✕ makes.
    """
    with _locked():
        rows = _load()
        kept = [r for r in rows if r.get("id") != fact_key]
        if len(kept) == len(rows):
            return False
        _write(kept)
    return True


def forget_ids(keys) -> int:
    """Drop every fact named. What an undo token carries back.

    A rule written by a Wrong press is an effect of that press, and the
    toast's Undo promises to put back every effect of an ending — the
    row, the settled key, the memory line and, since 2.2, this. Returns
    how many went, because a caller that cannot tell "gone" from "never
    there" cannot say which happened.
    """
    wanted = {str(k) for k in keys or () if k}
    if not wanted:
        return 0
    with _locked():
        rows = _load()
        kept = [r for r in rows if str(r.get("id") or "") not in wanted]
        if len(kept) == len(rows):
            return 0
        _write(kept)
    return len(rows) - len(kept)


def forget_exceptions(finding_key: str) -> int:
    """Drop the rules a Wrong press on this report wrote.

    "Let brAIn raise it again" holds the report's settled key and nothing
    else — the row is long gone — so the rule is found by the key it was
    written under. Without this the press released the wording and left
    the rule muting the very check it was asking to hear from.
    """
    key = str(finding_key or "").strip()
    if not key:
        return 0
    with _locked():
        rows = _load()
        kept = [r for r in rows
                if not (_is_exception_predicate(r.get("predicate"))
                        and str(r.get("finding_key") or "") == key)]
        if len(kept) == len(rows):
            return 0
        _write(kept)
    return len(rows) - len(kept)


def forget_text(text: str, source: str = "") -> int:
    """Drop the facts one queued line became. The inbox's own ✕.

    The line's id is its source and its text (`server._inbox_id`), so the
    fact it was filed as is found the same way: the same normalised
    sentence from the same writer, under whatever subject the tagger gave
    it. An exception is never matched — it did not come out of the inbox.
    """
    key = normalize(text)
    if not key:
        return 0
    source = str(source or "")
    with _locked():
        rows = _load()
        kept = [r for r in rows
                if _is_exception_predicate(r.get("predicate"))
                or normalize(r.get("text", "")) != key
                or (source and str(r.get("source") or "") != source)]
        if len(kept) == len(rows):
            return 0
        _write(kept)
    return len(rows) - len(kept)


# A `FORGET:` line names content rather than quoting a row, so it is
# matched the way the consolidator is told to match it — "the matching
# content, including rewordings of it" — and the bar is the share of the
# REQUEST's words a fact must carry. One word is too little to stand on:
# "brain memory forget fridge" is not a request to forget every fact that
# mentions one, so a single-word request only takes an exact match.
FORGET_SHARE = 0.8
FORGET_MIN_TOKENS = 2


def forget_matching(request: str) -> int:
    """Drop the facts a `FORGET:` line asks to have removed.

    `brain memory forget` reached the document and nothing else, so the
    runs reading this store went on asserting — under "do not contradict
    them" — exactly what somebody had asked brAIn to stop believing.
    Exceptions are included: a person asking brAIn to forget something it
    was told is asking about the telling, whatever shape it was stored in.
    """
    want = _claim_tokens(request)
    exact = normalize(request)
    if not exact:
        return 0
    with _locked():
        rows = _load()
        kept = []
        for row in rows:
            text = row.get("text", "")
            if normalize(text) == exact:
                continue
            if len(want) >= FORGET_MIN_TOKENS:
                theirs = _claim_tokens(text)
                if (want & _NEGATIONS) == (theirs & _NEGATIONS) and \
                        len(want & theirs) / len(want) >= FORGET_SHARE:
                    continue
            kept.append(row)
        if len(kept) == len(rows):
            return 0
        _write(kept)
    return len(rows) - len(kept)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _expired(row: dict, now: float) -> bool:
    stamp = str(row.get("expires") or "")
    if not stamp:
        return False
    return stamp < _day(now)


def _tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if w and w not in _STOPWORDS}


def _subjects_of(row: dict) -> list[str]:
    got = row.get("subjects")
    if isinstance(got, list) and got:
        return [str(s) for s in got if s]
    return [str(row.get("subject") or "house")]


def _score(row: dict, now: float) -> float:
    """Confidence, aged. A fact stated last week outranks the same fact
    stated in March; a fact nobody is sure of never outranks one they are.

    Halves over a year, which is slow on purpose: these are supposed to
    be durable, and a decay fast enough to matter would be a store that
    forgets what the house is like over a quiet summer.
    """
    age_days = max(0.0, (now - float(row.get("ts") or 0)) / 86400.0)
    return _clean_confidence(row.get("confidence")) * (0.5 ** (age_days / 365.0))


def recall(query: str = "", subject: str = "", subjects=(), limit: int = 20,
           now: float | None = None) -> list[dict]:
    """The facts most likely to answer this, ranked and deterministic.

    Exact subject matches first — somebody asking about one entity wants
    that entity — then lexical overlap with the query, then confidence
    aged by recency. Ties break on the stamp and then on the id, so two
    identical questions get the identical answer: a ranking that depends
    on dict order is a prompt that changes under a run for no reason.
    """
    now = time.time() if now is None else float(now)
    wanted = {str(s) for s in ([subject] if subject else []) + list(subjects) if s}
    terms = _tokens(query)
    scored: list[tuple] = []
    for row in _load():
        if not _live_for_retrieval(row, now):
            continue
        mine = set(_subjects_of(row))
        exact = 1 if (wanted & mine) else 0
        if wanted and not exact and not terms:
            continue
        overlap = len(terms & _tokens(row.get("text", ""))) if terms else 0
        if terms and not overlap and not exact and not wanted:
            # A query with no word in common is not an answer to it, and
            # padding a recall with unrelated facts is how a model comes
            # to cite one.
            continue
        scored.append((-exact, -overlap, -_score(row, now),
                       -int(row.get("ts") or 0), str(row.get("id") or ""), row))
    scored.sort(key=lambda item: item[:5])

    out: list[dict] = []
    per_subject: dict[str, int] = {}
    for item in scored:
        row = item[5]
        head = str(row.get("subject") or "house")
        if head not in wanted:
            if per_subject.get(head, 0) >= PER_SUBJECT_CAP:
                continue
            per_subject[head] = per_subject.get(head, 0) + 1
        out.append(dict(row))
        if len(out) >= max(1, int(limit or 20)):
            break
    return out


# The Knowledge tab's browser. `recall` is the wrong reader for a person:
# it ranks for a model, caps three rows per subject so one busy sensor
# cannot fill a prompt, and drops anything with no word in common with the
# query — right for a prompt and the reason the tab could show a couple of
# hundred rows of a store holding two thousand, in an order nobody could
# name. A person wants every row, searchable, in an order they chose.
BROWSE_SORTS = ("newest", "oldest", "subject", "certain")
BROWSE_KINDS = ("house", "area", "entity", "person", "rule")
BROWSE_MAX = 200


def _kind_of(row: dict) -> str:
    """What a row is about, as the browser's filter chips name it.

    A rule somebody set by pressing Wrong is its own kind whatever entity
    it is about: those are the rows that change what brAIn does, and the
    ones a person most needs to be able to find and undo.
    """
    if str(row.get("predicate") or "").startswith(EXCEPTION_PREFIX):
        return "rule"
    kind = subject_kind(str(row.get("subject") or "house"))
    return "area" if kind == "check" else kind


def browse(*, query: str = "", kind: str = "", source: str = "",
           subject: str = "", sort: str = "newest", offset: int = 0,
           limit: int = 50, names: dict | None = None,
           now: float | None = None) -> dict:
    """Every live fact, filtered, searched and sorted for a person.

    ``names`` maps a subject to what a person calls it (an entity's
    friendly name, an area's name) so a search for "freezer" finds the
    facts about ``sensor.garage_chest_2_temp`` and the list can show the
    name rather than the id. Every word of the query must appear in the
    text, the subject or that name — a filter, not a ranking, because a
    person typing two words wants the rows with both.

    ``facets`` counts each kind and source over the rows the OTHER
    filters leave, so the chips say how many a press would show.
    """
    now = time.time() if now is None else float(now)
    names = names or {}
    sort = sort if sort in BROWSE_SORTS else "newest"
    words = [w for w in normalize(query).split() if w]
    live = [r for r in _load() if not _expired(r, now)]

    def label(subj: str) -> str:
        return str(names.get(subj) or "")

    def matches_query(row: dict) -> bool:
        if not words:
            return True
        subjects = _subjects_of(row)
        hay = " ".join([normalize(row.get("text", ""))]
                       + [normalize(s.replace(".", " ").replace(":", " "))
                          for s in subjects]
                       + [normalize(label(s)) for s in subjects])
        return all(w in hay for w in words)

    def matches_subject(row: dict) -> bool:
        return not subject or subject in _subjects_of(row)

    base = [r for r in live if matches_query(r) and matches_subject(r)]
    kinds: dict[str, int] = {k: 0 for k in BROWSE_KINDS}
    sources: dict[str, int] = {}
    for row in base:
        if not source or str(row.get("source") or "") == source:
            k = _kind_of(row)
            kinds[k] = kinds.get(k, 0) + 1
        if not kind or _kind_of(row) == kind:
            src = str(row.get("source") or "")
            sources[src] = sources.get(src, 0) + 1
    rows = [r for r in base
            if (not kind or _kind_of(r) == kind)
            and (not source or str(r.get("source") or "") == source)]

    def subject_key(row: dict):
        subj = str(row.get("subject") or "house")
        return ((label(subj) or subj).lower(), -int(row.get("ts") or 0),
                str(row.get("id") or ""))

    if sort == "oldest":
        rows.sort(key=lambda r: (int(r.get("first_seen") or r.get("ts") or 0),
                                 str(r.get("id") or "")))
    elif sort == "subject":
        rows.sort(key=subject_key)
    elif sort == "certain":
        rows.sort(key=lambda r: (-_score(r, now), -int(r.get("ts") or 0),
                                 str(r.get("id") or "")))
    else:
        rows.sort(key=lambda r: (-int(r.get("ts") or 0), str(r.get("id") or "")))

    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 50), BROWSE_MAX))
    page = []
    for row in rows[offset:offset + limit]:
        out = dict(row)
        out["kind"] = _kind_of(row)
        subj = str(row.get("subject") or "house")
        out["subject_name"] = label(subj)
        page.append(out)
    return {"facts": page, "total": len(rows), "all": len(live),
            "offset": offset, "limit": limit, "sort": sort,
            "facets": {"kinds": kinds,
                       "sources": dict(sorted(sources.items(),
                                              key=lambda kv: (-kv[1], kv[0])))}}


def exceptions(entity_id: str, check_id: str, now: float | None = None) -> list[dict]:
    """What the homeowner has said about this rule and this entity.

    The loop the Wrong button always promised: a correction on a check's
    finding lands here as `exception:<check_id>` on that entity, and the
    check reads it before filing the same row again in new words.
    `exception:*` is the whole-entity form — "stop telling me about this
    sensor" rather than "stop telling me this about it".
    """
    now = time.time() if now is None else float(now)
    want = {EXCEPTION_PREFIX + str(check_id), EXCEPTION_PREFIX + "*"}
    out = []
    for row in _load():
        if _expired(row, now):
            continue
        if str(row.get("predicate") or "") not in want:
            continue
        if entity_id in _subjects_of(row):
            out.append(dict(row))
    return out


def exception_map(now: float | None = None) -> dict[str, set]:
    """``{entity_id: {check_id, …}}`` for the whole store, in one read.

    A checks pass loads this once into the snapshot rather than asking
    per entity per rule: the checks are pure functions over a snapshot
    and a rule that went and read a file would be a check that could
    fail halfway through a batch.
    """
    now = time.time() if now is None else float(now)
    out: dict[str, set] = {}
    for row in _load():
        if _expired(row, now):
            continue
        predicate = str(row.get("predicate") or "")
        if not predicate.startswith(EXCEPTION_PREFIX):
            continue
        check_id = predicate[len(EXCEPTION_PREFIX):].strip()
        if not check_id:
            continue
        for subject in _subjects_of(row):
            if subject_kind(subject) == "entity":
                out.setdefault(subject, set()).add(check_id)
    return out


# ---------------------------------------------------------------------------
# The prompt block
# ---------------------------------------------------------------------------

# The same words `categories.memory_excerpt` puts above the head of the
# document, because a run reading this block and a run reading that one
# are being told the same thing about the same house. One copy, in the
# module that already owned it.
MEMORY_HEAD = categories.MEMORY_HEAD

CORE_SUBJECTS = ("house",)
CORE_SHARE = 0.4


def _is_core(row: dict) -> bool:
    """A standing fact every run is told — unless the consolidator dropped it.

    `house` and `person:*` are the facts that are not about any one thing,
    which is what makes them worth telling every run. But they arrive
    raw, within a minute of being queued, and the consolidator — which is
    told to drop transient states, one-off commands and reports that were
    marked wrong — has not been asked about them yet. A row it has since
    left out of the document (`curation: dropped`, see `reconcile`) keeps
    its subjects and still answers a question about one of them; what it
    loses is the right to be read to every run as a standing truth.
    """
    if row.get("curation") == "dropped":
        return False
    for subject in _subjects_of(row):
        if subject in CORE_SUBJECTS or subject_kind(subject) == "person":
            return True
    return False


def _line(row: dict) -> str:
    source = str(row.get("source") or "")
    observed = str(row.get("observed") or "")
    stamp = ", ".join([p for p in (source, observed) if p])
    text = str(row.get("text", ""))
    predicate = str(row.get("predicate") or "")
    if _is_exception_predicate(predicate):
        # A rule's text is the homeowner's reason, which on its own does
        # not say what it was a reason ABOUT — "that is normal for this
        # sensor" under no report is a sentence a run cannot use. The
        # report rides with it, and so does what the rule stands down.
        about = str(row.get("about") or "").strip()
        if about and normalize(about) not in normalize(text):
            text = f'Reported "{about}" — marked wrong: {text}'
        rule = predicate[len(EXCEPTION_PREFIX):] or "*"
        text = (f"{text} [not to be reported again: {rule} on "
                f"{row.get('subject') or 'house'}]")
    return f"- ({stamp}) {text}" if stamp else f"- {text}"


def _live_for_retrieval(row: dict, now: float) -> bool:
    """Expired, or about something that is no longer in the house, is not
    something to tell a run. Both rows stay in the store — a person can
    still see them on the Knowledge tab — and the second goes for good
    once it has been gone long enough to be sure (`reconcile`)."""
    return not _expired(row, now) and not row.get("gone_since")


def _related_floor(terms: set[str]) -> int:
    """How many of a question's words a fact must share to be about it.

    One is enough for a short question — "is the lounge cold?" names the
    room and nothing else — and a quarter of them for a long one, so a
    paragraph of question does not pull in every fact that shares a
    word with it.
    """
    return max(1, -(-len(terms) // 4))


def retrieval_block(*, entities=(), areas=(), domains=(), person: str = "",
                    query: str = "", limit_chars: int = RETRIEVAL_CHARS,
                    now: float | None = None) -> str:
    """What this run should be told about this house, and nothing else.

    The core facts — standing preferences and whatever is known about
    the person asking — plus the facts about the entities and areas the
    run is reading. `domains` widens that to every fact about an entity
    in one of them, which is what a category-shaped run (all the lights,
    all the climate) actually wants. `query` is the question, and a fact
    sharing enough of its words is about it whatever it is tagged with —
    the lexical overlap `recall` ranks by, applied to the one call that
    used to take the argument and read nothing of it.

    A subject the run did not name may carry at most `PER_SUBJECT_CAP`
    rows: a house with forty facts about the boiler would otherwise answer
    every question about the heating with the boiler. `house` and the
    people are not capped — they are not one thing, they are everything
    that is not about one thing.

    Empty when there is nothing relevant, which matters: the caller
    falls back to the document's own head on an empty answer, so a fresh
    install behaves exactly as it did before this store existed.
    """
    now = time.time() if now is None else float(now)
    wanted = {str(e) for e in entities if e}
    wanted |= {str(a) if str(a).startswith("area:") else f"area:{a}"
               for a in areas if a}
    if person:
        wanted.add(f"person:{person}")
    domain_set = {str(d) for d in domains if d}
    terms = _tokens(query)
    floor = _related_floor(terms) if terms else 0

    core: list[tuple] = []
    matched: list[tuple] = []
    related: list[tuple] = []
    for row in _load():
        if not _live_for_retrieval(row, now):
            continue
        mine = set(_subjects_of(row))
        named = bool(wanted & mine)
        hit = named or any(
            subject_kind(s) == "entity" and s.split(".", 1)[0] in domain_set
            for s in mine)
        overlap = len(terms & _tokens(row.get("text", ""))) if terms else 0
        rank = (-overlap, -_score(row, now), -int(row.get("ts") or 0),
                str(row.get("id") or ""), row, named)
        if hit:
            matched.append(rank)
        elif _is_core(row):
            core.append(rank)
        elif terms and overlap >= floor:
            related.append(rank)
    if not core and not matched and not related:
        return ""
    for pool in (core, matched, related):
        pool.sort(key=lambda item: item[:4])

    # The core facts get a share of the budget rather than the front of
    # it: a house with forty standing preferences would otherwise spend
    # the whole block on them and tell the run nothing about the entities
    # it is reading, which is the failure this replaced one size up.
    budget = max(0, int(limit_chars) - len(MEMORY_HEAD) - 1)
    core_budget = int(budget * CORE_SHARE) if (matched or related) else budget
    lines: list[str] = []
    used = 0
    per_subject: dict[str, int] = {}
    for pool, allowance in ((core, core_budget), (matched, budget),
                            (related, budget)):
        for item in pool:
            row, named = item[4], item[5]
            head = str(row.get("subject") or "house")
            capped = (not named and head not in wanted
                      and subject_kind(head) in ("entity", "area"))
            if capped and per_subject.get(head, 0) >= PER_SUBJECT_CAP:
                continue
            line = _line(row)
            if used + len(line) + 1 > allowance:
                break
            lines.append(line)
            used += len(line) + 1
            if capped:
                per_subject[head] = per_subject.get(head, 0) + 1
    if not lines:
        return ""
    return MEMORY_HEAD + "\n" + "\n".join(lines)


def retrieval_fingerprint(*, entities=(), areas=(), domains=(),
                          query: str = "", now: float | None = None) -> str:
    """Which facts a run with these subjects would be told — as one digest.

    The ids, never the lines: a line carries the date a fact was last
    seen, and a fact re-taught today is the same fact it was yesterday.
    What a card's refresh gate needs to know is whether the SET moved, and
    an empty store answers "" so the caller can fall back to the document.
    """
    block_rows = []
    now = time.time() if now is None else float(now)
    wanted = {str(e) for e in entities if e}
    wanted |= {str(a) if str(a).startswith("area:") else f"area:{a}"
               for a in areas if a}
    domain_set = {str(d) for d in domains if d}
    terms = _tokens(query)
    floor = _related_floor(terms) if terms else 0
    for row in _load():
        if not _live_for_retrieval(row, now):
            continue
        mine = set(_subjects_of(row))
        hit = bool(wanted & mine) or any(
            subject_kind(s) == "entity" and s.split(".", 1)[0] in domain_set
            for s in mine)
        overlap = len(terms & _tokens(row.get("text", ""))) if terms else 0
        if hit or _is_core(row) or (terms and overlap >= floor):
            block_rows.append(str(row.get("id") or ""))
    if not block_rows:
        return ""
    return hashlib.sha256(
        "\n".join(sorted(block_rows)).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The inbox sweep
# ---------------------------------------------------------------------------

def _read_state(state_file) -> dict:
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"files": {}, "last_ingest": 0, "ingested": 0}
    if not isinstance(data, dict):
        return {"files": {}, "last_ingest": 0, "ingested": 0}
    files = data.get("files")
    return {"files": files if isinstance(files, dict) else {},
            "last_ingest": int(data.get("last_ingest") or 0),
            "ingested": int(data.get("ingested") or 0)}


# How many file fingerprints the state keeps. The consolidator prunes
# `processed/` after 30 days, so anything older than that cannot come
# back — and a state file that grew for ever would be the one thing here
# with no cap on it.
MAX_STATE_FILES = 2000


def _fingerprint(path: Path) -> str:
    """Inode and size, which is what says this is the SAME file.

    The consolidator archives what it consumes by MOVING it into
    `processed/`, so a name in the inbox and the same name under
    `processed/` are one file and must be ingested once — and a name that
    is free again is a name anything may reuse, which is what the inode
    is here for (`_inbox_fingerprint`'s reason, one module over).
    """
    st = path.stat()
    return f"{st.st_ino}:{st.st_size}"


def ingest_inbox(inbox_dir, processed_dir, *, known_entities=frozenset(),
                 areas: dict | None = None, state_file=None) -> int:
    """Fold the memory inbox's queued lines into facts. Never raises.

    A *reader* of that queue and never a second drain of it: the
    consolidator goes on moving the files it has filed into `processed/`,
    and this sweeps both directories so a line is ingested whether it is
    still waiting or has already reached the document. Which is also why
    the bookkeeping is a file rather than a deletion — there is nothing
    here that may be taken out of somebody else's queue.

    Returns how many facts were created (not how many lines were read: a
    line that says what the store already holds is not news).
    """
    if not writable():
        return 0
    state_file = INGEST_STATE_FILE if state_file is None else Path(state_file)
    state = _read_state(state_file)
    seen: dict = state["files"]
    created = 0
    alive: set[str] = set()
    # The archive first: what it holds is older than anything still
    # waiting, and a `FORGET:` in the queue has to land AFTER the line it
    # names, or it forgets nothing and the line is filed a moment later.
    for folder in (Path(processed_dir), Path(inbox_dir)):
        try:
            paths = sorted(folder.glob("*.jsonl"))
        except OSError:
            continue
        for path in paths:
            try:
                mark = _fingerprint(path)
            except OSError:
                continue
            alive.add(path.name)
            if seen.get(path.name) == mark:
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    # A torn line is not a fact, and it must not stop the
                    # rest of the file being read.
                    continue
                if _ingest_line(obj, known_entities, areas):
                    created += 1
            seen[path.name] = mark
    for name in [n for n in seen if n not in alive]:
        # The archive is pruned after 30 days; a fingerprint for a file
        # that is gone from both directories answers no question.
        del seen[name]
    if len(seen) > MAX_STATE_FILES:
        for name in sorted(seen)[:len(seen) - MAX_STATE_FILES]:
            del seen[name]
    try:
        atomic_write.write_json(state_file, {
            "files": seen, "last_ingest": int(time.time()),
            "ingested": int(state["ingested"]) + created})
    except OSError:
        # The facts are filed. A state file that would not write costs
        # one re-read of the same lines next pass, which `add` dedupes.
        pass
    return created


# How long a device-health observation is worth asserting. The same
# thirty days the consolidator is told to drop such a line from the
# document after (`brain-memory-consolidate.sh`'s dating rules), because a
# battery replaced weeks ago must not still be reported dead — and this
# store is what most panel runs read, not the document.
TRANSIENT_DAYS = 30
# What a device-health observation sounds like. A gate on the SHAPE of a
# health claim rather than on a word: "spare batteries are in the kitchen
# drawer" mentions a battery and is a durable fact about a house, where
# "the hall sensor's battery is low" is a snapshot of one afternoon.
_TRANSIENT_RE = re.compile(
    r"\b(?:batter(?:y|ies)\s+(?:is|are|was|were|has been|have been|went|"
    r"running)\s+(?:low|dead|flat|empty|out)|"
    r"(?:is|are|was|were|has been|have been|went|keeps going|goes)\s+"
    r"(?:unavailable|offline|unresponsive|unreachable|dead)|"
    r"stopped\s+(?:reporting|responding|checking in|updating)|"
    r"(?:is|was|has been)\s+(?:frozen|stuck)\b|"
    r"(?:low|dead|flat)\s+batter(?:y|ies))", re.I)
# What makes a line durable even though it describes health: a reason, a
# habit, an interval. "Replaced the CR2032 — it's a 3-monthly job on that
# sensor" is the maintenance fact the `done` ending exists to capture.
_DURABLE_RE = re.compile(
    r"\b(?:because|always|every|usually|by design|on purpose|wired|"
    r"monthly|weekly|yearly|annual|normal|expected|they said)\b", re.I)


def is_transient(text: str) -> bool:
    """A device-health snapshot rather than a fact about the house."""
    body = str(text or "")
    return bool(_TRANSIENT_RE.search(body)) and not _DURABLE_RE.search(body)


def _expiry_for(text: str, ts: float, given: str = "") -> str:
    given = str(given or "").strip()[:10]
    if given:
        return given
    if is_transient(text):
        return _day(float(ts) + TRANSIENT_DAYS * 86400)
    return ""


def _ingest_line(obj, known_entities, areas) -> bool:
    if not isinstance(obj, dict):
        return False
    text = str(obj.get("fact") or "").strip()
    if not text:
        return False
    if text.upper().startswith(FORGET_PREFIX):
        # Still not a fact: the store must not assert the very thing
        # somebody asked to have removed. What changed is that it is no
        # longer ignored — `brain memory forget` used to reach the
        # document and leave the store saying the old thing to every run.
        forget_matching(text[len(FORGET_PREFIX):].strip())
        return False
    source = str(obj.get("source") or "panel")
    person = str(obj.get("person") or "")
    named = str(obj.get("subject") or "").strip()
    also = [str(x).strip() for x in (obj.get("subjects") or [])
            if isinstance(x, str) and str(x).strip()]
    tagged = tag_subjects(text, known_entities=known_entities,
                          areas=areas or {}, person=person)
    if named or also:
        # A writer that knows what its fact is about beats a scan of the
        # sentence: `remember_fact` takes a subject for exactly this, and
        # a tagger that overrode it would make the argument decorative.
        # The scan's `house` fallback goes when a writer named anything —
        # it means "about nothing in particular", which is now untrue.
        lead = [named] if named else []
        for extra in also:
            if extra not in lead:
                lead.append(extra)
        tagged = lead + [s for s in tagged if s not in lead and s != "house"]
    stamp = obj.get("ts") or None
    try:
        when = float(stamp) if stamp else time.time()
    except (TypeError, ValueError):
        when, stamp = time.time(), None
    _row, created = add(
        text, subject=tagged[0], extra_subjects=tagged[1:], source=source,
        confidence=obj.get("confidence", DEFAULT_CONFIDENCE),
        run_id=str(obj.get("run_id") or ""),
        predicate=str(obj.get("predicate") or ""),
        expires=_expiry_for(text, when, obj.get("expires") or ""),
        ts=stamp, near_dedupe=True)
    return created


# ---------------------------------------------------------------------------
# Reconcile: the document, the queue, and the registry
# ---------------------------------------------------------------------------
#
# The store is filed from the inbox within a minute, before the
# consolidator has judged a line — and the consolidator is the one that
# drops transient states, one-off commands and reports marked wrong, merges
# rewordings, and applies `FORGET:`. A person editing `memory.md`, `brain
# memory clear` and `brain memory undo` all change the document and
# nothing else. So the store and the document drifted apart from the
# moment the store existed, and the store is what most runs read.
#
# `reconcile` makes the document the curated truth the store answers to.
# Every fact that came out of the queue is in one of three states:
#
#   * pending  — its line is still in the inbox: nobody has judged it yet,
#                and it is told to runs exactly as it was before;
#   * kept     — the document carries it (in its own words or close to);
#   * dropped  — the consolidator has had it and the document does not:
#                it keeps its subjects, and loses the right to be read to
#                every run as a standing fact (`_is_core`).
#
# And one transition that is a removal: a fact the document carried and no
# longer does left the document — a person deleted the line, a clear or an
# undo took it, a `FORGET:` struck it, or the consolidator superseded it —
# and is forgotten here too, because a store still asserting what the
# curated document stopped saying is the drift this exists to end.
#
# The registry half is cheaper and older than any of that: a fact whose
# every subject is an entity the house no longer has is about nothing, so
# it stops being retrieved at once and is dropped after `ORPHAN_DAYS`.

RECONCILE_STATE_FILE = Path(os.environ.get(
    "BRAIN_FACTS_RECONCILE_STATE",
    "/config/.brain/memory/facts-reconcile.json"))
# What share of a fact's own words one line of the document must carry for
# the document to be carrying it. Below the near-dedupe bar on purpose:
# the consolidator rewrites what it files ("observed" markers, merged
# sentences), and reading a reworded line as "gone" would forget a fact the
# document still holds.
REFLECT_SHARE = 0.6
ORPHAN_DAYS = 30

# What the document says, line by line — `categories.document_lines`, so
# the facts store and onboarding agree on what a fact line is.
document_lines = categories.document_lines


def _reflected(tokens: set[str], index: dict[str, set[int]]) -> bool:
    if not tokens:
        return False
    hits: dict[int, int] = {}
    for tok in tokens:
        for i in index.get(tok, ()):
            hits[i] = hits.get(i, 0) + 1
    if not hits:
        return False
    best = max(hits.values())
    return best >= min(2, len(tokens)) and best / len(tokens) >= REFLECT_SHARE


def _pending_keys(inbox_dir) -> set[str] | None:
    """The normalised text of every line still waiting, or None.

    None is "I could not look", and the caller then decides nothing about
    any row — a queue that would not read is not a queue that is empty,
    and reading it as one would mark every waiting fact dropped.
    """
    keys: set[str] = set()
    try:
        paths = sorted(Path(inbox_dir).glob("*.jsonl"))
    except OSError:
        return None
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        for line in raw.splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                key = normalize(obj.get("fact") or "")
                if key:
                    keys.add(key)
    return keys


def _read_reconcile_state() -> dict:
    try:
        with open(RECONCILE_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def reconcile(document: str | None, inbox_dir, *,
              known_entities=frozenset(), registry_fresh: bool = False,
              now: float | None = None, force: bool = False) -> dict:
    """Make the store answer to the document and the registry. Never raises.

    ``document`` None is "the document could not be read", and then the
    curation half is skipped whole rather than reading every fact as gone.
    ``registry_fresh`` says `known_entities` is a real list from a recent
    pass; without it nothing is called an orphan, for the same reason.

    Cheap when nothing moved: the inputs are digested and a pass whose
    digest matches the last one returns at once, because this is asked on
    the minute and the document changes a few times a day.
    """
    out = {"forgotten": 0, "kept": 0, "dropped": 0, "pending": 0,
           "orphaned": 0, "skipped": False}
    if not writable():
        out["skipped"] = True
        return out
    now = time.time() if now is None else float(now)
    try:
        pending = _pending_keys(inbox_dir) if document is not None else None
        lines = document_lines(document) if document is not None else []
        def inputs_digest() -> str:
            try:
                facts_stamp = str(os.stat(FACTS_FILE).st_mtime_ns)
            except OSError:
                facts_stamp = "none"
            return hashlib.sha256("\x00".join([
                hashlib.sha256(str(document).encode("utf-8", "replace"))
                .hexdigest(),
                ",".join(sorted(pending)) if pending is not None else "?",
                facts_stamp,
                str(len(known_entities)) if registry_fresh else "-",
                _day(now),
            ]).encode("utf-8", "replace")).hexdigest()

        digest = inputs_digest()
        state = _read_reconcile_state()
        if not force and state.get("digest") == digest:
            out["skipped"] = True
            return out

        index: dict[str, set[int]] = {}
        for i, line in enumerate(lines):
            for tok in _claim_tokens(line):
                index.setdefault(tok, set()).add(i)
        cleared = (document is not None and not lines
                   and int(state.get("doc_lines") or 0) > 0)
        known = set(known_entities or ())
        with _locked():
            rows = _load()
            kept_rows: list[dict] = []
            changed = False
            for row in rows:
                if _is_exception_predicate(row.get("predicate")):
                    kept_rows.append(row)
                    continue
                # -- the document --------------------------------------
                if pending is not None:
                    key = normalize(row.get("text", ""))
                    was = row.get("curation")
                    if key in pending:
                        now_is = "pending"
                    elif _reflected(_claim_tokens(row.get("text", "")), index):
                        now_is = "kept"
                    elif was == "kept" or cleared:
                        # It was in the document and is not any more.
                        out["forgotten"] += 1
                        changed = True
                        continue
                    else:
                        now_is = "dropped"
                    if was != now_is:
                        row["curation"] = now_is
                        changed = True
                    out[now_is] += 1
                kept_rows.append(row)
            # -- the registry (exceptions included: a rule about an
            # entity that is gone stands nothing down) ----------------
            final: list[dict] = []
            for row in kept_rows:
                entity_subjects = [s for s in _subjects_of(row)
                                   if subject_kind(s) == "entity"]
                only_entities = (entity_subjects
                                 and len(entity_subjects) == len(_subjects_of(row)))
                if registry_fresh and known and only_entities:
                    gone = not any(s in known for s in entity_subjects)
                    if gone:
                        since = int(row.get("gone_since") or 0)
                        if not since:
                            row["gone_since"] = int(now)
                            changed = True
                            out["orphaned"] += 1
                        elif now - since > ORPHAN_DAYS * 86400:
                            out["forgotten"] += 1
                            changed = True
                            continue
                    elif row.get("gone_since"):
                        row.pop("gone_since", None)
                        changed = True
                final.append(row)
            if changed:
                _write(final)
                # The pass's own write moves the store's stamp, and a
                # digest taken before it would make the next tick repeat
                # a pass that has nothing left to do.
                digest = inputs_digest()
        try:
            atomic_write.write_json(RECONCILE_STATE_FILE, {
                "digest": digest, "at": int(now),
                "doc_lines": len(lines) if document is not None
                else int(state.get("doc_lines") or 0),
                "last": {k: v for k, v in out.items() if k != "skipped"}})
        except OSError:
            # The reconcile itself is done; a state that would not write
            # costs one repeat of it on the next tick.
            pass
    except Exception:  # noqa: BLE001 — accounting over a store, never a crash
        out["skipped"] = True
    return out


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def export_rows() -> list[dict]:
    """Every row, as stored — for `/api/memory/export`.

    The rules a Wrong press wrote live here and nowhere else: the settled
    ledger that rides beside them in an export suppresses one WORDING,
    where an `exception:` fact stands a check down for an entity whatever
    it says next. An export without this file was a migration that put
    every corrected mistake back.
    """
    return [dict(r) for r in _load()]


def _int_or(value, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def merge_rows(rows) -> int:
    """Fold another install's rows in. Existing ids win. Never raises.

    A migration and not a sync, `findings_store.merge_rows`' rule: a fact
    this install already holds is this install's, and an import must not
    be able to rewrite it. Each incoming row is cleaned field by field —
    it is JSON somebody carried here from somewhere else — and the cap
    applies exactly as it does to a fact taught today.
    """
    if not isinstance(rows, list) or not writable():
        return 0
    added = 0
    with _locked():
        held = _load()
        seen = {str(r.get("id") or "") for r in held}
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()[:MAX_TEXT]
            if not text:
                continue
            subject = str(row.get("subject") or "house").strip()[:MAX_SUBJECT] \
                or "house"
            predicate = str(row.get("predicate") or "").strip()[:MAX_PREDICATE]
            key = fact_id(subject, text, predicate
                          if _is_exception_predicate(predicate) else "")
            if key in seen:
                continue
            subjects = [str(x).strip()[:MAX_SUBJECT]
                        for x in (row.get("subjects") or [subject])
                        if isinstance(x, str) and str(x).strip()][:MAX_SUBJECTS]
            if subject not in subjects:
                subjects.insert(0, subject)
            stamp = _int_or(row.get("ts"), int(time.time()))
            entry = {
                "id": key, "subject": subject, "subjects": subjects,
                "predicate": predicate, "text": text,
                "source": str(row.get("source") or "import")[:32],
                "confidence": _clean_confidence(row.get("confidence")),
                "observed": str(row.get("observed") or _day(stamp))[:10],
                "ts": stamp,
                "first_seen": _int_or(row.get("first_seen"), stamp),
                "run_id": str(row.get("run_id") or "")[:64],
                "expires": str(row.get("expires") or "")[:10],
            }
            for field in ("about", "finding_key"):
                if row.get(field):
                    entry[field] = str(row[field])[:MAX_TEXT]
            held.append(entry)
            seen.add(key)
            added += 1
        if added:
            _write(_prune(held))
    return added


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def summary(now: float | None = None) -> dict:
    """What is in here, for `/api/diagnostics` and the House view.

    Counts and stamps, never the text: this payload rides into the bundle
    `brain report` attaches to an issue, and a memory line is a fact about
    somebody's home rather than a diagnostic (`WEEKLY_STATE`'s rule).
    """
    now = time.time() if now is None else float(now)
    rows = _load()
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    exceptions_n = 0
    expired = 0
    by_curation: dict[str, int] = {}
    gone = 0
    for row in rows:
        if _expired(row, now):
            expired += 1
            continue
        source = str(row.get("source") or "")
        by_source[source] = by_source.get(source, 0) + 1
        kind = subject_kind(str(row.get("subject") or "house"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if str(row.get("predicate") or "").startswith(EXCEPTION_PREFIX):
            exceptions_n += 1
        curation = str(row.get("curation") or "")
        if curation:
            by_curation[curation] = by_curation.get(curation, 0) + 1
        if row.get("gone_since"):
            gone += 1
    state = _read_state(INGEST_STATE_FILE)
    reconciled = _read_reconcile_state()
    return {
        "count": len(rows) - expired,
        "expired": expired,
        "cap": MAX_FACTS,
        "by_source": dict(sorted(by_source.items())),
        "by_subject": dict(sorted(by_kind.items())),
        "exceptions": exceptions_n,
        # What the document has made of what the queue said, and how many
        # rows are about entities the house no longer has. A store whose
        # every row is `dropped` is a consolidator that keeps refusing,
        # which reads exactly like a quiet house from anywhere else.
        "by_curation": dict(sorted(by_curation.items())),
        "gone": gone,
        "last_ingest": state["last_ingest"],
        "ingested": state["ingested"],
        "last_reconcile": int(reconciled.get("at") or 0),
    }


# ---------------------------------------------------------------------------
# Rows by predicate — what the Resident's nightly reflect pass rewrites
# ---------------------------------------------------------------------------

def with_predicate(prefix: str, now: float | None = None) -> list[dict]:
    """Every live fact whose predicate starts with ``prefix``, oldest first.

    `outcomes` files its `judgement:` facts here and has to find them again
    to supersede or replace one — and an empty prefix would be every fact
    in the store, which is never what a caller asking by predicate meant,
    so it answers nothing instead.
    """
    prefix = str(prefix or "")
    if not prefix:
        return []
    now = time.time() if now is None else float(now)
    rows = [dict(r) for r in _load()
            if str(r.get("predicate") or "").startswith(prefix)
            and not _expired(r, now)]
    rows.sort(key=lambda r: (int(r.get("ts") or 0), str(r.get("id") or "")))
    return rows
