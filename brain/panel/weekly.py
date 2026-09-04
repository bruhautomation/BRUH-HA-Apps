"""The weekly report: what the week was, once, to everybody in the house.

The morning brief and this are not the same thing with different timers,
and treating them as one is the mistake that makes weekly reports
unread. The brief asks *is there anything* and its whole design is a
refusal — it stays silent most mornings on purpose. A weekly report
asks *what happened*, and its failure mode is the opposite one: a
report that lists everything, which is the dozen unread cards it was
meant to replace with the covers taken off.

So the gathering is capped section by section here, deterministically,
before any model runs, and the model's job is to say four things rather
than to choose which four.

**"One thing to do this week" is chosen before the model, not by it.**
Asked to pick, a model picks the one it can write the best sentence
about — which is the one with the most detail, not the one that matters.
It is the worst open severity, then the longest open, and the model is
told which one it is writing about.

**A week with nothing in it is still not a report.** `worth_reporting`
floors it on *material* rather than on urgency: no energy, nothing filed
or settled either way, and nothing learned is a week where the honest
message is silence. This is the same rule the brief carries and a
different threshold, because the two are answering different questions.

**"Still open" is not "filed".** A finding raised and settled inside the
same week is no longer in the store, so counting what is left
undercounts what happened — the number is named for what it actually is
rather than dressed up as the one nobody can compute.

**The day is the gate and the hour is a preference.** Unlike the brief,
whose window closes 45 minutes after the house gets up because a brief
delivered at lunchtime is not a morning brief, a weekly report delivered
on Sunday afternoon is still that week's. Skipping the week to protect
the hour would be the wrong trade, so the window only ever opens.
"""
from __future__ import annotations

import json
import os
import time

import energy

# Read sitting down rather than off a lock screen, so longer than the
# brief — but a "report" people scroll is a report people archive.
MAX_WORDS = 150
MIN_CHARS = 60
# Four sections and a couple of lookups. This is the least time-critical
# thing the add-on runs, so it gets room rather than a race.
TIMEOUT_S = 300
MAX_TURNS = 10

# The change log the memory consolidator writes, which is the only
# record of what actually reached `memory.md` and when.
MEMORY_LOG = os.environ.get(
    "BRAIN_MEMORY_LOG", "/config/.brain/memory/memory.log.jsonl")

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")
DEFAULT_DAY = "sunday"

# Caps per section. A section that runs long is a section that buried
# the one beside it.
MAX_LEARNED = 6
MAX_SETTLED_SOURCES = 4
WEEK_S = 7 * 86400
# A report is once a week; six days is the guard that lets a restarted
# panel still send this week's without ever sending two.
MIN_GAP_S = 6 * 86400

SYSTEM = """You write one short weekly message about somebody's home.

You are given the week's own numbers, already gathered. Say them the way
a person who lives there would, in under 150 words, in plain sentences
and at most three short paragraphs. No greeting, no sign-off, no
markdown, no bullet points, no headings — this is delivered as a
notification and read by everyone in the house.

Rules that matter more than style:
- Say only what the numbers support. Never invent one, and never round a
  number into a different claim ("about double" for 40% more).
- Cover the energy, what was found and answered, and what was learned —
  briefly. Then end with the one thing to do, which has already been
  chosen for you: write about that one and no other.
- A section that was unavailable is not a zero. Leave it out entirely
  rather than reporting nothing as good news.
- You have read-only tools. Use them to make one thing specific, not to
  find new material — anything you go and discover is next week's.
- No praise, no reassurance, no "a great week for the house".
"""


# ---------------------------------------------------------------------------
# The week's own numbers
# ---------------------------------------------------------------------------

def day_index(name: str) -> int:
    """`"sunday"` as 6. Anything unreadable is the default, not Monday —
    a mistyped option must not quietly move the report to the start of
    the week, where a "week" is one day old."""
    try:
        return DAYS.index(str(name or "").strip().lower())
    except ValueError:
        return DAYS.index(DEFAULT_DAY)


