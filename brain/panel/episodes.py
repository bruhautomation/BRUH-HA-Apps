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

Three corrections the logbook needs before it can be read as a house,
each found on a real one.

**A row that says "since" has to agree with the house now.** The logbook
drops some transitions — a climate entity going unavailable across a
restart is the one that was caught — so the last change it holds can be
seventeen hours stale while the entity has been unavailable since the
morning. ``live`` is one `/states` read: when the entity is no longer in
the state its newest episode ends in, that episode ends where the live
`last_changed` says, and the state it is really in becomes an episode of
its own. A row reading "heat_cool since 20:36" about a thermostat that
has not answered since 11:11 is the reading nothing could correct.

**Home Assistant restarting is an event, and it explains the minute after
it.** Core's start and stop carry no entity, so the miner drops them; they
are passed in as ``lifecycle`` and become one row, and every row nothing
caused that began around it is marked as having begun around it.

**Forty things changing in the same second is one thing happening.** An
integration reload moves every entity it owns at once, and listing them
is a page of one fact. Changes nothing caused, to one state, in one
second, across ``MASS_MIN`` or more entities are one row that names the
integration when the registry says they share one. And a
`device_tracker` is a person only where nothing better is — a house with
`person.*` entities has its people in those, and a router's tracker for a
smart plug was never anybody.
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
    # First because it explains rows below it: the minute after a restart
    # is a page of things going unavailable and coming back.
    # No entity is ever grouped by this gap — its rows are built whole by
    # `restart_episodes` and `_mass_changes` — but every subject carries one.
    {"id": "system", "label": "Home Assistant", "gap_s": 60.0,
     "reads": "span",
     "blurb": "Home Assistant itself stopping and starting, and anything "
              "that moved a whole integration's devices at once."},
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


# How many entities moving to one state in one second, with nothing to
# say what moved them, is an integration doing it rather than a house. A
# scene that turns six lights on carries the scene as its cause and is
# never collapsed — only the changes nothing claims are.
MASS_MIN = 6
# A reload that takes everything unavailable and brings it back a few
# seconds later is one thing that happened, so a second burst over mostly
# the same entities within this long joins the first.
MASS_JOIN_S = 300.0
# How many of a collapsed row's entities it carries, for the detail.
MASS_KEEP = 40
# A stop and the start after it are one restart while they are this close.
RESTART_PAIR_S = 3600.0
# What "around a restart" means for a row nothing caused: a minute before
# the stop (the shutdown takes entities with it) to ten minutes after the
# start (an integration that is slow to set up comes back late).
RESTART_BEFORE_S = 60.0
RESTART_AFTER_S = 600.0

# What an integration is called when a collapsed row names it. Anything
# not here is its domain with the underscores taken out, which is right
# for most of them and only wrong in its capitals.
INTEGRATION_NAMES = {
    "unifi": "UniFi", "zha": "ZHA", "mqtt": "MQTT", "zwave_js": "Z-Wave",
    "esphome": "ESPHome", "homekit_controller": "HomeKit", "hue": "Hue",
    "tplink": "TP-Link", "shelly": "Shelly", "tuya": "Tuya",
    "wled": "WLED", "lifx": "LIFX", "sonos": "Sonos", "cast": "Google Cast",
    "nmap_tracker": "Nmap", "ping": "Ping", "bluetooth_le_tracker":
    "Bluetooth LE", "mobile_app": "Mobile App", "matter": "Matter",
}


def integration_name(platform: str) -> str:
    p = str(platform or "").strip()
    if not p:
        return ""
    return INTEGRATION_NAMES.get(p, p.replace("_", " ").title())


def _norm(state) -> str:
    return str(state or "").strip().lower()


