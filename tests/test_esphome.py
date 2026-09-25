#!/usr/bin/env python3
"""ESPHome device management, driven rather than described.

The files half is driven against a real folder and the real edit journal
(`brain undo` reads the same lines). The dashboard half is driven against a
real aiohttp server speaking the dashboard's own protocol — `GET /version`,
`GET /devices`, and a WebSocket per command that takes `{"type": "spawn"}`
and answers `{"event": "line"}` … `{"event": "exit", "code": n}` — because a
fake of a protocol that accepts whatever it is handed proves only that it
matches the code that mocked it. The ingress route is driven the same way:
a fake Supervisor that refuses a request without the `ingress_session`
cookie, which is the one thing that route exists to present.
"""

import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

from aiohttp import web

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

import automation_writer  # noqa: E402
import esphome  # noqa: E402
import ha_data  # noqa: E402


class _Folder(unittest.TestCase):
    """A private /config/esphome and a private edit journal per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dir = root / "esphome"
        self.dir.mkdir()
        journal = root / "journal"
        patches = [
            mock.patch.object(esphome, "ESPHOME_DIR", self.dir),
            mock.patch.object(automation_writer, "JOURNAL_DIR", journal),
            mock.patch.object(automation_writer, "SNAP_DIR", journal / "snapshots"),
            mock.patch.object(automation_writer, "INDEX", journal / "index.jsonl"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.index = journal / "index.jsonl"
        esphome.JOBS.clear()
        esphome.forget_route()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path


WIZARD_FILE = """substitutions:
  name: porch-light
  friendly_name: Porch Light

esphome:
  name: ${name}
  friendly_name: ${friendly_name}

esp32:
  board: esp32dev

api:
  encryption:
    key: !secret porch_key

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

sensor:
  - platform: template
    lambda: !lambda return 1.0;
packages:
  common: !include common.yaml
