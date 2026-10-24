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

import automation_keys
import intents
import prompt_kit

# The window the person ledger is graded over. Two weeks is what the
# recorder holds on a default install and enough evenings for "you did
# the same" to mean anything; the replay itself runs the month
# `server.REPLAY_DAYS` gives every proposal.
GRADE_DAYS = 14

# The one-off keeps `brain_intent_`; a standing rule gets its own prefix
# so the two are tellable apart in somebody's automations list six months
# on, and `automation_writer.entry_for` takes either behind `brain_`.
ID_PREFIX = "brain_asked_"

# Person-facing: `plain` is the sentence on the card the person decides
# on; the trigger, condition and action lists are id fields, which is the
# one place PRESENTATION lets an entity id stand. A schema run, so the
# shape lives in `intents.SCHEMA`'s descriptions and is not restated here.
SYSTEM = prompt_kit.assemble(
    "You turn one sentence from the person who lives in a house into one "
    "Home Assistant automation. Nothing you write is applied: brAIn replays "
    "it over the house's recorded month and shows them a card first.",
    inputs=(
        "You are given their sentence, the rooms of the house and how many "
        "of each kind of thing it has."),
    tools=(
        "You have Home Assistant's reading tools. Find every entity the "
        "sentence is about by searching by name; never guess an entity id."),
    good=(
        "Decides `once` first, finds every entity the sentence names, and "
        "writes the smallest automation that does exactly what was said — "
        "nothing they did not ask for."),
    example=(
        "\"Whenever the front door opens after dark, turn the hall light "
        "on\" → once false; plain \"Turn the hall light on when the front "
        "door opens after sunset\"; a `state` trigger on the front door "
        "contact going to on, a `state` condition on sun.sun being "
        "below_horizon, and light.turn_on on the hall light."),
    rules="""\
Each of these is something brAIn refuses the answer over.
- `once` is true when the sentence asks for a single thing to happen the
  NEXT time something occurs and never again ("when the guests leave, turn
  the porch light off", "tell me when the dishwasher is done"), and false
  for a standing rule that should keep happening every time ("always turn
  the heating down when nobody is home"). When you cannot tell, it is a
  standing rule, and say so in `plain`.
- Write Home Assistant's current keys: `triggers`, `conditions` and
  `actions`, and each trigger names its kind under `trigger:`, never
  `platform:`.
- `triggers` may only use `time`, `state`, `numeric_state` or `template`.
  Those are the four the recorder can replay, and the card shows how often
  the trigger would have fired over the last month and how that squares
  with what they did themselves — the only check there is on an
  automation that has never run. Any other kind (`device`, `event`,
  `webhook`, `mqtt`, `sun`, `zone`) makes the answer unusable. Write
  "after dark" as a `state` trigger or condition on `sun.sun` or a
  `template`, never a `sun` trigger.
- `actions` names entities by id. For a one-off do not add an action that
  switches the automation off — brAIn writes that itself.
- `mode` is `single` (the default) or `restart`, and nothing else. Use
  `restart` when the automation WAITS — a `delay`, `wait_for_trigger` or
  `wait_template` — and a new trigger during the wait should start it
  again: "turn the light off five minutes after the motion stops" means
  after the LAST motion, and under `single` the light goes off five
  minutes after the first one with somebody still in the room. Better
  still, write the timeout as a second `state` trigger with `for:` and a
  `choose` on the trigger's `id`, which needs no wait at all. Never
  `parallel` or `queued`: two copies of one rule over one door opening is
  two lights arguing.
- Do not set `id`, `alias` or `description`.
- If nothing in the house matches what they named, set `error` to what
  you looked for and did not find, and leave the automation out.
- Be literal. A sentence you half-understood, written as an automation,
  is a thing that happens in somebody's house — every evening, for a
  standing rule.""",
)

# The two modes in which a rule never has two copies running at once.
ALLOWED_MODES = ("single", "restart")

# The answer's shape is the one-off's: `once`, `plain`, the three lists —
# and `mode`, which only a standing rule reads (a one-off is `single`).
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

    # The model's to choose between the two modes that never run a rule
    # twice at once, and refused beyond them. It used to be forced to
    # `single` with "two porch lights arguing" as the reason — which is an
    # argument against `parallel` and `queued`, not against `restart`, and
    # `restart` is what the commonest rule anybody asks for needs: on with
    # motion, off N minutes later, where `single` drops every re-trigger
    # during the wait and the light goes off on somebody still there. The
    # replay cannot show the difference (it models neither mode nor
    # delays), so this is decided here and not on the card.
    mode = str(answer.get("mode") or "single").strip().lower()
    if mode not in ALLOWED_MODES:
        out["refused"] = (
            f"brAIn will not write a `{mode[:20]}` rule: it would run more "
            "than one copy at once over a single trigger. Ask again and it "
            "will write one that runs once, or restarts.")
        return out
    config = automation_keys.modern({
        "id": f"{ID_PREFIX}{int(ts)}",
        "triggers": triggers,
        "conditions": intents._listify(answer.get("condition")
                                       or answer.get("conditions")),
        "actions": list(steps),
        "mode": mode,
    })

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
