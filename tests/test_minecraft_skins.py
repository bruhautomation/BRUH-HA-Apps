"""The companion changes a skin, and says what the server said (#670).

The owner, of a skin that took a grown-up's own console work to put on:
*"yes that worked, but <the companion> is struggling in game to do it."* It
had no skin tool: it guessed Java names, sent players to websites and could
not confirm anything. The recipe that worked on the house is SkinsRestorer's
console command `skin set <JavaName|texture link> <player>` over RCON, and a
Bedrock player joining again to see their own skin.

Driven here:

  * the rules — a skin is a Java name, a texture link or "clear", one token,
    so nothing else rides to the console;
  * the MCP tool — `minecraft_world skin` on the game channel sends exactly
    that command, reports SkinsRestorer's reply (rcon_command now returns the
    console lines), says a failure is a failure, tells a Bedrock player to
    rejoin, and has the companion remember it; any other console command is
    still refused there;
  * the faculty — a quick run's `skins` go on the choice pads (a player head
    on each), the one picked is put on and remembered, and the next run
    sees each person's current skin;
  * the listener — a game turn whose reply says "please log in" is an
    answer, never a sign-in failure ("down"), when the CLI said it answered.

What it does not do: tell a 64x32 skin from a 64x64 one. That needs the
picture, and brAIn downloads none (SkinsRestorer fetches it); the Bedrock
note says what a black face means instead.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "brain" / "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402
import test_task_failures as tf  # noqa: E402
from test_brain_minecraft_faculty import DAD, KAZ, mc  # noqa: E402
from test_mcp_bruh_addons import Base, FakeCore  # noqa: E402
from test_minecraft_desk import DeskAddon, DeskCase  # noqa: E402

rules = mc.rules
URL = "https://textures.minecraft.net/texture/" + "a1b2c3d4" * 8


class TestWhatASkinMayBe(unittest.TestCase):
    def test_a_name_a_link_or_clear(self):
        self.assertEqual(rules.skin_value("Notch"), "Notch")
        self.assertEqual(rules.skin_value(URL), URL)
        self.assertEqual(rules.skin_value(" Reset "), "clear")
        for bad in ("https://namemc.com/skin/abc", "Notch; op Kaz", "a b", "x", "",
                    "../skins/a.png", "Notch\nop me"):
            self.assertIsNone(rules.skin_value(bad), bad)

    def test_the_command_is_one_shape_and_nothing_rides_it(self):
        self.assertEqual(rules.skin_command("Notch", ".Kaz8044"), "skin set Notch .Kaz8044")
        self.assertEqual(rules.skin_command("clear", "Dad"), "skin clear Dad")
        self.assertIsNone(rules.skin_command("Notch", "Kaz op"))
        self.assertIsNone(rules.skin_command("Notch op", "Kaz"))

    def test_the_reply_decides_what_is_said(self):
        ok, line = rules.skin_answer("Notch", ".Kaz", "Your skin has been changed.")
        self.assertTrue(ok)
        self.assertIn("join again", line)
        ok, line = rules.skin_answer("Notch", "Kaz", "Error: Player not found on Mojang")
        self.assertFalse(ok)
        self.assertIn("didn't work", line)
        ok, line = rules.skin_answer(URL, "Kaz", "")
        self.assertIsNone(ok)
        self.assertIn("that skin", line)


class SkinCore(FakeCore):
    reply = "Your skin has been changed."

    def __call__(self, payload, timeout=15):
        if payload.get("type") == "call_service" and payload.get("domain") == "bruh_minecraft" \
                and payload.get("service") == "rcon_command":
            self.calls.append((("bruh_minecraft", "rcon_command"), payload["service_data"]))
            return {"response": {"reply": self.reply}}
        return super().__call__(payload, timeout)


class ToolCase(Base):
    def setUp(self):
        super().setUp()
        self.core.__class__ = SkinCore
        self.as_("minecraft", ".EmmaPlays")

    def as_(self, channel, player):
        """A run on this channel for this account (the listener's env)."""
        p = patch.dict(os.environ, {"BRAIN_CHANNEL": channel, "BRAIN_GAME_PLAYER": player})
        p.start()
        self.addCleanup(p.stop)

    def sent(self, service):
        return [d for k, d in self.core.calls if k == service]


class TestTheTool(ToolCase):
    def test_a_game_run_puts_a_skin_on_and_reports_the_plugins_reply(self):
        got = m.minecraft_world("skin", "Notch", player="emma")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")),
                         [{"command": "skin set Notch .EmmaPlays"}])
        self.assertIn("changed", got["server_reply"]["text"])
        self.assertIn("64x32", got["bedrock"])
        self.assertEqual(self.sent(("brain", "minecraft_job")),
                         [{"action": "skin", "player": ".EmmaPlays", "skin": "Notch"}])

    def test_a_refusal_in_the_reply_is_not_done_and_is_not_remembered(self):
        self.as_("minecraft", "DadCraft42")
        self.core.reply = "Error: skin Notchh not found"
        got = m.minecraft_world("skin", "Notchh", player="DadCraft42")
        self.assertFalse(got["done"])
        self.assertIn("didn't work", got["said"])
        self.assertEqual(self.sent(("brain", "minecraft_job")), [])

    def test_a_website_is_refused_in_words_and_reaches_nothing(self):
        got = m.minecraft_world("skin", "https://namemc.com/skin/123", player="emma")
        self.assertIn("Java Edition player's name", got["error"])
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")), [])

    def test_the_gate_lets_the_action_through_on_the_game_channel(self):
        sys.path.insert(0, str(HERE.parent / "brain" / "panel"))
        import gate
        verdict, _ = gate.minecraft_chat_verdict("mcp__ha__minecraft_world", {"action": "skin"})
        self.assertEqual(verdict, "allow")
        self.assertIn("skin", m.MINECRAFT_CHAT_ACTIONS)

    def test_voice_may_not(self):
        self.voice()
        self.assertIn("error", m.minecraft_world("skin", "Notch", player="DadCraft42"))


