#!/usr/bin/env python3
"""Tests for `answers.py` — the buttons a case offers, decided once.

The complaint this module was written against, in its own words: *"Yes/no
questions have a 'do it' button. There are lots of buttons. I don't always
see a dismiss. Some items are boiled down to 'change the batteries' but I'm
getting a 'disable the integration' prompt."* Each of those is a test here,
and each is driven over the real shape a case has rather than a plausible
one: the second half files a finding through the real store and reads the
answers back off the mirror and off the feed payload the panel renders.
"""

import json
import sys
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import answers  # noqa: E402
import cases  # noqa: E402
import findings_store  # noqa: E402

from test_cases import StoresCase  # noqa: E402

NO = {"wrong", "no", "decline", "drop", "cancel"}

# A problem's row after its primary: *Check again* on a check's row,
# *Dismiss*, then *Snooze · Ignore*.
TAIL = ["dismiss", "not_now", "wrong"]
CHECK_TAIL = ["recheck"] + TAIL


def case(**over) -> dict:
    base = {
        "id": "f:1", "kind": "problem", "status": "open",
        "finding_status": "open", "origin": {"store": "findings", "key": 1},
        "source": "check:dev.unavailable", "fixable": False, "plan": {},
        "fix_started": 0, "fix_ended": 0,
    }
    base.update(over)
    return base


# One case shape per situation, so the table is driven whole and a
# situation nobody can reach fails here rather than being dead.
SHAPES = {
    "battery": case(source="check:dev.battery_low"),
    "unplugged": case(source="check:dev.unavailable"),
    "stuck": case(source="check:dev.frozen"),
    "chore_check": case(source="check:chore.waiting"),
    "automation": case(source="check:auto.conflict"),
    "generic": case(source="resident", fixable=True),
    "hands": case(source="resident", fixable=False),
    "planned": case(finding_status="planned", fixable=True,
                    plan={"can_fix": True}),
    "planning": case(status="acting", finding_status="planning"),
    "fixing": case(status="acting", finding_status="fixing"),
    "change": case(kind="change", finding_status="fixed"),
    "question": case(id="h:1", kind="question",
                     origin={"store": "hypotheses", "key": 1}),
    "opportunity": case(id="p:1", kind="opportunity",
                        origin={"store": "proposals", "key": 1}),
    "chore": case(id="t:1", kind="chore", origin={"store": "todo", "key": 1}),
    "chore_done": case(id="t:1", kind="chore", status="done",
                       origin={"store": "todo", "key": 1}),
    "watching": case(status="watching", finding_status="held"),
    # A fix run that did not finish: still a problem, and the second
    # attempt is behind the ⋯ rather than leading the row.
    "fix_failed": case(source="resident", fixable=True,
                       finding_status="failed"),
    "tidy": case(source="check:reg.hardware_name", fixable=True),
    "gap": case(kind="question", source="house_book"),
}


class TestTheSituationIsAClosedVocabulary(unittest.TestCase):
    def test_every_situation_is_reachable_and_nothing_else_is(self):
        self.assertEqual(set(SHAPES), set(answers.SITUATIONS))
        for name, shape in SHAPES.items():
            self.assertEqual(answers.situation(shape), name, name)

    def test_a_check_nobody_classified_is_generic_or_hands_by_fixable(self):
        # reg.no_area is classified now (its Fix it is the tidy run), so
        # the unclassified example is the registry check that is not.
        self.assertEqual(answers.situation(case(source="check:reg.orphan_device",
                                                fixable=True)), "generic")
        self.assertEqual(answers.situation(case(source="check:reg.orphan_device",
                                                fixable=False)), "hands")
        self.assertEqual(answers.situation(case(source="check:auto.dead_ref")),
                         "automation")


