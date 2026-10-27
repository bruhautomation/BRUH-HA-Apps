"""Morph learning: two loops, the way brAIn has them.

**Loop one — suggestions you approve.** Morph keeps a log of how the
dashboard is used (what is opened, toggled, slid, and when; which of
brAIn's changes were kept and which were undone). A learning pass — at most
every ``learning_hours``, and only when something new happened — hands a
digest of that to brAIn, which may look at the house with read-only tools
and answers with at most ``MAX_SUGGESTIONS`` improvements. Each one appears
IN PLACE, in the section it is about, with *Do it*, *Not now* and *No*.
Nothing is changed until somebody presses Do it, and Do it is an ordinary
Tell (`tell.start`), so it lands as one commit with Undo.

**What makes it recursive** is that the pass is handed its own record:
which suggestions were done, which were declined and why, which changes
were then undone. It answers with a revised set of LESSONS, written to
``/config/morph/LEARNED.md`` — which every later Tell and every later pass
reads. A suggestion people keep refusing becomes a lesson not to make it;
a change people keep undoing becomes a lesson about how this household
wants its dashboard. The scorecard (`scorecard`) is the evidence the loop
is getting better rather than louder.

**Loop two — Morph's own code** lives in `devloop.py`: the faults and
gaps that need a change to Morph itself, not to this house's dashboard,
go to brAIn's development loop and on to the private reports repository.
A gap the learning pass notices is a SUGGESTION of kind ``code`` — "Send
it as an issue?" — never filed on the model's say-so: a report written by
a model about code it cannot see is a guess until somebody agrees.

**This loop is about the dashboard and only the dashboard.** brAIn learns
the house on its own (memory, findings, measurements); a Morph pass that
proposed automations or filed house facts as lessons would be a second,
weaker copy of that. So a pass suggests dashboard changes, its lessons are
rules about how this household wants its dashboard to look and behave,
and a fact about the house it happens to notice is not a lesson.

Three rules:

* **A pass that has nothing new to read does not run.** The model call is
  the only cost here, and re-asking an unchanged question buys the same
  answer.
* **A declined suggestion is never offered again** — keyed on its words,
  the way brAIn's settled ledger keys a finding — and the declined list is
  in the prompt, so the model does not spend a slot rewording it.
* **The gates are brAIn's**: a pass is a SCHEDULED task, so brAIn's own
  pause and usage budget hold it, and with brAIn absent nothing runs.
"""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import os
import re
import time

import brain
import paths
import settings
import store
import wording

log = logging.getLogger("morph.learning")

MAX_SUGGESTIONS = 5
MAX_OPEN = 8
MAX_LESSONS = 25
WINDOW_S = 30 * 86400
SNOOZE_S = 7 * 86400
PASS_TIMEOUT_S = 600

SCHEMA = {
    "type": "object",
    "required": ["suggestions", "lessons"],
    "properties": {
        "suggestions": {"type": "array", "maxItems": MAX_SUGGESTIONS, "items": {
            "type": "object", "required": ["title", "why", "change"], "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "description": "Under 60 characters, said as the change."},
                "why": {"type": "string", "description": "One sentence of evidence from the digest."},
                "change": {"type": "string",
                           "description": "The instruction Morph will hand you if they press Do it."},
                "kind": {"type": "string", "enum": ["dashboard"]},
                "section": {"type": "string", "description": "Section id it belongs in, if any."},
                "card": {"type": "string", "description": "Card id it is about, if any."},
            }}},
        "lessons": {"type": "array", "maxItems": MAX_LESSONS, "items": {
            "type": "object", "required": ["text"], "additionalProperties": False,
            "properties": {
                "text": {"type": "string", "description": "The rule, without its (you)/(tell)/(learned) mark."},
                "evidence": {"type": "array", "items": {"type": "string"},
                             "description": "For a NEW lesson: at least two separate things in the digest "
                                            "that point to it, or one reason a person typed, quoted as "
                                            "`note: <their words>`. Not needed to keep an existing one."}}},
            "description": "The COMPLETE revised list of lessons, not only new ones. Rules about the "
                           "dashboard, never facts about the house."},
        "code_reports": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "required": ["what", "detail"], "additionalProperties": False,
            "properties": {"what": {"type": "string"}, "detail": {"type": "string"},
                           "why": {"type": "string",
                                   "description": "The evidence in the digest that shows the problem."}}},
            "description": "Problems that need a change to Morph's own code, not to this "
                           "dashboard. Morph asks the household whether to send each one."},
    },
}

_WS = re.compile(r"\s+")


def _key(text: str) -> str:
    return hashlib.sha1(_WS.sub(" ", str(text or "").lower()).strip().encode()).hexdigest()[:12]


_WORD = re.compile(r"[a-z0-9]{3,}")
SIMILAR = 0.75
EVENT_STEP = 25  # a pass is worth running after this many new uses, not after one


def _words(text: str) -> frozenset:
    return frozenset(_WORD.findall(str(text or "").lower()))


def _similar(a: frozenset, b: frozenset) -> bool:
    """A reworded title for the same idea. Exact keys only catch the same
    words; a model asked for fresh ideas rewords an open one all the time, and
    each reworded copy spends a slot of ``MAX_OPEN`` and a person's attention."""
    return bool(a and b) and len(a & b) / len(a | b) >= SIMILAR


# ------------------------------------------------------------------ the log

USAGE_KINDS = ("open", "toggle", "slide", "scene", "history", "tell", "undo", "ask", "edit")


def usage(since: float = 0.0) -> list[dict]:
    rows = paths.read_jsonl(paths.USAGE, limit=50000)
    return [r for r in rows if float(r.get("ts") or 0) >= since]


