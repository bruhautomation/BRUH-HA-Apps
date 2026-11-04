#!/usr/bin/env python3
"""Scripts written into the running world: Skript scripts and data pack functions.

A click-triggered item (a wand) needs a script, and the world's folders live
in this add-on's storage, where nothing outside it can write. So the panel is
the one writer, and the `bruh_minecraft.write_script` / `remove_script` /
`list_scripts` services reach it through the bridge.

* **Two kinds, two fixed folders.** `skript` is `plugins/Skript/scripts/<name>.sk`
  (refused when the Skript plugin is not installed); `datapack_function` is
  `<world>/datapacks/bruh_scripts/data/bruh_scripts/function/<name>.mcfunction`,
  run in the game as `function bruh_scripts:<name>`. A name is lowercase
  letters, digits, `_` and `-`, so it can never name a folder or step out of
  one; the path is checked again after it is built.
* **Loaded without a restart, and its errors are the answer.** Skript is
  asked to `sk reload` the one script and the data pack loader to `reload`;
  both print their parse errors to the server console rather than to the
  RCON sender, so the console lines written right after are read back
  (`scripts/console_reply.py`). A script that did not load is a refusal with
  the errors in it; the file stays, so the next write can fix it.
* **Only what this wrote.** Every write is recorded per world in
  `.bruh-scripts.json` beside `.bruh-addons.json`. A file of the same name
  that is not in the record (somebody's own script) is never overwritten or
  removed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

KINDS = ("skript", "datapack_function")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MAX_BYTES = 64 * 1024
MAX_SCRIPTS = 200
RECORD_NAME = ".bruh-scripts.json"
PACK = "bruh_scripts"
PACK_MCMETA = {
    "pack": {
        "description": "BRUH Minecraft: scripts written through Home Assistant",
        "pack_format": 48,
        "supported_formats": {"min_inclusive": 15, "max_inclusive": 1000},
        "min_format": 15,
        "max_format": 1000,
    }
}
# `Skript-2.9.5.jar`, `Skript.jar`, `skript_2.10.jar` — not `skript-reflect`.
SKRIPT_JAR = re.compile(r"^skript(?:[-_ ]?v?\d[\w.+-]*)?\.jar$", re.IGNORECASE)
VERSION_RE = re.compile(r"\b1\.(\d+)(?:\.(\d+))?")

# How the two loaders say they are done, so a reload is not waited on longer.
SKRIPT_DONE = re.compile(r"(successfully reloaded|encountered \d+ errors?|"
                         r"reloaded .* with \d+ errors?|can't find the script|"
                         r"does not exist|no script)", re.IGNORECASE)
SKRIPT_ERROR = re.compile(r"(encountered \d+ errors?|with \d+ errors?|^\s*line \d+:|"
                          r"can't understand|can't find the script|does not exist|"
                          r"\berror\b)", re.IGNORECASE)
SKRIPT_NOT_ERROR = re.compile(r"(successfully reloaded|(^|\]\s*)reloading\b|\b0 errors)",
                              re.IGNORECASE)
FUNCTION_FAILED = re.compile(r"Failed to load function (\S+)")
FUNCTION_DETAIL = re.compile(r"(Whilst parsing|Unknown or incomplete|Incorrect argument|"
                             r"Expected |Invalid |<--\[HERE\])")


class ScriptError(Exception):
    """A refusal, with the sentence to say and the loader's errors."""

    def __init__(self, message: str, status: int = 409, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


# ---------------------------------------------------------------------------
# Where things go
# ---------------------------------------------------------------------------
def check_name(kind: str, name: str) -> tuple[str, str]:
    kind = str(kind or "").strip()
    name = str(name or "").strip()
    if kind not in KINDS:
        raise ScriptError(f"The kind is skript or datapack_function, not {kind!r}.", 400)
    if name.endswith(".sk") or name.endswith(".mcfunction"):
        name = name.rsplit(".", 1)[0]
    if not NAME_RE.match(name):
        raise ScriptError(
            f"{name!r} is not a script name: use 1 to 48 lowercase letters, digits, "
            "_ and -, starting with a letter or digit.", 400)
    return kind, name


def skript_installed(server_dir: Path) -> bool:
    try:
        return any(SKRIPT_JAR.match(p.name) for p in (Path(server_dir) / "plugins").iterdir()
                   if p.is_file())
    except OSError:
        return False


def function_folder(version: str) -> str:
    """`function` from 1.21 (and when nothing says), `functions` before it."""
    m = VERSION_RE.search(str(version or ""))
    if m and int(m.group(1)) < 21:
        return "functions"
    return "function"


def _inside(root: Path, path: Path) -> Path:
    root = Path(root).resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ScriptError("That path is outside the world.", 400)
    return path


def target(kind: str, name: str, server_dir: Path, level: str, version: str) -> Path:
    server_dir = Path(server_dir)
    if kind == "skript":
        return _inside(server_dir, server_dir / "plugins" / "Skript" / "scripts" / f"{name}.sk")
    pack = server_dir / level / "datapacks" / PACK
    return _inside(server_dir, pack / "data" / PACK / function_folder(version)
                   / f"{name}.mcfunction")


def call_name(kind: str, name: str) -> str:
    return f"{name}.sk" if kind == "skript" else f"{PACK}:{name}"


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------
def record_path(server_dir: Path) -> Path:
    return Path(server_dir) / RECORD_NAME


def read_record(server_dir: Path) -> dict[str, dict]:
    try:
        data = json.loads(record_path(server_dir).read_text())
    except (OSError, ValueError):
        return {}
    items = data.get("scripts") if isinstance(data, dict) else None
    return {k: v for k, v in (items or {}).items() if isinstance(v, dict)}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_record(server_dir: Path, items: dict[str, dict]) -> None:
    _atomic_write(record_path(server_dir),
                  json.dumps({"scripts": items}, indent=2, sort_keys=True).encode())


def listing(server_dir: Path) -> dict:
    rows = []
    for key, row in sorted(read_record(server_dir).items()):
        path = Path(server_dir) / str(row.get("path") or "")
        rows.append({**{k: row.get(k) for k in ("kind", "name", "call", "size",
                                                "written_at", "by", "loaded")},
                     "present": path.is_file()})
    return {"scripts": rows, "skript_installed": skript_installed(server_dir)}


# ---------------------------------------------------------------------------
# Loading, and what the loader said
# ---------------------------------------------------------------------------
def skript_errors(text: str) -> list[str]:
    lines = [ln.rstrip() for ln in str(text or "").splitlines() if ln.strip()]
    if not any(SKRIPT_ERROR.search(ln) and not SKRIPT_NOT_ERROR.search(ln) for ln in lines):
        return []
    return [ln for ln in lines if not SKRIPT_NOT_ERROR.search(ln)][:40]


def function_errors(text: str, name: str) -> list[str]:
    """The loader's failure for `bruh_scripts:<name>` and the line that says
    why; another pack's failures are not this script's answer."""
    want = f"{PACK}:{name}"
    out: list[str] = []
    keep = False
    for line in str(text or "").splitlines():
        m = FUNCTION_FAILED.search(line)
        if m:
            keep = m.group(1).rstrip(":,.") == want
            if keep:
                out.append(line.strip())
            continue
        if keep and FUNCTION_DETAIL.search(line) and not line.lstrip().startswith("at "):
            out.append(line.strip())
    return out[:40]


Run = Callable[[str, bool], str]
"""`run(command, listen)`: the RCON reply, with the console lines after it
when `listen` (console_reply.command with `always`). Raises when the server
does not answer."""


def _reload(kind: str, name: str, run: Run) -> tuple[bool, str, list[str]]:
    """(reached the server, what it said, errors)."""
    try:
        if kind == "skript":
            text = run(f"sk reload {name}.sk", True)
            return True, text, skript_errors(text)
        text = run("minecraft:reload", True)
        errors = function_errors(text, name)
        listed = run("minecraft:datapack list enabled", False) or ""
        if f"file/{PACK}" not in listed:
            run(f'minecraft:datapack enable "file/{PACK}"', False)
        return True, text, errors
    except Exception as exc:  # noqa: BLE001 — a server that is not running loads it at start
        return False, f"The server did not answer: {exc}", []


def write(server_dir: Path, level: str, version: str, kind: str, name: str, content: str,
          run: Run, by: str = "", clock: Callable[[], float] = time.time) -> dict:
    kind, name = check_name(kind, name)
    if not isinstance(content, str):
        raise ScriptError("The content is the script's text.", 400)
    body = content.replace("\r\n", "\n")
    if "\x00" in body:
        raise ScriptError("The content has a NUL byte in it; a script is text.", 400)
    data = body.encode("utf-8")
    if not data.strip():
        raise ScriptError("The script is empty.", 400)
    if len(data) > MAX_BYTES:
        raise ScriptError(f"The script is {len(data)} bytes; the most is {MAX_BYTES}.", 413)
    server_dir = Path(server_dir)
    if kind == "skript" and not skript_installed(server_dir):
        raise ScriptError("The Skript plugin is not installed in this world, so a Skript "
                          "script would do nothing. Install Skript from the add-on "
                          "browser first.", 409)
    if kind == "datapack_function" and not (server_dir / level).is_dir():
        raise ScriptError("The world folder does not exist yet; start the server once "
                          "first.", 409)
    record = read_record(server_dir)
    key = f"{kind}:{name}"
    path = target(kind, name, server_dir, level, version)
    if key not in record:
        if path.exists():
            raise ScriptError(f"There is already a script called {name} that was not "
                              "written here, so it is left alone. Choose another name.", 409)
        if len(record) >= MAX_SCRIPTS:
            raise ScriptError(f"This world already has {MAX_SCRIPTS} written scripts; "
                              "remove one first.", 409)
    if kind == "datapack_function":
        mcmeta = server_dir / level / "datapacks" / PACK / "pack.mcmeta"
        if not mcmeta.is_file():
            _atomic_write(mcmeta, json.dumps(PACK_MCMETA, indent=2).encode())
    _atomic_write(path, data)
    reached, text, errors = _reload(kind, name, run)
    record[key] = {
        "kind": kind, "name": name, "call": call_name(kind, name),
        "path": str(path.relative_to(server_dir)),
        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
        "written_at": int(clock()), "by": str(by or "")[:64],
        "loaded": bool(reached and not errors),
    }
    write_record(server_dir, record)
    if errors:
        raise ScriptError(f"{name} was saved but did not load: " + " | ".join(errors[:8]),
                          422, errors)
    answer = {"kind": kind, "name": name, "call": call_name(kind, name),
              "size": len(data), "reloaded": reached, "reply": text.strip()}
    if not reached:
        answer["note"] = ("The server is not running; the script loads when it starts. "
                          + text)
    elif kind == "datapack_function":
        answer["note"] = f"Run it in the game with: function {PACK}:{name}"
    return answer


def remove(server_dir: Path, level: str, version: str, kind: str, name: str,
           run: Run) -> dict:
    kind, name = check_name(kind, name)
    server_dir = Path(server_dir)
    record = read_record(server_dir)
    key = f"{kind}:{name}"
    row = record.get(key)
    if row is None:
        raise ScriptError(f"There is no script called {name} written here, so nothing "
                          "was removed.", 404)
    # The record says where it was written; it is believed only when that is
    # one of the two places this kind of script can be.
    places = {target(kind, name, server_dir, level, v) for v in ("1.20", "1.21")}
    recorded = server_dir / str(row.get("path") or "")
    path = recorded if recorded in places else target(kind, name, server_dir, level, version)
    reached = True
    text = ""
    try:
        if kind == "skript":
            # Skript unloads a script it disables (renaming it `-name.sk`).
            text = run(f"sk disable {name}.sk", True)
    except Exception as exc:  # noqa: BLE001
        reached, text = False, f"The server did not answer: {exc}"
    path.unlink(missing_ok=True)
    if kind == "skript":
        path.with_name(f"-{name}.sk").unlink(missing_ok=True)
    else:
        try:
            text = run("minecraft:reload", True)
        except Exception as exc:  # noqa: BLE001
            reached, text = False, f"The server did not answer: {exc}"
    record.pop(key, None)
    write_record(server_dir, record)
    return {"removed": name, "kind": kind, "unloaded": reached, "reply": text.strip()}
