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
                  noresume         refuse --resume the way the real CLI
                                   refuses a session id its store no longer
                                   holds: an error on stderr and a non-zero
                                   exit before a single event is emitted.
                                   Without --resume it behaves like ok.
                  permission       ask `can_use_tool` over the control
                                   channel before the tool runs, the way the
                                   real CLI does with --permission-prompt-tool
                                   stdio: allow → the tool runs; deny → a
                                   tool_result error carrying the message
                  question         ask `can_use_tool` for AskUserQuestion.
                                   The real CLI expects the answers back
                                   INSIDE updatedInput (`answers`, question
                                   text → answer string) — an allow without
                                   them is answered with an error result,
                                   which is the failure this fixture exists
                                   to reproduce
                  oddcontrol       send a control_request of a subtype the
                                   panel has never heard of before answering,
                                   and only proceed once it gets a
                                   control_response back — a turn hangs on
                                   silence, the way a real CLI waiting on
                                   its control channel would
  FAKE_CHAT_NOPROMPTFLAG  refuse --permission-prompt-tool at startup the way
                                   a CLI from before the stdio value exists:
                                   name the flag on stderr and die unspoken
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

# A CLI from before `--permission-prompt-tool stdio` existed: refuses the
# flag by name and dies before a single event, which is the shape the
# session's fallback has to recognise.
if os.environ.get("FAKE_CHAT_NOPROMPTFLAG") \
        and "--permission-prompt-tool" in argv:
    print("Error: tool stdio (passed via --permission-prompt-tool) "
          "must be an MCP tool", file=sys.stderr)
    sys.exit(1)

SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
if "--resume" in argv:
    if mode == "noresume":
        print(f"No conversation found with session ID: "
              f"{argv[argv.index('--resume') + 1]}", file=sys.stderr)
        sys.exit(1)
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
# The init event announces the model the CLI actually resolved, which is the
# one it was handed on --model. Reporting a fixed id whatever the argv is what
# let two model bugs through: the meta line's name and the context window are
# both derived from this field, and a fixture that never changes it cannot
# tell "the flag was passed" from "the flag was read".
emit({"type": "system", "subtype": "init", "tools": ["Read", "Bash"],
      "model": (argv[argv.index("--model") + 1]
                if "--model" in argv else "claude-sonnet-5"),
      "cwd": os.getcwd(),
      "claude_code_version": "2.1.220",
      "apiKeySource": os.environ.get("FAKE_CHAT_APIKEY", "none"),
      "slash_commands": ["compact", "model", "context"]})

def finish_turn(text):
    """One full turn: deltas, two model calls, a tool round-trip, a result."""
    # A partial-message delta, the way --include-partial-messages sends them
    # — thinking first, because that is the order the model produces them.
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "thinking_delta",
                              "thinking": "The user said: "}}})
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": text}}})
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


# The control question in flight (permission / question / oddcontrol
# modes): request_id -> (kind, the user text the turn will answer once the
# control round-trip lands).
asked = {}

