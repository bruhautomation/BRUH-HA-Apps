#!/usr/bin/env python3
"""May this devloop PR merge? The reviewer gate as code.

Plan items 1.1 and 1.2 with section 0's table. After CI is green, a fresh
reviewer (a different model tier from the fixer, which never saw the fix's
reasoning) returns ``approve`` / ``request_changes`` / ``unknown``. The
risk tier comes from the ``devloop-guard`` job, never from the run's own
reading of the diff.

- **A** (copy, UI, docs, test additions), **B** (logic in one add-on) and
  **T** (a test dispute, ``devloop-test/``): one ``approve`` and no
  ``request_changes``. For T the reviewer judges whether the old assertion
  contradicts what the house observed.
- **C** (a safety area, or logic across add-ons) and **M** (a grader
  change, ``devloop-meta/``, already proved no looser by the base guard):
  two ``approve`` from two different reviewers, and no
  ``request_changes``. The house canary and automatic revert stand behind
  every merge (``canary.py``).
- No tier found in the guard's output: treated as **C**, the strictest.
- A reviewer on the fixer's own model tier does not count.
- ``unknown`` is not an approve. The first one asks a fresh reviewer again;
  a second sends the batch back to its fixer one model tier up.

    merge_gate.py tier    GUARD_OUTPUT.txt
    merge_gate.py decide  --guard GUARD_OUTPUT.txt --fixer-model sonnet
                          --verdicts VERDICTS.json

VERDICTS.json: ``[{"reviewer": "<id>", "model": "opus", "verdict": "approve",
"reason": "…"}]``. The verdict may also be given as the reviewer's raw
reply; ``parse_verdict`` takes the last ``verdict: <word>`` line in it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffh_common as C  # noqa: E402

# Weakest to strictest. T is a test dispute (devloop-test/), M a grader
# change (devloop-meta/); the guard prints which.
TIERS = ("A", "B", "T", "C", "M")
APPROVALS = {"A": 1, "B": 1, "T": 1, "C": 2, "M": 2}
VERDICTS = ("approve", "request_changes", "unknown")
_TIER = re.compile(r"""\b(?:risk[ _-]?)?tier\b["']?\s*(?:[:=]|is)?\s*["']?((?-i:[ABCTM]))\b""",
                   re.IGNORECASE)
# A line that is nothing but the tier (``tier: B``, ``tier=B``, a workflow
# ``::notice::tier=B``, ``"tier": "B"``) beats a mention inside prose, so a
# summary that also explains the tiers is still read right.
_TIER_LINE = re.compile(
    r"""^\s*(?:::\w+[^:]*::)?\s*(?:[-*]\s*)?["']?(?:devloop[-_ ])?(?:risk[-_ ])?tier["']?"""
    r"""\s*[:=]\s*["']?((?-i:[ABCTM]))["']?\s*,?\s*$""", re.IGNORECASE | re.MULTILINE)
_VERDICT = re.compile(r"""\bverdict\b["']?\s*[:=]\s*["']?(approve|request_changes|unknown)\b""",
                      re.IGNORECASE)


def parse_tier(text: str | None) -> str | None:
    """The strictest tier the guard's output or summary names, or None."""
    found = {m.group(1).upper() for m in _TIER_LINE.finditer(text or "")}
    if not found:
        found = {m.group(1).upper() for m in _TIER.finditer(text or "")}
    for tier in reversed(TIERS):
        if tier in found:
            return tier
    return None


def parse_verdict(text: str | None) -> str:
    found = _VERDICT.findall(text or "")
    if found:
        return found[-1].lower()
    word = (text or "").strip().lower()
    return word if word in VERDICTS else "unknown"


def required_approvals(tier: str) -> int:
    return APPROVALS.get(tier, 2)


def decide(tier: str | None, verdicts: list[dict], fixer_model: str) -> dict:
    tier = tier if tier in TIERS else "C"
    need = required_approvals(tier)
    fixer = C.model_rank(fixer_model)
    counted, ignored = [], []
    seen = set()
    for v in verdicts:
        verdict = v.get("verdict")
        if verdict not in VERDICTS:
            verdict = parse_verdict(v.get("text") or verdict)
        who = v.get("reviewer") or f"r{len(seen)}"
        if who in seen:
            ignored.append({**v, "why": "the same reviewer twice"})
            continue
        if C.model_rank(v.get("model")) == fixer or C.model_rank(v.get("model")) < 0:
            ignored.append({**v, "why": "not a different model tier from the fixer"})
            continue
        seen.add(who)
        counted.append(verdict)
    approvals = counted.count("approve")
    changes = counted.count("request_changes")
    unknowns = counted.count("unknown")
    if changes:
        nxt, why = "fix", "a reviewer asked for changes"
    elif approvals >= need:
        nxt, why = "merge", f"tier {tier}: {approvals} approval(s), {need} needed"
    elif unknowns >= 2:
        nxt, why = "escalate", "two reviewers could not tell; refix one model tier up"
    else:
        nxt, why = "review", (f"tier {tier}: {approvals} of {need} approval(s); "
                              "ask a fresh reviewer")
    return {"tier": tier, "merge": nxt == "merge", "next": nxt, "reason": why,
            "approvals": approvals, "needed": need, "ignored": ignored,
            "escalate_model": C.next_model(fixer_model) if nxt == "escalate" else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tier")
    t.add_argument("guard")
    d = sub.add_parser("decide")
    d.add_argument("--guard", required=True)
    d.add_argument("--fixer-model", required=True)
    d.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    with open(args.guard, encoding="utf-8") as fh:
        tier = parse_tier(fh.read())
    if args.cmd == "tier":
        print(tier or "C")
        return 0
    out = decide(tier, C.load_json(args.verdicts), args.fixer_model)
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0 if out["merge"] else 1


if __name__ == "__main__":
    sys.exit(main())
