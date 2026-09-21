#!/usr/bin/env python3
"""Has anything LOOKED at a finding before somebody is shown it.

A house check reads one instant and cannot go and check anything, so the
Findings tab filled with rows that were true of a reading and wrong about
the house. Triage is the step between filing and surfacing: one Claude
run per drain, over the rows nothing has looked at, answering `elevated`
or `held` about each.

**Every producer files through it**, which is the correction 1.57.0
makes: the first cut triaged house checks alone, and the runs it spared
had read the house to write a card or study a topic — never to decide
whether what they noticed in passing belongs on a list of decisions.

The load-bearing rule is the one about what happens when that run cannot
be made or cannot be read, so most of this file is that rule from seven
directions: **triage may only hold a finding back by SAYING so, about
that finding, in a reply that parsed.** Everything else surfaces. A
triage that could not look must never be able to hide a problem, which is
`clear_resolved`'s rule moved one step earlier in the lifecycle.

The rest pins what a held row IS — a row, not a deletion, so the next
pass dedupes against it; invisible to the five surfaces a live finding
reaches; clearable by the check that stopped reporting it; and reversible
by one press, because a verdict nothing can correct is a verdict nobody
should trust.
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
# The reply reader
# ---------------------------------------------------------------------------

class TestReadingTheVerdicts(unittest.TestCase):
    def test_the_two_words_are_read(self):
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "elevated", "reason": "the battery is real"},
            {"id": 2, "verdict": "held", "reason": "it watches a cupboard"},
        ]}, 2)
        self.assertEqual(out[1], ("elevated", "the battery is real", ""))
        self.assertEqual(out[2], ("held", "it watches a cupboard", ""))

    def test_what_to_do_is_read_off_an_elevated_row_and_never_a_held_one(self):
        """The run has looked, so what it says to do is about THIS device
        in THIS house; a held row is shown to nobody and carries none."""
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "elevated", "reason": "real",
             "fix": "Power-cycle the Tuya hub in the garage; the other "
                    "three valves on it are answering."},
            {"id": 2, "verdict": "held", "reason": "a cupboard",
             "fix": "nothing, and this must not be kept"},
        ]}, 2)
        self.assertIn("Tuya hub", out[1][2])
        self.assertEqual(out[2][2], "")

    def test_a_written_fix_is_capped_at_the_store_s_own_cap(self):
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "elevated", "reason": "x", "fix": "y" * 5000}]}, 1)
        self.assertEqual(len(out[1][2]), triage.MAX_FIX)
        self.assertEqual(triage.MAX_FIX, findings_store.MAX_FIX)

    def test_the_contract_asks_for_the_fix_and_shows_the_generic_one(self):
        """The prompt has to ask for what the reader takes, and the run
        cannot improve on advice it has not been shown."""
        self.assertIn('"fix"', triage.SYSTEM)
        text = triage.frame([check_row(1)])
        self.assertIn("Re-pair it", text)
        self.assertIn("brAIn can make this change itself", text)

    def test_an_invented_verdict_is_dropped_rather_than_coerced(self):
        """An invented verdict reads exactly like a real one, and the safe
        reading of one this cannot recognise is the one that shows the card
        — which is what an absent entry produces."""
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "probably fine", "reason": "eh"},
            {"id": 2, "verdict": "IGNORE", "reason": "eh"},
        ]}, 2)
        self.assertEqual(out, {})

    def test_an_id_outside_the_batch_names_nothing(self):
        out = triage.parse({"verdicts": [
            {"id": 0, "verdict": "held", "reason": "x"},
            {"id": 7, "verdict": "held", "reason": "x"},
            {"id": "two", "verdict": "held", "reason": "x"},
        ]}, 3)
        self.assertEqual(out, {})

    def test_the_first_answer_about_a_row_is_the_one_kept(self):
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "held", "reason": "first"},
            {"id": 1, "verdict": "elevated", "reason": "second"},
        ]}, 1)
        self.assertEqual(out[1][0], "held")

    def test_a_reply_that_is_not_the_shape_asked_for_reads_as_nothing(self):
        for obj in (None, "", "not json", {"ok": True}, {"verdicts": "no"},
                    {"verdicts": [None, 3, "x"]}):
            self.assertEqual(triage.parse(obj, 3), {}, repr(obj))

    def test_a_reason_is_capped(self):
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "held", "reason": "x" * 5000}]}, 1)
        self.assertLessEqual(len(out[1][1]), triage.MAX_REASON)

    def test_the_prompt_numbers_the_rows(self):
        """A model retyping a finding's text back can name the wrong one; a
        number cannot be nearly right."""
        text = triage.frame([check_row(1), check_row(2)])
        self.assertIn("1. ", text)
        self.assertIn("2. ", text)
        self.assertIn("binary_sensor.hall", text)

    def test_the_contract_names_the_two_words_it_will_accept(self):
        """The reader drops anything else, so the prompt has to ask for
        exactly what the reader takes. The first cut of this said "HOLD
        when…" and showed only `"elevated"` in its example, so the likeliest
        correct reply was `"hold"` — a word the reader dropped, which
        surfaces, which is safe and is the feature quietly doing nothing.
        Hence the spelling stated outright, and both words in the sample."""
        for word in ('"elevated"', '"held"'):
            self.assertIn(word, triage.SYSTEM)

    def test_the_imperative_the_prompt_uses_is_read_as_the_same_word(self):
        """Not the coercion `parse` refuses: "hold" is the prompt's own verb
        in another tense, where "probably fine" is a verdict nobody asked
        for."""
        out = triage.parse({"verdicts": [
            {"id": 1, "verdict": "Hold", "reason": "a cupboard"},
            {"id": 2, "verdict": "ELEVATE", "reason": "real"},
        ]}, 2)
        self.assertEqual(out[1][0], "held")
        self.assertEqual(out[2][0], "elevated")


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


# ---------------------------------------------------------------------------
# The pass, over the real server
# ---------------------------------------------------------------------------

class PassCase(unittest.TestCase):
    """`_triage_findings` driven for real, with only the CLI stubbed."""

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

    def reply(self, verdicts: list[dict], run_id: str = "sess-1"):
        self.replies.append({
            "ok": True, "error": "",
            "text": json.dumps({"verdicts": verdicts}),
            "meta": {"session_id": run_id}})

    def run_pass(self, now: float | None = None):
        """The drain reads the queue, so nothing is handed to it."""
        return asyncio.run(self.server._triage_findings(
            now if now is not None else time.time()))

    def statuses(self) -> list[str]:
        return [f["status"] for f in
                sorted(findings_store.list_all(), key=lambda f: f["ts"])]


class TestSilenceSurfaces(PassCase):
    """The rule the whole step stands on: triage may only hold a finding
    back by SAYING so, about that finding, in a reply that parsed.

    Each of these is a way of not saying so, and each ends with the card on
    the list. A triage that could not look must never be able to hide a
    problem — "I could not tell" and "it is not real" are different claims
    and only the second may take a row off a screen.
    """

    def assert_all_shown(self, created, expect_reason=None):
        surfaced = self.run_pass()
        self.assertEqual(sorted(f["ts"] for f in surfaced),
                         sorted(f["ts"] for f in created))
        self.assertEqual(set(self.statuses()), {"open"})
        for row in findings_store.list_all():
            self.assertEqual(row["triage"]["verdict"], "untriaged")
            if expect_reason is not None:
                self.assertEqual(row["triage"]["reason"], expect_reason)

    def test_no_credential(self):
        import engine
        engine.get_auth = lambda: None
        self.assert_all_shown(self.file(2), triage.NO_CREDENTIAL)

    def test_automatic_runs_paused(self):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": False})
        self.assert_all_shown(self.file(2), triage.PAUSED)

    def test_the_usage_budget_is_spent(self):
        import usage_store
        old = usage_store.budget_state
        usage_store.budget_state = lambda *a, **k: {"blocked": True}
        try:
            self.assert_all_shown(self.file(2), triage.NO_BUDGET)
        finally:
            usage_store.budget_state = old

    def test_a_day_that_has_spent_its_runs_waits_rather_than_surfacing(self):
        """`MAX_PER_DAY` is `MAX_BATCH` one clock up: past it the queue
        waits for tomorrow, spends nothing, and shows nothing unjudged —
        `STALE_S` is what shows a queue that stopped draining."""
        created = self.file(2)
        self.server.TRIAGE_STATE["day"] = time.strftime("%Y-%m-%d")
        self.server.TRIAGE_STATE["runs"] = triage.MAX_PER_DAY
        self.reply([{"id": 1, "verdict": "held", "reason": "x"},
                    {"id": 2, "verdict": "held", "reason": "x"}])
        surfaced = self.run_pass()
        self.assertEqual(surfaced, [])
        self.assertEqual(self.prompts, [], "a capped day spent a run")
        self.assertEqual(set(self.statuses()), {"triaging"})
        self.assertEqual(len(findings_store.awaiting_triage()), len(created))
        # A new local day resets the count and the drain runs again.
        self.server.TRIAGE_STATE["day"] = "1970-01-01"
        self.run_pass()
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.server.TRIAGE_STATE["runs"], 1)

    def test_every_run_counts_against_the_day(self):
        self.server.TRIAGE_STATE["day"] = ""
        self.file(1)
        self.reply([{"id": 1, "verdict": "elevated", "reason": "x"}])
        self.run_pass()
        self.assertEqual(self.server.TRIAGE_STATE["runs"], 1)
        self.assertEqual(self.server.TRIAGE_STATE["day"],
                         time.strftime("%Y-%m-%d"))

    def test_the_run_failed(self):
        self.replies.append({"ok": False, "error": "timeout", "meta": {}})
        self.assert_all_shown(self.file(2), triage.RUN_FAILED)

    def test_the_run_raised(self):
        import engine

        def boom(*a, **k):
            raise RuntimeError("the CLI is not there")
        engine.run_analyst = boom
        self.assert_all_shown(self.file(2), triage.RUN_FAILED)

    def test_the_reply_was_not_the_shape_asked_for(self):
        self.replies.append({"ok": True, "error": "", "meta": {},
                             "text": "Looks fine to me, honestly."})
        self.assert_all_shown(self.file(2), triage.NOT_MENTIONED)

    def test_a_row_the_reply_did_not_mention(self):
        created = self.file(2)
        self.reply([{"id": 1, "verdict": "held", "reason": "a cupboard"}])
        surfaced = self.run_pass()
        self.assertEqual([f["ts"] for f in surfaced], [created[1]["ts"]])
        rows = {f["ts"]: f for f in findings_store.list_all()}
        self.assertEqual(rows[created[0]["ts"]]["status"], "held")
        self.assertEqual(rows[created[1]["ts"]]["status"], "open")
        self.assertEqual(rows[created[1]["ts"]]["triage"]["reason"],
                         triage.NOT_MENTIONED)

    def test_a_row_left_unjudged_because_a_drain_stopped_coming_back(self):
        """The one that makes the surplus WAITING honest rather than a
        second kind of silence: the queue is bounded by the clock, not by
        a drain being polite."""
        self.file(1)
        entry = json.loads(findings_store.FINDINGS_FILE.read_text())
        entry["findings"][0]["ts"] = int(time.time() - triage.STALE_S - 60)
        findings_store.FINDINGS_FILE.write_text(json.dumps(entry))
        surfaced = self.run_pass()
        self.assertEqual(len(surfaced), 1)
        self.assertEqual(findings_store.list_all()[0]["triage"]["reason"],
                         triage.UNJUDGED)

    def test_a_row_left_unjudged_by_an_earlier_pass(self):
        """A panel that died between filing and judging. The next pass is
        the thing that comes back, because nothing else will."""
        self.file(1)
        entry = json.loads(findings_store.FINDINGS_FILE.read_text())
        entry["findings"][0]["ts"] = int(time.time() - triage.STALE_S - 60)
        findings_store.FINDINGS_FILE.write_text(json.dumps(entry))
        surfaced = self.run_pass()
        self.assertEqual(len(surfaced), 1)
        [row] = findings_store.list_all()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["triage"]["reason"], triage.UNJUDGED)

    def test_a_pass_with_nothing_new_spawns_nothing(self):
        """The decision about what a run costs is taken before a process
        exists — a pass that filed nothing is the ordinary case."""
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(self.prompts, [])

    def test_a_row_from_a_producer_that_read_the_house_is_judged_too(self):
        """The correction. An insight run's finding goes through the same
        gate and the same run — asserted end to end, because the gate and
        the drain are two places it could go wrong."""
        [row] = findings_store.add_many(triage.gate(
            [{**check_row(0), "source": "energy",
              "source_title": "Energy"}]))
        self.assertEqual(row["status"], "triaging")
        self.reply([{"id": 1, "verdict": "held", "reason": "a cupboard"}])
        self.assertEqual(self.run_pass(), [])
        self.assertIn("Energy", self.prompts[0])
        self.assertEqual(findings_store.get(row["ts"])["status"], "held")


class TestHoldingSomethingBack(PassCase):
    def test_a_held_row_says_what_was_checked_and_names_the_run(self):
        created = self.file(2)
        self.reply([
            {"id": 1, "verdict": "held",
             "reason": "its history has 40 changes today — it is a button"},
            {"id": 2, "verdict": "elevated", "reason": "that battery is real"},
        ], run_id="sess-abc")
        surfaced = self.run_pass()
        self.assertEqual([f["ts"] for f in surfaced], [created[1]["ts"]])
        rows = {f["ts"]: f for f in findings_store.list_all()}
        held = rows[created[0]["ts"]]
        self.assertEqual(held["status"], "held")
        self.assertIn("40 changes", held["triage"]["reason"])
        self.assertEqual(held["triage"]["run_id"], "sess-abc")
        shown = rows[created[1]["ts"]]
        self.assertEqual(shown["status"], "open")
        self.assertEqual(shown["triage"]["verdict"], "elevated")

    def test_what_to_do_comes_from_the_run_that_looked(self):
        """The card's "What you'd need to do" was the rule's generic
        sentence — "check its power and its connection, then reload its
        integration" — on every row of its kind, which a person reading it
        called useless. The run that elevated the row has looked at the
        device, its integration and its area, so what it says to do is
        what the card carries; and a re-report on the next pass, which
        refreshes the detail, must not put the generic sentence back."""
        created = self.file(2)
        self.reply([
            {"id": 1, "verdict": "elevated", "reason": "it really is stuck",
             "fix": "Re-pair the hall sensor from the ZHA page; the other "
                    "four Aqara sensors on that coordinator are reporting."},
            {"id": 2, "verdict": "elevated", "reason": "real"},
        ])
        self.run_pass()
        rows = {f["ts"]: f for f in findings_store.list_all()}
        written = rows[created[0]["ts"]]
        self.assertIn("ZHA page", written["fix"])
        self.assertTrue(written["triage"]["wrote_fix"])
        # No fix written: the card is the card it always was.
        kept = rows[created[1]["ts"]]
        self.assertEqual(kept["fix"], CHECK_ROW["fix"])
        self.assertFalse(kept["triage"]["wrote_fix"])
        # The check reports the same row again with a moved detail.
        again = {**check_row(0), "detail": "last seen 4 Sep"}
        findings_store.refresh_details([again])
        after = {f["ts"]: f for f in findings_store.list_all()}[created[0]["ts"]]
        self.assertEqual(after["detail"], "last seen 4 Sep")
        self.assertIn("ZHA page", after["fix"])

    def test_a_held_row_keeps_the_generic_fix_it_was_filed_with(self):
        """Nothing writes advice onto a row nobody is shown."""
        created = self.file(1)
        self.reply([{"id": 1, "verdict": "held", "reason": "a cupboard",
                     "fix": "must not land"}])
        self.run_pass()
        [row] = findings_store.list_all()
        self.assertEqual(row["ts"], created[0]["ts"])
        self.assertEqual(row["fix"], CHECK_ROW["fix"])
        self.assertFalse(row["triage"]["wrote_fix"])

    def test_what_the_homeowner_has_already_said_is_in_the_prompt(self):
        """"That contact is on a cupboard nobody opens" is exactly the kind
        of thing somebody has said once, and a triage that cannot read it
        re-litigates every correction they have ever made."""
        self.server._read_shared_memory = \
            lambda: "The pantry contact is on a cupboard nobody opens."
        self.file(1)
        self.reply([{"id": 1, "verdict": "held", "reason": "they said so"}])
        self.run_pass()
        self.assertIn("cupboard nobody opens", self.prompts[0])


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
    gating does not make the tab expensive."""

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
        control this panel deleted, with a nicer name. The drain on the
        scheduler's own minute is what looks at it."""
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


