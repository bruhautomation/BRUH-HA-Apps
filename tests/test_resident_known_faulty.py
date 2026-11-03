"""A sensor the owner called broken is not evidence for the Resident.

"This sensor is broken, please ignore it" on a Resident case was kept as a
general correction and tied to nothing, so the next look drew a conclusion
from the same sensor. A reason that says a device is broken or finished with
(`corrections.gone_for_good`), given as a Wrong on any row, now marks every
entity of that row known-faulty (`corrections.known_faulty`), and a case
that rests on one is refused (`resident.faulty_case`)."""
import sys
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import corrections  # noqa: E402
import facts_store  # noqa: E402
import resident  # noqa: E402


class TestKnownFaulty(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = facts_store.FACTS_FILE
        facts_store.FACTS_FILE = Path(tmp.name) / "facts.json"
        self.addCleanup(setattr, facts_store, "FACTS_FILE", old)

    def wrong(self, eid, note, rule="resident"):
        facts_store.add(facts_store.exception_text("a report", note),
                        subject=eid, source="correction",
                        predicate=facts_store.EXCEPTION_PREFIX + rule,
                        confidence=0.95)

    def test_a_broken_reason_marks_the_entity(self):
        self.wrong("sensor.pump_pressure",
                   "This sensor is broken, please ignore it")
        self.assertIn("sensor.pump_pressure", corrections.known_faulty())

    def test_an_ordinary_reason_does_not(self):
        self.wrong("sensor.pump_pressure", "It reads low while the pump runs")
        self.assertEqual(corrections.known_faulty(), {})

    def test_a_case_resting_on_it_is_refused_and_another_is_not(self):
        self.wrong("sensor.pump_pressure",
                   "This sensor is broken, please ignore it")
        faulty = corrections.known_faulty()
        case = {"claim": "Pressure goes below zero when the pump runs",
                "entity_id": "switch.pump",
                "evidence": [{"entity": "sensor.pump_pressure", "value": "-3"}]}
        self.assertTrue(resident.faulty_case(case, [], faulty))
        other = {"claim": "x", "entity_id": "switch.pump",
                 "evidence": [{"entity": "sensor.other", "value": "1"}]}
        self.assertEqual(resident.faulty_case(other, [], faulty), "")
        self.assertTrue(resident.faulty_case(other, ["sensor.pump_pressure"],
                                             faulty))


if __name__ == "__main__":
    unittest.main()
