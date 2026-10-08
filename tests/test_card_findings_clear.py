#!/usr/bin/env python3
"""A card's own finding leaves when the card's next run no longer reports it.

A house check's row clears itself (`clear_resolved`): the check runs again,
does not find the problem, and the row goes — no memory line, no ledger
entry, because a problem that went away is not a fact about the house. A
row an insight card filed had no such ending. The card ran again, and its
prompt listed the row under "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT
report these again", so the run could not say whether the data still showed
it, and nothing would have read the answer anyway: the row sat open for as
long as nobody pressed anything, long after the data stopped supporting it.

So the card is now shown its own live rows apart, told to report one again
only if what it read still shows it, and a row it was shown and did not
report again is taken off the list the way `clear_resolved` takes one:
no memory line, no ledger entry. Never on a run that failed, never a row a
person has touched (snoozed, put back, planned, in a fix, fixed), and never
a row the run was not shown.

Driven through the real `_generate` with the model's reply stubbed, the
arrangement `test_card_opportunities` uses.
"""

import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_store  # noqa: E402
import journal  # noqa: E402

from test_card_opportunities import CardCase  # noqa: E402

LEAK = {"text": "The utility sink sensor has read wet for three days",
        "severity": "warning", "detail": "wet since Monday",
        "entity_id": "binary_sensor.utility_sink_leak"}


class ClearCase(CardCase):
    def setUp(self):
        super().setUp()
        self._settled = (findings_store.SETTLED_FILE, journal.JOURNAL_FILE)
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        journal.JOURNAL_FILE = str(Path(self.tmp.name) / "journal.jsonl")
        self.prompts = []
        self.fail_next = False
        real = self.engine.run_claude

        def run(prompt, *a, **k):
            self.prompts.append(prompt)
            if self.fail_next:
                return {"ok": False, "text": "", "error": "boom",
                        "meta": {}}
            return real(prompt, *a, **k)

        self.engine.run_claude = run

    def tearDown(self):
        findings_store.SETTLED_FILE, journal.JOURNAL_FILE = self._settled
        super().tearDown()

    def card_rows(self, source="lighting"):
        return [f for f in findings_store.list_all()
                if f.get("source") == source]

    def first_run(self):
        self.reply["findings"] = [dict(LEAK)]
        self.generate()
        rows = self.card_rows()
        self.assertEqual(len(rows), 1)
        return rows[0]


class TestTheNextRunAnswersForItsOwnRows(ClearCase):
    def test_a_row_the_next_run_does_not_report_again_is_cleared(self):
        row = self.first_run()
        self.reply.pop("findings")
        self.generate()
        self.assertIsNone(findings_store.get(row["ts"]))
        # Cleared, not answered: nothing in the settled ledger and so
        # nothing suppressing a later report of the same problem.
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertNotIn(findings_store.normalize(LEAK["text"]),
                         findings_store.suppressing_keys())

    def test_the_run_was_shown_the_row_as_its_own_to_answer_for(self):
        self.first_run()
        self.reply.pop("findings")
        self.generate()
        prompt = self.prompts[-1]
        self.assertIn(LEAK["text"], prompt)
        before, _sep, after = prompt.partition(
            "do NOT report these again")
        # Its own row is not in the list it is told never to repeat.
        self.assertNotIn(LEAK["text"], after.split("\n\n")[0])

    def test_a_row_reported_again_stays(self):
        row = self.first_run()
        self.generate()
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(len(self.card_rows()), 1)

    def test_a_row_reported_again_in_new_words_about_the_same_entity_stays(self):
        row = self.first_run()
        self.reply["findings"] = [{**LEAK, "text": "Utility sink: still wet"}]
        self.generate()
        self.assertIsNotNone(findings_store.get(row["ts"]))

    def test_a_failed_run_clears_nothing(self):
        row = self.first_run()
        self.reply.pop("findings")
        self.fail_next = True
        self.generate()      # the card from the first run is still there
        self.assertIsNotNone(findings_store.get(row["ts"]))

    def test_another_cards_row_is_not_this_cards_to_clear(self):
        row = self.first_run()
        self.reply.pop("findings")
        self.generate("energy")
        self.assertIsNotNone(findings_store.get(row["ts"]))


class TestAPersonsRowIsNotCleared(ClearCase):
    def touched(self, how):
        row = self.first_run()
        how(row)
        self.reply.pop("findings")
        self.generate()
        return findings_store.get(row["ts"])

    def test_snoozed(self):
        kept = self.touched(lambda r: findings_store.snooze(
            r["ts"], time.time() + 3600))
        self.assertIsNotNone(kept)

    def test_in_a_fix(self):
        kept = self.touched(lambda r: findings_store.set_status(
            r["ts"], "fixing"))
        self.assertIsNotNone(kept)

    def test_fixed(self):
        kept = self.touched(lambda r: findings_store.set_status(
            r["ts"], "fixed"))
        self.assertIsNotNone(kept)

    def test_put_back_by_a_person(self):
        def put_back(r):
            items = json.loads(findings_store.FINDINGS_FILE.read_text())
            for e in items if isinstance(items, list) else items["findings"]:
                if e["ts"] == r["ts"]:
                    e["status"] = "open"
                    e["triage"] = {"verdict": "held", "reason": "x",
                                   "elevated_by_person": True}
            findings_store.FINDINGS_FILE.write_text(json.dumps(items))
        self.assertIsNotNone(self.touched(put_back))


if __name__ == "__main__":
    unittest.main()
