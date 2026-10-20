// Design with brAIn: the parts list, the conversation, the 3D view, the
// versions and the print. Loaded after app.js and uses its helpers
// ($, el, api, toast, show, state). Every URL is relative (ingress).
"use strict";

const design = { status: null, parts: [], part: null, viewing: null, viewer: null,
  poll: null, loadedKey: "" };

function fmtSize(size) {
  return size ? size.map((v) => `${Math.round(v * 10) / 10}`).join(" × ") + " mm" : "";
}

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

async function designStatus() {
  try {
    const [st, list] = await Promise.all([api("api/design/status"), api("api/design/parts")]);
    design.status = st;
    design.parts = list.parts;
    // The tab is there when brAIn is, or when there are parts to look at.
    $("#designTab").hidden = !(st.brain.state === "ok" || list.parts.length);
    $("#designNote").textContent = st.brain.state === "ok"
      ? (st.cad ? "Describe a part and shape it with brAIn." : "The CAD tools are missing from this image.")
      : st.brain.sentence;
    $("#newPart").disabled = st.brain.state !== "ok";
    renderParts();
  } catch (_) { /* an older panel without the design routes: no tab */ }
}

function renderParts() {
  const box = $("#parts");
  if (!design.parts.length) {
    box.replaceChildren(el("p", { class: "hint" }, "No parts yet."));
    return;
  }
  box.replaceChildren(...design.parts.map((p) => el("button", {
    type: "button", class: `partrow ${design.part && design.part.id === p.id ? "on" : ""}`,
    onclick: () => openPart(p.id),
  }, p.thumbnail ? el("img", { src: `api/design/parts/${p.id}/thumb?t=${Math.round(p.updated || 0)}`, alt: "" })
    : el("span", { class: "thumb" }),
  el("span", { class: "grow" }, el("b", {}, p.name),
    el("span", { class: "hint" }, [p.versions ? `v${p.current || "–"} of ${p.versions}` : "no version",
      p.prints ? `${p.prints} printed` : null, ago(p.updated)].filter(Boolean).join(" · "))),
  ["thinking", "building", "fixing", "printing"].includes(p.state) ? el("span", { class: "chip live" }, "working") : null)));
}

async function newPart() {
  // brAIn names it from the first description; the name is editable above.
  try {
    const r = await api("api/design/parts", { json: { name: "New part" } });
    await designStatus();
    openPart(r.part.id);
    $("#composerText").focus();
  } catch (e) { toast(e.message, true); }
}

async function openPart(id) {
  try {
    const r = await api(`api/design/parts/${id}`);
    design.part = r.part;
    design.viewing = r.part.current;
    document.querySelector(".design").classList.add("open");
    $("#partView").hidden = false;
    renderPart();
    renderParts();
    pollPart();
  } catch (e) { toast(e.message, true); }
}

function closePart() {
  design.part = null;
  document.querySelector(".design").classList.remove("open");
  $("#partView").hidden = true;
  clearTimeout(design.poll);
  designStatus();
}

function busy(part) {
  return ["thinking", "building", "fixing", "printing"].includes(part.state);
}

function pollPart() {
  clearTimeout(design.poll);
  const part = design.part;
  if (!part) return;
  design.poll = setTimeout(async () => {
    if (!design.part || design.part.id !== part.id) return;
    try {
      const r = await api(`api/design/parts/${part.id}`);
      const moved = r.part.updated !== design.part.updated;
      const follow = design.viewing === design.part.current;
      design.part = r.part;
      if (follow) design.viewing = r.part.current;
      if (moved) {
        renderPart();
        designStatus();
      }
    } catch (_) { /* the next poll tries again */ }
    pollPart();
  }, busy(part) ? 1500 : 6000);
}

