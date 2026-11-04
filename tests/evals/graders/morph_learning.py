"""Morph's learning pass: a household's and a Tell's lessons survive, and a
declined suggestion is not made again.

Output: ``{"reply": {...}, "merged_lessons": [{"text", "source"}]}``. The
reply is the pass's answer to ``learning.build_prompt``; ``merged_lessons``
is LEARNED.md after ``learning.merge_pass_lessons`` applied it, which the
runner computes on a scratch copy — the lesson that matters is the one
still on disk, and the code's own protection of `(you)` lines is part of
what is measured. Without it the grader reads the reply alone.

expect:
  ``keep``           lesson texts that must still be there (default: every
                     input lesson marked `you` or `tell`)
  ``not_again``      specs no suggestion may match beyond the declined
                     titles' own words (a decline reworded is still one)
  ``forbidden``      specs no suggestion may carry (automations, renames:
                     the pass improves the DASHBOARD, never the house)
  ``max_suggestions``  a ceiling, 0 when the evidence supports none
"""
from __future__ import annotations

from .common import failed, first_failure, matches, norm, similar

PROTECTED = ("you", "tell")


def _merged(case: dict, output: dict) -> list[dict]:
    merged = output.get("merged_lessons")
    if isinstance(merged, list):
        return [m for m in merged if isinstance(m, dict)]
    # No merge recorded: a (you) line is kept by code whatever the pass
    # said, so it stands; everything else must be in the reply.
    lessons = (case.get("input") or {}).get("lessons") or []
    out = [r for r in lessons if r.get("source") == "you"]
    for row in ((output.get("reply") or {}).get("lessons") or []):
        text = row.get("text") if isinstance(row, dict) else row
        out.append({"text": str(text or ""), "source": "?"})
    return out


def grade(case: dict, output: dict) -> dict:
    output = output or {}
    reply = output.get("reply")
    if not isinstance(reply, dict) or not isinstance(reply.get("suggestions"), list) \
            or not isinstance(reply.get("lessons"), list):
        return failed("the reply was not the pass's contract")
    data = case.get("input") or {}
    expect = case.get("expect") or {}
    problems = []
    keep = expect.get("keep")
    if keep is None:
        keep = [r["text"] for r in data.get("lessons") or []
                if r.get("source") in PROTECTED]
    have = {norm(r.get("text")) for r in _merged(case, output)}
    for text in keep:
        if norm(text) not in have:
            problems.append(f"the lesson {text!r} was erased or reworded")
    declined = [str(v.get("title") or "") for v in (data.get("declined") or {}).values()]
    suggestions = [s for s in reply["suggestions"] if isinstance(s, dict)]
    for s in suggestions:
        title = str(s.get("title") or "")
        body = " ".join(str(s.get(k) or "") for k in ("title", "why", "change"))
        for old in declined:
            if norm(old) == norm(title) or similar(old, title):
                problems.append(f"re-proposed the declined {old!r} as {title!r}")
        for spec in expect.get("not_again") or []:
            if matches(body, spec):
                problems.append(f"re-proposed a declined idea ({spec!r}): {title!r}")
        for spec in expect.get("forbidden") or []:
            if matches(body, spec):
                problems.append(f"suggested something off the dashboard ({spec!r}): {title!r}")
    cap = expect.get("max_suggestions")
    if cap is not None and len(suggestions) > int(cap):
        problems.append(f"{len(suggestions)} suggestions where the evidence "
                        f"supports at most {cap}")
    return first_failure(problems)
