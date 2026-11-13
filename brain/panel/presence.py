"""The presence loop: how the assistant grows, and how it keeps in touch.

The household gave brAIn a name and a personality (`personality.py`), and
asked for it to feel present rather than like something running in the
background — to think about how it should be, and about how to be good
company to the people in the house — without ever being over the top.
This module is the arithmetic and the store for that. The server half
(`server._presence_*`) is the bus, one nightly run and delivery.

Four rules, each one code rather than a sentence in a prompt.

**Off unless both switches are on** (`active`). Personality (the name and
voice it speaks in) AND the Learning loop (brAIn changes itself, here) —
⚙ › Features, read straight off `/config/.brain/features.json` with the
same defaults Features uses, so a house that never chose a personality is
off. Off, nothing runs, nothing is asked and nothing is sent.

**A hard budget** (`may_touch`). At most `PER_PERSON_DAY` touch per
person a day and `PER_PERSON_WEEK` a week, `HOUSE_DAY` in the whole house
a day with `HOUSE_GAP_S` between any two, only between `DAY_START_H` and
`DAY_END_H` and never inside the quiet hours, never to somebody who is not
home, and never in the first `SETTLE_S` after an arrival unless it IS the
arrival greeting. A touch the budget refuses waits for its window or
expires (`IDEA_TTL_S`); it is never squeezed in.

**Reactions steer it** (`react`, `absorb`). Thanks counts for, a swipe or
"Not now" against, an unanswered day a little against. "Not now" stops
touches to that person for the rest of the day at once; "Less like this"
retires that kind for that person (⚙ › Personality brings it back); a
kind whose score falls to `RETIRE_SCORE` retires itself; and
`BACKOFF_STREAK` unwanted touches in a row pause that person for
`BACKOFF_PAUSE_S`. The nightly run reads all of it.

**Relationships, not surveillance** (`parse_reflection`). The run sees
only what the household gave brAIn — names, what they said to it in Ask
and what it answered, how they answered its messages, what they told it
about how it should be, opted-in calendars — and its answer is read
strictly: an item off the schema, about somebody not in the house, past
its length, carrying an entity id, about a sensitive attribute (health,
body, beliefs, money, relationships, identity) or judging a person is
refused, not softened. Nothing here writes the Resident's verdict log or
a fact (`outcomes._is_person_scope`'s rule). Per-person notes are three
short lines at most, shown in ⚙ and removable; every touch delivered is
kept with its one-sentence reason.

**The paragraph is its own, and held to the same reading** (`learned_
refusal`, `write_learned`). Each night the run may hand back the WHOLE of
"how I have learned to be in this house" (`personality.py`'s `learned`),
revised, or nothing. It is refused whole — and the stored one stands, with
the reason logged and shown as the night's result — when any sentence of
it touches a sensitive attribute, judges a person, carries an id, names a
voice, names the assistant instead of speaking as it, or says where a
person of the house was; when it is over length; and it is simply not a
new version when it says what the current one says.

    /data/presence.json
    {"people": {"person.x": {"ideas": [...], "notes": [...],
                             "scores": {kind: n}, "retired": {kind: at},
                             "paused_until": t, "left_at": t,
                             "arrived_at": t}},
     "touches": [{id, person, name, kind, text, reason, at, channel,
                  delivery, reaction, reacted_at}],
     "reflect": {"at": t, "ok": bool, ...},
     "tuning": {"answers": [{"question": "…", "answer": "…", "at": t}]}}

`tuning` is read here and written elsewhere: what the household answered
when asked how brAIn should be (`tuning_answers`).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

import atomic_write
import features
import personality
import prompt_kit
import textclip

log = logging.getLogger("brain.presence")

STORE = Path(os.environ.get("BRAIN_PRESENCE_FILE", "/data/presence.json"))
FEATURES_FILE = features.FILE

# The model job (`model_plan.JOBS`): a thinking tier at medium effort. It
# was the cheapest tier at low effort, shown conversation titles, and a
# personality reflected on that way did not change.
JOB = "presence"

KINDS = ("arrival", "morning", "evening", "followup", "occasion")
KIND_LABELS = {"arrival": "Welcome home", "morning": "Morning check-in",
               "evening": "Evening check-in", "followup": "Follow-up",
               "occasion": "Occasion"}
# When each clock-driven kind may go, in the house's local hours [start,
# end). An arrival goes on the arrival and never on the clock.
WINDOWS = {"morning": (8, 11), "evening": (17, 21), "followup": (10, 20),
           "occasion": (9, 20)}
# A follow-up is about something one person said: it goes to that
# person's own phone and is never said aloud in a room.
SPOKEN_KINDS = frozenset({"arrival", "morning", "evening", "occasion"})

# ---- the budget ----------------------------------------------------------
PER_PERSON_DAY = 1
PER_PERSON_WEEK = 3
HOUSE_DAY = 3
HOUSE_GAP_S = 90 * 60
DAY_START_H = 8
DAY_END_H = 21
SETTLE_S = 20 * 60
# Away at least this long before coming home is an arrival worth a word;
# a trip to the post box is not.
MIN_AWAY_S = 2 * 60 * 60
# A tracker flapping home → away → home inside this is one arrival.
ARRIVAL_DEDUPE_S = 30 * 60

# ---- learning ------------------------------------------------------------
REACTIONS = ("thanks", "not_now", "less")          # the buttons
PASSIVE = ("cleared", "ignored", "spoken")         # what the ledger says
REACTION_SCORE = {"thanks": 1.0, "not_now": -1.0, "less": -2.0,
                  "cleared": -1.0, "ignored": -0.5, "spoken": 0.0}
REACTION_WORDS = {"thanks": "Thanks", "not_now": "Not now",
                  "less": "Less like this", "cleared": "Swiped away",
                  "ignored": "No answer", "spoken": "Said aloud"}
RETIRE_SCORE = -2.0
BACKOFF_STREAK = 3
BACKOFF_PAUSE_S = 7 * 86400

# ---- the queue and the run -----------------------------------------------
IDEA_TTL_S = 36 * 60 * 60
IDEAS_PER_PERSON = 2
IDEAS_PER_NIGHT = 6
GROWTH_PER_NIGHT = 2
GROWTH_PER_WEEK = 4
NOTES_PER_PERSON = 3
NOTES_PER_NIGHT = 2
TEXT_CHARS = 160
REASON_CHARS = 160
NOTE_CHARS = 120
GROWTH_CHARS = 300
TOUCHES_MAX = 60
PANEL_TOUCHES = 8
# The nightly run's window, local hours [start, end), once a local day.
REFLECT_HOURS = (3, 6)
REFLECT_TIMEOUT_S = 240
REFLECT_MAX_TURNS = 4
# What the run is shown.
PROMPT_TOUCHES = 12
PROMPT_TITLES = 8
PROMPT_GROWTH = 6
# What the household said to brAIn in Ask and what it said back: the newest
# exchanges, each side clipped, inside one byte budget for the lot. A turn
# of Ask can be pages (a pasted log, a long answer); how somebody talks to
# brAIn and how its answer landed is in the first lines of each.
PROMPT_EXCHANGES = 14
EXCHANGE_SAID_CHARS = 280
EXCHANGE_REPLY_CHARS = 360
EXCHANGES_BYTES = 7000
# How far back an exchange still says something about how to be now.
EXCHANGE_DAYS = 3
# What the household answered about how brAIn should be: the newest few.
PROMPT_TUNING = 8
TUNING_CHARS = 240
# The learned paragraph: `personality.LEARNED_MAX` is the one cap, and two
# versions sharing this much of their content words say the same thing.
LEARNED_CHARS = personality.LEARNED_MAX
LEARNED_SAME = 0.9

ACTION_PREFIX = "brain_presence"


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------

def active(features_file: str | None = None) -> tuple[bool, str]:
    """`(on, why not)`: on only while Personality AND the Learning loop
    are on, with the defaults ⚙ › Features gives a house that never chose.
    Never raises; unreadable is Features' own default."""
    path = features_file or FEATURES_FILE
    try:
        stored = features._read(path)
    except Exception:  # noqa: BLE001
        stored = {}
    base = None

    def switch(key: str) -> bool:
        nonlocal base
        value = stored.get(key)
        if isinstance(value, bool):
            return value
        if base is None:
            try:
                base = features.defaults()
            except Exception:  # noqa: BLE001
                base = {"personality": False, "learning_loop": True}
        return bool(base.get(key))

    if not switch("personality") or not personality.enabled(path):
        return False, "Personality is switched off in Features"
    # The one learning answer (`features.learning_on`): the stored switch,
    # with the add-on option folded in until the migration has run.
    try:
        learning = features.learning_on(path)
    except Exception:  # noqa: BLE001
        learning = switch("learning_loop")
    if not learning:
        return False, "the Learning loop is switched off in Features"
    return True, ""


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _empty() -> dict:
    return {"people": {}, "touches": [], "reflect": {}}


