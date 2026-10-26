// BRUH Bambu Studio panel. Plain script, no build step.
//
// Every URL here is RELATIVE: ingress mounts the panel under
// /api/hassio_ingress/<token>/, so "/api/state" would be a request to Home
// Assistant's own root. BRUH Print shipped that bug once.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { data: null, files: [], view: "studio", busy: new Set(), armed: null };

function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.body = JSON.stringify(opts.json);
    init.headers["Content-Type"] = "application/json";
  }
  return fetch(path.replace(/^\//, ""), init).then(async (r) => {
    let body = {};
    try { body = await r.json(); } catch (_) { body = {}; }
    if (!r.ok || body.ok === false) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  });
}

function toast(text, bad = false) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.toggle("bad", bad);
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.hidden = true; }, bad ? 7000 : 3500);
}

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function duration(minutes) {
  if (minutes == null) return "";
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return h ? `${h} h ${m} min` : `${m} min`;
}

// ---------------------------------------------------------------- tabs ---
function show(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== view; });
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", t.dataset.view === view));
  document.body.classList.toggle("studio-open", view === "studio");
  document.body.classList.toggle("wide", view === "design");
  try { localStorage.setItem("bambu.view", view); } catch (_) { /* storage may be refused in an iframe */ }
  if (view === "files") loadFiles();
  if (view === "printers" && state.data) renderPrinters();
  if (view === "studio") connectScreen();
}

