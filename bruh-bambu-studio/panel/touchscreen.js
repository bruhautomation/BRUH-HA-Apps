// The Studio tab on a touch screen. Plain script, no build step.
//
// On a phone the stock noVNC page (`novnc/vnc.html` in an iframe) shrinks
// Bambu Studio's 1600x900 screen to the phone's width and stops there: no
// zoom, no pan, no right click, no wheel and no keyboard. So on a coarse
// pointer this page hosts noVNC's own RFB object itself, on a container it
// sizes, and puts a gesture layer over it:
//
//   one finger tap ........ left click where the finger was
//   one finger hold ....... right click there
//   one finger drag ....... depends on the mode: Move pans the screen, Drag
//                           holds the left button down (sliders, the 3D
//                           view), Scroll turns the mouse wheel
//   two fingers ........... pinch to zoom, centred on the fingers, and move
//
// Zoom is noVNC's own scaling, not a CSS transform: the container is sized
// to the screen times the zoom and RFB scales its canvas to fit it. That is
// what keeps a click honest — noVNC maps a mouse event's client position
// through the canvas's own bounds and its own scale, so a synthetic event at
// the point a finger touched lands on the pixel under that finger, at any
// zoom, with no arithmetic of ours in between. Panning is a translate on the
// container, which getBoundingClientRect sees too.
//
// A pointer: fine device never comes here: the desktop keeps the iframe.
"use strict";

