#!/usr/bin/env python3
"""The look under a finding states the finding's own durations (#771).

A house's robot vacuum was filed as unavailable "for 3 days" (the check
read it off the entity's history), and the look written under it said the
vacuum had been offline "for about 14 hours": two durations for one fact on
one card. `quotes_other_counts` (#443) already held a look to the row's
counts, but only where both counted the same word, and "hours" is not
"days".

Now a look's stated duration is read against the durations in the row's
own detail (the figure the check measured from the entity's history), and
only where it is provably the same fact: the row states one duration and
the look's sentence says the thing was in the same state ("offline" for
"unavailable"). Then the look says the row's. Another fact ("ran for 20
minutes"), several durations on the row, a high-stakes row, and agreeing
durations are left exactly as written. The first
look is told the same thing (`resident.FIRST_LOOK_SYSTEM`).
"""

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

VACUUM = {
    "text": "Robot vacuum has been unavailable for 3 days",
    "detail": "Robot vacuum (vacuum.roborock_s7) has been unavailable for "
              "3 days, since Friday at 09:12.",
    "fix": "Check the vacuum is on its dock and the dock has power.",
    "source": "check:dev.unavailable",
    "entity_id": "vacuum.roborock_s7",
}


def look(reason):
    return {"verdict": "elevated", "reason": reason, "at": 1_700_000_000}


class TestTheVacuumReplay(StoresCase):
    def test_days_in_both_places(self):
        items = findings_store._load()
        items.append({**VACUUM, "ts": 1_700_000_400, "status": "open",
                      "severity": "warning",
                      "triage": look("It has been offline for about 14 hours, "
                                     "which is longer than a charging gap.")})
        findings_store._write(items)
        listed = next(r for r in findings_store.listing()["findings"]
                      if r["ts"] == 1_700_000_400)
        case = cases.get(cases.case_id("findings", 1_700_000_400))
        for row in (listed, case):
            said = row["triage"]["reason"]
            self.assertIn("3 days", said)
            self.assertNotIn("hours", said)
            self.assertIn("longer than a charging gap", said)
        self.assertIn("3 days", listed["detail"])


class TestShownLook(unittest.TestCase):
    def test_a_second_example_weeks_against_days(self):
        row = {"text": "Garden sensor battery is low",
               "detail": "The garden sensor's battery has read 8% for "
                         "2 weeks."}
        out = findings_store.shown_look(
            look("The battery has sat at 8% for 10 days, so it is not "
                 "draining fast."), row)
        self.assertIn("for 2 weeks", out["reason"])
        self.assertNotIn("10 days", out["reason"])

    def test_vague_hours_against_days(self):
        out = findings_store.shown_look(
            look("It has been unreachable for hours."), VACUUM)
        self.assertEqual(out["reason"], "It has been unreachable for 3 days.")

    def test_agreeing_durations_are_left_alone(self):
        for reason in ("It has been offline for 3 days now.",
                       "It has been offline for about 72 hours.",
                       "The dock reports no fault."):
            with self.subTest(reason):
                out = findings_store.shown_look(look(reason), VACUUM)
                self.assertEqual(out["reason"], reason)

    def test_another_fact_with_its_own_duration_is_left_alone(self):
        # the reviewer's two counter-examples: a cycle is not the outage,
        # and a row with several durations gives no one figure to say
        reason = "It ran for 20 minutes, a normal cycle, before it dropped."
        self.assertEqual(
            findings_store.shown_look(look(reason), VACUUM)["reason"], reason)
        row = {"text": "The freezer door was left open",
               "detail": "It was open for 12 minutes on Monday and for "
                         "40 minutes on Wednesday."}
        reason = "Door opened for 5 minutes each time. The seal looks worn."
        # (the card itself still holds this look back under #443's rule —
        # "5 minutes" beside a detail counting other minutes — which is not
        # this rule's to change)
        self.assertEqual(findings_store.with_row_durations(reason, row),
                         reason)

    def test_a_high_stakes_rows_look_is_never_rewritten(self):
        row = {"text": "Leak sensor under the sink has been unavailable",
               "detail": "The kitchen leak sensor has been unavailable for "
                         "3 days.", "severity": "warning"}
        reason = "It has been offline for about 14 hours."
        self.assertEqual(
            findings_store.shown_look(look(reason), row)["reason"], reason)


class TestTheFirstLookIsTold(unittest.TestCase):
    def test_the_rule_is_in_the_prompt(self):
        self.assertIn("duration", resident.FIRST_LOOK_SYSTEM.lower())
        self.assertIn("same unit", resident.FIRST_LOOK_SYSTEM)


if __name__ == "__main__":
    unittest.main()
