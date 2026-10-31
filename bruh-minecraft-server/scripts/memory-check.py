#!/usr/bin/env python3
"""Compare the Java heap (memory_mb) with the host's memory, at add-on start.

A 6 GB heap on a 16 GB host left about 320 MB for everything else, the kernel
ended Java with SIGKILL, and nothing said why (#585). This only WARNS: it never
touches the stored option. The message is printed (run.sh logs it) and written
to $MC_PANEL_STATE/memory-warning.json for the panel's status; with no problem
the file is removed.

Inside an HA add-on /proc/meminfo reports the HOST's memory.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# What the rest of the host (HA Core, the OS, other add-ons) is left to live in.
RESERVE_MB = 2048


def read_meminfo(path: str = "/proc/meminfo") -> tuple[int, int]:
    """(MemTotal, MemAvailable) in MB, or (0, 0) when unreadable."""
    total = avail = 0
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return 0, 0
    return total, avail


def assess(memory_mb: int, total_mb: int, available_mb: int) -> dict | None:
    """A warning dict when the heap leaves too little for the host, else None."""
    if total_mb <= 0:
        return None  # cannot tell; say nothing rather than guess
    leaves = total_mb - memory_mb
    suggested = max(1024, ((total_mb - RESERVE_MB) // 256) * 256)
    if leaves < RESERVE_MB:
        message = (
            f"memory_mb is {memory_mb} MB but this host has {total_mb} MB, which leaves "
            f"only {max(leaves, 0)} MB for Home Assistant and everything else. Linux may "
            f"kill the server for memory. Consider memory_mb {suggested} or lower in the "
            "add-on's Configuration tab.")
    elif 0 < available_mb < memory_mb:
        message = (
            f"memory_mb is {memory_mb} MB but only {available_mb} MB is free right now "
            f"(of {total_mb} MB). Linux may kill the server for memory. Consider "
            f"memory_mb {suggested} or lower in the add-on's Configuration tab.")
    else:
        return None
    return {"memory_mb": memory_mb, "host_total_mb": total_mb,
            "host_available_mb": available_mb, "leaves_mb": max(leaves, 0),
            "suggested_mb": suggested, "message": message}


def main() -> int:
    try:
        memory_mb = int(os.environ.get("MEMORY_MB", "2048"))
    except ValueError:
        return 0
    total, avail = read_meminfo(os.environ.get("MEMINFO_PATH", "/proc/meminfo"))
    warning = assess(memory_mb, total, avail)
    out = Path(os.environ.get("MC_PANEL_STATE", "/data/panel")) / "memory-warning.json"
    try:
        if warning:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(warning))
            tmp.replace(out)
        else:
            out.unlink(missing_ok=True)
    except OSError:
        pass  # the log line below is the main channel
    if warning:
        print(warning["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
