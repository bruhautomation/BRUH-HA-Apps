"""What an automation WOULD have done, against history that already happened.

Everything on the capability map above "forecasts" stands on one thing
brAIn could not do: try a change without committing the house to it. A
proposed automation is a guess until somebody enables it and lives with
it for a week, which is exactly the commitment nobody wants to make on a
guess — so the proposals never got made, and the house went on being
programmed by hand.

The shadow runner is the other half. It takes an automation — one brAIn
wrote, or one already in the house — and evaluates its triggers and
conditions against the **recorded past**, reporting when it would have
fired and what it would have done. It calls no service and touches
nothing. "What would this have done last month" becomes a number, in
seconds, before anything is enabled.

**The scope is four trigger kinds, and the refusal is the feature.**
`time`, `state`, `numeric_state` and `template` are the ones the recorder
can reconstruct: a time trigger is arithmetic, and the other three are
answered by state changes the recorder already keeps. A `webhook`, an
`mqtt` message, an `event`, a `device` trigger — none of those is in the
recorder in a form this can replay, and **a partial replay is worse than
no replay**: reporting "this would have fired twice" about an automation
whose webhook fires forty times a day is a confident wrong number that
reads exactly like a right one, and it is the number somebody would
decide on. So an automation carrying *any* unsupported trigger is refused
whole, in as many words, naming the kind.

**Home Assistant 2026.7's purpose-specific triggers are state triggers
with a name**, and they are replayed as the transitions Core documents for
them. `trigger: light.turned_on` with `target: {entity_id: …}` is what the
automation editor writes by default now, and every one of them in
`PURPOSE_TRIGGERS` is built in Core out of `make_entity_target_state_
trigger` / `make_entity_transition_trigger` (or the cover pair) — "the
tracked value became one of these, from something that was not" — over
states the recorder keeps. Refusing them as unrecorded was a sentence that
was not true, and it cost every automation built in the new editor its
replay, its trial and its condition card. The table is copied off Core's
own `<domain>/trigger.py` and `condition.py` rather than inferred from the
names. A target that is an area, a floor, a label or a device is refused
for the reason `would_do` will not expand one: the registry as it was at
the time is not something this has. And a kind brAIn simply does not
have in the table is refused as **not known**, never as **not recorded**
— the second is a claim about Home Assistant and is only true of an
event, a webhook, an MQTT message and the like.

**A template is only replayed when every entity it reads can be
reconstructed.** A template trigger is a Jinja expression over the whole
state machine, and this has a state machine only for the entities it
fetched history for. So the template is parsed for the entities it names,
every one of them has to be in the timeline, and only a named set of HA's
own helpers is allowed (`states`, `is_state`, `state_attr`,
`is_state_attr`, `has_value`, `now`, `as_timestamp`, `float`, `int`).
Anything else — a custom filter, `expand`, `state_translated`, a bare
`states` iteration — is refused by name rather than rendered against a
half-built world.

**`for:` is a promise about a stretch of time**, not an instant, so it is
answered from the timeline rather than from the changing sample: a state
trigger with `for: 00:05:00` fires only where the entity then *stayed*
that way for five minutes, which is a question about the next sample and
not this one.

**Nothing here is persisted and nothing here is a decision.** It answers
"when, and what", and `proposals.py` decides what that is worth. Same
split `baselines.py` keeps from the checks that read it.
"""
from __future__ import annotations

import datetime as dt
import math
import re

# The four the recorder can answer for. Everything else is refused whole.
REPLAYABLE = frozenset({"time", "state", "numeric_state", "template"})

# The kinds whose firing really is not in the recorder: a message, an
# event, a request. Only these may be refused with that sentence; any
# other kind brAIn cannot replay is one it does not KNOW, which is a
# claim about brAIn rather than about Home Assistant.
NOT_RECORDED = frozenset({"webhook", "mqtt", "event", "tag", "conversation",
                          "persistent_notification", "homeassistant"})

# Core's own names for the states these read.
_UNAVAILABLE = frozenset({"unavailable", "unknown"})
_HVAC_ON = frozenset({"auto", "cool", "dry", "fan_only", "heat", "heat_cool"})
_ARMED = frozenset({"armed_away", "armed_custom_bypass", "armed_home",
                    "armed_night", "armed_vacation"})
_MEDIA_ON = frozenset({"buffering", "idle", "on", "paused", "playing"})
_COVER_KINDS = ("awning", "blind", "curtain", "shade", "shutter")


def _on_off(domain: str) -> dict:
    return {f"{domain}.turned_on": {"to": {"on"}},
            f"{domain}.turned_off": {"to": {"off"}}}


