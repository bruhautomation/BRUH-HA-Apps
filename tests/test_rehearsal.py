#!/usr/bin/env python3
"""`brain doctor --rehearse` — consent, the score, and the cleanup.

The rehearsal writes to somebody's `automations.yaml`, so every test here
is about one of the three things that makes that defensible: it asks
first, it scores honestly, and it takes everything back out.

What each class holds, and the mutation that breaks it:

  consent        let a POST with no consent start one -> automations
                 appear in somebody's config unasked
  the refusal    ignore protected_entities -> the rehearsal creates
                 something the configuration said not to touch
  planting       the planted automation really does fire the check it
                 was planted for, driven through the real check
  scoring        count a row about the real house -> "precision" becomes
                 a measurement of how tidy the house is
  not rehearsable    score a 30-day check -> a working check is reported
                 as broken on every single run
  cleanup        skip the helper -> a rehearsal leaves an input_number
                 behind and says it did not
  the finally    fail mid-run -> an automation stays in the file
  the leftover check   drop it from ha-selftest.sh -> nothing ever
                 catches the rehearsal that could not clean up
"""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SELFTEST = BASE_DIR / "brain" / "scripts" / "ha-selftest.sh"
sys.path.insert(0, str(PANEL))


class RehearsalCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BRAIN_REHEARSAL_FILE"] = os.path.join(
            self.tmp.name, "rehearsal.json")
        os.environ["BRAIN_JOURNAL_FILE"] = os.path.join(
            self.tmp.name, "journal.jsonl")
        os.environ["BRAIN_PROTECTED_ENTITIES"] = ""
        import journal
        importlib.reload(journal)
        import doctor
        importlib.reload(doctor)
        import rehearsal
        self.r = importlib.reload(rehearsal)

    async def asyncTearDown(self):
        self.tmp.cleanup()


class FakeHooks:
    """Home Assistant, as far as a rehearsal can tell.

    Automations land in a dict standing in for `automations.yaml`, the
    helper in another, and the snapshot is built from both — so a cleanup
    that misses something really is visible in the snapshot the removal
    checks itself against, rather than in a flag the test set.
    """

    def __init__(self, *, write_fails="", remove_fails="",
                 skip_helper_delete=False, findings=None, analyst=None):
        self.automations: dict[str, dict] = {}
        self.helpers: dict[str, float] = {}
        self.write_fails = write_fails
        self.remove_fails = remove_fails
        self.skip_helper_delete = skip_helper_delete
        self.findings = findings if findings is not None else []
        self.analyst_answer = analyst or {"ok": True, "findings": [],
                                          "model": "test-model"}
        self.ws_calls: list[dict] = []

    async def write(self, row):
        entry_id = row["config"]["id"]
        if self.write_fails and self.write_fails in entry_id:
            return None, "the file would not take it"
        self.automations[entry_id] = row["config"]
        return {"automation_id": entry_id,
                "entity_id": f"automation.{entry_id}"}, ""

    async def remove(self, entry_id, entity_id=""):
        if self.remove_fails and self.remove_fails in entry_id:
            return False, "the splice refused"
        self.automations.pop(entry_id, None)
        return True, ""

    async def snapshot(self):
        states = {f"automation.{k}": {"state": "on"} for k in self.automations}
        states.update({k: {"state": str(v)} for k, v in self.helpers.items()})
        return {"automations": list(self.automations.values()),
                "registry": dict.fromkeys(states, {}),
                "states": states,
                "available": {}}

    async def analyst(self, planted):
        return dict(self.analyst_answer)

    async def ws(self, commands):
        out = []
        for cmd in commands:
            self.ws_calls.append(cmd)
            kind = cmd.get("type")
            if kind == "input_number/create":
                self.helpers["input_number.brain_test_reading"] = 0.0
                out.append({"id": "x"})
            elif kind == "input_number/delete":
                if not self.skip_helper_delete:
                    self.helpers.pop("input_number.brain_test_reading", None)
                out.append({})
            elif kind == "call_service":
                eid = (cmd.get("service_data") or {}).get("entity_id")
                if eid in self.helpers:
                    self.helpers[eid] = (cmd["service_data"] or {}).get("value")
                out.append({})
            else:
                out.append(None)
        return out


