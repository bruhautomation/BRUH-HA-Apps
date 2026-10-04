#!/usr/bin/env python3
"""UserPromptSubmit hook: what brAIn remembers about the message being sent.

The chat had no memory pushed at it at all. Every scheduled run is handed
the facts about the entities it reads (`facts_store.retrieval_block`), and
the face where the most knowledgeable person in the house types the most
was handed the boot-time `/config/CLAUDE.md` and nothing about the message
in front of it. This is that retrieval, for the chat, hung off Claude
Code's own ``UserPromptSubmit`` hook: the CLI pipes ``{session_id,
transcript_path, cwd, hook_event_name, prompt}`` in on stdin and adds
whatever the hook prints as ``additionalContext`` to the turn.

It is wired in the CHAT's own ``--settings`` (``chat_session._settings``)
and nowhere else — the project settings file is read by voice and the
listeners too, and a synchronous hook ahead of every voice turn is latency
somebody can hear.

Three rules.

**It is plumbing, not a second retrieval.** The panel owns the facts store
and the registry the last checks pass saw, so this asks it
(``POST /api/chat/context`` over loopback, ``explain_change``'s
arrangement) and prints what comes back. A second copy of "which facts
are relevant" here would be a third answer beside the cards' and the
brief's.

**It is bounded.** A message waits on this, so the request has a short
budget well inside the CLI's own hook timeout, and nothing else is done.

**It never blocks the prompt.** For this event exit 2 BLOCKS the message,
and Python exits 2 on its own for a usage error — so every path ends in
``exit 0``, and a failure of any kind adds nothing rather than refusing
what somebody typed.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

PANEL_URL = os.environ.get("BRAIN_PANEL_URL", "http://127.0.0.1:8099")
# Seconds. The CLI's own ceiling for this hook is longer
# (`chat_session.CONTEXT_HOOK_TIMEOUT`); this is what a message waits at most.
BUDGET_S = float(os.environ.get("BRAIN_CHAT_CONTEXT_BUDGET", "2.0"))
MAX_PROMPT = 4000
MAX_CONTEXT = 4000


def context_for(prompt: str, session_id: str = "") -> str:
    """The panel's answer for this message, or "" for anything else.

    ``session_id`` is the CLI's, passed on so the panel hands one
    conversation each fact once rather than with every message."""
    body = json.dumps({"prompt": str(prompt or "")[:MAX_PROMPT],
                       "session_id": str(session_id or "")[:128]}).encode()
    request = urllib.request.Request(
        f"{PANEL_URL}/api/chat/context", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    # Loopback, never through a proxy an environment happens to name.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=BUDGET_S) as response:
        answer = json.loads(response.read().decode("utf-8", "replace"))
    text = answer.get("context") if isinstance(answer, dict) else ""
    return str(text or "")[:MAX_CONTEXT]


def main(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        event = json.loads(stdin.read() or "{}")
        prompt = event.get("prompt") if isinstance(event, dict) else ""
        if not isinstance(prompt, str) or not prompt.strip():
            return 0
        text = context_for(prompt, event.get("session_id") or "")
        if text.strip():
            stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            }}))
    except Exception:  # noqa: BLE001 — a hook that fails adds nothing
        return 0
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001
        code = 0
    sys.exit(code)
