"""BRUH Bambu Studio: the printer card's backend — camera, pictures, reconnect,
storage, the Home Assistant setup, and the print options in one table."""
from __future__ import annotations

import json
import os
import socket
import ssl
import struct
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from bambu_env import load  # noqa: E402

(camera, protocol, ftps, threemf, options, profiles, thumbs, slicer, ha_setup,
 server) = load("bambu.camera", "bambu.protocol", "bambu.ftps", "bambu.threemf",
                "design.options", "design.profiles", "thumbs", "slicer", "ha_setup", "server")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"frame" + b"\xff\xd9"


def sliced_3mf(path: Path, *, picture: bool = True) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/plate_1.gcode", "G28\n")
        if picture:
            z.writestr("Metadata/plate_1.png", PNG)
            z.writestr("Metadata/plate_no_light_1.png", b"\x89PNG other")
        z.writestr("Metadata/slice_info.config", """<?xml version="1.0"?>
<config><plate><metadata key="prediction" value="5400"/><metadata key="weight" value="38.5"/>
<filament id="1" type="PLA" color="#FFFFFF" used_m="9" used_g="30.1"/>
<filament id="2" type="PLA" color="#18C241" used_m="3" used_g="8.4"/></plate></config>""")
    return path


class TestTheCameraProtocol(unittest.TestCase):
    def test_the_auth_packet_is_eighty_bytes_with_the_code_in_it(self):
        packet = camera.auth_packet("12345678")
        self.assertEqual(len(packet), 80)
        self.assertEqual(struct.unpack("<IIII", packet[:16]), (0x40, 0x3000, 0, 0))
        self.assertEqual(packet[16:20], b"bblp")
        self.assertEqual(packet[48:56], b"12345678")
        self.assertEqual(packet[56:80], b"\x00" * 24)

    def test_a_frame_is_read_by_its_length(self):
        a, b = socket.socketpair()
        try:
            a.sendall(struct.pack("<I", len(JPEG)) + b"\x00" * 12 + JPEG)
            self.assertEqual(camera.read_frame(b), JPEG)
        finally:
            a.close()
            b.close()

    def test_a_frame_that_is_not_a_jpeg_is_refused(self):
        a, b = socket.socketpair()
        try:
            a.sendall(struct.pack("<I", 4) + b"\x00" * 12 + b"nope")
            with self.assertRaises(ConnectionError):
                camera.read_frame(b)
        finally:
            a.close()
            b.close()

    def test_an_mjpeg_stream_is_cut_into_whole_frames(self):
        buffer = bytearray(b"junk" + JPEG + JPEG[:5])
        self.assertEqual(camera.split_jpegs(buffer), [JPEG])
        self.assertEqual(bytes(buffer), JPEG[:5])
        buffer.extend(JPEG[5:])
        self.assertEqual(camera.split_jpegs(buffer), [JPEG])

    def test_which_camera_a_model_has(self):
        self.assertEqual(protocol.camera_kind("A1", None), "jpeg")
        self.assertEqual(protocol.camera_kind("P1S", None), "jpeg")
        self.assertEqual(protocol.camera_kind("X1C", None), "rtsp")
        self.assertEqual(protocol.camera_kind("", "rtsps://1.2.3.4/streaming/live/1"), "rtsp")
        self.assertEqual(protocol.camera_kind("X1C", "disable"), "disabled")

    def test_the_rtsp_address_carries_the_credentials_and_the_reported_path(self):
        self.assertEqual(camera.rtsp_url("10.0.0.5", "code", "rtsps://10.0.0.5/streaming/live/1"),
                         "rtsps://bblp:code@10.0.0.5:322/streaming/live/1")

    def test_a_real_tls_camera_is_read_end_to_end(self):
        """The port-6000 dialogue over real TLS: auth in, frames out."""
        cert_dir = tempfile.mkdtemp()
        key, crt = os.path.join(cert_dir, "k.pem"), os.path.join(cert_dir, "c.pem")
        if os.system(f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {key} -out {crt} "
                     f"-days 1 -subj /CN=printer >/dev/null 2>&1") != 0:
            self.skipTest("no openssl to make a certificate")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        got = {}

        def printer():
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(crt, key)
            conn, _ = listener.accept()
            with ctx.wrap_socket(conn, server_side=True) as tls:
                got["auth"] = camera.read_exact(tls, 80)
                for _ in range(3):
                    tls.sendall(struct.pack("<I", len(JPEG)) + b"\x00" * 12 + JPEG)
                tls.recv(1)

        threading.Thread(target=printer, daemon=True).start()
        cam = camera.Camera("127.0.0.1", "secret12", "jpeg")
        with mock.patch.object(camera, "JPEG_PORT", port):
            frame = cam.latest(5)
        cam.wanted_at = 0
        self.assertEqual(frame, JPEG)
        self.assertEqual(got["auth"][48:56], b"secret12")
        listener.close()

    def test_a_camera_switched_off_says_where_to_turn_it_on(self):
        cam = camera.Camera("127.0.0.1", "x", "disabled")
        self.assertIsNone(cam.latest(1))
        self.assertIn("LAN mode live view", cam.error)


