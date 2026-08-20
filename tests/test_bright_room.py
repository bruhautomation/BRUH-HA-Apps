#!/usr/bin/env python3
"""What Claude is told about the room it is lighting.

The director used to be handed roles and x positions:

    FIXTURES (role: count, left-to-right x positions):
      lamp: 3 at x=[0.10, 0.50, 0.90]

Everything a designer needs beyond that was missing, and each absence had
a matching feature it silently disabled — no ids while `select.ids` was in
the schema, no y while four of the travel orders key on it, no zones while
`select.zones` and `order: "zone"` both do. A vocabulary the prompt does
not ground is one the model avoids or invents.

So these check the grounding rather than the wording: every light
nameable, every zone listed, every ordering total, and the derived orders
agreeing with what the compiler will actually do — because a prompt that
promises `order:"x"` will travel left to right and a compiler that
disagrees is worse than saying nothing.
"""

import os
import sys
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from director import effects as fx  # noqa: E402
from director import room  # noqa: E402

ROOM = [
    {"id": "lifx-aaa", "label": "Couch Lamp", "role": "lamp", "zone": "Living",
     "x": 0.10, "y": 0.30, "kind": "lifx"},
    {"id": "lifx-bbb", "label": "Door Lamp", "role": "lamp", "zone": "Living",
     "x": 0.90, "y": 0.35, "kind": "lifx"},
    {"id": "lifx-ccc", "label": "Shelf Strip", "role": "strip", "zone": "Living",
     "x": 0.50, "y": 0.80, "kind": "lifx"},
    {"id": "lifx-ddd", "label": "Mantel Candle", "role": "candle", "zone": "",
     "x": 0.30, "y": 0.10, "kind": "lifx"},
    {"id": "switch.laser", "label": "Laser", "role": "laser", "zone": "Kitchen",
     "x": 0.70, "y": 0.90, "kind": "ha", "entity_id": "switch.laser"},
]


class TestEveryLightIsNameable(unittest.TestCase):
    """`select.ids` was in the schema and unusable, because no id was ever
    shown. A model cannot name what it has not been told."""

    def test_every_id_and_name_appears(self):
        text = room.describe(ROOM)
        for fixture in ROOM:
            self.assertIn(fixture["id"], text)
            self.assertIn(fixture["label"], text)

    def test_both_coordinates_appear(self):
        """y was never sent, while `y`, `-y`, `snake` and `center_out` all
        key on it — four orders the model was asked to choose between
        blind."""
        text = room.describe(ROOM)
        self.assertIn("x=0.10", text)
        self.assertIn("y=0.30", text)

    def test_a_switch_says_it_is_a_switch(self):
        """A party light is not a dim bulb, and an effect that treats it as
        one is an effect that does nothing."""
        text = room.describe(ROOM)
        self.assertIn("switch", text.lower())
        self.assertIn("Home Assistant switch", text)

    def test_an_unreachable_light_is_marked(self):
        text = room.describe([{**ROOM[0], "reachable": False}])
        self.assertIn("NOT ANSWERING", text)

    def test_an_empty_map_says_so_rather_than_nothing(self):
        text = room.describe([])
        self.assertIn("no lights", text)
        self.assertIn("Light Map", text)


class TestZones(unittest.TestCase):
    """`select.zones` and `order: "zone"` both key on zones, and the prompt
    never said which existed."""

    def test_zones_are_listed_with_their_members(self):
        text = room.describe(ROOM)
        self.assertIn("Living", text)
        self.assertIn("Kitchen", text)
        self.assertIn("Couch Lamp", text)

    def test_an_unzoned_light_is_not_a_zone(self):
        """An empty zone is the absence of an answer. Offering it as a
        group would be offering "the ones I never got round to" as a room."""
        self.assertEqual(["Kitchen", "Living"], room.zones(ROOM))

    def test_no_zones_says_do_not_use_them(self):
        """Naming a vocabulary without grounding it is how a model invents
        a zone that matches nothing and drives no lights at all."""
        bare = [{**f, "zone": ""} for f in ROOM]
        text = room.describe(bare)
        self.assertIn("none defined", text)
        self.assertIn("do not use", text)

    def test_zones_are_stable_and_deduped(self):
        doubled = ROOM + [{**ROOM[0], "id": "lifx-eee", "zone": "living "}]
        self.assertEqual(sorted(set(room.zones(doubled))), room.zones(doubled))


class TestTheOrdersAgreeWithTheCompiler(unittest.TestCase):
    """The prompt states what each order will do. If the compiler disagrees,
    the prompt is a promise the show breaks — worse than saying nothing."""

    def _movers(self):
        return [f for f in ROOM if f["role"] not in ("laser", "party")]

    def test_x_order_matches_order_fixtures(self):
        promised = [f["label"] for f in
                    room._order_by(self._movers(), lambda f: f.get("x", 0.5))]
        actual = [f["label"] for f in
                  fx.order_fixtures(self._movers(), "x")]
        self.assertEqual(promised, actual)

    def test_y_order_matches_order_fixtures(self):
        promised = [f["label"] for f in
                    room._order_by(self._movers(), lambda f: f.get("y", 0.5))]
        actual = [f["label"] for f in
                  fx.order_fixtures(self._movers(), "y")]
        self.assertEqual(promised, actual)

    def test_the_nearest_neighbour_walk_is_total_and_stable(self):
        walk = room._nearest_neighbour(self._movers())
        self.assertEqual(len(self._movers()), len(walk))
        self.assertEqual({f["id"] for f in self._movers()},
                         {f["id"] for f in walk})
        self.assertEqual([f["id"] for f in walk],
                         [f["id"] for f in room._nearest_neighbour(self._movers())])

    def test_switches_are_left_out_of_travel_orders(self):
        """A switch cannot take a colour and cannot be part of a chase;
        listing it in a travel order invites an effect that skips a beat."""
        text = room.describe(ROOM)
        orders = text.split("TRAVEL ORDERS", 1)[1]
        self.assertNotIn("Laser", orders)

    def test_too_few_movers_is_called_out(self):
        """A chase across two bulbs is a flicker. The choreographer already
        knows that; the model has to be told."""
        text = room.describe(ROOM[:2])
        self.assertIn("flicker", text)


class TestTheCatalogIsNotCopied(unittest.TestCase):
    def test_role_notes_cover_every_role_the_map_allows(self):
        """A role with no note reads as a role with no purpose, and the
        drift is invisible until somebody adds one."""
        from stores import light_map
        for role in light_map.ROLES:
            self.assertIn(role, room.ROLE_NOTES, f"{role} has no note")


if __name__ == "__main__":
    unittest.main()
