"""Emergency playbooks: what brAIn would write, and what it never will.

A playbook is the one automation in the add-on that acts on the whole
house at once, so the tests are about what is NOT in the config at least
as much as what is. Each names the mutation it catches:

  no sensor, no playbook   offer one anyway -> a card about a house that
                           cannot detect the thing it responds to
  locks never appear       add the capability page's "doors unlocked" ->
                           a false smoke alarm opens the house at 3am
  a protected valve        drop the producer-side check -> a card offering
                           a change `automation_writer` will refuse, and
                           no way to see brAIn knew the valve was there
  nothing left to do       propose it anyway -> "playbook" that sends a
                           notification brAIn already sends
  the key follows the set  key on the title -> a declined playbook comes
                           back reworded; or key on nothing -> adding a
                           detector never re-offers
  rehearsal calls nothing  use automation.trigger -> the rehearsal IS the
                           emergency

The rehearsal runs against a real aiohttp server so "it calls nothing"
is measured rather than described.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import playbooks  # noqa: E402
import shadow  # noqa: E402

NOW = 1_800_000_000.0


def st(state="off", **attrs) -> dict:
    return {"state": state, "attributes": attrs}


def house(**over) -> dict:
    """A house with a smoke detector, a leak sensor, and things to act on."""
    snap = {
        "now": NOW,
        "states": {
            "binary_sensor.hall_smoke": st(
                "off", device_class="smoke", friendly_name="Hall smoke"),
            "binary_sensor.kitchen_leak": st(
                "off", device_class="moisture", friendly_name="Kitchen leak"),
            "binary_sensor.hall_motion": st(
                "off", device_class="motion", friendly_name="Hall motion"),
            "light.kitchen": st("off", friendly_name="Kitchen"),
            "light.hall": st("on", friendly_name="Hall"),
            "climate.hall": st("heat", friendly_name="Hall thermostat",
                               hvac_action="idle"),
            "cover.lounge_blind": st("closed", device_class="blind",
                                     friendly_name="Lounge blind"),
            "cover.garage": st("closed", device_class="garage",
                               friendly_name="Garage door"),
            "valve.mains_water": st("open", friendly_name="Mains water"),
            "switch.water_heater_feed": st(
                "on", friendly_name="Water heater feed"),
            "switch.main_bedroom_lamp": st(
                "on", friendly_name="Main bedroom lamp"),
            "water_heater.tank": st("eco", friendly_name="Hot water tank"),
            "lock.front_door": st("locked", friendly_name="Front door"),
            "alarm_control_panel.house": st("armed_home",
                                            friendly_name="House alarm"),
            "sensor.hall_temp": st("18.5", device_class="temperature",
                                   friendly_name="Hall temperature"),
        },
        "entities": [
            {"entity_id": eid, "area_id": "hall"} for eid in
            ("binary_sensor.hall_smoke", "light.hall", "climate.hall",
             "sensor.hall_temp")
        ] + [
            {"entity_id": eid, "area_id": "kitchen"} for eid in
            ("binary_sensor.kitchen_leak", "light.kitchen")
        ],
        "devices": [],
        "areas": [{"area_id": "hall", "name": "Hall"},
                  {"area_id": "kitchen", "name": "Kitchen"}],
        "services": {"notify.mobile_app_phone", "notify.persistent_notification",
                     "light.turn_on", "valve.close_valve"},
        "thermal": {
            "unit": "°C",
            "rooms": {"sensor.hall_temp": {
                "k": 0.12, "coolest": 14.2, "warmest": 22.0,
                "unit": "°C", "area": "Hall"}},
        },
    }
    snap.update(over)
    return snap


def by_class(rows: list[dict]) -> dict:
    return {(r.get("playbook") or {}).get("class"): r for r in rows}


def every_action(obj: dict) -> list[dict]:
    return shadow.would_do(obj["config"])


def every_target(obj: dict) -> list[str]:
    out = []
    for call in every_action(obj):
        entity = call.get("entity_id")
        out += [entity] if isinstance(entity, str) else list(entity or [])
    return out


class TestWhatIsComposed(unittest.TestCase):

    def test_a_house_with_no_sensors_gets_no_playbook(self):
        snap = house()
        snap["states"] = {k: v for k, v in snap["states"].items()
                          if not k.startswith("binary_sensor.")}
        # The thermal room is still there, and freeze needs no detector —
        # so the two that DO need one are the two that must be gone.
        got = by_class(playbooks.build(snap))
        self.assertNotIn("smoke", got)
        self.assertNotIn("leak", got)

    def test_one_smoke_sensor_makes_one_playbook_naming_its_area(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        sensors = smoke["playbook"]["sensors"]
        self.assertEqual([s["entity_id"] for s in sensors],
                         ["binary_sensor.hall_smoke"])
        self.assertEqual(sensors[0]["area"], "Hall")
        self.assertIn("Hall", smoke["why"])

    def test_smoke_turns_lights_up_heating_off_and_blinds_open(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        services = [c["service"] for c in every_action(smoke)]
        self.assertIn("light.turn_on", services)
        self.assertIn("climate.set_hvac_mode", services)
        self.assertIn("cover.open_cover", services)
        self.assertIn("notify.mobile_app_phone", services)
        step = next(s for s in smoke["config"]["action"]
                    if s.get("service") == "light.turn_on")
        self.assertEqual(step["data"], {"brightness_pct": 100})
        self.assertNotIn("color_name", step["data"])

    def test_a_garage_door_is_not_a_blind(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        self.assertNotIn("cover.garage", every_target(smoke))
        self.assertIn("cover.lounge_blind", every_target(smoke))

    def test_a_motion_sensor_is_not_a_smoke_detector(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        self.assertNotIn("binary_sensor.hall_motion",
                         smoke["config"]["trigger"][0]["entity_id"])

    def test_leak_closes_the_water_and_names_what_it_closes(self):
        leak = by_class(playbooks.build(house()))["leak"]
        targets = every_target(leak)
        self.assertIn("valve.mains_water", targets)
        self.assertIn("switch.water_heater_feed", targets)
        self.assertIn("water_heater.tank", targets)
        names = [t["name"] for g in leak["playbook"]["groups"]
                 for t in g["targets"]]
        self.assertIn("Mains water", names)

    def test_a_bedroom_lamp_is_not_a_water_shutoff(self):
        # "main" as a bare word matches `switch.main_bedroom_lamp`, and a
        # leak playbook that turns the bedroom lamp off is one somebody
        # deletes. See WATER_WORDS.
        leak = by_class(playbooks.build(house()))["leak"]
        self.assertNotIn("switch.main_bedroom_lamp", every_target(leak))

    def test_freeze_reads_the_coldest_modelled_room_and_only_notifies(self):
        freeze = by_class(playbooks.build(house()))["freeze"]
        services = [c["service"] for c in every_action(freeze)]
        self.assertEqual(services, ["notify.mobile_app_phone"])
        triggers = freeze["config"]["trigger"]
        self.assertEqual(triggers[0]["entity_id"], "sensor.hall_temp")
        self.assertEqual(triggers[0]["below"], playbooks.FREEZE_C)
        self.assertEqual(triggers[1]["entity_id"], "climate.hall")
        self.assertEqual(triggers[1]["attribute"], "hvac_action")
        # Both halves are conditions too: a cold room in a house whose
        # heating is working is not this finding.
        kinds = {c.get("condition") for c in freeze["config"]["condition"]}
        self.assertEqual(kinds, {"numeric_state", "state"})

    def test_freeze_reads_the_coldest_room_when_there_are_several(self):
        snap = house()
        snap["states"]["sensor.loft_temp"] = st(
            "9.0", device_class="temperature", friendly_name="Loft")
        snap["entities"].append({"entity_id": "sensor.loft_temp",
                                 "area_id": "hall"})
        snap["thermal"]["rooms"]["sensor.loft_temp"] = {
            "k": 0.3, "coolest": 6.0, "unit": "°C", "area": "Hall"}
        room = playbooks.coldest_room(snap)
        self.assertEqual(room["entity_id"], "sensor.loft_temp")

    def test_a_fahrenheit_house_gets_a_fahrenheit_threshold(self):
        snap = house()
        snap["thermal"]["rooms"]["sensor.hall_temp"]["unit"] = "°F"
        freeze = by_class(playbooks.build(snap))["freeze"]
        self.assertEqual(freeze["config"]["trigger"][0]["below"],
                         playbooks.FREEZE_F)

    def test_no_modelled_room_means_no_freeze_playbook(self):
        snap = house()
        snap["thermal"] = {}
        self.assertNotIn("freeze", by_class(playbooks.build(snap)))

    def test_every_config_carries_mode_single_and_its_own_id(self):
        for name, obj in by_class(playbooks.build(house())).items():
            self.assertEqual(obj["config"]["mode"], "single", name)
            self.assertEqual(obj["config"]["id"], f"brain_playbook_{name}")
            self.assertEqual(obj["kind"], "playbook")
            self.assertEqual(obj["source"], "playbook")


class TestNothingUnlocksAnything(unittest.TestCase):
    """The one rule that is not about this house."""

    def test_no_lock_appears_in_any_generated_config(self):
        # Asserted over EVERY action of EVERY playbook rather than over
        # the branch that would have written one: a rule checked where the
        # config is built is a rule that holds for the branches somebody
        # remembered.
        for obj in playbooks.build(house()):
            for target in every_target(obj):
                self.assertFalse(playbooks.is_lock(target),
                                 f"{obj['title']} acts on {target}")
            for call in every_action(obj):
                domain = str(call["service"]).split(".", 1)[0]
                self.assertNotIn(domain, playbooks.LOCK_DOMAINS)

    def test_a_house_of_nothing_but_locks_produces_no_actions(self):
        snap = house()
        snap["states"] = {
            "binary_sensor.hall_smoke": st("off", device_class="smoke"),
            "lock.front_door": st("locked"),
            "lock.back_door": st("locked"),
            "alarm_control_panel.house": st("armed_home"),
        }
        snap["thermal"] = {}
        self.assertEqual(playbooks.build(snap), [])

    def test_the_card_says_so_in_one_sentence(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        self.assertIn("unlock", smoke["playbook"]["note"])

    def test_the_invariant_is_enforced_not_merely_documented(self):
        # Drive the guard directly: a spec that acted on a lock has to
        # raise rather than be published.
        with self.assertRaises(AssertionError):
            playbooks._assert_no_locks({"config": {"action": [
                {"service": "lock.unlock",
                 "target": {"entity_id": "lock.front_door"}}]}})


class TestProtection(unittest.TestCase):

    def test_a_protected_valve_is_listed_and_never_in_the_config(self):
        leak = by_class(playbooks.build(
            house(), ["valve.mains_water"]))["leak"]
        self.assertNotIn("valve.mains_water", every_target(leak))
        skipped = {s["entity_id"]: s for s in leak["playbook"]["skipped"]}
        self.assertIn("valve.mains_water", skipped)
        self.assertEqual(skipped["valve.mains_water"]["reason"], "protected")
        self.assertEqual(skipped["valve.mains_water"]["name"], "Mains water")

    def test_a_protected_domain_wildcard_works_the_same(self):
        smoke = by_class(playbooks.build(house(), ["light.*"]))["smoke"]
        self.assertNotIn("light.kitchen", every_target(smoke))
        self.assertNotIn("light.hall", every_target(smoke))
        self.assertTrue(smoke["playbook"]["skipped"])

    def test_a_playbook_with_nothing_left_to_do_is_not_proposed(self):
        # Everything a leak playbook acts on, protected. What is left is a
        # notification, and brAIn already sends those.
        got = by_class(playbooks.build(house(), [
            "valve.*", "switch.*", "water_heater.*"]))
        self.assertNotIn("leak", got)

    def test_what_the_producer_drops_the_writer_would_have_refused(self):
        # The producer-side check exists so a card never offers something
        # `automation_writer` will refuse — a wasted no.
        import automation_writer

        patterns = ["valve.mains_water"]
        leak = by_class(playbooks.build(house(), patterns))["leak"]
        self.assertIsNone(
            automation_writer._protected_refusal(leak["config"], patterns))
        # And with the drop removed it WOULD have refused.
        unguarded = by_class(playbooks.build(house()))["leak"]
        self.assertIsNotNone(
            automation_writer._protected_refusal(unguarded["config"], patterns))


class TestTheKeyFollowsTheSensors(unittest.TestCase):

    def key(self, snap, name="smoke", patterns=()):
        import proposals

        return proposals.key_for(by_class(playbooks.build(snap, list(patterns)))[name])

    def test_the_same_house_gives_the_same_key(self):
        self.assertEqual(self.key(house()), self.key(house()))

    def test_adding_a_detector_changes_the_key(self):
        # The mutation: key on the title. A declined playbook would never
        # be re-offered after somebody fits a second detector, which is
        # exactly when it should be.
        more = house()
        more["states"]["binary_sensor.loft_smoke"] = st(
            "off", device_class="smoke", friendly_name="Loft smoke")
        self.assertNotEqual(self.key(house()), self.key(more))

    def test_rewording_the_card_does_not_change_the_key(self):
        import proposals

        obj = by_class(playbooks.build(house()))["smoke"]
        first = proposals.key_for(obj)
        obj["why"] = "an entirely different sentence about the same change"
        obj["title"] = "Renamed"
        self.assertEqual(proposals.key_for(obj), first)

    def test_protecting_a_light_changes_the_key(self):
        self.assertNotEqual(self.key(house()),
                            self.key(house(), patterns=["light.kitchen"]))


class TestTheCardPayload(unittest.TestCase):

    def test_the_payload_survives_the_store(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BRAIN_PROPOSALS_FILE"] = f"{tmp}/p.json"
            os.environ["BRAIN_PROPOSALS_SETTLED"] = f"{tmp}/s.json"
            os.environ["BRAIN_PROPOSALS_SHARED"] = f"{tmp}/no/brain/x.json"
            sys.modules.pop("proposals", None)
            try:
                proposals = importlib.import_module("proposals")
                obj = by_class(playbooks.build(house()))["smoke"]
                row = proposals.add(obj)
                self.assertIsNotNone(row)
                back = json.loads(Path(f"{tmp}/p.json").read_text())
                stored = back["proposals"][0]["playbook"]
                self.assertEqual(stored["class"], "smoke")
                self.assertTrue(stored["groups"])
                self.assertIn("unlock", stored["note"])
                self.assertIn("trial", stored["no_trial"])
            finally:
                for key in ("BRAIN_PROPOSALS_FILE", "BRAIN_PROPOSALS_SETTLED",
                            "BRAIN_PROPOSALS_SHARED"):
                    os.environ.pop(key, None)
                sys.modules.pop("proposals", None)

    def test_the_written_automation_keeps_the_playbooks_own_id(self):
        import automation_writer

        obj = by_class(playbooks.build(house()))["smoke"]
        entry = automation_writer.entry_for({**obj, "ts": 1720}, NOW)
        self.assertEqual(entry["id"], "brain_playbook_smoke")

    def test_an_id_that_is_not_ours_is_refused_and_replaced(self):
        # A config off the wire may not claim an arbitrary id: the
        # duplicate-id refusal is what makes a stable one safe, and it
        # only works while every id brAIn writes is brAIn's.
        import automation_writer

        row = {"ts": 1720, "title": "x",
               "config": {"id": "somebody_elses", "trigger": [], "action": []}}
        self.assertEqual(automation_writer.entry_for(row, NOW)["id"],
                         "brain_1720")

    def test_a_routine_still_gets_its_timestamp_id(self):
        import automation_writer

        row = {"ts": 1720, "title": "x", "config": {"trigger": [], "action": []}}
        self.assertEqual(automation_writer.entry_for(row, NOW)["id"],
                         "brain_1720")


class TestNotifyTargets(unittest.TestCase):

    def test_the_configured_service_wins(self):
        self.assertEqual(playbooks.notify_targets(house(), "notify.family"),
                         ["notify.family"])
        self.assertEqual(playbooks.notify_targets(house(), "family"),
                         ["notify.family"])

    def test_with_none_configured_every_companion_app_is_told(self):
        snap = house()
        snap["services"] |= {"notify.mobile_app_tablet", "notify.slack"}
        self.assertEqual(playbooks.notify_targets(snap),
                         ["notify.mobile_app_phone", "notify.mobile_app_tablet"])

    def test_the_message_names_the_room_the_sensor_is_in(self):
        smoke = by_class(playbooks.build(house()))["smoke"]
        step = next(s for s in smoke["config"]["action"]
                    if str(s.get("service", "")).startswith("notify."))
        self.assertIn("area_name(trigger.entity_id)", step["data"]["message"])


class TestRehearsal(unittest.IsolatedAsyncioTestCase):
    """It reports; it does not run. Measured, not described."""

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        self.posts: list[str] = []
        self.states = [
            {"entity_id": "light.hall", "state": "on"},
            {"entity_id": "light.kitchen", "state": "off"},
            {"entity_id": "climate.hall", "state": "heat"},
            {"entity_id": "cover.lounge_blind", "state": "closed"},
        ]

        async def states(request):
            return web.json_response(self.states)

        async def anything_else(request):
            self.posts.append(request.path)
            return web.json_response([])

        core = web.Application()
        core.router.add_get("/states", states)
        core.router.add_route("*", "/{tail:.*}", anything_else)
        self.core = TestServer(core)
        await self.core.start_server()
        self.addAsyncCleanup(self.core.close)

        import ha_data
        self.ha_data = ha_data
        self._core_api = ha_data.CORE_API
        ha_data.CORE_API = str(self.core.make_url("")).rstrip("/")
        self.addCleanup(self._restore)

        self.server = importlib.import_module("server")
        self.obj = by_class(playbooks.build(house()))["smoke"]
        self.row = {**self.obj, "ts": 1720, "status": "proposed"}
        self._get = self.server.proposals.get
        self.server.proposals.get = lambda ts: (
            self.row if ts == 1720 else None)
        self.addCleanup(lambda: setattr(self.server.proposals, "get", self._get))

        import asyncio
        self.server.QUEUE = asyncio.Queue()
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def _restore(self):
        self.ha_data.CORE_API = self._core_api

    async def test_it_reports_every_call_with_the_state_now(self):
        resp = await self.client.get("/api/playbook/1720/rehearsal")
        self.assertEqual(resp.status, 200)
        out = await resp.json()
        self.assertEqual(out["class"], "smoke")
        lights = next(g for g in out["groups"]
                      if g["service"] == "light.turn_on")
        self.assertEqual(lights["count"], 2)
        self.assertEqual(lights["already"], 1)   # light.hall is on
        states = {t["entity_id"]: t["state"] for t in lights["targets"]}
        self.assertEqual(states["light.hall"], "on")
        self.assertEqual(states["light.kitchen"], "off")

    async def test_it_calls_nothing(self):
        # The mutation: reach for `automation.trigger`. That would run the
        # actions, which is not a rehearsal — it is the emergency.
        await self.client.get("/api/playbook/1720/rehearsal")
        self.assertEqual(self.posts, [])
        self.assertTrue((await (await self.client.get(
            "/api/playbook/1720/rehearsal")).json())["executes_nothing"])

    async def test_an_unknown_state_is_reported_as_unknown(self):
        self.states = []
        out = await (await self.client.get(
            "/api/playbook/1720/rehearsal")).json()
        lights = next(g for g in out["groups"]
                      if g["service"] == "light.turn_on")
        self.assertEqual(lights["already"], 0)
        self.assertTrue(all(t["state"] == "unknown"
                            for t in lights["targets"]))

    async def test_a_proposal_that_is_not_a_playbook_is_a_404(self):
        self.row = {"ts": 1720, "title": "a routine", "config": {}}
        resp = await self.client.get("/api/playbook/1720/rehearsal")
        self.assertEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