# HA 2026.7's purpose-specific triggers, as the transition each one is
# built from in Core (`homeassistant/components/<domain>/trigger.py`).
#   to      — the tracked value it fires on reaching
#   from    — when present, the value it has to come FROM
#             (`make_entity_transition_trigger`); absent, it may come from
#             anything that is not already in `to`
#             (`make_entity_target_state_trigger`)
#   attr    — the tracked value is this attribute rather than the state
#   cover   — a cover entity is read as `open`/`closed` (Core reads its
#             `is_closed` attribute); a binary sensor as `on`/`off`
PURPOSE_TRIGGERS: dict[str, dict] = {
    **_on_off("light"), **_on_off("switch"), **_on_off("fan"),
    "occupancy.detected": {"to": {"on"}},
    "occupancy.cleared": {"to": {"off"}},
    "motion.detected": {"to": {"on"}},
    "motion.cleared": {"to": {"off"}},
    "lock.locked": {"to": {"locked"}},
    "lock.unlocked": {"to": {"unlocked"}},
    "lock.jammed": {"to": {"jammed"}},
    "lock.opened": {"to": {"open"}},
    "door.opened": {"to": {"on", "open"}, "cover": True},
    "door.closed": {"to": {"off", "closed"}, "cover": True},
    "window.opened": {"to": {"on", "open"}, "cover": True},
    "window.closed": {"to": {"off", "closed"}, "cover": True},
    **{f"cover.{k}_opened": {"to": {"open"}, "cover": True}
       for k in _COVER_KINDS},
    **{f"cover.{k}_closed": {"to": {"closed"}, "cover": True}
       for k in _COVER_KINDS},
    "climate.turned_off": {"to": {"off"}},
    "climate.turned_on": {"from": {"off"}, "to": set(_HVAC_ON)},
    "climate.started_heating": {"to": {"heating"}, "attr": "hvac_action"},
    "climate.started_cooling": {"to": {"cooling"}, "attr": "hvac_action"},
    "climate.started_drying": {"to": {"drying"}, "attr": "hvac_action"},
    "media_player.started_playing": {
        "from": {"idle", "off", "on", "paused"}, "to": {"buffering", "playing"}},
    "media_player.stopped_playing": {
        "from": {"buffering", "paused", "playing"}, "to": {"idle", "off", "on"}},
    "media_player.paused_playing": {
        "from": {"buffering", "playing"}, "to": {"paused"}},
    "media_player.turned_off": {"from": set(_MEDIA_ON), "to": {"off"}},
    "media_player.turned_on": {"from": {"off"}, "to": set(_MEDIA_ON)},
    "alarm_control_panel.armed": {
        "from": {"arming", "disarmed", "disarming", "pending", "triggered"},
        "to": set(_ARMED)},
    **{f"alarm_control_panel.{s}": {"to": {s}} for s in (
        "armed_away", "armed_home", "armed_night", "armed_vacation",
        "disarmed", "triggered")},
}

# And the conditions (`<domain>/condition.py`): `make_entity_state_condition`
# — the tracked value is one of these — with `behavior` any/all over the
# targeted entities that are not unavailable.
PURPOSE_CONDITIONS: dict[str, dict] = {
    **{f"{d}.is_on": {"states": {"on"}} for d in ("light", "switch", "fan")},
    **{f"{d}.is_off": {"states": {"off"}} for d in ("light", "switch", "fan")},
    "occupancy.is_detected": {"states": {"on"}},
    "occupancy.is_not_detected": {"states": {"off"}},
    "motion.is_detected": {"states": {"on"}},
    "motion.is_not_detected": {"states": {"off"}},
    "lock.is_locked": {"states": {"locked"}},
    "lock.is_unlocked": {"states": {"unlocked"}},
    "lock.is_jammed": {"states": {"jammed"}},
    "lock.is_open": {"states": {"open"}},
    "door.is_open": {"states": {"on", "open"}, "cover": True},
    "door.is_closed": {"states": {"off", "closed"}, "cover": True},
    "window.is_open": {"states": {"on", "open"}, "cover": True},
    "window.is_closed": {"states": {"off", "closed"}, "cover": True},
    **{f"cover.{k}_is_open": {"states": {"open"}, "cover": True}
       for k in _COVER_KINDS},
    **{f"cover.{k}_is_closed": {"states": {"closed"}, "cover": True}
       for k in _COVER_KINDS},
    "climate.is_off": {"states": {"off"}},
    "climate.is_on": {"states": set(_HVAC_ON)},
    "climate.is_heating": {"states": {"heating"}, "attr": "hvac_action"},
    "climate.is_cooling": {"states": {"cooling"}, "attr": "hvac_action"},
    "climate.is_drying": {"states": {"drying"}, "attr": "hvac_action"},
    "media_player.is_on": {"states": set(_MEDIA_ON)},
    "media_player.is_off": {"states": {"off"}},
    "media_player.is_playing": {"states": {"playing"}},
    "media_player.is_paused": {"states": {"paused"}},
    "media_player.is_not_playing": {
        "states": {"buffering", "idle", "off", "on", "paused"}},
    "alarm_control_panel.is_armed": {"states": set(_ARMED)},
    **{f"alarm_control_panel.is_{s}": {"states": {s}} for s in (
        "armed_away", "armed_home", "armed_night", "armed_vacation",
        "disarmed", "triggered")},
}

# Core renamed two `behavior` words and still reads the old ones
# (`helpers/trigger/entity_trigger.py`, `_backwards_compatible_behavior`).
_BEHAVIOR_ALIASES = {"any": "each", "last": "all"}

# What a template may call. A template that reaches past these is refused
# by name: rendering it against a state machine holding only the entities
# we happened to fetch is how a replay invents an answer.
TEMPLATE_ALLOWED = frozenset({
    "states", "is_state", "state_attr", "is_state_attr", "has_value",
    "now", "utcnow", "as_timestamp", "float", "int", "round", "abs",
    "min", "max", "not", "and", "or", "if", "else", "is", "in", "none",
    "true", "false", "defined", "string", "number",
})

# How far back a replay may reach. The recorder's default purge is ten
# days and most houses leave it there, so a window past this quietly
# becomes a window over nothing.
MAX_WINDOW_DAYS = 30
# A replay that would report more firings than this is reporting a
# trigger that is not really a trigger (`state` with no `to:` on a sensor
# that updates every ten seconds), and the number is the sampling rather
# than the automation.
MAX_FIRINGS = 500
# Entities per replay. A template naming forty is a template this cannot
# honestly reconstruct anyway.
MAX_ENTITIES = 25

_ENTITY_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")
_JINJA_NAME_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
_FILTER_RE = re.compile(r"\|\s*([a-zA-Z_][a-zA-Z0-9_]*)")


class Refused(Exception):
    """This automation cannot be replayed, and the message says why.

    An exception rather than a `None`: every caller has to say the reason
    out loud, and a refusal that can be ignored by not reading a return
    value is a refusal that becomes a silent partial answer.
    """


# ---------------------------------------------------------------------------
# Reading the automation
# ---------------------------------------------------------------------------

