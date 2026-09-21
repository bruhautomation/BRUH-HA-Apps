"""The agentic half of Findings: actually going and fixing one.

Everything else the panel runs at Claude is pure generation over a data
bundle — tools are disallowed outright, because an insight card is a
drawing of data that is already in the prompt. A fix is the opposite: it
cannot be done from a snapshot. It needs to look at the live entity, read
the automation that is wrong, make the change, and check the change took.

So this is the one path in the panel that runs Claude *with* tools, and it
only ever runs because somebody pressed Fix on a specific finding. It is
bounded three ways: one finding per run, a turn cap, and a wall-clock
timeout. It reports back in the same JSON-only style as the rest.

The prompt's hard rules exist because this edits a real house. The short
version: change the minimum, never delete what you did not create, never
touch credentials, and if the fix turns out to need hands rather than
software, say so and stop instead of improvising something adjacent.

**There are two prompts here, because a press is now two presses.** Fix it
buys `PLAN_SYSTEM`: a READ-ONLY run (`engine.run_analyst`) that answers
with the steps it *would* take, and the change waits for somebody to read
them and press Apply. That is the difference between a button that starts
a tool-enabled run at a house and one that starts a sentence about it —
and it is enforced by which function the server calls rather than by
either prompt, because a tool list is a promise the CLI keeps. The two
runs are handed the same evidence (`_evidence`) and differ only in their
ending; `plan_block` is what carries the approved steps into the fix, so
the run that changes the house is asked to do the thing a person read
rather than to work out its own.

Stdlib plus engine (itself stdlib-only), so the test suite can import
it without the add-on runtime.
"""
from __future__ import annotations

import engine

# The plan run's guard. Far smaller than the fix's: this reads the entity, the
# automation and the history and writes a paragraph, where a fix has to make
# the change and then check it took.
DEFAULT_PLAN_MAX_TURNS = 24

# The runaway guard on one fix — not a budget. Large on purpose: a truncated
# agentic run leaves the house half-changed, which is far worse than a slow
# one, and the wall clock (FIX_TIMEOUT_S) is what actually bounds a fix.
DEFAULT_MAX_TURNS = 60

FIX_SYSTEM = """You are brAIn, the AI that looks after one specific Home Assistant home. The homeowner has looked at a problem you reported and pressed "Fix it". You are now going to fix that one problem, in their real house.

You have Home Assistant tools and shell/file access to the config directory. Use them.

HOW TO WORK
1. CONFIRM FIRST. Check the problem is still real — read the entity's current state, its history, the automation, whatever the finding points at. Homes change between the report and the press. If it has already resolved itself, say so and change nothing.
2. FIND THE ACTUAL CAUSE, not the symptom. An automation that never fires because its trigger entity was renamed is fixed by correcting the trigger, not by deleting the automation.
3. MAKE THE SMALLEST CHANGE THAT RESOLVES IT. One problem, one fix.
4. VERIFY. Re-read the state, re-validate the YAML, reload the relevant config. A fix you did not check is a claim, not a fix.

HARD RULES — these are not negotiable
- Fix ONLY the finding you were given. Anything else you notice along the way goes in "also_found", not into an edit.
- NEVER delete an entity, device, area, automation, script, dashboard or file you did not create in this run. Disable, correct, or comment out instead.
- NEVER touch secrets.yaml, credentials, tokens, or anything under .storage that you cannot validate.
- NEVER act on a PROTECTED ENTITY. The homeowner's protected list is given to you in the prompt below; anything matching it must not be turned on or off, set, unlocked, disabled, renamed, deleted, or written into an automation, a script or a scene that could act on it. Reading its state and its history is fine — the restriction is on acting. If the fix requires acting on one, do not do it: set "ok": false and say which entity and why. The MCP tools refuse these on your behalf, but shell and file edits do not go through them, so this rule is yours to keep.
- NEVER restart Home Assistant. Reloading a specific config domain is fine; a restart is the homeowner's call.
- If the real fix needs a human in the physical world — replacing a battery, re-pairing a device, power-cycling a hub — do NOT invent a software substitute. Set "needs_you": true and explain exactly what they have to do.
- If you are not confident the change is correct and safe, stop and explain. A refused fix is a good outcome; a wrong one costs trust.

OUTPUT
When you are finished, reply with ONE JSON object and nothing else — no markdown fences, no prose around it:
{
  "ok": true,
  "needs_you": false,
  "summary": "What you did, in one or two plain sentences the homeowner can check. Name what you changed and what it does now.",
  "changed": ["automation.morning_lights — trigger entity corrected to sensor.hall_motion", "one line per change; empty list if you changed nothing"],
  "verified": "How you confirmed it worked, or why you could not.",
  "also_found": ["optional: other problems you noticed and deliberately did not touch"]
}
Set "ok": false when the problem is still there. Set "needs_you": true when it needs hands rather than software — with "ok": false, because you did not fix it."""


