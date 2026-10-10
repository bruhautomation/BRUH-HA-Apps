#!/usr/bin/env python3
"""An insight card says what it counted, and agrees with the finding beside it.

Two things a real house reported about its cards:

  * a title that does not say what was counted ("evenings eased from 14
    openings to 5" — openings of what?), a kWh figure in the title that
    never names the appliance and a summary that leads with a different
    figure, and a card telling the household about brAIn's own data limits
    ("the recorder keeps only 7 nights, so there is no 14-night
    comparison"). The card contract now says so (`_CARD_CONTRACT`).
  * a card and an open finding about the same device telling the same
    story with different numbers and different names. The findings handed
    to a card carry each row's name, figures and window, and the block that
    lists them tells the run to quote them and mention the row in one
    clause rather than retell it. That rule rides the block rather than
    the contract: it matters exactly when there is a row to quote, and the
    contract is held under a size ceiling (`test_model_plan`).
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import categories  # noqa: E402
import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

CONTRACT = categories._CARD_CONTRACT


class TestTheCardContract(unittest.TestCase):
    def test_the_title_names_what_was_measured(self):
        self.assertIn("The title names the device, door or room measured",
                      CONTRACT)
        self.assertIn('never "14 openings to 5"', CONTRACT)

    def test_the_titles_number_is_in_the_summary_with_one_meaning(self):
        self.assertIn("a number in the title appears in the summary with "
                      "the same meaning", CONTRACT)

    def test_brains_own_data_limits_are_not_the_households_news(self):
        self.assertIn("Never mention the recorder, its retention, missing "
                      "history or a comparison it could not make", CONTRACT)
        self.assertIn("make the comparison the data does allow", CONTRACT)

    def test_the_existing_rules_stand(self):
        for rule in ("NO samples is missing data, never zero",
                     "leave it out of BOTH sides", '"signal 7"',
                     "Convert entity_ids to friendly names"):
            self.assertIn(rule, CONTRACT)
        for system in (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM):
            self.assertIn("The title names the device", system)


FREEZER = {"text": "The garage freezer has run warm for two days",
           "detail": "Averaged -9.5 °C between 02:00 and 06:00 on 8 Oct, "
                     "against -18 °C normally.",
           "severity": "warning", "entity_id": "sensor.garage_freezer_temp",
           "source": "check:base.unusual"}


class TestACardIsHandedTheFindingBesideIt(ClearCase):
    def setUp(self):
        super().setUp()
        self._names = dict(self.server._NAMES)
        self.server._NAMES.clear()
        self.server._NAMES["sensor.garage_freezer_temp"] = {
            "name": "Garage freezer", "area": "Garage"}
        findings_store.add_many([dict(FREEZER)])

    def tearDown(self):
        self.server._NAMES.clear()
        self.server._NAMES.update(self._names)
        super().tearDown()

    def test_the_prompt_carries_the_rows_name_figures_and_the_rule(self):
        self.generate()
        prompt = self.prompts[-1]
        self.assertIn(FREEZER["text"], prompt)
        self.assertIn("Garage freezer", prompt)
        self.assertIn("-9.5 °C between 02:00 and 06:00", prompt)
        self.assertIn("quote that row's figures and time window", prompt)
        self.assertIn("mention it in one clause", prompt)

    def test_the_refresh_fingerprint_does_not_move_with_a_rows_figures(self):
        """A check rewrites its detail every pass; a card that refreshed
        every time a number on somebody else's row moved would be a timer."""
        before = findings_store.prompt_block(("lighting",))
        findings_store.refresh_details([{**FREEZER,
                                         "detail": "Averaged -8 °C now."}])
        self.assertEqual(findings_store.prompt_block(("lighting",)), before)


if __name__ == "__main__":
    unittest.main()
