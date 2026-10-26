#!/usr/bin/env python3
"""History › Changes brAIn made: every change, newest first, each with an
Undo — or, where it cannot be put back, the reason why (#453).

The owner: "a running list of all the actions that brain has taken and
changes it made. Each action should have an undo button next to it. That
way if something happens autonomously it can easily be undone."

Two halves. `changes.build` is pure over the stores, so the rules — one row
per change, a name on every row, Undo or a reason, the newest of a pair the
only one undoable, a file changed since not brAIn's to put back, everything
inside a fix's window folded into that fix's own row — are driven over a
house's history written here. The routes are driven over the REAL writers:
the edit journal line out of `brain-edit-snapshot.py`'s own `main`, the
ledger row out of `ha_mcp_server.record_action`, and the file put back by
the real `automation_writer.revert`, because those halves agree by contract.
"""
from __future__ import annotations

import os
import re
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import actions  # noqa: E402
import automation_writer  # noqa: E402
import changes  # noqa: E402

from test_fix_plan import FixCase, journal_an_edit, record_a_call  # noqa: E402

NOW = 1_800_000_000.0
NAMES = {"light.porch": {"name": "Porch light"},
         "light.hall": {"name": "Hall lamp"},
         "lock.front": {"name": "Front door"}}
# An entity id in prose (a file name is a file name, said as one).
ID_RE = re.compile(r"\b(light|switch|lock|sensor|binary_sensor|automation|"
                   r"script|scene|climate|cover|fan|input_[a-z]+)\.[a-z0-9_]+\b")


def call(ts, domain="light", service="turn_off", entities=("light.porch",),
         before=True, channel="voice"):
    row = {"ts": ts, "domain": domain, "service": service,
           "entities": list(entities), "channel": channel}
    if before:
        row["before"] = {e: {"state": "on", "attributes": {}} for e in entities}
    return row


def build(**over):
    kw = dict(journal=[], ledger=[], fixes=[], tidy_batches=[], intents=[],
              accepted=[], names=NAMES, mtime=lambda p: None, now=NOW)
    kw.update(over)
    return changes.build(**kw)


class TestEveryRowIsReadable(unittest.TestCase):
    def test_every_kind_has_a_name_and_undo_or_a_reason(self):
        rows = build(
            journal=[{"ts": NOW - 50, "path": "/config/scripts.yaml",
                      "tool": "Edit", "snapshot": "x", "existed": True,
                      "channel": "chat"}],
            ledger=[call(NOW - 40), call(NOW - 30, "notify", "mobile_app_x", ())],
            tidy_batches=[{"id": "b1", "at": NOW - 20, "undone_at": 0,
                           "entries": [{"subject": "light.hall",
                                        "before": {}, "after": {}}]}],
            intents=[{"ts": 9, "status": "armed", "automation_id": "brain_x",
                      "title": "Porch off when guests leave",
                      "accepted_at": NOW - 10}],
            fixes=[{"ts": 7, "text": "The hall automation points at nothing",
                    "fix_started": NOW - 9, "fix_ended": NOW - 5}])
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["at"] for r in rows],
                         sorted((r["at"] for r in rows), reverse=True))
        for row in rows:
            self.assertTrue(row["title"].strip(), row)
            self.assertFalse(ID_RE.search(row["title"]), row["title"])
            self.assertTrue(bool(row["press"]) != bool(row["reason"]), row)
        by_kind = {r["kind"]: r for r in rows}
        self.assertEqual(by_kind["call"]["where"], "by voice")
        self.assertEqual(by_kind["edit"]["where"], "from the chat")
        self.assertIn("Porch light", [r["title"] for r in rows
                                      if r["kind"] == "call"][-1])
        self.assertEqual(by_kind["fix"]["press"]["steps"][0]["route"],
                         "/api/finding/7/unfix")
        self.assertEqual(by_kind["tidy"]["press"]["steps"][0]["route"],
                         "/api/tidy/undo/b1")
        self.assertEqual(by_kind["intent"]["press"]["steps"][0]["route"],
                         "/api/intent/9/remove")

    def test_a_message_cannot_be_unsent(self):
        [row] = build(ledger=[call(NOW, "notify", "mobile_app_x", ())])
        self.assertIsNone(row["press"])
        self.assertIn("cannot be unsent", row["reason"])


