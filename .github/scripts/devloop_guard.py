#!/usr/bin/env python3
"""devloop-guard: what an automated PR may not do, enforced by CI.

The fixer's instructions say all of this too; this is the half that does
not depend on a model reading them. CI runs it on every pull request whose
head branch starts with `devloop` -- and it runs THIS file as the BASE
branch holds it (the workflow is `pull_request_target` and takes the script
with `git show origin/<base>:...`), so a PR can never edit the grader that
judges it. `.claude/devloop.json` is read from the base branch too.

Two rules, on every `devloop*` branch:

* it may not touch a `grader_paths` file (this guard, the workflows, the
  skill, the checks CI runs). Those change only in a pull request a person
  asked for, on a branch that is not a devloop branch. One exception: a
  `devloop-meta/` branch may change the `retro_paths` files, the lessons
  the loop's own retro records (tier M);
* a `version_only_files` file may change only its version line.

It also prints the PR's risk tier (`tier=X`, and to `$GITHUB_OUTPUT`): A copy,
UI, docs or tests; B logic inside one add-on; C a safety area or logic across
add-ons. The path lists are data in `devloop.json`'s `tiers`, read from base.

It no longer asks for a test with every code change. That rule grew the
suite to the size of the product without making a release safer; the small
suite in `tests/` holds the things that must never break, and it is a
grader path, so a devloop PR cannot weaken it.

Usage: devloop_guard.py <base-ref> [--branch NAME]   (from the repository root)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

CONFIG_PATH = ".claude/devloop.json"
VERSION_RE = re.compile(r'^[+-]\s*("?version"?\s*:|version:)')
TEST_DIRS = ("tests/", "bruh-cooking/tests/", "bruh-cooking/frontend/test/")
JS_TEST_FILE = re.compile(r"\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs)$")

TIER_MEANING = {
    "A": "copy, UI, docs or tests: one independent reviewer",
    "B": "logic inside one add-on: one independent reviewer and the house canary",
    "C": "a safety area, or logic across add-ons: two independent reviewers "
         "and the house canary",
    "M": "the retro's lessons: two independent reviewers",
}


def git(*args: str, cwd=None) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, cwd=cwd).stdout


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


_GLOBS: dict[str, re.Pattern] = {}


def glob_re(pattern: str) -> re.Pattern:
    """`**` crosses folders, `*` and `?` do not."""
    if pattern not in _GLOBS:
        out, i = "", 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                out, i = out + "(?:.*/)?", i + 3
            elif pattern.startswith("**", i):
                out, i = out + ".*", i + 2
            elif pattern[i] == "*":
                out, i = out + "[^/]*", i + 1
            elif pattern[i] == "?":
                out, i = out + "[^/]", i + 1
            else:
                out, i = out + re.escape(pattern[i]), i + 1
        _GLOBS[pattern] = re.compile(out + r"\Z")
    return _GLOBS[pattern]


def matches(path: str, globs) -> bool:
    return any(glob_re(g).match(path) for g in globs or ())


def is_test_file(path: str) -> bool:
    return path.startswith(TEST_DIRS) or bool(JS_TEST_FILE.search(path))


def judge(base: str, branch: str = ""):
    """(tier, problems) for HEAD against `base`; problems are (rule, detail)."""
    config = json.loads(git("show", f"{base}:{CONFIG_PATH}"))
    merge_base = git("merge-base", base, "HEAD").strip()
    changes: list[tuple[str, str]] = []
    for line in git("diff", "--name-status", "--no-renames", merge_base,
                    "HEAD").splitlines():
        status, path = line.split("\t", 1)
        changes.append((status[0], path))
    problems: list[tuple[str, str]] = []

    touched = sorted(p for _, p in changes
                     if matches(p, config.get("grader_paths") or []))
    # The retro keeps its lessons in a devloop-meta/ PR, and that is all it
    # may keep there: the files named in `retro_paths`, nothing that judges.
    retro = branch.startswith("devloop-meta/")
    refused = [p for p in touched
               if not (retro and matches(p, config.get("retro_paths") or []))]
    if refused:
        problems.append(("grader", "a devloop PR may not change what judges "
                         "it: " + ", ".join(refused[:5])))

    version_ok: set[str] = set()
    version_only = set(config.get("version_only_files") or [])
    for path in sorted(version_only & {p for _, p in changes}):
        diff = git("diff", merge_base, "HEAD", "--", path)
        bad = next((ln for ln in diff.splitlines()
                    if ln[:1] in ("+", "-") and not ln.startswith(("+++", "---"))
                    and not VERSION_RE.match(ln)), None)
        if bad is None:
            version_ok.add(path)
        else:
            problems.append(("version-only", f"{path}: only the version line "
                             f"may change ({bad[:80]})"))

    tier = classify(changes, config, version_ok, refused)
    return ("M" if retro and touched and not refused else tier), problems


def classify(changes, config, version_ok, touched_graders) -> str:
    """The risk tier, from paths alone (lists in devloop.json's `tiers`)."""
    tiers = config.get("tiers") or {}
    if touched_graders or any(matches(p, tiers.get("C")) for _, p in changes):
        return "C"
    addons, outside = set(), False
    for _, path in changes:
        if (matches(path, tiers.get("A")) or path in version_ok
                or is_test_file(path)):
            continue
        top = path.split("/", 1)[0]
        if "/" in path and top in (tiers.get("addons") or []):
            addons.add(top)
        else:
            outside = True
    if outside or len(addons) > 1:
        return "C"
    return "B" if addons else "A"


def report(tier: str, problems, branch: str) -> int:
    for rule, detail in problems:
        print(f"devloop-guard: [{rule}] {detail}")
    print(f"tier={tier}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"tier={tier}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"## devloop-guard: `{branch}`", "",
                 f"**Tier {tier}**: {TIER_MEANING.get(tier, '')}", ""]
        if problems:
            lines += ["**Problems:**", ""]
            lines += [f"- `{rule}`: {detail}" for rule, detail in problems]
        else:
            lines.append("No problems.")
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    if problems:
        print("devloop-guard: fix the rule this PR broke, then push again.")
        return 1
    print("devloop-guard: ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base", nargs="?", default="origin/main")
    ap.add_argument("--branch", help="the PR's head branch (default: the "
                    "checked-out branch)")
    args = ap.parse_args(argv)
    branch = args.branch or git("rev-parse", "--abbrev-ref", "HEAD").strip()
    tier, problems = judge(args.base, branch)
    return report(tier, problems, branch)


if __name__ == "__main__":
    sys.exit(main())
