// BRUH Bambu Studio panel. Plain script, no build step.
//
// Every URL here is RELATIVE: ingress mounts the panel under
// /api/hassio_ingress/<token>/, so "/api/state" would be a request to Home
// Assistant's own root. BRUH Print shipped that bug once.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { data: null, files: [], view: "studio", busy: new Set() };

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

function connectScreen() {
  const frame = $("#screen");
  const s = state.data && state.data.studio;
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
  $("#screen").hidden = !s.running;
  if (!s.running) $("#screen").removeAttribute("src");
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
    toast(r.note || `${printer.name}: ${action} sent.`, Boolean(r.note));
    refresh();
  } catch (e) { toast(e.message, true); } finally { state.busy.delete(key); }
}

function stat(label, value) {
  return value == null || value === "" ? null : el("div", { class: "stat" }, el("span", {}, label), el("b", {}, value));
}

function temp(now, target) {
  if (now == null) return null;
  return target ? `${Math.round(now)}° → ${Math.round(target)}°` : `${Math.round(now)}°`;
}

function printerCard(p) {
  const stateWord = p.online ? (p.state || "connecting") : "offline";
  const chip = el("span", { class: `chip ${p.online ? (p.printing ? "live" : "") : "bad"}` }, stateWord);
  const card = el("article", { class: "card printer" },
    el("div", { class: "row spread" },
      el("div", {}, el("h2", {}, p.name), el("p", { class: "hint" }, [p.model, p.host].filter(Boolean).join(" · "))),
      chip));
  if (p.connection_error) card.append(el("p", { class: "warn" }, p.connection_error));
  if (p.printing || p.progress) {
    card.append(el("div", { class: "progress" }, el("div", { style: `width:${p.progress || 0}%` })),
      el("p", {}, [p.file, p.progress != null ? `${p.progress}%` : null,
        p.remaining_min != null ? `${duration(p.remaining_min)} left` : null,
        p.layer != null && p.total_layers ? `layer ${p.layer}/${p.total_layers}` : null]
        .filter(Boolean).join(" · ")));
  }
  card.append(el("div", { class: "stats" },
    stat("Nozzle", temp(p.nozzle_c, p.nozzle_target_c)), stat("Bed", temp(p.bed_c, p.bed_target_c)),
    stat("Chamber", p.chamber_c != null ? `${Math.round(p.chamber_c)}°` : null),
    stat("Speed", p.speed), stat("Errors", p.hms_count || null)));
  if (p.ams && p.ams.length) {
    card.append(el("div", { class: "ams" }, p.ams.map((t) => el("span", { class: "tray", title: t.type },
      el("i", { style: `background:${t.colour || "transparent"}` }), `${t.slot + 1} ${t.type}`,
      t.remaining != null ? ` ${t.remaining}%` : ""))));
  }
  const controls = el("div", { class: "row wrap" });
  if (p.state === "pause") controls.append(el("button", { class: "primary", onclick: () => command(p, "resume") }, "Resume"));
  else if (p.printing) controls.append(el("button", { onclick: () => command(p, "pause") }, "Pause"));
  if (p.printing) {
    controls.append(el("button", { class: "danger", onclick: () => {
      if (confirm(`Stop the print on ${p.name}? It cannot be resumed.`)) command(p, "stop");
    } }, "Stop"));
    const speed = el("select", { class: "sel", "aria-label": "Speed", onchange: (e) => command(p, "speed", { value: e.target.value }) },
      ["silent", "standard", "sport", "ludicrous"].map((s) => el("option", { value: s, selected: s === p.speed }, s)));
    controls.append(speed);
  }
  controls.append(el("button", { onclick: () => command(p, "light", { value: !p.chamber_light }) },
    p.chamber_light ? "Light off" : "Light on"));
  card.append(controls);

  const more = el("details", {}, el("summary", {}, "Temperatures, G-code and storage"));
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
  const storage = el("div", {});
  const list = el("button", { type: "button", onclick: async () => {
    storage.textContent = "Reading…";
    try {
      const r = await api(`api/printer/storage?printer=${encodeURIComponent(p.id)}`);
      storage.replaceChildren(el("ul", { class: "plain" }, r.files.map((f) =>
        el("li", {}, f.dir ? `${f.name}/` : f.name, f.size ? el("span", { class: "hint" }, ` ${(f.size / 1e6).toFixed(1)} MB`) : null))));
    } catch (e) { storage.textContent = e.message; }
  } }, "List the printer's files");
  const remove = el("button", { type: "button", class: "danger", onclick: async () => {
    if (!confirm(`Remove ${p.name} from BRUH Bambu Studio?`)) return;
    await api(`api/printers/${encodeURIComponent(p.id)}`, { method: "DELETE" }).catch((e) => toast(e.message, true));
    refresh();
  } }, "Remove printer");
  more.append(tform, gform, el("div", { class: "row wrap" }, list, remove), storage);
  card.append(more);
  return card;
}

