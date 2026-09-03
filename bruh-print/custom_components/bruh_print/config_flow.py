"""Config flow — one entry, set up from the add-on's discovery tile."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class BruhPrintConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance flow: there is one add-on and one shared folder."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="BRUH Print", data={})

    async def async_step_hassio(self, discovery_info) -> ConfigFlowResult:
        """The add-on announced itself to the Supervisor."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": "BRUH Print"}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="hassio_confirm")
        return self.async_create_entry(title="BRUH Print", data={})
