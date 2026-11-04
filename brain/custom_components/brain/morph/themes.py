"""Home Assistant themes kept with the dashboard (docs/design/morph-on-lovelace.md §2.6).

``/config/morph/themes/*.yaml`` are ordinary Home Assistant theme files
(``Name: {var: value, modes: {light: …, dark: …}}``), kept in Morph's git
history so a theme change is a commit and Undo puts it back. They are added
to the themes Home Assistant already has (its ``frontend: themes:`` config
is untouched), and every open screen repaints the moment one changes:
Home Assistant's own ``themes_updated`` event, which the frontend answers by
asking for the themes again. ``frontend.reload_themes`` replaces the themes
with configuration.yaml's, so they are added again right after it.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, MORPH_DIR

_LOGGER = logging.getLogger(__name__)

THEMES_DIR = MORPH_DIR / "themes"
EVENT = "themes_updated"
POLL_S = 3
MAX_FILE = 256 * 1024


def data_key():
    """The key Home Assistant's frontend keeps its themes under (a HassKey
    on newer cores, the plain string before)."""
    try:
        from homeassistant.components import frontend
        return getattr(frontend, "DATA_THEMES", "frontend_themes")
    except ImportError:
        return "frontend_themes"


def stamp(themes_dir: Path = THEMES_DIR) -> tuple:
    try:
        return tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in themes_dir.glob("*.yaml")))
    except OSError:
        return ()


def read_themes(themes_dir: Path = THEMES_DIR) -> tuple[dict, list[str]]:
    """(themes by name, problems in words). A file that does not read is
    left out and said; the others still load."""
    import yaml
    themes: dict = {}
    problems: list[str] = []
    try:
        files = sorted(themes_dir.glob("*.yaml"))
    except OSError:
        return themes, problems
    for f in files:
        try:
            if f.stat().st_size > MAX_FILE:
                problems.append(f"{f.name}: too large")
                continue
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — a YAML error, said
            problems.append(f"{f.name}: {str(exc)[:160]}")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{f.name}: a theme file is a mapping of theme names")
            continue
        for name, theme in raw.items():
            if isinstance(name, str) and isinstance(theme, dict):
                themes[name[:60]] = theme
            else:
                problems.append(f"{f.name}: {name!r} is not a theme")
    return themes, problems


@callback
def inject(hass: HomeAssistant, themes: dict, fire: bool) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    key = data_key()
    current = hass.data.get(key)
    if not isinstance(current, dict):
        current = {}
        hass.data[key] = current
    for name in data.get("themes_ours", set()) - set(themes):
        current.pop(name, None)
    current.update(themes)
    data["themes_ours"] = set(themes)
    if fire:
        data["themes_firing"] = True
        hass.bus.async_fire(EVENT)
        data["themes_firing"] = False


def start(hass: HomeAssistant) -> Callable[[], None]:
    data = hass.data.setdefault(DOMAIN, {})
    data["themes_stamp"] = None

    async def _tick(_now=None) -> None:
        now = await hass.async_add_executor_job(stamp)
        if now == data.get("themes_stamp"):
            return
        first = data.get("themes_stamp") is None
        data["themes_stamp"] = now
        themes, problems = await hass.async_add_executor_job(read_themes)
        data["themes"] = themes
        data["theme_problems"] = problems
        for p in problems:
            _LOGGER.warning("brAIn theme %s", p)
        inject(hass, themes, fire=not first or bool(themes))

    @callback
    def _reloaded(_event) -> None:
        # Home Assistant's own reload put configuration.yaml's themes back:
        # add ours again before any screen asks for them.
        if not data.get("themes_firing"):
            inject(hass, data.get("themes") or {}, fire=False)

    unsub_event = hass.bus.async_listen(EVENT, _reloaded)
    unsub_tick = async_track_time_interval(hass, _tick, timedelta(seconds=POLL_S))
    hass.async_create_task(_tick())

    @callback
    def _stop() -> None:
        unsub_event()
        unsub_tick()
        inject(hass, {}, fire=True)

    return _stop
