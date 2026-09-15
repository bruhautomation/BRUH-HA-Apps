#!/usr/bin/env python3
"""The to-do list — accepted work, and the card it stopped being.

Every ending a finding had was a decision made on the spot. The one
people actually give most often — *yes, that is real, and I will do it*
— had nowhere to go, so the Findings tab, which is a list of decisions
waiting on somebody, filled up with chores instead.

What is pinned here is the shape of that fourth ending and the two ways
it differs from the three that were already there:

  * it writes NO memory line, because nothing is true yet. The battery
    is still flat. The line is written when the chore is done.
  * it settles the key anyway, as `accepted`, because a report you have
    agreed to act on must not be raised at you again while it waits.

...plus the reversals, which have to put back every half of that or none
of it, and the two front doors landing on one implementation.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import todo_store  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (todo_store.TODO_FILE, todo_store.STATE_FILE)
        todo_store.TODO_FILE = base / "todo.json"
        # Its parent's parent has to be absent, or `publish_state` writes a
        # stray mirror — the findings store's own dev-checkout rule.
        todo_store.STATE_FILE = base / "nowhere" / ".brain" / "todo_state.json"

    def tearDown(self):
        todo_store.TODO_FILE, todo_store.STATE_FILE = self._old
        self.tmp.cleanup()


class TestTheStore(StoreCase):
    def test_an_item_carries_the_evidence_rather_than_a_pointer(self):
        """The finding row is deleted by the move, so a reference dangles."""
        item = todo_store.add(
            "Hall sensor has not reported since 3 Sep",
            detail="last seen 3 Sep", fix="Re-pair it",
            entity_id="binary_sensor.hall", severity="serious",
            origin="finding", source="check:devices", source_title="Checks",
            finding_key="hall sensor has not reported since 3 sep")
        self.assertIsNotNone(item)
        stored = todo_store.get(item["id"])
        for field, value in (("detail", "last seen 3 Sep"),
                             ("fix", "Re-pair it"),
                             ("entity_id", "binary_sensor.hall"),
                             ("severity", "serious"),
                             ("source_title", "Checks")):
            self.assertEqual(stored[field], value, field)

    def test_a_millisecond_is_not_an_id(self):
        """`proposals.add`'s bug, not repeated in the sibling that came after.

        A loop of adds lands several inside one millisecond, and two rows
        under one id means the second press answers the first item. The
        old recipe is run first so the failure is demonstrated rather than
        described.
        """
        frozen = 1_700_000_000.0            # one instant, eight adds
        naive = {int(frozen * 1000) for _ in range(8)}
        self.assertEqual(len(naive), 1, "the old recipe, demonstrated")

        ids = [todo_store.add(f"chore {i}", now=frozen)["id"] for i in range(8)]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(ids, sorted(ids))

    def test_the_list_is_worst_first_then_oldest(self):
        now = time.time()
        todo_store.add("a warning", severity="warning", now=now)
        todo_store.add("a critical", severity="critical", now=now + 1)
        todo_store.add("an older warning", severity="warning", now=now - 500)
        listed = todo_store.listing()
        self.assertEqual([i["text"] for i in listed["items"]],
                         ["a critical", "an older warning", "a warning"])
        self.assertEqual(listed["open"], 3)

    def test_a_finished_chore_leaves_the_count_and_not_the_store(self):
        """A chore list that forgets what you did cannot answer "did I".

        Which is a different question from the Findings tab's, where
        settling deletes the row because memory is the record of a
        decision. This is a list of chores.
        """
        item = todo_store.add("empty the dehumidifier")
        todo_store.complete(item["id"], note="done Tuesday")
        listed = todo_store.listing()
        self.assertEqual(listed["items"], [])
        self.assertEqual(listed["open"], 0)
        self.assertEqual([i["text"] for i in listed["done"]],
                         ["empty the dehumidifier"])
        self.assertEqual(listed["done"][0]["note"], "done Tuesday")
        self.assertTrue(listed["done"][0]["done_at"])

    def test_completing_twice_is_the_same_completion(self):
        item = todo_store.add("x")
        first = todo_store.complete(item["id"], note="once")
        again = todo_store.complete(item["id"], note="twice")
        self.assertEqual(again["note"], first["note"])
        self.assertEqual(len(todo_store.listing()["done"]), 1)

    def test_restoring_over_an_occupied_id_is_refused(self):
        """`findings_store.restore`'s rule: something newer holds it."""
        item = todo_store.add("x")
        todo_store.remove(item["id"])
        self.assertIsNotNone(todo_store.restore(item))
        self.assertIsNone(todo_store.restore(item))

    def test_a_blank_line_is_not_a_chore(self):
        self.assertIsNone(todo_store.add("   "))
        self.assertEqual(todo_store.listing()["open"], 0)

    def test_the_cap_refuses_rather_than_making_room(self):
        """Making room means dropping something somebody else put there."""
        for i in range(todo_store.MAX_OPEN):
            self.assertIsNotNone(todo_store.add(f"chore {i}"))
        self.assertIsNone(todo_store.add("one too many"))
        self.assertEqual(todo_store.listing()["open"], todo_store.MAX_OPEN)

    def test_finished_chores_are_capped_and_open_ones_never_are(self):
        keep = [todo_store.add(f"done {i}") for i in range(todo_store.MAX_DONE + 5)]
        for n, item in enumerate(keep):
            todo_store.complete(item["id"], now=time.time() + n)
        live = todo_store.add("still to do")
        listed = todo_store.listing()
        self.assertEqual(listed["done_count"], todo_store.MAX_DONE)
        self.assertEqual([i["text"] for i in listed["items"]], ["still to do"])
        self.assertIsNotNone(todo_store.get(live["id"]))

    def test_the_mirror_is_skipped_on_a_dev_checkout(self):
        """A test run must not grow a stray /config — the findings rule."""
        todo_store.add("x")
        self.assertFalse(todo_store.STATE_FILE.exists())

    def test_the_mirror_carries_the_open_list(self):
        todo_store.STATE_FILE.parent.parent.mkdir(parents=True)
        item = todo_store.add("replace the smoke alarm battery")
        todo_store.complete(todo_store.add("something finished")["id"])
        published = json.loads(todo_store.STATE_FILE.read_text())
        self.assertEqual(published["open"], 1)
        self.assertEqual([i["id"] for i in published["items"]], [item["id"]])


