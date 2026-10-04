#!/usr/bin/env python3
"""An approved plan is carried out as the ops it lists, and only those.

Driven through the routes with the REAL writers: the edit goes through
`automation_writer.apply_edit` into a real `automations.yaml`, the journal
line is the real snapshot, the ledger row is the real file `actions` reads.
Only Core is faked — the service call, the state read, the registry — and
`engine.run_agent` FAILS the test unless a case opts in, because "a
deterministic plan never spawns a tool-enabled run" is a claim about the
process and not about a prompt.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import actions  # noqa: E402
import findings_store  # noqa: E402
import interventions  # noqa: E402
import security  # noqa: E402
import typed_fix  # noqa: E402
import unfix  # noqa: E402

from test_fix_plan import FixCase, record_a_call  # noqa: E402

ORIGINAL = """# my automations
- id: '1700000000000'
  alias: Hall lights
  triggers:
  - trigger: state
    entity_id: binary_sensor.hall_old
  actions:
  - action: light.turn_on
    target:
      entity_id: light.hall
- id: other
  alias: Other
  triggers: []
  actions: []
"""
NEW_CONFIG = {"id": "1700000000000", "alias": "Hall lights",
              "triggers": [{"trigger": "state",
                            "entity_id": "binary_sensor.hall"}],
              "actions": [{"action": "light.turn_on",
                           "target": {"entity_id": "light.hall"}}]}
EDIT = {"op": "edit_automation", "id": "1700000000000",
        "new_config": NEW_CONFIG}


def plan(ops, **extra):
    return json.dumps({"can_fix": True, "needs_you": False, "ops": ops,
                       "steps": ["prose the panel will ignore"],
                       "summary": "Its trigger points at a renamed sensor.",
                       "risk": "none", **extra})


class TypedCase(FixCase):
    def _everywhere(self, modules, name, value):
        """Set one attribute on every copy of a module the code may hold.

        Several test files pop and re-import panel modules, so in a full run
        the module the server writes through can be a different object from
        the one this file imported — patching only ours is a patch the code
        under test never sees (CLAUDE.md, on `self.server.<module>`)."""
        for mod in {id(m): m for m in modules}.values():
            self._restores.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)

    def setUp(self):
        super().setUp()
        tmp = Path(self.tmp.name)
        import automation_writer
        import plan_ops
        import test_fix_plan
        self._restores = []
        # The values FixCase chose, read off the copy it patched — never off
        # whichever copy `import` hands back now, which may be another one.
        chosen = test_fix_plan.automation_writer
        writers = [automation_writer, chosen, self.server.automation_writer,
                   typed_fix.automation_writer, unfix.automation_writer,
                   plan_ops.automation_writer,
                   self.server.typed_fix.automation_writer,
                   self.server.unfix.automation_writer,
                   self.server.plan_ops.automation_writer]
        for name in ("CONFIG_DIR", "JOURNAL_DIR", "SNAP_DIR", "INDEX"):
            self._everywhere(writers, name, getattr(chosen, name))
        self._everywhere([actions, test_fix_plan.actions, self.server.actions,
                          unfix.actions, self.server.unfix.actions],
                         "LEDGER_FILE", str(self.ledger))
        self._everywhere([interventions, self.server.interventions], "FILE",
                         tmp / "interventions.jsonl")
        self._everywhere([security, self.server.security], "HONEYTOKEN_FILE",
                         tmp / "brain" / "honeytoken.json")
        (self.config / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n")
        self.automations = self.config / "automations.yaml"
        self.automations.write_text(ORIGINAL)
        self._typed_olds = (interventions.FILE, security.HONEYTOKEN_FILE,
                            self.server._replay_config,
                            self.server._registry_entity_id,
                            self.server._wait_for_entity,
                            self.server.RESTORE_SETTLE_S,
                            os.environ.get("BRAIN_PROTECTED_ENTITIES"))
        self.server.RESTORE_SETTLE_S = 0
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)

        async def no_replay(session, config, start, end, tz):
            return {"would_run": 2, "triggered": 2, "days": 7.0}

        async def registered(unique_id, platform="automation"):
            return "automation.hall_lights", True

        async def there(entity_id):
            return True

        self.server._replay_config = no_replay
        self.server._registry_entity_id = registered
        self.server._wait_for_entity = there
        # Core, as the panel reaches it.
        import ha_data
        self.ha_data = ha_data
        self._ha_olds = (ha_data.call_core_service, ha_data.entity_state)
        self.core_calls = []
        self.fail_service = None
        self.states = {"light.hall": {"state": "on", "attributes": {
            "brightness": 200, "friendly_name": "Hall"}}}

        async def call(domain, service, data=None, timeout=30):
            self.core_calls.append((domain, service, data or {}))
            if self.fail_service == (domain, service):
                raise RuntimeError("Core said no")
            if (domain, service) == ("scene", "apply"):
                for eid, target in (data or {}).get("entities", {}).items():
                    self.states[eid] = {"state": target["state"],
                                        "attributes": {}}
            return []

        async def state(entity_id, timeout=15):
            return self.states.get(entity_id)

        ha_data.call_core_service = call
        ha_data.entity_state = state

    def tearDown(self):
        (interventions.FILE, security.HONEYTOKEN_FILE,
         self.server._replay_config, self.server._registry_entity_id,
         self.server._wait_for_entity, self.server.RESTORE_SETTLE_S,
         protected) = self._typed_olds
        if protected is None:
            os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        else:
            os.environ["BRAIN_PROTECTED_ENTITIES"] = protected
        self.ha_data.call_core_service, self.ha_data.entity_state = \
            self._ha_olds
        for mod, name, value in reversed(self._restores):
            setattr(mod, name, value)
        super().tearDown()

    def planned_row(self, reply):
        self.analyst_reply = reply
        row = self.file_finding("the hall automation can never fire")

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)

        self.drive(body)
        return findings_store.get(row["ts"])

    def apply(self, row):
        async def body(client):
            res = await self.press(row["ts"], "apply", client)
            if res.status == 200:
                await self.work(client)
            return res.status

        status = self.drive(body)
        return status, findings_store.get(row["ts"])


class TestThePreviewShowsTheChange(TypedCase):
    def test_an_edit_carries_its_diff_and_both_replays(self):
        row = self.planned_row(plan([EDIT]))
        self.assertEqual(row["status"], "planned")
        self.assertTrue(row["plan"]["can_fix"], row["plan"])
        preview = row["plan"]["preview"][0]
        self.assertIn("-    entity_id: binary_sensor.hall_old", preview["diff"])
        self.assertIn("+    entity_id: binary_sensor.hall", preview["diff"])
        self.assertEqual(preview["replay"]["would_run"], 2)
        self.assertIn("replay_before", preview)
        # Nothing was written by planning.
        self.assertEqual(self.automations.read_text(), ORIGINAL)
        self.assertEqual(self.core_calls, [])

    def test_an_edit_brain_cannot_locate_is_not_offered(self):
        row = self.planned_row(plan([{**EDIT, "id": "missing",
                                      "new_config": {**NEW_CONFIG,
                                                     "id": "missing"}}]))
        self.assertFalse(row["plan"]["can_fix"])
        self.assertEqual(row["plan"]["ops"], [])
        self.assertIn("no automation with the id missing",
                      row["plan"]["summary"])

    def test_a_protected_entity_is_refused_at_the_plan(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.hall"
        row = self.planned_row(plan([{
            "op": "call_service", "domain": "light", "service": "turn_off",
            "entity_id": "light.hall"}]))
        self.assertFalse(row["plan"]["can_fix"])
        self.assertIn("protected", row["plan"]["summary"])

    def test_the_tripwire_is_refused_at_the_plan(self):
        security.HONEYTOKEN_FILE.parent.mkdir(parents=True)
        security.HONEYTOKEN_FILE.write_text(json.dumps({
            "entities": ["input_boolean.brain_honeytoken"],
            "created": [{"entity_id": "input_boolean.brain_honeytoken"}]}))
        row = self.planned_row(plan([{
            "op": "call_service", "domain": "input_boolean",
            "service": "turn_on",
            "entity_id": "input_boolean.brain_honeytoken"}]))
        self.assertFalse(row["plan"]["can_fix"])
        self.assertIn("tripwire", row["plan"]["summary"])


class TestThePanelMakesTheDeterministicChanges(TypedCase):
    def test_an_edit_and_a_reload_never_spawn_the_agent(self):
        row = self.planned_row(plan([EDIT, {"op": "reload",
                                            "domain": "automation"}],
                                    verify_by={"kind": "trace_within_h",
                                               "automation":
                                               "automation.hall_lights",
                                               "hours": 48}))
        status, row = self.apply(row)
        self.assertEqual(status, 200)
        self.assertEqual(self.agent_calls, [], "a deterministic plan ran Claude")
        self.assertEqual(row["status"], "fixed", row.get("result"))
        text = self.automations.read_text()
        self.assertIn("entity_id: binary_sensor.hall\n", text)
        self.assertTrue(text.startswith("# my automations\n"),
                        "every byte outside the entry stays")
        self.assertIn(("automation", "reload", {}), self.core_calls)
        recorded = interventions.for_finding(row["ts"])
        self.assertEqual(recorded["status"], "watching")
        self.assertEqual(recorded["verify_by"]["kind"], "trace_within_h")
        self.assertTrue(recorded["journal_ts"])
        self.assertEqual(recorded["kinds"], ["edit_automation", "reload"])

    def test_a_service_call_records_its_before_state_in_the_mcp_shape(self):
        row = self.planned_row(plan([{"op": "call_service", "domain": "light",
                                      "service": "turn_off",
                                      "entity_id": "light.hall"}]))
        self.apply(row)
        panel_rows = actions.read_ledger(0)
        self.assertEqual(len(panel_rows), 1)
        got = panel_rows[0]
        self.assertEqual((got["domain"], got["service"], got["entities"]),
                         ("light", "turn_off", ["light.hall"]))
        self.assertEqual(got["channel"], "fix")
        self.assertTrue(got["intervention"].startswith("fix-"))
        # The before-state is the MCP server's shape exactly: drive its own
        # reader over the same state and compare.
        mcp = self._mcp()
        mcp.ha_api_request = lambda path, *a, **k: {
            "state": "on", "attributes": {"brightness": 200,
                                          "friendly_name": "Hall"}}
        self.assertEqual(got["before"], mcp._read_before(["light.hall"]))
        # …and the MCP writer's row has the same core keys the panel's has.
        other = Path(self.tmp.name) / "mcp.jsonl"
        record_a_call(other, "light", "turn_off", {"entity_id": "light.hall"})
        theirs = actions.read_ledger(0, str(other))[0]
        self.assertLessEqual({"ts", "domain", "service", "entities"},
                             set(got) & set(theirs))

    def _mcp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mcp_for_shape", BASE_DIR / "brain" / "ha-mcp-server" /
            "ha_mcp_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_failure_midway_puts_the_edit_back(self):
        self.fail_service = ("light", "turn_off")
        row = self.planned_row(plan([EDIT, {"op": "call_service",
                                            "domain": "light",
                                            "service": "turn_off",
                                            "entity_id": "light.hall"}]))
        status, row = self.apply(row)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(self.automations.read_text(), ORIGINAL,
                         "the edit made before the failure was put back")
        self.assertIn("put back", row["result"])
        self.assertIsNone(interventions.for_finding(row["ts"]))

    def test_the_floors_are_asked_again_at_apply(self):
        row = self.planned_row(plan([{"op": "call_service", "domain": "light",
                                      "service": "turn_off",
                                      "entity_id": "light.hall"}]))
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.*"
        status, row = self.apply(row)
        self.assertEqual(row["status"], "failed")
        self.assertIn("protected", row["result"])
        self.assertEqual([c for c in self.core_calls if c[0] == "light"], [])

    def test_a_legacy_step_only_plan_cannot_be_applied(self):
        row = self.file_finding("old")
        findings_store.set_plan(row["ts"], {"can_fix": True,
                                            "steps": ["do it"],
                                            "summary": "s"})
        status, _row = self.apply(findings_store.get(row["ts"]))
        self.assertEqual(status, 409)
        self.assertEqual(self.agent_calls, [])


class TestTheAgenticOpRunsUnderItsContract(TypedCase):
    def test_the_contract_rides_the_environment(self):
        self.agent_allowed = True
        envs = []
        original = self.server.engine.run_agent

        def agent(prompt, system, *a, **k):
            envs.append(k.get("env") or {})
            return original(prompt, system, *a, **k)

        self.server.engine.run_agent = agent
        try:
            row = self.planned_row(plan([
                {"op": "reload", "domain": "automation"},
                {"op": "agentic", "instruction": "edit the heating package",
                 "files": ["/config/packages/heat.yaml"],
                 "calls": [{"domain": "climate", "service": "set_temperature",
                            "target": {"entity_id": "climate.hall"}}]}]))
            status, row = self.apply(row)
        finally:
            self.server.engine.run_agent = original
        self.assertEqual(len(envs), 1)
        env = envs[0]
        contract = json.loads(env["BRAIN_CHANGE_CONTRACT"])
        self.assertEqual(env["BRAIN_CHANNEL"], "fix")
        self.assertEqual(contract["id"], env["BRAIN_INTERVENTION_ID"])
        self.assertEqual(contract["files"], ["/config/packages/heat.yaml"])
        self.assertEqual(contract["calls"][0]["entities"], ["climate.hall"])
        # The reload is the panel's, made before the run, never on the
        # contract (so the run cannot make it a second time).
        self.assertIn(("automation", "reload", {}), self.core_calls)
        self.assertNotIn("automation", [c["domain"] for c in contract["calls"]])
        self.assertIn("WHAT THIS RUN MAY TOUCH", self.agent_calls[0])
        self.assertEqual(row["status"], "fixed")

    def test_the_engine_hands_the_contract_to_the_cli_and_clears_it(self):
        import engine
        seen = []
        old = engine._run_cli

        def fake(*a, **k):
            seen.append(engine._claude_env().get("BRAIN_CHANGE_CONTRACT"))
            return {"ok": True, "text": "{}", "error": "", "meta": {}}

        engine._run_cli = fake
        try:
            engine.__dict__["run_agent"] = type(self)._real_run_agent
            engine.run_agent("p", "s", env={"BRAIN_CHANGE_CONTRACT": "{}"})
        finally:
            engine._run_cli = old
        self.assertEqual(seen, ["{}"])
        self.assertIsNone(engine._claude_env().get("BRAIN_CHANGE_CONTRACT"))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import engine
        cls._real_run_agent = engine.run_agent


class TestUndoAndRestore(TypedCase):
    def fixed_by_the_panel(self, ops):
        row = self.planned_row(plan(ops))
        _status, row = self.apply(row)
        self.assertEqual(row["status"], "fixed", row.get("result"))
        return row

    def press(self, ts, verb, client):
        return client.post(f"/api/finding/{ts}/{verb}")

    def test_undo_reverts_the_panels_own_edit(self):
        row = self.fixed_by_the_panel([EDIT])
        self.assertNotEqual(self.automations.read_text(), ORIGINAL)

        async def body(client):
            res = await self.press(row["ts"], "unfix", client)
            return res.status

        self.assertEqual(self.drive(body), 200)
        self.assertEqual(self.automations.read_text(), ORIGINAL)
        self.assertEqual(interventions.for_finding(row["ts"])["status"],
                         "undone")

    def test_undo_lists_calls_and_never_restores_them_itself(self):
        row = self.fixed_by_the_panel([{"op": "call_service",
                                        "domain": "light",
                                        "service": "turn_off",
                                        "entity_id": "light.hall"}])
        before = len(self.core_calls)

        async def body(client):
            await self.press(row["ts"], "unfix", client)

        self.drive(body)
        self.assertNotIn("scene", [c[0] for c in self.core_calls[before:]],
                         "an undo must never restore a call on its own")
        self.assertIn("Put them back", findings_store.get(row["ts"])["result"])

    def write_calls(self, started, rows):
        for i, (domain, service, entities, before) in enumerate(rows):
            typed_fix.append_ledger(typed_fix.ledger_row(
                domain, service, entities, before=before,
                when=started + 1 + i), str(self.ledger))

    def test_restore_puts_back_what_was_recorded_and_says_so_per_entity(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.nursery"
        started = time.time() - 60
        self.write_calls(started, [
            ("light", "turn_off", ["light.hall"],
             {"light.hall": {"state": "on",
                             "attributes": {"brightness": 200,
                                            "friendly_name": "Hall"}}}),
            ("light", "turn_off", ["light.nursery"],
             {"light.nursery": {"state": "on", "attributes": {}}}),
            ("lock", "lock", ["lock.back"],
             {"lock.back": {"state": "unlocked", "attributes": {}}}),
            ("sensor", "x", ["sensor.temp"],
             {"sensor.temp": {"state": "21", "attributes": {}}}),
            ("light", "turn_on", ["light.porch"],
             {"light.porch": {"unknown": True}}),
            ("cover", "close_cover", ["cover.garage"],
             {"cover.garage": {"state": "open",
                               "attributes": {"device_class": "garage"}}}),
        ])
        # Turned on again later — the FIRST before-state is the one kept.
        self.write_calls(started + 20, [
            ("light", "turn_on", ["light.hall"],
             {"light.hall": {"state": "off", "attributes": {}}})])
        row = self.file_finding("restore me")
        findings_store.set_fix_window(row["ts"], started, time.time())
        findings_store.set_status(row["ts"], "fixed")
        self.states["light.hall"] = {"state": "off", "attributes": {}}

        async def body(client):
            res = await self.press(row["ts"], "restore", client)
            return res.status, await res.json()

        status, payload = self.drive(body)
        self.assertEqual(status, 200)
        by = {r["entity_id"]: r for r in payload["restored"]}
        self.assertTrue(by["light.hall"]["restored"])
        self.assertIn("protected", by["light.nursery"]["why"])
        self.assertIn("less secure", by["lock.back"]["why"])
        self.assertIn("reading", by["sensor.temp"]["why"])
        self.assertIn("could not read", by["light.porch"]["why"])
        self.assertIn("less secure", by["cover.garage"]["why"])
        applied = [c for c in self.core_calls if c[:2] == ("scene", "apply")]
        self.assertEqual(len(applied), 1)
        self.assertEqual(set(applied[0][2]["entities"]), {"light.hall"})
        self.assertEqual(applied[0][2]["entities"]["light.hall"],
                         {"state": "on", "brightness": 200})
        # The restore itself is on the ledger, as brAIn's.
        last = actions.read_ledger(0)[-1]
        self.assertEqual((last["domain"], last["service"], last["channel"]),
                         ("scene", "apply", "restore"))

    def test_a_restore_that_did_not_take_says_could_not_restore(self):
        started = time.time() - 60
        self.write_calls(started, [
            ("light", "turn_off", ["light.hall"],
             {"light.hall": {"state": "on", "attributes": {}}})])
        row = self.file_finding("stubborn")
        findings_store.set_fix_window(row["ts"], started, time.time())
        findings_store.set_status(row["ts"], "fixed")
        self.fail_service = ("scene", "apply")

        async def body(client):
            res = await self.press(row["ts"], "restore", client)
            return await res.json()

        payload = self.drive(body)
        self.assertFalse(payload["restored"][0]["restored"])
        self.assertIn("refused", payload["restored"][0]["why"])
        self.assertIn("Could not restore light.hall", payload["text"])

    def test_restore_is_refused_while_the_row_is_being_worked_on(self):
        row = self.file_finding("busy")
        findings_store.set_status(row["ts"], "fixing")

        async def body(client):
            res = await self.press(row["ts"], "restore", client)
            return res.status

        self.assertEqual(self.drive(body), 409)


class TestRestorePlanIsPure(unittest.TestCase):
    def test_an_alarm_is_never_restored_to_disarmed(self):
        out = unfix.restore_plan([{
            "ts": 1, "entities": ["alarm_control_panel.home"],
            "before": {"alarm_control_panel.home": {"state": "disarmed",
                                                    "attributes": {}}}}],
            protected=[])
        self.assertEqual(out["apply"], {})
        self.assertIn("less secure", out["refused"][0][1])

    def test_a_lock_may_be_restored_to_locked(self):
        out = unfix.restore_plan([{
            "ts": 1, "entities": ["lock.front"],
            "before": {"lock.front": {"state": "locked", "attributes": {}}}}],
            protected=[])
        self.assertEqual(out["apply"], {"lock.front": {"state": "locked"}})

    def test_a_row_without_a_before_state_is_said(self):
        out = unfix.restore_plan([{"ts": 1, "entities": ["light.x"]}],
                                 protected=[])
        self.assertIn("did not record", out["refused"][0][1])


if __name__ == "__main__":
    unittest.main()
