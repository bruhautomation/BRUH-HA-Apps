/* BRain — panel logic.
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
  findings: [],
  findFilter: "live",
  filter: "all",
  editingTags: null, // card id whose tag row is in edit mode
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
    chip.title = "No Claude credential stored";
  } else if (s.auth_check.state === "checking") {
    text.textContent = "Verifying Claude…";
    chip.classList.add("busy");
    chip.title = "Checking the stored credential";
  } else if (s.auth_check.state === "failed") {
    text.textContent = "Claude auth failed";
    chip.classList.add("bad");
    chip.title = s.auth_check.error || "Claude auth failed";
  } else if (s.auth_source === "shared") {
    text.textContent = "Claude · shared login";
    chip.classList.add("ok");
    chip.title = "Using BRain's shared login";
  } else {
    text.textContent = s.auth_type === "api_key" ? "Claude · API key" : "Claude · subscription";
    chip.classList.add("ok");
    chip.title = text.textContent;
  }
  // The words are hidden on a phone, so the state has to survive without them.
  chip.setAttribute("aria-label", text.textContent);
  // Three states, not two: not connected → connect; connected but never
  // onboarded → the first-run flow; onboarded → the dashboard.
  const ready = s.authenticated && obState.onboarded;
  $("#setup").classList.toggle("hidden", s.authenticated);
  $("#onboard").classList.toggle("hidden", !s.authenticated || obState.onboarded);
  $("#dash").classList.toggle("hidden", !ready);
  $("#refreshAll").classList.toggle("hidden", !ready);
  $("#settingsBtn").classList.toggle("hidden", !s.authenticated);
  renderUsageChip();
  renderPausedChip();
}

function fmtClock(epoch) {
  const d = new Date(epoch * 1000);
  return isNaN(d.getTime()) ? "" :
    d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// Topbar chip: current 5-hour-session usage + when the window resets
// (click opens ⚙). Dot goes warning-colored once the budget is reached.
function renderUsageChip() {
  const s = state.status;
  const chip = $("#usageChip");
  const u = s && s.authenticated && s.usage;
  if (!u || u.used_percent == null) {
    chip.classList.add("hidden");
    return;
  }
  // Split so a phone can keep the number and drop the sentence around it.
  const reset = u.resets_at ? fmtClock(u.resets_at) : "";
  $("#usageChipPct").textContent = `${Math.round(u.used_percent)}%`;
  $("#usageChipText").textContent = reset ? `used · resets ${reset}` : "used";
  chip.classList.toggle("ok", !u.blocked);
  chip.classList.toggle("warn", !!u.blocked);
  chip.title = (u.source === "account"
    ? `Your Anthropic account's 5-hour session: ${u.used_percent}% used`
    : `≈${u.used_percent}% of a ${u.plan_label} session used by Insights (estimate)`)
    + ` — budget ${u.budget_percent}%`
    + (reset ? `, window resets at ${reset}` : "")
    + ". Tap for settings.";
  chip.classList.remove("hidden");
}

// Topbar chip that says WHY nothing is auto-generating (click opens ⚙)
function renderPausedChip() {
  const s = state.status;
  const chip = $("#pausedChip");
  const text = $("#pausedChipText");
  let label = "";
  if (s && s.authenticated) {
    if (s.settings && s.settings.auto_enabled === false) {
      label = "Auto insights off";
      chip.title = "Automatic generation is switched off in Settings";
    } else if (s.usage && s.usage.blocked) {
      label = "Usage budget reached";
      chip.title = `Session usage ${s.usage.used_percent}% ≥ budget `
        + `${s.usage.budget_percent}% — auto-refresh paused until the 5-hour window rolls over`;
    }
  }
  text.textContent = label;
  if (label) chip.setAttribute("aria-label", label);
  chip.classList.toggle("hidden", !label);
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

const ACTIVE_STATES = ["queued", "collecting", "generating", "parsing", "fixing"];

function phaseLabel(jobState) {
  return {
    queued: "Queued…",
    collecting: "Gathering your home's data…",
    generating: "Claude is analyzing & designing…",
    parsing: "Rendering visualization…",
    fixing: "Working on the fix…",
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
  // These are hypotheses, not open questions — same two-tap affordance as
  // the Memory tab. A text box asked for an essay when the answer is yes or
  // no, and the card is where you most likely have the context to settle it.
  const wrap = el("div", "questions");
  insight.questions.forEach((q) => {
    const row = el("div", "qrow");
    row.appendChild(el("div", "qtext", q));

    const actions = el("div", "qform");
    const yes = el("button", "btn small primary", "\u2713  Yes");
    const no = el("button", "btn small", "\u2717  No");
    yes.type = no.type = "button";
    tip(yes, "Right — remember it as a fact");
    tip(no, "Wrong — don't pursue this again");

    const settle = async (route, body, done) => {
      yes.disabled = no.disabled = true;
      try {
        await api(route, {
          method: "POST",
          body: JSON.stringify({ insight_id: insight.id, question: q, ...body }),
        });
        toast(done);
        await refreshInsights();
        renderIfChanged();
        refreshMemoryBadge();
      } catch (e) {
        toast(e.message);
        yes.disabled = no.disabled = false;
      }
    };

    // The confirm route still takes an "answer": the claim is its own
    // answer, since confirming it is what makes it a fact.
    yes.addEventListener("click", () => settle(
      "api/questions/answer", { answer: q },
      "Filed — it lands in memory at the next consolidation"));
    no.addEventListener("click", () => settle(
      "api/questions/dismiss", {}, "Noted as a dead end"));

    actions.appendChild(yes);
    actions.appendChild(no);
    row.appendChild(actions);
    wrap.appendChild(row);
  });
  return wrap;
}


function makeHistoryControls(id, insight, view) {
  const wrap = el("span", "hist");
  const entries = state.history[id] ? historyEntries(id, insight) : null;
  const older = el("button", "btn icon hstep", "‹");
  tip(older, "Older run");
  older.addEventListener("click", () => stepRun(id, insight, 1));
  // hide steppers that can't go anywhere: ‹ once history is known to end
  // here, › whenever the latest run is already showing
  if (entries) {
    const idx = Math.max(entries.indexOf(view ? view.ts : ""), 0);
    if (idx >= entries.length - 1) older.classList.add("hidden");
  }
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
  if (!view) newer.classList.add("hidden");
  wrap.appendChild(older);
  wrap.appendChild(sel);
  wrap.appendChild(newer);
  return wrap;
}

// catInfo is null for ad-hoc "Ask" cards and insight is null until the
// answer lands, so an in-flight question has neither — `fallbackId` carries
// the job id for that case.
function makeCard(catInfo, insight, fallbackId) {
  const id = (insight && insight.id) || (catInfo && catInfo.id) || fallbackId;
  const job = jobFor(id);
  const view = insight ? state.viewing[id] : null;
  const shown = view && view.data ? view.data : insight;
  const active = !view && ACTIVE_STATES.includes(job.state);
  const disabled = !!(catInfo && catInfo.enabled === false);
  const card = el("article", "card" + (active ? " pending" : "") + (disabled ? " off" : ""));
  card.dataset.id = id;

  // head — name and icon come from the live definition (or, for an ad-hoc
  // Ask card, the live insight), never from the run being viewed: a rename
  // has to show up immediately, including on past runs
  const head = el("div", "card-head");
  head.appendChild(el("span", "cicon",
    (catInfo && catInfo.icon) || (insight && insight.icon) || (shown && shown.icon) || "✨"));
  const titles = el("div", "ctitles");
  const catName = catInfo ? catInfo.title
    : ((insight && insight.category_title) || "Custom");
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
    regen.addEventListener("click", () =>
      generate(id, (insight && insight.question) || job.question));
    actions.appendChild(regen);
  }
  // ✎ edits every card: a category card opens its full editor, an ad-hoc
  // Ask card (no definition behind it) gets the name/icon dialog
  if (catInfo || insight) {
    const edit = el("button", "btn icon", "✎");
    tip(edit, catInfo
      ? (catInfo.user ? "Edit insight — name, icon, prompt, schedule"
        : "Edit card — name, icon, prompt, schedule")
      : "Rename this card — name and icon");
    edit.addEventListener("click", () => {
      if (!catInfo) openNameEdit(insight);
      else if (catInfo.user) openUserEdit(catInfo);
      else openEdit(catInfo);
    });
    actions.appendChild(edit);
  }
  if (catInfo) {
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
  }
  // ✕ deletes every card — including one whose only trace is a job, so a
  // failed Ask can be cleared away instead of sitting there forever.
  // A still-running job is left alone: the worker would just re-register it.
  if (catInfo || insight || (fallbackId && !active)) {
    const del = el("button", "btn icon", "✕");
    tip(del, "Delete this card and its history");
    del.addEventListener("click", () => deleteCard(id, catInfo, catName));
    actions.appendChild(del);
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

  // the question shows while the answer is still generating too, so an
  // in-flight "Ask" card says what it's working on
  const question = (shown && shown.question) || job.question;
  if (question) card.appendChild(el("div", "summary", `“${question}”`));

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
    // Tags belong to the card, not to the run being viewed — editing them
    // while pinned to March's run must still change the card's tags.
    if (insight) {
      const tagRow = makeTagRow(insight);
      if (tagRow) card.appendChild(tagRow);
    }
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
    retry.addEventListener("click", () => generate(id, question));
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

// Tags a card can be found under: the model's content tags, the card's own
// category, and any hand edits — all resolved server-side (card_tags.py), so
// there is one answer to "what tags does this card have". One chip can match
// many cards: #batteries surfaces every card that found a battery problem,
// whatever category it belongs to.
function effectiveTags(i) {
  return Array.isArray(i.tags) ? i.tags : [];
}

// The tag row on a card. Read-only chips until you press ✎ — then each grows
// an ✕ and an input appears, because a tag you can delete by mis-tapping is
// worse than one you have to press twice to lose.
function makeTagRow(insight) {
  const id = insight.id;
  const editing = state.editingTags === id;
  const tags = effectiveTags(insight);
  if (!tags.length && !editing) return null;

  const row = el("div", "tagrow" + (editing ? " editing" : ""));

  const save = async (next) => {
    try {
      const res = await api(`api/card/${id}/tags`, {
        method: "PUT", body: JSON.stringify({ tags: next }) });
      insight.tags = res.tags;
      render();
    } catch (e) { toast(e.message); }
  };

  tags.forEach((t) => {
    const chip = el("span", "tagchip", `#${t}`);
    if (editing) {
      const x = el("button", "tagx", "✕");
      x.type = "button";
      tip(x, `Remove #${t} from this card`);
      x.addEventListener("click", () => save(tags.filter((o) => o !== t)));
      chip.appendChild(x);
    } else {
      chip.classList.add("clickable");
      chip.addEventListener("click", () => { state.filter = t; render(); });
    }
    row.appendChild(chip);
  });

  if (editing) {
    const form = el("form", "tagadd");
    const input = el("input", "taginput");
    input.type = "text";
    input.maxLength = 24;
    input.placeholder = "add a tag…";
    input.autocomplete = "off";
    form.appendChild(input);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const tag = input.value.trim().replace(/^#/, "").toLowerCase();
      if (!tag || tags.includes(tag)) { input.value = ""; return; }
      save(tags.concat(tag));
    });
    row.appendChild(form);
    const done = el("button", "btn small", "Done");
    done.addEventListener("click", () => { state.editingTags = null; render(); });
    row.appendChild(done);
  } else {
    const edit = el("button", "btn icon tagedit", "✎");
    tip(edit, "Edit this card's tags");
    edit.addEventListener("click", () => { state.editingTags = id; render(); });
    row.appendChild(edit);
  }
  return row;
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
        ACTIVE_STATES.concat("error").includes(s.jobs[jid].state)) {
      customs.unshift({ id: jid, category: "custom", category_title: "Custom", icon: "✨", virtual: true });
    }
  });
  customs.forEach((i) => {
    if (i.virtual ? (state.filter !== "all" && state.filter !== "asked") : !matches(i)) return;
    // a virtual card has no insight yet — makeCard works off the job id
    grid.appendChild(makeCard(null, i.virtual ? null : i, i.id));
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
      + ":q" + ((i.questions || []).length)
      + ":t" + effectiveTags(i).join(",")),
    view: Object.keys(state.viewing).map((k) => k + state.viewing[k].ts),
    cats: s && s.categories.map((c) =>
      [c.id, c.title, c.icon, c.enabled, c.focus_overridden, c.refresh_hours, c.schedule]),
    tagEdit: state.editingTags,
    paused: s && [s.settings && s.settings.auto_enabled, s.usage && s.usage.blocked],
    usage: s && s.usage && [s.usage.used_percent, s.usage.resets_at],
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
    const res = await api("api/generate", { method: "POST", body: JSON.stringify(body) });
    // "learn about the boiler" isn't a card — the server routed it to a study
    // session instead, and there is nothing on the dashboard to wait for.
    if (res && "learning" in res) {
      toast(res.learning
        ? `Studying ${res.learning} — it runs in the background; what it finds `
          + "lands in Memory and Findings"
        : "Studying whatever BRain knows least about — check Memory shortly");
      return;
    }
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
}

// One ✕ for every kind of card, and it means the same thing for all of them:
// gone. BRain proposes the cards a given home should have, so the way to get
// one back is to ask for it again — not to fish it out of a graveyard.
async function deleteCard(id, catInfo, name) {
  const label = name || (catInfo && catInfo.title) || "this card";
  if (!window.confirm(
    `Delete “${label}” and its history? This can't be undone — ask for it `
    + "again any time and BRain will build it fresh.")) return;
  try {
    await api(`api/card/${id}`, { method: "DELETE" });
    delete state.viewing[id];
    delete state.history[id];
    delete state.prevLatest[id];
    await Promise.all([refreshStatus(), refreshInsights()]);
    render();
    toast("Card deleted");
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
    ACTIVE_STATES.includes(j.state));
}

function fastPoll() {
  clearTimeout(state.pollTimer);
  const tick = async () => {
    const hadActive = anyActive();
    await refreshStatus().catch(() => {});
    if (hadActive && !anyActive()) {
      // A run just finished. Both lists can have changed — an insight run
      // rewrites its card AND may have turned up a problem — and neither
      // fetch depends on the other, so don't pay for them in series.
      await Promise.all([
        refreshInsights().catch(() => {}),
        refreshFindings(),
      ]);
      if (currentView === "findings") renderFindings();
    } else if (state.status) {
      updateFindBadge(state.status.findings_open);
    }
    renderIfChanged();
    refreshOpenSettings();
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

// "07:00, 19:00" ⇄ ["07:00","19:00"]. Returns null for empty, undefined
// (after a toast) when a chunk isn't a valid HH:MM time.
function parseTimes(text) {
  const chunks = String(text || "").split(/[,\s]+/).filter(Boolean);
  if (!chunks.length) return null;
  const out = [];
  for (const c of chunks) {
    const m = c.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
    if (!m) {
      toast(`“${c}” isn't a time — use 24h HH:MM, e.g. 07:00, 19:00`);
      return undefined;
    }
    const norm = `${m[1].padStart(2, "0")}:${m[2]}`;
    if (!out.includes(norm)) out.push(norm);
  }
  return out.sort();
}

function timesToText(schedule) {
  return Array.isArray(schedule) ? schedule.join(", ") : "";
}

// "default" placeholder on interval inputs shows the CURRENT effective
// default (⚙ Settings override, else the add-on configuration).
function defaultHoursPlaceholder(input) {
  const s = state.status;
  const hours = s && s.refresh_hours;
  input.placeholder = hours != null
    ? (hours > 0 ? `default: ${Math.round(hours)}h` : "default: off")
    : "default";
}

let editCatId = null;

function openEdit(cat) {
  editCatId = cat.id;
  $("#editIcon").textContent = cat.icon || "✨";
  $("#editTitle").textContent = `${cat.title} — edit card`;
  $("#editDesc").textContent = cat.description || "";
  $("#editName").value = cat.title || "";
  $("#editName").placeholder = cat.default_title || "Card name";
  $("#editIconIn").value = cat.icon || "";
  $("#editIconIn").placeholder = cat.default_icon || "✨";
  $("#editFocus").value = cat.focus || "";
  $("#editEnabled").checked = cat.enabled !== false;
  $("#editHours").value = cat.refresh_hours == null ? "" : cat.refresh_hours;
  defaultHoursPlaceholder($("#editHours"));
  $("#editTimes").value = timesToText(cat.schedule);
  const overridden = cat.focus_overridden || cat.renamed || cat.enabled === false
    || cat.refresh_hours != null || (cat.schedule && cat.schedule.length);
  $("#editReset").classList.toggle("hidden", !overridden);
  openBox("#editModal");
}

async function saveEdit(regen) {
  const hours = $("#editHours").value.trim();
  const schedule = parseTimes($("#editTimes").value);
  if (schedule === undefined) return;
  const body = {
    // blank name/icon fall back to the shipped ones rather than erroring —
    // the placeholder already shows what emptying the field gives you
    title: $("#editName").value.trim(),
    icon: $("#editIconIn").value.trim(),
    focus: $("#editFocus").value,
    enabled: $("#editEnabled").checked,
    refresh_hours: hours === "" ? null : Math.round(Number(hours)),
    schedule,
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
    toast("Restored this card's shipped name, icon and prompt");
    await refreshStatus();
    render();
  } catch (e) {
    toast(e.message);
  }
});
$("#editDelete").addEventListener("click", async () => {
  const cat = (state.status.categories || []).find((c) => c.id === editCatId);
  closeBox("#editModal");
  await deleteCard(editCatId, cat || { id: editCatId },
    cat ? cat.title : editCatId);
});
$("#editClose").addEventListener("click", () => closeBox("#editModal"));
$("#editModal").addEventListener("click", (ev) => {
  if (ev.target === $("#editModal")) closeBox("#editModal");
});

// ------------------------------------------------- ad-hoc card name modal
// Cards born from an Ask question have no recurring definition to edit —
// only the label and icon they carry on the dashboard.

let nameInsightId = null;

function openNameEdit(insight) {
  nameInsightId = insight.id;
  $("#nameIcon").textContent = insight.icon || "✨";
  $("#nameTitleBar").textContent = `${insight.category_title || "Custom"} — rename card`;
  $("#nameName").value = insight.category_title || "";
  $("#nameIconIn").value = insight.icon || "";
  openBox("#nameModal");
}

$("#nameSave").addEventListener("click", async () => {
  const name = $("#nameName").value.trim();
  if (!name) { toast("Give the card a name"); return; }
  try {
    await api(`api/insight/${nameInsightId}`, {
      method: "PUT",
      body: JSON.stringify({ name, icon: $("#nameIconIn").value.trim() }),
    });
    closeBox("#nameModal");
    await refreshInsights();
    render();
    toast("Card renamed");
  } catch (e) {
    toast(e.message);
  }
});
$("#nameDelete").addEventListener("click", async () => {
  const id = nameInsightId;
  closeBox("#nameModal");
  await deleteCard(id, null, $("#nameName").value.trim());
});
$("#nameClose").addEventListener("click", () => closeBox("#nameModal"));
$("#nameModal").addEventListener("click", (ev) => {
  if (ev.target === $("#nameModal")) closeBox("#nameModal");
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
  defaultHoursPlaceholder($("#newHours"));
  $("#newTimes").value = "";
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
  defaultHoursPlaceholder($("#newHours"));
  $("#newTimes").value = timesToText(cat.schedule);
  $("#newEnabled").checked = cat.enabled !== false;
  $("#newEnabledRow").classList.remove("hidden");
  $("#newDelete").classList.remove("hidden");
  $("#newSave").textContent = "Save";
  openBox("#newModal");
}

async function saveUserInsight() {
  const hours = $("#newHours").value.trim();
  const schedule = parseTimes($("#newTimes").value);
  if (schedule === undefined) return;
  const body = {
    title: $("#newName").value.trim(),
    icon: $("#newIcon").value.trim(),
    focus: $("#newFocus").value.trim(),
    refresh_hours: hours === "" ? null : Math.round(Number(hours)),
    schedule,
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
  const id = userEditId;
  const name = $("#newName").value.trim();
  closeBox("#newModal");
  await deleteCard(id, { id, user: true, title: name }, name);
});
$("#newClose").addEventListener("click", () => closeBox("#newModal"));
$("#newModal").addEventListener("click", (ev) => {
  if (ev.target === $("#newModal")) closeBox("#newModal");
});
// There is no "＋ New insight" button any more. Asking a question is how you
// make a card, and "＋ Make recurring" on the answer is how it becomes a
// scheduled one — so a blank prompt-writing dialog was a second, harder path
// to somewhere you had already been taken.

// -------------------------------------------------------- settings modal
// Auto-saves on change (no Save button) — the point is setting a budget in
// two taps. Slider commits on release ("change"), not on every pixel.

function renderUsageMeter(usage, budgetPct) {
  if (!usage) return;
  const pct = Math.min(100, usage.used_percent || 0);
  const fill = $("#usageFill");
  fill.style.width = pct + "%";
  fill.classList.toggle("over", pct >= budgetPct);
  $("#usageMark").style.left = Math.min(100, budgetPct) + "%";
  const spent = usage.window_tokens >= 1000
    ? `${Math.round(usage.window_tokens / 1000)}k` : String(usage.window_tokens || 0);
  const reset = usage.resets_at
    ? ` Session resets at ${fmtClock(usage.resets_at)}.` : "";
  $("#usageText").textContent = (usage.source === "account"
    ? `${usage.used_percent}% of your account's 5-hour session used (live from Anthropic — `
      + `all Claude use counts, not just Insights). Budget mark at ${budgetPct}%.`
    : `≈${spent} tokens spent by Insights in the last 5 h — about ${usage.used_percent}% of a `
      + `${usage.plan_label} session (rough estimate; install BRain for live account `
      + `usage). Budget mark at ${budgetPct}%.`) + reset;
}

// Generation-defaults fields: ⚙ number input id → settings key. These are
// the add-on's own Configuration options — the panel shows their live value
// and writes back to them, so both screens always agree.
const OPTION_FIELDS = {
  setRefresh: "refresh_hours",
  setHistoryDays: "history_days",
  setTimeout: "timeout_minutes",
  setKeepRuns: "history_keep_runs",
  setKeepDays: "history_keep_days",
};

// sentinel option value; no real model id can collide with it
const CUSTOM_MODEL = "__custom__";

// Model dropdown: the served catalog, grouped, plus whatever is configured
// now (so a hand-typed id survives a round trip) and a Custom… escape hatch
// for models newer than this build.
function renderModelField(data) {
  const sel = $("#setModel");
  const custom = $("#setModelCustom");
  const models = data.models || [];
  const current = data.settings.model || "";
  sel.textContent = "";
  let group = null;
  let parent = sel;
  models.forEach((m) => {
    if (m.group !== group) {
      group = m.group;
      parent = document.createElement("optgroup");
      parent.label = group;
      sel.appendChild(parent);
    }
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.hint ? `${m.label} — ${m.hint}` : m.label;
    parent.appendChild(opt);
  });
  const known = models.some((m) => m.id === current);
  if (!known) {
    const opt = document.createElement("option");
    opt.value = current;
    opt.textContent = `Custom: ${current}`;
    sel.appendChild(opt);
  }
  const other = document.createElement("option");
  other.value = CUSTOM_MODEL;
  other.textContent = "Custom model id…";
  sel.appendChild(other);
  sel.value = current;
  custom.value = known ? "" : current;
  custom.classList.add("hidden");
}

function renderSettingsForm(data) {
  $("#setEnabled").checked = data.settings.auto_enabled !== false;
  $("#setPlan").value = data.settings.plan || "pro";
  $("#setBudget").value = data.settings.budget_percent;
  $("#setBudgetVal").textContent = data.settings.budget_percent + "%";
  renderUsageMeter(data.usage, data.settings.budget_percent);
  Object.entries(OPTION_FIELDS).forEach(([id, key]) => {
    const val = data.settings[key];
    $("#" + id).value = val == null ? "" : String(val);
  });
  renderModelField(data);
  $("#setSyncNote").textContent = data.options_synced
    ? "These are the add-on's own Configuration options — edit them here or on "
      + "the Configuration tab, it's the same setting either way. Changes apply "
      + "immediately, no restart."
    : "The Supervisor isn't reachable, so these are stored in the panel only "
      + "and override the add-on's Configuration tab until it is.";
}

async function openSettings() {
  openBox("#setModal");
  try {
    renderSettingsForm(await api("api/settings"));
  } catch (e) {
    toast("Could not load settings: " + e.message);
  }
}

// Someone editing the add-on's Configuration tab while this dialog is open
// should see it here too. Skipped while a field has focus so a poll can't
// overwrite what's being typed.
async function refreshOpenSettings() {
  const modal = $("#setModal");
  if (!modal.classList.contains("open") || modal.contains(document.activeElement)) return;
  try {
    renderSettingsForm(await api("api/settings"));
  } catch (e) { /* transient — the next tick tries again */ }
}

