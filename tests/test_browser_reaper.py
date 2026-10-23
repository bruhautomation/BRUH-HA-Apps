"""A headless browser nobody is using is ended by the panel (report #355).

Two Chromium trees, started by a Bash tool in a terminal session that had
ended hours earlier, were reparented to PID 1 and went on burning CPU.
`browser_reaper` finds the TOP browser of an orphaned tree past a grace
period and ends its tree. Everything here runs over a fake /proc, with the
kill function injected: no test signals a real process.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "brain" / "panel"))

from task_manager_fake import stat_line  # noqa: E402

import browser_reaper  # noqa: E402

HZ = 100
UPTIME = 10_000.0


def started(age_s: float) -> int:
    return int((UPTIME - age_s) * HZ)


class FakeProcTree:
    """/proc as the kernel writes it: stat in field order, cmdline NUL-split."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "uptime").write_text(f"{UPTIME:.2f} 1234.00\n")

    def add(self, pid, ppid, comm, argv, age_s, uid=None):
        d = self.root / str(pid)
        d.mkdir()
        (d / "stat").write_text(stat_line(pid, comm, "S", ppid, 0, 0, 1, started(age_s)))
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        uid = os.getuid() if uid is None else uid
        (d / "status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")

    def remove(self, pid):
        d = self.root / str(pid)
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


CHROME = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"


