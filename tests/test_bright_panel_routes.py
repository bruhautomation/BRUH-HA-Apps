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
        "envelope": [round(0.2 + 0.7 * (i % 40) / 40, 3) for i in range(900)],
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

    async def run_job(self, path, payload=None):
        """POST a route that answers with a job handle, and wait it out.

        Every route that asks Claude for something works this way: the
        run is longer than the request that asked for it is allowed to
        live, so it is started and polled. The status is normalised back
        to what the route used to answer inline, which keeps the tests
        about the ROUTE rather than about the transport.
        """
        import asyncio

        status, started = await self.post(path, payload)
        if "job" not in started:
            return status, started
        for _ in range(4000):
            _, job = await self.get("/api/job/" + started["job"])
            if job.get("status") == "running":
                await asyncio.sleep(0.005)
                continue
            if job.get("status") == "error":
                return 409, {"error": job.get("error") or "failed"}
            return 200, job.get("result") or {}
        raise AssertionError(f"{path} never finished")

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
        return await self.run_job("/api/show/compile",
                                  {"track_hash": TRACK_HASH})

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
            "name": "Saturday Night",
            "media_player": "media_player.lounge",
            "end_scene": "scene.good_night",
            "fixtures": [f"lifx-{SERIALS[0]}"]})
        self.assertEqual(200, status)
        self.assertEqual("scene.good_night", body["party"]["end_scene"])
        status, listing = await self.get("/api/parties")
        self.assertEqual(["Saturday Night"],
                         [p["name"] for p in listing["parties"]])

    async def test_a_set_carries_no_vibe(self):
        """It steered the DIRECTOR, which is a compile-time decision, and
        it only ever reached a track with no show yet — so on a library
        with shows already built it did nothing at all, and on a fresh
        one it silently rewrote what went to disk. It lives beside the
        compile button now."""
        status, body = await self.post("/api/parties", {
            "name": "No Vibe", "vibe": "rave"})
        self.assertEqual(200, status)
        self.assertNotIn("vibe", body["party"])

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


class TestTheShowEditorsPreview(PanelCase):
    """The routes the visual editor is built on, over real HTTP."""

    async def _compile(self):
        return await self.run_job("/api/show/compile",
                                  {"track_hash": TRACK_HASH})

    async def _script(self):
        _, body = await self.get(f"/api/show/{TRACK_HASH}/script")
        return body["script"]

    async def test_a_window_answers_frames_for_the_moment_asked_for(self):
        await self._compile()
        status, body = await self.post(
            f"/api/show/{TRACK_HASH}/preview", {"start_s": 20, "span_s": 3})
        self.assertEqual(200, status)
        self.assertAlmostEqual(body["start_s"], 20.0, places=1)
        self.assertTrue(body["frames"])
        self.assertEqual(len(body["frames"][0]), len(body["fixtures"]))

    async def test_the_outline_carries_the_strip_and_its_furniture(self):
        await self._compile()
        status, body = await self.post(
            f"/api/show/{TRACK_HASH}/outline", {"columns": 40})
        self.assertEqual(200, status)
        self.assertEqual(len(body["columns"]), 40)
        self.assertTrue(body["timeline"]["scenes"])
        self.assertTrue(body["timeline"]["downbeats"])

    async def test_an_unsaved_edit_is_what_gets_previewed(self):
        """The claim that makes the editor live.

        A script in the request body is previewed instead of the one on
        disk — otherwise every change would have to be saved to be seen,
        and 'live preview' would mean 'preview of the last save'.
        """
        await self._compile()
        script = await self._script()
        _, before = await self.post(
            f"/api/show/{TRACK_HASH}/preview", {"start_s": 5, "span_s": 1})

        script["scenes"][0]["palette"] = [[120, 1.0]]
        script["scenes"][0]["brightness"] = 1.0
        _, after = await self.post(
            f"/api/show/{TRACK_HASH}/preview",
            {"start_s": 5, "span_s": 1, "script": script})
        self.assertNotEqual(before["frames"][0], after["frames"][0])

    async def test_previewing_an_edit_does_not_save_it(self):
        await self._compile()
        script = await self._script()
        original = json.loads(json.dumps(script))
        script["scenes"][0]["palette"] = [[120, 1.0]]
        await self.post(f"/api/show/{TRACK_HASH}/preview",
                        {"start_s": 5, "span_s": 1, "script": script})
        self.assertEqual(original["scenes"][0]["palette"],
                         (await self._script())["scenes"][0]["palette"])

    async def test_an_impossible_edit_is_refused_while_you_are_typing(self):
        """The compiler's refusals reach the preview, not just the save.

        Finding out that an effect floods a bulb belongs beside the effect
        you just changed, not several presses later.
        """
        await self._compile()
        script = await self._script()
        script["scenes"][0].setdefault("effects", []).append({
            "type": "strobe", "name": "far too much",
            "params": {"hits": 64, "every_beats": 1}})
        status, body = await self.post(
            f"/api/show/{TRACK_HASH}/preview",
            {"start_s": 1, "span_s": 1, "script": script})
        if status == 400:
            self.assertTrue(body["error"])
        else:
            # Not every over-ask trips the budget; what must never happen
            # is a traceback or a silent empty preview.
            self.assertTrue(body["frames"])

    async def test_a_track_the_library_never_scanned_says_so(self):
        # Deliberately not TRACK_HASH: the scratch /data is per CLASS, so a
        # sibling test compiling a show would decide this one's answer.
        unknown = "0" * 40
        status, body = await self.post(
            f"/api/show/{unknown}/preview", {"start_s": 0})
        self.assertEqual(400, status)
        self.assertIn("analyzed", body["error"])

    async def test_a_script_that_is_not_json_is_a_sentence(self):
        await self._compile()
        status, body = await self.post(
            f"/api/show/{TRACK_HASH}/preview", {"script": "{oh dear"})
        self.assertEqual(400, status)
        self.assertIn("JSON", body["error"])


