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


def grid(bpm: float = 120.0, seconds: float = 16.0,
         music: bool = True) -> fx.Grid:
    """The bench song. It carries a melody and a chord progression by
    default because a real track does — `music=False` is the track
    analysed before BRight could hear either, which is its own case and
    is tested as one."""
    beat = 60.0 / bpm
    beats = [round(i * beat, 4) for i in range(int(seconds / beat) + 1)]
    # A backbeat: kick on 1 and 3, snare on 2 and 4. `hits` rides with
    # the melody rather than with the beats because it is the same claim
    # — this is a track a current analyzer heard — and `music=False` is
    # the older analysis that has none of it.
    hits = [{"t": beats[i], "strength": 0.95 if i % 2 == 0 else 0.7,
             "band": "low" if i % 2 == 0 else "mid",
             "tone": 0.8 if i % 2 == 0 else 0.3, "on_beat": True}
            for i in range(len(beats))]
    if not music:
        return fx.Grid(beats, beats[::4], bpm)
    scale = (0, 2, 4, 5, 7, 9, 11, 12)
    notes = [{"t": round(i * beat / 2, 4), "d": round(beat / 2, 4),
              "m": 60 + scale[i % len(scale)],
              "pc": (60 + scale[i % len(scale)]) % 12, "s": 0.9}
             for i in range(int(seconds / (beat / 2)))]
    chords = [{"t": round(i * beat * 4, 4), "name": "C", "root": i * 5 % 12,
               "quality": "maj" if i % 2 else "min", "confidence": 0.9}
              for i in range(int(seconds / (beat * 4)) + 1)]
    # A stand-in loudness envelope at the analyzer's own 20Hz: two bars
    # of swell and fall, so `level` has a shape to follow on the bench.
    hop = 0.05
    frames = int(seconds / hop) + 1
    swell = [round(0.25 + 0.7 * abs(((i * hop / (beat * 4)) % 1.0) - 0.5) * 2, 3)
             for i in range(frames)]
    energy = {"hop_s": hop, "energy": swell, "low": swell,
              "mid": swell, "high": swell}
    return fx.Grid(beats, beats[::4], bpm, notes=notes, chords=chords,
                   energy=energy, hits=hits)


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



