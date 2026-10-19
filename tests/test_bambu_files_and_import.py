#!/usr/bin/env python3
"""BRUH Bambu Studio's Files list, link import, bare-model printing and colours.

* The Files list is what somebody brought in: the add-on's own slices and
  every design version's meshes are kept out, and a designed part appears
  once, as its current version.
* A link is imported from a local HTTP server that answers as Printables'
  GraphQL and file host do (one query lists the model's files, one mutation
  hands out each link), and as a plain file host — the real sites are not
  reachable from CI and a fake that accepted anything would prove nothing.
* A bare model gets Bambu Studio's profiles for the printer, with the
  filament following the tray.
"""
import http.server
import json
import os
import sys
import threading
import unittest
import unittest.mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_panel import FakeClient, Isolated, RouteTest, make_3mf, server  # noqa: E402

library = server.library
importer = server.importer
parts = server.parts
threemf = server.threemf

STL = b"solid cube\nendsolid cube\n"


def make_part(name="Bracket", n=1, colours=None):
    part = parts.create(name)
    vdir = parts.version_dir(part["id"], n)
    (vdir / "bodies").mkdir(parents=True)
    with zipfile.ZipFile(vdir / "bracket.3mf", "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
    (vdir / "bracket.stl").write_bytes(STL)
    (vdir / "bodies" / "Body.stl").write_bytes(STL)
    part["versions"] = [{"n": n, "ok": True, "colors": colours,
                         "files": {"3mf": "bracket.3mf", "stl": "bracket.stl",
                                   "bodies": {"Body": "bodies/Body.stl"}}}]
    part["current"] = n
    parts.save(part)
    return part


class TestTheFilesListIsWhatYouBroughtIn(RouteTest):
    def test_slices_and_design_versions_stay_out(self):
        make_3mf(self.lib / "sliced" / "benchy.gcode.3mf")
        (self.lib / "upload.stl").write_bytes(STL)
        part = make_part()
        _, body = self.call("GET", "/api/files")
        paths = [f["path"] for f in body["files"]]
        self.assertIn("upload.stl", paths)
        self.assertFalse([p for p in paths if p.startswith("sliced/")])
        design_rows = [f for f in body["files"] if f.get("design")]
        self.assertEqual(len(design_rows), 1, paths)
        self.assertEqual(design_rows[0]["design"], part["id"])
        self.assertEqual(design_rows[0]["name"], "Bracket.3mf")
        self.assertEqual(design_rows[0]["version"], 1)
        # Only the current version's 3MF, never its STL, STEP or bodies.
        self.assertEqual(len([p for p in paths if p.startswith("designs/")]), 1)

    def test_working_files_are_there_for_a_caller_that_asks(self):
        make_3mf(self.lib / "sliced" / "benchy.gcode.3mf")
        _, body = self.call("GET", "/api/files?working=1")
        self.assertIn("sliced/benchy.gcode.3mf", [f["path"] for f in body["files"]])

    def test_a_part_with_no_built_version_is_not_listed(self):
        parts.create("Nothing yet")
        _, body = self.call("GET", "/api/files")
        self.assertEqual([f for f in body["files"] if f.get("design")], [])

    def test_a_design_file_is_not_deleted_from_the_files_tab(self):
        part = make_part()
        rel = f"designs/{part['id']}/v1/bracket.3mf"
        status, body = self.call("DELETE", f"/api/files?path={rel}")
        self.assertEqual(status, 409)
        self.assertIn("Design tab", body["error"])
        self.assertTrue((self.lib / rel).is_file())


class TestABareModelIsGivenProfiles(Isolated):
    def setUp(self):
        super().setUp()
        self.row = {"id": "aaaa11112222", "name": "X1C", "model": "X1C"}
        self.client = FakeClient(summary={"online": True, "ams": [
            {"slot": 0, "type": "PETG", "colour": "#111111"},
            {"slot": 2, "type": "PLA", "colour": "#F2F2F2"}]})
        (self.lib / "cube.stl").write_bytes(STL)
        self.prepared = []

        def prepare(model, settings, outdir):
            self.prepared.append((model, settings))
            return {"paths": {}, "material": settings["material"]}
        patch = unittest.mock.patch.object(server.profiles, "prepare", prepare)
        patch.start()
        self.addCleanup(patch.stop)

    def profiles_for(self, **body):
        body = {"file": "cube.stl", **body}
        return server._bare_model_profiles(body, self.row, self.client), body

    def test_a_named_tray_decides_the_material(self):
        prepared, body = self.profiles_for(slot=0)
        self.assertEqual(self.prepared, [("X1C", {"material": "PETG"})])
        self.assertEqual((body["use_ams"], body["ams_mapping"]), (True, [0]))
        self.assertIsNotNone(prepared)

    def test_no_tray_named_takes_the_best_match(self):
        _, body = self.profiles_for(colour="white")
        self.assertEqual(body["ams_mapping"], [2])
        self.assertEqual(self.prepared[-1][1], {"material": "PLA"})

    def test_the_external_spool_uses_the_material_said(self):
        _, body = self.profiles_for(slot="external", material="petg")
        self.assertEqual((body["use_ams"], body["ams_mapping"]), (False, [0]))
        self.assertEqual(self.prepared[-1][1], {"material": "PETG"})

    def test_a_tray_the_printer_does_not_have_is_named(self):
        with self.assertRaises(LookupError) as caught:
            self.profiles_for(slot=5)
        self.assertIn("tray 6", str(caught.exception))

    def test_a_project_or_a_slice_keeps_its_own_settings(self):
        make_3mf(self.lib / "sliced.gcode.3mf")
        with zipfile.ZipFile(self.lib / "project.3mf", "w") as archive:
            archive.writestr("Metadata/project_settings.config", "{}")
        for name in ("sliced.gcode.3mf", "project.3mf"):
            with self.subTest(file=name):
                self.assertIsNone(server._bare_model_profiles(
                    {"file": name}, self.row, self.client))
        self.assertIsNone(server._bare_model_profiles(
            {"file": "cube.stl", "machine": "M", "process": "P"}, self.row, self.client))
        self.assertEqual(self.prepared, [])

    def test_a_3mf_from_elsewhere_is_bare(self):
        with zipfile.ZipFile(self.lib / "printables.3mf", "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model/>")
        self.assertFalse(threemf.inspect(str(self.lib / "printables.3mf"))["project"])
        self.assertIsNotNone(server._bare_model_profiles(
            {"file": "printables.3mf"}, self.row, self.client))


class _Site(http.server.BaseHTTPRequestHandler):
    """Printables' GraphQL and file host, and a plain file host, on loopback."""

    files = {"/files/benchy.stl": STL, "/files/bracket.3mf": b"PK\x03\x04 3mf"}

    def log_message(self, *_):
        pass

    def _send(self, code, body, kind="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in self.files:
            self._send(200, self.files[self.path])
        elif self.path == "/download?id=7":
            self._send(200, STL, extra={"Content-Disposition": 'attachment; filename="named.stl"'})
        elif self.path == "/page":
            self._send(200, b"<html>a model page</html>", "text/html; charset=utf-8")
        elif self.path == "/to-file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd")
            self.end_headers()
        else:
            self._send(404, b"")

    def do_POST(self):
        query = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        base = f"http://127.0.0.1:{self.server.server_port}"
        if "getDownloadLink" in query["query"]:
            name = {"11": "benchy.stl", "12": "bracket.3mf"}[query["variables"]["id"]]
            out = {"getDownloadLink": {"ok": True, "output": {"link": f"{base}/files/{name}"}}}
        elif query["variables"]["id"] == "404":
            out = {"print": None}
        else:
            out = {"print": {"id": "3161", "name": "3D Benchy & Bracket", "stls": [
                {"id": "11", "name": "benchy.stl"}, {"id": "12", "name": "bracket.3mf"},
                {"id": "13", "name": "instructions.pdf"}]}}
        self._send(200, json.dumps({"data": out}).encode(), "application/json")


class TestImportingALink(Isolated):
    @classmethod
    def setUpClass(cls):
        cls.site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()

    def run_import(self, url):
        # The importer must write into the library this test isolated; a
        # stale module from another load would write into the real one.
        self.assertIs(importer.library, library)
        job = {}
        with unittest.mock.patch.object(importer, "PRINTABLES_API", f"{self.base}/graphql"), \
                unittest.mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}):
            importer.run(job, url)
        return job

    def test_a_printables_page_brings_every_model_file(self):
        job = self.run_import("https://www.printables.com/model/3161-3d-benchy")
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(job["files"], ["imports/3D Benchy Bracket/benchy.stl",
                                        "imports/3D Benchy Bracket/bracket.3mf"])
        self.assertEqual((self.lib / job["files"][0]).read_bytes(), STL)

    def test_a_direct_link_is_downloaded_by_its_own_name(self):
        job = self.run_import(f"{self.base}/files/benchy.stl")
        self.assertEqual(job["files"], ["imports/benchy.stl"])
        job = self.run_import(f"{self.base}/download?id=7")
        self.assertEqual(job["files"], ["imports/named.stl"])

    def test_a_web_page_is_refused_and_nothing_is_kept(self):
        job = self.run_import(f"{self.base}/page")
        self.assertEqual(job["state"], "failed")
        self.assertIn("web page", job["error"])
        self.assertFalse((self.lib / "imports").exists() and any((self.lib / "imports").iterdir()))

    def test_a_redirect_off_the_web_is_refused(self):
        job = self.run_import(f"{self.base}/to-file")
        self.assertEqual(job["state"], "failed")
        self.assertIn("not a web address", job["error"])

    def test_makerworld_and_thingiverse_say_where_it_does_work(self):
        for url, word in (("https://makerworld.com/en/models/22030", "Studio tab"),
                          ("https://bambulab.com/share/abc", "Studio tab"),
                          ("https://www.thingiverse.com/thing:763622", "Thingiverse")):
            with self.subTest(url=url):
                job = self.run_import(url)
                self.assertEqual(job["state"], "failed")
                self.assertIn(word, job["error"])

    def test_only_web_links(self):
        for url in ("file:///etc/passwd", "ftp://example.com/a.stl", "not a link"):
            with self.subTest(url=url):
                self.assertEqual(self.run_import(url)["state"], "failed")


