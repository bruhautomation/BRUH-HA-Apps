"""Shared helpers for the house checks: names, times, and entity references.

Small on purpose. Anything that needs the snapshot's shape lives here so
the individual checks stay readable as rules.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
from typing import Any, Iterable, Iterator

import numfmt

log = logging.getLogger("brain.checks")

DAY = 86400.0

# Domains that hold *software* objects: their being "unavailable" is not a
# device gone quiet, and their sitting still for a week is not a stuck
# sensor. The device checks skip them.
SOFTWARE_DOMAINS = frozenset({
    "automation", "script", "scene", "zone", "person", "sun", "group",
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button", "schedule", "timer", "counter",
    "tts", "conversation", "stt", "wake_word", "assist_satellite",
    "update", "tag", "event", "date", "time", "datetime", "text",
    "number", "select", "button", "image", "notify", "todo", "calendar",
    "device_tracker",
})

# Entity ids look like `domain.object_id`, and so do a hundred other things
# in a YAML file ("3.5", "e.g.", "v2.0"). A reference is only counted when
# its domain is one Home Assistant actually has — the snapshot's states
# supply the domains this house has, and this set covers the ones a
# reference could name that happen to hold no entity right now.
_CORE_DOMAINS = frozenset({
    "alarm_control_panel", "automation", "binary_sensor", "button", "calendar",
    "camera", "climate", "cover", "date", "datetime", "device_tracker",
    "event", "fan", "humidifier", "image", "input_boolean", "input_button",
    "input_datetime", "input_number", "input_select", "input_text",
    "lawn_mower", "light", "lock", "media_player", "number", "person",
    "remote", "scene", "script", "select", "sensor", "siren", "switch",
    "text", "time", "timer", "todo", "update", "vacuum", "valve",
    "water_heater", "weather", "zone", "counter", "schedule", "group",
    "sun", "tag", "assist_satellite", "conversation", "stt", "tts",
    "wake_word", "air_quality", "geo_location", "plant",
})

_ENTITY_RE = re.compile(r"(?<![\w.])([a-z_]+)\.([a-z0-9_]+)(?![\w.])")
# HA lets a template reference look like states.sensor.x or states('sensor.x');
# the first form has no "domain.object" token on its own, so it gets its
# own pattern.
_STATES_ATTR_RE = re.compile(r"\bstates\.([a-z_]+)\.([a-z0-9_]+)")


class CouldNotLook(Exception):
    """A check's way of saying "I could not look", from inside the check.

    Most checks name the snapshot keys they need and are skipped before
    they run when one is missing. A check whose need depends on the house
    (`chore.job_done` needs a history fetch only when something has just
    finished) cannot say so up front, so it raises this: `run_all` files
    it under ``skipped`` with the sentence, never under ``errors``, and a
    skipped check clears nothing — `clear_resolved`'s rule.
    """


# How many withheld rows one checks pass may hand to the decision trail. A
# house where every check gives up on everything is a house the trail
# should describe once, not a reason to grow a list without bound.
TRAIL_MAX = 500


def parse_ts(value: Any) -> float | None:
    """An HA timestamp (ISO string, or epoch seconds) as epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Registry `created_at` is epoch seconds; a few payloads carry ms.
        return float(value) / (1000.0 if value > 1e11 else 1.0)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def age_days(value: Any, now: float) -> float | None:
    ts = parse_ts(value)
    return None if ts is None else max(0.0, (now - ts) / DAY)


def house_tz() -> dt.tzinfo:
    """The house's timezone (`baselines.house_timezone`), UTC when it
    cannot be read."""
    try:
        import baselines  # noqa: PLC0415 — panel-local, the one clock
        return baselines.house_timezone()[0]
    except Exception:  # noqa: BLE001 — a date in UTC beats no date
        return dt.timezone.utc


def clock(value: Any) -> str:
    """A time of day for a `detail` line ('14:20'), in the house's zone."""
    ts = parse_ts(value)
    if ts is None:
        return "an unknown time"
    return dt.datetime.fromtimestamp(ts, tz=house_tz()).strftime("%H:%M")


def when(value: Any) -> str:
    """A short date for a `detail` line: '3 Sep' / '3 Sep 2025'.

    In the house's own timezone: a reading that changed at 00:40Z on 21
    Oct changed on the evening of 20 Oct in New York, and that is the day
    the person living there would call it (#334). Every date a check
    writes goes through here."""
    ts = parse_ts(value)
    if ts is None:
        return "an unknown time"
    return numfmt.day(ts, house_tz()) or "an unknown time"


def num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f  # NaN reads as no number


# How many probed entities have to be cut short before the recorder is
# called incomplete. One could be a single integration writing late; two
# is the store itself.
HISTORY_MIN_CUT = 2


def recorder_excludes(recorder_filter: dict | None, entity_id: str) -> bool:
    """Whether the recorder's own `include`/`exclude` keeps this entity
    out of history on purpose (`snapshot.load_recorder_filter`).

    Home Assistant's order, as its docs give it: an entity named in
    `include` is recorded and one named in `exclude` is not; then an
    `exclude` glob or domain keeps it out; then an `include` glob or domain
    lets it in; and with an `include` configured, anything it did not name
    is not recorded. No filter (or one that could not be read) excludes
    nothing — the question is then not answered, never guessed.
    """
    import fnmatch

    flt = recorder_filter if isinstance(recorder_filter, dict) else {}
    inc = flt.get("include") if isinstance(flt.get("include"), dict) else {}
    exc = flt.get("exclude") if isinstance(flt.get("exclude"), dict) else {}
    if not inc and not exc:
        return False
    eid = str(entity_id or "")
    domain = eid.split(".", 1)[0]

    def names(block: dict, key: str) -> list[str]:
        value = block.get(key)
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in value or [] if isinstance(v, str)]

    if eid in names(inc, "entities"):
        return False
    if eid in names(exc, "entities"):
        return True
    if (domain in names(exc, "domains")
            or any(fnmatch.fnmatchcase(eid, g) for g in names(exc, "entity_globs"))):
        return True
    if (domain in names(inc, "domains")
            or any(fnmatch.fnmatchcase(eid, g) for g in names(inc, "entity_globs"))):
        return False
    return bool(inc)


def history_cut(snap: dict) -> dict:
    """The entities the history probe found cut short, when there are
    enough of them to say the recorder is missing rows — else `{}`.

    One answer, read by `sys.history_incomplete` (which reports it) and by
    every check that reads a window off the recorder (which stands down
    for it), so the two can never disagree about whether history is
    trustworthy this pass.

    Two kinds of row are not the recorder missing anything (#702, #707):
    an entity the recorder's own `exclude` keeps out of history on purpose
    (a network counter, typically), and one whose live value is the value
    its history ends on — a restart re-stamps `last_changed` without a
    change, so no row was due. The VALUE is compared, never the stamp.
    """
    probe = snap.get("history_health") or {}
    cut = probe.get("cut") or {}
    if not isinstance(cut, dict) or not cut:
        return {}
    flt = snap.get("recorder_filter")
    cut = {eid: row for eid, row in cut.items()
           if not recorder_excludes(flt, eid)
           and not (isinstance(row, dict) and "live_state" in row
                    and row.get("live_state") is not None
                    and str(row.get("live_state"))
                    == str(row.get("history_state")))}
    if not cut:
        return {}
    probed = int(probe.get("probed") or 0)
    if len(cut) >= HISTORY_MIN_CUT or len(cut) >= probed:
        return cut
    return {}


# How soon after Home Assistant starts a device going unavailable is put
# down to the start. A restart is the commonest reason a whole row of
# devices drops in one minute — and some integrations never come back from
# one — so a finding that says only "unavailable since 11:11" when Core
# started at 11:10 is telling half the story.
RESTART_WINDOW_S = 600


def ha_starts(snap: dict) -> list[float]:
    """Every time the snapshot knows Home Assistant started, oldest first:
    the logbook's own "started" lines, and the uptime integration's sensor
    (which reaches past the logbook's day)."""
    starts = [float(t) for t in ((snap.get("actions") or {}).get("starts")
                                 or []) if isinstance(t, (int, float))]
    states = snap.get("states") or {}
    uptime = {str(e.get("entity_id") or "")
              for e in snap.get("entities") or []
              if isinstance(e, dict) and e.get("platform") == "uptime"}
    for eid in uptime | {"sensor.uptime"}:
        st = states.get(eid)
        if isinstance(st, dict):
            ts = parse_ts(st.get("state"))
            if ts is not None:
                starts.append(ts)
    return sorted(set(starts))


