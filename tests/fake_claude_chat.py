#!/usr/bin/env python3
"""Stand-in for the Claude Code CLI in the shape the chat terminal drives it.

The chat session's whole job is turning `--output-format stream-json` into
something a browser can render, so the thing worth testing is the parsing —
which means the fixture has to emit the real event shapes, not a summary of
them: an assistant message carrying a thinking block, a text block and a
tool_use block, then the tool_result that comes back as a *user* event, then
the result envelope.

Behaviour switches via env:
  FAKE_CHAT_MODE  ok (default)     one full turn per user message
                  hang             read the message, never answer, but do
                                   honour a control_request interrupt — a
                                   current CLI
                  deaf             never answer and ignore control_request
                                   too — an older CLI, where the only way
                                   out is killing it
                  crash            exit non-zero mid-turn
                  error            answer with an is_error result envelope
  FAKE_CHAT_LOG   append each invocation's argv as a JSON line
"""

import json
import os
import sys
import time

argv = sys.argv[1:]

log_path = os.environ.get("FAKE_CHAT_LOG")
if log_path:
    with open(log_path, "a") as fh:
        fh.write(json.dumps(argv) + "\n")

mode = os.environ.get("FAKE_CHAT_MODE", "ok")

SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
if "--resume" in argv:
    SESSION = argv[argv.index("--resume") + 1]


def emit(obj):
    obj.setdefault("session_id", SESSION)
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


# The two events that describe the session rather than the conversation.
# `apiKeySource` is the CLI's own answer to "is anyone paying per token" —
# "none" means a subscription, where a per-message dollar figure is a number
# that looks like a charge and isn't one. FAKE_CHAT_APIKEY flips it.
emit({"type": "system", "subtype": "commands_changed", "commands": [
    {"name": "compact", "description": "Compact the conversation", "argumentHint": ""},
    {"name": "model", "description": "Change the model", "argumentHint": "[model]"},
    {"name": "context", "description": "Show what is in the context window",
     "argumentHint": ""},
    {"name": "__internal", "description": "plumbing nobody types", "argumentHint": ""},
]})
emit({"type": "system", "subtype": "init", "tools": ["Read", "Bash"],
      "model": "claude-sonnet-5", "cwd": os.getcwd(),
      "claude_code_version": "2.1.220",
      "apiKeySource": os.environ.get("FAKE_CHAT_APIKEY", "none"),
      "slash_commands": ["compact", "model", "context"]})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("type") == "control_request":
        if mode == "deaf":
            continue  # an older CLI: the request goes nowhere
        # A polite interrupt: acknowledge and close the turn, which is what
        # lets the session take the fast path instead of killing us.
        emit({"type": "control_response",
              "response": {"subtype": "success",
                           "request_id": msg.get("request_id")}})
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "stopped", "duration_ms": 10, "num_turns": 1})
        continue
    if msg.get("type") != "user":
        continue

    text = ""
    for block in (msg.get("message") or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")

    if mode in ("hang", "deaf"):
        continue
    if mode == "crash":
        sys.exit(3)

    # A partial-message delta, the way --include-partial-messages sends them.
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Look"}}})
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "ing…"}}})

    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "The user said: " + text},
        {"type": "text", "text": "Looking at `automations.yaml`."},
        {"type": "tool_use", "id": "toolu_1", "name": "Read",
         "input": {"file_path": "/config/automations.yaml"}},
    ]}})
    emit({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": [{"type": "text", "text": "- id: porch\n  alias: Porch"}]},
    ]}})
    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "You asked: " + text},
    ]}})

    if mode == "error":
        emit({"type": "result", "subtype": "error_max_turns", "is_error": True,
              "result": "", "duration_ms": 20, "num_turns": 9})
    else:
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "You asked: " + text, "duration_ms": 1234,
              "num_turns": 2, "total_cost_usd": 0.0123})

time.sleep(0.05)
