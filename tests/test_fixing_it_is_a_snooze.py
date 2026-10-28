#!/usr/bin/env python3
""""I need to fix this light" is a snooze, not a rule.

A dashboard clean-up (`org.dashboard_dead_ref`, and Morph's own "remove the
unavailable card" suggestion) only ever offered removal. The household
answered "I need to fix this light", and the words were stored as a general
correction — so nothing stayed quiet for the time the repair takes, and the
suggestion came back while the light was still unavailable. A reason that
says the thing is out of use FOR NOW — being repaired, unplugged for now,
"I'll plug it back in soon", "waiting on a part" — is the snooze the
household meant: no rule, quiet for the period it names (two weeks when it
names none), and over early when the entity it is about reports again, at
which point the card it would have removed is kept.

The second example is one the report never named: a `dev.unavailable`
row on a plug "away being repaired", answered with Wrong.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import findings_store  # noqa: E402
from morph_env import MorphEnv  # noqa: E402
from test_interpret import PhoneCase  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

DAY = 86400


class TestTheWordsAreRead(unittest.TestCase):
    def test_out_of_use_for_now(self):
        for said in ("I need to fix this light",
                     "It's being repaired",
                     "unplugged for now while we redecorate",
                     "temporarily out of use",
                     "I'll plug it back in soon",
                     "waiting on a replacement part",
                     "the bulb is away for repair",
                     "Fixing it this weekend"):
            self.assertTrue(corrections.temporary(said), said)

    def test_what_is_for_good_is_not(self):
        for said in ("unpowered unless we're using it",
                     "expected: unpowered most of the year",
                     "its battery is dead and I do not plan to replace it",
                     "normal for this sensor",
                     "this is intentional",
                     "I won't fix it, it's staying off",
                     "it's a dummy",
                     ""):
            self.assertFalse(corrections.temporary(said), said)

    def test_how_long(self):
        self.assertEqual(corrections.temporary_days("being repaired"),
                         corrections.TEMPORARY_DAYS)
        self.assertEqual(corrections.temporary_days(
            "unplugged for now, back in 3 weeks"), 21)
        self.assertEqual(corrections.temporary_days(
            "I'll fix it in 5 days"), 5)
        self.assertEqual(corrections.temporary_days(
            "being repaired, ask again in a month"), 30)
        self.assertEqual(corrections.temporary_days(
            "away for repair for a year"), corrections.TEMPORARY_MAX_DAYS)


class TestTheWrongPress(RouteCase):
    ENTITY = "switch.shed_plug"

    def press(self, row, note):
        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": note})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            return await res.json()
        return self.drive(body)

    def test_a_plug_away_being_repaired_is_snoozed_not_ruled(self):
        row = self.check_row("dev.unavailable")
        before = time.time()
        out = self.press(row, "It's away being repaired")
        self.assertEqual(self.rules(), [])
        kept = findings_store.get(row["ts"])
        self.assertIsNotNone(kept, "the row stays, asleep")
        until = int(kept.get("snoozed_until") or 0)
        self.assertGreaterEqual(until, before + corrections.TEMPORARY_DAYS * DAY - 5)
        self.assertLessEqual(until, time.time() + corrections.TEMPORARY_DAYS * DAY + 5)
        self.assertEqual(kept.get("snooze_wake"), [self.ENTITY])
        self.assertNotIn("correct", self.model_jobs())

        async def undo(client):
            res = await client.post(f"/api/undo/{out['undo']}")
            self.assertEqual(res.status, 200, await res.text())
            return await res.json()

        self.assertTrue(self.drive(undo).get("undone"))
        back = findings_store.get(row["ts"])
        self.assertEqual(int(back.get("snoozed_until") or 0), 0)
        self.assertFalse(back.get("snooze_wake"))

    def test_the_period_it_names_is_the_period(self):
        row = self.check_row("org.dashboard_dead_ref")
        self.press(row, "unplugged for now, back in 3 weeks")
        until = int(findings_store.get(row["ts"]).get("snoozed_until") or 0)
        self.assertAlmostEqual(until, time.time() + 21 * DAY, delta=60)

    def test_a_reason_for_good_is_still_a_rule(self):
        row = self.check_row("dev.unavailable")
        self.press(row, "I won't fix it, it's staying off")
        self.assertEqual([r["subject"] for r in self.rules()], [self.ENTITY])
        self.assertIsNone(findings_store.get(row["ts"]))


class TestItIsOverWhenTheThingIsBack(RouteCase):
    ENTITY = "light.porch"

    def morph_row(self):
        entry = findings_store.add_case({
            "text": "Remove the unavailable Porch light card",
            "claim": "Remove the unavailable Porch light card?",
            "kind": "question", "detail": "It has been unavailable a week.",
            "fix": "", "entity_id": self.ENTITY, "severity": "info",
            "stakes": "low", "fixable": False,
            "source": findings_store.MORPH_SOURCE,
            "source_title": "Morph, your dashboard", "morph_key": "g9",
            "status": "open"})
        self.assertIsNotNone(entry)
        return entry

    def test_a_morph_suggestion_answered_fixing_it_sleeps_then_is_kept(self):
        row = self.morph_row()

        async def body(_client):
            return await self.server._end_finding(
                row, self.server.FINDING_VERBS["wrong"],
                "I need to fix this light first")

        self.drive(body)
        kept = findings_store.get(row["ts"])
        self.assertGreater(int(kept.get("snoozed_until") or 0), time.time())
        self.assertEqual(kept.get("snooze_wake"), [self.ENTITY])
        # Still unavailable: nothing changes.
        self.assertEqual(findings_store.wake_returned(
            {self.ENTITY: {"state": "unavailable"}}), [])
        self.assertIsNotNone(findings_store.get(row["ts"]))
        # Back: the suggestion to remove its card is over, and Morph is told
        # the card is kept.
        woken = findings_store.wake_returned({self.ENTITY: {"state": "off"}})
        self.assertEqual([w["ts"] for w in woken], [row["ts"]])
        self.assertIsNone(findings_store.get(row["ts"]))

    def test_a_snoozed_row_from_a_producer_that_does_not_recheck_wakes(self):
        entry, _ = findings_store.add(
            "Porch light has been offline since Tuesday", severity="warning",
            source=findings_store.RESIDENT_SOURCE, entity_id=self.ENTITY)
        findings_store.snooze(entry["ts"], int(time.time() + 9 * DAY),
                              wake=[self.ENTITY])
        findings_store.wake_returned({self.ENTITY: {"state": "on"}})
        back = findings_store.get(entry["ts"])
        self.assertEqual(int(back.get("snoozed_until") or 0), 0)
        self.assertFalse(back.get("snooze_wake"))


class TestAReplyThatSaysFixingIt(PhoneCase):
    ENTITY = "light.porch"

    def setUp(self):
        super().setUp()
        self._journal = self.server.journal.JOURNAL_FILE
        self.server.journal.JOURNAL_FILE = str(Path(self.tmp.name)
                                               / "journal.jsonl")

    def tearDown(self):
        self.server.journal.JOURNAL_FILE = self._journal
        super().tearDown()

    def test_read_as_a_correction_it_is_still_a_snooze(self):
        """The interpreter read it as something to remember — the report's
        failure — and the reply is still the snooze it meant."""
        row = self.check_row("org.dashboard_dead_ref")
        self.replies["interpret"] = {"routes": [
            {"kind": "remember", "text": "I need to fix this light"}]}

        async def body(_client):
            return await self.server._morph_reply(
                f"f:{row['ts']}", "I need to fix this light", "panel")

        out = self.drive(body)
        self.assertTrue(out["read"])
        kept = findings_store.get(row["ts"])
        self.assertGreater(int(kept.get("snoozed_until") or 0), time.time())
        self.assertEqual(self.rules(), [])
        self.assertIn("back", out["say"].lower())

    def test_unread_it_is_still_a_snooze(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row("org.dashboard_dead_ref")

        async def body(_client):
            return await self.server._morph_reply(
                f"f:{row['ts']}", "I need to fix this light", "panel")

        self.drive(body)
        kept = findings_store.get(row["ts"])
        self.assertGreater(int(kept.get("snoozed_until") or 0), time.time())


class TestMorphKeepsTheCard(unittest.TestCase):
    def test_kept_closes_the_suggestion_without_declining_it(self):
        with MorphEnv() as env:
            env.brain_shared.mkdir(parents=True, exist_ok=True)
            L = env.learning
            data = L._load()
            data["items"].append({"id": "g9", "key": "k9",
                                  "title": "Remove the unavailable porch card",
                                  "status": "open", "kind": "dashboard"})
            L._save(data)
            L.sync_brain()
            (env.brain_shared / "morph").mkdir(exist_ok=True)
            (env.brain_shared / "morph" / "cases.json").write_text(json.dumps(
                {"ended_morph": [{"key": "g9", "how": "kept", "note": "",
                                  "at": 100}]}))
            L.sync_brain()
            L.sync_brain()
            item = next(x for x in L._load()["items"] if x["id"] == "g9")
            self.assertEqual(item["status"], "kept")
            self.assertNotIn("k9", L._load()["declined"])
            d = env.brain_shared / "finding-requests"
            files = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
            self.assertEqual(len([r for r in files if r.get("action") == "file"]), 1)


if __name__ == "__main__":
    unittest.main()
