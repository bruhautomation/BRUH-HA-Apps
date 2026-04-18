"""Config flow for BRUH Minecraft.

The add-on runs the Minecraft server on the same HA host, so we don't need
any credentials. This flow is a simple "confirm setup" + single-instance
guarantee, plus support for Supervisor service discovery.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import DOMAIN


class BruhMinecraftConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="BRUH Minecraft", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "server_dir": "/config/minecraft",
                "backup_dir": "/config/minecraft-backups",
            },
        )

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """Discovery from the Supervisor."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="BRUH Minecraft", data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))
