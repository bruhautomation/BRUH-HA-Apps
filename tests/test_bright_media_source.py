#!/usr/bin/env python3
"""Which of Core's media sources is the /media this add-on can see.

The bug this covers is a silent one and it takes out everything: BRight
built `media-source://media_source/local/…` from a path, `local` being the
id Home Assistant gives its local media source *by default*. An install
that sets `media_dirs` in configuration.yaml renames it, and then every id
BRight builds — the calibration click track and every song — comes back
`Unknown source directory`. Nothing plays, and the add-on has no way to
tell that from a speaker that is merely quiet.

Core does not publish the filesystem path behind a media source, so
"which of these is my /media" cannot be read, only tried. These run
against the same real aiohttp server speaking Core's handshake that the
playback-check suite uses, because a hand-rolled fake of a protocol proves
only that the fake matches the code that mocked it.
"""

import ast
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import media_source  # noqa: E402

from test_bright_playback_check import (  # noqa: E402
    FakeHomeAssistant, run_against)

PROBE = media_source.PROBE_RELATIVE


def resolver(*working_ids: str):
    """A Core that resolves the probe under exactly these source ids."""
    good = {media_source.build(source_id, PROBE) for source_id in working_ids}

    def answer(message):
        if message.get("media_content_id") in good:
            return {"url": "/media/local/x.wav", "mime_type": "audio/wav"}
        return None  # → the fake sends an error result, as Core does
    return answer


def tree(*source_ids: str):
    return {"children": [
        {"media_content_id": f"{media_source.PREFIX}/{source_id}",
         "title": source_id, "can_expand": True}
        for source_id in source_ids]}


class MediaSourceTest(unittest.TestCase):
    def setUp(self):
        media_source.forget()
        media_source._candidates = []
        media_source._last_error = ""

    tearDown = setUp


class TestTheDefaultIsStillTheDefault(MediaSourceTest):
    """`local` is right on the large majority of installs, and being right
    first time has to stay cheap — one resolve, no browse."""

    def test_the_default_is_found_and_costs_one_call(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": resolver("local")})
        state = run_against(fake, lambda: media_source.discover(PROBE))
        self.assertEqual("local", state["source_id"])
        self.assertTrue(state["discovered"])
        self.assertEqual(1, len(fake.seen))
        self.assertEqual("media_source/resolve_media", fake.seen[0]["type"])

    def test_the_answer_is_remembered(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": resolver("local")})
        run_against(fake, lambda: media_source.discover(PROBE))
        # A second discovery asks Core nothing: the id changes only when
        # somebody edits configuration.yaml and restarts Core.
        again = FakeHomeAssistant({})
        state = run_against(again, lambda: media_source.discover(PROBE))
        self.assertEqual("local", state["source_id"])
        self.assertEqual([], again.seen)


class TestARenamedSourceIsFound(MediaSourceTest):
    """The `media_dirs` install: the whole reason this module exists."""

    def test_a_renamed_source_is_discovered_by_trying_it(self):
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("mymedia"),
            "media_source/browse_media": tree("mymedia", "recordings"),
        })
        state = run_against(fake, lambda: media_source.discover(PROBE))
        self.assertEqual("mymedia", state["source_id"])
        self.assertTrue(state["discovered"])
        self.assertIn("mymedia", state["candidates"])

    def test_ids_are_then_built_with_it(self):
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("mymedia"),
            "media_source/browse_media": tree("mymedia"),
        })
        run_against(fake, lambda: media_source.discover(PROBE))
        self.assertEqual(f"{media_source.PREFIX}/mymedia/bright/calibration.wav",
                         media_source.build(media_source.current_id(),
                                            "bright/calibration.wav"))

    def test_the_default_is_not_tried_twice(self):
        """It is tried first, and the browse loop must skip it — trying a
        known-bad id again is a wasted round trip on every failed play."""
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("second"),
            "media_source/browse_media": tree("local", "second"),
        })
        run_against(fake, lambda: media_source.discover(PROBE))
        resolves = [m for m in fake.seen
                    if m["type"] == "media_source/resolve_media"]
        asked = [m["media_content_id"] for m in resolves]
        self.assertEqual(len(asked), len(set(asked)), f"asked twice: {asked}")


