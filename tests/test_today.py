#!/usr/bin/env python3
"""Today's own store: the snooze and ignore for the two cards no store owns,
and the History drawer (`panel/today.py`).

What is driven, and against what:

  * `hide` / `restore` / `hidden` over a real file in a temp directory: a
    snooze lapses on its date, an ignore and a listing do not, a key or a
    word the module does not know is refused, and an unreadable file hides
    nothing (the direction in which being wrong shows a card);
  * `tidy_key` / `update_key`: a NEW table or a NEWER version is a
    different card, so last month's ignore cannot hide this month's;
  * `history`: the four filters, each row's one press, the duplicate
    folded into one row with its count and its first date, a card put on
    To Do kept out of History, an `accepted` ending kept out too, and
    Undo carrying the sentence that says what it puts back;
  * the server's `_today_cards` and `_queue_count`: a hidden card leaves
    both, so the badge and the queue cannot disagree about it.
"""

import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import today  # noqa: E402

NOW = 1_800_000_000.0


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = unittest.mock.patch.object(today, "HIDDEN_FILE",
                                    Path(self.tmp.name) / "today-hidden.json")
        patcher.start()
        self.addCleanup(patcher.stop)


class TestHide(_Store):
    def test_a_snooze_lapses_on_its_date(self):
        row = today.hide("tidy:1700000000", "snoozed", "Tidy 4 names", now=NOW)
        self.assertEqual(row["until"], int(NOW + today.SNOOZE_S))
        self.assertTrue(today.is_hidden("tidy:1700000000", now=NOW + 60))
        self.assertFalse(today.is_hidden("tidy:1700000000", now=NOW + today.SNOOZE_S + 1))

    def test_an_ignore_and_a_listing_do_not_lapse(self):
        today.hide("update:update.core:2026.10.2", "ignored", now=NOW)
        today.hide("update:update.os:16.3", "listed", now=NOW)
        later = NOW + 400 * 86400
        self.assertTrue(today.is_hidden("update:update.core:2026.10.2", now=later))
        self.assertTrue(today.is_hidden("update:update.os:16.3", now=later))

    def test_what_it_does_not_know_is_refused(self):
        self.assertIsNone(today.hide("f:12", "snoozed", now=NOW))
        self.assertIsNone(today.hide("tidy:1", "dismissed", now=NOW))
        self.assertIsNone(today.hide("tidy:1; rm -rf /", "ignored", now=NOW))
        self.assertEqual(today.hidden(NOW), {})

    def test_restore_puts_one_back_and_says_when_nothing_was_hidden(self):
        today.hide("tidy:5", "ignored", now=NOW)
        self.assertTrue(today.restore("tidy:5"))
        self.assertFalse(today.is_hidden("tidy:5", now=NOW))
        self.assertFalse(today.restore("tidy:5"))

    def test_an_unreadable_file_hides_nothing(self):
        today.HIDDEN_FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(today.hidden(NOW), {})
        today.HIDDEN_FILE.write_text('{"hidden": {"tidy:1": {"how": "vanish"}}}',
                                     encoding="utf-8")
        self.assertEqual(today.hidden(NOW), {})


class TestKeys(unittest.TestCase):
    def test_a_new_table_and_a_newer_version_are_different_cards(self):
        self.assertNotEqual(today.tidy_key({"at": 1}), today.tidy_key({"at": 2}))
        self.assertEqual(today.tidy_key({}), "")
        a = today.update_key({"entity_id": "update.core", "latest": "2026.10.2"})
        b = today.update_key({"entity_id": "update.core", "latest": "2026.10.3"})
        self.assertNotEqual(a, b)
        self.assertTrue(today.KEY_RE.match(a))
        self.assertEqual(today.update_key({"latest": "1"}), "")


