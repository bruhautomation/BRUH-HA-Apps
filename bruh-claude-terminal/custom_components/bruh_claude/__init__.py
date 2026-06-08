"""BRUH Claude integration for Home Assistant.

Provides:
- A conversation agent ("BRUH Claude") selectable in Settings > Voice Assistants
- Usage limit sensors for Anthropic account data
- bruh_claude.send_prompt          — send a one-shot prompt to Claude
- bruh_claude.run_task             — run a Claude task with optional notification
- bruh_claude.clear_conversation   — clear a persistent conversation session

Both conversation agent and sensors are independently toggleable per config entry.
"""

from __future__ import annotations

import json
import logging
import os

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir

try:
    from homeassistant.core import SupportsResponse
except ImportError:
    SupportsResponse = None  # type: ignore[assignment,misc]

from .bridge import ClaudeBridge
from .const import (
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_SENSORS,
    CONF_MODEL,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Capture the manifest version at import time so we know which version of the
# code is actually loaded in memory.  The on-disk manifest.json may be
# overwritten by the add-on before _check_restart_required runs, so reading
# it later would give the *new* version instead of the *running* version.
_LOADED_VERSION: str = "unknown"
try:
    with open(os.path.join(os.path.dirname(__file__), "manifest.json")) as _fh:
        _LOADED_VERSION = json.load(_fh).get("version", "unknown")
except (OSError, json.JSONDecodeError):
    pass

SEND_PROMPT_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
    }
)

RUN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("notify", default=False): bool,
        vol.Optional("notify_entity"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
    }
)

CLEAR_CONVERSATION_SCHEMA = vol.Schema(
    {
        vol.Optional("conversation_id"): str,
    }
)


