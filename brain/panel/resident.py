"""The Resident — deciding what deserves attention, and what to do about it.

Everything scheduled in brAIn is a rule. A check reads one instant and
files what it finds; a miner reads a ledger and decides something is a
habit; a model is handed the answer and asked to phrase it. What that
costs is the complaint the whole of 2.0 is written against — *"so many of
the things you surface aren't actually real"* — and the maintainer already
named the fix in the same breath: *"the dumb ones are the ones that are
the most annoying that AI can solve on its own"*.

So the judgement moves to the front. A cheap look reads a batch of signals
and says, per signal, whether it is worth anything at all; only what
survives that buys a stronger run, and only what that run can make a claim
about becomes a case in front of a person.

**Nothing in this module calls `engine`.** It builds prompts and reads
replies; the server spawns the runs, records the tokens and files the
cases. That is not tidiness — it is what lets every rule below be driven
in a test with no CLI, no credential and no house, which is the only way
a prompt's guards have ever been held in this repo.

Four things live here, and they are four because each answers a different
question about the same loop.

**The first look** (`first_look_prompt`, `parse_first_look`) is
`triage.py`'s shape with the decision moved earlier: a numbered batch, a
closed vocabulary, structured output, and the rule that **silence
surfaces** — except that here surfacing is not a card, it is `watch`. A
signal the reply skipped, a reply that did not parse, a verdict nobody
asked for: every one of them leaves the signal on the watch list carrying
the sentence that says why, because a signal dropped for a reason nobody
recorded is a house nobody is watching.

**The guard** (`NEVER_IGNORE`, `never_ignore`) is the one thing a model's
verdict cannot overrule. Being wrong about a stuck thermometer costs a
card; being wrong about a leak costs a floor. A table, named rather than
derived, because a derivation over words is a name gate — the failure this
repo already documents in `dev.implausible` — and because the next thing
somebody wants exempted should have to be added on purpose.

**The watch list** (`watch`, `watched`, `expire`, `rejudge_due`) is what
makes `watch` a verdict rather than a bin. A watched subject re-enters the
look on **new evidence, never on the clock**: `curiosity.RETRY_EVENTS`'s
rule, for its reason — a timer buys the identical answer over the
identical data on somebody else's money.

**The ledger** (`Ledger`) is the budget, per local day, per tier. The
cheap tier never stops on it, because the whole plan rests on spending it
freely; the expensive ones stop, because a loop that can reach the top
tier is a loop that will.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import atomic_write
import model_plan

# ---------------------------------------------------------------------------
# The jobs, by name
# ---------------------------------------------------------------------------
#
# A job name and never a model: `model_plan` owns which tier a job runs at
# and how hard it thinks, and a second answer to that written here is the
# release where the attention loop quietly reaches Opus. The names are the
# ones already in `model_plan.JOBS`; a test pins that, because a job this
# module invents would fall through to the table's `sonnet` default and
# spend the middle tier on a look.
JOB_FIRST_LOOK = "first_look"
JOB_INVESTIGATE = "investigate"
JOB_PLAN = "fix_plan"
JOB_APPLY = "fix_apply"
JOBS = (JOB_FIRST_LOOK, JOB_INVESTIGATE, JOB_PLAN, JOB_APPLY)
# Which of them changed a house. A plan is a read-only run that says what
# it WOULD change, so it is counted under neither "looked" nor "acted" —
# saying "changed" about a sentence is the one claim the feed's foot exists
# not to make.
ACT_JOBS = (JOB_APPLY,)


def tier_for(job: str) -> str:
    """The tier a job runs at, read off `model_plan` rather than restated."""
    return model_plan.JOBS.get(job, ("sonnet",))[0]


# ---------------------------------------------------------------------------
# The first look
# ---------------------------------------------------------------------------

# Four verdicts, ordered by what each one costs. The order is the whole of
# the guard's arithmetic below: a floor raises a verdict, it never lowers
# one, so a model that already said `act` about a leak is left alone.
VERDICTS = ("ignore", "watch", "investigate", "act")
_RANK = {word: i for i, word in enumerate(VERDICTS)}

# One sentence per signal, shown on nothing and read in the log and the
# diagnostics — long enough to say what was read, short enough that a
# batch of them is not a page.
MAX_WHY = 240

# The batch. Bigger than triage's ten because a signal is a line rather
# than a paragraph and the point of the cheap tier is that a look is
# cheap; small enough that a reply is still a list somebody can read.
MAX_BATCH = 30

# A look is one turn over a batch that is already in the prompt: no tools,
# no history fetches, nothing to wait for.
TIMEOUT_S = 120
MAX_TURNS = 4

# What a signal that never got a verdict is left as, in the words the
# diagnostics show. `triage.NOT_MENTIONED`'s rule: one table, because six
# copies is six chances for one of them to stop saying that nothing looked.
SKIPPED = ("Nothing came back about this one, so it is being watched "
           "rather than dropped.")
UNREADABLE = ("The look's answer could not be read, so everything in the "
              "batch is being watched.")
FORCED = "This cannot be ignored: {why}."

# What a model's verdict may never be `ignore` about, and the floor each
# one earns.
#
# Two floors, because the two reasons are about different questions.
# `hot` is the signals module's own flag and it is about **when** — look
# now, do not wait for the timer — so what it earns is "do not forget
# this", which is `watch`. A safety class and a protected entity are about
# **what**, and the cheapest honest answer to those is to go and look.
#
# The table is a set of words matched against the signal's `kind`, plus
# the producer's own flags, and it deliberately does NOT scan the
# subject's entity id: that would be a name gate over somebody's naming
# scheme, which is the failure `checks/devices.measures_something_hot`
# documents, and `hot` is the signals module answering the same question
# with data instead of English. Over-matching here costs one look at the
# next tier; under-matching costs a leak nobody was shown, so the table is
# generous on purpose.
NEVER_IGNORE = ("leak", "water", "smoke", "co", "gas", "fire", "freeze",
                "security", "intrusion", "safety", "protected")
NEVER_IGNORE_FLOOR = "investigate"
HOT_FLOOR = "watch"
# The flags a signal may set itself, and what each one means to the guard.
# A producer that knows an entity is protected says so; nothing here tries
# to work it out.
FLAG_FLOORS = {"protected": NEVER_IGNORE_FLOOR, "safety": NEVER_IGNORE_FLOOR,
               "hot": HOT_FLOOR}

_WORD_RE = re.compile(r"[a-z0-9]+")


def never_ignore(signal: dict) -> tuple[str, str]:
    """`(floor, why)` — the least this signal's verdict may be, and why.

    `("", "")` when the model may say whatever it likes. The floors are
    ranked, so a signal that is both hot and about a leak takes the higher
    of the two rather than whichever was checked first.
    """
    if not isinstance(signal, dict):
        return "", ""
    floor, why = "", ""

    def raise_to(candidate: str, reason: str) -> None:
        nonlocal floor, why
        if _RANK.get(candidate, 0) > _RANK.get(floor, -1):
            floor, why = candidate, reason

    for flag, level in FLAG_FLOORS.items():
        if signal.get(flag):
            raise_to(level, f"the signal is marked {flag}")
    words = set(_WORD_RE.findall(str(signal.get("kind") or "").lower()))
    hit = sorted(words & set(NEVER_IGNORE))
    if hit:
        raise_to(NEVER_IGNORE_FLOOR, f"it is a {hit[0]} signal")
    return floor, why


FIRST_LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1},
                    "verdict": {"type": "string",
                                "enum": ["ignore", "watch", "investigate",
                                         "act"]},
                    "why": {"type": "string"},
                },
                "required": ["id", "verdict", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


FIRST_LOOK_SYSTEM = """You watch one home, and you are deciding what is worth anybody's attention.

