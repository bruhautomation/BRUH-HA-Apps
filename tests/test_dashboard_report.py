#!/usr/bin/env python3
"""`get_dashboard` says which dashboard it read, not which one you named.

Two defects, one function. It reported `url_path or "default"` — an echo of
the argument, which cannot tell "I asked for nothing and got the default"
from "I asked for a dashboard called default", and which names a token the
same tool then refuses: `lovelace/config` has never heard of "default", so
passing back what the answer printed came out as *Dashboard not found*. That
matters because the documented workflow is fetch, edit, save, and
`brain.update_dashboard` takes exactly that word for the default dashboard
(`power_tools._dashboard_key`) — a word one half of the pair hands out and
the other rejects breaks the round trip at its first step.

And the not-found branch claimed registration it had not checked: with the
dashboard list unreadable it still answered "registered but never saved",
which sends somebody to `take_control: true` on a dashboard that may not
exist. "I could not look" is not "it is there".
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
sys.path.insert(0, str(MCP_DIR))


class DashboardCase(unittest.TestCase):
    """Drives the real tool against a stub of Home Assistant's WS API."""

    @classmethod
    def setUpClass(cls):
        cls.mcp = importlib.import_module("ha_mcp_server")

    def setUp(self):
        self._real = self.mcp._ws_command
        self.asked = []

    def tearDown(self):
        self.mcp._ws_command = self._real

    def serve(self, configs, registered=None, list_fails=False):
        """`configs`: wire url_path (None for the default) -> its config."""
        def fake(message, timeout=None):
            self.asked.append(message)
            if message.get("type") == "lovelace/dashboards/list":
                if list_fails:
                    raise RuntimeError("websocket closed")
                return registered if registered is not None else []
            path = message.get("url_path")
            if path in configs:
                return configs[path]
            return {"error": "config_not_found"}

        self.mcp._ws_command = fake


class TestWhichDashboardYouGot(DashboardCase):
    def test_asking_for_nothing_names_the_default_rather_than_echoing(self):
        self.serve({None: {"title": "Home", "views": [{"title": "Downstairs"}]}})
        got = self.mcp.get_dashboard()
        self.assertTrue(got["is_default"])
        # The title HA actually returned, which is the half that makes a
        # wrong fetch visible in its own answer.
        self.assertEqual(got["dashboard"], "Home")
        self.assertEqual(got["config"]["views"][0]["title"], "Downstairs")

    def test_the_word_it_reports_is_a_word_it_accepts(self):
        """The round trip: fetch, read the url_path, fetch that.

        This is the bug as it was reported. The old answer printed
        "default" and the next call with it came back "Dashboard not
        found: default", because the literal went straight onto the wire.
        """
        self.serve({None: {"title": "Home", "views": []}},
                   registered=[{"url_path": "docs", "title": "Docs"}])
        # The old recipe, on this fixture, so the guard is measured against
        # a demonstrated failure rather than a described one: `url_path or
        # "default"` was reported and then put straight on the wire.
        echoed = None or "default"
        self.assertIn("error", self.mcp._ws_command(
            {"type": "lovelace/config", "url_path": echoed or None}))
        first = self.mcp.get_dashboard()
        again = self.mcp.get_dashboard(url_path=first["url_path"])
        self.assertNotIn("error", again)
        self.assertEqual(again["dashboard"], "Home")
        # And both of ITS calls asked for the default on the wire, which is
        # a null path — never the word. (The first entry is the old recipe
        # probed above, which is the one that was not found.)
        self.assertEqual([m.get("url_path") for m in self.asked
                          if m.get("type") == "lovelace/config"],
                         ["default", None, None])

    def test_a_named_dashboard_is_reported_by_its_own_title(self):
        self.serve({"docs": {"title": "Docs shots", "views": []}})
        got = self.mcp.get_dashboard(url_path="docs")
        self.assertEqual(got["url_path"], "docs")
        self.assertFalse(got["is_default"])
        self.assertEqual(got["dashboard"], "Docs shots")
        # And it cost one round trip: the title came out of the config that
        # was already on its way back. A name is worth having and it is not
        # worth a second call to Home Assistant on every dashboard read —
        # which is why a config with no title reports none (below) rather
        # than the tool going to look.
        self.assertEqual([m["type"] for m in self.asked], ["lovelace/config"])

    def test_a_view_fetch_and_an_oversize_summary_say_it_too(self):
        # Every exit reported the same echo, so every exit is checked: a
        # large dashboard is exactly the case somebody is paging through.
        big = {"title": "Home",
               "views": [{"title": f"V{n}", "cards": [{"x": "y" * 6000}]}
                         for n in range(40)]}
        self.serve({None: big})
        one = self.mcp.get_dashboard(view_index=2)
        self.assertEqual(one["dashboard"], "Home")
        self.assertEqual(one["url_path"], "default")
        self.assertEqual(one["view"]["title"], "V2")
        summary = self.mcp.get_dashboard()
        self.assertIn("too large", summary["note"])
        self.assertEqual(summary["dashboard"], "Home")
        self.assertEqual(summary["url_path"], "default")

    def test_a_dashboard_with_no_title_anywhere_still_reports_its_path(self):
        # `dashboard` is a name to recognise it by and HA does not always
        # have one; the token that fetches it again is the part that must
        # always be there.
        self.serve({"spare": {"views": []}}, registered=[{"url_path": "spare"}])
        got = self.mcp.get_dashboard(url_path="spare")
        self.assertEqual(got["url_path"], "spare")
        self.assertNotIn("dashboard", got)
        self.assertFalse(got["is_default"])


