"""Scenes asked for are written, in the house's own names, and only once.

Two complaints in one. A person who had said brAIn may act without asking
(or turned YOLO mode on) asked for scenes and got a card to accept anyway;
and the scenes were named "Morning — Lounge" in a house whose own scenes
all read "Lounge - Bright", with a second scene for a mood the room already
had. So:

  * `scenes.name_pattern` reads the house's naming off its own scenes and
    new scenes follow it; a house with no pattern keeps brAIn's;
  * a mood the room already has a scene for is not composed again, and a
    room with every mood is refused;
  * with brAIn acting without asking, `_design_scenes` writes the scenes
    into scenes.yaml through the ordinary accept (snapshot, reload,
    verify, settle) and says so; with it off the card stays;
  * the same rule for the other drafted changes a sentence can become
    (`_accepts_at_once`): a one-off or standing rule from a reply, from
    `brain.intent` under YOLO, and from a card somebody asked for a change.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
import unittest.mock as mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenes  # noqa: E402
from test_proposal_accept import AcceptCase  # noqa: E402
from test_scenes import house, light  # noqa: E402

DEN = [
    light("light.den_ceiling", "Den ceiling", "Den", ("color_temp",)),
    light("light.den_lamp", "Den lamp", "Den", ("brightness",)),
    light("light.den_strip", "Den strip", "Den", ("hs",)),
]


def with_scenes(rows, names: list[str], ids: list[str] | None = None) -> dict:
    snap = house(rows, extra_scenes=[
        {"id": (ids or [f"16{i:011d}" for i in range(len(names))])[i],
         "name": n, "entities": {}} for i, n in enumerate(names)])
    return snap


class TestTheHousesOwnNames(unittest.TestCase):
    def test_room_then_variant_is_read_and_followed(self):
        snap = with_scenes(DEN + [light("light.hall_a", "Hall a", "Hall")],
                           ["Den - Movie", "Hall - Party", "Den - Reading"])
        self.assertEqual(scenes.name_pattern(snap), ("area_first", " - "))
        obj = scenes.build(snap, "Den")
        self.assertEqual([c["name"] for c in obj["config"]],
                         ["Den - Morning", "Den - Day", "Den - Evening",
                          "Den - Night"])

    def test_variant_then_room_with_its_own_separator(self):
        snap = with_scenes(DEN, ["Movie: Den", "Reading: Den"])
        self.assertEqual(scenes.name_pattern(snap), ("area_last", ": "))
        self.assertEqual(scenes.build(snap, "Den")["config"][0]["name"],
                         "Morning: Den")

    def test_one_scene_is_not_a_pattern_and_no_scenes_keep_brains_names(self):
        self.assertIsNone(scenes.name_pattern(with_scenes(DEN, ["Den - Movie"])))
        self.assertIsNone(scenes.name_pattern(house(DEN)))
        self.assertEqual(scenes.build(house(DEN), "Den")["config"][0]["name"],
                         "Morning — Den")

    def test_brains_own_scenes_are_not_the_houses_habit(self):
        snap = with_scenes(DEN, ["Den - Morning", "Den - Day"],
                           ids=["brain_scene_den_morning", "brain_scene_den_day"])
        self.assertIsNone(scenes.name_pattern(snap))

    def test_a_scene_from_an_integration_counts_too(self):
        snap = house(DEN)
        for name, eid in (("Den - Movie", "scene.den_movie"),
                          ("Den - Reading", "scene.den_reading")):
            snap["states"][eid] = {"state": "unknown",
                                   "attributes": {"friendly_name": name}}
        self.assertEqual(scenes.name_pattern(snap), ("area_first", " - "))


class TestAMoodTheRoomHasIsNotMadeAgain(unittest.TestCase):
    def test_a_dim_scene_is_the_evening_and_is_left_out(self):
        snap = with_scenes(DEN, ["Den - Dim", "Den - Movie"])
        obj = scenes.build(snap, "Den")
        self.assertNotIn("refused", obj)
        self.assertEqual([c["name"] for c in obj["config"]],
                         ["Den - Morning", "Den - Day", "Den - Night"])
        self.assertNotIn("brain_scene_den_evening",
                         [c["id"] for c in obj["config"]])
        self.assertIn("Den - Dim", obj["why"])

    def test_a_room_with_every_mood_is_refused(self):
        snap = with_scenes(DEN, ["Den - Wake up", "Den - Bright", "Den - Relax",
                                 "Den - Sleep"])
        obj = scenes.build(snap, "Den")
        self.assertIn("already has a scene for every mood", obj["refused"])

    def test_another_rooms_scene_covers_nothing_here(self):
        snap = with_scenes(DEN + [light("light.hall_a", "Hall a", "Hall"),
                                  light("light.hall_b", "Hall b", "Hall")],
                           ["Hall - Dim", "Hall - Night"])
        self.assertEqual(len(scenes.build(snap, "Den")["config"]), 4)

    def test_a_name_already_taken_is_not_written_twice(self):
        # "Den - Evening" names no mood word brAIn reads? It does: the
        # mood word itself. A name taken by a scene about something else
        # is the other case.
        snap = with_scenes(DEN, ["Den - Movie", "Den - Day"])
        names = [c["name"] for c in scenes.build(snap, "Den")["config"]]
        self.assertNotIn("Den - Day", names)


class TestWrittenStraightAway(AcceptCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.scenes_file = self.config / "scenes.yaml"
        self.scenes_file.write_text("# My scenes.\n")
        snap = with_scenes(DEN, ["Den - Movie", "Den - Reading"])
        self.scenes_appear = [f"scene.den_{m}" for m in scenes.MOODS]
        self.server.SCENES_INFLIGHT.clear()

        async def rooms():
            return snap

        async def no_names(*_a, **_k):
            raise RuntimeError("no naming run here")

        for name, value in (("_claude", no_names),):
            self.addCleanup(setattr, self.server, name, getattr(self.server, name))
            setattr(self.server, name, value)
        self.addCleanup(setattr, self.server.checks.snapshot, "collect_rooms",
                        self.server.checks.snapshot.collect_rooms)
        self.server.checks.snapshot.collect_rooms = rooms
        self.addCleanup(setattr, self.server.automation_writer,
                        "protected_patterns",
                        self.server.automation_writer.protected_patterns)
        self.server.automation_writer.protected_patterns = lambda *_a: []

    async def design(self, acts: bool) -> dict:
        with mock.patch.object(self.server, "eff_skip_permissions",
                               lambda: acts), \
                mock.patch.object(self.server, "yolo_mode", lambda: False):
            out = await self.server._design_scenes("Den")
            await asyncio.gather(*list(self.server._SCENE_TASKS))
        return out

    def scene_rows(self):
        import yaml
        return yaml.safe_load(self.scenes_file.read_text()) or []

    async def test_acting_without_asking_writes_them_and_says_so(self):
        out = await self.design(True)
        self.assertTrue(out["acts"])
        self.assertIn("writing", out["say"])
        self.assertEqual([r["name"] for r in self.scene_rows()],
                         ["Den - Morning", "Den - Day", "Den - Evening",
                          "Den - Night"])
        self.assertIn("/services/scene/reload", self.calls)
        self.assertEqual([r for r in self.proposals.listing()
                          if r.get("status") in self.proposals.OPEN_STATUSES],
                         [], "no card left to press")
        # Written through the edit journal, so `brain undo` reverses it.
        journal = Path(self.tmp.name) / "edits"
        self.assertTrue(any(journal.rglob("*")), "the write left no snapshot")

    async def test_asking_first_leaves_the_card(self):
        out = await self.design(False)
        self.assertFalse(out["acts"])
        self.assertIn("offered for you to accept", out["say"])
        self.assertEqual(self.scenes_file.read_text(), "# My scenes.\n")
        [row] = self.proposals.listing()
        self.assertEqual(row["status"], "proposed")


class TestEveryDraftedChangeFollowsTheSameRule(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server

    def accepts(self, req, *, yolo=False, switch=False):
        with mock.patch.object(self.server, "yolo_mode", lambda: yolo), \
                mock.patch.object(self.server, "eff_skip_permissions",
                                  lambda: yolo or switch):
            return self.server._accepts_at_once(req)

    def test_yolo_writes_every_asked_rule_and_no_card_suggestion(self):
        for via in ("panel", "morph", "reply", "service", "onboarding",
                    "asked:abc"):
            self.assertTrue(self.accepts({"via": via}, yolo=True), via)
        self.assertFalse(self.accepts({"via": "card:abc"}, yolo=True))

    def test_the_switch_writes_only_what_a_person_typed(self):
        for via in ("panel", "morph", "reply", "asked:abc"):
            self.assertTrue(self.accepts({"via": via, "typed": True},
                                         switch=True), via)
        self.assertFalse(self.accepts({"via": "service"}, switch=True))
        self.assertFalse(self.accepts({"via": "card:abc", "typed": True},
                                      switch=True))
        self.assertFalse(self.accepts({"via": "reply", "typed": True}))

    def test_a_card_asked_for_a_change_files_its_rule_as_the_persons(self):
        asked = []

        def request(sentence, via="panel", now=None, *, trial=False, typed=False):
            asked.append((via, typed))
            return "queued"

        opp = [{"text": "From now on, turn the den lamp off at midnight",
                "entities": ["light.den_lamp"]}]
        with mock.patch.object(self.server, "_resident_gate", lambda _s: ""), \
                mock.patch.object(self.server.intents, "request", request):
            asyncio.run(self.server._offer_card_opportunities(
                "ask1", opp, asked="typed"))
            asyncio.run(self.server._offer_card_opportunities("sched1", opp))
        self.assertEqual(asked, [("asked:ask1", True), ("card:sched1", False)])


if __name__ == "__main__":
    unittest.main()
