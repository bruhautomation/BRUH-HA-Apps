#!/usr/bin/env python3
"""Integration test for the ingress panel (panel/server.py).

Spins up the aiohttp app in-process with aiohttp's TestClient. The JVM is
never launched — we instead pre-populate the panel state dir with fixture
JSON files and stub out RCON calls. That exercises every read-only route and
the non-RCON write routes (properties edit, plugin delete, etc.).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server")
PANEL_SERVER_PY = os.path.join(ADDON_DIR, "panel", "server.py")


def _load_panel_module(server_dir: Path, backup_dir: Path, state_dir: Path):
    """Import panel/server.py with PATHS pointing at a tmp fixture dir."""
    # panel/server.py imports Rcon from scripts/rcon_client.py. Swap in a
    # lightweight stub so tests never open a TCP socket. We install the stub
    # under the real module name so the panel's `from rcon_client import Rcon`
    # picks it up; a previous test file may have installed its own stub, so
    # overwrite unconditionally.
    rcon_mod = type(sys)("rcon_client")

    class _FakeRcon:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def command(self, *a, **kw): return "ok"

    rcon_mod.Rcon = _FakeRcon
    sys.modules["rcon_client"] = rcon_mod
    # Also purge the panel module so it picks up the fresh stub
    sys.modules.pop("panel_server", None)

    # Point the panel's scripts-dir resolution at the repo checkout so its
    # fallback sys.path insert doesn't clobber our stub with the real module.
    os.environ["BRUH_MC_SCRIPTS_DIR"] = "/nonexistent/for-tests"
    os.environ["MC_SERVER_DIR"] = str(server_dir)
    os.environ["MC_BACKUP_DIR"] = str(backup_dir)
    os.environ["MC_PANEL_STATE"] = str(state_dir)
    os.environ["MC_CONSOLE_LOG"] = str(state_dir / "console.log")
    os.environ["MC_INPUT_FIFO"] = str(state_dir / "stdin.fifo")

    spec = importlib.util.spec_from_file_location("panel_server", PANEL_SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class PanelTestBase(AioHTTPTestCase):
    """Boot the aiohttp app against a tempdir-backed state."""

    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.server_dir = root / "server"; self.server_dir.mkdir()
        self.backup_dir = root / "backups"; self.backup_dir.mkdir()
        self.state_dir = root / "state";    self.state_dir.mkdir()
        (self.server_dir / "plugins").mkdir()
        # Seed fixture data for the status / players / server_meta endpoints
        (self.state_dir / "stats.json").write_text(json.dumps({
            "online": 2, "max_players": 20, "players": ["Alice", "Bob"],
            "tps_1m": 19.99, "tps_5m": 20.0, "tps_15m": 20.0, "latency_ms": 14.2,
            "reachable": True, "rcon_ok": True, "uptime_seconds": 1800,
            "version": "1.21.3", "motd": "Fixture MOTD",
        }))
        (self.state_dir / "state.json").write_text(json.dumps({
            "status": "running", "server_type": "paper", "memory_mb": 4096,
            "motd": "Fixture MOTD", "max_players": 20, "difficulty": "normal",
            "gamemode": "survival", "hardcore": False, "online_mode": True,
        }))
        (self.state_dir / "players.json").write_text(json.dumps({
            "online": 2, "max": 20, "players": ["Alice", "Bob"],
        }))
        (self.state_dir / "rcon.secret").write_text("test-rcon-pw")
        # Seed a server.properties and a meta file + a plugin jar
        (self.server_dir / "server.properties").write_text(
            "motd=Hello\n"
            "difficulty=easy\n"
            "resource-pack=https://my.cdn/pack.zip\n"
            "rcon.password=test-rcon-pw\n"
        )
        (self.server_dir / ".server-meta.json").write_text(json.dumps({
            "server_type": "paper", "version": "1.21.3", "build": "201",
        }))
        (self.server_dir / "plugins" / "Example.jar").write_bytes(b"MZ-fake-jar")
        self.panel = _load_panel_module(self.server_dir, self.backup_dir, self.state_dir)
        return self.panel.build_app()


class TestReadOnlyRoutes(PanelTestBase):
    async def test_index(self):
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        body = await resp.text()
        self.assertIn("BRUH Minecraft", body)

    async def test_status_payload(self):
        resp = await self.client.request("GET", "/api/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Stats/state echoed verbatim
        self.assertEqual(data["stats"]["online"], 2)
        self.assertEqual(data["state"]["server_type"], "paper")
        self.assertIn("server_meta", data)

    async def test_players_endpoint(self):
        resp = await self.client.request("GET", "/api/players")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["players"], ["Alice", "Bob"])
        self.assertEqual(data["max"], 20)

    async def test_properties_hides_rcon_password(self):
        resp = await self.client.request("GET", "/api/properties")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertNotIn("rcon.password", data["properties"])
        self.assertIn("motd", data["properties"])
        self.assertIn("difficulty", data["editable"])

    async def test_plugins_list(self):
        resp = await self.client.request("GET", "/api/plugins")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        names = [p["name"] for p in data["plugins"]]
        self.assertIn("Example.jar", names)


class TestPropertiesEditing(PanelTestBase):
    async def test_editable_key_writes_through(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "motd", "value": "Hello From Test",
        })
        self.assertEqual(resp.status, 200)
        props_path = self.server_dir / "server.properties"
        content = props_path.read_text()
        self.assertIn("motd=Hello From Test", content)
        # Non-managed keys are preserved
        self.assertIn("resource-pack=https://my.cdn/pack.zip", content)

    async def test_non_editable_key_rejected(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "server-port", "value": "99999",
        })
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("not editable", data["error"])

    async def test_edit_persists_to_addon_option(self):
        # 1.7.0: panel edits must write back to the add-on options so they
        # survive a restart. Capture the (option_key, value) and the coercion.
        persisted = []

        async def fake_persist(option_key, value):
            persisted.append((option_key, value))
            return None  # success

        self.panel._persist_option = fake_persist
        # int option: max-players -> max_players coerced to int
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "max-players", "value": "33",
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["persisted"])
        self.assertIn(("max_players", 33), persisted)

    async def test_bool_option_coerced(self):
        persisted = []

        async def fake_persist(option_key, value):
            persisted.append((option_key, value))
            return None

        self.panel._persist_option = fake_persist
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "pvp", "value": "false",
        })
        self.assertEqual(resp.status, 200)
        self.assertIn(("pvp", False), persisted)

    async def test_persist_failure_surfaces_warning(self):
        async def fake_persist(option_key, value):
            return "Supervisor HTTP 403"

        self.panel._persist_option = fake_persist
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "motd", "value": "Hi",
        })
        data = await resp.json()
        self.assertFalse(data["persisted"])
        self.assertIn("403", data["warning"])

    async def test_gamemode_live_applies_to_all_players(self):
        rcon_calls = []

        async def fake_rcon(cmd):
            rcon_calls.append(cmd)
            return "ok"

        async def fake_persist(option_key, value):
            return None

        self.panel._rcon_command = fake_rcon
        self.panel._persist_option = fake_persist
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "gamemode", "value": "creative",
        })
        self.assertEqual(resp.status, 200)
        # Must move existing online players, not just set the default.
        self.assertIn("gamemode creative @a", rcon_calls)



class TestPluginManagement(PanelTestBase):
    async def test_delete_plugin_succeeds(self):
        target = self.server_dir / "plugins" / "Example.jar"
        self.assertTrue(target.exists())
        resp = await self.client.request("DELETE", "/api/plugins/Example.jar")
        self.assertEqual(resp.status, 200)
        self.assertFalse(target.exists())

    async def test_delete_rejects_path_traversal(self):
        resp = await self.client.request("DELETE", "/api/plugins/..%2Fserver.jar")
        # aiohttp may or may not 404 on the URL-decoded path — in either case
        # the real server.jar must stay put.
        self.assertIn(resp.status, {400, 404})
        # Confirm the seed file is still where we left it
        self.assertTrue((self.server_dir / "plugins" / "Example.jar").exists())

    async def test_delete_non_jar_rejected(self):
        resp = await self.client.request("DELETE", "/api/plugins/notajar.txt")
        self.assertEqual(resp.status, 400)


class TestCommandValidation(PanelTestBase):
    async def test_command_requires_non_empty(self):
        resp = await self.client.request("POST", "/api/command", json={"command": ""})
        self.assertEqual(resp.status, 400)

    async def test_command_runs_via_rcon(self):
        resp = await self.client.request("POST", "/api/command", json={"command": "list"})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["reply"], "ok")  # from fake MCRcon

    async def test_say_rejects_empty(self):
        resp = await self.client.request("POST", "/api/say", json={"message": ""})
        self.assertEqual(resp.status, 400)


class TestWorldsSwitchAutoRestart(PanelTestBase):
    """Regression for 1.2.9: clicking Switch updates active_world but the
    panel's header Restart only kicks the JVM — `ensure_worlds_layout`
    never re-runs so the /config/minecraft symlink stays pointed at the
    old profile and the same world keeps loading. api_worlds_switch must
    now trigger a full add-on restart via the Supervisor so the symlink
    actually moves."""

    async def _patch_deps(self, *, switch_ok=True, restart_err=None):
        """Replace _run_world_manager and _supervisor_restart_self on the
        loaded panel module. Returns the call-log list."""
        calls = []

        async def fake_run_world_manager(*args):
            calls.append(("world_manager", args))
            if switch_ok:
                return 0, "active_world set to 'survival'"
            return 1, "profile does not exist"

        async def fake_supervisor_restart():
            calls.append(("supervisor_restart",))
            return restart_err

        self.panel._run_world_manager = fake_run_world_manager
        self.panel._supervisor_restart_self = fake_supervisor_restart
        return calls

    async def test_switch_triggers_supervisor_restart(self):
        calls = await self._patch_deps()
        # Pretend the "survival" profile exists so world-name validation passes.
        resp = await self.client.request("POST", "/api/worlds/survival/switch")
        self.assertEqual(resp.status, 200, await resp.text())
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("restarting now", data["message"])
        # Both dependencies must have been invoked, in order.
        self.assertEqual(
            [c[0] for c in calls],
            ["world_manager", "supervisor_restart"],
        )

    async def test_switch_surfaces_restart_failure(self):
        calls = await self._patch_deps(restart_err="Supervisor HTTP 403")
        resp = await self.client.request("POST", "/api/worlds/survival/switch")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("auto-restart failed", data["warning"])
        self.assertIn("403", data["warning"])

    async def test_switch_does_not_restart_when_world_manager_fails(self):
        calls = await self._patch_deps(switch_ok=False)
        resp = await self.client.request("POST", "/api/worlds/nonexistent/switch")
        self.assertEqual(resp.status, 400)
        # Supervisor restart must NOT fire when the options write failed —
        # otherwise we'd restart the add-on for nothing.
        self.assertEqual([c[0] for c in calls], ["world_manager"])

    async def test_player_action_invalid_name(self):
        resp = await self.client.request("POST", "/api/player/bad;name/op")
        self.assertEqual(resp.status, 400)

    async def test_player_action_unknown_action(self):
        resp = await self.client.request("POST", "/api/player/Alice/bogus")
        self.assertEqual(resp.status, 400)

    async def test_player_action_valid(self):
        resp = await self.client.request("POST", "/api/player/Alice/op")
        self.assertEqual(resp.status, 200)


class TestBackupListing(PanelTestBase):
    async def test_empty_when_no_backups(self):
        resp = await self.client.request("GET", "/api/backups")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data, {"git": [], "archives": []})

    async def test_archives_are_listed(self):
        archives = self.backup_dir / "archives"
        archives.mkdir()
        (archives / "world-2026-01-01T00-00-00Z.tar.gz").write_bytes(b"fake-archive")
        resp = await self.client.request("GET", "/api/backups")
        data = await resp.json()
        names = [a["name"] for a in data["archives"]]
        self.assertIn("world-2026-01-01T00-00-00Z.tar.gz", names)


class TestRestoreValidation(PanelTestBase):
    async def test_rejects_garbage_ref(self):
        resp = await self.client.request("POST", "/api/restore/not-a-valid-ref")
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
