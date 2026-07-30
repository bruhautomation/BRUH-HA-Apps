"""Config flow for brAIn integration.

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

# HassioServiceInfo moved to homeassistant.helpers.service_info.hassio in
# HA 2024.12; the old re-export under homeassistant.components.hassio was
# removed entirely in 2026.x. Try new location first, then old, then None
# (plain-dict discovery payloads still work without it).
try:
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo
except ImportError:
    try:
        from homeassistant.components.hassio import HassioServiceInfo
    except ImportError:
        HassioServiceInfo = None  # type: ignore[assignment,misc]

from .const import (
    AVAILABLE_MODELS,
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_SENSORS,
    CONF_ENTRY_TYPE,
    CONF_INSIGHT_DAILY_AT,
    CONF_INSIGHT_INTERVAL,
    CONF_INSIGHT_NOTIFY,
    CONF_INSIGHT_PROMPT,
    CONF_INSIGHT_TEMPLATE,
    CONF_DENIED_SERVICES,
    CONF_MODEL,
    CONF_NAME,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_INSIGHT_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_NAME,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    ENTRY_TYPE_INSIGHT,
)
from .insight_format import INSIGHT_TEMPLATES

try:
    from homeassistant.helpers.selector import (
        SelectOptionDict,
        SelectSelector,
        SelectSelectorConfig,
        SelectSelectorMode,
        TextSelector,
        TextSelectorConfig,
    )

    # Inline labels render regardless of translation loading and double as
    # the template "preview" at a glance.
    TEMPLATE_LABELS = {
        "daily_briefing": "Daily briefing — what's notable right now (anomalies, batteries, weather that matters)",
        "anomaly_watch": "Anomaly watch — only problems; says 'All quiet.' otherwise",
        "battery_maintenance": "Battery & maintenance — what to replace now / soon",
        "camera_check": "Camera check — looks at every camera, reports anything notable",
        "custom": "Custom — use my prompt below",
    }

    def _select(options: dict[str, str]):
        return SelectSelector(SelectSelectorConfig(
            options=[SelectOptionDict(value=v, label=label) for v, label in options.items()],
            mode=SelectSelectorMode.DROPDOWN,
        ))

    TEMPLATE_FIELD = _select(TEMPLATE_LABELS)
    MODEL_FIELD = _select(AVAILABLE_MODELS)
    MULTILINE_FIELD = TextSelector(TextSelectorConfig(multiline=True))
    _HAS_SELECTORS = True
except ImportError:  # very old HA — plain widgets still work
    TEMPLATE_FIELD = vol.In(list(INSIGHT_TEMPLATES) + ["custom"])
    MODEL_FIELD = vol.In(AVAILABLE_MODELS)
    MULTILINE_FIELD = str
    _HAS_SELECTORS = False

# Common high-risk service patterns offered as one-click deny options. Users
# can also type any "domain.service" or whole-domain "domain.*" pattern, and
# every service domain on the system is offered as "domain.*" too.
CURATED_DENY_PATTERNS = [
    "homeassistant.restart",
    "homeassistant.stop",
    "hassio.host_reboot",
    "hassio.host_shutdown",
    "update.install",
    "recorder.purge",
    "lock.unlock",
    "lock.open",
    "alarm_control_panel.alarm_disarm",
    "cover.open_cover",
    "automation.turn_off",
    "script.*",
    "shell_command.*",
    "backup.create",
]


def denied_services_field(hass, default):
    """Multi-select of service patterns to forbid for this agent.

    Seeded with curated high-risk patterns plus every live service domain
    as "domain.*"; accepts custom typed patterns. Per agent — enforced in
    the MCP server's call_service chokepoint, so it covers every tool.
    """
    default = default or []
    if not _HAS_SELECTORS:
        # Old HA: free-text comma list, normalized by the caller.
        return vol.Optional(CONF_DENIED_SERVICES, default=default), str

    options = list(CURATED_DENY_PATTERNS)
    try:
        for domain in sorted(hass.services.async_services()):
            pat = f"{domain}.*"
            if pat not in options:
                options.append(pat)
    except Exception:  # noqa: BLE001 — registry unavailable: curated list only
        pass
    # Keep any already-selected custom values present as options
    for v in default:
        if v not in options:
            options.append(v)

    selector = SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=o, label=o) for o in options],
        multiple=True,
        custom_value=True,
        mode=SelectSelectorMode.DROPDOWN,
        sort=True,
    ))
    return vol.Optional(CONF_DENIED_SERVICES, default=default), selector


def _valid_daily_at(value: str) -> bool:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, TypeError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


class BruhClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for brAIn."""

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
            return self.async_show_menu(
                step_id="user",
                menu_options={
                    "add_agent": "Conversation agent — a voice personality for Assist",
                    "add_insight": "Insight job — a scheduled Claude report on a sensor",
                },
            )
        return await self.async_step_first_setup(user_input)

    # ------------------------------------------------------------------
    # Add insight job: a scheduled Claude run whose markdown lands on a
    # sensor (dashboard card YAML is provided on the sensor itself).
    # ------------------------------------------------------------------

    async def async_step_add_insight(
        self, user_input: dict[str, Any] | None = None
    ):
        """Create a scheduled insight job."""
        errors: dict[str, str] = {}

        if user_input is not None:
            shared_path = self.hass.config.path(".brain")
            dir_exists = await self.hass.async_add_executor_job(
                os.path.isdir, shared_path
            )
            daily_at = (user_input.get(CONF_INSIGHT_DAILY_AT) or "").strip()
            if not dir_exists:
                errors["base"] = "addon_not_running"
            elif daily_at and not _valid_daily_at(daily_at):
                errors["base"] = "invalid_daily_at"
            else:
                name = user_input[CONF_NAME]
                unique_id = f"{DOMAIN}_insight_{name.lower().replace(' ', '_')}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_INSIGHT,
                        CONF_NAME: name,
                        CONF_ENABLE_CONVERSATION: False,
                        CONF_ENABLE_SENSORS: False,
                        CONF_INSIGHT_TEMPLATE: user_input.get(
                            CONF_INSIGHT_TEMPLATE, "daily_briefing"
                        ),
                        CONF_INSIGHT_PROMPT: user_input.get(CONF_INSIGHT_PROMPT, ""),
                        CONF_INSIGHT_INTERVAL: user_input.get(CONF_INSIGHT_INTERVAL, 0),
                        CONF_INSIGHT_DAILY_AT: daily_at,
                        CONF_INSIGHT_NOTIFY: user_input.get(CONF_INSIGHT_NOTIFY, ""),
                        CONF_MODEL: user_input.get(CONF_MODEL, "default"),
                        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, DEFAULT_INSIGHT_TIMEOUT),
                    },
                )

        return self.async_show_form(
            step_id="add_insight",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(
                        CONF_INSIGHT_TEMPLATE, default="daily_briefing"
                    ): TEMPLATE_FIELD,
                    vol.Optional(CONF_INSIGHT_PROMPT, default=""): MULTILINE_FIELD,
                    vol.Optional(CONF_INSIGHT_INTERVAL, default=0): vol.All(
                        int, vol.Range(min=0, max=1440)
                    ),
                    vol.Optional(CONF_INSIGHT_DAILY_AT, default=""): str,
                    vol.Optional(CONF_INSIGHT_NOTIFY, default=""): str,
                    vol.Optional(CONF_MODEL, default="default"): MODEL_FIELD,
                    vol.Optional(
                        CONF_TIMEOUT, default=DEFAULT_INSIGHT_TIMEOUT
                    ): vol.All(int, vol.Range(min=30, max=600)),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # First setup: minimal — just name, auto-enable everything
    # ------------------------------------------------------------------

    async def async_step_first_setup(
        self, user_input: dict[str, Any] | None = None
    ):
        """Minimal first-time setup — just confirm and create defaults."""
        errors: dict[str, str] = {}

        if user_input is not None:
            shared_path = self.hass.config.path(".brain")
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
            shared_path = self.hass.config.path(".brain")
            dir_exists = await self.hass.async_add_executor_job(
                os.path.isdir, shared_path
            )
            if not dir_exists:
                errors["base"] = "addon_not_running"
            else:
                name = user_input.get(CONF_NAME, "brAIn Agent")
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
                        CONF_DENIED_SERVICES: user_input.get(CONF_DENIED_SERVICES, []),
                        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    },
                )

        deny_key, deny_field = denied_services_field(self.hass, [])
        return self.async_show_form(
            step_id="add_agent",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(
                        CONF_MODEL, default=DEFAULT_MODEL
                    ): MODEL_FIELD,
                    vol.Optional(
                        CONF_SYSTEM_PROMPT, default=DEFAULT_SYSTEM_PROMPT
                    ): MULTILINE_FIELD,
                    deny_key: deny_field,
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
        """Handle discovery from the brAIn app."""
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
            description_placeholders={"addon": "brAIn"},
        )


