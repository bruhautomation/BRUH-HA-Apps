#!/usr/bin/env python3
"""House rules: compiled once, matched in code, and only ever tighter.

The matcher is pure and driven directly; the panel half is driven through
`/api/gate` and `/api/house-rules` with the model stubbed at
`engine.run_claude`, recording every call, because "a rule that matches
turns allow into deny without a model" is a claim about which runs happen.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import engine  # noqa: E402
import gate  # noqa: E402
import house_rules  # noqa: E402

from test_action_gate import PFX, GateCase  # noqa: E402

GARAGE = {"understood": True, "domains": ["cover"], "areas": ["garage"],
          "services": ["open_cover"], "after": "22:00", "before": "06:00",
          "verdict": "deny", "why": "no garage after ten"}
HEAT = {"understood": True, "domains": ["climate"], "ceiling_key": "temperature",
        "ceiling": 23, "verdict": "deny", "why": "never above 23"}


def cons(entities, calls):
    return {"entities": [{"entity_id": e, "domain": e.split(".")[0],
                          "area": area} for e, area in entities],
            "calls": calls}


class TestCompiledIsReadInCode(unittest.TestCase):
    def test_what_cannot_be_checked_is_no_rule(self):
        cases = [
            ({**GARAGE, "understood": False}, "could not turn"),
            ({**GARAGE, "verdict": "allow"}, "ask or refuse"),
            ({**GARAGE, "domains": [], "areas": []}, "what it is about"),
            ({**GARAGE, "after": "late"}, "not a time"),
            ({**HEAT, "ceiling_key": "vibes"}, "cannot check"),
            ({**GARAGE, "entities": ["not an id"]}, "not a domain"),
        ]
        for raw, why in cases:
            matcher, error = house_rules.clean_compiled(raw)
            self.assertIsNone(matcher, raw)
            self.assertIn(why, error)

    def test_a_good_rule_compiles(self):
        matcher, error = house_rules.clean_compiled(GARAGE)
        self.assertEqual(error, "")
        self.assertEqual(matcher["areas"], ["garage"])


class TestTheMatcher(unittest.TestCase):
    def rules(self, *raws):
        return [{"text": r["why"], "compiled": house_rules.clean_compiled(r)[0]}
                for r in raws]

    def test_a_window_across_midnight(self):
        rules = self.rules(GARAGE)
        call = cons([("cover.garage_door", "Garage")],
                    [{"domain": "cover", "service": "open_cover", "data": {}}])
        self.assertEqual(house_rules.check(call, rules, 23 * 60)[0], "deny")
        self.assertEqual(house_rules.check(call, rules, 3 * 60)[0], "deny")
        self.assertIsNone(house_rules.check(call, rules, 12 * 60))
        close = cons([("cover.garage_door", "Garage")],
                     [{"domain": "cover", "service": "close_cover", "data": {}}])
        self.assertIsNone(house_rules.check(close, rules, 23 * 60),
                          "closing the garage is not what the rule forbids")

    def test_a_ceiling_matches_only_when_it_is_broken(self):
        rules = self.rules(HEAT)
        ok = cons([("climate.hall", "Hall")], [{"domain": "climate",
                   "service": "set_temperature", "data": {"temperature": 21}}])
        hot = cons([("climate.hall", "Hall")], [{"domain": "climate",
                    "service": "set_temperature", "data": {"temperature": 25}}])
        self.assertIsNone(house_rules.check(ok, rules, 600))
        self.assertEqual(house_rules.check(hot, rules, 600)[0], "deny")

    def test_tighten_never_loosens(self):
        deny, ask = ("deny", "r"), ("ask", "r")
        self.assertEqual(house_rules.tighten("allow", ask), ("ask", True))
        self.assertEqual(house_rules.tighten("allow", deny), ("deny", True))
        self.assertEqual(house_rules.tighten("deny", ask), ("deny", False))
        self.assertEqual(house_rules.tighten("ask", None), ("ask", False))
        self.assertEqual(house_rules.tighten("ask", ask), ("ask", False))


class RulesCase(GateCase):
    def setUp(self):
        super().setUp()
        self._hr_mods = {id(m): m for m in (house_rules,
                                            self.server.house_rules)}
        self._hr_old = {k: m.FILE for k, m in self._hr_mods.items()}
        for m in self._hr_mods.values():
            m.FILE = Path(self.tmp.name) / "house_rules.json"
        self._minute_old = self.server._local_minute
        self.minute = 23 * 60
        self.server._local_minute = lambda now=None: self.minute

    def tearDown(self):
        for k, m in self._hr_mods.items():
            m.FILE = self._hr_old[k]
        self.server._local_minute = self._minute_old
        super().tearDown()

    def write(self, *raws):
        rows = [{"text": r["why"], "compiled": house_rules.clean_compiled(r)[0],
                 "error": ""} for r in raws]
        house_rules.save(rows, [r["why"] for r in raws])


class TestTheGateObeysTheRules(RulesCase):
    def test_a_deny_rule_refuses_what_the_fast_path_would_allow(self):
        async def registry():
            return {"entity_area": {"cover.door": "garage"},
                    "area_names": {"garage": "Garage"},
                    "area_entities": {}, "device_entities": {}}
        self.server._gate_registry = registry
        self.write(GARAGE)
        out = self.ask(PFX + "control_cover",
                       {"entity_id": "cover.door", "action": "open"},
                       ["open the garage"])
        self.assertEqual((out["decision"], out["path"]), ("deny", "house_rule"))
        self.assertIn("no garage after ten", out["reason"])
        self.assertEqual(self.model_calls, [])
        self.minute = 12 * 60
        gate._CACHE.clear()
        self.server.gate._CACHE.clear()
        out = self.ask(PFX + "control_cover",
                       {"entity_id": "cover.door", "action": "close"},
                       ["close the garage"])
        self.assertNotEqual(out["path"], "house_rule")

    def test_an_ask_rule_tightens_the_models_allow(self):
        self.write({**HEAT, "verdict": "ask", "ceiling": 19})
        out = self.ask(PFX + "control_climate",
                       {"entity_id": "climate.hall", "action": "set_temperature",
                        "temperature": 21}, ["make it warmer"])
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual((out["decision"], out["path"]), ("ask", "house_rule"))

    def test_a_rule_cannot_loosen_a_floor(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "climate.hall"
        self.write({**HEAT, "verdict": "ask"})
        out = self.ask(PFX + "control_climate",
                       {"entity_id": "climate.hall", "action": "set_temperature",
                        "temperature": 30}, ["heat"])
        self.assertEqual((out["decision"], out["path"]), ("deny", "floor"))


class TestSavingCompilesOnlyWhatChanged(RulesCase):
    def setUp(self):
        super().setUp()
        self.compiles = []

        def model(prompt, system, *a, **k):
            if k.get("job") != "house_rules":
                return {"ok": True, "text": "OK", "error": "", "meta": {}}
            self.compiles.append(prompt)
            text = json.loads(prompt.split("\n", 1)[1])
            data = (GARAGE if "garage" in text else
                    {"understood": False, "verdict": "deny"})
            return {"ok": True, "text": "", "error": "", "meta": {},
                    "data": data}

        engine.run_claude = model

    def save(self, rules):
        async def body(client):
            res = await client.post("/api/house-rules", json={"rules": rules})
            return res.status, await res.json()
        return self.drive(body)

    def test_each_rule_is_compiled_once_and_a_miss_is_said(self):
        status, data = self.save(["no garage after ten",
                                  "be nice to the cat"])
        self.assertEqual(status, 200)
        self.assertEqual(len(self.compiles), 2)
        by = {r["text"]: r for r in data["rules"]}
        self.assertTrue(by["no garage after ten"]["compiled"])
        self.assertIsNone(by["be nice to the cat"]["compiled"])
        self.assertIn("could not turn", by["be nice to the cat"]["error"])
        status, _data = self.save(["no garage after ten", "be nice to the cat"])
        self.assertEqual(len(self.compiles), 3,
                         "only the rule that did not compile is asked again")

    def test_too_many_rules_is_refused(self):
        async def body(client):
            res = await client.post("/api/house-rules",
                                    json={"rules": [f"rule {i}"
                                                    for i in range(11)]})
            return res.status
        self.assertEqual(self.drive(body), 400)


if __name__ == "__main__":
    unittest.main()
