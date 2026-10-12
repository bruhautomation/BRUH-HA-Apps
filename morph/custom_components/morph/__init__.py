"""Morph: a sidebar dashboard brAIn designs, edits and keeps improving.

This integration is the half of Morph that has to run inside Home
Assistant: it registers the sidebar panel (a custom element in HA's own
frontend, so the page has the live ``hass`` object and Lovelace's card
helpers), serves the panel's modules and the dashboard's own card code, and
answers the panel's websocket commands. Everything that WRITES the
dashboard goes to the add-on, which owns /config/morph and its git history.
"""
from __future__ import annotations


from homeassistant.components import frontend, panel_custom
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from . import websocket
from .const import (
    CARDS_DIR,
    CARDS_URL,
    DOMAIN,
    ELEMENT,
    FRONTEND_DIR,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    STATIC_BASE,
    VERSION,
)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _register_static(hass: HomeAssistant) -> None:
    """Static paths cannot be unregistered, so this runs once per process.

    The panel's modules are served under a VERSIONED path so their relative
    imports carry the version too: a cache that held last release's
    engine.js beside this release's panel is the bug a query string on the
    entry module alone does not prevent. The dashboard's own card code is
    served uncached, because brAIn rewrites it while somebody is looking.
    """
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("static"):
        return
    cards_dir = str(CARDS_DIR)
    await hass.async_add_executor_job(lambda: CARDS_DIR.mkdir(parents=True, exist_ok=True))
    try:
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([
            StaticPathConfig(f"{STATIC_BASE}/{VERSION}", str(FRONTEND_DIR), True),
            StaticPathConfig(CARDS_URL, cards_dir, False),
        ])
    except ImportError:  # a core before 2024.7
        hass.http.register_static_path(f"{STATIC_BASE}/{VERSION}", str(FRONTEND_DIR), True)
        hass.http.register_static_path(CARDS_URL, cards_dir, False)
    data["static"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _register_static(hass)
    websocket.async_register(hass)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=ELEMENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_BASE}/{VERSION}/morph-panel.js",
        embed_iframe=False,
        require_admin=False,
        config={"version": VERSION, "cards_url": CARDS_URL},
    )
    entry.async_on_unload(websocket.start_watcher(hass))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    frontend.async_remove_panel(hass, PANEL_URL)
    return True
