"""brAIn as Home Assistant's AI Task entity.

Home Assistant's AI Task platform (core 2025.7+) is what "Suggest with AI"
buttons and the `ai_task.generate_data` action call: an instruction in,
text or a requested structure out. This entity answers it through brAIn,
with the same rules every unattended brAIn run answers to:

* **Reading tools only.** It is sent as a `read_only` task — the analyst's
  allow and deny lists, derived in the listener — because a task an
  automation can start on a timer must not be able to change the house.
* **What brAIn knows.** `memory=True`, so the listener puts the panel's own
  retrieval block in front of the instruction rather than the model
  meeting the house cold.
* **A structure is validated twice.** It goes to the CLI as a JSON Schema
  (`--json-schema`), and the object that comes back is then validated
  against Home Assistant's own schema before it is returned — a reply
  that does not fit is an error with the reason, never data shaped
  nearly right.

The platform is feature-detected (`Platform.AI_TASK` in `__init__`), so an
older core never imports this module at all. One entity per house: it
rides with the account-wide sensors, and claims a flag the unload clears.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
    GenDataTaskResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# How long a task may take. A suggestion somebody is waiting on in a dialog
# is minutes at most; the listener's own window is longer.
TASK_TIMEOUT_S = 240
MAX_INSTRUCTIONS = 8000


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_ai_task_added"):
        return
    domain_data["_ai_task_added"] = True
    domain_data["_ai_task_entry"] = config_entry.entry_id
    async_add_entities([BrainAITaskEntity(config_entry)])


def json_schema_for(structure) -> dict | None:
    """Home Assistant's voluptuous structure as a JSON Schema, or None.

    Converted the way Home Assistant's own LLM integrations convert one
    (`voluptuous_openapi` with the LLM helper's selector serializer). A
    structure that cannot be converted is asked for as JSON in words and
    still validated afterwards — the conversion is a hint to the CLI, the
    validation is the guarantee.
    """
    if structure is None:
        return None
    try:
        from voluptuous_openapi import convert  # noqa: PLC0415

        try:
            from homeassistant.helpers.llm import selector_serializer  # noqa: PLC0415
        except ImportError:
            selector_serializer = None
        schema = convert(structure, custom_serializer=selector_serializer) \
            if selector_serializer else convert(structure)
    except Exception as exc:  # noqa: BLE001 — a hint we could not build
        _LOGGER.debug("could not convert the AI Task structure: %s", exc)
        return None
    return schema if isinstance(schema, dict) else None


def prompt_for(task) -> str:
    """The instruction as brAIn is asked it."""
    lines = [str(getattr(task, "instructions", "") or "")[:MAX_INSTRUCTIONS]]
    if getattr(task, "attachments", None):
        lines.append("\n(Attachments were sent with this task; brAIn cannot "
                     "read them here — answer from the house instead.)")
    if getattr(task, "structure", None) is not None:
        lines.append("\nAnswer with JSON only, in exactly the shape asked for.")
    return "\n".join(lines)


def _parse_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
    return None


class BrainAITaskEntity(AITaskEntity):
    """brAIn, as the house's AI Task provider. Reads, never acts."""

    _attr_has_entity_name = True
    _attr_name = "AI Task"
    _attr_icon = "mdi:creation-outline"
    _attr_supported_features = AITaskEntityFeature.GENERATE_DATA
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="brAIn System",
        manufacturer="BRUH Automation",
        model="Claude Terminal",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_ai_task"

    async def _async_generate_data(self, task: GenDataTask,
                                   chat_log) -> GenDataTaskResult:
        from . import _get_bridge  # local import: avoid cycle
        from .bridge import BrainRunError

        structure = getattr(task, "structure", None)
        schema = json_schema_for(structure)
        bridge = _get_bridge(self.hass)
        try:
            answer = await bridge.async_send_task_full(
                prompt=prompt_for(task), timeout=TASK_TIMEOUT_S,
                tools="read_only", schema=schema, memory=True)
        except BrainRunError as exc:
            raise HomeAssistantError(str(exc)) from exc
        except TimeoutError as exc:
            raise HomeAssistantError(
                "brAIn did not answer in time — is the automation listener "
                "turned on in the add-on?") from exc

        text = str((answer or {}).get("text") or "")
        conversation_id = getattr(chat_log, "conversation_id", None)
        if structure is None:
            return GenDataTaskResult(conversation_id=conversation_id, data=text)

        data = (answer or {}).get("data")
        if data is None:
            data = _parse_json(text)
        if data is None:
            raise HomeAssistantError(
                "brAIn answered, but not with the structure asked for.")
        try:
            data = structure(data)
        except Exception as exc:  # noqa: BLE001 — vol.Invalid and friends
            raise HomeAssistantError(
                f"brAIn's answer did not fit the structure asked for: {exc}"
            ) from exc
        return GenDataTaskResult(conversation_id=conversation_id, data=data)
