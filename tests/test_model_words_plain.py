#!/usr/bin/env python3
"""A model-written row is stored in the words the house uses.

A real house's Resident cases and card findings read like a developer's
notes: `binary_sensor.hall_motion` where the house calls it "Hall motion",
"04:00–14:00 UTC" where every other surface speaks local time, and the
add-on's own Supervisor slug (`abcd1234_brain`) where a person knows it as
brAIn. The prompts say not to; `house_words` is the deterministic half,
applied where a model-written row's claim, detail and fix are stored. A
check's row is never touched — its `text` is the key it re-reports and
clears under — and evidence keeps its ids, which is where they belong.
"""

import datetime as dt
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import resident  # noqa: E402

NAMES = {"binary_sensor.hall_motion": {"name": "Hall motion"},
         "switch.attic_fan": {"name": "Attic fan"},
         "automation.night_fan": {"name": "Night fan"}}
ENTITY_RE = re.compile(r"\b(?:binary_sensor|switch|automation)\.[a-z0-9_]+\b")
SLUG_RE = re.compile(r"\b[0-9a-f]{8}_brain\b")
# A fixed zone two hours ahead of UTC, so a converted time is checkable
# without depending on the machine's own zone database.
PLUS_TWO = dt.timezone(dt.timedelta(hours=2))
NOON = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc).timestamp()

CLAIM = "binary_sensor.hall_motion has not reported since 04:00 UTC"
DETAIL = ("switch.attic_fan ran 04:00–14:00 UTC while automation.night_fan "
          "re-entered the control branch; abcd1234_brain logged it at "
          "2026-10-09T03:15:00Z.")
FIX = "Restart the hub that binary_sensor.hall_motion pairs through."


def leaks(text: str) -> list[str]:
    out = []
    if ENTITY_RE.search(text or ""):
        out.append("entity id")
    if "UTC" in (text or "") or re.search(r"\d(?:Z|\+00:?00)\b", text or ""):
        out.append("UTC")
    if SLUG_RE.search(text or ""):
        out.append("slug")
    return out


class TestTheWords(unittest.TestCase):
    def test_representative_strings_come_out_plain(self):
        for text in (CLAIM, DETAIL, FIX):
            out = house_words.plain(text, NAMES, PLUS_TWO, now=NOON)
            self.assertEqual(leaks(out), [], out)
        out = house_words.plain(DETAIL, NAMES, PLUS_TWO, now=NOON)
        self.assertIn("Attic fan ran 06:00–16:00", out)
        self.assertIn("brAIn logged it at 9 Oct 05:15", out)

    def test_an_id_the_house_has_no_name_for_stays_an_id(self):
        out = house_words.plain("sensor.mystery is stuck", NAMES, None)
        self.assertEqual(out, "sensor.mystery is stuck")

    def test_a_name_beside_its_own_id_is_said_once(self):
        out = house_words.plain("Hall motion (binary_sensor.hall_motion)",
                                NAMES, None)
        self.assertEqual(out, "Hall motion")

    def test_a_file_name_is_not_an_entity(self):
        out = house_words.plain("edit automations.yaml", NAMES, None)
        self.assertEqual(out, "edit automations.yaml")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE,
                     findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "config" / ".brain" / "findings_state.json")
        findings_store.DISPLAY_NAMES = lambda: NAMES
        findings_store.HOUSE_TZ = lambda: PLUS_TWO

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE,
         findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ) = self._old
        self.tmp.cleanup()


class TestARowIsStoredPlain(StoreCase):
    def test_a_resident_case(self):
        row = findings_store.add_case({
            "text": CLAIM, "claim": CLAIM, "detail": DETAIL, "fix": FIX,
            "entity_id": "binary_sensor.hall_motion",
            "evidence": [{"entity": "binary_sensor.hall_motion",
                          "value": "off", "when": "03:00"}]})
        self.assertIsNotNone(row)
        stored = findings_store.get(row["ts"])
        for key in ("claim", "detail", "fix", "text"):
            self.assertEqual(leaks(stored[key]), [], (key, stored[key]))
        # The evidence is where an id belongs.
        self.assertEqual(stored["evidence"][0]["entity"],
                         "binary_sensor.hall_motion")
        self.assertEqual(stored["entity_id"], "binary_sensor.hall_motion")

    def test_a_card_finding(self):
        [row] = findings_store.add_many([{
            "text": CLAIM, "detail": DETAIL, "fix": FIX,
            "source": "lighting", "entity_id": "binary_sensor.hall_motion"}])
        for key in ("text", "detail", "fix"):
            self.assertEqual(leaks(row[key]), [], (key, row[key]))

    def test_a_refinement_rewrites_what_it_shows_and_never_text(self):
        check_text = "Hall motion has stopped reporting"
        [row] = findings_store.add_many([{
            "text": check_text, "source": "check:dev.unavailable",
            "entity_id": "binary_sensor.hall_motion",
            "status": "triaging"}])
        out = findings_store.refine(row["ts"], {
            "claim": CLAIM, "detail": DETAIL, "fix": FIX})
        for key in ("claim", "detail", "fix"):
            self.assertEqual(leaks(out[key]), [], (key, out[key]))
        self.assertEqual(out["text"], check_text)

    def test_advice_from_the_chat(self):
        [row] = findings_store.add_many([{
            "text": "Hall motion has stopped reporting",
            "source": "check:dev.unavailable"}])
        out = findings_store.set_fix(row["ts"], FIX, "chat")
        self.assertEqual(leaks(out["fix"]), [])

    def test_a_checks_row_is_left_exactly_as_its_rule_wrote_it(self):
        text = "switch.attic_fan has been off since 04:00 UTC"
        [row] = findings_store.add_many([{
            "text": text, "detail": text, "source": "check:auto.dead_ref"}])
        self.assertEqual(row["text"], text)
        self.assertEqual(row["detail"], text)

    def test_with_no_names_handed_in_nothing_is_invented(self):
        findings_store.DISPLAY_NAMES = None
        findings_store.HOUSE_TZ = None
        [row] = findings_store.add_many([{
            "text": "abcd1234_brain lost switch.attic_fan",
            "source": "lighting"}])
        self.assertEqual(row["text"], "brAIn lost switch.attic_fan")


class TestTheContractSaysSo(unittest.TestCase):
    def test_the_investigation_names_local_time_brain_and_plain_automations(self):
        system = resident.INVESTIGATE_SYSTEM
        self.assertIn("local time", system)
        self.assertIn('never "UTC"', system)
        self.assertIn('Call the add-on "brAIn"', system)
        self.assertIn("what an automation does in plain words", system)


if __name__ == "__main__":
    unittest.main()