def triggers_of(config: dict) -> list[dict]:
    """The trigger blocks, under either key HA accepts."""
    raw = config.get("triggers")
    if raw is None:
        raw = config.get("trigger")
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    return [t for t in raw if isinstance(t, dict)]


def kind_of(block: dict) -> str:
    """`platform:` before 2024.10, `trigger:` after. Both still work."""
    return str(block.get("platform") or block.get("trigger") or "").lower()


def check_replayable(config: dict) -> list[dict]:
    """The triggers, or `Refused` naming the first kind that is not.

    Refused **whole**, never trimmed to the replayable subset: an
    automation with a state trigger and a webhook trigger fires for both,
    and reporting only the first is a number that is wrong in the
    direction of looking reasonable.
    """
    blocks = triggers_of(config)
    if not blocks:
        raise Refused("this automation has no triggers to replay")
    for block in blocks:
        kind = kind_of(block)
        if not kind:
            raise Refused("a trigger block does not say what kind it is")
        if kind in PURPOSE_TRIGGERS:
            target_entities(block, f"a `{kind}` trigger")
            continue
        if kind in REPLAYABLE:
            continue
        if kind in NOT_RECORDED:
            raise Refused(
                f"a `{kind}` trigger cannot be replayed — the recorder does "
                "not keep what it fires on, so brAIn would be guessing at "
                "how often it fired. Replay covers time, state, "
                "numeric_state and template triggers.")
        raise Refused(
            f"brAIn does not know how to replay a `{kind}` trigger yet, so "
            "it would be guessing at how often it fired. Replay covers "
            "time, state, numeric_state and template triggers, and Home "
            "Assistant's own state triggers such as `light.turned_on`.")
    return blocks


def target_entities(block: dict, what: str) -> list[str]:
    """The entity ids a purpose-specific trigger or condition targets.

    `Refused` for an area, a floor, a label or a device under `target:`:
    which entities those were at the time is a question for the registry
    as it was then, and a guess is a wrong count that reads like a right
    one — `would_do`'s reason for not expanding one, and `automation_
    writer`'s for refusing one. A target naming nothing is refused too,
    because "it never fired" about a trigger watching nothing is a
    confident zero about nothing.
    """
    target = block.get("target")
    target = target if isinstance(target, dict) else {}
    for scope in ("area_id", "floor_id", "label_id", "device_id"):
        if target.get(scope):
            raise Refused(
                f"{what} watches a whole {scope[:-3]} — which entities that "
                "was at the time is the registry's to say, and brAIn would "
                "be guessing. Name the entities in the target to replay it.")
    raw = target.get("entity_id")
    ids = [raw] if isinstance(raw, str) else list(raw or [])
    ids = [str(e).strip() for e in ids if isinstance(e, str) and e.strip()]
    if not ids:
        raise Refused(f"{what} names no entity, so there is nothing in "
                      "history to replay it against")
    return ids


def template_entities(text: str) -> set[str]:
    """Every entity id a template names."""
    return {f"{d}.{o}" for d, o in _ENTITY_RE.findall(str(text or ""))}


def check_template(text: str) -> None:
    """`Refused` when a template reaches past what can be reconstructed."""
    body = str(text or "")
    called = set(_JINJA_NAME_RE.findall(body)) | set(_FILTER_RE.findall(body))
    unknown = sorted(n for n in called if n not in TEMPLATE_ALLOWED)
    if unknown:
        raise Refused(
            "this template uses " + ", ".join(f"`{n}`" for n in unknown[:4])
            + " — brAIn replays a template against the entities it can "
            "rebuild from history, and cannot rebuild what those read.")
    if not template_entities(body):
        raise Refused(
            "this template names no entity, so there is nothing in history "
            "to replay it against")


def entities_watched(config: dict) -> set[str]:
    """Every entity the triggers and conditions read."""
    out: set[str] = set()
    for block in triggers_of(config):
        kind = kind_of(block)
        if kind in ("state", "numeric_state"):
            raw = block.get("entity_id")
            for eid in ([raw] if isinstance(raw, str) else list(raw or [])):
                if isinstance(eid, str):
                    out.add(eid)
        elif kind == "template":
            out |= template_entities(block.get("value_template"))
        elif kind in PURPOSE_TRIGGERS:
            out |= set(_target_ids(block))
    for cond in _conditions_of(config):
        out |= _condition_entities(cond)
    return out


def _target_ids(block: dict) -> list[str]:
    """`target: {entity_id}` as a list, refusing nothing — the fetch half.

    `entities_watched` runs before `check_replayable` and must not raise,
    so this reads what is there and leaves the refusals to the replay.
    """
    target = block.get("target")
    raw = target.get("entity_id") if isinstance(target, dict) else None
    ids = [raw] if isinstance(raw, str) else list(raw or [])
    return [str(e).strip() for e in ids if isinstance(e, str) and e.strip()]


def _ensure_list(raw) -> list[dict]:
    """`cv.ensure_list`, which is what Home Assistant applies to a nested
    `conditions:`.

    A single mapping is a list of one everywhere HA reads a condition
    block, so a reader that only understands a list answers an `and`/`not`
    written that way with "no conditions at all" — which is `True` at
    every instant, silently, in a module whose whole promise is that it
    never returns a plausible wrong number.
    """
    if isinstance(raw, dict):
        raw = [raw]
    return [c for c in (raw or []) if isinstance(c, dict)]


def _conditions_of(config: dict) -> list[dict]:
    raw = config.get("conditions")
    if raw is None:
        raw = config.get("condition")
    return _ensure_list(raw)


