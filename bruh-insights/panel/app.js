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
// Icon-only controls get an instant styled tooltip (CSS [data-tip]) instead
// of the browser's sluggish native title bubble, plus a matching aria-label.
const tip = (node, text) => {
  node.dataset.tip = text;
  node.setAttribute("aria-label", text);
  return node;
};

const state = {
  status: null,
  insights: [],
  filter: "all",
  pollTimer: null,
  setupTimer: null,
  frameSeq: 0,
  history: {},    // id -> [{ts, generated_at, title}] newest first (lazy)
  prevLatest: {}, // id -> full previous-run object (for "prev:" diffs)
  viewing: {},    // id -> {ts, data, prev} when a card is pinned to a past run
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

// ------------------------------------------------------- modal scroll lock
// Freezing the body while a modal is open stops the page behind the overlay
// from scrolling along with it (double-scroll bug, esp. iOS/ingress webview).
const modalLock = { y: 0 };

function syncModalLock() {
  const anyOpen = !!document.querySelector(".modal.open");
  const locked = document.body.classList.contains("modal-open");
  if (anyOpen && !locked) {
    modalLock.y = window.scrollY || document.documentElement.scrollTop || 0;
    document.body.style.top = `-${modalLock.y}px`;
    document.body.classList.add("modal-open");
  } else if (!anyOpen && locked) {
    document.body.classList.remove("modal-open");
    document.body.style.top = "";
    window.scrollTo(0, modalLock.y);
  }
}

function openBox(sel) {
  $(sel).classList.add("open");
  syncModalLock();
}

function closeBox(sel) {
  $(sel).classList.remove("open");
  syncModalLock();
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
  } else if (s.auth_source === "shared") {
    text.textContent = "Claude · shared login";
    chip.classList.add("ok");
    chip.title = "Using BRUH Terminal's shared login";
  } else {
    text.textContent = s.auth_type === "api_key" ? "Claude · API key" : "Claude · subscription";
    chip.classList.add("ok");
  }
  $("#setup").classList.toggle("hidden", s.authenticated);
  $("#dash").classList.toggle("hidden", !s.authenticated);
  $("#refreshAll").classList.toggle("hidden", !s.authenticated);
  $("#newInsight").classList.toggle("hidden", !s.authenticated);
  $("#knowledgeBtn").classList.toggle("hidden", !s.authenticated);
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

// ------------------------------------------------------- insight history

// generated_at ISO → history filename stamp ("2026-07-19T08:30:00" → "…T08-30-00")
function stampOf(iso) {
  return String(iso || "").replace(/:/g, "-");
}

function fmtRun(ts) {
  const d = new Date(ts.slice(0, 10) + "T" + ts.slice(11).replace(/-/g, ":"));
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

async function loadHistory(id) {
  if (state.history[id]) return state.history[id];
  const data = await api(`api/insight/${id}/history`).catch(() => ({ runs: [] }));
  const runs = data.runs || [];
  state.history[id] = runs;
  // fetch the run just before "latest" so highlight diffs work on the live card
  const ins = insightFor(id);
  if (ins && !state.prevLatest[id]) {
    const prev = runs.find((r) => r.ts !== stampOf(ins.generated_at));
    if (prev) {
      state.prevLatest[id] =
        await api(`api/insight/${id}/history/${prev.ts}`).catch(() => null);
    }
  }
  return runs;
}

async function viewRun(id, ts) {
  if (!ts) {
    delete state.viewing[id];
    renderIfChanged();
    return;
  }
  try {
    const data = await api(`api/insight/${id}/history/${ts}`);
    const runs = await loadHistory(id);
    const idx = runs.findIndex((r) => r.ts === ts);
    let prev = null;
    if (idx >= 0 && idx + 1 < runs.length) {
      prev = await api(`api/insight/${id}/history/${runs[idx + 1].ts}`).catch(() => null);
    }
    state.viewing[id] = { ts, data, prev };
    renderIfChanged();
  } catch (e) {
    toast(e.message);
  }
}

// ["" (latest), ts, ts, …] oldest last — the latest run's own history copy
// (same stamp as the live card) is folded into "Latest"
function historyEntries(id, insight) {
  const latestStamp = stampOf(insight.generated_at);
  return [""].concat(
    (state.history[id] || []).filter((r) => r.ts !== latestStamp).map((r) => r.ts));
}

async function stepRun(id, insight, dir) {
  await loadHistory(id);
  const entries = historyEntries(id, insight);
  const cur = state.viewing[id] ? state.viewing[id].ts : "";
  let idx = entries.indexOf(cur);
  if (idx === -1) idx = 0;
  const next = Math.min(Math.max(idx + dir, 0), entries.length - 1);
  if (next === idx) return;
  viewRun(id, entries[next] || null);
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

function makeQuestions(insight) {
  const wrap = el("div", "questions");
  insight.questions.forEach((q) => {
    const row = el("div", "qrow");
    const head = el("div", "qhead");
    head.appendChild(el("div", "qtext", `❓ ${q}`));
    const dis = el("button", "btn icon qdismiss", "✕");
    dis.type = "button";
    tip(dis, "Not relevant — tell Insights it's on the wrong track; this won't be asked again");
    dis.addEventListener("click", async () => {
      dis.disabled = true;
      try {
        await api("api/questions/dismiss", {
          method: "POST",
          body: JSON.stringify({ insight_id: insight.id, question: q }),
        });
        toast("Dismissed — Insights will drop that line of inquiry");
        await refreshInsights();
        renderIfChanged();
      } catch (e) {
        toast(e.message);
        dis.disabled = false;
      }
    });
    head.appendChild(dis);
    row.appendChild(head);
    const form = el("form", "qform");
    const input = el("input");
    input.type = "text";
    input.maxLength = 500;
    input.placeholder = "Answer to help future insights…";
    const btn = el("button", "btn small primary", "Send");
    btn.type = "submit";
    form.appendChild(input);
    form.appendChild(btn);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const answer = input.value.trim();
      if (!answer) return;
      btn.disabled = true;
      try {
        await api("api/questions/answer", {
          method: "POST",
          body: JSON.stringify({ insight_id: insight.id, question: q, answer }),
        });
        toast("Answer saved — the home will remember it");
        await refreshInsights();
        renderIfChanged();
      } catch (e) {
        toast(e.message);
        btn.disabled = false;
      }
    });
    row.appendChild(form);
    wrap.appendChild(row);
  });
  return wrap;
}

function makeHistoryControls(id, insight, view) {
  const wrap = el("span", "hist");
  const older = el("button", "btn icon hstep", "‹");
  tip(older, "Older run");
  older.addEventListener("click", () => stepRun(id, insight, 1));
  const sel = document.createElement("select");
  sel.className = "histsel";
  sel.title = "View a past run";
  const populate = () => {
    sel.textContent = "";
    historyEntries(id, insight).forEach((ts) => {
      const opt = document.createElement("option");
      opt.value = ts;
      opt.textContent = ts ? fmtRun(ts) : "Latest";
      sel.appendChild(opt);
    });
    sel.value = view ? view.ts : "";
  };
  if (state.history[id]) {
    populate();
  } else {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Latest";
    sel.appendChild(opt);
    // lazy-load past runs on first interaction
    sel.addEventListener("focus", async () => {
      await loadHistory(id);
      populate();
    }, { once: true });
  }
  sel.addEventListener("change", () => viewRun(id, sel.value || null));
  const newer = el("button", "btn icon hstep", "›");
  tip(newer, "Newer run");
  newer.addEventListener("click", () => stepRun(id, insight, -1));
  wrap.appendChild(older);
  wrap.appendChild(sel);
  wrap.appendChild(newer);
  return wrap;
}

function makeCard(catInfo, insight) {
  const id = insight ? insight.id : catInfo.id;
  const job = jobFor(id);
  const view = insight ? state.viewing[id] : null;
  const shown = view && view.data ? view.data : insight;
  const active = !view && ["queued", "collecting", "generating", "parsing"].includes(job.state);
  const disabled = !!(catInfo && catInfo.enabled === false);
  const card = el("article", "card" + (active ? " pending" : "") + (disabled ? " off" : ""));
  card.dataset.id = id;

  // head
  const head = el("div", "card-head");
  head.appendChild(el("span", "cicon", (shown && shown.icon) || (catInfo && catInfo.icon) || "✨"));
  const titles = el("div", "ctitles");
  const catName = insight ? (shown.category_title || "Custom") : catInfo.title;
  const catRow = el("div", "cat", catName);
  if (catInfo && catInfo.focus_overridden) {
    catRow.appendChild(el("span", "badge", "custom prompt"));
  }
  if (disabled) catRow.appendChild(el("span", "badge off", "disabled"));
  titles.appendChild(catRow);
  titles.appendChild(el("h3", null,
    shown ? shown.title : (catInfo ? catInfo.title : "Custom insight")));
  head.appendChild(titles);
  const actions = el("div", "actions");
  if (disabled) {
    const enable = el("button", "btn small", "Enable");
    enable.addEventListener("click", async () => {
      const path = catInfo.user ? `api/user_category/${id}` : `api/prompt/${id}`;
      try {
        await api(path, { method: "PUT", body: JSON.stringify({ enabled: true }) });
        await refreshStatus();
        render();
      } catch (e) { toast(e.message); }
    });
    actions.appendChild(enable);
  }
  if (!active && !view) {
    const regen = el("button", "btn icon", "↻");
    tip(regen, "Regenerate");
    regen.addEventListener("click", () => generate(id, insight && insight.question));
    actions.appendChild(regen);
  }
  if (catInfo) {
    const edit = el("button", "btn icon", "✎");
    tip(edit, catInfo.user ? "Edit insight" : "Edit prompt");
    edit.addEventListener("click", () =>
      catInfo.user ? openUserEdit(catInfo) : openEdit(catInfo));
    actions.appendChild(edit);
    const fb = el("button", "btn icon", "💬");
    tip(fb, "Give feedback — remembered for every future run");
    fb.addEventListener("click", () => openFeedback(catInfo));
    actions.appendChild(fb);
  }
  if (shown) {
    const expand = el("button", "btn icon", "⤢");
    tip(expand, "Expand");
    expand.addEventListener("click", () => openModal(shown));
    actions.appendChild(expand);
    const dash = el("button", "btn icon", "▦");
    tip(dash, "Add to dashboard");
    dash.addEventListener("click", () => openCardModal(shown));
    actions.appendChild(dash);
    if (insight && insight.category === "custom") {
      const del = el("button", "btn icon", "✕");
      tip(del, "Delete this card");
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

  if (view) {
    const pill = el("div", "histpill");
    pill.appendChild(el("span", null, `Viewing ${fmtRun(view.ts)}`));
    const back = el("button", "btn small", "Back to latest");
    back.addEventListener("click", () => viewRun(id, null));
    pill.appendChild(back);
    card.appendChild(pill);
  }

  if (shown && shown.question) {
    card.appendChild(el("div", "summary", `“${shown.question}”`));
  }

  // body
  if (active) {
    const phase = el("div", "phase");
    phase.appendChild(el("span", "orbit"));
    phase.appendChild(el("span", null, phaseLabel(job.state)));
    card.appendChild(phase);
    card.appendChild(el("div", "viz-skel"));
  } else if (shown) {
    if (shown.summary) card.appendChild(el("div", "summary", shown.summary));
    if (shown.highlights && shown.highlights.length) {
      const prevData = view ? view.prev : state.prevLatest[id];
      const prevHls = (prevData && prevData.highlights) || [];
      const hls = el("div", "highlights");
      shown.highlights.forEach((h) => {
        if (!h || !h.label) return;
        const box = el("div", "hl" + (h.status ? ` status-${h.status}` : ""));
        box.appendChild(el("div", "l", String(h.label)));
        box.appendChild(el("div", "v", String(h.value != null ? h.value : "—")));
        if (h.delta) box.appendChild(el("div", "d", String(h.delta)));
        const prev = prevHls.find((p) => p && p.label === h.label);
        if (prev && prev.value != null) {
          box.appendChild(el("div", "prev", `prev: ${prev.value}`));
        }
        hls.appendChild(box);
      });
      card.appendChild(hls);
    }
    if (!view && insight && insight.questions && insight.questions.length) {
      card.appendChild(makeQuestions(insight));
    }
    card.appendChild(makeFrame(shown));
    const foot = el("div", "foot");
    foot.appendChild(el("span", null,
      view ? `Generated ${timeAgo(shown.generated_at)}` : `Updated ${timeAgo(shown.generated_at)}`));
    foot.appendChild(el("span", "spacer"));
    if (shown.meta && shown.meta.duration_ms) {
      foot.appendChild(el("span", null, `${(shown.meta.duration_ms / 1000).toFixed(0)}s`));
    }
    if (insight && catInfo) {
      foot.appendChild(makeHistoryControls(id, insight, view));
    }
    if (!view && insight && insight.category === "custom" && insight.question) {
      const mk = el("button", "btn small", "＋ Make recurring");
      tip(mk, "Turn this question into a scheduled insight");
      mk.addEventListener("click", () => openNewInsight({
        title: (insight.title || insight.question).slice(0, 60),
        icon: insight.icon || "✨",
        focus: "Answer this question about the home, keeping the analysis "
          + `fresh each run: "${insight.question}"`,
      }));
      foot.appendChild(mk);
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

// Tags a card can be found under: the model's content tags plus its own
// category id ("asked" for ad-hoc questions). One tag chip can therefore
// match many cards — e.g. #batteries surfaces every card that found a
// battery problem, whatever category it belongs to.
function effectiveTags(i) {
  const tags = (Array.isArray(i.tags) ? i.tags : [])
    .filter((t) => typeof t === "string" && t.trim())
    .map((t) => t.trim().toLowerCase());
  if (i.category === "custom") tags.push("asked");
  else if (i.category) tags.unshift(i.category);
  return [...new Set(tags)];
}

function render() {
  const s = state.status;
  if (!s) return;
  renderAuth();
  if (!s.authenticated) return;

  // filter chips — the dynamic union of tags across all generated cards
  const filters = $("#filters");
  filters.textContent = "";
  const counts = {};
  state.insights.forEach((i) => effectiveTags(i).forEach((t) => {
    counts[t] = (counts[t] || 0) + 1;
  }));
  if (state.filter !== "all" && !counts[state.filter]) state.filter = "all";
  const tagList = Object.keys(counts).sort((a, b) =>
    counts[b] - counts[a] || a.localeCompare(b)).slice(0, 16);
  const chips = [{ id: "all", label: "✦ All" }]
    .concat(tagList.map((t) => ({ id: t, label: `#${t}`, n: counts[t] })));
  chips.forEach((c) => {
    const chip = el("button", "fchip" + (state.filter === c.id ? " active" : ""),
      c.n > 1 ? `${c.label} · ${c.n}` : c.label);
    chip.addEventListener("click", () => { state.filter = c.id; render(); });
    filters.appendChild(chip);
  });

  // cards
  const grid = $("#grid");
  grid.textContent = "";
  const matches = (i) => state.filter === "all" || effectiveTags(i).includes(state.filter);
  const customs = state.insights.filter((i) => i.category === "custom");
  // custom in-flight jobs that have no stored insight yet
  Object.keys(s.jobs || {}).forEach((jid) => {
    if (jid.startsWith("custom-") && !insightFor(jid) &&
        ["queued", "collecting", "generating", "parsing", "error"].includes(s.jobs[jid].state)) {
      customs.unshift({ id: jid, category: "custom", category_title: "Custom", icon: "✨", virtual: true });
    }
  });
  customs.forEach((i) => {
    if (i.virtual ? (state.filter !== "all" && state.filter !== "asked") : !matches(i)) return;
    grid.appendChild(makeCard(null, i.virtual ? null : i));
    if (i.virtual) grid.lastChild.dataset.id = i.id;
  });
  s.categories.forEach((c) => {
    const ins = insightFor(c.id);
    // not-yet-generated placeholders only clutter tag views — All only
    if (state.filter !== "all" && !(ins && matches(ins))) return;
    grid.appendChild(makeCard(c, ins));
  });
}

// Rebuild only when something meaningful changed (avoid iframe reloads)
let lastRenderKey = "";
function renderIfChanged() {
  const s = state.status;
  const key = JSON.stringify({
    auth: s && [s.authenticated, s.auth_check.state, s.auth_source],
    jobs: s && s.jobs,
    // a card pinned to a past run keys on that run, not generated_at — the
    // poll loop must not clobber it when the latest regenerates elsewhere
    gen: state.insights.map((i) => i.id
      + (state.viewing[i.id] ? "@" + state.viewing[i.id].ts : i.generated_at)
      + ":q" + ((i.questions || []).length)),
    view: Object.keys(state.viewing).map((k) => k + state.viewing[k].ts),
    cats: s && s.categories.map((c) =>
      [c.id, c.title, c.icon, c.enabled, c.focus_overridden, c.refresh_hours]),
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
  const prev = state.insights;
  state.insights = data.insights || [];
  // a regenerated insight invalidates its cached history/diff data
  state.insights.forEach((i) => {
    const old = prev.find((p) => p.id === i.id);
    if (old && old.generated_at !== i.generated_at) {
      delete state.history[i.id];
      delete state.prevLatest[i.id];
    }
  });
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
  openBox("#modal");
}

$("#modalClose").addEventListener("click", () => closeBox("#modal"));
$("#modal").addEventListener("click", (ev) => {
  if (ev.target === $("#modal")) closeBox("#modal");
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    document.querySelectorAll(".modal.open").forEach((m) => m.classList.remove("open"));
    syncModalLock();
  }
});

// ------------------------------------------------------ prompt edit modal

let editCatId = null;

function openEdit(cat) {
  editCatId = cat.id;
  $("#editIcon").textContent = cat.icon || "✨";
  $("#editTitle").textContent = `${cat.title} — prompt`;
  $("#editDesc").textContent = cat.description || "";
  $("#editFocus").value = cat.focus || "";
  $("#editEnabled").checked = cat.enabled !== false;
  $("#editHours").value = cat.refresh_hours == null ? "" : cat.refresh_hours;
  const overridden = cat.focus_overridden || cat.enabled === false || cat.refresh_hours != null;
  $("#editReset").classList.toggle("hidden", !overridden);
  openBox("#editModal");
}

async function saveEdit(regen) {
  const hours = $("#editHours").value.trim();
  const body = {
    focus: $("#editFocus").value,
    enabled: $("#editEnabled").checked,
    refresh_hours: hours === "" ? null : Math.round(Number(hours)),
  };
  try {
    await api(`api/prompt/${editCatId}`, { method: "PUT", body: JSON.stringify(body) });
    closeBox("#editModal");
    await refreshStatus();
    render();
    if (regen) {
      generate(editCatId);
    } else {
      toast("Prompt saved");
    }
  } catch (e) {
    toast(e.message);
  }
}

$("#editSave").addEventListener("click", () => saveEdit(false));
$("#editSaveRegen").addEventListener("click", () => saveEdit(true));
$("#editReset").addEventListener("click", async () => {
  try {
    await api(`api/prompt/${editCatId}`, { method: "DELETE" });
    closeBox("#editModal");
    toast("Restored the default prompt");
    await refreshStatus();
    render();
  } catch (e) {
    toast(e.message);
  }
});
$("#editClose").addEventListener("click", () => closeBox("#editModal"));
$("#editModal").addEventListener("click", (ev) => {
  if (ev.target === $("#editModal")) closeBox("#editModal");
});

// ------------------------------------------------ user-defined insights UI

let userEditId = null; // null = create mode

function openNewInsight(prefill) {
  userEditId = null;
  $("#newTitleBar").textContent =
    prefill && prefill.focus ? "Save as recurring insight" : "New insight";
  $("#newName").value = (prefill && prefill.title) || "";
  $("#newIcon").value = (prefill && prefill.icon) || "";
  $("#newFocus").value = (prefill && prefill.focus) || "";
  $("#newHours").value = "";
  $("#newEnabledRow").classList.add("hidden");
  $("#newDelete").classList.add("hidden");
  $("#newSave").textContent = "Create & generate";
  openBox("#newModal");
}

function openUserEdit(cat) {
  userEditId = cat.id;
  $("#newTitleBar").textContent = `${cat.title} — edit insight`;
  $("#newName").value = cat.title || "";
  $("#newIcon").value = cat.icon || "";
  $("#newFocus").value = cat.focus || "";
  $("#newHours").value = cat.refresh_hours == null ? "" : cat.refresh_hours;
  $("#newEnabled").checked = cat.enabled !== false;
  $("#newEnabledRow").classList.remove("hidden");
  $("#newDelete").classList.remove("hidden");
  $("#newSave").textContent = "Save";
  openBox("#newModal");
}

async function saveUserInsight() {
  const hours = $("#newHours").value.trim();
  const body = {
    title: $("#newName").value.trim(),
    icon: $("#newIcon").value.trim(),
    focus: $("#newFocus").value.trim(),
    refresh_hours: hours === "" ? null : Math.round(Number(hours)),
  };
  if (!body.title) { toast("Give the insight a name"); return; }
  if (!body.focus) { toast("Describe what Claude should analyze"); return; }
  try {
    if (userEditId) {
      body.enabled = $("#newEnabled").checked;
      await api(`api/user_category/${userEditId}`, {
        method: "PUT", body: JSON.stringify(body) });
      toast("Insight updated");
    } else {
      await api("api/user_category", { method: "POST", body: JSON.stringify(body) });
      toast("Insight created — generating…");
    }
    closeBox("#newModal");
    await refreshStatus();
    render();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
}

$("#newSave").addEventListener("click", saveUserInsight);
$("#newDelete").addEventListener("click", async () => {
  if (!userEditId) return;
  if (!window.confirm("Delete this insight and its history?")) return;
  try {
    await api(`api/user_category/${userEditId}`, { method: "DELETE" });
    closeBox("#newModal");
    toast("Insight deleted");
    await Promise.all([refreshStatus(), refreshInsights()]);
    render();
  } catch (e) {
    toast(e.message);
  }
});
$("#newClose").addEventListener("click", () => closeBox("#newModal"));
$("#newModal").addEventListener("click", (ev) => {
  if (ev.target === $("#newModal")) closeBox("#newModal");
});
$("#newInsight").addEventListener("click", () => openNewInsight(null));

// -------------------------------------------------------- feedback modal

let fbCatId = null;

function fmtWhen(ts) {
  const d = new Date(ts * 1000);
  return isNaN(d.getTime()) ? "" :
    d.toLocaleString([], { month: "short", day: "numeric" });
}

async function renderFbList() {
  const wrapEl = $("#fbListWrap");
  const list = $("#fbList");
  list.textContent = "";
  let entries = [];
  try {
    entries = (await api(`api/insight/${fbCatId}/feedback`)).feedback || [];
  } catch (e) { /* list stays hidden */ }
  wrapEl.classList.toggle("hidden", !entries.length);
  entries.slice().reverse().forEach((f) => {
    const row = el("div", "fbitem");
    const txt = el("div", "txt");
    txt.appendChild(el("div", null, f.text));
    txt.appendChild(el("div", "when", fmtWhen(f.ts)));
    row.appendChild(txt);
    const del = el("button", "btn icon", "✕");
    tip(del, "Remove — stop applying this feedback");
    del.addEventListener("click", async () => {
      try {
        await api(`api/insight/${fbCatId}/feedback/${f.ts}`, { method: "DELETE" });
        renderFbList();
      } catch (e) {
        toast(e.message);
      }
    });
    row.appendChild(del);
    list.appendChild(row);
  });
}

function openFeedback(cat) {
  fbCatId = cat.id;
  $("#fbIcon").textContent = cat.icon || "💬";
  $("#fbTitle").textContent = `${cat.title} — feedback`;
  $("#fbText").value = "";
  $("#fbListWrap").classList.add("hidden");
  openBox("#fbModal");
  renderFbList();
}

async function sendFeedback(regen) {
  const text = $("#fbText").value.trim();
  if (!text) { toast("Write the feedback first"); return; }
  try {
    await api(`api/insight/${fbCatId}/feedback`, {
      method: "POST", body: JSON.stringify({ feedback: text }) });
    $("#fbText").value = "";
    if (regen) {
      closeBox("#fbModal");
      toast("Feedback saved — regenerating with it now");
      generate(fbCatId);
    } else {
      toast("Feedback saved — applied on every future run");
      renderFbList();
    }
  } catch (e) {
    toast(e.message);
  }
}

$("#fbSave").addEventListener("click", () => sendFeedback(false));
$("#fbSaveRegen").addEventListener("click", () => sendFeedback(true));
$("#fbClose").addEventListener("click", () => closeBox("#fbModal"));
$("#fbModal").addEventListener("click", (ev) => {
  if (ev.target === $("#fbModal")) closeBox("#fbModal");
});

// ------------------------------------------------------- knowledge modal
// The viewer for everything the analyst has learned: open questions (answer
// or dismiss), learned facts (add/remove), answered Q&A, and the shared
// memory.md the BRUH Terminal maintains.

function kSourceLabel(src) {
  return { insights: "discovered", homeowner: "your answer",
    feedback: "feedback", user: "added by you" }[src] || src;
}

async function renderKnowledge() {
  let data;
  try {
    data = await api("api/knowledge");
  } catch (e) {
    toast("Could not load knowledge: " + e.message);
    return;
  }

  // open questions — answer inline or dismiss
  const openBoxEl = $("#kOpenQs");
  openBoxEl.textContent = "";
  const open = (data.questions || []).filter((q) => q.status === "open");
  if (!open.length) {
    openBoxEl.appendChild(el("div", "kempty", "No open questions — the analyst has everything it needs."));
  }
  open.slice().reverse().forEach((q) => {
    const row = el("div", "qrow");
    const head = el("div", "qtext", `❓ ${q.text}`);
    row.appendChild(head);
    const form = el("form", "qform");
    const input = el("input");
    input.type = "text";
    input.maxLength = 1000;
    input.placeholder = "Answer — it becomes a learned fact…";
    const send = el("button", "btn small primary", "Answer");
    send.type = "submit";
    const dismiss = el("button", "btn small", "Dismiss");
    dismiss.type = "button";
    tip(dismiss, "Retire without answering — it won't be asked again");
    form.appendChild(input);
    form.appendChild(send);
    form.appendChild(dismiss);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const answer = input.value.trim();
      if (!answer) return;
      send.disabled = true;
      try {
        await api(`api/knowledge/question/${q.ts}/answer`, {
          method: "POST", body: JSON.stringify({ answer }) });
        toast("Answered — every future insight will use it");
        await refreshInsights().catch(() => {});
        renderIfChanged();
        renderKnowledge();
      } catch (e) { toast(e.message); send.disabled = false; }
    });
    dismiss.addEventListener("click", async () => {
      try {
        await api(`api/knowledge/question/${q.ts}/dismiss`, { method: "POST" });
        await refreshInsights().catch(() => {});
        renderIfChanged();
        renderKnowledge();
      } catch (e) { toast(e.message); }
    });
    row.appendChild(form);
    openBoxEl.appendChild(row);
  });

  // learned facts
  const factsEl = $("#kFacts");
  factsEl.textContent = "";
  const facts = data.facts || [];
  if (!facts.length) {
    factsEl.appendChild(el("div", "kempty",
      "Nothing learned yet — facts appear here as insights discover them. "
      + "(Facts you teach live in the memory file instead.)"));
  }
  facts.slice().reverse().forEach((f) => {
    const row = el("div", "fbitem");
    const txt = el("div", "txt");
    txt.appendChild(el("div", null, f.text));
    const when = new Date(f.ts * 1000);
    txt.appendChild(el("div", "when",
      `${kSourceLabel(f.source)}${f.category ? " · " + f.category : ""}` +
      (isNaN(when.getTime()) ? "" :
        " · " + when.toLocaleDateString([], { month: "short", day: "numeric" }))));
    row.appendChild(txt);
    const del = el("button", "btn icon", "✕");
    tip(del, "Forget this fact");
    del.addEventListener("click", async () => {
      try {
        await api(`api/knowledge/fact/${f.ts}`, { method: "DELETE" });
        renderKnowledge();
      } catch (e) { toast(e.message); }
    });
    row.appendChild(del);
    factsEl.appendChild(row);
  });

  // answered questions
  const answered = (data.questions || []).filter((q) => q.status === "answered");
  $("#kAnsweredWrap").classList.toggle("hidden", !answered.length);
  const ansEl = $("#kAnswered");
  ansEl.textContent = "";
  answered.slice().reverse().forEach((q) => {
    const row = el("div", "fbitem");
    const txt = el("div", "txt");
    txt.appendChild(el("div", null, `Q: ${q.text}`));
    txt.appendChild(el("div", "kans", `A: ${q.answer}`));
    row.appendChild(txt);
    const del = el("button", "btn icon", "✕");
    tip(del, "Forget — the analyst may ask this again");
    del.addEventListener("click", async () => {
      try {
        await api(`api/knowledge/question/${q.ts}`, { method: "DELETE" });
        renderKnowledge();
      } catch (e) { toast(e.message); }
    });
    row.appendChild(del);
    ansEl.appendChild(row);
  });

  renderMemory(data);
}

// ---- home memory file: formatted view, raw-markdown edit, Claude merge ----

const memState = { editing: false, dirty: false, text: "", pollTimer: null };

const MEM_TEMPLATE = "# Home Memory\n\n## Preferences\n\n## Entity nicknames\n\n"
  + "## Household patterns\n\n## Device notes\n";

// Minimal markdown renderer for the memory document (headings, lists, bold,
// italic, inline code, links). Input is escaped first, so the produced HTML
// contains only tags we emit ourselves.
function mdInline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*]+)\*/g, "<i>$1</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function mdToHtml(md) {
  md = String(md || "").replace(/<!--[\s\S]*?-->/g, "");
  md = md.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  md.split("\n").forEach((raw) => {
    const line = raw.trimEnd();
    const h = line.match(/^(#{1,6})\s+(.*)/);
    const ul = line.match(/^\s*[-*]\s+(.*)/);
    const ol = line.match(/^\s*\d+\.\s+(.*)/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${mdInline(h[2])}</h${h[1].length}>`); }
    else if (ul) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${mdInline(ul[1])}</li>`);
    } else if (ol) {
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${mdInline(ol[1])}</li>`);
    } else if (!line.trim()) { closeList(); }
    else { closeList(); out.push(`<p>${mdInline(line)}</p>`); }
  });
  closeList();
  return out.join("\n");
}

function renderMemory(data) {
  const merging = !!(data.memory_state && data.memory_state.merging);
  $("#kMemMerging").classList.toggle("hidden", !merging);
  if (merging) pollMemoryMerge();
  if (memState.editing) return; // never clobber an edit in progress
  memState.text = data.shared_memory || "";
  const has = !!memState.text.trim();
  $("#kMemView").innerHTML = has ? mdToHtml(memState.text) : "";
  $("#kMemView").classList.toggle("hidden", !has);
  $("#kMemEmpty").classList.toggle("hidden", has);
  if (data.memory_state && data.memory_state.error) {
    toast("Memory merge problem: " + data.memory_state.error);
  }
}

function setMemEditing(on) {
  memState.editing = on;
  memState.dirty = false;
  $("#kMemTa").classList.toggle("hidden", !on);
  $("#kMemView").classList.toggle("hidden", on || !memState.text.trim());
  $("#kMemEmpty").classList.toggle("hidden", on || !!memState.text.trim());
  $("#kMemEdit").classList.toggle("hidden", on);
  $("#kMemSave").classList.toggle("hidden", !on);
  $("#kMemCancel").classList.toggle("hidden", !on);
  $("#kMemDirty").classList.add("hidden");
}

// while a Claude merge is running, poll until it lands and show the result
function pollMemoryMerge() {
  clearTimeout(memState.pollTimer);
  memState.pollTimer = setTimeout(async () => {
    if (!$("#kModal").classList.contains("open")) return;
    try {
      const data = await api("api/knowledge");
      renderMemory(data);
      if (data.memory_state && data.memory_state.merging) pollMemoryMerge();
      else if (!memState.editing) toast("Memory file updated");
    } catch (e) { /* transient; next open re-renders */ }
  }, 2500);
}

$("#kMemEdit").addEventListener("click", () => {
  $("#kMemTa").value = memState.text.trim() ? memState.text : MEM_TEMPLATE;
  setMemEditing(true);
});
$("#kMemTa").addEventListener("input", () => {
  memState.dirty = true;
  $("#kMemDirty").classList.remove("hidden");
});
$("#kMemCancel").addEventListener("click", () => {
  if (memState.dirty &&
      !window.confirm("Discard your unsaved memory edits?")) return;
  setMemEditing(false);
  renderKnowledge();
});
$("#kMemSave").addEventListener("click", async () => {
  const text = $("#kMemTa").value;
  try {
    await api("api/memory", { method: "PUT", body: JSON.stringify({ text }) });
    memState.text = text;
    setMemEditing(false);
    toast("Memory saved");
    renderKnowledge();
  } catch (e) { toast(e.message); }
});

$("#knowledgeBtn").addEventListener("click", () => {
  openBox("#kModal");
  renderKnowledge();
});
$("#kAddForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("#kAddInput").value.trim();
  if (!text) return;
  // adding a fact has Claude REWRITE the memory file — unsaved manual edits
  // in the editor below would be overwritten, so make the user choose first
  if (memState.editing && memState.dirty) {
    if (!window.confirm(
      "You have unsaved manual edits to the home memory file below.\n\n"
      + "Adding this fact makes Claude rewrite that file, and your unsaved "
      + "edits would be lost. Press Cancel to go save them first, or OK to "
      + "discard them and continue.")) return;
    setMemEditing(false);
  }
  try {
    const res = await api("api/knowledge/fact", {
      method: "POST", body: JSON.stringify({ text }) });
    $("#kAddInput").value = "";
    toast(res.added ? "Learned — merging it into the memory file…" : "Already known");
    if (res.merging) {
      $("#kMemMerging").classList.remove("hidden");
      pollMemoryMerge();
    }
    renderKnowledge();
  } catch (e) { toast(e.message); }
});
function closeKnowledge() {
  if (memState.editing && memState.dirty &&
      !window.confirm("Discard your unsaved memory edits?")) return;
  if (memState.editing) setMemEditing(false);
  closeBox("#kModal");
}
$("#kClose").addEventListener("click", closeKnowledge);
$("#kModal").addEventListener("click", (ev) => {
  if (ev.target === $("#kModal")) closeKnowledge();
});

// -------------------------------------------------- dashboard card modal

let cardInfoCache = null;

function copyFallback(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true, () => copyFallback(text));
  }
  return Promise.resolve(copyFallback(text));
}

// The card server (port 8100, plain HTTP) is only reachable on the LAN —
// never through the Nabu Casa cloud proxy. Pick the host the browser is
// ACTUALLY using to reach HA when it's a LAN address (hassio.local,
// homeassistant.local, a raw IP — whatever the user typed), because that
// name provably resolves for them; fall back to HA's internal_url for
// cloud/remote sessions.
function isCloudHost(host) {
  return /\.nabu\.casa$/i.test(host || "");
}

function cardHost(info) {
  const fromUrl = (u) => {
    const m = (u || "").match(/^https?:\/\/([^/:]+)/);
    return m ? m[1] : "";
  };
  const page = window.location.hostname;
  if (page && !isCloudHost(page)) return page;
  const internal = fromUrl(info.internal_url);
  if (internal && !isCloudHost(internal)) return internal;
  return "homeassistant.local";
}

async function openCardModal(insight) {
  openBox("#cardModal");
  const pre = $("#cardYaml");
  const warn = $("#cardWarn");
  const hint = $("#cardHint");
  const portStep = $("#cardPortStep");
  warn.classList.add("hidden");
  portStep.classList.add("hidden");
  pre.textContent = "Loading…";
  try {
    if (!cardInfoCache) cardInfoCache = await api("api/card_info");
  } catch (e) {
    pre.textContent = "Could not load card info: " + e.message;
    return;
  }
  const info = cardInfoCache;
  const yamlFor = (url) => [
    "type: iframe",
    `url: ${url}`,
    `title: ${(insight.title || "Insight").replace(/[:#"\n]/g, " ").trim()}`,
    "aspect_ratio: 90%",
  ].join("\n");

  if (info.www_cards) {
    // Preferred path: HA itself serves the mirrored HTML at /local/… — same
    // origin as every dashboard, so it works over HTTP, HTTPS, and Nabu Casa.
    const localUrl = `${info.local_dir}/${insight.id}${info.local_suffix}`;
    pre.textContent = yamlFor(localUrl);
    hint.textContent = "Home Assistant serves this file itself, so the card works on any "
      + "dashboard — local, HTTPS, and Nabu Casa remote alike. The file name contains this "
      + "add-on's private card token — anyone with the exact link can view the insight, "
      + "nothing else.";
    try {
      // the panel shares HA's origin (ingress), so we can verify /local works
      const probe = await fetch(localUrl, { cache: "no-store" });
      if (!probe.ok) throw new Error(String(probe.status));
    } catch (e) {
      warn.textContent = "Home Assistant isn't serving this file yet — its www folder was "
        + "just created. Restart Home Assistant once (Settings → System → ⋮ → Restart "
        + "Home Assistant), then the card will load.";
      warn.classList.remove("hidden");
    }
    return;
  }

  // Fallback (no /config/www access): the plain-HTTP card server on the
  // mapped host port.
  const host = cardHost(info);
  const port = info.host_port || info.port;
  pre.textContent = yamlFor(`http://${host}:${port}/card/${insight.id}?token=${info.token}`);
  if (info.port_checked && !info.host_port) portStep.classList.remove("hidden");

  const cloud = isCloudHost(window.location.hostname);
  if (window.location.protocol === "https:") {
    // an http:// iframe inside an https:// dashboard is mixed content —
    // the browser blanks it. Say so instead of letting the card "not work".
    warn.textContent = cloud
      ? "You're connected through Nabu Casa remote access right now. This card is served "
        + "over plain HTTP on your local network, so browsers will show it EMPTY on any "
        + "HTTPS dashboard (mixed content) — including this remote session. It works when "
        + `you open Home Assistant locally, e.g. http://${host}:8123. The YAML below uses `
        + "your local address — fix the hostname if it isn't right."
      : "You're viewing Home Assistant over HTTPS. Browsers block plain-HTTP iframes "
        + "inside an HTTPS page (mixed content), so this card will show EMPTY on dashboards "
        + `opened this way — it works when you open HA over HTTP, e.g. http://${host}:8123.`;
    warn.classList.remove("hidden");
    hint.textContent = "The URL contains this add-on's private card token — anyone with "
      + "the link on your network can view the insight, nothing else.";
  } else {
    hint.textContent = `This URL uses the address you're connected with right now `
      + `(“${host}”), so it resolves for every device that reaches HA the same way. `
      + "It contains this add-on's private card token — anyone with the link on your "
      + "network can view the insight, nothing else.";
  }
}

$("#cardCopy").addEventListener("click", () => {
  copyText($("#cardYaml").textContent).then((ok) =>
    toast(ok ? "YAML copied — paste it into a dashboard card" :
      "Copy failed — select the YAML and copy manually"));
});
$("#cardClose").addEventListener("click", () => closeBox("#cardModal"));
$("#cardModal").addEventListener("click", (ev) => {
  if (ev.target === $("#cardModal")) closeBox("#cardModal");
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
