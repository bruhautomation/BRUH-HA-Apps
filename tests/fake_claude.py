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
                   | max_turns (one-shot: end every call on the CLI's own
                     turn cap — the `error_max_turns` envelope under
                     --output-format json, "Error: Reached max turns" on
                     stderr with exit 1 otherwise)
                   | max_turns_then_land (one-shot: as max_turns for a call
                     that is not a --resume, and a normal answer prefixed
                     "LANDED: " for one that is — the shape of a run that
                     tripped the guard and was landed on its own session)
                   | overloaded_then_ok (one-shot: the first call answers
                     the API's own 529 envelope, every later call answers
                     normally; "first" is remembered in FAKE_ONCE_FILE)
                   | structured (one-shot, --output-format json: a
                     --json-schema run answers `structured_output` —
                     FAKE_STRUCTURED, or {"ok": true} — UNLESS the run
                     denied every tool with `--disallowedTools "*"`,
                     which denies the CLI's own StructuredOutput tool
                     too: then it burns its turns and answers prose with
                     no `structured_output`, which is what the real CLI
                     did to every first look and snapshot card)
                   | ratelimited (one-shot: the account's usage limit,
                     the way the CLI words it in -p mode)
  FAKE_REJECT      comma-separated flag names this CLI does not know; a
                   call carrying one dies naming it, the way the real
                   arg parser does ("error: unknown option '--tools'")
  FAKE_SESSIONS_DIR  the CLI's transcript store, as a directory of empty
                   files named for session ids. A one-shot call that got
                   past the arg parser leaves one behind (it reached the
                   API), and a later `--session-id` naming an id already
                   there is refused the way the real CLI refuses it —
                   "Session ID … is already in use" — before any request
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
log_path = os.environ.get("FAKE_CLAUDE_LOG")
if log_path:
    # One write per invocation: the pool pre-warms a spare in the background,
    # so two fake CLIs can append at once, and three writes interleave with
    # a reader into a half-written JSON line.
    with open(log_path, "a") as fh:
        fh.write(json.dumps(argv) + "\n"
                 + "ENV BRAIN_DENIED_SERVICES="
                 + os.environ.get("BRAIN_DENIED_SERVICES", "") + "\n"
                 + "ENV BRAIN_EXPOSED_ONLY="
                 + os.environ.get("BRAIN_EXPOSED_ONLY", "") + "\n"
                 + "ENV CLAUDE_CODE_DISABLE_AUTO_MEMORY="
                 + os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "") + "\n"
                 + "ENV CLAUDE_CODE_DISABLE_ADVISOR_TOOL="
                 + os.environ.get("CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "") + "\n")

mode = os.environ.get("FAKE_MODE", "ok")

AUTH_ERROR = ("Failed to authenticate: OAuth session expired and could not "
              "be refreshed")
RATE_LIMITED = "You've hit your limit · resets 3pm (UTC)"

# The arg parser runs before anything else, so a flag this CLI does not
# know ends the call before it could have reached the API.
for flag in filter(None, (os.environ.get("FAKE_REJECT") or "").split(",")):
    if "--" + flag.strip() in argv:
        print(f"error: unknown option '--{flag.strip()}'", file=sys.stderr)
        sys.exit(1)

sessions_dir = os.environ.get("FAKE_SESSIONS_DIR") or ""

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
    json_out = "--output-format" in argv and \
        argv[argv.index("--output-format") + 1] == "json"
    # The session id the real CLI would report: a --resume names it, a
    # --session-id mints it, and otherwise the CLI picks its own.
    sid = "22222222-2222-2222-2222-222222222222"
    for flag in ("--resume", "--session-id"):
        if flag in argv:
            sid = argv[argv.index(flag) + 1]
    if sessions_dir:
        # The real CLI files every conversation it starts, and refuses to
        # start a second one under an id whose transcript already exists —
        # before any request, so the refusal costs nothing and answers
        # nothing. A `--resume` is the other way to name an id, and the
        # only one that may reuse it.
        record = os.path.join(sessions_dir, sid)
        if "--session-id" in argv and os.path.exists(record):
            print(f"Error: Session ID {sid} is already in use.",
                  file=sys.stderr)
            sys.exit(1)
        with open(record, "a"):
            pass
    if mode == "ratelimited":
        if json_out:
            print(json.dumps({
                "type": "result", "subtype": "success", "is_error": True,
                "result": RATE_LIMITED, "session_id": sid, "num_turns": 1,
                "duration_ms": 20,
            }))
        else:
            print(RATE_LIMITED)
        sys.exit(1)
    if mode == "structured" and json_out:
        envelope = {"type": "result", "subtype": "success",
                    "session_id": sid, "duration_ms": 40,
                    "usage": {"input_tokens": 10, "output_tokens": 5}}
        disallowed = argv[argv.index("--disallowedTools") + 1] \
            if "--disallowedTools" in argv else ""
        if "--json-schema" in argv and "*" in disallowed.split(","):
            # `*` denies the CLI's own StructuredOutput tool with every
            # other one. The run asks for it, is refused, asks again, and
            # gives up in prose — no `structured_output`, several turns
            # spent, and a parse that only works when the prose happens
            # to hold the object.
            envelope.update(is_error=False, num_turns=5,
                            result="I was unable to use the StructuredOutput "
                                   "tool, so here is my answer in words.")
        else:
            wanted = os.environ.get("FAKE_STRUCTURED") or '{"ok": true}'
            envelope.update(is_error=False, num_turns=2,
                            result=wanted)
            if "--json-schema" in argv:
                envelope["structured_output"] = json.loads(wanted)
        print(json.dumps(envelope))
        sys.exit(0)
    if mode == "overloaded_then_ok":
        once = os.environ.get("FAKE_ONCE_FILE") or ""
        first = bool(once) and not os.path.exists(once)
        if first:
            with open(once, "w") as fh:
                fh.write("1")
            msg = ("API Error: 529 Overloaded. This is a server-side issue, "
                   "usually temporary — try again in a moment.")
            if json_out:
                print(json.dumps({
                    "type": "result", "subtype": "success", "is_error": True,
                    "result": msg, "session_id": sid, "num_turns": 1,
                    "duration_ms": 50,
                }))
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)
    tripped = mode == "max_turns" or (
        mode == "max_turns_then_land" and "--resume" not in argv)
    if tripped:
        if json_out:
            print(json.dumps({
                "type": "result", "subtype": "error_max_turns",
                "is_error": True, "result": "", "session_id": sid,
                "num_turns": 5, "duration_ms": 50,
            }))
        else:
            print("Error: Reached max turns (5)", file=sys.stderr)
        sys.exit(1)
    if mode == "autherror":
        # -p mode prints the auth error to stdout as the whole "response"
        print(AUTH_ERROR)
    elif mode == "max_turns_then_land":
        text = os.environ.get("FAKE_LANDING_TEXT") or f"LANDED: {data}"
        if json_out:
            print(json.dumps({
                "type": "result", "subtype": "success", "is_error": False,
                "result": text, "session_id": sid, "num_turns": 1,
                "duration_ms": 30,
            }))
        else:
            print(text)
    else:
        print(f"ONESHOT: {data}")
