"""brAIn's half of the wire to Morph, the dashboard (Morph 1.0 / brAIn 3.0;
part of brAIn since 4.0).

brAIn is the house's mind and Morph is its face (docs/design/morph-vision.md
§13). Morph's page runs in Home Assistant's own frontend and its service is
a process of its own (in brAIn's container since 4.0), and brAIn's panel
port stays unpublished, so everything between them is a file on the shared
volume, under ``/config/.brain/morph/``:

* ``feed.json`` — brAIn's measurements (what is normal for each sensor at
  this hour of the week, how often each door is open now, the house's
  rhythm, the person-caused habits, who lives here), for Morph's salience
  engine. Built here, pure over the stores the panel already keeps.
* ``cases.json`` — the one list of things waiting on a person, drawn by
  Morph: every case `cases.py` reads, with its To Do sentence, its
  conversation and the presses Morph can carry back, plus To Do itself and
  how Morph's own suggestions ended (``ended_morph``).
* ``timed.json`` — the timed actions waiting or running
  (`timed_actions.morph_payload`): what each does and when, and the request
  that stops one (kind ``timed`` on the request queue).
* ``asks/<id>.json`` in and ``answers/<id>.json`` out — Morph's Ask line,
  read by the interpreter on the ``morph`` surface.

Answers on a case and Morph's own suggestions ride the request queue every
other surface already writes to (`finding_requests`, kinds ``morph`` and
``morph_case``), so the ORDER between an answer given in Morph and one given
on a phone in the same burst is the queue's, as it is for every other kind.

Every writer here never raises and is skipped on a dev checkout — the
findings mirror's rule: when ``/config`` (the morph folder's grandparent)
does not exist, nothing is written, because a stray ``/config`` on somebody's
laptop is worse than a file nobody reads.

Stdlib only, and it imports no store: the panel hands every input in, so a
test drives each builder with plain dicts.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path

import atomic_write
import textclip

log = logging.getLogger("brain.morph")

MORPH_DIR = Path(os.environ.get("BRAIN_MORPH_DIR", "/config/.brain/morph"))
# How Morph's own suggestions ended, kept across a restart because Morph may
# have been off when the answer was given. In /data: it is the panel's.
ENDED_FILE = Path(os.environ.get("BRAIN_MORPH_ENDED_FILE",
                                 "/data/morph-ended.json"))
# The conversation on a case that has no findings row to carry it (a guess,
# a suggestion, a chore). A finding's thread is on its own row.
THREADS_FILE = Path(os.environ.get("BRAIN_MORPH_THREADS_FILE",
                                   "/data/morph-threads.json"))

FEED_VERSION = 1
CASES_VERSION = 1
# Morph treats the feed as stale past this, by the file's mtime. Two hours:
# it is rewritten at the top of every hour, so one missed hour is not stale
# and two are.
FEED_STALE_S = 7200
MAX_NORMAL = 400
MAX_DOORS = 200
MAX_HABITS = 200
MAX_PEOPLE = 40
MAX_ENDED = 50
MAX_THREAD_CASES = 100
HOURS_PER_WEEK = 168

# Morph's Ask line. A request older than this is nobody's question any more
# (Morph has given up and used its own behaviour), so it is dropped
# unanswered; an answer older than `ANSWER_KEEP_S` that Morph never read is
# swept so the folder cannot grow.
ASK_MAX_AGE_S = 60
ASK_MAX_BYTES = 16 * 1024
ASK_TEXT_MAX = 1000
ANSWER_KEEP_S = 3600
MAX_ASKS_PER_PASS = 8
ASK_ID_RE = re.compile(r"^a-[0-9a-fA-F]{4,64}$")
ASK_DO = ("done", "conversation", "tell_dashboard", "tell_code", "fallback")
# `kept`: a suggestion to remove a card about something that was out of use
# for now, ended because it reports again — the card stays.
ENDED_HOWS = ("accepted", "declined", "dismissed", "todo", "kept")


def writable() -> bool:
    """Whether this is an install with a shared volume to write to."""
    return MORPH_DIR.parent.parent.is_dir()


def _write(name: str, payload: dict) -> bool:
    if not writable():
        return False
    try:
        MORPH_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(MORPH_DIR / name, payload, mode=0o644)
        return True
    except Exception as exc:  # noqa: BLE001 — a mirror, never the panel
        log.warning("could not write %s for Morph: %s", name, exc)
        return False


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


# ---------------------------------------------------------------------------
# A. feed.json
# ---------------------------------------------------------------------------

def bucket_info(now: float, tz) -> dict:
    """The hour-of-week bucket now and next, in the house's zone, and when
    "now" ends. Monday 00:00 local is 0, `baselines.hour_of_week`'s rule."""
    local = dt.datetime.fromtimestamp(now, tz)
    current = local.weekday() * 24 + local.hour
    top = local.replace(minute=0, second=0, microsecond=0)
    until = int((top + dt.timedelta(hours=1)).timestamp())
    return {"now": current, "next": (current + 1) % HOURS_PER_WEEK,
            "until": until}


