#!/usr/bin/env python3
"""Tests for Cases — one object over four stores, driven against all four.

Nothing here fakes a store. A finding, a hypothesis, a proposal and a
to-do item are filed through the real writers into real files, and the
list that comes back is asserted to be one list with four kinds and four
id prefixes — because the whole claim this module makes is that it is a
*read model* and not a fifth store, and a fixture that stood in for the
four would be a test of the fixture.

The endings are driven with recording hooks, and what is asserted is that
**exactly one hook fires per verb per kind**: a case that settled two
things, or none, is the failure `_end_finding` exists to prevent arriving
by a new door. `not_now` fires none of them, which is the whole of what it
means.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import cases  # noqa: E402
import findings_store  # noqa: E402
import hypotheses  # noqa: E402
import proposals  # noqa: E402
import todo_store  # noqa: E402


class Recorder:
    """Hooks that write down what they were asked to do and change nothing.

    The endings themselves are the server's — a second implementation of
    one here would be the same press teaching brAIn two different things
    depending on which screen it was given on.
    """

    def __init__(self):
        self.calls: list[tuple] = []

    def _make(self, name):
        def fn(*args):
            self.calls.append((name,) + args)
            return {"hook": name}
        return fn

    def hooks(self, **missing) -> cases.Hooks:
        made = {field: self._make(field) for field in cases.Hooks._fields}
        made.update(missing)
        return cases.Hooks(**made)


class StoresCase(unittest.TestCase):
    """Four real stores in a temporary directory, and the sidecar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = {
            "findings": (findings_store.FINDINGS_FILE,
                         findings_store.INBOX_DIR,
                         findings_store.SETTLED_FILE,
                         findings_store.STATE_FILE),
            "hypotheses": hypotheses.HYPOTHESES_FILE,
            "proposals": (proposals.STORE, proposals.SETTLED_FILE,
                          proposals.SHARED),
            "todo": (todo_store.TODO_FILE, todo_store.STATE_FILE),
            "snooze": cases.SNOOZE_FILE,
        }
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        # Pointed under a "config" that does not exist, so the mirrors are
        # skipped exactly as they are on a dev checkout. The one test that
        # is about a mirror makes the directory itself.
        findings_store.STATE_FILE = root / "config" / ".brain" / "state.json"
        hypotheses.HYPOTHESES_FILE = root / "hypotheses.jsonl"
        proposals.STORE = root / "proposals.json"
        proposals.SETTLED_FILE = root / "proposals-settled.json"
        proposals.SHARED = root / "config" / ".brain" / "proposals.json"
        todo_store.TODO_FILE = root / "todo.json"
        todo_store.STATE_FILE = root / "config" / ".brain" / "todo.json"
        cases.SNOOZE_FILE = root / "cases-snooze.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old["findings"]
        hypotheses.HYPOTHESES_FILE = self._old["hypotheses"]
        (proposals.STORE, proposals.SETTLED_FILE,
         proposals.SHARED) = self._old["proposals"]
        (todo_store.TODO_FILE, todo_store.STATE_FILE) = self._old["todo"]
        cases.SNOOZE_FILE = self._old["snooze"]
        self.tmp.cleanup()

    # -- one of each -----------------------------------------------------
    def file_problem(self, **fields) -> dict:
        [row] = findings_store.add_many([{
            "text": "The hall sensor has not reported since Tuesday",
            "detail": "last seen 3 Sep", "fix": "Re-pair it",
            "severity": "serious", "entity_id": "sensor.hall_motion",
            "source": "check:dev.unavailable",
            "source_title": "Devices that stopped answering", **fields}])
        return row

    def file_question(self) -> dict:
        return hypotheses.propose(
            "The garage fridge is meant to run all night", "fridge")

    def file_opportunity(self) -> dict:
        return proposals.add({
            "kind": "routine", "source": "routines",
            "title": "Turn the porch light off at 23:10",
            "why": "You do this by hand on nine evenings out of ten.",
            "config": {"alias": None, "trigger": [{"platform": "time"}]}})

    def file_chore(self) -> dict:
        return todo_store.add(
            "Replace the hall sensor battery", detail="CR2032",
            severity="warning", origin="finding", source="check:dev.battery",
            source_title="Batteries", finding_key="hall battery")

    def one_of_each(self) -> dict:
        return {"problem": self.file_problem(), "question": self.file_question(),
                "opportunity": self.file_opportunity(),
                "chore": self.file_chore()}


