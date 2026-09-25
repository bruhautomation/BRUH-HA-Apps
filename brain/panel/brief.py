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
are already known: findings filed since the last one, a serious one still
unanswered, a health verdict that is not `ok`, a door open that is
normally shut, a light somebody left on all night. `worth_saying` is that
decision, it is deterministic, and an empty answer costs nothing at all.

**And a reason has to be something a person would act on.** The first
cut counted the night — "40 changes overnight, 31 with no recorded
cause" — and that is the logbook read aloud: nobody can do anything with
it, and it arrived on exactly the mornings nothing was wrong. So nothing
here is a count of activity. A reason names a thing (a door, a light, a
freezer, an add-on), says what is true of it now, and carries the fix
the finding already knows — and a light an automation turned on is not a
light somebody forgot, which is the one thing the night's causes are
still read for.

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
# A short run. The reasons are already gathered; what is left is a
# paragraph, and a brief that takes eight minutes to write has missed the
# morning it was for — so the timeout is the budget, and the turn cap is
# only the runaway guard behind it.
TIMEOUT_S = 180
MAX_TURNS = 24

# A finding at `info` is a note, not news: it is on the tab for whoever
# looks, and a brief that reads notes aloud is the boilerplate this
# replaced. New rows at warning and above are reasons; `info` never is.
NEWS_SEVERITIES = ("critical", "serious", "warning")
# A problem still open from before the last brief is mentioned again only
# when it is serious and has waited this long — a critical row nobody has
# answered is worth one more line; a warning from Tuesday is not.
STILL_OPEN_SEVERITIES = ("critical", "serious")
STILL_OPEN_AFTER_S = 24 * 3600
MAX_NEW = 4
MAX_STILL_OPEN = 2
# A light on this long at wake-up was left on overnight. One on for longer
# than LEFT_ON_MAX_HOURS is a light somebody keeps on (a porch lamp, a
# fish tank), and telling them about it every morning is a message they
# mute.
LEFT_ON_HOURS = 6
LEFT_ON_MAX_HOURS = 36
# A light an automation, a script, a scene or brAIn turned on was turned
# on on purpose: whatever put it there knows it is on. Only a light a
# person (or a wall switch) left on is news.
INTENTIONAL_CAUSES = frozenset({"automation", "script", "scene", "brain"})
MAX_NAMED = 4
# Share of an hour a closure is normally open, under which "open now" is
# odd. The same bar the bedtime check (`checks/evening.RARE_OPEN`) uses,
# named here because the brief is not a check and must not import one.
RARE_OPEN = 0.05

SYSTEM = """You write one short morning message about somebody's home.

You are given the things that are already known to be worth mentioning.
Say them the way a person who lives there would, in ONE paragraph of
under 80 words, in plain sentences. No greeting, no sign-off, no
markdown, no bullet points, no headings — this is read on a lock screen.

Every sentence must name a specific thing (a device, a door, a room, an
add-on) and say what is true of it or what to do about it. If a sentence
could be sent to any house on any morning, delete it.

Rules that matter more than style:
- Say only what the reasons support. You have read-only tools; use them
  to make a reason specific ("the freezer is at -12, usually -18")
  rather than to find new material.
- Lead with whatever a person would want to act on first, and give the
  action in a few words when the reason carries one.
- Never invent a number. If you did not read it, do not say it.
- Never summarise activity: no counts of changes, no "a quiet night",
  no "lights turned on and off", no weather unless it bears on a reason.
- Do not list everything. Two or three things is a message; six is a
  report, and a report is what this replaces.
- No praise, no reassurance, no "everything else looks great".
"""


def _finding_line(f: dict) -> str:
    """One finding as a reason: what, the specifics, and what to do."""
    text = str(f.get("text") or "").strip()
    detail = str(f.get("detail") or "").strip()
    fix = str(f.get("fix") or "").strip()
    line = f"[{f.get('severity', 'warning')}] {text}"
    if detail:
        line += f" — {detail[:240]}"
    if fix:
        line += f" What to do: {fix[:160]}"
    return line


