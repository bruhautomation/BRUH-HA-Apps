#!/usr/bin/env python3
"""Set a scalar key anywhere in Geyser's config.yml, preserving comments.

`remote.auth-type` is flat enough that a sed one-liner handles it, but
`advanced.bedrock.validate-bedrock-login` is nested two levels deep and
may or may not already exist in a given Geyser build. A proper YAML
load/dump would strip every comment and re-flow the file, which is a
nasty UX regression for operators who hand-edit the config. This script
does a targeted text edit instead:

1. If the key is already present anywhere in the file, flip its value in
   place (preserving indentation + comments).
2. If not, walk the section path (e.g. `advanced.bedrock`) and insert
   the key as a new line directly under the deepest matching section.
3. If even the parent section is missing, append a minimal new block at
   end-of-file. Geyser tolerates additional top-level keys across reboots.

Usage:
    patch-geyser-config.py <config.yml> <key> <value> <dotted.section.path>
    patch-geyser-config.py --managed <config.yml> <auth-type> <mtu> <validate> <motd1> <motd2>

Example:
    patch-geyser-config.py /path/config.yml validate-bedrock-login false advanced.bedrock

`--managed` writes every option the add-on owns, in whichever layout the
file is in. Geyser 2.9 moved its config (config-version 5; Geyser 2.12 is
at 11): `remote:` became `java:`, the top-level `mtu` moved under
`advanced.bedrock`, and `bedrock.motd1`/`motd2` became `motd.primary-motd`
/ `secondary-motd`. A file with a top-level `java:` (or a config-version of
5 or more) is the new layout; one with a top-level `remote:` is the old;
an empty or new file is written in the new layout, which an old file is
migrated to by Geyser itself on its next start. Geyser also reads any
`GEYSER_*` environment variable as an override of the same path
(`GEYSER_JAVA_AUTH_TYPE`), and warns about every one that is not a config
option — which is why the add-on never exports one: the file is the one
place these are set.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def set_key(text: str, key: str, value: str, *, section_path: list[str]) -> str:
    # 1. Fast path: the key is already in the file somewhere.
    existing = re.compile(
        rf"^(?P<indent>[ \t]*){re.escape(key)}:[ \t]*.*$",
        flags=re.MULTILINE,
    )
    new_text, n = existing.subn(
        lambda m: f"{m.group('indent')}{key}: {value}", text,
    )
    if n > 0:
        return new_text

    # 2. Walk the section path to find the insertion point.
    lines = text.splitlines(keepends=True)
    path_idx = 0
    parent_indent = ""
    insert_at: int | None = None
    insert_indent = ""
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent_here = line[: len(line) - len(stripped)]
        head = stripped.rstrip()
        # Only descend into a matching child header that is nested strictly
        # deeper than its parent (so we don't accidentally pick a sibling
        # with the same name at the wrong depth).
        if path_idx < len(section_path) and head == f"{section_path[path_idx]}:":
            if path_idx == 0 or len(indent_here) > len(parent_indent):
                parent_indent = indent_here
                path_idx += 1
                if path_idx == len(section_path):
                    insert_at = i + 1
                    insert_indent = parent_indent + "  "
                    break
    if insert_at is not None:
        lines.insert(insert_at, f"{insert_indent}{key}: {value}\n")
        return "".join(lines)

    # 3. Build the missing section path at end-of-file.
    trailer = "" if text.endswith("\n") else "\n"
    block = ["\n# Added by BRUH Minecraft Server add-on\n"]
    for depth, name in enumerate(section_path):
        block.append("  " * depth + f"{name}:\n")
    block.append("  " * len(section_path) + f"{key}: {value}\n")
    return text + trailer + "".join(block)


def _block_end(lines: list[str], start: int, indent: int) -> int:
    """The index after the last line nested deeper than `indent` from `start`."""
    i = start
    last = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if len(line) - len(line.lstrip()) <= indent:
                break
            last = i + 1
        i += 1
    return last


def _find(lines: list[str], start: int, end: int, name: str) -> tuple[int | None, int | None]:
    """(index, indent) of `name:` among the direct children in lines[start:end]."""
    child = None
    for i in range(start, end):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ind = len(line) - len(line.lstrip())
        if child is None:
            child = ind
        if ind != child:
            continue
        if re.match(rf"{re.escape(name)}:(\s|$)", stripped):
            return i, ind
    return None, child


def get_path(text: str, path: list[str]) -> str | None:
    """The scalar at a dotted path (`java.auth-type`), or None."""
    lines = text.splitlines(keepends=True)
    start, end, indent = 0, len(lines), -1
    for depth, name in enumerate(path):
        at, ind = _find(lines, start, end, name)
        if at is None:
            return None
        if depth == len(path) - 1:
            value = lines[at].split(":", 1)[1].strip()
            return re.sub(r"\s+#.*$", "", value).strip().strip('"').strip("'")
        indent = ind
        start, end = at + 1, _block_end(lines, at + 1, ind)
    return None


def set_path(text: str, path: list[str], value: str) -> str:
    """Set the scalar at a dotted path, creating the sections it needs at
    the end of their parent. Nothing else in the file moves."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start, end, indent = 0, len(lines), -1
    for depth, name in enumerate(path):
        at, child = _find(lines, start, end, name)
        if at is None:
            pad = child if child is not None else indent + 2 if indent >= 0 else 0
            new = []
            for d, part in enumerate(path[depth:]):
                lead = " " * (pad + 2 * d)
                if depth + d == len(path) - 1:
                    new.append(f"{lead}{part}: {value}\n")
                else:
                    new.append(f"{lead}{part}:\n")
            lines[end:end] = new
            return "".join(lines)
        if depth == len(path) - 1:
            lead = lines[at][: len(lines[at]) - len(lines[at].lstrip())]
            lines[at] = f"{lead}{name}: {value}\n"
            return "".join(lines)
        indent = child
        start, end = at + 1, _block_end(lines, at + 1, child)
    return "".join(lines)


