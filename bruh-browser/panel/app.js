"use strict";
// BRUH Browser's page: the setup steps, the errand in progress, the live
// browser and a short history. Everything an errand reports came from a
// web page, so it is drawn with textContent, never as HTML.

const $ = (sel) => document.querySelector(sel);
const state = { data: null, setupOpen: null, busy: false };

const STATE_WORDS = {
  queued: "Waiting", running: "Working", needs_you: "Waiting for you",
  done: "Done", failed: "Failed", stopped: "Stopped",
};
const STEP_WORDS = { done: "Done", not_yet: "Not yet", unknown: "Not proved yet", running: "Testing…" };
const STEP_ACTIONS = {
  1: { how: "",
       buttons: [["Open the Web Store page", "open", "webstore"], ["Open Chrome's extensions page", "open", "extensions", true]] },
  2: { how: "Open claude.ai below and sign in, then click the puzzle-piece icon in Chrome's toolbar, open Claude, and sign in there too if it asks.",
       buttons: [["Open claude.ai", "open", "claude"]] },
  3: { how: "A terminal opens on the browser's screen below, running Claude Code. Choose your Claude account (or type /login); its sign-in page opens in this Chrome. When it says you are signed in, press Test: the terminal closes by itself.",
       buttons: [["Open the sign-in window", "terminal"]] },
  4: { how: "Opens example.com and reads its heading: a harmless check that Claude Code can drive this Chrome.",
       buttons: [["Run the Test", "test"]] },
};

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") node.textContent = v;
    else if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) {
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function toast(text) {
  const box = $("#toast");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, 5000);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (_) { /* an empty answer */ }
  if (!res.ok) throw new Error(data.error || `The panel answered ${res.status}.`);
  return data;
}

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleString();
}

function money(value, currency) {
  if (value === null || value === undefined) return "";
  return `${Number(value).toFixed(2)}${currency ? " " + currency : ""}`;
}

