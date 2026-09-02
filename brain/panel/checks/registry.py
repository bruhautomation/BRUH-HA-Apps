"""Registry housekeeping checks.

Nothing here is broken in the sense an automation is broken. These are the
things that make a house *hard to work with*: entities still wearing the
serial number their integration gave them, devices in no room, helpers
nobody wired up, devices left behind by an integration that was
reconfigured. Every one of them is invisible until you go looking, and
every one of them costs somebody five minutes in a picker, every time.

They are `info` severity for that reason, and each one has a floor that
keeps it quiet on a house where the answer is "I have not got to that yet":
a fresh install has no areas and nothing is wrong with it, a helper made
this morning has not been wired up yet and nothing is wrong with that
either. A check that fires on a healthy house is the one people learn to
ignore first, and these are the checks most at risk of it.
"""
from __future__ import annotations

import re

from ._util import House, age_days, domain_of, join_names

# A house is "using areas" past this many. Below it, "not in an area" is
# how the house is set up, not a finding.
MIN_AREAS = 3
# A helper younger than this is still being wired up.
HELPER_GRACE_DAYS = 30
# Domains that are a helper somebody created, not a device.
HELPER_DOMAINS = frozenset({
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button", "counter", "timer", "schedule",
})
# Entities that live in the settings pages rather than in a picker. Their
# names come from the integration by design.
BACKGROUND_CATEGORIES = frozenset({"diagnostic", "config"})

# Hardware ids, in the three shapes they reach a name in: an IEEE/MAC
# address, a UUID, and a bare hex run. The hex run has to carry both a
# digit and an a-f letter, or "Bedroom 123456789012" and "deadbeefface"
# both read as hardware and neither is.
_MAC_RE = re.compile(r"(?<![0-9a-zA-Z])(?:[0-9a-fA-F]{2}[:_-]){5}[0-9a-fA-F]{2}"
                     r"(?![0-9a-zA-Z])")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX_RE = re.compile(r"(?<![0-9a-zA-Z])(?:0x)?([0-9a-fA-F]{12,})(?![0-9a-zA-Z])")


def hardware_token(text: str) -> str:
    """The hardware id inside a name, or ''.

    Order matters only for the message: a MAC is reported as a MAC even
    though the hex rule would also match most of one.
    """
    if not text:
        return ""
    match = _MAC_RE.search(text) or _UUID_RE.search(text)
    if match:
        return match.group(0)
    match = _HEX_RE.search(text)
    if match:
        run = match.group(1).lower()
        if any(c.isdigit() for c in run) and any(c in "abcdef" for c in run):
            return match.group(0)
    return ""


def _in_a_picker(house: House, eid: str) -> bool:
    """Enabled, not hidden, and not a diagnostic or config entity."""
    if not house.enabled(eid):
        return False
    reg = house.registry.get(eid) or {}
    if reg.get("hidden_by"):
        return False
    return str(reg.get("entity_category") or "") not in BACKGROUND_CATEGORIES


# ---------------------------------------------------------------------------
# reg.hardware_name — still called by its serial number
# ---------------------------------------------------------------------------

