"""Keep Google Chrome running on the virtual screen, and the sign-in window.

Chrome is supervised the way BRUH Bambu Studio supervises its slicer: started
once, started again when it exits (somebody WILL close the last window), a
crash on start is not restarted in a tight loop, and the last lines it
printed are kept for the panel to show.

**The sandbox is tried first and given up only when Chrome says so.** Chrome's
renderer sandbox needs user namespaces or a setuid helper; an add-on
container normally has neither (Docker's seccomp profile refuses the
namespace calls), and Chrome then exits at once with "No usable sandbox".
That line, and only that line, switches this to `--no-sandbox`, and the
panel says on its page which one is in force. Remote debugging is never
turned on: there is no `--remote-debugging-port` here, and the managed
policy (`RemoteDebuggingAllowed: false`) refuses it anyway.

The profile is Chrome's default one under $HOME (`~/.config/google-chrome`),
on purpose: Claude Code installs its native messaging host for the
extension into that profile's `NativeMessagingHosts/`, and a Chrome started
with another `--user-data-dir` would not find it.

The sign-in window is an xterm on the same screen running `claude --chrome`,
so Claude Code's `/login` happens where a person can see it, and the page it
opens ($BROWSER, `open-in-chrome.sh`) opens in this Chrome.
"""
from __future__ import annotations

import collections
import os
import shlex
import subprocess
import threading
import time

DISPLAY = os.environ.get("DISPLAY", ":1")
HOME = os.environ.get("HOME", "/data/home")
CHROME_BIN = os.environ.get("BROWSER_CHROME_BIN", "google-chrome")
TERMINAL_BIN = os.environ.get("BROWSER_TERMINAL_BIN", "xterm")
OPEN_BIN = os.environ.get("BROWSER_OPEN_BIN", "/opt/bruh-browser/open-in-chrome.sh")
ERRANDS_DIR = os.path.join(HOME, "errands")
QUICK_EXIT_S = 20
MAX_BACKOFF_S = 300
NO_SANDBOX_SIGNS = ("no usable sandbox", "failed to move to new namespace",
                    "operation not permitted", "setuid sandbox")

# The pages the setup steps open in the embedded Chrome. A fixed list: the
# route takes a name, never a URL, so nothing reaching the panel can open
# an arbitrary page in a browser signed in to the household's shops.
PAGES = {
    "webstore": "https://chromewebstore.google.com/detail/fcoeoabgfenejglbffodgkkbkcdhcgfn",
    "claude": "https://claude.ai/login",
    "extensions": "chrome://extensions/?id=fcoeoabgfenejglbffodgkkbkcdhcgfn",
    # The extension's site permissions page, as Claude Code's /chrome links it.
    "permissions": "https://clau.de/chrome/permissions",
}


def _screen_size() -> tuple[int, int]:
    raw = os.environ.get("SCREEN_RESOLUTION", "1366x900")
    try:
        w, h = (int(x) for x in raw.lower().split("x", 1))
        return w, h
    except ValueError:
        return 1366, 900


