"""A skin change says whether it worked (#760, #762).

"Make lev have the sheep skin in Minecraft": the companion could not tell
whether a skin went on, because SkinsRestorer answers `skin set` only after
it has fetched the skin — from Mojang for a Java name, from MineSkin for a
picture, seconds after RCON came back with nothing — and the console was
listened to for one second. And a picture (a PNG link) was refused, though
SkinsRestorer takes one.

So BRUH Minecraft has a skin action (`set_skin`, the bridge's `skin` kind,
scripts/skins.py): a Java player's name, an https link to a picture, or
clear, for one player; it waits for SkinsRestorer's own last word — past
"Uploading skin, please wait…" — up to SKIN_WAIT_S, or for SkinsRestorer's
record of that player to change on disk, and answers with SkinsRestorer's
words: success, failure (an error the service raises), or "said nothing".
A `skin set`/`skin clear` sent through rcon_command waits the same way.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_bridge import BridgeTestCase  # noqa: E402
from test_minecraft_world_scripts import _load  # noqa: E402

SCRIPTS = HERE.parent / "bruh-minecraft-server" / "scripts"
skins = _load("skins_under_test", SCRIPTS / "skins.py")

LEV = ".Lev6398"
LEV_UUID = "00000000-0000-0000-0009-01f2a3b4c5d6"
PNG = "https://i.imgur.com/sheep-skin_64x64.png"


class Later:
    """A clock and a sleep where SkinsRestorer's answer lands after RCON has
    returned: `then(seconds, do)` runs `do` once that much time has passed."""

    def __init__(self):
        self.now = 0.0
        self.due: list[tuple[float, object]] = []

    def then(self, at, do):
        self.due.append((at, do))

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s
        for at, do in list(self.due):
            if self.now >= at:
                self.due.remove((at, do))
                do()


class SkinCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.server = self.root / "server"
        (self.server / "plugins" / "SkinsRestorer" / "players").mkdir(parents=True)
        (self.server / "usercache.json").write_text(json.dumps(
            [{"name": LEV, "uuid": LEV_UUID, "expiresOn": "2027-01-01"}]))
        self.log = self.root / "console.log"
        self.log.write_text("[11:59:00 INFO]: Done (3.1s)!\n")
        self.later = Later()
        self.sent: list[str] = []

    def console(self, line):
        def write():
            with open(self.log, "a", encoding="utf-8") as fh:
                fh.write(f"[12:00:05 INFO]: {line}\n")
        return write

    def apply(self, skin, player=LEV, reply=""):
        def run(cmd):
            self.sent.append(cmd)
            return reply
        return skins.apply(run, skin, player, self.log, self.server,
                           sleep=self.later.sleep, clock=self.later.clock)


class TestTheAnswerArrivesLate(SkinCase):
    def test_a_picture_is_taken_and_its_late_answer_is_the_answer(self):
        self.later.then(1.0, self.console("[SkinsRestorer] Uploading skin, please wait... "
                                          "(This may take up some time)"))
        self.later.then(8.0, self.console(f"[SkinsRestorer] You changed the skin of {LEV}."))
        out = self.apply(PNG)
        self.assertEqual(self.sent, [f"skin set {PNG} {LEV}"])
        self.assertIs(out["worked"], True)
        self.assertIn("changed the skin", out["reply"])
        self.assertGreaterEqual(self.later.now, 8.0)

    def test_a_failure_is_a_failure_in_its_own_words(self):
        self.later.then(3.0, self.console("[SkinsRestorer] Error: Invalid skin URL or format"))
        out = self.apply("https://example.com/not-a-skin.png")
        self.assertIs(out["worked"], False)
        self.assertIn("Invalid skin URL", out["reply"])

    def test_the_record_on_disk_confirms_it_when_the_console_says_nothing(self):
        record = self.server / "plugins" / "SkinsRestorer" / "players" / f"{LEV_UUID}.player"
        self.later.then(2.0, lambda: record.write_text('{"skinIdentifier":{"identifier":"Notch"}}'))
        out = self.apply("Notch")
        self.assertIs(out["worked"], True)
        self.assertIn(LEV, out["reply"])

    def test_clear_puts_their_own_skin_back(self):
        self.later.then(1.0, self.console(f"[SkinsRestorer] Skin cleared for player {LEV}."))
        out = self.apply("reset")
        self.assertEqual(self.sent, [f"skin clear {LEV}"])
        self.assertIs(out["worked"], True)

    def test_silence_is_said_and_not_called_a_success(self):
        out = self.apply("Notch")
        self.assertIsNone(out["worked"])
        self.assertGreaterEqual(self.later.now, skins.SKIN_WAIT_S)

    def test_no_skinsrestorer_is_a_failure_at_once(self):
        out = self.apply("Notch", reply="Unknown or incomplete command, see below for error"
                                        "skin set Notch .Lev6398<--[HERE]")
        self.assertIs(out["worked"], False)
        self.assertEqual(self.later.now, 0.0)

    def test_nothing_else_can_ride_to_the_console(self):
        for skin, player in (("Notch op Kaz", LEV), ("Notch", "Kaz op"),
                             ("https://x.com/a b.png", LEV), ("http://x.com/a.png", LEV),
                             ("Notch\nop me", LEV), ("", LEV)):
            with self.assertRaises(ValueError, msg=(skin, player)):
                self.apply(skin, player)
        self.assertEqual(self.sent, [])


class TestTheBridge(BridgeTestCase):
    def test_the_skin_kind_answers_with_skinsrestorers_words(self):
        log = self.bridge.CONSOLE_LOG
        log.write_text("")
        server = Path(self.tmp.name) / "server"
        server.mkdir()
        self.bridge.SERVER_DIR = server
        rcon = sys.modules["rcon_client"].Rcon

        def command(_self, cmd):
            self.capture.append(cmd)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("[12:00:01 INFO]: [SkinsRestorer] Error: Skin data not found\n")
            return ""
        rcon.command = command
        out = asyncio.run(self.bridge.handle({"kind": "skin",
                                              "payload": {"player": "Dad", "skin": "Notch"}}))
        self.assertFalse(out["ok"])
        self.assertIn("Skin data not found", out["error"])
        self.assertEqual(self.capture, ["skin set Notch Dad"])
        # The same command through rcon_command waits the same way.
        out = asyncio.run(self.bridge.handle({"kind": "command",
                                              "payload": {"command": "skin set Notch Dad"}}))
        self.assertTrue(out["ok"])
        self.assertIn("Skin data not found", out["reply"])
        bad = asyncio.run(self.bridge.handle({"kind": "skin",
                                              "payload": {"player": "Dad", "skin": "a b"}}))
        self.assertFalse(bad["ok"])


class TestTheService(unittest.TestCase):
    def setUp(self):
        from test_minecraft_services import HAError, Base
        self.HAError = HAError
        case = Base("run")
        case.setUp()
        self.case = case

    def test_set_skin_answers_with_the_result_and_raises_on_a_failure(self):
        case = self.case
        case.answer = {"ok": True, "worked": True, "reply": "You changed the skin of .Lev6398."}
        got = case.call("set_skin", player=LEV, skin=PNG)
        self.assertEqual(case.sent[-1], ("skin", {"player": LEV, "skin": PNG}))
        self.assertIs(got["worked"], True)
        self.assertEqual(case.handlers["set_skin"][1], "optional")
        case.answer = {"ok": False, "error": "SkinsRestorer did not change the skin: Error"}
        with self.assertRaises(self.HAError):
            case.call("set_skin", player=LEV, skin="Notch")

    def test_a_skin_command_is_given_time_for_its_late_answer(self):
        waited = []
        case = self.case

        async def fake_send(kind, payload, timeout=15.0):
            waited.append(timeout)
            return {"ok": True, "reply": "You changed the skin of Dad."}
        case.mod.send_request = fake_send
        case.call("rcon_command", command="skin set Notch Dad")
        case.call("rcon_command", command="list")
        self.assertGreater(waited[0], 30)
        self.assertEqual(waited[1], 15.0)
