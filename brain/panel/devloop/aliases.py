"""Stable stand-ins for what would locate a home: entity ids, the names
people gave things, and the rooms they are in.

A report has to be useful to somebody fixing brAIn and useless to
somebody reading it for the house. What a developer needs is the SHAPE —
which domain, which check, that two rows are about the same light — and
never which light. So every entity id becomes ``<domain>.<domain>_<n>``,
every friendly name becomes ``<Domain> <n>`` and every room ``Room <n>``,
numbered in the order this house first met them and remembered on disk,
so the same light is ``light.light_07`` in March and in May and two
issues about it can be told to be about one thing.

Three rules.

**The map never leaves the box.** It is `/data/devloop/aliases.json`,
which is the one file that could turn an alias back into a room, and
nothing in this package sends it anywhere.

**Only entity-shaped words in an entity domain are aliased.** A report is
full of `server.py`, `memory.md` and `e.g.`, and aliasing those would
make the report useless to the one person who reads it; `light.turn_on`
is a service and says nothing about the house, so a service verb in the
object position is left alone.

**A name is replaced longest first and only as a whole word**, because
"Kitchen" inside "Kitchen Ceiling" must not leave "Light 4 Ceiling", and
a two-letter name would eat half the English in the report. Names under
`MIN_NAME` characters are left; an id that names the same thing is still
aliased, which is where the useful half of the information was anyway.

**A name made only of Home Assistant's own words is not the household's**
(`GENERIC_WORDS`). An integration names its entities "Battery", "Power",
"Energy", "Mode" or "Restart", and replacing those as whole words rewrote
the PROSE of every report: "non-battery sensors" arrived as "non-Binary
sensor 269 sensors", "power-sensed" as "Sensor 13-sensed", and "brAIn"
itself as "Conversation 7", so the fixer read a report it could not parse.
Such a name says nothing about which home it is in, so it is left in the
text; its entity id is still aliased. A person's, a tracker's and a zone's
name is never treated as generic, whatever it is.

**A one-word name that is also a common English word is aliased where
it is used as a name, not where it is used as the word**
(`is_ordinary`, `_used_as_name`, `ordinary_words.txt`). Households name
things "Screen", "Inside" and "Box", and replacing every such word
rewrote the prose: "the message box sits under the home indicator inside
HA's frame; full-screen is off" arrived as "the message Binary sensor 251
sits under the home indicator Light 56 HA's frame; full-Switch 335 is
off". Privacy decides first and the way the word is written second. A
name is exempt at all only when it is one ASCII word whose lower-case
form is on the bundled list of common English words (names, pets' names
and rooms taken out of it), and it is not a person's, tracker's, zone's
or room's: "Dexter", "Nursery", "Emma" and "свет" are aliased everywhere,
as are "Ben's room", "Kitchen ceiling" and "Lamp2". For an exempt name,
an occurrence written all lower case in running prose is the word and is
left, while one written with a capital (the household's own spelling,
which is how every field built from entity data carries it), quoted or in
a code span, followed by its domain word or beside its entity id, alone
in a table cell, list item or field, or between the `·` separators of a
`where` is the name and is aliased. A person's typed words and a log are
never prose to us: `apply(strict=True)` (the `owner_words` and
`log_excerpt` fields, the owner's note) and any line quoted with `>` or
inside a ``` fence keep the whole-word rule for every name. A person's
name is aliased however it is written ("will grace the hall" loses its
verb rather than risk a name).

**A first name is learnt where the house defines it, not guessed from
the text** (`name_parts`, `dashboard_names`). Morph draws a people tile,
a room's sleeper or a door by a name that is often no entity's whole
name: a card given `name:` in dashboard.yaml, "Ben" out of "Ben's room",
the first word of the person "Ben Smith", or the word left of "Ben door"
once the device words are gone; and brAIn's brief writes the same name
in free text ("ben's door is open"). So the map also holds every word of
a person's name, the owner in a possessive name, the words of a sleep,
door, window or room-presence sensor's name that are neither Home
Assistant's vocabulary nor common English, and the names Morph's own
configuration gives (a card's or a section's name, a group's label, and
any `person`/`sleeper`/`people` value). A common English word is never
learnt from these, so "Doors", "People" and "Kids" stay readable.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import atomic_write

from . import data_dir

# The domains whose object ids are chosen by, or named after, a household.
# A closed list rather than "anything with a dot" for the reason the
# module docstring gives: most dotted words in a report are file names.
ENTITY_DOMAINS = frozenset({
    "air_quality", "alarm_control_panel", "assist_satellite", "automation",
    "binary_sensor", "button", "calendar", "camera", "climate", "conversation",
    "counter", "cover", "date", "datetime", "device_tracker", "event", "fan",
    "group", "humidifier", "image", "input_boolean", "input_button",
    "input_datetime", "input_number", "input_select", "input_text", "lawn_mower",
    "light", "lock", "media_player", "notify", "number", "person", "remote",
    "scene", "schedule", "script", "select", "sensor", "siren", "stt", "sun",
    "switch", "text", "time", "timer", "todo", "tts", "update", "vacuum", "valve",
    "wake_word", "water_heater", "weather", "zone",
})
# A word in the object position that is a service rather than a thing.
SERVICE_WORDS = frozenset({
    "turn_on", "turn_off", "toggle", "reload", "trigger", "set_value",
    "press", "select_option", "set_temperature", "set_hvac_mode", "open_cover",
    "close_cover", "stop_cover", "lock", "unlock", "open", "play_media",
    "media_play", "media_pause", "media_stop", "volume_set", "send_message",
    "apply", "create", "delete", "update", "install", "start", "stop",
    "increment", "decrement", "set_percentage", "set_preset_mode",
    "persistent_notification", "speak", "announce", "home", "home_assistant",
})
MIN_NAME = 3
# Words Home Assistant and its integrations name entities with: device
# classes, split on underscores, and the names integrations give an
# entity of a device ("Restart", "Firmware", "Signal strength"). A name
# made of nothing else is vocabulary, not a household's choice. Domain
# names are deliberately absent: "Light" is aliased like any other name.
GENERIC_WORDS = frozenset("""
    absolute address alarm apparent aqi atmospheric auto battery brain
    bed brightness button carbon charge charging child cloud cold
    connected connectivity consumption current daily data device devices
    dioxide distance entities entity everything
    door duration enabled energy error factor filter firmware frequency
    garage gas heat high humidity identify illuminance indicator ip
    irradiance job last led level link linkquality lock low manual max
    min mode moisture monetary monoxide motion moving nozzle occupancy
    online opening overheating overloaded ozone ph plug power precipitation
    presence pressure print problem production progress rate reboot
    report reporting reports
    remaining reset restart rssi running safety seen setpoint signal size
    smoke sound speed state status strength sync tamper target temperature
    time today total update uptime version vibration voltage volume water
    weight wifi wind window
