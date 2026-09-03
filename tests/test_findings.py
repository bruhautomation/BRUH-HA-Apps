#!/usr/bin/env python3
"""Tests for Findings — the work list and the one path that changes the house.

Three things worth pinning here, because getting any of them wrong is
expensive in a way a screenshot wouldn't show:

  * a problem is reported ONCE, across every status. Re-raising something the
    homeowner dismissed is exactly what the dismiss button buys off, so the
    dedup has to survive settling, not just be a within-run guard.
  * "Fix it" is the only tool-enabled Claude invocation in the panel, and it
    edits a real home. It must be reachable only by pressing the button, it
    must share the generation queue (one Claude at a time), and a run that
    dies has to leave the finding in a state you can see rather than stuck
    on "fixing" forever.
  * a fix reply that can't be parsed still means the house was touched, so it
    reports as a failure carrying the tail rather than raising.
"""

import datetime as dt
import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import card_tags  # noqa: E402
import engine  # noqa: E402
import feedback_store  # noqa: E402
import findings_store  # noqa: E402
import fixer  # noqa: E402
import hypotheses  # noqa: E402
import knowledge_store  # noqa: E402
import onboarding  # noqa: E402
import prompt_store  # noqa: E402
import settings_store  # noqa: E402
import undo_store  # noqa: E402
import user_categories  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        # The mirror publishes only when its shared volume exists; pointing
        # it under tmp WITHOUT creating "config" keeps the ordinary store
        # tests from writing one, exactly like a dev checkout.
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "config" / ".brain" / "findings_state.json")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()


