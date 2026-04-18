"""Button platform: quick one-shot actions that map to bridge requests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Coroutine, Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bridge import send_request
from .const import DOMAIN
from .coordinator import BruhMinecraftCoordinator
from .entity import BruhMinecraftEntity


@dataclass(frozen=True, kw_only=True)
class BruhButtonDescription(ButtonEntityDescription):
    call: Callable[[], Coroutine[Any, Any, dict]]


BUTTONS: tuple[BruhButtonDescription, ...] = (
    BruhButtonDescription(
        key="backup_now",
        name="Backup world",
        icon="mdi:content-save",
        call=lambda: send_request("backup", {}, timeout=180.0),
    ),
    BruhButtonDescription(
        key="restart_server",
        name="Restart server",
        icon="mdi:restart",
        call=lambda: send_request("restart", {}, timeout=30.0),
    ),
    BruhButtonDescription(
        key="stop_server",
        name="Stop server",
        icon="mdi:stop",
        call=lambda: send_request("stop", {}, timeout=30.0),
    ),
    BruhButtonDescription(
        key="save_all",
        name="Save world",
        icon="mdi:earth",
        call=lambda: send_request("command", {"command": "save-all flush"}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BruhMinecraftCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BruhButton(coordinator, d) for d in BUTTONS)


class BruhButton(BruhMinecraftEntity, ButtonEntity):
    entity_description: BruhButtonDescription

    def __init__(
        self,
        coordinator: BruhMinecraftCoordinator,
        description: BruhButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.call()
