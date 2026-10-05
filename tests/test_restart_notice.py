"""The integration a version behind the add-on: said once, and said in the
panel too.

The field walkthrough found add-on 2.11.1 beside integration 2.11.0, a
Repairs entry *and* a persistent notification saying the same thing, and
nothing in ⚙ → Diagnostics. Driven through the integration's real
`_check_restart_required` (loaded by `brain_ha_env`) into the panel's real
`_integration_versions` and `reports.faults`, because the file one writes
and the other reads is a wire format, and a shape written down twice with
only one side tested is a shape that drifts.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

TESTS = Path(__file__).resolve().parent
PANEL = TESTS.parent / "brain" / "panel"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(PANEL))

import brain_ha_env as env  # noqa: E402
import reports  # noqa: E402


class _Services:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data=None, **kw):
        self.calls.append((domain, service, dict(data or {})))


class _Hass:
    def __init__(self, base: Path):
        self.services = _Services()
        self.config = types.SimpleNamespace(
            path=lambda *parts: str(base.joinpath(*parts)))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestOneNoticeAndThePanelKnows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / ".brain").mkdir()
        self.pkg = env.load_integration()
        self.pkg.ir = MagicMock(name="issue_registry")
        self.pkg._LOADED_VERSION = "2.11.0"
        self.hass = _Hass(self.base)

    def _check(self):
        asyncio.run(self.pkg._check_restart_required(self.hass))

    def _panel_reads(self):
        server = importlib.import_module("server")
        old = server.INTEGRATION_LOADED_FILE, server.RESTART_MARKER_FILE
        server.INTEGRATION_LOADED_FILE = (
            self.base / ".brain" / "integration_loaded.json")
        server.RESTART_MARKER_FILE = self.base / ".brain" / "restart_required"
        try:
            return server._integration_versions()
        finally:
            server.INTEGRATION_LOADED_FILE, server.RESTART_MARKER_FILE = old

    def test_a_pending_restart_is_one_repairs_issue_and_no_notification(self):
        (self.base / ".brain" / "restart_required").write_text(
            json.dumps({"required_version": "2.11.1"}))
        self._check()
        self.pkg.ir.async_create_issue.assert_called_once()
        created = [c for c in self.hass.services.calls
                   if c[:2] == ("persistent_notification", "create")]
        self.assertEqual(created, [])
        # The duplicate an older release posted is taken down.
        self.assertIn(("persistent_notification", "dismiss",
                       {"notification_id": "brain_restart_needed"}),
                      self.hass.services.calls)

    def test_the_panel_reads_what_the_integration_wrote(self):
        (self.base / ".brain" / "restart_required").write_text(
            json.dumps({"required_version": "2.11.1"}))
        self._check()
        versions = self._panel_reads()
        self.assertEqual(versions, {"loaded": "2.11.0", "required": "2.11.1",
                                    "restart_pending": True})
        rows = reports.faults({"versions": {"addon": "2.11.1",
                                            "integration": versions}})
        said = " | ".join(f"{r['where']}: {r['what']} {r['detail']}"
                          for r in rows)
        self.assertIn("Home Assistant integration", said)
        self.assertIn("running v2.11.0; the add-on deployed v2.11.1", said)
        self.assertIn("Restart Home Assistant", said)

    def test_after_the_restart_there_is_nothing_to_say(self):
        self.pkg._LOADED_VERSION = "2.11.1"
        (self.base / ".brain" / "restart_required").write_text(
            json.dumps({"required_version": "2.11.1"}))
        self._check()
        versions = self._panel_reads()
        self.assertFalse(versions["restart_pending"])
        self.assertEqual(versions["loaded"], "2.11.1")
        self.assertEqual(reports.faults({"versions": {"integration": versions}}),
                         [])


if __name__ == "__main__":
    unittest.main()