def _bucket_row(entry: dict, bucket: int):
    row = ((entry or {}).get("buckets") or {}).get(str(bucket))
    if not isinstance(row, dict):
        return None
    try:
        return [float(row["median"]), float(row["spread"]), int(row["n"])]
    except (KeyError, TypeError, ValueError):
        return None


def normal_rows(store: dict, bucket: dict) -> dict:
    """Per sensor, `[median, spread, samples]` for this hour and the next.

    Only a sensor with a real bucket for THIS hour is listed — never the
    whole-history fallback and never a guessed number, because Morph turns
    the spread into a deviation and a band nobody measured is a deviation
    nobody can trust. `next` is null where that hour has none.
    """
    out: dict = {}
    entities = (store or {}).get("entities") or {}
    for eid in sorted(entities):
        entry = entities[eid]
        if not isinstance(entry, dict) or entry.get("flat"):
            continue
        now_row = _bucket_row(entry, bucket["now"])
        if now_row is None:
            continue
        row = {"now": now_row, "next": _bucket_row(entry, bucket["next"])}
        if entry.get("unit"):
            row["unit"] = str(entry["unit"])[:16]
        out[eid] = row
        if len(out) >= MAX_NORMAL:
            break
    return out


def door_rows(store: dict, bucket: dict, usual_open) -> dict:
    """Per closure, the share of this hour (and the next) it is usually
    OPEN. `usual_open` is `closures.usual_open`; an hour it has not
    watched is absent rather than 0, which would read as "never open"."""
    out: dict = {}
    entities = (store or {}).get("entities") or {}
    for eid in sorted(entities):
        entry = entities[eid]
        if not isinstance(entry, dict):
            continue
        now_share = usual_open(entry, bucket["now"])
        if now_share is None:
            continue
        nxt = usual_open(entry, bucket["next"])
        out[eid] = {"now": round(float(now_share), 3),
                    "next": None if nxt is None else round(float(nxt), 3)}
        if len(out) >= MAX_DOORS:
            break
    return out


def rhythm_rows(profile: dict) -> dict:
    """`rhythm.profile` as minutes of the day; null where not measured."""
    def minute(shape):
        if isinstance(shape, dict) and isinstance(shape.get("minute"),
                                                  (int, float)):
            return int(round(shape["minute"]))
        return None

    out = {}
    for half in ("weekday", "weekend"):
        part = (profile or {}).get(half) or {}
        out[half] = {"wake": minute(part.get("wakes")),
                     "settle": minute(part.get("settles"))}
    return out


def habit_rows(routines: list) -> list:
    """The person-caused habits (`routines.mine`), in Morph's words.

    `person` is null: the routine ledger records that a PERSON did it, not
    which one, and naming a member of the household it did not record would
    be the one wrong answer.
    """
    out = []
    for r in routines or []:
        if not isinstance(r, dict) or not r.get("entity_id"):
            continue
        try:
            out.append({
                "entity_id": str(r["entity_id"]),
                "state": str(r.get("state") or ""),
                "minute": int(round(float(r.get("minute") or 0))),
                "spread": round(float(r.get("spread_min") or 0), 1),
                "days": str(r.get("when_days") or ""),
                "share": round(float(r.get("share") or 0), 3),
                "days_seen": int(r.get("days") or 0),
                "person": None,
            })
        except (TypeError, ValueError):
            continue
        if len(out) >= MAX_HABITS:
            break
    return out


