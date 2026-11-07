#!/usr/bin/env python3
"""brAIn's own reports offer one-tap reasons on Ignore, and the next look
reads the one chosen.

The Resident's reports ("brAIn, watching the house") were ignored five
times in eight with no word (#577, #739): they have no mute, so Ignore is
the one no, and an Ignore with no reason teaches nothing. Their Ignore box
now offers three short reasons (`answers.RESIDENT_REASONS`). A chip is a
typed reason — the panel fills the box with it and sends it on the same
route — so it is kept as the correction under the entities the report was
about, and the next investigation of that entity is handed it in its
memory block. Driven through the real route with each chip, and the
broken-sensor chip also marks the sensor broken for every reading check.
"""

import asyncio
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import answers  # noqa: E402
import corrections  # noqa: E402
import findings_store  # noqa: E402
import resident  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

APP_JS = TESTS_DIR.parent / "brain" / "panel" / "app.js"


def resident_row(entity: str) -> dict:
    entry, created = findings_store.add(
        "The cellar sump pump ran six times overnight",
        severity="warning", detail="It usually runs twice.",
        fix="Look at the float switch", source=findings_store.RESIDENT_SOURCE,
        source_title="brAIn, watching the house", entity_id=entity)
    assert created
    return entry


class TestTheChipsAreOffered(unittest.TestCase):
    def test_a_resident_report_offers_them_on_ignore(self):
        case = answers._request_case({"ts": 5, "source": "resident",
                                      "kind": "problem"})
        wrong = [a for a in answers.answers(case) if a["verb"] == "wrong"]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]["reasons"], list(answers.RESIDENT_REASONS))
        self.assertLessEqual(len(wrong[0]["reasons"]), 3)

    def test_a_house_check_does_not(self):
        case = answers._request_case({"ts": 5, "source": "check:dev.frozen",
                                      "kind": "problem"})
        self.assertFalse(any(a.get("reasons") for a in answers.answers(case)))

    def test_every_chip_is_a_correction_not_a_snooze(self):
        for reason in answers.RESIDENT_REASONS:
            with self.subTest(reason=reason):
                self.assertFalse(corrections.puts_off(reason))
                self.assertFalse(corrections.conditional(reason))
        self.assertTrue(corrections.gone_for_good("The sensor is broken"))

    def test_the_panel_sends_a_chip_as_the_typed_reason(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn("reasons: answer.reasons", js)
        self.assertIn("ta.value = reason;", js)


class TestThePickedChipReachesTheNextLook(RouteCase):
    ENTITY = "switch.cellar_sump_pump"

    def pick(self, reason: str) -> str:
        row = resident_row(self.ENTITY)
        case = answers._request_case(row)
        wrong = next(a for a in answers.answers(case) if a["verb"] == "wrong")
        self.assertIn(reason, wrong["reasons"])

        async def body(client):
            res = await client.post(wrong["route"], json={"note": reason})
            self.assertEqual(res.status, 200, await res.text())
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            return self.server._memory_block(entities=[self.ENTITY])

        memory = self.drive(body)
        return resident.investigate_prompt(
            {"subject": self.ENTITY, "text": "sump pump ran again"}, memory)

    def test_already_known(self):
        prompt = self.pick("Already known")
        self.assertIn("Already known", prompt)
        self.assertIn("sump pump ran six times", prompt)

    def test_not_an_issue_here(self):
        self.assertIn("Not an issue here", self.pick("Not an issue here"))

    def test_the_sensor_is_broken_marks_it_broken(self):
        self.assertIn("The sensor is broken", self.pick("The sensor is broken"))
        self.assertIn(self.ENTITY, corrections.known_faulty())


if __name__ == "__main__":
    unittest.main()
