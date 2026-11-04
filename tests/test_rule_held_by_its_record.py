#!/usr/bin/env python3
"""A rule the household marked wrong three times in a row is held back.

Reports #698, #500, #501, #599 and #579: rules at 0 of 6, 0 of 4, 0 of 3
and 0 of 2 confirmed kept putting cards in front of the household, because
the only thing their record earned was a line read to the first look and,
past four answers, a question about muting. Each Wrong was per entity or per
pair, so the next automation, the next forecast, the next card a person's
own rule wrote was news again.

Now `rule_record` reads a streak — the household's latest answers about
the rule, newest first, while they are Wrong — and a rule (a house check or
a card somebody made) three Wrongs deep is filed HELD by the one door,
`triage.gate`: kept, visible under History, never sent and never put in
front of anybody, with the record as its reason. It comes back to be
looked at when its report gets worse or names something new, or as soon
as somebody agrees with one of the rule's reports. Safety, security and a
critical row are never held.

The examples are made up: Garden lights / Patio lights conflicting, a
"Pool pump" card somebody made, a cellar humidity forecast.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import decision_trail  # noqa: E402
import findings_store  # noqa: E402
import rule_record  # noqa: E402
import test_checks_wrong_in_the_field as field  # noqa: E402
import triage  # noqa: E402
from checks import automations as auto  # noqa: E402

CONFLICT = "check:auto.conflict"
FORECAST = "check:forecast.decline"
USER_RULE = "user-1790000001"


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "state.json"
        self._trail = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(root / "decisions.jsonl")
        self.clock = 1_790_000_000

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        decision_trail.TRAIL_FILE = self._trail
        self.tmp.cleanup()

    def answers(self, source, *kinds):
        """One ledger answer per kind, oldest first, each about its own
        thing — the per-entity Wrongs the house gave."""
        for i, kind in enumerate(kinds):
            self.clock += 3600
            findings_store._remember_settled(
                {"text": f"{source} report {self.clock}", "source": source,
                 "source_title": "", "entity_id": f"sensor.thing_{i}"},
                kind, when=self.clock)

    def row(self, source, text="A new report", severity="warning", **extra):
        return {"text": text, "detail": "What the rule saw.",
                "fix": "Change the thing.", "severity": severity,
                "source": source, "entity_id": "sensor.new_thing", **extra}

    def card(self, source):
        return next(r for r in findings_store.scorecard()
                    if r["source"] == source)


class TestTheStreak(StoreCase):
    def test_the_latest_wrongs_in_a_row_are_counted(self):
        self.answers(CONFLICT, "fixed", "ignored", "ignored", "ignored")
        self.assertEqual(self.card(CONFLICT)["streak"], 3)
        self.assertTrue(rule_record.holds(self.card(CONFLICT)))

    def test_an_agreement_ends_the_streak(self):
        # 4 Wrong of 5, the field's auto.conflict, but the latest agreed
        self.answers(CONFLICT, "ignored", "ignored", "ignored", "ignored",
                     "accepted")
        self.assertEqual(self.card(CONFLICT)["streak"], 0)
        self.assertFalse(rule_record.holds(self.card(CONFLICT)))

    def test_two_in_a_row_is_not_yet_a_hold(self):
        self.answers(FORECAST, "ignored", "ignored")
        self.assertFalse(rule_record.holds(self.card(FORECAST)))

    def test_a_rule_three_deep_after_agreements_is_read_to_the_look_too(self):
        self.answers(CONFLICT, "fixed", "fixed", "fixed", "ignored",
                     "ignored", "ignored")
        self.assertTrue(rule_record.qualifies(self.card(CONFLICT)))

    def test_what_is_never_held(self):
        for source in ("check:sec.lock_cloud_voice", "check:climate.freeze",
                       "check:safety.tripped", "resident", "safety",
                       "insight-energy", "custom-123"):
            row = {"source": source, "streak": 5, "wrong": 5, "total": 5,
                   "last": "wrong"}
            self.assertFalse(rule_record.holds(row), source)


class TestHeldAtTheDoor(StoreCase):
    def file(self, *rows):
        return findings_store.add_many(triage.gate([dict(r) for r in rows]))

    def test_a_check_rule_three_wrongs_deep_files_held(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertEqual(row["status"], "held")
        reason = row["triage"]["reason"]
        self.assertIn("3", reason)
        self.assertIn("wrong", reason)
        # not in front of anybody, and nothing to send
        self.assertNotIn(row["ts"], [f["ts"] for f in
                                     findings_store.list_all("live")])

    def test_a_person_made_rule_three_wrongs_deep_files_held(self):
        self.answers(USER_RULE, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(USER_RULE, "The pool pump ran at night"))
        self.assertEqual(row["status"], "held")

    def test_another_rule_still_waits_for_its_look(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row("check:dev.battery_low", "Low"))
        self.assertEqual(row["status"], "triaging")

    def test_a_critical_row_is_never_held(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Freezer is warming",
                                   severity="critical"))
        self.assertEqual(row["status"], "triaging")

    def test_fresh_evidence_sends_it_to_be_looked_at(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        findings_store.refresh_details([self.row(
            FORECAST, "Cellar humidity is falling", severity="serious")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "triaging")

    def test_the_same_report_again_stays_held_and_files_nothing(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertEqual(self.file(self.row(
            FORECAST, "Cellar humidity is falling")), [])
        findings_store.refresh_details([self.row(
            FORECAST, "Cellar humidity is falling")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_one_agreement_lifts_the_hold(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored", "fixed")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertEqual(row["status"], "triaging")

    def test_a_person_can_still_put_one_back(self):
        self.answers(USER_RULE, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(USER_RULE, "The pool pump ran at night"))
        findings_store.elevate(row["ts"])
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")


class TestTheConflictRule(unittest.TestCase):
    """auto.conflict three Wrongs deep: a new pair is held, and a pair the
    household answered is still not filed at all (the per-pair rule)."""

    def setUp(self):
        field.TestAWrongOnAConflictSticks.setUp(self)
        self._trail = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "d.jsonl")

    def tearDown(self):
        decision_trail.TRAIL_FILE = self._trail
        field.TestAWrongOnAConflictSticks.tearDown(self)

    snap = field.TestAWrongOnAConflictSticks.snap
    press_wrong = field.TestAWrongOnAConflictSticks.press_wrong

    def test_three_pairs_wrong_holds_the_fourth_and_answered_pairs_stay_quiet(self):
        pairs = [("automation.garden_a", "automation.patio_a"),
                 ("automation.garden_b", "automation.patio_b"),
                 ("automation.garden_c", "automation.patio_c")]
        for pair in pairs:
            [row] = auto.conflicting(self.snap(pair), field.NOW)
            self.press_wrong(row)
        # the per-pair answer: each answered pair files nothing
        for pair in pairs:
            self.assertEqual(auto.conflicting(self.snap(pair), field.NOW), [])
        # a new pair is still a report the check makes, held at the door
        new = auto.conflicting(self.snap(("automation.porch_x",
                                          "automation.shed_y")), field.NOW)
        self.assertEqual(len(new), 1)
        [filed] = findings_store.add_many(triage.gate(
            [{**new[0], "source": CONFLICT}]))
        self.assertEqual(filed["status"], "held")


class TestTheOfferIsNotHandedToTheLook(unittest.TestCase):
    def test_a_held_row_is_not_offered_as_a_signal(self):
        import importlib
        server = importlib.import_module("server")
        before = len(server.RESIDENT_PENDING)
        server._offer_findings([{"ts": int(time.time()), "status": "held",
                                 "text": "x", "source": FORECAST,
                                 "entity_id": "sensor.x"}], time.time())
        self.assertEqual(len(server.RESIDENT_PENDING), before)


class TestNeverFired(StoreCase):
    """#579: once a never-fired report is marked Wrong, the check makes no
    row about that automation, whatever the reason said; and Wrongs on
    three others hold the next one back."""

    def snap_with(self, *entity_ids):
        from test_house_checks import house
        from test_never_fired_safety import installed
        snap = house()
        snap["states"].pop("automation.morning", None)
        snap["automations"] = []
        snap["entities"] = [e for e in snap["entities"]
                            if not str(e.get("entity_id", "")).startswith(
                                "automation.")]
        for eid in entity_ids:
            slug = eid.split(".", 1)[1]
            installed(snap, {"id": slug, "alias": slug.replace("_", " "),
                             "triggers": [{"trigger": "state",
                                           "entity_id": "binary_sensor.x"}],
                             "actions": []}, eid)
        snap["answers"] = findings_store.answered_checks()
        return snap

    def wrong(self, row, note=""):
        entry, _ = findings_store.add(
            row["text"], detail=row["detail"], fix=row["fix"],
            severity=row["severity"], source="check:auto.never_fired",
            entity_id=row["entity_id"])
        findings_store.settle_and_clear(entry["ts"], "ignored", note=note)

    def test_one_wrong_closes_it_for_that_automation(self):
        from test_house_checks import NOW
        [row] = auto.never_fired(self.snap_with("automation.holiday_lamp"),
                                 NOW)
        # a reason that writes no standing rule (a condition brAIn cannot
        # watch) is still an answer about this automation
        self.wrong(row, "it only runs when we are away on holiday")
        snap = self.snap_with("automation.holiday_lamp",
                              "automation.attic_fan")
        self.assertEqual([f["entity_id"] for f in auto.never_fired(snap, NOW)],
                         ["automation.attic_fan"])

    def test_wrongs_on_others_hold_the_next_one_back(self):
        from test_house_checks import NOW
        for eid in ("automation.one", "automation.two", "automation.three"):
            [row] = auto.never_fired(self.snap_with(eid), NOW)
            self.wrong(row)
        [row] = auto.never_fired(self.snap_with("automation.four"), NOW)
        [filed] = findings_store.add_many(triage.gate(
            [{**row, "source": "check:auto.never_fired"}]))
        self.assertEqual(filed["status"], "held")


if __name__ == "__main__":
    unittest.main()
