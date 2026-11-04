"""Home Assistant dashboards brAIn keeps (brain/morph/service/lovelace.py).

The integration mirrors what Home Assistant holds; the service keeps the
YAML in git and reconciles the two against the hash they last agreed on.
These drive ``sync`` through every case: first kept, an edit in Home
Assistant's own editor, an edit to the file (sent to HA to save), both at
once (Home Assistant wins), a file mid-edit, and an apply that HA has not
confirmed yet. Then what a person is told a change did.
"""
from __future__ import annotations

import json
import unittest

import yaml

from morph_env import MorphEnv

CFG = {"title": "Home", "views": [{"title": "Home", "sections": [
    {"type": "grid", "cards": [{"type": "heading", "heading": "Kitchen"},
                               {"type": "tile", "entity": "light.kitchen"}]}]}]}


class Sync(unittest.TestCase):
    def ha(self, env, key, cfg):
        """Home Assistant saved ``cfg`` (the integration's mirror)."""
        env.shared.joinpath("lovelace").mkdir(parents=True, exist_ok=True)
        env.shared.joinpath("lovelace", f"{key}.json").write_text(json.dumps(
            {"key": key, "config": cfg, "hash": env.lovelace.config_hash(cfg)}))

    def morph(self, env, *keys):
        env.shared.joinpath("lovelace").mkdir(parents=True, exist_ok=True)
        env.shared.joinpath("lovelace", "morphed.json").write_text(json.dumps({"keys": list(keys)}))

    def applied(self, env, key):
        f = env.shared / "lovelace-apply" / f"{key}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def file(self, env, key):
        return yaml.safe_load((env.morph_dir / "dashboards" / f"{key}.yaml").read_text())

    def write(self, env, key, cfg):
        (env.morph_dir / "dashboards" / f"{key}.yaml").write_text(yaml.safe_dump(cfg))

    def test_a_morphed_dashboard_is_kept_once_and_then_left_alone(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", CFG)
            ev = env.lovelace.sync()
            self.assertEqual([e["what"] for e in ev], ["new"])
            self.assertEqual(self.file(env, "default"), CFG)
            self.assertTrue((env.morph_dir / "dashboards" / "default.yaml").read_text().startswith("# Home"))
            self.assertEqual(env.lovelace.sync(), [])
            self.assertIsNone(self.applied(env, "default"))

    def test_a_dashboard_not_morphed_is_not_touched(self):
        with MorphEnv() as env:
            self.morph(env)
            self.ha(env, "default", CFG)
            self.assertEqual(env.lovelace.sync(), [])
            self.assertFalse((env.morph_dir / "dashboards" / "default.yaml").exists())

    def test_an_edit_in_home_assistant_rewrites_the_file(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", CFG)
            env.lovelace.sync()
            edited = json.loads(json.dumps(CFG))
            edited["views"][0]["title"] = "House"
            self.ha(env, "default", edited)
            self.assertEqual([e["what"] for e in env.lovelace.sync()], ["outside"])
            self.assertEqual(self.file(env, "default")["views"][0]["title"], "House")
            self.assertIsNone(self.applied(env, "default"))

    def test_an_edit_to_the_file_is_sent_to_home_assistant_once(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", CFG)
            env.lovelace.sync()
            edited = json.loads(json.dumps(CFG))
            edited["views"][0]["sections"][0]["cards"].append({"type": "tile", "entity": "light.bar"})
            self.write(env, "default", edited)
            self.assertEqual([e["what"] for e in env.lovelace.sync(now=1000)], ["apply"])
            self.assertEqual(self.applied(env, "default")["config"], edited)
            # Not confirmed yet: nothing new is sent, and it is not read as
            # Home Assistant moving.
            (env.shared / "lovelace-apply" / "default.json").unlink()
            self.assertEqual(env.lovelace.sync(now=1005), [])
            self.assertIsNone(self.applied(env, "default"))
            # Still nothing after RESEND_S: sent again.
            env.lovelace.sync(now=1000 + env.lovelace.RESEND_S + 1)
            self.assertEqual(self.applied(env, "default")["config"], edited)
            # Home Assistant saved it: agreed, quiet.
            self.ha(env, "default", edited)
            self.assertEqual(env.lovelace.sync(), [])

    def test_both_moved_home_assistant_wins(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", CFG)
            env.lovelace.sync()
            mine = json.loads(json.dumps(CFG)); mine["title"] = "Mine"
            theirs = json.loads(json.dumps(CFG)); theirs["title"] = "Theirs"
            self.write(env, "default", mine)
            self.ha(env, "default", theirs)
            self.assertEqual([e["what"] for e in env.lovelace.sync()], ["both"])
            self.assertEqual(self.file(env, "default")["title"], "Theirs")
            self.assertIsNone(self.applied(env, "default"))

    def test_a_file_that_does_not_read_is_held_and_said_once(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", CFG)
            env.lovelace.sync()
            (env.morph_dir / "dashboards" / "default.yaml").write_text("views: [\n  - title: x\n")
            ev = env.lovelace.sync()
            self.assertEqual([e["what"] for e in ev], ["held"])
            self.assertIn("could not be read", ev[0]["problem"])
            self.assertEqual(env.lovelace.sync(), [])
            self.assertIsNone(self.applied(env, "default"))

    def test_a_dashboard_with_nothing_stored_is_waited_for(self):
        with MorphEnv() as env:
            self.morph(env, "default")
            self.ha(env, "default", None)
            self.assertEqual(env.lovelace.sync(), [])


class WhatChanged(unittest.TestCase):
    def test_a_person_is_told_what_moved_was_added_and_changed(self):
        with MorphEnv() as env:
            new = json.loads(json.dumps(CFG))
            cards = new["views"][0]["sections"][0]["cards"]
            cards[1]["name"] = "Cans"
            cards.append({"type": "custom:morph-light-card", "entity": "light.bar"})
            new["views"].append({"title": "Yard", "cards": []})
            shows = env.lovelace.describe_change(CFG, new)
            self.assertIn("Added the Yard tab", shows)
            self.assertIn("Changed the tile card (Cans) in Home › Kitchen", shows)
            self.assertIn("Added a morph-light-card card (light.bar) to Home › Kitchen", shows)

    def test_a_card_that_moved_is_one_move(self):
        with MorphEnv() as env:
            old = {"views": [{"title": "A", "cards": [{"type": "tile", "entity": "light.x"}]},
                             {"title": "B", "cards": []}]}
            new = {"views": [{"title": "A", "cards": []},
                             {"title": "B", "cards": [{"type": "tile", "entity": "light.x"}]}]}
            self.assertEqual(env.lovelace.describe_change(old, new),
                             ["Moved the tile card (light.x) from A to B"])

    def test_a_path_is_said_in_words_and_never_trusted(self):
        with MorphEnv() as env:
            at = ["views", 0, "sections", 0, "cards", 1]
            self.assertEqual(env.lovelace.where(CFG, at), "Home › Kitchen › tile card (light.kitchen)")
            self.assertEqual(env.lovelace.at_path(CFG, at), {"type": "tile", "entity": "light.kitchen"})
            self.assertIsNone(env.lovelace.at_path(CFG, ["views", 7]))
            self.assertEqual(env.lovelace.clean_at(["views", "../../etc", 1]), [])
            self.assertEqual(env.lovelace.clean_at(["views", True]), [])
            self.assertEqual(env.lovelace.clean_at("views"), [])


class TellOnADashboard(unittest.TestCase):
    def test_the_prompt_sends_brain_to_the_yaml_and_the_held_part(self):
        with MorphEnv() as env:
            env.shared.joinpath("lovelace").mkdir(parents=True)
            env.shared.joinpath("lovelace", "morphed.json").write_text(json.dumps({"keys": ["default"]}))
            (env.morph_dir / "dashboards").mkdir()
            (env.morph_dir / "dashboards" / "default.yaml").write_text(yaml.safe_dump(CFG))
            target = {"kind": "lovelace", "dashboard": "default", "label": "the tile card",
                      "at": json.dumps(["views", 0, "sections", 0, "cards", 1])}
            part = env.tell.target_yaml(target)
            self.assertIn("light.kitchen", part)
            self.assertNotIn("heading", part)
            prompt = env.tell.build_prompt(target, "make it bigger", part)
            self.assertIn("/config/morph/dashboards/default.yaml", prompt)
            self.assertIn("never call update_dashboard", prompt)
            self.assertIn("card type", prompt)
            self.assertNotIn("/config/morph/dashboard.yaml", prompt)

    def test_a_dashboard_brain_does_not_keep_is_refused(self):
        with MorphEnv() as env:
            env.brain_on()
            out = env.tell.start({"kind": "lovelace", "dashboard": "other"}, "do it")
            self.assertIn("Morph this dashboard", out.get("error", ""))

    def test_read_back_says_what_the_commit_changed(self):
        with MorphEnv() as env:
            env.gitrepo.ensure()
            (env.morph_dir / "dashboards").mkdir()
            f = env.morph_dir / "dashboards" / "default.yaml"
            f.write_text(yaml.safe_dump(CFG))
            base = env.gitrepo.commit("kept", "morph")
            new = json.loads(json.dumps(CFG))
            new["views"][0]["sections"][0]["cards"].append({"type": "tile", "entity": "light.bar"})
            f.write_text(yaml.safe_dump(new))
            sha = env.gitrepo.commit("brAIn: added", "brain")
            back = env.tell.read_back(base, sha, {"kind": "lovelace", "dashboard": "default"})
            self.assertEqual(back["shows"], ["Added a tile card (light.bar) to Home › Kitchen"])
            self.assertEqual(back["unreadable"], "")


if __name__ == "__main__":
    unittest.main()
