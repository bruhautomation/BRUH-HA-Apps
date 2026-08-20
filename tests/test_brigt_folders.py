#!/usr/bin/env python3
"""More than one music folder — and why every one of them is under /media.

BRigt scanned exactly one folder, the `music_folder` option, and the only
way to look anywhere else was to have put the music there. `music_folder`
plus `additional_music_folders` is the answer, with one constraint that is
not arbitrary and is therefore tested: a show plays its track by handing a
media player a `media-source://…/local/…` URI, and Home Assistant only
serves those for files under its media folder. A folder outside it would
fill the Library tab with tracks that analyze perfectly and never play.
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "brigt")
PANEL_DIR = os.path.join(ADDON_DIR, "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import yaml  # noqa: E402

from analyzer import library  # noqa: E402
from playback import conductor  # noqa: E402


def _load_server(data_dir: str, media_dir: str, options_file: str,
                 music_folder: str):
    os.environ["BRIGT_STATE"] = data_dir
    os.environ["BRIGT_MEDIA"] = media_dir
    os.environ["BRIGT_OPTIONS"] = options_file
    os.environ["BRIGT_MUSIC_FOLDER"] = music_folder
    # A path that does not exist, so `_options_from_env` falls through to the
    # environment above rather than to some other test's leftovers.
    os.environ["BRIGT_ENV_FILE"] = os.path.join(data_dir, "no-such-env")
    path = os.path.join(PANEL_DIR, "server.py")
    spec = importlib.util.spec_from_file_location("brigt_panel_folders", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _track(path: Path, marker: bytes) -> Path:
    """An audio file the scanner will pick up, unique by content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(marker * 200)
    return path


