"""Device and sensor checks.

The physical half of the house: what has gone quiet, what is running on a
dying battery, what is reading a number no sensor should read, what has sat
on exactly one value for a week, and what belongs to an integration that is
no longer there.
"""
from __future__ import annotations

import re

import numfmt

from ._util import (SOFTWARE_DOMAINS, House, after_restart, age_days,
                    counted_names, domain_of, evidence_for, join_names, num,
                    parse_ts, spell_integration, when)

UNAVAILABLE_DAYS = 1.0
BATTERY_LOW_PCT = 15
BATTERY_SILENT_DAYS = 7
# A battery sensor that reads 0 today and has read nothing but 0 for at
# least this many days of its recorded history is not a cell running down:
# a mains-powered device publishing an unused battery field (a Z-Wave
# energy meter carries the command class and fills it with 0) reads 0 from
# the day it was included. A real battery that went flat has a history
# above 0 before it. Fewer days than this is too short to tell the two apart,
# so the row is still filed.
BATTERY_NEVER_CHARGED_DAYS = 7
FROZEN_DAYS = 7
FROZEN_MIN_DAYS = 5
# **A sensor with no `device_class` is not making a measurement claim, and
# that is where every false frozen row came from.** The scorecard read 0
# confirmed against 6 marked Wrong with ten more filed in the same pass —
# the tab saying this rule is wrong about this house, which is exactly what
# `dev.implausible` looked like before the hot-sensor gate, and the same
# failure the check catalog opens by naming.
#
# `state_class: measurement` is already required (the snapshot only fetches
# statistics for those), and it is not enough: an integration sets it on a
# great many numbers that are not measurements of anything that varies — a
# fixed tariff, a rated capacity, a configured current limit, a nameplate
# figure, a count of devices on a hub, a vendor index. Each of those reads
# exactly one value for a week because that is what it IS, and "a real
# sensor moves" is a true sentence about the wrong kind of number.
#
# What those have in common is that nothing declares what kind of quantity
# they are. A stuck thermometer carries `temperature`, a stuck plug carries
# `power`, a stuck barometer carries `pressure` — every case this check is
# for names its own class — so requiring one keeps the whole point and
# drops the rest. It is a guess made in the direction where being wrong is
# cheap, which is `measures_something_hot`'s trade: a missed stuck sensor
# costs one finding nobody got, a false one costs the list.
#
# `monetary` is named as well because a fixed tariff carries it and sits
# still for years, and `aqi`/`enum` because neither is a continuous
# quantity. `battery` and `signal_strength` were already out.
#
# `duration` is the one the first cut missed, and it is the clearest case
# in the set: a duration is a SPAN, and the spans a house publishes are
# almost all either configured or last-measured. A button's hold time, a
# timer's length, how long the last run took, a track's length — each
# reads one value until somebody changes it or runs the thing again,
# which on anything used occasionally is weeks. It reached the list the
# way `temperature`'s ambient gap did: a real house, a real row, and a
# sensor that was working exactly as intended.
FROZEN_SKIP_CLASSES = frozenset({
    "battery", "signal_strength", "monetary", "enum", "aqi",
    "timestamp", "date", "duration",
})
# A device class says what is measured, not that it is MEASURED. An
# estimate integration publishes one figure for a current or a power by
# design — the plug's rated draw, a figure somebody typed in — under the
# same class a real meter carries, and rewrites the state every day with
# the same number, so it reads exactly like a sensor stuck on its last
# value. What gives it away is that it says so: the name calls it an
# estimate, a nominal or rated figure, or the integration reports a fixed
# calculation. Whole words only, so a name that merely contains one is
# not read as one. A name gate, made in the direction FROZEN_SKIP_CLASSES
# makes its own: a stuck sensor called "estimated" costs one finding.
FIXED_FIGURE_WORDS = frozenset({"estimate", "estimated", "nominal", "rated",
                                "assumed", "configured"})
FIXED_MODE_ATTRS = ("calculation_mode", "strategy")


def states_a_fixed_figure(house: House, eid: str, attrs: dict) -> bool:
    """Whether a reading says it is an estimate or a set figure, not a meter."""
    reg = house.registry.get(eid) or {}
    names = (attrs.get("friendly_name"), reg.get("name"),
             reg.get("original_name"), eid.split(".", 1)[-1])
    for name in names:
        words = set(re.split(r"[^a-z0-9]+", str(name or "").lower()))
        if words & FIXED_FIGURE_WORDS:
            return True
    return any(str(attrs.get(key) or "").lower() == "fixed"
               for key in FIXED_MODE_ATTRS)


# A battery's voltage, or any low DC voltage, sits still by design. A cell
# reported at 0.1 V resolution reads 1.3 V for weeks while it discharges
# underneath that step, and a regulated 5 V or 12 V supply rail reads one
# value because regulating it is its whole job. What `dev.frozen` is for on
# a voltage sensor is mains: a supply that wanders by volts every hour and
# has stopped wandering. So a voltage reads as a battery's — and is skipped —
# when its name says battery or cell, when its device also reports a battery
# level, or when it is a DC level under `DC_VOLTAGE_MAX` (mains is 100 V and
# up everywhere). The cheap direction: a stuck 3 V probe costs one finding
# nobody got, and "this battery sensor is broken" on a healthy one costs the
# list, which is what a real house marked Not a problem on two siblings.
DC_VOLTAGE_MAX = 15.0
BATTERY_VOLTAGE_WORDS = frozenset({"battery", "batt", "cell", "vbat"})


def reads_a_battery_voltage(house: House, eid: str, attrs: dict) -> bool:
    reg = house.registry.get(eid) or {}
    for name in (attrs.get("friendly_name"), reg.get("name"),
                 reg.get("original_name"), eid.split(".", 1)[-1]):
        words = set(re.split(r"[^a-z0-9]+", str(name or "").lower()))
        if words & BATTERY_VOLTAGE_WORDS:
            return True
    dev_id = reg.get("device_id")
    if dev_id:
        for row in house.entities:
            if row.get("device_id") != dev_id or row.get("entity_id") == eid:
                continue
            other = house.states.get(row.get("entity_id") or "") or {}
            if (other.get("attributes") or {}).get("device_class") == "battery":
                return True
    value = num((house.states.get(eid) or {}).get("state"))
    unit = str(attrs.get("unit_of_measurement") or "").strip()
    if value is not None and unit in ("V", "mV"):
        volts = value / 1000.0 if unit == "mV" else value
        if abs(volts) < DC_VOLTAGE_MAX:
            return True
    return False


# And a cap, for `base.unusual`'s reason. More than a handful of sensors
# frozen at once is not a house with a handful of broken sensors — it is
# this rule having stopped describing the house (a recorder purge, an
# integration reloaded, a statistics backfill), and fifty rows would be
# reporting the measurement rather than the home.
FROZEN_MAX_ROWS = 5

