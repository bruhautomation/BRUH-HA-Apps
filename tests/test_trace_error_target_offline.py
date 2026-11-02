"""A run that failed only because the game had nobody to aim at is not broken.

A Minecraft service call answers "No player was found" when the target is not
in the game; that is the expected outcome with nobody playing. The trace-error
check and the trace signal both leave it alone, and every other error still
counts.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))
sys.path.insert(0, os.path.dirname(__file__))

from checks import automations  # noqa: E402
from checks._util import target_offline_error  # noqa: E402
import signals  # noqa: E402
from test_house_checks import NOW, core_run, house  # noqa: E402

KEY = "automation.morning-1"

OFFLINE = [
    "The Minecraft server refused it: No player was found",
    "The Minecraft server refused it: No entity was found",
    "The Minecraft server refused it: No targets matched selector",
    "That player is not in the game right now",
]
REAL = [
    "The Minecraft server refused it: Unknown command",
    "Could not connect to RCON",
    "Entity switch.pump is unavailable",
]


class TestTargetOffline(unittest.TestCase):

    def test_offline_replies_raise_nothing(self):
        for text in OFFLINE:
            snap = house()
            snap["traces"][KEY] = [core_run("1", "error", 300, error=text)]
            self.assertEqual(automations.trace_error(snap, NOW), [], text)
            self.assertIsNone(signals.from_trace(
                {"item_id": "morning-1", "error": text,
                 "timestamp": NOW}, NOW), text)

    def test_every_other_error_still_does(self):
        for text in REAL:
            snap = house()
            snap["traces"][KEY] = [core_run("1", "error", 300, error=text)]
            self.assertTrue(automations.trace_error(snap, NOW), text)
            self.assertFalse(target_offline_error(text), text)


if __name__ == "__main__":
    unittest.main()
