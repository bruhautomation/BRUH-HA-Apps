"""A trial is a replay of the week you lived through, graded against you.

1.42.0 shipped the lifecycle and not the two steps that make it mean
anything. "Try it for a week" set a status and an end date, and nothing
ever looked at the week — `proposals.trial_due` and
`proposals.record_trial` had no caller outside their own tests. A trial
that reports nothing is indistinguishable from a trial that is not
running, which is the same failure as a feature that does nothing.

**A trial cannot subscribe to live events, and does not need to.** The
proposed automation would have fired at moments the recorder already
holds, and what the person actually did at those moments is already in
`routines.py`'s ledger — the person-caused changes the checks pass keeps
for two months. So the whole trial is arithmetic over two things that
exist: `shadow.replay` for when it would have fired, and the routine
ledger for what you did. Nothing here fetches, and nothing here writes.

That is also why it is re-run on **every** checks pass rather than once at
the end: replaying a window costs one history fetch, so "three days in,
it would have fired three times and you did the same twice" is free, and
a report that only exists on the seventh day is a week of a card saying
nothing.

**Three verdicts, and the third is the one worth having.** *Agreed* is a
person doing the same thing within `AGREE_WINDOW_S` of the firing.
*Disagreed* is nothing happening — which is weak evidence either way, and
says so by its name rather than by being counted as a failure.
*Contradicted* is the person putting the entity to the **opposite** state
in that window: they would have undone it, and a trial that folded that
into "disagreed" would report a change somebody actively did not want as
merely unproven. `auto.overridden`'s argument, one layer earlier.

**A refusal is carried, never zeroed.** `shadow.replay` refuses an
automation it cannot honestly reconstruct, and *"it would never have
fired"* and *"brAIn cannot replay this"* are different answers — only one
of them is about the automation. The same is true of an action this
cannot read as one entity going to one state: a proposal whose action is
a scene, a script or three service calls has no single thing to grade a
person's press against, and guessing which of them counts is how a
confident wrong number gets made.

**And nothing here decides anything** — the same split `baselines.py`,
`closures.py`, `routines.py` and `thermal.py` keep. It answers "what
would have happened, and what did you do"; the person reading the card
decides whether that is a yes.
"""
from __future__ import annotations

import time

import routines
import shadow

# How near a person's own press has to be to count as answering the
# firing. Fifteen minutes is `routines.MAX_SPREAD_MIN`'s scale cut in
# three: the habit that produced the proposal is a time give or take
# three quarters of an hour, so a window as wide as the spread would
# count a press that has nothing to do with this firing, and a window of
# a minute would miss the habit the proposal was mined from.
AGREE_WINDOW_S = 15 * 60

# The firings ride in the payload so the card can show them; past a
# handful nobody reads the list, and the counts above it are the answer.
MAX_FIRING_ROWS = 50

VERDICTS = ("agreed", "disagreed", "contradicted")

# The state a call produces, which is `routines._SERVICE` read backwards.
# Derived rather than inverted from that table on purpose: every entry
# here is checked against `routines.service_for` below, so the two can
# disagree only by failing to name a target at all — never by naming the
# wrong one.
STATE_FOR_VERB = {
    "turn_on": "on", "turn_off": "off",
    "open_cover": "open", "close_cover": "closed",
    "media_play": "playing", "media_pause": "paused",
}

# What "they would have undone it" means, per state. Only states that
# have an opposite are here: a `climate` mode has several, and "not this
# one" is not evidence of disagreement with this one.
OPPOSITE = {"on": "off", "off": "on",
            "open": "closed", "closed": "open",
            "playing": "paused", "paused": "playing"}


def _refused(reason: str) -> dict:
    return {"refused": True, "error": reason}


