#!/usr/bin/env python3
"""Has anything LOOKED at a finding before somebody is shown it.

A house check reads one instant and cannot go and check anything, so the
Findings tab filled with rows that were true of a reading and wrong about
the house. Triage is the step between filing and surfacing: every
producer files through `triage.gate`, and the Resident's first look is
what judges the rows it marked. This file used to drive a triage drain
of its own; that drain was retired once the first look took its queue,
and what it held that still means something is in
`tests/test_resident_loop.py` and `tests/test_triage_retired.py`.

What is pinned here is what a held row IS — a row, not a deletion, so the
next pass dedupes against it; invisible to the five surfaces a live
finding reaches; clearable by the check that stopped reporting it; and
reversible by one press, because a verdict nothing can correct is a
verdict nobody should trust — and that every producer files through the
gate.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import triage  # noqa: E402


CHECK_ROW = {
    "text": "the hall sensor has not changed in 8 days",
    "detail": "last seen 3 Sep", "fix": "Re-pair it",
    "entity_id": "binary_sensor.hall", "severity": "warning",
    "source": "check:dev.frozen", "source_title": "Device checks",
}


def check_row(n: int = 0) -> dict:
    return {**CHECK_ROW, "text": f"{CHECK_ROW['text']} ({n})"}


# ---------------------------------------------------------------------------
# Who gets triaged, and the gate that says so
# ---------------------------------------------------------------------------

class TestWhoIsTriaged(unittest.TestCase):
    """Everyone. The gate is unconditional, and that is the whole of it."""

    def test_the_gate_marks_every_row_whoever_filed_it(self):
        """A check, an insight run, a study session, the fixer and a row
        with no source at all. The producer's name is context for the
        prompt now — it decides nothing."""
        rows = triage.gate([
            {"text": "a", "source": "check:dev.frozen"},
            {"text": "b", "source": "energy"},
            {"text": "c", "source": "study"},
            {"text": "d", "source": "fix"},
            {"text": "e"},
        ])
        self.assertEqual([r["status"] for r in rows], ["triaging"] * 5)

    def test_a_status_a_producer_claimed_for_itself_is_overwritten(self):
        """A line in the study inbox is JSON another process wrote, so it
        can name its own status and `coerce` honours one in
        `PRE_STATUSES`. The gate is what closes that door."""
        [row] = triage.gate([{"text": "a", "source": "study",
                              "status": "open"}])
        self.assertEqual(row["status"], "triaging")

    def test_the_gate_does_not_mutate_what_it_is_given(self):
        """The same list is handed to `refresh_details` and `clear_resolved`
        in the same pass — a gate that edited in place would be marking rows
        those two then read back."""
        original = {"text": "a", "source": "check:dev.frozen"}
        triage.gate([original])
        self.assertNotIn("status", original)


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "nowhere" / ".brain" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def file_check_rows(self, n: int = 1) -> list[dict]:
        return findings_store.add_many(
            triage.gate([check_row(i) for i in range(n)]))

    def hold(self, row: dict, reason: str = "it watches a cupboard") -> dict:
        moved = findings_store.record_triage(
            {row["ts"]: ("held", reason)}, "sess-1")
        return moved[0]


class TestTheStore(StoreCase):
    def test_a_check_row_is_filed_waiting_and_not_as_work(self):
        [row] = self.file_check_rows()
        self.assertEqual(row["status"], "triaging")
        self.assertEqual(findings_store.listing()["open"], 0)

    def test_a_held_row_is_a_row_and_not_a_deletion(self):
        """Which is what keeps the next pass deduping against it instead of
        filing the same problem again every six hours."""
        [row] = self.file_check_rows()
        self.hold(row)
        self.assertTrue(findings_store.is_known(row["text"]))
        self.assertEqual(findings_store.add_many([check_row(0)]), [])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_a_held_row_carries_what_was_checked_and_which_run(self):
        [row] = self.file_check_rows()
        held = self.hold(row, "its history has 40 changes today")
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["triage"]["verdict"], "held")
        self.assertEqual(held["triage"]["reason"],
                         "its history has 40 changes today")
        self.assertEqual(held["triage"]["run_id"], "sess-1")
        self.assertTrue(held["triage"]["at"])

    def test_a_verdict_arriving_late_does_not_drag_back_a_row_you_settled(self):
        """A run takes minutes. Anything that has left `triaging` in the
        meantime is a row a person or the fixer has already moved on from."""
        [row] = self.file_check_rows()
        findings_store.set_status(row["ts"], "fixing")
        moved = findings_store.record_triage({row["ts"]: ("held", "late")},
                                             "sess-1")
        self.assertEqual(moved, [])
        self.assertEqual(findings_store.get(row["ts"])["status"], "fixing")

    def test_an_unrecognised_verdict_moves_nothing(self):
        [row] = self.file_check_rows()
        self.assertEqual(
            findings_store.record_triage({row["ts"]: ("maybe", "x")}), [])
        self.assertEqual(findings_store.get(row["ts"])["status"], "triaging")

    def test_untriaged_surfaces_and_says_so_on_the_row(self):
        [row] = self.file_check_rows()
        [out] = findings_store.record_triage(
            {row["ts"]: ("untriaged", triage.RUN_FAILED)})
        self.assertEqual(out["status"], "open")
        self.assertEqual(out["triage"]["verdict"], "untriaged")
        self.assertEqual(out["triage"]["reason"], triage.RUN_FAILED)

    def test_stale_rows_are_the_ones_nothing_will_come_back_for(self):
        old = time.time() - triage.STALE_S - 60
        findings_store.add_many([{**check_row(0), "status": "triaging"}])
        entry = json.loads(findings_store.FINDINGS_FILE.read_text())
        entry["findings"][0]["ts"] = int(old)
        findings_store.FINDINGS_FILE.write_text(json.dumps(entry))
        [fresh_row] = findings_store.add_many(
            triage.gate([check_row(1)]))
        fresh = [fresh_row]
        self.assertEqual(
            findings_store.stale_triaging(time.time() - triage.STALE_S),
            [int(old)])
        self.assertNotIn(fresh[0]["ts"],
                         findings_store.stale_triaging(
                             time.time() - triage.STALE_S))

    def test_a_check_that_stops_reporting_takes_a_held_row_back(self):
        """"It went away" is the one claim that may delete a row, and it is
        as true of a held finding as of an open one — nobody ever answered
        it, so there is nothing of a person's to throw away."""
        [row] = self.file_check_rows()
        self.hold(row)
        gone = findings_store.clear_resolved({"check:dev.frozen"}, set())
        self.assertEqual([g["ts"] for g in gone], [row["ts"]])
        self.assertEqual(findings_store.list_all(), [])

    def test_a_check_that_could_not_look_clears_nothing(self):
        [row] = self.file_check_rows()
        self.hold(row)
        self.assertEqual(findings_store.clear_resolved(set(), set()), [])

    def test_elevating_puts_it_on_the_list_and_keeps_the_verdict(self):
        """What the run said is the only evidence it was wrong about this
        house — `unsettle`'s rule: the press stops the suppression and
        changes nothing else."""
        [row] = self.file_check_rows()
        self.hold(row, "it watches a cupboard")
        out = findings_store.elevate(row["ts"])
        self.assertEqual(out["status"], "open")
        self.assertEqual(out["triage"]["verdict"], "held")
        self.assertEqual(out["triage"]["reason"], "it watches a cupboard")
        self.assertTrue(out["triage"]["elevated_by_person"])
        self.assertEqual(findings_store.listing()["open"], 1)

    def test_only_a_held_row_can_be_elevated(self):
        [row] = self.file_check_rows()
        self.assertIsNone(findings_store.elevate(row["ts"]))
        findings_store.record_triage({row["ts"]: ("elevated", "real")})
        self.assertIsNone(findings_store.elevate(row["ts"]))
        self.assertIsNone(findings_store.elevate(999))

    def test_a_producer_may_only_file_into_the_two_pre_statuses(self):
        """A row arriving as `ignored` would be a producer settling a
        finding nobody was ever shown."""
        for status in ("ignored", "fixed", "held", "fixing", "nonsense"):
            findings_store.FINDINGS_FILE.unlink(missing_ok=True)
            [row] = findings_store.add_many(
                [{**check_row(0), "status": status}])
            self.assertEqual(row["status"], "open", status)