"""


class TestReadingAFile(_Folder):

    def test_substitutions_and_every_esphome_tag_are_read(self):
        info = esphome.describe(WIZARD_FILE)
        self.assertEqual(info["error"], "")
        self.assertEqual(info["name"], "porch-light")
        self.assertEqual(info["friendly_name"], "Porch Light")
        self.assertEqual(info["platform"], "esp32")
        self.assertEqual(info["board"], "esp32dev")

    def test_the_pre_2022_platform_spelling_is_read(self):
        info = esphome.describe("esphome:\n  name: old\n  platform: ESP8266\n"
                                "  board: d1_mini\n")
        self.assertEqual((info["platform"], info["board"]), ("esp8266", "d1_mini"))

    def test_a_parse_error_names_its_line(self):
        info = esphome.describe("esphome:\n  name: x\n bad: [\n")
        self.assertIn("line", info["error"])
        self.assertEqual(info["name"], "")

    def test_a_secret_is_never_mistaken_for_a_literal(self):
        doc, _ = esphome.parse_yaml("wifi:\n  ssid: !secret wifi_ssid\n")
        self.assertEqual(doc["wifi"]["ssid"], "!secret wifi_ssid")

    def test_list_marks_packages_and_skips_secrets_and_hidden_files(self):
        self.write("porch.yaml", WIZARD_FILE)
        self.write("common.yaml", "logger:\n")
        self.write("secrets.yaml", "wifi_ssid: home\n")
        self.write(".hidden.yaml", "esphome:\n  name: nope\n")
        rows = {r["configuration"]: r for r in esphome.list_configs()}
        self.assertEqual(sorted(rows), ["common.yaml", "porch.yaml"])
        self.assertTrue(rows["porch.yaml"]["is_device"])
        self.assertFalse(rows["common.yaml"]["is_device"])


class TestTheFileNameIsCheckedTwice(_Folder):

    def test_names_that_leave_the_folder_are_refused(self):
        for bad in ("../configuration.yaml", "a/b.yaml", ".hidden.yaml",
                    "porch", "porch.txt", "", "..yaml", "/etc/passwd.yaml",
                    "por\nch.yaml"):
            self.assertIsNone(esphome.config_path(bad), bad)

    def test_an_ordinary_name_is_inside_the_folder(self):
        path = esphome.config_path("porch-light.yaml")
        self.assertEqual(path.parent.resolve(), self.dir.resolve())


class TestWriting(_Folder):

    def test_a_write_is_journalled_so_brain_undo_can_put_it_back(self):
        path = self.write("porch.yaml", WIZARD_FILE)
        before = path.stat().st_mtime
        result = esphome.write_config("porch.yaml", WIZARD_FILE + "logger:\n",
                                      expect_mtime=before)
        self.assertTrue(result["ok"], result)
        line = json.loads(self.index.read_text().splitlines()[-1])
        self.assertEqual(line["path"], str(path))
        self.assertTrue(line["existed"])
        # And the real reverter puts the old bytes back.
        reverted = automation_writer.revert(line, config_dir=str(self.dir.parent))
        self.assertTrue(reverted.get("ok"), reverted)
        self.assertEqual(path.read_text(), WIZARD_FILE)

    def test_a_file_changed_on_disk_since_it_was_opened_is_not_overwritten(self):
        path = self.write("porch.yaml", WIZARD_FILE)
        opened = path.stat().st_mtime
        os.utime(path, (opened + 30, opened + 30))
        result = esphome.write_config("porch.yaml", "x: 1\n", expect_mtime=opened)
        self.assertFalse(result["ok"])
        self.assertTrue(result["conflict"])
        self.assertEqual(path.read_text(), WIZARD_FILE)

    def test_yaml_that_does_not_parse_is_saved_and_says_so(self):
        result = esphome.write_config("half.yaml", "esphome:\n  name: [\n",
                                      create=True)
        self.assertTrue(result["ok"])
        self.assertIn("does not parse", result["warning"])
        self.assertTrue((self.dir / "half.yaml").is_file())

    def test_create_refuses_a_file_that_exists(self):
        self.write("porch.yaml", WIZARD_FILE)
        result = esphome.write_config("porch.yaml", "x: 1\n", create=True)
        self.assertTrue(result["conflict"])

    def test_archive_moves_the_file_and_never_overwrites_an_older_archive(self):
        self.write("porch.yaml", "a: 1\n")
        first = esphome.archive_config("porch.yaml")
        self.write("porch.yaml", "a: 2\n")
        second = esphome.archive_config("porch.yaml")
        self.assertEqual(first["archived_to"], "archive/porch.yaml")
        self.assertEqual(second["archived_to"], "archive/porch-1.yaml")
        self.assertFalse((self.dir / "porch.yaml").exists())
        self.assertEqual((self.dir / "archive" / "porch.yaml").read_text(), "a: 1\n")


class TestCreating(_Folder):

    def test_a_new_device_parses_and_carries_its_own_keys(self):
        self.write("secrets.yaml", "wifi_ssid: a\nwifi_password: b\n")
        one = esphome.create_config("porch-light", "Porch Light", "esp32")
        two = esphome.create_config("garage-door", "", "esp8266")
        self.assertTrue(one["ok"], one)
        self.assertNotIn("warning", one)
        a = esphome.parse_yaml((self.dir / "porch-light.yaml").read_text())[0]
        b = esphome.parse_yaml((self.dir / "garage-door.yaml").read_text())[0]
        self.assertEqual(one["name"], "porch-light")
        self.assertEqual(two["platform"], "esp8266")
        self.assertEqual(a["esp32"]["board"], "esp32dev")
        self.assertNotEqual(a["api"]["encryption"]["key"],
                            b["api"]["encryption"]["key"])
        self.assertEqual(a["wifi"]["ssid"], "!secret wifi_ssid")

    def test_a_name_that_is_not_a_hostname_is_refused(self):
        for bad in ("Porch Light", "-porch", "porch_light", "a" * 40, ""):
            self.assertFalse(esphome.create_config(bad)["ok"], bad)

    def test_missing_wifi_secrets_are_said_out_loud(self):
        result = esphome.create_config("porch", "", "esp32")
        self.assertIn("wifi_ssid", result["warning"])


class TestSecrets(_Folder):

    def test_setting_one_touches_only_its_line(self):
        self.write("secrets.yaml", "# my secrets\nwifi_ssid: old  # home\n"
                                   "wifi_password: pw\n")
        result = esphome.set_secret("wifi_ssid", 'new "net"')
        self.assertTrue(result["ok"], result)
        text = (self.dir / "secrets.yaml").read_text()
        self.assertTrue(text.startswith("# my secrets\n"))
        self.assertIn("wifi_password: pw\n", text)
        self.assertEqual(esphome.parse_yaml(text)[0]["wifi_ssid"], 'new "net"')

    def test_a_new_key_is_appended(self):
        self.write("secrets.yaml", "wifi_ssid: a")
        self.assertTrue(esphome.set_secret("api_key", "xyz")["ok"])
        self.assertEqual(esphome.secret_keys(), ["api_key", "wifi_ssid"])

    def test_a_multi_line_value_is_refused_not_half_replaced(self):
        self.write("secrets.yaml", "cert: |\n  line one\n  line two\n")
        result = esphome.set_secret("cert", "x")
        self.assertFalse(result["ok"])
        self.assertIn("line one", (self.dir / "secrets.yaml").read_text())

    def test_keys_are_listed_and_values_are_not(self):
        self.write("secrets.yaml", "wifi_password: hunter2\n")
        self.assertEqual(esphome.secret_keys(), ["wifi_password"])
        self.assertNotIn("hunter2", json.dumps(esphome.secret_keys()))


class TestWhichAddon(unittest.TestCase):

    def test_running_beats_stopped_and_stable_beats_beta(self):
        rows = [
            {"slug": "5c53de3b_esphome-beta", "state": "started"},
            {"slug": "5c53de3b_esphome", "state": "stopped"},
            {"slug": "5c53de3b_esphome-dev", "state": "started"},
            {"slug": "core_mosquitto", "state": "started"},
        ]
        self.assertEqual(esphome.pick_addon(rows)["slug"], "5c53de3b_esphome-beta")
        rows[1]["state"] = "started"
        self.assertEqual(esphome.pick_addon(rows)["slug"], "5c53de3b_esphome")

    def test_no_esphome_is_none(self):
        self.assertIsNone(esphome.pick_addon([{"slug": "core_ssh"}]))


# ---------------------------------------------------------------------------
# A dashboard that speaks the dashboard's protocol
# ---------------------------------------------------------------------------

def dashboard_app(*, require_cookie=None, script=None, seen=None):
    """The ESPHome dashboard's HTTP and WebSocket surface, as far as brAIn
    uses it. `script` maps a command path to (lines, exit code); a code of
    None keeps the socket open until the client closes it (logs)."""
    script = script or {}
    seen = seen if seen is not None else []

    def gate(request):
        if require_cookie and request.cookies.get("ingress_session") != require_cookie:
            raise web.HTTPUnauthorized()

    async def version(request):
        gate(request)
        return web.json_response({"version": "2026.9.0"})

    async def devices(request):
        gate(request)
        return web.json_response({"configured": [{
            "configuration": "porch.yaml", "name": "porch-light",
            "deployed_version": "2026.8.0", "current_version": "2026.9.0",
            "address": "porch-light.local", "loaded_integrations": ["api", "wifi"],
        }], "importable": [{"name": "athom-plug", "friendly_name": "Athom Plug",
                            "package_import_url": "github://x", "network": "wifi"}]})

    async def ping(request):
        gate(request)
        return web.json_response({"porch.yaml": True})

    async def command(request):
        gate(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        msg = await ws.receive_json()
        seen.append((request.match_info["cmd"], msg))
        lines, code = script.get(request.match_info["cmd"], (["ok"], 0))
        for line in lines:
            await ws.send_json({"event": "line", "data": line})
        if code is None:
            async for _ in ws:
                pass
            return ws
        await ws.send_json({"event": "exit", "code": code})
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/version", version)
    app.router.add_get("/devices", devices)
    app.router.add_get("/ping", ping)
    app.router.add_get("/{cmd}", command)
    return app


class _Served(_Folder):

    def setUp(self):
        super().setUp()
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.runners = []

    def tearDown(self):
        for runner in self.runners:
            self.loop.run_until_complete(runner.cleanup())
        super().tearDown()

    def serve(self, app, prefix=""):
        async def up():
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            self.runners.append(runner)
            port = runner.addresses[0][1]
            return f"http://127.0.0.1:{port}{prefix}"
        return self.loop.run_until_complete(up())

    def go(self, coro):
        return self.loop.run_until_complete(coro)

    def follow(self, job_id, seconds=5):
        return self.go(esphome.wait(job_id, seconds))


class TestTheDashboardProtocol(_Served):

    def setUp(self):
        super().setUp()
        self.write("porch.yaml", WIZARD_FILE.replace("porch-light", "porch-light"))
        self.seen = []
        self.url = self.serve(dashboard_app(seen=self.seen, script={
            "validate": (["\x1b[32mINFO Reading configuration\x1b[0m",
                          "INFO Configuration is valid!"], 0),
            "run": (["Compiling", "Uploading: [=====]"], 1),
            "logs": (["[D][sensor:093]: 'Temp': 21.0"], None),
        }))
        env = mock.patch.dict(os.environ, {"BRAIN_ESPHOME_DASHBOARD_URL": self.url})
        env.start()
        self.addCleanup(env.stop)

    def test_a_validate_is_spawned_and_its_lines_arrive_without_colour(self):
        started = self.go(esphome.start("validate", "porch.yaml"))
        self.assertTrue(started["ok"], started)
        job = self.follow(started["job"]["id"])
        self.assertEqual(job.state, "succeeded")
        self.assertEqual(job.exit_code, 0)
        self.assertIn("INFO Reading configuration", list(job.lines))
        self.assertEqual(self.seen[0], ("validate", {"type": "spawn",
                                                     "configuration": "porch.yaml"}))

    def test_install_sends_the_port_and_a_non_zero_exit_is_a_failure(self):
        started = self.go(esphome.start("install", "porch.yaml"))
        job = self.follow(started["job"]["id"])
        self.assertEqual(self.seen[0][0], "run")
        self.assertEqual(self.seen[0][1]["port"], "OTA")
        self.assertEqual(job.state, "failed")
        self.assertIn("exit code 1", job.error)

    def test_logs_run_until_stopped_and_one_command_at_a_time(self):
        started = self.go(esphome.start("logs", "porch.yaml"))
        job_id = started["job"]["id"]
        self.follow(job_id, 0.5)
        again = self.go(esphome.start("validate", "porch.yaml"))
        self.assertTrue(again["conflict"])
        esphome.stop(job_id)
        job = self.follow(job_id, 5)
        self.assertEqual(job.state, "stopped")
        self.assertIn("[D][sensor:093]: 'Temp': 21.0", list(job.lines))

    def test_the_overview_joins_files_dashboard_and_ping(self):
        with mock.patch.object(esphome, "ha_devices",
                               mock.AsyncMock(return_value={"ok": True, "error": "",
                                                            "devices": []})):
            data = self.go(esphome.overview(fresh=True))
        self.assertTrue(data["dashboard"]["reachable"])
        self.assertEqual(data["dashboard"]["version"], "2026.9.0")
        dev = data["devices"][0]
        self.assertTrue(dev["update_available"])
        self.assertTrue(dev["online"])
        self.assertEqual(dev["address"], "porch-light.local")
        self.assertEqual(data["importable"][0]["name"], "athom-plug")


class TestTheIngressRoute(_Served):
    """The add-on's own route: a session minted through Core, then the
    Supervisor's ingress proxy, which refuses a request without the cookie."""

    def test_the_session_cookie_is_what_gets_the_dashboard_to_answer(self):
        self.write("porch.yaml", WIZARD_FILE)
        dash = dashboard_app(require_cookie="sess-1")

        async def addons(request):
            return web.json_response({"data": {"addons": [
                {"slug": "5c53de3b_esphome", "name": "ESPHome", "state": "started"}]}})

        async def info(request):
            return web.json_response({"data": {
                "state": "started", "version": "2026.9.0",
                "ingress_entry": "/api/hassio_ingress/TOKEN123"}})

        sup = web.Application()
        sup.router.add_get("/addons", addons)
        sup.router.add_get("/addons/5c53de3b_esphome/info", info)
        sup.add_subapp("/ingress/TOKEN123/", dash)
        base = self.serve(sup)
        calls = []

        async def ws_calls(session, commands):
            calls.append(commands)
            return [{"ok": True, "result": {"session": "sess-1"}, "error": ""}]

        with mock.patch.object(esphome, "SUPERVISOR_API", base), \
                mock.patch.object(ha_data, "SUPERVISOR_TOKEN", "tok"), \
                mock.patch.object(ha_data, "_ws_calls", ws_calls), \
                mock.patch.dict(os.environ, {"BRAIN_ESPHOME_DASHBOARD_URL": ""}):
            import aiohttp

            async def go():
                async with aiohttp.ClientSession() as s:
                    return await esphome.route(s, fresh=True)
            found, status = self.go(go())
        self.assertTrue(status["reachable"], status)
        self.assertEqual(status["via"], "ingress")
        self.assertEqual(found.base, f"{base}/ingress/TOKEN123")
        self.assertEqual(calls[0][0]["type"], "supervisor/api")
        self.assertEqual(calls[0][0]["endpoint"], "/ingress/session")

    def _supervisor(self, info_extra=None, dash=None):
        async def addons(request):
            return web.json_response({"data": {"addons": [
                {"slug": "5c53de3b_esphome", "name": "ESPHome", "state": "started"}]}})

        async def info(request):
            return web.json_response({"data": {
                "state": "started", "version": "2026.9.0",
                "ingress_entry": "/api/hassio_ingress/TOKEN123",
                **(info_extra or {})}})

        sup = web.Application()
        sup.router.add_get("/addons", addons)
        sup.router.add_get("/addons/5c53de3b_esphome/info", info)
        if dash is not None:
            sup.add_subapp("/ingress/TOKEN123/", dash)
        return self.serve(sup)

    def _discover(self, base, ws_calls, env):
        import aiohttp

        with mock.patch.object(esphome, "SUPERVISOR_API", base), \
                mock.patch.object(ha_data, "SUPERVISOR_TOKEN", "tok"), \
                mock.patch.object(ha_data, "_ws_calls", ws_calls), \
                mock.patch.dict(os.environ, {"BRAIN_ESPHOME_DASHBOARD_URL": "",
                                             "BRAIN_ESPHOME_HA_TOKEN": "",
                                             **env}):
            async def go():
                async with aiohttp.ClientSession() as s:
                    return await esphome.discover(s)
            return self.go(go())

    def test_the_supervisor_refusing_the_proxy_names_the_token(self):
        # What the Supervisor's proxy answers every `supervisor/*` command
        # an add-on sends, copied from its source: code and message both.
        base = self._supervisor()

        async def ws_calls(session, commands, **kw):
            return [{"ok": False, "result": None, "error": "Unauthorized"}]

        found, status = self._discover(base, ws_calls, {})
        self.assertIsNone(found)
        self.assertTrue(status["needs_token"])
        self.assertIn("no longer lets add-ons", status["reason"])
        self.assertIn("esphome_ha_token", status["reason"])

    def test_a_token_mints_the_session_over_cores_own_socket(self):
        dash = dashboard_app(require_cookie="sess-9")
        base = self._supervisor(dash=dash)
        seen = []

        async def ws_calls(session, commands, **kw):
            seen.append(kw)
            if kw.get("token") == "person-token":
                return [{"ok": True, "result": {"session": "sess-9"}, "error": ""}]
            return [{"ok": False, "result": None, "error": "Unauthorized"}]

        found, status = self._discover(
            base, ws_calls, {"BRAIN_ESPHOME_HA_TOKEN": "person-token"})
        self.assertTrue(status["reachable"], status)
        self.assertEqual(status["via"], "ingress")
        self.assertEqual(seen[0]["url"], esphome.CORE_DIRECT_WS)
        self.assertNotIn("supervisor/core", seen[0]["url"])

    def test_the_addons_own_port_is_tried_when_it_has_one(self):
        dash = self.serve(dashboard_app())
        port = int(dash.rsplit(":", 1)[1])
        base = self._supervisor({"network": {"6052/tcp": port},
                                 "ip_address": "127.0.0.1"})

        async def ws_calls(session, commands, **kw):
            raise AssertionError("an open port needs no session")

        found, status = self._discover(base, ws_calls, {})
        self.assertTrue(status["reachable"], status)
        self.assertEqual(status["via"], "port")
        self.assertEqual(found.base, f"http://127.0.0.1:{port}")

    def test_a_stopped_addon_is_a_sentence_naming_it(self):
        async def addons(request):
            return web.json_response({"data": {"addons": [
                {"slug": "5c53de3b_esphome", "name": "ESPHome", "state": "stopped"}]}})

        async def info(request):
            return web.json_response({"data": {"state": "stopped"}})

        sup = web.Application()
        sup.router.add_get("/addons", addons)
        sup.router.add_get("/addons/5c53de3b_esphome/info", info)
        base = self.serve(sup)
        with mock.patch.object(esphome, "SUPERVISOR_API", base), \
                mock.patch.object(ha_data, "SUPERVISOR_TOKEN", "tok"), \
                mock.patch.dict(os.environ, {"BRAIN_ESPHOME_DASHBOARD_URL": ""}):
            import aiohttp

            async def go():
                async with aiohttp.ClientSession() as s:
                    return await esphome.discover(s)
            found, status = self.go(go())
        self.assertIsNone(found)
        self.assertIn("ESPHome add-on is stopped", status["reason"])
        self.assertIn("Editing files still works", status["reason"])


