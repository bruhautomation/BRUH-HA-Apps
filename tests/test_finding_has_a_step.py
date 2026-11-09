#!/usr/bin/env python3
"""Every finding carries a step, or says plainly that nothing is needed and why (#775).

A house's findings stated a problem and stopped: no step, no "nothing to
do", so the reader could not tell whether to act, answer or ignore. The
investigation already refused a reply with no step (`resident.unfinished`,
#616) — but it read the step as the run wrote it, and the store then emptied
some of those steps on its own way in (a placeholder, a fork, a sentence
holding only a path), while every other model producer had no such rule.

Now the investigation reads its step as the card will show it, so a step
made only of a line number or an errand brAIn does itself is no step and
the reply is not filed (`resident.unfinished`); the store names what each
row asks (`findings_store.next_step`) and files any case saying "nothing
to do, because …" (`no_action`, or its step saying so) held with that
reason, never open; a high-stakes row is never dropped for its wording;
and a house check's rows each carry a step (the sweep below).
"""

import io
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import resident  # noqa: E402
from test_cases import StoresCase  # noqa: E402

# (a case as a run wrote it, the code `resident.unfinished` gives it, and
# where the store puts it: "open", "held", or None for never filed)
SAMPLES = [
    ({"text": "The dishwasher pump has failed twice this week",
      "detail": "It stopped mid-cycle on Monday and Thursday.",
      "fix": "Clean the filter under the bottom basket, then run a rinse."},
     "", "open"),
    ({"text": "The garage door sensor reads open at night",
      "detail": "It reported open from 02:10 to 02:40."},
     "no_step", None),
    # a step the card would not show — a line number, an errand to read
    # the log brAIn reads itself — is no step (the gap #616's rule missed)
    ({"text": "The hall motion sensor stopped reporting",
      "detail": "It last reported on Tuesday.",
      "fix": "Edit line 14 of the pipeline."},
     "no_step", None),
    ({"text": "The office plug dropped off the network",
      "detail": "It dropped off four times today.",
      "fix": "Check the errors in the log."},
     "no_step", None),
    ({"text": "The porch light stayed on all day",
      "detail": "It was on from 07:00 to 19:00.",
      "fix": "Nothing needs doing: the party automation left it on and it "
             "is off now."},
     "nothing_needed", "held"),
    ({"text": "The heat pump short-cycled overnight",
      "detail": "It started 14 times between 01:00 and 05:00.",
      "no_action": "It does this on the coldest nights and settles by "
                   "morning, so nothing needs doing."},
     "no_step", "held"),
    ({"text": "Is the shed heater meant to run at night?",
      "detail": "It ran from 23:00 to 06:00 three nights in a row.",
      "kind": "question"},
     "", "open"),
    # high-stakes is never dropped for its wording
    ({"text": "Water detected under the kitchen sink",
      "detail": "The leak sensor has read wet for ten minutes.",
      "severity": "critical", "stakes": "high"},
     "", "open"),
]


class TestEveryModelRowHasAStepOrAReason(StoresCase):
    def test_samples(self):
        for row, code, want in SAMPLES:
            with self.subTest(row["text"]):
                case = {"kind": "problem", "claim": row["text"] + ".", **row}
                self.assertEqual(resident.unfinished(case)[0], code)
                if want is None:
                    continue    # the run's reply is not filed
                if "no_action" not in row and code:
                    # the investigation holds what it does not file
                    continue
                made = findings_store.add_many(
                    [{**case, "source": "insights", "status": "open"}])
                stored = next((f for f in findings_store.list_all()
                               if f["text"] == row["text"]), None)
                self.assertIsNotNone(stored)
                self.assertEqual(stored["status"], want)
                said = findings_store.next_step(stored)
                if want == "held":
                    # not raised: not announced, and its reason is on it
                    self.assertEqual(made, [])
                    self.assertEqual(said[0], "no_action")
                    self.assertIn("nothing", stored["triage"]["reason"].lower())
                else:
                    self.assertEqual(len(made), 1)
                    self.assertIn(said[0], ("step", "question", "urgent"))

    def test_a_stated_nothing_from_any_case_producer_is_held_not_raised(self):
        made = findings_store.add_many([{
            "text": "The porch light stayed on all day", "kind": "problem",
            "claim": "The porch light stayed on all day.",
            "fix": "No action is needed; it is off now.", "source": "morph"}])
        self.assertEqual(made, [])
        stored = findings_store.list_all()[0]
        self.assertEqual(stored["status"], "held")
        self.assertTrue(stored["triage"]["reason"].startswith(
            "No action is needed; it is off"))

    def test_the_schema_keeps_the_stated_reason(self):
        entry = findings_store.coerce({
            "text": "The boiler ran at 3am",
            "no_action": "That is its weekly anti-legionella cycle."})
        self.assertEqual(entry["no_action"],
                         "That is its weekly anti-legionella cycle.")
        self.assertEqual(findings_store.next_step(entry)[0], "no_action")
        self.assertEqual(findings_store.next_step(
            findings_store.coerce({"text": "The boiler ran at 3am"}))[0], "")


