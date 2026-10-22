#!/usr/bin/env python3
"""BRUH Task Manager's real panel against a fake Supervisor and a fake /proc.

    python3 tests/manual/task_manager_demo_panel.py /tmp/tm-demo [port] [--level2] [--protected]

Serves the panel exactly the way `server.main()` does (QuietAccessLogger and
all) on `port` (default 18103), with the Supervisor at a local fake and /proc
at a generated Home Assistant OS machine whose counters move every second.
End process never signals a real process: the demo's `kill` removes the fake
one (the Studio Code Server extension host ignores the first ask, so Force
end can be seen).
"""
import asyncio
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "bruh-task-manager", "panel"))

from aiohttp import web  # noqa: E402

import apps as apps_mod  # noqa: E402
import procs  # noqa: E402
import server  # noqa: E402
import settings as settings_mod  # noqa: E402
from ending import Ender  # noqa: E402
from task_manager_fake import FakeProc, FakeSupervisor, private_namespace  # noqa: E402

STUBBORN = {602}
PREFIX = os.environ.get("DEMO_PREFIX", "/api/hassio_ingress/tmDemoToken01")


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "/tmp/tm-demo"
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 18103
    level2 = "--level2" in sys.argv
    protected = "--protected" in sys.argv or not level2
    # With Protection mode on the container sees only itself, whatever the
    # option says; the fake has to look like that, or the page would be
    # shown a Level 2 the Supervisor would never have granted.
    if protected:
        procs_, mounts_ = private_namespace()
        fake = FakeProc(os.path.join(workdir, "proc"), procs_, mounts_)
        self_pid = 40
    else:
        fake = FakeProc(os.path.join(workdir, "proc"))
        self_pid = 901
    fake.advance(1.0)

    def tick():
        while True:
            time.sleep(1.0)
            fake.advance(1.0)

    threading.Thread(target=tick, daemon=True).start()
    sup = FakeSupervisor(protected=protected,
                         options={"process_view": level2, "allow_ending_processes": level2,
                                  "sample_seconds": 2, "protected_processes": ["mosquitto"]})

    asked = set()

    def fake_kill(pid, sig):
        if pid in STUBBORN and sig == signal.SIGTERM and pid not in asked:
            asked.add(pid)
            return
        fake.end(pid)

    async def boot():
        runner = web.AppRunner(sup.app())
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port + 1).start()
        supervisor = apps_mod.Supervisor(f"http://127.0.0.1:{port + 1}", token="demo")
        sampler = procs.ProcessSampler(fake.root, self_pid=self_pid, hz=100, ncpu=4)
        monitor = server.Monitor(supervisor, proc_root=fake.root, shared=None,
                                 options=settings_mod.Options(supervisor, path="/nonexistent"),
                                 process_sampler=sampler,
                                 ender=Ender(sampler, kill=fake_kill))
        app = server.build_app(monitor)
        # Mounted under an ingress-shaped prefix as well as at the root: a
        # page that only works at "/" is a page whose absolute URLs nobody
        # has caught yet.
        outer = web.Application()
        outer.add_subapp(PREFIX, app)
        outer[server.MONITOR] = monitor
        for route in ("/api/health", "/api/snapshot"):
            outer.router.add_get(route, {"/api/health": server.h_health,
                                         "/api/snapshot": server.h_snapshot}[route])
        runner2 = web.AppRunner(outer, access_log_class=server.QuietAccessLogger)
        await runner2.setup()
        await web.TCPSite(runner2, "127.0.0.1", port).start()
        print(f"demo panel on http://127.0.0.1:{port}{PREFIX}/", flush=True)
        while True:
            await asyncio.sleep(3600)

    asyncio.run(boot())


if __name__ == "__main__":
    main()
