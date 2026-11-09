"""A skin goes on through `bruh_minecraft.set_skin`, and a picture is a skin (#760, #762).

BRUH Minecraft 1.19.7 grew `set_skin` {player, skin}: it sends
SkinsRestorer's command and WAITS for its answer (up to 30 s — SkinsRestorer
answers after fetching the skin, seconds after RCON returned nothing), then
answers {worked, reply, note}, and fails with SkinsRestorer's reason. Before
it, brAIn's `rcon_command` heard one second of console and could not tell
whether a skin had gone on. And a skin may be an https link to a picture (a
PNG), which SkinsRestorer uploads — brAIn refused anything but a
textures.minecraft.net link.

Driven here:

  * the rules — an https picture link is a skin, and the game channel's one
    console command takes it; a website page or a non-https link still is
    not;
  * the MCP tool — `minecraft_world skin` calls `set_skin` when Core has it,
    with a wait long enough for the add-on's 30 s, reads worked/reply/note,
    says a refusal is a refusal; an older add-on without it gets the old
    `rcon_command`;
  * the gates — on the game channel `set_skin` is the run's own player's,
    online, exactly {player, skin} (the own-skin rule `rcon_command` keeps);
    voice may not call it by the side door;
  * the faculty — a pad pick goes through `set_skin` when it is there, and
    an older add-on falls back to the console command.
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
from test_brain_minecraft_faculty import KAZ, mc  # noqa: E402
from test_mcp_bruh_addons import Base, FakeCore  # noqa: E402
from test_minecraft_desk import DeskAddon, DeskCase  # noqa: E402

rules = mc.rules
PNG = "https://i.imgur.com/Ab3dEf9.png"


class SetSkinCore(FakeCore):
    """Core with BRUH Minecraft 1.19.7's set_skin (listed and answered)."""
    has_set_skin = True
    answer = {"worked": True, "reply": "Your skin has been changed.", "player": ".EmmaPlays"}
    refuse = ""
    silent = False

    def __call__(self, payload, timeout=15):
        if payload.get("type") == "get_services":
            out = super().__call__(payload, timeout)
            if self.has_set_skin:
                out["bruh_minecraft"] = {"set_skin": {}, "rcon_command": {}}
            return out
        if payload.get("type") == "call_service" and payload.get("domain") == "bruh_minecraft" \
                and payload.get("service") in ("set_skin", "rcon_command"):
            key = ("bruh_minecraft", payload["service"])
            self.calls.append((key, payload["service_data"]))
            self.timeouts = getattr(self, "timeouts", []) + [(key[1], timeout)]
            if key[1] == "set_skin":
                if not self.has_set_skin:
                    return {"error": "Service bruh_minecraft.set_skin not found."}
                if self.silent:
                    raise TimeoutError("timed out during opening handshake")
                if self.refuse:
                    return {"error": self.refuse}
                return {"response": dict(self.answer)}
            return {"response": {"reply": "Your skin has been changed."}}
        return super().__call__(payload, timeout)


class ToolCase(Base):
    def setUp(self):
        super().setUp()
        self.core.__class__ = SetSkinCore
        self.as_("minecraft_trusted", "DadCraft42")
        for p in (patch.object(m, "SUPERVISOR_TOKEN", "t"),
                  patch.dict(m._SERVICE_DOMAINS, {"at": 0.0, "domains": None})):
            p.start()
            self.addCleanup(p.stop)

    def as_(self, channel, player):
        p = patch.dict(os.environ, {"BRAIN_CHANNEL": channel, "BRAIN_GAME_PLAYER": player})
        p.start()
        self.addCleanup(p.stop)

    def sent(self, service):
        return [d for k, d in self.core.calls if k == ("bruh_minecraft", service)]