# Sane physical ranges by device class and unit. A reading outside these is
# a broken sensor, not a hot day.
#
# **The temperature bounds are an AMBIENT range, and `device_class:
# temperature` does not mean ambient.** That gap fired this check on
# healthy houses for its whole life: a 3D printer reported its bed at
# 65°C and its nozzle at 220°C, and brAIn filed four `serious`-looking
# rows saying a temperature sensor cannot read outside -40–60°C. It can;
# that one measures a heater. So do an oven, a kettle, a sous-vide, a
# boiler flow pipe, a CPU, a water tank and a pizza stone. The producer
# scorecard is what caught it — 0 confirmed against 2 marked Wrong,
# which is the tab saying this rule is wrong about this house — and it
# is the exact failure the check catalog opens by naming: a check that
# fires on a healthy house is worse than no check, because it is the one
# a person learns to ignore first.
#
# So the ambient range is applied only where the sensor is plausibly
# measuring room air, and `_MEASURES_SOMETHING_HOT` is the gate. It is a
# name gate, which is a guess, and it is made in the direction where
# being wrong is cheap — the same trade `chore.waiting` writes down for
# the same reason. A missed implausible reading costs one finding nobody
# got; a false one costs the list.
_RANGES = {
    ("temperature", "°C"): (-40.0, 60.0),
    ("temperature", "°F"): (-40.0, 140.0),
    ("humidity", "%"): (0.0, 100.0),
    ("battery", "%"): (0.0, 100.0),
    ("illuminance", "lx"): (0.0, 200000.0),
    ("pressure", "hPa"): (800.0, 1100.0),
    ("pressure", "mbar"): (800.0, 1100.0),
}


# Words that mean "this is not the temperature of a room". Matched on the
# entity id and on the friendly name, as whole words where a bare one
# would be too eager: `bed` is a hotend's build plate and also a bedroom,
# so it is only read as hot beside a printer word. Deliberately long and
# deliberately incomplete — every entry is a class of device that really
# does live outside -40–60°C, and anything missed simply goes back to
# being checked as if it were a room, which is where it started.
_HOT_WORDS = frozenset("""
nozzle extruder hotend hot_end heatbreak heatsink heat_sink
oven grill griddle bbq barbecue smoker fryer hob stove burner kettle
boiler flue exhaust chimney furnace radiator manifold
flow return coolant condenser compressor refrigerant superheat
processor
engine motor inverter transformer inlet outlet
sauna steam hot_water hotwater dhw cylinder immersion
sous_vide sousvide probe meat roast food griddle
tank kiln soldering iron laser
""".split())
# A computer's own parts: its chips, its drives. A subset of the words
# above, named apart because `base.unusual` asks it — a processor's
# temperature follows its load, never the hour of the house's week.
_COMPUTER_WORDS = frozenset("""
cpu gpu chip core soc die vrm nvme ssd drive disk
hdd sata composite pkg x86 chipset apu dimm mainboard motherboard
processor package cputemp coretemp k10temp acpitz tctl tdie pch
""".split())
_HOT_WORDS = _HOT_WORDS | _COMPUTER_WORDS
# `bed`, `chamber`, `plate` and `tool` are only hot next to one of these
# — a heated bed is a printer's, a chamber is its enclosure and `tool0`
# is OctoPrint's name for the hotend, while a bedroom sensor and a
# chamber thermostat are ordinary rooms.
_HOT_WHEN_PAIRED = frozenset({"bed", "chamber", "plate", "platform", "tool"})
_PAIR_WORDS = frozenset({"printer", "print", "3d", "bambu", "prusa", "ender",
                         "creality", "voron", "klipper", "octoprint",
                         "anycubic", "elegoo", "filament", "extruder",
                         "nozzle", "hotend", "kiln", "moonraker",
                         "prusalink", "mainsail", "fluidd"})

# The integration that provides a reading is a fact, not a guess from its
# name: every temperature a printer integration publishes is a heater's or
# its enclosure's, and every one a system monitor publishes is a chip's or
# a drive's. Read before the name — the printer word on a Bambu Lab
# reading is on the DEVICE ("P1S"), never on "Bed temperature", which is
# how a working printer was filed as impossible three times.
PRINTER_PLATFORMS = frozenset({
    "octoprint", "prusalink", "bambu_lab", "moonraker", "klipper",
    "elegoo_printer", "anycubic_cloud", "creality_cloud", "duet3d",
    # BRUH Bambu Studio's own integration: a status and two heaters per
    # printer, and nothing on it is a room.
    "bruh_bambu",
})
COMPUTER_PLATFORMS = frozenset({
    "systemmonitor", "glances", "hddtemp", "openhardwaremonitor",
    "librehardwaremonitor", "proxmoxve", "synology_dsm", "qnap", "unraid",
    "truenas", "netdata", "hp_ilo", "scrutiny",
})
HOT_PLATFORMS = PRINTER_PLATFORMS | COMPUTER_PLATFORMS
# What a DEVICE's own name, model or maker may add. Narrower than the
# entity's words on purpose: a thermostatic radiator valve reads the room
# it sits in, so "radiator" on the device says nothing about the reading,
# while a reading on a printer or a computer is a heater's or a chip's.
_HOT_DEVICE_WORDS = _PAIR_WORDS | frozenset({
    "computer", "server", "nas", "synology", "qnap", "unraid", "truenas",
    "proxmox", "raspberry", "nuc", "pc", "laptop", "desktop", "cpu", "gpu"})


def _words(*parts: str) -> set[str]:
    out: set[str] = set()
    for part in parts:
        for word in str(part or "").lower().replace(".", " ").replace(
                "-", " ").replace("_", " ").split():
            out.add(word)
            out.add(word.strip("0123456789"))
    return {w for w in out if w}


def _hot_by_name(eid: str, name: str, device_names=()) -> bool:
    words = _words(eid, name)
    if words & _HOT_WORDS:
        return True
    device = _words(*device_names)
    if device & _HOT_DEVICE_WORDS:
        return True
    return bool(words & _HOT_WHEN_PAIRED and (words | device) & _PAIR_WORDS)


def heat_context(house, eid: str) -> tuple[str, tuple[str, ...]]:
    """The providing platform and the device's own names, for the gate.

    ``house`` is a `House` (or None, which is no context and the gate
    reading the entity's own words exactly as it always did).
    """
    if house is None:
        return "", ()
    reg = house.registry.get(eid) or {}
    dev = house.device_of(eid) or {}
    names = tuple(str(dev.get(k) or "") for k in
                  ("name_by_user", "name", "model", "manufacturer")
                  if dev.get(k))
    return str(reg.get("platform") or ""), names


def measures_something_hot(eid: str, name: str, world=None,
                           house=None) -> bool:
    """Whether this sensor plainly measures something other than room air.

    Public because `base.unusual` stands down for what `dev.implausible`
    claims, and the two have to agree about which sensors those are —
    the same reason `out_of_range` is shared and `_zwave_dead_devices`
    is.

    ``house`` adds what the registries know: the providing integration,
    which answers first (a printer's or a system monitor's temperature is
    never room air, whatever a reading says), and the device's names,
    which the word list reads beside the entity's own.

    `world` is the snapshot's entity readings (`world_model`): a
    confident reading of `heater` or `room_air` answers in any language,
    and the word list above answers whenever there is no reading or it
    was unsure — which is exactly how this answered before.
    """
    import world_model  # noqa: PLC0415 — panel-local, a leaf

    platform, device_names = heat_context(house, eid)
    if platform in HOT_PLATFORMS:
        return True
    return world_model.measures_heat(
        world, eid, lambda: _hot_by_name(eid, name, device_names))


