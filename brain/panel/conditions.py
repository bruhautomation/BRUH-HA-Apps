"""The condition an automation you keep undoing does not have.

`override_ledger.pattern` already says the sentence: *"Evening lights is
overridden on 8 of the last 14 weekday evenings, almost always between
21:00 and 23:00."* `auto.overridden` files that as a finding, which is a
report — it says the rule is wrong for this house and leaves somebody to
open the automation editor and work out what to write. This is the other
half: the **change** that answers it, offered as a proposal with the
numbers on the card and a replay of what it would have done.

It is the first producer whose config is an **edit** rather than an
addition, which is why 1.46.0 built `automation_writer.locate` first: what
goes into `automations.yaml` is the person's own automation with one
condition added, spliced over the exact bytes of the entry it replaces so
their ordering, their comments and their quoting all survive it.

**One condition, and it is negated.** The obvious shape — add
`condition: time` with the band's `after`/`before` and the pattern's
weekdays — is wrong, and wrong in the direction that breaks a working
house. A `time` condition is a **conjunction**: it passes only when the
clock is inside its window *and* the day is in its weekday list, so an
automation carrying one would stand down every Saturday and Sunday as
well, whatever the hour. What the evidence supports is far narrower —
*not* on weekday evenings between nine and eleven — so the condition is
one `time` inside a `not`, and `test_it_still_runs_at_the_weekend` is what
holds it there.

**The band comes from the ledger and is never re-derived.**
`override_ledger.pattern` carries every floor that makes a band mean
something (four events, three separate days, still happening, three
quarters of them inside the window, and the hours reported are the ones
actually occupied rather than the window that found them). Asking those
questions again here would be a second answer to "is this a pattern", and
the second answer is the one nobody can see.

**Four refusals, each a sentence.**

*An automation with no `id`.* Home Assistant's own editor cannot change
one either — an entry with no id has nothing stable to address — so the
card says that rather than pretending brAIn is the thing in the way.

*One that already stands down over that band.* Somebody has written the
condition; a proposal to write it again is noise, and one to write a
second copy of it is worse.

*A pattern under the ledger's own floors.* `pattern` returns `None` and
nothing is offered. There is no threshold in this file.

*A protected target.* Asked at the producer as well as at the writer,
because a card offering something `automation_writer` will refuse to write
is a wasted no.

**Nothing here decides anything and nothing here writes.** It composes a
config and the sentence for it; the store dedupes it, the panel replays
it, and a person answers it. The same split `baselines.py`, `closures.py`
and `thermal.py` keep.
"""
from __future__ import annotations

import override_ledger
from checks._util import House

# The two shapes `override_ledger.pattern` reports, as Home Assistant
# spells its weekdays. A pattern with neither is "whenever", and a
# condition that stood an automation down at every hour of every day it
# was ever undone would be a switch somebody else has to find.
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKENDS = ["sat", "sun"]
DAY_SETS = {"weekdays": WEEKDAYS, "weekends": WEEKENDS}

ALL_HOURS = frozenset(range(24))

# More than this on the tab at once and the Proposals list has stopped
# being a list of things you might want. The store caps the open rows too;
# this caps what one pass may add, oldest evidence first, so a capped pass
# offers the same ones every time.
MAX_ROWS = 3

SOURCE = "condition"


def _clock(hour: int) -> str:
    return f"{int(hour) % 24:02d}:00:00"


def band_hours(from_hour: int, to_hour: int) -> set[int]:
    """The hours a band covers, wrapping midnight.

    22:00–01:00 is a real bedtime and a band that could not cross midnight
    would report the busier half of one and call that the answer — the
    same reasoning `override_ledger._band` is built on, so the reading of
    its output has to match.
    """
    span = (int(to_hour) - int(from_hour)) % 24 or 24
    return {(int(from_hour) + n) % 24 for n in range(span)}


# ---------------------------------------------------------------------------
# What the automation already says about when it may run
# ---------------------------------------------------------------------------

def _conditions(config: dict):
    """Every condition in the config, with whether it is under a `not`.

    One level of nesting, which is what a hand-written automation has: an
    `and`/`or` block and a `not` block. Deeper than that and this stops
    claiming to know what the automation already refuses, which is a
    refusal to offer rather than a wrong offer.
    """
    raw = config.get("condition")
    if raw is None:
        raw = config.get("conditions")
    if isinstance(raw, dict):
        raw = [raw]
    for cond in raw or []:
        if not isinstance(cond, dict):
            continue
        kind = str(cond.get("condition") or "")
        if kind in ("not", "and", "or"):
            inner = cond.get("conditions")
            if isinstance(inner, dict):
                inner = [inner]
            for sub in inner or []:
                if isinstance(sub, dict):
                    yield sub, kind == "not"
        else:
            yield cond, False


