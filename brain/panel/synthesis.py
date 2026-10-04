"""The one thing to do this week, chosen across the week rather than by rank.

`weekly.one_thing` picks the worst severity and then the longest open, and
it is deterministic on purpose: asked to choose freely, a model picks the
row it can write the best sentence about. That rule is right about what it
refuses and wrong about what it can see. Three warnings about one flaky
hub outrank nothing on a severity list, while they are plainly the one
thing worth an afternoon; a `serious` row that has been open a month
because it is a fact of the house rather than a fault is the top of the
list every single week. Severity is a property of ONE row, and the
question the report ends on is about the week.

So the pick is made by the `synthesis` job (`model_plan.JOBS`) over the
open rows and the week's own numbers, with four rules that keep it from
becoming the free choice the old docstring warned about:

* **The candidates are the list, never the model's.** It answers with the
  id of a row it was shown and a sentence; an id it was not shown is no
  answer, and the severity pick stands.
* **A safety floor.** If anything open is `critical`, only `critical`
  rows are offered. A cross-category argument for tidying a dashboard is
  not allowed to outrank a freezer that has stopped.
* **The severity pick is journaled beside it as the baseline** (source
  ``weekly_pick``): which row each rule chose, whether they agreed, and
  who chose. That is the number that says whether the synthesis is worth
  its run — a pick that agrees with the rank every week is an Opus turn
  spent re-deriving a sort.
* **Every way of failing is the old behaviour.** No credential, paused,
  the budget spent, a failed run, an unreadable reply: the severity pick,
  with the reason recorded. Nothing about the report changes except the
  row it ends on.

Pure over what it is handed — no imports of the server, no network.
"""

from __future__ import annotations

import time

MAX_CANDIDATES = 12
TIMEOUT_S = 240
MAX_TURNS = 4
MAX_WHY = 240
JOURNAL_SOURCE = "weekly_pick"

_SEVERITY = {"critical": 0, "serious": 1, "warning": 2, "info": 3}

