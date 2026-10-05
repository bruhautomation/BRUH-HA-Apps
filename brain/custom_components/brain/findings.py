"""Make brAIn's findings visible inside Home Assistant.

The Findings tab is where brAIn reports what it thinks is broken — and the
tab is the problem: a critical finding discovered by the 3am scheduler was
completely silent until somebody happened to open the panel. The findings
store itself lives in the add-on's /data, which Home Assistant cannot see,
so the add-on republishes a compact mirror to /config/.brain on every
change and this module reads it:

  * a ``brain_finding`` event per NEW finding, so "brAIn found something"
    can trigger an automation, reach a phone, or land in the logbook next
    to the lights and doors
  * an "Open findings" sensor, so a dashboard (or a numeric_state trigger)
    can answer "how much is waiting on me" without the panel
  * a Repairs issue per finding that is a DECISION waiting on somebody,
    because Settings → Repairs is where Home Assistant puts the things
    that need a person, and it is read by people who never open the
    brAIn panel

Everything here is read-only over a file the add-on owns, same contract as
learning.py: nothing in this module writes findings. What the Repairs half
adds is not a write to the store — a press on one of its buttons drops a
*request* (``requests.write_request``), exactly as a tick in the To-do app
does, and the panel applies it through the tab's own endings.
"""

from __future__ import annotations

import json
import logging
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (DOMAIN, EVENT_FINDING, FINDINGS_STATE_FILENAME,
                    SHARED_DIR, TODO_STATE_FILENAME,
    EVENT_CASE, EVENT_CASE_ENDED, EVENT_CHANGE,
)

_LOGGER = logging.getLogger(__name__)

# The mirror carries the add-on's whole live list, which its store caps at
# 200 short rows (~200 KB at the very most, prose cut to 240 characters a
# field) — so this is room for that and a corrupted or hand-edited file
# still cannot stall the event loop.
MAX_STATE_BYTES = 1024 * 1024


def findings_state_path(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, FINDINGS_STATE_FILENAME)


def read_findings_state(hass: HomeAssistant) -> dict | None:
    """The add-on's published findings mirror, or None if it never wrote one.

    Shape: {ts, open, by_severity: {info/warning/serious/critical: n},
    findings: [{ts, text, severity, status, entity_id, fixable,
    source_title}, ...], snoozed: [same, + snoozed_until]} — newest first,
    live rows only. `snoozed` is the rows somebody pressed Dismiss on: still
    live, not asking until they come back, and kept apart so nothing that
    reads `findings` has to know about them. A mirror from an add-on that
    predates the key reads as none snoozed.
    """
    path = findings_state_path(hass)
    try:
        if os.path.getsize(path) > MAX_STATE_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rows = data.get("findings")
    data["findings"] = [f for f in rows if isinstance(f, dict) and f.get("text")] \
        if isinstance(rows, list) else []
    snoozed = data.get("snoozed")
    data["snoozed"] = [f for f in snoozed if isinstance(f, dict) and f.get("ts")] \
        if isinstance(snoozed, list) else []
    return data


def todo_state_path(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, TODO_STATE_FILENAME)


def read_todo_state(hass: HomeAssistant) -> dict | None:
    """The add-on's published to-do mirror, or None if it never wrote one.

    Shape: {generated_at, open, items: [{id, text, detail, fix, entity_id,
    severity, origin, source_title, added_at}, ...]} — open items only,
    worst first.

    It lives beside the findings reader because it is the same contract
    read twice — a file the add-on owns, never written here, stale rather
    than wrong when the add-on is stopped — and a second module for
    fifteen lines of that would be a second place for the rule to drift.
    """
    path = todo_state_path(hass)
    try:
        if os.path.getsize(path) > MAX_STATE_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rows = data.get("items")
    data["items"] = [i for i in rows if isinstance(i, dict) and i.get("text")] \
        if isinstance(rows, list) else []
    return data


