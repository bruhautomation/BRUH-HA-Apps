"""Ideas — the cards brAIn thinks this home should have, before you agree.

Onboarding studies a home once and proposes a card set, and that was the
only moment brAIn ever offered an idea. Everything after it was the
homeowner's to think of: the ask bar makes a card out of a question, and
"＋ Make recurring" turns one into a scheduled card, but both start with
somebody already knowing what to ask. So a house that has since grown a
solar array, a heat pump and four months of history goes on generating
whatever was chosen in its first twenty minutes, and the one thing brAIn
is best placed to say — *here is something worth watching that you have
not thought of* — had nowhere to be said.

This is that place, and the whole of what makes it safe is that it is a
**separate page from Insights**. An idea is not a card: nothing here
generates anything, spends anything per idea, or appears on a dashboard.
It is a proposal to be read and ticked, and accepting one is what creates
the category the ordinary scheduler then generates. That split is why the
page can afford to be generous — eight ideas nobody takes cost one run,
where eight cards nobody reads cost a run each, every refresh interval,
for ever.

Five rules.

**An idea is never re-proposed once it has been answered.** A dismissed
idea coming back next week is how a page stops being read, so the
fingerprint of everything accepted or dismissed is kept and consulted on
every pass — an index, never drained, the same arrangement
`findings_store` keeps beside a list that is meant to empty. Accepting is
recorded the same way for the same reason, plus one of its own: the
category now exists, and proposing it again would be brAIn offering to
build what it already built.

**A card this home already has is not an idea.** The fingerprint set is
seeded from the live categories on every pass rather than only from what
this module has seen, because a card made through the ask bar, through
onboarding or by hand is still a card, and this module did not watch any
of them being made.

**The cap refuses rather than making room** (`todo_store`'s rule): the
room would be made by dropping an idea somebody has not read yet.

**A pass that proposed nothing is an answer, not a failure.** The two are
different claims and only one of them is worth a second look — a house
brAIn has nothing new to suggest for is a house in good order, and
rendering that as an error teaches somebody to press the button again.
`last_error` is written only where a run actually failed.

**The weekly pass only ever ADDS.** It never clears the page, never
re-orders it and never removes an idea somebody has not answered, because
the one thing a person does with this page is come back to it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import atomic_write
import user_categories

log = logging.getLogger("brain.ideas")

STORE = os.environ.get("BRAIN_IDEAS_FILE", "/data/ideas.json")

# Eight is what one pass may propose, and it is the same number
# onboarding uses for the same reason: four sharp ideas beat eight vague
# ones, and a page longer than a screen is a page nobody finishes.
MAX_PER_RUN = 8
# What may sit unanswered. Past this the add is refused, which is visible
# on the page — an idea silently dropped to make room for a newer one is
# the page quietly deciding what somebody gets to read.
MAX_OPEN = 24
# The answered fingerprints. Capped because it is an index and not a
# record: what it is for is "do not offer this again", and the oldest
# entries are the ideas least likely to be re-proposed anyway.
MAX_ANSWERED = 400

MAX_TITLE = 60
MAX_ICON = 4
MAX_FOCUS = 4000
MAX_WHY = 600
MAX_QUESTION = 300

STATUSES = ("open", "accepted", "dismissed")


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        with open(STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"ideas": [], "answered": [], "last_run": 0, "last_error": "",
                "last_count": 0, "runs": 0}
    if not isinstance(data, dict):
        return {"ideas": [], "answered": [], "last_run": 0, "last_error": "",
                "last_count": 0, "runs": 0}
    data.setdefault("ideas", [])
    data.setdefault("answered", [])
    data.setdefault("last_run", 0)
    data.setdefault("last_error", "")
    data.setdefault("last_count", 0)
    data.setdefault("runs", 0)
    if not isinstance(data["ideas"], list):
        data["ideas"] = []
    if not isinstance(data["answered"], list):
        data["answered"] = []
    return data


def writable() -> bool:
    """Whether there is a directory to write into.

    `facts_store`'s rule: run.sh makes /data before the panel starts, so a
    missing parent is a dev checkout or a test rather than a fault worth
    reporting to somebody.
    """
    parent = os.path.dirname(STORE)
    return not parent or os.path.isdir(parent)


def _write(data: dict) -> None:
    if not writable():
        return
    try:
        atomic_write.write_json(STORE, data)
    except OSError as exc:
        log.warning("could not write the ideas store: %s", exc)


# ---------------------------------------------------------------------------
# What counts as the same idea
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[^a-z0-9]+")


def fingerprint(title: str) -> str:
    """The key two proposals of the same card share.

    Deliberately the title alone and not the focus: a second pass writes
    its own wording of the same idea, and a fingerprint over a paragraph
    of prose would make every re-proposal a new one — which is exactly
    the failure "never re-propose an answered idea" exists to prevent.
    `proposals.key_for` makes the same call for the same reason one store
    over, on the config rather than the sentence.
    """
    return _WORD.sub(" ", str(title or "").lower()).strip()


def _existing_keys() -> set[str]:
    """Every card this home already has, however it came to have one.

    Read live rather than accumulated: a card made through the ask bar,
    through onboarding or by hand is still a card this page must not
    offer to create, and none of those told this module anything.
    """
    keys: set[str] = set()
    try:
        for cat in user_categories.load():
            key = fingerprint(cat.get("title") or "")
            if key:
                keys.add(key)
    except Exception as exc:  # noqa: BLE001 — an unreadable catalog must
        # not stop the page; the cost is one duplicate idea somebody can
        # dismiss, where raising here would be a blank page.
        log.warning("could not read the categories (%s)", exc)
    return keys


def _answered_keys(data: dict) -> set[str]:
    return {str(e.get("key") or "") for e in data.get("answered") or []
            if isinstance(e, dict)}


def known_keys() -> set[str]:
    """What a pass may not propose: answered ideas and existing cards."""
    return _answered_keys(_load()) | _existing_keys()


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def _clean(value, cap: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:cap]


def _next_id(items: list[dict], now: float | None = None) -> int:
    """A millisecond, bumped past anything already taken.

    `todo_store._next_id`'s rule, and it bites harder here than there: one
    pass files up to eight ideas in a single loop, well inside a
    millisecond, and every press on this page keys on the id.
    """
    stamp = int((now if now is not None else time.time()) * 1000)
    taken = {int(e.get("id") or 0) for e in items if isinstance(e, dict)}
    while stamp in taken:
        stamp += 1
    return stamp


def _shape(entry: dict) -> dict:
    status = entry.get("status")
    return {
        "id": int(entry.get("id") or 0),
        "title": _clean(entry.get("title"), MAX_TITLE),
        "icon": (_clean(entry.get("icon"), MAX_ICON) or "✨"),
        "focus": str(entry.get("focus") or "").strip()[:MAX_FOCUS],
        "why": _clean(entry.get("why"), MAX_WHY),
        "question": _clean(entry.get("question"), MAX_QUESTION),
        "status": status if status in STATUSES else "open",
        "added_at": int(entry.get("added_at") or 0),
        "run_id": str(entry.get("run_id") or "")[:64],
        "category_id": str(entry.get("category_id") or "")[:64],
        "ended_at": int(entry.get("ended_at") or 0),
    }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def load() -> list[dict]:
    return [_shape(e) for e in _load()["ideas"] if isinstance(e, dict)]


def open_ideas() -> list[dict]:
    """Newest first — an idea proposed this morning is the news."""
    rows = [e for e in load() if e["status"] == "open"]
    rows.sort(key=lambda e: e["added_at"], reverse=True)
    return rows


def get(idea_id) -> dict | None:
    try:
        wanted = int(idea_id)
    except (TypeError, ValueError):
        return None
    for entry in load():
        if entry["id"] == wanted:
            return entry
    return None


def state() -> dict:
    """What the page renders, in one read.

    `last_count` is what the previous pass PROPOSED and not what is on
    the page now, because the two answer different questions: a pass that
    found four ideas and a page showing four because three were dismissed
    are different stories, and only the first says whether the run worked.
    """
    data = _load()
    rows = open_ideas()
    return {
        "ideas": rows,
        "open": len(rows),
        "last_run": int(data.get("last_run") or 0),
        "last_error": str(data.get("last_error") or "")[:400],
        "last_count": int(data.get("last_count") or 0),
        "runs": int(data.get("runs") or 0),
        "answered": len(data.get("answered") or []),
        "writable": writable(),
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def add_many(items, *, run_id: str = "", now: float | None = None) -> dict:
    """File what a pass proposed. Returns what happened to each one.

    Three reasons an idea does not land, and they are counted separately
    because they mean different things to somebody reading the page: it
    is a card this home already has, it is one already answered, or the
    page is full. Only the third is a reason to do anything.
    """
    data = _load()
    rows = [e for e in data["ideas"] if isinstance(e, dict)]
    blocked = _answered_keys(data) | _existing_keys()
    # Within one batch too: a run that proposes the same card twice in
    # different words would otherwise file both.
    seen = {fingerprint(e.get("title") or "") for e in rows
            if e.get("status") == "open"}
    open_now = len([e for e in rows if e.get("status", "open") == "open"])

    filed, duplicate, answered, full = [], 0, 0, 0
    for item in list(items or [])[:MAX_PER_RUN]:
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title"), MAX_TITLE)
        focus = str(item.get("focus") or "").strip()[:MAX_FOCUS]
        if not title or not focus:
            continue
        key = fingerprint(title)
        if key in seen or key in _existing_keys():
            duplicate += 1
            continue
        if key in blocked:
            answered += 1
            continue
        if open_now >= MAX_OPEN:
            full += 1
            continue
        entry = _shape({
            "id": _next_id(rows, now),
            "title": title,
            "icon": item.get("icon"),
            "focus": focus,
            "why": item.get("why"),
            "question": item.get("question"),
            "status": "open",
            "added_at": int(now if now is not None else time.time()),
            "run_id": run_id,
        })
        rows.append(entry)
        filed.append(entry)
        seen.add(key)
        open_now += 1

    data["ideas"] = rows
    _write(data)
    return {"filed": filed, "duplicate": duplicate, "answered": answered,
            "full": full}


def _remember(data: dict, key: str, title: str, how: str,
              now: float | None = None) -> None:
    """Record that this idea has been answered, so no pass offers it again."""
    if not key:
        return
    answered = [e for e in data.get("answered") or [] if isinstance(e, dict)]
    answered = [e for e in answered if e.get("key") != key]
    answered.append({"key": key, "title": title, "how": how,
                     "when": int(now if now is not None else time.time())})
    # Oldest first out, the index's own rule: this is "do not offer this
    # again" and never a record of what somebody did.
    data["answered"] = answered[-MAX_ANSWERED:]


def accept(idea_id, *, now: float | None = None) -> dict | None:
    """Turn an idea into a card. Returns the category, or None.

    The category is created FIRST and the row is only marked afterwards,
    `h_finding_todo`'s rule: an idea that vanished into a card that was
    never created is the one outcome with no way back, where a category
    created twice is visible and deletable.
    """
    entry = get(idea_id)
    if not entry or entry["status"] != "open":
        return None
    try:
        created = user_categories.create({
            "title": entry["title"], "icon": entry["icon"],
            "focus": entry["focus"],
        })
    except ValueError as exc:
        log.warning("could not create %r: %s", entry["title"], exc)
        return None

    data = _load()
    for row in data["ideas"]:
        if isinstance(row, dict) and int(row.get("id") or 0) == entry["id"]:
            row["status"] = "accepted"
            row["category_id"] = created.get("id") or ""
            row["ended_at"] = int(now if now is not None else time.time())
    _remember(data, fingerprint(entry["title"]), entry["title"], "accepted",
              now)
    _write(data)
    return created


def dismiss(idea_id, *, now: float | None = None) -> bool:
    """Take an idea off the page, and stop it being offered again.

    It writes no memory line and settles nothing about the house: this is
    a statement about an IDEA, not about the home — `clear_resolved`'s
    reason for writing nothing, and the mute's one store over.
    """
    entry = get(idea_id)
    if not entry or entry["status"] != "open":
        return False
    data = _load()
    for row in data["ideas"]:
        if isinstance(row, dict) and int(row.get("id") or 0) == entry["id"]:
            row["status"] = "dismissed"
            row["ended_at"] = int(now if now is not None else time.time())
    _remember(data, fingerprint(entry["title"]), entry["title"], "dismissed",
              now)
    _write(data)
    return True


def record_run(count: int, *, error: str = "", now: float | None = None) -> None:
    """Stamp a finished pass.

    The stamp is written whether or not anything was proposed, because it
    is what the weekly schedule reads: a pass that found nothing and was
    not recorded would be re-run on the next tick, for ever.
    """
    data = _load()
    data["last_run"] = int(now if now is not None else time.time())
    data["last_count"] = max(0, int(count or 0))
    data["last_error"] = str(error or "")[:400]
    data["runs"] = int(data.get("runs") or 0) + 1
    _write(data)


# ---------------------------------------------------------------------------
# The weekly top-up
# ---------------------------------------------------------------------------
# A house changes slowly, so ideas arrive slowly. The button is what
# somebody presses when they want one now; this is what keeps the page
# from being empty for anybody who never presses it.

TOP_UP_DAYS = 7


def due(now: float | None = None) -> bool:
    """Whether the weekly pass is owed.

    A never-run install is due, which is what puts something on the page
    for a home that onboarded before this existed. There is no window and
    no hour: unlike a brief, nobody is waiting for this at a particular
    time, so an add-on that was off all Tuesday should still top up on
    Wednesday rather than skip a week to protect an hour it does not have.
    """
    data = _load()
    last = float(data.get("last_run") or 0)
    stamp = now if now is not None else time.time()
    return (stamp - last) >= TOP_UP_DAYS * 86400


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
# One turn, read-only tools, over the map plus what brAIn has learned and
# measured. It is `onboarding.RECOMMEND_SYSTEM`'s job at a different
# moment in a home's life, and the differences are all consequences of
# that: this home already HAS cards, it has months of history rather than
# an afternoon's, and the measurements underneath it have had time to
# become answerable.

IDEAS_SYSTEM = """You propose recurring insight cards for one specific home, for a person who has been living with this dashboard for a while and is asking what they are missing.