class TestTheSettledLedger(unittest.TestCase):
    """`accepted` is a third kind, and it is a different claim from both."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE, findings_store.INBOX_DIR)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "nowhere" / ".brain" / "s.json"
        findings_store.INBOX_DIR = base / "inbox"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, findings_store.INBOX_DIR) = self._old
        self.tmp.cleanup()

    def _file(self, text="the hall sensor is stuck"):
        entry, _created = findings_store.add(
            text, severity="warning", source="check:devices",
            source_title="Device checks")
        self.assertIsNotNone(entry, text)
        return entry

    def test_accepting_suppresses_the_report_while_it_waits(self):
        row = self._file()
        findings_store.settle_and_clear(row["ts"], "accepted")
        self.assertEqual(findings_store.listing()["findings"], [])
        self.assertTrue(findings_store.is_known(row["text"]))

    def test_accepting_scores_as_the_report_being_right(self):
        """Agreeing to do something is agreeing it was real.

        Counting it as nothing until the chore is finished would make a
        producer look worse the more of its reports people took
        seriously and had not got round to.
        """
        for n in range(3):
            row = self._file(f"something wrong number {n}")
            findings_store.settle_and_clear(row["ts"], "accepted")
        score = {r["source"]: r for r in findings_store.scorecard()}
        self.assertEqual(score["check:devices"]["confirmed"], 3)
        self.assertEqual(score["check:devices"]["wrong"], 0)

    def test_finishing_upgrades_the_entry_rather_than_adding_one(self):
        """One problem stays one row of the scorecard."""
        row = self._file()
        key = findings_store.normalize(row["text"])
        findings_store.settle_and_clear(row["ts"], "accepted")
        self.assertTrue(findings_store.remember_answer(
            key, row["text"], "fixed", source="check:devices",
            source_title="Device checks"))
        ledger = findings_store.settled_listing()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["kind"], "fixed")
        self.assertEqual({r["source"]: r["total"]
                          for r in findings_store.scorecard()},
                         {"check:devices": 1})

    def test_an_answer_keys_on_what_the_item_stored(self):
        """Never on a second derivation from a copy of the text.

        The two agree right up until they do not, and the item is the
        only thing that still knows which entry it settled.
        """
        row = self._file()
        findings_store.settle_and_clear(row["ts"], "accepted")
        findings_store.remember_answer(
            "a key nothing would derive", row["text"], "fixed")
        keys = {e["key"] for e in findings_store.settled_listing()}
        self.assertIn("a key nothing would derive", keys)
        self.assertIn(findings_store.normalize(row["text"]), keys)

    def test_a_settlement_it_does_not_know_is_refused(self):
        row = self._file()
        with self.assertRaises(ValueError):
            findings_store.settle_and_clear(row["ts"], "parked")

    def test_remember_answer_says_no_rather_than_nothing(self):
        for args in ((("", "text", "fixed")), (("k", "", "fixed")),
                     (("k", "text", "parked"))):
            self.assertFalse(findings_store.remember_answer(*args), args)


class PanelCase(unittest.TestCase):
    """The routes, over a real client. `test_panel_edits`' harness."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import settings_store
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (
            findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
            findings_store.STATE_FILE, findings_store.INBOX_DIR,
            todo_store.TODO_FILE, todo_store.STATE_FILE,
            self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
            self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
            settings_store.SETTINGS_FILE, engine.run_claude,
        )
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.SETTLED_FILE = tmp / "settled.json"
        findings_store.STATE_FILE = tmp / "nowhere" / ".brain" / "s.json"
        findings_store.INBOX_DIR = tmp / "findings-inbox"
        todo_store.TODO_FILE = tmp / "todo.json"
        todo_store.STATE_FILE = tmp / "nowhere" / ".brain" / "todo.json"
        self.server.INSIGHTS_DIR = tmp
        self.server.MEMORY_INBOX_DIR = tmp / "memory-inbox"
        self.server.CARD_TOKEN_FILE = tmp / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = tmp / "www" / "brain"
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True})
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        import engine
        import settings_store
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, findings_store.INBOX_DIR,
         todo_store.TODO_FILE, todo_store.STATE_FILE,
         self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
         self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
         settings_store.SETTINGS_FILE, engine.run_claude) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def file_finding(self, text="the hall sensor is stuck"):
        entry, _created = findings_store.add(
            text, severity="warning", detail="last seen 3 Sep",
            fix="Re-pair it", entity_id="binary_sensor.hall",
            source="check:devices", source_title="Device checks")
        return entry

    def queued_memory(self) -> list[str]:
        """Every line waiting in the memory inbox, as plain text."""
        out = []
        for path in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                if line.strip():
                    out.append(json.loads(line).get("fact", ""))
        return out

    def drive(self, body):
        """Run one coroutine against a live client."""
        async def run():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(run())