function renderPart() {
  const p = design.part;
  if (!p) return;
  if (document.activeElement !== $("#partName")) $("#partName").value = p.name;
  const v = (p.versions || []).find((x) => x.n === design.viewing);
  const files = v && v.files;
  for (const [id, key] of [["#dl3mf", "3mf"], ["#dlStep", "step"]]) {
    const a = $(id);
    a.hidden = !(files && files[key]);
    if (files && files[key]) a.href = `api/design/parts/${p.id}/file?v=${v.n}&path=${encodeURIComponent(files[key])}`;
  }
  $("#partPrint").disabled = !(v && v.ok);
  renderMessages(p);
  renderVersions(p);
  const status = $("#designStatus");
  status.hidden = !busy(p);
  status.textContent = p.state_detail || "";
  $("#composer").querySelector("button").disabled = busy(p) || design.status?.brain.state !== "ok";
  $("#composerText").placeholder = design.status?.brain.state === "ok"
    ? (p.versions && p.versions.length ? "What should change?" : "Describe the part: what it is for, what it fits, sizes you know…")
    : design.status?.brain.sentence || "";
  loadModel(p, v);
}

// brAIn answers in Markdown. It is drawn as DOM nodes, never innerHTML: the
// text is a model's, and markup in it must stay text.
function mdInline(text) {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("`")) out.push(el("code", {}, t.slice(1, -1)));
    else if (t.startsWith("**") || t.startsWith("__")) out.push(el("strong", {}, mdInline(t.slice(2, -2))));
    else if (t.startsWith("[")) {
      out.push(el("a", { href: m[2], target: "_blank", rel: "noopener noreferrer" }, t.slice(1, t.indexOf("]"))));
    } else out.push(el("em", {}, mdInline(t.slice(1, -1))));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function markdown(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let para = [];
  let list = null;
  const flush = () => {
    if (para.length) blocks.push(el("p", {}, mdInline(para.join(" "))));
    para = [];
  };
  const endList = () => { if (list) blocks.push(list); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush(); endList();
      const code = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      blocks.push(el("pre", {}, el("code", {}, code.join("\n"))));
      continue;
    }
    const head = line.match(/^\s*(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const number = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (!line.trim()) { flush(); endList(); continue; }
    if (head) { flush(); endList(); blocks.push(el("p", { class: "mdh" }, el("strong", {}, mdInline(head[2])))); continue; }
    if (bullet || number) {
      flush();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) { endList(); list = el(tag, {}); }
      list.append(el("li", {}, mdInline((bullet || number)[1])));
      continue;
    }
    endList();
    para.push(line.trim());
  }
  flush(); endList();
  return el("div", { class: "md" }, blocks);
}

function renderMessages(p) {
  const box = $("#messages");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...(p.messages || []).map((m) => {
    const bubble = el("div", { class: `msg ${m.role}` },
      // A system note (a print's outcome) quotes Bambu Studio's own words,
      // whose setting names have underscores that Markdown would read as
      // italics and drop, so it is drawn as the words it is.
      m.role === "system" ? el("p", {}, m.text) : markdown(m.text));
    if (m.version) {
      bubble.append(el("button", { type: "button", class: "chip", onclick: () => { design.viewing = m.version; renderPart(); } },
        `Version ${m.version}`));
    }
    if (m.build) bubble.append(el("p", { class: "hint" }, m.build));
    if (m.questions && m.questions.length) {
      bubble.append(el("div", { class: "row wrap" }, m.questions.map((q) => el("button", {
        type: "button", class: "chip q", onclick: () => { $("#composerText").value = `${q} — `; $("#composerText").focus(); },
      }, q))));
    }
    return bubble;
  }));
  if (atBottom || busy(p)) box.scrollTop = box.scrollHeight;
}

