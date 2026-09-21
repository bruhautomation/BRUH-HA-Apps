"""What HAPPENED, rather than every time a value changed.

The Activity tab was a logbook with a cause bolted on: one row per state
change, newest first, filtered by who did it. That is Home Assistant's own
logbook with an extra column, and on a real house it is hundreds of rows an
hour of `sensor.something → 21.4` — which is why it was reported as having
"basically zero utility in its current form".

Nobody thinks in state changes. A person thinks in EPISODES: the TV was on
in the lounge from eight until eleven; somebody got home at 17:40; the
bedroom heating ran from six until half past seven; the front camera saw
something four times between two and three. Every one of those sentences is
derivable from the logbook this module is already handed, and not one of
them was on any screen — in brAIn or in Home Assistant.

Five rules.

**A reading is not an event.** A numeric sensor reporting every thirty
seconds is most of a house's logbook and none of it is something that
happened. Those domains are dropped whole and **counted**, because a list
that silently discards most of its input is one nobody can trust: the tab
says how much it left out and why.

**An episode is a run, and a gap only ends one that had already stopped.**
Two rules and the second is the one a first cut gets wrong. A change
arriving within the subject's own gap extends the episode — a door opened
twice in a minute is one trip through it, a motion sensor is a burst and
never a row each, and the numbers differ per subject because the things
genuinely happen on different scales. But a change arriving after ANY gap
still extends an episode whose last state was **active**, because the thing
did not stop: a television playing at eight and switched off at eleven is
one programme of three hours, and a gap rule alone files the `off` as a
fresh episode of *off* — which is how a first cut reported "Lounge TV, off,
0 seconds" under a heading about what played. That is `appliances.py`'s
"below the threshold is not finished" on a timeline, with the half that
says what finishing looks like.

**The sort is by subject, not by cause.** "Who did it" is a debugging
question and it was the only filter this tab had. What a person asks is
*what happened with the heating today*, so the sections are the kinds of
thing a house is made of, each with its own vocabulary — and a section with
nothing in it is not rendered, because an empty heading is a house with a
problem it does not have.

**Nothing here asks a model.** It is arithmetic over one fetch, so it costs
a tab visit rather than a Claude run — `curiosity.py`'s rule, which is that
a model call made to decide whether to make a model call is the one design
that cannot pay. What a model is for is the paragraph, and that is a press.

**And nothing here decides anything.** It groups and it ranks; whether an
episode is worth worrying about is the checks' job and the analyst's, the
same split `baselines.py` and `closures.py` keep.
"""
from __future__ import annotations

# Domains whose changes are READINGS. A house publishes tens of thousands
# of these a day and none of them is an event: dropping them is the single
# biggest thing that turns a logbook into a list of what happened. They are
# counted rather than silently discarded, because a tab that shows 40 of
# 4,000 rows without saying so is one people stop believing.
#
# `button`, `input_button` and `event` are here for a different reason: they
# are stateless, so what the logbook calls their "state" is a timestamp, and
# a row reading `Doorbell → 2026-09-15T20:14:03` is noise wearing an event's
# clothes. The press itself reaches this tab through whatever it changed.
READINGS = frozenset({
    "sensor", "number", "input_number", "counter", "weather", "air_quality",
    "update", "button", "input_button", "event", "image", "todo",
    "stt", "tts", "conversation", "text", "input_text",
    "date", "datetime", "time", "input_datetime",
})

