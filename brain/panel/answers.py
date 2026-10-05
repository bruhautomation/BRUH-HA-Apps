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
    "fix_failed",
    # A registry tidy-up brAIn can propose for review (`tidy.py`), and a
    # question the house book needs a person to answer (`house_book.py`).
    "tidy", "gap",
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
    # Names and rooms are what `tidy` proposes, so "Fix it" on these two is
    # the tidy run — a table to tick through — rather than a plan run that
    # would rename forty entities one tool call at a time.
    "reg.hardware_name": "tidy",
    "reg.no_area": "tidy",
}
# The house book files its gap questions under this source; their answer is
# typed, never a bare Yes.
HOUSE_BOOK_SOURCE = "house_book"
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
    if kind == "question" and case.get("source") == HOUSE_BOOK_SOURCE:
        return "gap"
    if kind == "question" or store == "hypotheses":
        return "question"
    # An opportunity is a PROPOSAL — a config brAIn wrote and Accept puts
    # into Home Assistant — only when it lives in that store. One the
    # Resident filed into the findings store has no config behind it, so
    # *Make the change* and *Try it for a week* were presses with nothing
    # to write or replay; it gets a finding's row instead (Fix it where
    # brAIn could, Add to list, Dismiss, Not a problem).
    if store == "proposals" or (kind == "opportunity" and store != "findings"):
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
        base = CHECK_SITUATIONS[check]
        # A tidy-up a person said needs their own hands is theirs.
        if base == "tidy" and not case.get("fixable"):
            base = "hands"
    elif check.startswith(AUTOMATION_PREFIX):
        base = "automation"
    else:
        base = "generic" if case.get("fixable") else "hands"
    # A fix run has already been here, and what it concluded decides the
    # first press more than the rule's own `fixable` does. `needs_you` is
    # the fixer saying a person has to do this — `fixable` is the row's
    # claim from before anybody looked, and leading with *Fix it* on it
    # bought another plan run to reach the same conclusion — so it is a
    # pair of hands, keeping the check's own situation (and the reason
    # its box opens with) where that already was one. `failed` is a run
    # that did not finish: trying again is a fair press, and it is behind
    # the ⋯ rather than leading, because the second attempt is the one
    # that should be read about first.
    if fstatus == "needs_you":
        return base if base in HANDS else "hands"
    if fstatus == "failed" and base not in HANDS:
        return "fix_failed"
    return base


# ---------------------------------------------------------------------------
# The answers
# ---------------------------------------------------------------------------

# The start of `plan_ops.LEGACY_PLAN`, the one refusal whose own remedy is
# to press Fix it again. Spelled here because this module is a leaf and may
# not import `plan_ops`; a test holds the two together.
LEGACY_PLAN_MARK = "this plan was written before brAIn checked"


def plan_refused(plan) -> bool:
    """Whether a plan run already concluded brAIn will not make this change.

    A plan on an open row is what a Cancel left behind, or a run that said
    "this needs you" or could not turn the fix into operations. Offering
    *Fix it* over it buys another plan run to reach the same sentence that
    is printed on the card — so the press goes, and the ⋯'s *Work out what
    to change* stays for somebody who thinks the house has moved since.
    A plan written before plans were operations is the exception: its own
    sentence says to press Fix it again.
    """
    if not isinstance(plan, dict) or not plan:
        return False
    if plan.get("can_fix") and plan.get("ops"):
        return False
    if not (plan.get("summary") or plan.get("steps") or plan.get("at")
            or plan.get("ops_refused") or plan.get("needs_you")):
        return False
    return not str(plan.get("ops_refused") or "").startswith(LEGACY_PLAN_MARK)


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


def _dismiss(case_id: str, question: bool = False) -> dict:
    """The snooze. Off the list for now, nothing settled, nothing taught,
    and brAIn picks when it comes back.

    A question says so in its own words, because what it does is
    different in one way that matters: a guess is not "still true or
    not", it is asked again — and while it is away it stops holding up
    the next one (`hypotheses.snooze`)."""
    if question:
        return _answer(
            "not_now", "Dismiss",
            "Not now. brAIn asks again in a week, and asks something else "
            "meanwhile — nothing is recorded either way.",
            route=f"/api/case/{case_id}/not_now", request="snooze",
            done="Asked again later")
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

    if sit == "gap":
        answer = _answer(
            "answer", "Answer", "Say where it is or what it does. It goes "
            "into memory, and the house book uses it next time.",
            route=f"/api/house_book/question/{key}/answer", primary=True,
            note=True, done="Filed into memory for the house book")
        answer["ask"] = ("Your answer goes into memory exactly as you write "
                         "it — never type a code or a password here.")
        answer["placeholder"] = "Behind the boiler, the red lever."
        return [answer, _dismiss(cid),
                _wrong(cid, label="Doesn't apply")]

    if sit == "tidy":
        return [_answer(
            "fix", "Fix it", "brAIn suggests names, rooms and aliases in "
            "this house's own style. Nothing changes until you tick them "
            "under House → Upkeep and press Apply.", route="/api/tidy/run",
            primary=True, done="Suggesting — review them under House → Upkeep"),
            _todo(cid), _dismiss(cid), _wrong(cid)]

    if sit == "question":
        return [
            _answer("yes", "Yes", "That's right. It becomes a plain fact "
                    "in memory.", route=f"/api/case/{cid}/do",
                    primary=True, done="Filed into memory"),
            # `request="wrong"`: a question the Resident filed is a finding
            # row, so Home Assistant's Repairs and a notification can carry
            # *No* back as the same correction the tab makes. They offered
            # only Dismiss before.
            _answer("no", "No", "Not right — say why if you can, and the "
                    "reason retires every guess built on the same "
                    "misreading.", route=f"/api/case/{cid}/wrong",
                    request="wrong", note=True, done="Noted"),
            # A guess in the hypothesis queue is asked again rather than
            # brought back, and says so; a question the Resident filed is
            # a finding row and is snoozed like one.
            _dismiss(cid, question=(case.get("origin") or {}).get("store")
                     == "hypotheses"),
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
    if (sit not in HANDS and sit != "fix_failed" and case.get("fixable")
            and not plan_refused(plan)):
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


__all__ = ["AUTOMATION_PREFIX", "CHECK_SITUATIONS", "HANDS",
           "LEGACY_PLAN_MARK", "MAX_VISIBLE", "PREFILL", "REQUEST_ACTIONS",
           "SITUATIONS", "answers", "more", "plan_refused",
           "request_answers", "situation"]
