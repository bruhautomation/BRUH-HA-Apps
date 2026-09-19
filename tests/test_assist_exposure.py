#!/usr/bin/env python3
"""What Home Assistant exposes to Assist is what voice may see.

Three processes read the one rule — the worker pool and the classic
listener filter the area map, the MCP server launched for a voice turn
refuses to read or act on anything else — and none of them can import
another's copy, so the tests drive each half over the real module and the
real files rather than writing the shape down three times.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "brain"
sys.path.insert(0, str(ADDON / "scripts"))
sys.path.insert(0, str(ADDON / "ha-mcp-server"))

import brain_exposed  # noqa: E402
import ha_mcp_server  # noqa: E402


def fake_ws(explicit: dict, registry: list, expose_new: bool = True):
    """Core's three answers, in the shapes it really sends."""
    def ws(payload):
        kind = payload["type"]
        if kind == "homeassistant/expose_entity/list":
            return {"exposed_entities": {
                eid: {"conversation": yes} for eid, yes in explicit.items()}}
        if kind == "homeassistant/expose_new_entities/get":
            assert payload["assistant"] == "conversation"
            return {"expose_new": expose_new}
        if kind == "config/entity_registry/list":
            return registry
        raise AssertionError(kind)
    return ws


REGISTRY = [
    {"entity_id": "light.kitchen"},
    {"entity_id": "lock.front_door"},
    {"entity_id": "switch.hidden_plug", "hidden_by": "user"},
    {"entity_id": "switch.diag", "entity_category": "diagnostic"},
    {"entity_id": "sensor.hall_temp", "original_device_class": "temperature"},
    {"entity_id": "sensor.uptime"},
    {"entity_id": "binary_sensor.back_door", "device_class": "door"},
    {"entity_id": "light.explicitly_off"},
    {"entity_id": "lock.explicitly_on"},
]
EXPLICIT = {"light.explicitly_off": False, "lock.explicitly_on": True,
            "sensor.yaml_only": True}


class TestCoresDefaultRule(unittest.TestCase):
    """The lists are Core's; a lock is not exposed unless somebody says so."""

    def test_the_default_domains_and_nothing_else(self):
        for eid in ("light.a", "switch.a", "climate.a", "cover.a", "fan.a",
                    "media_player.a", "scene.a", "script.a", "vacuum.a"):
            self.assertTrue(brain_exposed.default_exposed(eid, expose_new=True), eid)
        for eid in ("lock.a", "alarm_control_panel.a", "person.a",
                    "weather.a", "camera.a", "input_boolean.a", "sensor.a",
                    "binary_sensor.a"):
            self.assertFalse(brain_exposed.default_exposed(eid, expose_new=True), eid)

    def test_a_sensor_is_exposed_by_its_device_class(self):
        self.assertTrue(brain_exposed.default_exposed(
            "sensor.t", expose_new=True, device_class="temperature"))
        self.assertTrue(brain_exposed.default_exposed(
            "binary_sensor.d", expose_new=True, device_class="door"))
        self.assertFalse(brain_exposed.default_exposed(
            "sensor.t", expose_new=True, device_class="uptime"))

    def test_hidden_category_and_expose_new_off_all_say_no(self):
        self.assertFalse(brain_exposed.default_exposed("light.a", expose_new=True, hidden=True))
        self.assertFalse(brain_exposed.default_exposed(
            "light.a", expose_new=True, category="config"))
        self.assertFalse(brain_exposed.default_exposed("light.a", expose_new=False))