# The device classes that say what a `binary_sensor` or a `cover` IS.
# Borrowed from `closures.py` rather than re-derived — a door that this tab
# files under Motion and `evening.left_open` files under Doors is one house
# with two answers — but kept as its own names because this asks a wider
# question than "can it be left open".
DOOR_CLASSES = frozenset({"door", "garage_door", "window", "opening"})
COVER_CLASSES = frozenset({
    "door", "garage", "window", "gate", "awning", "shutter", "blind",
    "curtain", "damper", "shade",
})
MOTION_CLASSES = frozenset({
    "motion", "occupancy", "presence", "moving", "vibration", "sound",
})
# A leak, smoke or CO sensor is not "security" in the burglar sense and it
# belongs in the same section as the locks for the reason a person would put
# it there: these are the rows you look at first, and they are the rows that
# are about the house being safe rather than about it being used.
SAFETY_CLASSES = frozenset({
    "smoke", "gas", "carbon_monoxide", "moisture", "safety", "problem",
    "tamper", "heat", "cold",
})

# Each section: the id, what it is called, the sentence that says what is in
# it, the pause that ends an episode of it, and what one of its rows is
# ABOUT. The order is the order they are read in, and it is a judgement:
# what a person checks first is whether the house is safe and who is in it,
# and what they scroll past is a lamp.
#
# `reads` is the half a renderer would otherwise have to guess. A media
# episode is a SPAN ("3h 12m"), a motion episode is a COUNT ("seen 9
# times" — a momentary sensor's span is an artefact of when it last
# happened to fire), and a person's is a MOMENT ("out at 08:15"): three
# different sentences about the same shape of record, decided here so the
# panel cannot invent a fourth.
SUBJECTS: tuple[dict, ...] = (
    {"id": "security", "label": "Locks & safety", "gap_s": 300.0,
     "reads": "span",
     "blurb": "Locks, alarms, and the sensors that are about the house "
              "being safe rather than about it being used."},
    {"id": "people", "label": "People", "gap_s": 300.0,
     "reads": "moment",
     "blurb": "Who came and went. A tracker flapping at the edge of the "
              "wifi collapses into one row rather than twenty."},
    {"id": "climate", "label": "Heating & cooling", "gap_s": 1800.0,
     "reads": "span",
     "blurb": "What each room was asked to be, and when it was asked."},
    {"id": "openings", "label": "Doors, windows & blinds", "gap_s": 120.0,
     "reads": "span",
     "blurb": "What was opened and for how long. Two changes a minute "
              "apart is one trip through a door."},
    {"id": "media", "label": "Media", "gap_s": 1800.0,
     "reads": "span",
     "blurb": "What played, where, and for how long. A pause for an ad "
              "break is not the end of a programme."},
    {"id": "motion", "label": "Cameras & motion", "gap_s": 900.0,
     "reads": "count",
     "blurb": "Counted rather than listed: a hall sensor tripping nine "
              "times in an evening is one row that says nine."},
    {"id": "lights", "label": "Lights & switches", "gap_s": 900.0,
     "reads": "span",
     "blurb": "The bulk of what a house does, grouped so it can be read."},
    {"id": "other", "label": "Everything else", "gap_s": 900.0,
     "reads": "span",
     "blurb": "Scripts, scenes, helpers, and anything whose kind this "
              "could not tell — never guessed into a section it might "
              "not belong in."},
)

SUBJECT_IDS = tuple(s["id"] for s in SUBJECTS)
_BY_ID = {s["id"]: s for s in SUBJECTS}
_ORDER = {s["id"]: i for i, s in enumerate(SUBJECTS)}

# What one episode keeps of the changes inside it. A media player that
# changed forty times in three hours is one row and a number, and the tail
# is what the detail shows when somebody opens it.
MAX_STATES = 12
# Per section, so one busy domain cannot push every other section off the
# screen. The count is of everything, so a capped section says what it is
# not showing — the memory queue's rule.
MAX_ROWS = 40

# A state that reads as "this is doing something", per domain. It is what
# lets a row say "on for 3h 12m" rather than "4 changes": an episode that
# ENDS in an active state is still going, and one that ends inactive has a
# duration that means something.
ACTIVE_STATES = frozenset({
    "on", "open", "opening", "home", "playing", "heat", "cool", "heat_cool",
    "auto", "dry", "fan_only", "cleaning", "unlocked", "triggered",
    "recording", "streaming", "detected", "active", "running",
})


