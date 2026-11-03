"""Vesper's walkthrough: the stream that uses Morph like a person.

Held here: the stream exists and costs a Claude run, its charter is its own
system prompt, its ids come from dashboard.yaml, its rows file as
`Walkthrough: …` with the UX flag and route to Morph, and it is never
read-only by promise alone (it asks for no tool that writes).
"""
import json
import unittest

from test_devloop import DevloopCase  # noqa: F401 — shared fixtures
import devloop
from devloop import streams as streams_mod, upstream
import engine


class TestWalkthrough(unittest.TestCase):
    def test_it_is_a_claude_stream_that_stands_down_on_noise(self):
        self.assertEqual(devloop.STREAMS["walkthrough"]["cost"], "claude")
        self.assertFalse(devloop.STREAMS["walkthrough"]["default_on"])
        self.assertIn("walkthrough", upstream.CLAUDE_STREAMS)
        self.assertIn("walkthrough", upstream.STAND_DOWN_STREAMS)
        self.assertEqual(devloop.AUTOPILOT_HOURS["walkthrough"], 24)

    def test_the_charter_is_its_own_and_says_what_it_may_do(self):
        system = streams_mod.analyst_system("walkthrough")
        self.assertIn("You are brAIn", system)
        self.assertIn('press "open"', system)
        self.assertIn("refuses every write", system)
        self.assertNotIn("%(cap)d", system)

    def test_it_reads_the_ids_off_the_dashboard(self):
        text = "sections:\n  - id: s_ov_vesper\n    cards:\n      - id: c_lamp\n      - id: c_lamp\n"
        listed = streams_mod.morph_targets(text)
        self.assertIn("- s_ov_vesper", listed)
        self.assertEqual(listed.count("- c_lamp"), 1)
        self.assertIn("No card or section ids", streams_mod.morph_targets(""))

    def test_the_ids_ride_the_prompt(self):
        prompt = streams_mod.analyst_prompt(
            "walkthrough", "", streams_mod.morph_targets("id: c_lamp"))
        self.assertIn("- c_lamp", prompt)
        self.assertIn("Walk through Morph", prompt)

    def test_a_row_files_as_a_walkthrough_for_morph_with_the_ux_flag(self):
        reply = json.dumps({"rows": [{
            "title": "c_lamp: opened card drops its title", "what": "Held open, it loses its name.",
            "why": "At 390 the title is gone.", "done_when": "The title stays.",
            "impact": "every opened card", "ui": True, "addon": "Morph"}]})
        rows = streams_mod.parse_rows(reply, "walkthrough")
        self.assertEqual(rows[0]["where"], "Morph · Walkthrough: c_lamp: opened card drops its title")
        self.assertIs(rows[0]["ux"], True)

    def test_the_schema_takes_ui_and_addon_and_caps_rows(self):
        schema = streams_mod.reply_schema("walkthrough")
        item = schema["properties"]["rows"]
        self.assertIn("ui", item["items"]["properties"])
        self.assertIn("Morph", item["items"]["properties"]["addon"]["enum"])
        self.assertEqual(item["maxItems"], streams_mod.WALKTHROUGH_ROWS)

    def test_it_can_press_but_never_write(self):
        self.assertIn(f"{engine.MCP}screenshot_panel", engine.ANALYST_TOOLS)
        for tool in engine.ANALYST_TOOLS:
            self.assertNotRegex(tool, r"call_service|set_state|apply|delete")


if __name__ == "__main__":
    unittest.main()
