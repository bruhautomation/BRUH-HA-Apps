"""Serving Morph's panel modules, with this house's changes in place.

Morph's own code is the house's to change (the add-on's ``morphcode.py``):
brAIn copies a module into /config/morph/frontend/ and changes the copy.
So the panel's modules are not a plain static folder. Under
``/morph_static/<VERSION>/``:

* ``<name>.js`` is this house's copy when the add-on's ``code.json`` lists
  it as in use, and Morph's own otherwise;
* ``shipped/<name>.js`` is always Morph's own, which is what ``boot.js``
  loads when a changed copy fails to load;
* ``boot.js`` is never replaced: it is the loader that falls back, and
  neither is ``shell.js``, brAIn's sidebar entry;
* ``s/<stamp>/<name>.js`` is the same file as ``<name>.js``, under a name
  for the exact code being served (``stamp``).

``boot.js`` is the one file the browser asks after on every load, and it is
served with ``STAMP`` and ``MODULES`` written in. The panel's modules are
then fetched under ``s/<stamp>/``: while that stamp is the current one, the
answer can never change, so it is cached for good and the next load costs
no module requests at all. Revalidating seven ``no-cache`` modules one
import level at a time was most of why Morph opened slowly. A stamp that is
no longer current (a page opened before a change) is still answered, with
today's file and ``no-cache``. Everything else is ``no-cache``, because one
URL can hold two different files. The name is checked against one pattern
before it becomes a path, and only files directly in the two folders are
served.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import CODE_DIR, CODE_STATE, FRONTEND_DIR, STATIC_BASE, VERSION

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\.js$")
# The shell and the loader are never a house's copy: they are what opens
# brAIn at all, and what falls back when a copy breaks.
FIXED = ("boot.js", "shell.js")
HEADERS = {"Cache-Control": "no-cache"}
FOREVER = {"Cache-Control": "public, max-age=31536000, immutable"}
STAMP_RE = re.compile(r"^[0-9a-f]{12}$")
JS = "text/javascript; charset=utf-8"


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


def modules(*, frontend: Path = FRONTEND_DIR, code_dir: Path = CODE_DIR, code_state: Path = CODE_STATE) -> list[str]:
    """Every module the panel may import: Morph's own and this house's
    copies in use, never ``boot.js``."""
    names = {p.name for p in frontend.glob("*.js") if p.is_file()}
    names |= {n for n in in_use(code_state) if (code_dir / n).is_file()}
    return sorted(n for n in names if NAME.match(n) and n not in FIXED)


def stamp(*, frontend: Path = FRONTEND_DIR, code_dir: Path = CODE_DIR, code_state: Path = CODE_STATE) -> str:
    """A name for exactly the code being served: which file answers each
    module, and that file's size and time. Any change to Morph's own files
    (an update) or to which copies are in use moves it."""
    h = hashlib.sha256(VERSION.encode())
    for name in modules(frontend=frontend, code_dir=code_dir, code_state=code_state):
        path = pick(name, False, frontend=frontend, code_dir=code_dir, code_state=code_state)
        try:
            st = path.stat() if path else None
        except OSError:
            st = None
        h.update(f"{name}|{path}|{st.st_mtime_ns if st else 0}|{st.st_size if st else 0}\n".encode())
    return h.hexdigest()[:12]


def boot_source(*, frontend: Path = FRONTEND_DIR, code_dir: Path = CODE_DIR, code_state: Path = CODE_STATE) -> str | None:
    """``boot.js`` with the current stamp and module list written in."""
    try:
        text = (frontend / "boot.js").read_text(encoding="utf-8")
    except OSError:
        return None
    kw = {"frontend": frontend, "code_dir": code_dir, "code_state": code_state}
    text = text.replace("const STAMP = '';", f"const STAMP = {json.dumps(stamp(**kw))};", 1)
    return text.replace("const MODULES = [];", f"const MODULES = {json.dumps(modules(**kw))};", 1)


def stamped(name: str, want: str, **kw) -> tuple[bytes, bool] | None:
    """A module under ``s/<want>/``: its bytes, and whether they are the code
    ``want`` names (and so may be cached for good)."""
    path = pick(name, False, **kw)
    if path is None:
        return None
    before = stamp(**kw)
    try:
        body = path.read_bytes()
    except OSError:
        return None
    # Read between two stamps, so a file written mid-read is never cached
    # for good under a name it does not match.
    return body, before == want == stamp(**kw)


class MorphStaticView(HomeAssistantView):
    # Module scripts are fetched without the frontend's token, like any
    # static path; what is here is panel code, as /morph_cards already is.
    requires_auth = False
    url = STATIC_BASE + "/" + VERSION + "/{name}"
    extra_urls = [STATIC_BASE + "/" + VERSION + "/shipped/{name}",
                  STATIC_BASE + "/" + VERSION + "/s/{code}/{name}"]
    name = "morph:static"

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request: web.Request, name: str, code: str | None = None) -> web.StreamResponse:
        if code is not None:
            if not STAMP_RE.match(code) or name in FIXED:
                raise web.HTTPNotFound()
            got = await self.hass.async_add_executor_job(stamped, name, code)
            if got is None:
                raise web.HTTPNotFound()
            body, current = got
            return web.Response(body=body, headers={**(FOREVER if current else HEADERS), "Content-Type": JS})
        if name == "boot.js" and "/shipped/" not in request.path:
            text = await self.hass.async_add_executor_job(boot_source)
            if text is None:
                raise web.HTTPNotFound()
            return web.Response(text=text, headers={**HEADERS, "Content-Type": JS})
        shipped_only = "/shipped/" in request.path
        path = await self.hass.async_add_executor_job(pick, name, shipped_only)
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": JS})