class TestHistory(unittest.TestCase):
    def build(self, **over):
        args = dict(findings=[], settled=[], muted=[], snoozed_cases=[],
                    todo_done=[], tidy_batches=[], hidden_rows={}, now=NOW)
        args.update(over)
        return today.history(**args)

    def test_four_filters_in_order_with_counts(self):
        out = self.build(settled=[{"kind": "ignored", "text": "Fan ran long",
                                   "ts": NOW - 86400, "key": "k1"}])
        self.assertEqual([f["id"] for f in out["filters"]],
                         ["snoozed", "ignored", "done", "aside"])
        self.assertEqual([f["label"] for f in out["filters"]],
                         ["Snoozed", "Ignored", "Done", "Set aside by brAIn"])
        self.assertEqual([f["count"] for f in out["filters"]], [0, 1, 0, 0])

    def test_a_duplicate_is_one_row_with_its_count_and_first_date(self):
        cases = [{"id": f"f:{i}", "claim": "Cooling time yesterday",
                  "created_at": int(NOW - i * 86400), "snoozed_until": int(NOW + 86400)}
                 for i in range(6)]
        out = self.build(snoozed_cases=cases)
        rows = out["rows"]["snoozed"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 6)
        self.assertTrue(rows[0]["meta"].startswith("6 times since "))
        self.assertEqual(rows[0]["press"]["label"], "Restore")
        self.assertEqual(len(rows[0]["press"]["steps"]), 6)
        self.assertEqual(rows[0]["press"]["steps"][0]["route"], "/api/case/f:0/wake")

    def test_listed_and_accepted_are_not_history(self):
        out = self.build(
            hidden_rows={"update:update.core:1": {"how": "listed", "until": 0,
                                                  "at": int(NOW), "title": "Core"}},
            settled=[{"kind": "accepted", "text": "Battery low", "ts": NOW, "key": "k"}])
        self.assertTrue(all(not rows for rows in out["rows"].values()))

    def test_each_kind_lands_in_its_filter_with_its_own_press(self):
        out = self.build(
            settled=[{"kind": "ignored", "text": "A", "ts": NOW, "key": "ka",
                      "note": "it is on a timer"},
                     {"kind": "fixed", "text": "B", "ts": NOW, "key": "kb"}],
            muted=[{"source": "check:dev.frozen", "title": "Sensors frozen on one value"}],
            todo_done=[{"id": 3, "text": "Descale the kettle", "done_at": NOW}],
            tidy_batches=[{"id": "b1", "at": NOW, "entries": [{}, {}]}],
            findings=[{"ts": 7, "status": "held", "text": "Heating ran 14 hours",
                       "triage": {"reason": "a routine summary", "at": NOW}}],
            hidden_rows={"tidy:9": {"how": "snoozed", "until": int(NOW + 3 * 86400),
                                    "at": int(NOW), "title": "Tidy 4 names"}})
        routes = {name: [s["route"] for r in rows for s in r["press"]["steps"]]
                  for name, rows in out["rows"].items()}
        self.assertIn("/api/today/restore", routes["snoozed"])
        self.assertIn("/api/findings/unsettle", routes["ignored"])
        self.assertIn("/api/findings/unmute", routes["ignored"])
        self.assertIn("/api/todo/3/reopen", routes["done"])
        self.assertIn("/api/tidy/undo/b1", routes["done"])
        self.assertEqual(routes["aside"], ["/api/finding/7/elevate"])
        ignored = {r["title"]: r for r in out["rows"]["ignored"]}
        self.assertIn("You said: it is on a timer", ignored["A"]["meta"])
        tidied = next(r for r in out["rows"]["done"] if r["title"].startswith("Tidied"))
        self.assertEqual(tidied["press"]["label"], "Undo")
        self.assertIn("Puts back each field", tidied["press"]["steps"][0]["confirm"])


class TestTheQueueCountsTodaysOwnCards(_Store):
    """A hidden card leaves the queue and the count together."""

    def setUp(self):
        super().setUp()
        import server
        self.server = server
        self.today = server.today_mod
        patch = unittest.mock.patch.object(self.today, "HIDDEN_FILE", today.HIDDEN_FILE)
        patch.start()
        self.addCleanup(patch.stop)
        proposal = {"at": 1700000000, "rows": [{"id": "r0"}]}
        update = {"entity_id": "update.core", "latest": "2026.10.2",
                  "advice": {"verdict": "safe_tonight"}}
        for target, attr, value in (
            (server.tidy, "load", lambda: {"proposal": proposal}),
            (server.upgrades, "listing", lambda rows: [update]),
            (server.cases, "queue_count", lambda now=None: 4),
        ):
            p = unittest.mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def test_both_cards_count_until_hidden(self):
        cards = self.server._today_cards(NOW)
        self.assertEqual(cards["tidy"]["key"], "tidy:1700000000")
        self.assertEqual(len(cards["updates"]), 1)
        self.assertEqual(self.server._queue_count(NOW), 6)
        self.today.hide("tidy:1700000000", "snoozed", now=NOW)
        self.today.hide(cards["updates"][0]["key"], "listed", now=NOW)
        self.assertIsNone(self.server._today_cards(NOW)["tidy"])
        self.assertEqual(self.server._queue_count(NOW), 4)
        self.assertEqual(self.server._queue_count(NOW + self.today.SNOOZE_S + 1), 5)

    def test_an_update_nobody_assessed_is_not_a_card(self):
        with unittest.mock.patch.object(self.server.upgrades, "listing",
                               lambda rows: [{"entity_id": "update.os", "latest": "1"}]):
            self.assertEqual(self.server._today_cards(time.time())["updates"], [])


if __name__ == "__main__":
    unittest.main()