You are given a batch of SIGNALS. A signal is something that happened or
something a rule noticed: a check found a reading it thinks is wrong, a
measurement went outside its usual band, an appliance finished a cycle, a
person changed something by hand, an automation errored, a device stopped
answering. A signal is NOT a verdict. Every one of them was produced by
arithmetic that cannot look anything up, so a great many of them are true
about a number and wrong about this house.

Your job is the one nobody has ever done here: to say, cheaply and
immediately, which of these deserve any further thought at all. Most do
not. The small, obvious, technically-true ones are the ones that make a
person stop reading a list, and they are exactly the ones you can drop
without being asked twice.

There are four verdicts and nothing else is read:

"ignore" — this is not worth another thought. A sensor that sits still
because it watches something that sits still, a reading that is normal for
what it measures, a change a person obviously made on purpose, something
the home has already been told about. Be generous with this one.

"watch" — it might be something and one occurrence is not enough to say.
Nothing is spent; if it happens again with more behind it, you will see it
again and can decide then. This is the right answer when your reason
starts with "if".

"investigate" — worth going and looking: the history, the area, what else
changed, what this home has already said about it. This costs real money,
so it is for signals where you expect looking to CHANGE what you would
tell somebody.

"act" — something is wrong now and waiting is the wrong answer. Water,
smoke, a freeze, a door left open at night, a device whose failure has
consequences today.

