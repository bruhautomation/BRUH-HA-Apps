"""The fifth kind of knowledge, and the refusals that keep it a short list.

A proposal store's failure mode is not losing a row — it is becoming a
second inbox. So most of these cases are about what it declines to do:
offer the same thing twice, offer a thirteenth thing while twelve wait,
end a trial by writing its own result, or push out something you have not
answered to make room.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

NOW = 1_800_000_000.0
DAY = 86400.0


def automation(entity: str = "light.kitchen", at: str = "23:05:00") -> dict:
    return {"triggers": [{"trigger": "time", "at": at}],
            "actions": [{"action": "light.turn_off",
                         "target": {"entity_id": entity}}]}


def offer(**over) -> dict:
    base = {"kind": "automation", "title": "Turn the kitchen lights off at 23:05",
            "why": "You do this by hand on 26 of the last 30 nights",
            "source": "propose.routine", "config": automation()}
    base.update(over)
    return base


class ProposalCase(unittest.TestCase):
    """Each test gets its own /data, so nothing leaks between them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["BRAIN_PROPOSALS_FILE"] = str(root / "proposals.json")
        os.environ["BRAIN_PROPOSALS_SETTLED"] = str(root / "settled.json")
        # Deliberately under a parent that does not exist, so the mirror
        # is skipped exactly as it is on a dev checkout with no /config.
        os.environ["BRAIN_PROPOSALS_SHARED"] = str(
            root / "nope" / "brain" / "proposals_state.json")
        for name in ("proposals", "atomic_write"):
            sys.modules.pop(name, None)
        import proposals
        self.p = proposals
        self.addCleanup(self.tmp.cleanup)


class TestOfferingOne(ProposalCase):

    def test_a_proposal_arrives_proposed_and_nothing_is_enabled(self):
        row = self.p.add(offer())
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(self.p.counts()["open"], 1)

    def test_the_same_automation_is_never_offered_twice(self):
        self.assertIsNotNone(self.p.add(offer()))
        self.assertIsNone(self.p.add(offer()))

    def test_the_key_is_the_CHANGE_not_the_sentence(self):
        """A miner that rewords its own explanation next month is still
        offering the change you already saw."""
        self.assertIsNotNone(self.p.add(offer()))
        self.assertIsNone(self.p.add(offer(
            title="Kitchen lights off late evening",
            why="Reworded, same automation")))

    def test_a_different_automation_is_a_different_proposal(self):
        self.assertIsNotNone(self.p.add(offer()))
        self.assertIsNotNone(self.p.add(offer(
            title="Turn the hall lights off at 23:30",
            config=automation("light.hall", "23:30:00"))))

    def test_a_proposal_with_no_title_is_not_a_proposal(self):
        self.assertIsNone(self.p.add(offer(title="")))

    def test_the_tab_stops_growing_rather_than_dropping_what_you_owe(self):
        """A list that silently discards what you have not answered is
        worse than one that stops offering."""
        for i in range(self.p.MAX_OPEN):
            self.assertIsNotNone(
                self.p.add(offer(title=f"Proposal {i}",
                                 config=automation(f"light.n{i}"))), i)
        self.assertIsNone(self.p.add(offer(title="One too many",
                                           config=automation("light.extra"))))
        self.assertEqual(self.p.counts()["open"], self.p.MAX_OPEN)


class TestAskingBeforeOffering(ProposalCase):
    """`knows` and `add` are one predicate, or a producer gets two answers."""

    def test_it_agrees_with_add_about_a_duplicate(self):
        self.assertFalse(self.p.knows(offer()))
        self.assertIsNotNone(self.p.add(offer()))
        self.assertTrue(self.p.knows(offer()))
        self.assertIsNone(self.p.add(offer()))

    def test_it_agrees_with_add_about_something_declined(self):
        row = self.p.add(offer())
        self.p.decide(row["ts"], "declined", "we like it on")
        self.assertTrue(self.p.knows(offer()))
        self.assertIsNone(self.p.add(offer()))

    def test_it_is_about_the_change_and_not_the_sentence(self):
        self.p.add(offer())
        self.assertTrue(self.p.knows(offer(title="Kitchen off, late")))
        self.assertFalse(
            self.p.knows(offer(config=automation(at="23:30:00"))))


class TestTheTrial(ProposalCase):

    def test_a_trial_runs_a_whole_week(self):
        row = self.p.add(offer())
        started = self.p.start_trial(row["ts"], NOW)
        self.assertEqual(started["status"], "trialling")
        self.assertEqual(started["trial_ends_at"] - started["trial_started_at"],
                         int(self.p.TRIAL_DAYS * DAY))

    def test_a_week_is_the_floor_because_a_household_has_one(self):
        self.assertGreaterEqual(self.p.TRIAL_DAYS, 7)

    def test_a_trial_only_starts_from_proposed(self):
        row = self.p.add(offer())
        self.assertIsNotNone(self.p.start_trial(row["ts"], NOW))
        self.assertIsNone(self.p.start_trial(row["ts"], NOW))

    def test_it_is_not_due_until_the_week_is_up(self):
        row = self.p.start_trial(self.p.add(offer())["ts"], NOW)
        self.assertFalse(self.p.trial_due(row, NOW + 3 * DAY))
        self.assertTrue(self.p.trial_due(row, NOW + 8 * DAY))

    def test_recording_a_result_does_NOT_end_the_trial(self):
        """The report is evidence a person reads. A store that ended the
        trial by writing its own result would be deciding the thing it is
        reporting on."""
        row = self.p.start_trial(self.p.add(offer())["ts"], NOW)
        got = self.p.record_trial(row["ts"], {"would_fire": 6, "agreed": 5})
        self.assertEqual(got["status"], "trialling")
        self.assertEqual(got["trial_result"]["agreed"], 5)
        self.assertEqual(self.p.counts()["open"], 1)

    def test_a_result_cannot_be_recorded_on_something_not_trialling(self):
        row = self.p.add(offer())
        self.assertIsNone(self.p.record_trial(row["ts"], {"would_fire": 1}))


