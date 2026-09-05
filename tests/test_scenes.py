"""Four moods for a room, composed from the lights the room has.

Deterministic all the way through — the one Claude run names them — so
almost everything here is arithmetic over a fixture house, and each test
names the mutation it catches:

  `brightness`, not `_pct`   write the service field -> a scene's entity
                             dict is a STATE Home Assistant reproduces,
                             `light` reads `brightness`, and every light
                             comes on at whatever level it was already at
  colour temp before colour  prefer rgb -> an approximation of 2400K on a
                             bulb that could have taken the number
  an unreadable bulb         drop it -> a room of cheap bulbs is an empty
                             card instead of scenes that still work
  the night rule             leave everything on -> "night" is "evening"
  a protected light          include it -> a card offering something the
                             writer refuses, which is a wasted no
  one light                  offer anyway -> four ways of saying the same
                             thing
  the schedule's entity id   build it from the default names -> a
                             Claude-named set gives a schedule that turns
                             on nothing
  all four or none           offer the schedule early -> an automation
                             that errors at 07:00 every morning
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import scenes  # noqa: E402


def light(eid: str, name: str, area: str, modes=("color_temp",)):
    return {"entity_id": eid, "name": name, "area": area, "modes": modes}


def house(rows, extra_scenes=None) -> dict:
    """A snapshot with just what a `House` reads for a room."""
    states, entities, areas = {}, [], {}
    for i, row in enumerate(rows):
        attrs = {"friendly_name": row["name"]}
        if row["modes"] is not None:
            attrs["supported_color_modes"] = list(row["modes"])
        states[row["entity_id"]] = {"state": "on", "attributes": attrs}
        area_id = row["area"].lower().replace(" ", "_")
        areas[area_id] = row["area"]
        entities.append({"entity_id": row["entity_id"], "area_id": area_id,
                         "platform": "light", "unique_id": f"u{i}"})
    return {
        "states": states,
        "entities": entities,
        "devices": [],
        "areas": [{"area_id": k, "name": v} for k, v in areas.items()],
        "services": ["light.turn_on", "scene.turn_on"],
        "scenes": extra_scenes if extra_scenes is not None else [],
        "automations": [],
    }


LOUNGE = [
    light("light.lounge_main", "Lounge main", "Living room", ("color_temp",)),
    light("light.lounge_strip", "Lounge strip", "Living room", ("hs",)),
    light("light.lounge_lamp", "Lounge lamp", "Living room", ("brightness",)),
    light("light.lounge_plug", "Lounge plug", "Living room", ("onoff",)),
    light("light.lounge_night", "Lounge nightlight", "Living room",
          ("color_temp",)),
]


class TestWhatABulbCanBeTold(unittest.TestCase):

    def test_colour_temperature_is_preferred_over_colour(self):
        """A scene of whites is a colour-temperature scene, and kelvin is
        the control that says so — an RGB approximation of 2400K on a bulb
        that could have taken the number is a worse answer."""
        self.assertEqual(scenes.capability(
            {"attributes": {"supported_color_modes": ["hs", "color_temp"]}}),
            "colour_temp")

    def test_a_colour_only_bulb_gets_colour(self):
        for mode in ("hs", "xy", "rgb", "rgbw", "rgbww"):
            self.assertEqual(scenes.capability(
                {"attributes": {"supported_color_modes": [mode]}}),
                "colour", mode)

    def test_a_dimmable_bulb_gets_brightness(self):
        self.assertEqual(scenes.capability(
            {"attributes": {"supported_color_modes": ["brightness"]}}),
            "brightness")

    def test_an_unreadable_bulb_falls_to_on_off_rather_than_being_dropped(self):
        """"I could not tell" is an answer, and the honest thing to do with
        it is the setting that works on every bulb ever made."""
        for state in ({}, {"attributes": {}}, None,
                      {"attributes": {"supported_color_modes": None}},
                      {"attributes": {"supported_color_modes": ["unknown"]}}):
            self.assertEqual(scenes.capability(state), "onoff", state)


class TestTheColourItself(unittest.TestCase):

    def test_warm_is_warmer_than_cool(self):
        warm, cool = scenes.kelvin_to_rgb(2000), scenes.kelvin_to_rgb(5000)
        self.assertEqual(warm[0], 255)
        self.assertLess(warm[2], cool[2], "2000K is bluer than 5000K")

    def test_every_channel_stays_in_range(self):
        for k in (1000, 1800, 2400, 4000, 5000, 6500, 40000, 99999):
            rgb = scenes.kelvin_to_rgb(k)
            self.assertEqual(len(rgb), 3)
            for c in rgb:
                self.assertTrue(0 <= c <= 255, (k, rgb))

    def test_hsv_is_what_the_card_gets(self):
        h, s, v = scenes.rgb_to_hsv((255, 155, 61))
        self.assertTrue(0 <= h < 360)
        self.assertTrue(0 <= s <= 1)
        self.assertEqual(v, 1.0)


class TestComposing(unittest.TestCase):

    def build(self, rows=None, patterns=None, names=None, area="Living room"):
        return scenes.build(house(rows or LOUNGE), area, patterns, names)

    def entities(self, obj, mood):
        i = scenes.MOODS.index(mood)
        return obj["config"][i]["entities"]

    def test_four_scenes_in_the_order_a_day_happens(self):
        obj = self.build()
        self.assertEqual(len(obj["config"]), 4)
        self.assertEqual([e["mood"] for e in obj["scene"]["preview"]],
                         list(scenes.MOODS))
        for entry in obj["config"]:
            self.assertNotIn("mood", entry, "the card's key reached the file")

    def test_the_level_is_brightness_not_brightness_pct(self):
        """A scene's entity dict is a STATE Home Assistant reproduces, and
        `light`'s reproduce_state reads `brightness` (0-255).
        `brightness_pct` is a service field: it would store, load, reload
        and apply, and every light would come on where it already was."""
        row = self.entities(self.build(), "evening")["light.lounge_main"]
        self.assertIn("brightness", row)
        self.assertNotIn("brightness_pct", row)
        self.assertTrue(1 <= row["brightness"] <= 255)
        self.assertEqual(row["brightness"],
                         round(scenes.LEVELS["evening"]["pct"] * 255 / 100))

    def test_each_capability_gets_what_it_can_take_and_nothing_else(self):
        day = self.entities(self.build(), "day")
        self.assertIn("color_temp_kelvin", day["light.lounge_main"])
        self.assertNotIn("rgb_color", day["light.lounge_main"])
        self.assertIn("rgb_color", day["light.lounge_strip"])
        self.assertNotIn("color_temp_kelvin", day["light.lounge_strip"])
        self.assertEqual(set(day["light.lounge_lamp"]), {"state", "brightness"})
        self.assertEqual(day["light.lounge_plug"], {"state": "on"})

    def test_morning_is_cooler_than_evening_and_brighter(self):
        morning = self.entities(self.build(), "morning")["light.lounge_main"]
        evening = self.entities(self.build(), "evening")["light.lounge_main"]
        self.assertGreater(morning["color_temp_kelvin"],
                           evening["color_temp_kelvin"])
        self.assertGreater(morning["brightness"], evening["brightness"])

    def test_night_leaves_only_the_nightlight_on(self):
        night = self.entities(self.build(), "night")
        self.assertEqual(night["light.lounge_night"]["state"], "on")
        for eid in ("light.lounge_main", "light.lounge_strip",
                    "light.lounge_lamp", "light.lounge_plug"):
            self.assertEqual(night[eid], {"state": "off"}, eid)

    def test_a_room_with_no_nightlight_goes_dark_at_night(self):
        rows = [r for r in LOUNGE if "night" not in r["entity_id"]]
        night = self.entities(self.build(rows), "night")
        self.assertTrue(all(v == {"state": "off"} for v in night.values()))

    def test_the_night_word_is_a_whole_word(self):
        self.assertTrue(scenes.is_nightlight("Hall lamp"))
        self.assertTrue(scenes.is_nightlight("Bedside light"))
        self.assertFalse(scenes.is_nightlight("Overnight oats warmer"))
        self.assertFalse(scenes.is_nightlight("Kitchen"))

    def test_a_protected_light_is_skipped_and_named(self):
        obj = self.build(patterns=["light.lounge_strip"])
        self.assertNotIn("light.lounge_strip",
                         self.entities(obj, "day"))
        skipped = obj["scene"]["skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["entity_id"], "light.lounge_strip")
        self.assertIn("Lounge strip", obj["why"])
        self.assertIn("protected", obj["why"])

    def test_claude_s_names_reach_the_scene_names(self):
        obj = self.build(names={"morning": "Sunday morning", "day": "Bright",
                                "evening": "Wind down", "night": "Small hours"})
        self.assertEqual(obj["config"][0]["name"], "Sunday morning — Living room")
        self.assertEqual(obj["config"][3]["name"], "Small hours — Living room")

    def test_the_plain_names_are_the_fallback(self):
        obj = self.build()
        self.assertEqual(obj["config"][0]["name"], "Morning — Living room")

    def test_the_ids_carry_the_prefix_and_the_room(self):
        for entry in self.build()["config"]:
            self.assertTrue(entry["id"].startswith(
                f"{scenes.ID_PREFIX}living_room_"), entry["id"])

    def test_the_why_says_what_the_room_can_do(self):
        why = self.build()["why"]
        self.assertIn("5 lights", why)
        self.assertIn("take a colour temperature", why)
        self.assertIn("only switch on and off", why)
        self.assertIn("Lounge nightlight", why)


class TestTheSwatches(unittest.TestCase):

    def test_there_is_one_per_light_per_mood(self):
        obj = scenes.build(house(LOUNGE), "Living room")
        preview = obj["scene"]["preview"]
        self.assertEqual(len(preview), 4)
        for mood in preview:
            self.assertEqual(len(mood["lights"]), len(LOUNGE))
            for light_row in mood["lights"]:
                self.assertIn("h", light_row)
                self.assertIn("s", light_row)
                self.assertIn("v", light_row)
                self.assertIn("capability", light_row)
                self.assertIn("name", light_row)

    def test_a_light_that_is_off_says_so_rather_than_drawing_black(self):
        obj = scenes.build(house(LOUNGE), "Living room")
        night = obj["scene"]["preview"][3]
        off = [light_row for light_row in night["lights"]
               if not light_row["on"]]
        self.assertEqual(len(off), len(LOUNGE) - 1)
        self.assertTrue(all(r["v"] == 0.0 for r in off))

    def test_an_on_off_bulb_draws_no_warmth_it_will_not_have(self):
        obj = scenes.build(house(LOUNGE), "Living room")
        row = next(r for r in obj["scene"]["preview"][1]["lights"]
                   if r["entity_id"] == "light.lounge_plug")
        self.assertEqual(row["s"], 0.0)
        self.assertEqual(row["capability"], "onoff")

    def test_a_dimmable_bulb_draws_its_level_and_no_colour(self):
        obj = scenes.build(house(LOUNGE), "Living room")
        row = next(r for r in obj["scene"]["preview"][2]["lights"]
                   if r["entity_id"] == "light.lounge_lamp")
        self.assertEqual(row["s"], 0.0)
        self.assertAlmostEqual(row["v"], scenes.LEVELS["evening"]["pct"] / 100)


class TestTheRefusals(unittest.TestCase):

    def test_a_room_with_one_light_is_refused(self):
        obj = scenes.build(house(LOUNGE[:1]), "Living room")
        self.assertIn("refused", obj)
        self.assertNotIn("config", obj)
        self.assertIn("one light", obj["refused"])

    def test_a_room_with_none_says_so_differently(self):
        obj = scenes.build(house(LOUNGE), "Cellar")
        self.assertIn("no lights", obj["refused"])

    def test_a_room_left_with_one_by_the_protected_list_says_which(self):
        obj = scenes.build(house(LOUNGE[:2]), "Living room",
                           ["light.lounge_strip"])
        self.assertIn("refused", obj)
        self.assertIn("protected", obj["refused"])

    def test_a_floor_rather_than_a_room_is_refused(self):
        rows = [light(f"light.x{i}", f"Light {i}", "Everywhere")
                for i in range(scenes.MAX_LIGHTS + 1)]
        obj = scenes.build(house(rows), "Everywhere")
        self.assertIn("floor rather than a room", obj["refused"])

    def test_the_picker_never_offers_a_room_the_rule_forbids(self):
        rows = LOUNGE + [light("light.box", "Box room bulb", "Box room")]
        offered = scenes.areas_with_lights(house(rows))
        self.assertEqual([a["area"] for a in offered], ["Living room"])
        self.assertEqual(offered[0]["lights"], len(LOUNGE))

    def test_the_picker_counts_what_is_left_after_the_protected_list(self):
        offered = scenes.areas_with_lights(
            house(LOUNGE), ["light.lounge_strip", "light.lounge_plug"])
        self.assertEqual(offered[0]["lights"], len(LOUNGE) - 2)
        self.assertEqual(offered[0]["skipped"], 2)


class TestNamingThem(unittest.TestCase):

    def test_four_clean_lines(self):
        self.assertEqual(
            scenes.read_names("Sunday morning\nBright\nWind down\nSmall hours"),
            {"morning": "Sunday morning", "day": "Bright",
             "evening": "Wind down", "night": "Small hours"})

    def test_numbering_and_quotes_are_stripped_rather_than_refused(self):
        out = scenes.read_names('1. "Sunrise"\n2. Bright\n- Dusk\n* Night owl')
        self.assertEqual(out["morning"], "Sunrise")
        self.assertEqual(out["night"], "Night owl")

    def test_all_four_or_none(self):
        """Three good names and a fourth that came back as "4." is a set
        with a hole in it, and the plain names are a good answer."""
        self.assertEqual(scenes.read_names("One\nTwo\nThree"), {})
        self.assertEqual(scenes.read_names("One\nTwo\nThree\nFour\nFive"), {})
        self.assertEqual(scenes.read_names(""), {})
        self.assertEqual(scenes.read_names(None), {})


class TestTheSchedule(unittest.TestCase):

    def written(self, names=None, moods=scenes.MOODS):
        names = names or scenes.DEFAULT_NAMES
        return [{"id": f"{scenes.ID_PREFIX}living_room_{m}",
                 "name": f"{names[m]} — Living room"} for m in moods]

    def test_nothing_is_offered_until_all_four_scenes_exist(self):
        for moods in ((), ("morning",), ("morning", "day", "evening")):
            snap = house(LOUNGE, self.written(moods=moods))
            self.assertIsNone(
                scenes.schedule(snap, "Living room", 7 * 60, 22 * 60), moods)

    def test_it_names_the_entity_home_assistant_really_has(self):
        """The mutation: build the id from DEFAULT_NAMES. A Claude-named
        set then gives a schedule that turns on nothing."""
        names = {"morning": "Sunrise", "day": "Bright",
                 "evening": "Wind down", "night": "Small hours"}
        snap = house(LOUNGE, self.written(names))
        obj = scenes.schedule(snap, "Living room", 7 * 60, 22 * 60)
        targets = [b["sequence"][0]["target"]["entity_id"]
                   for b in obj["config"]["action"][0]["choose"]]
        self.assertEqual(targets[0], "scene.sunrise_living_room")
        self.assertEqual(targets[3], "scene.small_hours_living_room")

    def test_the_measured_hours_are_the_measured_ones(self):
        snap = house(LOUNGE, self.written())
        obj = scenes.schedule(snap, "Living room", 6 * 60 + 40, 23 * 60 + 15)
        times = [t["at"] for t in obj["config"]["trigger"]]
        self.assertEqual(times[0], "06:40:00")
        self.assertEqual(times[3], "23:15:00")
        self.assertEqual(obj["schedule"]["measured"], ["morning", "night"])
        self.assertIn("measured", obj["why"])

    def test_with_no_measurement_it_says_they_are_defaults(self):
        snap = house(LOUNGE, self.written())
        obj = scenes.schedule(snap, "Living room", None, None)
        self.assertEqual(obj["schedule"]["measured"], [])
        self.assertIn("has not measured enough days", obj["why"])
        self.assertEqual(obj["config"]["trigger"][0]["at"], "07:00:00")

    def test_the_middle_two_are_stated_as_the_guesses_they_are(self):
        snap = house(LOUNGE, self.written())
        obj = scenes.schedule(snap, "Living room", 7 * 60, 22 * 60)
        self.assertEqual(obj["schedule"]["times"]["day"], scenes.FIXED["day"])
        self.assertIn("fixed guesses", obj["why"])

    def test_it_is_an_ordinary_automation_so_the_1_44_path_takes_it(self):
        import shadow

        snap = house(LOUNGE, self.written())
        config = scenes.schedule(snap, "Living room", 7 * 60, 22 * 60)["config"]
        # Replayable, so it gets a replay and a trial week like any other.
        self.assertEqual(len(shadow.check_replayable(config)), 4)
        # And `would_do` finds the calls inside the `choose`, which is what
        # the protected check reads.
        calls = shadow.would_do(config)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c["service"] == "scene.turn_on" for c in calls))


class TestItIsNotBRight(unittest.TestCase):
    """A different idea with a different name. Describing this as BRight
    for every day would tell somebody it needs LIFX bulbs and a speaker."""

    def test_nothing_it_SAYS_borrows_the_other_add_on_s_vocabulary(self):
        """The module docstring names BRight once, to say they are not the
        same thing. What matters is that nothing it *emits* — the prompt,
        the names, the sentence on the card — reads as a light show."""
        obj = scenes.build(house(LOUNGE), "Living room")
        said = " ".join([
            scenes.SYSTEM, scenes.name_prompt("Living room"),
            obj["why"], obj["title"],
            " ".join(scenes.DEFAULT_NAMES.values()),
            " ".join(e["name"] for e in obj["config"]),
        ]).lower()
        # Distinctive terms only: "bright" is an ordinary word about
        # lighting and *"cool and bright"* is exactly the right sentence
        # for a morning scene. What must not appear is the other add-on's
        # machinery, which would tell somebody this needs LIFX bulbs.
        for word in ("lifx", "choreograph", "waveform", "light show",
                     "cue list", "party mode", "the director"):
            self.assertNotIn(word, said, word)


if __name__ == "__main__":                    # pragma: no cover
    unittest.main()
