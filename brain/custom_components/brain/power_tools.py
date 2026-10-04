"""BRUH Power Tools — advanced Home Assistant admin services.

Registry-management services exposed under the `brain` domain so
Claude (and any automation, script, or Assist pipeline) can reorganize a
Home Assistant instance through supervised, validated service calls
instead of editing `/config/.storage` files by hand:

- Areas:        create, delete, rename, set aliases, set icon,
                assign devices/entities
- Floors:       create, delete, rename, update (icon/level/aliases),
                assign areas
- Labels:       create, delete, rename, update (icon/colour/description),
                apply/remove on entities, devices, areas
- Entities:     rename, change entity_id, enable/disable, hide/unhide,
                voice aliases, icon overrides, orphan cleanup (dry-run default)
- Device types: the "Show as" control — a device class override (a binary
                sensor as a door, a cover as a garage door, a switch as an
                outlet), a switch shown as a light/fan/lock/cover/siren/valve
                and back (switch_as_x), sensor display precision and unit
- Devices:      rename, enable/disable (cascades to lonely parent devices),
                delete, orphan cleanup (dry-run default)
- Integrations: enable/disable/reload/delete config entries
- Helpers:      create/delete any storage-backed helper (input_*, counter,
                timer, schedule)
- Zones:        create, update, delete
- Persons:      create/delete/rename, attach/detach device trackers
- Blueprints:   import automation/script blueprints from a URL
- Statistics:   import/backfill long-term statistics (recorder)
- Users:        create/delete/enable/disable (owner accounts are protected)
- Diagnostics:  find automation/script/scene references to unknown entities
- Dashboards:   create/delete/update/restore storage dashboards with
                automatic backups, register/remove custom-card resources
- Repairs:      create/remove custom issues in Settings > System > Repairs

Adapted from Spook (https://github.com/frenck/spook) by Franck Nijhof,
released under the MIT License. Changes from Spook:
- all services live under `brain.*` instead of overloading core
  domains, so they never collide with Spook itself or future HA services
- every referenced registry id is validated up front with a clear error
  before anything is changed
- creation services return the new registry id as response data
- `delete_orphaned_entities` defaults to a dry run that reports what it
  would remove
- every destructive service supports `dry_run` previews with blast-radius
  response data; `import_statistics` (irreversible without a recorder DB
  restore) defaults to dry run
- every call is audit-logged (service, args, outcome) through the admin
  gate, so mutations leave a forensic trail
- dashboard writes are guarded: `url_path` is required (the default
  dashboard needs the explicit literal "default"), taking over a
  never-saved dashboard requires `take_control: true`, and
  `reset_dashboard_config` is the sanctioned undo
- label application is consolidated into two multi-target services
  (`add_label` / `remove_label`) instead of six single-target ones
- nothing is create-only: every attribute a create service accepts has a
  service that can change it afterwards, and every registry object that
  can be created can be renamed and deleted
- `update_*` services only write the fields the caller actually named, so
  changing a colour doesn't blank a description
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized, UnknownUser

# Bad-input failures raise ServiceValidationError so callers on EVERY
# transport see the message: HomeAssistantError becomes an opaque
# "500 Server got itself in trouble" over REST, which defeats the module's
# validation-first design. Environment/runtime failures stay HomeAssistantError.
try:
    from homeassistant.exceptions import ServiceValidationError
except ImportError:  # pre-2023.12
    ServiceValidationError = HomeAssistantError  # type: ignore[assignment,misc]
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from .const import DOMAIN

try:
    from homeassistant.core import SupportsResponse
except ImportError:  # pre-2023.7 — services simply won't return data
    SupportsResponse = None  # type: ignore[assignment,misc]

try:
    from homeassistant.helpers import floor_registry as fr
except ImportError:  # pre-2024.4
    fr = None  # type: ignore[assignment]

try:
    from homeassistant.helpers import label_registry as lr
except ImportError:  # pre-2024.4
    lr = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

# Label colors accepted by the HA frontend theme (from Spook's create_label).
LABEL_THEME_COLORS = {
    "primary", "accent", "disabled", "amber", "black", "blue-grey", "blue",
    "brown", "cyan", "dark-grey", "deep-orange", "deep-purple", "green",
    "grey", "indigo", "light-blue", "light-green", "light-grey", "lime",
    "orange", "pink", "purple", "red", "teal", "white", "yellow",
}

ISSUE_SEVERITIES = ("critical", "error", "warning")


# ---------------------------------------------------------------------------
# Validation helpers — fail loudly with the offending id before touching
# anything, so a typo never half-applies a change.
# ---------------------------------------------------------------------------


def _ensure_area(hass: HomeAssistant, area_id: str) -> None:
    if not ar.async_get(hass).async_get_area(area_id):
        raise ServiceValidationError(f"Area not found: {area_id}")


def _ensure_floor(hass: HomeAssistant, floor_id: str) -> None:
    _require_floors()
    if not fr.async_get(hass).async_get_floor(floor_id):
        raise ServiceValidationError(f"Floor not found: {floor_id}")


def _ensure_label(hass: HomeAssistant, label_id: str) -> None:
    _require_labels()
    if not lr.async_get(hass).async_get_label(label_id):
        raise ServiceValidationError(f"Label not found: {label_id}")


def _ensure_device(hass: HomeAssistant, device_id: str) -> None:
    if not dr.async_get(hass).async_get(device_id):
        raise ServiceValidationError(f"Device not found: {device_id}")


def _ensure_entity(hass: HomeAssistant, entity_id: str) -> None:
    if not er.async_get(hass).async_get(entity_id):
        raise ServiceValidationError(f"Entity not found in registry: {entity_id}")


def _ensure_config_entry(hass: HomeAssistant, entry_id: str) -> None:
    if not hass.config_entries.async_get_entry(entry_id):
        raise ServiceValidationError(f"Config entry not found: {entry_id}")


def _require_floors() -> None:
    if fr is None:
        raise HomeAssistantError(
            "Floors require Home Assistant 2024.4 or newer"
        )


def _require_labels() -> None:
    if lr is None:
        raise HomeAssistantError(
            "Labels require Home Assistant 2024.4 or newer"
        )


# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------


async def _create_area(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    if floor_id := call.data.get("floor_id"):
        _ensure_floor(hass, floor_id)
    kwargs: dict[str, Any] = {"name": call.data["name"]}
    if call.data.get("aliases") is not None:
        kwargs["aliases"] = set(call.data["aliases"])
    if call.data.get("icon") is not None:
        kwargs["icon"] = call.data["icon"]
    if floor_id:
        kwargs["floor_id"] = floor_id
    entry = ar.async_get(hass).async_create(**kwargs)
    return {"area_id": entry.id}


def _dry_run(call: ServiceCall) -> bool:
    return bool(call.data.get("dry_run", False))


async def _delete_area(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Delete an area. dry_run previews the blast radius (members are
    unassigned, not deleted — but the assignment loss is irreversible)."""
    area_id = call.data["area_id"]
    _ensure_area(hass, area_id)
    area = ar.async_get(hass).async_get_area(area_id)
    devices = sorted(
        d.id for d in dr.async_get(hass).devices.values() if d.area_id == area_id
    )
    entities = sorted(
        e.entity_id for e in er.async_get(hass).entities.values()
        if e.area_id == area_id
    )
    result = {
        "dry_run": _dry_run(call),
        "area_id": area_id,
        "name": area.name if area else None,
        "devices_assigned": devices,
        "entities_assigned": entities,
    }
    if _dry_run(call):
        return result
    ar.async_get(hass).async_delete(area_id)
    return result