def hooks(mod, **over):
    fake = FakeHooks(**over)
    return mod.Hooks(write=fake.write, remove=fake.remove,
                     snapshot=fake.snapshot, analyst=fake.analyst,
                     ws=fake.ws), fake


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

class TestConsent(RehearsalCase):
    async def test_the_plan_names_every_id_and_what_it_is_for(self):
        offer = self.r.plan()
        self.assertEqual([row["id"] for row in offer["plan"]],
                         [row["id"] for row in self.r.PLAN])
        for row in offer["plan"]:
            self.assertTrue(row["what"], row["id"])
            self.assertTrue(row["proves"], row["id"])
            self.assertTrue(row["id"].startswith(self.r.PREFIX)
                            or self.r.PREFIX in row["id"], row["id"])
        self.assertEqual(offer["refused"], "")

    async def test_a_protected_pattern_refuses_before_anything_is_offered(self):
        """The configuration has said not to touch this; the honest answer
        is to refuse before asking rather than to ask and then fail."""
        offer = self.r.plan(["input_number.*"])
        self.assertIn("protected_entities", offer["refused"])
        self.assertIn("input_number.brain_test_reading", offer["refused"])

    async def test_a_star_pattern_refuses_everything(self):
        self.assertTrue(self.r.plan(["*"])["refused"])

    async def test_the_plan_names_what_it_cannot_rehearse_and_why(self):
        """"We did not test this" and "this passed" are different claims."""
        offer = self.r.plan()
        ids = {row["check"] for row in offer["not_rehearsable"]}
        self.assertIn("auto.forgotten_off", ids)
        self.assertIn("dev.frozen", ids)
        for row in offer["not_rehearsable"]:
            self.assertTrue(row["why"], row["check"])
        # And nothing is in both lists: a check cannot be scored and
        # excused at the same time.
        planted = {row["check"] for row in self.r.PLAN if row["check"]}
        self.assertEqual(planted & ids, set())


# ---------------------------------------------------------------------------
# The planted defects really do fire the checks they are planted for
# ---------------------------------------------------------------------------

