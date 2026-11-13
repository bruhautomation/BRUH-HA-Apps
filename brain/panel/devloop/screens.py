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
# More of ⚙, photographed when asked for (the chat's screenshot tool, the
# Walkthrough) and not on every Screens pass: each screen there is three
# pictures under one time limit, and these are the sections a person
# opens to change who brAIn is and what it may do.
ASKED_SCREENS: list[tuple[str, str, str]] = [
    ("settings-features", "Settings › Features",
     "openSettings().then(() => showSettingsSection('features'))"),
    ("settings-permissions", "Settings › Permissions",
     "openSettings().then(() => showSettingsSection('permissions'))"),
    ("settings-personality", "Settings › Personality",
     "openSettings().then(() => showSettingsSection('personality'))"),
    ("settings-developer", "Settings › Developer",
     "openSettings().then(() => showSettingsSection('developer'))"),
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
SHOT_RE = re.compile(r"^[a-z0-9-]{1,60}-\d{3,4}-(?:light|dark)\.png$")
CAPTURE_RE = re.compile(r"^\d{10}$")

BLOCK = "▇"

# One card or section photographed on its own (the chat's screenshot of
# "this card"): named by the id the page keys it with — Morph puts a card's
# id in `data-tile` and a room's in `data-sec`, inside its shadow root. The
# picture is cropped to it wherever it is on the page, so a card far down a
# dashboard is reachable at all (the page capture starts at the top and
# stops at MAX_HEIGHT); this is the ceiling on one element instead.
FOCUS_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,120}$")
FOCUS_PRESSES = ("tap", "open")
ELEMENT_MAX_HEIGHT = 6000
FOCUS_MARGIN = 8
# Long enough to be a hold on every panel this photographs (Morph's is
# 540 ms), and short enough not to be a second press.
HOLD_S = 0.9
# How long a picture waits for the questions a card has put to Home Assistant
# (a chart's history) — bounded, so one that never answers costs this much.
ANSWERS_MAX_S = 12


class MissingElement(RuntimeError):
    """The page has nothing with the id asked for — an answer, not a fault."""


def parse_focus(screen: str, element: str = "", press: str = "") -> tuple[str, dict | None, str]:
    """``(screen, focus, why)`` from what the chat asked for: a screen name
    that may end in ``#<id>``, an ``element`` id beside it, and a press
    (``tap`` or ``open``) to make first. ``why`` is the sentence for a
    request that cannot be read; ``focus`` is None for the whole screen."""
    screen = str(screen or "").strip()
    wanted = str(element or "").strip()
    if "#" in screen:
        screen, _, after = screen.partition("#")
        screen = screen.strip()
        wanted = wanted or after.strip()
    press = str(press or "").strip().lower()
    if not wanted:
        if press:
            return screen, None, "a press needs a card or section to press (name its id)"
        return screen, None, ""
    if not FOCUS_ID_RE.match(wanted):
        return screen, None, (f"{wanted[:40]!r} is not a card or section id: use the id "
                              "the dashboard gives it (letters, digits, _ - . : @)")
    if press and press not in FOCUS_PRESSES:
        return screen, None, "press must be tap (a press) or open (held, to open it)"
    return screen, {"id": wanted, "press": press}, ""

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

# Every element in a frame, open shadow roots included: Lovelace cards and
# Morph draw inside shadow DOM, and a field, a canvas or a word that a
# plain querySelectorAll cannot see is one that is neither redacted,
# covered nor measured. `up` is the parent across a shadow boundary.
_DEEP_JS = r"""
const deepAll = (root) => {
  const out = [];
  const visit = (r) => {
    for (const el of r.querySelectorAll("*")) {
      out.push(el);
      if (el.shadowRoot) visit(el.shadowRoot);
    }
  };
  visit(root);
  return out;
};
const up = (el) => el.parentElement || (el.getRootNode && el.getRootNode().host) || null;
"""

# Collect every rendered string in this frame. Kept on `window` so the
# apply step writes back to exactly the nodes that were read.
_COLLECT_JS = r"""
(() => {
""" + _DEEP_JS + r"""
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
  const fields = document.body ? deepAll(document.body).filter((el) => el.matches("input, textarea")) : [];
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
""" + _DEEP_JS + r"""
  const own = (img) => {
    const src = img.currentSrc || img.src || "";
    if (!src || src.startsWith("data:") || src.startsWith("blob:")) return false;
    try {
      const u = new URL(src, location.href);
      return u.origin === location.origin && !u.pathname.includes("/api/")
        && /\.(svg|png|ico|webp)$/i.test(u.pathname);
    } catch (e) { return false; }
  };
  const targets = deepAll(document.documentElement).filter((el) => el.matches("canvas, video, object, embed, iframe, frame, img"))
    .filter((el) => (el.tagName === "IFRAME" || el.tagName === "FRAME")
      ? el.dataset.brainRedacted !== "1"
      : el.tagName === "IMG" ? !own(el) : true);
  let n = 0;
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const box = document.createElement("div");
    box.setAttribute("data-brain-cover", "1");
    // The words only when the box can hold them: over a 32px avatar they
    // spilled out and drew "not captured" across the name beside it.
    box.textContent = r.width >= 96 && r.height >= 20 ? "not captured" : "";
    Object.assign(box.style, {
      position: "absolute", left: (r.left + scrollX) + "px", top: (r.top + scrollY) + "px",
      width: r.width + "px", height: r.height + "px", zIndex: 2147483647,
      background: "repeating-linear-gradient(45deg,#8a8f98,#8a8f98 8px,#9aa0a8 8px,#9aa0a8 16px)",
      color: "#fff", font: "12px system-ui", display: "flex", alignItems: "center",
      justifyContent: "center", pointerEvents: "none", overflow: "hidden", boxSizing: "border-box" });
    document.body.appendChild(box);
    n++;
  }
  return n;
})()
"""