class TestOneRowAndAWayToSayNo(unittest.TestCase):
    def test_never_more_than_the_row_and_always_a_no(self):
        for name, shape in SHAPES.items():
            got = answers.answers(shape)
            self.assertLessEqual(len(got), answers.MAX_VISIBLE, name)
            if name in ("planning", "fixing"):
                self.assertEqual(got, [], name)
                continue
            self.assertTrue(got, name)
            if name in ("change", "chore_done"):
                continue
            verbs = {a["verb"] for a in got}
            self.assertTrue(verbs & NO, f"{name} offers no way to say no: {verbs}")

    def test_snooze_is_on_every_answerable_card(self):
        """"If I just want to ignore something and you may bring it up
        later, how do I do that?" — Snooze (`not_now`) is a visible press on
        every card a person answers, never behind the ⋯, and always the
        first of the secondary pair. A change to read, a finished chore and
        a held row are the three that are not answered that way."""
        for name, shape in SHAPES.items():
            got = answers.answers(shape)
            verbs = [a["verb"] for a in got]
            if name in ("planning", "fixing", "change", "chore_done", "watching"):
                self.assertNotIn("not_now", verbs, name)
                continue
            self.assertIn("not_now", verbs, name)
            # Second to last, just before Ignore — except on a question,
            # where Yes and No are the answer and Snooze follows them.
            if name == "question":
                self.assertEqual(verbs.index("not_now"), 2, name)
            else:
                self.assertEqual(verbs[-2:], ["not_now", verbs[-1]], name)
            dismiss = [a for a in got if a["verb"] == "not_now"][0]
            self.assertEqual(dismiss["label"], "Snooze")
            self.assertEqual(dismiss["request"], "snooze")
            self.assertFalse(dismiss["note"], "a snooze asks for no reason")

    def test_every_problem_takes_the_same_row_in_the_same_order(self):
        """One primary, then Check again (a check's row), Dismiss, Snooze ·
        Ignore — the same words in the same places on a battery, a quiet
        device, a stuck sensor and a Resident's case, so a row of buttons
        can be read without reading the words. The primary is Plan where
        brAIn could act and Add to list where a person's hands are
        needed. "The dismiss and check again buttons are useful": an old
        card that is no longer true is the commonest card there is."""
        tail = [("dismiss", "Dismiss"), ("not_now", "Snooze"), ("wrong", "Ignore")]
        check = [("recheck", "Check again")] + tail
        for name in ("battery", "unplugged", "stuck", "automation"):
            got = [(a["verb"], a["label"]) for a in answers.answers(SHAPES[name])]
            self.assertEqual(got, [("todo", "Add to list")] + check, name)
        for name in ("hands", "fix_failed"):
            got = [(a["verb"], a["label"]) for a in answers.answers(SHAPES[name])]
            self.assertEqual(got, [("todo", "Add to list")] + tail, name)
        got = [(a["verb"], a["label"]) for a in answers.answers(SHAPES["generic"])]
        self.assertEqual(got, [("fix", "Plan")] + tail)
        got = [(a["verb"], a["label"]) for a in answers.answers(
            case(source="check:auto.dead_ref", fixable=True))]
        self.assertEqual(got, [("fix", "Plan")] + check)

    def test_dismiss_clears_the_row_and_records_nothing(self):
        got = [a for a in answers.answers(SHAPES["battery"])
               if a["verb"] == "dismiss"][0]
        self.assertEqual((got["method"], got["route"]), ("DELETE", "/api/finding/1"))
        self.assertFalse(got["note"], "a dismiss asks for no reason")
        self.assertIsNone(got["request"], "Home Assistant carries no Dismiss")

    def test_every_label_is_a_vocabulary_word(self):
        """docs/design/ui-redesign-2026-10.md, "Action vocabulary": a
        button's label is one of these words and nothing else — Yes and No
        being the answer to a question rather than a verb."""
        vocab = {"Apply", "Plan", "Add to list", "Snooze", "Ignore", "Done",
                 "Restore", "Undo", "Ask", "Send", "Recheck", "Check again",
                 "Dismiss", "Run", "Save",
                 "Share", "Delete", "Yes", "No"}
        for name, shape in SHAPES.items():
            got = answers.answers(shape)
            for a in got + answers.more(shape, got, [
                    {"verb": "trial", "route": "/api/case/p:1/trial"}]):
                self.assertIn(a["label"], vocab, (name, a["label"]))

    def test_nothing_is_called_do_it_and_every_press_has_a_route(self):
        for name, shape in SHAPES.items():
            for a in answers.answers(shape):
                self.assertNotEqual(a["label"].strip().lower(), "do it", name)
                self.assertTrue(a["route"].startswith("/api/"), (name, a))
                self.assertTrue(a["label"] and a["hint"], (name, a))

    def test_exactly_one_primary_where_there_is_anything_to_press(self):
        for name, shape in SHAPES.items():
            got = answers.answers(shape)
            if not got:
                continue
            self.assertEqual(sum(1 for a in got if a["primary"]), 1, name)
            self.assertTrue(got[0]["primary"], name)


