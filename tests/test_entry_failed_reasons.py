#!/usr/bin/env python3
"""An integration that did not load is told by its own reason.

A real house's `sys.entry_failed` row opened with a count fragment ("5:
Climate 1 Ecobee, …") and gave every entry one stock list of remedies (a
hub powered on, a network share mounted, a password re-entered) whatever
each had actually said. Each entry's reason is read off what Core reports
— can't reach the device, sign-in rejected, the service answering with an
error, still retrying with nothing said — entries failing for the same
reason are grouped under it, each group gets the one action that fits it,
and a count is never the first word.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import system  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

STOCK = ("a hub powered on", "network share mounted", "password re-entered")


def entry(eid, title, state, reason):
    return {"entry_id": eid, "domain": title.lower().replace(" ", "_"),
            "title": title, "state": state, "source": "user", "reason": reason}


FIVE = [
    entry("a1", "Ecobee", "setup_retry", "Cannot connect to host 10.0.0.9:443"),
    entry("a2", "Hall thermostat", "setup_retry", "Timeout while connecting"),
    entry("a3", "Cloud thing", "setup_error",
          "Invalid authentication: 401 Unauthorized"),
    entry("a4", "Pool pump", "setup_retry", ""),
    entry("a5", "Weather service", "setup_retry",
          "Error on retrieving data: 503 Service Unavailable"),
]


class TestEachEntrySaysItsOwnReason(unittest.TestCase):
    def setUp(self):
        [self.row] = system.entry_failed(house(config_entries=list(FIVE)), NOW)

    def test_a_count_is_never_the_first_word(self):
        self.assertFalse(self.row["detail"][:1].isdigit(), self.row["detail"])

    def test_no_stock_list(self):
        for words in STOCK:
            self.assertNotIn(words, self.row["fix"])
            self.assertNotIn(words, self.row["detail"])

    def test_entries_failing_for_the_same_reason_are_grouped(self):
        detail = self.row["detail"]
        self.assertIn("Can't reach the device at its address: "
                      "Ecobee and Hall thermostat", detail)
        self.assertIn("Sign-in rejected: Cloud thing", detail)
        self.assertIn("The service it talks to answered with an error: "
                      "Weather service", detail)
        self.assertIn("Still retrying, with no reason given: Pool pump",
                      detail)

    def test_each_reason_gets_its_own_action(self):
        fix = self.row["fix"]
        self.assertIn("Ecobee and Hall thermostat: check", fix)
        self.assertIn("Cloud thing: sign in again", fix)
        self.assertIn("Weather service:", fix)
        self.assertIn("Pool pump:", fix)
        # Each action is said once per reason, not once per entry.
        self.assertEqual(fix.count("sign in again"), 1)

    def test_the_integrations_own_words_are_still_there(self):
        self.assertIn("Cloud thing: Invalid authentication", self.row["detail"])

    def test_text_is_unchanged(self):
        self.assertEqual(self.row["text"], system.ENTRY_FAILED_TEXT)


if __name__ == "__main__":
    unittest.main()
