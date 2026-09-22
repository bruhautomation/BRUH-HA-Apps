"""Answers — which presses a case offers, decided once, for every surface.

The Home feed put the same three buttons under every card — *Do it*, *Not
now*, *Wrong, because…* — on the argument that thirteen verbs was a row
nobody could hold in their head. Three was the right number and the wrong
three: **a yes/no question wore a button called Do it**, a flat battery
that needs a person's hands led with a press that promised brAIn would do
something, the dismiss was sometimes the one control that had wrapped out
of sight, and the rare verbs behind the ⋯ included the one press that
actually fitted the card. That is the complaint, in the words it arrived
in: *"Yes/no questions have a 'do it' button. There are lots of buttons. I
don't always see a dismiss. Some items are boiled down to 'change the
batteries' but I'm getting a 'disable the integration' prompt."*

So the buttons are **derived from the case**, here, and rendered by every
surface that shows one: the feed, the shared-volume mirror that Home
Assistant's Repairs page and the notification buttons are built from. One
derivation, because a card on the panel offering *Add to to-do* while the
same finding's Repairs entry offered *I've fixed it* is the same finding
asking two different questions.

Four rules.

**A situation picks the answers, and a situation is a small closed
vocabulary** (`SITUATIONS`), read off the case's kind, its status, the
check that raised it and whether brAIn could act on it. A flat battery is
a `battery`; a device that has gone quiet is `unplugged`; a sensor stuck
on one value is `stuck`; an automation problem is `automation`; a plan
waiting for consent is `planned`. The table is named rather than derived
from the sentence on the row — a derivation over words is a name gate, the
failure `dev.implausible` documents — and a check nobody has classified
gets the honest generic set rather than a guess.

**At most three visible presses, and one of them is always a way to say
no.** The dismiss is the press people reach for most and the one they
reported not being able to find; it is never behind the ⋯ and never
absent from an answerable case. What the three are differs by situation
— *Add to to-do · Replaced it · Not a problem* on a battery, *Yes · No* on
a question, *Apply · Cancel* on a plan — but the shape is the same, so a
row of buttons can be read without reading the words.

**A press that needs hands is never led by a press that needs a run.**
`fixable` is the row's own claim about whose sentence the fix is, and a
card whose fix is *Replace the battery* leads with the to-do list, never
with a plan run: the run costs money to work out that a person has to
open a cover. Where brAIn could act, *Let brAIn fix it* leads, and its
first step is still a read-only plan you consent to.

**Every answer names its route and its wire action**, so the panel does
not hold a second table of what a verb does, and the HA side can carry
the same press back as a request (`request` is `finding_requests`'
action name, or None for a press only the panel can make, like a plan
run whose progress has to be watched).

Stdlib only, and it imports no store: `cases.py` and `findings_store.py`
both read it, and a module both of those import may import neither.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# The situations a case can be in, as the feed reads them. Every one
# maps to a set of answers below; a case with none of these is `generic`.
SITUATIONS = (
    "battery", "unplugged", "stuck", "chore_check", "automation",
    "generic", "hands", "planned", "planning", "fixing", "change",
    "question", "opportunity", "chore", "chore_done", "watching",
)

# Which check ids read as which situation. Keyed on the id and never on
# the sentence, for the reason given in the module docstring; a new check
# lands in `generic` until somebody adds it here on purpose.
CHECK_SITUATIONS = {
    "dev.battery_low": "battery",
    "forecast.battery": "battery",
    "dev.unavailable": "unplugged",
    "dev.zwave_dead": "unplugged",
    "dev.zha_unseen": "unplugged",
    "dev.frozen": "stuck",
    "dev.implausible": "stuck",
    "base.unusual": "stuck",
    "chore.waiting": "chore_check",
    "evening.left_open": "chore_check",
}
# Every `auto.*` check is an automation problem, whatever its id.
AUTOMATION_PREFIX = "auto."

# The wire actions Home Assistant can carry back as a request
# (`finding_requests.ACTIONS`, minus `reply`, which is a turn and not an
# ending). Spelled here as well because the mirror is built from this
# module and the integration reads the mirror.
REQUEST_ACTIONS = ("todo", "fixed", "wrong", "snooze", "ack")

# How many presses a card shows before the ⋯. Three is the row a thumb
# can tell apart; four is the row that wrapped the dismiss out of sight.
MAX_VISIBLE = 3


def _answer(verb: str, label: str, hint: str, *, route: str,
            request: str | None = None, primary: bool = False,
            note: bool = False, prefill: str = "", done: str = "",
            method: str = "POST") -> dict:
    """One press. `note` says the press opens the reason box first;
    `prefill` is the reason it offers when the situation already knows
    the commonest one (a device switched off on purpose)."""
    return {
        "verb": verb, "label": label, "hint": hint, "route": route,
        "method": method, "request": request, "primary": primary,
        "note": note, "prefill": prefill, "done": done or label,
    }


# ---------------------------------------------------------------------------
# The situation
# ---------------------------------------------------------------------------

def situation(case: dict) -> str:
    """Which of `SITUATIONS` this case is in.

    Reads the case as `cases.py` builds it: `kind`, `status` (the case's
    four words), `origin.store`, `source`, `fixable`, and — for a finding
    — `finding_status`, the store's own word, because `planned`, `fixing`
    and `planning` are three different screens and the case status folds
    two of them into `acting`.
    """
    kind = case.get("kind")
    status = case.get("status") or "open"
    store = (case.get("origin") or {}).get("store") or ""
    fstatus = case.get("finding_status") or ""

    if store == "todo":
        return "chore_done" if status == "done" else "chore"
    if kind == "question" or store == "hypotheses":
        return "question"
    if kind == "opportunity" or store == "proposals":
        return "opportunity"
    if kind == "change" or fstatus == "fixed":
        return "change"
    if fstatus == "planned":
        return "planned"
    if fstatus == "planning":
        return "planning"
    if fstatus == "fixing":
        return "fixing"
    if status == "watching":
        return "watching"

    source = str(case.get("source") or "")
    check = source[len("check:"):] if source.startswith("check:") else ""
    if check in CHECK_SITUATIONS:
        return CHECK_SITUATIONS[check]
    if check.startswith(AUTOMATION_PREFIX):
        return "automation"
    return "generic" if case.get("fixable") else "hands"


# ---------------------------------------------------------------------------
# The answers
# ---------------------------------------------------------------------------

def _finding_key(case: dict):
    return (case.get("origin") or {}).get("key")


def _dismiss(case_id: str, label: str = "Not a problem",
             hint: str = "", prefill: str = "") -> dict:
    """The one press every answerable case has. It is `wrong` under
    whatever name the situation gives it, and it always opens the reason
    box, because the reason is the half that teaches."""
    return _answer(
        "wrong", label,
        hint or "brAIn has this wrong, or it's normal here. Say why if you "
                "like — it learns from the reason, not just the press.",
        route=f"/api/case/{case_id}/wrong", request="wrong", note=True,
        prefill=prefill, done="Noted")


def _todo(case_id: str, label: str = "Add to to-do", primary: bool = True) -> dict:
    return _answer(
        "todo", label,
        "It's real and you'll get to it. Onto your to-do list, and brAIn "
        "won't raise it again while it's there.",
        route=f"/api/case/{case_id}/do", request="todo", primary=primary,
        done="On your to-do list")


def _done(key, label: str = "Already done", primary: bool = False) -> dict:
    return _answer(
        "done", label,
        "You've handled it yourself. brAIn records that and stops raising it.",
        route=f"/api/finding/{key}/done", request="fixed", primary=primary,
        done="Recorded")


def _fix(key, label: str = "Let brAIn fix it", primary: bool = True) -> dict:
    return _answer(
        "fix", label,
        "brAIn works out exactly what it would change and shows you the "
        "steps. Nothing changes until you press Apply.",
        route=f"/api/finding/{key}/fix", primary=primary,
        done="Working out what it would change — nothing has changed yet")


def _recheck(key, label: str = "Check again") -> dict:
    return _answer(
        "recheck", label,
        "Run the check that found this, now. If the problem has gone, the "
        "card goes with it.",
        route=f"/api/finding/{key}/recheck", done="Checked")


def _later(case_id: str) -> dict:
    return _answer(
        "not_now", "Later",
        "Take it off the list for a while. brAIn picks when it comes back "
        "and the card says when.",
        route=f"/api/case/{case_id}/not_now", request="snooze",
        done="Back later")


def answers(case: dict) -> list[dict]:
    """The visible presses for this case, in order, primary first.

    Empty for a case nothing can be pressed on — a run in flight — and
    the caller renders the phase line instead. Never more than
    `MAX_VISIBLE`, and every non-empty list carries a way to say no.
    """
    sit = situation(case)
    cid = str(case.get("id") or "")
    key = _finding_key(case)
    plan = case.get("plan") or {}

    if sit in ("planning", "fixing"):
        return []

    if sit == "planned":
        out = []
        if plan.get("can_fix"):
            out.append(_answer(
                "apply", "Apply", "Let brAIn make exactly these changes, "
                "then report back.", route=f"/api/finding/{key}/apply",
                primary=True, done="On it — brAIn is making the change"))
        # Leads only when there is no Apply: a plan brAIn refused to
        # carry out is a sentence to read and one press to close.
        out.append(_answer(
            "cancel", "Don't change it", "Leave the house as it is. The "
            "plan stays on the card so you can read it again for free.",
            route=f"/api/finding/{key}/cancel", primary=not out,
            done="Left alone — the plan is still here"))
        out.append(_dismiss(cid))
        return out[:MAX_VISIBLE]

    if sit == "change":
        out = [_answer(
            "ack", "Got it", "Clear it off the list — what brAIn changed "
            "is already in memory.", route=f"/api/case/{cid}/do",
            request="ack", primary=True, done="Cleared")]
        if case.get("fix_started") and case.get("fix_ended"):
            out.append(_answer(
                "unfix", "Undo the fix", "Put back every file brAIn changed "
                "and reload Home Assistant. Service calls it made are "
                "listed, not reversed.", route=f"/api/finding/{key}/unfix",
                done="Put back — read what it says"))
        return out

    if sit == "question":
        return [
            _answer("yes", "Yes", "That's right. It becomes a plain fact "
                    "in memory.", route=f"/api/case/{cid}/do",
                    primary=True, done="Filed into memory"),
            _answer("no", "No", "Not right — say why if you can, and the "
                    "reason retires every guess built on the same "
                    "misreading.", route=f"/api/case/{cid}/wrong",
                    note=True, done="Noted"),
        ]

    if sit == "opportunity":
        out = [_answer(
            "accept", "Make the change", "Write it into Home Assistant and "
            "reload. Undo takes it straight back out.",
            route=f"/api/case/{cid}/do", primary=True,
            done="Done — Undo puts it back")]
        if case.get("status") == "open":
            out.append(_answer(
                "trial", "Try it for a week", "Replay the last week and "
                "grade what it would have done against what you did.",
                route=f"/api/proposal/{key}/trial", done="Trial started"))
        out.append(_answer(
            "decline", "No thanks", "Not for this house. Say why if you "
            "like, and the reason reaches every future suggestion.",
            route=f"/api/case/{cid}/wrong", note=True, done="Noted"))
        return out[:MAX_VISIBLE]

    if sit == "chore":
        return [
            _answer("complete", "Done", "Tick it off. This is the moment "
                    "the fact goes into memory.", route=f"/api/case/{cid}/do",
                    primary=True, done="Done — written into memory"),
            _answer("drop", "Remove", "Take it off the list undone. brAIn "
                    "is free to find it again.", route=f"/api/case/{cid}/wrong",
                    done="Off the list"),
        ]

    if sit == "chore_done":
        return [_answer("reopen", "Put it back", "Back onto the list, "
                        "undone.", route=f"/api/todo/{key}/reopen",
                        primary=True, done="Back on the list")]

    if sit == "watching":
        return [
            _answer("elevate", "Show it anyway", "brAIn looked and decided "
                    "not to bother you. This puts it on the list as the "
                    "check filed it.", route=f"/api/finding/{key}/elevate",
                    primary=True, done="On the list"),
            _dismiss(cid),
        ]

    # -- problems ----------------------------------------------------------
    if sit == "battery":
        return [_todo(cid),
                _done(key, "Replaced it"),
                _dismiss(cid)]
    if sit == "unplugged":
        return [_todo(cid),
                _recheck(key, "It's back"),
                _dismiss(cid, "It's off on purpose",
                         "It is unplugged, switched off or put away on "
                         "purpose. brAIn stops reporting this device.",
                         prefill="It's unplugged or switched off on purpose.")]
    if sit == "stuck":
        return [_todo(cid),
                _recheck(key),
                _dismiss(cid, "It's normal here",
                         "That reading is what this sensor does. brAIn "
                         "stops raising this rule for it.",
                         prefill="That is normal for this sensor.")]
    if sit == "chore_check":
        return [_done(key, "Done", primary=True),
                _later(cid),
                _dismiss(cid)]
    if sit == "automation":
        if case.get("fixable"):
            return [_fix(key), _todo(cid, primary=False), _dismiss(cid)]
        return [_todo(cid), _done(key), _dismiss(cid)]
    if sit == "generic":
        return [_fix(key), _todo(cid, primary=False), _dismiss(cid)]
    # hands: a fix a person has to make.
    return [_todo(cid), _done(key), _dismiss(cid)]


def more(case: dict, visible: list[dict], overflow: list[dict]) -> list[dict]:
    """What goes behind the ⋯: *Later* where it is not already on the row,
    then every rare verb the row has not already offered.

    `overflow` is `cases.overflow`'s list, unchanged — this only drops a
    verb that is already a visible button, so the same press is never
    offered twice under two names.
    """
    shown = {a["verb"] for a in visible}
    out: list[dict] = []
    sit = situation(case)
    if (visible and "not_now" not in shown
            and sit not in ("planned", "change", "chore_done", "watching")):
        out.append(_later(str(case.get("id") or "")))
    for item in overflow or []:
        if item.get("verb") in shown:
            continue
        out.append(item)
    return out


def request_answers(row: dict) -> list[dict]:
    """The answers a FINDING row can be given from outside the panel, as
    `[{action, label}]` — what the mirror carries and what Repairs and a
    notification render.

    Built from a bare store row rather than a case, because the mirror is
    written by the store and the store cannot import `cases`. The
    situation is read the same way; only the presses HA can carry back as
    a request survive, and *Later* rides at the end for every row that
    has a to-do or a dismiss on it, because "not this minute" is the
    lock-screen answer even when the panel keeps it behind the ⋯.
    """
    case = {
        "id": f"f:{int(row.get('ts') or 0)}",
        "kind": "change" if row.get("status") == "fixed" else (
            row.get("kind") or "problem"),
        "status": "open",
        "finding_status": row.get("status") or "open",
        "origin": {"store": "findings", "key": int(row.get("ts") or 0)},
        "source": row.get("source") or "",
        "fixable": row.get("fixable", True) is not False,
        "plan": row.get("plan") or {},
    }
    if case["finding_status"] in ("planning", "fixing"):
        return []
    out = [{"action": a["request"], "label": a["label"]}
           for a in answers(case) if a.get("request")]
    actions = {a["action"] for a in out}
    if out and "snooze" not in actions and case["kind"] != "change":
        out.append({"action": "snooze", "label": "Later"})
    return out


__all__ = ["AUTOMATION_PREFIX", "CHECK_SITUATIONS", "MAX_VISIBLE",
           "REQUEST_ACTIONS", "SITUATIONS", "answers", "more",
           "request_answers", "situation"]
