#!/usr/bin/env python3
"""Needs you reads as a queue: what is broken first, worst first, and a
look line only when the look said something about the house.

Two complaints from one real house, both reproduced here before the fix:

  * a serious broken-integration finding sat seventh, below a finished
    print chore and a mute question, with house-book questions, rule
    suggestions and registry tidy-ups mixed in. The feed was sorted by a
    band over stakes and then newest, so anything newer with the same
    stakes went above it. Each case now carries a `group` (problems,
    questions, chores, tidy — `answers.group`) and the feed is ordered by
    group, then urgent, then severity (`answers.feed_key`).
  * five cards carried the identical stock sentence `triage.UNJUDGED` and
    five more said the row "is already in front of the homeowner" — the
    look describing brAIn's own routing rather than the house. A card's
    look reason is now only what it says about the house
    (`findings_store.house_reason`): the silence sentences are blanked and
    the case says `unchecked` instead, so the panel can mark it and count
    it once at the top of the queue.
"""

import sys
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import cases  # noqa: E402
import findings_store  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402

from test_cases import StoresCase  # noqa: E402


# -- the look line --------------------------------------------------------

class TestALookReasonIsAboutTheHouse(unittest.TestCase):

    def test_routing_only_reasons_say_nothing(self):
        for said in (
                "This row is already in front of the homeowner.",
                "Already in front of the homeowner, so nothing to add.",
                "It is already on their list.",
                "Already filed and on the list.",
                "The homeowner has already been told about this.",
                "This is already raised on the list.",
        ):
            self.assertEqual(findings_store.house_reason(said), "", said)

    def test_a_judgement_is_kept(self):
        for said in (
                "The battery will last about a week, so this can wait.",
                "A freezer warming this fast spoils food within a day.",
                "It only matters if the door is also open at night.",
        ):
            self.assertEqual(findings_store.house_reason(said), said)

    def test_the_routing_half_of_a_mixed_reason_goes(self):
        out = findings_store.house_reason(
            "Already in front of the homeowner. The pump has not run "
            "since Tuesday, which matters before the frost.")
        self.assertEqual(out, "The pump has not run since Tuesday, which "
                              "matters before the frost.")
        out = findings_store.house_reason(
            "Already on the list; it can wait until the weekend.")
        self.assertEqual(out, "it can wait until the weekend.")

    def test_the_silence_sentences_are_no_reason(self):
        for said in (triage.UNJUDGED, triage.RUN_FAILED, triage.WAITING):
            self.assertEqual(findings_store.house_reason(said), "")

    def test_empty_is_empty(self):
        self.assertEqual(findings_store.house_reason(""), "")
        self.assertEqual(findings_store.house_reason(None), "")


def finding(**over):
    row = {"ts": 100, "text": "The hall sensor stopped answering",
           "detail": "since 06:40", "status": "open", "severity": "warning",
           "source": "check:dev.unavailable", "triage": {}}
    row.update(over)
    return row


class TestTheCaseCarriesTheHouseReason(unittest.TestCase):

    def test_an_unjudged_row_is_unchecked_and_says_no_sentence(self):
        for stock in (triage.UNJUDGED, triage.RUN_FAILED):
            kase = cases._from_finding(finding(triage={
                "verdict": "untriaged", "reason": stock}), {})
            self.assertEqual(kase["triage"].get("reason"), "", stock)
            self.assertTrue(kase["unchecked"], stock)

    def test_a_judged_row_is_not_unchecked(self):
        kase = cases._from_finding(finding(triage={
            "verdict": "elevated",
            "reason": "It runs the crawl-space fan, so it matters."}), {})
        self.assertFalse(kase["unchecked"])
        self.assertEqual(kase["triage"]["reason"],
                         "It runs the crawl-space fan, so it matters.")

    def test_a_routing_reason_is_blanked_on_the_case(self):
        kase = cases._from_finding(finding(triage={
            "verdict": "elevated",
            "reason": "This is already in front of the homeowner."}), {})
        self.assertEqual(kase["triage"]["reason"], "")
        self.assertFalse(kase["unchecked"])

    def test_an_echo_is_still_blanked(self):
        kase = cases._from_finding(finding(triage={
            "verdict": "elevated",
            "reason": "The hall sensor stopped answering"}), {})
        self.assertEqual(kase["triage"]["reason"], "")


class TestTheFindingsPayloadAgrees(StoresCase):
    """The Findings payload is the other surface that shows a look line,
    and it must say what the case says."""

    def test_listing_blanks_silence_and_routing(self):
        rows = findings_store.add_many([
            {"text": "The hall sensor stopped answering", "severity": "warning",
             "source": "check:dev.unavailable", "status": "triaging"},
            {"text": "The porch sensor stopped answering", "severity": "warning",
             "source": "check:dev.unavailable", "status": "triaging"},
        ])
        a, b = (r["ts"] for r in rows)
        findings_store.record_triage({
            a: ("untriaged", triage.UNJUDGED),
            b: ("elevated", "This is already in front of the homeowner.")})
        shown = {f["ts"]: f for f in findings_store.listing()["findings"]}
        self.assertEqual(shown[a]["triage"]["reason"], "")
        self.assertEqual(shown[b]["triage"]["reason"], "")
        # The record itself is untouched: only what is shown is filtered.
        self.assertEqual(findings_store.get(a)["triage"]["reason"],
                         triage.UNJUDGED)