def learned(path: str | None = None, since: float = 0.0,
            limit: int = MAX_LEARNED) -> dict:
    """What reached `memory.md` this week, from the consolidator's log.

    `{"added": [...], "removed": n, "available": bool}`. Removals are
    counted and not quoted: a line leaving the document is a correction,
    and quoting the wrong thing back at somebody as news is worse than
    saying a correction happened.
    """
    out: dict = {"added": [], "removed": 0, "available": False, "total": 0}
    try:
        with open(path or MEMORY_LOG, "r", encoding="utf-8") as fh:
            rows = fh.readlines()[-500:]
    except OSError:
        # No consolidation has ever run, or /config is not there. Either
        # way this is "I could not look", which is not "nothing learned".
        return out
    out["available"] = True
    added: list[str] = []
    for raw in rows:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            continue
        if float(ts) <= since:
            continue
        for line in row.get("added") or []:
            if isinstance(line, str) and line.strip():
                added.append(line.strip()[:200])
        removed = row.get("removed") or []
        out["removed"] += len(removed) if isinstance(removed, list) else 0
    out["total"] = len(added)
    out["added"] = added[-limit:]
    return out


def week_findings(open_rows: list[dict], settled: list[dict],
                  since: float) -> dict:
    """What was raised and what was answered, over the window.

    `still_open` is named for what it is: a row raised and settled inside
    the same week has left the store, so nothing here can count what was
    "filed" without counting it twice or not at all.
    """
    rows = [r for r in open_rows or [] if isinstance(r, dict)]
    fresh = [r for r in rows if float(r.get("ts") or 0) > since]
    ended = [e for e in settled or []
             if isinstance(e, dict) and float(e.get("ts") or 0) > since]
    right = sum(1 for e in ended if e.get("kind") == "fixed")
    wrong = sum(1 for e in ended if e.get("kind") == "ignored")

    by: dict[str, int] = {}
    for e in ended:
        title = str(e.get("source_title") or e.get("source") or "").strip()
        if title:
            by[title] = by.get(title, 0) + 1
    top = sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "still_open": len(fresh),
        "open_now": len(rows),
        "settled": len(ended),
        "confirmed": right,
        "wrong": wrong,
        "by_source": top[:MAX_SETTLED_SOURCES],
    }


_SEVERITY = {"critical": 0, "serious": 1, "warning": 2, "info": 3}


def one_thing(open_rows: list[dict], now: float | None = None) -> dict | None:
    """The single finding this week's report should end on.

    Worst severity, then longest open. Deterministic on purpose: a model
    asked to choose picks the row it can write about, which is the one
    carrying the most detail rather than the one carrying the most
    consequence.
    """
    now = time.time() if now is None else now
    live = [r for r in open_rows or []
            if isinstance(r, dict) and r.get("status") == "open"
            and float(r.get("snooze_until") or 0) <= now]
    if not live:
        return None
    live.sort(key=lambda r: (_SEVERITY.get(r.get("severity"), 9),
                             float(r.get("ts") or 0)))
    return live[0]


def gather(open_rows: list[dict], settled: list[dict], power: dict,
           since: float, memory_path: str | None = None,
           now: float | None = None) -> dict:
    """Everything the decision and the prompt read. No model, no network."""
    now = time.time() if now is None else now
    return {
        "since": since,
        "now": now,
        "energy": power or {},
        "findings": week_findings(open_rows, settled, since),
        "learned": learned(memory_path, since),
        "one_thing": one_thing(open_rows, now),
    }


# ---------------------------------------------------------------------------
# Whether to send, and what to say
# ---------------------------------------------------------------------------

def worth_reporting(state: dict) -> bool:
    """Whether the week holds enough to be worth a message and a turn.

    A floor on material, not on urgency — which is the whole difference
    from the brief. A house where nothing was found, nothing answered,
    nothing learned and no meter read is a house where the honest
    weekly report is silence.
    """
    found = state.get("findings") or {}
    if found.get("still_open") or found.get("settled"):
        return True
    if (state.get("learned") or {}).get("total"):
        return True
    power = state.get("energy") or {}
    return bool(power.get("available") and power.get("energy"))


def _energy_lines(power: dict) -> list[str]:
    if not power.get("available"):
        return []
    lines = []
    for name, key in (("Electricity", "energy"), ("Cost", "cost")):
        half = power.get(key)
        if not half:
            continue
        unit = half.get("unit") or ""
        text = f"{name} over the last 7 days: {half['this']}{unit}"
        if half.get("comparable"):
            pct = half.get("change_pct")
            if pct is None:
                text += f" (the week before used {half['last']}{unit})"
            elif not energy.worth_mentioning(pct):
                # A meter drifts and a warm week is a warm week. "1.2%
                # more than last week" every week is a line people learn
                # to skip, and the line beside it goes with it.
                text += (f", about the same as the {half['last']}{unit} "
                         + "of the week before")
            else:
                way = "more" if pct >= 0 else "less"
                text += (f", {abs(pct)}% {way} than the {half['last']}{unit} "
                         + "of the week before")
        else:
            text += (f" — but only {half['days']} of 7 days have complete "
                     "statistics, so there is no comparison to make")
        lines.append(text)
    return lines