(function () {
  const ZOOM_MAX = 2;          // CSS pixels per screen pixel, at most
  const TAP_SLOP = 10;         // how far a finger may wander and still tap
  const HOLD_MS = 550;         // a still finger this long is a right click
  const WHEEL_PX = 24;         // finger travel per wheel step
  const WHEEL_DELTA = 60;      // noVNC turns 50 px of wheel into one step
  const RETRY_MS = 3000;

  const ts = {
    rfb: null, url: "", wanted: false, connected: false, retry: null,
    z: 0, ox: 0, oy: 0, fit: true, fbW: 0, fbH: 0,
    mode: "pan", keyboard: false, keysym: null, keys: null,
    pointers: new Map(), gesture: null,
  };
  window.TouchScreen = ts;

  const q = (sel) => document.querySelector(sel);

  ts.wantedHere = () => {
    try { return window.matchMedia("(pointer: coarse)").matches; } catch (_) { return false; }
  };

  function wsUrl() {
    const dir = location.pathname.replace(/[^/]*$/, "");
    return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${dir}websockify`;
  }

  function say(text) {
    const s = q("#tsState");
    s.textContent = text || "";
    s.hidden = !text;
  }

  // ------------------------------------------------------------- connect ---
  ts.connect = async function () {
    ts.wanted = true;
    q("#touchScreen").hidden = false;
    sizePort();
    if (ts.rfb) return;
    clearTimeout(ts.retry);
    say("Connecting to Bambu Studio…");
    let RFB;
    try {
      const base = new URL("novnc/core/", location.href);
      [RFB, ts.keysym, ts.keys] = await Promise.all([
        import(new URL("rfb.js", base)).then((m) => m.default),
        import(new URL("input/keysymdef.js", base)).then((m) => m.default),
        import(new URL("input/keysym.js", base)).then((m) => m.default),
      ]);
    } catch (e) {
      say(`The screen viewer could not load: ${e.message}`);
      return;
    }
    if (!ts.wanted || ts.rfb) return;
    const host = q("#tsVnc");
    host.replaceChildren();
    let rfb;
    try {
      rfb = new RFB(host, wsUrl(), { wsProtocols: ["binary"], shared: true });
    } catch (e) {
      say(`Could not reach the screen: ${e.message}`);
      ts.retry = setTimeout(() => ts.wanted && ts.connect(), RETRY_MS);
      return;
    }
    ts.rfb = rfb;
    rfb.viewOnly = false;
    rfb.clipViewport = false;
    rfb.resizeSession = false;
    rfb.scaleViewport = true;
    rfb.showDotCursor = true;
    rfb.focusOnClick = false;
    rfb.background = "#000";
    rfb.addEventListener("connect", () => {
      if (ts.rfb !== rfb) return;
      ts.connected = true;
      say("");
      watchCanvas();
    });
    rfb.addEventListener("disconnect", () => {
      if (ts.rfb !== rfb) return;
      ts.connected = false;
      ts.rfb = null;
      if (!ts.wanted) return;
      say("The screen closed. Connecting again…");
      ts.retry = setTimeout(() => ts.wanted && ts.connect(), RETRY_MS);
    });
    watchCanvas();
  };

  ts.disconnect = function () {
    ts.wanted = false;
    clearTimeout(ts.retry);
    const rfb = ts.rfb;
    ts.rfb = null;
    ts.connected = false;
    if (rfb) { try { rfb.disconnect(); } catch (_) { /* already closed */ } }
  };

  ts.hide = function () {
    ts.disconnect();
    q("#touchScreen").hidden = true;
  };

  // The canvas's width and height ARE the remote screen's size (noVNC sets
  // them on every framebuffer resize), so they are read off the element.
  let canvasWatch = null;
  function watchCanvas() {
    const canvas = q("#tsVnc canvas");
    if (!canvas) return;
    if (canvasWatch) canvasWatch.disconnect();
    canvasWatch = new MutationObserver(screenSize);
    canvasWatch.observe(canvas, { attributes: true, attributeFilter: ["width", "height"] });
    screenSize();
  }

  function screenSize() {
    const canvas = q("#tsVnc canvas");
    if (!canvas || !canvas.width || !canvas.height) return;
    if (canvas.width === ts.fbW && canvas.height === ts.fbH) return;
    ts.fbW = canvas.width;
    ts.fbH = canvas.height;
    ts.fitScreen();
  }

  // -------------------------------------------------------------- layout ---
  function sizePort() {
    const port = q("#tsPort");
    const top = port.getBoundingClientRect().top;
    port.style.height = `${Math.max(180, Math.floor(window.innerHeight - top))}px`;
  }

  function portSize() {
    const r = q("#tsPort").getBoundingClientRect();
    return { w: r.width, h: r.height };
  }

  function zoomRange() {
    const { w } = portSize();
    const fit = ts.fbW ? w / ts.fbW : 1;
    return { min: fit, max: Math.max(fit, ZOOM_MAX) };
  }

  // A screen narrower than the port is centred; one shorter than it sits at
  // the top, under the controls, rather than floating in the middle.
  function clampOffset(o, content, room, centre = true) {
    if (content <= room) return centre ? (room - content) / 2 : 0;
    return Math.min(0, Math.max(room - content, o));
  }

  function layout() {
    if (!ts.fbW) return;
    const { w, h } = portSize();
    const { min, max } = zoomRange();
    if (ts.fit || !ts.z) ts.z = min;
    ts.z = Math.min(max, Math.max(min, ts.z));
    ts.fit = Math.abs(ts.z - min) < 1e-6;
    ts.ox = clampOffset(ts.ox, ts.fbW * ts.z, w);
    ts.oy = clampOffset(ts.oy, ts.fbH * ts.z, h, false);
    const host = q("#tsVnc");
    host.style.width = `${ts.fbW * ts.z}px`;
    host.style.height = `${ts.fbH * ts.z}px`;
    host.style.transform = `translate(${ts.ox}px, ${ts.oy}px)`;
    const pct = q("#tsZoom");
    if (pct) pct.textContent = `${Math.round(ts.z * 100)}%`;
  }

  ts.fitScreen = function () {
    ts.fit = true;
    ts.z = 0;
    layout();
    // The top of the screen first: menus and the toolbar are up there.
    ts.ox = 0;
    ts.oy = 0;
    layout();
  };

  // Zoom to `z`, keeping the screen point that was under (fx, fy) in the
  // port under (cx, cy) — the fingers' centre, which may itself have moved.
  function zoomAbout(z, fx, fy, cx, cy) {
    ts.fit = false;
    const { min, max } = zoomRange();
    ts.z = Math.min(max, Math.max(min, z));
    ts.ox = cx - fx * ts.z;
    ts.oy = cy - fy * ts.z;
    layout();
  }

  // --------------------------------------------------------------- mouse ---
  // Synthetic mouse events on noVNC's canvas, at the client point a finger
  // touched. After a mousedown noVNC "captures" the mouse behind a full
  // screen element; a real mouseup lands on that element, which hands it to
  // the canvas and lets the capture go — so a move or release is sent there
  // too, or the capture would cover the page for good.
  function target(type) {
    const capture = document.getElementById("noVNC_mouse_capture_elem");
    if (type !== "mousedown" && capture && capture.style.display !== "none") return capture;
    return q("#tsVnc canvas");
  }

  function mouse(type, x, y, button = 0) {
    const el = target(type);
    if (!el || !ts.rfb) return;
    const buttons = type === "mouseup" ? 0 : (type === "mousemove" ? ts.held : 1 << button);
    el.dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window,
      clientX: x, clientY: y, button, buttons,
    }));
  }
  ts.held = 0;

  function click(x, y, button) {
    mouse("mousemove", x, y);
    mouse("mousedown", x, y, button);
    mouse("mouseup", x, y, button);
    mark(x, y, button === 2);
  }

  function wheel(x, y, steps) {
    const canvas = q("#tsVnc canvas");
    if (!canvas || !ts.rfb) return;
    canvas.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true, cancelable: true, view: window,
      clientX: x, clientY: y, deltaMode: 0, deltaY: steps * WHEEL_DELTA,
    }));
  }

  // Where a click landed, briefly: on glass there is no pointer to watch.
  function mark(x, y, right) {
    const port = q("#tsPort").getBoundingClientRect();
    const dot = document.createElement("div");
    dot.className = right ? "tsmark right" : "tsmark";
    dot.style.left = `${x - port.left}px`;
    dot.style.top = `${y - port.top}px`;
    q("#tsPort").append(dot);
    setTimeout(() => dot.remove(), 450);
  }

  // ------------------------------------------------------------ gestures ---
  function two() {
    const [a, b] = [...ts.pointers.values()];
    return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) || 1 };
  }

  function endGesture() {
    const g = ts.gesture;
    if (!g) return;
    clearTimeout(g.hold);
    if (g.kind === "drag") { mouse("mouseup", g.lx, g.ly, 0); ts.held = 0; }
  }

  function onDown(e) {
    if (e.pointerType === "mouse") return forwardMouse(e);
    e.preventDefault();
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) { /* fine */ }
    ts.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ts.pointers.size === 1) {
      const g = { kind: "pending", sx: e.clientX, sy: e.clientY, lx: e.clientX, ly: e.clientY, acc: 0 };
      g.hold = setTimeout(() => {
        if (ts.gesture !== g || g.kind !== "pending") return;
        g.kind = "done";
        if (navigator.vibrate) { try { navigator.vibrate(15); } catch (_) { /* fine */ } }
        click(g.sx, g.sy, 2);
      }, HOLD_MS);
      ts.gesture = g;
    } else if (ts.pointers.size === 2) {
      endGesture();
      const port = q("#tsPort").getBoundingClientRect();
      const p = two();
      const cx = p.cx - port.left, cy = p.cy - port.top;
      ts.gesture = { kind: "pinch", d0: p.d, z0: ts.z, fx: (cx - ts.ox) / ts.z, fy: (cy - ts.oy) / ts.z };
    } else if (ts.gesture) {
      ts.gesture.kind = ts.gesture.kind === "pinch" ? "pinch" : "after";
    }
  }

  function onMove(e) {
    if (e.pointerType === "mouse") return forwardMouse(e);
    const p = ts.pointers.get(e.pointerId);
    const g = ts.gesture;
    if (!p || !g) return;
    e.preventDefault();
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (g.kind === "pinch" && ts.pointers.size >= 2) {
      const port = q("#tsPort").getBoundingClientRect();
      const t = two();
      zoomAbout(g.z0 * (t.d / g.d0), g.fx, g.fy, t.cx - port.left, t.cy - port.top);
      return;
    }
    if (g.kind === "pending") {
      if (Math.hypot(e.clientX - g.sx, e.clientY - g.sy) <= TAP_SLOP) return;
      clearTimeout(g.hold);
      g.kind = ts.mode;
      if (g.kind === "drag") {
        mouse("mousemove", g.sx, g.sy);
        ts.held = 1;
        mouse("mousedown", g.sx, g.sy, 0);
      }
    }
    if (g.kind === "pan") {
      ts.fit = false;
      ts.ox += dx; ts.oy += dy;
      layout();
    } else if (g.kind === "drag") {
      mouse("mousemove", e.clientX, e.clientY);
    } else if (g.kind === "scroll") {
      // Finger up scrolls the content down, as it does everywhere on a phone.
      g.acc -= dy;
      const steps = Math.trunc(g.acc / WHEEL_PX);
      if (steps) { g.acc -= steps * WHEEL_PX; wheel(g.sx, g.sy, steps); }
    }
    g.lx = e.clientX; g.ly = e.clientY;
  }

  function onUp(e) {
    if (e.pointerType === "mouse") return forwardMouse(e);
    e.preventDefault();
    ts.pointers.delete(e.pointerId);
    const g = ts.gesture;
    if (!g) return;
    if (ts.pointers.size > 0) {
      // A pinch losing one finger is not the start of a tap or a pan.
      if (g.kind === "pinch" || g.kind === "after") g.kind = "after";
      return;
    }
    clearTimeout(g.hold);
    if (g.kind === "pending" && e.type === "pointerup") click(g.sx, g.sy, 0);
    else if (g.kind === "drag") { mouse("mouseup", e.clientX, e.clientY, 0); ts.held = 0; }
    ts.gesture = null;
    // Clicking the screen while typing must not put the keyboard away.
    if (ts.keyboard) { try { q("#tsType").focus({ preventScroll: true }); } catch (_) { /* fine */ } }
  }

  // A mouse plugged into a tablet clicks where it points, like a desktop.
  function forwardMouse(e) {
    const type = { pointerdown: "mousedown", pointermove: "mousemove", pointerup: "mouseup" }[e.type];
    if (!type) return;
    e.preventDefault();
    if (type === "mousedown") ts.held |= 1 << e.button;
    if (type === "mouseup") ts.held &= ~(1 << e.button);
    mouse(type, e.clientX, e.clientY, Math.max(0, e.button));
  }

  // ------------------------------------------------------------ keyboard ---
  // The phone's keyboard needs a real text box to type into. It holds one
  // space so that Backspace on an "empty" box still makes an input event on
  // every keyboard, and whatever arrives after that space is sent as keys.
  const SEED = " ";

  function key(sym) { if (ts.rfb && sym) ts.rfb.sendKey(sym, null); }

  function sendText(text) {
    for (const ch of text) {
      if (ch === "\n") { key(ts.keys && ts.keys.XK_Return); continue; }
      const sym = ts.keysym ? ts.keysym.lookup(ch.codePointAt(0)) : null;
      key(sym);
    }
  }

  ts.backspace = () => key(ts.keys && ts.keys.XK_BackSpace);
  ts.enter = () => key(ts.keys && ts.keys.XK_Return);

  function onInput(e) {
    const box = e.target;
    const v = box.value;
    if (!v.startsWith(SEED) || v.length < SEED.length) {
      // The seed went: that is a Backspace (or the whole box was replaced).
      if (v.length < SEED.length) ts.backspace();
      else sendText(v);
    } else {
      sendText(v.slice(SEED.length));
    }
    box.value = SEED;
  }

  function onKeyDown(e) {
    const named = { Enter: "XK_Return", Tab: "XK_Tab", Escape: "XK_Escape",
      ArrowUp: "XK_Up", ArrowDown: "XK_Down", ArrowLeft: "XK_Left", ArrowRight: "XK_Right" }[e.key];
    if (!named) return;
    e.preventDefault();
    key(ts.keys && ts.keys[named]);
  }

  ts.openKeyboard = function () {
    ts.keyboard = true;
    const row = q("#tsKeyRow");
    row.hidden = false;
    q("#tsKeys").setAttribute("aria-pressed", "true");
    const box = q("#tsType");
    box.value = SEED;
    box.focus();
    try { box.setSelectionRange(SEED.length, SEED.length); } catch (_) { /* fine */ }
    sizePort();
    layout();
  };

  ts.closeKeyboard = function () {
    ts.keyboard = false;
    q("#tsKeyRow").hidden = true;
    q("#tsKeys").setAttribute("aria-pressed", "false");
    q("#tsType").blur();
    sizePort();
    layout();
  };

  ts.setMode = function (mode) {
    ts.mode = mode;
    document.querySelectorAll("#tsModes [data-mode]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
  };

  // ---------------------------------------------------------------- wire ---
  function wire() {
    const layer = q("#tsLayer");
    if (!layer) return;
    layer.addEventListener("pointerdown", onDown);
    layer.addEventListener("pointermove", onMove);
    layer.addEventListener("pointerup", onUp);
    layer.addEventListener("pointercancel", onUp);
    layer.addEventListener("contextmenu", (e) => e.preventDefault());
    document.querySelectorAll("#tsModes [data-mode]").forEach((b) =>
      b.addEventListener("click", () => ts.setMode(b.dataset.mode)));
    q("#tsFit").addEventListener("click", ts.fitScreen);
    q("#tsKeys").addEventListener("click", () => (ts.keyboard ? ts.closeKeyboard() : ts.openKeyboard()));
    q("#tsDone").addEventListener("click", ts.closeKeyboard);
    // pointerdown keeps the text box focused, so the keyboard stays up.
    for (const id of ["#tsBack", "#tsEnter"]) {
      q(id).addEventListener("pointerdown", (e) => e.preventDefault());
    }
    q("#tsBack").addEventListener("click", ts.backspace);
    q("#tsEnter").addEventListener("click", ts.enter);
    const box = q("#tsType");
    box.addEventListener("input", onInput);
    box.addEventListener("keydown", onKeyDown);
    const relayout = () => { if (!q("#touchScreen").hidden) { sizePort(); layout(); } };
    window.addEventListener("resize", relayout);
    if (window.visualViewport) window.visualViewport.addEventListener("resize", relayout);
    if (window.ResizeObserver) new ResizeObserver(() => layout()).observe(q("#tsPort"));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