class TestScanAllDeduplicates(unittest.TestCase):
    """One track reachable by two paths is one track.

    Folders overlap the moment somebody adds a subfolder of a folder they
    already listed — which is the exact thing they were asking for — and a
    library that lists it twice is a library that analyzes it twice.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        self.addCleanup(setattr, library, "SHOWS_DIR", self._shows)

    def test_a_nested_folder_does_not_double_a_track(self):
        root = Path(self.tmp.name) / "music"
        _track(root / "a.mp3", b"a")
        _track(root / "parties" / "b.mp3", b"b")
        tracks = library.scan_all([root, root / "parties"])
        self.assertEqual(2, len(tracks))
        self.assertEqual({"a", "b"}, {t["name"] for t in tracks})

    def test_the_same_file_in_two_folders_is_one_track(self):
        one = Path(self.tmp.name) / "one"
        two = Path(self.tmp.name) / "two"
        _track(one / "song.mp3", b"same")
        _track(two / "copy.mp3", b"same")
        tracks = library.scan_all([one, two])
        self.assertEqual(1, len(tracks), tracks)
        # The one found first, so the order of the folders is the order of
        # the answer rather than something that changes between scans.
        self.assertEqual("song", tracks[0]["name"])

    def test_a_folder_that_is_not_there_is_skipped_not_fatal(self):
        one = Path(self.tmp.name) / "one"
        _track(one / "song.mp3", b"x")
        tracks = library.scan_all([Path(self.tmp.name) / "gone", one])
        self.assertEqual(1, len(tracks))


class TestFoldersMustBeServable(unittest.TestCase):
    """The /media confinement, and the reason for it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.options = os.path.join(cls.tmp.name, "options.json")
        cls.server = _load_server(cls.tmp.name, cls.media.name, cls.options,
                                  os.path.join(cls.media.name, "music"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def test_a_folder_outside_media_has_no_media_id_to_play(self):
        """Why the schema pins /media, stated as the failure it prevents."""
        self.assertIsNone(conductor.media_content_id_for(
            {"file": "/share/music/song.mp3"}))
        self.assertEqual(
            "media-source://media_source/local/music/song.mp3",
            conductor.media_content_id_for({"file": "/media/music/song.mp3"}))

    def test_both_spellings_of_a_folder_are_accepted(self):
        media = str(self.server.MEDIA_DIR)
        for typed in (f"{media}/parties", "parties", "/parties",
                      "media/parties"):
            with self.subTest(typed=typed):
                self.assertEqual(Path(media) / "parties",
                                 self.server._under_media(typed))

    def test_an_escape_is_refused(self):
        for hostile in ("../etc", "/media/../etc", "", "   "):
            with self.subTest(value=hostile):
                self.assertIsNone(self.server._under_media(hostile))

    def test_the_media_root_itself_is_allowed(self):
        media = str(self.server.MEDIA_DIR)
        self.assertEqual(Path(media), self.server._under_media(media))


class TestReadingTheOption(unittest.TestCase):
    """`additional_music_folders` is a list, and a list cannot ride the env
    file — every separator is a character a path may legally contain."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.options = os.path.join(cls.tmp.name, "options.json")
        cls.server = _load_server(cls.tmp.name, cls.media.name, cls.options,
                                  os.path.join(cls.media.name, "music"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def _options(self, payload):
        Path(self.options).write_text(json.dumps(payload))
        self.addCleanup(lambda: Path(self.options).unlink(missing_ok=True))

    def test_the_folders_come_back_in_order(self):
        media = str(self.server.MEDIA_DIR)
        self._options({"additional_music_folders": [f"{media}/parties",
                                                    f"{media}/chill"]})
        self.assertEqual([Path(media) / "parties", Path(media) / "chill"],
                         self.server._additional_music_folders())

    def test_a_path_with_a_colon_in_it_survives(self):
        """The reason this is not packed into a shell string: `/media/best
        of 80s:90s` is a folder somebody has."""
        media = str(self.server.MEDIA_DIR)
        self._options({"additional_music_folders": [f"{media}/80s:90s"]})
        self.assertEqual([Path(media) / "80s:90s"],
                         self.server._additional_music_folders())

    def test_junk_entries_are_dropped_not_raised(self):
        media = str(self.server.MEDIA_DIR)
        self._options({"additional_music_folders": [
            f"{media}/keep", 7, None, "../escape", "", {"no": 1}]})
        self.assertEqual([Path(media) / "keep"],
                         self.server._additional_music_folders())

    def test_no_options_file_means_no_extra_folders(self):
        """A dev checkout, or a Supervisor that has not written it yet. The
        music folder on its own is a working add-on."""
        Path(self.options).unlink(missing_ok=True)
        self.assertEqual([], self.server._additional_music_folders())

    def test_unreadable_json_is_not_an_exception(self):
        Path(self.options).write_text("{not json")
        self.addCleanup(lambda: Path(self.options).unlink(missing_ok=True))
        self.assertEqual([], self.server._additional_music_folders())

    def test_the_music_folder_leads_and_duplicates_collapse(self):
        media = str(self.server.MEDIA_DIR)
        self._options({"additional_music_folders": [
            f"{media}/music", f"{media}/parties", f"{media}/parties"]})
        self.assertEqual(
            [Path(media) / "music", Path(media) / "parties"],
            self.server._music_folders())


class TestTheLibraryRoutes(unittest.TestCase):
    """What the Library tab asks for, over the real routes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.options = os.path.join(cls.tmp.name, "options.json")
        cls.server = _load_server(cls.tmp.name, cls.media.name, cls.options,
                                  os.path.join(cls.media.name, "music"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def setUp(self):
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        self.addCleanup(setattr, library, "SHOWS_DIR", self._shows)

    def _options(self, folders):
        Path(self.options).write_text(
            json.dumps({"additional_music_folders": folders}))
        self.addCleanup(lambda: Path(self.options).unlink(missing_ok=True))

    def _call(self, method, path, payload=None):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request(method, path, json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def test_the_library_lists_every_folder_and_every_track(self):
        media = Path(self.media.name)
        _track(media / "music" / "main.mp3", b"m")
        _track(media / "parties" / "loud.mp3", b"p")
        self._options([str(media / "parties")])

        status, body = self._call("GET", "/api/library")
        self.assertEqual(200, status)
        self.assertEqual({"main", "loud"}, {t["name"] for t in body["tracks"]})
        self.assertEqual([str(media / "music"), str(media / "parties")],
                         [f["path"] for f in body["folders"]])
        self.assertTrue(all(f["exists"] for f in body["folders"]))

    def test_a_missing_folder_is_reported_rather_than_hidden(self):
        media = Path(self.media.name)
        _track(media / "music" / "main.mp3", b"m")
        self._options([str(media / "gone")])

        status, body = self._call("GET", "/api/library")
        self.assertEqual(200, status)
        self.assertEqual([True, False], [f["exists"] for f in body["folders"]])

    def test_analyze_refuses_only_when_no_folder_exists(self):
        media = Path(self.media.name)
        self._options([str(media / "also-gone")])
        for stray in (media / "music", media / "also-gone"):
            if stray.is_dir():
                for child in stray.iterdir():
                    child.unlink()
                stray.rmdir()

        status, body = self._call("POST", "/api/library/analyze")
        self.assertEqual(404, status)
        self.assertIn(str(media / "music"), body["error"])
        self.assertIn(str(media / "also-gone"), body["error"])


class TestPartyUsesEveryFolder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.options = os.path.join(cls.tmp.name, "options.json")
        cls.server = _load_server(cls.tmp.name, cls.media.name, cls.options,
                                  os.path.join(cls.media.name, "music"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def setUp(self):
        self._shows = library.SHOWS_DIR
        library.SHOWS_DIR = Path(self.tmp.name) / "shows"
        self.addCleanup(setattr, library, "SHOWS_DIR", self._shows)

    def _call(self, payload):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request(
                    "POST", "/api/show/party_mode", json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def test_an_empty_party_names_every_folder_it_looked_in(self):
        media = Path(self.media.name)
        Path(self.options).write_text(json.dumps(
            {"additional_music_folders": [str(media / "parties")]}))
        self.addCleanup(lambda: Path(self.options).unlink(missing_ok=True))

        status, body = self._call({"media_player": "media_player.kitchen"})
        self.assertEqual(409, status, body)
        self.assertIn(str(media / "music"), body["error"])
        self.assertIn(str(media / "parties"), body["error"])

    def test_a_named_folder_still_wins_and_is_still_confined(self):
        status, body = self._call({"media_player": "media_player.kitchen",
                                   "folder": "../escape"})
        self.assertEqual(400, status)
        self.assertIn("/media", body["error"])


class TestTheOptionIsDeclared(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "config.yaml")) as handle:
            cls.config = yaml.safe_load(handle)

    def test_the_option_exists_with_an_empty_default(self):
        self.assertEqual([], self.config["options"]["additional_music_folders"])

    def test_the_schema_is_a_list_confined_to_media(self):
        schema = self.config["schema"]["additional_music_folders"]
        self.assertIsInstance(schema, list, "a single string is not a list")
        self.assertEqual(1, len(schema))
        self.assertIn("^/media", schema[0])

    def test_it_is_confined_the_same_way_the_music_folder_is(self):
        """Two folders, one rule — a second, looser one would let a folder
        in that no media player can be given."""
        self.assertEqual(self.config["schema"]["music_folder"],
                         self.config["schema"]["additional_music_folders"][0])


if __name__ == "__main__":
    unittest.main()