class TestLightsWithAnAttack(unittest.TestCase):
    """The difference between a light show and mood lighting.

    Every rhythmic effect BRight had was a SWELL: a sine travelling from
    the bulb's current level up to a target and back. Two things follow
    from that and both are audible from a sofa — the brightest instant
    lands halfway to the next beat rather than on it, and the motion has
    no attack, which is what "just a bunch of fading lights" describes.
    """

    def _levels(self, effect, seconds=8.0, fps=30, base=0.5):
        fixture = lamps(1)
        actions = fx.actions_for(fx.clean_effect(effect), fixture,
                                 grid(seconds=seconds), window=(0.0, seconds),
                                 palette=PALETTE, base_brightness=base)
        sim = fx.simulate(actions, fixture, duration_s=seconds, fps=fps)
        # The simulator clamps its own frame rate — it is a preview, not
        # a sampler — so the rate to index frames by is the one it used,
        # never the one that was asked for.
        return [frame[0][2] for frame in sim["frames"]], sim["fps"]

    def test_the_beat_pulse_is_brightest_on_the_beat(self):
        levels, fps = self._levels(
            {"type": "pulse", "name": "beat",
             "params": {"every_beats": 1, "depth": 0.4, "cycles_per_cue": 4}})
        beat_s = 0.5  # 120bpm
        for beat in (4, 5, 6, 7, 8):
            on = levels[int(beat * beat_s * fps)]
            off = levels[int((beat + 0.5) * beat_s * fps)]
            self.assertGreater(
                on, off + 0.15,
                f"beat {beat}: the room is at {on:.2f} on the beat and "
                f"{off:.2f} between beats — the pulse is inverted")

    def test_a_hit_strikes_and_decays_rather_than_swelling(self):
        levels, fps = self._levels(
            {"type": "hit", "name": "kick",
             "params": {"every_beats": 1, "peak": 1.0, "floor": 0.1,
                        "cycles_per_cue": 4}})
        beat_s = 0.5
        for beat in (4, 5, 6):
            start = int(beat * beat_s * fps)
            quarter = int((beat + 0.25) * beat_s * fps)
            late = int((beat + 0.9) * beat_s * fps)
            self.assertGreater(levels[start], levels[quarter],
                               "a hit is brightest the instant it lands")
            self.assertGreater(levels[quarter], levels[late],
                               "and keeps falling until the next one")

    def test_a_hit_covers_more_of_the_range_than_a_swell_of_the_same_depth(self):
        """The measurement that started this: count how many distinct
        levels the room actually visits."""
        swell, _ = self._levels(
            {"type": "pulse", "name": "swell",
             "params": {"every_beats": 1, "depth": 0.9, "cycles_per_cue": 4,
                        "shape": "sine"}}, base=0.05)
        strike, _ = self._levels(
            {"type": "hit", "name": "strike",
             "params": {"every_beats": 1, "peak": 0.95, "floor": 0.05,
                        "cycles_per_cue": 4}})
        self.assertGreater(max(strike) - min(strike), 0.6)
        # And the shape differs where it matters: a swell is symmetric
        # about its peak, a strike is not.
        self.assertGreater(max(swell), 0.6)

    def test_an_accent_lands_on_the_analyzed_hits_not_on_a_grid(self):
        actions = render({"type": "accent", "name": "drums",
                          "params": {"min_strength": 0.0, "min_gap_beats": 0}},
                         lamps(1))
        beat = 0.5
        hit_times = {round(i * beat, 3) for i in range(33)}
        self.assertTrue(actions)
        for action in actions:
            self.assertIn(round(action["t"], 3), hit_times)

    def test_an_accent_can_take_the_kick_and_leave_the_snare(self):
        kick = render({"type": "accent", "name": "k",
                       "params": {"band": "low", "min_strength": 0.0,
                                  "min_gap_beats": 0}}, lamps(1))
        snare = render({"type": "accent", "name": "s",
                        "params": {"band": "mid", "min_strength": 0.0,
                                   "min_gap_beats": 0}}, lamps(1))
        kick_times = {round(a["t"], 3) for a in kick}
        snare_times = {round(a["t"], 3) for a in snare}
        self.assertTrue(kick_times and snare_times)
        self.assertEqual(set(), kick_times & snare_times,
                         "the kick and the snare are different instruments "
                         "and must be able to drive different lights")

    def test_a_quiet_hit_is_dimmer_than_a_loud_one(self):
        actions = render({"type": "accent", "name": "a",
                          "params": {"min_strength": 0.0, "min_gap_beats": 0,
                                     "follow_strength": True}}, lamps(1))
        peaks = [a["bri"] for a in actions if a["kind"] == "set"]
        self.assertGreater(max(peaks), min(peaks),
                           "the analyzer ranked these hits and the room "
                           "should say so")

    def test_an_accent_thins_a_cluster_to_its_strongest(self):
        dense = render({"type": "accent", "name": "a",
                        "params": {"min_strength": 0.0, "min_gap_beats": 0}},
                       lamps(1))
        thinned = render({"type": "accent", "name": "a",
                          "params": {"min_strength": 0.0, "min_gap_beats": 2}},
                         lamps(1))
        self.assertLess(len(thinned), len(dense))

    def test_an_older_analysis_renders_nothing_rather_than_something_wrong(self):
        actions = fx.actions_for(
            fx.clean_effect({"type": "accent", "name": "a"}), lamps(1),
            grid(music=False), window=(0.0, 16.0), palette=PALETTE)
        self.assertEqual([], actions)
        self.assertIn("accent", fx.NEEDS_HITS)

    def test_a_hit_before_the_song_starts_is_dropped_never_clamped(self):
        """Clamping would move the peak off the beat, quietly, for the
        one cue nobody is watching for."""
        actions = render({"type": "pulse", "name": "p",
                          "params": {"every_beats": 1, "cycles_per_cue": 8}},
                         lamps(1))
        self.assertTrue(all(a["t"] >= 0 for a in actions))
        self.assertTrue(actions)


