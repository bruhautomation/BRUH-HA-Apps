#!/usr/bin/env python3
"""Dismiss means the same thing on every surface.

The panel's Dismiss takes a card off the list and records nothing, so the
card comes back only if brAIn sees the problem again. A phone's Dismiss
used to close the notification and leave the card where it was, which
was one word meaning two things: *"I want it to dismiss the card in brAIn
too."* These drive the integration's real notification handler into the
add-on's real request reader, because the two processes cannot import
each other and a format written down twice drifts.
"""

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_ha_env as env  # noqa: E402
import finding_requests  # noqa: E402
from test_ha_service_gates import FakeHass  # noqa: E402


class TestAPhonesDismissIsARequest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pkg = env.load_integration()
        self.hass = FakeHass(Path(self.tmp.name))

    def press(self, action: str) -> list[dict]:
        handler = self.pkg._make_action_handler(self.hass)
        asyncio.run(handler(types.SimpleNamespace(data={"action": action})))
        drop = Path(self.hass.config.path(
            self.pkg.const.SHARED_DIR, self.pkg.const.FINDING_REQUESTS_DIRNAME))
        if not drop.is_dir():
            return []
        return [json.loads(p.read_text()) for p in sorted(drop.glob("*.json"))]

    def test_dismiss_on_a_notification_writes_the_panels_dismiss(self):
        [written] = self.press("brain.dismiss.1720")
        parsed = finding_requests.parse(written)
        self.assertEqual((parsed["ts"], parsed["action"], parsed["via"]),
                         (1720, "dismiss", "notification"))
        # It ends nothing in the ledger: it is no verb of the tab's.
        self.assertEqual(finding_requests.verb_for("dismiss"), "")

    def test_somebody_elses_button_still_writes_nothing(self):
        self.assertEqual(self.press("other.dismiss.1720"), [])


if __name__ == "__main__":
    unittest.main()