def group(actions: list[dict], classes: dict[str, str] | None = None,
          now: float | None = None, *,
          live: dict[str, dict] | None = None,
          people_trackers: set[str] | frozenset[str] | None = None,
          platforms: dict[str, str] | None = None,
          lifecycle: list[dict] | None = None) -> dict:
    """Mined actions, oldest first, as episodes.

    Returns ``{"episodes": [...], "dropped": n, "kinds": {id: count}}`` —
    `dropped` being the readings, which is a number the tab has to be able
    to show: a list quietly hiding nine tenths of its input is the thing
    this is replacing.

    Pure, and deliberately over what it is handed rather than what it could
    fetch: the same list feeds `find_overrides` and the counts in the same
    request, and a second pass over the same window is two chances to
    disagree about it. The keyword arguments are the three corrections the
    module docstring describes, each optional so a caller without them gets
    exactly the grouping it had:

    * ``live`` — ``{entity_id: {"state", "last_changed"}}`` from `/states`;
    * ``people_trackers`` — the `device_tracker` ids that may stand for a
      person (a phone's GPS tracker), or None for "not known";
    * ``platforms`` — ``{entity_id: integration}`` to name a collapsed row;
    * ``lifecycle`` — `actions.lifecycle`'s starts and stops.
    """
    classes = classes or {}
    dropped = 0
    rows: list[dict] = []
    for a in actions or []:
        entity_id = str(a.get("entity_id") or "")
        if not entity_id:
            continue
        if is_reading(entity_id):
            dropped += 1
            continue
        rows.append(a)
    rows.sort(key=lambda x: x.get("ts") or 0)

    # A house with `person.*` entities has its people in those; a tracker
    # there is a phone or, far more often, a router's view of a plug.
    has_person = any(domain_of(a["entity_id"]) == "person" for a in rows) or \
        any(domain_of(e) == "person" for e in (live or {}))

    def subject_of(entity_id: str) -> str:
        subject = subject_for(entity_id, classes.get(entity_id, ""))
        if subject == "people" and domain_of(entity_id) == "device_tracker":
            if has_person or (people_trackers is not None
                              and entity_id not in people_trackers):
                return "other"
        return subject

    out, rows = _mass_changes(rows, platforms or {})

    # entity id -> the episode still open for it. An episode closes when
    # the next change to that entity is further away than its subject's own
    # gap, which is why this is keyed per entity rather than per subject.
    current: dict[str, dict] = {}
    for a in rows:
        entity_id = str(a["entity_id"])
        subject = subject_of(entity_id)
        gap = _BY_ID[subject]["gap_s"]
        ts = float(a.get("ts") or 0)
        state = str(a.get("state") or "")
        ep = current.get(entity_id)
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
        current[entity_id] = ep
    newest = list(current.values())
    out.extend(newest)
    for ep in out:
        if ep.get("kind") != "mass":
            _settle(ep, now)
    out.extend(_agree_with_now(newest, live or {}, now))
    restarts = restart_episodes(lifecycle or [])
    _mark_restarts(out, restarts)
    out.extend(restarts)
    out.sort(key=lambda e: (_ORDER[e["subject"]], -e["ended"], -e["started"]))
    kinds: dict[str, int] = {}
    for ep in out:
        kinds[ep["subject"]] = kinds.get(ep["subject"], 0) + 1
    return {"episodes": out, "dropped": dropped, "kinds": kinds}