# What the question mode asks, in the real tool's input shape.
QUESTIONS_INPUT = {"questions": [
    {"question": "Which zone should this apply to?", "header": "Zone",
     "options": [{"label": "Zone 3", "description": "The blackberries"},
                 {"label": "All zones", "description": "Everything at once"}],
     "multiSelect": False},
]}

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
        subtype = (msg.get("request") or {}).get("subtype")
        if subtype == "initialize":
            # The SDK handshake: acknowledged, and nothing else happens —
            # a turn must NOT close here, or every spawn ends idle.
            emit({"type": "control_response",
                  "response": {"subtype": "success",
                               "request_id": msg.get("request_id"),
                               "response": {"commands": []}}})
            continue
        # A polite interrupt: acknowledge and close the turn, which is what
        # lets the session take the fast path instead of killing us.
        emit({"type": "control_response",
              "response": {"subtype": "success",
                           "request_id": msg.get("request_id")}})
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "stopped", "duration_ms": 10, "num_turns": 1})
        continue
    if msg.get("type") == "control_response":
        # The panel answering a control question of ours.
        response = (msg.get("response") or {})
        request_id = response.get("request_id")
        pending = asked.pop(request_id, None)
        if pending is None:
            continue
        kind, text = pending
        if kind == "odd":
            # Any answer at all — success or error — unblocks the turn.
            # Silence is the one thing that must not happen, and the test
            # proves it did not by seeing the turn complete.
            finish_turn(text)
            continue
        answer = response.get("response") or {}
        if answer.get("behavior") == "allow":
            # The real CLI validates updatedInput against the tool schema;
            # the fixture at least insists it came back.
            updated = answer.get("updatedInput")
            if not isinstance(updated, dict):
                emit({"type": "result", "subtype": "error_during_execution",
                      "is_error": True, "result": "allow without updatedInput",
                      "duration_ms": 5, "num_turns": 1})
                continue
            if kind == "question":
                # The answers ride INSIDE updatedInput — the exact contract
                # a generic Allow button breaks. An empty sheet is the bug.
                answers = updated.get("answers")
                if not isinstance(answers, dict) or not answers or not all(
                        isinstance(k, str) and isinstance(v, str) and v
                        for k, v in answers.items()):
                    emit({"type": "result",
                          "subtype": "error_during_execution",
                          "is_error": True,
                          "result": "AskUserQuestion allowed without answers",
                          "duration_ms": 5, "num_turns": 1})
                    continue
                emit({"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_q",
                     "content": [{"type": "text",
                                  "text": "User has answered your questions: "
                                  + ", ".join(f'"{k}"="{v}"'
                                              for k, v in answers.items())}]},
                ]}})
                emit({"type": "result", "subtype": "success",
                      "is_error": False, "result": "Thanks — proceeding.",
                      "duration_ms": 15, "num_turns": 1})
                continue
            finish_turn(text)
        else:
            emit({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result",
                 "tool_use_id": "toolu_q" if kind == "question"
                                else "toolu_perm",
                 "is_error": True,
                 "content": [{"type": "text",
                              "text": answer.get("message") or "denied"}]},
            ]}})
            emit({"type": "result", "subtype": "success", "is_error": False,
                  "result": "Understood — I won't run that.",
                  "duration_ms": 15, "num_turns": 1})
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
    if mode == "permission":
        # Ask before touching the tool, the way the real CLI does when
        # --permission-prompt-tool stdio is on the argv and the call is
        # outside the allow rules.
        request_id = f"perm-{len(asked) + 1}"
        asked[request_id] = ("perm", text)
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_perm", "name": "Bash",
             "input": {"command": "rm /tmp/x"}},
        ], "usage": {"input_tokens": 900, "output_tokens": 30}}})
        emit({"type": "control_request", "request_id": request_id,
              "request": {"subtype": "can_use_tool", "tool_name": "Bash",
                          "input": {"command": "rm /tmp/x"},
                          "tool_use_id": "toolu_perm"}})
        continue
    if mode == "question":
        # AskUserQuestion rides the same wire as any permission ask; what
        # differs is that the *answers* have to come back in updatedInput.
        request_id = f"q-{len(asked) + 1}"
        asked[request_id] = ("question", text)
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_q", "name": "AskUserQuestion",
             "input": QUESTIONS_INPUT},
        ], "usage": {"input_tokens": 900, "output_tokens": 30}}})
        emit({"type": "control_request", "request_id": request_id,
              "request": {"subtype": "can_use_tool",
                          "tool_name": "AskUserQuestion",
                          "input": QUESTIONS_INPUT,
                          "tool_use_id": "toolu_q"}})
        continue
    if mode == "oddcontrol":
        # A control request from a feature the panel has never heard of.
        # The turn does not move until SOMETHING comes back — the hang on
        # silence is the point.
        request_id = f"odd-{len(asked) + 1}"
        asked[request_id] = ("odd", text)
        emit({"type": "control_request", "request_id": request_id,
              "request": {"subtype": "shiny_new_thing",
                          "payload": {"anyone": "listening?"}}})
        continue

    finish_turn(text)

time.sleep(0.05)