Rules:

- Never "ignore" anything about water, smoke, fire, gas, a freeze,
  security, a device somebody has marked protected, or a signal the home
  has already flagged as urgent. If one of those is in front of you and
  you think it is nothing, the answer is "watch" or "investigate" and your
  reason says why you think it is nothing.
- Say nothing about anybody's health, their whereabouts, who was home,
  their sleep or their household. If the only thing that makes a signal
  interesting is a person rather than the house, ignore it.
- "why" is one plain sentence naming what made you decide. It is read by
  the person who maintains this and it is the only record of your
  reasoning, so "looks fine" is not an answer.
- Judge each signal on what you were given. You have no tools here and
  nothing to look up: if you need to look something up, that is what
  "investigate" means.

Reply with JSON and nothing else:

{"verdicts": [{"id": 1, "verdict": "ignore", "why": "one sentence"},
              {"id": 2, "verdict": "investigate", "why": "one sentence"}]}

Every id you were given must appear exactly once."""


def _render_signal(signal: dict) -> str:
    """One signal as a line, for a caller that has no `signals` module.

    `signals.prompt_rows` is the renderer this prompt is written for and
    it is the one to hand in. This exists so the module can be driven on
    its own: one that could only be exercised through another module's
    output is one whose guards are tested through somebody else's bugs.
    """
    if not isinstance(signal, dict):
        return str(signal)
    bits = [f"[{signal.get('kind') or 'signal'}] {signal.get('subject') or ''}"]
    for name in ("salience", "repeats", "seen_at", "source"):
        if signal.get(name) not in (None, "", 0):
            bits.append(f"{name}={signal[name]}")
    evidence = signal.get("evidence")
    if evidence:
        bits.append(f"evidence: {evidence}")
    if signal.get("hot"):
        bits.append("marked urgent by the home")
    return " ".join(str(b) for b in bits).strip()


def _rows(rows) -> list[str]:
    """A list of rendered lines, whether the caller handed prose or data."""
    if isinstance(rows, str):
        return [line for line in rows.splitlines() if line.strip()]
    out = []
    for row in rows or []:
        out.append(row if isinstance(row, str) else _render_signal(row))
    return out


def first_look_prompt(batch_rows, memory_excerpt: str = "",
                      open_cases_rows=None) -> str:
    """The prompt for one batch.

    ``batch_rows`` is what `signals.prompt_rows` returned — or the raw
    signals, which are rendered here so this module can be driven alone.
    Signals are NUMBERED and never named back, `triage.frame`'s rule: a
    model retyping a subject can name the wrong one and a number cannot be
    nearly right.

    The open cases go in because the commonest reason a signal is worth
    nothing is that the home is already saying it, and the memory goes in
    because the commonest reason a signal is worth nothing *here* is
    something the homeowner has already explained.
    """
    parts = ["Decide what each of these signals is worth.\n"]
    if memory_excerpt.strip():
        parts.append("WHAT BRAIN KNOWS ABOUT THIS HOME:\n"
                     + memory_excerpt.strip() + "\n")
    cases = _rows(open_cases_rows)
    if cases:
        parts.append("ALREADY IN FRONT OF THE HOMEOWNER — a signal that is "
                     "one of these again is worth nothing:")
        parts += [f"- {row}" for row in cases]
        parts.append("")
    parts.append("SIGNALS:")
    for i, row in enumerate(_rows(batch_rows), 1):
        parts.append(f"{i}. {row}")
    parts.append("\nReply with the JSON contract and nothing else.")
    return "\n".join(parts)


def parse_first_look(obj, count: int, rows=None) -> dict[int, dict]:
    """`{1-based index: {verdict, why, forced}}` out of a reply.

    Every index from 1 to ``count`` is in the answer, always. That is the
    difference between this and `triage.parse`, and it is the same rule
    read the other way round: triage lets an unmentioned row fall through
    to the tab because surfacing is safe there, and here nothing is
    surfaced by a look — so a signal nobody judged has to be **kept**, and
    `watch` is the verdict that keeps it. Dropping it would be the one
    thing this loop must not do quietly.

    ``rows`` is the batch itself, and it is what `never_ignore` reads. It
    is optional because a caller may have only a count, and absent it the
    guard simply does not run — which is honest rather than safe, so the
    server passes it and a test pins that a leak cannot be ignored.

    `forced` says the verdict is the guard's rather than the model's: a
    third field instead of a tuple's third slot, because that is the one
    fact a reader has to be able to see and a slot is where it gets lost.
    """
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            obj = None
    listed = obj.get("verdicts") if isinstance(obj, dict) else obj
    said: dict[int, dict] = {}
    if isinstance(listed, list):
        for row in listed:
            if not isinstance(row, dict):
                continue
            try:
                idx = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if not 1 <= idx <= count or idx in said:
                continue
            verdict = str(row.get("verdict") or "").strip().lower()
            if verdict not in VERDICTS:
                # An invented verdict reads exactly like a real one, so it
                # is dropped rather than coerced — and a dropped one is
                # then a skipped one, which is watched and says so.
                continue
            said[idx] = {"verdict": verdict,
                         "why": str(row.get("why") or "").strip()[:MAX_WHY],
                         "forced": False}

    unreadable = not isinstance(listed, list)
    batch = list(rows or [])
    out: dict[int, dict] = {}
    for idx in range(1, count + 1):
        answer = said.get(idx) or {
            "verdict": "watch",
            "why": UNREADABLE if unreadable else SKIPPED,
            "forced": True,
        }
        signal = batch[idx - 1] if idx <= len(batch) else None
        floor, why = never_ignore(signal) if signal is not None else ("", "")
        if floor and _RANK[answer["verdict"]] < _RANK[floor]:
            answer = {"verdict": floor,
                      "why": (FORCED.format(why=why) + " " + answer["why"]
                              ).strip()[:MAX_WHY],
                      "forced": True}
        out[idx] = answer
    return out


# ---------------------------------------------------------------------------
# The investigation
# ---------------------------------------------------------------------------

# One signal, read properly: the entity's history, what else is in the
# area, the measurement stores, what the home has been told. An insight
# run's budget, because it is an insight run's shape.
INVESTIGATE_TIMEOUT_S = 420
INVESTIGATE_MAX_TURNS = 40

# What a Resident case may say it is. `change` and `chore` are absent on
# purpose: a change is something brAIn DID and a chore is what a person
# agreed to, and neither is a thing an investigation can decide it has
# found.
CASE_KINDS = ("problem", "opportunity", "question")

# How a case's stakes read as the severity the rest of the add-on already
# speaks. `high` maps to `serious` rather than `critical` because
# `critical` is the notifier's escalation tier — it pushes through quiet
# hours and repeats on a ladder — and that is a decision about a phone at
# three in the morning, not something an investigation's own confidence
# should be able to reach.
SEVERITY_BY_STAKES = {"high": "serious", "medium": "warning", "low": "info"}

# Below this, and only with high stakes, `escalate` is read at all. The
# plan's rule: a run that is unsure about something that matters is the
# one case worth a stronger model, and a run that is unsure about
# something that does not is a run that should have said `watch`.
ESCALATE_CONFIDENCE = 0.5

CASE_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "detail": {"type": "string"},
        "kind": {"type": "string", "enum": list(CASE_KINDS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "stakes": {"type": "string", "enum": ["low", "medium", "high"]},
        "fix": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "value": {"type": "string"},
                    "when": {"type": "string"},
                },
                "required": ["entity", "value", "when"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "shape": {"type": "string",
                              "enum": ["notify", "edit_file", "call_service",
                                       "write_automation"]},
                    "consent": {"type": "boolean"},
                    "detail": {"type": "string"},
                },
                "required": ["label", "shape", "consent", "detail"],
                "additionalProperties": False,
            },
        },
        "memory_hint": {"type": "string"},
        "escalate": {"type": "boolean"},
    },
    "required": ["claim", "detail", "confidence", "stakes", "evidence",
                 "actions", "escalate"],
    "additionalProperties": False,
}


INVESTIGATE_SYSTEM = """You look into ONE thing that happened in a home, and decide whether the person who lives there needs to know.

