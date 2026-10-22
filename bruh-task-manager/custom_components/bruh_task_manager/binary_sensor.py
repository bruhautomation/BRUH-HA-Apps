"""Is any app running away?

On when an app has stayed above the add-on's runaway threshold for the
runaway time. It never goes unavailable — Home Assistant hides an
unavailable entity's attributes, and the reason would go with them — and it
is UNKNOWN, not off, when the add-on has stopped measuring: "I could not
look" is not "nothing is running hot".

An automation acting on it restarts with Home Assistant's own action:

    action: hassio.addon_restart
    data:
      addon: "{{ state_attr('binary_sensor.bruh_task_manager_runaway_app', 'apps')[0].slug }}"
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TaskManagerEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([RunawayBinarySensor(coordinator, entry, "runaway_app")])


class RunawayBinarySensor(TaskManagerEntity, BinarySensorEntity):
    _attr_name = "Runaway app"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        if not self.data.get("available"):
            return None
        return bool((self.data.get("runaway") or {}).get("apps"))

    @property
    def extra_state_attributes(self) -> dict:
        runaway = self.data.get("runaway") or {}
        apps = [a for a in runaway.get("apps") or [] if isinstance(a, dict)]
        return {
            "apps": [{"name": a.get("name"), "slug": a.get("slug"),
                      "cpu_percent": a.get("cpu"), "minutes": a.get("minutes")}
                     for a in apps],
            "threshold_percent": runaway.get("threshold"),
            "minutes": runaway.get("minutes"),
            "reason": "" if self.data.get("available") else self.data.get("reason"),
        }
