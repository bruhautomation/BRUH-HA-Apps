"""Continue button: the app's virtual button press (food in / food out)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrevilleConfigEntry
from .appliance import WAITING_STATES
from .entity import BrevilleEntity, async_add_appliance_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_appliance_entities(
        entry,
        async_add_entities,
        lambda coordinator, appliance: [ContinueButton(coordinator, appliance, "continue")],
    )


class ContinueButton(BrevilleEntity, ButtonEntity):
    """Starts the timer once the food is in, or finishes once it's out."""

    @property
    def available(self) -> bool:
        # Not once an oven has finished and turned off: its next steps are
        # the app's optional "a bit more" and "keep warm".
        status = self.appliance.status
        return super().available and status.state in WAITING_STATES and status.active

    async def async_press(self) -> None:
        await self.coordinator.async_finish_wait(self.appliance)
