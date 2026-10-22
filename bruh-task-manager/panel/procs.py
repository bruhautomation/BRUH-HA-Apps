"""Every process on the machine, read straight out of /proc (Level 2).

Nothing here talks to the Supervisor or decides anything; it reads files and
does arithmetic, and the root it reads is a parameter so a test can hand it a
fake /proc. Three questions, three sections:

**What is each process doing?** `read_proc` parses `stat`, `status`,
`cmdline` and `cgroup`. CPU is `utime + stime` (field 14 and 15 of `stat`) and
a percentage is only defined between two readings, so `ProcessSampler` keeps
the last reading per process and divides the difference by the wall time and
the number of CPUs — the same "share of the whole machine" the Supervisor
uses for apps, so a process's figure and its app's figure are on one scale.
A process is keyed by (pid, start time): pids are reused, and a new process
under an old number must not inherit the old one's ticks.

Memory is resident memory (`VmRSS`). Proportional memory (`smaps_rollup`'s
`Pss`) is the honest figure for shared libraries, but reading it needs ptrace
READ access and the TARGET's AppArmor profile has to grant it, which most
apps' profiles do not; so it is read where it can be and reported as absent
where it cannot, never guessed.

**Which app does it belong to?** Every container is a cgroup, and
`/proc/<pid>/cgroup` names it (`.../docker-<64 hex>.scope`). That says WHICH
container but not whose — the Supervisor's API has no container ids — so the
container is named by what it mounts: an app's `/data` is
`.../addons/data/<slug>` on the host, the Supervisor's is `.../supervisor`,
and Home Assistant's container mounts `/config` from `.../homeassistant` and
has no `/data` at all. `mountinfo` is readable without ptrace access, which
is why that and not `/proc/<pid>/root` is the route. Supervisor plugins (DNS,
audio, …) mount neither and are named by their command. A container nothing
can name is reported as an unknown container, never guessed at — the ending
policy refuses those for exactly that reason.

**Can we see the host at all?** With Protection mode on, the container has
its own PID namespace and every process it can see is its own. Kernel
threads only exist in the host's namespace, so seeing one is the proof that
Level 2 is really in effect (`host_visible`), which is a different claim from
the option being switched on.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

# PF_KTHREAD in the flags field of /proc/<pid>/stat.
PF_KTHREAD = 0x00200000

CONTAINER_RE = re.compile(r"docker[-/]([0-9a-f]{64})")
ADDON_DATA_RE = re.compile(r"/addons/data/([^/]+)/?$")

# Supervisor plugins, named by the command their container runs. The key is
# the Level 1 key, so the two levels link.
PLUGIN_COMMANDS = (
    ("coredns", "plugin:dns", "DNS (Supervisor plugin)"),
    ("pulseaudio", "plugin:audio", "Audio (Supervisor plugin)"),
    ("mdns-repeater", "plugin:multicast", "Multicast (Supervisor plugin)"),
    ("observer", "plugin:observer", "Observer (Supervisor plugin)"),
)

MAX_CMD = 400


@dataclass
class Proc:
    pid: int
    ppid: int
    comm: str
    state: str
    ticks: int
    start: int
    threads: int
    kernel: bool
    cgroup: str
    cmd: str = ""
    uid: int | None = None
    rss_kb: int | None = None
    pss_kb: int | None = None
    ns_pid: int | None = None  # the pid inside its own namespace (1 = init)


@dataclass
class Identity:
    """Who a group of processes belongs to."""
    kind: str  # addon, core, supervisor, plugin, self, os, kernel, container
    key: str
    name: str
    slug: str | None = None


@dataclass
class Group:
    identity: Identity
    procs: list = field(default_factory=list)


def _read(path: str, binary: bool = False):
    mode = "rb" if binary else "r"
    try:
        with open(path, mode) as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def parse_stat(text: str):
    """(comm, fields after the comm) — the comm may contain spaces and ')'."""
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right < left:
        return None
    return text[left + 1:right], text[right + 2:].split()


def parse_cgroup(text: str) -> str:
    """The process's cgroup path: the v2 line, else the first docker one."""
    if not text:
        return ""
    fallback = ""
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        if parts[0] == "0" and parts[1] == "":
            if CONTAINER_RE.search(parts[2]) or not fallback:
                return parts[2]
        if not fallback and CONTAINER_RE.search(parts[2]):
            fallback = parts[2]
    return fallback


