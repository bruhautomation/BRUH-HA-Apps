#!/usr/bin/env python3
"""`/api/activity` still answers with the mined rows when a caller asks.

The MCP tool `get_activity` reads `/api/activity?hours=..&limit=..` and
returns its `total` and `actions` keys. The route moved to episode
`sections` for the Timeline and stopped sending either, so the tool
answered with counts beside an empty list and a total of 0 — "nothing
happened" about a house where plenty did. The Timeline never sends
`limit`, so a request carrying one is the tool's, and gets the rows:
newest first, narrowed by `cause`, capped by `limit` (default 200, at
most 1000). Driven through the real route over a real client.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from test_episodes import NOW, _TabHarness, act  # noqa: E402


class TestTheToolGetsItsRows(_TabHarness):
    def get(self, query: str) -> dict:
        async def body(client):
            res = await client.get("/api/activity" + query)
            self.assertEqual(res.status, 200)
            return await res.json()
        return self.drive(body)

    def test_rows_and_total_come_back_newest_first(self):
        data = self.get("?hours=24&limit=200")
        self.assertEqual(data["total"], len(self.rows))
        self.assertEqual(len(data["actions"]), len(self.rows))
        stamps = [r["ts"] for r in data["actions"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertIn("overrides", data)
        # The Timeline's own keys are untouched beside them.
        self.assertIn("sections", data)

    def test_cause_narrows_and_limit_caps(self):
        self.rows.append(act(5, "light.porch", "on", cause="automation",
                             by_name="Porch at dusk"))
        self.rows.append(act(6, "light.porch", "off", cause="person"))
        data = self.get("?hours=24&limit=200&cause=automation")
        self.assertEqual(data["total"], 1)
        self.assertEqual([r["entity_id"] for r in data["actions"]],
                         ["light.porch"])
        capped = self.get("?hours=24&limit=3")
        self.assertEqual(len(capped["actions"]), 3)
        self.assertEqual(capped["total"], len(self.rows))
        self.assertEqual(capped["actions"][0]["ts"], NOW + 10_800)

    def test_a_silly_limit_is_clamped(self):
        self.assertEqual(len(self.get("?limit=0")["actions"]), 1)
        self.assertLessEqual(len(self.get("?limit=99999")["actions"]), 1000)
        self.assertEqual(len(self.get("?limit=nope")["actions"]),
                         len(self.rows))

    def test_the_timeline_request_still_carries_no_rows(self):
        data = self.get("?hours=24")
        self.assertNotIn("actions", data)


if __name__ == "__main__":
    unittest.main()