class TestTheButtonsThatFit(unittest.TestCase):
    def verbs(self, shape):
        return [a["verb"] for a in answers.answers(shape)]

    def test_a_battery_leads_with_the_to_do_list_and_never_a_plan_run(self):
        got = answers.answers(SHAPES["battery"])
        self.assertEqual([a["verb"] for a in got], ["todo"] + CHECK_TAIL)
        self.assertTrue(got[0]["primary"])
        self.assertNotIn("fix", self.verbs(SHAPES["battery"]))
        # ...even when the row claims brAIn could act: a battery is hands
        # whatever the producer wrote on it.
        self.assertNotIn("fix", self.verbs(case(source="check:dev.battery_low",
                                                fixable=True)))

    def test_hands_are_never_led_by_a_run(self):
        self.assertEqual(self.verbs(SHAPES["hands"]), ["todo"] + TAIL)
        self.assertEqual(self.verbs(SHAPES["generic"]), ["fix"] + TAIL)
        # An automation brAIn could change leads with the plan; one it
        # could not leads with the list.
        self.assertEqual(self.verbs(case(source="check:auto.dead_ref",
                                         fixable=True)),
                         ["fix"] + CHECK_TAIL)
        self.assertEqual(self.verbs(SHAPES["automation"]), ["todo"] + CHECK_TAIL)

    def test_the_situation_decides_the_reason_and_never_the_buttons(self):
        """A quiet device's "Not a problem" opens with "off on purpose"
        already in the box and a stuck sensor's with "normal for this
        sensor"; the button says the same thing on both, because a row
        whose words changed from card to card had to be read every time."""
        quiet = answers.answers(SHAPES["unplugged"])[-1]
        stuck = answers.answers(SHAPES["stuck"])[-1]
        plain = answers.answers(SHAPES["battery"])[-1]
        for a in (quiet, stuck, plain):
            self.assertEqual((a["verb"], a["label"]), ("wrong", "Ignore"))
            self.assertTrue(a["note"])
        self.assertIn("on purpose", quiet["prefill"])
        self.assertIn("normal for this sensor", stuck["prefill"])
        self.assertEqual(plain["prefill"], "")
        # "It's back" is Check again, on every check's row whatever the
        # situation — the situation decides the reason, not the buttons.
        self.assertIn("recheck", self.verbs(SHAPES["unplugged"]))
        self.assertIn("recheck", self.verbs(SHAPES["battery"]))

    def test_a_question_is_yes_or_no_and_can_be_put_off(self):
        got = answers.answers(SHAPES["question"])
        self.assertEqual([(a["verb"], a["label"]) for a in got],
                         [("yes", "Yes"), ("no", "No"), ("not_now", "Snooze")])
        self.assertTrue(got[1]["note"])
        self.assertTrue(got[0]["route"].endswith("/do"))
        self.assertTrue(got[1]["route"].endswith("/wrong"))

    def test_a_plan_offers_apply_only_where_it_can_fix(self):
        self.assertEqual(self.verbs(SHAPES["planned"]), ["apply"] + CHECK_TAIL)
        # A plan brAIn will not carry out is a pair of hands.
        refused = case(finding_status="planned", plan={"can_fix": False})
        self.assertEqual(self.verbs(refused), ["todo"] + CHECK_TAIL)
        # A plan written before plans were operations is out of date, and
        # the remedy is to plan again — never an Apply over nothing.
        legacy = case(finding_status="planned", fixable=True, plan={
            "can_fix": True, "ops_refused": answers.LEGACY_PLAN_MARK + " …"})
        got = answers.answers(legacy)
        self.assertEqual([(a["verb"], a["label"]) for a in got][0], ("fix", "Plan"))

    def test_a_change_is_got_it_and_undo_only_inside_a_window(self):
        self.assertEqual(self.verbs(SHAPES["change"]), ["ack"])
        windowed = case(kind="change", finding_status="fixed",
                        fix_started=10.0, fix_ended=20.0)
        self.assertEqual(self.verbs(windowed), ["ack", "unfix"])

    def test_the_rest(self):
        self.assertEqual(self.verbs(SHAPES["opportunity"]),
                         ["accept", "not_now", "decline"])
        self.assertEqual(self.verbs(SHAPES["chore"]), ["complete", "not_now", "drop"])
        self.assertEqual(self.verbs(SHAPES["chore_done"]), ["reopen"])
        self.assertEqual(self.verbs(SHAPES["watching"]), ["elevate", "wrong"])
        # A chore check leads with Done — the work is minutes — and the
        # list is one press further away.
        self.assertEqual(self.verbs(SHAPES["chore_check"]), ["done"] + CHECK_TAIL)
        got = answers.answers(SHAPES["chore_check"])
        self.assertEqual(got[0]["label"], "Done")


