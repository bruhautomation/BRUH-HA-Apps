"""Morph's own code, changed by the house it runs in.

Morph is a dashboard brAIn designs, and the point of that is that nothing
about it is out of reach: not the dashboard file, and not the panel either
(its header, its layout engine, a built-in card type, its styles). So the
panel's own modules can be replaced one file at a time:

* brAIn copies a module from Morph's own copy (``paths.SHIPPED``, the
  frontend Home Assistant is serving) into ``/config/morph/frontend/`` under
  the same name and edits the copy. The integration serves that copy in
  place of Morph's own (``custom_components/morph/static.py``), and a page
  reload picks it up.
* It lives in Morph's git folder like everything else, so the change is one
  commit and the person's Undo puts Morph's own back.
* ``.base.json`` records which version of Morph's own file each copy was
  last written against (a hash, recorded when the copy changes). When an
  update changes Morph's own file underneath a copy, the copy is PAUSED —
  served as Morph's own until somebody makes the change again on the new
  file — because a copy of last release's module beside this release's
  others is how a working panel breaks on an update.
* A copy that fails to load is replaced by Morph's own for that page load
  (the integration's ``boot.js``), and the panel says so.

``publish`` writes the verdict to ``/config/.morph/code.json``: that file is
the one answer the integration reads to decide what to serve, so the two
halves cannot disagree about which copies are in use.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import paths

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\.js$")
# Never replaceable: the loader that falls back to Morph's own when a copy
# fails, and so the one file that has to keep working.
FIXED = ("boot.js",)
BASE_FILE = ".base.json"


def code_dir() -> Path:
    return paths.MORPH_DIR / "frontend"


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def copies() -> list[Path]:
    d = code_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and NAME_RE.match(p.name) and p.name not in FIXED)


def _bases() -> dict:
    data = paths.read_json(code_dir() / BASE_FILE, {})
    return data if isinstance(data, dict) else {}


def record_bases() -> bool:
    """Note, for every copy that changed since it was last seen, which
    version of Morph's own file it was written against. Called before every
    commit, so the record is committed with the copy and Undo puts both
    back together. Returns whether anything was written."""
    if not code_dir().is_dir():
        return False
    bases = _bases()
    out: dict = {}
    for p in copies():
        own = _sha(p)
        prev = bases.get(p.name) if isinstance(bases.get(p.name), dict) else None
        if prev and prev.get("own") == own:
            out[p.name] = prev
        else:
            out[p.name] = {"own": own, "base": _sha(paths.SHIPPED / p.name), "at": int(time.time())}
    if out == bases:
        return False
    paths.write_json(code_dir() / BASE_FILE, out, indent=1)
    return True


def status() -> list[dict]:
    """Each copy and whether it is in use.

    * ``active``: written against the Morph that is installed, or a module
      of its own that Morph does not ship;
    * ``paused``: Morph's own file changed since the copy was written.
    A copy nobody has recorded yet (brAIn's edit, a moment before Morph
    commits it) was written against what is installed now, so it is active.
    """
    bases = _bases()
    out = []
    for p in copies():
        shipped = paths.SHIPPED / p.name
        rec = bases.get(p.name) if isinstance(bases.get(p.name), dict) else None
        now = _sha(shipped)
        if not shipped.exists():
            state = "active"
            kind = "new"
        elif rec is None or rec.get("own") != _sha(p) or rec.get("base") == now:
            state, kind = "active", "changed"
        else:
            state, kind = "paused", "changed"
        out.append({"name": p.name, "status": state, "kind": kind, "at": (rec or {}).get("at")})
    return out


def publish(version: str) -> list[dict]:
    rows = status()
    paths.write_json(paths.CODE_STATE, {"version": version, "at": time.time(), "files": rows})
    return rows


def reset(name: str) -> tuple[bool, str]:
    """Put Morph's own file back (the copy is removed; the caller commits)."""
    if not NAME_RE.match(name or "") or name in FIXED:
        return False, "That is not one of Morph's files."
    p = code_dir() / name
    if not p.exists():
        return False, "There is no change to that file."
    p.unlink()
    record_bases()
    return True, ""


def redo_words(name: str, version: str) -> str:
    """What brAIn is asked when an update paused a copy."""
    return (f"Morph was updated to {version}, and its own {name} changed underneath your change to it, "
            f"so your change is paused. Your version is /config/morph/frontend/{name}; Morph's new copy is "
            f"{paths.SHIPPED / name}. Make the same change again on top of Morph's new copy and save it as "
            f"/config/morph/frontend/{name}.")