def _condition_entities(cond: dict) -> set[str]:
    out: set[str] = set()
    raw = cond.get("entity_id")
    for eid in ([raw] if isinstance(raw, str) else list(raw or [])):
        if isinstance(eid, str):
            out.add(eid)
    if cond.get("value_template"):
        out |= template_entities(cond["value_template"])
    out |= set(_target_ids(cond))
    for key in ("conditions", "condition"):
        nested = cond.get(key)
        if isinstance(nested, (list, dict)):
            for c in _ensure_list(nested):
                out |= _condition_entities(c)
    return out


async def fetch_history(session, entity_ids: list[str], start: float,
                        end: float) -> dict:
    """Raw state changes for a replay. NOT `ha_data.get_history`.

    That one downsamples numeric series into hourly buckets, drops
    `unavailable`/`unknown`, and caps how many changes it keeps — all
    correct for handing a model a summary, and all fatal here. A replay
    counts **edges**: an hourly bucket has thrown away the moment a
    sensor crossed a threshold, so the count would come back plausible
    and wrong, which is the one shape of answer this module exists to
    refuse.

    Attributes are requested rather than suppressed, because a template
    may call `state_attr`. That costs bytes, and the bound on it is
    `MAX_ENTITIES` plus the window cap — a replay is something a person
    pressed, not a poll.
    """
    import ha_data  # noqa: PLC0415 — panel-local, and this module is
                    # imported by the tests without it

    if not entity_ids:
        return {}
    ids = entity_ids[:MAX_ENTITIES]
    begin = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    finish = dt.datetime.fromtimestamp(end, dt.timezone.utc)
    # The ids came out of an automation config that arrived in an HTTP
    # body, so they may not be ids at all. `ha_data.history_params`
    # checks them and hands the query to aiohttp to encode; pasting them
    # into the URL after a `?` is what made this a partial SSRF, and
    # `_rest_get`'s own docstring had already said so.
    raw = await ha_data._rest_get(
        session, ha_data.history_path(begin), timeout=90,
        params=ha_data.history_params(ids, finish))
    out: dict[str, list] = {}
    for series in raw or []:
        if not series:
            continue
        eid = series[0].get("entity_id") or ""
        if eid:
            out[eid] = [p for p in series if isinstance(p, dict)]
    return out


# ---------------------------------------------------------------------------
# The timeline
# ---------------------------------------------------------------------------

def build_timeline(history: dict) -> dict[str, list[tuple[float, str, dict]]]:
    """`{entity_id: [(when, state, attributes), ...]}`, oldest first.

    Home Assistant's history endpoint hands back one list per entity of
    the states it *changed to*, which is exactly the shape a replay
    wants: an automation's state trigger fires on a change, and a
    recorder that stored every sample would answer a different question.
    """
    from checks._util import parse_ts  # noqa: PLC0415 — panel-local

    out: dict[str, list[tuple[float, str, dict]]] = {}
    for eid, rows in (history or {}).items():
        points = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            when = parse_ts(row.get("last_changed") or row.get("last_updated"))
            if when is None:
                continue
            points.append((when, str(row.get("state") or ""),
                           row.get("attributes") or {}))
        points.sort(key=lambda p: p[0])
        out[eid] = points
    return out


def state_at(timeline: dict, entity_id: str, when: float) -> tuple[str, dict]:
    """What an entity read at an instant, from what was recorded before it.

    `("", {})` when the timeline starts after that instant — which is a
    real answer and not "unknown": the recorder genuinely does not say,
    and every caller has to treat it as "cannot answer" rather than as a
    state that failed to match.
    """
    points = timeline.get(entity_id) or []
    found = ("", {})
    for ts, state, attrs in points:
        if ts > when:
            break
        found = (state, attrs)
    return found