class TestTheFourthEnding(PanelCase):
    def test_accepting_clears_the_card_and_puts_it_on_the_list(self):
        row = self.file_finding()

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/todo")
            self.assertEqual(res.status, 200)
            return await res.json()

        payload = self.drive(body)
        # Off the Findings tab entirely — the whole point of the press.
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["open"], 0)
        # ...and on the other list, carrying the card's own evidence.
        added = payload["added"]
        self.assertEqual(added["text"], row["text"])
        self.assertEqual(added["detail"], "last seen 3 Sep")
        self.assertEqual(added["fix"], "Re-pair it")
        self.assertEqual(added["origin"], "finding")
        self.assertEqual(added["source_title"], "Device checks")
        self.assertEqual(todo_store.listing()["open"], 1)

    def test_accepting_writes_no_memory_line(self):
        """Nothing is true yet. The battery is still flat."""
        row = self.file_finding()
        self.drive(lambda c: c.post(f"/api/finding/{row['ts']}/todo"))
        self.assertEqual(self.queued_memory(), [])

    def test_accepting_stops_it_being_raised_again_while_it_waits(self):
        row = self.file_finding()
        self.drive(lambda c: c.post(f"/api/finding/{row['ts']}/todo"))
        self.assertTrue(findings_store.is_known(row["text"]))
        # The producer re-reporting it changes nothing: the ledger is
        # what `add_many` dedupes against, across every status.
        again, created = findings_store.add(row["text"], severity="warning")
        self.assertFalse(created)
        self.assertEqual(findings_store.listing()["findings"], [])

    def test_a_list_that_is_full_leaves_the_finding_alone(self):
        """A finding that vanished into a list which refused it has no way
        back, so nothing is settled and nothing is deleted."""
        for i in range(todo_store.MAX_OPEN):
            todo_store.add(f"chore {i}")
        row = self.file_finding()

        async def body(client):
            return await client.post(f"/api/finding/{row['ts']}/todo")

        self.assertEqual(self.drive(body).status, 409)
        self.assertEqual(len(findings_store.listing()["findings"]), 1)
        self.assertFalse(findings_store.settled_listing())

    def test_finishing_writes_the_line_the_move_did_not(self):
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/todo")
            item = todo_store.listing()["items"][0]
            res = await client.post(f"/api/todo/{item['id']}/done",
                                    json={"note": "replaced the CR2032"})
            self.assertEqual(res.status, 200)
            return await res.json()

        payload = self.drive(body)
        self.assertEqual(payload["open"], 0)
        self.assertEqual(len(payload["done"]), 1)
        facts = self.queued_memory()
        self.assertEqual(len(facts), 1)
        self.assertIn(row["text"], facts[0])
        self.assertIn("replaced the CR2032", facts[0])
        # ...and the ledger says `fixed` now rather than `accepted`.
        ledger = findings_store.settled_listing()
        self.assertEqual([e["kind"] for e in ledger], ["fixed"])

    def test_dropping_one_undone_puts_the_problem_back_in_play(self):
        """Deciding not to do it is not evidence it stopped being true."""
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/todo")
            item = todo_store.listing()["items"][0]
            res = await client.delete(f"/api/todo/{item['id']}")
            return await res.json()

        payload = self.drive(body)
        self.assertTrue(payload["unsettled"])
        self.assertFalse(findings_store.is_known(row["text"]))
        # So the next pass is free to file it again, which is
        # `clear_resolved`'s own argument: if it really is over, nothing
        # comes back.
        _entry, created = findings_store.add(row["text"], severity="warning")
        self.assertTrue(created)

    def test_a_hand_added_chore_releases_nothing(self):
        """It carries no key, because no report was ever suppressed for it."""
        async def body(client):
            res = await client.post(
                "/api/todo", json={"text": "re-pair the bedroom blind"})
            self.assertEqual(res.status, 200)
            item = (await res.json())["added"]
            self.assertEqual(item["origin"], "hand")
            drop = await client.delete(f"/api/todo/{item['id']}")
            return await drop.json()

        payload = self.drive(body)
        self.assertFalse(payload["unsettled"])

    def test_an_empty_chore_is_refused(self):
        async def body(client):
            return await client.post("/api/todo", json={"text": "  "})

        self.assertEqual(self.drive(body).status, 400)

    def test_putting_a_finished_one_back_keeps_the_memory_line(self):
        """It was written when you said it was done; a consolidation may
        have filed it since, and editing the document is the only honest
        correction once it has."""
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/todo")
            item = todo_store.listing()["items"][0]
            await client.post(f"/api/todo/{item['id']}/done")
            res = await client.post(f"/api/todo/{item['id']}/reopen")
            return await res.json()

        payload = self.drive(body)
        self.assertEqual(payload["open"], 1)
        self.assertEqual(payload["done"], [])
        self.assertEqual(len(self.queued_memory()), 1)
        # ...and the ledger is back to `accepted`, because it is waiting.
        self.assertEqual([e["kind"] for e in findings_store.settled_listing()],
                         ["accepted"])

    def test_an_item_that_is_gone_is_a_404_and_not_a_crash(self):
        async def body(client):
            return [(await client.post("/api/todo/999/done")).status,
                    (await client.delete("/api/todo/999")).status,
                    (await client.post("/api/todo/nope/done")).status]

        self.assertEqual(self.drive(body), [404, 404, 404])


