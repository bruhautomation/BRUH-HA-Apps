"""The whole machine: CPU, memory, load and uptime.

/proc/stat, /proc/meminfo, /proc/loadavg and /proc/uptime are not
namespaced, so these are the HOST's figures at every level — Level 1
included, with Protection mode on.
"""
from __future__ import annotations

import os


def _read(path: str) -> str:
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def cpu_times(root: str = "/proc"):
    """(busy, total) jiffies from the aggregate line of /proc/stat."""
    for line in _read(os.path.join(root, "stat")).splitlines():
        if line.startswith("cpu "):
            try:
                values = [int(v) for v in line.split()[1:]]
            except ValueError:
                return None
            # user nice system idle iowait irq softirq steal (guest is
            # already counted in user, so it is left out of the total).
            values = values[:8]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            return total - idle, total
    return None


def meminfo(root: str = "/proc") -> dict:
    out = {}
    for line in _read(os.path.join(root, "meminfo")).splitlines():
        name, _, rest = line.partition(":")
        try:
            out[name] = int(rest.split()[0]) * 1024
        except (IndexError, ValueError):
            continue
    return out


class MachineSampler:
    def __init__(self, root: str = "/proc", ncpu: int | None = None) -> None:
        self.root = root
        self.ncpu = ncpu or os.cpu_count() or 1
        self._prev = None

    def sample(self) -> dict:
        times = cpu_times(self.root)
        cpu = None
        if times and self._prev:
            busy = times[0] - self._prev[0]
            total = times[1] - self._prev[1]
            if total > 0:
                cpu = round(max(busy, 0) / total * 100.0, 1)
        if times:
            self._prev = times
        mem = meminfo(self.root)
        total = mem.get("MemTotal")
        available = mem.get("MemAvailable")
        used = total - available if total and available is not None else None
        load = _read(os.path.join(self.root, "loadavg")).split()
        uptime = _read(os.path.join(self.root, "uptime")).split()
        return {
            "cpu": cpu,
            "cpus": self.ncpu,
            "mem_total": total,
            "mem_used": used,
            "mem_percent": round(used / total * 100.0, 1) if used is not None and total else None,
            "swap_total": mem.get("SwapTotal"),
            "swap_used": (mem["SwapTotal"] - mem.get("SwapFree", 0))
            if mem.get("SwapTotal") else None,
            "load": [float(v) for v in load[:3]] if len(load) >= 3 else None,
            "uptime_s": int(float(uptime[0])) if uptime else None,
        }
