#!/usr/bin/env python3
"""No finding is stored ending partway through a word.

A real house had details ending "…or the Smart", "…at 10.0.0.1" and one cut
to "…shows only ": a bare character slice wherever a producer capped what a
model or a log line wrote. `textclip.clip` is the one way prose is
shortened — it ends on a sentence or a word and says so with "…" — and
every path below writes through it now. Each test sends an over-long value
through the real producer and reads what would be stored.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import corrections  # noqa: E402
import findings_store  # noqa: E402
import hypotheses  # noqa: E402
import interventions  # noqa: E402
import sre  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)
from test_sre import NOW, collected  # noqa: E402

# Long prose whose words never line up with a round number of characters.
WORDS = ("the porch light dropped off the mesh again around midnight and "
         "the motion sensor beside it stopped reporting until somebody "
         "power cycled the Smart plug feeding the hub ")
LONG = (WORDS * 8).strip()


def assert_ends_cleanly(test, shown: str, said: str):
    """`shown` is all of `said`, or a prefix of it cut at a word boundary
    and marked with "…"."""
    test.assertTrue(shown, "nothing was kept")
    if shown == said:
        return
    test.assertTrue(shown.endswith("…"), f"cut without saying so: {shown[-40:]!r}")
    head = shown[:-1].rstrip()
    test.assertTrue(said.startswith(head), "the kept part is not the text")
    nxt = said[len(head):len(head) + 1]
    test.assertTrue(nxt == "" or not re.match(r"\w", nxt),
                    f"cut mid-word: …{head[-20:]!r}|{said[len(head):len(head) + 10]!r}")


class TestTheStoreClips(StoresCase):
    def test_a_case_claim(self):
        row = findings_store.add_case(
            {"text": "Porch light dropping", "claim": LONG, "kind": "problem",
             "detail": LONG, "fix": LONG,
             "severity": "warning", "stakes": "low"}, run_id="r")
        stored = findings_store.get(row["ts"])
        for field in ("claim", "detail", "fix"):
            with self.subTest(field=field):
                assert_ends_cleanly(self, stored[field], LONG)

    def test_a_filed_row(self):
        [row] = findings_store.add_many([{
            "text": "Porch light keeps dropping", "detail": LONG, "fix": LONG,
            "severity": "warning", "source": "check:dev.unavailable"}])
        stored = findings_store.get(row["ts"])
        assert_ends_cleanly(self, stored["detail"], LONG)
        assert_ends_cleanly(self, stored["fix"], LONG)


class TestTheOvernightCheckClips(unittest.TestCase):
    def test_title_detail_and_fix(self):
        dig = sre.digest(collected(), NOW)
        rid = next(r["id"] for r in dig["records"] if r["kind"] == "zigbee")
        out = sre.parse_causes({"causes": [{
            "title": LONG, "detail": LONG, "fix": LONG,
            "records": [rid]}]}, dig)
        [cause] = out["causes"]
        for field in ("title", "detail", "fix"):
            with self.subTest(field=field):
                assert_ends_cleanly(self, cause[field], LONG)

    def test_a_long_log_message(self):
        message = ("Error talking to the plug at 10.0.0.1 because the "
                   "connection was refused " * 6).strip()
        dig = sre.digest(collected(log=[{
            "name": "homeassistant.components.tplink", "message": [message],
            "level": "ERROR", "source": ["components/tplink/x.py", 1],
            "timestamp": NOW - 60, "count": 3}]), NOW)
        [log] = [r for r in dig["records"] if r["kind"] == "log"]
        assert_ends_cleanly(self, log["message"], message)


class TestTheOtherProducersClip(unittest.TestCase):
    def test_a_wide_correction_offer(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = corrections.OFFERS_FILE
        corrections.OFFERS_FILE = Path(tmp.name) / "offers.json"
        self.addCleanup(setattr, corrections, "OFFERS_FILE", old)
        row = corrections.offer_row(
            {"offer": True, "scope": "check", "check": "dev.unavailable"},
            LONG, entity_name=LONG[:180], check_title="Devices unavailable")
        self.assertLessEqual(len(row["claim"]), 240)
        self.assertTrue(row["claim"].endswith(("?", "…")),
                        f"claim cut mid-word: {row['claim'][-30:]!r}")
        said = row["detail"].split("“", 1)[1].split("”", 1)[0]
        assert_ends_cleanly(self, said, LONG)

    def test_a_maintenance_row(self):
        row = interventions.maintenance_row(
            {"finding_text": LONG, "id": "iv-1"}, days=14, times=2)
        quoted = row["text"].split("“", 1)[1].split("”", 1)[0]
        assert_ends_cleanly(self, quoted, LONG)

    def test_a_guess_written_long_by_another_writer(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(tmp.name) / "h.jsonl"
        self.addCleanup(setattr, hypotheses, "HYPOTHESES_FILE", old)
        hypotheses.HYPOTHESES_FILE.write_text(
            json.dumps({"ts": 1, "text": LONG, "status": "open"}) + "\n")
        [row] = hypotheses.list_all()
        assert_ends_cleanly(self, row["text"], LONG)


if __name__ == "__main__":
    unittest.main()