// -------------------------------------------------------------- studio ---
function screenUrl() {
  // noVNC builds its websocket as host + "/" + path, so the path carries
  // the ingress prefix this page was served under.
  const base = location.pathname.replace(/^\//, "").replace(/[^/]*$/, "");
  const q = new URLSearchParams({ autoconnect: "1", resize: "scale", reconnect: "1",
    reconnect_delay: "3000", path: `${base}websockify`, show_dot: "1" });
  return `novnc/vnc.html?${q}`;
}

// A touch screen gets noVNC on this page with zoom, pan and a keyboard
// (touchscreen.js); a mouse keeps the stock noVNC page in the frame.
function touchScreen() {
  return window.TouchScreen && window.TouchScreen.wantedHere() ? window.TouchScreen : null;
}

function connectScreen() {
  const frame = $("#screen");
  const s = state.data && state.data.studio;
  const touch = touchScreen();
  if (touch) {
    frame.hidden = true;
    if (s && s.running) touch.connect();
    return;
  }
  if (s && s.running && !frame.getAttribute("src")) frame.src = screenUrl();
}

function renderStudio() {
  const s = state.data.studio;
  const box = $("#studioStatus");
  const inst = s.install || {};
  box.replaceChildren();
  let text = "";
  const buttons = [];
  if (["resolving", "downloading", "extracting"].includes(inst.phase)) {
    const pct = inst.progress != null ? ` ${inst.progress}%` : "";
    text = { resolving: "Looking up the Bambu Studio release…",
      downloading: `Downloading Bambu Studio ${inst.version || ""}…${pct}`,
      extracting: "Unpacking Bambu Studio…" }[inst.phase];
  } else if (!s.installed) {
    text = inst.phase === "failed" ? `Bambu Studio could not be installed: ${inst.error}`
      : "Bambu Studio is not installed yet.";
    buttons.push(el("button", { class: "primary", onclick: () => install(false) }, "Install"));
  } else if (!s.running && s.missing_libraries && s.missing_libraries.length) {
    text = `Bambu Studio ${s.version || ""} needs system libraries this add-on does not have yet: `
      + `${s.missing_libraries.join(", ")}. Update BRUH Bambu Studio, or pin an older Bambu Studio `
      + "version in the add-on's Configuration tab.";
  } else if (!s.running && s.paused_for) {
    text = `Bambu Studio is closed while a print is ${s.paused_for}; it opens again when that is done.`;
  } else if (!s.running) {
    text = s.wanted ? (s.next_start_in ? `Bambu Studio closed; starting it again in ${s.next_start_in} s.`
      : "Starting Bambu Studio…") : "Bambu Studio is stopped.";
    buttons.push(el("button", { class: "primary", onclick: () => studio("restart") }, "Start"));
  }
  if (inst.phase === "failed" && s.installed) text = inst.error;
  box.hidden = !text;
  if (text) {
    box.append(el("p", {}, text));
    if (s.log_tail && s.log_tail.length && !s.running && s.installed) {
      box.append(el("details", {}, el("summary", {}, "What it last printed"),
        el("pre", {}, s.log_tail.join("\n"))));
    }
    if (buttons.length) box.append(el("div", { class: "row" }, buttons));
  }
  // No frame while there is nothing to show: a black rectangle under the
  // install notice reads as a broken screen.
  $("#screen").hidden = !s.running || !!touchScreen();
  if (!s.running) {
    $("#screen").removeAttribute("src");
    if (touchScreen()) touchScreen().hide();
  }
  if (state.view === "studio") connectScreen();
}

async function install(force) {
  try {
    await api("api/studio/install", { json: { force } });
    toast("Downloading Bambu Studio — this takes a few minutes.");
    refresh();
  } catch (e) { toast(e.message, true); }
}

async function studio(action, file) {
  try {
    await api(`api/studio/${action}`, { json: file ? { file } : {} });
    $("#screen").removeAttribute("src");
    if (touchScreen()) touchScreen().disconnect();
    if (action === "open") { show("studio"); toast("Opening it in Bambu Studio…"); }
    setTimeout(refresh, 1500);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------ printers ---
async function command(printer, action, extra = {}) {
  const key = `${printer.id}:${action}`;
  if (state.busy.has(key)) return;
  state.busy.add(key);
  try {
    const r = await api("api/printer/command", { json: { printer: printer.id, action, ...extra } });
    const said = { refresh: "Asked for a full report.", reconnect: "Reconnecting…",
      ams_refresh: "Reading the tray again…" }[action];
    toast(r.note || said || `${printer.name}: ${action} sent.`, Boolean(r.note));
    refresh();
  } catch (e) { toast(e.message, true); } finally { state.busy.delete(key); }
}

// Icons are Material Design paths (Apache 2.0), drawn inline so the panel
// needs nothing from the internet. Static strings only: nothing a printer
// or a person typed ever reaches innerHTML.
const ICONS = {
  light: "M12,2A7,7 0 0,0 5,9C5,11.38 6.19,13.47 8,14.74V17A1,1 0 0,0 9,18H15A1,1 0 0,0 16,17V14.74C17.81,13.47 19,11.38 19,9A7,7 0 0,0 12,2M9,21A1,1 0 0,0 10,22H14A1,1 0 0,0 15,21V20H9V21Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  full: "M5,5H10V7H7V10H5V5M14,5H19V10H17V7H14V5M17,14H19V19H14V17H17V14M10,17V19H5V14H7V17H10Z",
  refresh: "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  stop: "M18,18H6V6H18V18Z",
  nozzle: "M15 13V5A3 3 0 0 0 9 5V13A5 5 0 1 0 15 13M12 4A1 1 0 0 1 13 5V8H11V5A1 1 0 0 1 12 4Z",
  bed: "M3 17H21V19H3V17M5 5H7V15H5V5M9 5H11V15H9V5M13 5H15V15H13V5M17 5H19V15H17V5Z",
  chamber: "M21,16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V7.5C3,7.12 3.21,6.79 3.53,6.62L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.79,6.79 21,7.12 21,7.5V16.5M12,4.15L6.04,7.5L12,10.85L17.96,7.5L12,4.15M5,15.91L11,19.29V12.58L5,9.21V15.91M19,15.91V9.21L13,12.58V19.29L19,15.91Z",
  fan: "M12,11A1,1 0 0,0 11,12A1,1 0 0,0 12,13A1,1 0 0,0 13,12A1,1 0 0,0 12,11M12.5,2C17,2 17.11,5.57 14.75,6.75C13.76,7.24 13.32,8.29 13.13,9.22C13.61,9.42 14.03,9.73 14.35,10.13C18.05,8.13 22.03,8.92 22.03,12.5C22.03,17 18.46,17.1 17.28,14.73C16.78,13.74 15.72,13.3 14.79,13.11C14.59,13.59 14.28,14 13.88,14.34C15.87,18.03 15.08,22 11.5,22C7,22 6.91,18.42 9.27,17.24C10.25,16.75 10.69,15.71 10.89,14.79C10.4,14.59 9.97,14.27 9.65,13.87C5.96,15.85 2,15.07 2,11.5C2,7 5.56,6.89 6.74,9.26C7.24,10.25 8.29,10.68 9.22,10.87C9.41,10.39 9.73,9.97 10.14,9.65C8.15,5.96 8.94,2 12.5,2Z",
  speed: "M12,16A3,3 0 0,1 9,13C9,11.88 9.61,10.9 10.5,10.39L20.21,4.77L14.68,14.35C14.18,15.33 13.17,16 12,16M12,3C13.81,3 15.5,3.5 16.97,4.32L14.87,5.53C14,5.19 13,5 12,5A8,8 0 0,0 4,13C4,15.21 4.89,17.21 6.34,18.65H6.35C6.74,19.04 6.74,19.67 6.35,20.06C5.96,20.45 5.32,20.45 4.93,20.07V20.07C3.12,18.26 2,15.76 2,13A10,10 0 0,1 12,3M22,13C22,15.76 20.88,18.26 19.07,20.07V20.07C18.68,20.45 18.05,20.45 17.66,20.06C17.27,19.67 17.27,19.04 17.66,18.65V18.65C19.11,17.2 20,15.21 20,13C20,12 19.81,11 19.46,10.1L20.67,8C21.5,9.5 22,11.18 22,13Z",
  drop: "M12,20A6,6 0 0,1 6,14C6,10 12,3.25 12,3.25C12,3.25 18,10 18,14A6,6 0 0,1 12,20Z",
  shield: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M10,17L6,13L7.41,11.59L10,14.17L16.59,7.58L18,9L10,17Z",
  shieldAlert: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M11,7H13V13H11V7M11,15H13V17H11V15Z",
  eye: "M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17M12,4.5C7,4.5 2.73,7.61 1,12C2.73,16.39 7,19.5 12,19.5C17,19.5 21.27,16.39 23,12C21.27,7.61 17,4.5 12,4.5Z",
  link: "M3.9,12C3.9,10.29 5.29,8.9 7,8.9H11V7H7A5,5 0 0,0 2,12A5,5 0 0,0 7,17H11V15.1H7C5.29,15.1 3.9,13.71 3.9,12M8,13H16V11H8V13M17,7H13V8.9H17C18.71,8.9 20.1,10.29 20.1,12C20.1,13.71 18.71,15.1 17,15.1H13V17H17A5,5 0 0,0 22,12A5,5 0 0,0 17,7Z",
};

function icon(name) {
  const span = el("span", { class: "ic", "aria-hidden": "true" });
  span.innerHTML = `<svg viewBox="0 0 24 24"><path d="${ICONS[name]}"/></svg>`;
  return span;
}

function temp(now, target) {
  if (now == null) return "–";
  return target ? `${Math.round(now)}°` : `${Math.round(now)}°`;
}

function clock(minutes) {
  if (minutes == null || minutes <= 0) return "";
  return new Date(Date.now() + minutes * 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const STATE_WORDS = { idle: "Idle", prepare: "Preparing", running: "Printing", pause: "Paused",
  finish: "Finished", failed: "Failed", slicing: "Slicing", offline: "Offline", connecting: "Connecting" };

function stateTone(p) {
  if (!p.online) return "bad";
  if (p.state === "failed" || p.error_code) return "bad";
  if (p.state === "pause") return "warn";
  if (p.printing) return "live";
  if (p.state === "finish") return "done";
  return "";
}

// The camera: one <img> per printer that outlives every redraw (a redraw
// every four seconds would otherwise restart it). Each frame is fetched and
// decoded off screen, and only a frame that decoded is swapped in: setting
// the visible image's src blanked it while the next frame loaded, which
// flashed the feed every second or two, and a frame that failed showed a
// broken image.
const cams = {};

function cameraNode(p) {
  let cam = cams[p.id];
  if (!cam) {
    // Two pictures, one in front and one behind: a frame is loaded and
    // decoded into the one behind, then the two change places, so the one on
    // screen is never mid-load. Setting src on the visible picture, even to a
    // URL already decoded elsewhere, leaves it incomplete for a moment.
    const img = el("img", { class: "camimg", alt: `${p.name}'s camera`, decoding: "async" });
    const back = el("img", { class: "camback", alt: "", "aria-hidden": "true", decoding: "async" });
    const note = el("p", { class: "camnote" }, "Starting the camera…");
    const node = el("div", { class: "cam" }, img, back, note);
    cam = cams[p.id] = { node, img, back, note, on: true, timer: null, loading: false, failures: 0, url: null };
  }
  cam.printer = p;
  return cam;
}

function scheduleFrame(id, delay) {
  const cam = cams[id];
  if (!cam) return;
  clearTimeout(cam.timer);
  cam.timer = setTimeout(() => nextFrame(id), delay);
}

async function nextFrame(id) {
  const cam = cams[id];
  if (!cam || cam.loading) return;
  const watching = state.view === "printers" && cam.on && document.visibilityState === "visible"
    && cam.node.isConnected && cam.printer && cam.printer.online;
  if (!watching) { scheduleFrame(id, 2000); return; }
  cam.loading = true;
  let url = null;
  try {
    const r = await fetch(`api/printer/camera?printer=${encodeURIComponent(id)}&t=${Date.now()}`,
      { cache: "no-store" });
    const type = r.headers.get("content-type") || "";
    if (!r.ok || !type.startsWith("image/")) {
      const body = type.includes("json") ? await r.json().catch(() => ({})) : {};
      throw new Error(body.error || "The camera is not answering.");
    }
    url = URL.createObjectURL(await r.blob());
    const next = cam.back;
    next.src = url;
    await next.decode();
    const old = cam.url;
    const front = cam.img;
    next.className = "camimg";
    next.alt = front.alt;
    next.removeAttribute("aria-hidden");
    front.className = "camback";
    front.alt = "";
    front.setAttribute("aria-hidden", "true");
    cam.img = next;
    cam.back = front;
    cam.url = url;
    url = null;
    if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);
    cam.failures = 0;
    // The box takes the stream's own shape, so the picture is neither
    // stretched, cropped nor letterboxed (cameras differ: 16:9, 4:3).
    if (next.naturalWidth && next.naturalHeight) {
      const ratio = `${next.naturalWidth} / ${next.naturalHeight}`;
      if (cam.ratio !== ratio) {
        cam.ratio = ratio;
        const wrap = cam.node.closest(".camwrap");
        if (wrap) wrap.style.aspectRatio = ratio;
      }
    }
    cam.node.classList.add("has-frame");
    cam.node.classList.remove("no-frame");
    if (cam.on) cam.note.hidden = true;
    cam.loading = false;
    scheduleFrame(id, 600);
  } catch (err) {
    if (url) URL.revokeObjectURL(url);
    cam.loading = false;
    cam.failures += 1;
    // The last good frame stays on screen; a note says why it is not moving.
    // One slow frame over a moving picture is not worth a note.
    if (!cam.node.classList.contains("has-frame") || cam.failures > 1) {
      cam.note.textContent = err.message || "The camera is not answering.";
      cam.note.hidden = false;
    }
    if (!cam.node.classList.contains("has-frame")) cam.node.classList.add("no-frame");
    scheduleFrame(id, Math.min(30000, 3000 * cam.failures));
  }
}

function cameraBlock(p) {
  const cam = cameraNode(p);
  if (!p.online) {
    cam.note.textContent = "The printer is offline.";
    cam.note.hidden = false;
  } else if (!cam.loading && !cam.timer) {
    scheduleFrame(p.id, 50);
  }
  const tone = stateTone(p);
  const word = p.online ? (STATE_WORDS[p.state] || p.state || "Connecting") : "Offline";
  // The stage is the job's to say (it is in the job block), not the picture's.
  const overlay = el("div", { class: "camover" },
    el("span", { class: `pill ${tone}` }, el("i", { class: "dot" }), word),
    watchBadge(p),
    el("span", { class: "grow" }),
    el("button", { type: "button", class: "iconbtn", title: p.chamber_light ? "Light off" : "Light on",
      "aria-label": p.chamber_light ? "Turn the chamber light off" : "Turn the chamber light on",
      "aria-pressed": String(Boolean(p.chamber_light)),
      onclick: () => command(p, "light", { value: !p.chamber_light }) }, icon("light")),
    el("button", { type: "button", class: "iconbtn", title: cam.on ? "Pause the camera" : "Show the camera",
      "aria-label": cam.on ? "Pause the camera" : "Show the camera",
      onclick: () => { cam.on = !cam.on; if (cam.on) scheduleFrame(p.id, 0); renderPrinters(true); } },
    icon(cam.on ? "pause" : "play")),
    el("button", { type: "button", class: "iconbtn", title: "Full screen", "aria-label": "Show the camera full screen",
      onclick: () => fullScreen(cam.node) }, icon("full")));
  // Progress is the job's ring: nothing but controls is drawn over the
  // picture (a progress line along its bottom read as a green bar in it).
  const wrap = el("div", { class: "camwrap" }, cam.node, overlay);
  if (cam.ratio) wrap.style.aspectRatio = cam.ratio;
  if (!cam.on) { cam.note.textContent = "Camera paused."; cam.note.hidden = false; }
  return wrap;
}

// Full screen on the element, or, where the ingress frame refuses the
// Fullscreen API, the element filling the window until Escape or its own
// Leave button.
function fullScreen(node, onChange) {
  const leave = () => {
    node.classList.remove("filled");
    document.body.classList.remove("has-filled");
    document.removeEventListener("keydown", onKey);
    if (onChange) onChange(false);
  };
  const onKey = (e) => { if (e.key === "Escape") leave(); };
  if (document.fullscreenElement === node || node.classList.contains("filled")) {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else leave();
    return;
  }
  const fill = () => {
    node.classList.add("filled");
    document.body.classList.add("has-filled");
    document.addEventListener("keydown", onKey);
    if (onChange) onChange(true);
  };
  if (node.requestFullscreen && document.fullscreenEnabled !== false) {
    node.requestFullscreen().then(() => {
      if (onChange) {
        onChange(true);
        const off = () => { if (document.fullscreenElement !== node) { document.removeEventListener("fullscreenchange", off); onChange(false); } };
        document.addEventListener("fullscreenchange", off);
      }
    }, fill);
  } else {
    fill();
  }
}

function ring(pct) {
  const value = Math.max(0, Math.min(100, pct || 0));
  return el("div", { class: "ring", style: `--p:${value}`, role: "img", "aria-label": `${value}% done` },
    el("span", {}, `${value}`, el("small", {}, "%")));
}

function jobBlock(p) {
  if (!(p.printing || p.state === "finish" || p.state === "failed") || !p.file) return null;
  const facts = [];
  if (p.printing && p.remaining_min != null) {
    facts.push(el("div", { class: "fact" }, el("b", {}, duration(p.remaining_min)), el("span", {}, "left")));
    facts.push(el("div", { class: "fact" }, el("b", {}, clock(p.remaining_min)), el("span", {}, "done at")));
  }
  if (p.layer != null && p.total_layers) {
    facts.push(el("div", { class: "fact" }, el("b", {}, `${p.layer}/${p.total_layers}`), el("span", {}, "layer")));
  }
  return el("div", { class: "job" },
    ring(p.progress),
    el("div", { class: "jobtext" },
      el("b", { class: "jobname", title: p.file }, p.file),
      el("p", { class: "hint" }, p.printing ? (p.stage || "Printing")
        : p.state === "finish" ? "Finished — clear the plate before the next print." : "The print failed."),
      el("div", { class: "facts" }, facts)),
    p.job_picture ? el("img", { class: "jobpic", src: p.job_picture, alt: "", loading: "lazy" }) : null);
}

function tile(iconName, label, value, sub) {
  return el("div", { class: "tile" }, el("span", { class: "ticon" }, icon(iconName)),
    el("div", {}, el("span", { class: "tlabel" }, label), el("b", {}, value),
      sub ? el("span", { class: "tsub" }, sub) : null));
}

function readings(p) {
  const fans = p.fans || {};
  const fanText = fans.part != null ? `${fans.part}%` : "–";
  return el("div", { class: "tiles" },
    tile("nozzle", "Nozzle", temp(p.nozzle_c), p.nozzle_target_c ? `→ ${Math.round(p.nozzle_target_c)}°` : "off"),
    tile("bed", "Bed", temp(p.bed_c), p.bed_target_c ? `→ ${Math.round(p.bed_target_c)}°` : "off"),
    p.chamber_c != null ? tile("chamber", "Chamber", `${Math.round(p.chamber_c)}°`) : null,
    tile("fan", "Part fan", fanText, fans.aux != null ? `aux ${fans.aux}%` : null));
}

function spool(t, active, p) {
  const level = t.remaining != null ? t.remaining : 100;
  const colour = t.colour || "#c9d2da";
  return el("button", { type: "button", class: `spool${active ? " active" : ""}`,
    title: `${t.name || t.type}${t.remaining != null ? ` · ${t.remaining}% left` : ""}. Press to read the tray's tag again.`,
    onclick: () => (t.slot === "external" ? command(p, "refresh") : command(p, "ams_refresh", { value: t.slot })) },
  el("span", { class: "reel", style: `--c:${colour};--l:${level}` }, el("i", {})),
  el("b", {}, t.slot === "external" ? "Ext" : `${(t.slot % 4) + 1}`),
  el("span", { class: "mat" }, t.type || "?"),
  el("span", { class: "tsub" }, t.name && t.name !== t.type ? t.name : t.remaining != null ? `${t.remaining}%` : ""),
  active ? el("span", { class: "feeding" }, "in use") : null);
}

function amsBlock(p) {
  const trays = p.ams || [];
  if (!trays.length && !p.external_spool) return null;
  const units = new Map();
  for (const t of trays) {
    const u = Math.floor(t.slot / 4);
    if (!units.has(u)) units.set(u, []);
    units.get(u).push(t);
  }
  const box = el("div", { class: "amsbox" });
  for (const [u, list] of units) {
    const info = (p.ams_units || []).find((x) => x.id === u) || {};
    const humid = info.humidity != null ? el("span", { class: `humid h${info.humidity}`,
      title: "AMS humidity: 1 is dry, 5 is wet" }, icon("drop"), `${info.humidity}/5`) : null;
    box.append(el("div", { class: "amsunit" },
      el("div", { class: "amshead" }, el("b", {}, units.size > 1 ? `AMS ${u + 1}` : "AMS"), humid,
        info.temp_c != null ? el("span", { class: "hint" }, `${Math.round(info.temp_c)}°`) : null),
      el("div", { class: "spools" }, list.map((t) => spool(t, p.active_tray === t.slot, p)))));
  }
  if (p.external_spool) {
    box.append(el("div", { class: "amsunit ext" }, el("div", { class: "amshead" }, el("b", {}, "Spool holder")),
      el("div", { class: "spools" }, spool(p.external_spool, p.active_tray === "external", p))));
  }
  return box;
}

function hmsBlock(p) {
  if (!(p.hms && p.hms.length) && !p.error_code) return null;
  const notes = p.hms_notes || {};
  const items = (p.hms || []).map((code) => el("li", {},
    el("a", { href: `https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/${code}`, target: "_blank",
      rel: "noopener" }, code),
    notes[code] ? el("p", { class: "hint" }, notes[code]) : null));
  return el("div", { class: "alert" },
    el("b", {}, p.error_code ? `Print error ${p.error_code}` : "The printer has messages"),
    items.length ? el("ul", { class: "plain" }, items) : null,
    el("p", { class: "hint" }, "Each code opens Bambu Lab's page on what it means and what to do."));
}

function controlsBlock(p) {
  const row = el("div", { class: "controls" });
  if (p.state === "pause") row.append(el("button", { class: "primary", onclick: () => command(p, "resume") }, icon("play"), "Resume"));
  else if (p.printing) row.append(el("button", { onclick: () => command(p, "pause") }, icon("pause"), "Pause"));
  if (p.printing) {
    const armed = state.armed === p.id;
    row.append(el("button", { class: armed ? "danger solid" : "danger", onclick: () => {
      if (state.armed === p.id) { state.armed = null; command(p, "stop"); return; }
      state.armed = p.id;
      renderPrinters(true);
      setTimeout(() => { if (state.armed === p.id) { state.armed = null; renderPrinters(true); } }, 4000);
    } }, icon("stop"), armed ? "Press again to stop" : "Stop"));
    row.append(el("div", { class: "seg", role: "group", "aria-label": "Speed" },
      ["silent", "standard", "sport", "ludicrous"].map((s) => el("button", { type: "button",
        "aria-pressed": String(s === p.speed), onclick: () => command(p, "speed", { value: s }) },
      s[0].toUpperCase() + s.slice(1)))));
  }
  return row.childNodes.length ? row : null;
}

const storageNodes = {};

function storageBlock(p) {
  let node = storageNodes[p.id];
  if (!node) {
    node = storageNodes[p.id] = el("div", { class: "storage" });
    node.append(el("p", { class: "hint" }, "Open to read what is on the printer."));
  }
  const box = el("details", { class: "more", "data-k": "storage" },
    el("summary", {}, "On the printer"), node);
  box.addEventListener("toggle", () => { if (box.open && !node.dataset.loaded) loadStorage(p); });
  return box;
}

async function loadStorage(p) {
  const node = storageNodes[p.id];
  node.dataset.loaded = "1";
  node.replaceChildren(el("p", { class: "hint" }, "Reading the printer's storage…"));
  try {
    const r = await api(`api/printer/storage?printer=${encodeURIComponent(p.id)}`);
    const jobs = r.files.filter((f) => f.printable);
    const queue = [];
    const grid = el("div", { class: "pfiles" }, jobs.map((f) => el("div", { class: "pfile" },
      storagePicture(f, queue),
      el("b", { title: f.name }, f.name.replace(/(\.gcode)?\.3mf$/i, "")),
      el("span", { class: "hint" }, [f.size ? `${(f.size / 1e6).toFixed(1)} MB` : null, f.date].filter(Boolean).join(" · ")),
      el("div", { class: "row wrap" },
        el("button", { class: "primary", disabled: p.printing, onclick: () => printStored(p, f) }, "Print"),
        el("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete ${f.name} from ${p.name}?`)) return;
          try {
            await api(`api/printer/storage?printer=${encodeURIComponent(p.id)}&name=${encodeURIComponent(f.name)}`,
              { method: "DELETE" });
            loadStorage(p);
          } catch (e) { toast(e.message, true); }
        } }, "Delete")))));
    node.replaceChildren(
      jobs.length ? grid : el("p", { class: "hint" }, "No print jobs on the printer's storage."),
      el("div", { class: "row" }, el("button", { type: "button", onclick: () => loadStorage(p) }, "Read again")));
    loadPictures(queue, node);
  } catch (e) {
    node.dataset.loaded = "";
    node.replaceChildren(el("p", { class: "warn" }, e.message),
      el("button", { type: "button", onclick: () => loadStorage(p) }, "Try again"));
  }
}

// A file's picture on the printer: a quiet plate while it loads or when the
// file has none, never a word that reads as an error. The pictures are read
// one at a time (the printer serves one storage session well), and one that
// failed (storage busy, a slow answer) is asked again rather than left blank.
const PLATE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17l9 4 9-4-9-4-9 4zm9-14L3 7l9 4 9-4-9-4zm-9 9l9 4 9-4-2.2-1L12 13.9 5.2 11 3 12z"/></svg>';

function storagePicture(f, queue) {
  const box = el("div", { class: "nopic", "aria-hidden": "true" });
  box.innerHTML = PLATE_SVG;
  if (f.picture) { box.classList.add("loading"); queue.push({ url: f.picture, box }); }
  return box;
}

async function loadPictures(queue, node) {
  for (const item of queue) {
    for (let attempt = 0; attempt < 4 && node.isConnected; attempt += 1) {
      if (attempt) await new Promise((r) => setTimeout(r, 1500 * attempt));
      let r;
      try { r = await fetch(item.url, { cache: "no-store" }); } catch (_) { continue; }
      if (r.status === 404) break;  // the file has no picture
      if (!r.ok || !(r.headers.get("content-type") || "").startsWith("image/")) continue;
      const img = el("img", { src: URL.createObjectURL(await r.blob()), alt: "" });
      try { await img.decode(); } catch (_) { continue; }
      item.box.replaceWith(img);
      item.box = null;
      break;
    }
    if (item.box) item.box.classList.remove("loading");
  }
}

async function printStored(p, f) {
  const dlg = $("#printDialog");
  openPrintDialog({ title: `Print ${f.name}`, printers: [p], stored: f, sliced: true });
  dlg.dataset.stored = f.name;
  dlg.dataset.size = f.size || 0;
}

function manualBlock(p) {
  const box = el("details", { class: "more", "data-k": "manual" }, el("summary", {}, "Temperatures and G-code"));
  const tform = el("form", { class: "row wrap", onsubmit: (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    command(p, "temperature", { target: f.get("target"), value: Number(f.get("value")) });
  } }, el("select", { name: "target", class: "sel" }, el("option", { value: "nozzle" }, "Nozzle"), el("option", { value: "bed" }, "Bed")),
  el("input", { name: "value", type: "number", min: 0, max: 300, placeholder: "°C", required: true }),
  el("button", { type: "submit" }, "Set"),
  el("button", { type: "button", onclick: () => command(p, "home") }, "Home axes"));
  const gform = el("form", { class: "row wrap", onsubmit: (e) => {
    e.preventDefault();
    command(p, "gcode", { value: new FormData(e.target).get("gcode") });
  } }, el("input", { name: "gcode", placeholder: "M106 P1 S255", required: true, class: "grow" }),
  el("button", { type: "submit" }, "Send G-code"));
  box.append(tform, gform, el("p", { class: "hint" }, "Refused while it prints, so nothing here can change a print in progress."));
  return box;
}

// ------------------------------------------------- failure detection ---
// Print failure detection's section of the printer card: whether it is on,
// what it is doing, the open alert with the frame brAIn judged beside the
// picture of what the print should be, the plan of looks over the print's
// layers, and the history. Everything it shows comes from the server's
// summary (`failure_detection`); the history is fetched when opened.
const WATCH_STATUS = {
  off: ["Off", ""], idle: ["Ready", "done"], watching: ["Watching", "live"], looking: ["Looking", "live"],
  basic: ["Watching (basic)", "live"], warning: ["Warning", "warn"], failure: ["Failure", "bad"],
  covered: ["Camera covered", "warn"], dark: ["Too dark", "warn"], frozen: ["Camera frozen", "warn"],
  no_camera: ["No camera", "warn"],
};
const PROBLEM_WORDS = { none: "Nothing wrong", spaghetti: "Spaghetti", detached: "Part came loose",
  not_sticking: "First layer not sticking", blob: "Blob on the nozzle", no_extrusion: "Nothing extruding",
  layer_shift: "Layer shift", warping: "Warping", knocked_over: "Part knocked over", stringing: "Stringing",
  other: "Problem" };
const DECISION_TONE = { ok: "live", watch: "warn", warning: "warn", failure: "bad", ignored: "", blind: "" };
const DECISION_WORDS = { ok: "Looks fine", watch: "Unsure — looking again soon", warning: "Warning",
  failure: "Failure", ignored: "Ignored", blind: "Could not see" };
const KIND_WORDS = { first_layer: "First layer", early: "Early adhesion", narrowing: "Narrows",
  bridge: "Bridges", overhang: "Overhangs", support: "Supports", colour: "Colour change", tall: "Tall and thin",
  taller: "Taller", last: "Last layers", fill: "Routine", spread: "Routine" };
const watchHist = {};
const watchTargets = { list: null };

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min ago`;
  return new Date(ts * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

function watchBadge(p) {
  const w = p.failure_detection;
  if (!w || !w.enabled || !["warning", "failure", "covered", "dark", "looking"].includes(w.status)) return null;
  const [word, tone] = WATCH_STATUS[w.status];
  return el("span", { class: `pill ${tone} wbadge`, title: w.sentence },
    icon(w.status === "warning" || w.status === "failure" ? "shieldAlert" : "shield"), word);
}

async function watchAct(p, action, extra = {}) {
  const key = `${p.id}:watch:${action}`;
  if (state.busy.has(key)) return;
  state.busy.add(key);
  try {
    const r = await api("api/watch/action", { json: { printer: p.id, action, ...extra } });
    toast(r.note || "Done.");
    delete watchHist[p.id];
    refresh();
  } catch (e) { toast(e.message, true); } finally { state.busy.delete(key); }
}

async function watchSet(p, changes) {
  // A focused control keeps the card from redrawing (renderPrinters), and
  // the card has to show the setting that was just changed.
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  try {
    await api("api/watch/settings", { json: { printer: p ? p.id : undefined, ...changes } });
    refresh();
  } catch (e) { toast(e.message, true); }
}

function watchTimeline(p, w) {
  const points = (w.plan && w.plan.checkpoints) || [];
  const total = (w.plan && w.plan.total_layers) || p.total_layers;
  if (!points.length || !total) return null;
  const line = el("div", { class: "wline", role: "img",
    "aria-label": `${points.length} planned looks over ${total} layers` });
  line.append(el("i", { class: "wfill", style: `width:${Math.min(100, ((p.layer || 0) / total) * 100)}%` }));
  for (const c of points) {
    const tone = c.state === "done" ? (DECISION_TONE[c.decision] || "") : c.state;
    line.append(el("span", { class: `wtick ${tone}`, style: `left:${Math.min(100, (c.layer / total) * 100)}%`,
      title: `Layer ${c.layer} · ${KIND_WORDS[c.kind] || c.kind}: ${c.reason}`
        + (c.state === "done" ? ` — ${DECISION_WORDS[c.decision] || c.decision}` : c.state === "missed" ? " — missed" : "") }));
  }
  if (p.printing && p.layer) line.append(el("span", { class: "wnow", style: `left:${Math.min(100, (p.layer / total) * 100)}%` }));
  const upcoming = points.filter((c) => c.state === "planned").slice(0, 3);
  return el("div", { class: "wplan" },
    el("div", { class: "wplanhead" }, el("b", {}, "Where it looks"),
      el("span", { class: "hint" }, w.plan.source === "gcode" ? "Planned from the print's G-code"
        : "Spread by layer (the print's file could not be read)"),
      el("span", { class: "grow" }),
      el("span", { class: "hint" }, `${w.looks.used}/${w.looks.budget} looks`)),
    line,
    upcoming.length ? el("ul", { class: "wnext" }, upcoming.map((c) => el("li", {},
      el("b", {}, `Layer ${c.layer}`), el("span", { class: "wkind" }, KIND_WORDS[c.kind] || c.kind),
      el("span", { class: "hint" }, c.reason)))) : null);
}

function watchAlert(p, w) {
  const a = w.alert;
  if (!a || !a.open) return null;
  const failure = a.level === "failure";
  const buttons = failure && a.paused
    ? [el("button", { class: "primary", onclick: () => watchAct(p, "resume", { alert: a.id }) }, icon("play"), "Resume — not a failure"),
       el("button", { class: "danger", onclick: () => { if (confirm(`Stop the print on ${p.name}?`)) watchAct(p, "stop", { alert: a.id }); } }, icon("stop"), "Stop print")]
    : [el("button", { class: failure ? "primary" : "", onclick: () => watchAct(p, "pause", { alert: a.id }) }, icon("pause"), "Pause print"),
       el("button", { onclick: () => watchAct(p, "ignore", { alert: a.id }) }, "Ignore")];
  const pics = el("div", { class: "wpics" },
    a.image_url ? el("figure", {}, el("img", { src: a.image_url, alt: "What the camera saw" }), el("figcaption", {}, "What brAIn saw")) : null,
    w.expected_url ? el("figure", {}, el("img", { src: w.expected_url, alt: "What the print should look like" }), el("figcaption", {}, "What it should be")) : null);
  return el("div", { class: `walert ${failure ? "bad" : "warn"}` },
    el("div", { class: "walerthead" }, icon("shieldAlert"),
      el("b", {}, failure ? (a.paused ? "Print paused — it looks failed" : "The print looks failed")
        : "The print may be going wrong"),
      el("span", { class: "grow" }), el("span", { class: "hint" }, ago(a.at))),
    el("p", { class: "wsummary" }, a.summary),
    el("p", { class: "hint" }, [PROBLEM_WORDS[a.problem] || a.problem,
      a.confidence != null ? `${Math.round(a.confidence * 100)}% sure` : null].filter(Boolean).join(" · ")),
    a.pause_error ? el("p", { class: "warn" }, a.pause_error) : null,
    pics.childNodes.length ? pics : null,
    el("div", { class: "row wrap" }, buttons),
    el("p", { class: "hint" }, failure && a.paused
      ? "Resume if it is a false alarm: the same problem will then only be warned about on this print."
      : "Ignore stops warnings about this problem for the rest of the print."));
}

function watchHistory(p) {
  const box = el("details", { class: "more", "data-k": "watchhist" }, el("summary", {}, "Looks this print"));
  const list = el("div", { class: "whist" }, el("p", { class: "hint" }, "Loading…"));
  box.append(list);
  const fill = (h) => {
    if (!h.checks.length) { list.replaceChildren(el("p", { class: "hint" }, "No looks yet this print.")); return; }
    list.replaceChildren(...h.checks.map((c) => el("div", { class: "wcheck" },
      c.image_url ? el("a", { href: c.image_url, target: "_blank", rel: "noopener" },
        el("img", { src: c.image_url, alt: "", loading: "lazy" })) : el("div", { class: "nopic" }),
      el("div", { class: "grow" },
        el("div", { class: "row wcheckhead" },
          el("span", { class: `pill ${DECISION_TONE[c.decision] || ""}` }, el("i", { class: "dot" }), DECISION_WORDS[c.decision] || c.decision),
          el("b", {}, c.layer != null ? `Layer ${c.layer}` : "Finished"),
          el("span", { class: "hint" }, ago(c.at))),
        el("p", {}, c.summary),
        el("p", { class: "hint" }, [c.why, c.confidence != null ? `${Math.round(c.confidence * 100)}% sure` : null,
          c.expected ? "compared with the plate's picture" : null].filter(Boolean).join(" · "))))));
  };
  const load = async () => {
    try {
      const h = await api(`api/watch?printer=${encodeURIComponent(p.id)}`);
      watchHist[p.id] = h;
      fill(h);
    } catch (e) { list.replaceChildren(el("p", { class: "warn" }, e.message)); }
  };
  if (watchHist[p.id]) fill(watchHist[p.id]);
  box.addEventListener("toggle", () => { if (box.open) load(); });
  return box;
}

function watchSettings(p, w) {
  const box = el("details", { class: "more", "data-k": "watchset" }, el("summary", {}, "Detection settings"));
  const notify = el("select", { class: "sel", "aria-label": "Phone for alerts",
    onchange: (e) => watchSet(null, { notify: e.target.value }) },
  el("option", { value: "" }, "Home Assistant notifications only"));
  const fillTargets = () => {
    const current = (state.data && state.data.watch_notify) || w.notify || "";
    const list = watchTargets.list || [];
    notify.replaceChildren(el("option", { value: "" }, "Home Assistant notifications only"),
      ...[...new Set([...list, ...(current ? [current] : [])])].map((t) => el("option", { value: t, selected: t === current }, t.replace(/^notify\./, ""))));
  };
  box.addEventListener("toggle", async () => {
    if (!box.open) return;
    if (watchTargets.list === null) {
      try { watchTargets.list = (await api("api/watch/targets")).targets; } catch (_) { watchTargets.list = []; }
    }
    fillTargets();
  });
  fillTargets();
  const seg = (label, key, options) => el("div", { class: "wset" }, el("span", { class: "wsetlabel" }, label),
    el("div", { class: "seg", role: "group", "aria-label": label }, options.map(([value, word, title]) =>
      el("button", { type: "button", title, "aria-pressed": String(w[key] === value),
        onclick: () => watchSet(p, { [key]: value }) }, word))));
  const toggle = (label, key, hint) => el("label", { class: "check wcheckbox" },
    el("input", { type: "checkbox", checked: Boolean(w[key === "plate" ? "plate_watch" : key]),
      onchange: (e) => watchSet(p, { [key]: e.target.checked }) }),
    el("span", {}, label, el("small", { class: "hint" }, hint)));
  box.append(
    seg("When a print fails", "mode", [["pause", "Warn and pause", "Pause a print brAIn is sure has failed"],
      ["warn", "Only warn", "Never pause; only tell you"]]),
    seg("Sensitivity", "sensitivity", [["low", "Relaxed", "Fewer looks, and only sure things"],
      ["medium", "Balanced", ""], ["high", "Careful", "More looks, and doubts raised sooner"]]),
    toggle("Turn the chamber light on to see", "light", "Only when it is too dark, once per print."),
    toggle("Watch for the plate being cleared", "plate", "After a print, for the Plate clear sensor."),
    el("label", {}, "Alerts go to", notify),
    el("p", { class: "hint" }, "Each look is a brAIn run, so it looks at the moments a print is most likely to fail — the first layer, where the part narrows, bridges, colour changes, a part getting tall — and after anything doubtful, not every few seconds. A covered lens or a dark chamber stands everything down."));
  return box;
}

function watchBlock(p) {
  const w = p.failure_detection;
  if (!w) return null;
  const [word, tone] = WATCH_STATUS[w.status] || [w.status, ""];
  const head = el("div", { class: "whead" },
    el("span", { class: "wicon" }, icon(w.status === "warning" || w.status === "failure" ? "shieldAlert" : "shield")),
    el("div", { class: "grow" }, el("b", {}, "Print failure detection"),
      w.enabled ? el("p", { class: "hint" }, w.sentence) : null),
    w.enabled ? el("span", { class: `pill ${tone}` }, el("i", { class: "dot" }), word) : null,
    el("label", { class: "switch", title: w.enabled ? "Turn print failure detection off" : "Turn print failure detection on" },
      el("input", { type: "checkbox", role: "switch", checked: w.enabled, "aria-label": "Print failure detection",
        onchange: (e) => watchSet(p, { enabled: e.target.checked }) }), el("i", {})));
  if (!w.enabled) {
    return el("section", { class: "watch off" }, head,
      el("p", { class: "hint" }, "Watches the camera while it prints: brAIn looks at the moments a print is most likely to fail, warns you, and pauses a print that has failed."));
  }
  const last = w.last;
  const plate = w.plate || {};
  const plateWords = { clear: "Plate clear", occupied: "Print on the plate", printing: "Printing", unknown: "Plate: not sure" };
  // The last look is the alert's own while one is open: said once, not twice.
  const repeats = last && w.alert && w.alert.open && w.alert.check === last.n;
  const lastRow = last && !repeats ? el("div", { class: "wlast" },
    last.image_url ? el("img", { src: last.image_url, alt: "", loading: "lazy" }) : null,
    el("div", { class: "grow" },
      el("div", { class: "row wcheckhead" },
        el("span", { class: `pill ${DECISION_TONE[last.decision] || ""}` }, el("i", { class: "dot" }), DECISION_WORDS[last.decision] || last.decision),
        el("span", { class: "hint" }, [last.layer != null ? `layer ${last.layer}` : null, ago(last.at)].filter(Boolean).join(" · "))),
      el("p", {}, last.summary))) : null;
  return el("section", { class: `watch ${tone}` }, head,
    watchAlert(p, w),
    watchTimeline(p, w),
    lastRow,
    el("div", { class: "row wrap" },
      el("button", { type: "button", disabled: !(p.printing || p.state === "finish") || w.status === "looking",
        title: "Have brAIn look at the print now", onclick: () => watchAct(p, "check") }, icon("eye"), "Check now"),
      w.plate_watch && !p.printing ? el("span", { class: `pill ${plate.state === "clear" ? "done" : ""}`, title: plate.why || "" },
        el("i", { class: "dot" }), plateWords[plate.state] || "Plate") : null,
      w.plate_watch && plate.state !== "clear" && !p.printing
        ? el("button", { type: "button", onclick: () => watchAct(p, "plate_clear") }, "It's clear") : null),
    watchHistory(p), watchSettings(p, w));
}

function printerCard(p) {
  const meta = [p.model, p.nozzle_diameter ? `${p.nozzle_diameter} mm nozzle` : null, p.host,
    p.wifi ? `Wi-Fi ${p.wifi}` : null].filter(Boolean).join(" · ");
  // Removing a printer is rare and cannot be undone by a press, so it is in
  // the card's menu, not a ✕ beside Refresh.
  const menu = el("details", { class: "pmenu", "data-k": "menu" },
    el("summary", { "aria-label": `More for ${p.name}` }, "⋯"),
    el("div", { class: "pmenupop" },
      el("button", { type: "button", class: "danger", onclick: async () => {
        if (!confirm(`Remove ${p.name} from BRUH Bambu Studio?`)) return;
        await api(`api/printers/${encodeURIComponent(p.id)}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
        refresh();
      } }, icon("close"), "Remove printer")));
  const head = el("header", { class: "phead" },
    el("div", { class: "grow" }, el("h2", {}, p.name), el("p", { class: "hint" }, meta)),
    el("button", { type: "button", class: "quiet", title: "Ask for a full report (after changing a spool)",
      onclick: () => command(p, "refresh") }, icon("refresh"), "Refresh"),
    el("button", { type: "button", class: "quiet", title: "Drop the connection and open a new one",
      onclick: () => command(p, "reconnect") }, icon("link"), "Reconnect"),
    menu);
  // What the printer is doing now on the left (the picture, the job and its
  // controls, the temperatures and the filament); what watches it and what
  // is stored on it on the right. One column on a phone, in that order.
  const now = el("div", { class: "pnow" }, cameraBlock(p),
    el("div", { class: "pnowbody" },
      p.connection_error ? el("p", { class: "warn" }, p.connection_error,
        el("button", { type: "button", onclick: () => command(p, "reconnect") }, "Reconnect")) : null,
      jobBlock(p), hmsBlock(p), controlsBlock(p), readings(p), amsBlock(p)));
  const more = el("div", { class: "pmore" }, watchBlock(p), storageBlock(p), manualBlock(p));
  return el("article", { class: `printer ${stateTone(p)}`, "data-id": p.id }, head, now, more);
}