def worth_saying(state: dict) -> list[str]:
    """The reasons to send one at all, in the order they matter.

    Deterministic and cheap, and taken BEFORE any model runs: a brief
    nobody needed still costs a Claude turn, and "all quiet" every
    morning is the message people mute. Every reason names a thing;
    nothing here is a count of what the house did overnight.
    """
    reasons: list[str] = []

    health = (state.get("health") or {})
    if health.get("state") in ("degraded", "failed"):
        reasons.append(
            f"brAIn itself is {health['state']}: "
            f"{health.get('reason') or 'no reason recorded'}")

    fresh = [f for f in state.get("new_findings") or []
             if f.get("severity", "warning") in NEWS_SEVERITIES]
    if fresh:
        reasons.append("New since the last brief: " + _finding_line(fresh[0]))
        for f in fresh[1:MAX_NEW]:
            reasons.append("Also new: " + _finding_line(f))

    for f in (state.get("still_open") or [])[:MAX_STILL_OPEN]:
        days = int(max(0.0, float(state.get("now") or time.time())
                       - float(f.get("ts") or 0)) // 86400)
        waited = f"{days} day(s)" if days else "since yesterday"
        reasons.append(f"Still waiting on you ({waited}): " + _finding_line(f))

    # Something was mended while the house was asleep, and the one place
    # anybody would find out is here. The sentences are composed by
    # `healing.brief_lines` rather than here: they need the house's own
    # clock and the healer's vocabulary, and this module holds neither.
    for line in (state.get("healing") or [])[:3]:
        if str(line or "").strip():
            reasons.append(str(line).strip())

    morning = state.get("morning") or {}
    opened = morning.get("open_unusual") or []
    if opened:
        reasons.append(
            _names(opened) + (" are" if len(opened) > 1 else " is")
            + " open right now, which is unusual for this hour here")
    left = morning.get("left_on") or []
    if left:
        parts = [f"{row['name']} (on since {row['since']})"
                 for row in left[:MAX_NAMED]]
        more = len(left) - MAX_NAMED
        reasons.append(
            "Left on overnight, switched on by hand rather than by an "
            "automation: " + ", ".join(parts)
            + (f", and {more} more" if more > 0 else ""))

    return reasons


def _names(names: list[str]) -> str:
    names = [str(n) for n in names if str(n or "").strip()]
    shown = names[:MAX_NAMED]
    more = len(names) - len(shown)
    if more > 0:
        return ", ".join(shown) + f" and {more} more"
    if len(shown) > 1:
        return ", ".join(shown[:-1]) + " and " + shown[-1]
    return shown[0] if shown else ""


def _parse_iso(value) -> float | None:
    import datetime  # noqa: PLC0415 — only this helper needs it

    try:
        stamp = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.timestamp()


def morning_facts(states: list[dict], night_actions: list[dict], now: float,
                  *, closures_store: dict | None = None,
                  bucket: int | None = None, clock=None) -> dict:
    """What is true of the house at wake-up that somebody would act on.

    Two things, both read off the states the brief fetches once: a
    closure open that is normally shut at this hour of the week (the
    bedtime check's measurement, asked in the morning), and a light left
    on overnight by a person. The night's causes are read for that one
    purpose — the last thing to turn a light on says whether it is on
    on purpose — and are never reported themselves.

    Pure over what it is handed; `clock` turns an epoch into the house's
    own "HH:MM" and defaults to UTC for a caller with no timezone.
    """
    import datetime  # noqa: PLC0415

    def hhmm(ts: float) -> str:
        if clock is not None:
            return clock(ts)
        return datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc).strftime("%H:%M")

    last_on: dict[str, str] = {}
    for a in sorted(night_actions or [], key=lambda a: float(a.get("ts") or 0)):
        eid = str(a.get("entity_id") or "")
        if eid.startswith("light.") and str(a.get("state")) == "on":
            last_on[eid] = str(a.get("cause") or "unattributed")

    left_on: list[dict] = []
    open_unusual: list[str] = []
    entities = ((closures_store or {}).get("entities") or {})
    for st in states or []:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        attrs = st.get("attributes") or {}
        name = str(attrs.get("friendly_name") or eid)
        state = str(st.get("state") or "").lower()
        if eid.startswith("light.") and state == "on":
            # A light group repeats its members; the members are the news.
            if isinstance(attrs.get("entity_id"), list):
                continue
            since = _parse_iso(st.get("last_changed"))
            if since is None:
                continue
            hours = (now - since) / 3600.0
            if not LEFT_ON_HOURS <= hours <= LEFT_ON_MAX_HOURS:
                continue
            if last_on.get(eid) in INTENTIONAL_CAUSES:
                continue
            left_on.append({"entity_id": eid, "name": name,
                            "since": hhmm(since), "ts": since})
        elif eid in entities and bucket is not None:
            import closures  # noqa: PLC0415 — only the closures branch

            if state not in closures.OPEN_STATES:
                continue
            usual = closures.usual_open(entities[eid], bucket)
            # None is "not watched at this hour", which is not "never open".
            if usual is not None and usual <= RARE_OPEN:
                open_unusual.append(name)
    left_on.sort(key=lambda r: r["ts"])
    return {"left_on": left_on, "open_unusual": sorted(open_unusual)}


