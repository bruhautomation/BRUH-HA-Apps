"""Config flow — one entry, set up from the add-on's discovery tile."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN


class GardenRxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single instance: one add-on, one garden."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="GardenRX",
                data={CONF_HOST: user_input[CONF_HOST].strip(), CONF_PORT: int(user_input[CONF_PORT])},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default="local-gardenrx"): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
        )

    async def async_step_hassio(self, discovery_info) -> ConfigFlowResult:
        """The add-on announced itself, with the hostname Core reaches it by."""
        config = getattr(discovery_info, "config", None) or {}
        host = str(config.get(CONF_HOST) or "")
        port = int(config.get(CONF_PORT) or DEFAULT_PORT)
        await self.async_set_unique_id(DOMAIN)
        # An add-on reinstalled from another repository has a new hostname;
        # the entry follows it rather than calling the old one for ever.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        self._discovered = {CONF_HOST: host, CONF_PORT: port}
        self.context["title_placeholders"] = {"name": "GardenRX"}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="hassio_confirm")
        return self.async_create_entry(title="GardenRX", data=self._discovered)