function renderPrinters(force = false) {
  const list = $("#printerList");
  const printers = state.data.printers;
  renderHa();
  if (!printers.length) {
    list.replaceChildren(el("p", { class: "card hint" }, "No printers yet. Find them on your network, or add one by hand below."));
    // The first time somebody opens an empty Printers tab, look for them.
    if (state.view === "printers" && !renderPrinters.scanned) {
      renderPrinters.scanned = true;
      scanPrinters();
    }
    return;
  }
  // Rebuilt only when nothing in it has focus, so a half-typed G-code line
  // is not wiped by the next poll; the camera and storage nodes are moved
  // into the new card rather than built again.
  const active = document.activeElement;
  if (!force && active && list.contains(active) && active.matches("input, select, textarea")) return;
  const open = new Set([...list.querySelectorAll("details[open]")].map(
    (d) => `${d.closest(".printer")?.dataset.id}:${d.dataset.k}`));
  list.replaceChildren(...printers.map((p) => {
    const card = printerCard(p);
    card.querySelectorAll("details[data-k]").forEach((d) => { if (open.has(`${p.id}:${d.dataset.k}`)) d.open = true; });
    return card;
  }));
}

// ------------------------------------------------------- home assistant ---
function renderHa() {
  const ha = state.data.ha || {};
  const box = $("#haCard");
  if (!box) return;
  const rows = [];
  let tone = "";
  if (ha.reason === "disabled") {
    rows.push(el("p", {}, "The Home Assistant integration is switched off in the add-on's Configuration tab."));
  } else if (ha.restart_needed) {
    tone = "warn";
    rows.push(el("p", {}, ha.reason === "update"
      ? `Home Assistant is running integration ${ha.running}; ${ha.deployed} is installed. Restart Home Assistant to load it.`
      : "Home Assistant loads the BRUH Bambu Studio integration when it starts. Restart it once and the "
        + "sensors, the camera, the services and the dashboard card appear — the add-on sets the integration up by itself."),
    el("div", { class: "row" }, el("button", { class: "primary", onclick: restartHa }, "Restart Home Assistant")));
  } else if (ha.entry) {
    tone = "ok";
    rows.push(el("p", {}, `Set up in Home Assistant (integration ${ha.running || ha.deployed || ""}): a device per printer with `
      + "its status, stage, progress, temperatures and camera, and the bruh_bambu services."));
  } else if (ha.error) {
    rows.push(el("p", { class: "warn" }, ha.error));
  } else {
    rows.push(el("p", { class: "hint" }, "Checking Home Assistant…"));
  }
  const cards = el("div", { class: "cardlist" },
    el("div", {}, el("b", {}, "Dashboard card"), " ", ha.lovelace_card
      ? el("span", { class: "pill done" }, "installed") : el("span", { class: "pill" }, "not installed"),
    el("p", { class: "hint" }, "Edit a dashboard, Add card, and search for “BRUH Bambu printers”, or paste:"),
    el("pre", { class: "snippet" }, "type: custom:bruh-bambu-card")),
    el("div", {}, el("b", {}, "Morph card"), " ", ha.morph_card
      ? el("span", { class: "pill done" }, "installed")
      : el("span", { class: "pill" }, ha.morph_installed ? "copying…" : "Morph is not installed"),
    el("p", { class: "hint" }, ha.morph_installed ? "In Morph, hold Edit and ask for the Bambu printer card, or add:"
      : "Install the Morph add-on and the card is copied in within two minutes."),
    ha.morph_installed ? el("pre", { class: "snippet" }, "type: custom:morph-bambu-printer") : null));
  if (ha.entry && !ha.lovelace_card) {
    cards.prepend(el("p", { class: "warn" }, "The card file is missing: switch install_lovelace_card on in the add-on's Configuration tab."));
  }
  box.className = `card ha ${tone}`;
  box.replaceChildren(el("div", { class: "row spread" }, el("h2", {}, "Home Assistant"),
    el("button", { type: "button", onclick: checkHa }, "Check again")), ...rows, cards);
}

