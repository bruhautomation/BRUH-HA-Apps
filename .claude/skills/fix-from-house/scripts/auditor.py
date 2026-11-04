#!/usr/bin/env python3
"""The auditor: every decline cites evidence, and a tenth of them are re-judged.

Plan item 0.5 with section 0's replacement for the owner's sample. A loop
that is rewarded for closing drifts toward closing (2026-11-03: 24 of 70
closures were declined, duplicate or already fixed). Two checks hold it:

1. **Every declined or duplicate closure cites evidence**: a linked issue
   or PR (``#123`` or a GitHub link), a ``path:line``, or a release plus a
   test path (``4.3.0 … tests/test_x.py``). ``lint`` checks one comment
   before the run closes the issue; ``check`` checks a week of closures.
2. **A deterministic 10% sample** of the week's declined and duplicate
   closures, seeded by the ISO week, goes to a fresh auditor subagent.

The reopen rule (``apply``):

- a closure with no evidence is reopened, whatever the auditor says;
- a closure the auditor marks ``overturn`` is reopened with its reason;
- ``uphold`` stays closed;
- ``unknown`` stays closed and is carried into next week's sample.

A reopened issue loses ``devloop:declined`` / ``devloop:duplicate``, gains
``devloop:audit-reopened``, and the run drains it this run.

    auditor.py lint   --outcome declined --comment-file C.txt
    auditor.py sample --closures CLOSURES.json [--week 2026-W45 | --today 2026-11-04]
                      [--rate 0.1] [--carry CARRY.json]
    auditor.py check  --closures CLOSURES.json
    auditor.py apply  --closures CLOSURES.json --verdicts VERDICTS.json

CLOSURES.json: ``[{"number", "outcome", "comment", "closed_at"}]`` (outcome
one of fixed, already_fixed, duplicate, declined, not_brain, …).
VERDICTS.json: ``[{"number", "verdict": "uphold"|"overturn"|"unknown",
"reason"}]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffh_common as C  # noqa: E402

AUDITED = ("declined", "duplicate")
RATE = 0.10
REOPEN_LABEL = "devloop:audit-reopened"
VERDICTS = ("uphold", "overturn", "unknown")


def week_of(day: str | date) -> str:
    d = date.fromisoformat(day) if isinstance(day, str) else day
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def audited(closures: list[dict]) -> list[dict]:
    return [c for c in closures if c.get("outcome") in AUDITED]


def sample(closures: list[dict], week: str, rate: float = RATE,
           carry: list[int] | None = None) -> list[int]:
    """The issue numbers to audit: ceil(rate × n) of the declined and
    duplicate closures, the same for the same week every time it is asked,
    plus every number carried over from last week's ``unknown``."""
    pool = audited(closures)
    if not pool:
        return sorted(set(carry or []))
    k = max(1, math.ceil(rate * len(pool)))

    def key(c: dict) -> str:
        return hashlib.sha256(f"{week}:{c['number']}".encode()).hexdigest()

    chosen = {c["number"] for c in sorted(pool, key=key)[:k]}
    return sorted(chosen | set(carry or []))


def lint(outcome: str, comment: str) -> tuple[bool, str]:
    if outcome not in AUDITED:
        return True, "not a decline or duplicate"
    kinds = C.evidence_kinds(comment)
    if kinds:
        return True, "cites " + ", ".join(kinds)
    return False, ("a declined or duplicate closure must cite a linked issue or "
                   "PR (#n), a path:line, or a release and a tests/ path")


def check(closures: list[dict]) -> list[dict]:
    out = []
    for c in audited(closures):
        ok, why = lint(c["outcome"], c.get("comment") or "")
        if not ok:
            out.append({"number": c["number"], "outcome": c["outcome"], "why": why})
    return out


def apply(closures: list[dict], verdicts: list[dict]) -> dict:
    by_number = {c["number"]: c for c in closures}
    reopen: dict[int, str] = {}
    for bad in check(closures):
        reopen[bad["number"]] = "closed without evidence"
    upheld, carry, overturned = [], [], 0
    for v in verdicts:
        n, verdict = v.get("number"), v.get("verdict")
        if n not in by_number or verdict not in VERDICTS:
            continue
        if verdict == "overturn":
            overturned += 1
            reopen.setdefault(n, "the auditor overturned it: " + (v.get("reason") or ""))
        elif verdict == "unknown":
            if n not in reopen:
                carry.append(n)
        elif n not in reopen:
            upheld.append(n)
    actions = []
    for n, why in sorted(reopen.items()):
        outcome = by_number[n].get("outcome")
        actions.append({
            "number": n,
            "reopen": True,
            "remove_labels": [f"devloop:{outcome}"] if outcome in AUDITED else [],
            "add_labels": [REOPEN_LABEL],
            "comment": f"Reopened by the weekly audit: {why.strip()}",
        })
    return {"reopen": actions, "upheld": sorted(upheld), "carry": sorted(carry),
            "audit": {"sampled": len([v for v in verdicts if v.get("number") in by_number]),
                      "overturned": overturned}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("lint")
    li.add_argument("--outcome", required=True)
    li.add_argument("--comment-file", required=True)
    sa = sub.add_parser("sample")
    sa.add_argument("--closures", required=True)
    sa.add_argument("--week", default=None)
    sa.add_argument("--today", default=None)
    sa.add_argument("--rate", type=float, default=RATE)
    sa.add_argument("--carry", default=None)
    ch = sub.add_parser("check")
    ch.add_argument("--closures", required=True)
    ap_ = sub.add_parser("apply")
    ap_.add_argument("--closures", required=True)
    ap_.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "lint":
        with open(args.comment_file, encoding="utf-8") as fh:
            ok, why = lint(args.outcome, fh.read())
        print(why)
        return 0 if ok else 1
    closures = C.load_json(args.closures)
    if args.cmd == "sample":
        week = args.week or week_of(args.today or date.today())
        carry = C.load_json(args.carry) if args.carry else []
        out = {"week": week, "sample": sample(closures, week, args.rate, carry)}
    elif args.cmd == "check":
        out = {"missing_evidence": check(closures)}
    else:
        out = apply(closures, C.load_json(args.verdicts))
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 1 if args.cmd == "check" and out["missing_evidence"] else 0


if __name__ == "__main__":
    sys.exit(main())
