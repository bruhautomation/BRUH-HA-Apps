#!/usr/bin/env python3
"""Tidy — names, rooms and aliases, proposed by one press and applied by another.

What is driven, and against what:

  * `parse` over replies that break each rule (an id nobody was asked
    about, a room that does not exist, a protected entity, a name that is
    still hardware, two rows proposing one name) — every refusal is shown
    refusing, with the sentence it gives;
  * `area_reach` naming the automations whose area targets a move changes,
    and NOT naming one whose service domain the moved thing does not have;
  * Apply and Undo over a real WebSocket server speaking Core's handshake
    (`fake_core_ws`), because what Apply records for Undo is what Core
    ANSWERED, and what Undo restores depends on what Core holds NOW — a
    fake at the helper could show neither;
  * the press itself through the real route and the real runner, with only
    `engine.run_claude` and the registry read stubbed.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import ha_data  # noqa: E402
import tidy  # noqa: E402
from fake_core_ws import FakeCore, drive_app, ok, refused  # noqa: E402


def house() -> dict:
    """A small house: one plug still named after its IEEE, a lamp in no
    room, a well-named kitchen light, and a lock on the protected list."""
    return {
        "states": {
            "switch.plug_00158d0004a1b2c3": {
                "state": "on", "attributes": {
                    "friendly_name": "Plug 00158d0004a1b2c3"}},
            "light.lamp": {"state": "off", "attributes": {
                "friendly_name": "Lamp"}},
            "light.kitchen_ceiling": {"state": "on", "attributes": {
                "friendly_name": "Kitchen ceiling"}},
            "lock.front_door": {"state": "locked", "attributes": {
                "friendly_name": "Front door"}},
            "sensor.plug_power": {"state": "3", "attributes": {
                "friendly_name": "Plug power"}},
        },
        "entities": [
            {"entity_id": "switch.plug_00158d0004a1b2c3", "device_id": "dev-plug"},
            {"entity_id": "sensor.plug_power", "device_id": "dev-plug",
             "entity_category": "diagnostic"},
            {"entity_id": "light.lamp", "device_id": "dev-lamp"},
            {"entity_id": "light.kitchen_ceiling", "device_id": "dev-k",
             "area_id": "kitchen"},
            {"entity_id": "lock.front_door", "device_id": "dev-lock"},
        ],
        "devices": [
            {"id": "dev-plug", "name": "Plug 00158d0004a1b2c3", "area_id": "lounge"},
            {"id": "dev-lamp", "name": "Lamp"},
            {"id": "dev-k", "name": "Kitchen ceiling", "area_id": "kitchen"},
            {"id": "dev-lock", "name": "Front door lock"},
        ],
        "areas": [{"area_id": "kitchen", "name": "Kitchen"},
                  {"area_id": "lounge", "name": "Lounge"},
                  {"area_id": "hall", "name": "Hall"}],
        "automations": [
            {"id": "lights-out", "alias": "Lounge lights out",
             "actions": [{"action": "light.turn_off",
                          "target": {"area_id": "lounge"}}]},
            {"id": "warm-lounge", "alias": "Warm the lounge",
             "actions": [{"action": "climate.set_temperature",
                          "target": {"area_id": "lounge"}}]},
        ],
    }


def row(kind, target, subject, value, why="seen"):
    return {"kind": kind, "target": target, "id": subject, "value": value,
            "why": why}


class TestTheDigest(unittest.TestCase):
    def test_hardware_names_come_first_and_style_is_the_house_own(self):
        dig = tidy.digest(house())
        ids = [e["id"] for e in dig["entities"]]
        self.assertEqual(ids[0], "switch.plug_00158d0004a1b2c3")
        self.assertTrue(dig["entities"][0]["hardware"])
        # A diagnostic entity is not in a picker and is not offered.
        self.assertNotIn("sensor.plug_power", ids)
        self.assertIn("Kitchen ceiling", [s["name"] for s in dig["style"]])
        self.assertNotIn("Plug 00158d0004a1b2c3", [s["name"] for s in dig["style"]])
        self.assertEqual([d["id"] for d in dig["devices"]],
                         ["dev-lamp", "dev-lock"])


class TestWhatMayComeBack(unittest.TestCase):
    def parse(self, rows, patterns=()):
        snap = house()
        return tidy.parse({"rows": rows}, tidy.digest(snap), snap,
                          list(patterns))

    def test_a_good_rename_becomes_a_row(self):
        out = self.parse([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                              "Lounge plug")])
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["id"], "r0")
        self.assertEqual(out["rows"][0]["before_label"], "Plug 00158d0004a1b2c3")

    def test_an_id_nobody_was_asked_about_is_refused(self):
        out = self.parse([row("name", "entity", "light.invented", "Invented")])
        self.assertEqual(out["rows"], [])
        self.assertIn("not asked", out["refused"][0]["refused"])

    def test_a_room_that_does_not_exist_is_refused(self):
        out = self.parse([row("area", "device", "dev-lamp", "Conservatory")])
        self.assertEqual(out["rows"], [])
        self.assertIn("does not exist", out["refused"][0]["refused"])

    def test_a_room_can_be_named_by_its_name_and_lands_as_its_id(self):
        out = self.parse([row("area", "device", "dev-lamp", "hall")])
        self.assertEqual(out["rows"][0]["value"], "hall")
        self.assertEqual(out["rows"][0]["area_name"], "Hall")

    def test_a_protected_entity_is_never_touched(self):
        out = self.parse([row("alias", "entity", "lock.front_door", "the door"),
                          row("area", "device", "dev-lock", "hall")],
                         patterns=["lock.front_door"])
        self.assertEqual(out["rows"], [])
        self.assertEqual(len(out["refused"]), 2)
        self.assertTrue(all("protected" in r["refused"] for r in out["refused"]))

    def test_a_name_that_is_still_hardware_is_refused(self):
        out = self.parse([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                              "Plug 00:15:8d:00:04:a1")])
        self.assertIn("hardware", out["refused"][0]["refused"])

    def test_a_name_another_light_already_answers_to_is_refused(self):
        out = self.parse([row("name", "entity", "light.lamp", "Kitchen ceiling")])
        self.assertIn("already called", out["refused"][0]["refused"])

    def test_two_rows_proposing_one_name_keep_the_first(self):
        out = self.parse([row("name", "entity", "light.lamp", "Reading light"),
                          row("name", "entity", "switch.plug_00158d0004a1b2c3",
                              "reading LIGHT")])
        # Different domains: both stand — "reading light" as a switch and
        # as a light are not the same Assist target.
        self.assertEqual(len(out["rows"]), 2)
        out = self.parse([row("name", "entity", "light.lamp", "Reading light"),
                          row("name", "entity", "light.lamp", "reading LIGHT")])
        self.assertEqual(len(out["rows"]), 1)
        self.assertIn("same name", out["refused"][0]["refused"])

    def test_no_change_is_not_a_refusal_and_not_a_row(self):
        out = self.parse([row("name", "entity", "light.lamp", "lamp")])
        self.assertEqual((out["rows"], out["refused"]), ([], []))

    def test_rubbish_is_dropped_and_counted(self):
        out = self.parse(["not a row", {"kind": "rename"}])
        self.assertEqual(out["dropped"], 2)

    def test_the_table_is_capped(self):
        many = [row("alias", "entity", "switch.plug_00158d0004a1b2c3", f"plug {i}")
                for i in range(tidy.MAX_ROWS + 20)]
        out = self.parse(many)
        self.assertLessEqual(len(out["rows"]), tidy.MAX_ROWS)
        self.assertLessEqual(len([r for r in out["rows"] if r["kind"] == "alias"]),
                             tidy.MAX_ALIASES_PER_ENTITY)


class TestAnAreaMoveSaysWhatItChanges(unittest.TestCase):
    def test_a_light_into_the_lounge_names_the_lights_out_automation(self):
        reach = tidy.area_reach(house(), "device", "dev-lamp", "", "lounge")
        self.assertEqual([r["id"] for r in reach], ["lights-out"])
        self.assertEqual(reach[0]["change"], "will now reach it")
        self.assertEqual(reach[0]["area"], "Lounge")

    def test_a_climate_action_does_not_reach_a_light(self):
        reach = tidy.area_reach(house(), "device", "dev-lamp", "", "lounge")
        self.assertNotIn("warm-lounge", [r["id"] for r in reach])

    def test_moving_out_says_it_stops_reaching(self):
        reach = tidy.area_reach(house(), "device", "dev-plug", "lounge", "hall")
        # The plug's switch is not a light: lights-out never reached it.
        self.assertEqual(reach, [])
        snap = house()
        snap["automations"].append({"id": "all-off", "alias": "Everything off",
                                    "actions": [{"action": "homeassistant.turn_off",
                                                 "target": {"area_id": "lounge"}}]})
        reach = tidy.area_reach(snap, "device", "dev-plug", "lounge", "hall")
        self.assertEqual(reach[0]["change"], "will stop reaching it")

    def test_parse_puts_the_reach_on_the_row(self):
        snap = house()
        out = tidy.parse({"rows": [row("area", "device", "dev-lamp", "lounge")]},
                         tidy.digest(snap), snap, [])
        self.assertEqual(out["rows"][0]["reach"][0]["alias"], "Lounge lights out")


class StoreCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "tidy.json")
        self.registry = {
            "switch.plug_00158d0004a1b2c3": {"name": None, "area_id": None,
                                             "aliases": []},
            "light.lamp": {"name": None, "area_id": None, "aliases": ["lamp"]},
        }
        self.devices = {"dev-lamp": {"id": "dev-lamp", "name": "Lamp",
                                     "name_by_user": None, "area_id": None}}
        self.refuse_update_for: set[str] = set()

        def get(cmd):
            entry = self.registry.get(cmd["entity_id"])
            return ok({"entity_id": cmd["entity_id"], **entry}) if entry else refused("not found")

        def update(cmd):
            if cmd["entity_id"] in self.refuse_update_for:
                return refused("Entity is not editable")
            entry = self.registry[cmd["entity_id"]]
            for k in ("name", "area_id", "aliases"):
                if k in cmd:
                    entry[k] = cmd[k]
            return ok({"entity_entry": entry})

        def dev_update(cmd):
            dev = self.devices[cmd["device_id"]]
            for k in ("name_by_user", "area_id"):
                if k in cmd:
                    dev[k] = cmd[k]
            return ok(dev)

        self.core = await FakeCore({
            "config/entity_registry/get": get,
            "config/entity_registry/update": update,
            "config/device_registry/list": lambda c: ok(list(self.devices.values())),
            "config/device_registry/update": dev_update,
        }).start()
        self._ws = ha_data.CORE_WS
        ha_data.CORE_WS = self.core.url

    async def asyncTearDown(self):
        ha_data.CORE_WS = self._ws
        await self.core.close()
        self.tmp.cleanup()

    def propose(self, rows):
        snap = house()
        parsed = tidy.parse({"rows": rows}, tidy.digest(snap), snap, [])
        tidy.save_proposal(parsed, path=self.path, now=1000.0)
        return parsed

    async def call(self, fn, *args, **kw):
        import aiohttp
        async with aiohttp.ClientSession() as session:
            return await fn(session, *args, path=self.path, **kw)


class TestApplyAndUndo(StoreCase):
    async def test_apply_writes_what_was_ticked_and_records_before(self):
        self.propose([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                          "Lounge plug"),
                      row("alias", "entity", "light.lamp", "big light"),
                      row("area", "device", "dev-lamp", "hall")])
        result = await self.call(tidy.apply, ["r0", "r1", "r2"], now=2000.0)
        self.assertEqual(len(result["applied"]), 3)
        self.assertEqual(self.registry["switch.plug_00158d0004a1b2c3"]["name"],
                         "Lounge plug")
        self.assertEqual(self.registry["light.lamp"]["aliases"],
                         ["lamp", "big light"])
        self.assertEqual(self.devices["dev-lamp"]["area_id"], "hall")
        entry = next(e for e in result["batch"]["entries"]
                     if e["subject"] == "switch.plug_00158d0004a1b2c3")
        self.assertEqual(entry["before"], {"name": None})
        # The rows that landed left the table.
        self.assertEqual(tidy.load(self.path)["proposal"]["rows"], [])

    async def test_an_unticked_row_is_not_written(self):
        self.propose([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                          "Lounge plug"),
                      row("alias", "entity", "light.lamp", "big light")])
        await self.call(tidy.apply, ["r1"], now=2000.0)
        self.assertIsNone(self.registry["switch.plug_00158d0004a1b2c3"]["name"])
        self.assertNotIn("config/entity_registry/update",
                         [a["type"] for a in self.core.asked
                          if a.get("entity_id") == "switch.plug_00158d0004a1b2c3"])
        left = tidy.load(self.path)["proposal"]["rows"]
        self.assertEqual([r["id"] for r in left], ["r0"])

    async def test_a_refusal_is_not_recorded_for_undo(self):
        self.propose([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                          "Lounge plug"),
                      row("alias", "entity", "light.lamp", "big light")])
        self.refuse_update_for.add("light.lamp")
        result = await self.call(tidy.apply, ["r0", "r1"], now=2000.0)
        self.assertEqual([e["subject"] for e in result["batch"]["entries"]],
                         ["switch.plug_00158d0004a1b2c3"])
        self.assertIn("not editable", result["skipped"][0]["why"])

    async def test_undo_restores_and_keeps_a_newer_change(self):
        self.propose([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                          "Lounge plug"),
                      row("area", "device", "dev-lamp", "hall"),
                      row("alias", "entity", "light.lamp", "big light")])
        result = await self.call(tidy.apply, ["r0", "r1", "r2"], now=2000.0)
        batch = result["batch"]["id"]
        # Somebody renamed the plug again since, and added an alias of
        # their own to the lamp.
        self.registry["switch.plug_00158d0004a1b2c3"]["name"] = "Telly plug"
        self.registry["light.lamp"]["aliases"].append("reading lamp")
        undone = await self.call(tidy.undo, batch, now=3000.0)
        self.assertEqual(undone["error"], "")
        self.assertEqual(self.registry["switch.plug_00158d0004a1b2c3"]["name"],
                         "Telly plug")
        self.assertIn("changed again", undone["kept"][0]["why"])
        self.assertIsNone(self.devices["dev-lamp"]["area_id"])
        # Only the alias this batch added went; theirs stayed.
        self.assertEqual(self.registry["light.lamp"]["aliases"],
                         ["lamp", "reading lamp"])
        again = await self.call(tidy.undo, batch, now=3001.0)
        self.assertEqual(again["error"], "already undone")

    async def test_undo_ends_after_thirty_days(self):
        self.propose([row("name", "entity", "switch.plug_00158d0004a1b2c3",
                          "Lounge plug")])
        result = await self.call(tidy.apply, ["r0"], now=2000.0)
        late = 2000.0 + tidy.UNDO_DAYS * 86400 + 1
        out = await self.call(tidy.undo, result["batch"]["id"], now=late)
        self.assertIn("older than", out["error"])
        self.assertEqual(tidy.undoable(tidy.load(self.path)["batches"], late), [])
        self.assertEqual(len(tidy.undoable(tidy.load(self.path)["batches"], 2500.0)), 1)


class TestThePress(unittest.TestCase):
    """The route and the runner, real, with the CLI and the registry read
    stubbed — `test_resident_loop`'s arrangement."""

    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (tidy.STORE, server.engine.run_claude,
                     server.engine.get_auth,
                     server.checks.snapshot.collect_rooms)
        tidy.STORE = str(Path(self.tmp.name) / "tidy.json")
        self.prompts: list[dict] = []

        def fake_run(prompt, system, model="", timeout=0, max_turns=0,
                     source="", **kw):
            self.prompts.append({"prompt": prompt, "source": source, **kw})
            return {"ok": True, "error": "", "meta": {"session_id": "t-1"},
                    "text": json.dumps({"rows": [
                        row("name", "entity", "switch.plug_00158d0004a1b2c3",
                            "Lounge plug"),
                        row("name", "entity", "light.not_in_the_digest", "X")]})}

        async def fake_rooms(now=None):
            return house()

        server.engine.run_claude = fake_run
        server.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        server.checks.snapshot.collect_rooms = fake_rooms
        server.MAINT_STATE["tidy"].update(running=False, last_error="")

    def tearDown(self):
        (tidy.STORE, self.server.engine.run_claude,
         self.server.engine.get_auth,
         self.server.checks.snapshot.collect_rooms) = self._old
        self.tmp.cleanup()

    def test_the_runner_saves_only_what_passed(self):
        asyncio.run(self.server._run_tidy())
        proposal = tidy.load()["proposal"]
        self.assertEqual([r["subject"] for r in proposal["rows"]],
                         ["switch.plug_00158d0004a1b2c3"])
        self.assertEqual(len(proposal["refused"]), 1)
        self.assertEqual(proposal["run_id"], "t-1")
        # The job reached the runner, and the run carried the schema.
        self.assertEqual(self.prompts[0]["job"], "tidy")
        self.assertEqual(self.prompts[0]["source"], "maintenance")
        self.assertIs(self.prompts[0]["schema"], tidy.SCHEMA)

    def test_a_press_without_a_credential_spends_nothing(self):
        self.server.engine.get_auth = lambda: None

        async def go(client):
            res = await client.post("/api/tidy/run")
            return res.status

        self.assertEqual(drive_app(self.server.make_app, go), 400)
        self.assertEqual(self.prompts, [])

    def test_two_presses_in_one_tick_start_one_run(self):
        seen = []

        async def go():
            seen.append(self.server._maint_start("tidy", self.server._run_tidy))
            seen.append(self.server._maint_start("tidy", self.server._run_tidy))
            await asyncio.sleep(0.05)

        asyncio.run(go())
        self.assertEqual(seen, [True, False])

    def test_the_hardware_name_check_offers_the_tidy_run(self):
        import answers
        case = {"id": "f:1", "kind": "problem", "status": "open",
                "finding_status": "open",
                "origin": {"store": "findings", "key": 1},
                "source": "check:reg.hardware_name", "fixable": True, "plan": {}}
        got = answers.answers(case)
        self.assertEqual(got[0]["route"], "/api/tidy/run")
        # Plan, never Apply: the run drafts a table and changes nothing.
        self.assertEqual(got[0]["label"], "Plan")
        self.assertEqual([a["verb"] for a in got],
                         ["fix", "not_now", "wrong"])


if __name__ == "__main__":
    unittest.main()
