"""Replace a file's contents atomically, without racing another writer.

Every store in the panel wrote its file the same way::

    tmp = path.with_suffix(".tmp")
    tmp.write_text(...)
    tmp.replace(path)

which is atomic against a *reader* — a reader sees the old bytes or the new
ones, never a half-written file — and is exactly wrong against a second
*writer*. The scratch name is derived from the target, so it is the same
name for everyone: two writers both create ``findings.tmp``, the first
``replace()`` moves it, and the second finds its own scratch file gone::

    FileNotFoundError: '/…/findings.tmp' -> '/…/findings.json'

One writer raises and **the other's write is silently lost** — whichever
lost the race wrote its bytes into a file that the winner then renamed away.

That is reachable in the panel as it stands: ``h_finding_fix`` writes the
findings store from a request-handler thread (``asyncio.to_thread``) while
``_generate`` writes the same store from the event loop after an insight
run. It is what made ``test_fix_and_snooze_offer_no_undo`` fail about one
run in three.

The fix is a scratch name nobody else can pick — a random one, created
``O_EXCL`` in the target's own directory, so ``os.replace`` is still a
same-filesystem rename and still atomic.

Two things this has to carry over from the old code, and both are the kind
of regression that only shows up in somebody's log weeks later:

* **Mode.** ``Path.write_text`` created the file at ``0666`` and let the
  umask narrow it — 0644 under the add-on's — and several of these files are
  written by root and read by the ``claude`` user. So the scratch file is
  opened the same way rather than chmod-ed to a fixed number: silently
  narrowing them would break the terminal, the listeners and the
  consolidator with a permission error nothing reports, and silently
  *widening* them under a stricter umask would be its own surprise. An
  existing file keeps whatever mode it already had.
* **Owner.** ``os.replace`` swaps in a new inode, so a file that was
  ``claude``-owned comes back owned by whoever wrote it. ``run.sh`` creates
  ``/data/run-sources.jsonl`` claude-owned precisely so both halves can
  write it, and the old prune quietly undid that. Root can hand a file over;
  a non-root writer cannot, so this is best-effort by nature.

Stdlib only, like every store that imports it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# What a NEW file is created with — the mode passed to open(), which the
# process umask then narrows, exactly as it did for `Path.write_text`
# (0o644 under the add-on's umask of 022). Deliberately not a chmod to a
# fixed number: reading the umask means setting it first, which is not
# thread-safe, and hard-coding the result would silently widen these files
# for anyone running under a stricter one.
CREATE_MODE = 0o666


def _preserved(path: Path) -> tuple[int | None, int, int]:
    """The mode, uid and gid the file already has.

    ``None`` for the mode when there is no file yet — meaning "let the open
    mode and the umask decide", which is what the old code did by never
    setting a mode at all.
    """
    try:
        st = path.stat()
    except OSError:
        return None, -1, -1
    return st.st_mode & 0o777, st.st_uid, st.st_gid


def _scratch(directory: Path, name: str) -> tuple[int, str]:
    """Create an empty file nobody else can have picked, and open it.

    ``O_EXCL`` is what makes the name safe: two writers racing here both
    propose a random name, and a collision fails rather than silently
    sharing a file — which is the entire bug this module exists to remove.
    """
    while True:
        candidate = directory / f".{name}.{os.urandom(8).hex()}.tmp"
        try:
            return os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, CREATE_MODE
            ), str(candidate)
        except FileExistsError:
            continue        # 64 bits collided; ask for another name


def write_text(path, text: str, *, encoding: str = "utf-8",
               mode: int | None = None) -> None:
    """Replace ``path``'s contents with ``text``, atomically.

    Creates parent directories. ``mode`` forces the result's permissions; by
    default an existing file keeps the ones it had, and a new one gets what
    the umask allows — both of which is what the code this replaces did.
    Raises OSError on failure, leaving the target untouched and no scratch
    file behind; callers that treat a failed write as survivable catch it
    themselves, as they already did.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keep_mode, uid, gid = _preserved(path)
    fd, tmp = _scratch(path.parent, path.name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            # Durability, not atomicity: os.replace orders the rename, not
            # the data behind it, so without this a power cut can leave the
            # rename applied and the contents empty. These files are small
            # and written at human speed.
            handle.flush()
            os.fsync(handle.fileno())
        # Only ever narrows or restores: an explicit mode from the caller,
        # or the one the file already carried. A brand-new file is left at
        # whatever the umask gave it above.
        if mode is not None:
            os.chmod(tmp, mode)
        elif keep_mode is not None:
            os.chmod(tmp, keep_mode)
        if uid >= 0:
            try:
                os.chown(tmp, uid, gid)
            except OSError:
                # Only root can give a file away. A non-root writer keeps
                # its own ownership, which is what happened before this.
                pass
        os.replace(tmp, path)
    except BaseException:
        # A directory littered with scratch files is what a failed write
        # looks like from the outside, and the next reader would have to
        # know to ignore them.
        try:
            os.unlink(tmp)
        except OSError:
            # Already gone, or never created — either way the cleanup this
            # was going to do has happened. The original error is what the
            # caller needs, so it is re-raised below regardless.
            pass
        raise


def write_json(path, data, *, mode: int | None = None, **dumps) -> None:
    """``write_text`` of ``data`` as JSON — the shape most callers want.

    ``ensure_ascii=False`` by default: these files hold friendly names and
    memory lines, and escaping them costs bytes and readability for nothing.
    """
    dumps.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(data, **dumps), mode=mode)


def write_lines(path, lines, *, mode: int | None = None, **dumps) -> None:
    """JSONL: one object per line, trailing newline. Same guarantees."""
    dumps.setdefault("ensure_ascii", False)
    write_text(path, "".join(json.dumps(o, **dumps) + "\n" for o in lines),
               mode=mode)
