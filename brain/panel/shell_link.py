"""brAIn's page inside the shell, and whose sidebar entry is showing.

Since 4.0 brAIn's sidebar entry is the integration's custom panel, the
shell (`custom_components/brain/morph/frontend/shell.js`): it holds the
Morph dashboard as its Home tab and this page in a frame. Two things make
that work, and both are here:

* **The shell has to find this page.** The ingress URL is the Supervisor's
  to hand out (`/api/hassio_ingress/<token>/`), and only this add-on can
  read it, so it is written to `/config/.brain/ingress.json` for the
  integration to pass on (`brain/shell`).
* **One sidebar entry, never none.** While the shell is registered the
  integration rewrites `/config/.brain/shell.json` every few minutes, and
  this add-on hides its own ingress entry (the Supervisor's
  `ingress_panel`). The moment that mark is stale — Home Assistant did not
  load the integration, or was restarted without it — the entry is put
  back. Only a hide this module made is ever undone (`/data/ingress_hidden
  .json`): somebody who hid the entry themselves keeps it hidden.
"""
from __future__ import annotations

import json
import logging
import os
import time

import atomic_write

log = logging.getLogger("brain.shell")

SHARED = os.environ.get("BRAIN_SHARED_DIR", "/config/.brain")
INGRESS_FILE = os.path.join(SHARED, "ingress.json")
SHELL_FILE = os.path.join(SHARED, "shell.json")
HIDDEN_FILE = os.environ.get("BRAIN_INGRESS_HIDDEN_FILE", "/data/ingress_hidden.json")

# The integration rewrites the mark every 240s; three missed beats is gone.
SHELL_STALE_S = 900
SHELL_URL = "brain"


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def shell_fresh(now: float | None = None, path: str | None = None) -> bool:
    """Whether the shell panel is registered right now, by its mark."""
    mark = _read(path or SHELL_FILE)
    at = mark.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return False
    return 0 <= (now or time.time()) - at <= SHELL_STALE_S


def write_ingress(info: dict, path: str | None = None) -> bool:
    """Write what the Supervisor said about this page, when it changed."""
    target = path or INGRESS_FILE
    body = {k: info.get(k) for k in ("ingress_url", "slug") if info.get(k)}
    if not body.get("ingress_url") or not os.path.isdir(os.path.dirname(target) or "."):
        return False
    if {k: _read(target).get(k) for k in body} == body:
        return False
    atomic_write.write_json(target, body)
    return True


def decide(shown: bool | None, fresh: bool, we_hid: bool) -> bool | None:
    """What the ingress entry should become, or None to leave it.

    Hide it while the shell is there and it is showing; show it again when
    the shell is not there, but only when the hide was ours."""
    if shown is None:
        return None
    if fresh and shown:
        return False
    if not fresh and not shown and we_hid:
        return True
    return None


def we_hid(path: str | None = None) -> bool:
    return _read(path or HIDDEN_FILE).get("hidden") is True


def note_hidden(hidden: bool, path: str | None = None) -> None:
    target = path or HIDDEN_FILE
    try:
        if hidden:
            atomic_write.write_json(target, {"hidden": True, "at": int(time.time())})
        elif os.path.exists(target):
            os.unlink(target)
    except OSError:
        log.warning("could not record the ingress entry's state in %s", target)


async def sync(options_mod) -> str:
    """One pass: refresh what the Supervisor says, publish the page's
    address, and show or hide the ingress entry. Returns what it did, for
    the log and a test."""
    if not options_mod.available():
        return "no supervisor"
    await options_mod.refresh()
    info = options_mod.ingress()
    write_ingress(info)
    want = decide(info.get("ingress_panel"), shell_fresh(), we_hid())
    if want is None:
        return "unchanged"
    try:
        await options_mod.set_ingress_panel(want)
    except options_mod.OptionsError as exc:
        log.warning("could not %s brAIn's own sidebar entry: %s", "show" if want else "hide", exc)
        return "failed"
    note_hidden(not want)
    log.info("%s brAIn's own sidebar entry: %s", "Showed" if want else "Hid",
             "the brAIn panel is not registered" if want else "the brAIn panel is the one entry now")
    return "shown" if want else "hidden"
