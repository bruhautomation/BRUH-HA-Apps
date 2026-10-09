"""brAIn photographs its own panel, redacted, and measures what it shows.

The development loop could report what brAIn SAID (the design stream reads
its words) and what broke (faults), and nothing could see what a screen
LOOKS like on a real house: a control off the edge of a phone, a list
that scrolls sideways, a label the colours make unreadable. Those are the
bugs a person meets first and the ones a fixture house never has, because
a fixture house has eight lights and short names. So this stream drives a
headless Chromium over the panel on loopback, photographs each screen at
a phone's width and a laptop's, measures the layout faults a script can
see, and files one issue per release with the pictures attached. The cloud
half reads the pictures for what a script cannot see: whether it looks
like a modern product.

**What leaves the house is redacted on the page, before the picture is
taken, and a part of the page that cannot be redacted is covered.** Every
string the page renders — text nodes in every frame that can be reached,
the value and placeholder of every field — is collected, sent through
`redact` (one Python function, the same one for every frame), and written
back before the capture. `redact` removes, in this order:

* anything containing a CONFIDENTIAL string read off the house at capture
  time: a calendar entity's event title, description and location, the
  occasions brAIn read off the calendar, every zone's name but Home's,
  and any state or attribute that reads as a street address (a phone's
  geocoded location is one) — blanked whole, because a calendar event
  with one word changed is still the event;
* credentials: `upstream.scrub`'s rules, a password field's value, and
  anything key-shaped (a long mixed-case-and-digit run, a long hex run);
* addresses: a street address, a postcode beside a state or town, an
  email address, a phone number, a pair of coordinates;
* then the loop's own aliases, so a room or a lamp is called what the
  issue text calls it.

Pixels that are not text cannot be read, so they are covered: every
canvas, video, embedded object and image that is not one of the panel's
own static files, and every frame whose text could not be reached.
Nothing is uploaded from a capture whose redaction did not complete: a
screen that raised is dropped, and a capture where none completed files
nothing.

**It runs only when somebody switches it on**, like every stream, and it
costs no Claude run. It needs Chromium, which ships in the image; a box
without it says so in ⚙ rather than failing quietly.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

log = logging.getLogger("brain.devloop.screens")

# Where the panel answers inside the container. Loopback, because this is
# brAIn photographing itself: nothing here reaches past the box.
PANEL_URL = os.environ.get("BRAIN_SCREENS_URL", "http://127.0.0.1:8099/")

# The screens, as (slug, label, the script that shows it). Each script
# calls a function app.js already has, so a screen is shown the way its
# own button shows it. Settings sections are shown with the page open.
SCREENS: list[tuple[str, str, str]] = [
    ("insights", "Insights", "switchView('insights')"),
    ("needs-you", "Needs you", "switchView('findings')"),
    ("history", "History", "switchView('archive')"),
    ("ask", "Ask", "switchView('terminal')"),
    ("knowledge", "Knowledge", "switchView('memory')"),
    ("timeline", "Timeline", "switchView('activity')"),
    ("house-book", "House book", "switchView('housebook')"),
    ("settings", "Settings", "openSettings()"),
    ("settings-usage", "Settings › Model & usage",
     "openSettings().then(() => showSettingsSection('usage'))"),
    ("settings-notify", "Settings › Notifications",
     "openSettings().then(() => showSettingsSection('notifications'))"),
    ("settings-diagnostics", "Settings › Diagnostics",
     "openSettings().then(() => showSettingsSection('diagnostics'))"),
]
# (width, height, touch, colour scheme). A phone in both schemes, because a
# phone is where most people read brAIn and where dark mode is commonest,
# and a laptop with Home Assistant's sidebar open.
VIEWS: list[tuple[int, int, bool, str]] = [
    (390, 844, True, "light"),
    (390, 844, True, "dark"),
    (1200, 800, False, "light"),
]
# A screen taller than this is cut: a ten-thousand-pixel list is not a
# picture anybody reads, and the layout faults are measured whole anyway.
MAX_HEIGHT = 2600
NAV_TIMEOUT_S = 25
SETTLE_S = 0.8          # quiet on the network for this long = drawn
SETTLE_MAX_S = 9.0
MAX_PROBLEMS_PER_KIND = 6
# A test's look at the page after redaction and before the picture: the
# assertion that nothing confidential is left is made on the real page.
AFTER_REDACT = None

# A file name the panel may serve back for the review preview. Made here,
# checked again where it is read, because the route takes it off a URL.
SHOT_RE = re.compile(r"^[a-z0-9-]{1,40}-\d{3,4}-(?:light|dark)\.png$")
CAPTURE_RE = re.compile(r"^\d{10}$")

BLOCK = "▇"

# ---------------------------------------------------------------------------
# Redaction: one function for every string on every frame
# ---------------------------------------------------------------------------

_STREET_WORDS = (
    "street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|"
    "way|place|pl|terrace|ter|close|crescent|cres|highway|hwy|parkway|pkwy|"
    "circle|cir|square|sq|trail|trl|row|grove|gardens|mews|walk|hill")
ADDRESS_RE = re.compile(
    r"\b\d{1,6}[A-Za-z]?(?:[ \t]+[A-Za-z0-9.'-]+){1,5}[ \t]+(?:" + _STREET_WORDS
    + r")\b\.?(?:,?[ \t]+(?:apt|unit|suite|#)\s*[\w-]+)?", re.IGNORECASE)
# A postcode only counts beside something that makes it one: two capital
# letters (a US state) or a UK/Canadian shape that nothing else has.
POSTCODE_RE = re.compile(
    r"\b[A-Z]{2}[ \t]+\d{5}(?:-\d{4})?\b"
    r"|\b[A-Z]{1,2}\d[A-Z\d]?[ \t]*\d[A-Z]{2}\b"
    r"|\b[A-Z]\d[A-Z][ \t]?\d[A-Z]\d\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Groups of digits split by spaces, dots or dashes, nine digits or more in
# all (`_phone`): a date, a time, a version and a reading all fall short.
PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-]){1,4}\d{3,4}(?![\w.])")
LATLON_RE = re.compile(r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}")
# Key-shaped: what a credential looks like when nothing named it. Mixed
# case AND digits (entity ids are lower-case, so they never match), or a
# long hex run (a device or config entry id is 32, which is also what a
# webhook id looks like, and neither is worth a picture).
_KEYISH_RE = re.compile(r"[A-Za-z0-9_+/=-]{24,}")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_SECRET_LABEL_RE = re.compile(
    r"(?i)\b(password|passcode|passwd|pin|api[ _-]?key|secret|token)\b(\s*[:=]\s*)\S+")


def _blank(match: re.Match) -> str:
    return "".join(c if c.isspace() else BLOCK for c in match.group(0))


def _phone(match: re.Match) -> str:
    if sum(c.isdigit() for c in match.group(0)) >= 9:
        return _blank(match)
    return match.group(0)


def _keyish(match: re.Match) -> str:
    s = match.group(0)
    if (any(c.isupper() for c in s) and any(c.islower() for c in s)
            and any(c.isdigit() for c in s)):
        return BLOCK * min(len(s), 24)
    return s


def redact(text: str, *, confidential: list[str] | None = None,
           aliases=None) -> str:
    """One rendered string as it may appear in a picture that leaves the
    house. Never raises; anything it cannot reason about is blanked."""
    try:
        s = str(text or "")
        if not s.strip():
            return s
        low = s.casefold()
        for secret in confidential or ():
            if secret and secret.casefold() in low:
                return "".join(c if c.isspace() else BLOCK for c in s)
        from .upstream import scrub  # noqa: PLC0415 — upstream imports reports
        out = scrub(s)
        out = _SECRET_LABEL_RE.sub(lambda m: m.group(1) + m.group(2) + BLOCK * 6, out)
        for pattern in (EMAIL_RE, LATLON_RE, ADDRESS_RE, POSTCODE_RE):
            out = pattern.sub(_blank, out)
        out = PHONE_RE.sub(_phone, out)
        out = _HEX_RE.sub(lambda m: BLOCK * 12, out)
        out = _KEYISH_RE.sub(_keyish, out)
        if aliases is not None:
            out = aliases.apply(out)
        return out
    except Exception:  # noqa: BLE001 — a string we could not judge is not sent
        return "".join(c if c.isspace() else BLOCK for c in str(text or ""))


def confidential_strings(states: list | None, occasions_store: dict | None
                         ) -> list[str]:
    """What the house holds that must never be in a picture, read off the
    house at capture time. Longest first, so a title is matched before a
    word inside it; anything under four characters is too common to blank
    every string that contains it."""
    found: set[str] = set()

    def keep(value) -> None:
        if isinstance(value, str):
            v = " ".join(value.split())
            if len(v) >= 4:
                found.add(v[:200])

    for st in states or []:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        attrs = st.get("attributes") if isinstance(st.get("attributes"), dict) else {}
        domain = eid.split(".", 1)[0]
        if domain == "calendar":
            for key in ("message", "description", "location"):
                keep(attrs.get(key))
        elif domain == "zone" and eid != "zone.home":
            keep(attrs.get("friendly_name"))
        state = st.get("state")
        if isinstance(state, str) and (eid.endswith("geocoded_location")
                                       or ADDRESS_RE.search(state)):
            keep(state)
        for value in attrs.values():
            if isinstance(value, str) and len(value) <= 200 and ADDRESS_RE.search(value):
                keep(value)
    for occ in (occasions_store or {}).get("occasions") or []:
        if isinstance(occ, dict) and occ.get("kind") != "weather":
            keep(occ.get("text"))
    return sorted(found, key=len, reverse=True)


# ---------------------------------------------------------------------------
# What runs in the page
# ---------------------------------------------------------------------------

# Collect every rendered string in this frame. Kept on `window` so the
# apply step writes back to exactly the nodes that were read.
_COLLECT_JS = r"""
(() => {
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
  const nodes = [], strings = new Set();
  const walk = (root) => {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const p = n.parentElement;
      if (!n.nodeValue.trim() || (p && SKIP.has(p.tagName))) continue;
      nodes.push(n); strings.add(n.nodeValue);
    }
    root.querySelectorAll("*").forEach((el) => { if (el.shadowRoot) walk(el.shadowRoot); });
  };
  if (document.body) walk(document.body);
  const fields = [...document.querySelectorAll("input, textarea")];
  for (const f of fields) {
    if (f.value) strings.add(f.value);
    if (f.placeholder) strings.add(f.placeholder);
  }
  window.__brainShot = { nodes, fields };
  return [...strings];
})()
"""

# Write the redacted strings back, then cover what is not text.
_APPLY_JS = r"""
((map) => {
  const s = window.__brainShot;
  if (!s) throw new Error("nothing collected");
  for (const n of s.nodes) if (Object.prototype.hasOwnProperty.call(map, n.nodeValue)) n.nodeValue = map[n.nodeValue];
  for (const f of s.fields) {
    if (f.type === "password") { f.value = f.value ? "••••••••" : ""; continue; }
    if (f.value && Object.prototype.hasOwnProperty.call(map, f.value)) f.value = map[f.value];
    if (f.placeholder && Object.prototype.hasOwnProperty.call(map, f.placeholder)) f.placeholder = map[f.placeholder];
  }
  const style = document.createElement("style");
  style.textContent = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}";
  (document.head || document.documentElement).appendChild(style);
  return true;
})
"""

# Cover every pixel that is not text and could not be read: a canvas, a
# video, an embed, an image that is not one of the panel's own files, and a
# frame nobody marked as redacted.
_COVER_JS = r"""
(() => {
  const own = (img) => {
    const src = img.currentSrc || img.src || "";
    if (!src || src.startsWith("data:") || src.startsWith("blob:")) return false;
    try {
      const u = new URL(src, location.href);
      return u.origin === location.origin && !u.pathname.includes("/api/")
        && /\.(svg|png|ico|webp)$/i.test(u.pathname);
    } catch (e) { return false; }
  };
  const targets = [...document.querySelectorAll("canvas, video, object, embed, iframe, frame, img")]
    .filter((el) => (el.tagName === "IFRAME" || el.tagName === "FRAME")
      ? el.dataset.brainRedacted !== "1"
      : el.tagName === "IMG" ? !own(el) : true);
  let n = 0;
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const box = document.createElement("div");
    box.setAttribute("data-brain-cover", "1");
    box.textContent = "not captured";
    Object.assign(box.style, {
      position: "absolute", left: (r.left + scrollX) + "px", top: (r.top + scrollY) + "px",
      width: r.width + "px", height: r.height + "px", zIndex: 2147483647,
      background: "repeating-linear-gradient(45deg,#8a8f98,#8a8f98 8px,#9aa0a8 8px,#9aa0a8 16px)",
      color: "#fff", font: "12px system-ui", display: "flex", alignItems: "center",
      justifyContent: "center", pointerEvents: "none" });
    document.body.appendChild(box);
    n++;
  }
  return n;
})()
"""

# The layout faults a script can see, measured in the main frame.
_AUDIT_JS = r"""
((coarse, width) => {
  // The window's width as set, not innerWidth: a phone's browser zooms a
  // page that is too wide out to fit, and innerWidth then says it fits.
  const W = width || innerWidth, out = [];
  const desc = (el) => {
    // "button#id (btn tiny)", never "button.btn": `button.x` is an entity
    // id's shape, and the issue's aliases would rename it.
    let d = el.tagName.toLowerCase();
    if (el.id) d += "#" + el.id;
    const cls = [...el.classList].slice(0, 2);
    if (cls.length) d += " (" + cls.join(" ") + ")";
    return d;
  };
  const own = (el) => [...el.childNodes].filter((n) => n.nodeType === 3)
    .map((n) => n.nodeValue).join(" ").replace(/\s+/g, " ").trim();
  const label = (el) => (own(el) || el.getAttribute("aria-label") || el.innerText || "")
    .replace(/\s+/g, " ").trim().slice(0, 60);
  const shown = (el) => {
    if (el.closest("[data-brain-cover]")) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.05;
  };
  const scrollerX = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll" || ox === "hidden" || ox === "clip") return true;
    }
    return false;
  };
  const add = (kind, el, detail) => out.push({ kind, el: desc(el), text: label(el), detail });
  const doc = document.scrollingElement || document.documentElement;
  if (doc.scrollWidth > W + 1)
    out.push({ kind: "page_scrolls_sideways", el: "html", text: "",
               detail: `the page is ${doc.scrollWidth}px wide in a ${W}px window` });
  const all = [...document.body.querySelectorAll("*")].filter(shown);
  const offscreen = all.filter((el) => {
    const r = el.getBoundingClientRect();
    return (r.right > W + 1 || r.left < -1) && getComputedStyle(el).position !== "fixed"
      && !scrollerX(el);
  });
  for (const el of offscreen) {
    if (offscreen.includes(el.parentElement)) continue;
    const r = el.getBoundingClientRect();
    add("off_the_edge", el, `spans ${Math.round(r.left)}–${Math.round(r.right)}px in a ${W}px window`);
  }
  const controls = all.filter((el) => el.matches(
    "button, a[href], [role=button], [role=tab], select, summary, input:not([type=hidden]), textarea"));
  if (coarse) {
    for (const el of controls) {
      if (el.matches("p a, li a, .md a")) continue;
      const r = el.getBoundingClientRect();
      const t = el.matches("input[type=checkbox], input[type=radio]") ? el.closest("label") || el : el;
      const tr = t.getBoundingClientRect();
      if (Math.min(tr.width, tr.height) < 40)
        add("small_target", el, `${Math.round(tr.width)}×${Math.round(tr.height)}px, under the 40px a finger needs`);
    }
    for (const el of all.filter((e) => e.matches("input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=hidden]), textarea, select"))) {
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < 16) add("zooms_on_focus", el, `${fs}px text: iOS zooms the page in on focus below 16px`);
    }
  }
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (!own(el)) continue;
    if ((cs.overflowX === "hidden" || cs.overflowX === "clip") && cs.textOverflow !== "ellipsis"
        && el.scrollWidth > el.clientWidth + 2)
      add("text_cut_off", el, `${el.scrollWidth - el.clientWidth}px of text hidden with no ellipsis`);
  }
  // A bar pinned to the window sits over whatever scrolls under it; that
  // is what it is for, and not two controls fighting for one spot.
  const pinned = (el) => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const pos = getComputedStyle(p).position;
      if (pos === "fixed" || pos === "sticky") return true;
    }
    return false;
  };
  for (let i = 0; i < controls.length; i++) {
    if (pinned(controls[i])) continue;
    const a = controls[i].getBoundingClientRect();
    for (let j = i + 1; j < controls.length; j++) {
      if (controls[i].contains(controls[j]) || controls[j].contains(controls[i])
          || pinned(controls[j])) continue;
      const b = controls[j].getBoundingClientRect();
      const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      const small = Math.min(a.width * a.height, b.width * b.height);
      if (ix > 0 && iy > 0 && small > 0 && ix * iy > 0.25 * small)
        add("controls_overlap", controls[i], `overlaps ${desc(controls[j])} “${label(controls[j])}”`);
    }
  }
  const rgb = (c) => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : null; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => {
    for (let p = el; p; p = p.parentElement) {
      const c = rgb(getComputedStyle(p).backgroundColor);
      if (c && (c.length < 4 || c[3] > 0.5)) return c;
    }
    return matchMedia("(prefers-color-scheme: dark)").matches ? [0, 0, 0] : [255, 255, 255];
  };
  for (const el of all) {
    // WCAG exempts a control that is switched off.
    if (!own(el) || el.closest(":disabled, [aria-disabled=true]")) continue;
    const cs = getComputedStyle(el);
    const fg = rgb(cs.color);
    if (!fg || (fg.length > 3 && fg[3] < 0.5)) continue;
    const L1 = lum(fg), L2 = lum(bgOf(el));
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const big = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && +cs.fontWeight >= 700);
    if (ratio < (big ? 3 : 4.5))
      add("low_contrast", el, `contrast ${ratio.toFixed(2)}:1, under ${big ? 3 : 4.5}:1`);
  }
  return { problems: out, height: Math.min(doc.scrollHeight, 20000) };
})
"""


# ---------------------------------------------------------------------------
# The browser
# ---------------------------------------------------------------------------

def find_browser() -> str:
    """The Chromium on this box, or "" when there is none."""
    explicit = os.environ.get("BRAIN_CHROMIUM", "")
    if explicit and os.access(explicit, os.X_OK):
        return explicit
    for name in ("chromium-browser", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/usr/lib/chromium/chromium", "/usr/bin/chromium-browser"):
        if os.access(path, os.X_OK):
            return path
    return ""


class CDP:
    """The few DevTools calls this needs, over one WebSocket."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.inflight: set[str] = set()
        self.last_net = time.monotonic()
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        import aiohttp  # noqa: PLC0415
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if "id" in data:
                fut = self.pending.pop(data["id"], None)
                if fut and not fut.done():
                    fut.set_result(data)
                continue
            method = data.get("method", "")
            params = data.get("params") or {}
            if method == "Network.requestWillBeSent":
                self.inflight.add(params.get("requestId", ""))
                self.last_net = time.monotonic()
            elif method in ("Network.loadingFinished", "Network.loadingFailed"):
                self.inflight.discard(params.get("requestId", ""))
                self.last_net = time.monotonic()
            elif method == "Network.responseReceived":
                # A stream never finishes; once it answers it is not "loading".
                if "event-stream" in str((params.get("response") or {}).get("mimeType")):
                    self.inflight.discard(params.get("requestId", ""))
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("the browser went away"))

    async def call(self, method: str, params: dict | None = None,
                   session: str | None = None, timeout: float = 20) -> dict:
        self.next_id += 1
        mid = self.next_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send_str(json.dumps(msg))
        data = await asyncio.wait_for(fut, timeout)
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error'].get('message')}")
        return data.get("result") or {}

    async def settle(self) -> None:
        """Wait until the page has stopped fetching, within reason."""
        start = time.monotonic()
        while time.monotonic() - start < SETTLE_MAX_S:
            quiet = time.monotonic() - self.last_net
            if quiet >= SETTLE_S and (not self.inflight or quiet >= 4):
                return
            await asyncio.sleep(0.15)