# Find a card or section by its id through every open shadow root, scroll
# it into view and say where it is now (viewport coordinates). A card's own
# tile wins over anything else carrying the same id.
_FOCUS_JS = r"""
((id) => {
  const sels = [`.tile[data-tile="${CSS.escape(id)}"]`, `[data-tile="${CSS.escape(id)}"]`,
                `section[data-sec="${CSS.escape(id)}"]`, `[data-sec="${CSS.escape(id)}"]`,
                `[data-card="${CSS.escape(id)}"]`, `#${CSS.escape(id)}`];
  const find = (root, sel) => {
    const hit = root.querySelector(sel);
    if (hit) return hit;
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) { const deep = find(el.shadowRoot, sel); if (deep) return deep; }
    }
    return null;
  };
  let el = null;
  for (const sel of sels) { el = find(document, sel); if (el) break; }
  if (!el) return null;
  el.scrollIntoView({ block: "start", inline: "nearest" });
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
})
"""

# A guarded page may open no WebSocket: the constructor refuses, the way a
# network that is down refuses, and the attempt is counted for the report.
_NO_SOCKETS_JS = r"""
(() => {
  const refuse = function () {
    (window.__brainHeldSockets = window.__brainHeldSockets || []).push(String(arguments[0] || ""));
    throw new DOMException("brAIn's screenshots open no WebSocket", "SecurityError");
  };
  refuse.CONNECTING = 0; refuse.OPEN = 1; refuse.CLOSING = 2; refuse.CLOSED = 3;
  try { Object.defineProperty(window, "WebSocket", { value: refuse, configurable: false, writable: false }); }
  catch (e) { window.WebSocket = refuse; }
})();
"""

# Home Assistant's own frontend lives on its WebSocket, so a page of it
# cannot be photographed with the socket refused. Its writes all go over
# that socket too, so instead of refusing the socket, every message the page
# SENDS is read first and one that changes anything is dropped before it
# leaves: a service call, a script, an event, a save, a create, an update,
# a delete, a reload. The page waits for an answer that never comes, which
# is a truer picture than a light that switched. Counted for the report.
_HA_SOCKET_GUARD_JS = r"""
(() => {
  const WRITE = /^(call_service|execute_script|fire_event|conversation\/process|assist_pipeline\/run|validate_config)$|\/(create|update|delete|remove|save|set|reload|enable|disable|install|uninstall|restart|start|stop|apply|run|press|clear|move|rename|reorder|import|upload|ignore|dismiss|subscribe_trigger|turn_on|turn_off|toggle)([_/]|$)/;
  const send = WebSocket.prototype.send;
  const held = (window.__brainHeldSockets = window.__brainHeldSockets || []);
  Object.defineProperty(WebSocket.prototype, "send", { configurable: false, writable: false, value: function (data) {
    try {
      const msg = typeof data === "string" ? JSON.parse(data) : null;
      const kind = msg && typeof msg.type === "string" ? msg.type : "";
      if (kind && WRITE.test(kind)) { held.push("message " + kind); return; }
    } catch (e) { /* not JSON: HA sends none, but it is passed on */ }
    return send.call(this, data);
  } });
})();
"""

