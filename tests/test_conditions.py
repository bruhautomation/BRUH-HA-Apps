"""The condition an automation you keep undoing does not have.

`auto.overridden` already reports the fight; this is the change that ends
it, and every test here is about the proposal being *right* rather than
about it existing. Each names the mutation it catches:

  the `not` wrapper          write the bare `time` condition the obvious
                             way -> a `time` condition is a conjunction, so
                             the automation stands down every weekend too
  the band's complement      keep the band as the passing window -> the
                             automation runs ONLY in the hours somebody
                             undoes it, which is the change backwards
  the ledger's floors        re-derive the pattern here -> a second answer
                             to "is this a pattern", and the second one is
                             the one nobody can see
  no `id`                    offer anyway -> an accept that cannot address
                             the entry it means
  already stands down        offer anyway -> a second copy of a condition
                             somebody already wrote
  an unreadable condition    read it as absent -> "I could not tell" is
                             reported as "there is nothing there"
  a protected target         offer anyway -> a card offering something the
                             writer will refuse, which is a wasted no
  a refusal is not a card    put it on the tab -> a card on a list whose
                             whole contract is that every card can be
                             answered, and that one cannot
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import conditions  # noqa: E402
import override_ledger  # noqa: E402
import shadow  # noqa: E402

UTC = dt.timezone.utc
# A Monday, so weekday arithmetic in the tests reads as it is written.
MONDAY = dt.datetime(2026, 3, 2, 12, 0, tzinfo=UTC).timestamp()


def evening(day: int, hour: int = 21, minute: int = 30) -> float:
    """A timestamp `day` days after that Monday, at an hour of the evening."""
    base = dt.datetime(2026, 3, 2, hour, minute, tzinfo=UTC)
    return (base + dt.timedelta(days=day)).timestamp()


def overrides(entity: str = "automation.evening_lights",
              days=(0, 1, 2, 7, 8), hour: int = 21) -> list[dict]:
    return [{"ts": int(evening(d, hour, 10 + i * 5)),
             "entity_id": "light.lounge", "by": entity,
             "by_name": "Evening lights", "from_state": "on",
             "to_state": "off"}
            for i, d in enumerate(days)]


CONFIG = {
    "id": "evening_lights",
    "alias": "Evening lights",
    "trigger": [{"platform": "time", "at": "21:00:00"}],
    "action": [{"service": "light.turn_on",
                "target": {"entity_id": "light.lounge"}}],
    "mode": "single",
}


def snap(config: dict | None = CONFIG, entity: str = "automation.evening_lights"):
    cfg = dict(config) if config else None
    entities = []
    if cfg is not None and cfg.get("id"):
        entities.append({"entity_id": entity, "platform": "automation",
                         "unique_id": cfg["id"]})
    return {
        "states": {entity: {"entity_id": entity, "state": "on",
                            "attributes": {}}},
        "entities": entities,
        "devices": [], "areas": [], "services": ["light.turn_on"],
        "automations": [] if cfg is None else [cfg],
    }


def build(config=CONFIG, rows=None, patterns=None, entity="automation.evening_lights"):
    return conditions.build(snap(config, entity),
                            overrides(entity) if rows is None else rows,
                            UTC, evening(9), patterns)


class TestTheBand(unittest.TestCase):

    def test_a_band_is_the_hours_it_occupies(self):
        self.assertEqual(conditions.band_hours(21, 23), {21, 22})

    def test_a_band_wraps_midnight_because_bedtimes_do(self):
        self.assertEqual(conditions.band_hours(22, 1), {22, 23, 0})

    def test_a_band_that_starts_where_it_ends_is_the_whole_day(self):
        self.assertEqual(conditions.band_hours(3, 3), set(range(24)))


class TestTheCondition(unittest.TestCase):
    """The shape, and then what it actually does at an instant."""

    def setUp(self):
        self.cond = conditions.time_condition(21, 23, conditions.WEEKDAYS)

    def test_it_is_one_time_condition_inside_a_not(self):
        self.assertEqual(self.cond["condition"], "not")
        inner = self.cond["conditions"]
        self.assertEqual(len(inner), 1)
        self.assertEqual(inner[0]["condition"], "time")
        self.assertEqual(inner[0]["after"], "21:00:00")
        self.assertEqual(inner[0]["before"], "23:00:00")
        self.assertEqual(inner[0]["weekday"], conditions.WEEKDAYS)

    # Driven rather than described: `shadow.passes` is Home Assistant's
    # own semantics as this add-on replays them, so asking it is asking
    # what the automation would do.
    def held(self, when: float) -> bool:
        return shadow.passes(self.cond, {}, when, UTC)

    def test_it_stands_the_automation_down_inside_the_band(self):
        self.assertFalse(self.held(evening(0, 21, 30)))    # Monday 21:30
        self.assertFalse(self.held(evening(4, 22, 59)))    # Friday 22:59

    def test_it_leaves_every_other_hour_of_a_weekday_alone(self):
        self.assertTrue(self.held(evening(0, 20, 59)))
        self.assertTrue(self.held(evening(0, 23, 0)))
        self.assertTrue(self.held(evening(0, 7, 0)))

    def test_it_still_runs_at_the_weekend(self):
        """The mutation: drop the `not` and write the band directly. A
        `time` condition is a conjunction of its window AND its weekdays,
        so the direct version passes only on weekday evenings — which
        stands the automation down all weekend, every weekend, for a
        pattern that was never about the weekend."""
        self.assertTrue(self.held(evening(5, 21, 30)))     # Saturday
        self.assertTrue(self.held(evening(6, 22, 30)))     # Sunday

    def test_a_band_that_crosses_midnight_is_honoured_on_both_sides(self):
        cond = conditions.time_condition(22, 1, conditions.WEEKDAYS)
        self.assertFalse(shadow.passes(cond, {}, evening(0, 22, 30), UTC))
        self.assertFalse(shadow.passes(cond, {}, evening(1, 0, 30), UTC))
        self.assertTrue(shadow.passes(cond, {}, evening(1, 2, 30), UTC))


class TestWhatItAddsTo(unittest.TestCase):

    def test_an_automation_with_no_conditions_gets_one(self):
        out = conditions.with_condition(CONFIG, {"condition": "sun"})
        self.assertEqual(out["condition"], [{"condition": "sun"}])
        self.assertEqual(out["trigger"], CONFIG["trigger"])
        self.assertNotIn("condition", CONFIG, "the original was mutated")

    def test_an_existing_condition_list_is_appended_to(self):
        config = dict(CONFIG, condition=[{"condition": "state"}])
        out = conditions.with_condition(config, {"condition": "sun"})
        self.assertEqual(len(out["condition"]), 2)

    def test_a_single_condition_mapping_becomes_a_list(self):
        config = dict(CONFIG, condition={"condition": "state"})
        out = conditions.with_condition(config, {"condition": "sun"})
        self.assertEqual(len(out["condition"]), 2)

    def test_the_file_s_own_spelling_of_the_key_is_kept(self):
        """`conditions:` is 2024.10's spelling and `condition:` is the
        older one. Rewriting one as the other would be brAIn deciding how
        somebody's file is spelled, on a press about something else."""
        config = {"id": "x", "triggers": [], "actions": [],
                  "conditions": [{"condition": "state"}]}
        out = conditions.with_condition(config, {"condition": "sun"})
        self.assertEqual(len(out["conditions"]), 2)
        self.assertNotIn("condition", out)


