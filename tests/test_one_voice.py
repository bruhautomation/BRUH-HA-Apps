#!/usr/bin/env python3
"""brAIn speaks with one voice, and a card makes sense on its own.

What a real house showed:

  * insight cards written as follow-ups to earlier cards ("there hasn't
    been a new night since Thursday's card", "Friday's mystery" never
    explained) or opening on a bare "Normal." under the title;
  * cards reporting a risky event — a freezer door open for hours, a
    bridge dropping off — with the times and nothing after them: no
    consequence checked, nothing to do;
  * owner-facing text mixing "I" (a card), "brAIn suggests" (a finding)
    and an internal role name ("The Resident last said …" on a fault row).

The card contract and the investigation's contract now say so, and the
fixed sentences that reach the owner no longer name brAIn's internal
parts. Code identifiers, the `resident` source id and every wire value are
unchanged: only words a person reads moved.
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import categories  # noqa: E402
import decision_trail  # noqa: E402
import findings_store  # noqa: E402
import reports  # noqa: E402
import resident  # noqa: E402
import run_sources  # noqa: E402
import triage  # noqa: E402

CONTRACT = categories._CARD_CONTRACT
CARD_SYSTEMS = (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM)

# Names of brAIn's own machinery a homeowner has never been introduced to.
INTERNAL = re.compile(r"\bResident\b|\bfirst look\b|\bthe look\b|\blook's\b",
                      re.I)


class TestACardStandsAlone(unittest.TestCase):
    def test_the_contract_forbids_follow_ups(self):
        self.assertIn("Each card stands alone", CONTRACT)
        self.assertIn("never refer to an earlier card", CONTRACT)
        self.assertIn("mystery", CONTRACT)
        self.assertIn("bare verdict", CONTRACT)
        for system in CARD_SYSTEMS:
            self.assertIn("Each card stands alone", system)

    def test_a_run_with_nothing_new_says_what_holds_now(self):
        self.assertIn("nothing new", CONTRACT)
        self.assertIn("what holds now", CONTRACT)

    def test_the_previous_run_is_context_the_reader_never_saw(self):
        block = categories._previous_block(
            {"title": "Freezer steady", "summary": "x"})
        self.assertIn("never refer to it", block)
        # A refine is editing the card on screen; that block is unchanged.
        revising = categories._previous_block({"title": "t"}, revising=True)
        self.assertIn("THE CARD AS IT STANDS", revising)


class TestARiskyEventEndsSomewhere(unittest.TestCase):
    def test_the_contract_asks_for_a_consequence_or_a_step(self):
        self.assertIn("could have done harm", CONTRACT)
        self.assertIn("consequence", CONTRACT)
        self.assertIn("one clear thing", CONTRACT)
        for system in CARD_SYSTEMS:
            self.assertIn("could have done harm", system)


class TestOneVoice(unittest.TestCase):
    RULE = 'never "I"'

    def test_the_card_contract_writes_brain_in_the_third_person(self):
        for system in CARD_SYSTEMS:
            self.assertIn(self.RULE, system)
            self.assertIn("internal parts", system)

    def test_the_investigation_contract_does_too(self):
        self.assertIn(self.RULE, resident.INVESTIGATE_SYSTEM)
        self.assertIn("internal parts", resident.INVESTIGATE_SYSTEM)

    def test_fixed_sentences_name_no_internal_part(self):
        said = {
            "triage.UNJUDGED": triage.UNJUDGED,
            "triage.WAITING": triage.WAITING,
            "triage.RUN_FAILED": triage.RUN_FAILED,
            "resident.SKIPPED": resident.SKIPPED,
            "resident.UNREADABLE": resident.UNREADABLE,
            "findings_store.RESIDENT_TITLE": findings_store.RESIDENT_TITLE,
        }
        for kind, text in decision_trail.KINDS.items():
            said[f"decision_trail.KINDS[{kind}]"] = text
        for source, row in run_sources.SOURCES.items():
            for key in ("label", "blurb"):
                said[f"run_sources[{source}].{key}"] = row.get(key, "")
        for name, text in said.items():
            with self.subTest(name=name):
                self.assertIsNone(INTERNAL.search(text), text)

    def test_the_waiting_row_names_no_internal_part(self):
        runs = {"by_source": {"resident": {"rate_limited": 3, "error": 2}}}
        text = reports._why_looks_waited(runs, {"last_error": "paused"})
        self.assertIn("3", text)
        self.assertIn("paused", text)
        self.assertIsNone(INTERNAL.search(text), text)
        bare = reports._why_looks_waited({}, {})
        self.assertIsNone(INTERNAL.search(bare), bare)

    def test_a_stored_resident_title_is_read_as_the_new_one(self):
        self.assertEqual(findings_store._titled("resident", "The Resident"),
                         findings_store.RESIDENT_TITLE)
        # Somebody else's title is theirs.
        self.assertEqual(findings_store._titled("check:x", "Frozen sensors"),
                         "Frozen sensors")

    def test_a_late_verdict_still_recognises_the_old_stock_sentence(self):
        old = ("The look at this one did not finish, so it is on the list "
               "as it was filed.")
        self.assertEqual(findings_store.house_reason(old), "")
        self.assertEqual(findings_store.house_reason(triage.RUN_FAILED), "")


if __name__ == "__main__":
    unittest.main()
