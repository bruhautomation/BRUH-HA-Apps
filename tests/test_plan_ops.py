#!/usr/bin/env python3
"""A fix plan is a list of typed operations, checked in code.

`plan_ops` is the vocabulary that turns "Fix it" from prose into a
contract: five operations the panel performs itself and one (`agentic`)
that a tool-enabled run performs under a list of the calls and files it
may touch. These tests hold the refusals — each one is a way a plan could
otherwise reach a house in a shape nothing checked — and the round trip
through the findings store, because Apply reads the ops off the ROW.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402
import fixer  # noqa: E402
import plan_ops  # noqa: E402

EDIT = {"op": "edit_automation", "id": "1700000000000",
        "new_config": {"id": "1700000000000", "alias": "Hall lights",
                       "triggers": [{"trigger": "state",
                                     "entity_id": "binary_sensor.hall"}],
                       "actions": [{"action": "light.turn_on",
                                    "target": {"entity_id": "light.hall"}}]}}


class TestEachOpIsCheckedOrRefused(unittest.TestCase):
    def refuses(self, raw, fragment=""):
        with self.assertRaises(plan_ops.Refused) as caught:
            plan_ops.clean_op(raw)
        if fragment:
            self.assertIn(fragment, str(caught.exception))

    def test_an_unknown_op_is_refused(self):
        self.refuses({"op": "rm_rf"}, "not an operation")

    def test_an_edit_needs_its_own_id_a_trigger_and_an_action(self):
        self.assertEqual(plan_ops.clean_op(EDIT)["id"], "1700000000000")
        self.refuses({**EDIT, "id": "../etc"}, "config id")
        self.refuses({**EDIT, "new_config": {**EDIT["new_config"],
                                             "id": "other"}}, "different id")
        bad = {k: v for k, v in EDIT["new_config"].items() if k != "triggers"}
        self.refuses({**EDIT, "new_config": bad}, "no trigger")

    def test_reload_is_only_for_a_domain_that_re_reads_yaml(self):
        self.assertEqual(plan_ops.clean_op({"op": "reload",
                                            "domain": "automation"}),
                         {"op": "reload", "domain": "automation"})
        self.refuses({"op": "reload", "domain": "homeassistant"})

    def test_a_service_call_names_its_own_domains_entities_and_no_scope(self):
        op = plan_ops.clean_op({"op": "call_service", "domain": "light",
                                "service": "turn_off",
                                "target": {"entity_id": ["light.hall"]},
                                "data": {"transition": 2}})
        self.assertEqual(op["entities"], ["light.hall"])
        self.assertEqual(op["data"], {"transition": 2})
        self.refuses({"op": "call_service", "domain": "light",
                      "service": "turn_off",
                      "target": {"entity_id": ["switch.freezer"]}},
                     "may only act on light")
        self.refuses({"op": "call_service", "domain": "light",
                      "service": "turn_off", "target": {"area_id": "hall"}},
                     "targets by area")
        self.refuses({"op": "call_service", "domain": "light",
                      "service": "turn_off"}, "names no entity")

    def test_nothing_that_lowers_security_or_administers_ha(self):
        self.refuses({"op": "call_service", "domain": "lock",
                      "service": "unlock",
                      "target": {"entity_id": ["lock.front"]}}, "less secure")
        self.refuses({"op": "call_service", "domain": "alarm_control_panel",
                      "service": "alarm_disarm",
                      "target": {"entity_id": ["alarm_control_panel.home"]}})
        self.refuses({"op": "call_service", "domain": "homeassistant",
                      "service": "restart",
                      "target": {"entity_id": ["light.x"]}}, "may not call")
        # …including through an agentic op's call list.
        self.refuses({"op": "agentic", "instruction": "x",
                      "calls": [{"domain": "hassio", "service": "host_reboot"}]})

    def test_an_agentic_op_lists_what_it_may_touch(self):
        op = plan_ops.clean_op({"op": "agentic", "instruction": "fix it",
                                "files": ["/config/packages/heat.yaml"]})
        self.assertEqual(op["files"], ["/config/packages/heat.yaml"])
        self.refuses({"op": "agentic", "instruction": "fix it"},
                     "list the calls")
        self.refuses({"op": "agentic", "instruction": "x",
                      "files": ["/config/secrets.yaml"]}, "credentials")
        self.refuses({"op": "agentic", "instruction": "x",
                      "files": ["/config/../etc/passwd"]}, "not a file")
        self.refuses({"op": "agentic", "instruction": "x",
                      "files": ["/config/.storage/core.config_entries"]})

    def test_one_bad_op_refuses_the_whole_plan(self):
        with self.assertRaises(plan_ops.Refused):
            plan_ops.clean_ops([EDIT, {"op": "rm_rf"}])

    def test_verify_by_is_checked_and_never_refuses_the_plan(self):
        self.assertEqual(plan_ops.clean_verify({"kind": "finding_clears",
                                                "hours": 24}),
                         {"kind": "finding_clears", "hours": 24.0})
        self.assertIsNone(plan_ops.clean_verify({"kind": "vibes"}))
        self.assertIsNone(plan_ops.clean_verify(
            {"kind": "state_is", "entity": "not an id", "state": "on"}))


class TestTheContractIsTheAgenticOpsOnly(unittest.TestCase):
    def test_deterministic_ops_are_not_on_the_contract(self):
        ops = plan_ops.clean_ops([
            {"op": "reload", "domain": "automation"},
            {"op": "agentic", "instruction": "edit the package",
             "files": ["/config/packages/heat.yaml"],
             "calls": [{"domain": "climate", "service": "set_temperature",
                        "target": {"entity_id": "climate.hall"}}]}])
        contract = plan_ops.contract_for(ops, "fix-1-2")
        self.assertEqual(contract["id"], "fix-1-2")
        self.assertEqual(contract["files"], ["/config/packages/heat.yaml"])
        self.assertEqual(contract["calls"], [{"domain": "climate",
                                              "service": "set_temperature",
                                              "entities": ["climate.hall"]}])

    def test_the_steps_a_person_reads_are_the_ops(self):
        plan = fixer.parse_plan(json.dumps({
            "can_fix": True, "summary": "x",
            "steps": ["something else entirely"],
            "ops": [{"op": "reload", "domain": "automation"}]}))
        self.assertEqual(plan["steps"],
                         ["Reload Home Assistant's automation configuration"])

    def test_a_plan_with_an_unreadable_op_is_not_approvable(self):
        plan = fixer.parse_plan(json.dumps({
            "can_fix": True, "summary": "x",
            "ops": [{"op": "call_service", "domain": "lock",
                     "service": "unlock", "entity_id": "lock.front"}]}))
        self.assertFalse(plan["can_fix"])
        self.assertEqual(plan["ops"], [])
        self.assertEqual(plan["steps"], [])
        self.assertIn("less secure", plan["summary"])

    def test_a_plan_with_no_ops_is_not_approvable(self):
        plan = fixer.parse_plan(json.dumps({"can_fix": True, "summary": "x",
                                            "steps": ["do it"]}))
        self.assertFalse(plan["can_fix"])


class TestTheFloorsAreAskedOfThePlan(unittest.TestCase):
    def test_a_protected_entity_refuses(self):
        ops = plan_ops.clean_ops([{"op": "call_service", "domain": "light",
                                   "service": "turn_off",
                                   "entity_id": "light.nursery"}])
        self.assertIn("protected",
                      plan_ops.protected_refusal(ops, ["light.nursery"]))
        self.assertIsNone(plan_ops.protected_refusal(ops, ["lock.*"]))

    def test_an_edit_that_would_act_on_a_protected_entity_refuses(self):
        ops = plan_ops.clean_ops([EDIT])
        self.assertTrue(plan_ops.protected_refusal(ops, ["light.hall"]))

    def test_the_tripwire_refuses_without_being_named_in_a_prompt(self):
        ops = plan_ops.clean_ops([{"op": "call_service",
                                   "domain": "input_boolean",
                                   "service": "turn_on",
                                   "entity_id": "input_boolean.brain_honeytoken"}])
        why = plan_ops.protected_refusal(
            ops, [], honeytokens=["input_boolean.brain_honeytoken"])
        self.assertIn("tripwire", why)


class TestTheStoreKeepsTheTypedHalf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                      findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.SETTLED_FILE = tmp / "settled.json"
        findings_store.STATE_FILE = tmp / "nowhere" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._olds
        self.tmp.cleanup()

    def test_ops_verify_and_preview_round_trip(self):
        row, _ = findings_store.add("the hall automation never fires",
                                    source="check:auto.dead_ref")
        plan = fixer.parse_plan(json.dumps({
            "can_fix": True, "summary": "x",
            "ops": [EDIT], "expected_effect": "it fires again",
            "verify_by": {"kind": "trace_within_h",
                          "automation": "automation.hall_lights",
                          "hours": 48}}))
        plan["preview"] = [{"diff": "--- a\n+++ b\n", "replay": {
            "would_run": 3, "at": [1, 2, 3]}}]
        findings_store.set_plan(row["ts"], plan)
        stored = findings_store.get(row["ts"])["plan"]
        self.assertTrue(stored["can_fix"])
        self.assertEqual(stored["ops"][0]["id"], "1700000000000")
        self.assertEqual(stored["verify_by"]["kind"], "trace_within_h")
        self.assertEqual(stored["expected_effect"], "it fires again")
        self.assertEqual(stored["preview"][0]["replay"], {"would_run": 3})

    def test_a_stored_step_only_plan_is_not_approvable(self):
        """A plan from before plans were contracts says so, and Apply is
        refused — the plan is prose, and prose is not what Apply runs."""
        row, _ = findings_store.add("old plan", source="check:x")
        findings_store.set_plan(row["ts"], {"can_fix": True,
                                            "steps": ["do the thing"],
                                            "summary": "s"})
        stored = findings_store.get(row["ts"])["plan"]
        self.assertFalse(stored["can_fix"])
        self.assertEqual(stored["ops_refused"], plan_ops.LEGACY_PLAN)

    def test_a_stored_op_that_no_longer_validates_is_refused_on_read(self):
        row, _ = findings_store.add("tampered", source="check:x")
        items = json.loads(findings_store.FINDINGS_FILE.read_text())
        items["findings"][0]["plan"] = {"can_fix": True, "steps": ["x"], "summary": "s",
                            "ops": [{"op": "call_service", "domain": "lock",
                                     "service": "unlock",
                                     "entity_id": "lock.front"}]}
        findings_store.FINDINGS_FILE.write_text(json.dumps(items))
        stored = findings_store.get(row["ts"])["plan"]
        self.assertFalse(stored["can_fix"])
        self.assertIn("less secure", stored["ops_refused"])


if __name__ == "__main__":
    unittest.main()
