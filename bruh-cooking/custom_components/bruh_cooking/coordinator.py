"""Appliance list over REST, live appliance state over the websocket."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable
import contextlib
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timedelta
import json
import logging
import os
from typing import TYPE_CHECKING, Any, TypeVar

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

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

# What survives a restart of Home Assistant: each appliance's last contact, last
# temperature and last cook, so an appliance that is offline after a restart
# still says them.
STORE_VERSION = 1
STORE_SAVE_DELAY = 5
# How long a start from Home Assistant waits for its cook to be seen. The cloud
# can accept a start the appliance never begins (an oven left waiting for Start
# on its panel); a cook seen after this was started somewhere else.
START_WAIT = timedelta(minutes=15)
# Where a cook's settings came from when Home Assistant did not start it.
STARTED_ELSEWHERE = "started on the appliance or in the app"
# What the status says of the last cook when there is none to tell: none seen
# while the appliance was in contact, or, when it has never been heard from,
# that whether it cooked is not known.
NO_COOK_YET = "no cook yet"
NO_COOK_KNOWN = "unknown: it has not been heard from yet, so no cook could be seen"
# An appliance out of contact this long turns its Problem sensor on: longer
# than a Wi-Fi blip, short enough that a cook left running is noticed.
OFFLINE_PROBLEM_AFTER = timedelta(minutes=10)
# How often that is looked at: nothing else happens to an appliance that went quiet.
OFFLINE_CHECK = timedelta(minutes=1)
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
    # The temperature it last reported while in contact (None when it reported
    # none, as an idle oven does): what the Temperature sensor keeps, marked as
    # old, while the appliance is offline.
    last_temp_c: float | None = None
    # The latest cook seen: when it started and ended, what it was set to and
    # where those settings came from, and when it was due to finish, once known.
    last_cook: dict[str, Any] | None = None
    # The appliance's own id for that cook, to tell it from a new one when
    # contact comes back.
    last_cook_id: str | None = None
    # The preset the panel last filled the cook settings from, and the settings
    # it made: the next cook is that preset's only while they are unchanged.
    settings_preset: tuple[str, CookSettings] | None = None


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


def _clock(moment: datetime) -> str:
    """A time a person reads: "14:05", or "14:05 on 20 Nov" when it is not today."""
    local = dt_util.as_local(moment)
    if local.date() == dt_util.now().date():
        return f"{local:%H:%M}"
    return f"{local:%H:%M} on {local.day} {local:%b}"


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
        # Breville turning the sign-in down, as last observed.
        self.auth_failed = False
        # The account as last read: when the appliance list last came back, and
        # the appliances on it this integration does not drive, with the reason.
        self.last_poll: datetime | None = None
        self.not_driven: list[dict[str, str]] = []
        self._reported: tuple[Any, ...] | None = None
        self._account_pending: dict[str, Any] | None = None
        self._account_writing = False
        # Where a start's settings came from and when it was sent, held until
        # the cook it starts is seen, for START_WAIT at most (async_start_cook).
        self._pending_start: dict[str, tuple[str, datetime]] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.appliances"
        )
        self._remembered: dict[str, Any] = {}
        # When this run began watching: how long an appliance never heard from
        # has been out of contact is counted from here.
        self.watching_since = dt_util.utcnow()
        # The appliances whose Problem sensor is on for being out of contact.
        self._offline_problems: frozenset[str] = frozenset()

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
            "temperature_c": appliance.last_temp_c,
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
        if isinstance(saved.get("temperature_c"), (int, float)):
            appliance.last_temp_c = float(saved["temperature_c"])

    def settings_source(self, appliance: Appliance) -> str:
        """Where the next cook's settings come from, in words."""
        if appliance.settings_preset is not None:
            name, made = appliance.settings_preset
            if made == appliance.settings:
                return f"the {name} preset"
        return "the cook settings in Home Assistant"

    def cook_summary(self, appliance: Appliance) -> dict[str, Any] | str:
        """The last cook as a person reads it, in the house's unit; with none, whether that is known."""
        cook = appliance.last_cook
        if not cook:
            return NO_COOK_YET if appliance.last_contact is not None else NO_COOK_KNOWN
        out: dict[str, Any] = {
            key: cook[key] for key in ("started_at", "ended_at", "finish_at") if cook.get(key)
        }
        if (celsius := cook.get("target_temperature_c")) is not None:
            unit = self.hass.config.units.temperature_unit
            out["target_temperature"] = round(
                TemperatureConverter.convert(celsius, UnitOfTemperature.CELSIUS, unit), 1
            )
            out["temperature_unit"] = unit
        if cook.get("duration_s"):
            out["duration_minutes"] = round(cook["duration_s"] / 60)
        # A cook kept by 0.1.9 named only its preset.
        if source := cook.get("settings_from") or (cook.get("preset") and f"the {cook['preset']} preset"):
            out["settings_from"] = source
        return out

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

    def in_contact(self, appliance: Appliance) -> bool:
        """The cloud is connected and the appliance reports itself online: its readings are live."""
        return self.connected and appliance.status.online

    def last_known(self, appliance: Appliance) -> dict[str, Any]:
        """What marks a reading kept from before contact was lost: it is old, and from when."""
        return {
            "stale": True,
            "as_of": appliance.last_contact.isoformat(timespec="seconds")
            if appliance.last_contact
            else None,
        }

    def out_of_contact_since(self, appliance: Appliance) -> datetime | None:
        """Since when nothing has been heard from it; None while it is in contact.

        Its last contact, which a restart keeps; with none, when this run
        began watching it.
        """
        if self.in_contact(appliance):
            return None
        return appliance.last_contact or self.watching_since

    def offline_problem(self, appliance: Appliance) -> bool:
        """Out of contact for OFFLINE_PROBLEM_AFTER or longer: the Problem sensor says so."""
        since = self.out_of_contact_since(appliance)
        return since is not None and dt_util.utcnow() - since >= OFFLINE_PROBLEM_AFTER

    def _offline_flags(self) -> frozenset[str]:
        return frozenset(
            serial
            for serial, appliance in self.appliances.items()
            if appliance.on_account and self.offline_problem(appliance)
        )

    @callback
    def _note_offline(self) -> None:
        """What the entities show now, after any update."""
        self._offline_problems = self._offline_flags()

    @callback
    def _check_offline(self, _now: datetime | None = None) -> None:
        """Update the entities when an appliance crosses OFFLINE_PROBLEM_AFTER, and only then."""
        if self._offline_flags() != self._offline_problems:
            self.async_update_listeners()

    @callback
    def async_start_offline_watch(self) -> None:
        entry = self.config_entry
        entry.async_on_unload(self.async_add_listener(self._note_offline))
        entry.async_on_unload(
            async_track_time_interval(self.hass, self._check_offline, OFFLINE_CHECK)
        )

    def offline_report(self, appliance: Appliance, *, live: bool = True) -> dict[str, Any] | None:
        """Why an appliance is offline and one thing to try; None while it is online.

        Decided from what is observed: Breville turning the sign-in down (an
        authentication error), the cloud connection being down (the websocket
        will not connect), or the connection being fine while the appliance
        reports itself offline. The text names the time it was last heard
        from, which a restart of Home Assistant keeps, or with none the time
        this run began watching. `live` text (an answer read now) also says
        how long that is; a state attribute is written once and read later,
        so it says only the time, which does not go out of date.
        """
        if self.in_contact(appliance):
            return None
        if self.auth_failed:
            cause = "sign_in"
            why = "Breville is not accepting the saved sign-in"
            fix = "Sign in again: open Settings > Devices & services > BRUH Cooking and choose Reconfigure or the sign-in notice"
        elif not self.connected:
            cause = "cloud"
            why = "Home Assistant cannot reach Breville's cloud"
            fix = "Check that Home Assistant has internet access; it reconnects by itself"
        else:
            cause = "device"
            why = "Breville's cloud is reachable and the sign-in works, but the appliance is not answering"
            fix = f"Check that the appliance is plugged in and on Wi-Fi, and that the {self.brand} app shows it online"
        since = appliance.offline_since or appliance.last_contact
        now = dt_util.utcnow()
        if (contact := appliance.last_contact) is not None:
            if live:
                age = max(0.0, (now - contact).total_seconds())
                heard = (
                    f"Offline for {_ago(age)}, counted from when it was last heard from "
                    f"({_clock(contact)})"
                )
            else:
                heard = f"Offline since {_clock(contact)}, when it was last heard from"
        else:
            started = self.watching_since
            if live:
                age = max(0.0, (now - started).total_seconds())
                heard = (
                    f"Offline for at least {_ago(age)}: not heard from since BRUH Cooking "
                    f"started ({_clock(started)})"
                )
            else:
                heard = f"Offline: not heard from since BRUH Cooking started ({_clock(started)})"
        text = f"{heard}. {why}. To try: {fix}."
        cook = appliance.last_cook
        if cook is not None and not cook.get("ended_at"):
            text += " It was cooking when contact was lost, so whether it still is will be known when it answers."
        return {
            "cause": cause,
            "since": since.isoformat(timespec="seconds") if since else None,
            "text": text,
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
            if connected:
                self._set_auth_failed(False)
            else:
                now = dt_util.utcnow()
                for appliance in self.appliances.values():
                    if appliance.status.online:
                        # In contact until now: that is when it was last heard from.
                        appliance.last_contact = appliance.offline_since = now
                        self._remember(appliance)
                    self._hold_finish(appliance, appliance.status)
            self._account_changed()
            self.async_update_listeners()

    @callback
    def _set_auth_failed(self, failed: bool) -> None:
        if self.auth_failed != failed:
            self.auth_failed = failed
            _LOGGER.info("Breville sign-in %s", "was refused" if failed else "works")
            self._account_changed()
            self.async_update_listeners()

    @callback
    def _track(self, appliance: Appliance, before: ApplianceStatus) -> None:
        """Log and remember what changed: online or offline, a cook starting or stopping."""
        status, now = appliance.status, dt_util.utcnow()
        product = MODELS[appliance.model].product
        if status.online:
            appliance.last_contact = now
            appliance.offline_since = None
            appliance.last_temp_c = status.current_temp_c
        elif before.online and appliance.offline_since is None:
            appliance.offline_since = now
        if status.online != before.online:
            _LOGGER.info("%s is %s", product, "online" if status.online else "offline")
            if not status.online:
                self._hold_finish(appliance, before)
        cook = appliance.last_cook
        open_cook = cook is not None and not cook.get("ended_at")
        if status.active and not before.active:
            if not (open_cook and not before.online and status.cook_id == appliance.last_cook_id):
                # Not the cook that was running when contact went: a new one. (The
                # same one carries on, with its preset.)
                # Only a start sent moments ago: one the appliance never began
                # must not label a cook someone starts by hand later.
                pending = self._pending_start.pop(appliance.serial, None)
                appliance.last_cook = {
                    "started_at": now.isoformat(timespec="seconds"),
                    "ended_at": None,
                    "settings_from": pending[0]
                    if pending is not None and now - pending[1] <= START_WAIT
                    else STARTED_ELSEWHERE,
                }
                appliance.last_cook_id = status.cook_id
                _LOGGER.info("A cook started on the %s", product)
        elif status.online and not status.active and open_cook and (before.active or not before.online):
            # Seen stopped, or back in contact with the cook over (losing contact is
            # not the cook ending, so the last cook kept its finish time till now).
            cook["ended_at"] = now.isoformat(timespec="seconds")
            _LOGGER.info("The cook on the %s stopped", product)
        if status.online and status.active and appliance.last_cook is not None:
            # In contact during the cook: the live entities show its finish, and
            # what it is set to is kept (the first report can leave it out).
            appliance.last_cook.pop("finish_at", None)
            if status.target_temp_c is not None:
                appliance.last_cook["target_temperature_c"] = status.target_temp_c
            if status.cook_time_s:
                appliance.last_cook["duration_s"] = status.cook_time_s
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
        self,
        appliance: Appliance,
        settings: CookSettings | None = None,
        source: str | None = None,
    ) -> None:
        """Start a cook; `source` says where its settings came from (the next
        cook's settings when none is given), for the last cook to repeat."""
        self._ensure_control_allowed(appliance)
        try:
            steps = build_manual_steps(appliance.model, settings or appliance.settings)
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="start_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._pending_start[appliance.serial] = (
            source or self.settings_source(appliance), dt_util.utcnow()
        )
        try:
            await self._call(
                self.client.load_manual_recipe(
                    appliance.serial,
                    appliance.model,
                    firmware_for(appliance.model, appliance.state),
                    steps,
                    locale=self._locale(),
                )
            )
        except Exception:
            self._pending_start.pop(appliance.serial, None)
            raise

    @callback
    def note_settings_preset(self, appliance: Appliance, name: str) -> None:
        """The panel filled the cook settings from this preset."""
        appliance.settings_preset = (name, replace(appliance.settings))

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
