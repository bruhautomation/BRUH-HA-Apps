"""Config flow for BRUH Claude integration."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow

from .const import DEFAULT_TIMEOUT, DOMAIN


class BruhClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BRUH Claude."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle the initial step (manual setup)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check that the shared directory exists (add-on is running)
            shared_path = self.hass.config.path(".bruh_claude")
            if not os.path.isdir(shared_path):
                errors["base"] = "addon_not_running"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="BRUH Claude",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("timeout", default=DEFAULT_TIMEOUT): vol.All(
                        int, vol.Range(min=10, max=600)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: dict[str, Any]
    ):
        """Handle discovery from the BRUH Claude Terminal add-on."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Store discovery info for the confirm step
        self._discovery_info = discovery_info
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Confirm the add-on discovery and set up the integration."""
        if user_input is not None:
            return self.async_create_entry(
                title="BRUH Claude",
                data={"timeout": DEFAULT_TIMEOUT},
            )

        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": "BRUH Claude Terminal"},
        )
