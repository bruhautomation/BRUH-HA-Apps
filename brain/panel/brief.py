"""The morning brief: one message, at the hour this house actually gets up.

Everything brAIn reports lives on a tab somebody has to open. The
Findings tab fills up overnight and is read at the weekend; the health
verdict is answered by a sensor nobody has on a dashboard. What is
missing is the one place people already are — a phone, once, in the
morning — and the reason it has not existed is that the two obvious ways
to build it are both worse than nothing.

**A brief on a timer is not a rhythm.** 07:00 is early on a Sunday and
late on a Tuesday in the same house, and somebody who has to keep
correcting when it arrives stops reading it. `panel/rhythm.py` measures
when this house actually stirs, weekdays and weekends apart, and says
nothing rather than guessing until it has a fortnight of days.

**And a brief that arrives every day says nothing every day.** "All
quiet" each morning is the message people mute, and it costs a Claude
turn — the most expensive thing this add-on does — to produce. So the
decision to send is made *before* any model is asked, out of things that
are already counted: findings filed since the last one, a health verdict
that is not `ok`, an unusual night. `worth_saying` is that decision, it
is deterministic, and an empty answer costs nothing at all.

What the model is for is the sentence. Given the reasons, it says them
the way a person would in under eighty words, and it can look anything
up that it needs (read-only tools, the same set an insight card gets).
It is not handed the house.
"""
from __future__ import annotations

import time

# Under eighty words, because this is read on a lock screen. A brief that
# has to be opened to be read is a notification that failed.
MAX_WORDS = 80
# The floor under it too: a model that answers in four words has not
# answered, and sending that is worse than the silence it replaced.
MIN_CHARS = 40
# One turn, and a short one. The reasons are already gathered; what is
# left is a paragraph, and a brief that takes eight minutes to write has
# missed the morning it was for.
TIMEOUT_S = 180
MAX_TURNS = 8

SYSTEM = """You write one short morning message about somebody's home.

You are given the things that are already known to be worth mentioning.
Say them the way a person who lives there would, in ONE paragraph of
under 80 words, in plain sentences. No greeting, no sign-off, no
markdown, no bullet points, no headings — this is read on a lock screen.

Rules that matter more than style:
- Say only what the reasons support. You have read-only tools; use them
  to make a reason specific ("the freezer is at -12, usually -18")
  rather than to find new material.
- Lead with whatever a person would want to act on first.
- Never invent a number. If you did not read it, do not say it.
- Do not list everything. Two or three things is a message; six is a
  report, and a report is what this replaces.
- No praise, no reassurance, no "everything else looks great".
"""


def worth_saying(state: dict) -> list[str]:
    """The reasons to send one at all, in the order they matter.

    Deterministic and cheap, and taken BEFORE any model runs: a brief
    nobody needed still costs a Claude turn, and "all quiet" every
    morning is the message people mute.
    """
    reasons: list[str] = []

    health = (state.get("health") or {})
    if health.get("state") in ("degraded", "failed"):
        reasons.append(
            f"brAIn itself is {health['state']}: "
            f"{health.get('reason') or 'no reason recorded'}")

    fresh = state.get("new_findings") or []
    if fresh:
        worst = fresh[0]
        reasons.append(
            f"{len(fresh)} new finding(s) since the last brief, the first "
            f"being: [{worst.get('severity', 'warning')}] "
            f"{worst.get('text', '')}")
        for f in fresh[1:4]:
            reasons.append(f"also: [{f.get('severity', 'warning')}] "
                           f"{f.get('text', '')}")

    night = state.get("overnight") or {}
    if night.get("unattributed_spike"):
        reasons.append(
            f"{night['unattributed_spike']} changes overnight with no "
            "recorded cause, which is more than usual for this house")

    return reasons


def frame(reasons: list[str], state: dict) -> str:
    """The prompt. A frame, not a bundle — the tools fetch the rest."""
    lines = ["Write this morning's message for the home.", "",
             "What is worth mentioning, already established:"]
    lines += [f"- {r}" for r in reasons]

    night = state.get("overnight") or {}
    if night.get("counts"):
        counts = ", ".join(f"{k}: {v}" for k, v in
                           sorted(night["counts"].items()) if v)
        lines += ["", f"Overnight, by cause — {counts}."]
    if state.get("woke_at"):
        lines.append(f"It is about {state['woke_at']}, which is when this "
                     "house usually starts moving.")
    lines += ["",
              "Use your read-only tools to make any of the above specific "
              + "before you write. Then write the paragraph and nothing else."]
    return "\n".join(lines)


def tidy(text: str) -> str:
    """One paragraph, capped, or empty when there is nothing usable.

    A model that answered in four words has not answered, and sending
    that is worse than the silence it replaced.
    """
    body = " ".join(str(text or "").split())
    if len(body) < MIN_CHARS:
        return ""
    words = body.split(" ")
    if len(words) > MAX_WORDS:
        body = " ".join(words[:MAX_WORDS]).rstrip(",;:") + "…"
    return body


def due(now: float, minute_now: int, wake_minute: float | None,
        fallback_hour: int, last_sent: float,
        grace_min: int = 45) -> bool:
    """Whether this is the morning's moment, and it has not already gone.

    The window opens at the measured wake (or the fallback hour where
    nothing has been measured) and closes `grace_min` later, so a panel
    that was restarted at 09:00 does not deliver breakfast at lunchtime.
    Once a day: `last_sent` is what makes a five-minute loop send one.
    """
    if now - last_sent < 12 * 3600:
        return False
    target = wake_minute if wake_minute is not None else fallback_hour * 60
    return 0 <= (minute_now - target) <= grace_min


def state_from(findings: list[dict], health: dict, overnight: dict,
               since: float) -> dict:
    """Everything `worth_saying` reads, gathered from what is already known."""
    fresh = [f for f in findings or []
             if float(f.get("ts") or 0) > since]
    order = {"critical": 0, "serious": 1, "warning": 2, "info": 3}
    fresh.sort(key=lambda f: (order.get(f.get("severity", "warning"), 9),
                             -float(f.get("ts") or 0)))
    return {
        "new_findings": fresh,
        "health": health or {},
        "overnight": overnight or {},
        "since": since,
        "now": time.time(),
    }


__all__ = [
    "MAX_TURNS", "MAX_WORDS", "MIN_CHARS", "SYSTEM", "TIMEOUT_S", "due",
    "frame", "state_from", "tidy", "worth_saying",
]
