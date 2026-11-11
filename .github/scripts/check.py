#!/usr/bin/env python3
"""Every check a change has to pass, in one command and a few seconds.

    python3 .github/scripts/check.py                    # what CI runs
    python3 .github/scripts/check.py --base origin/main # plus the version bump

It answers one question: would this change break an install? In order:

  lint      ruff over every Python file (a syntax error or an undefined name)
  syntax    `node --check` on the panels' JavaScript, `bash -n` on the scripts
  manifests every add-on's YAML and JSON parses; config.yaml, the
            integration's manifest and the changelog agree on the version
  bump      (with --base) an add-on whose files changed has a new version,
            or Home Assistant never offers the update
  tests     the small suite in tests/: the action gate, protected entities,
            the tripwire, house rules, camera policy, service gates,
            redaction, add-on download hashes, the devloop's own gates

There is deliberately nothing slow here. A check that takes minutes is run
less often than one that takes seconds, and this is the only gate there is.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# Built by their own toolchains (TypeScript, bundlers), not loadable as-is.
NOT_PLAIN_JS = ("gardenrx/app/", "bruh-cooking/frontend/")
NOT_SHIPPED = ("CHANGELOG.md", "README.md", "DOCS.md")
problems: list[str] = []


def run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)


def tracked(*patterns: str) -> list[str]:
    return run("git", "ls-files", *patterns).stdout.split("\n")[:-1]


def step(name: str, fn) -> None:
    before, started = len(problems), time.monotonic()
    fn()
    mark = "ok  " if len(problems) == before else "FAIL"
    print(f"{mark} {name:<10} {time.monotonic() - started:5.1f}s", flush=True)


def lint() -> None:
    done = run("ruff", "check", ".", "--quiet")
    if done.returncode:
        problems.append("ruff:\n" + (done.stdout + done.stderr).strip())


def _syntax_of(path: str) -> str | None:
    if path.endswith((".js", ".mjs")):
        done = run("node", "--check", path)
    else:
        done = run("bash", "-n", path)
    return None if done.returncode == 0 else f"{path}: {done.stderr.strip()[-400:]}"


def syntax() -> None:
    files = [p for p in tracked("*.js", "*.mjs")
             if not p.startswith(NOT_PLAIN_JS) and not p.endswith(".min.js")]
    for path in tracked():
        if path.endswith((".js", ".mjs", ".py", ".md", ".json", ".yaml")):
            continue
        try:
            with open(ROOT / path, "rb") as fh:
                first = fh.readline(120)
        except OSError:
            continue
        if first.startswith(b"#!") and (b"bash" in first or first.strip() == b"#!/bin/sh"):
            files.append(path)
    with ThreadPoolExecutor(8) as pool:
        problems.extend(p for p in pool.map(_syntax_of, files) if p)


def _version(config: Path) -> str:
    match = re.search(r'^version:\s*"?([^"\s]+)"?', config.read_text(), re.M)
    return match.group(1) if match else ""


def addons() -> list[Path]:
    return sorted(p.parent for p in ROOT.glob("*/config.yaml"))


def manifests() -> None:
    import yaml
    for path in tracked("*/config.yaml", "*/build.yaml", "*/translations/*.yaml",
                        "repository.yaml", "*/custom_components/*/services.yaml"):
        try:
            yaml.safe_load((ROOT / path).read_text())
        except yaml.YAMLError as exc:
            problems.append(f"{path}: not valid YAML: {exc}")
    for path in tracked("*/custom_components/*/*.json",
                        "*/custom_components/*/translations/*.json"):
        try:
            json.loads((ROOT / path).read_text())
        except ValueError as exc:
            problems.append(f"{path}: not valid JSON: {exc}")
    for addon in addons():
        version = _version(addon / "config.yaml")
        if not version:
            problems.append(f"{addon.name}/config.yaml: no version")
            continue
        for manifest in addon.glob("custom_components/*/manifest.json"):
            theirs = json.loads(manifest.read_text()).get("version")
            if theirs != version:
                problems.append(f"{addon.name}: config.yaml is {version} but "
                                f"{manifest.relative_to(ROOT)} is {theirs}")
        changelog = addon / "CHANGELOG.md"
        if changelog.exists():
            top = re.search(r"^##\s+\[?v?(\d+\.\d+\.\d+)", changelog.read_text(), re.M)
            if not top or top.group(1) != version:
                problems.append(f"{addon.name}: config.yaml is {version} but the "
                                f"changelog's newest entry is "
                                f"{top.group(1) if top else 'missing'}")


def bump(base: str) -> None:
    for addon in addons():
        changed = [p for p in run("git", "diff", "--name-only", f"{base}...HEAD",
                                  "--", f"{addon.name}/").stdout.split()
                   if Path(p).name not in NOT_SHIPPED]
        if not changed:
            continue
        before = run("git", "show", f"{base}:{addon.name}/config.yaml")
        match = re.search(r'^version:\s*"?([^"\s]+)"?', before.stdout, re.M)
        if match and match.group(1) == _version(addon / "config.yaml"):
            problems.append(f"{addon.name}: {len(changed)} file(s) changed "
                            f"({changed[0]} …) but the version is still "
                            f"{match.group(1)}; bump config.yaml, the manifest "
                            "and the changelog")


def tests() -> None:
    done = run(sys.executable, "-m", "pytest")
    if done.returncode:
        problems.append("pytest:\n" + done.stdout[-6000:] + done.stderr[-2000:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="also require a version bump against this ref")
    args = ap.parse_args()
    started = time.monotonic()
    step("lint", lint)
    step("syntax", syntax)
    step("manifests", manifests)
    if args.base:
        step("bump", lambda: bump(args.base))
    step("tests", tests)
    print(f"{'FAILED' if problems else 'passed'} in {time.monotonic() - started:.1f}s")
    for problem in problems:
        print("\n" + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
