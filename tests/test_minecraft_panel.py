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

import aiohttp
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

    async def test_edit_writes_to_active_world_properties(self):
        # 1.8.0: panel edits write to the active world's server.properties
        # (the per-world source of truth) — no add-on option round-trip.
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "gamemode", "value": "creative",
        })
        self.assertEqual(resp.status, 200)
        content = (self.server_dir / "server.properties").read_text()
        self.assertIn("gamemode=creative", content)
        # Unrelated keys preserved.
        self.assertIn("resource-pack=https://my.cdn/pack.zip", content)

    async def test_rejects_newline_injection(self):
        # A newline in the value must be rejected — otherwise it injects an
        # extra server.properties line.
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "motd", "value": "hi\nrcon.password=pwned",
        })
        self.assertEqual(resp.status, 400)
        # server.properties must be untouched (no injected key).
        content = (self.server_dir / "server.properties").read_text()
        self.assertNotIn("pwned", content)

    async def test_rejects_out_of_range_int(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "view-distance", "value": "2",  # schema min is 3
        })
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("between 3 and 32", data["error"])

    async def test_rejects_non_numeric_int(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "max-players", "value": "lots",
        })
        self.assertEqual(resp.status, 400)

    async def test_rejects_unknown_enum(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "gamemode", "value": "creative; op @a",
        })
        self.assertEqual(resp.status, 400)

    async def test_rejects_non_bool(self):
        resp = await self.client.request("POST", "/api/properties", json={
            "key": "pvp", "value": "maybe",
        })
        self.assertEqual(resp.status, 400)

    async def test_enforce_whitelist_not_editable(self):
        resp = await self.client.request("GET", "/api/properties")
        data = await resp.json()
        self.assertNotIn("enforce-whitelist", data["editable"])

    async def test_gamemode_live_applies_to_all_players(self):
        rcon_calls = []

        async def fake_rcon(cmd):
            rcon_calls.append(cmd)
            return "ok"

        self.panel._rcon_command = fake_rcon
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


class TestRecommender(PanelTestBase):
    """1.10.0: 'Tune for my hardware' reads host RAM and proposes settings.

    The recommender uses a MEMINFO_PATH env override so we can stage a fake
    /proc/meminfo in a tempfile and exercise the math hermetically."""

    def _set_meminfo(self, mb: int) -> None:
        # The recommender reads MEMINFO_PATH at call time, so we just point it
        # at a temp file. kibibytes in /proc/meminfo are `MemTotal: <kB> kB`.
        path = self.state_dir / "fake_meminfo"
        path.write_text(f"MemTotal:    {mb * 1024} kB\nMemFree:     1234 kB\n")
        os.environ["MEMINFO_PATH"] = str(path)
        self.addCleanup(lambda: os.environ.pop("MEMINFO_PATH", None))

    async def test_recommend_scales_with_host_ram(self):
        # 16 GB host -> 6 GB heap (one of the upper-tier ceilings).
        self._set_meminfo(16384)
        resp = await self.client.request("GET", "/api/recommend")
        data = await resp.json()
        # Memory is rounded to 256 MB.
        self.assertEqual(data["memory_mb"] % 256, 0)
        self.assertGreaterEqual(data["memory_mb"], 4096)
        # 2 GB headroom reserved for HA/OS.
        self.assertLessEqual(data["memory_mb"], 16384 - 2048)
        # Distances scale with heap; simulation ≤ view.
        self.assertGreater(data["view_distance"], 0)
        self.assertLessEqual(data["simulation_distance"], data["view_distance"])

    async def test_recommend_tiny_host_falls_back_to_floor(self):
        # 2 GB host with 2 GB reserved leaves nothing — recommender should
        # still propose a usable >=1 GB heap rather than 0.
        self._set_meminfo(2048)
        resp = await self.client.request("GET", "/api/recommend")
        data = await resp.json()
        self.assertGreaterEqual(data["memory_mb"], 512)

    async def test_apply_writes_global_and_per_world(self):
        # Persist option is captured (no Supervisor in tests); server.properties
        # is checked on disk.
        self._set_meminfo(8192)
        persisted: list[tuple[str, object]] = []

        async def fake_persist(option_key, value):
            persisted.append((option_key, value))
            return None

        self.panel._persist_option = fake_persist
        resp = await self.client.request("POST", "/api/recommend/apply")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Global write
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0][0], "memory_mb")
        self.assertIsInstance(persisted[0][1], int)
        # Per-world write
        content = (self.server_dir / "server.properties").read_text()
        self.assertRegex(content, r"(?m)^view-distance=\d+")
        self.assertRegex(content, r"(?m)^simulation-distance=\d+")
        self.assertIn("memory_mb", data["applied"])
        self.assertIn("view-distance", data["applied"])

    async def test_apply_surfaces_supervisor_failure(self):
        self._set_meminfo(8192)

        async def fake_persist(option_key, value):
            return "Supervisor HTTP 403"

        self.panel._persist_option = fake_persist
        resp = await self.client.request("POST", "/api/recommend/apply")
        data = await resp.json()
        # Per-world write still happens; the global write reports a warning.
        self.assertTrue(data["ok"])
        self.assertTrue(data["warnings"])
        self.assertIn("403", data["warnings"][0])
        # memory_mb did NOT get added to applied{}.
        self.assertNotIn("memory_mb", data["applied"])


