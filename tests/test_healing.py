"""Overnight self-healing: every refusal, then the three things it does.

This is the only code in brAIn that changes the house with nobody
watching, so the refusals are tested harder than the actions and each
test names the mutation it catches:

  off by default            default it on -> a house heals without anybody
                            having asked it to
  the window                drop the quiet-hours test -> a Z-Wave ping and
                            an add-on start at four in the afternoon
  no window at all          fall back to an hour -> brAIn acts at a time
                            nobody set, on a house it has not measured
  one per finding a night   drop the night key -> a restart at 3am starts
                            the same add-on twice
  the cap                   drop MAX_PER_NIGHT -> nine broken things get
                            nine unattended calls
  protected entity          drop the protection ask -> a ping reaches the
                            device a lock lives on
  unresolvable target       treat "I could not tell" as "nothing is
                            protected" -> the bypass the list exists for
  a touched finding         heal a `fixing` row -> brAIn acts on a
                            conversation somebody is already having
  an errored add-on         start one in `error` -> a crash loop asked the
                            same question at 3am
  a failed call             retry it -> the same failure all night

The Supervisor and Core calls run against a real aiohttp server, the way
`tests/test_proposal_accept.py` drives the accept path: a stub of
`perform` would only prove the stub.
"""
from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import healing  # noqa: E402
from checks import system as sys_checks  # noqa: E402

NOW = 1_800_000_000.0
UTC = dt.timezone.utc


def finding(**over) -> dict:
    row = {"ts": int(NOW * 1000), "text": sys_checks.ADDON_STOPPED_TEXT,
           "source": "check:sys.addon_down", "status": "open",
           "severity": "warning", "snoozed_until": 0}
    row.update(over)
    return row


def house(**over) -> dict:
    """A house with one stopped add-on, one dead node, one failed entry."""
    snap = {
        "now": NOW,
        "available": {k: True for k in ("supervisor", "states", "registry",
                                        "config_entries")},
        "supervisor": {"addons": [
            {"slug": "core_mosquitto", "name": "Mosquitto broker",
             "installed": True, "state": "stopped", "boot": "auto"},
            {"slug": "core_ssh", "name": "Terminal & SSH",
             "installed": True, "state": "stopped", "boot": "manual"},
            {"slug": "a0d7b954_ide", "name": "Studio Code Server",
             "installed": True, "state": "error", "boot": "auto"},
            {"slug": "core_samba", "name": "Samba",
             "installed": True, "state": "started", "boot": "auto"},
        ]},
        "states": {
            "sensor.front_lock_node_status": {
                "state": "dead", "attributes": {}},
            "sensor.hall_sensor_node_status": {
                "state": "alive", "attributes": {}},
        },
        "entities": [
            {"entity_id": "sensor.front_lock_node_status", "device_id": "d1",
             "platform": "zwave_js", "config_entry_id": "zw1"},
            {"entity_id": "lock.front_door", "device_id": "d1",
             "platform": "zwave_js", "config_entry_id": "zw1"},
            {"entity_id": "sensor.hall_sensor_node_status", "device_id": "d2",
             "platform": "zwave_js", "config_entry_id": "zw1"},
            {"entity_id": "light.kitchen", "device_id": "d3",
             "platform": "hue", "config_entry_id": "hue1"},
        ],
        "devices": [{"id": "d1", "name": "Front door lock"},
                    {"id": "d2", "name": "Hall sensor"},
                    {"id": "d3", "name": "Kitchen bulb"}],
        "areas": [],
        "config_entries": [
            {"entry_id": "hue1", "domain": "hue", "title": "Hue bridge",
             "state": "setup_error", "source": "user",
             "reason": "Cannot connect"},
            {"entry_id": "zw1", "domain": "zwave_js", "title": "Z-Wave",
             "state": "loaded", "source": "user"},
        ],
    }
    snap.update(over)
    return snap


def zwave_finding() -> dict:
    return finding(ts=int(NOW * 1000) + 1,
                   text="Z-Wave nodes are marked dead by the controller",
                   source="check:dev.zwave_dead")


def entry_finding() -> dict:
    return finding(ts=int(NOW * 1000) + 2,
                   text=sys_checks.ENTRY_FAILED_TEXT,
                   source="check:sys.entry_failed")


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

