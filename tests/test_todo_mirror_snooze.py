#!/usr/bin/env python3
"""`todo.brain` holds exactly what the panel's To Do section shows.

A real house's To-do app held 23 items. 14 was the queue — open findings,
questions and suggestions — which is a different list on purpose (a
finding is a decision; To Do is work already agreed to), so those two
numbers were never meant to agree. What WAS wrong is that the app's list
and the panel's To Do disagreed: Snooze on a To Do row (`/api/case/t:<id>/
not_now`) hides it on the panel until it lapses, the snooze lives in the
cases' sidecar the to-do mirror never read, and the mirror is only
rewritten when the to-do store itself changes — so every snoozed chore
stayed on the phone, and a lapsed one did not come back until something
else was written.

Pinned here: the mirror lists the open items that are not asleep and its
`open` is that count; a snooze reaches it without a to-do write and so
does its lapse; the integration lists only what the mirror calls open and
awake, even from an older mirror that still carries a snoozed or finished
row; and the panel's To Do count is the same number.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import todo_store  # noqa: E402


class MirrorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (todo_store.TODO_FILE, todo_store.STATE_FILE,
                     todo_store.SNOOZED)
        todo_store.TODO_FILE = base / "todo.json"
        (base / "config" / ".brain").mkdir(parents=True)
        todo_store.STATE_FILE = base / "config" / ".brain" / "todo_state.json"
        self.asleep: dict = {}
        todo_store.SNOOZED = lambda: dict(self.asleep)

    def tearDown(self):
        (todo_store.TODO_FILE, todo_store.STATE_FILE,
         todo_store.SNOOZED) = self._old
        self.tmp.cleanup()

    def mirror(self) -> dict:
        return json.loads(todo_store.STATE_FILE.read_text())


class TestTheMirrorIsTheSection(MirrorCase):
    def test_a_snoozed_item_is_not_on_the_mirror(self):
        a = todo_store.add("Change the hall battery")
        b = todo_store.add("Descale the kettle")
        self.asleep[f"t:{b['id']}"] = int(time.time()) + 3600
        todo_store.publish_state()
        got = self.mirror()
        self.assertEqual([i["id"] for i in got["items"]], [a["id"]])
        self.assertEqual(got["open"], 1)
        self.assertEqual(got["snoozed"], 1)

    def test_a_snooze_reaches_the_mirror_without_a_todo_write(self):
        todo_store.add("Change the hall battery")
        b = todo_store.add("Descale the kettle")
        self.assertEqual(self.mirror()["open"], 2)
        self.asleep[f"t:{b['id']}"] = int(time.time()) + 3600
        # The scheduler's tick: rewrites only when what it would say moved.
        self.assertTrue(todo_store.publish_state(only_if_changed=True))
        self.assertEqual(self.mirror()["open"], 1)
        self.assertFalse(todo_store.publish_state(only_if_changed=True))

    def test_a_lapsed_snooze_comes_back(self):
        b = todo_store.add("Descale the kettle")
        self.asleep[f"t:{b['id']}"] = int(time.time()) + 3600
        todo_store.publish_state()
        self.assertEqual(self.mirror()["open"], 0)
        self.asleep[f"t:{b['id']}"] = int(time.time()) - 1
        todo_store.publish_state(only_if_changed=True)
        self.assertEqual(self.mirror()["open"], 1)

    def test_a_finished_chore_is_not_on_it(self):
        a = todo_store.add("Change the hall battery")
        todo_store.add("Descale the kettle")
        todo_store.complete(a["id"])
        self.assertEqual(self.mirror()["open"], 1)

    def test_the_count_the_panel_shows_is_the_mirrors(self):
        todo_store.add("Change the hall battery")
        b = todo_store.add("Descale the kettle")
        self.asleep[f"t:{b['id']}"] = int(time.time()) + 3600
        todo_store.publish_state()
        self.assertEqual(todo_store.counts()["shown"], self.mirror()["open"])

    def test_an_unreadable_snooze_hides_nothing(self):
        todo_store.add("Change the hall battery")

        def boom():
            raise OSError("no")
        todo_store.SNOOZED = boom
        todo_store.publish_state()
        self.assertEqual(self.mirror()["open"], 1)


class TestTheAppListsWhatTheMirrorCallsOpen(unittest.TestCase):
    """An older mirror, or one written mid-change, may still carry a row
    the panel does not show; the list keys on the row, not on trust."""

    @classmethod
    def setUpClass(cls):
        import test_brain_todo
        cls.mod = test_brain_todo
        cls.brain_todo = test_brain_todo.brain_todo

    def setUp(self):
        self.case = self.mod.WriterCase("run")
        self.case.setUp()
        self.hass = self.case.hass
        base = Path(self.hass.config.path(".brain"))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "todo_state.json"
        self.list = self.brain_todo.BrainTodoList(self.hass)

    def tearDown(self):
        self.case.tearDown()

    def test_snoozed_and_finished_rows_are_not_listed(self):
        now = int(time.time())
        items = [
            {"id": 1, "text": "Change the hall battery", "status": "open"},
            {"id": 2, "text": "Descale the kettle", "status": "open",
             "snoozed_until": now + 3600},
            {"id": 3, "text": "Bleed the radiators", "status": "done"},
            {"id": 4, "text": "Clean the filter"},
        ]
        self.path.write_text(json.dumps(
            {"generated_at": now, "open": 4, "items": items}))
        asyncio.run(self.list.async_update())
        self.assertEqual([i.uid for i in self.list._attr_todo_items],
                         ["t:1", "t:4"])


class TestThePanelsSnoozeReachesTheMirror(unittest.TestCase):
    """Driven through the real server: Snooze on a To Do row (the case
    verb) takes it off the mirror, and the To Do count is the mirror's."""

    @classmethod
    def setUpClass(cls):
        import test_numbers_agree
        cls.Case = test_numbers_agree.ServerStoresCase

    def test_snooze_through_the_route_reaches_the_mirror_and_the_count(self):
        case = self.Case("run")
        case.setUpClass()
        case.setUp()
        try:
            server = case.server
            server.todo_store.STATE_FILE.parent.mkdir(parents=True,
                                                      exist_ok=True)
            server.todo_store.add("Change the hall battery")
            b = server.todo_store.add("Descale the kettle")
            ended = server.cases.end(f"t:{b['id']}", "not_now",
                                     hooks=server.CASE_HOOKS)
            self.assertIsNotNone(ended)
            server.todo_store.publish_state(True)
            got = json.loads(server.todo_store.STATE_FILE.read_text())
            self.assertEqual([i["text"] for i in got["items"]],
                             ["Change the hall battery"])
            self.assertEqual(server._counts()["list_count"], got["open"])
            self.assertEqual(server._todo_payload()["open"], 2)
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
