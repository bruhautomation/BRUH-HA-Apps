"""A standing automation from a sentence: drafted, simulated, then offered.

`intents.py` turns *"when the guests leave, turn the porch light off"* into
an automation that runs once and switches itself off. The sentence people
actually type most often is the other kind — *"whenever the front door
opens after dark, turn the hall light on"* — a rule that should keep
happening, and until 2.3 the one answer brAIn had for it was a refusal
card telling them to ask some other way. This is the other way.

One Claude run drafts the automation with reading tools only (the
analyst's path, exactly as a one-off is drafted). What comes back is
checked before it becomes anything, then **simulated** twice over the
recorder's own history: `shadow.replay` says how often it would have
fired over the last month, and `trials.evaluate` grades those firings
against the person ledger over the last fortnight — how many times you
had already done the same thing yourself within a quarter of an hour, and
how many times you did the opposite. That pair is the case on the card,
and it is what makes this a suggestion rather than a change: nothing is
written until *Do it* is pressed, and *Try it for a week* is the ordinary
shadow trial every proposal has.

Four rules, and each is a refusal rather than a guess.

**The trigger has to be replayable.** The replay is the only check there
is on an automation that has never run, and one nobody can replay is one
nobody can judge — `shadow.check_replayable`'s own list, never a second
copy of it.

**It has to name something.** An automation that acts on nothing is
indistinguishable from one that has not fired yet.

**No protected entity**, asked here at the producer as well as at the
writer, because a card offering something `automation_writer` will refuse
is a wasted yes.

**Nothing here decides whether the sentence was a one-off or a rule.**
The model answers `once` and the caller routes; `build` refuses a
one-off handed to it rather than quietly making a standing rule out of
something that was meant to happen exactly once — that is the direction
in which being wrong changes somebody's house every evening.
"""
from __future__ import annotations

import intents

# The window the person ledger is graded over. Two weeks is what the
# recorder holds on a default install and enough evenings for "you did
# the same" to mean anything; the replay itself runs the month
# `server.REPLAY_DAYS` gives every proposal.
GRADE_DAYS = 14

# The one-off keeps `brain_intent_`; a standing rule gets its own prefix
# so the two are tellable apart in somebody's automations list six months
# on, and `automation_writer.entry_for` takes either behind `brain_`.
ID_PREFIX = "brain_asked_"

SYSTEM = """You turn one sentence from the person who lives in a house
into one Home Assistant automation.

Use the read-only tools to find the entities the sentence is about. Search
by name; do not guess an entity id.

Answer with ONE JSON object and nothing else. No markdown fence, no
commentary.

  {"once": false,
   "plain": "<one sentence: what you understood, in their words>",
   "trigger": [ ... ], "condition": [ ... ], "action": [ ... ]}

`once` is the first thing to decide. It is `true` when the sentence asks
for a single thing to happen the NEXT time something occurs and never
again ("when the guests leave, turn the porch light off", "tell me when
the dishwasher is done") and `false` when it asks for a standing rule —
something that should keep happening every time ("whenever the front door
opens after dark, turn the hall light on", "always turn the heating down
when nobody is home"). When you cannot tell, it is a standing rule, and
say so in `plain`.

Rules, and each of them is something brAIn will refuse the answer over:

* `trigger` may only use `time`, `state`, `numeric_state` or `template`.
  Those are the four Home Assistant's recorder can replay, and the card
  this becomes shows the person how often the trigger would have fired
  over the last month and how that squares with what they did themselves
  — which is the only check there is on an automation that has never
  run. Any other kind (`device`, `event`, `webhook`, `mqtt`, `sun`,
  `zone`) makes the answer unusable. Write "after dark" as a `state`
  trigger on `sun.sun` or a `template`, never a `sun` trigger.
* `action` is what to do, and it names entities by id. For a one-off do
  not add an action that switches the automation off — brAIn writes that
  itself.
* `condition` may be omitted or empty.
* Do not set `id`, `alias`, `mode` or `description`.
* If nothing in the house matches what they named, answer
  {"once": false, "error": "<what you looked for and did not find>"}.

Be literal. A sentence you half-understood, written as an automation,
is a thing that happens in somebody's house — every evening, for a
standing rule."""

# The answer's shape is the one-off's: `once`, `plain`, the three lists.
SCHEMA = intents.SCHEMA
prompt = intents.prompt
parse_answer = intents.parse_answer
title_for = intents.title_for


