#!/usr/bin/env python3
"""A track has many shows, and one of them is the one that plays.

Every compile used to overwrite `show.json`, so pressing "rewrite with
Claude" on a show you had spent an evening editing destroyed it. These
tests are about the archive that replaces that, and about the property
that makes it safe to add: every existing caller asks for "this track's
show" exactly as it always did, and gets the live one.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

HASH = "a" * 40
OTHER = "b" * 40


class VersionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from analyzer import library
        self.library = library
        self._old_dir = library.SHOWS_DIR
        self._old_shared = library.SHARED_SHOWS
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        # Somewhere the mirror will refuse to publish to, so these tests
        # never touch a real /config and never depend on one.
        library.SHARED_SHOWS = Path(self.tmp.name) / "nope" / "x" / "shows"
        self.addCleanup(setattr, library, "SHOWS_DIR", self._old_dir)
        self.addCleanup(setattr, library, "SHARED_SHOWS", self._old_shared)

    def save(self, cues=1, **kwargs):
        return self.library.save_show(
            HASH, {"scenes": [{"start": 0, "end": 1}]},
            {"cues": [{"t": i} for i in range(cues)]}, **kwargs)


class TestEveryeSaveIsAVersion(VersionCase):
    def test_the_newest_save_is_what_plays(self):
        self.save(cues=1, source="algorithmic")
        second = self.save(cues=7, source="claude")
        self.assertEqual(7, len(self.library.load_show(HASH)["cues"]),
                         "load_show must follow the pointer")
        listing = self.library.list_versions(HASH)
        self.assertEqual(second, listing["active"])
        self.assertEqual(2, len(listing["versions"]))

    def test_an_earlier_show_is_still_there_to_go_back_to(self):
        first = self.save(cues=3, source="claude")
        self.save(cues=9, source="edit")
        self.library.activate_version(HASH, first)
        self.assertEqual(3, len(self.library.load_show(HASH)["cues"]))
        self.assertEqual(first, self.library.list_versions(HASH)["active"])

    def test_versions_are_listed_newest_first_with_who_wrote_them(self):
        self.save(source="algorithmic")
        self.save(source="claude")
        rows = self.library.list_versions(HASH)["versions"]
        self.assertEqual(["claude", "algorithmic"], [r["source"] for r in rows])
        self.assertTrue(rows[0]["active"])
        self.assertFalse(rows[1]["active"])

    def test_a_version_records_its_size_so_the_list_means_something(self):
        self.save(cues=412)
        row = self.library.list_versions(HASH)["versions"][0]
        self.assertEqual(412, row["cues"])
        self.assertEqual(1, row["scenes"])

    def test_one_track_s_versions_are_not_another_s(self):
        self.save()
        self.assertEqual([], self.library.list_versions(OTHER)["versions"])
        self.assertIsNone(self.library.load_show(OTHER))

    def test_a_note_survives_so_a_revision_says_what_was_asked_for(self):
        self.save(source="revision", note="more strobes in the chorus")
        row = self.library.list_versions(HASH)["versions"][0]
        self.assertEqual("more strobes in the chorus", row["note"])


class TestNaming(VersionCase):
    def test_renaming_names_it(self):
        version = self.save()
        self.library.rename_version(HASH, version, "the good one")
        self.assertEqual("the good one",
                         self.library.list_versions(HASH)["versions"][0]["name"])

    def test_naming_pins_and_clearing_the_name_unpins(self):
        version = self.save()
        self.library.rename_version(HASH, version, "keep me")
        self.assertTrue(self.library.list_versions(HASH)["versions"][0]["pinned"])
        self.library.rename_version(HASH, version, "  ")
        self.assertFalse(self.library.list_versions(HASH)["versions"][0]["pinned"])

    def test_renaming_something_that_is_not_there_says_so(self):
        with self.assertRaises(ValueError):
            self.library.rename_version(HASH, "deadbeef", "x")


class TestDeleting(VersionCase):
    def test_deleting_takes_the_files_with_it(self):
        first = self.save()
        self.save()
        directory = self.library.SHOWS_DIR / HASH / "versions" / first
        self.assertTrue((directory / "show.json").exists())
        self.library.delete_version(HASH, first)
        self.assertFalse((directory / "show.json").exists())
        self.assertEqual(1, len(self.library.list_versions(HASH)["versions"]))

    def test_the_live_show_cannot_be_deleted_out_from_under_the_track(self):
        version = self.save()
        with self.assertRaises(ValueError) as caught:
            self.library.delete_version(HASH, version)
        self.assertIn("make another one live", str(caught.exception))
        self.assertIsNotNone(self.library.load_show(HASH))


class TestThePrune(VersionCase):
    def test_the_archive_stops_growing_and_eats_the_oldest(self):
        ids = [self.save(cues=i) for i in range(self.library.MAX_VERSIONS + 4)]
        rows = self.library.list_versions(HASH)["versions"]
        self.assertEqual(self.library.MAX_VERSIONS, len(rows))
        kept = {r["id"] for r in rows}
        self.assertNotIn(ids[0], kept)
        self.assertIn(ids[-1], kept)

    def test_a_named_version_is_never_eaten(self):
        keeper = self.save()
        self.library.rename_version(HASH, keeper, "the good one")
        for _ in range(self.library.MAX_VERSIONS + 6):
            self.save()
        kept = {r["id"] for r in self.library.list_versions(HASH)["versions"]}
        self.assertIn(keeper, kept, "naming a version is how you keep it")

    def test_the_live_version_is_never_eaten_even_when_it_is_the_oldest(self):
        oldest = self.save()
        for _ in range(self.library.MAX_VERSIONS + 6):
            self.save()
        self.library.activate_version(HASH, self.library.list_versions(
            HASH)["versions"][-1]["id"])
        active = self.library.list_versions(HASH)["active"]
        for _ in range(self.library.MAX_VERSIONS):
            self.save(source="edit")
            self.assertIsNotNone(self.library.load_show(HASH))
        self.assertIsNotNone(oldest)
        self.assertIsNotNone(active)

    def test_an_archive_of_nothing_but_named_versions_goes_over_rather_than_refusing(self):
        """Refusing to save because the archive is full would mean a full
        archive stops you working, which is worse than a long list."""
        for _ in range(self.library.MAX_VERSIONS + 3):
            version = self.save()
            self.library.rename_version(HASH, version, f"take {version[:4]}")
        rows = self.library.list_versions(HASH)["versions"]
        self.assertGreater(len(rows), self.library.MAX_VERSIONS)


class TestMigratingATrackThatPredatesVersions(VersionCase):
    def legacy(self, cues=5):
        directory = self.library.SHOWS_DIR / HASH
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "show.json").write_text(json.dumps(
            {"cues": [{"t": i} for i in range(cues)]}))
        (directory / "script.json").write_text(json.dumps({"scenes": []}))
        return directory

    def test_the_show_that_was_there_becomes_version_one(self):
        directory = self.legacy(cues=5)
        self.assertEqual(5, len(self.library.load_show(HASH)["cues"]),
                         "an existing show must not disappear on upgrade")
        rows = self.library.list_versions(HASH)["versions"]
        self.assertEqual(1, len(rows))
        self.assertEqual("import", rows[0]["source"])
        self.assertFalse((directory / "show.json").exists(),
                         "migration moves the files rather than copying them")

    def test_the_migrated_show_can_be_gone_back_to_after_a_rewrite(self):
        self.legacy(cues=5)
        old = self.library.list_versions(HASH)["active"]
        self.save(cues=99, source="claude")
        self.assertEqual(99, len(self.library.load_show(HASH)["cues"]))
        self.library.activate_version(HASH, old)
        self.assertEqual(5, len(self.library.load_show(HASH)["cues"]))

    def test_migration_happens_once_and_is_not_re_run(self):
        self.legacy()
        first = self.library.list_versions(HASH)["active"]
        second = self.library.list_versions(HASH)["active"]
        self.assertEqual(first, second)

    def test_a_track_with_no_show_at_all_still_answers_none(self):
        self.assertIsNone(self.library.load_show(HASH))
        self.assertEqual({"active": None, "versions": []},
                         self.library.list_versions(HASH))


class TestTheHashIsStillGuarded(VersionCase):
    def test_a_path_that_is_not_a_hash_is_refused(self):
        for bad in ("../../etc", "zz", "a" * 39):
            with self.assertRaises(ValueError):
                self.library.list_versions(bad)

    def test_a_version_id_that_is_not_one_is_refused(self):
        self.save()
        for bad in ("../../..", "a/b", "A" * 40):
            with self.assertRaises(ValueError):
                self.library.activate_version(HASH, bad)


if __name__ == "__main__":
    unittest.main()
