"""Overnight healing: a refused sign-in is not reloaded, and every heal is
on the action ledger.

A house reported a nightly reload of a config entry whose setup error was
"HTTP 403" — a refused credential, which a reload re-sends and cannot
clear — and the reload never showed under get_activity's "brain" cause,
because healing calls Core and the Supervisor directly rather than through
the MCP chokepoint that writes `/config/.brain/actions.jsonl`.

The planner is driven for real over a snapshot, and the ledger row is read
back with the real `actions.read_ledger` and attributed with the real
`actions.mine`, because a row shape written down twice is a shape that
drifts.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions  # noqa: E402
import healing  # noqa: E402
from checks import system as sys_checks  # noqa: E402
from test_healing import NOW, PerformCase, finding, house, zwave_finding  # noqa: E402


def entry_finding() -> dict:
    return finding(ts=int(NOW * 1000) + 2, text=sys_checks.ENTRY_FAILED_TEXT,
                   source="check:sys.entry_failed")


def entries(*rows) -> list[dict]:
    return [{"entry_id": eid, "domain": dom, "title": title,
             "state": "setup_error", "source": "user", "reason": reason}
            for eid, dom, title, reason in rows]


def plan(snap, rows=None):
    return healing.plan(rows or [entry_finding()], snap, [], set(),
                        healing.MAX_PER_NIGHT, NOW)


class TestARefusedSignInIsNotReloaded(unittest.TestCase):

    def test_a_403_is_skipped_with_its_reason(self):
        snap = house(config_entries=entries(
            ("hue1", "hue", "Hue bridge", "Error fetching data: HTTP 403")))
        out = plan(snap)
        self.assertEqual(out["attempts"], [])
        self.assertEqual(len(out["skips"]), 1, out)
        why = out["skips"][0]["reason"]
        self.assertIn("refused", why)
        self.assertIn("403", why)
        self.assertIn("Hue bridge", why)

    def test_a_403_inside_an_html_page_is_skipped(self):
        page = ("Unexpected response <!DOCTYPE html><html><head>"
                "<title>403 Forbidden</title></head><body>")
        snap = house(config_entries=entries(("hue1", "hue", "Hue", page)))
        self.assertEqual(plan(snap)["attempts"], [])

    def test_the_obvious_auth_words_are_refusals(self):
        for reason in ("401 Client Error", "Unauthorized",
                       "Invalid authentication", "Authentication failed",
                       "invalid API key", "Access denied"):
            snap = house(config_entries=entries(("hue1", "hue", "Hue", reason)))
            self.assertEqual(plan(snap)["attempts"], [], reason)

    def test_a_connection_failure_is_still_reloaded(self):
        for reason in ("Cannot connect", "Timeout while connecting",
                       "HTTP 500 Internal Server Error", "", "Error 4031 seen"):
            snap = house(config_entries=entries(("hue1", "hue", "Hue", reason)))
            out = plan(snap)
            self.assertEqual(len(out["attempts"]), 1, (reason, out))
            self.assertEqual(out["attempts"][0]["data"], {"entry_id": "hue1"})

    def test_a_refused_entry_does_not_hide_one_that_can_be_reloaded(self):
        snap = house(config_entries=entries(
            ("aaa", "nest", "Nest", "HTTP 403"),
            ("hue1", "hue", "Hue bridge", "Cannot connect")))
        out = plan(snap)
        self.assertEqual(len(out["attempts"]), 1, out)
        self.assertEqual(out["attempts"][0]["data"], {"entry_id": "hue1"})


class TestEveryHealIsOnTheLedger(PerformCase):

    def read(self):
        return actions.read_ledger(0, healing.LEDGER_FILE)

    async def test_a_reload_is_attributed_to_brain(self):
        snap = house()
        snap["entities"].append({"entity_id": "light.hue_lounge",
                                 "device_id": "d4", "platform": "hue",
                                 "config_entry_id": "hue1"})
        _plan, results = await self.one([entry_finding()], snap)
        self.assertEqual(results, [(True, "")])
        rows = self.read()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual((row["domain"], row["service"]),
                         ("homeassistant", "reload_config_entry"))
        self.assertEqual(row["channel"], healing.LEDGER_CHANNEL)
        self.assertIn("light.hue_lounge", row["entities"])
        self.assertEqual(row["target"], {"entry_id": "hue1"})
        # The timeline's own join: a change on an entity the reload owned,
        # seconds after it, is brAIn's.
        mined = actions.mine(
            [{"entity_id": "light.hue_lounge", "state": "on",
              "when": row["ts"] + 2, "name": "Lounge"}], {}, rows)
        self.assertEqual(mined["actions"][0]["cause"], "brain")

    async def test_a_ping_is_on_the_ledger(self):
        await self.one([zwave_finding()])
        rows = self.read()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["domain"], rows[0]["service"]),
                         ("zwave_js", "ping"))
        self.assertIn("sensor.front_lock_node_status", rows[0]["entities"])
        self.assertEqual(rows[0]["channel"], "healing")

    async def test_an_addon_start_is_on_the_ledger(self):
        await self.one([finding()])
        rows = self.read()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual((rows[0]["domain"], rows[0]["service"]),
                         ("hassio", "addon_start"))
        self.assertEqual(rows[0]["target"], {"addon": "core_mosquitto"})

    async def test_a_missing_directory_writes_nothing_and_heals_anyway(self):
        gone = Path(self._ledger_dir.name) / "no" / "such" / "actions.jsonl"
        healing.LEDGER_FILE = str(gone)
        _plan, results = await self.one([finding()])
        self.assertEqual(results, [(True, "")])
        self.assertFalse(gone.parent.exists())

    async def test_a_ledger_that_cannot_be_built_never_fails_the_heal(self):
        old = healing.ledger_row

        def boom(*a, **k):
            raise RuntimeError("no")
        healing.ledger_row = boom
        try:
            _plan, results = await self.one([finding()])
        finally:
            healing.ledger_row = old
        self.assertEqual(results, [(True, "")])


class TestTheRowShape(unittest.TestCase):

    def test_it_is_the_panel_s_shared_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "actions.jsonl")
            healing.record_ledger({"kind": "service", "domain": "zwave_js",
                                   "service": "ping",
                                   "data": {"entity_id": "sensor.x"},
                                   "entities": ["sensor.x"]}, path)
            rows = actions.read_ledger(0, path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]) - {"target"},
                         {"ts", "domain", "service", "entities", "channel"})

    def test_an_unknown_kind_writes_nothing(self):
        self.assertIsNone(healing.ledger_row({"kind": "telepathy"}))


if __name__ == "__main__":
    unittest.main()