async function checkHa() {
  try {
    const r = await api("api/ha/check", { json: {} });
    state.data.ha = r.ha;
    renderHa();
  } catch (e) { toast(e.message, true); }
}

async function restartHa() {
  if (!confirm("Restart Home Assistant now? Dashboards reconnect by themselves in a minute or two.")) return;
  try {
    await api("api/ha/restart", { json: {} });
    toast("Home Assistant is restarting.");
  } catch (e) { toast(e.message, true); }
}

async function savePrinter(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const r = await api("api/printers", { json: data });
    e.target.reset();
    $("#codeHint").hidden = true;
    $("#addPrinter").open = false;
    toast("Printer saved; connecting…");
    refresh();
    confirmConnected(r.printer);
  } catch (err) { toast(err.message, true); }
}

// Saving is not connecting: the access code, LAN mode and Developer mode are
// only proven by the printer answering, so say which happened.
async function confirmConnected(row) {
  for (let i = 0; i < 10; i++) {
    await new Promise((res) => setTimeout(res, 2000));
    await refresh();
    const p = (state.data.printers || []).find((x) => x.id === row.id);
    if (p && p.online) { toast(`Connected to ${p.name}.`); return; }
    if (i === 9) {
      toast(`${row.name} has not answered${p && p.connection_error ? `: ${p.connection_error}` : ""}. `
        + "Check the access code, and that LAN mode and Developer mode are on.", true);
    }
  }
}

