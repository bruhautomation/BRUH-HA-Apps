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

The value names are read off the installed CLI rather than remembered:
``--permission-mode`` takes ``bypassPermissions`` and accepts ``default``
(2.1.289 lists ``manual`` in its help and maps it to ``default``; every
older CLI calls it ``default``, so that is the spelling that works on both).
"""
from __future__ import annotations

import logging
import os
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
    that fails removes whatever was there, because a stale ``bypass`` from
    before the switch was turned off is the one stale value that fails open.
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
        log.warning("could not publish the permission switch to %s (%s); "
                    "new terminal sessions will ask", path, exc)
        try:
            path.unlink()
        except OSError:
            # Already gone, or not ours to remove — either way the reader
            # falls back to the boot value or asks.
            pass
        return False