def target_of(config: dict) -> tuple[str, str] | None:
    """The one entity and the one state this automation's action produces.

    `None` when the action is anything else — several calls, a scene, a
    script, a service with no state to name, or a target this cannot
    resolve. `shadow.would_do` is what reads the action (one
    implementation of "what would this have done"), and
    `routines.service_for` is what confirms the answer: it is the map
    that built the config in the first place, so agreeing with it is the
    only way this cannot drift from the producer.
    """
    calls = shadow.would_do(config)
    if len(calls) != 1:
        return None
    call = calls[0]
    if call.get("area_id") or call.get("device_id"):
        # Resolving one needs the registries as they were at the time,
        # exactly as `actions.py` and `shadow.would_do` refuse to.
        return None
    entity = call.get("entity_id")
    if isinstance(entity, list):
        if len(entity) != 1:
            return None
        entity = entity[0]
    if not isinstance(entity, str) or "." not in entity:
        return None

    service = str(call.get("service") or "")
    verb = service.split(".", 1)[1] if "." in service else ""
    state = STATE_FOR_VERB.get(verb)
    if not state:
        return None
    if routines.service_for(entity, state) != service:
        return None
    return entity, state


def _verdict(when: float, entity_id: str, state: str,
             rows: list[dict]) -> str:
    """How the person answered this firing, from the nearest press.

    Only presses that mean something about *this* change are considered:
    the same state (agreement) or its opposite (a contradiction). A press
    putting the entity somewhere else entirely is not evidence about a
    proposal to turn it on, so it leaves the firing unanswered rather
    than counting against it — and the nearest of the two wins, because
    the closest evidence to the moment is the evidence about the moment.
    """
    against = OPPOSITE.get(state)
    best: tuple[float, float, str] | None = None
    for row in rows:
        if row.get("entity_id") != entity_id:
            continue
        row_state = str(row.get("state") or "")
        if row_state == state:
            verdict = "agreed"
        elif against and row_state == against:
            verdict = "contradicted"
        else:
            continue
        try:
            stamp = float(row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        gap = abs(stamp - when)
        if gap > AGREE_WINDOW_S:
            continue
        # Nearest wins; a tie goes to the earlier press, so the answer
        # does not depend on the order the ledger happens to be in.
        rank = (gap, stamp)
        if best is None or rank < (best[0], best[1]):
            best = (gap, stamp, verdict)
    return best[2] if best else "disagreed"


def evaluate(config: dict, history: dict, person_rows: list[dict],
             start: float, end: float, tz=None,
             now: float | None = None) -> dict:
    """What the trial has seen so far. Pure over what it is handed.

    `history` is what `shadow.fetch_history` returned for
    `shadow.entities_watched(config)` — empty for a `time` trigger, which
    watches nothing and needs no fetch. `person_rows` are
    `routines.load()["rows"]`.
    """
    if not isinstance(config, dict):
        return _refused("there is no automation to try")

    target = target_of(config)
    if target is None:
        return _refused(
            "this proposal's action is not one entity going to one state, "
            "so there is nothing to grade what you did against")
    entity_id, state = target

    try:
        result = shadow.replay(config, history, start, end, tz)
    except shadow.Refused as exc:
        return _refused(str(exc))

    rows = [r for r in (person_rows or []) if isinstance(r, dict)]
    counts = dict.fromkeys(VERDICTS, 0)
    firings = []
    for when in result.get("at") or []:
        verdict = _verdict(float(when), entity_id, state, rows)
        counts[verdict] += 1
        if len(firings) < MAX_FIRING_ROWS:
            firings.append({"ts": int(when), "verdict": verdict})

    return {
        "would_fire": int(result.get("would_run") or 0),
        **counts,
        "firings": firings,
        "entity_id": entity_id,
        "state": state,
        "window": {"start": int(start), "end": int(end)},
        # Whole days, because a trial is counted in days and "3 days in"
        # is what the card says. A part-day rounds down: the seventh day
        # is not over until it is.
        "days": max(0, int((end - start) // 86400)),
        "evaluated_at": int(time.time() if now is None else now),
    }


__all__ = ["AGREE_WINDOW_S", "MAX_FIRING_ROWS", "OPPOSITE", "STATE_FOR_VERB",
           "VERDICTS", "evaluate", "target_of"]