def after_restart(snap: dict, value: Any) -> float | None:
    """The start a change at ``value`` came right after, or None."""
    changed = parse_ts(value)
    if changed is None:
        return None
    for start in reversed(ha_starts(snap)):
        if 0 <= changed - start <= RESTART_WINDOW_S:
            return start
    return None


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


# What a domain is called in a sentence, for an entity the house has no
# name for (one that no longer exists, mostly). Anything missing here is
# its domain with the underscores read as spaces.
_DOMAIN_NOUN = {
    "binary_sensor": "sensor", "input_boolean": "toggle helper",
    "input_select": "dropdown helper", "input_number": "number helper",
    "input_text": "text helper", "input_datetime": "date and time helper",
    "input_button": "button helper", "media_player": "media player",
    "climate": "thermostat", "alarm_control_panel": "alarm panel",
    "device_tracker": "tracker", "water_heater": "water heater",
}

_MAC_IN_NAME_RE = re.compile(
    r"\s*[(\[]?\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b[)\]]?", re.I)


def spoken_id(entity_id: str) -> str:
    """An entity id as a person would say it: 'the scene "before movie"'.

    For an entity the house has no name for — a reference to one that no
    longer exists, a fixture with no friendly name — so a finding's prose
    never shows `scene.before_movie`. The id itself belongs in the row's
    ``evidence``, which the card keeps under Details.
    """
    domain, _, obj = str(entity_id or "").partition(".")
    if not obj:
        return str(entity_id or "")
    noun = _DOMAIN_NOUN.get(domain, domain.replace("_", " "))
    words = " ".join(w for w in obj.split("_") if w)
    return f"the {noun} \u201c{words}\u201d"


# A state Home Assistant stores as a token, as its frontend shows it. A
# finding read "goes not_home at 05:20" and "went from running to
# “finish”"; the words a person sees on the entity's own card are these.
_STATE_WORDS = {
    "not_home": "away", "home": "home", "finish": "finished",
    "heat_cool": "heat/cool", "fan_only": "fan only",
    "armed_away": "armed away", "armed_home": "armed home",
    "armed_night": "armed night", "armed_vacation": "armed vacation",
    "armed_custom_bypass": "armed custom bypass",
    "below_horizon": "below the horizon",
    "above_horizon": "above the horizon",
}


def state_words(state) -> str:
    """A raw state token as Home Assistant's frontend says it: `not_home`
    is "away", a status's `finish` is "finished", and any other token with
    underscores reads with spaces."""
    raw = str(state if state is not None else "").strip()
    if raw in _STATE_WORDS:
        return _STATE_WORDS[raw]
    return raw.replace("_", " ")


def without_mac(name: str) -> str:
    """A device name with any MAC address taken out of it.

    Integrations name devices "Living room speaker (AA:BB:CC:DD:EE:FF)";
    the address tells a person nothing a picker does not, and it is the
    one part of the name nobody reads aloud. Empty when the name WAS the
    address — the caller says so in words.
    """
    return re.sub(r"\s{2,}", " ", _MAC_IN_NAME_RE.sub("", str(name or ""))).strip(" -–—")


def evidence_for(entity_ids: Iterable[str], value: str, limit: int = 8) -> list[dict]:
    """``evidence`` rows naming the ids a finding's prose names by name.

    The card shows evidence under its closed Details, so this is where an
    entity id goes: findable by whoever needs it, and out of the sentence
    a person reads first.
    """
    return [{"entity": e, "value": value, "when": ""}
            for e in list(entity_ids)[:limit] if e]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _names_room(name: str, area: str) -> bool:
    """Does ``name`` say the room called ``area``, in whole words?

    "Kitchen humidity" says the Kitchen; "Kitchenette lamp" does not. A
    trailing "room" on the area is optional ("Laundry light" says the
    Laundry Room) — the fold `facts_store._room_key` makes — but only
    while a word is left, or every name with "room" in it says the Room.
    """
    have = _words(name)
    want = _words(area)
    if want[-1:] == ["room"] and len(want) > 1:
        options = (want, want[:-1])
    else:
        options = (want,)
    for words in options:
        n = len(words)
        if n and any(have[i:i + n] == words for i in range(len(have) - n + 1)):
            return True
    return False


# Checks that each say "this device has gone quiet": a battery nobody will
# replace, a reading stuck on one value, a device not answering. An answer to
# one of them about one entity of a device is an answer about the device.
DEVICE_QUIET = frozenset({"dev.battery_low", "dev.frozen", "dev.unavailable"})
# The checks that say a device reads wrong or has gone quiet: the ones a
# person's "I don't use it any more" or "that sensor is broken" settles for
# good (`House.answered_off`).
DEVICE_FINISHED = DEVICE_QUIET | {"dev.implausible"}
# How many times a row may be marked Wrong before the check stops filing
# it for that entity.
WRONG_LIMIT = 2
# Checks whose report is a standing fact about an automation rather than an
# event — it has never fired, it has been off for months, its condition
# never passes — so the next report is the same fact, and ONE Wrong closes
# the check for that automation (#579). The rule a Wrong writes usually
# does this already; this is the answer read off the ledger, which holds
# whatever the reason said (a condition brAIn cannot watch writes no rule,
# a correction's lifetime ends one).
ANSWERED_ONCE = frozenset({"auto.never_fired", "auto.forgotten_off",
                           "auto.condition_never_passes"})
# "That reading is not impossible" is the same fact on the next pass too:
# the sensor measures a heater, or the household knows it is broken. So one
# Wrong about an entity closes `dev.implausible` for it, counted from the
# answer's status; a rule's explained range used to let the next, further-out
# reading file it again. Kept apart from `ANSWERED_ONCE`, whose checks also
# refuse "Don't remind me" (`server._for_now`): a snooze stays a snooze here.
ONE_WRONG = ANSWERED_ONCE | {"dev.implausible"}
# The checks that report one sensor's READINGS: out of its usual range,
# impossible, drifting. A Wrong under one of them is the household saying
# the sensor's readings are not news, so the Wrongs about one entity are
# counted across the three: `WRONG_LIMIT` of them closes all three for that
# entity, whichever check each was given under.
READING_CHECKS = frozenset({"base.unusual", "dev.implausible",
                            "forecast.decline"})
# The checks that stand down by their own record (`House.stand_down`): the
# reading checks, while their record is held (`rule_record.holds`: the
# latest answers Wrong with no agreement among them), raise each entity
# only once; `auto.never_fired`, once marked Wrong twice with the latest a
# Wrong, raises nothing.
STAND_DOWN_ONCE = READING_CHECKS
STAND_DOWN_SILENT = frozenset({"auto.never_fired"})
SILENT_MIN_WRONG = 2
# The checks that, while their record stands them down (`rule_record.holds`,
# or the Resident's own arithmetic, `rule_record.measured_only`), file only
# what a measurement backs (#1078): two rules undoing each other is filed
# when both rules' own traces show them running at the moments the
# entity moved, a device gone quiet when the stretch is at least
# `MEASURED_UNAVAILABLE_DAYS` long. Never a pair `_never_covered` names.
STAND_DOWN_MEASURED = frozenset({"auto.conflict", "dev.unavailable"})
MEASURED_UNAVAILABLE_DAYS = 7
# What backs a row from each of them, in the sentence the trail says.
MEASURED_BY = {
    "auto.conflict": "both rules' own run history",
    "dev.unavailable": f"a stretch of at least {MEASURED_UNAVAILABLE_DAYS} "
                       "days offline",
}
# The chore checks that answer for one machine: an explanation given under
# either is about the machine (`House.owner_explained`).
CHORE_CHECKS = frozenset({"chore.waiting", "chore.dehumidifier"})
# How long an explanation given with a Wrong on a device check keeps holding
# across the device's later stretches (`House.owner_explained`): a knob that
# sleeps sleeps again, and a reason that turns out to be about a repair
# still lapses.
EXPLAINED_HOLD_S = 90 * 86400



# How a correction that names a machine state is read against that state
# (`chores.condition_holds`), set by `checks.chores` when it is imported.
CONDITION_HOLDS = None

# How far past the explained reading a rule keeps holding, as a share of the
# distance between the usual and that reading: a reading a little further
# out is the same thing the person explained, one far beyond it is not.
EXPLAINED_MARGIN = 0.1


def explained_range(value, anchor, floor: float = 0.0) -> list[float] | None:
    """``[low, high]`` a Wrong on a reading's row explains: from ``anchor``
    (the usual, or the edge of what the sensor can read) to the reading
    ``value``, widened by `EXPLAINED_MARGIN` of that distance and at least
    ``floor`` — the smallest move the check would report. Carried on the
    row (`explained`), kept on the rule by the press (`server.
    _record_exception`) and read by `House._applies_now`."""
    value, anchor = num(value), num(anchor)
    if value is None or anchor is None:
        return None
    low, high = sorted((value, anchor))
    pad = max(float(floor or 0.0), EXPLAINED_MARGIN * (high - low))
    return [round(low - pad, 3), round(high + pad, 3)]