def people_rows(states) -> dict:
    """`person.*` with its name and Home Assistant user, off one /states."""
    out: dict = {}
    for st in states or []:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        if not eid.startswith("person."):
            continue
        attrs = st.get("attributes") or {}
        out[eid] = {"name": str(attrs.get("friendly_name") or eid)[:80],
                    "user_id": str(attrs.get("user_id") or "")[:64] or None}
        if len(out) >= MAX_PEOPLE:
            break
    return out


def build_feed(*, now: float, tz, tz_name: str, baselines_store=None,
               closures_store=None, usual_open=None, rhythm_profile=None,
               routines=None, states=None, appliances=None) -> dict:
    """The feed, out of whatever the panel could read.

    A store that could not be read is handed in as None and its key is
    ABSENT — "brAIn could not look" — never an empty one written as if it
    had measured nothing.
    """
    feed: dict = {"v": FEED_VERSION, "at": int(now),
                  "stale_after_s": FEED_STALE_S, "tz": tz_name,
                  "bucket": bucket_info(now, tz)}
    if rhythm_profile is not None:
        feed["rhythm"] = rhythm_rows(rhythm_profile)
    if baselines_store is not None:
        feed["normal"] = normal_rows(baselines_store, feed["bucket"])
    if closures_store is not None and usual_open is not None:
        feed["doors"] = door_rows(closures_store, feed["bucket"], usual_open)
    if routines is not None:
        feed["habits"] = habit_rows(routines)
    if states is not None:
        feed["people"] = people_rows(states)
    if appliances is not None:
        feed["appliances"] = appliances
    return feed


def publish_feed(feed: dict) -> bool:
    return _write("feed.json", feed)


# ---------------------------------------------------------------------------
# B. cases.json
# ---------------------------------------------------------------------------

# What Morph can press, by the verb `answers.answers` gave the case, and the
# words Morph's request may carry back (`finding_requests.MORPH_ACTIONS`).
# Yes, No, Done and the rest are a reply's words, which is how Morph answers
# them (§14.2). Snooze, Check again and Ignore ride too (#452): the card in
# Morph offers the presses Needs you offers, in the same words, so a case
# reads as one surface wherever it is looked at. Ignore carries its optional
# reason as the request's `text`, which reaches `_end_finding` as the note.
_ACTION_OF_VERB = {"fix": "fix", "apply": "apply", "todo": "todo",
                   "dismiss": "dismiss", "not_now": "snooze",
                   "recheck": "recheck", "wrong": "wrong",
                   "not_applicable": "not_applicable"}


def morph_answers(case_answers: list) -> list:
    """`[{action, label}]` for the presses Morph can carry back."""
    out, seen = [], set()
    for a in case_answers or []:
        if not isinstance(a, dict):
            continue
        action = _ACTION_OF_VERB.get(str(a.get("verb") or ""))
        if action and action not in seen:
            seen.add(action)
            out.append({"action": action, "label": str(a.get("label") or "")})
    return out


def case_row(case: dict, *, todo_text: str, thread: list, ask: str,
             answers: list, area_id: str = "", urgent: bool = False,
             finding_status: str = "", morph_key: str = "",
             chip: str = "", who: dict | None = None) -> dict:
    """One case in Morph's shape (contract B). `chip` is Needs you's own
    status chip (`answers.chip`) and `who` its who-acts line, so Morph draws
    the card the panel draws; Morph derives its own where they are absent."""
    evidence = []
    for ev in case.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("entity"):
            evidence.append(str(ev["entity"]))
        elif isinstance(ev, str):
            evidence.append(ev)
    plan = case.get("plan") or {}
    row = {
        "id": str(case.get("id") or ""),
        "kind": str(case.get("kind") or "problem"),
        "claim": str(case.get("claim") or ""),
        "ask": ask,
        "detail": str(case.get("detail") or ""),
        "severity": str(case.get("severity") or "warning"),
        "stakes": str(case.get("stakes") or ""),
        "urgent": bool(urgent),
        "entity_id": str(case.get("entity_id") or ""),
        "evidence": evidence[:8],
        "area_id": area_id,
        "source": str(case.get("source") or ""),
        "source_title": str(case.get("source_title") or ""),
        "fixable": bool(case.get("fixable")),
        "status": finding_status or str(case.get("status") or "open"),
        "plan": ({"steps": [str(x) for x in plan.get("steps") or []][:10],
                  "risk": str(plan.get("risk") or "")}
                 if isinstance(plan, dict) and (plan.get("steps")
                                                or plan.get("risk")) else None),
        "todo_text": todo_text,
        "thread": list(thread or [])[-12:],
        "answers": answers,
        "created_at": int(case.get("created_at") or 0),
    }
    if morph_key:
        row["morph_key"] = morph_key
    if chip:
        row["chip"] = chip
    if who and who.get("line"):
        row["who"] = {"who": str(who.get("who") or ""),
                      "line": str(who["line"])}
    return row