""".split())
# Kinds whose name is a person's or a place's, never vocabulary.
PERSONAL_KINDS = frozenset({"person", "device_tracker", "zone"})
ENTITY_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")
# The person-ish identifiers notify services carry, and the companion
# app's own prefix: `notify.mobile_app_brians_phone` is a name in an id.
_MOBILE_RE = re.compile(r"\bmobile_app_[a-z0-9_]+\b")


def is_generic(name: str, kind: str) -> bool:
    """True when ``name`` is made only of `GENERIC_WORDS` (and digits)."""
    if kind in PERSONAL_KINDS:
        return False
    words = re.findall(r"[a-z]+|\d+", str(name or "").casefold())
    return bool(words) and all(w.isdigit() or w in GENERIC_WORDS for w in words)


# What a one-word name may stand beside and still be the household's thing.
_QUOTES = "\"'`\u2018\u2019\u201c\u201d"
_SEPARATORS = "\u00b7\u203a|"
_LINE_LEAD_RE = re.compile(r"^[\s>*\-\u2022|#]*(?:\d+[.)]\s*)?[*_`]*")
_LINE_TAIL_RE = re.compile(r"[*_`]*\s*(?::.*)?\|?\s*$")


# Never exempt, however common the word: a room says where, and these say who.
_NEVER_ORDINARY = PERSONAL_KINDS | {"room", "area"}
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+")
_WORDS: frozenset | None = None


def ordinary_words() -> frozenset:
    """The bundled list (`ordinary_words.txt`), read once. An unreadable
    list is an empty one, so every name keeps the strict rule."""
    global _WORDS
    if _WORDS is None:
        try:
            lines = (Path(__file__).with_name("ordinary_words.txt")
                     .read_text(encoding="utf-8").split("\n"))
        except OSError:
            lines = []
        _WORDS = frozenset(w.strip() for w in lines
                           if w.strip() and not w.lstrip().startswith("#"))
    return _WORDS


def is_ordinary(name: str, kind: str) -> bool:
    """True when ``name`` is one ASCII word whose lower-case form is a common
    English word on the bundled list, and not a person's, place's or room's,
    so it is aliased only where it is used as a name."""
    name = str(name or "")
    return (kind not in _NEVER_ORDINARY and bool(_ASCII_WORD_RE.fullmatch(name))
            and name.lower() in ordinary_words())


# The classes whose entity is named after the person or room it watches
# ("Ben door", "Ben sleep"), so what is left of its name once Home
# Assistant's and English's words are gone is that person or room.
_ABOUT_CLASSES = frozenset({"door", "window", "opening", "garage_door",
                            "occupancy", "presence", "motion"})
_SLEEP_RE = re.compile(r"(?i)(?:^|[\s_.])(?:a?sleep\w*|bed(?:time)?|in_bed)(?:$|[\s_.])")
_POSSESSIVE_RE = re.compile(r"([^\W\d_]{3,})['’]s\b")
_PART_RE = re.compile(r"[^\W\d_]{3,}")


def _common(word: str) -> bool:
    """A word that names nothing in particular: Home Assistant's own
    vocabulary or a common English word."""
    return is_generic(word, "thing") or is_ordinary(word, "thing")


def name_parts(name: str, kind: str, eid: str = "", klass: str = "") -> list[tuple[str, str]]:
    """The words inside a name that are a person's or a room's own, as
    ``(word, kind)``: every word of a person's name; the owner of a
    possessive ("Ben" in "Ben's room"); and what a sleep, door, window or
    presence sensor's name says beyond the device ("Ben" in "Ben door").
    Never a common English word or Home Assistant's vocabulary."""
    name = str(name or "")
    out: list[tuple[str, str]] = []
    if kind == "person":
        out += [(w, "person") for w in _PART_RE.findall(name) if not is_generic(w, "thing")]
    out += [(w, "person") for w in _POSSESSIVE_RE.findall(name) if not _common(w)]
    if klass in _ABOUT_CLASSES or _SLEEP_RE.search(f"{eid} {name}"):
        out += [(w, "name") for w in _PART_RE.findall(_POSSESSIVE_RE.sub("", name))
                if not _common(w)]
    return [(w, k) for w, k in out if w.casefold() != name.casefold()]


