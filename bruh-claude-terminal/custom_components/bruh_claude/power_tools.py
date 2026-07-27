"""BRUH Power Tools — advanced Home Assistant admin services.

Registry-management services exposed under the `bruh_claude` domain so
Claude (and any automation, script, or Assist pipeline) can reorganize a
Home Assistant instance through supervised, validated service calls
instead of editing `/config/.storage` files by hand:

- Areas:        create, delete, rename, set aliases, assign devices/entities
- Floors:       create, delete, rename, assign areas
- Labels:       create, delete, apply/remove on entities, devices, areas
- Entities:     rename, change entity_id, enable/disable, hide/unhide,
                clean up orphaned registry entries (dry-run by default)
- Devices:      rename, enable/disable (cascades to lonely parent devices)
- Integrations: enable/disable/reload config entries
- Zones:        create, delete
- Persons:      attach/detach device trackers
- Blueprints:   import automation/script blueprints from a URL
- Statistics:   import/backfill long-term statistics (recorder)
- Users:        enable/disable accounts (owner accounts are protected)
- Diagnostics:  find automation/script/scene references to unknown entities
- Dashboards:   update/restore storage dashboards with automatic backups
- Repairs:      create/remove custom issues in Settings > System > Repairs

Adapted from Spook (https://github.com/frenck/spook) by Franck Nijhof,
released under the MIT License. Changes from Spook:
- all services live under `bruh_claude.*` instead of overloading core
  domains, so they never collide with Spook itself or future HA services
- every referenced registry id is validated up front with a clear error
  before anything is changed
- creation services return the new registry id as response data
- `delete_orphaned_entities` defaults to a dry run that reports what it
  would remove
- label application is consolidated into two multi-target services
  (`add_label` / `remove_label`) instead of six single-target ones
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized, UnknownUser
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
        raise HomeAssistantError(f"Area not found: {area_id}")


def _ensure_floor(hass: HomeAssistant, floor_id: str) -> None:
    _require_floors()
    if not fr.async_get(hass).async_get_floor(floor_id):
        raise HomeAssistantError(f"Floor not found: {floor_id}")


def _ensure_label(hass: HomeAssistant, label_id: str) -> None:
    _require_labels()
    if not lr.async_get(hass).async_get_label(label_id):
        raise HomeAssistantError(f"Label not found: {label_id}")


def _ensure_device(hass: HomeAssistant, device_id: str) -> None:
    if not dr.async_get(hass).async_get(device_id):
        raise HomeAssistantError(f"Device not found: {device_id}")


def _ensure_entity(hass: HomeAssistant, entity_id: str) -> None:
    if not er.async_get(hass).async_get(entity_id):
        raise HomeAssistantError(f"Entity not found in registry: {entity_id}")


def _ensure_config_entry(hass: HomeAssistant, entry_id: str) -> None:
    if not hass.config_entries.async_get_entry(entry_id):
        raise HomeAssistantError(f"Config entry not found: {entry_id}")


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


async def _delete_area(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_area(hass, call.data["area_id"])
    ar.async_get(hass).async_delete(call.data["area_id"])


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


async def _delete_floor(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_floor(hass, call.data["floor_id"])
    fr.async_get(hass).async_delete(call.data["floor_id"])


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


async def _delete_label(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_label(hass, call.data["label_id"])
    lr.async_get(hass).async_delete(call.data["label_id"])


def _label_targets(call: ServiceCall) -> tuple[list[str], list[str], list[str]]:
    entities = call.data.get("entity_id") or []
    devices = call.data.get("device_id") or []
    areas = call.data.get("area_id") or []
    if not (entities or devices or areas):
        raise HomeAssistantError(
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


async def _change_entity_id(hass: HomeAssistant, call: ServiceCall) -> None:
    _ensure_entity(hass, call.data["entity_id"])
    er.async_get(hass).async_update_entity(
        call.data["entity_id"], new_entity_id=call.data["new_entity_id"]
    )


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


async def _disable_integration(hass: HomeAssistant, call: ServiceCall) -> None:
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
    for entry_id in call.data["config_entry_id"]:
        await hass.config_entries.async_set_disabled_by(
            entry_id, ConfigEntryDisabler.USER
        )


async def _reload_integration(hass: HomeAssistant, call: ServiceCall) -> None:
    for entry_id in call.data["config_entry_id"]:
        _ensure_config_entry(hass, entry_id)
    for entry_id in call.data["config_entry_id"]:
        await hass.config_entries.async_reload(entry_id)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def _zone_collection(hass: HomeAssistant):
    """Return zone storage collection; handles the YAML-home-zone case
    where HA doesn't put the collection in hass.data (from Spook)."""
    zone_data = hass.data.get("zone")
    if zone_data is not None:
        return zone_data
    try:
        return hass.data["websocket_api"]["zone/list"][0].__self__.storage_collection
    except (KeyError, IndexError, AttributeError) as err:
        raise HomeAssistantError(
            "Zone storage is not available on this Home Assistant version"
        ) from err


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