def domain_of(entity_id: str) -> str:
    return str(entity_id or "").split(".", 1)[0]


def subject_for(entity_id: str, device_class: str = "") -> str:
    """Which section this entity belongs in.

    Domain first and the device class only where the domain genuinely
    cannot answer, which is `binary_sensor` and `cover`: a `binary_sensor`
    with no class is a door, a motion sensor, a leak detector or a plug's
    own power flag, and naming one is a guess. So an unclassed one goes to
    **other** rather than to the section it is most likely to be in —
    `closures.is_closure`'s rule, and for its reason: the cost of being
    wrong here is the front door filed under Motion.
    """
    domain = domain_of(entity_id)
    klass = str(device_class or "").strip().lower()
    if domain in ("person", "device_tracker"):
        return "people"
    if domain in ("climate", "water_heater", "humidifier"):
        return "climate"
    if domain == "media_player":
        return "media"
    if domain in ("lock", "alarm_control_panel", "siren"):
        return "security"
    if domain == "camera":
        return "motion"
    if domain == "cover":
        # An unclassed cover is still a thing that opens — that is what the
        # domain means, which is why this one may fall through where a
        # binary_sensor may not.
        return "openings" if (klass in COVER_CLASSES or not klass) else "other"
    if domain == "valve":
        return "openings"
    if domain == "binary_sensor":
        if klass in DOOR_CLASSES:
            return "openings"
        if klass in MOTION_CLASSES:
            return "motion"
        if klass in SAFETY_CLASSES:
            return "security"
        return "other"
    if domain in ("light", "switch", "fan", "input_boolean", "vacuum",
                  "lawn_mower", "remote"):
        return "lights"
    return "other"


def is_reading(entity_id: str) -> bool:
    """A change nobody would call an event."""
    return domain_of(entity_id) in READINGS


def _active(state: str) -> bool:
    return str(state or "").strip().lower() in ACTIVE_STATES


def group(actions: list[dict], classes: dict[str, str] | None = None,
          now: float | None = None) -> dict:
    """Mined actions, oldest first, as episodes.

    Returns ``{"episodes": [...], "dropped": n, "kinds": {id: count}}`` —
    `dropped` being the readings, which is a number the tab has to be able
    to show: a list quietly hiding nine tenths of its input is the thing
    this is replacing.

    Pure, and deliberately over what it is handed rather than what it could
    fetch: the same list feeds `find_overrides` and the counts in the same
    request, and a second pass over the same window is two chances to
    disagree about it.
    """
    classes = classes or {}
    dropped = 0
    # entity id -> the episode still open for it. An episode closes when
    # the next change to that entity is further away than its subject's own
    # gap, which is why this is keyed per entity rather than per subject.
    live: dict[str, dict] = {}
    out: list[dict] = []
    for a in sorted(actions or [], key=lambda x: x.get("ts") or 0):
        entity_id = str(a.get("entity_id") or "")
        if not entity_id:
            continue
        if is_reading(entity_id):
            dropped += 1
            continue
        subject = subject_for(entity_id, classes.get(entity_id, ""))
        gap = _BY_ID[subject]["gap_s"]
        ts = float(a.get("ts") or 0)
        state = str(a.get("state") or "")
        ep = live.get(entity_id)
        if ep is not None and (_active(ep["last"]) or ts - ep["ended"] <= gap):
            # Either it never stopped, or this is close enough to be the
            # same burst. See the module docstring: the first half is what
            # makes an `off` three hours later the END of the programme
            # rather than an episode of its own.
            _extend(ep, a, ts, state)
            continue
        if ep is not None:
            out.append(ep)
        ep = {
            "subject": subject,
            "entity_id": entity_id,
            "name": str(a.get("name") or entity_id),
            "started": ts,
            "ended": ts,
            "count": 1,
            "first": state,
            "last": state,
            "states": [{"ts": ts, "state": state,
                        "cause": a.get("cause") or "unattributed",
                        "by_name": str(a.get("by_name") or "")}],
            "causes": {},
            "cause": "",
            "by_name": "",
        }
        _credit(ep, a)
        live[entity_id] = ep
    out.extend(live.values())
    for ep in out:
        _settle(ep, now)
    out.sort(key=lambda e: (_ORDER[e["subject"]], -e["ended"]))
    kinds: dict[str, int] = {}
    for ep in out:
        kinds[ep["subject"]] = kinds.get(ep["subject"], 0) + 1
    return {"episodes": out, "dropped": dropped, "kinds": kinds}


