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
import os
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

    # The shapes Modrinth's /project really answers (read off the live API):
    # a plugin is `project_type: "mod"` with paper/spigot loaders, and a
    # project shipping as a mod AND a data pack (VeinMiner) is also "mod",
    # with `datapack` among its loaders. Only `loaders` says what it is.
    PROJECTS = {
        "chairs01": {"id": "chairs01", "slug": "chairs", "title": "Chairs",
                     "project_type": "mod", "loaders": ["paper", "spigot"]},
        "libby001": {"id": "libby001", "slug": "libby", "title": "Libby",
                     "project_type": "mod", "loaders": ["spigot"]},
        "terra001": {"id": "terra001", "slug": "terralith", "title": "Terralith",
                     "project_type": "datapack", "loaders": ["datapack"]},
        "OhduvhIc": {"id": "OhduvhIc", "slug": "veinminer", "title": "VeinMiner",
                     "project_type": "mod", "client_side": "optional",
                     "loaders": ["bukkit", "datapack", "fabric", "folia", "forge",
                                 "neoforge", "paper", "purpur", "quilt", "spigot"]},
        "clientmod": {"id": "clientmod", "slug": "sodium", "title": "Sodium",
                      "project_type": "mod", "client_side": "required",
                      "loaders": ["fabric"]},
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
        if pid == "OhduvhIc":
            return web.json_response([
                {"id": "vm-dp", "version_number": "1.3.3", "version_type": "release",
                 "date_published": "2026-01-01", "loaders": ["datapack"],
                 "game_versions": ["1.21.4"], "files": [self.f("veinminer-1.3.3.zip", PACK)]},
                {"id": "vm-paper", "version_number": "2.1", "version_type": "release",
                 "date_published": "2026-02-01", "loaders": ["paper"],
                 "game_versions": ["1.21.4"], "files": [self.f("veinminer-2.1.jar", JAR)]},
            ])
        return web.json_response([])

    async def file(self, request):
        name = request.match_info["name"]
        return web.Response(body={"chairs-1.9.jar": JAR, "libby.jar": LIB,
                                  "Terralith.zip": PACK,
                                  "veinminer-1.3.3.zip": PACK,
                                  "veinminer-2.1.jar": JAR}.get(name, b""))


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

    async def test_a_project_that_is_also_a_mod_installs_as_a_datapack(self):
        # VeinMiner: Modrinth answers project_type "mod"; it is a data pack
        # too, and the browser offered it under Data packs.
        rows = await addons.install(self.client, self.ctx, "OhduvhIc", "datapack")
        self.assertEqual(rows[-1]["file"], "veinminer-1.3.3.zip")
        self.assertEqual(
            (self.ctx.server_dir / "world" / "datapacks" / "veinminer-1.3.3.zip").read_bytes(),
            PACK)

    async def test_the_same_project_installs_as_a_plugin(self):
        rows = await addons.install(self.client, self.ctx, "OhduvhIc", "plugin")
        self.assertEqual(rows[-1]["file"], "veinminer-2.1.jar")

    def test_published_as_reads_loaders_not_the_type_field(self):
        p = FakeModrinth.PROJECTS
        self.assertTrue(addons.published_as(p["OhduvhIc"], "datapack"))
        self.assertTrue(addons.published_as(p["chairs01"], "plugin"))
        self.assertFalse(addons.published_as(p["terra001"], "plugin"))
        self.assertFalse(addons.published_as(p["chairs01"], "datapack"))
        self.assertTrue(addons.published_as(
            {"project_type": "resourcepack", "loaders": ["minecraft"]}, "resourcepack"))

    async def test_a_batch_installs_each_and_reports_each(self):
        results = await addons.install_many(self.client, self.ctx, [
            {"id": "terra001", "kind": "datapack"},
            {"id": "OhduvhIc", "kind": "datapack"},
            {"id": "terra001", "kind": "plugin"},       # refused, the rest still land
            {"id": "terra001", "kind": "datapack"},     # a duplicate is asked once
        ])
        self.assertEqual([(r["id"], r["ok"]) for r in results],
                         [("terra001", True), ("OhduvhIc", True), ("terra001", False)])
        self.assertIn("plugin", results[2]["error"])
        dp = self.ctx.server_dir / "world" / "datapacks"
        self.assertEqual(sorted(p.name for p in dp.iterdir()),
                         ["Terralith.zip", "veinminer-1.3.3.zip"])
        self.assertEqual(sorted(r["title"] for r in addons.installed(self.ctx)),
                         ["Terralith", "VeinMiner"])

    async def test_an_empty_or_huge_batch_is_refused(self):
        with self.assertRaises(addons.AddonError):
            await addons.install_many(self.client, self.ctx, [])
        with self.assertRaises(addons.AddonError):
            await addons.install_many(self.client, self.ctx,
                                      [{"id": f"p{i:04d}", "kind": "datapack"}
                                       for i in range(addons.MAX_BATCH + 1)])

    async def test_a_mod_every_client_must_have_is_refused(self):
        ctx = addons.Context("fabric", "1.21.4", self.ctx.server_dir, "world", self.ctx.packs_dir)
        with self.assertRaises(addons.AddonError) as err:
            await addons.install(self.client, ctx, "clientmod", "mod")
        self.assertIn("iPad", str(err.exception))



class TestTheWholeWorldOnOneList(Base):
    """Everything in the world, browser-added or not, with whether it is on."""

    async def test_every_folder_is_listed_with_its_status(self):
        await addons.install(self.client, self.ctx, "terra001", "datapack")
        plugins = self.ctx.server_dir / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        old = plugins / "Essentials.jar"
        import zipfile
        with zipfile.ZipFile(old, "w") as zf:
            zf.writestr("plugin.yml", "name: EssentialsX\nversion: '2.21.0'\nmain: x\n")
        (plugins / "Geyser-Spigot.jar").write_bytes(JAR)
        os.utime(old, (1000, 1000))
        os.utime(plugins / "Geyser-Spigot.jar", (1000, 1000))
        await addons.install(self.client, self.ctx, "chairs01", "plugin")
        (self.ctx.server_dir / "world" / "datapacks" / "bukkit").mkdir()
        self.ctx.packs_dir.mkdir(parents=True, exist_ok=True)
        (self.ctx.packs_dir / "Faithful.zip").write_bytes(PACK)

        got = addons.world_contents(self.ctx, running=True, started_at=5000,
                                    active_pack="", changes=[])
        by = {it["file"]: it for it in got["items"]}
        # By hand, and loaded before the launch: working.
        self.assertEqual(by["Essentials.jar"]["source"], "manual")
        # A jar added by hand is named by what it declares about itself.
        self.assertEqual((by["Essentials.jar"]["title"], by["Essentials.jar"]["version"]),
                         ("EssentialsX", "2.21.0"))
        self.assertEqual(by["Essentials.jar"]["status"], "active")
        # Added since the launch: waiting on a restart, and the list says so.
        self.assertEqual(by["chairs-1.9.jar"]["status"], "restart")
        self.assertEqual(by["chairs-1.9.jar"]["title"], "Chairs")
        self.assertTrue(got["restart_needed"])
        # Crossplay plugins are listed under Server software, not here.
        self.assertNotIn("Geyser-Spigot.jar", by)
        self.assertEqual([c["title"] for c in addons.components(self.ctx.server_dir)], ["Geyser"])
        # Data packs reload live; the server's own folder is not one of ours.
        self.assertEqual(by["Terralith.zip"]["status"], "active")
        self.assertNotIn("bukkit", by)
        # A pack in the library that this world does not offer.
        self.assertEqual(by["Faithful.zip"]["status"], "unused")

    async def test_a_stopped_server_needs_no_restart(self):
        await addons.install(self.client, self.ctx, "chairs01", "plugin")
        got = addons.world_contents(self.ctx, running=False, started_at=None,
                                    active_pack="", changes=[])
        self.assertFalse(got["restart_needed"])
        self.assertEqual({it["status"] for it in got["items"]}, {"next_start"})

    async def test_the_active_pack_waits_on_a_restart_after_a_switch(self):
        self.ctx.packs_dir.mkdir(parents=True, exist_ok=True)
        (self.ctx.packs_dir / "Faithful.zip").write_bytes(PACK)
        change = [{"action": "switched to", "kind": "resourcepack", "title": "Faithful", "at": 9}]
        got = addons.world_contents(self.ctx, running=True, started_at=5,
                                    active_pack="Faithful.zip", changes=change)
        self.assertEqual(got["items"][0]["status"], "restart")
        quiet = addons.world_contents(self.ctx, running=True, started_at=5,
                                      active_pack="Faithful.zip", changes=[])
        self.assertEqual(quiet["items"][0]["status"], "active")

    async def test_one_search_covers_every_kind(self):
        got = await addons.search_all(self.client, self.ctx, "chairs")
        self.assertEqual(len(self.fake.searches), len(addons.kinds_for("paper")))
        kinds = {json.loads(q["facets"])[0][0] for q in self.fake.searches}
        self.assertEqual(kinds, {"project_type:plugin", "project_type:datapack",
                                 "project_type:resourcepack"})
        # Round-robin: one from each kind before the second of any.
        self.assertEqual([h["kind"] for h in got["hits"]],
                         ["plugin", "datapack", "resourcepack"])

if __name__ == "__main__":
    unittest.main()