def hardware_name(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    hits: list[tuple[str, str, str]] = []  # (entity_id, name, token)
    for eid in house.states:
        if not _in_a_picker(house, eid):
            continue
        name = house.name(eid)
        token = hardware_token(name)
        if token:
            hits.append((eid, name, token))
    if not hits:
        return []
    hits.sort()
    shown = [f"{name} ({eid})" for eid, name, _ in hits[:6]]
    return [{
        "text": "Some entities are still named after their hardware id",
        "detail": f"{len(hits)} of them, including "
                  + join_names(shown, limit=6)
                  + ". A name like that is unfindable in a picker and "
                    "unsayable to Assist.",
        "fix": "Rename them in Settings > Devices & services > Entities — "
               "or ask brAIn to suggest names from where each one is.",
        "severity": "info",
        "fixable": True,
        "entity_id": hits[0][0],
    }]


# ---------------------------------------------------------------------------
# reg.no_area — a device in no room
# ---------------------------------------------------------------------------

def no_area(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    if len(house.areas) < MIN_AREAS:
        # A house that has not set areas up is not a house with a problem.
        return []
    by_device: dict[str, list[str]] = {}
    for eid in house.states:
        if not _in_a_picker(house, eid):
            continue
        dev = house.device_of(eid)
        if dev is None or dev.get("area_id"):
            continue
        if (house.registry.get(eid) or {}).get("area_id"):
            continue  # the entity overrides its device's area
        by_device.setdefault(dev["id"], []).append(eid)
    if not by_device:
        return []
    names = sorted(house.device_name(house.devices[d]) for d in by_device)
    return [{
        "text": "Some devices are not assigned to an area",
        "detail": f"{len(names)} of them: " + join_names(names)
                  + ". Anything not in an area is invisible to \"turn off "
                    "the kitchen\", to area cards, and to every automation "
                    "that targets a room.",
        "fix": "Assign each one in Settings > Devices & services > Devices.",
        "severity": "info",
        "fixable": True,
        "entity_id": sorted(by_device[sorted(by_device)[0]])[0],
    }]


# ---------------------------------------------------------------------------
# reg.unused_helper — created, never wired up
# ---------------------------------------------------------------------------

def _referenced(house: House) -> set[str]:
    """Every entity id named anywhere a helper could be used from.

    One `entity_refs` call over everything, not one per source: it rebuilds
    the registered-services set on each call, and this walks the whole
    house.
    """
    sources: list = [house.snap.get(k) for k in ("automations", "scripts", "scenes")]
    sources += [d.get("config") or {} for d in (house.snap.get("dashboards") or [])]
    # A template entity or a group's own options can name a helper, and
    # those live in attributes rather than in any file.
    sources += [st.get("attributes") or {} for eid, st in house.states.items()
                if domain_of(eid) not in HELPER_DOMAINS]
    return house.entity_refs(sources)


def unused_helper(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    candidates = []
    for eid in house.states:
        if domain_of(eid) not in HELPER_DOMAINS:
            continue
        if not house.enabled(eid):
            continue
        reg = house.registry.get(eid) or {}
        age = age_days(reg.get("created_at"), now)
        # No created_at (a YAML helper) is not young; it is unknown, and a
        # YAML helper has been there since the file was written.
        if age is not None and age < HELPER_GRACE_DAYS:
            continue
        candidates.append(eid)
    if not candidates:
        return []
    refs = _referenced(house)
    unused = sorted(e for e in candidates if e not in refs)
    if not unused:
        return []
    names = [f"{house.name(e)} ({e})" for e in unused]
    return [{
        "text": "Some helpers are not used by anything",
        "detail": f"{len(unused)} helper{'' if len(unused) == 1 else 's'} "
                  "no automation, script, scene or dashboard refers to: "
                  + join_names(names)
                  + ". Checked against the config files and the storage-mode "
                    "dashboards.",
        "fix": "Delete the ones you have finished with. If one is used from "
               "a YAML dashboard or a template brAIn cannot read, say so "
               "and it will stop asking.",
        "severity": "info",
        "fixable": False,
        "entity_id": unused[0],
    }]


# ---------------------------------------------------------------------------
# reg.orphan_device — a device row with nothing behind it
# ---------------------------------------------------------------------------

def orphan_device(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    if not house.devices:
        return []
    has_entities: set[str] = set()
    for reg in house.entities:
        dev_id = reg.get("device_id")
        if dev_id:
            has_entities.add(str(dev_id))
    # A hub that another device reports as its via_device is doing a job
    # even with no entities of its own.
    parents = {str(d.get("via_device_id")) for d in house.devices.values()
               if d.get("via_device_id")}
    orphans = []
    for dev_id, dev in house.devices.items():
        if dev_id in has_entities or dev_id in parents:
            continue
        if dev.get("disabled_by"):
            continue
        orphans.append(house.device_name(dev))
    if not orphans:
        return []
    orphans.sort()
    return [{
        "text": "Some devices are left in the registry with no entities",
        "detail": f"{len(orphans)}: " + join_names(orphans)
                  + ". They are usually what is left after an integration "
                    "was reconfigured or a device was replaced.",
        "fix": "Remove them from Settings > Devices & services > Devices, "
               "or run brain.delete_orphaned_devices (it is a dry run "
               "unless you tell it otherwise).",
        "severity": "info",
        "fixable": True,
        "entity_id": "",
    }]


CHECKS = [
    {"id": "reg.hardware_name", "title": "Entities named after hardware",
     "needs": ("states", "registry"), "run": hardware_name},
    {"id": "reg.no_area", "title": "Devices in no area",
     "needs": ("states", "registry"), "run": no_area},
    {"id": "reg.unused_helper", "title": "Helpers nothing uses",
     "needs": ("states", "registry", "automations", "dashboards"),
     "run": unused_helper},
    {"id": "reg.orphan_device", "title": "Devices with no entities",
     "needs": ("registry",), "run": orphan_device},
]
