"""A print the printer stopped itself is one card, and a person's pause is none.

Report 432: a print went from running to pause in the small hours while the
printer's own problem sensor turned on and its failure detection read
"failure"; it sat paused at 10 % with the bed hot, and an earlier failed
print that afternoon produced nothing either. `chore.print_stopped` reads
the status, the problem flag, the progress and the bed off the same device
— states the snapshot already holds — and files one row; a pause with no
flag is somebody pressing pause and files nothing.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import urgency  # noqa: E402
from checks import chores  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402

STATUS = "sensor.attic_printer_status"


def printer(status="pause", *, problem="on", detection="failure",
            bed="65", unit="°C", platform="bruh_bambu", flags=True):
    snap = house()
    snap["devices"].append({"id": "dev_ap", "name": "Attic printer",
                            "manufacturer": "Bambu Lab", "model": "A1"})
    rows = [
        (STATUS, status, "Attic printer Status", "status", {}),
        ("sensor.attic_printer_progress", "10", "Attic printer Progress",
         "progress", {"unit_of_measurement": "%"}),
        ("sensor.attic_printer_bed_temperature", bed,
         "Attic printer Bed temperature", "bed",
         {"device_class": "temperature", "unit_of_measurement": unit}),
    ]
    if flags:
        rows += [
            ("binary_sensor.attic_printer_print_problem", problem,
             "Attic printer Print problem", "print_problem",
             {"device_class": "problem"}),
            ("sensor.attic_printer_failure_detection", detection,
             "Attic printer Failure detection", "failure_detection", {}),
        ]
    for eid, state, name, key, attrs in rows:
        snap["states"][eid] = {"state": state, "last_updated": iso(3 * 3600),
                               "last_changed": iso(3 * 3600),
                               "attributes": {"friendly_name": name, **attrs}}
        snap["entities"].append({"entity_id": eid, "platform": platform,
                                 "device_id": "dev_ap",
                                 "translation_key": key})
    return snap


def rows(snap):
    return chores.print_stopped(snap, NOW)


class TestAStoppedPrint(unittest.TestCase):
    def test_a_pause_on_the_printers_own_detection_is_one_row(self):
        got = rows(printer())
        self.assertEqual(len(got), 1)
        row = got[0]
        self.assertEqual(row["entity_id"], STATUS)
        self.assertEqual(row["text"], "Attic printer stopped a print on its "
                                      "own failure detection")
        self.assertIn("10 %", row["detail"])
        self.assertIn("3 hours ago", row["detail"])
        self.assertIn("still hot", row["detail"])
        self.assertNotIn("sensor.", row["detail"])

    def test_a_failed_print_with_the_problem_flag(self):
        got = rows(printer("failed", detection="idle"))
        self.assertEqual(len(got), 1)

    def test_the_detection_alone_is_enough(self):
        self.assertEqual(len(rows(printer(problem="off"))), 1)

    def test_a_bed_that_has_cooled_says_so(self):
        got = rows(printer(bed="24"))
        self.assertIn("cooled down", got[0]["detail"])

    def test_fahrenheit(self):
        got = rows(printer(bed="149", unit="°F"))
        self.assertIn("still hot", got[0]["detail"])

    def test_another_printer_integration_named_in_words(self):
        snap = printer(platform="mqtt")
        for e in snap["entities"]:
            e.pop("translation_key", None)
        self.assertEqual(len(rows(snap)), 1)


class TestNothingToSay(unittest.TestCase):
    def test_a_person_pressing_pause(self):
        self.assertEqual(rows(printer(problem="off", detection="watching")),
                         [])
        self.assertEqual(rows(printer(flags=False)), [])

    def test_a_resumed_or_finished_print(self):
        for status in ("running", "finish", "idle"):
            self.assertEqual(rows(printer(status)), [], status)

    def test_a_paused_washer_is_not_a_printer(self):
        snap = printer()
        snap["devices"][-1].update(name="Utility washer",
                                   manufacturer="Generic", model="")
        for e in snap["entities"]:
            e["platform"] = "mqtt"
        self.assertEqual(rows(snap), [])


class TestItIsACheckLikeAnyOther(unittest.TestCase):
    def test_catalogued_and_it_clears_when_it_runs_clean(self):
        self.assertIsNotNone(checks.get_check("chore.print_stopped"))
        result = checks.run_all(printer("running"), NOW,
                                only=["chore.print_stopped"])
        self.assertIn("chore.print_stopped", result["ran"])
        self.assertEqual(result["findings"], [])

    def test_quiet_hours_hold_it(self):
        self.assertEqual(urgency.urgency_of(
            {"source": "check:chore.print_stopped"}), "today")

    def test_an_answer_stands_it_down(self):
        snap = printer()
        snap["facts"] = {STATUS: {"chore.print_stopped"}}
        self.assertEqual(rows(snap), [])


if __name__ == "__main__":
    unittest.main()