class TestWhoWroteThisShow(PanelCase):
    """A show tagged `algorithmic` used to say nothing about why.

    On a real install every Claude-written show fell back for days — the
    prompt demonstrated `//` annotations, the model wrote them back, and
    JSON has no comments — and the only trace was a WARNING nobody reads.
    From the outside a fallback and a success are identical: you get a
    show either way. So the record travels with the show, and the reason
    travels with a fallback.
    """

    async def test_a_plain_compile_records_who_wrote_it(self):
        status, body = await self.run_job(
            "/api/show/compile", {"track_hash": TRACK_HASH})
        self.assertEqual(200, status)
        report = body["director"]
        self.assertEqual("algorithmic", report["used"])
        self.assertFalse(report["fell_back"])

    async def test_the_record_can_be_read_back_later(self):
        """The editor opens shows it did not compile, so the compile
        response is not the only place this can be asked."""
        await self.client.post("/api/show/compile",
                               json={"track_hash": TRACK_HASH})
        response = await self.client.get(f"/api/show/{TRACK_HASH}/director")
        self.assertEqual(200, response.status)
        self.assertEqual("algorithmic", (await response.json())["used"])

    async def test_a_show_with_no_record_says_so_rather_than_failing(self):
        response = await self.client.get(f"/api/show/{'cd' * 20}/director")
        self.assertEqual(404, response.status)
        self.assertIn("no record", (await response.json())["error"])

    async def test_asking_for_claude_without_brain_is_refused_by_name(self):
        """Not silently downgraded. Pressing a button called Claude and
        getting the algorithmic director is the failure this whole record
        exists to make impossible."""
        response = await self.client.post(
            "/api/show/compile",
            json={"track_hash": TRACK_HASH, "director": "claude"})
        self.assertEqual(409, response.status)
        self.assertIn("brAIn", (await response.json())["error"])

    async def test_an_unknown_director_is_refused(self):
        response = await self.client.post(
            "/api/show/compile",
            json={"track_hash": TRACK_HASH, "director": "gpt"})
        self.assertEqual(400, response.status)

    async def test_algorithmic_can_be_asked_for_explicitly(self):
        """The override is per-compile in both directions — a show you
        want rebuilt without spending a Claude run is the same button."""
        status, body = await self.run_job(
            "/api/show/compile",
            {"track_hash": TRACK_HASH, "director": "algorithmic"})
        self.assertEqual(200, status)
        self.assertEqual("algorithmic", body["director"]["used"])
        self.assertFalse(body["director"]["fell_back"])