# The layout faults a script can see, measured in the main frame.
_AUDIT_JS = r"""
((coarse, width) => {
""" + _DEEP_JS + r"""
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
    for (let p = up(el); p && p !== document.body; p = up(p)) {
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
  const all = deepAll(document.body).filter(shown);
  const offscreen = all.filter((el) => {
    const r = el.getBoundingClientRect();
    return (r.right > W + 1 || r.left < -1) && getComputedStyle(el).position !== "fixed"
      && !scrollerX(el);
  });
  for (const el of offscreen) {
    if (offscreen.includes(up(el))) continue;
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
    for (let p = el; p && p !== document.body; p = up(p)) {
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
  // Any CSS colour as [r, g, b, alpha 0–1], painted on a 1px canvas. A
  // computed colour is not always rgb(): Chromium answers a color-mix() as
  // oklab(0.85 0.02 0.09), and reading those numbers as 0–255 took every
  // mixed label to near black (1.52:1 on Morph's medium background).
  const cv = document.createElement("canvas");
  cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const rgb = (c) => {
    if (!c) return null;
    if (cx) {
      try {
        cx.clearRect(0, 0, 1, 1);
        cx.fillStyle = "rgba(0, 0, 0, 0)";
        cx.fillStyle = c;
        cx.fillRect(0, 0, 1, 1);
        const d = cx.getImageData(0, 0, 1, 1).data;
        return [d[0], d[1], d[2], d[3] / 255];
      } catch (e) { /* the plain reading below */ }
    }
    const m = /^rgba?\(/.test(c) && c.match(/[\d.]+/g);
    return m ? m.map(Number) : null;
  };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => {
    for (let p = el; p; p = up(p)) {
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


def _path_of(url: str) -> str:
    """A URL's path, never its query or host: what the report may say
    about a request the guard held back."""
    from urllib.parse import urlsplit  # noqa: PLC0415
    try:
        return urlsplit(str(url or "")).path[:100] or "/"
    except ValueError:
        return "?"


def request_allowed(method: str, url: str, post_data, reads) -> bool:
    """Whether the write guard lets a request through.

    A GET, a HEAD and an OPTIONS go; anything else goes only when its path
    matches one of ``reads`` — ``{"path": regex}``, optionally with
    ``"field"``/``"equals"``: the JSON body's field must hold exactly that
    value (GardenRX's one data route carries reads and writes alike). A
    body that is not JSON, or not there, does not satisfy a field."""
    verb = str(method or "").upper()
    if verb in ("GET", "HEAD", "OPTIONS"):
        return True
    path = _path_of(url)
    for rule in reads or []:
        if not isinstance(rule, dict) or not re.search(str(rule.get("path") or "$^"), path):
            continue
        field = rule.get("field")
        if not field:
            return True
        try:
            body = json.loads(post_data) if isinstance(post_data, str) else None
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get(field) == rule.get("equals"):
            return True
    return False


class CDP:
    """The few DevTools calls this needs, over one WebSocket."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.inflight: set[str] = set()
        self.answers_left: dict[str, float] = {}
        self.last_net = time.monotonic()
        # The write guard, per tab: the reads it lets through, and what it
        # held back. A tab with no entry is not guarded.
        self.guards: dict[str, list] = {}
        self.held: dict[str, list[str]] = {}
        self._tasks: set[asyncio.Task] = set()
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
            if method == "Fetch.requestPaused":
                # Answered off the reader: the answer is itself a call
                # whose reply this loop has to read.
                task = asyncio.create_task(self._paused(params, data.get("sessionId")))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                continue
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

    async def _paused(self, params: dict, session: str | None) -> None:
        """A request the write guard stopped: let a read through, fail
        anything else. Never raises — a tab that is closing is fine."""
        req = params.get("request") or {}
        rid = params.get("requestId", "")
        reads = self.guards.get(session or "")
        try:
            if reads is None or request_allowed(req.get("method", ""), req.get("url", ""),
                                                req.get("postData"), reads):
                await self.call("Fetch.continueRequest", {"requestId": rid}, session)
                return
            self.held.setdefault(session or "", []).append(
                f"{req.get('method', '?')} {_path_of(req.get('url', ''))}"[:120])
            await self.call("Fetch.failRequest", {"requestId": rid,
                                                  "errorReason": "BlockedByClient"}, session)
        except Exception:  # noqa: BLE001 — the tab went away mid-answer
            pass

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
    # Its own session, so the browser and every helper it starts are one
    # process group the panel can end together (report #355: a browser
    # left running costs CPU for as long as the add-on runs).
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True)
    port_file = Path(profile) / "DevToolsActivePort"
    try:
        for _ in range(150):
            if port_file.exists():
                lines = port_file.read_text().splitlines()
                if lines and lines[0].isdigit():
                    return proc, int(lines[0]), lines[1] if len(lines) > 1 else ""
            if proc.returncode is not None:
                break
            await asyncio.sleep(0.1)
    except BaseException:
        # Cancelled, or the port file could not be read: the caller never
        # learns about this process, so it is ended here.
        _kill_group(proc)
        raise
    _kill_group(proc)
    raise RuntimeError("Chromium did not start")


def _kill_group(proc) -> None:
    """SIGKILL the browser's whole process group, synchronously (it may be
    called while a task is being cancelled). Never raises."""
    import signal  # noqa: PLC0415
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass  # already gone: there is nothing left to end


async def _stop(proc) -> None:
    """Wait for the browser to exit, and kill its group if it will not. A
    cancellation during the wait still kills it before propagating."""
    try:
        try:
            await asyncio.wait_for(proc.wait(), 5)
            _kill_group(proc)  # helpers that outlived the browser
            return
        except asyncio.TimeoutError:
            _kill_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            log.warning("devloop screens: Chromium did not exit after it was killed")
    except BaseException:
        _kill_group(proc)
        raise


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


def own_target(url: str = PANEL_URL, screens=None) -> dict:
    """brAIn's own panel as a capture target. Not guarded: it is brAIn's
    own page on loopback, and the screens are opened by its own functions."""
    return {"key": "brain", "product": "brAIn", "url": url, "guard": False,
            "reads": [], "screens": [
                {"slug": slug, "label": label, "url": url, "script": script}
                for slug, label, script in (screens or SCREENS)]}