LOG_SENTENCES = {
    "never": ("Morph has no record of use yet: the panel has not logged a single tap, so the zero "
              "counts are not evidence that nobody uses the dashboard."),
    "unreadable": ("The use log could not be read, so the counts are missing, not zero: they are not "
                   "evidence that nobody uses the dashboard."),
    "quiet": "The use log is there and holds nothing from the last 30 days: nobody used the dashboard.",
    "ok": "",
}


def usage_log(since: float) -> dict:
    """What the use log can say, apart from its counts (#361). A digest of
    0 events over 0 days read the same whether nothing had ever been
    logged, the file could not be read, or the household really did not
    touch the page for a month — and only the last is evidence about the
    dashboard. ``state`` is never | unreadable | quiet | ok."""
    try:
        size = paths.USAGE.stat().st_size
    except FileNotFoundError:
        return {"state": "never", "newest_at": None}
    except OSError:
        return {"state": "unreadable", "newest_at": None}
    if not paths.USAGE.is_file():
        return {"state": "unreadable", "newest_at": None}
    try:
        with open(paths.USAGE, encoding="utf-8") as f:
            f.read(1)
    except OSError:
        return {"state": "unreadable", "newest_at": None}
    rows = paths.read_jsonl(paths.USAGE, limit=50000) if size else []
    newest = max((float(r.get("ts") or 0) for r in rows), default=0.0) or None
    if not rows:
        return {"state": "never", "newest_at": None}
    return {"state": "ok" if newest and newest >= since else "quiet", "newest_at": newest}


def prune_usage(max_age_s: int = 60 * 86400) -> None:
    rows = usage(time.time() - max_age_s)
    try:
        paths.write_text(paths.USAGE, "".join(
            __import__("json").dumps(r, ensure_ascii=False) + "\n" for r in rows))
    except OSError:
        pass  # pruning is housekeeping; the log is read with a time window either way


def prune_due(now: float | None = None) -> bool:
    """Prune the use log once a day. It was written and never called, so the
    file grew for ever and every pass parsed all of it."""
    now = now or time.time()
    if now - float(state().get("last_prune") or 0) < 86400:
        return False
    prune_usage()
    _set_state(last_prune=now)
    return True


def record_outcome(row: dict) -> None:
    try:
        paths.append_jsonl(paths.OUTCOMES, row)
    except OSError:
        pass  # an outcome is evidence for learning, never worth failing the action it records


def outcomes(since: float = 0.0) -> list[dict]:
    return [r for r in paths.read_jsonl(paths.OUTCOMES) if float(r.get("at") or 0) >= since]


# ------------------------------------------------------------- suggestions

def _mint_id(taken: set, now: float) -> str:
    """An id no other suggestion has. It was a millisecond stamp plus one
    character, and a pass that made several in one millisecond (or two
    broken card files reported together) gave them one id between them, so
    an answer to one changed whichever came first. Minted past what is
    taken, the way brAIn's proposals and to-do ids are."""
    n = int(float(now or 0) * 1000)
    while f"g{n}" in taken:
        n += 1
    taken.add(f"g{n}")
    return f"g{n}"


def _repair_ids(items: list) -> bool:
    """Give every suggestion after the first that shares an id one of its
    own. The first keeps its id, and with it the brAIn case filed under it;
    the others are filed again under their new ids."""
    taken = {str(it.get("id") or "") for it in items if isinstance(it, dict)}
    seen: set = set()
    changed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "")
        if not iid or iid in seen:
            it["id"] = _mint_id(taken, float(it.get("created") or 0) or time.time())
            it.pop("filed", None)
            it.pop("withdrawn", None)
            changed = True
        seen.add(it["id"])
    return changed


