"""Notify platform for BRUH Minecraft.

Exposes a `notify.bruh_minecraft` entity so Home Assistant automations can
broadcast in-game messages with the same `notify.send_message` service they
use for phone pushes, Slack, etc.

Delegates to the add-on via the file-IPC bridge — which in turn issues
`/tellraw` (for structured title + message) or `/say` (plain broadcast).
"""
from __future__ import annotations

import json
import logging

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bridge import send_request
from .const import DOMAIN
from .coordinator import BruhMinecraftCoordinator
from .entity import BruhMinecraftEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BruhMinecraftCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BruhMinecraftNotify(coordinator)])


class BruhMinecraftNotify(BruhMinecraftEntity, NotifyEntity):
    """Broadcast chat / titles to every player on the Minecraft server."""

    _attr_supported_features = NotifyEntityFeature.TITLE
    _attr_name = "Broadcast"
    _attr_icon = "mdi:message-text"

    def __init__(self, coordinator: BruhMinecraftCoordinator) -> None:
        super().__init__(coordinator, "notify")

    async def async_send_message(
        self,
        message: str,
        title: str | None = None,
    ) -> None:
        """Send `message` to every connected player.

        If `title` is provided we use `/tellraw` to produce a coloured,
        bold title followed by the message, otherwise we fall back to
        `/say` for a plain chat broadcast.
        """
        message = (message or "").strip()
        if not message:
            return
        title = (title or "").strip()

        if title:
            # Build a JSON component for /tellraw. Using `@a` targets everyone.
            components = [
                {"text": title, "bold": True, "color": "gold"},
                {"text": "\n"},
                {"text": message, "color": "white"},
            ]
            command = f"tellraw @a {json.dumps(components)}"
        else:
            # Collapse newlines (Minecraft /say rejects them) and cap length.
            sanitized = message.replace("\n", " ").replace("\r", " ")[:256]
            command = f"say {sanitized}"

        try:
            await send_request("command", {"command": command})
        except Exception:  # noqa: BLE001 — log and continue; notify must not raise
            _LOGGER.exception("Failed to broadcast Minecraft message")
