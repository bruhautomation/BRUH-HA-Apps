#!/usr/bin/env python3
"""Run the house's LLM jobs against their eval cases, with a real model.

    python3 tests/evals/run.py --dry-run              # build every prompt, ask nothing
    python3 tests/evals/run.py                        # every case, 3 trials, pinned models
    python3 tests/evals/run.py --jobs extractor --only some-case-id
    python3 tests/evals/run.py --changed origin/main  # only the jobs a branch can move

For each case it builds the REAL prompt with the job's own builder
(``evals/jobs.py``), asks the job's pinned model through the `claude` CLI
headless, and grades the answer with the job's deterministic grader
(``evals/graders/``). Each case runs ``--trials`` times (3).

What it reports, per job and per suite (regression / capability):

  pass@1   the share of all graded trials that passed — how often one run
           of the job gets it right
  pass^3   the share of cases whose every trial passed — whether an
           unattended loop can count on the job, which is the number the
           gate reads

Exit codes: 0 the run met every regression threshold, or there was no
credential to spend (it says ``skipped: no token``); 1 a regression suite
fell below its threshold, or could not be graded at all; 2 bad arguments.
A capability suite never fails the run: it is tracked, and a case moves to
the regression suite once it has held (docs/notes/diagnostics.md says how).

The JSON report carries the models asked (pinned) and the models the CLI
says it ran, the judge's model, and the runner's environment — CPU, memory
and the cgroup limits when they can be read — because a score with no
machine attached cannot be told apart from infrastructure noise.
"""
from __future__ import annotations

import os
import sys

# This directory must not be first on the path: a module here named like a
# standard library one would shadow it (it happened, with `select`).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
sys.path.insert(0, os.path.dirname(_HERE))

import argparse  # noqa: E402
import json  # noqa: E402
import platform  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

from evals import jobs as job_adapters  # noqa: E402
from evals import model as model_mod  # noqa: E402
from evals import schema  # noqa: E402
from evals import selection as selector  # noqa: E402
from evals.graders import FAIL, PASS, UNKNOWN, grade  # noqa: E402
from evals.graders import judge as judge_mod  # noqa: E402

DEFAULT_TRIALS = 3
DEFAULT_THRESHOLD = 0.95
# Generous enough for every case's three trials on the pinned tiers, small
# enough that a runaway is a stopped run rather than a bill. The workflow
# sets its own, where the schedule is.
DEFAULT_MAX_TOKENS = 3_000_000
CREDENTIAL_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


# ------------------------------------------------------------- environment

def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def environment() -> dict:
    """What the scores were measured on. Container limits from cgroup v2
    (or v1) when readable; nothing is guessed when they are not."""
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "cgroup_cpu_max": _read("/sys/fs/cgroup/cpu.max")
        or _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
        "cgroup_memory_max": _read("/sys/fs/cgroup/memory.max")
        or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "runner_os": os.environ.get("RUNNER_OS", ""),
        "runner_name": os.environ.get("RUNNER_NAME", ""),
        "git_sha": os.environ.get("GITHUB_SHA", ""),
    }
    meminfo = _read("/proc/meminfo").splitlines()
    env["mem_total"] = meminfo[0].split(":", 1)[1].strip() if meminfo else ""
    try:
        argv = model_mod.claude_argv() + ["--version"]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        env["claude_cli"] = (out.stdout or out.stderr).strip()[:120]
    except (OSError, subprocess.SubprocessError):
        env["claude_cli"] = ""
    return env


def have_credential() -> bool:
    return any(os.environ.get(name) for name in CREDENTIAL_VARS)


# -------------------------------------------------------------- the scoring

def case_verdict(trials: list[dict]) -> str:
    """One case over its trials: fail if any graded trial failed, pass if
    every trial passed, else unknown (an error or an undecided trial and no
    failure — not evidence either way)."""
    words = [t["verdict"] for t in trials]
    if FAIL in words:
        return FAIL
    if words and all(w == PASS for w in words):
        return PASS
    return UNKNOWN


def summarise(rows: list[dict]) -> dict:
    """pass@1 over graded trials, pass^k over cases decided either way."""
    trials = [t for r in rows for t in r["trials"]]
    graded = [t for t in trials if t["verdict"] in (PASS, FAIL)]
    decided = [r for r in rows if r["verdict"] in (PASS, FAIL)]
    return {
        "cases": len(rows),
        "trials": len(trials),
        "graded_trials": len(graded),
        "errors": sum(1 for t in trials if t.get("error")),
        "unknown_trials": sum(1 for t in trials if t["verdict"] == UNKNOWN
                              and not t.get("error")),
        "pass_at_1": round(sum(t["verdict"] == PASS for t in graded) / len(graded), 3)
        if graded else None,
        "pass_pow_k": round(sum(r["verdict"] == PASS for r in decided) / len(decided), 3)
        if decided else None,
        "decided_cases": len(decided),
        "incomplete": sum(1 for r in rows if r.get("incomplete")),
    }