class TestAHeldRowReachesNobody(StoreCase):
    """The five surfaces a live finding reaches, each checked by filing the
    same row without triage and watching that surface light up."""

    def held_and_open(self) -> tuple[dict, dict]:
        rows = self.file_check_rows(2)
        return self.hold(rows[0]), findings_store.record_triage(
            {rows[1]["ts"]: ("elevated", "real")})[0]

    def test_the_badge_does_not_count_it(self):
        """One held row and one elevated one, and the badge counts one.
        Neither row is named here on purpose: what is being asserted is the
        NUMBER, and binding them would be two names nothing reads."""
        self.held_and_open()
        self.assertEqual(findings_store.open_count(), 1)
        self.assertEqual(findings_store.listing()["open"], 1)

    def test_the_live_filter_does_not_hold_it(self):
        _held, shown = self.held_and_open()
        live = [f["ts"] for f in findings_store.list_all("live")]
        self.assertEqual(live, [shown["ts"]])

    def test_the_analyst_is_not_told_not_to_report_it(self):
        """Deliberately: triage's verdict is about a rule's row, not a
        standing truth about the house. An analyst that independently finds
        the same problem is evidence triage was wrong, and a prompt block
        that had already forbidden it would throw that away."""
        held, shown = self.held_and_open()
        block = findings_store.prompt_block()
        self.assertIn(shown["text"], block)
        self.assertNotIn(held["text"], block)

    def test_the_shared_volume_mirror_does_not_carry_it(self):
        """Which is what keeps it out of `sensor.brain_open_findings` and
        out of `todo.brain` — those read the mirror and nothing else."""
        base = Path(self.tmp.name)
        findings_store.STATE_FILE = base / "config" / ".brain" / "state.json"
        (base / "config").mkdir(parents=True, exist_ok=True)
        held, shown = self.held_and_open()
        mirror = json.loads(findings_store.STATE_FILE.read_text())
        texts = [f["text"] for f in mirror["findings"]]
        self.assertIn(shown["text"], texts)
        self.assertNotIn(held["text"], texts)
        self.assertEqual(mirror["open"], 1)

    def test_it_is_still_on_the_payload_the_tab_reads(self):
        """Because the tab has a filter for it — the one place a held row is
        meant to be visible, and the one press that reverses it."""
        held, _shown = self.held_and_open()
        rows = findings_store.listing()["findings"]
        self.assertIn(held["ts"], [f["ts"] for f in rows])


