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


class TestThreeButtonsAndAWayToSayNo(unittest.TestCase):
    def test_never_more_than_three_and_always_a_no(self):
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
        self.assertEqual([a["verb"] for a in got], ["todo", "done", "wrong"])
        self.assertEqual(got[1]["label"], "Replaced it")
        self.assertNotIn("fix", self.verbs(SHAPES["battery"]))

    def test_hands_are_never_led_by_a_run(self):
        self.assertEqual(self.verbs(SHAPES["hands"]), ["todo", "done", "wrong"])
        self.assertEqual(self.verbs(SHAPES["generic"]), ["fix", "todo", "wrong"])
        # An automation brAIn could change leads with the plan; one it
        # could not leads with the list.
        self.assertEqual(self.verbs(case(source="check:auto.dead_ref",
                                         fixable=True)), ["fix", "todo", "wrong"])
        self.assertEqual(self.verbs(SHAPES["automation"]), ["todo", "done", "wrong"])

    def test_a_quiet_device_can_be_off_on_purpose(self):
        got = answers.answers(SHAPES["unplugged"])
        self.assertEqual([a["verb"] for a in got], ["todo", "recheck", "wrong"])
        self.assertEqual(got[1]["label"], "It's back")
        self.assertEqual(got[2]["label"], "It's off on purpose")
        self.assertTrue(got[2]["note"])
        self.assertIn("on purpose", got[2]["prefill"])

    def test_a_stuck_sensor_can_be_normal_here(self):
        got = answers.answers(SHAPES["stuck"])
        self.assertEqual([a["verb"] for a in got], ["todo", "recheck", "wrong"])
        self.assertEqual(got[2]["label"], "It's normal here")

    def test_a_question_is_yes_or_no(self):
        got = answers.answers(SHAPES["question"])
        self.assertEqual([(a["verb"], a["label"]) for a in got],
                         [("yes", "Yes"), ("no", "No")])
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
                         ["accept", "trial", "decline"])
        self.assertEqual(self.verbs(SHAPES["chore"]), ["complete", "drop"])
        self.assertEqual(self.verbs(SHAPES["chore_done"]), ["reopen"])
        self.assertEqual(self.verbs(SHAPES["watching"]), ["elevate", "wrong"])
        self.assertEqual(self.verbs(SHAPES["chore_check"]), ["done", "not_now", "wrong"])


class TestWhatGoesBehindTheDots(unittest.TestCase):
    def test_later_is_added_and_visible_verbs_are_dropped(self):
        shape = SHAPES["hands"]
        visible = answers.answers(shape)
        overflow = [{"verb": "done", "label": "I had already done it",
                     "route": "/api/finding/1/done", "method": "POST"},
                    {"verb": "discuss", "label": "Talk about it",
                     "route": "/api/finding/1/discuss", "method": "POST"}]
        more = answers.more(shape, visible, overflow)
        self.assertEqual([m["verb"] for m in more], ["not_now", "discuss"])

    def test_no_later_where_later_makes_no_sense(self):
        for name in ("planned", "change", "chore_done", "watching"):
            shape = SHAPES[name]
            more = answers.more(shape, answers.answers(shape), [])
            self.assertNotIn("not_now", [m["verb"] for m in more], name)
        # A chore check already shows Later on the row, so it is not
        # offered twice.
        shape = SHAPES["chore_check"]
        more = answers.more(shape, answers.answers(shape), [])
        self.assertEqual(more, [])


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
                         [("todo", "Add to to-do"), ("wrong", "It's off on purpose"),
                          ("snooze", "Later")])

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
                         ["todo", "wrong", "snooze"])
        self.assertEqual(mirrored[1]["label"], "It's off on purpose")
        # The feed's own answers, on the same row, carry the same
        # wire actions in the same order plus the panel-only press.
        kase = cases.get(f"f:{row['ts']}")
        feed = [a["request"] for a in cases.answers(kase) if a["request"]]
        self.assertEqual(feed, ["todo", "wrong"])
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
                         ["todo", "recheck", "wrong"])
        self.assertEqual([m["verb"] for m in kase["more"]][0], "not_now")
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