class TestWhatGoesBehindTheDots(unittest.TestCase):
    def test_the_dots_hold_at_most_three_and_never_a_visible_press(self):
        """The ⋯ is Ask, Recheck, Done and Plan chosen per kind — at most
        three, in vocabulary words, and never a press already on the row."""
        for name, shape in SHAPES.items():
            visible = answers.answers(shape)
            more = answers.more(shape, visible, [])
            self.assertLessEqual(len(more), answers.MAX_MORE, name)
            self.assertFalse({a["verb"] for a in visible}
                             & {m["verb"] for m in more}, name)
        hands = answers.more(SHAPES["hands"], answers.answers(SHAPES["hands"]), [])
        self.assertEqual([(m["verb"], m["label"]) for m in hands],
                         [("discuss", "Ask"), ("done", "Done")])
        quiet = SHAPES["unplugged"]
        got = answers.more(quiet, answers.answers(quiet), [])
        # Check again is on the row now, so the ⋯ does not offer it twice.
        self.assertEqual([m["label"] for m in got], ["Ask", "Done"])
        # A suggestion's week-long trial is the one verb read off the
        # overflow, and it is called Run.
        opp = SHAPES["opportunity"]
        got = answers.more(opp, answers.answers(opp), [
            {"verb": "trial", "route": "/api/case/p:1/trial"}])
        self.assertEqual([(m["verb"], m["label"]) for m in got], [("trial", "Run")])

    def test_the_row_press_a_card_leaves_off_is_behind_the_dots(self):
        """A chore check leads with Done and shows no Add to list; the
        list is still reachable, behind the ⋯. Nowhere else on a problem
        is a press of the fixed row missing from both."""
        shape = SHAPES["chore_check"]
        more = answers.more(shape, answers.answers(shape), [])
        self.assertEqual([(m["verb"], m["label"]) for m in more][0],
                         ("todo", "Add to list"))
        for name in ("planned", "change", "chore_done", "watching"):
            shape = SHAPES[name]
            more = answers.more(shape, answers.answers(shape), [])
            self.assertNotIn("not_now", [m["verb"] for m in more], name)
            self.assertNotIn("todo", [m["verb"] for m in more], name)


class TestWhatAPhoneCanCarry(unittest.TestCase):
    def test_only_wire_actions_and_always_a_later(self):
        for status, source, fixable in (("open", "check:dev.battery_low", False),
                                        ("open", "resident", True),
                                        ("open", "check:dev.unavailable", False),
                                        ("planned", "resident", True)):
            got = answers.request_answers({"ts": 1, "status": status,
                                           "source": source, "fixable": fixable})
            actions = [g["action"] for g in got]
            for action in actions:
                self.assertIn(action, answers.REQUEST_ACTIONS, action)
            self.assertIn("snooze", actions, (status, source))
            self.assertEqual(len(actions), len(set(actions)))

    def test_the_labels_are_the_cards_own(self):
        got = answers.request_answers({"ts": 1, "status": "open",
                                       "source": "check:dev.unavailable",
                                       "fixable": False})
        self.assertEqual([(g["action"], g["label"]) for g in got],
                         [("todo", "Add to list"), ("snooze", "Snooze"),
                          ("wrong", "Ignore")])

    def test_a_change_is_got_it_alone_and_a_run_in_flight_is_nothing(self):
        self.assertEqual(answers.request_answers({"ts": 1, "status": "fixed"}),
                         [{"action": "ack", "label": "Done"}])
        for status in ("planning", "fixing"):
            self.assertEqual(answers.request_answers({"ts": 1, "status": status}),
                             [], status)


