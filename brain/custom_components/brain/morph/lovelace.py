"""Home Assistant's own dashboards, changed by brAIn (docs/design/morph-on-lovelace.md §2.1).

A dashboard the household has "Morphed" stays a storage-mode Lovelace
dashboard that Home Assistant draws itself. This is the half that runs in
Core, because only Core can read and save a dashboard:

* **The mirror.** Whenever a Morphed dashboard is saved, by anyone (HA's own
  editor, brAIn, Undo), its config is written to
  ``/config/.morph/lovelace/<key>.json``. Morph's service keeps that as
  ``/config/morph/dashboards/<key>.yaml`` in git: one commit per change.
* **Apply.** When that YAML changes (brAIn edited it in a Tell, a person
  pressed Undo, somebody edited it by hand), the service drops
  ``/config/.morph/lovelace-apply/<key>.json``, and this saves it through
  Home Assistant's own ``LovelaceStorage.async_save``. HA then fires
  ``lovelace_updated``, and every open screen reloads that dashboard in
  place (``ha-panel-lovelace``'s ``_lovelaceChanged``).
* **Which dashboards.** ``/config/.morph/lovelace/morphed.json`` is the list,
  written here only, by an administrator's "Morph this dashboard".

``key`` is the dashboard's url_path, and ``default`` for the default
dashboard (the word brAIn's power tools already use). A YAML-mode dashboard
cannot be Morphed: Home Assistant cannot save it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, SHARED

_LOGGER = logging.getLogger(__name__)

LL_DIR = SHARED / "lovelace"
APPLY_DIR = SHARED / "lovelace-apply"
MORPHED = LL_DIR / "morphed.json"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
APPLY_S = 1
EVENT = "lovelace_updated"


def key_of(url_path: str | None) -> str:
    return url_path or "default"


def url_of(key: str) -> str | None:
    return None if key == "default" else key


def config_hash(config) -> str:
    """The same hash the service computes (lovelace.py there): canonical
    JSON, so a config read back unchanged is never a change."""
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}")
    scratch.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    scratch.replace(path)


def read_morphed(path: Path = MORPHED) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = data.get("keys") if isinstance(data, dict) else None
    return [k for k in keys if isinstance(k, str) and KEY_RE.match(k)] if isinstance(keys, list) else []


def write_morphed(keys: list[str], path: Path = MORPHED) -> None:
    _write_json(path, {"keys": sorted(set(keys)), "at": time.time()})


def dashboards(hass: HomeAssistant) -> dict:
    """Home Assistant's dashboards by url_path (None is the default). Read
    the way brAIn's power tools read them: a dataclass from 2024.x, a dict
    before it."""
    data = hass.data.get("lovelace")
    if data is None:
        return {}
    found = getattr(data, "dashboards", None)
    if found is None and isinstance(data, dict):
        found = data.get("dashboards")
    return found if isinstance(found, dict) else {}


def _dashboard(hass: HomeAssistant, key: str):
    boards = dashboards(hass)
    url = url_of(key)
    if url in boards:
        return boards[url]
    # The default dashboard migrated to a "lovelace" entry on newer cores.
    if key == "default" and "lovelace" in boards:
        return boards["lovelace"]
    return None


def mode_of(board) -> str:
    return str(getattr(board, "mode", "storage") or "storage")


def describe(hass: HomeAssistant) -> list[dict]:
    """Every dashboard, for the layer's menu and brAIn's ⚙ › Dashboard."""
    morphed = set(read_morphed())
    out = []
    for url, board in dashboards(hass).items():
        key = key_of(url)
        cfg = getattr(board, "config", None) or {}
        title = (cfg.get("title") if isinstance(cfg, dict) else None) or ("Overview" if url in (None, "lovelace") else url)
        out.append({"key": key, "url_path": url or "lovelace", "title": title, "mode": mode_of(board),
                    "icon": cfg.get("icon") if isinstance(cfg, dict) else None, "morphed": key in morphed})
    out.sort(key=lambda d: (d["key"] != "default", str(d["title"]).lower()))
    return out


async def load_config(hass: HomeAssistant, key: str):
    """The dashboard's config, or None when it has none yet (an untouched
    default dashboard is generated by the frontend, not stored)."""
    board = _dashboard(hass, key)
    if board is None:
        return None
    try:
        return await board.async_load(False)
    except Exception:  # noqa: BLE001 — ConfigNotFound and its kin: nothing stored
        return None


async def mirror(hass: HomeAssistant, key: str) -> dict | None:
    """Write what Home Assistant holds now for one Morphed dashboard."""
    board = _dashboard(hass, key)
    if board is None:
        return None
    cfg = await load_config(hass, key)
    row = {"key": key, "mode": mode_of(board), "config": cfg,
           "hash": config_hash(cfg) if cfg is not None else "", "at": time.time()}
    await hass.async_add_executor_job(_write_json, LL_DIR / f"{key}.json", row)
    return row


async def apply_pending(hass: HomeAssistant) -> list[str]:
    """Save every config the service asked for, through HA's own storage."""
    def _list() -> list[tuple[Path, dict]]:
        out = []
        try:
            files = sorted(APPLY_DIR.glob("*.json"))
        except OSError:
            return out
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                if time.time() - f.stat().st_mtime > 10:
                    f.unlink(missing_ok=True)
                continue
            out.append((f, data if isinstance(data, dict) else {}))
        return out

    done = []
    morphed = set(await hass.async_add_executor_job(read_morphed))
    for f, data in await hass.async_add_executor_job(_list):
        key = str(data.get("key") or "")
        cfg = data.get("config")
        await hass.async_add_executor_job(lambda p=f: p.unlink(missing_ok=True))
        if key not in morphed or not isinstance(cfg, dict):
            continue
        board = _dashboard(hass, key)
        if board is None or mode_of(board) != "storage":
            continue
        try:
            await board.async_save(cfg)
            done.append(key)
        except Exception as exc:  # noqa: BLE001 — said in the mirror, never a crash
            _LOGGER.warning("brAIn could not save dashboard %s: %s", key, exc)
            await hass.async_add_executor_job(_write_json, LL_DIR / f"{key}.error.json",
                                              {"error": str(exc)[:300], "at": time.time()})
            continue
        await mirror(hass, key)
    return done