class TestFindingsStore(StoreCase):
    def test_add_and_shape(self):
        entry, created = findings_store.add(
            "Back Door battery is dead",
            detail="0% since Jul 12", fix="Replace the CR2032",
            severity="serious", fixable=False,
            entity_id="sensor.back_door_battery", source="health",
            source_title="Device Health")
        self.assertTrue(created)
        self.assertEqual(entry["status"], "open")
        self.assertEqual(entry["severity"], "serious")
        self.assertFalse(entry["fixable"])
        self.assertEqual(entry["entity_id"], "sensor.back_door_battery")
        self.assertEqual(findings_store.open_count(), 1)

    def test_a_bogus_severity_falls_back_rather_than_raising(self):
        entry, _ = findings_store.add("X", severity="catastrophic")
        self.assertEqual(entry["severity"], "warning")

    def test_blank_text_is_not_a_finding(self):
        entry, created = findings_store.add("   ")
        self.assertIsNone(entry)
        self.assertFalse(created)

    def test_dedup_survives_settling(self):
        """The point of Dismiss is that it sticks. A finding that comes back
        after being ignored — in the same words or a rewording — makes the
        button worthless."""
        findings_store.add("Back Door battery is dead")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "ignored")

        for wording in ("Back Door battery is dead",
                        "back door battery is dead!",
                        "  Back  Door   battery is dead  "):
            entry, created = findings_store.add(wording)
            self.assertFalse(created, f"{wording!r} came back as a new finding")
            self.assertEqual(entry["status"], "ignored")
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_ids_are_unique_within_one_second(self):
        """ts doubles as the id the panel acts on, and one insight run can
        report three findings inside the same second."""
        for text in ("A problem", "B problem", "C problem"):
            findings_store.add(text)
        ids = [f["ts"] for f in findings_store.list_all()]
        self.assertEqual(len(set(ids)), 3)

    def test_lifecycle_and_live_filter(self):
        """A finished fix is still live: brAIn changed something in the house
        and nobody has read what it did yet. It leaves the list when a person
        presses Got it, not when the run ends."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]
        self.assertEqual(len(findings_store.list_all("live")), 1)
        findings_store.set_status(ts, "fixing")
        self.assertEqual(len(findings_store.list_all("live")), 1)
        entry = findings_store.set_status(ts, "fixed", result="Reloaded it",
                                          changed=["automation.x — trigger fixed"])
        self.assertEqual(entry["result"], "Reloaded it")
        self.assertEqual(entry["changed"], ["automation.x — trigger fixed"])
        self.assertTrue(entry["settled_at"])
        self.assertEqual(len(findings_store.list_all("live")), 1)
        self.assertEqual(findings_store.open_count(), 1)

        findings_store.settle_and_clear(ts, "fixed")
        self.assertEqual(findings_store.list_all(), [])
        self.assertEqual(findings_store.open_count(), 0)

    def test_a_failed_fix_still_needs_you(self):
        """failed and needs_you both stay on the badge — a fix that didn't
        work is not a problem that went away."""
        findings_store.add("A")
        findings_store.add("B")
        a, b = findings_store.list_all()[1], findings_store.list_all()[0]
        findings_store.set_status(a["ts"], "failed")
        findings_store.set_status(b["ts"], "needs_you")
        self.assertEqual(findings_store.open_count(), 2)

    def test_unknown_status_is_a_programming_error(self):
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        with self.assertRaises(ValueError):
            findings_store.set_status(ts, "sorted")

    def test_set_status_on_a_ghost_returns_none(self):
        self.assertIsNone(findings_store.set_status(999, "fixed"))

    def test_remove_lets_it_be_reported_again(self):
        """Unlike ignoring, forgetting is not a judgement — the finding can
        legitimately come back."""
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        self.assertTrue(findings_store.remove(ts))
        self.assertFalse(findings_store.is_known("A"))
        _, created = findings_store.add("A")
        self.assertTrue(created)

    def test_pruning_drops_settled_before_open(self):
        """An open finding is live work. Dropping it silently to make room is
        how a real problem disappears without ever being fixed."""
        for i in range(findings_store.MAX_FINDINGS):
            findings_store.add(f"Old settled problem {i}")
        for f in findings_store.list_all():
            findings_store.set_status(f["ts"], "fixed")
        findings_store.add("A brand new open problem")
        texts = [f["text"] for f in findings_store.list_all()]
        self.assertIn("A brand new open problem", texts)
        self.assertLessEqual(len(texts), findings_store.MAX_FINDINGS)

    def test_prompt_block_names_both_lists(self):
        findings_store.add("Still open")
        findings_store.add("Waved off")
        waved = next(f for f in findings_store.list_all() if f["text"] == "Waved off")
        findings_store.set_status(waved["ts"], "ignored")
        block = findings_store.prompt_block()
        self.assertIn("ALREADY ON THE FINDINGS LIST", block)
        self.assertIn("Still open", block)
        self.assertIn("SAID WERE WRONG", block)
        self.assertIn("Waved off", block)

    def test_prompt_block_is_empty_when_nothing_is_known(self):
        self.assertEqual(findings_store.prompt_block(), "")

    def test_a_fix_orphaned_by_a_restart_is_recoverable(self):
        """"fixing" is claimed on disk but owned by an in-memory job. A
        restart mid-fix orphans it: the row still says fixing, the job that
        would settle it is gone, and the tab offers no buttons in that
        status — so the finding becomes permanently unreachable."""
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixing")

        self.assertEqual(findings_store.reconcile_running("brAIn restarted"), 1)
        entry = findings_store.get(ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("restarted", entry["result"])
        # back on the badge, and Try again is offered
        self.assertEqual(findings_store.open_count(), 1)
        # nothing else is touched, and a second pass is a no-op
        self.assertEqual(findings_store.reconcile_running("again"), 0)

    def test_a_running_fix_is_not_counted_as_a_decision(self):
        """The badge is "things waiting on you". A fix already in flight is
        waiting on Claude, not on the homeowner."""
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixing")
        self.assertEqual(findings_store.open_count(), 0)
        self.assertEqual(len(findings_store.list_all("live")), 1)

    def test_add_many_writes_once_and_dedupes_within_the_batch(self):
        """A study session filing five findings must not rewrite the store
        five times — that is five SD-card erase cycles for one batch."""
        writes = []
        real_write = findings_store._write
        findings_store._write = lambda items: (writes.append(len(items)),
                                               real_write(items))[1]
        try:
            created = findings_store.add_many([
                {"text": "One"}, {"text": "Two"},
                {"text": "one"},        # same as the first, normalized
                {"text": "   "},        # nothing there
                "not a dict",
            ])
        finally:
            findings_store._write = real_write
        self.assertEqual([f["text"] for f in created], ["One", "Two"])
        self.assertEqual(len(writes), 1, "add_many rewrote the store per item")

    def test_coerce_is_the_one_reader_of_the_wire_shape(self):
        """Both producers — a model reply and an inbox line — hand over the
        same loose shape, so both go through one coercion."""
        entry = findings_store.coerce({"finding": "  Stuck sensor  ",
                                       "severity": "SERIOUS", "fixable": False})
        self.assertEqual(entry["text"], "Stuck sensor")
        self.assertEqual(entry["severity"], "serious")
        self.assertFalse(entry["fixable"])
        # absent means fixable; only an explicit false means hands required
        self.assertTrue(findings_store.coerce({"text": "x"})["fixable"])
        self.assertIsNone(findings_store.coerce({"text": "  "}))
        self.assertIsNone(findings_store.coerce("nope"))


class TestFindingsInbox(StoreCase):
    """Study sessions run on the CLI side and must be able to file what they
    found without the panel being up — same hand-off as the memory inbox."""

    def _write(self, name, *objs):
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / name).write_text(
            "".join(json.dumps(o) + "\n" for o in objs), encoding="utf-8")

    def test_sweep_folds_in_and_consumes(self):
        self._write("1-study-devices.jsonl",
                    {"text": "Hall motion offline nightly", "severity": "warning",
                     "fix": "Re-pair it", "fixable": False,
                     "source": "study:devices", "source_title": "Study: devices"})
        swept = findings_store.sweep_inbox()
        # The sweep returns the new rows themselves (the notify hook needs
        # the entries, not a count), already shaped for the API.
        self.assertEqual([f["text"] for f in swept],
                         ["Hall motion offline nightly"])
        entry = findings_store.list_all()[0]
        self.assertEqual(entry["text"], "Hall motion offline nightly")
        self.assertEqual(entry["source"], "study:devices")
        self.assertFalse(entry["fixable"])
        # consumed, so a second sweep is a no-op rather than a duplicate
        self.assertEqual(findings_store.sweep_inbox(), [])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_a_torn_line_does_not_wedge_the_tab(self):
        """A study session killed mid-write leaves half a line behind. That
        must cost its own line and nothing else."""
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / "1.jsonl").write_text(
            json.dumps({"text": "Good one"}) + "\n{\"text\": \"tor",
            encoding="utf-8")
        self.assertEqual(len(findings_store.sweep_inbox()), 1)
        self.assertEqual([f["text"] for f in findings_store.list_all()], ["Good one"])

    def test_missing_inbox_is_fine(self):
        self.assertEqual(findings_store.sweep_inbox(), [])


class TestFindingsStateMirror(StoreCase):
    """The shared-volume mirror is how Home Assistant SEES findings.

    The store lives in /data, which HA cannot read, and this mirror is what
    the integration's sensor and event watcher run on — so it has to be
    republished by every write, not by the writes somebody remembered."""

    def setUp(self):
        super().setUp()
        # The shared volume exists in these tests (it is /config in
        # production); the publish guard checks for its presence.
        findings_store.STATE_FILE.parent.parent.mkdir(parents=True)

    def _state(self):
        return json.loads(findings_store.STATE_FILE.read_text(encoding="utf-8"))

    def test_every_write_republishes(self):
        findings_store.add("Hall battery dead", severity="critical")
        state = self._state()
        self.assertEqual(state["open"], 1)
        self.assertEqual(state["by_severity"]["critical"], 1)
        self.assertEqual(state["findings"][0]["text"], "Hall battery dead")

        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "fixed")
        state = self._state()
        self.assertEqual(state["open"], 0)
        self.assertEqual(state["findings"], [])

    def test_snoozed_findings_leave_the_open_count(self):
        findings_store.add("Porch light flaky")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) + 3600)
        state = self._state()
        self.assertEqual(state["open"], 0)
        # ...and the row itself waits off the mirror too: it is not asking.
        self.assertEqual(state["findings"], [])

    def test_no_shared_volume_means_no_mirror_and_no_error(self):
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "nowhere" / ".brain" / "state.json")
        findings_store.add("A problem")   # must not raise
        self.assertFalse(findings_store.STATE_FILE.exists())
        # ...and the finding itself is safe regardless of the mirror.
        self.assertEqual(findings_store.open_count(), 1)

    def test_publish_state_republishes_on_demand(self):
        findings_store.add("A problem")
        findings_store.STATE_FILE.unlink()
        findings_store.publish_state()
        self.assertEqual(self._state()["open"], 1)


class NotifyCase(StoreCase):
    """A findings store plus a notify service that records instead of sending.

    Shared rather than inherited from one test class by another: a subclass
    of a TestCase re-runs every one of its parent's cases under the
    subclass's own setUp, so `TestQuietHoursRouting` inheriting the notify
    cases would have re-run them inside quiet hours and failed them.
    """

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self.ha_data = importlib.import_module("ha_data")
        self.sent = []
        self._old_send = self.ha_data.send_notification

        async def record(service, title, message, timeout=15):
            self.sent.append((service, title, message))

        self.ha_data.send_notification = record
        os.environ.pop("BRAIN_FINDINGS_NOTIFY", None)
        os.environ.pop("BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY", None)

    def tearDown(self):
        self.ha_data.send_notification = self._old_send
        os.environ.pop("BRAIN_FINDINGS_NOTIFY", None)
        os.environ.pop("BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY", None)
        super().tearDown()

    def _announce(self, created):
        asyncio.run(self.server._announce_findings(created))


class TestFindingsNotify(NotifyCase):
    """New findings can reach a phone, gated on severity.

    The gate lives server-side in _announce_findings: only CREATED rows are
    ever handed to it (add_many dedupes across every status and the settled
    ledger), the notify target comes from the add-on option with an env
    fallback, and a failed delivery is a log line — the finding is already
    safe on the list by the time this runs."""

    def test_no_target_means_no_notification(self):
        created = findings_store.add_many([{"text": "X", "severity": "critical"}])
        self._announce(created)
        self.assertEqual(self.sent, [])

    def test_severity_floor_holds(self):
        os.environ["BRAIN_FINDINGS_NOTIFY"] = "mobile_app_phone"
        created = findings_store.add_many([
            {"text": "Nitpick", "severity": "info"},
            {"text": "Battery dying", "severity": "serious"},
        ])
        self._announce(created)
        self.assertEqual(len(self.sent), 1)
        service, title, message = self.sent[0]
        self.assertEqual(service, "mobile_app_phone")
        self.assertIn("Battery dying", message)
        self.assertNotIn("Nitpick", message)

    def test_floor_is_configurable_and_bogus_values_fall_back(self):
        os.environ["BRAIN_FINDINGS_NOTIFY"] = "mobile_app_phone"
        os.environ["BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY"] = "info"
        created = findings_store.add_many([{"text": "Nitpick", "severity": "info"}])
        self._announce(created)
        self.assertEqual(len(self.sent), 1)

        os.environ["BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY"] = "apocalyptic"
        _, sev = self.server._findings_notify_target()
        self.assertEqual(sev, "serious")

    def test_a_failed_delivery_is_swallowed(self):
        os.environ["BRAIN_FINDINGS_NOTIFY"] = "mobile_app_phone"

        async def boom(service, title, message, timeout=15):
            raise RuntimeError("no such notify service")

        self.ha_data.send_notification = boom
        created = findings_store.add_many([{"text": "X", "severity": "critical"}])
        self._announce(created)   # must not raise


class TestQuietHoursRouting(NotifyCase):
    """The panel's own use of the router, driven rather than grepped.

    `notify_router` is tested on its own; this is the wiring, which is
    where the mistakes actually live — a quiet window read from the wrong
    place, an urgent row held with the rest, a held row never queued.
    """

    def setUp(self):
        super().setUp()
        self.notify_router = importlib.import_module("notify_router")
        self.baselines = importlib.import_module("baselines")
        self.queue = str(Path(self.tmp.name) / "notify-queue.json")
        self._old_queue = self.notify_router.QUEUE_FILE
        self.notify_router.QUEUE_FILE = self.queue
        os.environ["BRAIN_FINDINGS_NOTIFY"] = "mobile_app_phone"
        os.environ["BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY"] = "info"
        # The house's clock is the router's clock, and a test may not
        # depend on the machine's.
        self._old_tz = self.baselines.house_timezone
        self.baselines.house_timezone = lambda *a, **k: (
            dt.timezone.utc, "UTC")

    def tearDown(self):
        self.notify_router.QUEUE_FILE = self._old_queue
        self.baselines.house_timezone = self._old_tz
        for var in ("BRAIN_NOTIFY_QUIET_START", "BRAIN_NOTIFY_QUIET_END"):
            os.environ.pop(var, None)
        super().tearDown()

    def quiet(self, start="22", end="7"):
        os.environ["BRAIN_NOTIFY_QUIET_START"] = start
        os.environ["BRAIN_NOTIFY_QUIET_END"] = end

    def at(self, hour):
        """Pin the panel's clock inside or outside the window."""
        when = dt.datetime(2026, 3, 4, hour, 30,
                           tzinfo=dt.timezone.utc).timestamp()
        old = self.server.time.time
        self.server.time.time = lambda: when
        self.addCleanup(lambda: setattr(self.server.time, "time", old))

    def rows(self, *specs):
        return findings_store.add_many([
            {"text": text, "severity": "warning", "source": source}
            for text, source in specs])

    def test_outside_the_window_everything_goes_straight_out(self):
        self.quiet()
        self.at(14)
        self._announce(self.rows(("Drifting", "check:forecast.decline")))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.notify_router.load_queue(self.queue), [])

    def test_inside_the_window_an_ordinary_row_is_held_not_sent(self):
        self.quiet()
        self.at(3)
        self._announce(self.rows(("Drifting", "check:forecast.decline")))
        self.assertEqual(self.sent, [])
        held = self.notify_router.load_queue(self.queue)
        self.assertEqual([r["text"] for r in held], ["Drifting"])

    def test_inside_the_window_an_urgent_row_still_gets_through(self):
        self.quiet()
        self.at(3)
        self._announce(self.rows(("Boiler offline", "check:dev.unavailable")))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Boiler offline", self.sent[0][2])
        self.assertEqual(self.notify_router.load_queue(self.queue), [])

    def test_one_batch_can_split_both_ways(self):
        self.quiet()
        self.at(3)
        self._announce(self.rows(
            ("Boiler offline", "check:dev.unavailable"),
            ("Drifting", "check:forecast.decline")))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Boiler offline", self.sent[0][2])
        self.assertNotIn("Drifting", self.sent[0][2])
        self.assertEqual(
            [r["text"] for r in self.notify_router.load_queue(self.queue)],
            ["Drifting"])

    def test_no_quiet_hours_configured_holds_nothing(self):
        self.at(3)
        self._announce(self.rows(("Drifting", "check:forecast.decline")))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.notify_router.load_queue(self.queue), [])

    def test_the_severity_floor_still_comes_first(self):
        # A row nobody wanted notifying about must not be held either —
        # otherwise it arrives in the morning digest instead.
        os.environ["BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY"] = "serious"
        self.quiet()
        self.at(3)
        self._announce(self.rows(("Nitpick", "check:reg.no_area")))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.notify_router.load_queue(self.queue), [])

    def test_the_flush_sends_what_was_held_as_one_message(self):
        self.quiet()
        self.at(3)
        self._announce(self.rows(
            ("Drifting", "check:forecast.decline"),
            ("No area", "check:reg.no_area")))
        self.assertEqual(self.sent, [])
        sent = asyncio.run(self.server._flush_held_findings())
        self.assertEqual(sent, 2)
        self.assertEqual(len(self.sent), 1)
        _service, title, message = self.sent[0]
        self.assertIn("held", title.lower())
        self.assertIn("Drifting", message)
        self.assertIn("No area", message)
        self.assertEqual(self.notify_router.load_queue(self.queue), [])

    def test_a_finding_ended_overnight_is_not_in_the_morning_digest(self):
        self.quiet()
        self.at(3)
        created = self.rows(("Gone by morning", "check:forecast.decline"),
                            ("Still there", "check:reg.no_area"))
        self._announce(created)
        findings_store.settle_and_clear(created[0]["ts"], "fixed")
        self.assertEqual(asyncio.run(self.server._flush_held_findings()), 1)
        self.assertIn("Still there", self.sent[0][2])
        self.assertNotIn("Gone by morning", self.sent[0][2])

    def test_an_empty_queue_sends_nothing_at_all(self):
        self.assertEqual(asyncio.run(self.server._flush_held_findings()), 0)
        self.assertEqual(self.sent, [])

    def test_the_diagnostics_payload_says_what_is_being_held(self):
        self.quiet()
        self.at(3)
        self._announce(self.rows(("Drifting", "check:forecast.decline")))
        diag = self.server._notify_diagnostics()
        self.assertEqual(diag["held"], 1)
        self.assertTrue(diag["quiet_now"])
        self.assertEqual((diag["quiet_start"], diag["quiet_end"]), (22, 7))
        self.assertTrue(diag["service"])