// --------------------------------------------------------- find printers ---
const CODE_WHERE = "On the printer's screen, the 8-character access code is in its network "
  + "settings (LAN Only, or WLAN on the A1 and P1). Turn on LAN-only mode and Developer mode "
  + "there too, so it takes commands from Home Assistant.";

async function scanPrinters(subnet = "") {
  const btn = $("#scanBtn");
  btn.disabled = true;
  btn.textContent = "Looking…";
  $("#scanNote").textContent = subnet ? `Looking on ${subnet}…` : "Looking on Home Assistant's network…";
  try {
    const r = await api("api/printers/scan", { json: { subnet, wait: 90 } });
    renderScan(r.job);
  } catch (err) {
    $("#scanNote").textContent = err.message;
    $("#scanResults").replaceChildren();
  } finally {
    btn.disabled = false;
    btn.textContent = "Find printers on my network";
  }
}

function renderScan(job) {
  const found = job.found || [];
  const where = (job.networks || []).join(", ");
  $("#scanNote").textContent = found.length
    ? `Found ${found.length} on ${where}.`
    : `No Bambu Lab printer answered on ${where}. Check it is switched on and on this network, `
      + "or add it below by its IP address.";
  $("#scanResults").replaceChildren(...found.map((f) => {
    const what = `${f.model || "Bambu Lab printer"} · ${f.serial}`;
    let action;
    if (f.known && !f.moved) {
      action = el("span", { class: "chip" }, `Added as ${f.name}`);
    } else if (f.known) {
      action = el("button", { type: "button", onclick: () => moveP(f) }, "Update address");
    } else {
      action = el("button", { type: "button", class: "primary", onclick: () => startAdd(f) }, "Add");
    }
    return el("div", { class: "file" },
      el("div", { class: "grow" }, el("b", {}, what),
        el("p", { class: "hint" }, f.known && f.moved ? `${f.name} moved from ${f.saved_host} to ${f.host}` : f.host)),
      action);
  }));
}

