#!/usr/bin/env python3
"""Numbers that agree: one source for every count, and the status line.

The walkthrough that started the redesign found every number disagreeing
with another: the To-do badge said 2 while its list held 4, Home
Assistant's To-do held 5, facts were 99 in HA and 755 in the panel, the
morning brief said 677 of 721 runs failed while Diagnostics said 224 ok,
and the health sensor said `ok` while Diagnostics said degraded. Each half
here is driven through the real code on both sides of the gap — the
panel's real counters into the real status mirror, and the integration's
real entities reading it — because a number written down twice is the
drift this file exists to stop.

Also the copy bugs in server-composed text: "-100.233labels", "press
Wrong" (no Wrong button exists), and a sentence cut mid-word.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import os
import re
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(PANEL_DIR))

import brain_status  # noqa: E402
import numfmt  # noqa: E402
import textclip  # noqa: E402

GLUED = re.compile(r"\d[a-zA-Z]")


def _load_leaf(name: str):
    spec = importlib.util.spec_from_file_location(
        f"brain_leaf_under_test_{name}", INTEGRATION_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status_mirror = _load_leaf("status_mirror")


# ---------------------------------------------------------------------------
# Numbers in sentences
# ---------------------------------------------------------------------------

class TestNumbersReadTheWayPeopleWriteThem(unittest.TestCase):
    def test_the_walkthroughs_own_example(self):
        self.assertEqual(numfmt.quantity(-100.233, "labels"), "−100 labels")
        self.assertEqual(numfmt.times(5.39), "5.4 times")
        self.assertEqual(numfmt.times(1.0), "1 time")

    def test_rounding_by_size(self):
        self.assertEqual(numfmt.number(1234.56), "1,235")
        self.assertEqual(numfmt.number(21.46), "21.5")
        self.assertEqual(numfmt.number(21.0), "21")
        self.assertEqual(numfmt.number(0.5), "0.5")
        self.assertEqual(numfmt.number(0.01234), "0.012")
        self.assertEqual(numfmt.number(0), "0")
        self.assertEqual(numfmt.number(-0.0001), "−0.0001")

    def test_signs_and_units(self):
        self.assertEqual(numfmt.quantity(3.58, "labels", signed=True),
                         "+3.6 labels")
        self.assertEqual(numfmt.quantity(40, "%"), "40%")
        self.assertEqual(numfmt.quantity(21.5, "°C"), "21.5 °C")
        self.assertEqual(numfmt.quantity(5, ""), "5")

    def test_not_a_number_is_its_own_text_and_never_a_raise(self):
        self.assertEqual(numfmt.number("abc"), "abc")
        self.assertEqual(numfmt.number(None), "")
        self.assertEqual(numfmt.number(float("nan")), "nan")


class TestTheDriftCheckSaysItReadably(unittest.TestCase):
    """`forecast.decline` over a BRUH Print roll — the card the walkthrough
    found reading "-100.233labels … 5.39 times it" — driven for real."""

    NOW = 1_700_000_000.0

    def setUp(self):
        import baselines
        self.forecasts = importlib.import_module("checks.forecasts")
        bucket = str(baselines.hour_of_week(self.NOW, dt.timezone.utc))
        eid = "sensor.labelwriter_left_roll"
        self.snap = {
            "now": self.NOW,
            "states": {eid: {"state": "120", "attributes": {
                "state_class": "measurement",
                "unit_of_measurement": "labels"},
                "last_changed": "", "last_updated": ""}},
            "entities": [{"entity_id": eid, "name": "Left roll"}],
            "devices": [], "areas": [],
            "baselines": {"built_at": int(self.NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {eid: {
                              "unit": "labels", "samples": 672,
                              "overall": {"median": 200.0, "spread": 18.6,
                                          "n": 672},
                              "buckets": {bucket: {"median": 200.0,
                                                   "spread": 18.6, "n": 4}},
                              "trend": {"per_day": -3.5797, "move": -100.233,
                                        "days": 28.0, "noise": 18.6113,
                                        "spreads": 5.39, "consistent": True,
                                        "points": 672}}}}}

    def test_the_detail_is_rounded_and_spaced(self):
        [row] = self.forecasts.decline(self.snap, self.NOW)
        detail = row["detail"]
        self.assertIn("−100 labels over the last 28 days", detail)
        self.assertIn("−3.6 labels a day", detail)
        self.assertIn("18.6 labels", detail)
        self.assertIn("5.4 times it", detail)
        self.assertIsNone(GLUED.search(detail), detail)
        self.assertNotIn("100.233", detail)

    def test_no_card_tells_anybody_to_press_a_button_that_is_not_there(self):
        [row] = self.forecasts.decline(self.snap, self.NOW)
        self.assertNotIn("Wrong", row["fix"])
        self.assertIn("press Ignore", row["fix"])


class TestNoCheckSaysPressWrong(unittest.TestCase):
    """No button is called Wrong — it is Ignore — so no server-composed
    sentence may tell anybody to press it. Read off the source because the
    strings live inside f-strings across a dozen checks, and the claim is
    exactly "this string is absent", which a grep can honestly make."""

    def test_no_string_literal_says_press_wrong(self):
        import ast
        offenders = []
        for path in list(PANEL_DIR.glob("*.py")) + list(
                (PANEL_DIR / "checks").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Docstrings are prose about history; only strings a person
            # can be shown count.
            docs = {id(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in docs
                        and re.search(r"press(?:ing)?\s+Wrong|marked Wrong",
                                      node.value)):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])


class TestSentencesAreNotCutMidWord(unittest.TestCase):
    def test_a_morning_brief_on_a_phone_ends_on_a_word(self):
        import notify_router
        title, body = notify_router.compose_brief("word " * 400)
        self.assertLessEqual(len(body), notify_router.MESSAGE_MAX)
        self.assertTrue(body.endswith(textclip.ELLIPSIS), body[-20:])


# ---------------------------------------------------------------------------
# The status line
# ---------------------------------------------------------------------------

class TestTheStatusLine(unittest.TestCase):
    NOW = 1_700_000_000.0

    def derive(self, **kw):
        base = {"signed_in": True, "now": self.NOW,
                "clock": lambda ts: "10:20 PM"}
        base.update(kw)
        return brain_status.derive(**base)

    def test_watching_says_when_it_last_looked(self):
        st = self.derive(last_look_at=self.NOW - 9 * 60)
        self.assertEqual(st["state"], "watching")
        self.assertEqual(st["label"], "Watching")
        self.assertEqual(st["sentence"], "Watching · last look 9 min ago")
        self.assertEqual(st["last_look_at"], int(self.NOW - 540))

    def test_a_usage_limit_is_paused_with_when_it_ends(self):
        st = self.derive(rate_limit_until=self.NOW + 3600)
        self.assertEqual(st["state"], "paused")
        self.assertEqual(st["sentence"],
                         "Paused: Claude limit reached, back at 10:20 PM.")
        self.assertEqual(st["back_at"], int(self.NOW + 3600))

    def test_a_spent_budget_and_a_switched_off_house_are_paused_too(self):
        st = self.derive(budget={"blocked": True, "resets_at": self.NOW + 60})
        self.assertEqual((st["state"], st["back_at"]),
                         ("paused", int(self.NOW + 60)))
        st = self.derive(auto_enabled=False)
        self.assertEqual(st["state"], "paused")
        self.assertIsNone(st["back_at"])

    def test_a_restart_owed_says_the_one_thing_to_do(self):
        st = self.derive(restart_pending=True, restart_since=self.NOW - 60,
                         rate_limit_until=self.NOW + 60)
        self.assertEqual(st["state"], "needs_restart")
        self.assertEqual(st["sentence"],
                         "Restart Home Assistant to finish updating brAIn.")
        self.assertEqual(st["since"], int(self.NOW - 60))

    def test_signed_out_outranks_everything(self):
        self.assertEqual(self.derive(signed_in=False, restart_pending=True)
                         ["state"], "signed_out")
        self.assertEqual(self.derive(auth_state="failed")["state"],
                         "signed_out")

    def test_a_health_verdict_that_is_not_ok_is_degraded(self):
        st = self.derive(health={"state": "degraded",
                                 "reason": "the automation listener stopped"})
        self.assertEqual(st["state"], "degraded")
        self.assertIn("automation listener stopped", st["sentence"])
        self.assertEqual(self.derive(health={"state": "ok"})["state"],
                         "watching")

    def test_every_answer_has_the_same_shape(self):
        keys = {"state", "label", "sentence", "since", "back_at",
                "last_look_at"}
        for kw in ({}, {"signed_in": False}, {"restart_pending": True},
                   {"auto_enabled": False},
                   {"health": {"state": "failed", "reason": "x"}}):
            self.assertEqual(set(self.derive(**kw)), keys, kw)

    def test_the_vocabulary_is_the_integrations(self):
        self.assertEqual(set(brain_status.STATES) | {"unknown"},
                         set(status_mirror.STATES))


# ---------------------------------------------------------------------------
# One source for every count — the panel half
# ---------------------------------------------------------------------------

class ServerStoresCase(unittest.TestCase):
    """The four stores in a temp dir, patched on the modules the SERVER
    holds (several test files re-import panel modules, so the copy this
    file imported can be a different object from the one the server
    writes through)."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        s = self.server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        targets = [
            (s.findings_store, "FINDINGS_FILE", root / "findings.json"),
            (s.findings_store, "INBOX_DIR", root / "inbox"),
            (s.findings_store, "SETTLED_FILE", root / "settled.json"),
            (s.findings_store, "STATE_FILE", root / "config/.brain/f.json"),
            (s.hypotheses, "HYPOTHESES_FILE", root / "hypotheses.jsonl"),
            (s.proposals, "STORE", root / "proposals.json"),
            (s.proposals, "SETTLED_FILE", root / "p-settled.json"),
            (s.proposals, "SHARED", root / "config/.brain/p.json"),
            (s.todo_store, "TODO_FILE", root / "todo.json"),
            (s.todo_store, "STATE_FILE", root / "config/.brain/t.json"),
            (s.cases, "SNOOZE_FILE", root / "snooze.json"),
            (s.facts_store, "FACTS_FILE", root / "memory" / "facts.json"),
            (s, "STATUS_FILE", root / "config" / ".brain" / "status.json"),
        ]
        # ...and the same stores on the copies `cases` holds, which after a
        # re-import elsewhere in the suite can be different module objects.
        held = {id(getattr(s, n)): getattr(s.cases, n)
                for n in ("findings_store", "hypotheses", "proposals",
                          "todo_store")}
        extra = [(held[id(mod)], name, value) for mod, name, value in targets
                 if id(mod) in held and held[id(mod)] is not mod]
        for mod, name, value in targets + extra:
            p = patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def file_problem(self):
        [row] = self.server.findings_store.add_many([{
            "text": "The hall sensor has not reported since Tuesday",
            "severity": "serious", "entity_id": "sensor.hall_motion",
            "source": "check:dev.unavailable"}])
        return row

    def file_question(self):
        return self.server.hypotheses.propose(
            "The garage fridge is meant to run all night", "fridge")

    def file_suggestion(self):
        return self.server.proposals.add({
            "kind": "routine", "source": "routines",
            "title": "Turn the porch light off at 23:10",
            "why": "You do this by hand on nine evenings out of ten.",
            "config": {"alias": None, "trigger": [{"platform": "time"}]}})

    def file_chore(self):
        return self.server.todo_store.add(
            "Replace the hall sensor battery", origin="hand")


