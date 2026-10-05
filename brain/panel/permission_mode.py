"""Whether brAIn acts without asking — one switch, read by two faces.

The add-on option is `dangerously_skip_permissions` (kept, so every
existing configuration means what it meant), shown as "Let brAIn act
without asking" on the Configuration tab and in ⚙ → Terminal & chat. It is
mirrored both ways like the generation options (`addon_options`), so it is
one setting with two doors.

Two faces read it, and they read it at different moments:

* **The chat** reads it from the panel every time it decides how to spawn a
  process (`ChatSession.skip_permissions`, refreshed by the server the way
  `model` is), and spawns with ``--permission-mode bypassPermissions`` when
  it is on. A change reaches an idle conversation on its next message,
  through a respawn on ``--resume``; a conversation that is mid-answer keeps
  the mode it was started with until then.
* **The classic terminal** is a shell script, so it reads a FILE —
  ``/data/brain-permissions``, one word — when a session STARTS
  (`scripts/brain-permissions.sh`). It used to be a flag baked into the
  command ttyd was launched with at boot, which is why a change needed an
  add-on restart. run.sh writes the file at boot, before ttyd, and the
  panel rewrites it whenever the effective value moves.

Two rules every reader of the file keeps. **Only the one word means act**:
``bypass``. "ask", an empty file, a half-written one, a word nobody
recognises, a file the reader cannot open — all of those are asking, because
a security default may only fail closed. And **an absent file is the only
case that falls back** (to the flag run.sh wrote into ``/data/.brain_env``):
something at the path that cannot be read is not the same claim as nothing
having been written yet.

That second rule is why a write that FAILS must never leave the path empty
of a file. The fallback is the value from the last boot, so removing a
stale ``bypass`` after the switch was turned off hands the answer straight
back to a boot value that may still be the flag — the one way a failed OFF
could start the next terminal session acting anyway. So a failed write
leaves an EMPTY file (`_clear`): truncating one needs no free space, which
is the commonest reason the write failed, and an empty file reads as
asking whatever the boot value says.

**A switch reaches a session when it STARTS, and a terminal session can
outlive many flips.** ttyd attaches to the same tmux session on every page
load (``tmux new-session -A``), so turning the switch off does not reach a
terminal Claude started while it was on: that process goes on acting
without asking until somebody ends it. Nothing here ends it — the
terminal's shell is never killed — so `terminal_sessions` reports what is
still running under tmux and how it started, and ⚙ says so in words.

The value names are read off the installed CLI rather than remembered:
``--permission-mode`` takes ``bypassPermissions`` and accepts ``default``
(2.1.289 lists ``manual`` in its help and maps it to ``default``; every
older CLI calls it ``default``, so that is the spelling that works on both).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.permissions")

# The add-on option, and the settings key that mirrors it — one name, so
# the ⚙ field, the Configuration tab and the Supervisor's options object
# cannot disagree about what they are called.
OPTION = "dangerously_skip_permissions"

# The file the terminal reads. Spelled again in scripts/brain-permissions.sh
# and run.sh, which cannot import this; tests/test_permission_mode.py reads
# all three, because a path renamed in one of them goes silent in the other.
DEFAULT_FILE = "/data/brain-permissions"
# Where run.sh wrote the boot value the terminal falls back on when the file
# above is ABSENT. Spelled again in scripts/brain-permissions.sh.
DEFAULT_ENV_FILE = "/data/.brain_env"

# The two words the file holds. Anything else is read as ASK.
ON = "bypass"
OFF = "ask"

# What each face is handed.
CHAT_BYPASS = "bypassPermissions"
CHAT_DISCUSS = "default"
TERMINAL_FLAG = "--dangerously-skip-permissions"


def file_path() -> str:
    """Where the switch is published — read at call time, so a test (or a
    box that knows better) can point it somewhere else."""
    return os.environ.get("BRAIN_PERMISSIONS_FILE", DEFAULT_FILE)


def env_file_path() -> str:
    return os.environ.get("BRAIN_PERMS_ENV_FILE", DEFAULT_ENV_FILE)


def startup() -> bool:
    """The option as run.sh exported it when the panel started — the floor
    under the live value, the way `BRAIN_MODEL` is under the model's."""
    return os.environ.get("BRAIN_SKIP_PERMISSIONS", "false").strip().lower() \
        == "true"


