#!/usr/bin/env python3
"""brAIn's work list inside Home Assistant, and the answers coming back.

The add-on republishes /config/.brain/findings_state.json on every change
(tests/test_findings.py pins that half) and cannot be reached from Home
Assistant — 8099 is unpublished on purpose — so this side reads the
mirror and writes *requests*. tests/test_finding_requests.py pins what
the add-on does with one; this pins what is written, and that the two
agree about the format without either being able to import the other.

`todo.py` and `requests.py` import the `todo` component and
`homeassistant.core`, so both come in through stubs that skip the
integration's heavyweight `__init__`.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

# --- just enough Home Assistant for the two modules under test -------------

if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    core = types.ModuleType("homeassistant.core")

    class _HomeAssistant:
        pass

    core.HomeAssistant = _HomeAssistant
    sys.modules["homeassistant.core"] = core

if "homeassistant.components.todo" not in sys.modules:
    for name in ("homeassistant.components", "homeassistant.config_entries",
                 "homeassistant.helpers", "homeassistant.helpers.device_registry",
                 "homeassistant.helpers.entity_platform"):
        sys.modules.setdefault(name, types.ModuleType(name))

    todo_mod = types.ModuleType("homeassistant.components.todo")

    class _TodoItem:
        def __init__(self, summary=None, uid=None, status=None,
                     description=None, due=None):
            self.summary, self.uid = summary, uid
            self.status, self.description, self.due = status, description, due

    class _TodoItemStatus:
        NEEDS_ACTION = "needs_action"
        COMPLETED = "completed"

    class _TodoListEntity:
        _attr_todo_items = None

    class _TodoListEntityFeature:
        CREATE_TODO_ITEM = 1
        DELETE_TODO_ITEM = 2
        UPDATE_TODO_ITEM = 4
        MOVE_TODO_ITEM = 8

    todo_mod.TodoItem = _TodoItem
    todo_mod.TodoItemStatus = _TodoItemStatus
    todo_mod.TodoListEntity = _TodoListEntity
    todo_mod.TodoListEntityFeature = _TodoListEntityFeature
    sys.modules["homeassistant.components.todo"] = todo_mod

    ce = sys.modules["homeassistant.config_entries"]
    ce.ConfigEntry = type("ConfigEntry", (), {})
    dr = sys.modules["homeassistant.helpers.device_registry"]
    dr.DeviceInfo = dict
    ep = sys.modules["homeassistant.helpers.entity_platform"]
    ep.AddEntitiesCallback = object

_pkg = types.ModuleType("brain_cc")
_pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules.setdefault("brain_cc", _pkg)

brain_requests = importlib.import_module("brain_cc.requests")
brain_todo = importlib.import_module("brain_cc.todo")
TodoItemStatus = sys.modules["homeassistant.components.todo"].TodoItemStatus
TodoItem = sys.modules["homeassistant.components.todo"].TodoItem

import finding_requests  # noqa: E402  (the add-on's reader)
import notify_router  # noqa: E402


class _Config:
    def __init__(self, base: str):
        self._base = base

    def path(self, *parts: str) -> str:
        return os.path.join(self._base, *parts)


class _Hass:
    def __init__(self, base: str):
        self.config = _Config(base)
        self.data: dict = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class WriterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = _Hass(self.tmp.name)
        self.dir = Path(brain_requests.requests_dir(self.hass))

    def written(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(self.dir.glob("*.json"))]


class TestWhatIsWritten(WriterCase):
    def test_a_request_lands_with_everything_the_addon_needs(self):
        self.assertTrue(brain_requests.write_request(
            self.hass, 1720, "wrong", note="never opened", via="todo"))
        rows = self.written()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ts"], 1720)
        self.assertEqual(rows[0]["action"], "wrong")
        self.assertEqual(rows[0]["note"], "never opened")
        self.assertEqual(rows[0]["via"], "todo")

    def test_only_the_three_endings_are_written(self):
        for action in ("fix", "delete", "", "regenerate"):
            self.assertFalse(brain_requests.write_request(
                self.hass, 1, action), action)
        self.assertEqual(self.written(), [])

    def test_the_directory_is_created_on_first_use(self):
        self.assertFalse(self.dir.exists())
        brain_requests.write_request(self.hass, 1, "fixed")
        self.assertTrue(self.dir.is_dir())

    def test_two_answers_in_the_same_instant_are_two_files(self):
        for ts in range(6):
            brain_requests.write_request(self.hass, ts + 1, "fixed")
        self.assertEqual(len(self.written()), 6)

    def test_names_sort_chronologically_so_answers_apply_in_order(self):
        for ts in (11, 22, 33):
            brain_requests.write_request(self.hass, ts, "fixed")
        names = sorted(p.name for p in self.dir.glob("*.json"))
        order = [json.loads((self.dir / n).read_text(encoding="utf-8"))["ts"]
                 for n in names]
        self.assertEqual(order, [11, 22, 33])

    def test_no_scratch_file_is_left_behind(self):
        # The add-on globs "*.json", so a leftover .tmp is invisible to
        # it — but a directory filling with them is still a bug.
        brain_requests.write_request(self.hass, 1, "fixed")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_an_unwritable_volume_is_reported_and_never_raised(self):
        # A to-do tick has nowhere useful to show an exception.
        broken = _Hass(os.path.join(self.tmp.name, "file"))
        Path(broken.config.path()).write_text("not a directory",
                                              encoding="utf-8")
        self.assertFalse(brain_requests.write_request(broken, 1, "fixed"))


class TestTheTwoSidesAgree(WriterCase):
    """Neither process can import the other, so the format is driven."""

    def test_what_is_written_is_what_the_addon_parses(self):
        brain_requests.write_request(self.hass, 1720, "wrong",
                                     note="never opened", via="todo")
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = self.dir
        try:
            got = finding_requests.collect()
        finally:
            finding_requests.REQUEST_DIR = old
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["ts"], 1720)
        self.assertEqual(got[0]["action"], "wrong")
        self.assertEqual(got[0]["note"], "never opened")
        self.assertEqual(got[0]["via"], "todo")

    def test_a_snooze_carries_its_hours_across(self):
        brain_requests.write_request(self.hass, 5, "snooze", hours=6)
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = self.dir
        try:
            got = finding_requests.collect()
        finally:
            finding_requests.REQUEST_DIR = old
        self.assertEqual(got[0]["hours"], 6.0)

    def test_the_button_identifier_survives_the_round_trip(self):
        # The add-on writes it into the notification; this side reads it
        # back off the companion app's event. Two processes, one format,
        # driven end to end rather than written down twice.
        for ts, verb in ((1720, "fixed"), (1, "wrong"), (1_760_000_000, "snooze")):
            wanted = [a for a in notify_router.actions_for(
                [{"ts": ts, "text": "a"}], "mobile_app_x")
                if a["action"].split(".")[1] == verb][0]
            self.assertEqual(brain_requests.parse_action(wanted["action"]),
                             (verb, ts))

    def test_the_reader_rejects_every_other_button_in_the_house(self):
        # The companion app fires this event for every actionable
        # notification anywhere, so most of what arrives is not ours.
        for junk in ("", None, "brain", "brain.fixed", "brain.fixed.x",
                     "brain.explode.1720", "other.fixed.1720",
                     "brain.fixed.1720.extra", "BRAIN.fixed.1720", 17):
            self.assertIsNone(brain_requests.parse_action(junk), junk)


class TestTheOwnershipFlag(WriterCase):
    """A flag left set over a reload is an entity that never comes back."""

    def test_setting_up_claims_the_pair_the_unload_clears(self):
        added = []

        def add_entities(entities, update_before_add=False):
            added.extend(entities)

        hass = _Hass(self.tmp.name)
        entry = types.SimpleNamespace(entry_id="abc123")
        asyncio.run(brain_todo.async_setup_entry(hass, entry, add_entities))
        data = hass.data["brain"]
        self.assertTrue(data["_todo_added"])
        # Without the second key the flag survives a reload and the list
        # never comes back until Home Assistant restarts.
        self.assertEqual(data["_todo_entry"], "abc123")
        self.assertEqual(len(added), 1)

    def test_a_second_entry_does_not_add_a_second_list(self):
        # One store, one list — the same account-wide rule the health
        # sensor and the findings watcher follow.
        added = []

        def add_entities(entities, update_before_add=False):
            added.extend(entities)

        hass = _Hass(self.tmp.name)
        for eid in ("abc123", "def456"):
            asyncio.run(brain_todo.async_setup_entry(
                hass, types.SimpleNamespace(entry_id=eid), add_entities))
        self.assertEqual(len(added), 1)
        self.assertEqual(hass.data["brain"]["_todo_entry"], "abc123")


class TestTheItems(unittest.TestCase):
    def finding(self, **kw):
        row = {"ts": 1720, "text": "The hall sensor has not reported",
               "severity": "serious", "status": "open",
               "detail": "last seen 3 Sep", "fix": "Re-pair it",
               "source_title": "Devices"}
        row.update(kw)
        return row

    def test_a_finding_becomes_an_item_the_addon_can_be_told_about(self):
        item = brain_todo.item_for(self.finding())
        self.assertEqual(item.uid, "1720")
        self.assertIn("hall sensor", item.summary)
        self.assertEqual(item.status, TodoItemStatus.NEEDS_ACTION)
        # The description is what somebody reads before deciding to get
        # up: the evidence, then the suggested fix.
        self.assertIn("last seen 3 Sep", item.description)
        self.assertIn("Re-pair it", item.description)
        self.assertLess(item.description.index("last seen"),
                        item.description.index("Re-pair"))

    def test_only_what_is_waiting_on_a_person_is_a_chore(self):
        # A row brAIn is fixing, or has fixed and is waiting to be
        # acknowledged, is not something to put on somebody's list.
        for status in ("fixing", "fixed", "dismissed", "", None):
            self.assertIsNone(
                brain_todo.item_for(self.finding(status=status)), status)

    def test_a_row_with_no_id_or_no_text_is_not_an_item(self):
        for kw in ({"ts": None}, {"ts": True}, {"ts": "1720"},
                   {"text": ""}, {"text": "   "}):
            self.assertIsNone(brain_todo.item_for(self.finding(**kw)), kw)

    def test_a_finding_with_no_prose_still_makes_an_item(self):
        item = brain_todo.item_for(
            self.finding(detail="", fix="", source_title=""))
        self.assertIsNotNone(item)
        self.assertIsNone(item.description)

    def test_the_description_is_bounded(self):
        item = brain_todo.item_for(
            self.finding(detail="x" * 5000, fix="y" * 5000))
        self.assertLessEqual(len(item.description), 1000)


class TestTheList(WriterCase):
    def setUp(self):
        super().setUp()
        self.state = Path(self.hass.config.path(".brain", "findings_state.json"))
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.list = brain_todo.BrainTodoList(self.hass)

    def publish(self, findings):
        self.state.write_text(json.dumps(
            {"ts": 1, "open": len(findings), "findings": findings}),
            encoding="utf-8")

    def row(self, ts, text="something", status="open"):
        return {"ts": ts, "text": text, "severity": "warning",
                "status": status, "detail": "", "fix": "",
                "source_title": "Checks"}

    def test_it_is_unavailable_until_the_addon_has_published_one(self):
        # An empty list and a list that could not be read look identical
        # in the app, and only one of them means there is nothing to do.
        self.assertFalse(self.list.available)
        asyncio.run(self.list.async_update())
        self.assertFalse(self.list.available)
        self.publish([self.row(1)])
        asyncio.run(self.list.async_update())
        self.assertTrue(self.list.available)

    def test_a_restart_holds_the_last_list_rather_than_clearing_it(self):
        self.publish([self.row(1), self.row(2)])
        asyncio.run(self.list.async_update())
        self.state.unlink()
        asyncio.run(self.list.async_update())
        self.assertEqual(len(self.list._attr_todo_items), 2)
        self.assertTrue(self.list.available)

    def test_completing_one_is_i_have_fixed_it(self):
        self.publish([self.row(1720)])
        asyncio.run(self.list.async_update())
        asyncio.run(self.list.async_update_todo_item(
            TodoItem(uid="1720", summary="x",
                     status=TodoItemStatus.COMPLETED)))
        rows = self.written()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["ts"], rows[0]["action"]), (1720, "fixed"))
        # And it leaves the list at once rather than reappearing for half
        # a minute while the add-on catches up.
        self.assertEqual(self.list._attr_todo_items, [])

    def test_deleting_one_is_not_a_problem_here(self):
        self.publish([self.row(1720), self.row(1721)])
        asyncio.run(self.list.async_update())
        asyncio.run(self.list.async_delete_todo_items(["1720", "1721"]))
        rows = self.written()
        self.assertEqual([r["action"] for r in rows], ["wrong", "wrong"])
        self.assertEqual(self.list._attr_todo_items, [])

    def test_an_edit_that_is_not_a_completion_answers_nothing(self):
        # The summary and description are the finding's, so a rename has
        # nowhere to go — and failing the whole update over something
        # nobody meant to change would be worse.
        self.publish([self.row(1720)])
        asyncio.run(self.list.async_update())
        asyncio.run(self.list.async_update_todo_item(
            TodoItem(uid="1720", summary="renamed",
                     status=TodoItemStatus.NEEDS_ACTION)))
        self.assertEqual(self.written(), [])
        self.assertEqual(len(self.list._attr_todo_items), 1)

    def test_an_item_with_no_finding_id_answers_nothing(self):
        asyncio.run(self.list.async_delete_todo_items(["not-a-number", ""]))
        self.assertEqual(self.written(), [])

    def test_adding_an_item_is_not_offered(self):
        # A list that silently deletes what you put on it is worse than
        # one that does not offer to take it: an item created here would
        # have nothing behind it and would vanish on the next poll.
        feature = sys.modules["homeassistant.components.todo"].TodoListEntityFeature
        self.assertFalse(
            brain_todo.BrainTodoList._attr_supported_features
            & feature.CREATE_TODO_ITEM)
        self.assertTrue(
            brain_todo.BrainTodoList._attr_supported_features
            & feature.DELETE_TODO_ITEM)
        self.assertTrue(
            brain_todo.BrainTodoList._attr_supported_features
            & feature.UPDATE_TODO_ITEM)


if __name__ == "__main__":
    unittest.main()