class TestOnlyWhatIsSafeIsOffered(unittest.TestCase):
    def test_the_newest_of_a_pair_is_the_one_undo_offers(self):
        rows = build(ledger=[call(NOW - 60), call(NOW - 10, service="turn_on")])
        newest, oldest = rows
        self.assertIsNotNone(newest["press"])
        self.assertIsNone(oldest["press"])
        self.assertIn("later change", oldest["reason"])
        edits = build(journal=[
            {"ts": NOW - 60, "path": "/config/a.yaml", "tool": "Edit",
             "snapshot": "1", "existed": True},
            {"ts": NOW - 10, "path": "/config/a.yaml", "tool": "Edit",
             "snapshot": "2", "existed": True}])
        self.assertIsNotNone(edits[0]["press"])
        self.assertIn("later change", edits[1]["reason"])

    def test_a_file_changed_since_is_not_put_back(self):
        [row] = build(journal=[{"ts": NOW - 3600, "path": "/config/a.yaml",
                                "tool": "Edit", "snapshot": "1",
                                "existed": True}],
                      mtime=lambda p: NOW - 60)
        self.assertIsNone(row["press"])
        self.assertIn("changed since", row["reason"])

    def test_a_lock_is_never_put_back_to_unlocked(self):
        locked = {"ts": NOW, "domain": "lock", "service": "lock",
                  "entities": ["lock.front"],
                  "before": {"lock.front": {"state": "unlocked",
                                            "attributes": {}}}}
        [row] = build(ledger=[locked])
        self.assertIsNone(row["press"])
        self.assertIn("less secure", row["reason"])

    def test_no_recorded_before_state_says_so(self):
        [row] = build(ledger=[call(NOW, before=False)])
        self.assertIsNone(row["press"])
        self.assertIn("did not record", row["reason"])

    def test_a_fixs_own_edits_and_calls_are_its_row(self):
        rows = build(
            fixes=[{"ts": 7, "text": "Hall", "fix_started": NOW - 100,
                    "fix_ended": NOW - 50}],
            journal=[{"ts": NOW - 80, "path": "/config/automations.yaml",
                      "tool": "Edit", "snapshot": "x", "existed": True}],
            ledger=[call(NOW - 70)])
        self.assertEqual([r["kind"] for r in rows], ["fix"])

    def test_an_accepted_suggestion_is_named_and_a_one_off_is_once(self):
        rows = build(
            journal=[{"ts": NOW - 100, "path": "/config/automations.yaml",
                      "tool": automation_writer.TOOL, "snapshot": "x",
                      "existed": True},
                     {"ts": NOW - 50, "path": "/config/automations.yaml",
                      "tool": automation_writer.TOOL, "snapshot": "y",
                      "existed": True}],
            accepted=[{"status": "accepted", "title": "Porch light off at 23:10",
                       "settled_at": NOW - 98, "automation_id": "brain_a"},
                      {"status": "accepted", "title": "One-off",
                       "settled_at": NOW - 48, "automation_id": "brain_once"}],
            intents=[{"ts": 3, "status": "armed", "automation_id": "brain_once",
                      "title": "One-off", "accepted_at": NOW - 48}])
        titles = [r["title"] for r in rows]
        self.assertIn("Added “Porch light off at 23:10”", titles)
        self.assertEqual(sum("One-off" in t for t in titles), 1)

    def test_older_than_the_window_is_not_listed(self):
        self.assertEqual(build(ledger=[call(NOW - 40 * 86400)]), [])

    def test_a_page_is_newest_first_and_says_there_is_more(self):
        rows = build(ledger=[call(NOW - i, entities=(f"light.l{i}",))
                             for i in range(1, 8)])
        page = changes.page(rows, 3)
        self.assertEqual(page["total"], 7)
        self.assertTrue(page["more"])
        nxt = changes.page(rows, 3, before=page["rows"][-1]["at"])
        self.assertLess(nxt["rows"][0]["at"], page["rows"][-1]["at"])


