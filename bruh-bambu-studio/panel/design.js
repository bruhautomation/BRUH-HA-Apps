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
  ["thinking", "building", "fixing"].includes(p.state) ? el("span", { class: "chip live" }, "working") : null)));
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
  return ["thinking", "building", "fixing"].includes(part.state);
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

function renderMessages(p) {
  const box = $("#messages");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...(p.messages || []).map((m) => {
    const bubble = el("div", { class: `msg ${m.role}` }, el("p", {}, m.text));
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
  const colors = {};
  const bodies = Object.entries((v.files && v.files.bodies) || {}).map(([name, path]) => ({
    name, url: `api/design/parts/${p.id}/file?v=${v.n}&path=${encodeURIComponent(path)}`, color: colors[name] }));
  try {
    await design.viewer.load(bodies);
    const size = design.viewer.size();
    if (size && !$("#measureBtn").getAttribute("aria-pressed").includes("true")) {
      $("#measureOut").textContent = `Overall ${fmtSize(size)}`;
    }
    if (v.n === p.current) saveThumb(p);
  } catch (e) { note.hidden = false; note.textContent = `Could not show it: ${e.message}`; }
}

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
async function openDesignPrint() {
  const printers = (state.data && state.data.printers) || [];
  if (!printers.length) { toast("Add a printer on the Printers tab first.", true); return; }
  $("#dpPrinter").replaceChildren(...printers.map((p) => el("option", { value: p.id },
    `${p.name}${p.online ? "" : " (offline)"}`)));
  const s = design.part.print_settings || {};
  const f = $("#designPrintForm");
  for (const key of ["layer_height", "walls", "infill_percent", "supports", "brim"]) f[key].value = s[key] ?? "";
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
    trays.replaceChildren(el("legend", {}, "Filament"), ...options);
    if (plan.trays.length && plan.recommended_slot == null && s.material) {
      $("#dpAdvice").textContent += ` No ${s.material} is loaded in the AMS — load it, or pick another tray.`;
    }
  } catch (e) { trays.replaceChildren(el("legend", {}, "Filament"), el("p", { class: "warn" }, e.message)); }
}

async function submitDesignPrint(e) {
  if (e.submitter && e.submitter.value !== "go") return;
  const f = new FormData(e.target);
  const settings = {};
  for (const key of ["layer_height", "walls", "infill_percent"]) if (f.get(key)) settings[key] = Number(f.get(key));
  for (const key of ["supports", "brim"]) if (f.get(key)) settings[key] = f.get(key);
  const slot = f.get("slot");
  try {
    await api(`api/design/parts/${design.part.id}/print`, { json: {
      printer: f.get("printer"), version: design.viewing, print_settings: settings,
      slot: slot === "external" || slot == null ? "external" : Number(slot),
      timelapse: f.get("timelapse") === "on" } });
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
$("#partPrint").addEventListener("click", openDesignPrint);
$("#dpPrinter").addEventListener("change", loadPlan);
$("#designPrintForm").addEventListener("submit", submitDesignPrint);
$("#dpCancel").addEventListener("click", () => $("#designPrint").close());
document.querySelectorAll("[data-view3d]").forEach((b) => b.addEventListener("click", () => design.viewer && design.viewer.view(b.dataset.view3d)));
$("#measureBtn").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  if (design.viewer) design.viewer.setMeasuring(on);
  $("#measureOut").textContent = on ? "Tap two points on the part." : "";
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
