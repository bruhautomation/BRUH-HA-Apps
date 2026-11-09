"""A block check over RCON puts nothing in the players' chat (#761).

The owner: "I see a lot of rcon ok messages. What are those? Can you hide
those messages without breaking anything?" The companion checked blocks
with `execute if block … run say ok`; `say` broadcasts, so every check put
"[Rcon] ok" in every player's chat — about 1,300 times for one build. The
same check without its `run say` answers the sender alone, "Test passed" or
"Test failed", which is the answer the check wanted.

So `rcon_command` (the HA bridge, scripts/console_reply.quiet_probe) sends
a check that ends in `run say <one word>` without the say. A real
announcement — several words, or a say that is not after a test — is sent
as written.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_bridge import BridgeTestCase  # noqa: E402


class TestAProbeIsNotChat(BridgeTestCase):
    def send(self, command: str) -> dict:
        return asyncio.run(self.bridge.handle({"kind": "command",
                                               "payload": {"command": command}}))

    def test_a_block_check_is_sent_without_its_say(self):
        out = self.send("execute if block 10 64 -3 minecraft:stone run say ok")
        self.assertTrue(out["ok"])
        self.assertEqual(self.capture, ["execute if block 10 64 -3 minecraft:stone"])
        self.assertFalse([c for c in self.capture if " say " in c])

    def test_other_checks_and_words_are_probes_too(self):
        for cmd, sent in (
            ("/minecraft:execute in minecraft:the_end unless block ~ ~ ~ air run minecraft:say found",
             "minecraft:execute in minecraft:the_end unless block ~ ~ ~ air"),
            ("execute positioned 0 70 0 if entity @a[distance=..5] run say yes",
             "execute positioned 0 70 0 if entity @a[distance=..5]"),
            ("execute if blocks 0 0 0 1 1 1 5 5 5 all run say 1",
             "execute if blocks 0 0 0 1 1 1 5 5 5 all"),
        ):
            self.capture.clear()
            self.send(cmd)
            self.assertEqual(self.capture, [sent], cmd)

    def test_an_announcement_is_left_as_it_is(self):
        for cmd in ("execute if entity @a[name=Dad] run say Dinner is ready everyone",
                    "say ok",
                    "execute as @a run say hi"):
            self.capture.clear()
            self.send(cmd)
            self.assertEqual(self.capture, [cmd], cmd)