async function saveSettings(fields) {
  try {
    const data = await api("api/settings", {
      method: "PUT", body: JSON.stringify(fields) });
    renderSettingsForm(data);
    if (state.status) {
      state.status.settings = data.settings;
      state.status.usage = data.usage;
    }
    renderUsageChip();
    renderPausedChip();
    toast("Saved");
  } catch (e) {
    toast(e.message);
  }
}

$("#settingsBtn").addEventListener("click", openSettings);
$("#usageChip").addEventListener("click", openSettings);
$("#pausedChip").addEventListener("click", openSettings);
$("#setEnabled").addEventListener("change", () =>
  saveSettings({ auto_enabled: $("#setEnabled").checked }));
$("#setPlan").addEventListener("change", () =>
  saveSettings({ plan: $("#setPlan").value }));
$("#setBudget").addEventListener("input", () => {
  $("#setBudgetVal").textContent = $("#setBudget").value + "%";
  $("#usageMark").style.left = Math.min(100, Number($("#setBudget").value)) + "%";
});
$("#setBudget").addEventListener("change", () =>
  saveSettings({ budget_percent: Math.round(Number($("#setBudget").value)) }));
Object.entries(OPTION_FIELDS).forEach(([id, key]) => {
  $("#" + id).addEventListener("change", () => {
    const raw = $("#" + id).value.trim();
    let value = null;
    if (raw !== "") {
      value = Math.round(Number(raw));
      if (!isFinite(value)) { toast("Enter a number"); return; }
    }
    saveSettings({ [key]: value });
  });
});
$("#setModel").addEventListener("change", () => {
  const sel = $("#setModel");
  const custom = $("#setModelCustom");
  if (sel.value === CUSTOM_MODEL) {
    // reveal the free-text box; nothing is saved until it's filled in
    custom.classList.remove("hidden");
    custom.focus();
    return;
  }
  custom.classList.add("hidden");
  saveSettings({ model: sel.value });
});
$("#setModelCustom").addEventListener("change", () =>
  saveSettings({ model: $("#setModelCustom").value.trim() }));