class TestTheSnapshot(unittest.TestCase):
    def test_an_explicit_setting_wins_over_the_default(self):
        snap = brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY))
        self.assertIn("lock.explicitly_on", snap["exposed"])
        self.assertIn("light.explicitly_off", snap["hidden"])
        # ...and the defaults land where Core lands them.
        self.assertIn("light.kitchen", snap["exposed"])
        self.assertIn("sensor.hall_temp", snap["exposed"])
        self.assertIn("binary_sensor.back_door", snap["exposed"])
        for eid in ("lock.front_door", "switch.hidden_plug", "switch.diag",
                    "sensor.uptime"):
            self.assertIn(eid, snap["hidden"], eid)
        # An explicit setting on an entity with no registry row still counts.
        self.assertIn("sensor.yaml_only", snap["exposed"])

    def test_expose_new_off_leaves_only_the_explicit_yeses(self):
        snap = brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY, expose_new=False))
        self.assertEqual(snap["exposed"], ["lock.explicitly_on", "sensor.yaml_only"])

    def test_is_exposed_reads_the_snapshot_and_then_the_domain_default(self):
        snap = brain_exposed.index(brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY)))
        self.assertTrue(brain_exposed.is_exposed("light.kitchen", snap))
        self.assertTrue(brain_exposed.is_exposed("LIGHT.KITCHEN", snap))
        self.assertFalse(brain_exposed.is_exposed("lock.front_door", snap))
        # A YAML entity with no registry row and no setting: Core's domain
        # default, with no device class to consult.
        self.assertTrue(brain_exposed.is_exposed("switch.yaml_plug", snap))
        self.assertFalse(brain_exposed.is_exposed("sensor.yaml_temp", snap))
        self.assertFalse(brain_exposed.is_exposed("lock.yaml_lock", snap))
        # No snapshot at all answers no for everything: fail closed.
        self.assertFalse(brain_exposed.is_exposed("light.kitchen", None))

    def test_a_half_answer_raises_rather_than_reading_as_empty(self):
        for broken in ({"type": "homeassistant/expose_entity/list"},):
            def ws(payload, broken=broken):
                if payload["type"] == broken["type"]:
                    return {"error": "unknown command"}
                return fake_ws(EXPLICIT, REGISTRY)(payload)
            with self.assertRaises(ValueError):
                brain_exposed.snapshot(ws)

    def test_the_cache_round_trips_and_ages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cache", "exposed.json")
            snap = brain_exposed.refresh(fake_ws(EXPLICIT, REGISTRY), path)
            self.assertTrue(brain_exposed.is_exposed("light.kitchen", snap))
            again = brain_exposed.load(path, max_age=60)
            self.assertEqual(again["exposed"], snap["exposed"])
            self.assertIsNone(brain_exposed.load(path, max_age=-1))
            self.assertIsNone(brain_exposed.load(os.path.join(tmp, "nope"), 60))
            # load_or_refresh answers None, never raises, when Core is down.
            def down(payload):
                raise OSError("no websocket")
            self.assertIsNone(brain_exposed.load_or_refresh(
                down, os.path.join(tmp, "nope"), 60))


class TestTheMapFilter(unittest.TestCase):
    def setUp(self):
        self.snap = brain_exposed.index(brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY)))

    def test_only_exposed_ids_survive_and_an_emptied_area_goes(self):
        text = ("Weather: weather.home\n"
                "People: person.a\n"
                "Kitchen: light.kitchen, lock.front_door, switch.hidden_plug\n"
                "Porch: lock.front_door\n"
                "Hall: binary_sensor.back_door, sensor.uptime\n")
        got = brain_exposed.filter_map(text, self.snap)
        self.assertEqual(got, "Kitchen: light.kitchen\nHall: binary_sensor.back_door\n")

    def test_no_snapshot_is_an_empty_map(self):
        self.assertEqual(brain_exposed.filter_map("Kitchen: light.kitchen\n", None), "")

    def test_the_listener_s_route_is_the_cli_over_a_pipe(self):
        # The classic listener is shell: it pipes the rendered map through
        # `brain_exposed.py filter <cache>`, the same function the pool
        # calls. Driven as a subprocess, because that is what it is.
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "exposed.json")
            brain_exposed.refresh(fake_ws(EXPLICIT, REGISTRY), cache)
            proc = subprocess.run(
                [sys.executable, str(ADDON / "scripts" / "brain_exposed.py"),
                 "filter", cache],
                input="Kitchen: light.kitchen, lock.front_door\nPorch: lock.front_door\n",
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "Kitchen: light.kitchen\n")


class GateCase(unittest.TestCase):
    def setUp(self):
        self._old = (ha_mcp_server.EXPOSED_ONLY, ha_mcp_server.DENIED_SERVICES,
                     ha_mcp_server.PROTECTED_ENTITIES, dict(ha_mcp_server._EXPOSURE))
        ha_mcp_server.DENIED_SERVICES = []
        ha_mcp_server.PROTECTED_ENTITIES = []
        ha_mcp_server.EXPOSED_ONLY = True
        self.snap = brain_exposed.index(brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY)))
        ha_mcp_server._EXPOSURE.update(at=float("inf"), snap=self.snap)

    def tearDown(self):
        (ha_mcp_server.EXPOSED_ONLY, ha_mcp_server.DENIED_SERVICES,
         ha_mcp_server.PROTECTED_ENTITIES, old) = self._old
        ha_mcp_server._EXPOSURE.clear()
        ha_mcp_server._EXPOSURE.update(old)