ASK_MAX = 300


def ask_line(case: dict, situation: str) -> str:
    """What brAIn wants from the person on this card, one line, or "".

    Deterministic from what the card already holds: a question asks itself;
    a plan waiting asks for its Apply; a problem brAIn could fix says what
    it would do; a problem that needs hands says what to do. A change brAIn
    made, a run in flight and a row brAIn is only watching ask nothing.
    """
    kind = case.get("kind")
    fix = " ".join(str(case.get("fix") or "").split())
    if situation in ("planning", "fixing", "watching", "change", "chore_done"):
        return ""
    if kind == "question":
        claim = str(case.get("claim") or "")
        return claim if claim.endswith("?") else "Is that right?"
    if situation == "planned":
        return "Apply this change?"
    if kind == "opportunity":
        return "Should brAIn do it?"
    if kind == "chore":
        return ""
    if situation == "gap":
        return "Where is it, or what does it do?"
    # Whole sentences, never a slice that stops mid-word (#560).
    if case.get("fixable") and fix:
        return textclip.shorten(f"Fix it? {fix}", ASK_MAX)
    return textclip.shorten(fix, ASK_MAX)


def todo_rows(items: list, snoozes: dict, area_of, word=None) -> list:
    """To Do as Morph lists it: open items, each with its snooze.

    `word` turns an item into the sentence shown (`findings_store.
    todo_item_text`, which rewords a claim filed as an item into an errand);
    without it the stored text is shown."""
    out = []
    now = time.time()
    for item in items or []:
        if not isinstance(item, dict) or item.get("status") == "done":
            continue
        until = int((snoozes or {}).get(f"t:{item.get('id')}", 0) or 0)
        eid = str(item.get("entity_id") or "")
        out.append({"id": int(item.get("id") or 0),
                    "text": str((word(item) if word else "") or item.get("text") or ""),
                    "entity_id": eid,
                    "area_id": area_of(eid) if eid else "",
                    "snoozed_until": until if until > now else None,
                    "origin": str(item.get("from_case") or "")})
    return out


def publish_cases(payload: dict) -> bool:
    return _write("cases.json", payload)


def publish_timed(payload: dict) -> bool:
    """Write `timed.json`. Skipped on a dev checkout; never raises."""
    return _write("timed.json", payload)


# ---------------------------------------------------------------------------
# How Morph's own suggestions ended, and the conversation on a case with no
# findings row
# ---------------------------------------------------------------------------

def ended() -> list:
    rows = _read_json(ENDED_FILE, [])
    return [r for r in rows if isinstance(r, dict)][-MAX_ENDED:]


def note_ended(key: str, how: str, note: str = "",
               now: float | None = None) -> bool:
    """Record that a Morph suggestion ended, for `ended_morph`. Never raises."""
    if not key or how not in ENDED_HOWS:
        return False
    try:
        rows = ended()
        rows.append({"key": str(key)[:64], "how": how,
                     "note": " ".join(str(note or "").split())[:400],
                     "at": int(time.time() if now is None else now)})
        if not ENDED_FILE.parent.is_dir():
            return False              # a dev checkout: no /data to keep it in
        atomic_write.write_json(ENDED_FILE, rows[-MAX_ENDED:])
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not record how a Morph suggestion ended: %s", exc)
        return False


def threads() -> dict:
    data = _read_json(THREADS_FILE, {})
    return {k: v for k, v in data.items() if isinstance(v, list)}