function renderVersions(p) {
  const vs = p.versions || [];
  $("#versions").replaceChildren(...vs.map((v) => el("button", {
    type: "button", class: `chip ${v.n === design.viewing ? "on" : ""} ${v.ok ? "" : "bad"}`,
    title: v.summary || "", onclick: () => { design.viewing = v.n; renderPart(); },
  }, `v${v.n}${v.n === p.current ? " ●" : ""}`)));
  const v = vs.find((x) => x.n === design.viewing);
  const info = $("#versionInfo");
  info.replaceChildren();
  if (!v) return;
  info.append(el("p", {}, [v.summary, fmtSize(v.size_mm), v.grams ? `≈ ${v.grams} g PLA` : null].filter(Boolean).join(" · ")));
  if (v.warnings && v.warnings.length) info.append(el("ul", { class: "warnlist" }, v.warnings.map((w) => el("li", {}, w))));
  if (v.dims) info.append(el("p", {}, Object.entries(v.dims).map(([k, val]) => `${k}: ${val}`).join(" · ")));
  if (v.ok && v.n !== p.current) {
    info.append(el("button", { type: "button", onclick: () => makeCurrent(v.n) }, `Keep working from v${v.n}`));
  }
}

async function makeCurrent(n) {
  try {
    const r = await api(`api/design/parts/${design.part.id}`, { json: { current: n } });
    design.part = r.part;
    renderPart();
  } catch (e) { toast(e.message, true); }
}

async function loadModel(p, v) {
  const holder = $("#viewer");
  const note = $("#viewerNote");
  const key = v && v.ok ? `${p.id}:${v.n}` : "";
  if (key === design.loadedKey) return;
  design.loadedKey = key;
  if (!key) {
    note.hidden = false;
    note.textContent = v ? "This version did not build." : "No version yet — describe the part to brAIn.";
    if (design.viewer) design.viewer.group.clear();
    $("#bodyList").replaceChildren();
    return;
  }
  if (!window.BambuViewer) {
    note.hidden = false;
    note.textContent = design.status && !design.status.viewer
      ? "The 3D view is not available in this image; download the 3MF to look at it."
      : "Loading the 3D view…";
    window.addEventListener("bambu-viewer-ready", () => { design.loadedKey = ""; renderPart(); }, { once: true });
    return;
  }
  note.hidden = true;
  if (!design.viewer) {
    design.viewer = new window.BambuViewer(holder);
    design.viewer.onMeasure = (m) => {
      $("#measureOut").textContent = !m ? "" : m.first ? "Pick the second point."
        : `${m.distance.toFixed(2)} mm  (ΔX ${m.dx.toFixed(2)} · ΔY ${m.dy.toFixed(2)} · ΔZ ${m.dz.toFixed(2)})`;
    };
  }
  // Each body in the colour it prints in: the script's own COLORS first,
  // then the filament brAIn suggested for the whole part (versions built
  // before COLORS existed), and only then the palette that tells bodies apart.
  const colors = v.colors || {};
  const partColour = (p.print_settings && p.print_settings.colour) || "";
  const bodies = Object.entries((v.files && v.files.bodies) || {}).map(([name, path]) => ({
    name, url: `api/design/parts/${p.id}/file?v=${v.n}&path=${encodeURIComponent(path)}`,
    color: colors[name] || partColour }));
  try {
    await design.viewer.load(bodies);
    renderBodies(bodies);
    firstHelp();
    const size = design.viewer.size();
    if (size && !$("#measureBtn").getAttribute("aria-pressed").includes("true")) {
      $("#measureOut").textContent = `Overall ${fmtSize(size)}`;
    }
    if (v.n === p.current) saveThumb(p);
  } catch (e) { note.hidden = false; note.textContent = `Could not show it: ${e.message}`; }
}

// A key under the view: each body in its colour, and a tap hides or shows
// it — how somebody looks inside a print-in-place part or at one colour.
function renderBodies(bodies) {
  const box = $("#bodyList");
  const colourOf = window.bambuFilamentColour || (() => null);
  const named = bodies.filter((b) => b.color);
  if (bodies.length < 2 && !named.length) { box.replaceChildren(); return; }
  box.replaceChildren(...bodies.map((b) => {
    const chip = el("button", { type: "button", class: "chip body", "aria-pressed": "true",
      title: `Hide or show ${b.name}` },
    el("i", { style: `background:${colourOf(b.color) || "transparent"}` }),
    b.color && !b.color.startsWith("#") ? `${b.name} · ${b.color}` : b.name);
    chip.addEventListener("click", () => {
      const on = chip.getAttribute("aria-pressed") !== "true";
      chip.setAttribute("aria-pressed", String(on));
      if (design.viewer) design.viewer.setVisible(b.name, on);
    });
    return chip;
  }));
}

