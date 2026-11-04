"""The devloop's Claude streams (gaps, ideas, look): precision against
labelled past reports, with what the developer declined as the negatives.

Output: ``{"reply": {"rows": [...]}}`` — the stream's answer, before
``parse_reply`` shapes it into issues.

expect:
  ``negatives``   specs for reports that were declined, closed as not
                  brAIn's, or already filed: a row matching one is a false
                  positive, and one is a fail — refiling a decline is the
                  exact noise the loop pays a person (or now an auditor) for
  ``positives``   specs for reports that were right (fixed, held)
  ``required``    specs at least one row must match
  ``min_precision``  of the rows that match a label, the share that are
                  positives (default 1.0)
  ``empty``       true when the right answer is no row at all
  ``max_rows``    a ceiling
  ``addon``       the add-on a `look` row must be filed for
  ``still``       true when the owner's complaint is one already filed: the
                  row's `what` must start "Still a problem:"
A row that matches no label cannot be judged here: the verdict is
``unknown`` unless the case carries a ``judge`` rubric for the LLM judge.
"""
from __future__ import annotations

from .common import failed, first_failure, matches, unknown

FIELDS = ("title", "what", "why", "done_when")


def _text(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in ("title", "what", "why"))


def grade(case: dict, output: dict) -> dict:
    reply = (output or {}).get("reply")
    rows = reply.get("rows") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return failed("the reply had no rows list")
    rows = [r for r in rows if isinstance(r, dict)]
    expect = case.get("expect") or {}
    problems = []
    if expect.get("empty") and rows:
        problems.append(f"expected no row, got {len(rows)}: "
                        + " | ".join(str(r.get("title"))[:60] for r in rows))
    if expect.get("max_rows") is not None and len(rows) > int(expect["max_rows"]):
        problems.append(f"{len(rows)} rows, over {expect['max_rows']}")
    for r in rows:
        missing = [k for k in FIELDS if not str(r.get(k) or "").strip()]
        if missing:
            problems.append(f"row {str(r.get('title'))[:60]!r} lacks {missing}")
    positive = negative = unlabelled = 0
    for r in rows:
        text = _text(r)
        neg = [s for s in expect.get("negatives") or [] if matches(text, s)]
        if neg:
            negative += 1
            problems.append(f"refiled a closed report ({neg[0]!r}): "
                            f"{str(r.get('title'))[:80]!r}")
        elif any(matches(text, s) for s in expect.get("positives") or []):
            positive += 1
        else:
            unlabelled += 1
    for spec in expect.get("required") or []:
        if not any(matches(_text(r), spec) for r in rows):
            problems.append(f"no row about {spec!r}")
    if expect.get("addon"):
        wrong = [r for r in rows if (r.get("addon") or "brAIn") != expect["addon"]]
        if wrong:
            problems.append(f"filed for {wrong[0].get('addon') or 'brAIn'}, "
                            f"not {expect['addon']}")
    if expect.get("still"):
        if not any(str(r.get("what") or "").startswith("Still a problem:") for r in rows):
            problems.append("an already-filed complaint was not marked "
                            "\"Still a problem:\"")
    labelled = positive + negative
    need = float(expect.get("min_precision", 1.0))
    if labelled and positive / labelled < need:
        problems.append(f"precision {positive}/{labelled} under {need:.0%}")
    if problems:
        return failed("; ".join(problems))
    if unlabelled and not expect.get("empty"):
        return unknown(f"{unlabelled} row(s) match no labelled report")
    return first_failure([], f"{positive} labelled row(s), all right")