async def _launch(binary: str, profile: str):
    args = [
        binary, "--headless=new", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--disable-background-networking",
        "--disable-breakpad", "--disable-crash-reporter", "--mute-audio",
        "--hide-scrollbars", "--force-device-scale-factor=1",
        # The panel's chart frames are sandboxed srcdoc pages. Kept in the
        # page's own process they can be reached to redact; split off they
        # cannot, and would be covered instead. Only loopback is loaded.
        "--disable-site-isolation-trials",
        "--disable-features=IsolateSandboxedIframes,site-per-process,Translate",
        "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    port_file = Path(profile) / "DevToolsActivePort"
    for _ in range(150):
        if port_file.exists():
            lines = port_file.read_text().splitlines()
            if lines and lines[0].isdigit():
                return proc, int(lines[0]), lines[1] if len(lines) > 1 else ""
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.1)
    proc.kill()
    raise RuntimeError("Chromium did not start")


async def _stop(proc) -> None:
    """Wait for the browser to exit, and kill it if it will not."""
    try:
        await asyncio.wait_for(proc.wait(), 5)
        return
    except asyncio.TimeoutError:
        proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        log.warning("devloop screens: Chromium did not exit after it was killed")


async def _redact_frame(cdp: CDP, session: str, frame_id: str, context: int | None,
                        confidential: list[str], aliases) -> None:
    params = {"expression": _COLLECT_JS, "returnByValue": True}
    if context is not None:
        params["contextId"] = context
    res = await cdp.call("Runtime.evaluate", params, session)
    if res.get("exceptionDetails"):
        raise RuntimeError("could not read the frame's text")
    strings = (res.get("result") or {}).get("value") or []
    mapping = {}
    for s in strings:
        if isinstance(s, str):
            r = redact(s, confidential=confidential, aliases=aliases)
            if r != s:
                mapping[s] = r
    params = {"expression": f"({_APPLY_JS})({json.dumps(mapping)})",
              "returnByValue": True}
    if context is not None:
        params["contextId"] = context
    res = await cdp.call("Runtime.evaluate", params, session)
    if res.get("exceptionDetails") or (res.get("result") or {}).get("value") is not True:
        raise RuntimeError("could not write the frame's text back")


