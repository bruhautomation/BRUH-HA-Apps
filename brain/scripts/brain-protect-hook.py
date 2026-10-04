#!/usr/bin/env python3
"""PreToolUse hook: `protected_entities` on the routes around the MCP server.

`protected_entities` is enforced at one chokepoint — `call_service` in the
MCP server — and every Claude path that reaches the house through a TOOL
meets it there. Two routes never touch a tool. A shell can call a service
directly (`ha service call …`, which is `ha-service.sh` curling Core with
the Supervisor token, or a curl of its own), and an edit can write an
automation or a script that acts on the entity the next time it runs. Both
were open in the terminal, the chat and a Fix it run, and DOCS.md said so.

So this hook stands where those two routes start:

- **A shell service call is refused whenever the list is non-empty.** A
  command line cannot be resolved to the entities it reaches — a `--data`
  payload, an area, a device, a template, a variable — and "I could not
  tell" may not be read as "nothing is protected", which is the MCP
  server's own rule for a label or a floor. The refusal names the route
  that can tell: the `call_service` tool. Reading (`ha service list`, a GET
  of the service list) is not a call and is left alone.
- **A YAML edit that names a protected entity is refused.** Write's new
  content, Edit's replacement, every MultiEdit replacement: if one of them
  names an entity the list covers, the edit does not happen. That includes
  context an Edit merely carries along, deliberately — changing an
  automation that already unlocks the door changes how the door is
  unlocked, and a person can still make that edit by hand.

What it cannot see is said rather than hidden: a shell command that edits
a file (`sed -i`, a heredoc), or a service called from a script nobody
named. Those are a person's own terminal, and the list is a guard on what
brAIn does on its own, not a sandbox.

Parsed exactly as `ha_mcp_server` and `automation_writer` parse the option
(comma-separated; an exact id, `domain.*` or `*`), because a second reading
of the same option is a second answer to "is this protected".

A hook that refuses prints Claude Code's PreToolUse decision on stdout and
exits 0; one that allows prints nothing. Anything it cannot read allows:
a hook that crashed on a malformed payload would cost the edit, and an
empty list is the answer "nothing is protected" honestly.

It does one more thing, and only for a command it allows, because it is
the one hook that already reads every Bash command before it runs: the
files that command names under /config (and the other trees brAIn hands
over) are handed to the claude user first when it cannot write them
(`brain_own.ensure_writable_command`). The Edit tool writes a new file and
renames it, which the claude user's own /config lets it do; a shell
redirect, a `tee` or Python's `open(path, "w")` writes in place, into a
file Home Assistant's editor last saved as root. That step fails open: a
panel that is down or slow costs at most a few seconds and never the
command, and a refused command asks nothing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

YAML_SUFFIXES = (".yaml", ".yml")

# A service CALL from a shell: the `ha` dispatcher and `ha-service`, and the
# REST route itself wherever it is reached from (curl, wget, a python
# one-liner). `/api/services/<domain>/<service>` is a call; the bare list
# is a read.
SHELL_CALL_RES = (
    re.compile(r"\bha(?:-|\s+)service(?:\.sh)?\s+call\b"),
    re.compile(r"/api/services/[A-Za-z0-9_]+/[A-Za-z0-9_]+"),
    # Core's WebSocket call, from a script written into the command line.
    re.compile(r"call_service[\s\S]*(?:/api/websocket|/core/websocket)"
               r"|(?:/api/websocket|/core/websocket)[\s\S]*call_service"),
)

ENTITY_RE = re.compile(r"(?<![\w.])([a-z_][a-z0-9_]*)\.([a-z0-9_]+)(?![\w])")


def patterns() -> list[str]:
    raw = os.environ.get("BRAIN_PROTECTED_ENTITIES", "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def named_protected(text: str, pats: list[str]) -> list[str]:
    """The protected entity ids `text` names, in the order it names them."""
    found: list[str] = []
    for match in ENTITY_RE.finditer((text or "").lower()):
        entity = f"{match.group(1)}.{match.group(2)}"
        domain = match.group(1)
        if any(p in (entity, f"{domain}.*", "*") for p in pats):
            if entity not in found:
                found.append(entity)
    return found


def is_shell_call(command: str) -> bool:
    return any(rx.search(command or "") for rx in SHELL_CALL_RES)


def edited_text(tool: str, tool_input: dict) -> str:
    """What an edit would put into the file."""
    if tool == "Write":
        return str(tool_input.get("content") or "")
    if tool == "Edit":
        return str(tool_input.get("new_string") or "")
    if tool == "MultiEdit":
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            return "\n".join(str(e.get("new_string") or "")
                             for e in edits if isinstance(e, dict))
    return ""


def decide(payload: dict, pats: list[str]) -> str | None:
    """The refusal sentence for this tool call, or None to allow it."""
    if not pats or not isinstance(payload, dict):
        return None
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if is_shell_call(command):
            return ("protected_entities is set, and a service called from a shell "
                    "cannot be checked against it — its target can be a data "
                    "payload, an area, a device or a template. Call the service "
                    "with the Home Assistant call_service tool instead, which "
                    "checks the target and refuses only a protected one.")
        return None
    if tool in ("Write", "Edit", "MultiEdit"):
        path = str(tool_input.get("file_path") or "")
        if not path.lower().endswith(YAML_SUFFIXES):
            return None
        hits = named_protected(edited_text(tool, tool_input), pats)
        if hits:
            names = ", ".join(hits[:5]) + (" …" if len(hits) > 5 else "")
            return (f"This edit names {names}, which protected_entities covers. "
                    "brAIn does not write automations, scripts or other YAML "
                    "that reach a protected entity; make this change by hand "
                    "in Home Assistant, or take the entity off the list first.")
    return None


def make_writable(payload) -> None:
    """Hand the files an allowed Bash command names to the claude user when
    it cannot write them. Never raises; a missing `brain_own.py` is a step
    skipped."""
    try:
        if str(payload.get("tool_name") or "") != "Bash":
            return
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.append(here)
        import brain_own
        brain_own.ensure_writable_command(str(tool_input.get("command") or ""))
    except Exception:  # noqa: BLE001 — a hook may not cost the call over a bug
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    try:
        reason = decide(payload, patterns())
    except Exception:  # noqa: BLE001 — a hook may not cost the call over a bug
        reason = None
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
        return 0
    if isinstance(payload, dict):
        make_writable(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
