#!/usr/bin/env python3
"""BRUH Bambu Studio's panel: the printers, the library, the installer, the routes.

The printer is faked at the client (`PrinterClient`'s socket half), never at
the routes: what is under test is that a press on the panel or a service
call from Home Assistant reaches the printer as the request it should, and
that a refusal comes back in the panel's own words.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

(server, store, library, installer, slicer, client_mod, threemf,
 protocol) = bambu_env.load("server", "store", "library", "installer", "slicer",
                            "bambu.client", "bambu.threemf", "bambu.protocol")


def make_3mf(path: Path, plates=(1,), *, seconds=3600, grams=12.5, filaments=2):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        for plate in plates:
            archive.writestr(f"Metadata/plate_{plate}.gcode", "G28\n")
        if plates:
            fil = "".join(f'<filament id="{i + 1}"/>' for i in range(filaments))
            archive.writestr("Metadata/slice_info.config",
                             f'<config><plate><metadata key="prediction" value="{seconds}"/>'
                             f'<metadata key="weight" value="{grams}"/>{fil}</plate></config>')


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.lib = root / "share" / "bambu"
        patches = [
            mock.patch.object(store, "PRINTERS", root / "printers.json"),
            mock.patch.object(store, "SECRETS", root / "secrets" / "printers.json"),
            mock.patch.object(library, "ROOT", self.lib),
            mock.patch.object(installer, "INSTALL_ROOT", root / "bambu-studio"),
            mock.patch.object(installer, "MARKER", root / "bambu-studio" / "installed.json"),
            mock.patch.object(server, "SHARED", root / "config" / ".bruh_bambu"),
            mock.patch.object(server, "STATE_FILE", root / "config" / ".bruh_bambu" / "state.json"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        library.ensure()


class TestPrinterStore(Isolated):
    def test_a_printer_is_stored_apart_from_its_access_code(self):
        row = store.save({"name": "Workshop", "host": "192.168.1.50",
                          "serial": "01p00a123456789", "model": "P1S"}, "zq8W4kT2")
        self.assertEqual(row["id"], "01p00a123456789")
        self.assertEqual(row["serial"], "01P00A123456789")
        self.assertNotIn("zq8W4kT2", store.PRINTERS.read_text())
        self.assertEqual(store.codes(), {row["id"]: "zq8W4kT2"})
        self.assertEqual(oct(store.SECRETS.stat().st_mode & 0o777), "0o600")

    def test_saving_again_keeps_the_code_when_none_is_given(self):
        store.save({"host": "10.0.0.2", "serial": "AAAA11112222"}, "abcd1234")
        store.save({"host": "10.0.0.3", "serial": "AAAA11112222", "name": "Moved"}, None)
        self.assertEqual(store.load()[0]["host"], "10.0.0.3")
        self.assertEqual(store.codes()["aaaa11112222"], "abcd1234")

    def test_bad_fields_are_refused_by_name(self):
        for entry, code, word in (({"host": "not a host!", "serial": "AAAA11112222"}, "abcd1234", "IP"),
                                  ({"host": "10.0.0.2", "serial": "x"}, "abcd1234", "serial"),
                                  ({"host": "10.0.0.2", "serial": "AAAA11112222"}, "no", "access code"),
                                  ({"host": "10.0.0.2", "serial": "AAAA11112222"}, None, "required")):
            with self.subTest(word=word), self.assertRaises(ValueError) as caught:
                store.save(entry, code)
            self.assertIn(word, str(caught.exception))

    def test_which_printer_is_a_question_when_there_are_two(self):
        rows = [store.clean({"name": "X1C", "host": "10.0.0.2", "serial": "AAAA11112222"}),
                store.clean({"name": "A1 mini", "host": "10.0.0.3", "serial": "BBBB11112222"})]
        with self.assertRaises(LookupError) as caught:
            store.resolve(rows, "")
        self.assertIn("Which printer?", str(caught.exception))
        self.assertEqual(store.resolve(rows, "a1")["name"], "A1 mini")
        self.assertEqual(store.resolve(rows, "bbbb11112222")["name"], "A1 mini")
        self.assertEqual(store.resolve(rows[:1], None)["name"], "X1C")
        with self.assertRaises(LookupError):
            store.resolve([], None)


class TestLibrary(Isolated):
    def test_a_name_cannot_leave_the_library(self):
        for bad in ("../../etc/passwd", "/../secrets", "", "sliced/../../x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                library.path_of(bad)
        self.assertEqual(library.path_of("sliced/a.3mf"),
                         Path(os.path.realpath(self.lib / "sliced" / "a.3mf")))

    def test_uploads_are_models_and_nothing_else(self):
        self.assertEqual(library.safe_upload_name("C:\\models\\Benchy.STL"), "Benchy.STL")
        for bad in ("run.sh", ".hidden.3mf", "x.gcode"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                library.safe_upload_name(bad)

    def test_the_listing_says_what_is_sliced(self):
        make_3mf(self.lib / "sliced" / "benchy.gcode.3mf", plates=(1, 2))
        make_3mf(self.lib / "project.3mf", plates=())
        (self.lib / "part.stl").write_bytes(b"solid x")
        rows = {r["path"]: r for r in library.listing()}
        self.assertTrue(rows["sliced/benchy.gcode.3mf"]["sliced"])
        self.assertEqual(rows["sliced/benchy.gcode.3mf"]["plates"], [1, 2])
        self.assertEqual(rows["sliced/benchy.gcode.3mf"]["seconds"], 3600)
        self.assertEqual(rows["sliced/benchy.gcode.3mf"]["grams"], 12.5)
        self.assertFalse(rows["project.3mf"]["sliced"])
        self.assertFalse(rows["part.stl"]["sliced"])

    def test_a_new_name_never_overwrites(self):
        (self.lib / "a.gcode.3mf").write_bytes(b"x")
        new = library.unique(self.lib / "a.gcode.3mf")
        self.assertTrue(new.name.startswith("a-") and new.name.endswith(".gcode.3mf"))


class TestThreeMF(Isolated):
    def test_the_mapping_is_one_slot_per_filament(self):
        make_3mf(self.lib / "two.3mf", filaments=2)
        info = threemf.inspect(str(self.lib / "two.3mf"))
        self.assertEqual(info["filaments"], 2)
        self.assertEqual(threemf.ams_mapping(info), [0, 1])

    def test_a_file_that_is_not_a_zip_is_not_sliced(self):
        (self.lib / "bad.3mf").write_text("nope")
        self.assertFalse(threemf.inspect(str(self.lib / "bad.3mf"))["sliced"])


class TestInstaller(Isolated):
    RELEASE = {"tag_name": "v02.08.02.61", "assets": [
        {"name": "Bambu_Studio_mac-v02.08.02.61.dmg", "browser_download_url": "https://x/mac"},
        {"name": "BambuStudio_ubuntu24.04-v02.08.02.61-20260820225108.AppImage",
         "browser_download_url": "https://x/2404"},
        {"name": "BambuStudio_ubuntu22.04-v02.08.02.61-20260820225108.AppImage",
         "browser_download_url": "https://x/2204"}]}

    def test_the_ubuntu_22_04_build_is_picked_because_it_is_the_one_that_runs(self):
        self.assertEqual(installer.pick_asset(self.RELEASE)["browser_download_url"],
                         "https://x/2204")

    def test_latest_and_a_pinned_tag_ask_the_right_endpoint(self):
        asked = []
        with mock.patch.object(installer, "_get_json",
                               side_effect=lambda url: asked.append(url) or self.RELEASE):
            self.assertEqual(installer.resolve("latest"), ("v02.08.02.61", "https://x/2204"))
            installer.resolve("02.08.02.61")
        self.assertTrue(asked[0].endswith("/releases/latest"))
        self.assertTrue(asked[1].endswith("/releases/tags/v02.08.02.61"))
        with self.assertRaises(ValueError):
            installer.resolve("newest please")

    def test_a_release_with_no_runnable_build_says_so(self):
        with mock.patch.object(installer, "_get_json", return_value={"tag_name": "v9", "assets": []}):
            with self.assertRaises(LookupError) as caught:
                installer.resolve("latest")
        self.assertIn("appimage_url", str(caught.exception))

    def test_a_link_is_used_as_given_and_must_be_https(self):
        self.assertEqual(installer.resolve("latest", "https://e/Bambu-v02.07.00.55.AppImage"),
                         ("v02.07.00.55", "https://e/Bambu-v02.07.00.55.AppImage"))
        with self.assertRaises(ValueError):
            installer.resolve("latest", "http://e/x.AppImage")

    def test_an_install_whose_launcher_is_gone_is_no_install(self):
        installer.INSTALL_ROOT.mkdir(parents=True)
        installer.MARKER.write_text(json.dumps({"version": "v1", "apprun": "/nope/AppRun"}))
        self.assertIsNone(installer.installed())

    def test_a_failed_download_keeps_the_slicer_already_there(self):
        apprun = installer.INSTALL_ROOT / "v1" / "squashfs-root" / "AppRun"
        apprun.parent.mkdir(parents=True)
        apprun.write_text("#!/bin/sh\n")
        installer.MARKER.write_text(json.dumps({"version": "v1", "apprun": str(apprun)}))
        with mock.patch.object(installer, "resolve", return_value=("v2", "https://x")), \
                mock.patch.object(installer, "_download", side_effect=OSError("network down")):
            installer.install("latest")
        self.assertEqual(installer.STATE["phase"], "failed")
        self.assertIn("still in use", installer.STATE["error"])
        self.assertEqual(installer.installed()["version"], "v1")


class TestSlicerCommand(Isolated):
    def test_a_project_slices_with_its_own_settings(self):
        argv = slicer.command("/s/AppRun", Path("/share/bambu/p.3mf"),
                              Path("/share/bambu/sliced/p.gcode.3mf"), plate=0)
        self.assertEqual(argv, ["/s/AppRun", "--slice", "0", "--export-3mf", "p.gcode.3mf",
                                "--outputdir", "/share/bambu/sliced", "/share/bambu/p.3mf"])

    def test_a_bare_model_is_handed_its_profiles(self):
        argv = slicer.command("/s/AppRun", Path("/m.stl"), Path("/o/m.gcode.3mf"),
                              machine=Path("/r/m.json"), process=Path("/r/p.json"),
                              filaments=[Path("/r/f.json")], arrange=True)
        self.assertIn("--load-settings", argv)
        self.assertEqual(argv[argv.index("--load-settings") + 1], "/r/m.json;/r/p.json")
        self.assertEqual(argv[argv.index("--load-filaments") + 1], "/r/f.json")
        self.assertIn("--arrange", argv)

    def test_a_bare_model_without_profiles_is_refused_before_anything_runs(self):
        (self.lib / "m.stl").write_bytes(b"solid")
        with mock.patch.object(installer, "apprun", return_value=Path("/s/AppRun")):
            with self.assertRaises(ValueError) as caught:
                slicer.start("m.stl")
        self.assertIn("machine", str(caught.exception))


class FakeMQTT:
    """paho's client, answering a publish the way a printer does."""

    def __init__(self, owner, result="success"):
        self.owner, self.result, self.sent = owner, result, []

    def publish(self, topic, body):
        self.sent.append((topic, json.loads(body)))
        payload = json.loads(body)
        section = next(iter(payload.values()))
        if self.result is not None and "sequence_id" in section:
            echo = {next(iter(payload)): {**section, "result": self.result,
                                          "reason": "busy" if self.result == "fail" else ""}}
            msg = mock.Mock(payload=json.dumps(echo).encode())
            self.owner._on_message(None, None, msg)