class TestWhatItAlreadyRefuses(unittest.TestCase):

    def test_no_conditions_blocks_no_hours(self):
        self.assertEqual(
            conditions.blocked_hours(CONFIG, conditions.WEEKDAYS), set())

    def test_a_bare_time_condition_blocks_everything_outside_its_window(self):
        config = dict(CONFIG, condition=[
            {"condition": "time", "after": "07:00:00", "before": "09:00:00"}])
        blocked = conditions.blocked_hours(config, conditions.WEEKDAYS)
        self.assertIn(21, blocked)
        self.assertNotIn(8, blocked)

    def test_a_negated_time_condition_blocks_its_own_window(self):
        config = dict(CONFIG, condition=[
            conditions.time_condition(21, 23, conditions.WEEKDAYS)])
        blocked = conditions.blocked_hours(config, conditions.WEEKDAYS)
        self.assertEqual({21, 22}, blocked & {21, 22})
        self.assertNotIn(8, blocked)

    def test_a_condition_about_other_days_says_nothing_about_these(self):
        config = dict(CONFIG, condition=[
            {"condition": "time", "after": "07:00:00", "before": "09:00:00",
             "weekday": ["sat", "sun"]}])
        self.assertEqual(
            conditions.blocked_hours(config, conditions.WEEKDAYS), set())

    def test_a_condition_about_SOME_of_these_days_is_unreadable(self):
        """Half an overlap cannot be answered from the config alone, and
        an unreadable condition may not be reported as an absent one."""
        config = dict(CONFIG, condition=[
            {"condition": "time", "after": "07:00:00", "weekday": ["mon"]}])
        self.assertIsNone(
            conditions.blocked_hours(config, conditions.WEEKDAYS))

    def test_a_time_condition_naming_an_entity_is_unreadable(self):
        config = dict(CONFIG, condition=[
            {"condition": "time", "after": "input_datetime.bedtime"}])
        self.assertIsNone(
            conditions.blocked_hours(config, conditions.WEEKDAYS))