$("#setClose").addEventListener("click", () => closeBox("#setModal"));
$("#setModal").addEventListener("click", (ev) => {
  if (ev.target === $("#setModal")) closeBox("#setModal");
});

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

// ---------------------------------------------------------------- findings
// The work list. Memory is what is TRUE of this home, a hypothesis is what
// BRain might have wrong about it, and a finding is what is BROKEN in it.
// Two ways out and no third: fix it, or say it isn't a problem here.

const FIND_STATUS = {
  open:      { label: "Needs a decision", cls: "open" },
  fixing:    { label: "BRain is fixing it…", cls: "fixing" },
  fixed:     { label: "Fixed", cls: "fixed" },
  failed:    { label: "Couldn't fix it", cls: "failed" },
  needs_you: { label: "Needs you", cls: "needsyou" },
  ignored:   { label: "Dismissed", cls: "ignored" },
};

const FIND_SEVERITY = {
  info: "Tidy-up", warning: "Degraded", serious: "Broken", critical: "Urgent",
};

// "live" is the default view on purpose: a work list that opens on its own
// archive is a list nobody works.
const FIND_FILTERS = [
  { id: "live", label: "Needs you", match: (f) =>
    ["open", "fixing", "failed", "needs_you"].includes(f.status) },
  { id: "fixed", label: "Fixed", match: (f) => f.status === "fixed" },
  { id: "ignored", label: "Dismissed", match: (f) => f.status === "ignored" },
  { id: "all", label: "Everything", match: () => true },
];