def _extend(ep: dict, a: dict, ts: float, state: str) -> None:
    ep["ended"] = ts
    ep["last"] = state
    ep["count"] += 1
    ep["states"].append({"ts": ts, "state": state,
                         "cause": a.get("cause") or "unattributed",
                         "by_name": str(a.get("by_name") or "")})
    _credit(ep, a)


def _credit(ep: dict, a: dict) -> None:
    cause = str(a.get("cause") or "unattributed")
    ep["causes"][cause] = ep["causes"].get(cause, 0) + 1


def _settle(ep: dict, now: float | None) -> None:
    """The numbers that are read off an episode once it is closed.

    ``duration_s`` is **how long this episode has covered**, which is one
    number with one meaning in both states it can be in: a light switched
    on at 18:00 and off at 23:00 has covered five hours and is finished,
    and one switched on at 18:00 with nothing since has covered whatever
    it is now and is not. `open` is which — carried rather than inferred
    from the number, because "0 s" about a light that has been on all
    evening is the reading a first cut produced and it is worse than none.

    The cause is the commonest one that is not `unattributed`: a run that a
    person started and an automation continued is a person's, and reading
    the first would make every automation's tidy-up its author.
    """
    ep["open"] = _active(ep["last"])
    upto = float(now) if (ep["open"] and now) else ep["ended"]
    ep["duration_s"] = max(0.0, upto - ep["started"])
    named = {c: n for c, n in ep["causes"].items() if c != "unattributed"}
    if named:
        ep["cause"] = max(named.items(), key=lambda kv: kv[1])[0]
        for row in ep["states"]:
            if row["cause"] == ep["cause"] and row["by_name"]:
                ep["by_name"] = row["by_name"]
                break
    else:
        ep["cause"] = "unattributed"
    # Newest first inside the row, and capped: the head of a forty-change
    # episode is the part nobody scrolls to.
    ep["states"] = list(reversed(ep["states"]))[:MAX_STATES]


def sections(grouped: dict) -> list[dict]:
    """The episodes as the tab renders them: one block per subject that has
    something in it, capped, with the count of everything so a capped block
    can say what it is not showing."""
    out = []
    for spec in SUBJECTS:
        rows = [e for e in grouped.get("episodes") or []
                if e["subject"] == spec["id"]]
        if not rows:
            continue
        out.append({
            "id": spec["id"], "label": spec["label"], "blurb": spec["blurb"],
            "reads": spec["reads"],
            "total": len(rows), "episodes": rows[:MAX_ROWS],
            "changes": sum(e["count"] for e in rows),
        })
    return out


# ---------------------------------------------------------------------------
# What brAIn knows that a logbook does not
# ---------------------------------------------------------------------------

