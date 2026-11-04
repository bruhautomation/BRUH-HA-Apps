#!/usr/bin/env python3
"""devloop-guard: what an automated PR may not do, enforced by CI.

The fixer's instructions say all of this too; this is the half that does
not depend on a model reading them. CI runs it on every pull request whose
head branch starts with `devloop` -- and it runs THIS file as the BASE
branch holds it (the workflow is `pull_request_target` and takes the script
with `git show origin/<base>:...`), so a PR can never edit the grader that
judges it. Everything it reads to decide (`.claude/devloop.json`,
`tests/affected.py`, the frozen cases) is read from the base branch too.

Three kinds of branch, by prefix:

* `devloop/`      a fix. It may not touch a `grader_paths` file, may not
                  change or remove a line of a test file that exists on
                  base (adding is fine), may not lose a test by name, may not
                  skip one, and a code change needs an ADDED test in a file
                  `tests/affected.py` selects for that code.
* `devloop-test/` a test dispute. It may change existing tests -- and
                  nothing outside the tests -- and gets tier T, so the skill
                  knows an independent reviewer must agree the old assertion
                  contradicts what the house observed. Skips and deleted
                  test files still fail.
* `devloop-meta/` a grader change. It may touch `grader_paths`, and then the
                  MONOTONIC check must pass: the base guard and the PR's
                  guard both run over every frozen case in
                  `tests/devloop_guard_cases/`, and the PR's guard must flag
                  every case the base guard flags. Only here is any code from
                  the PR executed, in a subprocess with a scrubbed
                  environment (no secrets, no token) under a timeout.

On every branch: a `version_only_files` file may change only its version
line, and a deleted test file fails.

It also prints the PR's risk tier (`tier=X`, and to `$GITHUB_OUTPUT`): A copy,
UI, docs or test additions; B logic inside one add-on; C a safety area or
logic across add-ons; T a test dispute; M a grader change. The path lists
are data in `devloop.json`'s `tiers`, read from base.

Usage: devloop_guard.py <base-ref> [--branch NAME]   (from the repository root)
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD_PATH = ".github/scripts/devloop_guard.py"
CONFIG_PATH = ".claude/devloop.json"
AFFECTED_PATH = "tests/affected.py"
CASES_DIR = "tests/devloop_guard_cases/"
# Set inside a monotonic run, so a case that is itself a devloop-meta/ PR
# does not start a second monotonic run inside the first.
NESTED_ENV = "DEVLOOP_GUARD_NESTED"
CASE_TIMEOUT = 120  # seconds, per guard per case

# A skip in any of its spellings, matched on an ADDED line: `@skipIf(` and
# `@skipUnless(` imported bare, and a `SkipTest` raised from inside a test,
# skip it as surely as `@unittest.skip` does and were let through once. The
# JS half: `it.skip`, `xit`, `describe.skip`, `.todo`, and `.only`/`fit`,
# which skip every OTHER test in the file.
SKIP_RE = re.compile(
    r"(@unittest\.skip|\.skipTest\(|pytest\.mark\.(skip|xfail)|@skip\b|"
    r"@skip\w*\(|\bSkipTest\(|importorskip\(|"
    r"\bxit\(|\bxtest\(|\bxdescribe\(|\bfit\(|\bfdescribe\(|"
    r"\.skip\(|\.skipIf\(|\.only\(|\.todo\(|it\.skip|describe\.skip)")
VERSION_RE = re.compile(r'^[+-]\s*("?version"?\s*:|version:)')
# What counts as code: a change here needs a test that can see it. The
# panels' HTML, CSS and JS and the docs are not on it (tier A, measured by
# hand and by CI's layout job).
CODE_RE = re.compile(
    r"^(?:brain/panel/.*\.py|brain/scripts/.*|brain/integrations/.*|"
    r"brain/custom_components/.*\.py|brain/ha-mcp-server/.*|"
    r"brain/morph/service/.*\.py|"
    r"bruh-print/.*\.py|bruh-bambu-studio/.*\.py|bright/.*\.py|bruh-minecraft-server/.*\.py|bruh-task-manager/.*\.py|"
    r"gardenrx/(?:app/src|gateway)/.*\.(?:ts|tsx|mjs|js)|gardenrx/custom_components/.*\.py|"
    r"bruh-cooking/custom_components/.*\.py|bruh-cooking/frontend/src/.*\.ts)$")
# Where tests live: the repository's suite, the two BRUH Cooking keeps beside
# its code, and any `*.test.ts`-style file beside its source (GardenRX).
TEST_DIRS = ("tests/", "bruh-cooking/tests/", "bruh-cooking/frontend/test/")
JS_TEST_FILE = re.compile(r"\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs)$")
MEASURE_FILE = re.compile(r"^tests/manual/measure-[^/]+\.mjs$")
PY_TEST_NAME = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test\w*)[ \t]*\(",
                          re.M)
JS_TEST_NAME = re.compile(
    r"""^[ \t]*(?:it|test)(?:\.\w+)?[ \t]*\([ \t]*(['"`])(.+?)\1""", re.M)
# What makes an added line in a browser measure a check rather than prose.
MEASURE_CHECK = re.compile(r"\bassert|\bfail\(|throw new Error|\bexpect\(")

TIER_MEANING = {
    "A": "copy, UI, docs or test additions: one independent reviewer",
    "B": "logic inside one add-on: one independent reviewer and the house canary",
    "C": "a safety area, or logic across add-ons: two independent reviewers "
         "and the house canary",
    "T": "a test dispute: an independent reviewer must agree the old "
         "assertion contradicts what the house observed",
    "M": "a grader change: the base guard proved the new one is no looser",
}


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def git(*args: str, cwd=None) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, cwd=cwd).stdout


def show(ref: str, path: str, cwd=None) -> str | None:
    done = subprocess.run(["git", "show", f"{ref}:{path}"],
                          capture_output=True, text=True, cwd=cwd)
    return done.stdout if done.returncode == 0 else None


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


def test_names(path: str, text: str | None) -> collections.Counter:
    """Every test in a file by name, counted (a name may repeat across
    classes). Python `def test_*`, and JS `it("…")` / `test("…")`."""
    if not text:
        return collections.Counter()
    if path.endswith(".py"):
        return collections.Counter(PY_TEST_NAME.findall(text))
    if path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
        return collections.Counter(m.group(2) for m in JS_TEST_NAME.finditer(text))
    return collections.Counter()


def branch_kind(branch: str) -> str:
    if branch.startswith("devloop-meta/"):
        return "meta"
    if branch.startswith("devloop-test/"):
        return "test"
    return "fix"   # devloop/, and anything else is held to the strictest


# ---------------------------------------------------------------------------
# tests/affected.py, from base
# ---------------------------------------------------------------------------


def load_affected(base: str, tmp: str):
    """tests/affected.py as the base branch holds it, imported from a
    temporary directory (never the PR's copy)."""
    text = show(base, AFFECTED_PATH)
    if text is None:
        return None
    path = Path(tmp) / "devloop_guard_affected.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("devloop_guard_affected", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # dataclasses look their module up
    try:
        spec.loader.exec_module(module)
    except Exception:   # noqa: BLE001 - a base that cannot load fails closed
        sys.modules.pop(spec.name, None)
        return None
    return module


def selection_for(affected, code: list[str], repo: Path):
    """(answer, covers) from base's affected.py; `None` answer is ALL."""
    if hasattr(affected, "tests_for"):
        answer = affected.tests_for(code, repo=repo)
        if answer is getattr(affected, "ALL", None):
            return None, (lambda p: True)
        return answer, (lambda p: affected.covers(answer, p))
    # An affected.py from before tests_for: the same question by hand.
    sel = affected.select(code, affected.Index(repo))
    if sel.whole:
        return None, (lambda p: True)
    answer = set(sel.tests) | set(sel.measures)
    return answer, (lambda p: p in answer)


# ---------------------------------------------------------------------------
# the judgement
# ---------------------------------------------------------------------------


def judge(base: str, branch: str, nested: bool = False):
    """(tier, problems) for HEAD against `base`; problems are (rule, detail)."""
    config = json.loads(git("show", f"{base}:{CONFIG_PATH}"))
    kind = branch_kind(branch)
    merge_base = git("merge-base", base, "HEAD").strip()
    changes: list[tuple[str, str]] = []
    for line in git("diff", "--name-status", "--no-renames", merge_base,
                    "HEAD").splitlines():
        status, path = line.split("\t", 1)
        changes.append((status[0], path))
    graders = config.get("grader_paths") or []
    version_only = set(config.get("version_only_files") or [])
    problems: list[tuple[str, str]] = []

    def flag(rule: str, detail: str) -> None:
        problems.append((rule, detail))

    # Graders.
    touched_graders = sorted(p for _, p in changes if matches(p, graders))
    exempt: set[str] = set()
    if touched_graders:
        if kind == "meta":
            exempt = set(touched_graders)
            if not nested:
                for rule, detail in monotonic(base):
                    flag(rule, detail)
        else:
            flag("grader", "a grader file changed; that is a devloop-meta/ "
                 "PR of its own, judged by the base guard: "
                 + ", ".join(touched_graders[:5]))

    # Manifests: the version line and nothing else.
    version_ok: set[str] = set()
    changed = {p for _, p in changes}
    for path in sorted(version_only & changed):
        diff = git("diff", merge_base, "HEAD", "--", path)
        bad = next((ln for ln in diff.splitlines()
                    if ln[:1] in ("+", "-") and not ln.startswith(("+++", "---"))
                    and not VERSION_RE.match(ln)), None)
        if bad is None:
            version_ok.add(path)
        else:
            flag("version-only", f"{path}: only the version line may change "
                 f"({bad[:80]})")

    # Tests.
    added_tests: dict[str, int] = {}
    for status, path in changes:
        if not is_test_file(path):
            continue
        if status == "D":
            if path not in exempt:
                flag("test-deleted", f"{path}: a test file was deleted")
            continue
        head = show("HEAD", path)
        before = None if status == "A" else show(merge_base, path)
        diff = git("diff", "--unified=0", "--ignore-space-at-eol",
                   "--ignore-blank-lines", "--no-renames", merge_base, "HEAD",
                   "--", path)
        plus = [ln[1:] for ln in diff.splitlines()
                if ln.startswith("+") and not ln.startswith("+++")]
        minus = [ln[1:] for ln in diff.splitlines()
                 if ln.startswith("-") and not ln.startswith("---")
                 and ln[1:].strip()]
        gained = test_names(path, head) - test_names(path, before)
        count = sum(gained.values())
        if MEASURE_FILE.match(path) and (before is None or any(
                MEASURE_CHECK.search(ln) for ln in plus)):
            count += 1
        added_tests[path] = count
        if path in exempt:
            continue
        for ln in plus:
            if SKIP_RE.search(ln):
                flag("skip", f"{path}: a test was skipped: {ln.strip()[:100]}")
                break
        if before is None or kind == "test":
            continue
        if minus:
            flag("test-modified", f"{path}: {len(minus)} line(s) of a test "
                 f"file that exists on base were changed or removed (first: "
                 f"{minus[0].strip()[:80]!r}); add tests, never edit them, or "
                 "dispute the test in a devloop-test/ PR")
        lost = test_names(path, before) - test_names(path, head)
        if lost:
            flag("test-removed", f"{path}: test(s) gone by name: "
                 + ", ".join(sorted(lost)[:5]))

    # A test dispute changes tests and nothing else.
    if kind == "test":
        others = sorted(p for _, p in changes if not is_test_file(p))
        if others:
            flag("test-branch-scope", "a devloop-test/ PR may change tests "
                 "only: " + ", ".join(others[:5]))

    # A code change needs an added test that can see it.
    code = sorted(p for s, p in changes
                  if s != "D" and CODE_RE.match(p) and not is_test_file(p))
    if code and kind != "test":
        with tempfile.TemporaryDirectory() as tmp:
            affected = load_affected(base, tmp)
            if affected is None:
                flag("no-test", "cannot judge the tests: the base branch has "
                     f"no loadable {AFFECTED_PATH}")
            else:
                root = Path(git("rev-parse", "--show-toplevel").strip())
                answer, covers = selection_for(affected, code, root)
                seen = sorted(p for p, n in added_tests.items()
                              if n and covers(p))
                if not seen:
                    hint = ("" if answer is None else " (it selects: "
                            + ", ".join(sorted(answer)[:4])
                            + (" …" if len(answer) > 4 else "") + ")")
                    flag("no-test", "a code change with no added test in a "
                         f"file {AFFECTED_PATH} selects for it: "
                         + ", ".join(code[:5])
                         + (" …" if len(code) > 5 else "") + hint)
            sys.modules.pop("devloop_guard_affected", None)

    tier = classify(kind, changes, config, version_ok, touched_graders)
    return tier, problems


def classify(kind, changes, config, version_ok, touched_graders) -> str:
    """The risk tier, from paths alone (lists in devloop.json's `tiers`)."""
    if kind == "meta" or touched_graders:
        return "M"
    if kind == "test":
        return "T"
    tiers = config.get("tiers") or {}
    if any(matches(p, tiers.get("C")) for _, p in changes):
        return "C"
    addons, outside = set(), False
    for _, path in changes:
        if matches(path, tiers.get("A")) or path in version_ok:
            continue
        if is_test_file(path):
            # An added test is A; a changed one is a problem of its own (or
            # tier T) and belongs with whatever it tests.
            continue
        top = path.split("/", 1)[0]
        if "/" in path and top in (tiers.get("addons") or []):
            addons.add(top)
        else:
            outside = True
    if outside or len(addons) > 1:
        return "C"
    return "B" if addons else "A"


# ---------------------------------------------------------------------------
# the monotonic check (devloop-meta/ only)
# ---------------------------------------------------------------------------


def bundle(ref: str, cwd=None) -> dict:
    """What a guard judges with: itself, its config, its affected.py."""
    return {"guard": show(ref, GUARD_PATH, cwd), "config": show(ref, CONFIG_PATH, cwd),
            "affected": show(ref, AFFECTED_PATH, cwd)}


def load_cases(ref: str, cwd=None) -> list[tuple[str, dict]]:
    names = git("ls-tree", "-r", "--name-only", ref, "--", CASES_DIR,
                cwd=cwd).splitlines()
    out = []
    for name in sorted(n for n in names if n.endswith("/case.json")):
        try:
            out.append((name, json.loads(show(ref, name, cwd) or "")))
        except ValueError:
            continue
    return out


def _safe(rel: str) -> str:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not rel.strip():
        raise ValueError(f"case path {rel!r} leaves the repository")
    return rel


def clean_env(home: str) -> dict:
    """No secrets, no token, no git config from the runner."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home,
            "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, NESTED_ENV: "1"}


def build_case_repo(case: dict, grader: dict, dest: Path) -> Path:
    """A throwaway repository: `main` holds the grader bundle's config and
    affected.py plus the case's base files; the case's branch holds its head
    files (or its unified diff) on top."""
    dest.mkdir(parents=True)
    env = clean_env(str(dest.parent))

    def run(*args, stdin=None):
        subprocess.run(["git", "-c", "user.name=guard", "-c",
                        "user.email=guard@localhost", "-c",
                        "commit.gpgsign=false", *args], cwd=dest, env=env,
                       check=True, capture_output=True, text=True, input=stdin)

    def write(files: dict) -> None:
        for rel, text in files.items():
            target = dest / _safe(rel)
            if text is None:
                if target.exists():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    run("init", "-q", "-b", "main")
    base_files = dict(case.get("base") or {})
    if grader.get("config") is not None:
        base_files.setdefault(CONFIG_PATH, grader["config"])
    if grader.get("affected") is not None:
        base_files.setdefault(AFFECTED_PATH, grader["affected"])
    write(base_files)
    run("add", "-A")
    run("commit", "-qm", "base", "--allow-empty")
    run("checkout", "-qb", case["branch"])
    write(case.get("head") or {})
    if case.get("diff"):
        run("apply", "--whitespace=nowarn", "-", stdin=case["diff"])
    run("add", "-A")
    run("commit", "-qm", "head", "--allow-empty")
    return dest


def run_case(case: dict, grader: dict, workdir: Path):
    """(flagged, output): flagged is True/False, or None when the guard
    crashed or ran out of time rather than giving a verdict."""
    repo = build_case_repo(case, grader, workdir / "repo")
    script = workdir / "guard.py"
    script.write_text(grader["guard"], encoding="utf-8")
    try:
        done = subprocess.run(
            [sys.executable, "-I", str(script), "main", "--branch",
             case["branch"]], cwd=repo, env=clean_env(str(workdir)),
            capture_output=True, text=True, timeout=CASE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    out = done.stdout + done.stderr
    if done.returncode == 0:
        return False, out
    if done.returncode == 1 and "devloop-guard:" in done.stdout:
        return True, out
    return None, out


def monotonic(base: str, cwd=None) -> list[tuple[str, str]]:
    """Every frozen case the base guard flags, the PR's guard must flag."""
    old, new = bundle(base, cwd), bundle("HEAD", cwd)
    if new["guard"] is None:
        return [("meta-not-stricter", f"the PR removes {GUARD_PATH}")]
    cases = load_cases(base, cwd)
    if not cases:
        return [("meta-not-stricter", f"the base branch holds no frozen cases "
                 f"in {CASES_DIR}, so nothing proves the new guard")]
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, case) in enumerate(cases):
            try:
                old_flag, _ = run_case(case, old, Path(tmp) / f"{i}-old")
                if old_flag is False:
                    continue
                new_flag, out = run_case(case, new, Path(tmp) / f"{i}-new")
            except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
                problems.append(("meta-error", f"{name}: could not build the "
                                 f"case ({exc})"))
                continue
            if new_flag is None:
                problems.append(("meta-not-stricter", f"{name}: the PR's guard "
                                 f"gave no verdict ({out.strip()[-120:]})"))
            elif not new_flag:
                problems.append(("meta-not-stricter", f"{name}: the base guard "
                                 "flags this case and the PR's guard lets it "
                                 "through"))
    return problems


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------


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
    tier, problems = judge(args.base, branch,
                           nested=bool(os.environ.get(NESTED_ENV)))
    return report(tier, problems, branch)


if __name__ == "__main__":
    sys.exit(main())
