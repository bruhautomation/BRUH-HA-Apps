"""BRUH Task Manager integration: sensors over the add-on's state mirror.

There are no services. What to do about a runaway app is an automation's
decision, and Home Assistant already has the action for it
(`hassio.addon_restart`); a second way to restart an app would be a second
thing to keep in step with the Supervisor.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import TaskManagerCoordinator
from .fingerprint import record_loaded

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # What this Home Assistant loaded (fingerprint.py, taken at import), for the
    # add-on's run.sh: it says a restart is needed only when the code it deploys
    # differs from this.
    await hass.async_add_executor_job(record_loaded, hass.config.path(".bruh_task_manager/integration.json"))
    coordinator = TaskManagerCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