class TestTheLookIsToldToWriteAboutTheHouse(unittest.TestCase):

    def test_the_first_look_prompt_says_so(self):
        text = resident.FIRST_LOOK_SYSTEM
        self.assertIn("never about where the row is listed", text)


# -- the order ------------------------------------------------------------

def case(**over):
    base = {"id": "f:1", "kind": "problem", "status": "open",
            "finding_status": "open", "origin": {"store": "findings", "key": 1},
            "severity": "warning", "source": "check:dev.frozen",
            "fixable": False, "created_at": 1}
    base.update(over)
    return base


class TestEachCaseHasAGroup(unittest.TestCase):

    def test_the_groups(self):
        self.assertEqual(answers.group(case()), "problems")
        self.assertEqual(answers.group(case(kind="change",
                                            finding_status="fixed")),
                         "problems")
        self.assertEqual(answers.group(case(kind="question",
                                            source="house_book")),
                         "questions")
        self.assertEqual(answers.group(case(kind="question",
                                            source="mute_offer")),
                         "questions")
        self.assertEqual(answers.group(case(
            id="h:5", kind="question",
            origin={"store": "hypotheses", "key": 5})), "questions")
        self.assertEqual(answers.group(case(source="check:chore.job_done",
                                            severity="info")), "chores")
        self.assertEqual(answers.group(case(kind="opportunity")), "chores")
        self.assertEqual(answers.group(case(source="check:reg.no_area",
                                            fixable=True)), "tidy")
        self.assertEqual(answers.group(case(severity="info")), "tidy")
        # Urgent is a problem whatever it was filed as.
        self.assertEqual(answers.group(case(kind="question"), urgent=True),
                         "problems")
        self.assertEqual(set(answers.GROUPS), set(answers.GROUP_WORDS))


class TestTheFeedIsOrderedByGroupThenSeverity(unittest.TestCase):

    def test_a_serious_problem_leads_whatever_is_newer(self):
        feed = [
            case(id="f:chore", source="check:chore.job_done",
                 severity="info", created_at=90),
            case(id="f:mute", kind="question", source="mute_offer",
                 severity="info", created_at=80),
            case(id="h:book", kind="question", source="house_book",
                 created_at=70),
            case(id="f:tidy", source="check:reg.hardware_name",
                 fixable=True, created_at=60),
            case(id="f:warn", severity="warning", created_at=50),
            case(id="f:serious", severity="serious",
                 source="check:sys.entry_failed", created_at=10),
            case(id="f:change", kind="change", finding_status="fixed",
                 severity="critical", created_at=95),
            case(id="f:urgent", severity="critical", urgent=True,
                 created_at=5),
        ]
        ordered = sorted(feed, key=answers.feed_key)
        ids = [c["id"] for c in ordered]
        self.assertEqual(ids[:4], ["f:urgent", "f:serious", "f:warn",
                                   "f:change"])
        self.assertEqual(set(ids[4:6]), {"f:mute", "h:book"})
        self.assertEqual(ids[6:], ["f:chore", "f:tidy"])


class TestThePayloadIsInThatOrder(StoresCase):

    def test_the_feed_payload_leads_with_the_serious_problem(self):
        import server  # noqa: PLC0415 — imported here so the fixture is in place
        # The serious fault was weighed `medium` by the run that looked and
        # the finished print `high`, so the old band order put the print
        # (and anything else newer) above it.
        [serious] = findings_store.add_many([{
            "text": "An integration failed to set up",
            "severity": "serious", "source": "check:sys.entry_failed",
            "source_title": "System check", "stakes": "medium"}])
        findings_store.add_many([{
            "text": "The print on the printer has finished",
            "severity": "warning", "source": "check:chore.job_done",
            "entity_id": "sensor.printer_status", "stakes": "high"}])
        findings_store.add_many([{
            "text": "Two lamps have hardware names",
            "severity": "warning", "source": "check:reg.hardware_name",
            "fixable": True}])
        self.file_question()
        with unittest.mock.patch.dict(server._NAMES, {}, clear=True):
            payload = server._cases_payload()
        ids = [c["id"] for c in payload["cases"]]
        self.assertEqual(ids[0], f"f:{serious['ts']}", ids)
        groups = [c["group"] for c in payload["cases"]]
        self.assertEqual(groups, sorted(groups, key=answers.GROUPS.index),
                         groups)


if __name__ == "__main__":
    unittest.main()