class TestTheImportRoute(RouteTest):
    def test_the_route_runs_the_importer_as_a_job(self):
        def fake_run(job, url):
            job.update(state="done", files=["imports/a.stl"])
        with unittest.mock.patch.object(server.importer, "run", fake_run):
            status, body = self.call("POST", "/api/import", json={"url": "https://x/a.stl", "wait": 5})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["job"]["kind"], "import")
        self.assertEqual(body["job"]["files"], ["imports/a.stl"])

    def test_no_link_is_a_400(self):
        status, body = self.call("POST", "/api/import", json={})
        self.assertEqual(status, 400)
        self.assertIn("link", body["error"])


class TestColoursReachTheView(unittest.TestCase):
    def test_the_build_keeps_one_colour_per_real_body(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "bruh-bambu-studio" / "cad"))
        try:
            import build
        finally:
            sys.path.pop(0)
        parts_ = {"Base": object(), "Lid": object()}
        self.assertEqual(build._colours({"Base": "white", "Lid": "#FF0000", "Ghost": "red",
                                         "Bad": 3}, parts_), {"Base": "white", "Lid": "#FF0000"})
        self.assertIsNone(build._colours({"Base": "  "}, parts_))
        self.assertIsNone(build._colours(None, parts_))

    def test_brain_is_asked_for_colours_and_the_version_keeps_them(self):
        designer = server.designer
        self.assertIn("COLORS", designer.brief())
        self.assertIn("COLORS", (Path(server.__file__).parent.parent / "cad" / "example_part.py").read_text())
        source = Path(designer.__file__).read_text()
        self.assertIn('"colors": report.get("colors")', source)

    def test_the_view_paints_bodies_from_the_version(self):
        js = (Path(server.__file__).parent / "design.js").read_text()
        self.assertIn("v.colors", js)
        self.assertNotIn("const colors = {};", js)


if __name__ == "__main__":
    unittest.main()
