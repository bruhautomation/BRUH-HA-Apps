#!/usr/bin/env python3
"""The Online sensor goes off while the server is down (#585).

It read `reachable` out of stats.json, which nothing rewrites once the add-on
has stopped - so a dead server stayed "on" for 3.5 hours. It now also needs
fresh stats and a state that is not "stopped".
"""
from __future__ import annotations

import ast
import os
import unittest

from test_minecraft_integration import PKG_DIR


def _source() -> str:
    with open(os.path.join(PKG_DIR, "binary_sensor.py"), encoding="utf-8") as fh:
        return fh.read()


def _load_helpers() -> dict:
    """binary_sensor.py needs Home Assistant to import, so lift just its pure
    helper (the constants and server_is_up) out of the source."""
    src = _source()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "server_is_up")
            or (isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") in ("STALE_AFTER_SECONDS", "DOWN_STATUSES")
                for t in n.targets))]
    ns: dict = {"time": __import__("time")}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "binary_sensor", "exec"), ns)
    return ns


class TestServerIsUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = type("M", (), _load_helpers())

    def up(self, stats, state, now=1000):
        return self.mod.server_is_up(stats, state, now=now)

    def test_running_with_fresh_stats_is_on(self):
        self.assertTrue(self.up({"reachable": True, "updated_at": 990}, {"status": "running"}))

    def test_reachable_but_stale_stats_is_off(self):
        # The collector writes every 15 s; nothing for minutes means it is gone.
        self.assertFalse(self.up({"reachable": True, "updated_at": 1000 - 3 * 3600},
                                 {"status": "running"}))

    def test_stopped_state_is_off_at_once(self):
        self.assertFalse(self.up({"reachable": True, "updated_at": 999}, {"status": "stopped"}))

    def test_not_reachable_is_off(self):
        self.assertFalse(self.up({"reachable": False, "updated_at": 999}, {"status": "running"}))

    def test_missing_state_or_timestamp_does_not_force_off(self):
        self.assertTrue(self.up({"reachable": True}, {}))

    def test_the_sensor_uses_it_for_online_and_rcon(self):
        src = _source()
        body = src[src.index("def is_on"):]
        self.assertIn("server_is_up(", body)


if __name__ == "__main__":
    unittest.main()