class TestTheBriefIsReadable(PanelCase):
    """"Show me exactly what Claude is doing" starts with what it is told."""

    async def test_the_brief_is_the_real_one(self):
        response = await self.client.get(f"/api/show/{TRACK_HASH}/prompt")
        self.assertEqual(200, response.status)
        body = await response.json()
        prompt = body["prompt"]
        # Built by the same function a real run uses, so these are not a
        # description of the brief — they are in it.
        self.assertIn("Demo Track", prompt)
        self.assertIn("THE ROOM", prompt)
        self.assertIn("lifx-d073d5000001", prompt,
                      "every light is nameable, or select.ids is unusable")
        self.assertIn("lounge", prompt, "the zones somebody set")
        self.assertIn('order:"x"', prompt,
                      "the travel orders are worked out in Python, because "
                      "sorting a dozen floats is what a model does badly "
                      "and confidently")
        self.assertEqual(3, body["fixtures"])
        self.assertEqual(len(prompt), body["chars"])

    async def test_reading_the_brief_runs_nothing(self):
        """It costs no Claude run, which is what makes it worth reading
        before deciding to spend one."""
        response = await self.client.get(f"/api/show/{TRACK_HASH}/prompt")
        self.assertFalse((await response.json())["available"],
                         "no brAIn in the test environment, and the brief "
                         "is still readable")

    async def test_a_vibe_appears_in_the_brief(self):
        response = await self.client.get(
            f"/api/show/{TRACK_HASH}/prompt?vibe=slow and blue")
        self.assertIn("slow and blue", (await response.json())["prompt"])

    async def test_an_unanalyzed_track_says_what_to_do(self):
        response = await self.client.get(f"/api/show/{'cd' * 20}/prompt")
        self.assertEqual(404, response.status)
        self.assertIn("Library", (await response.json())["error"])


class TestSeeingTheMusic(PanelCase):
    """Nothing in the panel showed the song at all.

    A show is a list of times, and the only way to know whether the drop
    landed on the drop was to play it in a dark room and watch. The
    waveform and the landmarks travel in ONE answer on purpose: two
    requests would let the picture and the marks disagree about which
    track they are of.
    """

    async def test_the_song_and_its_landmarks_arrive_together(self):
        response = await self.client.get(f"/api/track/{TRACK_HASH}/waveform")
        self.assertEqual(200, response.status)
        body = await response.json()
        self.assertEqual(900, len(body["envelope"]))
        self.assertEqual("Demo Track", body["title"])
        self.assertEqual(BPM, body["bpm"])
        self.assertTrue(body["sections"], "the sections the analyser found")
        self.assertTrue(body["drops"], "and the drops it marked")
        self.assertTrue(body["duration_s"])

    async def test_bar_lines_not_every_beat(self):
        """At 120bpm a four minute track is 480 beats; drawn on a 900px
        canvas that is a grey wash rather than a grid."""
        body = await (await self.client.get(
            f"/api/track/{TRACK_HASH}/waveform")).json()
        self.assertLess(len(body["downbeats"]), len(BEATS))

    async def test_an_unanalysed_track_says_what_to_do(self):
        response = await self.client.get(f"/api/track/{'cd' * 20}/waveform")
        self.assertEqual(404, response.status)
        self.assertIn("Library", (await response.json())["error"])

    async def test_a_bad_hash_is_refused_rather_than_globbed(self):
        response = await self.client.get("/api/track/not-a-hash/waveform")
        self.assertEqual(400, response.status)


class TestCalibrationHousekeeping(PanelCase):
    """The sound can be stopped, and a departed speaker can be forgotten."""

    async def test_stopping_the_click_track_needs_a_player(self):
        response = await self.client.post("/api/calibrate/stop", json={})
        self.assertEqual(400, response.status)

    async def test_a_profile_can_be_deleted(self):
        from stores import calibration as calibration_store
        calibration_store.add_run("media_player.departed", 320.0, method="mic")
        response = await self.client.delete(
            "/api/calibrate/profile/media_player.departed")
        self.assertEqual(200, response.status)
        body = await response.json()
        self.assertEqual("media_player.departed", body["deleted"])
        self.assertNotIn("media_player.departed",
                         [p["entity_id"] for p in body["profiles"]])

    async def test_deleting_a_profile_that_never_existed_is_a_404(self):
        response = await self.client.delete(
            "/api/calibrate/profile/media_player.never_here")
        self.assertEqual(404, response.status)

    async def test_a_junk_entity_is_refused_not_globbed(self):
        response = await self.client.delete(
            "/api/calibrate/profile/..%2F..%2Fetc")
        self.assertEqual(400, response.status)


class TestNudgeRoutes(PanelCase):
    async def test_a_nudge_with_nothing_running_is_refused(self):
        response = await self.client.post("/api/show/nudge", json={"ms": 25})
        self.assertEqual(409, response.status)
        self.assertIn("nothing is running", (await response.json())["error"])

    async def test_a_zero_nudge_is_refused(self):
        response = await self.client.post("/api/show/nudge", json={"ms": 0})
        self.assertEqual(400, response.status)

    async def test_keep_with_nothing_nudged_is_refused(self):
        response = await self.client.post("/api/show/nudge/keep", json={})
        self.assertEqual(409, response.status)


