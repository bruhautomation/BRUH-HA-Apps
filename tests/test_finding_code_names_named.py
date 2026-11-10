#!/usr/bin/env python3
"""A code name leaves a finding as the thing it names, never as "an internal name" (#791).

The step that takes a snake_case code name out of a model's sentence
(`house_words.technical`, #618) put the words "an internal name" where the
name had been: "the an internal name event fired", "Nothing answers an
internal name today." The sentence broke, and the person could no longer
tell which thing was meant. Now a code name the house has a name for is said
by that name, an aside in brackets goes, and any other is said as its own
words ("bruh minecraft moment"); the code name itself still goes to the
row's Technical line. And whatever a row stored before this (the phrase is
in real houses' stores), no surface shows the phrase: the display pass
repairs it.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
from test_cases import StoresCase  # noqa: E402

PHRASE = "an internal name"


class TestTheWordsAreNeverThePhrase(unittest.TestCase):
    def test_a_code_name_is_said_as_its_words(self):
        for said, words in (
                ("The bruh_minecraft_moment event fired twice.",
                 "The bruh minecraft moment event fired twice."),
                ("Nothing answers shed_heater_moment today.",
                 "Nothing answers shed heater moment today."),
                # a second shape the issue never showed: a setting's key
                ("Turn off `garage_auto_close` for the weekend.",
                 "Turn off garage auto close for the weekend.")):
            with self.subTest(said):
                out, found = house_words.technical(said)
                self.assertNotIn(PHRASE, out)
                self.assertEqual(out, words)
                self.assertEqual(len(found), 1)

    def test_a_code_name_the_house_knows_is_said_by_its_name(self):
        names = {"input_boolean.garage_auto_close": "Garage closes itself"}
        out, found = house_words.technical(
            "Turn off garage_auto_close for the weekend.", names=names)
        self.assertEqual(out, "Turn off Garage closes itself for the weekend.")
        self.assertEqual(found, ["garage_auto_close"])

    def test_a_code_name_in_brackets_is_an_aside_and_goes(self):
        out, _ = house_words.technical(
            "The garage closes itself (garage_auto_close) at 22:00.")
        self.assertEqual(out, "The garage closes itself at 22:00.")


class TestAStoredPhraseIsRepairedOnScreen(StoresCase):
    """Rows a house stored while the old step wrote the phrase."""

    def _stored(self, **fields):
        items = findings_store._load()
        items.append({"ts": 1_700_000_100, "status": "open",
                      "source": findings_store.RESIDENT_SOURCE,
                      "severity": "warning", **fields})
        findings_store._write(items)
        return 1_700_000_100

    def _shown(self, ts):
        listed = next(r for r in findings_store.listing()["findings"]
                      if r["ts"] == ts)
        case = cases.get(cases.case_id("findings", ts))
        return listed, case

    def test_no_surface_shows_the_phrase(self):
        ts = self._stored(
            text="The an internal name event stopped firing",
            claim="The an internal name event stopped firing on Tuesday.",
            detail="It last fired on Tuesday. Nothing calls an internal name now.",
            fix="Turn on the automation that fires the event.",
            technical=["bruh_minecraft_moment"],
            triage={"verdict": "elevated", "at": 1_700_000_000,
                    "reason": "The an internal name event has not fired since "
                              "the update."})
        listed, case = self._shown(ts)
        for where, row in (("listing", listed), ("cases", case)):
            for field in ("text", "claim", "detail", "fix"):
                with self.subTest(where=where, field=field):
                    self.assertNotIn(PHRASE, str(row.get(field) or "").lower())
            with self.subTest(where=where, field="look"):
                self.assertNotIn(PHRASE, row["triage"].get("reason", "").lower())
        self.assertIn("event", listed["text"])
        self.assertTrue(listed["detail"].startswith("It last fired on Tuesday."))


class TestAModelRowNeverStoresThePhrase(StoresCase):
    def test_a_resident_case_keeps_its_words(self):
        row = findings_store.add_case({
            "text": "The bruh_minecraft_moment event stopped firing",
            "claim": "The bruh_minecraft_moment event stopped firing.",
            "detail": "It last fired on Tuesday.",
            "fix": "Turn the moment automation back on.",
            "kind": "problem"})
        self.assertIsNotNone(row)
        stored = findings_store.get(row["ts"])
        for field in ("text", "claim", "detail", "fix"):
            self.assertNotIn(PHRASE, stored.get(field, ""))
        self.assertIn("bruh minecraft moment", stored["claim"])
        self.assertIn("bruh_minecraft_moment", stored["technical"])


if __name__ == "__main__":
    unittest.main()
