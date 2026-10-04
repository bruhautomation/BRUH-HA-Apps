#!/usr/bin/env python3
"""brain own — make a file under /config writable by Claude, without sudo.

Claude Code runs as the `claude` user; Home Assistant runs as root, and its
UI editors save automations.yaml, scripts.yaml and scenes.yaml by writing a
new file and renaming it over the old one — so a file that was the claude
user's at boot is root's again after the next save from the automation
editor. The panel is the one process in the add-on that is root, so it is
what hands a file back (`POST /api/own`, loopback only, in
`panel/ownership.py`, which decides what may and may not be handed over).

Three callers, one module:

* `brain own [-r] <path...>` — the CLI, for anything the hooks do not see
  (a path in a variable, a script that writes where it likes);
* `ensure_writable(path)` — called by the PreToolUse edit hook
  (`brain-edit-snapshot.py`) before a Write or Edit reaches a file the
  claude user cannot write;
* `ensure_writable_command(command)` — called by the PreToolUse Bash hook
  (`brain-protect-hook.py`) for the paths a shell command names, because a
  redirect, a `tee` or Python's `open(..., "w")` writes in place, where the
  Edit tool writes a new file and renames it.

The two hook halves are fast and they fail OPEN: a panel that is down,
slow or refusing leaves the tool to go ahead and fail on its own, exactly
as it would have without this. A hook must never be the reason a command
or an edit did not happen.

It is not only /config: /addon_configs, /share, /media and /addons are
handed to the claude user too when run.sh maps them (`ROOT_VARS`, the same
names `atomic_write.HANDOVER_ROOT_VARS` reads in the panel, which decides).

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
# The other trees run.sh hands to the claude user, by the variable it
# exports when each is mapped — `atomic_write.HANDOVER_ROOT_VARS` in the
# panel, spelled again here because this runs as that user and cannot
# import it; a test holds the two equal.
ROOT_VARS = ("ADDON_CONFIG_DIR", "SHARE_DIR", "MEDIA_DIR", "ADDONS_DIR")
# The most paths one shell command may ask about, and the characters that
# end a path inside a command line (a colon too: `A=/config/a:/config/b` is
# a list far more often than a file name with a colon in it).
MAX_COMMAND_PATHS = 20
_PATH_END = " \t\n'\"<>|;&()`$\\{}:"

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
The edit hooks do this by themselves before Claude edits a file or runs
a command that names one, and brAIn re-owns the top-level YAML every
minute; this is the same thing on demand.
Nobody needs to run sudo or chown.

It works under /config, and under /addon_configs, /share, /media and
/addons when the add-on maps them.

Refused, whatever you ask: anything outside those folders, .storage,
.cloud, .brain/secrets, secrets.yaml and the recorder database. A
symbolic link is answered for the file it points at, which has to pass
the same checks.
"""


def _inside(path: str, root: str) -> bool:
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def roots() -> list[str]:
    """The trees the panel may hand a path over in, as this process sees
    them: the config folder, and each mapped tree run.sh exported. Read at
    call time; `atomic_write.handover_roots`'s rules (absolute, never the
    whole filesystem)."""
    out: list[str] = []
    for raw in [CONFIG_DIR] + [os.environ.get(v, "") for v in ROOT_VARS]:
        raw = (raw or "").strip()
        if not raw or not os.path.isabs(raw):
            continue
        norm = os.path.normpath(raw)
        if norm != os.sep and norm not in out:
            out.append(norm)
    return out


def _in_roots(path: str, trees: list[str]) -> bool:
    return any(_inside(path, t) or _inside(path, os.path.realpath(t))
               for t in trees)