def protected_block(patterns) -> str:
    """The homeowner's protected list, told to the one face that can bypass it.

    `protected_entities` is enforced in the MCP server, at the
    `call_service` chokepoint every `control_*` tool routes through —
    which covers every way the fixer can move something *through a tool*.
    It does not cover the two things this run has that an insight run
    does not: a shell and a file editor. `ha service light.turn_on`, a
    line added to `automations.yaml`, a script written and reloaded — all
    of them reach the house without passing the chokepoint, and none of
    them can be refused by it.

    So the list is stated. That is weaker than enforcement and it is not
    offered as a substitute for it: it is the only thing available on the
    paths where enforcement cannot reach, and a rule the model was never
    told is one it cannot keep. An empty list produces no block, because
    a heading over nothing reads as "nothing is protected here" — which
    is true, and is also what a list that failed to load looks like.
    """
    rows = [str(p).strip() for p in (patterns or []) if str(p).strip()]
    if not rows:
        return ""
    return (
        "PROTECTED ENTITIES — the homeowner has told brAIn not to act on "
        "these. Read them freely; do not turn them on or off, set them, "
        "unlock them, disable them, rename them, delete them, or write them "
        "into anything that could. The Home Assistant tools refuse these on "
        "your behalf, but a shell command or an edit to automations.yaml "
        "does not go through those tools, so on those paths this is the only "
        "thing standing between the list and the house:\n"
        + "\n".join(f"- {p}" for p in rows)
        + "\nA pattern ending in `.*` is a whole domain, and `*` is "
        "everything. If the fix needs one of these, do not do it — return "
        "\"ok\": false and say which entity and why.")


PLAN_SYSTEM = """You are brAIn, the AI that looks after one specific Home Assistant home. The homeowner has looked at a problem you reported and pressed "Fix it". You are NOT fixing it yet. You are working out what fixing it would mean, so they can read it and decide.

You have READ-ONLY Home Assistant tools. You cannot change anything on this run even if you try — no service calls, no file edits — and that is the point: this is the step that happens before consent.

HOW TO WORK
1. CONFIRM FIRST. Read the entity's current state, its history, the automation, whatever the finding points at. Homes change between the report and the press. If it has already resolved itself, say so: "can_fix" false, and why, in "summary".
2. FIND THE ACTUAL CAUSE, not the symptom. An automation that never fires because its trigger entity was renamed is fixed by correcting the trigger, not by deleting the automation.
3. WRITE THE STEPS SOMEBODY IS CONSENTING TO. One line per concrete change: which entity, file or automation, and what it becomes. "Edit /config/automations.yaml: change the trigger of 'Morning lights' from sensor.hall_motion_old to sensor.hall_motion" is a step. "Fix the automation" is not — it is the thing they already asked for, and nobody can say yes or no to it.
4. SAY WHAT COULD GO WRONG, in one sentence, about THIS change in THIS house. "The automation will not fire between the edit and the reload" is a risk; "changes may have side effects" is noise.

WHEN THE ANSWER IS NO
- If the real fix needs a human in the physical world — replacing a battery, re-pairing a device, power-cycling a hub — set "needs_you": true and say exactly what they have to do. Do not invent a software substitute.
- If the fix would need to act on a PROTECTED ENTITY (the homeowner's list is in the prompt below), set "can_fix": false and name the entity.
- If you cannot work out what is wrong, or this is a change you would not be confident making, set "can_fix": false and say so plainly. A refused plan is a good outcome; a confident wrong one costs trust, because this one is read as permission.

OUTPUT
Reply with ONE JSON object and nothing else — no markdown fences, no prose around it:
{
  "can_fix": true,
  "needs_you": false,
  "steps": ["one line per concrete change: which entity/file/automation, what it becomes"],
  "risk": "one sentence: what could go wrong",
  "summary": "One or two plain sentences: what is actually wrong, and what you would do about it."
}
Set "can_fix": false when software should not or cannot make this change — with an empty "steps", because a list of changes under a refusal reads as a plan somebody can approve."""


