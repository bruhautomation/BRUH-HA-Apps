"""HA 2026.7's purpose-specific triggers are state triggers with a name.

`trigger: light.turned_on` with the light under `target:` is what Home
Assistant's automation editor writes by default since 2026.7, and the
shadow runner refused every one of them as *"the recorder does not keep
what it fires on"* — a sentence that is not true: they fire on state
changes the recorder keeps like any other. So every automation built in
the new editor lost its replay, its week's trial and its condition card,
and `auto.trigger_unavailable` never looked at its trigger at all.

The semantics below are Core's, read off its source rather than off the
names (`homeassistant/helpers/trigger/entity_trigger.py`,
`EntityTargetStateTriggerBase` / `EntityTransitionTriggerBase` and the
`behavior` each/first/all handling; `homeassistant/helpers/condition.py`,
`EntityConditionBase` with `behavior` any/all; each domain's own
`trigger.py`/`condition.py` for which value reaches which state):

  * neither end of the change may be `unavailable`/`unknown`;
  * the tracked value must reach one of the target states, from a value
    that is not already one of them — or, for a transition trigger, from
    one of its named origins;
  * `behavior: each` fires per entity, `first` when exactly one targeted
    entity has got there, `all` when every reporting one has;
  * a condition leaves an unavailable entity out of both `any` and `all`.

And a kind brAIn does not have in its table is refused as NOT KNOWN,
never as not recorded — the second is a claim about Home Assistant.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import shadow  # noqa: E402
import trials  # noqa: E402

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 2, 2, 0, 0, tzinfo=UTC).timestamp()


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).isoformat()


def rows(pairs, attrs=None):
    """`[(hours_after_T0, state[, attributes]), ...]` as history rows."""
    out = []
    for p in pairs:
        h, s = p[0], p[1]
        a = p[2] if len(p) > 2 else (attrs or {})
        out.append({"last_changed": iso(T0 + h * 3600), "state": s,
                    "attributes": a})
    return out


def run(config, history, hours=24.0):
    return shadow.replay(config, history, T0, T0 + hours * 3600, UTC)


def purpose(kind, entities, **options):
    block = {"trigger": kind, "target": {"entity_id": entities}}
    if options:
        block["options"] = options
    return {"triggers": [block],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.hall"}}]}


LIGHTS = {
    # off → on → (attribute update while on) → off → unavailable → on
    "light.kitchen": rows([(0, "off"), (8, "on"), (8.5, "on"), (9, "off"),
                           (12, "unavailable"), (13, "on"), (20, "off"),
                           (21, "on")]),
    "light.lounge": rows([(0, "off"), (21.5, "on")]),
}


class TestALightTurnedOn(unittest.TestCase):

    def test_it_counts_the_changes_into_on(self):
        got = run(purpose("light.turned_on", "light.kitchen"), LIGHTS)
        # 08:00 and 21:00. The 08:30 row is the same state again, and the
        # 13:00 one comes FROM unavailable, which Core does not fire on.
        self.assertEqual(got["triggered"], 2)
        self.assertEqual(sorted(got["entities"]), ["light.kitchen"])

    def test_turned_off_is_the_mirror(self):
        got = run(purpose("light.turned_off", "light.kitchen"), LIGHTS)
        self.assertEqual(got["triggered"], 2)   # 09:00 and 20:00

    def test_a_for_is_a_stretch_after_the_change(self):
        got = run(purpose("light.turned_on", "light.kitchen",
                          **{"for": "00:45:00"}), LIGHTS)
        # 08:00 held an hour; 21:00 held three. Both count, each 45 min on.
        self.assertEqual(got["at"], [T0 + 8.75 * 3600, T0 + 21.75 * 3600])
        got = run(purpose("light.turned_on", "light.kitchen",
                          **{"for": {"hours": 2}}), LIGHTS)
        self.assertEqual(got["at"], [T0 + 23 * 3600])


class TestAStretchEndsWhereItBreaks(unittest.TestCase):
    """A `for:` was ended by the NEXT recorded row, whatever it said. The
    recorder keeps a row for an attribute-only update, and Home Assistant
    does not cancel a `for:` over one, so a light that stayed on for an
    hour read as one that stayed on until somebody dimmed it — and a
    `numeric_state` stretch on a sensor reporting every few minutes could
    never last longer than the gap between two readings."""

    def test_an_attribute_update_does_not_end_a_state_stretch(self):
        history = {"light.kitchen": rows([
            (0, "off"), (8, "on", {"brightness": 100}),
            (8.5, "on", {"brightness": 40}), (9, "off")])}
        got = run({"triggers": [{"trigger": "state",
                                 "entity_id": "light.kitchen", "to": "on",
                                 "for": "00:45:00"}]}, history)
        self.assertEqual(got["at"], [T0 + 8.75 * 3600])

    def test_a_reading_that_stays_inside_the_range_holds(self):
        history = {"sensor.temp": rows([(0, "18"), (6, "26"), (6.25, "27"),
                                        (6.5, "28"), (7, "21")])}
        got = run({"triggers": [{"trigger": "numeric_state",
                                 "entity_id": "sensor.temp", "above": 25,
                                 "for": {"minutes": 50}}]}, history)
        self.assertEqual(got["at"], [T0 + (6 + 50 / 60) * 3600])
        got = run({"triggers": [{"trigger": "numeric_state",
                                 "entity_id": "sensor.temp", "above": 25,
                                 "for": {"minutes": 61}}]}, history)
        self.assertEqual(got["at"], [])


class TestBehaviour(unittest.TestCase):

    def test_each_fires_for_every_entity(self):
        got = run(purpose("light.turned_on", ["light.kitchen", "light.lounge"],
                          behavior="each"), LIGHTS)
        self.assertEqual(got["triggered"], 3)

    def test_the_old_word_any_is_each(self):
        got = run(purpose("light.turned_on", ["light.kitchen", "light.lounge"],
                          behavior="any"), LIGHTS)
        self.assertEqual(got["triggered"], 3)

    def test_first_fires_on_the_first_to_get_there(self):
        got = run(purpose("light.turned_on", ["light.kitchen", "light.lounge"],
                          behavior="first"), LIGHTS)
        # 08:00 kitchen (lounge off) and 21:00 kitchen (lounge off); the
        # lounge at 21:30 is the SECOND to be on, which is not first.
        self.assertEqual(got["at"], [T0 + 8 * 3600, T0 + 21 * 3600])

    def test_all_fires_when_the_last_one_gets_there(self):
        got = run(purpose("light.turned_on", ["light.kitchen", "light.lounge"],
                          behavior="all"), LIGHTS)
        self.assertEqual(got["at"], [T0 + 21.5 * 3600])

    def test_a_stretch_about_all_of_them_is_refused(self):
        with self.assertRaises(shadow.Refused):
            run(purpose("light.turned_on", ["light.kitchen", "light.lounge"],
                        behavior="all", **{"for": "00:05:00"}), LIGHTS)


class TestTheOtherShapes(unittest.TestCase):

    def test_started_heating_reads_hvac_action(self):
        history = {"climate.hall": rows([
            (0, "heat", {"hvac_action": "idle"}),
            (6, "heat", {"hvac_action": "heating"}),
            (7, "heat", {"hvac_action": "idle"}),
            (17, "heat", {"hvac_action": "heating"}),
        ])}
        got = run(purpose("climate.started_heating", "climate.hall"), history)
        self.assertEqual(got["triggered"], 2)

    def test_climate_turned_on_is_a_transition_from_off(self):
        history = {"climate.hall": rows([(0, "off"), (6, "heat"),
                                         (7, "cool"), (8, "off"),
                                         (9, "auto")])}
        got = run(purpose("climate.turned_on", "climate.hall"), history)
        # heat→cool is a change between two "on" modes and is not one.
        self.assertEqual(got["at"], [T0 + 6 * 3600, T0 + 9 * 3600])

    def test_a_door_is_a_binary_sensor_or_a_cover(self):
        history = {
            "binary_sensor.front": rows([(0, "off"), (8, "on"), (9, "off")]),
            "cover.garage": rows([(0, "closed", {"is_closed": True}),
                                  (10, "opening", {"is_closed": False}),
                                  (10.02, "open", {"is_closed": False}),
                                  (11, "closed", {"is_closed": True})]),
        }
        got = run(purpose("door.opened",
                          ["binary_sensor.front", "cover.garage"]), history)
        # opening → open is the same "open", so the garage counts once.
        self.assertEqual(got["at"], [T0 + 8 * 3600, T0 + 10 * 3600])
        got = run(purpose("door.closed",
                          ["binary_sensor.front", "cover.garage"]), history)
        self.assertEqual(got["at"], [T0 + 9 * 3600, T0 + 11 * 3600])

    def test_a_cover_with_no_is_closed_reads_its_state(self):
        history = {"cover.blind": rows([(0, "closed"), (7, "opening"),
                                        (7.01, "open"), (20, "closed")])}
        got = run(purpose("cover.blind_opened", "cover.blind"), history)
        self.assertEqual(got["triggered"], 1)

    def test_media_started_playing_needs_a_named_origin(self):
        history = {"media_player.tv": rows([
            (0, "off"), (19, "playing"), (19.5, "paused"),
            (19.6, "playing"), (20, "unavailable"), (20.1, "playing")])}
        got = run(purpose("media_player.started_playing", "media_player.tv"),
                  history)
        # off→playing and paused→playing; unavailable→playing is not one.
        self.assertEqual(got["at"], [T0 + 19 * 3600, T0 + 19.6 * 3600])


class TestTheRefusalsSayTheTruth(unittest.TestCase):

    def test_an_area_target_is_refused_by_name(self):
        config = {"triggers": [{"trigger": "light.turned_on",
                                "target": {"area_id": "kitchen"}}]}
        with self.assertRaises(shadow.Refused) as caught:
            shadow.check_replayable(config)
        self.assertIn("area", str(caught.exception))

    def test_a_kind_brain_does_not_know_is_not_called_unrecorded(self):
        config = {"triggers": [{"trigger": "light.brightness_changed",
                                "target": {"entity_id": "light.kitchen"}}]}
        with self.assertRaises(shadow.Refused) as caught:
            shadow.check_replayable(config)
        said = str(caught.exception)
        self.assertIn("`light.brightness_changed`", said)
        self.assertIn("does not know", said)
        self.assertNotIn("recorder does not keep", said)

    def test_a_sun_trigger_is_not_called_unrecorded_either(self):
        with self.assertRaises(shadow.Refused) as caught:
            shadow.check_replayable({"triggers": [{"trigger": "sun"}]})
        self.assertNotIn("recorder does not keep", str(caught.exception))

    def test_a_webhook_still_is(self):
        with self.assertRaises(shadow.Refused) as caught:
            shadow.check_replayable(
                {"triggers": [{"trigger": "webhook", "webhook_id": "x"}]})
        self.assertIn("recorder does not keep", str(caught.exception))

    def test_a_target_naming_nothing_is_refused(self):
        with self.assertRaises(shadow.Refused):
            shadow.check_replayable(
                {"triggers": [{"trigger": "light.turned_on", "target": {}}]})

    def test_an_entity_with_no_history_is_refused_not_zero(self):
        with self.assertRaises(shadow.Refused):
            run(purpose("light.turned_on", "light.attic"), LIGHTS)

    def test_the_four_legacy_kinds_are_still_the_four(self):
        # `intents.SYSTEM` tells the model these four by name, and the
        # table is not a fifth thing to tell it.
        self.assertEqual(shadow.REPLAYABLE,
                         {"time", "state", "numeric_state", "template"})


class TestPurposeConditions(unittest.TestCase):

    HISTORY = {
        "binary_sensor.door": rows([(0, "off"), (9, "on"), (9.05, "off"),
                                    (20, "on"), (20.5, "off")]),
        "light.hall": rows([(0, "off"), (19, "on"), (23, "off")]),
        "light.porch": rows([(0, "unavailable"), (19.5, "on")]),
    }

    def config(self, cond):
        return {"triggers": [{"trigger": "state",
                              "entity_id": "binary_sensor.door", "to": "on"}],
                "conditions": [cond],
                "actions": []}

    def test_light_is_on_holds_only_while_it_is(self):
        got = run(self.config({"condition": "light.is_on",
                               "target": {"entity_id": "light.hall"}}),
                  self.HISTORY)
        self.assertEqual(got["triggered"], 2)
        self.assertEqual(got["would_run"], 1)   # 20:00, not 09:00
        self.assertIn("light.hall", got["entities"])

    def test_all_leaves_an_unavailable_entity_out(self):
        cond = {"condition": "light.is_on",
                "target": {"entity_id": ["light.hall", "light.porch"]},
                "options": {"behavior": "all"}}
        got = run(self.config(cond), self.HISTORY)
        # 09:00: hall off (porch unavailable, not counted) → no.
        # 20:00: hall on, porch on → yes.
        self.assertEqual(got["would_run"], 1)

    def test_a_condition_on_an_area_is_refused(self):
        with self.assertRaises(shadow.Refused):
            run(self.config({"condition": "light.is_on",
                             "target": {"floor_id": "upstairs"}}),
                self.HISTORY)

    def test_a_condition_with_a_for_is_refused(self):
        with self.assertRaises(shadow.Refused):
            run(self.config({"condition": "light.is_on",
                             "target": {"entity_id": "light.hall"},
                             "options": {"for": "00:10:00"}}),
                self.HISTORY)


class TestATrialOfOneIsNoLongerRefused(unittest.TestCase):
    """Trials are a replay graded against what a person did; refusing the
    replay refused the trial. A light.turned_on rule now has one."""

    def test_it_grades_rather_than_refusing(self):
        config = purpose("light.turned_on", "light.kitchen")
        got = trials.evaluate(config, LIGHTS, [], T0, T0 + 24 * 3600, UTC,
                              now=T0 + 24 * 3600)
        self.assertFalse(got.get("refused"), got)
        self.assertEqual(got["would_fire"], 2)


if __name__ == "__main__":
    unittest.main()