class TestTheRoutes(FixCase):
    def setUp(self):
        super().setUp()
        s = self.server
        tmp = Path(self.tmp.name)
        self._change_olds = (s.tidy.STORE, s.intents.STORE,
                             s.proposals.SETTLED_FILE, s.security.HONEYTOKEN_FILE)
        s.tidy.STORE = str(tmp / "tidy.json")
        s.intents.STORE = tmp / "intents.json"
        s.proposals.SETTLED_FILE = tmp / "proposals-settled.json"
        s.security.HONEYTOKEN_FILE = tmp / "honeytoken.json"

    def tearDown(self):
        s = self.server
        (s.tidy.STORE, s.intents.STORE, s.proposals.SETTLED_FILE,
         s.security.HONEYTOKEN_FILE) = self._change_olds
        super().tearDown()

    def test_the_hook_names_the_face_that_asked(self):
        target = self.config / "scripts.yaml"
        target.write_text("a: 1\n", encoding="utf-8")
        os.environ["BRAIN_CHANNEL"] = "chat"
        try:
            journal_an_edit(target)
        finally:
            os.environ.pop("BRAIN_CHANNEL", None)
        rows = self.server._changes_rows()
        self.assertEqual(rows[0]["where"], "from the chat")
        self.assertEqual(rows[0]["title"], "Edited scripts.yaml")

    def test_undo_puts_the_file_back_through_the_one_reverter(self):
        target = self.config / "scripts.yaml"
        target.write_text("before: 1\n", encoding="utf-8")
        journal_an_edit(target)
        target.write_text("after: 1\n", encoding="utf-8")
        reloads = []

        async def body(client):
            import ha_data
            old = ha_data.call_core_service

            async def fake(domain, service, data=None):
                reloads.append((domain, service))
                return {}

            ha_data.call_core_service = fake
            try:
                listed = await (await client.get("/api/changes")).json()
                [row] = listed["rows"]
                self.assertEqual(listed["label"], "Changes brAIn made")
                route = row["press"]["steps"][0]["route"]
                answer = await client.post(route)
                self.assertEqual(answer.status, 200, await answer.text())
                return await answer.json()
            finally:
                ha_data.call_core_service = old

        out = self.drive(body)
        self.assertEqual(target.read_text(), "before: 1\n")
        self.assertEqual(reloads, [("script", "reload")])
        self.assertIn("scripts.yaml", out["text"])

    def test_a_row_with_no_undo_is_refused_by_the_route_too(self):
        target = self.config / "scripts.yaml"
        target.write_text("v: 0\n", encoding="utf-8")
        journal_an_edit(target)
        first = float(automation_writer.INDEX.read_text().splitlines()[0]
                      .split('"ts": ')[1].split(",")[0])
        time.sleep(0.01)
        journal_an_edit(target)

        async def body(client):
            answer = await client.post(f"/api/changes/edit/{first:.6f}/undo")
            return answer.status, await answer.text()

        status, text = self.drive(body)
        self.assertEqual(status, 409)
        self.assertIn("later change", text)

    def test_undo_restores_a_call_off_its_recorded_before_state(self):
        record_a_call(self.ledger, "light", "turn_off",
                      {"entity_id": "light.porch"})
        # The MCP server's own writer, driven here without the before-state
        # its chokepoint reads first: the row says it cannot be put back —
        # never a guess.
        rows = self.server._changes_rows()
        [row] = [r for r in rows if r["kind"] == "call"]
        self.assertIsNone(row["press"])
        self.assertIn("did not record how it was before", row["reason"])
        # With a before-state on the row, Undo is the restore press.
        line = {"ts": time.time(), "domain": "light", "service": "turn_off",
                "entities": ["light.porch"], "channel": "voice",
                "before": {"light.porch": {"state": "on", "attributes": {}}}}
        with open(actions.LEDGER_FILE, "a", encoding="utf-8") as fh:
            fh.write(__import__("json").dumps(line) + "\n")
        applied = []

        async def body(client):
            import ha_data
            olds = (ha_data.call_core_service, ha_data.entity_state,
                    self.server.RESTORE_SETTLE_S)

            async def fake_call(domain, service, data=None):
                applied.append((domain, service, data))
                return {}

            async def fake_state(eid):
                return {"entity_id": eid, "state": "on", "attributes": {}}

            ha_data.call_core_service = fake_call
            ha_data.entity_state = fake_state
            self.server.RESTORE_SETTLE_S = 0
            try:
                listed = await (await client.get("/api/changes")).json()
                newest = listed["rows"][0]
                self.assertEqual(newest["kind"], "call")
                answer = await client.post(newest["press"]["steps"][0]["route"])
                self.assertEqual(answer.status, 200, await answer.text())
                return await answer.json()
            finally:
                (ha_data.call_core_service, ha_data.entity_state,
                 self.server.RESTORE_SETTLE_S) = olds

        out = self.drive(body)
        self.assertEqual(applied[0][:2], ("scene", "apply"))
        self.assertEqual(applied[0][2]["entities"]["light.porch"]["state"], "on")
        self.assertTrue(out["restored"][0]["restored"])


if __name__ == "__main__":
    unittest.main()