def build_plan_prompt(finding: dict, memory: str = "", context: str = "",
                      protected=None) -> str:
    """The user prompt for the read-only run that happens BEFORE any change.

    Deliberately the same evidence `build_prompt` hands the fix — the
    finding, what the rule (or a look, or a conversation) said to do, the
    house's memory, the protected list — because the plan is the fix's
    first few minutes done where a person can read the answer. What
    differs is only the ending: this one asks for the steps, and says out
    loud that nothing is being changed yet.
    """
    parts = _evidence(finding)
    block = protected_block(protected)
    if block:
        parts.append("\n" + block)
    if memory.strip():
        parts.append(
            "\nWHAT YOU ALREADY KNOW ABOUT THIS HOME — read it before you "
            "decide what to do, it is where the homeowner's preferences and "
            "this house's quirks live:\n" + memory.strip())
    if context.strip():
        parts.append("\n" + context.strip())
    parts.append(
        "\nGo and look now. Confirm it is still real, work out the cause, and "
        "reply with the JSON object per the contract — the steps are what the "
        "homeowner will read and press Apply on, so write them as the changes "
        "they are. Change NOTHING on this run. JSON only, no commentary."
    )
    return "\n".join(parts)


# The two replies as the CLI validates them (`--json-schema`). The prose
# contracts above still describe them for a CLI without the flag, and
# `parse_plan`/`parse_result` read either a validated object or the text.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "can_fix": {"type": "boolean"},
        "needs_you": {"type": "boolean"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["can_fix", "steps", "summary"],
    "additionalProperties": True,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "needs_you": {"type": "boolean"},
        "summary": {"type": "string"},
        "changed": {"type": "array", "items": {"type": "string"}},
        "verified": {"type": "string"},
        "also_found": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "summary"],
    "additionalProperties": True,
}


def parse_plan(text: str, obj: dict | None = None) -> dict:
    """Read the plan run's reply. Never raises, for `parse_result`'s reason.

    The failure here is cheaper than the fix's — nothing has been touched
    — but it has to fail in the direction that matters: an unreadable
    reply comes back as `can_fix: false` carrying the tail, so the card
    offers no Apply. **A plan this could not read must never be read as
    permission to change somebody's house**, which is also why an empty
    step list cannot be `can_fix`: Apply would send a tool-enabled run at
    a home carrying nothing it was told to do.

    `obj` is the CLI's validated object when the run carried PLAN_SCHEMA;
    the text is read only when there is none, so one reader serves both.
    """
    raw = (text or "").strip()
    if not isinstance(obj, dict):
        obj = engine.extract_json(raw)
    if not isinstance(obj, dict):
        return {
            "can_fix": False,
            "needs_you": False,
            "steps": [],
            "risk": "",
            "summary": "brAIn looked at this, but its plan came back "
                       "unreadable, so there is nothing to approve. Try "
                       "again, or discuss it in the chat."
                       + (f" It ended with: …{raw[-300:]}" if raw else ""),
        }

    needs_you = bool(obj.get("needs_you"))
    steps = []
    if isinstance(obj.get("steps"), list):
        for item in obj["steps"]:
            if isinstance(item, str) and item.strip():
                steps.append(item.strip()[:200])
    # Read the same way `parse_result` reads its pair: a change that needs
    # hands is not one software is going to make.
    can_fix = bool(obj.get("can_fix")) and not needs_you and bool(steps)
    return {
        "can_fix": can_fix,
        "needs_you": needs_you,
        # A refusal's steps are dropped rather than rendered: a list of
        # changes under "brAIn cannot do this" reads as a plan somebody
        # can approve, which is the one misreading this step exists to
        # prevent.
        "steps": steps if can_fix else [],
        "risk": str(obj.get("risk") or "").strip()[:300],
        "summary": str(obj.get("summary") or "").strip()[:600],
    }


def plan_block(plan: dict) -> str:
    """The approved plan, handed to the run that carries it out.

    This is the whole difference between the fix as it was and the fix as
    it is: the run is no longer asked to work out what to do, it is asked
    to do the thing a person read and said yes to. Anything else it now
    thinks would be better is a finding, not an edit — the rule
    ``also_found`` has always carried, with something specific to hold it
    against. An empty plan produces no block rather than an empty heading,
    `protected_block`'s reason.
    """
    steps = [str(s).strip() for s in (plan or {}).get("steps") or []
             if str(s).strip()]
    if not steps:
        return ""
    lines = ["THE PLAN THE HOMEOWNER APPROVED — do exactly these steps and "
             "nothing else:"]
    lines += [f"{i}. {step}" for i, step in enumerate(steps, 1)]
    if (plan or {}).get("risk"):
        lines.append(f"What you said could go wrong: {plan['risk']}")
    lines.append(
        "They pressed Apply on those steps and on nothing else. If you get "
        "there and the house has moved on, or a step turns out to be wrong or "
        "unsafe, STOP and say so — return \"ok\": false with what you found. "
        "Do not substitute a different change: they did not agree to one, and "
        "a fix nobody approved is worse than a fix that did not happen. "
        "Anything else you notice goes in \"also_found\".")
    return "\n".join(lines)