function startAdd(f) {
  const form = $("#printerForm");
  form.name.value = f.model ? `Bambu ${f.model}` : "";
  form.model.value = f.model || "";
  form.host.value = f.host;
  form.serial.value = f.serial;
  form.access_code.value = "";
  $("#codeHint").textContent = CODE_WHERE;
  $("#codeHint").hidden = false;
  $("#addPrinter").open = true;
  $("#addPrinter").scrollIntoView({ behavior: "smooth", block: "center" });
  form.access_code.focus();
}

async function moveP(f) {
  try {
    await api("api/printers", { json: { name: f.name, model: f.model, host: f.host, serial: f.serial } });
    toast(`${f.name} is at ${f.host} now; reconnecting…`);
    f.moved = false;
    refresh();
    confirmConnected({ id: f.known, name: f.name });
  } catch (err) { toast(err.message, true); }
}

// --------------------------------------------------------------- files ---
async function loadFiles() {
  try {
    const r = await api("api/files");
    state.files = r.files;
    $("#libraryRoot").textContent = `${r.root} — also reachable over Samba and from Bambu Studio's Open dialog.`;
    renderFiles();
  } catch (e) { toast(e.message, true); }
}

const JOB_VERB = { print: "Print", slice: "Slice", import: "Import" };

function jobDone(j) {
  if (j.kind === "import" && j.files) {
    return `${j.files.length} file${j.files.length === 1 ? "" : "s"} added`
      + (j.skipped ? ` (${j.skipped} more on the page were not)` : "");
  }
  return j.note || j.phase || "done";
}