def _num(value) -> float | None:
    """A state as a number, or `None` when it is not one.

    `math.isfinite` rather than the `f != f` NaN idiom CodeQL reads as a
    comparison of identical values — it was right to ask, and the wider
    guard is the more correct one anyway: `float("inf")` parses happily,
    and a reading of infinity satisfies `above:` for ever. A state that
    is not a finite number is not a number this can replay against.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# When it would have fired
# ---------------------------------------------------------------------------

def _match(spec, value: str) -> bool:
    """Whether a `to:`/`from:` spec matches a state. Absent matches all."""
    if spec is None:
        return True
    if isinstance(spec, str):
        return spec == value
    return value in [str(s) for s in spec]


def _held_for(points, index: int, seconds: float, until: float,
              still=None) -> bool:
    """Whether the state at `index` then lasted `seconds`.

    A `for:` is a promise about a stretch, so it is answered from the
    samples AFTER this one rather than from this one — and a stretch still
    running when the window ends counts only if it has already been long
    enough, never on the assumption that it continued.

    The stretch ends at the first later sample that breaks it, which is
    `still(state, attrs)` going false — by default, the state no longer
    being the one it changed to. NOT simply the next sample: the recorder
    keeps a row for an attribute-only update (a light's brightness, a
    thermostat's action), and Home Assistant does not cancel a `for:`
    over one, so ending the stretch there reported a light that stayed on
    for an hour as one that stayed on for the half hour before somebody
    dimmed it. A `numeric_state` stretch is "still inside the range",
    which a sensor reporting every minute crosses no boundary of.
    """
    started, held = points[index][0], points[index][1]
    if still is None:
        def still(state, _attrs):
            return state == held
    ends = until
    for ts, state, attrs in points[index + 1:]:
        if not still(state, attrs):
            ends = ts
            break
    return (ends - started) >= seconds


def _seconds(spec) -> float:
    """A HA duration — `"00:05:00"`, `{minutes: 5}`, or a number."""
    if spec is None:
        return 0.0
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, dict):
        return (float(spec.get("hours") or 0) * 3600
                + float(spec.get("minutes") or 0) * 60
                + float(spec.get("seconds") or 0))
    parts = str(spec).split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def _state_firings(block: dict, timeline: dict, start: float,
                   end: float) -> list[float]:
    """Instants a `state` trigger would have fired."""
    raw = block.get("entity_id")
    ids = [raw] if isinstance(raw, str) else list(raw or [])
    hold = _seconds(block.get("for"))
    out = []
    for eid in ids:
        points = timeline.get(str(eid)) or []
        for i, (ts, state, _attrs) in enumerate(points):
            if not (start <= ts <= end) or i == 0:
                continue
            was = points[i - 1][1]
            if was == state:
                continue                      # an attribute-only update
            if not _match(block.get("from"), was):
                continue
            if not _match(block.get("to"), state):
                continue
            if hold and not _held_for(points, i, hold, end):
                continue
            out.append(ts + hold)
    return out


def _numeric_firings(block: dict, timeline: dict, start: float,
                     end: float) -> list[float]:
    """Instants a `numeric_state` trigger would have crossed its bound.

    A crossing, never a level: HA fires when a value moves *into* the
    range and not for every sample it spends inside one, so a replay that
    reported the level would report a reading rather than a trigger.
    """
    raw = block.get("entity_id")
    ids = [raw] if isinstance(raw, str) else list(raw or [])
    above = _num(block.get("above"))
    below = _num(block.get("below"))
    if above is None and below is None:
        raise Refused(
            "a numeric_state trigger with neither `above` nor `below` has "
            "nothing to cross")
    hold = _seconds(block.get("for"))

    def inside(value: float | None) -> bool:
        if value is None:
            return False
        if above is not None and not value > above:
            return False
        return not (below is not None and not value < below)

    out = []
    for eid in ids:
        points = timeline.get(str(eid)) or []
        for i, (ts, state, _attrs) in enumerate(points):
            if not (start <= ts <= end) or i == 0:
                continue
            if not inside(_num(state)) or inside(_num(points[i - 1][1])):
                continue
            if hold and not _held_for(points, i, hold, end,
                                      lambda st, _a: inside(_num(st))):
                continue
            out.append(ts + hold)
    return out


def _tracked(spec: dict, entity_id: str, state: str, attrs: dict):
    """The value a purpose-specific trigger or condition reads.

    The state itself, an attribute (`hvac_action` for `climate.started_
    heating`), or — for a cover under a door, window or cover kind —
    `open`/`closed`, which Core reads off `is_closed` and which an older
    history row without that attribute still says through its state.
    """
    if spec.get("attr"):
        return (attrs or {}).get(spec["attr"])
    if spec.get("cover") and entity_id.startswith("cover."):
        closed = (attrs or {}).get("is_closed")
        if isinstance(closed, bool):
            return "closed" if closed else "open"
        if state == "closed":
            return "closed"
        if state in ("open", "opening", "closing"):
            return "open"
        return None
    return state


def _behavior(block: dict) -> tuple[str, float]:
    options = block.get("options")
    options = options if isinstance(options, dict) else {}
    behavior = str(options.get("behavior") or "each").lower()
    behavior = _BEHAVIOR_ALIASES.get(behavior, behavior)
    hold = _seconds(options.get("for", block.get("for")))
    return behavior, hold


def _purpose_firings(block: dict, timeline: dict, start: float,
                     end: float) -> list[float]:
    """Instants a purpose-specific trigger would have fired.

    Core's own rule (`EntityTargetStateTriggerBase` and its transition
    sibling): neither end of the change may be `unavailable`/`unknown`,
    the tracked value must reach one of `to`, and it must come from a
    value that is not already there — or, where the trigger names a
    `from`, from one of those. `behavior: each` fires per entity; `first`
    fires when exactly one targeted entity has got there and `all` when
    every one that is reporting has, which is read off the timeline at
    the instant of the change.
    """
    kind = kind_of(block)
    spec = PURPOSE_TRIGGERS[kind]
    ids = target_entities(block, f"a `{kind}` trigger")
    behavior, hold = _behavior(block)
    if behavior not in ("each", "first", "all"):
        raise Refused(f"`behavior: {behavior}` is not one brAIn knows how "
                      "to replay")
    if behavior != "each" and hold and len(ids) > 1:
        # Core keeps one timer for the whole target there, cancelled the
        # moment the combined state stops holding — a stretch about every
        # entity at once, which a per-entity hold would not answer.
        raise Refused(f"`behavior: {behavior}` with `for:` over several "
                      "entities is a stretch about all of them at once, "
                      "which brAIn does not replay yet")
    for eid in ids:
        _require_history(timeline, eid, f"this `{kind}` trigger watches")

    def valid(eid: str, state: str, attrs: dict) -> bool:
        return _tracked(spec, eid, state, attrs) in spec["to"]

    out = []
    for eid in ids:
        points = timeline.get(eid) or []
        for i, (ts, state, attrs) in enumerate(points):
            if not (start <= ts <= end) or i == 0:
                continue
            was, was_attrs = points[i - 1][1], points[i - 1][2]
            if state in _UNAVAILABLE or was in _UNAVAILABLE:
                continue
            if not valid(eid, state, attrs):
                continue
            before = _tracked(spec, eid, was, was_attrs)
            if before is None or before == _tracked(spec, eid, state, attrs):
                continue
            if "from" in spec:
                if before not in spec["from"]:
                    continue
            elif before in spec["to"]:
                continue
            if behavior != "each":
                world = [state_at(timeline, other, ts) for other in ids]
                reporting = [(o, st, at) for o, (st, at) in zip(ids, world)
                             if st not in _UNAVAILABLE and st != ""]
                matches = sum(1 for o, st, at in reporting
                              if valid(o, st, at))
                if behavior == "first" and matches != 1:
                    continue
                if behavior == "all" and matches != len(reporting):
                    continue
            if hold and not _held_for(
                    points, i, hold, end,
                    lambda st, at, e=eid: (st not in _UNAVAILABLE
                                           and valid(e, st, at))):
                continue
            out.append(ts + hold)
    return out


def _time_firings(block: dict, start: float, end: float, tz) -> list[float]:
    """Every occurrence of a `time` trigger's `at:` inside the window."""
    raw = block.get("at")
    ats = [raw] if isinstance(raw, (str, int, float)) else list(raw or [])
    out = []
    for at in ats:
        text = str(at)
        parts = text.split(":")
        try:
            hour, minute = int(parts[0]), int(parts[1])
            second = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            raise Refused(
                f"`at: {text}` is not a plain time of day — a time trigger "
                "on a sensor or an entity is resolved by Home Assistant at "
                "run time, which history does not record") from None
        day = dt.datetime.fromtimestamp(start, tz).replace(
            hour=0, minute=0, second=0, microsecond=0)
        last = dt.datetime.fromtimestamp(end, tz)
        while day <= last:
            fire = day.replace(hour=hour, minute=minute, second=second)
            ts = fire.timestamp()
            if start <= ts <= end:
                out.append(ts)
            day += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Templates, against the world as it was
