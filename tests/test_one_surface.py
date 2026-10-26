#!/usr/bin/env python3
"""Needs you, Home Assistant's Repairs and a phone read as one surface (#452).

The owner: "wherever I'm looking at things (HA issues, morph feed, brain
insights), it feels like the same surface." So the Repairs dialog shows the
card's own title, its who-acts line (#451) and the same press words — read
off ONE table, `answers.REQUEST_LABELS`, which `notify_router.ACTION_LABELS`
is derived from rather than a second copy — and every fixed sentence that
names the assistant to a person uses the household's chosen name.

Driven end to end: the add-on's real `findings_store._publish_state` writes
the mirror, the integration's real `FindingsWatcher` raises the issue, and
the real `FindingRepairFlow` builds the menu from what the issue carries.
"""

import sys
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import answers  # noqa: E402
import findings_store  # noqa: E402
import notify_router  # noqa: E402
import personality  # noqa: E402

from test_brain_findings_watcher import REGISTRY, MirrorCase, findings  # noqa: E402
from test_brain_repairs import repairs  # noqa: E402


class TestOneTableOfPressWords(unittest.TestCase):
    def test_the_phone_reads_the_same_table(self):
        for verb, label in notify_router.ACTION_LABELS:
            self.assertEqual(label, answers.REQUEST_LABELS[verb])
        self.assertEqual(notify_router.DISMISS_LABEL,
                         answers.REQUEST_LABELS["dismiss"])

    def test_the_cards_presses_use_it(self):
        battery = {"id": "f:1", "kind": "problem", "status": "open",
                   "finding_status": "open",
                   "origin": {"store": "findings", "key": 1},
                   "source": "check:dev.battery_low", "fixable": False}
        by_request = {a["request"]: a["label"] for a in answers.answers(battery)
                      if a.get("request")}
        for action, label in by_request.items():
            self.assertEqual(label, answers.REQUEST_LABELS[action], action)


class TestTheDialogIsTheCard(MirrorCase):
    def _issue(self):
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        return REGISTRY.created[-1]

    def test_title_who_and_words_reach_the_dialog(self):
        with unittest.mock.patch.object(personality, "assistant_name",
                                        return_value="Vesper"):
            row = self.file("The landing sensor battery is at 3%",
                            fixable=False)
        issue = self._issue()
        placeholders = issue["translation_placeholders"]
        self.assertEqual(placeholders["text"], row["text"])
        self.assertEqual(placeholders["who"], "This needs you.")
        self.assertEqual(placeholders["assistant"], "Vesper")
        data = issue["data"]
        flow = repairs.FindingRepairFlow(row["ts"], data["text"],
                                         data["answers"], data["labels"],
                                         data["assistant"])
        menu = flow.menu_labels()
        self.assertIsNotNone(menu)
        # The card's own words, never "I've fixed it" or "Not a problem here".
        self.assertEqual(menu["todo"], "Add to To Do")
        self.assertEqual(menu["wrong"], "Ignore")
        self.assertEqual(menu["snooze"], "Snooze")
        self.assertEqual(menu["dismiss"], "Dismiss")
        for label in menu.values():
            self.assertIn(label, set(answers.REQUEST_LABELS.values()))

    def test_a_card_brain_can_fix_says_so_and_where_to_press(self):
        with unittest.mock.patch.object(personality, "assistant_name",
                                        return_value="Vesper"):
            # An automation check's fixable row leads with the press that
            # lets brAIn make the change.
            findings_store.add("An automation calls a script that is gone",
                               severity="warning", source="check:auto.dead_ref",
                               source_title="Automations", fixable=True)
        state = findings.read_findings_state(self.hass)
        mirror = state["findings"][0]
        self.assertEqual(mirror["who_kind"], "brain")
        self.assertEqual(mirror["who"], "Vesper can fix this.")
        issue = self._issue()
        self.assertIn("Needs you", issue["translation_placeholders"]["where"])

    def test_an_older_addon_falls_back_to_translated_words(self):
        flow = repairs.FindingRepairFlow(7, "x", ("wrong", "todo"))
        self.assertIsNone(flow.menu_labels())
        shown = flow.__class__.async_step_init
        self.assertTrue(callable(shown))


class TestTheNameOnAPhone(unittest.TestCase):
    def test_titles_use_the_household_name(self):
        with unittest.mock.patch.object(personality, "assistant_name",
                                        return_value="Vesper"):
            title, _ = notify_router.compose([{"text": "x"}])
            self.assertEqual(title, "Vesper found a problem")
            self.assertEqual(notify_router.compose_brief("Quiet.")[0],
                             "Vesper this morning")
            self.assertEqual(notify_router.compose_accepted("x", "")[0],
                             "Vesper made a change you accepted")
        title, _ = notify_router.compose([{"text": "x"}])
        self.assertTrue(title.endswith("found a problem"))


if __name__ == "__main__":
    unittest.main()
