"""The Repairs fix for entity ids that come from an appliance's older name."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

from .entity_ids import async_rename_entity_ids


class RenameEntityIdsFlow(RepairsFlow):
    """Rename an appliance's entity ids to its current name, once the owner confirms."""

    def __init__(self, serial: str, name: str) -> None:
        self._serial = serial
        self._name = name

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        if user_input is not None:
            async_rename_entity_ids(self.hass, self._serial)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._name},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    issue = ir.async_get(hass).async_get_issue("bruh_cooking", issue_id)
    placeholders = (issue.translation_placeholders if issue else None) or {}
    return RenameEntityIdsFlow(str((data or {}).get("serial") or ""), placeholders.get("name", ""))