class TestEveryCheckRowHasAStep(unittest.TestCase):
    def test_sweep(self):
        from test_finding_text_plain import SWEEP_MODULES, _Capture
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(SWEEP_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertGreater(len(cap.rows), 20)
        bad = sorted({cid for cid, row, _s in cap.rows
                      if findings_store.next_step(
                          {"source": f"check:{cid}", **row})[0] not in
                      ("step", "question", "note", "no_action", "urgent")})
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()


class TestAStoredSteplessRowIsNotOnTheOpenList(StoresCase):
    """Rows no investigation filed — a first look's, another model
    writer's, one stored before the rule — are read on the way out too."""

    def _stored(self, ts, **fields):
        items = findings_store._load()
        items.append({"ts": ts, "status": "open", "severity": "warning",
                      "source": findings_store.RESIDENT_SOURCE, **fields})
        findings_store._write(items)

    def _open_ids(self):
        return {c["id"] for c in cases.list_cases("open")}

    def test_a_stepless_model_row_is_set_aside_and_a_leak_is_not(self):
        self._stored(1_700_000_500,
                     text="The garage door sensor reads open at night",
                     detail="It reported open from 02:10 to 02:40.",
                     triage={"verdict": "elevated", "at": 1_700_000_000,
                             "reason": "Two openings at night."})
        self._stored(1_700_000_600,
                     text="Water detected under the kitchen sink",
                     detail="The leak sensor has read wet for ten minutes.")
        self._stored(1_700_000_700,
                     text="The dishwasher pump has failed twice",
                     fix="Clean the filter under the bottom basket.")
        self._stored(1_700_000_800, source="check:dev.unavailable",
                     text="Hall plug is unavailable")
        opened = self._open_ids()
        self.assertNotIn(cases.case_id("findings", 1_700_000_500), opened)
        self.assertIn(cases.case_id("findings", 1_700_000_600), opened)
        self.assertIn(cases.case_id("findings", 1_700_000_700), opened)
        self.assertIn(cases.case_id("findings", 1_700_000_800), opened)
        listed = {r["ts"]: r for r in findings_store.listing()["findings"]}
        self.assertEqual(listed[1_700_000_500]["status"], "held")
        self.assertEqual(listed[1_700_000_600]["status"], "open")
        # the stored row is untouched: a step written later puts it back
        self.assertEqual(findings_store.get(1_700_000_500)["status"], "open")


class TestWhatIsNeverSetAside(StoresCase):
    def _stored(self, ts, **fields):
        items = findings_store._load()
        items.append({"ts": ts, "status": "open", "severity": "warning",
                      "source": findings_store.RESIDENT_SOURCE, **fields})
        findings_store._write(items)

    def _open(self, ts):
        return cases.case_id("findings", ts) in {
            c["id"] for c in cases.list_cases("open")}

    def test_a_follow_up_that_came_back_after_brains_fix_stays_open(self):
        # the follow-up look files it with only a detail (server.py)
        self._stored(1_700_000_900, source="followup",
                     source_title="Follow-up looks",
                     text="Hall plug unavailable — came back after brAIn's fix",
                     detail="It came back 3 days after brAIn's fix.")
        self.assertTrue(self._open(1_700_000_900))
        listed = {r["ts"]: r for r in findings_store.listing()["findings"]}
        self.assertEqual(listed[1_700_000_900]["status"], "open")

    def test_a_step_held_in_a_plan_items_or_a_self_edit_is_a_step(self):
        for ts, extra in (
                (1_700_001_000, {"plan": {"can_fix": True, "summary":
                                          "Turn the schedule back on.",
                                          "steps": ["Turn it on."]}}),
                (1_700_001_100, {"items": ["Hall plug", "Desk lamp"]}),
                (1_700_001_200, {"self_edit": {"key": "voice",
                                               "value": "Aria"}})):
            with self.subTest(next(iter(extra))):
                row = {"ts": ts, "status": "open",
                       "source": findings_store.RESIDENT_SOURCE,
                       "text": f"Row {ts}", **extra}
                self.assertFalse(findings_store.stepless(row))
                self.assertTrue(findings_store.stepless(
                    {k: v for k, v in row.items() if k not in extra}))