class TestEveryShapeKnowsWhereItPeaks(unittest.TestCase):
    def test_the_table_covers_every_shape_the_vocabulary_offers(self):
        self.assertEqual(set(fx.SHAPES), set(fx.PEAK_PHASE))

    def test_the_table_agrees_with_the_simulator(self):
        """Two answers to "where is this waveform brightest" is one
        answer too many — and the simulator is what the preview draws."""
        for shape in fx.SHAPES:
            with self.subTest(shape=shape):
                samples = [(phase / 200.0,
                            fx._wave_position(shape, phase / 200.0, 0.5))
                           for phase in range(200)]
                brightest = max(samples, key=lambda pair: pair[1])[0]
                expected = fx.PEAK_PHASE[shape]
                # saw peaks at the very end of its cycle, which sampling
                # inside [0, 1) reaches as 0.995.
                self.assertAlmostEqual(
                    expected, brightest if expected < 1.0 else 1.0,
                    delta=0.02,
                    msg=f"{shape} peaks at {brightest}, table says {expected}")


if __name__ == "__main__":
    unittest.main()


class TestTheEffectsThatFollowTheMusic(unittest.TestCase):
    """`melody` and `harmony` — the two that answer what is being played
    rather than when it hits."""

    def test_melody_puts_one_note_on_one_light_at_a_time(self):
        actions = render({"type": "melody", "name": "tune",
                          "params": {"voices": 1}})
        self.assertTrue(actions)
        times = sorted({a["t"] for a in actions})
        self.assertGreater(len(times), 8, "the tune barely moved")
        # One voice means one fixture lit per note.
        per_time = {}
        for action in actions:
            per_time.setdefault(action["t"], set()).add(action["fixture"]["id"])
        self.assertTrue(all(len(v) == 1 for v in per_time.values()))

    def test_melody_walks_across_the_room(self):
        """A rising line has to travel — a melody effect that put every
        note on the same bulb would be a pulse with extra steps."""
        actions = render({"type": "melody", "name": "tune",
                          "params": {"voices": 1}})
        used = {a["fixture"]["id"] for a in actions}
        self.assertGreater(len(used), 1)

    def test_a_notes_pitch_picks_its_colour(self):
        """The same pitch class is always the same colour, so a phrase
        that returns home looks like it did."""
        actions = render({"type": "melody", "name": "tune",
                          "params": {"hue_spread": 1.0, "voices": 1}})
        by_pitch = {}
        for action, note in zip(actions, grid().notes):
            by_pitch.setdefault(note["pc"], set()).add(round(action["hue"], 3))
        repeated = {pc: hues for pc, hues in by_pitch.items() if len(hues) > 1}
        self.assertFalse(repeated, f"one pitch class, two colours: {repeated}")

    def test_hue_spread_zero_keeps_the_scene_colour(self):
        """Following the tune in brightness only, without a second
        parameter to mean it."""
        actions = render({"type": "melody", "name": "tune",
                          "params": {"hue_spread": 0.0}})
        hues = {round(a["hue"], 3) for a in actions}
        self.assertEqual(1, len(hues), f"expected one colour, got {hues}")

    def test_a_quiet_note_is_dimmer_than_a_loud_one(self):
        loud = {"t": 0.5, "d": 0.4, "m": 60, "pc": 0, "s": 1.0}
        soft = {"t": 1.5, "d": 0.4, "m": 60, "pc": 0, "s": 0.3}
        bench = fx.Grid([0.0, 0.5, 1.0, 1.5, 2.0], [0.0], 120.0,
                        notes=[loud, soft])
        actions = fx.actions_for(
            fx.clean_effect({"type": "melody", "name": "t",
                             "params": {"min_strength": 0.0}}),
            lamps(), bench, window=(0.0, 4.0), palette=PALETTE)
        levels = {a["t"]: a["bri"] for a in actions}
        self.assertGreater(levels[0.5], levels[1.5])

    def test_min_strength_drops_the_notes_under_it(self):
        actions = render({"type": "melody", "name": "tune",
                          "params": {"min_strength": 0.99}})
        self.assertEqual([], actions)

    def test_harmony_changes_the_room_when_the_chord_changes(self):
        actions = render({"type": "harmony", "name": "chords"})
        self.assertTrue(actions)
        times = sorted({a["t"] for a in actions})
        # The bench progression changes every four beats (2s at 120bpm).
        self.assertGreater(len(times), 1)
        for first, second in zip(times, times[1:]):
            self.assertGreaterEqual(round(second - first, 3), 1.9)

    def test_harmony_covers_the_whole_selection_on_every_change(self):
        cast = lamps()
        actions = render({"type": "harmony", "name": "chords"}, cast)
        by_time = {}
        for action in actions:
            by_time.setdefault(action["t"], set()).add(action["fixture"]["id"])
        for lit in by_time.values():
            self.assertEqual(len(cast), len(lit))

    def test_a_scene_that_opens_mid_chord_still_has_a_colour(self):
        """Starting black until the next change would be reading the
        list rather than the music."""
        bench = grid(seconds=16.0)
        actions = fx.actions_for(
            fx.clean_effect({"type": "harmony", "name": "c"}), lamps(),
            bench, window=(3.0, 7.0), palette=PALETTE)
        self.assertTrue(actions)
        self.assertAlmostEqual(3.0, min(a["t"] for a in actions), places=3)

    def test_minor_and_major_are_different_colours(self):
        minor = {"t": 0.0, "name": "Am", "root": 9, "quality": "min"}
        major = {"t": 4.0, "name": "A", "root": 9, "quality": "maj"}
        bench = fx.Grid([0.0, 1.0, 2.0, 3.0, 4.0], [0.0], 120.0,
                        chords=[minor, major])
        actions = fx.actions_for(
            fx.clean_effect({"type": "harmony", "name": "c",
                             "params": {"minor_shift": -40}}),
            lamps(), bench, window=(0.0, 8.0), palette=PALETTE)
        hues = {a["t"]: a["hue"] for a in actions}
        self.assertNotEqual(hues[0.0], hues[4.0],
                            "the same root, major and minor, one colour")

    def test_both_render_nothing_when_the_track_has_no_music(self):
        """A track analysed before BRight could hear melody or harmony.
        Silence is correct — and the compiler is what says why."""
        silent = grid(music=False)
        for name in ("melody", "harmony"):
            with self.subTest(effect=name):
                actions = fx.actions_for(
                    fx.clean_effect({"type": name, "name": name}), lamps(),
                    silent, window=(0.0, 16.0), palette=PALETTE)
                self.assertEqual([], actions)
        self.assertFalse(silent.has_music)
        self.assertTrue(grid().has_music)

    def test_a_busy_line_cannot_flood_the_wire(self):
        many = [{"t": round(i * 0.02, 3), "d": 0.02, "m": 60 + i % 12,
                 "pc": (60 + i % 12) % 12, "s": 0.9} for i in range(4000)]
        bench = fx.Grid([0.0, 0.5], [0.0], 120.0, notes=many)
        kept = bench.notes_in(0.0, 100.0)
        self.assertLessEqual(len(kept), fx.MAX_STEPS)
        self.assertEqual(sorted(kept, key=lambda n: n["t"]), kept,
                         "the cap reordered the tune")