async def _delete_zone(hass: HomeAssistant, call: ServiceCall) -> None:
    try:
        from homeassistant.helpers.entity_component import DATA_INSTANCES

        entity_component = hass.data[DATA_INSTANCES]["zone"]
    except KeyError as err:
        raise HomeAssistantError("Zone component is not loaded") from err

    collection = _zone_collection(hass)
    for entity_id in call.data["entity_id"]:
        entity = entity_component.get_entity(entity_id)
        if entity is None:
            raise HomeAssistantError(f"Zone not found: {entity_id}")
        if not entity.editable or "id" not in entity._config:  # noqa: SLF001
            raise HomeAssistantError(f"This zone is not editable: {entity_id}")
        await collection.async_delete_item(entity._config["id"])  # noqa: SLF001


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
        raise HomeAssistantError(f"Person not found: {call.data['entity_id']}")
    if not entity.editable or "id" not in entity._config:  # noqa: SLF001
        raise HomeAssistantError(
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
        raise HomeAssistantError(f"Unsupported blueprint URL: {url}")

    domain_blueprints = hass.data.get(BLUEPRINT_DOMAIN, {})
    if imported.blueprint.domain not in domain_blueprints:
        raise HomeAssistantError(
            f"Unsupported blueprint domain: {imported.blueprint.domain}"
        )

    imported.blueprint.update_metadata(source_url=url)
    try:
        await domain_blueprints[imported.blueprint.domain].async_add_blueprint(
            imported.blueprint, imported.suggested_filename
        )
    except FileAlreadyExists as err:
        raise HomeAssistantError(
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


async def _import_statistics(hass: HomeAssistant, call: ServiceCall) -> None:
    """Import/backfill long-term statistics rows for a statistic id.

    The source is derived from the statistic_id (Spook makes callers pass
    it, which is an easy way to create rows HA refuses to load):
    entity-style ids ("sensor.gas_meter") import as recorder statistics,
    external ids ("bruh:solar_forecast") as external statistics.
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
        raise HomeAssistantError(
            f"Invalid statistic_id '{statistic_id}': use an entity id "
            "(sensor.gas_meter) or an external id (domain:object_id)"
        )

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
        async_import_statistics(hass, metadata, call.data["stats"])
    else:
        async_add_external_statistics(hass, metadata, call.data["stats"])


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
            raise HomeAssistantError(f"User not found: {user_id}")
        if user.system_generated:
            raise HomeAssistantError(
                f"Cannot modify a system-generated user: {user_id}"
            )
        # Guard Spook doesn't have: an owner can never be locked out.
        if not active and user.is_owner:
            raise HomeAssistantError(
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


async def _find_orphaned_references(
    hass: HomeAssistant, call: ServiceCall
) -> dict | None:
    """Report entity references in automations/scripts/scenes that point at
    entities Home Assistant doesn't know (renamed, deleted, or typo'd)."""
    known = {state.entity_id for state in hass.states.async_all()}
    known |= set(er.async_get(hass).entities)

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

DASHBOARD_BACKUP_DIR = ".bruh_claude/dashboard_backups"
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
        raise HomeAssistantError(
            f"Dashboard not found: {url_path or 'default'}."
            + (f" Storage dashboards: {available}" if available else "")
        )
    dashboard = dashboards[key]
    if getattr(dashboard, "mode", "storage") != "storage":
        raise HomeAssistantError(
            f"Dashboard '{url_path or 'default'}' is YAML-mode — "
            "edit its YAML file instead"
        )
    return dashboard


def _dashboard_slug(url_path: str | None) -> str:
    return url_path or "default"


def _save_dashboard_backup(directory: str, slug: str, config: dict) -> str:
    """Write a timestamped backup and prune old ones. Executor-safe."""
    from datetime import datetime, timezone

    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(directory, f"{slug}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    backups = sorted(
        f for f in os.listdir(directory)
        if f.startswith(f"{slug}-") and f.endswith(".json")
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
        # Backup names are generated server-side; refuse path tricks.
        if "/" in name or "\\" in name or not name.startswith(f"{slug}-"):
            raise HomeAssistantError(f"Not a backup of this dashboard: {name}")
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            raise HomeAssistantError(f"Backup not found: {name}")
    else:
        try:
            backups = sorted(
                f for f in os.listdir(directory)
                if f.startswith(f"{slug}-") and f.endswith(".json")
            )
        except OSError:
            backups = []
        if not backups:
            raise HomeAssistantError(
                f"No backups exist for dashboard '{slug}' yet — "
                "backups are created by bruh_claude.update_dashboard"
            )
        path = os.path.join(directory, backups[-1])
    with open(path, encoding="utf-8") as fh:
        return os.path.basename(path), json.load(fh)


async def _update_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Replace a storage dashboard's config, backing up the old one first."""
    new_config = call.data["config"]
    if not isinstance(new_config, dict) or not isinstance(
        new_config.get("views"), list
    ):
        raise HomeAssistantError(
            "config must be a full dashboard object with a 'views' list"
        )
    url_path = call.data.get("url_path")
    dashboard = _get_dashboard(hass, url_path)

    backup_name = None
    try:
        old_config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 — dashboard never saved (auto-generated)
        old_config = None
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
    return {
        "url_path": _dashboard_slug(url_path),
        "views": len(new_config["views"]),
        "backup": backup_name,
    }


async def _restore_dashboard(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    """Restore a storage dashboard from a backup (latest by default)."""
    url_path = call.data.get("url_path")
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
    """One bruh_claude.* admin service."""

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
    }),
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
    }),
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
    }),
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
    }),
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
    }),
    PowerTool("reload_integration", _reload_integration, {
        vol.Required("config_entry_id"): _STR_LIST,
    }),
    # Zones
    PowerTool("create_zone", _create_zone, {
        vol.Required("name"): cv.string,
        vol.Required("latitude"): cv.latitude,
        vol.Required("longitude"): cv.longitude,
        vol.Optional("radius"): vol.Coerce(float),
        vol.Optional("icon"): cv.icon,
        vol.Optional("passive"): cv.boolean,
    }),
    PowerTool("delete_zone", _delete_zone, {
        vol.Required("entity_id"): _ENTITY_LIST,
    }),
    # Persons
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
    }),
    # Users
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
        vol.Optional("url_path"): cv.string,
    }, has_response=True),
    PowerTool("restore_dashboard", _restore_dashboard, {
        vol.Optional("url_path"): cv.string,
        vol.Optional("backup"): cv.string,
    }, has_response=True),
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


def _admin_gated(hass: HomeAssistant, tool: PowerTool):
    """Wrap a handler with the same admin check HA applies to admin
    services (async_register_admin_service doesn't support response data,
    so the gate is replicated here)."""

    async def wrapped(call: ServiceCall):
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise UnknownUser(context=call.context)
            if not user.is_admin:
                raise Unauthorized(context=call.context)
        return await tool.handler(hass, call)

    return wrapped


@callback
def async_register_power_tools(hass: HomeAssistant) -> None:
    """Register every power-tool service under the bruh_claude domain."""
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