# ---------------------------------------------------------------------------

def render_template(text: str, timeline: dict, when: float) -> bool:
    """Whether a template was truthy at `when`, over the rebuilt world.

    `Refused` when the template reaches past `TEMPLATE_ALLOWED`, and
    `Refused` when any entity it names has no history before that
    instant: a template asking about an entity the recorder cannot place
    is a template this would be answering from a blank, and a blank reads
    as `unknown`, which reads as `false`, which is a confident no.
    """
    body = str(text or "")
    # The allow-list runs HERE, not only in `check_replayable`. It was a
    # separate earlier pass, which means a template only ever reached the
    # sandbox because a caller had remembered to validate it first — the
    # same shape as asking `protected_entities` anywhere but the
    # chokepoint. This function renders a Jinja string that arrived in an
    # HTTP body, so the check belongs on the path that renders it, and a
    # second caller cannot be added without it. Validating twice on the
    # replay path costs one regex sweep of a short string.
    check_template(body)
    names = template_entities(body)
    world = {}
    for eid in sorted(names):
        _require_history(timeline, eid, "this template reads")
        world[eid] = state_at(timeline, eid, when)

    def _states(eid: str = "") -> str:
        return world.get(eid, ("", {}))[0]

    def _is_state(eid: str, value) -> bool:
        got = _states(eid)
        return got in ([value] if isinstance(value, str) else list(value or []))

    def _state_attr(eid: str, attr: str):
        return world.get(eid, ("", {}))[1].get(attr)

    env = {
        "states": _states,
        "is_state": _is_state,
        "state_attr": _state_attr,
        "is_state_attr": lambda e, a, v: _state_attr(e, a) == v,
        "has_value": lambda e: _states(e) not in ("", "unknown", "unavailable"),
        "now": lambda: dt.datetime.fromtimestamp(when, dt.timezone.utc),
        "utcnow": lambda: dt.datetime.fromtimestamp(when, dt.timezone.utc),
        "as_timestamp": lambda d: d.timestamp() if hasattr(d, "timestamp")
        else _num(d),
        "float": lambda v, d=0.0: (_num(v) if _num(v) is not None else d),
        "int": lambda v, d=0: int(_num(v)) if _num(v) is not None else d,
    }
    try:
        from jinja2.sandbox import SandboxedEnvironment  # noqa: PLC0415
    except ImportError:  # pragma: no cover — see the note below
        # This branch shipped with a comment claiming "the image ships
        # jinja2", and the Dockerfile did not install it. So every
        # template trigger refused on every real install while three
        # tests passed on a laptop that happened to have Jinja — the
        # comment was the only thing asserting it, and a comment cannot
        # fail. `py3-jinja2` is in the image now, `jinja2` is in the
        # test requirements, and `test_the_image_ships_what_a_template
        # _needs` fails if either goes.
        raise Refused("templates cannot be replayed without Jinja") from None
    # `autoescape=True` on a renderer whose output never reaches a browser
    # looks like cargo cult, and CodeQL rates the default critical for a
    # reason worth honouring rather than suppressing: this is a sandbox
    # evaluating a string somebody wrote in their own automations, and the
    # day its output is put on a page is the day the missing escape
    # matters. It cannot change the verdict here — the result is compared
    # against a fixed set of words — so the safe setting is free.
    env_jinja = SandboxedEnvironment(autoescape=True)
    try:
        rendered = env_jinja.from_string(body).render(**env)
    except Exception as exc:  # noqa: BLE001 — a template that will not render
        # against the rebuilt world is refused, never read as false.
        raise Refused(f"this template would not render: {exc}"[:160]) from None
    return str(rendered).strip().lower() in ("true", "on", "yes", "1")


def _template_firings(block: dict, timeline: dict, start: float,
                      end: float) -> list[float]:
    """Instants a template trigger would have gone false → true.

    An **edge**, like Home Assistant's own: a template trigger fires when
    the result becomes true, not for every moment it stays true, so the
    sample instants are every recorded change to any entity it reads.
    """
    body = block.get("value_template")
    check_template(body)
    names = sorted(template_entities(body))
    # Checked here rather than left to `render_template`, which is only
    # reached once there is a sample instant to render at. An entity with
    # no recorded history contributes none, so the loop below would never
    # run and this would return "it never fired" — a confident zero about
    # an automation nobody can see, which is the exact failure the
    # replay scope exists to prevent.
    for eid in names:
        _require_history(timeline, eid, "this template reads")
    instants = sorted({ts for eid in names
                       for ts, _s, _a in (timeline.get(eid) or [])
                       if start <= ts <= end})
    hold = _seconds(block.get("for"))
    out, was = [], False
    for ts in instants:
        now_true = render_template(body, timeline, ts)
        if now_true and not was:
            out.append(ts + hold)
        was = now_true
    return out


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