# Morph's configuration: which keys hold a name the dashboard draws, and
# which of them always hold a person's.
_CONFIG_NAME_KEYS = frozenset({"name", "title", "label"})
_CONFIG_PERSON_KEYS = frozenset({"person", "people", "sleeper", "sleepers", "who",
                                 "owner", "child", "children", "kid", "kids"})
_CONFIG_SKIP_RE = re.compile(r"[{}\[\]<>]|^[a-z_]+\.[a-z0-9_]+$|^(?:mdi|hass|custom):")
_CONFIG_MAX = 400


def _config_entities(node: dict) -> list[str]:
    ents = node.get("entities") if isinstance(node.get("entities"), list) else [node.get("entity")]
    return [e if isinstance(e, str) else str((e or {}).get("entity") or "")
            for e in ents if isinstance(e, (str, dict))]


def dashboard_names(data, found: list | None = None, person: bool = False,
                    depth: int = 0) -> list[tuple[str, str]]:
    """Every name Morph's configuration gives (a card's or a section's
    name, a group's label, any `person`/`sleeper`/`people` value), as
    ``(name, kind)``. A dashboard's or a floor's title is the page's, not
    the household's ("Home"), and a common word is no household's name."""
    found = [] if found is None else found
    if depth > 12 or len(found) >= _CONFIG_MAX:
        return found
    if isinstance(data, list):
        for item in data:
            dashboard_names(item, found, person, depth + 1)
        return found
    if isinstance(data, str):
        if person:
            found.append((data, "person"))
        return found
    if not isinstance(data, dict):
        return found
    domains = {e.split(".", 1)[0] for e in _config_entities(data) if "." in e}
    personal = person or bool(domains & PERSONAL_KINDS)
    for key, value in data.items():
        key = str(key)
        if key in _CONFIG_PERSON_KEYS:
            dashboard_names(value, found, True, depth + 1)
        elif key in _CONFIG_NAME_KEYS and isinstance(value, str):
            if key == "title" and ("sections" in data or "floors" in data):
                continue
            section = key == "title" and ("groups" in data or "cards" in data)
            kind = "person" if personal else ("room" if section else "name")
            found.append((value, kind))
        elif isinstance(value, (dict, list)):
            dashboard_names(value, found, False, depth + 1)
    return found


