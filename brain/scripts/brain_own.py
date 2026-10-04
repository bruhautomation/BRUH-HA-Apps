#!/usr/bin/env python3
"""brain own — make a file under /config writable by Claude, without sudo.

Claude Code runs as the `claude` user; Home Assistant runs as root, and its
UI editors save automations.yaml, scripts.yaml and scenes.yaml by writing a
new file and renaming it over the old one — so a file that was the claude
user's at boot is root's again after the next save from the automation
editor. The panel is the one process in the add-on that is root, so it is
what hands a file back (`POST /api/own`, loopback only, in
`panel/ownership.py`, which decides what may and may not be handed over).

Two callers, one module:

* `brain own [-r] <path...>` — the CLI, for a shell redirect, a `sed -i`,
  anything the edit hook does not see;
* `ensure_writable(path)` — called by the PreToolUse edit hook
  (`brain-edit-snapshot.py`) before a Write or Edit reaches a file the
  claude user cannot write. It is fast and it fails OPEN: a panel that is
  down, slow or refusing leaves the edit to go ahead and fail on its own,
  exactly as it would have without this. A hook must never be the reason
  an edit did not happen.

Nobody should ever be asked to type `sudo chown`. This is the reason.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PANEL_URL = os.environ.get("BRAIN_PANEL_URL", "http://127.0.0.1:8099")
CONFIG_DIR = os.environ.get("BRAIN_CONFIG_DIR", "/config")

# The hook's whole budget for asking. Loopback answers in milliseconds; a
# panel that takes longer than this is a panel the edit should not wait on.
def _seconds(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if 0 < value <= 30 else default


HOOK_TIMEOUT_S = _seconds(os.environ.get("BRAIN_OWN_HOOK_TIMEOUT"), 3.0)
CLI_TIMEOUT_S = 60.0

USAGE = """brain own — make a file under /config writable by Claude

Usage:
  brain own <path...>       Hand these files (or folders) to the claude user
  brain own -r <folder...>  The same, for everything inside the folder

Home Assistant saves automations.yaml, scripts.yaml and scenes.yaml as
root, which leaves them read-only to Claude until they are handed back.
The edit hook does this by itself before Claude edits a file, and brAIn
re-owns the top-level YAML every ten minutes; this is the same thing on
demand. Nobody needs to run sudo or chown.

Refused, whatever you ask: anything outside /config, a symbolic link,
.storage, .cloud, .brain/secrets, secrets.yaml and the recorder database.
"""


def _inside(path: str, root: str) -> bool:
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def targets_for(path) -> list[str]:
    """What to ask the panel to hand over before an edit of ``path``.

    Nothing when this process can already write it, when it is outside the
    config folder, or when this process is root (root writes anything). For
    a file that exists, the file itself if it is not writable; for one that
    does not, the nearest folder that exists, if a new entry cannot be made
    in it. A link is never asked about — the panel would refuse it, and
    the edit should meet its own error rather than a hook's.
    """
    if os.geteuid() == 0 or not path:
        return []
    target = os.path.abspath(str(path))
    root = os.path.normpath(CONFIG_DIR)
    if not _inside(target, root):
        return []
    wanted: list[str] = []
    if os.path.lexists(target):
        if os.path.islink(target):
            return []
        if not os.access(target, os.W_OK):
            wanted.append(target)
        folder = os.path.dirname(target)
    else:
        folder = os.path.dirname(target)
        while folder and not os.path.lexists(folder) and folder != os.sep:
            folder = os.path.dirname(folder)
    # The folder matters as well as the file: a tool that saves by writing
    # a temporary file beside the target and renaming it needs to make a
    # new entry there, and a new file needs it by definition.
    if (folder and _inside(folder, root) and not os.path.islink(folder)
            and os.path.isdir(folder)
            and not os.access(folder, os.W_OK | os.X_OK)):
        wanted.append(folder)
    return wanted


def request_own(paths, recursive: bool = False,
                timeout: float = CLI_TIMEOUT_S) -> dict:
    """POST the paths to the panel. Returns its JSON answer — a refusal's
    body too, which says why — and raises OSError when nothing answered."""
    body = json.dumps({"paths": list(paths),
                       "recursive": bool(recursive)}).encode()
    req = urllib.request.Request(
        f"{PANEL_URL}/api/own", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"})
    # No proxy: this is loopback, and an HTTP(S)_PROXY in the environment
    # would otherwise carry a request for 127.0.0.1 off the machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            answer = json.loads(exc.read().decode() or "{}")
        except ValueError:
            answer = {}
        if not isinstance(answer, dict):
            answer = {}
        answer.setdefault("error", f"the panel answered HTTP {exc.code}")
        return answer


def ensure_writable(path, timeout: float = HOOK_TIMEOUT_S) -> bool | None:
    """The edit hook's half. Never raises.

    None when there was nothing to ask, True when the panel handed
    everything over, False when it was asked and could not (or did not
    answer). The caller ignores the answer on purpose: the edit goes ahead
    either way, and a refusal is the edit's own error to report.
    """
    try:
        wanted = targets_for(path)
        if not wanted:
            return None
        answer = request_own(wanted, timeout=timeout)
        return bool(answer.get("ok"))
    except Exception:  # noqa: BLE001 — a hook must never break the edit
        return False


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("help", "-h", "--help"):
        print(USAGE, end="")
        return 0 if args else 1
    recursive = False
    paths = []
    for arg in args:
        if arg in ("-r", "-R", "--recursive"):
            recursive = True
        else:
            paths.append(os.path.abspath(arg))
    if not paths:
        print(USAGE, end="", file=sys.stderr)
        return 1
    try:
        answer = request_own(paths, recursive=recursive)
    except OSError as exc:
        print(f"The panel is not answering on {PANEL_URL} ({exc}).",
              file=sys.stderr)
        print("Is the add-on running? (brain doctor checks this)",
              file=sys.stderr)
        return 2
    if "results" not in answer:
        print(answer.get("error") or "The panel gave no answer.",
              file=sys.stderr)
        return 1
    who = answer.get("user") or "claude"
    for row in answer["results"]:
        if not row.get("ok"):
            print(f"✗ {row.get('path')}: {row.get('reason') or 'refused'}")
            continue
        changed = int(row.get("changed") or 0)
        if changed:
            noun = "entry" if changed == 1 else "entries"
            line = f"✓ {row.get('path')}: {changed} {noun} handed to {who}"
        else:
            line = f"· {row.get('path')}: already {who}'s"
        if row.get("skipped"):
            line += (f" ({row['skipped']} with other hard links left as "
                     "they were)")
        if row.get("truncated"):
            line += " (stopped early: too many files; run it on a smaller folder)"
        print(line)
    return 0 if answer.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