async function refreshFindings() {
  try {
    const data = await api("api/findings");
    state.findings = data.findings || [];
    updateFindBadge(data.open);
  } catch (e) {
    // transient — the tab keeps whatever it last showed rather than blanking
  }
}

// The badge count always comes from the server (findings_store owns what
// "unsettled" means) — deriving a second answer here is how the tab and the
// list end up disagreeing about how much is waiting.
function updateFindBadge(n) {
  const badge = $("#findBadge");
  if (!badge) return;
  badge.textContent = n ? String(n) : "";
  badge.classList.toggle("hidden", !n);
}

// Every finding button goes through here: all six endpoints answer with the
// same {findings, open}, so there is one place that knows what to do with it.
async function findAction(finding, verb, done, btns) {
  btns.forEach((b) => { b.disabled = true; });
  const del = verb === "forget";
  try {
    const data = await api(
      del ? `api/finding/${finding.ts}` : `api/finding/${finding.ts}/${verb}`,
      { method: del ? "DELETE" : "POST" });
    state.findings = data.findings || [];
    updateFindBadge(data.open);
    renderFindings();
    toast(done);
    if (verb === "fix") { refreshStatus().catch(() => {}); fastPoll(); }
  } catch (e) {
    toast(e.message);
    btns.forEach((b) => { b.disabled = false; });
  }
}

