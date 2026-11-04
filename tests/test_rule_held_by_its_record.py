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
a card somebody made) three Wrongs deep is held by default: `triage.gate`
files its rows carrying the record, the first look is told the streak,
and a row no look keeps (skipped, failed, never looked at) is held with
the record as its reason instead of shown unjudged — kept under History,
never sent. It comes back to be looked at when its report gets worse or
names something new, or as soon as somebody agrees with one of the
rule's reports. Safety, security and a
critical row are never held.

The examples are made up: Garden lights / Patio lights conflicting, a
"Pool pump" card somebody made, a cellar humidity forecast.
"""

import asyncio
import os
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
from test_outcomes import OutcomesLoop  # noqa: E402
from test_resident_loop import reply  # noqa: E402

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
        # A look runs on this install (`triage.LAST_LOOK_AT`): a row from a
        # rule three deep waits for it. `TestNoLookEverRuns` says otherwise.
        self._look_clock = triage.LAST_LOOK_AT
        triage.LAST_LOOK_AT = time.time
        self._protected = os.environ.get("BRAIN_PROTECTED_ENTITIES")
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        decision_trail.TRAIL_FILE = self._trail
        triage.LAST_LOOK_AT = self._look_clock
        if self._protected is None:
            os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        else:
            os.environ["BRAIN_PROTECTED_ENTITIES"] = self._protected
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

    def file(self, *rows):
        return findings_store.add_many(triage.gate([dict(r) for r in rows]))

    def nothing_looked(self, row):
        """What every silence does to a waiting row: the stale sweep, a
        look that failed (`triage.UNJUDGED` / `RUN_FAILED`)."""
        findings_store.record_triage({row["ts"]: ("untriaged",
                                                  triage.UNJUDGED)})
        return findings_store.get(row["ts"])


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


class TestHeldByDefault(StoreCase):
    def file(self, *rows):
        return findings_store.add_many(triage.gate([dict(r) for r in rows]))

    def nothing_looked(self, row):
        """What every silence does to a waiting row: the stale sweep, a
        look that failed (`triage.UNJUDGED` / `RUN_FAILED`)."""
        findings_store.record_triage({row["ts"]: ("untriaged",
                                                  triage.UNJUDGED)})
        return findings_store.get(row["ts"])

    def test_a_check_rule_three_wrongs_deep_is_held_when_nothing_looks(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertTrue(row["record_hold"])
        # not shown while it waits for its look
        self.assertFalse(triage.waiting_too_long(
            {**row, "ts": 1}, now=time.time()))
        held = self.nothing_looked(row)
        self.assertEqual(held["status"], "held")
        self.assertIn("last 3 reports wrong", held["triage"]["reason"])
        self.assertNotIn(row["ts"], [f["ts"] for f in
                                     findings_store.list_all("live")])

    def test_a_person_made_rule_three_wrongs_deep_is_held(self):
        self.answers(USER_RULE, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(USER_RULE, "The pool pump ran at night"))
        self.assertEqual(self.nothing_looked(row)["status"], "held")

    def test_a_look_that_keeps_it_is_the_fresh_evidence(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        findings_store.record_triage({row["ts"]: ("elevated", "it is new")})
        shown = findings_store.get(row["ts"])
        self.assertEqual(shown["status"], "open")
        self.assertNotIn("record_hold", shown)

    def test_another_rule_still_shows_unjudged(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row("check:dev.battery_low", "Low"))
        self.assertNotIn("record_hold", row)
        self.assertEqual(self.nothing_looked(row)["status"], "open")

    def test_a_critical_row_is_never_held(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Freezer is warming",
                                   severity="critical"))
        self.assertEqual(self.nothing_looked(row)["status"], "open")

    def test_fresh_evidence_sends_a_held_row_to_be_looked_at(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.nothing_looked(row)
        findings_store.refresh_details([self.row(
            FORECAST, "Cellar humidity is falling", severity="serious")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "triaging")

    def test_the_same_report_again_stays_held_and_files_nothing(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.nothing_looked(row)
        self.assertEqual(self.file(self.row(
            FORECAST, "Cellar humidity is falling")), [])
        findings_store.refresh_details([self.row(
            FORECAST, "Cellar humidity is falling")])
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_one_agreement_lifts_the_hold(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored", "fixed")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertNotIn("record_hold", row)

    def test_a_person_can_still_put_one_back(self):
        self.answers(USER_RULE, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(USER_RULE, "The pool pump ran at night"))
        self.nothing_looked(row)
        findings_store.elevate(row["ts"])
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")

    def test_the_look_is_told_the_streak(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [line] = rule_record.lines(
            [{"kind": "check", "subject": "sensor.x", "source": FORECAST}],
            findings_store.scorecard())
        self.assertIn("last 3 in a row were wrong", line)


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
        findings_store.record_triage({filed["ts"]: ("untriaged", "")})
        self.assertEqual(findings_store.get(filed["ts"])["status"], "held")


class TestThroughTheLook(OutcomesLoop):
    """The real loop: a look that answers nothing for the row holds it; a
    look that keeps it shows it."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))
        for i in range(3):
            row = self.file_row(f"The larder contact has not changed {i}",
                                entity=f"binary_sensor.larder_{i}")
            self.end(row["ts"], "wrong")

    def test_a_reply_that_skips_it_holds_it(self):
        row = self.file_row("The larder contact has not changed again",
                            entity="binary_sensor.larder_9")
        self.looks.append(reply([]))
        self.fresh_tick(time.time())
        self.assertIn("last 3 in a row were wrong",
                      self.look_calls[-1]["prompt"])
        got = self.fs.get(row["ts"])
        self.assertEqual(got["status"], "held")
        self.assertIn("last 3 reports wrong", got["triage"]["reason"])