# brAIn's page as the phone's sidebar shows it: framed by the shell
# (`harness.shell_page`), under a phone's top safe area, in the Home
# Assistant app's full screen or not, and after a scroll or a focus — the
# header and scroll faults a picture of the page alone could never show.
SHELL_INSET_MAX = 80
SHELL_AFTER = ("", "scroll", "focus")
# The screen's script, run in the shell's frame once brAIn's page is there.
_SHELL_RUN_JS = r"""
(async (script) => {
  const until = Date.now() + 15000;
  let w = null;
  while (Date.now() < until) {
    const sh = document.querySelector('brain-shell');
    const f = sh && sh.shadowRoot && sh.shadowRoot.querySelector('iframe');
    w = f && f.getAttribute('src') ? f.contentWindow : null;
    if (w && typeof w.switchView === 'function' && w.document.readyState === 'complete') break;
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!w || typeof w.switchView !== 'function') throw new Error("brAIn's page did not open in the shell");
  await new Promise((r) => setTimeout(r, 400));
  if (script) await w.eval(script);
  return true;
})
"""
# A scroll of the page, or the first box on it focused, as a person would.
_AFTER_JS = r"""
(async (after) => {
  const sh = document.querySelector('brain-shell');
  const f = sh && sh.shadowRoot && sh.shadowRoot.querySelector('iframe');
  const w = (f && f.contentWindow) || window;
  const d = w.document;
  if (after === 'scroll') {
    for (let y = 0; y <= 600; y += 60) { w.scrollTo(0, y); await new Promise((r) => setTimeout(r, 40)); }
  } else if (after === 'focus') {
    // Where a person would type: Ask's message box (the conversation's, or
    // the list page's on a phone), the classic terminal's own input inside
    // its frame, else the first text field showing on the screen.
    const FIELD = 'textarea, input[type=text], input[type=search], input:not([type])';
    const shown = (n) => !!n && n.getClientRects().length > 0 && !n.disabled
      && n.ownerDocument.defaultView.getComputedStyle(n).visibility !== 'hidden';
    const term = d.getElementById('termFrame');
    let td = null;
    try { td = shown(term) ? term.contentDocument : null; } catch (e) { td = null; }
    const picks = [d.getElementById('chatInput'), d.querySelector('.crnewchat textarea, .crnewchat input'),
      td && td.querySelector('.xterm-helper-textarea'),
      ...d.querySelectorAll(FIELD)];
    for (const n of picks) {
      if (!n || (n.ownerDocument === d && !shown(n))) continue;
      if (n.ownerDocument !== d) term.focus();
      n.focus();
      if (n.ownerDocument.activeElement === n) break;
    }
  }
  await new Promise((r) => setTimeout(r, 700));
  return true;
})
"""
# Where the header is on the screen, and whether anything outside the page
# was left scrolled: what a picture shows, said in numbers.
_LAYOUT_JS = r"""
(() => {
  const sh = document.querySelector('brain-shell');
  const f = sh && sh.shadowRoot && sh.shadowRoot.querySelector('iframe');
  const w = (f && f.contentWindow) || window;
  const d = w.document;
  const off = f ? f.getBoundingClientRect().top : 0;
  const box = (n) => {
    if (!n || !n.getClientRects().length) return null;
    const cs = w.getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    const r = n.getBoundingClientRect();
    return { top: Math.round(r.top + off), bottom: Math.round(r.bottom + off) };
  };
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:env(safe-area-inset-top,0px);visibility:hidden';
  document.body.appendChild(probe);
  const inset = Math.round(probe.getBoundingClientRect().height);
  probe.remove();
  const row = [d.querySelector('.topbar .brandlink'), d.querySelector('#settingsBtn')].map(box).filter(Boolean);
  const outer = [];
  const se = document.scrollingElement;
  if (se && se.scrollTop) outer.push('the page, ' + Math.round(se.scrollTop) + 'px');
  const ha = document.getElementById('haouter');
  if (ha && ha.scrollTop) outer.push("Home Assistant's scroller, " + Math.round(ha.scrollTop) + 'px');
  const vv = window.visualViewport;
  if (vv && vv.offsetTop > 0.5) outer.push('the visual viewport, ' + Math.round(vv.offsetTop) + 'px');
  const first = row.length ? { top: Math.min(...row.map((r) => r.top)), bottom: Math.max(...row.map((r) => r.bottom)) } : null;
  return {
    framed: !!f, safe_area_top: inset, panel_top: sh ? Math.round(sh.getBoundingClientRect().top) : 0,
    header: box(d.querySelector('.topbar')), first_row: first, tabs: box(d.querySelector('.viewtabs')),
    tabs_slid_away: d.documentElement.classList.contains('bar-hidden'),
    focused: (() => {
      // Through any frame holding the focus (the classic terminal's), to
      // the element typed into: "textarea", or "iframe > textarea".
      const path = [];
      let a = d.activeElement;
      while (a && a !== a.ownerDocument.body) {
        path.push(a.id ? a.tagName.toLowerCase() + '#' + a.id : a.tagName.toLowerCase());
        if (a.localName !== 'iframe') break;
        try { a = a.contentDocument && a.contentDocument.activeElement; } catch (e) { break; }
      }
      return path.join(' > ');
    })(),
    outer_scroll: outer,
  };
})()
"""


