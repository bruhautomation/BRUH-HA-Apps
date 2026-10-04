#!/usr/bin/env python3
"""PreToolUse hook: ask brAIn's action gate before an acting tool runs.

Wired in run.sh's settings beside `brain-edit-snapshot.py`. Claude Code
hands every PreToolUse hook the tool name, its input, the session id and
the transcript path on stdin; this posts the call to the panel's
`/api/gate` over loopback and turns the answer into the hook's own output.

Five rules, each a test (`tests/test_action_gate.py`).

**It never says allow.** A PreToolUse `allow` bypasses Claude Code's own
permission system — the chat's Discuss ask rules, every deny rule, the
prompt a terminal would have shown. So an allowed call is this script
printing NOTHING and exiting 0, which leaves every other rule exactly where
it was. It can only ever add a refusal or a question.

**Unreachable is never allow.** A panel that does not answer, answers late,
or answers something unreadable: a run somebody is watching (`chat`,
`terminal`) is asked; any other run is refused. Fail closed where nobody can
be asked, fail to a question where somebody can.

**Only acting tools are sent**, and the list is a copy of
`consequence.GATED_MCP` held equal to it by a test, because this has to
answer without the panel — a read costs nothing but the Python start.
Built-in file and shell tools are sent only under a change contract.

**A voice agent at the voice level is not sent at all.** It runs under the
narrowest deterministic floors the add-on has — exposed entities only, an
allow-list of services — and a voice command waiting on a loopback round
trip and a model is a voice command that times out. A wider voice agent is
gated like anything else.

**The person's words are read from the transcript and nothing else is.**
Their own turns only: a `tool_result` block, a system reminder, a command's
output and the assistant's text are all excluded, because those are where
text somebody else wrote arrives.

Every path exits 0 with a JSON decision or nothing; a crash here must not
wedge every acting tool, so an exception is treated as unreachable.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PANEL_URL = os.environ.get("BRAIN_PANEL_URL", "http://127.0.0.1:8099")
TIMEOUT_S = float(os.environ.get("BRAIN_GATE_TIMEOUT_S", "25"))
MCP_PREFIX = "mcp__home-assistant__"
INTERACTIVE = frozenset({"chat", "terminal"})
# A copy of `consequence.GATED_MCP`; `tests/test_action_gate.py` holds the
# two equal.
GATED_MCP = frozenset({
    "call_service", "control_light", "control_climate",
    "control_media_player", "control_cover", "control_fan", "control_switch",
    "control_lock", "control_alarm", "control_vacuum", "activate_scene",
    "run_script", "reload_config", "fire_event", "remember_fact",
    "bright_show", "print_label", "minecraft_addons", "minecraft_command",
    "minecraft_player", "minecraft_server", "minecraft_teleport",
    "minecraft_world", "music_assistant_command", "music_assistant_play",
    "music_assistant_player", "music_assistant_remove_players",
    "esphome_clean", "esphome_compile", "esphome_create_device",
    "esphome_delete_device", "esphome_install", "esphome_set_secret",
    "esphome_update_firmware", "esphome_write_config",
    "set_device_class", "show_switch_as", "stop_showing_switch_as",
    "set_sensor_display",
})
CONTRACT_BUILTINS = frozenset({"Bash", "Write", "Edit", "MultiEdit",
                               "NotebookEdit"})
TAIL_BYTES = 256 * 1024
MAX_WORDS = 6
MAX_WORD_CHARS = 1200
# Text a harness puts in a user turn that is not the person typing.
NOT_THE_PERSON = ("<system-reminder", "<command-", "<local-command",
                  "Caveat: The messages below", "[Request interrupted")


def channel() -> str:
    word = os.environ.get("BRAIN_CHANNEL", "").strip().lower()
    return "".join(ch for ch in word if ch.isalnum() or ch == "_")[:32]


def voice_level() -> bool:
    return (os.environ.get("BRAIN_EXPOSED_ONLY", "") == "1"
            or os.environ.get("BRAIN_ASSIST_ACCESS", "").strip() == "voice")


def contract() -> dict | None:
    raw = os.environ.get("BRAIN_CHANGE_CONTRACT", "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return {"invalid": True}
    return value if isinstance(value, dict) else {"invalid": True}


def gated(tool: str, under_contract: bool) -> bool:
    if tool.startswith(MCP_PREFIX):
        return tool[len(MCP_PREFIX):] in GATED_MCP
    return under_contract and tool in CONTRACT_BUILTINS


def _texts(content) -> list[str]:
    """The person's own text in one user message's content."""
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text") or ""))
            # tool_result, image and anything else are not the person.
    return out


def person_words(path: str) -> list[str]:
    """The person's last few turns, oldest first. [] when unreadable."""
    if not path or not path.endswith(".jsonl"):
        return []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    words: list[str] = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "user":
            continue
        if row.get("isMeta") or row.get("isCompactSummary") \
                or row.get("toolUseResult") is not None:
            continue
        message = row.get("message") if isinstance(row.get("message"), dict) \
            else {}
        if message.get("role") not in (None, "user"):
            continue
        for text in _texts(message.get("content")):
            text = text.strip()
            if not text or text.startswith(NOT_THE_PERSON):
                continue
            words.append(text[:MAX_WORD_CHARS])
    return words[-MAX_WORDS:]


def emit(decision: str, reason: str, chan: str) -> int:
    """Print the hook's answer. `allow` prints nothing, on purpose."""
    if decision == "ask" and chan not in INTERACTIVE:
        decision = "deny"
    if decision not in ("ask", "deny"):
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": f"brAIn's action gate: {reason}"[:500],
    }}))
    return 0


def unreachable(chan: str, why: str) -> int:
    if chan in INTERACTIVE:
        return emit("ask", f"it could not be reached ({why}), so you are "
                           "being asked instead", chan)
    return emit("deny", f"it could not be reached ({why}), and with nobody "
                        "here to ask, the action is refused", chan)


def main(stdin=None) -> int:
    chan = channel()
    try:
        payload = json.load(stdin or sys.stdin)
    except (ValueError, OSError):
        return 0      # not a payload this hook understands; nothing to gate
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get("tool_name") or "")
    agreed = contract()
    if not gated(tool, agreed is not None):
        return 0
    if voice_level() and chan == "voice":
        return 0
    try:
        body = json.dumps({
            "tool": tool,
            "input": payload.get("tool_input") if isinstance(
                payload.get("tool_input"), dict) else {},
            "channel": chan,
            "session_id": str(payload.get("session_id") or "")[:64],
            "words": person_words(str(payload.get("transcript_path") or "")),
            "contract": agreed,
            "intervention": os.environ.get("BRAIN_INTERVENTION_ID", "")[:64],
            "exposed_only": os.environ.get("BRAIN_EXPOSED_ONLY", "") == "1",
        }).encode()
        req = urllib.request.Request(
            f"{PANEL_URL}/api/gate", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            answer = json.loads(resp.read(65536).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return unreachable(chan, type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 — a crash is unreachable, never allow
        return unreachable(chan, type(exc).__name__)
    if not isinstance(answer, dict) or answer.get("decision") not in (
            "allow", "ask", "deny"):
        return unreachable(chan, "an answer it could not read")
    return emit(answer["decision"], str(answer.get("reason") or ""), chan)


if __name__ == "__main__":
    sys.exit(main())