def gate(by_job: dict, threshold: float) -> list[str]:
    """Why the run fails, one sentence per regression suite that does."""
    out = []
    for job, suites in by_job.items():
        reg = suites.get("regression")
        if not reg or not reg["cases"]:
            continue
        if reg["incomplete"] == reg["cases"]:
            continue  # the budget, not the job: reported, not gated
        if reg["pass_pow_k"] is None:
            out.append(f"{job}: no regression case could be graded "
                       f"({reg['errors']} errored trials)")
        elif reg["errors"] * 2 > reg["trials"]:
            out.append(f"{job}: {reg['errors']} of {reg['trials']} trials errored")
        elif reg["pass_pow_k"] < threshold:
            out.append(f"{job}: regression pass^k {reg['pass_pow_k']:.0%} is under "
                       f"{threshold:.0%}")
    return out


# ------------------------------------------------------------------ the run

def run_case(case: dict, model: str, trials: int, ask, budget: dict,
             use_judge: bool) -> dict:
    row = {"id": case["id"], "job": case["job"], "kind": case["kind"],
           "model": model, "trials": []}
    for _ in range(int(case.get("trials") or trials)):
        # Checked BEFORE the trial: a cap that stops once it has been
        # passed has already spent the run that passed it. With several
        # workers it can still be passed by the trials already in flight.
        with budget["lock"]:
            if budget["spent"] >= budget["max"]:
                row["incomplete"] = f"the {budget['max']} token budget is spent"
                break
        trial = job_adapters.run(case, model, ask)
        with budget["lock"]:
            budget["spent"] += trial.tokens
        entry = {"tokens": trial.tokens, "models": trial.models,
                 "seconds": trial.seconds}
        if trial.error:
            entry.update(verdict=UNKNOWN, reason="error: " + trial.error,
                         error=trial.error)
        else:
            result = grade(case, trial.output)
            if result["verdict"] == UNKNOWN and use_judge \
                    and (case.get("expect") or {}).get("judge"):
                result, cost = judge_mod.judge(case, trial.output, ask)
                with budget["lock"]:
                    budget["spent"] += cost
                entry["judged"] = True
            entry.update(result)
            entry["output"] = trial.output
        row["trials"].append(entry)
    row["verdict"] = case_verdict(row["trials"]) if not row.get("incomplete") \
        else (FAIL if FAIL in [t["verdict"] for t in row["trials"]] else UNKNOWN)
    return row


def run(cases: list[dict], *, trials: int = DEFAULT_TRIALS,
        threshold: float = DEFAULT_THRESHOLD, max_tokens: int = DEFAULT_MAX_TOKENS,
        models: dict | None = None, ask=None, use_judge: bool = True,
        workers: int = 1) -> dict:
    ask = ask or model_mod.ask
    models = {**model_mod.PINNED_MODELS, **(models or {})}
    budget = {"spent": 0, "max": max_tokens, "lock": threading.Lock()}

    def one(case):
        return run_case(case, models[case["job"]], trials, ask, budget, use_judge)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(one, cases))  # map keeps the cases' order
    by_job: dict[str, dict] = {}
    for job in schema.JOBS:
        mine = [r for r in rows if r["job"] == job]
        if not mine:
            continue
        by_job[job] = {kind: summarise([r for r in mine if r["kind"] == kind])
                       for kind in schema.KINDS if any(r["kind"] == kind for r in mine)}
    reasons = gate(by_job, threshold)
    used = sorted({m for r in rows for t in r["trials"] for m in t.get("models") or []})
    return {
        "generated_at": int(time.time()),
        "trials": trials,
        "threshold": threshold,
        "models_asked": {job: models[job] for job in by_job},
        "models_reported": used,
        "judge_model": judge_mod.JUDGE_MODEL,
        "tokens": budget["spent"],
        "max_tokens": max_tokens,
        "by_job": by_job,
        "failed": reasons,
        "results": rows,
    }


def render(report: dict) -> str:
    lines = [f"evals — {len(report['results'])} case(s) × {report['trials']} trials, "
             f"{report['tokens']} tokens"]
    for job, suites in report["by_job"].items():
        for kind, s in suites.items():
            p1 = "–" if s["pass_at_1"] is None else f"{s['pass_at_1']:.0%}"
            pk = "–" if s["pass_pow_k"] is None else f"{s['pass_pow_k']:.0%}"
            extra = []
            if s["errors"]:
                extra.append(f"{s['errors']} errored")
            if s["unknown_trials"]:
                extra.append(f"{s['unknown_trials']} undecided")
            if s["incomplete"]:
                extra.append(f"{s['incomplete']} cut by the budget")
            lines.append(f"  {job:<16} {kind:<11} pass@1 {p1:>4}  "
                         f"pass^{report['trials']} {pk:>4}  ({s['cases']} cases"
                         + (", " + ", ".join(extra) if extra else "") + ")")
    for row in report["results"]:
        if row["verdict"] == FAIL:
            why = next((t["reason"] for t in row["trials"] if t["verdict"] == FAIL), "")
            lines.append(f"  ✗ {row['job']}/{row['id']} ({row['kind']}): {why[:240]}")
    lines.append("")
    lines.append("FAILED: " + "; ".join(report["failed"]) if report["failed"]
                 else f"every regression suite met {report['threshold']:.0%} pass^k")
    return "\n".join(lines)