class TestThePlantedDefectsAreReal(unittest.TestCase):
    """Driven through the real check functions, not through the score.

    A plan whose automation does not actually trip `auto.dead_ref` would
    report a working check as broken on every install, forever — which is
    the one failure a rehearsal must not have.
    """

    def setUp(self):
        import rehearsal
        self.r = rehearsal
        from checks import automations as auto_checks
        self.checks = auto_checks

    def _snap(self, configs):
        return {
            "automations": configs,
            "states": {"sun.sun": {"state": "above_horizon", "attributes": {}},
                       "light.real": {"state": "on", "attributes": {}}},
            "registry": {}, "devices": {}, "areas": {},
            "services": {"light.turn_on", "notify.persistent_notification"},
            "available": {},
        }

    def test_the_dead_ref_automation_trips_dead_ref(self):
        row = next(r for r in self.r.PLAN if r["check"] == "auto.dead_ref")
        found = self.checks.dead_ref(self._snap([row["row"]["config"]]), 0.0)
        self.assertEqual(len(found), 1, found)
        self.assertIn(row["id"], found[0]["text"])

    def test_the_dead_service_automation_trips_dead_service(self):
        row = next(r for r in self.r.PLAN if r["check"] == "auto.dead_service")
        found = self.checks.dead_service(
            self._snap([row["row"]["config"]]), 0.0)
        self.assertEqual(len(found), 1, found)
        self.assertIn(row["id"], found[0]["text"])

    def test_neither_trips_the_other(self):
        """Two planted rows that both fire both checks would score four
        finds out of two, which is a number that means nothing."""
        ref = next(r for r in self.r.PLAN if r["check"] == "auto.dead_ref")
        svc = next(r for r in self.r.PLAN if r["check"] == "auto.dead_service")
        snap = self._snap([ref["row"]["config"]])
        self.assertEqual(self.checks.dead_service(snap, 0.0), [])
        snap = self._snap([svc["row"]["config"]])
        self.assertEqual(self.checks.dead_ref(snap, 0.0), [])

    def test_every_planted_automation_carries_the_brain_prefix(self):
        """`automation_writer.entry_for` only honours a config's own id
        behind the `brain_` prefix; without it the entry lands under a
        timestamp and nothing can find it to remove it."""
        import automation_writer
        for row in self.r.PLAN:
            if row["kind"] != "automation":
                continue
            entry = automation_writer.entry_for(row["row"], 1_700_000_000)
            self.assertEqual(entry["id"], row["id"])
            self.assertTrue(entry["id"].startswith(automation_writer.ID_PREFIX))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring(RehearsalCase):
    def _found(self, check, ident, source=None):
        return {"text": f"Automation '{ident}' is broken",
                "entity_id": f"automation.{ident}",
                "source": source or f"check:{check}"}

    async def test_every_planted_defect_found(self):
        planted = [r for r in self.r.PLAN if r["check"]]
        rows = [self._found(r["check"], r["id"]) for r in planted]
        score = self.r.score_checks({"findings": rows, "ran": ["x"]},
                                    self.r.PLAN)
        self.assertEqual((score["planted"], score["found"], score["extra"]),
                         (len(planted), len(planted), 0))
        self.assertTrue(all(r["verdict"] in ("found", "clean")
                            for r in score["rows"]))

    async def test_a_missed_defect_is_missed(self):
        score = self.r.score_checks({"findings": [], "ran": ["x"]},
                                    self.r.PLAN)
        self.assertEqual(score["found"], 0)
        self.assertIn("missed", [r["verdict"] for r in score["rows"]])

    async def test_a_row_under_the_wrong_check_id_does_not_count(self):
        """Finding the right automation for the wrong reason is not the
        check working."""
        row = next(r for r in self.r.PLAN if r["check"] == "auto.dead_ref")
        score = self.r.score_checks(
            {"findings": [self._found("auto.dead_ref", row["id"],
                                      source="check:auto.never_fired")],
             "ran": ["x"]}, self.r.PLAN)
        by = {r["id"]: r for r in score["rows"]}
        self.assertEqual(by[row["id"]]["verdict"], "missed")
        self.assertEqual(score["extra"], 1)

    async def test_a_finding_about_the_real_house_is_not_counted_either_way(self):
        """Counting it would make the number a property of how tidy the
        house is rather than of the checks."""
        rows = [{"text": "The porch light has been unavailable for a day",
                 "entity_id": "light.porch", "source": "check:dev.unavailable"}]
        score = self.r.score_checks({"findings": rows, "ran": ["x"]},
                                    self.r.PLAN)
        self.assertEqual(score["extra"], 0)

    async def test_anything_reported_about_the_healthy_row_is_a_false_positive(self):
        helper = next(r for r in self.r.PLAN if not r["check"])
        rows = [{"text": f"{helper['id']} is not used by anything",
                 "entity_id": helper["id"], "source": "check:reg.unused_helper"}]
        score = self.r.score_checks({"findings": rows, "ran": ["x"]},
                                    self.r.PLAN)
        by = {r["id"]: r for r in score["rows"]}
        self.assertEqual(by[helper["id"]]["verdict"], "false positive")
        # And it does not count against the planted total.
        self.assertEqual(score["planted"], 2)

    async def test_the_analyst_score_is_precision_and_recall_over_planted_rows(self):
        planted = [r for r in self.r.PLAN if r["check"]]
        answer = [{"text": f"{planted[0]['id']} names a missing entity"},
                  {"text": "brain_test_something_else is odd"},
                  {"text": "your porch light is unavailable"}]
        score = self.r.score_analyst(answer, self.r.PLAN, "a-model")
        self.assertEqual((score["planted"], score["found"], score["extra"]),
                         (2, 1, 1))
        self.assertEqual(score["recall"], 0.5)
        self.assertEqual(score["precision"], 0.5)
        self.assertEqual(score["model"], "a-model")

    async def test_a_perfect_analyst_scores_one_and_one(self):
        answer = [{"text": r["id"]} for r in self.r.PLAN if r["check"]]
        score = self.r.score_analyst(answer, self.r.PLAN)
        self.assertEqual((score["recall"], score["precision"]), (1.0, 1.0))

    async def test_an_analyst_that_found_nothing_scores_zero_not_a_crash(self):
        score = self.r.score_analyst([], self.r.PLAN)
        self.assertEqual((score["recall"], score["precision"]), (0.0, 0.0))

    async def test_a_bare_string_finding_is_read_too(self):
        """The card contract tolerates a model that drops to a plain
        string, and so must the score."""
        row = next(r for r in self.r.PLAN if r["check"])
        score = self.r.score_analyst([row["id"] + " is broken"], self.r.PLAN)
        self.assertEqual(score["found"], 1)