// The controls, said once: the first time a part is shown on this browser
// the help opens by itself, and the ? brings it back.
function setHelp(open) {
  $("#viewHelp").hidden = !open;
  $("#viewHelpBtn").setAttribute("aria-expanded", String(open));
}

function firstHelp() {
  let seen = true;
  try { seen = localStorage.getItem("bambu.viewHelp") === "1"; } catch (_) { /* storage refused */ }
  if (seen) return;
  setHelp(true);
  try { localStorage.setItem("bambu.viewHelp", "1"); } catch (_) { /* storage refused */ }
}

(function orderHelp() {
  // The gestures for the device in hand come first; the other set stays,
  // because a laptop with a touch screen has both.
  const touch = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  const pop = $("#viewHelp");
  const first = pop.querySelector(`[data-input="${touch ? "touch" : "mouse"}"]`);
  if (first) pop.prepend(first);
})();

$("#viewHelpBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  setHelp($("#viewHelp").hidden);
});
document.addEventListener("pointerdown", (e) => {
  if (!$("#viewHelp").hidden && !e.target.closest("#viewHelp, #viewHelpBtn")) setHelp(false);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setHelp(false); });

async function saveThumb(p) {
  if (design.thumbFor === `${p.id}:${p.current}`) return;
  design.thumbFor = `${p.id}:${p.current}`;
  await new Promise((r) => setTimeout(r, 300));
  const blob = await design.viewer.snapshot();
  if (blob) fetch(`api/design/parts/${p.id}/thumb`, { method: "POST", body: blob }).catch(() => {});
}

async function send(e) {
  e.preventDefault();
  const box = $("#composerText");
  const text = box.value.trim();
  if (!text || !design.part) return;
  try {
    const r = await api(`api/design/parts/${design.part.id}/message`, { json: { text } });
    box.value = "";
    design.part = r.part;
    design.viewing = r.part.current;
    renderPart();
    pollPart();
  } catch (err) { toast(err.message, true); }
}

// --------------------------------------------------------------- print ---
const COLOUR_NAMES = { black: [0, 0, 0], white: [255, 255, 255], grey: [128, 128, 128],
  silver: [192, 192, 192], red: [200, 30, 30], orange: [240, 130, 20], yellow: [240, 210, 30],
  green: [40, 160, 60], blue: [30, 90, 200], cyan: [0, 180, 220], purple: [120, 50, 160],
  pink: [240, 120, 170], brown: [120, 80, 40], beige: [220, 200, 160], gold: [210, 170, 50] };

// "#1E9FE0" → "blue": a tray read by the colour a person would call it.
function colourName(colour) {
  const m = /^#?([0-9a-f]{6})/i.exec(String(colour || ""));
  if (!m) return String(colour || "");
  const rgb = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  let best = "", bestD = Infinity;
  for (const [name, ref] of Object.entries(COLOUR_NAMES)) {
    const d = ref.reduce((sum, v, i) => sum + (v - rgb[i]) ** 2, 0);
    if (d < bestD) { best = name; bestD = d; }
  }
  return best;
}

// Print offers three ways: brAIn does it all, the person does it here, or
// the person does it in Bambu Studio.
function openPrintChoice() {
  const ready = design.status?.brain.state === "ok";
  $("#pcAuto").disabled = !ready || busy(design.part);
  $("#pcAuto").title = ready ? "" : (design.status?.brain.sentence || "brAIn is not available.");
  $("#printChoice").showModal();
}

const AUTO_PRINT = "Print this part now. Pick the printer, the filament for each body and the "
  + "settings yourself, and ask me only if something critical is unknown.";