class TestExportImport(StoreCase):
    """Everything learned, portable — and an import that merges, not clobbers.

    The export is the durable knowledge (the memory document, the findings
    work list, the settled ledger, the facts ledger). Import is a migration:
    ledgers merge with existing entries winning, the document replaces only
    an effectively-empty one unless told otherwise, and running the same
    import twice must change nothing the second time."""

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self._old_mem = self.server.SHARED_MEMORY_FILE
        self._old_kn = knowledge_store.KNOWLEDGE_FILE
        self.server.SHARED_MEMORY_FILE = Path(self.tmp.name) / "memory.md"
        knowledge_store.KNOWLEDGE_FILE = str(
            Path(self.tmp.name) / "knowledge.json")

    def tearDown(self):
        self.server.SHARED_MEMORY_FILE = self._old_mem
        knowledge_store.KNOWLEDGE_FILE = self._old_kn
        super().tearDown()

    def _populate(self):
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n- The garage fridge runs 24/7 on purpose\n",
            encoding="utf-8")
        findings_store.add("Back door battery dead", severity="serious",
                           status="open")
        findings_store.add("Porch sensor reads on all day")
        porch = [f for f in findings_store.list_all()
                 if "Porch" in f["text"]][0]
        findings_store.settle_and_clear(porch["ts"], "ignored",
                                        note="it watches the compressor")
        knowledge_store.add_fact("The loft is unheated", category="climate")

    def _fresh_install(self):
        """Point every store at an empty directory — the machine being
        migrated TO."""
        fresh = Path(self.tmp.name) / "fresh"
        fresh.mkdir()
        findings_store.FINDINGS_FILE = fresh / "findings.json"
        findings_store.SETTLED_FILE = fresh / "settled.json"
        knowledge_store.KNOWLEDGE_FILE = str(fresh / "knowledge.json")
        self.server.SHARED_MEMORY_FILE = fresh / "memory.md"

    def _import(self, payload):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                resp = await client.post("/api/memory/import", json=payload)
                return resp.status, (await resp.json()
                                     if resp.status == 200
                                     else await resp.text())
            finally:
                await client.close()

        return asyncio.run(run())

    def test_export_carries_the_durable_knowledge(self):
        self._populate()
        payload = self.server._export_payload()
        self.assertEqual(payload["brain_export"], self.server.EXPORT_VERSION)
        self.assertIn("garage fridge", payload["memory_md"])
        self.assertEqual([f["text"] for f in payload["findings"]],
                         ["Back door battery dead"])
        self.assertEqual(payload["settled"][0]["note"],
                         "it watches the compressor")
        self.assertEqual(payload["knowledge_facts"][0]["text"],
                         "The loft is unheated")

    def test_export_route_offers_a_download(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                resp = await client.get("/api/memory/export")
                self.assertEqual(resp.status, 200)
                self.assertIn("attachment",
                              resp.headers.get("Content-Disposition", ""))
                return await resp.json()
            finally:
                await client.close()

        data = asyncio.run(run())
        self.assertIn("brain_export", data)

    def test_import_is_a_migration_and_is_idempotent(self):
        self._populate()
        payload = self.server._export_payload()
        self._fresh_install()

        status, result = self._import(payload)
        self.assertEqual(status, 200)
        # empty document on the new install: the export's replaces it
        self.assertEqual(result["memory"], "replaced")
        self.assertEqual(result["findings"], 1)
        self.assertEqual(result["settled"], 1)
        self.assertEqual(result["knowledge_facts"], 1)
        self.assertIn("garage fridge",
                      self.server.SHARED_MEMORY_FILE.read_text())
        # the live row kept its lifecycle, the answer kept its note
        self.assertEqual(findings_store.list_all()[0]["status"], "open")
        self.assertEqual(findings_store.settled_listing()[0]["note"],
                         "it watches the compressor")
        # the settled ledger still suppresses the dismissed wording
        self.assertTrue(findings_store.is_known("Porch sensor reads on all day"))

        status, again = self._import(payload)
        self.assertEqual(status, 200)
        self.assertEqual((again["findings"], again["settled"],
                          again["knowledge_facts"]), (0, 0, 0))

    def test_import_never_clobbers_a_real_document_uninvited(self):
        self._populate()
        payload = self.server._export_payload()
        self._fresh_install()
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n- This install already knows things\n",
            encoding="utf-8")

        status, result = self._import(payload)
        self.assertEqual(status, 200)
        self.assertEqual(result["memory"], "kept")
        self.assertIn("already knows",
                      self.server.SHARED_MEMORY_FILE.read_text())

        status, result = self._import({**payload, "replace_memory": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["memory"], "replaced")
        self.assertIn("garage fridge",
                      self.server.SHARED_MEMORY_FILE.read_text())

    def test_import_refuses_what_is_not_an_export(self):
        status, text = self._import({"memory_md": "sneaky"})
        self.assertEqual(status, 400)
        self.assertIn("brain_export", text)


class TestFixParsing(unittest.TestCase):
    def test_parses_a_clean_reply(self):
        parsed = fixer.parse_result(json.dumps({
            "ok": True, "needs_you": False, "summary": "Corrected the trigger.",
            "changed": ["automation.morning_lights — trigger entity corrected"],
            "verified": "Re-read the automation; it now references the live entity.",
            "also_found": ["The porch light has no area"],
        }))
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["changed"]), 1)
        self.assertIn("Corrected the trigger.", fixer.result_text(parsed))
        self.assertIn("Verified:", fixer.result_text(parsed))

    def test_tolerates_a_code_fence(self):
        parsed = fixer.parse_result(
            '```json\n{"ok": true, "summary": "Done", "changed": []}\n```')
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["summary"], "Done")

    def test_needs_you_can_never_read_as_fixed(self):
        """A model that ticks both is claiming it fixed something only hands
        can fix. The finding must not settle as done."""
        parsed = fixer.parse_result(json.dumps({
            "ok": True, "needs_you": True, "summary": "Replace the battery."}))
        self.assertFalse(parsed["ok"])
        self.assertTrue(parsed["needs_you"])

    def test_an_unreadable_reply_is_a_failure_that_says_so(self):
        """The run may already have edited the house. Raising here would lose
        that; silence would be worse."""
        parsed = fixer.parse_result("I had a go at it and things happened.")
        self.assertFalse(parsed["ok"])
        self.assertIn("unreadable", parsed["summary"])
        self.assertIn("things happened", parsed["summary"])

    def test_prompt_carries_the_finding_and_the_memory(self):
        prompt = fixer.build_prompt(
            {"text": "Back Door battery is dead", "detail": "0% since Jul 12",
             "fix": "Replace the CR2032", "entity_id": "sensor.back_door_battery",
             "fixable": False, "source_title": "Device Health"},
            memory="## Device notes\n- The garage fridge runs 24/7 on purpose")
        self.assertIn("Back Door battery is dead", prompt)
        self.assertIn("sensor.back_door_battery", prompt)
        self.assertIn("starting hypothesis", prompt,
                      "the proposed fix must not read as an instruction")
        self.assertIn("garage fridge", prompt)
        self.assertIn("needing a human", prompt)

    def test_the_system_prompt_states_the_hard_rules(self):
        """These are the rules that keep an agentic run off the rails in
        somebody's actual house. Losing one silently is the failure mode."""
        for rule in ("NEVER delete", "NEVER restart", "secrets.yaml",
                     "smallest change", "one problem"):
            self.assertIn(rule.lower(), fixer.FIX_SYSTEM.lower(),
                          f"the fix contract dropped: {rule}")


