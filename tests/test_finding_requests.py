"""An answer given somewhere else, on its way back to the one store.

The panel owns the findings store and Home Assistant cannot reach it —
8099 is unpublished on purpose — so a tick in the To-do app and a button
on a notification both cross the gap as a *request* the panel applies.

Every case here is about that gap being a few seconds wide: somebody's
phone is out of date, a file half written, an add-on that was off for a
week. None of those is an error, and all of them look like one to code
that assumes the two sides agree.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import finding_requests  # noqa: E402
import findings_store  # noqa: E402
import notify_router  # noqa: E402

# The integration's own writer, for the checks half: it imports
# `homeassistant.core` and nothing else on purpose, which is what makes it
# drivable straight into the panel's reader from here.
if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = type("HomeAssistant", (), {})
    sys.modules["homeassistant.core"] = _core
_pkg = types.ModuleType("brain_cc")
_pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules.setdefault("brain_cc", _pkg)
brain_requests = importlib.import_module("brain_cc.requests")  # noqa: E402


class _IntegrationHass:
    """The two attributes `requests.py` reaches for, and nothing else."""

    def __init__(self, base: str):
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(base, *parts))


class RequestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE,
                     finding_requests.REQUEST_DIR)
        base = Path(self.tmp.name)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.INBOX_DIR = base / "inbox"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "config" / ".brain" / "state.json"
        finding_requests.REQUEST_DIR = base / "requests"
        finding_requests.REQUEST_DIR.mkdir()

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE,
         finding_requests.REQUEST_DIR) = self._old
        self.tmp.cleanup()

    def drop(self, name: str, body) -> Path:
        path = finding_requests.REQUEST_DIR / name
        path.write_text(body if isinstance(body, str) else json.dumps(body),
                        encoding="utf-8")
        return path


class TestWhatCountsAsARequest(RequestCase):
    def test_the_three_endings_a_person_can_give_from_outside(self):
        for action in ("fixed", "wrong", "snooze"):
            got = finding_requests.parse({"ts": 12, "action": action})
            self.assertIsNotNone(got, action)
            self.assertEqual(got["action"], action)

    def test_a_reply_is_a_request_and_not_an_ending(self):
        # A reply typed into a notification is a turn in the case's
        # conversation: it is accepted as a request, and it maps to no
        # verb on the tab, because nothing about it settles the row.
        got = finding_requests.parse({"ts": 12, "action": "reply",
                                      "note": "why does this matter?"})
        self.assertIsNotNone(got)
        self.assertEqual(got["action"], "reply")
        self.assertEqual(got["note"], "why does this matter?")
        self.assertEqual(finding_requests.verb_for("reply"), "")

    def test_nothing_that_starts_work_is_an_answer(self):
        # A fix run, a regeneration, a delete: those are work rather than
        # an answer, and they belong behind the panel where the thing
        # they start can be watched.
        for action in ("fix", "delete", "regenerate", "discuss", "", None):
            self.assertIsNone(
                finding_requests.parse({"ts": 12, "action": action}), action)

    def test_every_field_is_data_from_another_process(self):
        for obj in (None, [], "fixed", {}, {"action": "fixed"},
                    {"ts": "12", "action": "fixed"},
                    {"ts": True, "action": "fixed"},
                    {"ts": 12}):
            self.assertIsNone(finding_requests.parse(obj), obj)

    def test_a_note_is_capped_and_a_snooze_is_bounded(self):
        got = finding_requests.parse(
            {"ts": 1, "action": "wrong", "note": "x" * 5000, "hours": 10 ** 9})
        self.assertEqual(len(got["note"]), finding_requests.NOTE_MAX)
        self.assertEqual(got["hours"], finding_requests.SNOOZE_MAX_H)
        floor = finding_requests.parse({"ts": 1, "action": "snooze", "hours": 0})
        self.assertEqual(floor["hours"], 1.0)
        default = finding_requests.parse({"ts": 1, "action": "snooze"})
        self.assertEqual(default["hours"], finding_requests.SNOOZE_DEFAULT_H)

    def test_a_request_names_the_tab_s_own_verb(self):
        # The two surfaces have to settle a finding through the same
        # code, so a request's action maps onto a verb the panel already
        # has rather than onto a second vocabulary.
        self.assertEqual(finding_requests.verb_for("fixed"), "done")
        self.assertEqual(finding_requests.verb_for("wrong"), "wrong")
        self.assertEqual(finding_requests.verb_for("snooze"), "")


class TestDrainingTheDrop(RequestCase):
    def test_what_is_taken_is_validated_and_the_files_are_gone(self):
        self.drop("001.json", {"ts": 5, "action": "fixed"})
        self.drop("002.json", {"ts": 6, "action": "wrong", "note": "no"})
        got = finding_requests.collect()
        self.assertEqual([r["ts"] for r in got], [5, 6])
        self.assertEqual(list(finding_requests.REQUEST_DIR.glob("*.json")), [])

    def test_oldest_first_so_answers_apply_in_the_order_they_were_given(self):
        for name in ("003.json", "001.json", "002.json"):
            self.drop(name, {"ts": int(name[:3]), "action": "fixed"})
        self.assertEqual([r["ts"] for r in finding_requests.collect()],
                         [1, 2, 3])

    def test_an_unreadable_request_is_dropped_not_retried_forever(self):
        self.drop("001.json", "{not json")
        self.drop("002.json", "[1, 2]")
        self.drop("003.json", {"nonsense": True})
        self.assertEqual(finding_requests.collect(), [])
        self.assertEqual(list(finding_requests.REQUEST_DIR.glob("*.json")), [])

    def test_an_enormous_file_is_not_a_request(self):
        self.drop("001.json", {"ts": 5, "action": "fixed",
                               "note": "x" * (finding_requests.MAX_BYTES + 10)})
        self.assertEqual(finding_requests.collect(), [])

    def test_a_backlog_is_drained_over_several_passes(self):
        # An add-on that was off for a week must not spend its first
        # minute back on a directory nothing drained.
        for i in range(finding_requests.MAX_PER_PASS + 20):
            self.drop(f"{i:04d}.json", {"ts": i + 1, "action": "fixed"})
        first = finding_requests.collect()
        self.assertEqual(len(first), finding_requests.MAX_PER_PASS)
        self.assertEqual(len(finding_requests.collect()), 20)

    def test_a_request_from_three_weeks_ago_is_dropped(self):
        path = self.drop("001.json", {"ts": 5, "action": "fixed"})
        old = time.time() - finding_requests.KEEP_S - 60
        os.utime(path, (old, old))
        self.drop("002.json", {"ts": 6, "action": "fixed"})
        self.assertEqual([r["ts"] for r in finding_requests.collect()], [6])

    def test_past_the_cap_the_oldest_go_rather_than_the_newest(self):
        for i in range(finding_requests.MAX_QUEUED + 5):
            self.drop(f"{i:05d}.json", {"ts": i + 1, "action": "fixed"})
        got = finding_requests.collect()
        # The five oldest were pruned, so the first one left is the sixth.
        self.assertEqual(got[0]["ts"], 6)

    def test_a_missing_directory_is_an_empty_queue_and_not_a_crash(self):
        finding_requests.REQUEST_DIR = Path(self.tmp.name) / "nowhere"
        self.assertEqual(finding_requests.collect(), [])
        self.assertEqual(finding_requests.pending(), 0)

    def test_a_half_written_file_is_invisible_until_it_is_whole(self):
        # The integration writes to a scratch name and renames, and the
        # panel globs "*.json" — so a partial write cannot be read.
        (finding_requests.REQUEST_DIR / "001.json.tmp").write_text(
            '{"ts": 5, "act', encoding="utf-8")
        self.assertEqual(finding_requests.collect(), [])
        self.assertEqual(finding_requests.pending(), 0)


class TestTheButtonsOnAMessage(unittest.TestCase):
    def test_only_the_companion_app_gets_buttons(self):
        # Every other notifier takes `data` and means something different
        # by it or nothing at all, and a payload built on a guess is how
        # a working notification stops arriving.
        self.assertTrue(notify_router.can_answer("notify.mobile_app_pixel"))
        self.assertTrue(notify_router.can_answer("mobile_app_pixel"))
        for service in ("notify.notify", "telegram", "notify.persistent_notification",
                        "notify.everyone", "", None, "mobile_apple"):
            self.assertFalse(notify_router.can_answer(service), service)

    def test_a_digest_gets_none_because_it_could_not_say_which(self):
        rows = [{"ts": 1, "text": "a"}, {"ts": 2, "text": "b"}]
        self.assertEqual(
            notify_router.actions_for(rows, "notify.mobile_app_pixel"), [])
        self.assertEqual(
            notify_router.actions_for([], "notify.mobile_app_pixel"), [])

    def test_one_finding_gets_the_cards_own_answers_and_a_reply(self):
        """The buttons are the row's own answers (`answers.py`): the feed's
        fixed row less the one press a phone cannot start (a plan run), so
        *Add to list · Dismiss · Not a problem* on every problem, and Reply
        rides last."""
        got = notify_router.actions_for([{"ts": 1720, "text": "a"}],
                                        "notify.mobile_app_pixel")
        self.assertEqual([a["action"] for a in got],
                         ["brain.todo.1720", "brain.snooze.1720",
                          "brain.wrong.1720", "brain.reply.1720"])
        self.assertEqual([a["title"] for a in got],
                         ["Add to list", "Dismiss", "Not a problem", "Reply"])
        hands = notify_router.actions_for(
            [{"ts": 1720, "text": "a", "fixable": False}],
            "notify.mobile_app_pixel")
        self.assertEqual([a["action"].split(".")[1] for a in hands],
                         ["todo", "snooze", "wrong", "reply"])
        quiet = notify_router.actions_for(
            [{"ts": 1720, "text": "a", "source": "check:dev.unavailable",
              "fixable": False}], "notify.mobile_app_pixel")
        self.assertEqual([a["title"] for a in quiet],
                         ["Add to list", "Dismiss", "Not a problem", "Reply"])
        # A change brAIn made gets Got it and nothing that would claim
        # somebody else's work.
        change = notify_router.actions_for(
            [{"ts": 1720, "text": "a", "status": "fixed"}],
            "notify.mobile_app_pixel")
        self.assertEqual([a["action"].split(".")[1] for a in change],
                         ["ack", "reply"])
        # A mirror row already carrying its answers is rendered as handed.
        stamped = notify_router.actions_for(
            [{"ts": 1720, "text": "a",
              "answers": [{"action": "wrong", "label": "Nope"}]}],
            "notify.mobile_app_pixel")
        self.assertEqual([(a["action"], a["title"]) for a in stamped],
                         [("brain.wrong.1720", "Nope"),
                          ("brain.reply.1720", "Reply")])
        # Never more than the companion app renders, plus Reply.
        for buttons in (got, quiet, change):
            self.assertLessEqual(len(buttons),
                                 notify_router.MAX_ANSWER_BUTTONS + 1)
        # Reply is the one button that takes text: the companion app
        # opens a box for `textInput` and sends what was typed as
        # `reply_text`. The endings carry no behaviour, because a box on
        # "I've fixed it" is a chore in front of a one-press answer.
        by_verb = {a["action"].split(".")[1]: a for a in got}
        self.assertEqual(by_verb["reply"].get("behavior"), "textInput")
        for verb in ("todo", "wrong", "snooze"):
            self.assertNotIn("behavior", by_verb[verb], verb)

    def test_a_row_with_no_id_gets_no_buttons(self):
        for row in ({"text": "a"}, {"ts": None, "text": "a"},
                    {"ts": True, "text": "a"}, {"ts": "1720"}):
            self.assertEqual(
                notify_router.actions_for([row], "notify.mobile_app_pixel"), [],
                row)

    def test_the_reader_rejects_far_more_than_it_accepts(self):
        # The companion app fires one event for every actionable
        # notification in the house, brAIn's and everybody else's.
        self.assertEqual(notify_router.parse_action("brain.fixed.1720"),
                         ("fixed", 1720))
        self.assertEqual(notify_router.parse_action("brain.reply.1720"),
                         ("reply", 1720))
        for junk in ("", None, "brain", "brain.fixed", "brain.fixed.x",
                     "brain.explode.1720", "other.fixed.1720",
                     "brain.fixed.1720.extra", "BRAIN.fixed.1720"):
            self.assertIsNone(notify_router.parse_action(junk), junk)

    def test_the_writer_and_the_reader_agree(self):
        # Two processes that cannot import each other, so the format is
        # driven end to end rather than written down twice.
        for ts in (1, 1720, 1_760_000_000):
            action = notify_router.actions_for(
                [{"ts": ts, "text": "a"}], "mobile_app_x")[0]["action"]
            self.assertEqual(notify_router.parse_action(action)[1], ts)


class TestBothFrontDoorsSettleTheSame(RequestCase):
    """The point of the whole exercise.

    An ending is three things — the row deleted, the key in the settled
    ledger, and the memory line in the homeowner's own words — and a tick
    in the To-do app has to do all three, identically to the press on the
    Findings tab that means the same. A second implementation would be
    the same answer teaching brAIn two different things depending on
    where it was given.
    """

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self.inbox = Path(self.tmp.name) / "memory-inbox"
        self._old_inbox = self.server.MEMORY_INBOX_DIR
        self.server.MEMORY_INBOX_DIR = self.inbox

    def tearDown(self):
        self.server.MEMORY_INBOX_DIR = self._old_inbox
        super().tearDown()

    def facts(self) -> list[dict]:
        out = []
        for path in sorted(self.inbox.glob("*.jsonl")) if self.inbox.is_dir() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def a_finding(self, text="The hall sensor has not reported since Tuesday"):
        entry, _created = findings_store.add(
            text, detail="last seen 3 Sep", fix="Re-pair it",
            severity="serious", source="check:dev.unavailable",
            source_title="Devices")
        return entry

    def test_a_tick_ends_the_finding_exactly_as_the_tab_does(self):
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "fixed",
                               "via": "todo"})
        got = asyncio.run(self.server._apply_finding_requests())

        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["ok"])
        self.assertEqual(got[0]["via"], "todo")
        # The row is gone from the list...
        self.assertEqual(findings_store.list_all(), [])
        # ...the key is in the ledger, so the next analysis does not
        # re-raise it...
        self.assertTrue(findings_store.is_known(entry["text"]))
        # ...and the memory line is the tab's own, not a second wording.
        facts = self.facts()
        self.assertEqual(len(facts), 1)
        self.assertIn("Fixed by the homeowner", facts[0]["fact"])
        self.assertIn(entry["text"], facts[0]["fact"])
        self.assertEqual(facts[0]["source"], "homeowner")

    def test_a_delete_is_the_correction_and_carries_its_reason(self):
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "wrong",
                               "note": "that cupboard is never opened",
                               "via": "todo"})
        asyncio.run(self.server._apply_finding_requests())
        facts = self.facts()
        self.assertEqual(len(facts), 1)
        # The note is the half that teaches, and it lands as a correction
        # rather than as a fact about a problem being over.
        self.assertIn("that cupboard is never opened", facts[0]["fact"])
        self.assertEqual(facts[0]["source"], "correction")

    def _stub_reply_run(self, answer="Still off since Tuesday; its hub rebooted at 03:10.",
                        ok=True):
        prompts: list[str] = []
        sent: list[tuple] = []

        def run_analyst(prompt, system, model, timeout, max_turns, source, **kw):
            prompts.append(prompt)
            return {"ok": ok, "text": answer, "error": "" if ok else "boom"}

        async def send(rows, message=None, **kw):
            sent.append((rows, message))
            return True

        self._old_run = self.server.engine.run_analyst
        self._old_send = self.server._send_notification
        self.server.engine.run_analyst = run_analyst
        self.server._send_notification = send
        self.addCleanup(setattr, self.server.engine, "run_analyst", self._old_run)
        self.addCleanup(setattr, self.server, "_send_notification", self._old_send)
        return prompts, sent

    def test_a_reply_is_answered_by_push_and_settles_nothing(self):
        # The Reply button is the case's conversation reached from a lock
        # screen: what was typed goes to the Resident under the finding
        # it was typed about, the answer comes back as the next
        # notification about the same row, and the row is exactly where
        # it was — the three verbs are still the only endings.
        prompts, sent = self._stub_reply_run()
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "reply",
                               "note": "why does this matter?",
                               "via": "notification"})
        got = asyncio.run(self.server._apply_finding_requests())

        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["ok"], got[0])
        self.assertEqual(got[0]["via"], "notification")
        # The run was handed the finding AND the words, as a reply.
        self.assertEqual(len(prompts), 1)
        self.assertIn(entry["text"], prompts[0])
        self.assertIn("They replied from their phone", prompts[0])
        self.assertIn("why does this matter?", prompts[0])
        # The answer went back to the same row, so it carries the same
        # buttons, and the body is what the run said.
        self.assertEqual(len(sent), 1)
        rows, message = sent[0]
        self.assertEqual([r["ts"] for r in rows], [entry["ts"]])
        self.assertIn("Still off since Tuesday", message[1])
        # Nothing settled: the row is on the list, the ledger is empty,
        # and no memory line was written about a question.
        self.assertEqual([r["ts"] for r in findings_store.list_all()],
                         [entry["ts"]])
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual(self.facts(), [])

    def test_a_failed_run_still_answers_rather_than_going_quiet(self):
        # A reply that vanished into silence is worse than one that says
        # brAIn could not look; the row stays and the person is told.
        _prompts, sent = self._stub_reply_run(answer="", ok=False)
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "reply",
                               "note": "is it still off?"})
        got = asyncio.run(self.server._apply_finding_requests())
        self.assertTrue(got[0]["ok"])
        self.assertEqual(len(sent), 1)
        self.assertIn("could not look", sent[0][1][1])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_an_empty_reply_is_not_a_turn(self):
        prompts, sent = self._stub_reply_run()
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "reply",
                               "note": "   "})
        got = asyncio.run(self.server._apply_finding_requests())
        self.assertFalse(got[0]["ok"])
        self.assertIn("empty", got[0]["why"])
        self.assertEqual(prompts, [])
        self.assertEqual(sent, [])

    def test_the_two_doors_produce_the_same_ledger_entry(self):
        # Driven rather than described: the same text, ended each way, has
        # to leave the same shape behind.
        first = self.a_finding("A is broken")
        self.drop("001.json", {"ts": first["ts"], "action": "fixed"})
        asyncio.run(self.server._apply_finding_requests())
        via_request = findings_store.settled_listing()[0]

        second = self.a_finding("B is broken")
        spec = self.server.FINDING_VERBS["done"]
        asyncio.run(self.server._end_finding(
            findings_store.get(second["ts"]), spec, ""))
        via_tab = findings_store.settled_listing()[0]

        self.assertEqual(via_request["kind"], via_tab["kind"])
        self.assertEqual(via_request["source"], via_tab["source"])
        self.assertEqual(via_request["source_title"], via_tab["source_title"])
        one, two = self.facts()
        self.assertEqual(one["source"], two["source"])
        self.assertEqual(one["fact"].replace("A is broken", "X"),
                         two["fact"].replace("B is broken", "X"))

    def test_a_snooze_leaves_the_finding_exactly_as_open_as_it_was(self):
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "snooze",
                               "hours": 3})
        asyncio.run(self.server._apply_finding_requests())
        row = findings_store.get(entry["ts"])
        self.assertEqual(row["status"], "open")
        self.assertGreater(row["snoozed_until"], time.time() + 3000)
        # "Not now" is not a decision, so it teaches nothing.
        self.assertEqual(self.facts(), [])

    def test_an_answer_for_a_finding_that_is_gone_is_an_ordinary_race(self):
        # Somebody ticks an item off while the panel has already cleared
        # it. Nothing is resurrected, nothing is retried, and it is not
        # reported as a failure of anything.
        self.drop("001.json", {"ts": 999, "action": "fixed"})
        got = asyncio.run(self.server._apply_finding_requests())
        self.assertEqual(len(got), 1)
        self.assertFalse(got[0]["ok"])
        self.assertEqual(got[0]["why"], "no such finding")
        self.assertEqual(findings_store.list_all(), [])
        self.assertEqual(self.facts(), [])

    def test_applying_the_same_request_twice_changes_nothing(self):
        # The delete can fail — a read-only /config, a permission that
        # changed — and the next pass finds the same file. That has to be
        # harmless, which is why there is no ledger of applied ids.
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "fixed"})
        asyncio.run(self.server._apply_finding_requests())
        self.drop("002.json", {"ts": entry["ts"], "action": "fixed"})
        asyncio.run(self.server._apply_finding_requests())
        self.assertEqual(len(self.facts()), 1)
        self.assertEqual(len(findings_store.settled_listing()), 1)

    def test_one_bad_request_does_not_stop_the_rest_of_the_queue(self):
        entry = self.a_finding()
        self.drop("001.json", "{not json")
        self.drop("002.json", {"ts": entry["ts"], "action": "fixed"})
        got = asyncio.run(self.server._apply_finding_requests())
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["ok"])

    def test_the_diagnostics_can_tell_a_quiet_week_from_a_dead_loop(self):
        entry = self.a_finding()
        self.drop("001.json", {"ts": entry["ts"], "action": "fixed"})
        self.drop("002.json", {"ts": 999, "action": "fixed"})
        before = dict(self.server.REQUESTS_STATE)
        asyncio.run(self.server._apply_finding_requests())
        got = self.server._requests_diagnostics()
        self.assertEqual(got["pending"], 0)
        self.assertEqual(got["applied"] - before["applied"], 1)
        self.assertEqual(got["missed"] - before["missed"], 1)
        self.assertGreater(got["last"], 0)

    def test_a_waiting_queue_is_visible_before_it_is_drained(self):
        self.drop("001.json", {"ts": 1, "action": "fixed"})
        self.drop("002.json", {"ts": 2, "action": "fixed"})
        self.assertEqual(self.server._requests_diagnostics()["pending"], 2)


class TestAskingForAChecksPass(RequestCase):
    """`brain.check` and the Run-checks button, from both ends.

    The one kind on this queue that is not an ending: it names no row,
    carries no verb, and what it asks for is minutes of work the drain
    loop cannot wait for. Two things have to hold — two asks in one drain
    are ONE pass (`create_task` only schedules, so two tasks made in the
    same tick would both clear `run_checks`' own guard), and a pass
    already running consumes the request rather than queueing it.
    """

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self._old_inbox = self.server.MEMORY_INBOX_DIR
        self.server.MEMORY_INBOX_DIR = Path(self.tmp.name) / "memory-inbox"
        self._old_run = self.server.run_checks
        self._old_state = dict(self.server.CHECKS_REQUEST_STATE)
        self._old_running = self.server.CHECKS_STATE["running"]
        self.runs: list[str] = []

        async def fake_run_checks(reason="schedule"):
            self.runs.append(reason)
            return {"reason": reason}

        self.server.run_checks = fake_run_checks

    def tearDown(self):
        self.server.run_checks = self._old_run
        self.server.MEMORY_INBOX_DIR = self._old_inbox
        self.server.CHECKS_REQUEST_STATE.clear()
        self.server.CHECKS_REQUEST_STATE.update(self._old_state)
        self.server.CHECKS_STATE["running"] = self._old_running
        super().tearDown()

    def a_finding(self) -> dict:
        entry, _created = findings_store.add(
            "The hall sensor has not reported since Tuesday",
            severity="serious", source="check:dev.unavailable",
            source_title="Devices")
        return entry

    def drain(self) -> list[dict]:
        """One pass of the drain, with the started task allowed to run."""
        async def go():
            out = await self.server._apply_finding_requests()
            # `_start_requested_checks` starts the pass and does not await
            # it — the loop has to be back for the next answer somebody
            # gives from their phone — so the test yields to let the task
            # it created reach its first line.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return out

        return asyncio.run(go())

    def test_what_the_integration_writes_is_what_the_panel_parses(self):
        # Neither process can import the other, so the format is driven
        # end to end rather than written down twice.
        hass = _IntegrationHass(self.tmp.name)
        self.assertTrue(brain_requests.write_checks_request(hass, "service"))
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = Path(brain_requests.requests_dir(hass))
        try:
            got = finding_requests.collect()
        finally:
            finding_requests.REQUEST_DIR = old
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "checks")
        self.assertEqual(got[0]["via"], "service")

    def test_a_checks_request_starts_a_pass(self):
        self.drop("001.json", {"kind": "checks", "via": "service"})
        got = self.drain()
        self.assertEqual(self.runs, ["service"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "checks")
        self.assertTrue(got[0]["ok"])

    def test_two_requests_in_one_drain_are_one_pass(self):
        self.drop("001.json", {"kind": "checks", "via": "service"})
        self.drop("002.json", {"kind": "checks", "via": "button"})
        got = self.drain()
        self.assertEqual(self.runs, ["service"])
        row = [r for r in got if r.get("kind") == "checks"][0]
        self.assertEqual(row["asked"], 2)
        self.assertIn("button", row["via"])
        self.assertIn("service", row["via"])

    def test_a_pass_already_running_consumes_the_request(self):
        """Not queued: a second pass a minute later over the same house
        finds the same things, and the one running is about to answer the
        question that was asked."""
        self.server.CHECKS_STATE["running"] = True
        self.drop("001.json", {"kind": "checks", "via": "service"})
        got = self.drain()
        self.assertEqual(self.runs, [])
        row = [r for r in got if r.get("kind") == "checks"][0]
        self.assertFalse(row["ok"])
        self.assertIn("already running", row["why"])
        # ...and the file is gone, so it cannot be applied again later.
        self.assertEqual(finding_requests.pending(), 0)

    def test_an_ending_in_the_same_burst_is_applied_before_the_pass(self):
        """A pass that ran first would re-file what the answer settled."""
        entry = self.a_finding()
        order: list[str] = []

        async def watching_run_checks(reason="schedule"):
            order.append("checks")
            return {"reason": reason}

        self.server.run_checks = watching_run_checks
        real_end = self.server._end_finding

        async def watching_end(finding, spec, note=""):
            order.append("ending")
            return await real_end(finding, spec, note)

        self.server._end_finding = watching_end
        try:
            self.drop("001.json", {"kind": "checks", "via": "service"})
            self.drop("002.json", {"ts": entry["ts"], "action": "fixed"})
            self.drain()
        finally:
            self.server._end_finding = real_end
        self.assertEqual(order, ["ending", "checks"])

    def test_a_request_nobody_can_see_is_a_request_that_swallows(self):
        self.drop("001.json", {"kind": "checks", "via": "service"})
        before = self.server._requests_diagnostics()["checks_asked"]
        self.drain()
        after = self.server._requests_diagnostics()
        self.assertEqual(after["checks_asked"] - before, 1)
        self.assertGreater(after["checks_asked_last"], 0)


if __name__ == "__main__":
    unittest.main()