async function autoPrint() {
  $("#printChoice").close();
  if (design.viewing !== design.part.current) {
    toast(`brAIn prints the current version, v${design.part.current}.`);
  }
  try {
    const r = await api(`api/design/parts/${design.part.id}/message`, { json: { text: AUTO_PRINT } });
    design.part = r.part;
    renderPart();
    pollPart();
  } catch (err) { toast(err.message, true); }
}

async function openInStudio() {
  $("#printChoice").close();
  try {
    const r = await api(`api/design/parts/${design.part.id}/studio`, { json: { version: design.viewing } });
    show("studio");
    toast(`Opening it in Bambu Studio. ${r.note || ""}`.trim());
  } catch (err) { toast(err.message, true); }
}

async function openDesignPrint() {
  $("#printChoice").close();
  const printers = (state.data && state.data.printers) || [];
  if (!printers.length) { toast("Add a printer on the Printers tab first.", true); return; }
  $("#dpPrinter").replaceChildren(...printers.map((p) => el("option", { value: p.id },
    `${p.name}${p.online ? "" : " (offline)"}`)));
  const s = design.part.print_settings || {};
  try {
    buildOptions($("#dpOptions"), await optionCatalog(), s, { slice: true });
  } catch (e) { $("#dpOptions").replaceChildren(el("p", { class: "warn" }, e.message)); }
  $("#designPrint").showModal();
  await loadPlan();
}

async function loadPlan() {
  const printer = $("#dpPrinter").value;
  const trays = $("#dpTrays");
  trays.replaceChildren(el("legend", {}, "Filament"), el("p", { class: "hint" }, "Reading the printer…"));
  try {
    const plan = await api(`api/design/parts/${design.part.id}/plan?printer=${encodeURIComponent(printer)}`);
    const s = plan.settings || {};
    $("#dpAdvice").textContent = [
      s.material || s.colour ? `brAIn suggests ${[s.colour, s.material].filter(Boolean).join(" ")}.` : "",
      s.why || ""].filter(Boolean).join(" ");
    $("#dpProfiles").textContent = plan.problem ? plan.problem
      : `Slicing with ${plan.machine} · ${plan.process} · ${plan.filament} (filament profile follows the tray you pick).`;
    const options = plan.trays.map((t) => el("label", { class: "check tray" },
      el("input", { type: "radio", name: "slot", value: String(t.slot), checked: t.slot === plan.recommended_slot }),
      el("i", { style: `background:${t.colour || "transparent"}` }),
      `AMS ${t.slot + 1}: ${t.type}${t.remaining != null ? ` · ${t.remaining}%` : ""}`,
      t.slot === plan.recommended_slot ? el("span", { class: "chip" }, "best match") : null));
    options.push(el("label", { class: "check tray" },
      el("input", { type: "radio", name: "slot", value: "external", checked: plan.recommended_slot == null }),
      `External spool${s.material ? ` (load ${[s.colour, s.material].filter(Boolean).join(" ")})` : ""}`));
    if (plan.bodies && plan.bodies.length > 1) {
      // A part in several bodies: a tray for each, starting from its colour.
      const rows = plan.bodies.map((b) => el("label", { class: "bodytray" },
        el("span", {}, el("i", { style: `background:${b.colour || "transparent"}` }), ` ${b.name}`),
        el("select", { name: `body:${b.name}` },
          ...plan.trays.map((t) => el("option", { value: String(t.slot), selected: t.slot === b.recommended_slot },
            `AMS ${t.slot + 1}: ${[colourName(t.colour), t.type].filter(Boolean).join(" ")}${t.remaining != null ? ` · ${t.remaining}%` : ""}`)),
          el("option", { value: "external", selected: b.recommended_slot == null || !plan.trays.length },
            "External spool"))));
      const missing = plan.bodies.filter((b) => b.recommended_slot == null)
        .map((b) => `${colourName(b.colour) || "its colour"} for ${b.name}`);
      trays.replaceChildren(el("legend", {}, "Filament for each body"), ...rows,
        missing.length ? el("p", { class: "warn" }, `Not loaded: ${missing.join(", ")}. Load it into the AMS, or pick another tray.`) : null,
        el("p", { class: "hint" }, "Bodies on different trays print in those colours; the external spool suits a one-colour print."));
      return;
    }
    trays.replaceChildren(el("legend", {}, "Filament"), ...options);
    if (plan.trays.length && plan.recommended_slot == null && s.material) {
      $("#dpAdvice").textContent += ` No ${s.material} is loaded in the AMS — load it, or pick another tray.`;
    }
  } catch (e) { trays.replaceChildren(el("legend", {}, "Filament"), el("p", { class: "warn" }, e.message)); }
}