class ServerCase(unittest.TestCase):
    """The panel with every store pointed at a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (
            findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
            findings_store.SETTLED_FILE,
            card_tags.TAGS_FILE, self.server.INSIGHTS_DIR,
            self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
            prompt_store.OVERRIDES_FILE, feedback_store.FEEDBACK_FILE,
            user_categories.USER_CATS_FILE, knowledge_store.KNOWLEDGE_FILE,
            engine.AUTH_FILE, engine.SHARED_AUTH_FILE, engine.CLAUDE_HOME,
        )
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.INBOX_DIR = tmp / "findings-inbox"
        findings_store.SETTLED_FILE = tmp / "findings-settled.json"
        card_tags.TAGS_FILE = tmp / "card_tags.json"
        self.server.INSIGHTS_DIR = tmp
        self.server.MEMORY_INBOX_DIR = tmp / "memory-inbox"
        self.server.SHARED_MEMORY_FILE = tmp / "memory.md"
        prompt_store.OVERRIDES_FILE = os.path.join(self.tmp.name, "o", "ov.json")
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "fb.json")
        user_categories.USER_CATS_FILE = os.path.join(self.tmp.name, "uc.json")
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "k.json")
        hypotheses.HYPOTHESES_FILE = tmp / "hypotheses.jsonl"
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        onboarding.STATE_FILE = tmp / "onboarding.json"
        onboarding.STUDY_REQUESTS_DIR = tmp / "study_requests"
        settings_store.save({"onboarded": True})
        # A credential has to exist: pressing Fix without one is rejected.
        engine.CLAUDE_HOME = os.path.join(self.tmp.name, "home")
        engine.SHARED_AUTH_FILE = os.path.join(self.tmp.name, "shared.json")
        # SECRETS_DIR too, not just AUTH_FILE: save_auth() mkdirs it, and the
        # default is /data — writable for root, denied for everyone else, so
        # skipping it passes locally and fails in CI.
        engine.SECRETS_DIR = os.path.join(self.tmp.name, "secrets")
        engine.AUTH_FILE = os.path.join(self.tmp.name, "auth.json")
        self.server.CARD_TOKEN_FILE = tmp / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = tmp / "www" / "brain"
        engine.save_auth("sk-ant-oat01-" + "x" * 30)
        # NOTHING in these tests may reach the real Claude CLI. make_app()
        # starts a worker and an auth check on startup, and this container
        # happens to have `claude` on PATH — without these stubs the suite
        # spawns real agentic runs and hangs.
        self._old_engine = (engine.run_claude, engine.run_agent)
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": json.dumps({"ok": True, "summary": "stub"}),
            "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()
        # The undo ring is process-global and in memory on purpose. Left
        # between tests, a token from one leaks into the next.
        undo_store.clear()

    def tearDown(self):
        (engine.run_claude, engine.run_agent) = self._old_engine
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE,
         card_tags.TAGS_FILE, self.server.INSIGHTS_DIR,
         self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
         prompt_store.OVERRIDES_FILE, feedback_store.FEEDBACK_FILE,
         user_categories.USER_CATS_FILE, knowledge_store.KNOWLEDGE_FILE,
         engine.AUTH_FILE, engine.SHARED_AUTH_FILE, engine.CLAUDE_HOME) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))


class TestFindingRoutes(ServerCase):
    def test_the_list_sweeps_the_inbox(self):
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / "1.jsonl").write_text(
            json.dumps({"text": "Found while studying"}) + "\n", encoding="utf-8")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.get("/api/findings")).json()
                self.assertEqual([f["text"] for f in data["findings"]],
                                 ["Found while studying"])
                self.assertEqual(data["open"], 1)
            finally:
                await client.close()

        asyncio.run(run())

    def test_done_writes_it_to_memory_and_clears_the_row(self):
        """"I've fixed it" is an ending. The row goes, the fact that it was
        fixed goes into memory, and the key stays so it is never raised
        again."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/done")).json()
                self.assertEqual(data["findings"], [])
                self.assertEqual(data["open"], 0)
                self.assertEqual([e["text"] for e in data["settled"]],
                                 ["Sensor stuck"])
                self.assertEqual(data["settled"][0]["kind"], "fixed")
                # resolving it yourself is durable knowledge about the home
                queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
                self.assertTrue(queued)
                self.assertIn("Sensor stuck", queued[0].read_text())
                # ...and it does not come back
                self.assertTrue(findings_store.is_known("sensor stuck!"))
            finally:
                await client.close()

        asyncio.run(run())

    def test_wrong_with_no_reason_says_it_is_normal_here(self):
        """Dismissing is a different fact from fixing — this house is fine as
        it is — so it lands in memory in different words."""
        findings_store.add("Hallway light is on all night")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/wrong")).json()
                self.assertEqual(data["findings"], [])
                self.assertEqual(data["settled"][0]["kind"], "ignored")
                queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
                self.assertIn("Not a problem in this home",
                              queued[0].read_text())
            finally:
                await client.close()

        asyncio.run(run())

    def test_ignore_is_still_routed_under_its_old_name(self):
        """A panel served before the update is open in somebody's browser and
        its buttons still say ignore. Same ending, same ledger kind."""
        findings_store.add("Hallway light is on all night")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/finding/{ts}/ignore")
                self.assertEqual(resp.status, 200)
                self.assertEqual((await resp.json())["settled"][0]["kind"],
                                 "ignored")
            finally:
                await client.close()

        asyncio.run(run())

    def test_wrong_with_a_reason_hands_the_reason_on(self):
        """The reason is the half that teaches. It goes to the consolidator
        as a correction — which decides what durable truth is in it — and it
        stays on the ledger entry so the analyst reads WHY, not just what."""
        findings_store.add("Front porch sensor has been on for 8 days")
        ts = findings_store.list_all()[0]["ts"]
        why = "That sensor always reads on. It's not stuck."

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/finding/{ts}/wrong",
                                         json={"note": why})
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data["findings"], [])
                self.assertEqual(data["settled"][0]["note"], why)
            finally:
                await client.close()

        asyncio.run(run())
        queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        line = json.loads(queued[0].read_text().splitlines()[0])
        # A correction, not a fact: the report is NOT true of the house, and
        # a consolidator handed it as one would file the thing being denied.
        self.assertEqual(line["source"], "correction")
        self.assertIn(why, line["fact"])
        self.assertIn("Front porch sensor has been on for 8 days", line["fact"])
        self.assertNotIn("Not a problem in this home", line["fact"])
        # ...and the analyst is told the reason, not only the wording.
        block = findings_store.prompt_block()
        self.assertIn(why, block)

    def test_a_note_on_an_ending_that_has_no_use_for_one_keeps_its_memory_line(self):
        """"I fixed it" plus a comment is still "I fixed it". Falling through
        to the ordinary line is what stops a note silently costing it."""
        findings_store.add("Back Door battery is dead")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/finding/{ts}/done",
                                         json={"note": "swapped the cell"})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        line = json.loads(queued[0].read_text().splitlines()[0])
        self.assertEqual(line["source"], "homeowner")
        self.assertIn("Fixed by the homeowner", line["fact"])

    def test_i_fixed_it_can_say_what_you_did(self):
        """Same box as Wrong, and not the same thing: nothing is being
        denied here, so the note is more of the fact rather than evidence
        against a report — and it keeps the homeowner source, not
        `correction`, or the consolidator would be told to weigh a fix
        against a claim nobody made."""
        findings_store.add("Back Door battery is dead")
        ts = findings_store.list_all()[0]["ts"]
        why = "Replaced the CR2032 — it's a 3-monthly job on that one."

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/finding/{ts}/done",
                                         json={"note": why})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        line = json.loads(queued[0].read_text().splitlines()[0])
        self.assertEqual(line["source"], "homeowner")
        self.assertIn("Fixed by the homeowner", line["fact"])
        self.assertIn(why, line["fact"])

    def test_every_ending_hands_back_a_way_to_undo_it(self):
        """They delete the row — that is what makes the list a list — and
        the two endings sit beside each other meaning opposite things, so a
        mis-tap has nothing to put back by hand."""
        for verb in ("wrong", "done"):
            findings_store.add(f"Problem for {verb}")
            ts = next(f["ts"] for f in findings_store.list_all()
                      if f["text"] == f"Problem for {verb}")

            async def run(v=verb, t=ts):
                client = self._client()
                await client.start_server()
                try:
                    return await (await client.post(f"/api/finding/{t}/{v}")).json()
                finally:
                    await client.close()

            self.assertTrue(asyncio.run(run()).get("undo"), verb)

    def test_undoing_an_ending_puts_back_all_three_of_its_effects(self):
        """An ending does three things — deletes the row, writes the key
        that suppresses it, queues the memory line. Undoing one of the three
        would leave a card that is back on the list and still silently
        deduped away next run."""
        findings_store.add("Front porch sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(
                    f"/api/finding/{ts}/wrong",
                    json={"note": "It always reads on."})).json()
                self.assertEqual(data["findings"], [])
                resp = await client.post(f"/api/undo/{data['undo']}")
                self.assertEqual(resp.status, 200)
                return await resp.json()
            finally:
                await client.close()

        payload = asyncio.run(run())
        self.assertTrue(payload["undone"])
        self.assertEqual([f["text"] for f in payload["findings"]],
                         ["Front porch sensor stuck"])
        self.assertEqual(payload["findings"][0]["ts"], ts)
        # The suppression is lifted...
        self.assertEqual(findings_store.settled_listing(), [])
        # ...and the memory line it queued is out of the inbox. It cannot
        # have been consolidated yet — the token is younger than any pass.
        self.assertEqual(
            list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])

    def test_a_token_is_spent_once(self):
        """Two presses on a toast still on screen must not restore twice."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/wrong")).json()
                first = await client.post(f"/api/undo/{data['undo']}")
                second = await client.post(f"/api/undo/{data['undo']}")
                return first.status, second.status
            finally:
                await client.close()

        first, second = asyncio.run(run())
        self.assertEqual(first, 200)
        self.assertEqual(second, 404)
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_undo_says_so_when_the_row_came_back_on_its_own(self):
        """Re-reported while the toast was up: the list holds a newer
        version, so putting the old one back would lose whatever happened
        since. The suppression still lifts — that is what was asked for."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/wrong")).json()
                # something re-files it under the same id before you press Undo
                findings_store._write([{"ts": ts, "text": "Sensor stuck",
                                        "status": "open"}])
                return await (await client.post(f"/api/undo/{data['undo']}")).json()
            finally:
                await client.close()

        payload = asyncio.run(run())
        self.assertFalse(payload["undone"])
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(findings_store.settled_listing(), [])

    def test_dismiss_is_undoable_and_teaches_nothing_either_way(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.delete(f"/api/finding/{ts}")).json()
                self.assertTrue(data.get("undo"))
                return await (await client.post(f"/api/undo/{data['undo']}")).json()
            finally:
                await client.close()

        payload = asyncio.run(run())
        self.assertTrue(payload["undone"])
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual(list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])

    def test_fix_and_snooze_offer_no_undo(self):
        """Fix starts a Claude run against the actual house, so an "undo"
        that only took the card back would be a lie about what it undid.
        Snooze took nothing away and already has "Bring it back now"."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                snoozed = await (await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "week"})).json()
                fixed = await (await client.post(f"/api/finding/{ts}/fix")).json()
                return snoozed, fixed
            finally:
                await client.close()

        snoozed, fixed = asyncio.run(run())
        self.assertNotIn("undo", snoozed)
        self.assertNotIn("undo", fixed)

    def test_undoing_a_guess_puts_it_back_in_the_queue(self):
        claim = "The garage fridge is meant to run 24/7"
        entry = hypotheses.propose(claim, "energy")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(
                    f"/api/hypothesis/{entry['ts']}/confirm")).json()
                self.assertTrue(data.get("undo"))
                return await (await client.post(f"/api/undo/{data['undo']}")).json()
            finally:
                await client.close()

        payload = asyncio.run(run())
        self.assertTrue(payload["undone"])
        self.assertEqual([h["text"] for h in payload["hypotheses"]], [claim])
        self.assertEqual([h["status"] for h in hypotheses.list_all()], ["open"])
        self.assertEqual(list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])

    def test_undoing_a_no_clears_the_dead_end_too(self):
        """Rejecting also wrote the claim into the ask-history. Leaving that
        behind would put the guess back on the list and make it
        un-proposable for ever after."""
        claim = "The attic fan is broken"
        entry = hypotheses.propose(claim, "energy")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(
                    f"/api/hypothesis/{entry['ts']}/reject",
                    json={"note": "It's on a humidistat."})).json()
                return await (await client.post(f"/api/undo/{data['undo']}")).json()
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual([h["status"] for h in hypotheses.list_all()], ["open"])
        self.assertEqual(hypotheses.dead_ends(), [])
        self.assertFalse(knowledge_store.is_known_question(claim))
        self.assertEqual(list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])

    def test_an_expired_token_is_refused_rather_than_guessed_at(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                return (await client.post("/api/undo/nope-not-a-token")).status
            finally:
                await client.close()

        self.assertEqual(asyncio.run(run()), 404)

    def test_the_list_carries_the_guesses_too(self):
        """One list of decisions, one badge that can read as done. The count
        spans both, because "how much is waiting on me" is the only question
        a badge on a work list answers."""
        findings_store.add("Back Door battery is dead")
        hypotheses.propose("The garage fridge is meant to run 24/7", "energy")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.get("/api/findings")).json()
                self.assertEqual(len(data["findings"]), 1)
                self.assertEqual([h["text"] for h in data["hypotheses"]],
                                 ["The garage fridge is meant to run 24/7"])
                self.assertEqual(data["open"], 2)
                status = await (await client.get("/api/status")).json()
                self.assertEqual(status["findings_open"], 2)
            finally:
                await client.close()

        asyncio.run(run())

    def test_ack_clears_a_finished_fix_without_repeating_its_memory(self):
        """The fixer already wrote what it changed. Got it only means "I have
        read this", so it must not queue a second line saying it again."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixed", result="Reloaded it")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/ack")).json()
                self.assertEqual(data["findings"], [])
                self.assertEqual(data["settled"][0]["kind"], "fixed")
                self.assertEqual(
                    list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])
            finally:
                await client.close()

        asyncio.run(run())

    def test_unsettle_lets_brain_raise_it_again(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "ignored")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/findings/unsettle",
                                         json={"key": "sensor stuck"})
                data = await resp.json()
                self.assertEqual(data["settled"], [])
                self.assertFalse(findings_store.is_known("Sensor stuck"))
                # ...and asking again for something nothing suppresses is a 404
                resp = await client.post("/api/findings/unsettle",
                                         json={"key": "sensor stuck"})
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())

    def test_delete_removes_it(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.delete(f"/api/finding/{ts}")).json()
                self.assertEqual(data["findings"], [])
                self.assertEqual((await client.delete(f"/api/finding/{ts}")).status, 404)
                self.assertEqual((await client.post("/api/finding/nope/fix")).status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_fix_queues_a_job_and_never_runs_on_its_own(self):
        """Nothing may change the house except a press of this button — so
        the route is the only thing that enqueues a fix, and a second press
        while one is in flight is refused rather than queued behind it."""
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]
        old_run_fix = self.server._run_fix

        async def run():
            gate = asyncio.Event()
            started = asyncio.Event()

            async def held(job_id):
                started.set()
                await gate.wait()

            self.server._run_fix = held
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/fix")).json()
                self.assertEqual(data["findings"][0]["status"], "fixing")
                job = self.server.JOBS[f"{self.server.FIX_JOB_PREFIX}{ts}"]
                self.assertEqual(job["kind"], "fix")
                self.assertEqual(job["finding_ts"], ts)
                await asyncio.wait_for(started.wait(), 5)

                # a second press while it's in flight is refused, not queued
                self.assertEqual(
                    (await client.post(f"/api/finding/{ts}/fix")).status, 409)
            finally:
                gate.set()
                await client.close()
                self.server._run_fix = old_run_fix

        asyncio.run(run())

    def test_fix_without_a_credential_is_refused(self):
        engine.clear_auth()
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                self.assertEqual(
                    (await client.post(f"/api/finding/{ts}/fix")).status, 400)
                self.assertEqual(findings_store.get(ts)["status"], "open")
            finally:
                await client.close()

        asyncio.run(run())