class TestTheGateInTheServer(GateCase):
    """Driven through the chokepoints, never the helper — the protected
    list's own rule, for its reason."""

    @patch("ha_mcp_server.ha_api_request")
    def test_an_unexposed_entity_cannot_be_acted_on(self, api):
        for payload in ({"entity_id": "lock.front_door"},
                        {"entity_id": ["light.kitchen", "lock.front_door"]},
                        {"target": {"entity_id": "lock.front_door"}},
                        {"entity_id": "all"}):
            got = ha_mcp_server.call_service("lock", "unlock", payload)
            self.assertIn("error", got, payload)
            self.assertIn("exposed", got["error"], payload)
        api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_an_exposed_one_still_works_and_a_room_target_is_refused(self, api):
        api.return_value = {"ok": True}
        ha_mcp_server.call_service("light", "turn_on", {"entity_id": "light.kitchen"})
        api.assert_called_once()
        got = ha_mcp_server.call_service("light", "turn_off", {"area_id": "kitchen"})
        self.assertIn("error", got)
        self.assertIn("name the entity ids", got["error"])
        api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_control_tools_route_through_it(self, api):
        got = ha_mcp_server.control_lock("lock.front_door", "unlock")
        self.assertIn("error", got)
        api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_reads_are_gated_too(self, api):
        api.return_value = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            {"entity_id": "lock.front_door", "state": "locked", "attributes": {}},
            {"entity_id": "switch.yaml_plug", "state": "off", "attributes": {}},
        ]
        rows = ha_mcp_server.get_all_states()
        self.assertEqual([r["entity_id"] for r in rows],
                         ["light.kitchen", "switch.yaml_plug"])
        self.assertIn("error", ha_mcp_server.get_entity_state("lock.front_door"))
        self.assertIn("error", ha_mcp_server.get_history("lock.front_door"))
        self.assertIn("error", ha_mcp_server.get_statistics("lock.front_door"))
        api.return_value = {"entity_id": "light.kitchen", "state": "on"}
        self.assertEqual(ha_mcp_server.get_entity_state("light.kitchen")["state"], "on")

    @patch("ha_mcp_server.ha_api_request")
    def test_an_unreadable_exposure_fails_closed(self, api):
        api.return_value = [{"entity_id": "light.kitchen", "state": "on", "attributes": {}}]
        ha_mcp_server._EXPOSURE.update(at=0.0, snap=None)
        with patch.object(ha_mcp_server, "_ws_command", side_effect=OSError("down")):
            got = ha_mcp_server.call_service("light", "turn_on", {"entity_id": "light.kitchen"})
            self.assertIn("error", got)
            self.assertIn("could not be read", got["error"])
            self.assertEqual(ha_mcp_server.get_all_states(), [])
        api.assert_called_once()  # the states fetch; never the service call

    @patch("ha_mcp_server.ha_api_request")
    def test_off_the_voice_channel_nothing_changes(self, api):
        ha_mcp_server.EXPOSED_ONLY = False
        api.return_value = {"ok": True}
        ha_mcp_server.call_service("lock", "unlock", {"entity_id": "lock.front_door"})
        api.assert_called_once()
        api.return_value = [{"entity_id": "lock.front_door", "state": "locked", "attributes": {}}]
        self.assertEqual(len(ha_mcp_server.get_all_states()), 1)


class TestTheTwoWritersAgreeWithTheReader(unittest.TestCase):
    """`BRAIN_EXPOSED_ONLY` is a wire between three processes: spelled in
    the pool, the listener and the server, and read by one of them."""

    def test_the_variable_is_one_name_in_all_three(self):
        pool = (ADDON / "integrations" / "assist-worker-pool.py").read_text()
        listener = (ADDON / "integrations" / "assist-listener.sh").read_text()
        server = (ADDON / "ha-mcp-server" / "ha_mcp_server.py").read_text()
        for text in (pool, listener, server):
            self.assertIn("BRAIN_EXPOSED_ONLY", text)
        self.assertEqual(server.count('os.environ.get("BRAIN_EXPOSED_ONLY"'), 1)

    def test_the_option_reaches_every_half(self):
        import yaml
        config = yaml.safe_load((ADDON / "config.yaml").read_text())
        self.assertEqual(config["options"]["assist_exposure"], "exposed")
        self.assertEqual(config["schema"]["assist_exposure"], "list(exposed|all)?")
        run = (ADDON / "run.sh").read_text()
        self.assertIn("bashio::config 'assist_exposure' 'exposed'", run)
        self.assertIn('export BRAIN_ASSIST_EXPOSURE="${assist_exposure}"', run)
        # The two fallbacks agree with the shipped default: a fallback that
        # disagrees is a second answer that wins when nobody is looking.
        pool = (ADDON / "integrations" / "assist-worker-pool.py").read_text()
        listener = (ADDON / "integrations" / "assist-listener.sh").read_text()
        self.assertIn('os.environ.get("BRAIN_ASSIST_EXPOSURE", "exposed")', pool)
        self.assertEqual(len(re.findall(r"\$\{BRAIN_ASSIST_EXPOSURE:-exposed\}", listener)), 2)