# ---------------------------------------------------------------------------
# Findings as Repairs issues
# ---------------------------------------------------------------------------

# The statuses on the mirror that are a DECISION waiting on a person.
# `_publish_state` mirrors five of them (the add-on's LIVE_STATUSES) and
# these are the three a Repairs entry can honestly ask about: `fixing` is
# a repair brAIn is running right now, which is work in flight rather than
# a question, and `fixed` is news to READ — its one honest answer is the
# tab's "Got it", which is not one of the three verbs a request can carry,
# so a dialog offering "I've fixed it" over a row saying brAIn already did
# would be asking somebody to claim somebody else's work.
REPAIR_STATUSES = ("open", "needs_you", "failed")

# How loud each severity is in Home Assistant's own vocabulary. `info` is
# deliberately ABSENT rather than mapped to WARNING: Repairs is the list of
# things that need a person, and a row nobody has to act on teaches people
# to skim the page where the row that matters lives — the check catalog's
# own first rule (a check that fires on a healthy house is worse than no
# check), applied to a surface rather than to a rule. An `info` finding is
# still on the tab, still in the sensor, still an event; it raises no
# repair, because there is nothing to repair.
REPAIR_SEVERITY = {
    "critical": "ERROR",
    "serious": "ERROR",
    "warning": "WARNING",
}

# A cap, because Repairs is a page somebody works through and a house
# having a bad week must not be able to fill it — nine rows is a list and
# forty is a wall people stop opening, which costs the entries that were
# never brAIn's. OLDEST first, for two reasons: the row that has waited
# longest is the one at risk of never being looked at, and taking the
# newest instead would churn — every finding filed would evict one, so the
# set would be deleted and re-created under somebody's cursor.
MAX_REPAIR_ISSUES = 25

ISSUE_PREFIX = "finding_"

# Where an answer given in the Repairs dialog is remembered until the
# add-on has applied it. See `mark_answered`.
ANSWERED_KEY = "_findings_answered"


def issue_id_for(ts: int) -> str:
    """The Repairs issue id for a finding. Spelled in one place.

    `repairs.py` parses the same string back into a ts, so the two halves
    of the id are one function and one prefix rather than two literals a
    rename would split.
    """
    return f"{ISSUE_PREFIX}{int(ts)}"


def mark_answered(hass: HomeAssistant, ts: int) -> None:
    """Remember that somebody answered this finding from the Repairs page.

    A press writes a *request*; the add-on drains it within seconds and the
    row then leaves the mirror. Until it has, the row is still there — so
    the next poll would put the issue straight back, which reads as a
    dialog that reappears the moment you close it. The id is held only
    until its row is gone (`_forget_answered`), which is the add-on saying
    the answer landed, so this can neither grow forever nor go on
    suppressing a finding that is genuinely still open.
    """
    hass.data.setdefault(DOMAIN, {}).setdefault(ANSWERED_KEY, set()).add(int(ts))


def _answers(row: dict) -> tuple:
    """The wire actions the add-on says this row can be answered with,
    in the order it offers them — `[{action, label}]` on the mirror row,
    reduced to the action ids the Repairs flow has a step for. A mirror
    from an older add-on carries none, and an empty tuple means the flow
    falls back to its classic three."""
    out = []
    for item in row.get("answers") or []:
        action = str((item or {}).get("action") or "") if isinstance(item, dict) else ""
        if action and action not in out:
            out.append(action)
    return tuple(out)


