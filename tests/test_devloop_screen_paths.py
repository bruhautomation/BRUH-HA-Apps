#!/usr/bin/env python3
"""Every add-on's Screens pictures reach the reports repository, and one
add-on's new Screens issue closes only that add-on's old one.

Two seams the Screens stream opened when it began photographing the other
BRUH add-ons, each driven against the loopback GitHub `test_devloop`
stands up:

  * the uploader admitted only `screens/brain-<version>/…`, while
    `screens.repo_path` writes `screens/<product>-<version>/…`, so every
    other add-on's pictures were refused and its issue never filed;
  * a new rolling issue closed every other rolling issue of its stream, and
    the Screens stream has one per add-on, so filing Morph's closed brAIn's.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import test_devloop as base  # noqa: E402

import devloop  # noqa: E402
import devloop.screens as screens  # noqa: E402
import devloop.siblings as siblings  # noqa: E402

github = base.github
upstream = base.upstream


class TestEveryProductsFolderIsWritable(unittest.TestCase):
    def test_every_product_repo_path_writes_is_a_path_the_uploader_takes(self):
        names = ("insights-390-light.png", "x-1200-dark.png",
                 # SHOT_RE's longest slug: the uploader must take every name
                 # the capture may write.
                 "a" * 60 + "-390-light.png")
        for name in names:
            self.assertRegex(name, screens.SHOT_RE)
        for product in ("brAIn", "Morph", *siblings.PRODUCTS):
            for version in ("4.0.30", "0.1.1", "dev", "1.2.3-beta.1"):
                for name in names:
                    path = screens.repo_path(version, name, product)
                    self.assertRegex(path, github.FILE_PATH_RE, (product, version, name))

    def test_each_product_has_its_own_folder(self):
        self.assertEqual(screens.repo_path("0.1.1", "x-390-light.png", "GardenRX"),
                         "screens/gardenrx-0.1.1/x-390-light.png")
        self.assertEqual(screens.repo_path("1.0.0", "x-390-light.png", "BRUH Bambu Studio"),
                         "screens/bruh-bambu-studio-1.0.0/x-390-light.png")

    def test_anything_else_is_still_refused(self):
        for path in ("README.md", "screens/brain-1.0/../../x-390-light.png",
                     "screens/Brain-1.0/x-390-light.png",
                     "screens/brain-1.0/x-390-light.jpg",
                     "docs/brain-1.0/x-390-light.png",
                     "screens/brain-1.0/sub/x-390-light.png"):
            self.assertIsNone(github.FILE_PATH_RE.match(path), path)


def _shot(name: str, screen: str, product: str, payload: bytes) -> dict:
    return {"name": name, "screen": screen, "width": 390, "scheme": "light",
            "sha": hashlib.sha256(payload).hexdigest(), "product": product}


class ScreensCase(base.DevloopCase):
    def capture(self, cap: str, shots: list[tuple[str, str, str]], versions: dict,
                brain: str = "2.17.0") -> None:
        """Write each picture where a capture keeps it and file the rows."""
        d = devloop.DATA_DIR / "screens" / cap
        d.mkdir(parents=True, exist_ok=True)
        kept = []
        for name, screen, product in shots:
            payload = f"\x89PNG {cap} {name}".encode()
            (d / name).write_bytes(payload)
            kept.append(_shot(name, screen, product, payload))
        rows = screens.rows({"shots": kept, "problems": [], "errors": []},
                            brain, cap, versions=versions)
        upstream.ingest("screens", rows, base.diagnostics(version=brain), base.NAMES)

    def issue_titled(self, word: str) -> dict:
        return next(i for i in self.gh.issues if word in i["title"])


class TestAnotherAddonsScreensAreFiled(ScreensCase):
    def test_gardenrx_pictures_go_under_its_folder_and_its_issue_is_filed(self):
        self.switch_on()
        self.capture("1700000000", [("gardenrx-today-390-light.png", "GardenRX › Today",
                                     "GardenRX")], {"GardenRX": "0.3.1"})
        upstream.send_due()
        self.assertEqual(list(self.gh.files),
                         ["screens/gardenrx-0.3.1/gardenrx-today-390-light.png"])
        row = next(r for r in upstream.listing() if r["stream"] == "screens")
        self.assertFalse(row.get("error"), row.get("error"))
        issue = self.issue_titled("GardenRX")
        self.assertIn("screens/gardenrx-0.3.1/gardenrx-today-390-light.png?raw=true",
                      issue["body"])
        self.assertIn({"name": "devloop:gardenrx"}, issue["labels"])


class TestOnlyTheSameAddonIsSuperseded(ScreensCase):
    SHOTS = [("insights-390-light.png", "Insights", "brAIn"),
             ("gardenrx-today-390-light.png", "GardenRX › Today", "GardenRX"),
             ("morph-dashboard-390-light.png", "Morph › Dashboard", "Morph")]

    def test_filing_one_addons_screens_leaves_the_others_open(self):
        self.switch_on()
        self.capture("1700000000", self.SHOTS, {"GardenRX": "0.3.1", "Morph": "2.17.0"})
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 3)
        self.assertEqual([i["state"] for i in self.gh.issues], ["open"] * 3,
                         [i["title"] for i in self.gh.issues])

        # A new GardenRX release: its new issue retires its old one, and only it.
        self.capture("1700000500", [self.SHOTS[1]], {"GardenRX": "0.3.2"})
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 4)
        old = next(i for i in self.gh.issues[:3] if "GardenRX" in i["title"])
        self.assertEqual(old["state"], "closed")
        self.assertIn((old["number"], "Superseded by #4 (GardenRX 0.3.2)."),
                      self.gh.comments)
        others = [i for i in self.gh.issues[:3] if i is not old]
        self.assertEqual([i["state"] for i in others], ["open", "open"],
                         [i["title"] for i in others])

    def test_a_new_brain_release_retires_brains_alone(self):
        self.switch_on()
        self.capture("1700000000", self.SHOTS, {"GardenRX": "0.3.1", "Morph": "2.17.0"})
        upstream.send_due()
        self.capture("1700000500", [self.SHOTS[0]], {}, brain="2.17.1")
        upstream.send_due()
        closed = [i for i in self.gh.issues if i["state"] == "closed"]
        self.assertEqual(len(closed), 1, [i["title"] for i in closed])
        self.assertIn("Panel screens", closed[0]["title"])
        self.assertIn((closed[0]["number"], "Superseded by #4 (brAIn 2.17.1)."),
                      self.gh.comments)


if __name__ == "__main__":
    unittest.main()