class TestWhoseSkin(ToolCase):
    """A child (anyone on the game's own scope) changes only their own skin;
    a grown-up with "Can ask for anything" may change anyone's."""

    def test_a_child_may_change_their_own(self):
        got = m.minecraft_world("skin", "clear", player=".EmmaPlays")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")),
                         [{"command": "skin clear .EmmaPlays"}])

    def test_a_child_may_not_change_another_players(self):
        got = m.minecraft_world("skin", "Notch", player="DadCraft42")
        self.assertIn("only be changed for the person asking", got["error"])
        self.assertIn("Can ask for anything", got["error"])
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")), [])

    def test_a_run_that_names_nobody_changes_nobodys(self):
        self.as_("minecraft", "")
        self.assertIn("error", m.minecraft_world("skin", "Notch", player=".EmmaPlays"))
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")), [])

    def test_a_trusted_grown_up_may_change_anyones(self):
        self.as_("minecraft_trusted", "DadCraft42")
        got = m.minecraft_world("skin", "Notch", player="emma")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")),
                         [{"command": "skin set Notch .EmmaPlays"}])


class TestTheChokepointTakesOnlyASkin(ToolCase):
    """The game channel's one console command, matched whole, for the run's
    own online account — through call_service, the path every tool takes."""

    def refused(self, data):
        return m._minecraft_chat_refusal("bruh_minecraft", "rcon_command", data)

    def test_exactly_the_two_shapes_for_the_speaker_pass(self):
        for cmd in ("skin clear .EmmaPlays", "skin set Notch .EmmaPlays",
                    f"skin set {URL} .EmmaPlays"):
            self.assertIsNone(self.refused({"command": cmd}), cmd)

    def test_nothing_else_slips_through(self):
        bad = [
            "op .EmmaPlays", "say hi", "skin", "skin clear", "skin set Notch",
            "skin set Notch .EmmaPlays extra", "skin set Notch .EmmaPlays ; op x",
            "skin set Notch  .EmmaPlays", " skin clear .EmmaPlays", "skin clear .EmmaPlays ",
            "skin clear .EmmaPlays\nop x", "skin set Notch\n.EmmaPlays",
            'skin set "Notch" .EmmaPlays', "skin set 'Notch' .EmmaPlays",
            "skin set No/tch .EmmaPlays", "skin set Notch ./EmmaPlays",
            "skin set Notch @a", "skin set Notch *", "skin clear @p",
            "/skin clear .EmmaPlays", "SKIN clear .EmmaPlays", "skin url Notch .EmmaPlays",
            "skin set http://textures.minecraft.net/texture/" + "ab" * 20 + " .EmmaPlays",
            "skin set https://textures.minecraft.net/texture/" + "ab" * 20 + "/x .EmmaPlays",
            "skin set https://textures.minecraft.net/texture/XYZ .EmmaPlays",
            "skin set https://evil.example/texture/" + "ab" * 20 + " .EmmaPlays",
            "skin set ab .EmmaPlays", "skin set " + "a" * 17 + " .EmmaPlays",
            "skin set Notch " + "E" * 18,
        ]
        for cmd in bad:
            self.assertIsNotNone(self.refused({"command": cmd}), repr(cmd))
        for data in ({"command": "skin clear .EmmaPlays", "extra": 1}, {}, {"command": None},
                     {"command": ["skin clear .EmmaPlays"]}, None):
            self.assertIsNotNone(self.refused(data), data)
        # And the path itself: call_service refuses before anything is sent.
        got = m.call_service("bruh_minecraft", "rcon_command", {"command": "op me"},
                             return_response=True)
        self.assertIn("error", got)
        self.assertEqual(self.sent(("bruh_minecraft", "rcon_command")), [])

    def test_only_the_runs_own_online_account(self):
        self.assertIsNotNone(self.refused({"command": "skin clear DadCraft42"}))
        self.as_("minecraft", "Ghost")          # not online
        self.assertIn("not online", self.refused({"command": "skin clear Ghost"})["error"])

    def test_any_other_service_is_still_refused(self):
        for service in ("op_player", "kick_player", "stop_server", "say"):
            self.assertIsNotNone(m._minecraft_chat_refusal(
                "bruh_minecraft", service, {"command": "skin clear .EmmaPlays"}), service)