class TestTheDrainReadsTheQueue(PassCase):
    """Not what a caller just filed. Four of the five producers do not run
    a checks pass, so a drain that could only judge its own caller's rows
    would leave theirs to the stale sweep an hour later."""

    def test_a_row_another_producer_filed_is_judged_by_whoever_drains(self):
        queued = findings_store.add_many(triage.gate(
            [{**check_row(0), "source": "study",
              "source_title": "Study session"}]))
        self.reply([{"id": 1, "verdict": "held", "reason": "a cupboard"}])
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(findings_store.get(queued[0]["ts"])["status"],
                         "held")

    def test_the_surplus_waits_rather_than_surfacing_unjudged(self):
        """Surfacing it would spend the cap on exactly the rows this
        exists to catch, and on the busiest houses first."""
        created = self.file(triage.MAX_BATCH + 3)
        self.reply([{"id": i, "verdict": "held", "reason": "a cupboard"}
                    for i in range(1, triage.MAX_BATCH + 1)])
        self.assertEqual(self.run_pass(), [])
        rows = {f["ts"]: f["status"] for f in findings_store.list_all()}
        self.assertEqual(
            [rows[f["ts"]] for f in created[triage.MAX_BATCH:]],
            ["triaging"] * 3)
        self.assertEqual(len([v for v in rows.values() if v == "held"]),
                         triage.MAX_BATCH)

    def test_the_next_drain_takes_the_oldest_first(self):
        """Which is what stops a row losing the same lottery twice."""
        created = self.file(triage.MAX_BATCH + 3)
        self.reply([{"id": i, "verdict": "held", "reason": "a cupboard"}
                    for i in range(1, triage.MAX_BATCH + 1)])
        self.run_pass()
        self.reply([{"id": i, "verdict": "elevated", "reason": "real"}
                    for i in (1, 2, 3)])
        surfaced = self.run_pass()
        self.assertEqual(sorted(f["ts"] for f in surfaced),
                         sorted(f["ts"] for f in created[triage.MAX_BATCH:]))
        self.assertEqual(findings_store.list_all("triaging"), [])

    def test_a_gate_that_answered_before_any_run_covers_the_whole_queue(self):
        """`MAX_BATCH` is what one run may READ. Rationing an excuse no run
        was spawned for would leave the rest waiting on a drain that gives
        the identical answer a minute later."""
        import engine
        engine.get_auth = lambda: None
        created = self.file(triage.MAX_BATCH + 3)
        surfaced = self.run_pass()
        self.assertEqual(len(surfaced), len(created))
        self.assertEqual(set(self.statuses()), {"open"})
        for row in findings_store.list_all():
            self.assertEqual(row["triage"]["reason"], triage.NO_CREDENTIAL)

    def test_two_drains_at_once_spend_one_run(self):
        """`create_task` and `await` both only schedule, so a guard reading
        a state its own call has not set yet is no guard — the flag is set
        before the first await. The loser files nothing: its rows are in
        the queue the winner is draining."""
        created = self.file(2)
        self.reply([{"id": i, "verdict": "elevated", "reason": "real"}
                    for i in (1, 2)])

        async def both():
            return await asyncio.gather(
                self.server._triage_findings(time.time()),
                self.server._triage_findings(time.time()))

        first, second = asyncio.run(both())
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(sorted(f["ts"] for f in first + second),
                         sorted(f["ts"] for f in created))
        self.assertEqual(findings_store.list_all("triaging"), [])


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
