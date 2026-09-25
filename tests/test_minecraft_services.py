#!/usr/bin/env python3
"""The bruh_minecraft services, driven through their registered handlers.

A service that awaited the bridge and threw the answer away gave an
automation a green tick for a server that refused the command, or was not
running at all. These tests register the real services against a fake
`hass`, answer the bridge the way the add-on does, and assert what the
caller is handed: the server's reply as response data, and an error with
the add-on's own sentence when there is nothing to reply with.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG_DIR = REPO / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft"
BRIDGE_PY = REPO / "bruh-minecraft-server" / "integrations" / "ha-bridge.py"
SCRIPTS = REPO / "bruh-minecraft-server" / "scripts"


class Invalid(Exception):
    pass


class HAError(Exception):
    pass


def _stub_modules() -> dict:
    """Just enough voluptuous and Home Assistant for __init__ to import.

    The schemas are exercised for real where it matters (a player name, a
    coordinate): `vol.Invalid` is the one thing the validators raise, so it
    is a real exception here rather than an accept-anything stub.
    """
    vol = types.ModuleType("voluptuous")
    vol.Invalid = Invalid

    class _Any:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, v):
            return v

    for name in ("Schema", "Required", "Optional", "All", "Any", "In",
                 "Length", "Range", "Coerce"):
        setattr(vol, name, _Any)
    mods = {"voluptuous": vol}
    for name in ("homeassistant", "homeassistant.config_entries",
                 "homeassistant.const", "homeassistant.core",
                 "homeassistant.helpers", "homeassistant.helpers.config_validation",
                 "homeassistant.helpers.update_coordinator",
                 "homeassistant.exceptions"):
        mods[name] = types.ModuleType(name)
    mods["homeassistant.const"].Platform = types.SimpleNamespace(
        SENSOR="sensor", BINARY_SENSOR="binary_sensor", BUTTON="button", NOTIFY="notify")
    mods["homeassistant.core"].HomeAssistant = object
    mods["homeassistant.core"].ServiceCall = object
    mods["homeassistant.core"].SupportsResponse = types.SimpleNamespace(
        OPTIONAL="optional", ONLY="only")
    mods["homeassistant.exceptions"].HomeAssistantError = HAError
    mods["homeassistant.config_entries"].ConfigEntry = object
    cv = mods["homeassistant.helpers.config_validation"]
    cv.string = str
    cv.config_entry_only_config_schema = lambda domain: None
    mods["homeassistant.helpers"].config_validation = cv

    class _Coord:
        def __init__(self, *a, **kw):
            pass

        def __class_getitem__(cls, item):
            return cls

    mods["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _Coord
    return mods


def load_integration():
    saved = {k: sys.modules.get(k) for k in _stub_modules()}
    sys.modules.update(_stub_modules())
    pkg = "bruh_mc_services_test"
    try:
        for mod in list(sys.modules):
            if mod.startswith(pkg):
                sys.modules.pop(mod)
        parent = types.ModuleType(pkg)
        parent.__path__ = [str(PKG_DIR)]
        sys.modules[pkg] = parent
        spec = importlib.util.spec_from_file_location(
            pkg, PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[pkg] = module
        spec.loader.exec_module(module)
        return module
    finally:
        # Put back whatever another test module installed: several install
        # partial homeassistant stubs, and the first to load wins a shared
        # table (the power-tools device-cycle test's rule).
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class FakeServices:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, name, handler, schema=None, supports_response=None):
        self.handlers[name] = (handler, supports_response)


class Call:
    def __init__(self, data):
        self.data = data


class Base(unittest.TestCase):
    def setUp(self):
        self.mod = load_integration()
        self.sent = []
        self.answer = {"ok": True, "reply": "Teleported Steve to Alex"}

        async def fake_send(kind, payload, timeout=15.0):
            self.sent.append((kind, payload))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        self.mod.send_request = fake_send
        hass = types.SimpleNamespace(services=FakeServices())
        self.mod._register_services(hass)
        self.handlers = hass.services.handlers

    def call(self, name, **data):
        handler, _ = self.handlers[name]
        return asyncio.run(handler(Call(data)))


class TestTheAnswerReachesTheCaller(Base):
    def test_a_command_returns_the_servers_reply(self):
        got = self.call("rcon_command", command="/list\nstop")
        self.assertEqual(got, {"reply": "Teleported Steve to Alex"})
        # A newline is a second command; it never reaches the console as one.
        self.assertEqual(self.sent, [("command", {"command": "/list stop"})])

    def test_a_refusal_is_an_error_with_the_add_ons_sentence(self):
        self.answer = {"ok": False, "error": "RCON is not reachable"}
        with self.assertRaises(HAError) as ctx:
            self.call("say", message="hi")
        self.assertIn("RCON is not reachable", str(ctx.exception))

    def test_a_silent_add_on_is_an_error_not_a_success(self):
        self.answer = TimeoutError("no response")
        with self.assertRaises(HAError) as ctx:
            self.call("restart_server")
        self.assertIn("did not answer", str(ctx.exception))

    def test_status_is_response_only_and_carries_the_players(self):
        self.answer = {"ok": True, "online": 2, "max": 20, "players": ["Steve", ".Alex"],
                       "state": {"status": "running"}, "stats": {}}
        got = self.call("get_status")
        self.assertEqual(got["players"], ["Steve", ".Alex"])
        self.assertEqual(self.handlers["get_status"][1], "only")
        self.assertEqual(self.handlers["rcon_command"][1], "optional")

    def test_pardon_is_a_player_action(self):
        self.call("pardon_player", player="Steve")
        self.assertEqual(self.sent, [("player_action", {"name": "Steve", "action": "pardon"})])


class TestTeleport(Base):
    def test_to_a_player(self):
        self.call("teleport", player="Steve", to_player="Alex")
        self.assertEqual(self.sent[-1][1]["command"], "minecraft:tp Steve Alex")

    def test_to_coordinates_relative_ones_included(self):
        self.call("teleport", player="@a", x="100", y="~5", z="-20.5")
        self.assertEqual(self.sent[-1][1]["command"], "minecraft:tp @a 100 ~5 -20.5")

    def test_both_or_neither_is_refused_before_anything_is_sent(self):
        for data in ({"player": "Steve", "to_player": "Alex", "x": 1, "y": 2, "z": 3},
                     {"player": "Steve"}, {"player": "Steve", "x": 1}):
            with self.assertRaises(HAError):
                self.call("teleport", **data)
        self.assertEqual(self.sent, [])

    def test_gamemode(self):
        self.call("set_gamemode", player=".Emma", gamemode="creative")
        self.assertEqual(self.sent[-1][1]["command"], "gamemode creative .Emma")


class TestValidators(Base):
    def test_player_names(self):
        for good in ("Steve", ".Bedrock_Kid", "@a", "@p", "abc_123"):
            self.assertEqual(self.mod._player(good), good)
        for bad in ("", "Steve Alex", "a" * 18, "@e[type=creeper]", "Steve;stop", "x\nstop"):
            with self.assertRaises(Invalid, msg=bad):
                self.mod._player(bad)

    def test_coordinates(self):
        for good in ("0", "-12", "3.5", "~", "~-4", "^2"):
            self.assertEqual(self.mod._coordinate(good), good)
        for bad in ("north", "1 2", "~~", ""):
            with self.assertRaises(Invalid, msg=bad):
                self.mod._coordinate(bad)


class TestTheBridgeAnswersStatus(unittest.TestCase):
    """The add-on half, over a stubbed RCON: who is on, or that nobody answered."""

    def load(self, tmp, reply):
        rcon_mod = types.ModuleType("rcon_client")

        class Rcon:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                if isinstance(reply, Exception):
                    raise reply
                return self

            def __exit__(self, *a):
                return False

            def command(self, cmd):
                self.last = cmd
                return reply

        rcon_mod.Rcon = Rcon
        saved = sys.modules.get("rcon_client")
        sys.modules["rcon_client"] = rcon_mod
        os.environ["MC_PANEL_STATE"] = tmp
        try:
            spec = importlib.util.spec_from_file_location("ha_bridge_status", BRIDGE_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            os.environ.pop("MC_PANEL_STATE", None)
            if saved is None:
                sys.modules.pop("rcon_client", None)
            else:
                sys.modules["rcon_client"] = saved
        mod.PANEL_STATE = Path(tmp)
        return mod

    def test_players_are_parsed_and_colour_codes_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "state.json").write_text(json.dumps({"status": "running"}))
            mod = self.load(tmp, "There are 2 of a max of 20 players online: §aSteve, .Alex")
            got = asyncio.run(mod.handle({"kind": "status"}))
        self.assertTrue(got["ok"])
        self.assertTrue(got["reachable"])
        self.assertEqual(got["players"], ["Steve", ".Alex"])
        self.assertEqual(got["state"], {"status": "running"})

    def test_a_server_that_is_down_is_a_state_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, ConnectionRefusedError("refused"))
            got = asyncio.run(mod.handle({"kind": "status"}))
        self.assertTrue(got["ok"])
        self.assertFalse(got["reachable"])
        self.assertEqual(got["players"], [])
        self.assertIn("refused", got["note"])

    def test_an_empty_command_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, "")
            got = asyncio.run(mod.handle({"kind": "command", "payload": {"command": "  "}}))
        self.assertFalse(got["ok"])


class TestTheBridgeAsksThePanelForAddons(TestTheBridgeAnswersStatus):
    """The add-on browser lives in the panel; the bridge asks it over loopback.

    A real HTTP server stands in for the panel, so a refusal's JSON body is
    read the way the panel sends it — the sentence, not "HTTP 409".
    """

    def serve(self, status, body):
        import http.server
        import threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                seen.append((self.command, self.path,
                             self.rfile.read(length).decode() if length else ""))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = _answer

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}", seen

    def test_install_is_posted_and_its_answer_passed_back(self):
        url, seen = self.serve(200, {"ok": True, "installed": [{"title": "GSit"}],
                                     "restart_needed": True})
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, "")
            mod.PANEL_URL = url
            got = asyncio.run(mod.handle({"kind": "addon_install",
                                          "payload": {"id": "abc123", "kind": "plugin"}}))
        self.assertTrue(got["ok"])
        self.assertEqual(got["installed"][0]["title"], "GSit")
        self.assertEqual(seen[0][:2], ("POST", "/api/addons/install"))
        self.assertEqual(json.loads(seen[0][2]), {"id": "abc123", "kind": "plugin"})

    def test_a_refusal_carries_the_panels_sentence(self):
        url, _ = self.serve(409, {"error": "This server runs fabric, which cannot load plugins."})
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, "")
            mod.PANEL_URL = url
            got = asyncio.run(mod.handle({"kind": "addon_search",
                                          "payload": {"kind": "plugin", "query": "x"}}))
        self.assertFalse(got["ok"])
        self.assertIn("cannot load plugins", got["error"])


class TestTheCatalogAgrees(unittest.TestCase):
    def test_every_registered_service_is_documented_in_both_files(self):
        import yaml
        mod = load_integration()
        hass = types.SimpleNamespace(services=FakeServices())
        mod._register_services(hass)
        names = set(hass.services.handlers)
        yaml_names = set(yaml.safe_load((PKG_DIR / "services.yaml").read_text()))
        self.assertEqual(names, yaml_names)
        for path in (PKG_DIR / "strings.json", PKG_DIR / "translations" / "en.json"):
            self.assertEqual(set(json.loads(path.read_text())["services"]), names, path)

    def test_the_shipped_translation_is_the_strings_file(self):
        # HA reads translations/en.json at runtime; strings.json is the
        # source. They had drifted to the point that en.json carried no
        # entity or service names at all.
        self.assertEqual(json.loads((PKG_DIR / "strings.json").read_text()),
                         json.loads((PKG_DIR / "translations" / "en.json").read_text()))


if __name__ == "__main__":
    unittest.main()