class TestARowNothingLookedAtIsNotInvisible(StoreCase):
    """The walkthrough found a serious row — an add-on in an error state —
    `triaging` for 28 minutes with `triage: {}`, while the feed said
    "Nothing waiting on you", the sensor said 0 and Diagnostics said
    "Findings open 0". `STALE_S` surfaces it after an hour; until then it
    reached no surface at all. Past `SHOW_AFTER_S` it is shown and counted,
    still waiting for the look."""

    def _age(self, rows, seconds):
        data = json.loads(findings_store.FINDINGS_FILE.read_text())
        for entry in data["findings"]:
            entry["ts"] = int(entry["ts"] - seconds)
        findings_store.FINDINGS_FILE.write_text(json.dumps(data))

    def test_a_fresh_row_waits_unseen_as_it_always_did(self):
        self.file_check_rows(1)
        self.assertEqual(findings_store.open_count(), 0)
        self.assertEqual(findings_store.waiting_look_count(), 0)
        self.assertNotIn("waiting_look", findings_store.listing()["findings"][0])

    def test_past_the_bound_it_is_counted_everywhere(self):
        base = Path(self.tmp.name)
        findings_store.STATE_FILE = base / "config" / ".brain" / "state.json"
        (base / "config").mkdir(parents=True, exist_ok=True)
        self.file_check_rows(1)
        self._age(None, 28 * 60)
        findings_store.publish_state()
        self.assertEqual(findings_store.waiting_look_count(), 1)
        self.assertEqual(findings_store.open_count(), 1)
        listing = findings_store.listing()
        self.assertEqual(listing["open"], 1)
        [row] = listing["findings"]
        self.assertEqual(row["status"], "triaging")
        self.assertTrue(row["waiting_look"])
        mirror = json.loads(findings_store.STATE_FILE.read_text())
        self.assertEqual(mirror["open"], 1)
        self.assertEqual(mirror["waiting_look"], 1)
        # Counted, not listed: the watcher's events and Repairs wait for a
        # verdict, which is what `findings` there is read for.
        self.assertEqual(mirror["findings"], [])

    def test_the_badge_counts_it_beside_the_cases(self):
        import cases
        self.file_check_rows(1)
        self._age(None, 28 * 60)
        old = cases.list_cases
        cases.list_cases = lambda *a, **k: []
        try:
            self.assertEqual(cases.open_count(), 1)
        finally:
            cases.list_cases = old

    def test_once_looked_at_it_is_counted_as_what_the_look_said(self):
        [row] = self.file_check_rows(1)
        self._age(None, 28 * 60)
        self.hold({**row, "ts": row["ts"] - 28 * 60})
        self.assertEqual(findings_store.waiting_look_count(), 0)
        self.assertEqual(findings_store.open_count(), 0)