class TestTheReport(unittest.TestCase):
    REPORT = {"print": {"gcode_state": "RUNNING", "stg_cur": 4, "cooling_fan_speed": "15",
                        "big_fan1_speed": "6", "nozzle_diameter": "0.4",
                        "ipcam": {"rtsp_url": "disable"},
                        "hms": [{"attr": 0x07002000, "code": 0x00020001}],
                        "vt_tray": {"tray_type": "TPU", "tray_color": "FFA500FF"},
                        "ams": {"tray_now": "1", "ams": [{"id": "0", "humidity": "4", "temp": "27.5",
                                                          "tray": [{"id": "1", "tray_type": "PLA",
                                                                    "tray_sub_brands": "PLA Matte"}]}]}}}

    def test_the_stage_fans_ams_and_errors_are_read(self):
        out = protocol.summarise(self.REPORT)
        self.assertEqual(out["stage"], "Changing filament")
        self.assertEqual(out["fans"]["part"], 100)
        self.assertEqual(out["fans"]["aux"], 40)
        self.assertEqual(out["hms"], ["0700_2000_0002_0001"])
        self.assertEqual(out["active_tray"], 1)
        self.assertEqual(out["ams"][0]["name"], "PLA Matte")
        self.assertEqual(out["ams_units"], [{"id": 0, "humidity": 4, "temp_c": 27.5}])
        self.assertEqual(out["external_spool"]["slot"], "external")
        self.assertEqual(out["external_spool"]["colour"], "#FFA500")
        self.assertEqual(out["rtsp_url"], "disable")

    def test_an_idle_printer_has_no_stage_and_the_external_spool_feeds(self):
        out = protocol.summarise({"print": {"gcode_state": "IDLE", "stg_cur": 0,
                                            "ams": {"tray_now": "254"}}})
        self.assertIsNone(out["stage"])
        self.assertEqual(out["active_tray"], "external")

    def test_an_unknown_stage_is_said_as_its_number(self):
        out = protocol.summarise({"print": {"gcode_state": "RUNNING", "stg_cur": 99}})
        self.assertEqual(out["stage"], "Stage 99")


