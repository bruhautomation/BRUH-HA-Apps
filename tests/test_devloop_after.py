"""The after picture: a fixed screen, photographed once the fix is installed (plan 3.4).

For a `look` or `unmet` report the cloud closed fixed, once the house runs
the release, the house photographs the screen the report names (through
the Screens capture, redacted and guarded), uploads it beside the Screens
pictures and posts one ``brain-after`` comment naming the before and after
paths. Nothing waits on the owner's answer. A report naming no screen gets
no picture rather than a guess.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import TOKEN, DevloopCase  # noqa: E402

from devloop import after, blocks, screens  # noqa: E402

SCREENS = [{"slug": s, "label": label, "url": "x", "script": ""}
           for s, label, _ in screens.SCREENS]
PNG = b"\x89PNG\r\n\x1a\n" + b"after" * 10


def report(**kw) -> dict:
    entry = {"fp": "ab12cd34ef56ab12", "stream": "look", "state": "sent", "issue": 1,
             "where": "Fix: Settings › Notifications hides the quiet hours",
             "what": "Quiet hours are below the fold", "verdict": "fixed",
             "fixed_in": "2.17.1", "closed_at": time.time() - 3600, "version": "2.17.0"}
    entry.update(kw)
    return entry


class TestWhichScreen(unittest.TestCase):
    def test_the_longest_name_in_the_words_wins(self):
        self.assertEqual(after.match_screen(report(), SCREENS)["slug"], "settings-notify")
        self.assertEqual(after.match_screen(report(where="Fix: Settings is crowded"),
                                            SCREENS)["slug"], "settings")
        self.assertIsNone(after.match_screen(report(where="Fix: The brief is long",
                                                    what="Too many words"), SCREENS))

    def test_due_only_once_the_fix_runs_and_once_per_fix(self):
        items = {"a": report()}
        self.assertEqual(after.due(items, "2.17.0", {}, {}), [])
        self.assertEqual(len(after.due(items, "2.17.1", {}, {})), 1)
        self.assertEqual(after.due(items, "2.17.1", {}, {"ab12cd34ef56ab12": {
            "fixed_in": "2.17.1"}}), [])
        self.assertEqual(after.due({"a": report(stream="gaps")}, "2.17.1", {}, {}), [])
        self.assertEqual(after.due({"a": report(verdict="declined")}, "2.17.1", {}, {}), [])

    def test_before_is_the_newest_screens_picture_older_than_the_fix(self):
        name = "settings-notify-390-light.png"
        sha = hashlib.sha256(b"x").hexdigest()

        def shots(version):
            return {"stream": "screens", "version": version, "rolling": True,
                    "gallery": [{"name": name, "screen": "Settings › Notifications",
                                 "width": 390, "scheme": "light", "sha": sha}],
                    "uploaded": {name: {"sha": sha, "url": "u"}}}
        items = {"a": shots("2.16.0"), "b": shots("2.17.0"), "c": shots("2.17.1")}
        scr = after.match_screen(report(), SCREENS)
        self.assertEqual(after.before_path(items, "brAIn", scr, "2.17.1"),
                         f"screens/brain-2.17.0/{name}")
        self.assertIsNone(after.before_path({}, "brAIn", scr, "2.17.1"))


class TestThePass(DevloopCase):
    def run_pass(self, items, version="2.17.1"):
        target = screens.own_target("http://127.0.0.1:1/")
        calls = []

        async def capture(tgt, scr):
            calls.append((tgt["product"], scr["slug"]))
            return PNG, f"{scr['slug']}-390-light.png"
        n = asyncio.run(after.run_pass(token=TOKEN, repo="me/reports", items=items,
                                       version=version, products={}, catalog=[target],
                                       capture=capture))
        return n, calls

    def test_the_picture_is_uploaded_and_the_block_posted_once(self):
        self.switch_on()
        self.gh.issues.append({"number": 1, "state": "closed", "body": "", "labels": []})
        items = {"ab12cd34ef56ab12": report()}
        n, calls = self.run_pass(items)
        self.assertEqual((n, calls), (1, [("brAIn", "settings-notify")]))
        path = "screens/brain-2.17.1/settings-notify-390-light.png"
        self.assertEqual(self.gh.files[path], PNG)
        [(number, body)] = self.gh.comments
        obj = blocks.parse_block("after", body)
        self.assertEqual(number, 1)
        self.assertEqual({k: obj[k] for k in ("v", "fp", "release", "before", "after")},
                         {"v": 1, "fp": "ab12cd34ef56ab12", "release": "2.17.1",
                          "before": "", "after": path})
        self.assertEqual(self.run_pass(items), (0, []), "once per fix")

    def test_a_report_naming_no_screen_is_not_photographed(self):
        self.switch_on()
        items = {"ab12cd34ef56ab12": report(where="Fix: The brief is long", what="Words")}
        self.assertEqual(self.run_pass(items), (0, []))
        self.assertEqual(json.loads(after.state_file().read_text())["ab12cd34ef56ab12"]
                         ["skipped"], "no screen named")

    def test_a_capture_that_fails_is_tried_again(self):
        self.switch_on()
        items = {"ab12cd34ef56ab12": report()}

        async def broken(tgt, scr):
            raise RuntimeError("Chromium went away")
        n = asyncio.run(after.run_pass(token=TOKEN, repo="me/reports", items=items,
                                       version="2.17.1", products={},
                                       catalog=[screens.own_target()], capture=broken))
        self.assertEqual(n, 0)
        self.assertEqual(len(after.due(items, "2.17.1", {}, after.load())), 1)


if __name__ == "__main__":
    unittest.main()