def word(on: bool) -> str:
    return ON if on else OFF


def publish(on: bool) -> bool:
    """Write the switch where a terminal session reads it, if it moved.

    Returns whether the file now says ``on``. Never raises: the chat reads
    the panel directly, so a file that cannot be written costs only the
    terminal's copy, and the reader's own rules make that copy ask rather
    than act. A missing parent directory is a dev checkout or a test, not
    a reason to create one — `facts_store.writable`'s rule. And a write
    that fails leaves the path EMPTY rather than gone (`_clear`), because
    a gone file is the one case the reader falls back on, and the fallback
    is the boot value — which, on an add-on started with the switch on, is
    the flag this write was trying to take away.
    """
    path = Path(file_path())
    if not path.parent.is_dir():
        return False
    text = word(on) + "\n"
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return True
    except OSError:
        # Unreadable is not a reason to skip the write below.
        pass
    try:
        # 0644: the panel is root and the terminal is the `claude` user,
        # and the word in here is not a secret — it is what the
        # Configuration tab already shows.
        atomic_write.write_text(path, text, mode=0o644)
        return True
    except OSError as exc:
        failure = exc
    if _clear(path):
        log.warning("could not publish the permission switch to %s (%s); "
                    "left it empty, so new terminal sessions will ask",
                    path, failure)
    else:
        log.error("could not publish the permission switch to %s (%s), and "
                  "could not clear it either; a terminal session starting "
                  "now reads whatever was there before", path, failure)
    return False


