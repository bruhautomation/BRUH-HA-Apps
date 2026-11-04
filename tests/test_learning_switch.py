#!/usr/bin/env python3
"""One Learning switch (self-learning plan 2.1).

⚙ › Features › Learning loop governs everything that learns: the memory
extractor, voice's `remember_fact` auto-writes, reflect, presence, Morph's
learning and memory clean-up. The add-on option `learning` used to be a
second gate over half of them; it is now only the switch's default, folded
in ONCE (`features.migrate_learning`), so a house that had `learning: false`
starts with the switch off and from then on the switch is the authority.

Every reader asks the switches' file at call time, so a flip needs no
restart: driven here through the real modules and scripts over a temporary
file, plus grep-level checks that no reader of the option is left behind.
Under the switch, ⚙ shows what each learner wrote in the last seven days
(`learning_report`), counted off the ledgers they already keep.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
BRAIN = BASE_DIR / "brain"
PANEL = BRAIN / "panel"
SCRIPTS = BRAIN / "scripts"
sys.path.insert(0, str(PANEL))

import features  # noqa: E402
import learning_report  # noqa: E402
import presence  # noqa: E402


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.file = self.root / "features.json"
        env = {k: v for k, v in os.environ.items()
               if k not in ("BRAIN_LEARNING_OPTION", "BRAIN_ASSIST_LEARNING")}
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def option(self, value: bool) -> None:
        os.environ["BRAIN_LEARNING_OPTION"] = "true" if value else "false"

    def write(self, body: dict) -> None:
        self.file.write_text(json.dumps(body), encoding="utf-8")

    def stored(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))


class TestTheMigration(FileCase):
    def test_a_house_with_learning_false_starts_with_the_switch_off(self):
        # Every house that ever opened Features has learning_loop: true
        # written as a default; the option somebody set to false wins once.
        self.write({"morph": True, "learning_loop": True})
        self.option(False)
        self.assertFalse(features.learning_on(str(self.file)))
        self.assertFalse(features.migrate_learning(str(self.file)))
        body = self.stored()
        self.assertIs(body["learning_loop"], False)
        self.assertIs(body[features.LEARNING_MIGRATED], True)
        self.assertIs(body["morph"], True, "the other switches are kept")

    def test_a_house_that_never_chose_takes_the_option(self):
        self.option(False)
        self.assertFalse(features.migrate_learning(str(self.file)))
        self.option(True)
        other = self.root / "other.json"
        self.assertTrue(features.migrate_learning(str(other)))

    def test_after_the_migration_the_switch_is_the_authority(self):
        self.option(True)
        self.write({"learning_loop": False})
        features.migrate_learning(str(self.file))
        # The option changing later does nothing in either direction.
        self.option(True)
        self.assertFalse(features.learning_on(str(self.file)))
        features.save({"learning_loop": True}, str(self.file))
        self.option(False)
        self.assertTrue(features.learning_on(str(self.file)))
        self.assertTrue(features.migrate_learning(str(self.file)))
        self.assertTrue(features.load(str(self.file))["learning_loop"])

    def test_a_save_before_the_migration_is_the_person_choosing(self):
        self.option(False)
        self.write({"learning_loop": True})
        features.save({"learning_loop": True}, str(self.file))
        self.assertTrue(features.learning_on(str(self.file)))
        self.assertIs(self.stored()[features.LEARNING_MIGRATED], True)

    def test_a_save_of_another_switch_carries_the_migrated_answer(self):
        self.option(False)
        self.write({"learning_loop": True, "morph": False})
        features.save({"morph": True}, str(self.file))
        self.assertFalse(features.learning_on(str(self.file)))

    def test_publish_marks_the_migration(self):
        self.option(False)
        self.write({"learning_loop": True})
        out = features.publish(str(self.file))
        self.assertFalse(out["learning_loop"])
        self.assertIs(self.stored()[features.LEARNING_MIGRATED], True)

    def test_the_cli_run_sh_calls_migrates_and_prints(self):
        self.write({"learning_loop": True})
        env = {**os.environ, "BRAIN_FEATURES_FILE": str(self.file),
               "BRAIN_LEARNING_OPTION": "false"}
        out = subprocess.run([sys.executable, str(PANEL / "features.py"), "learning"],
                             capture_output=True, text=True, env=env, timeout=60,
                             check=True)
        self.assertEqual(out.stdout.strip(), "false")
        self.assertIs(self.stored()["learning_loop"], False)

    def test_on_learning_loop_reads_the_switch(self):
        self.option(True)
        self.write({"learning_loop": False, features.LEARNING_MIGRATED: True})
        self.assertFalse(features.on("learning_loop", str(self.file)))


class TestEveryReaderFollowsTheSwitch(FileCase):
    """A flip of the file is seen by the next call, with no restart, and
    BRAIN_ASSIST_LEARNING (the switch at boot) only answers without it."""

    def migrated(self, on: bool) -> None:
        self.write({"learning_loop": on, features.LEARNING_MIGRATED: True})

    def test_the_memory_extractor(self):
        mod = _load_script("brain_memory_extract_switch",
                           SCRIPTS / "brain-memory-extract.py")
        mod.FEATURES_FILE = self.file
        mod.BRAIN_ENV_FILE = self.root / "no-env-file"
        os.environ["BRAIN_ASSIST_LEARNING"] = "true"
        self.migrated(False)
        self.assertFalse(mod.learning_enabled())
        self.migrated(True)
        os.environ["BRAIN_ASSIST_LEARNING"] = "false"
        self.assertTrue(mod.learning_enabled())
        self.file.unlink()
        self.assertFalse(mod.learning_enabled(), "no file: the boot value")

    def test_voice_remember_fact(self):
        mod = _load_script("brain_voice_context_switch",
                           SCRIPTS / "brain_voice_context.py")
        mod.FEATURES_FILE = str(self.file)
        os.environ["BRAIN_ASSIST_LEARNING"] = "true"
        self.migrated(False)
        self.assertFalse(mod.learning_on())
        self.assertNotIn("remember_fact in the", mod.system_prompt(household=""))
        self.migrated(True)
        self.assertTrue(mod.learning_on())
        self.assertIn("remember_fact in the", mod.system_prompt(household=""))

    def test_presence(self):
        with mock.patch.object(presence.personality, "enabled", return_value=True):
            self.write({"personality": True, "learning_loop": True})
            self.option(False)  # not migrated yet: the option still counts
            self.assertEqual(presence.active(str(self.file))[0], False)
            self.migrated(True)
            body = self.stored()
            body["personality"] = True
            self.write(body)
            self.assertTrue(presence.active(str(self.file))[0])

    def test_reflect_and_the_server(self):
        text = (PANEL / "server.py").read_text(encoding="utf-8")
        body = text.split("def _learning_on() -> bool:", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("features.learning_on()", body)
        self.assertNotIn("addon_options", body)
        # Health is asked about the switch, not the option.
        self.assertIn('safe_options["learning"] = features.learning_on()', text)
        # Memory clean-up applies a removal unasked only while it is on.
        body = text.split("async def _run_memory_cleanup()", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("features.learning_on", body)

    def test_no_reader_of_the_option_is_left_behind(self):
        readers = set()
        for path in BRAIN.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".sh", ""):
                continue
            if path.name == "CHANGELOG.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "BRAIN_ASSIST_LEARNING" in text:
                readers.add(path.relative_to(BRAIN).as_posix())
        self.assertEqual(readers, {
            "run.sh", "panel/features.py", "scripts/brain-memory-extract.py",
            "scripts/brain_voice_context.py"})
        for rel in ("scripts/brain-memory-extract.py", "scripts/brain_voice_context.py"):
            self.assertIn("features.json", (BRAIN / rel).read_text(encoding="utf-8"), rel)
        run = (BRAIN / "run.sh").read_text(encoding="utf-8")
        # The option is read once, as the switch's default, and nowhere else.
        self.assertEqual(len(re.findall(r"bashio::config 'learning'", run)), 1)
        self.assertIn("features.py learning", run)
        for fn in ("start_study_watcher", "start_memory_consolidator"):
            body = run.split(f"{fn}() {{", 1)[1].split("\n}\n", 1)[0]
            self.assertIn("BRAIN_ASSIST_LEARNING", body, fn)

    def test_the_option_says_it_is_only_the_default(self):
        en = (BRAIN / "translations" / "en.yaml").read_text(encoding="utf-8")
        block = en.split("  learning:\n", 1)[1].split("\n  memory_injection:", 1)[0]
        self.assertIn("Learning loop", block)
        self.assertIn("switch decides", block)


class TestWhatLearningWrote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = {k: getattr(learning_report, k) for k in (
            "MEMORY_DIR", "FACTS_FILE", "PERSONALITY_FILE", "PRESENCE_FILE", "MORPH_DIR")}
        learning_report.MEMORY_DIR = root / "memory"
        learning_report.FACTS_FILE = root / "memory" / "facts.json"
        learning_report.PERSONALITY_FILE = root / "personality.json"
        learning_report.PRESENCE_FILE = root / "presence.json"
        learning_report.MORPH_DIR = root / "morph"
        self.now = time.time()
        self.old = self.now - 30 * 86400
        self.recent = self.now - 86400

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(learning_report, k, v)
        self.tmp.cleanup()

    def test_an_empty_house_counts_nothing(self):
        out = learning_report.last_days(now=self.now)
        self.assertEqual(out["total"], 0)
        self.assertEqual([r["key"] for r in out["learners"]],
                         ["memory", "reflect", "presence", "morph"])

    def test_each_learner_is_counted_off_its_own_ledger(self):
        inbox = learning_report.MEMORY_DIR / "inbox"
        (inbox / "processed").mkdir(parents=True)
        lines = [{"ts": int(self.recent), "source": "conversation", "fact": "a"},
                 {"ts": int(self.recent), "source": "study:lights", "fact": "b"},
                 {"ts": int(self.old), "source": "conversation", "fact": "old"}]
        (inbox / "1-x.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines[:2]) + "\nnot json\n")
        (inbox / "processed" / "2-y.jsonl").write_text(
            json.dumps({"ts": int(self.recent), "source": "voice", "fact": "c"}) + "\n"
            + json.dumps(lines[2]) + "\n")
        learning_report.FACTS_FILE.write_text(json.dumps({"facts": [
            {"predicate": "judgement:quieter", "first_seen": int(self.recent)},
            {"predicate": "judgement:louder", "first_seen": int(self.old)},
            {"predicate": "", "first_seen": int(self.recent)}]}))
        learning_report.PERSONALITY_FILE.write_text(json.dumps({"growth": [
            {"at": int(self.recent), "text": "x", "by": "self"},
            {"at": int(self.recent), "text": "the household's own"}]}))
        learning_report.PRESENCE_FILE.write_text(json.dumps({"people": {
            "person.a": {"notes": [{"at": int(self.recent), "text": "n"},
                                   {"at": int(self.old), "text": "old"}]}}}))
        out = {r["key"]: r for r in learning_report.last_days(now=self.now)["learners"]}
        self.assertEqual(out["memory"]["count"], 3)
        self.assertEqual(out["memory"]["by_source"],
                         {"conversation": 1, "study": 1, "voice": 1})
        self.assertEqual(out["reflect"]["count"], 1)
        self.assertEqual((out["presence"]["growth"], out["presence"]["notes"]), (1, 1))
        self.assertEqual(out["morph"]["count"], 0)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_morph_learning_commits(self):
        repo = learning_report.MORPH_DIR
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

        def git(*args, author="Morph <morph@morph.local>"):
            name, email = author[:-1].split(" <")
            subprocess.run(["git", "-c", f"user.name={name}", "-c", f"user.email={email}",
                            "-c", "commit.gpgsign=false", *args],
                           cwd=repo, check=True, capture_output=True, env=env, timeout=60)

        git("init", "-q")
        (repo / "dashboard.yaml").write_text("a: 1\n")
        git("add", "-A")
        git("commit", "-qm", "person")
        (repo / "LEARNED.md").write_text("- lesson\n")
        git("add", "-A")
        git("commit", "-qm", "Learned", author="Morph learning <learning@morph.local>")
        (repo / "cards").mkdir()
        (repo / "cards" / "x.js").write_text("1\n")
        git("add", "-A")
        git("commit", "-qm", "card", author="Morph learning <learning@morph.local>")
        out = learning_report.morph(int(self.now - 7 * 86400))
        self.assertEqual(out, {"count": 2, "learned_md": 1})

    def test_the_settings_page_shows_it_under_the_switch(self):
        html = (PANEL / "index.html").read_text(encoding="utf-8")
        group = html.split('id="featLearning"', 1)[1].split('class="setgroup"', 1)[0]
        self.assertIn('id="featLearned"', group)
        self.assertNotIn("does nothing while that is off", group)
        app = (PANEL / "app.js").read_text(encoding="utf-8")
        self.assertIn("paintLearned(f.learned)", app)
        server = (PANEL / "server.py").read_text(encoding="utf-8")
        self.assertIn('out["learned"] = learning_report.last_days()', server)


if __name__ == "__main__":
    unittest.main()