class TestSetupWizard(PanelTestBase):
    """1.10.0: the first-run wizard accepts the EULA + initial choices and
    triggers a Supervisor restart so the JVM boots."""

    def _set_options(self, **opts) -> None:
        # The panel reads MC_OPTIONS_FILE to decide if setup is required.
        path = self.state_dir / "options.json"
        path.write_text(json.dumps(opts))
        os.environ["MC_OPTIONS_FILE"] = str(path)
        self.addCleanup(lambda: os.environ.pop("MC_OPTIONS_FILE", None))

    async def test_status_reports_setup_required_when_eula_unset(self):
        self._set_options(eula=False)
        resp = await self.client.request("GET", "/api/status")
        self.assertTrue((await resp.json())["setup_required"])

    async def test_status_no_setup_when_eula_accepted(self):
        self._set_options(eula=True)
        resp = await self.client.request("GET", "/api/status")
        self.assertFalse((await resp.json())["setup_required"])

    async def test_marker_suppresses_wizard_even_if_eula_false(self):
        # The marker is the dominant signal — if a previous wizard run
        # completed, even a manually-flipped `eula: false` (or any other
        # weird state) must NOT bring the wizard back. This is the
        # belt-and-suspenders gate that prevents the wizard from appearing
        # after every update.
        self._set_options(eula=False)
        (self.panel.SETUP_MARKER).parent.mkdir(parents=True, exist_ok=True)
        self.panel.SETUP_MARKER.write_text("2026-01-01T00:00:00+0000")
        resp = await self.client.request("GET", "/api/status")
        self.assertFalse((await resp.json())["setup_required"])

    async def test_eula_accepted_writes_marker_on_first_read(self):
        # The upgrade-from-pre-wizard case: existing install has EULA true
        # but no marker (because the user accepted EULA in YAML before this
        # release existed). The first /api/status call must claim the
        # setup-completed state by writing the marker, so subsequent calls
        # don't re-evaluate.
        self._set_options(eula=True)
        self.assertFalse(self.panel.SETUP_MARKER.is_file())
        await self.client.request("GET", "/api/status")
        self.assertTrue(self.panel.SETUP_MARKER.is_file())

    async def test_wizard_submit_writes_marker(self):
        # Belt-and-suspenders: the wizard's submit path explicitly drops the
        # marker so even if the Supervisor write of `eula: true` somehow
        # fails, the wizard never reappears.
        self._set_options(eula=False)
        async def noop(*a, **kw): return None
        self.panel._persist_option = noop
        self.panel._supervisor_restart_self = noop
        self._patch_worlds_dirs()
        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True, "active_world": "default",
        })
        self.assertEqual(resp.status, 200)
        self.assertTrue(self.panel.SETUP_MARKER.is_file())

    async def test_setup_rejects_without_eula(self):
        resp = await self.client.request("POST", "/api/setup", json={"eula": False})
        self.assertEqual(resp.status, 400)

    def _patch_worlds_dirs(self):
        """Point the panel's MC_WORLDS_DIR / MC_BACKUPS_ROOT at tmpdirs so the
        wizard doesn't try to write under /config inside CI."""
        from pathlib import Path as _P
        self.panel.MC_WORLDS_DIR = _P(self.tmp.name) / "minecraft-worlds"
        self.panel.MC_BACKUPS_ROOT = _P(self.tmp.name) / "minecraft-backups"
        self.panel.MC_WORLDS_DIR.mkdir(parents=True, exist_ok=True)
        self.panel.MC_BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)

    async def test_setup_writes_options_and_restarts(self):
        self._patch_worlds_dirs()
        persisted = []
        async def fake_persist(key, value):
            persisted.append((key, value))
            return None
        restarted = [False]
        async def fake_restart():
            restarted[0] = True
            return None
        self.panel._persist_option = fake_persist
        self.panel._supervisor_restart_self = fake_restart

        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True,
            "server_type": "paper",
            "online_mode": False,
            "active_world": "default",
            "gamemode": "creative",
            "difficulty": "peaceful",
            "level_type": "minecraft:flat",
            "level_seed": "12345",
            "pvp": False,
            "hardcore": False,
            "memory_mb": 4096,
            "view_distance": 12,
            "simulation_distance": 8,
            "install_essentialsx": True,
        })
        self.assertEqual(resp.status, 200, await resp.text())
        # Global writes
        self.assertIn(("eula", True), persisted)
        self.assertIn(("server_type", "paper"), persisted)
        self.assertIn(("active_world", "default"), persisted)
        self.assertIn(("memory_mb", 4096), persisted)
        self.assertIn(("install_essentialsx", True), persisted)
        self.assertTrue(restarted[0])
        # Per-world server.properties is written under the staged world dir.
        props = (self.panel.MC_WORLDS_DIR / "default" / "server.properties").read_text()
        self.assertIn("online-mode=false", props)
        self.assertIn("enforce-secure-profile=false", props)
        self.assertIn("gamemode=creative", props)
        self.assertIn("difficulty=peaceful", props)
        self.assertIn("level-type=minecraft:flat", props)
        self.assertIn("level-seed=12345", props)
        self.assertIn("pvp=false", props)
        self.assertIn("view-distance=12", props)
        self.assertIn("simulation-distance=8", props)

    async def test_setup_rejects_invalid_world_name(self):
        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True, "active_world": "bad name/with slash",
        })
        self.assertEqual(resp.status, 400)

    async def test_setup_rejects_invalid_gamemode(self):
        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True, "gamemode": "creative; op @a",
        })
        self.assertEqual(resp.status, 400)

    async def test_setup_rejects_out_of_range_memory(self):
        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True, "memory_mb": 100,
        })
        self.assertEqual(resp.status, 400)

    async def test_setup_creates_world_skeleton_for_new_name(self):
        self._patch_worlds_dirs()
        async def noop(*a, **kw): return None
        self.panel._persist_option = noop
        self.panel._supervisor_restart_self = noop
        resp = await self.client.request("POST", "/api/setup", json={
            "eula": True, "active_world": "creative_one", "gamemode": "creative",
        })
        self.assertEqual(resp.status, 200)
        wdir = self.panel.MC_WORLDS_DIR / "creative_one"
        self.assertTrue(wdir.is_dir())
        self.assertTrue((wdir / "plugins").is_dir())
        self.assertTrue((wdir / "mods").is_dir())
        self.assertTrue((wdir / "server.properties").is_file())
        self.assertTrue((self.panel.MC_BACKUPS_ROOT / "creative_one").is_dir())


