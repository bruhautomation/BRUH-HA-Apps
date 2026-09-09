#!/usr/bin/env python3
"""A snapshot key is available when Core ANSWERED, not when nothing raised.

`ha_data._ws_commands` hands back None for a command Core refused and the
real answer otherwise — so a refused `recorder/statistics_during_period`
reached `collect` as None, was folded into `{}`, and the key was marked
available. `{}` is a recorder with no statistics for anything, and a
recorder with no statistics is a house whose every sensor is un-frozen
and every battery un-forecast: `clear_resolved` then deleted the rows the
previous pass had filed, on the evidence of a recorder that was down.

Every case here drives the real `collect` against a stubbed transport and
reads what `run_all` and the store do with the snapshot it produced,
because the claim is about the rows and not about a flag.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import actions  # noqa: E402
import checks  # noqa: E402
import findings_store  # noqa: E402
import ha_data  # noqa: E402

snapshot = checks.snapshot

NOW = 1_800_000_000.0

STATES = [
    {"entity_id": "sensor.hall_temp", "state": "21.4",
     "attributes": {"device_class": "temperature", "state_class": "measurement",
                    "unit_of_measurement": "°C", "friendly_name": "Hall"}},
    {"entity_id": "sensor.back_door_battery", "state": "88",
     "attributes": {"device_class": "battery", "state_class": "measurement",
                    "unit_of_measurement": "%", "friendly_name": "Back door"}},
]


class Transport:
    """Core, as `collect` sees it: a WS command router and a REST GET.

    Each answer is configurable so a test can say "the recorder refused"
    (None) apart from "the recorder had nothing" ({}), which is the whole
    distinction under test.
    """

    def __init__(self, *, stats="empty", battery="empty", dashboards="empty"):
        self.stats, self.battery, self.dashboards = stats, battery, dashboards
        self.asked: list[dict] = []

    def _answer(self, cmd: dict):
        kind = cmd.get("type")
        if kind in ("config/area_registry/list", "config/device_registry/list",
                    "config/entity_registry/list", "config/auth/list",
                    "config_entries/get"):
            return []
        if kind == "recorder/statistics_during_period":
            battery = any("battery" in i for i in cmd.get("statistic_ids", []))
            mode = self.battery if battery else self.stats
            if mode == "refused":
                return None
            if mode == "rows":
                return {i: [{"start": (NOW - 86400) * 1000, "mean": 20.0,
                             "min": 19.0, "max": 21.0}]
                        for i in cmd["statistic_ids"]}
            return {}
        if kind == "lovelace/dashboards/list":
            return None if self.dashboards == "refused" else []
        if kind == "lovelace/config":
            return None  # an auto-generated Overview answers with an error
        return None  # zha/devices and anything this house does not have

    async def ws(self, session, commands):
        self.asked.extend(commands)
        return [self._answer(c) for c in commands]

    async def rest(self, session, path, timeout=30, params=None):
        if path == "/states":
            return [dict(s) for s in STATES]
        if path == "/services":
            return []
        raise RuntimeError(f"unexpected GET {path}")


async def _no_supervisor(session):
    return {"backups": [], "addons": [], "host": {}, "core": {}}


async def _no_actions(session, start, end, users):
    return {"available": False, "actions": [], "overrides": [], "counts": {}}


def collect_with(transport: Transport) -> dict:
    old = (ha_data._ws_commands, ha_data._rest_get, snapshot._supervisor,
           actions.collect)
    ha_data._ws_commands = transport.ws
    ha_data._rest_get = transport.rest
    snapshot._supervisor = _no_supervisor
    actions.collect = _no_actions
    try:
        return asyncio.run(snapshot.collect(NOW))
    finally:
        (ha_data._ws_commands, ha_data._rest_get, snapshot._supervisor,
         actions.collect) = old


class TestTheShapeOfTheAnswerIsTheAvailability(unittest.TestCase):

    def test_a_refused_statistics_command_is_unavailable(self):
        snap = collect_with(Transport(stats="refused", battery="refused"))
        self.assertIs(snap["available"]["stats"], False)
        self.assertIs(snap["available"]["battery_stats"], False)
        self.assertIn("recorder", snap["errors"]["stats"])
        self.assertIn("recorder", snap["errors"]["battery_stats"])
        # and the keys still exist, empty, so nothing downstream KeyErrors
        self.assertEqual((snap["stats"], snap["battery_stats"]), ({}, {}))

    def test_a_recorder_with_nothing_to_say_is_available(self):
        """`{}` is an answer. A house whose sensors have no long-term
        statistics yet has been looked at, and the checks may run."""
        snap = collect_with(Transport(stats="empty", battery="empty"))
        self.assertIs(snap["available"]["stats"], True)
        self.assertIs(snap["available"]["battery_stats"], True)

    def test_the_two_windows_fail_separately(self):
        """One try block used to cover both, so a battery window that
        failed blanked the daily statistics beside it."""
        snap = collect_with(Transport(stats="rows", battery="refused"))
        self.assertIs(snap["available"]["stats"], True)
        self.assertIn("sensor.hall_temp", snap["stats"])
        self.assertIs(snap["available"]["battery_stats"], False)

    def test_a_refused_dashboard_list_is_unavailable(self):
        snap = collect_with(Transport(dashboards="refused"))
        self.assertIs(snap["available"]["dashboards"], False)
        self.assertEqual(snap["dashboards"], [])

    def test_a_house_with_no_storage_dashboards_is_available(self):
        """An empty list is the ordinary answer on a house that only has
        the auto-generated Overview, and it must not read as a failure."""
        snap = collect_with(Transport(dashboards="empty"))
        self.assertIs(snap["available"]["dashboards"], True)
        self.assertEqual(snap["dashboards"], [])


class TestAnUnavailableKeyClearsNothing(unittest.TestCase):
    """The consequence, through the real store: rows filed by the checks
    that need these keys survive a pass in which Core refused them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        root = Path(self.tmp.name)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "config" / ".brain" / "state.json"
        for source in ("check:dev.frozen", "check:forecast.battery",
                       "check:org.dashboard_dead_ref"):
            findings_store.add(f"Planted by {source}", source=source,
                               source_title="Check")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def _pass(self, snap):
        result = checks.run_all(snap, NOW)
        cleared = findings_store.clear_resolved(
            {checks.source_for(c) for c in result["ran"]},
            {findings_store.normalize(f["text"]) for f in result["findings"]})
        return result, cleared

    def test_refused_keys_keep_the_rows_that_need_them(self):
        snap = collect_with(Transport(stats="refused", battery="refused",
                                      dashboards="refused"))
        result, cleared = self._pass(snap)
        for cid in ("dev.frozen", "forecast.battery", "org.dashboard_dead_ref"):
            self.assertNotIn(cid, result["ran"], cid)
        self.assertEqual(cleared, [])
        self.assertEqual(len(findings_store.list_all("open")), 3)

    def test_answered_keys_let_the_same_rows_clear(self):
        """The control: the same pass with Core answering. `{}` from the
        recorder is a house with nothing frozen and nothing draining, and
        an empty dashboard list is a house with nothing dead on one."""
        snap = collect_with(Transport(stats="empty", battery="empty",
                                      dashboards="empty"))
        result, cleared = self._pass(snap)
        for cid in ("dev.frozen", "forecast.battery", "org.dashboard_dead_ref"):
            self.assertIn(cid, result["ran"], cid)
        self.assertEqual(len(cleared), 3)
        self.assertEqual(findings_store.list_all("open"), [])


