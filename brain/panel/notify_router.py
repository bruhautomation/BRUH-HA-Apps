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

**Most problems are not worth a phone at all.** Severity and urgency
between them say how loud a row should be, and for a long time there were
only two volumes: above the floor it was pushed once, below it nothing
happened. That put a dying battery and a freezing pipe through the same
door, so the floor was the only dial anybody had and turning it down to
hear about the pipe let everything else in behind it. There are three
tiers now (`tier_of`). **Escalate** is `critical` severity AND a producer
whose rows are `now` — a leak, a freeze, a hub that has stopped answering
— and it goes out immediately, quiet hours or not, and then *asks again*
on a ladder until somebody answers it. **Notify** is everything else
above the floor: exactly what happened before, once, held through the
night unless it is urgent. **Quiet** is below the floor, and quiet does
not mean lost — the row is on the Findings tab, in `todo.brain` and in
Home Assistant's own Repairs, all of which are places somebody looks
rather than places that interrupt.

**A reminder is only worth sending while the problem is still there.**
The ladder reads the findings store on every tick and never the ledger's
own copy: fixed, dismissed, snoozed, moved to the to-do list or cleared
by the check that filed it are five different endings and all of them
mean stop. And the ladder *ends* — three reminders, and the last one says
so, because a notification that will go on arriving for ever is one
people silence rather than answer.

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
    "check:sys.disk_space": "now",
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
    # Pipes. This is the one climate finding that is about the next few
    # hours rather than about the building, and the hours it fires in are
    # exactly the ones quiet hours would hold it through.
    "check:climate.freeze": "now",
    # A window open on a cold night is costing money for as long as it
    # stays open, and it is a thing somebody can go and close.
    "check:climate.window": "now",
    # Everything else here was measured over a month of nights and is
    # about the building: a room that has been two degrees short all
    # winter is not two degrees shorter at 3am, and a heating schedule
    # that starts late starts late again tomorrow.
    "check:climate.": "whenever",
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

# Where a still-open emergency's ladder lives. On disk, and written after
# every message, because backoff that lives only in memory is a promise a
# restart breaks — and a restart is the first thing anybody does when
# something is wrong. `usage-limits-tracker._resume_backoff`'s reason.
ESCALATION_FILE = os.environ.get("BRAIN_NOTIFY_ESCALATION",
                                 "/data/notify-escalation.json")

# The floor a fresh install ships with, read by the panel AND by run.sh's
# env fallback rather than spelled separately in each — a default that
# disagrees with itself is a second answer that wins exactly when nobody
# is looking (`${VAR:-default}`'s rule). `critical` rather than `serious`
# because the tiers below make the floor mean something different from
# what it used to: everything under it is still on the Findings tab, in
# `todo.brain` and in Repairs, and what the floor now governs is only
# whether a phone is interrupted. Somebody who wants the old behaviour
# sets it back to `serious`.
DEFAULT_MIN_SEVERITY = "critical"

# How loud a row is allowed to be. Ordered quietest first, the way
# URGENCY and `findings_store.SEVERITIES` are.
TIERS = ("quiet", "notify", "escalate")

# The ladder a still-open emergency climbs, as offsets **from the first
# message** rather than gaps between them. Offsets, because that is what
# survives a restart with no arithmetic: the rung is the number of
# reminders already sent, so a ledger read off disk lands on the same
# minute the process that wrote it would have. Three, and then it stops —
# a notification that will go on arriving for ever is one people silence
# rather than answer, which is the opposite of what a reminder is for.
ESCALATION_S = (60 * 60, 4 * 60 * 60, 12 * 60 * 60)
# A ledger past this is not an emergency, it is an outage, and fifty
# phones' worth of reminders about it helps nobody. The cap REFUSES the
# ladder rather than making room: the room would be made by dropping a
# row that has been escalating for hours, which is the one thing on the
# list most likely to still matter. The row is still announced — only the
# repeats are refused — and it is said out loud in the log.
ESCALATION_MAX_ROWS = 50
# One announcement plus every rung. The ladder already stops itself —
# `_next_at` answers 0 past the last rung — so this is a bound on what a
# file off disk can make the list grow to, not a second policy.
ESCALATION_SENDS_MAX = len(ESCALATION_S) + 1


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
        min_severity = DEFAULT_MIN_SEVERITY
    floor = findings_store.SEVERITIES.index(min_severity)
    out = []
    for f in findings or []:
        sev = str((f or {}).get("severity") or "warning")
        if sev not in findings_store.SEVERITIES:
            sev = "warning"
        if findings_store.SEVERITIES.index(sev) >= floor:
            out.append(f)
    return out


