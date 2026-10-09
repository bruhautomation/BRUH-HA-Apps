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


def when(value: Any) -> str:
    """A short date for a `detail` line: '3 Sep' / '3 Sep 2025'."""
    ts = parse_ts(value)
    if ts is None:
        return "an unknown time"
    d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    return d.strftime("%-d %b %Y") if d.year != dt.datetime.now(dt.timezone.utc).year \
        else d.strftime("%-d %b")


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


def history_cut(snap: dict) -> dict:
    """The entities the history probe found cut short, when there are
    enough of them to say the recorder is missing rows — else `{}`.

    One answer, read by `sys.history_incomplete` (which reports it) and by
    every check that reads a window off the recorder (which stands down
    for it), so the two can never disagree about whether history is
    trustworthy this pass.
    """
    probe = snap.get("history_health") or {}
    cut = probe.get("cut") or {}
    if not isinstance(cut, dict) or not cut:
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
        return check_id in rules or "*" in rules

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
            attrs = (self.states.get(entity_id) or {}).get("attributes") or {}
            reg = self.registry.get(entity_id) or {}
            klass = (attrs.get("device_class") or reg.get("device_class")
                     or reg.get("original_device_class") or "")
            if klass in classes:
                return True
        return False

    def withheld_by(self, entity_id: str, check_id: str) -> dict | None:
        """The correction that stands this check down for this entity, or None.

        Four scopes, narrowest first (`corrections.SCOPES`): this check on
        this entity, anything on this entity, this check in this entity's
        room, this check everywhere. The three wide ones never cover a pair
        `_never_covered` names. A snapshot with no ``corrections`` key — an
        older collector, a store that could not be read — falls back to the
        exception map `excepted` reads, so nothing that was standing down
        starts filing again because of how the snapshot was built.
        """
        table = self.snap.get("corrections")
        if not isinstance(table, dict):
            if self.excepted(entity_id, check_id):
                return {"scope": "entity_check", "text": ""}
            return None
        rules = (table.get("entity") or {}).get(entity_id) or {}
        if check_id in rules:
            return {**rules[check_id], "scope": "entity_check"}
        if self._never_covered(entity_id, check_id):
            return None
        if "*" in rules:
            return {**rules["*"], "scope": "entity"}
        area = self.area_id_of(entity_id)
        if area:
            hit = ((table.get("area") or {}).get(area) or {}).get(check_id)
            if hit:
                return {**hit, "scope": "check_area"}
        hit = (table.get("check") or {}).get(check_id)
        if hit:
            return {**hit, "scope": "check"}
        return None

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
        rule = self.withheld_by(entity_id, check_id)
        if rule is None:
            return True
        self._note({"kind": "exception", "subject": entity_id,
                    "check": check_id,
                    "reason": str(rule.get("text") or
                                  "you said this is not a problem here"),
                    "text": f"scope: {rule.get('scope', 'entity_check')}"
                            + (f", until {rule['until']}"
                               if rule.get("until") else "")})
        return False

    def gave_up(self, check_id: str, rows: list[dict], reason: str) -> None:
        """A check that says nothing because it found too much. One line each.

        Past a cap a check files nothing at all, on purpose — a dozen
        sensors frozen at once is a recorder purge, not a dozen broken
        sensors — and that is exactly the silence somebody later asks
        about. Each entity the check would have named gets a line on the
        decision trail with the sentence for why it went unsaid.
        """
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            self._note({"kind": "cap", "subject": str(row.get("entity_id") or ""),
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
# What follows the token: an optional closing quote, then `~` (glued into a
# longer string) or `(` (called).
_GLUED_OR_CALLED = re.compile(r"""['"]?\s*~|\s*\(""")


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
    return bool(_GLUED_OR_CALLED.match(text, m.end()))


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


def join_names(names: Iterable[str], limit: int = 6) -> str:
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


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
