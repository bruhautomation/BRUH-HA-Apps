"""Base entity for Breville+ appliances."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .appliance import MODELS
from .const import BRAND_SAGE, CONF_BRAND, DOMAIN
from .coordinator import Appliance, BrevilleCoordinator

if TYPE_CHECKING:
    from . import BrevilleConfigEntry


@callback
def async_add_appliance_entities(
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    entities_for: Callable[[BrevilleCoordinator, Appliance], Iterable[Entity]],
) -> None:
    """Add a platform's entities for each appliance, including ones found later."""
    coordinator = entry.runtime_data
    added: dict[str, Appliance] = {}

    @callback
    def add_new() -> None:
        # A different object for a known serial is an appliance that was
        # removed and has come back.
        new = [a for serial, a in coordinator.appliances.items() if added.get(serial) is not a]
        if new:
            added.update((a.serial, a) for a in new)
            async_add_entities(e for a in new for e in entities_for(coordinator, a))

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class BrevilleEntity(CoordinatorEntity[BrevilleCoordinator]):
    """An entity belonging to one appliance."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrevilleCoordinator, appliance: Appliance, key: str) -> None:
        super().__init__(coordinator)
        self._appliance = appliance
        self._attr_unique_id = f"{appliance.serial}_{key}"
        self._attr_translation_key = key
        info = MODELS[appliance.model]
        manufacturer = info.manufacturer
        if manufacturer == "Breville" and coordinator.config_entry.data.get(CONF_BRAND) == BRAND_SAGE:
            manufacturer = "Sage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.serial)},
            manufacturer=manufacturer,
            model=info.product,
            model_id=appliance.item_number or appliance.model,
            name=appliance.name or info.product,
            serial_number=appliance.serial,
        )

    @property
    def appliance(self) -> Appliance:
        return self._appliance

    @property
    def cloud_available(self) -> bool:
        """The cloud connection is up and the appliance is still on the account."""
        return self.coordinator.connected and self._appliance.on_account

    @property
    def available(self) -> bool:
        # Live state comes from the websocket; a failed appliance-list refresh
        # alone shouldn't make the appliance unavailable.
        return self.cloud_available and self._appliance.status.online
