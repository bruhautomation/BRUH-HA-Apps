"""End a headless browser nobody is using any more (report #355).

A Claude session in the terminal or the chat that runs Playwright or
Chromium from a Bash tool for a screenshot can end — the session closed,
the tool timed out, the script crashed — and leave the browser running.
Its parent goes, the kernel reparents it to PID 1, and its renderers go on
spending several percent of CPU each for as long as the add-on runs: the
house that reported this went from 12% to idle once two such trees were
killed by hand.

So the panel, which runs as root in the add-on's own PID namespace, looks
on start and about every `REAP_INTERVAL_S` from the scheduler's tick (no
loop of its own, `ownership.maybe_sweep`'s shape) for the TOP process of a
Chromium tree — `chrome`/`chromium`/`headless_shell`, started headless or
with a DevTools port or pipe, and not itself a `--type=` helper — that is
ORPHANED (its parent is PID 1) and older than `GRACE_S`, and ends that
tree: SIGTERM to every process in it, then SIGKILL to whatever is still
there after `TERM_WAIT_S`. A browser whose parent is alive is somebody's
run in progress (a Playwright script, brAIn's own screenshot pass, a test)
and is never touched; neither is anything that is not a browser.

The tree is walked by parent pid rather than signalled as a process group:
a browser started from a shell may share its group with things that are
still somebody's work. A pid is signalled only while it still carries the
start time it had when it was read, so a pid reused during the wait is
never killed. A profile directory the browser named under the temp
directory, owned by the browser's own user, is removed afterwards.

Pure over a /proc root and an injected kill, so the tests run over a fake
tree and never signal a real process. Never raises.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import tempfile
import time

log = logging.getLogger("brain.browser_reaper")

# An orphan younger than this may be a browser whose launcher is between
# processes; past it nobody is going to come back for it.
GRACE_S = 300
# How often the scheduler's tick looks.
REAP_INTERVAL_S = 120
# How long a tree has to exit on SIGTERM before SIGKILL.
TERM_WAIT_S = 5.0

BROWSER_NAMES = frozenset({
    "chrome", "chromium", "chromium-browser", "chrome-headless-shell",
    "headless_shell", "google-chrome", "google-chrome-stable",
})
_FLAGS = ("--headless", "--remote-debugging-port", "--remote-debugging-pipe")

_LAST: list[float] = []


def in_addon() -> bool:
    """Only inside the add-on: a dev checkout or a test machine is somebody
    else's processes. The Supervisor writes /data/options.json; nothing
    else does."""
    return os.path.isfile("/data/options.json")


def _read(path: str, binary: bool = False):
    try:
        with open(path, "rb" if binary else "r") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _stat(proc_root: str, pid: int):
    """(ppid, start ticks) off /proc/<pid>/stat, or None."""
    raw = _read(f"{proc_root}/{pid}/stat")
    if not raw:
        return None
    try:
        rest = raw[raw.rindex(")") + 2:].split()
        return int(rest[1]), int(rest[19])
    except (ValueError, IndexError):
        return None


def _uid(proc_root: str, pid: int):
    raw = _read(f"{proc_root}/{pid}/status") or ""
    for line in raw.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    return None


def _snapshot(proc_root: str) -> dict[int, dict]:
    procs: dict[int, dict] = {}
    try:
        names = os.listdir(proc_root)
    except OSError:
        return procs
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        st = _stat(proc_root, pid)
        if st is None:
            continue
        raw = _read(f"{proc_root}/{pid}/cmdline", binary=True) or b""
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        procs[pid] = {"pid": pid, "ppid": st[0], "start": st[1], "argv": argv}
    return procs


def is_browser(argv: list[str]) -> bool:
    """The top process of a headless or remote-controlled Chromium."""
    if not argv:
        return False
    if os.path.basename(argv[0]) not in BROWSER_NAMES:
        return False
    args = argv[1:]
    if any(a.startswith("--type=") for a in args):
        return False
    return any(a == f or a.startswith(f + "=") for a in args for f in _FLAGS)


def _profile(argv: list[str]) -> str | None:
    for a in argv:
        if a.startswith("--user-data-dir="):
            return a.split("=", 1)[1] or None
    return None


def _tree(procs: dict[int, dict], top: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for p in procs.values():
        children.setdefault(p["ppid"], []).append(p["pid"])
    out, todo, seen = [], [top], set()
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        todo.extend(children.get(pid, ()))
    return out


def _same(proc_root: str, pid: int, start: int) -> bool:
    st = _stat(proc_root, pid)
    return st is not None and st[1] == start


def _remove_profile(path: str, uid, tmp_roots, remove) -> bool:
    """Remove a profile directory only under a temp root, never the root
    itself, never through a link, and only one the browser's user owns."""
    if not path or uid is None:
        return False
    try:
        real = os.path.realpath(path)
        info = os.lstat(real)
    except OSError:
        return False
    if not os.path.isdir(real) or os.path.islink(real) or info.st_uid != uid:
        return False
    for root in tmp_roots:
        base = os.path.realpath(root)
        if real != base and real.startswith(base.rstrip(os.sep) + os.sep):
            remove(real)
            return True
    return False