class TestPuttingItBack(PanelCase):
    """Each press is reversed whole or not at all.

    Half of an accept undone is the same chore twice or work that has
    silently disappeared, which is why one token carries both halves.
    """

    def test_undoing_an_accept_takes_the_item_and_returns_the_card(self):
        row = self.file_finding()

        async def body(client):
            token = (await (await client.post(
                f"/api/finding/{row['ts']}/todo")).json())["undo"]
            res = await client.post(f"/api/undo/{token}")
            return await res.json()

        payload = self.drive(body)
        self.assertTrue(payload["undone"])
        self.assertEqual(todo_store.listing()["open"], 0)
        self.assertEqual([f["text"] for f in findings_store.listing()["findings"]],
                         [row["text"]])
        # The suppression goes with it. `is_known` stays true — the row is
        # back on the list, which is what it is for — so the claim worth
        # making is about the ledger, which is what would outlive the row.
        self.assertEqual(findings_store.settled_listing(), [])

    def test_undoing_an_accept_whose_item_has_moved_on_puts_nothing_back(self):
        """Ticked off or dropped in the meantime: restoring the row would
        be the same work twice."""
        row = self.file_finding()

        async def body(client):
            token = (await (await client.post(
                f"/api/finding/{row['ts']}/todo")).json())["undo"]
            item = todo_store.listing()["items"][0]
            await client.delete(f"/api/todo/{item['id']}")
            res = await client.post(f"/api/undo/{token}")
            return await res.json()

        payload = self.drive(body)
        self.assertFalse(payload["undone"])
        self.assertIn("error", payload)

    def test_undoing_a_completion_takes_the_memory_line_back(self):
        """The token is younger than any consolidation pass, which is
        exactly what makes this reversible."""
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/todo")
            item = todo_store.listing()["items"][0]
            token = (await (await client.post(
                f"/api/todo/{item['id']}/done",
                json={"note": "did it"})).json())["undo"]
            res = await client.post(f"/api/undo/{token}")
            return await res.json()

        payload = self.drive(body)
        self.assertTrue(payload["undone"])
        self.assertEqual(payload["open"], 1)
        self.assertEqual(self.queued_memory(), [])
        self.assertEqual([e["kind"] for e in findings_store.settled_listing()],
                         ["accepted"])

    def test_undoing_a_drop_restores_the_item_and_the_suppression(self):
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/todo")
            item = todo_store.listing()["items"][0]
            token = (await (await client.delete(
                f"/api/todo/{item['id']}")).json())["undo"]
            res = await client.post(f"/api/undo/{token}")
            return await res.json()

        payload = self.drive(body)
        self.assertTrue(payload["undone"])
        self.assertEqual(payload["open"], 1)
        self.assertTrue(findings_store.is_known(row["text"]))

    def test_a_token_is_taken_once(self):
        row = self.file_finding()

        async def body(client):
            token = (await (await client.post(
                f"/api/finding/{row['ts']}/todo")).json())["undo"]
            first = await client.post(f"/api/undo/{token}")
            second = await client.post(f"/api/undo/{token}")
            return first.status, second.status

        self.assertEqual(self.drive(body), (200, 404))


