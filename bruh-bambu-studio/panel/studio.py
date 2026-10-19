"""Keep Bambu Studio running on the virtual screen.

The slicer is a desktop app and somebody WILL close its window — that is
what the X in the corner is for — so it is supervised: it is started once
it is installed, started again if it exits, and stopped only when the
panel is asked to stop it. A slicer that crashes on start is not restarted
in a tight loop; each quick failure doubles the wait, and the last lines it
printed are kept for the panel to show, because "Bambu Studio is not
running" with no reason is the screen nobody can act on.

`open(path)` restarts it with a file, which is how "open this model in the
slicer" works without driving its menus: Bambu Studio opens what it is
handed on its command line.
"""
from __future__ import annotations

import collections
import os
import subprocess
import threading
import time

import installer

DISPLAY = os.environ.get("DISPLAY", ":1")
HOME = os.environ.get("HOME", "/data/home")
QUICK_EXIT_S = 20
MAX_BACKOFF_S = 300


class Studio:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.wanted = True
        self.started_at = 0.0
        self.restarts = 0
        self.backoff = 2.0
        self.next_start = 0.0
        self.file: str | None = None
        self.tail: collections.deque[str] = collections.deque(maxlen=40)
        self._lock = threading.Lock()

    def env(self) -> dict:
        return {**os.environ, "DISPLAY": DISPLAY, "HOME": HOME,
                "LIBGL_ALWAYS_SOFTWARE": "1", "GDK_BACKEND": "x11",
                "NO_AT_BRIDGE": "1",
                # WebKit's sandbox needs user namespaces a container
                # does not have; without this its pages are blank.
                "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS": "1",
                "WEBKIT_DISABLE_COMPOSITING_MODE": "1"}

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self) -> None:
        run = installer.apprun()
        if run is None:
            return
        argv = [str(run)]
        if self.file:
            argv.append(self.file)
        self.proc = subprocess.Popen(argv, env=self.env(), cwd=HOME,
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        self.started_at = time.time()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if line:
                self.tail.append(line[:300])

    def tick(self) -> None:
        """Called on the panel's timer."""
        with self._lock:
            if not self.wanted or self.running() or installer.apprun() is None:
                return
            now = time.time()
            if self.proc is not None:
                # It exited. A quick death is a crash loop in the making.
                lived = now - self.started_at
                self.backoff = (min(self.backoff * 2, MAX_BACKOFF_S)
                                if lived < QUICK_EXIT_S else 2.0)
                self.next_start = now + self.backoff
                self.proc = None
                self.restarts += 1
                return
            if now >= self.next_start:
                self._spawn()

    def stop(self) -> None:
        with self._lock:
            self.wanted = False
            self._terminate()

    def _terminate(self) -> None:
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self, file: str | None = None) -> None:
        with self._lock:
            self.file = file
            self.wanted = True
            self._terminate()
            self.backoff = 2.0
            self.next_start = 0.0
            self._spawn()

    def state(self) -> dict:
        info = installer.installed()
        return {
            "installed": bool(info),
            "version": info.get("version") if info else None,
            "running": self.running(),
            "wanted": self.wanted,
            "restarts": self.restarts,
            "next_start_in": max(0, round(self.next_start - time.time()))
            if self.wanted and not self.running() and self.next_start else 0,
            "log_tail": list(self.tail)[-8:],
            "install": dict(installer.STATE),
        }
