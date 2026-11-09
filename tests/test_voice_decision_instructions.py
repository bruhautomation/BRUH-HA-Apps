#!/usr/bin/env python3
"""A settled voice does not leave brAIn's own files saying the old one.

A house's gap report (#769): the household chose brAIn's voice, brAIn
recorded it, and its own instruction files — an override of
chat_identity.md and the persona in personality.json — went on naming the
voice it replaced. brAIn then filed a finding about the conflict, with
nothing to press.

Those files are words a person wrote (⚙ › Instructions, ⚙ › Personality),
and the growth note that settles a voice can come from a conversation, so
brAIn does not rewrite them unattended: in the same step that stores the
voice it files ONE yes/no question per file, quoting the line, whose Yes
makes the edit — the old voice's name replaced by the new one, nothing
else touched. A model-written row about the conflict carries the same
button. After Yes no instruction file names the replaced voice.

Invented voices: Alba replaced by Sara, and a second house where Nova
gives way to Ember in a "Voice:" line the strict growth patterns never
read.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import findings_store  # noqa: E402
import instructions  # noqa: E402
import personality  # noqa: E402
import self_care  # noqa: E402
# Imported before any test saves the store's hooks: the import hands
# `findings_store` its own, and a tearDown must not put back the empty ones.
import server  # noqa: E402
from fake_core_ws import drive_app  # noqa: E402

IDENTITY = ("You are brAIn, the house's assistant.\n"
            "You speak with the Alba voice on every speaker.\n"
            "Keep answers short.\n")
PERSONA = "Calm and dry.\nVoice: Alba, unhurried.\nNever shouts."


class FilesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._olds = (personality.STORE, personality.FEATURES_FILE,
                      instructions.DIR, findings_store.FINDINGS_FILE,
                      findings_store.INBOX_DIR, findings_store.SETTLED_FILE,
                      findings_store.SELF_CARE, findings_store.IDENTITY)
        personality.STORE = str(root / "personality.json")
        personality.FEATURES_FILE = str(root / "features.json")
        instructions.DIR = root / "instructions"
        instructions.DIR.mkdir()
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.SELF_CARE = self_care.as_question
        findings_store.IDENTITY = personality.identity
        self.identity = instructions.DIR / "chat_identity.md"
        self.identity.write_text(IDENTITY, encoding="utf-8")
        personality.save("Juniper", PERSONA, voice="Alba")

    def tearDown(self):
        self.identity.unlink(missing_ok=True)
        instructions.apply("chat_identity")
        (personality.STORE, personality.FEATURES_FILE, instructions.DIR,
         findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.SELF_CARE,
         findings_store.IDENTITY) = self._olds
        self.tmp.cleanup()

    def files_say(self) -> str:
        return (self.identity.read_text(encoding="utf-8") + "\n"
                + personality.load()["persona"])


class TestTheQuestionsAndTheirYes(FilesCase):
    def test_one_question_per_file_and_yes_makes_the_edit(self):
        personality.add_growth("The voice changed from Alba to Sara.")
        rows = self_care.voice_questions("Sara", "Alba")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["kind"], "question")
            self.assertIn("Sara", row["claim"])
            self.assertTrue(row["claim"].rstrip().endswith("?"))
            self.assertTrue(self_care.correct(row))
        said = self.files_say()
        self.assertNotIn("Alba", said)
        self.assertIn("You speak with the Sara voice on every speaker.", said)
        self.assertIn("Voice: Sara, unhurried.", said)
        self.assertIn("Keep answers short.", said)
        self.assertIn("Never shouts.", said)

    def test_a_voice_line_the_growth_patterns_never_read(self):
        self.identity.write_text("Voice: Nova\nBe brief.\n", encoding="utf-8")
        personality.save("Juniper", "Plain.", voice="Ember")
        [row] = self_care.voice_questions("Ember", "Nova")
        self.assertTrue(self_care.correct(row))
        self.assertEqual(self.identity.read_text(encoding="utf-8"),
                         "Voice: Ember\nBe brief.\n")

    def test_files_that_already_agree_ask_nothing(self):
        self.assertEqual(self_care.voice_questions("Alba", "Alba"), [])

    def test_a_conflict_finding_carries_the_apply_button(self):
        personality.add_growth("The voice changed from Alba to Sara.")
        [row] = findings_store.add_many([{
            "text": "brAIn's instructions still name the Alba voice",
            "detail": "Memory says the household chose Sara.",
            "fix": "Update the instructions to say Sara.",
            "source": "resident", "severity": "info"}])
        self.assertEqual(row["source"], self_care.SOURCE)
        self.assertTrue(self_care.correct(row))
        self.assertNotIn("Alba", self.files_say())


class TestInTheSameStep(FilesCase):
    def setUp(self):
        super().setUp()
        self.server = server

    def test_settling_the_voice_files_the_questions_and_yes_clears_it(self):
        async def go(client):
            resp = await client.post(
                "/api/personality/growth",
                json={"text": "The voice changed from Alba to Sara."})
            return resp.status

        self.assertEqual(drive_app(self.server.make_app, go), 200)
        rows = [f for f in findings_store.list_all("live")
                if f.get("source") == self_care.SOURCE]
        self.assertEqual(len(rows), 2, rows)
        for row in rows:
            asyncio.run(self.server._end_finding(
                row, self.server.FINDING_VERBS["confirm"], ""))
        self.assertEqual(personality.identity()["voice"], "Sara")
        self.assertNotIn("Alba", self.files_say())
        json.dumps(rows)


if __name__ == "__main__":
    unittest.main()