def build(sentence: str, answer: dict, ts: int,
          patterns: list[str] | None = None) -> dict:
    """One standing proposal from one answer, or one carrying `refused`.

    Never raises and never returns None, `intents.build`'s contract: a
    sentence somebody typed always gets an answer, and *"brAIn could not
    do this and here is why"* is one of them.
    """
    import automation_writer  # noqa: PLC0415 — panel-local
    import shadow  # noqa: PLC0415

    plain = str(answer.get("plain") or "").strip()[:400]
    text = str(sentence).strip()[:intents.MAX_SENTENCE]
    out = {
        "kind": "automation",
        "source": "sentence",
        "title": title_for(sentence),
        "sentence": text,
        "plain": plain,
    }

    if answer.get("error"):
        out["refused"] = (
            "brAIn could not find what that sentence is about: "
            f"{str(answer['error'])[:200]}")
        return out
    if answer.get("once") is True:
        # The caller routes on `once`; a one-off reaching this builder is
        # a bug in the caller, and the honest answer is a refusal rather
        # than a rule that fires every evening about a thing meant to
        # happen exactly once.
        out["refused"] = ("that sounds like a one-off rather than a "
                          "standing rule — brAIn arms those separately.")
        return out

    triggers = intents._listify(answer.get("trigger") or answer.get("triggers"))
    steps = intents._listify(answer.get("action") or answer.get("actions"))
    if not triggers or not steps:
        out["refused"] = ("brAIn did not get an automation back it could "
                          "use — there was no trigger or no action in it.")
        return out

    config = {
        "id": f"{ID_PREFIX}{int(ts)}",
        "trigger": triggers,
        "condition": intents._listify(answer.get("condition")
                                      or answer.get("conditions")),
        "action": list(steps),
        # Not the model's to choose: a rule that could run twice at once
        # over one door opening is two porch lights arguing.
        "mode": "single",
    }

    try:
        shadow.check_replayable(config)
    except shadow.Refused as exc:
        out["refused"] = (
            f"brAIn will not offer this: {exc} — and without a replay "
            "there is nothing to show you about a rule that has never run.")
        return out

    named = set()
    for call in shadow.would_do(config):
        raw = call.get("entity_id")
        named |= {str(e) for e in intents._listify(raw) if e}
        if any(call.get(f"{k}_id")
               for k in ("area", "device", "label", "floor")):
            named.add("a target")
    if not named:
        out["refused"] = ("that sentence did not name anything in this "
                          "house that brAIn could act on, so the automation "
                          "would have done nothing.")
        return out

    refusal = automation_writer._protected_refusal(
        config, automation_writer.protected_patterns(patterns))
    if refusal:
        out["refused"] = refusal
        return out

    out["config"] = config
    out["why"] = why_for(sentence, plain)
    # The evidence the card renders, apart from the config `key_for`
    # hashes: the sentence and the restatement side by side (which half
    # was misread is the only thing worth knowing when it is wrong), and
    # the grade `server` fills in once it has replayed the fortnight.
    out["spoken"] = {"sentence": text, "plain": plain,
                     "against_you": None, "days": GRADE_DAYS}
    return out


def why_for(sentence: str, plain: str) -> str:
    """The card's one paragraph: theirs, then Claude's reading of it."""
    lead = f"You asked for this: “{str(sentence).strip()}”."
    if plain:
        return f"{lead} brAIn read that as: {plain}"
    return lead


def case_line(replay: dict | None, graded: dict | None,
              replay_days: int = 30) -> str:
    """The case for the rule, in one sentence, from the two simulations.

    The replay says how often it would have fired; the grade says how that
    squares with what the person did. A rule that would have fired nine
    times and agreed with them six is a habit they already have; one that
    would have fired nine times and been contradicted seven is a rule they
    would spend the week putting back. Both are worth knowing before
    saying yes, and neither is a number on its own.

    A simulation brAIn could not run says so rather than reading as zero:
    "it would never have fired" and "brAIn could not tell" are different
    answers and only one of them is about the rule.
    """
    if not isinstance(replay, dict) or replay.get("refused") \
            or replay.get("error"):
        why = ""
        if isinstance(replay, dict):
            why = str(replay.get("error") or "").strip()
        return ("brAIn could not replay this rule over your history"
                + (f" ({why})" if why else "") + ", so there is no count "
                "to show you — the trial week is the only check there is.")
    fired = int(replay.get("would_run") or 0)
    days = int(replay.get("days") or replay_days)
    times = "time" if fired == 1 else "times"
    head = f"Over the last {days} days it would have fired {fired} {times}"
    if not fired:
        return head + " — nothing it waits for happened in that window."
    if not isinstance(graded, dict) or graded.get("refused"):
        return head + "."
    window = int(graded.get("days") or GRADE_DAYS)
    within = int(graded.get("would_fire") or 0)
    agreed = int(graded.get("agreed") or 0)
    against = int(graded.get("contradicted") or 0)
    if not within:
        return head + f"; none of those fell in the last {window} days."
    parts = [f"{within} in the last {window} days"]
    if agreed:
        parts.append(f"you had already done the same on {agreed}")
    if against:
        parts.append(f"you did the opposite on {against}")
    if not agreed and not against:
        parts.append("nothing you did lined up with any of them")
    return head + ": " + ", ".join(parts) + "."