# ---------------------------------------------------------------------------
# The run, and the cleanup
# ---------------------------------------------------------------------------

class TestTheRun(RehearsalCase):
    async def test_the_happy_path_plants_scores_and_removes(self):
        planted = [r for r in self.r.PLAN if r["check"]]
        h, fake = hooks(self.r)

        async def snapshot():
            snap = await fake.snapshot()
            snap["findings_for_test"] = True
            return snap

        h.snapshot = snapshot
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [{"text": f"Automation '{r['id']}' is broken",
                          "entity_id": f"automation.{r['id']}",
                          "source": f"check:{r['check']}"} for r in planted],
            "ran": ["auto.dead_ref"], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            out = await self.r.run(h)
        finally:
            checks.run_all = real
        self.assertEqual(out["error"], "")
        self.assertEqual(out["checks"]["found"], len(planted))
        self.assertTrue(out["cleanup"]["ok"], out["cleanup"])
        self.assertEqual(fake.automations, {})
        self.assertEqual(fake.helpers, {})

    async def test_a_failure_halfway_still_cleans_up(self):
        """The removal is in a `finally`, because the thing left behind is
        in somebody's automations.yaml."""
        h, fake = hooks(self.r)

        async def boom(planted):
            raise RuntimeError("the analyst exploded")

        h.analyst = boom
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [], "ran": [], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            out = await self.r.run(h)
        finally:
            checks.run_all = real
        self.assertIn("exploded", out["error"])
        self.assertTrue(out["cleanup"]["ok"], out["cleanup"])
        self.assertEqual(fake.automations, {})
        self.assertEqual(fake.helpers, {})

    async def test_a_write_that_fails_stops_before_the_rest_and_removes_what_landed(self):
        h, fake = hooks(self.r, write_fails="dead_service")
        out = await self.r.run(h)
        self.assertIn("could not create", out["error"])
        self.assertEqual(fake.automations, {}, "the first one was removed")

    async def test_a_helper_that_did_not_go_is_the_loudest_line(self):
        h, fake = hooks(self.r, skip_helper_delete=True)
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [], "ran": [], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            out = await self.r.run(h)
        finally:
            checks.run_all = real
        self.assertFalse(out["cleanup"]["ok"])
        self.assertIn("LEFT BEHIND", out["cleanup"]["sentence"])
        self.assertIn("input_number.brain_test_reading",
                      out["cleanup"]["sentence"])

    async def test_a_removal_that_refused_is_reported_by_name(self):
        h, fake = hooks(self.r, remove_fails="dead_ref")
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [], "ran": [], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            out = await self.r.run(h)
        finally:
            checks.run_all = real
        self.assertFalse(out["cleanup"]["ok"])
        self.assertIn("brain_test_dead_ref", out["cleanup"]["sentence"])

    async def test_the_cleanup_is_verified_against_a_fresh_snapshot(self):
        """Not "the removals reported ok" — "nothing under the prefix is
        left", read back from the house."""
        h, fake = hooks(self.r)

        async def lying_remove(entry_id, entity_id=""):
            return True, ""        # says yes, changes nothing

        h.remove = lying_remove
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [], "ran": [], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            out = await self.r.run(h)
        finally:
            checks.run_all = real
        self.assertFalse(out["cleanup"]["ok"])
        self.assertIn("still in the house", out["cleanup"]["sentence"])

    async def test_leftovers_reads_all_three_places(self):
        snap = {"automations": [{"id": "brain_test_dead_ref"}],
                "registry": {"input_number.brain_test_reading": {}},
                "states": {"automation.brain_test_other": {}}}
        self.assertEqual(self.r.leftovers(snap),
                         ["automation.brain_test_other",
                          "brain_test_dead_ref",
                          "input_number.brain_test_reading"])

    async def test_a_clean_house_has_no_leftovers(self):
        self.assertEqual(self.r.leftovers(
            {"automations": [{"id": "morning"}],
             "registry": {"light.porch": {}}, "states": {"sun.sun": {}}}), [])

    async def test_the_summary_is_numbers_and_never_the_rows(self):
        self.r.save({"finished_at": 5, "checks": {"planted": 2, "found": 1,
                                                  "extra": 0, "rows": [1, 2]},
                     "analyst": {"precision": 0.5, "recall": 0.5,
                                 "model": "m", "ran": True, "rows": [1]},
                     "cleanup": {"ok": True}})
        s = self.r.summary()
        self.assertEqual(s["checks"], {"planted": 2, "found": 1, "extra": 0})
        self.assertNotIn("rows", s["checks"])
        self.assertNotIn("rows", s["analyst"])
        self.assertTrue(s["cleanup_ok"])

    async def test_no_run_yet_is_an_empty_summary(self):
        self.assertEqual(self.r.summary(),
                         {"ran_at": 0, "checks": {}, "analyst": {}})

    async def test_the_run_is_journaled(self):
        import journal
        h, _ = hooks(self.r)
        import checks
        real = checks.run_all
        checks.run_all = lambda snap, now=None, only=None: {
            "findings": [], "ran": [], "skipped": {}, "errors": {},
            "per_check": {}}
        try:
            await self.r.run(h)
        finally:
            checks.run_all = real
        rows = [r for r in journal.tail(0) if r.get("source") == "doctor"]
        self.assertTrue(rows)
        self.assertEqual(rows[-1]["extra"]["stage"], "rehearsal")