function renderPrinters() {
  const list = $("#printerList");
  const printers = state.data.printers;
  if (!printers.length) {
    list.replaceChildren(el("p", { class: "card hint" }, "No printers yet. Add one below."));
    $("#addPrinter").open = true;
  } else {
    // Rebuilt only when nothing in it has focus, so a half-typed G-code
    // line is not wiped by the next poll.
    const active = document.activeElement;
    if (active && list.contains(active) && active.matches("input, select, textarea")) return;
    const open = new Set([...list.querySelectorAll("details[open]")].map((d) => d.closest(".printer")?.dataset.id));
    list.replaceChildren(...printers.map((p) => {
      const card = printerCard(p);
      card.dataset.id = p.id;
      if (open.has(p.id)) card.querySelector("details").open = true;
      return card;
    }));
  }
}

async function savePrinter(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    await api("api/printers", { json: data });
    e.target.reset();
    $("#addPrinter").open = false;
    toast("Printer saved; connecting…");
    refresh();
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

function renderJobs() {
  const jobs = (state.data && state.data.jobs) || [];
  $("#jobList").replaceChildren(...jobs.slice(0, 5).map((j) => el("p", { class: `job ${j.state}` },
    `${j.kind === "print" ? "Print" : "Slice"} ${j.file || j.source}: `,
    j.state === "running" ? `${j.phase || "working"}${j.progress != null ? ` ${j.progress}%` : ""}…`
      : j.state === "failed" ? j.error : (j.phase || "done"))));
}

function renderFiles() {
  const rows = state.files.map((f) => {
    const facts = [f.sliced ? "sliced" : "not sliced",
      f.plates && f.plates.length > 1 ? `${f.plates.length} plates` : null,
      f.seconds ? duration(Math.round(f.seconds / 60)) : null,
      f.grams ? `${f.grams} g` : null, `${(f.size / 1e6).toFixed(1)} MB`].filter(Boolean).join(" · ");
    return el("div", { class: "file" },
      el("div", { class: "grow" }, el("b", {}, f.path), el("p", { class: "hint" }, facts)),
      el("div", { class: "row wrap" },
        el("button", { class: "primary", onclick: () => openPrint(f) }, "Print"),
        !f.sliced && f.path.toLowerCase().endsWith(".3mf") ? el("button", { onclick: () => slice(f) }, "Slice") : null,
        el("button", { onclick: () => studio("open", f.path) }, "Open in Studio"),
        el("button", { class: "danger", onclick: async () => {
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

function openPrint(f) {
  const dlg = $("#printDialog");
  const printers = state.data.printers;
  if (!printers.length) { toast("Add a printer first.", true); show("printers"); return; }
  $("#printTitle").textContent = `Print ${f.name}`;
  $("#printPrinter").replaceChildren(...printers.map((p) => el("option", { value: p.id }, `${p.name} (${p.online ? p.state || "online" : "offline"})`)));
  $("#printForm").plate.value = (f.plates && f.plates[0]) || 1;
  $("#printNote").textContent = f.sliced ? "" : "It is sliced first with the settings saved in the project.";
  dlg.dataset.file = f.path;
  dlg.showModal();
}

async function submitPrint(e) {
  const dlg = $("#printDialog");
  if (e.submitter && e.submitter.value !== "go") return;
  const f = new FormData(e.target);
  try {
    await api("api/print", { json: { file: dlg.dataset.file, printer: f.get("printer"),
      plate: Number(f.get("plate")), use_ams: f.get("use_ams") === "on",
      bed_leveling: f.get("bed_leveling") === "on", timelapse: f.get("timelapse") === "on" } });
    toast("Sending it to the printer…");
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
    if (state.data.jobs.some((j) => j.state === "running" && j.kind !== "print") && state.view === "files") {
      clearTimeout(refresh.f);
      refresh.f = setTimeout(loadFiles, 4000);
    }
  } catch (e) { $("#studioStatus").hidden = false; $("#studioStatus").textContent = `The panel is not answering: ${e.message}`; }
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
$("#printerForm").addEventListener("submit", savePrinter);
$("#printForm").addEventListener("submit", submitPrint);
$("#printCancel").addEventListener("click", () => $("#printDialog").close());
$("#upload").addEventListener("change", upload);
api("api/printers").then((r) => {
  $("#modelSelect").replaceChildren(el("option", { value: "" }, "Not sure"), ...r.models.map((m) => el("option", { value: m }, m)));
}).catch(() => {});
let first = "studio";
try { first = localStorage.getItem("bambu.view") || "studio"; } catch (_) { /* storage refused */ }
refresh().then(() => show(first));
setInterval(refresh, 4000);
