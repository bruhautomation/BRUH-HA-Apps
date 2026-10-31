"""A house change a trusted grown-up asked for in Minecraft, waiting for a person.

A grown-up whose row in ⚙ › Minecraft has "Can ask for anything" on (and
whose name the server checked) gets brAIn's chat from the game: the
`minecraft_trusted` task scope on its own channel. With "Let brAIn act
without asking" on, a house change simply happens, as in the chat. Off, the
chat would show an approval card — and a headless run has no page to show
one on, so the 4.0.29 refusal ("I'll need you to approve that in brAIn")
sent the owner looking for something that did not exist.

So the action gate files the call itself as ONE question in brAIn › Today
(`findings_store.add_case`, source `minecraft_approval`, Approve / Deny),
mirrored to Home Assistant's Repairs like every open question and sent to
the phone with the same two buttons where brAIn's notifications go to one.
The run is told the exact sentence to say in the game — where it waits.

Approve runs EXACTLY the call that was asked (`run_call`: the MCP server's
own `tools/call`, so `protected_entities`, the tripwire and every other
chokepoint inside the tool still stand) and the companion tells the person
in the game "Done: …"; Deny, Doesn't apply and an hour with no answer
(`APPROVAL_TTL`) tell them it was not approved. Nothing here asks a model.

`approvals.json` beside the faculty's files is the panel's record of each
one and how it ended, which ⚙ › Minecraft lists.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import minecraft_companion

rules = minecraft_companion.rules

SOURCE = "minecraft_approval"
SOURCE_TITLE = "Asked for in Minecraft"
MAX_RECORDS = 30
RUN_TIMEOUT_S = 90
MCP_SERVER = os.environ.get(
    "BRAIN_MCP_SERVER",
    str(Path(__file__).resolve().parent.parent / "ha-mcp-server" / "ha_mcp_server.py"))
CHANNEL = "minecraft_trusted"


def short_tool(tool: Any) -> str:
    return str(tool or "").rsplit("__", 1)[-1][:60]


def _entities(args: dict) -> list[str]:
    out: list[str] = []
    for src in (args, args.get("data") if isinstance(args.get("data"), dict) else {},
                args.get("target") if isinstance(args.get("target"), dict) else {}):
        value = src.get("entity_id") if isinstance(src, dict) else None
        for eid in ([value] if isinstance(value, str) else value or []):
            if isinstance(eid, str) and eid not in out:
                out.append(eid[:80])
    return out[:6]


def describe(tool: Any, args: Any) -> str:
    """The call in a few words a person can approve: the service or tool,
    and the entities it names. Built by code from the call, never a model's
    sentence, clipped."""
    args = args if isinstance(args, dict) else {}
    name = short_tool(tool)
    ents = _entities(args)
    if name == "call_service":
        what = f"{args.get('domain') or '?'}.{args.get('service') or '?'}"
    elif name.startswith("control_"):
        what = f"{name.split('_', 1)[1]} {args.get('action') or ''}".strip()
    else:
        what = name.replace("_", " ")
    if ents:
        what += " on " + ", ".join(ents)
    return " ".join(what.split())[:160]


def as_row(tool: str, args: dict, speaker: dict, now: float, assistant: str) -> dict:
    """The question filed in brAIn › Today."""
    person = str((speaker or {}).get("person") or "A grown-up")[:40]
    what = describe(tool, args)
    stamp = time.strftime("%H:%M", time.localtime(now))
    ents = _entities(args)
    return {
        "text": f"{person} asked in Minecraft: {what} (at {stamp})",
        "claim": (f"{person} asked {assistant} in Minecraft to do this in the house: {what}. "
                  "Approve and it is done now; Deny and it is not. Nothing happens until "
                  "you answer, and it is dropped after an hour."),
        "detail": "", "fix": "",
        "kind": "question", "severity": "warning", "fixable": False,
        "source": SOURCE, "source_title": SOURCE_TITLE,
        "entity_id": ents[0] if ents else "",
        "minecraft_approval": {
            "tool": str(tool)[:120], "input": args,
            "player": str((speaker or {}).get("player") or "")[:17],
            "person": person, "what": what,
            "asked_at": int(now), "expires_at": int(now + rules.APPROVAL_TTL)},
    }


def same_call(row: dict, tool: str, args: dict, player: str) -> bool:
    ask = (row or {}).get("minecraft_approval") or {}
    return (row.get("source") == SOURCE and ask.get("tool") == tool
            and ask.get("input") == args and ask.get("player") == player)


def expired(row: dict, now: float) -> bool:
    ask = (row or {}).get("minecraft_approval") or {}
    return row.get("source") == SOURCE and now >= float(ask.get("expires_at") or 0)


def line(key: str, what: str = "") -> str:
    return rules.APPROVAL_LINES[key].format(what=what)


# -- the record ⚙ › Minecraft lists ----------------------------------------------
def _path(shared_dir: str | None = None) -> str:
    return os.path.join(rules.folder(shared_dir or minecraft_companion.SHARED_DIR),
                        rules.APPROVALS)


def record(entry: dict, shared_dir: str | None = None) -> None:
    """One approval's state, newest first, keyed on `ts` (the finding's)."""
    path = _path(shared_dir)
    data = rules.read_json(path, {})
    rows = data.get("approvals") if isinstance(data.get("approvals"), list) else []
    rows = [r for r in rows if isinstance(r, dict) and r.get("ts") != entry.get("ts")]
    rules.write_json(path, {"approvals": ([entry] + rows)[:MAX_RECORDS]})


def listing(shared_dir: str | None = None) -> list[dict]:
    data = rules.read_json(_path(shared_dir), {})
    rows = data.get("approvals") if isinstance(data.get("approvals"), list) else []
    return [r for r in rows if isinstance(r, dict)]


# -- carrying out an approved call -------------------------------------------------
def _argv() -> list[str]:
    cmd = ["python3", MCP_SERVER]
    if hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("su-exec"):
        cmd = ["su-exec", "claude"] + cmd
    return cmd


def run_call(tool: str, args: dict, timeout: float = RUN_TIMEOUT_S) -> bool:
    """Run the one approved call through the MCP server's own `tools/call`.
    True when the tool answered without an error. The tool's words are not
    returned: they reach the log only, never a player."""
    name = short_tool(tool)
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": name, "arguments": args if isinstance(args, dict) else {}}},
    ]
    env = {**os.environ, "BRAIN_CHANNEL": CHANNEL}
    env.pop("BRAIN_EXPOSED_ONLY", None)
    env.pop("BRAIN_ASSIST_ACCESS", None)
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, the add-on's own server
            _argv(), input="\n".join(json.dumps(x) for x in lines) + "\n",
            capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    for raw in proc.stdout.splitlines():
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("id") == 2:
            result = msg.get("result") if isinstance(msg.get("result"), dict) else {}
            return bool(result) and not result.get("isError")
    return False


__all__ = ["SOURCE", "SOURCE_TITLE", "as_row", "describe", "expired", "line", "listing",
           "record", "run_call", "same_call"]