def _placeholders(row: dict) -> tuple:
    """What the Repairs entry says about a finding, as a stable tuple.

    A tuple rather than a dict because it is compared against the last one
    raised, and re-raising an issue is a registry write plus an update
    signal — worth it when the sentence changed (a check refreshes its
    `detail` in place), worth nothing every sixty seconds otherwise.

    Every field falls back to a sentence rather than to an empty string: a
    dialog rendering "What you'd need to do:" with nothing after it reads
    as text that failed to load.
    """
    return (
        ("text", str(row.get("text") or "brAIn reported a problem")[:255]),
        ("detail", str(row.get("detail") or "").strip()
         or "brAIn gave no extra detail."),
        ("fix", str(row.get("fix") or "").strip()
         or "brAIn did not say how to fix this one."),
        ("source_title", str(row.get("source_title") or "").strip() or "brAIn"),
    )



def _rows(state: dict) -> tuple[dict[int, dict], dict[int, dict]]:
    """The mirror's live rows and its snoozed ones, each keyed by ts.

    A row in both is live: the add-on writes each row once, so that can only
    be a hand-edited file, and the reading that keeps a row asking is the
    one that cannot hide a problem.
    """
    current = {int(f.get("ts") or 0): f for f in state.get("findings") or []}
    snoozed = {int(f.get("ts") or 0): f for f in state.get("snoozed") or []
               if int(f.get("ts") or 0) not in current}
    return current, snoozed


def _case_payload(finding: dict) -> dict:
    """The case vocabulary, off a mirror row. One shape for all three events.

    `case_id` is the Home feed's own (`f:<ts>`), so a listener can match
    one event to another and to the panel's deep link; the `ts` half is the
    id the finding's answers take (a To-do tick, a notification button, a
    Repairs dialog). `kind` and `claim` are what the Resident wrote where it
    was the producer, and the finding's own text otherwise.
    """
    ts = int(finding.get("ts") or 0)
    return {
        "case_id": f"f:{ts}",
        "ts": ts,
        "kind": str(finding.get("kind") or "problem"),
        "claim": str(finding.get("claim") or finding.get("text") or ""),
        "finding": str(finding.get("text") or ""),
        "severity": str(finding.get("severity") or "warning"),
        "status": str(finding.get("status") or "open"),
        "entity_id": str(finding.get("entity_id") or ""),
        "fixable": bool(finding.get("fixable", True)),
        "source": str(finding.get("source_title") or ""),
        "name": "brAIn",
    }