def _require_history(timeline: dict, entity_id: str, why: str) -> None:
    """`Refused` unless the recorder can place this entity at all.

    An entity absent from the timeline was never fetched or never
    recorded, and reading it as `""` makes every comparison against it
    quietly false — which turns "brAIn cannot answer" into "the condition
    did not hold", and that is a wrong number wearing a right one's
    clothes.
    """
    if not (timeline.get(entity_id) or []):
        raise Refused(
            f"{why} `{entity_id}`, which brAIn has no recorded history for "
            "over this window")


def passes(cond: dict, timeline: dict, when: float, tz) -> bool:
    """Whether one condition held at an instant."""
    kind = str(cond.get("condition") or "").lower()
    if kind in ("and", "or", "not"):
        inner = _ensure_list(cond.get("conditions"))
        results = [passes(c, timeline, when, tz) for c in inner]
        if kind == "and":
            return all(results)
        if kind == "or":
            return any(results)
        return not any(results)
    if kind == "state":
        raw = cond.get("entity_id")
        ids = [raw] if isinstance(raw, str) else list(raw or [])
        for e in ids:
            _require_history(timeline, str(e), "this condition reads")
        return all(_match(cond.get("state"), state_at(timeline, str(e), when)[0])
                   for e in ids)
    if kind == "numeric_state":
        raw = cond.get("entity_id")
        ids = [raw] if isinstance(raw, str) else list(raw or [])
        above, below = _num(cond.get("above")), _num(cond.get("below"))
        for e in ids:
            _require_history(timeline, str(e), "this condition reads")
            value = _num(state_at(timeline, str(e), when)[0])
            if value is None:
                return False
            if above is not None and not value > above:
                return False
            if below is not None and not value < below:
                return False
        return True
    if kind == "template":
        return render_template(cond.get("value_template"), timeline, when)
    if kind == "time":
        local = dt.datetime.fromtimestamp(when, tz)
        after, before = cond.get("after"), cond.get("before")
        minute = local.hour * 60 + local.minute

        def _minutes(spec) -> int:
            # `_time_firings` already refuses an `at:` naming an entity
            # and says why; this half raised `ValueError` out of `int()`
            # instead, which reaches the Replay button as a 500 about
            # nothing somebody can act on. Same claim, same sentence.
            parts = str(spec).split(":")
            try:
                return (int(parts[0]) * 60
                        + int(parts[1] if len(parts) > 1 else 0))
            except ValueError:
                raise Refused(
                    f"`{spec}` is not a plain time of day — a time "
                    "condition on a sensor or a helper is resolved by Home "
                    "Assistant when it runs, which history does not record"
                ) from None

        # **A time condition wraps midnight**, and this one did not.
        # Home Assistant's own `condition.time` reads `after > before` as
        # "from tonight until tomorrow morning" — 22:00 to 01:00 is a real
        # bedtime and the commonest window anybody writes one for. Testing
        # the two bounds separately answers `False` at every instant of
        # such a window, which is not a slightly wrong replay: a
        # `not`-wrapped one then passes at every instant instead, so a
        # proposal that stands an automation down between ten and one
        # would report having changed nothing at all.
        start = None if after is None else _minutes(after)
        end = None if before is None else _minutes(before)
        if start is not None and end is not None and start > end:
            if not (minute >= start or minute < end):
                return False
        else:
            if start is not None and minute < start:
                return False
            if end is not None and minute >= end:
                return False
        weekdays = cond.get("weekday")
        if weekdays:
            names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            want = [weekdays] if isinstance(weekdays, str) else list(weekdays)
            if names[local.weekday()] not in [str(w)[:3].lower() for w in want]:
                return False
        return True
    if kind in PURPOSE_CONDITIONS:
        return _purpose_passes(kind, cond, timeline, when)
    raise Refused(
        f"a `{kind or 'nameless'}` condition cannot be replayed — brAIn "
        "would have to guess whether it held, and a guessed condition "
        "silently changes the count")


def _purpose_passes(kind: str, cond: dict, timeline: dict,
                    when: float) -> bool:
    """A purpose-specific condition at an instant (`EntityConditionBase`).

    `behavior: any` (the default) or `all` over the targeted entities
    that are reporting — Core leaves an `unavailable`/`unknown` one out of
    both counts rather than reading it as a no. A `for:` is refused: it
    is a stretch Core measures from when the value last became valid,
    which is an answer about history before the instant rather than at it.
    """
    spec = PURPOSE_CONDITIONS[kind]
    ids = target_entities(cond, f"a `{kind}` condition")
    options = cond.get("options")
    options = options if isinstance(options, dict) else {}
    behavior = str(options.get("behavior") or "any").lower()
    if behavior not in ("any", "all"):
        raise Refused(f"`behavior: {behavior}` is not one brAIn knows how "
                      "to replay")
    if _seconds(options.get("for", cond.get("for"))):
        raise Refused(f"a `{kind}` condition with `for:` is a stretch of "
                      "history, which brAIn does not replay yet")
    seen = []
    for eid in ids:
        _require_history(timeline, eid, "this condition reads")
        state, attrs = state_at(timeline, eid, when)
        if state in _UNAVAILABLE or state == "":
            continue
        seen.append(_tracked(spec, eid, state, attrs) in spec["states"])
    return all(seen) if behavior == "all" else any(seen)


# ---------------------------------------------------------------------------
# What it would have done
# ---------------------------------------------------------------------------

def would_do(config: dict) -> list[dict]:
    """The service calls an automation's actions would have made.

    An **area or device target is recorded and deliberately not
    resolved**, exactly as `actions.py` refuses to resolve one: expanding
    it needs the registries as they were at the time, and a wrong
    expansion would tell somebody a proposal touches lights it does not.
    """
    raw = config.get("actions")
    if raw is None:
        raw = config.get("action")
    out: list[dict] = []
    _walk_actions(raw, out, 0)
    return out


