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
import logging
import re
import time

import brain
import paths
import settings
import store

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
            "type": "object", "required": ["title", "why", "change"],
            "properties": {
                "title": {"type": "string", "description": "Under 60 characters, said as the change."},
                "why": {"type": "string", "description": "One sentence of evidence from the digest."},
                "change": {"type": "string",
                           "description": "The instruction Morph will hand you if they press Do it."},
                "kind": {"type": "string", "enum": ["dashboard", "house"]},
                "section": {"type": "string", "description": "Section id it belongs in, if any."},
                "card": {"type": "string", "description": "Card id it is about, if any."},
            }}},
        "lessons": {"type": "array", "maxItems": MAX_LESSONS, "items": {"type": "string"},
                    "description": "The COMPLETE revised list of lessons, not only new ones."},
        "code_reports": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "required": ["what", "detail"],
            "properties": {"what": {"type": "string"}, "detail": {"type": "string"}}},
            "description": "Problems that need a change to Morph's own code, not to this dashboard."},
    },
}

_WS = re.compile(r"\s+")


def _key(text: str) -> str:
    return hashlib.sha1(_WS.sub(" ", str(text or "").lower()).strip().encode()).hexdigest()[:12]


# ------------------------------------------------------------------ the log

USAGE_KINDS = ("open", "toggle", "slide", "scene", "history", "tell", "undo", "ask", "edit")


def usage(since: float = 0.0) -> list[dict]:
    rows = paths.read_jsonl(paths.USAGE, limit=50000)
    return [r for r in rows if float(r.get("ts") or 0) >= since]


def prune_usage(max_age_s: int = 60 * 86400) -> None:
    rows = usage(time.time() - max_age_s)
    try:
        paths.write_text(paths.USAGE, "".join(
            __import__("json").dumps(r, ensure_ascii=False) + "\n" for r in rows))
    except OSError:
        pass  # pruning is housekeeping; the log is read with a time window either way


def record_outcome(row: dict) -> None:
    try:
        paths.append_jsonl(paths.OUTCOMES, row)
    except OSError:
        pass  # an outcome is evidence for learning, never worth failing the action it records


def outcomes(since: float = 0.0) -> list[dict]:
    return [r for r in paths.read_jsonl(paths.OUTCOMES) if float(r.get("at") or 0) >= since]


# ------------------------------------------------------------- suggestions

