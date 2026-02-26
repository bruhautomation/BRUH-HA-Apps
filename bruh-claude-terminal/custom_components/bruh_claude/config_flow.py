"""Config flow for BRUH Claude integration.

Supports multiple config entries so users can create several conversation
agents with different names and system prompts (personalities).
"""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow

try:
    from homeassistant.components.hassio import HassioServiceInfo
except ImportError:
    HassioServiceInfo = None  # type: ignore[assignment,misc]

from .const import (
    CONF_NAME,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_NAME,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)


class BruhClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BRUH Claude."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle the initial step (manual setup).

        Each entry creates a separate conversation agent with its own
        name and optional system prompt, so users can have multiple
        personalities available in Settings > Voice Assistants.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check that the shared directory exists (app is running)
            shared_path = self.hass.config.path(".bruh_claude")
            dir_exists = await self.hass.async_add_executor_job(
                os.path.isdir, shared_path
            )
            if not dir_exists:
                errors["base"] = "addon_not_running"
            else:
                # Use the name as part of the unique_id to allow multiple entries
                name = user_input.get(CONF_NAME, DEFAULT_NAME)
                unique_id = f"{DOMAIN}_{name.lower().replace(' ', '_')}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(
                        CONF_SYSTEM_PROMPT, default=DEFAULT_SYSTEM_PROMPT
                    ): str,
                    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                        int, vol.Range(min=10, max=600)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: Any
    ):
        """Handle discovery from the BRUH Claude Terminal app.

        Triggered automatically by the Supervisor when the add-on posts
        to the /discovery API with service name 'bruh_claude'.
        """
        await self.async_set_unique_id(f"{DOMAIN}_default")
        self._abort_if_unique_id_configured()

        # Extract config from discovery info (supports both dict and HassioServiceInfo)
        if HassioServiceInfo is not None and isinstance(discovery_info, HassioServiceInfo):
            self._discovery_info = discovery_info.config
        elif isinstance(discovery_info, dict):
            self._discovery_info = discovery_info
        else:
            self._discovery_info = {}

        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Confirm the app discovery and set up the integration."""
        if user_input is not None:
            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_NAME: DEFAULT_NAME,
                    CONF_TIMEOUT: DEFAULT_TIMEOUT,
                    CONF_SYSTEM_PROMPT: DEFAULT_SYSTEM_PROMPT,
                },
            )

        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": "BRUH Claude Terminal"},
        )