class TestOneTableOfOptions(unittest.TestCase):
    def test_values_out_of_range_or_unknown_are_dropped_not_clamped(self):
        got = options.clean_slice({"layer_height": 0.5, "walls": "4", "brim": "outer",
                                   "print_sequence": "by_object", "ironing": "sometimes",
                                   "prime_tower": "false", "infill_percent": True})
        self.assertEqual(got, {"walls": 4, "brim": "outer", "print_sequence": "by object",
                               "prime_tower": False})

    def test_every_enum_value_written_is_one_bambu_studio_knows(self):
        # The values Bambu Studio's own key maps hold (PrintConfig.cpp).
        known = {"sparse_infill_pattern": {"grid", "gyroid", "cubic", "honeycomb", "line",
                                           "triangles", "adaptivecubic", "lightning", "zig-zag",
                                           "concentric", "alignedrectilinear"},
                 "wall_generator": {"classic", "arachne"},
                 "seam_position": {"aligned", "nearest", "back", "random"},
                 "ironing_type": {"no ironing", "top", "topmost", "solid"},
                 "support_type": {"normal(auto)", "tree(auto)", None},
                 "brim_type": {"no_brim", "outer_only", "inner_only", "outer_and_inner",
                               "auto_brim", "brim_ears"},
                 "print_sequence": {"by layer", "by object"},
                 "fuzzy_skin": {"none", "external", "all"}}
        for key, (_l, _g, kind, spec, pkey, _h) in options.SLICE.items():
            if kind == "enum":
                self.assertLessEqual(set(spec.values()), known[pkey], key)
        beds = {p[1] for p in options.PLATES.values() if p[1]}
        self.assertLessEqual(beds, {"Cool Plate", "Engineering Plate", "High Temp Plate",
                                    "Textured PEI Plate"})

    def test_the_process_profile_gets_bambu_studio_keys(self):
        out = options.process_values({"supports": "tree", "infill_percent": 25,
                                      "print_sequence": "by object", "layer_height": 0.12,
                                      "plate_type": "textured_pei", "prime_tower": False})
        self.assertEqual(out["enable_support"], "1")
        self.assertEqual(out["support_type"], "tree(auto)")
        self.assertEqual(out["sparse_infill_density"], "25%")
        self.assertEqual(out["print_sequence"], "by object")
        self.assertEqual(out["layer_height"], "0.12")
        self.assertEqual(out["curr_bed_type"], "Textured PEI Plate")
        self.assertEqual(out["enable_prime_tower"], "0")

    def test_a_vase_is_written_as_a_vase_the_slicer_accepts(self):
        out = options.process_values({"vase": True, "walls": 3})
        self.assertEqual((out["spiral_mode"], out["wall_loops"], out["sparse_infill_density"]),
                         ("1", "1", "0%"))

    def test_the_nozzle_temperature_goes_to_the_filament(self):
        self.assertNotIn("nozzle_temperature", options.process_values({"nozzle_temp": 225}))
        self.assertEqual(options.filament_values({"nozzle_temp": 225})["nozzle_temperature"], ["225"])

    def test_start_options_and_the_plate_the_printer_checks(self):
        self.assertEqual(options.clean_start({"plate_type": "Textured PEI", "copies": "3",
                                              "speed": "sport", "timelapse": "yes"}),
                         {"plate_type": "textured_pei", "copies": 3, "speed": "sport",
                          "timelapse": True})
        self.assertEqual(options.mqtt_bed_type("cool"), "cool_plate")
        self.assertEqual(options.mqtt_bed_type(None), "auto")

    def test_brain_is_offered_every_option_by_schema(self):
        props = options.schema_properties()
        for key in list(options.SLICE) + list(options.START):
            self.assertIn(key, props)
        self.assertEqual(props["print_sequence"]["enum"], ["by layer", "by object"])

    def test_the_catalog_the_dialogs_are_built_from(self):
        cat = options.catalog()
        self.assertEqual({o["key"] for o in cat["slice"]}, set(options.SLICE))
        self.assertIn("Layout", {o["group"] for o in cat["slice"]})

    def test_profiles_apply_writes_them_over_the_process(self):
        out = profiles.apply({"name": "0.20mm Standard", "wall_loops": "2"}, {"walls": 5})
        self.assertEqual(out["wall_loops"], "5")
        self.assertTrue(out["name"].endswith("(BRUH Bambu)"))

    def test_project_file_carries_the_plate_and_inspection(self):
        body = protocol.project_file("a.3mf", 1, use_ams=True, ams_mapping=[0], timelapse=False,
                                     bed_leveling=True, flow_cali=False, vibration_cali=True,
                                     bed_type="textured_plate", layer_inspect=True)["print"]
        self.assertEqual((body["bed_type"], body["layer_inspect"]), ("textured_plate", True))
        body = protocol.project_file("a.3mf", 1, use_ams=True, ams_mapping=[0], timelapse=False,
                                     bed_leveling=True, flow_cali=False, vibration_cali=True,
                                     bed_type="lava")["print"]
        self.assertEqual(body["bed_type"], "auto")


class TestSlicing(unittest.TestCase):
    def test_copies_repeat_one_plate(self):
        argv = slicer.command("/AppRun", Path("/x/part.3mf"), Path("/out/p.gcode.3mf"), copies=4)
        self.assertEqual(argv[argv.index("--slice") + 1], "1")
        self.assertEqual(argv[argv.index("--repetitions") + 1], "4")
        self.assertIn("--arrange", argv)

    def test_the_setting_the_cli_rejected_is_named(self):
        lines = ["[info] loading", "Param values in 3mf/config error: ",
                 "filament_prime_volume: 0 not in range [1,1e+308]", "run found error, return -18"]
        self.assertEqual(slicer.rejected(lines), ["filament_prime_volume: 0 not in range [1,1e+308]"])

    def test_a_sliced_job_is_described_with_its_filaments(self):
        info = threemf.inspect(str(sliced_3mf(Path(tempfile.mkdtemp()) / "a.3mf")))
        self.assertEqual(info["seconds"], 5400)
        self.assertEqual([f["grams"] for f in info["filament_use"]], [30.1, 8.4])
        text = server.describe_slice(info)
        self.assertIn("1 h 30 min", text)
        self.assertIn("38.5 g of filament", text)
        self.assertIn("8.4 g #18C241 PLA", text)


class FakeStorage:
    """bambu.ftps.Storage's read_range over bytes, counting the reads."""

    def __init__(self, data: bytes):
        self.data, self.reads = data, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read_range(self, _name, offset, length):
        self.reads += 1
        return self.data[offset:offset + length]


