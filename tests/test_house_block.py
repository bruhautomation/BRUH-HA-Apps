#!/usr/bin/env python3
"""What brAIn measured, on its way into a prompt.

The analyst used to be handed entities and history and no hint that seven
measurements had already been made over the same data — so it re-derived
"what is normal here" on every run and reached a different answer each
time, while the tab beside it carried the real one. The brief and the
weekly report had the same hole and a second one: neither read the memory
document, so both could say the hall is cold in a house whose hall is
always cold.

Three things have to hold and each is a different failure. The block is
BUDGETED (2 KB is 2 KB even on a house with forty measured rooms), it is
ABSENT rather than empty when nothing has been measured, and it reaches
all four prompt builders rather than the one somebody remembered.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import brief  # noqa: E402
import categories  # noqa: E402
import house  # noqa: E402
import weekly  # noqa: E402

NOW = 1_800_000_000.0

CATEGORY = {"id": "climate", "title": "Climate", "icon": "🌡️",
            "focus": "Rooms and their temperatures."}


def store(state, summary, **fields):
    base = {"unit": "rooms", "need": 1, "have": 1, "now": NOW,
            "summary": summary}
    base.update(fields)
    return house.progress(state=state, **base)


def snapshot(**states):
    """A house where the named stores are ready and the rest are not."""
    stores = {}
    for name in house.STORES:
        said = states.get(name)
        stores[name] = store(house.READY, said) if said else store(
            house.NOT_STARTED, "Nothing measured yet.", have=0)
    return {"generated_at": int(NOW), "stores": stores}


class TestTheBlockItself(unittest.TestCase):
    def test_nothing_ready_is_no_block_at_all(self):
        """An empty heading reads as "measured, and nothing found", which
        is the opposite of what a fresh install means."""
        self.assertEqual(categories.house_block(snapshot()), "")
        self.assertEqual(categories.house_block({}), "")
        self.assertEqual(categories.house_block(None), "")

    def test_only_a_ready_measurement_is_stated(self):
        snap = snapshot(rhythm="Weekdays wake about 07:10.")
        snap["stores"]["thermal"] = store(
            house.STALE, "Measured 9 days ago.", have=3)
        snap["stores"]["closures"] = store(
            house.COLLECTING, "3 of the 24 hours one needs.", have=3)
        snap["stores"]["appliances"] = store(
            house.UNAVAILABLE, "No power sensor.", have=0)
        block = categories.house_block(snap)
        self.assertIn("07:10", block)
        for absent in ("9 days ago", "24 hours one needs", "No power sensor"):
            self.assertNotIn(absent, block)

    def test_the_sentence_is_the_stores_own(self):
        """Never one composed here: every floor and caveat in it belongs
        to the module that owns the measurement."""
        snap = snapshot(thermal="2 rooms measured against sensor.outside.")
        self.assertIn("- thermal: 2 rooms measured against sensor.outside.",
                      categories.house_block(snap))

    def test_it_never_exceeds_its_budget(self):
        """2 KB, taken from nothing else. Memory has its own budget in the
        bundle and the findings block has no cap at all, and neither may
        be pushed out by a house with a great many measurements."""
        snap = snapshot(**{name: f"{name} " + "x" * 900
                           for name in house.STORES})
        block = categories.house_block(snap)
        self.assertLessEqual(len(block), categories.HOUSE_CHARS)
        # And it is capped by dropping whole lines, not by cutting one:
        # half a measurement reads exactly like a whole one.
        for line in block.split("\n")[1:]:
            self.assertTrue(line.endswith("x"), line[-40:])

    def test_a_smaller_budget_still_carries_the_heading(self):
        snap = snapshot(rhythm="Up at seven.", energy="84 kWh last week.")
        block = categories.house_block(snap, limit=10)
        self.assertTrue(block.startswith("WHAT brAIn HAS ALREADY MEASURED"))
        self.assertNotIn("- rhythm", block)

    def test_it_names_the_tool_that_reads_the_rest(self):
        """The block is a summary; the drill-down is a tool the analyst
        already has, and a summary that does not say so is a dead end."""
        block = categories.house_block(snapshot(rhythm="Up at seven."))
        self.assertIn("get_house_model", block)

    def test_it_says_an_absent_measurement_is_not_a_quiet_house(self):
        block = categories.house_block(snapshot(rhythm="Up at seven."))
        self.assertIn("has not been made yet", block)


class TestTheMemoryExcerpt(unittest.TestCase):
    def test_an_empty_document_is_no_block(self):
        self.assertEqual(categories.memory_excerpt(""), "")
        self.assertEqual(categories.memory_excerpt(None), "")
        self.assertEqual(categories.memory_excerpt("   \n  "), "")

    def test_it_is_cut_between_lines(self):
        """A fact truncated mid-sentence is a fact stated wrongly."""
        doc = "- the hall is always cold\n- the cat opens the back door\n"
        out = categories.memory_excerpt(doc, limit=40)
        self.assertIn("the hall is always cold", out)
        self.assertNotIn("the cat opens", out)

    def test_a_short_document_arrives_whole(self):
        out = categories.memory_excerpt("- the hall is always cold")
        self.assertIn("- the hall is always cold", out)
        self.assertIn("Do not contradict them", out)


class TestItReachesEveryPrompt(unittest.TestCase):
    BLOCK = categories.house_block(
        snapshot(rhythm="Weekdays wake about 07:10.",
                 thermal="2 rooms measured against sensor.outside."))

    def test_the_snapshot_path_carries_it(self):
        prompt = categories.build_prompt(
            CATEGORY, {"entities": []}, house=self.BLOCK)
        self.assertIn("07:10", prompt)
        self.assertIn("WHAT brAIn HAS ALREADY MEASURED", prompt)

    def test_the_search_path_carries_it(self):
        prompt = categories.build_orientation_prompt(
            CATEGORY, {"entity_count": 3}, house=self.BLOCK)
        self.assertIn("07:10", prompt)

    def test_both_prompt_builders_place_it_the_same_way(self):
        """`_framing` is shared on purpose — the searching path quietly
        losing a section the snapshot path has is the drift it exists to
        prevent."""
        a = categories.build_prompt(CATEGORY, {}, house=self.BLOCK)
        b = categories.build_orientation_prompt(CATEGORY, {}, house=self.BLOCK)
        head = "WHAT brAIn HAS ALREADY MEASURED"
        self.assertEqual(a[:a.index(head)], b[:b.index(head)])

    def test_neither_carries_a_heading_when_nothing_is_measured(self):
        prompt = categories.build_prompt(CATEGORY, {}, house="")
        self.assertNotIn("WHAT brAIn HAS ALREADY MEASURED", prompt)

    def test_it_does_not_eat_the_findings_or_the_memory_block(self):
        """Its own budget, taken from nothing else."""
        prompt = categories.build_prompt(
            CATEGORY, {}, house=self.BLOCK,
            knowledge="DEAD ENDS: the porch sensor",
            findings="ALREADY REPORTED: the freezer is warm")
        self.assertIn("DEAD ENDS", prompt)
        self.assertIn("ALREADY REPORTED", prompt)
        self.assertIn("07:10", prompt)

    def test_the_morning_brief_gets_the_house_and_the_memory(self):
        state = {"house": self.BLOCK,
                 "memory": categories.memory_excerpt("- the hall is cold")}
        prompt = brief.frame(["one new finding"], state)
        self.assertIn("07:10", prompt)
        self.assertIn("the hall is cold", prompt)

    def test_the_brief_without_them_is_the_prompt_it_always_was(self):
        prompt = brief.frame(["one new finding"], {})
        self.assertNotIn("WHAT brAIn HAS ALREADY MEASURED", prompt)
        self.assertNotIn("WHAT IS ALREADY KNOWN", prompt)
        self.assertIn("one new finding", prompt)

    def test_the_weekly_report_gets_the_house_and_the_memory(self):
        state = {"findings": {"settled": 1, "still_open": 2},
                 "learned": {"available": True, "total": 0},
                 "energy": {"available": False, "reason": "no meters"},
                 "house": self.BLOCK,
                 "memory": categories.memory_excerpt("- the hall is cold")}
        prompt = weekly.frame(state)
        self.assertIn("07:10", prompt)
        self.assertIn("the hall is cold", prompt)

    def test_the_weekly_report_still_ends_on_its_instruction(self):
        """The blocks go BEFORE the closing instruction, or the model's
        last line is a memory excerpt rather than what to do."""
        state = {"findings": {}, "learned": {"available": True},
                 "energy": {}, "house": self.BLOCK, "memory": "x"}
        prompt = weekly.frame(state)
        self.assertTrue(prompt.rstrip().endswith("nothing else."))
        self.assertLess(prompt.index("07:10"), prompt.index("nothing else."))


if __name__ == "__main__":
    unittest.main()
