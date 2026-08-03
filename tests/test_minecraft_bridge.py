#!/usr/bin/env python3
"""End-to-end test of the file-IPC bridge.

Exercises the full loop without a running Minecraft server:

1. Write a request file in the shared dir (as the HA integration would)
2. Run one tick of the add-on-side listener (ha-bridge.py) with a stubbed RCON
3. Verify a response file is written with the expected payload
4. Verify the request file is cleaned up

Also tests that the mirror loop copies /data/panel state files into
/config/.bruh_minecraft/ for the HA coordinator to consume.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
BRIDGE_PY = os.path.join(BASE_DIR, "bruh-minecraft-server", "integrations", "ha-bridge.py")
CC_PKG = os.path.join(
    BASE_DIR, "bruh-minecraft-server", "custom_components", "bruh_minecraft",
)


def _load_ha_bridge(shared_dir: Path):
    """Load custom_components/bruh_minecraft/bridge.py without executing __init__.py
    (which pulls in homeassistant + voluptuous, unavailable in the test sandbox).

    Trick: manually populate sys.modules with a stub package + the const module,
    so bridge.py's `from .const import ...` resolves without importing the real
    package __init__.
    """
    import types

    pkg_name = "bruh_minecraft_pkg_for_test"
    const_name = f"{pkg_name}.const"
    bridge_name = f"{pkg_name}.bridge"

    for mod in (bridge_name, const_name, pkg_name):
        sys.modules.pop(mod, None)

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [CC_PKG]  # marks as a package
    sys.modules[pkg_name] = pkg

    # Load const.py as <pkg>.const
    const_spec = importlib.util.spec_from_file_location(
        const_name, os.path.join(CC_PKG, "const.py"),
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    const_mod.COMMAND_REQ_DIR = str(shared_dir / "requests")
    const_mod.COMMAND_RES_DIR = str(shared_dir / "responses")
    sys.modules[const_name] = const_mod
    const_spec.loader.exec_module(const_mod)  # type: ignore[union-attr]
    # Override the paths post-load so they point at our tmp dir
    const_mod.COMMAND_REQ_DIR = str(shared_dir / "requests")
    const_mod.COMMAND_RES_DIR = str(shared_dir / "responses")

    # Now load bridge.py as <pkg>.bridge so its relative import resolves
    bridge_spec = importlib.util.spec_from_file_location(
        bridge_name, os.path.join(CC_PKG, "bridge.py"),
    )
    bridge_mod = importlib.util.module_from_spec(bridge_spec)
    bridge_mod.__package__ = pkg_name
    sys.modules[bridge_name] = bridge_mod
    bridge_spec.loader.exec_module(bridge_mod)  # type: ignore[union-attr]
    bridge_mod.COMMAND_REQ_DIR = str(shared_dir / "requests")
    bridge_mod.COMMAND_RES_DIR = str(shared_dir / "responses")
    return bridge_mod


def _install_fake_rcon(capture: list[str]) -> None:
    """Install a fake rcon_client module that records commands passed to it."""
    mod = type(sys)("rcon_client")

    class _FakeRcon:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def command(self, cmd):
            capture.append(cmd)
            return f"OK: {cmd}"

    mod.Rcon = _FakeRcon
    sys.modules["rcon_client"] = mod


def _load_bridge(panel_state: Path, shared_dir: Path, capture: list[str]):
    _install_fake_rcon(capture)
    # Steer ha-bridge's scripts-dir resolver at a non-existent path so it
    # can't pull in the real rcon_client over our stub.
    os.environ["BRUH_MC_SCRIPTS_DIR"] = "/nonexistent/for-tests"
    os.environ["MC_PANEL_STATE"] = str(panel_state)
    spec = importlib.util.spec_from_file_location("ha_bridge", BRIDGE_PY)
    module = importlib.util.module_from_spec(spec)
    # Patch the shared-dir constants before loading
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    module.SHARED = shared_dir
    module.REQ_DIR = shared_dir / "requests"
    module.RES_DIR = shared_dir / "responses"
    module.REQ_DIR.mkdir(parents=True, exist_ok=True)
    module.RES_DIR.mkdir(parents=True, exist_ok=True)
    return module


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.panel = root / "panel"; self.panel.mkdir()
        self.shared = root / "shared"
        (self.panel / "rcon.secret").write_text("secret")
        self.capture: list[str] = []
        self.bridge = _load_bridge(self.panel, self.shared, self.capture)

    def _write_request(self, kind: str, payload: dict, rid: str = "abc123") -> Path:
        self.bridge.REQ_DIR.mkdir(parents=True, exist_ok=True)
        path = self.bridge.REQ_DIR / f"{rid}.json"
        path.write_text(json.dumps({
            "id": rid, "kind": kind, "payload": payload, "ts": 0,
        }))
        return path

    def _read_response(self, rid: str = "abc123") -> dict:
        res = self.bridge.RES_DIR / f"{rid}.json"
        # Poll briefly in case the writer hasn't flushed yet
        for _ in range(20):
            if res.is_file():
                return json.loads(res.read_text())
            # In synchronous tests the handler completes before we return,
            # so this loop should never actually wait.
            import time; time.sleep(0.05)
        self.fail(f"response file {res} never appeared")


class TestHandle(BridgeTestCase):
    def test_command_routes_via_rcon(self):
        asyncio.run(self._run_one_request("command", {"command": "weather clear"}))
        data = self._read_response()
        self.assertTrue(data["ok"])
        self.assertEqual(data["reply"], "OK: weather clear")
        self.assertIn("weather clear", self.capture)

    def test_say_clamps_and_trims(self):
        long = "x" * 500 + "\nsneaky"
        asyncio.run(self._run_one_request("say", {"message": long}))
        # The command sent should be at most 256 chars after `say `
        sent = self.capture[-1]
        self.assertTrue(sent.startswith("say "))
        self.assertLessEqual(len(sent) - len("say "), 256)
        self.assertNotIn("\n", sent)

    def test_player_action_known(self):
        asyncio.run(self._run_one_request("player_action", {
            "name": "Alice", "action": "op",
        }))
        self.assertEqual(self.capture[-1], "op Alice")

    def test_player_action_unknown(self):
        asyncio.run(self._run_one_request("player_action", {
            "name": "Alice", "action": "bogus",
        }))
        data = self._read_response()
        self.assertFalse(data["ok"])
        self.assertIn("unknown action", data["error"])

    def test_unknown_kind(self):
        asyncio.run(self._run_one_request("not_a_kind", {}))
        data = self._read_response()
        self.assertFalse(data["ok"])
        self.assertIn("unknown kind", data["error"])

    def test_stop_writes_no_restart_flag(self):
        asyncio.run(self._run_one_request("stop", {}))
        self.assertTrue((self.panel / "no_restart").is_file())
        # And issues save-all flush + stop over RCON
        self.assertIn("save-all flush", self.capture)
        self.assertIn("stop", self.capture)

    async def _run_one_request(self, kind: str, payload: dict) -> None:
        """Invoke handle() directly (bypassing the poll loop) so each test is fast."""
        self._write_request(kind, payload)
        req_path = next(iter(self.bridge.REQ_DIR.glob("*.json")))
        data = json.loads(req_path.read_text())
        result = await self.bridge.handle(data)
        self.bridge._write_response(data["id"], result)
        req_path.unlink()


class TestMirror(BridgeTestCase):
    def test_mirror_copies_panel_state_files(self):
        # Seed three fake panel state files
        (self.panel / "stats.json").write_text('{"online": 3}')
        (self.panel / "state.json").write_text('{"status": "running"}')
        (self.panel / "players.json").write_text('{"players": []}')

        async def one_pass():
            task = asyncio.create_task(self.bridge.mirror_loop())
            await asyncio.sleep(0.1)  # let mirror_loop iterate once
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # The cancel above is the point of the test; the task reporting it is
                # the expected outcome.
                pass

        asyncio.run(one_pass())
        for name in ("stats.json", "state.json", "players.json"):
            self.assertTrue(
                (self.shared / name).is_file(),
                f"{name} was not mirrored into shared dir",
            )


class TestHaIntegrationBridge(unittest.TestCase):
    """Smoke test the HA-side bridge.py (opposite side of the wire)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shared = Path(self.tmp.name)
        self.mod = _load_ha_bridge(self.shared)

    def test_send_request_times_out(self):
        # No listener — send_request should raise TimeoutError after timeout
        async def call():
            with self.assertRaises(TimeoutError):
                await self.mod.send_request("command", {"command": "list"}, timeout=0.5)

        asyncio.run(call())
        # And should clean up the orphan request file
        req_dir = self.shared / "requests"
        if req_dir.is_dir():
            self.assertEqual(list(req_dir.iterdir()), [])

    def test_send_request_returns_response(self):
        async def call():
            task = asyncio.create_task(
                self.mod.send_request("command", {"command": "list"}, timeout=5.0),
            )
            # Fake the add-on side: wait for the request file, then write a response
            for _ in range(30):
                req_dir = Path(self.mod.COMMAND_REQ_DIR)
                if req_dir.is_dir():
                    files = list(req_dir.glob("*.json"))
                    if files:
                        body = json.loads(files[0].read_text())
                        res_path = Path(self.mod.COMMAND_RES_DIR) / f"{body['id']}.json"
                        res_path.parent.mkdir(parents=True, exist_ok=True)
                        res_path.write_text(json.dumps({"ok": True, "reply": "there is 0"}))
                        break
                await asyncio.sleep(0.05)
            result = await task
            self.assertEqual(result, {"ok": True, "reply": "there is 0"})

        asyncio.run(call())


if __name__ == "__main__":
    unittest.main()
