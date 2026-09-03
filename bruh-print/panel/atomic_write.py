#!/usr/bin/env python3
"""tmp + rename, with a scratch name no other writer can pick.

Lifted from brAIn, for the bug it was written for: deriving the scratch name
from the target (`path.with_suffix(".tmp")`) makes every writer choose the
SAME name, so two concurrent writers both create it, the first `replace()`
moves it, and the second's bytes go into a file that has already been
renamed away — one write silently lost. Reachable here the moment a print
from the Lovelace card lands while the panel is saving a template.

`mkstemp` in the target's own directory keeps the rename same-filesystem and
therefore still atomic. Mode is restored because mkstemp creates 0600 where
`write_text` made 0644, and `fsync` runs before the rename because the
rename was always ordered and the data behind it was not.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_bytes(path: Path | str, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644

    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text(path: Path | str, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path | str, payload: Any, *, indent: int = 2) -> None:
    write_text(path, json.dumps(payload, indent=indent, sort_keys=False))


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default