class TestCrashBanner(PanelTestBase):
    async def test_status_omits_crash_when_running(self):
        # Default fixture writes status=running, so no crash should surface.
        resp = await self.client.request("GET", "/api/status")
        data = await resp.json()
        self.assertIsNone(data.get("crash"))

    async def test_status_reports_crash_with_excerpt(self):
        # Mark stopped + drop a console.log with an exception trace.
        state_path = self.state_dir / "state.json"
        s = json.loads(state_path.read_text())
        s["status"] = "stopped"
        state_path.write_text(json.dumps(s))
        (self.state_dir / "console.log").write_text(
            "[12:34:56 INFO]: Done (3.2s)!\n"
            "[12:34:57 ERROR]: java.lang.NullPointerException: cannot do thing\n"
            "\tat com.example.Plugin.onEnable(Plugin.java:42)\n"
            "[12:34:58 INFO]: Stopping server\n"
        )
        resp = await self.client.request("GET", "/api/status")
        crash = (await resp.json())["crash"]
        self.assertIsNotNone(crash)
        self.assertTrue(any("NullPointerException" in ln for ln in crash["excerpt"]))

    async def test_no_crash_when_user_stopped(self):
        # User-initiated stop writes no_restart; we suppress the banner so
        # the user doesn't see "crash" after clicking Stop.
        s = json.loads((self.state_dir / "state.json").read_text())
        s["status"] = "stopped"
        (self.state_dir / "state.json").write_text(json.dumps(s))
        (self.state_dir / "no_restart").write_text("1")
        (self.state_dir / "console.log").write_text("[INFO]: ERROR fake but stopped on purpose\n")
        resp = await self.client.request("GET", "/api/status")
        self.assertIsNone((await resp.json())["crash"])


