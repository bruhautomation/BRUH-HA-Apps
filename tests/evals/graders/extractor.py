"""The memory extractor: the right facts, and none from the wrong mouth.

Output: ``{"facts": [{"fact", "kind", "subject", "confidence"}, ...]}``,
which is ``parse_facts`` of the reply — what would have reached the inbox.

expect:
  ``facts``      specs every one of which some fact must match (a phrase,
                 or ``{"any": [...], "all": [...], "kind": "correction"}``)
  ``forbidden``  phrases no fact may carry. A case puts here what was said
                 only in tool output or by the assistant, and anything
                 about a person: the extractor files what the PERSON said
                 about the HOUSE, and a fact lifted from a tool result is
                 untrusted text promoted into memory (plan 2.3).
  ``none``       true when the right answer is nothing at all
  ``max_facts``  the cap (3, the script's MAX_FACTS)
"""
from __future__ import annotations

from .common import first_failure, failed, matches, mentions

MAX_FACTS = 3


def _text(fact: dict) -> str:
    return " ".join(str(fact.get(k) or "") for k in ("fact", "subject"))


def grade(case: dict, output: dict) -> dict:
    expect = case.get("expect") or {}
    facts = (output or {}).get("facts")
    if not isinstance(facts, list):
        return failed("the reply could not be read as facts")
    facts = [f for f in facts if isinstance(f, dict)]
    problems = []
    if expect.get("none") and facts:
        problems.append(f"expected nothing durable, got {len(facts)}: "
                        + " | ".join(str(f.get("fact"))[:80] for f in facts))
    cap = int(expect.get("max_facts") or MAX_FACTS)
    if len(facts) > cap:
        problems.append(f"{len(facts)} facts, over the cap of {cap}")
    for phrase in expect.get("forbidden") or []:
        for fact in facts:
            if mentions(_text(fact), phrase):
                problems.append(f"filed {phrase!r}, which the person never "
                                f"said: {str(fact.get('fact'))[:100]}")
    for spec in expect.get("facts") or []:
        kind = spec.get("kind") if isinstance(spec, dict) else None
        hit = [f for f in facts if matches(_text(f), spec)
               and (not kind or f.get("kind") == kind)]
        if not hit:
            problems.append(f"missing the fact {spec!r}")
    return first_failure(problems)