class TestSnooze(StoreCase):
    """"Remind me later" and "not a problem" are different answers.

    The second is permanent and is fed back into every future analysis so
    the same non-problem is never raised again. Using it for the first would
    quietly throw away a real problem you meant to come back to — so snooze
    must not touch the status at all.
    """

    def test_snoozing_leaves_the_finding_exactly_as_open_as_it_was(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        shaped = findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual(shaped["status"], "open")
        self.assertEqual(findings_store.get(ts)["status"], "open")
        self.assertTrue(findings_store.is_snoozed(shaped))

    def test_a_snoozed_finding_stops_asking(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        self.assertEqual(findings_store.open_count(), 1)
        findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual(findings_store.open_count(), 0)
        self.assertEqual(findings_store.listing()["open"], 0)
        self.assertEqual(findings_store.listing()["snoozed"], 1)
        self.assertEqual(findings_store.list_all("live"), [])

    def test_a_snoozed_finding_is_findable_rather_than_vanished(self):
        """The point of "later" is that it comes back, and something you
        cannot find has not come back."""
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual([f["text"] for f in findings_store.list_all("snoozed")],
                         ["Battery low"])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_it_comes_back_on_its_own(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) - 1)   # already due
        self.assertEqual(findings_store.open_count(), 1)
        self.assertEqual(len(findings_store.list_all("live")), 1)
        self.assertEqual(findings_store.list_all("snoozed"), [])

    def test_it_can_be_brought_back_by_hand(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) + 3600)
        findings_store.snooze(ts, 0)
        self.assertEqual(findings_store.open_count(), 1)

    def test_snoozing_an_unknown_finding_is_not_an_error(self):
        self.assertIsNone(findings_store.snooze(1, int(time.time()) + 60))