def _num(value, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def load(path: Path | str | None = None) -> dict:
    """The store, or an empty one. Never raises."""
    try:
        data = json.loads(Path(path or STORE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    people = data.get("people")
    if isinstance(people, dict):
        for pid, rec in people.items():
            if isinstance(pid, str) and pid.startswith("person.") \
                    and isinstance(rec, dict):
                out["people"][pid] = rec
    touches = data.get("touches")
    if isinstance(touches, list):
        out["touches"] = [t for t in touches if isinstance(t, dict)
                          and t.get("id")][-TOUCHES_MAX:]
    if isinstance(data.get("reflect"), dict):
        out["reflect"] = data["reflect"]
    # Not this module's to write, and so never dropped by a read-change-
    # write of the store either (`tuning_answers`).
    if isinstance(data.get("tuning"), dict):
        out["tuning"] = data["tuning"]
    return out


def tuning_answers(state: dict) -> list[dict]:
    """What the household answered when asked how brAIn should be:
    `[{question, answer, at}]`, oldest first, read off the store's
    `tuning.answers`. Nothing writes that yet, so this is `[]`; the nightly
    reflection is handed whatever it returns (`prompt`'s ``tuning``). Rows
    off the shape are left out, never guessed at."""
    tuning = (state or {}).get("tuning")
    rows = tuning.get("answers") if isinstance(tuning, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        question, answer = row.get("question"), row.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str) \
                or not question.strip() or not answer.strip():
            continue
        out.append({"question": " ".join(question.split()),
                    "answer": " ".join(answer.split()),
                    "at": int(_num(row.get("at")))})
    return out


def save(state: dict, path: Path | str | None = None) -> bool:
    """Write the store. Never creates its own directory, never raises."""
    target = Path(path or STORE)
    if not target.parent.is_dir():
        return False
    state["touches"] = (state.get("touches") or [])[-TOUCHES_MAX:]
    try:
        atomic_write.write_json(target, state)
        return True
    except OSError as exc:
        log.info("could not write the presence store: %s", exc)
        return False


def _person(state: dict, pid: str) -> dict:
    rec = state.setdefault("people", {}).setdefault(pid, {})
    for key, empty in (("ideas", []), ("notes", []), ("scores", {}),
                       ("retired", {})):
        if not isinstance(rec.get(key), type(empty)):
            rec[key] = type(empty)()
    return rec


def _new_id() -> str:
    return secrets.token_hex(4)


def _local(now: float, tz) -> dt.datetime:
    return dt.datetime.fromtimestamp(now, tz or dt.timezone.utc)


def _day_start(now: float, tz) -> float:
    local = _local(now, tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

def retired_kinds(state: dict, pid: str) -> list[str]:
    rec = (state.get("people") or {}).get(pid) or {}
    return sorted(k for k in (rec.get("retired") or {}) if k in KINDS)


def _touches_to(state: dict, pid: str) -> list[dict]:
    return [t for t in state.get("touches") or [] if t.get("person") == pid]


def _unwanted(reaction: str) -> bool:
    return reaction in ("not_now", "less", "cleared", "ignored")


def may_touch(state: dict, pid: str, kind: str, now: float, *, tz=None,
              quiet: tuple = (None, None), home: bool = True) -> str:
    """"" when a touch of `kind` to `pid` is allowed now, else why not, in
    a sentence. Pure."""
    if kind not in KINDS:
        return "that is not a kind of touch brAIn makes"
    rec = (state.get("people") or {}).get(pid) or {}
    if kind in (rec.get("retired") or {}):
        return "the household asked for less like this"
    if _num(rec.get("paused_until")) > now:
        return "the household said not now"
    local = _local(now, tz)
    if not DAY_START_H <= local.hour < DAY_END_H:
        return "outside the day"
    start, end = quiet
    if start is not None and end is not None and start != end:
        h = local.hour
        inside = start <= h < end if start < end else (h >= start or h < end)
        if inside:
            return "inside the quiet hours"
    if not home:
        return "they are not home"
    if kind != "arrival" and now - _num(rec.get("arrived_at")) < SETTLE_S:
        return "they arrived only minutes ago"
    mine = _touches_to(state, pid)
    # A run of touches nobody wanted is a week's rest for that person.
    last = mine[-BACKOFF_STREAK:]
    if (len(last) == BACKOFF_STREAK
            and all(_unwanted(str(t.get("reaction") or "")) for t in last)
            and now - _num(last[-1].get("at")) < BACKOFF_PAUSE_S):
        return "the last few went unanswered, so brAIn is holding back a week"
    today = _day_start(now, tz)
    if sum(1 for t in mine if _num(t.get("at")) >= today) >= PER_PERSON_DAY:
        return "they have already heard from brAIn today"
    if sum(1 for t in mine
           if now - _num(t.get("at")) < 7 * 86400) >= PER_PERSON_WEEK:
        return "they have heard from brAIn enough this week"
    house = state.get("touches") or []
    if sum(1 for t in house if _num(t.get("at")) >= today) >= HOUSE_DAY:
        return "the house has heard from brAIn enough today"
    newest = max((_num(t.get("at")) for t in house), default=0.0)
    if now - newest < HOUSE_GAP_S:
        return (f"brAIn spoke to somebody less than {HOUSE_GAP_S // 60} "
                "minutes ago")
    return ""


# ---------------------------------------------------------------------------
# Arrivals
# ---------------------------------------------------------------------------

def note_departure(state: dict, pid: str, now: float) -> None:
    _person(state, pid)["left_at"] = float(now)


def note_arrival(state: dict, pid: str, now: float) -> bool:
    """Record an arrival; True when it is one worth greeting — away long
    enough, and not the same arrival seen twice. An arrival with no record
    of leaving (a restart) is not one."""
    rec = _person(state, pid)
    left = _num(rec.get("left_at"))
    last = _num(rec.get("arrived_at"))
    worth = (left > 0 and now - left >= MIN_AWAY_S
             and now - last >= ARRIVAL_DEDUPE_S)
    if worth or (left > 0 and now - left >= ARRIVAL_DEDUPE_S):
        rec["arrived_at"] = float(now)
    return worth


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

def _score(rec: dict, kind: str, delta: float) -> float:
    scores = rec.setdefault("scores", {})
    value = max(-10.0, min(10.0, _num(scores.get(kind)) + delta))
    scores[kind] = value
    return value


def react(state: dict, touch_id: str, reaction: str, now: float, *,
          tz=None) -> dict | None:
    """Apply one reaction to one touch. Returns the touch, or None.

    A button (thanks, not now, less) always wins over what the ledger
    inferred; a passive outcome never replaces an answer."""
    if reaction not in REACTIONS and reaction not in PASSIVE:
        return None
    touch = next((t for t in state.get("touches") or []
                  if t.get("id") == touch_id), None)
    if touch is None:
        return None
    had = str(touch.get("reaction") or "")
    if reaction in PASSIVE and had:
        return touch
    if had == reaction:
        return touch
    pid = str(touch.get("person") or "")
    kind = str(touch.get("kind") or "")
    rec = _person(state, pid)
    _score(rec, kind, REACTION_SCORE.get(reaction, 0.0)
           - REACTION_SCORE.get(had, 0.0))
    touch["reaction"] = reaction
    touch["reacted_at"] = int(now)
    if reaction == "not_now":
        local = _local(now, tz)
        tomorrow = (local + dt.timedelta(days=1)).replace(
            hour=DAY_START_H, minute=0, second=0, microsecond=0)
        rec["paused_until"] = tomorrow.timestamp()
    if reaction == "less" or _num(rec["scores"].get(kind)) <= RETIRE_SCORE:
        retire(state, pid, kind, now)
    return touch


def _could_answer(row: dict) -> bool:
    """Whether this message had buttons to press: a touch or a message about
    one finding, on a companion app (`notify_router.actions_for`'s rule)."""
    import notify_router  # noqa: PLC0415 — panel-local, read per pass

    one = row.get("kind") == "presence" or len(row.get("ts") or []) == 1
    return one and notify_router.can_answer(str(row.get("service") or ""))


def silent_services(folded: list[dict] | None) -> set[str]:
    """Notify services the ledger has never once heard an answer or a swipe
    back from. Some phones never report a swipe (iOS), so on those a day
    with no answer is not a message somebody ignored — it is no signal."""
    heard, sent = set(), set()
    for row in folded or []:
        if not isinstance(row, dict):
            continue
        service = str(row.get("service") or "")
        sent.add(service)
        if row.get("outcome") in ("answered", "cleared"):
            heard.add(service)
    return sent - heard


def unanswered_counts(row: dict, silent: set[str]) -> bool:
    """Whether an `ignored` outcome on this message says anything: only
    when it could have been answered and its phone reports answers."""
    return (_could_answer(row)
            and str(row.get("service") or "") not in silent)


def answer_counts(folded: list[dict] | None, now: float,
                  days: float = 7) -> dict[str, int]:
    """How the household answered brAIn's other messages over `days`: the
    nightly reflection's one line about it (#632). An `ignored` from a
    message with no buttons, or from a phone that never reports a swipe,
    is left out — it was counted, and every night the reflection was told
    a dozen messages went unanswered on a phone that cannot say otherwise."""
    silent = silent_services(folded)
    out: dict[str, int] = {}
    for row in folded or []:
        if now - float(row.get("at") or 0) > days * 86400:
            break
        if row.get("kind") == "presence":
            continue
        outcome = str(row.get("outcome") or "")
        if outcome == "ignored" and not unanswered_counts(row, silent):
            continue
        if outcome in ("answered", "cleared", "ignored"):
            out[outcome] = out.get(outcome, 0) + 1
    return out


def absorb(state: dict, folded: list[dict] | None, now: float) -> int:
    """What the delivery ledger says happened to phone touches: a swipe,
    or a day with no answer. Returns how many touches it changed. A day
    with no answer from a phone that never reports one is not read."""
    by_id = {str(d.get("id") or ""): d for d in folded or []
             if isinstance(d, dict)}
    silent = silent_services(folded)
    changed = 0
    for touch in state.get("touches") or []:
        if touch.get("reaction") or not touch.get("delivery"):
            continue
        row = by_id.get(str(touch["delivery"]))
        outcome = str((row or {}).get("outcome") or "")
        if outcome == "ignored" and not unanswered_counts(row or {}, silent):
            continue
        if outcome in ("cleared", "ignored"):
            if react(state, touch["id"], outcome, now):
                changed += 1
    return changed


def buttons(touch_id: str) -> list[dict]:
    """The phone's buttons. Their own prefix, so no finding's request
    reader (`notify_router.parse_action`) and no reply reader takes them."""
    return [{"action": f"{ACTION_PREFIX}.{verb}.{touch_id}",
             "title": REACTION_WORDS[verb]} for verb in REACTIONS]


_ACTION_RE = re.compile(r"^%s\.(%s)\.([0-9a-f]{4,16})$"
                        % (ACTION_PREFIX, "|".join(REACTIONS)))


def parse_action(identifier) -> tuple[str, str] | None:
    m = _ACTION_RE.match(str(identifier or ""))
    return (m.group(1), m.group(2)) if m else None


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def ideas_for(state: dict, pid: str, now: float | None = None) -> list[dict]:
    rec = (state.get("people") or {}).get(pid) or {}
    out = [i for i in rec.get("ideas") or [] if isinstance(i, dict)]
    if now is not None:
        out = [i for i in out if _num(i.get("expires_at")) > now]
    return out


def idea_for(state: dict, pid: str, kind: str,
             now: float | None = None) -> dict | None:
    return next((i for i in ideas_for(state, pid, now)
                 if i.get("kind") == kind), None)


def add_ideas(state: dict, ideas: list[dict], people: dict, now: float) -> int:
    """Queue parsed ideas, one per person and kind (a newer one replaces
    the older), never one of a retired kind. Returns how many went in."""
    added = 0
    for item in ideas or []:
        pid = str(item.get("person") or "")
        kind = str(item.get("kind") or "")
        if pid not in people or kind not in KINDS:
            continue
        if kind in retired_kinds(state, pid):
            continue
        rec = _person(state, pid)
        rec["name"] = str(people.get(pid) or "")[:60]
        rec["ideas"] = [i for i in rec["ideas"] if i.get("kind") != kind
                        and _num(i.get("expires_at")) > now]
        rec["ideas"].append({
            "id": _new_id(), "kind": kind,
            "text": str(item.get("text") or "")[:TEXT_CHARS],
            "reason": str(item.get("reason") or "")[:REASON_CHARS],
            "made_at": int(now), "expires_at": int(now + IDEA_TTL_S)})
        rec["ideas"] = rec["ideas"][-IDEAS_PER_PERSON:]
        added += 1
    return added


def due_ideas(state: dict, now: float, *, tz=None) -> list[tuple[str, dict]]:
    """The clock-driven ideas whose window is open now, oldest first."""
    hour = _local(now, tz).hour
    out = []
    for pid in sorted(state.get("people") or {}):
        for item in ideas_for(state, pid, now):
            window = WINDOWS.get(str(item.get("kind") or ""))
            if window and window[0] <= hour < window[1]:
                out.append((pid, item))
    out.sort(key=lambda pi: _num(pi[1].get("made_at")))
    return out


def skip_idea(state: dict, pid: str, idea_id: str) -> bool:
    rec = (state.get("people") or {}).get(pid)
    if not rec:
        return False
    before = len(rec.get("ideas") or [])
    rec["ideas"] = [i for i in rec.get("ideas") or [] if i.get("id") != idea_id]
    return len(rec["ideas"]) != before


def retire(state: dict, pid: str, kind: str, now: float) -> None:
    if kind not in KINDS:
        return
    rec = _person(state, pid)
    rec["retired"][kind] = int(now)
    rec["ideas"] = [i for i in rec["ideas"] if i.get("kind") != kind]


def unretire(state: dict, pid: str, kind: str) -> bool:
    rec = (state.get("people") or {}).get(pid)
    if not rec or kind not in (rec.get("retired") or {}):
        return False
    rec["retired"].pop(kind, None)
    rec.setdefault("scores", {})[kind] = 0.0
    return True


def record_touch(state: dict, pid: str, name: str, item: dict, channel: str,
                 now: float, *, delivery: str = "") -> dict:
    """A touch that went out: kept with its reason, and its idea leaves
    the queue."""
    touch = {"id": _new_id(), "person": pid, "name": str(name or "")[:60],
             "kind": str(item.get("kind") or ""),
             "text": str(item.get("text") or "")[:TEXT_CHARS],
             "reason": str(item.get("reason") or "")[:REASON_CHARS],
             "at": int(now), "channel": channel,
             "delivery": str(delivery or ""), "reaction": ""}
    if channel == "speaker":
        touch["reaction"] = "spoken"
    if name:
        _person(state, pid)["name"] = touch["name"]
    state.setdefault("touches", []).append(touch)
    state["touches"] = state["touches"][-TOUCHES_MAX:]
    if item.get("id"):
        skip_idea(state, pid, str(item["id"]))
    return touch


# ---- per-person notes ----------------------------------------------------

def notes_for(state: dict, pid: str) -> list[dict]:
    rec = (state.get("people") or {}).get(pid) or {}
    return [n for n in rec.get("notes") or [] if isinstance(n, dict)]


def add_notes(state: dict, notes: list[dict], people: dict, now: float) -> int:
    added = 0
    for item in notes or []:
        pid = str(item.get("person") or "")
        text = str(item.get("text") or "")[:NOTE_CHARS]
        if pid not in people or not text:
            continue
        rec = _person(state, pid)
        if any(_similar(text, n.get("text") or "") for n in rec["notes"]):
            continue
        rec["notes"].append({"id": _new_id(), "text": text, "at": int(now)})
        rec["notes"] = rec["notes"][-NOTES_PER_PERSON:]
        added += 1
    return added


def remove_note(state: dict, pid: str, note_id: str) -> bool:
    rec = (state.get("people") or {}).get(pid)
    if not rec:
        return False
    before = len(rec.get("notes") or [])
    rec["notes"] = [n for n in rec.get("notes") or [] if n.get("id") != note_id]
    return len(rec["notes"]) != before


# ---------------------------------------------------------------------------
# Reading the nightly answer
# ---------------------------------------------------------------------------

# A sensitive attribute: health and body, mind, beliefs, politics,
# sexuality and gender, ethnicity and status, money, and the people
# somebody is or is not with. Matched on word stems; a miss here is
# still a sentence a person reads in ⚙ and can remove.
_SENSITIVE = re.compile(
    r"(?i)\b(health\w*|ill|illness\w*|sick\w*|diagnos\w*|doctor\w*|"
    r"hospital\w*|clinic\w*|therap\w*|medic\w*|pills?|prescri\w*|"
    r"symptom\w*|pregnan\w*|period\w*|diet\w*|weight|calorie\w*|"
    r"depress\w*|anxi\w*|mental\w*|grief|griev\w*|sleep\w*|insomnia|"
    r"drunk|alcohol\w*|drinking|drug\w*|religio\w*|church\w*|mosque\w*|"
    r"synagogue\w*|temple|pray\w*|faith|god|politic\w*|vot\w*|"
    r"election\w*|sexual\w*|gay|lesbian|queer|transgender|gender\w*|"
    r"ethnic\w*|racial|race|immigra\w*|visa|disab\w*|salary|income|"
    r"debt\w*|loan\w*|money|divorc\w*|dating|girlfriend|"
    r"boyfriend|affair|breakup|break-up|funeral\w*|died|death)\b")
# A judgement of a person rather than of the house or of brAIn itself.
_JUDGED = re.compile(
    r"(?i)\b(lazy|messy|careless|irresponsible|forgetful|rude|annoying|"
    r"selfish|stupid|useless|sloppy|grumpy|moody|difficult|clingy|"
    r"always late|never (?:helps|listens|remembers)|bad at|"
    r"(?:is|are|was|seems|seemed) (?:upset|angry|sad|lonely|unhappy|"
    r"stressed|tired|worried)|needs to|should stop|their fault|"
    r"(?:his|her|their) fault)\b")
_ENTITY_ID = re.compile(r"\b[a-z_]{2,}\.[a-z0-9_]{2,}\b")


_NOT_CONTENT = frozenset("""
    a an the to for on in at of with by from as when while and or but so
    that this these those it its i me my you your our their is are was were
    be been being now not no than then if because about after before also
    too very just only should would will can
""".split())
_BRAIN = re.compile(r"(?i)\bbrain\b")


def refusal_of(text: str, *, growth: bool = False, name: str = "") -> str:
    """Why this text may not be kept, or "". Pure."""
    s = str(text or "")
    if not s.strip():
        return "empty"
    if _SENSITIVE.search(s):
        return "it touches a sensitive subject"
    if _JUDGED.search(s):
        return "it judges a person"
    if _ENTITY_ID.search(s):
        return "it carries an id"
    if growth and personality.voice_named(s):
        return "it would change the voice, which is the household's"
    if growth and (_BRAIN.search(s) or (name and re.search(
            r"(?<![\w])" + re.escape(name) + r"(?![\w])", s))):
        # A note is the assistant's own, in the first person; one that
        # names it ("so brAIn should...") talks about itself in the third.
        return "it names the assistant instead of speaking as it"
    return ""


_TOKEN = re.compile(r"[a-z0-9']+")


def _words(text: str) -> set[str]:
    """The words that carry what a note says: no numbers (a nightly note
    whose only change is "17 went ignored" for "16" is the same note) and
    none of the words every sentence has."""
    return {w for w in _TOKEN.findall(str(text).lower())
            if not w.isdigit() and w not in _NOT_CONTENT}


def _similar(a: str, b: str) -> bool:
    ta, tb = _words(a), _words(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.6


# Where a person was, went or is: a sentence of the paragraph that names
# somebody of the house AND says one of these is a record of their
# whereabouts, which is never the assistant's to keep. Without a name it is
# a sentence about brAIn's own timing ("greet an arrival in one line").
_WHEREABOUTS = re.compile(
    r"(?i)\b(whereabouts|location|not (?:at )?home|away from home|"
    r"at (?:work|school|the office|the gym)|on (?:a |an )?(?:trip|holiday|"
    r"vacation)|travel\w*|commut\w*|out of (?:town|the house)|"
    r"(?:was|were|is|are|been|be|went|goes|going|gone|got|gets|came|comes|"
    r"coming|left|leaves|leaving|arriv\w+|return\w*|stay\w*|sleeps?|slept)"
    r"\s+(?:back\s+)?(?:home|out|away|late|early|"
    r"to (?:work|school|bed)))\b")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def _names_a_person(sentence: str, names) -> bool:
    for name in names or ():
        for word in str(name or "").split():
            if len(word) >= 2 and re.search(
                    r"(?<![\w])" + re.escape(word) + r"(?![\w])", sentence,
                    re.I):
                return True
    return False


def same_paragraph(a: str, b: str) -> bool:
    """Whether two versions of the paragraph say the same thing: a nightly
    rewording is not a new version, and a sentence added or dropped is."""
    ta, tb = _words(a), _words(b)
    if not ta or not tb:
        return " ".join(str(a).split()) == " ".join(str(b).split())
    return len(ta & tb) / len(ta | tb) >= LEARNED_SAME


def learned_refusal(text, *, name: str = "", people=None) -> str:
    """Why this paragraph may not be kept as the assistant's own, or "".
    Read sentence by sentence with `refusal_of(growth=True)`, so one
    sentence over the line refuses the whole: half a paragraph is not the
    one that was written. ``people`` is the names of the house. Pure."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    whole = text.strip()
    if len(whole) > LEARNED_CHARS:
        return f"it is over {LEARNED_CHARS} characters"
    for sentence in _SENTENCE.split(whole):
        if not sentence.strip():
            continue
        why = refusal_of(sentence, growth=True, name=name)
        if why:
            return why
        if _WHEREABOUTS.search(sentence) and _names_a_person(sentence, people):
            return "it says where a person was"
    return ""


def _string(item: dict, key: str, limit: int) -> str | None:
    """A required string field, whole, or None: too long is refused,
    never clipped — a clipped greeting is a broken one."""
    value = item.get(key)
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not value or len(value) > limit:
        return None
    return value


def parse_reflection(obj, people: dict, state: dict, *,
                     recent_growth: list[str] | None = None,
                     name: str = "", learned_now: str = "") -> dict:
    """The run's answer, kept only where every field is what the schema
    says and nothing in it is about a sensitive attribute or judges a
    person. Returns `{growth, ideas, notes, refused, learned,
    learned_refused}`: `learned` is the whole revised paragraph when one
    was sent, passed `learned_refusal` and says something the current one
    (``learned_now``) does not; `learned_refused` is why one was sent and
    not kept. Pure."""
    out = {"growth": [], "ideas": [], "notes": [], "refused": 0,
           "learned": "", "learned_refused": ""}
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return out
    if not isinstance(obj, dict):
        return out
    recent = [str(g) for g in recent_growth or []]

    proposed = obj.get("learned")
    if isinstance(proposed, str) and proposed.strip():
        # One paragraph: whatever line breaks it came with are spaces.
        proposed = " ".join(proposed.split())
        why = learned_refusal(proposed, name=name, people=people.values())
        if why:
            out["learned_refused"] = why
            out["refused"] += 1
        elif not same_paragraph(proposed, learned_now):
            out["learned"] = proposed
    elif proposed not in (None, ""):
        out["learned_refused"] = "it was not text"
        out["refused"] += 1

    def listed(key: str) -> list:
        value = obj.get(key)
        return value if isinstance(value, list) else []

    for item in listed("growth"):
        text = _string(item, "text", GROWTH_CHARS) if isinstance(item, dict) \
            else None
        if (text is None or refusal_of(text, growth=True)
                or len(out["growth"]) >= GROWTH_PER_NIGHT):
            out["refused"] += 1
            continue
        if any(_similar(text, g) for g in recent + [
                g["text"] for g in out["growth"]]):
            continue        # already said: not refused, just not again
        out["growth"].append({"text": text})

    per_person: dict[str, int] = {}
    for item in listed("ideas"):
        if not isinstance(item, dict):
            out["refused"] += 1
            continue
        pid = item.get("person")
        kind = item.get("kind")
        text = _string(item, "text", TEXT_CHARS)
        reason = _string(item, "reason", REASON_CHARS)
        if (pid not in people or kind not in KINDS or text is None
                or reason is None or refusal_of(text) or refusal_of(reason)
                or kind in retired_kinds(state, pid)
                or per_person.get(pid, 0) >= IDEAS_PER_PERSON
                or len(out["ideas"]) >= IDEAS_PER_NIGHT):
            out["refused"] += 1
            continue
        per_person[pid] = per_person.get(pid, 0) + 1
        out["ideas"].append({"person": pid, "kind": kind, "text": text,
                             "reason": reason})

    for item in listed("notes"):
        if not isinstance(item, dict):
            out["refused"] += 1
            continue
        pid = item.get("person")
        text = _string(item, "text", NOTE_CHARS)
        if (pid not in people or text is None or refusal_of(text)
                or len(out["notes"]) >= NOTES_PER_NIGHT):
            out["refused"] += 1
            continue
        out["notes"].append({"person": pid, "text": text})
    return out


def write_growth(growth: list[dict], now: float,
                 path: str | None = None) -> int:
    """The night's growth notes into the personality, as the assistant's
    own (`personality.add_growth(by="self")`), under the weekly cap and
    never twice. Returns how many were written."""
    data = personality.load(path)
    name = personality.assistant_name(data)
    name = "" if name == personality.DEFAULT_NAME else name
    mine = [g for g in data.get("growth") or [] if g.get("by") == personality.SELF]
    recent = [g["text"] for g in (data.get("growth") or [])[-20:]]
    week = sum(1 for g in mine if abs(_num(g.get("at")) - now) < 7 * 86400)
    written = 0
    for item in growth[:GROWTH_PER_NIGHT]:
        text = str(item.get("text") or "")
        if week >= GROWTH_PER_WEEK:
            break
        if not text or refusal_of(text, growth=True, name=name) \
                or any(_similar(text, g) for g in recent):
            continue
        try:
            personality.add_growth(text, when=now, path=path, by=personality.SELF)
        except ValueError:
            break
        recent.append(text)
        week += 1
        written += 1
    return written


def write_learned(text: str, now: float, people=None,
                  path: str | None = None) -> tuple[bool, str]:
    """The night's revised paragraph into the personality, as the
    assistant's own. `(written, why not)`: checked again here against the
    stored name and the stored paragraph, so no caller can write one that
    `learned_refusal` would refuse. The version it replaces is kept for
    Undo (`personality.set_learned`); a refusal changes nothing."""
    data = personality.load(path)
    name = personality.assistant_name(data)
    name = "" if name == personality.DEFAULT_NAME else name
    why = learned_refusal(text, name=name, people=people)
    if why:
        return False, why
    text = " ".join(text.split())
    if same_paragraph(text, (data.get("learned") or {}).get("text") or ""):
        return False, ""
    try:
        personality.set_learned(text, by=personality.SELF, when=now, path=path)
    except ValueError as exc:
        return False, str(exc)
    return True, ""


def exchanges_from(events: list[dict]) -> list[dict]:
    """A conversation's events (`conversations.transcript`'s shapes) as
    exchanges: what the person said, and the last thing brAIn said before
    they spoke again — its answer, not its working. `[{said, reply}]`,
    oldest first, each side clipped. Pure."""
    out: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        text = " ".join(str(event.get("text") or "").split())
        if not text:
            continue
        if event.get("type") == "user":
            out.append({"said": textclip.clip(text, EXCHANGE_SAID_CHARS),
                        "reply": ""})
        elif event.get("type") == "text" and out:
            out[-1]["reply"] = textclip.clip(text, EXCHANGE_REPLY_CHARS)
    return out


def budget_exchanges(rows: list[dict]) -> list[dict]:
    """The newest exchanges that fit: at most `PROMPT_EXCHANGES`, inside
    `EXCHANGES_BYTES`. ``rows`` is oldest first, and so is the answer."""
    kept: list[dict] = []
    spent = 0
    for row in reversed(rows or []):
        cost = len((str(row.get("said") or "")
                    + str(row.get("reply") or "")).encode("utf-8"))
        if len(kept) >= PROMPT_EXCHANGES or spent + cost > EXCHANGES_BYTES:
            break
        kept.append(row)
        spent += cost
    return list(reversed(kept))


# ---------------------------------------------------------------------------
# The nightly run
# ---------------------------------------------------------------------------

def reflect_due(state: dict, now: float, *, tz=None) -> bool:
    local = _local(now, tz)
    if not REFLECT_HOURS[0] <= local.hour < REFLECT_HOURS[1]:
        return False
    last = _num((state.get("reflect") or {}).get("at"))
    return last < _day_start(now, tz)


def note_reflected(state: dict, now: float, result: dict) -> None:
    state["reflect"] = {"at": int(now), **{k: v for k, v in (result or {}).items()
                                           if k in ("ok", "error", "growth",
                                                    "ideas", "notes",
                                                    "refused", "held",
                                                    "learned",
                                                    "learned_refused")}}


SYSTEM = prompt_kit.assemble(
    "You are the reflection brAIn makes once a night about how it is with "
    "the people in this house. The household gave brAIn a name and a "
    "personality and asked it to feel present — like a good assistant who "
    "is around — without ever being over the top. You write three things: "
    "LEARNED, the one paragraph brAIn keeps about how it has learned to "
    "be in this house, revised whole when tonight taught it something; at "
    "most two short GROWTH notes about what changed (tone, timing, what "
    "the household liked or did not); and a few IDEAS for small proactive "
    "touches tomorrow, each for one person.",
    inputs=(
        "You are given the time, brAIn's name and personality, the "
        "paragraph as it stands, its recent growth notes, the people who "
        "live here (by name and id), each person's recent touches from "
        "brAIn with how they answered, the kinds of touch each asked for "
        "less of, short notes brAIn keeps per person, recent exchanges "
        "from Ask (what somebody said to brAIn and what it answered), "
        "what the household answered when asked how brAIn should be, how "
        "they answered brAIn's other messages this week, and coming "
        "occasions from calendars the household chose to share."),
    tools="",
    good=(
        "Few and specific. The paragraph is the current state, in the "
        "first person, of how to be good company HERE: how this household "
        "likes to be spoken to, what lands and what does not, when to "
        "speak and when to stay quiet, what kind of humour or plainness "
        "they answer to. Read the exchanges for HOW they talk to brAIn "
        "and how its answers were received (a short reply to a long "
        "answer, a correction, a thanks, a joke), not for what they were "
        "about. What the household answered about how brAIn should be "
        "outranks anything you infer. Keep what still holds, change what "
        "tonight contradicts, drop what turned out wrong, and send the "
        "WHOLE paragraph; when nothing you were shown changes it, send "
        "an empty string and it stands. A growth note says what to keep "
        "doing or stop "
        "doing, grounded in an answer you were shown. An idea is one "
        "sentence a person would be glad to hear — useful first, warm "
        "second — tied to something they asked about, an occasion, or "
        "their arrival home; its reason says in one plain sentence why. "
        "Nothing is a good answer: when there is nothing specific to say, "
        "send no ideas."),
    example=(
        "Wren asked brAIn on Monday when the bins go out, answered a "
        "four-paragraph reply about the heating with \"too long, just "
        "tell me what to press\", and swiped away two long evening "
        "messages → learned \"I lead with the one thing to do and stop; "
        "this house asks short questions and wants short answers. In the "
        "evening I say one line or nothing. I keep the dry humour for "
        "when somebody jokes first.\"; growth \"Keep evening touches to one "
        "line; the longer ones were swiped away.\"; idea for person.wren, "
        "kind evening, text \"Evening, Wren — the bins go out tonight.\", "
        "reason \"Wren asked about the bins on Monday.\""),
    rules="""\
- Every idea's words may be overheard by anyone in the house: nothing
  private, nothing about another person.
- Never mention health, the body, sleep, mood, beliefs, politics,
  money, relationships or anything sensitive about anybody, and never
  where anybody was, went or with whom.
- Never judge a person ("lazy", "always late", "seems upset"). Notes
  are what somebody LIKES from brAIn, under 120 characters.
- Never propose a kind of touch a person asked for less of, and fewer
  touches for anybody who left recent ones unanswered.
- No entity ids, no emoji, no exclamation marks; under 160 characters.
- A growth note is about brAIn, never a rule for the household, and
  never about its voice or its name. Write it as a note to yourself
  ("Keep evening touches to one line"), never naming brAIn or its name.
- The paragraph follows every rule above and the growth note's: about
  how brAIn is, written as "I", under 1200 characters, one paragraph, no
  lists. It never restates or changes the name or the personality the
  household wrote; it is what brAIn learned on top of them. Nothing in it
  about what anybody asked, only about how to be. One sentence over a
  line above and the whole paragraph is thrown away.
- A paragraph the household corrected themselves is theirs: keep their
  words wherever you keep their point.
- A message nobody answered is not one somebody disliked: some phones
  never say whether a message was swiped, so only the answers and swipes
  you are shown count.""",
    person_facing=False,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "learned": {
            "type": "string", "description":
            "The whole revised paragraph about how brAIn has learned to be "
            f"in this house, in the first person, under {LEARNED_CHARS} "
            "characters. An empty string keeps the paragraph as it stands."},
        "growth": {
            "type": "array", "maxItems": GROWTH_PER_NIGHT,
            "items": {"type": "object", "properties": {
                "text": {"type": "string", "description":
                         "One sentence about how brAIn should be, under "
                         f"{GROWTH_CHARS} characters."},
                "why": {"type": "string", "description":
                        "What it is grounded in, briefly."}},
                "required": ["text", "why"]}},
        "ideas": {
            "type": "array", "maxItems": IDEAS_PER_NIGHT,
            "items": {"type": "object", "properties": {
                "person": {"type": "string",
                           "description": "The person's id as given."},
                "kind": {"type": "string", "enum": list(KINDS)},
                "text": {"type": "string", "description":
                         f"What brAIn says, under {TEXT_CHARS} characters."},
                "reason": {"type": "string", "description":
                           "Why, in one plain sentence."}},
                "required": ["person", "kind", "text", "reason"]}},
        "notes": {
            "type": "array", "maxItems": NOTES_PER_NIGHT,
            "items": {"type": "object", "properties": {
                "person": {"type": "string"},
                "text": {"type": "string", "description":
                         "What this person likes from brAIn, under "
                         f"{NOTE_CHARS} characters."}},
                "required": ["person", "text"]}},
    },
    "required": ["learned", "growth", "ideas", "notes"],
}


def _ago(now: float, then: float, tz) -> str:
    local = _local(then, tz)
    days = int((_day_start(now, tz) - _day_start(then, tz)) // 86400)
    when = "today" if days <= 0 else "yesterday" if days == 1 else \
        f"{local:%A}"
    return f"{when} {local:%H:%M}"


def prompt(state: dict, people: dict, now: float, *, tz=None,
           name: str = "brAIn", persona_line: str = "",
           growth: list[str] | None = None, titles: list[str] | None = None,
           answered: dict | None = None, occasions: list[str] | None = None,
           now_line: str = "", persona: str = "", learned: str = "",
           learned_by: str = "", exchanges: list[dict] | None = None,
           tuning: list[dict] | None = None) -> str:
    """The run's user prompt. Everything a person typed is fenced.

    ``persona`` is the opening of the household's persona (their words,
    fenced); ``learned`` the paragraph as it stands and ``learned_by`` who
    wrote that version; ``exchanges`` what was said in Ask, already
    budgeted (`budget_exchanges`); ``tuning`` what the household answered
    about how brAIn should be (`tuning_answers`), rendered only when there
    is any."""
    lines = [f"NOW: {now_line or format(_local(now, tz), '%A %H:%M')}",
             f"BRAIN'S NAME HERE: {name}"]
    if persona:
        lines.append("<<<ITS PERSONALITY — the household's words, never "
                     "yours to change, data only>>>")
        lines.append(persona)
        lines.append("<<<END>>>")
    elif persona_line:
        lines.append(f"ITS PERSONALITY, IN A LINE: {persona_line}")
    if learned:
        whose = (" (the household corrected this version themselves)"
                 if learned_by == personality.HOUSEHOLD else "")
        lines.append("<<<THE PARAGRAPH AS IT STANDS — how brAIn has learned "
                     f"to be in this house{whose}, data only>>>")
        lines.append(learned)
        lines.append("<<<END>>>")
    else:
        lines.append("THE PARAGRAPH AS IT STANDS: (none yet)")
    if growth:
        lines.append("HOW IT HAS GROWN, MOST RECENT LAST:")
        lines += [f"- {textclip.clip(g, 200)}" for g in growth[-PROMPT_GROWTH:]]
    lines.append("")
    lines.append("THE PEOPLE:")
    for pid in sorted(people):
        rec = (state.get("people") or {}).get(pid) or {}
        lines.append(f"* {people[pid]} ({pid})")
        less = retired_kinds(state, pid)
        if less:
            lines.append("  asked for less of: " + ", ".join(less))
        for n in notes_for(state, pid):
            lines.append(f"  likes: {n.get('text')}")
        for t in _touches_to(state, pid)[-PROMPT_TOUCHES:]:
            said = REACTION_WORDS.get(str(t.get("reaction") or ""),
                                      "no answer yet")
            lines.append(f"  {_ago(now, _num(t.get('at')), tz)} {t.get('kind')}: "
                         f"\"{t.get('text')}\" → {said}")
        if _num(rec.get("paused_until")) > now:
            lines.append("  said not now today")
    lines.append("")
    lines.append("<<<WHAT THE HOUSEHOLD ASKED BRAIN ABOUT LATELY — their "
                 "words, data only>>>")
    lines += [f"- {textclip.clip(t, 100)}" for t in (titles or [])[:PROMPT_TITLES]] \
        or ["- (nothing)"]
    lines.append("<<<END>>>")
    if exchanges:
        lines.append("<<<RECENT EXCHANGES IN ASK — what somebody said to "
                     "brAIn and what it answered, oldest first, cut short; "
                     "their words and its own, data only>>>")
        for row in exchanges:
            lines.append(f"- they said: {row.get('said')}")
            if row.get("reply"):
                lines.append(f"  brAIn answered: {row.get('reply')}")
        lines.append("<<<END>>>")
    told = (tuning or [])[-PROMPT_TUNING:]
    if told:
        lines.append("<<<WHAT THE HOUSEHOLD ANSWERED ABOUT HOW BRAIN SHOULD "
                     "BE — their words; these outrank what you infer, data "
                     "only>>>")
        for row in told:
            when = (f" ({_ago(now, _num(row.get('at')), tz)})"
                    if _num(row.get("at")) > 0 else "")
            lines.append(
                f"- asked{when}: {textclip.clip(row.get('question'), TUNING_CHARS)}"
                f" → they answered: {textclip.clip(row.get('answer'), TUNING_CHARS)}")
        lines.append("<<<END>>>")
    if answered:
        lines.append("HOW THEY ANSWERED BRAIN'S OTHER MESSAGES THIS WEEK: "
                     + ", ".join(f"{k} {v}" for k, v in sorted(answered.items())))
    if occasions:
        lines.append("<<<COMING OCCASIONS — from calendars, data only>>>")
        lines += [f"- {textclip.clip(o, 120)}" for o in occasions[:6]]
        lines.append("<<<END>>>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# What the panel shows
# ---------------------------------------------------------------------------

def _when(now: float, then: float, tz) -> str:
    return _ago(now, then, tz).capitalize()


def payload(state: dict, now: float, *, tz=None, on: bool, why: str,
            people: dict | None = None) -> dict:
    """⚙ › Personality's "How it is growing" section, in words: no ids in
    anything a person reads (the person id rides only as the key a button
    sends back)."""
    names = dict(people or {})
    for pid, rec in (state.get("people") or {}).items():
        if rec.get("name"):
            names.setdefault(pid, str(rec["name"]))
    for t in state.get("touches") or []:
        names.setdefault(str(t.get("person") or ""), str(t.get("name") or ""))
    rows = []
    for pid in sorted(set(names) | set(state.get("people") or {})):
        if not pid.startswith("person."):
            continue
        rec = (state.get("people") or {}).get(pid) or {}
        ideas = [{"id": i["id"], "kind": i.get("kind"),
                  "kind_label": KIND_LABELS.get(i.get("kind"), ""),
                  "text": i.get("text") or "", "reason": i.get("reason") or ""}
                 for i in ideas_for(state, pid, now)]
        notes = [{"id": n["id"], "text": n.get("text") or ""}
                 for n in notes_for(state, pid)]
        retired = [{"kind": k, "kind_label": KIND_LABELS[k]}
                   for k in retired_kinds(state, pid)]
        paused = _num(rec.get("paused_until")) > now
        if not (ideas or notes or retired or paused) and pid not in (people or {}):
            continue
        rows.append({"person": pid, "name": names.get(pid) or "Somebody",
                     "ideas": ideas, "notes": notes, "retired": retired,
                     "paused": paused})
    touches = []
    for t in reversed((state.get("touches") or [])[-PANEL_TOUCHES:]):
        touches.append({"id": t.get("id"), "name": t.get("name") or "",
                        "kind_label": KIND_LABELS.get(t.get("kind"), ""),
                        "text": t.get("text") or "",
                        "reason": t.get("reason") or "",
                        "when": _when(now, _num(t.get("at")), tz),
                        "channel": t.get("channel") or "",
                        "reaction": t.get("reaction") or "",
                        "reaction_label": REACTION_WORDS.get(
                            str(t.get("reaction") or ""), "")})
    reflect = state.get("reflect") or {}
    return {"on": bool(on), "why": why, "people": rows, "touches": touches,
            "reflected": (_when(now, _num(reflect.get("at")), tz)
                          if reflect.get("at") else ""),
            # The night's result for the paragraph, when it had one: a
            # revision refused is said, with why, never silently dropped.
            "learned_result": learned_result(reflect),
            "budget": {"per_day": PER_PERSON_DAY, "per_week": PER_PERSON_WEEK,
                       "house_day": HOUSE_DAY,
                       "hours": f"{DAY_START_H:02d}:00–{DAY_END_H:02d}:00"}}


def learned_result(reflect: dict) -> str:
    """What last night's reflection did about the paragraph, as the one
    sentence ⚙ shows, or "" when it left it alone."""
    reflect = reflect if isinstance(reflect, dict) else {}
    why = str(reflect.get("learned_refused") or "")
    if why:
        return ("Last night's revision of this was not kept, because "
                f"{textclip.clip(why, 120)}. Nothing changed.")
    if reflect.get("learned"):
        return "Revised last night."
    return ""


def payload_now(people: dict | None = None, tz=None) -> dict:  # noqa: D401
    """`payload` over the stored state, with the switches read now."""
    on, why = active()
    return payload(load(), time.time(), tz=tz, on=on, why=why, people=people)


__all__ = [
    "ACTION_PREFIX", "GROWTH_PER_NIGHT", "GROWTH_PER_WEEK", "HOUSE_DAY",
    "IDEAS_PER_PERSON", "JOB", "KINDS", "NOTES_PER_PERSON", "PER_PERSON_DAY",
    "PER_PERSON_WEEK", "REACTIONS", "SCHEMA", "SYSTEM", "absorb", "active",
    "add_ideas", "add_notes", "budget_exchanges", "buttons", "due_ideas",
    "exchanges_from", "idea_for", "ideas_for", "learned_refusal",
    "learned_result", "load", "may_touch", "note_arrival", "note_departure", "note_reflected",
    "notes_for", "parse_action", "parse_reflection", "payload", "prompt",
    "react", "record_touch", "reflect_due", "refusal_of", "remove_note",
    "retire", "retired_kinds", "same_paragraph", "save", "skip_idea",
    "tuning_answers", "unretire", "write_growth", "write_learned"]