def _frames(tree: dict) -> list[dict]:
    out = []
    for child in tree.get("childFrames") or []:
        out.append(child["frame"])
        out += _frames(child)
    return out


async def _redact_page(cdp: CDP, session: str, confidential: list[str], aliases) -> None:
    """Every frame's text redacted, then everything else covered. Raises if
    the MAIN frame could not be redacted: that screen is then not kept."""
    await _redact_frame(cdp, session, "", None, confidential, aliases)
    tree = (await cdp.call("Page.getFrameTree", {}, session)).get("frameTree") or {}
    await cdp.call("DOM.getDocument", {"depth": 0}, session)
    frames = _frames(tree)
    worlds: list[int] = []
    for frame in frames:
        try:
            world = await cdp.call("Page.createIsolatedWorld",
                                   {"frameId": frame["id"], "worldName": "brain-shot",
                                    "grantUniveralAccess": False}, session)
            ctx = int(world["executionContextId"])
            await _redact_frame(cdp, session, frame["id"], ctx, confidential, aliases)
            owner = await cdp.call("DOM.getFrameOwner", {"frameId": frame["id"]}, session)
            obj = await cdp.call("DOM.resolveNode",
                                 {"backendNodeId": owner["backendNodeId"]}, session)
            await cdp.call("Runtime.callFunctionOn", {
                "objectId": obj["object"]["objectId"],
                "functionDeclaration": "function(){this.dataset.brainRedacted='1'}"},
                session)
            worlds.append(ctx)
        except Exception as exc:  # noqa: BLE001 — an unreachable frame is covered
            log.info("devloop screens: a frame was covered, not redacted: %s", exc)
    for ctx in worlds:
        try:
            await cdp.call("Runtime.evaluate", {"expression": _COVER_JS,
                                                "contextId": ctx}, session)
        except Exception:  # noqa: BLE001 — its owner is marked; cover it whole
            pass
    res = await cdp.call("Runtime.evaluate", {"expression": _COVER_JS,
                                              "returnByValue": True}, session)
    if res.get("exceptionDetails"):
        raise RuntimeError("could not cover the page's images")


