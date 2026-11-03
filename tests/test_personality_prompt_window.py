#!/usr/bin/env python3
"""What a prompt carries about who brAIn is: the household's own words first.

Three reports from one house:

* #640 — `personality.json` held `"voice": "says so"`, stored by an older
  parser from a note ending "…the persona now says so.", and every card
  prompt said "brAIn's spoken voice is says so." Today's parser reads that
  note as naming no voice, but nothing re-read a value already stored. The
  store re-validates the voice as it loads: one that no longer reads as a
  name is re-read from the household's own notes, newest first, or dropped.
* #633 — the prompt carried the last three growth entries, and those were
  three nightly self-notes, so the household's settled entries (the voice
  they chose among them) were out of every prompt. The household's newest
  three are carried, and at most one of the assistant's own beside them.
* #624 — an older line in an instruction override still named a rejected
  voice. The chat and the terminal now carry the stored voice in the
  personality block as the answer that outranks any other line naming one.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import personality  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / "personality.json")
        self.features = str(Path(self.tmp.name) / "features.json")
        Path(self.features).write_text(json.dumps({"personality": True}),
                                       encoding="utf-8")
        self._old = personality.FEATURES_FILE
        personality.FEATURES_FILE = self.features
        self.addCleanup(setattr, personality, "FEATURES_FILE", self._old)

    def write(self, data: dict):
        Path(self.file).write_text(json.dumps(data), encoding="utf-8")


class TestAStoredVoiceIsReread(StoreCase):
    def test_a_junk_voice_is_reread_from_the_households_notes(self):
        self.write({"name": "Juniper", "voice": "says so", "growth": [
            {"date": "2026-01-02", "text": "The voice changed to Ember."},
            {"date": "2026-01-05", "text": "We chose the Aurora voice, "
             "not Nova; the persona now says so."},
        ]})
        data = personality.load(self.file)
        self.assertEqual(data["voice"], "Ember")
        line = personality.identity_line(path=self.file)
        self.assertNotIn("says so", line)
        self.assertIn("Ember", line)

    def test_with_no_note_naming_one_it_is_dropped(self):
        self.write({"name": "Juniper", "voice": "says so", "growth": []})
        self.assertEqual(personality.load(self.file)["voice"], "")
        self.assertIn("not recorded", personality.identity_line(path=self.file))

    def test_a_self_note_never_sets_it(self):
        self.write({"voice": "says so", "growth": [
            {"date": "2026-01-02", "text": "The voice changed to Ember.",
             "by": "self"}]})
        self.assertEqual(personality.load(self.file)["voice"], "")

    def test_a_voice_a_person_typed_stands(self):
        for voice in ("Aurora", "sara", "Jenny Neural", "en_GB-alba-medium"):
            with self.subTest(voice=voice):
                self.write({"voice": voice})
                self.assertEqual(personality.load(self.file)["voice"], voice)


class TestTheHouseholdsGrowthComesFirst(StoreCase):
    GROWTH = [
        {"date": "2026-01-01", "text": "Keep answers short."},
        {"date": "2026-01-02", "text": "Say the room before the device."},
        {"date": "2026-01-03", "text": "The voice changed to Ember."},
        {"date": "2026-01-04", "text": "Fewer evening messages.", "by": "self"},
        {"date": "2026-01-05", "text": "Keep messages rare.", "by": "self"},
        {"date": "2026-01-06", "text": "Speak only when asked.", "by": "self"},
    ]

    def test_three_self_notes_do_not_crowd_out_the_household(self):
        block = personality.prompt_block({"name": "Juniper", "persona": "Dry.",
                                          "growth": self.GROWTH})
        for text in ("Keep answers short.", "Say the room before the device.",
                     "The voice changed to Ember."):
            self.assertIn(text, block)
        self.assertEqual(block.count("(your own note)"), 1)
        self.assertIn("Speak only when asked.", block)        # the newest own
        self.assertNotIn("Fewer evening messages.", block)

    def test_the_window_keeps_the_stored_order(self):
        kept = personality.prompt_growth(self.GROWTH)
        self.assertEqual([g["date"] for g in kept],
                         ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-06"])


class TestTheVoiceOutranksAnOlderLine(StoreCase):
    def test_the_chat_block_carries_the_stored_voice(self):
        personality.save("Juniper", "Dry.", path=self.file, voice="Aurora")
        block = personality.prompt_block(personality.load(self.file))
        self.assertIn("Your spoken voice is Aurora", block)
        self.assertIn("this one stands", block)
        self.assertIn("Aurora", personality.section(self.file))

    def test_no_voice_says_nothing_about_one(self):
        personality.save("Juniper", "Dry.", path=self.file)
        self.assertNotIn("voice", personality.prompt_block(
            personality.load(self.file)).lower())


if __name__ == "__main__":
    unittest.main()
