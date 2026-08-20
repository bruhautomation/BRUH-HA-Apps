#!/usr/bin/env python3
"""BRight's effect vocabulary: the catalog, selection, the beat grid, the
render, and the simulation the preview draws from.

The load-bearing claim in this module is that the picture and the packets
come from ONE render. Several tests below check exactly that — an effect's
actions are rendered once and then read twice — because a preview built
from a second implementation is a preview of the second implementation,
and it would look right while the room stayed dark.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from director import compiler, effects as fx  # noqa: E402
from lifx import packets  # noqa: E402


def lamps(count: int = 5) -> list[dict]:
    return [
        {"id": f"lifx-d073d500000{i}", "kind": "lifx",
         "serial": f"d073d500000{i}", "label": f"Lamp {i}", "role": "lamp",
         "zone": "lounge" if i < 3 else "kitchen",
         "x": round(i / max(1, count - 1), 3), "y": 0.5,
         "rtt": {"p50_ms": 6.0}}
        for i in range(count)
    ]


CANDLE = {"id": "lifx-d073d50000c1", "kind": "lifx", "serial": "d073d50000c1",
          "label": "Candle", "role": "candle", "zone": "lounge",
          "x": 0.5, "y": 0.1}
LASER = {"id": "switch.laser", "kind": "ha", "entity_id": "switch.laser",
         "label": "Laser", "role": "laser", "zone": "lounge",
         "x": 0.5, "y": 0.9}


def grid(bpm: float = 120.0, seconds: float = 16.0) -> fx.Grid:
    beat = 60.0 / bpm
    beats = [round(i * beat, 4) for i in range(int(seconds / beat) + 1)]
    return fx.Grid(beats, beats[::4], bpm)


PALETTE = [[200, 0.9], [300, 0.8], [40, 0.7]]


def render(effect: dict, fixtures=None, seconds: float = 16.0,
           **kwargs) -> list[dict]:
    return fx.actions_for(fx.clean_effect(effect), fixtures or lamps(),
                          grid(seconds=seconds), window=(0.0, seconds),
                          palette=PALETTE, **kwargs)


class TestTheCatalogIsTheWholeVocabulary(unittest.TestCase):
    def test_every_type_renders_and_every_renderer_has_a_type(self):
        """A catalog entry with no renderer validates and does nothing —
        the worst possible failure, because it looks like it worked."""
        self.assertEqual(set(fx.CATALOG), set(fx.RENDERERS))

    def test_every_type_produces_actions_for_a_normal_room(self):
        fixtures = lamps() + [CANDLE, LASER]
        for name in fx.CATALOG:
            with self.subTest(effect=name):
                actions = render({"type": name, "name": name}, fixtures)
                self.assertTrue(actions, f"{name} rendered nothing at all")
                for action in actions:
                    self.assertIn(action["kind"], ("set", "wave", "aux"))
                    self.assertGreaterEqual(action["t"], -1.0)

    def test_the_catalog_payload_describes_every_parameter(self):
        for spec in fx.catalog_payload():
            with self.subTest(effect=spec["type"]):
                self.assertTrue(spec["label"])
                self.assertTrue(spec["blurb"])
                self.assertIn(spec["channel"], ("light", "switch"))
                for param in spec["params"]:
                    self.assertIn("default", param)
                    self.assertIn(param["kind"],
                                  ("int", "number", "bool", "choice"))


class TestParametersAreForgiving(unittest.TestCase):
    """These files are meant to be typed by hand. A show that refuses to
    compile over `depth: 1.2` would be a worse tool than one that reads it
    as 1."""

    def test_out_of_range_is_clamped_not_rejected(self):
        effect = fx.clean_effect(
            {"type": "pulse", "params": {"depth": 9.0, "every_beats": -4}})
        self.assertEqual(1.0, effect["params"]["depth"])
        self.assertEqual(0.25, effect["params"]["every_beats"])

    def test_nonsense_becomes_the_default(self):
        effect = fx.clean_effect(
            {"type": "chase", "params": {"width": "lots", "bounce": "yes"}})
        self.assertEqual(1, effect["params"]["width"])
        self.assertIs(True, effect["params"]["bounce"])

    def test_missing_parameters_are_filled(self):
        effect = fx.clean_effect({"type": "sparkle"})
        self.assertEqual(set(fx.CATALOG["sparkle"]["params"]),
                         set(effect["params"]))

    def test_an_unknown_type_names_the_ones_that_exist(self):
        with self.assertRaises(fx.EffectError) as caught:
            fx.clean_effect({"type": "hyperdrive"})
        self.assertIn("chase", str(caught.exception))

    def test_an_effect_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(fx.EffectError):
            fx.clean_effect({"type": "wash", "start": 10, "end": 4})


class TestSelectionIsExplicitAndNarrow(unittest.TestCase):
    """Everything an effect does not name is left alone. That is the whole
    reason for building effects rather than scenes."""

    def test_an_empty_selection_means_every_light_it_can_drive(self):
        fixtures = lamps(3) + [LASER]
        chosen = fx.resolve_fixtures(fx.clean_effect({"type": "wash"}), fixtures)
        self.assertEqual(3, len(chosen))  # the laser is a switch, not a light

    def test_ids_select_exactly_those_lights(self):
        fixtures = lamps(5)
        effect = fx.clean_effect({
            "type": "chase",
            "select": {"ids": [fixtures[1]["id"], fixtures[3]["id"]]}})
        chosen = fx.resolve_fixtures(effect, fixtures)
        self.assertEqual([fixtures[1]["id"], fixtures[3]["id"]],
                         [f["id"] for f in chosen])

    def test_unselected_lights_get_no_actions_at_all(self):
        fixtures = lamps(5)
        actions = render({"type": "chase",
                          "select": {"ids": [fixtures[0]["id"]]}}, fixtures)
        touched = {a["fixture"]["id"] for a in actions}
        self.assertEqual({fixtures[0]["id"]}, touched)

    def test_zones_select_a_room(self):
        fixtures = lamps(5)
        effect = fx.clean_effect({"type": "wash",
                                  "select": {"zones": ["kitchen"]}})
        self.assertEqual({"kitchen"},
                         {f["zone"] for f in fx.resolve_fixtures(effect, fixtures)})

    def test_exclude_removes_one_light_from_a_role(self):
        fixtures = lamps(4)
        effect = fx.clean_effect({
            "type": "wash", "select": {"roles": ["lamp"],
                                       "exclude": [fixtures[0]["id"]]}})
        self.assertNotIn(fixtures[0]["id"],
                         {f["id"] for f in fx.resolve_fixtures(effect, fixtures)})

    def test_switches_and_lights_never_answer_each_others_effects(self):
        fixtures = lamps(2) + [LASER]
        self.assertEqual(
            ["switch.laser"],
            [f["id"] for f in fx.resolve_fixtures(
                fx.clean_effect({"type": "aux"}), fixtures)])
        self.assertNotIn(
            "switch.laser",
            {f["id"] for f in fx.resolve_fixtures(
                fx.clean_effect({"type": "strobe"}), fixtures)})


class TestRoleMannersAreTheDefaultAndAnOverride(unittest.TestCase):
    def test_a_candle_is_left_out_of_the_harsh_effects(self):
        fixtures = lamps(2) + [CANDLE]
        for harsh in ("strobe", "chase", "sparkle", "stab", "theater"):
            with self.subTest(effect=harsh):
                chosen = fx.resolve_fixtures(
                    fx.clean_effect({"type": harsh}), fixtures)
                self.assertNotIn(CANDLE["id"], {f["id"] for f in chosen})

    def test_an_effect_that_means_it_can_own_the_candle(self):
        fixtures = lamps(2) + [CANDLE]
        chosen = fx.resolve_fixtures(
            fx.clean_effect({"type": "strobe", "respect_roles": False}),
            fixtures)
        self.assertIn(CANDLE["id"], {f["id"] for f in chosen})

    def test_a_candle_stays_under_its_ceiling_when_manners_are_on(self):
        actions = render({"type": "wash", "params": {"brightness": 1.0}},
                         [CANDLE])
        self.assertTrue(actions)
        for action in actions:
            self.assertLessEqual(action["bri"], 0.45 + 1e-9)

    def test_the_ceiling_lifts_when_the_effect_owns_the_fixture(self):
        actions = render({"type": "wash", "respect_roles": False,
                          "params": {"brightness": 1.0}}, [CANDLE])
        self.assertAlmostEqual(1.0, max(a["bri"] for a in actions))


class TestOrderingReadsTheMap(unittest.TestCase):
    def test_x_runs_left_to_right_and_minus_x_the_other_way(self):
        fixtures = lamps(4)
        left = [f["id"] for f in fx.order_fixtures(fixtures, "x")]
        right = [f["id"] for f in fx.order_fixtures(fixtures, "-x")]
        self.assertEqual(left, list(reversed(right)))
        self.assertEqual(sorted(fixtures, key=lambda f: f["x"])[0]["id"],
                         left[0])

    def test_center_out_starts_in_the_middle(self):
        fixtures = lamps(5)
        first = fx.order_fixtures(fixtures, "center_out")[0]
        self.assertAlmostEqual(0.5, first["x"], places=3)

    def test_random_is_seeded_so_a_show_looks_the_same_twice(self):
        fixtures = lamps(6)
        self.assertEqual([f["id"] for f in fx.order_fixtures(fixtures, "random", 7)],
                         [f["id"] for f in fx.order_fixtures(fixtures, "random", 7)])

    def test_every_ordering_keeps_every_light(self):
        fixtures = lamps(6)
        for order in fx.ORDERS:
            with self.subTest(order=order):
                self.assertEqual(
                    {f["id"] for f in fixtures},
                    {f["id"] for f in fx.order_fixtures(fixtures, order)})

    def test_a_chase_lights_the_lights_in_that_order(self):
        fixtures = lamps(4)
        actions = [a for a in render(
            {"type": "chase", "order": "x",
             "params": {"step_beats": 1, "width": 1, "background": 0.0,
                        "brightness": 1.0}}, fixtures)
            if a["bri"] > 0.5]
        lit = [a["fixture"]["x"] for a in actions[:4]]
        self.assertEqual(sorted(lit), lit, f"the chase did not travel: {lit}")


class TestTheBeatGrid(unittest.TestCase):
    def test_steps_land_on_real_beats(self):
        g = grid(bpm=100)
        ticks = g.ticks(0.0, 8.0, 1, "beat")
        self.assertTrue(set(ticks).issubset(set(g.beats)))

    def test_a_half_beat_step_subdivides(self):
        g = grid(bpm=120)
        whole = g.ticks(0.0, 4.0, 1, "beat")
        half = g.ticks(0.0, 4.0, 0.5, "beat")
        self.assertGreater(len(half), len(whole))

    def test_downbeat_alignment_uses_the_downbeats(self):
        g = grid(bpm=120)
        ticks = g.ticks(0.0, 16.0, 1, "downbeat")
        self.assertTrue(set(ticks).issubset(set(g.downbeats)))

    def test_no_beats_still_produces_a_grid(self):
        """A preview on the bench has no track, and every stepping effect
        must work there or the preview is of something else."""
        ticks = fx.Grid([], [], 120).ticks(0.0, 4.0, 1, "time")
        self.assertGreater(len(ticks), 3)

    def test_stepping_is_capped(self):
        ticks = fx.Grid([], [], 240).ticks(0.0, 10000.0, 0.25, "time")
        self.assertLessEqual(len(ticks), fx.MAX_STEPS)


class TestOneRenderTwoConsumers(unittest.TestCase):
    """The preview and the packets are the same numbers, or the preview is
    a drawing of a different program."""

    def test_the_simulation_moves_when_the_effect_moves(self):
        fixtures = lamps(4)
        actions = render({"type": "chase", "params": {"step_beats": 1}},
                         fixtures)
        frames = fx.simulate(actions, fixtures, duration_s=8.0, fps=15)
        levels = [max(c[2] for c in frame) for frame in frames["frames"]]
        self.assertGreater(max(levels) - min(levels), 0.3,
                           "the preview shows no motion for a chase")

    def test_the_simulation_leaves_unselected_lights_alone(self):
        fixtures = lamps(4)
        actions = render({"type": "wash",
                          "select": {"ids": [fixtures[0]["id"]]}}, fixtures)
        frames = fx.simulate(actions, fixtures, duration_s=4.0, fps=10)
        untouched = {frame[2][2] for frame in frames["frames"]}
        self.assertEqual(1, len(untouched),
                         "a light nothing selected changed anyway")

    def test_a_frame_carries_one_colour_per_fixture(self):
        fixtures = lamps(3) + [CANDLE]
        actions = render({"type": "wash"}, fixtures)
        frames = fx.simulate(actions, fixtures, duration_s=2.0, fps=10)
        self.assertEqual(len(fixtures), len(frames["fixtures"]))
        for frame in frames["frames"]:
            self.assertEqual(len(fixtures), len(frame))

    def test_the_same_actions_become_packets(self):
        fixtures = lamps(3)
        actions = render({"type": "pulse"}, fixtures)
        out = compiler._Cues(source=7, ha_leads={})
        compiler.render_actions(actions, out)
        self.assertEqual(len(actions), len(out.cues))
        kinds = {packets.parse_header(
            __import__("base64").b64decode(cue["payload_b64"]))["type"]
            for cue in out.cues}
        self.assertEqual({packets.SET_WAVEFORM}, kinds)

    def test_waveform_shapes_reach_the_wire_as_themselves(self):
        for name, code in (("sine", packets.WAVEFORM_SINE),
                           ("pulse", packets.WAVEFORM_PULSE),
                           ("triangle", packets.WAVEFORM_TRIANGLE),
                           ("saw", packets.WAVEFORM_SAW),
                           ("half_sine", packets.WAVEFORM_HALF_SINE)):
            with self.subTest(shape=name):
                actions = render({"type": "pulse", "params": {"shape": name}},
                                 lamps(1))
                out = compiler._Cues(source=7, ha_leads={})
                compiler.render_actions(actions, out)
                import base64
                import struct
                payload = packets.parse_header(
                    base64.b64decode(out.cues[0]["payload_b64"]))["payload"]
                waveform = struct.unpack("<BBHHHHIfhB", payload)[9]
                self.assertEqual(code, waveform)


class TestTheAuxChannel(unittest.TestCase):
    def test_on_and_off_become_service_calls(self):
        for state, service in (("on", "homeassistant.turn_on"),
                               ("off", "homeassistant.turn_off")):
            with self.subTest(state=state):
                actions = render({"type": "aux", "params": {"state": state}},
                                 [LASER])
                out = compiler._Cues(source=1, ha_leads={"switch.laser": 280.0})
                compiler.render_actions(actions, out)
                self.assertEqual(service, out.cues[0]["service"])
                self.assertEqual(280.0, out.cues[0]["lead_ms"])

    def test_flash_turns_it_on_and_off_again(self):
        actions = render({"type": "aux", "params": {"state": "flash",
                                                    "flashes": 3}}, [LASER])
        self.assertTrue(any(a["on"] for a in actions))
        self.assertTrue(any(not a["on"] for a in actions))


class TestTheRateBudgetIsEnforcedOnEffectsToo(unittest.TestCase):
    def test_a_wild_effect_is_refused_with_the_reason(self):
        fixtures = lamps(2)
        analysis = {"hash": "ab" * 20, "bpm": 160,
                    "beats": [round(i * 0.375, 4) for i in range(200)],
                    "tags": {"duration": 60}}
        script = {
            "version": 2, "track_hash": "ab" * 20,
            "scenes": [{
                "start": 0.0, "end": 60.0, "kind": "peak", "palette": PALETTE,
                "brightness": 0.8,
                # Eight bars a second on two lights, three times over.
                "effects": [
                    {"type": "chase", "name": f"wild {i}",
                     "params": {"step_beats": 0.125}} for i in range(3)],
            }],
        }
        with self.assertRaises(compiler.CompileError) as caught:
            compiler.compile_show(script, fixtures, analysis, source=3)
        message = str(caught.exception)
        self.assertIn("msgs/s", message)
        self.assertIn("step_beats", message)


class TestPresetsAndParties(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from stores import effect_presets, parties
        self.presets = effect_presets
        self.parties = parties
        self._preset_file = effect_presets.PRESETS_FILE
        self._party_file = parties.PARTIES_FILE
        effect_presets.PRESETS_FILE = Path(self.tmp.name) / "presets.json"
        parties.PARTIES_FILE = Path(self.tmp.name) / "parties.json"

    def tearDown(self):
        self.presets.PRESETS_FILE = self._preset_file
        self.parties.PARTIES_FILE = self._party_file

    def test_a_preset_keeps_its_lights_as_well_as_its_settings(self):
        effect = fx.clean_effect({"type": "chase",
                                  "select": {"ids": ["lifx-d073d5000001"]}})
        self.presets.save("kitchen chase", effect)
        back = self.presets.get("kitchen chase")
        self.assertEqual(["lifx-d073d5000001"], back["effect"]["select"]["ids"])

    def test_saving_the_same_name_replaces_rather_than_duplicates(self):
        self.presets.save("one", fx.clean_effect({"type": "wash"}))
        self.presets.save("one", fx.clean_effect({"type": "chase"}))
        self.assertEqual(1, len(self.presets.load()))
        self.assertEqual("chase", self.presets.get("one")["effect"]["type"])

    def test_a_party_is_found_however_it_is_typed(self):
        self.parties.save({"name": "Saturday Night",
                           "media_player": "media_player.lounge"})
        self.assertIsNotNone(self.parties.get("saturday night"))
        self.assertIsNotNone(self.parties.get("  SATURDAY NIGHT "))

    def test_a_party_refuses_an_end_scene_that_is_not_a_scene(self):
        with self.assertRaises(ValueError):
            self.parties.save({"name": "Bad", "end_scene": "light.lounge"})

    def test_a_party_refuses_a_folder_outside_media(self):
        with self.assertRaises(ValueError):
            self.parties.save({"name": "Bad", "folder": "/config/music"})

    def test_no_fixtures_means_all_of_them(self):
        party = self.parties.save({"name": "Everything"})
        self.assertEqual([], party["fixtures"])


if __name__ == "__main__":
    unittest.main()