class TestAProposalIsNotCutMidWord(ServerStoresCase):
    def test_a_suggestion_title_ends_on_a_word_with_an_ellipsis(self):
        p = self.server.proposals
        long = "Turn the porch light off at quarter past eleven "
        row = p.add({"kind": "routine", "source": "routines",
                     "title": long * 10, "why": long * 40,
                     "config": {"trigger": [{"platform": "time"}]}})
        self.assertLessEqual(len(row["title"]), p.TITLE_MAX)
        self.assertTrue(row["title"].endswith(textclip.ELLIPSIS), row["title"])
        self.assertTrue(row["why"].endswith(textclip.ELLIPSIS))
        kept = row["title"][:-1]
        self.assertTrue((long * 10).startswith(kept))
        self.assertEqual((long * 10)[len(kept)], " ", "cut mid-word")


class TestOneCountForTheQueue(ServerStoresCase):
    def test_the_queue_is_findings_questions_and_suggestions(self):
        self.file_problem()
        self.file_question()
        self.file_suggestion()
        self.file_chore()
        # Three decisions; the chore is To Do, not the queue.
        self.assertEqual(self.server.cases.queue_count(), 3)
        # The old feed count left the suggestion out, which is how one
        # badge and one list disagreed.
        self.assertEqual(self.server.cases.open_count(), 2)

    def test_every_route_a_badge_reads_says_the_same_number(self):
        self.file_problem()
        self.file_question()
        self.file_suggestion()
        self.file_chore()
        _auth, read = self.server._status_payload()
        findings = self.server._findings_payload()
        cases_payload = self.server._cases_payload()
        self.assertEqual(read["queue_count"], 3)
        self.assertEqual(read["findings_open"], 3)
        self.assertEqual(findings["open"], 3)
        self.assertEqual(findings["queue_count"], 3)
        self.assertEqual(cases_payload["open"], 3)
        self.assertEqual(read["list_count"],
                         self.server.todo_store.listing()["open"])
        self.assertEqual(read["list_count"], 1)

    def test_the_status_object_rides_api_status(self):
        _auth, read = self.server._status_payload()
        self.assertEqual(set(read["status"]),
                         {"state", "label", "sentence", "since", "back_at",
                          "last_look_at"})


