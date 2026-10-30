"""BRUH Cooking: Breville+ and Sage cooking appliances, driven by Home Assistant and brAIn."""

from __future__ import annotations

from datetime import timedelta

import voluptuous as vol

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .api import BRANDS, BrevilleClient, Tokens
from .appliance import CONVECTION_ALL, OVEN_MODES
from .const import (
    ATTR_AUTO_START_TIMER,
    ATTR_CONVECTION,
    ATTR_DURATION,
    ATTR_KEEP_WARM,
    ATTR_LEVEL,
    ATTR_MODE,
    ATTR_TEMPERATURE,
    BRAND_BREVILLE,
    CONF_BRAND,
    DOMAIN,
    SERVICE_START_COOK,
)
from .coordinator import BrevilleCoordinator
from .fingerprint import record_loaded
from .frontend import (
    async_add_entry_panel,
    async_follow_bundle,
    async_forget_entry_panel,
    async_remove_entry_panel,
    async_setup_frontend,
)
from .services import async_register_services
from .panel_api import (
    async_panel_entry_removed,
    async_panel_entry_set_up,
    async_panel_entry_unloaded,
    async_remove_presets,
    async_setup_panel_api,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

START_COOK_SCHEMA = {
    vol.Optional(ATTR_TEMPERATURE): vol.Coerce(float),
    vol.Optional(ATTR_DURATION): cv.positive_time_period,
    vol.Optional(ATTR_MODE): vol.In(list(OVEN_MODES)),
    vol.Optional(ATTR_CONVECTION): vol.In(list(CONVECTION_ALL)),
    vol.Optional(ATTR_LEVEL): vol.In(["low", "medium", "high"]),
    vol.Optional(ATTR_AUTO_START_TIMER): cv.boolean,
    vol.Optional(ATTR_KEEP_WARM): cv.boolean,
}

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

BrevilleConfigEntry = ConfigEntry[BrevilleCoordinator]

# Where this Home Assistant records the code it loaded (fingerprint.py), for
# the add-on's run.sh: it says a restart is needed only when the code it
# deploys differs from this.
LOADED_FILE = ".bruh_cooking/integration.json"
# How often the sidebar panel's URL is checked against the bundle on disk.
BUNDLE_FOLLOW = timedelta(seconds=60)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services, the sidebar panel and its websocket API."""
    await hass.async_add_executor_job(record_loaded, hass.config.path(LOADED_FILE))
    _register_services(hass)
    async_setup_frontend(hass)
    async_setup_panel_api(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    """start_cook (targets an appliance's Cook switch), and the ones brAIn calls by name."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_START_COOK,
        entity_domain=SWITCH_DOMAIN,
        schema=START_COOK_SCHEMA,
        func="async_start_cook_service",
    )
    async_register_services(hass)


async def async_setup_entry(hass: HomeAssistant, entry: BrevilleConfigEntry) -> bool:
    """Set up Breville+ Cooking from a config entry."""

    def save_tokens(tokens: Tokens) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **tokens.as_dict()}
        )

    client = BrevilleClient(
        async_get_clientsession(hass),
        Tokens.from_dict(entry.data),
        endpoints=BRANDS[entry.data.get(CONF_BRAND, BRAND_BREVILLE)],
        on_tokens_updated=save_tokens,
    )
    coordinator = BrevilleCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_websocket()
    # The sidebar panel, best effort: every entity works without it.
    await async_add_entry_panel(hass, entry)

    async def _follow(_now) -> None:
        await async_follow_bundle(hass)

    entry.async_on_unload(
        async_track_time_interval(hass, _follow, BUNDLE_FOLLOW, cancel_on_shutdown=True)
    )
    async_panel_entry_set_up(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BrevilleConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    # Usually to reload: the panel keeps the appliances, unavailable, until they're back.
    async_panel_entry_unloaded(hass, entry)
    await async_remove_entry_panel(hass, entry)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BrevilleConfigEntry) -> None:
    """Let the panel forget a removed entry, and the presets go with the last one."""
    async_panel_entry_removed(hass, entry.entry_id)
    await async_forget_entry_panel(hass, entry.entry_id)
    if not any(
        other.entry_id != entry.entry_id for other in hass.config_entries.async_entries(DOMAIN)
    ):
        await async_remove_presets(hass)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: BrevilleConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a device once its appliance has left the account."""
    coordinator = entry.runtime_data
    serials = [ident for domain, ident in device.identifiers if domain == DOMAIN]
    if any(
        (appliance := coordinator.appliances.get(serial)) is not None and appliance.on_account
        for serial in serials
    ):
        return False
    for serial in serials:
        await coordinator.async_remove_appliance(serial)
    return True