# The owner's mark that a thermometer does not measure the air of the room
# it is in (a sensor inside a pump box, one on a heating manifold): an
# `exception:room_air` fact on the sensor, written from the Wrong box
# (`server._mark_not_room_air`). No check is called this, so it stands no
# check down by itself; the readers of a room's air ask `room_air_verdict`.
ROOM_AIR_RULE = "room_air"
# The household's statement, read by the correction's second look out of a
# Wrong's reason, that a room is not heated (#1476): an `exception:unheated`
# fact on `area:<id>`, which `checks.thermal.unconditioned_from` reads as a
# room nothing heats. Like `ROOM_AIR_RULE`, no check has this id.
UNHEATED_RULE = "unheated"


class House:
    """Lookups over a snapshot that several checks want."""

    def __init__(self, snap: dict):
        self.snap = snap
        self.states: dict[str, dict] = snap.get("states") or {}
        self.entities: list[dict] = snap.get("entities") or []
        self.devices: dict[str, dict] = {
            d["id"]: d for d in (snap.get("devices") or []) if d.get("id")}
        self.areas: dict[str, str] = {
            a["area_id"]: a.get("name") or a["area_id"]
            for a in (snap.get("areas") or []) if a.get("area_id")}
        self.registry: dict[str, dict] = {
            e["entity_id"]: e for e in self.entities if e.get("entity_id")}
        self.known_domains = (
            {domain_of(e) for e in self.states} | _CORE_DOMAINS)
        # What each entity IS, as `world_model` read it — `{}` when the
        # snapshot carries no reading, which is every word list answering
        # exactly as it did before a reading existed.
        world = snap.get("world")
        self.world: dict = world if isinstance(world, dict) else {}

    # -- names -------------------------------------------------------------
    def name(self, entity_id: str) -> str:
        st = self.states.get(entity_id) or {}
        attrs = st.get("attributes") or {}
        if attrs.get("friendly_name"):
            return str(attrs["friendly_name"])
        reg = self.registry.get(entity_id) or {}
        return str(reg.get("name") or reg.get("original_name") or entity_id)

    def label(self, entity_id: str) -> str:
        """What a finding's prose calls an entity: its name, never its id.

        ``name`` falls back to the id when the house has no name for it,
        which is right for matching and wrong in a sentence; this falls
        back to :func:`spoken_id` instead.
        """
        name = self.name(entity_id)
        return name if name and name != entity_id else spoken_id(entity_id)

    def device_of(self, entity_id: str) -> dict | None:
        reg = self.registry.get(entity_id) or {}
        return self.devices.get(reg.get("device_id") or "")

    def device_name(self, device: dict) -> str:
        return str(device.get("name_by_user") or device.get("name")
                   or device.get("id") or "a device")

    def area_of(self, entity_id: str) -> str:
        reg = self.registry.get(entity_id) or {}
        area = reg.get("area_id")
        if not area:
            dev = self.device_of(entity_id)
            area = (dev or {}).get("area_id")
        return self.areas.get(area or "", "")

    def where(self, entity_id: str) -> str:
        """' in the Kitchen' or ''. For a sentence about an entity."""
        area = self.area_of(entity_id)
        return f" in the {area}" if area else ""

    def placed(self, entity_id: str, *names: str) -> str:
        """Where it is, as a sentence of its own, or '' when that adds nothing.

        A finding's detail used to end with ``where()`` hung after its full
        stop ("…its normal variation. in the Kitchen."), and when the name
        already said a room the clause either repeated it or joined two
        rooms into one phrase nobody could read. So this is a whole,
        capitalised sentence with a leading space; nothing when there is no
        area or when a name the row uses already says that room; and when a
        name says a DIFFERENT room than the one it is assigned to, both
        plainly, because which is right is the person's to say.

        ``names`` are the names the row puts in front of a reader (the
        entity's own by default); a room is "said" by a name when its words
        appear there whole, case-folded, with a trailing "room" optional.
        """
        area = self.area_of(entity_id)
        if not area:
            return ""
        said = [str(n) for n in (names or (self.name(entity_id),)) if n]
        if any(_names_room(n, area) for n in said):
            return ""
        for other in sorted(set(self.areas.values()), key=len, reverse=True):
            if other and other != area and any(_names_room(n, other)
                                               for n in said):
                return f" It is named for the {other} but assigned to the {area}."
        return f" It is in the {area}."

    def room_air_verdict(self, entity_id: str) -> tuple[str, str]:
        """``(kind, why)`` when this thermometer is known NOT to read the
        air of its room, else ``("", "")``.

        ``marked``: the owner said so (`ROOM_AIR_RULE`). ``broken``: the
        owner said this sensor is broken (`said_broken`), so its reading is
        evidence of nothing. ``not_air``: the
        nightly heat model left it out for what it is (a machine's probe,
        a derived reading, a reading that jumps like equipment). ``held``:
        the model found something keeps it warm at night, so it does not
        follow outdoors. All four are structured, read off the snapshot:
        the facts table, the owner's stored answers (`snap["said_broken"]`) and
        the thermal store's `unmeasured[eid]["kind"]`.
        A sensor the model simply lacked nights for has no verdict.
        """
        table = self.snap.get("facts")
        if isinstance(table, dict) and ROOM_AIR_RULE in (
                table.get(entity_id) or ()):
            return "marked", "you said it does not measure the room's air"
        if self.said_broken(entity_id):
            return "broken", "you said this sensor is broken"
        left = (((self.snap.get("thermal") or {}).get("unmeasured") or {})
                .get(entity_id))
        if isinstance(left, dict) and left.get("kind") in ("not_air", "held"):
            return str(left["kind"]), str(left.get("reason") or "")
        return "", ""

    def said_broken(self, entity_id: str) -> str:
        """The owner's own words saying THIS sensor is broken, or "" (#1202).

        Off `snap["said_broken"]` (`corrections.sensor_said_broken`): a rule
        a Wrong wrote under this entity alone — never one fanned out over
        every entity a row or a case cited — whose reason says, about the
        sensor and nothing else, that it is broken (`says_sensor_broken`:
        not "the heater is broken", not "sensor fine", not "retired").
        Deliberately NOT `snap["faulty"]`, whose wording takes any subject.
        Under the floors the room-air mark has (`server.
        _cannot_mark_room_air`): never a lock, an alarm, a protected entity,
        nor anything on a device that carries a leak, smoke, gas or safety
        class (`_never_whole` with no check). It takes a reading out of the
        freeze check, so in doubt it is not broken. No trail entry here;
        each reader says in its own sentence what it did not rely on.
        """
        said_map = self.snap.get("said_broken")
        if not isinstance(said_map, dict):
            return ""
        said = str(said_map.get(entity_id) or "")
        if not said:
            return ""
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
        except Exception:  # noqa: BLE001 — unread settles nothing
            return ""
        if not corrections.says_sensor_broken(said):
            return ""
        never = (self.snap.get("corrections") or {}).get("never")
        protected = (never or {}).get("protected") if isinstance(
            never, dict) else None
        # The snapshot's table, and the fixed lists when it has none.
        if self._never_whole(entity_id, "") or corrections.never_covered(
                entity_id, "",
                protected=corrections.never_table(protected)["protected"]):
            return ""
        return said

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.states or entity_id in self.registry

    def excepted(self, entity_id: str, check_id: str) -> bool:
        """Has the homeowner said this rule is wrong about this entity?

        `snap["facts"]` is `facts_store.exception_map()`, loaded once by
        the collector: `{entity_id: {check_id, …}}`, where `*` is the
        whole-entity form. Wrong on a check's finding writes one, and a
        check reads it here before filing the same row again in new
        words — the loop the Wrong button always promised. A snapshot
        with no key (an older collector, a store that could not be read)
        excepts nothing, which is the direction in which being wrong
        shows a card.
        """
        table = self.snap.get("facts")
        if not isinstance(table, dict):
            return False
        rules = table.get(entity_id)
        if not rules:
            return False
        if check_id in rules:
            return True
        # The whole-entity form never stands a safety device down; this
        # fallback has no corrections table, so the fixed lists answer.
        if "*" in rules:
            return not self._never_whole(entity_id, check_id)
        return False

    def _never_whole(self, entity_id: str, check_id: str) -> bool:
        """A pair the whole-entity rule (`*`) may never cover, read off the
        fixed lists in `corrections` where the snapshot carries none."""
        if self._never_covered(entity_id, check_id):
            return True
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
        except Exception:  # noqa: BLE001
            return False
        for eid in [entity_id, *self.siblings(entity_id)]:
            attrs = (self.states.get(eid) or {}).get("attributes") or {}
            reg = self.registry.get(eid) or {}
            klass = (attrs.get("device_class") or reg.get("device_class")
                     or reg.get("original_device_class") or "")
            if corrections.never_covered(eid, check_id, device_class=klass):
                return True
        return False

    def area_id_of(self, entity_id: str) -> str:
        """The area id an entity sits in — its own, else its device's.

        `area_of`'s rule (an entity's own area beats its device's, which is
        Home Assistant's) answering with the id rather than the name,
        because a correction scoped to a room is stored under the id: a
        room somebody renames is still the room they meant.
        """
        reg = self.registry.get(entity_id) or {}
        area = reg.get("area_id")
        if not area:
            area = (self.device_of(entity_id) or {}).get("area_id")
        return str(area or "")

    def _never_covered(self, entity_id: str, check_id: str) -> bool:
        """Is this a pair no WIDE correction may ever stand down?

        A correction somebody gave about one sensor may be scoped to a room
        or to a whole rule (`corrections.py`), and the room or the rule can
        later hold a leak detector, a smoke alarm, a lock or something on
        the protected list that nobody was thinking of when they typed it.
        So the wide scopes are refused for those at READ time as well as at
        write time — a scope written in March cannot know what was fitted
        in May. The table is the snapshot's (`corrections.scope_map()`'s
        `never`), so this stays a pure read over what the pass was handed.
        """
        never = (self.snap.get("corrections") or {}).get("never") or {}
        if check_id in set(never.get("checks") or ()):
            return True
        domain = domain_of(entity_id)
        if domain in set(never.get("domains") or ()):
            return True
        patterns = [str(p).lower() for p in never.get("protected") or ()]
        target = entity_id.lower()
        if any(p in (target, f"{domain}.*", "*") for p in patterns):
            return True
        classes = set(never.get("classes") or ())
        if classes:
            # The entity's own class, and its device's other entities': a
            # leak sensor's battery is the leak sensor's battery.
            for eid in [entity_id, *self.siblings(entity_id)]:
                attrs = (self.states.get(eid) or {}).get("attributes") or {}
                reg = self.registry.get(eid) or {}
                klass = (attrs.get("device_class") or reg.get("device_class")
                         or reg.get("original_device_class") or "")
                if klass in classes:
                    return True
        return False

    def siblings(self, entity_id: str) -> list[str]:
        """The other entities on this entity's device, or [] for none."""
        device = (self.registry.get(entity_id) or {}).get("device_id")
        if not device:
            return []
        return [e for e in self._device_entities(device) if e != entity_id]

    def _device_entities(self, device_id: str) -> list[str]:
        """Every entity on one device, read once per snapshot."""
        by_device = getattr(self, "_by_device", None)
        if by_device is None:
            by_device = {}
            for row in self.entities:
                if row.get("device_id") and row.get("entity_id"):
                    by_device.setdefault(row["device_id"], []).append(
                        str(row["entity_id"]))
            self._by_device = by_device
        return list(by_device.get(device_id, ()))

    def _device_rule(self, entity_id: str, check_id: str, rules_of) -> dict | None:
        """An answer given about another entity of the same device.

        A Wrong is written under the entity its row was filed under, and a
        device publishes several: the battery row of a sensor somebody will
        not re-battery, and the temperature reading on the same box that
        `dev.frozen` then reports as stuck. The person answered about the
        DEVICE. So a `*` rule on a sibling, or a rule for this check, or a
        rule for any check in `DEVICE_QUIET` when this check is one of them
        (a dead battery, a frozen reading and an unavailable device are one
        device having gone quiet), stands this check down too. The caller
        has already refused this for a pair `_never_covered` names, so a
        smoke detector on the same device is never covered.
        """
        family = DEVICE_QUIET if check_id in DEVICE_QUIET else {check_id}
        for other in self.siblings(entity_id):
            rules = rules_of(other) or {}
            for key in ("*", check_id, *sorted(family)):
                if key in rules:
                    rule = rules[key] if isinstance(rules[key], dict) else {}
                    return {**rule, "scope": "device", "via": other}
        return None

    def _explains_now(self, entity_id: str, rule: dict) -> bool:
        """Whether this entity's reading is still inside the range the rule
        explained (`explained_range`), or the rule carries none. A rule
        reached through ANOTHER entity of the device (`via`) explained that
        entity's reading, not this one's, and a reading that cannot be read
        is not news."""
        explained = (rule or {}).get("explained")
        if (not isinstance(explained, (list, tuple)) or len(explained) != 2
                or (rule or {}).get("via")):
            return True
        value = num((self.states.get(entity_id) or {}).get("state"))
        low, high = (num(v) for v in explained)
        if value is None or low is None or high is None:
            return True
        return low <= value <= high

    def _applies_now(self, entity_id: str, rule: dict) -> bool:
        """Whether a rule whose reason names a machine state stands down now.

        "Normal while the printer is printing — only unusual if hot while it
        is idle" was stored as a rule with no condition and stood the check
        down in both states. The reason is the rule's own text, so it is
        read here against the device's job status (`chores.condition_holds`):
        the rule holds in the state the person called normal and not in the
        one they asked to hear about. A reason that names no state this
        device reports stands down as it always did.
        """
        text = str((rule or {}).get("text") or "")
        # `chores` registers the reader (`CONDITION_HOLDS`): it imports this
        # module, so asking for it here would be an import cycle. The package
        # imports every check, so it is always set once `checks` is loaded.
        reader = CONDITION_HOLDS
        holds = reader(self, entity_id, text) if (reader and text) else None
        if holds is not None:
            return holds
        # A reason that names no state — "that's normal for this sensor" —
        # on a reading check's row explained the reading the person was
        # shown, and holds while the reading stays there.
        return self._explains_now(entity_id, rule)

    def withheld_by(self, entity_id: str, check_id: str) -> dict | None:
        """The correction that stands this check down for this entity, or None.

        Four scopes, narrowest first (`corrections.SCOPES`): this check on
        this entity, anything on this entity, then an answer about another
        entity of the same device (`_device_rule`), this check in this
        entity's room, this check everywhere. The wide ones never cover a pair
        `_never_covered` names. A snapshot with no ``corrections`` key — an
        older collector, a store that could not be read — falls back to the
        exception map `excepted` reads, so nothing that was standing down
        starts filing again because of how the snapshot was built.
        """
        table = self.snap.get("corrections")
        if not isinstance(table, dict):
            if self.excepted(entity_id, check_id):
                return {"scope": "entity_check", "text": ""}
            # No table to read `never` off: the fixed lists answer, with
            # the device's other classes (a leak sensor's battery).
            if self._never_whole(entity_id, check_id):
                return None
            facts = self.snap.get("facts")
            return self._device_rule(
                entity_id, check_id,
                lambda eid: {c: {"text": ""} for c in
                             ((facts or {}).get(eid) or ())}
                if isinstance(facts, dict) else None)
        rules = (table.get("entity") or {}).get(entity_id) or {}
        if check_id in rules and self._applies_now(entity_id, rules[check_id]):
            return {**rules[check_id], "scope": "entity_check"}
        if self._never_covered(entity_id, check_id):
            return None
        if "*" in rules and self._applies_now(entity_id, rules["*"]):
            return {**rules["*"], "scope": "entity"}
        hit = self._device_rule(entity_id, check_id,
                                lambda eid: (table.get("entity") or {}).get(eid))
        if hit and self._applies_now(entity_id, hit):
            return hit
        area = self.area_id_of(entity_id)
        if area:
            hit = ((table.get("area") or {}).get(area) or {}).get(check_id)
            if hit:
                return {**hit, "scope": "check_area"}
        hit = (table.get("check") or {}).get(check_id)
        if hit:
            return {**hit, "scope": "check"}
        return None

    def unwatched(self, entity_id: str, check_id: str = "*") -> dict | None:
        """The owner's Stop watching on this entity or its device, or None.

        Only the explicit rule about everything on a thing (`*`, what the
        Stop watching press writes, `server._stop_watching`), on this
        entity or another of its device, holding now (`_applies_now`),
        never for a pair the whole-entity rule may not cover
        (`_never_whole`). Never read off words: a reason typed in a box is
        a rule only for the check it was typed under. The one reader the
        checks pass asks for every row it hands back (`checks.run_all`), and
        the checks that name an entity in a row about something else (a
        trigger of an automation) ask it for that entity.
        """
        if not entity_id or "." not in entity_id:
            return None
        if self._never_whole(entity_id, check_id):
            return None
        table = self.snap.get("corrections")
        if isinstance(table, dict):
            def rules_of(eid):
                return (table.get("entity") or {}).get(eid) or {}
        else:
            facts = self.snap.get("facts")

            def rules_of(eid):
                held = (facts or {}).get(eid) if isinstance(facts, dict) \
                    else None
                return {c: {"text": ""} for c in held or ()}
        for eid in [entity_id, *self.siblings(entity_id)]:
            rule = rules_of(eid).get("*")
            if rule is None:
                continue
            rule = rule if isinstance(rule, dict) else {}
            if not self._applies_now(entity_id, {**rule, "via": eid}):
                continue
            return {**rule, "text": str(rule.get("text") or "")
                    or "you asked brAIn to stop watching it",
                    "scope": "entity" if eid == entity_id else "device",
                    "via": eid}
        return None

    def answered_off(self, entity_id: str, check_id: str) -> dict | None:
        """The household's own earlier answers that close this check for
        this entity, read off the settled ledger (`snap["answers"]`), or None.

        Two things close it, both read before a card is made: the same row
        marked Wrong `WRONG_LIMIT` times (once for `ONE_WRONG`'s standing
        facts about an automation; a rule that was written and still
        did not hold is not a reason to ask a third time), and a reason that
        says the device is finished with — retired, not used, broken
        (`corrections.gone_for_good`) — for a check that is about the device
        reading wrong or going quiet (`DEVICE_FINISHED`), on this entity or
        another of its device. A different check is a different kind of
        fault and is not closed by either. Never a pair `_never_covered`
        names: a smoke or leak sensor is asked about whatever was said.
        """
        answers = self.snap.get("answers")
        if not isinstance(answers, dict):
            answers = {}
        if not answers and not self.snap.get("faulty"):
            return None
        if self._never_covered(entity_id, check_id):
            return None
        finished = check_id in DEVICE_FINISHED
        gone = broken = None
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
            gone = corrections.gone_for_good
            broken = corrections.broken_answer
        except Exception:  # noqa: BLE001
            pass
        own = (answers.get(entity_id) or {}).get(check_id)
        limit = 1 if check_id in ONE_WRONG else WRONG_LIMIT
        if isinstance(own, dict) and int(own.get("wrong") or 0) >= limit:
            times = int(own["wrong"])
            return {"text": "you marked this wrong" + (
                        "" if times == 1 else f" {times} times"),
                    "scope": "answers"}
        if check_id not in (READING_CHECKS | STAND_DOWN_SILENT
                            | STAND_DOWN_MEASURED):
            said = self._once_while_held(entity_id, check_id, answers)
            if said:
                return said
        if check_id in READING_CHECKS:
            # Counted by status across the three reading checks (above).
            times = sum(int(((answers.get(entity_id) or {}).get(cid) or {})
                            .get("wrong") or 0) for cid in READING_CHECKS)
            stood = self.stand_down(check_id)
            if times >= (1 if stood else WRONG_LIMIT):
                said = ("you marked this sensor's readings wrong"
                        + ("" if times == 1 else f" {times} times"))
                if stood:
                    return {"text": f"{said}, and {stood['reason']}",
                            "scope": "answers", "kind": "stand_down"}
                return {"text": said, "scope": "answers"}
        # Said on any card, not only this check's: "I don't use that remote
        # any more" on a Resident case or an overnight card is the same
        # device finished with (`corrections.known_faulty`, #697).
        # Through the one helper every reader shares (#701): the floors
        # are this entity's, whichever entity of the device was answered,
        # and the drop goes on the trail.
        faulty = self.snap.get("faulty")
        if finished and isinstance(faulty, dict) and faulty:
            for eid in [entity_id, *self.siblings(entity_id)]:
                said = broken(eid, check_id, faulty=faulty,
                              never=lambda _e, c: self._never_covered(
                                  entity_id, c),
                              note=lambda row: self._note(
                                  {**row, "subject": entity_id}),
                              ) if broken else str(faulty.get(eid) or "")
                if said:
                    return {"text": said, "scope": "answers",
                            "noted": bool(broken)}
        if check_id in DEVICE_QUIET:
            said = self._answered_this_stretch(entity_id, check_id, answers)
            if said:
                return said
        if check_id == "dev.unavailable":
            # An explanation the household gave about this device going
            # quiet — a remote that sleeps, a lamp left unplugged — covers
            # its next stretch too: the stretch rule above lifts when the
            # device comes back and goes again, which is exactly what a
            # sleeping knob does every day (`owner_explained`).
            said = self.owner_explained(entity_id, DEVICE_QUIET)
            if said:
                return {"text": said["text"] + " (your explanation of this "
                        "device)", "scope": "answers"
                        if said["via"] == entity_id else "device"}
        if not (finished and gone):
            return None
        for eid in [entity_id, *self.siblings(entity_id)]:
            for cid in sorted(DEVICE_FINISHED):
                row = (answers.get(eid) or {}).get(cid)
                for note in (row or {}).get("notes") or ():
                    if gone(note):
                        return {"text": str(note), "scope": "answers"}
        return None

    def _once_while_held(self, entity_id: str, check_id: str,
                         answers: dict) -> dict | None:
        """The reading checks' "each sensor once" for every other check
        whose own record holds it (#1477): while `stand_down` does, one
        Wrong about this entity closes the check for it, and for a check
        about the DEVICE (`DEVICE_QUIET`: a flat battery, a stuck reading, a
        device not answering) one Wrong under any of them about another
        entity of the same device does too, so a dead device is not asked
        about once per sensor. A check about a measurement that differs per
        entity is never closed by a sibling's answer. The caller has
        refused a pair `_never_covered` names."""
        stood = self.stand_down(check_id)
        if not stood:
            return None
        family = DEVICE_QUIET if check_id in DEVICE_QUIET else {check_id}
        for eid in [entity_id, *(self.siblings(entity_id)
                                 if check_id in DEVICE_QUIET else ())]:
            for cid in sorted(family):
                row = (answers.get(eid) or {}).get(cid)
                if isinstance(row, dict) and int(row.get("wrong") or 0) >= 1:
                    said = ("you marked this wrong" if eid == entity_id else
                            f"you marked {self.label(eid)} on the same "
                            "device wrong")
                    return {"text": f"{said}, and {stood['reason']}",
                            "scope": "answers" if eid == entity_id
                            else "device", "kind": "stand_down"}
        return None

    def settled_device(self, device: dict | None, entity_id: str = "",
                       check_id: str = "*") -> str:
        """The household's own answer finishing with this device, or "".

        A check that NAMES devices in a list rather than filing a row per
        entity (the Zigbee devices gone quiet, the network's drop list)
        asked only whether somebody disabled or labelled the device, so
        "it is not in use", "that sensor is broken" or Stop watching, given
        on any card about any of its entities, left it named in the next
        list (#1132). Read from what is stored, the same two answers every
        other reader takes: a device said to be finished with or broken
        (`snap["faulty"]`, `corrections.broken_answer`'s wording) and a rule
        about everything on one of its entities (`*`, Stop watching). Never
        a pair `_never_covered` names, and the drop goes on the trail.
        """
        device_id = str((device or {}).get("id") or "")
        named = [entity_id] if entity_id else []
        if device_id:
            named += [e for e in self._device_entities(device_id)
                      if e not in named]
        if not named:
            return ""
        if any(self._never_covered(eid, check_id) for eid in named):
            return ""
        faulty = self.snap.get("faulty")
        faulty = faulty if isinstance(faulty, dict) else {}
        table = self.snap.get("corrections")
        rules_of = ((table.get("entity") or {}) if isinstance(table, dict)
                    else {})
        facts = self.snap.get("facts")
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
            gone = corrections.gone_for_good
        except Exception:  # noqa: BLE001
            def gone(_note):
                return False
        said = ""
        for eid in named:
            reason = str(faulty.get(eid) or "")
            if reason and gone(reason):
                said = reason
                break
            rule = (rules_of.get(eid) or {}).get("*")
            if rule is not None:
                said = str((rule or {}).get("text") or "") \
                    if isinstance(rule, dict) else ""
                said = said or "you asked brAIn to stop watching it"
                break
            if not rules_of and isinstance(facts, dict) \
                    and "*" in (facts.get(eid) or ()):
                said = "you asked brAIn to stop watching it"
                break
        if said:
            self._note({"kind": "exception", "subject": named[0],
                        "check": check_id, "reason": said,
                        "text": "you settled this device, so it is left "
                                "out of the list"})
        return said

    def acknowledged(self, entity_id: str, check_id: str) -> bool:
        """Has the household said they know about this (an `accepted` ending:
        To Do, "on my list") and is that answer still standing? The check
        reads it to say a row in new words only when it got worse; the
        row itself stays held by the ledger."""
        answers = self.snap.get("answers")
        row = ((answers or {}).get(entity_id) or {}).get(check_id) \
            if isinstance(answers, dict) else None
        return isinstance(row, dict) and bool(row.get("acked_at"))

    def acknowledged_level(self, entity_id: str, check_id: str):
        """The level a standing acknowledgement was given at, or None."""
        answers = self.snap.get("answers")
        row = ((answers or {}).get(entity_id) or {}).get(check_id) \
            if isinstance(answers, dict) else None
        level = row.get("acked_level") if isinstance(row, dict) else None
        return float(level) if isinstance(level, (int, float)) else None

    def stretch_began(self, entity_id: str):
        """When this entity's current state began, as an epoch, or None.

        The earlier of the recorder's start of an unavailable stretch
        (`snap["unavailable_since"]`) and the live `last_changed` — a
        restart re-stamps the live one, so a live stamp from right after a
        start is no change at all and, with nothing earlier, is unknown.
        """
        live = (self.states.get(entity_id) or {}).get("last_changed")
        stamps = [parse_ts(((self.snap.get("unavailable_since") or {})
                            .get(entity_id)))]
        if after_restart(self.snap, live) is None:
            stamps.append(parse_ts(live))
        stamps = [s for s in stamps if s is not None]
        return min(stamps) if stamps else None

    def _answered_this_stretch(self, entity_id: str, check_id: str,
                               answers: dict) -> dict | None:
        """A Wrong given about this device going quiet, in the stretch it is
        still in (#863, #848).

        The rule a Wrong writes stands the device down, but a reason that
        writes none — a condition brAIn cannot watch, kept as a question —
        left one Wrong short of `WRONG_LIMIT`, and the answer was read only
        under the entity the row led with, so the next pass led with a
        sibling and asked again. An answer about any entity of the device,
        under any check that says it has gone quiet (`DEVICE_QUIET`), holds
        while the entity filed now is still in the state it was answered
        in; one that came back and went again since is news. "For now" is
        the snooze the person asked for (`corrections.temporary`) and is
        left to it.
        """
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
            temporary = corrections.temporary
        except Exception:  # noqa: BLE001
            def temporary(_note):
                return False
        since = self.stretch_began(entity_id)
        for eid in [entity_id, *self.siblings(entity_id)]:
            for cid in sorted(DEVICE_QUIET):
                row = (answers.get(eid) or {}).get(cid)
                if not isinstance(row, dict) or int(row.get("wrong") or 0) < 1:
                    continue
                notes = [str(n) for n in row.get("notes") or ()]
                if notes and temporary(notes[-1]):
                    continue
                at = int(row.get("wrong_at") or row.get("at") or 0)
                if since is not None and at < since:
                    continue
                return {"text": (notes[-1] if notes else
                                 "you marked this wrong")
                        + " (answered while it was in this state; brAIn "
                          "asks again if it comes back and goes again)",
                        "scope": "answers" if eid == entity_id
                        else "device"}
        return None

    def answered_since(self, key: str, check_id: str, since) -> dict | None:
        """The household's Wrong on this check about ``key`` (an entity, or
        `entry:<id>` for a config entry), given at or after ``since`` — when
        the thing last changed state — or None. An answer holds until the
        state it was given about changes: a plug that came back and went
        again, an integration that loaded and failed again, is news."""
        answers = self.snap.get("answers")
        row = ((answers or {}).get(key) or {}).get(check_id) \
            if isinstance(answers, dict) else None
        if not isinstance(row, dict) or int(row.get("wrong") or 0) < 1:
            return None
        if since is not None and int(row.get("at") or 0) < float(since):
            return None
        return row

    def should_report(self, entity_id: str, check_id: str) -> bool:
        """May this check file a row about this entity? The one question.

        Every check that files a row about an entity asks it, and
        `tests/test_scoped_corrections.py` holds that by reading the checks'
        own source: a check that bypassed it would go on filing a row the
        homeowner already answered, in new words, which is the loop the
        Wrong button exists to end. A refusal leaves its reason on the
        decision trail (`_note`), because a row withheld because somebody
        said so is the one silence a person can ask about and deserves the
        sentence they gave.
        """
        rule = self.withheld_by(entity_id, check_id) \
            or self.answered_off(entity_id, check_id)
        if rule is None:
            return True
        if rule.get("noted"):
            # Its own trail entry is written (`corrections.broken_answer`).
            return False
        self._note({"kind": str(rule.get("kind") or "exception"),
                    "subject": entity_id,
                    "check": check_id,
                    "reason": str(rule.get("text") or
                                  "you said this is not a problem here"),
                    "text": f"scope: {rule.get('scope', 'entity_check')}"
                            + (f", until {rule['until']}"
                               if rule.get("until") else "")})
        return False

    def stand_down(self, check_id: str,
                   now: float | None = None) -> dict | None:
        """This check's own record, when it stands the check down, else None.

        ``{"wrong", "total", "streak", "reason"}``, read off the producer
        scorecard the collector loads (`snap["record"]`, `{source: row}`,
        counted from the endings' status, never their words). A reading
        check (`STAND_DOWN_ONCE`) stands down while `rule_record.holds` —
        its latest answers Wrong with no agreement among them — and then
        raises each entity once (`answered_off`); `auto.never_fired`
        (`STAND_DOWN_SILENT`) stands down once marked Wrong
        `SILENT_MIN_WRONG` times, the latest a Wrong, and raises nothing.
        Any agreement given later lifts both. `STAND_DOWN_MEASURED`'s checks
        stand down while `rule_record.holds` or `rule_record.measured_only`
        (the Resident's arithmetic) and then file only what a measurement
        backs; ``measured`` on the answer says what that is. No record, or
        one that cannot be read, stands nothing down.
        """
        table = self.snap.get("record")
        row = (table or {}).get(f"check:{check_id}") \
            if isinstance(table, dict) else None
        if not isinstance(row, dict):
            return None
        try:
            import rule_record  # noqa: PLC0415 — a leaf, the one arithmetic
            wrong = int(row.get("wrong") or 0)
            total = int(row.get("total") or 0)
            streak = int(row.get("streak") or 0)
        except Exception:  # noqa: BLE001 — unreadable holds nothing back
            return None
        if check_id in STAND_DOWN_MEASURED:
            import time as _time  # noqa: PLC0415
            when = _time.time() if now is None else float(now)
            row = {**row, "source": f"check:{check_id}"}
            if not (rule_record.holds(row)
                    or (rule_record.quietable(row["source"])
                        and rule_record.measured_only(row, when))):
                return None
            said = (f"the last {streak} of this rule's reports wrong in a "
                    "row" if streak >= rule_record.HOLD_STREAK else
                    f"{wrong} of this rule's {total} reports wrong, the "
                    "latest among them")
            backed = MEASURED_BY.get(check_id, "a measurement")
            return {"wrong": wrong, "total": total, "streak": streak,
                    "measured": backed,
                    "reason": f"you marked {said}, so brAIn raises one only "
                              f"when {backed} backs it, until you agree "
                              "with one"}
        if check_id in STAND_DOWN_SILENT:
            if wrong < SILENT_MIN_WRONG or row.get("last") != "wrong":
                return None
            reason = (f"you marked {wrong} of this rule's {total} reports "
                      "wrong, the latest among them, so brAIn has stopped "
                      "raising it until you agree with one")
        else:
            if not rule_record.holds({**row, "source": f"check:{check_id}"}):
                return None
            said = (f"the last {streak} of this rule's reports in a row"
                    if streak >= rule_record.HOLD_STREAK else
                    f"{wrong} of this rule's {total} reports, the latest "
                    "among them")
            thing = "sensor" if check_id in READING_CHECKS else "thing"
            reason = (f"you marked {said} wrong, so brAIn raises each "
                      f"{thing} only once until you agree with one")
        return {"wrong": wrong, "total": total, "streak": streak,
                "reason": reason}

    def owner_explained(self, entity_id: str, checks=None,
                        now: float | None = None) -> dict | None:
        """The household's own explanation stored against this entity or
        another entity of its device, or None.

        Read from structure, never from the words: a correction rule
        written against the entity (any check, or one of ``checks``), or a
        Wrong that came WITH a reason (`snap["answers"]`' notes) under one
        of ``checks`` (any check when None). A reason that says "for now"
        (`corrections.temporary`) is a snooze, not an explanation, and an
        explanation given more than `EXPLAINED_HOLD_S` ago no longer covers
        a NEW stretch on its own. Never a pair `_never_covered` names: a
        smoke, leak or gas sensor, a lock, an alarm or a protected entity
        is reported whatever was said about it.
        """
        want = set(checks) if checks else None
        probe = sorted(want)[0] if want else "*"
        if self._never_covered(entity_id, probe):
            return None
        try:
            import corrections  # noqa: PLC0415 — lazy: it imports the stores
            temporary = corrections.temporary
        except Exception:  # noqa: BLE001
            def temporary(_note):
                return False
        import time as _time  # noqa: PLC0415
        now = _time.time() if now is None else float(now)
        table = self.snap.get("corrections")
        rules_of = ((table.get("entity") or {}) if isinstance(table, dict)
                    else {})
        facts = self.snap.get("facts")
        answers = self.snap.get("answers")
        answers = answers if isinstance(answers, dict) else {}
        for eid in [entity_id, *self.siblings(entity_id)]:
            if self._never_covered(eid, probe):
                continue
            rules = rules_of.get(eid) or {}
            if not rules and isinstance(facts, dict):
                rules = {c: {} for c in (facts.get(eid) or ())}
            for cid, rule in sorted(rules.items()):
                if want is None or cid in want:
                    text = str((rule or {}).get("text") or "") \
                        if isinstance(rule, dict) else ""
                    if text and temporary(text):
                        continue
                    return {"text": text or "you said this is not a "
                            "problem here", "via": eid, "check": cid}
            for cid, row in sorted((answers.get(eid) or {}).items()):
                if want is not None and cid not in want:
                    continue
                if not isinstance(row, dict) or int(row.get("wrong") or 0) < 1:
                    continue
                notes = [str(n) for n in row.get("notes") or () if str(n)]
                if not notes or temporary(notes[-1]):
                    continue
                at = int(row.get("wrong_at") or row.get("at") or 0)
                if at and now - at > EXPLAINED_HOLD_S:
                    continue
                return {"text": notes[-1], "via": eid, "check": cid}
        return None

    def gave_up(self, check_id: str, rows: list[dict], reason: str,
                kind: str = "cap") -> None:
        """A check that says nothing about rows it found. One line each.

        Past a cap a check files nothing at all, on purpose — a dozen
        sensors frozen at once is a recorder purge, not a dozen broken
        sensors — and that is exactly the silence somebody later asks
        about. Each entity the check would have named gets a line on the
        decision trail with the sentence for why it went unsaid.

        ``kind`` is the decision trail's word for WHY (`decision_trail.KINDS`):
        ``cap`` only when a too-many-at-once limit fired, ``drift`` when the
        reading was the season or the weather moving the band, ``claimed``
        when another check reports the entity, ``explained`` when something
        in the house accounts for it. One word for all of them told a person
        a check had given up on a reading it had in fact explained.
        """
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            self._note({"kind": kind, "subject": str(row.get("entity_id") or ""),
                        "check": check_id, "reason": reason,
                        "text": str(row.get("text") or "")})

    def _note(self, row: dict) -> None:
        trail = self.snap.get("_trail")
        if isinstance(trail, list) and len(trail) < TRAIL_MAX:
            trail.append(row)

    def enabled(self, entity_id: str) -> bool:
        reg = self.registry.get(entity_id)
        if reg is None:
            return entity_id in self.states
        return not reg.get("disabled_by")

    # -- automations -------------------------------------------------------
    def automation_entity(self, config_id: str) -> str:
        """The entity_id an automation config's `id` registered as."""
        for e in self.entities:
            if (e.get("platform") == "automation"
                    and str(e.get("unique_id") or "") == str(config_id)):
                return e["entity_id"]
        return ""

    def entity_refs(self, obj: Any) -> set[str]:
        """Every entity id mentioned anywhere in a config tree.

        A service name has the same shape as an entity id
        (``light.turn_on`` / ``light.kitchen``), so the values of the keys
        that hold one are skipped, and so is anything that is a registered
        service — ``light.turn_on`` inside a template is still a service.
        """
        services = set(self.snap.get("services") or ())
        out: set[str] = set()
        for text in _strings(obj):
            spans = _template_spans(text)
            loop_vars = _loop_vars(text) if spans else frozenset()
            for m in _ENTITY_RE.finditer(text):
                domain, obj_id = m.group(1), m.group(2)
                ref = f"{domain}.{obj_id}"
                if (domain not in self.known_domains or domain == "notify"
                        or ref in services):
                    continue
                if not _could_be_an_id(domain, obj_id):
                    continue
                if spans and _BUILT_ANYWHERE.match(text, m.end()):
                    continue
                if spans and _inside(m.start(), spans) and _not_a_ref(
                        text, m, loop_vars):
                    continue
                out.add(ref)
            for domain, obj_id in _STATES_ATTR_RE.findall(text):
                if domain in self.known_domains:
                    out.add(f"{domain}.{obj_id}")
        return out