class FindingsWatcher:
    """Fires a ``brain_finding`` event for each newly-reported finding, and
    keeps a Repairs issue for each one that is waiting on a person.

    The watermark is the set of finding ids (their ``ts`` — the id the panel
    acts on) already seen, primed from the file's current content at startup
    so a restart does not replay the whole open list onto the bus. The
    add-on's store dedupes across every status and the settled ledger, so an
    id that appears here is genuinely news.

    **The status snapshot is primed with it**, because the watermark is only
    half of what the events are diffed against: `brain_change` fires for a
    row whose status MOVED to `fixed`, and with nothing remembered about the
    statuses at startup every row already sitting in `fixed` — which stays
    live until somebody presses Got it — read as having just moved, so
    every restart and every reload announced "changed the house" again.

    **A snoozed row has not ended.** Dismiss takes a row out of `findings`
    and puts it in the mirror's `snoozed`, so the watcher keeps it in both
    the watermark and the snapshot: no `brain_case_ended` when it leaves,
    no `brain_case`/`brain_finding` when it comes back, and a real
    `brain_case_ended` if it is settled while it is away.

    **The issues are reconciled rather than diffed**, and that difference is
    exactly why they are NOT primed the way the events are: an event is
    news and an issue is state. Home Assistant drops a non-persistent issue
    when it restarts, so a row still waiting on somebody would silently
    lose its entry — the first poll after a boot is what has to put every
    one of them back. So every pass computes what the mirror says should
    exist and makes the registry match: created where missing, re-raised
    where the sentence changed, deleted where the ts has left the mirror or
    the person has answered it.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._seen: set[int] | None = None
        self._last: dict | None = None
        # ts -> the (severity, placeholders) last raised for it; see
        # `_placeholders` for why the comparison is worth keeping.
        self._issues: dict[int, tuple] = {}

    def prime(self) -> None:
        """Adopt the current list without announcing it.

        The event watermark AND the status snapshot are primed — the second
        is what stops a row already `fixed` re-firing `brain_change` on every
        restart (see the class docstring). The issue set deliberately is
        not: a restart clears non-persistent issues, so priming them would
        leave a house that rebooted with no Repairs entry for anything
        already open. A mirror that has never been written primes an empty
        roster — what the add-on files once it does is news, which on a
        fresh install it is.
        """
        state = read_findings_state(self.hass)
        current, snoozed = _rows(state or {})
        self._seen = set(current) | set(snoozed)
        self._last = {**snoozed, **current}

    async def async_poll(self, _now=None) -> None:
        state = await self.hass.async_add_executor_job(
            read_findings_state, self.hass)
        if state is None:
            return
        current, snoozed = _rows(state)
        self._announce(current, snoozed)
        # Reconciled on every pass, including the one that primes the
        # watermark: an issue is state, and the first poll after a restart
        # is what puts the page back. Snoozed rows raise none — Dismiss is
        # somebody saying "not now", and a Repairs entry is a "now".
        self.sync_issues(current)

    def _announce(self, current: dict[int, dict],
                  snoozed: dict[int, dict] | None = None) -> None:
        """One ``brain_finding`` event per finding nothing has announced."""
        snoozed = snoozed or {}
        if self._seen is None:
            self._seen = set(current) | set(snoozed)
            self._last = {**snoozed, **current}
            return
        fresh = [current[ts] for ts in sorted(current) if ts not in self._seen]
        # Ids leave the mirror when a finding is settled; forgetting them
        # here keeps the watermark from growing forever, and cannot re-fire
        # a settled finding because the add-on's settled ledger stops the
        # same problem ever re-entering the list. A row that moved to
        # `snoozed` has not left — it has been put off — so it is neither
        # gone now nor fresh when it returns.
        before = self._last if isinstance(self._last, dict) else {}
        gone = [before[ts] for ts in sorted(before)
                if ts not in current and ts not in snoozed]
        # A row whose status moved to `fixed` is brAIn having changed the
        # house — the one moment an automation may want to react to with
        # something other than a notification. A row that ARRIVES fixed
        # counts too: a fix can land between two polls.
        changed = [current[ts] for ts in sorted(current)
                   if str(current[ts].get("status") or "") == "fixed"
                   and str((before.get(ts) or {}).get("status") or "") != "fixed"]
        self._seen = set(current) | set(snoozed)
        # A snoozed row is remembered by its last LIVE shape where there is
        # one (the claim it was announced under), else by the mirror's.
        self._last = {**{ts: before.get(ts) or row for ts, row in snoozed.items()},
                      **current}
        for finding in gone:
            self.hass.bus.async_fire(EVENT_CASE_ENDED, {
                **_case_payload(finding),
                "message": f"closed: {finding.get('text')}",
            })
        for finding in changed:
            self.hass.bus.async_fire(EVENT_CHANGE, {
                **_case_payload(finding),
                "message": f"changed the house: {finding.get('text')}",
            })
        for finding in fresh:
            self.hass.bus.async_fire(EVENT_CASE, {
                **_case_payload(finding),
                "message": f"opened a case: {finding.get('text')}",
            })
            self.hass.bus.async_fire(EVENT_FINDING, {
                "ts": int(finding.get("ts") or 0),
                "finding": str(finding.get("text") or ""),
                "severity": str(finding.get("severity") or "warning"),
                "entity_id": str(finding.get("entity_id") or ""),
                "fixable": bool(finding.get("fixable", True)),
                "source": str(finding.get("source_title") or ""),
                # The logbook renders these verbatim, so it has to read as a
                # sentence rather than a field dump.
                "name": "brAIn",
                "message": f"found a problem: {finding.get('text')}",
            })

    # -- Repairs ------------------------------------------------------------

    def _answered(self) -> set:
        return self.hass.data.setdefault(DOMAIN, {}).setdefault(
            ANSWERED_KEY, set())

    def _wanted(self, current: dict[int, dict]) -> dict[int, tuple]:
        """Which findings deserve a Repairs entry, and what each would say.

        Oldest first, capped — see `MAX_REPAIR_ISSUES`. A row somebody has
        just answered in the dialog is left out until the add-on has
        drained the request and taken the row off the mirror.
        """
        answered = self._answered()
        wanted: dict[int, tuple] = {}
        # Urgent cards first (`urgent` on the mirror row — a leak, an
        # alarm, a freezing pipe): an Urgent card always raises a Repair,
        # so the cap is spent on them before the oldest of the rest, and
        # a week of warnings can never be what keeps one off the page.
        order = sorted(current, key=lambda t: (not current[t].get("urgent"), t))
        for ts in order:
            if ts in answered:
                continue
            row = current[ts]
            severity = REPAIR_SEVERITY.get(str(row.get("severity") or "warning"))
            if row.get("urgent") is True:
                severity = "CRITICAL"
            if severity is None:
                continue
            if str(row.get("status") or "open") not in REPAIR_STATUSES:
                continue
            wanted[ts] = (severity, _placeholders(row), _answers(row))
            if len(wanted) >= MAX_REPAIR_ISSUES:
                break
        return wanted

    def sync_issues(self, current: dict[int, dict]) -> None:
        """Make the issue registry agree with the mirror.

        Never raises: a Repairs page that could not be updated must not
        take the event watcher down with it — the events, the sensor and
        the to-do list are all still true without it.
        """
        try:
            self._sync(current)
        except Exception as exc:  # noqa: BLE001 — see the docstring
            _LOGGER.debug("could not sync the finding repairs: %s", exc)

    def _sync(self, current: dict[int, dict]) -> None:
        wanted = self._wanted(current)
        for ts in [t for t in self._issues if t not in wanted]:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id_for(ts))
            self._issues.pop(ts, None)
        for ts, spec in wanted.items():
            if self._issues.get(ts) == spec:
                continue
            severity, placeholders, answers = spec
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id_for(ts),
                is_fixable=True,
                # CRITICAL for an Urgent card; a core (or a stub) without
                # it gets ERROR, still the loudest it has.
                severity=getattr(ir.IssueSeverity, severity, None)
                or ir.IssueSeverity.ERROR,
                translation_key="finding",
                translation_placeholders=dict(placeholders),
                # What the fix flow is about, so it does not have to go
                # back to the mirror to name the finding it is ending.
                # ...and which answers the panel offers it, so the
                # dialog's menu is the card's row of buttons and not a
                # second, fixed list: a battery gets *Add to to-do*, a
                # change brAIn made gets *Got it*.
                data={"ts": int(ts), "text": placeholders[0][1],
                      "answers": list(answers)},
            )
            self._issues[ts] = spec
        self._forget_answered(current)

    def _forget_answered(self, current: dict[int, dict]) -> None:
        """Drop remembered answers whose row has left the mirror.

        That departure is the add-on saying the request was applied.
        Keeping them would be a set that grows for the life of the
        process and, worse, one that suppresses a finding that came back.
        """
        answered = self._answered()
        for ts in [t for t in answered if t not in current]:
            answered.discard(ts)

    def clear_issues(self) -> None:
        """Take every issue this watcher raised back down.

        Called when the entry unloads: a reload re-creates them on the
        first poll, and removing the integration should not leave brAIn's
        rows on somebody's Repairs page with nothing behind them.
        """
        for ts in list(self._issues):
            try:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id_for(ts))
            except Exception as exc:  # noqa: BLE001 — see `sync_issues`
                _LOGGER.debug("could not remove a finding repair: %s", exc)
        self._issues.clear()