def shell_screen(scr: dict, url: str = PANEL_URL, *, inset: int = 0,
                 fullscreen: bool = True, after: str = "") -> dict:
    """One of brAIn's own screens, photographed inside the shell: the page
    framed the way the sidebar frames it, the phone's top safe area
    ``inset`` px, and with the app's full screen off a strip of that height
    above the panel (the band the app keeps for its status bar). ``after``
    scrolls the page or focuses its first box before the picture."""
    inset = max(0, min(SHELL_INSET_MAX, int(inset or 0)))
    strip = 0 if fullscreen else inset
    base = url if url.endswith("/") else url + "/"
    return {**scr, "url": f"{base}devloop/harness/shell?strip={strip}",
            "script": f"({_SHELL_RUN_JS})({json.dumps(scr.get('script') or '')})",
            "inset": inset, "after": after if after in SHELL_AFTER else "", "layout": True}


def layout_problems(layout: dict, label: str, width: int, scheme: str) -> list[dict]:
    """What the header's numbers say is wrong, as problems beside the
    picture: a header not drawn, a first row under the status bar or the
    island, and Home Assistant's page left scrolled around the panel."""
    out = []
    row = layout.get("first_row") or {}
    inset = int(layout.get("safe_area_top") or 0)
    panel_top = int(layout.get("panel_top") or 0)

    def add(kind: str, detail: str) -> None:
        out.append({"screen": label, "width": width, "scheme": scheme, "kind": kind,
                    "el": ".topbar", "text": "", "detail": detail[:160]})

    if not layout.get("header"):
        add("header_hidden", "brAIn's header is not drawn")
    elif row and inset and row.get("top", 0) < inset:
        add("under_status_bar", f"the header's first row starts at {row['top']}px, "
            f"inside the {inset}px status bar and island strip")
    elif row and inset and panel_top >= inset and row.get("top", 0) - inset > 24:
        add("doubled_inset", f"the panel already starts below the {inset}px strip and the "
            f"header pads for it again (first row at {row['top']}px)")
    for what in layout.get("outer_scroll") or []:
        add("outer_scroll", f"left scrolled around the panel: {what}")
    return out


