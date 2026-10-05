"""How soon a finding wants to be read, and which rows are Urgent.

A leaf: it imports nothing of the panel's. `notify_router` decides what a
phone hears and `findings_store` publishes the HA mirror, and both need
this answer; when it lived in `notify_router` the two imported each other,
which is an import ring CodeQL rightly reports (a module whose answer can
depend on which neighbour was imported first). `notify_router` re-exports
every name here, so its callers are unchanged.
"""

from __future__ import annotations

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
    # A smoke, leak, CO or gas detector that has just tripped. Filed by the
    # deterministic safety lane (`server._safety_trip`) the moment the bus
    # admits the transition, with no model in the way — and `now` is what
    # lets it through quiet hours, which is the only hour a leak in a
    # bedroom ceiling is ever reported in.
    "safety": "now",
    # The tripwire (`security.py`): something tried to act on an entity
    # nothing should touch. That is now, whatever the hour.
    "security": "now",
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
    # An update waiting at 23:00 is the same update at 08:00, and
    # `check:sys.` as a family is `today` because the rest of it is a
    # disk filling up or an add-on that is down.
    "check:sys.update_pending": "whenever",
    # A trend, a forecast, a tidy-up. None of these change overnight.
    "check:forecast.": "whenever",
    "check:base.": "whenever",
    "check:reg.": "whenever",
    "check:auto.": "whenever",
    # Who can reach the house. A lock a cloud speaker can open is as true
    # at 08:00 as at 03:00, and a ban that already happened is history.
    "check:sec.": "whenever",
    # A question for the house book is never urgent — it is somebody being
    # asked where the stopcock is, which keeps until they are up.
    "house_book": "whenever",
}


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


def is_urgent(finding: dict) -> bool:
    """Whether this row is an Urgent card: the escalate pair, minus the floor.

    `tier_of`'s own test — `critical` AND (a `now` producer, or a case's
    `stakes: high`) — asked without the notify floor, because "urgent" is
    a fact about the row and the floor is a choice about a phone. It is
    what the Today queue sorts first and what raises a Repairs entry in
    Home Assistant whatever else is on that page, so a leak, an alarm or a
    freezing pipe is one rule wherever it is read.
    """
    if str((finding or {}).get("severity") or "") != "critical":
        return False
    return (urgency_of(finding) == "now"
            or str((finding or {}).get("stakes") or "") == "high")
