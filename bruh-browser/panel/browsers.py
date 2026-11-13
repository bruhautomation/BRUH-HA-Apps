"""Which Claude in Chrome an errand drives: this add-on's own, unless a person said otherwise.

**What Claude Code does when one account has several browsers connected**
(read off Claude Code 2.1.323's bundle; `--chrome` reaches the extension
through Anthropic's bridge, so every Chrome signed in to the account with the
extension on is a candidate, on any computer): it picks the device id
persisted in `~/.claude.json` (`chromeExtension.pairedDeviceId`, or the
`CLAUDE_CHROME_PAIRED_DEVICE_ID` environment variable when the file has
none) if that browser is connected; otherwise THE ONLY connected browser,
wherever it is; otherwise the one on this computer; otherwise it asks the
person (which a `-p` run cannot). So "the only one connected" is how an
errand could drive the owner's laptop without anybody choosing it: this
add-on's Chrome had dropped off, and the laptop's was the only one left.

What this module does about it:

* `list_connected` asks Claude Code's own Chrome MCP server
  (`claude --claude-in-chrome-mcp`, the stdio server `--chrome` starts) for
  `list_connected_browsers` over JSON-RPC: no model, no prompt, the same
  bridge the errand would use. An older CLI without the bridge answers that
  listing needs one, which means only this container's Chrome is reachable.
* `preflight`, before every errand: lists them, works out which one is this
  add-on's Chrome (`identify_own`), and either names the device to pin
  (`pin`, written into `~/.claude.json` and the environment, so the CLI's
  "persisted" rule picks it) or answers a question of kind `choice` for the
  person: the BRUH Browser's own Chrome is not connected, or nobody has said
  which browser this is. It never lets the "only one connected" rule choose.
* The person's default (`/data/browsers.json`) is "own" unless they or brAIn
  set another; an errand may name a browser for itself.

Another computer's Chrome is a bigger step than this add-on's: the extension
there keeps asking its person before it acts (`own=False` leaves the
extension's ask mode alone), and no purchase is ever made there
(`tasks.check_approval`).
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from pathlib import Path

import browser_atomic

OWN = "own"
LIST_TIMEOUT_S = 25
FRESH_S = 60
OWN_LABEL = "the BRUH Browser on your Home Assistant box"
NATIVE_SIGNS = ("only available with bridge connections",)
NOT_CONNECTED_SIGNS = ("not connected", "no browsers are connected", "can't be reached")


def label(row: dict, own_device: str | None) -> str:
    if own_device and row.get("deviceId") == own_device:
        return OWN_LABEL
    name = str(row.get("name") or "").strip()
    platform = str(row.get("osPlatform") or "").strip()
    if name and name.lower() not in ("browser", "chrome"):
        return f"Chrome on {name}" if "chrome" not in name.lower() else name
    return f"Chrome on a {platform} computer" if platform else "Chrome on another computer"


def _is_linux(row: dict) -> bool:
    return "linux" in str(row.get("osPlatform") or "").lower()


def identify_own(rows: list[dict], known: str | None) -> str | None:
    """This add-on's Chrome among the connected browsers, or None when it
    cannot be told apart. The CLI's `onThisComputer` decides when it is
    given; a Linux browser alone among others is the next best sign (the
    add-on's Chrome runs on Linux, a household's laptop rarely does)."""
    ids = [r.get("deviceId") for r in rows]
    if known and known in ids:
        return known
    local = [r for r in rows if r.get("onThisComputer") is True]
    if len(local) == 1:
        return local[0]["deviceId"]
    if any(r.get("onThisComputer") is True for r in rows):
        return None
    linux = [r for r in rows if _is_linux(r) and r.get("onThisComputer") is not False]
    others = [r for r in rows if not _is_linux(r)]
    if len(linux) == 1 and (others or len(rows) == 1) and not known:
        return linux[0]["deviceId"]
    return None


def _rpc(proc: subprocess.Popen, msg: dict) -> None:
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _read_reply(proc: subprocess.Popen, want_id: int, deadline: float) -> dict | None:
    buf = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.5)
        if not ready:
            if proc.poll() is not None:
                return None
            continue
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            return None
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                msg = json.loads(line.decode(errors="replace"))
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == want_id:
                return msg
    return None


def list_connected(claude_bin: str, env: dict,
                   timeout_s: int = LIST_TIMEOUT_S) -> tuple[list[dict] | None, str, bool]:
    """(rows, "", native) or (None, why not, native). `native` is True when
    this CLI reaches only the local Chrome (no bridge, so nothing to choose)."""
    try:
        proc = subprocess.Popen([claude_bin, "--claude-in-chrome-mcp"], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return None, f"Claude Code could not be started to list the browsers: {exc}", False
    deadline = time.monotonic() + timeout_s
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "bruh-browser", "version": "1"}}})
        if _read_reply(proc, 1, deadline) is None:
            return None, "Claude Code's Chrome connection did not answer.", False
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "list_connected_browsers", "arguments": {}}})
        reply = _read_reply(proc, 2, deadline)
    except OSError as exc:
        return None, f"Claude Code's Chrome connection failed: {exc}", False
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if reply is None:
        return None, "Claude Code did not list the browsers in time.", False
    if reply.get("error"):
        message = str((reply.get("error") or {}).get("message") or "an error")
        return None, f"Claude Code could not list the browsers: {message[:200]}", False
    result = reply.get("result") or {}
    texts = [str(b.get("text") or "") for b in result.get("content") or []
             if isinstance(b, dict)]
    joined = " ".join(texts)
    if any(sign in joined.lower() for sign in NATIVE_SIGNS):
        return [], "", True
    for text in texts:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, list):
            rows = [clean_row(r) for r in data if isinstance(r, dict)]
            return [r for r in rows if r], "", False
    if result.get("isError"):
        return None, (joined[:300] or "Claude Code could not list the browsers."), False
    return None, "Claude Code's answer listed no browsers it could read.", False


def clean_row(raw: dict) -> dict | None:
    device = str(raw.get("deviceId") or "").strip()
    if not device or len(device) > 128:
        return None
    row = {"deviceId": device, "name": str(raw.get("name") or "")[:60],
           "osPlatform": str(raw.get("osPlatform") or "")[:30]}
    for key in ("onThisComputer", "isLocal", "inUse"):
        if isinstance(raw.get(key), bool):
            row[key] = raw[key]
    return row


def pin(home: Path, device: str | None, name: str = "") -> None:
    """Make `device` the browser Claude Code's "persisted" rule picks: it is
    read from `~/.claude.json` before the environment, so it is written
    there (the add-on's own Claude Code config; nothing else runs while an
    errand starts, the sign-in window is closed first)."""
    if not device:
        return
    path = Path(home) / ".claude.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    want = {"pairedDeviceId": device, "pairedDeviceName": name or "BRUH Browser"}
    if doc.get("chromeExtension") == want:
        return
    doc["chromeExtension"] = want
    browser_atomic.write_json(path, doc)


class Browsers:
    """The connected browsers as last listed, which one is this add-on's,
    and the household's default."""

    def __init__(self, store: Path, claude_bin: str, env, *, home: Path | None = None,
                 lister=None, now=time.time):
        self.store = Path(store)
        self.home = Path(home or os.environ.get("HOME", "/data/home"))
        self.claude_bin = claude_bin
        self.env = env  # () -> the environment Claude Code runs in
        self.lister = lister or (lambda: list_connected(self.claude_bin, self.env()))
        self.now = now
        self.lock = threading.Lock()
        self.data = {"own_device": None, "default": OWN, "default_name": OWN_LABEL,
                     "seen": [], "listed_at": None, "list_error": "", "native": False}
        try:
            saved = json.loads(self.store.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.data.update({k: saved[k] for k in self.data if k in saved})
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            browser_atomic.write_json(self.store, self.data)
        except OSError:
            pass

    def refresh(self) -> dict:
        rows, why, native = self.lister()
        with self.lock:
            self.data["listed_at"] = self.now()
            self.data["native"] = native
            self.data["list_error"] = why
            if rows is not None:
                self.data["seen"] = rows
                own = identify_own(rows, self.data.get("own_device"))
                if own:
                    self.data["own_device"] = own
            self._save()
            return self.view()

    def fresh(self) -> dict:
        listed = self.data.get("listed_at") or 0
        if self.now() - listed > FRESH_S:
            return self.refresh()
        return self.view()

    def view(self) -> dict:
        own = self.data.get("own_device")
        default = self.data.get("default") or OWN
        rows = []
        for row in self.data.get("seen") or []:
            rows.append({**row, "label": label(row, own), "own": row["deviceId"] == own,
                         "default": (default == OWN and row["deviceId"] == own)
                         or default == row["deviceId"]})
        return {"browsers": rows, "own_device": own,
                "own_connected": bool(own and any(r["deviceId"] == own for r in rows)),
                "default": default,
                "default_label": OWN_LABEL if default == OWN else self.data.get("default_name"),
                "listed_at": self.data.get("listed_at"),
                "list_error": self.data.get("list_error") or "",
                "native": bool(self.data.get("native"))}

    def set_default(self, browser: str) -> tuple[dict | None, str]:
        browser = str(browser or "").strip()
        with self.lock:
            if browser in ("", OWN):
                self.data.update(default=OWN, default_name=OWN_LABEL)
            else:
                row = self._match(browser)
                if not row:
                    return None, "That browser is not one this account has connected."
                if row["deviceId"] == self.data.get("own_device"):
                    self.data.update(default=OWN, default_name=OWN_LABEL)
                else:
                    self.data.update(default=row["deviceId"],
                                     default_name=label(row, self.data.get("own_device")))
            self._save()
            return self.view(), ""

    def set_own(self, device: str) -> tuple[dict | None, str]:
        with self.lock:
            row = self._match(device)
            if not row:
                return None, "That browser is not one this account has connected."
            self.data["own_device"] = row["deviceId"]
            if self.data.get("default") == row["deviceId"]:
                self.data.update(default=OWN, default_name=OWN_LABEL)
            self._save()
            return self.view(), ""

    def _match(self, wanted: str) -> dict | None:
        """A browser by device id or by the words a person used for it."""
        wanted = str(wanted or "").strip()
        own = self.data.get("own_device")
        rows = self.data.get("seen") or []
        for row in rows:
            if row["deviceId"] == wanted:
                return row
        low = wanted.lower()
        if low in (OWN, "bruh browser", "the bruh browser", OWN_LABEL.lower()):
            return next((r for r in rows if r["deviceId"] == own), None)
        hits = [r for r in rows if low and (low in label(r, own).lower()
                                            or low == r.get("name", "").lower())]
        return hits[0] if len(hits) == 1 else None

    def resolve(self, wanted: str | None) -> tuple[str | None, str]:
        """The target an errand names ("own", a device id, a name) as
        (OWN or a device id, "") or (None, why)."""
        wanted = str(wanted or "").strip()
        if not wanted:
            return self.data.get("default") or OWN, ""
        if wanted.lower() in (OWN, "bruh browser", "the bruh browser"):
            return OWN, ""
        with self.lock:
            row = self._match(wanted)
        if not row:
            return None, ("That is not a browser this account has connected. Ask "
                          "browser_status with browsers for the list.")
        if row["deviceId"] == self.data.get("own_device"):
            return OWN, ""
        return row["deviceId"], ""

    def preflight(self, target: str | None) -> dict:
        """Before an errand: {"device", "own", "name"} to run on, or
        {"question": ...} for the person. Lists the browsers afresh."""
        target = target or self.data.get("default") or OWN
        view = self.refresh()
        if view["native"]:
            # This CLI reaches only the Chrome in this container.
            return {"device": None, "own": True, "name": OWN_LABEL}
        rows = view["browsers"]
        if not rows:
            # Nothing listed (or the listing failed): the run finds out for
            # itself and says which setup step to redo. Pin what is known.
            own = view["own_device"]
            if target != OWN:
                return {"question": self._question(
                    "The browser this errand was meant to use is not connected "
                    "right now.", rows, view)}
            return {"device": own, "own": True, "name": OWN_LABEL}
        own = view["own_device"]
        if target == OWN:
            if own and view["own_connected"]:
                return {"device": own, "own": True, "name": OWN_LABEL}
            if not own and len(rows) == 1 and _is_linux(rows[0]) \
                    and rows[0].get("onThisComputer") is not False:
                return {"device": rows[0]["deviceId"], "own": True, "name": OWN_LABEL}
            text = ("BRUH Browser's own Chrome is not connected to Claude right now, "
                    "and another browser on this Claude account is." if own else
                    "Several browsers are connected to this Claude account and it is not "
                    "clear which one is BRUH Browser's own Chrome.")
            return {"question": self._question(text + " Which should this errand use?",
                                               rows, view)}
        row = next((r for r in rows if r["deviceId"] == target), None)
        if row:
            return {"device": target, "own": False, "name": row["label"]}
        return {"question": self._question(
            "The browser this errand was meant to use is not connected right now. "
            "Which should it use?", rows, view)}

    def pin(self, device: str | None, name: str = "") -> None:
        pin(self.home, device, name)

    def question_for(self, text: str) -> dict:
        """"Which browser?" with the browsers as they are now."""
        view = self.refresh()
        return self._question(text + " Which browser should this errand use?"
                              if not text.rstrip().endswith("?") else text,
                              view["browsers"], view)

    @staticmethod
    def _question(text: str, rows: list[dict], view: dict) -> dict:
        options = [{"label": r["label"] if not r["own"] else "Use " + OWN_LABEL,
                    "browser": OWN if r["own"] else r["deviceId"]} for r in rows[:3]]
        if not view["own_connected"]:
            options.insert(0, {"label": "Wait for the BRUH Browser, then try again",
                               "browser": OWN})
        labels = []
        for opt in options:
            if not opt["label"].startswith(("Use ", "Wait ")):
                opt["label"] = "Use " + opt["label"]
            labels.append(opt["label"])
        return {"kind": "choice", "text": text, "options": labels[:4],
                "browsers": options[:4], "money": False}
