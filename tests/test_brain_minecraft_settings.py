"""⚙ › Minecraft: the companion's settings are brAIn's (#592).

The owner: "I'm not seeing any way to set the model … this needs to be a
part of brain not BRUH Minecraft." The panel's `minecraft_companion` is the
one writer of `/config/.brain/minecraft/settings.json`: on/off, the family
list, bedtime, the budgets (0 = unlimited, the default) and the model and
effort for replies and builds, "Default" resolved through `model_plan` and
written beside the choice so the integration's listener uses it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "brain" / "panel"))

import minecraft_companion as mcp  # noqa: E402
import model_plan  # noqa: E402

rules = mcp.rules
FAMILY = [{"person": "Kaz", "role": "child", "players": [".Kaz8044"]},
          {"person": "Dad", "role": "reader", "players": ["BenMC13765"], "nicknames": ["Daddy"]}]


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self.shared = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.shared, True)
        (self.shared / "personality.json").write_text(json.dumps({"name": "Juniper"}))
        for p in (patch.object(mcp, "_thinking", lambda: "normal"),
                  patch.object(mcp, "_chat_agent_model", lambda: "")):
            p.start()
            self.addCleanup(p.stop)

    def saved(self) -> dict:
        return json.loads((self.shared / "minecraft" / "settings.json").read_text())


class TestTheSettings(SettingsCase):
    def test_a_fresh_house_is_off_with_no_limits(self):
        s = mcp.load(str(self.shared))
        self.assertFalse(s["enabled"])
        self.assertEqual(s["budgets"], {"daily_turns": 0, "daily_actions": 0, "per_session": 0})

    def test_save_keeps_the_family_budgets_and_models(self):
        out = mcp.save({"enabled": True, "people": FAMILY, "budgets": {"daily_turns": 0,
                                                                       "daily_actions": 50},
                        "chat_model": "haiku", "build_model": "opus", "build_effort": "high",
                        "bedtime_entity": "binary_sensor.boys_door=off"}, str(self.shared))
        self.assertTrue(out["enabled"])
        self.assertEqual(out["people"][1]["nicknames"], ["Daddy"])
        self.assertEqual(out["budgets"]["daily_actions"], 50)
        self.assertEqual(out["budgets"]["daily_turns"], 0)
        self.assertEqual((out["build_model"], out["build_effort"]), ("opus", "high"))
        self.assertTrue(self.saved()["saved_at"])
        # The listener reads the same file through the same rules.
        self.assertEqual(rules.effective_settings(str(self.shared))["build_model"], "opus")

    def test_what_cannot_be_kept_is_said(self):
        for bad in ({"people": [{"person": "X"}]}, {"budgets": {"daily_turns": -1}},
                    {"budgets": {"nonsense": 1}}, {"chat_model": "gpt-4"},
                    {"chat_effort": "extreme"}, {"enabled": "yes"},
                    {"bedtime_entity": "door"}):
            with self.subTest(bad=bad), self.assertRaises(rules.RulesError):
                mcp.save(bad, str(self.shared))
        self.assertFalse((self.shared / "minecraft" / "settings.json").exists())


class TestDefaultIsAModelPlanAnswer(SettingsCase):
    def test_a_reply_is_quick_and_a_build_is_the_chats_model(self):
        self.assertEqual(model_plan.JOBS["minecraft_chat"][:2], ("haiku", "low"))
        models = mcp.resolved_models()
        self.assertEqual(models["chat"], {"model": "haiku", "effort": "low"})
        self.assertEqual(models["build"]["model"], "sonnet")
        with patch.object(mcp, "_chat_agent_model", lambda: "opus"):
            self.assertEqual(mcp.resolved_models()["build"]["model"], "opus")

    def test_publish_makes_no_folder_for_a_house_without_the_game(self):
        # A panel start must not create the shared folder (conftest keeps it
        # missing so a started panel cannot turn Personality off for later
        # tests) nor a minecraft folder in a house without BRUH Minecraft.
        missing = self.shared / "nowhere"
        self.assertFalse(mcp.publish(str(missing)))
        self.assertFalse(missing.exists())
        self.assertFalse(mcp.publish(str(self.shared)))
        self.assertFalse((self.shared / "minecraft").exists())

    def test_publish_writes_it_beside_the_settings_only_when_it_moved(self):
        mcp.save({"enabled": True}, str(self.shared))
        self.assertFalse(mcp.publish(str(self.shared)))
        with patch.object(mcp, "_thinking", lambda: "generous"):
            self.assertTrue(mcp.publish(str(self.shared)))
        self.assertEqual(self.saved()["models"]["chat"]["model"], "sonnet")
        self.assertTrue(self.saved()["enabled"])


class TestTheView(SettingsCase):
    def test_it_shows_the_name_the_family_today_and_the_talk(self):
        mcp.save({"enabled": True, "people": FAMILY}, str(self.shared))
        base = self.shared / "minecraft"
        (base / "state.json").write_text(json.dumps(
            {"day": rules.day_of(__import__("time").time()), "turns": 3, "actions": 1,
             "paused": True, "paused_by": "Dad"}))
        (base / "talks.json").write_text(json.dumps({"talks": [{"person": "Dad", "said": "hi"}]}))
        view = mcp.view(str(self.shared))
        self.assertEqual(view["name"], "Juniper")
        self.assertEqual(view["wake_words"], ["Juniper", "brain"])
        self.assertEqual(view["today"], {"turns": 3, "actions": 1})
        self.assertTrue(view["paused"])
        self.assertEqual(view["talks"][0]["said"], "hi")
        self.assertEqual(view["model_choices"], ["", "haiku", "sonnet", "opus"])


class TestThePanelPage(unittest.TestCase):
    def test_the_section_is_in_settings_and_shown_only_with_bruh_minecraft(self):
        html = (REPO / "brain" / "panel" / "index.html").read_text()
        js = (REPO / "brain" / "panel" / "app.js").read_text()
        self.assertIn('id="setNavMinecraft" hidden', html)
        self.assertIn('id="setsecMinecraft" data-sec="minecraft"', html)
        self.assertIn('"minecraft", "instructions"', js)
        self.assertIn("minecraft: () => loadMinecraft(),", js)
        self.assertIn("nav.hidden = !d.present;", js)
        for label in ("For answering in chat", "For building", "Effort for answering",
                      "Replies and greetings a day", "0 means no limit"):
            self.assertIn(label, js)

    def test_the_routes(self):
        src = (REPO / "brain" / "panel" / "server.py").read_text()
        self.assertIn('app.router.add_get("/api/minecraft", h_minecraft_get)', src)
        self.assertIn('app.router.add_put("/api/minecraft", h_minecraft_put)', src)
        self.assertIn('app.router.add_post("/api/minecraft/undo", h_minecraft_undo)', src)
        self.assertIn('"bruh_minecraft", "get_companion"', src)


if __name__ == "__main__":
    unittest.main()