def dry_run(cases: list[dict]) -> tuple[int, str]:
    """Build every case's prompt with today's builders and ask nothing. A
    builder that moved or broke is named here, in the free run, rather than
    as a night of errored trials."""
    broken = []
    for case in cases:
        if case["job"] == "consolidator":
            try:
                job_adapters.build(case)
            except LookupError as exc:
                # The whole script runs in a real trial; only the dry
                # preview needs the function by name.
                print(f"  – {case['id']}: preview skipped ({exc})")
                continue
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{case['job']}/{case['id']}: {str(exc)[:300]}")
            continue
        try:
            req = job_adapters.build(case)
            if req.decided is None and not req.prompt:
                broken.append(f"{case['job']}/{case['id']}: an empty prompt")
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{case['job']}/{case['id']}: {str(exc)[:300]}")
    if broken:
        return 1, "prompts that would not build:\n  " + "\n  ".join(broken)
    return 0, f"built the prompt for all {len(cases)} case(s); no model was asked"


def changed_paths(base: str) -> list[str] | None:
    # Two dots: on a pull request the checkout is the merge commit, so its
    # diff against the base's tip is what merging would change (ci.yml's
    # reasoning, which also needs only a depth-1 fetch of the base).
    out = subprocess.run(["git", "diff", "--name-only", base, "HEAD"],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return None  # not knowing what changed means running everything
    return [p for p in out.stdout.splitlines() if p.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__.split("\n")[0])
    parser.add_argument("--jobs", default="", help="comma-separated jobs (default all)")
    parser.add_argument("--kind", default="all", choices=("all",) + schema.KINDS)
    parser.add_argument("--only", default="", help="one case id")
    parser.add_argument("--changed", default="", metavar="BASE",
                        help="only the jobs the diff against BASE can move")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="regression pass^k a job must reach (0.95)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help="stop asking once this much has been spent")
    parser.add_argument("--model", action="append", default=[], metavar="JOB=ID",
                        help="override one job's pinned model (recorded in the report)")
    parser.add_argument("--workers", type=int, default=1,
                        help="cases run at once (each case's trials stay in order)")
    parser.add_argument("--no-judge", action="store_true",
                        help="never ask the LLM judge; undecided stays unknown")
    parser.add_argument("--dry-run", action="store_true",
                        help="build every prompt and ask no model")
    parser.add_argument("--assume-credential", action="store_true",
                        help="run without a token in the environment (a CLI "
                             "signed in by its own login, or a stand-in)")
    parser.add_argument("--out", default="", help="write the JSON report here")
    args = parser.parse_args(argv)

    if args.trials < 1 or not 0 < args.threshold <= 1:
        parser.error("--trials must be >= 1 and --threshold in (0, 1]")
    overrides = {}
    for item in args.model:
        job, _, mid = item.partition("=")
        if job not in schema.JOBS or not mid:
            parser.error(f"--model takes JOB=ID with JOB one of {schema.JOBS}")
        overrides[job] = mid
    wanted = [j for j in args.jobs.split(",") if j]
    unknown_jobs = [j for j in wanted if j not in schema.JOBS]
    if unknown_jobs:
        parser.error(f"unknown jobs {unknown_jobs}")
    if args.changed:
        paths = changed_paths(args.changed)
        reach = list(schema.JOBS) if paths is None else \
            selector.selected_jobs(paths, schema.JOBS)
        wanted = [j for j in (wanted or schema.JOBS) if j in reach]
        if not wanted:
            print(f"skipped: nothing changed since {args.changed} builds a prompt")
            return 0
    cases = schema.load_cases(jobs=wanted or None, kind=args.kind, only=args.only)
    if not cases:
        print("no cases match", file=sys.stderr)
        return 2

    if args.dry_run:
        rc, text = dry_run(cases)
        print(text)
        return rc
    if not have_credential() and not args.assume_credential and \
            not os.environ.get("EVALS_CLAUDE_BIN"):
        report = {"skipped": "no token", "generated_at": int(time.time()),
                  "cases": len(cases)}
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print("skipped: no token — set CLAUDE_CODE_OAUTH_TOKEN (the "
              "BRAIN_REPLAY_TOKEN secret in CI) to grade the prompts. "
              "The graders and every case's prompt are checked without one "
              "(tests/evals/test_graders.py, --dry-run).")
        return 0
    if not shutil.which(model_mod.claude_argv()[0]):
        print(f"no `{model_mod.claude_argv()[0]}` CLI on PATH", file=sys.stderr)
        return 2

    report = run(cases, trials=args.trials, threshold=args.threshold,
                 max_tokens=args.max_tokens, models=overrides,
                 use_judge=not args.no_judge, workers=args.workers)
    report["environment"] = environment()
    print(render(report))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, default=str) + "\n",
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
