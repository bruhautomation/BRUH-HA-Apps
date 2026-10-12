"""What three house reports about Morph found, driven end to end.

* "It says it's making changes to the dashboard, but none of them are
  applied." A Tell ended on brAIn's own summary whether or not anything in
  /config/morph had changed. It now reads the dashboard back and says what
  is different on screen, worked out from the file — and says so plainly
  when nothing is, or when the file no longer reads.
* "Sections overlap at rest" naming "Add section" ghosts: a resting spring
  outlived its element when Edit closed (engine.js, driven under node).
* Settings gained brAIn's "What do you want to fix?" box, for Morph: the
  owner's words reach brAIn's development loop as they are.
"""
import asyncio
import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from morph_env import FRONTEND, MorphEnv
from test_morph_loops import DOC, FakeBrain, fast, finish

HAS_GIT = shutil.which("git") is not None
HAS_NODE = shutil.which("node") is not None


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestATellIsReadBack(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.published = []

        def publish():
            mirror = self.env.store.publish(self.env.gitrepo.head())
            self.published.append(mirror["revision"])
            return mirror
        self.env.tell.ON_PUBLISH = publish

    def tell(self, words, work):
        fake = FakeBrain(self.env, work)
        fake.start()
        self.addCleanup(fake.stop.set)

        async def go():
            st = self.env.tell.start({"kind": "dashboard"}, words)
            return await finish(self.env, st)
        return asyncio.run(go())

    def test_a_summary_over_an_unchanged_dashboard_says_nothing_changed(self):
        st = self.tell("Remove the Right now card",
                       lambda task: {"data": {"summary": "Removed the Right now card.",
                                              "changed": [], "reload": True}})
        self.assertEqual("done", st["phase"])
        self.assertTrue(st.get("unchanged"))
        self.assertTrue(st["say"].startswith("Nothing on the dashboard changed."), st["say"])
        self.assertIn("Removed the Right now card.", st["say"], "what brAIn said is quoted, not hidden")
        self.assertNotIn("commit", st)

    def test_a_change_is_listed_from_the_file_and_published_at_once(self):
        env = self.env

        def work(task):
            dash, _, _ = env.store.read()
            dash["greeting"] = False
            dash["floors"][0]["sections"][0]["title"] = "Cook space"
            env.store.write(dash)
            return {"data": {"summary": "Done.", "changed": ["dashboard.yaml"]}}

        st = self.tell("Hide the greeting and rename the kitchen", work)
        self.assertEqual("done", st["phase"], st.get("say"))
        self.assertFalse(st.get("unchanged"))
        self.assertIn("The greeting is hidden.", st["shows"])
        self.assertIn("“Kitchen” is now called “Cook space”.", st["shows"])
        # The mirror the panel reads is the file brAIn wrote, before "done".
        _, _, text = env.store.read()
        self.assertEqual(env.store.revision(text), st["revision"])
        self.assertIn(st["revision"], self.published)
        mirror = json.loads(env.paths.MIRROR.read_text())
        self.assertIs(mirror["dashboard"]["greeting"], False)

    def test_a_file_that_no_longer_reads_is_not_applied_and_can_be_undone(self):
        env = self.env

        def work(task):
            env.paths.DASHBOARD.write_text("floors: [\n  - title: oops\n", encoding="utf-8")
            return {"data": {"summary": "Added a Pets section.", "changed": ["dashboard.yaml"]}}

        st = self.tell("Add a Pets section", work)
        self.assertEqual("failed", st["phase"])
        self.assertTrue(st["say"].startswith("Not applied: dashboard.yaml could not be read"), st["say"])
        self.assertTrue(st.get("commit"), "the broken write is still one commit Undo can revert")
        out = env.tell.undo(st["id"])
        self.assertTrue(out["ok"], out)
        dash, problems, _ = env.store.read()
        self.assertEqual([], problems)
        self.assertEqual("Kitchen", dash["floors"][0]["sections"][0]["title"])

    def test_a_rewrite_that_changes_nothing_on_screen_says_so(self):
        env = self.env

        def work(task):
            text = env.paths.DASHBOARD.read_text(encoding="utf-8")
            env.paths.DASHBOARD.write_text(text + "\n# tidied\n", encoding="utf-8")
            return {"data": {"summary": "Moved the lights first.", "changed": ["dashboard.yaml"]}}

        st = self.tell("Move the lights first", work)
        self.assertTrue(st.get("unchanged"))
        self.assertIn("nothing on the dashboard is different", st["say"])


class TestDescribeChange(unittest.TestCase):

    def test_what_a_person_would_see(self):
        with MorphEnv() as env:
            old, _ = env.store.normalize(DOC)
            new = json.loads(json.dumps(old))
            new["story"] = False
            card = new["floors"][0]["sections"][0]["groups"][0]["cards"]
            card.append({"id": "c_fan", "type": "fan", "entity": "fan.ceiling"})
            card.pop(0)
            got = env.tell.describe_change(old, new)
        self.assertIn("The story line is hidden.", got)
        self.assertIn("New card “fan.ceiling” in Kitchen.", got)
        self.assertIn("Removed the card “light.countertop” from Kitchen.", got)

    def test_the_greeting_is_a_flag_the_file_can_carry(self):
        with MorphEnv() as env:
            dash, problems = env.store.normalize({"greeting": False})
            self.assertEqual([], problems)
            self.assertIs(dash["greeting"], False)
            self.assertIs(env.store.empty()["greeting"], True)
        panel = (FRONTEND / "morph-panel.js").read_text()
        self.assertIn("dash.greeting !== false", panel)


class TestWhatDoYouWantToFix(unittest.TestCase):

    def test_the_words_go_as_they_are_and_can_be_taken_back(self):
        with MorphEnv() as env:
            out = env.devloop.note_request("The scenes line wraps badly on my phone. It hides the clock.",
                                           ui=True, context="Morph 0.5.0")
            self.assertTrue(out["ok"], out)
            rows = env.devloop.rows()
            self.assertEqual(1, len(rows))
            row = rows[0]
            self.assertEqual("Morph · Looks", row["where"])
            self.assertEqual("The scenes line wraps badly on my phone.", row["what"])
            self.assertIn("> The scenes line wraps badly on my phone. It hides the clock.", row["body"])
            self.assertNotIn("Morph reported this", row["body"])
            mine = env.devloop.mine()
            self.assertEqual([False], [m["picked"] for m in mine])
            self.assertTrue(mine[0]["ui"])
            self.assertTrue(env.devloop.withdraw(mine[0]["fp"])["ok"])
            self.assertEqual([], env.devloop.rows())

    def test_nothing_is_sent_while_reporting_is_off_or_the_box_is_empty(self):
        with MorphEnv() as env:
            self.assertFalse(env.devloop.note_request("  ")["ok"])
            env.settings.update({"report_code_issues": False})
            out = env.devloop.note_request("The fan card is too tall")
            self.assertFalse(out["ok"])
            self.assertIn("Report Morph’s own problems", out["error"])
            self.assertEqual([], env.devloop.mine())

    def test_a_fault_morph_noted_is_not_the_persons_to_take_back(self):
        with MorphEnv() as env:
            env.devloop.note_fault("Cards", "A fan card failed to draw")
            fp = next(iter(json.loads((env.data / "faults.json").read_text())))
            self.assertFalse(env.devloop.withdraw(fp)["ok"])
            self.assertEqual(1, len(env.devloop.rows()))

    def test_the_panel_routes_it(self):
        ws = (FRONTEND.parent / "websocket.py").read_text()
        self.assertIn('"report", "report_withdraw"', ws)
        with MorphEnv() as env:
            self.assertIn("mine", env.devloop.status())


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestAGhostLeavesNoSpring(unittest.TestCase):
    """overlaps() compared every spring the engine had ever made, and a
    resting spring outlives its element: after Edit closed, each "Add
    section" ghost's spring stayed where the ghost had stood."""

    def run_node(self, body):
        script = textwrap.dedent(f"""
            import {{ Engine }} from {json.dumps((FRONTEND / 'engine.js').as_uri())};
            const el = (id, connected) => ({{ isConnected: connected, getAttribute: () => id }});
            const e = new Engine(null);
            {body}
        """)
        r = subprocess.run(["node", "--input-type=module", "-e", script],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    def test_a_section_no_longer_on_the_page_is_not_an_overlap(self):
        got = self.run_node("""
            e.model = { sections: [{ id: 's_lab' }] };
            e.it['s:s_lab'] = { el: el('s_lab', true), x: 0, y: 0, w: 400, h: 300 };
            e.it['s:__new@0'] = { el: el('__new@0', false), x: 0, y: 0, w: 400, h: 300 };
            console.log(JSON.stringify(e.overlaps()));
        """)
        self.assertEqual([], got)

    def test_two_real_sections_on_top_of_each_other_still_are(self):
        got = self.run_node("""
            e.model = { sections: [{ id: 'a' }, { id: 'b' }] };
            e.it['s:a'] = { el: el('a', true), x: 0, y: 0, w: 400, h: 300 };
            e.it['s:b'] = { el: el('b', true), x: 100, y: 100, w: 400, h: 300 };
            console.log(JSON.stringify(e.overlaps()));
        """)
        self.assertEqual([["a", "b"]], got)


class TestCardCodeIsGuarded(unittest.TestCase):

    def test_agents_md_shows_a_guarded_define(self):
        agents = (Path(__file__).resolve().parent.parent / "morph" / "defaults" / "AGENTS.md").read_text()
        self.assertIn('if (!customElements.get("morph-pets")) customElements.define(', agents)
        self.assertNotIn("\ncustomElements.define(", agents)


if __name__ == "__main__":
    unittest.main()