class TestNothingResolves(MediaSourceTest):
    """/media is not any of Core's media directories. That is a real
    finding, and the answer has to name what Core does have — the person
    has to recognise their own configuration.yaml in it."""

    def test_the_error_names_the_directories_core_has(self):
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver(),  # nothing works
            "media_source/browse_media": tree("music", "films"),
        })
        state = run_against(fake, lambda: media_source.discover(PROBE))
        self.assertFalse(state["discovered"])
        self.assertIn("music", state["error"])
        self.assertIn("films", state["error"])
        self.assertIn("media_dirs", state["error"])

    def test_no_media_directories_at_all_says_so(self):
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver(),
            "media_source/browse_media": {"children": []},
        })
        state = run_against(fake, lambda: media_source.discover(PROBE))
        self.assertFalse(state["discovered"])
        self.assertIn("no media directories", state["error"])

    def test_a_failure_still_answers_with_the_default(self):
        """current_id() never returns None: the callers build ids while a
        show is being dispatched and cannot handle an absent answer. The
        default is what shipped, so falling back to it is never worse."""
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver(),
            "media_source/browse_media": tree("music"),
        })
        run_against(fake, lambda: media_source.discover(PROBE))
        self.assertEqual(media_source.DEFAULT_ID, media_source.current_id())

    def test_an_unreachable_core_is_reported_not_raised(self):
        """Discovery runs on the way to playing something. A diagnosis that
        dies of its own exception is worse than one that reports it could
        not look."""
        state = media_source.state()
        self.assertEqual(media_source.DEFAULT_ID, state["source_id"])
        self.assertFalse(state["discovered"])


class TestForgetting(MediaSourceTest):
    """A cached wrong answer must never be something you restart the add-on
    to clear — editing `media_dirs` should cost one failed play."""

    def test_forget_makes_the_next_discovery_ask_again(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": resolver("local")})
        run_against(fake, lambda: media_source.discover(PROBE))
        media_source.forget()
        second = FakeHomeAssistant({
            "media_source/resolve_media": resolver("mymedia"),
            "media_source/browse_media": tree("mymedia"),
        })
        state = run_against(second, lambda: media_source.discover(PROBE))
        self.assertEqual("mymedia", state["source_id"])

    def test_force_re_asks_even_when_cached(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": resolver("local")})
        run_against(fake, lambda: media_source.discover(PROBE))
        second = FakeHomeAssistant({
            "media_source/resolve_media": resolver("moved"),
            "media_source/browse_media": tree("moved"),
        })
        state = run_against(second,
                            lambda: media_source.discover(PROBE, force=True))
        self.assertEqual("moved", state["source_id"])


class TestPathsUnderMedia(MediaSourceTest):
    def test_a_file_under_media_becomes_a_relative_id(self):
        root = media_source.MEDIA_ROOT
        self.assertEqual("music/a.mp3",
                         media_source.relative_to_media(root / "music/a.mp3"))

    def test_a_file_outside_media_is_not_servable(self):
        """A folder outside Core's media root analyses perfectly and can
        never be served — None is the honest answer, not a built id."""
        self.assertIsNone(media_source.relative_to_media("/share/music/a.mp3"))
        self.assertIsNone(media_source.content_id(Path("/share/music/a.mp3")))


class TestEveryBuilderGoesThroughIt(unittest.TestCase):
    """Two places build media ids — the click track and every song. A fix
    that reached one of them would leave the other silently broken, and
    they fail identically from outside."""

    def test_no_media_id_is_spelled_out_by_hand(self):
        """Parsed rather than grepped: every one of these files has prose
        ABOUT the hardcoded id, and a grep cannot tell the bug from the
        comment explaining it. Docstrings are collected and skipped; what
        is left is string literals the code actually evaluates."""
        panel = Path(BASE_DIR) / "bright" / "panel"
        offenders = []
        for path in sorted(panel.rglob("*.py")):
            if path.name == "media_source.py":
                continue  # the one place the prefix is allowed to be written
            tree_ = ast.parse(path.read_text())
            docs = set()
            for node in ast.walk(tree_):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc is not None:
                        docs.add(doc)
            for node in ast.walk(tree_):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and "media-source://" in node.value
                        and node.value not in docs):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], offenders,
                         "a media id built by hand cannot learn the source "
                         "id, which is the whole failure")