# Inside a Jinja template a `domain.object` token is not always a reference.
# `"switch.pump_" ~ zone` is a string being glued into an id the template
# builds at run time, `zone.split('-')` is a method call on a loop variable
# that happens to be called after a domain, and `{% for zone in zones %}`
# makes every `zone.<x>` after it an attribute of that variable. Reporting
# any of those as a missing entity is `auto.dead_ref` firing on a healthy
# script, so they are skipped — but only inside `{{ }}`/`{% %}`, because a
# plain string outside a template that names an entity names an entity, and
# `states('sensor.x')` inside one still does.
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_FOR_RE = re.compile(r"\{%-?\s*for\s+([a-z_][a-z0-9_]*(?:\s*,\s*[a-z_][a-z0-9_]*)*)"
                     r"\s+in\b")
# What follows the token: an optional closing quote, then `~` or `+` (glued
# into a longer string), `(` (called), or the string-format operator `%`
# with something after it (never `%}`, which closes a tag).
_GLUED_OR_CALLED = re.compile(r"""['"]?\s*[~+]|\s*\(|['"]?\s*%(?!\})""")
# A token followed straight away by `{` is a prefix with the rest of the id
# still to come: `switch.pump_zone{{ repeat.index }}` (the template glued on
# OUTSIDE its span, which is why this one is asked wherever the string holds
# a template) and `'switch.zone{}'.format(i)`. An id never ends in a brace.
_BUILT_ANYWHERE = re.compile(r"\{")


