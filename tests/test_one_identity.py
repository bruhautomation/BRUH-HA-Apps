#!/usr/bin/env python3
"""One stored answer for who brAIn is, and brAIn's own upkeep in plain words.

A real house's findings and cards contradicted each other about brAIn
itself: one finding said "My spoken voice changed from voice A to voice
B", another that the household chose voice C, and a card that voice B was
already the voice — each from a model's memory. One finding told the owner
to edit "line 27 of chat_identity.md" and call `note_personality_change`,
with entity and model ids in the text, in the first person beside rows
saying "brAIn" — asking the owner to do brAIn's own housekeeping.

Now:

* the voice is stored beside the name (`personality.json` `voice`, set in
  ⚙ › Personality or by the growth note that says it changed), and
  `personality.identity()` is the one answer; a model's sentence about
  brAIn's voice or name is replaced by that answer or dropped
  (`house_words.self_said`), in findings and on cards, and the card prompt
  carries it;
* a model's "I"/"my" is "brAIn", and the household's name for brAIn in a
  model's prose is "brAIn" too, so a surface that speaks the name says one;
* a row about brAIn itself loses its file paths, tool names, ids and model
  ids (`house_words.self_said(dev=True)`), the place 4.0.4's
  `without_log_text` scrubs log text;
* a row telling the owner to change a line of brAIn's own instructions is
  a yes/no question brAIn answers itself: Yes takes the line out
  (`self_care`).

The examples are not the house's.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import instructions  # noqa: E402
import personality  # noqa: E402
import self_care  # noqa: E402

from test_card_verdict_post_check import GenerateCase  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = str(Path(self.tmp.name) / "personality.json")
        self._old = personality.STORE
        personality.STORE = self.file

    def tearDown(self):
        personality.STORE = self._old
        self.tmp.cleanup()


class TestTheStoredAnswer(StoreCase):
    def test_the_voice_is_stored_beside_the_name(self):
        personality.save("Juniper", "", path=self.file, voice="Aurora")
        self.assertEqual(personality.load(self.file)["voice"], "Aurora")
        self.assertEqual(personality.identity(path=self.file)["voice"],
                         "Aurora")
        # A save that says nothing of the voice keeps it.
        personality.save("Juniper", "Dry.", path=self.file)
        self.assertEqual(personality.load(self.file)["voice"], "Aurora")

    def test_a_growth_note_that_the_voice_changed_is_the_new_answer(self):
        personality.add_growth("The spoken voice changed from Aurora to "
                               "Ember for the kitchen speaker.",
                               path=self.file)
        self.assertEqual(personality.load(self.file)["voice"], "Ember")

    def test_the_prompt_line_quotes_it(self):
        personality.save("", "", path=self.file, voice="Ember")
        line = personality.identity_line(path=self.file)
        self.assertIn("Ember", line)
        self.assertIn("never from memory", line)


class TestSelfSaid(unittest.TestCase):
    def test_a_voice_claim_reads_the_stored_answer(self):
        said = house_words.self_said(
            "My spoken voice changed from Nova to Ember. The hall speaker "
            "answers.", name="brAIn", voice="Aurora")
        self.assertNotIn("Nova", said)
        self.assertNotIn("Ember", said)
        self.assertIn("Aurora", said)
        self.assertIn("The hall speaker answers.", said)

    def test_with_no_stored_voice_the_claim_goes(self):
        said = house_words.self_said(
            "brAIn now speaks with Nova. The hall speaker answers.",
            name="brAIn", voice="")
        self.assertEqual(said, "The hall speaker answers.")

    def test_first_person_is_brain_and_one_name(self):
        self.assertEqual(house_words.self_said(
            "I see the porch light on at noon.", name="brAIn"),
            "brAIn sees the porch light on at noon.")
        self.assertEqual(house_words.self_said(
            "Juniper noticed my last look ran late.", name="Juniper"),
            "brAIn noticed brAIn's last look ran late.")

    def test_developer_text_leaves_a_row_about_brain(self):
        said = house_words.self_said(
            "Update the wake phrase. Edit line 12 of curiosity.md and call "
            "get_findings; it runs on claude-sonnet-4-5.", name="brAIn",
            dev=True)
        for word in (".md", "get_findings", "claude-", "line 12"):
            self.assertNotIn(word, said)
        self.assertIn("Update the wake phrase.", said)


class TestAFindingAboutBrain(StoreCase):
    def setUp(self):
        super().setUp()
        self.dir = Path(self.tmp.name)
        self._olds = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                      instructions.DIR, findings_store.SELF_CARE,
                      findings_store.IDENTITY)
        findings_store.FINDINGS_FILE = self.dir / "findings.json"
        findings_store.INBOX_DIR = self.dir / "inbox"
        self._settled = findings_store.SETTLED_FILE
        findings_store.SETTLED_FILE = self.dir / "settled.json"
        instructions.DIR = self.dir / "instructions"
        instructions.DIR.mkdir()
        findings_store.SELF_CARE = self_care.as_question
        findings_store.IDENTITY = personality.identity
        personality.save("", "", path=self.file, voice="Aurora")

    def tearDown(self):
        # Whatever an override put in force goes back to the shipped text.
        (instructions.DIR / "curiosity.md").unlink(missing_ok=True)
        instructions.apply("curiosity")
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         instructions.DIR, findings_store.SELF_CARE,
         findings_store.IDENTITY) = self._olds
        findings_store.SETTLED_FILE = self._settled
        super().tearDown()

    def test_a_model_row_reads_the_one_answer_in_plain_words(self):
        [row] = findings_store.add_many([{
            "text": "My announcements now use the Nova voice",
            "detail": "I switched my voice to Nova after the update; "
                      "sensor.brain_health read ok.",
            "fix": "Call note_personality_change to record it.",
            "source": "resident", "severity": "info"}])
        prose = " ".join(row[k] for k in ("text", "detail", "fix"))
        self.assertNotIn("Nova", prose)
        self.assertNotIn("note_personality_change", prose)
        self.assertNotRegex(prose, r"\b(?:I|My|my)\b")

    def test_a_stale_instruction_line_is_brains_own_question(self):
        (instructions.DIR / "curiosity.md").write_text(
            "Ask about the house.\nAlways mention the Nova voice.\n"
            "Keep it short.\n", encoding="utf-8")
        [row] = findings_store.add_many([{
            "text": "brAIn's curiosity instructions still name an old voice",
            "detail": "Line 2 of curiosity.md says Nova.",
            "fix": "Edit line 2 of curiosity.md to remove it.",
            "source": "resident", "severity": "info"}])
        self.assertEqual(row["source"], self_care.SOURCE)
        self.assertEqual(row["kind"], "question")
        self.assertIn("Always mention the Nova voice.", row["claim"])
        self.assertTrue(row["claim"].rstrip().endswith("?"))
        self.assertEqual(row["fix"], "")
        self.assertTrue(self_care.correct(row))
        self.assertEqual(
            (instructions.DIR / "curiosity.md").read_text(encoding="utf-8"),
            "Ask about the house.\nKeep it short.\n")

    def test_a_line_brain_cannot_find_is_not_a_question(self):
        [row] = findings_store.add_many([{
            "text": "brAIn's curiosity instructions are out of date",
            "fix": "Edit line 9 of curiosity.md.",
            "source": "resident", "severity": "info"}])
        self.assertNotEqual(row["source"], self_care.SOURCE)
        self.assertNotIn("curiosity.md", row["fix"])


class TestThroughTheServer(GenerateCase):
    def setUp(self):
        super().setUp()
        self._pfile = personality.STORE
        personality.STORE = str(Path(self.tmp.name) / "personality.json")
        personality.save("", "", voice="Aurora")
        self.prompts = []
        old_run = self.engine.run_claude

        def run(prompt, *a, **k):
            self.prompts.append(prompt)
            return old_run(prompt, *a, **k)
        self.engine.run_claude = run

    def tearDown(self):
        personality.STORE = self._pfile
        super().tearDown()

    def test_a_card_reads_the_stored_voice(self):
        self.reply.update(
            title="Kitchen speaker: 14 announcements",
            summary="I announced the laundry 14 times. My voice is already "
                    "Nova on the kitchen speaker.",
            highlights=[{"label": "Announcements", "value": "14"}])
        card = self.generate()
        self.assertNotIn("Nova", card["summary"])
        self.assertNotRegex(card["summary"], r"\b(?:I|My)\b")
        self.assertIn("Aurora", self.prompts[-1])

    def test_yes_on_the_question_takes_the_line_out(self):
        old_dir = instructions.DIR
        instructions.DIR = Path(self.tmp.name) / "instructions"
        instructions.DIR.mkdir()
        self.addCleanup(setattr, instructions, "DIR", old_dir)
        old_settled = findings_store.SETTLED_FILE
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        self.addCleanup(setattr, findings_store, "SETTLED_FILE", old_settled)
        path = instructions.DIR / "curiosity.md"
        self.addCleanup(instructions.apply, "curiosity")
        self.addCleanup(path.unlink, missing_ok=True)
        path.write_text("One.\nSay Nova.\nThree.\n", encoding="utf-8")
        [row] = findings_store.add_many([{
            "text": "Old voice in curiosity instructions",
            "fix": "Edit line 2 of curiosity.md.", "source": "resident",
            "severity": "info"}])
        self.assertEqual(row["source"], self_care.SOURCE)
        asyncio.run(self.server._end_finding(
            row, self.server.FINDING_VERBS["confirm"], ""))
        self.assertEqual(path.read_text(encoding="utf-8"), "One.\nThree.\n")
        self.assertFalse(any(f.get("ts") == row["ts"] for f in
                             findings_store.list_all("live")))
        json.dumps(row)


if __name__ == "__main__":
    unittest.main()