def tier_of(finding: dict, min_severity: str | None = None) -> str:
    """How loud this row is allowed to be: quiet, notify or escalate.

    The floor is applied FIRST, so nothing under it can escalate however
    urgent its producer is — that is the setting doing what it says, and
    it is also why a house that wants the old behaviour can reach it by
    moving one option rather than by learning a second rule.

    **Escalate is severity AND urgency, never either.** A `critical`
    battery forecast is three weeks out, and a `now` producer files
    plenty of rows that are merely a nuisance — it is the pair that
    describes a leak, a freeze, a hub that has stopped answering. The
    urgency half is `urgency_of`'s, which is declared per producer, so
    the set of rows that can wake a house is a set of lines of code
    rather than a set of sentences a model wrote.
    """
    sev = str((finding or {}).get("severity") or "warning")
    kept = worth_sending([finding or {}],
                         min_severity or DEFAULT_MIN_SEVERITY)
    if not kept:
        return "quiet"
    if sev == "critical" and urgency_of(finding) == "now":
        return "escalate"
    return "notify"


def classify(findings: list[dict],
             min_severity: str | None = None) -> dict[str, list[dict]]:
    """The batch split three ways, each list in the order it was filed.

    One pass and one answer, because a caller asking `tier_of` per row
    and re-grouping would be a second place the split is decided.
    """
    out: dict[str, list[dict]] = {name: [] for name in TIERS}
    for f in findings or []:
        out[tier_of(f, min_severity)].append(f)
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
        # A queue that could not be written is a finding that will never be
        # announced, and the only other symptom is a phone that stayed
        # quiet. Off the event loop: a report fetches the add-on log.
        _report_queue_failure(target, exc)


def _report_queue_failure(target: str, exc: BaseException) -> None:
    import threading  # noqa: PLC0415 — panel-local, and only on failure

    def run() -> None:
        import reports  # noqa: PLC0415 — deferred: reports imports nothing of ours
        reports.file_incident(
            "notify", "the notification hold queue could not be written",
            f"A finding held for the end of quiet hours could not be queued "
            f"at {target}, so it will not be announced when they end.\n"
            f"The error was: {exc}",
            "Check that /data is writable and not full; `brain doctor` "
            "reports the disk.",
            run={"source": "notify_queue", "outcome": "notify",
                 "error": str(exc)[:300]})

    threading.Thread(target=run, name="brain-reports-queue", daemon=True).start()


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
# The ladder
# ---------------------------------------------------------------------------

def _escalation_row(finding: dict, now: float) -> dict:
    """The least of an escalating finding that a reminder needs.

    `_row`'s rule: not a second copy of the store. `ts` is what the live
    store is read against on every tick and what `actions_for` puts on
    the buttons, and `first_at` is what the ladder's rungs are measured
    from — which is what makes a ledger read off disk land on the same
    minute the process that wrote it would have.
    """
    return {
        "ts": int(finding.get("ts") or 0),
        "text": str(finding.get("text") or "")[:200],
        "severity": str(finding.get("severity") or "critical"),
        "first_at": int(now),
        "sent_at": [int(now)],
        "next_at": _next_at(now, 1),
    }


def _next_at(first_at: float, sends: int) -> float:
    """When the next reminder is due, or 0 once the ladder has ended.

    Derived from the first message and the number of messages already
    sent rather than from the last one, so a stamp read off disk and a
    stamp computed here cannot disagree — and so a restart resumes the
    rung it was on instead of starting the ladder again.
    """
    rung = max(0, int(sends) - 1)
    if rung >= len(ESCALATION_S):
        return 0.0
    return float(first_at) + ESCALATION_S[rung]


