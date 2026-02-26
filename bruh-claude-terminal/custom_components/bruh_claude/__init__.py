"""BRUH Claude integration for Home Assistant.

Provides:
- A conversation agent ("BRUH Claude") selectable in Settings > Voice Assistants
- bruh_claude.send_prompt  — send a one-shot prompt to Claude
- bruh_claude.run_task     — run a Claude task with optional notification
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

try:
    from homeassistant.core import SupportsResponse
except ImportError:
    SupportsResponse = None  # type: ignore[assignment,misc]

from .bridge import ClaudeBridge
from .const import CONF_TIMEOUT, DEFAULT_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BRUH Claude from a config entry."""
    timeout = entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    bridge = ClaudeBridge(hass, timeout=timeout)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = bridge

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, guarded by domain key)
    if not hass.services.has_service(DOMAIN, "send_prompt"):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _get_bridge(hass: HomeAssistant) -> ClaudeBridge:
    """Return the first available bridge instance."""
    bridges = hass.data.get(DOMAIN, {})
    if not bridges:
        raise ValueError("BRUH Claude integration is not configured")
    return next(iter(bridges.values()))


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
