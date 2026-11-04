#!/usr/bin/env python3
"""The `claude` the consolidator is handed during an eval.

The consolidator is a shell script that builds its own prompt and reads its
own reply, so the eval runs the script whole rather than a copy of its
prompt (`BRAIN_CLAUDE_BIN` is the script's documented seam). This stands in
for the binary: it runs the real CLI (or ``EVALS_CLAUDE_BIN``) with the
script's arguments plus the isolation every eval run gets, passes stdin and
stdout through untouched, and appends the CLI's envelope to
``EVALS_TEE_LOG`` so the runner can count the tokens and the model the
pass really ran on.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys


def main(argv: list[str]) -> int:
    override = os.environ.get("EVALS_CLAUDE_BIN", "").strip()
    base = shlex.split(override) if override else ["claude"]
    extra = ["--strict-mcp-config", "--setting-sources", ""]
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    proc = subprocess.run(base + argv + extra, input=sys.stdin.read(),
                          capture_output=True, text=True, env=env, check=False)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    log = os.environ.get("EVALS_TEE_LOG", "")
    if log:
        try:
            envelope = json.loads(proc.stdout or "")
        except ValueError:
            envelope = {"unparsed": (proc.stdout or "")[:200]}
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"rc": proc.returncode,
                                 "envelope": envelope}) + "\n")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