class TestTheRealRowRoundTrip(StoresCase):
    """A finding filed through the real store, read back three ways."""

    def test_the_mirror_carries_the_answers_and_they_agree_with_the_feed(self):
        (Path(self.tmp.name) / "config").mkdir()
        row = self.file_problem()
        mirror = json.loads(findings_store.STATE_FILE.read_text())
        mirrored = mirror["findings"][0]["answers"]
        self.assertEqual([m["action"] for m in mirrored],
                         ["todo", "snooze", "wrong"])
        self.assertEqual(mirrored[1]["label"], "Snooze")
        # The feed's own answers, on the same row, carry the same
        # wire actions in the same order plus the panel-only press.
        kase = cases.get(f"f:{row['ts']}")
        feed = [a["request"] for a in cases.answers(kase) if a["request"]]
        self.assertEqual(feed, ["todo", "snooze", "wrong"])
        self.assertEqual(kase["finding_status"], "open")

    def test_the_feed_payload_carries_answers_more_and_names(self):
        import server  # noqa: PLC0415 — imported here so the fixture is in place
        row = self.file_problem()
        with unittest.mock.patch.dict(server._NAMES, {
            "sensor.hall_motion": {"name": "Hall Motion", "area": "Hall"}},
                clear=True):
            payload = server._cases_payload()
        kase = [c for c in payload["cases"] if c["id"] == f"f:{row['ts']}"][0]
        self.assertEqual([a["verb"] for a in kase["answers"]],
                         ["todo"] + CHECK_TAIL)
        self.assertIn("done", [m["verb"] for m in kase["more"]])
        self.assertLessEqual(len(kase["more"]), answers.MAX_MORE)
        # Today's card: one status chip, and whether "Ignore all like this"
        # can mute the rule that raised it.
        self.assertEqual(kase["chip"], "problem")
        self.assertTrue(kase["mutable"])
        self.assertFalse(kase["urgent"])
        self.assertEqual(kase["situation"], "unplugged")
        self.assertEqual(kase["entity_name"], "Hall Motion")
        self.assertEqual(kase["area"], "Hall")
        self.assertEqual(payload["names"]["sensor.hall_motion"]["name"],
                         "Hall Motion")
        # A visible verb is never also behind the dots.
        shown = {a["verb"] for a in kase["answers"]}
        self.assertFalse(shown & {m["verb"] for m in kase["more"]})


    def test_a_held_finding_is_not_on_the_feed_until_it_is_shown(self):
        """Triage held it, so it lives under Looked at and nowhere else.
        On the feed it rendered under Needs you with Show it anyway, and
        the press left the same card in place with the ordinary row on it
        — a button that read as doing nothing. Elevating is what puts it
        on the feed, and that is the one visible change the press makes."""
        import server  # noqa: PLC0415 — imported here so the fixture is in place
        row = self.file_problem()
        findings_store.set_status(row["ts"], "held")
        ids = [c["id"] for c in server._cases_payload()["cases"]]
        self.assertNotIn(f"f:{row['ts']}", ids)
        # Still a case — the Looked-at filter and a press by id reach it.
        self.assertEqual(cases.get(f"f:{row['ts']}")["status"], "watching")
        self.assertIsNotNone(findings_store.elevate(row["ts"]))
        ids = [c["id"] for c in server._cases_payload()["cases"]]
        self.assertIn(f"f:{row['ts']}", ids)

if __name__ == "__main__":
    unittest.main()