class TestTheWindow(unittest.TestCase):
    """When it may run, and — the case nothing else can report — when it
    has no idea when nobody is looking."""

    def at(self, hour, minute=0):
        return dt.datetime(2026, 9, 4, hour, minute, tzinfo=UTC)

    def test_inside_quiet_hours_is_the_window(self):
        ok, why = healing.window(self.at(2), 22, 7, None)
        self.assertTrue(ok, why)

    def test_outside_quiet_hours_it_does_not_run(self):
        # The mutation: drop this test and a Z-Wave ping lands at four in
        # the afternoon, which is the whole difference between overnight
        # self-healing and self-healing.
        ok, why = healing.window(self.at(16), 22, 7, None)
        self.assertFalse(ok)
        self.assertIn("quiet hours", why)

    def test_the_window_crosses_midnight(self):
        for hour in (22, 23, 0, 3, 6):
            self.assertTrue(healing.window(self.at(hour), 22, 7, None)[0],
                            f"{hour}:00 should be inside 22-07")
        for hour in (7, 12, 21):
            self.assertFalse(healing.window(self.at(hour), 22, 7, None)[0],
                             f"{hour}:00 should be outside 22-07")

    def test_quiet_hours_set_the_same_are_no_quiet_hours(self):
        # `notify_router` reads start == end as unset rather than a
        # 24-hour silence, and this has to agree with it or the two
        # disagree about what somebody typed.
        ok, why = healing.window(self.at(2), 7, 7, None)
        self.assertFalse(ok)
        self.assertIn("settle time", why)

    def test_with_no_quiet_hours_it_is_an_hour_after_the_house_settles(self):
        settles = 23 * 60          # 23:00
        self.assertTrue(healing.window(self.at(0, 10), None, None, settles)[0])
        self.assertFalse(healing.window(self.at(23, 10), None, None, settles)[0])

    def test_with_neither_it_does_not_run_and_says_why(self):
        # The mutation: fall back to a fixed hour. That is brAIn acting
        # unattended at a time nobody set, on a house whose quiet hours it
        # has never measured — which is exactly the guess this refuses.
        ok, why = healing.window(self.at(3), None, None, None)
        self.assertFalse(ok)
        self.assertIn("has not been measured", why)

    def test_a_night_spans_midnight(self):
        late = healing.night_key(dt.datetime(2026, 9, 4, 23, 40, tzinfo=UTC))
        early = healing.night_key(dt.datetime(2026, 9, 5, 3, 10, tzinfo=UTC))
        self.assertEqual(late, early)
        # And the next evening is a different night.
        self.assertNotEqual(
            late, healing.night_key(dt.datetime(2026, 9, 5, 23, 40, tzinfo=UTC)))


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

class PlanCase(unittest.TestCase):

    def plan(self, findings, snap=None, patterns=(), done=(), cap=None):
        return healing.plan(
            findings, snap if snap is not None else house(), list(patterns),
            set(done), healing.MAX_PER_NIGHT if cap is None else cap, NOW)

    def reasons(self, result) -> str:
        return " | ".join(s["reason"] for s in result["skips"])