def frame(state: dict) -> str:
    """The prompt. The week's numbers, and the one thing already chosen."""
    lines = ["Write this week's message for the home.", "",
             "The week's numbers, already gathered:"]

    power = state.get("energy") or {}
    body = _energy_lines(power)
    if body:
        lines += [f"- {b}" for b in body]
    elif power.get("reason"):
        lines.append(f"- No energy figures this week: {power['reason']}. "
                     "Do not mention energy at all.")

    found = state.get("findings") or {}
    lines.append(
        f"- {found.get('settled', 0)} problem(s) were answered this week "
        f"({found.get('confirmed', 0)} confirmed as real, "
        f"{found.get('wrong', 0)} marked as a misread of the house); "
        f"{found.get('still_open', 0)} raised this week are still open, "
        f"and {found.get('open_now', 0)} are open in total.")
    for title, count in found.get("by_source") or []:
        lines.append(f"  - {count} of those came from {title}")

    lore = state.get("learned") or {}
    if not lore.get("available"):
        lines.append("- Nothing can be said about what was learned: the "
                     "memory log could not be read. Do not mention it.")
    elif lore.get("total"):
        lines.append(f"- {lore['total']} new thing(s) were filed into "
                     "memory this week, including:")
        lines += [f"  - {line}" for line in lore.get("added") or []]
        if lore.get("removed"):
            lines.append(f"  - and {lore['removed']} line(s) were corrected "
                         "or removed")
    else:
        lines.append("- Nothing new was filed into memory this week.")

    pick = state.get("one_thing")
    if pick:
        lines += ["",
                  "The one thing to do this week — write about THIS one "
                  + "and no other:",
                  f"- [{pick.get('severity', 'warning')}] "
                  + f"{pick.get('text', '')}"]
        if pick.get("detail"):
            lines.append(f"  {str(pick['detail'])[:300]}")
        if pick.get("fix"):
            lines.append(f"  Suggested: {str(pick['fix'])[:300]}")
    else:
        lines += ["",
                  "There is nothing open to end on. Say so in a few "
                  + "words rather than finding something."]

    lines += ["",
              "Use your read-only tools at most once or twice, to make "
              + "one of the above specific. Then write the message and "
              + "nothing else."]
    return "\n".join(lines)


def tidy(text: str) -> str:
    """Capped, and empty when there is nothing usable.

    Paragraph breaks survive because this one is allowed up to three of
    them; everything else collapses, so a model that reached for a bullet
    list does not deliver one.
    """
    paras = [" ".join(p.split()) for p in str(text or "").split("\n\n")]
    body = "\n\n".join(p for p in paras if p)
    if len(" ".join(body.split())) < MIN_CHARS:
        return ""
    words = body.split(" ")
    if len(words) > MAX_WORDS:
        body = " ".join(words[:MAX_WORDS]).rstrip(",;:") + "…"
    return body


def due(now: float, weekday: int, minute_now: int, wake_minute: float | None,
        fallback_hour: int, last_sent: float, want_day: int) -> bool:
    """Whether this is the week's moment.

    The day is the gate; the hour only ever opens the window. A weekly
    report delivered on Sunday afternoon is still that week's, and
    skipping a week to protect an hour is the wrong trade — which is
    exactly the trade the brief makes, for the opposite reason.
    """
    if now - last_sent < MIN_GAP_S:
        return False
    if weekday != want_day:
        return False
    target = wake_minute if wake_minute is not None else fallback_hour * 60
    return minute_now >= target


__all__ = [
    "DAYS", "DEFAULT_DAY", "MAX_LEARNED", "MAX_TURNS", "MAX_WORDS",
    "MEMORY_LOG", "MIN_CHARS", "MIN_GAP_S", "SYSTEM", "TIMEOUT_S", "WEEK_S",
    "day_index", "due", "frame", "gather", "learned", "one_thing", "tidy",
    "week_findings", "worth_reporting",
]
