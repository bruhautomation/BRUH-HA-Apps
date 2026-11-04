#!/usr/bin/env python3
"""A stand-in `claude` for the runner's own tests: no model, no network.

It answers ``-p --output-format json`` the way the CLI does — an envelope
with ``result``, ``usage``, ``modelUsage`` and, when a ``--json-schema``
was passed, ``structured_output`` — from ``EVALS_FAKE_REPLIES``, a JSON
file mapping a marker to a reply: the first marker found in the prompt
(stdin) or the system prompt wins, ``"*"`` is the fallback. A reply is a
string (the result text) or an object (the structured output, also
serialised as the text). Every call's argv is appended to
``EVALS_FAKE_LOG`` so a test can see what was asked and with which flags.
"""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("0.0.0 (fake)")
        return 0
    prompt = sys.stdin.read()
    system = argv[argv.index("--system-prompt") + 1] if "--system-prompt" in argv else ""
    model = argv[argv.index("--model") + 1] if "--model" in argv else ""
    log = os.environ.get("EVALS_FAKE_LOG", "")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "prompt": prompt[:4000]}) + "\n")
    with open(os.environ["EVALS_FAKE_REPLIES"], encoding="utf-8") as fh:
        replies = json.load(fh)
    reply = replies.get("*")
    for marker, value in replies.items():
        if marker != "*" and (marker in prompt or marker in system):
            reply = value
            break
    envelope = {"type": "result", "subtype": "success", "is_error": False,
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "modelUsage": {model: {}} if model else {}}
    if isinstance(reply, (dict, list)):
        envelope["result"] = json.dumps(reply)
        if "--json-schema" in argv:
            envelope["structured_output"] = reply
    else:
        envelope["result"] = str(reply if reply is not None else "")
    print(json.dumps(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
