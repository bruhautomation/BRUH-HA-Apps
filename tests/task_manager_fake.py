"""A Home Assistant OS machine on disk, for BRUH Task Manager's tests and demo.

Two halves, both copied from what the real thing writes rather than from
what the code expects:

* `FakeProc` builds a /proc tree: kernel threads (flag PF_KTHREAD), systemd
  and dockerd in the host's cgroups, and containers whose processes carry a
  `0::/system.slice/docker-<id>.scope` cgroup line and a `mountinfo` whose
  /data or /config root is the host path the Supervisor binds
  (`/supervisor/addons/data/<slug>`, `/supervisor`, `/supervisor/homeassistant`).
  `stat` is written in the kernel's field order, comm in parentheses and
  all, so the parser is tested against the real layout.
* `FakeSupervisor` answers the routes the panel calls, in the Supervisor's
  `{"result": "ok", "data": …}` envelope, with cumulative CPU counters that
  grow between calls the way Docker's do.
"""
from __future__ import annotations

import os
import random
import shutil

from aiohttp import web

PF_KTHREAD = 0x00200000
HZ = 100


def cid(n: int) -> str:
    return f"{n:064x}"


def stat_line(pid, comm, state, ppid, flags, ticks, threads, start):
    fields = [str(pid), f"({comm})", state, str(ppid), "0", "0", "0", "-1",
              str(flags), "0", "0", "0", "0",
              str(ticks), "0",  # utime, stime
              "0", "0", "20", "0", str(threads), "0", str(start)]
    fields += ["0"] * 30
    return " ".join(fields) + "\n"


def mountinfo_for(data_root=None, config_root=None) -> str:
    lines = ["600 590 0:200 / / rw,relatime - overlay overlay rw"]
    if data_root:
        lines.append(f"610 600 179:8 {data_root} /data rw,relatime - ext4 /dev/mmcblk0p8 rw")
    if config_root:
        lines.append(f"611 600 179:8 {config_root} /config rw,relatime - ext4 /dev/mmcblk0p8 rw")
    return "\n".join(lines) + "\n"


# (pid, ppid, comm, cmdline, container, ns_pid, rss_kb, cpu_weight)
SELF_CONTAINER = 9


def house():
    """The processes of a small, ordinary HAOS install."""
    procs = [
        (2, 0, "kthreadd", "", "kernel", None, None, 0),
        (12, 2, "ksoftirqd/0", "", "kernel", None, None, 1),
        (1, 0, "systemd", "/sbin/init", "os:init.scope", None, 9000, 0),
        (210, 1, "dockerd", "/usr/bin/dockerd -H fd://", "os:docker.service", None, 72000, 2),
        (220, 1, "NetworkManager", "/usr/sbin/NetworkManager --no-daemon", "os:NetworkManager.service", None, 14000, 0),
        (300, 210, "python3", "python3 -m supervisor", 1, 1, 160000, 3),
        (400, 210, "s6-svscan", "/package/admin/s6/command/s6-svscan -d4 -- /run/service", 2, 1, 900, 0),
        (401, 400, "python3", "python3 -m homeassistant --config /config", 2, 30, 620000, 25),
        (402, 401, "ffmpeg", "ffmpeg -rtsp_transport tcp -i rtsp://camera/stream -f mpegts -", 2, 41, 52000, 18),
        (500, 210, "s6-svscan", "/package/admin/s6/command/s6-svscan -d4 -- /run/service", 3, 1, 900, 0),
        (501, 500, "s6-supervise", "s6-supervise mosquitto", 3, 18, 700, 0),
        (502, 501, "mosquitto", "mosquitto -c /etc/mosquitto/mosquitto.conf", 3, 19, 6000, 1),
        (600, 210, "s6-svscan", "/package/admin/s6/command/s6-svscan -d4 -- /run/service", 4, 1, 900, 0),
        (601, 600, "node", "node /usr/local/lib/code-server/out/node/entry.js", 4, 20, 410000, 6),
        (602, 601, "node", "node /usr/local/lib/code-server/lib/vscode/out/bootstrap-fork --type=extensionHost", 4, 22, 880000, 90),
        (700, 210, "coredns", "coredns -conf /config/corefile", 5, 1, 21000, 0),
        (900, 210, "s6-svscan", "/package/admin/s6/command/s6-svscan -d4 -- /run/service", SELF_CONTAINER, 1, 900, 0),
        (901, 900, "python3", "python3 -u /opt/bruh-task-manager/panel/server.py", SELF_CONTAINER, 40, 38000, 1),
        (950, 210, "mystery", "/usr/bin/mystery --serve", 7, 1, 3000, 0),
    ]
    mounts = {
        1: mountinfo_for(data_root="/supervisor"),
        2: mountinfo_for(config_root="/supervisor/homeassistant"),
        3: mountinfo_for(data_root="/supervisor/addons/data/core_mosquitto",
                         config_root="/supervisor/homeassistant"),
        4: mountinfo_for(data_root="/supervisor/addons/data/a0d7b954_vscode",
                         config_root="/supervisor/homeassistant"),
        5: mountinfo_for(),
        SELF_CONTAINER: mountinfo_for(data_root="/supervisor/addons/data/local_bruh-task-manager",
                                      config_root="/supervisor/homeassistant"),
        7: mountinfo_for(),
    }
    return procs, mounts