class TestFactsAreOneCount(ServerStoresCase):
    def test_the_house_view_total_the_summary_and_the_mirror_agree(self):
        fs = self.server.facts_store
        (self.root / "memory").mkdir()
        for i in range(5):
            fs.add(f"The boiler is serviced in month {i}", subject="house",
                   source="panel")
        fs.add("A guest is staying", subject="house", source="occasion",
               expires="2000-01-01")
        browse = fs.browse()
        self.assertEqual(browse["all"], 5)
        self.assertEqual(fs.count(), 5)
        self.assertEqual(fs.summary()["count"], 5)
        self.assertEqual(self.server._counts()["facts_count"], 5)


class TestRunsAreCountedOverOneSet(unittest.TestCase):
    """Health's "N of M runs did not succeed" divides Claude failures by
    Claude runs. It divided every failed journal row — the summary row
    `_generate` writes beside each failed card among them — by every
    journal line, which is how a brief said 677 of 721."""

    def test_the_rate_is_claude_runs_over_claude_runs(self):
        import health
        journal = {"runs": 721, "failed": 677,
                   "failed_by_outcome": {"error": 677},
                   "claude_runs": 300, "claude_failed": 76,
                   "claude_failed_by_outcome": {"error": 76}}
        found = health.problems({"journal": journal}, {})
        self.assertFalse([p for p in found if p.get("id") == "runs"])
        journal["claude_failed"] = 200
        journal["claude_failed_by_outcome"] = {"error": 200}
        [runs] = [p for p in health.problems({"journal": journal}, {})
                  if p.get("id") == "runs"]
        self.assertIn("200 of 300 runs", runs["fix"])

    def test_the_summary_counts_claude_failures_apart(self):
        import journal as journal_mod
        rows = [{"ts": 100, "source": "card", "outcome": "error",
                 "model": "x", "tokens": 1},
                {"ts": 100, "source": "card", "outcome": "error"},
                {"ts": 100, "source": "card", "outcome": "ok", "model": "x"}]
        with patch.object(journal_mod, "tail", lambda n=0: rows):
            out = journal_mod.summary(24, now=200)
        self.assertEqual((out["claude_runs"], out["claude_failed"]), (2, 1))
        self.assertEqual(out["failed"], 2)