def _clear(path: Path) -> bool:
    """Leave something at ``path`` the terminal's reader reads as asking.

    Returns whether that is now true. In order of preference:

    * **an empty file**, by truncating what is there (no free space
      needed, so it survives the ENOSPC that most likely failed the write)
      or creating one (an inode, no data). ``O_NOFOLLOW`` because a
      symlink at the path would truncate whatever it points at; one is
      taken away first and the empty file made in its place.
    * **a directory already there** is left alone — the reader cannot read
      a word out of one, which is asking.
    * **removing the path**, only as a last resort and only while the boot
      value it would hand the answer to does not act. Otherwise removing
      it is the failure this function exists to prevent.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    last: OSError | None = None
    for _attempt in range(2):
        try:
            # codeql[py/overly-permissive-file] — the terminal runs as the claude user and must read this one word; it holds no secret.
            os.close(os.open(path, flags, 0o644))
            return True
        except IsADirectoryError:
            return True
        except OSError as exc:
            if path.is_symlink() and _attempt == 0:
                try:
                    path.unlink()
                    continue
                except OSError:
                    # A symlink that will not go is a path nothing here can
                    # make empty; the fall-through below decides from that.
                    pass
            last = exc
            break
    if not os.path.lexists(path):
        # Nothing to remove, and nothing could be made: the reader falls
        # back on the boot value, which is either asking or out of reach.
        return not boot_flag_set()
    if boot_flag_set():
        log.debug("not removing %s: the boot value it would fall back on "
                  "acts (%s)", path, last)
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


# The one line of /data/.brain_env the reader looks at, exactly as
# scripts/brain-permissions.sh's `sed` matches it — the last such line wins.
_ENV_LINE = re.compile(r'^export BRAIN_CLAUDE_PERMS_FLAG="([^"]*)"$')


def boot_flag_set() -> bool:
    """Whether the terminal's fallback — the boot value run.sh wrote into
    ``/data/.brain_env`` — is the flag. Read, never sourced, exactly the
    way the shell reader reads it; tests drive the two over one set of
    files, because a fallback with two answers is two different switches."""
    try:
        text = Path(env_file_path()).read_text(encoding="utf-8",
                                               errors="replace")
    except OSError:
        return False
    found = ""
    for line in text.splitlines():
        match = _ENV_LINE.match(line)
        if match:
            found = match.group(1)
    return found == TERMINAL_FLAG


def published() -> bool | None:
    """What the published file says: True for ``bypass``, False for ``ask``,
    None for anything else — absent, empty, garbage or unreadable.

    The posture check reads this rather than ``/data/options.json``: it is
    what a terminal session starting now actually reads, and the panel
    rewrites it the moment the switch moves. Whitespace is dropped the way
    the shell reader's ``tr -d '[:space:]'`` drops it, bytes and all.
    """
    try:
        with open(file_path(), "rb") as fh:
            data = fh.read(32)
    except OSError:
        return None
    word_ = bytes(b for b in data if b not in b" \t\n\v\f\r")
    if word_ == ON.encode():
        return True
    if word_ == OFF.encode():
        return False
    return None


def _bypass_mode(argv: list[str]) -> bool:
    for i, arg in enumerate(argv):
        if arg == "--permission-mode" and i + 1 < len(argv) \
                and argv[i + 1] == CHAT_BYPASS:
            return True
        if arg == f"--permission-mode={CHAT_BYPASS}":
            return True
    return False


def _process_table(proc_root: str) -> dict[int, tuple[int, list[str]]] | None:
    """pid → (ppid, argv) for every process we can read. None when the
    table itself cannot be listed."""
    table: dict[int, tuple[int, list[str]]] = {}
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    for name in entries:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, name, "cmdline"), "rb") as fh:
                raw = fh.read()
            with open(os.path.join(proc_root, name, "stat"), "rb") as fh:
                stat = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        # `pid (comm) state ppid …` — comm may hold spaces or parentheses,
        # so the fields are read after the LAST close bracket.
        fields = stat.rpartition(")")[2].split()
        try:
            ppid = int(fields[1])
        except (IndexError, ValueError):
            continue
        argv = [a.decode("utf-8", errors="replace")
                for a in raw.split(b"\0") if a]
        if argv:
            table[int(name)] = (ppid, argv)
    return table


def _is_claude(argv: list[str]) -> bool:
    return os.path.basename(argv[0]) == "claude"


def terminal_sessions(proc_root: str = "/proc") -> dict | None:
    """The Claude processes running in the terminal now, by how they began.

    ``{"acting": n, "asking": n}``, or None when the process table cannot
    be read. A terminal process is a Claude CLI with ``tmux`` among its
    ancestors — that is what the Terminal tab is, and it is what keeps the
    chat's processes, the engine's runs, the listeners and a guided
    sign-in (all children of the panel or a listener) out of the count —
    and only the TOP one of a chain, so a CLI that starts helpers of its
    own is one session. ``acting`` is one started with
    ``--dangerously-skip-permissions`` (or a bypass permission mode), which
    includes a background task the session picker started that way;
    ``asking`` is an interactive one (no ``-p``) started without.

    The panel is root, so every process's ``cmdline`` is readable; one
    that is not is skipped, which can only make a count smaller.
    """
    table = _process_table(proc_root)
    if table is None:
        return None
    acting = asking = 0
    for pid, (ppid, argv) in table.items():
        if not _is_claude(argv):
            continue
        parent = table.get(ppid)
        if parent is not None and _is_claude(parent[1]):
            continue
        under_tmux = False
        seen = {pid}
        cursor = ppid
        while cursor in table and cursor not in seen and len(seen) < 64:
            seen.add(cursor)
            up_ppid, up_argv = table[cursor]
            if os.path.basename(up_argv[0]) == "tmux":
                under_tmux = True
                break
            cursor = up_ppid
        if not under_tmux:
            continue
        if TERMINAL_FLAG in argv or _bypass_mode(argv):
            acting += 1
        elif "-p" not in argv and "--print" not in argv:
            asking += 1
    return {"acting": acting, "asking": asking}