def read_proc(root: str, pid: int) -> Proc | None:
    base = os.path.join(root, str(pid))
    stat = _read(os.path.join(base, "stat"))
    if stat is None:
        return None
    parsed = parse_stat(stat)
    if parsed is None:
        return None
    comm, rest = parsed
    try:
        state = rest[0]
        ppid = int(rest[1])
        flags = int(rest[6])
        ticks = int(rest[11]) + int(rest[12])
        threads = int(rest[17])
        start = int(rest[19])
    except (IndexError, ValueError):
        return None
    proc = Proc(pid=pid, ppid=ppid, comm=comm, state=state, ticks=ticks,
                start=start, threads=threads,
                kernel=bool(flags & PF_KTHREAD),
                cgroup=parse_cgroup(_read(os.path.join(base, "cgroup")) or ""))
    raw = _read(os.path.join(base, "cmdline"), binary=True)
    if raw:
        proc.cmd = raw.rstrip(b"\0").replace(b"\0", b" ").decode(
            "utf-8", "replace")[:MAX_CMD]
    status = _read(os.path.join(base, "status")) or ""
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            proc.rss_kb = _kb(line)
        elif line.startswith("Uid:"):
            try:
                proc.uid = int(line.split()[1])
            except (IndexError, ValueError):
                pass  # no uid shown; nothing decides anything on it
        elif line.startswith("NSpid:"):
            try:
                proc.ns_pid = int(line.split()[-1])
            except (IndexError, ValueError):
                # Unknown, not 1: the init check then falls back to the
                # process name (policy.SUPERVISION).
                pass
    if not proc.kernel:
        rollup = _read(os.path.join(base, "smaps_rollup"))
        if rollup:
            for line in rollup.splitlines():
                if line.startswith("Pss:"):
                    proc.pss_kb = _kb(line)
                    break
    return proc


def _kb(line: str) -> int | None:
    try:
        return int(line.split()[1])
    except (IndexError, ValueError):
        return None


def list_pids(root: str) -> list[int]:
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(int(n) for n in names if n.isdigit())


# ----------------------------------------------------------------------------
# Naming containers
# ----------------------------------------------------------------------------

