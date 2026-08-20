#!/usr/bin/env python3
"""BRight's panel, driven over HTTP: the show file, the effect preview,
saved parties, and the bulb picker.

These run the real aiohttp app against a scratch /data, so the answers
they check are the answers a browser gets — including the refusals, which
are half of what this panel is for. Nothing here reaches a bulb or a Home
Assistant: the device registry is a seeded file and no test presses
anything that would send a packet.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "bright" / "panel"

SERIALS = ["d073d5000001", "d073d5000002", "d073d5000003", "d073d5000004"]
TRACK_HASH = "ab" * 20
BPM = 120.0
BEATS = [round(60.0 / BPM * i, 3) for i in range(1, 200)]


def _seed(state: Path) -> None:
    (state / "shows" / TRACK_HASH).mkdir(parents=True, exist_ok=True)
    (state / "cache").mkdir(parents=True, exist_ok=True)
    (state / "lifx-devices.json").write_text(json.dumps({
        "devices": [
            {"serial": serial, "ip": f"192.168.1.{10 + i}",
             "label": f"Lamp {i}", "port": 56700,
             "rtt": {"p50_ms": 6.0, "p95_ms": 9.0, "loss": 0.0}}
            for i, serial in enumerate(SERIALS)
        ],
    }))
    # Three of the four bulbs are mapped: the fourth is what the picker
    # has to offer, and "already mapped" is the case it has to not offer.
    (state / "light-map.json").write_text(json.dumps({
        "version": 1,
        "fixtures": [
            {"id": f"lifx-{serial}", "kind": "lifx", "serial": serial,
             "label": f"Lamp {i}", "role": "lamp", "zone": "lounge",
             "x": 0.2 * (i + 1), "y": 0.5}
            for i, serial in enumerate(SERIALS[:3])
        ],
    }))
    duration = BEATS[-1] + 4
    (state / "shows" / TRACK_HASH / "analysis.json").write_text(json.dumps({
        "version": 1, "hash": TRACK_HASH, "bpm": BPM, "beats": BEATS,
        "downbeats": BEATS[::4], "onsets": BEATS, "brightness": 0.6,
        "file": "/media/music/demo.mp3",
        "tags": {"title": "Demo Track", "duration": duration},
        "sections": [
            {"start": 0.0, "end": 30.0, "kind": "intro", "energy": 0.2},
            {"start": 30.0, "end": duration, "kind": "peak", "energy": 0.9},
        ],
        "drops": [{"t": 30.0, "strength": 0.9}],
        "lyrics": {"synced": False, "lines": []},
    }))


# The module names the two panels share. Taken out of sys.modules around
# this file's imports so neither panel answers for the other.
_SHARED_NAMES = ("server", "stores", "director", "analyzer", "lifx",
                 "playback", "atomic_write", "jobs", "ha_client",
                 "panel_port", "playback_check", "calibrate", "undo_store")


def _drop_panel_modules() -> dict:
    """Remove the shared module names and hand back what was there."""
    removed = {}
    for name in list(sys.modules):
        if name.split(".")[0] in _SHARED_NAMES:
            removed[name] = sys.modules.pop(name)
    return removed


class PanelCase(unittest.IsolatedAsyncioTestCase):
    """One scratch /data per test class, and the real app on top of it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.shared = cls.state / "shared"
        _seed(cls.state)
        os.environ.update({
            "BRIGHT_STATE": str(cls.state),
            "BRIGHT_SHARED": str(cls.shared),
            "BRIGHT_MEDIA": str(cls.state / "media"),
        })
        (cls.state / "media" / "music").mkdir(parents=True, exist_ok=True)

        # BRight's panel and brAIn's panel both own a module called
        # `server`, and several called `stores`. Whichever directory is
        # first on sys.path wins, and by the time the whole suite runs
        # brAIn's is usually already on it — which is how this file passed
        # alone and failed in the suite, importing brAIn's panel and
        # asking it for BRight's routes.
        #
        # So: put this panel's directory at the FRONT for the life of the
        # class, drop every module either panel could have bound to those
        # names, import, and put both back afterwards. The environment has
        # to be set before the import either way, because every store
        # resolves its path at import time.
        cls._path = list(sys.path)
        cls._modules = _drop_panel_modules()
        sys.path.insert(0, str(PANEL_DIR))
        import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        _drop_panel_modules()
        sys.modules.update(cls._modules)
        sys.path[:] = cls._path
        cls.tmp.cleanup()

    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def get(self, path):
        response = await self.client.get(path)
        return response.status, await response.json()

    async def post(self, path, payload=None):
        response = await self.client.post(path, json=payload or {})
        return response.status, await response.json()

    async def put(self, path, payload):
        response = await self.client.put(path, json=payload)
        return response.status, await response.json()

    async def delete(self, path):
        response = await self.client.delete(path)
        return response.status, await response.json()