SYSTEM = """You choose the one thing a household should deal with this week.

You are shown the problems that are open in their home right now, each
with an id, and a summary of the week. Choose the ONE whose dealing-with
would make the most difference this week. Think across the list: several
rows that share a cause are one thing, and a row that has been open for
weeks because it is how the house is may matter less than a newer one.

Rules:
- Answer with the id of a row you were shown, and nothing you were not.
- A row marked critical is never passed over for something less severe —
  if you are shown critical rows, you are only shown critical rows.
- `why` is one plain sentence a person would understand, under 30 words,
  naming the row or the shared cause. No markdown.

Answer with JSON only: {"ts": <id>, "why": "<sentence>"}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "ts": {"type": "integer"},
        "why": {"type": "string"},
    },
    "required": ["ts", "why"],
    "additionalProperties": False,
}


def _live(rows: list[dict], now: float) -> list[dict]:
    return [r for r in rows or []
            if isinstance(r, dict) and r.get("status") == "open"
            and float(r.get("snooze_until") or 0) <= now
            and isinstance(r.get("ts"), (int, float))]


def _rank(row: dict) -> tuple:
    return (_SEVERITY.get(row.get("severity"), 9), float(row.get("ts") or 0))


def candidates(open_rows: list[dict], now: float | None = None) -> list[dict]:
    """The rows the synthesis may choose from, in the baseline's own order.

    Ranked the way `weekly.one_thing` ranks them, so the first candidate
    IS the baseline and a cap can never cut it, and capped because a
    prompt listing every open row in a neglected house is a prompt about
    the backlog rather than about this week.
    """
    now = time.time() if now is None else now
    live = sorted(_live(open_rows, now), key=_rank)
    if any(r.get("severity") == "critical" for r in live):
        live = [r for r in live if r.get("severity") == "critical"]
    return live[:MAX_CANDIDATES]


def worth_asking(cands: list[dict]) -> bool:
    """Two candidates or more. One is not a choice, and nothing is paid for."""
    return len(cands) >= 2


def _age_days(row: dict, now: float) -> int:
    try:
        return max(0, int((now - float(row.get("ts") or now)) // 86400))
    except (TypeError, ValueError):
        return 0


def frame(cands: list[dict], week_lines: list[str], now: float | None = None,
          memory: str = "") -> str:
    """The prompt: the candidates by id, and the week they sit in."""
    now = time.time() if now is None else now
    lines = ["The problems open in this home right now:"]
    for r in cands:
        who = str(r.get("source_title") or r.get("source") or "").strip()
        head = (f"- id {int(r['ts'])} [{r.get('severity', 'warning')}] "
                f"{str(r.get('text') or '')[:200]}")
        head += f" (open {_age_days(r, now)} day(s)"
        head += f", from {who[:60]})" if who else ")"
        lines.append(head)
        if r.get("detail"):
            lines.append(f"  {str(r['detail'])[:240]}")
    if week_lines:
        lines += ["", "This week in the home:"]
        lines += [f"- {str(x)[:240]}" for x in week_lines[:12]]
    if str(memory or "").strip():
        lines += ["", "What brAIn knows about this home:",
                  str(memory).strip()[:4000]]
    lines += ["", "Which one should this week's report end on?"]
    return "\n".join(lines)


def parse(answer: dict | None, cands: list[dict]) -> tuple[dict, str] | None:
    """`(row, why)` when the answer names a candidate, else None."""
    if not isinstance(answer, dict):
        return None
    try:
        want = int(answer.get("ts"))
    except (TypeError, ValueError):
        return None
    for r in cands:
        if int(r.get("ts") or 0) == want:
            why = " ".join(str(answer.get("why") or "").split())[:MAX_WHY]
            return r, why
    return None


def decision(baseline: dict | None, chosen: tuple[dict, str] | None,
             reason: str = "") -> dict:
    """What the report ends on, and the journal line beside it.

    ``{"pick", "why", "chosen_by", "agreed", "extra"}`` — ``extra`` is the
    journal row's payload, kept here so the two halves of the comparison
    are written by one function and cannot be recorded differently.
    """
    if chosen is not None:
        pick, why = chosen
        chosen_by = "synthesis"
    else:
        pick, why, chosen_by = baseline, "", "severity"
    base_ts = int((baseline or {}).get("ts") or 0)
    pick_ts = int((pick or {}).get("ts") or 0)
    agreed = bool(base_ts and base_ts == pick_ts)
    extra = {"baseline": base_ts, "pick": pick_ts, "agreed": agreed,
             "chosen_by": chosen_by}
    if reason:
        extra["reason"] = str(reason)[:120]
    return {"pick": pick, "why": why, "chosen_by": chosen_by,
            "agreed": agreed, "extra": extra}


def agreement(rows: list[dict]) -> dict:
    """How often the synthesis agreed with the rank, over the journal.

    The number that decides whether the job earns its run. Only weeks the
    synthesis actually chose count toward agreement — a week it could not
    run is a week the rank chose by default, and counting those as
    agreement would flatter it.
    """
    picks = [r for r in rows or []
             if isinstance(r, dict) and r.get("source") == JOURNAL_SOURCE
             and isinstance(r.get("extra"), dict)]
    chose = [r for r in picks if r["extra"].get("chosen_by") == "synthesis"]
    agreed = sum(1 for r in chose if r["extra"].get("agreed"))
    last = picks[-1]["extra"] if picks else {}
    return {"weeks": len(picks), "synthesised": len(chose),
            "agreed": agreed, "differed": len(chose) - agreed,
            "last": {k: last.get(k) for k in
                     ("chosen_by", "agreed", "reason") if k in last}}


__all__ = ["JOURNAL_SOURCE", "MAX_CANDIDATES", "SCHEMA", "SYSTEM",
           "agreement", "candidates", "decision", "frame", "parse",
           "worth_asking"]
