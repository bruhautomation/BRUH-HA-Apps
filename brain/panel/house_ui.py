"""The house's own layer over brAIn's page: `house.css` and `house.js`.

brAIn's page is `/opt/panel` — root's, baked into the image and replaced by
every update — and the chat and the terminal run as the `claude` user, so
"change brAIn's own header" was a promise YOLO could not keep: an edit to
`/opt/panel` either failed or was wiped by the next update. Morph has a house
copy of its code; brAIn's page had nothing.

This is the additive answer, and it never makes a program file writable:

* two optional files in `HOUSE_DIR` (`/config/.brain/ui/`), where the rest of
  what the house keeps for brAIn lives (`.brain/instructions/` is the same
  idea for prompts). `run.sh` hands `/config/.brain` to the `claude` user at
  boot, the edit-snapshot hook journals every edit under `/config` so
  `brain undo` puts a file back, and an update never touches `/config`;
* `house.css` is linked AFTER `style.css`, so it wins a tie and adds to the
  shipped sheet rather than replacing it;
* `house.js` is never a tag in the page: the shipped `house-layer.js` loads
  it in a script of its own after `app.js` has run, so a house.js that
  throws is one line in ⚙ › Instructions and the shipped panel is untouched;
* each file is refused past `MAX_BYTES`, and a link or anything but a plain
  file is refused rather than followed (a link to `secrets.yaml` would
  otherwise be served to the page);
* `?nohouse=1` on the page (the shell passes it into its frame) skips both,
  the safe mode for a house.js that broke the page.

**Automatic undo** (the owner's decision of 2026-11-04: no person presses
anything before brAIn changes its own page, so the page has to catch a bad
change itself, the way Morph's boot.js falls back to the shipped module).
A version of a file the page has not yet seen work is *unconfirmed*
(`good: false` in the facts). `house-layer.js` loads it, waits for the page
to settle and runs the page's health check (the header, the tabs and the
main pane drawn and visible, and house.js not thrown); then it reports:

* `confirm` — the version works: a copy is kept as the last good one
  (`STATE_DIR`, under `/data`, which a session cannot write — the thing
  being judged never marks itself good);
* `revert` — it threw on load or failed the check: the file is put back to
  the last good copy, or taken away when there is none (the shipped page is
  the oldest good version there is), the bad bytes are kept beside the good
  ones, and why goes into `reverts.jsonl`, which the page shows in
  ⚙ › Instructions, the diagnostics payload carries and the next session
  is told about.

Both act only on the version the page actually loaded (`v`): a tab left open
on an older version can never undo a newer edit. `brain undo` and the edit
snapshots still work as before; this is the undo nobody has to ask for.

`listing()` is what the page, ⚙ and the diagnostics payload are told: names,
sizes and a state, never a byte of what the files say.
"""
from __future__ import annotations

import html
import json
import os
import stat
import threading
import time
from pathlib import Path

import atomic_write

HOUSE_DIR = Path(os.environ.get("BRAIN_HOUSE_UI_DIR", "/config/.brain/ui"))
# The page's verdicts on the house's files: the last good copy of each, the
# bad ones it took away, and why. Under /data, which only the panel writes.
STATE_DIR = Path(os.environ.get("BRAIN_HOUSE_STATE_DIR", "/data/house-ui"))
GOOD_FILE = "good.json"
REVERTS_FILE = "reverts.jsonl"
MAX_REVERTS = 50          # lines kept in reverts.jsonl
MAX_BAD_KEPT = 10         # bad copies kept per file
MAX_WHY = 200
# How long a revert is news on the page and in a session's context.
REVERT_SHOWN_S = 7 * 86400
_LOCK = threading.Lock()
# The only names served, in the order they are layered. Never a name off the
# wire: the routes are fixed, one per file.
FILES = ("house.css", "house.js")
CONTENT_TYPES = {"house.css": "text/css", "house.js": "application/javascript"}
# A header restyle or a few added behaviours is a few KB; past this it is not
# a layer any more, and the page reads it on every load.
MAX_BYTES = 256 * 1024
# The one include point in index.html. A comment, so the file opened as
# itself (every browser measure does) shows nothing where it sits.
PLACEHOLDER = "<!--brain:house-->"


