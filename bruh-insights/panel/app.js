/* BRUH Insights — panel logic.
   All URLs are relative: the HA Supervisor proxies us under
   /api/hassio_ingress/<token>/, so absolute paths would escape the ingress. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const state = {
  status: null,
  insights: [],
  filter: "all",
  pollTimer: null,
  setupTimer: null,
  frameSeq: 0,
};

// ---------------------------------------------------------------- helpers

async function api(path, opts = {}) {
  const resp = await fetch(path.replace(/^\//, ""), {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
  return resp.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

function timeAgo(iso) {
  if (!iso) return "";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 90) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)} h ago`;
  return `${Math.round(secs / 86400)} d ago`;
}

// Height auto-sizing: a script appended to every srcdoc posts its content
// height; sandboxed frames can't be measured from outside.
const SIZE_SNIPPET = (id) => `<script>(function(){var last=0;function post(){var b=document.body;if(!b)return;var h=Math.ceil(Math.max(b.offsetHeight,b.getBoundingClientRect().height));if(h>0&&Math.abs(h-last)>2){last=h;parent.postMessage({type:"bruh-size",id:${JSON.stringify(id)},h:h},"*");}}try{new ResizeObserver(post).observe(document.body);}catch(e){}window.addEventListener("load",post);setTimeout(post,400);setTimeout(post,1200);})();<\/script>`;

window.addEventListener("message", (ev) => {
  const d = ev.data;
  if (!d || d.type !== "bruh-size" || typeof d.h !== "number") return;
  const frame = document.querySelector(`iframe[data-frame="${CSS.escape(String(d.id))}"]`);
  if (frame) frame.style.height = Math.min(Math.max(d.h, 120), 760) + "px";
});

// ------------------------------------------------------------------ auth UI

function renderAuth() {
  const s = state.status;
  const chip = $("#authChip");
  const text = $("#authChipText");
  chip.classList.remove("ok", "warn", "bad", "busy");
  if (!s) return;
  if (!s.authenticated) {
    text.textContent = "Not connected";
    chip.classList.add("warn");
  } else if (s.auth_check.state === "checking") {
    text.textContent = "Verifying Claude…";
    chip.classList.add("busy");
  } else if (s.auth_check.state === "failed") {
    text.textContent = "Claude auth failed";
    chip.classList.add("bad");
    chip.title = s.auth_check.error || "";
  } else {
    text.textContent = s.auth_type === "api_key" ? "Claude · API key" : "Claude · subscription";
    chip.classList.add("ok");
  }
  $("#setup").classList.toggle("hidden", s.authenticated);
  $("#dash").classList.toggle("hidden", !s.authenticated);
  $("#refreshAll").classList.toggle("hidden", !s.authenticated);
}

function bindSetup() {
  document.querySelectorAll(".setup .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".setup .tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".setup .pane").forEach((p) =>
        p.classList.toggle("active", p.dataset.pane === tab.dataset.pane));
    });
  });

  $("#setupStart").addEventListener("click", async () => {
    $("#setupStart").disabled = true;
    $("#setupErr").classList.add("hidden");
    try {
      await api("api/auth/setup/start", { method: "POST" });
      pollSetup();
    } catch (e) {
      showSetupError(e.message);
      $("#setupStart").disabled = false;
    }
  });

  $("#setupSubmit").addEventListener("click", async () => {
    const code = $("#setupCode").value.trim();
    if (!code) return;
    $("#setupSubmit").disabled = true;
    try {
      await api("api/auth/setup/code", { method: "POST", body: JSON.stringify({ code }) });
    } catch (e) {
      showSetupError(e.message);
      $("#setupSubmit").disabled = false;
    }
  });

  $("#setupCancel").addEventListener("click", async () => {
    await api("api/auth/setup/cancel", { method: "POST" }).catch(() => {});
    resetSetupUI();
  });

  $("#pasteSave").addEventListener("click", () => saveToken($("#pasteToken").value));
  $("#apiSave").addEventListener("click", () => saveToken($("#apiKey").value));
}

async function saveToken(value) {
  value = (value || "").trim();
  if (!value) return;
  try {
    await api("api/auth/token", { method: "POST", body: JSON.stringify({ token: value }) });
    toast("Connected! Verifying with Claude…");
    await refreshStatus();
  } catch (e) {
    toast(e.message);
  }
}

function showSetupError(msg) {
  const box = $("#setupErr");
  box.textContent = msg;
  box.classList.remove("hidden");
}

function resetSetupUI() {
  clearTimeout(state.setupTimer);
  $("#setupStart").disabled = false;
  $("#setupUrlBox").classList.add("hidden");
  $("#setupCodeRow").classList.add("hidden");
  $("#setupPhase").classList.add("hidden");
  $("#setupSubmit").disabled = false;
}

async function pollSetup() {
  clearTimeout(state.setupTimer);
  let st;
  try {
    st = await api("api/auth/setup/status");
    pollSetup.failures = 0;
  } catch (e) {
    // NEVER let a transient fetch failure kill the poll loop (mobile apps
    // suspend the webview in the background and abort in-flight requests —
    // previously that left the UI frozen on "Exchanging code…" even after
    // the backend had finished). Keep retrying quietly.
    pollSetup.failures = (pollSetup.failures || 0) + 1;
    if (pollSetup.failures > 5) showSetupError("Connection to the add-on lost — retrying…");
    state.setupTimer = setTimeout(pollSetup, 3000);
    return;
  }
  const phaseChip = $("#setupPhase");
  const phaseText = $("#setupPhaseText");
  phaseChip.classList.remove("hidden");
  phaseChip.classList.add("busy");
  // Surface flow errors whatever the phase — a failed code exchange loops
  // back to awaiting_code with a fresh link, and the error explains that.
  if (st.error) showSetupError(st.error);
  else $("#setupErr").classList.add("hidden");
  const detail = $("#setupDetail");
  if (st.phase === "working" && st.detail) {
    detail.textContent = st.detail;
    detail.classList.remove("hidden");
  } else {
    detail.classList.add("hidden");
  }
  if (st.phase === "starting") {
    phaseText.textContent = st.error ? "Getting a fresh link…" : "Preparing sign-in…";
    $("#setupUrlBox").classList.add("hidden");
    $("#setupSubmit").disabled = true;
  }
  if (st.phase === "awaiting_code") {
    phaseText.textContent = "Waiting for your code";
    if (st.url) {
      $("#setupUrlBox").classList.remove("hidden");
      const a = $("#setupUrl");
      a.href = st.url;
      a.textContent = st.url;
    }
    $("#setupCodeRow").classList.remove("hidden");
    $("#setupSubmit").disabled = false;
    if (st.error && pollSetup.lastPhase !== "awaiting_code") {
      // fresh link after a failed attempt — the old code is dead
      $("#setupCode").value = "";
    }
  }
  if (st.phase === "working") {
    if (pollSetup.lastPhase !== "working") pollSetup.workingSince = Date.now();
    const secs = Math.round((Date.now() - (pollSetup.workingSince || Date.now())) / 1000);
    phaseText.textContent = secs > 15
      ? `Exchanging code… ${secs}s (can take a minute — we'll keep nudging it)`
      : "Exchanging code…";
    $("#setupCodeRow").classList.remove("hidden"); // keep Cancel reachable
    $("#setupSubmit").disabled = true;
  }
  pollSetup.lastPhase = st.phase;
  if (st.phase === "done") {
    phaseChip.classList.remove("busy");
    phaseChip.classList.add("ok");
    phaseText.textContent = "Connected!";
    toast("Claude account connected 🎉");
    resetSetupUI();
    await refreshStatus();
    return;
  }
  if (st.phase === "error") {
    showSetupError(st.error || "Sign-in failed — try again or use the token tab.");
    resetSetupUI();
    return;
  }
  state.setupTimer = setTimeout(pollSetup, 1500);
}

// ------------------------------------------------------------------ cards

function jobFor(id) {
  return (state.status && state.status.jobs && state.status.jobs[id]) || {};
}

function insightFor(id) {
  return state.insights.find((i) => i.id === id);
}

function phaseLabel(jobState) {
  return {
    queued: "Queued…",
    collecting: "Gathering your home's data…",
    generating: "Claude is analyzing & designing…",
    parsing: "Rendering visualization…",
  }[jobState] || "Working…";
}

function makeFrame(insight) {
  const wrapper = el("div", "viz");
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("title", insight.title || "Insight visualization");
  frame.setAttribute("loading", "lazy");
  const frameId = `${insight.id}-${state.frameSeq++}`;
  frame.dataset.frame = frameId;
  frame.srcdoc = insight.html + SIZE_SNIPPET(frameId);
  wrapper.appendChild(frame);
  return wrapper;
}

function makeCard(catInfo, insight) {
  const id = insight ? insight.id : catInfo.id;
  const job = jobFor(id);
  const active = ["queued", "collecting", "generating", "parsing"].includes(job.state);
  const card = el("article", "card" + (active ? " pending" : ""));
  card.dataset.id = id;

  // head
  const head = el("div", "card-head");
  head.appendChild(el("span", "cicon", (insight && insight.icon) || (catInfo && catInfo.icon) || "✨"));
  const titles = el("div", "ctitles");
  const catName = insight ? insight.category_title || "Custom" : catInfo.title;
  titles.appendChild(el("div", "cat", catName));
  titles.appendChild(el("h3", null,
    insight ? insight.title : (catInfo ? catInfo.title : "Custom insight")));
  head.appendChild(titles);
  const actions = el("div", "actions");
  if (!active) {
    const regen = el("button", "btn icon", "↻");
    regen.title = "Regenerate";
    regen.addEventListener("click", () => generate(id, insight && insight.question));
    actions.appendChild(regen);
  }
  if (insight) {
    const expand = el("button", "btn icon", "⤢");
    expand.title = "Expand";
    expand.addEventListener("click", () => openModal(insight));
    actions.appendChild(expand);
    if (insight.category === "custom") {
      const del = el("button", "btn icon", "✕");
      del.title = "Delete";
      del.addEventListener("click", async () => {
        await api(`api/insight/${id}`, { method: "DELETE" }).catch(() => {});
        await refreshInsights();
        render();
      });
      actions.appendChild(del);
    }
  }
  head.appendChild(actions);
  card.appendChild(head);

  if (insight && insight.question) {
    card.appendChild(el("div", "summary", `“${insight.question}”`));
  }

  // body
  if (active) {
    const phase = el("div", "phase");
    phase.appendChild(el("span", "orbit"));
    phase.appendChild(el("span", null, phaseLabel(job.state)));
    card.appendChild(phase);
    card.appendChild(el("div", "viz-skel"));
  } else if (insight) {
    if (insight.summary) card.appendChild(el("div", "summary", insight.summary));
    if (insight.highlights && insight.highlights.length) {
      const hls = el("div", "highlights");
      insight.highlights.forEach((h) => {
        if (!h || !h.label) return;
        const box = el("div", "hl" + (h.status ? ` status-${h.status}` : ""));
        box.appendChild(el("div", "l", String(h.label)));
        box.appendChild(el("div", "v", String(h.value != null ? h.value : "—")));
        if (h.delta) box.appendChild(el("div", "d", String(h.delta)));
        hls.appendChild(box);
      });
      card.appendChild(hls);
    }
    card.appendChild(makeFrame(insight));
    const foot = el("div", "foot");
    foot.appendChild(el("span", null, `Updated ${timeAgo(insight.generated_at)}`));
    foot.appendChild(el("span", "spacer"));
    if (insight.meta && insight.meta.duration_ms) {
      foot.appendChild(el("span", null, `${(insight.meta.duration_ms / 1000).toFixed(0)}s`));
    }
    card.appendChild(foot);
  } else if (job.state === "error") {
    const box = el("div", "errbox");
    box.appendChild(el("div", null, "Generation failed"));
    const code = el("code", null, job.error || "unknown error");
    box.appendChild(code);
    const retry = el("button", "btn small", "Try again");
    retry.style.marginTop = "10px";
    retry.addEventListener("click", () => generate(id));
    box.appendChild(retry);
    card.appendChild(box);
  } else {
    const box = el("div", "empty");
    box.appendChild(el("div", "big", catInfo ? catInfo.icon : "✨"));
    box.appendChild(el("div", null, catInfo ? catInfo.description : ""));
    const go = el("button", "btn primary small", "Generate insight");
    go.style.marginTop = "12px";
    go.addEventListener("click", () => generate(id));
    box.appendChild(go);
    card.appendChild(box);
  }
  return card;
}

function render() {
  const s = state.status;
  if (!s) return;
  renderAuth();
  if (!s.authenticated) return;

  // filter chips
  const filters = $("#filters");
  filters.textContent = "";
  const chips = [{ id: "all", title: "All", icon: "✦" }]
    .concat(s.categories.map((c) => ({ id: c.id, title: c.title, icon: c.icon })));
  if (state.insights.some((i) => i.category === "custom")) {
    chips.push({ id: "custom", title: "Asked", icon: "💬" });
  }
  chips.forEach((c) => {
    const chip = el("button", "fchip" + (state.filter === c.id ? " active" : ""),
      `${c.icon} ${c.title}`);
    chip.addEventListener("click", () => { state.filter = c.id; render(); });
    filters.appendChild(chip);
  });

  // cards
  const grid = $("#grid");
  grid.textContent = "";
  const customs = state.insights.filter((i) => i.category === "custom");
  // custom in-flight jobs that have no stored insight yet
  Object.keys(s.jobs || {}).forEach((jid) => {
    if (jid.startsWith("custom-") && !insightFor(jid) &&
        ["queued", "collecting", "generating", "parsing", "error"].includes(s.jobs[jid].state)) {
      customs.unshift({ id: jid, category: "custom", category_title: "Custom", icon: "✨", virtual: true });
    }
  });
  if (state.filter === "all" || state.filter === "custom") {
    customs.forEach((i) => {
      grid.appendChild(makeCard(null, i.virtual ? null : i));
      if (i.virtual) grid.lastChild.dataset.id = i.id;
    });
  }
  if (state.filter !== "custom") {
    s.categories.forEach((c) => {
      if (state.filter !== "all" && state.filter !== c.id) return;
      grid.appendChild(makeCard(c, insightFor(c.id)));
    });
  }
}

// Rebuild only when something meaningful changed (avoid iframe reloads)
let lastRenderKey = "";
function renderIfChanged() {
  const s = state.status;
  const key = JSON.stringify({
    auth: s && [s.authenticated, s.auth_check.state],
    jobs: s && s.jobs,
    gen: state.insights.map((i) => i.id + i.generated_at),
    filter: state.filter,
  });
  if (key !== lastRenderKey) {
    lastRenderKey = key;
    render();
  }
}

// ------------------------------------------------------------------ actions

async function generate(categoryOrId, question) {
  try {
    const body = question
      ? { question }
      : (categoryOrId && categoryOrId.startsWith("custom-")
        ? null // regenerating a custom card without its question isn't possible
        : { category: categoryOrId });
    if (!body) return;
    await api("api/generate", { method: "POST", body: JSON.stringify(body) });
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
}

async function refreshStatus() {
  state.status = await api("api/status");
  renderIfChanged();
}

async function refreshInsights() {
  const data = await api("api/insights");
  state.insights = data.insights || [];
}

function anyActive() {
  const jobs = (state.status && state.status.jobs) || {};
  return Object.values(jobs).some((j) =>
    ["queued", "collecting", "generating", "parsing"].includes(j.state));
}

function fastPoll() {
  clearTimeout(state.pollTimer);
  const tick = async () => {
    const hadActive = anyActive();
    await refreshStatus().catch(() => {});
    if (hadActive && !anyActive()) {
      await refreshInsights().catch(() => {});
    }
    renderIfChanged();
    state.pollTimer = setTimeout(tick, anyActive() ? 2500 : 20000);
  };
  state.pollTimer = setTimeout(tick, 2500);
}

// ------------------------------------------------------------------ modal

function openModal(insight) {
  $("#modalIcon").textContent = insight.icon || "✨";
  $("#modalTitle").textContent = insight.title || "";
  const frame = $("#modalFrame");
  const frameId = `modal-${state.frameSeq++}`;
  frame.dataset.frame = frameId;
  frame.srcdoc = insight.html + SIZE_SNIPPET(frameId);
  $("#modal").classList.add("open");
}

$("#modalClose").addEventListener("click", () => $("#modal").classList.remove("open"));
$("#modal").addEventListener("click", (ev) => {
  if (ev.target === $("#modal")) $("#modal").classList.remove("open");
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") $("#modal").classList.remove("open");
});

// ------------------------------------------------------------------ boot

$("#refreshAll").addEventListener("click", async () => {
  try {
    const res = await api("api/generate_all", { method: "POST" });
    toast(res.queued.length ? `Refreshing ${res.queued.length} insights…` : "Already refreshing");
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
});

$("#askForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#askInput").value.trim();
  if (!q) return;
  $("#askInput").value = "";
  toast("Asking Claude about your home…");
  await generate(null, q);
});

// Coming back to the tab/app: poll immediately — mobile webviews suspend
// timers in the background, so the completed state may be waiting for us.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  refreshStatus().then(async () => {
    if (anyActive()) return;
    await refreshInsights().catch(() => {});
    renderIfChanged();
  }).catch(() => {});
  api("api/auth/setup/status").then((st) => {
    if (["starting", "awaiting_code", "working", "done"].includes(st.phase)) pollSetup();
  }).catch(() => {});
});

(async function init() {
  bindSetup();
  try {
    await Promise.all([refreshStatus(), refreshInsights()]);
  } catch (e) {
    toast("Could not reach the add-on: " + e.message);
  }
  render();
  fastPoll();
  // resume a guided sign-in if one is mid-flight (page reload)
  try {
    const st = await api("api/auth/setup/status");
    if (["starting", "awaiting_code", "working"].includes(st.phase)) pollSetup();
  } catch (e) { /* ignore */ }
})();