// ------------------------------------------------------------- setup ---
async function stepAction(kind, page) {
  if (state.busy) return;
  state.busy = true;
  try {
    if (kind === "open") { await api("api/setup/open", { page }); toast("Opened in the browser below."); }
    if (kind === "terminal") { await api("api/setup/terminal", {}); toast("The sign-in window is open on the browser's screen below."); }
    if (kind === "test") { await api("api/setup/test", {}); toast("Testing…"); }
    $("#screen").scrollIntoView({ behavior: "smooth", block: kind === "test" ? "nearest" : "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    state.busy = false;
    refresh();
  }
}

function renderSetup(data) {
  const box = $("#setup");
  if (state.setupOpen === null) state.setupOpen = !data.ready;
  box.hidden = !state.setupOpen;
  $("#setupToggle").setAttribute("aria-expanded", String(state.setupOpen));
  $("#setupToggle").textContent = state.setupOpen ? "Hide setup" : "Setup";
  const list = $("#steps");
  list.replaceChildren(...data.setup.map((step) => {
    const extra = STEP_ACTIONS[step.n] || { how: "", buttons: [] };
    const buttons = extra.buttons.map(([label, kind, page, ghost]) => el("button", {
      type: "button", class: ghost || step.status === "done" ? "ghost" : "",
      onclick: () => stepAction(kind, page),
    }, label));
    return el("li", { class: `step${step.status === "done" ? " is-step-done" : ""}`, id: `step${step.n}` },
      el("span", { class: "num", "aria-hidden": "true", text: step.status === "done" ? "✓" : String(step.n) }),
      el("div", { class: "body" },
        el("div", { class: "title" }, `${step.n}. ${step.title}`,
          el("span", { class: `badge is-${step.status}`, text: STEP_WORDS[step.status] || step.status })),
        el("p", { text: step.detail }),
        step.status === "done" || !extra.how ? null : el("p", { class: "how", text: extra.how }),
        el("div", { class: "actions" }, buttons)));
  }));
  const note = $("#sandboxNote");
  note.hidden = !data.chrome.sandbox_note;
  note.textContent = data.chrome.sandbox_note || "";
}

// ------------------------------------------------------------ errand ---
async function errandAction(kind, id) {
  try {
    await api(`api/tasks/${encodeURIComponent(id)}/${kind}`, {});
    toast(kind === "stop" ? "Stopping the errand." : "Carrying on.");
  } catch (err) {
    toast(err.message);
  }
  refresh();
}

function cartTable(cart) {
  if (!cart || !cart.items || !cart.items.length) return null;
  const cur = cart.currency || "";
  const rows = cart.items.map((it) => el("tr", {},
    el("td", { text: it.name }), el("td", { class: "n", text: `× ${it.quantity}` }),
    el("td", { class: "n", text: money(it.price, cur) })));
  const fees = (cart.fees || []).map((f) => el("tr", {},
    el("td", { text: f.name }), el("td", {}), el("td", { class: "n", text: money(f.amount, cur) })));
  return el("div", {},
    cart.store ? el("p", { class: "muted", text: `At ${cart.store}` }) : null,
    el("table", { class: "cart" },
      el("thead", {}, el("tr", {}, el("th", { text: "Item" }), el("th", { class: "n", text: "Qty" }),
        el("th", { class: "n", text: "Price" }))),
      el("tbody", {}, rows, fees),
      el("tfoot", {}, el("tr", {}, el("td", { text: "Total" }), el("td", {}),
        el("td", { class: "n", text: money(cart.total, cur) })))),
    (cart.substitutions || []).length ? el("p", { text: `Substituted: ${cart.substitutions.join("; ")}` }) : null,
    (cart.left_out || []).length ? el("p", { text: `Left out: ${cart.left_out.join("; ")}` }) : null,
    cart.delivery ? el("p", { text: `Delivery: ${cart.delivery}` }) : null);
}

function renderErrand(task) {
  const body = $("#errandBody");
  const badge = $("#errandState");
  if (!task) {
    badge.hidden = true;
    body.replaceChildren(el("p", { class: "muted",
      text: "No errands yet. Ask brAIn, for example: “add my usual groceries plus oat milk to the cart”." }));
    return;
  }
  badge.hidden = false;
  badge.className = `badge is-${task.state}`;
  badge.textContent = STATE_WORDS[task.state] || task.state;
  const live = task.state === "running" || task.state === "queued";
  const kids = [
    el("p", { class: "errand-prompt", text: task.prompt }),
    el("div", { class: "meta" },
      el("span", { text: task.kind === "test" ? "Setup test" : task.purchase ? "Purchase (approved)" : "Cart only — no purchase" }),
      el("span", { text: `from ${task.source || "brAIn"}` }),
      el("span", { text: ago(task.created_at) }),
      task.steps ? el("span", { text: `${task.steps} steps` }) : null),
  ];
  if (live) kids.push(el("p", { class: "progress" }, el("span", { class: "spinner", "aria-hidden": "true" }),
    el("span", { text: task.progress || "Working" })));
  if (task.state === "needs_you") kids.push(el("div", { class: "callout warn" },
    el("strong", { text: "It needs you in the browser below" }),
    el("p", { text: task.needs_you || "Look at the browser below." }),
    el("div", { class: "actions" },
      el("button", { type: "button", onclick: () => errandAction("continue", task.id) }, "I've done it — continue"),
      el("button", { type: "button", class: "ghost", onclick: () => errandAction("stop", task.id) }, "Stop"))));
  if (task.error && task.state !== "needs_you") {
    const step = task.setup_step;
    kids.push(el("div", { class: task.state === "stopped" ? "callout warn" : "callout bad" },
      el("p", { text: task.error }),
      step ? el("div", { class: "actions" }, el("button", { type: "button", class: "ghost",
        onclick: () => { state.setupOpen = true; refresh(); setTimeout(() => $(`#step${step}`)?.scrollIntoView({ behavior: "smooth" }), 50); },
      }, `Show setup step ${step}`)) : null));
  }
  if (task.order_placed) kids.push(el("div", { class: "callout good" },
    el("strong", { text: `Order placed${task.order_number ? ` — ${task.order_number}` : ""}` })));
  if (task.answer) kids.push(el("p", { class: "report", text: task.answer }));
  const cart = cartTable(task.cart);
  if (cart) kids.push(cart);
  if (cart && !task.purchase && task.state === "done") kids.push(el("div", { class: "callout good" },
    el("p", { text: "Nothing has been bought. brAIn reads you this cart and asks before it buys; the purchase is a second errand you approve." })));
  if (live) kids.push(el("div", { class: "actions" },
    el("button", { type: "button", class: "danger", onclick: () => errandAction("stop", task.id) }, "Stop")));
  body.replaceChildren(...kids);
}

function renderHistory(rows) {
  const list = $("#history");
  if (!rows.length) {
    list.replaceChildren(el("li", { class: "muted", text: "Nothing yet." }));
    return;
  }
  list.replaceChildren(...rows.map((t) => el("li", {},
    el("span", { class: `badge is-${t.state}`, text: STATE_WORDS[t.state] || t.state }),
    el("span", { class: "what", text: t.prompt }),
    el("span", { class: "when", text: `${ago(t.created_at)}${t.cart && t.cart.total != null ? ` · ${money(t.cart.total, t.cart.currency)}` : ""}${t.order_placed ? " · ordered" : ""}` }))));
}

// ------------------------------------------------------------ screen ---
function screenUrl() {
  // noVNC builds its websocket as host + "/" + path, so the path carries the
  // ingress prefix this page was served under.
  const base = location.pathname.replace(/^\//, "").replace(/[^/]*$/, "");
  const q = new URLSearchParams({ autoconnect: "1", resize: "scale", reconnect: "1",
    reconnect_delay: "3000", path: `${base}websockify`, show_dot: "1" });
  return `novnc/vnc.html?${q}`;
}

function renderScreen(data) {
  const frame = $("#screen");
  const note = $("#screenNote");
  if (!frame.getAttribute("src")) frame.src = screenUrl();
  $("#fullLink").href = screenUrl();
  const c = data.chrome;
  const words = [];
  if (!c.running) words.push(`Chrome is starting${c.restarts ? ` (restarted ${c.restarts} times)` : ""}…`);
  if (c.terminal_open) words.push("The Claude Code sign-in window is open on this screen.");
  note.hidden = !words.length;
  note.textContent = words.join(" ");
}

function renderPill(data) {
  const pill = $("#pill");
  const cur = data.current;
  let text = data.ready ? "Ready" : "Setup needed";
  let cls = data.ready ? "is-done" : "is-not_yet";
  if (cur && (cur.state === "running" || cur.state === "queued")) { text = "Working"; cls = "is-running"; }
  else if (cur && cur.state === "needs_you") { text = "Needs you"; cls = "is-needs_you"; }
  pill.textContent = text;
  pill.className = `pill ${cls}`;
}

// ----------------------------------------------------------- refresh ---
async function refresh() {
  clearTimeout(refresh.timer);
  try {
    const data = await api("api/state");
    state.data = data;
    renderPill(data);
    renderSetup(data);
    renderErrand(data.current);
    renderScreen(data);
    renderHistory(data.history || []);
  } catch (err) {
    $("#pill").textContent = "Not answering";
  }
  const cur = state.data && state.data.current;
  const busy = cur && (cur.state === "running" || cur.state === "queued");
  refresh.timer = setTimeout(refresh, busy ? 2000 : 5000);
}

$("#setupToggle").addEventListener("click", () => {
  state.setupOpen = !state.setupOpen;
  if (state.data) renderSetup(state.data);
});
refresh();
