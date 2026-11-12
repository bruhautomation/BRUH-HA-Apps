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

And a rule whose latest answers are three Wrongs in a row (`HOLD_STREAK`,
the scorecard's `streak`) is HELD BY DEFAULT (#698, #500, #501, #599):
`triage.gate` files its rows carrying `held_reason` (`record_hold`), the
look is told the streak, and a row no look keeps — the look let it go,
skipped it, failed or never came — is held with that record as its
reason (History › Set aside by brAIn) instead of being shown unjudged.
Fresh evidence is what brings one forward: a look that keeps it, its
report getting worse or naming something new
(`findings_store.refresh_details` sends a held row back to be looked at),
somebody putting it back, or the household agreeing with one of the
rule's reports, which ends the streak. Each Wrong was per entity or per
pair, so the next automation or the next forecast was news again; the
streak is the rule's own record. A critical row is never held, and
neither is anything `quietable` refuses.

Never told about: anything that is not a house check or a card a person
made (`user-…`, the household's own rule), a security check
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
                               "check:safety.tripped", "devloop_verify"})
# `signals.SAFETY_FLAG_CHECKS`, restated (check ids, no `check:`).
SAFETY_CHECKS = frozenset({"climate.freeze", "safety.tripped"})
# Security checks are never quieted, whatever their record.
NEVER_PREFIXES = ("check:sec.",)

MAX_LINES = 6

# Three Wrongs in a row, the latest answers, and the rule is held (above).
HOLD_STREAK = 3
# Or a record this one-sided, the latest answer a Wrong (#811, #812): a
# streak is ended by any agreement, so a rule Wrong four times in five with
# its one agreement among the latest answers was never held however often
# the household went on saying Wrong.
HOLD_WRONG = 3
HOLD_SHARE = 0.75
# A card somebody made is a rule they wrote (`user_categories.ID_PREFIX`).
PERSON_RULE_PREFIX = "user-"


def quietable(source: str) -> bool:
    """Whether a producer is one brAIn may quiet by its record at all."""
    source = str(source or "")
    if source.startswith(PERSON_RULE_PREFIX) and len(source) > len(
            PERSON_RULE_PREFIX):
        return True
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
    return holds(row) or (wrong >= MIN_WRONG and total > 0
                          and wrong >= WRONG_SHARE * total
                          and row.get("last") == "wrong")


def holds(row: dict) -> bool:
    """A scorecard row whose latest `HOLD_STREAK` answers were all Wrong,
    or which is Wrong at least `HOLD_WRONG` times and `HOLD_SHARE` of its
    answers with the latest a Wrong: its rule's rows are filed held
    (above)."""
    if not isinstance(row, dict) or not quietable(row.get("source")):
        return False
    try:
        if int(row.get("streak") or 0) >= HOLD_STREAK:
            return True
        wrong = int(row.get("wrong") or 0)
        total = int(row.get("total") or 0)
    except (TypeError, ValueError):
        return False
    return (wrong >= HOLD_WRONG and total > 0
            and wrong >= HOLD_SHARE * total and row.get("last") == "wrong")


def held_rules(scorecard) -> dict[str, dict]:
    """The rules held by their record, by source."""
    return {str(r["source"]): r for r in (scorecard or [])
            if isinstance(r, dict) and holds(r)}


def held_reason(row: dict) -> str:
    """The verdict a held row carries: the record, in the household's words,
    and what brings it back."""
    row = row or {}
    streak = int(row.get("streak") or 0)
    if streak >= HOLD_STREAK:
        said = f"You marked this rule's last {streak} reports wrong"
    else:
        # Held by its share (`holds`): a streak an agreement ended.
        said = (f"You marked {int(row.get('wrong') or 0)} of this rule's "
                f"{int(row.get('total') or 0)} reports wrong, the latest "
                "among them")
    return (said + ", so brAIn set this one aside. It comes back if it "
            "gets worse or names something new, or once you agree with one "
            "of this rule's reports.")


def never_held(row: dict, patterns: list[str] | None = None) -> bool:
    """A row no record holds back: critical, flagged as harm, from a check
    about harm, or about a protected entity.

    A check's row carries no `safety`/`protected`/`hot` flag — those live
    on the SIGNAL (`signals.make`), built later from the row — so a row
    read here is judged off what it does carry: its severity, its check
    and its entities. Protection is matched by the one matcher
    (`automation_writer.is_protected` over `protected_patterns`, the
    option parsed in one place), on the row's own entity and every item
    it names that is one; a list that cannot be read is read as
    protected, the direction that shows a card.
    """
    if not isinstance(row, dict):
        return True
    if str(row.get("severity") or "") == "critical":
        return True
    if any(row.get(flag) for flag in ("safety", "protected", "hot")):
        return True
    source = str(row.get("source") or "")
    if source.removeprefix("check:") in SAFETY_CHECKS:
        return True
    entities = [str(row.get("entity_id") or "")] + [
        str(x) for x in (row.get("items") or []) if isinstance(x, str)]
    entities = [e for e in entities if "." in e and " " not in e]
    if not entities:
        return False
    try:
        import automation_writer  # noqa: PLC0415 — a leaf's one matcher
        if patterns is None:
            patterns = automation_writer.protected_patterns()
        return any(automation_writer.is_protected(e, patterns)
                   for e in entities)
    except Exception:  # noqa: BLE001 — unreadable is not "nothing is
        # protected": the record holds nothing it cannot see.
        return True


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
        line = (f"{which} came from the rule “{title}”: the household "
                f"has marked {int(row['wrong'])} of its "
                f"{int(row['total'])} answered reports wrong, the latest "
                "included.")
        if holds(row):
            # Held by default (#698): only a look that keeps it shows it.
            line += (" The last "
                     + (f"{int(row['streak'])} in a row were wrong"
                        if int(row.get("streak") or 0) >= HOLD_STREAK
                        else "answer was wrong and so were most before it")
                     + ", so brAIn holds this rule's rows unless you keep "
                     "one for fresh, specific evidence the others did not "
                     "have.")
        out.append(line)
    return out[:MAX_LINES]