function renderJobs() {
  const jobs = ((state.data && state.data.jobs) || []).filter((j) => j.kind !== "scan");
  $("#jobList").replaceChildren(...jobs.slice(0, 5).map((j) => el("p", { class: `jobline ${j.state}` },
    el("b", {}, `${JOB_VERB[j.kind] || "Job"} `),
    `${j.file || j.source && j.kind !== "import" && j.source || j.title || j.url || ""}: `,
    j.state === "running" ? `${j.phase || "working"}${j.progress != null ? ` ${j.progress}%` : ""}…`
      : j.state === "failed" ? j.error : jobDone(j))));
}

async function importLink(e) {
  e.preventDefault();
  const box = $("#importUrl");
  const url = box.value.trim();
  if (!url) return;
  try {
    await api("api/import", { json: { url } });
    box.value = "";
    toast("Importing — it shows up in the list when it is done.");
    refresh();
  } catch (err) { toast(err.message, true); }
}

function filePicture(f) {
  const src = f.design ? `api/design/parts/${encodeURIComponent(f.design)}/thumb`
    : `api/thumb?path=${encodeURIComponent(f.path)}`;
  // A file with no picture gets the same quiet plate as one on a printer.
  return el("img", { class: "fthumb", src, alt: "", loading: "lazy",
    onerror: (e) => {
      const box = el("div", { class: "fthumb nopic", "aria-hidden": "true" });
      box.innerHTML = PLATE_SVG;
      e.target.replaceWith(box);
    } });
}

function filamentChips(f) {
  const use = (f.filament_use || []).filter((u) => u.colour || u.type);
  if (!use.length) return null;
  return el("div", { class: "fchips" }, use.map((u) => el("span", { class: "fchip",
    title: `${u.type || ""}${u.grams ? ` · ${u.grams} g` : ""}` },
  el("i", { style: `background:${u.colour || "transparent"}` }), `${u.type || ""}${u.grams ? ` ${u.grams} g` : ""}`)));
}

