"""Whether a finding reaches a phone, and when.

Before this there was a sender and no router: five callers — an insight
run, two sweeps, a checks pass and the startup sweep — each handed a list
of new findings straight to one notify service, and the entire policy was
two options, a service name and a severity floor. Three things follow
from that, and all three are what makes people turn a notifier off.

**Severity is how bad, not how soon.** A `critical` battery forecast is
three weeks out; a `warning` about a boiler that has stopped answering is
now. Ordering by badness and delivering everything immediately gets the
urgent ones through and wakes the house for the rest, so urgency is its
own axis here — declared per **producer**, never per row, because a
producer is a line of code and a row is a sentence a model wrote.

**Nothing knew what time it was.** `sys.disk_low` at 03:40 is a phone
lighting up a bedroom about something that will still be true at
breakfast, and the second time that happens the notification is gone for
good. Quiet hours are in the house's own timezone, from the same cache
`baselines` reads, and they fall back to UTC *and say which*.

**A quiet hour is a hold, not a silence.** Dropping what arrives at night
would be worse than sending it: the finding is on the list either way,
and a notifier that silently decides some problems are not worth
mentioning is one nobody can reason about. Held rows queue on disk and
leave together, in one message, when the quiet ends — and a row that was
settled or cleared while it waited is dropped from the queue rather than
announced, because telling somebody at 07:00 about a problem that went
away at 04:00 is worse than never mentioning it.

What is deliberately not here is coalescing across those five callers.
Each already hands over its whole batch at once, so a checks pass is one
message however many rows it filed; two callers landing together are two
genuinely different events, and a debounce holding the urgent ones back
to merge them would be machinery paying for a failure nobody can produce.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os

log = logging.getLogger("brain.notify")

QUEUE_FILE = os.environ.get("BRAIN_NOTIFY_QUEUE", "/data/notify-queue.json")

# How soon, as against how bad. Ordered least to most urgent so an index
# comparison works the way `findings_store.SEVERITIES` already does.
URGENCY = ("whenever", "today", "now")

# What each producer's rows are, by `source`. A prefix match on
# `check:<id>` so a check inherits its family's urgency and only the ones
# that differ are named. Anything unlisted is `today`, which is the
# honest default for a report a person has not seen yet: it goes out
# promptly while somebody is awake, and waits when they are not.
DEFAULT_URGENCY = "today"
PRODUCER_URGENCY = {
    # Something is happening in the house right now and waiting costs
    # something real.
    "check:dev.unavailable": "now",
    "check:dev.implausible": "now",
    "check:sys.addon_down": "now",
    "check:sys.disk_low": "now",
    # This one fires INSIDE quiet hours by construction — it only speaks
    # around the hour this house goes to bed, which is the hour the
    # window starts. Anything but `now` holds it until morning, which is
    # the one delivery that makes the check pointless.
    "check:evening.left_open": "now",
    # A chore is never urgent and often arrives in the evening: an
    # emptied dishwasher at eight in the morning is the same dishwasher.
    # `whenever` is what lets quiet hours hold it, which is the whole
    # reason urgency is declared per producer.
    "check:chore.waiting": "whenever",
    # A trend, a forecast, a tidy-up. None of these change overnight.
    "check:forecast.": "whenever",
    "check:base.": "whenever",
    "check:reg.": "whenever",
    "check:auto.": "whenever",
}

# A queue that has grown past this is a notifier nobody has read for
# days; the digest says how many rather than listing them.
QUEUE_MAX = 200
# How many rows a message names before it counts the rest.
LINES_MAX = 12
# HA's own notify payloads are not meant to be essays.
MESSAGE_MAX = 1500


# ---------------------------------------------------------------------------
# When it is
# ---------------------------------------------------------------------------

def parse_hour(text: str) -> int | None:
    """`"22"`, `"22:00"` or `"22:30"` as an hour, or None for unset.

    Minutes are read and deliberately discarded: quiet hours are a
    bedtime, the flush already coalesces, and an option that accepts
    22:30 and behaves as 22:00 is worse than one that says it takes an
    hour. The parse tolerates the shape people type anyway.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    head = raw.split(":", 1)[0].strip()
    try:
        hour = int(head)
    except (TypeError, ValueError):
        return None
    return hour if 0 <= hour <= 23 else None