async def _rename_area(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_area(hass, call.data["area_id"])
    ar.async_get(hass).async_update(call.data["area_id"], name=call.data["name"])


async def _set_area_aliases(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_area(hass, call.data["area_id"])
    ar.async_get(hass).async_update(
        call.data["area_id"], aliases=set(call.data["aliases"])
    )


async def _set_area_icon(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set (or, with icon omitted, clear) an area's icon."""
    _ensure_area(hass, call.data["area_id"])
    ar.async_get(hass).async_update(call.data["area_id"], icon=call.data.get("icon"))


async def _add_device_to_area(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_area(hass, call.data["area_id"])
    for device_id in call.data["device_id"]:
        _ensure_device(hass, device_id)
    registry = dr.async_get(hass)
    for device_id in call.data["device_id"]:
        registry.async_update_device(device_id, area_id=call.data["area_id"])


async def _remove_device_from_area(hass: HomeAssistant, call: ServiceCall) -> None:
    for device_id in call.data["device_id"]:
        _ensure_device(hass, device_id)
    registry = dr.async_get(hass)
    for device_id in call.data["device_id"]:
        registry.async_update_device(device_id, area_id=None)


async def _add_entity_to_area(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_area(hass, call.data["area_id"])
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, area_id=call.data["area_id"])


async def _remove_entity_from_area(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, area_id=None)


# ---------------------------------------------------------------------------
# Floors
# ---------------------------------------------------------------------------


async def _create_floor(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    _require_floors()
    entry = fr.async_get(hass).async_create(
        name=call.data["name"],
        aliases=set(call.data["aliases"]) if call.data.get("aliases") else None,
        icon=call.data.get("icon"),
        level=call.data.get("level"),
    )
    return {"floor_id": entry.floor_id}


async def _delete_floor(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Delete a floor. dry_run previews the areas that would lose it."""
    floor_id = call.data["floor_id"]
    _ensure_floor(hass, floor_id)
    floor = fr.async_get(hass).async_get_floor(floor_id)
    areas = sorted(
        a.id for a in ar.async_get(hass).areas.values() if a.floor_id == floor_id
    )
    result = {
        "dry_run": _dry_run(call),
        "floor_id": floor_id,
        "name": floor.name if floor else None,
        "areas_assigned": areas,
    }
    if _dry_run(call):
        return result
    fr.async_get(hass).async_delete(floor_id)
    return result


async def _rename_floor(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_floor(hass, call.data["floor_id"])
    fr.async_get(hass).async_update(call.data["floor_id"], name=call.data["name"])


def _partial_update(call: ServiceCall, fields: tuple[str, ...]) -> dict:
    """The subset of `fields` this call actually named.

    An update service that fills in every field from call.data.get() wipes
    whatever the caller didn't mention — so only keys that are present are
    passed through, and passing none at all is an error rather than a
    silent no-op.
    """
    changes = {f: call.data[f] for f in fields if f in call.data}
    if not changes:
        raise ServiceValidationError(
            "Nothing to update — give at least one of: " + ", ".join(fields)
        )
    return changes


async def _update_floor(hass: HomeAssistant, call: ServiceCall) -> None:
    """Change a floor's icon, level or aliases (name is rename_floor).

    Everything create_floor accepts was write-once until now: there was no
    way to give an existing floor an icon, or to correct its level.
    """
    _ensure_floor(hass, call.data["floor_id"])
    changes = _partial_update(call, ("icon", "level", "aliases"))
    if "aliases" in changes:
        changes["aliases"] = set(changes["aliases"])
    fr.async_get(hass).async_update(call.data["floor_id"], **changes)


async def _add_area_to_floor(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_floor(hass, call.data["floor_id"])
    for area_id in call.data["area_id"]:
        _ensure_area(hass, area_id)
    registry = ar.async_get(hass)
    for area_id in call.data["area_id"]:
        registry.async_update(area_id, floor_id=call.data["floor_id"])


async def _remove_area_from_floor(hass: HomeAssistant, call: ServiceCall) -> None:
    for area_id in call.data["area_id"]:
        _ensure_area(hass, area_id)
    registry = ar.async_get(hass)
    for area_id in call.data["area_id"]:
        registry.async_update(area_id, floor_id=None)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


async def _create_label(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    _require_labels()
    entry = lr.async_get(hass).async_create(
        name=call.data["name"],
        color=call.data.get("color"),
        description=call.data.get("description"),
        icon=call.data.get("icon"),
    )
    return {"label_id": entry.label_id}


async def _rename_label(hass: HomeAssistant, call: ServiceCall) -> None:
    """Rename a label, the same way areas, floors, devices and entities do."""
    _ensure_label(hass, call.data["label_id"])
    lr.async_get(hass).async_update(call.data["label_id"], name=call.data["name"])


async def _update_label(hass: HomeAssistant, call: ServiceCall) -> None:
    """Change a label's icon, colour or description (name is rename_label).

    A label was create-only: everything you set when you made it was fixed
    for the life of the label, which for the colour — the thing a label is
    mostly for — is the one attribute people want to change.
    """
    _ensure_label(hass, call.data["label_id"])
    lr.async_get(hass).async_update(
        call.data["label_id"],
        **_partial_update(call, ("icon", "color", "description")),
    )


async def _delete_label(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Delete a label. dry_run previews what currently carries it."""
    label_id = call.data["label_id"]
    _ensure_label(hass, label_id)
    label = lr.async_get(hass).async_get_label(label_id)
    result = {
        "dry_run": _dry_run(call),
        "label_id": label_id,
        "name": label.name if label else None,
        "entities_labeled": sorted(
            e.entity_id for e in er.async_get(hass).entities.values()
            if label_id in e.labels
        ),
        "devices_labeled": sorted(
            d.id for d in dr.async_get(hass).devices.values()
            if label_id in d.labels
        ),
        "areas_labeled": sorted(
            a.id for a in ar.async_get(hass).areas.values()
            if label_id in a.labels
        ),
    }
    if _dry_run(call):
        return result
    lr.async_get(hass).async_delete(label_id)
    return result


def _label_targets(call: ServiceCall) -> tuple[list[str], list[str], list[str]]:
    entities = call.data.get("entity_id") or []
    devices = call.data.get("device_id") or []
    areas = call.data.get("area_id") or []
    if not (entities or devices or areas):
        raise ServiceValidationError(
            "Provide at least one target: entity_id, device_id, or area_id"
        )
    return entities, devices, areas


async def _apply_labels(
    hass: HomeAssistant, call: ServiceCall, *, add: bool
) -> None:
    label_ids = set(call.data["label_id"])
    for label_id in label_ids:
        _ensure_label(hass, label_id)
    entities, devices, areas = _label_targets(call)
    for entity_id in entities:
        _ensure_entity(hass, entity_id)
    for device_id in devices:
        _ensure_device(hass, device_id)
    for area_id in areas:
        _ensure_area(hass, area_id)

    entity_registry = er.async_get(hass)
    for entity_id in entities:
        entry = entity_registry.async_get(entity_id)
        labels = set(entry.labels)
        labels = labels | label_ids if add else labels - label_ids
        entity_registry.async_update_entity(entity_id, labels=labels)

    device_registry = dr.async_get(hass)
    for device_id in devices:
        entry = device_registry.async_get(device_id)
        labels = set(entry.labels)
        labels = labels | label_ids if add else labels - label_ids
        device_registry.async_update_device(device_id, labels=labels)

    area_registry = ar.async_get(hass)
    for area_id in areas:
        entry = area_registry.async_get_area(area_id)
        labels = set(entry.labels)
        labels = labels | label_ids if add else labels - label_ids
        area_registry.async_update(area_id, labels=labels)


async def _add_label(hass: HomeAssistant, call: ServiceCall) -> None:
    await _apply_labels(hass, call, add=True)


async def _remove_label(hass: HomeAssistant, call: ServiceCall) -> None:
    await _apply_labels(hass, call, add=False)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


async def _rename_entity(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, name=call.data["name"])


async def _change_entity_id(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Rename an entity id, reporting everything that references the old id.

    The rename does NOT rewrite automations/scripts/scenes/dashboards that
    reference the old id — the response lists the affected sources so the
    breakage is visible the moment it's created, not discovered later by a
    broken automation. dry_run previews without renaming."""
    entity_id = call.data["entity_id"]
    new_entity_id = call.data["new_entity_id"]
    _ensure_entity(hass, entity_id)

    references = sorted(
        source_id
        for source_id, referenced in _reference_sources(hass)
        if entity_id in referenced
    )
    result = {
        "dry_run": _dry_run(call),
        "entity_id": entity_id,
        "new_entity_id": new_entity_id,
        "references_to_old_id": references,
    }
    if references:
        result["note"] = (
            "These automations/scripts/scenes reference the old id and must "
            "be updated by hand (dashboards may too — run "
            "find_orphaned_references after fixing them)."
        )
    if _dry_run(call):
        return result
    er.async_get(hass).async_update_entity(
        entity_id, new_entity_id=new_entity_id
    )
    return result


async def _enable_entity(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, disabled_by=None)


async def _disable_entity(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(
            entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )


async def _hide_entity(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(
            entity_id, hidden_by=er.RegistryEntryHider.USER
        )


async def _unhide_entity(hass: HomeAssistant, call: ServiceCall) -> None:
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, hidden_by=None)


async def _set_entity_aliases(hass: HomeAssistant, call: ServiceCall) -> None:
    """Replace an entity's voice-assistant aliases."""
    _ensure_entity(hass, call.data["entity_id"])
    er.async_get(hass).async_update_entity(
        call.data["entity_id"], aliases=set(call.data["aliases"])
    )


async def _set_entity_icon(hass: HomeAssistant, call: ServiceCall) -> None:
    """Set (or, when icon is omitted, clear) entity icon overrides."""
    for entity_id in call.data["entity_id"]:
        _ensure_entity(hass, entity_id)
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        registry.async_update_entity(entity_id, icon=call.data.get("icon"))


async def _delete_orphaned_entities(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Remove registry entries whose provider is gone (state is 'restored').

    Defaults to a dry run: nothing is deleted unless dry_run is explicitly
    false, and the response always lists the affected entity ids.

    An optional entity_id list scopes the cleanup. Every requested entity
    is re-verified as orphaned; anything still provided by an integration
    is skipped and reported under skipped_not_orphaned, never deleted.
    """
    dry_run = call.data.get("dry_run", True)
    orphaned = [
        state.entity_id
        for state in hass.states.async_all()
        if state.attributes.get("restored")
    ]
    requested = call.data.get("entity_id")
    skipped: list[str] = []
    if requested:
        requested_set = set(requested)
        skipped = sorted(requested_set - set(orphaned))
        targets = [e for e in orphaned if e in requested_set]
    else:
        targets = orphaned
    if not dry_run:
        registry = er.async_get(hass)
        for entity_id in targets:
            registry.async_remove(entity_id)
            hass.states.async_remove(entity_id, call.context)
    result = {"dry_run": dry_run, "count": len(targets), "entity_ids": targets}
    if requested:
        result["skipped_not_orphaned"] = skipped
    return result


# ---------------------------------------------------------------------------
# Device types — what Home Assistant shows a device as
# ---------------------------------------------------------------------------
#
# The entity settings dialog's "Show as" is three different mechanisms
# depending on what the entity is, and each is used here exactly the way
# that dialog uses it (frontend: src/panels/config/entities/
# entity-registry-settings-editor.ts):
#
#  - a binary sensor (door, window, motion, moisture…), a cover (garage,
#    blind, shutter…), a switch's "outlet" and the like take a DEVICE CLASS
#    override in the entity registry: `async_update_entity(device_class=)`,
#    and None gives the integration's own `original_device_class` back.
#    Core does not check the value — `config/entity_registry/update` takes
#    any string — so the check is here, against the domain's own
#    `<Domain>DeviceClass` enum read off the running core, and a core that
#    will not say is refused rather than written to unchecked;
#  - a SWITCH (a smart plug running a fan or a lamp) is shown as a light,
#    fan, lock, cover, siren or valve by the `switch_as_x` helper: a config
#    entry whose entity — unique_id is the entry's own id — takes the
#    switch's place while the switch is hidden, and removing the entry
#    unhides it (switch_as_x's own `async_remove_entry` does that). The
#    entry is made through the helper's own config flow, which is what the
#    dialog does too, and what the flow offers (the target domains, whether
#    `invert` exists — 2024.2 on) is read off the form it returns rather than
#    assumed. Only a switch can be wrapped: a fan entity cannot be shown as
#    a light, and the refusal says what can be done instead;
#  - a sensor's display precision and unit live in the registry's `sensor`
#    entity options, the same mapping the dialog writes.
#
# A sensor's and a number's device class is refused rather than overridden.
# It decides the unit, and long-term statistics group units by the device
# class on the STATE (`sensor/recorder.py`), which the override changes — so
# a wrong one quietly breaks history nobody is looking at, and Home
# Assistant's own UI does not offer it for that reason.

SWITCH_AS_X = "switch_as_x"
# config_entries.SOURCE_USER's value: the step a person starts the flow at.
_FLOW_SOURCE_USER = "user"

# The domains that have device classes, and the enum each keeps them in —
# importable from the domain's package on every core this integration runs
# on (the enums moved into each `const.py` later and stayed re-exported).
DEVICE_CLASS_ENUMS = {
    "binary_sensor": "BinarySensorDeviceClass",
    "button": "ButtonDeviceClass",
    "cover": "CoverDeviceClass",
    "event": "EventDeviceClass",
    "humidifier": "HumidifierDeviceClass",
    "media_player": "MediaPlayerDeviceClass",
    "switch": "SwitchDeviceClass",
    "update": "UpdateDeviceClass",
    "valve": "ValveDeviceClass",
}
DEVICE_CLASS_REFUSED = {
    "sensor": (
        "{entity_id} is a sensor, and brAIn will not override a sensor's "
        "device class: it decides the unit, and Home Assistant's long-term "
        "statistics group units by it, so a wrong one breaks the history. "
        "Home Assistant's own settings do not offer it either. Its unit and "
        "display precision can be changed with brain.set_sensor_display."
    ),
    "number": (
        "{entity_id} is a number, and brAIn will not override a number's "
        "device class: it decides the unit the value is read in, and Home "
        "Assistant's own settings do not offer it."
    ),
}
# The classes brAIn's safety lane pages on through quiet hours. The lane reads
# the class off the STATE's own `device_class` attribute
# (`panel/signals.HOT_SAFETY_CLASSES`), which is exactly what a registry
# override rewrites — so showing a smoke detector as a door takes it out of
# the lane silently, and showing a motion sensor as smoke puts every motion
# into it. Spelled here because the integration cannot import the panel, and
# held equal to the panel's set by a test.
SAFETY_DEVICE_CLASSES = frozenset({"smoke", "gas", "carbon_monoxide", "moisture"})
# A binary sensor made in the UI's template helper takes its type from the
# helper's own options. Home Assistant's entity dialog hides the override
# for exactly that case (`_hideDeviceClassOverride` in the frontend's
# entity-registry-settings-editor), because a registry override beats the
# integration's class and would mask every later change made in the helper's
# options — an override the UI neither shows nor lets anybody clear.
_TEMPLATE_PLATFORM = "template"
# What switch_as_x has offered as targets, for the sentences that tell
# somebody what to do instead. Never used to validate a request: the live
# flow's own form says what this core offers.
SWITCH_AS_TARGETS = ("cover", "fan", "light", "lock", "siren", "valve")
# switch_as_x's own strings: "Invert state, only supported for cover, lock
# and valve." On a light, fan or siren Core takes the flag and ignores it.
SWITCH_AS_INVERTIBLE = ("cover", "lock", "valve")
_NO_INVERT = (
    "This Home Assistant's switch_as_x helper has no invert option (it "
    "arrived in 2024.2), so the switch can only be shown as it is."
)
# Display precision: the dialog's own choices, 0 to 6 decimals.
SENSOR_PRECISION_MAX = 6
# How long to wait for a new helper's entity to reach the registry. Setting
# the entry up is awaited by the flow, so this is a margin, not a poll.
_WRAPPER_WAIT_S = 3.0


def _domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0]


async def _component(hass: HomeAssistant, path: str):
    """A core component module (`binary_sensor`, `sensor.const`), or None
    when this core has no such thing."""
    name = f"homeassistant.components.{path}"
    module = sys.modules.get(name)
    if module is not None:
        return module
    try:
        # Off the loop: importing a component that is not loaded yet reads
        # files, which Home Assistant flags inside the event loop.
        return await hass.async_add_executor_job(importlib.import_module, name)
    except Exception:  # noqa: BLE001 — a core without it, or one that fails to load
        return None


async def _device_classes(hass: HomeAssistant, domain: str) -> list[str] | None:
    """The device classes this core offers for a domain, or None when it
    has none or will not say."""
    enum_name = DEVICE_CLASS_ENUMS.get(domain)
    if enum_name is None:
        return None
    module = await _component(hass, domain)
    enum = getattr(module, enum_name, None) if module is not None else None
    if enum is None:
        return None
    try:
        values = sorted({str(getattr(member, "value", member)) for member in enum})
    except TypeError:
        return None
    return values or None


def _not_in_registry(hass: HomeAssistant, entity_id: str, where: str) -> str:
    """Why a setting cannot be stored on an entity the registry lacks."""
    if hass.states.get(entity_id) is not None:
        return (
            f"{entity_id} has no unique ID, so Home Assistant keeps no "
            f"registry entry to store a setting on — {where}"
        )
    return f"Entity not found: {entity_id}"


def _resolve_entity_ref(registry, ref) -> str | None:
    """An entity id from either an entity id or a registry entry id.

    switch_as_x stores whichever it was handed and later rewrites it to
    follow a rename, and a 2023 registry's `async_get` takes an entity id
    only — so a uuid is looked up by walking the entries."""
    if not isinstance(ref, str) or not ref:
        return None
    if "." in ref:
        return ref
    for entry in getattr(registry, "entities", {}).values():
        if getattr(entry, "id", None) == ref:
            return entry.entity_id
    return None


def _wrapper_entity_id(registry, entry) -> str | None:
    """The entity a switch_as_x entry made — its unique_id is the entry id."""
    target = (entry.options or {}).get("target_domain")
    if not target:
        return None
    return registry.async_get_entity_id(target, SWITCH_AS_X, entry.entry_id)


def _switch_as_entries(hass: HomeAssistant, registry, switch_id: str) -> list:
    """Every switch_as_x entry wrapping this switch, with the entity it made."""
    refs = {switch_id}
    switch_entry = registry.async_get(switch_id)
    if switch_entry is not None and getattr(switch_entry, "id", None):
        refs.add(switch_entry.id)
    return [
        (entry, _wrapper_entity_id(registry, entry))
        for entry in hass.config_entries.async_entries(SWITCH_AS_X)
        if (entry.options or {}).get("entity_id") in refs
    ]


def _wrapped_switch(hass: HomeAssistant, registry, reg_entry):
    """(config entry, the switch it wraps) when this registry entry is a
    switch_as_x entity, else None."""
    if reg_entry is None or getattr(reg_entry, "platform", None) != SWITCH_AS_X:
        return None
    entry_id = getattr(reg_entry, "config_entry_id", None)
    config_entry = (
        hass.config_entries.async_get_entry(entry_id) if entry_id else None
    )
    options = getattr(reg_entry, "options", None) or {}
    switch = (options.get(SWITCH_AS_X) or {}).get("entity_id")
    if not switch and config_entry is not None:
        switch = _resolve_entity_ref(
            registry, (config_entry.options or {}).get("entity_id")
        )
    return config_entry, switch


def _references_to(hass: HomeAssistant, entity_ids) -> list[str]:
    """Automations, scripts and scenes that name any of these entities."""
    wanted = {e for e in entity_ids if e}
    if not wanted:
        return []
    return sorted(
        source_id
        for source_id, referenced in _reference_sources(hass)
        if wanted & set(referenced)
    )


async def _no_device_classes(hass: HomeAssistant, registry, entity_id: str,
                             reg_entry) -> str:
    """The sentence for an entity whose domain has no device classes."""
    domain = _domain(entity_id)
    wrapped = _wrapped_switch(hass, registry, reg_entry)
    if wrapped is not None and wrapped[1]:
        return (
            f"{entity_id} is {wrapped[1]} shown as a {domain}. To show it as "
            f"something else, call brain.show_switch_as on {wrapped[1]} with "
            "another target_domain, or brain.stop_showing_switch_as to make "
            "it a switch again."
        )
    if domain in SWITCH_AS_TARGETS:
        return (
            f"A {domain} has no device classes in Home Assistant, and only a "
            f"switch can be shown as another kind of device — so {entity_id} "
            "cannot be shown as anything else. If it runs off a smart plug, "
            "show the plug's switch as what you want with brain.show_switch_as."
        )
    return (
        f"Home Assistant has no device classes for {domain} entities. It has "
        f"them for: {', '.join(sorted(DEVICE_CLASS_ENUMS))}."
    )


async def _not_a_switch(hass: HomeAssistant, entity_id: str) -> str:
    """The sentence for show_switch_as handed something that is not a switch."""
    domain = _domain(entity_id)
    if domain in DEVICE_CLASS_ENUMS:
        choices = await _device_classes(hass, domain)
        listed = f" (choices: {', '.join(choices)})" if choices else ""
        return (
            f"{entity_id} is a {domain}, and only a switch can be shown as "
            f"another kind of device. A {domain}'s type is its device class: "
            f"change it with brain.set_device_class{listed}."
        )
    if domain == "sensor":
        return (
            f"{entity_id} is a sensor, and only a switch can be shown as "
            "another kind of device. A sensor's unit and display precision "
            "can be changed with brain.set_sensor_display."
        )
    return (
        f"{entity_id} is a {domain}, not a switch. Home Assistant can show "
        f"only a switch as another kind of device, so a {domain} cannot be "
        "shown as a light or anything else. If it is plugged into a smart "
        "plug, show that plug's switch instead (brain.show_switch_as with "
        "the plug's switch.* entity)."
    )


def _schema_fields(schema) -> dict:
    """{field name: validator} off a flow form's data_schema, or {} when it
    cannot be read. Both voluptuous's markers and its successor's keep the
    field name on the marker's `schema`."""
    fields = getattr(schema, "schema", None)
    if not isinstance(fields, dict):
        return {}
    named = {}
    for key, validator in fields.items():
        name = getattr(key, "schema", key)
        if isinstance(name, str):
            named[name] = validator
    return named


def _select_options(validator) -> list[str]:
    """The values a select selector offers, or [] when it cannot be read.
    2023 cores list `{value, label}` dicts and later ones plain values."""
    config = getattr(validator, "config", None)
    options = config.get("options") if isinstance(config, dict) else None
    if not isinstance(options, (list, tuple)):
        return []
    values = []
    for option in options:
        value = option.get("value") if isinstance(option, dict) else option
        if isinstance(value, str) and value:
            values.append(str(value))
    return values


def _check_invert_target(target: str) -> None:
    if target not in SWITCH_AS_INVERTIBLE:
        raise ServiceValidationError(
            f"invert only changes a {', a '.join(SWITCH_AS_INVERTIBLE[:-1])} "
            f"or a {SWITCH_AS_INVERTIBLE[-1]} — Home Assistant ignores it on "
            f"a {target}. Leave invert off."
        )


async def _set_invert(hass: HomeAssistant, entry, invert: bool) -> None:
    """Flip invert on an existing helper through its own options flow —
    the entity dialog's route — which reloads the entry when it finishes."""
    manager = hass.config_entries.options
    flow = await manager.async_init(entry.entry_id)
    flow_id = flow.get("flow_id") if isinstance(flow, dict) else None
    if not flow_id or flow.get("type") != "form":
        why = (flow.get("reason") or flow.get("type")) \
            if isinstance(flow, dict) else flow
        raise HomeAssistantError(
            f"Home Assistant would not open the switch_as_x helper's "
            f"options ({why})."
        )
    try:
        result = await manager.async_configure(flow_id, {"invert": invert})
    except Exception as err:  # noqa: BLE001 — the helper's own schema refusing
        with suppress(Exception):
            manager.async_abort(flow_id)
        raise HomeAssistantError(
            f"Home Assistant's switch_as_x helper would not change invert: {err}"
        ) from err
    kind = str(result.get("type")) if isinstance(result, dict) else ""
    if kind != "create_entry":
        with suppress(Exception):
            manager.async_abort(flow_id)
        reason = (result.get("reason") or result.get("errors") or kind) \
            if isinstance(result, dict) else result
        raise HomeAssistantError(
            f"Home Assistant's switch_as_x helper did not change invert ({reason})."
        )


async def _await_wrapper(hass: HomeAssistant, registry, target: str,
                         entry_id: str | None) -> str | None:
    """The new helper's entity id once the registry holds it, or None."""
    if not entry_id:
        return None
    deadline = time.monotonic() + _WRAPPER_WAIT_S
    while True:
        found = registry.async_get_entity_id(target, SWITCH_AS_X, entry_id)
        if found or time.monotonic() >= deadline:
            return found
        await asyncio.sleep(0.1)


async def _set_device_class(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Show an entity as a different kind of device: a binary sensor as a
    door, a window or a leak; a cover as a garage door or a blind; a switch
    as an outlet. An omitted or empty device_class gives back the
    integration's own. Every entity is checked before any is changed.

    Two refusals are about the entity rather than the class. A binary sensor
    made in the UI's template helper takes its type from the helper's options,
    so only clearing an override is allowed on one. And a change that takes
    an entity OUT of a safety class (smoke, gas, carbon monoxide, leak) needs
    `confirm_safety`, because brAIn's safety lane reads the class this
    rewrites; a change INTO one says so in the entity's `note`."""
    registry = er.async_get(hass)
    raw = call.data.get("device_class")
    wanted = str(raw).strip().lower() if raw is not None else ""
    wanted = wanted or None
    confirm_safety = call.data.get("confirm_safety") is True
    choices_by_domain: dict[str, list[str] | None] = {}
    plans = []
    for entity_id in call.data["entity_id"]:
        reg_entry = registry.async_get(entity_id)
        domain = _domain(entity_id)
        # The kind of entity first: "a light has no device classes" is the
        # answer for a light whether or not it has a unique ID.
        if domain in DEVICE_CLASS_REFUSED:
            raise ServiceValidationError(
                DEVICE_CLASS_REFUSED[domain].format(entity_id=entity_id)
            )
        if domain not in DEVICE_CLASS_ENUMS:
            raise ServiceValidationError(
                await _no_device_classes(hass, registry, entity_id, reg_entry)
            )
        if reg_entry is None:
            raise ServiceValidationError(_not_in_registry(
                hass, entity_id,
                "set its device class where it is defined (its YAML, or "
                "homeassistant: customize:).",
            ))
        original = getattr(reg_entry, "original_device_class", None)
        if (wanted is not None and wanted != original
                and _ui_template_binary_sensor(reg_entry, domain)):
            raise ServiceValidationError(
                f"{entity_id} is a template binary sensor made in Home "
                "Assistant's UI, and its type is set in the template helper's "
                "own options rather than with an override (Home Assistant's "
                "entity settings hide that control for it too). Change it "
                "under Settings → Devices & services → Helpers → the helper → "
                "Template options. An empty device_class still clears an "
                "override already there."
            )
        if wanted is not None:
            if domain not in choices_by_domain:
                choices_by_domain[domain] = await _device_classes(hass, domain)
            choices = choices_by_domain[domain]
            if not choices:
                raise HomeAssistantError(
                    f"brAIn could not read the device classes this Home "
                    f"Assistant offers for {domain}, so it will not write an "
                    f"unchecked one onto {entity_id}."
                )
            if wanted not in choices:
                raise ServiceValidationError(
                    f'"{wanted}" is not a {domain} device class. Choose one '
                    f"of: {', '.join(choices)} — or leave device_class empty "
                    "to give back the integration's own."
                )
        previous = getattr(reg_entry, "device_class", None) or original
        # Choosing what the integration already reports is following it:
        # stored as no override, so a later change upstream still lands.
        stored = None if wanted is None or wanted == original else wanted
        effective = stored or original
        if (previous in SAFETY_DEVICE_CLASSES
                and effective not in SAFETY_DEVICE_CLASSES
                and not confirm_safety):
            raise ServiceValidationError(
                f"{entity_id} is a {_safety_word(previous)} sensor now, and "
                f"showing it as {effective or 'no class'} takes it out of the "
                "classes brAIn's safety lane pages on: when it trips, it "
                "would no longer be filed as critical and sent straight "
                "away, through quiet hours. Ask the homeowner first; call "
                "again with confirm_safety: true only once they have said yes."
            )
        plans.append((entity_id, original, previous, stored, effective))
    changed = []
    for entity_id, original, previous, stored, effective in plans:
        registry.async_update_entity(entity_id, device_class=stored)
        row = {
            "entity_id": entity_id,
            "device_class": effective,
            "override": stored,
            "original_device_class": original,
            "previous": previous,
        }
        if (effective in SAFETY_DEVICE_CLASSES
                and previous not in SAFETY_DEVICE_CLASSES):
            row["note"] = (
                f"brAIn's safety lane now treats {entity_id} as a "
                f"{_safety_word(effective)} sensor: when it trips, it is filed "
                "as critical and sent straight away, through quiet hours."
            )
        elif (previous in SAFETY_DEVICE_CLASSES
                and effective not in SAFETY_DEVICE_CLASSES):
            row["note"] = (
                f"{entity_id} is no longer in brAIn's safety lane: when it "
                "trips, it is not filed as critical or sent through quiet hours."
            )
        changed.append(row)
    return {"entities": changed}


def _ui_template_binary_sensor(reg_entry, domain: str) -> bool:
    """A binary sensor the UI's template helper made: its type lives in the
    helper's options, the frontend's `_hideDeviceClassOverride` rule."""
    return (domain == "binary_sensor"
            and getattr(reg_entry, "platform", None) == _TEMPLATE_PLATFORM
            and bool(getattr(reg_entry, "config_entry_id", None)))


def _safety_word(device_class) -> str:
    """A safety class as a person says it: "carbon monoxide", "leak"."""
    return {"carbon_monoxide": "carbon monoxide",
            "moisture": "leak"}.get(device_class, str(device_class))


async def _show_switch_as(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Show a switch as a light, fan, lock, cover, siren or valve through
    Home Assistant's own switch_as_x helper. The original switch is hidden
    and keeps working; brain.stop_showing_switch_as undoes it. A switch
    already shown as something else is moved to the new type, the way the
    entity dialog does it."""
    entity_id = call.data["entity_id"]
    target = str(call.data["target_domain"]).strip().lower()
    invert = call.data.get("invert")
    registry = er.async_get(hass)
    wrapped = _wrapped_switch(hass, registry, registry.async_get(entity_id))
    if wrapped is not None:
        if not wrapped[1]:
            raise ServiceValidationError(
                f"{entity_id} is a switch shown as a {_domain(entity_id)}, "
                "but brAIn could not tell which switch it wraps."
            )
        switch_id = wrapped[1]
    elif _domain(entity_id) == "switch":
        switch_id = entity_id
    else:
        raise ServiceValidationError(await _not_a_switch(hass, entity_id))
    if registry.async_get(switch_id) is None and hass.states.get(switch_id) is None:
        raise ServiceValidationError(f"Entity not found: {switch_id}")
    if target == "switch":
        raise ServiceValidationError(
            f"To show {switch_id} as a switch again, call "
            "brain.stop_showing_switch_as."
        )
    if invert:
        _check_invert_target(target)
    existing = _switch_as_entries(hass, registry, switch_id)

    for entry, wrapper in existing:
        options = entry.options or {}
        if options.get("target_domain") != target:
            continue
        if invert is None or bool(options.get("invert", False)) == bool(invert):
            return {
                "entity_id": wrapper,
                "switch_entity_id": switch_id,
                "target_domain": target,
                "config_entry_id": entry.entry_id,
                "already": True,
            }
        # The same type with invert flipped: the helper's own options flow
        # changes the entry and reloads it, which keeps the entity and
        # everything somebody set on it. The dialog drives that options flow
        # and so does this, so the helper's own schema is what accepts it.
        if "invert" not in options:
            raise ServiceValidationError(_NO_INVERT)
        await _set_invert(hass, entry, bool(invert))
        return {
            "entity_id": wrapper,
            "switch_entity_id": switch_id,
            "target_domain": target,
            "config_entry_id": entry.entry_id,
            "invert": bool(invert),
            "changed": "invert",
        }

    flow = await hass.config_entries.flow.async_init(
        SWITCH_AS_X, context={"source": _FLOW_SOURCE_USER}
    )
    flow_id = flow.get("flow_id") if isinstance(flow, dict) else None
    finished = False
    replaced: list[dict] = []
    try:
        if not flow_id or flow.get("type") != "form":
            why = (flow.get("reason") or flow.get("type")) \
                if isinstance(flow, dict) else flow
            raise HomeAssistantError(
                f"Home Assistant would not start its switch_as_x helper ({why})."
            )
        fields = _schema_fields(flow.get("data_schema"))
        offered = _select_options(fields.get("target_domain"))
        if offered and target not in offered:
            raise ServiceValidationError(
                f"This Home Assistant can show a switch as: "
                f"{', '.join(offered)} — not {target}."
            )
        if invert is not None and fields and "invert" not in fields:
            if invert:
                raise ServiceValidationError(_NO_INVERT)
            invert = None  # off on a core without it is what it does anyway
        user_input: dict[str, Any] = {"entity_id": switch_id, "target_domain": target}
        if invert is not None:
            user_input["invert"] = bool(invert)
        for entry, wrapper in existing:
            replaced.append({
                "entity_id": wrapper,
                "target_domain": (entry.options or {}).get("target_domain"),
                "config_entry_id": entry.entry_id,
            })
            await hass.config_entries.async_remove(entry.entry_id)
        try:
            result = await hass.config_entries.flow.async_configure(
                flow_id, user_input
            )
        except Exception as err:  # noqa: BLE001 — the helper's own schema refusing
            raise ServiceValidationError(
                f"Home Assistant's switch_as_x helper would not show "
                f"{switch_id} as a {target}: {err}"
                + _restored_note(switch_id, replaced)
            ) from err
        kind = str(result.get("type")) if isinstance(result, dict) else ""
        finished = kind in ("create_entry", "abort")
        if kind != "create_entry":
            reason = (result.get("reason") or result.get("errors") or kind) \
                if isinstance(result, dict) else result
            raise HomeAssistantError(
                f"Home Assistant's switch_as_x helper did not create the "
                f"{target} ({reason})." + _restored_note(switch_id, replaced)
            )
    finally:
        if not finished and flow_id:
            with suppress(Exception):
                hass.config_entries.flow.async_abort(flow_id)

    entry = result.get("result")
    entry_id = getattr(entry, "entry_id", None)
    new_entity = await _await_wrapper(hass, registry, target, entry_id)
    response: dict[str, Any] = {
        "entity_id": new_entity,
        "switch_entity_id": switch_id,
        "target_domain": target,
        "config_entry_id": entry_id,
    }
    if invert is not None:
        response["invert"] = bool(invert)
    notes = []
    if new_entity is None:
        notes.append(
            "The helper was made but its entity has not appeared yet — look "
            "under Settings → Devices & services → Helpers."
        )
    if replaced:
        response["replaced"] = replaced
        references = _references_to(hass, [r["entity_id"] for r in replaced])
        if references:
            response["references_to_replaced"] = references
            notes.append(
                "These automations/scripts/scenes used the entity that was "
                f"replaced; point them at {new_entity or 'the new one'}."
            )
    if notes:
        response["note"] = " ".join(notes)
    return response


def _restored_note(switch_id: str, replaced: list[dict]) -> str:
    if not replaced:
        return ""
    gone = ", ".join(r["entity_id"] or r["config_entry_id"] for r in replaced)
    return f" The old one ({gone}) was removed, so {switch_id} shows as a switch again."


async def _stop_showing_switch_as(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Undo brain.show_switch_as: remove the switch_as_x helper, which
    unhides the switch it wrapped. Takes the helper's entity or the switch.
    dry_run previews what goes and what refers to it."""
    entity_id = call.data["entity_id"]
    registry = er.async_get(hass)
    reg_entry = registry.async_get(entity_id)
    wrapped = _wrapped_switch(hass, registry, reg_entry)
    if wrapped is not None:
        config_entry, switch_id = wrapped
        if config_entry is None:
            raise ServiceValidationError(
                f"{entity_id} was made by the switch_as_x helper, but its "
                "helper is gone — remove the leftover with "
                "brain.delete_orphaned_entities."
            )
        targets = [(config_entry, entity_id)]
    elif _domain(entity_id) == "switch":
        switch_id = entity_id
        targets = _switch_as_entries(hass, registry, switch_id)
        if not targets:
            raise ServiceValidationError(
                f"{entity_id} is not shown as another kind of device, so "
                "there is nothing to undo — it already shows as a switch."
            )
    else:
        platform = getattr(reg_entry, "platform", None)
        made_by = f" from the {platform} integration" if platform else ""
        raise ServiceValidationError(
            f"{entity_id} is a {_domain(entity_id)}{made_by}, not a switch "
            "shown as another kind of device, so there is nothing to undo."
        )
    removed = [wrapper for _, wrapper in targets]
    result: dict[str, Any] = {
        "dry_run": _dry_run(call),
        "switch_entity_id": switch_id,
        "removed_entity_ids": [w for w in removed if w],
        "config_entry_ids": [entry.entry_id for entry, _ in targets],
    }
    references = _references_to(hass, removed)
    if references:
        result["references_to_removed"] = references
        result["note"] = (
            "These automations/scripts/scenes use the entity that goes away; "
            f"point them back at {switch_id}."
        )
    if _dry_run(call):
        return result
    for entry, _ in targets:
        outcome = await hass.config_entries.async_remove(entry.entry_id)
        if isinstance(outcome, dict) and outcome.get("require_restart"):
            result["require_restart"] = True
    return result


async def _convertible_units(hass: HomeAssistant, reg_entry) -> list[str] | None:
    """The units Home Assistant can show this sensor in, or None when its
    device class has no converter (or the core will not say).

    The sensor converts by its OWN device class — the one the integration
    reports — so that is what is asked, not an override."""
    device_class = getattr(reg_entry, "original_device_class", None)
    if not device_class:
        return None
    module = await _component(hass, "sensor.const")
    converters = getattr(module, "UNIT_CONVERTERS", None) if module else None
    if not isinstance(converters, dict):
        return None
    units = getattr(converters.get(device_class), "VALID_UNITS", None)
    if not units:
        return None
    try:
        return sorted(str(unit) for unit in units if unit is not None)
    except TypeError:
        return None


async def _set_sensor_display(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Change how a sensor is shown: its display precision (decimal places)
    and, where Home Assistant can convert it, its unit. Only the fields
    named change; null puts back the integration's own."""
    named = [f for f in ("display_precision", "unit_of_measurement")
             if f in call.data]
    if not named:
        raise ServiceValidationError(
            "Nothing to update: name display_precision, unit_of_measurement "
            "or both (null puts back the integration's own)."
        )
    precision = call.data.get("display_precision")
    if precision is not None and (
        isinstance(precision, bool) or not isinstance(precision, int)
        or not 0 <= precision <= SENSOR_PRECISION_MAX
    ):
        raise ServiceValidationError(
            f"display_precision is a whole number of decimal places from 0 to "
            f"{SENSOR_PRECISION_MAX}, or null for the integration's own."
        )
    unit = call.data.get("unit_of_measurement")
    unit = str(unit).strip() if unit is not None else ""
    registry = er.async_get(hass)
    plans = []
    for entity_id in call.data["entity_id"]:
        if _domain(entity_id) != "sensor":
            raise ServiceValidationError(
                f"{entity_id} is not a sensor. Display precision and unit "
                "are a sensor's settings; to change what kind of device "
                "something is shown as, see brain.set_device_class and "
                "brain.show_switch_as."
            )
        reg_entry = registry.async_get(entity_id)
        if reg_entry is None:
            raise ServiceValidationError(_not_in_registry(
                hass, entity_id,
                "set its precision or unit where it is defined.",
            ))
        if "unit_of_measurement" in call.data and unit:
            valid = await _convertible_units(hass, reg_entry)
            if valid is None:
                kind = getattr(reg_entry, "original_device_class", None)
                raise ServiceValidationError(
                    f"{entity_id}'s unit cannot be changed: Home Assistant "
                    "converts units only for sensors whose device class has a "
                    "converter (temperature, energy, power, pressure, …), and "
                    f"this one's is {kind or 'not set'}. Its display "
                    "precision can still be changed."
                )
            if unit not in valid:
                raise ServiceValidationError(
                    f'"{unit}" is not a unit Home Assistant can show '
                    f"{entity_id} in. Choose one of: {', '.join(valid)}."
                )
        plans.append((entity_id, reg_entry))
    changed = []
    for entity_id, reg_entry in plans:
        options = dict((getattr(reg_entry, "options", None) or {}).get("sensor") or {})
        for name in named:
            value = precision if name == "display_precision" else (unit or None)
            if value is None:
                options.pop(name, None)
            else:
                options[name] = value
        registry.async_update_entity_options(entity_id, "sensor", options)
        changed.append({
            "entity_id": entity_id,
            **{name: options.get(name) for name in named},
        })
    return {"entities": changed}


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


async def _rename_device(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_device(hass, call.data["device_id"])
    dr.async_get(hass).async_update_device(
        call.data["device_id"], name_by_user=call.data["name"]
    )


# The via_device chain is a tree in theory and a linked list in practice —
# but nothing in Home Assistant enforces either, because via_device_id is
# just whatever id an integration reported. `alexa_media` points every
# device at ITSELF, so a chain walked by recursion is infinitely deep: the
# service died with RecursionError on each of an Echo/Wyze/Ecobee household's
# devices, after disabling some of them, which is the worst place for a
# registry write to stop. Both walks are iterative and carry a `seen` set,
# so a self-reference and a longer A -> B -> A cycle both end the walk at
# the point it would repeat itself rather than at the interpreter's limit.
# Stopping there loses nothing: every device on the cycle has been visited
# by the time it closes, so there is no parent left to reach.


@callback
def _via_device_chain(
    registry: dr.DeviceRegistry, device_id: str
) -> list[str]:
    """`device_id` and its via-parents, nearest first, cycle-safe.

    Stops at the first id already walked (a self-referential or looping
    via_device_id) and at the first id the registry no longer holds.
    """
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = device_id
    while current is not None and current not in seen:
        seen.add(current)
        device = registry.async_get(current)
        if device is None:
            break
        chain.append(current)
        current = device.via_device_id
    return chain


@callback
def _disable_device_and_parent_if_needed(
    registry: dr.DeviceRegistry, device_id: str
) -> None:
    """Disable a device; also disable its via-parent once no enabled
    children remain (from Spook)."""
    seen: set[str] = set()
    current: str | None = device_id
    while current is not None and current not in seen:
        seen.add(current)
        device = registry.async_get(current)
        if device is None:
            return
        if device.disabled_by is None:
            registry.async_update_device(
                current, disabled_by=dr.DeviceEntryDisabler.USER
            )
        parent_id = device.via_device_id
        if parent_id is None or parent_id in seen:
            if parent_id is not None:
                _LOGGER.debug(
                    "device %s is its own via_device ancestor; "
                    "stopping the parent walk at %s",
                    device_id,
                    current,
                )
            return
        # The just-disabled device counts as disabled whether or not the
        # registry entry we are holding has caught up with the write.
        if not all(
            child.id == current or child.disabled_by is not None
            for child in registry.devices.values()
            if child.via_device_id == parent_id
        ):
            return
        current = parent_id


@callback
def _enable_device_and_parents(
    registry: dr.DeviceRegistry, device_id: str
) -> None:
    """Enable a device and its via-parent chain (from Spook).

    Parents first, so a child is never briefly enabled under a disabled
    parent — which is the order the recursion this replaced produced.
    """
    for current in reversed(_via_device_chain(registry, device_id)):
        registry.async_update_device(current, disabled_by=None)


async def _disable_device(hass: HomeAssistant, call: ServiceCall) -> None:
    for device_id in call.data["device_id"]:
        _ensure_device(hass, device_id)
    registry = dr.async_get(hass)
    for device_id in call.data["device_id"]:
        _disable_device_and_parent_if_needed(registry, device_id)


async def _enable_device(hass: HomeAssistant, call: ServiceCall) -> None:
    for device_id in call.data["device_id"]:
        _ensure_device(hass, device_id)
    registry = dr.async_get(hass)
    for device_id in call.data["device_id"]:
        _enable_device_and_parents(registry, device_id)


def _device_summary(hass: HomeAssistant, device_id: str) -> dict:
    """What deleting this device would take with it."""
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    entities = sorted(
        e.entity_id
        for e in er.async_entries_for_device(
            er.async_get(hass), device_id, include_disabled_entities=True
        )
    )
    live = sorted(
        entry_id
        for entry_id in (device.config_entries if device else set())
        if hass.config_entries.async_get_entry(entry_id) is not None
    )
    return {
        "device_id": device_id,
        "name": (device.name_by_user or device.name) if device else None,
        "entities_removed": entities,
        "children": sorted(
            d.id for d in registry.devices.values() if d.via_device_id == device_id
        ),
        # A device its integration still provides comes straight back on the
        # next reload. Saying which entries own it is the difference between
        # "this didn't work" and "this device isn't stale".
        "live_config_entries": live,
    }


async def _delete_device(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Remove devices from the registry, with their entities.

    dry_run previews what goes. A device still provided by a loaded
    integration will be recreated the next time that integration sets up —
    the preview reports the config entries that would do it, so a delete
    that won't stick is visible before it is made rather than after.
    """
    for device_id in call.data["device_id"]:
        _ensure_device(hass, device_id)
    devices = [_device_summary(hass, d) for d in call.data["device_id"]]
    result = {"dry_run": _dry_run(call), "count": len(devices), "devices": devices}
    if _dry_run(call):
        return result
    registry = dr.async_get(hass)
    for device_id in call.data["device_id"]:
        registry.async_remove_device(device_id)
    return result


def _orphaned_devices(hass: HomeAssistant) -> list[str]:
    """Devices no loaded config entry claims any more.

    Two ways to be orphaned: no config entries at all, or config entries
    that have themselves been removed. Both leave a device in the registry
    that nothing will ever update again.
    """
    return sorted(
        device.id
        for device in dr.async_get(hass).devices.values()
        if not any(
            hass.config_entries.async_get_entry(entry_id) is not None
            for entry_id in device.config_entries
        )
    )


async def _delete_orphaned_devices(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Remove devices whose integration is gone. Dry run by default.

    The device counterpart of delete_orphaned_entities, and it defaults the
    same way: nothing is removed unless dry_run is explicitly false. An
    optional device_id list scopes it, and every requested device is
    re-checked — anything a live config entry still claims is reported
    under skipped_not_orphaned rather than deleted.
    """
    dry_run = call.data.get("dry_run", True)
    orphaned = _orphaned_devices(hass)
    requested = call.data.get("device_id")
    skipped: list[str] = []
    if requested:
        requested_set = set(requested)
        skipped = sorted(requested_set - set(orphaned))
        targets = [d for d in orphaned if d in requested_set]
    else:
        targets = orphaned
    devices = [_device_summary(hass, d) for d in targets]
    if not dry_run:
        registry = dr.async_get(hass)
        for device_id in targets:
            registry.async_remove_device(device_id)
    result = {"dry_run": dry_run, "count": len(targets), "devices": devices}
    if requested:
        result["skipped_not_orphaned"] = skipped
    return result


# ---------------------------------------------------------------------------
# Integrations (config entries)
# ---------------------------------------------------------------------------


async def _enable_integration(hass: HomeAssistant, call: ServiceCall) -> None:
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
    for entry_id in call.data["config_entry_id"]:
        await hass.config_entries.async_set_disabled_by(entry_id, None)


async def _disable_integration(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    entries = []
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
        entries.append(hass.config_entries.async_get_entry(entry_id))
    registry = er.async_get(hass)
    result = {
        "dry_run": _dry_run(call),
        "integrations": [
            {
                "config_entry_id": e.entry_id,
                "domain": e.domain,
                "title": e.title,
                "entities_affected": len(
                    er.async_entries_for_config_entry(registry, e.entry_id)
                ),
            }
            for e in entries
        ],
    }
    if _dry_run(call):
        return result
    for entry_id in call.data["config_entry_id"]:
        await hass.config_entries.async_set_disabled_by(
            entry_id, ConfigEntryDisabler.USER
        )
    return result


async def _reload_integration(hass: HomeAssistant, call: ServiceCall) -> None:
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
    for entry_id in call.data["config_entry_id"]:
        await hass.config_entries.async_reload(entry_id)


async def _delete_integration(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Remove config entries entirely — the devices and entities go too.

    Disable is reversible and this is not, so it previews the same way the
    other destructive tools do: what would be removed, and how much of the
    registry goes with it.
    """
    registry = er.async_get(hass)
    entries = []
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
        entry = hass.config_entries.async_get_entry(entry_id)
        entries.append({
            "config_entry_id": entry_id,
            "domain": entry.domain,
            "title": entry.title,
            "entities_removed": len(
                er.async_entries_for_config_entry(registry, entry_id)
            ),
            "devices_removed": len(
                dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
            ),
        })
    result = {"dry_run": _dry_run(call), "integrations": entries}
    if _dry_run(call):
        return result
    for entry_id in call.data["config_entry_id"]:
        outcome = await hass.config_entries.async_remove(entry_id)
        for e in entries:
            if e["config_entry_id"] == entry_id:
                e["require_restart"] = bool(outcome.get("require_restart"))
    return result


# ---------------------------------------------------------------------------
# Storage collections (zones, helpers, dashboards, resources, persons)
# ---------------------------------------------------------------------------


def _storage_collection(hass: HomeAssistant, domain: str, list_command=None):
    """Return a domain's storage collection.

    Most helper domains never put their collection in hass.data; the only
    stable way in is through the websocket handlers they register (Spook's
    zone workaround, generalized)."""
    data = hass.data.get(domain)
    if data is not None and hasattr(data, "async_create_item"):
        return data
    try:
        handler = hass.data["websocket_api"][list_command or f"{domain}/list"][0]
        return handler.__self__.storage_collection
    except (KeyError, IndexError, AttributeError) as err:
        raise HomeAssistantError(
            f"{domain} storage is not available on this Home Assistant version"
        ) from err


async def _collection_create(collection, data: dict, what: str) -> dict:
    """Create an item, translating the collection's schema errors."""
    try:
        return await collection.async_create_item(data)
    except vol.Invalid as err:
        raise ServiceValidationError(f"Invalid {what}: {err}") from err
    except ValueError as err:
        raise HomeAssistantError(f"Could not create {what}: {err}") from err


# ---------------------------------------------------------------------------
# Helpers (input_*, counter, timer, schedule)
# ---------------------------------------------------------------------------

HELPER_DOMAINS = (
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "counter", "timer", "schedule",
)


async def _create_helper(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Create a helper of any storage-backed type.

    Type-specific options (min/max for input_number, options for
    input_select, duration for timer, weekday blocks for schedule, ...)
    pass through and are validated by the helper's own schema, so error
    messages match what the UI would say."""
    helper_type = call.data["helper_type"]
    collection = _storage_collection(hass, helper_type)
    payload = {"name": call.data["name"], **(call.data.get("options") or {})}
    item = await _collection_create(collection, payload, f"{helper_type} helper")
    entity_id = er.async_get(hass).async_get_entity_id(
        helper_type, helper_type, item["id"]
    )
    return {"helper_type": helper_type, "id": item["id"], "entity_id": entity_id}


async def _delete_helper(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    registry = er.async_get(hass)
    targets: list[tuple[str, str, str]] = []
    for entity_id in call.data["entity_id"]:
        domain = entity_id.split(".")[0]
        if domain not in HELPER_DOMAINS:
            raise ServiceValidationError(
                f"Not a managed helper domain: {entity_id} "
                f"(supported: {', '.join(HELPER_DOMAINS)})"
            )
        entry = registry.async_get(entity_id)
        if entry is None:
            raise ServiceValidationError(f"Entity not found in registry: {entity_id}")
        targets.append((domain, entity_id, entry.unique_id))
    if _dry_run(call):
        return {
            "dry_run": True,
            "would_delete": [entity_id for _, entity_id, _ in targets],
        }
    for domain, entity_id, unique_id in targets:
        collection = _storage_collection(hass, domain)
        try:
            await collection.async_delete_item(unique_id)
        except Exception as err:  # noqa: BLE001 — ItemNotFound => YAML helper
            raise ServiceValidationError(
                f"Could not delete {entity_id} — helpers defined in YAML "
                "must be removed from the YAML file"
            ) from err
    return {
        "dry_run": False,
        "deleted": [entity_id for _, entity_id, _ in targets],
    }


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def _zone_collection(hass: HomeAssistant):
    """Zone storage collection (YAML home zone keeps it out of hass.data)."""
    return _storage_collection(hass, "zone")


async def _create_zone(hass: HomeAssistant, call: ServiceCall) -> None:
    collection = _zone_collection(hass)
    data = {
        "name": call.data["name"],
        "latitude": call.data["latitude"],
        "longitude": call.data["longitude"],
        "radius": call.data.get("radius", 100),
        "passive": call.data.get("passive", False),
    }
    if call.data.get("icon") is not None:
        data["icon"] = call.data["icon"]
    await collection.async_create_item(data)


async def _delete_zone(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    try:
        from homeassistant.helpers.entity_component import DATA_INSTANCES

        entity_component = hass.data[DATA_INSTANCES]["zone"]
    except KeyError as err:
        raise HomeAssistantError("Zone component is not loaded") from err

    collection = _zone_collection(hass)
    targets: list[tuple[str, str]] = []
    for entity_id in call.data["entity_id"]:
        entity = entity_component.get_entity(entity_id)
        if entity is None:
            raise ServiceValidationError(f"Zone not found: {entity_id}")
        if not entity.editable or "id" not in entity._config:  # noqa: SLF001
            raise ServiceValidationError(f"This zone is not editable: {entity_id}")
        targets.append((entity_id, entity._config["id"]))  # noqa: SLF001
    if _dry_run(call):
        return {
            "dry_run": True,
            "would_delete": [entity_id for entity_id, _ in targets],
        }
    for _, item_id in targets:
        await collection.async_delete_item(item_id)
    return {
        "dry_run": False,
        "deleted": [entity_id for entity_id, _ in targets],
    }


async def _update_zone(hass: HomeAssistant, call: ServiceCall) -> None:
    """Move, resize, or restyle an editable zone."""
    changes = {
        key: call.data[key]
        for key in ("name", "latitude", "longitude", "radius", "icon", "passive")
        if key in call.data
    }
    if not changes:
        raise ServiceValidationError(
            "Nothing to update — pass at least one of name, latitude, "
            "longitude, radius, icon, passive"
        )
    try:
        from homeassistant.helpers.entity_component import DATA_INSTANCES

        entity_component = hass.data[DATA_INSTANCES]["zone"]
    except KeyError as err:
        raise HomeAssistantError("Zone component is not loaded") from err

    entity_id = call.data["entity_id"]
    entity = entity_component.get_entity(entity_id)
    if entity is None:
        raise ServiceValidationError(f"Zone not found: {entity_id}")
    if not entity.editable or "id" not in entity._config:  # noqa: SLF001
        raise ServiceValidationError(f"This zone is not editable: {entity_id}")
    await _zone_collection(hass).async_update_item(
        entity._config["id"], changes  # noqa: SLF001
    )


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------


def _person_parts(hass: HomeAssistant):
    try:
        _, collection, entity_component = hass.data["person"]
    except (KeyError, TypeError, ValueError) as err:
        raise HomeAssistantError(
            "Person storage is not available on this Home Assistant version"
        ) from err
    return collection, entity_component


async def _person_trackers(
    hass: HomeAssistant, call: ServiceCall, *, add: bool
) -> None:
    collection, entity_component = _person_parts(hass)
    entity = entity_component.get_entity(call.data["entity_id"])
    if entity is None:
        raise ServiceValidationError(f"Person not found: {call.data['entity_id']}")
    if not entity.editable or "id" not in entity._config:  # noqa: SLF001
        raise ServiceValidationError(
            f"This person is not editable: {call.data['entity_id']}"
        )
    trackers = set(entity.device_trackers)
    requested = set(call.data["device_tracker"])
    trackers = trackers | requested if add else trackers - requested
    await collection.async_update_item(
        entity._config["id"],  # noqa: SLF001
        {"device_trackers": sorted(trackers)},
    )


async def _add_device_tracker_to_person(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    await _person_trackers(hass, call, add=True)


async def _remove_device_tracker_from_person(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    await _person_trackers(hass, call, add=False)


async def _rename_person(hass: HomeAssistant, call: ServiceCall) -> None:
    """Rename a person. YAML-defined people are not editable, same as
    delete_person — say so rather than failing inside the collection."""
    collection, entity_component = _person_parts(hass)
    entity = entity_component.get_entity(call.data["entity_id"])
    if entity is None:
        raise ServiceValidationError(f"Person not found: {call.data['entity_id']}")
    if not entity.editable or "id" not in entity._config:  # noqa: SLF001
        raise ServiceValidationError(
            f"This person is not editable (YAML-defined): {call.data['entity_id']}"
        )
    await collection.async_update_item(
        entity._config["id"],  # noqa: SLF001
        {"name": call.data["name"]},
    )


async def _create_person(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    collection, _ = _person_parts(hass)
    payload: dict[str, Any] = {
        "name": call.data["name"],
        "device_trackers": call.data.get("device_tracker") or [],
    }
    if call.data.get("user_id"):
        payload["user_id"] = call.data["user_id"]
    item = await _collection_create(collection, payload, "person")
    return {"person_id": item["id"]}


async def _delete_person(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    collection, entity_component = _person_parts(hass)
    entity = entity_component.get_entity(call.data["entity_id"])
    if entity is None:
        raise ServiceValidationError(f"Person not found: {call.data['entity_id']}")
    if not entity.editable or "id" not in entity._config:  # noqa: SLF001
        raise ServiceValidationError(
            f"This person is not editable (YAML-defined): {call.data['entity_id']}"
        )
    result = {
        "dry_run": _dry_run(call),
        "entity_id": call.data["entity_id"],
        "name": getattr(entity, "name", None),
        "device_trackers": sorted(entity.device_trackers or []),
    }
    if _dry_run(call):
        return result
    await collection.async_delete_item(entity._config["id"])  # noqa: SLF001
    return result


# ---------------------------------------------------------------------------
# User lifecycle
# ---------------------------------------------------------------------------


async def _create_user(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Create a Home Assistant user, optionally with a local login.

    username and password must be given together; without them the user
    exists but cannot log in until credentials are added in the UI."""
    from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER

    username = call.data.get("username")
    password = call.data.get("password")
    if bool(username) != bool(password):
        raise ServiceValidationError(
            "username and password must be provided together"
        )
    provider = None
    if username:
        provider = next(
            (p for p in hass.auth.auth_providers if p.type == "homeassistant"),
            None,
        )
        if provider is None:
            raise HomeAssistantError(
                "No Home Assistant (local) auth provider is configured — "
                "cannot create a login"
            )

    user = await hass.auth.async_create_user(
        call.data["name"],
        group_ids=[GROUP_ID_ADMIN if call.data.get("admin") else GROUP_ID_USER],
    )
    if provider:
        try:
            await provider.async_add_auth(username, password)
            credentials = await provider.async_get_or_create_credentials(
                {"username": username}
            )
            await hass.auth.async_link_user(user, credentials)
        except HomeAssistantError:
            await hass.auth.async_remove_user(user)
            raise
        except Exception as err:  # noqa: BLE001 — e.g. username taken
            await hass.auth.async_remove_user(user)
            raise HomeAssistantError(
                f"Could not create login for '{username}': {err}"
            ) from err
    return {"user_id": user.id, "name": user.name}


async def _delete_user(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    users = []
    for user_id in call.data["user_id"]:
        user = await hass.auth.async_get_user(user_id)
        if user is None:
            raise ServiceValidationError(f"User not found: {user_id}")
        if user.system_generated:
            raise ServiceValidationError(
                f"Cannot delete a system-generated user: {user_id}"
            )
        # Same lockout guard as disable_user: owners are untouchable.
        if user.is_owner:
            raise ServiceValidationError(
                f"Refusing to delete owner account: {user.name or user_id}"
            )
        users.append(user)
    result = {
        "dry_run": _dry_run(call),
        "users": [{"user_id": u.id, "name": u.name} for u in users],
    }
    if _dry_run(call):
        return result
    for user in users:
        await hass.auth.async_remove_user(user)
    return result


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------


async def _import_blueprint(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Import a blueprint from a URL (community forum, GitHub, gists...)."""
    import asyncio

    import aiohttp

    try:
        from homeassistant.components.blueprint import DOMAIN as BLUEPRINT_DOMAIN
        from homeassistant.components.blueprint.errors import FileAlreadyExists
        from homeassistant.components.blueprint.importer import (
            fetch_blueprint_from_url,
        )
    except ImportError as err:
        raise HomeAssistantError(
            "The blueprint integration is not loaded"
        ) from err

    url = call.data["url"]
    try:
        async with asyncio.timeout(15):
            imported = await fetch_blueprint_from_url(hass, url)
    except (TimeoutError, aiohttp.ClientError) as err:
        raise HomeAssistantError(
            f"Error fetching blueprint from {url}"
        ) from err
    if imported is None:
        raise ServiceValidationError(f"Unsupported blueprint URL: {url}")

    domain_blueprints = hass.data.get(BLUEPRINT_DOMAIN, {})
    if imported.blueprint.domain not in domain_blueprints:
        raise ServiceValidationError(
            f"Unsupported blueprint domain: {imported.blueprint.domain}"
        )

    imported.blueprint.update_metadata(source_url=url)
    try:
        await domain_blueprints[imported.blueprint.domain].async_add_blueprint(
            imported.blueprint, imported.suggested_filename
        )
    except FileAlreadyExists as err:
        raise ServiceValidationError(
            f"A blueprint file named {imported.suggested_filename} already exists"
        ) from err
    except OSError as err:
        raise HomeAssistantError("Error writing blueprint file") from err
    return {
        "domain": imported.blueprint.domain,
        "path": imported.suggested_filename,
        "name": imported.blueprint.name,
    }


# ---------------------------------------------------------------------------
# Statistics (recorder)
# ---------------------------------------------------------------------------


async def _import_statistics(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Import/backfill long-term statistics rows for a statistic id.

    The source is derived from the statistic_id (Spook makes callers pass
    it, which is an easy way to create rows HA refuses to load):
    entity-style ids ("sensor.gas_meter") import as recorder statistics,
    external ids ("bruh:solar_forecast") as external statistics.

    This is the most dangerous service in the file: corrupted history is
    nearly undetectable at write time, surfaces months later as a wrong
    energy chart, and can't be undone without a recorder DB restore. It
    therefore DEFAULTS TO A DRY RUN that reports the affected time range
    and how many existing rows the import would overwrite; pass
    dry_run: false to actually write.
    """
    try:
        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
            async_import_statistics,
        )
    except ImportError as err:
        raise HomeAssistantError("The recorder integration is not loaded") from err

    from homeassistant.core import valid_entity_id

    statistic_id = call.data["statistic_id"]
    is_internal = valid_entity_id(statistic_id)
    if not is_internal and ":" not in statistic_id:
        raise ServiceValidationError(
            f"Invalid statistic_id '{statistic_id}': use an entity id "
            "(sensor.gas_meter) or an external id (domain:object_id)"
        )

    stats = call.data["stats"]
    if not stats:
        raise ServiceValidationError("stats must contain at least one row")
    starts = sorted(row["start"] for row in stats)
    dry_run = call.data.get("dry_run", True)
    if dry_run:
        # Best-effort count of existing rows in the affected window — the
        # values the import would overwrite.
        existing_rows: Any = "unknown"
        try:
            from datetime import timedelta

            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            existing = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                starts[0],
                starts[-1] + timedelta(hours=1),
                {statistic_id},
                "hour",
                None,
                {"state", "sum", "mean", "min", "max"},
            )
            existing_rows = len(existing.get(statistic_id, []))
        except Exception:  # noqa: BLE001 — recorder API shape varies
            pass
        return {
            "dry_run": True,
            "statistic_id": statistic_id,
            "source": "recorder" if is_internal else "external",
            "rows_to_import": len(stats),
            "window_start": str(starts[0]),
            "window_end": str(starts[-1]),
            "existing_rows_in_window": existing_rows,
            "note": ("Nothing was written. Existing rows in this window "
                     "will be OVERWRITTEN on import and cannot be restored "
                     "without a recorder DB backup. Re-run with "
                     "dry_run: false to import."),
        }

    metadata: dict[str, Any] = {
        "has_sum": call.data["has_sum"],
        "name": call.data.get("name"),
        "source": "recorder" if is_internal else statistic_id.split(":", 1)[0],
        "statistic_id": statistic_id,
        "unit_of_measurement": call.data.get("unit_of_measurement"),
    }
    try:  # 2025.x recorder metadata shape
        from homeassistant.components.recorder.models import StatisticMeanType

        metadata["mean_type"] = (
            StatisticMeanType.ARITHMETIC
            if call.data["has_mean"]
            else StatisticMeanType.NONE
        )
        try:
            from homeassistant.components.recorder.statistics import (
                STATISTIC_UNIT_TO_UNIT_CONVERTER,
            )

            converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(
                call.data.get("unit_of_measurement")
            )
            metadata["unit_class"] = converter.UNIT_CLASS if converter else None
        except ImportError:
            # An older recorder ships no unit-converter table, so the statistic is
            # created with a null unit class rather than not created at all.
            pass
    except ImportError:  # older recorder
        metadata["has_mean"] = call.data["has_mean"]

    if is_internal:
        async_import_statistics(hass, metadata, stats)
    else:
        async_add_external_statistics(hass, metadata, stats)
    return {
        "dry_run": False,
        "statistic_id": statistic_id,
        "rows_imported": len(stats),
        "window_start": str(starts[0]),
        "window_end": str(starts[-1]),
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def _set_user_active(
    hass: HomeAssistant, call: ServiceCall, *, active: bool
) -> None:
    users = []
    for user_id in call.data["user_id"]:
        user = await hass.auth.async_get_user(user_id)
        if user is None:
            raise ServiceValidationError(f"User not found: {user_id}")
        if user.system_generated:
            raise ServiceValidationError(
                f"Cannot modify a system-generated user: {user_id}"
            )
        # Guard Spook doesn't have: an owner can never be locked out.
        if not active and user.is_owner:
            raise ServiceValidationError(
                f"Refusing to disable owner account: {user.name or user_id}"
            )
        users.append(user)
    for user in users:
        await hass.auth.async_update_user(user, is_active=active)


async def _enable_user(hass: HomeAssistant, call: ServiceCall) -> None:
    await _set_user_active(hass, call, active=True)


async def _disable_user(hass: HomeAssistant, call: ServiceCall) -> None:
    await _set_user_active(hass, call, active=False)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _reference_sources(hass: HomeAssistant):
    """Yield (config_entity_id, referenced_entity_ids) for every automation,
    script, and scene. Each source is optional — skip what isn't loaded."""
    try:
        from homeassistant.components.automation import entities_in_automation

        for state in hass.states.async_all("automation"):
            yield state.entity_id, entities_in_automation(hass, state.entity_id)
    except ImportError:
        # Not every install loads the automation component; one that does not
        # contributes no references.
        pass
    try:
        from homeassistant.components.script import entities_in_script

        for state in hass.states.async_all("script"):
            yield state.entity_id, entities_in_script(hass, state.entity_id)
    except ImportError:
        # Same for scripts: absent means nothing to yield, not an error.
        pass
    try:
        from homeassistant.components.homeassistant.scene import entities_in_scene

        for state in hass.states.async_all("scene"):
            yield state.entity_id, entities_in_scene(hass, state.entity_id)
    except ImportError:
        # Same for scenes.
        pass


def _runtime_created_entities(hass: HomeAssistant) -> set[str]:
    """Entity ids the config itself creates on demand (scene.create).

    A snapshot scene made by scene.create only exists after the automation
    has run, so "unknown right now" does not make references to it orphans.
    Scan automation/script raw configs for scene.create calls and treat the
    resulting scene ids as known.
    """
    created: set[str] = set()

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("service") == "scene.create" or node.get("action") == "scene.create":
                data = node.get("data") or {}
                scene_id = data.get("scene_id") or node.get("scene_id")
                if isinstance(scene_id, str) and scene_id:
                    created.add(f"scene.{scene_id}")
            for value in node.values():
                scan(value)
        elif isinstance(node, list):
            for item in node:
                scan(item)

    for domain in ("automation", "script"):
        component = hass.data.get(domain)
        for entity in getattr(component, "entities", None) or []:
            scan(getattr(entity, "raw_config", None))
    return created


async def _find_orphaned_references(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Report entity references in automations/scripts/scenes that point at
    entities Home Assistant doesn't know (renamed, deleted, or typo'd)."""
    known = {state.entity_id for state in hass.states.async_all()}
    known |= set(er.async_get(hass).entities)
    known |= _runtime_created_entities(hass)

    orphaned: dict[str, list[str]] = {}
    checked = 0
    for source_id, referenced in _reference_sources(hass):
        checked += 1
        unknown = sorted(
            ref for ref in referenced
            if ref not in known and "." in ref
        )
        if unknown:
            orphaned[source_id] = unknown

    if orphaned and call.data.get("create_issue"):
        lines = [
            f"- {source}: {', '.join(refs)}" for source, refs in orphaned.items()
        ]
        ir.async_create_issue(
            hass,
            DOMAIN,
            "user_orphaned_references",
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="user_issue",
            translation_placeholders={
                "title": f"{len(orphaned)} config items reference unknown entities",
                "description": "\n".join(lines)[:2000],
            },
        )
    return {
        "checked": checked,
        "sources_with_orphans": len(orphaned),
        "orphaned": orphaned,
    }


# ---------------------------------------------------------------------------
# Dashboards (Lovelace)
# ---------------------------------------------------------------------------

DASHBOARD_BACKUP_DIR = ".brain/dashboard_backups"
DASHBOARD_BACKUP_KEEP = 20


def _lovelace_dashboards(hass: HomeAssistant) -> dict:
    data = hass.data.get("lovelace")
    if data is None:
        raise HomeAssistantError("Lovelace is not loaded")
    dashboards = getattr(data, "dashboards", None)
    if dashboards is None and isinstance(data, dict):
        dashboards = data.get("dashboards")
    if dashboards is None:
        raise HomeAssistantError(
            "Could not access Lovelace dashboards on this Home Assistant version"
        )
    return dashboards


def _get_dashboard(hass: HomeAssistant, url_path: str | None):
    dashboards = _lovelace_dashboards(hass)
    key = url_path or None
    if key not in dashboards:
        available = ", ".join(sorted(str(k) for k in dashboards if k))
        raise ServiceValidationError(
            f"Dashboard not found: {url_path or 'default'}."
            + (f" Storage dashboards: {available}" if available else "")
        )
    dashboard = dashboards[key]
    if getattr(dashboard, "mode", "storage") != "storage":
        raise ServiceValidationError(
            f"Dashboard '{url_path or 'default'}' is YAML-mode — "
            "edit its YAML file instead"
        )
    return dashboard


def _dashboard_slug(url_path: str | None) -> str:
    return url_path or "default"


def _dashboard_key(url_path: str | None) -> str | None:
    """Map the explicit literal "default" (and None) to the storage key of
    the default dashboard. update_dashboard requires url_path so the
    default dashboard can never be targeted by accidental omission — only
    by passing "default" on purpose."""
    if url_path in (None, "default"):
        return None
    return url_path


def _is_backup_of(slug: str, name: str) -> bool:
    """True only for this dashboard's own backups ({slug}-{stamp}.json).

    A bare startswith(f"{slug}-") also matches OTHER dashboards whose slug
    shares the prefix (docs-shots vs docs-shots-v2): restore then picks the
    foreign file as "newest", pruning deletes the other dashboard's history,
    and the path guard accepts it. Require the exact timestamp shape after
    the slug so slugs can never shadow each other.
    """
    prefix = f"{slug}-"
    if not name.startswith(prefix):
        return False
    return re.fullmatch(r"\d{8}-\d{6}\.json", name[len(prefix):]) is not None


def _save_dashboard_backup(directory: str, slug: str, config: dict) -> str:
    """Write a timestamped backup and prune old ones. Executor-safe."""
    from datetime import datetime, timezone

    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(directory, f"{slug}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    backups = sorted(
        f for f in os.listdir(directory) if _is_backup_of(slug, f)
    )
    for stale in backups[:-DASHBOARD_BACKUP_KEEP]:
        try:
            os.remove(os.path.join(directory, stale))
        except OSError:
            # Pruning old dashboard backups is opportunistic — one that will not
            # delete is retried on the next save, and keeping it costs a file.
            pass
    return path


def _load_dashboard_backup(
    directory: str, slug: str, name: str | None
) -> tuple[str, dict]:
    """Read a named backup, or the newest one for this dashboard."""
    if name:
        # Backup names are generated server-side; refuse path tricks and
        # other dashboards' backups alike.
        if "/" in name or "\\" in name or not _is_backup_of(slug, name):
            raise ServiceValidationError(f"Not a backup of this dashboard: {name}")
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            raise ServiceValidationError(f"Backup not found: {name}")
    else:
        try:
            backups = sorted(
                f for f in os.listdir(directory) if _is_backup_of(slug, f)
            )
        except OSError:
            backups = []
        if not backups:
            raise ServiceValidationError(
                f"No backups exist for dashboard '{slug}' yet — "
                "backups are created by brain.update_dashboard"
            )
        path = os.path.join(directory, backups[-1])
    with open(path, encoding="utf-8") as fh:
        return os.path.basename(path), json.load(fh)


async def _update_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Replace a storage dashboard's config, backing up the old one first.

    Safety rails, each of which has prevented (or would have prevented) a
    real incident:
    - url_path is required; the default dashboard is only reachable via
      the explicit literal "default", never by omission.
    - saving onto a never-saved (auto-generated) dashboard permanently
      takes manual control of it, so that case requires take_control: true.
    - dry_run returns the resolved target and a change summary without
      writing anything.
    - view_index replaces a single view instead of the whole config,
      shrinking the blast radius of small edits.
    """
    url_path = _dashboard_key(call.data["url_path"])
    view_index = call.data.get("view_index")
    new_config = call.data["config"]
    dashboard = _get_dashboard(hass, url_path)

    try:
        old_config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 — dashboard never saved (auto-generated)
        old_config = None

    if view_index is not None:
        # config is ONE view object, spliced into the stored config.
        if old_config is None:
            raise ServiceValidationError(
                "view_index edits need a stored config, and this dashboard "
                "has none (it is auto-generated) — save a full config with "
                "take_control: true first"
            )
        views = old_config.get("views") or []
        if not isinstance(new_config, dict) or "views" in new_config:
            raise ServiceValidationError(
                "With view_index, config must be a single view object "
                "(not a full dashboard config)"
            )
        if not 0 <= view_index < len(views):
            raise ServiceValidationError(
                f"view_index {view_index} out of range — this dashboard "
                f"has {len(views)} views"
            )
        merged = dict(old_config)
        merged["views"] = list(views)
        merged["views"][view_index] = new_config
        new_config = merged
    elif not isinstance(new_config, dict) or not isinstance(
        new_config.get("views"), list
    ):
        raise ServiceValidationError(
            "config must be a full dashboard object with a 'views' list"
        )

    taking_control = old_config is None
    if taking_control and not call.data.get("take_control"):
        raise ServiceValidationError(
            f"Dashboard '{_dashboard_slug(url_path)}' has never been saved "
            "(it is auto-generated). Saving will take permanent manual "
            "control of it — pass take_control: true to confirm, and undo "
            "later with brain.reset_dashboard_config if needed."
        )

    if _dry_run(call):
        return {
            "dry_run": True,
            "url_path": _dashboard_slug(url_path),
            "would_take_control": taking_control,
            "old_views": len((old_config or {}).get("views") or []),
            "new_views": len(new_config["views"]),
            "edited_view_index": view_index,
            "backup_would_be_created": bool(old_config),
        }

    backup_name = None
    if old_config:
        backup_name = os.path.basename(
            await hass.async_add_executor_job(
                _save_dashboard_backup,
                hass.config.path(DASHBOARD_BACKUP_DIR),
                _dashboard_slug(url_path),
                old_config,
            )
        )

    await dashboard.async_save(new_config)
    result = {
        "url_path": _dashboard_slug(url_path),
        "views": len(new_config["views"]),
        "backup": backup_name,
    }
    if taking_control:
        result["took_control"] = True
        result["note"] = (
            "This dashboard was auto-generated; it is now manually "
            "controlled. brain.reset_dashboard_config reverts it."
        )
    return result


async def _restore_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Restore a storage dashboard from a backup (latest by default)."""
    url_path = _dashboard_key(call.data.get("url_path"))
    dashboard = _get_dashboard(hass, url_path)
    backup_name, config = await hass.async_add_executor_job(
        _load_dashboard_backup,
        hass.config.path(DASHBOARD_BACKUP_DIR),
        _dashboard_slug(url_path),
        call.data.get("backup"),
    )
    await dashboard.async_save(config)
    return {
        "url_path": _dashboard_slug(url_path),
        "restored_from": backup_name,
        "views": len(config.get("views") or []),
    }


async def _reset_dashboard_config(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Delete a dashboard's STORED config (after backing it up), reverting
    it to auto-generated. The sanctioned way to clear a config — the gap
    that previously pushed callers to raw `lovelace/config/delete` over
    websocket, which is prohibited. The dashboard itself stays registered;
    delete_dashboard removes the registration."""
    url_path = _dashboard_key(call.data["url_path"])
    dashboard = _get_dashboard(hass, url_path)
    try:
        old_config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 — never saved
        old_config = None
    if not old_config:
        raise ServiceValidationError(
            f"Dashboard '{_dashboard_slug(url_path)}' has no stored config "
            "to reset — it is already auto-generated"
        )
    if _dry_run(call):
        return {
            "dry_run": True,
            "url_path": _dashboard_slug(url_path),
            "views_in_stored_config": len(old_config.get("views") or []),
        }
    backup_name = os.path.basename(
        await hass.async_add_executor_job(
            _save_dashboard_backup,
            hass.config.path(DASHBOARD_BACKUP_DIR),
            _dashboard_slug(url_path),
            old_config,
        )
    )
    if not hasattr(dashboard, "async_delete"):
        raise HomeAssistantError(
            "Resetting a dashboard config is not supported on this "
            "Home Assistant version"
        )
    await dashboard.async_delete()
    return {
        "url_path": _dashboard_slug(url_path),
        "backup": backup_name,
        "note": ("Stored config removed — the dashboard is auto-generated "
                 "again. brain.restore_dashboard brings the config "
                 "back from the backup."),
    }


def _dashboards_collection(hass: HomeAssistant):
    return _storage_collection(
        hass, "lovelace_dashboards", list_command="lovelace/dashboards/list"
    )


async def _create_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    payload: dict[str, Any] = {
        "url_path": call.data["url_path"],
        "title": call.data["title"],
        "show_in_sidebar": call.data.get("show_in_sidebar", True),
        "require_admin": call.data.get("require_admin", False),
    }
    if call.data.get("icon"):
        payload["icon"] = call.data["icon"]
    item = await _collection_create(
        _dashboards_collection(hass), payload, "dashboard"
    )
    return {"url_path": item["url_path"], "id": item["id"]}


async def _delete_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Delete a storage dashboard, backing up its config first."""
    url_path = call.data["url_path"]
    collection = _dashboards_collection(hass)
    item = next(
        (i for i in collection.async_items() if i.get("url_path") == url_path),
        None,
    )
    if item is None:
        available = ", ".join(
            sorted(str(i.get("url_path")) for i in collection.async_items())
        )
        raise ServiceValidationError(
            f"Dashboard not found: {url_path}."
            + (f" Existing: {available}" if available else "")
        )

    backup_name = None
    dashboards = _lovelace_dashboards(hass)
    dashboard = dashboards.get(url_path)
    old_config = None
    if dashboard is not None and getattr(dashboard, "mode", "storage") == "storage":
        try:
            old_config = await dashboard.async_load(False)
        except Exception:  # noqa: BLE001 — never saved
            old_config = None
    if _dry_run(call):
        return {
            "dry_run": True,
            "url_path": url_path,
            "title": item.get("title"),
            "views_in_stored_config": len((old_config or {}).get("views") or []),
            "backup_would_be_created": bool(old_config),
        }
    if old_config:
        backup_name = os.path.basename(
            await hass.async_add_executor_job(
                _save_dashboard_backup,
                hass.config.path(DASHBOARD_BACKUP_DIR),
                _dashboard_slug(url_path),
                old_config,
            )
        )
    await collection.async_delete_item(item["id"])
    return {"url_path": url_path, "backup": backup_name}


RESOURCE_TYPES = ("module", "css", "js", "html")


def _resources_collection(hass: HomeAssistant):
    data = hass.data.get("lovelace")
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):
        resources = data.get("resources")
    if resources is None:
        raise HomeAssistantError("Lovelace resources are not available")
    if not hasattr(resources, "async_create_item"):
        raise HomeAssistantError(
            "Dashboard resources are managed in YAML on this system — "
            "edit them in configuration.yaml"
        )
    return resources


async def _add_dashboard_resource(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Register a dashboard resource (custom card module, css, ...)."""
    collection = _resources_collection(hass)
    url = call.data["url"]
    if any(i.get("url") == url for i in collection.async_items()):
        raise ServiceValidationError(f"A resource with this URL already exists: {url}")
    item = await _collection_create(
        collection,
        {"res_type": call.data.get("res_type", "module"), "url": url},
        "dashboard resource",
    )
    return {"id": item["id"], "url": url}


async def _remove_dashboard_resource(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    collection = _resources_collection(hass)
    url = call.data["url"]
    matches = [i for i in collection.async_items() if i.get("url") == url]
    if not matches:
        urls = ", ".join(sorted(str(i.get("url")) for i in collection.async_items())[:20])
        raise ServiceValidationError(
            f"No resource with URL: {url}." + (f" Registered: {urls}" if urls else "")
        )
    for item in matches:
        await collection.async_delete_item(item["id"])


# ---------------------------------------------------------------------------
# Repairs
# ---------------------------------------------------------------------------


async def _create_repair_issue(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    issue_id = call.data.get("issue_id")
    if not issue_id:
        from homeassistant.util.ulid import ulid

        issue_id = ulid()
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"user_{issue_id}",
        is_fixable=True,
        is_persistent=call.data.get("persistent", False),
        severity=ir.IssueSeverity(call.data.get("severity", "warning")),
        translation_key="user_issue",
        translation_placeholders={
            "title": call.data["title"],
            "description": call.data["description"],
        },
    )
    return {"issue_id": issue_id}


async def _remove_repair_issue(hass: HomeAssistant, call: ServiceCall) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"user_{call.data['issue_id']}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_STR_LIST = vol.All(cv.ensure_list, [cv.string])
_ENTITY_LIST = vol.All(cv.ensure_list, [cv.entity_id])


@dataclass(frozen=True)
class PowerTool:
    """One brain.* admin service."""

    service: str
    handler: Callable
    schema: dict = field(default_factory=dict)
    has_response: bool = False


POWER_TOOLS: tuple[PowerTool, ...] = (
    # Areas
    PowerTool("create_area", _create_area, {
        vol.Required("name"): cv.string,
        vol.Optional("icon"): cv.icon,
        vol.Optional("aliases"): _STR_LIST,
        vol.Optional("floor_id"): cv.string,
    }, has_response=True),
    PowerTool("delete_area", _delete_area, {
        vol.Required("area_id"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("rename_area", _rename_area, {
        vol.Required("area_id"): cv.string,
        vol.Required("name"): cv.string,
    }),
    PowerTool("set_area_aliases", _set_area_aliases, {
        vol.Required("area_id"): cv.string,
        vol.Required("aliases"): _STR_LIST,
    }),
    PowerTool("set_area_icon", _set_area_icon, {
        vol.Required("area_id"): cv.string,
        vol.Optional("icon"): cv.icon,
    }),
    PowerTool("add_device_to_area", _add_device_to_area, {
        vol.Required("area_id"): cv.string,
        vol.Required("device_id"): _STR_LIST,
    }),
    PowerTool("remove_device_from_area", _remove_device_from_area, {
        vol.Required("device_id"): _STR_LIST,
    }),
    PowerTool("add_entity_to_area", _add_entity_to_area, {
        vol.Required("area_id"): cv.string,
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    PowerTool("remove_entity_from_area", _remove_entity_from_area, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    # Floors
    PowerTool("create_floor", _create_floor, {
        vol.Required("name"): cv.string,
        vol.Optional("icon"): cv.icon,
        vol.Optional("level"): vol.Coerce(int),
        vol.Optional("aliases"): _STR_LIST,
    }, has_response=True),
    PowerTool("delete_floor", _delete_floor, {
        vol.Required("floor_id"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("rename_floor", _rename_floor, {
        vol.Required("floor_id"): cv.string,
        vol.Required("name"): cv.string,
    }),
    PowerTool("update_floor", _update_floor, {
        vol.Required("floor_id"): cv.string,
        vol.Optional("icon"): vol.Any(None, cv.icon),
        vol.Optional("level"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("aliases"): _STR_LIST,
    }),
    PowerTool("add_area_to_floor", _add_area_to_floor, {
        vol.Required("floor_id"): cv.string,
        vol.Required("area_id"): _STR_LIST,
    }),
    PowerTool("remove_area_from_floor", _remove_area_from_floor, {
        vol.Required("area_id"): _STR_LIST,
    }),
    # Labels
    PowerTool("create_label", _create_label, {
        vol.Required("name"): cv.string,
        vol.Optional("icon"): cv.icon,
        vol.Optional("color"): vol.Any(cv.color_hex, vol.In(LABEL_THEME_COLORS)),
        vol.Optional("description"): cv.string,
    }, has_response=True),
    PowerTool("rename_label", _rename_label, {
        vol.Required("label_id"): cv.string,
        vol.Required("name"): cv.string,
    }),
    PowerTool("update_label", _update_label, {
        vol.Required("label_id"): cv.string,
        vol.Optional("icon"): vol.Any(None, cv.icon),
        vol.Optional("color"): vol.Any(None, cv.color_hex, vol.In(LABEL_THEME_COLORS)),
        vol.Optional("description"): vol.Any(None, cv.string),
    }),
    PowerTool("delete_label", _delete_label, {
        vol.Required("label_id"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("add_label", _add_label, {
        vol.Required("label_id"): _STR_LIST,
        vol.Optional("entity_id"): _ENTITY_LIST,
        vol.Optional("device_id"): _STR_LIST,
        vol.Optional("area_id"): _STR_LIST,
    }),
    PowerTool("remove_label", _remove_label, {
        vol.Required("label_id"): _STR_LIST,
        vol.Optional("entity_id"): _ENTITY_LIST,
        vol.Optional("device_id"): _STR_LIST,
        vol.Optional("area_id"): _STR_LIST,
    }),
    # Entities
    PowerTool("rename_entity", _rename_entity, {
        vol.Required("entity_id"): _ENTITY_LIST,
        vol.Required("name"): cv.string,
    }),
    PowerTool("change_entity_id", _change_entity_id, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("new_entity_id"): cv.entity_id,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("enable_entity", _enable_entity, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    PowerTool("disable_entity", _disable_entity, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    PowerTool("hide_entity", _hide_entity, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    PowerTool("unhide_entity", _unhide_entity, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    PowerTool("set_entity_aliases", _set_entity_aliases, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("aliases"): _STR_LIST,
    }),
    PowerTool("set_entity_icon", _set_entity_icon, {
        vol.Required("entity_id"): _ENTITY_LIST,
        vol.Optional("icon"): cv.icon,
    }),
    PowerTool("delete_orphaned_entities", _delete_orphaned_entities, {
        vol.Optional("dry_run", default=True): cv.boolean,
        vol.Optional("entity_id"): _ENTITY_LIST,
    }, has_response=True),
    # Device types — the entity dialog's "Show as"
    PowerTool("set_device_class", _set_device_class, {
        vol.Required("entity_id"): _ENTITY_LIST,
        # Omitted, empty or null gives back the integration's own; the value
        # is checked against the domain's device classes in the handler,
        # because which those are is a question for the running core.
        vol.Optional("device_class"): vol.Any(None, cv.string),
        # Taking an entity OUT of a safety class needs this, and only a yes
        # from the homeowner is a reason to send it.
        vol.Optional("confirm_safety", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("show_switch_as", _show_switch_as, {
        vol.Required("entity_id"): cv.entity_id,
        # Checked against what the core's own switch_as_x flow offers.
        vol.Required("target_domain"): cv.string,
        vol.Optional("invert"): cv.boolean,
    }, has_response=True),
    PowerTool("stop_showing_switch_as", _stop_showing_switch_as, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("set_sensor_display", _set_sensor_display, {
        vol.Required("entity_id"): _ENTITY_LIST,
        vol.Optional("display_precision"): vol.Any(
            None,
            vol.All(vol.Coerce(int), vol.Range(min=0, max=SENSOR_PRECISION_MAX)),
        ),
        vol.Optional("unit_of_measurement"): vol.Any(None, cv.string),
    }, has_response=True),
    # Devices
    PowerTool("rename_device", _rename_device, {
        vol.Required("device_id"): cv.string,
        vol.Required("name"): cv.string,
    }),
    PowerTool("enable_device", _enable_device, {
        vol.Required("device_id"): _STR_LIST,
    }),
    PowerTool("disable_device", _disable_device, {
        vol.Required("device_id"): _STR_LIST,
    }),
    PowerTool("delete_device", _delete_device, {
        vol.Required("device_id"): _STR_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("delete_orphaned_devices", _delete_orphaned_devices, {
        vol.Optional("dry_run", default=True): cv.boolean,
        vol.Optional("device_id"): _STR_LIST,
    }, has_response=True),
    # Integrations
    PowerTool("enable_integration", _enable_integration, {
        vol.Required("config_entry_id"): _STR_LIST,
    }),
    PowerTool("disable_integration", _disable_integration, {
        vol.Required("config_entry_id"): _STR_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("reload_integration", _reload_integration, {
        vol.Required("config_entry_id"): _STR_LIST,
    }),
    PowerTool("delete_integration", _delete_integration, {
        vol.Required("config_entry_id"): _STR_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    # Helpers
    PowerTool("create_helper", _create_helper, {
        vol.Required("helper_type"): vol.In(HELPER_DOMAINS),
        vol.Required("name"): cv.string,
        vol.Optional("options"): dict,
    }, has_response=True),
    PowerTool("delete_helper", _delete_helper, {
        vol.Required("entity_id"): _ENTITY_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    # Zones
    PowerTool("create_zone", _create_zone, {
        vol.Required("name"): cv.string,
        vol.Required("latitude"): cv.latitude,
        vol.Required("longitude"): cv.longitude,
        vol.Optional("radius"): vol.Coerce(float),
        vol.Optional("icon"): cv.icon,
        vol.Optional("passive"): cv.boolean,
    }),
    PowerTool("update_zone", _update_zone, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("name"): cv.string,
        vol.Optional("latitude"): cv.latitude,
        vol.Optional("longitude"): cv.longitude,
        vol.Optional("radius"): vol.Coerce(float),
        vol.Optional("icon"): cv.icon,
        vol.Optional("passive"): cv.boolean,
    }),
    PowerTool("delete_zone", _delete_zone, {
        vol.Required("entity_id"): _ENTITY_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    # Persons
    PowerTool("create_person", _create_person, {
        vol.Required("name"): cv.string,
        vol.Optional("user_id"): cv.string,
        vol.Optional("device_tracker"): _ENTITY_LIST,
    }, has_response=True),
    PowerTool("delete_person", _delete_person, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("rename_person", _rename_person, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("name"): cv.string,
    }),
    PowerTool("add_device_tracker_to_person", _add_device_tracker_to_person, {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("device_tracker"): _ENTITY_LIST,
    }),
    PowerTool(
        "remove_device_tracker_from_person", _remove_device_tracker_from_person, {
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("device_tracker"): _ENTITY_LIST,
        },
    ),
    # Blueprints
    PowerTool("import_blueprint", _import_blueprint, {
        vol.Required("url"): cv.url,
    }, has_response=True),
    # Statistics
    PowerTool("import_statistics", _import_statistics, {
        vol.Required("statistic_id"): cv.string,
        vol.Required("has_mean"): cv.boolean,
        vol.Required("has_sum"): cv.boolean,
        vol.Optional("name"): cv.string,
        vol.Optional("unit_of_measurement"): cv.string,
        vol.Optional("dry_run", default=True): cv.boolean,
        vol.Required("stats"): [
            {
                vol.Required("start"): cv.datetime,
                vol.Optional("mean"): vol.Coerce(float),
                vol.Optional("min"): vol.Coerce(float),
                vol.Optional("max"): vol.Coerce(float),
                vol.Optional("last_reset"): vol.Any(None, cv.datetime),
                vol.Optional("state"): vol.Coerce(float),
                vol.Optional("sum"): vol.Coerce(float),
            },
        ],
    }, has_response=True),
    # Users
    PowerTool("create_user", _create_user, {
        vol.Required("name"): cv.string,
        vol.Optional("username"): cv.string,
        vol.Optional("password"): vol.All(cv.string, vol.Length(min=8)),
        vol.Optional("admin", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("delete_user", _delete_user, {
        vol.Required("user_id"): _STR_LIST,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("enable_user", _enable_user, {
        vol.Required("user_id"): _STR_LIST,
    }),
    PowerTool("disable_user", _disable_user, {
        vol.Required("user_id"): _STR_LIST,
    }),
    # Diagnostics
    PowerTool("find_orphaned_references", _find_orphaned_references, {
        vol.Optional("create_issue", default=False): cv.boolean,
    }, has_response=True),
    # Dashboards
    PowerTool("update_dashboard", _update_dashboard, {
        vol.Required("config"): dict,
        # Required on purpose: "omit for the default dashboard" was a trap —
        # the default is only reachable via the explicit literal "default".
        vol.Required("url_path"): cv.string,
        vol.Optional("take_control", default=False): cv.boolean,
        vol.Optional("view_index"): vol.Coerce(int),
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("restore_dashboard", _restore_dashboard, {
        vol.Optional("url_path"): cv.string,
        vol.Optional("backup"): cv.string,
    }, has_response=True),
    PowerTool("reset_dashboard_config", _reset_dashboard_config, {
        vol.Required("url_path"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("create_dashboard", _create_dashboard, {
        vol.Required("url_path"): cv.string,
        vol.Required("title"): cv.string,
        vol.Optional("icon"): cv.icon,
        vol.Optional("show_in_sidebar", default=True): cv.boolean,
        vol.Optional("require_admin", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("delete_dashboard", _delete_dashboard, {
        vol.Required("url_path"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }, has_response=True),
    PowerTool("add_dashboard_resource", _add_dashboard_resource, {
        vol.Required("url"): cv.string,
        vol.Optional("res_type", default="module"): vol.In(RESOURCE_TYPES),
    }, has_response=True),
    PowerTool("remove_dashboard_resource", _remove_dashboard_resource, {
        vol.Required("url"): cv.string,
    }),
    # Repairs
    PowerTool("create_repair_issue", _create_repair_issue, {
        vol.Required("title"): cv.string,
        vol.Required("description"): cv.string,
        vol.Optional("severity", default="warning"): vol.In(ISSUE_SEVERITIES),
        vol.Optional("persistent", default=False): cv.boolean,
        vol.Optional("issue_id"): cv.string,
    }, has_response=True),
    PowerTool("remove_repair_issue", _remove_repair_issue, {
        vol.Required("issue_id"): cv.string,
    }),
)

POWER_TOOL_SERVICES: tuple[str, ...] = tuple(t.service for t in POWER_TOOLS)


# Fields that must never reach the audit log verbatim.
_AUDIT_REDACTED_FIELDS = {"password"}
# Cap per-call audit payloads (dashboard configs run to hundreds of KB).
_AUDIT_MAX_CHARS = 2000


def _audit_payload(data: Any) -> str:
    """Serialize service-call data for the audit log, redacted and capped."""
    try:
        redacted = {
            k: ("**redacted**" if k in _AUDIT_REDACTED_FIELDS else v)
            for k, v in dict(data).items()
        }
        text = json.dumps(redacted, default=str)
    except (TypeError, ValueError):
        text = repr(data)
    if len(text) > _AUDIT_MAX_CHARS:
        text = text[:_AUDIT_MAX_CHARS] + f"... [{len(text)} chars total]"
    return text


async def async_require_admin(hass: HomeAssistant, context) -> None:
    """Raise unless the caller may use an admin service.

    The same check Home Assistant applies to `async_register_admin_service`,
    replicated because that registration cannot return response data. A
    context with no user is the system — an automation, a script started by
    one, the integration itself — and passes, which is HA's own rule: only
    an admin can write an automation in the first place, so an automation
    calling this is an admin's decision. Lifted out of `_admin_gated` so
    the core services that reach a shell or durable memory (`run_task`,
    `ask`, `add_memory`, …) ask the SAME question, rather than a second
    copy of it drifting from this one.
    """
    user_id = getattr(context, "user_id", None)
    if not user_id:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(context=context)
    if not user.is_admin:
        raise Unauthorized(context=context)


def _admin_gated(hass: HomeAssistant, tool: PowerTool):
    """Wrap a handler with the same admin check HA applies to admin
    services (async_register_admin_service doesn't support response data,
    so the gate is replicated here — see `async_require_admin`).

    Also the audit chokepoint: every power-tool call — these services
    rename entities, delete areas, disable integrations, delete users —
    leaves one structured log line with the service, its arguments, and
    the outcome, so there is a forensic trail when something needs to be
    traced or undone."""

    async def wrapped(call: ServiceCall):
        await async_require_admin(hass, call.context)
        _LOGGER.info(
            "BRUH audit: %s.%s called (user_id=%s) data=%s",
            DOMAIN, tool.service, call.context.user_id or "-",
            _audit_payload(call.data),
        )
        try:
            result = await tool.handler(hass, call)
        except Exception as err:
            _LOGGER.warning(
                "BRUH audit: %s.%s FAILED: %s", DOMAIN, tool.service, err
            )
            raise
        _LOGGER.info(
            "BRUH audit: %s.%s ok%s",
            DOMAIN, tool.service,
            f" result={_audit_payload(result)}" if isinstance(result, dict) else "",
        )
        return result

    return wrapped


@callback
def async_register_power_tools(hass: HomeAssistant) -> None:
    """Register every power-tool service under the brain domain."""
    for tool in POWER_TOOLS:
        if hass.services.has_service(DOMAIN, tool.service):
            continue
        kwargs: dict[str, Any] = {}
        if tool.has_response and SupportsResponse is not None:
            kwargs["supports_response"] = SupportsResponse.OPTIONAL
        hass.services.async_register(
            DOMAIN,
            tool.service,
            _admin_gated(hass, tool),
            schema=vol.Schema(tool.schema) if tool.schema else None,
            **kwargs,
        )
    _LOGGER.debug("Registered %d BRUH power tools", len(POWER_TOOLS))