class TestProtectedDevices(_Served):
    """Flashing a device is acting on every entity it carries."""

    def setUp(self):
        super().setUp()
        self.write("porch.yaml", WIZARD_FILE)
        self.url = self.serve(dashboard_app())
        env = mock.patch.dict(os.environ, {
            "BRAIN_ESPHOME_DASHBOARD_URL": self.url,
            "BRAIN_PROTECTED_ENTITIES": "lock.front_door"})
        env.start()
        self.addCleanup(env.stop)

    def _registry(self, answer):
        return mock.patch.object(esphome, "ha_devices", mock.AsyncMock(return_value=answer))

    def test_a_device_carrying_a_protected_entity_is_not_flashed(self):
        reg = {"ok": True, "error": "", "devices": [{
            "id": "d1", "name": "Porch Light", "name_by_user": "", "area_id": "",
            "entities": ["light.porch", "lock.front_door"], "update_entity": ""}]}
        with self._registry(reg):
            result = self.go(esphome.start("install", "porch.yaml"))
        self.assertTrue(result["refused"])
        self.assertIn("lock.front_door", result["error"])
        self.assertEqual(esphome.JOBS, {})

    def test_an_unreadable_registry_refuses_while_the_list_is_set(self):
        with self._registry({"ok": False, "error": "timeout", "devices": []}):
            result = self.go(esphome.start("install", "porch.yaml"))
        self.assertTrue(result["refused"])

    def test_a_device_home_assistant_has_never_seen_carries_nothing(self):
        with self._registry({"ok": True, "error": "", "devices": []}):
            result = self.go(esphome.start("install", "porch.yaml"))
        self.assertTrue(result["ok"], result)
        self.follow(result["job"]["id"])

    def test_validate_does_not_ask_at_all(self):
        with self._registry({"ok": False, "error": "timeout", "devices": []}):
            result = self.go(esphome.start("validate", "porch.yaml"))
        self.assertTrue(result["ok"])
        self.follow(result["job"]["id"])

    def test_the_rename_does_not_hide_a_device(self):
        info = {"name": "porch-light", "friendly_name": "Porch Light"}
        dev = {"name": "Porch Light", "name_by_user": "Front porch"}
        self.assertIs(esphome.match_device(info, [dev]), dev)


