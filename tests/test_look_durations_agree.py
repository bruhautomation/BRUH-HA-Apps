#!/usr/bin/env python3
"""The look under a finding states the finding's own durations (#771).

A house's robot vacuum was filed as unavailable "for 3 days" (the check
read it off the entity's history), and the look written under it said the
vacuum had been offline "for about 14 hours": two durations for one fact on
one card. `quotes_other_counts` (#443) already held a look to the row's
counts, but only where both counted the same word, and "hours" is not
"days".

Now a look's stated duration is read against the durations in the row's
own detail (the figure the check measured from the entity's history):
when the detail states one, the look says that one; when it states several
and the look's agrees with none, the look's sentence goes. Durations that
agree, and a look that states none, are left exactly as written. The first
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
        row = {"text": "Front door lock battery is low",
               "detail": "The front door lock's battery has read 8% for "
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

    def test_several_durations_and_none_agree_drops_that_sentence(self):
        row = {"text": "The freezer door was left open",
               "detail": "It was open for 12 minutes on Monday and for "
                         "40 minutes on Wednesday."}
        out = findings_store.shown_look(
            look("It was open for 3 hours. The seal looks worn."), row)
        self.assertEqual(out["reason"], "The seal looks worn.")


class TestTheFirstLookIsTold(unittest.TestCase):
    def test_the_rule_is_in_the_prompt(self):
        self.assertIn("duration", resident.FIRST_LOOK_SYSTEM.lower())
        self.assertIn("same unit", resident.FIRST_LOOK_SYSTEM)


if __name__ == "__main__":
    unittest.main()
