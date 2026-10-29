"""The sidebar panel's websocket API and the custom presets store.

The panel reads live values from hass.states and controls appliances through
their entities. This API sends what it can't work out from those: which entity
holds which key, how to draw each appliance, the oven's modes, whether control
is allowed, the oven's sensor target, and the presets. The payload is
`PanelMessage` in frontend/src/types.ts, which is the contract between the two.
Applying a preset is the one control that doesn't go through an entity: it
sets every cook setting at once, as choosing an oven mode resets the others.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any
import uuid

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .appliance import MODELS
from .const import CONF_ALLOW_UNTESTED_CONTROL, DOMAIN
from .frontend import SIGNAL_ENTRY_STATE, panel_entries
from .panel_spec import detect_finish, oven_mode_table
from .presets import (
    BUILTIN_PRESETS,
    MAX_CUSTOM_PRESETS,
    Preset,
    PresetError,
    applied_settings,
    check_settings,
    clean_name,
    read_custom,
    settings_preset,
    write_custom,
)

if TYPE_CHECKING:
    from .coordinator import Appliance, BrevilleCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.presets"
STORAGE_VERSION = 1
# Seconds to wait before sending an update: changes come in bursts, such as a
# platform adding its entities one at a time.
DEBOUNCE = 0.3

# Error codes the panel translates; it shows the message for any other.
ERR_COOK_RUNNING = "cook_running"
ERR_UNKNOWN_APPLIANCE = "unknown_appliance"
ERR_UNKNOWN_PRESET = "unknown_preset"
ERR_INVALID_PRESET = "invalid_preset"
ERR_TOO_MANY_PRESETS = "too_many_presets"
ERR_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ApplianceState:
    """What the panel shows an appliance from: its coordinator's, or what it had when its
    entry unloaded."""

    serial: str
    model: str
    name: str | None
    item_number: str | None
    sensor_target_c: float | None
    available: bool


@dataclass
class PanelData:
    """The custom presets, the open subscriptions, and appliances kept through a reload."""

    store: Store
    # None until loaded.
    custom: list[Preset] | None = None
    subscriptions: set[PanelSubscription] = field(default_factory=set)
    # The appliances of entries that unloaded, as they were then, by entry id.
    # The panel shows them unavailable until the entry is set up again, rather
    # than dropping them while it reloads or waits to retry its setup.
    unloaded: dict[str, list[ApplianceState]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def async_custom(self) -> list[Preset]:
        """The custom presets, loaded the first time they're needed."""
        async with self.lock:
            if self.custom is None:
                self.custom = read_custom(await self.store.async_load())
        return self.custom

    async def async_save(self) -> None:
        await self.store.async_save(write_custom(self.custom or []))

    @callback
    def changed(self) -> None:
        for subscription in list(self.subscriptions):
            subscription.async_changed()


DATA: HassKey[PanelData] = HassKey(f"{DOMAIN}_panel")
# The same for every message, so worked out once.
_OVEN_MODES: list[dict[str, Any]] = []


def _panel_data(hass: HomeAssistant) -> PanelData:
    if (data := hass.data.get(DATA)) is None:
        data = hass.data[DATA] = PanelData(Store(hass, STORAGE_VERSION, STORAGE_KEY))
    return data


def _oven_modes() -> list[dict[str, Any]]:
    if not _OVEN_MODES:
        _OVEN_MODES.extend(oven_mode_table())
    return _OVEN_MODES


def _coordinator(hass: HomeAssistant, entry: ConfigEntry) -> BrevilleCoordinator | None:
    """The coordinator of an entry that's set up; none while its appliances are kept."""
    data = hass.data.get(DATA)
    if data is not None and entry.entry_id in data.unloaded:
        return None
    return getattr(entry, "runtime_data", None)


def _appliance_state(coordinator: BrevilleCoordinator, appliance: Appliance) -> ApplianceState:
    status = appliance.status
    return ApplianceState(
        appliance.serial,
        appliance.model,
        appliance.name,
        appliance.item_number,
        status.sensor_target_c if status.active else None,
        coordinator.connected and appliance.on_account and status.online,
    )


def _appliance_states(hass: HomeAssistant, entry: ConfigEntry) -> list[ApplianceState]:
    """An entry's appliances: live while it's set up, else as they were when it unloaded."""
    data = hass.data.get(DATA)
    if data is not None and (kept := data.unloaded.get(entry.entry_id)) is not None:
        return kept
    if (coordinator := _coordinator(hass, entry)) is None:
        return []
    return [_appliance_state(coordinator, a) for a in coordinator.appliances.values()]


