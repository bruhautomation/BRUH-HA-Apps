#!/usr/bin/env python3
"""devloop-guard: what an automated PR may not do, enforced by CI.

The fixer's instructions say all of this too; this is the half that does
not depend on a model reading them. It runs on pull requests whose head
branch starts with `devloop/` and fails on any of:

* a change to a `version_only_files` file other than its version line (the base
  branch's `.claude/devloop.json` is read, so a PR cannot loosen it);
* a deleted test file, or a line that skips or deletes a test;
* a change to the add-ons' code (Python, shell, the integrations) with no
  change under `tests/`: the skill says "failing test first", and this is
  the half that holds when a model does not read it. Copy, layout and
  docs are exempt, because a measure is run by hand and CI's `layout` job.

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
# What counts as code: a change here with nothing under tests/ is a fix
# nobody proved. The panel's HTML, CSS, JS and the docs are not on it.
CODE_RE = re.compile(
    r"^(?:brain/panel/.*\.py|brain/scripts/.*|brain/integrations/.*|"
    r"brain/custom_components/.*\.py|brain/ha-mcp-server/.*|"
    r"brain/morph/service/.*\.py|"
    r"bruh-print/.*\.py|bruh-bambu-studio/.*\.py|bright/.*\.py|bruh-minecraft-server/.*\.py|bruh-task-manager/.*\.py|"
    r"gardenrx/(?:app/src|gateway)/.*\.(?:ts|tsx|mjs|js)|gardenrx/custom_components/.*\.py)$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout


def main(base: str) -> int:
    config = json.loads(git("show", f"{base}:.claude/devloop.json"))
    version_only = set(config.get("version_only_files") or [])
    problems: list[str] = []
    code_changed: list[str] = []
    tests_changed = False
    for line in git("diff", "--name-status", f"{base}...HEAD").splitlines():
        parts = line.split("\t")
        status, paths = parts[0], parts[1:]
        for path in paths:
            if status.startswith("D") and path.startswith("tests/"):
                problems.append(f"{path}: a test file was deleted")
            if path.startswith("tests/"):
                tests_changed = True
            elif CODE_RE.match(path) and not status.startswith("D"):
                code_changed.append(path)
    if code_changed and not tests_changed:
        problems.append("a code change with no test change: "
                        + ", ".join(code_changed[:5])
                        + (" …" if len(code_changed) > 5 else ""))
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
        print("devloop-guard: fix the rule this PR broke, then push again.")
        return 1
    print("devloop-guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
