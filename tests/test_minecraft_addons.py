#!/usr/bin/env python3
"""The Minecraft add-on browser, against a real HTTP server speaking Modrinth.

The fake answers the three calls the browser makes (search, project,
versions) and serves the file, so what is under test is the wire — the
facets that decide what a server is offered, the version it picks, the
hash it checks — and not a mock that accepts whatever it is handed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, web

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "mc_addons", REPO / "bruh-minecraft-server" / "panel" / "addons.py")
addons = importlib.util.module_from_spec(spec)
sys.modules["mc_addons"] = addons
spec.loader.exec_module(addons)

JAR = b"PK\x03\x04 a plugin jar"
LIB = b"PK\x03\x04 a library jar"
PACK = b"PK\x03\x04 a data pack"


def sha(b: bytes) -> str:
    return hashlib.sha512(b).hexdigest()


class FakeModrinth:
    def __init__(self):
        self.searches = []
        self.bad_hash = False
        self.foreign_url = False

    def app(self, base):
        self.base = base
        app = web.Application()
        app.router.add_get("/v2/search", self.search)
        app.router.add_get("/v2/project/{id}", self.project)
        app.router.add_get("/v2/project/{id}/version", self.versions)
        app.router.add_get("/cdn/{name}", self.file)
        return app

    async def search(self, request):
        self.searches.append(dict(request.query))
        return web.json_response({"total_hits": 1, "hits": [{
            "project_id": "chairs01", "slug": "chairs", "title": "Chairs",
            "description": "Sit on stairs", "downloads": 5}]})

    PROJECTS = {
        "chairs01": {"id": "chairs01", "slug": "chairs", "title": "Chairs",
                     "project_type": "plugin"},
        "libby001": {"id": "libby001", "slug": "libby", "title": "Libby",
                     "project_type": "plugin"},
        "terra001": {"id": "terra001", "slug": "terralith", "title": "Terralith",
                     "project_type": "datapack"},
        "clientmod": {"id": "clientmod", "slug": "sodium", "title": "Sodium",
                      "project_type": "mod", "client_side": "required"},
    }

    async def project(self, request):
        p = self.PROJECTS.get(request.match_info["id"])
        if not p:
            return web.json_response({}, status=404)
        return web.json_response(p)

    def f(self, name, body):
        url = f"{self.base}/cdn/{name}"
        if self.foreign_url:
            url = "https://evil.example/" + name
        return {"url": url, "filename": name, "primary": True,
                "hashes": {"sha512": "0" * 128 if self.bad_hash else sha(body)}}

    async def versions(self, request):
        self.version_query = dict(request.query)
        pid = request.match_info["id"]
        if pid == "chairs01":
            return web.json_response([
                {"id": "v-beta", "version_number": "2.0-beta", "version_type": "beta",
                 "date_published": "2026-09-01", "loaders": ["paper"],
                 "game_versions": ["1.21.4"], "files": [self.f("chairs-2.jar", JAR)],
                 "dependencies": []},
                {"id": "v-rel", "version_number": "1.9", "version_type": "release",
                 "date_published": "2026-08-01", "loaders": ["paper"],
                 "game_versions": ["1.21.4"], "files": [self.f("chairs-1.9.jar", JAR)],
                 "dependencies": [{"project_id": "libby001", "dependency_type": "required"},
                                  {"project_id": "nope", "dependency_type": "optional"}]},
            ])
        if pid == "libby001":
            return web.json_response([
                {"id": "l1", "version_number": "1", "version_type": "release",
                 "date_published": "2026-01-01", "loaders": ["spigot"],
                 "game_versions": ["1.21.4"], "files": [self.f("libby.jar", LIB)]}])
        if pid == "terra001":
            return web.json_response([
                {"id": "t1", "version_number": "2.5", "version_type": "release",
                 "date_published": "2026-01-01", "loaders": ["datapack"],
                 "game_versions": ["1.21.4"], "files": [self.f("Terralith.zip", PACK)]}])
        return web.json_response([])

    async def file(self, request):
        name = request.match_info["name"]
        return web.Response(body={"chairs-1.9.jar": JAR, "libby.jar": LIB,
                                  "Terralith.zip": PACK}.get(name, b""))


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeModrinth()
        self.runner = None
        app = web.Application()
        self.runner = web.AppRunner(app)
        # Bind first to learn the port, then build the real app on it.
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        base = f"http://127.0.0.1:{port}"
        self.runner = web.AppRunner(self.fake.app(base))
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", port).start()
        self.api = base + "/v2"
        self._hosts = set(addons.DOWNLOAD_HOSTS)
        addons.DOWNLOAD_HOSTS.add("127.0.0.1")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ctx = addons.Context("paper", "1.21.4", root / "server", "world", root / "packs")
        self.session = ClientSession()
        self.client = addons.Modrinth(self.session, self.api)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        addons.DOWNLOAD_HOSTS.clear()
        addons.DOWNLOAD_HOSTS.update(self._hosts)
        self.tmp.cleanup()


class TestWhatIsOffered(unittest.TestCase):
    def test_the_server_decides_the_kinds(self):
        self.assertEqual(addons.kinds_for("paper"), ["plugin", "datapack", "resourcepack"])
        self.assertEqual(addons.kinds_for("fabric"), ["mod", "datapack", "resourcepack"])
        self.assertEqual(addons.kinds_for("vanilla"), ["datapack", "resourcepack"])

    def test_a_plugin_search_on_fabric_is_refused(self):
        with self.assertRaises(addons.AddonError):
            addons.search_params("plugin", "", "fabric", "1.21.4")

    def test_mods_are_server_side_only(self):
        facets = json.loads(addons.search_params("mod", "tree", "fabric", "")["facets"])
        self.assertIn(["client_side:optional", "client_side:unsupported"], facets)
        self.assertIn(["categories:fabric"], facets)
        self.assertNotIn("versions", json.dumps(facets))  # no version, no filter

    def test_game_version_prefers_the_exact_one(self):
        self.assertEqual(addons.game_version({"version": "1.21.4"}, {"version": "Paper 1.20"}), "1.21.4")
        self.assertEqual(addons.game_version({}, {"version": "Paper 26.1"}), "26.1")
        self.assertEqual(addons.game_version({}, {}), "")

    def test_a_release_beats_a_newer_beta(self):
        vs = [{"version_type": "beta", "date_published": "2", "loaders": ["paper"],
               "game_versions": ["1"], "files": [{"url": "u"}]},
              {"version_type": "release", "date_published": "1", "loaders": ["paper"],
               "game_versions": ["1"], "files": [{"url": "u"}], "id": "rel"}]
        self.assertEqual(addons.pick_version(vs, ["paper"], "1")["id"], "rel")
        self.assertIsNone(addons.pick_version(vs, ["fabric"], "1"))

    def test_unsafe_file_names_are_replaced(self):
        self.assertEqual(addons.safe_filename("../../evil.jar", "chairs", "plugin"), "evil.jar")
        self.assertEqual(addons.safe_filename("a b;c.jar", "chairs", "plugin"), "chairs.jar")
        self.assertEqual(addons.safe_filename("x.jar", "pack", "datapack"), "pack.zip")

    def test_a_datapack_cannot_climb_out_of_the_world(self):
        d = addons.destination("datapack", Path("/s"), "../../etc", Path("/p"))
        self.assertEqual(d, Path("/s/world/datapacks"))


class TestSearch(Base):
    async def test_search_sends_the_servers_facets(self):
        got = await addons.search(self.client, self.ctx, "plugin", "chair")
        facets = json.loads(self.fake.searches[0]["facets"])
        self.assertIn(["project_type:plugin"], facets)
        self.assertIn(["categories:paper", "categories:spigot", "categories:bukkit"], facets)
        self.assertIn(["versions:1.21.4"], facets)
        self.assertEqual(got["hits"][0]["title"], "Chairs")
        self.assertIn("iPad", got["hits"][0]["reach"])


class TestInstall(Base):
    async def test_install_brings_its_required_library_and_records_both(self):
        rows = await addons.install(self.client, self.ctx, "chairs01", "plugin")
        self.assertEqual([r["title"] for r in rows], ["Libby", "Chairs"])
        plugins = self.ctx.server_dir / "plugins"
        self.assertEqual((plugins / "chairs-1.9.jar").read_bytes(), JAR)
        self.assertEqual((plugins / "libby.jar").read_bytes(), LIB)
        listed = {r["title"]: r for r in addons.installed(self.ctx)}
        self.assertEqual(listed["Libby"]["required_by"], "Chairs")
        self.assertEqual(listed["Libby"]["needed_by"], ["Chairs"])
        self.assertEqual(listed["Chairs"]["version"], "1.9")  # the release, not the beta
        # Removing the library something still needs is refused.
        with self.assertRaises(addons.AddonError):
            addons.remove(self.ctx, "libby001")
        addons.remove(self.ctx, "chairs01")
        addons.remove(self.ctx, "libby001")
        self.assertEqual(list(plugins.glob("*.jar")), [])

    async def test_a_hash_mismatch_writes_nothing(self):
        self.fake.bad_hash = True
        with self.assertRaises(addons.AddonError):
            await addons.install(self.client, self.ctx, "terra001", "datapack")
        dp = self.ctx.server_dir / "world" / "datapacks"
        self.assertEqual([p for p in dp.iterdir()] if dp.exists() else [], [])
        self.assertEqual(addons.installed(self.ctx), [])

    async def test_a_download_off_modrinths_cdn_is_not_fetched(self):
        self.fake.foreign_url = True
        with self.assertRaises(addons.AddonError) as ctx:
            await addons.install(self.client, self.ctx, "terra001", "datapack")
        self.assertIn("CDN", str(ctx.exception))

    async def test_a_datapack_lands_in_the_worlds_datapacks(self):
        await addons.install(self.client, self.ctx, "terra001", "datapack")
        self.assertEqual(
            (self.ctx.server_dir / "world" / "datapacks" / "Terralith.zip").read_bytes(), PACK)

    async def test_a_kind_that_does_not_match_the_project_is_refused(self):
        with self.assertRaises(addons.AddonError):
            await addons.install(self.client, self.ctx, "terra001", "plugin")

    async def test_a_mod_every_client_must_have_is_refused(self):
        ctx = addons.Context("fabric", "1.21.4", self.ctx.server_dir, "world", self.ctx.packs_dir)
        with self.assertRaises(addons.AddonError) as err:
            await addons.install(self.client, ctx, "clientmod", "mod")
        self.assertIn("iPad", str(err.exception))


if __name__ == "__main__":
    unittest.main()