# The keys a Home Assistant action can hide more actions behind. A
# `choose` used to be skipped with the delays and the waits, which meant
# `_protected_refusal` — whose whole job is to read what an automation
# would DO — saw nothing at all in one and passed it vacuously. Nothing
# reached that until a schedule was written as four branches of a
# `choose`, and a check that answers "no service calls" about an
# automation full of them is not a check.
_ACTION_KEYS = ("sequence", "then", "else", "default", "actions")
_MAX_ACTION_DEPTH = 6


# Where an entity id can be written on one action. `target:` is the
# modern spelling and `entity_id:` at the top of the step is the older
# one — and `data: {entity_id: ...}` is the oldest of the three, still
# honoured by every entity service and still what most automations
# written before 2021 say. Reading only the first two is how a lock
# reached that way is a lock `_protected_refusal` cannot see.
_TARGET_KEYS = ("entity_id", "area_id", "device_id", "label_id", "floor_id")


def _ids(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or [])
            if isinstance(v, (str, int)) and str(v).strip()]


def _call(step: dict, service) -> dict:
    """One service call, with every way its targets can be spelled.

    A **scope** — an area, a device, a label or a floor — is recorded and
    deliberately not resolved: expanding one needs the registries as they
    were at the time, and `automation_writer` refuses outright rather
    than guess. All four are reported, because a scope this does not
    mention is a scope nothing downstream can refuse.
    """
    target = step.get("target")
    target = target if isinstance(target, dict) else {}
    data = step.get("data")
    data = data if isinstance(data, dict) else {}

    entities: list[str] = []
    for source in (step, target, data):
        for eid in _ids(source.get("entity_id")):
            if eid not in entities:
                entities.append(eid)
    call = {"service": str(service), "entity_id": entities}
    for key in _TARGET_KEYS[1:]:
        call[key] = next(
            (source.get(key) for source in (target, data, step)
             if source.get(key) is not None), None)
    return call


def _walk_actions(raw, out: list[dict], depth: int) -> None:
    if depth > _MAX_ACTION_DEPTH:
        return                             # somebody's YAML, not a promise
    if isinstance(raw, dict):
        raw = [raw]
    for step in (raw or []):
        if not isinstance(step, dict):
            continue
        service = step.get("action") or step.get("service")
        if service:
            out.append(_call(step, service))
            continue
        if step.get("device_id") and not any(k in step for k in _ACTION_KEYS):
            # A **device action** — what Home Assistant's own automation
            # editor writes for a device somebody picked off a list. It
            # names no service at all (`{device_id, domain, type}`), so a
            # reader looking for one walks straight past it, and every
            # protected check downstream sees an automation that does
            # nothing. Reported as the device target it is, which is the
            # scope `automation_writer` already refuses to expand.
            out.append(_call(step, "{}.{}".format(
                step.get("domain") or "device", step.get("type") or "action")))
            continue
        for branch in (step.get("choose") or []):
            if isinstance(branch, dict):
                _walk_actions(branch.get("sequence"), out, depth + 1)
        for key in _ACTION_KEYS:
            if key in step:
                _walk_actions(step[key], out, depth + 1)
        repeat = step.get("repeat")
        if isinstance(repeat, dict):
            _walk_actions(repeat.get("sequence"), out, depth + 1)
        parallel = step.get("parallel")
        if parallel is not None:
            _walk_actions(parallel, out, depth + 1)


def replay(config: dict, history: dict, start: float, end: float,
           tz=None) -> dict:
    """When this automation would have fired over the window, and what for.

    Raises `Refused` — never returns a partial answer — when any trigger
    or condition is outside what history can reconstruct.
    """
    tz = tz or dt.timezone.utc
    if end <= start:
        raise Refused("the replay window ends before it starts")
    if (end - start) > MAX_WINDOW_DAYS * 86400:
        raise Refused(
            f"a replay reaches back at most {MAX_WINDOW_DAYS} days — past "
            "that the recorder has usually purged what it would read")

    blocks = check_replayable(config)
    timeline = build_timeline(history)
    conditions = _conditions_of(config)

    fired: list[float] = []
    for block in blocks:
        kind = kind_of(block)
        if kind == "state":
            fired += _state_firings(block, timeline, start, end)
        elif kind == "numeric_state":
            fired += _numeric_firings(block, timeline, start, end)
        elif kind == "time":
            fired += _time_firings(block, start, end, tz)
        elif kind == "template":
            fired += _template_firings(block, timeline, start, end)
        elif kind in PURPOSE_TRIGGERS:
            fired += _purpose_firings(block, timeline, start, end)

    fired = sorted(t for t in set(fired) if start <= t <= end)
    if len(fired) > MAX_FIRINGS:
        raise Refused(
            f"this would have fired {len(fired)} times in the window, which "
            "is a trigger watching something that changes constantly rather "
            "than an automation — narrow it with a `to:` or a `for:`")

    ran, blocked = [], 0
    for when in fired:
        if all(passes(c, timeline, when, tz) for c in conditions):
            ran.append(when)
        else:
            blocked += 1

    return {
        "window_start": start, "window_end": end,
        "days": round((end - start) / 86400.0, 2),
        "triggered": len(fired),
        "blocked_by_conditions": blocked,
        "would_run": len(ran),
        "at": ran[:MAX_FIRINGS],
        "actions": would_do(config),
        "entities": sorted(entities_watched(config)),
    }


__all__ = [
    "MAX_ENTITIES", "MAX_FIRINGS", "MAX_WINDOW_DAYS", "NOT_RECORDED",
    "PURPOSE_CONDITIONS", "PURPOSE_TRIGGERS", "REPLAYABLE",
    "TEMPLATE_ALLOWED", "Refused", "build_timeline", "check_replayable",
    "check_template", "entities_watched", "fetch_history", "kind_of",
    "passes",
    "render_template", "replay", "state_at", "target_entities",
    "template_entities",
    "triggers_of", "would_do",
]
