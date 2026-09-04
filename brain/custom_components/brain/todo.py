"""brAIn's work list, in Home Assistant's own To-do app.

The Findings tab is where brAIn reports what it thinks is broken, and it
is behind ingress: a critical finding is a panel somebody has to open.
The `sensor.brain_open_findings` count answers *how much*, and nothing
answered *what* anywhere a person already looks.

`todo.brain` is the same list, as items. **One list, two views** — not a
copy: every item is derived from the mirror the add-on publishes, nothing
about a finding is stored here, and the uid is the finding's own id.
Ticking one off ends the finding, through a request the add-on applies
with the same code the tab's buttons use.

Three decisions, each of them a refusal:

**Adding an item is not supported.** A to-do list you can add to and this
one cannot be the same thing: an item created here would have nothing
behind it and would vanish on the next poll. A list that silently deletes
what you put on it is worse than one that does not offer to take it, so
`CREATE_TODO_ITEM` is not in the feature set and the app hides the
button.

**Completing is "I've fixed it" and deleting is "not a problem".** They
are the tab's own two endings and no new vocabulary: both take the row
away, they mean opposite things, and each writes the memory line it
always did. Nothing here invents a third.

**A tick that races the add-on is not an error.** Somebody completes an
item the panel cleared four seconds ago; the request is dropped on the
add-on's side and the item is gone from the next poll either way. There
is nothing to report and nothing to retry.

There are no due dates yet, deliberately. A forecast's date lives in the
prose of its `detail` ("about 9 days left"), and a date parsed out of a
sentence is a guess with a calendar entry attached to it — the forecast
checks have to carry a real one first.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .findings import read_findings_state
from .requests import write_request

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

# A severity is a word people already read on the tab; repeating it in
# every summary would make the list a wall of "[warning]".
SEVERITY_MARK = {"critical": "🔴", "serious": "🟠", "warning": "🟡", "info": "⚪"}

# The list is what is waiting on a person. A row brAIn is fixing, or has
# fixed and is waiting to be acknowledged, is not a chore.
WAITING_STATUSES = ("open",)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the work list (account-wide, once)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_todo_added"):
        return
    # Which entry claimed it, so `async_unload_entry` can hand the list
    # back when that entry goes. Without the second key the flag survives
    # a reload and the list never comes back until Home Assistant
    # restarts — the failure the health sensor's own pair exists for.
    domain_data["_todo_added"] = True
    domain_data["_todo_entry"] = config_entry.entry_id
    async_add_entities([BrainTodoList(hass)], True)


def item_for(finding: dict) -> TodoItem | None:
    """One finding as a to-do item, or None if it is not one."""
    ts = finding.get("ts")
    text = str(finding.get("text") or "").strip()
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not text:
        return None
    if finding.get("status") not in WAITING_STATUSES:
        return None
    mark = SEVERITY_MARK.get(finding.get("severity"), "")
    detail = str(finding.get("detail") or "").strip()
    fix = str(finding.get("fix") or "").strip()
    source = str(finding.get("source_title") or "").strip()
    # The description is what somebody reads on a phone before deciding
    # to get up, so it is the evidence and the suggested fix — in that
    # order, because the second is only worth reading if the first is
    # true. The panel holds the full text; this is a summary of one.
    parts = [p for p in (detail, fix and f"Try: {fix}", source) if p]
    return TodoItem(
        summary=f"{mark} {text}".strip(),
        uid=str(int(ts)),
        status=TodoItemStatus.NEEDS_ACTION,
        description="\n\n".join(parts)[:1000] or None,
    )


class BrainTodoList(TodoListEntity):
    """The open findings, as Home Assistant's own to-do items."""

    _attr_has_entity_name = True
    _attr_name = "brAIn"
    _attr_icon = "mdi:clipboard-list-outline"
    # No CREATE: see the module docstring. Completing and deleting are
    # the tab's two endings, and there is no third.
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="brAIn System",
        manufacturer="BRUH Automation",
        model="Claude Terminal",
    )

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._attr_unique_id = f"{DOMAIN}_work_list"
        self._attr_todo_items: list[TodoItem] = []
        self._read_one = False

    @property
    def available(self) -> bool:
        """Unavailable until the add-on has published a mirror at all.

        An empty list and a list that could not be read look identical in
        the app, and only one of them means there is nothing to do — so
        "the add-on has never written one" is a state rather than a
        cheerful zero. Once one has been read the entity stays available
        and holds its last list: a restart is ten seconds, not an
        all-clear.
        """
        return self._read_one

    async def async_update(self) -> None:
        state = await self.hass.async_add_executor_job(
            read_findings_state, self.hass)
        if state is None:
            # Keep the last list rather than emptying it: the add-on
            # restarting for ten seconds must not read as "all clear".
            return
        items = [item_for(f) for f in state.get("findings") or []]
        self._attr_todo_items = [i for i in items if i is not None]
        self._read_one = True

    async def _answer(self, uid: str, action: str, note: str = "") -> None:
        try:
            ts = int(uid)
        except (TypeError, ValueError):
            _LOGGER.warning("ignoring a to-do item with no finding id: %s", uid)
            return
        await self.hass.async_add_executor_job(
            write_request, self.hass, ts, action, note, "todo", 0)
        # Drop it from the local list at once so the app does not show it
        # again for up to thirty seconds while the add-on catches up.
        self._attr_todo_items = [
            i for i in self._attr_todo_items or [] if i.uid != uid]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Completing one is "I've fixed it"; anything else is a no-op.

        The summary and description are the finding's, so an edit to
        either has nowhere to go — and rejecting the whole update would
        make a rename fail loudly over something nobody meant to change.
        """
        if item.status == TodoItemStatus.COMPLETED and item.uid:
            await self._answer(item.uid, "fixed")

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Deleting one is "not a problem here" — the tab's other ending."""
        for uid in uids:
            await self._answer(uid, "wrong")
