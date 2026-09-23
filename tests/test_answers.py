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
}


class TestTheSituationIsAClosedVocabulary(unittest.TestCase):
    def test_every_situation_is_reachable_and_nothing_else_is(self):
        self.assertEqual(set(SHAPES), set(answers.SITUATIONS))
        for name, shape in SHAPES.items():
            self.assertEqual(answers.situation(shape), name, name)

    def test_a_check_nobody_classified_is_generic_or_hands_by_fixable(self):
        self.assertEqual(answers.situation(case(source="check:reg.no_area",
                                                fixable=True)), "generic")
        self.assertEqual(answers.situation(case(source="check:reg.no_area",
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

    def test_dismiss_is_on_every_answerable_card(self):
        """"If I just want to ignore something and you may bring it up
        later, how do I do that?" — Dismiss (`not_now`, the snooze) is a
        visible press on every card a person answers, never behind the ⋯.
        A plan waiting for consent, a change to read, a finished chore and
        a held row are the four that are not answered that way."""
        for name, shape in SHAPES.items():
            got = answers.answers(shape)
            verbs = [a["verb"] for a in got]
            if name in ("planning", "fixing", "planned", "change",
                        "chore_done", "watching", "chore"):
                self.assertNotIn("not_now", verbs, name)
                continue
            self.assertIn("not_now", verbs, name)
            dismiss = [a for a in got if a["verb"] == "not_now"][0]
            self.assertEqual(dismiss["label"], "Dismiss")
            self.assertEqual(dismiss["request"], "snooze")
            self.assertFalse(dismiss["note"], "a snooze asks for no reason")

    def test_every_problem_takes_the_same_row_in_the_same_order(self):
        """The fixed row: Fix it where brAIn could act, then Add to list,
        Dismiss, Not a problem — the same words in the same places on a
        battery, a quiet device, a stuck sensor and a Resident's case, so a
        row of buttons can be read without reading the words."""
        tail = [("todo", "Add to list"), ("not_now", "Dismiss"),
                ("wrong", "Not a problem")]
        for name in ("battery", "unplugged", "stuck", "hands", "automation"):
            got = [(a["verb"], a["label"]) for a in answers.answers(SHAPES[name])]
            self.assertEqual(got, tail, name)
        for shape in (SHAPES["generic"],
                      case(source="check:auto.dead_ref", fixable=True)):
            got = [(a["verb"], a["label"]) for a in answers.answers(shape)]
            self.assertEqual(got, [("fix", "Fix it")] + tail)

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
        self.assertEqual([a["verb"] for a in got], ["todo", "not_now", "wrong"])
        self.assertTrue(got[0]["primary"])
        self.assertNotIn("fix", self.verbs(SHAPES["battery"]))
        # ...even when the row claims brAIn could act: a battery is hands
        # whatever the producer wrote on it.
        self.assertNotIn("fix", self.verbs(case(source="check:dev.battery_low",
                                                fixable=True)))

    def test_hands_are_never_led_by_a_run(self):
        self.assertEqual(self.verbs(SHAPES["hands"]), ["todo", "not_now", "wrong"])
        self.assertEqual(self.verbs(SHAPES["generic"]),
                         ["fix", "todo", "not_now", "wrong"])
        # An automation brAIn could change leads with the plan; one it
        # could not leads with the list.
        self.assertEqual(self.verbs(case(source="check:auto.dead_ref",
                                         fixable=True)),
                         ["fix", "todo", "not_now", "wrong"])
        self.assertEqual(self.verbs(SHAPES["automation"]),
                         ["todo", "not_now", "wrong"])

    def test_the_situation_decides_the_reason_and_never_the_buttons(self):
        """A quiet device's "Not a problem" opens with "off on purpose"
        already in the box and a stuck sensor's with "normal for this
        sensor"; the button says the same thing on both, because a row
        whose words changed from card to card had to be read every time."""
        quiet = answers.answers(SHAPES["unplugged"])[-1]
        stuck = answers.answers(SHAPES["stuck"])[-1]
        plain = answers.answers(SHAPES["battery"])[-1]
        for a in (quiet, stuck, plain):
            self.assertEqual((a["verb"], a["label"]), ("wrong", "Not a problem"))
            self.assertTrue(a["note"])
        self.assertIn("on purpose", quiet["prefill"])
        self.assertIn("normal for this sensor", stuck["prefill"])
        self.assertEqual(plain["prefill"], "")
        # "It's back" is Check again, behind the ⋯ now — the situation
        # no longer puts a recheck on the row.
        self.assertNotIn("recheck", self.verbs(SHAPES["unplugged"]))

    def test_a_question_is_yes_or_no_and_can_be_put_off(self):
        got = answers.answers(SHAPES["question"])
        self.assertEqual([(a["verb"], a["label"]) for a in got],
                         [("yes", "Yes"), ("no", "No"), ("not_now", "Dismiss")])
        self.assertTrue(got[1]["note"])
        self.assertTrue(got[0]["route"].endswith("/do"))
        self.assertTrue(got[1]["route"].endswith("/wrong"))

    def test_a_plan_offers_apply_only_where_it_can_fix(self):
        self.assertEqual(self.verbs(SHAPES["planned"]), ["apply", "cancel", "wrong"])
        refused = case(finding_status="planned", plan={"can_fix": False})
        self.assertEqual(self.verbs(refused), ["cancel", "wrong"])

    def test_a_change_is_got_it_and_undo_only_inside_a_window(self):
        self.assertEqual(self.verbs(SHAPES["change"]), ["ack"])
        windowed = case(kind="change", finding_status="fixed",
                        fix_started=10.0, fix_ended=20.0)
        self.assertEqual(self.verbs(windowed), ["ack", "unfix"])

    def test_the_rest(self):
        self.assertEqual(self.verbs(SHAPES["opportunity"]),
                         ["accept", "trial", "not_now", "decline"])
        self.assertEqual(self.verbs(SHAPES["chore"]), ["complete", "drop"])
        self.assertEqual(self.verbs(SHAPES["chore_done"]), ["reopen"])
        self.assertEqual(self.verbs(SHAPES["watching"]), ["elevate", "wrong"])
        # A chore check leads with Done — the work is minutes — and the
        # list is one press further away.
        self.assertEqual(self.verbs(SHAPES["chore_check"]), ["done", "not_now", "wrong"])
        got = answers.answers(SHAPES["chore_check"])
        self.assertEqual(got[0]["label"], "Done")


class TestWhatGoesBehindTheDots(unittest.TestCase):
    def test_visible_verbs_are_dropped_and_the_rest_ride_through(self):
        shape = SHAPES["hands"]
        visible = answers.answers(shape)
        overflow = [{"verb": "done", "label": "I've already fixed it",
                     "route": "/api/finding/1/done", "method": "POST"},
                    {"verb": "discuss", "label": "Talk about it",
                     "route": "/api/finding/1/discuss", "method": "POST"},
                    {"verb": "todo", "label": "dup", "route": "/x", "method": "POST"}]
        more = answers.more(shape, visible, overflow)
        # Dismiss is already on the row, so it is not offered twice; the
        # duplicate to-do is dropped for the same reason.
        self.assertEqual([m["verb"] for m in more], ["done", "discuss"])

    def test_the_row_press_a_card_leaves_off_is_behind_the_dots(self):
        """A chore check leads with Done and shows no Add to list; the
        list is still reachable, behind the ⋯. Nowhere else on a problem
        is a press of the fixed row missing from both."""
        shape = SHAPES["chore_check"]
        more = answers.more(shape, answers.answers(shape), [])
        self.assertEqual([(m["verb"], m["label"]) for m in more],
                         [("todo", "Add to list")])
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
                         [("todo", "Add to list"), ("snooze", "Dismiss"),
                          ("wrong", "Not a problem")])

    def test_a_change_is_got_it_alone_and_a_run_in_flight_is_nothing(self):
        self.assertEqual(answers.request_answers({"ts": 1, "status": "fixed"}),
                         [{"action": "ack", "label": "Got it"}])
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
        self.assertEqual(mirrored[1]["label"], "Dismiss")
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
                         ["todo", "not_now", "wrong"])
        self.assertEqual([m["verb"] for m in kase["more"]][0], "done")
        self.assertEqual(kase["situation"], "unplugged")
        self.assertEqual(kase["entity_name"], "Hall Motion")
        self.assertEqual(kase["area"], "Hall")
        self.assertEqual(payload["names"]["sensor.hall_motion"]["name"],
                         "Hall Motion")
        # A visible verb is never also behind the dots.
        shown = {a["verb"] for a in kase["answers"]}
        self.assertFalse(shown & {m["verb"] for m in kase["more"]})


if __name__ == "__main__":
    unittest.main()