class TestFindingsUI(unittest.TestCase):
    """The panel is the only caller of these routes, so a verb it presses
    that the server doesn't know is a button that does nothing — and there
    is no import to catch it."""

    @classmethod
    def setUpClass(cls):
        cls.js = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        cls.server = importlib.import_module("server")

    def test_every_verb_the_ui_presses_exists(self):
        pressed = set(re.findall(r'findAction\(\s*f,\s*"([a-z]+)"', self.js))
        pressed |= set(re.findall(r'chatFindingAction\("([a-z]+)"', self.js))
        # "fix" and "forget" have routes of their own rather than table rows
        for verb in pressed - {"fix", "forget"}:
            self.assertIn(verb, self.server.FINDING_VERBS, verb)

    def test_the_two_endings_read_differently(self):
        """"I did it" beside "Not a problem" was the confusion: both looked
        like ways to make a card go away. The labels have to say which fact
        each one teaches the home.

        They are verbs now, and short — a row of four buttons is read at a
        glance or not at all — but they still say different things, and the
        tooltips carry the meaning the labels no longer spell out."""
        self.assertIn("I fixed it", self.js)
        self.assertIn("Ignore", self.js)
        self.assertNotIn("I did it", self.js)

    def test_every_button_on_the_row_carries_a_glyph(self):
        """One unlabelled-by-icon button in a row of icons reads as the odd
        one out rather than as the quiet one."""
        for label in ('"✦  Fix it"', '"💬  Discuss"', '"✓  I fixed it"',
                      '"⏰  Remind me later"', '"⌫  Dismiss"', '"✕  Wrong"'):
            self.assertIn(label, self.js)

    def test_dismiss_clears_without_teaching_anything(self):
        """Three ways off the list, and they are not the same thing.

        Wrong settles: the answer goes into memory and the analyst is told
        never to raise it again. Dismiss just clears the row — no memory
        line, no ledger entry — so the next run is free to find it again.
        That is `forget`, which findings_store already separates from
        `wrong` for exactly this reason, and it had no button.
        """
        self.assertIn('findAction(\n      f, "forget", "Cleared", btns)', self.js)
        self.assertIn('f, "wrong",', self.js)

    def test_wrong_asks_why_and_sends_what_it_is_told(self):
        """The reason is the half that teaches. A button that only suppressed
        a wording left brAIn knowing one sentence was unwanted and nothing
        about the house — the next run made the same mistake in new words."""
        self.assertIn("openNoteForm(card, actions", self.js)
        self.assertIn("What's brAIn got wrong?", self.js)
        # The note travels as a body on the same verb — not a second endpoint,
        # because "wrong" and "wrong, because…" are one ending either way.
        self.assertIn("...(note ? { body: JSON.stringify({ note }) } : {})", self.js)

    def test_the_reason_is_offered_and_never_demanded(self):
        """"Not a problem here" needs no essay. A required box turns a
        one-press dismissal into a chore and fills up with "no"."""
        self.assertNotIn("send.disabled = !ta.value", self.js)
        self.assertIn("Optional", self.js)

    def test_the_endings_tooltips_stay_short(self):
        """These are read at a glance beside five other buttons. The old
        Ignore tooltip ran to two clauses and a caveat about wording."""
        self.assertIn('"brAIn has this wrong, or it\'s normal here — say why, and it "',
                      self.js)
        self.assertNotIn("in any wording", self.js)

    def test_there_is_no_archive_of_dismissed_cards(self):
        """The whole point: an ending deletes the row and writes the answer
        into memory, which is then the one place it is read from.

        There is no view of the settled ledger at all. Rendering it beside
        the work list put a growing pile of answered cards next to a list
        that is supposed to empty, and invited people to treat it as the
        record when memory already is. The ledger stays — it is the dedup
        index that stops the analyst re-raising what you answered — it is
        just not something the panel draws."""
        self.assertNotIn('{ id: "ignored"', self.js)
        self.assertNotIn('{ id: "fixed"', self.js)
        self.assertNotIn('label: "Answered"', self.js)
        self.assertNotIn('label: "Everything"', self.js)
        self.assertNotIn("makeSettled", self.js)
        self.assertNotIn("findingsSettled", self.js)
        # Two chips and no more: the work, and what is waiting.
        self.assertIn('{ id: "live", label: "Needs you"', self.js)
        self.assertIn('{ id: "snoozed", label: "Later"', self.js)