class TestBuilding(unittest.TestCase):

    def test_the_proposal_carries_the_edited_automation_and_its_id(self):
        rows = build()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["kind"], "condition")
        self.assertEqual(row["source"], "condition")
        self.assertEqual(row["edits"], "evening_lights")
        self.assertEqual(row["automation"]["entity_id"],
                         "automation.evening_lights")
        # The person's own automation, with one thing different.
        self.assertEqual(row["config"]["trigger"], CONFIG["trigger"])
        self.assertEqual(row["config"]["action"], CONFIG["action"])
        self.assertEqual(row["config"]["condition"], [row["condition"]])
        self.assertEqual(row["before_config"], CONFIG)

    def test_the_why_carries_the_ledger_s_numbers_and_a_denominator(self):
        why = build()[0]["why"]
        self.assertIn("5 times", why)
        self.assertIn("5 separate weekdays", why)
        self.assertIn("21:00", why)
        self.assertIn("in the last 9 days", why)

    def test_the_title_says_what_the_change_is(self):
        self.assertEqual(
            build()[0]["title"],
            "Stand Evening lights down between 21:00 and 22:00 on weekdays")

    def test_a_pattern_under_the_ledger_s_floors_offers_nothing(self):
        """The floors are `override_ledger`'s, and reusing them is the
        point: three events is under MIN_EVENTS and this file has no
        threshold of its own to disagree with it."""
        self.assertLess(3, override_ledger.MIN_EVENTS + 1)
        self.assertEqual(build(rows=overrides(days=(0, 1, 2))[:3]), [])

    def test_a_pattern_with_no_band_offers_nothing(self):
        rows = (overrides(days=(0, 1), hour=3) + overrides(days=(2, 3), hour=9)
                + overrides(days=(4, 7), hour=15))
        self.assertEqual(build(rows=rows), [])

    def test_a_pattern_spanning_the_weekend_offers_nothing(self):
        """"Whenever" is not a condition, and a weekday list this cannot
        name is not one either."""
        self.assertEqual(build(rows=overrides(days=(0, 1, 5, 6, 7))), [])

    def test_an_automation_this_file_does_not_hold_offers_nothing(self):
        self.assertEqual(build(rows=overrides(entity="automation.other")), [])

    def test_an_unreadable_automations_yaml_offers_nothing(self):
        self.assertEqual(build(config=None), [])


class TestTheRefusals(unittest.TestCase):
    """A refusal is carried and is never a card: every card on the
    Proposals tab can be answered, and none of these can."""

    def only(self, **kw):
        rows = build(**kw)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_an_automation_with_no_id_is_refused_by_name(self):
        config = {k: v for k, v in CONFIG.items() if k != "id"}
        row = self.only(config=config,
                        entity="automation.evening_lights")
        self.assertNotIn("config", row)
        self.assertIn("no `id`", row["refused"])
        self.assertIn("automation editor", row["refused"])

    def test_an_automation_that_already_stands_down_is_refused(self):
        config = dict(CONFIG, condition=[
            conditions.time_condition(21, 23, conditions.WEEKDAYS)])
        row = self.only(config=config)
        self.assertIn("already stands down", row["refused"])

    def test_an_unreadable_time_condition_is_refused_rather_than_ignored(self):
        config = dict(CONFIG, condition=[
            {"condition": "time", "after": "input_datetime.bedtime"}])
        row = self.only(config=config)
        self.assertIn("cannot read", row["refused"])

    def test_a_protected_target_is_refused(self):
        row = self.only(patterns=["light.lounge"])
        self.assertIn("protected", row["refused"])
        self.assertNotIn("config", row)

    def test_an_area_target_is_refused_while_the_list_is_set(self):
        config = dict(CONFIG, action=[
            {"service": "light.turn_on", "target": {"area_id": "lounge"}}])
        row = self.only(config=config, patterns=["lock.front"])
        self.assertIn("area", row["refused"])


class TestNothingHereWrites(unittest.TestCase):

    def test_the_module_touches_no_file_and_no_network(self):
        source = (BASE_DIR / "brain" / "panel" / "conditions.py").read_text()
        for forbidden in ("aiohttp", "requests", "open(", "write_text",
                          "atomic_write"):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":                    # pragma: no cover
    unittest.main()