def _unescape(path: str) -> str:
    """mountinfo writes a space as \\040, a tab as \\011 and so on."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def identify_mounts(mountinfo: str) -> Identity | None:
    """Name a container by what its /data and /config are on the host."""
    data_root = config_root = None
    for line in (mountinfo or "").splitlines():
        head = line.split(" - ", 1)[0].split()
        if len(head) < 5:
            continue
        root, mount_point = _unescape(head[3]), _unescape(head[4])
        if mount_point == "/data":
            data_root = root
        elif mount_point == "/config":
            config_root = root
    if data_root:
        match = ADDON_DATA_RE.search(data_root)
        if match:
            slug = match.group(1)
            return Identity("addon", f"addon:{slug}", slug, slug=slug)
        if data_root.rstrip("/").endswith("/supervisor") or data_root == "/supervisor":
            return Identity("supervisor", "supervisor", "Supervisor")
        return None
    if config_root and config_root.rstrip("/").endswith("/homeassistant"):
        return Identity("core", "core", "Home Assistant")
    return None


def identify_commands(commands) -> Identity | None:
    """Name a container by its commands, for the ones that mount nothing."""
    joined = " ".join(commands)
    if re.search(r"-m\s+homeassistant\b|/usr/src/homeassistant", joined):
        return Identity("core", "core", "Home Assistant")
    if re.search(r"-m\s+supervisor\b|/usr/src/supervisor", joined):
        return Identity("supervisor", "supervisor", "Supervisor")
    for word, key, name in PLUGIN_COMMANDS:
        if any(os.path.basename(c.split(" ", 1)[0]) == word for c in commands):
            return Identity("plugin", key, name)
    return None


def os_unit(cgroup: str) -> str:
    """'…/system.slice/NetworkManager.service' -> 'NetworkManager'."""
    last = cgroup.rstrip("/").rsplit("/", 1)[-1]
    for suffix in (".service", ".scope", ".slice", ".mount"):
        if last.endswith(suffix):
            last = last[: -len(suffix)]
    if last in ("", "init"):
        return "systemd"
    return last


# ----------------------------------------------------------------------------
# The sampler
# ----------------------------------------------------------------------------

class ProcessSampler:
    """Two readings make a percentage; this keeps the previous one."""

    # An unnamed container is asked again every this many samples: its
    # processes may have been mid-start the first time.
    RELABEL_EVERY = 12

    def __init__(self, root: str = "/proc", *, self_pid: int | None = None,
                 clock=time.monotonic, hz: int | None = None,
                 ncpu: int | None = None) -> None:
        self.root = root
        self.self_pid = self_pid if self_pid is not None else os.getpid()
        self.clock = clock
        self.hz = hz or os.sysconf("SC_CLK_TCK")
        self.ncpu = ncpu or os.cpu_count() or 1
        self._prev: dict[tuple[int, int], int] = {}
        self._prev_t: float | None = None
        self._labels: dict[str, Identity] = {}
        self._label_age: dict[str, int] = {}
        self._self_cgroup: str | None = None

    # -- naming ---------------------------------------------------------------

    def self_cgroup(self) -> str:
        if self._self_cgroup is None:
            text = _read(os.path.join(self.root, str(self.self_pid), "cgroup"))
            self._self_cgroup = parse_cgroup(text or "")
        return self._self_cgroup

    def identify(self, proc: Proc, members=None) -> Identity:
        if proc.kernel:
            return Identity("kernel", "kernel", "Linux kernel")
        if proc.cgroup == self.self_cgroup():
            return Identity("self", "self", "BRUH Task Manager")
        match = CONTAINER_RE.search(proc.cgroup)
        if not match:
            unit = os_unit(proc.cgroup)
            return Identity("os", "os", "Home Assistant OS", slug=unit)
        cid = match.group(1)
        known = self._labels.get(cid)
        if known is not None and (known.kind != "container"
                                  or self._label_age.get(cid, 0) > 0):
            if known.kind == "container":
                self._label_age[cid] -= 1
            return known
        identity = self._label(cid, members or [proc])
        self._labels[cid] = identity
        if identity.kind == "container":
            self._label_age[cid] = self.RELABEL_EVERY
        return identity

    def _label(self, cid: str, members) -> Identity:
        for proc in sorted(members, key=lambda p: p.pid)[:6]:
            info = _read(os.path.join(self.root, str(proc.pid), "mountinfo"))
            found = identify_mounts(info or "")
            if found:
                return found
        found = identify_commands([p.cmd or p.comm for p in members])
        if found:
            return found
        return Identity("container", f"container:{cid[:12]}",
                        f"Container {cid[:12]}")

    # -- one reading ----------------------------------------------------------

    def read_all(self) -> list[Proc]:
        out = []
        for pid in list_pids(self.root):
            proc = read_proc(self.root, pid)
            if proc is not None:
                out.append(proc)
        return out

    def sample(self) -> dict:
        now = self.clock()
        procs = self.read_all()
        elapsed = None if self._prev_t is None else max(now - self._prev_t, 1e-6)
        seen: dict[tuple[int, int], int] = {}
        by_cgroup: dict[str, list[Proc]] = {}
        for proc in procs:
            by_cgroup.setdefault(proc.cgroup, []).append(proc)

        groups: dict[str, Group] = {}
        host_visible = False
        for proc in procs:
            key = (proc.pid, proc.start)
            seen[key] = proc.ticks
            cpu = None
            if elapsed is not None and key in self._prev:
                delta = max(proc.ticks - self._prev[key], 0)
                cpu = round(delta / self.hz / elapsed / self.ncpu * 100.0, 2)
            if proc.kernel:
                host_visible = True
            identity = self.identify(proc, by_cgroup.get(proc.cgroup))
            group = groups.get(identity.key)
            if group is None:
                group = groups[identity.key] = Group(identity)
            row = row_of(proc, cpu)
            if identity.kind == "os":
                row["unit"] = identity.slug
            group.procs.append(row)

        self._prev = seen
        self._prev_t = now
        return {
            "host_visible": host_visible,
            "measured": elapsed is not None,
            "groups": [summarise(g) for g in groups.values()],
            "count": len(procs),
        }

    def describe(self, pid: int):
        """A fresh read of one process and who owns it, for End process."""
        proc = read_proc(self.root, pid)
        if proc is None:
            return None, None
        members = []
        for other in self.read_all():
            if other.cgroup == proc.cgroup:
                members.append(other)
        return proc, self.identify(proc, members or [proc])


def row_of(proc: Proc, cpu) -> dict:
    return {
        "pid": proc.pid,
        "ppid": proc.ppid,
        "start": proc.start,
        "name": proc.comm,
        "cmd": proc.cmd or f"[{proc.comm}]",
        "state": proc.state,
        "cpu": cpu,
        "rss_kb": proc.rss_kb,
        "pss_kb": proc.pss_kb,
        "threads": proc.threads,
        "uid": proc.uid,
        "ns_pid": proc.ns_pid,
        "kernel": proc.kernel,
    }


def summarise(group: Group) -> dict:
    ident = group.identity
    cpu = [p["cpu"] for p in group.procs if p["cpu"] is not None]
    rss = [p["rss_kb"] for p in group.procs if p["rss_kb"] is not None]
    return {
        "key": ident.key,
        "kind": ident.kind,
        "name": ident.name,
        "slug": None if ident.kind == "os" else ident.slug,
        "cpu": round(sum(cpu), 2) if cpu else None,
        "rss_kb": sum(rss) if rss else None,
        "count": len(group.procs),
        "procs": sorted(group.procs, key=lambda p: (-(p["cpu"] or 0), p["pid"])),
    }


def host_visible(root: str = "/proc") -> bool:
    """Is this the host's process list? Only the host has kernel threads.

    pid 2 is kthreadd on every Linux host; inside a private PID namespace
    pid 2 is one of the container's own processes, which is never a kernel
    thread.
    """
    proc = read_proc(root, 2)
    return bool(proc and proc.kernel)