function makeFinding(f) {
  const meta = FIND_STATUS[f.status] || FIND_STATUS.open;
  const card = el("article", `finding sev-${f.severity} st-${meta.cls}`);

  const line = el("div", "findmeta");
  line.appendChild(el("span", "findsev", FIND_SEVERITY[f.severity] || "Degraded"));
  line.appendChild(el("span", "findstate", meta.label));
  if (f.source_title) line.appendChild(el("span", "findsrc", f.source_title));
  card.appendChild(line);
  card.appendChild(el("h3", "findtitle", f.text));

  if (f.detail) card.appendChild(el("p", "finddetail", f.detail));
  if (f.entity_id) card.appendChild(el("code", "findentity", f.entity_id));

  // The proposed fix is shown before anything is done, and replaced by what
  // actually happened afterwards — a stale "here's what I'd do" sitting
  // under a finished run is how you lose track of what the house looks like.
  if (f.result) {
    const box = el("div", "findresult");
    f.result.split("\n\n").forEach((para) => box.appendChild(el("p", null, para)));
    if (f.changed && f.changed.length) {
      const list = el("ul", "findchanged");
      f.changed.forEach((c) => list.appendChild(el("li", null, c)));
      box.appendChild(list);
    }
    card.appendChild(box);
  } else if (f.fix) {
    const box = el("div", "findfix");
    box.appendChild(el("span", "findfixlabel", f.fixable
      ? "BRain would" : "You'd need to"));
    box.appendChild(el("span", null, f.fix));
    card.appendChild(box);
  }

  const actions = el("div", "findactions");
  const btns = [];
  const add = (node) => { btns.push(node); actions.appendChild(node); return node; };

  if (f.status === "fixing") {
    const busy = el("div", "phase");
    busy.appendChild(el("span", "orbit"));
    busy.appendChild(el("span", null, "Fixing it now — this can take a few minutes"));
    actions.appendChild(busy);
  } else if (f.status === "fixed" || f.status === "ignored") {
    const back = add(el("button", "btn small ghost", "Put it back on the list"));
    back.addEventListener("click", () =>
      findAction(f, "reopen", "Back on the list", btns));
    const forget = add(el("button", "btn icon", "✕"));
    tip(forget, "Forget this finding entirely — it can be reported again");
    forget.addEventListener("click", () => {
      if (!window.confirm(
        `Forget “${f.text}”? Unlike dismissing it, BRain may report it again.`)) return;
      findAction(f, "forget", "Forgotten", btns);
    });
  } else {
    if (f.fixable) {
      const fix = add(el("button", "btn small primary",
        f.status === "failed" ? "✦  Try again" : "✦  Fix it"));
      tip(fix, "Let BRain make the change in Home Assistant, then report back");
      fix.addEventListener("click", () => findAction(
        f, "fix", "On it — BRain is making the change", btns));
    }
    const done = add(el("button", "btn small", "✓  I did it"));
    tip(done, "You handled it yourself — mark it resolved");
    done.addEventListener("click", () =>
      findAction(f, "done", "Marked done", btns));
    const ignore = add(el("button", "btn small ghost", "Not a problem"));
    tip(ignore, "Dismiss it — BRain will never raise this again");
    ignore.addEventListener("click", () => findAction(
      f, "ignore", "Dismissed — BRain won't raise it again", btns));
  }
  card.appendChild(actions);
  return card;
}

function renderFindings() {
  const chips = $("#findFilters");
  chips.textContent = "";
  const counts = {};
  FIND_FILTERS.forEach((f) => {
    counts[f.id] = state.findings.filter(f.match).length;
  });
  FIND_FILTERS.forEach((f) => {
    // "Everything" always shows; the others only once they hold something,
    // so a home with nothing wrong isn't handed three empty filters.
    if (f.id !== "all" && f.id !== "live" && !counts[f.id]) return;
    const chip = el("button", "fchip" + (state.findFilter === f.id ? " active" : ""),
      counts[f.id] ? `${f.label} · ${counts[f.id]}` : f.label);
    chip.addEventListener("click", () => { state.findFilter = f.id; renderFindings(); });
    chips.appendChild(chip);
  });

  const list = $("#findList");
  list.textContent = "";
  const active = FIND_FILTERS.find((f) => f.id === state.findFilter) || FIND_FILTERS[0];
  const shown = state.findings.filter(active.match);
  if (!shown.length) {
    list.appendChild(el("div", "findempty", state.findFilter === "live"
      ? "Nothing's broken that BRain can see. Findings appear here as insight "
        + "runs and study sessions turn them up."
      : "Nothing here yet."));
    return;
  }
  shown.forEach((f) => list.appendChild(makeFinding(f)));
}

