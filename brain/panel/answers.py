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

**Every card has one primary, then Snooze · Ignore, always those words
and that order** (docs/design/ui-redesign-2026-10.md, "One queue, one
card"), so a row of buttons can be read without reading the words. The
primary is the one press that fits the card: *Plan* where brAIn could
work out a change (a read-only run that changes nothing), *Apply* once a
plan is on the card, *Add to list* where it needs a person's hands, *Done*
on a chore check, *Send* on a house-book question. Everything rarer —
*Ask*, *Recheck*, *Done*, *Plan* — is behind the ⋯, at most three. The
first cut of this module gave each situation its own vocabulary
(*Replaced it*, *It's back*, *It's off on purpose*) and what it taught
was that the row changed from card to card and had to be read every
time: *"this all feels really complicated"*. What a situation decides
now is the **reason** the Ignore box offers ("It's unplugged or switched
off on purpose."), never the buttons.

**Snooze is on every answerable card, and it is a snooze.** "I just
want to ignore this and you may bring it up later" is the commonest
answer to a card. It is the case's own `not_now`: nothing is settled,
nothing is taught, and brAIn picks when it comes back — sooner the more
it matters (`cases.SNOOZE_BY_STAKES`) — which the toast and History both
say. *Ignore* is the other no, and they are different claims: one is
"not this week", the other is "never raise this again", and only the
second teaches and only the second is for good.

**A press that needs hands is never led by a press that needs a run.**
`fixable` is the row's own claim about whose sentence the fix is, and a
card whose fix is *Replace the battery* leads with the to-do list, never
with a plan run: the run costs money to work out that a person has to
open a cover. Where brAIn could act, *Plan* leads, and what it drafts
is applied only by the *Apply* you press on the plan.

**Every answer names its route and its wire action**, so the panel does
not hold a second table of what a verb does, and the HA side can carry
the same press back as a request (`request` is `finding_requests`'
action name, or None for a press only the panel can make, like a plan
run whose progress has to be watched). *Done*, *Recheck* and *Ask* sit
behind the ⋯ (`more`), because each is right for one card in twenty and
a row is what somebody reads on every one. The wire actions never change
with a label: Home Assistant's Repairs and the notification buttons key
on them.

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

# How many presses a card shows before the ⋯. Three: one primary, then
# *Snooze · Ignore* (docs/design/ui-redesign-2026-10.md, "One queue, one
# card"). It was four while the row also carried *Add to list* beside
# *Fix it*, and a fourth button is the one a phone wraps out of sight.
MAX_VISIBLE = 3

# The situations whose Ignore box opens with a reason already in
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


def plan_is_legacy(plan) -> bool:
    """A plan written before plans were operations: nothing in it can be
    approved, and its remedy is to plan again (`plan_ops.LEGACY_PLAN`)."""
    return isinstance(plan, dict) and str(
        plan.get("ops_refused") or "").startswith(LEGACY_PLAN_MARK)


# What a card's ⋯ may hold at most. The design doc's own number: a menu
# longer than three is a second button row nobody reads.
MAX_MORE = 3


def _wrong(case_id: str, prefill: str = "", label: str = "Ignore",
           hint: str = "") -> dict:
    """The correction. It is `wrong` on every card, always opens the reason
    box (optional — the reason is the half that teaches), and settles the
    row for good. Called **Ignore**: "never raise this again" is what the
    press does, whatever brought somebody to it."""
    return _answer(
        "wrong", label,
        hint or "Never raise this again. Say why if you like — brAIn learns "
        "from the reason, not just the press.",
        route=f"/api/case/{case_id}/wrong", request="wrong", note=True,
        prefill=prefill, done="Ignored — brAIn won't raise this again")


def _dismiss(case_id: str, question: bool = False) -> dict:
    """The snooze. Off the list for now, nothing settled, nothing taught,
    and brAIn picks when it comes back.

    A question says so in its own words, because what it does is
    different in one way that matters: a guess is not "still true or
    not", it is asked again — and while it is away it stops holding up
    the next one (`hypotheses.snooze`)."""
    if question:
        return _answer(
            "not_now", "Snooze",
            "Hide it for now. brAIn asks again later, and asks something "
            "else meanwhile — nothing is recorded either way.",
            route=f"/api/case/{case_id}/not_now", request="snooze",
            done="Snoozed")
    return _answer(
        "not_now", "Snooze",
        "Hide it for now. Nothing is recorded — it comes back later if it's "
        "still true, sooner the more it matters.",
        route=f"/api/case/{case_id}/not_now", request="snooze",
        done="Snoozed")


def _todo(case_id: str, primary: bool = False) -> dict:
    return _answer(
        "todo", "Add to list",
        "You'll handle it. It goes on Your list, and brAIn won't raise it "
        "again while it's there.",
        route=f"/api/case/{case_id}/do", request="todo", primary=primary,
        done="On your list")


def _done(key, primary: bool = False) -> dict:
    return _answer(
        "done", "Done",
        "It's handled. brAIn records that and stops raising it.",
        route=f"/api/finding/{key}/done", request="fixed", primary=primary,
        done="Done — recorded")


def _plan(key, primary: bool = False) -> dict:
    """The read-only plan run. Called **Plan** and never Apply: it changes
    nothing, and Apply is the press that consents to what it drafts."""
    return _answer(
        "fix", "Plan",
        "brAIn drafts exactly what it would change and shows you first. "
        "Nothing changes until you press Apply.",
        route=f"/api/finding/{key}/fix", primary=primary,
        done="Planning — nothing has changed yet")


def _ask(key) -> dict:
    return _answer(
        "discuss", "Ask",
        "Talk it through with brAIn, in a chat about this card. Any change "
        "it suggests still asks you first.",
        route=f"/api/finding/{key}/discuss", done="Opened a chat about it")


def _recheck(key) -> dict:
    return _answer(
        "recheck", "Recheck", "Run the check that found this again, now.",
        route=f"/api/finding/{key}/recheck", done="Checked again")


def answers(case: dict) -> list[dict]:
    """The visible presses for this case, in order, primary first.

    One primary, then the **Snooze · Ignore** pair wherever a card can be
    put off or waved away — always those words, always that order, so a
    row can be read without reading the words. Empty for a case nothing
    can be pressed on — a run in flight — and the caller renders the
    phase line instead. Never more than `MAX_VISIBLE`.
    """
    sit = situation(case)
    cid = str(case.get("id") or "")
    key = _finding_key(case)
    plan = case.get("plan") or {}

    if sit in ("planning", "fixing"):
        return []

    if sit == "planned":
        if plan.get("can_fix") and not plan_is_legacy(plan):
            lead = _answer(
                "apply", "Apply", "brAIn makes exactly these changes now, "
                "then reports back. Undo puts them back.",
                route=f"/api/finding/{key}/apply", primary=True,
                done="Applying — brAIn is making the change")
        elif plan_is_legacy(plan):
            # "This plan is out of date." The remedy is to plan again.
            lead = _plan(key, primary=True)
        else:
            # brAIn will not make this change: a person's hands.
            lead = _todo(cid, primary=True)
        return [lead, _dismiss(cid), _wrong(cid)]

    if sit == "change":
        out = [_answer(
            "ack", "Done", "Clear it off the list — what brAIn changed is "
            "already in memory.", route=f"/api/case/{cid}/do",
            request="ack", primary=True, done="Done")]
        if case.get("fix_started") and case.get("fix_ended"):
            out.append(_answer(
                "unfix", "Undo", "Put back every file brAIn changed and "
                "reload Home Assistant. Service calls it made are listed, "
                "not reversed.", route=f"/api/finding/{key}/unfix",
                done="Put back — read what it says"))
        return out

    if sit == "gap":
        answer = _answer(
            "answer", "Send", "Say where it is or what it does. It goes "
            "into memory, and the house book uses it next time.",
            route=f"/api/house_book/question/{key}/answer", primary=True,
            note=True, done="Filed into memory for the house book")
        answer["ask"] = ("Your answer goes into memory exactly as you write "
                         "it — never type a code or a password here.")
        answer["placeholder"] = "Behind the boiler, the red lever."
        return [answer, _dismiss(cid),
                _wrong(cid, hint="This doesn't apply to this house.")]

    if sit == "tidy":
        return [_answer(
            "fix", "Plan", "brAIn suggests names, rooms and aliases in this "
            "house's own style, as one card to review. Nothing changes "
            "until you press Apply on it.", route="/api/tidy/run",
            primary=True, done="Suggesting — they arrive as one card here"),
            _dismiss(cid), _wrong(cid)]

    if sit == "question":
        return [
            # Yes and No are the answer, not a verb: a guess is a yes/no
            # question and a button called anything else asks somebody to
            # translate.
            _answer("yes", "Yes", "That's right. It becomes a plain fact "
                    "in memory.", route=f"/api/case/{cid}/do",
                    primary=True, done="Filed into memory"),
            # `request="wrong"`: a question the Resident filed is a finding
            # row, so Home Assistant's Repairs and a notification can carry
            # *No* back as the same correction the tab makes.
            _answer("no", "No", "Not right — say why if you can, and the "
                    "reason retires every guess built on the same "
                    "misreading.", route=f"/api/case/{cid}/wrong",
                    request="wrong", note=True, done="Noted"),
            _dismiss(cid, question=(case.get("origin") or {}).get("store")
                     == "hypotheses"),
        ]

    if sit == "opportunity":
        return [
            _answer("accept", "Apply", "Write it into Home Assistant and "
                    "reload. Undo takes it straight back out.",
                    route=f"/api/case/{cid}/do", primary=True,
                    done="Applied — Undo puts it back"),
            _dismiss(cid),
            _answer("decline", "Ignore", "Not for this house. Say why if "
                    "you like, and the reason reaches every future "
                    "suggestion.", route=f"/api/case/{cid}/wrong", note=True,
                    done="Ignored"),
        ]

    if sit == "chore":
        return [
            _answer("complete", "Done", "Tick it off. This is the moment "
                    "the fact goes into memory.", route=f"/api/case/{cid}/do",
                    primary=True, done="Done — written into memory"),
            _dismiss(cid),
            _answer("drop", "Ignore", "Take it off the list for good: "
                    "brAIn will not raise it again.",
                    route=f"/api/case/{cid}/wrong", done="Ignored"),
        ]

    if sit == "chore_done":
        return [_answer("reopen", "Restore", "Back onto Your list, "
                        "undone.", route=f"/api/todo/{key}/reopen",
                        primary=True, done="Back on your list")]

    if sit == "watching":
        return [
            _answer("elevate", "Restore", "brAIn looked and decided not to "
                    "bother you. This puts it back in the queue as the check "
                    "filed it.", route=f"/api/finding/{key}/elevate",
                    primary=True, done="Back in the queue"),
            _wrong(cid),
        ]

    # -- problems: one primary, then Snooze · Ignore -------------------------
    # A chore check (empty the dishwasher, shut the back door) is the one
    # problem whose honest first press is "Done": the work is minutes and
    # putting it on a list is sillier than doing it. Everything else leads
    # with Plan where brAIn could act and the list where it could not.
    if sit == "chore_check":
        return [_done(key, primary=True), _dismiss(cid), _wrong(cid)]
    if (sit not in HANDS and sit != "fix_failed" and case.get("fixable")
            and not plan_refused(plan)):
        lead = _plan(key, primary=True)
    else:
        lead = _todo(cid, primary=True)
    return [lead, _dismiss(cid),
            _wrong(cid, prefill=PREFILL.get(sit, ""))][:MAX_VISIBLE]


# The one status chip on a card (docs/design/ui-redesign-2026-10.md,
# "Visual standard"): a dot and one word, four kinds and no fifth.
CHIPS = ("urgent", "problem", "tidy", "suggestion")
CHIP_WORDS = {"urgent": "Urgent", "problem": "Problem", "tidy": "Tidy-up",
              "suggestion": "Suggestion"}


def chip(case: dict, urgent: bool = False) -> str:
    """Which of `CHIPS` this case wears. `urgent` is the caller's, because
    it is `notify_router.is_urgent`'s rule and this module is a leaf.

    A question rides as a suggestion: it is brAIn proposing something it
    thinks is true, in the asking colour, and a fifth chip for it would be
    the two-severities-at-once card the design doc cut."""
    if urgent:
        return "urgent"
    kind = case.get("kind")
    if kind in ("opportunity", "question"):
        return "suggestion"
    if situation(case) == "tidy" or case.get("severity") == "info":
        return "tidy"
    return "problem"


def more(case: dict, visible: list[dict], overflow: list[dict]) -> list[dict]:
    """What goes behind the ⋯: at most `MAX_MORE` of Ask, Recheck, Done
    and Plan — the design doc's four, chosen per kind — never one already
    on the row.

    `overflow` (`cases.overflow`'s whole list) is read only for the verb
    no finding has: a proposal's week-long trial. Everything else is built
    here, so the two lists cannot name one press twice under two words.
    """
    shown = {a["verb"] for a in visible}
    out: list[dict] = []

    def add(item: dict) -> None:
        if item["verb"] not in shown and len(out) < MAX_MORE:
            shown.add(item["verb"])
            out.append(item)

    sit = situation(case)
    store = (case.get("origin") or {}).get("store")
    key = _finding_key(case)
    kind = case.get("kind")
    cid = str(case.get("id") or "")
    if store == "findings":
        if sit in ("planning", "fixing", "change"):
            add(_ask(key))
            return out
        if sit == "chore_check":
            add(_todo(cid))
        add(_ask(key))
        if str(case.get("source") or "").startswith("check:"):
            add(_recheck(key))
        if kind in ("problem", "opportunity") and sit != "watching":
            add(_done(key))
        plan = case.get("plan") or {}
        if (case.get("fixable") and sit not in HANDS and sit != "watching"
                and (plan_refused(plan) or sit == "fix_failed")):
            add(_plan(key))
        return out
    for item in overflow or []:
        if item.get("verb") == "trial":
            add(_answer("trial", "Run", "Try it for a week first: replay it "
                        "over the days since and grade each firing against "
                        "what you did. Nothing is switched on.",
                        route=item["route"], done="Trial started"))
    return out


def request_answers(row: dict) -> list[dict]:
    """The answers a FINDING row can be given from outside the panel, as
    `[{action, label}]` — what the mirror carries and what Repairs and a
    notification render.

    Built from a bare store row rather than a case, because the mirror is
    written by the store and the store cannot import `cases`. The
    situation is read the same way; only the presses HA can carry back as
    a request survive. A phone cannot start a plan run, so a problem whose
    card leads with *Plan* is offered *Add to list* in its place — the
    lock screen's way of saying "I'll handle it" — and *Snooze* rides at
    the end of any row that somehow left it off, because "not this
    minute" is the lock-screen answer.
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
    if (out and "todo" not in actions and case["kind"] == "problem"
            and situation(case) != "chore_check"):
        out.insert(0, {"action": "todo", "label": "Add to list"})
        actions.add("todo")
    if out and "snooze" not in actions and case["kind"] != "change":
        out.append({"action": "snooze", "label": "Snooze"})
    return out


__all__ = ["AUTOMATION_PREFIX", "CHECK_SITUATIONS", "CHIPS", "CHIP_WORDS", "HANDS",
           "LEGACY_PLAN_MARK", "MAX_MORE", "MAX_VISIBLE", "PREFILL", "REQUEST_ACTIONS",
           "SITUATIONS", "answers", "chip", "more", "plan_is_legacy", "plan_refused",
           "request_answers", "situation"]