def _mass_changes(rows: list[dict], platforms: dict[str, str]
                  ) -> tuple[list[dict], list[dict]]:
    """The same-second bursts nothing caused, as one row each, and what is
    left for the per-entity grouping.

    Keyed on the SECOND and the state the entities moved TO, never on a
    window: two lights switched off a few seconds apart are two things
    somebody did, where forty trackers switching to `home` in one second
    is a reload. A burst over mostly the same entities within
    ``MASS_JOIN_S`` joins the row before it, which is what makes
    "unavailable" and "home" twelve seconds later one row.
    """
    buckets: dict[tuple[int, str], dict[str, int]] = {}
    for i, a in enumerate(rows):
        if (a.get("cause") or "unattributed") != "unattributed":
            continue
        key = (int(float(a.get("ts") or 0)), _norm(a.get("state")))
        buckets.setdefault(key, {})[str(a["entity_id"])] = i
    mass = sorted(((k, v) for k, v in buckets.items() if len(v) >= MASS_MIN),
                  key=lambda kv: kv[0][0])
    if not mass:
        return [], rows
    taken: set[int] = set()
    made: list[dict] = []
    for (second, _state), members in mass:
        taken.update(members.values())
        ents = set(members)
        state = str(rows[next(iter(members.values()))].get("state") or "")
        ts = min(float(rows[i].get("ts") or 0) for i in members.values())
        joined = None
        for prev in reversed(made):
            if ts - prev["ended"] > MASS_JOIN_S:
                break
            overlap = len(ents & prev["_ents"])
            if overlap * 2 >= min(len(ents), len(prev["_ents"])):
                joined = prev
                break
        if joined is not None:
            joined["_ents"] |= ents
            joined["ended"] = max(joined["ended"], ts)
            joined["last"] = state
            joined["count"] += len(members)
            joined["states"].append({"ts": ts, "state": state,
                                     "cause": "unattributed", "by_name": "",
                                     "entities": len(members)})
            continue
        made.append({
            "subject": "system", "kind": "mass", "entity_id": "",
            "started": ts, "ended": ts, "count": len(members),
            "first": state, "last": state,
            "states": [{"ts": ts, "state": state, "cause": "unattributed",
                        "by_name": "", "entities": len(members)}],
            "causes": {"unattributed": len(members)},
            "cause": "unattributed", "by_name": "", "_ents": ents,
        })
    for ep in made:
        ents = sorted(ep.pop("_ents"))
        names = {integration_name(platforms.get(e, "")) for e in ents}
        source = names.pop() if len(names) == 1 else ""
        ep["entities"] = ents[:MASS_KEEP]
        ep["devices"] = len(ents)
        ep["integration"] = source
        ep["name"] = (f"{len(ents)} devices"
                      + (f" from {source}" if source else ""))
        ep["open"] = False
        ep["duration_s"] = max(0.0, ep["ended"] - ep["started"])
        ep["states"] = list(reversed(ep["states"]))[:MAX_STATES]
    left = [a for i, a in enumerate(rows) if i not in taken]
    return made, left


def _agree_with_now(newest: list[dict], live: dict[str, dict],
                    now: float | None) -> list[dict]:
    """Make each entity's newest episode agree with the state it is in NOW.

    The logbook can miss a transition — a thermostat going unavailable
    across a restart is the one that was caught — so the newest episode
    can claim a state the entity left hours ago. When the live state
    differs, the episode ends at the live `last_changed` and the live
    state becomes an episode of its own, open, because it is what the
    entity is doing now. Returns the episodes it adds.

    A `last_changed` no later than the episode's own end is a disagreement
    this cannot resolve (the logbook holds a change the state does not),
    so the episode is only marked with what it says now and stops claiming
    to be still going — it is certainly not.
    """
    added: list[dict] = []
    for ep in newest:
        row = live.get(ep["entity_id"])
        if not isinstance(row, dict) or row.get("state") is None:
            continue
        state = str(row.get("state"))
        if _norm(state) == _norm(ep["last"]):
            continue
        ep["live"] = state
        try:
            changed = float(row.get("last_changed") or 0)
        except (TypeError, ValueError):
            changed = 0.0
        if now:
            changed = min(changed, float(now))
        if changed <= ep["ended"]:
            if ep["open"]:
                ep["open"] = False
                ep["duration_s"] = max(0.0, ep["ended"] - ep["started"])
            continue
        ep["open"] = False
        ep["ended"] = changed
        ep["duration_s"] = max(0.0, changed - ep["started"])
        upto = float(now) if now else changed
        added.append({
            "subject": ep["subject"], "entity_id": ep["entity_id"],
            "name": ep["name"], "started": changed, "ended": changed,
            "count": 0, "first": state, "last": state,
            "states": [{"ts": changed, "state": state,
                        "cause": "unattributed", "by_name": ""}],
            "causes": {}, "cause": "unattributed", "by_name": "",
            # Read off the house rather than the logbook — the panel says
            # so, because the change it stands for is the one the logbook
            # did not record.
            "from_live": True, "open": True,
            "duration_s": max(0.0, upto - changed),
        })
    return added


