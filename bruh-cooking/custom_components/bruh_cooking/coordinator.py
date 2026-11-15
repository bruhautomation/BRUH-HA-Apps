"""Appliance list over REST, live appliance state over the websocket."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
import os
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
from homeassistant.helpers.storage import Store
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
    BRAND_SAGE,
    CONF_ALLOW_UNTESTED_CONTROL,
    CONF_BRAND,
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

# What survives a restart of Home Assistant: each appliance's last contact and
# last cook, so an appliance that is offline after a restart still says them.
STORE_VERSION = 1
STORE_SAVE_DELAY = 5
# How long a preset named by `start` waits for its cook to be seen. The cloud
# can accept a start the appliance never begins (an oven left waiting for Start
# on its panel); a cook seen after this is someone else's and is not labelled.
PRESET_WAIT = timedelta(minutes=15)
# Where the add-on reads how each account stands (its log is not Home
# Assistant's): one file per config entry, no email and no token in it.
ACCOUNT_DIR = ".bruh_cooking/accounts"

# The account sensor's states.
CONNECTION_CONNECTED = "connected"
CONNECTION_DOWN = "not_connected"
CONNECTION_SIGN_IN_REFUSED = "sign_in_refused"
CONNECTION_STATES = [CONNECTION_CONNECTED, CONNECTION_DOWN, CONNECTION_SIGN_IN_REFUSED]


def account_file(hass: HomeAssistant, entry_id: str) -> str:
    return hass.config.path(ACCOUNT_DIR, f"{entry_id}.json")


def account_identifier(entry_id: str) -> tuple[str, str]:
    """The account device's identifier: never an appliance's serial."""
    return (DOMAIN, f"account_{entry_id}")


def device_for(hass: HomeAssistant, serial: str) -> dr.DeviceEntry | None:
    """The device registered for an appliance's serial.

    Read from the lists of this integration's own devices: Home Assistant is
    retiring the registry's identifier lookup.
    """
    registry = dr.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            if (DOMAIN, serial) in device.identifiers:
                return device
    return None


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
    # When the appliance last reported itself online, and since when it has not.
    last_contact: datetime | None = None
    offline_since: datetime | None = None
    # The latest cook seen: when it started and ended, and what it was set to;
    # the preset it came from and when it was due to finish, once known.
    last_cook: dict[str, Any] | None = None
    # The appliance's own id for that cook, to tell it from a new one when
    # contact comes back.
    last_cook_id: str | None = None


def _ago(seconds: float) -> str:
    """How long, in words a person reads: "under a minute", "12 min", "3 h 5 min", "2 days"."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{hours // 24} days"


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
        # What the integration observes about the way to the appliance: Breville
        # turning the sign-in down, or the cloud connection being down, and since when.
        self.auth_failed = False
        self.problem_since: datetime | None = dt_util.utcnow()
        # The account as last read: when the appliance list last came back, and
        # the appliances on it this integration does not drive, with the reason.
        self.last_poll: datetime | None = None
        self.not_driven: list[dict[str, str]] = []
        self._reported: tuple[Any, ...] | None = None
        self._account_pending: dict[str, Any] | None = None
        self._account_writing = False
        # A preset's name and when it was named, held until the cook it starts
        # is seen, for PRESET_WAIT at most (note_preset).
        self._pending_preset: dict[str, tuple[str, datetime]] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.appliances"
        )
        self._remembered: dict[str, Any] = {}

    async def async_load_remembered(self) -> None:
        """Read what an earlier run kept: the last contact and last cook per appliance."""
        data = await self._store.async_load()
        self._remembered = data if isinstance(data, dict) else {}

    async def async_save_remembered(self) -> None:
        """Write what is kept now, rather than after the save delay (the entry is unloading)."""
        if self._remembered:
            await self._store.async_save(dict(self._remembered))

    @callback
    def _remember(self, appliance: Appliance) -> None:
        self._remembered[appliance.serial] = {
            "last_contact": appliance.last_contact.isoformat(timespec="seconds")
            if appliance.last_contact
            else None,
            "last_cook": appliance.last_cook,
            "cook_id": appliance.last_cook_id,
        }
        self._store.async_delay_save(lambda: dict(self._remembered), STORE_SAVE_DELAY)

    @callback
    def _restore(self, appliance: Appliance) -> None:
        saved = self._remembered.get(appliance.serial)
        if not isinstance(saved, dict):
            return
        if isinstance(saved.get("last_contact"), str):
            appliance.last_contact = dt_util.parse_datetime(saved["last_contact"])
        if isinstance(saved.get("last_cook"), dict):
            appliance.last_cook = saved["last_cook"]
        if isinstance(saved.get("cook_id"), str):
            appliance.last_cook_id = saved["cook_id"]

    @callback
    def note_preset(self, appliance: Appliance, preset: str | None) -> None:
        """A cook is about to start from this preset (None: it did not start)."""
        if preset is None:
            self._pending_preset.pop(appliance.serial, None)
        else:
            self._pending_preset[appliance.serial] = (preset, dt_util.utcnow())

    @property
    def brand(self) -> str:
        """Breville or Sage, as the account was added: what the person calls it."""
        return "Sage" if self.config_entry.data.get(CONF_BRAND) == BRAND_SAGE else "Breville"

    # -- the account, for the account sensor and the add-on's log ------------

    @property
    def connection(self) -> str:
        if self.auth_failed:
            return CONNECTION_SIGN_IN_REFUSED
        return CONNECTION_CONNECTED if self.connected else CONNECTION_DOWN

    def account_summary(self) -> dict[str, Any]:
        """How the account stands, in counts and names; never a credential or the email."""
        return {
            "connection": self.connection,
            "appliances_found": sum(1 for a in self.appliances.values() if a.on_account),
            "last_poll": self.last_poll.isoformat(timespec="seconds") if self.last_poll else None,
            "not_driven": [dict(item) for item in self.not_driven],
        }

    @callback
    def _account_changed(self) -> None:
        """Log the account once per change, and write it where the add-on reads it."""
        summary = self.account_summary()
        key = (summary["connection"], summary["appliances_found"], tuple(
            (item["name"], item["reason"]) for item in self.not_driven
        ))
        if key != self._reported:
            self._reported = key
            _LOGGER.info(
                "%s account: %s, %d appliance(s) found%s",
                self.brand,
                summary["connection"].replace("_", " "),
                summary["appliances_found"],
                "".join(f"; not driven: {item['name']}, {item['reason']}" for item in self.not_driven),
            )
        # One writer at a time, newest last: the report is written in the executor.
        self._account_pending = {
            **summary, "brand": self.brand, "written_at": dt_util.utcnow().isoformat(timespec="seconds"),
        }
        if not self._account_writing:
            self._account_writing = True
            self.hass.async_create_task(self._write_account(), f"{DOMAIN} account report")

    async def _write_account(self) -> None:
        path = account_file(self.hass, self.config_entry.entry_id)

        def write(data: dict[str, Any]) -> None:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(f"{path}.tmp", "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                os.replace(f"{path}.tmp", path)
            except OSError as err:
                _LOGGER.debug("Could not write the account report: %s", err)

        try:
            while (data := self._account_pending) is not None:
                self._account_pending = None
                await self.hass.async_add_executor_job(write, data)
        finally:
            self._account_writing = False

    @callback
    def _note_path(self) -> None:
        """Track since when the way to the appliances has been down."""
        if self.connected and not self.auth_failed:
            self.problem_since = None
        elif self.problem_since is None:
            self.problem_since = dt_util.utcnow()

    def offline_report(self, appliance: Appliance) -> dict[str, Any] | None:
        """Why an appliance is offline and one thing to try; None while it is online.

        Decided from what is observed: Breville turning the sign-in down (an
        authentication error), the cloud connection being down (the websocket
        will not connect), or the connection being fine while the appliance
        reports itself offline.
        """
        if self.connected and appliance.status.online:
            return None
        if self.auth_failed:
            cause = "sign_in"
            since = self.problem_since
            why = "Breville is not accepting the saved sign-in"
            fix = "Sign in again: open Settings > Devices & services > BRUH Cooking and choose Reconfigure or the sign-in notice"
        elif not self.connected:
            cause = "cloud"
            since = self.problem_since
            why = "Home Assistant cannot reach Breville's cloud"
            fix = "Check that Home Assistant has internet access; it reconnects by itself"
        else:
            cause = "device"
            since = appliance.offline_since
            why = "Breville's cloud is reachable and the sign-in works, but the appliance is not answering"
            fix = f"Check that the appliance is plugged in and on Wi-Fi, and that the {self.brand} app shows it online"
        since = since or self.problem_since or dt_util.utcnow()
        age = max(0.0, (dt_util.utcnow() - since).total_seconds())
        return {
            "cause": cause,
            "since": since.isoformat(timespec="seconds"),
            "text": f"Offline for {_ago(age)}. {why}. To try: {fix}.",
        }

    async def _async_update_data(self) -> dict[str, Appliance]:
        try:
            result = await self.client.get_appliances()
        except BrevilleAuthError as err:
            self._set_auth_failed(True)
            self._account_changed()
            raise ConfigEntryAuthFailed(str(err)) from err
        except (BrevilleError, aiohttp.ClientError, TimeoutError) as err:
            self._account_changed()
            raise UpdateFailed(f"Error fetching appliances: {err}") from err
        self._set_auth_failed(False)

        added = []
        listed: set[str] = set()
        not_driven: list[dict[str, str]] = []
        supported = ", ".join(sorted({info.product for info in MODELS.values()}))
        for raw in result["appliances"]:
            serial, model = raw.get("serialNumber"), raw.get("model")
            name = str(raw.get("name") or model or "An unnamed appliance")
            if not serial:
                not_driven.append({
                    "name": name,
                    "reason": "the account lists it without a serial number, so it cannot be told apart",
                })
                continue
            if model not in MODELS:
                not_driven.append({
                    "name": name,
                    "reason": f"model {model or 'unknown'} is not one BRUH Cooking drives ({supported})",
                })
                continue
            listed.add(serial)
            if (appliance := self.appliances.get(serial)) is None:
                appliance = self.appliances[serial] = Appliance(
                    serial, model, raw.get("name"), raw.get("itemNumber"),
                    default_settings(model),
                )
                self._restore(appliance)
                _LOGGER.info("Found %s on the account", MODELS[model].product)
                added.append(appliance)
            elif raw.get("name") and raw["name"] != appliance.name:
                appliance.name = raw["name"]
                self._follow_name(appliance)
        # Appliances that left the account go unavailable; their devices can
        # then be deleted (async_remove_config_entry_device).
        for serial, appliance in self.appliances.items():
            appliance.on_account = serial in listed
        self.not_driven = not_driven
        self.last_poll = dt_util.utcnow()
        self._account_changed()
        if added and self._socket is not None and self._socket.connected:
            for appliance in added:
                await self._socket.subscribe(appliance.serial, appliance.model)
        return self.appliances

    @callback
    def _follow_name(self, appliance: Appliance) -> None:
        """The device takes a name changed in the app, unless a person named it in Home Assistant."""
        device = device_for(self.hass, appliance.serial)
        if device is not None and device.name != appliance.name and not device.name_by_user:
            dr.async_get(self.hass).async_update_device(device.id, name=appliance.name)

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
                self._set_auth_failed(True)
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
            _LOGGER.info(
                "Connection to Breville's cloud is %s", "up" if connected else "down"
            )
            self._note_path()
            if connected:
                self._set_auth_failed(False)
            else:
                for appliance in self.appliances.values():
                    self._hold_finish(appliance, appliance.status)
            self._account_changed()
            self.async_update_listeners()

    @callback
    def _set_auth_failed(self, failed: bool) -> None:
        if self.auth_failed != failed:
            self.auth_failed = failed
            _LOGGER.info("Breville sign-in %s", "was refused" if failed else "works")
            self._note_path()
            self._account_changed()
            self.async_update_listeners()

    @callback
    def _track(self, appliance: Appliance, before: ApplianceStatus) -> None:
        """Log and remember what changed: online or offline, a cook starting or stopping."""
        status, now = appliance.status, dt_util.utcnow()
        product = MODELS[appliance.model].product
        if status.online:
            appliance.last_contact = now
        if status.online != before.online:
            appliance.offline_since = None if status.online else now
            _LOGGER.info("%s is %s", product, "online" if status.online else "offline")
            if not status.online:
                self._hold_finish(appliance, before)
        cook = appliance.last_cook
        open_cook = cook is not None and not cook.get("ended_at")
        if status.active and not before.active:
            if not (open_cook and not before.online and status.cook_id == appliance.last_cook_id):
                # Not the cook that was running when contact went: a new one. (The
                # same one carries on, with its preset.)
                appliance.last_cook = {
                    "started_at": now.isoformat(timespec="seconds"),
                    "ended_at": None,
                    "target_temperature_c": status.target_temp_c,
                    "duration_s": status.cook_time_s,
                }
                appliance.last_cook_id = status.cook_id
                # Only a preset named moments ago: a start the appliance never began
                # must not label a cook someone starts by hand later.
                pending = self._pending_preset.pop(appliance.serial, None)
                if pending is not None and now - pending[1] <= PRESET_WAIT:
                    appliance.last_cook["preset"] = pending[0]
                _LOGGER.info("A cook started on the %s", product)
        elif status.online and not status.active and open_cook and (before.active or not before.online):
            # Seen stopped, or back in contact with the cook over (losing contact is
            # not the cook ending, so the last cook kept its finish time till now).
            cook["ended_at"] = now.isoformat(timespec="seconds")
            _LOGGER.info("The cook on the %s stopped", product)
        if status.online and status.active and appliance.last_cook is not None:
            # In contact during the cook: the live entities show its finish.
            appliance.last_cook.pop("finish_at", None)
        self._remember(appliance)

    @callback
    def _hold_finish(self, appliance: Appliance, seen: ApplianceStatus) -> None:
        """Contact is lost during a cook: keep when it was due to finish.

        The cook's end and time remaining go unavailable with the appliance, so
        the last cook carries the finish time last seen until the cook is seen to end.
        """
        cook = appliance.last_cook
        if cook is None or cook.get("ended_at") or seen.ends_at is None:
            return
        cook["finish_at"] = seen.ends_at.isoformat(timespec="seconds")
        self._remember(appliance)

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
        before = appliance.status
        appliance.status = parse_status(appliance.model, appliance.state, previous=appliance.status)
        self._track(appliance, before)
        if appliance.status.firmware and appliance.status.firmware != firmware:
            self._update_sw_version(appliance)
        self.async_update_listeners()

    @callback
    def _update_sw_version(self, appliance: Appliance) -> None:
        if device := device_for(self.hass, appliance.serial):
            dr.async_get(self.hass).async_update_device(
                device.id, sw_version=appliance.status.firmware
            )

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
            result = await request
        except BrevilleAuthError as err:
            self._set_auth_failed(True)
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
        self._set_auth_failed(False)
        return result

    def _locale(self) -> str:
        language = self.hass.config.language or "en"
        if "-" in language:
            return language
        country = self.hass.config.country
        return f"{language}-{country}" if country else "en-US"