def targets_for(path) -> list[str]:
    """What to ask the panel to hand over before ``path`` is written.

    Nothing when this process can already write it, when it is outside the
    handed-over trees, or when this process is root (root writes
    anything). A symbolic link is resolved and its target asked about,
    because the target is what a write lands in and what the panel checks.
    For a file that exists, the file itself if it is not writable; for one
    that does not, the nearest folder that exists, if a new entry cannot be
    made in it.
    """
    if os.geteuid() == 0 or not path:
        return []
    target = os.path.abspath(str(path))
    trees = roots()
    if not _in_roots(target, trees):
        return []
    if os.path.islink(target):
        target = os.path.realpath(target)
        if not _in_roots(target, trees):
            return []
    wanted: list[str] = []
    if os.path.lexists(target):
        if not os.access(target, os.W_OK):
            wanted.append(target)
        folder = os.path.dirname(target)
    else:
        folder = os.path.dirname(target)
        while folder and not os.path.lexists(folder) and folder != os.sep:
            folder = os.path.dirname(folder)
    if folder and os.path.islink(folder):
        folder = os.path.realpath(folder)
    # The folder matters as well as the file: a tool that saves by writing
    # a temporary file beside the target and renaming it needs to make a
    # new entry there, and a new file needs it by definition.
    if (folder and _in_roots(folder, trees) and os.path.isdir(folder)
            and not os.access(folder, os.W_OK | os.X_OK)):
        wanted.append(folder)
    return wanted


def command_paths(command) -> list[str]:
    """The paths in the handed-over trees a shell command names, in order,
    at most `MAX_COMMAND_PATHS`.

    A reading of the words, not of the shell: a path held in a variable or
    built by a script is not seen, which is what `brain own` and the
    minute's sweep are for. Trailing punctuation is not part of a path. A
    path through a hidden folder (`.storage`, `.git`, `.cloud`) is left
    out: on a command line it is nearly always being read, which needs no
    hand-over, and boot leaves those folders alone for the same reason.
    """
    if not isinstance(command, str) or not command:
        return []
    found: list[str] = []
    for tree in roots():
        start = 0
        while True:
            at = command.find(tree, start)
            if at < 0:
                break
            start = at + len(tree)
            if at and command[at - 1] not in _PATH_END + "=":
                continue
            end = start
            while end < len(command) and command[end] not in _PATH_END:
                end += 1
            word = command[at:end].rstrip(".,:")
            if word != tree and not word.startswith(tree + "/"):
                continue
            norm = os.path.normpath(word)
            if not _inside(norm, tree) or any(
                    part.startswith(".")
                    for part in norm[len(tree):].split("/") if part):
                continue
            if norm not in found:
                found.append(norm)
            if len(found) >= MAX_COMMAND_PATHS:
                return found
    return found


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


def _ask(wanted: list[str], timeout: float, check: list) -> bool | None:
    """One request for every path, and the answer read back off the files
    themselves: an `ok` about a file this process still cannot write is not
    an answer anybody should act on."""
    if not wanted:
        return None
    answer = request_own(wanted, timeout=timeout)
    if not answer.get("ok"):
        return False
    return not any(targets_for(p) for p in check)


def ensure_writable(path, timeout: float = HOOK_TIMEOUT_S) -> bool | None:
    """The edit hook's half. Never raises.

    None when there was nothing to ask, True when the panel handed
    everything over and this process can now write it, False when it was
    asked and could not (or did not answer, or answered and the file is
    still not writable). The caller ignores the answer on purpose: the edit
    goes ahead either way, and a refusal is the edit's own error to report.
    """
    try:
        return _ask(targets_for(path), timeout, [path])
    except Exception:  # noqa: BLE001 — a hook must never break the edit
        return False


def ensure_writable_command(command,
                            timeout: float = HOOK_TIMEOUT_S) -> bool | None:
    """The Bash hook's half: `ensure_writable` for every path a command
    names, in one request. Never raises; the answer is ignored for the same
    reason. A command that only reads a root-owned file hands it over too,
    which costs nothing: it is the claude user's file to read either way.
    """
    try:
        paths = command_paths(command)
        wanted: list[str] = []
        for path in paths:
            for target in targets_for(path):
                if target not in wanted:
                    wanted.append(target)
        return _ask(wanted[:MAX_COMMAND_PATHS], timeout, paths)
    except Exception:  # noqa: BLE001 — a hook must never break the command
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
        name = row.get("path")
        if row.get("target"):
            name = f"{name} → {row['target']}"
        if changed:
            noun = "entry" if changed == 1 else "entries"
            line = f"✓ {name}: {changed} {noun} handed to {who}"
        else:
            line = f"· {name}: already {who}'s"
        if row.get("skipped"):
            line += (f" ({row['skipped']} with other hard links left as "
                     "they were)")
        if row.get("truncated"):
            line += " (stopped early: too many files; run it on a smaller folder)"
        print(line)
    return 0 if answer.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
