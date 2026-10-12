"""Serving Morph's panel modules, with this house's changes in place.

Morph's own code is the house's to change (the add-on's ``morphcode.py``):
brAIn copies a module into /config/morph/frontend/ and changes the copy.
So the panel's modules are not a plain static folder. Under
``/morph_static/<VERSION>/``:

* ``<name>.js`` is this house's copy when the add-on's ``code.json`` lists
  it as in use, and Morph's own otherwise;
* ``shipped/<name>.js`` is always Morph's own, which is what ``boot.js``
  loads when a changed copy fails to load;
* ``boot.js`` is never replaced: it is the loader that falls back.

Every answer says ``no-cache`` (the browser revalidates, and gets a 304 when
nothing moved), because one URL can now hold two different files. The name
is checked against one pattern before it becomes a path, and only files
directly in the two folders are served.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import CODE_DIR, CODE_STATE, FRONTEND_DIR, STATIC_BASE, VERSION

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\.js$")
FIXED = ("boot.js",)
HEADERS = {"Cache-Control": "no-cache"}


def in_use(code_state: Path = CODE_STATE) -> set[str]:
    """The copies the add-on says are in use. Unreadable is none: serving
    Morph's own is always a working panel."""
    try:
        data = json.loads(code_state.read_text(encoding="utf-8"))
        return {str(r["name"]) for r in data.get("files") or []
                if isinstance(r, dict) and r.get("status") == "active" and NAME.match(str(r.get("name") or ""))}
    except (OSError, ValueError, TypeError, KeyError):
        return set()


def pick(name: str, shipped_only: bool, *, frontend: Path = FRONTEND_DIR, code_dir: Path = CODE_DIR,
         code_state: Path = CODE_STATE) -> Path | None:
    """The file to serve for ``name``, or None for a 404."""
    if not NAME.match(name or ""):
        return None
    if not shipped_only and name not in FIXED and name in in_use(code_state):
        own = code_dir / name
        if own.is_file():
            return own
    path = frontend / name
    return path if path.is_file() else None


class MorphStaticView(HomeAssistantView):
    # Module scripts are fetched without the frontend's token, like any
    # static path; what is here is panel code, as /morph_cards already is.
    requires_auth = False
    url = STATIC_BASE + "/" + VERSION + "/{name}"
    extra_urls = [STATIC_BASE + "/" + VERSION + "/shipped/{name}"]
    name = "morph:static"

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request: web.Request, name: str) -> web.StreamResponse:
        shipped_only = "/shipped/" in request.path
        path = await self.hass.async_add_executor_job(pick, name, shipped_only)
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "text/javascript; charset=utf-8"})