# ---------------------------------------------------------------------------
# The mirror, and the integration's entities reading it
# ---------------------------------------------------------------------------

class TestTheStatusMirror(ServerStoresCase):
    def publish(self):
        (self.root / "config" / ".brain").mkdir(parents=True, exist_ok=True)
        self.server.publish_status()
        return self.server.STATUS_FILE

    def test_the_mirror_carries_the_panels_own_answers(self):
        self.file_problem()
        self.file_suggestion()
        self.file_chore()
        path = self.publish()
        data = json.loads(path.read_text(encoding="utf-8"))
        _auth, read = self.server._status_payload()
        self.assertEqual(data["queue_count"], read["queue_count"])
        self.assertEqual(data["list_count"], read["list_count"])
        self.assertEqual(data["status"]["state"], read["status"]["state"])
        self.assertEqual(data["stale_after_s"], self.server.STATUS_STALE_S)

    def test_the_reader_reads_what_the_writer_wrote(self):
        self.file_problem()
        path = self.publish()
        state, attrs = status_mirror.status(str(path))
        self.assertIn(state, status_mirror.STATES)
        self.assertNotEqual(state, "unknown")
        self.assertEqual(status_mirror.count(str(path), "queue_count"), (1, ""))

    def test_a_dev_checkout_grows_no_config(self):
        self.server.publish_status()
        self.assertFalse(self.server.STATUS_FILE.exists())


