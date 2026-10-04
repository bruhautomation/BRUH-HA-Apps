#!/usr/bin/env python3
"""What the `call_service` chokepoint reads, and what it used to miss.

Three holes, all at the one place every acting tool goes through:

* A voice-level agent (BRAIN_EXPOSED_ONLY=1) was scoped by the entities a
  call named, so a call that named none — `homeassistant.restart`,
  `hassio.host_shutdown`, `brain.create_user` with `admin: true` — passed
  every gate with the Supervisor's admin token behind it.
* The protected list, the deny-list and the exposure gate read `entity_id`
  and `target` and nothing else, so `scene.apply` with an `entities` map
  unlocked a protected lock through Core's reproduce_state.
* `scene.turn_on`, `script.turn_on`, `automation.trigger` and a bare
  `script.<object_id>` reached the house through a container that was
  checked as the container — the indirection `fire_event` has been refused
  for since the protected list existed.

Every test drives `call_service` (or the dispatcher) with Core faked at the
REST call and the WebSocket, and asserts what reached Core — never a helper,
because a helper that answers correctly while the chokepoint forgets to ask
it is the bypass.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "brain" / "scripts"))
sys.path.insert(0, str(REPO / "brain" / "ha-mcp-server"))

import brain_exposed  # noqa: E402
import ha_mcp_server as m  # noqa: E402

# Core's three exposure answers, in the shapes it sends (test_assist_exposure
# drives the real snapshot builder over the same shapes).
REGISTRY = [
    {"entity_id": "light.kitchen"},
    {"entity_id": "light.hall", "device_id": "dev-hall", "area_id": "hall"},
    {"entity_id": "lock.front_door", "device_id": "dev-lock"},
    {"entity_id": "media_player.den"},
    {"entity_id": "script.goodnight"},
    {"entity_id": "script.unlock_door"},
    {"entity_id": "scene.movie"},
    {"entity_id": "input_boolean.guest", "labels": ["guests"]},
    {"entity_id": "tts.google"},
]
EXPLICIT = {"script.unlock_door": False, "tts.google": True}


def exposure_ws(payload, timeout=15):
    kind = payload["type"]
    if kind == "homeassistant/expose_entity/list":
        return {"exposed_entities": {eid: {"conversation": yes}
                                     for eid, yes in EXPLICIT.items()}}
    if kind == "homeassistant/expose_new_entities/get":
        return {"expose_new": True}
    if kind == "config/entity_registry/list":
        return REGISTRY
    raise AssertionError(kind)


class FakeCore:
    """search/related and the registries, in the shapes Core answers them."""

    DEVICES = [
        {"id": "dev-hall", "area_id": "hall"},
        {"id": "dev-lock", "area_id": "hall"},
        {"id": "dev-porch", "area_id": "porch"},
    ]
    AREAS = [
        {"area_id": "hall", "floor_id": "ground"},
        {"area_id": "porch", "floor_id": "ground"},
    ]

    def __init__(self):
        self.related = {}
        self.asked = []
        self.down = False

    def __call__(self, payload, timeout=15):
        kind = payload["type"]
        self.asked.append(kind)
        if self.down:
            raise OSError("Home Assistant is restarting")
        if kind == "search/related":
            # HA answers every item type it found, with the requested item
            # removed, and leaves out the empty ones.
            return self.related.get(payload["item_id"], {})
        if kind == "config/entity_registry/list":
            return REGISTRY
        if kind == "config/device_registry/list":
            return self.DEVICES
        if kind == "config/area_registry/list":
            return self.AREAS
        if kind == "call_service":
            return {"response": {}}
        raise AssertionError(kind)


class ChokepointCase(unittest.TestCase):
    def setUp(self):
        saved = {k: getattr(m, k) for k in
                 ("DENIED_SERVICES", "PROTECTED_ENTITIES", "EXPOSED_ONLY")}
        saved_exposure = dict(m._EXPOSURE)
        saved_scopes = dict(m._PROTECTED_SCOPES)
        saved_floors = dict(m._AREA_FLOORS)

        def restore():
            for k, v in saved.items():
                setattr(m, k, v)
            m._EXPOSURE.clear()
            m._EXPOSURE.update(saved_exposure)
            m._PROTECTED_SCOPES.clear()
            m._PROTECTED_SCOPES.update(saved_scopes)
            m._AREA_FLOORS.clear()
            m._AREA_FLOORS.update(saved_floors)
        self.addCleanup(restore)
        m.DENIED_SERVICES = []
        m.PROTECTED_ENTITIES = []
        m.EXPOSED_ONLY = False
        m._PROTECTED_SCOPES.update(at=0.0, areas=set(), devices=set())
        m._AREA_FLOORS.update(at=0.0, floors={})
        snap = brain_exposed.index(brain_exposed.snapshot(exposure_ws))
        m._EXPOSURE.update(at=float("inf"), snap=snap)

        self.core = FakeCore()
        self.rest = []

        self.state_reads = []

        def rest(endpoint, method="GET", data=None, accept=None):
            # A state read is the chokepoint recording what an entity was
            # doing before the call (the before-state the ledger carries),
            # not the call reaching Core — kept apart so "reached Core
            # once" still means the service call.
            if method == "GET" and str(endpoint).startswith("/api/states/"):
                self.state_reads.append(endpoint)
                return {"entity_id": endpoint.rsplit("/", 1)[-1],
                        "state": "off", "attributes": {}}
            self.rest.append((endpoint, data))
            return {"ok": True}
        for p in (patch.object(m, "_ws_command", self.core),
                  patch.object(m, "ha_api_request", rest),
                  patch.object(m, "record_action", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def voice(self):
        m.EXPOSED_ONLY = True

    def reached_core(self):
        return [e for e, _ in self.rest] + [
            k for k in self.core.asked if k == "call_service"]

    def refused(self, domain, service, data=None, needle=None):
        got = m.call_service(domain, service, data)
        self.assertIn("error", got, f"{domain}.{service} {data}")
        if needle:
            self.assertIn(needle, got["error"])
        return got["error"]


class TestTheVoiceLevelScopesServices(ChokepointCase):
    """A default voice agent is the one a kitchen satellite talks to."""

    def test_an_entity_less_admin_call_is_refused(self):
        self.voice()
        for domain, service, data in (
            ("homeassistant", "restart", None),
            ("homeassistant", "stop", {}),
            ("homeassistant", "reload_all", {}),
            ("hassio", "host_shutdown", {}),
            ("hassio", "host_reboot", {}),
            ("hassio", "addon_stop", {"addon": "core_ssh"}),
            ("brain", "create_user", {"name": "Guest", "username": "guest",
                                      "password": "pw", "admin": True}),
            ("brain", "delete_integration", {"config_entry_id": "abc",
                                             "dry_run": False}),
            ("recorder", "purge", {"keep_days": 0}),
            ("backup", "create", {}),
            ("shell_command", "anything", {}),
        ):
            with self.subTest(service=f"{domain}.{service}"):
                why = self.refused(domain, service, data, "names no entity")
                self.assertIn("Whole house", why)
        self.assertEqual(self.reached_core(), [])

    def test_it_is_refused_through_the_dispatcher_too(self):
        self.voice()
        got = m.handle_tool_call("call_service", {
            "domain": "homeassistant", "service": "restart"})
        self.assertIn("names no entity", got["error"])
        self.assertEqual(self.reached_core(), [])

    def test_a_meta_call_with_no_target_no_longer_reaches_the_whole_house(self):
        """Before this, `homeassistant.turn_off {}` on voice passed the
        exposure gate — it named nothing to check — and Core read it as
        every entity it has."""
        self.voice()
        self.refused("homeassistant", "turn_off", {}, "names no entity")
        self.assertEqual(self.reached_core(), [])

    def test_an_entity_riding_in_the_payload_is_not_a_target(self):
        self.voice()
        self.refused("hassio", "addon_stop",
                     {"addon": "core_ssh", "data": {"entity_id": "light.kitchen"}},
                     "names no entity")
        self.assertEqual(self.reached_core(), [])

    def test_another_integrations_service_on_an_exposed_entity_is_refused(self):
        self.voice()
        for domain, service in (("brain", "delete_entity"),
                                ("homeassistant", "reload_config_entry"),
                                ("zwave_js", "set_config_parameter"),
                                ("recorder", "purge_entities")):
            with self.subTest(service=f"{domain}.{service}"):
                self.refused(domain, service, {"entity_id": "light.kitchen"},
                             "rather than one of light's own")
        self.assertEqual(self.reached_core(), [])

    def test_update_install_is_administration_even_on_its_own_entity(self):
        self.voice()
        EXPLICIT["update.core"] = True
        self.addCleanup(EXPLICIT.pop, "update.core")
        m._EXPOSURE.update(snap=brain_exposed.index(brain_exposed.snapshot(exposure_ws)))
        self.refused("update", "install", {"entity_id": "update.core"},
                     "administer Home Assistant itself")
        self.assertEqual(self.reached_core(), [])

    def test_what_voice_does_every_day_still_works(self):
        self.voice()
        for domain, service, data in (
            ("light", "turn_on", {"entity_id": "light.kitchen"}),
            ("homeassistant", "turn_off", {"entity_id": "light.kitchen"}),
            ("notify", "mobile_app_phone", {"message": "Dinner"}),
            ("persistent_notification", "create", {"message": "hi"}),
            ("tts", "speak", {"entity_id": "tts.google",
                              "media_player_entity_id": "media_player.den",
                              "message": "Dinner"}),
            ("music_assistant", "play_media", {"entity_id": "media_player.den",
                                               "media_id": "Jazz"}),
            ("media_player", "join", {"entity_id": "media_player.den",
                                      "group_members": ["media_player.den"]}),
        ):
            with self.subTest(service=f"{domain}.{service}"):
                got = m.call_service(domain, service, data)
                self.assertNotIn("error", got)
        self.assertEqual(len(self.rest), 7)

    def test_a_whole_house_agent_is_untouched(self):
        for domain, service in (("homeassistant", "restart"),
                                ("brain", "create_area")):
            got = m.call_service(domain, service, {"name": "Loft"})
            self.assertNotIn("error", got)
        self.assertEqual(len(self.rest), 2)


class TestTheWholePayloadIsRead(ChokepointCase):
    """`entities`, `snapshot_entities`, `group_members`, `*_entity_id` and a
    protected id passed as a script variable all name an entity."""

    def test_scene_apply_cannot_unlock_a_protected_lock(self):
        m.PROTECTED_ENTITIES = ["lock.front_door", "cover.garage_door"]
        for service, data in (
            ("apply", {"entities": {"lock.front_door": "unlocked"}}),
            ("apply", {"entities": {"light.kitchen": "on",
                                    "cover.garage_door": {"state": "open"}}}),
            ("create", {"scene_id": "x",
                        "entities": {"lock.front_door": "unlocked"}}),
            ("create", {"scene_id": "x", "snapshot_entities": ["lock.front_door"]}),
        ):
            with self.subTest(service=service, data=data):
                self.refused("scene", service, data, "protected")
        self.assertEqual(self.reached_core(), [])

    def test_every_other_place_an_entity_can_sit(self):
        m.PROTECTED_ENTITIES = ["lock.front_door", "media_player.nursery"]
        for domain, service, data in (
            ("media_player", "join", {"entity_id": "media_player.den",
                                      "group_members": ["media_player.nursery"]}),
            ("tts", "speak", {"entity_id": "tts.google",
                              "media_player_entity_id": "media_player.nursery"}),
            ("script", "turn_on", {"entity_id": "script.goodnight",
                                   "variables": {"door": "lock.front_door"}}),
        ):
            with self.subTest(service=f"{domain}.{service}"):
                self.refused(domain, service, data, "protected")
        self.assertEqual(self.reached_core(), [])

    def test_the_deny_list_reads_the_scene_map_like_a_meta_call(self):
        m.DENIED_SERVICES = ["lock.unlock", "cover.open_cover"]
        self.refused("scene", "apply",
                     {"entities": {"lock.front_door": "unlocked"}},
                     "lock services are restricted")
        self.refused("scene", "create",
                     {"scene_id": "x", "entities": {"cover.garage": "open"}},
                     "cover services are restricted")
        self.assertEqual(self.reached_core(), [])
        m.call_service("scene", "apply", {"entities": {"light.kitchen": "on"}})
        self.assertEqual(len(self.rest), 1)

    def test_voice_cannot_reach_an_unexposed_lock_through_a_scene_map(self):
        self.voice()
        self.refused("scene", "apply",
                     {"entities": {"lock.front_door": "unlocked"}},
                     "not exposed")
        self.assertEqual(self.reached_core(), [])

    def test_a_file_name_shaped_like_an_entity_is_not_refused(self):
        """`song.mp3` is the shape of an entity id and no entity at all."""
        self.voice()
        got = m.call_service("bright", "start_show",
                             {"track": "song.mp3", "media_player": "media_player.den"})
        self.assertNotIn("error", got)

    def test_the_ledger_now_records_the_scene_map(self):
        named, loose = m._payload_entities({
            "entities": {"light.kitchen": "on", "lock.front_door": "locked"},
            "snapshot_entities": "light.hall, light.kitchen",
            "group_members": ["media_player.den"],
            "media_player_entity_id": "media_player.den",
            "variables": {"who": "person.ben", "file": "song.mp3"}})
        self.assertEqual(named, ["light.kitchen", "lock.front_door", "light.hall",
                                 "media_player.den"])
        self.assertEqual(loose, ["person.ben", "song.mp3"])
        self.assertEqual(
            m._call_entities({"entities": {"light.kitchen": "on"}}, ["script.x"]),
            ["light.kitchen", "script.x"])


class TestAScriptCalledByItsName(ChokepointCase):
    """`script.<object_id>` runs that script and carries no entity id."""

    def test_an_unexposed_script_cannot_be_run_by_name_on_voice(self):
        self.voice()
        self.refused("script", "unlock_door", {}, "script.unlock_door is not exposed")
        self.assertEqual(self.reached_core(), [])

    def test_a_protected_script_cannot_be_run_by_name(self):
        m.PROTECTED_ENTITIES = ["script.unlock_door"]
        self.refused("script", "unlock_door", None, "protected")
        self.assertEqual(self.reached_core(), [])

    def test_a_denied_script_turn_on_covers_the_bare_name(self):
        m.DENIED_SERVICES = ["script.turn_on"]
        self.refused("script", "unlock_door", None, "script.turn_on is not permitted")
        self.assertEqual(self.reached_core(), [])

    def test_the_script_domains_own_services_are_not_scripts(self):
        self.assertIsNone(m._script_service_target("script", "turn_on"))
        self.assertIsNone(m._script_service_target("script", "reload"))
        self.assertIsNone(m._script_service_target("light", "goodnight"))
        self.assertEqual(m._script_service_target("script", "goodnight"),
                         "script.goodnight")


class TestWhatAContainerReaches(ChokepointCase):
    """search/related answers what a script, scene or automation references;
    a protected member refuses the run, and so does an unexposed one on voice."""

    def test_a_scene_holding_the_protected_lock_is_refused(self):
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        self.core.related["scene.movie"] = {
            "entity": ["light.hall", "lock.front_door"],
            "device": ["dev-hall", "dev-lock"], "area": ["hall"],
            "floor": ["ground"]}
        why = self.refused("scene", "turn_on", {"entity_id": "scene.movie"},
                           "scene.movie acts on lock.front_door")
        self.assertIn("protected", why)
        self.assertEqual(self.reached_core(), [])
        # activate_scene is the same call.
        self.assertIn("error", m.activate_scene("scene.movie"))

    def test_every_route_that_runs_one_is_checked(self):
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        for container in ("script.goodnight", "automation.night"):
            self.core.related[container] = {"entity": ["lock.front_door"]}
        for domain, service, data in (
            ("script", "turn_on", {"entity_id": "script.goodnight"}),
            ("script", "toggle", {"target": {"entity_id": ["script.goodnight"]}}),
            ("script", "goodnight", {}),
            ("homeassistant", "turn_on", {"entity_id": "script.goodnight"}),
            ("automation", "trigger", {"entity_id": "automation.night"}),
        ):
            with self.subTest(service=f"{domain}.{service}"):
                self.refused(domain, service, data, "a protected entity")
        self.assertIn("error", m.run_script("script.goodnight"))
        self.assertEqual(self.reached_core(), [])

    def test_stopping_a_script_is_not_running_it(self):
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        self.core.related["script.goodnight"] = {"entity": ["lock.front_door"]}
        got = m.call_service("script", "turn_off", {"entity_id": "script.goodnight"})
        self.assertNotIn("error", got)
        self.assertNotIn("search/related", self.core.asked)

    def test_a_room_with_a_protected_lock_in_it_is_not_a_reason(self):
        """search/related adds the AREA and DEVICE of every referenced entity;
        a script that turns on the hall light lists the hall, and the hall
        holds the protected lock. Refusing on that would refuse every script
        touching anything in that room."""
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        self.core.related["script.goodnight"] = {
            "entity": ["light.hall"], "device": ["dev-hall"],
            "area": ["hall"], "floor": ["ground"]}
        got = m.call_service("script", "turn_on", {"entity_id": "script.goodnight"})
        self.assertNotIn("error", got)
        self.assertEqual(len(self.rest), 1)

    def test_a_script_that_targets_the_room_itself_is_refused(self):
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        self.core.related["script.goodnight"] = {
            "entity": ["light.kitchen"], "area": ["hall"], "floor": ["ground"]}
        self.refused("script", "turn_on", {"entity_id": "script.goodnight"},
                     "targets area hall")
        self.core.related["script.goodnight"] = {
            "entity": ["light.kitchen"], "device": ["dev-lock"], "area": ["hall"]}
        self.refused("script", "turn_on", {"entity_id": "script.goodnight"},
                     "targets device dev-lock")
        self.core.related["script.goodnight"] = {"label": ["guests"]}
        self.refused("script", "turn_on", {"entity_id": "script.goodnight"},
                     "label or floor")
        self.assertEqual(self.reached_core(), [])

    def test_the_containers_own_label_is_not_a_target(self):
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        REGISTRY.append({"entity_id": "script.labelled", "labels": ["evening"]})
        self.addCleanup(REGISTRY.pop)
        self.core.related["script.labelled"] = {"entity": ["light.kitchen"],
                                                "label": ["evening"]}
        got = m.call_service("script", "turn_on", {"entity_id": "script.labelled"})
        self.assertNotIn("error", got)

    def test_members_that_cannot_be_read_refuse_while_anything_is_protected(self):
        """The label/floor rule, and fire_event's: not waved through because
        it could not be checked."""
        m.PROTECTED_ENTITIES = ["lock.front_door"]
        self.core.down = True
        self.refused("scene", "turn_on", {"entity_id": "scene.movie"},
                     "could not be read")
        self.assertEqual(self.reached_core(), [])

    def test_with_nothing_protected_and_no_voice_nothing_is_looked_up(self):
        got = m.call_service("script", "turn_on", {"entity_id": "script.goodnight"})
        self.assertNotIn("error", got)
        self.assertNotIn("search/related", self.core.asked)

    def test_voice_cannot_run_a_script_that_reaches_an_unexposed_entity(self):
        """script.goodnight is exposed (scripts are by default); the lock it
        unlocks is not — REACH_EXPOSED asked the model not to go this way,
        and now the gate says so too."""
        self.voice()
        self.core.related["script.goodnight"] = {"entity": ["lock.front_door"]}
        why = self.refused("script", "turn_on", {"entity_id": "script.goodnight"},
                           "script.goodnight reaches lock.front_door")
        self.assertIn("not exposed", why)
        self.assertEqual(self.reached_core(), [])

    def test_voice_runs_a_script_whose_members_are_all_exposed(self):
        self.voice()
        self.core.related["script.goodnight"] = {
            "entity": ["light.kitchen", "light.hall"], "device": ["dev-hall"],
            "area": ["hall"], "floor": ["ground"]}
        got = m.call_service("script", "goodnight", {})
        self.assertNotIn("error", got)
        self.assertEqual(self.rest[0][0], "/api/services/script/goodnight")

    def test_voice_cannot_run_one_that_acts_through_a_device(self):
        self.voice()
        self.core.related["script.goodnight"] = {"device": ["dev-porch"],
                                                 "area": ["porch"]}
        self.refused("script", "turn_on", {"entity_id": "script.goodnight"},
                     "through an area, device")


class TestTheLedgerAttributesThem(unittest.TestCase):
    def test_scene_apply_and_a_bare_script_name_land_in_the_ledger(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "actions.jsonl")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("BRAIN_CHANNEL", "BRAIN_ASSIST_ACCESS",
                                "BRAIN_EXPOSED_ONLY", "CLAUDE_CODE_SESSION_ID")}
            env["BRAIN_CHANNEL"] = "chat"
            with patch.object(m, "ACTION_LEDGER", path), \
                    patch.dict(os.environ, env, clear=True), \
                    patch.object(m, "ha_api_request", lambda *a, **k: {}), \
                    patch.object(m, "PROTECTED_ENTITIES", []), \
                    patch.object(m, "EXPOSED_ONLY", False):
                m.call_service("scene", "apply",
                               {"entities": {"light.kitchen": "on"}})
                m.call_service("script", "goodnight", {})
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh]
        self.assertEqual(rows[0]["entities"], ["light.kitchen"])
        self.assertEqual(rows[1]["entities"], ["script.goodnight"])
        self.assertEqual({r["channel"] for r in rows}, {"chat"})


if __name__ == "__main__":
    unittest.main()