def load_escalations(path: str | None = None) -> dict[int, dict]:
    """The ladder, keyed by the finding's ts. `{}` for anything unreadable."""
    try:
        with open(path or ESCALATION_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[int, dict] = {}
    for key, row in data.items():
        if not isinstance(row, dict):
            continue
        try:
            ts = int(key)
        except (TypeError, ValueError):
            continue
        sent = [s for s in row.get("sent_at") or [] if isinstance(s, (int, float))]
        if not sent:
            continue
        row = dict(row)
        row["ts"] = ts
        row["sent_at"] = [int(s) for s in sent]
        row["first_at"] = int(row.get("first_at") or sent[0])
        row["next_at"] = _next_at(row["first_at"], len(sent))
        out[ts] = row
    return out


def save_escalations(rows: dict[int, dict], path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or ESCALATION_FILE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(
            target, {str(ts): row for ts, row in rows.items()})
    except OSError as exc:
        # Losing this file costs repeats on a problem that is still on the
        # Findings tab, so it is a log line rather than a raised error —
        # but it is never silent, `save_queue`'s reason.
        log.warning("could not write the escalation ledger: %s", exc)


def begin_escalation(findings: list[dict], now: float,
                     path: str | None = None) -> int:
    """Start the ladder for rows that have just been announced.

    Idempotent on `ts`: a row already climbing keeps the rung it is on,
    because a second `add_many` that somehow re-offered it must not reset
    a ladder that is most of the way to its last reminder. Returns how
    many were added.
    """
    rows = load_escalations(path)
    added = 0
    for f in findings or []:
        row = _escalation_row(f, now)
        if not row["ts"] or row["ts"] in rows:
            continue
        if len(rows) >= ESCALATION_MAX_ROWS:
            log.warning(
                "not escalating %s: %d already on the ladder (the cap)",
                row["ts"], len(rows))
            break
        rows[row["ts"]] = row
        added += 1
    if added:
        save_escalations(rows, path)
    return added


def prune_escalations(live_ids: set[int], path: str | None = None) -> list[int]:
    """Forget every row that is no longer an open finding. Returns the ids.

    Fixed, dismissed, snoozed, moved to the to-do list, cleared by the
    check that filed it — five endings, and every one of them means stop.
    The caller reads the findings store for this on every tick and never
    the ledger's own copy, because the ledger cannot know.
    """
    rows = load_escalations(path)
    gone = [ts for ts in rows if ts not in live_ids]
    if gone:
        for ts in gone:
            rows.pop(ts, None)
        save_escalations(rows, path)
    return gone


def due_escalations(now: float, path: str | None = None) -> list[dict]:
    """The reminders that have come due, oldest ladder first."""
    rows = [r for r in load_escalations(path).values()
            if r.get("next_at") and float(r["next_at"]) <= now]
    rows.sort(key=lambda r: float(r.get("first_at") or 0))
    return rows


def record_reminder(ts: int, now: float,
                    path: str | None = None) -> dict | None:
    """Write down that a reminder went out, and when the next one is due.

    Written after every send, `usage-limits-tracker._resume_backoff`'s
    reason: a ladder that lived only in memory would start again from
    the first rung on the restart somebody performs precisely because
    their phone is going off.
    """
    rows = load_escalations(path)
    row = rows.get(int(ts))
    if row is None:
        return None
    row["sent_at"] = [*row.get("sent_at", []), int(now)][-ESCALATION_SENDS_MAX:]
    row["next_at"] = _next_at(row.get("first_at") or now, len(row["sent_at"]))
    save_escalations(rows, path)
    return row


def next_escalation_at(path: str | None = None) -> float:
    """The soonest reminder due, or 0 when nothing is climbing.

    The flush loop's wait reads this, because a ladder due in ten minutes
    must not wait out a nine-hour night.
    """
    due = [float(r["next_at"]) for r in load_escalations(path).values()
           if r.get("next_at")]
    return min(due) if due else 0.0


def escalation_state(path: str | None = None) -> dict:
    """What the ladder is holding, for `/api/diagnostics`.

    A queue nobody can see is a queue that silently swallows — the hold
    queue's rule, and it applies twice over here, because the failure
    this would hide is a house being reminded about nothing or not being
    reminded about a leak.
    """
    rows = load_escalations(path)
    # Named for the diagnostics block it is spread into rather than for
    # this function: a bare `next_at` beside the hold queue's own stamps
    # is a number nobody reading the payload could attribute.
    return {
        "escalating": len(rows),
        "escalation_next_at": int(next_escalation_at(path)),
        "escalation_reminders_sent": sum(
            max(0, len(r.get("sent_at") or []) - 1) for r in rows.values()),
        "escalation_since": min((int(r.get("first_at") or 0)
                                 for r in rows.values()), default=0),
    }


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


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def compose_escalation(row: dict, tz: dt.tzinfo | None = None) -> tuple[str, str]:
    """The message a reminder sends, and the one that says it is the last.

    **It says which repeat it is**, because the second copy of a sentence
    somebody has already read is otherwise indistinguishable from the
    notifier having sent it twice by mistake — and it says since when,
    which is the fact that makes a reminder worth reading rather than
    worth silencing.

    **And the last one says so.** A notification that will go on arriving
    for ever is one people turn off, which takes the next real emergency
    with it; saying where the ladder ends is what makes the ones before
    it safe to leave on. The finding does not go away — it is on the
    Findings tab, in `todo.brain` and in Repairs — so what stops is the
    asking rather than the problem.
    """
    sent = list(row.get("sent_at") or [])
    number = max(1, len(sent))
    last = number >= len(ESCALATION_S)
    when = dt.datetime.fromtimestamp(
        float(row.get("first_at") or 0), tz or dt.timezone.utc).strftime("%H:%M")
    title = "brAIn: still open"
    lines = [f"[{row.get('severity', 'critical')}] {row.get('text', '')}",
             "",
             f"Still open since {when} — {_ordinal(number)} reminder."]
    if last:
        lines.append("brAIn will not ask about this again; it stays on the "
                     "Findings tab.")
    return title, "\n".join(lines)[:MESSAGE_MAX]



# An accepted proposal is the one message here that is not about a
# finding, and it is `whenever` — nothing is wrong, nothing is waiting.
# It is nonetheless **sent rather than held**, and that is not the quiet
# window being ignored: this message answers a button somebody pressed
# seconds ago, so unlike every producer above it there is a person awake
# and looking by construction. What quiet hours protect against is an
# unattended producer, and this is the only sender that is not one.
ACCEPTED_URGENCY = "whenever"


def compose_accepted(title: str, entity_id: str) -> tuple[str, str]:
    """The one message an accepted proposal sends.

    Composed here rather than in the panel so both messages this module
    can send are written in one place — and deliberately NOT shaped like
    a finding, because a change you asked for arriving under "brAIn found
    a problem" is how a notification stops being read.
    """
    body = str(title or "a change you accepted").strip()[:MESSAGE_MAX]
    if entity_id:
        body = f"{body}\n\nIt is now {entity_id}."
    return "brAIn made a change you accepted", body[:MESSAGE_MAX]


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


def open_link(service: str, path: str | None) -> dict:
    """What tapping the notification opens: the panel, on the Findings tab.

    A notification about a finding used to land on Home Assistant's front
    page, with the row it was about three taps away and the person having
    to remember which add-on had sent it. The companion app takes a
    relative path under two names — `url` on iOS and `clickAction` on
    Android — and both are harmless on the other platform, so both are
    sent. Gated the way the buttons are (`can_answer`): only a
    `mobile_app_*` service reads these keys and means this by them, and a
    payload built on a guess about another notifier is how a working
    notification stops arriving. No path — the Supervisor has not said
    what this add-on's slug is — is no link, never a made-up one.
    """
    if not path or not can_answer(service):
        return {}
    return {"url": path, "clickAction": path}


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
    "ACCEPTED_URGENCY", "ACTION_LABELS", "ACTION_PREFIX",
    "DEFAULT_MIN_SEVERITY", "DEFAULT_URGENCY", "ESCALATION_FILE",
    "ESCALATION_MAX_ROWS", "ESCALATION_S", "PRODUCER_URGENCY", "QUEUE_FILE",
    "TIERS", "URGENCY", "actions_for", "begin_escalation", "can_answer",
    "classify", "compose", "compose_accepted", "compose_escalation",
    "due_escalations", "escalation_state", "hold", "in_quiet_hours",
    "load_escalations", "load_queue", "next_escalation_at", "parse_action",
    "parse_hour", "prune_escalations", "quiet_ends_at", "record_reminder",
    "save_escalations", "save_queue", "take_queue", "tier_of", "urgency_of",
    "worth_sending",
]
