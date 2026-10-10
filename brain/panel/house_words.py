"""What a model wrote about the house, in the words the house uses.

A model-written row — a Resident case, an insight card's finding, a chat's
advice — is told to name things the way the homeowner does, and it mostly
does. What it slips on is always the same three things, and each is a
sentence a person has to translate before they can read the card:

  * an **entity id** (`sensor.hall_motion`) where the house has a name for
    it ("Hall motion");
  * a **time in UTC** ("04:00–14:00 UTC", "2026-10-09T04:00:00Z") where
    every other surface in the panel speaks the house's local time;
  * the add-on's own **Supervisor slug** (`abcd1234_brain`), which is how
    brAIn appears in a log line and is "brAIn" everywhere a person reads.

So this is the deterministic half of the rule the prompts state: it turns
what it can recognise and leaves everything else exactly as it was. An id
the house has no name for stays an id — a made-up name is worse than the
id — and a time it cannot parse keeps its words. It is pure over what it
is handed (the names map, the zone, the clock), imports nothing of the
panel's, and never raises: a cleanup that failed returns the text it was
given. (`plain_words` is the other half of the same rule, for brAIn's
own machinery: what its producers and jobs are called.)
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Mapping

# An entity id in prose. The shape `server._ENTITY_IN_TEXT_RE` reads, with
# an optional backtick either side so `sensor.x` loses its code quotes too.
_ENTITY_RE = re.compile(r"`?\b([a-z_]+)\.([a-z0-9_]+)\b`?")
# The add-on's Supervisor slug: an 8-hex repository prefix (or `local`)
# and `_brain`, optionally with the `addon_` a container name carries.
_SLUG_RE = re.compile(r"\b(?:addon_)?(?:[0-9a-f]{8}|local)_brain\b")
# An ISO stamp that says it is UTC: a `Z`, `+00:00`, or the word after it.
_ISO_UTC_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})[T ](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?"
    r"(?:\s*(?:Z|\+00:?00)\b|Z|\+00:?00|\s+(?:UTC|GMT)\b)")
# A clock time, or a range of two, followed by UTC or GMT.
_CLOCK_UTC_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})(?:\s*(–|—|-|to)\s*(\d{1,2}):(\d{2}))?"
    r"\s*\(?(?:UTC|GMT)\)?")


def _names_for(names: Mapping | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for eid, row in (names or {}).items():
        name = row.get("name") if isinstance(row, dict) else row
        name = str(name or "").strip()
        if name and name != eid:
            out[str(eid)] = name
    return out


def _local(day: dt.date, hour: int, minute: int,
           tz: dt.tzinfo | None) -> dt.datetime | None:
    if hour > 23 or minute > 59:
        return None
    moment = dt.datetime(day.year, day.month, day.day, hour, minute,
                         tzinfo=dt.timezone.utc)
    return moment.astimezone(tz) if tz is not None else moment


def _clock(moment: dt.datetime) -> str:
    return moment.strftime("%H:%M")


def _date_clock(moment: dt.datetime) -> str:
    return f"{moment.day} {moment.strftime('%b')} {_clock(moment)}"


def entities(text: str, names: Mapping | None) -> str:
    """Every id the names map knows, as its name; the rest left alone."""
    known = _names_for(names)
    if not known or not text:
        return text

    def swap(m: re.Match) -> str:
        eid = f"{m.group(1)}.{m.group(2)}"
        return known.get(eid, m.group(0))

    out = _ENTITY_RE.sub(swap, text)
    # "Hall motion (sensor.hall_motion)" became "Hall motion (Hall motion)".
    for name in set(known.values()):
        out = re.sub(re.escape(name) + r"\s*\(\s*" + re.escape(name)
                     + r"\s*\)", name, out)
    return out


def times(text: str, tz: dt.tzinfo | None,
          now: float | None = None) -> str:
    """UTC times as the house's local time, where they can be read."""
    if not text or ("UTC" not in text and "GMT" not in text
                    and not re.search(r"\d(?:Z|\+00:?00)\b", text)):
        return text
    today = (dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
             if now is not None else dt.datetime.now(dt.timezone.utc).date())

    def iso(m: re.Match) -> str:
        try:
            day = dt.date.fromisoformat(m.group(1))
        except ValueError:
            return m.group(0)
        moment = _local(day, int(m.group(2)), int(m.group(3)), tz)
        return _date_clock(moment) if moment else m.group(0)

    def clock(m: re.Match) -> str:
        first = _local(today, int(m.group(1)), int(m.group(2)), tz)
        if first is None:
            return m.group(0)
        if not m.group(3):
            return _clock(first)
        second = _local(today, int(m.group(4)), int(m.group(5)), tz)
        if second is None:
            return m.group(0)
        dash = "–" if m.group(3) in ("-", "—", "–") else f" {m.group(3)} "
        return f"{_clock(first)}{dash}{_clock(second)}"

    return _CLOCK_UTC_RE.sub(clock, _ISO_UTC_RE.sub(iso, text))


def slug(text: str) -> str:
    """The add-on's Supervisor slug as the name people know it by."""
    return _SLUG_RE.sub("brAIn", text) if text else text


def plain(text: str, names: Mapping | None = None,
          tz: dt.tzinfo | None = None, now: float | None = None) -> str:
    """`text` with the three slips turned into the house's own words."""
    if not isinstance(text, str) or not text:
        return text
    try:
        return entities(slug(times(text, tz, now)), names)
    except Exception:  # noqa: BLE001 — a cleanup must never cost the row
        return text
