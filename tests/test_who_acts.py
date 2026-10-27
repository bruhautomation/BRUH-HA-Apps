#!/usr/bin/env python3
"""Every card on Needs you says, on its face, whose move it is (#451).

The owner's words: brAIn "needs a way to decide if it can handle a task on
its own … and when it can it really needs to be surfacing 'hey I can fix
this, go ahead?' … It's kind of unclear when I need to do something vs
it." So a card carries ONE line — "brAIn can fix this." over the press that
lets it, "This needs you." over Add to To Do, "brAIn needs an answer." over
Yes — decided on the server off the card's own primary press, so the line
and the button cannot disagree, and the line uses the household's name for
the assistant when one is set.
"""

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import findings_store  # noqa: E402
import personality  # noqa: E402

from test_answers import SHAPES, case  # noqa: E402
from test_cases import StoresCase  # noqa: E402

BRAIN_PRESSES = {"fix", "apply", "accept"}
HANDS_PRESSES = {"todo", "done", "complete"}
ANSWER_PRESSES = {"yes", "confirm", "answer"}


class TestEveryAnswerableCardSaysWhoActs(unittest.TestCase):
    def test_one_line_and_it_matches_the_primary(self):
        for name, shape in SHAPES.items():
            rows = answers.answers(shape)
            acts = answers.who_acts(shape)
            if not rows:
                # A run in flight: the phase line is what the card says.
                self.assertIsNone(acts, name)
                continue
            self.assertIsNotNone(acts, name)
            self.assertTrue(acts["line"], name)
            lead = [a for a in rows if a.get("primary")][0]
            verb = lead["verb"]
            if acts["who"] == "brain":
                self.assertIn(verb, BRAIN_PRESSES, name)
            elif acts["who"] == "you":
                self.assertIn(verb, HANDS_PRESSES, name)
                self.assertEqual(acts["line"], "This needs you.", name)
            elif acts["who"] == "answer":
                self.assertIn(verb, ANSWER_PRESSES, name)
                self.assertEqual(acts["line"], "brAIn needs an answer.", name)
            else:
                self.assertEqual(acts["who"], "told", name)

    def test_brain_can_fix_where_it_could_act(self):
        acts = answers.who_acts(SHAPES["generic"])
        self.assertEqual((acts["who"], acts["line"]),
                         ("brain", "brAIn can fix this."))
        planned = answers.who_acts(SHAPES["planned"])
        self.assertEqual(planned["line"], "brAIn can fix this.")

    def test_a_battery_and_a_refused_plan_need_you(self):
        for shape in (SHAPES["battery"], SHAPES["hands"],
                      case(finding_status="planned", fixable=True,
                           plan={"can_fix": False, "summary": "Needs a person."}),
                      case(source="resident", fixable=True,
                           plan={"summary": "Needs you.", "needs_you": True})):
            self.assertEqual(answers.who_acts(shape)["line"], "This needs you.")

    def test_never_both_lines(self):
        for shape in SHAPES.values():
            acts = answers.who_acts(shape)
            if acts:
                said = acts["line"]
                self.assertFalse("needs you" in said and "can fix" in said)

    def test_the_household_name_is_used(self):
        self.assertEqual(answers.who_acts(SHAPES["generic"], "Vesper")["line"],
                         "Vesper can fix this.")
        self.assertEqual(answers.who_acts(SHAPES["question"], "Vesper")["line"],
                         "Vesper needs an answer.")
        self.assertEqual(answers.who_line("brain", "  "), "brAIn can fix this.")


class TestTheAssistantsName(unittest.TestCase):
    def test_the_chosen_name_else_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "personality.json"
            self.assertEqual(personality.assistant_name(path=str(path)), "brAIn")
            path.write_text(json.dumps({"name": "Vesper", "persona": "calm"}))
            self.assertEqual(personality.assistant_name(path=str(path)), "Vesper")
            path.write_text("{not json")
            self.assertEqual(personality.assistant_name(path=str(path)), "brAIn")


class TestTheFeedCarriesIt(StoresCase):
    """Driven through the real `_cases_payload` over real stores."""

    def test_every_case_on_the_feed_has_its_line(self):
        import server  # noqa: PLC0415
        findings_store.add_many([
            {"text": "The hall motion sensor battery is at 4%",
             "severity": "warning", "source": "check:dev.battery_low",
             "fixable": False},
            {"text": "An automation calls a script that is gone",
             "severity": "warning", "source": "check:auto.dead_ref",
             "fixable": True},
        ])
        with unittest.mock.patch.object(server.personality, "assistant_name",
                                        return_value="Vesper"), \
                unittest.mock.patch.dict(server._NAMES, {}, clear=True):
            payload = server._cases_payload()
        lines = {c["claim"]: (c.get("who") or {}).get("line")
                 for c in payload["cases"]}
        self.assertEqual(lines["The hall motion sensor battery is at 4%"],
                         "This needs you.")
        self.assertEqual(lines["An automation calls a script that is gone"],
                         "Vesper can fix this.")

    def test_the_cards_no_case_covers_carry_it_too(self):
        import server  # noqa: PLC0415
        findings_store.add_many([{
            "text": "A sensor nothing has looked at yet",
            "severity": "warning", "source": "check:dev.unavailable"}])
        payload = server._findings_payload()
        for row in payload["findings"]:
            self.assertEqual(row["who"]["line"], "This needs you.")
        self.assertEqual(server._who_for("accept", "opportunity", "Vesper")["line"],
                         "Vesper can set this up.")
        self.assertEqual(server._who_for("apply", name="Vesper")["line"],
                         "Vesper can fix this.")


class TestThePanelDrawsIt(unittest.TestCase):
    def test_every_card_builder_hands_its_line_to_qcard(self):
        app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("function qWho(who)", app)
        for builder, arg in (("makeCase", "row.who"), ("makeLooseFinding", "f.who"),
                             ("makeLooseQuestion", "h.who"),
                             ("makeSuggestion", "row.who"),
                             ("makeTidyCard", "t.who"), ("makeUpdateCard", "u.who")):
            start = app.index(f"function {builder}(")
            body = app[start:app.index("\n}\n", start)]
            self.assertIn(f"who: {arg}", body, builder)


if __name__ == "__main__":
    unittest.main()