class TestPartyTransportRoutes(PanelCase):
    async def test_a_skip_with_nothing_running_is_refused(self):
        response = await self.client.post("/api/party/skip", json={"step": 1})
        self.assertEqual(409, response.status)
        self.assertIn("no party", (await response.json())["error"])

    async def test_a_junk_step_is_refused(self):
        response = await self.client.post("/api/party/skip",
                                          json={"step": "sideways"})
        self.assertEqual(400, response.status)


class TestRevisionRoute(PanelCase):
    async def test_empty_feedback_is_refused_before_anything_runs(self):
        response = await self.client.post(
            f"/api/show/{TRACK_HASH}/revise", json={"feedback": "  "})
        self.assertEqual(400, response.status)
        self.assertIn("changed", (await response.json())["error"])

    async def test_without_brain_the_refusal_names_the_dependency(self):
        response = await self.client.post(
            f"/api/show/{TRACK_HASH}/revise", json={"feedback": "more"})
        self.assertEqual(409, response.status)
        self.assertIn("brAIn", (await response.json())["error"])


class TestAutoSyncRoute(PanelCase):
    async def test_missing_fields_are_a_400(self):
        response = await self.client.post("/api/show/autosync", json={})
        self.assertEqual(400, response.status)

    async def test_with_nothing_running_it_is_refused(self):
        response = await self.client.post("/api/show/autosync", json={
            "record_start_epoch_ms": 1000.0,
            "wav_b64": "UklGRg==",
        })
        self.assertEqual(409, response.status)
        self.assertIn("nothing is playing",
                      (await response.json())["error"])


class TestMetronomePicksItsBulbs(PanelCase):
    """The Lab's sync proof runs on the bulbs you ticked, not the house."""

    async def test_unknown_serials_are_refused_by_name(self):
        response = await self.client.post("/api/show/metronome", json={
            "track_hash": TRACK_HASH,
            "media_player": "media_player.living",
            "serials": ["ffffffffffff"],
        })
        self.assertEqual(409, response.status)
        self.assertIn("none of the selected bulbs",
                      (await response.json())["error"])

    async def test_known_serials_pass_the_filter(self):
        # The next gate after the filter is calibration, which this
        # scratch install has none of — reaching THAT refusal is the
        # proof the selected bulb was accepted and cues were built.
        response = await self.client.post("/api/show/metronome", json={
            "track_hash": TRACK_HASH,
            "media_player": "media_player.living",
            "serials": [SERIALS[0]],
        })
        self.assertEqual(409, response.status)
        self.assertIn("calibrated", (await response.json())["error"])

    async def test_a_selection_does_not_reach_a_compiled_show(self):
        # /start_show ignores serials by design: a compiled show's cues
        # already exist, and parties filter at dispatch instead. The
        # request must not 409 about bulbs it was never going to filter.
        response = await self.client.post("/api/show/start_show", json={
            "track_hash": TRACK_HASH,
            "media_player": "media_player.living",
            "serials": ["ffffffffffff"],
        })
        body = await response.json()
        self.assertNotIn("none of the selected bulbs",
                         body.get("error", ""))