# ---------------------------------------------------------------------------
# The read model
# ---------------------------------------------------------------------------

class TestOneListOverFourStores(StoresCase):
    def test_four_stores_become_one_list_of_four_kinds(self):
        self.one_of_each()
        listed = cases.list_cases(kinds=cases.KINDS)
        self.assertEqual(len(listed), 4)
        self.assertEqual({c["kind"] for c in listed},
                         {"problem", "question", "opportunity", "chore"})
        self.assertEqual({c["id"].split(":")[0] for c in listed},
                         set(cases.PREFIXES.values()))
        for case in listed:
            self.assertIn(case["origin"]["store"], cases.STORES)
            self.assertEqual(case["id"],
                             cases.case_id(case["origin"]["store"],
                                           case["origin"]["key"]))

    def test_nothing_is_written_to_disk_by_reading(self):
        """A read model, not a fifth store: the one file this module owns
        is the snooze sidecar, and reading does not create it."""
        self.one_of_each()
        cases.list_cases()
        cases.open_count()
        self.assertFalse(cases.SNOOZE_FILE.exists())

    def test_a_fixed_finding_is_a_change_and_not_a_problem(self):
        """brAIn altered somebody's house; that is news to read, which is
        a different object from a problem however the row was labelled."""
        row = self.file_problem()
        findings_store.set_status(row["ts"], "fixed", "re-paired it")
        [case] = [c for c in cases.list_cases() if c["id"].startswith("f:")]
        self.assertEqual(case["kind"], "change")

    def test_a_run_in_flight_is_acting_and_a_held_row_is_watching(self):
        row = self.file_problem()
        findings_store.set_status(row["ts"], "fixing")
        self.assertEqual(cases.get(f"f:{row['ts']}")["status"], "acting")
        findings_store.set_status(row["ts"], "held")
        self.assertEqual(cases.get(f"f:{row['ts']}")["status"], "watching")

    def test_the_badge_counts_decisions_and_nothing_else(self):
        row = self.file_problem()
        self.file_question()
        self.assertEqual(cases.open_count(), 2)
        findings_store.set_status(row["ts"], "planning")
        self.assertEqual(cases.open_count(), 1)

    def test_a_chore_is_on_the_todo_tab_and_never_on_the_feed(self):
        """Accepting a finding is the press that takes it OFF the feed and
        off its badge: the To-do tab carries the work and its own count.
        Rendered on the feed, an accepted battery came back as *Broken ·
        Device check · battery is low* over *Done · Remove* — a finding
        with no way onto the to-do list, which is what was reported."""
        self.file_problem()
        item = self.file_chore()
        self.assertEqual([c["kind"] for c in cases.list_cases()], ["problem"])
        self.assertEqual(cases.open_count(), 1)
        self.assertNotIn("chore", cases.FEED_KINDS)
        # Still a case: the To-do tab's endings ride the same hooks, and a
        # caller that wants it asks for it by name.
        self.assertEqual(cases.get(f"t:{item['id']}")["kind"], "chore")
        self.assertIn("chore", {c["kind"] for c in
                                cases.list_cases(kinds=cases.KINDS)})

    def test_a_finished_chore_is_a_record_rather_than_a_decision(self):
        item = self.file_chore()
        todo_store.complete(item["id"])
        self.assertEqual(cases.list_cases(kinds=cases.KINDS), [])
        [done] = cases.list_cases("done", kinds=cases.KINDS)
        self.assertEqual(done["kind"], "chore")
        self.assertEqual(done["ended"]["verb"], "do")

    def test_an_answered_hypothesis_leaves_the_feed(self):
        guess = self.file_question()
        hypotheses.confirm(guess["ts"])
        self.assertEqual(cases.list_cases(kinds=["question"]), [])

    def test_kinds_filters_and_the_sort_puts_the_stakes_first(self):
        self.file_problem()
        self.file_question()
        listed = cases.list_cases()
        self.assertEqual(listed[0]["kind"], "problem")
        self.assertEqual([c["kind"] for c in
                          cases.list_cases(kinds=["question"])], ["question"])

    def test_severity_becomes_stakes_through_one_table(self):
        for severity, stakes in (("critical", "high"), ("serious", "high"),
                                 ("warning", "medium"), ("info", "low")):
            row = self.file_problem(text=f"A {severity} thing",
                                    severity=severity)
            self.assertEqual(cases.get(f"f:{row['ts']}")["stakes"], stakes)

    def test_get_reads_one_store_and_refuses_anything_that_is_not_an_id(self):
        made = self.one_of_each()
        self.assertEqual(cases.get(f"f:{made['problem']['ts']}")["kind"],
                         "problem")
        self.assertEqual(cases.get(f"t:{made['chore']['id']}")["kind"], "chore")
        for bad in ("", "x:1", "f:", "12345", None, "f:not-a-number"):
            self.assertIsNone(cases.get(bad))
        self.assertIsNone(cases.get("f:999"))

    def test_the_id_prefix_is_what_stops_two_id_spaces_colliding(self):
        """A finding's id is a second and a to-do item's a millisecond,
        so a bare integer is read as whichever store is asked first."""
        self.assertEqual(cases.split_id("t:17"), ("todo", 17))
        self.assertEqual(cases.split_id("h:9"), ("hypotheses", 9))
        self.assertIsNone(cases.split_id("17"))
        with self.assertRaises(ValueError):
            cases.case_id("nowhere", 1)

    def test_the_kinds_are_the_stores_own_vocabulary(self):
        """One table, in the module that decides what may be written to
        disk — a word the reader admitted and the store refused would be a
        case the feed renders and nothing can file."""
        self.assertIs(cases.KINDS, findings_store.CASE_KINDS)