// ------------------------------------------------------- knowledge modal
// The viewer for everything the analyst has learned: open questions (answer
// or dismiss), learned facts (add/remove), answered Q&A, and the shared
// memory.md the BRain maintains.

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

  // Hypotheses: two taps, not a text box. The whole point of replacing
  // open questions is that answering costs nothing — a form to fill in is
  // exactly the friction that let the old list pile up unanswered.
  const openBoxEl = $("#kOpenQs");
  openBoxEl.textContent = "";
  const open = data.hypotheses || [];
  if (!open.length) {
    openBoxEl.appendChild(el("div", "kempty",
      "Nothing waiting on you — BRain isn't unsure about anything right now."));
  }
  open.slice().reverse().forEach((h) => {
    const row = el("div", "qrow");
    row.appendChild(el("div", "qtext", h.text));

    const actions = el("div", "qform");
    const yes = el("button", "btn small primary", "✓  Yes");
    const no = el("button", "btn small", "✗  No");
    yes.type = no.type = "button";
    tip(yes, "Right — remember it as a fact");
    tip(no, "Wrong — don't pursue this again");

    const settle = async (verb, btn, done) => {
      yes.disabled = no.disabled = true;
      try {
        await api(`api/hypothesis/${h.ts}/${verb}`, { method: "POST" });
        toast(done);
        await refreshInsights().catch(() => {});
        renderIfChanged();
        renderKnowledge();
      } catch (e) {
        toast(e.message);
        yes.disabled = no.disabled = false;
      }
    };
    yes.addEventListener("click", () => settle(
      "confirm", yes, "Filed — it lands in memory at the next consolidation"));
    no.addEventListener("click", () => settle(
      "reject", no, "Noted as a dead end"));

    actions.appendChild(yes);
    actions.appendChild(no);
    row.appendChild(actions);
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
    tip(del, "Forget this fact — it's also removed from the memory file");
    del.addEventListener("click", async () => {
      try {
        const res = await api(`api/knowledge/fact/${f.ts}`, { method: "DELETE" });
        if (res.removing) {
          toast("Forgotten — removing it from the memory file too…");
          $("#kMemMerging").classList.remove("hidden");
          pollMemoryMerge();
        }
        renderKnowledge();
      } catch (e) { toast(e.message); }
    });
    row.appendChild(del);
    factsEl.appendChild(row);
  });

  // "Answered questions" is gone with the model it belonged to: a
  // confirmed guess becomes a plain memory line and its record is
  // settled, so there is no Q/A pair left to show.

  renderPending(data.inbox_pending);
  renderMemory(data);
}

// The consolidate button says how much is waiting, so pressing it is an
// informed choice rather than a hopeful one.
function renderPending(n) {
  const label = $("#kPending");
  const btn = $("#kConsolidate");
  if (!label || !btn) return;
  const count = Number(n) || 0;
  label.textContent = count
    ? `${count} thing${count === 1 ? "" : "s"} waiting`
    : "nothing waiting";
  label.classList.remove("hidden");
  btn.disabled = memState.consolidating || !count;
  btn.textContent = memState.consolidating
    ? "Filing…" : "⇪ File into memory now";
}

// ---- home memory file: formatted view, raw-markdown edit, Claude merge ----

const memState = { editing: false, dirty: false, text: "", pollTimer: null,
                   consolidating: false };

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
    if (currentView !== "memory") return;
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
// Run a consolidation pass now instead of waiting for the daily one. The
// document below is rewritten by it, so unsaved manual edits have to be
// settled first — same rule as teaching it a fact.
$("#kConsolidate").addEventListener("click", async () => {
  if (memState.editing && memState.dirty) {
    if (!window.confirm(
      "You have unsaved manual edits to the memory document.\n\n"
      + "Filing rewrites that document and your unsaved edits would be lost. "
      + "Press Cancel to go save them first, or OK to discard them.")) return;
    setMemEditing(false);
  }
  memState.consolidating = true;
  $("#kConsolidate").disabled = true;
  $("#kConsolidate").textContent = "Filing…";
  $("#kMemMerging").classList.remove("hidden");
  try {
    const res = await api("api/memory/consolidate", { method: "POST" });
    toast(res.consolidated
      ? `Filed ${res.consolidated} thing(s) into memory`
      : "Nothing was waiting — memory is up to date");
  } catch (e) {
    toast("Could not file it: " + e.message);
  } finally {
    memState.consolidating = false;
    $("#kMemMerging").classList.add("hidden");
    renderKnowledge();
  }
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


// ----------------------------------------------------------------- docs
// A small markdown subset is enough for the guide, and keeps the page a
// single self-contained file — no bundler, no CDN (the panel runs behind
// ingress with no outbound access anyway).
//
// The content is authored in docs.js and never user-supplied, but the
// renderer escapes first regardless: a docs page is exactly where a lazy
// innerHTML becomes an injection vector later.

const docsState = { section: null, query: "" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Inline: `code`, **bold**, [text](url). Applied AFTER escaping.
function inlineMd(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function renderMarkdown(src) {
  const lines = src.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;

  const closeList = (stack) => { while (stack.length) out.push(`</${stack.pop()}>`); };
  const listStack = [];

  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^```/.test(line)) {
      closeList(listStack);
      const lang = line.slice(3).trim();
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre class="doccode"${lang ? ` data-lang="${esc(lang)}"` : ""}>`
               + `<code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }

    // table: a header row followed by a |---| separator
    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      closeList(listStack);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push('<div class="doctablewrap"><table class="doctable"><thead><tr>'
               + head.map((c) => `<th>${inlineMd(c)}</th>`).join("")
               + "</tr></thead><tbody>"
               + rows.map((r) => "<tr>" + r.map((c) => `<td>${inlineMd(c)}</td>`).join("") + "</tr>").join("")
               + "</tbody></table></div>");
      continue;
    }

    // blockquote
    if (/^>\s?/.test(line)) {
      closeList(listStack);
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${inlineMd(buf.join(" "))}</blockquote>`);
      continue;
    }

    // headings
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      closeList(listStack);
      const level = h[1].length;
      out.push(`<h${level}>${inlineMd(h[2])}</h${level}>`);
      i++;
      continue;
    }

    // lists (one level of nesting is plenty for this guide)
    const li = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
    if (li) {
      const tag = /\d/.test(li[2]) ? "ol" : "ul";
      const depth = li[1].length >= 2 ? 2 : 1;
      while (listStack.length > depth) out.push(`</${listStack.pop()}>`);
      if (listStack.length < depth) { out.push(`<${tag}>`); listStack.push(tag); }
      // continuation lines belong to the item above
      let text = li[3];
      while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1])
             && !/^\s*([-*]|\d+\.)\s/.test(lines[i + 1])) {
        text += " " + lines[++i].trim();
      }
      out.push(`<li>${inlineMd(text)}</li>`);
      i++;
      continue;
    }

    if (!line.trim()) { closeList(listStack); i++; continue; }

    // paragraph (join until a blank line)
    const buf = [line];
    while (i + 1 < lines.length && lines[i + 1].trim()
           && !/^(#{1,4}\s|```|>|\s*([-*]|\d+\.)\s|\s*\|)/.test(lines[i + 1])) {
      buf.push(lines[++i]);
    }
    out.push(`<p>${inlineMd(buf.join(" "))}</p>`);
    i++;
  }
  closeList(listStack);
  return out.join("\n");
}