class TestTheTwoDoors(PanelCase):
    """A tick in the To-do app and the tab's own button are one path.

    `_end_finding`'s rule, one store over: "done" is three things, and a
    second implementation would be the same press teaching brAIn two
    different things depending on where it was made.
    """

    def _apply(self, request: dict):
        import finding_requests
        self._req_old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = Path(self.tmp.name) / "requests"
        finding_requests.REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        (finding_requests.REQUEST_DIR / "0000000000001-000000-aa.json").write_text(
            json.dumps(request), encoding="utf-8")
        try:
            return asyncio.run(self.server._apply_finding_requests())
        finally:
            finding_requests.REQUEST_DIR = self._req_old

    def test_a_tick_elsewhere_finishes_it_exactly_as_the_button_does(self):
        row = self.file_finding()
        self.drive(lambda c: c.post(f"/api/finding/{row['ts']}/todo"))
        item = todo_store.listing()["items"][0]

        results = self._apply({"kind": "todo", "action": "done",
                               "id": item["id"], "note": "sorted it",
                               "via": "todo"})
        self.assertEqual([r["ok"] for r in results], [True])
        self.assertEqual(todo_store.listing()["open"], 0)
        facts = self.queued_memory()
        self.assertEqual(len(facts), 1)
        self.assertIn("sorted it", facts[0])
        self.assertEqual([e["kind"] for e in findings_store.settled_listing()],
                         ["fixed"])

    def test_a_drop_elsewhere_releases_the_suppression_too(self):
        row = self.file_finding()
        self.drive(lambda c: c.post(f"/api/finding/{row['ts']}/todo"))
        item = todo_store.listing()["items"][0]
        self._apply({"kind": "todo", "action": "drop", "id": item["id"]})
        self.assertFalse(findings_store.is_known(row["text"]))

    def test_an_add_from_elsewhere_lands_on_the_same_list(self):
        results = self._apply({"kind": "todo", "action": "add",
                               "text": "replace the smoke alarm battery"})
        self.assertEqual([r["ok"] for r in results], [True])
        listed = todo_store.listing()
        self.assertEqual([i["text"] for i in listed["items"]],
                         ["replace the smoke alarm battery"])
        self.assertEqual(listed["items"][0]["origin"], "hand")

    def test_a_request_about_an_item_that_is_gone_is_an_ordinary_race(self):
        """Somebody's phone was a few seconds out of date."""
        results = self._apply({"kind": "todo", "action": "done", "id": 999})
        self.assertEqual([r["ok"] for r in results], [False])
        self.assertEqual(results[0]["why"], "no such item")

    def test_a_request_that_could_never_be_applied_is_not_a_request(self):
        import finding_requests
        for bad in ({"kind": "todo", "action": "done"},          # no id
                    {"kind": "todo", "action": "add", "text": ""},
                    {"kind": "todo", "action": "park", "id": 1}):
            self.assertIsNone(finding_requests.parse(bad), bad)
        # ...and one with no `kind` at all is a finding's, which is what
        # every request written before this list existed looks like.
        self.assertEqual(
            finding_requests.parse({"ts": 5, "action": "fixed"})["action"],
            "fixed")


if __name__ == "__main__":
    unittest.main()
