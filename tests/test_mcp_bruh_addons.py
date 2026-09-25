#!/usr/bin/env python3
"""brAIn's tools for BRUH Minecraft, BRight and BRUH Print.

Driven through the real `call_service` chokepoint with Home Assistant
faked at the WebSocket, so what is under test is what reaches Core — the
service, its data, `return_response` — and every guard on the way:
the per-agent blocked-services list, the protected list, the voice gate.
A voice agent may play (teleport, give, time, a label, a show) and may
not administer (ban, op, a raw command, stopping the server, installing
server code); a misheard sentence that bans a child from the family
server is the case the split exists for.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402


class FakeCore:
    """Answers `call_service` over the WebSocket the way Core does."""

    def __init__(self):
        self.calls = []
        self.online = ["Steve", ".EmmaPlays", "DadCraft42"]
        self.missing = set()

    def __call__(self, payload, timeout=15):
        assert payload["type"] == "call_service", payload
        assert payload["return_response"] is True
        key = (payload["domain"], payload["service"])
        self.calls.append((key, payload["service_data"]))
        if key in self.missing:
            return {"error": f"Service {key[0]}.{key[1]} not found."}
        if key == ("bruh_minecraft", "get_status"):
            return {"response": {"reachable": True, "online": len(self.online), "max": 20,
                                 "players": self.online, "state": {"active_world": "family"},
                                 "stats": {"version": "1.21.4"}}}
        if key[0] == "bruh_print":
            return {"response": {"printed": payload["service_data"].get("copies", 1),
                                 "side": "left", "notes": []}}
        return {"response": {"reply": "ok"}}

    def acted(self):
        return [k for k, _ in self.calls if k[1] != "get_status"]


class Base(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.tmp = tempfile.TemporaryDirectory()
        saved = {k: getattr(m, k) for k in ("DENIED_SERVICES", "PROTECTED_ENTITIES",
                                            "EXPOSED_ONLY")}
        self.addCleanup(lambda: [setattr(m, k, v) for k, v in saved.items()])
        self.addCleanup(self.tmp.cleanup)
        m.DENIED_SERVICES = []
        m.PROTECTED_ENTITIES = []
        m.EXPOSED_ONLY = False
        for p in (patch.object(m, "_ws_command", self.core),
                  patch.object(m, "record_action", lambda *a, **k: None),
                  patch.object(m, "_exposure", lambda: {"exposed": set()}),
                  patch.object(m, "_entity_exposed",
                               lambda eid: (not m.EXPOSED_ONLY) or eid == "media_player.den")):
            p.start()
            self.addCleanup(p.stop)

    def voice(self):
        m.EXPOSED_ONLY = True


class TestMinecraftNames(Base):
    def test_a_spoken_name_finds_the_player_the_server_knows(self):
        got = m.minecraft_teleport("emma plays", to_player="dad")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.core.calls[-1], (("bruh_minecraft", "teleport"),
                                               {"player": ".EmmaPlays", "to_player": "DadCraft42"}))

    def test_everyone_is_the_all_players_selector(self):
        m.minecraft_teleport("everyone", to_player="Steve")
        self.assertEqual(self.core.calls[-1][1]["player"], "@a")

    def test_an_ambiguous_name_is_a_question_not_a_guess(self):
        self.core.online = ["Emma1", "Emma2"]
        got = m.minecraft_teleport("emma", to_player="Emma1")
        self.assertIn("ask which", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_an_offline_name_says_who_is_on(self):
        got = m.minecraft_player("Bob", "gamemode", "creative")
        self.assertIn("Online now: Steve, .EmmaPlays, DadCraft42", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_whitelisting_somebody_offline_is_ordinary(self):
        got = m.minecraft_player("NewFriend", "whitelist_add")
        self.assertTrue(got["done"])
        self.assertEqual(self.core.calls[-1], (("bruh_minecraft", "whitelist_add"),
                                               {"player": "NewFriend"}))

    def test_give_names_the_item_in_minecrafts_words(self):
        m.minecraft_player("steve", "give", "oak log", amount=200)
        self.assertEqual(self.core.calls[-1][1],
                         {"player": "Steve", "item": "minecraft:oak_log", "amount": 64})

    def test_time_and_weather_take_the_words_people_say(self):
        m.minecraft_world("time", "morning")
        self.assertEqual(self.core.calls[-1][1], {"time": "day"})
        m.minecraft_world("weather", "sunny")
        self.assertEqual(self.core.calls[-1][1], {"weather": "clear"})


class TestTheVoiceSplit(Base):
    def test_voice_may_play(self):
        self.voice()
        self.assertTrue(m.minecraft_teleport("steve", to_player="dad")["done"])
        self.assertTrue(m.minecraft_player("steve", "gamemode", "creative")["done"])
        self.assertTrue(m.minecraft_world("say", "dinner time")["done"])
        self.assertEqual(m.print_label(text="Chili")["printed"], 1)
        self.assertTrue(m.bright_show("party", party="Friday", media_player="media_player.den")["done"])

    def test_voice_may_not_administer(self):
        self.voice()
        for got in (m.minecraft_player("Steve", "ban"),
                    m.minecraft_player("Steve", "op"),
                    m.minecraft_command("stop"),
                    m.minecraft_server("stop"),
                    m.minecraft_addons("install", project_id="abc", kind="plugin")):
            self.assertIn("Whole house", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_the_side_door_is_shut_too(self):
        self.voice()
        got = m.call_service("bruh_minecraft", "ban_player", {"player": "Steve"})
        self.assertIn("Whole house", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_voice_may_still_look(self):
        self.voice()
        self.assertEqual(m.minecraft_status()["players"], self.core.online)
        m.minecraft_addons("search", query="chairs")
        self.assertEqual(self.core.calls[-1][0], ("bruh_minecraft", "search_addons"))

    def test_voice_prints_a_bounded_number(self):
        self.voice()
        got = m.print_label(text="Chili", copies=200)
        self.assertIn("at most 10", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_a_speaker_voice_cannot_see_is_not_played_on(self):
        self.voice()
        got = m.bright_show("party", party="Friday", media_player="media_player.bedroom")
        self.assertIn("not exposed", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_a_whole_house_agent_administers(self):
        self.assertTrue(m.minecraft_player("Steve", "ban")["done"])
        self.assertEqual(m.minecraft_command("/difficulty hard")["command"], "difficulty hard")


class TestTheGuardsStillApply(Base):
    def test_a_blocked_service_is_refused_through_the_tool(self):
        m.DENIED_SERVICES = ["bruh_minecraft.teleport"]
        got = m.minecraft_teleport("steve", to_player="dad")
        self.assertIn("not permitted", got["error"])
        self.assertNotIn(("bruh_minecraft", "teleport"), self.core.acted())

    def test_a_protected_scene_is_not_called_at_the_end_of_a_show(self):
        m.PROTECTED_ENTITIES = ["scene.bedtime"]
        got = m.bright_show("stop", scene="scene.bedtime")
        self.assertIn("protected", got["error"])
        self.assertEqual(self.core.acted(), [])

    def test_an_add_on_not_installed_says_so(self):
        self.core.missing.add(("bruh_print", "print_text"))
        got = m.print_label(text="Chili")
        self.assertIn("BRUH Print's Home Assistant integration is not set up", got["error"])


class TestTheOtherCalls(Base):
    def test_print_a_template_with_its_fields(self):
        m.print_label(template="Freezer bag", fields={"contents": "Chili"}, copies=2)
        self.assertEqual(self.core.calls[-1], (("bruh_print", "print_template"),
                                               {"template": "Freezer bag", "copies": 2,
                                                "fields": {"contents": "Chili"}}))

    def test_bright_actions_map_to_their_services(self):
        m.bright_show("party")
        self.assertEqual(self.core.calls[-1][0], ("bright", "party_mode"))
        m.bright_show("track", track="/media/music/a.mp3")
        self.assertEqual(self.core.calls[-1], (("bright", "start_show"),
                                               {"track": "/media/music/a.mp3"}))
        m.bright_show("stop")
        self.assertEqual(self.core.calls[-1], (("bright", "stop_show"), {}))

    def test_every_new_tool_is_registered_and_reachable(self):
        names = {t["name"] for t in m.TOOLS}
        for name in ("minecraft_status", "minecraft_teleport", "minecraft_player",
                     "minecraft_world", "minecraft_command", "minecraft_server",
                     "minecraft_addons", "label_printer_status", "print_label",
                     "bright_status", "bright_show"):
            self.assertIn(name, names)
            self.assertTrue(callable(getattr(m, m.TOOL_IMPLEMENTATIONS[name])))


if __name__ == "__main__":
    unittest.main()
