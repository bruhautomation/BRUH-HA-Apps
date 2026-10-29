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

`listing()` is what the page, ⚙ and the diagnostics payload are told: names,
sizes and a state, never a byte of what the files say.
"""
from __future__ import annotations

import html
import json
import os
import stat
from pathlib import Path

HOUSE_DIR = Path(os.environ.get("BRAIN_HOUSE_UI_DIR", "/config/.brain/ui"))
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


def listing() -> list[dict]:
    """Each house file present, with its size and whether it is used."""
    return [row for row in (_state(n) for n in FILES) if row is not None]


def summary() -> dict:
    """The diagnostics row: names and sizes, never contents."""
    return {"dir": str(HOUSE_DIR), "max_bytes": MAX_BYTES,
            "files": [{k: r[k] for k in ("name", "bytes", "state")}
                      for r in listing()]}


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
             "files": rows}
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


def wants_off(query: dict) -> bool:
    """`?nohouse=1` (or any true spelling) is the safe mode."""
    return str(query.get("nohouse", "")).strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":  # used by the browser measure to render a page
    import sys
    sys.stdout.write(render(sys.stdin.read(), off=len(sys.argv) > 1 and sys.argv[1] == "off"))
