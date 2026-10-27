"""Morph's own code, changed by the house it runs in.

Morph is a dashboard brAIn designs, and the point of that is that nothing
about it is out of reach: not the dashboard file, and not the panel either
(its header, its layout engine, a built-in card type, its styles). So the
panel's own modules can be replaced one file at a time:

* brAIn copies a module from Morph's own copy (``paths.SHIPPED``, the
  frontend Home Assistant is serving) into ``/config/morph/frontend/`` under
  the same name and edits the copy. The integration serves that copy in
  place of Morph's own (``custom_components/brain/morph/static.py``), and a page
  reload picks it up.
* It lives in Morph's git folder like everything else, so the change is one
  commit and the person's Undo puts Morph's own back.
* ``.base.json`` records which version of Morph's own file each copy was
  last written against (a hash, recorded when the copy changes). When an
  update changes Morph's own file underneath a copy, the copy is PAUSED —
  served as Morph's own until somebody makes the change again on the new
  file — because a copy of last release's module beside this release's
  others is how a working panel breaks on an update. The record also keeps
  every other module Morph shipped at the time (``others``), and a copy is
  paused when any of them moved too: a copy of morph-panel.js that imports
  engine.js can break on an update that never touched morph-panel.js.
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
# Never replaceable: brAIn's shell (the sidebar entry itself) and the loader
# that falls back to Morph's own when a copy fails, the two files that have
# to keep working.
FIXED = ("boot.js", "shell.js")
BASE_FILE = ".base.json"
# Morph's own file as it was when each copy was written. An update replaces
# Morph's own, so without this a paused copy can only be compared with the
# NEW file, which mixes this house's change with everything the release
# changed; with it, making the change again is a three-way merge.
BASE_DIR = ".base"
# A house module Morph has replaced and no longer reads: the household's
# personality lived in the old frontend/personality.js, read by the house's
# own copy of morph-panel.js, until brAIn kept it (/config/.brain/personality.json,
# which Morph's own Settings reads). A copy that is in use is what the page
# runs, so a copy still importing the old file went on showing the old
# personality whatever Morph shipped (#391). The retired file, and any copy
# that reads it, is paused: Morph's own runs, and Settings says why.
RETIRED = ("personality.js",)
_READS_RETIRED = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in RETIRED) + r")\b")
BRAIN_PERSONALITY = "/config/.brain/personality.json"


def _retired(p: Path) -> bool:
    """The retired module itself, or a copy that still reads it."""
    if p.name in RETIRED:
        return True
    try:
        return bool(_READS_RETIRED.search(p.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


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


def _shipped() -> dict:
    """Every module Morph ships, by name, as a short hash."""
    d = paths.SHIPPED
    try:
        return {p.name: _sha(p) for p in sorted(d.iterdir())
                if p.is_file() and p.suffix == ".js" and p.name not in FIXED}
    except OSError:
        return {}


def record_bases() -> bool:
    """Note, for every copy that changed since it was last seen, which
    version of Morph's own file it was written against. Called before every
    commit, so the record is committed with the copy and Undo puts both
    back together. Returns whether anything was written."""
    if not code_dir().is_dir():
        return False
    bases = _bases()
    out: dict = {}
    shipped_now = _shipped()
    for p in copies():
        own = _sha(p)
        prev = bases.get(p.name) if isinstance(bases.get(p.name), dict) else None
        if prev and prev.get("own") == own:
            out[p.name] = prev
            if "others" not in prev:
                # A record from before 0.5.4 kept no others: what is
                # installed now is the best answer left, and it makes the
                # NEXT update pause the copy when it should.
                out[p.name] = {**prev, "others": _others(p.name, shipped_now)}
        else:
            shipped = paths.SHIPPED / p.name
            out[p.name] = {"own": own, "base": _sha(shipped), "at": int(time.time()),
                           "others": _others(p.name, shipped_now)}
            _keep_base(p.name, shipped)
    if out == bases:
        return False
    paths.write_json(code_dir() / BASE_FILE, out, indent=1)
    return True


def _others(name: str, shipped: dict) -> dict:
    return {k: v for k, v in shipped.items() if k != name}


def moved_others(rec: dict | None, shipped: dict | None = None) -> list[str]:
    """Morph's other modules that changed since this copy was written."""
    was = (rec or {}).get("others")
    if not isinstance(was, dict):
        return []
    now = _shipped() if shipped is None else shipped
    return sorted(n for n in set(was) | set(now) if was.get(n) != now.get(n))