class TestEndingOne(ProposalCase):

    def test_an_ending_removes_the_row_and_remembers_the_key(self):
        row = self.p.add(offer())
        self.assertIsNotNone(self.p.decide(row["ts"], "declined", "", NOW))
        self.assertEqual(self.p.listing(), [])
        self.assertIn(row["key"], self.p.settled_keys())

    def test_a_declined_proposal_is_never_offered_again(self):
        row = self.p.add(offer())
        self.p.decide(row["ts"], "declined", "my partner works nights", NOW)
        self.assertIsNone(self.p.add(offer()))

    def test_the_note_is_optional(self):
        row = self.p.add(offer())
        self.assertIsNotNone(self.p.decide(row["ts"], "declined", "", NOW))

    def test_a_note_is_capped_and_trimmed(self):
        row = self.p.add(offer())
        got = self.p.decide(row["ts"], "declined", "  " + "x" * 900 + "  ", NOW)
        self.assertEqual(len(got["note"]), self.p.NOTE_MAX)

    def test_a_trialling_proposal_can_be_ended_from_the_trial(self):
        row = self.p.start_trial(self.p.add(offer())["ts"], NOW)
        self.assertIsNotNone(self.p.decide(row["ts"], "accepted", "", NOW))

    def test_ending_the_same_one_twice_changes_nothing(self):
        row = self.p.add(offer())
        self.assertIsNotNone(self.p.decide(row["ts"], "accepted", "", NOW))
        self.assertIsNone(self.p.decide(row["ts"], "accepted", "", NOW))

    def test_only_the_two_real_endings_are_accepted(self):
        row = self.p.add(offer())
        for bogus in ("proposed", "trialling", "deleted", ""):
            self.assertIsNone(self.p.decide(row["ts"], bogus, "", NOW))
        self.assertEqual(self.p.counts()["open"], 1)


class TestWhatAnEndingTeaches(ProposalCase):

    def test_a_decline_WITH_a_reason_is_a_fact_about_the_house(self):
        row = dict(offer(), note="my partner works nights")
        line = self.p.memory_line(row, "declined")
        self.assertIn("my partner works nights", line)
        self.assertIn("They said", line)

    def test_a_decline_with_NO_reason_teaches_nothing_and_says_nothing(self):
        """A preference about a suggestion is not a fact about a home,
        and memory has no use for one."""
        self.assertEqual(self.p.memory_line(dict(offer(), note=""),
                                            "declined"), "")

    def test_an_accept_is_always_worth_recording(self):
        line = self.p.memory_line(offer(), "accepted")
        self.assertIn("Accepted", line)
        self.assertIn("kitchen", line.lower())


class TestTheStoreItself(ProposalCase):

    def test_what_is_written_is_what_is_read_back(self):
        self.p.add(offer())
        with open(os.environ["BRAIN_PROPOSALS_FILE"], encoding="utf-8") as fh:
            on_disk = json.load(fh)["proposals"]
        self.assertEqual(self.p.listing(), on_disk)

    def test_a_missing_store_is_an_empty_list_not_a_crash(self):
        os.environ["BRAIN_PROPOSALS_FILE"] = "/nonexistent/proposals.json"
        sys.modules.pop("proposals", None)
        import proposals
        self.assertEqual(proposals.listing(), [])

    def test_the_mirror_is_skipped_where_there_is_no_shared_volume(self):
        """A dev checkout must not grow a stray /config."""
        self.p.add(offer())
        self.assertFalse(self.p.SHARED.exists())
        self.assertFalse(self.p.SHARED.parent.exists())

    def test_the_mirror_carries_the_open_rows_and_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "config" / ".brain" / "proposals_state.json"
            shared.parent.parent.mkdir(parents=True)
            self.p.SHARED = shared      # read at import, so set the constant
            self.p.add(offer())
            payload = json.loads(shared.read_text(encoding="utf-8"))
        self.assertEqual(payload["open"], 1)
        self.assertNotIn("config", payload["proposals"][0])

    def test_counts_span_the_two_statuses_that_wait_on_a_person(self):
        a = self.p.add(offer())
        b = self.p.add(offer(title="Second", config=automation("light.b")))
        self.p.start_trial(b["ts"], NOW)
        got = self.p.counts()
        self.assertEqual(got["proposed"], 1)
        self.assertEqual(got["trialling"], 1)
        self.assertEqual(got["open"], 2)
        self.p.decide(a["ts"], "declined", "", NOW)
        self.assertEqual(self.p.counts()["open"], 1)


if __name__ == "__main__":
    unittest.main()
