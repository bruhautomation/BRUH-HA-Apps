#!/usr/bin/env python3
"""Keep the shared UI token block identical in every stylesheet that adopted it.

    python3 .github/scripts/ui_tokens.py           # check: exit 1 if a block differs
    python3 .github/scripts/ui_tokens.py --write   # rewrite every marked block

The source is branding/ui/tokens.css. A stylesheet adopts the standard by
carrying the block between two marker comments (docs/notes/ui-standard.md);
nothing is served from branding/, so there is no extra file to ship.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE = ROOT / "branding" / "ui" / "tokens.css"
STYLESHEETS = (
    "brain/panel/style.css",
    "brain/custom_components/brain/morph/frontend/styles.js",
    "bruh-minecraft-server/panel/style.css",
    "bruh-print/panel/style.css",
    "bright/panel/style.css",
    "bruh-bambu-studio/panel/style.css",
    "bruh-task-manager/panel/style.css",
    "bruh-browser/panel/style.css",
    "gardenrx/app/src/app/globals.css",
)
START = "/* ui-tokens:start (synced from branding/ui/tokens.css; do not edit here) */"
END = "/* ui-tokens:end */"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def wanted() -> str:
    return f"{START}\n{SOURCE.read_text().strip()}\n{END}"


def _state(text: str) -> str:
    """none, one (a lone marker: a mistake), or the block count as 'blocks'."""
    starts, ends = text.count("ui-tokens:start"), text.count("ui-tokens:end")
    if not starts and not ends:
        return "none"
    return "blocks" if starts == ends == len(BLOCK.findall(text)) == 1 else "broken"


def check() -> list[str]:
    problems = []
    want = wanted()
    for rel in STYLESHEETS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text()
        state = _state(text)
        if state == "none":
            continue
        if state == "broken":
            problems.append(f"{rel}: the ui-tokens markers are not one start and one end "
                            "in order; fix them or run ui_tokens.py --write after repairing")
        elif BLOCK.search(text).group(0) != want:
            problems.append(f"{rel}: the ui-tokens block differs from branding/ui/tokens.css; "
                            "run `python3 .github/scripts/ui_tokens.py --write` "
                            "(edit the source, never the copy)")
    return problems


def write() -> list[str]:
    changed = []
    want = wanted()
    for rel in STYLESHEETS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text()
        if _state(text) != "blocks":
            continue
        new = BLOCK.sub(lambda _m: want, text, count=1)
        if new != text:
            path.write_text(new)
            changed.append(rel)
    return changed


def main() -> int:
    if "--write" in sys.argv[1:]:
        done = write()
        print("\n".join(f"rewrote {p}" for p in done) or "every marked block already matches")
        return 0
    problems = check()
    print("\n".join(problems) or "ui-tokens blocks match")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
