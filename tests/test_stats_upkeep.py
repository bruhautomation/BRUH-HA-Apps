#!/usr/bin/env python3
"""Home Assistant's long-term statistics, kept healthy by brAIn (#576).

The owner: they do not want to click every "Fix issue" button on Home
Assistant's Repairs page for statistics issues; brAIn should fix and clean
those up itself. What an unattended pass may do is the whole question, so
every rule here is driven over `recorder/validate_statistics`' own answer
shape (Core's `ValidationIssue.as_dict`, `{type, data}` per statistic):

  * a unit change whose live sensor agrees is fixed without touching a row
    of history, and carries the exact command that puts it back;
  * a statistic is deleted on a schedule only when the registry says its
    entity is gone or disabled — an enabled entity with no state yet is a
    restart, and an unreadable registry is "could not tell";
  * a live sensor's history is never deleted: it is one question;
  * an entity the recorder excludes on purpose is never touched or asked
    about, nor is a protected one, nor one whose fix the owner undid;
  * the pass validates again and records whether each fix held, History
    lists every change, and only a unit fix carries an Undo.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import changes  # noqa: E402
import stats_upkeep  # noqa: E402

NOW = 1_800_000_000.0
NAMES = {"sensor.boiler_energy": {"name": "Boiler energy"},
         "sensor.attic_temp": {"name": "Attic temperature"},
         "sensor.cellar_power": {"name": "Cellar power"}}


def state(eid, unit=None, state_class="measurement"):
    attrs = {}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    if state_class:
        attrs["state_class"] = state_class
    return {"entity_id": eid, "state": "12", "attributes": attrs}


def units(eid, state_unit="kWh", metadata_unit="Wh"):
    return {eid: [{"type": "units_changed", "data": {
        "statistic_id": eid, "state_unit": state_unit,
        # No shared unit class: nothing converts one into the other, which
        # is the only kind of unit change fixed unattended (the review of
        # #576; a Wh → kWh relabel is `test_stats_upkeep_review`'s).
        "state_unit_class": None, "metadata_unit": metadata_unit,
        "metadata_unit_class": None, "supported_unit": metadata_unit}}]}


def issue(eid, kind):
    return {eid: [{"type": kind, "data": {"statistic_id": eid}}]}


def plan(result, states, registry=(), **kw):
    # Core fully started, and a removed sensor already seen missing hours
    # ago, unless a test says otherwise.
    kw.setdefault("core_state", "RUNNING")
    kw.setdefault("now", NOW)
    kw.setdefault("missing", {"sensor.old_meter": NOW - 7 * 3600})
    return stats_upkeep.plan(stats_upkeep.issues_from(result), states,
                             list(registry) if registry is not None else None,
                             **kw)


class TestWhatAPassMayDoAlone(unittest.TestCase):
    def test_a_unit_change_is_fixed_without_touching_history(self):
        out = plan(units("sensor.boiler_energy"),
                   [state("sensor.boiler_energy", "kWh")])
        self.assertEqual(len(out["fix"]), 1)
        fix = out["fix"][0]
        self.assertEqual(fix["command"], {
            "type": "recorder/update_statistics_metadata",
            "statistic_id": "sensor.boiler_energy", "unit_class": None,
            "unit_of_measurement": "kWh"})
        # The undo is the same call with what the statistics had.
        self.assertEqual(fix["undo"]["unit_of_measurement"], "Wh")
        self.assertEqual(out["clear"], [])
        self.assertEqual(out["ask"], [])

    def test_a_second_unit_change_waits_for_the_live_sensor_to_agree(self):
        # A sensor mid-restart briefly reports no unit, or another unit:
        # relabelling the history on that would be acting on a glitch.
        out = plan(units("sensor.cellar_power", "kW", "W"),
                   [state("sensor.cellar_power", "W")])
        self.assertEqual(out["fix"], [])
        out = plan(units("sensor.cellar_power", None, "W"),
                   [state("sensor.cellar_power")])
        self.assertEqual(out["fix"], [])
        self.assertEqual(len(out["leave"]), 1)

    def test_a_removed_or_disabled_entity_is_cleared(self):
        result = {**issue("sensor.old_meter", "no_state"),
                  **issue("sensor.off_meter", "no_state")}
        out = plan(result, [], registry=[
            {"entity_id": "sensor.off_meter", "disabled_by": "user"}])
        cleared = {c["statistic_id"]: c for c in out["clear"]}
        self.assertEqual(set(cleared), {"sensor.old_meter", "sensor.off_meter"})
        self.assertEqual(cleared["sensor.old_meter"]["gone"], "removed")
        self.assertEqual(cleared["sensor.off_meter"]["gone"], "disabled")
        self.assertEqual(cleared["sensor.old_meter"]["command"], {
            "type": "recorder/clear_statistics",
            "statistic_ids": ["sensor.old_meter"]})

    def test_an_entity_that_has_not_loaded_yet_is_never_cleared(self):
        out = plan(issue("sensor.slow_meter", "no_state"), [], registry=[
            {"entity_id": "sensor.slow_meter", "disabled_by": None}])
        self.assertEqual(out["clear"], [])
        # A registry that could not be read is "could not tell".
        out = plan(issue("sensor.slow_meter", "no_state"), [], registry=None)
        self.assertEqual(out["clear"], [])
        # And one reporting again is not gone, whatever the issue said.
        out = plan(issue("sensor.slow_meter", "no_state"),
                   [state("sensor.slow_meter", "W")])
        self.assertEqual(out["clear"], [])


class TestALiveSensorsHistoryIsAsked(unittest.TestCase):
    def test_state_class_removed_is_a_question_never_a_clear(self):
        out = plan(issue("sensor.attic_temp", "state_class_removed"),
                   [state("sensor.attic_temp", "°C", state_class=None)])
        self.assertEqual(out["clear"], [])
        self.assertEqual(out["fix"], [])
        self.assertEqual([a["statistic_id"] for a in out["ask"]],
                         ["sensor.attic_temp"])

    def test_a_mean_type_change_is_asked_too(self):
        out = plan(issue("sensor.cellar_power", "mean_type_changed"),
                   [state("sensor.cellar_power", "W")])
        self.assertEqual(out["clear"], [])
        self.assertEqual(len(out["ask"]), 1)

    def test_the_question_names_things_and_asks_once(self):
        asks = plan({**issue("sensor.attic_temp", "state_class_removed"),
                     **issue("sensor.cellar_power", "mean_type_changed")},
                    [state("sensor.attic_temp", "°C", None),
                     state("sensor.cellar_power", "W")])["ask"]
        row = stats_upkeep.ask_row(asks, NAMES)
        self.assertEqual(row["kind"], "question")
        self.assertEqual(row["source"], stats_upkeep.SOURCE)
        for words in (row["text"], row["claim"]):
            self.assertIn("Attic temperature", words)
            self.assertIn("Cellar power", words)
            self.assertNotIn("sensor.", words)
        self.assertIsNone(stats_upkeep.ask_row([], NAMES))


class TestWhatIsLeftAlone(unittest.TestCase):
    def test_an_entity_excluded_on_purpose_is_never_flagged(self):
        result = {**issue("sensor.noisy", "entity_no_longer_recorded"),
                  **issue("sensor.chatty", "entity_not_recorded")}
        out = plan(result, [state("sensor.noisy", "W"),
                            state("sensor.chatty", "W")])
        self.assertEqual(out["fix"] + out["clear"] + out["ask"], [])
        self.assertEqual(len(out["leave"]), 2)

    def test_a_protected_entity_or_a_tripwire_is_never_touched(self):
        result = {**units("sensor.boiler_energy"),
                  **issue("sensor.old_meter", "no_state")}
        live = [state("sensor.boiler_energy", "kWh")]
        out = plan(result, live, patterns=["sensor.boiler_energy"],
                   tokens=["sensor.old_meter"])
        self.assertEqual(out["fix"] + out["clear"], [])
        out = plan(result, live, patterns=["*"])
        self.assertEqual(out["fix"] + out["clear"], [])

    def test_a_fix_the_owner_undid_is_never_made_again(self):
        out = plan(units("sensor.boiler_energy"),
                   [state("sensor.boiler_energy", "kWh")],
                   kept=[["sensor.boiler_energy", "units_changed"]])
        self.assertEqual(out["fix"], [])


class TestVerifiedAndListed(unittest.TestCase):
    def test_verify_says_which_fix_held(self):
        fixed = plan({**units("sensor.boiler_energy"),
                      **units("sensor.cellar_power", "kW", "W")},
                     [state("sensor.boiler_energy", "kWh"),
                      state("sensor.cellar_power", "kW")])["fix"]
        entries = [stats_upkeep.entry(f, ok=True, error="", at=NOW)
                   for f in fixed]
        after = stats_upkeep.issues_from(units("sensor.cellar_power", "kW", "W"))
        held = {e["statistic_id"]: e["held"]
                for e in stats_upkeep.verify(entries, after)}
        self.assertEqual(held, {"sensor.boiler_energy": True,
                                "sensor.cellar_power": False})

    def _store(self):
        out = plan({**units("sensor.boiler_energy"),
                    **issue("sensor.old_meter", "no_state")},
                   [state("sensor.boiler_energy", "kWh")])
        entries = [stats_upkeep.entry(a, ok=True, error="", at=NOW - 60)
                   for a in out["fix"] + out["clear"]]
        return {"changes": stats_upkeep.verify(entries, []), "kept": []}

    def test_history_lists_each_fix_and_only_a_unit_has_undo(self):
        rows = changes.build(journal=[], ledger=[], fixes=[], tidy_batches=[],
                             intents=[], accepted=[], names=NAMES,
                             mtime=lambda p: None, now=NOW,
                             stat_changes=self._store())
        by_kind = {("unit" if "unit" in r["title"] else "clear"): r
                   for r in rows}
        self.assertEqual(len(rows), 2)
        unit = by_kind["unit"]
        self.assertIn("Boiler energy", unit["title"])
        self.assertEqual(unit["where"], "routine upkeep")
        self.assertTrue(unit["press"]["steps"][0]["route"].startswith(
            "/api/statistics/undo/"))
        clear = by_kind["clear"]
        self.assertIsNone(clear["press"])
        self.assertIn("cannot be put back", clear["reason"])
        for row in rows:
            self.assertNotIn("sensor.", row["title"])

    def test_undo_keeps_the_statistic_from_being_fixed_again(self):
        store = self._store()
        cid = next(c["id"] for c in store["changes"] if c["action"] == "unit")
        self.assertIn(cid, stats_upkeep.undoable(store))
        stats_upkeep.mark_undone(store, cid, NOW)
        self.assertNotIn(cid, stats_upkeep.undoable(store))
        out = plan(units("sensor.boiler_energy"),
                   [state("sensor.boiler_energy", "kWh")], kept=store["kept"])
        self.assertEqual(out["fix"], [])


class TestWhenAPassRuns(unittest.TestCase):
    def test_daily_after_a_start_and_after_a_core_update(self):
        store = {"last_run": NOW - 3600, "core_version": "2026.10.1"}
        self.assertFalse(stats_upkeep.due(store, NOW, core_version="2026.10.1"))
        self.assertTrue(stats_upkeep.due(store, NOW, core_version="2026.11.0"))
        self.assertTrue(stats_upkeep.due(store, NOW, booted=True))
        self.assertTrue(stats_upkeep.due(store, NOW + 86400))


class TestThePassAgainstCore(unittest.TestCase):
    """`server._run_statistics` over a fake recorder: the calls it makes,
    in order, the question it files, and the store it leaves."""

    def setUp(self):
        self.server = importlib.import_module("server")
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (stats_upkeep.STORE, self.server._stats_ws,
                      self.server._stats_states,
                      self.server.findings_store.add_case,
                      dict(self.server._NAMES))
        stats_upkeep.STORE = Path(self.tmp.name) / "stats.json"
        self.server._NAMES.clear()
        self.server._NAMES.update(NAMES)
        self.sent: list[dict] = []
        self.filed: list[dict] = []
        self.issues = {**units("sensor.boiler_energy"),
                       **issue("sensor.old_meter", "no_state"),
                       **issue("sensor.attic_temp", "state_class_removed"),
                       **issue("sensor.noisy", "entity_no_longer_recorded")}

        async def ws(commands):
            out = []
            for cmd in commands:
                self.sent.append(cmd)
                kind = cmd["type"]
                if kind == "recorder/validate_statistics":
                    out.append({"ok": True, "result": self.issues, "error": ""})
                elif kind == "config/entity_registry/list":
                    out.append({"ok": True, "result": [], "error": ""})
                elif kind == "get_config":
                    out.append({"ok": True, "result": {"state": "RUNNING"},
                                "error": ""})
                else:
                    if kind == "recorder/update_statistics_metadata":
                        self.issues.pop(cmd["statistic_id"], None)
                    if kind == "recorder/clear_statistics":
                        for sid in cmd["statistic_ids"]:
                            self.issues.pop(sid, None)
                    out.append({"ok": True, "result": None, "error": ""})
            return out

        async def states():
            return [state("sensor.boiler_energy", "kWh"),
                    state("sensor.attic_temp", "°C", None),
                    state("sensor.noisy", "W")]

        def add_case(row, **kw):
            self.filed.append(row)
            return {**row, "ts": 1}

        self.server._stats_ws = ws
        self.server._stats_states = states
        self.server.findings_store.add_case = add_case

    def tearDown(self):
        (stats_upkeep.STORE, self.server._stats_ws, self.server._stats_states,
         self.server.findings_store.add_case, names) = self.saved
        self.server._NAMES.clear()
        self.server._NAMES.update(names)
        self.tmp.cleanup()

    def test_one_pass_fixes_clears_asks_and_verifies(self):
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        # The removed meter was seen missing on a pass seven hours ago.
        stats_upkeep.save({"missing": {"sensor.old_meter": NOW - 7 * 3600}},
                          None, NOW)
        asyncio.run(self.server._run_statistics("schedule", now=NOW))
        kinds = [c["type"] for c in self.sent]
        self.assertEqual(kinds[:2], ["recorder/validate_statistics",
                                     "config/entity_registry/list"])
        self.assertIn("recorder/update_statistics_metadata", kinds)
        self.assertIn("recorder/clear_statistics", kinds)
        cleared = [c for c in self.sent
                   if c["type"] == "recorder/clear_statistics"]
        # The deleted meter only: never the live attic sensor's history.
        self.assertEqual(cleared[0]["statistic_ids"], ["sensor.old_meter"])
        self.assertEqual(len(cleared), 1)
        # Repairs refreshed, then validated again to verify.
        self.assertEqual(kinds[-2:], ["recorder/update_statistics_issues",
                                      "recorder/validate_statistics"])
        store = stats_upkeep.load()
        self.assertEqual({c["statistic_id"]: c["held"]
                          for c in store["changes"]},
                         {"sensor.boiler_energy": True,
                          "sensor.old_meter": True})
        self.assertEqual(len(self.filed), 1)
        self.assertIn("Attic temperature", self.filed[0]["text"])

        # The next pass asks nothing again about the same statistic.
        self.sent.clear()
        asyncio.run(self.server._run_statistics("schedule", now=NOW + 90000))
        self.assertEqual(len(self.filed), 1)
        self.assertNotIn("recorder/clear_statistics",
                         [c["type"] for c in self.sent])


if __name__ == "__main__":
    unittest.main()