You have READ-ONLY Home Assistant tools and brAIn's own measurements. Use them. Search by domain and by name, read the entities that matter, read their history and statistics, and ask what is normal here before you claim something is interesting. Change nothing.

You are given what brAIn has learned about this home, a map of its data, what it has measured, and THE CARDS IT ALREADY HAS. Do not propose a card this home already has, in new words or old.

What makes a good idea here:

- It could not have been written for a different house. Name the real rooms, devices, meters and patterns. "Energy" is not an idea; "The heat pump against everything else — it is 60% of your winter usage and nothing on the dashboard separates them" is.
- It is worth generating AGAIN. A card runs on a schedule, so the question it answers has to have a moving answer. A one-off curiosity is a question for the ask bar, not a card.
- It rests on data this home actually has. If the history, the entities or the measurements are not there, the card will say the same empty thing every run. Check before you propose.
- It tells the person something they would not already know from looking at Home Assistant. A card that restates a thermostat's own screen is a card nobody reads twice.

Prefer ideas that use what brAIn can do and a dashboard cannot: comparing a room against the rest of the house, a month against the month before, a measured baseline against what is happening now, one appliance's own cycle history, the gap between what an automation was meant to do and what it does.

Reply with ONE JSON object and nothing else:
{"ideas": [{"title": "Short card name (max 60 chars)",
            "icon": "one emoji",
            "why": "Why THIS home, citing what you actually found — the rooms, the numbers, the entities. Two sentences at most. This is the sentence the homeowner reads to decide.",
            "question": "The question this card answers every time it runs, in one line.",
            "focus": "What Claude should analyse each run. Specific: name the entities, areas, statistics and comparisons to make. This becomes the card's standing prompt, so write it to be read by a model with tools and no memory of this conversation."}],
 "nothing_new": false,
 "note": "Only when nothing_new is true: one sentence on why there is nothing worth adding right now."}

