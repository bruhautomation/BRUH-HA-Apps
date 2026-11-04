"""BRUH Minecraft draws a job's boss bar for one player, and only its own
(`bruh_companion:` ids); every other boss bar command is refused."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_brain_minecraft_faculty import KAZ  # noqa: E402


# ---------------------------------------------------------------------------
# BRUH Minecraft draws the bar, and only its own
# ---------------------------------------------------------------------------
class TestTheAddOnDrawsTheBar(unittest.TestCase):
    def setUp(self):
        from test_minecraft_desk_hands import DeskBase  # noqa: PLC0415
        self.case = type("Hands", (DeskBase,), {"runTest": lambda self: None})()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_a_bar_for_one_player_set_and_removed(self):
        from test_minecraft_companion import companion  # noqa: PLC0415
        c = self.case
        c.join(KAZ)
        out = c.hands.bar(KAZ, "j1a2b3c", "a castle — the towers", 45)
        self.assertEqual((out["bar"], out["percent"]), ("bruh_companion:j1a2b3c", 45))
        cmds = [x for x in c.world.commands if "bossbar" in x]
        self.assertTrue(any(x.startswith("minecraft:bossbar add bruh_companion:j1a2b3c ")
                            for x in cmds), cmds)
        self.assertIn("minecraft:bossbar set bruh_companion:j1a2b3c value 45", cmds)
        self.assertIn(f"minecraft:bossbar set bruh_companion:j1a2b3c players {KAZ}", cmds)
        c.hands.bar(KAZ, "j1a2b3c", end=True)
        self.assertEqual(c.world.commands[-1], "minecraft:bossbar remove bruh_companion:j1a2b3c")
        for bad in ("minecraft:bossbar remove minecraft:raid",
                    "minecraft:bossbar set bruh_companion:j1 players @a",
                    "minecraft:bossbar list"):
            with self.assertRaises(companion.GuardError, msg=bad):
                companion.check_command(bad)
        with self.assertRaises(companion.CompanionError):
            c.hands.bar(KAZ, "NOT A KEY!", "x")


if __name__ == "__main__":
    unittest.main()
