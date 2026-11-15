"""Tell the owner when an appliance's entity ids come from an older name, and fix them on request.

Home Assistant builds an entity id once, from the device's name at that time,
and never changes it; the friendly name follows the device's current name. An
appliance renamed in the Breville app therefore ends up with ids that no longer
look like its name. Nothing is renamed on its own (automations use the ids): a
Repairs issue offers a fix that renames them when the owner confirms
(repairs.py), with Home Assistant's own rule for a new id. New entities are
named from the device's current name, so they already match.
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


def _stale(entities: er.EntityRegistry, device: dr.DeviceEntry) -> list[er.RegistryEntry]:
    """The device's entities whose ids do not start with its current name."""
    name = device.name_by_user or device.name
    if not name:
        return []
    prefix = slugify(name)
    return [
        entity
        for entity in er.async_entries_for_device(entities, device.id)
        if entity.platform == DOMAIN
        and not entity.entity_id.split(".", 1)[1].startswith(prefix)
    ]


@callback
def async_rename_entity_ids(hass: HomeAssistant, serial: str) -> list[tuple[str, str]]:
    """Give an appliance's entities ids from its current name. Returns (old, new) pairs.

    The new id is the one Home Assistant would give the entity now (its own
    "Recreate entity IDs"), so a taken id gets Home Assistant's usual suffix.
    """
    entities = er.async_get(hass)
    device = device_for(hass, serial)
    if device is None:
        return []
    renamed: list[tuple[str, str]] = []
    reserved: set[str] = set()
    for entity in _stale(entities, device):
        wanted = entities.async_regenerate_entity_id(entity, reserved_entity_ids=reserved)
        reserved.add(wanted)
        if wanted == entity.entity_id:
            continue
        entities.async_update_entity(entity.entity_id, new_entity_id=wanted)
        renamed.append((entity.entity_id, wanted))
    return renamed


@callback
def async_check_entity_ids(hass: HomeAssistant, entry_id: str) -> None:
    """Raise or clear one Repairs issue per appliance of the entry."""
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry_id):
        if device.entry_type is dr.DeviceEntryType.SERVICE:
            continue  # the account, not an appliance
        serial = next((ident for domain, ident in device.identifiers if domain == DOMAIN), None)
        name = device.name_by_user or device.name
        if serial is None or not name:
            continue
        if _stale(entities, device):
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
