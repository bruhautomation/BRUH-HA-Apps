"""A personality written as a rich object is read whole, and a broken import is repaired.

Morph's old `personality.js` describes the assistant as an object of
nested parts — a one-line summary, traits as a list, voice rules as an
object of lists, a nested description — and its growth log under keys of
its own choosing. The import kept only the object's top-level STRING
values, so a house came out with a persona of two lines and no growth at
all. `parse_morph` now renders every part (lists as lines, nested objects
as "key: value" lines), reads growth under any of the reasonable keys or
as plain strings, and `repair_from_morph` replaces a stored file that is
exactly an earlier, poorer import — and never one somebody has edited.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import personality  # noqa: E402

RICH_JS = r"""// The dashboard's assistant, as this household describes it.
export const PERSONA = {
  name: "Wren",
  line: "A patient, plain-spoken helper who knows the house well.",
  born: "2026-03-14",
  traits: ["calm under pressure", "notices small things", 'dry, never sarcastic'],
  voice: {
    rules: ["say what changed in one sentence", "never apologise twice"],
    tone: "warm",
  },
  likes: ["tidy schedules", "the garden at dusk"],
  description: {
    short: "Keeps the lights sensible.",
    long: "Prefers asking once over guessing twice.",
  },
};

export const GROWTH = [
  { when: "2026-04-02", what: "Learned the loft is the music room." },
  { day: "2026-05-11", growth: "Stopped reading the weather out twice." },
  { on: "2026-06-20", entry: "Calls the back gate the orchard gate." },
  "Speaks more softly after nine.",
];
"""


class RichCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / ".brain").mkdir()
        self.file = str(Path(self.tmp.name) / ".brain" / "personality.json")
        self.src = Path(self.tmp.name) / "personality.js"
        self.src.write_text(RICH_JS, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()


class TestEveryPartIsRead(RichCase):
    def test_nested_lists_and_objects_lose_nothing(self):
        data = personality.parse_morph(RICH_JS)
        self.assertEqual(data["name"], "Wren")
        persona = data["persona"]
        for part in ("patient, plain-spoken helper", "2026-03-14",
                     "calm under pressure", "notices small things",
                     "dry, never sarcastic", "say what changed in one sentence",
                     "never apologise twice", "warm", "tidy schedules",
                     "the garden at dusk", "Keeps the lights sensible.",
                     "Prefers asking once over guessing twice."):
            self.assertIn(part, persona)
        self.assertIn("- calm under pressure",
                      [line.strip() for line in persona.splitlines()])
        self.assertTrue(any(line.strip() == "short: Keeps the lights sensible."
                            for line in persona.splitlines()), persona)

    def test_growth_under_any_reasonable_key_or_as_a_string(self):
        growth = personality.parse_morph(RICH_JS)["growth"]
        texts = [g["text"] for g in growth]
        self.assertEqual(len(growth), 4, growth)
        self.assertIn("Learned the loft is the music room.", texts)
        self.assertIn("Stopped reading the weather out twice.", texts)
        self.assertIn("Calls the back gate the orchard gate.", texts)
        self.assertIn("Speaks more softly after nine.", texts)
        dates = {g["text"]: g["date"] for g in growth}
        self.assertEqual(dates["Learned the loft is the music room."], "2026-04-02")
        self.assertEqual(dates["Calls the back gate the orchard gate."], "2026-06-20")

    def test_a_plain_persona_text_still_reads_as_itself(self):
        data = personality.parse_morph(
            'export const PERSONA = { name: "Wren", persona: "Quiet." };')
        self.assertEqual(data["persona"], "Quiet.")


class TestABrokenImportIsRepaired(RichCase):
    def broken(self) -> dict:
        """What the old reader stored from RICH_JS."""
        data = {"name": "Wren",
                "persona": ("line: A patient, plain-spoken helper who knows "
                            "the house well.\nborn: 2026-03-14"),
                "growth": [], "updated_at": 1_760_000_000}
        Path(self.file).write_text(json.dumps(data), encoding="utf-8")
        return data

    def test_the_poorer_import_is_replaced_once(self):
        self.broken()
        said = personality.repair_from_morph(str(self.src), self.file)
        self.assertIn("repaired", said)
        data = personality.load(self.file)
        self.assertIn("calm under pressure", data["persona"])
        self.assertEqual(len(data["growth"]), 4)
        self.assertEqual(personality.repair_from_morph(str(self.src), self.file), "")

    def test_a_persona_somebody_edited_is_left_alone(self):
        data = self.broken()
        data["persona"] += "\nLikes a joke about the weather."
        Path(self.file).write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(personality.repair_from_morph(str(self.src), self.file), "")
        self.assertNotIn("calm under pressure",
                         personality.load(self.file)["persona"])

    def test_growth_recorded_since_is_left_alone(self):
        data = self.broken()
        data["growth"] = [{"date": "2026-09-01", "text": "Learned a new room."}]
        Path(self.file).write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(personality.repair_from_morph(str(self.src), self.file), "")

    def test_a_renamed_assistant_is_left_alone(self):
        data = self.broken()
        data["name"] = "Robin"
        Path(self.file).write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(personality.repair_from_morph(str(self.src), self.file), "")

    def test_no_stored_file_or_no_morph_file_does_nothing(self):
        self.assertEqual(personality.repair_from_morph(str(self.src), self.file), "")
        self.broken()
        self.assertEqual(personality.repair_from_morph(
            str(Path(self.tmp.name) / "absent.js"), self.file), "")


if __name__ == "__main__":
    unittest.main()
