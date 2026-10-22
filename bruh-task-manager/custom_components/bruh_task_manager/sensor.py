"""The machine's CPU and memory, and the app using the most CPU.

The numeric sensors go unavailable when the add-on has stopped measuring —
a CPU figure from an hour ago is not a CPU figure — and say why in the
coordinator's data, which the binary sensor (which never goes unavailable)
carries as its `reason`.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TaskManagerEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([
        MachineCpuSensor(coordinator, entry, "cpu"),
        MachineMemorySensor(coordinator, entry, "memory"),
        BusiestAppSensor(coordinator, entry, "busiest_app"),
        BusiestAppCpuSensor(coordinator, entry, "busiest_app_cpu"),
    ])


class _Measured(TaskManagerEntity, SensorEntity):
    @property
    def available(self) -> bool:
        return super().available and bool(self.data.get("available"))


class MachineCpuSensor(_Measured):
    _attr_name = "CPU"
    _attr_icon = "mdi:cpu-64-bit"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self):
        return (self.data.get("machine") or {}).get("cpu")

    @property
    def extra_state_attributes(self) -> dict:
        m = self.data.get("machine") or {}
        return {"cpus": m.get("cpus"), "load": m.get("load")}


class MachineMemorySensor(_Measured):
    _attr_name = "Memory used"
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self):
        return (self.data.get("machine") or {}).get("mem_percent")

    @property
    def extra_state_attributes(self) -> dict:
        m = self.data.get("machine") or {}
        return {"used_bytes": m.get("mem_used"), "total_bytes": m.get("mem_total")}


class BusiestAppSensor(_Measured):
    _attr_name = "Busiest app"
    _attr_icon = "mdi:speedometer"

    @property
    def native_value(self):
        busiest = self.data.get("busiest") or {}
        return busiest.get("name")

    @property
    def extra_state_attributes(self) -> dict:
        busiest = self.data.get("busiest") or {}
        return {
            "slug": busiest.get("slug"),
            "cpu_percent": busiest.get("cpu"),
            "memory_mb": busiest.get("memory_mb"),
            "top": self.data.get("top") or [],
            "level": self.data.get("level"),
        }


class BusiestAppCpuSensor(_Measured):
    _attr_name = "Busiest app CPU"
    _attr_icon = "mdi:chart-line"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self):
        return (self.data.get("busiest") or {}).get("cpu")
