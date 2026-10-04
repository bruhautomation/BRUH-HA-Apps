"""brAIn's measurements, offered to OTHER conversation agents.

Home Assistant's LLM API (`homeassistant.helpers.llm`, core 2024.6+) is how
a conversation agent — OpenAI's, Google's, a local model's, or the MCP
Server integration handing tools to an outside client — is given tools.
brAIn has spent months measuring this particular house; this API lets any
of those agents ask it three questions, all read-only:

* ``what_is_normal`` — what one entity normally reads at this hour of the
  week, and how far from that it is now;
* ``recall`` — what brAIn remembers about something, with where each fact
  came from;
* ``explain_change`` — why an entity is the way it is: its recent changes
  and what caused each.

Each is answered by the MCP server's own function (through the add-on's
API, `bridge.async_llm_tool`), so a measurement has one implementation
whichever agent asks. **Exposure is checked here**, because it is Home
Assistant that knows which assistant is asking: an entity that assistant
cannot see is refused before anything is asked, a fact about one is left
out of what `recall` returns, and an exposure that cannot be checked
refuses rather than answering.

Feature-detected: on a core without the helper, nothing is registered.
"""

from __future__ import annotations

import logging

import voluptuous as vol

try:
    from homeassistant.helpers import llm
except ImportError:  # a core before 2024.6
    llm = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

API_ID = "brain_measurements"
API_NAME = "brAIn measurements"
API_PROMPT = (
    "brAIn has measured this home over weeks. Use what_is_normal to tell an "
    "ordinary reading from an odd one, explain_change to say why something "
    "changed (an automation, a person, brAIn), and recall for what the "
    "household has told brAIn. These tools only read; they change nothing.")


def _should_expose(hass, assistant: str, entity_id: str) -> bool | None:
    """Home Assistant's own answer, or None when it cannot be asked."""
    try:
        from homeassistant.components.homeassistant.exposed_entities import (  # noqa: PLC0415
            async_should_expose,
        )
    except ImportError:
        return None
    try:
        return bool(async_should_expose(hass, assistant or "conversation", entity_id))
    except Exception:  # noqa: BLE001 — "I could not tell" is not a yes
        return None


def entity_refusal(hass, assistant: str, entity_id: str) -> str:
    """Why this assistant may not ask about this entity, or ""."""
    exposed = _should_expose(hass, assistant, entity_id)
    if exposed is None:
        return ("brAIn could not check whether that entity is exposed to this "
                "assistant, so it will not answer about it.")
    if not exposed:
        return (f"{entity_id} is not exposed to this assistant. It can be "
                "exposed in Settings → Voice assistants → Expose.")
    return ""


def filter_facts(hass, assistant: str, result: dict) -> dict:
    """`recall`'s answer without the facts about entities this assistant
    cannot see — a fact about an unexposed lock is a read of that lock."""
    facts = result.get("facts") if isinstance(result, dict) else None
    if not isinstance(facts, list):
        return result
    kept = []
    for fact in facts:
        subjects = (fact.get("subjects") or [fact.get("subject")]) \
            if isinstance(fact, dict) else []
        entities = [s for s in subjects
                    if isinstance(s, str) and "." in s and ":" not in s]
        if all(_should_expose(hass, assistant, e) is True for e in entities):
            kept.append(fact)
    return {**result, "facts": kept}


async def call_tool(hass, name: str, args: dict, assistant: str) -> dict:
    """One measurement for one assistant: exposure first, then the add-on."""
    from . import _get_bridge  # noqa: PLC0415 — local import: avoid cycle

    if name in ("what_is_normal", "explain_change"):
        entity = str((args or {}).get("entity_id") or "")
        refused = entity_refusal(hass, assistant, entity)
        if refused:
            return {"error": refused}
    try:
        bridge = _get_bridge(hass)
    except ValueError:
        return {"error": "brAIn is not set up."}
    result = await bridge.async_llm_tool(name, dict(args or {}))
    if name == "recall":
        result = filter_facts(hass, assistant, result)
    return result


def _tools():
    """The three tools, as Home Assistant LLM `Tool` objects."""
    class _BrainTool(llm.Tool):
        # The add-on's own name for the measurement. The name other agents
        # see carries a `brain_` prefix, so it cannot collide with Home
        # Assistant's own tools.
        tool_id = ""

        async def async_call(self, hass, tool_input, llm_context):
            assistant = getattr(llm_context, "assistant", None) or "conversation"
            return await call_tool(hass, self.tool_id,
                                   dict(getattr(tool_input, "tool_args", {}) or {}),
                                   assistant)

    class WhatIsNormal(_BrainTool):
        tool_id = "what_is_normal"
        name = "brain_what_is_normal"
        description = ("What one entity normally reads at this hour of the week "
                       "in this home, how far from that it is now, and where it "
                       "has been heading. Read-only.")
        parameters = vol.Schema({vol.Required("entity_id"): str})

    class Recall(_BrainTool):
        tool_id = "recall"
        name = "brain_recall"
        description = ("What brAIn remembers about this home on a subject or a "
                       "few words, each fact with who taught it and when. "
                       "Read-only.")
        parameters = vol.Schema({vol.Optional("query"): str,
                                 vol.Optional("subject"): str})

    class ExplainChange(_BrainTool):
        tool_id = "explain_change"
        name = "brain_explain_change"
        description = ("Why an entity is the way it is: its recent changes and "
                       "what caused each — an automation, a person, a voice "
                       "command, brAIn. Read-only.")
        parameters = vol.Schema({vol.Required("entity_id"): str,
                                 vol.Optional("hours"): int})

    return [WhatIsNormal(), Recall(), ExplainChange()]


def _make_api(hass):
    tools = _tools()

    class BrainMeasurementsAPI(llm.API):
        async def async_get_api_instance(self, llm_context):
            return llm.APIInstance(api=self, api_prompt=API_PROMPT,
                                   llm_context=llm_context, tools=tools)

    return BrainMeasurementsAPI(hass=hass, id=API_ID, name=API_NAME)


def async_register(hass):
    """Register the API; returns the unregister callable, or None."""
    if llm is None or not hasattr(llm, "async_register_api"):
        return None
    try:
        api = _make_api(hass)
        unregister = llm.async_register_api(hass, api)
    except Exception as exc:  # noqa: BLE001 — another agent's tools are optional
        _LOGGER.warning("could not register brAIn's LLM API: %s", exc)
        return None
    return unregister if callable(unregister) else None


__all__ = ["API_ID", "API_NAME", "async_register", "call_tool",
           "entity_refusal", "filter_facts"]
