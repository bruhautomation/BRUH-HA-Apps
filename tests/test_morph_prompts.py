"""What Morph hands brAIn, read off the real builders.

An audit of Morph's prompts found a Tell prompt with three "first"s, rules
said twice (once in the prompt and once in AGENTS.md, so editing one left
the other contradicting it), cuts nobody marked, a suggestion's title sent
as the name of a card that does not exist, Morph's own sentence shown to
brAIn as what brAIn had answered, and LEARNED.md rewritten whole by a pass
that could drop a rule somebody typed. Everything here drives the code that
builds the prompt or reads the answer — the stand-in brAIn is
``test_morph_loops``'s, which claims a task by renaming it — because a
grep for a line is not a test of what the line does.
"""
import asyncio
import importlib
import json
import shutil
import subprocess
import textwrap
import time
import unittest
from pathlib import Path

from morph_env import FRONTEND, MorphEnv
from test_morph_loops import DOC, FakeBrain, fast, finish

HAS_GIT = shutil.which("git") is not None
HAS_NODE = shutil.which("node") is not None
SHOT = "0123456789abcdef0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
OK = {"data": {"summary": "ok", "files": [], "home_assistant": []}}


class _Base(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.env.brain_on()
        fast(self.env)
        dash, _ = self.env.store.normalize(DOC)
        self.env.store.write(dash)
        self.env.gitrepo.commit("First", "morph")
        self.dash = dash
        self.card = dash["floors"][0]["sections"][0]["groups"][0]["cards"][0]["id"]
        self.section = dash["floors"][0]["sections"][0]["id"]

    def brain(self, work=None):
        fake = FakeBrain(self.env, work or (lambda task: OK))
        fake.start()
        self.addCleanup(fake.stop.set)
        return fake

    def tell(self, *args, **kw):
        async def go():
            return await finish(self.env, self.env.tell.start(*args, **kw))
        return asyncio.run(go())

    def prompt(self, target, words="Make it bigger", **kw):
        current = self.env.tell.target_yaml(target)
        return self.env.tell.build_prompt(target, words, current, **kw)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestOneProcedure(_Base):

    def test_the_picture_comes_first_and_the_sections_follow_in_order(self):
        self.env.paths.SHOTS.mkdir(parents=True, exist_ok=True)
        (self.env.paths.SHOTS / f"{SHOT}.png").write_bytes(PNG)
        self.env.learning.add_lesson("Lights before sensors", "learned")
        text = self.prompt({"kind": "card", "id": self.card, "label": "Countertop"},
                           shot=self.env.paths.SHOTS / f"{SHOT}.png")
        order = ["LOOK FIRST", "THE REQUEST", "WHERE THIS LIVES", "Scope:", "HOUSEHOLD RULES", "HOW", "ANSWER"]
        at = [text.index(x) for x in order]
        self.assertEqual(sorted(at), at, "one procedure, in one order")
        self.assertEqual(1, text.lower().count("first"), "one thing is looked at first")
        self.assertIn("identify in the picture what the request is about", text)
        self.assertNotIn("Fix what the picture shows is wrong", text)

    def test_each_rule_is_said_once_and_the_details_are_agents_mds(self):
        text = self.prompt({"kind": "dashboard"})
        # The dashboard file's own header mentions git; that is the file,
        # not a rule of the prompt's.
        text = text[:text.index("```yaml")] + text[text.index("```\n", text.index("```yaml") + 7):]
        self.assertEqual(1, text.count("git"))
        self.assertEqual(1, text.count("remember_fact"))
        self.assertEqual(1, text.count("smallest change"))
        self.assertIn("Read the sections you need", text)
        self.assertNotIn("READ IT FIRST", text)
        self.assertNotIn("has no history", text, "the calculated-sensor rule lives in AGENTS.md")
        self.assertNotIn("never replace boot.js", text.lower(), "the copy procedure lives in AGENTS.md")

    def test_showing_a_protected_entity_is_fine_and_acting_on_one_is_not(self):
        text = self.prompt({"kind": "dashboard"})
        self.assertIn("Showing a protected entity on the\ndashboard is fine; acting on one is not.", text)

    def test_every_kind_says_where_it_lives(self):
        story = self.prompt({"kind": "story", "label": "story"})
        self.assertIn("storyFacts", story)
        self.assertIn("situation sentence", story)
        self.assertIn("Target: the story line\n", story, "the kind word is not repeated as a label")
        upcoming = self.prompt({"kind": "upcoming", "label": "Coming up"})
        self.assertIn("upcoming.js", upcoming)
        self.assertIn("Target: the Coming up timeline\n", upcoming)
        card = self.prompt({"kind": "card", "id": self.card, "label": "Countertop"})
        self.assertIn("This card is in /config/morph/dashboard.yaml", card)
        self.assertIn("Morph's normalized form of it", card)
        code = self.prompt({"kind": "code", "id": "styles.js", "label": "styles.js"})
        self.assertIn("Target: Morph's own styles.js", code)
        self.assertNotIn("the Morph's", code)
        self.assertIn("/config/morph/frontend/", code)

    def test_a_long_dashboard_is_cut_on_a_line_and_says_so(self):
        dash = json.loads(json.dumps(self.dash))
        cards = dash["floors"][0]["sections"][0]["groups"][0]["cards"]
        cards += [{"entity": f"light.lamp_{i:04d}", "name": f"Lamp number {i}"} for i in range(600)]
        self.env.store.write(dash)
        current = self.env.tell.target_yaml({"kind": "dashboard"})
        self.assertLessEqual(len(current), self.env.tell.TARGET_CHARS + 120)
        last = current.splitlines()[-1]
        self.assertRegex(last, r"^# … \d+ more lines cut; Read /config/morph/dashboard\.yaml for the rest\.$")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestWhereATellCameFrom(_Base):

    def test_person_words_ride_on_every_tell(self):
        fake = self.brain()
        morphd = importlib.import_module("morphd")
        self.tell({"kind": "dashboard"}, "Call it Our house")
        self.assertEqual("Call it Our house", fake.seen[-1]["person_words"])

        self.env.learning.add_suggestions(
            [{"title": "Move the hallway above the kitchen", "change": "Move Kitchen below Hallway",
              "section": self.section}], self.dash)
        sid = self.env.learning.listing()[0]["id"]

        async def do_it():
            out = await morphd.handle("suggestion", {"verb": "do", "id": sid})
            return await finish(self.env, self.env.tell.read_state(out["tell"]))
        st = asyncio.run(do_it())
        task = fake.seen[-1]
        self.assertEqual("Move Kitchen below Hallway", task["person_words"])
        self.assertEqual({"kind": "section", "label": "Kitchen"},
                         {k: st["target"][k] for k in ("kind", "label")},
                         "the suggestion names the section, not a card called by its title")
        self.assertIn("Target: the section “Kitchen”", task["prompt"])
        self.assertNotIn("the card “Move the hallway", task["prompt"])
        self.assertIn("this came from a suggestion Morph made (“Move the hallway above the kitchen”)",
                      task["prompt"])

    def test_a_question_answer_and_undo_and_a_redo_say_where_they_came_from(self):
        def work(task):
            if len(fake.seen) == 1:
                return {"data": {"summary": "Added", "files": [], "home_assistant": ["input_boolean.guest"],
                                 "question": {"text": "Keep a history?", "options": [
                                     {"label": "In the card", "request": "Keep it in the card."},
                                     {"label": "A sensor", "request": "Make a sensor."}]}}}
            return OK
        fake = self.brain(work)
        first = self.tell({"kind": "dashboard"}, "Add a guest switch and make the helper for it")

        async def answer():
            return await finish(self.env, self.env.tell.answer_question(first["id"], 0))
        asyncio.run(answer())
        task = fake.seen[-1]
        self.assertEqual("Keep it in the card.", task["person_words"])
        self.assertIn("Origin: this is the answer the person pressed to your question “Keep a history?”",
                      task["prompt"])
        self.assertIn("→ you said: “Added”", task["prompt"], "brAIn's own words, as brAIn's")
        self.assertNotIn("you answered:", task["prompt"])

        async def undo():
            out = self.env.tell.undo(first["id"])
            return await finish(self.env, self.env.tell.read_state(out["follow"]))
        follow = asyncio.run(undo())
        task = fake.seen[-1]
        self.assertEqual("house", follow["scope"])
        self.assertTrue(task["person_words"].startswith("Put back the Home Assistant changes"))
        self.assertIn("input_boolean.guest", task["prompt"])
        self.assertIn("Origin: this is Undo.", task["prompt"])
        self.assertNotIn("WHERE THIS LIVES", task["prompt"], "no dashboard YAML for a house undo")
        self.assertNotIn("picture", task["prompt"])

        self.tell({"kind": "code", "id": "styles.js", "label": "styles.js"}, "Make it again", origin="redo")
        task = fake.seen[-1]
        self.assertEqual("", task["person_words"], "nobody typed a redo")
        self.assertIn("Origin: Morph is asking, not a person.", task["prompt"])
        self.assertNotIn("came from a suggestion, or an", task["prompt"])

    def test_history_says_what_brain_said_and_what_morph_saw_apart(self):
        env = self.env

        def work(task):
            if len(fake.seen) == 1:
                dash, _, _ = env.store.read()
                dash["title"] = "Our house"
                env.store.write(dash)
                return {"data": {"summary": "Renamed it.", "files": ["dashboard.yaml"], "home_assistant": []}}
            return OK
        fake = self.brain(work)
        first = self.tell({"kind": "dashboard"}, "Call it Our house")
        self.tell({"kind": "dashboard"}, "Shorter", first["id"])
        text = fake.seen[-1]["prompt"]
        self.assertIn("asked “Call it Our house” → you said: “Renamed it.” → Morph read back: "
                      "The title is now “Our house”.", text)

    def test_turns_past_the_kept_ones_are_counted(self):
        prev = [{"text": f"turn {i}", "summary": "ok", "shows": []} for i in range(6)]
        text = self.env.tell.build_prompt({"kind": "dashboard"}, "again", "", prev, earlier=3)
        self.assertIn("(3 earlier turns not shown.)", text)
        self.assertEqual(6, text.count("→ you said: “ok”"), "every kept turn is shown")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestTheAnswer(_Base):

    def test_the_schema_requires_what_morph_cannot_derive(self):
        schema = self.env.tell.RESULT_SCHEMA
        self.assertEqual(["summary", "files", "home_assistant"], schema["required"])
        self.assertNotIn("reload", schema["required"])
        self.assertIs(False, schema["additionalProperties"])
        self.assertIs(False, schema["properties"]["question"]["additionalProperties"])
        facts = schema["properties"]["facts"]["items"]["properties"]
        self.assertEqual(["high", "medium"], facts["confidence"]["enum"])

    def test_undo_reads_home_assistant_and_falls_back_to_changed(self):
        house = self.env.tell.house_changes
        self.assertEqual(["automation.morph_lights"],
                         house({"files": ["morph dashboard"], "home_assistant": ["automation.morph_lights"]}),
                         "a house change whose name says morph is still the house's")
        self.assertEqual(["input_boolean.guest"], house({"changed": ["dashboard.yaml", "input_boolean.guest"]}))
        self.assertEqual([], house({"files": ["dashboard.yaml"], "home_assistant": []}))

    def test_facts_carry_the_confidence_brain_states_and_person_subjects(self):
        (self.env.brain_shared / "memory").mkdir(parents=True)
        n = self.env.tell.queue_facts([
            {"fact": "Ben works in the study", "subject": "person:ben", "confidence": "high"},
            {"fact": "The lamp is in the hall", "subject": "light.lamp"},
            {"fact": "Odd one", "confidence": "certain"}], "morph-abc")
        self.assertEqual(3, n)
        f = next((self.env.brain_shared / "memory" / "inbox").glob("*.jsonl"))
        rows = [json.loads(x) for x in f.read_text().splitlines()]
        self.assertEqual(["high", "medium", "medium"], [r["confidence"] for r in rows])
        self.assertEqual("person:ben", rows[0]["subject"])

    def test_a_tell_that_failed_teaches_no_lesson(self):
        self.brain(lambda task: {"status": "failed", "error": "auth", "result": "signed out",
                                 "data": {"lesson": "Never do that"}})
        self.tell({"kind": "dashboard"}, "Anything")
        self.assertEqual([], self.env.learning.read_lessons())


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestLearnedMdHasThreeWriters(_Base):

    def write(self, text):
        self.env.paths.LEARNED.write_text(text, encoding="utf-8")

    def test_an_unmarked_line_is_the_households(self):
        self.write("# mine\n\n- Kitchen goes first\n- Small titles (learned)\n")
        rows = self.env.learning.read_lesson_rows()
        self.assertEqual([("Kitchen goes first", "you"), ("Small titles", "learned")],
                         [(r["text"], r["source"]) for r in rows])

    def test_a_pass_cannot_drop_or_reword_a_line_somebody_typed(self):
        self.write("- Kitchen goes first\n- Small titles (learned)\n")
        fake = self.brain(lambda task: {"data": {"suggestions": [], "lessons": [
            {"text": "Kitchen section goes first always"},          # a rewording of theirs
            {"text": "Cameras at the bottom", "evidence": ["undone twice", "declined once"]}]}})
        asyncio.run(self.env.learning.run_pass(pressed=True))
        self.assertIn("(you)", fake.seen[0]["prompt"], "the pass is told who wrote each line")
        rows = [(r["text"], r["source"]) for r in self.env.learning.read_lesson_rows()]
        self.assertIn(("Kitchen goes first", "you"), rows)
        self.assertIn(("Cameras at the bottom", "learned"), rows)
        self.assertNotIn("Kitchen section goes first always", [t for t, _ in rows])
        self.assertNotIn("Small titles", [t for t, _ in rows], "a machine line the pass dropped goes")

    def test_a_new_lesson_needs_two_pieces_of_evidence_or_a_typed_reason(self):
        env = self.env
        env.learning.add_suggestions([{"title": "Hide the camera", "change": "Hide it"}], self.dash)
        env.learning.decide(env.learning.listing()[0]["id"], "no", "We watch it at night")
        self.assertEqual([], env.learning.read_lessons(), "a reason is evidence, not a rule")
        self.brain(lambda task: {"data": {"suggestions": [], "lessons": [
            {"text": "Guessed with nothing", "evidence": ["a hunch"]},
            {"text": "Invented note", "evidence": ["note: we hate blue"]},
            {"text": "Cameras stay visible at night", "evidence": ["note: We watch it at night"]}]}})
        asyncio.run(env.learning.run_pass(pressed=True))
        self.assertEqual(["Cameras stay visible at night"], env.learning.read_lessons())
        self.assertIn("2 new lessons without enough evidence", env.learning.state()["last_note"])

    def test_the_cap_drops_the_oldest_machine_line_never_a_persons(self):
        L = self.env.learning
        lines = ["Theirs one"] + [f"Machine {i} (tell)" for i in range(L.MAX_LESSONS)]
        L.write_lessons(lines)
        rows = L.read_lesson_rows()
        self.assertEqual(L.MAX_LESSONS, len(rows))
        self.assertEqual(("Theirs one", "you"), (rows[0]["text"], rows[0]["source"]))
        self.assertNotIn("Machine 0", [r["text"] for r in rows])

    def test_a_tells_lesson_is_marked_as_one(self):
        self.brain(lambda task: {"data": {"summary": "ok", "files": [], "home_assistant": [],
                                          "lesson": "Short titles"}})
        self.tell({"kind": "dashboard"}, "Shorter title")
        self.assertEqual([("Short titles", "tell")],
                         [(r["text"], r["source"]) for r in self.env.learning.read_lesson_rows()])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestTheLearningPassEvidence(_Base):

    def test_an_undone_tell_says_what_was_rejected(self):
        env = self.env

        def work(task):
            dash, _, _ = env.store.read()
            dash["greeting"] = False
            env.store.write(dash)
            return {"data": {"summary": "Hid it", "files": ["dashboard.yaml"], "home_assistant": []}}
        self.brain(work)
        st = self.tell({"kind": "dashboard"}, "Hide the greeting")
        env.tell.undo(st["id"])
        d = env.learning.digest(env.store.read()[0])
        self.assertEqual(["The greeting is hidden."], d["tells"][-1]["rejected"])
        text = env.learning.build_prompt(d, "", [], {}, [])
        self.assertIn("The greeting is hidden.", text)

    def test_the_card_types_are_in_the_prompt(self):
        text = (self.env.paths.DEFAULTS / "AGENTS.md").read_text(encoding="utf-8")
        self.env.paths.AGENTS.write_text(text, encoding="utf-8")
        d = self.env.learning.digest(self.dash)
        prompt = self.env.learning.build_prompt(d, "", [], {}, [])
        self.assertIn("### Card types Morph draws itself", prompt)
        self.assertIn("| `readings` |", prompt)
        self.assertIn("Nothing floats over anything", prompt)

    def test_the_fingerprint_moves_after_thirty_tells(self):
        L = self.env.learning
        for i in range(31):
            L.record_outcome({"kind": "tell", "id": f"t{i}", "text": "x", "phase": "done", "at": time.time()})
        before = L.fingerprint(L.digest(self.dash))
        L.record_outcome({"kind": "tell", "id": "t31", "text": "x", "phase": "done", "at": time.time() + 1})
        self.assertNotEqual(before, L.fingerprint(L.digest(self.dash)))

    def test_long_lists_are_cut_by_item_and_say_how_many(self):
        L = self.env.learning
        items = [{"asked": "x" * 300, "phase": "done", "undone": False} for _ in range(30)]
        text = L.fit(items, 4000, "changes", newest=True)
        body, note = text.rsplit("\n", 1)
        self.assertIsInstance(json.loads(body), list, "whole items, never a cut mid-token")
        self.assertRegex(note, r"^\(\d+ more changes not shown, the oldest\.\)$")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestTheDevloopHandoff(_Base):

    def test_a_looks_report_is_marked_ux(self):
        self.env.switch(development_loop=True)
        self.env.devloop.note_request("The header is too tall on a phone", ui=True)
        self.env.devloop.note_request("Suggestions come back after No", ui=False)
        rows = {r["where"]: r for r in self.env.devloop.rows()}
        self.assertIs(True, rows["Morph · Looks"].get("ux"))
        self.assertNotIn("ux", rows["Morph · From you"])

    def test_a_code_suggestion_sent_as_an_issue_carries_its_evidence(self):
        L = self.env.learning
        self.env.switch(development_loop=True)
        L.add_suggestions(L.code_suggestions([{"what": "The fan card cannot show speed", "detail": "Add it",
                                               "why": "Opened 30 times, slid 0"}]), self.dash)
        sid = L.listing()[0]["id"]
        self.assertTrue(L.decide(sid, "send")["ok"])
        self.assertIn("Opened 30 times, slid 0", self.env.devloop.rows()[0]["body"])

    def test_a_house_card_that_will_not_load_comes_back_to_the_house(self):
        env = self.env
        env.paths.CARDS_DIR.mkdir(parents=True, exist_ok=True)
        (env.paths.CARDS_DIR / "pets.js").write_text("syntax error(")
        rows = [{"kind": "card", "card_type": "custom", "ts": time.time(),
                 "message": "Card code pets.js failed to load: Unexpected token"},
                {"kind": "card", "card_type": "custom", "ts": time.time(),
                 "message": "Card code gone.js failed to load: 404"}]
        env.paths.ERRORS.write_text("".join(json.dumps(r) + "\n" for r in rows))
        env.devloop.ingest_errors()
        self.assertEqual(["A custom card failed to draw: Card code gone.js failed to load: 404"],
                         [r["what"] for r in env.devloop.rows()],
                         "only a file the house does not have is Morph's to look at")
        sug = env.learning.listing()
        self.assertEqual(["Fix the card code pets.js"], [s["title"] for s in sug])
        self.assertIn("Unexpected token", sug[0]["change"])
        # Fixed, then broken again: offered again.
        env.learning.settle_doing(lambda _id: {})
        sug[0]["status"] = "done"
        data = env.learning._load()
        data["items"][0]["status"] = "done"
        env.learning._save(data)
        self.assertTrue(env.learning.house_card_broken("pets.js", "Unexpected token again"))
        self.assertEqual(1, len(env.learning.listing()))


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestMergeAll(_Base):
    """An update that paused several copies is ONE press: one Tell names
    every file, merges what merges, asks about a conflict, keeps exactly
    the undecided ones paused, and lands as one commit."""

    def setUp(self):
        super().setUp()
        code = self.env.morph_dir / "frontend"
        code.mkdir()
        for name in ("styles.js", "cards.js"):
            own = (self.env.shipped / name).read_text()
            (code / name).write_text(own + f"/* this house's change to {name} */\n")
        self.env.gitrepo.commit("brAIn: two changes", "brain")
        for name in ("styles.js", "cards.js"):
            p = self.env.shipped / name
            p.write_text(p.read_text() + "/* next release */\n")

    def rows(self):
        return {r["name"]: r["status"] for r in self.env.morphcode.status()}

    def test_one_tell_names_both_and_the_conflict_stays_paused(self):
        self.assertEqual({"styles.js": "paused", "cards.js": "paused"}, self.rows())
        env = self.env

        def work(task):
            if len(fake.seen) == 1:
                own = (env.shipped / "styles.js").read_text()
                (env.morph_dir / "frontend" / "styles.js").write_text(own + "/* merged */\n")
                return {"data": {"summary": "Merged styles.js; cards.js needs you.",
                                 "files": ["frontend/styles.js"], "home_assistant": [],
                                 "waiting": ["cards.js"],
                                 "question": {"text": "Where should the new card go?", "options": [
                                     {"label": "Keep mine", "request": "Keep my card in /config/morph/frontend/cards.js."},
                                     {"label": "Use Morph's own", "request": "Delete /config/morph/frontend/cards.js."}]}}}
            return {"data": {"summary": "Kept yours.", "files": [], "home_assistant": []}}
        fake = self.brain(work)
        morphd = importlib.import_module("morphd")
        head = env.gitrepo.head()

        async def go():
            out = await morphd.handle("code_merge_all", {})
            again = await morphd.handle("code_merge_all", {})
            return out, again, await finish(env, env.tell.read_state(out["id"]))
        out, again, st = asyncio.run(go())
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["id"], again["id"], "a second press shows the running merge")
        self.assertEqual(1, len(fake.seen), "one Tell for every paused copy")
        task = fake.seen[0]
        self.assertEqual("Merge all paused copies", task["person_words"])
        for name in ("styles.js", "cards.js"):
            self.assertIn(f"## {name}", task["prompt"])
            self.assertIn(f".base/{name}", task["prompt"], "the original each change was made against")
        self.assertEqual({"styles.js": "active", "cards.js": "paused"}, self.rows(),
                         "what merged is in use; the conflict waits for the person")
        self.assertEqual(["styles.js"], st["merged"])
        self.assertNotIn("code_issue", st, "a merge re-makes a change already offered as an issue")
        log = env.gitrepo.log()
        self.assertEqual(head, log[1]["sha"], "one commit for the whole merge")
        self.assertIn("frontend/styles.js", env.gitrepo.changed_files(st["commit"]))
        self.assertIn("frontend/.base.json", env.gitrepo.changed_files(st["commit"]))

        async def answer():
            return await finish(env, env.tell.answer_question(st["id"], 0))
        second = asyncio.run(answer())
        self.assertEqual("Keep my card in /config/morph/frontend/cards.js.", fake.seen[-1]["person_words"])
        self.assertIn("Then carry on with the rest of this merge.", fake.seen[-1]["prompt"])
        self.assertEqual(["cards.js"], second["merge"])
        self.assertEqual({"styles.js": "active", "cards.js": "active"}, self.rows())

    def test_a_question_with_no_waiting_list_leaves_every_file_paused(self):
        fake = self.brain(lambda task: {"data": {
            "summary": "Need you", "files": [], "home_assistant": [],
            "question": {"text": "Which?", "options": [{"label": "A", "request": "a"},
                                                       {"label": "B", "request": "b"}]}}})
        morphd = importlib.import_module("morphd")

        async def go():
            out = await morphd.handle("code_merge_all", {})
            return await finish(self.env, self.env.tell.read_state(out["id"]))
        asyncio.run(go())
        self.assertEqual(1, len(fake.seen))
        self.assertEqual({"styles.js": "paused", "cards.js": "paused"}, self.rows(), "nothing is guessed")

    def test_the_per_file_words_are_unchanged_by_the_shared_builder(self):
        words = self.env.morphcode.redo_words("styles.js", "0.5.10", [])
        self.assertTrue(words.startswith("Make my change to Morph's styles.js again on the new Morph (0.5.10)."))
        self.assertIn("do not guess", words)
        both = self.env.morphcode.redo_all_words(["styles.js", "cards.js"], "0.5.10")
        self.assertIn("three-way merge", both)
        self.assertIn("`waiting`", both)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestTheAskBar(unittest.TestCase):
    """A device command that mentions one of the page's nouns is the
    house's, and a dashboard change is still a Tell."""

    def ask(self, phrases):
        script = textwrap.dedent(f"""
            import {{ isDashChange, ASK_CONTEXT }} from {json.dumps((FRONTEND / 'util.js').as_uri())};
            console.log(JSON.stringify({{ got: {json.dumps(phrases)}.map(isDashChange), ctx: ASK_CONTEXT }}));
        """)
        r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    def test_device_commands_are_not_dashboard_changes(self):
        house = ["turn on the card table lamp", "Put the card table lamp on", "Make the card table lamp brighter",
                 "turn off the chart room light", "dim the section lights"]
        page = ["Move the kitchen card up", "Make the chart bigger", "hide the story",
                "remove the camera tile", "turn off the card on the dashboard and add a tile"]
        out = self.ask(house + page)
        self.assertEqual([False] * len(house) + [True] * len(page), out["got"])
        self.assertIn("Morph’s own page is changed with Morph’s Tell", out["ctx"])
        self.assertIn("do not claim to have changed it", out["ctx"])

    def test_the_panel_uses_them(self):
        panel = (FRONTEND / "morph-panel.js").read_text()
        self.assertIn("isDashChange(q)", panel)
        self.assertIn("extra_system_prompt: ASK_CONTEXT", panel)
        self.assertNotIn("const DASH_CHANGE", panel)


