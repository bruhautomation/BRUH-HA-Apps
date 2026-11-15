"""Tell the owner when an appliance's entity ids come from an older name, and fix them on request.

Home Assistant builds an entity id once, from the device's name at that time,
and never changes it; the friendly name follows the device's current name. An
appliance renamed in the Breville app therefore ends up with ids that no longer
look like its name. Nothing is renamed on its own (automations use the ids): a
Repairs notice offers a fix that renames them when the owner confirms
(repairs.py), and says which automations to check. New entities are named from
the device's current name, so they already match.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import device_for


def issue_id(serial: str) -> str:
    return f"entity_ids_{serial}"


def _stale(entities, device, prefix: str) -> list[er.RegistryEntry]:
    return [
        entity
        for entity in er.async_entries_for_device(entities, device.id)
        if entity.platform == DOMAIN
        and not entity.entity_id.split(".", 1)[1].startswith(prefix)
    ]


@callback
def async_rename_entity_ids(hass: HomeAssistant, serial: str) -> list[tuple[str, str]]:
    """Give an appliance's entities ids from its current name. Returns (old, new) pairs.

    The new id is the device's name and the entity's own name, as Home Assistant
    builds one for a new entity. An id already taken is left as it is.
    """
    entities = er.async_get(hass)
    device = device_for(hass, serial)
    if device is None:
        return []
    name = device.name_by_user or device.name
    if not name:
        return []
    prefix = slugify(name)
    renamed: list[tuple[str, str]] = []
    for entity in _stale(entities, device, prefix):
        own = entity.original_name or entity.translation_key or entity.unique_id.removeprefix(f"{serial}_")
        wanted = f"{entity.domain}.{slugify(f'{name} {own}')}"
        if wanted == entity.entity_id or entities.async_get(wanted) is not None:
            continue
        entities.async_update_entity(entity.entity_id, new_entity_id=wanted)
        renamed.append((entity.entity_id, wanted))
    return renamed


@callback
def async_check_entity_ids(hass: HomeAssistant, entry_id: str) -> None:
    """Raise or clear one Repairs notice per device of the entry."""
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry_id):
        serial = next((ident for domain, ident in device.identifiers if domain == DOMAIN), None)
        name = device.name_by_user or device.name
        if serial is None or not name:
            continue
        prefix = slugify(name)
        if _stale(entities, device, prefix):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id(serial),
                is_fixable=True,
                data={"serial": serial},
                severity=ir.IssueSeverity.WARNING,
                translation_key="entity_ids_old_name",
                translation_placeholders={"name": name},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id(serial))