# ---------------------------------------------------------------------------
# The three endings
# ---------------------------------------------------------------------------

class TestExactlyOneHookPerEnding(StoresCase):
    def press(self, case_id: str, verb: str, note: str = "",
              **missing) -> tuple:
        rec = Recorder()
        out = cases.end(case_id, verb, note, hooks=rec.hooks(**missing))
        return out, rec.calls

    def test_every_kind_and_verb_fires_exactly_one_hook(self):
        expected = {
            ("problem", "do"): "finding_todo",
            ("problem", "wrong"): "end_finding",
            ("change", "do"): "end_finding",
            ("change", "wrong"): "end_finding",
            ("opportunity", "do"): "proposal",
            ("opportunity", "wrong"): "proposal",
            ("question", "do"): "hypothesis",
            ("question", "wrong"): "hypothesis",
            ("chore", "do"): "todo_done",
            ("chore", "wrong"): "todo_drop",
        }
        for (kind, verb), hook in expected.items():
            with self.subTest(kind=kind, verb=verb):
                made = self.one_of_each()
                if kind == "change":
                    findings_store.set_status(made["problem"]["ts"], "fixed")
                ident = {
                    "problem": f"f:{made['problem']['ts']}",
                    "change": f"f:{made['problem']['ts']}",
                    "opportunity": f"p:{made['opportunity']['ts']}",
                    "question": f"h:{made['question']['ts']}",
                    "chore": f"t:{made['chore']['id']}",
                }[kind]
                out, calls = self.press(ident, verb, "because I said so")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], hook)
                self.assertEqual(out["kind"], kind)
                self.assertEqual(out["verb"], verb)
                self.assertEqual(out["result"], {"hook": hook})
                self.tearDown()
                self.setUp()

    def test_the_store_gets_its_own_word_for_the_ending(self):
        made = self.one_of_each()
        _, calls = self.press(f"p:{made['opportunity']['ts']}", "do")
        self.assertEqual(calls[0][:3],
                         ("proposal", made["opportunity"]["ts"], "accept"))
        _, calls = self.press(f"h:{made['question']['ts']}", "wrong", "no")
        self.assertEqual(calls[0], ("hypothesis", made["question"]["ts"],
                                    "reject", "no"))

    def test_do_on_a_problem_is_the_to_do_list_and_not_a_claim_it_is_done(self):
        """Pressing yes is agreeing the report is real; it is not a report
        that the battery is in. The memory line is written when the chore
        is ticked, which is a chore case's own Do it."""
        row = self.file_problem()
        _, calls = self.press(f"f:{row['ts']}", "do")
        self.assertEqual(calls[0], ("finding_todo", row["ts"]))

    def test_a_hook_the_server_did_not_pass_is_a_refusal(self):
        """A press that appeared to work and changed nothing is the one
        outcome with no way back."""
        row = self.file_problem()
        out, calls = self.press(f"f:{row['ts']}", "do", finding_todo=None)
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_a_verb_that_is_not_one_of_the_three_does_nothing(self):
        row = self.file_problem()
        for verb in ("done", "ack", "ignore", "", None, "DO"):
            out, calls = self.press(f"f:{row['ts']}", verb)
            self.assertIsNone(out)
            self.assertEqual(calls, [])

    def test_a_case_that_is_not_there_does_nothing(self):
        out, calls = self.press("f:123", "do")
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_nothing_may_be_pressed_while_a_run_is_changing_the_house(self):
        """An ending would delete the row the fixer is still writing to,
        and settle a question nobody has the answer to yet — which is why
        the Findings tab renders no buttons in `fixing` either."""
        row = self.file_problem()
        findings_store.set_status(row["ts"], "fixing")
        for verb in cases.VERBS:
            out, calls = self.press(f"f:{row['ts']}", verb)
            self.assertIsNone(out, verb)
            self.assertEqual(calls, [])
        self.assertEqual([r["verb"] for r in
                          cases.overflow(cases.get(f"f:{row['ts']}"))],
                         ["discuss"])

    def test_a_finished_chore_has_been_answered_once_already(self):
        item = self.file_chore()
        todo_store.complete(item["id"])
        out, calls = self.press(f"t:{item['id']}", "wrong")
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_a_trialling_proposal_may_still_be_answered(self):
        """`watching` is one word over two stores and it means different
        things: a held finding nobody has been shown, and a proposal
        brAIn is watching for a week. Both are answerable."""
        made = self.file_opportunity()
        proposals.start_trial(made["ts"])
        self.assertEqual(cases.get(f"p:{made['ts']}")["status"], "watching")
        out, calls = self.press(f"p:{made['ts']}", "do")
        self.assertEqual(calls[0][:3], ("proposal", made["ts"], "accept"))
        self.assertIsNotNone(out)

    def test_overflow_refuses_anything_that_is_not_a_case(self):
        self.assertEqual(cases.overflow(None), [])
        self.assertEqual(cases.overflow("f:1"), [])

    def test_a_note_longer_than_the_store_takes_is_cut_at_the_store(self):
        row = self.file_problem()
        _, calls = self.press(f"f:{row['ts']}", "wrong", "x" * 5000)
        self.assertEqual(len(calls[0][3]), findings_store.MAX_NOTE)