class TestTheBulbPicker(PanelCase):
    async def test_it_offers_only_the_bulbs_not_on_the_map(self):
        status, body = await self.get("/api/map/candidates")
        self.assertEqual(200, status)
        self.assertEqual([SERIALS[3]], [c["serial"] for c in body["candidates"]])
        self.assertEqual(4, body["discovered"])

    async def test_adding_one_puts_it_where_the_picker_said(self):
        status, body = await self.post("/api/map/add-lifx", {
            "serial": SERIALS[3], "role": "strip", "zone": "hall",
            "x": 0.8, "y": 0.2})
        self.assertEqual(200, status)
        self.assertEqual("strip", body["fixture"]["role"])
        self.assertEqual("hall", body["fixture"]["zone"])
        _, candidates = await self.get("/api/map/candidates")
        self.assertEqual([], candidates["candidates"])
        # Put the map back for whatever runs next.
        await self.delete(f"/api/map/fixture/lifx-{SERIALS[3]}")

    async def test_an_undiscovered_bulb_is_refused_with_the_reason(self):
        status, body = await self.post("/api/map/add-lifx",
                                       {"serial": "d073d5ffffff"})
        self.assertEqual(404, status)
        self.assertIn("discover", body["error"].lower())


class TestTheEffectPreview(PanelCase):
    async def test_the_catalog_carries_the_room_and_the_vocabulary(self):
        status, body = await self.get("/api/effects/catalog")
        self.assertEqual(200, status)
        self.assertGreaterEqual(len(body["catalog"]), 12)
        self.assertEqual(3, len(body["fixtures"]))
        self.assertIn("x", body["orders"])
        self.assertTrue(body["palettes"])

    async def test_a_preview_answers_frames_and_a_price(self):
        status, body = await self.post("/api/effects/preview", {
            "effects": [{"type": "chase", "name": "test",
                         "params": {"step_beats": 1}}],
            "bpm": 120, "duration_s": 8})
        self.assertEqual(200, status)
        self.assertEqual(3, len(body["preview"]["fixtures"]))
        self.assertGreater(len(body["preview"]["frames"]), 30)
        self.assertGreater(body["cues"], 0)
        self.assertFalse(body["over_budget"])
        self.assertEqual(body["budget_hz"], 18.0)

    async def test_a_bad_effect_is_a_sentence_not_a_traceback(self):
        status, body = await self.post("/api/effects/preview",
                                       {"effects": [{"type": "hyperdrive"}]})
        self.assertEqual(400, status)
        self.assertIn("hyperdrive", body["error"])

    async def test_nothing_to_preview_is_refused(self):
        status, body = await self.post("/api/effects/preview", {})
        self.assertEqual(400, status)
        self.assertIn("preview", body["error"])

    async def test_presets_round_trip(self):
        status, body = await self.post("/api/effects/presets", {
            "name": "kitchen chase",
            "effect": {"type": "chase", "select": {"ids": ["lifx-" + SERIALS[0]]}}})
        self.assertEqual(200, status)
        self.assertEqual(1, len(body["presets"]))
        status, body = await self.delete("/api/effects/presets/kitchen%20chase")
        self.assertEqual(200, status)
        self.assertEqual([], body["presets"])

    async def test_a_preset_with_no_name_says_so(self):
        status, body = await self.post("/api/effects/presets",
                                       {"effect": {"type": "wash"}})
        self.assertEqual(400, status)
        self.assertIn("name", body["error"])


