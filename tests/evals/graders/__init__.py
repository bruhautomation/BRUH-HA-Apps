"""One deterministic grader per job: ``grade(case, output) -> verdict``.

Each grader is a pure function of the case and the job's output — no
model, no clock, no network — so every one of them runs in ordinary CI
against hand-written good and bad outputs (``tests/evals/test_graders.py``).
"""
from __future__ import annotations

from . import (consolidator, devloop_streams, extractor, first_look,
               morph_learning, reflect)
from .common import FAIL, PASS, UNKNOWN, VERDICTS

GRADERS = {
    "extractor": extractor.grade,
    "consolidator": consolidator.grade,
    "reflect": reflect.grade,
    "first_look": first_look.grade,
    "morph_learning": morph_learning.grade,
    "devloop_streams": devloop_streams.grade,
}


def grade(case: dict, output: dict) -> dict:
    """The case's job's grader. A grader that raises is a ``fail`` naming
    the exception: a crash in grading must never read as a pass."""
    try:
        result = GRADERS[case["job"]](case, output)
    except Exception as exc:  # noqa: BLE001 — reported, never swallowed
        return {"verdict": FAIL, "reason": f"the grader raised {exc!r}"}
    if not isinstance(result, dict) or result.get("verdict") not in VERDICTS:
        return {"verdict": FAIL, "reason": f"the grader answered {result!r}"}
    return result


__all__ = ["FAIL", "GRADERS", "PASS", "UNKNOWN", "VERDICTS", "grade"]