def _entity_maps(
    registry: er.EntityRegistry, entry_id: str, serials: list[str]
) -> dict[str, dict[str, dict[str, str]]]:
    """Entity ids by serial, key and domain, leaving out disabled entities."""
    # Longest first, so a serial that begins with another's isn't taken for it.
    prefixes = sorted(((f"{serial}_", serial) for serial in serials), key=lambda p: len(p[0]), reverse=True)
    maps: dict[str, dict[str, dict[str, str]]] = {}
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.disabled:
            continue
        for prefix, serial in prefixes:
            if entity.unique_id.startswith(prefix):
                key = entity.unique_id.removeprefix(prefix)
                maps.setdefault(serial, {}).setdefault(key, {})[entity.domain] = entity.entity_id
                break
    return maps


def _appliance(
    entry: ConfigEntry,
    appliance: ApplianceState,
    device: dr.DeviceEntry,
    entities: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """An appliance as the panel receives it (PanelAppliance). The serial stays here."""
    info = MODELS[appliance.model]
    return {
        "device_id": device.id,
        "entry_id": entry.entry_id,
        "name": appliance.name or info.product,
        "model": appliance.model,
        "product": info.product,
        "kind": info.kind.value,
        "finish": detect_finish(appliance.model, appliance.item_number, appliance.serial),
        "available": appliance.available,
        "tested": info.tested,
        "control_allowed": info.tested or bool(entry.options.get(CONF_ALLOW_UNTESTED_CONTROL)),
        "can_edit_cook": info.can_edit_cook,
        "sensor_target_c": appliance.sensor_target_c,
        "limits": {
            "min_temp_c": info.min_temp_c,
            "max_temp_c": info.max_temp_c,
            "max_cook_s": info.max_cook_s,
        },
        "entities": entities,
    }


@callback
def panel_message(hass: HomeAssistant, custom: list[Preset]) -> dict[str, Any]:
    """What the panel shows (PanelMessage): the appliances of the entries that show it."""
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    appliances = []
    for entry in panel_entries(hass):
        states = _appliance_states(hass, entry)
        registered = {
            identifier: device
            for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
            for domain, identifier in device.identifiers
            if domain == DOMAIN
        }
        entity_maps = _entity_maps(registry, entry.entry_id, [a.serial for a in states])
        for appliance in states:
            # The panel routes by device, so an appliance without one can't be shown.
            if (device := registered.get(appliance.serial)) is not None:
                appliances.append(
                    _appliance(entry, appliance, device, entity_maps.get(appliance.serial, {}))
                )
    return {
        "appliances": appliances,
        "oven_modes": _oven_modes(),
        "presets": [preset.as_dict() for preset in (*BUILTIN_PRESETS, *custom)],
    }


class PanelSubscription:
    """One panel's subscription, which is sent the PanelMessage whenever it changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg_id: int,
        data: PanelData,
    ) -> None:
        self.hass = hass
        self.connection = connection
        self.msg_id = msg_id
        self._data = data
        self._last: dict[str, Any] | None = None
        # The entity ids in the last message, to tell which removed entities mattered.
        self._entity_ids: set[str] = set()
        self._coordinators: dict[BrevilleCoordinator, CALLBACK_TYPE] = {}
        self._unsub_registry: CALLBACK_TYPE | None = None
        self._unsub_send: CALLBACK_TYPE | None = None
        self._send_job = HassJob(
            self._async_send_if_changed, "BRUH Cooking panel update", cancel_on_shutdown=True
        )

    @callback
    def async_start(self, message: dict[str, Any]) -> None:
        self._data.subscriptions.add(self)
        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self.async_changed, event_filter=self._ours
        )
        self._follow_coordinators()
        self._send(message)

    @callback
    def async_stop(self) -> None:
        self._data.subscriptions.discard(self)
        if self._unsub_send is not None:
            self._unsub_send()
            self._unsub_send = None
        if self._unsub_registry is not None:
            self._unsub_registry()
            self._unsub_registry = None
        for unsub in self._coordinators.values():
            unsub()
        self._coordinators.clear()

    @callback
    def async_entries_changed(self) -> None:
        """Follow the coordinators of the entries set up now, and send any change."""
        self._follow_coordinators()
        self.async_changed()

    @callback
    def async_changed(self, _event: Event | None = None) -> None:
        """Send the message once a burst of changes is over, if it changed."""
        if self._unsub_send is None:
            self._unsub_send = async_call_later(self.hass, DEBOUNCE, self._send_job)

    @callback
    def _ours(self, event_data: er.EventEntityRegistryUpdatedData) -> bool:
        """Whether an entity registry update is about this integration's entities."""
        if event_data["action"] == "remove":
            # The entity is gone from the registry, so look in what was sent.
            return event_data["entity_id"] in self._entity_ids
        entity = er.async_get(self.hass).async_get(event_data["entity_id"])
        return entity is not None and entity.platform == DOMAIN

    @callback
    def _follow_coordinators(self) -> None:
        current = {
            coordinator
            for entry in panel_entries(self.hass)
            if (coordinator := _coordinator(self.hass, entry)) is not None
        }
        for coordinator in self._coordinators.keys() - current:
            self._coordinators.pop(coordinator)()
        for coordinator in current - self._coordinators.keys():
            self._coordinators[coordinator] = coordinator.async_add_listener(self.async_changed)

    @callback
    def _async_send_if_changed(self, _now: Any) -> None:
        self._unsub_send = None
        message = panel_message(self.hass, self._data.custom or [])
        if message != self._last:
            self._send(message)

    @callback
    def _send(self, message: dict[str, Any]) -> None:
        self._last = message
        self._entity_ids = {
            entity_id
            for appliance in message["appliances"]
            for domains in appliance["entities"].values()
            for entity_id in domains.values()
        }
        self.connection.send_message(websocket_api.event_message(self.msg_id, message))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/panel/subscribe"})
@websocket_api.async_response
async def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send the PanelMessage now, and again whenever it changes."""
    data = _panel_data(hass)
    message = panel_message(hass, await data.async_custom())
    subscription = PanelSubscription(hass, connection, msg["id"], data)
    connection.subscriptions[msg["id"]] = subscription.async_stop
    connection.send_result(msg["id"])
    subscription.async_start(message)


def _find_appliance(
    hass: HomeAssistant, device_id: str
) -> tuple[BrevilleCoordinator | None, Appliance | None, bool]:
    """A shown appliance's coordinator and appliance, by device; whether it's shown at all.

    The coordinator and appliance are None while the appliance's entry isn't set up.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None, None, False
    serials = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
    for entry in panel_entries(hass):
        if entry.entry_id not in device.config_entries:
            continue
        if (coordinator := _coordinator(hass, entry)) is None:
            return None, None, True
        for serial in serials:
            if (appliance := coordinator.appliances.get(serial)) is not None:
                return coordinator, appliance, True
        return None, None, False
    return None, None, False


def _preset(custom: list[Preset], preset_id: str) -> Preset | None:
    return next((p for p in (*BUILTIN_PRESETS, *custom) if p.id == preset_id), None)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/panel/apply_preset",
        vol.Required("device_id"): str,
        vol.Required("preset_id"): str,
    }
)
@websocket_api.async_response
async def ws_apply_preset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Fill in an appliance's cook settings from a preset. Nothing starts."""
    data = _panel_data(hass)
    coordinator, appliance, shown = _find_appliance(hass, msg["device_id"])
    if not shown:
        connection.send_error(msg["id"], ERR_UNKNOWN_APPLIANCE, "Unknown appliance.")
        return
    if coordinator is None or appliance is None:
        connection.send_error(msg["id"], ERR_UNAVAILABLE, "The appliance isn't available.")
        return
    if (preset := _preset(await data.async_custom(), msg["preset_id"])) is None:
        connection.send_error(msg["id"], ERR_UNKNOWN_PRESET, "Unknown preset.")
        return
    if appliance.status.active:
        connection.send_error(msg["id"], ERR_COOK_RUNNING, "Stop the cook first.")
        return
    fahrenheit = hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
    try:
        appliance.settings = applied_settings(
            preset, appliance.model, appliance.settings, fahrenheit=fahrenheit
        )
    except PresetError as err:
        connection.send_error(msg["id"], ERR_INVALID_PRESET, str(err))
        return
    # The setting entities show the new settings.
    coordinator.async_update_listeners()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/panel/save_preset",
        vol.Optional("preset_id"): str,
        vol.Optional("device_id"): str,
        vol.Optional("name"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_preset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save an appliance's current settings as a custom preset, or rename or update one.

    Without `preset_id`, a new preset from `device_id`'s settings, named `name`.
    With it, `name` renames the preset and `device_id` replaces its settings.
    """
    data = _panel_data(hass)
    custom = await data.async_custom()
    preset_id = msg.get("preset_id")
    existing = next((p for p in custom if p.id == preset_id), None) if preset_id else None
    if preset_id and existing is None:
        connection.send_error(msg["id"], ERR_UNKNOWN_PRESET, "Unknown preset.")
        return
    if existing is None and len(custom) >= MAX_CUSTOM_PRESETS:
        connection.send_error(
            msg["id"], ERR_TOO_MANY_PRESETS, f"There can be at most {MAX_CUSTOM_PRESETS} presets."
        )
        return
    kind = existing.kind if existing else None
    settings = dict(existing.settings) if existing else None
    if (device_id := msg.get("device_id")) is not None:
        _, appliance, shown = _find_appliance(hass, device_id)
        if appliance is None:
            code = ERR_UNAVAILABLE if shown else ERR_UNKNOWN_APPLIANCE
            connection.send_error(msg["id"], code, "The appliance isn't available.")
            return
        appliance_kind = MODELS[appliance.model].kind
        if kind is not None and appliance_kind is not kind:
            connection.send_error(
                msg["id"], ERR_INVALID_PRESET, "That appliance cooks a different kind of preset."
            )
            return
        kind = appliance_kind
        settings = settings_preset(appliance.model, appliance.settings)
    if kind is None or settings is None:
        connection.send_error(msg["id"], ERR_INVALID_PRESET, "Choose the appliance to save from.")
        return
    try:
        name = clean_name(msg.get("name")) if "name" in msg or existing is None else existing.name
        check_settings(kind, settings)
    except PresetError as err:
        connection.send_error(msg["id"], ERR_INVALID_PRESET, str(err))
        return
    preset = Preset(existing.id if existing else uuid.uuid4().hex, kind, settings, name=name)
    if existing is None:
        custom.append(preset)
    else:
        custom[custom.index(existing)] = preset
    await data.async_save()
    connection.send_result(msg["id"], {"preset": preset.as_dict()})
    data.changed()


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/panel/delete_preset", vol.Required("preset_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_preset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a custom preset, for everyone."""
    data = _panel_data(hass)
    custom = await data.async_custom()
    if (preset := next((p for p in custom if p.id == msg["preset_id"]), None)) is None:
        connection.send_error(msg["id"], ERR_UNKNOWN_PRESET, "Unknown preset.")
        return
    custom.remove(preset)
    await data.async_save()
    connection.send_result(msg["id"])
    data.changed()


@callback
def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Register the panel's websocket commands, and follow the entries' state."""
    for command in (ws_subscribe, ws_apply_preset, ws_save_preset, ws_delete_preset):
        websocket_api.async_register_command(hass, command)

    @callback
    def entry_state_changed() -> None:
        # Setup and unload update subscribers themselves; this catches options
        # changing, which reloads nothing, and an entry disabled while it waits
        # to retry its setup, which unloads nothing.
        if (data := hass.data.get(DATA)) is not None:
            _entries_changed(data)

    async_dispatcher_connect(hass, SIGNAL_ENTRY_STATE, entry_state_changed)


@callback
def async_panel_entry_set_up(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show a set-up entry's appliances live, and update subscribers."""
    if (data := hass.data.get(DATA)) is not None:
        data.unloaded.pop(entry.entry_id, None)
        _entries_changed(data)


@callback
def async_panel_entry_unloaded(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Keep an unloaded entry's appliances as they were, unavailable, and update subscribers.

    An entry unloads to reload, after a reauth say, and setup can take a
    while; meanwhile, and while it waits to retry its setup, the panel shows
    the appliances unavailable instead of losing them.
    """
    data = _panel_data(hass)
    coordinator = getattr(entry, "runtime_data", None)
    data.unloaded[entry.entry_id] = [
        ApplianceState(a.serial, a.model, a.name, a.item_number, None, False)
        for a in (coordinator.appliances.values() if coordinator is not None else ())
    ]
    _entries_changed(data)


@callback
def async_panel_entry_removed(hass: HomeAssistant, entry_id: str) -> None:
    """Let a removed entry's appliances go, and update subscribers."""
    if (data := hass.data.get(DATA)) is not None:
        data.unloaded.pop(entry_id, None)
        _entries_changed(data)


def _entries_changed(data: PanelData) -> None:
    for subscription in list(data.subscriptions):
        subscription.async_entries_changed()


async def async_remove_presets(hass: HomeAssistant) -> None:
    """Delete the custom presets, once the last entry is removed.

    Best effort: a failure is logged, since it must never fail the removal.
    """
    try:
        data = _panel_data(hass)
        async with data.lock:
            data.custom = []
            await data.store.async_remove()
    except Exception:
        _LOGGER.exception("Could not remove the BRUH Cooking panel's presets")


async def async_panel_diagnostics(hass: HomeAssistant) -> dict[str, Any]:
    """How many custom presets there are, for diagnostics. Their names are left out."""
    return {"custom_presets": len(await _panel_data(hass).async_custom())}