def _template_spans(text: str) -> list[tuple[int, int]]:
    if "{{" not in text and "{%" not in text:
        return []
    return [(m.start(), m.end()) for m in _TEMPLATE_RE.finditer(text)]


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _loop_vars(text: str) -> frozenset[str]:
    names: set[str] = set()
    for m in _FOR_RE.finditer(text):
        names.update(n.strip() for n in m.group(1).split(","))
    return frozenset(names)


def _not_a_ref(text: str, m: re.Match, loop_vars: frozenset[str]) -> bool:
    if m.group(1) in loop_vars:
        return True
    if _REGEX_ARG.search(text, 0, m.start()):
        return True
    return bool(_GLUED_OR_CALLED.match(text, m.end()))


# Home Assistant never names an entity whose domain or object id starts or
# ends with `_` or holds `__` (`valid_entity_id`), so a token shaped like
# that is a piece of an id wherever it sits: `'switch.pump_zone_' ~ n`
# with the prefix kept in a `{% set %}` or a `variables:` value, where the
# glue is nowhere near it (#336).
def _could_be_an_id(domain: str, obj_id: str) -> bool:
    return not any(part.startswith("_") or part.endswith("_") or "__" in part
                   for part in (domain, obj_id))


# A regex filter's or test's pattern names no entity, whatever it looks
# like: `regex_replace('switch.pump_zone_', '')`, `is match('light.hall')`,
# `select('search', 'light.hall')`. Asked of the text up to the token.
_REGEX_ARG = re.compile(
    r"""(?:\b(?:regex_[a-z_]+|match|search)\s*\(\s*|"""
    r"""['"](?:regex_[a-z_]+|match|search)['"]\s*,\s*)['"]\Z""")