// Search matches section titles and body text, and reports where it hit so
// a result is worth clicking rather than a bare title.
function docsSearch(query) {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const hits = [];
  (window.BRAIN_DOCS || []).forEach((sec) => {
    const inTitle = sec.title.toLowerCase().includes(q);
    const lines = sec.body.split("\n")
      .filter((l) => l.trim() && !/^(#{1,4}\s|```)/.test(l))
      .filter((l) => l.toLowerCase().includes(q));
    if (inTitle || lines.length) {
      hits.push({
        sec,
        count: lines.length,
        snippet: lines[0] ? lines[0].replace(/^[>\s*-]+/, "").slice(0, 120) : "",
      });
    }
  });
  return hits;
}

function renderDocsNav() {
  const nav = $("#docsNav");
  const hits = docsSearch(docsState.query);
  nav.innerHTML = "";

  if (hits) {
    if (!hits.length) {
      nav.appendChild(el("p", "docsempty", `No matches for “${docsState.query}”`));
      return;
    }
    hits.forEach(({ sec, count, snippet }) => {
      const b = el("button", "docslink"
        + (sec.id === docsState.section ? " active" : ""));
      b.appendChild(el("span", "docslinktitle", `${sec.icon}  ${sec.title}`));
      if (snippet) b.appendChild(el("span", "docssnippet", snippet));
      if (count > 1) b.appendChild(el("span", "docscount", `${count} matches`));
      b.addEventListener("click", () => selectDocs(sec.id));
      nav.appendChild(b);
    });
    return;
  }

  (window.BRAIN_DOCS || []).forEach((sec) => {
    const b = el("button", "docslink"
      + (sec.id === docsState.section ? " active" : ""));
    b.appendChild(el("span", "docslinktitle", `${sec.icon}  ${sec.title}`));
    b.addEventListener("click", () => selectDocs(sec.id));
    nav.appendChild(b);
  });
}

function selectDocs(id) {
  const sections = window.BRAIN_DOCS || [];
  const sec = sections.find((s) => s.id === id) || sections[0];
  if (!sec) return;
  docsState.section = sec.id;
  $("#docsBody").innerHTML = renderMarkdown(sec.body);
  $("#docsBody").scrollTop = 0;

  // Highlight the search term in the rendered body so a hit is findable
  // on the page, not just in the sidebar.
  const q = docsState.query.trim();
  if (q) {
    const walker = document.createTreeWalker($("#docsBody"), NodeFilter.SHOW_TEXT);
    const targets = [];
    while (walker.nextNode()) {
      if (walker.currentNode.nodeValue.toLowerCase().includes(q.toLowerCase())) {
        targets.push(walker.currentNode);
      }
    }
    targets.forEach((node) => {
      const span = document.createElement("span");
      span.innerHTML = esc(node.nodeValue).replace(
        new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"),
        '<mark>$1</mark>');
      node.parentNode.replaceChild(span, node);
    });
    const first = $("#docsBody").querySelector("mark");
    if (first) first.scrollIntoView({ block: "center" });
  }
  renderDocsNav();
}

// Surface pending guesses on the tab itself. The whole point of two-tap
// confirmation is that answering is cheap — but only if you know there is
// something to answer without opening the tab to check.
async function refreshMemoryBadge() {
  const badge = $("#memBadge");
  if (!badge) return;
  try {
    const data = await api("api/knowledge");
    const n = (data.hypotheses || []).length;
    badge.textContent = n ? String(n) : "";
    badge.classList.toggle("hidden", !n);
  } catch (e) {
    badge.classList.add("hidden");
  }
}

function renderDocs() {
  if (!docsState.section) selectDocs((window.BRAIN_DOCS || [{}])[0].id);
  else renderDocsNav();
}

$("#docsSearch").addEventListener("input", (ev) => {
  docsState.query = ev.target.value;
  const hits = docsSearch(docsState.query);
  // Jump straight to the best match so typing feels like it does something.
  if (hits && hits.length) selectDocs(hits[0].sec.id);
  else renderDocsNav();
});

// ----------------------------------------------------------- onboarding
// A fresh install has no cards. BRain studies the home first, then
// proposes cards grounded in what it found — a generic card about a house
// it has never looked at is noise on every run, so there is deliberately
// no canned fallback.

const obState = { onboarded: true, phase: "learning", learning: null,
                  recommendations: [], sparse: false, missing: "",
                  poll: null, busy: false };

async function refreshOnboarding() {
  try {
    const data = await api("api/onboarding");
    Object.assign(obState, data);
  } catch (e) {
    // Older panel against a newer add-on, or a transient error — treat as
    // onboarded so the dashboard is never held hostage by this call.
    obState.onboarded = true;
  }
  renderOnboarding();
}

function renderOnboarding() {
  if (obState.onboarded) {
    clearInterval(obState.poll);
    obState.poll = null;
    return;
  }

  const learning = obState.learning || { topics: [], done: [], complete: false };
  const box = $("#obTopics");
  box.textContent = "";
  learning.topics.forEach((topic) => {
    const done = learning.done.includes(topic);
    const row = el("div", "obstep" + (done ? " done" : ""));
    row.appendChild(el("span", "obtick", done ? "\u2713" : "\u00b7"));
    row.appendChild(el("span", null, topic));
    box.appendChild(row);
  });

  const ready = learning.complete && learning.memory_ready;
  const chose = obState.phase === "choosing" && (obState.recommendations.length || obState.sparse);

  $("#obLearn").classList.toggle("hidden", ready || chose);
  $("#obRecommend").classList.toggle("hidden", !ready || chose);
  $("#obChoose").classList.toggle("hidden", !chose || obState.sparse);
  $("#obSparse").classList.toggle("hidden", !chose || !obState.sparse);

  if (learning.complete && !learning.memory_ready) {
    $("#obLearnHint").textContent =
      "Studied everything — waiting for what it found to be filed into memory.";
  }

  if (obState.sparse) {
    $("#obSparseText").textContent = obState.missing
      || "There isn't enough here yet for BRain to suggest anything useful.";
  }

  const list = $("#obList");
  list.textContent = "";
  obState.recommendations.forEach((rec, i) => {
    const row = el("label", "obcard");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.dataset.index = String(i);
    row.appendChild(cb);
    const body = el("div", "obcardbody");
    body.appendChild(el("div", "obcardtitle", `${rec.icon || "\u2728"}  ${rec.title}`));
    if (rec.why) body.appendChild(el("div", "obcardwhy", rec.why));
    body.appendChild(el("div", "obcardfocus", rec.focus));
    row.appendChild(body);
    list.appendChild(row);
  });
}

function obPoll() {
  clearInterval(obState.poll);
  // Studying takes minutes; a slow poll is plenty and keeps this cheap.
  obState.poll = setInterval(refreshOnboarding, 15000);
}

async function obCall(route, body, btn) {
  if (obState.busy) return null;
  obState.busy = true;
  if (btn) btn.disabled = true;
  try {
    return await api(route, body === undefined
      ? { method: "POST" }
      : { method: "POST", body: JSON.stringify(body) });
  } catch (e) {
    toast(e.message);
    return null;
  } finally {
    obState.busy = false;
    if (btn) btn.disabled = false;
  }
}

$("#obStart").addEventListener("click", async (ev) => {
  const res = await obCall("api/onboarding/learn", undefined, ev.target);
  if (!res) return;
  toast(res.queued.length
    ? `Studying ${res.queued.length} topic(s) — this runs in the background`
    : "Already studied — checking what it found");
  await refreshOnboarding();
  obPoll();
});

$("#obGo").addEventListener("click", async (ev) => {
  ev.target.textContent = "Thinking\u2026";
  const res = await obCall("api/onboarding/recommend", undefined, ev.target);
  ev.target.textContent = "See what it suggests";
  if (!res) return;
  Object.assign(obState, res, { phase: "choosing" });
  renderOnboarding();
});

$("#obAccept").addEventListener("click", async (ev) => {
  const picked = Array.from($("#obList").querySelectorAll("input:checked"))
    .map((cb) => Number(cb.dataset.index));
  const res = await obCall("api/onboarding/accept", { accept: picked }, ev.target);
  if (!res) return;
  obState.onboarded = true;
  toast(picked.length ? `Created ${picked.length} card(s)` : "Done — no cards created");
  await Promise.all([refreshStatus(), refreshInsights()]);
  render();
});

const obFinish = async (ev) => {
  const res = await obCall("api/onboarding/skip", undefined, ev.target);
  if (!res) return;
  obState.onboarded = true;
  await Promise.all([refreshStatus(), refreshInsights()]);
  render();
};
$("#obSkip").addEventListener("click", obFinish);
$("#obSkip2").addEventListener("click", obFinish);
$("#obNone").addEventListener("click", obFinish);

$("#obRetry").addEventListener("click", async (ev) => {
  obState.sparse = false;
  obState.phase = "learning";
  renderOnboarding();
  await refreshOnboarding();
});

// ---------------------------------------------------------------- views
// Insights / Terminal / Memory. The Memory pane reuses the knowledge
// dialog's markup verbatim — it is relocated out of the modal at startup
// rather than duplicated, so every id (and every handler bound to one)
// keeps working untouched.
let currentView = "insights";

function switchView(name) {
  if (name === currentView) return;
  if (currentView === "memory" && memState.editing && memState.dirty &&
      !window.confirm("Discard your unsaved memory edits?")) return;
  if (currentView === "memory" && memState.editing) setMemEditing(false);

  currentView = name;
  document.querySelectorAll(".viewtab").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view" + name[0].toUpperCase() + name.slice(1)));

  // Insights actions have no meaning on the other tabs. Settings stays —
  // it is add-on-wide, not per-view.
  const refresh = $("#refreshAll");
  if (refresh) refresh.style.display = name === "insights" ? "" : "none";

  if (name === "findings") {
    // render what we have, then again once the fetch lands — but only if
    // it actually changed anything
    renderFindings();
    refreshFindings().then(renderFindings);
  }
  if (name === "terminal") {
    const frame = $("#termFrame");
    // Lazy: don't start a shell session for someone who never opens the tab.
    if (frame.getAttribute("src") === "about:blank") frame.src = "terminal/";
  }
  if (name === "memory") renderKnowledge();
  if (name !== "memory") refreshMemoryBadge();
  if (name === "docs") renderDocs();
}

document.querySelectorAll(".viewtab").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view)));

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
// Relocate the knowledge dialog's body into the Memory tab and retire the
// dialog shell. Done in JS rather than by moving the markup so the ids stay
// exactly where every handler above expects them.
(function adoptMemoryPane() {
  const modal = $("#kModal");
  const host = $("#memoryHost");
  if (!modal || !host) return;
  const body = modal.querySelector(".edit-body");
  if (body) host.appendChild(body);
  modal.remove();
})();

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