# ---------------------------------------------------------------------------
# The pass, over the real server
# ---------------------------------------------------------------------------

class PassCase(unittest.TestCase):
    """The panel driven for real over temporary stores, with only the CLI
    stubbed — and the stub records every prompt, so a test can say that
    nothing was spent."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import settings_store
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._olds = (
            findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
            findings_store.STATE_FILE, settings_store.SETTINGS_FILE,
            engine.run_analyst, engine.get_auth, engine.run_claude,
            self.server._house_prompt_block, self.server._read_shared_memory,
            self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
            self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
            findings_store.INBOX_DIR,
        )
        findings_store.INBOX_DIR = base / "findings-inbox"
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        self.server.INSIGHTS_DIR = base
        self.server.MEMORY_INBOX_DIR = base / "memory-inbox"
        self.server.CARD_TOKEN_FILE = base / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = base / "www" / "brain"
        # The startup auth re-check is a real `claude -p` turn, so a route
        # test that leaves it alone spends its whole two minutes waiting
        # for a CLI that is not there — `PanelCase`'s stub, one file over.
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "nowhere" / ".brain" / "s.json"
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True, "auto_enabled": True})
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.server._read_shared_memory = lambda: ""

        async def house(now=None):
            return ""
        self.server._house_prompt_block = house
        self.replies: list[dict] = []
        self.prompts: list[str] = []

        def run_analyst(prompt, system, *a, **k):
            self.prompts.append(prompt)
            return self.replies.pop(0) if self.replies else {
                "ok": False, "error": "no reply", "meta": {}}
        engine.run_analyst = run_analyst

    def tearDown(self):
        import engine
        import settings_store
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, settings_store.SETTINGS_FILE,
         engine.run_analyst, engine.get_auth, engine.run_claude,
         self.server._house_prompt_block, self.server._read_shared_memory,
         self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
         self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
         findings_store.INBOX_DIR) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def file(self, n: int = 1) -> list[dict]:
        return findings_store.add_many(
            triage.gate([check_row(i) for i in range(n)]))

    def statuses(self) -> list[str]:
        return [f["status"] for f in
                sorted(findings_store.list_all(), key=lambda f: f["ts"])]


class TestTheRoute(PassCase):
    def drive(self, body):
        async def run():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(run())

    def test_one_press_puts_a_held_row_back_on_the_list(self):
        [row] = self.file(1)
        findings_store.record_triage({row["ts"]: ("held", "a cupboard")},
                                     "sess-1")

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/elevate")
            self.assertEqual(res.status, 200)
            return await res.json()

        payload = self.drive(body)
        self.assertTrue(payload["elevated"])
        self.assertEqual(payload["open"], 1)
        [back] = payload["findings"]
        self.assertEqual(back["status"], "open")
        self.assertEqual(back["triage"]["reason"], "a cupboard")

    def test_a_row_that_is_not_held_is_a_409_rather_than_a_silent_yes(self):
        [row] = self.file(1)
        findings_store.record_triage({row["ts"]: ("elevated", "real")})

        async def body(client):
            return await client.post(f"/api/finding/{row['ts']}/elevate")

        self.assertEqual(self.drive(body).status, 409)


# ---------------------------------------------------------------------------
# Every producer, and the queue they share
# ---------------------------------------------------------------------------

class TestEveryProducerFilesThroughTheGate(PassCase):
    """The correction 1.57.0 makes. Five producers file findings and one of
    them is a tab fetch that must not spend a Claude run, so the claim is
    two halves: nothing reaches the list without being gated, and the
    gating does not make the tab expensive. What judges the gated rows is
    the Resident's first look; `tests/test_resident_loop.py` and
    `tests/test_triage_retired.py` hold that half."""

    def drive(self, body):
        async def run():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(run())

    def queue_study_finding(self, status: str | None = None):
        row = {"text": "the study session noticed the loft light is on",
               "source": "study", "source_title": "Study session",
               "severity": "info"}
        if status is not None:
            row["status"] = status
        (findings_store.INBOX_DIR / "1-study.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8")

    def test_a_study_session_arrives_waiting_to_be_looked_at(self):
        self.queue_study_finding()

        async def body(client):
            return await (await client.get("/api/findings")).json()

        payload = self.drive(body)
        [row] = payload["findings"]
        self.assertEqual(row["status"], "triaging")
        self.assertEqual(payload["open"], 0)

    def test_a_status_the_inbox_file_claimed_does_not_survive_the_gate(self):
        """The one producer whose rows are JSON another process wrote.
        `coerce` honours a status in `PRE_STATUSES`, so without the gate a
        study session could file straight onto the list."""
        self.queue_study_finding(status="open")

        async def body(client):
            return await (await client.get("/api/findings")).json()

        [row] = self.drive(body)["findings"]
        self.assertEqual(row["status"], "triaging")

    def test_the_tab_fetch_that_sweeps_does_not_spend_a_run(self):
        """A Claude run behind a tab fetch is the "refresh everything"
        control this panel deleted, with a nicer name. The Resident's own
        tick is what looks at it."""
        self.queue_study_finding()

        async def body(client):
            await (await client.get("/api/findings")).json()
            return await (await client.get("/api/findings")).json()

        self.drive(body)
        self.assertEqual(self.prompts, [])

    def test_no_call_site_in_the_panel_can_file_past_the_gate(self):
        """A behaviour test covers the producer a request can reach; this
        covers the four it cannot without a real house behind it. It is a
        claim a read CAN honestly make — that no `add_many` call anywhere
        in the panel is missing its gate — rather than a stand-in for
        driving one."""
        import ast
        tree = ast.parse((PANEL_DIR / "server.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "add_many"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "findings_store"]
        self.assertGreaterEqual(len(calls), 4)
        for call in calls:
            arg = call.args[0] if call.args else None
            gated = (isinstance(arg, ast.Call)
                     and isinstance(arg.func, ast.Attribute)
                     and arg.func.attr == "gate"
                     and isinstance(arg.func.value, ast.Name)
                     and arg.func.value.id == "triage")
            self.assertTrue(gated, f"line {call.lineno} files past the gate")

    def test_the_store_sweep_gates_only_when_it_is_handed_one(self):
        """`sweep_inbox` is the one `add_many` inside the store, so the
        policy is passed in rather than reached for — a store that knew it
        would be a second place it is decided."""
        self.queue_study_finding()
        [ungated] = findings_store.sweep_inbox()
        self.assertEqual(ungated["status"], "open")


# ---------------------------------------------------------------------------
# One vocabulary
# ---------------------------------------------------------------------------

class TestOneVocabulary(unittest.TestCase):
    """The words live in `triage.py`; three other files spell them, and a
    spelling that drifts is a verdict nothing acts on."""

    @classmethod
    def setUpClass(cls):
        cls.js = (PANEL_DIR / "app.js").read_text()
        cls.store = (PANEL_DIR / "findings_store.py").read_text()

    def test_the_store_knows_both_statuses(self):
        for status in ("triaging", "held"):
            self.assertIn(status, findings_store.STATUSES, status)

    def test_neither_is_work_waiting_on_anybody(self):
        for status in ("triaging", "held"):
            self.assertNotIn(status, findings_store.LIVE_STATUSES, status)
            self.assertNotIn(status, findings_store.UNSETTLED_STATUSES, status)

    def test_both_are_clearable_by_the_check_that_filed_them(self):
        for status in ("triaging", "held"):
            self.assertIn(status, findings_store.CLEARABLE, status)

    def test_a_producer_may_file_only_into_the_pre_statuses(self):
        self.assertEqual(set(findings_store.PRE_STATUSES),
                         {"open", "triaging"})

    def test_the_panel_filters_on_the_status_the_store_writes(self):
        self.assertIn('{ id: "held", label: "Looked at", '
                      'match: (f) => f.status === "held" }', self.js)

    def test_the_panel_presses_the_route_the_server_serves(self):
        self.assertIn("api/finding/${f.ts}/elevate", self.js)
        server_src = (PANEL_DIR / "server.py").read_text()
        self.assertIn('"/api/finding/{ts}/elevate"', server_src)

    def test_the_panel_names_the_third_verdict_out_loud(self):
        """A card nothing looked at must not read as a card something did."""
        self.assertIn('t.verdict === "untriaged"', self.js)

    def test_a_triage_run_is_claimed_like_every_other_background_caller(self):
        import run_sources
        self.assertIn("triage", run_sources.SOURCES)
        self.assertIn("triage", run_sources.ENGINE_SOURCES)
        shell = (BASE_DIR / "brain" / "scripts"
                 / "brain-run-source.sh").read_text()
        self.assertIn("triage", shell)


if __name__ == "__main__":
    unittest.main()