class TestTheThreeRemedies(PlanCase):

    def test_a_stopped_boot_auto_addon_is_started(self):
        out = self.plan([finding()])
        self.assertEqual(len(out["attempts"]), 1, out)
        a = out["attempts"][0]
        self.assertEqual(a["remedy"], "addon.start")
        self.assertEqual(a["target"], "core_mosquitto")
        self.assertEqual(a["path"], "/addons/core_mosquitto/start")

    def test_a_manual_boot_addon_is_never_started(self):
        # `boot: manual` is somebody's decision. The check already stands
        # down for it and so must the healer, or the two disagree about
        # what "meant to be running" is.
        snap = house()
        snap["supervisor"]["addons"] = [
            a for a in snap["supervisor"]["addons"]
            if a["slug"] != "core_mosquitto"]
        out = self.plan([finding()], snap)
        self.assertEqual(out["attempts"], [])
        targets = [a["target"] for a in out["attempts"]]
        self.assertNotIn("core_ssh", targets)

    def test_an_errored_addon_is_never_started(self):
        # The mutation: start one in `error`. The Supervisor could not
        # start it or it exited and kept exiting — asking again at 3am is
        # asking for the same answer, all night, every night.
        snap = house()
        snap["supervisor"]["addons"] = [
            a for a in snap["supervisor"]["addons"] if a["state"] == "error"]
        out = self.plan([finding(text=sys_checks.ADDON_ERROR_TEXT)], snap)
        self.assertEqual(out["attempts"], [])

    def test_the_error_row_heals_nothing_even_with_a_stopped_addon(self):
        # `addon_down` files two rows and only one is startable. Matching
        # on the source alone would let the error row start an unrelated
        # add-on it is not about.
        out = self.plan([finding(text=sys_checks.ADDON_ERROR_TEXT)])
        self.assertEqual(out["attempts"], [])

    def test_a_dead_zwave_node_is_pinged(self):
        out = self.plan([zwave_finding()])
        self.assertEqual(len(out["attempts"]), 1, out)
        a = out["attempts"][0]
        self.assertEqual(a["remedy"], "zwave.ping")
        self.assertEqual(a["domain"], "zwave_js")
        self.assertEqual(a["service"], "ping")
        self.assertEqual(a["data"], {"entity_id": "sensor.front_lock_node_status"})

    def test_a_failed_entry_is_reloaded(self):
        out = self.plan([entry_finding()])
        self.assertEqual(len(out["attempts"]), 1, out)
        a = out["attempts"][0]
        self.assertEqual(a["remedy"], "entry.reload")
        self.assertEqual((a["domain"], a["service"]),
                         ("homeassistant", "reload_config_entry"))
        self.assertEqual(a["data"], {"entry_id": "hue1"})

    def test_a_loaded_entry_is_never_reloaded(self):
        snap = house()
        snap["config_entries"] = [
            {"entry_id": "zw1", "domain": "zwave_js", "state": "loaded"}]
        self.assertEqual(self.plan([entry_finding()], snap)["attempts"], [])

    def test_every_remedy_declares_what_it_had_to_read(self):
        # A remedy added without a `NEEDS` row would act off a snapshot
        # nobody checked, which is the failure the test above pins one
        # case of. Asserted over the table so a fourth remedy cannot skip
        # the gate by being written after it.
        self.assertEqual(set(healing.REMEDIES), set(healing.NEEDS))
        for source, keys in healing.NEEDS.items():
            self.assertTrue(keys, source)

    def test_the_playbook_is_closed(self):
        # Anything not in REMEDIES heals nothing, and every other
        # producer in the add-on is in that set.
        for source in ("check:dev.battery_low", "check:climate.freeze",
                       "insight", "check:reg.no_area", ""):
            out = self.plan([finding(source=source)])
            self.assertEqual(out["attempts"], [], source)
            self.assertEqual(out["skips"], [], f"{source} should not be listed")