def away_spans(grouped: dict, now: float | None = None) -> list[dict]:
    """When the house was empty, out of the same window.

    This is the one overlay worth having for free: "the heating ran for two
    hours and nobody was in" is a sentence Home Assistant holds every fact
    for and has never said. It is derived from `person.*` episodes only —
    a `device_tracker` is a phone, and a phone on a charger in the hall is
    not a person.

    **A person never seen is not a person who was out.** The logbook carries
    CHANGES, so the state before anybody's first one is genuinely unknown,
    and reading that silence as "away" would report an empty house on every
    window where nobody moved. So the roster is taken FIRST — every person
    who changed anywhere in the window — and a span cannot open until every
    one of them has been seen at least once: walking the changes and
    claiming an empty house off whoever has been met so far reports one the
    instant the first person leaves, and closes it when the second is met
    still sitting at home, which is a span that never happened. That is
    `clear_resolved`'s rule in the half that claims something about a house
    rather than about a row.

    A span still running ends at ``now`` when there is one, and at the last
    thing that happened otherwise — never at the last person's own move,
    which is where it started and would make it zero seconds long.
    """
    people = [e for e in grouped.get("episodes") or []
              if e["subject"] == "people"
              and domain_of(e["entity_id"]) == "person"]
    if not people:
        return []
    # Every change any person made, oldest first, as (ts, entity, home).
    moves: list[tuple[float, str, bool]] = []
    for ep in people:
        for row in ep["states"]:
            moves.append((float(row["ts"]), ep["entity_id"],
                          str(row["state"]).strip().lower() == "home"))
    moves.sort(key=lambda m: m[0])
    roster = {ep["entity_id"] for ep in people}
    known: dict[str, bool] = {}
    spans: list[dict] = []
    opened: float | None = None
    for ts, entity_id, home in moves:
        known[entity_id] = home
        everyone_out = len(known) == len(roster) and not any(known.values())
        if everyone_out and opened is None:
            opened = ts
        elif not everyone_out and opened is not None:
            spans.append({"start": opened, "end": ts})
            opened = None
    if opened is not None:
        last = max([float(now)] if now else [],
                   default=max((e["ended"] for e in grouped.get("episodes") or []),
                               default=opened))
        spans.append({"start": opened, "end": max(last, opened),
                      "ongoing": True})
    return [s for s in spans if s["end"] > s["start"]]


def within(spans: list[dict], ts: float) -> bool:
    """Whether an instant falls inside one of the spans."""
    return any(s["start"] <= ts <= s["end"] for s in spans or [])


def mark_overrides(grouped: dict, overrides: list[dict]) -> int:
    """Put each override on the episode it happened in.

    1.28's tab listed them in a block above the list, which is where they
    went to be skimmed: a count of "somebody put things back 4×" is not
    something anybody can act on, while *this* row being the one a person
    undid is. The block is gone and the mark is on the row.

    Keyed on the entity and the instant rather than on a join the miner
    could hand over, because an override is recorded against the PERSON's
    move and the episode it belongs to is the one that contains it.
    """
    marked = 0
    for o in overrides or []:
        ts = float(o.get("ts") or 0)
        entity_id = str(o.get("entity_id") or "")
        for ep in grouped.get("episodes") or []:
            if (ep["entity_id"] == entity_id
                    and ep["started"] <= ts <= ep["ended"]):
                ep["undid"] = str(o.get("by_name") or o.get("by") or "")
                marked += 1
                break
    return marked


# ---------------------------------------------------------------------------
# The paragraph — the one part of this that costs anything
# ---------------------------------------------------------------------------
#
# Everything above is arithmetic over one fetch, so the tab is free however
# often somebody opens it. This is the other half, and it is a PRESS: a
# Claude run behind a tab that refreshes on every visit is the "refresh
# everything" button with a timer on it, which is the control this panel
# deleted.
#
# What the model is for is the SENTENCE, `brief.py`'s split exactly: the
# gathering is deterministic and capped before anything is spawned, so what
# is asked is "say what this adds up to", never "go and find something".

SUMMARY_TIMEOUT_S = 240
SUMMARY_MAX_TURNS = 16
# Enough for a day of a busy house, and few enough that the reply is a
# paragraph rather than a list read back.
SUMMARY_MAX_ROWS = 60
SUMMARY_MAX_WORDS = 90
# A four-word summary is worse than the silence it replaced — `brief.py`'s
# floor, for its reason.
SUMMARY_MIN_CHARS = 60

