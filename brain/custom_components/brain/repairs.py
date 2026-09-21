"""Repair flows for the brAIn integration.

Two of them. The first is a fixable repair that restarts Home Assistant
from Settings → System → Repairs when the integration files have been
updated. The second ends a **finding** from the same page: `findings.py`
raises one issue per row that is a decision waiting on somebody, and the
flow here is where the three answers a person can give from outside the
panel are offered.

The flow writes nothing to the findings store and could not if it wanted
to — the store is the panel's, on the other side of a port Home Assistant
cannot reach. A press drops a *request* through `requests.write_request`,
exactly as a tick in the To-do app and a button on a notification do, and
the panel applies it through the same `_end_finding` the Findings tab's
own buttons use. One ending, one implementation, three front doors.
"""

from __future__ import annotations

import logging
import os
from functools import partial

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .findings import ISSUE_PREFIX, issue_id_for, mark_answered
from .requests import write_request

_LOGGER = logging.getLogger(__name__)

# The three endings a finding can be given from outside the panel, in the
# order the menu offers them. They are `requests.ACTIONS` and nothing new:
# anything that starts WORK — a fix run, a regeneration — belongs behind
# the panel where the thing it starts can be watched.
FLOW_ACTIONS = ("fixed", "wrong", "snooze")

# "Remind me tomorrow", in hours. The same default the panel's own snooze
# uses; a box asking for a number would be a form in front of the one
# answer that exists to be quick.
SNOOZE_HOURS = 24

# How the answer is labelled in the add-on's log, beside `todo` and
# `notification`.
VIA = "repairs"

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


class FindingRepairFlow(RepairsFlow):
    """End one finding from Settings → System → Repairs.

    A menu rather than a confirm, because a finding has three honest
    answers and a page that only offered "dismiss" would teach people to
    dismiss the ones they meant to correct — which is the whole argument
    behind `✕ Wrong` carrying a note on the tab.

    Two details are load-bearing. **The press is the consent**: nothing is
    written until a menu option is chosen, and what is written is a
    request the add-on applies, never a change to the store. And the issue
    is **remembered as answered** before it is deleted, because the row
    stays on the mirror until the add-on has drained the request — without
    that, the next poll would raise the issue again and the dialog would
    reappear seconds after being closed.
    """

    def __init__(self, ts: int, text: str = "") -> None:
        self._ts = int(ts)
        self._text = text

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=list(FLOW_ACTIONS),
            description_placeholders={"text": self._text},
        )

    async def async_step_fixed(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self._answer("fixed")

    async def async_step_snooze(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self._answer("snooze", hours=SNOOZE_HOURS)

    async def async_step_wrong(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """"You have misread my house" — with an optional reason.

        The box is never required, for the reason the tab's is not: "not a
        problem here" needs no essay, and a mandatory field turns a
        one-press dismissal into a chore and fills up with "no". What is
        typed reaches the memory inbox as a correction, which is the half
        that teaches.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="wrong",
                data_schema=vol.Schema({vol.Optional("note", default=""): str}),
                description_placeholders={"text": self._text},
            )
        return await self._answer("wrong", note=str(user_input.get("note") or ""))

    async def _answer(self, action: str, note: str = "",
                      hours: float = 0) -> data_entry_flow.FlowResult:
        ok = await self.hass.async_add_executor_job(
            partial(write_request, self.hass, self._ts, action,
                    note=note, via=VIA, hours=hours))
        if not ok:
            # The shared volume would not take it. Aborting leaves the
            # issue exactly where it was, which is the honest outcome: an
            # entry that vanished over an answer nothing recorded is the
            # one ending with no way back.
            return self.async_abort(reason="cannot_write")
        mark_answered(self.hass, self._ts)
        # Deleted here as well as by the flow manager, so the entry going
        # away does not depend on a core detail this file cannot see.
        ir.async_delete_issue(self.hass, DOMAIN, issue_id_for(self._ts))
        return self.async_create_entry(title="", data={})


def _finding_ts(issue_id: str) -> int | None:
    """The finding a `finding_<ts>` issue is about, or None.

    An issue id is a string off the registry, so the tail is an int or
    this is not one of ours — the same rule `finding_requests.parse`
    applies to every field another process wrote.
    """
    try:
        return int(issue_id[len(ISSUE_PREFIX):])
    except (TypeError, ValueError):
        return None


def _remove_file(path: str) -> None:
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        # Removing a file that is already gone is this function's goal, not
        # its failure.
        pass


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the appropriate repair flow for a given issue."""
    if issue_id == "restart_required":
        return RestartRequiredRepairFlow()
    if issue_id.startswith(ISSUE_PREFIX):
        ts = _finding_ts(issue_id)
        if ts is not None:
            # `data` is what `findings.py` stamped on the issue, so the
            # dialog can name the finding without going back to the
            # mirror — and an issue raised by an older build that carries
            # none still ends the right row, because the ts is in the id.
            return FindingRepairFlow(ts, str((data or {}).get("text") or ""))
    if issue_id.startswith("user_"):
        # Issues created via brain.create_repair_issue: confirming
        # simply acknowledges and removes the issue.
        return ConfirmRepairFlow()
    return RepairsFlow()