class TestTheShowFile(PanelCase):
    async def _compile(self):
        return await self.post("/api/show/compile", {"track_hash": TRACK_HASH})

    async def test_the_script_is_readable_and_names_its_file(self):
        await self._compile()
        status, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        self.assertEqual(200, status)
        self.assertTrue(body["compiled"])
        self.assertTrue(body["script"]["scenes"])
        self.assertTrue(body["effects"])
        self.assertIn("demo-track", body["file"])

    async def test_an_edit_compiles_through_the_same_door(self):
        await self._compile()
        _, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        script = body["script"]
        script["scenes"][0]["effects"].append({
            "type": "sparkle", "name": "extra sparkle",
            "params": {"every_beats": 2}})
        status, saved = await self.put(f"/api/show/{TRACK_HASH}/script",
                                       {"script": script})
        self.assertEqual(200, status)
        self.assertIn("extra sparkle",
                      [e["name"] for e in saved["effects"]])

    async def test_an_edit_that_would_flood_a_bulb_is_refused(self):
        await self._compile()
        _, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        script = body["script"]
        script["scenes"][0]["effects"] = [
            {"type": "chase", "name": f"flood {i}",
             "params": {"step_beats": 0.125}} for i in range(4)]
        status, refused = await self.put(f"/api/show/{TRACK_HASH}/script",
                                         {"script": script})
        self.assertEqual(422, status)
        self.assertIn("msgs/s", refused["error"])

    async def test_nonsense_json_is_refused_before_anything_is_kept(self):
        status, body = await self.put(f"/api/show/{TRACK_HASH}/script",
                                      {"script": "not a script"})
        self.assertEqual(400, status)
        _, after = await self.get(f"/api/show/{TRACK_HASH}/script")
        self.assertTrue(after["script"], "a refused edit took the show with it")

    async def test_the_file_on_the_shared_volume_can_be_read_back(self):
        await self._compile()
        mirror = next((self.shared / "shows").glob("*.json"))
        edited = json.loads(mirror.read_text())
        edited["scenes"][0]["brightness"] = 0.42
        mirror.write_text(json.dumps(edited))
        status, body = await self.post(
            f"/api/show/{TRACK_HASH}/script/import")
        self.assertEqual(200, status)
        self.assertEqual(0.42, body["script"]["scenes"][0]["brightness"])

    async def test_a_hand_edited_file_that_is_broken_says_where(self):
        await self._compile()
        mirror = next((self.shared / "shows").glob("*.json"))
        mirror.write_text('{"scenes": [ oops }')
        status, body = await self.post(f"/api/show/{TRACK_HASH}/script/import")
        self.assertEqual(400, status)
        self.assertIn("line", body["error"])
        # Leave a good file behind for anything that runs after this.
        await self._compile()

    async def test_the_cue_list_is_readable_without_the_packets(self):
        await self._compile()
        status, body = await self.get(f"/api/show/{TRACK_HASH}/cues?limit=5")
        self.assertEqual(200, status)
        self.assertEqual(5, len(body["cues"]))
        self.assertGreater(body["total"], 5)
        for cue in body["cues"]:
            self.assertNotIn("payload_b64", cue)
            self.assertTrue(cue["desc"])

    async def test_a_cue_names_the_effect_that_asked_for_it(self):
        await self._compile()
        _, body = await self.get(f"/api/show/{TRACK_HASH}/cues?limit=500")
        self.assertTrue(any("·" in cue["desc"] for cue in body["cues"]),
                        "no cue traces back to an effect")


class TestSavedParties(PanelCase):
    async def test_a_party_round_trips(self):
        status, body = await self.post("/api/parties", {
            "name": "Saturday Night", "vibe": "rave",
            "media_player": "media_player.lounge",
            "end_scene": "scene.good_night",
            "fixtures": [f"lifx-{SERIALS[0]}"]})
        self.assertEqual(200, status)
        self.assertEqual("scene.good_night", body["party"]["end_scene"])
        status, listing = await self.get("/api/parties")
        self.assertEqual(["Saturday Night"],
                         [p["name"] for p in listing["parties"]])

    async def test_the_names_are_mirrored_where_core_can_read_them(self):
        await self.post("/api/parties", {"name": "Mirror Test"})
        mirrored = json.loads((self.shared / "parties.json").read_text())
        self.assertIn("Mirror Test", mirrored["parties"])

    async def test_starting_an_unknown_party_lists_the_real_ones(self):
        await self.post("/api/parties", {"name": "Saturday Night"})
        status, body = await self.post("/api/show/start_party",
                                       {"party": "Wednesday"})
        self.assertEqual(404, status)
        self.assertIn("Saturday Night", body["error"])

    async def test_a_party_with_no_speaker_anywhere_says_which_step_is_missing(self):
        await self.post("/api/parties", {"name": "No Speaker"})
        status, body = await self.post("/api/show/start_party",
                                       {"party": "No Speaker"})
        self.assertEqual(400, status)
        self.assertIn("calibrate", body["error"].lower())

    async def test_deleting_one_leaves_the_others(self):
        await self.post("/api/parties", {"name": "Keep"})
        await self.post("/api/parties", {"name": "Drop"})
        status, body = await self.delete("/api/parties/Drop")
        self.assertEqual(200, status)
        self.assertNotIn("Drop", [p["name"] for p in body["parties"]])
        self.assertIn("Keep", [p["name"] for p in body["parties"]])

    async def test_a_scene_that_is_not_a_scene_is_refused(self):
        status, body = await self.post("/api/parties",
                                       {"name": "Bad", "end_scene": "light.x"})
        self.assertEqual(400, status)
        self.assertIn("scene", body["error"])


class TestStopping(PanelCase):
    async def test_stop_takes_a_scene(self):
        status, body = await self.post("/api/show/stop_show",
                                       {"scene": "scene.good_night"})
        self.assertEqual(200, status)
        self.assertEqual("scene.good_night", body["scene"])

    async def test_stop_refuses_something_that_is_not_a_scene(self):
        status, body = await self.post("/api/show/stop_show",
                                       {"scene": "light.lounge"})
        self.assertEqual(400, status)

    async def test_an_idle_panel_says_it_is_idle_and_not_active(self):
        await self.post("/api/show/stop_show")
        status, body = await self.get("/api/show/state")
        self.assertEqual(200, status)
        self.assertEqual("idle", body["status"])
        self.assertFalse(body["active"],
                         "an idle panel would show a Stop button")


if __name__ == "__main__":
    unittest.main()
