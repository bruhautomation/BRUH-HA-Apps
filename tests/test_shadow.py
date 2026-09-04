"""What an automation would have done, and the answers it must refuse.

Every case here is one of two things: a count recovered from a history
whose right answer is known by construction, or a refusal that has to
happen rather than a number that would look reasonable and be wrong.

The refusals are the larger half on purpose. A replay that reports "this
would have fired twice" about an automation whose webhook fires forty
times a day is a confident wrong number wearing a right one's clothes,
and it is the number somebody would decide on.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import shadow  # noqa: E402

UTC = dt.timezone.utc
# A Monday, so weekday conditions are predictable.
T0 = dt.datetime(2026, 2, 2, 0, 0, tzinfo=UTC).timestamp()
DAY = 86400.0


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).isoformat()


def rows(pairs: list[tuple[float, str]]) -> list[dict]:
    """`[(hours_after_T0, state), ...]` as history rows."""
    return [{"last_changed": iso(T0 + h * 3600), "state": s} for h, s in pairs]


def house() -> dict:
    """A day: a door that opens twice (once briefly), a warming sensor."""
    return {
        "binary_sensor.door": rows([(1, "off"), (9, "on"), (9.05, "off"),
                                    (20, "on"), (20.5, "off")]),
        "sensor.temp": rows([(1, "18"), (8, "22"), (12, "26"), (18, "21")]),
        "person.ben": rows([(0, "home"), (9, "not_home"), (18, "home")]),
    }


def run(config: dict, history: dict | None = None, hours: float = 24.0):
    return shadow.replay(config, house() if history is None else history,
                         T0, T0 + hours * 3600, UTC)


def trig(**kw) -> dict:
    return {"triggers": [kw]}


class TestTheCountsAreRight(unittest.TestCase):

    def test_a_state_trigger_counts_the_changes_it_names(self):
        got = run(trig(trigger="state", entity_id="binary_sensor.door",
                       to="on"))
        self.assertEqual(got["triggered"], 2)
        self.assertEqual(got["would_run"], 2)

    def test_a_from_narrows_it(self):
        self.assertEqual(
            run(trig(trigger="state", entity_id="binary_sensor.door",
                     **{"from": "on"}, to="off"))["would_run"], 2)

    def test_an_attribute_only_update_is_not_a_change(self):
        history = {"binary_sensor.door": rows([(1, "on"), (2, "on"), (3, "on")])}
        self.assertEqual(
            run(trig(trigger="state", entity_id="binary_sensor.door"),
                history)["triggered"], 0)

    def test_a_for_is_a_promise_about_a_stretch(self):
        """The 09:00 opening lasted three minutes, so a ten-minute `for`
        excludes it — a question about the NEXT sample, not this one."""
        plain = run(trig(trigger="state", entity_id="binary_sensor.door",
                         to="on"))
        held = run(trig(trigger="state", entity_id="binary_sensor.door",
                        to="on", **{"for": "00:10:00"}))
        self.assertEqual(plain["triggered"], 2)
        self.assertEqual(held["triggered"], 1)

    def test_a_for_reads_every_shape_home_assistant_takes(self):
        for spec in ("00:10:00", {"minutes": 10}, 600):
            self.assertEqual(
                run(trig(trigger="state", entity_id="binary_sensor.door",
                         to="on", **{"for": spec}))["triggered"], 1, spec)

    def test_numeric_state_is_a_crossing_not_a_level(self):
        """It climbs past 25 once and then STAYS there for three samples.

        Home Assistant fires on the way in, not for every sample spent
        inside — so a replay reading the level would answer 3 here, and
        the fixture has to hold three consecutive readings above the bar
        or it cannot tell the two apart at all.
        """
        climbing = {"sensor.temp": rows([(1, "18"), (2, "26"), (3, "27"),
                                         (4, "28"), (5, "21")])}
        got = run(trig(trigger="numeric_state", entity_id="sensor.temp",
                       above=25), climbing)
        self.assertEqual(got["triggered"], 1)

    def test_a_band_is_re_entered_and_that_counts_twice(self):
        """18 -> 22 -> 26 -> 21 enters 20..24, leaves it, and comes back.

        Both entries are firings, because Home Assistant fires on the
        crossing: a replay that counted the band once would be reporting
        "was it ever in range" rather than "when did it enter".
        """
        self.assertEqual(
            run(trig(trigger="numeric_state", entity_id="sensor.temp",
                     above=20, below=24))["triggered"], 2)

    def test_a_time_trigger_is_arithmetic(self):
        self.assertEqual(run(trig(trigger="time", at="07:30:00"))["triggered"], 1)
        self.assertEqual(
            run(trig(trigger="time", at="07:30:00"), hours=72)["triggered"], 3)

    def test_two_triggers_are_the_union_and_never_double_counted(self):
        got = run({"triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"},
            {"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"}]})
        self.assertEqual(got["triggered"], 2)

    def test_the_old_platform_spelling_still_reads(self):
        self.assertEqual(
            run({"trigger": [{"platform": "state",
                              "entity_id": "binary_sensor.door",
                              "to": "on"}]})["triggered"], 2)


class TestConditions(unittest.TestCase):

    def test_a_condition_blocks_without_hiding_the_trigger(self):
        """Both numbers are reported: "it fired twice and ran once" is a
        different fact from "it ran once"."""
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "state",
                                   "entity_id": "person.ben", "state": "home"}]})
        self.assertEqual(got["triggered"], 2)
        self.assertEqual(got["blocked_by_conditions"], 1)
        self.assertEqual(got["would_run"], 1)

    def test_a_numeric_condition_reads_the_state_AT_the_instant(self):
        """The door opens at 09:00 and 20:00; the sensor read 22 and 21
        then — never the 26 it reached at noon in between. A condition
        answered from the window's peak rather than from the moment
        would pass both."""
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "numeric_state",
                                   "entity_id": "sensor.temp", "above": 24}]})
        self.assertEqual(got["triggered"], 2)
        self.assertEqual(got["would_run"], 0)
        # And it does pass where the reading really is above the bar.
        warm = run({"triggers": [{"trigger": "state",
                                  "entity_id": "binary_sensor.door", "to": "on"}],
                    "conditions": [{"condition": "numeric_state",
                                    "entity_id": "sensor.temp", "above": 21}]})
        self.assertEqual(warm["would_run"], 1)     # 22 at 09:00, 21 at 20:00

    def test_and_or_not_nest(self):
        home = {"condition": "state", "entity_id": "person.ben", "state": "home"}
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "not", "conditions": [home]}]})
        self.assertEqual(got["would_run"], 1)      # the one where he is out

    def test_a_time_condition_reads_the_clock_and_the_weekday(self):
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "time", "after": "18:00:00"}]})
        self.assertEqual(got["would_run"], 1)
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "time", "weekday": "sun"}]})
        self.assertEqual(got["would_run"], 0)      # T0 is a Monday


class TestTemplates(unittest.TestCase):

    def test_a_template_is_rendered_against_the_world_as_it_was(self):
        got = run(trig(trigger="template",
                       value_template="{{ states('sensor.temp')|float(0) > 25 }}"))
        self.assertEqual(got["triggered"], 1)

    def test_a_template_fires_on_the_EDGE_not_on_every_true_moment(self):
        """Home Assistant fires when a template becomes true. Reporting
        every instant it stayed true would report the sampling."""
        history = {"sensor.temp": rows([(1, "10"), (2, "30"), (3, "31"),
                                        (4, "32"), (5, "9"), (6, "40")])}
        got = run(trig(trigger="template",
                       value_template="{{ states('sensor.temp')|float(0) > 25 }}"),
                  history)
        self.assertEqual(got["triggered"], 2)

    def test_is_state_and_state_attr_are_available(self):
        self.assertEqual(
            run(trig(trigger="template",
                     value_template="{{ is_state('person.ben','not_home') }}")
                )["triggered"], 1)

    def test_state_at_reads_what_was_recorded_before_the_instant(self):
        timeline = shadow.build_timeline(house())
        self.assertEqual(
            shadow.state_at(timeline, "person.ben", T0 + 12 * 3600)[0],
            "not_home")
        self.assertEqual(
            shadow.state_at(timeline, "person.ben", T0 + 23 * 3600)[0], "home")


class TestTheRefusals(unittest.TestCase):
    """The half that matters: a wrong number here looks like a right one."""

    def refuses(self, config, needle, history=None):
        with self.assertRaises(shadow.Refused) as caught:
            run(config, history)
        self.assertIn(needle, str(caught.exception))
        return str(caught.exception)

    def test_an_unreplayable_trigger_is_refused_by_name(self):
        for kind in ("webhook", "mqtt", "event", "device", "sun", "zone"):
            self.refuses(trig(trigger=kind), f"`{kind}`")

    def test_an_automation_is_refused_WHOLE_not_trimmed(self):
        """The case the scope decision exists for: replaying only the
        readable trigger reports a number that is wrong in the direction
        of looking reasonable."""
        self.refuses({"triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"},
            {"trigger": "webhook", "webhook_id": "x"}]}, "`webhook`")

    def test_a_trigger_that_does_not_say_its_kind(self):
        self.refuses({"triggers": [{"entity_id": "binary_sensor.door"}]},
                     "does not say what kind")

    def test_no_triggers_at_all(self):
        self.refuses({"actions": []}, "no triggers")

    def test_a_numeric_trigger_with_nothing_to_cross(self):
        self.refuses(trig(trigger="numeric_state", entity_id="sensor.temp"),
                     "nothing to cross")

    def test_a_template_reaching_past_what_can_be_rebuilt(self):
        got = self.refuses(
            trig(trigger="template",
                 value_template="{{ expand('group.all')|count > 2 }}"), "expand")
        self.assertIn("cannot rebuild", got)

    def test_a_template_naming_an_entity_with_no_history(self):
        """This returned `would_run: 0` before the check moved ahead of
        the sample loop — a confident zero about an automation that may
        fire daily, which is the worst failure this feature has."""
        self.refuses(
            trig(trigger="template",
                 value_template="{{ states('sensor.ghost')|float(0) > 1 }}"),
            "no recorded history")

    def test_a_condition_naming_an_entity_with_no_history(self):
        for cond in ({"condition": "state", "entity_id": "person.ghost",
                      "state": "home"},
                     {"condition": "numeric_state", "entity_id": "sensor.ghost",
                      "above": 5}):
            self.refuses({"triggers": [{"trigger": "state",
                                        "entity_id": "binary_sensor.door",
                                        "to": "on"}],
                          "conditions": [cond]}, "no recorded history")

    def test_a_condition_kind_that_cannot_be_replayed(self):
        self.refuses({"triggers": [{"trigger": "state",
                                    "entity_id": "binary_sensor.door",
                                    "to": "on"}],
                      "conditions": [{"condition": "zone", "entity_id": "x"}]},
                     "`zone` condition")

    def test_a_time_trigger_on_an_entity_is_not_arithmetic(self):
        self.refuses(trig(trigger="time", at="input_datetime.wake"),
                     "not a plain time of day")

    def test_a_window_longer_than_the_recorder_usually_keeps(self):
        with self.assertRaises(shadow.Refused) as caught:
            shadow.replay(trig(trigger="time", at="07:00:00"), house(), T0,
                          T0 + (shadow.MAX_WINDOW_DAYS + 1) * DAY, UTC)
        self.assertIn("at most", str(caught.exception))

    def test_a_window_that_ends_before_it_starts(self):
        with self.assertRaises(shadow.Refused):
            shadow.replay(trig(trigger="time", at="07:00:00"), house(),
                          T0 + DAY, T0, UTC)

    def test_a_trigger_that_would_fire_constantly_is_the_sampling(self):
        noisy = {"sensor.noise": rows([(h / 60.0, str(h % 2))
                                       for h in range(shadow.MAX_FIRINGS + 40)])}
        self.refuses(trig(trigger="state", entity_id="sensor.noise"),
                     "which is a trigger watching something", noisy)


class TestWhatItWouldHaveDone(unittest.TestCase):

    def test_the_service_calls_are_reported(self):
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "actions": [{"action": "light.turn_on",
                                "target": {"entity_id": "light.hall"}}]})
        self.assertEqual(got["actions"], [{"service": "light.turn_on",
                                           "entity_id": "light.hall",
                                           "area_id": None, "device_id": None}])

    def test_an_area_target_is_recorded_and_NOT_resolved(self):
        """Expanding one needs the registry as it was at the time, and a
        wrong expansion says a proposal touches lights it does not."""
        got = shadow.would_do({"actions": [{"action": "light.turn_off",
                                            "target": {"area_id": "kitchen"}}]})
        self.assertEqual(got[0]["area_id"], "kitchen")
        self.assertEqual(got[0]["entity_id"], [])

    def test_a_step_that_calls_nothing_is_not_an_action(self):
        self.assertEqual(
            shadow.would_do({"actions": [{"delay": "00:01:00"},
                                         {"wait_template": "{{ true }}"}]}), [])

    def test_the_entities_it_watches_are_listed(self):
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "binary_sensor.door", "to": "on"}],
                   "conditions": [{"condition": "state",
                                   "entity_id": "person.ben", "state": "home"}]})
        self.assertEqual(got["entities"],
                         ["binary_sensor.door", "person.ben"])


class TestTheDependencyNothingWasAsserting(unittest.TestCase):
    """A comment claimed the image shipped Jinja. The image did not.

    Every template trigger refused on every real install, and the three
    template tests passed anyway, because CI and a laptop both happened
    to have Jinja from somewhere else. The claim lived in a `# pragma:
    no cover` comment, and a comment cannot fail — the same failure as a
    grep for a line standing in for a test of what the line does.

    So both environments are asserted, and separately: the tests run
    where pip installed it, the add-on runs where apk did, and neither
    is evidence about the other.
    """

    def test_a_template_can_actually_be_rendered_here(self):
        # Not "is jinja2 importable" — the sandbox class shadow.py
        # reaches for, through shadow's own path.
        timeline = shadow.build_timeline(
            {"sensor.t": [{"state": "21", "last_changed": iso(0)}]})
        self.assertTrue(
            shadow.render_template(
                "{{ states('sensor.t') | float > 20 }}", timeline, T0 + 60))

    def test_the_image_ships_what_a_template_needs(self):
        root = Path(__file__).resolve().parent.parent
        dockerfile = (root / "brain" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("py3-jinja2", dockerfile,
                      "shadow.render_template needs Jinja, and an add-on "
                      "that does not install it refuses every template "
                      "trigger on every real install")
        reqs = (root / "tests" / "requirements-dev.txt").read_text(
            encoding="utf-8")
        self.assertIn("jinja2", reqs.lower(),
                      "the suite must not depend on Jinja arriving by "
                      "accident — that is what hid this for a release")


if __name__ == "__main__":
    unittest.main()
