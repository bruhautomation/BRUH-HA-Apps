"""Morph's half of the brAIn integration, and the one sidebar entry.

Morph was an add-on and an integration of its own until brAIn 4.0
(docs/design/brain-morph-merge.md). Its service runs in brAIn's container
now; this is the half that has to run inside Home Assistant: the panel's
modules and the dashboard's card code (static.py), the panel's websocket
commands (websocket.py), and the sidebar entry itself.

The sidebar entry is brAIn's SHELL (`frontend/shell.js`): a custom panel,
because Morph hosts Lovelace cards with the live ``hass``, which only a page
inside Home Assistant's own frontend has. It holds brAIn's own page in a
frame (Insights, Ask, Memory, Settings) and Morph drawn natively as the
Home tab while the Morph dashboard is switched on. The panel is registered
whatever the switch says, and re-registered when the switch or the
assistant's name changes, so the sidebar always says the name the house
gave brAIn.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import timedelta

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from . import websocket
from .switches import read_features
from .const import (
    CARDS_DIR,
    CARDS_URL,
    DOMAIN,
    ELEMENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    SHELL_BEAT_S,
    SHELL_MARK,
    STATIC_BASE,
    VERSION,
)

FEATURE_POLL_S = 5


def panel_spec(features: dict) -> dict:
    """What the sidebar entry is for these switches: the title is the
    assistant's name, and with the dashboard off the panel is brAIn's alone,
    which was always administrators only."""
    return {
        "title": features.get("name") or PANEL_TITLE,
        "require_admin": not features.get("morph"),
    }


def _panel_config(features: dict) -> dict:
    return {
        "version": VERSION,
        "cards_url": CARDS_URL,
        "morph": bool(features.get("morph")),
        "_panel_custom": {
            "name": ELEMENT,
            "embed_iframe": False,
            "trust_external": False,
            # shell.js loads Morph's boot.js, which loads Morph's own copy
            # when a changed one fails.
            "module_url": f"{STATIC_BASE}/{VERSION}/shell.js",
        },
    }


@callback
def _register_panel(hass: HomeAssistant, features: dict, update: bool) -> None:
    spec = panel_spec(features)
    kw = dict(component_name="custom", sidebar_title=spec["title"], sidebar_icon=PANEL_ICON,
              frontend_url_path=PANEL_URL, config=_panel_config(features),
              require_admin=spec["require_admin"])
    if not update:
        try:
            frontend.async_register_built_in_panel(hass, **kw)
            return
        except ValueError:
            # Still registered from before a reload of the entry: replace it.
            pass
    try:
        frontend.async_register_built_in_panel(hass, **kw, update=True)
    except TypeError:
        # A core without `update`: take it down and put it back.
        frontend.async_remove_panel(hass, PANEL_URL)
        frontend.async_register_built_in_panel(hass, **kw)


def write_mark(path=SHELL_MARK) -> None:
    """Say the shell is registered, so brAIn may hide its own ingress
    entry. Never raises: a mark that could not be written only means the
    ingress entry stays, which is a second way in, not none."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_name(f".{path.name}.{time.time_ns()}")
        scratch.write_text(json.dumps({"url": PANEL_URL, "at": int(time.time()), "version": VERSION}),
                           encoding="utf-8")
        scratch.replace(path)
    except OSError:
        pass  # the ingress entry stays; see the docstring


def clear_mark(path=SHELL_MARK) -> None:
    try:
        path.unlink()
    except OSError:
        pass  # never written, or already gone


async def _register_static(hass: HomeAssistant) -> None:
    """Static paths cannot be unregistered, so this runs once per process.

    The panel's modules are served under a VERSIONED path so their relative
    imports carry the version too: a cache that held last release's
    engine.js beside this release's panel is the bug a query string on the
    entry module alone does not prevent. They come through a view rather
    than a static folder, because a module may be this house's own copy
    (static.py). The dashboard's own card code is served uncached, because
    brAIn rewrites it while somebody is looking.
    """
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("static"):
        return
    from .static import MorphStaticView
    cards_dir = str(CARDS_DIR)
    await hass.async_add_executor_job(lambda: CARDS_DIR.mkdir(parents=True, exist_ok=True))
    try:
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([
            StaticPathConfig(CARDS_URL, cards_dir, False),
        ])
    except ImportError:  # a core before 2024.7
        hass.http.register_static_path(CARDS_URL, cards_dir, False)
    hass.http.register_view(MorphStaticView(hass))
    data["static"] = True


async def async_setup(hass: HomeAssistant) -> Callable[[], None]:
    """Set Morph's half up once for the process; returns the teardown."""
    data = hass.data.setdefault(DOMAIN, {})
    await _register_static(hass)
    websocket.async_register(hass)
    features = await hass.async_add_executor_job(read_features)
    data["features"] = features
    _register_panel(hass, features, update=False)
    await hass.async_add_executor_job(write_mark)
    data["mark_at"] = time.time()
    unsub_watch = websocket.start_watcher(hass)

    async def _poll(_now=None) -> None:
        now = await hass.async_add_executor_job(read_features)
        if panel_spec(now) != panel_spec(data.get("features") or {}) or \
                now.get("morph") != (data.get("features") or {}).get("morph"):
            _register_panel(hass, now, update=True)
            websocket.notify(hass, ("features",))
        data["features"] = now
        if time.time() - data.get("mark_at", 0) >= SHELL_BEAT_S:
            await hass.async_add_executor_job(write_mark)
            data["mark_at"] = time.time()

    unsub_poll = async_track_time_interval(hass, _poll, timedelta(seconds=FEATURE_POLL_S))

    @callback
    def _teardown() -> None:
        unsub_watch()
        unsub_poll()
        frontend.async_remove_panel(hass, PANEL_URL)
        hass.async_add_executor_job(clear_mark)

    return _teardown


async def async_retire_morph_entries(hass: HomeAssistant) -> int:
    """Remove the config entry the retired `morph` integration left behind.

    Its files are gone (brAIn's run.sh deletes them), so the entry can only
    ever fail to load and sit on Settings › Devices & services as an error
    about an integration that no longer exists."""
    removed = 0
    for entry in list(hass.config_entries.async_entries("morph")):
        await hass.config_entries.async_remove(entry.entry_id)
        removed += 1
    return removed