async def capture(out_dir: Path, *, confidential: list[str], aliases,
                  url: str = PANEL_URL, screens=None, views=None) -> dict:
    """Photograph every screen at every view into ``out_dir``. Answers
    ``{"shots": [...], "problems": [...], "errors": [...]}``; a screen that
    could not be redacted is in ``errors`` and has no picture."""
    import aiohttp  # noqa: PLC0415

    binary = find_browser()
    if not binary:
        raise RuntimeError("Chromium is not installed on this box")
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: list[dict] = []
    problems: list[dict] = []
    errors: list[str] = []
    # The profile is removed by hand, after the browser has gone: its helper
    # processes go on writing to it for a moment after the browser is told
    # to stop, and a TemporaryDirectory that raised on "directory not
    # empty" would throw away a capture that had finished.
    profile = tempfile.mkdtemp(prefix="brain-shot-")
    proc = None
    try:
        proc, port, ws_path = await _launch(binary, profile)
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(f"ws://127.0.0.1:{port}{ws_path}",
                                       max_msg_size=64 * 1024 * 1024) as ws:
                cdp = CDP(ws)
                for width, height, touch, scheme in (views or VIEWS):
                    for slug, label, script in (screens or SCREENS):
                        try:
                            shot = await _one(cdp, url, slug, label, script, width,
                                              height, touch, scheme, out_dir,
                                              confidential, aliases)
                        except Exception as exc:  # noqa: BLE001 — one screen
                            errors.append(f"{label} at {width}px {scheme}: {exc}"[:200])
                            continue
                        problems += shot.pop("problems")
                        shots.append(shot)
                try:
                    await cdp.call("Browser.close", timeout=5)
                except Exception:  # noqa: BLE001 — it is killed below if it did not go
                    pass
                cdp.reader.cancel()
    finally:
        if proc is not None:
            await _stop(proc)
        shutil.rmtree(profile, ignore_errors=True)
    return {"shots": shots, "problems": problems, "errors": errors}


