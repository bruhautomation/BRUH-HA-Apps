"""Has anything actually LOOKED at this before you are shown it.

A house check is a pure function over one snapshot. `dev.frozen` says a
sensor has not moved in a week, and it is right about the reading and
wrong about the house roughly as often as the house has a sensor meant to
sit still; `dev.implausible` said a working 3D printer was impossible;
`base.unusual` says a number is far from its own normal and cannot know
that the heating season started on Tuesday. Every floor in `checks/`
exists to answer that and none of them can finish the job, because a rule
reading one instant cannot go and look at anything.

So there is a step between filing and surfacing. Every producer files
through `gate`, which marks its rows `triaging`, and the Resident's first
look (`server._resident_pass`, `resident.parse_first_look`) is what
judges them: only a row a reply that parsed said `ignore` about is held,
and everything else surfaces. This module used to hold a judge of its
own — one Claude run per drain answering `elevated` or `held` — and it
was retired once the first look took its queue: nothing scheduled it, and
a second judge kept only for its own tests is a second vocabulary for one
decision. What is left is what both judges shared.

**Silence surfaces.** A row is only ever held back by a reply that SAID
so, about that row. A run that failed, a pass that died halfway, a row
nothing came back for — every one of those ends with the finding on the
tab, marked `untriaged`, carrying one of the sentences below. "I could
not look" and "it is not real" are different claims and only the second
may hide a problem, which is `clear_resolved`'s rule moved one step
earlier in the lifecycle.

**A held row is a row, not a deletion.** It stays in the store, which is
what makes the next pass's re-report dedupe against it rather than file
it again, and it clears exactly as an open row does when the check stops
reporting it. It is visible on its own filter, with the reason and the
conversation that reached it, and one press elevates it — a verdict
nothing can correct is a verdict nobody should trust.

**EVERY finding is gated, whoever filed it.** An insight run, a study
session and the fixer each read the house before they filed anything, but
none of them was asked whether what it noticed in passing belongs on a
list of decisions — and the small, obvious, technically-true rows are the
ones that make people stop reading a list. So `gate` marks every row and
a producer's name rides into the look as context rather than deciding.

**Waiting is honest because of the clock.** A gate that holds the batch
(no credential, paused, no budget) and a day that has spent its looks
both make rows wait rather than surface unjudged, because surfacing them
spends the cap on exactly the rows this exists to catch. `STALE_S` is
the promise that a row nothing ever came back for surfaces anyway.
"""
from __future__ import annotations

import time

# What a row can be in once something has (or has not) looked at it. The
# third is not a judgement — it is the record that nothing looked, which
# is why it surfaces like any untriaged finding and says so on the card.
VERDICTS = ("elevated", "held", "untriaged")

# A row left waiting by a panel that died, or by a look that has not run
# since. Anything older than this surfaces untriaged on the next pass — a
# guard that refuses has to change the next attempt, and a row nothing
# will ever judge is a problem nobody is ever shown. It is also what
# bounds the wait a held batch asks a queued row to accept.
STALE_S = 3600

# How long a row may wait for its first look before it is SHOWN anyway,
# still waiting. `STALE_S` is when a row stops waiting and surfaces as
# unjudged; this is the shorter promise that a row is never invisible for
# that whole hour. A look is due every ten minutes, so a row older than
# this is one a look has not reached — a gate holding the batch (a spent
# usage window, a pause, no credential) is the commonest reason — and a
# serious problem sitting unseen behind it while every count said
# "nothing waiting on you" is the failure this exists to end. It is shown
# and COUNTED (badge, sensor, Diagnostics) with `WAITING` on the card, and
# it stays `triaging`, so the look still judges it when it comes.
SHOW_AFTER_S = 15 * 60

# One sentence, shown on the card. Long enough to name what was looked at
# ("its history has 40 changes today — it is a doorbell button, not a
# stuck sensor"), short enough that ten of them are a list.
MAX_REASON = 300

# Which rules judged a row. 2 = judged on the CLAIM against all its own
# evidence (`resident.CLAIM_RULE`); a held verdict stamped 0 was given
# before that and gets one fresh look (`findings_store.migrate_folds`).
LOOK_VERSION = 2

