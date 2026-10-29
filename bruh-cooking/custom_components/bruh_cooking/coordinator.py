"""Appliance list over REST, live appliance state over the websocket."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable
import contextlib
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, TypeVar

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ApplianceSocket,
    BrevilleAuthError,
    BrevilleClient,
    BrevilleError,
    StopRecipeReason,
    parse_message,
)
from .appliance import (
    FINISH_WAIT_MODELS,
    MODELS,
    ApplianceStatus,
    CookSettings,
    StateTracker,
    build_edit,
    build_finish_wait,
    build_manual_steps,
    build_next_step,
    default_settings,
    firmware_for,
    parse_status,
)
from .const import (
    APPLIANCE_REFRESH_INTERVAL,
    CONF_ALLOW_UNTESTED_CONTROL,
    CONF_SHOW_SIDEBAR_PANEL,
    DEFAULT_SHOW_SIDEBAR_PANEL,
    DOMAIN,
    MESSAGE_LOG_SIZE,
    WS_RECONNECT_FACTOR,
    WS_RECONNECT_MAX,
    WS_RECONNECT_MIN,
)

if TYPE_CHECKING:
    from . import BrevilleConfigEntry

_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


def sidebar_panel_enabled(entry: ConfigEntry) -> bool:
    """The sidebar panel shows the entry's appliances unless it's turned off."""
    return entry.options.get(CONF_SHOW_SIDEBAR_PANEL, DEFAULT_SHOW_SIDEBAR_PANEL) is not False


@dataclass
class Appliance:
    """One supported appliance and its latest state."""

    serial: str
    model: str
    name: str | None
    item_number: str | None
    settings: CookSettings
    state: dict[str, Any] = field(default_factory=dict)
    status: ApplianceStatus = field(default_factory=ApplianceStatus)
    # False once the appliance list no longer includes it.
    on_account: bool = True
    # Raw websocket messages, newest last, for diagnostics.
    messages: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MESSAGE_LOG_SIZE)
    )


class BrevilleCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Keeps every appliance on the account up to date."""

    config_entry: BrevilleConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BrevilleConfigEntry, client: BrevilleClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=APPLIANCE_REFRESH_INTERVAL,
        )
        self.client = client
        self.appliances: dict[str, Appliance] = {}
        self.connected = False
        self._tracker = StateTracker()
        self._socket: ApplianceSocket | None = None
        self._unsupported: set[str] = set()

    async def _async_update_data(self) -> dict[str, Appliance]:
        try:
            result = await self.client.get_appliances()
        except BrevilleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (BrevilleError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching appliances: {err}") from err

        added = []
        listed: set[str] = set()
        for raw in result["appliances"]:
            serial, model = raw.get("serialNumber"), raw.get("model")
            if not serial:
                continue
            if model not in MODELS:
                if serial not in self._unsupported:
                    self._unsupported.add(serial)
                    _LOGGER.info("Ignoring unsupported appliance model %s", model)
                continue
            listed.add(serial)
            if (appliance := self.appliances.get(serial)) is None:
                appliance = self.appliances[serial] = Appliance(
                    serial, model, raw.get("name"), raw.get("itemNumber"),
                    default_settings(model),
                )
                added.append(appliance)
            elif raw.get("name"):
                appliance.name = raw["name"]
        # Appliances that left the account go unavailable; their devices can
        # then be deleted (async_remove_config_entry_device).
        for serial, appliance in self.appliances.items():
            appliance.on_account = serial in listed
        if added and self._socket is not None and self._socket.connected:
            for appliance in added:
                await self._socket.subscribe(appliance.serial, appliance.model)
        return self.appliances

    async def async_remove_appliance(self, serial: str) -> None:
        """Forget an appliance whose device was deleted."""
        if self.appliances.pop(serial, None) is None:
            return
        if self._socket is not None and self._socket.connected:
            with contextlib.suppress(BrevilleError, aiohttp.ClientError):
                await self._socket.unsubscribe(serial)

    # -- websocket -----------------------------------------------------------

    @callback
    def async_start_websocket(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self._run_websocket(), f"{DOMAIN} websocket"
        )

    async def _run_websocket(self) -> None:
        delay = WS_RECONNECT_MIN
        while True:
            socket = self.client.websocket()
            try:
                await socket.connect()
                self._socket = socket
                self._set_connected(True)
                delay = WS_RECONNECT_MIN
                for appliance in list(self.appliances.values()):
                    await socket.subscribe(appliance.serial, appliance.model)
                async for msg in socket.messages():
                    self._handle_message(msg)
                _LOGGER.debug("Websocket closed by the server")
            except BrevilleAuthError:
                _LOGGER.warning("Breville session expired; re-authentication required")
                self.config_entry.async_start_reauth(self.hass)
                return
            except (BrevilleError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Websocket error: %s", err)
            except Exception:  # keep the live connection alive whatever happens
                _LOGGER.exception("Unexpected error in the Breville websocket")
            finally:
                self._socket = None
                self._set_connected(False)
                await socket.close()
            await asyncio.sleep(delay)
            delay = min(delay * WS_RECONNECT_FACTOR, WS_RECONNECT_MAX)

    @callback
    def _set_connected(self, connected: bool) -> None:
        if self.connected != connected:
            self.connected = connected
            self.async_update_listeners()

    @callback
    def _handle_message(self, msg: Any) -> None:
        # Keep every message for the appliance, even ones that are ignored or
        # out of date: the sequence is what diagnostics are for.
        serial = msg.get("serialNumber") if isinstance(msg, dict) else None
        if (logged := self.appliances.get(serial)) is not None:
            logged.messages.append(
                {"at": dt_util.utcnow().isoformat(timespec="seconds"), "message": msg}
            )
        update = parse_message(msg)
        if update is None or (appliance := self.appliances.get(update.serial)) is None:
            return
        if not self._tracker.apply(update, appliance.model):
            return
        appliance.state = self._tracker.state(update.serial)
        firmware = appliance.status.firmware
        appliance.status = parse_status(appliance.model, appliance.state, previous=appliance.status)
        if appliance.status.firmware and appliance.status.firmware != firmware:
            self._update_sw_version(appliance)
        self.async_update_listeners()

    @callback
    def _update_sw_version(self, appliance: Appliance) -> None:
        registry = dr.async_get(self.hass)
        if device := registry.async_get_device(identifiers={(DOMAIN, appliance.serial)}):
            registry.async_update_device(device.id, sw_version=appliance.status.firmware)

    # -- commands --------------------------------------------------------------

    def control_allowed(self, appliance: Appliance) -> bool:
        """Whether cooks may be started or changed (stopping always is)."""
        return MODELS[appliance.model].tested or bool(
            self.config_entry.options.get(CONF_ALLOW_UNTESTED_CONTROL)
        )

    def _ensure_control_allowed(self, appliance: Appliance) -> None:
        if not self.control_allowed(appliance):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="untested_control",
                translation_placeholders={"product": MODELS[appliance.model].product},
            )

    async def async_start_cook(
        self, appliance: Appliance, settings: CookSettings | None = None
    ) -> None:
        self._ensure_control_allowed(appliance)
        try:
            steps = build_manual_steps(appliance.model, settings or appliance.settings)
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="start_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._call(
            self.client.load_manual_recipe(
                appliance.serial,
                appliance.model,
                firmware_for(appliance.model, appliance.state),
                steps,
                locale=self._locale(),
            )
        )

    async def async_stop_cook(self, appliance: Appliance) -> None:
        await self._call(
            self.client.stop_recipe(
                appliance.serial,
                appliance.model,
                firmware=firmware_for(appliance.model, appliance.state),
                reason=StopRecipeReason.CANCEL,
            )
        )

    async def async_finish_wait(self, appliance: Appliance) -> None:
        """The app's on-screen button: food in, or food out."""
        self._ensure_control_allowed(appliance)
        if appliance.model in FINISH_WAIT_MODELS:
            await self._call(
                self.client.finish_wait(
                    appliance.serial,
                    appliance.model,
                    build_finish_wait(appliance.model, appliance.state),
                )
            )
            return
        try:
            step = build_next_step(appliance.state)
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="edit_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self._call(
            self.client.send_step(
                appliance.serial,
                appliance.model,
                firmware_for(appliance.model, appliance.state),
                step.recipe_id,
                step.step_index,
            )
        )

    async def async_edit_cook(
        self,
        appliance: Appliance,
        *,
        temperature_c: float | None = None,
        duration_s: int | None = None,
    ) -> None:
        self._ensure_control_allowed(appliance)
        if not MODELS[appliance.model].can_edit_cook:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="stop_cook_first"
            )
        try:
            edit = build_edit(
                appliance.model, appliance.state, appliance.status,
                temperature_c=temperature_c, duration_s=duration_s,
            )
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="edit_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if edit.csj_program is not None:
            await self._call(
                self.client.csj_update_program(appliance.serial, edit.csj_program)
            )
        else:
            await self._call(
                self.client.update_cook(
                    appliance.serial, appliance.model, edit.updates,
                    uuid=edit.uuid, step=edit.step,
                )
            )

    async def _call(self, request: Awaitable[_T]) -> _T:
        try:
            return await request
        except BrevilleAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_expired"
            ) from err
        except (BrevilleError, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    def _locale(self) -> str:
        language = self.hass.config.language or "en"
        if "-" in language:
            return language
        country = self.hass.config.country
        return f"{language}-{country}" if country else "en-US"