class TestTheHelpersSayWhichItWas(unittest.TestCase):
    """The distinction lives in the helper's return value, so a caller
    that reads it wrong is a caller that can be pointed at."""

    def _ws(self, answer):
        async def ws(session, commands):
            return [answer for _ in commands]
        return ws

    def _fetch(self, answer, ids=("sensor.a",)):
        old = ha_data._ws_commands
        ha_data._ws_commands = self._ws(answer)
        try:
            return asyncio.run(snapshot._fetch_stats(
                None, list(ids), NOW, 7, ["mean"]))
        finally:
            ha_data._ws_commands = old

    def test_refused_is_none_and_empty_is_empty(self):
        self.assertIsNone(self._fetch(None))
        self.assertEqual(self._fetch({}), {})

    def test_nothing_to_ask_is_an_empty_answer_not_a_refusal(self):
        """No ids means no command was sent, and a command that was never
        sent cannot have been refused."""
        self.assertEqual(self._fetch(None, ids=()), {})

    def test_dashboards_refused_is_none(self):
        old = ha_data._ws_commands
        ha_data._ws_commands = self._ws(None)
        try:
            self.assertIsNone(asyncio.run(snapshot._dashboards(None)))
        finally:
            ha_data._ws_commands = old


if __name__ == "__main__":
    unittest.main()
