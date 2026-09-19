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

* **Mode.** Several of these files are written by root and read by the
  ``claude`` user, so silently narrowing them would break the terminal, the
  listeners and the consolidator with a permission error nothing reports.
  An existing file keeps exactly the mode it had; a new one gets what the
  umask allows, which is what ``Path.write_text`` produced and therefore
  what all of them already carry. The scratch file itself is private until
  the contents are complete — a half-written store is nobody's business,
  and anything built on ``open(..., 'w')`` left it readable throughout.
* **Owner.** ``os.replace`` swaps in a new inode, so a file that was
  ``claude``-owned comes back owned by whoever wrote it. ``run.sh`` creates
  ``/data/run-sources.jsonl`` claude-owned precisely so both halves can
  write it, and the old prune quietly undid that. Root can hand a file over;
  a non-root writer cannot, so this is best-effort by nature.

``locked`` is the other half, and it answers a different failure. An
atomic replace makes a *write* indivisible; it does nothing at all for a
read-modify-write, which is what every store in this panel performs —
read the whole file, change one entry, write it all back. A line another
process appended between the read and the rename is simply gone, and
nothing raises: the winner's bytes are complete and correct and do not
contain it. ``/config/.brain/memory/hypotheses.jsonl`` had three
uncoordinated writers doing exactly that (the panel, ``brain-learn.sh``
appending with ``>>``, and the consolidator's expiry rewrite), and the
panel alone has two — the knowledge and feedback stores are written from
``asyncio.to_thread`` request handlers, so two concurrent requests race
each other.

The lock is a **sidecar** (``<store>.lock``) rather than the store file
itself, and that is forced rather than chosen: ``os.replace`` swaps in a
new inode, so a lock taken on the store is released into a file nobody
can see the moment the write lands — the next writer would lock the new
inode and the two would never meet. The sidecar's inode is stable.

It is ``flock``, so it is advisory, per-open-file-description, released
by the kernel when the process dies, and — the part that matters here —
**shared with the shell**, which is the only way a Python store and a
``jq``/``>>`` script can take the same lock. The file is opened read-only
(``O_RDONLY``), because ``flock`` needs an fd and not write permission,
and because ``O_WRONLY``/``>`` truncates the holder's file at open. Which
means root and the ``claude`` user can each lock a file the other
created.

A lock that cannot be taken **does not refuse the work**: past the
timeout the caller proceeds unlocked, logging that it did, because the
behaviour that leaves is exactly the behaviour every one of these stores
had before this existed — where refusing would lose a homeowner's press
over a lock a dead process left held on a filesystem that does not
support locking at all.

Stdlib only, like every store that imports it.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path

try:  # Linux everywhere this ships; absent on Windows, where the tests do not run.
    import fcntl
except ImportError:  # pragma: no cover - not reachable on any supported image
    fcntl = None

_LOG = logging.getLogger("brain.atomic_write")

# The scratch file is created private and opened up only once it is
# complete. Nothing else has any business reading a half-written store, and
# the old code — like anything built on open(..., 'w') — left the partial
# file readable for the length of the write.
SCRATCH_MODE = 0o600

# What a file gets when there is no existing one to copy: whatever the
# process umask allows, which is what `Path.write_text` produced and so is
# what every one of these files already carries (0o644 under the add-on's
# umask of 022).
#
# Read once, at import. Reading a umask means setting it and putting it
# back, which is not thread-safe — and doing that on every write would race
# the panel's own request threads. It is ambient process state that nothing
# here changes after start-up, so once is both safe and correct.
def _umask() -> int:
    current = os.umask(0o022)
    os.umask(current)
    return current


DEFAULT_MODE = 0o666 & ~_umask()


def _preserved(path: Path) -> tuple[int, int, int]:
    """The mode, uid and gid the file already has, or the defaults."""
    try:
        st = path.stat()
    except OSError:
        return DEFAULT_MODE, -1, -1
    return st.st_mode & 0o777, st.st_uid, st.st_gid


def _scratch(directory: Path, name: str) -> tuple[int, str]:
    """Create an empty private file nobody else can have picked, and open it.

    ``O_EXCL`` is what makes the name safe: two writers racing here both
    propose a random name, and a collision fails rather than silently
    sharing a file — which is the entire bug this module exists to remove.
    """
    while True:
        candidate = directory / f".{name}.{os.urandom(8).hex()}.tmp"
        try:
            return os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SCRATCH_MODE
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
        # Opened up only now that the contents are complete: an explicit
        # mode from the caller, the one the file already carried, or the
        # umask's answer for a file that did not exist yet.
        os.chmod(tmp, keep_mode if mode is None else mode)
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


# ---------------------------------------------------------------------------
# Cross-process locking, for the read-modify-write an atomic replace cannot
# make safe on its own.
# ---------------------------------------------------------------------------

# The sidecar's name, spelled once. The shell half (brain-memory-lock.sh)
# spells the same thing, and `tests/test_store_locking.py` reads it out of
# that script rather than trusting the two to agree: a lock whose two halves
# name different files is no lock at all, and it fails silently.
LOCK_SUFFIX = ".lock"

# How long a caller waits before giving up and doing the work unlocked. A
# consolidation pass rewriting the queue is seconds; a study session never
# holds this across its Claude run (it takes the lock only to append). Ten
# seconds is far past any honest holder and far short of a request timeout.
LOCK_TIMEOUT_S = float(os.environ.get("BRAIN_STORE_LOCK_WAIT", "10"))
LOCK_POLL_S = 0.02


def lock_path(path) -> Path:
    """The sidecar this store's lock is taken on."""
    return Path(str(path) + LOCK_SUFFIX)


def _open_lock(lock: Path) -> int | None:
    """An fd on the sidecar, creating it if this is the first caller.

    Read-only on purpose: ``flock`` wants a file description and not write
    permission, so whichever of root and the ``claude`` user gets there
    first can create it and the other can still lock it.
    """
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for create in (False, True):
        try:
            fd = os.open(lock, os.O_RDONLY | (os.O_CREAT if create else 0), 0o644)
        except FileNotFoundError:
            continue        # first caller: round again, this time with O_CREAT
        except OSError:
            return None
        if create:
            # The umask could have made it 0600, which is a lock only its
            # creator can take — and the two halves run as different users.
            try:
                os.fchmod(fd, 0o644)
            except OSError:
                pass        # somebody else created it; theirs is already right
        return fd
    return None


def _take(fd: int, shared: bool, timeout: float) -> bool:
    """Poll for the lock rather than blocking, so the timeout is real.

    ``LOCK_NB`` in a loop is also exactly what the shell half does, because
    BusyBox's ``flock`` has no ``-w`` — and answers an unknown flag with the
    same exit status as "the lock is held".
    """
    mode = (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            fcntl.flock(fd, mode)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_S)


@contextlib.contextmanager
def locked(path, *, shared: bool = False, timeout: float | None = None):
    """Hold this store's lock for the body. Yields whether it was taken.

    Wrap the WHOLE read-modify-write, never just the write: the window this
    closes is between the read and the rename, so a lock taken around the
    rename alone protects nothing.

    ``shared=True`` is for asking a question of the file — several readers
    may hold it at once and none of them blocks another, which is what
    makes "is anybody writing" a question that can never itself contend.
    """
    if fcntl is None:  # pragma: no cover - not reachable on any supported image
        yield False
        return
    fd = _open_lock(lock_path(path))
    if fd is None:
        # An unwritable directory, or a lock file we may not open. The work
        # still happens: this is the behaviour every store had before.
        _LOG.warning("no lock available for %s — writing unlocked", path)
        yield False
        return
    wait = LOCK_TIMEOUT_S if timeout is None else timeout
    try:
        held = _take(fd, shared, wait)
        if not held:
            _LOG.warning("waited %.0fs for the lock on %s — writing unlocked",
                         wait, path)
        yield held
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # Closing the fd releases the lock anyway — this is the tidy
            # half, and failing it changes nothing a caller can act on.
            pass
        os.close(fd)