# ---------------------------------------------------------------------------
# The routes: the 428, the refusal, and the 409
# ---------------------------------------------------------------------------

class TestTheRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        for key, value in {
            "BRAIN_REHEARSAL_FILE": os.path.join(base, "rehearsal.json"),
            "BRAIN_DOCTOR_DEEP_FILE": os.path.join(base, "deep.json"),
            "BRAIN_FINDINGS_FILE": os.path.join(base, "findings.json"),
            "BRAIN_FINDINGS_SETTLED": os.path.join(base, "settled.json"),
            "BRAIN_FINDINGS_STATE": os.path.join(base, "state.json"),
            "BRAIN_FINDINGS_INBOX": os.path.join(base, "finbox"),
            "BRAIN_JOURNAL_FILE": os.path.join(base, "journal.jsonl"),
            "BRAIN_MEMORY_DIR": os.path.join(base, "memory"),
            "BRAIN_MEMORY_INBOX": os.path.join(base, "memory", "inbox"),
            "BRAIN_DIR": os.path.join(base, "insights"),
            "BRAIN_SETTINGS_FILE": os.path.join(base, "settings.json"),
            "BRAIN_KNOWLEDGE_FILE": os.path.join(base, "knowledge.json"),
            "BRAIN_DIAGNOSTICS_FILE": os.path.join(base, "diag.json"),
            "BRAIN_PROTECTED_ENTITIES": "",
        }.items():
            os.environ[key] = value
        import rehearsal
        importlib.reload(rehearsal)
        import server
        self.server = importlib.reload(server)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    class R:
        can_read_body = True
        match_info: dict = {}

        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

        async def text(self):
            return json.dumps(self._body)

    async def test_without_consent_it_is_428_and_nothing_is_queued(self):
        resp = await self.server.h_rehearse_start(self.R({}))
        self.assertEqual(resp.status, 428)
        body = json.loads(resp.text)
        self.assertTrue(body["plan"])
        self.assertIn("consent", body["error"])
        self.assertTrue(self.server.QUEUE.empty(),
                        "a rehearsal was queued without consent")

    async def test_with_consent_it_queues_a_rehearse_job(self):
        resp = await self.server.h_rehearse_start(self.R({"consent": True}))
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.server.JOBS["doctor-rehearse"]["kind"],
                         "rehearse")
        self.assertEqual(self.server.QUEUE.get_nowait(), "doctor-rehearse")

    async def test_a_protected_pattern_refuses_even_with_consent(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "input_number.*"
        try:
            resp = await self.server.h_rehearse_start(
                self.R({"consent": True}))
        finally:
            os.environ["BRAIN_PROTECTED_ENTITIES"] = ""
        self.assertEqual(resp.status, 409)
        self.assertIn("protected_entities", json.loads(resp.text)["refused"])
        self.assertTrue(self.server.QUEUE.empty())

    async def test_a_deep_run_in_flight_blocks_a_rehearsal(self):
        self.server.DOCTOR_STATE.update(running=True, kind="deep")
        try:
            resp = await self.server.h_rehearse_start(
                self.R({"consent": True}))
        finally:
            self.server.DOCTOR_STATE.update(running=False, kind="")
        self.assertEqual(resp.status, 409)
        self.assertIn("already running", json.loads(resp.text)["error"])

    async def test_the_get_carries_the_plan_so_the_dialog_can_ask(self):
        resp = await self.server.h_rehearse_get(self.R({}))
        body = json.loads(resp.text)
        self.assertTrue(body["plan"])
        self.assertTrue(body["not_rehearsable"])
        self.assertFalse(body["running"])

    async def test_diagnostics_carries_the_rehearsal_summary(self):
        import asyncio
        import rehearsal
        rehearsal.save({"finished_at": 7,
                        "checks": {"planted": 2, "found": 2, "extra": 0},
                        "analyst": {"precision": 1.0, "recall": 1.0,
                                    "model": "m", "ran": True},
                        "cleanup": {"ok": True}})
        payload = await asyncio.to_thread(self.server._diagnostics_payload)
        self.assertEqual(payload["rehearsal"]["checks"]["found"], 2)
        self.assertEqual(payload["rehearsal"]["analyst"]["recall"], 1.0)


# ---------------------------------------------------------------------------
# The leftover check, lifted out of the real script and driven
# ---------------------------------------------------------------------------

def leftover_block() -> str:
    src = SELFTEST.read_text(encoding="utf-8")
    match = re.search(r"^brain_test_leftovers\(\) \{\n.*?^\}\n", src,
                      re.M | re.S)
    assert match, "ha-selftest.sh no longer defines brain_test_leftovers"
    return match.group(0)


class TestTheLeftoverCheck(unittest.TestCase):
    """The design page's own recommendation: cleanup is the first thing the
    plain doctor verifies next time. Driven rather than grepped."""

    def run_block(self, autos_text: str | None) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            config.mkdir()
            if autos_text is not None:
                (config / "automations.yaml").write_text(autos_text)
            script = (
                "set -u\n"
                'pass() { echo "PASS $1"; }\n'
                'warn() { echo "WARN $1"; }\n'
                'info() { echo "INFO $1"; }\n'
                f'BRAIN_CONFIG_DIR={config}\n'
                'HA_BASE_URL=http://127.0.0.1:1\n'
                'SUPERVISOR_TOKEN=\n'
                + leftover_block()
                + "brain_test_leftovers\n"
            )
            return subprocess.run(["bash", "-c", script], capture_output=True,
                                  text=True, timeout=30)

    def test_a_clean_house_passes(self):
        out = self.run_block("- id: morning\n  alias: Morning\n").stdout
        self.assertIn("PASS no rehearsal leftovers", out)

    def test_a_leftover_automation_warns_and_names_the_fix(self):
        out = self.run_block(
            "- id: brain_test_dead_ref\n  alias: brain_test_dead_ref\n").stdout
        self.assertIn("WARN a rehearsal left something behind", out)
        self.assertIn("automations.yaml", out)
        self.assertIn("brain doctor --rehearse", out)

    def test_a_missing_automations_file_is_not_a_leftover(self):
        self.assertIn("PASS no rehearsal leftovers", self.run_block(None).stdout)

    def test_the_real_script_calls_it(self):
        """A function nothing calls is a check that never runs."""
        src = SELFTEST.read_text(encoding="utf-8")
        self.assertIn("\nbrain_test_leftovers\n", src)
        self.assertIn("Rehearsal leftovers", src)


if __name__ == "__main__":
    unittest.main()