def in_quiet_hours(now: float, start: int | None, end: int | None,
                   tz: dt.tzinfo | None = None) -> bool:
    """Whether local `now` is inside the quiet window.

    A window that crosses midnight (22 → 7) is the normal case and the
    one an ordinary `start <= h < end` gets backwards, so it is written
    out rather than assumed. `start == end` is not a 24-hour silence: it
    is somebody who has set the two the same by accident, and the honest
    reading of that is no quiet hours at all.
    """
    if start is None or end is None or start == end:
        return False
    hour = dt.datetime.fromtimestamp(now, tz or dt.timezone.utc).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def quiet_ends_at(now: float, end: int, tz: dt.tzinfo | None = None) -> float:
    """The next local moment the quiet window closes, as an epoch."""
    tz = tz or dt.timezone.utc
    local = dt.datetime.fromtimestamp(now, tz)
    target = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= local:
        target += dt.timedelta(days=1)
    return target.timestamp()


# ---------------------------------------------------------------------------
# How soon
# ---------------------------------------------------------------------------

def urgency_of(finding: dict) -> str:
    """How soon this producer's rows want to be read.

    Keyed on the producer rather than on the row, because a row's words
    are written by a model or by a check's f-string and would drift the
    first time either was reworded. A check that wants a different
    urgency from its family says so by name.
    """
    source = str((finding or {}).get("source") or "")
    if source in PRODUCER_URGENCY:
        return PRODUCER_URGENCY[source]
    for prefix, level in PRODUCER_URGENCY.items():
        if prefix.endswith(".") and source.startswith(prefix):
            return level
    return DEFAULT_URGENCY


def worth_sending(findings: list[dict], min_severity: str) -> list[dict]:
    """The rows above the severity floor, in the order they were filed."""
    import findings_store  # noqa: PLC0415 — panel-local

    if min_severity not in findings_store.SEVERITIES:
        min_severity = "serious"
    floor = findings_store.SEVERITIES.index(min_severity)
    out = []
    for f in findings or []:
        sev = str((f or {}).get("severity") or "warning")
        if sev not in findings_store.SEVERITIES:
            sev = "warning"
        if findings_store.SEVERITIES.index(sev) >= floor:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# The hold queue
# ---------------------------------------------------------------------------

def _row(finding: dict, now: float) -> dict:
    """The least of a finding that a digest needs. Not a second copy of it.

    `ts` is the id the store already has, and it is what lets a settled
    row be dropped from the queue before it is ever announced.
    """
    return {
        "ts": int(finding.get("ts") or 0),
        "text": str(finding.get("text") or "")[:200],
        "severity": str(finding.get("severity") or "warning"),
        "held_at": int(now),
    }