async function submitDesignPrint(e) {
  if (e.submitter && e.submitter.value !== "go") return;
  const f = new FormData(e.target);
  const chosen = readOptions(e.target);
  const settings = { ...chosen.settings, ...chosen.start };
  const slot = f.get("slot");
  const slots = {};
  for (const [key, value] of f.entries()) {
    if (key.startsWith("body:")) slots[key.slice(5)] = value === "external" ? "external" : Number(value);
  }
  try {
    await api(`api/design/parts/${design.part.id}/print`, { json: {
      printer: f.get("printer"), version: design.viewing, print_settings: settings,
      ...(Object.keys(slots).length ? { slots }
        : { slot: slot === "external" || slot == null ? "external" : Number(slot) }),
      timelapse: Boolean(chosen.start.timelapse) } });
    toast("Slicing and sending it to the printer — follow it on the Printers tab.");
    pollPart();
  } catch (err) { toast(err.message, true); }
}

async function rename() {
  const name = $("#partName").value.trim();
  if (!design.part || !name || name === design.part.name) return;
  try {
    design.part = (await api(`api/design/parts/${design.part.id}`, { json: { name } })).part;
    designStatus();
  } catch (e) { toast(e.message, true); }
}

async function removePart() {
  if (!design.part || !confirm(`Delete ${design.part.name} and every version of it?`)) return;
  try {
    await api(`api/design/parts/${design.part.id}`, { method: "DELETE" });
    closePart();
  } catch (e) { toast(e.message, true); }
}

$("#newPart").addEventListener("click", newPart);
$("#partBack").addEventListener("click", closePart);
$("#composer").addEventListener("submit", send);
$("#composerText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#partName").addEventListener("change", rename);
$("#partDelete").addEventListener("click", removePart);
$("#partPrint").addEventListener("click", openPrintChoice);
$("#pcAuto").addEventListener("click", autoPrint);
$("#pcManual").addEventListener("click", openDesignPrint);
$("#pcStudio").addEventListener("click", openInStudio);
$("#pcCancel").addEventListener("click", () => $("#printChoice").close());
$("#dpPrinter").addEventListener("change", loadPlan);
$("#designPrintForm").addEventListener("submit", submitDesignPrint);
$("#dpCancel").addEventListener("click", () => $("#designPrint").close());
document.querySelectorAll("[data-view3d]").forEach((b) => b.addEventListener("click", () => design.viewer && design.viewer.view(b.dataset.view3d)));
$("#measureBtn").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  if (design.viewer) design.viewer.setMeasuring(on);
  const touch = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  $("#measureOut").textContent = on ? `${touch ? "Tap" : "Click"} two points on the part.` : "";
});
$("#wireBtn").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  if (design.viewer) design.viewer.setWireframe(on);
});
// The 3D view is a module; it loads only when there is a part to show, and
// a panel without the vendored three.js simply never gets one.
if (!document.querySelector('script[src="viewer.js"]')) {
  const s = document.createElement("script");
  s.type = "module";
  s.src = "viewer.js";
  document.head.append(s);
}
designStatus();
setInterval(() => { if (!design.part) designStatus(); }, 15000);
