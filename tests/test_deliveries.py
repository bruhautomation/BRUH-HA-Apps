#!/usr/bin/env python3
"""The delivery ledger: what was sent, and what happened to it.

`deliveries.py` is folded at read time from two kinds of line — a message,
and something that happened to one — so the outcomes are tested by writing
the lines the real writers write and reading them back. The server half is
driven through the real `_send_notification`, the real bus hook
(`_on_bus_event`) and the real request drain, because "the tag reached the
phone" and "the swipe found its way back to the line" are claims about
those paths, not about the module on its own.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deliveries  # noqa: E402
import eventbus  # noqa: E402
from test_dispatch import NOTIFY_ROW, DispatchCase  # noqa: E402

NOW = 1_760_000_000.0


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deliveries.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, ts=7, at=NOW, **kw):
        did = deliveries.new_id()
        deliveries.record(kw.pop("kind", "notify"), delivery_id=did,
                          service="mobile_app_phone", title="t", body="b",
                          rows=[{"ts": ts, "source": "check:dev.x",
                                 "entity_id": "light.garden",
                                 "severity": kw.pop("severity", "warning")}],
                          when=at, path=self.path, **kw)
        return did

    def fold(self, now=NOW + 60):
        return deliveries.fold(now, self.path)


class TestWhatHappenedToIt(LedgerCase):

    def test_a_button_is_an_answer(self):
        self.send()
        deliveries.note_answer(7, "snooze", via="notification",
                               when=NOW + 30, path=self.path)
        [row] = self.fold()
        self.assertEqual(row["outcome"], "answered")
        self.assertEqual(row["action"], "snooze")
        self.assertEqual(row["after_s"], 30)

    def test_a_swipe_is_a_clear_and_needs_the_tag(self):
        did = self.send()
        self.assertFalse(deliveries.note_cleared({"tag": "someone-else"},
                                                 path=self.path))
        deliveries.note_cleared({"message": "b", "tag": deliveries.tag_for(did)},
                                when=NOW + 12, path=self.path)
        [row] = self.fold()
        self.assertEqual(row["outcome"], "cleared")
        self.assertEqual(row["after_s"], 12)

    def test_a_nested_tag_is_read_too(self):
        did = self.send()
        self.assertEqual(deliveries.tag_of({"data": {"tag": deliveries.tag_for(did)}}),
                         deliveries.tag_for(did))

    def test_answered_then_swiped_is_answered(self):
        did = self.send()
        deliveries.note_answer(7, "fixed", when=NOW + 5, path=self.path)
        deliveries.note_cleared({"tag": deliveries.tag_for(did)},
                                when=NOW + 6, path=self.path)
        [row] = self.fold()
        self.assertEqual(row["outcome"], "answered")

    def test_nothing_for_a_day_is_ignored_and_less_is_pending(self):
        self.send()
        self.assertEqual(self.fold(NOW + 3600)[0]["outcome"], "pending")
        self.assertEqual(self.fold(NOW + 25 * 3600)[0]["outcome"], "ignored")

    def test_an_answer_belongs_to_the_newest_message_before_it(self):
        first = self.send(at=NOW)
        second = self.send(at=NOW + 3600, kind="reminder")
        deliveries.note_answer(7, "fixed", when=NOW + 3700, path=self.path)
        by_id = {r["id"]: r for r in self.fold(NOW + 4000)}
        self.assertEqual(by_id[second]["outcome"], "answered")
        self.assertEqual(by_id[first]["outcome"], "pending")

    def test_a_send_that_failed_is_not_ignored_it_failed(self):
        self.send(ok=False, error="no such service")
        self.assertEqual(self.fold(NOW + 2 * 86400)[0]["outcome"], "failed")

    def test_the_ledger_is_capped(self):
        old = (deliveries.MAX_LINES, deliveries.PRUNE_SLACK)
        deliveries.MAX_LINES, deliveries.PRUNE_SLACK = 5, 2
        try:
            for i in range(12):
                self.send(ts=i, at=NOW + i)
        finally:
            deliveries.MAX_LINES, deliveries.PRUNE_SLACK = old
        lines = self.path.read_text().splitlines()
        self.assertLessEqual(len(lines), 7)
        self.assertEqual(json.loads(lines[-1])["ts"], [11])

    def test_i_could_not_look_is_not_nothing_sent(self):
        self.path.mkdir()          # a directory where the file should be
        self.assertIsNone(deliveries.fold(NOW, self.path))
        summary = deliveries.summary(NOW, self.path)
        self.assertFalse(summary["available"])

    def test_no_parent_directory_writes_nothing(self):
        missing = Path(self.tmp.name) / "nope" / "deliveries.jsonl"
        deliveries.record("notify", delivery_id="x", service="s", title="t",
                          body="b", path=missing)
        self.assertFalse(missing.exists())

    def test_the_summary_says_what_is_knowable(self):
        self.send()
        did = self.send(ts=8)
        deliveries.note_cleared({"tag": deliveries.tag_for(did)},
                                when=NOW + 2, path=self.path)
        s = deliveries.summary(NOW + 60, self.path)
        self.assertTrue(s["available"])
        self.assertEqual(s["week"], 2)
        self.assertEqual(s["clears_ever"], 1)
        self.assertEqual(s["week_by_outcome"], {"pending": 1, "cleared": 1})
        self.assertIn("not reported", s["opened"])


class TestTheBusSubscribesToTheSwipe(unittest.TestCase):

    def test_a_clear_reaches_the_raw_hook_and_is_never_a_signal(self):
        self.assertIn("mobile_app_notification_cleared", eventbus.EVENT_TYPES)
        seen, signals = [], []
        bus = eventbus.EventBus(signals.append,
                                on_event=lambda t, d: seen.append((t, d)))
        bus._handle({"event_type": "mobile_app_notification_cleared",
                     "data": {"tag": "brain-d-abc", "message": "x"}})
        self.assertEqual(seen, [("mobile_app_notification_cleared",
                                 {"tag": "brain-d-abc", "message": "x"})])
        self.assertEqual(signals, [])


class TestTheServerWritesAndReadsIt(DispatchCase):

    def setUp(self):
        super().setUp()
        import engine
        engine.get_auth = lambda: None     # the deterministic path

    def test_every_send_is_a_line_carrying_the_tag_it_sent(self):
        [row] = self.file(NOTIFY_ROW)
        self.announce([row])
        [msg] = self.sent
        [line] = self.deliveries.fold()
        self.assertEqual(msg["data"]["tag"], deliveries.tag_for(line["id"]))
        self.assertEqual(line["ts"], [row["ts"]])
        self.assertEqual(line["kind"], "notify")
        self.assertEqual(line["entities"], ["sensor.garage_freezer"])

    def test_a_notifier_that_is_not_the_app_carries_no_tag(self):
        self.server._findings_notify_target = lambda: ("telegram", "warning")
        [row] = self.file(NOTIFY_ROW)
        self.announce([row])
        self.assertIsNone(self.sent[0]["data"])
        [line] = self.deliveries.fold()
        self.assertEqual(line["service"], "telegram")

    def test_a_swipe_on_the_phone_finds_its_line(self):
        [row] = self.file(NOTIFY_ROW)
        self.announce([row])
        tag = self.sent[0]["data"]["tag"]
        self.server._on_bus_event("mobile_app_notification_cleared",
                                  {"message": self.sent[0]["body"], "tag": tag})
        [line] = self.deliveries.fold()
        self.assertEqual(line["outcome"], "cleared")

    def test_the_safety_lane_is_still_the_first_thing_the_hook_does(self):
        calls = []
        srv = self.server
        old = srv._note_safety
        srv._note_safety = lambda t, d: calls.append(t)
        try:
            srv._on_bus_event("mobile_app_notification_cleared", {"tag": "x"})
            srv._on_bus_event("state_changed", {"entity_id": "light.x"})
        finally:
            srv._note_safety = old
        self.assertEqual(calls, ["mobile_app_notification_cleared",
                                 "state_changed"])

    def test_an_answer_from_a_notification_button_is_recorded(self):
        import finding_requests
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = Path(self.tmp.name) / "requests"
        finding_requests.REQUEST_DIR.mkdir()
        self.addCleanup(setattr, finding_requests, "REQUEST_DIR", old)
        [row] = self.file(NOTIFY_ROW)
        self.announce([row])
        for i, (via, action) in enumerate((("notification", "snooze"),
                                           ("todo", "fixed"))):
            (finding_requests.REQUEST_DIR / f"{int(time.time() * 1000)}-{i}.json"
             ).write_text(json.dumps({"ts": row["ts"], "action": action,
                                      "via": via}))
        asyncio.run(self.server._apply_finding_requests())
        [line] = self.deliveries.fold()
        self.assertEqual(line["outcome"], "answered")
        # The notification's own button, not the To-do tick behind it.
        self.assertEqual(line["action"], "snooze")

    def test_every_answer_a_notification_can_carry_is_recorded(self):
        """Each button the router puts on a message (and the integration
        still accepts `ack`) comes back through the request drop as a
        finding request, and each one is that message's answer. A guess's
        answer and a To-do tick ride the same queue as their own kinds and
        are answers to no message, so they match nothing and raise nothing.
        """
        import finding_requests
        import notify_router
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = Path(self.tmp.name) / "requests"
        finding_requests.REQUEST_DIR.mkdir()
        self.addCleanup(setattr, finding_requests, "REQUEST_DIR", old)
        verbs = [v for v, _label in notify_router.ACTION_LABELS] + ["ack"]
        self.assertTrue(set(verbs) <= set(finding_requests.ACTIONS))
        now = time.time()
        for i, verb in enumerate(verbs):
            self.deliveries.record(
                "notify", delivery_id=f"d{i}", service="mobile_app_phone",
                title="t", body="b", rows=[{"ts": 1000 + i}], when=now - 60)
        drops = [{"ts": 1000 + i, "action": verb, "via": "notification"}
                 for i, verb in enumerate(verbs)]
        # A Dismiss with no hours (the feed's own snooze length) is still
        # a snooze as far as the message is concerned.
        drops[verbs.index("snooze")]["hours"] = None
        drops += [{"kind": "hypothesis", "ts": 1000, "action": "reject",
                   "via": "notification"},
                  {"kind": "todo", "action": "done", "id": 7,
                   "via": "notification"}]
        for i, body in enumerate(drops):
            (finding_requests.REQUEST_DIR / f"{int(now * 1000)}-{i:02d}.json"
             ).write_text(json.dumps(body))
        requests = finding_requests.collect()
        self.assertEqual(len(requests), len(drops))
        noted = self.server._deliveries_note_requests(requests)
        self.assertEqual(noted, len(verbs))
        folded = {line["id"]: line for line in self.deliveries.fold()}
        for i, verb in enumerate(verbs):
            self.assertEqual(folded[f"d{i}"]["outcome"], "answered", verb)
            self.assertEqual(folded[f"d{i}"]["action"], verb)

    def test_an_accepted_change_is_a_line(self):
        asyncio.run(self.server._announce_accepted(
            {"title": "Porch light at sunset"},
            {"entity_id": "automation.porch_light"}))
        [msg] = self.sent
        [line] = self.deliveries.fold()
        self.assertEqual(line["kind"], "accepted")
        self.assertEqual(line["title"], msg["title"])
        self.assertTrue(line["ok"])

    def test_a_failed_accepted_change_is_a_failed_line(self):
        import ha_data

        async def boom(*a, **k):
            raise RuntimeError("no such service")

        ha_data.send_notification = boom
        asyncio.run(self.server._announce_accepted(
            {"title": "Porch light at sunset"}, {}))
        [line] = self.deliveries.fold()
        self.assertEqual((line["kind"], line["outcome"]),
                         ("accepted", "failed"))

    def test_the_safety_lanes_notice_is_a_line(self):
        import ha_data
        calls = []

        async def core(domain, service, data=None, timeout=10):
            calls.append((domain, service))

        old = ha_data.call_core_service
        ha_data.call_core_service = core
        self.addCleanup(setattr, ha_data, "call_core_service", old)
        filed = {"ts": 4242, "text": "Kitchen leak sensor is wet",
                 "severity": "critical", "source": "safety",
                 "entity_id": "binary_sensor.kitchen_leak"}
        asyncio.run(self.server._safety_fallback_notice(filed))
        self.assertEqual(calls, [("persistent_notification", "create")])
        [line] = self.deliveries.fold()
        self.assertEqual(line["kind"], "notice")
        self.assertEqual(line["service"], "persistent_notification")
        self.assertEqual(line["ts"], [4242])
        # Never a learned suggestion's evidence: a safety source, a kind
        # nothing counts.
        import notify_learn
        self.assertEqual(notify_learn.tally([line], time.time()), [])

    def test_it_is_in_the_diagnostics(self):
        [row] = self.file(NOTIFY_ROW)
        self.announce([row])
        diag = self.server._notify_diagnostics()
        self.assertTrue(diag["deliveries"]["available"])
        self.assertEqual(diag["deliveries"]["week"], 1)
        self.assertIn("dispatch", diag)
        self.assertIn("suggestions", diag)
        json.dumps(diag)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    unittest.main()
