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


def fact_id(subject: str, text: str) -> str:
    """The id of a fact, derived from what it says about what.

    Content, not a stamp: nothing that writes into the memory inbox mints
    an id and `ts` is not unique — one insight run queues three facts
    inside the same second — so two lines that make the same claim about
    the same subject ARE one fact, whichever writer produced them.
    """
    return hashlib.sha256(
        f"{subject}\x00{normalize(text)}".encode("utf-8", "replace")
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
        extra_subjects=()) -> tuple[dict | None, bool]:
    """Record one fact. Returns ``(fact, created)``.

    A re-add is not a second fact: the id is the subject plus the
    normalised text, so the same claim from the same subject refreshes
    `ts` and `observed` — it is still true today — and keeps the
    `first_seen` it already had, which is the date that says how long
    this house has been like this.
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
    key = fact_id(subject, text)
    with _locked():
        rows = _load()
        for row in rows:
            if row.get("id") == key:
                row["ts"] = int(now)
                row["observed"] = _day(now)
                # A later sighting may know more than the first did —
                # a run id, an expiry, a tighter subject list — and may
                # not know less: an empty field is not a correction.
                if run_id:
                    row["run_id"] = str(run_id)[:64]
                if predicate:
                    row["predicate"] = predicate
                if expires:
                    row["expires"] = str(expires)[:10]
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
        rows.append(entry)
        _write(_prune(rows))
    return dict(entry), True


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
        if _expired(row, now):
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
    for subject in _subjects_of(row):
        if subject in CORE_SUBJECTS or subject_kind(subject) == "person":
            return True
    return False


def _line(row: dict) -> str:
    source = str(row.get("source") or "")
    observed = str(row.get("observed") or "")
    stamp = ", ".join([p for p in (source, observed) if p])
    return f"- ({stamp}) {row.get('text', '')}" if stamp else f"- {row.get('text', '')}"


def retrieval_block(*, entities=(), areas=(), domains=(), person: str = "",
                    query: str = "", limit_chars: int = RETRIEVAL_CHARS,
                    now: float | None = None) -> str:
    """What this run should be told about this house, and nothing else.

    The core facts — standing preferences and whatever is known about
    the person asking — plus the facts about the entities and areas the
    run is reading. `domains` widens that to every fact about an entity
    in one of them, which is what a category-shaped run (all the lights,
    all the climate) actually wants.

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

    core: list[tuple] = []
    matched: list[tuple] = []
    for row in _load():
        if _expired(row, now):
            continue
        mine = set(_subjects_of(row))
        hit = bool(wanted & mine) or any(
            subject_kind(s) == "entity" and s.split(".", 1)[0] in domain_set
            for s in mine)
        rank = (-_score(row, now), -int(row.get("ts") or 0),
                str(row.get("id") or ""), row)
        if hit:
            matched.append(rank)
        elif _is_core(row):
            core.append(rank)
    if not core and not matched:
        return ""
    core.sort(key=lambda item: item[:3])
    matched.sort(key=lambda item: item[:3])

    # The core facts get a share of the budget rather than the front of
    # it: a house with forty standing preferences would otherwise spend
    # the whole block on them and tell the run nothing about the entities
    # it is reading, which is the failure this replaced one size up.
    budget = max(0, int(limit_chars) - len(MEMORY_HEAD) - 1)
    core_budget = int(budget * CORE_SHARE) if matched else budget
    lines: list[str] = []
    used = 0
    for pool, allowance in ((core, core_budget), (matched, budget)):
        for item in pool:
            line = _line(item[3])
            if used + len(line) + 1 > allowance:
                break
            lines.append(line)
            used += len(line) + 1
    if not lines:
        return ""
    return MEMORY_HEAD + "\n" + "\n".join(lines)


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
    for folder in (Path(inbox_dir), Path(processed_dir)):
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


def _ingest_line(obj, known_entities, areas) -> bool:
    if not isinstance(obj, dict):
        return False
    text = str(obj.get("fact") or "").strip()
    if not text or text.upper().startswith(FORGET_PREFIX):
        return False
    source = str(obj.get("source") or "panel")
    person = str(obj.get("person") or "")
    named = str(obj.get("subject") or "").strip()
    tagged = tag_subjects(text, known_entities=known_entities,
                          areas=areas or {}, person=person)
    if named:
        # A writer that knows what its fact is about beats a scan of the
        # sentence: `remember_fact` takes a subject for exactly this, and
        # a tagger that overrode it would make the argument decorative.
        tagged = [named] + [s for s in tagged if s != named]
    _row, created = add(
        text, subject=tagged[0], extra_subjects=tagged[1:], source=source,
        confidence=obj.get("confidence", DEFAULT_CONFIDENCE),
        run_id=str(obj.get("run_id") or ""),
        predicate=str(obj.get("predicate") or ""),
        ts=obj.get("ts") or None)
    return created


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
    state = _read_state(INGEST_STATE_FILE)
    return {
        "count": len(rows) - expired,
        "expired": expired,
        "cap": MAX_FACTS,
        "by_source": dict(sorted(by_source.items())),
        "by_subject": dict(sorted(by_kind.items())),
        "exceptions": exceptions_n,
        "last_ingest": state["last_ingest"],
        "ingested": state["ingested"],
    }
