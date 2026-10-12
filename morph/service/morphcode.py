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
# Morph's own file as it was when each copy was written. An update replaces
# Morph's own, so without this a paused copy can only be compared with the
# NEW file, which mixes this house's change with everything the release
# changed; with it, making the change again is a three-way merge.
BASE_DIR = ".base"


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
            shipped = paths.SHIPPED / p.name
            out[p.name] = {"own": own, "base": _sha(shipped), "at": int(time.time())}
            _keep_base(p.name, shipped)
    if out == bases:
        return False
    paths.write_json(code_dir() / BASE_FILE, out, indent=1)
    return True


def _keep_base(name: str, shipped: Path) -> None:
    """Keep Morph's own ``name`` beside the copy written against it (or
    drop a stale one when Morph ships no such file)."""
    kept = code_dir() / BASE_DIR / name
    try:
        if shipped.is_file():
            if _sha(kept) != _sha(shipped):
                kept.parent.mkdir(exist_ok=True)
                paths.write_text(kept, shipped.read_text(encoding="utf-8"))
        else:
            kept.unlink(missing_ok=True)
    except OSError:
        pass  # the record still says which version it was; the redo prompt says the original is missing


def kept_base(name: str) -> Path | None:
    """Morph's own file this copy was written against, when it was kept
    and is the one the record names."""
    rec = _bases().get(name)
    kept = code_dir() / BASE_DIR / name
    if isinstance(rec, dict) and kept.is_file() and _sha(kept) == rec.get("base"):
        return kept
    return None


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
    (code_dir() / BASE_DIR / name).unlink(missing_ok=True)
    record_bases()
    return True, ""


def redo_words(name: str, version: str, history: list[str] | None = None) -> str:
    """What brAIn is asked when an update paused a copy. The first sentence
    is what a person reads where the request is listed."""
    mine = f"/config/morph/frontend/{name}"
    base = kept_base(name)
    lines = [f"Make my change to Morph's {name} again on the new Morph ({version}).",
             f"Morph was updated, its own {name} changed underneath this house's change to it, so the change "
             f"is paused and Morph's own is running.",
             f"- This house's version: {mine}",
             f"- Morph's new {name}: {paths.SHIPPED / name}"]
    if base:
        lines += [f"- Morph's {name} as it was when the change was made: {base}",
                  f"The change is the difference between that file and {mine}. Apply that difference to Morph's "
                  f"new {name} (a three-way merge: keep everything the update changed) and save the result as "
                  f"{mine}."]
    else:
        lines += [f"Morph's {name} from before the update was not kept, so {mine} differs from the new file both "
                  f"by this house's change and by everything the update changed. Work out what the house's "
                  f"change was (the commits below say what it was for), then start from Morph's new {name}, "
                  f"make only that change, and save the result as {mine}. Never copy the old file over the new "
                  f"one: that would undo the update."]
    said = [m for m in (history or []) if m][:6]
    if said:
        lines.append(f"Commits that changed {mine}, newest first:")
        lines += [f"- {m}" for m in said]
    lines.append("If the change is no longer needed (the update already does it), say so and leave the file alone.")
    return "\n".join(lines)