def _hour(value) -> int | None:
    """The hour out of an `after:`/`before:` that is a clock time.

    A `time` condition may name an `input_datetime` or a sensor instead,
    and an entity's hour is not something a config can be read for — so
    that one answers `None` and the condition it came from is not counted
    as covering anything. "I could not tell" and "it does not cover this"
    are different claims, and only the second may suppress a proposal.
    """
    text = str(value or "").strip()
    if not text or "." in text:
        return None
    head = text.split(":")[0]
    try:
        hour = int(head)
    except ValueError:
        return None
    return hour % 24 if 0 <= hour <= 24 else None


def _window(cond: dict) -> set[int] | None:
    """The hours a `time` condition passes in, or None if it cannot be read."""
    after, before = cond.get("after"), cond.get("before")
    if after is None and before is None:
        return set(ALL_HOURS)
    start = 0 if after is None else _hour(after)
    end = 24 if before is None else _hour(before)
    if start is None or end is None:
        return None
    if start == end:
        return set(ALL_HOURS)
    return band_hours(start, end)


def blocked_hours(config: dict, days: list[str]) -> set[int] | None:
    """The hours this automation's own conditions already forbid, or None.

    `None` means a condition was found that could not be read — an
    `input_datetime` for its `after`, a weekday list that only half
    overlaps the days in question — and an unreadable condition may not be
    reported as an absent one.
    """
    wanted = set(days)
    blocked: set[int] = set()
    for cond, negated in _conditions(config):
        if str(cond.get("condition") or "") != "time":
            continue
        weekdays = cond.get("weekday")
        if isinstance(weekdays, str):
            weekdays = [weekdays]
        if weekdays:
            named = {str(d).strip().lower() for d in weekdays}
            if not wanted <= named:
                # It speaks about some of these days and not others, so
                # what it forbids on the days this pattern is about is not
                # answerable from the config alone.
                if wanted & named:
                    return None
                continue
        window = _window(cond)
        if window is None:
            return None
        blocked |= window if negated else (ALL_HOURS - window)
    return blocked


# ---------------------------------------------------------------------------
# The condition itself
# ---------------------------------------------------------------------------

def time_condition(from_hour: int, to_hour: int, days: list[str]) -> dict:
    """`not (it is between these hours on these days)`.

    See the module docstring for why the `not` is not decoration: a bare
    `time` condition is a conjunction, so the direct version would stand
    the automation down every weekend too.
    """
    return {
        "condition": "not",
        "conditions": [{
            "condition": "time",
            "after": _clock(from_hour),
            "before": _clock(to_hour),
            "weekday": list(days),
        }],
    }


def with_condition(config: dict, condition: dict) -> dict:
    """The automation as it is, plus one condition. Nothing else moves.

    Home Assistant takes both spellings of the key and an entry may carry
    either; whichever this one uses is the one added to, because rewriting
    `condition:` as `conditions:` would be this deciding how somebody's
    file is spelled.
    """
    out = dict(config)
    key = "conditions" if "conditions" in out and "condition" not in out \
        else "condition"
    existing = out.get(key)
    if isinstance(existing, dict):
        existing = [existing]
    out[key] = list(existing or []) + [condition]
    return out


# ---------------------------------------------------------------------------
# Matching the ledger's automations to the file's entries
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    import re  # noqa: PLC0415 — one call, on a path walked a handful of
    # times per pass
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def index_automations(house: House) -> dict[str, dict]:
    """`entity_id -> {config, id, alias}` for everything in automations.yaml.

    An entry **with** an id is matched through the registry, which is the
    only honest answer — the entity id is whatever Home Assistant
    registered and a rename moves it. An entry **without** one is matched
    by the object id Core derives from its alias, and it is indexed
    deliberately: that automation is the one this has to refuse about by
    name, and an entry nothing could find would be reported as no pattern
    at all.
    """
    out: dict[str, dict] = {}
    for config in house.snap.get("automations") or []:
        if not isinstance(config, dict):
            continue
        cid = str(config.get("id") or "")
        alias = str(config.get("alias") or "")
        entity = house.automation_entity(cid) if cid else ""
        if not entity and alias:
            entity = f"automation.{_slug(alias)}"
        if not entity:
            continue
        out.setdefault(entity, {"config": config, "id": cid,
                                "alias": alias or entity})
    return out


# ---------------------------------------------------------------------------
# The sentence
# ---------------------------------------------------------------------------

def _when(pattern: dict) -> str:
    days = pattern.get("when_days") or ""
    return {"weekdays": "weekday", "weekends": "weekend"}.get(days, "")


def _day_word(pattern: dict) -> str:
    return {"weekday": "weekdays", "weekend": "weekend days"}.get(
        _when(pattern), "days")


