#!/usr/bin/env python3
"""A card that says something has not happened for days has to have looked.

Reported from a real house: a card said a pump "had not cycled in 58+
hours" because one power sensor read 0 W across the week, while another
sensor on the same pump showed a cycle inside that window — later traced to
a recorder gap. The panel's own history readers already drop a series that
ends before its live last change and say so (`history_incomplete`, in the
bundle and in the MCP `get_history` answer), but a series can be flat for
other reasons and long-term statistics carry no such flag, so nothing told
the run that an absence is a claim like any other. Both card system prompts
— the snapshot path's and the search path's — now say it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import categories  # noqa: E402


class TestAnAbsenceIsAClaim(unittest.TestCase):

    def test_both_card_prompts_carry_the_rule(self):
        for name in ("SYSTEM_PROMPT", "ANALYST_SYSTEM"):
            text = getattr(categories, name)
            with self.subTest(prompt=name):
                self.assertIn('"nothing for N h"', text)
                self.assertIn("related sensors", text)
                # The field both history readers write, by its own name.
                self.assertIn("history_incomplete", text)

    def test_the_bundle_field_is_the_name_the_rule_uses(self):
        source = (Path(__file__).resolve().parent.parent / "brain" / "panel"
                  / "ha_data.py").read_text(encoding="utf-8")
        self.assertIn('bundle["history_incomplete"]', source)


if __name__ == "__main__":
    unittest.main()
