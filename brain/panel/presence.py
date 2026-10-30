"""The presence loop: how the assistant grows, and how it keeps in touch.

The household gave brAIn a name and a personality (`personality.py`), and
asked for it to feel present rather than like something running in the
background — to think about how it should be, and about how to be good
company to the people in the house — without ever being over the top.
This module is the arithmetic and the store for that. The server half
(`server._presence_*`) is the bus, one cheap nightly run and delivery.

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
only what the household gave brAIn — names, what they asked it about, how
they answered its messages, opted-in calendars — and its answer is read
strictly: an item off the schema, about somebody not in the house, past
its length, carrying an entity id, about a sensitive attribute (health,
body, beliefs, money, relationships, identity) or judging a person is
refused, not softened. Nothing here writes the Resident's verdict log or
a fact (`outcomes._is_person_scope`'s rule). Per-person notes are three
short lines at most, shown in ⚙ and removable; every touch delivered is
kept with its one-sentence reason.

    /data/presence.json
    {"people": {"person.x": {"ideas": [...], "notes": [...],
                             "scores": {kind: n}, "retired": {kind: at},
                             "paused_until": t, "left_at": t,
                             "arrived_at": t}},
     "touches": [{id, person, name, kind, text, reason, at, channel,
                  delivery, reaction, reacted_at}],
     "reflect": {"at": t, "ok": bool, ...}}
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

# The model job (`model_plan.JOBS`): the cheapest tier, never stepped up.
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
SCORE_WINDOW = 10

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
REFLECT_TIMEOUT_S = 180
REFLECT_MAX_TURNS = 4
# What the run is shown.
PROMPT_TOUCHES = 12
PROMPT_TITLES = 8
PROMPT_GROWTH = 6

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
    if not switch("learning_loop"):
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


def absorb(state: dict, folded: list[dict] | None, now: float) -> int:
    """What the delivery ledger says happened to phone touches: a swipe,
    or a day with no answer. Returns how many touches it changed."""
    by_id = {str(d.get("id") or ""): d for d in folded or []
             if isinstance(d, dict)}
    changed = 0
    for touch in state.get("touches") or []:
        if touch.get("reaction") or not touch.get("delivery"):
            continue
        row = by_id.get(str(touch["delivery"]))
        outcome = str((row or {}).get("outcome") or "")
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


def refusal_of(text: str, *, growth: bool = False) -> str:
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
    return ""


_TOKEN = re.compile(r"[a-z0-9']+")


def _similar(a: str, b: str) -> bool:
    ta = set(_TOKEN.findall(str(a).lower()))
    tb = set(_TOKEN.findall(str(b).lower()))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.6


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
                     recent_growth: list[str] | None = None) -> dict:
    """The run's answer, kept only where every field is what the schema
    says and nothing in it is about a sensitive attribute or judges a
    person. Returns `{growth, ideas, notes, refused}`. Pure."""
    out = {"growth": [], "ideas": [], "notes": [], "refused": 0}
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return out
    if not isinstance(obj, dict):
        return out
    recent = [str(g) for g in recent_growth or []]

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
    mine = [g for g in data.get("growth") or [] if g.get("by") == personality.SELF]
    recent = [g["text"] for g in (data.get("growth") or [])[-20:]]
    week = sum(1 for g in mine if abs(_num(g.get("at")) - now) < 7 * 86400)
    written = 0
    for item in growth[:GROWTH_PER_NIGHT]:
        text = str(item.get("text") or "")
        if week >= GROWTH_PER_WEEK:
            break
        if not text or refusal_of(text, growth=True) \
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
                                                    "refused", "held")}}


SYSTEM = prompt_kit.assemble(
    "You are the reflection brAIn makes once a night about how it is with "
    "the people in this house. The household gave brAIn a name and a "
    "personality and asked it to feel present — like a good assistant who "
    "is around — without ever being over the top. You write two things: "
    "at most two short GROWTH notes about how brAIn should be (tone, "
    "timing, what the household liked or did not), and a few IDEAS for "
    "small proactive touches tomorrow, each for one person.",
    inputs=(
        "You are given the time, brAIn's name and personality, the people "
        "who live here (by name and id), each person's recent touches from "
        "brAIn with how they answered, the kinds of touch each asked for "
        "less of, short notes brAIn keeps per person, the titles of what "
        "the household asked brAIn about lately, how they answered brAIn's "
        "other messages this week, and coming occasions from calendars the "
        "household chose to share."),
    tools="",
    good=(
        "Few and specific. A growth note says what to keep doing or stop "
        "doing, grounded in an answer you were shown. An idea is one "
        "sentence a person would be glad to hear — useful first, warm "
        "second — tied to something they asked about, an occasion, or "
        "their arrival home; its reason says in one plain sentence why. "
        "Nothing is a good answer: when there is nothing specific to say, "
        "send no ideas."),
    example=(
        "Wren asked brAIn on Monday when the bins go out, and swiped away "
        "two long evening messages → growth \"Keep evening touches to one "
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
  never about its voice or its name.""",
    person_facing=False,
)

SCHEMA = {
    "type": "object",
    "properties": {
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
    "required": ["growth", "ideas", "notes"],
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
           now_line: str = "") -> str:
    """The run's user prompt. Everything a person typed is fenced."""
    lines = [f"NOW: {now_line or format(_local(now, tz), '%A %H:%M')}",
             f"BRAIN'S NAME HERE: {name}"]
    if persona_line:
        lines.append(f"ITS PERSONALITY, IN A LINE: {persona_line}")
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
            "budget": {"per_day": PER_PERSON_DAY, "per_week": PER_PERSON_WEEK,
                       "house_day": HOUSE_DAY,
                       "hours": f"{DAY_START_H:02d}:00–{DAY_END_H:02d}:00"}}


def payload_now(people: dict | None = None, tz=None) -> dict:  # noqa: D401
    """`payload` over the stored state, with the switches read now."""
    on, why = active()
    return payload(load(), time.time(), tz=tz, on=on, why=why, people=people)


__all__ = [
    "ACTION_PREFIX", "GROWTH_PER_NIGHT", "GROWTH_PER_WEEK", "HOUSE_DAY",
    "IDEAS_PER_PERSON", "JOB", "KINDS", "NOTES_PER_PERSON", "PER_PERSON_DAY",
    "PER_PERSON_WEEK", "REACTIONS", "SCHEMA", "SYSTEM", "absorb", "active",
    "add_ideas", "add_notes", "buttons", "due_ideas", "idea_for", "ideas_for",
    "load", "may_touch", "note_arrival", "note_departure", "note_reflected",
    "notes_for", "parse_action", "parse_reflection", "payload", "prompt",
    "react", "record_touch", "reflect_due", "refusal_of", "remove_note",
    "retire", "retired_kinds", "save", "skip_idea", "unretire",
    "write_growth"]
