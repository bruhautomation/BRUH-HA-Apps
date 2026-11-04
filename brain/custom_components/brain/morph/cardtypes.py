"""Card types: a card brAIn builds once and every dashboard uses (docs/design/morph-on-lovelace.md §2.3).

A type is ``/config/morph/types/<slug>.yaml``, and for a card no existing
card can draw, ``<slug>.js`` beside it:

```yaml
name: Thermostat with buttons       # what HA's card picker shows, after "Morph · "
description: A thermostat and the scripts that go with it.
kind: template                      # template (a Lovelace card with [[variables]]) or element (<slug>.js)
variables:                          # what one copy sets; HA's visual editor draws these
  - name: entity
    label: Thermostat
    required: true
    selector: {entity: {filter: [{domain: climate}]}}
card:                               # template only: any Lovelace config, built-in or HACS
  type: vertical-stack
  cards:
    - type: thermostat
      entity: "[[entity]]"
```

Every type is the custom card ``custom:morph-type-<slug>`` (morph-types.js
in the browser), so a copy on any dashboard draws the type as it is NOW:
change the file and every copy, on every dashboard, changes with it. This
reads the folder for the browser (``morph/types``) and serves the element
code under ``/morph_types/``.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import CARDS_DIR, DOMAIN, MORPH_DIR, SHARED

TYPES_DIR = MORPH_DIR / "types"
TYPES_URL = "/morph_types"
USAGE = SHARED / "types-usage.json"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
KINDS = ("template", "element")
MAX_FILE = 256 * 1024
MAX_TYPES = 200


def _load_yaml(text: str):
    import yaml  # Home Assistant ships PyYAML
    return yaml.safe_load(text)


def clean_variables(raw) -> list[dict]:
    out = []
    for v in raw if isinstance(raw, list) else []:
        if not isinstance(v, dict) or not isinstance(v.get("name"), str):
            continue
        name = v["name"].strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,39}", name) or name == "type":
            continue
        row = {"name": name, "selector": v.get("selector") if isinstance(v.get("selector"), dict) else {"text": {}}}
        if v.get("label"):
            row["label"] = str(v["label"])[:80]
        if v.get("helper"):
            row["helper"] = str(v["helper"])[:200]
        if v.get("required"):
            row["required"] = True
        if "default" in v:
            row["default"] = v["default"]
        out.append(row)
    return out[:30]


def read_type(path: Path) -> dict:
    """One type as the browser needs it, or a row saying what is wrong."""
    slug = path.stem
    row: dict = {"slug": slug, "type": f"custom:morph-type-{slug}"}
    try:
        st = path.stat()
        if st.st_size > MAX_FILE:
            return {**row, "error": "The file is too large."}
        raw = _load_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {**row, "error": f"Could not be read: {exc}"}
    except Exception as exc:  # noqa: BLE001 — a YAML error, said to the person
        return {**row, "error": f"Does not read as YAML: {str(exc)[:200]}"}
    if not isinstance(raw, dict):
        return {**row, "error": "A card type is a mapping (name, kind, variables, card)."}
    kind = raw.get("kind") or ("element" if (path.with_suffix(".js")).exists() else "template")
    if kind not in KINDS:
        return {**row, "error": f"kind must be template or element, not {kind!r}."}
    row.update(name=str(raw.get("name") or slug)[:60], description=str(raw.get("description") or "")[:300],
               kind=kind, variables=clean_variables(raw.get("variables")), rev=int(st.st_mtime))
    if isinstance(raw.get("grid"), dict):
        row["grid"] = {k: raw["grid"][k] for k in ("columns", "rows", "min_columns", "min_rows")
                       if isinstance(raw["grid"].get(k), (int, str))}
    if kind == "template":
        if not isinstance(raw.get("card"), dict) or not raw["card"].get("type"):
            return {**row, "error": "A template type needs `card:` with a `type:`."}
        row["card"] = raw["card"]
    else:
        js = path.with_suffix(".js")
        try:
            row["module"] = f"{TYPES_URL}/{slug}.js?v={int(js.stat().st_mtime)}"
            row["rev"] = max(row["rev"], int(js.stat().st_mtime))
        except OSError:
            return {**row, "error": f"An element type needs its code in types/{slug}.js."}
    return row


def read_all(types_dir: Path = TYPES_DIR, usage: Path = USAGE, cards_dir: Path = CARDS_DIR) -> dict:
    rows = []
    try:
        files = sorted(types_dir.glob("*.yaml"))
    except OSError:
        files = []
    for f in files[:MAX_TYPES]:
        if SLUG_RE.match(f.stem):
            rows.append(read_type(f))
    try:
        used = json.loads(usage.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        used = {}
    counts = used.get("types") if isinstance(used, dict) else None
    for r in rows:
        r["used"] = (counts or {}).get(r["slug"], [])
    # This house's own card code (cards/*.js), loaded on dashboards too.
    modules = []
    try:
        for f in sorted(cards_dir.glob("*.js")):
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}\.js", f.name):
                modules.append(f"/morph_cards/{f.name}?v={int(f.stat().st_mtime)}")
    except OSError:
        pass  # no cards folder is no house cards
    return {"types": rows, "modules": modules, "at": time.time()}


def stamp(types_dir: Path = TYPES_DIR, usage: Path = USAGE, cards_dir: Path = CARDS_DIR) -> float:
    """Moves whenever a type, its code, the usage index or a house card does."""
    best = 0.0
    for d, pat in ((types_dir, "*"), (cards_dir, "*.js")):
        try:
            best = max([best, d.stat().st_mtime] + [f.stat().st_mtime for f in d.glob(pat)])
        except OSError:
            pass  # a folder not made yet moves nothing
    try:
        best = max(best, usage.stat().st_mtime)
    except OSError:
        pass  # no usage index yet
    return best


@websocket_api.websocket_command({vol.Required("type"): "morph/types"})
@websocket_api.async_response
async def ws_types(hass: HomeAssistant, connection, msg) -> None:
    connection.send_result(msg["id"], await hass.async_add_executor_job(read_all))


def module_path(name: str, types_dir: Path = TYPES_DIR) -> Path | None:
    """An element type's code, by ``<slug>.js`` only: the folder's YAML is
    not served (module scripts are fetched without the frontend's token)."""
    if not name.endswith(".js") or not SLUG_RE.match(name[:-3]):
        return None
    path = types_dir / name
    return path if path.is_file() else None


def _view():
    from aiohttp import web
    from homeassistant.components.http import HomeAssistantView

    class MorphTypesView(HomeAssistantView):
        requires_auth = False
        url = TYPES_URL + "/{name}"
        name = "morph:types"

        def __init__(self, hass) -> None:
            self.hass = hass

        async def get(self, request, name: str):
            path = await self.hass.async_add_executor_job(module_path, name)
            if path is None:
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers={"Cache-Control": "no-cache",
                                                   "Content-Type": "text/javascript; charset=utf-8"})
    return MorphTypesView


async def async_setup(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("types_ready"):
        return
    await hass.async_add_executor_job(lambda: TYPES_DIR.mkdir(parents=True, exist_ok=True))
    hass.http.register_view(_view()(hass))
    websocket_api.async_register_command(hass, ws_types)
    data["types_ready"] = True