async def _one(cdp: CDP, url: str, slug: str, label: str, script: str,
               width: int, height: int, touch: bool, scheme: str,
               out_dir: Path, confidential: list[str], aliases) -> dict:
    """One screen in its own tab, so nothing a previous screen left open
    (a dialog, a scroll position) is in this picture."""
    target = await cdp.call("Target.createTarget", {"url": "about:blank"})
    tid = target["targetId"]
    session = (await cdp.call("Target.attachToTarget",
                              {"targetId": tid, "flatten": True}))["sessionId"]
    try:
        await cdp.call("Page.enable", {}, session)
        await cdp.call("Network.enable", {}, session)
        await cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1,
            "mobile": touch}, session)
        await cdp.call("Emulation.setTouchEmulationEnabled",
                       {"enabled": True, "maxTouchPoints": 5} if touch
                       else {"enabled": False}, session)
        await cdp.call("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": scheme},
            {"name": "prefers-reduced-motion", "value": "reduce"}]}, session)
        cdp.last_net = time.monotonic()
        await cdp.call("Page.navigate", {"url": url}, session, timeout=NAV_TIMEOUT_S)
        await cdp.settle()
        res = await cdp.call("Runtime.evaluate", {
            "expression": f"Promise.resolve({script})", "awaitPromise": True},
            session, timeout=NAV_TIMEOUT_S)
        if res.get("exceptionDetails"):
            raise RuntimeError("the screen could not be opened")
        cdp.last_net = time.monotonic()
        await cdp.settle()
        await cdp.call("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"}, session)
        await _redact_page(cdp, session, confidential, aliases)
        if AFTER_REDACT is not None:
            await AFTER_REDACT(cdp, session)
        res = await cdp.call("Runtime.evaluate", {
            "expression": f"({_AUDIT_JS})({json.dumps(touch)}, {int(width)})",
            "returnByValue": True}, session)
        audit = (res.get("result") or {}).get("value") or {}
        full = max(height, min(int(audit.get("height") or height), MAX_HEIGHT))
        await cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": full, "deviceScaleFactor": 1,
            "mobile": touch}, session)
        await asyncio.sleep(0.3)
        pic = await cdp.call("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": False}, session, timeout=30)
        name = f"{slug}-{width}-{scheme}.png"
        if not SHOT_RE.match(name):
            raise RuntimeError("bad screen name")
        data = base64.b64decode(pic["data"])
        (out_dir / name).write_bytes(data)
        problems = []
        per_kind: dict[str, int] = {}
        for p in audit.get("problems") or []:
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind") or "")
            per_kind[kind] = per_kind.get(kind, 0) + 1
            if per_kind[kind] > MAX_PROBLEMS_PER_KIND:
                continue
            problems.append({
                "screen": label, "width": width, "scheme": scheme, "kind": kind,
                "el": str(p.get("el") or "")[:80],
                "text": redact(str(p.get("text") or "")[:60],
                               confidential=confidential, aliases=aliases),
                "detail": str(p.get("detail") or "")[:160]})
        return {"name": name, "screen": label, "width": width, "scheme": scheme,
                "sha": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "problems": problems}
    finally:
        try:
            await cdp.call("Target.closeTarget", {"targetId": tid})
        except Exception:  # noqa: BLE001 — a tab that will not close dies with the browser
            pass


# ---------------------------------------------------------------------------
# Kept on this box, and what the issue says
# ---------------------------------------------------------------------------

def shots_dir(base: Path) -> Path:
    return base / "screens"


def new_capture_dir(base: Path, now: float | None = None) -> Path:
    stamp = str(int(now or time.time()))
    return shots_dir(base) / stamp


def prune(base: Path, keep: str) -> None:
    """Only the newest capture is kept: it is what the issue shows."""
    root = shots_dir(base)
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.name != keep and CAPTURE_RE.match(child.name) and child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


def local_file(base: Path, capture: str, name: str) -> Path | None:
    """A kept picture by name, or None for anything that is not one."""
    if not CAPTURE_RE.match(str(capture or "")) or not SHOT_RE.match(str(name or "")):
        return None
    path = shots_dir(base) / capture / name
    return path if path.is_file() else None


KIND_WORDS = {
    "page_scrolls_sideways": "Page scrolls sideways",
    "off_the_edge": "Off the edge of the window",
    "small_target": "Too small to tap",
    "zooms_on_focus": "Field text under 16px (iOS zooms in)",
    "text_cut_off": "Text cut off with no ellipsis",
    "controls_overlap": "Controls overlap",
    "low_contrast": "Low contrast",
}


def rows(result: dict, version: str, capture: str, now: float | None = None) -> list[dict]:
    """The one rolling issue for this release, or nothing when no screen
    could be kept."""
    shots = result.get("shots") or []
    if not shots:
        return []
    problems = result.get("problems") or []
    screens = len({s["screen"] for s in shots})
    lines = [
        ("brAIn photographed its own panel on this house and measured the "
         + "layout. Every string on screen was redacted before the picture "
         + "was taken (calendar events, addresses, credentials and anything "
         + "key-shaped blanked; names aliased); images, canvases and frames "
         + "that could not be read are covered."),
        "",
        ("**For the developer:** the measured problems below are what a "
         + "script can see. Look at the pictures for what it cannot: spacing, "
         + "hierarchy, alignment, consistency, and whether each screen looks "
         + "like a modern, calm product on a phone."),
        "",
        f"Captured {time.strftime('%d %b %Y %H:%M', time.localtime(now or time.time()))}.",
        "",
    ]
    if problems:
        lines.append(f"## Measured problems ({len(problems)})")
        lines.append("")
        by_screen: dict[str, list[dict]] = {}
        for p in problems:
            by_screen.setdefault(f"{p['screen']} — {p['width']}px {p['scheme']}", []).append(p)
        for title, items in by_screen.items():
            lines.append(f"**{title}**")
            for p in items:
                what = KIND_WORDS.get(p["kind"], p["kind"])
                text = f" “{p['text']}”" if p.get("text") else ""
                lines.append(f"- {what}: `{p['el']}`{text} — {p['detail']}")
            lines.append("")
    else:
        lines += ["## Measured problems", "", "None on any screen.", ""]
    if result.get("errors"):
        lines += ["## Screens not captured", ""]
        lines += [f"- {e}" for e in result["errors"][:12]]
        lines.append("")
    gallery = [{"name": s["name"], "screen": s["screen"], "width": s["width"],
                "scheme": s["scheme"], "sha": s["sha"]} for s in shots]
    return [{
        "key": f"screens:{version}",
        "where": "Panel screens",
        "what": (f"UI audit on brAIn {version}: {len(problems)} measured "
                 f"problem{'s' if len(problems) != 1 else ''} across {screens} screens"),
        "body": "\n".join(lines),
        "gallery": gallery,
        "capture": capture,
        "ux": True,
    }]


def repo_path(version: str, name: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z.-]", "-", str(version or "dev"))[:40] or "dev"
    return f"screens/brain-{safe}/{name}"


__all__ = [
    "SCREENS", "VIEWS", "capture", "confidential_strings", "find_browser",
    "local_file", "new_capture_dir", "prune", "redact", "repo_path", "rows",
]