# Every way a finding reaches the tab without anything having looked at
# it, in the words the card shows. They are here rather than at the call
# sites for the reason every closed vocabulary in this add-on is one
# table: these are the sentences that say "this card was NOT checked", and
# a copy per site is a chance for one of them to quietly stop saying it.
#
# Each one names what happened rather than apologising for it, because the
# person reading has to be able to tell an unchecked card from a checked
# one and then decide whether to believe it. None of them names the
# producer: every one of the five files through `gate` now, so a sentence
# about "the check" would be wrong about four of them.
UNJUDGED = ("Nothing finished looking at this one, so it is on the list as "
            "it was filed.")
WAITING = ("brAIn has not looked at this one yet, so it is shown as it was "
           "filed rather than left waiting out of sight.")
RUN_FAILED = ("The look at this one did not finish, so it is on the list "
              "as it was filed.")


def gate(rows: list[dict], muted: set[str] | None = None) -> list[dict]:
    """The wire-shaped findings a producer is about to file, every one of
    them marked as waiting for something to look at it — less the ones
    from a producer the homeowner has muted.

    One place decides this, so the store never has to know the policy and
    a second producer cannot file straight past it by accident. It is
    unconditional on purpose — see the third rule. It does not mutate
    what it is handed, because the same list goes on to `refresh_details`
    and `clear_resolved` in the same pass.

    **A muted producer's rows are dropped here and nowhere else.** "Stop
    raising these" is the press for a rule that is wrong about this house
    — the scorecard reading 0 confirmed against 6 marked Wrong — and Wrong
    one row at a time was the only answer it had, which is a key in the
    settled ledger per wording and the next pass making the same mistake
    in new words. Dropping the row at the door, rather than filing it and
    hiding it, is what keeps the mute out of `LIVE_STATUSES`, the mirror,
    the badge and every dedupe; the press itself clears what that producer
    already filed (`findings_store.clear_source`), and unmuting brings
    nothing back until the producer reports it again, `unsettle`'s rule.
    `muted` is read from the settings when not given, so every producer
    gets the same answer without each caller remembering to ask.
    """
    if muted is None:
        try:
            import settings_store
            muted = settings_store.muted()
        except Exception:  # noqa: BLE001 — a settings file that cannot
            # be read mutes nothing: the wrong direction here hides a card.
            muted = set()
    return [{**row, "status": "triaging"} if isinstance(row, dict) else row
            for row in rows
            if not (isinstance(row, dict) and muted
                    and str(row.get("source") or "") in muted)]


def waiting_too_long(row: dict, now: float | None = None) -> bool:
    """A row still `triaging` past `SHOW_AFTER_S` — shown and counted while
    it waits. Keyed on the raw store entry or the shaped row alike (both
    carry `status`, `ts` and `text`); a snoozed row is not waiting on
    anybody, which is the snooze's own rule."""
    if not isinstance(row, dict) or row.get("status") != "triaging":
        return False
    if not str(row.get("text") or "").strip():
        return False
    now = time.time() if now is None else float(now)
    if float(row.get("snoozed_until") or 0) > now:
        return False
    # From when it started WAITING, not when it was filed: a row sent back
    # to the look a fortnight after it was filed has not waited a fortnight.
    try:
        since = int(row.get("triaging_since") or 0)
    except (TypeError, ValueError):
        since = 0
    return (since or int(row.get("ts") or 0)) <= now - SHOW_AFTER_S


# The most first looks one day may spend. Nothing else bounded the look
# below the usage budget, and on a large house's first pass that is
# hundreds of runs in an hour. Past this the queue waits for tomorrow
# rather than surfacing unjudged — the batch cap's trade, one clock up.
# Counted per local day and reset with it (`server._triage_runs_today`).
MAX_PER_DAY = 200

# How many of those a HOT signal may spend by pulling a look forward. Hot
# cuts the ten-minute interval to one, which is right for a leak and is
# also what every change to a protected entity and every person moving at
# an odd hour is — so a busy house could spend the whole day's looks by
# mid-morning on the interval alone, and every row filed after that waited
# out `STALE_S` and was shown as if nothing had looked. Past this share a
# hot signal waits for the timer like any other, which keeps the rest of
# the day's looks for the timer and for the rows a rule filed; a TRIPPED
# safety sensor is the one hot signal the share never holds.
HOT_LOOKS_PER_DAY = 150

__all__ = [
    "HOT_LOOKS_PER_DAY", "MAX_PER_DAY", "MAX_REASON", "RUN_FAILED", "SHOW_AFTER_S", "STALE_S",
    "UNJUDGED", "VERDICTS", "WAITING", "gate", "waiting_too_long",
]
