"""The loop's lessons are data, and LESSONS.md is their rendering (plan 2.5).

``lessons.json`` is the record; ``LESSONS.md`` is rendered from it by
``scripts/lessons.py`` and must equal that rendering, so nobody edits the
index by hand and the two cannot disagree. Every lesson says how it is
held (a guard rule, a test, a hook, or only prose), stale ones retire, and
the index stays short.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "fix-from-house"
SCRIPTS = SKILL / "scripts"


def _load(filename: str, name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load("lessons.py", "ffh_test_lessons")


def data() -> dict:
    return json.loads((SKILL / "lessons.json").read_text(encoding="utf-8"))


class TestTheShippedLessons(unittest.TestCase):
    def test_lessons_md_is_the_rendering_of_lessons_json(self):
        rendered = L.render(data())
        on_disk = (SKILL / "LESSONS.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, rendered,
                         "LESSONS.md was edited by hand or lessons.json changed without "
                         "a render: run `python3 .claude/skills/fix-from-house/scripts/"
                         "lessons.py render --write`.")

    def test_the_json_is_valid_and_the_index_is_short(self):
        d = L.validate(data())
        self.assertGreater(len(d["lessons"]), 10)
        self.assertLessEqual(L.render(d).count("\n"), L.MAX_LINES)

    def test_the_stale_human_gates_are_retired(self):
        # Section 0: no person in the loop. A lesson that still sends work
        # to a person, or names the gone needs_human_paths, is retired.
        for item in data()["lessons"]:
            text = (item["rule"] + " " + item["evidence"]).lower()
            for word in ("needs_human", "needs-human", "to a person",
                         "a person's design call", "handed to a person"):
                self.assertNotIn(word, text, item["id"])
        retired = {x["id"] for x in data()["retired"]}
        self.assertIn("2026-10-13-needs-human-paths", retired)

    def test_tested_lessons_name_tests_that_exist(self):
        for item in data()["lessons"]:
            if item["enforced_by"].startswith("test:"):
                self.assertTrue((ROOT / item["enforced_by"][5:]).exists(), item["id"])

    def test_the_loop_health_prose_left_for_runs_jsonl(self):
        text = (SKILL / "LESSONS.md").read_text(encoding="utf-8")
        self.assertNotIn("## Loop health", text)
        self.assertIn("runs.jsonl", text)


class TestTheRules(unittest.TestCase):
    def test_bad_lessons_are_refused(self):
        good = data()
        cases = {
            "bad id": {"id": "lesson one"},
            "bad enforcement": {"enforced_by": "vibes"},
            "missing test": {"enforced_by": "test:tests/test_nothing_here.py"},
            "two lines": {"rule": "a\nb"},
            "dates": {"first_seen": "2026-11-01", "last_relevant": "2026-10-01"},
            "empty": {"evidence": " "},
        }
        for why, change in cases.items():
            with self.subTest(why=why):
                d = copy.deepcopy(good)
                d["lessons"][0].update(change)
                with self.assertRaises(L.LessonError):
                    L.validate(d)
        d = copy.deepcopy(good)
        d["lessons"].append(copy.deepcopy(d["lessons"][0]))
        with self.assertRaises(L.LessonError):
            L.validate(d)

    def test_stale_retire_and_promote(self):
        d = copy.deepcopy(data())
        lid = d["lessons"][0]["id"]
        d["lessons"][0]["first_seen"] = d["lessons"][0]["last_relevant"] = "2026-08-01"
        self.assertIn(lid, L.stale(d, date(2026, 11, 4)))
        self.assertNotIn(lid, L.stale(d, date(2026, 9, 1)))
        L.retire(d, lid, date(2026, 11, 4), "not relevant for 60 days")
        self.assertNotIn(lid, [x["id"] for x in d["lessons"]])
        L.validate(d)
        prose = next(x["id"] for x in d["lessons"] if x["enforced_by"] == "prose")
        with self.assertRaises(L.LessonError):
            L.promote(d, prose, "test:tests/test_never_written.py", date(2026, 11, 4))
        with self.assertRaises(L.LessonError):
            L.promote(d, prose, "prose", date(2026, 11, 4))
        L.promote(d, prose, "test:tests/test_fix_from_house_lessons.py", date(2026, 11, 4))
        item = next(x for x in d["lessons"] if x["id"] == prose)
        self.assertEqual(item["enforced_by"], "test:tests/test_fix_from_house_lessons.py")
        self.assertEqual(item["last_relevant"], "2026-11-04")

    def test_an_index_over_the_cap_is_refused(self):
        d = copy.deepcopy(data())
        base = d["lessons"][0]
        for i in range(200):
            d["lessons"].append(dict(base, id=f"2026-11-04-filler-{i}"))
        with self.assertRaises(L.LessonError):
            L.render(d)

    def test_the_cli_writes_json_and_index_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lessons.json"
            path.write_text(json.dumps(data()))
            rc = L.main(["--file", str(path), "add", "--id", "2026-11-04-new-thing",
                         "--rule", "A new rule.", "--evidence", "It happened (#1).",
                         "--today", "2026-11-04"])
            self.assertEqual(rc, 0)
            self.assertEqual(L.main(["--file", str(path), "dates", "--retro", "2026-11-04",
                                     "--notes", "2026-11-04"]), 0)
            self.assertEqual(L.main(["--file", str(path), "check"]), 0)
            md = (Path(tmp) / "LESSONS.md").read_text()
        self.assertIn("2026-11-04-new-thing", md)
        self.assertIn("Last retro: 2026-11-04", md)
        self.assertIn("Last notes consolidation: 2026-11-04", md)


if __name__ == "__main__":
    unittest.main()