# Keys whose string value names a service, a trigger kind or a platform —
# never an entity.
_NOT_ENTITY_KEYS = frozenset({"service", "action", "trigger", "platform",
                              "domain", "event_type", "condition", "mode"})


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
                if k in _NOT_ENTITY_KEYS and isinstance(v, str):
                    continue
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def walk(obj: Any) -> Iterator[Any]:
    """Every node of a config tree, depth first."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk(v)


def listify(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def counted_names(names: Iterable[str], limit: int = 6) -> str:
    """"2: Hall, Porch" — or just the name when there is one.

    A card under the heading "Z-Wave nodes are marked dead" read
    "1: Laundry Room Energy Monitor", which looks like a list numbered by
    somebody who stopped at one. The count only says something when there
    is more than one thing to count.
    """
    names = list(names)
    if len(names) == 1:
        return names[0]
    return f"{len(names)}: " + join_names(names, limit)


# Integrations whose domain does not spell their name.
_KNOWN_INTEGRATION_NAMES = {
    "zha": "Zigbee (ZHA)", "zwave_js": "Z-Wave", "mqtt": "MQTT",
    "esphome": "ESPHome", "hassio": "Supervisor",
    "homekit_controller": "HomeKit Device", "unifiprotect": "UniFi Protect",
    "hue": "Philips Hue", "tplink": "TP-Link", "mobile_app": "Mobile App",
    "github": "GitHub", "upnp": "UPnP", "dlna_dmr": "DLNA",
    "ibeacon": "iBeacon",
}


def spell_integration(domain: str) -> str:
    """An integration's domain as the words a person knows it by, where
    nothing better is to hand: `bambu_lab` → `Bambu Lab`. A domain is a
    registry key, and a finding titled with one names nothing a person sees
    (#340)."""
    domain = str(domain or "")
    if domain in _KNOWN_INTEGRATION_NAMES:
        return _KNOWN_INTEGRATION_NAMES[domain]
    return " ".join(w[:1].upper() + w[1:] for w in domain.split("_") if w)


# The most characters an inline list of names may take in a finding's
# sentence. A detail is capped by the store (`findings_store.MAX_DETAIL`)
# and clamped to three lines on a card, so a list of long names ran past
# both and was cut mid-name — "the scene “…”, the select…" (#437). A row
# that lists things carries them whole as `items`; the sentence only has
# to say enough to read.
LIST_BUDGET = 260


def join_names(names: Iterable[str], limit: int = 6,
               budget: int = LIST_BUDGET) -> str:
    """Names joined for a sentence: at most ``limit`` of them and at most
    ``budget`` characters of them (always the first), then "and N more"."""
    names = list(names)
    kept: list[str] = []
    used = 0
    for name in names[:limit]:
        cost = len(name) + (2 if kept else 0)
        if kept and used + cost > budget:
            break
        kept.append(name)
        used += cost
    if len(kept) == len(names):
        return ", ".join(kept)
    return ", ".join(kept) + f" and {len(names) - len(kept)} more"


# A name Home Assistant or a person numbered to tell copies apart: "Porch
# light 2", "Porch light (2)". The number is the only difference.
_NUMBERED_RE = re.compile(r"^(.*?\S)\s*(?:\((\d{1,3})\)|(?<=\s)(\d{1,3}))$")


def _plural(noun: str) -> str:
    if re.search(r"(?:s|sh|ch|x|z)$", noun):
        return noun + "es"
    if re.search(r"[^aeiou]y$", noun):
        return noun[:-1] + "ies"
    return noun + "s"


def _kind_of(entity_ids: list[str], count_: int) -> str:
    """"7 sensors", "2 lights" — "2 entities" when their kinds differ."""
    domains = {domain_of(e) for e in entity_ids}
    noun = (_DOMAIN_NOUN.get(next(iter(domains)), next(iter(domains))
                             .replace("_", " "))
            if len(domains) == 1 else "entity")
    return f"{count_} {noun if count_ == 1 else _plural(noun)}"


def _and_words(words: list[str]) -> str:
    return (", ".join(words[:-1]) + " and " + words[-1]
            if len(words) > 1 else (words[0] if words else ""))


def _unnumbered(label: str) -> str:
    m = _NUMBERED_RE.match(label)
    return (m.group(1) if m else label).casefold()


def merged_names(labels: Iterable[str]) -> list[str]:
    """Names that differ only by a number said once (#1334): "Porch
    light 1, 2 and 3" for a series; "Porch light" for "Porch light" and
    "Porch light (1)", since "(1)" marks a copy and an unnumbered name is
    the original. Order kept, by first appearance."""
    order: list[str] = []
    by: dict[str, list[str]] = {}
    for label in labels:
        label = str(label or "")
        if not label:
            continue
        key = _unnumbered(label)
        if key not in by:
            by[key] = []
            order.append(key)
        if label not in by[key]:
            by[key].append(label)
    out = []
    for key in order:
        group = by[key]
        if len(group) == 1:
            out.append(group[0])
            continue
        base, numbers = group[0], []
        for label in group:
            m = _NUMBERED_RE.match(label)
            if m:
                base = m.group(1)
                if m.group(3):
                    numbers.append(m.group(3))
        numbers = sorted(dict.fromkeys(numbers), key=int)
        out.append(f"{base} {_and_words(numbers)}" if len(numbers) > 1
                   else base)
    return out


def grouped_labels(house: "House", entity_ids: Iterable[str]) -> list[str]:
    """What a finding calls a set of entities, one label a thing (#1334).

    Entities of one device are that device ("7 sensors on Kitchen tablet"),
    an id Home Assistant numbered for a collision (`light.porch_2` beside
    `light.porch`) is the entity it copies, and names that differ only by
    a number are one name with its numbers ("Porch light 1, 2 and 3",
    "Porch light" for "Porch light" and "Porch light (1)"). Entities the
    house no longer has (no name, no device) that share the first words of
    their id are one label too: their id is the device's name followed by
    the reading's. Read off the registry and the names, never the words."""
    ids = list(dict.fromkeys(str(e) for e in entity_ids if e))
    present = set(ids)
    order: list[tuple] = []
    groups: dict[tuple, list[str]] = {}

    def put(key: tuple, eid: str) -> None:
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(eid)

    # A copy is the entity it copies, listed under that one's name.
    ids = [e for e in ids
           if re.sub(r"_\d+$", "", e) == e or re.sub(r"_\d+$", "", e)
           not in present]
    on_device: dict[str, list[str]] = {}
    for eid in ids:
        dev = house.device_of(eid)
        if dev and dev.get("id"):
            on_device.setdefault(str(dev["id"]), []).append(eid)
    for eid in ids:
        dev = house.device_of(eid)
        if dev and dev.get("id") and len(on_device[str(dev["id"])]) > 1:
            put(("device", str(dev["id"])), eid)
            continue
        if not house.exists(eid):
            domain, _, obj = eid.partition(".")
            words = [w for w in obj.split("_") if w]
            if len(words) >= 3:
                put(("gone", domain, tuple(words[:2])), eid)
                continue
        put(("name", _unnumbered(house.label(eid))), eid)
    out: list[str] = []
    for key in order:
        members = groups[key]
        if key[0] == "device":
            dev = house.devices.get(key[1]) or {}
            out.append(f"{_kind_of(members, len(members))} on "
                       f"{house.device_name(dev)}")
            continue
        if key[0] == "gone":
            if len(members) == 1:
                out.append(house.label(members[0]))
                continue
            # The longest run of id words every member starts with.
            split = [[w for w in m.partition(".")[2].split("_") if w]
                     for m in members]
            common = []
            for words in zip(*split):
                if len(set(words)) != 1:
                    break
                common.append(words[0])
            out.append(f"{_kind_of(members, len(members))} whose names "
                       f"start \u201c{' '.join(common)}\u201d")
            continue
        out.append(merged_names([house.label(e) for e in members])[0])
    return out


def entity_list(house: "House", entity_ids: Iterable[str],
                budget: int = LIST_BUDGET) -> str:
    """`grouped_labels` as a sentence's list: whole when it fits ``budget``
    (no count cap, #1334), otherwise as much as fits and how many more."""
    labels = grouped_labels(house, entity_ids)
    return join_names(labels, limit=max(1, len(labels)), budget=budget)


def load_yaml_file(path: str) -> Any:
    """Parse one of HA's YAML files, or None if it is absent or broken.

    ``!secret``, ``!include`` and friends are HA's tags, not YAML's; a
    loader that refuses them would refuse most real config files. They are
    read as None here — a check reading a value that was a secret sees
    nothing, which is the honest answer, not a crash.
    """
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None

    class _Loader(yaml.SafeLoader):
        pass

    def _tag(loader, suffix, node):
        return None

    _Loader.add_multi_constructor("!", _tag)
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 — SafeLoader subclass
    except yaml.YAMLError as exc:
        log.warning("could not parse %s: %s", path, str(exc)[:200])
        return None


_TARGET_OFFLINE = re.compile(
    r"no (?:player|entity|entities|targets?)\b.{0,30}?(?:was|were|found|matched)"
    r"|no targets? matched"
    r"|not in the game(?: right now)?",
    re.IGNORECASE)


def target_offline_error(error: Any) -> bool:
    """A game server's answer that the thing aimed at is not there.

    "No player was found" is what Minecraft says when a command names a
    player who is not in the game: the expected outcome with nobody playing,
    not a broken automation. Every other error is still an error."""
    return bool(_TARGET_OFFLINE.search(str(error or "")))
