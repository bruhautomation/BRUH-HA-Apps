"""Serve the sidebar panel and keep it in the sidebar while an entry shows it.

One panel serves the whole integration. It's registered while an entry set up
since Home Assistant started is enabled and has "Show in the sidebar" on, and
it lists those entries' appliances. An entry keeps its place while it reloads
or waits to retry its setup, so nobody looking at the panel is sent elsewhere;
it leaves once it's removed or disabled, or the option is turned off. The
sidebar says "BRUH Cooking" whatever the accounts' brand. All of this is best effort: every entity works without
the panel, so a failure here is logged and never fails setup or unload.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .coordinator import sidebar_panel_enabled

_LOGGER = logging.getLogger(__name__)

# frontend/build.mjs writes the bundle here, and the folder is served at STATIC_URL.
FRONTEND_DIR = Path(__file__).parent / "frontend"
BUNDLE = "bruh-cooking-panel.js"
STATIC_URL = f"/{DOMAIN}"
# The panel's path must differ from the static path: with the panel at
# /bruh_cooking, reloading the page would reach the static file handler
# instead of Home Assistant's frontend.
PANEL_URL_PATH = "bruh-cooking"
PANEL_ELEMENT = "bruh-cooking-panel"
# The add-on's name, so it isn't translated.
TITLE = "BRUH Cooking"
PANEL_ICON = "mdi:pot-steam-outline"
# Sent when an entry the panel shows changes state or options, so open panels
# follow it too.
SIGNAL_ENTRY_STATE = f"{DOMAIN}_panel_entry_state"


@dataclass
class PanelState:
    """The sidebar panel's state for this Home Assistant process."""

    # The ids of entries set up since Home Assistant started. One that unloads
    # stays until it's removed.
    entries: set[str] = field(default_factory=set)
    served: bool = False
    bundle_read: bool = False
    # The first 8 hex digits of the bundle's SHA-256; None when it couldn't be read.
    bundle_hash: str | None = None
    # The registered panel's module URL and title; None while it isn't in the sidebar.
    module_url: str | None = None
    title: str | None = None
    # Entries can be set up and unloaded at once; each sync sees the last one finished.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


DATA: HassKey[PanelState] = HassKey(f"{DOMAIN}_frontend")


def integration_version(hass: HomeAssistant) -> str:
    """The manifest version, as Home Assistant parsed it when it loaded the integration."""
    try:
        version = async_get_loaded_integration(hass, DOMAIN).version
    except IntegrationNotLoaded:
        return "unknown"
    return str(version) if version else "unknown"


def bundle_hash(path: Path) -> str | None:
    """The first 8 hex digits of the bundle's SHA-256, or None when it can't be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return None


def panel_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """The entries whose appliances the panel shows, in config entry order.

    Those set up since Home Assistant started that are still there, enabled
    and showing the panel, whether they're set up now or reloading or waiting
    to retry their setup.
    """
    state = hass.data.get(DATA)
    if state is None:
        return []
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False)
        if entry.entry_id in state.entries and sidebar_panel_enabled(entry)
    ]


def panel_title(entries: list[ConfigEntry]) -> str:
    """The sidebar's title: the add-on's name, for Breville and Sage accounts alike."""
    return TITLE


def panel_module_url(hass: HomeAssistant) -> str | None:
    """The module URL of the registered panel, or None while it isn't in the sidebar."""
    state = hass.data.get(DATA)
    return state.module_url if state is not None else None


def registered_title(hass: HomeAssistant) -> str | None:
    """The registered panel's sidebar title, or None while it isn't in the sidebar."""
    state = hass.data.get(DATA)
    return state.title if state is not None else None


@callback
def async_setup_frontend(hass: HomeAssistant) -> None:
    """Follow changes to the entries: options apply without a reload, and
    disabling an entry that's waiting to retry its setup unloads nothing."""

    @callback
    def entry_changed(change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if change is ConfigEntryChange.UPDATED and entry.domain == DOMAIN:
            async_entry_changed(hass)

    async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, entry_changed)


async def async_add_entry_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Note an entry that was set up, and bring the sidebar up to date."""
    hass.data.setdefault(DATA, PanelState()).entries.add(entry.entry_id)
    await _async_sync_safely(hass)


async def async_remove_entry_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Bring the sidebar up to date after an entry unloaded.

    The entry keeps its place, as an entry usually unloads to reload. Home
    Assistant disables an entry before unloading it, so a disabled one leaves
    now; a removed one leaves once it's gone (async_forget_entry_panel).
    """
    if DATA in hass.data:
        await _async_sync_safely(hass)


async def async_forget_entry_panel(hass: HomeAssistant, entry_id: str) -> None:
    """Forget an entry that was removed, and bring the sidebar up to date."""
    state = hass.data.get(DATA)
    if state is not None and entry_id in state.entries:
        state.entries.discard(entry_id)
        await _async_sync_safely(hass)


@callback
def async_entry_changed(hass: HomeAssistant) -> None:
    """An entry's state or options changed: update the sidebar, and open panels."""
    if DATA in hass.data:
        hass.async_create_task(_async_sync_safely(hass), "BRUH Cooking sidebar panel")
    async_dispatcher_send(hass, SIGNAL_ENTRY_STATE)


async def _async_sync_safely(hass: HomeAssistant) -> None:
    try:
        async with hass.data[DATA].lock:
            await _async_sync(hass)
    except Exception:
        _LOGGER.exception("Could not update the BRUH Cooking sidebar panel")


async def _async_sync(hass: HomeAssistant) -> None:
    """Register the panel while an entry shows it, and remove it once none does."""
    state = hass.data[DATA]
    entries = panel_entries(hass)
    title = panel_title(entries)
    if state.module_url is not None and (not entries or state.title != title):
        # Gone, or registered again with the new title: Home Assistant doesn't
        # rename a registered panel.
        state.module_url = state.title = None
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    if not entries or state.module_url is not None or not await _async_serve(hass, state):
        return
    # A new URL for every build, not just every release, so a browser never
    # keeps an old copy, even of a test build that still carries the last
    # release's version.
    module_url = f"{STATIC_URL}/{BUNDLE}?v={integration_version(hass)}-{state.bundle_hash}"
    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_ELEMENT,
            sidebar_title=title,
            sidebar_icon=PANEL_ICON,
            module_url=module_url,
            require_admin=False,
        )
    except Exception:
        # Nothing is recorded, so the next entry set up tries again.
        _LOGGER.exception("Could not add the BRUH Cooking panel to the sidebar")
        return
    state.module_url = module_url
    state.title = title


async def _async_serve(hass: HomeAssistant, state: PanelState) -> bool:
    """Read the bundle's hash and serve its folder, once per process; whether that worked."""
    if not state.bundle_read:
        state.bundle_read = True
        path = FRONTEND_DIR / BUNDLE
        state.bundle_hash = await hass.async_add_executor_job(bundle_hash, path)
        if state.bundle_hash is None:
            _LOGGER.warning("Not showing the BRUH Cooking sidebar panel: %s is missing", path)
    if state.bundle_hash is None:
        return False
    if state.served:
        return True
    http = getattr(hass, "http", None)
    if http is None:
        # Without the HTTP integration, as in tests, there's no frontend to load it either.
        return True
    try:
        # Cached for good: each build has its own URL.
        await http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=True)]
        )
    except Exception:
        # The panel would only fail to load, so it waits for the next try.
        _LOGGER.exception("Could not serve the BRUH Cooking sidebar panel's files")
        return False
    state.served = True
    return True
