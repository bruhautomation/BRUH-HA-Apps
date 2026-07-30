"""Repair flows for the brAIn integration.

Provides a fixable repair that lets users restart Home Assistant directly
from Settings > System > Repairs when the integration files have been updated.
"""

from __future__ import annotations

import logging
import os

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
except ImportError:
    # HA versions before 2022.9 don't have the repairs module.
    # Provide a stub so the module can still be imported without errors.
    from homeassistant.data_entry_flow import FlowHandler as RepairsFlow  # type: ignore[assignment]

    ConfirmRepairFlow = RepairsFlow  # type: ignore[assignment,misc]


class RestartRequiredRepairFlow(RepairsFlow):
    """Repair flow that restarts Home Assistant to load updated integration files."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step - restart HA when user clicks the button."""
        if user_input is not None:
            # Clean up the marker file
            marker = self.hass.config.path(".brain", "restart_required")
            await self.hass.async_add_executor_job(_remove_file, marker)

            # Trigger the restart
            try:
                await self.hass.services.async_call("homeassistant", "restart")
            except Exception:
                _LOGGER.exception("Failed to restart Home Assistant")
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )


def _remove_file(path: str) -> None:
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the appropriate repair flow for a given issue."""
    if issue_id == "restart_required":
        return RestartRequiredRepairFlow()
    if issue_id.startswith("user_"):
        # Issues created via brain.create_repair_issue: confirming
        # simply acknowledges and removes the issue.
        return ConfirmRepairFlow()
    return RepairsFlow()