if __name__ == "__main__":
    unittest.main()


class TestResolvingIsNotServing(MediaSourceTest):
    """The failure that reached a real house, and the reason for the fetch.

    `resolve_media` answers for any source that EXISTS, whether or not the
    path under it does — it builds and signs a URL rather than looking on
    disk. On an install whose only media source was `media: /config/media`,
    Core resolved `media-source://media_source/media/bright/calibration.wav`
    happily while the click track sat under `/media` and nothing of the
    sort existed at `/config/media/bright/`. BRight read the successful
    resolve as "found it", built every media id that way, and Core answered
    the eventual play with an HTTP 500 about a file that was never there.

    The URL is fetched now, and these run that fetch against a REAL HTTP
    server rather than stubbing it: what a served and an unserved path do
    differently IS the thing under test, and a stub of that is a stub of
    the answer.
    """

    def _serve(self, status_by_path):
        """A stand-in for Core's HTTP, on a thread. Returns its base URL."""
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's spelling
                path = self.path.split("?", 1)[0]
                self.send_response(status_by_path.get(path, 404))
                self.send_header("Content-Length", "1")
                self.end_headers()
                self.wfile.write(b"x")

            def log_message(self, *args):
                pass  # a test server narrating itself is noise

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    def _discover_against(self, fake, base_url):
        original = media_source.CORE_HTTP
        media_source.CORE_HTTP = base_url
        try:
            return run_against(fake, lambda: media_source.discover(PROBE))
        finally:
            media_source.CORE_HTTP = original

    def test_a_source_that_resolves_but_404s_is_not_chosen(self):
        """The exact shape of the real failure: one source, it resolves,
        and the file is not under it."""
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("media"),
            "media_source/browse_media": lambda m: tree("media"),
        })
        state = self._discover_against(
            fake, self._serve({"/media/local/x.wav": 404}))
        self.assertFalse(state["discovered"],
                         "a signed URL for a file that is not there is not "
                         "a discovery")

    def test_a_source_that_serves_is_chosen(self):
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("media"),
            "media_source/browse_media": lambda m: tree("media"),
        })
        state = self._discover_against(
            fake, self._serve({"/media/local/x.wav": 200}))
        self.assertTrue(state["discovered"])
        self.assertEqual("media", state["source_id"])

    def test_a_fetch_that_cannot_run_does_not_veto(self):
        """A probe that cannot run is not evidence of absence.

        On an install where this fetch route does not work, refusing every
        candidate would turn a working discovery into a total failure —
        strictly worse than the behaviour being fixed. So an unreachable
        prober falls back to the resolve alone.
        """
        fake = FakeHomeAssistant({
            "media_source/resolve_media": resolver("media"),
            "media_source/browse_media": lambda m: tree("media"),
        })
        # Port 9 is discard; nothing answers, so the fetch fails at the
        # transport rather than with a status.
        state = self._discover_against(fake, "http://127.0.0.1:9")
        self.assertTrue(state["discovered"],
                        "the resolve still counts when nothing can check it")
        self.assertEqual("media", state["source_id"])
