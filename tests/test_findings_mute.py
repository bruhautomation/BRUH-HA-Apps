#!/usr/bin/env python3
""""Stop raising these": a producer the homeowner has had enough of.

The scorecard reads a rule as wrong about this house — `forecast.decline`
at 0 confirmed against 3 marked Wrong, `chore.waiting` at 0 of 2 — and the
only answer the tab had was Wrong, one row at a time, which settles one
wording and leaves the next pass to make the same mistake in new words. A
mute is the press for the RULE: its open rows come off the list, nothing it
files lands again, and one press on the Findings tab reverses it.

Five claims, each its own case. The rows are dropped at the one door every
producer files through (`triage.gate`), never filed and hidden. The press
clears what was already there, and only what nobody has acted on. Nothing
is settled and nothing goes into memory — a mute is about the rule, not
the house. Unmuting brings nothing back until the producer reports it
again (`unsettle`'s rule). And the setting cannot be read as muting more
than it says: an unreadable file mutes nothing, which is the direction in
which being wrong shows a card.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import settings_store  # noqa: E402
import triage  # noqa: E402
from test_todo_list import PanelCase  # noqa: E402


def row(source: str, n: int = 0) -> dict:
    return {"text": f"something from {source} ({n})", "severity": "warning",
            "source": source, "source_title": source.title(),
            "fix": "the generic sentence"}


class TestTheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "s.json")
        self.addCleanup(setattr, settings_store, "SETTINGS_FILE", self._old)

    def test_it_is_a_deduped_list_of_producer_ids(self):
        settings_store.save({"muted_sources": [" check:dev.frozen ",
                                               "check:dev.frozen", "custom-1"]})
        self.assertEqual(settings_store.load()["muted_sources"],
                         ["check:dev.frozen", "custom-1"])
        self.assertEqual(settings_store.muted(),
                         {"check:dev.frozen", "custom-1"})

    def test_anything_that_is_not_a_list_of_strings_is_refused(self):
        for bad in ("check:dev.frozen", [1], [None], {"a": 1}):
            with self.assertRaises(ValueError):
                settings_store.save({"muted_sources": bad})

    def test_it_is_capped(self):
        with self.assertRaises(ValueError):
            settings_store.save({"muted_sources": [
                f"check:x{i}" for i in range(settings_store.MAX_MUTED + 1)]})

    def test_nothing_muted_is_the_default_and_an_unreadable_file_mutes_nothing(self):
        self.assertEqual(settings_store.muted(), set())
        Path(settings_store.SETTINGS_FILE).write_text("{not json")
        self.assertEqual(settings_store.muted(), set())


class TestTheGate(unittest.TestCase):
    """The rows are dropped at the door, never filed and hidden."""

    def test_a_muted_producers_rows_never_reach_the_store(self):
        rows = [row("check:dev.frozen"), row("check:dev.battery_low")]
        out = triage.gate(rows, muted={"check:dev.frozen"})
        self.assertEqual([r["source"] for r in out], ["check:dev.battery_low"])
        self.assertEqual(out[0]["status"], "triaging")

    def test_nothing_muted_is_the_gate_it_always_was(self):
        rows = [row("check:dev.frozen")]
        self.assertEqual([r["source"] for r in triage.gate(rows, muted=set())],
                         ["check:dev.frozen"])

    def test_the_gate_reads_the_setting_when_not_told(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = os.path.join(tmp.name, "s.json")
        self.addCleanup(setattr, settings_store, "SETTINGS_FILE", old)
        settings_store.save({"muted_sources": ["custom-9"]})
        out = triage.gate([row("custom-9"), row("check:x")])
        self.assertEqual([r["source"] for r in out], ["check:x"])

    def test_the_gate_still_does_not_mutate_what_it_is_given(self):
        rows = [row("check:dev.frozen")]
        triage.gate(rows, muted={"check:dev.frozen"})
        self.assertNotIn("status", rows[0])


class TestThePress(PanelCase):
    """The route, driven end to end through the real app."""

    def post(self, path, body):
        async def run(client):
            res = await client.post(path, json=body)
            self.assertEqual(res.status, 200, await res.text())
            return await res.json()
        return self.drive(run)

    def test_muting_takes_the_producers_open_rows_off_and_names_it(self):
        findings_store.add_many(triage.gate([
            row("check:dev.frozen", 1), row("check:dev.frozen", 2),
            row("check:dev.battery_low", 3)]))
        payload = self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cleared"], 2)
        self.assertEqual([f["source"] for f in payload["findings"]],
                         ["check:dev.battery_low"])
        # Named by the check's own title, not its group's: "Device check"
        # three times is three things nobody can tell apart.
        self.assertEqual(payload["muted"],
                         [{"source": "check:dev.frozen",
                           "title": "Sensors frozen on one value"}])
        # And a producer that is not a check is named by what it filed
        # under, which is all anything has recorded about it.
        findings_store.add_many(triage.gate([row("custom-7")]))
        listing = self.post("/api/findings/mute", {"source": "custom-7"})
        self.assertEqual(listing["muted"][1],
                         {"source": "custom-7", "title": "Custom-7"})

    def test_a_mute_settles_nothing_and_teaches_nothing(self):
        findings_store.add_many(triage.gate([row("check:dev.frozen")]))
        self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual(self.queued_memory(), [])

    def test_a_row_somebody_is_acting_on_stays(self):
        created = findings_store.add_many(triage.gate([
            row("check:dev.frozen", 1), row("check:dev.frozen", 2)]))
        # `fixed` is brAIn having changed something in the house and news
        # nobody has read; a mute is about the rule and may not take it.
        findings_store.set_status(created[0]["ts"], "fixed", result="done")
        payload = self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        self.assertEqual(payload["cleared"], 1)
        self.assertEqual([f["status"] for f in payload["findings"]], ["fixed"])

    def test_the_next_pass_files_nothing_from_it(self):
        self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        created = findings_store.add_many(triage.gate([row("check:dev.frozen")]))
        self.assertEqual(created, [])
        self.assertEqual(findings_store.list_all(), [])

    def test_unmuting_brings_nothing_back_until_it_is_reported_again(self):
        findings_store.add_many(triage.gate([row("check:dev.frozen")]))
        self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        payload = self.post("/api/findings/unmute", {"source": "check:dev.frozen"})
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["muted"], [])
        created = findings_store.add_many(triage.gate([row("check:dev.frozen")]))
        self.assertEqual(len(created), 1)

    def test_wrong_can_mute_the_rule_in_the_same_press(self):
        created = findings_store.add_many(triage.gate([
            row("check:dev.frozen", 1), row("check:dev.frozen", 2)]))
        payload = self.post(f"/api/finding/{created[0]['ts']}/wrong",
                            {"note": "that one never moves", "mute": True})
        # The row pressed got its ending — settled, taught, undoable —
        # and the rule took the other row with it, counted.
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["also_cleared"], 1)
        self.assertIn("undo", payload)
        self.assertEqual(len(findings_store.settled_listing()), 1)
        self.assertTrue(any("never moves" in line for line in self.queued_memory()))
        self.assertEqual([m["source"] for m in payload["muted"]],
                         ["check:dev.frozen"])

    def test_wrong_without_the_box_mutes_nothing(self):
        created = findings_store.add_many(triage.gate([
            row("check:dev.frozen", 1), row("check:dev.frozen", 2)]))
        payload = self.post(f"/api/finding/{created[0]['ts']}/wrong", {})
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(payload.get("muted", []), [])

    def test_a_press_with_no_producer_named_is_refused(self):
        async def run(client):
            res = await client.post("/api/findings/mute", json={})
            self.assertEqual(res.status, 400)
        self.drive(run)

    def test_the_diagnostics_say_which_producers_are_off(self):
        self.post("/api/findings/mute", {"source": "check:dev.frozen"})
        server = importlib.import_module("server")
        diag = server._diagnostics_payload()
        self.assertEqual(diag["findings"]["muted"], ["check:dev.frozen"])


if __name__ == "__main__":
    unittest.main()