def house_config_names() -> list[tuple[str, str]]:
    """The names Morph's dashboard.yaml and its kept copies of Home
    Assistant's dashboards (`dashboards/*.yaml`) give, read off the box.
    A file that is missing or does not parse gives none."""
    try:
        import yaml  # noqa: PLC0415 — the image ships py3-yaml
    except ImportError:
        return []
    main = Path(os.environ.get("BRAIN_MORPH_DASHBOARD", "/config/morph/dashboard.yaml"))
    files = [main]
    try:
        files += sorted((main.parent / "dashboards").glob("*.yaml"))[:40]
    except OSError:
        pass
    found: list[tuple[str, str]] = []
    for path in files:
        try:
            dashboard_names(yaml.safe_load(path.read_text(encoding="utf-8")), found)
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return found


def _typed_words(text: str, start: int) -> bool:
    """Whether ``start`` is inside a line quoted with ``>`` (a person's own
    words) or a ``` fence (a log, a traceback): never running prose."""
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith(">"):
        return True
    return text.count("```", 0, start) % 2 == 1


def _used_as_name(text: str, start: int, end: int, kinds: frozenset) -> bool:
    """Whether the lower-case word at ``text[start:end]`` stands where a
    name stands rather than where English does. Ids are parked as
    ``\x00n\x00`` placeholders by the time this runs."""
    before, after = text[max(0, start - 40):start], text[end:end + 40]
    # Quoted, or a code span: "screen", `screen`, 'screen'.
    if before[-1:] and before[-1] in _QUOTES and after[:1] and after[0] in _QUOTES:
        return True
    # Followed by its domain word or beside an entity id: "screen switch",
    # "screen (switch.screen)". Not preceded by it: "the light inside the
    # box" is English.
    for kind in kinds:
        word = re.escape(kind).replace("_", "[ _]")
        if re.match(rf"\s+(?:{word}|entity)\b", after, re.IGNORECASE):
            return True
    if re.match(r"\s*\(?\x00\d+\x00", after) or re.search(r"\x00\d+\x00\)?\s*$", before):
        return True
    # Between the separators a `where` is built with: "Ask · screen".
    if re.search(rf"[{_SEPARATORS}]\s*$", before.split("\n")[-1]) \
            and re.match(rf"\s*(?:[{_SEPARATORS}]|$)", after.split("\n")[0]):
        return True
    # Alone on its line, in a list item or field ("- screen: off"), or as
    # the whole of a field the report built from entity data.
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    head = text[line_start:start]
    tail = text[end:len(text) if line_end < 0 else line_end]
    return bool(_LINE_LEAD_RE.fullmatch(head) and _LINE_TAIL_RE.fullmatch(tail))


def _file() -> Path:
    return data_dir() / "aliases.json"