class TestAgentsMd(unittest.TestCase):
    """The guide brAIn reads: complete, and split into how Morph works for
    any face and the Tell answer as reference."""

    @classmethod
    def setUpClass(cls):
        cls.text = (Path(__file__).resolve().parent.parent / "brain" / "morph" / "defaults" / "AGENTS.md").read_text()

    def test_the_schema_is_complete(self):
        for key in ("hidden:", "unit", "type: lovelace", "options", "cards:", "sections:"):
            self.assertIn(key, self.text)

    def test_every_frontend_module_is_listed(self):
        for f in sorted(FRONTEND.glob("*.js")):
            self.assertIn(f"`{f.name}`", self.text, f.name)

    def test_all_thirteen_design_rules(self):
        body = self.text[self.text.index("## The design rules"):]
        body = body[:body.index("\n## ", 5)]
        self.assertEqual([str(i) for i in range(1, 14)],
                         [ln.split(".", 1)[0] for ln in body.splitlines() if ln[:1].isdigit()])

    def test_the_sections_the_audit_asked_for(self):
        for heading in ("# How Morph works", "# Answering a Tell (reference)", "## Checking your change",
                        "## When to ask instead of act", "## Custom card code"):
            self.assertIn(heading, self.text)
        self.assertLess(self.text.index("# How Morph works"), self.text.index("# Answering a Tell"))
        self.assertIn("it is what runs Morph's own\n   panel when your copy fails to load", self.text,
                      "the boot.js rule says why")

    def test_the_pointers_stay_pointers(self):
        defaults = Path(__file__).resolve().parent.parent / "brain" / "morph" / "defaults"
        for name in ("CLAUDE.md", "cards-README.md"):
            self.assertLess(len((defaults / name).read_text().splitlines()), 10, name)


if __name__ == "__main__":
    unittest.main()
