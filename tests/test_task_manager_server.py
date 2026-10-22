"""BRUH Task Manager's routes, driven over HTTP against a fake Supervisor.

The Supervisor is a real aiohttp server speaking its own envelope
(tests/task_manager_fake.py), because what the panel gets wrong talking to it
is shape: a one-shot stats answer with no cpu_percent, an options write that
must carry every option, a restart that takes minutes.
"""
import asyncio
import os
import shutil
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import task_manager_env

server, apps, settings, procs, ending = task_manager_env.load(
    "server", "apps", "settings", "procs", "ending")
fake_mod = task_manager_env.fake()


class PanelCase(unittest.IsolatedAsyncioTestCase):
    PROTECTED = False
    OPTIONS = {"process_view": True, "allow_ending_processes": True}

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        if self.PROTECTED:
            procs_, mounts = fake_mod.private_namespace()
            self.fake = fake_mod.FakeProc(os.path.join(self.dir, "proc"), procs_, mounts)
            self_pid = 40
        else:
            self.fake = fake_mod.FakeProc(os.path.join(self.dir, "proc"))
            self_pid = 901
        self.sup = fake_mod.FakeSupervisor(protected=self.PROTECTED, options=dict(self.OPTIONS))
        self.sup_server = TestServer(self.sup.app())
        await self.sup_server.start_server()
        self.supervisor = apps.Supervisor(str(self.sup_server.make_url("")).rstrip("/"), token="t")
        sampler = procs.ProcessSampler(self.fake.root, self_pid=self_pid, hz=100, ncpu=4)
        self.killed = []

        def kill(pid, sig):
            self.killed.append((pid, sig))
            self.fake.end(pid)

        self.shared = os.path.join(self.dir, "config", ".bruh_task_manager")
        os.makedirs(os.path.dirname(self.shared))
        self.monitor = server.Monitor(
            self.supervisor, proc_root=self.fake.root, shared=self.shared,
            options=settings.Options(self.supervisor, path="/nonexistent"),
            process_sampler=sampler, ender=ending.Ender(sampler, kill=kill))
        app = server.build_app(self.monitor)
        app.on_startup.clear()  # the tests drive tick() themselves
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        await self.monitor.tick()
        self.fake.advance(2.0)
        await self.monitor.tick()

    async def asyncTearDown(self):
        await self.client.close()
        await self.supervisor.close()
        await self.sup_server.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def snapshot(self, processes=False):
        resp = await self.client.get("/api/snapshot" + ("?processes=1" if processes else ""))
        self.assertEqual(200, resp.status)
        return await resp.json()


class TestLevelTwo(PanelCase):
    async def test_every_app_is_measured_with_cpu_from_the_counters(self):
        snap = await self.snapshot()
        rows = {a["key"]: a for a in snap["apps"]}
        self.assertIn("core", rows)
        self.assertIn("addon:core_samba", rows)
        self.assertIsNone(rows["addon:core_samba"]["cpu"], "a stopped app is not 0%")
        self.assertEqual(["start"], rows["addon:core_samba"]["actions"])
        # The fake works the Studio Code Server at ~92%; one-shot answers
        # carry no cpu_percent, so this is the panel's own arithmetic.
        self.assertGreater(rows["addon:a0d7b954_vscode"]["cpu"], 70)
        self.assertEqual("addon:a0d7b954_vscode", snap["apps"][0]["key"])
        self.assertEqual([], rows["addon:local_bruh-task-manager"]["actions"])
        self.assertEqual(["restart"], rows["core"]["actions"])

    async def test_level_two_is_active_and_lists_processes_with_verdicts(self):
        snap = await self.snapshot(processes=True)
        self.assertTrue(snap["level2"]["active"])
        groups = {g["key"]: g for g in snap["processes"]["groups"]}
        self.assertEqual("Studio Code Server", groups["addon:a0d7b954_vscode"]["name"])
        host = {p["pid"]: p for p in groups["addon:a0d7b954_vscode"]["procs"]}
        self.assertTrue(host[602]["can_end"])
        self.assertFalse(host[600]["can_end"])
        self.assertFalse(any(p["can_end"] for p in groups["core"]["procs"]))
        self.assertIn("addon:a0d7b954_vscode", snap["process_keys"])

    async def test_processes_are_left_out_unless_asked_for(self):
        self.assertNotIn("processes", await self.snapshot())

    async def test_end_process_route_re_asks_policy(self):
        start = procs.read_proc(self.fake.root, 401).start
        resp = await self.client.post("/api/process/401/end", json={"start": start})
        self.assertEqual(409, resp.status)
        self.assertEqual([], self.killed)
        start = procs.read_proc(self.fake.root, 602).start
        resp = await self.client.post("/api/process/602/end", json={"start": start})
        body = await resp.json()
        self.assertEqual("ended", body["outcome"], body)
        resp = await self.client.post("/api/process/1/end", json={"start": 0})
        self.assertEqual(409, resp.status)

    async def test_a_restart_is_a_job_and_names_its_consequence_first(self):
        resp = await self.client.get("/api/app/addon:core_mosquitto/impact?action=stop")
        lines = (await resp.json())["lines"]
        self.assertTrue(any("mqtt" in line for line in lines), lines)
        self.assertTrue(any("watchdog" in line for line in lines), lines)
        self.sup.action_delay = 0.2
        resp = await self.client.post("/api/app/addon:core_mosquitto/restart")
        job = await resp.json()
        self.assertEqual("running", job["status"])
        for _ in range(50):
            await asyncio.sleep(0.05)
            job = await (await self.client.get(f"/api/job/{job['id']}")).json()
            if job["status"] != "running":
                break
        self.assertEqual("done", job["status"])
        self.assertIn("/addons/core_mosquitto/restart", self.sup.posts)

    async def test_actions_not_offered_are_refused(self):
        for path in ("/api/app/core/stop", "/api/app/addon:local_bruh-task-manager/restart",
                     "/api/app/addon:nope/restart", "/api/app/core/delete"):
            with self.subTest(path=path):
                resp = await self.client.post(path)
                self.assertEqual(404, resp.status)

    async def test_the_mirror_home_assistant_reads(self):
        import json
        with open(os.path.join(self.shared, "state.json")) as handle:
            mirror = json.load(handle)
        self.assertEqual("Studio Code Server", mirror["busiest"]["name"])
        self.assertNotIn("addon:local_bruh-task-manager", [t["key"] for t in mirror["top"]])
        self.assertEqual(2, mirror["level"])
        self.assertGreaterEqual(mirror["stale_after_s"], 60)

    async def test_static_files_are_bound_to_their_routes_under_a_prefix(self):
        # Mounted under a prefix (ingress-shaped), app.js must still be JS.
        inner = server.build_app(self.monitor)
        inner.on_startup.clear()
        outer = web.Application()
        outer.add_subapp("/api/hassio_ingress/abc", inner)
        client = TestClient(TestServer(outer))
        await client.start_server()
        try:
            resp = await client.get("/api/hassio_ingress/abc/app.js")
            self.assertEqual("application/javascript", resp.content_type)
            self.assertNotIn("<!doctype", (await resp.text())[:50].lower())
            page = await (await client.get("/api/hassio_ingress/abc/")).text()
            self.assertIn('href="style.css"', page)
            self.assertNotIn('href="/style.css"', page)
            self.assertNotIn('src="/', page)
        finally:
            await client.close()


