"""Morph's service: the dashboard file, its history, and the generator.

Each test runs against a scratch /config/morph that is a real git
repository, because "every change is one commit and Undo is a revert" is a
claim about git, and a fake git would only agree with the code that mocked
it.
"""
import shutil
import unittest

from morph_env import MorphEnv

HAS_GIT = shutil.which("git") is not None


DOC = {
    "title": "Home",
    "floors": [{
        "title": "Ground",
        "sections": [{
            "title": "Kitchen",
            "color": "amber",
            "width": 9,
            "groups": [{"cards": [
                {"entity": "light.countertop"},
                {"type": "tile", "entity": "sensor.fridge"},
                {"type": "note", "text": "Bins go out Tuesday"},
                {"name": "Broken"},
            ]}],
        }],
    }],
}


class TestTheDocument(unittest.TestCase):

    def test_normalize_keeps_what_it_can_and_names_what_it_dropped(self):
        with MorphEnv() as env:
            dash, problems = env.store.normalize(DOC)
            sec = dash["floors"][0]["sections"][0]
            self.assertEqual(4, sec["width"], "a width is clamped, never refused")
            cards = sec["groups"][0]["cards"]
            self.assertEqual(["light", "lovelace", "note"], [c["type"] for c in cards])
            self.assertEqual({"type": "tile", "entity": "sensor.fridge"}, cards[1]["card"],
                             "a Lovelace card is wrapped whole, not rewritten")
            self.assertEqual(1, len(problems))
            self.assertIn("no entity", problems[0])

    def test_a_round_trip_keeps_every_id(self):
        """Undo, notes and the usage log key on ids, so a save that minted
        new ones would read as a whole new dashboard."""
        with MorphEnv() as env:
            first, _ = env.store.normalize(DOC)
            again, _ = env.store.load_text(env.store.dump(first))
            self.assertEqual(first, again)
            ids = [c["id"] for f in first["floors"] for s in f["sections"]
                   for g in s["groups"] for c in g["cards"]]
            self.assertTrue(all(i.startswith("c_") and not i.startswith("c_c_") for i in ids))

    def test_ids_are_unique_even_when_two_cards_show_one_entity(self):
        with MorphEnv() as env:
            raw = {"floors": [{"sections": [{"cards": [
                {"entity": "light.a"}, {"entity": "light.a"}]}]}]}
            dash, _ = env.store.normalize(raw)
            ids = [c["id"] for c in dash["floors"][0]["sections"][0]["groups"][0]["cards"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_garbage_is_an_empty_dashboard_with_a_reason(self):
        with MorphEnv() as env:
            dash, problems = env.store.load_text("- just\n- a list\n")
            self.assertEqual([], dash["floors"])
            self.assertTrue(problems)


class TestABrokenFile(unittest.TestCase):

    def test_a_file_that_does_not_parse_keeps_the_last_good_dashboard(self):
        """Somebody mid-edit is not asking for an empty house."""
        with MorphEnv() as env:
            dash, _ = env.store.normalize(DOC)
            env.store.write(dash)
            good = env.store.publish()
            self.assertFalse(good["held"])
            (env.morph_dir / "dashboard.yaml").write_text("floors: [\n  - title: x\n")
            mirror = env.store.publish()
            self.assertTrue(mirror["held"])
            self.assertEqual(good["dashboard"], mirror["dashboard"])
            self.assertIn("line", mirror["problems"][0])
            self.assertNotEqual(good["revision"], mirror["revision"],
                                "the revision follows the file, so a fix is noticed")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestHistory(unittest.TestCase):

    def test_every_change_is_one_commit_and_undo_is_a_revert(self):
        with MorphEnv() as env:
            dash, _ = env.store.normalize(DOC)
            env.store.write(dash)
            base = env.gitrepo.commit("First", "person")
            self.assertTrue(base)
            dash["title"] = "Our house"
            env.store.write(dash)
            change = env.gitrepo.commit("Renamed", "brain")
            self.assertEqual("", env.gitrepo.commit("Nothing", "brain"),
                             "nothing changed is an answer, not a commit")
            ok, new = env.gitrepo.revert(change)
            self.assertTrue(ok, new)
            self.assertEqual("Home", env.store.read()[0]["title"])
            self.assertTrue(env.gitrepo.is_reverted(change))
            self.assertFalse(env.gitrepo.is_reverted(base))
            who = [row["who"] for row in env.gitrepo.log()]
            self.assertEqual(["person", "brain", "person"], who)

    def test_restore_is_a_new_commit_so_it_can_be_undone(self):
        with MorphEnv() as env:
            dash, _ = env.store.normalize(DOC)
            env.store.write(dash)
            first = env.gitrepo.commit("First", "person")
            dash["title"] = "Later"
            env.store.write(dash)
            env.gitrepo.commit("Later", "person")
            ok, new = env.gitrepo.restore(first)
            self.assertTrue(ok)
            self.assertEqual("Home", env.store.read()[0]["title"])
            self.assertEqual(3, len(env.gitrepo.log()))

    def test_an_edit_made_by_hand_is_committed_as_outside(self):
        with MorphEnv() as env:
            dash, _ = env.store.normalize(DOC)
            env.store.write(dash)
            env.gitrepo.commit("First", "person")
            (env.morph_dir / "dashboard.yaml").write_text("title: Typed\nfloors: []\n")
            self.assertTrue(env.gitrepo.commit_pending())
            self.assertEqual("outside", env.gitrepo.log()[0]["who"])

    def test_a_revert_refuses_what_is_not_a_commit_here(self):
        with MorphEnv() as env:
            env.gitrepo.ensure()
            self.assertFalse(env.gitrepo.revert("; rm -rf /")[0])
            self.assertFalse(env.gitrepo.revert("deadbeef")[0])


class TestTheGenerator(unittest.TestCase):

    def house(self):
        def st(eid, name, **attrs):
            return {"entity_id": eid, "state": "on",
                    "attributes": {"friendly_name": name, **attrs}}
        return {
            "floors": [{"floor_id": "ground", "name": "Ground", "level": 0}],
            "areas": [{"area_id": "kitchen", "name": "Kitchen", "floor_id": "ground"}],
            "devices": [],
            "states": [
                st("light.kitchen_countertop", "Kitchen Countertop"),
                st("sensor.kitchen_temp", "Kitchen temperature", device_class="temperature"),
                st("lock.front", "Front door"),
                st("sensor.brain_status", "brAIn status"),
            ],
            "entities": [
                {"entity_id": "light.kitchen_countertop", "area_id": "kitchen"},
                {"entity_id": "sensor.kitchen_temp", "area_id": "kitchen"},
                {"entity_id": "lock.front"},
                {"entity_id": "sensor.brain_status", "platform": "brain"},
            ],
        }

    def test_a_room_becomes_a_section_and_the_house_gets_its_own(self):
        with MorphEnv() as env:
            dash, problems = env.store.normalize(env.generator.build(self.house()))
            self.assertEqual([], problems)
            titles = [s["title"] for f in dash["floors"] for s in f["sections"]]
            self.assertIn("Kitchen", titles)
            entities = env.store.all_entities(dash)
            self.assertIn("light.kitchen_countertop", entities)
            self.assertIn("lock.front", entities)
            self.assertNotIn("sensor.brain_status", entities,
                             "the add-ons' own entities are not the house")
            kitchen = next(s for f in dash["floors"] for s in f["sections"]
                           if s["title"] == "Kitchen")
            names = [c.get("name") for g in kitchen["groups"] for c in g["cards"]]
            self.assertIn("Countertop", names, "the room is said once, by the section")


if __name__ == "__main__":
    unittest.main()