function renderFiles() {
  const rows = state.files.map((f) => {
    const designed = Boolean(f.design);
    const badges = [el("span", { class: `pill ${f.sliced ? "done" : ""}` }, f.sliced ? "Sliced" : f.project ? "Project" : "Model")];
    if (f.plates && f.plates.length > 1) badges.push(el("span", { class: "pill" }, `${f.plates.length} plates`));
    if (designed) badges.push(el("span", { class: "pill ghost" }, `Designed with brAIn · v${f.version}`));
    const facts = [f.seconds ? duration(Math.round(f.seconds / 60)) : null,
      f.grams ? `${f.grams} g` : null, `${(f.size / 1e6).toFixed(1)} MB`,
      new Date(f.modified * 1000).toLocaleDateString()].filter(Boolean).join(" · ");
    return el("div", { class: "frow" }, filePicture(f),
      el("div", { class: "grow" }, el("b", { class: "fname" }, designed ? f.name : f.path),
        el("div", { class: "badges" }, badges), el("p", { class: "hint" }, facts), filamentChips(f)),
      el("div", { class: "factions" },
        el("button", { class: "primary", onclick: () => openPrint(f) }, "Print"),
        !f.sliced && f.path.toLowerCase().endsWith(".3mf") ? el("button", { onclick: () => slice(f) }, "Slice") : null,
        el("button", { onclick: () => studio("open", f.path) }, "Open in Studio"),
        designed ? el("button", { onclick: () => { show("design"); if (window.openPart) window.openPart(f.design); } },
          "Open design") : el("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete ${f.path}?`)) return;
          await api(`api/files?path=${encodeURIComponent(f.path)}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
          loadFiles();
        } }, "Delete")));
  });
  $("#fileList").replaceChildren(...(rows.length ? rows : [el("p", { class: "hint" },
    "No models yet. Upload one, or save a project from Bambu Studio into this folder.")]));
  renderJobs();
}

async function slice(f) {
  try {
    await api("api/slice", { json: { file: f.path } });
    toast("Slicing — it shows up here when it is done.");
    refresh();
  } catch (e) { toast(e.message, true); }
}

// ----------------------------------------------------- print options ---
// One form, built from the panel's own list of options (/api/print/options),
// used by every print dialog: what brAIn can set, a person can set too.
let OPTION_CATALOG = null;

async function optionCatalog() {
  if (!OPTION_CATALOG) OPTION_CATALOG = await api("api/print/options");
  return OPTION_CATALOG;
}

function optionInput(o, value, prefix) {
  const name = `${prefix}${o.key}`;
  if (o.kind === "bool") {
    return el("label", { class: "check", title: o.help || "" },
      el("input", { type: "checkbox", name, checked: value === true || (value == null && o.default === true) }), o.label);
  }
  let input;
  if (o.kind === "enum") {
    const labels = o.key === "plate_type" ? (OPTION_CATALOG && OPTION_CATALOG.plates) || {} : {};
    input = el("select", { name },
      prefix === "s:" ? el("option", { value: "" }, "Profile's own") : null,
      ...o.choices.map((c) => el("option", { value: c, selected: c === (value ?? o.default) },
        labels[c] || c[0].toUpperCase() + c.slice(1))));
  } else {
    const [lo, hi, step] = o.range;
    input = el("input", { name, type: "number", min: lo, max: hi, step: step || 1,
      value: value ?? (prefix === "s:" ? "" : o.default ?? ""), placeholder: prefix === "s:" ? "profile" : "" });
  }
  return el("label", { title: o.help || "" }, o.label, input);
}

// `values` is what is set already (a part's print settings). `slice` false
// leaves the slicer options out (a file already sliced keeps its own).
function buildOptions(box, catalog, values = {}, { slice = true } = {}) {
  const start = el("div", { class: "optgrid" },
    catalog.start.filter((o) => o.kind !== "bool").map((o) => optionInput(o, values[o.key], "o:")));
  const toggles = el("div", { class: "opttoggles" },
    catalog.start.filter((o) => o.kind === "bool").map((o) => optionInput(o, values[o.key], "o:")));
  box.replaceChildren(start, toggles);
  if (!slice) return;
  const groups = new Map();
  for (const o of catalog.slice) {
    if (!groups.has(o.group)) groups.set(o.group, []);
    groups.get(o.group).push(o);
  }
  const set = catalog.slice.filter((o) => values[o.key] != null && values[o.key] !== "").length;
  const more = el("details", { class: "optmore" },
    el("summary", {}, "Slicer settings", set ? el("span", { class: "pill" }, `${set} set`) : null,
      el("span", { class: "hint" }, " — empty fields keep Bambu Studio's profile")));
  for (const [group, list] of groups) {
    more.append(el("fieldset", { class: "optgroup" }, el("legend", {}, group),
      el("div", { class: "optgrid" }, list.map((o) => optionInput(o, values[o.key], "s:")))));
  }
  box.append(more);
}

// What a form holds: {start: {...}, settings: {...}}, empty fields left out.
function readOptions(form) {
  const start = {}, settings = {};
  const catalog = OPTION_CATALOG || { start: [], slice: [] };
  for (const o of catalog.start) {
    const field = form.elements[`o:${o.key}`];
    if (!field) continue;
    if (o.kind === "bool") start[o.key] = field.checked;
    else if (field.value !== "") start[o.key] = o.kind === "int" ? Number(field.value) : field.value;
  }
  for (const o of catalog.slice) {
    const field = form.elements[`s:${o.key}`];
    if (!field) continue;
    if (o.kind === "bool") { if (field.checked) settings[o.key] = true; continue; }
    if (field.value === "") continue;
    settings[o.key] = o.kind === "enum" ? field.value : Number(field.value);
  }
  return { start, settings };
}

// A model with no project settings (an STL, a STEP, a 3MF from Printables)
// is sliced with Bambu Studio's own profiles for the printer, and the
// filament profile follows the tray picked here.
function bareModel(f) { return !f.sliced && !f.project; }

function fillFilaments(f) {
  const bare = f && bareModel(f);
  $("#printFilamentRow").hidden = !bare;
  $("#printAmsRow").hidden = Boolean(bare);
  if (!bare) return;
  const printer = state.data.printers.find((p) => p.id === $("#printPrinter").value) || {};
  const trays = printer.ams || [];
  $("#printFilament").replaceChildren(
    ...trays.map((t) => el("option", { value: String(t.slot), selected: printer.active_tray === t.slot },
      `AMS ${t.slot + 1}: ${[t.name || t.type].filter(Boolean).join(" ")}${t.remaining != null ? ` · ${t.remaining}%` : ""}`)),
    el("option", { value: "external" }, printer.external_spool
      ? `External spool: ${printer.external_spool.type}` : "External spool (PLA)"));
}

async function openPrintDialog({ title, printers, file, stored, sliced }) {
  const dlg = $("#printDialog");
  delete dlg.dataset.stored;
  delete dlg.dataset.file;
  $("#printTitle").textContent = title;
  $("#printPrinter").replaceChildren(...printers.map((p) => el("option", { value: p.id },
    `${p.name} (${p.online ? STATE_WORDS[p.state] || p.state || "online" : "offline"})`)));
  $("#printPrinter").onchange = () => fillFilaments(file);
  fillFilaments(file);
  $("#printForm").plate.value = (file && file.plates && file.plates[0]) || 1;
  $("#printPicture").replaceChildren(file ? filePicture(file)
    : stored && stored.picture ? el("img", { class: "fthumb", src: stored.picture, alt: "" }) : "");
  $("#printNote").textContent = sliced ? "It is sliced already, so it prints as it was sliced (more than one copy slices it again)."
    : file && bareModel(file) ? "It is sliced first with Bambu Studio's profiles for this printer, the filament you pick and the settings below."
      : "It is sliced first with the settings saved in the project.";
  try {
    buildOptions($("#printOptions"), await optionCatalog(), {}, { slice: Boolean(file && bareModel(file)) });
  } catch (e) { $("#printOptions").replaceChildren(el("p", { class: "warn" }, e.message)); }
  if (file) dlg.dataset.file = file.path;
  dlg.dataset.bare = file && bareModel(file) ? "1" : "";
  dlg.showModal();
}

async function openPrint(f) {
  if (f.design) {
    // A designed part prints with brAIn's settings and its own tray choice.
    show("design");
    await window.openPart(f.design);
    window.openDesignPrint();
    return;
  }
  const printers = state.data.printers;
  if (!printers.length) { toast("Add a printer first.", true); show("printers"); return; }
  openPrintDialog({ title: `Print ${f.name}`, printers, file: f, sliced: f.sliced });
}

async function submitPrint(e) {
  const dlg = $("#printDialog");
  if (e.submitter && e.submitter.value !== "go") return;
  const f = new FormData(e.target);
  const { start, settings } = readOptions(e.target);
  if (dlg.dataset.stored) {
    try {
      await api("api/printer/storage/print", { json: { printer: f.get("printer"), name: dlg.dataset.stored,
        size: Number(dlg.dataset.size || 0), plate: Number(f.get("plate")),
        use_ams: f.get("use_ams") === "on", ...start } });
      toast("Started from the printer's own storage.");
      refresh();
    } catch (err) { toast(err.message, true); }
    return;
  }
  const job = { file: dlg.dataset.file, printer: f.get("printer"),
    plate: Number(f.get("plate")), use_ams: f.get("use_ams") === "on", ...start };
  if (Object.keys(settings).length) job.settings = settings;
  if (dlg.dataset.bare) {
    delete job.use_ams;
    job.slot = f.get("slot") === "external" ? "external" : Number(f.get("slot"));
  }
  try {
    await api("api/print", { json: job });
    toast("Sending it to the printer — follow it on the Printers tab.");
    refresh();
  } catch (err) { toast(err.message, true); }
}

async function upload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  toast(`Uploading ${file.name}…`);
  try {
    await api("api/files", { method: "POST", body: form });
    toast(`${file.name} uploaded.`);
    loadFiles();
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
}

// ---------------------------------------------------------------- poll ---
async function refresh() {
  try {
    state.data = await api("api/state");
    renderStudio();
    renderPrinters();
    if (state.view === "files") renderJobs();
    // A slice or an import that has just finished put a file in the library.
    const busy = new Set(state.data.jobs.filter((j) => j.state === "running" && j.kind !== "print").map((j) => j.id));
    const finished = [...(refresh.busy || [])].some((id) => !busy.has(id));
    refresh.busy = busy;
    if ((busy.size || finished) && state.view === "files") {
      clearTimeout(refresh.f);
      refresh.f = setTimeout(loadFiles, finished ? 0 : 4000);
    }
  } catch (e) { $("#studioStatus").hidden = false; $("#studioStatus").textContent = `The panel is not answering: ${e.message}`; }
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
$("#printerForm").addEventListener("submit", savePrinter);
$("#scanBtn").addEventListener("click", () => scanPrinters());
$("#scanForm").addEventListener("submit", (e) => { e.preventDefault(); scanPrinters($("#scanSubnet").value.trim()); });
$("#printForm").addEventListener("submit", submitPrint);
$("#printCancel").addEventListener("click", () => $("#printDialog").close());
$("#upload").addEventListener("change", upload);
$("#importForm").addEventListener("submit", importLink);
api("api/printers").then((r) => {
  $("#modelSelect").replaceChildren(el("option", { value: "" }, "Not sure"), ...r.models.map((m) => el("option", { value: m }, m)));
}).catch(() => {});
let first = "studio";
try { first = localStorage.getItem("bambu.view") || "studio"; } catch (_) { /* storage refused */ }
refresh().then(() => show(first));
setInterval(refresh, 4000);

// A card's ⋯ menu closes on a press anywhere else, as a menu does.
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.pmenu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
});