async def capture(out_dir: Path, *, confidential: list[str], aliases,
                  url: str = PANEL_URL, screens=None, views=None,
                  targets=None, own: bool = True) -> dict:
    """Photograph every screen of every target at every view into
    ``out_dir``. Answers ``{"shots": [...], "problems": [...], "errors":
    [...]}``; a screen that could not be redacted is in ``errors`` and has
    no picture. brAIn's own panel is the first target unless ``own`` is
    false; ``targets`` are the others (`screen_targets.py`)."""
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
                work = ([own_target(url, screens)] if own else []) + list(targets or [])
                for width, height, touch, scheme in (views or VIEWS):
                    for tgt in work:
                        guard = list(tgt.get("reads") or []) if tgt.get("guard") else None
                        init = str(tgt.get("init") or "")
                        sockets = bool(tgt.get("sockets"))
                        for scr in tgt.get("screens") or []:
                            label = scr["label"]
                            try:
                                shot = await _one(
                                    cdp, scr["url"], scr["slug"], label, scr.get("script") or "",
                                    width, height, touch, scheme, out_dir, confidential,
                                    aliases, guard=guard, focus=scr.get("focus"),
                                    init=init, sockets=sockets, inset=int(scr.get("inset") or 0),
                                    after=str(scr.get("after") or ""),
                                    layout=bool(scr.get("layout")))
                            except MissingElement as exc:
                                errors.append({"product": tgt.get("product", "brAIn"),
                                               "missing": True, "text": str(exc)[:200]})
                                continue
                            except Exception as exc:  # noqa: BLE001 — one screen
                                errors.append({"product": tgt.get("product", "brAIn"), "text":
                                               f"{label} at {width}px {scheme}: {exc}"[:200]})
                                continue
                            shot["product"] = tgt.get("product", "brAIn")
                            for p in shot["problems"]:
                                p["product"] = shot["product"]
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
               out_dir: Path, confidential: list[str], aliases, *,
               guard: list | None = None, focus: dict | None = None,
               init: str = "", sockets: bool = False, inset: int = 0,
               after: str = "", layout: bool = False) -> dict:
    """One screen in its own tab, so nothing a previous screen left open
    (a dialog, a scroll position) is in this picture. With ``guard`` (the
    reads it lets through) every other write is failed in the browser and
    every WebSocket is blocked, before the page is loaded — or, with
    ``sockets`` (Home Assistant's own frontend, which lives on its socket),
    the socket opens and every message that would change anything is
    dropped instead. ``init`` runs in the page before any of its own
    script (Home Assistant's sign-in, `screen_targets.ha_targets`)."""
    target = await cdp.call("Target.createTarget", {"url": "about:blank"})
    tid = target["targetId"]
    session = (await cdp.call("Target.attachToTarget",
                              {"targetId": tid, "flatten": True}))["sessionId"]
    try:
        await cdp.call("Page.enable", {}, session)
        await cdp.call("Network.enable", {}, session)
        if init:
            await cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": init}, session)
        if guard is not None:
            cdp.guards[session] = guard
            if sockets:
                await cdp.call("Page.addScriptToEvaluateOnNewDocument",
                               {"source": _HA_SOCKET_GUARD_JS}, session)
            else:
                # A WebSocket is not a request the Fetch domain sees, and
                # Chromium's blocked-URL list does not reach its handshake
                # either (the test proved it), so the constructor is replaced
                # in every frame before any of the page's own script runs.
                await cdp.call("Page.addScriptToEvaluateOnNewDocument",
                               {"source": _NO_SOCKETS_JS}, session)
                await cdp.call("Network.setBlockedURLs", {"urls": ["ws://*", "wss://*"]}, session)
            await cdp.call("Fetch.enable", {"patterns": [
                {"urlPattern": "*", "requestStage": "Request"}]}, session)
        await cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1,
            "mobile": touch}, session)
        await cdp.call("Emulation.setTouchEmulationEnabled",
                       {"enabled": True, "maxTouchPoints": 5} if touch
                       else {"enabled": False}, session)
        await cdp.call("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": scheme},
            {"name": "prefers-reduced-motion", "value": "reduce"}]}, session)
        if inset:
            # A phone's top safe area, the way the app reports it to
            # env(safe-area-inset-top). A Chromium without the override
            # photographs the page without one, and the layout says so
            # (`safe_area_top` 0).
            try:
                await cdp.call("Emulation.setSafeAreaInsetsOverride", {"insets": {
                    "top": inset, "topMax": inset, "bottom": 34, "bottomMax": 34,
                    "left": 0, "leftMax": 0, "right": 0, "rightMax": 0}}, session)
            except Exception:  # noqa: BLE001 — an older browser: no inset
                pass
        cdp.answers_left[session] = ANSWERS_MAX_S
        cdp.last_net = time.monotonic()
        await cdp.call("Page.navigate", {"url": url}, session, timeout=NAV_TIMEOUT_S)
        await cdp.settle()
        if script:
            res = await cdp.call("Runtime.evaluate", {
                "expression": f"Promise.resolve({script})", "awaitPromise": True},
                session, timeout=NAV_TIMEOUT_S)
            if res.get("exceptionDetails"):
                raise RuntimeError("the screen could not be opened")
            cdp.last_net = time.monotonic()
            await cdp.settle()
        await _answers(cdp, session)
        if focus:
            # Found and pressed BEFORE redaction, so what is redacted is the
            # page as it will be photographed — an opened card included.
            await _focus_press(cdp, session, focus, label, touch)
        else:
            await cdp.call("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"}, session)
        if after in ("scroll", "focus"):
            await cdp.call("Runtime.evaluate", {
                "expression": f"({_AFTER_JS})({json.dumps(after)})", "awaitPromise": True},
                session, timeout=NAV_TIMEOUT_S)
        await _answers(cdp, session)
        placed = None
        if layout:
            res = await cdp.call("Runtime.evaluate", {
                "expression": _LAYOUT_JS, "returnByValue": True}, session)
            placed = (res.get("result") or {}).get("value") or {}
            if after == "focus" and not placed.get("focused"):
                placed["note"] = "nothing on this screen takes typing, so nothing was focused"
        await _redact_page(cdp, session, confidential, aliases)
        if AFTER_REDACT is not None:
            await AFTER_REDACT(cdp, session)
        res = await cdp.call("Runtime.evaluate", {
            "expression": f"({_AUDIT_JS})({json.dumps(touch)}, {int(width)})",
            "returnByValue": True}, session)
        audit = (res.get("result") or {}).get("value") or {}
        if focus:
            shot_args = await _focus_clip(cdp, session, focus, label, width, height, touch)
        else:
            full = max(height, min(int(audit.get("height") or height), MAX_HEIGHT))
            await cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": full, "deviceScaleFactor": 1,
                "mobile": touch}, session)
            await asyncio.sleep(0.3)
            shot_args = {"format": "png", "captureBeyondViewport": False}
        pic = await cdp.call("Page.captureScreenshot", shot_args, session, timeout=30)
        name = f"{slug}-{width}-{scheme}.png"
        if not SHOT_RE.match(name):
            raise RuntimeError("bad screen name")
        data = base64.b64decode(pic["data"])
        (out_dir / name).write_bytes(data)
        problems = layout_problems(placed, label, width, scheme) if placed else []
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
        if guard is not None:
            res = await cdp.call("Runtime.evaluate", {
                "expression": "(window.__brainHeldSockets || []).slice(0, 6)",
                "returnByValue": True}, session)
            for url_ in (res.get("result") or {}).get("value") or []:
                cdp.held.setdefault(session, []).append(
                    url_ if str(url_).startswith("message ") else f"WebSocket {_path_of(url_)}")
        held = sorted(set(cdp.held.pop(session, [])))[:MAX_PROBLEMS_PER_KIND]
        return {"name": name, "screen": label, "width": width, "scheme": scheme,
                "sha": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "problems": problems, "held": held,
                **({"layout": placed} if placed is not None else {})}
    finally:
        cdp.guards.pop(session, None)
        cdp.held.pop(session, None)
        cdp.answers_left.pop(session, None)
        try:
            await cdp.call("Target.closeTarget", {"targetId": tid})
        except Exception:  # noqa: BLE001 — a tab that will not close dies with the browser
            pass


# A page that can draw what is not on it yet (the harness's Morph, whose
# folded rooms carry no tiles) says so with `window.__harnessReveal(id)`:
# it unfolds what holds the id and answers the id the page keys it with.
_REVEAL_JS = r"""
(async (id) => {
  const reveal = window.__harnessReveal;
  if (typeof reveal !== "function") return id;
  try { const got = await reveal(id); return typeof got === "string" && got ? got : id; }
  catch (e) { return id; }
})
"""