def _state(name: str) -> dict | None:
    """One file's row, or None when it is not there."""
    path = HOUSE_DIR / name
    try:
        st = path.lstat()
    except OSError:
        return None
    row = {"name": name, "bytes": int(st.st_size), "state": "ok",
           "v": f"{st.st_mtime_ns:x}-{st.st_size:x}"}
    if not stat.S_ISREG(st.st_mode):
        row["state"] = "refused"
    elif st.st_size > MAX_BYTES:
        row["state"] = "too_big"
    return row


def _good() -> dict:
    """``{name: v}``: the version of each file the page last confirmed."""
    try:
        data = json.loads((STATE_DIR / GOOD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in FILES and isinstance(v, str)}


def listing() -> list[dict]:
    """Each house file present, with its size, whether it is used, and
    whether this version has been seen to work (`good`)."""
    good = _good()
    rows = [row for row in (_state(n) for n in FILES) if row is not None]
    for row in rows:
        row["good"] = good.get(row["name"]) == row["v"]
    return rows


def _row(name: str) -> dict | None:
    return next((r for r in listing() if r["name"] == name), None)


def _set_good(name: str, v: str | None) -> None:
    good = _good()
    if v:
        good[name] = v
    else:
        good.pop(name, None)
    atomic_write.write_json(STATE_DIR / GOOD_FILE, good)


def confirm(name: str, v: str) -> bool:
    """The page saw version ``v`` of ``name`` work: keep it as the last
    good copy. False when ``v`` is not what is there now (a newer edit
    landed since the page loaded) or there is nothing usable to keep."""
    if name not in FILES:
        return False
    with _LOCK:
        row = _row(name)
        if not row or row["state"] != "ok" or row["v"] != str(v or ""):
            return False
        if row["good"]:
            return True
        data = read(name)
        if data is None:
            return False
        try:
            atomic_write.write_bytes(STATE_DIR / "good" / name, data)
            _set_good(name, row["v"])
        except OSError:
            return False
    return True


def _keep_bad(name: str, data: bytes | None, now: float) -> str:
    """Keep the bytes that were taken away, newest ten per file."""
    if data is None:
        return ""
    folder = STATE_DIR / "reverted"
    target = folder / f"{name}.{int(now)}"
    try:
        atomic_write.write_bytes(target, data)
        old = sorted(folder.glob(f"{name}.*"), key=lambda p: p.name)
        for extra in old[:-MAX_BAD_KEPT]:
            extra.unlink(missing_ok=True)
    except OSError:
        return ""
    return str(target)


def _log_revert(entry: dict) -> None:
    path = STATE_DIR / REVERTS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    lines.append(json.dumps(entry, separators=(",", ":")))
    atomic_write.write_text(path, "\n".join(lines[-MAX_REVERTS:]) + "\n")


def reverts(limit: int = MAX_REVERTS) -> list[dict]:
    """What the page has taken back, newest first."""
    try:
        raw = (STATE_DIR / REVERTS_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return list(reversed(out))[:max(0, limit)]


def last_revert(now: float | None = None) -> dict | None:
    """The newest revert while it is still news, else None."""
    now = time.time() if now is None else now
    rows = reverts(1)
    if rows and now - float(rows[0].get("at") or 0) < REVERT_SHOWN_S:
        return {k: rows[0].get(k) for k in ("at", "name", "why", "restored")}
    return None


def revert(name: str, v: str, why: str, now: float | None = None) -> dict:
    """Take back version ``v`` of ``name``, which threw or failed the page's
    check: put the last good copy back, or take the file away when there
    is none. ``{"reverted": bool, "restored": "previous"|"none", "why"}``.

    Never touches a version other than ``v``: a newer edit stands until a
    page that loaded IT says otherwise."""
    now = time.time() if now is None else now
    why = " ".join(str(why or "it failed the page's check").split())[:MAX_WHY]
    if name not in FILES:
        return {"reverted": False, "why": "not a house file"}
    with _LOCK:
        row = _row(name)
        if not row or row["v"] != str(v or ""):
            return {"reverted": False,
                    "why": "that version is no longer there"}
        bad = read(name)
        good_copy = STATE_DIR / "good" / name
        restored = "none"
        try:
            # A version already confirmed that breaks now (a shipped change
            # it leaned on) has no better copy than itself: take it away.
            if not row["good"] and good_copy.is_file():
                data = good_copy.read_bytes()
                atomic_write.write_bytes(HOUSE_DIR / name, data)
                restored = "previous"
                fresh = _state(name)
                _set_good(name, fresh["v"] if fresh else None)
            else:
                (HOUSE_DIR / name).unlink(missing_ok=True)
                good_copy.unlink(missing_ok=True)
                _set_good(name, None)
        except OSError as exc:
            return {"reverted": False, "why": f"could not put it back: {exc}"[:MAX_WHY]}
        kept = _keep_bad(name, bad, now)
        entry = {"at": int(now), "name": name, "v": row["v"], "why": why,
                 "restored": restored, "kept": kept}
        try:
            _log_revert(entry)
        except OSError:
            # The file is already back; a ledger that could not be written
            # only loses the "why" line, never the undo itself.
            pass
    return {"reverted": True, "restored": restored, "why": why}


def summary() -> dict:
    """The diagnostics row: names and sizes, never contents."""
    return {"dir": str(HOUSE_DIR), "max_bytes": MAX_BYTES,
            "files": [{k: r[k] for k in ("name", "bytes", "state", "good")}
                      for r in listing()],
            "last_revert": last_revert()}


def read(name: str) -> bytes | None:
    """A house file's bytes, or None for anything that is not to be served.

    Opened `O_NOFOLLOW` and checked on the descriptor, so a file swapped for
    a link between the listing and the read is still refused.
    """
    if name not in FILES:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(HOUSE_DIR / name, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            data = fh.read(MAX_BYTES + 1)
    except OSError:
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    return data if len(data) <= MAX_BYTES else None


def head_block(off: bool = False) -> str:
    """What replaces `PLACEHOLDER`: the facts for `house-layer.js`, and the
    house stylesheet's link when there is one to use."""
    rows = listing()
    facts = {"off": bool(off), "max": MAX_BYTES, "dir": str(HOUSE_DIR),
             "files": rows, "reverted": last_revert()}
    out = ['<meta name="brain-house" content="%s">'
           % html.escape(json.dumps(facts, separators=(",", ":")), quote=True)]
    css = next((r for r in rows if r["name"] == "house.css"), None)
    if not off and css and css["state"] == "ok":
        out.append('<link id="brainHouseCss" rel="stylesheet" href="house.css?v=%s">'
                   % html.escape(css["v"], quote=True))
    return "\n".join(out)


def render(page: str, off: bool = False) -> str:
    """The panel's index with the house layer's include point filled."""
    return page.replace(PLACEHOLDER, head_block(off), 1)


OUTCOMES = ("confirm", "revert")


def outcome(body) -> dict:
    """What `POST api/house/outcome` does with the page's verdict:
    ``{"name", "v", "outcome": "confirm"|"revert", "why"}``. Raises
    ValueError for a body that is not one."""
    if not isinstance(body, dict):
        raise ValueError("send a JSON object")
    name = body.get("name")
    verdict = body.get("outcome")
    v = body.get("v")
    if name not in FILES:
        raise ValueError("name must be house.css or house.js")
    if verdict not in OUTCOMES:
        raise ValueError("outcome must be confirm or revert")
    if not isinstance(v, str) or not v or len(v) > 64:
        raise ValueError("v must be the version the page loaded")
    if verdict == "confirm":
        return {"confirmed": confirm(name, v)}
    return revert(name, v, str(body.get("why") or ""))


def wants_off(query: dict) -> bool:
    """`?nohouse=1` (or any true spelling) is the safe mode."""
    return str(query.get("nohouse", "")).strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":  # used by the browser measure to render a page
    import sys
    sys.stdout.write(render(sys.stdin.read(), off=len(sys.argv) > 1 and sys.argv[1] == "off"))
