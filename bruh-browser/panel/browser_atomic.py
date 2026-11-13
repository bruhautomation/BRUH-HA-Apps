#!/usr/bin/env python3
"""tmp + rename, with a scratch name no other writer can pick.

BRUH Browser's copy of the rule brAIn's and BRUH Bambu Studio's
`atomic_write` modules keep (each panel is a self-contained image; see
CLAUDE.md's File Conventions): the scratch file is created with `O_EXCL` under
a random name in the target's own directory, so two writers can never share
it and `os.replace` stays a same-filesystem rename; it is private (0600) until
complete; its data is fsynced before the rename. Named for this add-on so a
grep for a function name answers with the file this panel imports.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


def write_bytes(path, data: bytes, mode: int = 0o600) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.parent / f".{target.name}.{secrets.token_hex(6)}.tmp"
    fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(scratch, mode)
        os.replace(scratch, target)
    except BaseException:
        try:
            os.unlink(scratch)
        except OSError:
            pass
        raise


def write_json(path, value, mode: int = 0o600) -> None:
    write_bytes(path, json.dumps(value, indent=1, ensure_ascii=False).encode(), mode)
