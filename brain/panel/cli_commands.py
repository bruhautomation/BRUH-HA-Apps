"""The `brain` and `ha` dispatchers, as an autocomplete list.

Claude Code advertises its slash commands over the stream, so the chat's
palette can offer exactly what a given install has. The other half of what
anyone types in that box is the add-on's own two CLIs — and they are not
slash commands, so nothing announced them and nothing offered them.

They do announce themselves, just not over a wire: ``brain help`` and
``ha help`` print the list. Parsing that output means the palette is right
by construction — a subcommand added to a dispatcher shows up here without
this file being touched, which a second hardcoded copy of the list could
never promise.

Cached for the life of the process. The dispatchers are baked into the
image, so the answer cannot change under a running add-on, and shelling out
twice per keystroke would be absurd.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger("brain.cli")

# Both are installed on PATH by run.sh. `ha` becomes `hass` if something
# else already owns the name, which is exactly the sort of thing a
# hardcoded list gets wrong.
DISPATCHERS = ("brain", "ha", "hass")
HELP_TIMEOUT_S = 10

# "  brain memory <action>          Long-term home memory"
_TOP = re.compile(r"^ {2}(?P<name>\w+(?: \S+)?)(?P<args>[^ ]*(?: [^ ]+)*?)\s{2,}(?P<desc>\S.*)$")
# "      add \"<fact>\"               Teach it something" — a subcommand of
# whichever top-level line came before it.
_SUB = re.compile(r"^ {4,}(?P<name>[a-z][\w-]*)(?P<args>.*?)\s{2,}(?P<desc>\S.*)$")

_cache: list[dict] | None = None


def _run_help(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        return ""
    try:
        proc = subprocess.run([path, "help"], capture_output=True, text=True,
                              timeout=HELP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("%s help failed: %s", binary, exc)
        return ""
    # The dispatchers print usage and exit 0; a non-zero exit still often
    # carries the text, so the output is what matters, not the code.
    return proc.stdout or ""


def _parse(binary: str, text: str) -> list[dict]:
    out: list[dict] = []
    parent = ""
    for line in text.splitlines():
        if not line.strip() or not line.startswith("  "):
            parent = ""
            continue
        top = _TOP.match(line)
        if top and top.group("name").split()[0] == binary:
            name = top.group("name")
            parent = name
            out.append({
                "name": name,
                "hint": " ".join(top.group("args").split()),
                "description": top.group("desc").strip(),
            })
            continue
        sub = _SUB.match(line)
        if sub and parent:
            out.append({
                "name": f"{parent} {sub.group('name')}",
                "hint": " ".join(sub.group("args").split()),
                "description": sub.group("desc").strip(),
            })
    return out


def listing() -> list[dict]:
    """Every `brain`/`ha` command this image actually has, or [] if neither
    dispatcher is installed (a dev checkout, or `enable_terminal: false`)."""
    global _cache
    if _cache is not None:
        return _cache
    found: list[dict] = []
    seen: set[str] = set()
    for binary in DISPATCHERS:
        for item in _parse(binary, _run_help(binary)):
            if item["name"] in seen:
                continue
            seen.add(item["name"])
            found.append(item)
    found.sort(key=lambda c: c["name"])
    _cache = found
    return found


def reset_cache() -> None:
    """Only the tests need this — see the note about the image above."""
    global _cache
    _cache = None