def load_queue(path: str | None = None) -> list[dict]:
    try:
        with open(path or QUEUE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def save_queue(rows: list[dict], path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or QUEUE_FILE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, rows[-QUEUE_MAX:])
    except OSError as exc:
        log.warning("could not write the notification queue: %s", exc)


def hold(findings: list[dict], now: float, path: str | None = None) -> int:
    """Queue rows for the end of the quiet window. Returns the queue depth.

    Deduped on `ts`, because the sweeps re-file and a person should not
    be handed the same sentence twice in one digest.
    """
    rows = load_queue(path)
    seen = {r.get("ts") for r in rows}
    for f in findings or []:
        row = _row(f, now)
        if row["ts"] in seen:
            continue
        seen.add(row["ts"])
        rows.append(row)
    save_queue(rows, path)
    return len(rows[-QUEUE_MAX:])


def take_queue(live_ids: set[int] | None = None,
               path: str | None = None) -> list[dict]:
    """Empty the queue, dropping anything that is no longer waiting.

    `live_ids` is what the findings store still holds open. A row settled
    or cleared while it waited is dropped rather than sent: announcing a
    problem at 07:00 that went away at 04:00 teaches somebody that these
    messages are not about anything. `None` means the store could not be
    read, and then everything is sent — an unreadable store is not
    evidence that a problem is over.
    """
    rows = load_queue(path)
    if not rows:
        return []
    save_queue([], path)
    if live_ids is None:
        return rows
    return [r for r in rows if int(r.get("ts") or 0) in live_ids]


# ---------------------------------------------------------------------------
# The message
# ---------------------------------------------------------------------------

def compose(rows: list[dict], held: bool = False) -> tuple[str, str]:
    """One title and one body for however many rows there are."""
    n = len(rows)
    if held:
        title = ("brAIn held a problem overnight" if n == 1
                 else f"brAIn held {n} problems overnight")
    else:
        title = ("brAIn found a problem" if n == 1
                 else f"brAIn found {n} problems")
    lines = [f"[{r.get('severity', 'warning')}] {r.get('text', '')}"
             for r in rows[:LINES_MAX]]
    if n > LINES_MAX:
        # Counted, never truncated: a list that stops mid-way reads as
        # the whole of what happened.
        lines.append(f"…and {n - LINES_MAX} more on the Findings tab.")
    return title, "\n".join(lines)[:MESSAGE_MAX]



# ---------------------------------------------------------------------------
# Buttons on the message
# ---------------------------------------------------------------------------

# The identifier the companion app hands back in
# `mobile_app_notification_action`. Prefixed so a house with other
# actionable notifications can tell whose button was pressed, and short
# because it travels in a payload with a length limit nobody documents.
ACTION_PREFIX = "brain"
ACTION_LABELS = (("fixed", "I've fixed it"), ("wrong", "Not a problem"),
                 ("snooze", "Later"))


def can_answer(service: str) -> bool:
    """Whether this notifier is one that can carry buttons back.

    Only the Home Assistant companion app. Every other notifier — a
    Telegram bot, a Discord webhook, `persistent_notification`, a group
    that fans out to several — takes `data` and means something different
    by it or nothing at all, and a payload built on a guess is how a
    working notification stops arriving. A missing button is a much
    smaller loss than that, so the gate is the one signal that is not a
    guess: the service is a `mobile_app_*` one.

    A notify GROUP containing mobile apps is deliberately not detected.
    It cannot be, from a name, and guessing wrong is the failure above.
    """
    name = str(service or "").strip().removeprefix("notify.")
    return name.startswith("mobile_app_")


def actions_for(rows: list[dict], service: str) -> list[dict]:
    """The buttons for this message, or none.

    **Only ever for a message about exactly one finding.** A digest is
    several problems in one notification, and a button on it would have
    to guess which — so a held batch and a checks pass that filed three
    arrive as they always did, and the person opens the tab. That is the
    honest answer rather than ending an arbitrary one of them.
    """
    if len(rows) != 1 or not can_answer(service):
        return []
    ts = rows[0].get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return []
    return [{"action": f"{ACTION_PREFIX}.{verb}.{int(ts)}", "title": title}
            for verb, title in ACTION_LABELS]


def parse_action(identifier: str) -> tuple[str, int] | None:
    """`"brain.fixed.1720"` as `("fixed", 1720)`, or None for anything else.

    The companion app fires one event for every actionable notification
    in the house, brAIn's and everybody else's, so this has to reject far
    more than it accepts.
    """
    parts = str(identifier or "").split(".")
    if len(parts) != 3 or parts[0] != ACTION_PREFIX:
        return None
    verb = parts[1]
    if verb not in [v for v, _t in ACTION_LABELS]:
        return None
    try:
        return verb, int(parts[2])
    except (TypeError, ValueError):
        return None


__all__ = [
    "ACTION_LABELS", "ACTION_PREFIX", "DEFAULT_URGENCY", "PRODUCER_URGENCY",
    "QUEUE_FILE", "URGENCY", "actions_for", "can_answer", "compose", "hold",
    "in_quiet_hours", "load_queue", "parse_action", "parse_hour",
    "quiet_ends_at", "save_queue", "take_queue", "urgency_of",
    "worth_sending",
]