class TestTheReaderNeverRaises(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "status.json"

    def write(self, body):
        self.path.write_text(json.dumps(body), encoding="utf-8")

    def test_missing_garbage_and_stale_are_unknown_with_a_reason(self):
        state, attrs = status_mirror.status(str(self.path))
        self.assertEqual(state, "unknown")
        self.assertIn("not published", attrs["reason"])
        self.path.write_text("[1,2]")
        self.assertEqual(status_mirror.status(str(self.path))[0], "unknown")
        self.write({"status": {"state": "watching"}, "queue_count": 2,
                    "stale_after_s": 60})
        old = time.time() - 600
        os.utime(self.path, (old, old))
        state, attrs = status_mirror.status(str(self.path))
        self.assertEqual(state, "unknown")
        self.assertIn("not running", attrs["reason"])
        value, reason = status_mirror.count(str(self.path), "queue_count")
        self.assertIsNone(value)
        self.assertIn("not running", reason)

    def test_a_count_the_panel_could_not_take_is_unknown_not_zero(self):
        self.write({"status": {"state": "watching"}, "queue_count": None})
        self.assertEqual(status_mirror.count(str(self.path), "queue_count")[0],
                         None)
        self.write({"status": {"state": "partying"}, "queue_count": True})
        self.assertEqual(status_mirror.status(str(self.path))[0], "unknown")
        self.assertIsNone(status_mirror.count(str(self.path), "queue_count")[0])


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _import_platforms():
    """`sensor.py` and `binary_sensor.py` behind permissive stubs, with
    `sys.modules` put back as it was found."""
    saved = dict(sys.modules)
    try:
        for name in ("homeassistant", "homeassistant.components",
                     "homeassistant.components.sensor",
                     "homeassistant.components.binary_sensor",
                     "homeassistant.config_entries", "homeassistant.const",
                     "homeassistant.core", "homeassistant.helpers",
                     "homeassistant.helpers.issue_registry",
                     "homeassistant.helpers.device_registry",
                     "homeassistant.helpers.entity_platform",
                     "homeassistant.helpers.dispatcher"):
            sys.modules[name] = _AutoModule(name)
        sys.modules["homeassistant.components.sensor"].SensorEntity = type(
            "SensorEntity", (), {})
        sys.modules["homeassistant.components.binary_sensor"]\
            .BinarySensorEntity = type("BinarySensorEntity", (), {})
        sys.modules["homeassistant.core"].callback = lambda func: func
        sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = \
            lambda **kw: dict(kw)
        pkg = types.ModuleType("brain_numbers_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_numbers_cc"] = pkg
        return (importlib.import_module("brain_numbers_cc.sensor"),
                importlib.import_module("brain_numbers_cc.binary_sensor"))
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


class TestTheEntitiesMatchThePanel(ServerStoresCase):
    """Entity names and states match the panel: the real panel writes the
    mirror, the real entities read it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sensor, cls.binary = _import_platforms()

    def hass(self):
        root = self.root / "config"

        class Config:
            def path(self, *parts):
                return str(root.joinpath(*parts))

        class Hass:
            config = Config()

            async def async_add_executor_job(self, func, *args):
                return func(*args)

        return Hass()

    def publish(self):
        (self.root / "config" / ".brain").mkdir(parents=True, exist_ok=True)
        self.server.publish_status()

    def test_status_needs_you_and_facts_read_the_panels_numbers(self):
        hass = self.hass()
        status = self.sensor.BrainStatusSensor(None)
        needs = self.binary.BrainNeedsYouSensor(None)
        facts = self.sensor.BrainFactsSensor(None)
        for entity in (status, needs, facts):
            entity.hass = hass
        self.assertEqual(status.entity_id, "sensor.brain_status")
        self.assertEqual(needs.entity_id, "binary_sensor.brain_needs_you")
        self.assertEqual(status._attr_unique_id, "brain_status")
        self.assertEqual(needs._attr_unique_id, "brain_needs_you")
        self.assertEqual(facts._attr_unique_id, "brain_facts_learned")

        # Nothing published: unknown with a reason — never "off", never 0.
        asyncio.run(status.async_update())
        needs.update()
        facts.update()
        self.assertEqual(status._attr_native_value, "unknown")
        self.assertIsNone(needs._attr_is_on)
        self.assertIn("reason", needs.extra_state_attributes)
        self.assertIsNone(facts._attr_native_value)
        self.assertIn("reason", facts.extra_state_attributes)

        # An empty queue: off, and the status the panel itself gives.
        self.publish()
        _auth, read = self.server._status_payload()
        asyncio.run(status.async_update())
        needs.update()
        self.assertEqual(status._attr_native_value, read["status"]["state"])
        self.assertEqual(status.extra_state_attributes["sentence"],
                         read["status"]["sentence"])
        self.assertIs(needs._attr_is_on, False)

        # Something waiting: on, with the badge's own count.
        self.file_problem()
        self.file_suggestion()
        self.publish()
        needs.update()
        self.assertIs(needs._attr_is_on, True)
        self.assertEqual(needs.extra_state_attributes["count"],
                         self.server.cases.queue_count())

    def test_the_facts_sensor_says_what_the_house_view_says(self):
        hass = self.hass()
        (self.root / "memory").mkdir()
        for i in range(3):
            self.server.facts_store.add(f"Fact number {i} about the boiler",
                                        subject="house", source="panel")
        self.publish()
        facts = self.sensor.BrainFactsSensor(None)
        facts.hass = hass
        facts.update()
        self.assertEqual(facts._attr_native_value,
                         self.server.facts_store.browse()["all"])
        self.assertEqual(facts._attr_native_value, 3)

    def test_the_old_waiting_on_you_sensor_says_what_it_counts(self):
        self.assertEqual(self.binary.BrainWantsInputSensor._attr_name,
                         "Questions waiting")
        self.assertEqual(self.binary.BrainWantsInputSensor(None)
                         ._attr_unique_id, "brain_wants_input")
        self.assertEqual(self.binary.BrainNeedsYouSensor._attr_device_info
                         ["identifiers"], {("brain", "system_health")})

    def test_setup_adds_both(self):
        import ast
        for module, cls in (("sensor.py", "BrainStatusSensor"),
                            ("binary_sensor.py", "BrainNeedsYouSensor")):
            tree = ast.parse((INTEGRATION_DIR / module).read_text())
            setup = next(n for n in tree.body
                         if isinstance(n, ast.AsyncFunctionDef)
                         and n.name == "async_setup_entry")
            names = {n.func.id for n in ast.walk(setup)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name)}
            self.assertIn(cls, names, module)


# ---------------------------------------------------------------------------
# Urgent cards raise a Repair
# ---------------------------------------------------------------------------

class TestUrgentCardsRaiseARepair(ServerStoresCase):
    def test_the_mirror_marks_an_urgent_row_and_only_that_row(self):
        fs = self.server.findings_store
        (self.root / "config" / ".brain").mkdir(parents=True, exist_ok=True)
        fs.add_many([
            {"text": "Water under the dishwasher", "severity": "critical",
             "source": "safety", "entity_id": "binary_sensor.leak"},
            {"text": "A battery is low", "severity": "warning",
             "source": "check:dev.battery_low"}])
        fs.publish_state()
        state = json.loads(fs.STATE_FILE.read_text(encoding="utf-8"))
        flags = {r["text"]: r.get("urgent") for r in state["findings"]}
        self.assertIs(flags["Water under the dishwasher"], True)
        self.assertIsNone(flags["A battery is low"])

    def test_an_urgent_row_beats_the_cap(self):
        env_dir = str(Path(__file__).resolve().parent)
        if env_dir not in sys.path:
            sys.path.insert(0, env_dir)
        import brain_ha_env as env
        pkg = env.load_integration()
        created: list = []
        ir = pkg.findings.ir
        with patch.object(ir, "async_create_issue",
                          lambda hass, domain, issue_id, **kw:
                          created.append((issue_id, kw["severity"]))), \
                patch.object(ir, "async_delete_issue", lambda *a, **k: None):
            hass = types.SimpleNamespace(data={})
            watcher = pkg.findings.FindingsWatcher(hass)
            current = {ts: {"ts": ts, "text": f"warning {ts}",
                            "severity": "warning", "status": "open"}
                       for ts in range(1, 41)}
            current[999] = {"ts": 999, "text": "Water under the sink",
                            "severity": "critical", "status": "open",
                            "urgent": True}
            watcher.sync_issues(current)
        ids = [i for i, _sev in created]
        self.assertEqual(len(ids), pkg.findings.MAX_REPAIR_ISSUES)
        self.assertIn("finding_999", ids)
        sev = dict(created)["finding_999"]
        self.assertEqual(sev, getattr(ir.IssueSeverity, "CRITICAL", None)
                         or ir.IssueSeverity.ERROR)


if __name__ == "__main__":
    unittest.main()


class TestTheOpenFindingsSensorIsTheQueue(ServerStoresCase):
    """`sensor.brain_open_findings` read the findings mirror's own `open` —
    the findings alone — while every panel surface reads the queue
    (`cases.queue_count`): findings, questions and suggestions, and a row
    still waiting for its first look past `triage.SHOW_AFTER_S`. So one
    open question was a badge of 3 beside a sensor of 2."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_dir = str(Path(__file__).resolve().parent)
        if env_dir not in sys.path:
            sys.path.insert(0, env_dir)
        import brain_ha_env as env
        cls.sensor, _binary = _import_platforms()
        # `update` imports the mirror's reader at call time; the real one,
        # out of the integration loaded for real.
        cls.findings = env.load_integration().findings

    def file_unlooked(self):
        fs = self.server.findings_store
        [row] = fs.add_many(self.server.triage.gate([{
            "text": "The cellar sensor reads far outside its range",
            "severity": "warning", "entity_id": "sensor.cellar",
            "source": "check:base.unusual"}]))
        items = fs._load()
        for item in items:
            if item["ts"] == row["ts"]:
                item["ts"] -= self.server.triage.SHOW_AFTER_S + 60
        fs._write(items)

    def test_the_mirror_and_the_sensor_count_what_the_panel_counts(self):
        (self.root / "config" / ".brain").mkdir(parents=True, exist_ok=True)
        # Where the integration reads it, so both halves meet on one file.
        fs = self.server.findings_store
        p = patch.object(fs, "STATE_FILE", self.root / "config" / ".brain"
                         / self.findings.FINDINGS_STATE_FILENAME)
        p.start()
        self.addCleanup(p.stop)
        self.file_problem()
        self.file_unlooked()
        self.file_question()
        fs = self.server.findings_store
        fs.publish_state()
        self.server.publish_status()
        panel = self.server._findings_payload()["open"]
        self.assertEqual(panel, 3)
        mirror = json.loads(fs.STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(mirror["open"], panel)
        # The findings alone are still said, under their own name.
        self.assertEqual(mirror["findings_open"], 2)

        root = self.root / "config"

        class Config:
            def path(self, *parts):
                return str(root.joinpath(*parts))

        entity = self.sensor.BrainOpenFindingsSensor(None)
        entity.hass = types.SimpleNamespace(config=Config())
        parent = types.ModuleType("brain_numbers_cc")
        parent.__path__ = [str(INTEGRATION_DIR)]
        with patch.dict(sys.modules, {"brain_numbers_cc": parent,
                                      "brain_numbers_cc.findings":
                                          self.findings}):
            entity.update()
        self.assertEqual(entity._attr_native_value, panel)