def frame(reasons: list[str], state: dict) -> str:
    """The prompt. A frame, not a bundle — the tools fetch the rest."""
    lines = ["Write this morning's message for the home.", "",
             "What is worth mentioning, already established:"]
    lines += [f"- {r}" for r in reasons]

    if state.get("woke_at"):
        lines.append(f"It is about {state['woke_at']}, which is when this "
                     "house usually starts moving.")

    # What brAIn has measured, and what it has been told. Both blocks are
    # built by `categories` and handed in by the caller: this module has
    # no store of its own and a brief that re-derived either would be a
    # second answer to what this house is like. Neither is material —
    # `worth_saying` has already decided there is something to say — they
    # are what makes a reason SPECIFIC without spending a tool call, and
    # what stops a message repeating something the homeowner has
    # corrected.
    if str(state.get("house") or "").strip():
        lines += ["", str(state["house"]).strip()]
    if str(state.get("memory") or "").strip():
        lines += ["", str(state["memory"]).strip()]
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
               since: float, healing: list[str] | None = None,
               morning: dict | None = None,
               now: float | None = None) -> dict:
    """Everything `worth_saying` reads, gathered from what is already known.

    `findings` is the LIVE list: a row triage held back is shown to
    nobody, and reading it aloud on a phone would undo the hold.
    """
    now = time.time() if now is None else float(now)
    order = {"critical": 0, "serious": 1, "warning": 2, "info": 3}

    def rank(f):
        return (order.get(f.get("severity", "warning"), 9),
                -float(f.get("ts") or 0))

    live = [f for f in findings or []
            if str(f.get("status") or "open") in ("open", "needs_you",
                                                  "failed", "planned")]
    fresh = sorted((f for f in live if float(f.get("ts") or 0) > since),
                   key=rank)
    still = sorted((f for f in live
                    if float(f.get("ts") or 0) <= since
                    and f.get("severity") in STILL_OPEN_SEVERITIES
                    and now - float(f.get("ts") or 0) >= STILL_OPEN_AFTER_S),
                   key=rank)
    return {
        "new_findings": fresh,
        "still_open": still,
        "health": health or {},
        "overnight": overnight or {},
        "morning": morning or {},
        "healing": list(healing or []),
        "since": since,
        "now": now,
    }


__all__ = [
    "MAX_TURNS", "MAX_WORDS", "MIN_CHARS", "SYSTEM", "TIMEOUT_S", "due",
    "frame", "morning_facts", "state_from", "tidy", "worth_saying",
]