class TestUndoStore(unittest.TestCase):
    """"I misclicked", and nothing more.

    In memory and short-lived on purpose: it is the thing the toast offers
    while the toast is on screen, not a history. A durable undo log would be
    a second record of decisions that memory.md already holds — the exact
    duplication the Findings redesign removed.
    """

    def setUp(self):
        undo_store.clear()

    tearDown = setUp

    def test_a_token_is_taken_exactly_once(self):
        """Undo is not idempotent in the useful direction: two presses on a
        toast still up must not restore a row twice."""
        token = undo_store.record("finding", finding={"ts": 1})
        self.assertEqual(undo_store.take(token)["finding"], {"ts": 1})
        self.assertIsNone(undo_store.take(token))

    def test_an_unknown_token_is_none_rather_than_a_raise(self):
        self.assertIsNone(undo_store.take("not-a-token"))

    def test_an_expired_token_is_gone(self):
        token = undo_store.record("finding", finding={"ts": 1})
        undo_store._ENTRIES[token]["at"] -= undo_store.TTL_S + 1
        self.assertIsNone(undo_store.take(token))

    def test_the_ring_drops_the_oldest_first(self):
        """More than a handful pending means somebody is working through a
        list fast, and only the newest few are reachable anyway."""
        tokens = [undo_store.record("finding", finding={"ts": i})
                  for i in range(undo_store.MAX_ENTRIES + 3)]
        self.assertIsNone(undo_store.take(tokens[0]))
        self.assertIsNotNone(undo_store.take(tokens[-1]))


class TestSettledLedger(StoreCase):
    """Settling deletes the row, so everything that used to be carried BY the
    row — "we already told you about this", "you said it isn't a problem" —
    has to be carried by the ledger instead. If it isn't, every ending
    quietly becomes a Forget, and the analyst re-reports it next week."""

    def test_settling_clears_the_row_and_keeps_the_answer(self):
        findings_store.add("Freezer door sensor is noisy")
        ts = findings_store.list_all()[0]["ts"]
        settled = findings_store.settle_and_clear(ts, "ignored")
        self.assertEqual(settled["text"], "Freezer door sensor is noisy")
        self.assertEqual(findings_store.list_all(), [])
        self.assertEqual(findings_store.listing()["settled"][0]["kind"],
                         "ignored")

    def test_a_settled_problem_is_never_reported_again(self):
        findings_store.add("Freezer door sensor is noisy")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "ignored")
        for wording in ("Freezer door sensor is noisy",
                        "freezer door sensor is noisy!",
                        "  Freezer  door   sensor is noisy  "):
            self.assertTrue(findings_store.is_known(wording), wording)
            entry, created = findings_store.add(wording)
            self.assertFalse(created, f"{wording!r} came back")
            # nothing to hand back either: the row it would return is gone
            self.assertIsNone(entry)
        self.assertEqual(findings_store.add_many(
            [{"text": "freezer DOOR sensor is noisy"}]), [])
        self.assertEqual(findings_store.list_all(), [])

    def test_settling_the_same_problem_twice_keeps_one_entry(self):
        for _ in range(2):
            findings_store.add("Noisy sensor")
            ts = findings_store.list_all()[0]["ts"]
            findings_store.settle_and_clear(ts, "fixed")
            findings_store.unsettle("noisy sensor")
            findings_store.add("Noisy sensor")
            ts = findings_store.list_all()[0]["ts"]
            findings_store.settle_and_clear(ts, "ignored")
            findings_store.unsettle("noisy sensor")
        findings_store.add("Noisy sensor")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "ignored")
        self.assertEqual(len(findings_store.settled_listing()), 1)

    def test_unsettling_is_the_only_thing_that_forgets_an_answer(self):
        findings_store.add("Noisy sensor")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "ignored")
        self.assertTrue(findings_store.unsettle("noisy sensor"))
        self.assertFalse(findings_store.unsettle("noisy sensor"))
        self.assertFalse(findings_store.is_known("Noisy sensor"))
        _, created = findings_store.add("Noisy sensor")
        self.assertTrue(created)

    def test_a_settlement_that_never_happened_is_none(self):
        self.assertIsNone(findings_store.settle_and_clear(999, "fixed"))

    def test_a_row_goes_back_under_the_id_it_left_under(self):
        """Undo's half of an ending. The ts is the id the panel acted on, so
        a row that came back under a new one would be a different card to
        everything holding a reference to it."""
        findings_store.add("Sensor stuck")
        row = findings_store.list_all()[0]
        findings_store.settle_and_clear(row["ts"], "ignored")
        self.assertEqual(findings_store.list_all(), [])

        back = findings_store.restore(row)
        self.assertEqual(back["ts"], row["ts"])
        self.assertEqual(back["text"], "Sensor stuck")
        self.assertEqual(back["status"], "open")
        self.assertEqual(findings_store.open_count(), 1)

    def test_a_row_is_not_restored_over_a_newer_one(self):
        """If the analyst re-reported it while the toast was up, the list
        already holds a newer version and overwriting it would throw away
        whatever has happened since."""
        findings_store.add("Sensor stuck")
        row = findings_store.list_all()[0]
        findings_store.settle_and_clear(row["ts"], "ignored")
        findings_store.unsettle(findings_store.normalize(row["text"]))
        findings_store.add("Sensor stuck")
        again = findings_store.list_all()[0]
        # Force the collision the ts-as-id contract makes possible.
        again["ts"] = row["ts"]
        findings_store._write([again])

        self.assertIsNone(findings_store.restore(row))
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_restoring_junk_is_refused_rather_than_stored(self):
        self.assertIsNone(findings_store.restore({}))
        self.assertIsNone(findings_store.restore({"ts": 1, "text": "  "}))

    def test_the_reason_survives_the_row_it_was_typed_on(self):
        """The row is deleted; the reason is the part worth keeping. Losing
        it would leave a key that suppresses one wording and teaches the
        analyst nothing about the house."""
        findings_store.add("Front porch sensor stuck on for 8 days")
        ts = findings_store.list_all()[0]["ts"]
        settled = findings_store.settle_and_clear(
            ts, "ignored", note="That sensor always reads on.")
        self.assertEqual(settled["note"], "That sensor always reads on.")
        self.assertEqual(findings_store.settled_listing()[0]["note"],
                         "That sensor always reads on.")

    def test_a_reason_is_rendered_with_the_finding_it_corrects(self):
        """Verbatim and attributed. "They said: X" is evidence handed over;
        an unattributed line reads as a rule the model has to obey, which is
        not what a homeowner typing one sentence is doing."""
        findings_store.add("Front porch sensor stuck on for 8 days")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(
            ts, "ignored", note="It watches the compressor — it's meant to.")
        block = findings_store.prompt_block()
        self.assertIn("Front porch sensor stuck on for 8 days", block)
        self.assertIn("They said: It watches the compressor — it's meant to.",
                      block)
        # ...and it is offered as something to reason from, not as a filter.
        self.assertIn("take it into account", block)

    def test_a_dismissal_with_no_reason_renders_no_empty_line(self):
        findings_store.add("Waved off")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.settle_and_clear(ts, "ignored")
        self.assertNotIn("They said:", findings_store.prompt_block())

    def test_a_reason_is_capped(self):
        findings_store.add("Long story")
        ts = findings_store.list_all()[0]["ts"]
        settled = findings_store.settle_and_clear(ts, "ignored", note="x" * 900)
        self.assertEqual(len(settled["note"]), findings_store.MAX_NOTE)
        self.assertEqual(len(findings_store.settled_listing()[0]["note"]),
                         findings_store.MAX_NOTE)

    def test_a_ledger_written_before_notes_existed_still_reads(self):
        """An upgrade finds entries with no `note` key at all, and a prompt
        that raises on one is a prompt that never builds again."""
        findings_store.SETTLED_FILE.write_text(json.dumps({"settled": [
            {"key": "waved off", "text": "Waved off", "kind": "ignored",
             "ts": 1750000000}]}), encoding="utf-8")
        block = findings_store.prompt_block()
        self.assertIn("Waved off", block)
        self.assertNotIn("They said:", block)

    def test_only_the_two_endings_are_settlements(self):
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        with self.assertRaises(ValueError):
            findings_store.settle_and_clear(ts, "snoozed")

    def test_the_ledger_still_teaches_the_analyst(self):
        findings_store.add("Still open")
        findings_store.add("Waved off")
        findings_store.add("Sorted out")
        for text, kind in (("Waved off", "ignored"), ("Sorted out", "fixed")):
            ts = next(f["ts"] for f in findings_store.list_all()
                      if f["text"] == text)
            findings_store.settle_and_clear(ts, kind)
        block = findings_store.prompt_block()
        self.assertIn("Still open", block)
        self.assertIn("SAID WERE WRONG", block)
        self.assertIn("Waved off", block)
        self.assertIn("ALREADY DEALT WITH", block)
        self.assertIn("Sorted out", block)

    def test_pre_ledger_dismissals_are_migrated_not_stranded(self):
        """Upgrading with dismissed rows on disk: the Dismissed filter is
        gone, so leaving them there would suppress findings from a place
        nobody can see, with nothing on screen saying so."""
        findings_store.add("Waved off ages ago")
        findings_store.add("Still open")
        ts = next(f["ts"] for f in findings_store.list_all()
                  if f["text"] == "Waved off ages ago")
        findings_store.set_status(ts, "ignored")

        self.assertEqual(findings_store.migrate_settled(), 1)
        self.assertEqual([f["text"] for f in findings_store.list_all()],
                         ["Still open"])
        self.assertEqual([e["text"] for e in findings_store.settled_listing()],
                         ["Waved off ages ago"])
        self.assertTrue(findings_store.is_known("waved off ages ago"))
        # idempotent: a second startup has nothing left to move
        self.assertEqual(findings_store.migrate_settled(), 0)

    def test_a_finished_fix_is_not_migrated(self):
        """It is live news, not an answer — somebody still has to read what
        brAIn changed in their house."""
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixed", result="Reloaded it")
        self.assertEqual(findings_store.migrate_settled(), 0)
        self.assertEqual(len(findings_store.list_all("live")), 1)