async function openCardModal(insight) {
  openBox("#cardModal");
  const pre = $("#cardYaml");
  const warn = $("#cardWarn");
  const hint = $("#cardHint");
  warn.classList.add("hidden");
  pre.textContent = "Loading…";
  try {
    if (!cardInfoCache) cardInfoCache = await api("api/card_info");
  } catch (e) {
    pre.textContent = "Could not load card info: " + e.message;
    return;
  }
  const info = cardInfoCache;
  if (!info.www_cards) {
    pre.textContent = "Dashboard cards are unavailable: the add-on could not write to "
      + "/config/www. Check that the /config mount is writable and restart the add-on.";
    return;
  }
  // HA itself serves the mirrored HTML at /local/… — same origin as every
  // dashboard, so the card works over HTTP, HTTPS, and Nabu Casa alike.
  const localUrl = `${info.local_dir}/${insight.id}${info.local_suffix}`;
  pre.textContent = [
    "type: iframe",
    `url: ${localUrl}`,
    `title: ${(insight.title || "Insight").replace(/[:#"\n]/g, " ").trim()}`,
    "aspect_ratio: 90%",
  ].join("\n");
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
  // No optimistic toast: whether this is a question or a study session is
  // decided server-side (LEARN_RE), and a second copy of that rule here
  // would drift into telling you the wrong thing is happening.
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
  await refreshOnboarding();
  render();
  fastPoll();
  refreshMemoryBadge();
  refreshFindings();
  // resume a guided sign-in if one is mid-flight (page reload)
  try {
    const st = await api("api/auth/setup/status");
    if (["starting", "awaiting_code", "working"].includes(st.phase)) pollSetup();
  } catch (e) { /* ignore */ }
})();