async def set_morphed(hass: HomeAssistant, key: str, on: bool) -> dict:
    board = _dashboard(hass, key)
    if board is None:
        return {"ok": False, "error": "There is no such dashboard."}
    if on and mode_of(board) != "storage":
        return {"ok": False, "error": "This dashboard is kept in YAML files, which Home Assistant cannot "
                                      "save. brAIn can change dashboards made in Home Assistant's own editor."}
    keys = set(await hass.async_add_executor_job(read_morphed))
    keys.add(key) if on else keys.discard(key)
    await hass.async_add_executor_job(write_morphed, sorted(keys))
    hass.data.setdefault(DOMAIN, {})["morphed"] = keys
    if on:
        await mirror(hass, key)
    return {"ok": True, "morphed": on}


# -------------------------------------------------------------- websocket

@websocket_api.websocket_command({vol.Required("type"): "morph/dashboards"})
@websocket_api.async_response
async def ws_dashboards(hass: HomeAssistant, connection, msg) -> None:
    connection.send_result(msg["id"], {"dashboards": await hass.async_add_executor_job(describe, hass),
                                       "admin": bool(connection.user and connection.user.is_admin)})


@websocket_api.websocket_command({vol.Required("type"): "morph/dashboard_morph",
                                  vol.Required("key"): str, vol.Required("on"): bool})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dashboard_morph(hass: HomeAssistant, connection, msg) -> None:
    key = msg["key"]
    if not KEY_RE.match(key):
        connection.send_error(msg["id"], "invalid", "Not a dashboard")
        return
    connection.send_result(msg["id"], await set_morphed(hass, key, msg["on"]))


def start(hass: HomeAssistant) -> Callable[[], None]:
    """Mirror every Morphed dashboard now and whenever HA saves one, and
    apply what the service asks for. Returns the teardown."""
    data = hass.data.setdefault(DOMAIN, {})

    async def _all() -> None:
        for key in await hass.async_add_executor_job(read_morphed):
            await mirror(hass, key)

    # The list as last read: the event handler runs on the loop and must
    # not read a file there.
    data["morphed"] = set()

    @callback
    def _updated(event) -> None:
        key = key_of((event.data or {}).get("url_path"))
        if key in data["morphed"]:
            hass.async_create_task(mirror(hass, key))

    async def _tick(_now=None) -> None:
        data["morphed"] = set(await hass.async_add_executor_job(read_morphed))
        await apply_pending(hass)

    hass.async_create_task(_all())
    unsub_event = hass.bus.async_listen(EVENT, _updated)
    unsub_tick = async_track_time_interval(hass, _tick, timedelta(seconds=APPLY_S))
    if not data.get("ll_ws"):
        from . import eyes  # noqa: PLC0415 — eyes reads this module's dashboards
        for handler in (ws_dashboards, ws_dashboard_morph, eyes.ws_eyes):
            websocket_api.async_register_command(hass, handler)
        data["ll_ws"] = True

    @callback
    def _stop() -> None:
        unsub_event()
        unsub_tick()

    return _stop