class TestAPictureIsASkin(unittest.TestCase):
    def test_an_https_picture_link_is_a_skin(self):
        self.assertEqual(rules.skin_value(PNG), PNG)
        self.assertEqual(rules.skin_value("https://cdn.example.org/skins/fox_v2.PNG"),
                         "https://cdn.example.org/skins/fox_v2.PNG")
        self.assertEqual(rules.skin_command(PNG, ".Kaz8044"), f"skin set {PNG} .Kaz8044")
        self.assertTrue(rules.SKIN_COMMAND.fullmatch(f"skin set {PNG} .Kaz8044"))

    def test_a_page_or_anything_that_could_ride_is_not(self):
        for bad in ("http://i.imgur.com/a.png", "https://namemc.com/skin/abc",
                    "https://i.imgur.com/a.png .Other", "https://i.imgur.com/a.png;op",
                    "https://localhost/a.png", "https:///a.png", "https://i.imgur.com/.png",
                    'https://i.imgur.com/"a".png', "https://i.imgur.com/a b.png",
                    "file:///skins/a.png", "https://i.imgur.com/a.png\nop me"):
            self.assertIsNone(rules.skin_value(bad), repr(bad))

    def test_the_game_prompt_says_a_picture_link_is_fine(self):
        note = mc.Companion._skins_note("")
        self.assertIn("picture", note)
        self.assertIn(".png", note.lower())


class TestTheToolUsesSetSkin(ToolCase):
    def test_it_is_called_with_player_and_skin_and_waited_for(self):
        got = m.minecraft_world("skin", PNG, player="emma")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent("set_skin"), [{"player": ".EmmaPlays", "skin": PNG}])
        self.assertEqual(self.sent("rcon_command"), [])
        self.assertIn("changed", got["server_reply"]["text"])
        self.assertIn("64x32", got["bedrock"])
        wait = dict(self.core.timeouts)["set_skin"]
        self.assertGreaterEqual(wait, 45)
        self.assertEqual([d for k, d in self.core.calls if k == ("brain", "minecraft_job")],
                         [{"action": "skin", "player": ".EmmaPlays", "skin": PNG}])

    def test_clear_is_sent_as_clear(self):
        m.minecraft_world("skin", "reset", player="emma")
        self.assertEqual(self.sent("set_skin"), [{"player": ".EmmaPlays", "skin": "clear"}])

    def test_nothing_said_in_time_is_not_a_yes(self):
        self.core.answer = {"worked": None, "reply": "",
                            "note": "SkinsRestorer said nothing within 30 s"}
        got = m.minecraft_world("skin", "Notch", player="DadCraft42")
        self.assertIn("do not say it worked", got["note"])
        self.assertIn("SkinsRestorer said nothing", got["note"])

    def test_no_answer_at_all_is_unknown_not_a_failure(self):
        self.core.silent = True
        got = m.minecraft_world("skin", "Notch", player="DadCraft42")
        self.assertIsNone(got["done"])
        self.assertIn("did not say", got["error"])
        self.assertNotIn("did not go on:", got["error"])
        self.assertIn("didn't say whether", got["said"])

    def test_a_refusal_is_a_refusal_in_its_words_and_is_not_remembered(self):
        self.core.refuse = "SkinsRestorer did not change the skin: Error: skin not found"
        got = m.minecraft_world("skin", "Notchh", player="DadCraft42")
        self.assertFalse(got["done"])
        self.assertIn("skin not found", got["said"])
        self.assertEqual([d for k, d in self.core.calls if k == ("brain", "minecraft_job")], [])

    def test_an_older_add_on_gets_the_console_command(self):
        self.core.has_set_skin = False
        got = m.minecraft_world("skin", "Notch", player="DadCraft42")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent("set_skin"), [])
        self.assertEqual(self.sent("rcon_command"), [{"command": "skin set Notch DadCraft42"}])

    def test_a_list_that_could_not_be_read_tries_set_skin_then_the_console(self):
        self.core.has_set_skin = False
        self.core.services = None          # get_services fails: could not ask
        got = m.minecraft_world("skin", "Notch", player="DadCraft42")
        self.assertTrue(got["done"], got)
        self.assertEqual(len(self.sent("set_skin")), 1)
        self.assertEqual(self.sent("rcon_command"), [{"command": "skin set Notch DadCraft42"}])