SUMMARY_SYSTEM = """You are describing what happened in somebody's home.

You are given episodes already grouped from the logbook — what each thing
did, when, for how long, and what caused it. Say what the window ADDS UP
TO, in at most %(words)d words, one paragraph, no greeting, no markdown, no
bullet list.

Write about the house, never about the person. Nothing about health,
sleep, who was in, or what anybody was doing — "the house was empty from
09:10" is about the house; "they were at work" is not, and there is no
exception to this.

Say what is notable and say nothing when there is nothing: a quiet day is
"a quiet day" and not a list of the lights that came on. Prefer the thing
somebody could not have got by looking — a run that was longer than the
rest, something that happened while the house was empty, an automation a
person undid — over an inventory of what is on the screen already.

Do not invent a cause. If an episode says nothing moved it, it says
nothing moved it.""" % {"words": SUMMARY_MAX_WORDS}


def summary_prompt(payload: dict, tz_name: str = "") -> str:
    """The window, capped, as the text one run is handed.

    Built from the SECTIONS rather than from the raw actions: what is being
    summarised is what the person is looking at, and a model handed the
    four hundred underlying rows would write about the ones the tab
    deliberately does not show.
    """
    import datetime as _dt

    def clock(ts: float) -> str:
        try:
            return _dt.datetime.fromtimestamp(float(ts)).strftime("%H:%M")
        except (ValueError, OSError, OverflowError):
            return "??:??"

    parts = [f"WINDOW: {clock(payload.get('start') or 0)} to "
             f"{clock(payload.get('end') or 0)}"
             + (f" ({tz_name})" if tz_name else "")]
    away = payload.get("away") or []
    if away:
        parts.append("NOBODY HOME: " + ", ".join(
            f"{clock(s['start'])}–{clock(s['end'])}"
            + (" (still)" if s.get("ongoing") else "") for s in away[:6]))
    budget = SUMMARY_MAX_ROWS
    for section in payload.get("sections") or []:
        if budget <= 0:
            break
        rows = section.get("episodes") or []
        take = rows[:max(1, min(len(rows), budget))]
        budget -= len(take)
        parts.append(f"\n{section['label'].upper()} "
                     f"({section.get('total', len(rows))} in this window):")
        for ep in take:
            bits = [f"- {ep['name']}: {ep['first']}"]
            if ep["last"] != ep["first"]:
                bits.append(f" to {ep['last']}")
            bits.append(f", {clock(ep['started'])}")
            if ep["duration_s"] >= 60:
                bits.append(f" for {round(ep['duration_s'] / 60)} min")
            if ep["open"]:
                bits.append(" (still)")
            if ep["count"] > 1:
                bits.append(f", {ep['count']} changes")
            if ep.get("cause") and ep["cause"] != "unattributed":
                bits.append(f", by {ep['cause']}")
                if ep.get("by_name"):
                    bits.append(f" {ep['by_name']}")
            if ep.get("undid"):
                bits.append(" — a person undid this")
            parts.append("".join(bits))
    dropped = int(payload.get("dropped") or 0)
    if dropped:
        parts.append(f"\n({dropped} sensor readings in this window are not "
                     "listed — they are readings, not events.)")
    parts.append("\nSay what this adds up to.")
    return "\n".join(parts)


__all__ = [
    "ACTIVE_STATES", "COVER_CLASSES", "DOOR_CLASSES", "MAX_ROWS",
    "MAX_STATES", "MOTION_CLASSES", "READINGS", "SAFETY_CLASSES",
    "SUBJECTS", "SUBJECT_IDS", "SUMMARY_MAX_ROWS", "SUMMARY_MAX_TURNS",
    "SUMMARY_MAX_WORDS", "SUMMARY_MIN_CHARS", "SUMMARY_SYSTEM",
    "SUMMARY_TIMEOUT_S", "away_spans", "domain_of", "group",
    "is_reading", "mark_overrides", "sections", "subject_for",
    "summary_prompt", "within",
]