def private_namespace():
    """What the same add-on sees with Protection mode ON: only itself.

    Its own PID namespace (its init is pid 1, no kernel threads, no pid 2
    that is kthreadd) and its own cgroup namespace (its cgroup reads "/").
    """
    procs = [
        (1, 0, "s6-svscan", "/package/admin/s6/command/s6-svscan -d4 -- /run/service", "self", 1, 900, 0),
        (40, 1, "python3", "python3 -u /opt/bruh-task-manager/panel/server.py", "self", 40, 38000, 1),
    ]
    return procs, {}


def _put(path: str, data) -> None:
    """Write beside and rename: real /proc never shows a half-written file,
    and the demo rewrites these every second while the panel reads them."""
    scratch = f"{path}.{os.getpid()}.tmp"
    with open(scratch, "wb" if isinstance(data, bytes) else "w") as handle:
        handle.write(data)
    os.replace(scratch, path)


class FakeProc:
    def __init__(self, root: str, procs=None, mounts=None, ncpu: int = 4) -> None:
        self.root = root
        default_procs, default_mounts = house()
        self.procs = list(procs if procs is not None else default_procs)
        self.mounts = dict(mounts if mounts is not None else default_mounts)
        self.ncpu = ncpu
        self.ticks = {p[0]: 1000 for p in self.procs}
        self.cpu_total = [100000, 200000]  # busy, idle
        self.gone: set[int] = set()
        self.write()

    @staticmethod
    def cgroup_of(container) -> str:
        if container in ("kernel", "self"):
            return "0::/\n"
        if isinstance(container, str) and container.startswith("os:"):
            return f"0::/system.slice/{container[3:]}\n"
        return f"0::/system.slice/docker-{cid(container)}.scope\n"

    def advance(self, seconds: float, jitter: bool = True) -> None:
        busy = 0
        for p in self.procs:
            weight = p[7]
            add = int(weight * seconds * HZ / 100 * (random.uniform(0.6, 1.4) if jitter else 1))
            self.ticks[p[0]] += add
            busy += add
        self.cpu_total[0] += busy
        self.cpu_total[1] += max(int(seconds * HZ * self.ncpu) - busy, 0)
        self.write()

    def end(self, pid: int) -> None:
        self.gone.add(pid)
        shutil.rmtree(os.path.join(self.root, str(pid)), ignore_errors=True)

    def write(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        for pid, ppid, comm, cmd, container, ns_pid, rss, _w in self.procs:
            if pid in self.gone:
                continue
            base = os.path.join(self.root, str(pid))
            os.makedirs(base, exist_ok=True)
            kernel = container == "kernel"
            _put(os.path.join(base, "stat"),
                 stat_line(pid, comm, "S", ppid, PF_KTHREAD if kernel else 0x400100,
                           self.ticks[pid], 1 if kernel else 4, 500 + pid))
            _put(os.path.join(base, "cmdline"), cmd.replace(" ", "\0").encode() + (b"\0" if cmd else b""))
            _put(os.path.join(base, "cgroup"), self.cgroup_of(container))
            status = [f"Name:\t{comm}", "State:\tS (sleeping)", f"PPid:\t{ppid}",
                      "Uid:\t0\t0\t0\t0"]
            if ns_pid is not None:
                status.append(f"NSpid:\t{pid}\t{ns_pid}")
            else:
                status.append(f"NSpid:\t{pid}")
            if rss is not None:
                status.append(f"VmRSS:\t   {rss} kB")
            _put(os.path.join(base, "status"), "\n".join(status) + "\n")
            if isinstance(container, int):
                _put(os.path.join(base, "mountinfo"), self.mounts.get(container, mountinfo_for()))
            else:
                _put(os.path.join(base, "mountinfo"), mountinfo_for())
        busy, idle = self.cpu_total
        _put(os.path.join(self.root, "stat"), f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\n")
        _put(os.path.join(self.root, "meminfo"),
             "MemTotal:        3900000 kB\nMemFree:          400000 kB\n"
             "MemAvailable:    1500000 kB\nSwapTotal:             0 kB\n")
        _put(os.path.join(self.root, "loadavg"), "1.42 1.10 0.95 2/412 9999\n")
        _put(os.path.join(self.root, "uptime"), "392811.33 1200000.00\n")


ADDONS = [
    {"slug": "core_mosquitto", "name": "Mosquitto broker", "state": "started", "version": "6.4.1"},
    {"slug": "a0d7b954_vscode", "name": "Studio Code Server", "state": "started", "version": "5.18.0"},
    {"slug": "local_bruh-task-manager", "name": "BRUH Task Manager", "state": "started", "version": "0.1.0"},
    {"slug": "core_samba", "name": "Samba share", "state": "stopped", "version": "12.3.2"},
]

# How hard each container works, as a share of the whole machine.
LOAD = {"core": 9.0, "supervisor": 1.2, "dns": 0.1, "audio": 0.0, "multicast": 0.0,
        "observer": 0.0, "cli": 0.0, "core_mosquitto": 0.4, "a0d7b954_vscode": 92.0,
        "local_bruh-task-manager": 0.5}
MEMORY = {"core": 640e6, "supervisor": 170e6, "dns": 22e6, "audio": 12e6, "multicast": 3e6,
          "observer": 9e6, "cli": 4e6, "core_mosquitto": 7e6, "a0d7b954_vscode": 1.3e9,
          "local_bruh-task-manager": 40e6}


class FakeSupervisor:
    def __init__(self, *, protected: bool = True, options=None) -> None:
        self.protected = protected
        self.options = dict(options or {})
        self.counters: dict[str, list] = {}
        self.posts: list[str] = []
        self.addons = [dict(a) for a in ADDONS]
        self.action_delay = 0.0
        self.refuse_options = False

    def _ok(self, data=None):
        return web.json_response({"result": "ok", "data": data or {}})

    def _stats(self, name: str):
        load = LOAD.get(name, 0.0)
        c = self.counters.setdefault(name, [0, 0, 0, 0, 0, 0])
        c[1] += 10_000_000_000  # system usage grows with wall time
        c[0] += int(10_000_000_000 * load / 100 * random.uniform(0.9, 1.1))
        c[2] += random.randint(1000, 90000)
        c[3] += random.randint(1000, 40000)
        c[4] += random.randint(0, 200000)
        c[5] += random.randint(0, 300000)
        return self._ok({
            "cpu_usage": c[0], "cpu_system_usage": c[1], "online_cpus": 4,
            "memory_usage": int(MEMORY.get(name, 50e6)), "memory_limit": 4e9,
            "memory_percent": round(MEMORY.get(name, 50e6) / 4e9 * 100, 2),
            "network_rx": c[2], "network_tx": c[3], "blk_read": c[4], "blk_write": c[5],
            "cpu_percent": None,
        })

    def app(self) -> web.Application:
        app = web.Application()

        async def addons(request):
            return self._ok({"addons": self.addons})

        async def self_info(request):
            return self._ok({"slug": "local_bruh-task-manager", "options": self.options,
                             "protected": self.protected})

        async def self_options(request):
            if self.refuse_options:
                return web.json_response({"result": "error", "message": "nope"}, status=400)
            body = await request.json()
            self.options = body["options"]
            self.posts.append("options")
            return self._ok()

        async def addon_info(request):
            slug = request.match_info["slug"]
            extra = {"core_mosquitto": {"discovery": ["mqtt"], "boot": "auto", "ingress": False,
                                        "watchdog": True},
                     "a0d7b954_vscode": {"boot": "auto", "ingress": True}}.get(slug, {})
            return self._ok({"slug": slug, **extra})

        async def addon_stats(request):
            return self._stats(request.match_info["slug"])

        async def plugin_stats(request):
            return self._stats(request.match_info["name"])

        async def action(request):
            import asyncio
            self.posts.append(request.path)
            if self.action_delay:
                await asyncio.sleep(self.action_delay)
            slug = request.match_info.get("slug")
            act = request.match_info.get("action")
            for a in self.addons:
                if a["slug"] == slug and act in ("stop", "start"):
                    a["state"] = "stopped" if act == "stop" else "started"
            return self._ok()

        app.router.add_get("/addons", addons)
        app.router.add_get("/addons/self/info", self_info)
        app.router.add_post("/addons/self/options", self_options)
        app.router.add_get("/addons/{slug}/info", addon_info)
        app.router.add_get("/addons/{slug}/stats", addon_stats)
        app.router.add_post("/addons/{slug}/{action}", action)
        async def core_stats(request):
            return self._stats("core")

        async def supervisor_stats(request):
            return self._stats("supervisor")

        app.router.add_get("/core/stats", core_stats)
        app.router.add_get("/supervisor/stats", supervisor_stats)
        app.router.add_post("/core/restart", action)
        app.router.add_post("/supervisor/restart", action)
        app.router.add_post("/{name}/restart", action)
        app.router.add_get("/{name}/stats", plugin_stats)
        return app