def computer_temperature(house, eid: str) -> bool:
    """Whether this temperature is a computer's chip or drive.

    The providing integration first (a system monitor's temperatures are
    all a chip's or a drive's), then the chip and drive words on the
    entity, or a computer word on its device. A confident `world_model`
    reading of room air answers no, as it does for the hot gate.
    """
    st = house.states.get(eid) or {}
    attrs = st.get("attributes") or {}
    if str(attrs.get("device_class") or "") != "temperature":
        return False
    name = str(attrs.get("friendly_name") or "")
    platform, device_names = heat_context(house, eid)
    if platform in COMPUTER_PLATFORMS:
        return True
    if not measures_something_hot(eid, name, house.world, house):
        return False
    return bool(_words(eid, name) & _COMPUTER_WORDS
                or _words(*device_names) & (_HOT_DEVICE_WORDS - _PAIR_WORDS))


def printer_heater(house, eid: str) -> bool:
    """Whether this temperature is a 3D printer's heater or enclosure.

    A heater (`measures_something_hot`) on a printer: the providing
    integration is a printer's, or a printer word is on the entity or its
    device. Shared by `base.unusual`, which leaves these to
    `base.heater_idle`, and that check, which judges them by whether the
    printer is printing — the one thing an hour-of-the-week band cannot see.
    """
    st = house.states.get(eid) or {}
    attrs = st.get("attributes") or {}
    if str(attrs.get("device_class") or "") != "temperature":
        return False
    name = str(attrs.get("friendly_name") or "")
    if not measures_something_hot(eid, name, house.world, house):
        return False
    platform, device_names = heat_context(house, eid)
    if platform in PRINTER_PLATFORMS:
        return True
    return bool(_words(eid, name, *device_names) & _PAIR_WORDS)


# brAIn's own integration. Its entities are readings ABOUT this add-on — the
# usage figures, the health verdict, the open-findings count — and the
# device checks reported them as hardware: "brAIn Usage Limits has been
# unavailable for more than a day — check its power and its connection
# (batteries, Wi-Fi, the hub it pairs through)", on the day the usage
# tracker was stuck. The batteries advice is wrong for a sensor with no
# batteries, and the fault it was about is `health.py`'s to report, which
# it does with the switch named. A check that files a finding about the
# add-on's own sensor is the add-on filing a bug report against itself
# under somebody else's remedy.
SELF_PLATFORMS = frozenset({"brain"})


def _live_hardware(house: House):
    for eid, st in house.states.items():
        if domain_of(eid) in SOFTWARE_DOMAINS:
            continue
        if not house.enabled(eid):
            continue
        if (house.registry.get(eid) or {}).get("platform") in SELF_PLATFORMS:
            continue
        yield eid, st


def is_node_status(entity_id: str, reg: dict) -> bool:
    """Whether this is the node status sensor Z-Wave JS publishes.

    Read off what the integration REGISTERED — its translation key
    `node_status`, or its unique id `<home id>.<node id>.node_status` —
    and never off the entity id alone. The entity id is derived from a
    name: it is in the house's own language, it is whatever somebody
    renamed it to, and a second device of the same name gets `_2` on the
    end. Reading the suffix missed a node the controller had declared
    dead for days, and its frozen 0% battery was filed in its place. The
    suffix stays as the answer for a registry row that carries neither
    field (an older Core), which is what this always did.
    """
    if not entity_id.startswith("sensor."):
        return False
    if reg.get("platform") != "zwave_js":
        return False
    if reg.get("translation_key") == "node_status":
        return True
    if str(reg.get("unique_id") or "").endswith(".node_status"):
        return True
    return entity_id.endswith("_node_status")


def _zwave_dead_nodes(house: House) -> list[dict]:
    """Every device whose Z-Wave node status sensor reads `dead`.

    Both the device id and the **sensor that said so**, because two
    different callers need two different halves of the same answer:
    ``dev.unavailable`` and ``dev.zwave_dead`` want the device, and
    ``panel/healing.py`` wants an entity to ping. Computing it twice is
    how they would come to disagree about which box this is.
    """
    out: list[dict] = []
    for eid, st in sorted(house.states.items()):
        if not is_node_status(eid, house.registry.get(eid) or {}):
            continue
        if str(st.get("state") or "").lower() != "dead":
            continue
        dev = house.device_of(eid)
        if dev:
            out.append({"device_id": dev["id"], "entity_id": eid,
                        "name": house.device_name(dev)})
    return out


def _zwave_dead_devices(house: House) -> set[str]:
    """Device ids whose Z-Wave node status sensor reads `dead`."""
    return {n["device_id"] for n in _zwave_dead_nodes(house)}


def zwave_dead_nodes(snap: dict) -> list[dict]:
    """The public door onto the same answer, for `panel/healing.py`."""
    return _zwave_dead_nodes(House(snap))


# ---------------------------------------------------------------------------
# dev.unavailable — grouped by device, or a dead hub files forty rows
# ---------------------------------------------------------------------------

def _restart_note(snap: dict, st: dict) -> str:
    """A sentence when the drop came right after Home Assistant started.

    Said in the detail and never the text — the text is what the store
    dedupes on — and only when a start is on record within
    `RESTART_WINDOW_S` before the change: a device that did not come back
    from a restart is usually its integration, not its batteries, and a
    card that does not mention the restart sends somebody to the wrong
    end of the house.
    """
    if after_restart(snap, st.get("last_changed")) is None:
        return ""
    return (" It went unavailable right after Home Assistant restarted, so "
            "its integration may not have come back from the restart — "
            "reloading the integration is the first thing to try.")


# An entity whose state is computed from other entities rather than read off
# a device. A light group goes unavailable when every light in it does; a
# template sensor when what it reads does. Its own row is the same fault said
# again, under a remedy ("check its power, reload its integration") that
# points at the helper rather than at the hardware behind it.
DERIVED_PLATFORMS = frozenset({
    "group", "template", "min_max", "switch_as_x", "derivative",
    "integration", "statistics", "threshold", "trend", "filter",
    "utility_meter", "combine", "mold_indicator", "bayesian", "compensation",
})
# A config entry in one of these states is an integration that did not set
# up, and every entity it provides is unavailable because of that one fact.
# `sys.entry_failed` reports it, naming the integration and its error; a row
# per device here is the same fault said once per device under a remedy
# (batteries, Wi-Fi) that cannot reach it. An entry somebody unloaded is a
# decision, and not news either.
ENTRY_NOT_LOADED = frozenset({
    "setup_error", "setup_retry", "migration_error", "not_loaded",
    "failed_unload",
})
# What a device's settings page carries. An unavailable firmware or "cloud
# connection" entity on a device that still answers is not the device
# having gone away.
SETTINGS_CATEGORIES = frozenset({"diagnostic", "config"})
# Integrations whose entities are features somebody switches on or off on
# the device itself. The companion app publishes a sensor per phone feature
# (kiosk mode, a camera, an activity reading) and one that is turned off in
# the app reads unavailable for ever while the phone goes on reporting
# everything else — a setting, not a fault. On a device that still answers
# such an entity says nothing; a phone that has gone quiet altogether is
# still reported as the device.
FEATURE_PLATFORMS = frozenset({"mobile_app"})