# A page that puts questions to Home Assistant (the harness: every chart's
# history, a sparkline's statistics) says when none is out with
# `window.__harnessIdle(ms)`. Without it, a picture taken as a room unfolds
# has charts with no lines, because their questions had only just been asked.
_ANSWERS_JS = r"""
(async (ms) => {
  const idle = window.__harnessIdle;
  if (typeof idle !== "function") return 0;
  try { return await idle(ms); } catch (e) { return 0; }
})
"""


async def _answers(cdp: CDP, session: str) -> None:
    """Wait for the page's open questions, out of ONE budget per picture
    (`ANSWERS_MAX_S` spread over every call), so a question that never
    comes back costs the bound once and not at every step."""
    left = cdp.answers_left.get(session, ANSWERS_MAX_S)
    if left <= 0:
        return
    began = time.monotonic()
    try:
        await cdp.call("Runtime.evaluate", {
            "expression": f"({_ANSWERS_JS})({int(left * 1000)})",
            "awaitPromise": True, "returnByValue": True}, session, timeout=left + 8)
    except Exception:  # noqa: BLE001 — a page that cannot say is photographed as it is
        pass
    cdp.answers_left[session] = left - (time.monotonic() - began)


async def _reveal(cdp: CDP, session: str, focus: dict) -> None:
    res = await cdp.call("Runtime.evaluate", {
        "expression": f"({_REVEAL_JS})({json.dumps(str(focus['id']))})",
        "awaitPromise": True, "returnByValue": True}, session, timeout=NAV_TIMEOUT_S)
    got = (res.get("result") or {}).get("value")
    if isinstance(got, str) and FOCUS_ID_RE.match(got):
        focus["found"] = got


async def _find(cdp: CDP, session: str, focus: dict, label: str) -> dict:
    res = await cdp.call("Runtime.evaluate", {
        "expression": f"({_FOCUS_JS})({json.dumps(str(focus.get('found') or focus['id']))})",
        "returnByValue": True}, session)
    rect = (res.get("result") or {}).get("value")
    if not isinstance(rect, dict) or not rect.get("w") or not rect.get("h"):
        raise MissingElement(f"{label} has no card or section called {focus['id']!r} "
                             "on screen")
    return rect


async def _focus_press(cdp: CDP, session: str, focus: dict, label: str,
                       touch: bool = False) -> None:
    """Scroll the element into view, and tap it or hold it open first when
    asked. The press is a real pointer down and up at its middle (a finger
    on a phone view, a mouse otherwise), so the
    page answers it exactly as it answers a finger — and the write guard
    and the socket refusal are already on the page, so whatever the press
    tries to change goes nowhere."""
    await _reveal(cdp, session, focus)
    await _answers(cdp, session)
    rect = await _find(cdp, session, focus, label)
    press = focus.get("press") or ""
    if press not in FOCUS_PRESSES:
        return
    x, y = rect["x"] + rect["w"] / 2, rect["y"] + min(rect["h"] / 2, 40)
    hold = HOLD_S if press == "open" else 0.05
    if touch:
        # A phone's press is a finger. A card built on Home Assistant's
        # action handler listens to touch alone once the device has touch
        # (a mouse press never reaches it), and Morph's pointer handlers
        # get the finger's pointer events as well.
        point = [{"x": x, "y": y, "id": 1, "radiusX": 4, "radiusY": 4, "force": 1}]
        await cdp.call("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": point}, session)
        await asyncio.sleep(hold)
        await cdp.call("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}, session)
    else:
        common = {"x": x, "y": y, "button": "left", "clickCount": 1}
        await cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, session)
        await cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", **common}, session)
        await asyncio.sleep(hold)
        await cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **common}, session)
    cdp.last_net = time.monotonic()
    await cdp.settle()
    await asyncio.sleep(0.6)          # an opening card animates into place


async def _focus_clip(cdp: CDP, session: str, focus: dict, label: str,
                      width: int, height: int, touch: bool) -> dict:
    """The screenshot arguments for one element: the window made tall
    enough to hold it, the element scrolled to its top, and the picture
    cropped to it with a little room round it."""
    rect = await _find(cdp, session, focus, label)
    tall = int(min(rect["h"] + 2 * FOCUS_MARGIN, ELEMENT_MAX_HEIGHT))
    await cdp.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": max(height, tall), "deviceScaleFactor": 1,
        "mobile": touch}, session)
    await asyncio.sleep(0.3)
    rect = await _find(cdp, session, focus, label)
    view_h = max(height, tall)
    x0 = max(0.0, rect["x"] - FOCUS_MARGIN)
    y0 = max(0.0, rect["y"] - FOCUS_MARGIN)
    x1 = min(float(width), rect["x"] + rect["w"] + FOCUS_MARGIN)
    y1 = min(float(view_h), rect["y"] + rect["h"] + FOCUS_MARGIN)
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise MissingElement(f"{label}: {focus['id']!r} has no size on screen")
    return {"format": "png", "captureBeyondViewport": False,
            "clip": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0, "scale": 1}}


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
    # The same rule, written where it can be followed from the open():
    # the joined path normalised and required to sit under the folder.
    # Redundant with the two patterns above on purpose — a guard a static
    # analyser cannot see is a guard somebody deletes.
    root = os.path.normpath(str(shots_dir(base)))
    full = os.path.normpath(os.path.join(root, str(capture), str(name)))
    if not full.startswith(root + os.sep):
        return None
    return Path(full) if os.path.isfile(full) else None


KIND_WORDS = {
    "page_scrolls_sideways": "Page scrolls sideways",
    "off_the_edge": "Off the edge of the window",
    "small_target": "Too small to tap",
    "zooms_on_focus": "Field text under 16px (iOS zooms in)",
    "text_cut_off": "Text cut off with no ellipsis",
    "controls_overlap": "Controls overlap",
    "low_contrast": "Low contrast",
    "header_hidden": "Header not drawn",
    "under_status_bar": "Header under the status bar",
    "doubled_inset": "Safe area padded twice",
    "outer_scroll": "Home Assistant's page left scrolled",
}


HARNESS_NOTE = ("The cards and the dashboard were drawn in brAIn's own preview page, "
                "handed this house's real states through a read-only proxy: anything "
                "they would have read from Home Assistant's frontend itself (its theme, "
                "a hosted Lovelace card) is a stand-in there, and a hosted card is "
                "drawn as a labelled box.")


def rows(result: dict, version: str, capture: str, now: float | None = None,
         versions: dict | None = None, unreached: dict | None = None) -> list[dict]:
    """One rolling issue per product per release: brAIn's own panel, and
    each other BRUH add-on whose screens were captured. Nothing for a
    product with no picture kept. ``versions`` is product → installed
    version for the other add-ons; ``unreached`` is product → why it was
    not photographed, said in brAIn's own issue."""
    shots = result.get("shots") or []
    by_product: dict[str, list[dict]] = {}
    for s in shots:
        by_product.setdefault(s.get("product") or "brAIn", []).append(s)
    out = []
    for product, pics in by_product.items():
        problems = [p for p in result.get("problems") or []
                    if (p.get("product") or "brAIn") == product]
        errors = [e for e in result.get("errors") or []
                  if (e.get("product") if isinstance(e, dict) else "brAIn") == product]
        held = sorted({h for s in pics for h in s.get("held") or []})
        own = product == "brAIn"
        ver = version if own else str((versions or {}).get(product) or "?")
        out.append(_product_row(product, ver, pics, problems, errors, held, capture, now,
                                unreached if own else None))
    return out


def _product_row(product: str, version: str, shots: list[dict], problems: list[dict],
                 errors: list, held: list[str], capture: str, now: float | None,
                 unreached: dict | None) -> dict:
    own = product == "brAIn"
    screens = len({s["screen"] for s in shots})
    subject = "its own panel" if own else f"{product}'s screens"
    lines = [
        (f"brAIn photographed {subject} on this house and measured the "
         + "layout. Every string on screen was redacted before the picture "
         + "was taken (calendar events, addresses, credentials and anything "
         + "key-shaped blanked; names aliased); images, canvases and frames "
         + "that could not be read are covered."),
        "",
    ]
    if not own:
        lines += [("Nothing photographed could change anything: every request "
                   + "that was not a read was failed in the browser and every "
                   + "WebSocket was blocked, so a part of a screen that needs "
                   + "one may look empty or say it could not connect."), ""]
        if any(s["screen"].endswith(("Lovelace card", "Lovelace cards", "Dashboard"))
               for s in shots):
            lines += [HARNESS_NOTE, ""]
    lines += [
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
    if held:
        lines += ["## Requests held back while photographing", ""]
        lines += [f"- `{h}`" for h in held[:12]]
        lines.append("")
    if errors:
        lines += ["## Screens not captured", ""]
        lines += [f"- {e['text'] if isinstance(e, dict) else e}" for e in errors[:12]]
        lines.append("")
    if unreached:
        lines += ["## Other BRUH add-ons not photographed", ""]
        lines += [f"- {name}: {why}" for name, why in sorted(unreached.items())]
        lines.append("")
    gallery = [{"name": s["name"], "screen": s["screen"], "width": s["width"],
                "scheme": s["scheme"], "sha": s["sha"]} for s in shots]
    row = {
        "key": f"screens:{version}" if own else f"screens:{product}:{version}",
        "where": "Panel screens" if own else f"{product} · Screens",
        "what": (f"UI audit on {product} {version}: {len(problems)} measured "
                 f"problem{'s' if len(problems) != 1 else ''} across {screens} screens"),
        "body": "\n".join(lines),
        "gallery": gallery,
        "capture": capture,
        "ux": True,
    }
    if not own:
        row["product"] = product
        row["product_version"] = version
    return row


def repo_path(version: str, name: str, product: str = "brAIn") -> str:
    safe = re.sub(r"[^0-9A-Za-z.-]", "-", str(version or "dev"))[:40] or "dev"
    who = re.sub(r"[^0-9a-z-]", "-", str(product or "brAIn").lower())[:40] or "brain"
    return f"screens/{who}-{safe}/{name}"


__all__ = [
    "SCREENS", "VIEWS", "capture", "confidential_strings", "find_browser",
    "own_target", "request_allowed", "local_file", "new_capture_dir", "prune", "redact", "repo_path", "rows",
]
