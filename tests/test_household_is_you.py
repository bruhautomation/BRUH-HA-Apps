#!/usr/bin/env python3
"""The household is "you", and what it sees is called by its name (#562).

A house's look conclusions said "The homeowner said…" and "The owner
wants…" beside cards saying "You've marked…", a finding called the
dashboard "Morph", and a question ended "Where to look: brAIn". The rule
is one block of the shared prompt kit (`prompt_kit.ADDRESS`, inside the
IDENTITY every assembled prompt carries, and in the Resident's own rules:
"you", and the dashboard by its name on screen), and
`house_words.household` is the floor under a model's row: it rewrites
"the homeowner" as a subject or possessive and "The owner" / "The user"
opening a sentence with a verb, and leaves somebody else's owner alone.
"Morph" has no floor: brAIn's own questions about Morph's code name it on
purpose. The examples are invented.
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402
import resident  # noqa: E402
from devloop import verify  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

THIRD_PERSON = re.compile(r"\b[Tt]he (?:home\s?owner|owner|user)\b(?!\s+of\b)")

# What a model wrote, as a house's rows carried it, in other words.
MODEL_SAID = [
    "The homeowner said the greenhouse fan may run all night.",
    "The owner wants the gate light off by 23:10.",
    "The user marked a report like this wrong last spring.",
    "The owner has already replaced the garage sensor battery.",
    "The homeowner's note says the cellar pump is seasonal.",
    "Because the homeowner always leaves the shed heater on, it is expected.",
]

# Everyday sentences that are about somebody else, or no person at all.
LEAVE_ALONE = [
    "The owner of the car next door parked across the drive.",
    "A previous owner left the cellar pump wired to the hall switch.",
    "Check the owner's manual for the reset button.",
    "The user interface of the thermostat shows the setpoint.",
    "Things morph into a mess when the rules overlap.",
    "You've marked this wrong before, so it stays quiet.",
    "The heater ran at 0:30, as it does every night.",
]


class TestTheFloor(unittest.TestCase):
    def test_model_prose_addresses_the_household(self):
        for said in MODEL_SAID:
            with self.subTest(said):
                out = house_words.household(said)
                self.assertNotRegex(out, THIRD_PERSON)

    def test_the_verb_agrees(self):
        self.assertEqual(house_words.household(MODEL_SAID[1]),
                         "You want the gate light off by 23:10.")
        self.assertEqual(house_words.household(MODEL_SAID[3]),
                         "You have already replaced the garage sensor battery.")
        self.assertEqual(house_words.household(MODEL_SAID[4]),
                         "Your note says the cellar pump is seasonal.")

    def test_everyday_sentences_pass_untouched(self):
        for said in LEAVE_ALONE:
            with self.subTest(said):
                self.assertEqual(house_words.household(said), said)

    def test_quoted_words_are_theirs(self):
        said = "The note reads “the owner wants it on”."
        self.assertEqual(house_words.household(said), said)


class TestAModelRowIsWrittenToYou(StoresCase):
    def test_a_case_and_its_look(self):
        row = findings_store.add_case(
            {"text": "Greenhouse fan running overnight",
             "claim": MODEL_SAID[0], "kind": "problem",
             "detail": " ".join(MODEL_SAID[1:5]),
             "fix": "Leave it: " + MODEL_SAID[5], "severity": "info",
             "stakes": "low"}, run_id="r")
        stored = findings_store.get(row["ts"])
        for field in ("claim", "detail", "fix"):
            with self.subTest(field=field):
                self.assertNotRegex(stored[field], THIRD_PERSON)

    def test_a_looks_conclusion_on_the_card(self):
        [row] = findings_store.add_many([{
            "text": "Shed heater on at night", "detail": "It ran.",
            "severity": "warning", "source": "check:climate.heater"}])
        findings_store.hold_after_look(
            row["ts"], "The owner wants the shed heater on overnight, so "
            "this is expected.", run_id="r")
        entry = findings_store.get(row["ts"])
        look = findings_store.shown_look(entry["triage"], entry)
        self.assertEqual(look["reason"],
                         "You want the shed heater on overnight, so this is expected.")


class TestThePromptsSayIt(unittest.TestCase):
    def test_the_shared_identity_carries_the_address_rule(self):
        self.assertIn(prompt_kit.ADDRESS, prompt_kit.IDENTITY)
        self.assertIn("\"you\"", prompt_kit.ADDRESS)
        self.assertIn("the dashboard", prompt_kit.ADDRESS)

    def test_the_residents_prompts_carry_it(self):
        texts = [v for k, v in vars(resident).items()
                 if isinstance(v, str) and k.isupper() and len(v) > 2000]
        self.assertTrue(any(prompt_kit.ADDRESS in t for t in texts))


class TestWhereToLook(unittest.TestCase):
    def test_a_group_names_no_place_either(self):
        rows = [{"fp": f"{i:016x}", "stream": "look", "fixed_in": "9.9.9",
                 "title": t, "what": t} for i, t in enumerate(
                     ("The shed card repeats", "The gate card is blank"))]
        self.assertNotIn("Where to look: brAIn", verify.group_row(rows)["detail"])


if __name__ == "__main__":
    unittest.main()