def reap(*, proc_root: str = "/proc", kill=os.kill, sleep=time.sleep,
         hz: int | None = None, grace_s: float = GRACE_S,
         tmp_roots=None, remove=None) -> list[dict]:
    """End every orphaned headless browser tree past ``grace_s``. Answers
    what it reaped, ``[{"pid", "profile", "tree"}]``."""
    hz = hz or os.sysconf("SC_CLK_TCK")
    tmp_roots = tmp_roots or (tempfile.gettempdir(),)
    remove = remove or (lambda p: shutil.rmtree(p, ignore_errors=True))
    uptime_raw = _read(f"{proc_root}/uptime")
    try:
        uptime = float(uptime_raw.split()[0])
    except (AttributeError, ValueError, IndexError):
        return []
    procs = _snapshot(proc_root)
    reaped: list[dict] = []
    for p in sorted(procs.values(), key=lambda r: r["pid"]):
        if p["ppid"] != 1 or not is_browser(p["argv"]):
            continue
        if uptime - p["start"] / hz < grace_s:
            continue
        tree = _tree(procs, p["pid"])
        profile = _profile(p["argv"])
        uid = _uid(proc_root, p["pid"])
        for sig in (signal.SIGTERM, signal.SIGKILL):
            live = [pid for pid in tree if _same(proc_root, pid, procs[pid]["start"])]
            if not live:
                break
            if sig == signal.SIGKILL:
                log.info("browser reaper: pid %d did not exit on SIGTERM; killing",
                         p["pid"])
            for pid in live:
                try:
                    kill(pid, sig)
                except Exception:  # noqa: BLE001 — gone, or not ours to signal
                    pass
            if sig == signal.SIGTERM:
                sleep(TERM_WAIT_S)
        log.info("browser reaper: ended an idle headless browser, pid %d "
                 "(%d processes), profile %s", p["pid"], len(tree), profile or "-")
        if profile:
            try:
                _remove_profile(profile, uid, tmp_roots, remove)
            except Exception:  # noqa: BLE001 — a profile left is only disk
                pass
        reaped.append({"pid": p["pid"], "profile": profile, "tree": tree})
    return reaped


def maybe_reap(now: float | None = None, force: bool = False) -> int | None:
    """`reap` at most every `REAP_INTERVAL_S`, and only inside the add-on;
    None when it did not run. Never raises — it rides the scheduler tick."""
    if not force and not in_addon():
        return None
    now = time.monotonic() if now is None else now
    if _LAST and now - _LAST[0] < REAP_INTERVAL_S:
        return None
    _LAST[:] = [now]
    try:
        return len(reap())
    except Exception as exc:  # noqa: BLE001 — a reap is never the tick
        log.debug("browser reaper failed: %s", exc)
        return 0