class TestRoleMannersCoverTheMusicalEffects(unittest.TestCase):
    """A candle is ambience: "Glows and drifts. Never strobes." A melody
    note lands every few hundred milliseconds — musical, and still a
    flicker. Harmony is the opposite and keeps its candles."""

    def test_a_candle_is_not_asked_to_follow_the_tune(self):
        fixtures = lamps(2) + [CANDLE]
        actions = render({"type": "melody", "name": "tune"}, fixtures)
        self.assertTrue(actions)
        touched = {a["fixture"]["role"] for a in actions}
        self.assertNotIn("candle", touched)

    def test_a_candle_does_follow_the_chords(self):
        fixtures = lamps(2) + [CANDLE]
        actions = render({"type": "harmony", "name": "chords"}, fixtures)
        touched = {a["fixture"]["role"] for a in actions}
        self.assertIn("candle", touched)

    def test_an_effect_that_means_it_can_still_own_the_candle(self):
        """`respect_roles: false` is the override, same as every other
        harsh effect — the rule is a default, not a wall."""
        fixtures = [CANDLE]
        actions = render({"type": "melody", "name": "tune",
                          "respect_roles": False}, fixtures)
        self.assertTrue(actions)


class TestColourMovesWithoutTheBrightnessMoving(unittest.TestCase):
    """The gap the audit found: every effect in the catalog modulated
    brightness, because `SetWaveform` carries a whole colour and moves all
    of it. `SetWaveformOptional` is the same engine with a channel mask,
    and these two are the only motion a room can make without flickering.
    """

    def _room_over_time(self, effect, seconds=8.0):
        cast = lamps(2)
        acts = fx.actions_for(fx.clean_effect(effect), cast,
                              grid(seconds=seconds), window=(0.0, seconds),
                              palette=PALETTE, base_brightness=0.55)
        sim = fx.simulate(acts, cast, duration_s=seconds, fps=10)
        return ([f[0][0] for f in sim["frames"]],
                [f[0][1] for f in sim["frames"]],
                [f[0][2] for f in sim["frames"]])

    def test_colour_drift_travels_the_hue_and_freezes_the_level(self):
        hues, _, bris = self._room_over_time(
            {"type": "colour_drift", "name": "d",
             "params": {"period_beats": 4, "span": 120}})
        self.assertGreater(max(hues) - min(hues), 60,
                           "the colour did not travel")
        self.assertLess(max(bris) - min(bris), 0.001,
                        "brightness moved — this effect exists not to")

    def test_saturate_moves_only_the_saturation(self):
        _, sats, bris = self._room_over_time(
            {"type": "saturate", "name": "s",
             "params": {"period_beats": 4, "to_saturation": 0.0}})
        self.assertGreater(max(sats) - min(sats), 0.15)
        self.assertLess(max(bris) - min(bris), 0.001)

    def test_one_packet_carries_the_whole_travel(self):
        """Same economy as every other bulb routine: the motion is run by
        the bulb, so the wire sees one message however long it runs."""
        acts = render({"type": "colour_drift", "name": "d"}, lamps(3))
        self.assertEqual(3, len(acts), "one packet per bulb, not per step")
        self.assertEqual(("h",), acts[0]["channels"])

    def test_the_wire_gets_the_optional_waveform_and_only_then(self):
        from lifx import packets as pk

        cast = lamps(1)
        analysis = {"beats": [i * 0.5 for i in range(20)], "bpm": 120,
                    "tags": {"duration": 8}, "duration_s": 8}
        def _type_of(effect):
            show = compiler.compile_show(
                {"version": 2, "scenes": [{
                    "start": 0, "end": 8, "mood": "m", "palette": PALETTE,
                    "brightness": 0.5, "base": False, "effects": [effect]}],
                 "moments": []}, cast, analysis, source=7)
            import base64
            return pk.parse_header(
                base64.b64decode(show["cues"][0]["payload_b64"]))["type"]

        self.assertEqual(pk.SET_WAVEFORM_OPTIONAL,
                         _type_of({"type": "colour_drift", "name": "d"}))
        # An ordinary waveform effect keeps the ordinary message — nothing
        # already compiled changes shape.
        self.assertEqual(pk.SET_WAVEFORM,
                         _type_of({"type": "breathe", "name": "b"}))


