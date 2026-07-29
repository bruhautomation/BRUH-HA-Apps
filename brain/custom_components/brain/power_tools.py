"""BRUH Power Tools — advanced Home Assistant admin services.

Registry-management services exposed under the `brain` domain so
Claude (and any automation, script, or Assist pipeline) can reorganize a
Home Assistant instance through supervised, validated service calls
instead of editing `/config/.storage` files by hand:

- Areas:        create, delete, rename, set aliases, assign devices/entities
- Floors:       create, delete, rename, assign areas
- Labels:       create, delete, apply/remove on entities, devices, areas
- Entities:     rename, change entity_id, enable/disable, hide/unhide,
                voice aliases, icon overrides, orphan cleanup (dry-run default)
- Devices:      rename, enable/disable (cascades to lonely parent devices)
- Integrations: enable/disable/reload config entries
- Helpers:      create/delete any storage-backed helper (input_*, counter,
                timer, schedule)
- Zones:        create, update, delete
- Persons:      create/delete, attach/detach device trackers
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
"""

from __future__ import annotations

import json
import logging
import os
import re
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
# Devices
# ---------------------------------------------------------------------------


async def _rename_device(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_device(hass, call.data["device_id"])
    dr.async_get(hass).async_update_device(
        call.data["device_id"], name_by_user=call.data["name"]
    )


@callback
def _disable_device_and_parent_if_needed(
    registry: dr.DeviceRegistry, device_id: str
) -> None:
    """Disable a device; also disable its via-parent once no enabled
    children remain (from Spook)."""
    device = registry.async_get(device_id)
    if device is None:
        return
    if device.disabled_by is None:
        registry.async_update_device(
            device_id, disabled_by=dr.DeviceEntryDisabler.USER
        )
    if device.via_device_id is None:
        return
    if all(
        child.id == device_id or child.disabled_by is not None
        for child in registry.devices.values()
        if child.via_device_id == device.via_device_id
    ):
        _disable_device_and_parent_if_needed(registry, device.via_device_id)


@callback
def _enable_device_and_parents(
    registry: dr.DeviceRegistry, device_id: str
) -> None:
    """Enable a device and its via-parent chain (from Spook)."""
    device = registry.async_get(device_id)
    if device is None:
        return
    if device.via_device_id is not None:
        _enable_device_and_parents(registry, device.via_device_id)
    registry.async_update_device(device_id, disabled_by=None)


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
        pass
    try:
        from homeassistant.components.script import entities_in_script

        for state in hass.states.async_all("script"):
            yield state.entity_id, entities_in_script(hass, state.entity_id)
    except ImportError:
        pass
    try:
        from homeassistant.components.homeassistant.scene import entities_in_scene

        for state in hass.states.async_all("scene"):
            yield state.entity_id, entities_in_scene(hass, state.entity_id)
    except ImportError:
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


def _admin_gated(hass: HomeAssistant, tool: PowerTool):
    """Wrap a handler with the same admin check HA applies to admin
    services (async_register_admin_service doesn't support response data,
    so the gate is replicated here).

    Also the audit chokepoint: every power-tool call — these services
    rename entities, delete areas, disable integrations, delete users —
    leaves one structured log line with the service, its arguments, and
    the outcome, so there is a forensic trail when something needs to be
    traced or undone."""

    async def wrapped(call: ServiceCall):
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise UnknownUser(context=call.context)
            if not user.is_admin:
                raise Unauthorized(context=call.context)
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