def restart_episodes(lifecycle: list[dict]) -> list[dict]:
    """Home Assistant's own starts and stops, as rows.

    A stop and the start after it are ONE restart: the gap between them is
    how long the house had no Home Assistant, which is the number worth
    having. A start with no stop before it in the window is still a row —
    a power cut leaves no stop behind it, and that is when it matters most.
    """
    out: list[dict] = []
    pending: float | None = None

    def row(started: float, ended: float, first: str, last: str,
            name: str, count: int) -> dict:
        return {
            "subject": "system", "kind": "restart", "entity_id": "",
            "name": name, "started": started, "ended": ended,
            "count": count, "first": first, "last": last,
            "states": [], "causes": {}, "cause": "unattributed",
            "by_name": "", "open": False,
            "duration_s": max(0.0, ended - started),
        }

    for ev in sorted(lifecycle or [], key=lambda e: e.get("ts") or 0):
        ts = float(ev.get("ts") or 0)
        if ev.get("event") == "stopped":
            if pending is not None:
                out.append(row(pending, pending, "stopped", "stopped",
                               "Home Assistant stopped", 1))
            pending = ts
        elif ev.get("event") == "started":
            if pending is not None and ts - pending <= RESTART_PAIR_S:
                out.append(row(pending, ts, "stopped", "started",
                               "Home Assistant restarted", 2))
            else:
                if pending is not None:
                    out.append(row(pending, pending, "stopped", "stopped",
                                   "Home Assistant stopped", 1))
                out.append(row(ts, ts, "started", "started",
                               "Home Assistant started", 1))
            pending = None
    if pending is not None:
        out.append(row(pending, pending, "stopped", "stopped",
                       "Home Assistant stopped", 1))
    return out


def _mark_restarts(episodes: list[dict], restarts: list[dict]) -> int:
    """Mark the rows nothing caused that began around a restart.

    Only `unattributed` rows: an automation that ran at startup has its own
    cause and the restart is not it. The mark is the restart's own time,
    so the panel can say which one when a window holds two.
    """
    marked = 0
    for ep in episodes:
        if ep.get("kind") == "restart" or ep.get("cause") not in (
                "", "unattributed"):
            continue
        for r in restarts:
            lo = r["started"] - RESTART_BEFORE_S
            hi = r["ended"] + RESTART_AFTER_S
            if lo <= ep["started"] <= hi:
                ep["near_restart"] = r["ended"]
                marked += 1
                break
    return marked


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
    "ACTIVE_STATES", "COVER_CLASSES", "DOOR_CLASSES", "INTEGRATION_NAMES",
    "MASS_JOIN_S", "MASS_MIN", "MAX_ROWS", "MAX_STATES", "MOTION_CLASSES",
    "READINGS", "RESTART_AFTER_S", "RESTART_BEFORE_S", "RESTART_PAIR_S",
    "SAFETY_CLASSES", "integration_name", "restart_episodes",
    "SUBJECTS", "SUBJECT_IDS", "SUMMARY_MAX_ROWS", "SUMMARY_MAX_TURNS",
    "SUMMARY_MAX_WORDS", "SUMMARY_MIN_CHARS", "SUMMARY_SYSTEM",
    "SUMMARY_TIMEOUT_S", "away_spans", "domain_of", "group",
    "is_reading", "mark_overrides", "sections", "subject_for",
    "summary_prompt", "within",
]