def _evidence(finding: dict) -> list[str]:
    """What is known about the problem, in the words both runs are given.

    The plan run and the fix run are handed the same evidence on purpose —
    they are two halves of one press — so it is assembled once. A second
    copy would be a second answer to "what did brAIn know when it
    decided", and the plan a person approved would stop describing the run
    that carries it out.
    """
    parts = ["THE PROBLEM TO FIX:", f"- What is wrong: {finding.get('text', '')}"]
    if finding.get("detail"):
        parts.append(f"- Evidence when it was reported: {finding['detail']}")
    if finding.get("entity_id"):
        parts.append(f"- Entity involved: {finding['entity_id']}")
    if finding.get("fix"):
        parts.append(
            f"- The fix proposed when it was reported: {finding['fix']}\n"
            "  Treat that as a starting hypothesis, not an instruction — you can "
            "see the live system and it could not."
        )
    if finding.get("source_title"):
        parts.append(f"- Reported by: {finding['source_title']}")
    if finding.get("fixable") is False:
        parts.append(
            "- This was flagged as needing a human. Verify that judgement "
            "yourself: if software really can fix it, fix it; if not, return "
            "\"needs_you\": true with precise instructions."
        )
    return parts


def build_prompt(finding: dict, memory: str = "", context: str = "",
                 protected=None, plan: dict | None = None) -> str:
    """The user prompt for one fix run.

    ``plan`` is what the homeowner actually pressed Apply on, and it is
    what the run is told to carry out rather than to work out. It stays
    optional in the signature for the one caller that may have none to
    hand — a row whose stored plan could not be read back — where the run
    is the fix it always was.
    """
    parts = _evidence(finding)

    approved = plan_block(plan or {})
    if approved:
        parts.append("\n" + approved)

    block = protected_block(protected)
    if block:
        parts.append("\n" + block)

    if memory.strip():
        parts.append(
            "\nWHAT YOU ALREADY KNOW ABOUT THIS HOME — read it before you change "
            "anything, it is where the homeowner's preferences and this house's "
            "quirks live:\n" + memory.strip())
    if context.strip():
        parts.append("\n" + context.strip())

    parts.append(
        "\nGo and fix it now. Confirm it is still real, find the cause, make the "
        "smallest correct change, verify it, then reply with the JSON object per "
        "the contract — JSON only, no commentary."
    )
    return "\n".join(parts)


def parse_result(text: str, obj: dict | None = None) -> dict:
    """Read the fix run's reply.

    Uses the same extractor the analysis path does — a second, subtly
    different JSON parser on the one path that edits a real house is not a
    place to be creative.

    A run that edits the house and then fails to produce parseable JSON has
    still edited the house, so this never raises: an unreadable reply comes
    back as a failure carrying the raw tail, which is the only honest thing
    to show someone whose home was just touched.

    `obj` is the CLI's validated object when the run carried RESULT_SCHEMA.
    """
    raw = (text or "").strip()
    if not isinstance(obj, dict):
        obj = engine.extract_json(raw)
    if not isinstance(obj, dict):
        return {
            "ok": False,
            "needs_you": False,
            "summary": "The fix run finished but its report was unreadable, so "
                       "brAIn cannot say what it changed. Check the affected "
                       "entity before pressing Fix again."
                       + (f" It ended with: …{raw[-300:]}" if raw else ""),
            "changed": [],
            "verified": "",
            "also_found": [],
        }

    def _strings(value, limit=None):
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip()[:200])
            if limit is not None and len(out) >= limit:
                break
        return out

    needs_you = bool(obj.get("needs_you"))
    return {
        # needs_you and ok are mutually exclusive by definition: if it needs
        # your hands, software did not fix it, whatever the model ticked.
        "ok": bool(obj.get("ok")) and not needs_you,
        "needs_you": needs_you,
        "summary": str(obj.get("summary") or "").strip()[:1000],
        # length is capped by findings_store, which owns MAX_CHANGED
        "changed": _strings(obj.get("changed")),
        "verified": str(obj.get("verified") or "").strip()[:400],
        "also_found": _strings(obj.get("also_found"), 5),
    }


def result_text(parsed: dict) -> str:
    """The one blob of text the Findings card shows after a run."""
    parts = [parsed["summary"]] if parsed.get("summary") else []
    if parsed.get("verified"):
        parts.append(f"Verified: {parsed['verified']}")
    return "\n\n".join(parts).strip()