class TestResourcePacks(PanelTestBase):
    def _packs_dir(self):
        d = self.state_dir / "resource-packs"
        d.mkdir(exist_ok=True)
        os.environ["MC_RESOURCE_PACKS"] = str(d)
        self.addCleanup(lambda: os.environ.pop("MC_RESOURCE_PACKS", None))
        # Force the module-level constant to re-read the override.
        from pathlib import Path as _P
        self.panel.MC_RESOURCE_PACKS = _P(os.environ["MC_RESOURCE_PACKS"])
        return d

    async def test_list_empty(self):
        self._packs_dir()
        resp = await self.client.request("GET", "/api/resource-packs")
        self.assertEqual((await resp.json())["packs"], [])

    async def test_list_returns_sha1(self):
        d = self._packs_dir()
        (d / "Test.zip").write_bytes(b"PK\x03\x04hello")
        resp = await self.client.request("GET", "/api/resource-packs")
        packs = (await resp.json())["packs"]
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["name"], "Test.zip")
        self.assertEqual(len(packs[0]["sha1"]), 40)

    async def test_delete_rejects_invalid_name(self):
        self._packs_dir()
        resp = await self.client.request("DELETE", "/api/resource-packs/..%2Fevil")
        self.assertIn(resp.status, {400, 404})

    async def test_apply_writes_to_active_world_properties(self):
        d = self._packs_dir()
        (d / "Pack.zip").write_bytes(b"PK\x03\x04hello")
        resp = await self.client.request("POST", "/api/resource-packs/Pack.zip/apply", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        content = (self.server_dir / "server.properties").read_text()
        self.assertIn(f"resource-pack={body['url']}", content)
        self.assertIn(f"resource-pack-sha1={body['sha1']}", content)


class TestWorldImport(PanelTestBase):
    async def test_import_rejects_non_zip(self):
        import io
        form = aiohttp.FormData()
        form.add_field("name", "imported")
        form.add_field("file", io.BytesIO(b"not a zip"), filename="x.zip")
        resp = await self.client.request("POST", "/api/worlds/import", data=form)
        self.assertEqual(resp.status, 400)

    async def test_import_rejects_zip_without_level_dat(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("notes.txt", "hi")
        buf.seek(0)
        form = aiohttp.FormData()
        form.add_field("name", "bad")
        form.add_field("file", buf, filename="bad.zip", content_type="application/zip")
        resp = await self.client.request("POST", "/api/worlds/import", data=form)
        self.assertEqual(resp.status, 400)
        self.assertIn("level.dat", (await resp.json())["error"])

    async def test_import_stages_valid_world(self):
        import io, zipfile, tempfile, shutil
        # Point the panel module's world directory at a tempdir so imports
        # don't try to write into /config.
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path as _P
            self.panel.MC_WORLDS_DIR = _P(tmp) / "minecraft-worlds"
            self.panel.MC_BACKUPS_ROOT = _P(tmp) / "minecraft-backups"
            (self.panel.MC_WORLDS_DIR).mkdir(parents=True)
            (self.panel.MC_BACKUPS_ROOT).mkdir(parents=True)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("my_world/level.dat", b"\x0a\x00\x00")  # fake nbt
                z.writestr("my_world/region/r.0.0.mca", b"region-data")
            buf.seek(0)
            form = aiohttp.FormData()
            form.add_field("name", "imported")
            form.add_field("file", buf, filename="my_world.zip", content_type="application/zip")
            resp = await self.client.request("POST", "/api/worlds/import", data=form)
            self.assertEqual(resp.status, 200, await resp.text())
            self.assertTrue((self.panel.MC_WORLDS_DIR / "imported" / "world" / "level.dat").is_file())
            self.assertTrue((self.panel.MC_BACKUPS_ROOT / "imported").is_dir())


if __name__ == "__main__":
    unittest.main()
