#!/usr/bin/env python3
"""The nightly self-notes: no note off a phone that cannot answer, no copy
of last night's, and none about the assistant in the third person.

One house got a near-identical "fewer messages" self-note three nights
running (#632). Its phone never reports a swipe, so every message to it
ended `ignored` and the reflection was told "ignored 15" each night; the
similarity check let each new copy through because the counts (17, 16, 15)
were words of their own; and one note said "so brAIn should speak only…",
the assistant naming itself.

* `presence.answer_counts` leaves out an `ignored` from a message that had
  no buttons, or from a phone the ledger has never heard an answer or a
  swipe from; `absorb` does not read one as a touch nobody wanted.
* `_similar` compares what a note says — no numbers, no filler words.
* A growth note naming brAIn (or the household's name for it) is refused.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import personality  # noqa: E402
import presence  # noqa: E402

NOW = 1_800_000_000.0
IPHONE = "notify.mobile_app_phone_one"
ANDROID = "notify.mobile_app_phone_two"


def sent(i, service, outcome, *, kind="notify", ts=(1,)):
    return {"id": f"d{i}", "at": NOW - i * 3600, "kind": kind,
            "service": service, "ts": list(ts), "outcome": outcome}


class TestNoSignalIsNotIgnored(unittest.TestCase):
    def test_a_phone_that_never_answers_counts_no_ignored(self):
        folded = [sent(i, IPHONE, "ignored") for i in range(1, 14)]
        self.assertEqual(presence.answer_counts(folded, NOW), {})

    def test_a_phone_that_does_report_still_counts(self):
        folded = [sent(1, ANDROID, "cleared"), sent(2, ANDROID, "ignored"),
                  sent(3, IPHONE, "ignored")]
        self.assertEqual(presence.answer_counts(folded, NOW),
                         {"cleared": 1, "ignored": 1})

    def test_a_message_with_no_buttons_counts_no_ignored(self):
        folded = [sent(1, ANDROID, "answered"),
                  sent(2, ANDROID, "ignored", ts=(1, 2, 3)),   # a digest
                  sent(3, ANDROID, "ignored", kind="brief", ts=()),
                  sent(4, "notify.telegram", "ignored")]
        self.assertEqual(presence.answer_counts(folded, NOW), {"answered": 1})

    def test_absorb_reads_no_reaction_off_a_silent_phone(self):
        state = {"touches": [{"id": "t1", "person": "person.one",
                              "kind": "evening", "delivery": "d1",
                              "at": NOW - 90000}], "people": {}}
        folded = [sent(1, IPHONE, "ignored", kind="presence", ts=())]
        self.assertEqual(presence.absorb(state, folded, NOW), 0)
        self.assertNotIn("reaction", state["touches"][0])


class TestTheSameNoteTwice(unittest.TestCase):
    def test_counts_do_not_make_a_new_note(self):
        a = ("Keep messages rare and short; 17 went ignored this week, so "
             "speak only when tied to something asked about.")
        b = ("Keep messages rare and short; 16 went ignored this week, so "
             "I should speak only when tied to something you asked about.")
        self.assertTrue(presence._similar(a, b))

    def test_different_notes_stay_different(self):
        self.assertFalse(presence._similar(
            "Keep evening touches to one line.",
            "Say the room before the device when greeting somebody home."))


class TestANoteSpeaksAsTheAssistant(unittest.TestCase):
    def test_naming_brain_is_refused(self):
        self.assertTrue(presence.refusal_of(
            "Keep messages rare, so brAIn should speak only when asked.",
            growth=True))
        self.assertEqual(presence.refusal_of(
            "Keep messages rare and speak only when asked.", growth=True), "")
        # Ideas and notes are spoken to people, where the rule is not this.
        self.assertEqual(presence.refusal_of("brAIn noticed the bins."), "")

    def test_naming_the_households_name_is_refused_when_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "personality.json")
            personality.save("Juniper", "Warm.", path=path)
            written = presence.write_growth(
                [{"text": "Juniper should keep evening touches short."},
                 {"text": "Keep morning touches to one line."}], NOW, path=path)
            self.assertEqual(written, 1)
            texts = [g["text"] for g in personality.load(path)["growth"]]
            self.assertEqual(texts, ["Keep morning touches to one line."])


if __name__ == "__main__":
    unittest.main()