def _load() -> dict:
    data = paths.read_json(paths.SUGGESTIONS, {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    data.setdefault("declined", {})
    return data


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
    added = 0
    for row in rows or []:
        if not isinstance(row, dict) or open_now >= MAX_OPEN:
            continue
        title = str(row.get("title") or "").strip()[:80]
        change = str(row.get("change") or "").strip()[:1200]
        if not title or not change:
            continue
        key = _key(title)
        if key in known:
            continue
        known.add(key)
        item = {"id": f"g{int(time.time() * 1000)}{added}", "key": key, "title": title,
                "why": str(row.get("why") or "").strip()[:400], "change": change,
                "kind": row.get("kind") if row.get("kind") in ("dashboard", "house") else "dashboard",
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


def decide(sid: str, verb: str, note: str = "") -> dict:
    """Not now / No. Do it is `tell.start` with the suggestion's change, and
    calls `mark_doing` once it has an id."""
    data = _load()
    item = next((it for it in data["items"] if it.get("id") == sid), None)
    if not item:
        return {"ok": False, "error": "That suggestion is gone."}
    note = str(note or "").strip()[:400]
    if verb == "not_now":
        item["snoozed_until"] = time.time() + SNOOZE_S
    elif verb == "no":
        item["status"] = "declined"
        item["note"] = note
        item["decided"] = time.time()
        data["declined"][item["key"]] = {"title": item["title"], "note": note, "at": time.time()}
        if note:
            add_lesson(f"Declined “{item['title']}”: {note}", "a suggestion was turned down")
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
            changed = True
    if changed:
        _save(data)


# ----------------------------------------------------------------- lessons

def read_lessons() -> list[str]:
    try:
        text = paths.LEARNED.read_text(encoding="utf-8")
    except OSError:
        return []
    return [ln[2:].strip() for ln in text.splitlines() if ln.startswith("- ")]


def write_lessons(lessons: list[str], commit: bool = True) -> None:
    import gitrepo
    lessons = [str(x).strip().replace("\n", " ")[:300] for x in lessons if str(x).strip()]
    seen, out = set(), []
    for ln in lessons:
        k = _key(ln)
        if k not in seen:
            seen.add(k)
            out.append(ln)
    out = out[-MAX_LESSONS:]
    body = ("# What this household has taught Morph\n\n"
            "Rewritten by Morph's learning loop from what was done, declined and undone.\n"
            "Every Tell and every learning pass reads this. Edit it freely — it is yours.\n\n"
            + "".join(f"- {ln}\n" for ln in out))
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


def add_lesson(text: str, why: str = "") -> None:
    lessons = read_lessons()
    line = text.strip() + (f" ({why})" if why else "")
    write_lessons(lessons + [line])


# --------------------------------------------------------------- the digest

def _bucket(hour: int) -> str:
    return ("night" if hour < 6 else "morning" if hour < 12 else
            "afternoon" if hour < 18 else "evening" if hour < 23 else "night")


def digest(dash: dict, now: float | None = None, states: dict | None = None) -> dict:
    now = now or time.time()
    rows = usage(now - WINDOW_S)
    by_card = collections.Counter()
    by_section = collections.Counter()
    when = collections.defaultdict(collections.Counter)
    kinds = collections.Counter()
    days = set()
    for r in rows:
        card, sec = r.get("card") or "", r.get("section") or ""
        if card:
            by_card[card] += 1
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
                                  "entity": ent, "uses": by_card.get(c["id"], 0),
                                  "unavailable": bool(st and st.get("state") in ("unavailable", "unknown"))})
    out = outcomes(now - WINDOW_S)
    tells = [o for o in out if o.get("kind") == "tell"]
    undone = {o.get("id") for o in out if o.get("kind") == "undo"}
    import gitrepo
    for t in tells:
        if t.get("commit") and t["id"] not in undone and gitrepo.is_reverted(t["commit"]):
            undone.add(t["id"])
    return {
        "days_with_use": len(days), "events": len(rows), "by_kind": dict(kinds),
        "sections": order, "cards": cards,
        "never_used": [c["id"] for c in cards if not c["uses"]] if len(days) >= 7 else [],
        "dead": [c["id"] for c in cards if c["unavailable"]],
        "tells": [{"asked": t.get("text"), "phase": t.get("phase"),
                   "undone": t.get("id") in undone} for t in tells[-30:]],
        "suggestions": [{"title": o.get("title"), "verb": o.get("verb"), "note": o.get("note", "")}
                        for o in out if o.get("kind") == "suggestion"][-30:],
    }


def fingerprint(d: dict) -> str:
    """What has to change for a pass to be worth running."""
    return _key(f"{d['events']}|{len(d['tells'])}|{len(d['suggestions'])}|{len(d['dead'])}")


def build_prompt(d: dict, dash_text: str, lessons: list[str], declined: dict) -> str:
    import json
    lines = [
        "MORPH · learning pass. Morph is this house's dashboard (/config/morph; read AGENTS.md).",
        "You are improving it from how the household actually uses it. You may LOOK at the house",
        "with your read-only tools; you must NOT change anything — every suggestion waits for a",
        "person to press Do it, and then it is handed back to you as an ordinary request.",
        "",
        "Usage over the last 30 days (counts only):",
        json.dumps({k: d[k] for k in ("days_with_use", "events", "by_kind")}),
        "",
        "Sections in dashboard order, with how often each was used and when:",
        json.dumps(d["sections"])[:6000],
        "",
        "Cards (id, section, type, entity, uses, unavailable):",
        json.dumps(d["cards"])[:8000],
        "",
        f"Cards nobody has touched in a month: {d['never_used'][:40]}",
        f"Cards whose entity is unavailable: {d['dead'][:40]}",
        "",
        "Changes people asked brAIn for, and whether they were then UNDONE:",
        json.dumps(d["tells"])[:4000],
        "",
        "How earlier suggestions were answered (do / not_now / no, with the reason when given):",
        json.dumps(d["suggestions"])[:4000],
        "",
        "Never suggest these again — they were declined:",
        json.dumps([v.get("title") for v in declined.values()][-60:]),
        "",
        "Lessons so far (from LEARNED.md):",
        *(f"- {ln}" for ln in lessons),
        "",
        "The dashboard as it is now:",
        "```yaml", dash_text[:16000], "```",
        "",
        f"Answer with at most {MAX_SUGGESTIONS} suggestions, each backed by the evidence above",
        "(a section used every evening placed below ones nobody opens; a card that has been",
        "unavailable for weeks; something the household keeps asking brAIn to do by hand that",
        "could be one tap). Fewer is better than weak; none is a fine answer. `change` is the",
        "exact instruction you would want to be handed. Then revise the COMPLETE list of lessons:",
        "keep what still holds, drop what the evidence contradicts, add what the undone changes",
        "and declined suggestions teach. Lessons are about how THIS household wants its dashboard,",
        "written as rules. Put a problem that needs Morph's own code changed (not this",
        "dashboard) in code_reports.",
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
    prompt = build_prompt(d, text, read_lessons(), data["declined"])
    tid = brain.new_id("morph-learn")
    _set_state(running=tid, last_pass=time.time(), fingerprint=fp)
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
            devloop.note_fault("Learning", "A learning pass failed", note)
            return {"error": err or "unreadable"}
        added = add_suggestions(obj.get("suggestions") or [], dash)
        if isinstance(obj.get("lessons"), list) and obj["lessons"]:
            write_lessons(obj["lessons"])
        for rep in (obj.get("code_reports") or [])[:5]:
            if isinstance(rep, dict) and rep.get("what"):
                devloop.note_fault("Learning", str(rep["what"])[:140], str(rep.get("detail") or "")[:1500],
                                   source="learning")
        _set_state(running="", last_note=f"Learned from {d['events']} uses; "
                   f"{added} new suggestion{'s' if added != 1 else ''}.", last_added=added)
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
        "open": sum(1 for it in items if it.get("status") == "open"),
        "tells": len(tells),
        "tells_kept": len(tells) - undone,
        "tells_undone": undone,
        "lessons": len(read_lessons()),
    }
