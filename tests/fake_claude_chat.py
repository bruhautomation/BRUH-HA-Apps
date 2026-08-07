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
                  noresume         refuse --resume the way an older CLI
                                   does: an error on stderr and a non-zero
                                   exit before a single event is emitted.
                                   Without --resume it behaves like ok.
                  noresume-live    refuse --resume the way a current CLI
                                   (2.1.x, observed) does: an in-band error
                                   `result` event on stdout carrying "No
                                   conversation found with session ID",
                                   stderr repeating it, and a moment of
                                   lingering before the exit — the shape
                                   that made a death-watch alone a coin
                                   flip. Without --resume it behaves like
                                   ok.
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

# A CLI that cannot start at all — bad install, dead credential. Dies before
# emitting a single event, whatever the argv, with its reason on stderr.
if os.environ.get("FAKE_CHAT_BROKEN"):
    print("Invalid API key · Please run /login", file=sys.stderr)
    sys.exit(1)

SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
if "--resume" in argv:
    rid = argv[argv.index("--resume") + 1]
    if mode == "noresume":
        print(f"No conversation found with session ID: {rid}",
              file=sys.stderr)
        sys.exit(1)
    if mode == "noresume-live":
        print(json.dumps({
            "type": "result", "subtype": "error_during_execution",
            "is_error": True, "num_turns": 0, "session_id": rid,
            "errors": [f"No conversation found with session ID: {rid}"],
        }), flush=True)
        print(f"No conversation found with session ID: {rid}",
              file=sys.stderr)
        time.sleep(0.3)
        sys.exit(1)
    SESSION = rid


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

    # Per-call usage, on every assistant message. Two calls in this turn,
    # each re-sending the conversation — so the second call's numbers are
    # the context size and the two added together are not.
    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "The user said: " + text},
        {"type": "text", "text": "Looking at `automations.yaml`."},
        {"type": "tool_use", "id": "toolu_1", "name": "Read",
         "input": {"file_path": "/config/automations.yaml"}},
    ], "usage": {"input_tokens": 1200, "cache_read_input_tokens": 40_000,
                 "output_tokens": 120}}})
    emit({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": [{"type": "text", "text": "- id: porch\n  alias: Porch"}]},
    ]}})
    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "You asked: " + text},
    ], "usage": {"input_tokens": 300, "cache_read_input_tokens": 41_500,
                 "output_tokens": 40}}})

    if mode == "error":
        emit({"type": "result", "subtype": "error_max_turns", "is_error": True,
              "result": "", "duration_ms": 20, "num_turns": 9})
    else:
        # The result envelope's usage is the whole turn added up — both
        # calls — which is work done, not conversation size. Emitted here
        # precisely so a test can prove the panel does not read it.
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "You asked: " + text, "duration_ms": 1234,
              "num_turns": 2, "total_cost_usd": 0.0123,
              "usage": {"input_tokens": 1500,
                        "cache_read_input_tokens": 81_500,
                        "output_tokens": 160}})

time.sleep(0.05)