Propose at most {{CAP}}, and fewer is better. Three ideas somebody takes beat eight they scroll past.

If this home is already well covered, or what is left is too thin to make a card worth running, set "nothing_new": true, return an empty list, and say so in "note". That is a real answer and a good one — padding the page with generic cards is how a dashboard stops being read."""


def system_prompt(cap: int = MAX_PER_RUN) -> str:
    """The contract, with the cap written into it once.

    A plain replace and not `%` or `.format`: this is a page of PROSE
    about a house, and prose about a house says things like "60% of your
    winter usage". Percent-formatting turned that into a `TypeError` at
    the moment the pass ran — a template that breaks on its own content
    is a template the next person to edit it will break again.
    """
    return IDEAS_SYSTEM.replace("{{CAP}}", str(max(1, int(cap))))


def build_prompt(memory: str, orientation, have, measured: str = "") -> str:
    """What one pass is given.

    `have` is the whole point of the block: without it the run proposes
    the cards this home already has, every week, and the page fills with
    things to dismiss. It is passed as titles rather than as full
    definitions because what the run needs is "do not suggest this
    again", not the focus text of a card it is not being asked to edit.
    """
    parts = ["Propose insight cards worth adding to THIS home's dashboard.\n"]
    titles = [str(t).strip() for t in (have or []) if str(t or "").strip()]
    if titles:
        parts.append("CARDS THIS HOME ALREADY HAS — do not propose these, "
                     "or a reworded version of one:\n"
                     + "\n".join(f"- {t}" for t in titles))
    else:
        parts.append("CARDS THIS HOME ALREADY HAS: none yet.")
    if memory.strip():
        parts.append("\nWHAT BRAIN HAS LEARNED ABOUT THIS HOME:\n"
                     + memory.strip())
    if measured.strip():
        parts.append("\nWHAT BRAIN HAS MEASURED (a card can build on any of "
                     "these; one that is not ready yet cannot carry a card):\n"
                     + measured.strip())
    if orientation:
        parts.append("\nTHE SHAPE OF ITS DATA:\n"
                     + json.dumps(orientation, separators=(",", ":"))[:20000])
    parts.append("\nSearch for what you need before proposing anything.")
    return "\n".join(parts)


def parse(text: str) -> dict:
    """Validate a reply into {ideas, nothing_new, note}.

    A reply that did not parse RAISES, because the caller has to tell a
    failed run from a run that had nothing to say — those are different
    claims and only one of them is worth showing as an error.
    """
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    obj = None
    try:
        obj = json.loads(stripped)
    except ValueError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if match:
            try:
                obj = json.loads(match.group(0))
            except ValueError:
                obj = None
    if not isinstance(obj, dict):
        raise ValueError("the ideas reply was not valid JSON")

    out = []
    for item in (obj.get("ideas") or [])[:MAX_PER_RUN]:
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title"), MAX_TITLE)
        focus = str(item.get("focus") or "").strip()[:MAX_FOCUS]
        # Both or neither: a title with no focus is a card that cannot be
        # generated, and a focus with no title is one nobody can pick.
        if not title or not focus:
            continue
        out.append({
            "title": title,
            "icon": (_clean(item.get("icon"), MAX_ICON) or "✨"),
            "focus": focus,
            "why": _clean(item.get("why"), MAX_WHY),
            "question": _clean(item.get("question"), MAX_QUESTION),
        })

    # A run that proposed nothing IS `nothing_new`, whatever it set: the
    # flag and the empty list are two spellings of one answer, and taking
    # the flag alone would render "nothing to suggest" as a failure.
    nothing = bool(obj.get("nothing_new")) or not out
    return {"ideas": out, "nothing_new": nothing,
            "note": _clean(obj.get("note"), 400) if nothing else ""}