class TestOnlyAnOrphanedIdleBrowserIsReaped(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.proc = FakeProcTree(base / "proc")
        self.tmp_root = base / "tmp"
        self.profile = self.tmp_root / "claude-1000" / "-config" / "s" / "prof9333"
        self.profile.mkdir(parents=True)
        (self.profile / "Local State").write_text("{}")
        self.young_profile = self.tmp_root / "prof9341"
        self.young_profile.mkdir()
        p = self.proc
        p.add(1, 0, "s6-svscan", ["/package/admin/s6/command/s6-svscan"], 20_000)
        # 1. orphaned headless Chromium, an hour old, with its helpers
        p.add(100, 1, "chrome", [CHROME, "--headless=new", "--remote-debugging-port=9333",
                                  f"--user-data-dir={self.profile}", "about:blank"], 3600)
        p.add(101, 100, "chrome", [CHROME, "--type=zygote", "--no-sandbox"], 3600)
        p.add(102, 101, "chrome", [CHROME, "--type=renderer", "--headless=new"], 3590)
        # 2. orphan inside the grace period
        p.add(200, 1, "chrome", [CHROME, "--headless", "--remote-debugging-port=9341",
                                  f"--user-data-dir={self.young_profile}"], 60)
        # 3. a browser whose parent (a Playwright run) is still alive
        p.add(300, 1, "node", ["node", "shot.mjs"], 4000)
        p.add(301, 300, "chrome", [CHROME, "--headless=new", "--remote-debugging-pipe"], 3900)
        # 4. a non-browser orphan
        p.add(400, 1, "python3", ["python3", "-m", "http.server", "--headless"], 5000)
        # 5. an orphaned renderer is not the top of a tree
        p.add(500, 1, "chrome", [CHROME, "--type=renderer", "--headless=new"], 5000)
        # 6. a non-headless browser (somebody's own Chrome) is left alone
        p.add(600, 1, "chrome", [CHROME, "--user-data-dir=/root/.config/chrome"], 5000)
        self.sent: list[tuple[int, int]] = []
        self.removed: list[str] = []

    def tearDown(self):
        self._tmp.cleanup()

    def reap(self, kill=None):
        def fake_kill(pid, sig):
            self.sent.append((pid, sig))
        return browser_reaper.reap(
            proc_root=str(self.proc.root), kill=kill or fake_kill,
            sleep=lambda _s: None, hz=HZ, tmp_roots=(str(self.tmp_root),),
            remove=lambda path: self.removed.append(path))

    def test_only_the_idle_orphan_tree_is_signalled(self):
        reaped = self.reap()
        self.assertEqual([r["pid"] for r in reaped], [100])
        self.assertEqual(reaped[0]["profile"], str(self.profile))
        termed = {pid for pid, sig in self.sent if sig == signal.SIGTERM}
        killed = {pid for pid, sig in self.sent if sig == signal.SIGKILL}
        self.assertEqual(termed, {100, 101, 102})
        # Nothing went away in the fake, so the wait ends in SIGKILL.
        self.assertEqual(killed, {100, 101, 102})
        touched = {pid for pid, _ in self.sent}
        self.assertFalse(touched & {1, 200, 300, 301, 400, 500, 600})
        self.assertEqual(self.removed, [str(self.profile)])

    def test_a_tree_that_goes_on_sigterm_is_not_killed(self):
        def kill(pid, sig):
            self.sent.append((pid, sig))
            if sig == signal.SIGTERM:
                self.proc.remove(pid)
        self.reap(kill=kill)
        self.assertFalse([s for s in self.sent if s[1] == signal.SIGKILL])

    def test_a_pid_reused_during_the_wait_is_not_killed(self):
        def kill(pid, sig):
            self.sent.append((pid, sig))
            if sig == signal.SIGTERM and pid == 102:
                self.proc.remove(102)
                self.proc.add(102, 1, "bash", ["bash"], 1)
        self.reap(kill=kill)
        self.assertNotIn((102, signal.SIGKILL), self.sent)

    def test_a_profile_not_under_tmp_or_not_the_owners_is_kept(self):
        self.proc.remove(100)
        self.proc.add(100, 1, "chrome", [CHROME, "--headless", "--user-data-dir=/root/keep"], 3600)
        self.reap()
        self.assertEqual(self.removed, [])
        self.proc.remove(100)
        self.proc.add(100, 1, "chrome", [CHROME, "--headless",
                                          f"--user-data-dir={self.profile}"], 3600,
                      uid=os.getuid() + 1)
        self.reap()
        self.assertEqual(self.removed, [])

    def test_it_never_raises(self):
        def boom(*_a):
            raise PermissionError("no")
        self.assertEqual(len(self.reap(kill=boom)), 1)
        with unittest.mock.patch.object(browser_reaper, "reap",
                                        side_effect=RuntimeError("x")):
            self.assertEqual(browser_reaper.maybe_reap(now=1e9, force=True), 0)

    def test_maybe_reap_is_gated_and_stands_down_off_the_addon(self):
        calls = []
        with unittest.mock.patch.object(browser_reaper, "reap",
                                        lambda **_k: calls.append(1) or []), \
                unittest.mock.patch.object(browser_reaper, "_LAST", []):
            browser_reaper.maybe_reap(now=1000.0, force=True)
            self.assertIsNone(browser_reaper.maybe_reap(now=1010.0, force=True))
            browser_reaper.maybe_reap(now=1000.0 + browser_reaper.REAP_INTERVAL_S,
                                      force=True)
        self.assertEqual(calls, [1, 1])
        with unittest.mock.patch.object(browser_reaper, "reap",
                                        lambda **_k: calls.append(1) or []), \
                unittest.mock.patch.object(browser_reaper, "_LAST", []), \
                unittest.mock.patch.object(browser_reaper, "in_addon", lambda: False):
            self.assertIsNone(browser_reaper.maybe_reap(now=1.0))
        self.assertEqual(calls, [1, 1])


class TestTheSchedulerTickReaps(unittest.TestCase):
    def test_one_tick_calls_the_reaper(self):
        import server  # noqa: PLC0415
        reaped: list[int] = []

        async def one_tick():
            ticks = {"n": 0}

            async def sleep_once(_seconds):
                ticks["n"] += 1
                if ticks["n"] > 1:
                    raise asyncio.CancelledError

            with unittest.mock.patch.object(asyncio, "sleep", sleep_once), \
                    unittest.mock.patch.object(server.ownership, "maybe_sweep", lambda: None), \
                    unittest.mock.patch.object(server.browser_reaper, "maybe_reap",
                                               lambda: reaped.append(1)), \
                    unittest.mock.patch.object(server.findings_store, "sweep_inbox",
                                               lambda *a: []), \
                    unittest.mock.patch.object(server, "_ingest_facts", lambda: None), \
                    unittest.mock.patch.object(server.journal, "book_shell_rows",
                                               lambda *a: None):
                try:
                    await server._scheduler()
                except asyncio.CancelledError:
                    pass  # the second sleep ends the loop; that is the exit

        with unittest.mock.patch.dict(os.environ, {"BRAIN_ENABLE_INSIGHTS": "false"}):
            asyncio.run(one_tick())
        self.assertEqual(reaped, [1])


class TestTheScreenshotBrowserIsNeverLeftBehind(unittest.TestCase):
    """`screens._launch` cancelled while it waits for the DevTools port:
    the browser it started (here a stand-in that never writes the port
    file, and a child of its own) is ended, group and all."""

    def test_a_cancelled_launch_kills_its_group(self):
        sys.path.insert(0, str(HERE.parent / "brain" / "panel"))
        from devloop import screens  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "chrome"
            fake.write_text("#!/bin/sh\nsleep 30 &\necho $! > \"$0.child\"\nwait\n")
            fake.chmod(0o755)
            profile = Path(tmp) / "prof"
            profile.mkdir()
            seen = {}

            async def go():
                real = asyncio.create_subprocess_exec

                async def spy(*a, **k):
                    proc = await real(*a, **k)
                    seen["proc"] = proc
                    return proc
                with unittest.mock.patch.object(asyncio, "create_subprocess_exec", spy):
                    task = asyncio.ensure_future(screens._launch(str(fake), str(profile)))
                    for _ in range(50):
                        await asyncio.sleep(0.05)
                        if Path(f"{fake}.child").exists():
                            break
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 5)
                    await asyncio.wait_for(seen["proc"].wait(), 5)
            asyncio.run(go())
            child = int(Path(f"{fake}.child").read_text())
            gone = False
            for _ in range(50):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    gone = True
                    break
                stat = Path(f"/proc/{child}/stat")
                if stat.exists() and stat.read_text().split(") ")[1].startswith("Z"):
                    gone = True
                    break
                import time  # noqa: PLC0415
                time.sleep(0.05)
            self.assertTrue(gone, "the browser's child outlived a cancelled launch")


if __name__ == "__main__":
    unittest.main()
