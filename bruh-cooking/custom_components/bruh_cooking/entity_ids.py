"""Tell the owner when an appliance's entity ids come from an older name.

Home Assistant builds an entity id once, from the device's name at that time,
and never changes it; the friendly name follows the device's current name. An
appliance renamed in the Breville app therefore ends up with ids that no longer
look like its name. Nothing is renamed here (automations use the ids): a Repairs
notice points to Home Assistant's own "Recreate entity IDs" on the device page.
New entities are named from the device's current name, so they already match.
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


def issue_id(serial: str) -> str:
    return f"entity_ids_{serial}"


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
        stale = any(
            not entity.entity_id.split(".", 1)[1].startswith(prefix)
            for entity in er.async_entries_for_device(entities, device.id)
            if entity.platform == DOMAIN
        )
        if stale:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id(serial),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="entity_ids_old_name",
                translation_placeholders={"name": name},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id(serial))