class TestNotNowEndsNothing(StoresCase):
    def press(self, case_id: str, now: float) -> tuple:
        rec = Recorder()
        out = cases.end(case_id, "not_now", hooks=rec.hooks(), now=now)
        return out, rec.calls

    def test_not_now_fires_no_hook_at_all(self):
        made = self.one_of_each()
        for ident in (f"f:{made['problem']['ts']}",
                      f"p:{made['opportunity']['ts']}",
                      f"h:{made['question']['ts']}",
                      f"t:{made['chore']['id']}"):
            out, calls = self.press(ident, now=1_760_000_000)
            self.assertEqual(calls, [], ident)
            self.assertGreater(out["snoozed_until"], 1_760_000_000)

    def test_a_problem_uses_the_field_the_store_already_carries(self):
        """One answer to "when does this come back", in the place every
        other reader of a finding already looks."""
        row = self.file_problem(severity="warning")
        now = 1_760_000_000.0
        out, _ = self.press(f"f:{row['ts']}", now)
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["snoozed_until"], out["snoozed_until"])
        self.assertEqual(stored["snoozed_until"],
                         int(now + cases.SNOOZE_BY_STAKES["medium"]))
        self.assertFalse(cases.SNOOZE_FILE.exists())

    def test_how_long_it_buys_is_keyed_on_how_much_it_matters(self):
        now = 1_760_000_000.0
        for severity, stakes in (("critical", "high"), ("warning", "medium"),
                                 ("info", "low")):
            row = self.file_problem(text=f"A {severity} thing",
                                    severity=severity)
            out, _ = self.press(f"f:{row['ts']}", now)
            self.assertEqual(out["snoozed_until"],
                             int(now + cases.SNOOZE_BY_STAKES[stakes]))

    def test_the_three_stores_with_nowhere_to_put_one_use_the_sidecar(self):
        made = self.one_of_each()
        now = 1_760_000_000.0
        for ident in (f"p:{made['opportunity']['ts']}",
                      f"h:{made['question']['ts']}",
                      f"t:{made['chore']['id']}"):
            self.press(ident, now)
        stored = json.loads(cases.SNOOZE_FILE.read_text())["snoozed"]
        self.assertEqual(len(stored), 3)

    def test_a_question_goes_quiet_until_the_queue_retires_it(self):
        guess = self.file_question()
        now = float(guess["ts"])
        out, _ = self.press(f"h:{guess['ts']}", now)
        self.assertEqual(out["snoozed_until"],
                         guess["ts"] + hypotheses.TTL_DAYS * 86400)

    def test_a_press_always_buys_at_least_a_day_of_quiet(self):
        """A question already past its expiry would otherwise come
        straight back, which reads as the button doing nothing."""
        guess = self.file_question()
        later = guess["ts"] + hypotheses.TTL_DAYS * 86400 + 5
        out, _ = self.press(f"h:{guess['ts']}", later)
        self.assertEqual(out["snoozed_until"],
                         int(later + cases.MIN_SNOOZE_S))

    def test_a_snoozed_case_is_hidden_until_its_time_and_never_dropped(self):
        made = self.one_of_each()
        now = 1_760_000_000.0
        self.press(f"p:{made['opportunity']['ts']}", now)
        listed = cases.list_cases(now=now + 60)
        self.assertNotIn("opportunity", {c["kind"] for c in listed})
        self.assertEqual([c["kind"] for c in
                          cases.list_cases("snoozed", now=now + 60)],
                         ["opportunity"])
        # ...and the row underneath was never touched.
        self.assertEqual(proposals.get(made["opportunity"]["ts"])["status"],
                         "proposed")
        back = cases.list_cases(now=now + cases.SNOOZE_BY_STAKES["low"] + 60)
        self.assertIn("opportunity", {c["kind"] for c in back})

    def test_a_snoozed_case_still_answers_when_its_id_is_pressed(self):
        made = self.one_of_each()
        self.press(f"p:{made['opportunity']['ts']}", 1_760_000_000.0)
        self.assertIsNotNone(cases.get(f"p:{made['opportunity']['ts']}"))

    def test_the_sidecar_drops_what_has_come_round(self):
        made = self.one_of_each()
        self.press(f"p:{made['opportunity']['ts']}", 1_000.0)
        self.press(f"t:{made['chore']['id']}", 1_000_000_000.0)
        stored = json.loads(cases.SNOOZE_FILE.read_text())["snoozed"]
        self.assertEqual(list(stored), [f"t:{made['chore']['id']}"])

    def test_a_sidecar_that_cannot_be_read_hides_nothing(self):
        """The direction in which being wrong costs one extra card rather
        than hiding a case somebody is waiting on."""
        made = self.one_of_each()
        self.press(f"p:{made['opportunity']['ts']}", 1_760_000_000.0)
        cases.SNOOZE_FILE.write_text("{ torn", encoding="utf-8")
        self.assertIn("opportunity",
                      {c["kind"] for c in cases.list_cases(now=1_760_000_060)})