def _down(st: dict | None) -> bool:
    return bool(st) and st.get("state") == "unavailable"


def _members(house: House, eid: str) -> list[str]:
    """The entities a group names, when its state still carries them."""
    raw = ((house.states.get(eid) or {}).get("attributes") or {}).get(
        "entity_id")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, str) and "." in m and m != eid]


def _entry_not_loaded(snap: dict, reg: dict) -> bool:
    entry_id = reg.get("config_entry_id")
    if not entry_id:
        return False
    for entry in snap.get("config_entries") or []:
        if isinstance(entry, dict) and entry.get("entry_id") == entry_id:
            return str(entry.get("state") or "") in ENTRY_NOT_LOADED
    return False


def _device_answers(house: House, dev_id: str) -> bool:
    """Whether a primary entity on this device still reports a state.

    A device that has gone away takes every entity with it. One whose
    light still answers while its "cloud" sensor does not has not gone
    anywhere, and "check its power and its connection" is the wrong fix
    for it.
    """
    for row in house.entities:
        if row.get("device_id") != dev_id or row.get("disabled_by"):
            continue
        if str(row.get("entity_category") or "") in SETTINGS_CATEGORIES:
            continue
        st = house.states.get(row.get("entity_id") or "")
        if st and st.get("state") not in ("unavailable", "unknown", None):
            return True
    return False


