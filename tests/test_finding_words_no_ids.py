#!/usr/bin/env python3
"""A finding says what it means, never a path, an id, a code or a build (#774).

A house's findings quoted config file paths with line numbers, service and
entity ids (`tts.google_en_com`, `sensor.…`), hex error codes and firmware
build strings. The rules against them were there (#563,
`house_words.technical`) and these got through four gaps:

* an id the house has no name for was left as the id, on purpose
  ("a made-up name is worse") — and a service id such as `tts.speak` is in
  no names map, so it was always left;
* a look's conclusion kept every path and line number with its file names
  (`technical(files=False)` skipped the whole file rule);
* a build string with no version in front of it ("build 24C101") was not
  read as one;
* a row stored before the rule was never read again.

Now `house_words.lint` names every such fragment, and the display pass
(`findings_store.shown_words`, `shown_look`) says an id by the house's name
for it or by what it is ("the voice service"), so the sentence still reads;
a path is "a configuration file" and the rest leave for Details. A safety
row's words are its code's and are never touched.
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


class TestTheLint(unittest.TestCase):
    def test_each_kind_is_flagged(self):
        for said, token in (
                ("Edit /config/.storage/assist_pipeline.pipelines line 42.",
                 "/config/.storage/assist_pipeline.pipelines"),
                ("The pipeline still uses tts.google_en_com.", "tts.google_en_com"),
                ("sensor.attic_temp stopped at noon.", "sensor.attic_temp"),
                ("The hub answered 0x1f.", "0x1f"),
                ("It is on firmware build 24C101.", "build 24C101"),
                ("It runs v2.1.0_20240512 now.", "2.1.0_20240512"),
                ("The an internal name event stopped.", "an internal name")):
            with self.subTest(said):
                found = house_words.lint(said)
                self.assertTrue(any(token in f for f in found), found)

    def test_everyday_words_are_not_flagged(self):
        for said in ("Firmware 1.2 is fine on the gate controller.",
                     "The update to 2026.10.1 installed at 0:30.",
                     "The pump ran 3.5 hours, from 14:10 to 17:40.",
                     "Check the automations.yaml backup, e.g. last week's."):
            with self.subTest(said):
                self.assertEqual(house_words.lint(said, files=False), [])


class TestIdsAreSaidInWords(unittest.TestCase):
    NAMES = {"sensor.attic_temp": "Attic temperature"}

    def test_a_known_id_is_its_name(self):
        self.assertEqual(
            house_words.ids("sensor.attic_temp stopped at noon.", self.NAMES)[0],
            "Attic temperature stopped at noon.")

    def test_an_unknown_id_is_what_it_is(self):
        for said, words in (
                ("The pipeline still uses tts.google_en_com for replies.",
                 "The pipeline still uses the voice service for replies."),
                ("The old voice is set in tts.cloud_say.",
                 "The old voice is set in the voice service."),
                ("media_player.den_echo dropped off twice.",
                 "The speaker dropped off twice."),
                ("The hall speaker (media_player.den_echo) dropped off.",
                 "The hall speaker dropped off."),
                ("The sensor.attic_humidity sensor is stuck.",
                 "The sensor is stuck.")):
            with self.subTest(said):
                out, found = house_words.ids(said, self.NAMES)
                self.assertEqual(out, words)
                self.assertTrue(found)
                self.assertEqual(house_words.lint(out), [])

    def test_words_and_files_are_not_ids(self):
        for said in ("Check automations.yaml, e.g. the hall one.",
                     "Version 2026.10.1 is out."):
            with self.subTest(said):
                self.assertEqual(house_words.ids(said, {}), (said, []))


class TestTheShownRowIsPlain(StoresCase):
    def setUp(self):
        super().setUp()
        self._names = findings_store.DISPLAY_NAMES
        findings_store.DISPLAY_NAMES = lambda: {
            "sensor.attic_temp": "Attic temperature"}

    def tearDown(self):
        findings_store.DISPLAY_NAMES = self._names
        super().tearDown()

    def _stored(self, ts, **fields):
        items = findings_store._load()
        items.append({"ts": ts, "status": "open", "severity": "warning",
                      **fields})
        findings_store._write(items)

    def test_a_stored_model_row_is_shown_plain(self):
        ts = 1_700_000_200
        self._stored(
            ts, source=findings_store.RESIDENT_SOURCE,
            text="The assistant still speaks with the old voice",
            claim="The assistant still speaks with tts.google_en_com.",
            detail=("The pipeline at /config/.storage/assist_pipeline.pipelines "
                    "line 42 names tts.google_en_com. sensor.attic_temp is fine. "
                    "The hub answered 0x1f on firmware build 24C101."),
            fix="Pick the new voice in the voice assistant's settings.",
            triage={"verdict": "elevated", "at": 1_700_000_000,
                    "reason": "The file /config/.storage/core.config_entries "
                              "line 7 still points at tts.google_en_com."})
        listed = next(r for r in findings_store.listing()["findings"]
                      if r["ts"] == ts)
        case = cases.get(cases.case_id("findings", ts))
        for where, row in (("listing", listed), ("cases", case)):
            for field in ("claim", "detail", "fix"):
                with self.subTest(where=where, field=field):
                    self.assertEqual(house_words.lint(row.get(field) or ""), [],
                                     row.get(field))
            with self.subTest(where=where, field="look"):
                self.assertEqual(house_words.lint(row["triage"]["reason"],
                                                  files=False), [])
        self.assertIn("Attic temperature is fine.", listed["detail"])
        self.assertIn("the voice service", listed["claim"])
        self.assertTrue(listed["triage"]["reason"])

    def test_a_safety_row_keeps_its_words(self):
        ts = 1_700_000_300
        said = "Water at binary_sensor.kitchen_leak: shut the water off."
        self._stored(ts, source="safety", text="Water under the sink",
                     detail=said, fix="Shut off the water at the main.",
                     severity="critical")
        listed = next(r for r in findings_store.listing()["findings"]
                      if r["ts"] == ts)
        self.assertEqual(listed["detail"], said)


if __name__ == "__main__":
    unittest.main()