def accept(name: str) -> bool:
    """Record a copy as written against the Morph installed now: brAIn was
    asked to make it work on this release, answered, and left it in place.
    Committed with the next commit like any record."""
    p = code_dir() / name
    if not NAME_RE.match(name or "") or not p.is_file():
        return False
    bases = _bases()
    shipped = paths.SHIPPED / name
    bases[name] = {"own": _sha(p), "base": _sha(shipped), "at": int(time.time()),
                   "others": _others(name, _shipped())}
    _keep_base(name, shipped)
    paths.write_json(code_dir() / BASE_FILE, bases, indent=1)
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
    * ``paused``: Morph's own file changed since the copy was written
      (``kind: changed``), or another of Morph's modules did (``kind:
      others``, with ``moved`` naming them).
    A copy nobody has recorded yet (brAIn's edit, a moment before Morph
    commits it) was written against what is installed now, so it is active.
    """
    bases = _bases()
    shipped_now = _shipped()
    out = []
    for p in copies():
        shipped = paths.SHIPPED / p.name
        rec = bases.get(p.name) if isinstance(bases.get(p.name), dict) else None
        now = _sha(shipped)
        fresh = rec is None or rec.get("own") != _sha(p)
        moved = [] if fresh else [n for n in moved_others(rec, shipped_now) if n != p.name]
        row = {"name": p.name, "kind": "new" if not shipped.exists() else "changed", "at": (rec or {}).get("at")}
        if _retired(p):
            row["status"], row["why"] = "paused", "personality"
        elif fresh:
            row["status"] = "active"
        elif shipped.exists() and rec.get("base") != now:
            row["status"] = "paused"
        elif moved:
            row["status"], row["why"], row["moved"] = "paused", "others", moved[:12]
        else:
            row["status"] = "active"
        out.append(row)
    return out


_TYPES_LITERAL = re.compile(r"export\s+const\s+TYPES\s*=\s*\{([^}]*)\}")
_TYPES_ASSIGN = re.compile(r"\bTYPES\s*(?:\.\s*([A-Za-z_]\w*)|\[\s*['\"]([A-Za-z_]\w*)['\"]\s*\])\s*=(?!=)")
_TYPE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def card_types() -> list[str]:
    """The card types the served cards.js draws, when that is a copy.

    The dashboard compiler (``store.normalize``) wraps a type it does not
    know as a Lovelace card, which is right for ``tile`` and wrong for a
    type this house's own copy of cards.js added: Lovelace has never heard
    of it and draws "Configuration error". Only an ACTIVE copy counts — a
    paused one is not what the page is running, so its types would be drawn
    by a cards.js that does not have them. Read off the copy's ``TYPES``
    object and any ``TYPES.x = …`` after it; empty when there is no copy.
    """
    path = code_dir() / "cards.js"
    if not path.is_file():
        return []
    try:
        active = any(r.get("name") == "cards.js" and r.get("status") == "active" for r in status())
    except OSError:
        return []
    if not active:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found: list[str] = []
    m = _TYPES_LITERAL.search(text)
    if m:
        for part in m.group(1).split(","):
            key = part.split(":", 1)[0].strip().strip("'\"")
            if _TYPE_NAME.match(key):
                found.append(key)
    for a, b in _TYPES_ASSIGN.findall(text):
        key = a or b
        if _TYPE_NAME.match(key):
            found.append(key)
    return list(dict.fromkeys(found))


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


def _redo_part(name: str, version: str, history: list[str] | None, row: dict) -> tuple[str, list[str]]:
    """(the request's first sentence, what brAIn needs about one paused
    copy): which files to read, and whether this is a three-way merge or a
    check against modules that moved. Shared by the per-file press and by
    Merge all, so the two cannot describe one copy differently."""
    mine = f"/config/morph/frontend/{name}"
    if row.get("why") == "personality":
        if name in RETIRED:
            return (f"Remove Morph's old {name}.",
                    [f"{mine} held this household's personality before brAIn kept it. The personality is "
                     f"brAIn's now ({BRAIN_PERSONALITY}, changed in brAIn's Settings › Personality), and "
                     f"Morph's own Settings reads it there. Make sure the personality in {mine} is what "
                     f"{BRAIN_PERSONALITY} holds (say so if it differs, and change nothing there), then "
                     f"delete {mine}. Never write a personality into Morph's files."])
        head = f"Make my change to Morph's {name} again without the old personality file."
        return (head, [
            f"{mine} still reads the old /config/morph/frontend/personality.js, which Morph no longer uses: the "
            f"personality is brAIn's ({BRAIN_PERSONALITY}), and Morph's own {name} reads it there in "
            f"Settings › Personality. So the change is paused and Morph's own is running.",
            f"- This house's version: {mine}",
            f"- Morph's own {name}: {paths.SHIPPED / name}",
            f"Start from Morph's own {name} and carry over only the rest of this house's change. Never "
            f"import, read or write personality.js, and never copy a personality into Morph's files. If "
            f"the personality was the whole change, delete {mine} and say so: Morph then runs its own.",
        ])
    if row.get("why") == "others":
        moved = row.get("moved") or []
        head = f"Make my change to Morph's {name} work on the new Morph ({version})."
        lines = [f"Morph was updated. Its own {name} did not change, but {', '.join(moved)} did, and this house's "
                 f"{mine} uses Morph's other modules, so the change is paused and Morph's own is running.",
                 f"- This house's version: {mine}",
                 f"- Morph's new modules: {paths.SHIPPED}/"]
        lines.append(f"Read {mine} against the new {', '.join(moved)}: every import it takes must still be "
                     f"exported under that name, every function it calls must still take what it passes, and "
                     f"anything it relies on (CSS classes, data attributes, state fields) must still be there. "
                     f"Fix what no longer fits in {mine} and nothing else. If it already fits, leave it as it "
                     f"is and say so: Morph uses it again once you answer.")
    else:
        base = kept_base(name)
        head = f"Make my change to Morph's {name} again on the new Morph ({version})."
        lines = [f"Morph was updated, its own {name} changed underneath this house's change to it, so the change "
                 f"is paused and Morph's own is running.",
                 f"- This house's version: {mine}",
                 f"- Morph's new {name}: {paths.SHIPPED / name}"]
        if base:
            lines += [f"- Morph's {name} as it was when the change was made: {base}",
                      f"The change is the difference between that file and {mine}. Apply that difference to "
                      f"Morph's new {name} (a three-way merge: keep everything the update changed) and save the "
                      f"result as {mine}."]
        else:
            lines += [f"Morph's {name} from before the update was not kept, so {mine} differs from the new file "
                      f"both by this house's change and by everything the update changed. Work out what the "
                      f"house's change was (the commits below say what it was for), then start from Morph's new "
                      f"{name}, make only that change, and save the result as {mine}. Never copy the old file "
                      f"over the new one: that would undo the update."]
    lines.append("Carry over only what this household asked for: a change a commit below or a `(you)` line in "
                 "/config/morph/LEARNED.md explains. A change to the design's own numbers (springs, the "
                 "make-room-first delays, the theme backgrounds, type sizes), a second Now, a second list of "
                 "brAIn's cases, or hover tooltips, with no such reason behind it, is drift: leave Morph's new "
                 "code as it is there and name what you dropped in your answer.")
    said = [m for m in (history or []) if m][:6]
    if said:
        lines.append(f"Commits that changed {mine}, newest first:")
        lines += [f"- {m}" for m in said]
    lines.append(f"If the change is no longer needed (the update already does it), delete {mine} and say so: "
                 f"Morph then runs its own.")
    return head, lines


def redo_words(name: str, version: str, history: list[str] | None = None) -> str:
    """What brAIn is asked when an update paused a copy. The first sentence
    is what a person reads where the request is listed."""
    mine = f"/config/morph/frontend/{name}"
    row = next((r for r in status() if r["name"] == name), {})
    head, lines = _redo_part(name, version, history, row)
    lines.append(f"If the update rewrote the same code this house's change was in, so that there is more than one "
                 f"reasonable way to bring the two together, do not guess and do not write {mine}: answer with "
                 f"`question`, saying in one sentence what the update did to that part, with one option per way "
                 f"to resolve it and one that uses Morph's own. Each option's request must say the whole change "
                 f"to make, file paths included (the files above), because it is sent to you on its own. The "
                 f"change stays paused until one is pressed.")
    return "\n".join([head] + lines)


MERGE_ALL = "all"


def paused() -> list[str]:
    return [r["name"] for r in status() if r["status"] == "paused"]


def redo_all_words(names: list[str], version: str, histories: dict | None = None) -> str:
    """One request for EVERY paused copy, so an update that paused three
    files is one press and one commit rather than three of each. Each file
    gets the same description the per-file press gives it; the conflicts
    are asked one at a time through `question`, and `waiting` names what is
    still undecided so Morph keeps exactly those paused."""
    rows = {r["name"]: r for r in status()}
    lines = [f"Merge all of this house's paused changes to Morph's own code onto the new Morph ({version}): "
             + ", ".join(names) + ".",
             "Morph was updated underneath every one of them. Bring each change across, one file at a time:"]
    for name in names:
        head, part = _redo_part(name, version, (histories or {}).get(name), rows.get(name, {}))
        lines += ["", f"## {name}", head, *part]
    lines += [
        "",
        "Merge every file that merges cleanly, and save it. For a file where the update rewrote the same code " +
        "this house's change was in, so that there is more than one reasonable way to bring the two together, " +
        "do not guess and do not write that file. Answer with `question` about ONE such conflict (the first): " +
        "say in one sentence what the update did to that part, with one option per way to resolve it and one " +
        "that uses Morph's own, each option's request saying the whole change to make for that file, file " +
        "paths included, because it is sent to you on its own. List in `waiting` every file still undecided, " +
        "that one included. Morph puts every file you merged back in use, keeps the waiting ones paused, and " +
        "the person's answer continues this merge with what is left.",
    ]
    return "\n".join(lines)