# ---------------------------------------------------------------------------
# The rest of the verbs
# ---------------------------------------------------------------------------

class TestTheOverflow(StoresCase):
    def verbs(self, case_id: str) -> dict:
        return {row["verb"]: row for row in cases.overflow(cases.get(case_id))}

    def test_every_entry_names_a_verb_and_a_route(self):
        made = self.one_of_each()
        for ident in (f"f:{made['problem']['ts']}",
                      f"p:{made['opportunity']['ts']}",
                      f"h:{made['question']['ts']}",
                      f"t:{made['chore']['id']}"):
            for row in cases.overflow(cases.get(ident)):
                self.assertTrue(row["verb"])
                self.assertTrue(row["route"].startswith("/api/"))
                self.assertTrue(row["label"])

    def test_a_problem_keeps_the_claim_that_do_it_does_not_make(self):
        row = self.file_problem()
        verbs = self.verbs(f"f:{row['ts']}")
        self.assertEqual(verbs["done"]["route"], f"/api/finding/{row['ts']}/done")
        self.assertIn("fix", verbs)
        self.assertIn("discuss", verbs)
        self.assertIn("mute", verbs)

    def test_a_verb_that_cannot_work_is_absent_rather_than_disabled(self):
        row = self.file_problem(source="resident", source_title="The Resident")
        # Not a check's row, so there is nothing to run again.
        self.assertNotIn("recheck", self.verbs(f"f:{row['ts']}"))
        # Not held, so there is nothing to bring to the front.
        self.assertNotIn("elevate", self.verbs(f"f:{row['ts']}"))
        findings_store.set_status(row["ts"], "held")
        self.assertIn("elevate", self.verbs(f"f:{row['ts']}"))

    def test_a_check_row_may_be_run_again(self):
        row = self.file_problem()
        self.assertEqual(self.verbs(f"f:{row['ts']}")["recheck"]["route"],
                         f"/api/finding/{row['ts']}/recheck")

    def test_a_change_offers_to_put_it_back(self):
        row = self.file_problem()
        findings_store.set_status(row["ts"], "fixed")
        verbs = self.verbs(f"f:{row['ts']}")
        self.assertIn("unfix", verbs)
        self.assertNotIn("done", verbs)

    def test_an_opportunity_offers_the_week_that_makes_a_yes_evidence(self):
        made = self.file_opportunity()
        self.assertEqual(self.verbs(f"p:{made['ts']}")["trial"]["route"],
                         f"/api/proposal/{made['ts']}/trial")

    def test_a_question_has_no_overflow_at_all(self):
        made = self.file_question()
        self.assertEqual(cases.overflow(cases.get(f"h:{made['ts']}")), [])

    def test_a_finished_chore_can_be_put_back(self):
        item = self.file_chore()
        self.assertEqual(cases.overflow(cases.get(f"t:{item['id']}")), [])
        todo_store.complete(item["id"])
        self.assertEqual(self.verbs(f"t:{item['id']}")["reopen"]["route"],
                         f"/api/todo/{item['id']}/reopen")


