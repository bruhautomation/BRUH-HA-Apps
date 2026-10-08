#!/usr/bin/env python3
"""A held verdict that a later report contradicts is looked at again, and a
fault filed by several cards before the cross-fold existed is one row.

Reported from a real house: four copies of "this history_stats window is
wrong" were held as "zero cooling in late September is normal" while their
own details showed hours of cooling the sensor missed. A later copy proved
the window wrong and nothing went back to the verdicts; and one fault
filed six times by different cards (one open, five held) showed a different
status depending on which copy was opened.

Driven over the real store.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import findings_store  # noqa: E402
import triage  # noqa: E402
from test_cross_producer_fold import SENSOR, card  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402


class Case(FoldCase):
    def setUp(self):
        super().setUp()
        self._mig = findings_store.MIGRATIONS_FILE
        findings_store.MIGRATIONS_FILE = Path(self.tmp.name) / "mig.json"

    def tearDown(self):
        findings_store.MIGRATIONS_FILE = self._mig
        super().tearDown()


class TestAContradictedHoldIsLookedAtAgain(Case):

    def held_row(self, source="hvac"):
        [row] = findings_store.add_many(triage.gate([card(
            "Cooling hours reads 0", source, detail="reads 0 for the day")]))
        findings_store.record_triage({row["ts"]: ("held", "seasonal")})
        return row

    def test_a_changed_detail_from_another_card_sends_it_back(self):
        row = self.held_row()
        findings_store.add_many(triage.gate([card(
            "The window is wrong", "dehumidifier",
            detail="it missed 3.7 h of cooling")]))
        got = findings_store.get(row["ts"])
        self.assertEqual(got["status"], "triaging")
        self.assertIn("3.7 h", got["detail"])

    def test_a_changed_detail_from_the_same_card_sends_it_back(self):
        row = self.held_row()
        findings_store.add_many([card(
            "The window is wrong again", "hvac",
            detail="it missed 8.53 h of cooling")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "triaging")

    def test_the_same_detail_leaves_the_verdict_standing(self):
        row = self.held_row()
        findings_store.add_many([card("Zero again", "dehumidifier",
                                      detail="reads 0 for the day")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_row_a_person_put_back_is_never_held_again_by_a_re_report(self):
        row = self.held_row()
        findings_store.elevate(row["ts"])
        findings_store.add_many([card("New evidence", "hvac",
                                      detail="something new")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")

    def test_a_row_a_person_ended_is_not_revived(self):
        row = self.held_row()
        findings_store.settle_and_clear(row["ts"], "ignored")
        findings_store.add_many([card("New evidence", "hvac",
                                      detail="something new")])
        self.assertEqual([r for r in findings_store.list_all()
                          if r["status"] == "triaging"], [])


class TestOldHoldsGetOneFreshLook(Case):

    def old_hold(self, n=1, **over):
        out = []
        for i in range(n):
            [row] = findings_store.add_many([card(
                f"Reading {i} is odd", "hvac", eid=f"sensor.s{i}", **over)])
            out.append(row["ts"])
        items = json.loads(findings_store.FINDINGS_FILE.read_text())
        for f in items["findings"]:
            f["status"] = "held"
            f["triage"] = {"verdict": "held", "reason": "normal for the season",
                           "at": 1}
        findings_store.FINDINGS_FILE.write_text(json.dumps(items))
        return out

    def test_a_hold_from_before_the_claim_rule_is_looked_at_once(self):
        [ts] = self.old_hold()
        self.assertEqual(findings_store.migrate_folds()["retriaged"], 1)
        self.assertEqual(findings_store.get(ts)["status"], "triaging")
        # The new look holds it again: stamped, so a restart leaves it.
        findings_store.record_triage({ts: ("held", "still normal")})
        self.assertEqual(findings_store.migrate_folds()["retriaged"], 0)
        self.assertEqual(findings_store.get(ts)["status"], "held")
        self.assertEqual(findings_store.get(ts)["triage"]["v"],
                         triage.LOOK_VERSION)

    def test_it_is_bounded_and_marked(self):
        ts = self.old_hold(findings_store.MIGRATION_RETRIAGE_MAX + 5)
        out = findings_store.migrate_folds()
        self.assertEqual(out["retriaged"], findings_store.MIGRATION_RETRIAGE_MAX)
        # A restart is not a new pass: the rest are left, not re-looked.
        self.assertEqual(findings_store.migrate_folds(),
                         {"folded": 0, "retriaged": 0})
        self.assertEqual(len(ts), 30)

    def test_a_person_put_back_row_and_a_check_row_are_left(self):
        [ts] = self.old_hold()
        findings_store.elevate(ts)
        [chk] = findings_store.add_many([card("Frozen", "check:dev.frozen",
                                              eid="sensor.c")])
        findings_store.record_triage({chk["ts"]: ("held", "x")})
        self.assertEqual(findings_store.migrate_folds()["retriaged"], 0)


class TestOneFaultFiledByManyCardsIsOneRow(Case):

    def six(self, statuses):
        rows = []
        for i, status in enumerate(statuses):
            rows.append({"ts": 1000 + i, "text": f"Window wrong {i}",
                         "entity_id": SENSOR, "source": f"card{i}",
                         "source_title": "c", "severity": "warning",
                         "detail": f"detail {i}", "status": status,
                         "triage": {"verdict": "held", "at": 1}
                         if status == "held" else {}})
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": rows}))

    def test_the_open_copy_wins_and_the_newest_detail_with_it(self):
        self.six(["held", "held", "open", "held", "held", "held"])
        self.assertEqual(findings_store.migrate_folds()["folded"], 5)
        [row] = findings_store.list_all()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["detail"], "detail 5")

    def test_it_never_touches_a_fixed_row_the_resident_or_a_check(self):
        rows = [
            {"ts": 1, "text": "a", "entity_id": SENSOR, "source": "c1",
             "status": "open"},
            {"ts": 2, "text": "b", "entity_id": SENSOR, "source": "c2",
             "status": "fixed"},
            {"ts": 3, "text": "c", "entity_id": SENSOR, "source": "resident",
             "status": "open"},
            {"ts": 4, "text": "d", "entity_id": SENSOR,
             "source": "check:dev.frozen", "status": "open"},
        ]
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": rows}))
        self.assertEqual(findings_store.migrate_folds()["folded"], 0)
        self.assertEqual(len(findings_store.list_all()), 4)

    def test_it_runs_once(self):
        self.six(["open", "held"])
        findings_store.migrate_folds()
        self.six(["open", "held"])
        self.assertEqual(findings_store.migrate_folds()["folded"], 0)


if __name__ == "__main__":
    unittest.main()
