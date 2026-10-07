#!/usr/bin/env python3
"""devloop-guard: what an automated PR may not do, enforced by CI.

The fixer's instructions say all of this too; this is the half that does
not depend on a model reading them. It runs on pull requests whose head
branch starts with `devloop/` and fails on any of:

* a changed file under one of `.claude/devloop.json`'s `needs_human_paths`
  (the base branch's copy is read, so a PR cannot loosen its own guard);
* a change to a `version_only_files` file other than its version line;
* a deleted test file, or a line that skips or deletes a test.

Usage: devloop_guard.py <base-ref>   (run from the repository root)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

SKIP_RE = re.compile(
    r"^\+.*(@unittest\.skip|\.skipTest\(|pytest\.mark\.(skip|xfail)|@skip\b|"
    r"\bxit\(|\.skip\(|it\.skip|describe\.skip)")
VERSION_RE = re.compile(r'^[+-]\s*("?version"?\s*:|version:)')


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout


def main(base: str) -> int:
    config = json.loads(git("show", f"{base}:.claude/devloop.json"))
    protected = config.get("needs_human_paths") or []
    version_only = set(config.get("version_only_files") or [])
    problems: list[str] = []
    for line in git("diff", "--name-status", f"{base}...HEAD").splitlines():
        parts = line.split("\t")
        status, paths = parts[0], parts[1:]
        for path in paths:
            if any(path == p or (p.endswith("/") and path.startswith(p))
                   for p in protected):
                problems.append(f"{path} is on needs_human_paths")
            if status.startswith("D") and path.startswith("tests/"):
                problems.append(f"{path}: a test file was deleted")
    for path in version_only:
        diff = git("diff", f"{base}...HEAD", "--", path)
        for line in diff.splitlines():
            if line.startswith(("+++", "---")) or line[:1] not in ("+", "-"):
                continue
            if not VERSION_RE.match(line):
                problems.append(f"{path}: only the version line may change ({line[:80]})")
                break
    tests_diff = git("diff", "--unified=0", f"{base}...HEAD", "--", "tests/")
    for line in tests_diff.splitlines():
        if SKIP_RE.match(line):
            problems.append(f"a test was skipped: {line[:100]}")
    removed = sum(1 for ln in tests_diff.splitlines()
                  if re.match(r"^-\s*def test_", ln))
    added = sum(1 for ln in tests_diff.splitlines()
                if re.match(r"^\+\s*def test_", ln))
    if removed > added:
        problems.append(f"{removed - added} test function(s) removed")
    for p in problems:
        print(f"devloop-guard: {p}")
    if problems:
        print("devloop-guard: this PR needs a person. Label it needs-human.")
        return 1
    print("devloop-guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