class TestASlowClaudeRunOutlivesItsRequest(PanelCase):
    """The bug this contract exists for.

    A Claude-tier compile takes minutes. It used to be awaited inside the
    request, so ingress cut the connection and the browser reported a
    network error — "load failed" — about a director that was still
    working and would go on to save a show nobody was told about. Every
    route that asks Claude for something answers with a job id now, and
    the run is polled.
    """

    async def test_compile_answers_a_job_rather_than_a_show(self):
        status, body = await self.post("/api/show/compile",
                                       {"track_hash": TRACK_HASH})
        self.assertEqual(202, status)
        self.assertIn("job", body)
        # And the job is what carries the show.
        _, result = await self.run_job("/api/show/compile",
                                       {"track_hash": TRACK_HASH})
        self.assertIn("stats", result)

    async def test_a_failing_run_reports_its_reason_through_the_job(self):
        """A refusal must still arrive. It used to be an HTTP status with
        a body; it is a finished job carrying the message now, and losing
        the reason on the way would be the same bug wearing a job."""
        status, body = await self.run_job("/api/show/compile",
                                          {"track_hash": "nope" * 10})
        self.assertEqual(409, status)
        self.assertTrue(body["error"])

    async def test_a_bad_request_is_still_refused_before_any_job_starts(self):
        """Argument checking does not become somebody's minute-long wait."""
        status, body = await self.post(
            "/api/show/compile",
            {"track_hash": TRACK_HASH, "director": "gpt"})
        self.assertEqual(400, status)
        self.assertNotIn("job", body)

    async def test_pressing_twice_follows_the_run_already_going(self):
        """One Claude run per show. The second press gets the live job's
        id rather than a collision message, so both presses watch the
        same run instead of one of them reporting a failure."""
        _, first = await self.post("/api/show/compile",
                                   {"track_hash": TRACK_HASH})
        status, second = await self.post("/api/show/compile",
                                         {"track_hash": TRACK_HASH})
        if status == 409:
            self.assertEqual(first["job"], second["job"])
        # Either the first finished between the presses (202 with a new
        # id) or it was still going (409 with the same one). Both are
        # correct; a 500 or a lost id is not.
        self.assertIn("job", second)

    async def test_revise_is_a_job_too(self):
        status, body = await self.post(f"/api/show/{TRACK_HASH}/revise",
                                       {"feedback": "more blue"})
        # No brAIn in a scratch install, so this refuses before starting —
        # but it refuses with a MESSAGE, which is the half that matters.
        self.assertEqual(409, status)
        self.assertIn("brAIn", body["error"])


class TestTheManualSocket(PanelCase):
    """Manual mode's wire, driven as the phone drives it.

    v1 spent an HTTP round trip on every gesture and the commands backed
    up behind each other; the protocol below is what replaced it, so it
    is worth one test that speaks it rather than trusting the handlers
    it dispatches to.
    """

    async def socket(self):
        return await self.client.ws_connect("/api/live/ws")

    async def ask(self, ws, op):
        await ws.send_json(op)
        return await ws.receive_json(timeout=10)

    async def test_hello_answers_with_the_state_the_panel_renders(self):
        ws = await self.socket()
        try:
            event = await self.ask(ws, {"op": "hello"})
        finally:
            await ws.close()
        self.assertEqual("state", event["ev"])
        self.assertIn("status", event["session"])
        self.assertEqual([], event["loops"])

    async def test_an_op_nobody_implements_is_answered(self):
        # A frame the panel drops is a phone waiting forever on a reply
        # that is never coming.
        ws = await self.socket()
        try:
            event = await self.ask(ws, {"op": "levitate"})
            self.assertEqual("error", event["ev"])
            self.assertIn("levitate", event["message"])
            junk = await self.ask(ws, "not an op at all")
        finally:
            await ws.close()
        self.assertEqual("error", junk["ev"])

    async def test_a_gesture_without_a_session_says_which_button(self):
        ws = await self.socket()
        try:
            event = await self.ask(ws, {"op": "pad", "pad": "drop"})
        finally:
            await ws.close()
        self.assertEqual("error", event["ev"])
        self.assertIn("Manual session", event["message"])

    async def test_a_played_loop_comes_back_as_looping_dots(self):
        ws = await self.socket()
        try:
            started = await self.ask(ws, {"op": "start"})
            self.assertEqual("state", started["ev"])
            self.assertEqual("manual", started["session"]["status"])

            # A tap is answered by light, not by a frame — so the next
            # thing off the socket is the loop's own state.
            await ws.send_json({"op": "tap", "id": f"lifx-{SERIALS[0]}"})
            looping = await self.ask(ws, {
                "op": "loop",
                "taps": [{"t": 0, "id": f"lifx-{SERIALS[0]}"},
                         {"t": 20, "id": f"lifx-{SERIALS[1]}"},
                         {"t": 500, "id": f"lifx-{SERIALS[2]}"}],
                "pressed_ms": 1000})
            self.assertEqual("state", looping["ev"])
            self.assertEqual(1, len(looping["loops"]))
            loop = looping["loops"][0]
            self.assertEqual([f"lifx-{s}" for s in SERIALS[:3]], loop["ids"],
                             "two taps 20ms apart are one hit, all three "
                             "bulbs are marked")
            self.assertEqual(2, loop["strikes"])

            stopped = await self.ask(ws, {"op": "stop_loop",
                                          "id": loop["id"]})
            self.assertEqual([], stopped["loops"])
            ended = await self.ask(ws, {"op": "stop"})
            self.assertFalse(ended["session"]["active"])
        finally:
            await ws.close()