class Chrome:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.terminal: subprocess.Popen | None = None
        self.wanted = True
        self.sandbox = True
        self.sandbox_note = ""
        self._retry_now = False
        self.started_at = 0.0
        self.restarts = 0
        self.backoff = 2.0
        self.next_start = 0.0
        self.tail: collections.deque[str] = collections.deque(maxlen=40)
        self._lock = threading.Lock()

    def env(self) -> dict:
        return {**os.environ, "DISPLAY": DISPLAY, "HOME": HOME,
                "BROWSER": OPEN_BIN, "NO_AT_BRIDGE": "1"}

    def argv(self) -> list[str]:
        w, h = _screen_size()
        out = [CHROME_BIN, "--no-first-run", "--no-default-browser-check",
               # A container's /dev/shm is 64 MB; Chrome's tabs crash in it.
               "--disable-dev-shm-usage",
               # No keyring on this screen: without this Chrome stalls asking
               # for one before it shows a window.
               "--password-store=basic",
               "--hide-crash-restore-bubble",
               "--window-position=0,0", f"--window-size={w},{h}",
               "--start-maximized"]
        if not self.sandbox:
            out.append("--no-sandbox")
        return out

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self) -> None:
        try:
            self.proc = subprocess.Popen(self.argv(), env=self.env(), cwd=HOME,
                                         stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT)
        except OSError as exc:
            self.tail.append(f"Chrome could not be started: {exc}")
            self.proc = None
            self.next_start = time.time() + MAX_BACKOFF_S
            return
        self.started_at = time.time()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            self.tail.append(line[:300])
            if self.sandbox and "sandbox" in line.lower() and any(
                    sign in line.lower() for sign in NO_SANDBOX_SIGNS):
                self.sandbox = False
                self._retry_now = True
                self.sandbox_note = ("Chrome's own sandbox is not available in this "
                                     "container, so it runs with --no-sandbox; "
                                     "the add-on's container and AppArmor profile "
                                     "are the boundary.")

    def tick(self) -> None:
        """Called on the panel's timer."""
        with self._lock:
            if self.terminal is not None and self.terminal.poll() is not None:
                self.terminal = None
            if not self.wanted or self.running():
                return
            now = time.time()
            if self.proc is not None:
                lived = now - self.started_at
                self.proc = None
                self.restarts += 1
                if self._retry_now:
                    # It died for want of a sandbox: start again unsandboxed now.
                    self._retry_now = False
                    self.backoff, self.next_start = 2.0, now
                    return
                self.backoff = (min(self.backoff * 2, MAX_BACKOFF_S)
                                if lived < QUICK_EXIT_S else 2.0)
                self.next_start = now + self.backoff
                return
            if now >= self.next_start:
                self._spawn()

    def open_page(self, name: str) -> str | None:
        """Open one of PAGES as a tab; a sentence when it cannot be."""
        url = PAGES.get(name)
        if not url:
            return "That is not a page this panel opens."
        if not self.running():
            return "Chrome is not running yet; wait a few seconds and try again."
        try:
            subprocess.Popen([OPEN_BIN, url], env=self.env(), cwd=HOME,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as exc:
            return f"The page could not be opened: {exc}"
        return None

    # ------------------------------------------------------------ sign-in

    def terminal_open(self) -> bool:
        return self.terminal is not None and self.terminal.poll() is None

    def open_terminal(self) -> str | None:
        """The sign-in window: `claude --chrome` in an xterm on this screen."""
        if self.terminal_open():
            return None
        os.makedirs(ERRANDS_DIR, exist_ok=True)
        script = (f"cd {shlex.quote(ERRANDS_DIR)} && claude --chrome; echo; "
                  "read -r -p 'Claude Code has closed. Press Enter to close this window. ' _")
        argv = [TERMINAL_BIN, "-title", "Sign Claude Code in",
                "-fa", "DejaVu Sans Mono", "-fs", "14",
                "-bg", "#0b1016", "-fg", "#e8eef3",
                "-e", "bash", "-c", script]
        try:
            self.terminal = subprocess.Popen(argv, env=self.env(), cwd=ERRANDS_DIR,
                                             stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL,
                                             start_new_session=True)
        except OSError as exc:
            return f"The sign-in window could not be opened: {exc}"
        return None

    def close_terminal(self) -> bool:
        """Close the sign-in window; True when one was open."""
        term = self.terminal
        if term is None or term.poll() is not None:
            self.terminal = None
            return False
        try:
            os.killpg(term.pid, 15)
        except OSError:
            term.terminate()
        try:
            term.wait(timeout=5)
        except subprocess.TimeoutExpired:
            term.kill()
        self.terminal = None
        return True

    def state(self) -> dict:
        return {"running": self.running(), "restarts": self.restarts,
                "sandbox": self.sandbox, "sandbox_note": self.sandbox_note,
                "terminal_open": self.terminal_open(),
                "log_tail": list(self.tail)[-6:]}