# ---------------------------------------------------------------------------
# The store's half
# ---------------------------------------------------------------------------

class TestAResidentRowIsAlreadyJudged(StoresCase):
    def a_case(self, **fields) -> dict:
        row = {
            "text": "The garage freezer has been drifting warmer",
            "claim": "The garage freezer has been drifting warmer",
            "detail": "It reads 6C warmer than a month ago.",
            "kind": "problem", "confidence": 0.8, "stakes": "high",
            "severity": "serious", "fix": "Check the door seal.",
            "fix_by": "resident",
            "evidence": [{"entity": "sensor.garage_freezer_temp",
                          "value": "-12.4", "when": "now"}],
            "actions": [{"label": "Tell me if it passes -10",
                         "shape": "notify", "consent": False, "detail": ""}],
            "memory_hint": "The garage freezer sits in an unheated garage.",
        }
        row.update(fields)
        return findings_store.add_case(row, run_id="sess-1")

    def test_a_case_lands_carrying_the_verdict_that_wrote_it(self):
        """The gate's promise is that nothing reaches a person unjudged.
        A case IS the look, so what keeps the promise is written on the
        row rather than asserted in prose."""
        row = self.a_case()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["triage"]["verdict"], "elevated")
        self.assertEqual(row["triage"]["reason"], row["claim"])
        self.assertEqual(row["triage"]["run_id"], "sess-1")
        self.assertTrue(row["triage"]["wrote_fix"])

    def test_it_files_as_a_producer_the_scorecard_can_grade(self):
        row = self.a_case()
        self.assertEqual(row["source"], findings_store.RESIDENT_SOURCE)
        self.assertEqual(row["source_title"], findings_store.RESIDENT_TITLE)
        findings_store.settle_and_clear(row["ts"], "fixed")
        [scored] = findings_store.scorecard()
        self.assertEqual(scored["source"], "resident")
        self.assertEqual((scored["confirmed"], scored["wrong"]), (1, 0))

    def test_a_row_with_no_claim_is_refused(self):
        """The claim is the judgement. Without one this would be a door a
        producer that had not looked could file straight through, which is
        the one thing the gate exists to prevent."""
        self.assertIsNone(findings_store.add_case({"text": "Something"}))
        self.assertIsNone(findings_store.add_case({"claim": "  "}))
        self.assertIsNone(findings_store.add_case("not a row"))
        self.assertEqual(findings_store.list_all(), [])

    def test_a_case_whose_text_was_already_answered_is_dropped(self):
        row = self.a_case()
        findings_store.settle_and_clear(row["ts"], "ignored", "not a problem")
        self.assertIsNone(self.a_case())

    def test_the_run_id_is_provenance_and_is_not_required(self):
        row = findings_store.add_case({"text": "A thing", "claim": "A thing"})
        self.assertEqual(row["triage"]["verdict"], "elevated")
        self.assertEqual(row["run_id"], "")

    def test_the_case_fields_survive_the_round_trip(self):
        row = self.a_case()
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["kind"], "problem")
        self.assertEqual(stored["confidence"], 0.8)
        self.assertEqual(stored["stakes"], "high")
        self.assertEqual(stored["evidence"][0]["entity"],
                         "sensor.garage_freezer_temp")
        self.assertEqual(stored["actions"][0]["shape"], "notify")
        self.assertFalse(stored["actions"][0]["consent"])
        self.assertEqual(stored["fix_by"], "resident")
        self.assertIn("unheated garage", stored["memory_hint"])

    def test_the_case_reaches_the_feed_as_the_kind_it_claims(self):
        self.a_case(kind="opportunity",
                    text="The lounge could hold its heat better",
                    claim="The lounge could hold its heat better")
        [case] = cases.list_cases()
        self.assertEqual(case["kind"], "opportunity")
        self.assertEqual(case["investigation"], {"run_id": "sess-1"})
        self.assertEqual(case["confidence"], 0.8)
        self.assertEqual(case["actions"][0]["label"],
                         "Tell me if it passes -10")

    def test_an_action_shape_the_panel_does_not_know_is_dropped(self):
        """Every one of these is a thing that would happen to somebody's
        house; reading an unknown word as the nearest known one is how a
        notification becomes a file edit."""
        row = self.a_case(actions=[
            {"label": "Do something", "shape": "run_a_shell_command",
             "consent": False, "detail": ""},
            {"label": "Tell me", "shape": "notify", "consent": True}])
        self.assertEqual([a["shape"] for a in row["actions"]], ["notify"])

    def test_an_evidence_row_naming_nothing_is_not_evidence(self):
        row = self.a_case(evidence=[{"value": "9", "when": "now"},
                                    {"entity": "sensor.a", "value": "1",
                                     "when": "now"}])
        self.assertEqual([e["entity"] for e in row["evidence"]], ["sensor.a"])

    def test_a_confidence_that_is_not_a_number_is_no_confidence(self):
        for bad in ("high", None, True, [0.5]):
            row = self.a_case(confidence=bad,
                              text=f"A thing {bad}", claim=f"A thing {bad}")
            self.assertNotIn("confidence", row)

    def test_the_caps_hold(self):
        row = self.a_case(
            claim="c" * 5000,
            evidence=[{"entity": f"sensor.e{i}", "value": "1", "when": "now"}
                      for i in range(50)],
            actions=[{"label": f"A{i}", "shape": "notify", "consent": True,
                      "detail": ""} for i in range(50)],
            memory_hint="m" * 5000)
        self.assertEqual(len(row["claim"]), findings_store.MAX_CLAIM)
        self.assertEqual(len(row["evidence"]), findings_store.MAX_EVIDENCE)
        self.assertEqual(len(row["actions"]), findings_store.MAX_ACTIONS)
        self.assertEqual(len(row["memory_hint"]),
                         findings_store.MAX_MEMORY_HINT)