class TestTheRefusals(PlanCase):

    def test_only_open_findings_are_healed(self):
        # The mutation: heal a `fixing` row. Somebody pressed Fix it on
        # Tuesday and is mid-conversation with brAIn about that row.
        for status in ("fixing", "fixed", "failed", "needs_you", "ignored"):
            out = self.plan([finding(status=status)])
            self.assertEqual(out["attempts"], [], status)
            self.assertIn("already answered", self.reasons(out))

    def test_a_snoozed_finding_is_not_healed(self):
        out = self.plan([finding(snoozed_until=int(NOW + 3600))])
        self.assertEqual(out["attempts"], [])
        self.assertIn("snoozed", self.reasons(out))

    def test_one_attempt_per_finding_per_night(self):
        # The mutation: drop the night key. A restart at three in the
        # morning finds the same open finding and starts the add-on again.
        first = self.plan([finding()])
        self.assertEqual(len(first["attempts"]), 1)
        again = self.plan([finding()], done={finding()["ts"]})
        self.assertEqual(again["attempts"], [])
        self.assertIn("already tried tonight", self.reasons(again))

    def test_the_cap_holds(self):
        # The mutation: drop MAX_PER_NIGHT. Nine broken things at once is
        # not a house to fix unattended, it is a house to look at.
        rows = [finding(), zwave_finding(), entry_finding()]
        self.assertEqual(len(self.plan(rows, cap=2)["attempts"]), 2)
        capped = self.plan(rows, cap=1)
        self.assertEqual(len(capped["attempts"]), 1)
        self.assertIn("limit of 1", self.reasons(capped))

    def test_the_cap_takes_the_same_rows_every_night(self):
        rows = [entry_finding(), finding(), zwave_finding()]
        for _ in range(3):
            picked = [a["ts"] for a in self.plan(rows, cap=2)["attempts"]]
            self.assertEqual(picked, sorted(picked))
            self.assertEqual(picked, [finding()["ts"], zwave_finding()["ts"]])

    def test_a_protected_entity_on_the_device_stops_the_ping(self):
        # The mutation: check only the entity being pinged. A ping reaches
        # the BOX, and the box here is the front door lock.
        out = self.plan([zwave_finding()], patterns=["lock.front_door"])
        self.assertEqual(out["attempts"], [])
        self.assertIn("lock.front_door", self.reasons(out))
        self.assertIn("protected", self.reasons(out))

    def test_a_protected_domain_wildcard_stops_it_too(self):
        out = self.plan([zwave_finding()], patterns=["lock.*"])
        self.assertEqual(out["attempts"], [])

    def test_a_protected_entity_elsewhere_does_not_stop_it(self):
        # The refusal has to be about this device, or `protected_entities`
        # switches self-healing off wholesale and nobody can tell why.
        out = self.plan([zwave_finding()], patterns=["light.kitchen"])
        self.assertEqual(len(out["attempts"]), 1, self.reasons(out))

    def test_a_protected_entity_on_the_config_entry_stops_the_reload(self):
        out = self.plan([entry_finding()], patterns=["light.kitchen"])
        self.assertEqual(out["attempts"], [])
        self.assertIn("light.kitchen", self.reasons(out))

    def test_an_unresolvable_target_is_skipped_not_guessed(self):
        # The mutation: read "I could not tell which entities this touches"
        # as "nothing is protected". That is the bypass the list exists to
        # prevent — an older Core carries no config_entry_id at all.
        snap = house()
        snap["entities"] = [{k: v for k, v in e.items()
                             if k != "config_entry_id"}
                            for e in snap["entities"]]
        out = self.plan([entry_finding()], snap, patterns=["light.kitchen"])
        self.assertEqual(out["attempts"], [])
        self.assertIn("could not work out", self.reasons(out))
        # And with nothing protected there is nothing to resolve against,
        # so it proceeds: the refusal is about the list, not the field.
        self.assertEqual(len(self.plan([entry_finding()], snap)["attempts"]), 1)

    def test_a_star_pattern_stands_everything_down(self):
        # An add-on is not an entity, so no narrower pattern can reach it
        # — but `*` is not a claim about entities. It is somebody saying
        # brAIn may not act on this house.
        for row in (finding(), zwave_finding(), entry_finding()):
            out = self.plan([row], patterns=["*"])
            self.assertEqual(out["attempts"], [], row["source"])
            self.assertIn("everything", self.reasons(out))

    def test_a_snapshot_that_could_not_be_read_is_not_a_house_that_healed(self):
        # The mutation: act on whatever the snapshot happens to hold. A
        # Supervisor outage would then read as every add-on having come
        # back — which is `clear_resolved`'s rule ("I could not look" is
        # not "it went away") one layer over, in the half that acts.
        for source, key, row in (
                ("check:sys.addon_down", "supervisor", finding()),
                ("check:dev.zwave_dead", "states", zwave_finding()),
                ("check:sys.entry_failed", "config_entries", entry_finding())):
            snap = house()
            snap["available"][key] = False
            out = self.plan([row], snap)
            self.assertEqual(out["attempts"], [], source)
            self.assertIn("could not read", self.reasons(out))

    def test_a_row_with_nothing_left_to_act_on_is_skipped(self):
        snap = house()
        snap["supervisor"]["addons"] = []
        out = self.plan([finding()], snap)
        self.assertEqual(out["attempts"], [])
        self.assertIn("matches this row any more", self.reasons(out))

    def test_all_three_together_fit_under_the_cap(self):
        out = self.plan([finding(), zwave_finding(), entry_finding()])
        self.assertEqual(len(out["attempts"]), 3)
        self.assertEqual({a["remedy"] for a in out["attempts"]},
                         {"addon.start", "zwave.ping", "entry.reload"})


