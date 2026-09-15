"""brAIn's work list, in Home Assistant's own To-do app.

The Findings tab is where brAIn reports what it thinks is broken, and it
is behind ingress: a critical finding is a panel somebody has to open.
The `sensor.brain_open_findings` count answers *how much*, and nothing
answered *what* anywhere a person already looks.

`todo.brain` is the same list, as items. **One list, three views** — not a
copy: every item is derived from a mirror the add-on publishes, nothing
is stored here, and the uid names the row it came from. Ticking one off
reaches the add-on as a request it applies with the same code the panel's
own buttons use.

**Two stores feed it, and the uid says which.** An open finding is brAIn
asking a question; an item on the to-do list is one somebody has already
answered with "yes, and I'll do it". They live in different stores with
different lifetimes — the whole point of accepting a finding is that the
item outlives the card — so they arrive here as two mirrors and are shown
as one list, because from the app's side they are the same thing: work.
The uid is `f:<finding ts>` or `t:<item id>`, prefixed rather than left
bare precisely so the two id spaces cannot collide by accident; a bare
integer is still read as a finding, because that is what every uid handed
out before the to-do list existed was, and an app holding an old one must
not silently answer about the wrong row.

Three decisions, and only one of them is still a refusal:

**Adding an item IS supported now, and was not.** The old refusal was
right for what this was: an item created against a derived list would
have had nothing behind it and would have vanished on the next poll, and
a list that silently deletes what you put on it is worse than one that
will not take it. There is a store behind it now, so `CREATE_TODO_ITEM`
creates a real row on the to-do list and it is still there on the next
poll — which is the condition the refusal was protecting, met rather than
argued away.

**Completing and deleting mean what they mean on the row's own list.**
On a finding they are still "I've fixed it" and "not a problem here", the
tab's two endings and no new vocabulary. On a to-do item, completing is
the tab's Done — the moment the memory line is written — and deleting is
taking it off the list undone, which lets brAIn report the problem again.
Nothing here invents a verb; each row's own list already had these.

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
from functools import partial

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
from .findings import read_findings_state, read_todo_state
from .requests import write_request, write_todo_request

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

# A severity is a word people already read on the tab; repeating it in
# every summary would make the list a wall of "[warning]".
SEVERITY_MARK = {"critical": "🔴", "serious": "🟠", "warning": "🟡", "info": "⚪"}

# The list is what is waiting on a person. A row brAIn is fixing, or has
# fixed and is waiting to be acknowledged, is not a chore.
WAITING_STATUSES = ("open",)

# Which store a uid names. Prefixed so the two id spaces cannot collide:
# a finding's ts is seconds and an item's id is milliseconds, which makes
# a collision unlikely rather than impossible, and "unlikely" is not a
# property to answer somebody's chores with.
FINDING_UID = "f:"
TODO_UID = "t:"


def split_uid(uid: str) -> tuple[str, int] | None:
    """`"t:17"` as `("todo", 17)`. A bare integer is a finding.

    The bare form is what every uid handed out before the to-do list
    existed looked like, and an app that has not polled since is still
    holding some — answering those as findings is the same courtesy
    `/api/finding/{ts}/ignore` is still routed for.
    """
    text = str(uid or "").strip()
    kind = "finding"
    if text.startswith(TODO_UID):
        kind, text = "todo", text[len(TODO_UID):]
    elif text.startswith(FINDING_UID):
        text = text[len(FINDING_UID):]
    try:
        return kind, int(text)
    except (TypeError, ValueError):
        return None


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
        uid=f"{FINDING_UID}{int(ts)}",
        status=TodoItemStatus.NEEDS_ACTION,
        description="\n\n".join(parts)[:1000] or None,
    )


def item_for_todo(row: dict) -> TodoItem | None:
    """One accepted chore as a to-do item, or None if it is not one.

    The same shape as a finding's, from the other store — deliberately,
    because a list where accepted work looked different from unaccepted
    work would be asking somebody to care about which store a chore is in,
    which is brAIn's bookkeeping and not theirs.
    """
    item_id = row.get("id")
    text = str(row.get("text") or "").strip()
    if isinstance(item_id, bool) or not isinstance(item_id, (int, float)):
        return None
    if not item_id or not text:
        return None
    mark = SEVERITY_MARK.get(row.get("severity"), "")
    detail = str(row.get("detail") or "").strip()
    fix = str(row.get("fix") or "").strip()
    source = str(row.get("source_title") or "").strip()
    parts = [p for p in (detail, fix and f"Try: {fix}", source) if p]
    return TodoItem(
        summary=f"{mark} {text}".strip(),
        uid=f"{TODO_UID}{int(item_id)}",
        status=TodoItemStatus.NEEDS_ACTION,
        description="\n\n".join(parts)[:1000] or None,
    )


class BrainTodoList(TodoListEntity):
    """The work waiting on a person, as Home Assistant's own to-do items.

    Two stores, one list: the findings brAIn is still asking about, and
    the chores somebody has already accepted. See the module docstring.
    """

    _attr_has_entity_name = True
    _attr_name = "brAIn"
    _attr_icon = "mdi:clipboard-list-outline"
    # CREATE is here because there is now a store behind it — see the
    # module docstring. Completing and deleting still mean what each row's
    # own list means by them, and there is still no third verb.
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
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
        # Kept apart so one mirror failing to read keeps the other half
        # rather than emptying the list — see `async_update`.
        self._chores: list[TodoItem] = []
        self._findings: list[TodoItem] = []
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
        """Both mirrors, as one list. Either one missing is not an empty list.

        A mirror that could not be read keeps whatever that half already
        held, rather than emptying it — the add-on restarting for ten
        seconds must not read as "all clear" — and the two are asked
        separately because an add-on mid-write can leave one current and
        the other a moment behind, which is a reason to keep the older
        half and not a reason to drop it.
        """
        findings = await self.hass.async_add_executor_job(
            read_findings_state, self.hass)
        chores = await self.hass.async_add_executor_job(
            read_todo_state, self.hass)
        if findings is None and chores is None:
            return

        if findings is not None:
            rows = [item_for(f) for f in findings.get("findings") or []]
            self._findings = [i for i in rows if i is not None]
        if chores is not None:
            rows = [item_for_todo(t) for t in chores.get("items") or []]
            self._chores = [i for i in rows if i is not None]

        # Accepted work first: it is what somebody has already agreed to
        # do, where a finding is still a question. A list that led with
        # the questions would put the undecided above the decided every
        # morning, which is the order that makes a list feel unfinished.
        self._attr_todo_items = self._chores + self._findings
        self._read_one = True

    async def _answer_finding(self, ts: int, action: str,
                              note: str = "") -> None:
        await self.hass.async_add_executor_job(
            write_request, self.hass, ts, action, note, "todo", 0)

    async def _answer_todo(self, action: str, *, item_id: int = 0,
                           text: str = "", note: str = "") -> None:
        await self.hass.async_add_executor_job(
            partial(write_todo_request, self.hass, action,
                    item_id=item_id, text=text, note=note, via="todo"))

    def _forget(self, uid: str) -> None:
        """Drop a row from the local list at once.

        The add-on catches up within seconds, but "seconds" is up to a
        whole poll interval, and an item that stays ticked-but-present
        for half a minute is one people tick again.
        """
        self._chores = [i for i in self._chores if i.uid != uid]
        self._findings = [i for i in self._findings if i.uid != uid]
        self._attr_todo_items = self._chores + self._findings

    async def _act(self, uid: str, *, finding: str, chore: str) -> None:
        """One press, routed to whichever list the row came from."""
        which = split_uid(uid)
        if which is None:
            _LOGGER.warning("ignoring a to-do item with no id: %s", uid)
            return
        kind, row_id = which
        if kind == "todo":
            await self._answer_todo(chore, item_id=row_id)
        else:
            await self._answer_finding(row_id, finding)
        self._forget(uid)

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add one by hand — a real row on the add-on's to-do list.

        Optimistically absent from the local list rather than
        optimistically present: the add-on mints the id, and an item
        shown here under an id nothing has issued is one that cannot be
        ticked off until the next poll replaces it. A few seconds of not
        being there is the smaller lie.
        """
        summary = str(item.summary or "").strip()
        if not summary:
            return
        await self._answer_todo("add", text=summary)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Completing one means what completing it means on its own list.

        On a finding that is "I've fixed it"; on a chore it is the tab's
        Done, which is the moment the memory line gets written. Anything
        else is a no-op: the summary and description are derived, so an
        edit to either has nowhere to go, and rejecting the whole update
        would make a rename fail loudly over something nobody meant to
        change.
        """
        if item.status == TodoItemStatus.COMPLETED and item.uid:
            await self._act(item.uid, finding="fixed", chore="done")

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Deleting means what deleting means on the row's own list.

        On a finding it is "not a problem here" — the tab's other ending.
        On a chore it is taking it off the list undone, which releases
        the suppression and lets brAIn report the problem again.
        """
        for uid in uids:
            await self._act(uid, finding="wrong", chore="drop")
