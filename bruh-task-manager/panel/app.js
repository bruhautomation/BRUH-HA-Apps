/* BRUH Task Manager panel.
 *
 * Every URL is relative (ingress mounts the page under a prefix). Process
 * names and command lines are text from other programs, so nothing from the
 * server is ever written with innerHTML — every node is built with
 * textContent.
 */
"use strict";

const state = {
  view: "apps",
  snap: null,
  procs: null,
  openGroups: new Set(),
  showAll: new Set(),
  lastApps: "",
  lastProcs: "",
  timer: null,
};

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch(path.replace(/^\//, ""), {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  if (!res.ok && !(body && "outcome" in body)) {
    throw new Error((body && (body.error || body.message)) || `HTTP ${res.status}`);
  }
  return body;
}

/* -- formatting ------------------------------------------------------------ */

function pct(v) { return v === null || v === undefined ? "–" : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`; }
function bytes(v) {
  if (v === null || v === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; let n = v;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}
function rate(v) { return v === null || v === undefined ? "–" : `${bytes(v)}/s`; }
function kb(v) { return v === null || v === undefined ? "–" : bytes(v * 1024); }
function duration(s) {
  if (s === null || s === undefined) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}
function minutesAgo(ts) {
  const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  return m < 1 ? "under a minute" : `${m} min`;
}

function spark(svg, values) {
  while (svg.firstChild) svg.firstChild.remove();
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  if (pts.length < 2) return;
  const max = Math.max(5, ...pts.map(([, v]) => v));
  const n = Math.max(values.length - 1, 1);
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", pts.map(([i, v]) => `${(i / n) * 60},${20 - (v / max) * 19}`).join(" "));
  svg.append(line);
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 6000);
}

/* -- top bar --------------------------------------------------------------- */

const machineHistory = [];

function renderMachine(m) {
  if (!m) return;
  $("mCpu").textContent = pct(m.cpu);
  machineHistory.push(m.cpu);
  machineHistory.splice(0, Math.max(0, machineHistory.length - 60));
  spark($("mCpuSpark"), machineHistory);
  $("mMem").textContent = pct(m.mem_percent);
  $("mMemSub").textContent = m.mem_total ? `${bytes(m.mem_used)} of ${bytes(m.mem_total)}` : "";
  $("mLoad").textContent = m.load ? m.load[0].toFixed(2) : "–";
  $("mCpus").textContent = m.cpus ? `${m.cpus} CPU${m.cpus === 1 ? "" : "s"}` : "";
  $("mUp").textContent = duration(m.uptime_s);
}

function renderBanners(snap) {
  const run = (snap.runaway && snap.runaway.apps) || [];
  const banner = $("runawayBanner");
  if (run.length) {
    banner.hidden = false;
    banner.textContent = run.map((r) =>
      `${r.name} has used over ${snap.runaway.threshold}% of the CPU for ${Math.round(r.minutes)} minutes.`).join(" ");
  } else {
    banner.hidden = true;
  }
  const err = $("errorBanner");
  err.hidden = !snap.apps_error;
  err.textContent = snap.apps_error || "";
  const badge = $("levelBadge");
  const l2 = snap.level2 || {};
  badge.textContent = l2.active ? "Level 2 · every process" : "Level 1 · apps";
  badge.classList.toggle("l2", !!l2.active);
}

/* -- apps ------------------------------------------------------------------ */

const KIND_LABEL = { core: "Home Assistant", supervisor: "Supervisor", plugin: "Supervisor plugin", addon: "App" };

function sortedApps(apps) {
  const q = $("appSearch").value.trim().toLowerCase();
  const by = $("appSort").value;
  const list = apps.filter((a) => !q || a.name.toLowerCase().includes(q) || (a.slug || "").toLowerCase().includes(q));
  const cmp = {
    cpu: (a, b) => (b.cpu || 0) - (a.cpu || 0),
    mem: (a, b) => (b.mem_bytes || 0) - (a.mem_bytes || 0),
    name: (a, b) => a.name.localeCompare(b.name),
  }[by];
  return list.sort((a, b) => cmp(a, b) || a.name.localeCompare(b.name));
}

function appRow(app, snap) {
  const chips = [el("span", { class: "chip", text: KIND_LABEL[app.kind] || app.kind })];
  if (app.state !== "started") chips.push(el("span", { class: "chip", text: app.state }));
  if (app.is_self) chips.push(el("span", { class: "chip", text: "this app" }));
  if (app.runaway) chips.push(el("span", { class: "chip warn", text: "running away" }));
  else if (app.above_since) chips.push(el("span", { class: "chip warn", text: `high CPU for ${minutesAgo(app.above_since)}` }));

  const width = Math.min(100, app.cpu || 0);
  const sp = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  sp.setAttribute("class", "spark");
  sp.setAttribute("viewBox", "0 0 60 20");
  sp.setAttribute("preserveAspectRatio", "none");
  spark(sp, app.history || []);

  const acts = el("div", { class: "acts" });
  if ((snap.process_keys || []).includes(app.key)) {
    acts.append(el("button", { class: "btn small", text: "Processes", onclick: () => showProcessesOf(app.key) }));
  }
  for (const action of app.actions || []) {
    const label = { restart: "Restart", stop: "Stop", start: "Start" }[action];
    acts.append(el("button", {
      class: `btn small${action === "stop" ? " danger" : ""}`,
      text: label,
      onclick: () => confirmAction(app, action),
    }));
  }

  return el("div", { class: `app${app.runaway ? " runaway" : ""}${app.state !== "started" ? " stopped" : ""}` },
    el("div", { class: "appname" }, el("strong", { text: app.name, title: app.slug || app.name }), el("div", { class: "chips" }, chips)),
    el("div", { class: "cpu" },
      el("div", { class: "cpuline" }, el("span", { class: "numlabel", text: "CPU" }), el("span", { class: "num", text: pct(app.cpu) })),
      el("div", { class: "barwrap" }, el("i", { style: `width:${width}%` })),
      sp),
    el("div", {}, el("span", { class: "numlabel", text: "Memory" }), el("span", { class: "num", text: bytes(app.mem_bytes) })),
    el("div", { class: "io" },
      el("div", { text: `Net ↓ ${rate(app.net_rx_rate)} ↑ ${rate(app.net_tx_rate)}` }),
      el("div", { text: `Disk r ${rate(app.disk_read_rate)} w ${rate(app.disk_write_rate)}` })),
    acts);
}

function renderApps(snap) {
  const key = JSON.stringify([snap.generated_at, $("appSearch").value, $("appSort").value]);
  if (key === state.lastApps) return;
  state.lastApps = key;
  const list = $("appList");
  const apps = sortedApps([...(snap.apps || [])]);
  list.replaceChildren(...apps.map((a) => appRow(a, snap)));
  if (!apps.length) {
    list.append(el("p", { class: "hint", text: snap.apps_error ? "" : "Measuring… the first figures arrive after two readings." }));
  }
}

async function confirmAction(app, action) {
  let lines;
  try {
    const info = await api(`api/app/${encodeURIComponent(app.key)}/impact?action=${action}`);
    lines = info.lines;
  } catch (e) {
    toast(e.message);
    return;
  }
  const label = { restart: "Restart", stop: "Stop", start: "Start" }[action];
  const ok = await ask(`${label} ${app.name}?`, lines, label, action === "stop");
  if (!ok) return;
  try {
    const job = await api(`api/app/${encodeURIComponent(app.key)}/${action}`, { method: "POST" });
    toast(job.message);
    followJob(job.id);
  } catch (e) {
    toast(e.message);
  }
}

async function followJob(id) {
  for (let i = 0; i < 400; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    let job;
    try { job = await api(`api/job/${id}`); } catch (_) { continue; }
    if (job.status !== "running") {
      toast(job.message);
      poll(true);
      return;
    }
  }
}

function ask(title, lines, goLabel, danger) {
  const dlg = $("confirm");
  $("confirmTitle").textContent = title;
  $("confirmLines").replaceChildren(...(lines || []).map((l) => el("li", { text: l })));
  const go = $("confirmGo");
  go.textContent = goLabel;
  go.className = `btn ${danger ? "danger" : "primary"}`;
  return new Promise((resolve) => {
    dlg.onclose = () => resolve(dlg.returnValue === "go");
    dlg.returnValue = "";
    dlg.showModal();
  });
}

/* -- processes ------------------------------------------------------------- */

const GROUP_LABEL = {
  addon: "App", core: "Home Assistant", supervisor: "Supervisor", plugin: "Supervisor plugin",
  self: "This app", os: "Operating system", kernel: "Kernel", container: "Unknown container",
};
const PER_GROUP = 25;

function showProcessesOf(key) {
  state.openGroups.add(key);
  switchView("processes");
  setTimeout(() => {
    const node = document.querySelector(`[data-group="${CSS.escape(key)}"]`);
    if (node) node.scrollIntoView({ block: "start" });
  }, 400);
}

function procRow(p, group) {
  const acts = el("div", { class: "acts" });
  if (p.can_end) {
    if (p.force_in === null || p.force_in === undefined) {
      acts.append(el("button", { class: "btn small danger", text: "End", onclick: () => endProcess(p, group, false) }));
    } else if (p.force_in > 0) {
      acts.append(el("button", { class: "btn small", text: `Force end in ${Math.ceil(p.force_in)}s`, disabled: true }));
    } else {
      acts.append(el("button", { class: "btn small danger", text: "Force end", onclick: () => endProcess(p, group, true) }));
    }
  }
  const sameWhy = group._sameWhy;
  return el("div", { class: "proc" },
    el("div", { class: "pname" },
      el("strong", { text: p.name }),
      el("span", { class: "pid", text: `pid ${p.pid}${p.unit ? ` · ${p.unit}` : ""}` }),
      el("span", { class: "cmd", text: p.cmd, title: p.cmd }),
      !p.can_end && p.why_not && p.why_not !== sameWhy ? el("span", { class: "why", text: p.why_not }) : null),
    el("span", { class: "num", text: pct(p.cpu), title: "Share of the whole machine" }),
    el("span", { class: "num", text: kb(p.pss_kb !== null && p.pss_kb !== undefined ? p.pss_kb : p.rss_kb),
      title: p.pss_kb !== null && p.pss_kb !== undefined ? "Proportional memory (shared pages split between their users)" : "Resident memory" }),
    acts);
}

function groupNode(group, query) {
  let procs = group.procs;
  if (query) {
    const groupHit = group.name.toLowerCase().includes(query) || (group.slug || "").toLowerCase().includes(query);
    if (!groupHit) procs = procs.filter((p) => p.name.toLowerCase().includes(query) || p.cmd.toLowerCase().includes(query));
    if (!procs.length) return null;
  }
  const whys = new Set(group.procs.map((p) => (p.can_end ? "" : p.why_not || "")));
  group._sameWhy = whys.size === 1 ? [...whys][0] : null;
  const all = state.showAll.has(group.key);
  const shown = all ? procs : procs.slice(0, PER_GROUP);
  const details = el("details", { class: "group", "data-group": group.key, open: state.openGroups.has(group.key) || !!query });
  details.addEventListener("toggle", () => {
    if (details.open) state.openGroups.add(group.key); else state.openGroups.delete(group.key);
  });
  details.append(
    el("summary", {},
      el("span", { class: "gname" },
        el("span", { class: "caret", "aria-hidden": "true" }),
        el("strong", { text: group.name }),
        el("span", { class: "sub", text: GROUP_LABEL[group.kind] || group.kind })),
      el("span", { class: "num", text: pct(group.cpu) }),
      el("span", { class: "num", text: kb(group.rss_kb) }),
      el("span", { class: "num gcount", text: `${group.count} proc${group.count === 1 ? "" : "s"}` })));
  if (group._sameWhy) details.append(el("div", { class: "gwhy", text: group._sameWhy }));
  const body = el("div", { class: "procs" }, shown.map((p) => procRow(p, group)));
  if (procs.length > shown.length) {
    body.append(el("div", { class: "proc" },
      el("button", { class: "btn small", text: `Show all ${procs.length}`, onclick: () => { state.showAll.add(group.key); state.lastProcs = ""; renderProcesses(); } })));
  }
  details.append(body);
  return details;
}

function renderProcesses() {
  const snap = state.snap;
  if (!snap) return;
  const l2 = snap.level2 || {};
  $("procOff").hidden = !!l2.active;
  $("procOn").hidden = !l2.active;
  if (!l2.active) {
    $("procOffSentence").textContent = l2.sentence || "";
    return;
  }
  const view = state.procs;
  if (!view) { $("procHint").textContent = "Measuring…"; return; }
  const query = $("procSearch").value.trim().toLowerCase();
  const kernel = $("showKernel").checked;
  const key = JSON.stringify([snap.generated_at, query, kernel, [...state.showAll]]);
  if (key === state.lastProcs) return;
  state.lastProcs = key;
  $("procHint").textContent = `${view.count} processes. CPU is a share of the whole machine; memory is resident memory unless it says otherwise.`
    + (view.measured ? "" : " The first CPU figures arrive after two readings.");
  const groups = view.groups.filter((g) => kernel || g.kind !== "kernel");
  $("procList").replaceChildren(...groups.map((g) => groupNode(g, query)).filter(Boolean));
}

async function endProcess(p, group, force) {
  const title = force ? `Force end ${p.name}?` : `End ${p.name}?`;
  const lines = force
    ? [`${p.name} (pid ${p.pid}) in ${group.name} did not stop when asked.`,
       "Force end stops it immediately, without letting it save anything."]
    : [`${p.name} (pid ${p.pid}) in ${group.name} is asked to stop, and can save and exit cleanly.`,
       `If it is the main process of ${group.name}, the app may stop or restart.`,
       "If it is still running a few seconds later, Force end is offered."];
  if (!(await ask(title, lines, force ? "Force end" : "End", true))) return;
  try {
    const res = await api(`api/process/${p.pid}/end`, {
      method: "POST", body: JSON.stringify({ start: p.start, force }),
    });
    toast(res.message);
  } catch (e) {
    toast(e.message);
  }
  poll(true);
}

/* -- settings -------------------------------------------------------------- */

let settingsFilled = false;

function renderSettings(snap) {
  const s = snap.settings || {};
  const v = s.values || {};
  const l2 = snap.level2 || {};
  $("l2Sentence").textContent = l2.sentence || "";
  for (const li of $("l2Steps").children) {
    li.classList.toggle("done", !!(l2.steps || {})[li.dataset.step]);
  }
  const link = $("infoLink");
  if (s.slug) link.href = `/hassio/addon/${encodeURIComponent(s.slug)}/info`;
  link.hidden = !s.slug;
  $("optProcessView").checked = !!v.process_view;
  $("optProcessView").disabled = !s.can_save;
  $("optEnding").checked = !!v.allow_ending_processes;
  $("optEnding").disabled = !s.can_save || !v.process_view;
  $("endRow").classList.toggle("disabled", !v.process_view);
  if (!settingsFilled) {
    $("optProtected").value = (v.protected_processes || []).join("\n");
    $("optThreshold").value = v.runaway_cpu_percent;
    $("optMinutes").value = v.runaway_minutes;
    $("optSample").value = v.sample_seconds;
    settingsFilled = true;
  }
  $("settingsSource").textContent = s.can_save
    ? "These are the add-on's options: the Configuration tab shows the same values."
    : "The Supervisor cannot be reached, so settings cannot be saved from here.";
}

async function saveSettings(changes, done) {
  try {
    await api("api/settings", { method: "POST", body: JSON.stringify(changes) });
    toast(done);
  } catch (e) {
    toast(e.message);
  }
  settingsFilled = false;
  poll(true);
}

/* -- loop ------------------------------------------------------------------ */

function switchView(view) {
  state.view = view;
  for (const tab of document.querySelectorAll(".tab")) tab.setAttribute("aria-selected", String(tab.dataset.view === view));
  $("viewApps").hidden = view !== "apps";
  $("viewProcesses").hidden = view !== "processes";
  $("viewSettings").hidden = view !== "settings";
  state.lastProcs = "";
  poll(true);
}

async function poll(now) {
  clearTimeout(state.timer);
  try {
    const wantProcs = state.view === "processes";
    const snap = await api(`api/snapshot${wantProcs ? "?processes=1" : ""}`);
    if (snap && snap.generated_at) {
      const fresh = !state.snap || snap.generated_at !== state.snap.generated_at;
      state.snap = snap;
      if (wantProcs) state.procs = snap.processes || null;
      if (fresh) renderMachine(snap.machine);
      renderBanners(snap);
      renderApps(snap);
      renderProcesses();
      renderSettings(snap);
    }
  } catch (e) {
    $("errorBanner").hidden = false;
    $("errorBanner").textContent = `The panel did not answer: ${e.message}`;
  }
  const every = ((state.snap && state.snap.sample_seconds) || 5) * 1000;
  state.timer = setTimeout(poll, every);
}

function wire() {
  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => switchView(tab.dataset.view));
  for (const b of document.querySelectorAll("[data-goto]")) b.addEventListener("click", () => switchView(b.dataset.goto));
  $("appSearch").addEventListener("input", () => state.snap && renderApps(state.snap));
  $("appSort").addEventListener("change", () => state.snap && renderApps(state.snap));
  $("procSearch").addEventListener("input", renderProcesses);
  $("showKernel").addEventListener("change", renderProcesses);
  $("optProcessView").addEventListener("change", async (e) => {
    const on = e.target.checked;
    if (on) {
      const ok = await ask("Turn on Level 2?", [
        "BRUH Task Manager will read the list of every process on this machine and show each one's CPU and memory.",
        "It only takes effect once you also turn Protection mode off on the add-on's Info page and restart the add-on.",
        "Turning Protection mode off lets this add-on see every process and its command line, and send signals to other apps' processes. It still cannot read their passwords or tokens.",
        "Switch it off and turn Protection mode back on when you are finished.",
      ], "Turn on", false);
      if (!ok) { e.target.checked = false; return; }
    }
    saveSettings({ process_view: on, ...(on ? {} : { allow_ending_processes: false }) },
      on ? "Level 2 is switched on. Next: turn Protection mode off and restart the add-on."
        : "Level 2 is off. Turn Protection mode back on from the add-on's Info page.");
  });
  $("optEnding").addEventListener("change", async (e) => {
    const on = e.target.checked;
    if (on) {
      const ok = await ask("Allow ending processes?", [
        "End process is offered only for processes inside apps, never for Home Assistant, the Supervisor or the operating system.",
        "Each process is asked to stop first; Force end is offered only if it is still running a few seconds later.",
        "Ending part of an app can stop the app. Restart on the Apps tab is the gentler answer when you are not sure.",
      ], "Allow", true);
      if (!ok) { e.target.checked = false; return; }
    }
    saveSettings({ allow_ending_processes: on }, on ? "Ending processes is allowed." : "Ending processes is switched off.");
  });
  $("saveProtected").addEventListener("click", () => {
    const list = $("optProtected").value.split("\n").map((s) => s.trim()).filter(Boolean);
    saveSettings({ protected_processes: list }, "Saved.");
  });
  $("saveRunaway").addEventListener("click", () => saveSettings({
    runaway_cpu_percent: Number($("optThreshold").value),
    runaway_minutes: Number($("optMinutes").value),
    sample_seconds: Number($("optSample").value),
  }, "Saved."));
}

wire();
poll(true);
