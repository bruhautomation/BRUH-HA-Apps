"""A finding still waiting for its first look is a card, so it is a case.

A row still `triaging` past `triage.SHOW_AFTER_S` is drawn on Today with
the full answer row and a Respond line, under the case id `f:<ts>` — and
every press on it went through `cases.get`, which did not know the word
`triaging` and answered "no such case". The CLI's own route
(`/api/finding/<ts>/wrong`) never asked `cases` and so worked, which is
what made the panel look broken beside it.

Driven through the real routes (`h_case_respond`, `h_case_verb`) with only
the model stubbed, and the look's half through the real
`_signal_for_finding` the minute sweep calls.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import triage  # noqa: E402
from test_panel_respond import RespondCase  # noqa: E402

# Every status a card on Today can be drawn for: the case list's own, the
# loose finding card's list in `todayCards`, and a row still waiting for
# its look (`waiting_look`).
FEED_STATUSES = ("open", "needs_you", "failed", "planned", "fixed",
                 "planning", "fixing", "held", "triaging")


class WaitingCase(RespondCase):
    def waiting_row(self) -> dict:
        row = self.check_row()
        findings_store.set_status(row["ts"], "triaging")
        got = findings_store.get(row["ts"])
        self.assertEqual(got["status"], "triaging")
        return got


class TestEveryCardTheFeedDrawsIsACase(WaitingCase):
    def test_every_status_the_feed_can_render_resolves(self):
        for status in FEED_STATUSES:
            with self.subTest(status=status):
                row, created = findings_store.add(
                    f"A report in {status}", severity="warning",
                    source="check:dev.frozen", entity_id=f"sensor.{status}")
                self.assertTrue(created)
                findings_store.set_status(row["ts"], status)
                case = cases.get(f"f:{row['ts']}")
                self.assertIsNotNone(case, status)
                self.assertEqual(case["origin"]["key"], row["ts"])

    def test_a_waiting_row_reads_as_an_open_case(self):
        row = self.waiting_row()
        case = cases.get(f"f:{row['ts']}")
        self.assertEqual(case["status"], "open")

    def test_the_list_still_leaves_a_row_nobody_has_looked_at_out(self):
        # The look decides what a waiting row is; the case LIST must not
        # start judging it by drawing every fresh row as a decision.
        row = self.waiting_row()
        listed = {c["id"] for c in cases.list_cases(None)}
        self.assertNotIn(f"f:{row['ts']}", listed)


class TestEveryPressOnAWaitingRowLands(WaitingCase):
    def test_respond_is_accepted_and_recorded_on_the_row(self):
        row = self.waiting_row()
        self.replies["interpret"] = {"routes": [{"kind": "chat"}]}
        out = self.respond(f"f:{row['ts']}", "it is the one in the garage")
        self.assertEqual(out["status"], 200, out)
        turns = findings_store.get(row["ts"])["thread"]
        self.assertEqual(turns[0]["who"], "you")
        self.assertIn("in the garage", turns[0]["text"])

    def test_snooze_and_ignore_are_accepted(self):
        snoozed = self.waiting_row()
        ignored_entry, created = findings_store.add(
            "Another report", severity="warning", source="check:dev.frozen",
            entity_id="sensor.other")
        self.assertTrue(created)
        findings_store.set_status(ignored_entry["ts"], "triaging")
        self.replies["correct"] = {"scope": "entity_check",
                                   "lifetime": "permanent"}
        statuses = {}

        async def body(client):
            res = await client.post(f"/api/case/f:{snoozed['ts']}/not_now")
            statuses["not_now"] = (res.status, await res.text())
            res = await client.post(f"/api/case/f:{ignored_entry['ts']}/wrong",
                                    json={"note": "not a problem here"})
            statuses["wrong"] = (res.status, await res.text())

        self.drive(body)
        self.assertEqual(statuses["not_now"][0], 200, statuses)
        self.assertEqual(statuses["wrong"][0], 200, statuses)
        self.assertGreater(
            int(findings_store.get(snoozed["ts"]).get("snoozed_until") or 0),
            int(time.time()))
        self.assertIsNone(findings_store.get(ignored_entry["ts"]))

    def test_dismiss_through_the_reply_line_is_accepted(self):
        row = self.waiting_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "dismiss"}]}
        out = self.respond(f"f:{row['ts']}", "dismiss it, it passed")
        self.assertEqual(out["status"], 200, out)


class TestTheLookReadsTheReply(WaitingCase):
    def test_a_reply_rides_into_the_signal_the_look_is_handed(self):
        row = self.waiting_row()
        findings_store.append_thread(row["ts"], "you",
                                     "the door is propped open on purpose")
        row = findings_store.get(row["ts"])
        sig = self.server._signal_for_finding(
            row, time.time(), self.server.signals.EMPTY_CONTEXT)
        lines = self.server.signals.prompt_rows([{**sig, "finding_ts":
                                                  row["ts"]}])
        self.assertIn("propped open on purpose", lines[0])

    def test_a_row_nobody_replied_to_carries_no_reply(self):
        row = self.waiting_row()
        sig = self.server._signal_for_finding(
            row, time.time(), self.server.signals.EMPTY_CONTEXT)
        self.assertFalse([e for e in sig["evidence"]
                          if "replied" in e["entity"]])
        self.assertTrue(triage.SHOW_AFTER_S > 0)


if __name__ == "__main__":
    unittest.main()
