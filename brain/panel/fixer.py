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

Stdlib plus engine (itself stdlib-only), so the test suite can import
it without the add-on runtime.
"""
from __future__ import annotations

import engine

# Turn budget for one fix. Generous rather than tight: a truncated agentic
# run leaves the house half-changed, which is far worse than a slow one.
DEFAULT_MAX_TURNS = 30

FIX_SYSTEM = """You are BRain, the AI that looks after one specific Home Assistant home. The homeowner has looked at a problem you reported and pressed "Fix it". You are now going to fix that one problem, in their real house.

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


def build_prompt(finding: dict, memory: str = "", context: str = "") -> str:
    """The user prompt for one fix run."""
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


def parse_result(text: str) -> dict:
    """Read the fix run's reply.

    Uses the same extractor the analysis path does — a second, subtly
    different JSON parser on the one path that edits a real house is not a
    place to be creative.

    A run that edits the house and then fails to produce parseable JSON has
    still edited the house, so this never raises: an unreadable reply comes
    back as a failure carrying the raw tail, which is the only honest thing
    to show someone whose home was just touched.
    """
    raw = (text or "").strip()
    obj = engine.extract_json(raw)
    if not isinstance(obj, dict):
        return {
            "ok": False,
            "needs_you": False,
            "summary": "The fix run finished but its report was unreadable, so "
                       "BRain cannot say what it changed. Check the affected "
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
