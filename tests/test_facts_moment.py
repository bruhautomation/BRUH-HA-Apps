#!/usr/bin/env python3
"""A reading of one moment is not a standing fact about the house.

Reported from a real house: an insight run filed "the hall moved across
69–72 °F in the last 12 hours" and "the freezer sensor is frozen right
now", and the store went on handing both to every later run as true. A
machine's fact about a recent window or the present moment is filed with
a short `expires` (`MOMENT_DAYS`) through the ordinary `_expired` rule,
and the repair pass gives one already stored the same life, counted from
when it was last said. What a person said is never aged by its wording,
and a rule, a judgement or an occasion keeps its own lifetime.

Driven through the real inbox sweep and the real reconcile.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import facts_store  # noqa: E402
from test_facts_filing import DAY, NOW, REGISTRY, StoreCase  # noqa: E402


class TestAMomentIsFiledWithAShortLife(StoreCase):

    def test_a_reading_of_the_last_hours_expires_in_days(self):
        self.queue({"fact": "The hall moved across 69-72 F in the last "
                            "12 hours", "source": "card", "ts": NOW})
        got = self.row("moved across")
        self.assertEqual(got["expires"],
                         facts_store._day(NOW + facts_store.MOMENT_DAYS * DAY))
        self.assertFalse(facts_store._expired(got, NOW + DAY))
        self.assertTrue(facts_store._expired(
            got, NOW + (facts_store.MOMENT_DAYS + 1) * DAY))

    def test_right_now_and_currently_are_moments(self):
        for text in ("The freezer sensor reads -18 right now",
                     "The lounge lamp is currently on",
                     "The boiler ran twice this morning"):
            self.assertTrue(facts_store.is_moment(text), text)

    def test_a_standing_fact_has_no_expiry(self):
        self.queue({"fact": "The boiler is in the utility room",
                    "source": "card", "ts": NOW})
        self.assertEqual(self.row("utility room").get("expires", ""), "")

    def test_a_habit_that_names_when_is_still_a_habit(self):
        self.assertFalse(facts_store.is_moment(
            "The heating always comes on at six, as it did this morning"))

    def test_what_a_person_said_is_never_aged_by_its_wording(self):
        self.queue({"fact": "The garage door is broken right now, leave it",
                    "source": "correction", "ts": NOW})
        self.assertEqual(self.row("garage door").get("expires", ""), "")

    def test_a_rule_keeps_its_own_lifetime(self):
        self.queue({"fact": "That reading is normal today",
                    "source": "card", "ts": NOW,
                    "predicate": "exception:dev.frozen",
                    "subject": "sensor.freezer_temp"})
        self.assertEqual(self.row("normal today").get("expires", ""), "")


class TestTheRepairAgesOldMoments(StoreCase):

    def test_a_stored_moment_gets_a_life_from_when_it_was_said(self):
        said = int(NOW - 30 * DAY)
        self.store([
            {"id": "a", "subject": "house", "subjects": ["house"],
             "predicate": "", "source": "card", "ts": said,
             "first_seen": said,
             "text": "The freezer sensor is frozen right now"},
            {"id": "b", "subject": "house", "subjects": ["house"],
             "predicate": "", "source": "person", "ts": said,
             "first_seen": said,
             "text": "The porch light is on right now because of the party"},
            {"id": "c", "subject": "house", "subjects": ["house"],
             "predicate": "", "source": "card", "ts": said,
             "first_seen": said, "text": "The boiler is in the utility room"},
        ])
        facts_store.reconcile(None, self.inbox, now=NOW, registry=REGISTRY)
        moment = self.row("frozen right now")
        self.assertEqual(moment["expires"],
                         facts_store._day(said + facts_store.MOMENT_DAYS * DAY))
        self.assertTrue(facts_store._expired(moment, NOW))
        self.assertEqual(self.row("porch light").get("expires", ""), "")
        self.assertEqual(self.row("utility room").get("expires", ""), "")

    def test_the_repair_rule_is_a_new_repair_version(self):
        # A store repaired under version 1 must be repaired again.
        self.assertGreaterEqual(facts_store.REPAIR_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