def remove_path(text: str, path: list[str]) -> str:
    """Drop the scalar line at a dotted path, if there is one."""
    lines = text.splitlines(keepends=True)
    start, end = 0, len(lines)
    for depth, name in enumerate(path):
        at, ind = _find(lines, start, end, name)
        if at is None:
            return text
        if depth == len(path) - 1:
            if lines[at].split(":", 1)[1].strip():
                del lines[at]
            return "".join(lines)
        start, end = at + 1, _block_end(lines, at + 1, ind)
    return text


def layout(text: str) -> str:
    """'new' (Geyser 2.9+, config-version 5+) or 'old'."""
    version = get_path(text, ["config-version"])
    try:
        if version is not None and int(version) >= 5:
            return "new"
    except ValueError:
        pass
    if re.search(r"^java:\s*$", text, re.M):
        return "new"
    if re.search(r"^remote:\s*$", text, re.M):
        return "old"
    return "new"


def _quoted(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def managed(text: str, auth: str, mtu: str, validate: str, motd1: str, motd2: str) -> str:
    """Every option the add-on owns, set in the file's own layout."""
    if layout(text) == "new":
        places = {"auth": ["java", "auth-type"], "mtu": ["advanced", "bedrock", "mtu"],
                  "motd1": ["motd", "primary-motd"], "motd2": ["motd", "secondary-motd"]}
    else:
        places = {"auth": ["remote", "auth-type"], "mtu": ["mtu"],
                  "motd1": ["bedrock", "motd1"], "motd2": ["bedrock", "motd2"]}
    text = set_path(text, places["auth"], auth)
    text = set_path(text, places["mtu"], str(int(mtu)))
    text = set_path(text, ["advanced", "bedrock", "validate-bedrock-login"], validate)
    text = set_path(text, places["motd1"], _quoted(motd1))
    text = set_path(text, places["motd2"], _quoted(motd2))
    # Up to 1.17.7 the add-on staged `mtu` under `advanced`, where no Geyser
    # reads it; the setting now lives where the layout says.
    return remove_path(text, ["advanced", "mtu"])


def main(argv: list[str]) -> int:
    if len(argv) == 8 and argv[1] == "--managed":
        cfg = Path(argv[2])
        auth, mtu, validate, motd1, motd2 = argv[3:8]
        if auth not in ("online", "offline", "floodgate") or validate not in ("true", "false"):
            print("patch-geyser-config.py: bad auth-type or validate value", file=sys.stderr)
            return 64
        try:
            if not 576 <= int(mtu) <= 9000:
                raise ValueError(mtu)
        except ValueError:
            print(f"patch-geyser-config.py: mtu {mtu!r} is not a number from 576 to 9000",
                  file=sys.stderr)
            return 64
        text = cfg.read_text() if cfg.exists() else ""
        updated = managed(text, auth, mtu, validate, motd1, motd2)
        if updated != text:
            cfg.write_text(updated)
        print(layout(updated))
        return 0
    if len(argv) != 5:
        print("usage: patch-geyser-config.py <cfg> <key> <value> <dotted.section.path>",
              file=sys.stderr)
        return 64
    cfg = Path(argv[1])
    key = argv[2]
    value = argv[3]
    section_path = [p for p in argv[4].split(".") if p]
    text = cfg.read_text()
    updated = set_key(text, key, value, section_path=section_path)
    if updated != text:
        cfg.write_text(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
