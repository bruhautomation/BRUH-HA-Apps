"""One poll of the add-on, shared by every GardenRX sensor."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GardenRxClient, GardenRxError
from .const import DOMAIN, SCAN_INTERVAL_S

_LOGGER = logging.getLogger(__name__)


class GardenRxCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, client: GardenRxClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_S),
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.summary()
        except GardenRxError as err:
            raise UpdateFailed(str(err)) from err