You have read-only tools: history, statistics, the logbook, traces, what
brAIn has measured about this house, and what it has been told. Use them.
The whole reason this run costs more than the look that sent it here is
that you can go and find out.

Answer with ONE JSON object and nothing else. What it means:

- "claim" — one sentence: what you are asserting is true, in plain words
  to the person who lives there. Not what you looked at, not a hedge, not
  a question. If you cannot make a claim, leave it EMPTY and nothing is
  filed, which is a good answer and costs nobody anything.
- "detail" — a short paragraph: what you found and why it follows.
- "kind" — "problem" if something is wrong, "opportunity" if something
  could be better, "question" if the honest answer is that you need to
  ask the person something only they can answer.
- "confidence" — 0 to 1, how sure you are of the claim.
- "stakes" — how much it matters if you are right: "low", "medium", "high".
- "fix" — what to DO about it, specific to this house: the entity, the
  integration, the automation, the setting. Never a category and never
  generic advice restated. If the honest answer is that there is nothing
  to do but wait, say that and why.
- "evidence" — every row is something you ACTUALLY READ. Each names the
  entity it came from, the value you saw and when. This is the half that
  makes a claim checkable, and it is the half you must not invent: if you
  did not read it, it does not go here. A claim with fabricated evidence
  is worse than no claim at all, because it goes in front of somebody as
  a fact and nothing will ever question it again.
