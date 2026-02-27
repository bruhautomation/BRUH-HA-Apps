"""Config flow for BRUH Claude integration.

Supports multiple config entries so users can create several conversation
agents with different names and system prompts (personalities).

Flow paths:
  - First setup (no entries): just a name → creates agent + sensors with defaults
  - Add Service (entries exist): name + model + system prompt + timeout → new agent
  - Discovery: confirm → creates agent + sensors with defaults
"""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow

try:
    from homeassistant.components.hassio import HassioServiceInfo
except ImportError:
    HassioServiceInfo = None  # type: ignore[assignment,misc]

from .const import (
    AVAILABLE_MODELS,
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_SENSORS,
    CONF_MODEL,
    CONF_NAME,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_NAME,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)


class BruhClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BRUH Claude."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialise flow state."""
        self._discovery_info: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return BruhClaudeOptionsFlowHandler(config_entry)

    # ------------------------------------------------------------------
    # Entry point: route based on whether entries already exist
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Route to the appropriate setup step."""
        if self._async_current_entries():
            return await self.async_step_add_agent(user_input)
        return await self.async_step_first_setup(user_input)

    # ------------------------------------------------------------------
    # First setup: minimal — just name, auto-enable everything
    # ------------------------------------------------------------------

    async def async_step_first_setup(
        self, user_input: dict[str, Any] | None = None
    ):
        """Minimal first-time setup — just confirm and create defaults."""
        errors: dict[str, str] = {}

        if user_input is not None:
            shared_path = self.hass.config.path(".bruh_claude")
            dir_exists = await self.hass.async_add_executor_job(
                os.path.isdir, shared_path
            )
            if not dir_exists:
                errors["base"] = "addon_not_running"
            else:
                name = user_input.get(CONF_NAME, DEFAULT_NAME)
                unique_id = f"{DOMAIN}_{name.lower().replace(' ', '_')}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_ENABLE_CONVERSATION: True,
                        CONF_ENABLE_SENSORS: True,
                        CONF_MODEL: DEFAULT_MODEL,
                        CONF_SYSTEM_PROMPT: DEFAULT_SYSTEM_PROMPT,
                        CONF_TIMEOUT: DEFAULT_TIMEOUT,
                    },
                )

        return self.async_show_form(
            step_id="first_setup",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Add agent: full personality settings for additional agents
    # ------------------------------------------------------------------

    async def async_step_add_agent(
        self, user_input: dict[str, Any] | None = None
    ):
        """Add an additional conversation agent with a custom personality."""
        errors: dict[str, str] = {}

        if user_input is not None:
            shared_path = self.hass.config.path(".bruh_claude")
            dir_exists = await self.hass.async_add_executor_job(
                os.path.isdir, shared_path
            )
            if not dir_exists:
                errors["base"] = "addon_not_running"
            else:
                name = user_input.get(CONF_NAME, "Claude Agent")
                unique_id = f"{DOMAIN}_{name.lower().replace(' ', '_')}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_ENABLE_CONVERSATION: True,
                        CONF_ENABLE_SENSORS: False,
                        CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
                        CONF_SYSTEM_PROMPT: user_input.get(
                            CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT
                        ),
                        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    },
                )

        return self.async_show_form(
            step_id="add_agent",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(
                        CONF_MODEL, default=DEFAULT_MODEL
                    ): vol.In(AVAILABLE_MODELS),
                    vol.Optional(
                        CONF_SYSTEM_PROMPT, default=DEFAULT_SYSTEM_PROMPT
                    ): str,
                    vol.Optional(
                        CONF_TIMEOUT, default=DEFAULT_TIMEOUT
                    ): vol.All(int, vol.Range(min=10, max=600)),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Discovery flow (Supervisor auto-discovery)
    # ------------------------------------------------------------------

    async def async_step_hassio(
        self, discovery_info: Any
    ):
        """Handle discovery from the BRUH Claude Terminal app."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(f"{DOMAIN}_default")
        self._abort_if_unique_id_configured()

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
                    CONF_ENABLE_CONVERSATION: True,
                    CONF_ENABLE_SENSORS: True,
                    CONF_MODEL: DEFAULT_MODEL,
                    CONF_TIMEOUT: DEFAULT_TIMEOUT,
                    CONF_SYSTEM_PROMPT: DEFAULT_SYSTEM_PROMPT,
                },
            )

        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": "BRUH Claude Terminal"},
        )


class BruhClaudeOptionsFlowHandler(OptionsFlow):
    """Handle options for a BRUH Claude config entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}

        # Only show the sensor toggle if this is the sole entry
        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        is_only_entry = len(all_entries) <= 1

        if user_input is not None:
            enable_conv = user_input.get(
                CONF_ENABLE_CONVERSATION,
                current.get(CONF_ENABLE_CONVERSATION, True),
            )
            enable_sens = user_input.get(
                CONF_ENABLE_SENSORS,
                current.get(CONF_ENABLE_SENSORS, is_only_entry),
            )

            if is_only_entry and not enable_conv and not enable_sens:
                errors["base"] = "no_features"
            elif not is_only_entry and not enable_conv:
                errors["base"] = "no_features"
            else:
                data = {**user_input}
                if not is_only_entry:
                    data[CONF_ENABLE_SENSORS] = current.get(
                        CONF_ENABLE_SENSORS, False
                    )
                return self.async_create_entry(title="", data=data)

        schema_fields: dict = {
            vol.Optional(
                CONF_ENABLE_CONVERSATION,
                default=current.get(CONF_ENABLE_CONVERSATION, True),
            ): bool,
        }

        if is_only_entry:
            schema_fields[vol.Optional(
                CONF_ENABLE_SENSORS,
                default=current.get(CONF_ENABLE_SENSORS, True),
            )] = bool

        schema_fields[vol.Optional(
            CONF_MODEL,
            default=current.get(CONF_MODEL, DEFAULT_MODEL),
        )] = vol.In(AVAILABLE_MODELS)

        schema_fields[vol.Optional(
            CONF_SYSTEM_PROMPT,
            default=current.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
        )] = str

        schema_fields[vol.Optional(
            CONF_TIMEOUT,
            default=current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )] = vol.All(int, vol.Range(min=10, max=600))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )
