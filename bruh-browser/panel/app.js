"use strict";
// BRUH Browser's page: the setup steps, the errand in progress, the live
// browser and a short history. Everything an errand reports came from a
// web page, so it is drawn with textContent, never as HTML.

const $ = (sel) => document.querySelector(sel);
const state = { data: null, setupOpen: null, busy: false, drafts: {}, confirmBuy: null, sending: false };

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
  4: { how: "If the extension still asks before it acts: in the live browser below, click the Claude icon in Chrome's toolbar (or the puzzle-piece icon, then Claude) to open its side panel, and answer its question with Allow, choosing the answer that keeps allowing the site if it offers one. The extension's site permissions page lists the sites it may act on. Then press Run the Test.",
       buttons: [["Open the extension's site permissions", "open", "permissions"], ["Run the Test", "test", null, true]] },
  5: { how: "Opens example.com and reads its heading: a harmless check that Claude Code can drive this Chrome, and that the extension acts without asking.",
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
async function errandAction(kind, id, body, said) {
  if (state.sending) return;
  state.sending = true;
  try {
    await api(`api/tasks/${encodeURIComponent(id)}/${kind}`, body || {});
    toast(said || (kind === "stop" ? "Stopping the errand." : "Carrying on."));
    if (kind === "answer") delete state.drafts[id];
  } catch (err) {
    toast(err.message);
  } finally {
    state.sending = false;
  }
  refresh();
}

function showStep(n) {
  state.setupOpen = true;
  refresh();
  setTimeout(() => $(`#step${n}`)?.scrollIntoView({ behavior: "smooth" }), 50);
}

const IN_BROWSER = {
  sign_in: "Sign in", captcha: "Prove it's a person", verification: "Enter the code",
  dialog: "Close the dialog", extension: "The Claude extension is asking",
};

// A paused errand, drawn with the controls its question takes. An old
// errand with no question is treated as kind "other".
function questionBox(task) {
  const q = task.question || { kind: "other", text: task.needs_you || "", options: [] };
  const kind = q.kind || "other";
  const id = task.id;
  const kids = [];
  const browserPick = Array.isArray(q.browsers) && q.browsers.length;
  const words = kind === "choice" || kind === "confirm" || kind === "other";
  const inBrowser = kind in IN_BROWSER;
  kids.push(el("strong", { text: browserPick ? "Which browser?" : inBrowser ? `${IN_BROWSER[kind]} in the live browser below`
    : kind === "other" ? "It needs you" : "It's asking you" }));
  kids.push(el("p", { class: "question-text", text: q.text || "Look at the live browser below." }));
  if (q.money) kids.push(el("p", { class: "money-note", text: "Your answer changes what is spent. Nothing is bought until you approve the finished cart." }));
  if (kind === "extension") kids.push(el("p", { text: "To stop it asking on every errand, see setup step 4." }));
  else if (inBrowser) kids.push(el("p", { text: "Do it in the live browser below, then press I've done it, carry on." }));
  const options = browserPick ? q.browsers.map((b) => b.label) : (q.options || []);
  if (options.length) {
    kids.push(el("div", { class: "options", role: "group", "aria-label": "Answers" },
      options.map((label) => el("button", { type: "button", class: "option",
        onclick: () => errandAction("answer", id, { answer: label }, `Answered: ${label}`) }, label))));
  }
  if (words && !browserPick) {
    const boxId = `answer-${id}`;
    const area = el("textarea", { id: boxId, rows: "2", maxlength: "500",
      placeholder: kind === "other" ? "Tell it what to do" : "Or tell it what to do instead",
      oninput: (e) => { state.drafts[id] = e.target.value; } });
    area.value = state.drafts[id] || "";
    const send = () => {
      const text = (state.drafts[id] || "").trim();
      if (!text) { toast("Type what it should do first."); return; }
      errandAction("answer", id, { answer: text }, "Sent. It carries on with your answer.");
    };
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    kids.push(el("label", { class: "answer-label", for: boxId, text: options.length ? "or tell it what to do" : "Your answer" }),
      el("div", { class: "answer-row" }, area, el("button", { type: "button", onclick: send }, "Send")));
  }
  const row = [];
  if (inBrowser || kind === "other") row.push(el("button", { type: "button", class: inBrowser ? "" : "ghost",
    onclick: () => errandAction("answer", id, { carry_on: true }, "Carrying on.") }, "I've done it, carry on"));
  if (inBrowser) row.push(el("button", { type: "button", class: "ghost",
    onclick: () => $("#screen").scrollIntoView({ behavior: "smooth", block: "start" }) }, "Go to the live browser"));
  if (kind === "extension") row.push(el("button", { type: "button", class: "ghost", onclick: () => showStep(4) }, "Show setup step 4"));
  row.push(el("button", { type: "button", class: "ghost danger-ink", onclick: () => errandAction("stop", id) }, "Stop this errand"));
  kids.push(el("div", { class: "actions" }, row));
  return el("div", { class: "callout warn question", "data-kind": kind }, kids);
}

function boughtFrom(cartId) {
  return (state.data?.history || []).find((t) => t.approved_from === cartId);
}

// The finished cart's own choice, the same one brAIn offers: Buy this (a
// second press restates the total) or Don't buy.
function cartChoice(task) {
  const cart = task.cart;
  const cur = cart.currency || "";
  const bought = boughtFrom(task.id);
  if (bought) return el("div", { class: "callout good" }, el("p", { text: `Approved: errand ${bought.id} is placing this order (${STATE_WORDS[bought.state] || bought.state}).` }));
  if (task.declined) return el("div", { class: "callout" }, el("p", { text: "You said don't buy this cart. It will not be bought; ask for a new cart if you change your mind." }));
  if (task.browser_own === false) return el("div", { class: "callout warn" }, el("p", { text: `This cart was built in ${task.browser_label || "a Chrome on another computer"}. BRUH Browser buys only in its own Chrome, so it cannot be bought from here.` }));
  const windowMin = state.data?.approval_window_minutes || 30;
  const age = Date.now() / 1000 - (task.finished_at || 0);
  if (age > windowMin * 60) return el("div", { class: "callout" }, el("p", { text: `This cart is more than ${windowMin} minutes old, and prices and stock move. Ask brAIn for the cart again to buy it.` }));
  if (cart.total === null || cart.total === undefined) return null;
  const total = money(cart.total, cur);
  const armed = state.confirmBuy === task.id;
  const buy = el("button", { type: "button", class: armed ? "buy armed" : "buy",
    onclick: () => {
      if (!armed) {
        state.confirmBuy = task.id;
        clearTimeout(cartChoice.timer);
        cartChoice.timer = setTimeout(() => { state.confirmBuy = null; refresh(); }, 10000);
        renderErrand(state.data.current);
        return;
      }
      state.confirmBuy = null;
      errandAction("buy", task.id, { total: cart.total }, "Approved. A second errand re-reads the checkout and places the order.");
    } }, armed ? `Buy for ${total}?` : "Buy this");
  return el("div", { class: "callout good buybox" },
    el("p", { text: armed ? `Press again to buy this cart for ${total}. The order is placed only if the checkout still shows these items and this total.`
      : "Nothing has been bought. Buy it here, or tell brAIn; either way the order is placed only if the checkout still matches this cart." }),
    el("div", { class: "actions" }, buy,
      armed ? el("button", { type: "button", class: "ghost", onclick: () => {
        state.confirmBuy = null;
        renderErrand(state.data.current);
      } }, "Not now")
        : el("button", { type: "button", class: "ghost", onclick: () => {
          state.confirmBuy = null;
          errandAction("decline", task.id, {}, "Declined. This cart will not be bought.");
        } }, "Don't buy")));
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
    cart.delivery ? el("p", { text: `Delivery: ${cart.delivery}` }) : null,
    el("table", { class: "cart" },
      el("thead", {}, el("tr", {}, el("th", { text: "Item" }), el("th", { class: "n", text: "Qty" }),
        el("th", { class: "n", text: "Price" }))),
      el("tbody", {}, rows, fees),
      el("tfoot", {}, el("tr", {}, el("td", { text: "Total" }), el("td", {}),
        el("td", { class: "n", text: money(cart.total, cur) })))),
    (cart.substitutions || []).length ? el("p", { text: `Substituted: ${cart.substitutions.join("; ")}` }) : null,
    (cart.left_out || []).length ? el("p", { text: `Left out: ${cart.left_out.join("; ")}` }) : null);
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
      task.browser_label ? el("span", { text: `in ${task.browser_label}` }) : null,
      el("span", { text: ago(task.created_at) }),
      task.steps ? el("span", { text: `${task.steps} steps` }) : null),
  ];
  if (live) kids.push(el("p", { class: "progress" }, el("span", { class: "spinner", "aria-hidden": "true" }),
    el("span", { text: task.progress || "Working" })));
  if (task.state === "needs_you") kids.push(questionBox(task));
  if (task.error && task.state !== "needs_you") {
    const step = task.setup_step;
    kids.push(el("div", { class: task.state === "stopped" ? "callout warn" : "callout bad" },
      el("p", { text: task.error }),
      step ? el("div", { class: "actions" }, el("button", { type: "button", class: "ghost",
        onclick: () => showStep(step) }, `Show setup step ${step}`)) : null));
  }
  if (task.order_placed) kids.push(el("div", { class: "callout good" },
    el("strong", { text: `Order placed${task.order_number ? ` — ${task.order_number}` : ""}` })));
  if (task.answer) kids.push(el("p", { class: "report", text: task.answer }));
  const cart = cartTable(task.cart);
  if (cart) kids.push(cart);
  if (cart && !task.purchase && task.state === "done") kids.push(cartChoice(task));
  if (live) kids.push(el("div", { class: "actions" },
    el("button", { type: "button", class: "danger", onclick: () => errandAction("stop", task.id) }, "Stop")));
  // A refresh redraws the errand; keep the person's place in the answer box.
  const active = document.activeElement;
  const keep = active && active.id && body.contains(active) ? [active.id, active.selectionStart, active.selectionEnd] : null;
  body.replaceChildren(...kids.filter(Boolean));
  if (keep) {
    const again = document.getElementById(keep[0]);
    if (again) { again.focus(); try { again.setSelectionRange(keep[1], keep[2]); } catch (_) { /* not a text box */ } }
  }
}

// ---------------------------------------------------------- browsers ---
async function browserAction(path, body, said) {
  try {
    await api(path, body);
    if (said) toast(said);
  } catch (err) {
    toast(err.message);
  }
  refresh();
}

async function listBrowsers() {
  toast("Asking Claude which browsers are connected…");
  try {
    const view = await api("api/browsers?refresh=1");
    if (view.busy) toast("An errand is running; the list refreshes when it ends.");
  } catch (err) {
    toast(err.message);
  }
  refresh();
}

function renderBrowsers(view) {
  const box = $("#browsersBody");
  if (!view) { box.replaceChildren(el("p", { class: "muted", text: "Not available." })); return; }
  const kids = [];
  if (view.native) {
    kids.push(el("p", { text: "This Claude Code reaches only the Chrome in this app, so every errand runs here." }));
  } else if (!view.browsers.length) {
    kids.push(el("p", { class: "muted", text: view.list_error || (view.listed_at ? "No browsers are connected to this Claude account right now." : "Not listed yet.") }));
  } else {
    kids.push(el("ul", { class: "browsers" }, view.browsers.map((b) => el("li", {},
      el("div", { class: "who" },
        el("strong", { text: b.label.charAt(0).toUpperCase() + b.label.slice(1) }),
        el("span", { class: "muted", text: [b.name && b.label !== `Chrome on ${b.name}` ? `named “${b.name}”` : "", b.osPlatform].filter(Boolean).join(" · ") })),
      el("div", { class: "tags" },
        b.own ? el("span", { class: "badge is-done", text: "This app's Chrome" }) : null,
        b.default ? el("span", { class: "badge is-running", text: "Default" }) : null),
      el("div", { class: "actions" },
        b.default ? null : el("button", { type: "button", class: "ghost",
          onclick: () => browserAction("api/browsers/default", { browser: b.own ? "own" : b.deviceId }, `Errands now use ${b.label} unless told otherwise.`) }, "Use by default"),
        view.own_device ? null : el("button", { type: "button", class: "ghost",
          onclick: () => browserAction("api/browsers/own", { browser: b.deviceId }, "Marked as this app's Chrome.") }, "This is the BRUH Browser"))))));
    if (!view.own_device) kids.push(el("p", { class: "note", text: "It is not clear which of these is this app's own Chrome. Press This is the BRUH Browser on the right one; until then an errand stops and asks which to use." }));
  }
  kids.push(el("p", { class: "muted", text: view.default === "own"
    ? "Errands use this app's own Chrome unless you or brAIn pick another. Another computer's Chrome keeps asking its person before it acts, and nothing is ever bought there."
    : `Errands use ${view.default_label || "another browser"} unless told otherwise. Nothing is ever bought there; purchases happen only in this app's own Chrome.` }));
  kids.push(el("div", { class: "actions" }, el("button", { type: "button", class: "ghost", onclick: listBrowsers }, "Check again"),
    view.default === "own" ? null : el("button", { type: "button", class: "ghost",
      onclick: () => browserAction("api/browsers/default", { browser: "own" }, "Errands use this app's Chrome again.") }, "Use this app's Chrome by default")));
  box.replaceChildren(...kids);
}

