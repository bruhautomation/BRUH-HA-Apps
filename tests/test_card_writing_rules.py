#!/usr/bin/env python3
"""How an insight card is written, from a house that read every one of them.

Eight things a real house found wrong with its cards, each a rule now:

  * an all-clear took a card slot like any other, with the title and the
    summary sometimes disagreeing about whether anything needed doing —
    the contract asks an all-normal card to say so in one short sentence,
    and the panel sorts a card with no status and nothing on Needs you
    below the ones that need something (`cardNeedsSomething`);
  * the title's number restated in the summary, units nobody can read
    ("°F·h", "2.4x", "degree-hours"), a partial day against whole days;
  * "more", "again", "outdated" about runs the reader never saw;
  * brAIn's own process in the owner's prose ("the tool's cap",
    "baseline", "readings window");
  * dates, times and units written five ways — and a contract that said
    "6:42 PM" to a 24-hour house; the prompt now names the house's clock;
  * a card calling a device fine while a finding beside it said otherwise,
    and two cards about one air conditioner on one day — the findings
    block forbids the first and the other cards are handed by title;
  * an unusual reading with no cause, or a bare "not a leak";
  * a missing event blamed on the house when its sensor was offline.

The contract is held under its size ceiling (`test_model_plan`), so what
these rules cost was paid for by cutting words, not by moving the ceiling.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import categories  # noqa: E402
import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

CONTRACT = categories._CARD_CONTRACT
SYSTEMS = (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM)


class TestTheContractCarriesEachRule(unittest.TestCase):
    def rule(self, *phrases):
        for phrase in phrases:
            self.assertIn(phrase, CONTRACT)
            for system in SYSTEMS:
                self.assertIn(phrase, system)

    def test_an_all_clear_is_one_short_sentence_that_agrees_with_its_title(self):
        self.rule("When all is normal, title and summary both say so",
                  "none with a status", '"html": ""')

    def test_the_summary_adds_to_the_titles_number_rather_than_repeating_it(self):
        self.rule("inside its comparison and reason, never restated alone")

    def test_no_unit_a_resident_would_look_up(self):
        self.rule("No unit to look up", "°F·h", "degree-hours", '"2.4x"',
                  '"twice the usual"')

    def test_a_partial_day_is_compared_with_the_same_hours(self):
        self.rule("A partial day is compared with the same hours")

    def test_more_or_again_carries_the_earlier_value(self):
        self.rule('"More", "again", "still", "new" or "outdated" only with '
                  "the earlier value stated in the same card",
                  "never answer a worry nobody raised")

    def test_no_process_words_in_the_owners_prose(self):
        self.rule("never a tool or its cap", '"baseline"', '"readings window"',
                  '"this hour of the week"', '"at least 10"')

    def test_one_style_per_kind_of_value(self):
        self.rule("One style:", "the house's clock (the prompt says which",
                  '"Tue 13 Oct"', '"13–19 Oct"', '"6 h 42 min"', '"66 °F"')
        # The old example put a 12-hour time in front of every house.
        self.assertNotIn('("6:42 PM")', CONTRACT)

    def test_an_unusual_reading_names_a_cause_or_a_next_step(self):
        self.rule("Calling a reading unusual names the cause you checked",
                  "gives one next step")

    def test_a_missing_event_checks_its_sensor_first(self):
        self.rule("check its sensor's availability and battery",
                  "the sensor is the story")

    def test_a_conclusion_of_fine_files_no_finding(self):
        self.rule("A conclusion of fine files none")

    def test_the_contract_stays_under_its_ceiling(self):
        self.assertLess(len(CONTRACT), 9100)


class TestThePromptNamesTheHousesClock(unittest.TestCase):
    CAT = {"id": "energy", "title": "Energy", "focus": "Where the power goes."}

    def test_each_style_and_neither(self):
        for builder in (categories.build_prompt,
                        categories.build_orientation_prompt):
            p24 = builder(self.CAT, {}, clock="24h")
            p12 = builder(self.CAT, {}, clock="12h")
            none = builder(self.CAT, {})
            self.assertIn("like 18:42", p24)
            self.assertNotIn("6:42 PM", p24)
            self.assertIn("like 6:42 PM", p12)
            self.assertNotIn("CLOCK:", none)

    def test_other_cards_reach_both_builders(self):
        block = "OTHER CARDS ON THIS DASHBOARD:\n- Cooling: 3 h on Tuesday"
        for builder in (categories.build_prompt,
                        categories.build_orientation_prompt):
            self.assertIn("Cooling: 3 h on Tuesday",
                          builder(self.CAT, {}, others=block))


FREEZER = {"text": "The garage freezer has run warm for two days",
           "detail": "Averaged -9.5 °C between 02:00 and 06:00 on 8 Oct.",
           "severity": "warning", "entity_id": "sensor.garage_freezer_temp",
           "source": "check:base.unusual"}


class TestACardIsTold(ClearCase):
    def setUp(self):
        super().setUp()
        self._clock = self.server._clock_style
        self.server._clock_style = lambda: "24h"

    def tearDown(self):
        self.server._clock_style = self._clock
        super().tearDown()

    def test_never_to_call_fine_what_a_finding_says_is_not(self):
        findings_store.add_many([dict(FREEZER)])
        self.generate()
        prompt = self.prompts[-1]
        self.assertIn("Never call a device, door or automation fine, safe "
                      "or normal while a row here says otherwise", prompt)
        self.assertIn("is doubtful, and the card says so", prompt)

    def test_the_houses_clock(self):
        self.generate()
        self.assertIn("like 18:42", self.prompts[-1])

    def test_the_other_cards_titles_and_not_its_own(self):
        self.reply["title"] = "Living room AC: 3 h cooling on Tuesday"
        self.generate("energy")
        self.reply["title"] = "Evening lights"
        self.generate()               # lighting, once, so it has a title
        self.generate()               # and again: its own is not "another"
        prompt = self.prompts[-1]
        self.assertIn("OTHER CARDS ON THIS DASHBOARD", prompt)
        others = prompt.split("OTHER CARDS ON THIS DASHBOARD", 1)[1]
        others = others.split("\n\n", 1)[0]
        self.assertIn("Living room AC: 3 h cooling on Tuesday", others)
        self.assertNotIn("Evening lights", others)

    def test_no_block_when_there_is_no_other_card(self):
        self.generate()
        self.assertNotIn("OTHER CARDS ON THIS DASHBOARD", self.prompts[-1])


def _lift(js: str, name: str) -> str:
    """One top-level `function name(...) {...}` out of app.js."""
    match = re.search(r"^function " + re.escape(name) + r"\(.*?^\}\n",
                      js, re.S | re.M)
    assert match, name
    return match.group(0)


class TestAnAllClearSortsBelowTheCardsThatNeedSomething(unittest.TestCase):
    """Driven under node: the real functions, lifted out of app.js."""

    @classmethod
    def setUpClass(cls):
        js = (PANEL / "app.js").read_text(encoding="utf-8")
        const = re.search(r"^const ATTENTION_STATUSES = .*?;\n", js, re.M)
        assert const, "ATTENTION_STATUSES"
        cls.src = (const.group(0) + _lift(js, "cardNeedsSomething")
                   + _lift(js, "attentionFirst"))

    def run_js(self, body: str):
        res = subprocess.run(["node", "-e", self.src + body],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_which_cards_need_something(self):
        out = self.run_js("""
          const cases = [
            [null, 0],
            [{highlights: [{label: "a", value: "1"}]}, 0],
            [{highlights: [{label: "a", value: "1", status: "good"}]}, 0],
            [{highlights: [{label: "a", value: "1", status: "warning"}]}, 0],
            [{highlights: [{label: "a", value: "1", status: "critical"}]}, 0],
            [{highlights: []}, 1],
            [{}, 0],
          ];
          console.log(JSON.stringify(cases.map(([i, n]) => cardNeedsSomething(i, n))));
        """)
        self.assertEqual(out, [True, False, False, True, True, True, False])

    def test_the_order_is_stable_within_each_half(self):
        out = self.run_js("""
          const items = ["q1", "L1", "q2", "L2", "q3"];
          console.log(JSON.stringify(attentionFirst(items, (x) => x[0] === "L")));
        """)
        self.assertEqual(out, ["L1", "L2", "q1", "q2", "q3"])

    def test_render_orders_the_grid_through_them(self):
        js = (PANEL / "app.js").read_text(encoding="utf-8")
        render = _lift(js, "render")
        self.assertIn("attentionFirst(", render)
        self.assertIn("cardNeedsSomething(", render)


if __name__ == "__main__":
    unittest.main()