# ---------------------------------------------------------------------------
# The store, across a restart
# ---------------------------------------------------------------------------

class TestTheStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "healing.json"

    def test_a_restart_reads_back_what_tonight_already_tried(self):
        night = "2026-09-04"
        healing.save({"night": night,
                      "attempts": [{"ts": 11, "ok": True}]}, self.path)
        back = healing.load(self.path)
        self.assertEqual(healing.attempted_tonight(back, night), {11})

    def test_last_nights_attempts_do_not_count_for_tonight(self):
        healing.save({"night": "2026-09-03",
                      "attempts": [{"ts": 11, "ok": True}]}, self.path)
        back = healing.load(self.path)
        self.assertEqual(healing.attempted_tonight(back, "2026-09-04"), set())

    def test_an_unreadable_store_reads_as_no_pass_yet(self):
        # Every way of failing reads as "nothing has run": the cost is one
        # duplicate call to a remediation that is idempotent, where a
        # stamp wrongly read as done would switch the feature off in
        # silence.
        self.path.write_text("{ not json")
        self.assertEqual(healing.load(self.path)["attempts"], [])
        self.assertEqual(healing.load(Path(self.tmp.name) / "gone.json")
                         ["night"], "")


# ---------------------------------------------------------------------------
# The calls, against a real server
# ---------------------------------------------------------------------------

class PerformCase(unittest.IsolatedAsyncioTestCase):
    """A real aiohttp server standing in for the Supervisor and for Core."""

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        self.calls: list[tuple[str, dict]] = []
        self.addon_status = 200

        async def addon_start(request):
            self.calls.append((request.path, {}))
            if self.addon_status != 200:
                return web.json_response({"message": "no"},
                                         status=self.addon_status)
            return web.json_response({"result": "ok"})

        async def service(request):
            self.calls.append((request.path, await request.json()))
            return web.json_response([])

        app = web.Application()
        app.router.add_post("/addons/{slug}/start", addon_start)
        app.router.add_post("/services/{domain}/{service}", service)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        base = str(self.server.make_url("")).rstrip("/")

        self._sup = healing.SUPERVISOR_API
        healing.SUPERVISOR_API = base
        self.addCleanup(self._restore_sup)

        import ha_data
        self.ha_data = ha_data
        self._core = ha_data.CORE_API
        ha_data.CORE_API = base
        self.addCleanup(self._restore_core)

    def _restore_sup(self):
        healing.SUPERVISOR_API = self._sup

    def _restore_core(self):
        self.ha_data.CORE_API = self._core

    async def one(self, findings, snap=None):
        import aiohttp

        plan = healing.plan(findings, snap or house(), [], set(),
                            healing.MAX_PER_NIGHT, NOW)
        out = []
        async with aiohttp.ClientSession() as session:
            for attempt in plan["attempts"]:
                out.append(await healing.perform(session, attempt))
        return plan, out


class TestThePerformedCalls(PerformCase):

    async def test_starting_an_addon_hits_the_supervisor(self):
        _plan, results = await self.one([finding()])
        self.assertEqual(results, [(True, "")])
        self.assertEqual(self.calls[0][0], "/addons/core_mosquitto/start")

    async def test_pinging_a_node_calls_zwave_js_ping_on_the_entity(self):
        _plan, results = await self.one([zwave_finding()])
        self.assertEqual(results, [(True, "")])
        path, body = self.calls[0]
        self.assertEqual(path, "/services/zwave_js/ping")
        self.assertEqual(body, {"entity_id": "sensor.front_lock_node_status"})

    async def test_reloading_an_entry_calls_the_documented_service(self):
        _plan, results = await self.one([entry_finding()])
        self.assertEqual(results, [(True, "")])
        path, body = self.calls[0]
        self.assertEqual(path, "/services/homeassistant/reload_config_entry")
        self.assertEqual(body, {"entry_id": "hue1"})

    async def test_a_refused_start_comes_back_as_a_sentence(self):
        self.addon_status = 400
        _plan, results = await self.one([finding()])
        ok, why = results[0]
        self.assertFalse(ok)
        self.assertIn("400", why)

    async def test_perform_never_raises(self):
        # A call that cannot be made at all — a kind nothing implements —
        # is an answer, not a traceback taking the loop down.
        import aiohttp

        async with aiohttp.ClientSession() as session:
            ok, why = await healing.perform(session, {"kind": "telepathy"})
        self.assertFalse(ok)
        self.assertIn("telepathy", why)