class TestLevelFollowsTheAudio(unittest.TestCase):
    """The other half of the audit: only two effects moved brightness
    through more than two values, and none of them read the song. This one
    has no levels of its own — it reads the analyzer's loudness envelope."""

    def _bench(self, energy):
        beats = [round(i * 0.5, 3) for i in range(33)]
        return fx.Grid(beats, beats[::4], 120.0, energy=energy)

    def test_brightness_tracks_the_envelope(self):
        # Quiet for four beats, loud for four: the lights must follow.
        hop = 0.05
        quiet = [0.05] * int(2.0 / hop)
        loud = [0.95] * int(2.0 / hop)
        g = self._bench({"hop_s": hop, "energy": quiet + loud})
        acts = fx.actions_for(
            fx.clean_effect({"type": "level", "name": "lv",
                             "params": {"step_beats": 1, "floor": 0.0,
                                        "ceiling": 1.0}}),
            lamps(1), g, window=(0.0, 4.0), palette=PALETTE)
        early = [a["bri"] for a in acts if a["t"] < 1.5]
        late = [a["bri"] for a in acts if a["t"] >= 2.0]
        self.assertTrue(early and late)
        self.assertLess(max(early), 0.3, "stayed bright through the quiet")
        self.assertGreater(min(late), 0.6, "did not lift for the loud part")

    def test_a_band_can_be_chosen(self):
        hop = 0.05
        g = self._bench({"hop_s": hop, "energy": [0.5] * 80,
                         "low": [0.9] * 80, "high": [0.1] * 80})
        def level_of(band):
            acts = fx.actions_for(
                fx.clean_effect({"type": "level", "name": "l",
                                 "params": {"band": band, "floor": 0.0,
                                            "ceiling": 1.0}}),
                lamps(1), g, window=(0.0, 4.0), palette=PALETTE)
            return acts[0]["bri"]
        self.assertGreater(level_of("low"), level_of("high"))

    def test_gamma_shapes_the_mapping(self):
        hop = 0.05
        g = self._bench({"hop_s": hop, "energy": [0.5] * 80})
        def level_of(gamma):
            acts = fx.actions_for(
                fx.clean_effect({"type": "level", "name": "l",
                                 "params": {"gamma": gamma, "floor": 0.0,
                                            "ceiling": 1.0}}),
                lamps(1), g, window=(0.0, 4.0), palette=PALETTE)
            return acts[0]["bri"]
        self.assertGreater(level_of(0.5), level_of(2.0),
                           "gamma below 1 must lift the quiet parts")

    def test_a_track_with_no_envelope_renders_nothing(self):
        g = fx.Grid([0.0, 0.5, 1.0], [0.0], 120.0)
        self.assertFalse(g.has_energy)
        acts = fx.actions_for(fx.clean_effect({"type": "level", "name": "l"}),
                              lamps(1), g, window=(0.0, 4.0), palette=PALETTE)
        self.assertEqual([], acts)