class Aliases:
    """The map, loaded once per pass and saved once if it grew."""

    def __init__(self, data: dict | None = None):
        data = data if isinstance(data, dict) else {}
        self.ids: dict[str, str] = {k: v for k, v in (data.get("ids") or {}).items()
                                    if isinstance(k, str) and isinstance(v, str)}
        self.names: dict[str, str] = {k: v for k, v in (data.get("names") or {}).items()
                                      if isinstance(k, str) and isinstance(v, str)}
        self.counters: dict[str, int] = {
            k: int(v) for k, v in (data.get("counters") or {}).items()
            if isinstance(k, str) and isinstance(v, int)}
        self.dirty = False

    # -- persistence -------------------------------------------------------

    @classmethod
    def load(cls) -> "Aliases":
        try:
            return cls(json.loads(_file().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        if not self.dirty:
            return
        atomic_write.write_json(_file(), {
            "ids": self.ids, "names": self.names, "counters": self.counters},
            mode=0o600)
        self.dirty = False

    # -- minting -----------------------------------------------------------

    def _next(self, kind: str) -> int:
        n = self.counters.get(kind, 0) + 1
        self.counters[kind] = n
        self.dirty = True
        return n

    def entity(self, entity_id: str) -> str:
        if entity_id not in self.ids:
            domain = entity_id.split(".", 1)[0]
            self.ids[entity_id] = f"{domain}.{domain}_{self._next(domain):02d}"
        return self.ids[entity_id]

    def name(self, name: str, kind: str) -> str:
        key = f"{kind}:{name}"
        if key not in self.names:
            label = kind.replace("_", " ").capitalize()
            self.names[key] = f"{label} {self._next('name:' + kind)}"
        return self.names[key]

    def learn(self, names: dict) -> None:
        """Mint aliases for every friendly name and room in ``names``
        (`server._NAMES`'s shape: ``{entity_id: {"name", "area"}}``), so the
        numbering follows the house rather than the order faults happen."""
        for eid in sorted(names or {}):
            row = names.get(eid) or {}
            if not isinstance(row, dict):
                continue
            domain = eid.split(".", 1)[0]
            if domain in ENTITY_DOMAINS:
                self.entity(eid)
            nm = str(row.get("name") or "").strip()
            if len(nm) >= MIN_NAME:
                self.name(nm, domain if domain in ENTITY_DOMAINS else "thing")
            area = str(row.get("area") or "").strip()
            if len(area) >= MIN_NAME:
                self.name(area, "room")
        # The words inside those names that are a person's or a room's,
        # and the names Morph's configuration draws: after every whole
        # name, so a word that is already one keeps its own alias.
        known = {k.split(":", 1)[1].casefold() for k in self.names}
        found: list[tuple[str, str]] = []
        for eid in sorted(names or {}):
            row = names.get(eid) or {}
            if isinstance(row, dict):
                domain = eid.split(".", 1)[0]
                found += name_parts(str(row.get("name") or ""),
                                    "person" if domain in PERSONAL_KINDS else domain,
                                    eid, str(row.get("class") or ""))
                found += name_parts(str(row.get("area") or ""), "room")
        for real, kind in house_config_names():
            real = " ".join(str(real).split())[:60]
            if kind != "person" and _common(real):
                continue
            found.append((real, kind))
            found += name_parts(real, kind)
        for real, kind in found:
            if len(real) >= MIN_NAME and real.casefold() not in known \
                    and not is_generic(real, kind):
                known.add(real.casefold())
                self.name(real, kind)

    # -- applying ----------------------------------------------------------

    def apply(self, text: str, strict: bool = False) -> str:
        """``text`` with every id, name and room swapped for its alias.
        ``strict`` is for a person's typed words and logs: every name is
        replaced wherever it stands, the rule before one-word names were
        read by their use."""
        text = str(text or "").replace("\x00", "")
        # Ids first, parked behind placeholders while the names run: a room
        # called "Kitchen" would otherwise rewrite `light.kitchen` into
        # `light.Room 2`, and a lamp called "Light" would rewrite the
        # alias `light.light_07` that was just put there.
        parked: list[str] = []

        def _id(match: re.Match) -> str:
            domain, obj = match.group(1), match.group(2)
            if domain not in ENTITY_DOMAINS or obj in SERVICE_WORDS:
                return match.group(0)
            parked.append(self.entity(f"{domain}.{obj}"))
            return f"\x00{len(parked) - 1}\x00"

        text = ENTITY_RE.sub(_id, text)
        # Names, longest first, as whole words, case-insensitively — a
        # sentence starting with a room's name capitalises it.
        # ONE pass over an alternation, so an alias just written ("Room 2")
        # is never read again by a shorter real name ("Room").
        lookup: dict[str, str] = {}
        # A one-word name every holder of which is ordinary, with the kinds
        # it names (their domain words are where it stands as a name).
        ordinary: dict[str, set] = {}
        strict_names: set[str] = set()
        for key, alias in self.names.items():
            kind, real = key.split(":", 1)
            if len(real) >= MIN_NAME and not is_generic(real, kind):
                folded = real.casefold()
                lookup.setdefault(folded, alias)
                if is_ordinary(real, kind):
                    ordinary.setdefault(folded, set()).add(kind)
                else:
                    strict_names.add(folded)
        kinds = {} if strict else {
            k: frozenset(v) for k, v in ordinary.items() if k not in strict_names}

        def _name(m: re.Match) -> str:
            word = m.group(1)
            folded = word.casefold()
            if (folded in kinds and word.islower()
                    and not _typed_words(m.string, m.start(1))
                    and not _used_as_name(m.string, m.start(1), m.end(1), kinds[folded])):
                return word
            return lookup[folded]

        if lookup:
            pattern = re.compile(
                r"(?<![\w])(" + "|".join(re.escape(r) for r in sorted(
                    lookup, key=len, reverse=True)) + r")(?![\w])", re.IGNORECASE)
            text = pattern.sub(_name, text)
        text = _MOBILE_RE.sub("mobile_app_device", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m.group(1))], text)