class TestSnoozeAndDiscussRoutes(ServerCase):
    def test_the_snooze_route_takes_a_duration_and_gives_it_back(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                before = int(time.time())
                data = await (await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "week"})).json()
                self.assertEqual(data["open"], 0)
                self.assertEqual(data["snoozed"], 1)
                until = findings_store.get(ts)["snoozed_until"]
                self.assertGreaterEqual(until, before + 7 * 86400 - 5)
                # Still open. Snoozing is not a decision.
                self.assertEqual(findings_store.get(ts)["status"], "open")

                data = await (await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "now"})).json()
                self.assertEqual(data["open"], 1)

                resp = await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "forever"})
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_discussing_a_finding_hands_it_to_the_chat_read_only(self):
        """The discussion is for understanding it. "Explain this to me" and
        "go change my house" are different consents, and Fix it is the one
        that gives the second."""
        findings_store.add("Porch light never comes on",
                           detail="The trigger cannot fire",
                           fix="Invert the condition", entity_id="light.porch")
        ts = findings_store.list_all()[0]["ts"]
        sent = []

        async def run():
            import chat_session
            client = self._client()
            await client.start_server()

            async def fake_send(text):
                sent.append(text)
                return {"ok": True}

            session = chat_session.session()
            original, session.send = session.send, fake_send
            try:
                data = await (await client.post(
                    f"/api/finding/{ts}/discuss")).json()
                self.assertTrue(data["ok"])
                self.assertEqual(data["finding"]["ts"], ts)
            finally:
                session.send = original
                await client.close()

        asyncio.run(run())
        self.assertEqual(len(sent), 1)
        prompt = sent[0]
        # The first line is the conversation's title in the Chats rail —
        # "Discussing: <the finding>", not a sentence every discussion
        # shares.
        self.assertTrue(
            prompt.startswith("Discussing: Porch light never comes on"),
            prompt.splitlines()[0])
        self.assertIn("The trigger cannot fire", prompt)
        self.assertIn("Invert the condition", prompt)
        self.assertIn("light.porch", prompt)
        self.assertIn("Do not change anything", prompt)

    def test_discussing_a_finding_that_does_not_exist_is_a_404(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/finding/1/discuss")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())


class TestFixRun(ServerCase):
    def setUp(self):
        super().setUp()
        self._old_agent = engine.run_agent
        findings_store.add("Automation can't fire", fix="Correct the trigger")
        self.ts = findings_store.list_all()[0]["ts"]
        self.job = f"{self.server.FIX_JOB_PREFIX}{self.ts}"

    def tearDown(self):
        engine.run_agent = self._old_agent
        super().tearDown()

    def _reply(self, obj):
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": json.dumps(obj), "error": "", "meta": {}}

    def _run(self):
        self.server._set_job(self.job, state="queued", kind="fix", finding_ts=self.ts)
        asyncio.run(self.server._run_fix(self.job))

    def test_a_successful_fix_settles_and_is_remembered(self):
        self._reply({"ok": True, "summary": "Trigger corrected.",
                     "changed": ["automation.morning_lights — trigger corrected"],
                     "verified": "Reloaded automations; it fires again."})
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "fixed")
        self.assertIn("Trigger corrected.", entry["result"])
        self.assertEqual(entry["changed"],
                         ["automation.morning_lights — trigger corrected"])
        self.assertEqual(self.server.JOBS[self.job]["state"], "done")
        # a later analysis must not rediscover a problem brAIn resolved
        queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        self.assertTrue(queued, "the fix was not written into memory")
        self.assertIn("Automation can't fire", queued[0].read_text())

    def test_needs_you_does_not_read_as_fixed(self):
        self._reply({"ok": False, "needs_you": True,
                     "summary": "The CR2032 has to be replaced by hand."})
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "needs_you")
        self.assertEqual(findings_store.open_count(), 1)

    def test_side_findings_become_findings_not_edits(self):
        """Anything it notices on the way in is a new work item, never an
        edit it wasn't asked to make."""
        self._reply({"ok": True, "summary": "Done.", "changed": ["x — y"],
                     "also_found": ["The porch light has no area"]})
        self._run()
        texts = [f["text"] for f in findings_store.list_all()]
        self.assertIn("The porch light has no area", texts)

    def test_a_failed_run_leaves_a_visible_state_not_a_stuck_one(self):
        """A finding wedged on 'fixing' forever is unreachable from the UI —
        no button is offered in that state."""
        engine.run_agent = lambda *a, **k: {
            "ok": False, "text": "", "error": "claude timed out", "meta": {}}
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("claude timed out", entry["result"])
        self.assertEqual(self.server.JOBS[self.job]["state"], "error")

    def test_an_unparseable_reply_fails_loudly(self):
        self._reply_raw = None
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": "I did some stuff", "error": "", "meta": {}}
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("unreadable", entry["result"])

    def test_a_deleted_finding_does_not_crash_the_worker(self):
        findings_store.remove(self.ts)
        self._run()
        self.assertEqual(self.server.JOBS[self.job]["state"], "error")

    def test_the_worker_dispatches_on_kind(self):
        """One queue serves cards and fixes; picking the wrong handler would
        try to generate an insight called 'fix-1234'."""
        self._reply({"ok": True, "summary": "Done.", "changed": []})
        seen = []
        old_generate = self.server._generate

        async def spy(job_id):
            seen.append(job_id)

        self.server._generate = spy
        try:
            async def run():
                self.server._enqueue(self.job, kind="fix", finding_ts=self.ts)
                worker = asyncio.ensure_future(self.server._worker())
                await self.server.QUEUE.join()
                worker.cancel()

            asyncio.run(run())
        finally:
            self.server._generate = old_generate
        self.assertEqual(seen, [], "a fix was handed to the insight generator")
        self.assertEqual(findings_store.get(self.ts)["status"], "fixed")


if __name__ == "__main__":
    unittest.main()