// -------------------------------------------------------- profiles ---
// What an order-history errand read off a store's own site, kept in this
// add-on: items, brands and things to avoid, each removable, and a store's
// profile can be cleared. Everything in it came from a web page (textContent).
async function profileAction(path, body, said) {
  try { await api(path, body); if (said) toast(said); } catch (err) { toast(err.message); }
  state.clearing = null;
  refresh();
}

function profileItemRow(p, kind, key, label, sub) {
  return el("li", {},
    el("div", { class: "what" }, el("span", { text: label }), sub ? el("span", { class: "sub", text: sub }) : null),
    el("button", { type: "button", class: "ghost", "aria-label": `Remove ${label}`,
      onclick: () => profileAction("api/profiles/remove", { profile: p.id, kind, key },
        "Removed. A later order-history errand will not add it back.") }, "Remove"));
}

function renderProfiles(rows) {
  const box = $("#profilesBody");
  if (!rows.length) {
    box.replaceChildren(el("p", { class: "muted",
      text: "None yet. Ask brAIn to look at your old orders at a store, for example “look at my old Walmart orders and learn what I usually buy”. What it reads is kept here, on this add-on only, and used the next time you ask for your usual order. It never lets an errand buy anything." }));
    return;
  }
  box.replaceChildren(...rows.map((p) => {
    const armed = state.clearing === p.id;
    const kids = [el("h3", { text: p.store }),
      el("p", { class: "cap", text: `${p.items.length} item${p.items.length === 1 ? "" : "s"} · updated ${ago(p.updated_at)}` })];
    if (p.items.length) kids.push(el("ul", {}, p.items.map((it) => profileItemRow(p, "item", it.key, it.name,
      [it.variant, it.quantity ? `usually ${it.quantity}` : "", it.every ? (typeof it.every === "number" ? `about every ${it.every} days` : it.every) : "", it.last_bought ? `last bought ${it.last_bought}` : ""]
        .filter(Boolean).join(" · ")))));
    for (const [kind, title, list] of [["brand", "Brands you prefer", p.brands], ["avoid", "Things to avoid", p.avoid]]) {
      if (list.length) kids.push(el("div", { class: "group" }, el("strong", { text: title }),
        el("ul", {}, list.map((w) => profileItemRow(p, kind, w, w, ""))))); 
    }
    kids.push(el("div", { class: "actions" }, el("button", { type: "button", class: armed ? "danger" : "ghost danger-ink",
      onclick: () => {
        if (!armed) { state.clearing = p.id; renderProfiles(state.data.profiles || []); return; }
        profileAction("api/profiles/clear", { profile: p.id }, `Cleared the ${p.store} profile.`);
      } }, armed ? `Clear ${p.store}? Press again` : "Clear profile"),
      armed ? el("button", { type: "button", class: "ghost", onclick: () => { state.clearing = null; renderProfiles(state.data.profiles || []); } }, "Not now") : null));
    return el("div", { class: "profile" }, kids);
  }));
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
    renderBrowsers(data.browsers);
    renderProfiles(data.profiles || []);
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
