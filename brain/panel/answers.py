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

**Every problem card offers the same row, in the same order, and only the
first press on it is conditional.** *Fix it* where brAIn could make the
change itself (`fixable`, the row's own claim), then *Add to list*,
*Dismiss* and *Not a problem* — always those words, always that order,
so a row of buttons can be read without reading the words. The first cut
of this module gave each situation its own vocabulary (*Replaced it*,
*It's back*, *It's off on purpose*, *It's normal here*) on the theory
that a specific press teaches more, and what it taught was that the row
changed from card to card and had to be read every time: *"this all
feels really complicated"*. What a situation decides now is the
**reason** the *Not a problem* box offers ("It's unplugged or switched
off on purpose."), never the buttons.

**Dismiss is on every answerable card, and it is a snooze.** "I just
want to ignore this and you may bring it up later" is the commonest
answer to a card and it was behind the ⋯ as *Later*. It is the case's
own `not_now`: nothing is settled, nothing is taught, and brAIn picks
when it comes back — sooner the more it matters (`cases.SNOOZE_BY_STAKES`)
— which the toast and the card both say. *Not a problem* is the other
no, and they are different claims: one is "not this week", the other is
"you have this wrong", and only the second teaches and only the second
is for good.

**A press that needs hands is never led by a press that needs a run.**
`fixable` is the row's own claim about whose sentence the fix is, and a
card whose fix is *Replace the battery* leads with the to-do list, never
with a plan run: the run costs money to work out that a person has to
open a cover. Where brAIn could act, *Fix it* leads, and its first step
is still a read-only plan you consent to.

**Every answer names its route and its wire action**, so the panel does
not hold a second table of what a verb does, and the HA side can carry
the same press back as a request (`request` is `finding_requests`'
action name, or None for a press only the panel can make, like a plan
run whose progress has to be watched). *I've already fixed it*, *Check
again* and the rest sit behind the ⋯ (`cases.overflow`), because each is
right for one card in twenty and a row is what somebody reads on every
one.

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

# How many presses a card shows before the ⋯. Four: the fixed row is
# *Fix it · Add to list · Dismiss · Not a problem*, and on a phone it wraps
# to two rows of two rather than dropping the one press somebody wanted.
MAX_VISIBLE = 4

# The situations whose "Not a problem" box opens with a reason already in
# it — the commonest correction for that kind of row, offered so the press
# that fits is one tap and still edits. Every other situation opens empty.
PREFILL = {
    "unplugged": "It's unplugged or switched off on purpose.",
    "stuck": "That is normal for this sensor.",
}
# The situations on which brAIn is never offered as the one to fix it,
# whatever the row claims: each is a thing a person does with their hands,
# and a plan run that concludes "open the cover" is money spent to say so.
HANDS = ("battery", "unplugged", "stuck", "chore_check", "hands")


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


def _wrong(case_id: str, prefill: str = "", label: str = "Not a problem") -> dict:
    """The correction. It is `wrong` on every card, always opens the reason
    box (optional — the reason is the half that teaches), and settles the
    row for good."""
    return _answer(
        "wrong", label,
        "brAIn has this wrong, or it's normal here. It stops raising this. "
        "Say why if you like — it learns from the reason, not just the press.",
        route=f"/api/case/{case_id}/wrong", request="wrong", note=True,
        prefill=prefill, done="Noted — brAIn won't raise this again")


def _dismiss(case_id: str) -> dict:
    """The snooze. Off the list for now, nothing settled, nothing taught,
    and brAIn picks when it comes back."""
    return _answer(
        "not_now", "Dismiss",
        "Off the list for now. Nothing is recorded — brAIn brings it back "
        "later if it's still true, sooner the more it matters.",
        route=f"/api/case/{case_id}/not_now", request="snooze",
        done="Dismissed")


def _todo(case_id: str, primary: bool = False) -> dict:
    return _answer(
        "todo", "Add to list",
        "It's real and you'll get to it. Onto the To-do tab, and brAIn "
        "won't raise it again while it's there.",
        route=f"/api/case/{case_id}/do", request="todo", primary=primary,
        done="On your to-do list")


def _done(key, label: str = "Done", primary: bool = False) -> dict:
    return _answer(
        "done", label,
        "You've handled it yourself. brAIn records that and stops raising it.",
        route=f"/api/finding/{key}/done", request="fixed", primary=primary,
        done="Recorded")


def _fix(key) -> dict:
    return _answer(
        "fix", "Fix it",
        "brAIn works out exactly what it would change and shows you the "
        "steps. Nothing changes until you press Apply.",
        route=f"/api/finding/{key}/fix", primary=True,
        done="Working out what it would change — nothing has changed yet")


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
        out.append(_wrong(cid))
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
            _dismiss(cid),
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
        out.append(_dismiss(cid))
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
            _wrong(cid),
        ]

    # -- problems: one row, whatever the check --------------------------------
    # A chore check (empty the dishwasher, shut the back door) is the one
    # problem whose honest first press is "Done": the work is minutes and
    # putting it on a list is sillier than doing it. Everything else leads
    # with Fix it where brAIn could act and the list where it could not.
    if sit == "chore_check":
        return [_done(key, primary=True), _dismiss(cid), _wrong(cid)]
    out: list[dict] = []
    if sit not in HANDS and case.get("fixable"):
        out.append(_fix(key))
    out.append(_todo(cid, primary=not out))
    out.append(_dismiss(cid))
    out.append(_wrong(cid, prefill=PREFILL.get(sit, "")))
    return out[:MAX_VISIBLE]


def more(case: dict, visible: list[dict], overflow: list[dict]) -> list[dict]:
    """What goes behind the ⋯: the two presses of the fixed row a card
    does not show (*Add to list* on a chore check, *Dismiss* wherever the
    row leaves it off), then every rare verb the row has not already
    offered.

    `overflow` is `cases.overflow`'s list, unchanged — this only drops a
    verb that is already a visible button, so the same press is never
    offered twice under two names.
    """
    shown = {a["verb"] for a in visible}
    out: list[dict] = []
    sit = situation(case)
    cid = str(case.get("id") or "")
    if (visible and "todo" not in shown and case.get("kind") == "problem"
            and case.get("status") == "open"
            and sit not in ("planned", "change")):
        out.append(_todo(cid))
    if (visible and "not_now" not in shown
            and sit not in ("planned", "change", "chore_done", "watching")):
        out.append(_dismiss(cid))
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
    a request survive, and *Dismiss* rides at the end of any row that
    somehow left it off, because "not this minute" is the lock-screen
    answer.
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
        out.append({"action": "snooze", "label": "Dismiss"})
    return out


__all__ = ["AUTOMATION_PREFIX", "CHECK_SITUATIONS", "HANDS", "MAX_VISIBLE",
           "PREFILL", "REQUEST_ACTIONS", "SITUATIONS", "answers", "more",
           "request_answers", "situation"]
