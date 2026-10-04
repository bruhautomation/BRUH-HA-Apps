#!/usr/bin/env python3
"""A correction has a scope and a lifetime, and both are guarded.

`corrections.py` turns "not a problem, because…" into one of four scopes
and a lifetime, and `House.should_report` is the one question every
per-entity check asks before filing. Driven over the real facts store, the
real checks and the real routes, with only `engine.run_claude` stubbed.

The guardrails, each a test that names its mutation:

  wide is silent            write a check_area rule straight from the reply
                            -> `test_a_room_wide_correction_is_offered_...`
  safety is covered         drop `_never_covered`'s class test -> a leak
                            sensor in the same room is stood down
  protected is covered      drop the protected-pattern test in `plan`
  undo leaves the scope     drop `forget_exceptions` from `_undo_finding`
                            -> the lifetime the pass wrote survives Undo
  a check skips the ask     remove one `should_report` from a check ->
                            the AST sweep names the function
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))

import corrections  # noqa: E402
import decision_trail  # noqa: E402
import facts_store  # noqa: E402
import findings_store  # noqa: E402
from checks._util import House  # noqa: E402
from test_todo_list import PanelCase  # noqa: E402

TODAY = dt.date(2026, 9, 14)


def check_finding(entity="binary_sensor.cupboard", check="dev.frozen"):
    return {"ts": 1, "text": f"{entity} has read the same value for a week",
            "source": f"check:{check}", "entity_id": entity}


class TestPlan(unittest.TestCase):
    """What a reply may do, checked before anything is written."""

    def plan(self, reply, **kw):
        kw.setdefault("today", TODAY)
        return corrections.plan(reply, check_finding(kw.pop("entity",
                                                            "binary_sensor.cupboard"),
                                                     kw.pop("check", "dev.frozen")),
                                **kw)

    def test_an_unknown_scope_is_the_press_s_own(self):
        got = self.plan({"scope": "everywhere", "lifetime": "permanent"})
        self.assertEqual(got["scope"], "entity_check")
        self.assertTrue(got["clamped"])

    def test_a_wide_scope_is_an_offer_and_never_a_rule(self):
        got = self.plan({"scope": "check", "lifetime": "permanent"})
        self.assertEqual(got["scope"], "check")
        self.assertTrue(got["offer"])
        area = self.plan({"scope": "check_area", "lifetime": "permanent"},
                         area_id="garage")
        self.assertTrue(area["offer"])
        self.assertEqual(area["area_id"], "garage")

    def test_a_room_nobody_knows_is_not_a_room(self):
        got = self.plan({"scope": "check_area", "lifetime": "permanent"})
        self.assertEqual(got["scope"], "entity_check")
        self.assertFalse(got["offer"])

    def test_no_scope_covers_a_safety_device(self):
        for kw in ({"device_class": "moisture"}, {"device_class": "smoke"},
                   {"entity": "lock.front_door"},
                   {"entity": "alarm_control_panel.house"},
                   {"protected": ["binary_sensor.*"]},
                   {"check": "climate.freeze"}):
            with self.subTest(**kw):
                for scope in ("entity", "check_area", "check"):
                    got = self.plan({"scope": scope, "lifetime": "permanent"},
                                    area_id="garage", **kw)
                    self.assertEqual(got["scope"], "entity_check")
                    self.assertFalse(got["offer"])

    def test_only_a_rule_s_report_can_be_widened(self):
        got = corrections.plan({"scope": "entity", "lifetime": "permanent"},
                               {"ts": 1, "text": "x", "source": "resident",
                                "entity_id": "sensor.a"}, today=TODAY)
        self.assertEqual(got["scope"], "entity_check")

    def test_until_a_month_resumes_on_its_first_day(self):
        got = self.plan({"scope": "entity_check", "lifetime": "month",
                         "until_month": 10})
        self.assertEqual(got["resume"], "2026-10-01")
        self.assertEqual(got["expires"], "2026-09-30")
        self.assertEqual(got["until"], "until October")
        # A month that has already begun means next year's.
        again = self.plan({"scope": "entity_check", "lifetime": "month",
                           "until_month": 9})
        self.assertEqual(again["resume"], "2027-09-01")

    def test_a_season_ends_when_it_ends(self):
        winter = self.plan({"scope": "entity_check", "lifetime": "season",
                            "season": "winter"},
                           today=dt.date(2026, 10, 20))
        self.assertEqual(winter["resume"], "2027-03-01")
        south = self.plan({"scope": "entity_check", "lifetime": "season",
                           "season": "winter"}, southern=True,
                          today=dt.date(2026, 6, 20))
        self.assertEqual(south["resume"], "2026-09-01")

    def test_a_date_that_cannot_be_a_lifetime_is_permanent(self):
        for reply in ({"lifetime": "date", "until_date": "2026-01-01"},
                      {"lifetime": "date", "until_date": "2031-01-01"},
                      {"lifetime": "date", "until_date": "soon"},
                      {"lifetime": "month", "until_month": 13},
                      {"lifetime": "season", "season": "monsoon"}):
            with self.subTest(**reply):
                got = self.plan({"scope": "entity_check", **reply})
                self.assertEqual((got["resume"], got["expires"]), ("", ""))

    def test_the_sentence_is_built_by_code(self):
        got = self.plan({"scope": "entity_check", "lifetime": "month",
                         "until_month": 10})
        self.assertEqual(corrections.confirmation(got),
                         "Got it — I'll stop flagging it until October.")
        forever = self.plan({"scope": "entity_check", "lifetime": "permanent"})
        self.assertEqual(corrections.confirmation(forever),
                         "Got it — I won't flag that again.")
        wide = self.plan({"scope": "check_area", "lifetime": "permanent"},
                         area_id="garage")
        said = corrections.confirmation(wide, entity_name="Cupboard door",
                                        area_name="Garage",
                                        check_title="Sensors frozen")
        self.assertIn("Want me to stop flagging", said)
        self.assertIn("Garage", said)


class StoreCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._olds = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
                      corrections.OFFERS_FILE, corrections.facts_store)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        corrections.OFFERS_FILE = root / "offers.json"
        corrections.facts_store = facts_store

    def tearDown(self):
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         corrections.OFFERS_FILE, corrections.facts_store) = self._olds
        self.tmp.cleanup()

    def press_rule(self, entity="binary_sensor.cupboard", check="dev.frozen",
                   key="cupboard key"):
        row, _ = facts_store.add(
            "it is a cupboard nobody opens", subject=entity,
            source="correction", predicate=f"exception:{check}",
            about="it read the same", finding_key=key)
        return row


class TestApplyAndOffer(StoreCase):
    def test_a_lifetime_lands_on_the_press_s_own_rule(self):
        base = self.press_rule()
        the_plan = corrections.plan(
            {"scope": "entity_check", "lifetime": "month", "until_month": 10},
            check_finding(), today=TODAY)
        got = corrections.apply_plan(the_plan, check_finding(), [base["id"]],
                                     "cupboard", finding_key="cupboard key")
        self.assertEqual(got["ids"], [base["id"]])
        row = next(r for r in facts_store.export_rows() if r["id"] == base["id"])
        self.assertEqual(row["expires"], "2026-09-30")

    def test_an_entity_scope_is_one_rule_carrying_the_key(self):
        base = self.press_rule()
        the_plan = corrections.plan({"scope": "entity",
                                     "lifetime": "permanent"},
                                    check_finding(), today=TODAY)
        got = corrections.apply_plan(the_plan, check_finding(), [base["id"]],
                                     "it is a dummy", finding_key="cupboard key")
        wide = [r for r in facts_store.export_rows()
                if r["predicate"] == "exception:*"]
        self.assertEqual(len(wide), 1)
        self.assertEqual(wide[0]["finding_key"], "cupboard key")
        self.assertIn(wide[0]["id"], got["ids"])
        # ...and Let-brAIn-raise-it-again's own door takes both back.
        facts_store.forget_exceptions("cupboard key")
        self.assertEqual(corrections.scope_map()["entity"], {})

    def test_an_undone_press_is_scoped_by_nothing(self):
        base = self.press_rule()
        facts_store.forget_ids([base["id"]])
        the_plan = corrections.plan({"scope": "entity",
                                     "lifetime": "permanent"},
                                    check_finding(), today=TODAY)
        got = corrections.apply_plan(the_plan, check_finding(), [base["id"]],
                                     "x", finding_key="cupboard key")
        self.assertFalse(got["written"])
        self.assertTrue(got["why"])
        self.assertEqual(facts_store.export_rows(), [])

    def test_a_room_wide_correction_is_offered_then_written_on_yes(self):
        self.press_rule()
        the_plan = corrections.plan(
            {"scope": "check_area", "lifetime": "permanent",
             "reason": "garage plugs are not used"},
            check_finding(), today=TODAY, area_id="garage")
        before = facts_store.export_rows()
        row = corrections.offer_row(the_plan, "none of the garage ones matter",
                                    entity_name="Cupboard door",
                                    area_name="Garage",
                                    check_title="Sensors frozen",
                                    finding_key="cupboard key")
        # Asking wrote nothing: the reply alone never makes a wide rule.
        self.assertEqual(facts_store.export_rows(), before)
        self.assertEqual(row["kind"], "question")
        self.assertEqual(row["source"], corrections.SOURCE)
        got = corrections.accept_offer(row["text"])
        self.assertEqual(len(got["ids"]), 1)
        table = corrections.scope_map()
        self.assertIn("dev.frozen", table["area"]["garage"])
        rule = next(r for r in facts_store.export_rows()
                    if r["id"] == got["ids"][0])
        self.assertEqual(rule["subject"], "area:garage")
        self.assertEqual(rule["finding_key"], "cupboard key")
        # The original report's key takes the wide rule back with the rest.
        self.assertEqual(corrections.withdraw("cupboard key"),
                         [corrections.offer_key_for(row["text"])])
        facts_store.forget_exceptions("cupboard key")
        self.assertEqual(corrections.scope_map()["area"], {})

    def test_an_expired_rule_stands_nothing_down(self):
        facts_store.add("off for the summer", subject="sensor.a",
                        source="correction", predicate="exception:dev.frozen",
                        expires="2020-01-01")
        self.assertEqual(corrections.scope_map()["entity"], {})


class TestShouldReport(StoreCase):
    """`House.should_report` over a real scope map."""

    def house(self, table):
        return House({
            "states": {
                "binary_sensor.cupboard": {"attributes": {}},
                "binary_sensor.leak": {"attributes": {"device_class": "moisture"}},
                "sensor.lounge": {"attributes": {}},
            },
            "entities": [
                {"entity_id": "binary_sensor.cupboard", "area_id": "garage"},
                {"entity_id": "binary_sensor.leak", "area_id": "garage"},
                {"entity_id": "sensor.lounge", "area_id": "lounge"},
            ],
            "corrections": table,
            "_trail": [],
        })

    def test_four_scopes_narrowest_first(self):
        facts_store.add("garage", subject="area:garage", source="correction",
                        predicate="exception:dev.frozen")
        house = self.house(corrections.scope_map())
        self.assertFalse(house.should_report("binary_sensor.cupboard",
                                             "dev.frozen"))
        self.assertTrue(house.should_report("binary_sensor.cupboard",
                                            "dev.unavailable"))
        self.assertTrue(house.should_report("sensor.lounge", "dev.frozen"))
        self.assertEqual(house.snap["_trail"][0]["kind"], "exception")
        self.assertIn("check_area", house.snap["_trail"][0]["text"])

    def test_a_wide_rule_never_covers_a_leak_sensor_fitted_later(self):
        facts_store.add("garage", subject="area:garage", source="correction",
                        predicate="exception:dev.frozen")
        facts_store.add("all of them", subject="check:dev.unavailable",
                        source="correction",
                        predicate="exception:dev.unavailable")
        house = self.house(corrections.scope_map())
        self.assertTrue(house.should_report("binary_sensor.leak", "dev.frozen"))
        self.assertTrue(house.should_report("binary_sensor.leak",
                                            "dev.unavailable"))
        self.assertFalse(house.should_report("sensor.lounge",
                                             "dev.unavailable"))

    def test_a_protected_entity_is_never_covered_widely(self):
        facts_store.add("all of them", subject="check:dev.frozen",
                        source="correction", predicate="exception:dev.frozen")
        house = self.house(corrections.scope_map(
            protected=["binary_sensor.cupboard"]))
        self.assertTrue(house.should_report("binary_sensor.cupboard",
                                            "dev.frozen"))
        self.assertFalse(house.should_report("sensor.lounge", "dev.frozen"))

    def test_no_table_falls_back_to_the_exception_map(self):
        house = House({"facts": {"sensor.a": {"dev.frozen"}}, "_trail": []})
        self.assertFalse(house.should_report("sensor.a", "dev.frozen"))
        self.assertTrue(house.should_report("sensor.a", "base.unusual"))


# Every function in a check module that files a row about an entity — a
# dict carrying a "text" and an "entity_id" that is not the empty string —
# asks `should_report` (or reads its answer through `gave_up`'s caller).
CHECK_MODULES = ("automations", "baseline", "chores", "dashboards", "devices",
                 "evening", "forecasts", "registry", "system", "thermal")


def _files_entity_rows(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if not {"text", "entity_id"} <= keys:
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "entity_id":
                if not (isinstance(v, ast.Constant) and v.value == ""):
                    return True
    return False


def _asks(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "should_report":
            return True
    return False


class TestEveryCheckAsks(unittest.TestCase):
    def test_every_per_entity_row_is_asked_about(self):
        missing = []
        for name in CHECK_MODULES:
            tree = ast.parse((PANEL / "checks" / f"{name}.py").read_text())
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and _files_entity_rows(fn) \
                        and not _asks(fn):
                    missing.append(f"checks/{name}.py:{fn.name}")
        self.assertEqual(missing, [], "these file a row about an entity "
                         "without asking House.should_report")

    def test_the_sweep_can_fail(self):
        tree = ast.parse("def bad(house):\n"
                         "    return [{'text': 'x', 'entity_id': 'a.b'}]\n")
        fn = tree.body[0]
        self.assertTrue(_files_entity_rows(fn))
        self.assertFalse(_asks(fn))


class TestTheConstantsAgreeWithTheirSources(unittest.TestCase):
    def test_safety_sets(self):
        import signals
        from checks import automations
        self.assertLessEqual(set(signals.HOT_SAFETY_CLASSES),
                             set(corrections.NEVER_CLASSES))
        self.assertLessEqual(set(automations.SAFETY_CLASSES),
                             set(corrections.NEVER_CLASSES))
        self.assertLessEqual(set(signals.SAFETY_CHECKS),
                             set(corrections.NEVER_CHECKS))
        self.assertLessEqual(set(automations.SAFETY_DOMAINS),
                             set(corrections.NEVER_DOMAINS))


# ---------------------------------------------------------------------------
# Through the routes
# ---------------------------------------------------------------------------

class RouteCase(PanelCase):
    ENTITY = "binary_sensor.cupboard"

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        s = self.server
        self._route_olds = (
            facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
            facts_store.RECONCILE_STATE_FILE, corrections.OFFERS_FILE,
            s.corrections.facts_store, s.facts_store, s.engine.run_claude,
            s.engine.get_auth, decision_trail.TRAIL_FILE, dict(s._NAMES),
            dict(s._FACTS_CTX), s._findings_notify_target)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "facts-ingest.json"
        facts_store.RECONCILE_STATE_FILE = root / "facts-reconcile.json"
        s.corrections.OFFERS_FILE = root / "offers.json"
        corrections.OFFERS_FILE = root / "offers.json"
        s.corrections.facts_store = facts_store
        s.facts_store = facts_store
        decision_trail.TRAIL_FILE = os.path.join(self.tmp.name, "d.jsonl")
        s._NAMES.clear()
        s._NAMES.update({self.ENTITY: {"name": "Cupboard door",
                                       "area": "Garage"}})
        s._FACTS_CTX.update(entity_areas={self.ENTITY: "garage"},
                            areas={"garage": "Garage"})
        s.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.replies = {}
        self.jobs = []

        def fake(prompt, system, model="", timeout=480, max_turns=4,
                 source="", *, job="", effort="", schema=None):
            self.jobs.append(job)
            if job in self.replies:
                return {"ok": True, "data": self.replies[job], "text": "",
                        "error": "", "meta": {}}
            return {"ok": True, "text": "OK", "error": "", "meta": {}}

        s.engine.run_claude = fake
        s.CORRECTION_STATE.update(day="", runs=0)
        s.interpret.STATE.update(day="", runs=0)

    def tearDown(self):
        s = self.server
        (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE,
         facts_store.RECONCILE_STATE_FILE, offers, s.corrections.facts_store,
         s.facts_store, s.engine.run_claude, s.engine.get_auth,
         decision_trail.TRAIL_FILE, names, ctx,
         s._findings_notify_target) = self._route_olds
        corrections.OFFERS_FILE = offers
        s.corrections.OFFERS_FILE = offers
        s._NAMES.clear()
        s._NAMES.update(names)
        s._FACTS_CTX.clear()
        s._FACTS_CTX.update(ctx)
        super().tearDown()

    def check_row(self, check="dev.frozen"):
        entry, created = findings_store.add(
            "Cupboard door has read exactly the same value for a week",
            severity="warning", detail="off for 8 days", fix="Check it",
            source=f"check:{check}", source_title="Sensors frozen on one value",
            entity_id=self.ENTITY)
        self.assertTrue(created)
        return entry

    def model_jobs(self):
        """The runs this test caused — not the panel's own sign-in check,
        which a live app with a credential starts by itself."""
        return [j for j in self.jobs if j != "auth_check"]

    def rules(self):
        return [r for r in facts_store.export_rows()
                if str(r.get("predicate") or "").startswith("exception:")]


class TestThePressGetsItsSecondLook(RouteCase):
    def test_wrong_with_a_reason_lands_a_lifetime_and_undo_takes_it_back(self):
        row = self.check_row()
        # A whole-entity rule beside the press's own, both until spring:
        # the second has an id the undo token never saw, which is the
        # case `forget_exceptions` in `_undo_finding` exists for.
        self.replies["correct"] = {"scope": "entity",
                                   "lifetime": "season", "season": "winter"}

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": "it's always like that in "
                                                  "winter"})
            self.assertEqual(res.status, 200)
            payload = await res.json()
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            rules = self.rules()
            self.assertEqual(sorted(r["predicate"] for r in rules),
                             ["exception:*", "exception:dev.frozen"])
            self.assertTrue(all(r["expires"] for r in rules))
            undo = await client.post(f"/api/undo/{payload['undo']}")
            self.assertEqual(undo.status, 200, await undo.text())
            return rules

        self.drive(body)
        self.assertIn("correct", self.jobs)
        self.assertEqual(self.rules(), [])

    def test_a_room_wide_reason_files_a_question_and_no_rule(self):
        row = self.check_row()
        self.replies["correct"] = {"scope": "check_area",
                                   "lifetime": "permanent"}

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/wrong",
                                    json={"note": "none of the garage ones "
                                                  "matter"})
            self.assertEqual(res.status, 200)
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))

        self.drive(body)
        # Only the press's own rule: the room is a question.
        self.assertEqual([r["subject"] for r in self.rules()], [self.ENTITY])
        offers = [f for f in findings_store.list_all()
                  if f["source"] == corrections.SOURCE]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["kind"], "question")

        async def yes(_client):
            return await self.server._end_finding(
                offers[0], self.server.FINDING_VERBS["confirm"], "")

        payload, fact = self.drive(yes)
        self.assertTrue(payload.get("_exception_ids"))
        self.assertIn("area:garage", [r["subject"] for r in self.rules()])
        self.assertTrue(fact)

    def test_no_to_an_offer_writes_nothing_and_teaches_nothing(self):
        row = self.check_row()
        self.replies["correct"] = {"scope": "check", "lifetime": "permanent"}

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/wrong",
                              json={"note": "I never care about this"})
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
            offer = next(f for f in findings_store.list_all()
                         if f["source"] == corrections.SOURCE)
            self.before = len(self.queued_memory())
            return await self.server._end_finding(
                offer, self.server.FINDING_VERBS["wrong"], "")

        payload, fact = self.drive(body)
        self.assertEqual(fact, "")
        self.assertNotIn("_exception_ids", payload)
        self.assertEqual(len(self.queued_memory()), self.before)
        self.assertEqual([r["subject"] for r in self.rules()], [self.ENTITY])

    def test_without_a_credential_the_press_is_what_it_always_was(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/wrong",
                              json={"note": "it's like that in winter"})
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))

        self.drive(body)
        self.assertEqual(self.model_jobs(), [])
        self.assertEqual(len(self.rules()), 1)
        self.assertEqual(self.rules()[0]["expires"], "")


if __name__ == "__main__":
    unittest.main()
