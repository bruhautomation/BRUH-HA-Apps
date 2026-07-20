#!/usr/bin/env python3
"""Stand-in for the Claude Code CLI used by test_assist_worker_pool.py.

Speaks just enough of the two invocation shapes the worker pool uses:

  stream mode  (--input-format stream-json): emits an init event, then one
               result event per user message, embedding its own PID so tests
               can prove process reuse.
  one-shot     (no --input-format): reads stdin, prints "ONESHOT: <text>".

Behavior switches via env:
  FAKE_CLAUDE_LOG  append each invocation's argv as a JSON line
  FAKE_MODE        ok (default) | hang (never answer) | crash (die after read)
                   | autherror (reply with the CLI's OAuth-expired error, the
                     way the real CLI does when a token refresh fails)
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
log_path = os.environ.get("FAKE_CLAUDE_LOG")
if log_path:
    with open(log_path, "a") as fh:
        fh.write(json.dumps(argv) + "\n")
        fh.write("ENV BRUH_DENIED_SERVICES="
                 + os.environ.get("BRUH_DENIED_SERVICES", "") + "\n")

mode = os.environ.get("FAKE_MODE", "ok")

AUTH_ERROR = ("Failed to authenticate: OAuth session expired and could not "
              "be refreshed")

if "--input-format" in argv:
    sid = "11111111-1111-1111-1111-111111111111"
    if "--resume" in argv:
        sid = argv[argv.index("--resume") + 1]
    print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}),
          flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        text = msg["message"]["content"][0]["text"]
        if mode == "hang":
            time.sleep(60)
            continue
        if mode == "crash":
            sys.exit(1)
        if mode == "autherror":
            # the real CLI marks the result event as an error
            print(json.dumps({
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "result": AUTH_ERROR,
                "session_id": sid,
            }), flush=True)
            continue
        result = f"OK[{os.getpid()}]: {text}"
        if "--include-partial-messages" in argv:
            # Mirror the real CLI: token-level stream_event deltas, then an
            # assistant message event with the full text, then the result.
            half = len(result) // 2
            for chunk in (result[:half], result[half:]):
                print(json.dumps({
                    "type": "stream_event",
                    "event": {"type": "content_block_delta",
                              "delta": {"type": "text_delta", "text": chunk}},
                    "session_id": sid,
                }), flush=True)
            print(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": result}]},
                "session_id": sid,
            }), flush=True)
        print(json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result,
            "session_id": sid,
        }), flush=True)
else:
    data = sys.stdin.read()
    if mode == "hang":
        time.sleep(60)
    if mode == "autherror":
        # -p mode prints the auth error to stdout as the whole "response"
        print(AUTH_ERROR)
    else:
        print(f"ONESHOT: {data}")