def _get_platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the list of platforms to set up for this config entry."""
    opts = {**entry.data, **entry.options}
    platforms: list[Platform] = []
    if opts.get(CONF_ENABLE_CONVERSATION, True):
        platforms.append(Platform.CONVERSATION)
    if opts.get(CONF_ENABLE_SENSORS, True):
        platforms.append(Platform.SENSOR)
    return platforms


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries to the current version."""
    if config_entry.version < 2:
        _LOGGER.debug("Migrating config entry %s from version %s to 2",
                       config_entry.entry_id, config_entry.version)
        new_data = {**config_entry.data}
        new_data.setdefault(CONF_ENABLE_CONVERSATION, True)
        new_data.setdefault(CONF_ENABLE_SENSORS, True)
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
    if config_entry.version < 3:
        _LOGGER.debug("Migrating config entry %s from version 2 to 3",
                       config_entry.entry_id)
        new_data = {**config_entry.data}
        new_data.setdefault(CONF_MODEL, DEFAULT_MODEL)
        new_data.setdefault(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT)
        new_data.setdefault(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=3
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BRUH Claude from a config entry."""
    opts = {**entry.data, **entry.options}
    timeout = opts.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    bridge = ClaudeBridge(hass, timeout=timeout)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = bridge

    # Only forward platforms the user has enabled
    platforms = _get_platforms(entry)
    hass.data[DOMAIN][f"{entry.entry_id}_platforms"] = platforms

    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # Register services (only once, guarded by domain key)
    if not hass.services.has_service(DOMAIN, "send_prompt"):
        _register_services(hass)

    # Check if the add-on deployed newer integration files that need a restart
    await _check_restart_required(hass)

    # Reload the entry when the user changes options (system prompt, timeout, etc.)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Listen for the add-on signalling that new files were deployed while HA is
    # running. Wrap in async_on_unload so the listener is removed when the entry
    # unloads/reloads — otherwise listeners accumulate on every options change.
    async def _on_restart_required(event: Event) -> None:
        await _check_restart_required(hass)

    entry.async_on_unload(
        hass.bus.async_listen("bruh_claude_restart_required", _on_restart_required)
    )

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = hass.data.get(DOMAIN, {}).get(
        f"{entry.entry_id}_platforms",
        _get_platforms(entry),
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_platforms", None)

        # Remaining configured entries (bridge instances), excluding the
        # metadata keys (_sensors_added, _sensors_entry, <id>_platforms).
        remaining = [
            eid for eid in hass.data[DOMAIN]
            if not eid.startswith("_") and not eid.endswith("_platforms")
        ]

        # If this entry owned the account-wide sensors, clear the flag so
        # another entry can recreate them on its next reload.
        if hass.data[DOMAIN].get("_sensors_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_sensors_entry", None)
            hass.data[DOMAIN].pop("_sensors_added", None)

            # Auto-migrate: reload another entry so it picks up sensor duties.
            if remaining:
                hass.async_create_task(
                    hass.config_entries.async_reload(remaining[0])
                )

        # Last entry removed — tear down the domain services so they don't
        # linger and raise "not configured" if called with no bridge.
        if not remaining:
            for service in ("send_prompt", "run_task", "clear_conversation"):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _check_restart_required(hass: HomeAssistant) -> None:
    """Check if the add-on deployed newer files and create/clear a repair issue."""
    marker_path = hass.config.path(".bruh_claude", "restart_required")
    marker = await hass.async_add_executor_job(_read_marker, marker_path)

    if marker is None:
        # No marker file — nothing to do, clear any stale repair
        ir.async_delete_issue(hass, DOMAIN, "restart_required")
        return

    required_version = marker.get("required_version", "")

    # Use the version captured at import time — NOT the on-disk manifest,
    # which the add-on may have already overwritten with the newer version.
    loaded_version = _LOADED_VERSION

    if required_version and required_version == loaded_version:
        # The restart already happened — we're running the new version
        await hass.async_add_executor_job(_remove_file, marker_path)
        ir.async_delete_issue(hass, DOMAIN, "restart_required")
        # Also dismiss any leftover persistent notification from older versions
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": "bruh_claude_restart_needed"},
        )
        return

    # Files on disk are newer than what's loaded — prompt user to restart
    ir.async_create_issue(
        hass,
        DOMAIN,
        "restart_required",
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="restart_required",
        translation_placeholders={"version": required_version},
    )

    # Also create a persistent notification as a visible fallback in case
    # the user doesn't check Settings > System > Repairs.
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"BRUH Claude: Restart Required (v{required_version})",
                "message": (
                    f"The BRUH Claude integration has been updated to v{required_version}. "
                    "Please restart Home Assistant to load the new version.\n\n"
                    "Go to **Settings > System > Restart**, or check "
                    "**Settings > System > Repairs** to fix automatically."
                ),
                "notification_id": "bruh_claude_restart_needed",
            },
        )
    except Exception:
        _LOGGER.debug("Could not create persistent notification for restart")


def _read_marker(path: str) -> dict | None:
    """Read the restart marker JSON file, return None if missing."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _read_json(path: str) -> dict | None:
    """Read a JSON file, return None on error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _remove_file(path: str) -> None:
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass


def _get_bridge(hass: HomeAssistant) -> ClaudeBridge:
    """Return the first available bridge instance."""
    domain_data = hass.data.get(DOMAIN, {})
    for key, value in domain_data.items():
        if isinstance(value, ClaudeBridge):
            return value
    raise ValueError("BRUH Claude integration is not configured")


def _register_services(hass: HomeAssistant) -> None:
    """Register bruh_claude services."""

    async def handle_send_prompt(call: ServiceCall):
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        timeout = call.data.get("timeout")

        try:
            result = await bridge.async_send_conversation(
                text=prompt, timeout=timeout
            )
        except TimeoutError:
            result = "Claude did not respond in time."

        return {"response": result}

    async def handle_run_task(call: ServiceCall):
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        notify = call.data.get("notify", False)
        notify_entity = call.data.get("notify_entity")
        timeout = call.data.get("timeout")

        try:
            result = await bridge.async_send_task(
                prompt=prompt,
                notify=notify,
                notify_entity=notify_entity,
                timeout=timeout,
            )
        except TimeoutError:
            result = "Claude task did not complete in time."

        return {"response": result}

    async def handle_clear_conversation(call: ServiceCall):
        bridge = _get_bridge(hass)
        conversation_id = call.data.get("conversation_id")
        await bridge.async_clear_conversation(conversation_id)
        _LOGGER.info(
            "Cleared conversation session: %s",
            conversation_id or "ALL",
        )

    extra_kwargs: dict = {}
    if SupportsResponse is not None:
        extra_kwargs["supports_response"] = SupportsResponse.OPTIONAL

    hass.services.async_register(
        DOMAIN,
        "send_prompt",
        handle_send_prompt,
        schema=SEND_PROMPT_SCHEMA,
        **extra_kwargs,
    )

    hass.services.async_register(
        DOMAIN,
        "run_task",
        handle_run_task,
        schema=RUN_TASK_SCHEMA,
        **extra_kwargs,
    )

    hass.services.async_register(
        DOMAIN,
        "clear_conversation",
        handle_clear_conversation,
        schema=CLEAR_CONVERSATION_SCHEMA,
    )
