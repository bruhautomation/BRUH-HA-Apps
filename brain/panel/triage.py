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

Four rules, and the first is the one the others serve.

**Silence surfaces.** Triage can only ever hold a row back by SAYING so,
about that row, in a reply that parsed. No credential, the budget spent,
the automatic switch off, the run failed, the reply unparseable, a row the
reply did not mention, more rows than one run may take, a pass that died
halfway — every one of those ends with the finding on the tab, marked
`untriaged`. "I could not look" and "it is not real" are different
claims and only the second may hide a problem, which is `clear_resolved`'s
rule moved one step earlier in the lifecycle.

**One run per pass, never one per finding.** The batch is capped and the
decision to spend anything at all is arithmetic taken before a process is
spawned — `curiosity.py`'s rule with less riding on it, because a pass
that filed nothing new is the ordinary case and it costs one list
comprehension.

**A held row is a row, not a deletion.** It stays in the store, which is
what makes the next pass's re-report dedupe against it rather than file
it again, and it clears exactly as an open row does when the check stops
reporting it. It is visible on its own filter, with the reason and the
conversation that reached it, and one press elevates it — a verdict
nothing can correct is a verdict nobody should trust, which is the
`unsettle` press one store over.

**Only a producer that has not looked is triaged.** A check has read one
snapshot and nothing else. An insight run, a study session and a
curiosity run each spent a Claude turn reading the house before they
filed anything, so triaging one is paying full price to ask a model to
grade its own answer a minute later.
"""
from __future__ import annotations

import json

# What a row can be in once something has (or has not) looked at it. The
# third is not a judgement — it is the record that nothing looked, which
# is why it surfaces like any untriaged finding and says so on the card.
VERDICTS = ("elevated", "held", "untriaged")

# The most rows one run may judge. Past this the surplus SURFACES rather
# than waiting for the next pass: waiting is silence, and silence is what
# this whole module exists to avoid being mistaken for a verdict. Ten is
# what one turn can read the house about without the reply becoming a
# list it skims.
MAX_BATCH = 10

# A run that reads history for ten entities is an insight run's shape, so
# it takes an insight run's budget.
TIMEOUT_S = 420
MAX_TURNS = 40

# A row left mid-triage by a panel that died. Anything older than this
# surfaces untriaged on the next pass — a guard that refuses has to change
# the next attempt, and a row nothing will ever judge is a problem nobody
# is ever shown.
STALE_S = 3600

# One sentence, shown on the card. Long enough to name what was looked at
# ("its history has 40 changes today — it is a doorbell button, not a
# stuck sensor"), short enough that ten of them are a list.
MAX_REASON = 300

# Every way a finding reaches the tab without anything having looked at
# it, in the words the card shows. They are here rather than at the seven
# call sites for the reason every closed vocabulary in this add-on is one
# table: these are the sentences that say "this card was NOT checked", and
# seven copies is seven chances for one of them to quietly stop saying it.
#
# Each one names what happened rather than apologising for it, because the
# person reading has to be able to tell an unchecked card from a checked
# one and then decide whether to believe it.
UNJUDGED = ("Nothing finished looking at this one, so it is on the list as "
            "the check filed it.")
TOO_MANY = ("More arrived at once than one look can cover, so this one is "
            "on the list unchecked.")
RUN_FAILED = ("The check on this one did not finish, so it is on the list "
              "as the rule filed it.")
NOT_MENTIONED = ("Nothing came back about this one, so it is on the list as "
                 "the check filed it.")
NO_CREDENTIAL = ("brAIn is not signed in, so nothing looked at this before "
                 "showing it.")
PAUSED = ("Automatic runs are paused, so nothing looked at this before "
          "showing it.")
NO_BUDGET = ("The usage budget is spent, so nothing looked at this before "
             "showing it.")

# The prompt asks for these two and nothing else; the reader accepts the
# imperative form of each beside it. See `parse`.
_SAME_WORD = {"hold": "held", "elevate": "elevated"}

_CHECK_PREFIX = "check:"


def needs_triage(source: str | None) -> bool:
    """True for a producer that filed without looking at anything.

    Deliberately a property of the SOURCE and not of the row: a producer
    is a line of code and a row is a sentence a rule or a model wrote, so
    keying this on the text would be keying it on the thing that gets
    reworded. Everything but a house check reached its finding through a
    Claude run that had already read the house.
    """
    return str(source or "").startswith(_CHECK_PREFIX)


def gate(rows: list[dict]) -> list[dict]:
    """The wire-shaped findings a pass is about to file, with the ones
    nothing has looked at marked as waiting for something to.

    One place decides this, so the store never has to know the policy and
    a second producer cannot file straight past it by accident.
    """
    out = []
    for row in rows:
        if isinstance(row, dict) and needs_triage(row.get("source")):
            out.append({**row, "status": "triaging"})
        else:
            out.append(row)
    return out


SYSTEM = """You are checking whether problems a smart home found are real.

A house check is one rule reading one instant. It cannot look anything up,
so it reports things that are true of the reading and wrong about the
house: a sensor that has not moved because it watches a cupboard nobody
opens, a temperature that is impossible for a room and ordinary for an
oven, a reading far from normal because the season changed.

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
rule thought it was. Say what you checked.

Never hold anything about safety, security, a battery that will die, a
device that has stopped answering, or data loss.

Reply with JSON and nothing else:

{"verdicts": [{"id": 1, "verdict": "elevated", "reason": "one sentence"},
              {"id": 2, "verdict": "held", "reason": "one sentence"}]}

Every id you were given must appear exactly once. `reason` is one plain
sentence naming what you looked at — it is shown to the homeowner."""


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
        parts.append("\n".join(bits))
    parts.append("\nReply with the JSON contract and nothing else.")
    return "\n".join(parts)


def parse(obj, count: int) -> dict[int, tuple[str, str]]:
    """`{1-based index: (verdict, reason)}` out of a reply.

    Anything this cannot read is simply absent, and an absent row
    surfaces — which is why nothing here raises and nothing here guesses.
    A verdict that is not one of the two words a run may give is dropped
    rather than coerced: an invented verdict reads exactly like a real
    one, and the safe reading is the one that shows the finding.
    """
    out: dict[int, tuple[str, str]] = {}
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
        out[idx] = (verdict, str(row.get("reason") or "").strip()[:MAX_REASON])
    return out


__all__ = [
    "MAX_BATCH", "MAX_REASON", "MAX_TURNS", "NOT_MENTIONED", "NO_BUDGET",
    "NO_CREDENTIAL", "PAUSED", "RUN_FAILED", "STALE_S", "SYSTEM",
    "TIMEOUT_S", "TOO_MANY", "UNJUDGED", "VERDICTS", "frame", "gate",
    "needs_triage", "parse",
]