class TestTheRoutes(_Served):

    def test_get_put_and_a_conflict_are_json_with_their_status(self):
        path = self.write("porch.yaml", WIZARD_FILE)
        app = web.Application()
        esphome.setup(app)
        base = self.serve(app)
        import aiohttp

        async def go():
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{base}/api/esphome/config/porch.yaml") as r:
                    got = (r.status, await r.json())
                async with s.put(f"{base}/api/esphome/config/porch.yaml",
                                 json={"content": "a: 1\n",
                                       "mtime": got[1]["mtime"] - 50}) as r:
                    conflict = (r.status, await r.json())
                async with s.get(f"{base}/api/esphome/config/..%2Fsecrets.yaml") as r:
                    escape = r.status
                async with s.post(f"{base}/api/esphome/config/porch.yaml/explode",
                                  json={}) as r:
                    bogus = (r.status, await r.json())
                return got, conflict, escape, bogus
        got, conflict, escape, bogus = self.go(go())
        self.assertEqual(got[0], 200)
        self.assertEqual(got[1]["name"], "porch-light")
        self.assertEqual(conflict[0], 409)
        self.assertEqual(path.read_text(), WIZARD_FILE)
        self.assertIn(escape, (400, 404))
        self.assertEqual(bogus[0], 400)


class TestTheMcpTools(unittest.TestCase):
    """The tools go through the panel, and a refusal arrives as its sentence."""

    @classmethod
    def setUpClass(cls):
        import ha_mcp_server
        cls.mcp = ha_mcp_server

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.endswith("/install"):
                    self._answer(409, {"ok": False, "refused": True,
                                       "error": "carries lock.front_door"})
                else:
                    self._answer(404, {"ok": False, "error": "nope"})

            def do_GET(self):
                if self.path == "/api/esphome/secrets":
                    self._answer(200, {"ok": True, "keys": ["wifi_ssid"]})
                else:
                    self._answer(200, {"ok": True, "path": self.path})

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        patch = mock.patch.object(self.mcp, "PANEL_URL", self.url)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_refusal_carries_the_panels_sentence(self):
        result = self.mcp.handle_tool_call("esphome_install",
                                           {"configuration": "porch"})
        self.assertIn("lock.front_door", result["error"])
        self.assertTrue(result["refused"])

    def test_secrets_are_listed_by_key_and_never_read(self):
        result = self.mcp.handle_tool_call("esphome_get_config",
                                           {"configuration": "secrets.yaml"})
        self.assertEqual(result["keys"], ["wifi_ssid"])
        self.assertNotIn("content", result)

    def test_a_bare_name_gets_its_extension_and_is_quoted(self):
        result = self.mcp.handle_tool_call("esphome_get_config",
                                           {"configuration": "porch light"})
        self.assertEqual(result["path"], "/api/esphome/config/porch%20light.yaml")


if __name__ == "__main__":
    unittest.main()