class TestOneWaveformPerBulb(unittest.TestCase):
    """A LIFX bulb runs exactly one waveform at a time — sending a second
    is how you end the first. Two overlapping on one light is the later
    cancelling the earlier, which from a sofa reads as an effect that
    mysteriously does nothing."""

    def _rows(self, effects):
        analysis = {"beats": [i * 0.5 for i in range(40)], "bpm": 120,
                    "tags": {"duration": 16}, "duration_s": 16}
        return compiler.script_actions(
            {"version": 2, "scenes": [{
                "start": 0, "end": 16, "mood": "m", "palette": PALETTE,
                "brightness": 0.5, "base": False, "effects": effects}],
             "moments": []}, lamps(3), analysis)["effects"]

    def test_two_routines_on_one_light_are_reported(self):
        rows = self._rows([{"type": "breathe", "name": "first"},
                           {"type": "colour_drift", "name": "second"}])
        clash = [r for r in rows if r.get("note")]
        self.assertTrue(clash, "stacking two bulb routines said nothing")
        self.assertIn("first", clash[0]["note"])
        self.assertIn("one waveform at a time", clash[0]["note"])

    def test_routines_on_different_lights_are_fine(self):
        cast = lamps(3)
        rows = self._rows([
            {"type": "breathe", "name": "a",
             "select": {"ids": [cast[0]["id"]]}},
            {"type": "colour_drift", "name": "b",
             "select": {"ids": [cast[1]["id"]]}}])
        self.assertEqual([], [r for r in rows if r.get("note")])

    def test_a_stepping_effect_never_clashes(self):
        rows = self._rows([{"type": "breathe", "name": "a"},
                           {"type": "chase", "name": "b"}])
        self.assertEqual([], [r for r in rows if r.get("note")])

    def test_the_catalog_agrees_with_itself_about_which_are_routines(self):
        """`BULB_ROUTINES` is what the compiler and the brief both read.
        An effect that emits a wave action and is not on the list would
        clash silently."""
        for name in fx.CATALOG:
            if fx.CATALOG[name]["channel"] != "light":
                continue
            acts = render({"type": name, "name": name})
            emits_wave = any(a["kind"] == "wave" for a in acts)
            with self.subTest(effect=name):
                self.assertEqual(emits_wave, name in fx.BULB_ROUTINES,
                                 f"{name} emits_wave={emits_wave} but "
                                 f"BULB_ROUTINES says otherwise")