# ---------------------------------------------------------------------------
# The pass, end to end, through the panel
# ---------------------------------------------------------------------------

class TestThePassThroughTheServer(PerformCase):
    """`run_healing` against the real panel module: off by default, one
    write per attempt, and a failure recorded exactly once."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        store = Path(self.root.name) / "healing.json"
        self._store = healing.STORE
        healing.STORE = store
        self.addCleanup(lambda: setattr(healing, "STORE", self._store))
        os.environ["BRAIN_JOURNAL_FILE"] = str(
            Path(self.root.name) / "journal.jsonl")
        self.addCleanup(lambda: os.environ.pop("BRAIN_JOURNAL_FILE", None))

        self.server = importlib.import_module("server")
        import journal
        journal.JOURNAL_FILE = os.environ["BRAIN_JOURNAL_FILE"]

        self.rows = [finding()]
        self.snapshot = house()

        async def collect(now=None):
            return self.snapshot

        self._old = (self.server.checks.snapshot.collect,
                     self.server.findings_store.list_all,
                     self.server.automation_writer.protected_patterns)
        self.server.checks.snapshot.collect = collect
        self.server.findings_store.list_all = lambda status=None: list(self.rows)
        self.server.automation_writer.protected_patterns = lambda *a, **k: []
        self.addCleanup(self._restore)
        self.server.HEAL_STATE["last"] = None

    def _restore(self):
        (self.server.checks.snapshot.collect,
         self.server.findings_store.list_all,
         self.server.automation_writer.protected_patterns) = self._old

    def journal_rows(self):
        path = os.environ["BRAIN_JOURNAL_FILE"]
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh.read().splitlines() if line]

    async def test_a_pass_acts_records_and_journals(self):
        state = await self.server.run_healing("test")
        self.assertEqual(len(state["attempts"]), 1, state)
        self.assertTrue(state["attempts"][0]["ok"])
        self.assertEqual(self.calls[0][0], "/addons/core_mosquitto/start")
        outcomes = [r["outcome"] for r in self.journal_rows()
                    if r["source"] == "healing"]
        self.assertEqual(outcomes, [healing.OUTCOME_OK])
        # And it is on disk before the pass returns, so a restart sees it.
        self.assertEqual(
            healing.attempted_tonight(healing.load(), state["night"]),
            {finding()["ts"]})

    async def test_a_second_pass_the_same_night_does_nothing(self):
        # The mutation: drop the night key from the loop's guard. A
        # restart at 3am starts the same add-on twice.
        await self.server.run_healing("test")
        self.calls.clear()
        again = await self.server.run_healing("test")
        self.assertEqual(self.calls, [])
        self.assertEqual(len(again["attempts"]), 1)   # last night's, carried

    async def test_a_failed_call_is_recorded_once_and_not_retried(self):
        self.addon_status = 500
        state = await self.server.run_healing("test")
        self.assertFalse(state["attempts"][0]["ok"])
        self.assertIn("500", state["attempts"][0]["error"])
        self.assertEqual(len(self.calls), 1)
        self.calls.clear()
        await self.server.run_healing("test")
        self.assertEqual(self.calls, [], "a failed call was retried tonight")
        # Once, and the second pass records why it did not try again
        # rather than saying nothing about a night it looked at.
        outcomes = [r["outcome"] for r in self.journal_rows()
                    if r["source"] == "healing"]
        self.assertEqual(outcomes.count(healing.OUTCOME_FAIL), 1)
        self.assertEqual(outcomes[-1], healing.OUTCOME_SKIP)

    async def test_a_skip_is_journalled_with_its_reason(self):
        self.server.automation_writer.protected_patterns = lambda *a, **k: ["*"]
        state = await self.server.run_healing("test")
        self.assertEqual(state["attempts"], [])
        self.assertEqual(self.calls, [])
        skipped = [r for r in self.journal_rows()
                   if r["outcome"] == healing.OUTCOME_SKIP]
        self.assertTrue(skipped)
        self.assertIn("protected", skipped[0]["error"])

    def test_it_is_off_by_default(self):
        # The mutation: default it on. A house starts healing itself
        # because it was updated, which nobody asked for.
        import yaml
        config = yaml.safe_load(
            (BASE_DIR / "brain" / "config.yaml").read_text())
        self.assertIs(config["options"]["self_healing"], False)
        self.assertEqual(config["schema"]["self_healing"], "bool?")

    def test_the_loop_does_nothing_while_the_option_is_off(self):
        os.environ.pop("BRAIN_SELF_HEALING", None)
        self.server.addon_options._options = {"self_healing": False}
        try:
            self.assertFalse(self.server._healing_enabled())
            self.server.addon_options._options = {"self_healing": True}
            self.assertTrue(self.server._healing_enabled())
        finally:
            self.server.addon_options._options = None

    def test_the_diagnostics_carry_no_excuse_beside_a_working_pass(self):
        # A "reason" next to a healer that is on and inside its window is
        # noise — the same rule `budget_state` follows about an excuse
        # beside a number that is fine.
        self.server.addon_options._options = {"self_healing": True}
        old = self.server._healing_window
        self.server._healing_window = lambda now: (True, "inside quiet hours")
        try:
            self.assertEqual(self.server._healing_diagnostics()["reason"], "")
            self.assertTrue(self.server._healing_diagnostics()["in_window"])
            self.server._healing_window = lambda now: (False, "no quiet hours")
            diag = self.server._healing_diagnostics()
            self.assertEqual(diag["reason"], "no quiet hours")
            self.assertFalse(diag["in_window"])
        finally:
            self.server._healing_window = old
            self.server.addon_options._options = None

    def test_the_diagnostics_say_why_it_is_quiet(self):
        self.server.addon_options._options = {"self_healing": False}
        try:
            diag = self.server._healing_diagnostics()
        finally:
            self.server.addon_options._options = None
        self.assertFalse(diag["enabled"])
        self.assertEqual(sorted(diag["remedies"]), sorted(healing.REMEDIES))
        self.assertEqual(diag["max_per_night"], healing.MAX_PER_NIGHT)


# ---------------------------------------------------------------------------
# What the morning says
# ---------------------------------------------------------------------------

class TestTheMorningLine(unittest.TestCase):

    def store(self, ok=True, ts=11):
        return {"night": "2026-09-04", "attempts": [
            {"ts": ts, "ok": ok, "at": NOW, "error": "" if ok else "no",
             "sentence": "started the Mosquitto broker add-on"}]}

    def test_a_heal_that_stuck_says_so(self):
        lines = healing.brief_lines(self.store(), open_ids=set(), tz=UTC)
        self.assertEqual(len(lines), 1)
        self.assertIn("started the Mosquitto broker add-on", lines[0])
        self.assertIn("working now", lines[0])

    def test_a_heal_that_did_not_stick_says_that_instead(self):
        # The finding is still open, which is the ONLY verification there
        # is: a 200 from the Supervisor is a request being accepted.
        lines = healing.brief_lines(self.store(), open_ids={11}, tz=UTC)
        self.assertIn("has not cleared yet", lines[0])

    def test_a_failed_call_reads_as_a_failure(self):
        lines = healing.brief_lines(self.store(ok=False), set(), UTC)
        self.assertIn("could not", lines[0])

    def test_the_brief_carries_it_as_a_reason(self):
        import brief
        state = brief.state_from([], {}, {}, NOW,
                                 ["brAIn started the broker at 03:10"])
        self.assertIn("brAIn started the broker at 03:10",
                      brief.worth_saying(state))
        # And no healing is not a reason to send one.
        self.assertEqual(brief.worth_saying(brief.state_from([], {}, {}, NOW)),
                         [])


if __name__ == "__main__":
    unittest.main()
