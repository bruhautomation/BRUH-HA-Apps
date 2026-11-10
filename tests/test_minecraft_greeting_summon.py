"""A greeting does not fail on a summon whose answer was lost (#809).

The house's report: two greetings failed with "The server did not answer."
while RCON was reachable and TPS was 20. `appear()` read the summon's reply
alone: `_try` returns None for any exception — a connection that dropped
under the shared RCON session, which reconnects only on the NEXT command —
and `reply or "The server did not answer."` read an empty reply the same
way. So one dropped connection failed a greeting the next command would
have made, and a summon the server carried out but whose answer was lost
failed too (leaving a body nobody tracked).

Now a reply that is not "Summoned …" is checked by asking whether the
tagged body is there; only when it is not is the summon sent once more, so
a lost answer never makes a second body; a summon that still did not take
leaves nothing behind and says what happened (an empty reply is not "did
not answer"); a refusal the server worded is the answer, with no retry.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_minecraft_companion import KAZ, FakeWorld, HandsBase, companion  # noqa: E402


class LossyWorld(FakeWorld):
    """A server whose next summons go as planned: "drop" (the connection
    breaks before the server reads it), "lost" (it summons, the answer
    never comes back), "empty" (it summons and says nothing), "silent"
    (nothing happens and nothing is said), or a refusal's own words."""

    def __init__(self):
        super().__init__()
        self.plan: list[str] = []

    def reply(self, cmd: str) -> str:
        m = re.search(r"if entity @e\[tag=([^,\]]+),limit=1\]$", cmd)
        if m:
            self.commands.append(cmd)
            there = any(m.group(1) in e["tags"] for e in self.entities)
            return "Test passed" if there else "Test failed"
        if "summon minecraft:allay " in cmd and self.plan:
            how = self.plan.pop(0)
            if how == "drop":
                self.commands.append(cmd)
                raise ConnectionResetError("connection closed by server")
            if how == "silent":
                self.commands.append(cmd)
                return ""
            if how not in ("lost", "empty"):
                self.commands.append(cmd)
                return how
            super().reply(cmd)
            if how == "lost":
                raise TimeoutError("timed out")
            return ""
        return super().reply(cmd)


class GreetingCase(HandsBase):
    def setUp(self):
        super().setUp()
        lossy = LossyWorld()
        self.world = lossy
        self.col.session.factory = lossy.factory
        self.col.session.close()
        self.join(KAZ)

    def allays(self):
        return [e for e in self.world.entities if e["type"] == "allay"]

    def summons(self):
        return [c for c in self.world.commands if "summon minecraft:allay " in c]


class TestALostAnswerIsNotAFailedGreeting(GreetingCase):
    def test_a_dropped_connection_costs_a_second_ask_not_the_greeting(self):
        self.world.plan = ["drop"]
        act = self.hands.appear(KAZ, seconds=10, kind="greet")
        self.assertEqual(act["status"], "active", act)
        self.assertEqual(len(self.allays()), 1)
        self.assertEqual(len(self.summons()), 2)

    def test_a_summon_whose_answer_was_lost_is_found_and_never_doubled(self):
        self.world.plan = ["lost"]
        act = self.hands.appear(KAZ, seconds=10, kind="greet")
        self.assertEqual(act["status"], "active", act)
        self.assertEqual(len(self.allays()), 1)
        self.assertEqual(len(self.summons()), 1)

    def test_an_empty_answer_with_the_body_there_is_a_greeting(self):
        self.world.plan = ["empty"]
        act = self.hands.appear(KAZ, seconds=10, kind="greet")
        self.assertEqual(act["status"], "active", act)
        self.assertEqual(len(self.allays()), 1)
        self.assertEqual(len(self.summons()), 1)


class TestAFailedSummonSaysWhatHappened(GreetingCase):
    def test_nothing_said_and_nothing_there_twice_is_said_so_and_leaves_nothing(self):
        self.world.plan = ["silent", "silent"]
        with self.assertRaisesRegex(companion.CompanionError, "said nothing"):
            self.hands.appear(KAZ, seconds=10, kind="greet")
        act = self.hands.actions.list()[0]
        self.assertEqual(act["status"], "failed")
        self.assertNotIn("did not answer", act["note"])
        self.assertEqual(self.allays(), [])
        self.assertTrue(any(c.startswith("minecraft:kill @e[tag=") and act["tag"] in c
                            for c in self.world.commands))

    def test_a_refusal_in_words_is_the_answer_and_is_not_retried(self):
        self.world.plan = ["Unable to summon entity"]
        with self.assertRaisesRegex(companion.CompanionError, "Unable to summon"):
            self.hands.appear(KAZ, seconds=10, kind="greet")
        self.assertEqual(len(self.summons()), 1)
        self.assertEqual(self.hands.actions.list()[0]["note"], "Unable to summon entity")


if __name__ == "__main__":
    unittest.main()
