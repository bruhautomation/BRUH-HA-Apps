"""What the household has said about a rule, read to the next look.

The scorecard (`findings_store.scorecard`) counts every ending a rule's
cards got, and a rule the household marks Wrong most of the time kept
filing, because the two things that could quiet it did not reach it:
`mute_offer` asks about a rule only past four endings and three quarters
Wrong, and is a question a person has to answer; `outcomes.candidates`
reads the Resident's own verdict log, which holds only rows a look judged
and labels only the ones it SURFACED, and then needs a model to write a
lesson that the first look meets only through the memory retrieval. A
rule at 2 right and 4 wrong reached neither.

So brAIn quiets such a rule by itself in the one way that changes no
floor: the first look is TOLD the rule's record beside the signals it
filed, and that a row from it is worth showing only with fresh, specific
evidence. A look that then answers `ignore` sets the row aside (History ›
Set aside by brAIn) instead of putting it in front of somebody; nothing
here mutes, settles or drops anything, and the never-ignore floors are
applied after the reply as they always are, so a record can never make a
safety, protected or hot signal worth less.

Never told about: anything that is not a house check, a security check
(`check:sec.*`), a check about harm (`signals.SAFETY_FLAG_CHECKS`), and
the producers that are not rules (`cases.UNMUTABLE_SOURCES`). Those sets
are restated here, because `reports.py` reads this module and must run
with the panel down; `tests/test_rule_record.py` holds them equal.

A leaf: the standard library only.
"""
from __future__ import annotations

# A record worth reading: at least this many Wrongs, and Wrong at least
# this share of the answers. The LATEST answer has to be a Wrong too — a
# rule somebody last agreed with has changed or been fixed since, the
# same rule `mute_offer` and `outcomes.candidates` keep.
MIN_WRONG = 2
WRONG_SHARE = 0.6

# `cases.UNMUTABLE_SOURCES`, restated.
UNMUTABLE_SOURCES = frozenset({"resident", "safety", "security",
                               "check:safety.tripped"})
# `signals.SAFETY_FLAG_CHECKS`, restated (check ids, no `check:`).
SAFETY_CHECKS = frozenset({"climate.freeze", "safety.tripped"})
# Security checks are never quieted, whatever their record.
NEVER_PREFIXES = ("check:sec.",)

MAX_LINES = 6


def quietable(source: str) -> bool:
    """Whether a producer is one brAIn may quiet by its record at all."""
    source = str(source or "")
    if not source.startswith("check:") or source in UNMUTABLE_SOURCES:
        return False
    if source.startswith(NEVER_PREFIXES):
        return False
    return source[len("check:"):] not in SAFETY_CHECKS


def qualifies(row: dict) -> bool:
    """A scorecard row lopsided enough to be read to the look."""
    if not isinstance(row, dict) or not quietable(row.get("source")):
        return False
    try:
        wrong = int(row.get("wrong") or 0)
        total = int(row.get("total") or 0)
    except (TypeError, ValueError):
        return False
    return (wrong >= MIN_WRONG and total > 0
            and wrong >= WRONG_SHARE * total
            and row.get("last") == "wrong")


def lopsided(scorecard) -> dict[str, dict]:
    """The qualifying rows of a scorecard, by source."""
    return {str(r["source"]): r for r in (scorecard or [])
            if isinstance(r, dict) and qualifies(r)}


def lines(batch, scorecard, floor=None) -> list[str]:
    """One line per lopsided rule with signals in this batch.

    Signals are named by their 1-based position, as the prompt numbers
    them. ``floor`` is `resident.never_ignore`: a signal it floors is left
    out, because a record is no argument about a signal the code will not
    let be ignored anyway, and saying it there would only invite a reply
    the floor then overrules.
    """
    rules = lopsided(scorecard)
    if not rules:
        return []
    found: dict[str, list[int]] = {}
    for i, sig in enumerate(batch or [], 1):
        if not isinstance(sig, dict):
            continue
        source = str(sig.get("source") or "")
        if source not in rules:
            continue
        if any(sig.get(flag) for flag in ("safety", "protected", "hot")):
            continue
        if floor is not None:
            try:
                if (floor(sig) or ("", ""))[0]:
                    continue
            except Exception:  # noqa: BLE001 — a floor that cannot be read
                continue      # is a floor: say nothing about the signal
        found.setdefault(source, []).append(i)
    out = []
    for source, idx in found.items():
        row = rules[source]
        title = str(row.get("title") or "").strip() or source
        which = ("Signal " + str(idx[0]) if len(idx) == 1 else
                 "Signals " + ", ".join(str(n) for n in idx[:-1])
                 + f" and {idx[-1]}")
        out.append(f"{which} came from the rule “{title}”: the household "
                   f"has marked {int(row['wrong'])} of its "
                   f"{int(row['total'])} answered reports wrong, the latest "
                   "included.")
    return out[:MAX_LINES]