class BruhClaudeOptionsFlowHandler(OptionsFlow):
    """Handle options for a brAIn config entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        errors: dict[str, str] = {}
        current = {**self._config_entry.data, **self._config_entry.options}

        if self._config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INSIGHT:
            return await self.async_step_insight(user_input)

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
        )] = MODEL_FIELD

        schema_fields[vol.Optional(
            CONF_SYSTEM_PROMPT,
            default=current.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
        )] = MULTILINE_FIELD

        deny_key, deny_field = denied_services_field(
            self.hass, current.get(CONF_DENIED_SERVICES, [])
        )
        schema_fields[deny_key] = deny_field

        schema_fields[vol.Optional(
            CONF_TIMEOUT,
            default=current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )] = vol.All(int, vol.Range(min=10, max=600))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )


    async def async_step_insight(
        self, user_input: dict[str, Any] | None = None
    ):
        """Options for an insight job entry.

        Must be a real step named after the form's step_id — HA routes the
        form submission to async_step_<step_id>.
        """
        current = {**self._config_entry.data, **self._config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            daily_at = (user_input.get(CONF_INSIGHT_DAILY_AT) or "").strip()
            if daily_at and not _valid_daily_at(daily_at):
                errors["base"] = "invalid_daily_at"
            else:
                return self.async_create_entry(title="", data=user_input)

        # Preview: pre-fill the prompt with the selected template's full text
        # so the user can read exactly what runs (and tweak it — saving
        # stores the text as this job's prompt).
        default_prompt = current.get(CONF_INSIGHT_PROMPT, "")
        if not default_prompt:
            default_prompt = INSIGHT_TEMPLATES.get(
                current.get(CONF_INSIGHT_TEMPLATE, "daily_briefing"), ""
            )

        return self.async_show_form(
            step_id="insight",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INSIGHT_TEMPLATE,
                        default=current.get(CONF_INSIGHT_TEMPLATE, "daily_briefing"),
                    ): TEMPLATE_FIELD,
                    vol.Optional(
                        CONF_INSIGHT_PROMPT,
                        default=default_prompt,
                    ): MULTILINE_FIELD,
                    vol.Optional(
                        CONF_INSIGHT_INTERVAL,
                        default=current.get(CONF_INSIGHT_INTERVAL, 0),
                    ): vol.All(int, vol.Range(min=0, max=1440)),
                    vol.Optional(
                        CONF_INSIGHT_DAILY_AT,
                        default=current.get(CONF_INSIGHT_DAILY_AT, ""),
                    ): str,
                    vol.Optional(
                        CONF_INSIGHT_NOTIFY,
                        default=current.get(CONF_INSIGHT_NOTIFY, ""),
                    ): str,
                    vol.Optional(
                        CONF_MODEL, default=current.get(CONF_MODEL, "default")
                    ): MODEL_FIELD,
                    vol.Optional(
                        CONF_TIMEOUT,
                        default=current.get(CONF_TIMEOUT, DEFAULT_INSIGHT_TIMEOUT),
                    ): vol.All(int, vol.Range(min=30, max=600)),
                }
            ),
            errors=errors,
        )