def _load() -> dict:
    data = paths.read_json(paths.SUGGESTIONS, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    data.setdefault("declined", {})
    data["items"] = [it for it in data["items"] if isinstance(it, dict)]
    if _repair_ids(data["items"]):
        _save(data)
    return data


def _taken(data: dict) -> set:
    return {str(it.get("id") or "") for it in data["items"]}


def _save(data: dict) -> None:
    paths.write_json(paths.SUGGESTIONS, data)


def listing(now: float | None = None) -> list[dict]:
    """What the dashboard shows: open suggestions, snoozed ones hidden until
    their date."""
    now = now or time.time()
    out = []
    for it in _load()["items"]:
        if it.get("status") in ("open", "doing") and float(it.get("snoozed_until") or 0) <= now:
            out.append(it)
    return out


def all_items() -> list[dict]:
    return _load()["items"]


def add_suggestions(rows: list[dict], dash: dict) -> int:
    data = _load()
    known = {it["key"] for it in data["items"]} | set(data["declined"])
    sections = {s["id"] for f in dash.get("floors") or [] for s in f.get("sections") or []}
    cards = {c["id"] for f in dash.get("floors") or [] for s in f.get("sections") or []
             for g in s.get("groups") or [] for c in g.get("cards") or []}
    open_now = sum(1 for it in data["items"] if it.get("status") == "open")
    seen_words = [_words(it["title"]) for it in data["items"]] + \
        [_words(v.get("title")) for v in data["declined"].values()]
    added = 0
    taken = _taken(data)
    for row in rows or []:
        if not isinstance(row, dict) or open_now >= MAX_OPEN:
            continue
        title = str(row.get("title") or "").strip()[:80]
        change = wording.clip(row.get("change"), 1200)
        if not title or not change:
            continue
        key = _key(title)
        if key in known:
            continue
        words = _words(title)
        if any(_similar(words, w) for w in seen_words):
            continue
        known.add(key)
        seen_words.append(words)
        item = {"id": _mint_id(taken, time.time()), "key": key, "title": title,
                "why": str(row.get("why") or "").strip()[:400], "change": change,
                "kind": "code" if row.get("kind") == "code" else "dashboard",
                "status": "open", "created": time.time()}
        if row.get("section") in sections:
            item["section"] = row["section"]
        if row.get("card") in cards:
            item["card"] = row["card"]
        data["items"].append(item)
        added += 1
        open_now += 1
    data["items"] = data["items"][-200:]
    _save(data)
    return added


def code_suggestions(reports: list) -> list[dict]:
    """A pass's ``code_reports`` as suggestions of kind ``code``: the
    household is asked whether brAIn should make it on this house's copy of
    Morph (Do it) or only send it as an issue, rather than the model's
    sentence being filed in their name."""
    out = []
    for rep in (reports or [])[:5]:
        if not isinstance(rep, dict) or not str(rep.get("what") or "").strip():
            continue
        what = str(rep["what"]).strip()[:140]
        why = str(rep.get("why") or "").strip()[:400]
        out.append({"kind": "code", "title": what[:80],
                    "why": why or ("A change to Morph itself. brAIn can make it here now, then ask "
                                   "whether to send it to Morph's developers."),
                    "change": f"{what}\n\n{wording.clip(rep.get('detail'), 1100)}"})
    return out


HOUSE_CARD_TITLE = "Fix the card code {name}"


def house_card_broken(name: str, error: str, now: float | None = None) -> bool:
    """A card file in /config/morph/cards failed to load. That code is
    this house's — brAIn wrote it in a Tell — so it is not a fault in
    Morph's code and is not sent to Morph's developers; it comes back to
    the house as a suggestion whose Do it is a Tell that fixes the file.

    A file that breaks again after it was fixed is offered again (a done
    suggestion is reopened); one the household said No to stays quiet."""
    now = now or time.time()
    name = str(name or "")[:80]
    error = " ".join(str(error or "").split())[:400]
    title = HOUSE_CARD_TITLE.format(name=name)
    key = _key(title)
    data = _load()
    if key in data["declined"]:
        return False
    why = f"It fails to load in the browser: {error}" if error else "It fails to load in the browser."
    change = (f"The custom card code /config/morph/cards/{name} fails to load in the browser"
              + (f": {error}" if error else "") + ". Fix the file so it loads, keeping what the card is for. "
              "It is this house's card code, not Morph's.")
    item = next((it for it in data["items"] if it.get("key") == key), None)
    if item and item.get("status") in ("open", "doing"):
        item.update(why=why, change=change, card_file=name)
    elif item:
        item.update(status="open", why=why, change=change, created=now, card_file=name)
        for gone in ("snoozed_until", "filed", "withdrawn"):
            item.pop(gone, None)
    else:
        data["items"].append({"id": _mint_id(_taken(data), now), "key": key, "title": title, "why": why,
                              "change": change, "kind": "dashboard", "status": "open", "created": now,
                              "card_file": name})
    _save(data)
    return True


def house_card_loaded(name: str, now: float | None = None) -> bool:
    """The panel loaded a card file cleanly that had a "Fix the card code"
    suggestion open: the file is fixed, however it was fixed, so the
    suggestion closes itself rather than asking somebody to fix a working
    card. Answers whether one closed."""
    now = now or time.time()
    key = _key(HOUSE_CARD_TITLE.format(name=str(name or "")[:80]))
    data = _load()
    item = next((it for it in data["items"] if it.get("key") == key
                 and it.get("status") in ("open", "doing")), None)
    if not item or float(item.get("created") or 0) > now:
        return False
    item.update(status="done", decided=now)
    _save(data)
    record_outcome({"kind": "suggestion", "id": item["id"], "verb": "fixed", "title": item["title"], "at": now})
    return True


def decide(sid: str, verb: str, note: str = "") -> dict:
    """Not now / No / Send. Do it is `tell.start` with the suggestion's
    change, and calls `mark_doing` once it has an id; on a ``code``
    suggestion the yes is Send, which files it for Morph's own loop."""
    data = _load()
    item = next((it for it in data["items"] if it.get("id") == sid), None)
    if not item:
        return {"ok": False, "error": "That suggestion is gone."}
    note = str(note or "").strip()[:400]
    if verb == "send":
        if item.get("kind") != "code":
            return {"ok": False, "error": "Only a problem with Morph itself is sent as an issue."}
        if not settings.load()["report_code_issues"]:
            return {"ok": False, "error": "“Report Morph’s own problems” is off in Settings, so "
                                          "nothing reaches brAIn's development loop."}
        import devloop
        # The evidence goes with the change: a report that says only what
        # to do is one nobody can weigh.
        detail = item["change"] + (f"\n\nWhy brAIn suggested it: {item['why']}" if item.get("why") else "")
        devloop.note_fault("Learning", item["title"], detail, source="learning")
        item["status"] = "sent"
        item["decided"] = time.time()
    elif verb == "not_now":
        item["snoozed_until"] = time.time() + SNOOZE_S
    elif verb == "no":
        item["status"] = "declined"
        item["note"] = note
        item["decided"] = time.time()
        data["declined"][item["key"]] = {"title": item["title"], "note": note, "at": time.time()}
        # The reason is not written down as a lesson here. "We watch it at
        # night" under "Hide the camera" is evidence, not a rule; it reaches
        # the next pass in the digest (the outcome below carries it), and
        # becomes a lesson only if it states a rule about the dashboard.
    else:
        return {"ok": False, "error": "Unknown answer."}
    _save(data)
    record_outcome({"kind": "suggestion", "id": sid, "verb": verb, "title": item["title"],
                    "note": note, "at": time.time()})
    return {"ok": True}


def mark_doing(sid: str, tell_id: str) -> dict | None:
    data = _load()
    item = next((it for it in data["items"] if it.get("id") == sid), None)
    if not item:
        return None
    item["status"] = "doing"
    item["tell"] = tell_id
    item["decided"] = time.time()
    _save(data)
    record_outcome({"kind": "suggestion", "id": sid, "verb": "do", "title": item["title"],
                    "tell": tell_id, "at": time.time()})
    return item


def settle_doing(read_tell) -> None:
    """A suggestion being done is settled by its tell: done, or failed (and
    then offered again, because a run that failed said nothing about the
    idea)."""
    data = _load()
    changed = False
    for it in data["items"]:
        if it.get("status") != "doing":
            continue
        st = read_tell(it.get("tell") or "") or {}
        if st.get("phase") == "done":
            it["status"] = "done"
            it["commit"] = st.get("commit") or ""
            changed = True
        elif st.get("phase") == "failed":
            it["status"] = "open"
            it["last_error"] = st.get("say") or ""
            it.pop("filed", None)
            it.pop("withdrawn", None)
            changed = True
    if changed:
        _save(data)


# ------------------------------------------------------ brAIn's one list

# A suggestion is not a list of Morph's own any more (docs/design/
# morph-vision.md §13.1): each open one is FILED as one of brAIn's cases
# (source "morph", kind "opportunity") through brAIn's request queue, and
# its ending — given in Morph, on a phone, in Repairs or in brAIn's Today —
# comes back in brAIn's `cases.json` under `ended_morph`. This file keeps
# what it filed and what it was told, as an index (it is what stops the
# next pass proposing the same thing), never as something drawn.
MORPH_SOURCE = "morph"
ENDED = ("declined", "sent", "doing", "done")
_SEQ = 0


def _brain_requests_dir():
    return paths.BRAIN_SHARED / "finding-requests"


def _drop_request(body: dict) -> bool:
    """One request into brAIn's queue: a scratch name renamed, a name that
    sorts chronologically (brAIn drains oldest first)."""
    global _SEQ
    d = _brain_requests_dir()
    if not paths.BRAIN_SHARED.is_dir():
        return False
    try:
        d.mkdir(parents=True, exist_ok=True)
        _SEQ += 1
        name = f"{int(time.time() * 1000):015d}-{_SEQ:06d}-morph"
        scratch = d / f".{name}.tmp"
        scratch.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.replace(scratch, d / f"{name}.json")
        return True
    except OSError:
        return False


def case_body(item: dict) -> dict:
    """The case brAIn files for one suggestion: the claim is the change in a
    sentence, the ask is the question a person answers in their own words."""
    code = item.get("kind") == "code"
    return {"kind": "morph_case", "action": "file", "key": item["id"], "case_kind": "opportunity",
            "claim": item["title"], "detail": item.get("why") or "",
            "ask": "Should brAIn change Morph itself for this?" if code else "Should I make this change to the dashboard?",
            "section": item.get("section") or "", "card": item.get("card") or "",
            "entity_id": item.get("entity_id") or "", "via": MORPH_SOURCE}


def sync_brain(start_tell=None) -> dict:
    """File what is open and not yet filed; withdraw what ended here; read
    the endings brAIn published and act on them. ``start_tell(item)``
    begins the Tell an accepted suggestion asks for and returns its id."""
    data = _load()
    filed = withdrawn = applied = 0
    now = time.time()
    for it in data["items"]:
        snoozed = float(it.get("snoozed_until") or 0) > now
        if it.get("status") == "open" and not it.get("filed") and not snoozed:
            if _drop_request(case_body(it)):
                it["filed"] = now
                filed += 1
        elif it.get("filed") and not it.get("withdrawn") and (
                it.get("status") in ENDED or (it.get("status") == "open" and snoozed)):
            # Answered here — No, Send, Do it, a card that loads again — or
            # snoozed: brAIn's case goes, or it goes on asking about a
            # suggestion the page no longer shows. A snoozed one is filed
            # again when its date comes round.
            if _drop_request({"kind": "morph_case", "action": "withdraw", "key": it["id"], "via": MORPH_SOURCE}):
                withdrawn += 1
                if it.get("status") == "open":
                    it.pop("filed", None)
                else:
                    it["withdrawn"] = now
    feed = paths.read_json(paths.BRAIN_SHARED / "morph" / "cases.json", {}) or {}
    ended = feed.get("ended_morph") if isinstance(feed, dict) else None
    seen = set(data.setdefault("ended_seen", []))
    for e in ended if isinstance(ended, list) else []:
        if not isinstance(e, dict):
            continue
        key = str(e.get("key") or "")
        mark = f"{key}@{e.get('at')}"
        if not key or mark in seen:
            continue
        seen.add(mark)
        it = next((x for x in data["items"] if x.get("id") == key), None)
        if not it or it.get("status") not in ("open",):
            continue
        how = str(e.get("how") or "")
        note = str(e.get("note") or "")[:400]
        if how == "accepted" and start_tell:
            tid = start_tell(it)
            if tid:
                it.update(status="doing", tell=tid, decided=now, withdrawn=now)
                record_outcome({"kind": "suggestion", "id": key, "verb": "do", "title": it["title"], "tell": tid, "at": now})
        elif how == "declined":
            it.update(status="declined", note=note, decided=now, withdrawn=now)
            data["declined"][it["key"]] = {"title": it["title"], "note": note, "at": now}
            record_outcome({"kind": "suggestion", "id": key, "verb": "no", "title": it["title"], "note": note, "at": now})
        else:
            # Dismissed, snoozed or put on To Do: not now, and filed again
            # when it comes back round.
            it["snoozed_until"] = now + SNOOZE_S
            it.pop("filed", None)
            record_outcome({"kind": "suggestion", "id": key, "verb": "not_now", "title": it["title"], "at": now})
        applied += 1
    data["ended_seen"] = sorted(seen)[-200:]
    _save(data)
    return {"filed": filed, "withdrawn": withdrawn, "applied": applied}


# ----------------------------------------------------------------- lessons

# LEARNED.md has three writers: the household (by hand, or in Settings), a
# Tell's `lesson`, and the learning pass, which rewrites the list. Each line
# says which wrote it, because the pass used to replace the whole file and a
# rule somebody typed by hand was one rewrite away from being gone. A line
# with no mark — every line of a file from before the marks — is the
# household's: the safe reading of "nobody said" is that a person did.
SOURCES = ("you", "tell", "learned")
_TAG = re.compile(r"^(.*?)\s*\((you|tell|learned)\)\s*$", re.S)


def split_lesson(line: str) -> tuple[str, str]:
    """(text, source) of one LEARNED.md line."""
    line = " ".join(str(line or "").split())
    m = _TAG.match(line)
    return (m.group(1).strip(), m.group(2)) if m else (line, "you")


def read_lesson_rows() -> list[dict]:
    try:
        text = paths.LEARNED.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for ln in text.splitlines():
        if ln.startswith("- "):
            body, source = split_lesson(ln[2:])
            if body:
                rows.append({"text": body, "source": source})
    return rows


def read_lessons(tagged: bool = False) -> list[str]:
    """The lessons' words; ``tagged`` adds each line's (source) mark, which
    is how the Settings editor shows them and how they are saved back."""
    return [f"{r['text']} ({r['source']})" if tagged else r["text"] for r in read_lesson_rows()]


def _rows_of(lessons) -> list[dict]:
    rows = []
    for x in lessons or []:
        if isinstance(x, dict):
            text, source = str(x.get("text") or ""), str(x.get("source") or "you")
            text, tagged = split_lesson(text)
            source = source if source in SOURCES else tagged
        else:
            text, source = split_lesson(str(x))
        text = text[:300]
        if text:
            rows.append({"text": text, "source": source})
    return rows


def write_lessons(lessons, commit: bool = True) -> None:
    """Write LEARNED.md from lines (marks parsed; an unmarked line is the
    household's) or ``{text, source}`` rows. Over ``MAX_LESSONS`` the oldest
    line a machine wrote goes first; a household's own line is never cut to
    make room."""
    import gitrepo
    seen, out = set(), []
    for row in _rows_of(lessons):
        k = _key(row["text"])
        if k not in seen:
            seen.add(k)
            out.append(row)
    while len(out) > MAX_LESSONS:
        machine = next((i for i, r in enumerate(out) if r["source"] != "you"), None)
        if machine is None:
            break
        out.pop(machine)
    body = ("# What this household has taught Morph\n\n"
            "Every Tell and every learning pass reads this. Edit it freely — it is yours.\n"
            "Each line ends with who wrote it: (you) the household, (tell) brAIn during a Tell,\n"
            "(learned) Morph's learning pass. A line with no mark is yours, and Morph never\n"
            "rewords or drops a line of yours.\n\n"
            + "".join(f"- {r['text']} ({r['source']})\n" for r in out))
    try:
        current = paths.LEARNED.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current == body:
        return
    paths.write_text(paths.LEARNED, body)
    paths.hand_to_brain(paths.LEARNED)
    if not commit:
        return
    try:
        gitrepo.commit("Learned: revised what Morph knows about this household", "learning")
    except Exception:  # noqa: BLE001 — a lesson is still on disk without its commit
        log.warning("could not commit LEARNED.md")


def add_lesson(text: str, source: str = "tell") -> None:
    body, _ = split_lesson(text)
    if not body:
        return
    write_lessons(read_lesson_rows() + [{"text": body, "source": source if source in SOURCES else "tell"}])


def _norm(text: str) -> str:
    return " ".join(_WORD.findall(str(text or "").lower()))


def _evidenced(evidence, notes) -> bool:
    """Whether a NEW lesson has what it needs: two separate pieces of
    evidence, or one reason a person actually typed (checked against the
    reasons in the digest, so a model cannot invent one)."""
    items = [str(e).strip() for e in (evidence or []) if str(e).strip()] if isinstance(evidence, list) else []
    if len({_norm(e) for e in items if _norm(e)}) >= 2:
        return True
    said = [_norm(n) for n in notes or [] if _norm(n)]
    for e in items:
        if e.lower().startswith("note:"):
            quoted = _norm(e[5:])
            if quoted and any(quoted in n or n in quoted for n in said):
                return True
    return False


def merge_pass_lessons(returned, notes=()) -> dict:
    """A pass's complete list of lessons, merged under three rules the
    prompt states and this enforces:

    * a (you) line is kept exactly as written, whatever the pass answered,
      and a pass line that rewords one is dropped rather than added beside
      it;
    * a line the pass returns that is already on the list keeps its source;
    * a NEW line needs evidence (`_evidenced`), or it is not written.

    Answers what was dropped, for the pass's note."""
    current = read_lesson_rows()
    known = {_key(r["text"]): r for r in current}
    yours = [r for r in current if r["source"] == "you"]
    your_words = [_words(r["text"]) for r in yours]
    keep = {_key(r["text"]) for r in yours}
    new: list[dict] = []
    unsupported = 0
    for item in returned or []:
        if isinstance(item, dict):
            text, evidence = item.get("text"), item.get("evidence")
        else:
            text, evidence = item, None
        body, _ = split_lesson(str(text or ""))
        k = _key(body)
        if not body or k in keep:
            continue
        if any(_similar(_words(body), w) for w in your_words):
            continue  # a rewording of a household line: theirs stands as written
        if k in known:
            keep.add(k)
            continue
        if not _evidenced(evidence, notes):
            unsupported += 1
            continue
        keep.add(k)
        new.append({"text": body[:300], "source": "learned"})
    rows = [r for r in current if _key(r["text"]) in keep] + new
    write_lessons(rows)
    return {"added": len(new), "unsupported": unsupported}


# --------------------------------------------------------------- the digest

def _bucket(hour: int) -> str:
    return ("night" if hour < 6 else "morning" if hour < 12 else
            "afternoon" if hour < 18 else "evening" if hour < 23 else "night")


def digest(dash: dict, now: float | None = None, states: dict | None = None) -> dict:
    now = now or time.time()
    rows = usage(now - WINDOW_S)
    by_card = collections.Counter()
    by_entity = collections.Counter()
    by_section = collections.Counter()
    when = collections.defaultdict(collections.Counter)
    kinds = collections.Counter()
    days = set()
    for r in rows:
        card, sec = r.get("card") or "", r.get("section") or ""
        if card:
            by_card[card] += 1
        elif str(r.get("detail") or "").count(".") == 1:
            # A press the panel could not tie to a card (a button, a light
            # group's member, from before it learned to) still names the
            # entity it acted on: it counts toward the card showing that.
            by_entity[str(r["detail"])] += 1
        if sec:
            by_section[sec] += 1
            try:
                when[sec][_bucket(int(r.get("hour") or 0))] += 1
            except (TypeError, ValueError):
                pass  # a row with no readable hour still counts as a use, just not by time of day
        kinds[r.get("kind") or "?"] += 1
        days.add(time.strftime("%Y-%m-%d", time.localtime(float(r.get("ts") or 0))))
    cards, order = [], []
    for fl in dash.get("floors") or []:
        for i, sec in enumerate(fl.get("sections") or []):
            order.append({"floor": fl["title"], "section": sec["id"], "title": sec["title"],
                          "position": i + 1, "uses": by_section.get(sec["id"], 0),
                          "when": dict(when.get(sec["id"]) or {})})
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    ent = c.get("entity") or ""
                    st = (states or {}).get(ent) if ent else None
                    cards.append({"id": c["id"], "section": sec["id"], "type": c["type"],
                                  "entity": ent,
                                  "uses": by_card.get(c["id"], 0) + (by_entity.get(ent, 0) if ent else 0),
                                  "unavailable": bool(st and st.get("state") in ("unavailable", "unknown"))})
    out = outcomes(now - WINDOW_S)
    tells = [o for o in out if o.get("kind") == "tell"]
    undone = {o.get("id") for o in out if o.get("kind") == "undo"}
    import gitrepo
    for t in tells:
        if t.get("commit") and t["id"] not in undone and gitrepo.is_reverted(t["commit"]):
            undone.add(t["id"])
    shown = []
    for t in tells[-30:]:
        row = {"asked": t.get("text"), "phase": t.get("phase"), "undone": t.get("id") in undone}
        if row["undone"] and t.get("commit"):
            # What was rejected, read off the commit: "undone" alone says a
            # person did not keep something, not what it was.
            row["rejected"] = rejected_change(t.get("base") or "", t["commit"])
        shown.append(row)
    sugg = [o for o in out if o.get("kind") == "suggestion"]
    log = usage_log(now - WINDOW_S)
    log["sentence"] = LOG_SENTENCES[log["state"]]
    return {
        "days_with_use": len(days), "events": len(rows), "by_kind": dict(kinds), "log": log,
        "sections": order, "cards": cards,
        "never_used": [c["id"] for c in cards if not c["uses"]] if len(days) >= 7 and log["state"] == "ok" else [],
        "dead": [c["id"] for c in cards if c["unavailable"]],
        "tells": shown,
        "suggestions": [{"title": o.get("title"), "verb": o.get("verb"), "note": o.get("note", "")}
                        for o in sugg][-30:],
        # Totals and the newest stamp, for the fingerprint: the lists above
        # are capped at 30, so their lengths stop moving once a house has
        # been answering for a while.
        "outcomes_total": len(out),
        "last_outcome_at": max((float(o.get("at") or 0) for o in out), default=0.0),
    }


def rejected_change(base: str, commit: str) -> list[str]:
    """What an undone Tell changed on the dashboard, in a person's words."""
    import dashdiff
    import gitrepo
    try:
        new_text = gitrepo.file_at(commit, "dashboard.yaml")
        if new_text is None:
            return []
        old_text = gitrepo.file_at(base, "dashboard.yaml") if base else None
        old = store.load_text(old_text)[0] if old_text is not None else store.empty()
        return dashdiff.describe_change(old, store.load_text(new_text)[0])[:4]
    except Exception:  # noqa: BLE001 — evidence is best-effort; a pass runs without it
        return []


def fingerprint(d: dict) -> str:
    """What has to change for a pass to be worth running."""
    # Uses are counted in steps: the log grows with every tap, and a pass keyed
    # on the exact count ran every interval for any house that is lived in,
    # re-asking a question the last twenty-four hours had barely changed.
    # Answers are counted by their total and newest stamp, never by the
    # length of a list capped at 30 (which stops moving at 30).
    total = d.get("outcomes_total", len(d.get("tells") or []) + len(d.get("suggestions") or []))
    last = d.get("last_outcome_at", 0)
    dead = ",".join(sorted(d.get("dead") or []))
    return _key(f"{d['events'] // EVENT_STEP}|{total}|{last}|{dead}")


AGENTS_SECTIONS = ("## The design rules", "### Card types Morph draws itself")


def design_rules() -> list[str]:
    """AGENTS.md's design rules and its card-type table, handed to the pass
    as text: a read-only task has no file access (brAIn denies Read for
    that scope), so telling it to "read AGENTS.md" asked for something it
    could never do — and a pass that does not know which card types exist
    suggests cards Morph cannot draw."""
    try:
        text = paths.AGENTS.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for heading in AGENTS_SECTIONS:
        start = text.find(heading)
        if start < 0:
            continue
        level = heading.split(" ", 1)[0]
        ends = [i for i in (text.find("\n## ", start + 5), text.find(f"\n{level} ", start + 5)) if i > 0]
        body = text[start:min(ends) if ends else None].strip()
        out += [body, ""]
    return out


def _compact(obj) -> str:
    import json
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def fit(items: list, limit: int, noun: str, newest: bool = False) -> str:
    """``items`` as compact JSON, as many WHOLE items as fit in ``limit``,
    then a line saying how many were left out. Slicing the serialised text
    cut an item mid-token, which reads as broken JSON rather than as "there
    is more"; ``newest`` keeps the end of the list rather than the start."""
    order = list(reversed(items)) if newest else list(items)
    kept, size = [], 2
    for it in order:
        s = _compact(it)
        if size + len(s) + 1 > limit:
            break
        kept.append(it)
        size += len(s) + 1
    if newest:
        kept.reverse()
    cut = len(items) - len(kept)
    return _compact(kept) + (f"\n({cut} more {noun} not shown{', the oldest' if newest else ''}.)" if cut else "")


def build_prompt(d: dict, dash_text: str, lessons, declined: dict,
                 items: list[dict] | None = None) -> str:
    import json
    # The dashboard below already lists every card; repeating the ones nobody
    # touched (and that are not broken) is tokens spent saying nothing.
    used = [c for c in d["cards"] if c["uses"] or c["unavailable"]]
    pending = [it["title"] for it in items or [] if it.get("status") in ("open", "doing")]
    finished = [it["title"] for it in items or [] if it.get("status") in ("done", "sent")]
    marked = [f"- {r['text']} ({r['source']})" if isinstance(r, dict) else f"- {r}" for r in lessons or []]
    lines = [
        "MORPH · learning pass. Morph is this house's dashboard. You are improving the DASHBOARD —",
        "its layout, its cards, what is on it and where — from how the household actually uses it.",
        "Learning about the house itself is brAIn's job elsewhere; do not suggest automations,",
        "helpers, renames or other changes to Home Assistant here.",
        "You may LOOK at the house with your read-only Home Assistant tools (this run has no file",
        "access; everything you need from Morph's files is below). You must NOT change anything —",
        "every suggestion waits for a person to press Do it, and then it is handed back to you as",
        "an ordinary request.",
        "",
        *design_rules(),
        "Usage over the last 30 days (counts only):",
        json.dumps({k: d[k] for k in ("days_with_use", "events", "by_kind")}),
        *([(d.get("log") or {}).get("sentence")] if (d.get("log") or {}).get("sentence") else []),
        *(["Do not suggest moving, hiding or removing anything because of how little it was used."]
          if (d.get("log") or {}).get("state") in ("never", "unreadable") else []),
        "",
        "Sections in dashboard order, with how often each was used and when:",
        fit(d["sections"], 6000, "sections"),
        "",
        "Cards that were used or are unavailable (id, section, type, entity, uses, unavailable);",
        "every other card is in the dashboard below:",
        fit(used, 8000, "cards"),
        "",
        f"Cards nobody has touched in a month: {d['never_used'][:40]}"
        + (f" (and {len(d['never_used']) - 40} more)" if len(d["never_used"]) > 40 else ""),
        f"Cards whose entity is unavailable: {d['dead'][:40]}"
        + (f" (and {len(d['dead']) - 40} more)" if len(d["dead"]) > 40 else ""),
        "",
        "Changes people asked brAIn for, whether they were then UNDONE, and for an undone one what",
        "it had changed on the dashboard (`rejected`):",
        fit(d["tells"], 4000, "changes", newest=True),
        "",
        "How earlier suggestions were answered (do / not_now / no, with the reason when one was typed):",
        fit(d["suggestions"], 4000, "answers", newest=True),
        "",
        "Never suggest these again — they were declined:",
        json.dumps([v.get("title") for v in declined.values()][-60:], ensure_ascii=False),
        "",
        "Already waiting for an answer, or snoozed (do not suggest them again, reworded or not):",
        json.dumps(pending[-30:], ensure_ascii=False),
        "Already done or sent (the dashboard reflects them; suggest only what is still missing):",
        json.dumps(finished[-30:], ensure_ascii=False),
        "",
        "Lessons so far (LEARNED.md). Each ends with who wrote it: (you) the household, (tell) brAIn",
        "during a Tell, (learned) an earlier pass. A (you) line is kept exactly as written whatever",
        "you answer: return it unchanged or leave it out, and never reword it.",
        *marked,
        "",
        "The dashboard as it is now:",
        "```yaml", store.clip_lines(dash_text, 16000, "this run cannot read the rest."), "```",
        "",
        f"Answer with at most {MAX_SUGGESTIONS} dashboard suggestions, each backed by the evidence",
        "above (a section used every evening placed below ones nobody opens; a card that has been",
        "unavailable for weeks; something the household keeps asking for by hand that could be one",
        "tap on the dashboard). Fewer is better than weak; none is a fine answer. `change` is the",
        "exact instruction you would want to be handed.",
        "",
        "Then revise the COMPLETE list of lessons: keep what still holds and drop what the evidence",
        "contradicts. A NEW lesson needs evidence — at least two separate things above that point to",
        "it (two undone changes, an undo and a decline) or one reason a person typed — listed in its",
        "`evidence`, a person's reason quoted as `note: <their words>`. A lesson without that is not",
        "written. A reason given for a decline is evidence; it is a lesson only if it states a rule",
        "about the dashboard. Lessons are rules about how THIS household wants its dashboard to look",
        "and behave; a fact about the house (what a device is, who uses a room) is not a lesson.",
        "",
        "Put a problem that needs Morph's own code changed (not this dashboard) in code_reports, with",
        "its evidence in `why`; the household can have brAIn make it on this house's copy of Morph,",
        "or send it as an issue, so say plainly what should change.",
    ]
    return "\n".join(lines)


def state() -> dict:
    return paths.read_json(paths.LEARN_STATE, {}) or {}


def _set_state(**kw) -> None:
    st = state()
    st.update(kw)
    paths.write_json(paths.LEARN_STATE, st)


def due(now: float | None = None) -> bool:
    now = now or time.time()
    s = settings.load()
    if not s["learning"]:
        return False
    return now - float(state().get("last_pass") or 0) >= s["learning_hours"] * 3600


async def run_pass(states: dict | None = None, *, pressed: bool = False) -> dict:
    """One learning pass. Never raises; answers what happened."""
    import asyncio

    import devloop
    if not brain.available():
        _set_state(last_note=brain.status()["sentence"])
        return {"skipped": "brain"}
    dash, _, text = store.read()
    d = digest(dash, states=states)
    fp = fingerprint(d)
    st = state()
    if not pressed and fp == st.get("fingerprint"):
        _set_state(last_pass=time.time(), last_note="Nothing new to learn from since the last pass.")
        return {"skipped": "unchanged"}
    data = _load()
    prompt = build_prompt(d, text, read_lesson_rows(), data["declined"], data["items"])
    tid = brain.new_id("morph-learn")
    # The fingerprint is recorded only by a pass that answered: one written
    # here would let a pass that failed (brAIn stopped, signed out, slow)
    # mark the evidence as read, and every later pass would skip it as
    # "nothing new" until somebody happened to use the dashboard again.
    _set_state(running=tid, last_pass=time.time())
    try:
        await asyncio.to_thread(brain.submit, tid, prompt, schema=SCHEMA, tools="read_only",
                                timeout=PASS_TIMEOUT_S, model=settings.load().get("learn_model") or "",
                                scheduled=not pressed)
        deadline = time.time() + brain.CLAIM_GRACE_S
        while not brain.claimed(tid):
            if time.time() > deadline:
                brain.withdraw(tid)
                _set_state(running="", last_note="Nothing picked the pass up; brAIn's Automation "
                           "integration has to be on.")
                return {"skipped": "unclaimed"}
            await asyncio.sleep(1)
        deadline = time.time() + PASS_TIMEOUT_S + 120
        res = None
        while res is None and time.time() < deadline:
            res = await asyncio.to_thread(brain.result, tid)
            if res is None:
                await asyncio.sleep(2)
        if res is None:
            _set_state(running="", last_note="brAIn did not answer the learning pass in time.")
            return {"error": "timeout"}
        obj, rtext, err = brain.answer_data(res)
        if err or not isinstance(obj, dict):
            note = rtext[:300] if err else "brAIn's answer could not be read."
            _set_state(running="", last_note=note)
            # A run that failed (signed out, paused, out of time) is brAIn's
            # weather; only an answer that came back unreadable is the two
            # halves' contract failing, which is Morph's to fix.
            if not err:
                devloop.note_fault("Learning", "brAIn's answer to a learning pass could not be read",
                                   rtext[:800])
            return {"error": err or "unreadable"}
        rows = [r for r in (obj.get("suggestions") or []) if isinstance(r, dict)]
        rows = [{**r, "kind": "dashboard"} for r in rows]
        added = add_suggestions(rows + code_suggestions(obj.get("code_reports")), dash)
        merged = {"unsupported": 0}
        if isinstance(obj.get("lessons"), list) and obj["lessons"]:
            notes = [s.get("note") for s in d["suggestions"] if s.get("note")]
            merged = merge_pass_lessons(obj["lessons"], notes)
        note = f"Learned from {d['events']} uses; {added} new suggestion{'s' if added != 1 else ''}."
        if merged["unsupported"]:
            note += (f" {merged['unsupported']} new lesson{'s' if merged['unsupported'] != 1 else ''} "
                     "without enough evidence left out.")
        _set_state(running="", fingerprint=fp, last_note=note, last_added=added)
        return {"added": added}
    except Exception as exc:  # noqa: BLE001
        log.exception("learning pass failed")
        _set_state(running="", last_note=f"The learning pass failed: {exc}")
        return {"error": str(exc)}


def scorecard(now: float | None = None) -> dict:
    """Is the loop getting better or only louder? Counts, no judgement."""
    import gitrepo
    now = now or time.time()
    out = outcomes(now - 90 * 86400)
    items = _load()["items"]
    tells = [o for o in out if o.get("kind") == "tell" and o.get("phase") == "done" and o.get("commit")]
    undone = sum(1 for t in tells if gitrepo.is_reverted(t["commit"]))
    return {
        "suggested": len(items),
        "done": sum(1 for it in items if it.get("status") == "done"),
        "declined": sum(1 for it in items if it.get("status") == "declined"),
        "sent": sum(1 for it in items if it.get("status") == "sent"),
        "open": sum(1 for it in items if it.get("status") == "open"),
        "tells": len(tells),
        "tells_kept": len(tells) - undone,
        "tells_undone": undone,
        "lessons": len(read_lessons()),
    }
