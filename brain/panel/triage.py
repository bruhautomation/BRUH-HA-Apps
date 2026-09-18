"""Has anything actually LOOKED at this before you are shown it.

A house check is a pure function over one snapshot. `dev.frozen` says a
sensor has not moved in a week, and it is right about the reading and
wrong about the house roughly as often as the house has a sensor meant to
sit still; `dev.implausible` said a working 3D printer was impossible;
`base.unusual` says a number is far from its own normal and cannot know
that the heating season started on Tuesday. Every floor in `checks/`
exists to answer that and none of them can finish the job, because a rule
reading one instant cannot go and look at anything. What that costs is
the thing this add-on is worst at: cards that are not real, on the one
list whose whole value is that its rows mean something.

So there is a step between filing and surfacing, and it is a Claude run
that CAN go and look — the entity's history, what else is in that area,
what the house has already been told. It answers one word per row,
**elevated** or **held**, with a sentence; only the first reaches the
tab, the badge, the notification and the analyst's prompt block.

Five rules, and the first is the one the others serve.

**Silence surfaces.** Triage can only ever hold a row back by SAYING so,
about that row, in a reply that parsed. No credential, the budget spent,
the automatic switch off, the run failed, the reply unparseable, a row the
reply did not mention, a pass that died halfway — every one of those ends
with the finding on the tab, marked `untriaged`. "I could not look" and
"it is not real" are different claims and only the second may hide a
problem, which is `clear_resolved`'s rule moved one step earlier in the
lifecycle.

**One run per drain, never one per finding.** The batch is capped and the
decision to spend anything at all is arithmetic taken before a process is
spawned — `curiosity.py`'s rule with less riding on it, because a drain
with nothing waiting is the ordinary case and it costs one read.

**A held row is a row, not a deletion.** It stays in the store, which is
what makes the next pass's re-report dedupe against it rather than file
it again, and it clears exactly as an open row does when the check stops
reporting it. It is visible on its own filter, with the reason and the
conversation that reached it, and one press elevates it — a verdict
nothing can correct is a verdict nobody should trust, which is the
`unsettle` press one store over.

**EVERY finding is triaged, and the first cut of this was wrong about
that.** What shipped gated on the source and triaged house checks alone,
on the argument that an insight run, a study session and the fixer had
each spent a Claude turn reading the house before they filed anything, so
grading one is paying full price to have a model mark its own homework.
The argument is about the wrong question. A run that read the house was
asked to write a card, or to study a topic, or to make a change; a
finding is the side channel it drops what it noticed into on the way
past, and **nothing anywhere asked it whether that was worth a person's
evening**. Reading the house and judging whether a row belongs on a list
of decisions are two different jobs, and only one of them had ever been
done. It is also backwards about which rows do the damage: the ones
people give up on a list over are the small ones, the obvious ones, the
ones that are technically true — which is exactly the set a model can
drop without being asked twice. So `gate` marks every row whoever filed
it, and what a producer's name still does here is ride into the prompt as
context rather than decide anything.

**The surplus WAITS, and the clock is what makes that honest.** `gate` is
applied by five producers and the drain is one run, so more can arrive at
once than one run may read. Surfacing the overflow unjudged — which is
what the first cut did — spends the cap on exactly the rows this exists
to catch, on the busiest houses first. Waiting is only silence if nothing
comes back for it, and something does: the drain runs on the scheduler's
own minute, and `STALE_S` is the promise that a row nothing ever came
back for surfaces anyway. The batch is taken **oldest first**, so a row
cannot lose the same lottery twice.
"""
from __future__ import annotations

import json

# What a row can be in once something has (or has not) looked at it. The
# third is not a judgement — it is the record that nothing looked, which
# is why it surfaces like any untriaged finding and says so on the card.
VERDICTS = ("elevated", "held", "untriaged")

# The most rows one run may judge. What does not fit waits for the next
# drain rather than surfacing unjudged — see the fifth rule. Ten is what
# one turn can read the house about without the reply becoming a list it
# skims.
MAX_BATCH = 10

# A run that reads history for ten entities is an insight run's shape, so
# it takes an insight run's budget.
TIMEOUT_S = 420
MAX_TURNS = 40