class TestLevelOne(PanelCase):
    PROTECTED = True
    OPTIONS = {"process_view": False}

    async def test_level_one_reads_no_processes(self):
        snap = await self.snapshot(processes=True)
        self.assertEqual("off", snap["level2"]["state"])
        self.assertIsNone(snap["processes"])
        self.assertEqual([], snap["process_keys"])

    async def test_switching_level_two_on_writes_through_and_names_the_next_step(self):
        resp = await self.client.post("/api/settings", json={"process_view": True,
                                                             "log_level": "debug"})
        self.assertEqual(200, resp.status)
        self.assertTrue(self.sup.options["process_view"])
        self.assertNotEqual("debug", self.sup.options.get("log_level"),
                            "only the editable keys may be written from the panel")
        self.assertIn("runaway_minutes", self.sup.options, "the whole option set is sent")
        await self.monitor.tick()
        snap = await self.snapshot(processes=True)
        self.assertEqual("needs_protection_off", snap["level2"]["state"])
        self.assertEqual({"option": True, "protection_off": False, "visible": False},
                         snap["level2"]["steps"])
        self.assertIsNone(snap["processes"])

    async def test_a_refused_write_says_so(self):
        self.sup.refuse_options = True
        resp = await self.client.post("/api/settings", json={"process_view": True})
        self.assertEqual(409, resp.status)
        self.assertIn("refused", (await resp.json())["error"])

    async def test_ending_is_refused_at_level_one(self):
        start = procs.read_proc(self.fake.root, 40).start
        resp = await self.client.post("/api/process/40/end", json={"start": start})
        self.assertEqual(409, resp.status)
        self.assertEqual([], self.killed)

    async def test_nonsense_settings_are_clamped_or_refused(self):
        resp = await self.client.post("/api/settings", json={"runaway_cpu_percent": 5000})
        self.assertEqual(200, resp.status)
        self.assertEqual(100, self.sup.options["runaway_cpu_percent"])
        resp = await self.client.post("/api/settings", json={"nothing": 1})
        self.assertEqual(400, resp.status)


class TestLevelTwoSentences(unittest.TestCase):
    def test_each_combination_names_the_missing_step(self):
        cases = {
            (True, False, True): "active",
            (True, True, False): "needs_protection_off",
            (True, False, False): "needs_restart",
            (True, None, False): "unknown",
            (False, False, True): "exposed",
            (False, True, False): "off",
        }
        for args, state in cases.items():
            with self.subTest(args=args):
                status = settings.level2_status(*args)
                self.assertEqual(state, status["state"])
                self.assertEqual(state == "active", status["active"])
                self.assertTrue(status["sentence"])


class TestTheRealServerStarts(unittest.IsolatedAsyncioTestCase):
    async def test_the_access_logger_is_one_aiohttp_accepts(self):
        # run_app type-checks access_log_class; constructing the class by hand
        # in a test proves nothing (BRUH Print 0.1.0 shipped exactly that).
        app = web.Application()
        runner = web.AppRunner(app, access_log_class=server.QuietAccessLogger)
        await runner.setup()
        await runner.cleanup()


if __name__ == "__main__":
    unittest.main()