class TestPictures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.object(thumbs, "CACHE", self.tmp / "cache")
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_plate_picture_is_chosen_over_the_others(self):
        self.assertEqual(thumbs.png_member(["Metadata/plate_no_light_1.png", "Metadata/plate_1.png"]),
                         "Metadata/plate_1.png")
        self.assertIsNone(thumbs.png_member(["3D/3dmodel.model"]))

    def test_a_library_3mf_gives_its_own_picture_and_it_is_kept(self):
        path = sliced_3mf(self.tmp / "a.3mf")
        self.assertEqual(thumbs.library(path), PNG)
        with mock.patch.object(thumbs, "from_zip", side_effect=AssertionError("read again")):
            self.assertEqual(thumbs.library(path), PNG)

    def test_a_file_with_no_picture_is_remembered_as_having_none(self):
        path = sliced_3mf(self.tmp / "b.3mf", picture=False)
        with mock.patch.object(thumbs, "render", return_value=False) as render:
            self.assertIsNone(thumbs.library(path))
            self.assertIsNone(thumbs.library(path))
        self.assertEqual(render.call_count, 1)

    def test_a_picture_on_the_printer_is_read_in_a_few_pieces(self):
        data = sliced_3mf(self.tmp / "c.3mf").read_bytes()
        storage = FakeStorage(data)
        self.assertEqual(thumbs.printer("SER", "c.3mf", len(data), lambda: storage), PNG)
        self.assertLessEqual(storage.reads, 4)
        storage.reads = 0
        self.assertEqual(thumbs.printer("SER", "c.3mf", len(data), lambda: storage), PNG)
        self.assertEqual(storage.reads, 0)

    def test_a_printer_that_cannot_be_reached_is_not_remembered_as_pictureless(self):
        class Broken(FakeStorage):
            def read_range(self, *a):
                raise OSError("unreachable")

        data = sliced_3mf(self.tmp / "d.3mf").read_bytes()
        with self.assertRaises(OSError):
            thumbs.printer("SER", "d.3mf", len(data), lambda: Broken(b""))
        self.assertEqual(thumbs.printer("SER", "d.3mf", len(data), lambda: FakeStorage(data)), PNG)

    def test_a_remote_zip_reads_slice_info_too(self):
        data = sliced_3mf(self.tmp / "e.3mf").read_bytes()
        info = threemf.inspect(ftps.RemoteFile(FakeStorage(data), "e.3mf", len(data)))
        self.assertEqual(info["plates"], [1])
        self.assertEqual(info["filaments"], 2)

    def test_the_stl_drawing_script_draws(self):
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("numpy and Pillow are in the image's CAD virtualenv")
        sys.path.insert(0, str(Path(__file__).parent.parent / "bruh-bambu-studio" / "cad"))
        try:
            import thumb
        finally:
            sys.path.pop(0)
        import numpy as np
        v = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], float)
        f = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])
        image = thumb.render(v, f, 64)
        self.assertEqual(image.size, (64, 64))
        self.assertGreater(sum(1 for px in image.convert('RGBA').tobytes()[3::4] if px), 100)


class TestHomeAssistantSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cc").mkdir()
        (self.tmp / "cc" / "manifest.json").write_text(json.dumps({"version": "0.2.0"}))
        for name, value in (("DEPLOYED", self.tmp / "cc"), ("SHARED", self.tmp / "shared"),
                            ("NOTIFIED", self.tmp / "notified")):
            p = mock.patch.object(ha_setup, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t", "ENABLE_HA_INTEGRATION": "true"})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []

    def fake(self, answers):
        def call(method, path, body=None):
            self.calls.append((method, path, body))
            for prefix, answer in answers:
                if path.startswith(prefix):
                    return answer.pop(0) if isinstance(answer, list) else answer
            return 404, None
        return mock.patch.object(ha_setup, "_call", side_effect=call)

    def test_core_that_does_not_know_the_integration_asks_for_a_restart_once(self):
        with self.fake([("/core/api/config/config_entries/entry", (200, [])),
                        ("/core/api/config/config_entries/flow",
                         (400, {"message": "Invalid handler specified"})),
                        ("/core/api/services/persistent_notification", (200, []))]):
            state = ha_setup.check(force=True)
            ha_setup.check(force=True)
        self.assertTrue(state["restart_needed"])
        notes = [c for c in self.calls if "persistent_notification" in c[1]]
        self.assertEqual(len(notes), 1)
        self.assertIn("Restart Home Assistant", notes[0][2]["message"])

    def test_once_core_knows_it_the_entry_is_made_without_anybody(self):
        with self.fake([("/core/api/config/config_entries/entry",
                         [(200, []), (200, [{"domain": "bruh_bambu", "state": "loaded", "entry_id": "e"}])]),
                        ("/core/api/config/config_entries/flow/f1", (200, {"type": "create_entry"})),
                        ("/core/api/config/config_entries/flow",
                         (200, {"type": "form", "flow_id": "f1", "step_id": "user"}))]):
            (self.tmp / "shared").mkdir()
            (self.tmp / "shared" / "integration.json").write_text(json.dumps({"version": "0.2.0"}))
            state = ha_setup.check(force=True)
        self.assertEqual(state["entry"]["state"], "loaded")
        self.assertFalse(state["restart_needed"])

    def test_an_older_running_copy_is_a_restart(self):
        (self.tmp / "shared").mkdir()
        (self.tmp / "shared" / "integration.json").write_text(json.dumps({"version": "0.1.6"}))
        with self.fake([("/core/api/config/config_entries/entry",
                         (200, [{"domain": "bruh_bambu", "state": "loaded", "entry_id": "e"}])),
                        ("/core/api/services/persistent_notification", (200, []))]):
            state = ha_setup.check(force=True)
        self.assertTrue(state["restart_needed"])
        self.assertEqual(state["reason"], "update")

    def test_the_restart_is_the_homeassistant_service_the_add_on_may_call(self):
        with self.fake([("/core/api/services/homeassistant/restart", (200, []))]):
            ok, _why = ha_setup.restart_core()
        self.assertTrue(ok)


class TestRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.tmp = Path(tempfile.mkdtemp())
        for target, name, value in ((server.library, "ROOT", self.tmp / "lib"),
                                    (server.store, "PRINTERS", self.tmp / "printers.json")):
            if hasattr(target, name):
                p = mock.patch.object(target, name, value)
                p.start()
                self.addCleanup(p.stop)
        (self.tmp / "lib").mkdir()
        self.panel = server.Panel(start_clients=False)
        self.client = TestClient(TestServer(server.build_app(self.panel, ticker=False)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_the_options_are_served(self):
        r = await self.client.get("/api/print/options")
        body = await r.json()
        self.assertIn("print_sequence", {o["key"] for o in body["slice"]})

    async def test_a_library_picture_is_served_and_a_path_outside_is_not(self):
        sliced_3mf(self.tmp / "lib" / "a.3mf")
        with mock.patch.object(thumbs, "CACHE", self.tmp / "cache"):
            r = await self.client.get("/api/thumb", params={"path": "a.3mf"})
            self.assertEqual(r.status, 200)
            self.assertEqual(await r.read(), PNG)
            r = await self.client.get("/api/thumb", params={"path": "../../etc/passwd"})
            self.assertEqual(r.status, 404)

    async def test_a_name_on_the_printer_cannot_leave_its_folder(self):
        for name in ("../x.3mf", "a/b.3mf", ".hidden", "x\x00.3mf"):
            with self.assertRaises(ValueError, msg=name):
                server._storage_name(name)
        self.assertEqual(server._storage_name("Gear rotor v2.gcode.3mf"), "Gear rotor v2.gcode.3mf")

    async def test_reconnect_opens_a_new_session(self):
        row = {"id": "p1", "name": "A1", "host": "1.2.3.4", "serial": "S", "model": "A1"}
        old = mock.Mock(host="1.2.3.4", code="c")
        self.panel.clients["p1"] = old
        with mock.patch.object(server.store, "resolve", return_value=row), \
                mock.patch.object(server.store, "load", return_value=[row]), \
                mock.patch.object(server.store, "codes", return_value={"p1": "c"}):
            r = await self.client.post("/api/printer/command", json={"printer": "p1", "action": "reconnect"})
        self.assertEqual(r.status, 200)
        old.stop.assert_called_once()
        self.assertIsNot(self.panel.clients["p1"], old)

    async def test_a_camera_with_nothing_to_show_says_why(self):
        row = {"id": "p1", "name": "A1", "host": "127.0.0.1", "serial": "S", "model": "X1C"}
        client = mock.Mock(host="127.0.0.1", code="c")
        client.summary.return_value = {"rtsp_url": "disable"}
        self.panel.clients["p1"] = client
        with mock.patch.object(server.store, "resolve", return_value=row):
            r = await self.client.get("/api/printer/camera", params={"printer": "p1"})
        self.assertEqual(r.status, 503)
        self.assertIn("LAN mode live view", (await r.json())["error"])


if __name__ == "__main__":
    unittest.main()