class TestTheGates(ToolCase):
    def refused(self, data):
        return m._minecraft_chat_refusal("bruh_minecraft", "set_skin", data)

    def test_the_game_channel_may_set_only_its_own_players_skin(self):
        self.as_("minecraft", ".EmmaPlays")
        self.assertIsNone(self.refused({"player": ".EmmaPlays", "skin": PNG}))
        self.assertIsNone(self.refused({"player": ".EmmaPlays", "skin": "clear"}))
        for data in ({"player": "DadCraft42", "skin": "Notch"},
                     {"player": ".EmmaPlays", "skin": "Notch op"},
                     {"player": ".EmmaPlays", "skin": "https://namemc.com/x"},
                     {"player": ".EmmaPlays", "skin": "Notch", "extra": 1},
                     {"player": "@a", "skin": "Notch"}, {"skin": "Notch"}, {}, None):
            self.assertIsNotNone(self.refused(data), data)
        got = m.minecraft_world("skin", PNG, player=".EmmaPlays")
        self.assertTrue(got["done"], got)
        self.assertIn("only be changed for the person asking",
                      m.minecraft_world("skin", "Notch", player="DadCraft42")["error"])

    def test_a_run_that_names_nobody_or_an_offline_player_is_refused(self):
        self.as_("minecraft", "")
        self.assertIsNotNone(self.refused({"player": ".EmmaPlays", "skin": "Notch"}))
        self.as_("minecraft", "Ghost")
        self.assertIn("not online", self.refused({"player": "Ghost", "skin": "Notch"})["error"])

    def test_voice_may_not_by_the_side_door(self):
        self.assertIn(("bruh_minecraft", "set_skin"), m.VOICE_ADMIN_SERVICES)
        self.voice()
        got = m.call_service("bruh_minecraft", "set_skin",
                             {"player": "DadCraft42", "skin": "Notch"}, return_response=True)
        self.assertIn("error", got)
        self.assertEqual(self.sent("set_skin"), [])


class NewSkinAddon(DeskAddon):
    worked = True
    missing = False

    async def __call__(self, service, data):
        if service == "set_skin":
            self.calls.append((service, dict(data)))
            if self.missing:
                raise RuntimeError("Service bruh_minecraft.set_skin not found")
            return {"worked": self.worked, "reply": "Your skin has been changed."}
        if service == "rcon_command":
            self.calls.append((service, dict(data)))
            return {"reply": "Your skin has been changed."}
        return await super().__call__(service, data)


class TestTheFaculty(DeskCase):
    def setUp(self):
        super().setUp()
        self.addon = NewSkinAddon()
        self.c.call = self.addon
        self.c.has_service = lambda service: service == "set_skin"

    def pick(self):
        self.join(KAZ)
        self.brain.quick.append({"reply": "Pick a skin!", "skins": [
            {"label": "A knight", "skin": "KnightSkin"},
            {"label": "A fox", "skin": PNG}]})
        self.chat(KAZ, "can I have a new skin")
        self.event("answer", player=KAZ, answer="A fox", index=1, verified=True)

    def test_a_pick_goes_through_set_skin(self):
        self.pick()
        self.assertEqual(self.addon.of("set_skin"), [{"player": KAZ, "skin": PNG}])
        self.assertEqual(self.addon.of("rcon_command"), [])
        self.assertIn("Done", self.lines_to(KAZ)[-1])
        people = json.loads((self.shared / "minecraft" / "people.json").read_text())
        self.assertEqual(people["Kaz"]["skins"], {KAZ: PNG})

    def test_an_older_add_on_falls_back_to_the_console(self):
        self.addon.missing = True
        self.pick()
        self.assertEqual(self.addon.of("rcon_command"), [{"command": f"skin set {PNG} {KAZ}"}])
        self.assertIn("Done", self.lines_to(KAZ)[-1])

    def test_without_the_service_listed_it_is_the_console(self):
        self.c.has_service = lambda service: False
        self.pick()
        self.assertEqual(self.addon.of("set_skin"), [])
        self.assertEqual(self.addon.of("rcon_command"), [{"command": f"skin set {PNG} {KAZ}"}])


if __name__ == "__main__":
    unittest.main()