def append_side_thread(case_id: str, turn: dict, clean, cap: int = 12,
                       seed: list | None = None) -> list:
    """Append a turn to a non-findings case's conversation. `clean` is
    `findings_store.clean_thread`, so both kinds of thread are one shape.
    `seed` starts a thread that has none here yet — a finding's turns, when
    the reply that ended it took the row (and its thread) with it."""
    try:
        rows = threads()
        rows[case_id] = clean(list(rows.get(case_id) or seed or [])
                              + [turn])[-cap:]
        if len(rows) > MAX_THREAD_CASES:
            for old in sorted(rows, key=lambda k: max(
                    (t.get("at") or 0) for t in rows[k]) if rows[k] else 0)[
                    :len(rows) - MAX_THREAD_CASES]:
                rows.pop(old, None)
        if not THREADS_FILE.parent.is_dir():
            return rows[case_id]      # a dev checkout: kept for this call only
        atomic_write.write_json(THREADS_FILE, rows)
        return rows[case_id]
    except Exception as exc:  # noqa: BLE001
        log.warning("could not keep the conversation on %s: %s", case_id, exc)
        return []


# ---------------------------------------------------------------------------
# D. The Ask line
# ---------------------------------------------------------------------------

def take_asks(now: float | None = None) -> list[dict]:
    """The questions waiting, validated, their files removed.

    Taken before they are answered (deleted first), so a slow answer can
    never be asked twice. Too old, too large, unreadable or misshapen is
    dropped unanswered — Morph has fallen back to its own behaviour by then.
    """
    now = time.time() if now is None else now
    folder = MORPH_DIR / "asks"
    try:
        files = sorted(p for p in folder.glob("*.json") if p.is_file())
    except OSError:
        return []
    out: list[dict] = []
    for path in files:
        try:
            size = path.stat().st_size
            mtime = path.stat().st_mtime
            raw = path.read_text(encoding="utf-8", errors="replace") \
                if size <= ASK_MAX_BYTES else ""
        except OSError:
            continue
        try:
            path.unlink()
        except OSError:
            # Not removable is not answerable twice either: skip it, and
            # the age rule drops it on a later pass.
            continue
        ask = parse_ask(raw, now, mtime)
        if ask is None:
            log.info("dropped a Morph ask that was old or unreadable: %s",
                     path.name)
            continue
        out.append(ask)
        if len(out) >= MAX_ASKS_PER_PASS:
            break
    return out


def parse_ask(raw: str, now: float, mtime: float = 0.0) -> dict | None:
    try:
        obj = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    ask_id = obj.get("id")
    text = obj.get("text")
    if not isinstance(ask_id, str) or not ASK_ID_RE.match(ask_id):
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    ts = obj.get("ts")
    stamp = float(ts) if isinstance(ts, (int, float)) and \
        not isinstance(ts, bool) else float(mtime or now)
    if now - stamp > ASK_MAX_AGE_S:
        return None
    return {"id": ask_id, "text": " ".join(text.split())[:ASK_TEXT_MAX],
            "ts": int(stamp),
            "user_id": str(obj.get("user_id") or "")[:64]}


def write_answer(answer: dict) -> bool:
    """`answers/<id>.json`, atomically. Never raises."""
    ask_id = str(answer.get("id") or "")
    if not ASK_ID_RE.match(ask_id) or answer.get("do") not in ASK_DO:
        return False
    if not writable():
        return False
    try:
        folder = MORPH_DIR / "answers"
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(folder / f"{ask_id}.json", answer, mode=0o644)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not answer Morph's ask %s: %s", ask_id, exc)
        return False


def sweep_answers(now: float | None = None) -> int:
    """Remove answers nobody read within `ANSWER_KEEP_S`."""
    now = time.time() if now is None else now
    gone = 0
    try:
        for path in (MORPH_DIR / "answers").glob("*.json"):
            try:
                if now - path.stat().st_mtime > ANSWER_KEEP_S:
                    path.unlink()
                    gone += 1
            except OSError:
                continue
    except OSError:
        return gone
    return gone


__all__ = ["ASK_DO", "ENDED_FILE", "ENDED_HOWS", "FEED_STALE_S", "MORPH_DIR",
           "THREADS_FILE", "append_side_thread", "ask_line", "bucket_info",
           "build_feed", "case_row", "ended", "morph_answers", "note_ended",
           "parse_ask", "publish_cases", "publish_feed", "sweep_answers",
           "take_asks", "threads", "todo_rows", "write_answer", "writable"]
