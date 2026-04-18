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

Example:
    patch-geyser-config.py /path/config.yml validate-bedrock-login false advanced.bedrock
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
    block = [f"\n# Added by BRUH Minecraft Server add-on\n"]
    for depth, name in enumerate(section_path):
        block.append("  " * depth + f"{name}:\n")
    block.append("  " * len(section_path) + f"{key}: {value}\n")
    return text + trailer + "".join(block)


def main(argv: list[str]) -> int:
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