class TestNeverHeldForAProtectedEntity(StoreCase):
    """A check's row carries no `protected` flag — the signal does — so the
    gate works protection out off the row's own entity: a lock on the
    protected list is shown whatever its rule's record, and the next
    device from the same rule is held as before."""

    UNAVAILABLE = "check:dev.unavailable"

    def lock_row(self, entity="lock.front_door"):
        return {"text": "Front door lock has been unavailable for a day",
                "detail": "Last seen 3 Sep 02:10.",
                "fix": "Check the lock's power and its hub.",
                "severity": "warning", "source": self.UNAVAILABLE,
                "source_title": "Devices unavailable for a day",
                "entity_id": entity, "fixable": False}

    def test_a_protected_lock_is_never_held_by_a_record(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.front_door"
        self.answers(self.UNAVAILABLE, "ignored", "ignored", "ignored")
        self.assertTrue(rule_record.never_held(self.lock_row()))
        [row] = self.file(self.lock_row())
        self.assertNotIn("record_hold", row)
        # the fallback path: nothing looked, and it is shown unjudged
        self.assertEqual(self.nothing_looked(row)["status"], "open")
        # the next device from the same three-deep rule is held as before
        [other] = self.file({**self.lock_row("switch.loft_plug"),
                             "text": "Loft plug has been unavailable "
                                     "for a day"})
        self.assertTrue(other.get("record_hold"))
        self.assertEqual(self.nothing_looked(other)["status"], "held")

    def test_a_domain_pattern_and_a_named_item_count(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.*"
        self.assertTrue(rule_record.never_held(self.lock_row("lock.back")))
        self.assertTrue(rule_record.never_held({
            **self.lock_row("sensor.hub_status"),
            "items": ["switch.loft_plug", "lock.side_gate"]}))
        self.assertFalse(rule_record.never_held(
            self.lock_row("switch.loft_plug")))

    def test_a_check_about_harm_is_never_held(self):
        for source in ("check:climate.freeze", "check:safety.tripped"):
            self.assertTrue(rule_record.never_held(
                {**self.lock_row("sensor.pipe"), "source": source}), source)

    def test_an_unreadable_list_holds_nothing(self):
        import automation_writer

        def broken():
            raise OSError("no list")
        old = automation_writer.protected_patterns
        automation_writer.protected_patterns = broken
        try:
            self.assertTrue(rule_record.never_held(
                self.lock_row("switch.loft_plug")))
        finally:
            automation_writer.protected_patterns = old


class TestNoLookEverRuns(StoreCase):
    """A row carrying a record waits for its look; with no look since it
    started waiting (the Resident off, or never came) it is shown after
    the ordinary wait rather than hidden for ever."""

    def test_shown_after_the_ordinary_wait_when_no_look_has_run(self):
        self.answers(FORECAST, "ignored", "ignored", "ignored")
        [row] = self.file(self.row(FORECAST, "Cellar humidity is falling"))
        self.assertTrue(row["record_hold"])
        filed = int(row["ts"])
        later = filed + triage.SHOW_AFTER_S + 60
        # a look ran after it started waiting: it waits
        triage.LAST_LOOK_AT = lambda: filed + 30
        self.assertFalse(triage.waiting_too_long(row, now=later))
        # no look has ever run
        triage.LAST_LOOK_AT = lambda: 0
        self.assertFalse(triage.waiting_too_long(row, now=filed + 60))
        self.assertTrue(triage.waiting_too_long(row, now=later))
        # the last look is older than this row: the same
        triage.LAST_LOOK_AT = lambda: filed - 3600
        self.assertTrue(triage.waiting_too_long(row, now=later))
        # no clock at all is unknown, and unknown waits
        triage.LAST_LOOK_AT = None
        self.assertFalse(triage.waiting_too_long(row, now=later))


class TestTheFloorBeatsTheRecord(OutcomesLoop):
    """`_resident_apply`'s fallback holds a row from a rule three deep when
    the reply said nothing about it — never a signal the floor keeps: hot,
    safety or protected (`resident.never_ignore`)."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))
        for i in range(3):
            row = self.file_row(f"The larder contact has not changed {i}",
                                entity=f"binary_sensor.larder_{i}")
            self.end(row["ts"], "wrong")

    def apply(self, row, **flags):
        srv = self.server
        signal = {**srv.signals.make(
            "check", row["entity_id"], now=time.time(),
            source=row["source"], text=row["text"], **flags),
            "finding_ts": row["ts"], "record_hold": row["record_hold"]}
        asyncio.run(srv._resident_apply([signal], {}, "look-x", time.time(),
                                        {}, "", 0, 0))
        return self.fs.get(row["ts"])["status"]

    def test_a_hot_safety_or_protected_signal_is_shown_not_held(self):
        for i, flags in enumerate(({"hot": True}, {"safety": True},
                                   {"protected": True})):
            row = self.file_row(f"The larder contact has not changed {i}x",
                                entity=f"binary_sensor.larder_{i}x")
            self.assertTrue(row.get("record_hold"), flags)
            self.assertEqual(self.apply(row, **flags), "open", flags)
        plain = self.file_row("The larder contact has not changed again",
                              entity="binary_sensor.larder_9")
        self.assertEqual(self.apply(plain), "held")


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
        findings_store.record_triage({filed["ts"]: ("untriaged", "")})
        self.assertEqual(findings_store.get(filed["ts"])["status"], "held")


if __name__ == "__main__":
    unittest.main()
