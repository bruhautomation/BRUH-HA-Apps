#!/usr/bin/env python3
"""A card never shows a field cut mid-clause (#560).

A house's cards ended "…followed by malformed-event errors.…", "…re-interview
it from its device page.…", a list that stopped after three of nine devices
"last 29 Oct;…", and a look's conclusion "will be settled by your…". Each was
a cap on a finding's detail, what-to-do or look reason that kept as many
characters as fitted. `textclip.shorten` is the cut for those fields: the
last WHOLE sentence that fits, or whole list items and how many more ("and 6
more."), and only one sentence longer than the whole budget is cut on a word
with "…". The tests send long text through the real producers, with examples
the report never named (a pantry freezer, a row of window sensors).
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import morph_bridge  # noqa: E402
import resident  # noqa: E402
import textclip  # noqa: E402
import triage  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

SENTENCES = " ".join(
    f"The pantry freezer warmed by {n} degrees after its door was left ajar "
    f"for part of the evening, and it took a while to recover."
    for n in range(2, 20))
SENSORS = ("Eleven window sensors stopped reporting: " + "; ".join(
    f"the {w} window sensor last heard 2{i} Sep" for i, w in enumerate(
        ("study", "landing", "attic", "porch", "pantry", "nursery", "den",
         "loft", "garage", "cellar", "sunroom"))) + ".")


def cut_mid_clause(shown: str, said: str) -> bool:
    """Whether ``shown`` (a shortened ``said``) stops inside a clause while
    ``said`` had a sentence end it could have stopped at instead."""
    if shown == said or not shown.endswith("…"):
        return False
    head = shown[:-1]
    return bool(re.search(r"[.!?]\s", said[:len(head) + 1]))


class TestShorten(unittest.TestCase):
    def test_text_that_fits_is_unchanged(self):
        for text in ("Battery at 4%.", "The hall light is on; the fan is off.",
                     "Firmware 1.2 is fine.", "It ran at 0:30, as usual"):
            with self.subTest(text):
                self.assertEqual(textclip.shorten(text, 200), text)

    def test_a_long_account_ends_on_a_whole_sentence_unmarked(self):
        out = textclip.shorten(SENTENCES, 600)
        self.assertLessEqual(len(out), 600)
        self.assertTrue(out.endswith("recover."), out[-40:])
        self.assertTrue(SENTENCES.startswith(out))

    def test_a_list_keeps_whole_items_and_counts_the_rest(self):
        out = textclip.shorten(SENSORS, 200)
        self.assertLessEqual(len(out), 200)
        m = re.search(r"; and (\d+) more\.$", out)
        self.assertIsNotNone(m, out)
        kept = out[:m.start()].split(": ", 1)[1].split("; ")
        self.assertEqual(len(kept) + int(m.group(1)), 11, out)
        for item in kept:
            self.assertIn(item, SENSORS)

    def test_a_comma_list_after_a_colon(self):
        text = ("Left on overnight: the study lamp, the attic fan, the porch "
                "heater, the den radio, the loft kettle, the cellar pump.")
        out = textclip.shorten(text, 60)
        self.assertRegex(out, r", and \d more\.$")
        self.assertLessEqual(len(out), 60)

    def test_an_ellipsis_after_a_full_stop_is_taken_off(self):
        self.assertEqual(
            textclip.shorten("The kettle plug answered again.…", 200),
            "The kettle plug answered again.")
        self.assertEqual(
            textclip.shorten("It is back. Pair it from its page.…", 20),
            "It is back.")

    def test_one_sentence_longer_than_the_budget_still_ends_on_a_word(self):
        text = "word " * 100
        out = textclip.shorten(text, 50)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 50)

    def test_everyday_sentences_with_semicolons_are_not_lists(self):
        text = ("The heater ran long; the room stayed cold. " * 30).strip()
        out = textclip.shorten(text, 120)
        self.assertNotIn("more.", out)
        self.assertTrue(out.endswith("cold."), out)


class TestTheStoresCutWhole(StoresCase):
    def test_a_filed_row_detail_and_fix(self):
        [row] = findings_store.add_many([{
            "text": "Pantry freezer warmed", "detail": SENTENCES,
            "fix": SENTENCES, "severity": "warning",
            "source": "check:climate.freezer"}])
        stored = findings_store.get(row["ts"])
        for field in ("detail", "fix"):
            with self.subTest(field=field):
                self.assertTrue(stored[field].endswith("recover."),
                                stored[field][-40:])
                self.assertFalse(cut_mid_clause(stored[field], SENTENCES))

    def test_a_check_list_counts_what_it_left_out(self):
        long_list = SENSORS + " " + SENSORS + " " + SENSORS
        [row] = findings_store.add_many([{
            "text": "Window sensors quiet", "detail": long_list,
            "severity": "warning", "source": "check:dev.unavailable"}])
        stored = findings_store.get(row["ts"])
        self.assertFalse(stored["detail"].endswith("…"), stored["detail"][-60:])

    def test_a_case_claim_detail_and_fix(self):
        row = findings_store.add_case(
            {"text": "Pantry freezer warming", "claim": SENTENCES,
             "kind": "problem", "detail": SENTENCES, "fix": SENTENCES,
             "severity": "warning", "stakes": "low"}, run_id="r")
        stored = findings_store.get(row["ts"])
        for field in ("claim", "detail", "fix"):
            with self.subTest(field=field):
                self.assertFalse(stored[field].endswith("…"), stored[field][-40:])

    def test_a_looks_conclusion(self):
        [row] = findings_store.add_many([{
            "text": "Pantry freezer warmed again", "detail": "It warmed.",
            "severity": "warning", "source": "check:climate.freezer"}])
        findings_store.hold_after_look(row["ts"], SENTENCES, run_id="r")
        reason = findings_store.get(row["ts"])["triage"]["reason"]
        self.assertLessEqual(len(reason), triage.MAX_REASON)
        self.assertFalse(cut_mid_clause(reason, SENTENCES), reason[-40:])
        self.assertTrue(reason.endswith("."), reason[-40:])

    def test_a_row_stored_by_an_older_cut_reads_whole(self):
        [row] = findings_store.add_many([{
            "text": "Kettle plug dropped", "detail": "x",
            "severity": "warning", "source": "check:dev.unavailable"}])
        items = findings_store._load()
        for item in items:
            if item["ts"] == row["ts"]:
                item["detail"] = "It dropped off twice, then answered.…"
        findings_store._write(items)
        self.assertEqual(findings_store.get(row["ts"])["detail"],
                         "It dropped off twice, then answered.")


class TestTheOtherSurfacesCutWhole(unittest.TestCase):
    def test_an_investigations_reason_for_holding_back(self):
        why = resident.parse_dismissal({"dismiss": True, "claim": "",
                                        "detail": SENTENCES})
        self.assertLessEqual(len(why), resident.MAX_WHY)
        self.assertFalse(cut_mid_clause(why, SENTENCES), why[-40:])

    def test_morphs_ask_line(self):
        case = {"kind": "problem", "fixable": True, "fix": SENTENCES}
        line = morph_bridge.ask_line(case, "open")
        self.assertLessEqual(len(line), 300)
        self.assertTrue(line.endswith("."), line[-40:])
        line = morph_bridge.ask_line({"kind": "problem", "fix": SENTENCES}, "open")
        self.assertTrue(line.endswith("recover."), line[-40:])


class TestAClampedFieldOpensWhole(unittest.TestCase):
    def test_the_panel_releases_its_clamps_when_details_open(self):
        css = (BASE_DIR / "brain" / "panel" / "style.css").read_text()
        for field in (".card-body", ".qfixtext"):
            with self.subTest(field=field):
                self.assertRegex(
                    css, r"\.qcard:has\(> details\.qdetails\[open\]\)[^{]*"
                    + re.escape(field) + r"[^{]*\{[^}]*line-clamp:\s*unset")

    def test_morph_does_not_clamp_a_cases_account(self):
        css = (BASE_DIR / "brain" / "custom_components" / "brain" / "morph"
               / "frontend" / "styles.js").read_text()
        rule = re.search(r"\.case \.casebody\{[^}]*\}", css).group(0)
        self.assertNotIn("line-clamp", rule)


if __name__ == "__main__":
    unittest.main()
