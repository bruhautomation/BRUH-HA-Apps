"""The trial: a replay of the week, graded against what you actually did.

1.42.0's trial set a status and an end date and evaluated nothing, so
every case here is about the half that was missing. The fixtures differ
by **one** thing at a time — the person row's state, or its timing, or
nothing at all — because the only way to believe a verdict is to see the
neighbouring fixture come out differently.

Each test names the mutation it catches:

  agreement            drop `row_state == state` -> everything is disagreed
  contradiction        fold `contradicted` into `disagreed` -> a change the
                       person actively undid reads as merely unproven
  the window           widen/remove AGREE_WINDOW_S -> a press an hour later
                       counts as an answer
  nearest wins         take the first match rather than the nearest -> the
                       verdict depends on ledger order
  a carried refusal    return zeros on Refused -> "cannot replay" reads as
                       "would never have fired"
  a time trigger       require history -> a time-triggered proposal, which
                       is every one the habit miner writes, never evaluates
  the target           accept several calls / an area target -> a firing is
                       graded against a press for a different entity
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import trials  # noqa: E402

DAY = 86400.0
# A Monday, 00:00 UTC, so the arithmetic below reads as clock time and the
# weekday condition below has a week to sit in. (2027-01-15 is a Friday.)
MON = 1_800_000_000.0 - (1_800_000_000.0 % DAY) + 3 * DAY


def at_config(entity: str = "light.hall", service: str = "light.turn_on",
              when: str = "18:40:00") -> dict:
    """What `routines.to_config` writes: a time trigger and one call."""
    return {"trigger": [{"platform": "time", "at": when}],
            "action": [{"service": service,
                        "target": {"entity_id": entity}}],
            "mode": "single"}


def press(ts: float, entity: str = "light.hall", state: str = "on") -> dict:
    return {"ts": int(ts), "entity_id": entity, "state": state,
            "name": entity}


def firing_seconds(day: int, hour: int = 18, minute: int = 40) -> float:
    return MON + day * DAY + hour * 3600 + minute * 60


class TrialCase(unittest.TestCase):
    def run_trial(self, rows, days=3, config=None, history=None):
        config = at_config() if config is None else config
        return trials.evaluate(config, history or {}, rows,
                               MON, MON + days * DAY, now=MON + days * DAY)


class TestTheThreeVerdicts(TrialCase):

    def test_a_press_at_the_same_time_to_the_same_state_is_agreement(self):
        rows = [press(firing_seconds(d) + 120) for d in range(3)]
        out = self.run_trial(rows)
        self.assertEqual(out["would_fire"], 3)
        self.assertEqual(out["agreed"], 3)
        self.assertEqual((out["disagreed"], out["contradicted"]), (0, 0))

    def test_nothing_at_all_is_a_disagreement_and_not_a_contradiction(self):
        """The ONLY difference from the case above is the empty ledger."""
        out = self.run_trial([])
        self.assertEqual(out["would_fire"], 3)
        self.assertEqual(out["disagreed"], 3)
        self.assertEqual((out["agreed"], out["contradicted"]), (0, 0))

    def test_the_opposite_state_is_its_own_verdict(self):
        """One character different from the agreement fixture: `off`.

        Folding this into `disagreed` reports a change the person
        actively undid as merely unproven, which is the number somebody
        would accept on.
        """
        rows = [press(firing_seconds(d) + 120, state="off")
                for d in range(3)]
        out = self.run_trial(rows)
        self.assertEqual(out["contradicted"], 3)
        self.assertEqual((out["agreed"], out["disagreed"]), (0, 0))

    def test_a_press_on_something_else_answers_nothing(self):
        rows = [press(firing_seconds(d) + 120, entity="light.kitchen")
                for d in range(3)]
        self.assertEqual(self.run_trial(rows)["disagreed"], 3)

    def test_a_state_with_no_opposite_is_not_a_contradiction(self):
        """`unavailable` is a reading that is not there, not a refusal."""
        rows = [press(firing_seconds(d) + 60, state="unavailable")
                for d in range(3)]
        out = self.run_trial(rows)
        self.assertEqual((out["disagreed"], out["contradicted"]), (3, 0))

    def test_every_firing_lands_in_exactly_one_bucket(self):
        rows = [press(firing_seconds(0) + 60),
                press(firing_seconds(1) + 60, state="off")]
        out = self.run_trial(rows)
        self.assertEqual(
            out["agreed"] + out["disagreed"] + out["contradicted"],
            out["would_fire"])


class TestTheWindow(TrialCase):

    def test_a_press_just_inside_the_window_counts(self):
        rows = [press(firing_seconds(0) + trials.AGREE_WINDOW_S - 1)]
        self.assertEqual(self.run_trial(rows)["agreed"], 1)

    def test_a_press_just_outside_it_does_not(self):
        """Same fixture, one second later."""
        rows = [press(firing_seconds(0) + trials.AGREE_WINDOW_S + 1)]
        out = self.run_trial(rows)
        self.assertEqual(out["agreed"], 0)
        self.assertEqual(out["disagreed"], 3)

    def test_the_window_reaches_backwards_too(self):
        """Somebody who got there first agreed with it."""
        rows = [press(firing_seconds(0) - trials.AGREE_WINDOW_S + 1)]
        self.assertEqual(self.run_trial(rows)["agreed"], 1)

    def test_the_nearest_press_decides_not_the_first_one_listed(self):
        """Ledger order must not choose the verdict.

        The far press is the wrong answer and is listed first; taking
        the first match rather than the nearest reports `contradicted`.
        """
        moment = firing_seconds(0)
        rows = [press(moment + 600, state="off"), press(moment + 30)]
        self.assertEqual(self.run_trial(rows)["agreed"], 1)
        rows.reverse()
        self.assertEqual(self.run_trial(rows)["agreed"], 1)


class TestARefusalIsCarried(TrialCase):

    def test_an_unreplayable_trigger_is_refused_and_not_zeroed(self):
        config = at_config()
        config["trigger"].append({"platform": "webhook", "webhook_id": "x"})
        out = self.run_trial([], config=config)
        self.assertTrue(out["refused"])
        self.assertIn("webhook", out["error"])
        self.assertNotIn("would_fire", out)

    def test_an_action_that_is_not_one_entity_one_state_is_refused(self):
        config = at_config()
        config["action"].append({"service": "light.turn_on",
                                 "target": {"entity_id": "light.kitchen"}})
        self.assertTrue(self.run_trial([], config=config)["refused"])

    def test_an_area_target_is_refused_rather_than_resolved(self):
        config = at_config()
        config["action"] = [{"service": "light.turn_on",
                             "target": {"area_id": "hall"}}]
        self.assertTrue(self.run_trial([], config=config)["refused"])

    def test_a_service_with_no_state_to_name_is_refused(self):
        config = at_config(service="light.toggle")
        self.assertTrue(self.run_trial([], config=config)["refused"])

    def test_a_service_the_producer_would_not_have_written_is_refused(self):
        """`routines.service_for` is the authority, so a call it does not
        agree with has no target — `switch.open_cover` is a real service
        name and a nonsense one for a switch."""
        config = at_config(entity="switch.pump", service="switch.open_cover")
        self.assertTrue(self.run_trial([], config=config)["refused"])

    def test_a_backwards_window_is_the_replay_refusing_and_says_so(self):
        out = trials.evaluate(at_config(), {}, [], MON + DAY, MON)
        self.assertTrue(out["refused"])
        self.assertIn("ends before it starts", out["error"])


class TestATimeTriggerNeedsNoHistory(TrialCase):

    def test_the_habit_miner_s_own_config_evaluates_with_an_empty_fetch(self):
        """Every proposal `routines.to_config` writes is a time trigger,
        so `entities_watched` is empty and there is nothing to fetch. A
        trial that required history would evaluate none of them."""
        import shadow
        config = at_config()
        self.assertEqual(shadow.entities_watched(config), set())
        out = self.run_trial([], config=config)
        self.assertEqual(out["would_fire"], 3)

    def test_a_weekday_condition_is_honoured_by_the_replay(self):
        config = at_config()
        config["condition"] = [{"condition": "time",
                                "weekday": ["sat", "sun"]}]
        # Monday to Thursday: no weekend day in the window at all.
        self.assertEqual(
            self.run_trial([], days=4, config=config)["would_fire"], 0)
        # And the same fixture over a week, which does hold one.
        self.assertEqual(
            self.run_trial([], days=7, config=config)["would_fire"], 2)

    def test_a_state_trigger_reads_the_history_it_is_handed(self):
        config = {"trigger": [{"platform": "state",
                               "entity_id": "binary_sensor.dusk",
                               "to": "on"}],
                  "action": [{"service": "light.turn_on",
                              "target": {"entity_id": "light.hall"}}],
                  "mode": "single"}
        history = {"binary_sensor.dusk": [
            {"entity_id": "binary_sensor.dusk", "state": "off",
             "last_changed": _iso(MON + 3600)},
            {"entity_id": "binary_sensor.dusk", "state": "on",
             "last_changed": _iso(firing_seconds(0))},
        ]}
        out = self.run_trial([press(firing_seconds(0) + 60)],
                             config=config, history=history)
        self.assertEqual(out["would_fire"], 1)
        self.assertEqual(out["agreed"], 1)


def _iso(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


class TestTheReportItself(TrialCase):

    def test_the_window_and_the_day_count_are_what_was_asked_for(self):
        out = self.run_trial([], days=3)
        self.assertEqual(out["window"], {"start": int(MON),
                                         "end": int(MON + 3 * DAY)})
        self.assertEqual(out["days"], 3)

    def test_a_part_day_rounds_down_because_a_day_is_not_over(self):
        out = trials.evaluate(at_config(), {}, [], MON, MON + 2.5 * DAY)
        self.assertEqual(out["days"], 2)

    def test_the_firing_list_is_capped_and_the_counts_are_not(self):
        """Four triggers a day for a fortnight — 56 firings, which is over
        the cap and inside `shadow.MAX_WINDOW_DAYS`."""
        config = at_config()
        config["trigger"] = [{"platform": "time", "at": f"{h:02d}:00:00"}
                             for h in (6, 12, 18, 22)]
        out = trials.evaluate(config, {}, [], MON, MON + 14 * DAY)
        self.assertEqual(out["would_fire"], 56)
        self.assertEqual(len(out["firings"]), trials.MAX_FIRING_ROWS)

    def test_it_names_the_entity_and_state_it_graded_against(self):
        out = self.run_trial([])
        self.assertEqual((out["entity_id"], out["state"]),
                         ("light.hall", "on"))

    def test_every_verdict_word_is_one_of_the_three(self):
        rows = [press(firing_seconds(0) + 60)]
        out = self.run_trial(rows)
        for row in out["firings"]:
            self.assertIn(row["verdict"], trials.VERDICTS)

    def test_nothing_here_writes_or_decides(self):
        """A trial reports; ending one is a person's press. The module
        holds no store path and no writer."""
        source = (BASE_DIR / "brain" / "panel" / "trials.py").read_text()
        body = source.split('"""', 2)[2]     # past the module docstring
        for forbidden in ("atomic_write", "open(", "proposals", "aiohttp"):
            self.assertNotIn(forbidden, body, forbidden)


if __name__ == "__main__":
    unittest.main()