def unavailable(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    # A node the Z-Wave controller has declared dead is dev.zwave_dead's
    # row, with a mesh fix on it. Reporting the same box twice under two
    # different fixes is how a list stops being read.
    dead_devices = _zwave_dead_devices(house)
    # A Wi-Fi client UniFi still holds while its entities are gone is
    # `net.wifi_hung`'s row (named by its access point), and a Zigbee
    # device gone quiet is `net.zigbee_silent`'s or `dev.zha_unseen`'s —
    # the same box under one fix, never two.
    from . import network  # noqa: PLC0415 — network imports this module
    claimed = (network.wifi_hung_devices(house, now)
               | network.zigbee_quiet_devices(house, now))
    by_device: dict[str, list[tuple[str, float]]] = {}
    loose: list[tuple[str, float]] = []
    derived: list[tuple[str, float]] = []
    for eid, st in _live_hardware(house):
        if st.get("state") != "unavailable":
            continue
        age = age_days(st.get("last_changed"), now)
        if age is None or age < UNAVAILABLE_DAYS:
            continue
        # An entity whose integration is gone is the `restored` check's.
        if (st.get("attributes") or {}).get("restored"):
            continue
        reg = house.registry.get(eid) or {}
        # Somebody hid it: they have decided it is not something they
        # want to look at, and a serious card about it is the opposite.
        if reg.get("hidden_by") == "user":
            continue
        # The integration did not set up: `sys.entry_failed`'s row.
        if _entry_not_loaded(snap, reg):
            continue
        if (reg.get("platform") in DERIVED_PLATFORMS
                or (_members(house, eid) and not house.device_of(eid))):
            derived.append((eid, age))
            continue
        dev = house.device_of(eid)
        if dev:
            if dev["id"] in dead_devices or dev["id"] in claimed:
                continue
            by_device.setdefault(dev["id"], []).append((eid, age))
        else:
            loose.append((eid, age))
    out = []
    for dev_id, rows in by_device.items():
        dev = house.devices[dev_id]
        answers = _device_answers(house, dev_id)
        if answers:
            # The device is there. What is left is a primary entity that
            # stopped reporting on a device that did not; a settings-page
            # entity on its own is not worth a card.
            rows = [r for r in rows if str((house.registry.get(r[0]) or {})
                    .get("entity_category") or "") not in SETTINGS_CATEGORIES
                    and (house.registry.get(r[0]) or {}).get("platform")
                    not in FEATURE_PLATFORMS]
            if not rows:
                continue
        # The row is filed under whichever entity has been down longest, so
        # a Wrong given about it is written under that one; the next pass
        # may lead with a sibling (a restart re-stamps them all). An answer
        # about one entity of a device reaches its siblings
        # (`House.withheld_by`'s device step), so what is left here is only
        # what nobody answered — a safety sibling, which no answer covers.
        rows = [r for r in rows if house.should_report(r[0], "dev.unavailable")]
        if not rows:
            continue
        rows.sort(key=lambda r: r[1], reverse=True)
        first, longest = rows[0]
        name = house.device_name(dev)
        if answers:
            out.append({
                "text": f"{house.name(first)} on {name} has been unavailable "
                        "for more than a day",
                "detail": f"Since {when(house.states[first].get('last_changed'))}"
                          + (f"; {len(rows)} of its entities are affected"
                             if len(rows) > 1 else "")
                          + f". {name} itself is still answering, so this is "
                            "that entity rather than the device."
                          + house.placed(first, house.name(first), name)
                          + _restart_note(snap, house.states[first]),
                "fix": "The device is reachable, so this is one of its "
                       "features: check what that entity reads from (a "
                       "sensor lead, an accessory, a cloud service), or "
                       "disable the entity "
                       "if the device does not support it.",
                "severity": "warning",
                "fixable": False,
                "entity_id": first,
            })
            continue
        out.append({
            "text": f"{name} has been unavailable for more than a day",
            "detail": f"Since {when(house.states[first].get('last_changed'))}"
                      + (f"; {len(rows)} of its entities are affected"
                         if len(rows) > 1 else "")
                      + "."
                      + house.placed(first, name)
                      + _restart_note(snap, house.states[first]),
            "fix": "Check its power and its connection (batteries, Wi-Fi, "
                   "the hub it pairs through), then reload its integration.",
            "severity": "serious",
            "fixable": False,
            "entity_id": first,
        })
    for eid, age in loose:
        if not house.should_report(eid, "dev.unavailable"):
            continue
        out.append({
            "text": f"{house.name(eid)} has been unavailable for more than "
                    "a day",
            "detail": f"Since {when(house.states[eid].get('last_changed'))}."
                      + house.placed(eid)
                      + _restart_note(snap, house.states[eid]),
            "fix": "Check whatever provides it, then reload its integration.",
            "severity": "serious",
            "fixable": False,
            "entity_id": eid,
        })
    out.extend(_derived_rows(snap, house, derived, now))
    return out


def _derived_rows(snap: dict, house: House, derived: list, now: float) -> list:
    """A group or helper that is down, said only where it is the fault.

    A helper's state is made of other entities, so one that is unavailable
    is almost always its inputs being unavailable — and those are reported
    by name above, under the fix that can reach them. Said here only when
    the inputs are known and some of them are fine (a member renamed or
    removed, a helper pointing at nothing), with that as the fix. A helper
    whose inputs cannot be read is one row only while no hardware of its
    kind is down beside it, because then there is nothing else that could
    be the cause.
    """
    out = []
    down_domains = {domain_of(e) for e, st in _live_hardware(house)
                    if _down(st) and (house.registry.get(e) or {}).get(
                        "platform") not in DERIVED_PLATFORMS}
    for eid, _age in derived:
        members = _members(house, eid)
        reg = house.registry.get(eid) or {}
        kind = "group" if (reg.get("platform") == "group" or members) \
            else (str(reg.get("platform") or "").replace("_", " ")
                  + " helper").strip()
        if members:
            missing = [m for m in members if not house.exists(m)]
            down = [m for m in members if _down(house.states.get(m))]
            if not missing and len(down) == len(members):
                house._note({"kind": "dedupe", "subject": eid,
                             "check": "dev.unavailable",
                             "reason": "every member of this group is "
                                       "unavailable and reported by name",
                             "text": ""})
                continue
            if missing:
                fix = (f"It is a {kind} that names "
                       f"{join_names([house.label(m) for m in missing])}, "
                       "which no longer exist"
                       f"{'s' if len(missing) == 1 else ''} — edit the "
                       "group's members rather than reloading it.")
            else:
                fix = (f"It is a {kind} of "
                       f"{join_names([house.label(m) for m in members])}; a group "
                       "goes unavailable when its members do, so check "
                       "those rather than the group.")
        else:
            if domain_of(eid) in down_domains:
                house._note({"kind": "dedupe", "subject": eid,
                             "check": "dev.unavailable",
                             "reason": f"a {kind} goes unavailable with what "
                                       "it reads, and that is reported by name",
                             "text": ""})
                continue
            fix = (f"It is a {kind}, so it reads unavailable when what it is "
                   "built from does — check the entities it reads, or its "
                   "configuration.")
        if not house.should_report(eid, "dev.unavailable"):
            continue
        out.append({
            "text": f"{house.name(eid)} has been unavailable for more than "
                    "a day",
            "detail": f"Since {when(house.states[eid].get('last_changed'))}."
                      + house.placed(eid)
                      + _restart_note(snap, house.states[eid]),
            "fix": fix,
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.battery_low — a threshold, and the case a threshold misses
# ---------------------------------------------------------------------------

def _is_battery(st: dict) -> bool:
    attrs = st.get("attributes") or {}
    return attrs.get("device_class") == "battery" and attrs.get(
        "unit_of_measurement") == "%"


# Batteries somebody CHARGES rather than replaces. A phone sits under 15%
# most evenings and is plugged in at bedtime; an EV, a home battery and a
# UPS run their charge down and back up by design; a robot vacuum goes
# back to its dock. Every one of them carries `device_class: battery` in
# percent, so `dev.battery_low` filed "Replace the battery." about a
# phone — the wrong remedy on a row that was never a fault, and a fresh
# one on every dip, because the row clears the moment it recharges.
#
# Decided by the integration that provides the battery and by what else
# the device is, never by its name. The platforms are the ones whose
# battery is the rechargeable kind by construction: the companion app
# (phones, watches, tablets, laptops), UPS monitors, home batteries and
# inverters, EVs, and robot vacuums and mowers. An integration that
# covers both kinds (Xiaomi's, Gardena's — a vacuum and a water timer on
# AA cells) is deliberately absent and decided by what else the device is.
#
# What none of those signals can settle — a battery on a device whose
# integration is not on the list and that has nothing else beside it — is
# asked of the house's own reading (`world_model`), which reads the maker,
# model and name in whatever language the house uses, and is believed only
# above its confidence floor. It comes LAST: a reading may add a charged
# battery the integration could not name, and never takes one away.
RECHARGEABLE_PLATFORMS = frozenset({
    "mobile_app",
    "nut", "apcupsd",
    "powerwall", "enphase_envoy", "solaredge", "fronius", "growatt_server",
    "goodwe", "solax", "huawei_solar", "sonnen", "victron_remote_monitoring",
    "tesla_fleet", "teslemetry", "tessie", "renault", "bmw_connected_drive",
    "volvo", "nissan_leaf", "mercedes_me", "kia_uvo", "smartcar",
    "polestar", "audiconnect", "volkswagen_carnet", "ohme", "zappi",
    "roborock", "ecovacs", "roomba", "neato", "sharkiq", "dreame",
    "husqvarna_automower",
})
# And a device that IS one of these, whoever provides its battery: a
# vacuum or a mower docks to charge, and anything that reports itself
# charging is charged.
RECHARGEABLE_DOMAINS = frozenset({"vacuum", "lawn_mower"})


def rechargeable(house: House, eid: str) -> bool:
    """Whether this battery is charged rather than replaced.

    Shared with `forecast.battery`, whose remedy ("have a replacement
    ready") is wrong in the same way, so the two cannot disagree about
    which batteries those are.
    """
    reg = house.registry.get(eid) or {}
    if str(reg.get("platform") or "") in RECHARGEABLE_PLATFORMS:
        return True
    device = reg.get("device_id")
    if not device:
        return _read_as_rechargeable(house, eid)
    for row in house.entities:
        if row.get("device_id") != device or not row.get("entity_id"):
            continue
        other = str(row["entity_id"])
        if domain_of(other) in RECHARGEABLE_DOMAINS:
            return True
        attrs = (house.states.get(other) or {}).get("attributes") or {}
        cls = (attrs.get("device_class") or row.get("device_class")
               or row.get("original_device_class"))
        if domain_of(other) == "binary_sensor" and cls == "battery_charging":
            return True
    return _read_as_rechargeable(house, eid)


def _read_as_rechargeable(house: House, eid: str) -> bool:
    """A confident world-model reading, and nothing guessed from a name.

    No fallback on purpose: a word list here would be the rule this
    function exists to replace, and "I could not tell" keeps the battery
    on the list of things somebody has to go and change.
    """
    import world_model  # noqa: PLC0415 — a leaf; imported where it is read
    return world_model.battery_kind(house.world, eid, None) == "rechargeable"


def _never_above_zero(snap: dict, entity_id: str) -> bool:
    """Whether the recorded history says this battery has only ever read 0.

    Read off `battery_stats` (sixty days of daily means). No history, or
    too little of it, is "I could not tell" and answers False — the row
    is filed as it always was.
    """
    rows = (snap.get("battery_stats") or {}).get(entity_id) or []
    means = [num(r.get("mean")) for r in rows if isinstance(r, dict)]
    means = [m for m in means if m is not None]
    if len(means) < BATTERY_NEVER_CHARGED_DAYS:
        return False
    return max(means) <= 0


# A power or energy reading that changed inside this window is the device
# running, whatever its battery field says.
MAINS_LIVE_S = 86400
MAINS_CLASSES = frozenset({"power", "energy", "current", "apparent_power"})


def _runs_on_mains(house: House, eid: str, now: float) -> bool:
    """Whether a sibling power or energy sensor is reporting live readings.

    A 0% battery beside watts that moved in the last day is a mains device
    filling an unused battery field — the same claim `_never_above_zero`
    makes from a week of statistics, made from the live states the snapshot
    already holds. A sensor unavailable, not a number, or still for a day is
    no evidence, and the row files as it always did.
    """
    for other in house.siblings(eid):
        st = house.states.get(other) or {}
        attrs = st.get("attributes") or {}
        if attrs.get("device_class") not in MAINS_CLASSES:
            continue
        if num(st.get("state")) is None:
            continue
        changed = parse_ts(st.get("last_changed"))
        if changed is not None and now - changed <= MAINS_LIVE_S:
            return True
    return False


def battery_low(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    # A node the Z-Wave controller has declared dead is dev.zwave_dead's
    # row: the battery it shows is the last thing it said before the mesh
    # lost it (often a frozen 0%), and "replace the battery" under it is
    # the same box under a second fix — `dev.unavailable`'s rule, through
    # the same helper so the two cannot disagree about which box that is.
    dead_devices = _zwave_dead_devices(house)
    # A Z-Wave battery node the mesh has not heard from is
    # `net.zwave_silent`'s row: the battery it shows is the last thing it
    # said, and its own row already says to check it.
    from . import network  # noqa: PLC0415 — network imports this module
    dead_devices = dead_devices | network.zwave_silent_devices(house, now)
    out = []
    flagged: list[tuple[str, dict]] = []
    for eid, st in _live_hardware(house):
        if _is_low_battery_flag(eid, st):
            flagged.append((eid, st))
            continue
        if not _is_battery(st):
            continue
        dev = house.device_of(eid)
        if dev and dev["id"] in dead_devices:
            continue
        # Charged, not replaced: see RECHARGEABLE_PLATFORMS. Both halves
        # of this check are about a cell somebody has to go and change,
        # and neither is true of a phone at 9% or an app that has not
        # reported since it was uninstalled.
        if rechargeable(house, eid):
            continue
        # Wrong on one of these rows writes an exception fact, and the
        # check has to read it, or it files the same row in new words.
        if not house.should_report(eid, "dev.battery_low"):
            continue
        level = num(st.get("state"))
        if level == 0 and (_never_above_zero(snap, eid)
                           or _runs_on_mains(house, eid, now)):
            continue
        dev = house.device_of(eid)
        who = house.device_name(dev) if dev else house.name(eid)
        if level is not None and level <= BATTERY_LOW_PCT:
            out.append({
                "text": f"{who} battery is low",
                "detail": f"{level:g}% as of {when(st.get('last_updated'))}."
                          + house.placed(eid, who),
                "fix": ("Replace the battery. If this device runs off "
                        "mains power and has no battery, disable its "
                        "battery entity in Home Assistant instead."
                        if level == 0 else "Replace the battery."),
                "severity": "warning" if level > 5 else "serious",
                "fixable": False,
                "entity_id": eid,
            })
            continue
        # A dead device stops reporting its own battery, and the last
        # value it sent is whatever it was — often a healthy number. Only
        # `last_reported` (HA 2024.4+) says whether the sensor is still
        # talking; `last_updated` does not move on an unchanged value.
        reported = st.get("last_reported")
        silent = age_days(reported, now) if reported else None
        if silent is not None and silent >= BATTERY_SILENT_DAYS \
                and st.get("state") not in ("unavailable", "unknown"):
            out.append({
                "text": f"{who} has stopped reporting its battery",
                "detail": f"Last heard {when(reported)}; "
                          f"it still shows {st.get('state')}%, which is the "
                          "last thing it said, not what it is now."
                          + house.placed(eid, who),
                "fix": "Check whether the device is still alive; a dead "
                       "battery is the usual reason it went quiet.",
                "severity": "warning",
                "fixable": False,
                "entity_id": eid,
            })
    out.extend(_flag_rows(house, flagged, dead_devices))
    return out


def _is_low_battery_flag(eid: str, st: dict) -> bool:
    """A low-battery flag: a binary sensor of class battery, on meaning low.

    Some integrations report a battery only this way (a smoke alarm, a lock,
    a Z-Wave node's notification), so a check reading percentages alone
    never saw them run down.
    """
    attrs = st.get("attributes") or {}
    return domain_of(eid) == "binary_sensor" \
        and attrs.get("device_class") == "battery"


def _flag_rows(house: House, flagged: list, dead_devices: set) -> list[dict]:
    """`dev.battery_low`'s rows for a low-battery flag that is on, where the
    device has no percentage of its own (that one already speaks)."""
    out = []
    for eid, st in flagged:
        if st.get("state") != "on":
            continue
        dev = house.device_of(eid)
        if dev and dev["id"] in dead_devices:
            continue
        if any(_is_battery(house.states.get(o) or {})
               for o in house.siblings(eid)):
            continue
        if rechargeable(house, eid):
            continue
        if not house.should_report(eid, "dev.battery_low"):
            continue
        who = house.device_name(dev) if dev else house.name(eid)
        out.append({
            "text": f"{who} battery is low",
            "detail": f"It has reported a low battery since "
                      f"{when(st.get('last_changed'))}."
                      + house.placed(eid, who),
            "fix": "Replace the battery.",
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.implausible — a reading no sensor should give
# ---------------------------------------------------------------------------

# **A heater's gate lifts the ceiling, never the floor.** The hot-sensor
# gate exists because a nozzle or a boiler pipe reads far above room air;
# nothing in a house reads below the coldest air on earth, and an outdoor
# heat-pump thermometer named for its compressor read −150 °F overnight
# while the house's outdoor reference read 54 °F (#337). With the whole
# range lifted, nothing called that impossible, the baseline learned the
# night as normal and the morning's +18 °F was filed as unusual. So the
# cold floor holds for every temperature — a few degrees below the lowest
# air temperature anywhere people live — and only cold storage (a freezer,
# a dewar, a cryogenic store, whose name says so) is allowed below it,
# down to what liquid nitrogen reaches.
COLD_FLOOR = {"°C": -55.0, "°F": -67.0}
CRYO_FLOOR = {"°C": -200.0, "°F": -328.0}
_COLD_STORAGE_WORDS = frozenset({
    "freezer", "freezers", "deepfreeze", "cryo", "cryogenic", "cryostat",
    "ult", "nitrogen", "ln2", "dewar"})
# An impossible reading the nightly baseline pass threw away is still the
# sensor's fault after it starts reading sanely again; reported for this
# long after the last one, then left to the next night.
IMPOSSIBLE_RECENT_DAYS = 2.0


def bounds_for(attrs: dict, entity_id: str = "", world=None, house=None
               ) -> tuple[float, float] | None:
    """The physical range a reading of this kind can take, or None.

    Shared by `dev.implausible`, `base.unusual` (through `out_of_range`)
    and the nightly baseline pass, which drops what falls outside it so a
    broken night never becomes a normal one.
    """
    attrs = attrs or {}
    klass = attrs.get("device_class")
    unit = attrs.get("unit_of_measurement")
    bounds = _RANGES.get((klass, unit))
    if klass != "temperature" or not bounds:
        return bounds
    name = attrs.get("friendly_name") or ""
    low, high = bounds
    # A heater's temperature is not an impossible temperature. The upper
    # bound is an ambient one and this is the only thing standing between
    # it and every oven, kettle, boiler and print head in the house.
    if measures_something_hot(entity_id, name, world, house):
        low, high = COLD_FLOOR.get(unit, low), float("inf")
    if _words(entity_id, name) & _COLD_STORAGE_WORDS:
        low = CRYO_FLOOR.get(unit, low)
    return low, high


def impossible_value(value: float | None, attrs: dict, entity_id: str = "",
                     world=None, house=None) -> bool:
    """True when ``value`` is outside what this kind of sensor can read."""
    bounds = bounds_for(attrs, entity_id, world, house)
    if not bounds or value is None:
        return False
    return not bounds[0] <= value <= bounds[1]


def out_of_range(state: dict, entity_id: str = "", world=None,
                 house=None) -> bool:
    """True when a reading is outside what its kind of sensor can produce.

    Shared with `base.unusual`, which stands down for exactly these: a
    thermometer reading 99°C is impossible before it is unusual, and the
    two checks reporting one sensor under two different fixes is how a
    list stops being read. Same reasoning — and the same shape — as
    `dev.unavailable` standing down for a dead Z-Wave node.

    ``entity_id`` is optional only because `base.unusual` calls this with
    a bare state row; the name gate reads the friendly name either way,
    and an id given is one more place to find a word like `nozzle`.
    """
    attrs = (state or {}).get("attributes") or {}
    return impossible_value(num((state or {}).get("state")), attrs,
                            entity_id, world, house)


def recently_impossible(baseline: dict | None, now: float,
                        bounds: tuple[float, float] | None = None
                        ) -> dict | None:
    """What the nightly pass threw away as impossible for this sensor, when
    the last of it was inside `IMPOSSIBLE_RECENT_DAYS`, or None.

    ``bounds`` is the range this sensor's kind can read as the pass reading
    it NOW knows it (`bounds_for` with the registries). A record a pass
    with less to go on left — one that took a chip's 90 °C for a room's —
    is not evidence once the same values are possible: given the bounds,
    a record whose lowest and highest both sit inside them is no record.
    """
    seen = (baseline or {}).get("impossible") if isinstance(
        baseline, dict) else None
    if not isinstance(seen, dict):
        return None
    last = seen.get("last")
    if not isinstance(last, (int, float)) or isinstance(last, bool):
        return None
    if now - float(last) > IMPOSSIBLE_RECENT_DAYS * 86400:
        return None
    if bounds:
        low, high = bounds
        values = [num(seen.get(k)) for k in ("lowest", "highest")]
        values = [v for v in values if v is not None]
        if values and all(low <= v <= high for v in values):
            return None
    return seen


def _range_said(key: tuple, bounds: tuple[float, float]) -> str:
    lo, hi = bounds
    if hi == float("inf"):
        return (f"a {key[0]} sensor cannot read below "
                f"{numfmt.quantity(lo, key[1])}")
    return (f"a {key[0]} sensor cannot read outside {numfmt.number(lo)}–"
            f"{numfmt.quantity(hi, key[1])}")


def _outside_said(house: House, attrs: dict) -> str:
    if attrs.get("device_class") != "temperature":
        return ""
    from .baseline import outdoor_reading  # noqa: PLC0415 — it imports us
    said = outdoor_reading(house, "temperature")
    return f" For comparison, {said}." if said else ""


IMPLAUSIBLE_FIX = ("The sensor is likely faulty or misconfigured. Check its "
                   "wiring or pairing, and exclude it from automations until "
                   "it reads sanely.")


def implausible(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    stored = (snap.get("baselines") or {}).get("entities") or {}
    out = []
    for eid, st in _live_hardware(house):
        attrs = st.get("attributes") or {}
        key = (attrs.get("device_class"), attrs.get("unit_of_measurement"))
        bounds = bounds_for(attrs, eid, house.world, house)
        if not bounds:
            continue
        value = num(st.get("state"))
        if value is None:
            continue
        if out_of_range(st, eid, house.world, house):
            detail = (f"{numfmt.quantity(value, key[1])} as of "
                      f"{when(st.get('last_updated'))}; "
                      f"{_range_said(key, bounds)}.")
        else:
            # Reading sanely now, after a night it could not have read:
            # still the sensor, and the night was kept out of its baseline.
            seen = recently_impossible(stored.get(eid), now, bounds)
            lowest = num((seen or {}).get("lowest"))
            if lowest is None:
                continue
            if lowest >= bounds[0]:
                lowest = num(seen.get("highest")) or lowest
            detail = (f"It read {numfmt.quantity(lowest, key[1])} as "
                      f"recently as {when(seen.get('last'))} and reads "
                      f"{numfmt.quantity(value, key[1])} now; "
                      f"{_range_said(key, bounds)}.")
        if not house.should_report(eid, "dev.implausible"):
            continue
        out.append({
            "text": f"{house.name(eid)} is reporting an impossible value",
            "detail": detail + _outside_said(house, attrs) + house.placed(eid),
            "fix": IMPLAUSIBLE_FIX,
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.frozen — exactly one value for a week, from long-term statistics
# ---------------------------------------------------------------------------

def _flat_battery_beside(house: House, eid: str) -> str:
    """A battery on this entity's device reading at or under the low mark.

    Read off the live state only — the snapshot holds it already — and a
    battery somebody charges (`rechargeable`) does not count, because a
    phone at 9% is not why its other sensors stopped.
    """
    for other in house.siblings(eid):
        st = house.states.get(other) or {}
        if not _is_battery(st):
            continue
        level = num(st.get("state"))
        if level is not None and level <= BATTERY_LOW_PCT \
                and not rechargeable(house, other):
            return other
    return ""


def frozen(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    stats = snap.get("stats") or {}
    out = []
    for eid, rows in stats.items():
        st = house.states.get(eid)
        if not st or domain_of(eid) in SOFTWARE_DOMAINS or not house.enabled(eid):
            continue
        if st.get("state") in ("unavailable", "unknown"):
            continue
        attrs = st.get("attributes") or {}
        # A sensor that does not say what it measures is not one this can
        # claim should have moved: see FROZEN_SKIP_CLASSES. Batteries sit
        # at 100 for weeks, signal strength sits wherever the router is,
        # and a fixed tariff sits still for years — none is a stuck
        # sensor, and nor is a rated capacity or a device count.
        device_class = str(attrs.get("device_class") or "")
        if not device_class or device_class in FROZEN_SKIP_CLASSES:
            continue
        if states_a_fixed_figure(house, eid, attrs):
            continue
        if device_class == "voltage" and reads_a_battery_voltage(
                house, eid, attrs):
            continue
        days = [r for r in rows if isinstance(r, dict)
                and r.get("min") is not None and r.get("max") is not None]
        if len(days) < FROZEN_MIN_DAYS:
            continue
        lo = min(num(r["min"]) or 0.0 for r in days)
        hi = max(num(r["max"]) or 0.0 for r in days)
        if hi - lo > 1e-9:
            continue
        if abs(lo) < 1e-9:
            # A power sensor on an idle plug reads 0 for a week and is fine.
            continue
        # The live state is the one reading the statistics cannot speak
        # for: a sensor whose state changed inside the window to something
        # other than the value the week supposedly held was not frozen —
        # the statistics are missing the rows that would have shown it.
        live = num(st.get("state"))
        changed = parse_ts(st.get("last_changed"))
        if (live is not None and abs(live - lo) > 1e-9
                and changed is not None
                and changed >= now - len(days) * 86400):
            continue
        flat = _flat_battery_beside(house, eid)
        if flat:
            # A reading that stopped beside a battery at or near empty is
            # the battery's row (`dev.battery_low`), not a second card about
            # the same box under a different fix.
            house._note({"kind": "dedupe", "subject": eid,
                         "check": "dev.frozen",
                         "reason": f"{house.label(flat)} reads "
                                   f"{house.states[flat].get('state')}%, so "
                                   "the battery check owns this device",
                         "text": ""})
            continue
        if not house.should_report(eid, "dev.frozen"):
            # "It is a contact on a cupboard nobody opens" — said once,
            # on the Wrong button, and read here ever after.
            continue
        unit = attrs.get("unit_of_measurement") or ""
        out.append({
            "text": f"{house.name(eid)} has read exactly the same value "
                    "for a week",
            "detail": f"{numfmt.quantity(lo, unit)} on every one of the "
                      f"last {len(days)} "
                      "days. A real sensor moves." + house.placed(eid),
            "fix": "Check the sensor — it has probably stopped updating "
                   "while its integration keeps repeating the last value.",
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    # Past the cap this says nothing at all, rather than saying it more
    # quietly: a dozen at once is a fact about the statistics rather than
    # about the sensors. And it says on the decision trail that it did.
    if len(out) > FROZEN_MAX_ROWS:
        house.gave_up("dev.frozen", out, f"{len(out)} sensors read one value "
                      f"for a week at once — past {FROZEN_MAX_ROWS} that is a "
                      "recorder purge or a reload rather than broken sensors")
        return []
    return out


# ---------------------------------------------------------------------------
# dev.restored — the integration that provided it is gone
# ---------------------------------------------------------------------------

def restored(snap: dict, now: float) -> list[dict]:
    """Restored entities whose provider is really gone.

    `restored: true` says the integration has not added the entity THIS
    run, which is also true of a config entry retrying its setup (a
    device that did not answer at boot) and of a loaded one whose device
    is simply away (a beacon out of range): deleting those takes a
    working device out of the house. So an entity whose config entry
    still exists, in any state, is not left over — and the check needs
    the config entries to say so, or it is skipped ("I could not look").
    """
    house = House(snap)
    entries = {str(e.get("entry_id")) for e in (snap.get("config_entries") or [])
               if isinstance(e, dict) and e.get("entry_id")}
    by_platform: dict[str, list[str]] = {}
    for eid, st in house.states.items():
        if (st.get("attributes") or {}).get("restored") is not True:
            continue
        reg = house.registry.get(eid) or {}
        if str(reg.get("config_entry_id") or "") in entries:
            continue
        by_platform.setdefault(str(reg.get("platform") or "unknown"), []).append(eid)
    out = []
    for platform, eids in sorted(by_platform.items()):
        eids = sorted(e for e in eids if house.should_report(e, "dev.restored"))
        if not eids:
            continue
        out.append({
            "text": f"Entities from the {spell_integration(platform)} "
                    "integration are left over with nothing providing them",
            "detail": f"{len(eids)} restored entit{'y' if len(eids) == 1 else 'ies'}: "
                      + join_names([house.label(e) for e in eids])
                      + ". They show as unavailable and clutter every picker.",
            "fix": "Reinstall the integration if it was removed by mistake. "
                   "Otherwise remove them in Settings > Devices & services > "
                   "Entities: select them and press Remove selected.",
            "evidence": evidence_for(eids, "restored, nothing provides it"),
            "severity": "info",
            "fixable": True,
            "entity_id": eids[0],
        })
    return out


# ---------------------------------------------------------------------------
# dev.zwave_dead — the controller has given up on a node
# ---------------------------------------------------------------------------

def zwave_dead(snap: dict, now: float) -> list[dict]:
    """Z-Wave JS publishes a node status sensor per device, and it says
    `dead` when the controller has stopped getting answers.

    That is a different finding from ``dev.unavailable`` even when both are
    true of the same box: unavailable says Home Assistant has no state,
    dead says the *mesh* has lost the node, and the fix is a mesh fix — move
    it, re-interview it, or replace a failed node — not a restart.
    """
    house = House(snap)
    dead = [house.device_name(house.devices[d])
            for d in _zwave_dead_devices(house)]
    if not dead:
        return []
    dead.sort()
    return [{
        "text": "Z-Wave nodes are marked dead by the controller",
        "detail": counted_names(dead)
                  + ". The controller has stopped getting answers from "
                    "them, so nothing they do reaches Home Assistant.",
        "fix": "Wake a battery node (its button usually does it). For a "
               "plugged-in node, check it still has power and is in range "
               "of another plugged-in node — then re-interview it from its "
               "device page. A node that is really gone should be removed with "
               "'Remove failed node' so the mesh stops routing through it.",
        "severity": "serious",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# dev.zha_unseen — a Zigbee device that has stopped checking in
# ---------------------------------------------------------------------------

def zha_unseen(snap: dict, now: float) -> list[dict]:
    """ZHA records `last_seen` per device, which is the honest question for
    a Zigbee mesh: a sleepy sensor is `available` between check-ins, so
    availability alone says nothing, and silence is what matters.

    A week is this check's; hours are `net.zigbee_silent`'s. One classifier
    (`network.zigbee_quiet`) decides which, over one list of the devices a
    check may speak about, so a device is never in both.
    """
    from . import network  # noqa: PLC0415 — network imports this module
    house = House(snap)
    rows = []
    for dev, reg, _entity in network.zigbee_devices(house):
        if network.zigbee_quiet(dev, now) != "dropped":
            continue
        age = age_days(dev.get("last_seen"), now) or 0.0
        rows.append((age, network.zigbee_name(dev, reg, house)))
    if not rows:
        return []
    rows.sort(reverse=True)
    longest, first = rows[0]
    return [{
        "text": "Zigbee devices have stopped checking in",
        "detail": counted_names([n for _, n in rows])
                  + f". The quietest is {first}, last seen "
                    f"{when(max(0.0, now - longest * 86400))} "
                    f"({int(longest)} days ago).",
        "fix": "A battery device this quiet has usually run its battery "
               "down or dropped off the mesh — press its button to wake "
               "it. If it does not come back, re-pair it near the "
               "coordinator, then move it back.",
        "severity": "warning",
        "fixable": False,
        "entity_id": "",
    }]


CHECKS = [
    {"id": "dev.unavailable", "title": "Devices unavailable for a day",
     "needs": ("states", "registry"), "run": unavailable},
    {"id": "dev.battery_low", "title": "Batteries low or gone quiet",
     "needs": ("states", "registry"), "run": battery_low},
    {"id": "dev.implausible", "title": "Impossible sensor readings",
     "needs": ("states", "registry"), "run": implausible},
    {"id": "dev.frozen", "title": "Sensors frozen on one value",
     "needs": ("states", "registry", "stats"), "run": frozen,
     # A week of one value read off a recorder that is missing rows is a
     # week of holes: skipped (never "it went away") while the history
     # probe says the recorder is incomplete — `checks.run_all`.
     "reads_history": True},
    {"id": "dev.restored", "title": "Entities with no integration",
     "needs": ("states", "registry", "config_entries"), "run": restored},
    {"id": "dev.zwave_dead", "title": "Z-Wave nodes marked dead",
     "needs": ("states", "registry"), "run": zwave_dead},
    {"id": "dev.zha_unseen", "title": "Zigbee devices gone quiet",
     "needs": ("zha_devices",), "run": zha_unseen},
]