class TestPrinterClient(unittest.TestCase):
    def make(self, result="success"):
        c = client_mod.PrinterClient("10.0.0.2", "AAAA11112222", "abcd1234")
        c._client = FakeMQTT(c, result)
        c.connected = True
        return c

    def test_a_command_goes_to_the_request_topic_and_waits_for_the_echo(self):
        c = self.make()
        self.assertEqual(c.send(protocol.simple("pause")), {"acknowledged": True, "result": "success"})
        topic, body = c._client.sent[-1]
        self.assertEqual(topic, "device/AAAA11112222/request")
        self.assertEqual(body["print"]["command"], "pause")

    def test_a_refusal_is_raised_with_the_printers_reason(self):
        c = self.make("fail")
        with self.assertRaises(RuntimeError) as caught:
            c.send(protocol.simple("resume"))
        self.assertIn("busy", str(caught.exception))

    def test_no_echo_is_reported_as_such_not_as_success(self):
        c = self.make(None)
        with mock.patch.object(client_mod, "ECHO_WAIT_S", 0.3):
            self.assertEqual(c.send(protocol.simple("pause")), {"acknowledged": False})

    def test_reports_merge_and_go_stale(self):
        c = self.make()
        for delta in ({"print": {"gcode_state": "RUNNING", "nozzle_temper": 200}},
                      {"print": {"bed_temper": 60}}):
            c._on_message(None, None, mock.Mock(payload=json.dumps(delta).encode()))
        out = c.summary()
        self.assertEqual((out["state"], out["nozzle_c"], out["bed_c"]), ("running", 200.0, 60.0))
        self.assertTrue(out["online"])
        c.last_report = time.time() - client_mod.STALE_AFTER_S - 5
        self.assertFalse(c.summary()["online"])
        self.assertIn("stopped reporting", c.summary()["connection_error"])

    def test_a_disconnected_printer_refuses_rather_than_queueing(self):
        c = self.make()
        c.connected = False
        c.last_error = "The printer refused the access code."
        with self.assertRaises(ConnectionError) as caught:
            c.send(protocol.simple("stop"))
        self.assertIn("access code", str(caught.exception))