POOL_PATH = ADDON / "integrations" / "assist-worker-pool.py"
FAKE_CLAUDE = REPO / "tests" / "fake_claude.py"


def pool_env(tmp: str, env: dict) -> dict:
    return {"BRAIN_SHARED_DIR": os.path.join(tmp, "shared"),
            "BRAIN_ASSIST_WORKDIR": tmp,
            "BRAIN_CLAUDE_BIN": f"{sys.executable} {FAKE_CLAUDE}",
            "FAKE_CLAUDE_LOG": os.path.join(tmp, "argv.log"),
            "BRAIN_RUN_SOURCES": os.path.join(tmp, "run-sources.jsonl"), **env}


def load_pool(tmp: str, env: dict) -> object:
    with patch.dict(os.environ, pool_env(tmp, env)):
        os.environ.pop("SUPERVISOR_TOKEN", None)
        os.environ.pop("FAKE_MODE", None)
        spec = importlib.util.spec_from_file_location(
            f"assist_pool_{uuid.uuid4().hex}", POOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    for d in (mod.REQUESTS_DIR, mod.RESPONSES_DIR, mod.SESSIONS_DIR,
              mod.CACHE_DIR, mod.LOG_DIR):
        os.makedirs(d, exist_ok=True)
    return mod


class TestThePoolAppliesIt(unittest.TestCase):
    def test_the_default_gates_and_all_lifts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_pool(tmp, {})
            self.assertTrue(mod.EXPOSED_ONLY)
            mod = load_pool(tmp, {"BRAIN_ASSIST_EXPOSURE": "all"})
            self.assertFalse(mod.EXPOSED_ONLY)
            self.assertEqual(mod.apply_exposure("Kitchen: lock.front_door\n"),
                             "Kitchen: lock.front_door\n")

    def test_the_map_is_filtered_through_the_one_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_pool(tmp, {})
            snap = brain_exposed.index(brain_exposed.snapshot(fake_ws(EXPLICIT, REGISTRY)))
            with patch.object(brain_exposed, "load_or_refresh", return_value=snap), \
                    patch.object(brain_exposed, "_default_ws", return_value=lambda p: None):
                got = mod.apply_exposure("Kitchen: light.kitchen, lock.front_door\n")
            self.assertEqual(got, "Kitchen: light.kitchen\n")

    def test_an_unreadable_exposure_empties_the_map_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_pool(tmp, {})
            with patch.object(brain_exposed, "load_or_refresh", return_value=None), \
                    patch.object(brain_exposed, "_default_ws", return_value=lambda p: None):
                got = mod.apply_exposure("Kitchen: light.kitchen\n")
            self.assertEqual(got, "")
            logs = "".join(p.read_text() for p in Path(mod.LOG_DIR).glob("assist-*.log"))
            self.assertIn("AREA-MAP emptied", logs)
            self.assertIn("assist_exposure: all", logs)

    def test_every_worker_is_told_which_channel_it_is(self):
        # The spawn reads the environment at spawn time, so the fake CLI
        # has to be on it for the whole press and not only at import.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, pool_env(tmp, {})):
            mod = load_pool(tmp, {})
            pool = mod.Pool()
            try:
                pool.handle({"id": uuid.uuid4().hex, "conversation_id": "c",
                             "text": "turn on the lab lights",
                             "type": "conversation", "ts": 0, "timeout": 30})
            finally:
                for worker in list(pool.workers.values()):
                    worker.kill()
                if pool.spare is not None:
                    pool.spare.kill()
            lines = Path(tmp, "argv.log").read_text().splitlines()
            envs = [l for l in lines if l.startswith("ENV BRAIN_EXPOSED_ONLY=")]
            self.assertTrue(envs)
            self.assertEqual(envs[-1], "ENV BRAIN_EXPOSED_ONLY=1")


if __name__ == "__main__":
    unittest.main()
