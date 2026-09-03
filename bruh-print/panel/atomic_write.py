#!/usr/bin/env python3
"""tmp + rename, with a scratch name no other writer can pick.

Lifted from brAIn, for the bug it was written for: deriving the scratch name
from the target (`path.with_suffix(".tmp")`) makes every writer choose the
SAME name, so two concurrent writers both create it, the first `replace()`
moves it, and the second's bytes go into a file that has already been
renamed away — one write silently lost. Reachable here the moment a print
from the Lovelace card lands while the panel is saving a template.

Three things this has to get right, and each is a regression that only shows
up in somebody's log weeks later.

**The scratch name.** `O_EXCL` on a random name is what makes it safe: two
writers racing here both propose a name, and a collision fails loudly rather
than silently sharing a file — which is the entire bug this module removes.
It is created in the target's own directory, so `os.replace` is still a
same-filesystem rename and still atomic.

**Mode.** The scratch file is private until its contents are complete —
nothing has any business reading a half-written store, and anything built on
`open(..., "w")` leaves the partial file readable for the length of the
write. What it becomes afterwards is the mode the file already had, or the
caller's, or the umask's. A hardcoded `0o644` was what shipped, and it is
wrong twice over: it makes every file in `/data` world-readable when nothing
outside this container reads them, and it ignores a umask the operator set
on purpose. The one file that genuinely has to be readable by another
process — the state mirror Home Assistant Core reads — asks for its mode
explicitly, which is also the only place the question is visible.

**Owner.** `os.replace` swaps in a new inode, so a file that belonged to
somebody else comes back owned by whoever wrote it. Root can hand a file
over and a non-root writer cannot, so this is best-effort by nature.

`fsync` before the rename is the one thing the old code was missing outright
— the rename was always ordered, the data behind it was not.

Stdlib only, like every store that imports it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Created private and opened up only once the contents are complete.
SCRATCH_MODE = 0o600


def _umask() -> int:
    """The process umask, read the only way Python offers: by setting it."""
    current = os.umask(0o022)
    os.umask(current)
    return current


def _default_mode() -> int:
    """What an ordinary `open(..., "w")` would have produced here.

    Read per call rather than at import, because `run.sh` and the panel are
    the same process tree and a umask set between them should be honoured.
    """
    return 0o666 & ~_umask()


def _preserved(path: Path) -> tuple[int | None, int, int]:
    """The mode, uid and gid the file already has, or (None, -1, -1)."""
    try:
        st = path.stat()
    except OSError:
        return None, -1, -1
    return st.st_mode & 0o777, st.st_uid, st.st_gid


def _scratch(directory: Path, name: str) -> tuple[int, Path]:
    """An empty private file nobody else can have picked, already open."""
    while True:
        candidate = directory / f".{name}.{os.urandom(8).hex()}.tmp"
        try:
            handle = os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SCRATCH_MODE)
        except FileExistsError:
            continue
        return handle, candidate


def write_bytes(path: Path | str, data: bytes, *, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kept_mode, uid, gid = _preserved(path)
    handle, tmp = _scratch(path.parent, path.name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        # The caller's mode, then the one the file already carried, then the
        # umask's — in that order, because an explicit ask outranks history
        # and history outranks a default.
        if mode is not None:
            os.chmod(tmp, mode)
        elif kept_mode is not None:
            os.chmod(tmp, kept_mode)
        else:
            os.chmod(tmp, _default_mode())
        if uid != -1:
            try:
                os.chown(tmp, uid, gid)
            except OSError:
                # Best effort: only root can hand a file to another user, and
                # a panel that refused to save a template because it could
                # not restore an owner would be the worse failure.
                pass
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text(path: Path | str, text: str, *, mode: int | None = None) -> None:
    write_bytes(path, text.encode("utf-8"), mode=mode)


def write_json(path: Path | str, payload: Any, *, indent: int = 2,
               mode: int | None = None) -> None:
    write_text(path, json.dumps(payload, indent=indent, sort_keys=False),
               mode=mode)


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default
