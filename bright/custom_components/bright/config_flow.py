"""Config flow for BRight.

The add-on runs on the same HA host, so there are no credentials — this
flow is a "confirm setup" + single-instance guarantee, plus support for
Supervisor service discovery.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import DOMAIN


class BrightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="BRight", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """Discovery from the Supervisor."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="BRight", data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))