# A row left waiting by a panel that died, or by a drain that has not run
# since. Anything older than this surfaces untriaged on the next pass — a
# guard that refuses has to change the next attempt, and a row nothing
# will ever judge is a problem nobody is ever shown. It is also what
# bounds the wait the fifth rule asks a queued row to accept.
STALE_S = 3600

# One sentence, shown on the card. Long enough to name what was looked at
# ("its history has 40 changes today — it is a doorbell button, not a
# stuck sensor"), short enough that ten of them are a list.
MAX_REASON = 300

# Every way a finding reaches the tab without anything having looked at
# it, in the words the card shows. They are here rather than at the six
# call sites for the reason every closed vocabulary in this add-on is one
# table: these are the sentences that say "this card was NOT checked", and
# six copies is six chances for one of them to quietly stop saying it.
#
# Each one names what happened rather than apologising for it, because the
# person reading has to be able to tell an unchecked card from a checked
# one and then decide whether to believe it. None of them names the
# producer: every one of the five files through `gate` now, so a sentence
# about "the check" would be wrong about four of them.
UNJUDGED = ("Nothing finished looking at this one, so it is on the list as "
            "it was filed.")
RUN_FAILED = ("The look at this one did not finish, so it is on the list "
              "as it was filed.")
NOT_MENTIONED = ("Nothing came back about this one, so it is on the list as "
                 "it was filed.")
NO_CREDENTIAL = ("brAIn is not signed in, so nothing looked at this before "
                 "showing it.")
PAUSED = ("Automatic runs are paused, so nothing looked at this before "
          "showing it.")
NO_BUDGET = ("The usage budget is spent, so nothing looked at this before "
             "showing it.")

# The prompt asks for these two and nothing else; the reader accepts the
# imperative form of each beside it. See `parse`.
_SAME_WORD = {"hold": "held", "elevate": "elevated"}


def gate(rows: list[dict], muted: set[str] | None = None) -> list[dict]:
    """The wire-shaped findings a producer is about to file, every one of
    them marked as waiting for something to look at it — less the ones
    from a producer the homeowner has muted.

    One place decides this, so the store never has to know the policy and
    a second producer cannot file straight past it by accident. It is
    unconditional on purpose — see the fourth rule. It does not mutate
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


SYSTEM = """You are checking whether problems a smart home found are real.

Some of these came from a rule reading one instant of the house. It cannot
look anything up, so it reports things that are true of the reading and
wrong about the house: a sensor that has not moved because it watches a
cupboard nobody opens, a temperature that is impossible for a room and
ordinary for an oven, a reading far from normal because the season changed.

Others were mentioned in passing by a run that was doing something else —
writing a report, studying a topic, making a repair. That run read the
house, but nothing asked it whether what it noticed was worth putting in
front of a person, which is the question here.

Your job is to look — history, the area, what else the house says, what
the homeowner has told brAIn before — and decide, for each one, whether
it is worth putting in front of a person.

There are exactly two verdicts and they are spelled "elevated" and
"held". Nothing else is read.

"elevated" — the finding is real and there is something a person would
want to know or do about it. When in doubt, elevate: a real problem
nobody was shown is much worse than one card too many.

"held" — only when you have LOOKED and the finding is not a problem in
this house. Not because it is minor, not because it is old, not because
you would not have raised it — because you checked and it is not what the
one who raised it thought it was. Say what you checked.

Never hold anything about safety, security, a battery that will die, a
device that has stopped answering, or data loss.

For everything you elevate, also say what to DO about it — `fix`. Each
finding carries the generic advice the rule that raised it always gives
("check its power and its connection, then reload its integration"),
which is useless to somebody who wants to know what to do about THIS
device in THIS house. You have looked, so write what you found into the
answer: which integration it is on and whether the rest of that
integration is fine, whether the hub it pairs through is answering, which
automation to open and which condition to add, which other device is
already doing the job. Name the entity, the integration, the automation,
the setting — not a category. One or two sentences, in plain words to
the person who lives there, and never the generic advice restated. If
the generic advice really is right, say it in specifics. If the honest
answer is "there is nothing to do but wait", say that and why. A held
finding needs no `fix`.

Reply with JSON and nothing else:

{"verdicts": [{"id": 1, "verdict": "elevated", "reason": "one sentence",
               "fix": "what to do, specific to this house"},
              {"id": 2, "verdict": "held", "reason": "one sentence"}]}

Every id you were given must appear exactly once. `reason` is one plain
sentence naming what you looked at — it is shown to the homeowner, and so
is `fix`, under "What you'd need to do"."""

# The most a written fix may run to on the card. The store's own cap on
# the field, so a rewritten one cannot be longer than a filed one.
MAX_FIX = 600


def frame(rows: list[dict], house: str = "", memory: str = "") -> str:
    """The prompt for one batch. Rows are numbered, because a model
    retyping a finding's text back can name the wrong one and a number
    cannot be nearly right."""
    parts = ["Decide which of these are worth showing the homeowner.\n"]
    if memory.strip():
        parts.append("WHAT BRAIN KNOWS ABOUT THIS HOME:\n"
                     + memory.strip() + "\n")
    if house.strip():
        parts.append("WHAT BRAIN HAS MEASURED:\n" + house.strip() + "\n")
    parts.append("FINDINGS:")
    for i, row in enumerate(rows, 1):
        bits = [f"{i}. [{row.get('severity') or 'warning'}] {row.get('text') or ''}"]
        if row.get("detail"):
            bits.append(f"   detail: {row['detail']}")
        if row.get("entity_id"):
            bits.append(f"   entity: {row['entity_id']}")
        if row.get("source_title"):
            bits.append(f"   raised by: {row['source_title']}")
        # What the card will say under "What you'd need to do" unless the
        # run writes something better — shown so the run can see how
        # generic it is, and whether brAIn could make the change itself.
        if row.get("fix"):
            bits.append(f"   generic advice on the card now: {row['fix']}")
        bits.append("   brAIn can make this change itself: "
                    + ("yes" if row.get("fixable", True) is not False
                       else "no — it needs hands"))
        parts.append("\n".join(bits))
    parts.append("\nReply with the JSON contract and nothing else.")
    return "\n".join(parts)


def parse(obj, count: int) -> dict[int, tuple[str, str, str]]:
    """`{1-based index: (verdict, reason, fix)}` out of a reply.

    Anything this cannot read is simply absent, and an absent row
    surfaces — which is why nothing here raises and nothing here guesses.
    A verdict that is not one of the two words a run may give is dropped
    rather than coerced: an invented verdict reads exactly like a real
    one, and the safe reading is the one that shows the finding.

    `fix` is what the run says to do about an elevated row, written from
    what it looked at, and it replaces the generic sentence the rule
    filed. It is empty when the run wrote none — the card then keeps the
    generic one, which is the same card it showed before — and it is
    always empty on a held row, because a held row is shown to nobody.
    """
    out: dict[int, tuple[str, str, str]] = {}
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return out
    rows = obj.get("verdicts") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if not 1 <= idx <= count or idx in out:
            continue
        verdict = str(row.get("verdict") or "").strip().lower()
        # The two words, plus the two imperatives the same sentence could
        # reasonably come back as. This is not the coercion the docstring
        # refuses: a reply saying "hold" is the prompt's own verb in
        # another tense, where "probably fine" is a verdict nobody asked
        # for. Reading the first as silence would make a run that answered
        # correctly indistinguishable from one that failed — and silence
        # surfaces, so the cost is the feature doing nothing while looking
        # like it works. The table is named rather than a suffix trick,
        # because the next near-miss should have to be added on purpose.
        verdict = _SAME_WORD.get(verdict, verdict)
        if verdict not in ("elevated", "held"):
            continue
        fix = str(row.get("fix") or "").strip()[:MAX_FIX] \
            if verdict == "elevated" else ""
        out[idx] = (verdict, str(row.get("reason") or "").strip()[:MAX_REASON],
                    fix)
    return out


__all__ = [
    "MAX_BATCH", "MAX_FIX", "MAX_REASON", "MAX_TURNS", "NOT_MENTIONED", "NO_BUDGET",
    "NO_CREDENTIAL", "PAUSED", "RUN_FAILED", "STALE_S", "SYSTEM",
    "TIMEOUT_S", "UNJUDGED", "VERDICTS", "frame", "gate", "parse",
]