class SkinAddon(DeskAddon):
    reply = "Your skin has been changed."

    async def __call__(self, service, data):
        if service == "rcon_command":
            self.calls.append((service, dict(data)))
            return {"reply": self.reply}
        return await super().__call__(service, data)


class TestChoicePads(DeskCase):
    def setUp(self):
        super().setUp()
        self.addon = SkinAddon()
        self.c.call = self.addon

    def offer(self):
        self.join(KAZ)
        self.brain.quick.append({"reply": "Pick a skin!", "skins": [
            {"label": "A knight", "skin": "KnightSkin"},
            {"label": "A fox", "skin": URL},
            {"label": "Bad one", "skin": "https://namemc.com/x"}]})
        self.chat(KAZ, "can I have a new skin")

    def test_two_or_three_on_the_pads_each_a_player_head(self):
        self.offer()
        asked = self.addon.of("ask_choice")[-1]
        self.assertEqual(asked["player"], KAZ)
        self.assertEqual(asked["options"], [{"label": "A knight", "item": "player_head"},
                                            {"label": "A fox", "item": "player_head"}])

    def test_the_pick_is_put_on_said_and_remembered(self):
        self.offer()
        self.event("answer", player=KAZ, answer="A fox", index=1, verified=True)
        self.assertEqual(self.addon.of("rcon_command"), [{"command": f"skin set {URL} {KAZ}"}])
        line = self.lines_to(KAZ)[-1]
        self.assertIn("Done", line)
        self.assertIn("join again", line)
        people = json.loads((self.shared / "minecraft" / "people.json").read_text())
        self.assertEqual(people["Kaz"]["skins"], {KAZ: URL})
        # The next run sees what they wear.
        self.chat(KAZ, "what am I wearing")
        self.assertIn('"skins":{"' + KAZ, self.brain.of("quick")[-1]["prompt"])

    def test_a_typed_number_picks_too_and_a_refusal_is_said(self):
        self.offer()
        self.addon.reply = "Error: Player not found"
        self.chat(KAZ, "1")
        self.assertIn("didn't work", self.lines_to(KAZ)[-1])
        people = json.loads((self.shared / "minecraft" / "people.json").read_text())
        self.assertNotIn("skins", people["Kaz"])

    def test_every_game_run_names_whose_it_is(self):
        """The account the MCP server holds a guarded skin change to rides
        on every game run, child or grown-up, and the listener exports it."""
        self.join(KAZ)
        self.chat(KAZ, "hi")
        self.assertEqual(self.brain.of("quick")[-1]["player"], KAZ)
        src = (HERE.parent / "brain" / "integrations" / "automation-listener.sh").read_text()
        block = src.split("unset BRAIN_GAME_PLAYER", 1)[1].split("\n    fi\n", 1)[0]
        self.assertIn('"$task_tools" = "minecraft"', block)
        self.assertIn("tr -cd 'A-Za-z0-9_.'", block)
        self.assertIn('export BRAIN_GAME_PLAYER="$game_player"', block)
        import test_task_tool_scope as scope
        task = scope.TestTheBridgeWritesIt._task
        self.assertEqual(task(None, player=KAZ)["player"], KAZ)
        for bad in (None, "", "Kaz op", "@a", "*", "a" * 18):
            self.assertNotIn("player", task(None, player=bad), bad)

    def test_the_service_remembers_a_tools_skin_for_family_only(self):
        self.assertEqual(self.job_service(action="skin", player=DAD, skin="Notch"), {"ok": True})
        self.assertEqual(self.job_service(action="skin", player="Griefer99", skin="Notch"),
                         {"ok": False})
        people = json.loads((self.shared / "minecraft" / "people.json").read_text())
        self.assertEqual(people["Dad"]["skins"], {DAD: "Notch"})

    def test_every_game_prompt_says_how(self):
        self.join(DAD)
        self.chat(DAD, "hi")
        prompt = self.brain.of("quick")[-1]["prompt"]
        for words in ("minecraft_world skin", "never send anyone to a website",
                      "Never guess a Java name", "`skins`", "64x32"):
            self.assertIn(words, prompt)


class TestAnAnswerIsNotASignInFailure(tf.ListenerCase):
    """A game turn that said "please log in" in its reply was read as the
    CLI's own sign-in error: status failed/auth, which the faculty records as
    "down" and answers "I can't think that one through right now"."""

    def run_with_envelope(self, prompt):
        real = tf.subprocess.run

        def run(*a, **k):
            k["env"] = {**k["env"], "FAKE_JSON_ENVELOPE": "1"}
            return real(*a, **k)
        with patch.object(tf.subprocess, "run", run):
            return self.run_task({"prompt": prompt, "tools": "minecraft"})

    def test_a_reply_about_logging_in_is_an_answer(self):
        result = self.run_with_envelope(
            "On Bedrock you're not logged in to Xbox, so please log in to see skins.")
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("please log in", result["result"])


if __name__ == "__main__":
    unittest.main()