def why_for(name: str, pattern: dict) -> str:
    """The ledger's numbers, said the way somebody would say them.

    A count with no denominator is not evidence — `auto.overridden` shipped
    as one and 1.34.0 fixed it — so the span the days are counted out of
    is on the sentence, and so is how much of the pattern sits inside the
    band, because "almost always" over three quarters and "always" are
    different claims.
    """
    events = int(pattern.get("events") or 0)
    days = int(pattern.get("days") or 0)
    span = max(1, round(((pattern.get("last") or 0)
                         - (pattern.get("first") or 0)) / 86400) + 1)
    share = float(pattern.get("hour_share") or 0)
    return (
        f"You have put {name} back {events} "
        f"{'time' if events == 1 else 'times'}, on {days} separate "
        f"{_day_word(pattern)} in the last {span} "
        f"{'day' if span == 1 else 'days'} — "
        f"{'always' if share >= 0.999 else 'almost always'} between "
        f"{_clock(pattern['from_hour'])[:5]} and "
        f"{_clock(pattern['to_hour'])[:5]}. Nothing about that shows up in "
        "Home Assistant: the automation ran, nothing errored, and you "
        "undid it."
    )


def title_for(name: str, pattern: dict) -> str:
    when = _when(pattern)
    days = f"on {when}s" if when else "on the days you undo it"
    return (f"Stand {name} down between "
            f"{_clock(pattern['from_hour'])[:5]} and "
            f"{_clock(pattern['to_hour'])[:5]} {days}")


# ---------------------------------------------------------------------------
# Building them
# ---------------------------------------------------------------------------

def _refusal(entry: dict, pattern: dict, days: list[str],
             patterns: list[str]) -> str:
    import automation_writer  # noqa: PLC0415 — panel-local, and the one
    # place the protected question has an answer

    if not entry["id"]:
        return ("this automation has no `id` in automations.yaml, so there "
                "is nothing stable to address it by — Home Assistant's own "
                "editor cannot change it either. Give it an id (open it in "
                "the automation editor and save it once) and brAIn will "
                "offer this again")
    blocked = blocked_hours(entry["config"], days)
    if blocked is None:
        return ("this automation already has a time condition brAIn cannot "
                "read — it names an entity rather than a clock time — so "
                "brAIn will not add a second one beside it")
    if band_hours(pattern["from_hour"], pattern["to_hour"]) <= blocked:
        return ("this automation already stands down over those hours, so "
                "there is nothing to add")
    refusal = automation_writer._protected_refusal(entry["config"], patterns)
    return refusal or ""


def build(snap: dict, rows: list[dict] | None = None, tz=None,
          now: float | None = None,
          patterns: list[str] | None = None) -> list[dict]:
    """Every condition this house's overrides can prove it wants.

    `rows` is the override ledger; `None` loads it, which is what the
    checks pass does. Each answer is a proposal object ready for
    `proposals.add`, carrying `edits` — the id of the entry the accept
    path will `replace_entry` rather than append to.
    """
    house = House(snap)
    if house.snap.get("automations") is None:
        return []                    # automations.yaml could not be read
    index = index_automations(house)
    ledger = override_ledger.load() if rows is None else rows
    patterns = list(patterns or [])

    out: list[dict] = []
    grouped = override_ledger.by_automation(ledger)
    for entity in sorted(grouped, key=lambda e: -len(grouped[e])):
        entry = index.get(entity)
        if not entry:
            continue                 # an automation this file does not hold
        pattern = override_ledger.pattern(grouped[entity], tz, now)
        if not pattern or "from_hour" not in pattern:
            continue                 # under the ledger's floors, or no band
        days = DAY_SETS.get(str(pattern.get("when_days") or ""))
        if not days:
            continue                 # "whenever" is not a condition
        name = entry["alias"]
        obj = {
            "kind": "condition",
            "source": SOURCE,
            "title": title_for(name, pattern),
            "why": why_for(name, pattern),
            "pattern": {k: pattern.get(k) for k in
                        ("events", "days", "from_hour", "to_hour",
                         "hour_share", "when_days")},
            "automation": {"entity_id": entity, "alias": name,
                           "id": entry["id"]},
        }
        refusal = _refusal(entry, pattern, days, patterns)
        if refusal:
            # Carried rather than dropped: "brAIn found nothing" and "brAIn
            # found this and will not act on it" are different answers, and
            # the second is the one that names the thing to change.
            obj["refused"] = refusal
            out.append(obj)
            continue
        condition = time_condition(pattern["from_hour"], pattern["to_hour"],
                                   days)
        obj["config"] = with_condition(entry["config"], condition)
        obj["edits"] = entry["id"]
        obj["condition"] = condition
        obj["before_config"] = entry["config"]
        out.append(obj)
        if sum(1 for r in out if not r.get("refused")) >= MAX_ROWS:
            break
    return out


__all__ = ["ALL_HOURS", "DAY_SETS", "MAX_ROWS", "SOURCE", "WEEKDAYS",
           "WEEKENDS", "band_hours", "blocked_hours", "build",
           "index_automations", "time_condition", "title_for",
           "why_for", "with_condition"]