class TestEveryOtherRowIsUnchanged(StoresCase):
    """The compatibility half: a check's finding is the dict it has always
    been, key for key, in the store and in the mirror."""

    # What `_shape` has always emitted. Written out rather than derived,
    # because a list computed from the code it is checking agrees with
    # whatever the code does.
    HISTORIC = (
        "ts", "text", "detail", "fix", "fix_by", "severity", "fixable",
        "entity_id", "source", "source_title", "run_id", "status", "result",
        "changed", "settled_at", "snoozed_until", "triage", "plan",
        "fix_started", "fix_ended", "fix_files", "fix_calls", "checked_at")
    # `answers` is the one key added since the mirror was first written:
    # the presses a row can be given from outside the panel, `[{action,
    # label}]`, so Repairs and a notification offer what the feed does.
    # An older integration ignores a key it does not read.
    MIRROR = ("ts", "text", "severity", "status", "entity_id", "fixable",
              "source_title", "detail", "fix", "answers")

    def test_a_row_that_carries_no_case_fields_grows_no_keys(self):
        row = self.file_problem()
        self.assertEqual(tuple(row), self.HISTORIC)
        self.assertEqual(tuple(findings_store.get(row["ts"])), self.HISTORIC)

    def test_a_resident_row_adds_its_keys_at_the_end(self):
        row = findings_store.add_case({
            "text": "A drifting freezer", "claim": "A drifting freezer",
            "kind": "problem", "stakes": "high"})
        self.assertEqual(tuple(row)[:len(self.HISTORIC)], self.HISTORIC)
        self.assertEqual(tuple(row)[len(self.HISTORIC):],
                         ("kind", "claim", "stakes"))

    def test_the_mirror_keeps_its_wire_shape_for_an_ordinary_row(self):
        (Path(self.tmp.name) / "config").mkdir()
        self.file_problem()
        payload = json.loads(findings_store.STATE_FILE.read_text())
        self.assertEqual(tuple(payload["findings"][0]), self.MIRROR)

    def test_the_mirror_carries_a_resident_rows_claim(self):
        (Path(self.tmp.name) / "config").mkdir()
        findings_store.add_case({"text": "A drifting freezer",
                                 "claim": "A drifting freezer",
                                 "kind": "problem"})
        payload = json.loads(findings_store.STATE_FILE.read_text())
        self.assertEqual(tuple(payload["findings"][0]),
                         self.MIRROR + ("kind", "claim"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Whose fix it is
# ---------------------------------------------------------------------------

class TestWhoseFixItIs(StoresCase):
    """`fixable` reaches the feed, because the card has nothing else.

    The feed headed every `fix` sentence "You'd need to" — a single
    hardcoded string — so a row brAIn could act on told somebody to do it
    by hand while the same card's ⋯ offered to work the change out. The
    heading is chosen from this key and from nothing else, so a case that
    does not carry it cannot be rendered honestly.
    """

    def test_a_fixable_finding_says_so_on_its_case(self):
        self.file_problem(text="The porch automation is switched off",
                          fix="Turn it back on.", fixable=True)
        row = next(c for c in cases.list_cases()
                   if c["claim"].startswith("The porch"))
        self.assertTrue(row["fixable"])

    def test_a_hands_required_finding_says_so_too(self):
        self.file_problem(text="The hall sensor battery is flat",
                          fix="Replace the CR2032.", fixable=False)
        row = next(c for c in cases.list_cases()
                   if c["claim"].startswith("The hall sensor battery"))
        self.assertFalse(row["fixable"])

    def test_absent_reads_as_fixable_which_is_the_stores_own_rule(self):
        """`findings_store` documents absent as fixable; cases may not
        answer the same question differently, or a row written before the
        key existed changes meaning on its way to the screen."""
        row = self.file_problem(text="Something without the key")
        self.assertTrue(findings_store.coerce(dict(row)).get("fixable", True))
        case = next(c for c in cases.list_cases()
                    if c["claim"] == "Something without the key")
        self.assertTrue(case["fixable"])

    def test_every_case_carries_the_key_whatever_store_it_came_from(self):
        """A card that reads `undefined` picks the wrong heading silently."""
        self.one_of_each()
        rows = cases.list_cases()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("fixable", row, row.get("claim"))
            self.assertIsInstance(row["fixable"], bool)

    def test_a_chore_is_never_brains_to_do(self):
        """A to-do item is work somebody accepted. Whatever the finding it
        came from said, the person is the one doing it now."""
        self.file_chore()
        row = next(c for c in cases.list_cases(kinds=cases.KINDS)
                   if c["kind"] == "chore")
        self.assertFalse(row["fixable"])
