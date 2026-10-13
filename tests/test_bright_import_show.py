#!/usr/bin/env python3
"""`bright.import_show` and `bright.get_status` with `parties_only`, end to
end: the integration's own handler, the add-on's real bridge, the real
panel app — with the file IPC between the first two replaced by a direct
call, which is the one part that is not BRight's code.

Also the guide published beside the mirrored shows, which is what tells
whoever opens that folder that an edit there does nothing until it is
imported.
"""

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from test_addon_service_responses import registered  # noqa: E402
from test_bright_panel_routes import PanelCase, TRACK_HASH  # noqa: E402
from test_bright_party import _load_bridge  # noqa: E402


class _IntegrationCase(PanelCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bridge = _load_bridge()
        server = self.client.server
        self.bridge.PANEL_URL = f"http://{server.host}:{server.port}"
        self.handlers = {name: handler
                         for name, (_, handler) in registered("bright").items()}
        bridge = self.bridge
        self.sent = []

        async def send_request(kind, payload, timeout=15.0):
            # What the request file and the response file carry, without
            # the files: the bridge's own dispatcher answers it.
            self.sent.append((kind, timeout))
            return await bridge.handle({"kind": kind, "payload": payload})

        for handler in self.handlers.values():
            handler.__globals__["send_request"] = send_request
        self.HomeAssistantError = self.handlers["import_show"].__globals__[
            "HomeAssistantError"]

    async def call(self, service, **data):
        return await self.handlers[service](types.SimpleNamespace(data=data))

    def mirror(self):
        return next((self.shared / "shows").glob("*.json"))


class TestImportShow(_IntegrationCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_job("/api/show/compile", {"track_hash": TRACK_HASH})

    async def test_an_edited_file_becomes_the_show(self):
        mirror = self.mirror()
        edited = json.loads(mirror.read_text())
        edited["scenes"][0]["brightness"] = 0.37
        mirror.write_text(json.dumps(edited))

        answer = await self.call("import_show", track=mirror.name)

        self.assertTrue(answer["imported"])
        self.assertEqual(TRACK_HASH, answer["track_hash"])
        self.assertEqual(mirror.name, answer["file"])
        self.assertGreater(answer["cues"], 0)
        self.assertNotIn("ok", answer, "the transport's flag is not an answer")
        self.assertEqual("import_show", self.sent[-1][0])
        self.assertGreater(self.sent[-1][1], 15.0,
                           "an import is waited for longer than a stop")
        _, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        self.assertEqual(0.37, body["script"]["scenes"][0]["brightness"])

    async def test_the_hash_and_the_short_hash_name_the_same_track(self):
        for track in (TRACK_HASH, TRACK_HASH[:8], f"/config/.bright/shows/"
                      f"{self.mirror().name}"):
            with self.subTest(track=track):
                answer = await self.call("import_show", track=track)
                self.assertEqual(TRACK_HASH, answer["track_hash"])

    async def test_broken_json_is_refused_with_its_line(self):
        self.mirror().write_text('{"version": 2,\n "scenes": [ oops ]}')
        with self.assertRaises(self.HomeAssistantError) as caught:
            await self.call("import_show", track=self.mirror().name)
        self.assertIn("line 2", str(caught.exception))
        self.assertIn("not valid JSON", str(caught.exception))
        # Leave a good file behind for anything that runs after this.
        await self.run_job("/api/show/compile", {"track_hash": TRACK_HASH})

    async def test_a_script_that_will_not_run_is_refused_with_the_reason(self):
        mirror = self.mirror()
        edited = json.loads(mirror.read_text())
        edited["scenes"][0]["effects"] = [{"type": "disco_inferno"}]
        mirror.write_text(json.dumps(edited))
        with self.assertRaises(self.HomeAssistantError) as caught:
            await self.call("import_show", track=mirror.name)
        self.assertIn("disco_inferno", str(caught.exception))
        await self.run_job("/api/show/compile", {"track_hash": TRACK_HASH})

    async def test_a_name_that_is_no_show_is_said(self):
        with self.assertRaises(self.HomeAssistantError) as caught:
            await self.call("import_show", track="no-such-song-0f0f0f0f.json")
        self.assertIn("no track's show matches", str(caught.exception))
        with self.assertRaises(self.HomeAssistantError) as caught:
            await self.call("import_show", track="not a file")
        self.assertIn("not a show file name", str(caught.exception))

    async def test_a_saved_effect_in_an_edited_file_is_expanded(self):
        """The README says a saved effect can be named with `use`; the
        import validated before expanding, so naming one was refused as an
        unknown effect type."""
        await self.post("/api/effects/presets", {
            "name": "lamp chase",
            "effect": {"type": "chase", "select": {"roles": ["lamp"]},
                       "params": {"step_beats": 1}}})
        mirror = self.mirror()
        edited = json.loads(mirror.read_text())
        edited["scenes"][0]["effects"].append({"use": "lamp chase"})
        mirror.write_text(json.dumps(edited))
        answer = await self.call("import_show", track=mirror.name)
        self.assertTrue(answer["imported"])
        _, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        self.assertIn("chase", [e["type"] for e in
                                body["script"]["scenes"][0]["effects"]])

    async def test_the_guide_sits_beside_the_shows_and_is_left_alone(self):
        shows = self.shared / "shows"
        guide = shows / "README.md"
        catalog = shows / "EFFECTS.md"
        text = guide.read_text()
        self.assertIn("changes nothing until it is", " ".join(text.split()))
        self.assertIn("bright.import_show", text)
        self.assertIn("/script/import", text)
        self.assertIn("EFFECTS.md", text)
        self.assertIn("chase", catalog.read_text())
        self.assertIn("accent", catalog.read_text())
        stamp = guide.stat().st_mtime_ns
        os.utime(guide, ns=(stamp - 10**9, stamp - 10**9))
        await self.run_job("/api/show/compile", {"track_hash": TRACK_HASH})
        self.assertEqual(stamp - 10**9, guide.stat().st_mtime_ns,
                         "an unchanged guide was written again")
        self.assertEqual([self.mirror()], list(shows.glob("*.json")),
                         "the guide must not look like a show file")


class TestStatusForNamingASet(_IntegrationCase):
    async def test_parties_only_skips_the_library_and_describes_each_set(self):
        await self.post("/api/parties", {
            "name": "Friday", "media_player": "media_player.den",
            "tracks": [TRACK_HASH]})

        def no_scan(*_):
            raise AssertionError("the library was scanned")

        original = self.server.library.scan_all
        self.server.library.scan_all = no_scan
        try:
            answer = await self.call("get_status", parties_only=True)
        finally:
            self.server.library.scan_all = original
        self.assertNotIn("tracks", answer)
        self.assertIn("status", answer["state"])
        friday = next(p for p in answer["parties"] if p["name"] == "Friday")
        self.assertEqual("media_player.den", friday["media_player"])
        self.assertEqual(1, friday["songs"])

    async def test_the_default_answer_is_unchanged(self):
        answer = await self.call("get_status")
        self.assertIn("tracks", answer)
        self.assertIn("track_count", answer)
        self.assertTrue(all(isinstance(p, str) for p in answer["parties"]))


if __name__ == "__main__":
    unittest.main()