class FakeClient:
    def __init__(self, summary=None, answer=None):
        self.host, self.code, self.connected, self.last_error = "10.0.0.2", "abcd1234", True, ""
        self._summary = summary or {"online": True, "state": "idle", "printing": False}
        self.answer = answer or {"acknowledged": True, "result": "success"}
        self.sent = []

    def summary(self):
        return dict(self._summary)

    def send(self, payload):
        self.sent.append(payload)
        return self.answer

    def tick(self):
        pass

    def stop(self):
        pass


class RouteTest(Isolated):
    def setUp(self):
        super().setUp()
        store.save({"name": "X1C", "host": "10.0.0.2", "serial": "AAAA11112222"}, "abcd1234")
        self.panel = server.Panel(start_clients=False)
        self.fake = FakeClient()
        self.panel.clients["aaaa11112222"] = self.fake
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.http = TestClient(TestServer(server.build_app(self.panel, ticker=False)), loop=self.loop)
        self.loop.run_until_complete(self.http.start_server())
        self.addCleanup(lambda: self.loop.run_until_complete(self.http.close()))

    def call(self, method, path, **kw):
        async def go():
            resp = await self.http.request(method, path, **kw)
            return resp.status, await resp.json()
        return self.loop.run_until_complete(go())


class TestRoutes(RouteTest):
    def test_health_and_state(self):
        self.assertEqual(self.call("GET", "/api/health"), (200, {"ok": True}))
        status, body = self.call("GET", "/api/state")
        self.assertEqual(body["printers"][0]["name"], "X1C")
        self.assertFalse(body["studio"]["installed"])

    def test_a_command_reaches_the_printer(self):
        status, body = self.call("POST", "/api/printer/command",
                                 json={"action": "speed", "value": "sport"})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.sent[-1], protocol.speed("sport"))
        self.assertEqual(body["note"], "")

    def test_an_unconfirmed_command_says_why_it_may_have_done_nothing(self):
        self.fake.answer = {"acknowledged": False}
        _, body = self.call("POST", "/api/printer/command", json={"action": "pause"})
        self.assertIn("Developer mode", body["note"])

    def test_gcode_and_heat_wait_while_printing(self):
        self.fake._summary = {"online": True, "state": "running", "printing": True}
        for action in ({"action": "gcode", "value": "G28"},
                       {"action": "temperature", "target": "bed", "value": 60},
                       {"action": "home"}):
            status, body = self.call("POST", "/api/printer/command", json=action)
            self.assertEqual(status, 400)
            self.assertIn("printing", body["error"])
        self.assertEqual(self.fake.sent, [])

    def test_a_bad_argument_is_a_400_in_words(self):
        status, body = self.call("POST", "/api/printer/command",
                                 json={"action": "temperature", "target": "bed", "value": 600})
        self.assertEqual(status, 400)
        self.assertIn("0–120", body["error"])

    def test_an_unknown_printer_is_named(self):
        status, body = self.call("POST", "/api/printer/command",
                                 json={"action": "pause", "printer": "Prusa"})
        self.assertEqual(status, 404)
        self.assertIn("X1C", body["error"])

    def test_a_sliced_file_is_uploaded_and_started(self):
        make_3mf(self.lib / "sliced" / "benchy.gcode.3mf", plates=(1, 2), filaments=2)
        uploads = []

        class Storage:
            def __init__(self, host, code):
                uploads.append((host, code))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def upload(self, local, name, progress=None):
                uploads.append(name)
                progress and progress(10, 10)
                return 10

        with mock.patch.object(server.ftps, "Storage", Storage):
            status, body = self.call("POST", "/api/print", json={
                "file": "sliced/benchy.gcode.3mf", "plate": 2, "wait": 10})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["job"]["phase"], "started")
        self.assertEqual(uploads, [("10.0.0.2", "abcd1234"), "benchy.gcode.3mf"])
        sent = self.fake.sent[-1]["print"]
        self.assertEqual(sent["param"], "Metadata/plate_2.gcode")
        self.assertEqual(sent["ams_mapping"], [0, 1])
        self.assertIs(sent["use_ams"], False)

    def test_a_plate_the_file_does_not_have_is_refused(self):
        make_3mf(self.lib / "one.gcode.3mf", plates=(1,))
        _, body = self.call("POST", "/api/print", json={"file": "one.gcode.3mf",
                                                        "plate": 3, "wait": 10})
        self.assertFalse(body["ok"])
        self.assertIn("Plate 3", body["error"])

    def test_a_printer_already_printing_is_not_sent_a_second_job(self):
        make_3mf(self.lib / "one.gcode.3mf")
        self.fake._summary = {"online": True, "state": "running", "printing": True}
        _, body = self.call("POST", "/api/print", json={"file": "one.gcode.3mf", "wait": 10})
        self.assertIn("already printing", body["error"])
        self.assertEqual(self.fake.sent, [])

    def test_file_routes_stay_inside_the_library(self):
        status, _ = self.call("DELETE", "/api/files?path=../../printers.json")
        self.assertEqual(status, 400)
        self.assertTrue(store.PRINTERS.exists())

    def test_the_mirror_carries_no_access_code(self):
        server.SHARED.parent.mkdir()
        self.panel.publish()
        text = server.STATE_FILE.read_text()
        self.assertIn("X1C", text)
        self.assertNotIn("abcd1234", text)

    def test_no_mirror_is_written_where_there_is_no_config(self):
        # A dev checkout must not grow a stray /config.
        self.panel.publish()
        self.assertFalse(server.SHARED.parent.exists())


if __name__ == "__main__":
    unittest.main()