- "actions" — zero or more things that could be done, each with a "shape"
  saying what kind of change it is ("notify", "call_service", "edit_file",
  "write_automation") and "consent" saying whether it must be asked before
  it happens. Anything that changes a file, writes an automation or calls
  a service on somebody's house needs consent. Propose nothing you cannot
  describe exactly.
- "memory_hint" — the durable fact this should teach if the person agrees
  it is right: something true of this HOUSE next month, not a note about
  today. Empty if there is none.
- "escalate" — true only if you are genuinely unsure AND being wrong would
  matter. It asks for a stronger model to look again; it is not a way to
  say something is important.

Rules that matter more than anything about style:

- NEVER invent a number, a reading or an event. Cite only what you read.
- Say nothing about anybody's health, their whereabouts, who was home,
  their sleep or their household. If the only account you can give is
  about a person rather than about the house, make no claim. This is not
  a style rule and there is no exception to it.
- Do not restate what brAIn already knows or what is already in front of
  the homeowner. If the answer is already on their list, make no claim.
- One claim per run. If you found two things, claim the one that matters
  and say the other in "detail"."""


def investigate_prompt(signal: dict, memory_excerpt: str = "",
                       house_block: str = "", open_cases_rows=None) -> str:
    """The prompt for one investigation.

    One signal, not a batch: the whole point of the tier is that this run
    goes and looks, and a run asked to look at ten things properly looks
    at none of them.
    """
    parts = ["Look into this, and decide whether it is worth telling the "
             + "homeowner.\n", "THE SIGNAL:", _render_signal(signal), ""]
    if memory_excerpt.strip():
        parts.append("WHAT BRAIN KNOWS ABOUT THIS HOME:\n"
                     + memory_excerpt.strip() + "\n")
    if house_block.strip():
        parts.append("WHAT BRAIN HAS MEASURED:\n" + house_block.strip() + "\n")
    cases = _rows(open_cases_rows)
    if cases:
        parts.append("ALREADY IN FRONT OF THE HOMEOWNER — do not claim any "
                     "of these again:")
        parts += [f"- {row}" for row in cases]
        parts.append("")
    parts.append("Reply with the JSON contract and nothing else.")
    return "\n".join(parts)


def _evidence_rows(value) -> list[dict]:
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip()
        if not entity:
            continue
        out.append({"entity": entity,
                    "value": str(item.get("value") or "").strip(),
                    "when": str(item.get("when") or "").strip()})
    return out


def parse_case(obj, *, read_entities=None) -> dict | None:
    """One reply as a row `findings_store.add_case` can file, or None.

    None for a reply that could not be read, for one that made no claim —
    which the contract asks for in as many words, and which is the honest
    and common outcome — and for one whose evidence names something the
    run never read.

    **That last one refuses the WHOLE case rather than trimming the row.**
    An invented reading is not a blemish on a sound conclusion: the
    conclusion was reasoned from it, so dropping the row leaves the claim
    it produced, wearing the evidence that survived. `read_entities` is
    what the run actually touched, and it is optional — with nothing to
    check against, nothing is checked, because "I could not look" and
    "there is nothing wrong" are different claims and only one of them may
    throw a real investigation away.

    `text` is set to the claim, because the claim is what the store
    dedupes on: a run that reaches the same conclusion twice in different
    words is the same case, and `findings_store.normalize` is what catches
    it. `severity` comes from the stakes through one table, so the
    notifier and the feed cannot disagree about the same case.
    """
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return None
    if not isinstance(obj, dict):
        return None
    claim = str(obj.get("claim") or "").strip()
    if not claim:
        return None

    evidence = _evidence_rows(obj.get("evidence"))
    if read_entities is not None:
        known = {str(e) for e in read_entities}
        if any(row["entity"] not in known for row in evidence):
            return None

    try:
        confidence = float(obj.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    stakes = obj.get("stakes")
    if stakes not in SEVERITY_BY_STAKES:
        stakes = "medium"
    kind = obj.get("kind") if obj.get("kind") in CASE_KINDS else "problem"

    actions = []
    for item in obj.get("actions") if isinstance(obj.get("actions"), list) else []:
        if not isinstance(item, dict):
            continue
        actions.append({
            "label": str(item.get("label") or "").strip(),
            "shape": str(item.get("shape") or "").strip().lower(),
            # An action whose consent flag could not be read must never be
            # read as permission already given — `_clean_actions` refuses
            # it the same way, and this is the door before that one.
            "consent": item.get("consent", True) is not False,
            "detail": str(item.get("detail") or "").strip(),
        })

    return {
        "text": claim,
        "claim": claim,
        "detail": str(obj.get("detail") or "").strip(),
        "kind": kind,
        "confidence": confidence,
        "stakes": stakes,
        "severity": SEVERITY_BY_STAKES[stakes],
        "fix": str(obj.get("fix") or "").strip(),
        "fix_by": "resident",
        "evidence": evidence,
        "actions": actions,
        "memory_hint": str(obj.get("memory_hint") or "").strip(),
        # Read only where the plan says it may be: a run that is unsure
        # about something that does not matter has asked for a stronger
        # model to settle a question nobody needed settled, and a flag
        # that means "this is important" is a flag every run sets.
        "escalate": (bool(obj.get("escalate"))
                     and confidence < ESCALATE_CONFIDENCE
                     and stakes == "high"),
    }


# ---------------------------------------------------------------------------
# The watch list
# ---------------------------------------------------------------------------

WATCH_FILE = Path(os.environ.get("BRAIN_RESIDENT_WATCH_FILE",
                                 "/data/resident-watch.json"))
# How long a subject stays watched with nothing further happening. A
# fortnight is the hypothesis queue's own answer to the same question and
# it is the right one here too: past it, the thing that was going to
# happen again has not, and re-judging the next occurrence from scratch
# costs one cheap look.
WATCH_TTL_S = 14 * 86400
# What re-opens a watched subject. Occurrences and never days, for
# `curiosity.RETRY_EVENTS`' reason: what makes the second look different
# from the first is that there is more to look at, and a week in which
# nothing happened has added nothing.
WATCH_RETRY_REPEATS = 3
MAX_WATCHED = 500
MAX_WATCH_WHY = 240


def _load_watch() -> dict[str, dict]:
    """Every way of failing to read answers "nothing is watched", which
    puts the next signal about that subject back into the look. That costs
    one cheap run; the other direction silently stops the loop looking at
    the thing it had decided to keep an eye on."""
    try:
        data = json.loads(WATCH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("watching") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)}


def _save_watch(rows: dict[str, dict]) -> None:
    if len(rows) > MAX_WATCHED:
        rows = dict(sorted(rows.items(),
                           key=lambda kv: kv[1].get("at") or 0)[-MAX_WATCHED:])
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_json(WATCH_FILE, {"watching": rows})


def watch(signal: dict, why: str = "", now: float | None = None) -> dict:
    """Keep an eye on this subject. Returns the entry as it now stands.

    The repeat count is recorded at the moment of watching, because that
    is the baseline the next signal is measured against: without it,
    "further evidence" would mean "any evidence", and the first signal
    after the watch would re-open it immediately.
    """
    now = time.time() if now is None else now
    subject = str((signal or {}).get("subject") or "")
    if not subject:
        return {}
    rows = _load_watch()
    rows[subject] = {
        "subject": subject,
        "kind": str((signal or {}).get("kind") or ""),
        "why": str(why or "").strip()[:MAX_WATCH_WHY],
        "at": int(now),
        "repeats": int((signal or {}).get("repeats") or 0),
    }
    _save_watch(rows)
    return rows[subject]


def watched() -> dict[str, dict]:
    """`{subject: entry}` — what is being kept an eye on."""
    return _load_watch()


def expire(now: float | None = None) -> int:
    """Drop what has been watched longer than `WATCH_TTL_S`. Returns how
    many went, so a caller can say so rather than guess."""
    now = time.time() if now is None else now
    rows = _load_watch()
    kept = {k: v for k, v in rows.items()
            if (now - float(v.get("at") or 0)) <= WATCH_TTL_S}
    if len(kept) != len(rows):
        _save_watch(kept)
    return len(rows) - len(kept)


def rejudge_due(signal: dict, now: float | None = None) -> bool:
    """May this signal go into the next look?

    True for a subject nothing is watching, for one whose watch has aged
    out, and for one that has happened `WATCH_RETRY_REPEATS` more times
    since — **never** simply because time has passed. A signal the guard
    will not let anybody ignore always passes, because a watch must not be
    able to hold a leak back.
    """
    now = time.time() if now is None else now
    if never_ignore(signal)[0]:
        return True
    subject = str((signal or {}).get("subject") or "")
    entry = _load_watch().get(subject)
    if entry is None:
        return True
    if (now - float(entry.get("at") or 0)) > WATCH_TTL_S:
        return True
    seen = int(entry.get("repeats") or 0)
    return int((signal or {}).get("repeats") or 0) - seen >= WATCH_RETRY_REPEATS


# ---------------------------------------------------------------------------
# The budget ledger
# ---------------------------------------------------------------------------

LEDGER_FILE = Path(os.environ.get("BRAIN_RESIDENT_LEDGER_FILE",
                                  "/data/resident-ledger.json"))

# What the thinking dial buys, per local day. The cheap tier is absent
# because it has no ceiling: the whole plan rests on looking being cheap
# enough to do freely, and a look that stops because a counter filled is a
# house nobody is watching for the rest of the day.
SONNET_PER_DAY = {"light": 4, "normal": 8, "generous": 16}
# And what may never be reached on a timer past. `fable` shares this
# ceiling and is additionally never allowed unattended at all, which is
# `model_plan.PRESS_ONLY` read from the budget's side.
OPUS_PER_DAY = {"light": 0, "normal": 2, "generous": 4}
# Days kept. Enough that a week's worth is answerable and small enough
# that the file is never anything but small.
LEDGER_DAYS = 7


def _day_key(now: float, tz) -> str:
    """The LOCAL day. A budget whose day turns at midnight UTC gives half
    the world two evenings' worth in one — `curiosity.spent`'s reason."""
    return dt.datetime.fromtimestamp(now, tz or dt.timezone.utc).date().isoformat()


class Ledger:
    """What the Resident has spent today, per tier, across restarts.

    Held on disk rather than in memory for `schedule_store`'s reason: a
    restart is the first thing anybody does after changing an option, so
    an in-memory count makes "twice a day" mean "twice per restart" — and
    the shape of the mistake is the same one the usage tracker's backoff
    made before `_resume_backoff`.

    **Every way of failing to read reads as nothing spent.** For the cheap
    tier that is exactly right and costs nothing. For the expensive ones
    it costs at most one day's allowance, once, where the other direction
    — an unreadable file read as *spent* — would stop the Resident
    investigating anything, for good, the first time a write was torn, and
    would look from every surface like a quiet house. `curiosity.load`
    makes the same trade for the same reason.
    """

    def __init__(self, path=None, tz=None):
        self.path = Path(path) if path else LEDGER_FILE
        self.tz = tz or dt.timezone.utc

    # -- storage ---------------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        days = data.get("days") if isinstance(data, dict) else None
        return {str(k): v for k, v in days.items()
                if isinstance(v, dict)} if isinstance(days, dict) else {}

    def _save(self, days: dict) -> None:
        if len(days) > LEDGER_DAYS:
            days = dict(sorted(days.items())[-LEDGER_DAYS:])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(self.path, {"days": days})

    # -- writing ---------------------------------------------------------
    def record(self, job: str, tokens: int = 0, now: float | None = None,
               tier: str = "") -> None:
        """Charge one run to today. Never raises: accounting must not be
        able to fail the run it is accounting for — `journal.record`'s
        rule, and this one is read by a budget rather than by a report."""
        now = time.time() if now is None else now
        try:
            tier = tier or tier_for(job)
            days = self._load()
            day = days.setdefault(_day_key(now, self.tz),
                                  {"jobs": {}, "tiers": {}})
            jobs = day.setdefault("jobs", {})
            jobs[job] = int(jobs.get(job) or 0) + 1
            row = day.setdefault("tiers", {}).setdefault(
                tier, {"runs": 0, "tokens": 0})
            row["runs"] = int(row.get("runs") or 0) + 1
            row["tokens"] = int(row.get("tokens") or 0) + max(0, int(tokens))
            self._save(days)
        except (OSError, TypeError, ValueError):
            # See the class docstring: a ledger that could not be written
            # is one day's allowance, and a ledger that took the run down
            # with it is the feature.
            pass

    # -- reading ---------------------------------------------------------
    def today(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return self._load().get(_day_key(now, self.tz),
                                {"jobs": {}, "tiers": {}})

    def spent(self, tier: str, now: float | None = None) -> int:
        return int((self.today(now).get("tiers") or {})
                   .get(tier, {}).get("runs") or 0)

    def allows(self, tier: str, thinking: str = model_plan.DEFAULT_THINKING,
               blocked: bool = False, *, pressed: bool = False,
               now: float | None = None) -> tuple[bool, str]:
        """`(may it run, why not)` — a sentence rather than a bare bool,
        because both halves of this are read on the diagnostics screen and
        "the budget is spent" and "the account is out" send somebody to
        two different places. `curiosity.may_ask`'s shape.

        `blocked` is the usage tracker's own answer about the account's
        real window, and it stops **everything**, the cheap tier included:
        a look that cannot be paid for is not a look. It is the one stop
        a press does not get past either, because a press cannot conjure
        a window that is spent.
        """
        if blocked:
            return False, ("the account's usage window is spent, so nothing "
                           + "is being run")
        if tier not in model_plan.TIERS:
            return False, f"there is no {tier} tier"
        if thinking not in model_plan.THINKING:
            thinking = model_plan.DEFAULT_THINKING
        if tier == "haiku":
            # Never stopped by the ledger. Looking is the cheap half and
            # the whole plan rests on spending it freely; a counter that
            # can switch it off is a house nobody is watching.
            return True, ""
        if pressed:
            # "Automatic runs pause; asking by hand always runs" — one
            # promise with two halves, and this is the second.
            return True, ""
        if tier == "fable":
            return False, ("the deep review is only ever run by a person's "
                           + "press")
        cap = (SONNET_PER_DAY if tier == "sonnet" else OPUS_PER_DAY)[thinking]
        used = self.spent(tier, now)
        if used >= cap:
            return False, (f"the {tier} allowance for today is spent "
                           + f"({used} of {cap} on the {thinking} thinking "
                           + "setting)")
        return True, ""

    def summary(self, now: float | None = None) -> dict:
        """What the feed's foot says, and what `/api/diagnostics` carries.

        "Looked 96 times, investigated 3, changed nothing" is the line, and
        the third number is deliberately about CHANGES: a plan is a
        read-only run that says what it would do, so counting one as an
        act would make the sentence claim something about somebody's house
        that never happened.
        """
        now = time.time() if now is None else now
        day = self.today(now)
        jobs = day.get("jobs") or {}
        tiers = day.get("tiers") or {}
        return {
            "day": _day_key(now, self.tz),
            "looked": int(jobs.get(JOB_FIRST_LOOK) or 0),
            "investigated": int(jobs.get(JOB_INVESTIGATE) or 0),
            "acted": sum(int(jobs.get(job) or 0) for job in ACT_JOBS),
            "tokens": {tier: int((row or {}).get("tokens") or 0)
                       for tier, row in tiers.items()},
        }


__all__ = [
    "ACT_JOBS", "CASE_KINDS", "CASE_SCHEMA", "ESCALATE_CONFIDENCE",
    "FIRST_LOOK_SCHEMA", "FIRST_LOOK_SYSTEM", "FORCED", "HOT_FLOOR",
    "INVESTIGATE_MAX_TURNS", "INVESTIGATE_SYSTEM", "INVESTIGATE_TIMEOUT_S",
    "JOBS", "JOB_APPLY", "JOB_FIRST_LOOK", "JOB_INVESTIGATE", "JOB_PLAN",
    "LEDGER_FILE", "MAX_BATCH", "MAX_TURNS", "MAX_WHY", "NEVER_IGNORE",
    "NEVER_IGNORE_FLOOR", "OPUS_PER_DAY", "SEVERITY_BY_STAKES", "SKIPPED",
    "SONNET_PER_DAY", "TIMEOUT_S", "UNREADABLE", "VERDICTS", "WATCH_FILE",
    "WATCH_RETRY_REPEATS", "WATCH_TTL_S", "Ledger", "expire",
    "first_look_prompt", "investigate_prompt", "never_ignore", "parse_case",
    "parse_first_look", "rejudge_due", "tier_for", "watch", "watched",
]
