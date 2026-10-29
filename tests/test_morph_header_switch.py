"""A switch can ride in its section's title row as a pill.

The owner asked for a pause toggle to be named by its entity and to "go
somewhere more useful, like in the header of the card as a button". The
panel draws a ``switch`` card with ``options.header: true`` in the title row
(``measure-morph``'s owner block drives it in a browser); what is checked
here is the half a Tell depends on: the option survives Morph's own reading
of dashboard.yaml, and the guide every Tell reads says it exists.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from morph_env import MorphEnv

AGENTS = Path(__file__).resolve().parent.parent / "brain" / "morph" / "defaults" / "AGENTS.md"

DOC = {"floors": [{"title": "Outside", "sections": [{"title": "Yard", "cards": [
    {"entity": "switch.irrigation"},
    {"type": "switch", "entity": "input_boolean.watering_paused", "name": "Pause watering",
     "options": {"header": True}},
]}]}]}


class TestTheOptionSurvives(unittest.TestCase):
    def test_normalize_and_a_round_trip_keep_options_header(self):
        with MorphEnv() as env:
            dash, problems = env.store.normalize(DOC)
            self.assertEqual([], problems)
            cards = dash["floors"][0]["sections"][0]["groups"][0]["cards"]
            pause = cards[1]
            self.assertEqual("switch", pause["type"])
            self.assertEqual("input_boolean.watering_paused", pause["entity"])
            self.assertEqual("Pause watering", pause["name"])
            self.assertIs(True, pause["options"]["header"])
            again, _ = env.store.load_text(env.store.dump(dash))
            self.assertEqual(dash, again)


class TestTheGuideSaysSo(unittest.TestCase):
    def test_agents_md_names_the_header_switch(self):
        text = AGENTS.read_text(encoding="utf-8")
        self.assertIn("`options.header: true`", text)
        row = next(line for line in text.splitlines() if line.startswith("| `switch` |"))
        self.assertIn("options.header", row)


if __name__ == "__main__":
    unittest.main()