class TestTheNotFoundBranch(DashboardCase):
    def test_a_url_path_nobody_has_is_reported_as_missing(self):
        self.serve({None: {"views": []}},
                   registered=[{"url_path": "docs", "title": "Docs"}])
        got = self.mcp.get_dashboard(url_path="nope")
        self.assertIn("not found", got["error"])
        self.assertIn("docs", got["error"])

    def test_a_registered_dashboard_that_was_never_saved_says_so(self):
        self.serve({None: {"views": []}},
                   registered=[{"url_path": "fresh", "title": "Fresh"}])
        got = self.mcp.get_dashboard(url_path="fresh")
        self.assertIn("take_control", got["note"])
        self.assertEqual(got["url_path"], "fresh")
        self.assertEqual(got["dashboard"], "Fresh")

    def test_an_unreadable_list_is_not_evidence_that_it_is_registered(self):
        """The narrowing. Three answers, not two.

        With the list unreadable the old code fell through to "registered
        but has no stored config yet", which is a claim about a dashboard
        it had no way to check — and the remedy it named (take_control on
        a save) fails at the save for one that does not exist.
        """
        self.serve({None: {"views": []}}, list_fails=True)
        got = self.mcp.get_dashboard(url_path="maybe")
        self.assertIn("error", got)
        self.assertIn("unknown", got["error"])
        self.assertIn("list_dashboards", got["error"])
        self.assertNotIn("take_control", got.get("error", ""))

    def test_the_default_dashboard_never_needs_the_list_at_all(self):
        # It has no registry row of its own, so asking the list about it
        # could only ever answer "not found" about the one dashboard every
        # house has.
        self.serve({}, list_fails=True)
        got = self.mcp.get_dashboard()
        self.assertIn("take_control", got["note"])
        self.assertTrue(got["is_default"])
        self.assertEqual([m["type"] for m in self.asked], ["lovelace/config"])


class TestOneWordForTheDefault(unittest.TestCase):
    """The MCP tool and the service that edits what it fetched agree."""

    def test_the_token_is_the_one_update_dashboard_takes(self):
        mcp = importlib.import_module("ha_mcp_server")
        source = (BASE_DIR / "brain" / "custom_components" / "brain"
                  / "power_tools.py").read_text()
        # `_dashboard_key` maps this literal (and None) to the default
        # dashboard's storage key. Read out of the sibling rather than
        # written down twice.
        self.assertIn('if url_path in (None, "default"):', source)
        self.assertEqual(mcp.DEFAULT_DASHBOARD, "default")

    def test_the_wire_never_carries_the_word(self):
        mcp = importlib.import_module("ha_mcp_server")
        for spelling in (None, "", "default"):
            self.assertIsNone(mcp._dashboard_wire_path(spelling), spelling)
        self.assertEqual(mcp._dashboard_wire_path("docs"), "docs")


if __name__ == "__main__":
    unittest.main()
