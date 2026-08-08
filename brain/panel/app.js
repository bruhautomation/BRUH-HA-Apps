/* brAIn — panel logic.
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
// Controls get an instant styled tooltip instead of the browser's sluggish
// native title bubble, plus a matching aria-label.
const tip = (node, text) => {
  node.dataset.tip = text;
  node.setAttribute("aria-label", text);
  return node;
};

// ---------------------------------------------------------------- tooltips
// One element for the lot, positioned in JS and clamped to the viewport.
//
// It was a `::after` per control, absolutely positioned at `right: -4px` and
// up to 240px wide — so it hung leftward from the control's right edge and
// fell off the screen for anything sitting in the first ~236px. On a phone
// that was four of the six buttons under a finding; on a desktop it was
// still two, because the findings list starts at the left margin. Nothing in
// CSS can see the viewport edge, so nothing in CSS could fix it.
//
// One element also means one thing on screen at a time, which is what you
// want from a tooltip and what per-control pseudo-elements can't promise.
const TIP_DELAY_MS = 150;
const TIP_GAP = 7;
const TIP_MARGIN = 8;
const tipState = { node: null, timer: null, box: null };

function tipBox() {
  if (!tipState.box) {
    tipState.box = el("div", "tipbox");
    // The text is already on the control as aria-label, so a screen reader
    // must not meet it twice.
    tipState.box.setAttribute("aria-hidden", "true");
    document.body.appendChild(tipState.box);
  }
  return tipState.box;
}

function placeTip(node) {
  const box = tipBox();
  box.textContent = node.dataset.tip || "";
  // Measure before deciding: max-width is a clamp, so the rendered width is
  // whatever the text needed and guessing it is how this broke the first time.
  box.style.left = "0px";
  box.style.top = "0px";
  const a = node.getBoundingClientRect();
  const b = box.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  // Centred on the control, then pulled inside the viewport. Centring rather
  // than edge-anchoring means the clamp only has to act near the very edges.
  const left = Math.max(TIP_MARGIN,
    Math.min(a.left + a.width / 2 - b.width / 2, vw - b.width - TIP_MARGIN));
  // Below by default so the pointer never covers it; above when below would
  // not fit, which is what the old `.card .foot` override was for.
  let top = a.bottom + TIP_GAP;
  if (top + b.height > vh - TIP_MARGIN) top = a.top - b.height - TIP_GAP;
  box.style.left = Math.round(Math.max(TIP_MARGIN, left)) + "px";
  box.style.top = Math.round(Math.max(TIP_MARGIN, top)) + "px";
  box.classList.add("on");
}

function hideTip() {
  clearTimeout(tipState.timer);
  tipState.node = null;
  if (tipState.box) tipState.box.classList.remove("on");
}

// Take down what is SHOWING without cancelling what is pending. A tooltip is
// fixed to where its control was, so a scroll makes a visible one a label
// pointing at nothing — but one still inside its open delay is measured when
// it opens, after the scroll, so it is already correct. Cancelling that one
// too is what made a tooltip vanish for good whenever the page happened to
// settle a scroll in the 150ms after the pointer arrived.
function dismissTip() {
  if (tipState.box) tipState.box.classList.remove("on");
}

function showTip(node) {
  if (!node || !node.dataset.tip || node.disabled) return;
  clearTimeout(tipState.timer);
  tipState.node = node;
  tipState.timer = setTimeout(() => {
    if (tipState.node === node && node.isConnected) placeTip(node);
  }, TIP_DELAY_MS);
}

// Delegated, because most of these controls are built and rebuilt as the
// lists redraw — binding per control would leak a listener per render.
// `pointerover` rather than `mouseenter`: it bubbles, and a touch that
// becomes a press should not leave a bubble behind, which is why the
// pointerdown handler below closes it.
document.addEventListener("pointerover", (ev) => {
  const node = ev.target.closest && ev.target.closest("[data-tip]");
  if (node !== tipState.node) { hideTip(); showTip(node); }
});
document.addEventListener("pointerout", (ev) => {
  const node = ev.target.closest && ev.target.closest("[data-tip]");
  if (node && node === tipState.node) hideTip();
});
document.addEventListener("pointerdown", hideTip);
document.addEventListener("focusin", (ev) => {
  const node = ev.target.closest && ev.target.closest("[data-tip]");
  if (node) showTip(node);
});
document.addEventListener("focusout", hideTip);
// A tooltip is fixed to where the control WAS, so a scroll makes a visible
// one a label pointing at nothing — it goes rather than chasing. A resize
// reflows everything, and the pointer is very unlikely to still be over what
// it was, so that one takes the pending tooltip with it.
window.addEventListener("scroll", dismissTip, true);
window.addEventListener("resize", hideTip);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") hideTip();
});

const state = {
  status: null,
  insights: [],
  findings: [],
  // Guesses waiting to be confirmed. They come down the findings endpoint
  // because they are the same job as a finding — something only the person
  // who lives here can answer — and one list is what makes "nothing waiting"
  // a thing the tab can ever say.
  hypotheses: [],
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

// How long an undoable toast stays up. Longer than a plain one, because a
// plain toast is something you read and this is something you might act on
// — and 3.2s is not enough to notice you pressed the wrong button, look at
// the message, and reach the control.
const TOAST_MS = 3200;
const TOAST_UNDO_MS = 8000;

// `undo` is a token from the server; when there is one the toast grows a
// button. Every ending on the Findings tab deletes its row — that is what
// makes the list a list — so a mis-tap has nothing to put back by hand, and
// the two endings sit beside each other meaning opposite things.
function toast(msg, undo) {
  const t = $("#toast");
  t.textContent = "";
  t.appendChild(el("span", null, msg));
  // Only while the toast is up: the button is the offer, and the offer
  // expires with it. The token expires server-side too, so a stale one is
  // refused rather than acting on a decision made five minutes ago.
  t.classList.toggle("undoable", !!undo);
  if (undo) {
    const btn = el("button", "toastundo", "Undo");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const data = await api(`api/undo/${undo}`, { method: "POST" });
        // A conversation restore answers without the findings payload —
        // feeding its response to takeFindings would blank the Findings
        // tab and its badge over an undo that had nothing to do with them.
        if (data.findings) {
          takeFindings(data);
          renderFindings();
        }
        if (data.restored_conversation) refreshConversationLists();
        t.classList.remove("show");
        // `undone: false` means the row could not go back — the analyst
        // re-reported it while the toast was up, so the list already holds
        // a newer version and overwriting it would lose what happened
        // since. Say which, rather than claiming a success. A batch restore
        // reports its count, and a partial one says both numbers — "put
        // back" over a half-restored list would lie about the other half.
        toast(data.undone ? "Put back"
                          : data.restore_total
                            ? `Put back ${data.restored_count} of ${data.restore_total}`
                            : data.restored_conversation
                              ? "It couldn't be restored"
                              : "It's already back on the list — nothing to undo");
      } catch (e) {
        btn.disabled = false;
        toast(e.message);
      }
    });
    t.appendChild(btn);
  }
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"),
                        undo ? TOAST_UNDO_MS : TOAST_MS);
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

// JSON is not script-safe on its own: `JSON.stringify` leaves `<` alone, so
// an id containing `</script>` would close the tag it is embedded in and the
// rest would be parsed as markup. Escaping `<` covers `</script`, `<script`
// and `<!--` in one go, and `<` is still the same string to the parser.
const jsonInScript = (v) => JSON.stringify(v).replace(/</g, "\\u003c");

const SIZE_SNIPPET = (id) => `<script>(function(){var last=0;function post(){var b=document.body;if(!b)return;var h=Math.ceil(Math.max(b.offsetHeight,b.getBoundingClientRect().height));if(h>0&&Math.abs(h-last)>2){last=h;parent.postMessage({type:"bruh-size",id:${jsonInScript(id)},h:h},"*");}}try{new ResizeObserver(post).observe(document.body);}catch(e){}window.addEventListener("load",post);setTimeout(post,400);setTimeout(post,1200);})();<\/script>`;

window.addEventListener("message", (ev) => {
  const d = ev.data;
  if (!d || d.type !== "bruh-size" || typeof d.h !== "number") return;
  const frame = document.querySelector(`iframe[data-frame="${CSS.escape(String(d.id))}"]`);
  // The sender has to be the frame it says it is. These frames are
  // sandboxed srcdoc, so every one of them reports `ev.origin` as the
  // string "null" — an origin check cannot tell one from another, or from
  // any other opaque-origin window that happens to post at us. Window
  // identity can, and it is the same rule the keyboard message follows.
  if (!frame || ev.source !== frame.contentWindow) return;
  frame.style.height = Math.min(Math.max(d.h, 120), 760) + "px";
});

// ------------------------------------------------------------------ auth UI

// Which chip the disclosure popover currently belongs to — also the "is it
// open" flag, so a re-render can refresh it in place instead of leaving a
// stale reading on screen under a live chip. Declared up here because the
// renderers below read it.
let chipPopFor = null;

function renderAuth() {
  const s = state.status;
  const chip = $("#authChip");
  const text = $("#authChipText");
  chip.classList.remove("ok", "warn", "bad", "busy");
  if (!s) return;
  // A working login is not news. The chip is here to say something is wrong
  // (or being checked) — once it's fine it goes away and gives the bar back
  // to usage, where the numbers actually move.
  let settled = false;
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
  } else {
    settled = true;
    text.textContent = s.auth_source === "shared" ? "Claude · shared login"
      : s.auth_type === "api_key" ? "Claude · API key" : "Claude · subscription";
    chip.classList.add("ok");
    chip.title = text.textContent;
  }
  chip.classList.toggle("hidden", settled);
  // The words are hidden on a phone, so the state has to survive without them.
  chip.setAttribute("aria-label", text.textContent);
  // Three states, not two: not connected → connect; connected but never
  // onboarded → the first-run flow; onboarded → the dashboard.
  const ready = s.authenticated && obState.onboarded;
  $("#setup").classList.toggle("hidden", s.authenticated);
  $("#onboard").classList.toggle("hidden", !s.authenticated || obState.onboarded);
  $("#dash").classList.toggle("hidden", !ready);
  $("#settingsBtn").classList.toggle("hidden", !s.authenticated);
  renderUsageChip();
  renderPausedChip();
  syncTermMode();
}

function fmtClock(epoch) {
  const d = new Date(epoch * 1000);
  return isNaN(d.getTime()) ? "" :
    d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// Token counts, the way the panel says them everywhere: 41231 -> "41.2k".
// One decimal under 100k and none above it — "412.3k" is three digits of
// precision on a number nobody reads that closely.
function fmtTokens(n) {
  const v = Number(n) || 0;
  if (v < 1000) return String(Math.round(v));
  return (v / 1000).toFixed(v < 100000 ? 1 : 0) + "k";
}

// A weekly reset is days away, so a bare clock time is ambiguous — say which
// day. Same short form the cards use for dates.
function fmtDayClock(epoch) {
  const d = new Date(epoch * 1000);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })
    + " " + fmtClock(epoch);
}

// Topbar chip: both usage windows — the 5-hour session that gates automatic
// runs, and the weekly one that a Claude plan really runs you out of. Each
// number sits behind its own word, because "19% · 100%" is two readings with
// nothing on screen saying which window either belongs to.
//
// The reset times are behind a press, not a hover. They were in a `title`,
// which on a phone is a fact that exists and cannot be read — and the phone
// is where this pill is most often the only thing on screen worth reading.
// The dot goes warning-coloured once the budget is reached.
function renderUsageChip() {
  const s = state.status;
  const chip = $("#usageChip");
  const u = s && s.authenticated && s.usage;
  if (!u || u.used_percent == null) {
    chip.classList.add("hidden");
    if (chipPopFor === chip) closeChipPop();
    return;
  }
  const hasWeek = u.week_percent != null;
  $("#usageChipPct").textContent = `${Math.round(u.used_percent)}%`;
  $("#usageChipWeekPct").textContent = hasWeek ? `${Math.round(u.week_percent)}%` : "";
  $("#usageChipWeek").classList.toggle("hidden", !hasWeek);
  chip.classList.toggle("ok", !u.blocked);
  chip.classList.toggle("warn", !!u.blocked);
  chip.removeAttribute("title");
  chip.setAttribute("aria-label",
    `Claude usage — session ${Math.round(u.used_percent)}%`
    + (hasWeek ? `, week ${Math.round(u.week_percent)}%` : "")
    + (u.blocked ? ". Automatic insights are paused until it resets." : "")
    + ". Press for detail.");
  chip.classList.remove("hidden");
  // Keep an open disclosure honest: usage polls every few seconds.
  if (chipPopFor === chip) fillUsagePop();
}

// Both windows, each with its number and when it rolls over — the two facts
// the pill itself has no room for. A window with no known reset is listed
// with its reading and no time rather than left out: the reading is real
// either way, and a missing row reads as a missing window.
function fillUsagePop() {
  const u = (state.status && state.status.usage) || {};
  const rows = [];
  const row = (name, pct, when) =>
    `<div class="prow"><span class="pname">${esc(name)}`
    + (when ? `<span class="pwhen">${esc(when)}</span>` : "")
    + `</span><span class="pval">${Math.round(pct)}%</span></div>`;
  rows.push(row("Session · 5 hours", u.used_percent || 0,
    u.resets_at ? `resets ${fmtClock(u.resets_at)}` : ""));
  if (u.week_percent != null) {
    rows.push(row("This week", u.week_percent,
      u.week_resets_at ? `resets ${fmtDayClock(u.week_resets_at)}` : ""));
  }
  // The budget only ever throttles brAIn's own scheduled work, so it belongs
  // here beside the number it is measured against — not in a separate chip
  // repeating a percentage the pill is already showing. When it has been
  // reached this is the only place that says so, so it says it plainly.
  if (u.budget_percent != null) {
    rows.push(u.blocked
      ? `<p class="pnote"><b>Automatic insights are paused.</b> The session `
        + `window is past your <b>${Math.round(u.budget_percent)}%</b> budget`
        + (u.resets_at ? `, and resumes when it rolls over at `
                       + `<b>${esc(fmtClock(u.resets_at))}</b>` : "")
        + `. Anything you ask for by hand still runs, and the budget is in `
        + `<b>⚙ Settings</b> if it is set too tight.</p>`
      : `<p class="pnote">Automatic insights pause once the session window `
        + `passes <b>${Math.round(u.budget_percent)}%</b>, leaving the rest of `
        + `your Claude account to you. Asking a question by hand always runs.</p>`);
  }
  rows.push(spendRows(u));
  setChipPop($("#usageChip"), "Claude usage", rows.join(""));
}

// A run id, as the name of the thing that spent the tokens.
//
// The card usually still exists, so its own title is the best answer; a
// deleted one falls back to the id it was recorded under rather than
// disappearing from the list, because a row that vanishes takes its tokens
// off a total that did not shrink.
function spendLabel(id) {
  if (!id) return "Everything else";
  if (id === "onboarding") return "First-run setup";
  if (id.startsWith("fix-")) return "Fix it (a finding)";
  const insight = insightFor(id);
  if (insight && insight.title) return insight.title;
  const cat = (state.status && state.status.categories || []).find((c) => c.id === id);
  if (cat && cat.title) return cat.title;
  return id;
}

// Where the session went — the half of "you are at 41%" that the pill has
// never been able to answer.
//
// The ledger has recorded a card id per run since the budget existed and
// nothing ever read it back, so the only way to attribute a jump was to
// remember what you had pressed. Deliberately scoped: these are brAIn's own
// runs and the note says so, because when the figure above is the account's
// (which covers the terminal, the chat and voice too) a breakdown read as
// exhaustive is how you conclude a terminal session is free.
function spendRows(u) {
  const rows = u && u.breakdown;
  if (!rows || !rows.length) return "";
  const out = [`<div class="psub">What brAIn spent, this session</div>`];
  rows.forEach((r) => {
    const runs = r.runs > 1 ? `${r.runs} runs` : "1 run";
    out.push(`<div class="prow"><span class="pname">`
      + `${esc(r.rest ? "Everything else" : spendLabel(r.id))}`
      + `<span class="pwhen">${esc(runs)}</span></span>`
      + `<span class="pval">${esc(fmtTokens(r.tokens))}</span></div>`);
  });
  out.push(`<p class="pnote">`
    + (u.source === "account"
      ? `Insight, fix and setup runs only — the percentage above is your whole `
        + `Anthropic account, so the terminal, the chat and voice are in that `
        + `number and not in this list.`
      : `Insight, fix and setup runs in the last 5 hours, against a rough `
        + `<b>${esc(u.plan_label || "plan")}</b> allowance. Sign in with your Claude `
        + `subscription for your account's real usage instead of this estimate.`)
    + `</p>`);
  return out.join("");
}

// Topbar chip that says WHY nothing is auto-generating — and undoes it.
//
// Only for the reason a press can do something about. "Usage budget
// reached" used to get a chip of its own, sitting next to a usage pill
// already reporting the very number it was about — the same fact twice,
// wrapping the bar onto a second row to say it. The pill carries that state
// itself: its dot goes warning-coloured and its popover explains what the
// budget gates and when the window rolls over. What is left here is the one
// thing that is a switch somebody turned off.
function renderPausedChip() {
  const s = state.status;
  const chip = $("#pausedChip");
  const text = $("#pausedChipText");
  let label = "";
  let mode = "";
  if (s && s.authenticated && s.settings && s.settings.auto_enabled === false) {
    label = "Auto insights off";
    mode = "off";
    chip.title = "Turn automatic insights back on";
  }
  text.textContent = label;
  chip.dataset.mode = mode;
  if (label) {
    chip.setAttribute("aria-label",
      "Automatic insights are off — press to turn them on");
  }
  chip.classList.toggle("hidden", !label);
  if (!label && chipPopFor === chip) closeChipPop();
}

// ------------------------------------------------------- chip disclosures

function setChipPop(anchor, title, bodyHtml) {
  const pop = $("#chipPop");
  $("#chipPopTitle").textContent = title;
  $("#chipPopBody").innerHTML = bodyHtml;
  pop.classList.remove("hidden");
  chipPopFor = anchor;
  anchor.setAttribute("aria-expanded", "true");
  positionChipPop();
}

// Under the chip and right-aligned with it, then pulled back inside the
// viewport — the chips live at the right-hand end of the bar, and on a phone
// that end is the screen edge.
function positionChipPop() {
  if (!chipPopFor) return;
  const pop = $("#chipPop");
  const a = chipPopFor.getBoundingClientRect();
  // Height is bounded to what is left on the side it opens, and the
  // overflow scrolls. It never mattered while this held two rows and a
  // sentence; the spend breakdown is up to seven more, and a popover whose
  // last rows are under the bottom of the screen is a list with no end —
  // the same failure the tooltips had sideways, for the same reason: CSS
  // cannot see the edge. Measured before the width, because a scrollbar
  // appearing changes it.
  //
  // Below the anchor by default — every chip lives in the top bar — but
  // flipped above when below cannot hold it and above holds more: the chat
  // meta line's model button anchors one of these from the bottom edge of
  // the screen, where "below" is no room at all.
  const below = window.innerHeight - a.bottom - 14;
  const above = a.top - 14;
  const flip = below < 180 && above > below;
  pop.style.maxHeight = Math.max(180, flip ? above : below) + "px";
  const w = pop.offsetWidth;
  const left = Math.max(8, Math.min(a.right - w, window.innerWidth - w - 8));
  pop.style.left = Math.round(left) + "px";
  pop.style.top = flip
    ? Math.round(Math.max(8, a.top - 6 - pop.offsetHeight)) + "px"
    : Math.round(a.bottom + 6) + "px";
}

function closeChipPop() {
  if (!chipPopFor) return;
  chipPopFor.setAttribute("aria-expanded", "false");
  chipPopFor = null;
  $("#chipPop").classList.add("hidden");
}

// A press on the chip toggles its own disclosure; a press anywhere else
// dismisses it. Nothing here traps focus or locks the page — it is a label
// that got too long, not a dialog.
function toggleChipPop(anchor, fill) {
  if (chipPopFor === anchor) closeChipPop();
  else { closeChipPop(); fill(); }
}

document.addEventListener("click", (ev) => {
  if (!chipPopFor) return;
  // Inside the popover, or on the control that owns it. The second is not a
  // nicety: this listener runs after the handler that opened the popover, so
  // without it every press would open and immediately close again. It used
  // to name `.chip.clickable` specifically, which meant any OTHER control
  // that opened one — a finding's "Remind me later", say — could never show
  // it at all.
  if (ev.target.closest("#chipPop")) return;
  if (chipPopFor.contains(ev.target)) return;
  closeChipPop();
});
window.addEventListener("resize", () => positionChipPop());
window.addEventListener("scroll", () => closeChipPop(), true);

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

const ACTIVE_STATES = ["queued", "collecting", "searching", "generating", "parsing", "fixing"];

function phaseLabel(jobState) {
  return {
    queued: "Queued…",
    collecting: "Gathering your home's data…",
    searching: "Looking up what this needs…",
    generating: "Claude is analyzing & designing…",
    parsing: "Rendering visualization…",
    fixing: "Working on the fix…",
  }[jobState] || "Working…";
}

// What the run is spending, while it is spending it.
//
// A generation is minutes of spinner, and the only thing that made it
// visible afterwards was the usage pill moving with nothing on screen
// saying which card moved it. The size is knowable the moment the prompt
// exists, so it is said then: an ad-hoc question posts the WHOLE home
// (every entity, not the category's slice), which is why one costs several
// times what a category card costs, and that is a fact worth reading
// before the answer arrives rather than inferring from a percentage later.
function jobSentNote(job) {
  if (!job || !job.prompt_chars) return "";
  const parts = [];
  // A searching run is given no entities — it is given a map and goes and
  // fetches what it needs — so it must not claim a count the snapshot path
  // would have meant literally.
  if (job.entities) parts.push(`${job.entities} entities`);
  parts.push(`~${fmtTokens(job.prompt_chars / 4)} tokens sent`);
  return parts.join(" · ");
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
// Everything the card can do that isn't about what's on screen right now.
// Same popover the rest of the panel uses, so it closes the same way and only
// one is ever open — and each item gets its words, which is what six unlabelled
// glyphs never had room for.
function cardMenuButton(items) {
  const btn = el("button", "btn icon", "⋯");
  tip(btn, "More");
  btn.addEventListener("click", () => {
    if (chipPopFor === btn) { closeChipPop(); return; }
    const rows = items.map(([icon, label, hint], i) =>
      `<button class="cardmenuitem" data-i="${i}">`
      + `<span class="cmicon">${esc(icon)}</span>`
      + `<span class="cmtext"><b>${esc(label)}</b>`
      + `<small>${esc(hint)}</small></span></button>`).join("");
    setChipPop(btn, "", `<div class="cardmenu">${rows}</div>`);
    $("#chipPop").querySelectorAll(".cardmenuitem").forEach((row) =>
      row.addEventListener("click", () => {
        closeChipPop();
        items[Number(row.dataset.i)][3]();
      }));
  });
  return btn;
}

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
  // One button on the head, and a menu for the rest. Six icons in a row beside
  // the title is what squeezed the title into an ellipsis on a phone: they are
  // `flex: none`, so every one of them was taken out of the words you read the
  // card by. Expand earns the visible slot because it is the only one that
  // does something to what is on screen rather than to the card's definition.
  if (shown) {
    const expand = el("button", "btn icon", "⤢");
    tip(expand, "Expand");
    expand.addEventListener("click", () => openModal(shown));
    actions.appendChild(expand);
  }

  const menu = [];
  if (!active && !view) {
    menu.push(["↻", "Regenerate", "Run this card again now",
      () => generate(id, (insight && insight.question) || job.question)]);
  }
  // ✎ edits every card: a category card opens its full editor, an ad-hoc
  // Ask card (no definition behind it) gets the name/icon dialog
  if (catInfo || insight) {
    menu.push(["✎", catInfo ? "Edit" : "Rename", catInfo
      ? (catInfo.user ? "Edit insight — name, icon, prompt, schedule"
        : "Edit card — name, icon, prompt, schedule")
      : "Rename this card — name and icon",
      () => {
        if (!catInfo) openNameEdit(insight);
        else if (catInfo.user) openUserEdit(catInfo);
        else openEdit(catInfo);
      }]);
  }
  if (catInfo) {
    menu.push(["💬", "Give feedback", "Remembered for every future run",
      () => openFeedback(catInfo)]);
  }
  if (shown) {
    menu.push(["▦", "Add to dashboard", "Copy this card into Home Assistant",
      () => openCardModal(shown)]);
  }
  // ✕ deletes every card — including one whose only trace is a job, so a
  // failed Ask can be cleared away instead of sitting there forever.
  // A still-running job is left alone: the worker would just re-register it.
  if (catInfo || insight || (fallbackId && !active)) {
    menu.push(["✕", "Delete", "Delete this card and its history",
      () => deleteCard(id, catInfo, catName)]);
  }
  if (menu.length) actions.appendChild(cardMenuButton(menu));
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
    const sent = jobSentNote(job);
    if (sent) phase.appendChild(el("span", "phasecost", sent));
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
    // A card used to end in a yes/no row for every guess the run raised.
    // Those are decisions, and decisions live on the Findings tab — the
    // same three claims were on the card, in the Memory tab, and counted
    // by neither, so answering one left the other two on screen looking
    // unanswered. The card reports; it no longer asks.
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
    // What this run cost, on the run it cost it. The number was already in
    // the stored card and only the stopwatch was ever rendered — so the
    // expensive card and the cheap one looked identical, and the only
    // evidence either way was a percentage in the top bar attributable to
    // nothing. Seconds and tokens are not the same reading: a fast card
    // over the whole home outspends a slow one over eight thermostats.
    const cost = shown.meta && shown.meta.cost;
    if (cost && cost.total) {
      const span = el("span", null, `${fmtTokens(cost.total)} tokens`);
      tip(span, `${fmtTokens(cost.input)} in · ${fmtTokens(cost.output)} out`
        + (cost.cached ? ` · ${fmtTokens(cost.cached)} read from cache (free)` : "")
        + ". Counted against your 5-hour session window.");
      foot.appendChild(span);
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
        : "Studying whatever brAIn knows least about — check Memory shortly");
      return;
    }
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
}

// One ✕ for every kind of card, and it means the same thing for all of them:
// gone. brAIn proposes the cards a given home should have, so the way to get
// one back is to ask for it again — not to fish it out of a graveyard.
async function deleteCard(id, catInfo, name) {
  const label = name || (catInfo && catInfo.title) || "this card";
  if (!window.confirm(
    `Delete “${label}” and its history? This can't be undone — ask for it `
    + "again any time and brAIn will build it fresh.")) return;
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
    closeChipPop();
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
  // The weekly window isn't budgeted against, but it is the one that ends a
  // Claude plan's week — so it is stated wherever the session is.
  const week = usage.week_percent == null ? ""
    : ` Your week is ${usage.week_percent}% used`
      + (usage.week_resets_at ? `, resetting ${fmtDayClock(usage.week_resets_at)}.` : ".");
  $("#usageText").textContent = (usage.source === "account"
    ? `${usage.used_percent}% of your account's 5-hour session used (live from Anthropic — `
      + `all Claude use counts, not just Insights). Budget mark at ${budgetPct}%.`
    : `≈${spent} tokens spent by Insights in the last 5 h — about ${usage.used_percent}% of a `
      + `${usage.plan_label} session (rough estimate; sign in with your Claude subscription `
      + `for live account usage). Budget mark at ${budgetPct}%.`) + reset + week;
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
  $("#setTerminalUi").value = data.settings.terminal_ui || "chat";
  $("#setGatherMode").value = data.settings.gather_mode || "search";
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

// `note` is what to say when the save came from somewhere that isn't the
// Settings dialog — "Saved" is only meaningful next to the field you just
// changed, and the topbar chip is nowhere near one.
async function saveSettings(fields, note) {
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
    toast(note || "Saved");
  } catch (e) {
    toast(e.message);
  }
}

$("#settingsBtn").addEventListener("click", openSettings);

// The pill answers the question it raises: two readings, and when each one
// starts over. It used to open Settings, where neither number appears.
$("#usageChip").addEventListener("click", () =>
  toggleChipPop($("#usageChip"), fillUsagePop));

// The chip undoes what it reports. "Auto insights off" is a switch, so
// pressing it is the switch — one press, no dialog, and the chip goes away
// because the thing it was reporting is no longer true. A budget that has
// been reached is not a switch, so that one explains itself instead.
$("#pausedChip").addEventListener("click", async () => {
  closeChipPop();
  await saveSettings({ auto_enabled: true },
    "Automatic insights on — recurring cards will refresh again");
});
$("#setEnabled").addEventListener("change", () =>
  saveSettings({ auto_enabled: $("#setEnabled").checked }));
$("#setPlan").addEventListener("change", () =>
  saveSettings({ plan: $("#setPlan").value }));
$("#setGatherMode").addEventListener("change", () =>
  saveSettings({ gather_mode: $("#setGatherMode").value }));
// Applied straight away rather than on the next status poll, so the Terminal
// tab has already changed by the time the dialog is closed — and through the
// same path as the tab's own switch, so changing it here carries the
// conversation too rather than being the one route that abandons it.
$("#setTerminalUi").addEventListener("change", () => {
  switchTermMode($("#setTerminalUi").value);
});
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
// brAIn might have wrong about it, and a finding is what is BROKEN in it.
// Two ways out and no third: fix it, or say it isn't a problem here.

const FIND_STATUS = {
  open:      { label: "Needs a decision", cls: "open" },
  fixing:    { label: "brAIn is fixing it…", cls: "fixing" },
  fixed:     { label: "brAIn fixed it — have a look", cls: "fixed" },
  failed:    { label: "Couldn't fix it", cls: "failed" },
  needs_you: { label: "Needs you", cls: "needsyou" },
  ignored:   { label: "Dismissed", cls: "ignored" },
};

const FIND_SEVERITY = {
  info: "Tidy-up", warning: "Degraded", serious: "Broken", critical: "Urgent",
};

// "live" is the default view on purpose: a work list that opens on its own
// archive is a list nobody works.
// A snoozed finding is still live — it just isn't asking yet, so it comes
// out of "Needs you" and gets a chip of its own rather than vanishing. The
// point of "remind me later" is that it comes back, and something you can't
// find is not something that came back.
// "fixed" is in the live list: brAIn changed something in the house, and
// that is news until you have read it. The card's only button then is
// "Got it", which ends it like every other ending does.
//
// There are two filters and no more. There used to be four: "Answered",
// which listed the settled ledger, and "Everything", which existed mostly
// to reach it. Both contradicted the thing that makes an ending an ending —
// settling a finding writes a plain fact into memory and DELETES the row,
// and memory is then the one place that answer is read from. Rendering the
// ledger beside the work list put a growing pile of answered cards next to
// a list that is supposed to empty, and invited people to treat it as the
// record when memory already is.
//
// The ledger itself is untouched and must stay: it is the dedup index that
// stops the analyst re-raising next week what you answered today. It is
// simply not a view any more.
const FIND_FILTERS = [
  { id: "live", label: "Needs you", match: (f) =>
    ["open", "fixing", "fixed", "failed", "needs_you"].includes(f.status)
    && !findings_isSnoozed(f) },
  { id: "snoozed", label: "Later", match: (f) => findings_isSnoozed(f) },
];

async function refreshFindings() {
  try {
    const data = await api("api/findings");
    takeFindings(data);
  } catch (e) {
    // transient — the tab keeps whatever it last showed rather than blanking
  }
}

// Every findings endpoint answers with the same
// {findings, hypotheses, open, settled}, so there is one place that unpacks
// it. `settled` is deliberately dropped on the floor: the ledger is a dedup
// index the server reads, not something the panel renders — settling writes
// the answer into memory and deletes the row, and memory is where that
// answer is read from afterwards.
function takeFindings(data) {
  state.findings = data.findings || [];
  state.hypotheses = data.hypotheses || [];
  updateFindBadge(data.open);
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
// same {findings, hypotheses, open}, so there is one place that knows what
// to do with it. `note` is the homeowner's reason, sent with the endings
// that have somewhere to put it.
async function findAction(finding, verb, done, btns, note) {
  btns.forEach((b) => { b.disabled = true; });
  const del = verb === "forget";
  try {
    const data = await api(
      del ? `api/finding/${finding.ts}` : `api/finding/${finding.ts}/${verb}`,
      { method: del ? "DELETE" : "POST",
        ...(note ? { body: JSON.stringify({ note }) } : {}) });
    takeFindings(data);
    renderFindings();
    // `undo` is present on the presses that took a row away, and absent on
    // Fix it (a Claude run is already touching the house) and on the snooze
    // (it took nothing away, and has "Bring it back now").
    toast(done, data.undo);
    if (verb === "fix") { refreshStatus().catch(() => {}); fastPoll(); }
  } catch (e) {
    toast(e.message);
    btns.forEach((b) => { b.disabled = false; });
  }
}

// The reason box. It opens in place of the card's buttons rather than in a
// popover, because it is the only control on this tab you type into and a
// floating box anchored to a button is a bad place to type a sentence on a
// phone — and because what you are correcting has to stay on screen while
// you write about it.
//
// Sending nothing is a first-class answer. "Not a problem here" needs no
// explanation, so Send is never disabled: the note is offered, not demanded,
// and a required field here would turn a one-press dismissal into a chore
// and get filled with "no" forever after.
function openNoteForm(card, actions, onSend, opts) {
  const form = el("div", "findnote");
  form.appendChild(el("p", "findnotehint", opts.hint));
  const ta = document.createElement("textarea");
  ta.className = "findnotebox";
  ta.rows = 2;
  ta.maxLength = 400;
  ta.placeholder = opts.placeholder;
  form.appendChild(ta);
  const row = el("div", "findnoteactions");
  const send = el("button", "btn small primary", opts.send);
  const cancel = el("button", "btn small ghost", "Cancel");
  row.appendChild(send);
  row.appendChild(cancel);
  form.appendChild(row);

  actions.classList.add("hidden");
  card.appendChild(form);
  ta.focus();

  send.addEventListener("click", () => {
    send.disabled = cancel.disabled = true;
    onSend(ta.value.trim(), [send, cancel]);
  });
  cancel.addEventListener("click", () => {
    form.remove();
    actions.classList.remove("hidden");
  });
  // Enter sends, Shift+Enter breaks the line — a two-row box is for one
  // sentence, and reaching for a button after typing one is the friction
  // that stops people typing them.
  ta.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send.click(); }
  });
}

function findings_isSnoozed(f) {
  return !!f.snoozed_until && f.snoozed_until * 1000 > Date.now();
}

// "Back tomorrow" beats "back 2026-08-01 14:03" for a thing you chose in
// those words a moment ago.
function timeUntil(epoch) {
  const secs = epoch - Date.now() / 1000;
  if (secs <= 0) return "now";
  if (secs < 5400) return "in an hour";
  if (secs < 172800) return "tomorrow";
  if (secs < 1209600) return `in ${Math.round(secs / 86400)} days`;
  return `on ${new Date(epoch * 1000).toLocaleDateString(
    [], { month: "short", day: "numeric" })}`;
}

const SNOOZE_OPTIONS = [
  ["hour", "In an hour"],
  ["tomorrow", "Tomorrow"],
  ["week", "Next week"],
  ["month", "Next month"],
];

async function snoozeFinding(f, choice, btns) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(`api/finding/${f.ts}/snooze`, {
      method: "POST", body: JSON.stringify({ for: choice }) });
    takeFindings(data);
    renderFindings();
    if (chatState.finding && chatState.finding.ts === f.ts && choice !== "now") {
      setChatFinding(null);
    }
    toast(choice === "now" ? "Back on the list"
                           : `Reminding you ${timeUntil(
                               Math.floor(Date.now() / 1000)
                               + { hour: 3600, tomorrow: 86400, week: 604800,
                                   month: 2592000 }[choice])}`);
  } catch (e) {
    toast(e.message);
    btns.forEach((b) => { b.disabled = false; });
  }
}

function openSnoozePop(anchor, f, btns) {
  const rows = SNOOZE_OPTIONS.map(([id, label]) =>
    `<button class="btn small snoozeopt" data-for="${id}">${esc(label)}</button>`
  ).join("");
  setChipPop(anchor, "Remind me", `<div class="snoozeopts">${rows}</div>`
    + `<p class="pnote">It stays exactly as it is — still open, still yours to
       decide. This only stops it asking until then.</p>`);
  $("#chipPop").querySelectorAll(".snoozeopt").forEach((btn) =>
    btn.addEventListener("click", () => {
      closeChipPop();
      snoozeFinding(f, btn.dataset.for, btns);
    }));
}

// Discuss: hand the finding to the chat and go there. The action bar that
// appears above the composer is what makes it a discussion you can end
// rather than a detour — Fix it, I've fixed it and Remind me later are one
// press away without coming back to this tab.
async function discussFinding(f, btns) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    if (chatState.session === "classic") applyTermMode("chat");
    switchView("terminal");
    chatConnect();
    await api(`api/finding/${f.ts}/discuss`, { method: "POST" });
    setChatFinding(f);
  } catch (e) {
    toast(e.message);
  } finally {
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
      ? "brAIn would" : "You'd need to"));
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
  } else if (f.status === "fixed") {
    // brAIn already wrote what it changed into memory when it made the
    // change, so this press is only "I have read it" — one button, because
    // offering a decision on something already done is a decision about
    // nothing.
    const ok = add(el("button", "btn small primary", "✓  Got it"));
    tip(ok, "Clear it off the list — what brAIn changed is already in memory");
    ok.addEventListener("click", () => findAction(f, "ack", "Cleared", btns));
  } else if (f.status === "ignored") {
    // A row dismissed before the settled ledger existed, still on disk
    // until startup moves it. Startup normally gets there first.
    const back = add(el("button", "btn small ghost", "Put it back on the list"));
    back.addEventListener("click", () =>
      findAction(f, "reopen", "Back on the list", btns));
  } else {
    if (f.fixable) {
      const fix = add(el("button", "btn small primary",
        f.status === "failed" ? "✦  Try again" : "✦  Fix it"));
      tip(fix, "Let brAIn make the change in Home Assistant, then report back");
      fix.addEventListener("click", () => findAction(
        f, "fix", "On it — brAIn is making the change", btns));
    }
    // Talk about it before deciding. The discussion is read-only by
    // construction — the prompt says so — because "explain this to me" and
    // "go change my house" are different consents, and Fix it is the one
    // that gives the second.
    const talk = add(el("button", "btn small", "💬  Discuss"));
    tip(talk, "Ask brAIn about this one in the chat, without changing anything");
    talk.addEventListener("click", () => discussFinding(f, btns));

    // The two endings, in the words of what they mean rather than of what
    // they do to a row. They are easy to confuse until you say what each
    // one teaches brAIn: one says the problem is over, the other says it
    // was never a problem here.
    // Same box as Wrong, and for the same reason — but what it collects is
    // not a correction. Nothing here is being denied: "I fixed it" leaves
    // brAIn knowing a problem is over, and "replaced the CR2032, it's a
    // 3-monthly job on that sensor" leaves it knowing the house. So it goes
    // into memory beside the fact rather than as evidence against a report.
    const done = add(el("button", "btn small", "✓  I fixed it"));
    tip(done, "It was a real problem and it's sorted now. Say what you did, "
      + "if it's worth remembering.");
    done.addEventListener("click", () => openNoteForm(card, actions,
      (note, formBtns) => findAction(
        f, "done",
        note ? "Fixed — that's gone into memory" : "Fixed — written into memory",
        btns.concat(formBtns), note),
      {
        hint: "What did you do? Optional — it goes into memory with the fix, "
          + "so brAIn knows how this house works next time.",
        placeholder: "Replaced the CR2032 — it's a 3-monthly job on that one.",
        send: "Done",
      }));

    // Not a decision, so not next to the ones that are. Dismissing is
    // permanent and teaches the analyst never to raise it again; this just
    // stops it asking until the date you pick.
    const later = add(el("button", "btn small ghost", "⏰  Remind me later"));
    tip(later, "Take it off the list for a while — it comes back, unchanged");
    later.addEventListener("click", (ev) => openSnoozePop(ev.currentTarget, f, btns));

    // Off the list now, and free to come back. Not a judgement about the
    // problem — it clears the row without teaching the analyst anything, so
    // the next run may well raise it again. That is the difference from
    // Wrong, and it is the whole reason both exist.
    const dismiss = add(el("button", "btn small ghost", "⌫  Dismiss"));
    tip(dismiss, "Clear it for now. brAIn may raise it again.");
    dismiss.addEventListener("click", () => findAction(
      f, "forget", "Cleared", btns));

    // This was "Ignore", which described what happened to the row and not
    // what the person meant. Most of the time they do not mean "hide this",
    // they mean "you have misread my house" — the sensor is not stuck, it
    // is a door contact on a cupboard nobody opens — and the old button had
    // nowhere to say so, so brAIn learned one wording was unwanted and
    // nothing about why. It is the same ending; it now asks for the reason,
    // and the reason is the half that stops the next four reports like it.
    const wrong = add(el("button", "btn small ghost", "✕  Wrong"));
    tip(wrong, "brAIn has this wrong, or it's normal here — say why, and it "
      + "learns from that rather than just dropping the card.");
    wrong.addEventListener("click", () => openNoteForm(card, actions,
      (note, formBtns) => findAction(
        f, "wrong",
        note ? "Noted — brAIn will take that into account"
             : "Noted — brAIn won't raise it again",
        btns.concat(formBtns), note),
      {
        hint: "What's brAIn got wrong? Optional — it goes into memory and "
          + "into what the next analysis knows about your house.",
        placeholder: "That sensor always reads on — it's not stuck.",
        send: "Send",
      }));
  }
  if (findings_isSnoozed(f)) {
    const back = el("div", "findsnoozed");
    back.appendChild(el("span", null, `⏰ Back ${timeUntil(f.snoozed_until)}`));
    const now = el("button", "btn small ghost", "Bring it back now");
    now.addEventListener("click", () => snoozeFinding(f, "now", [now]));
    back.appendChild(now);
    card.appendChild(back);
  }
  card.appendChild(actions);
  return card;
}

// A guess waiting to be confirmed, on the same list and in the same shape as
// a finding — but never wearing a severity, because nothing is wrong: brAIn
// thinks something is true and wants to be told. Yes files it as a fact; No
// asks why, for the same reason Wrong does, and for a guess the reason is
// worth even more — a rejected claim with no explanation retires one
// sentence, and "no, that's the beer fridge, it cycles all night" retires
// every guess built on the same misreading.
async function hypoAction(h, verb, done, btns, note) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(`api/hypothesis/${h.ts}/${verb}`, {
      method: "POST",
      ...(note ? { body: JSON.stringify({ note }) } : {}) });
    takeFindings(data);
    renderFindings();
    toast(done, data.undo);
  } catch (e) {
    toast(e.message);
    btns.forEach((b) => { b.disabled = false; });
  }
}

function makeHypothesis(h) {
  const card = el("article", "finding hypo");
  const line = el("div", "findmeta");
  line.appendChild(el("span", "findsev", "Is this right?"));
  line.appendChild(el("span", "findstate", "brAIn wants confirming"));
  if (h.topic) line.appendChild(el("span", "findsrc", h.topic));
  card.appendChild(line);
  card.appendChild(el("h3", "findtitle", h.text));

  const actions = el("div", "findactions");
  const btns = [];
  const yes = el("button", "btn small primary", "✓  Yes");
  tip(yes, "Right — brAIn remembers it as a fact about your house");
  const no = el("button", "btn small ghost", "✕  No");
  tip(no, "Wrong — say why, and brAIn learns from that rather than just "
    + "dropping the guess.");
  btns.push(yes, no);
  actions.appendChild(yes);
  actions.appendChild(no);
  card.appendChild(actions);

  yes.addEventListener("click", () => hypoAction(
    h, "confirm", "Filed — it lands in memory at the next consolidation", btns));
  no.addEventListener("click", () => openNoteForm(card, actions,
    (note, formBtns) => hypoAction(
      h, "reject",
      note ? "Noted — brAIn will take that into account" : "Noted as a dead end",
      btns.concat(formBtns), note),
    {
      hint: "What's it got wrong? Optional — it goes into memory and into "
        + "what the next analysis knows about your house.",
      placeholder: "That's the beer fridge — it's meant to cycle all night.",
      send: "Send",
    }));
  return card;
}

function findCount(f) {
  return state.findings.filter(f.match).length
    + (f.id === "live" ? state.hypotheses.length : 0);
}

function renderFindings() {
  const chips = $("#findFilters");
  chips.textContent = "";
  const counts = {};
  FIND_FILTERS.forEach((f) => { counts[f.id] = findCount(f); });
  // "Needs you" is always offered because it is where the work is. "Later"
  // appears only once something is actually waiting in it, so a home with
  // nothing wrong is handed one chip rather than a row of empty ones.
  FIND_FILTERS.forEach((f) => {
    if (f.id !== "live" && !counts[f.id]) return;
    const chip = el("button", "fchip" + (state.findFilter === f.id ? " active" : ""),
      counts[f.id] ? `${f.label} · ${counts[f.id]}` : f.label);
    chip.addEventListener("click", () => { state.findFilter = f.id; renderFindings(); });
    chips.appendChild(chip);
  });

  const list = $("#findList");
  list.textContent = "";
  const active = FIND_FILTERS.find((f) => f.id === state.findFilter) || FIND_FILTERS[0];
  const shown = state.findings.filter(active.match);
  // Guesses go at the top of the live list. They are two taps against a
  // finding's read-and-decide, and burying the cheap decisions under the
  // expensive ones is how a queue capped at three sat unanswered for a
  // fortnight and expired.
  const claims = state.findFilter === "live" ? state.hypotheses : [];
  if (!shown.length && !claims.length) {
    list.appendChild(el("div", "findempty", state.findFilter === "live"
      ? "Nothing waiting on you. Problems brAIn finds, and guesses it wants "
        + "confirmed, both land here as insight runs and study sessions turn "
        + "them up."
      : "Nothing here yet."));
    return;
  }
  claims.forEach((h) => list.appendChild(makeHypothesis(h)));
  shown.forEach((f) => list.appendChild(makeFinding(f)));
}

// ------------------------------------------------------- knowledge modal
// The viewer for everything the analyst has learned: open questions (answer
// or dismiss), learned facts (add/remove), answered Q&A, and the shared
// memory.md the brAIn maintains.

// Where a queued fact came from, in words rather than in the source tag the
// writer stamped on it. An unknown source falls through as itself: a new
// writer showing its own tag is odd, and showing nothing is a lie.
function kSourceLabel(src) {
  return {
    insights: "discovered", homeowner: "your answer", confirmed: "you confirmed",
    correction: "your correction", feedback: "feedback", user: "added by you",
    panel: "added by you", assist: "voice", terminal: "terminal",
    "terminal-forget": "removal, from the terminal",
    study: "study session", automation: "automation",
  }[src] || src;
}

// One fact still waiting for the document — a line of the inbox itself, not
// a reconstruction of it, so what is listed here is exactly what the count
// beside the button counts and exactly what the next pass will read.
//
// ✕ drops the line. It does NOT ask the consolidator to strike the text
// from memory.md, which is what the old button did: a queued fact has by
// definition never been filed, so there was nothing there to remove, and
// the request went off to delete a line that in most cases did not exist.
function makeQueuedRow(f) {
  const row = el("div", "fbitem");
  const txt = el("div", "txt");
  txt.appendChild(el("div", null, f.text));
  const when = new Date(f.ts * 1000);
  txt.appendChild(el("div", "when",
    kSourceLabel(f.source) +
    (isNaN(when.getTime()) ? "" :
      " · " + when.toLocaleDateString([], { month: "short", day: "numeric" }))));
  row.appendChild(txt);
  const del = el("button", "btn icon", "✕");
  tip(del, "Drop it from the queue — it never reaches memory");
  del.addEventListener("click", async () => {
    del.disabled = true;
    try {
      const res = await api(`api/memory/inbox/${f.id}`, { method: "DELETE" });
      takeQueue(res.inbox, res.inbox_pending);
      toast("Dropped — it won't be filed");
    } catch (e) {
      toast(e.message);
      del.disabled = false;
    }
  });
  row.appendChild(del);
  return row;
}

// The list and its count, drawn from the one payload that carries both.
function takeQueue(inbox, pending) {
  const items = inbox || [];
  const factsEl = $("#kFacts");
  factsEl.textContent = "";
  if (!items.length) {
    factsEl.appendChild(el("div", "kempty",
      "Nothing waiting — it's all in the memory document."));
  }
  // Newest first: what you just taught it is what you came to check on.
  items.slice().reverse().forEach((f) => factsEl.appendChild(makeQueuedRow(f)));
  // The list is capped and the count is not, so on a very long queue say
  // what is not on screen rather than letting the two numbers disagree
  // again in a quieter way.
  const hidden = Math.max(0, (Number(pending) || 0) - items.length);
  if (hidden) {
    factsEl.appendChild(el("div", "kmore",
      `…and ${hidden} more waiting. They all get filed together.`));
  }
  renderPending(pending, memState.lastState);
}

async function renderKnowledge() {
  let data;
  try {
    data = await api("api/knowledge");
  } catch (e) {
    toast("Could not load knowledge: " + e.message);
    return;
  }

  // Guesses waiting to be confirmed used to head this column. They are on
  // the Findings tab now — a guess to confirm and a problem to settle are
  // both "a decision only you can make", and two lists of those meant two
  // badges, neither of which ever read as done. What is left here is one
  // queue and one document, which is what this tab is for.

  // What is actually in the inbox, which is what the count counts. This
  // list used to be built from the facts ledger instead, keeping anything
  // the last consolidation predated — a different population entirely. The
  // ledger holds what the ANALYST discovered; the inbox holds that plus
  // corrections, confirmed guesses, facts you taught it here, voice, study
  // sessions and whatever another add-on dropped in /share. So the label
  // said nine things waiting over four cards, and both were right about
  // different questions.
  //
  // Filed facts are still listed nowhere: they are the document on the
  // right, which is the whole point of filing them.
  memState.lastState = data.memory_state;
  takeQueue(data.inbox, data.inbox_pending);

  // "Answered questions" is gone with the model it belonged to: a
  // confirmed guess becomes a plain memory line and its record is
  // settled, so there is no Q/A pair left to show.

  renderMemory(data);
}

// The consolidate button says how much is waiting, so pressing it is an
// informed choice rather than a hopeful one — and it stays "Filing…" for
// as long as a pass is actually in flight, whoever started it. Reading
// that off a local flag meant the button came back to life the instant the
// request returned, inviting a second press onto a pass still running.
function renderPending(n, state) {
  const label = $("#kPending");
  const btn = $("#kConsolidate");
  if (!label || !btn) return;
  const count = Number(n) || 0;
  const busy = memState.consolidating || !!(state && state.merging);
  label.textContent = count
    ? `${count} thing${count === 1 ? "" : "s"} waiting`
    : "nothing waiting";
  label.classList.remove("hidden");
  btn.disabled = busy || !count;
  btn.textContent = busy ? "Filing…" : "⇪ File into memory now";
}

// ---- home memory file: formatted view, raw-markdown edit, Claude merge ----

const memState = { editing: false, dirty: false, text: "", pollTimer: null,
                   consolidating: false, lastReported: 0, watching: false,
                   pollFails: 0,
                   // The last consolidation state seen, so dropping one row
                   // from the queue can redraw the button without a second
                   // round trip for something that has not changed.
                   lastState: null };

// How often to ask whether a pass has landed. It was 2.5s against the full
// knowledge payload; the endpoint is now a flag, so this is cheap — but a
// consolidation takes minutes, not seconds, and nothing is gained by
// asking twice a second.
const MEM_POLL_MS = 4000;

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
  // Escape first, strip comments second. Stripping `<!-- -->` out of raw
  // markup is a sanitiser shape — one pass over nested or truncated
  // comments leaves `<!--` behind — and it never needed to be one: the
  // escape below is what makes this safe, and running it first means the
  // comment strip is only ever tidying already-inert text.
  md = String(md || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  md = md.replace(/&lt;!--[\s\S]*?--&gt;/g, "");
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

// Everything on this tab that depends only on the consolidator's state, so
// the poll can keep it live without re-fetching the document behind it.
// " (2m 10s)" for a pass that has been running `secs`, or "" when we don't
// know — an unknown elapsed is silence, never a confident "(0s)". The server
// does the subtraction, so a phone with a wrong clock still reads right.
function elapsedLabel(secs) {
  const s = Math.max(0, Math.floor(Number(secs) || 0));
  if (!s) return "";
  if (s < 60) return ` (${s}s)`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? ` (${m}m ${rem}s)` : ` (${m}m)`;
}

function renderMemoryProgress(st) {
  const merging = !!st.merging;
  const running = !!st.running;
  $("#kMemMerging").classList.toggle("hidden", !merging);
  $("#kMemMergingSpin").classList.toggle("hidden", !running);
  // A pass that is running says so, and says whose it is. The daemon's own
  // passes used to be invisible here, so the queue emptied with nothing on
  // screen accounting for it.
  // How long it has been going, not how long it "takes". A pass is one Claude
  // call that rewrites the whole document, so its length depends on the
  // document — "a few minutes" answered a question nobody was asking, while
  // the one they were ("is this still working, or is it stuck?") needs a
  // number that moves.
  const since = elapsedLabel(st.running_for);
  $("#kMemMergingText").textContent = running
    ? (st.by === "you"
        ? `Filing these into the memory document now…${since}`
        : `brAIn is filing memory now — this runs daily, and early when the queue builds up.${since}`)
    : "✨ Queued — it lands at the next consolidation…";

  // A queue that has been waiting far longer than the daily pass is not a
  // busy consolidator, it is one that is not running — and that failed
  // silently for weeks once, with every screen saying everything was fine.
  // Whatever the cause, this is the symptom, so this is what gets said.
  // A pass that failed says what it hit, here, rather than only in a toast
  // that has already gone: this is the screen you come back to.
  const stale = Number(st.stale_hours) || 0;
  const staleBox = $("#kMemStale");
  const trouble = !running && (st.error || stale);
  staleBox.classList.toggle("hidden", !trouble);
  if (st.error) {
    staleBox.textContent = `⚠ The last attempt to file memory did not finish: `
      + `${st.error}`;
  } else if (stale) {
    const when = stale >= 48 ? `${Math.round(stale / 24)} days`
                             : `${Math.round(stale)} hours`;
    staleBox.textContent = `⚠ Nothing has been filed into memory for ${when}, `
      + `and facts are waiting. Press “File into memory now” — if that doesn't `
      + `clear it, the add-on log shows what the consolidator is hitting.`;
  }
}

function renderMemory(data) {
  const st = data.memory_state || {};
  renderMemoryProgress(st);
  if (st.merging) pollMemoryMerge();
  if (memState.editing) return; // never clobber an edit in progress
  memState.text = data.shared_memory || "";
  const has = !!memState.text.trim();
  $("#kMemView").innerHTML = has ? mdToHtml(memState.text) : "";
  $("#kMemView").classList.toggle("hidden", !has);
  $("#kMemEmpty").classList.toggle("hidden", has);
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

// While a pass is running, poll until it lands and say how it went.
//
// The poll asks for the flag, not the library: /api/memory/state is a
// couple of hundred bytes, where the knowledge payload it used to fetch
// every 2.5s is ~19 KB of facts and the whole memory document. The
// document is only re-read when the pass has actually finished, which is
// the one moment it can have changed.
function pollMemoryMerge() {
  clearTimeout(memState.pollTimer);
  memState.pollTimer = setTimeout(async () => {
    if (currentView !== "memory") return;
    let data;
    try {
      data = await api("api/memory/state");
      memState.pollFails = 0;
    } catch (e) {
      // Transient — a suspended webview aborts in-flight requests, and
      // giving up on the first one leaves the tab frozen on "Filing…".
      // Bounded, because a panel that is genuinely gone should stop being
      // asked every four seconds forever.
      memState.pollFails = (memState.pollFails || 0) + 1;
      if (memState.pollFails <= 10) pollMemoryMerge();
      return;
    }
    const st = data.memory_state || {};
    if (st.merging) {
      // Only a pass this panel started has an outcome we can report: the
      // daemon's own never touch memory_state, so announcing one would
      // announce whatever the last button press did, again.
      if (st.by === "you") memState.watching = true;
      renderMemoryProgress(st);
      pollMemoryMerge();
      return;
    }
    // Landed. Re-read everything once, and report the outcome exactly
    // once — reportMemoryPass keys off done_at, so a pass is never
    // announced twice however many pollers saw it finish.
    reportMemoryPass(st);
    renderKnowledge();
  }, MEM_POLL_MS);
}

// One pass, one message. The error lives on in memory_state so the tab can
// keep showing it, which is exactly why it must not be re-toasted on every
// render — a failing consolidator used to raise a toast per poll.
function reportMemoryPass(st) {
  const stamp = Number(st.done_at) || 0;
  if (!memState.watching) return;
  memState.watching = false;
  if (!stamp || stamp === memState.lastReported) return;
  memState.lastReported = stamp;
  if (st.error) toast("Could not file it: " + st.error);
  else if (memState.editing) return;
  else if (st.filed) toast(`Filed ${st.filed} thing(s) into memory`);
  else toast("Nothing was waiting — memory is up to date");
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
  // Started, not awaited: the pass rewrites the whole document with a
  // Claude call behind it and takes minutes. Holding the button's request
  // open for that is what made pressing it look like nothing happening —
  // the request timed out long before the pass did, and the toast said the
  // filing had failed while it was still running.
  memState.consolidating = true;
  $("#kConsolidate").disabled = true;
  $("#kConsolidate").textContent = "Filing…";
  $("#kMemMerging").classList.remove("hidden");
  try {
    const res = await api("api/memory/consolidate", { method: "POST" });
    toast(res.started
      ? "Filing into memory — this takes a few minutes."
      : "A pass is already running — this will land in the same one.");
    memState.watching = true;
    pollMemoryMerge();
  } catch (e) {
    toast("Could not start it: " + e.message);
    $("#kMemMerging").classList.add("hidden");
  } finally {
    memState.consolidating = false;
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

// The Memory tab used to carry a badge counting pending guesses, and it was
// dropped with them: what is left on that tab is a queue that drains itself
// on a timer and a document. Neither is waiting on anybody, and a badge that
// counts work nobody has to do is a badge people learn to ignore — including
// on the tab next to it, which counts work they do.

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
// A fresh install has no cards. brAIn studies the home first, then
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
      || "There isn't enough here yet for brAIn to suggest anything useful.";
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
  // The terminal takes the viewport, so the page behind it stops scrolling
  // — two scrollers stacked is why a swipe sometimes moved the wrong one.
  document.body.classList.toggle("term-open", name === "terminal");
  document.querySelectorAll(".viewtab").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view" + name[0].toUpperCase() + name.slice(1)));

  if (name === "findings") {
    // render what we have, then again once the fetch lands — but only if
    // it actually changed anything
    renderFindings();
    refreshFindings().then(renderFindings);
  }
  if (name === "terminal") {
    if (chatState.session === "classic") {
      const frame = $("#termFrame");
      // Lazy: don't start a shell session for someone who never opens the tab.
      if (frame.getAttribute("src") === "about:blank") frame.src = "terminal/";
    } else {
      chatConnect();
      restoreChatFinding();
    }
  } else {
    // Leaving the tab: whatever the keyboard was doing over there, the bar
    // belongs to whichever tab is in front now. The chat stream goes too —
    // an open SSE for a tab nobody is looking at holds a connection and a
    // subscriber for nothing.
    termChrome.keyboard = false;
    chatDisconnect();
  }
  applyTermChrome();
  if (name === "memory") renderKnowledge();
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

// The terminal is sized as "the viewport minus the bar", and the phone bar
// is two rows that become three if a trouble chip joins the usage pill. So
// the height is measured rather than assumed: --bar-h is the CSS fallback
// for each layout, and this keeps it exact at whatever the bar actually is.
function syncBarHeight() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  const root = document.documentElement;
  // Measure against the STYLESHEET's value for this layout, never against
  // the one we last wrote. `.topbar`'s height *is* --bar-h, so an inline
  // override on <html> feeds the previous measurement back into the thing
  // being measured. Leaving the immersive terminal is where that bites:
  // immersive writes 0px, and on the way back out the bar is visible again
  // but pinned to height 0 by our own inline value, so it renders clipped —
  // and the next measurement latches the clipped height for good.
  root.style.removeProperty("--bar-h");
  const h = Math.round(bar.getBoundingClientRect().height);
  // Hidden means zero, and getBoundingClientRect on a display:none element
  // already says so — but that is the one case we must NOT write, because
  // `body.term-immersive { --bar-h: 0px }` is already saying it in CSS and
  // an inline 0 would outlive the class that justified it.
  if (h > 0) root.style.setProperty("--bar-h", h + "px");
}

(function trackBarHeight() {
  const bar = document.querySelector(".topbar");
  if (!bar || typeof ResizeObserver === "undefined") return;
  new ResizeObserver(syncBarHeight).observe(bar);
})();

// ---------------------------------------------------------- chat terminal
//
// The same Claude Code the classic tab runs, rendered as DOM instead of
// drawn into a character grid. Everything that knows the CLI's wire format
// lives in chat_session.py; what arrives here is a short list of event
// types — user, text, text_delta, thinking, tool, tool_result, notice,
// result, state, cleared — and this file only has to draw them.

const chatState = {
  es: null,          // EventSource, or null when the stream is down
  live: null,        // the message node partial text is streaming into
  liveText: "",
  tools: new Map(),  // tool_use id -> its <details>, so a result can find it
  working: null,     // the status line shown for as long as the turn runs
  statusVerb: "",    // what the status line says it is doing
  statusTimer: null, // the 1s tick that keeps its elapsed seconds honest
  busyStart: 0,      // when this turn started, for those seconds
  pendingSend: 0,    // a send is in flight but the busy state hasn't landed
  liveThink: null,   // the think box thinking deltas are streaming into
  thinkBoxes: [],    // streamed think boxes awaiting their final block
  permCard: null,    // the approval card currently on screen, if any
  ready: false,      // has a snapshot been drawn
  session: "chat",   // "chat" | "classic"
  runState: "idle",
  sessionId: null,   // the CLI's id for this conversation — what `--resume` takes
  info: {},          // model, cwd, version, api_key_source, from the CLI itself
  context: {},       // {tokens, window} — how full the conversation is
  models: [],        // the same choices ⚙ offers, for the chat's own picker
  chatModel: "",     // the stored chat override; "" = follow the global model
  defaultModel: "",  // the global model the chat defers to when unset
  convs: [],         // past conversations, for the wide-screen sidebar
  commands: [],      // its slash commands, as it advertises them
  cli: [],           // the brain/ha dispatchers, parsed from their own help
  cmdIndex: 0,       // highlighted row in the command palette
  finding: null,     // the finding this conversation is about, if any
};

function chatLog() { return $("#chatLog"); }

// Sticky-bottom, but only if you were already there — nothing is ruder than
// yanking someone back down while they are reading what scrolled past.
function chatAtBottom() {
  const log = chatLog();
  return log.scrollHeight - log.scrollTop - log.clientHeight < 90;
}

function chatScroll(force) {
  const log = chatLog();
  if (force || chatAtBottom()) log.scrollTop = log.scrollHeight;
}

function chatAppend(node, stick) {
  const wasBottom = stick !== false && chatAtBottom();
  chatLog().appendChild(node);
  $("#chatEmpty").classList.toggle("hidden", chatLog().childElementCount > 0);
  if (wasBottom) chatScroll(true);
  return node;
}

// Thinking is generated BEFORE the text it precedes, but it only reaches us
// in the assistant message that closes the turn — by which time the text has
// already been streaming into a live node for several seconds. Appending it
// would put the reasoning after the conclusion it led to, so it goes in
// where it belongs instead. The transcript a reload repaints has it in the
// right order already; this only fixes the live view.
function chatInsertBeforeLive(node) {
  const wasBottom = chatAtBottom();
  if (chatState.live) chatLog().insertBefore(node, chatState.live);
  else chatLog().appendChild(node);
  $("#chatEmpty").classList.toggle("hidden", chatLog().childElementCount > 0);
  if (wasBottom) chatScroll(true);
  return node;
}

// The panel already has an escaping markdown renderer for the guide, and
// this is exactly the content that needs one: it escapes first, so a model
// that echoes a <script> back at you renders it as text.
function chatMarkdown(text) {
  const node = el("div", "msg bot");
  node.innerHTML = renderMarkdown(String(text || ""));
  return node;
}

function chatToolNode(ev) {
  const box = el("details", "toolcall running");
  const sum = el("summary");
  sum.appendChild(el("span", "tdot"));
  sum.appendChild(el("span", "tname", ev.name || "tool"));
  sum.appendChild(el("span", "tsum", ev.summary || ""));
  box.appendChild(sum);
  const body = el("div", "tbody");
  if (ev.input && ev.input !== "{}") {
    body.appendChild(el("div", "tlabel", "Input"));
    const pre = el("pre");
    pre.appendChild(el("code", null, ev.input));
    body.appendChild(pre);
  }
  box.appendChild(body);
  return box;
}

function chatToolResult(ev) {
  const box = chatState.tools.get(ev.id);
  if (!box) return;
  box.classList.remove("running");
  box.classList.add(ev.denied ? "denied" : ev.ok ? "ok" : "bad");
  const body = box.querySelector(".tbody");
  body.appendChild(el("div", "tlabel",
                      ev.denied ? "Not permitted" : ev.ok ? "Result" : "Error"));
  const pre = el("pre");
  pre.appendChild(el("code", null, ev.text || "(no output)"));
  body.appendChild(pre);
  // A refusal needs the sentence as well as the label. Without it the box
  // says a thing failed and leaves you to work out that nothing was broken,
  // that retrying cannot help, and that the fix is somewhere else entirely.
  if (ev.denied) {
    body.appendChild(el("div", "tnote",
      "This call was declined — by a permission rule, or on the approval "
      + "card — so it never ran. Nothing is broken, and asking again "
      + "without allowing it will not change the answer."));
  }
  // A failure is the one case worth opening unasked — it is the reason the
  // next thing Claude says will look strange.
  if (!ev.ok) box.open = true;
}

// The status line: a verb, the elapsed seconds, and the pulse that says
// something is alive — the same bottom line the native CLI keeps for a whole
// turn. Its predecessor was three dots that vanished on the first token, so
// a tool-heavy minute looked hung with the only motion inside a collapsed
// chip. It lives under the newest content for as long as the turn runs, and
// each rendered event retells it what Claude is doing right now.
function chatStatus(verb) {
  // Replayed transcripts render the same events a live turn does; a status
  // line for last Tuesday's tool call is a spinner that never stops.
  if (chatState.runState !== "busy" && !chatState.pendingSend) return;
  chatState.statusVerb = verb || chatState.statusVerb || "Working…";
  let node = chatState.working;
  if (!node) {
    node = el("div", "chatwork");
    node.append(el("i"), el("i"), el("i"));
    node.appendChild(el("span", "chatverb"));
    node.appendChild(el("span", "chatelapsed"));
    chatState.working = chatAppend(node);
    if (!chatState.busyStart) chatState.busyStart = Date.now();
    if (!chatState.statusTimer) {
      chatState.statusTimer = setInterval(chatStatusTick, 1000);
    }
  } else if (node !== chatLog().lastElementChild) {
    const stick = chatAtBottom();
    chatLog().appendChild(node);
    if (stick) chatScroll(true);
  }
  node.querySelector(".chatverb").textContent = chatState.statusVerb;
  chatStatusTick();
}

function chatStatusTick() {
  const node = chatState.working;
  if (!node) return;
  const s = Math.round((Date.now() - chatState.busyStart) / 1000);
  node.querySelector(".chatelapsed").textContent = s >= 1 ? `${s}s` : "";
}

function chatStatusClear() {
  if (chatState.statusTimer) {
    clearInterval(chatState.statusTimer);
    chatState.statusTimer = null;
  }
  if (chatState.working) {
    chatState.working.remove();
    chatState.working = null;
  }
  chatState.busyStart = 0;
  chatState.statusVerb = "";
}

// Thinking streams into an open box as it happens — the native CLI shows
// its reasoning live, and a chat that sits on dots for a minute and then
// deals the reasoning out after its conclusion reads as a different, and
// worse, model. The streamed box is kept in a queue: the assistant event
// that closes the message repeats the block whole, and replaces the
// streamed copy in place rather than adding a twin above it.
function chatThinkDelta(text) {
  let entry = chatState.liveThink;
  if (!entry) {
    const box = el("details", "think live");
    box.open = true;
    box.appendChild(el("summary", null, "Thinking…"));
    const body = el("div", "tbody");
    box.appendChild(body);
    entry = { box, body, text: "" };
    chatState.liveThink = entry;
    chatState.thinkBoxes.push(entry);
    chatAppend(box);
  }
  entry.text += text;
  entry.body.innerHTML = renderMarkdown(entry.text);
  chatScroll();
}

// The thinking ended — text or a tool call started. Fold the box up the way
// the CLI folds its own, but keep it queued for the final block.
function chatCloseLiveThink() {
  const entry = chatState.liveThink;
  if (!entry) return;
  entry.box.classList.remove("live");
  entry.box.open = false;
  entry.box.querySelector("summary").textContent = "Thinking";
  chatState.liveThink = null;
}

// The approval card: the chat's version of the TUI's permission prompt.
// The CLI is blocked on this answer, so it renders where the eye already
// is — under the tool chip that provoked it — with the two words that are
// actually the decision. AskUserQuestion gets its own shape: the CLI is
// not asking "may I", it is asking the questions themselves, and a generic
// Allow would send them back an empty answer sheet.
function chatPermission(ev) {
  chatPermissionGone();
  const card = (ev.kind === "question" && (ev.questions || []).length)
    ? chatQuestionCard(ev)
    : chatApprovalCard(ev);
  chatState.permCard = chatAppend(card);
}

function chatStatusForPermission(ev) {
  return ev.kind === "question"
    ? "Waiting for your answer" : "Waiting for your approval";
}

// One POST, shared by both cards. On failure the buttons come back —
// except a 404, which means the question is no longer waiting (timed out,
// withdrawn, or answered from another tab) and re-arming would invite a
// second answer to a question nobody is asking.
function chatPermissionPost(body, buttons, rearm) {
  buttons.forEach((b) => { b.disabled = true; });
  api("api/chat/permission", { method: "POST", body: JSON.stringify(body) })
    .catch((e) => {
      toast(e.message);
      if (rearm) rearm(); else buttons.forEach((b) => { b.disabled = false; });
    });
}

function chatApprovalCard(ev) {
  const card = el("div", "permcard");
  card.dataset.id = ev.id || "";
  card.appendChild(el("div", "permhead",
    `Claude wants to use ${ev.tool || "a tool"}`));
  if (ev.summary) card.appendChild(el("div", "permsum", ev.summary));
  if (ev.input && ev.input !== "{}") {
    const pre = el("pre");
    pre.appendChild(el("code", null, ev.input));
    card.appendChild(pre);
  }
  const row = el("div", "permrow");
  const allow = el("button", "btn small primary", "Allow once");
  const deny = el("button", "btn small", "Don't allow");
  allow.addEventListener("click", () =>
    chatPermissionPost({ id: ev.id, allow: true }, [allow, deny]));
  deny.addEventListener("click", () =>
    chatPermissionPost({ id: ev.id, allow: false }, [allow, deny]));
  row.append(allow, deny);
  card.appendChild(row);
  return card;
}

// The question card: the questions, their options, and a free-text "other"
// per question — the same three affordances the CLI's own picker draws on
// a TTY. Answers go back keyed by question text (multi-select joined with
// commas), which is the wire shape the CLI's permission component uses.
function chatQuestionCard(ev) {
  const card = el("div", "permcard qcard");
  card.dataset.id = ev.id || "";
  card.dataset.kind = "question";
  const qs = ev.questions || [];
  card.appendChild(el("div", "permhead",
    qs.length > 1 ? "Claude has some questions" : "Claude has a question"));

  const picks = qs.map(() => ({ chosen: new Set(), other: "" }));
  const row = el("div", "permrow");
  const send = el("button", "btn small primary", "Send answers");
  const skip = el("button", "btn small", "Don't answer");
  send.disabled = true;
  const arm = () => {
    // Every question answered — by a pick or typed text — or the send
    // stays down: a half-filled sheet is the empty sheet with extra steps.
    send.disabled = !picks.every((p) => p.chosen.size || p.other.trim());
    skip.disabled = false;
  };

  qs.forEach((q, i) => {
    const box = el("div", "qbox");
    const head = el("div", "qhead");
    if (q.header) head.appendChild(el("span", "qchip", q.header));
    head.appendChild(el("span", "qtext", q.question));
    box.appendChild(head);
    const opts = el("div", "qopts");
    const other = el("input", "qother");
    (q.options || []).forEach((o) => {
      const b = el("button", "qopt");
      b.type = "button";
      b.appendChild(el("span", "qlabel", o.label));
      if (o.description) b.appendChild(el("span", "qdesc", o.description));
      b.addEventListener("click", () => {
        const p = picks[i];
        if (q.multi) {
          if (p.chosen.has(o.label)) p.chosen.delete(o.label);
          else p.chosen.add(o.label);
          b.classList.toggle("on", p.chosen.has(o.label));
        } else {
          // Single-select: one option, and it displaces any typed answer —
          // two answers to a pick-one question is not a thing to send.
          p.chosen.clear();
          p.chosen.add(o.label);
          p.other = "";
          other.value = "";
          [...opts.children].forEach((c) =>
            c.classList.toggle("on", c === b));
        }
        arm();
      });
      opts.appendChild(b);
    });
    box.appendChild(opts);
    other.type = "text";
    other.placeholder = q.multi
      ? "Anything else? (optional)" : "Or type your own answer…";
    other.addEventListener("input", () => {
      const p = picks[i];
      p.other = other.value;
      if (!q.multi && other.value.trim()) {
        p.chosen.clear();
        [...opts.children].forEach((c) => c.classList.remove("on"));
      }
      arm();
    });
    box.appendChild(other);
    card.appendChild(box);
  });

  send.addEventListener("click", () => {
    const answers = {};
    qs.forEach((q, i) => {
      const p = picks[i];
      const parts = [...p.chosen];
      const typed = p.other.trim();
      if (typed) parts.push(typed);
      answers[q.question] = parts.join(", ");
    });
    chatPermissionPost({ id: ev.id, allow: true, answers }, [send, skip], arm);
  });
  skip.addEventListener("click", () =>
    chatPermissionPost({ id: ev.id, allow: false }, [send, skip], arm));
  row.append(send, skip);
  card.appendChild(row);
  return card;
}

function chatPermissionDone(ev) {
  const card = chatState.permCard;
  if (!card || (ev.id && card.dataset.id !== ev.id)) return;
  const row = card.querySelector(".permrow");
  if (row) {
    const q = card.dataset.kind === "question";
    row.replaceWith(el("div", "permnote",
      ev.answered ? (ev.allow ? (q ? "Answered" : "Allowed")
                              : (q ? "Skipped" : "Not allowed"))
                  : "Withdrawn"));
  }
  chatState.permCard = null;
}

function chatPermissionGone() {
  if (chatState.permCard) {
    chatState.permCard.remove();
    chatState.permCard = null;
  }
}

// Partial text streams into a live node; the assistant event that follows
// carries the same block whole, and replaces it. That is why deltas are not
// kept in the transcript — otherwise every answer would appear twice on the
// next reload.
function chatDelta(text) {
  if (!chatState.live) {
    chatState.liveText = "";
    chatState.live = chatAppend(el("div", "msg bot"));
  }
  chatState.liveText += text;
  chatState.live.innerHTML = renderMarkdown(chatState.liveText);
  chatScroll();
}

function chatSealLive(finalText) {
  if (chatState.live) {
    chatState.live.innerHTML = renderMarkdown(String(finalText || chatState.liveText));
    chatState.live = null;
    chatState.liveText = "";
    chatScroll();
    return true;
  }
  return false;
}

function chatRender(ev) {
  switch (ev.type) {
    case "user": {
      const row = el("div", "msg user");
      row.appendChild(el("div", "bubble", ev.text));
      chatAppend(row, true);
      chatScroll(true);
      chatStatus();
      break;
    }
    case "text_delta":
      chatCloseLiveThink();
      chatDelta(ev.text);
      chatStatus("Writing…");
      break;
    case "thinking_delta":
      chatThinkDelta(ev.text);
      chatStatus("Thinking…");
      break;
    case "text":
      if (!chatSealLive(ev.text)) chatAppend(chatMarkdown(ev.text));
      chatStatus();
      break;
    case "thinking": {
      chatCloseLiveThink();
      // The whole block, at message close. If it streamed in live it is
      // already on screen — replace that copy in place rather than dealing
      // a twin; the retro-insert is for replays and models that stream no
      // thinking deltas.
      const streamed = chatState.thinkBoxes.shift();
      if (streamed) {
        streamed.body.innerHTML = renderMarkdown(ev.text || "");
        break;
      }
      const box = el("details", "think");
      box.appendChild(el("summary", null, "Thinking"));
      const body = el("div", "tbody");
      body.innerHTML = renderMarkdown(ev.text || "");
      box.appendChild(body);
      chatInsertBeforeLive(box);
      break;
    }
    case "tool": {
      chatCloseLiveThink();
      chatSealLive();
      const node = chatAppend(chatToolNode(ev));
      if (ev.id) chatState.tools.set(ev.id, node);
      chatStatus(`Running ${ev.name || "a tool"}…`);
      break;
    }
    case "tool_result":
      chatToolResult(ev);
      chatStatus("Working…");
      break;
    case "permission":
      chatPermission(ev);
      chatStatus(chatStatusForPermission(ev));
      break;
    case "permission_done":
      chatPermissionDone(ev);
      chatStatus("Working…");
      break;
    case "notice":
      chatSealLive();
      chatAppend(el("div", "chatnotice" + (ev.level === "error" ? " error" : ""),
                    ev.text || ""));
      chatStatus();
      break;
    case "result": {
      chatSealLive();
      const bits = [];
      if (ev.duration_ms) bits.push((ev.duration_ms / 1000).toFixed(1) + "s");
      if (ev.turns) bits.push(ev.turns + (ev.turns === 1 ? " turn" : " turns"));
      // The dollar figure only when dollars are actually involved. On a
      // subscription the CLI still reports `total_cost_usd` — the list price
      // of those tokens had you bought them — and printing that after every
      // message is a number that looks like a charge and isn't one. The CLI
      // tells us which it is: apiKeySource is "none" on a subscription.
      if (ev.cost_usd && chatBilledPerToken()) {
        bits.push("$" + Number(ev.cost_usd).toFixed(3));
      }
      if (bits.length) chatAppend(el("div", "chatstat", bits.join(" · ")));
      break;
    }
    case "info":
      chatState.info = ev;
      chatMeta();
      break;
    case "context":
      chatState.context = { tokens: ev.tokens, window: ev.window };
      chatMeta();
      break;
    case "commands":
      chatState.commands = ev.commands || [];
      break;
    case "cleared":
      chatReset();
      break;
    case "state":
      chatSetState(ev.state, ev.error);
      break;
    default:
      break;
  }
}

// Which model is answering, and how full the conversation is.
//
// The token figure is the CLI's own report of what it sent on the last model
// call, which IS the conversation so far — so it is a measurement, not an
// estimate. One call, not the whole turn: a turn is many calls and adding
// them up measures work done, not conversation size. The percentage only
// appears for a model whose window we have a published figure for; for
// anything else the count stands on its own, because a percentage of a
// guessed denominator is worse than no percentage.
function chatMeta() {
  const box = $("#chatMeta");
  if (!box) return;
  const model = (chatState.info && chatState.info.model) || "";
  const ctx = chatState.context || {};
  box.classList.toggle("hidden", !model && !ctx.tokens);
  $("#chatModel").textContent = model ? prettyModel(model) : "";
  const pill = $("#chatCtx");
  if (!ctx.tokens) { pill.classList.add("hidden"); return; }
  pill.classList.remove("hidden");
  const k = ctx.tokens >= 1000
    ? (ctx.tokens / 1000).toFixed(ctx.tokens >= 10000 ? 0 : 1) + "k"
    : String(ctx.tokens);
  if (ctx.window > 0) {
    const pct = Math.round((ctx.tokens / ctx.window) * 100);
    pill.textContent = `${k} / ${Math.round(ctx.window / 1000)}k context · ${pct}%`;
    // Only two states, and the warning one is the only one worth a colour:
    // a context that is nearly full is about to start dropping the start of
    // the conversation, which is the thing you would want warning about.
    pill.classList.toggle("warn", pct >= 80);
  } else {
    pill.textContent = `${k} tokens of context`;
    pill.classList.remove("warn");
  }
}

// `claude-opus-5-20260101` is not a thing anyone says out loud.
function prettyModel(id) {
  const m = /(opus|sonnet|haiku)[-\s]?([0-9](?:\.[0-9])?)?/i.exec(id || "");
  if (!m) return id;
  const name = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
  return m[2] ? `Claude ${name} ${m[2]}` : `Claude ${name}`;
}

// "none" means no API key is paying — a Pro/Max subscription, where the
// tokens are already bought and a per-message price is meaningless.
function chatBilledPerToken() {
  const src = chatState.info && chatState.info.api_key_source;
  return !!src && src !== "none";
}

function chatReset() {
  chatStatusClear();
  chatLog().innerHTML = "";
  chatState.live = null;
  chatState.liveText = "";
  chatState.liveThink = null;
  chatState.thinkBoxes = [];
  chatState.permCard = null;
  chatState.tools.clear();
  $("#chatEmpty").classList.remove("hidden");
}

function chatSetState(runState, error) {
  chatState.runState = runState;
  const busy = runState === "busy";
  $("#chatSend").classList.toggle("hidden", busy);
  $("#chatStop").classList.toggle("hidden", !busy);
  if (busy) {
    chatState.pendingSend = 0;
    chatStatus();
  } else {
    chatSealLive();
    chatCloseLiveThink();
    // Streamed boxes whose final block never came (an interrupted turn)
    // stay on screen as they are; only the matching queue is dropped.
    chatState.thinkBoxes = [];
    chatState.pendingSend = 0;
    chatStatusClear();
  }
  const box = $("#chatErr");
  box.textContent = error || "";
  box.classList.toggle("hidden", !error);
}

// One stream, reopened on drop. EventSource retries by itself, but only
// while the page believes the connection died — an ingress that closes it
// cleanly looks like a finished response, so the close handler re-arms.
function chatConnect() {
  if (chatState.es) return;
  let es;
  try {
    es = new EventSource("api/chat/stream");
  } catch (e) {
    return;
  }
  chatState.es = es;
  es.onmessage = (msg) => {
    let ev;
    try { ev = JSON.parse(msg.data); } catch (e) { return; }
    if (ev.type === "snapshot") {
      chatReset();
      // Session facts arrive with the snapshot rather than being waited for:
      // the CLI announces them once, at startup, and a viewer who connected
      // afterwards would otherwise never see them.
      chatState.sessionId = ev.session_id || null;
      chatState.info = ev.info || {};
      chatState.context = ev.context || {};
      chatState.commands = ev.commands || [];
      chatState.models = ev.models || chatState.models;
      chatState.chatModel = ev.chat_model || "";
      chatState.defaultModel = ev.default_model || "";
      chatMeta();
      chatState.cli = ev.cli || chatState.cli;
      (ev.events || []).forEach(chatRender);
      chatSetState(ev.state, ev.error);
      if (ev.permission) {
        // A reload mid-question: the turn is still blocked on this card,
        // so it has to come back with the transcript it interrupted.
        chatPermission(ev.permission);
        chatStatus(chatStatusForPermission(ev.permission));
      }
      chatState.ready = true;
      chatScroll(true);
      renderChatRail();
      refreshChatRail();
      return;
    }
    if (ev.session_id) chatState.sessionId = ev.session_id;
    chatRender(ev);
  };
  es.onerror = () => {
    es.close();
    if (chatState.es === es) {
      chatState.es = null;
      // Only while the tab is still the one on screen: a closed stream for a
      // tab nobody is looking at is a reconnect loop nobody asked for.
      if (currentView === "terminal" && chatState.session === "chat") {
        setTimeout(chatConnect, 2000);
      }
    }
  };
}

function chatDisconnect() {
  if (!chatState.es) return;
  chatState.es.close();
  chatState.es = null;
}

async function chatSend(text) {
  text = (text || "").trim();
  if (!text || chatState.runState === "busy") return;
  const input = $("#chatInput");
  input.value = "";
  $("#chatCmds").classList.add("hidden");
  chatGrow();
  // The busy state hasn't landed yet, but the person has let go of the
  // message — the status line starts here so the send is visibly in flight.
  chatState.pendingSend = Date.now();
  chatStatus("Sending…");
  try {
    await api("api/chat/send", { method: "POST", body: JSON.stringify({ text }) });
  } catch (e) {
    chatState.pendingSend = 0;
    chatStatusClear();
    // Put it back rather than losing what they typed.
    input.value = text;
    chatGrow();
    toast(e.message);
  }
}

// Grow with the text, up to the CSS cap. Reset first so deleting a line
// shrinks it again.
function chatGrow() {
  const input = $("#chatInput");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px";
}

$("#chatForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  chatSend($("#chatInput").value);
});

$("#chatInput").addEventListener("input", () => {
  chatGrow();
  chatState.cmdIndex = 0;
  chatRenderCmds();
});

$("#chatInput").addEventListener("keydown", (ev) => {
  const matches = chatCmdMatches();
  const paletteOpen = matches && matches.length
    && !$("#chatCmds").classList.contains("hidden");

  // While the palette is up it owns the arrows, Tab and Escape — and Enter,
  // which picks rather than sends. Sending "/mod" because you were halfway
  // through choosing /model is the failure this prevents.
  if (paletteOpen) {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const step = ev.key === "ArrowDown" ? 1 : -1;
      chatState.cmdIndex =
        (chatState.cmdIndex + step + matches.length) % matches.length;
      chatRenderCmds();
      return;
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      $("#chatCmds").classList.add("hidden");
      return;
    }
    if (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing)) {
      ev.preventDefault();
      // Clamped HERE, not only where the list is drawn. This list is
      // recomputed on every keystroke and shrinks as you type, so an index
      // that was in range when the palette was painted can be past the end
      // by the time you press Enter — and reading past the end threw, which
      // killed this handler outright. The palette then neither picked nor
      // sent, apparently at random, until the index came back into range.
      const pick = matches[Math.min(chatState.cmdIndex, matches.length - 1)];
      if (pick) chatPickCmd((pick.prefix || "") + pick.name);
      return;
    }
  }

  // Enter sends on a keyboard and breaks a line on a touchscreen. On a phone
  // the return key is where your thumb is and a two-line message is normal;
  // on a desktop, reaching for a button to send is the wrong ergonomics.
  if (ev.key !== "Enter" || ev.shiftKey || ev.isComposing) return;
  if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return;
  ev.preventDefault();
  chatSend($("#chatInput").value);
});

// The panel cannot see an iOS keyboard open inside the ingress iframe, but
// it knows when its own composer took focus — which on a touchscreen is the
// same moment. Same fold as the classic terminal's, same way back.
$("#chatInput").addEventListener("focus", () => {
  if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) {
    termChrome.keyboard = true;
    applyTermChrome();
  }
});
$("#chatInput").addEventListener("blur", () => releaseChatKeyboard());

// Blur is not reliable enough to be the only way out of this state. On iOS,
// dismissing the keyboard with its own control leaves the textarea focused,
// so blur never fires — and the flag stayed true for the rest of the
// session, holding the bar folded. Anything that means "the composer is not
// being typed into any more" clears it, and it is re-checked rather than
// trusted.
// No "is the composer still focused?" guard, deliberately: on iOS it still
// is, which is the whole problem. Unfolding the bar a moment early costs a
// row of screen; getting this wrong the other way costs every control on
// the page, permanently.
function releaseChatKeyboard() {
  if (!termChrome.keyboard) return;
  termChrome.keyboard = false;
  applyTermChrome();
}

// Every route back to the page: switching app, rotating, coming back to the
// tab, or touching anything that is not the composer.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") releaseChatKeyboard();
});
window.addEventListener("pageshow", () => releaseChatKeyboard());
document.addEventListener("touchend", (ev) => {
  if (!ev.target.closest(".chatbar")) releaseChatKeyboard();
}, true);
if (window.visualViewport) {
  // The keyboard closing gives the viewport its height back. On the
  // platforms where this fires it is the most direct signal there is.
  window.visualViewport.addEventListener("resize", () => {
    if (window.visualViewport.height >= window.innerHeight - 40) {
      releaseChatKeyboard();
    }
  });
}

$("#chatStop").addEventListener("click", async () => {
  try { await api("api/chat/stop", { method: "POST" }); }
  catch (e) { toast(e.message); }
});

$("#chatNew").addEventListener("click", async () => {
  // Not "this is cleared and Claude forgets": Claude Code keeps the
  // conversation on disk and it stays in the list, so the honest cost is
  // that the next thing you say starts a separate one.
  if (chatLog().childElementCount && !window.confirm(
    "Start a new chat? This one is kept — you can reopen it from the "
    + "conversations list.")) return;
  try { await api("api/chat/new", { method: "POST" }); }
  catch (e) { toast(e.message); }
  refreshChatRail();
});

document.querySelectorAll(".chatseeds .seed").forEach((btn) =>
  btn.addEventListener("click", () => chatSend(btn.textContent)));

// --------------------------------------------------- the finding on trial
//
// A discussion is about one finding, and the decisions about that finding
// have to be reachable from inside it. Otherwise agreeing to a fix at the
// end of a conversation means going back to the other tab and finding the
// card again, which is where a decision goes to die.
//
// Remembered across reloads, because a conversation you were having is not
// over because the page reloaded.

function setChatFinding(f) {
  chatState.finding = f || null;
  const bar = $("#chatFinding");
  // The strip is one element reused for every finding, unlike the cards,
  // which are rebuilt. A reason box left open on the one you just settled
  // would greet the next one with its buttons hidden.
  const openNote = bar.querySelector(".findnote");
  if (openNote) openNote.remove();
  const acts = bar.querySelector(".cfacts");
  if (acts) acts.classList.remove("hidden");
  bar.classList.toggle("hidden", !f);
  if (!f) { prefSet("brain.chatFinding", ""); return; }
  $("#chatFindingText").textContent = f.text;
  $("#chatFindingFix").classList.toggle("hidden", !f.fixable);
  prefSet("brain.chatFinding", String(f.ts));
}

async function restoreChatFinding() {
  const ts = prefGet("brain.chatFinding");
  if (!ts) return;
  const f = (state.findings || []).find((x) => String(x.ts) === ts);
  if (f) { setChatFinding(f); return; }
  // The list may not be loaded yet on a cold start — fetch it once.
  try {
    takeFindings(await api("api/findings"));
    const found = state.findings.find((x) => String(x.ts) === ts);
    if (found) setChatFinding(found);
    else prefSet("brain.chatFinding", "");
  } catch (e) { /* the strip simply stays down */ }
}

async function chatFindingAction(verb, done, note, extraBtns) {
  const f = chatState.finding;
  if (!f) return;
  const btns = [...$("#chatFinding").querySelectorAll("button")]
    .concat(extraBtns || []);
  await findAction(f, verb, done, btns, note);
  // Settled: the discussion can carry on, but it is no longer a decision
  // waiting on you, so the bar goes.
  setChatFinding(null);
}

$("#chatFindingClose").addEventListener("click", () => setChatFinding(null));
$("#chatFindingFix").addEventListener("click", () =>
  chatFindingAction("fix", "On it — brAIn is making the change"));
$("#chatFindingDone").addEventListener("click", () => openNoteForm(
  $("#chatFinding"), $("#chatFinding").querySelector(".cfacts"),
  (note, formBtns) => chatFindingAction(
    "done",
    note ? "Fixed — that's gone into memory" : "Fixed — written into memory",
    note, formBtns),
  {
    hint: "What did you do? Optional — it goes into memory with the fix, so "
      + "brAIn knows how this house works next time.",
    placeholder: "Replaced the CR2032 — it's a 3-monthly job on that one.",
    send: "Done",
  }));
// The same ending as the card's, and it asks the same question — the strip
// exists so you don't have to go back to the tab to decide, and an ending
// that quietly dropped the reason would make going back the better option.
// Explaining it to Claude in the chat is not the same thing: that reaches
// this conversation, and the note reaches every future one.
$("#chatFindingWrong").addEventListener("click", () => openNoteForm(
  $("#chatFinding"), $("#chatFinding").querySelector(".cfacts"),
  (note, formBtns) => chatFindingAction(
    "wrong",
    note ? "Noted — brAIn will take that into account"
         : "Noted — brAIn won't raise it again",
    note, formBtns),
  {
    hint: "What's brAIn got wrong? Optional — it goes into memory and into "
      + "what the next analysis knows about your house.",
    placeholder: "That sensor always reads on — it's not stuck.",
    send: "Send",
  }));
$("#chatFindingLater").addEventListener("click", (ev) => {
  const f = chatState.finding;
  if (!f) return;
  openSnoozePop(ev.currentTarget, f, [ev.currentTarget]);
});

// ------------------------------------------------------- conversations
//
// The list is Claude Code's, not ours: it files every conversation under
// the working directory, and both faces of this tab stand in /config. So a
// session started in the classic terminal is here beside one started in the
// chat, and picking either replays it into this pane and carries on.
//
// It also files everything the ADD-ON runs there, which is not the same
// thing at all: voice, the automation listener and the memory consolidator
// drive the same Claude Code, so a house using them showed a rail of
// identical machine prompts. Each row now says whose it is and the filter
// chooses; "Yours" is the default because that is what a list of your
// conversations means. Nothing is hidden — a machine's run is one press
// away, and worth having when you want to know what voice actually did.

// Which face the list is showing. Persisted: a filter you have to re-pick
// on every reload is a filter you stop using.
const convFilter = { source: prefGet("brain.convSource") || "you",
                     options: [] };

function setConvFilter(source) {
  convFilter.source = source;
  prefSet("brain.convSource", source);
  refreshChatRail();
  if ($("#convModal").classList.contains("open")) openConversations();
}

// One row's "who ran this", as a chip. Yours get none: a label on every
// row for the ordinary case is just noise with extra steps.
function sourceChip(row) {
  if (!row.source || row.source === "you") return null;
  const meta = convFilter.options.find((o) => o.id === row.source);
  return el("span", "csrc", meta ? meta.label : row.source);
}

// The chips above the list. Only faces that have actually run here are
// offered — the server counts them — so a house with no voice assistant is
// never given an empty Voice filter to wonder about.
function renderConvFilter(host, onPick) {
  host.textContent = "";
  if (convFilter.options.length <= 1) return;   // only "Yours": no choice to make
  convFilter.options.forEach((o) => {
    const b = el("button", "crfilter" + (o.id === convFilter.source ? " on" : ""),
                 o.count ? `${o.label} ${o.count}` : o.label);
    b.type = "button";
    if (o.blurb) tip(b, o.blurb);
    b.setAttribute("aria-pressed", o.id === convFilter.source ? "true" : "false");
    b.addEventListener("click", () => { setConvFilter(o.id); onPick(); });
    host.appendChild(b);
  });
}

function convQuery() {
  return `api/chat/conversations?source=${encodeURIComponent(convFilter.source)}`;
}

// Selection mode: several rows in one press instead of one ✕ each. One
// mode across both surfaces — the rail and the ⋯ dialog show the same
// list, and a selection that vanished when you opened the other view would
// read as a different feature in each place.
const convSel = { on: false, ids: new Set() };

function convSelToggle(on) {
  convSel.on = on === undefined ? !convSel.on : !!on;
  if (!convSel.on) convSel.ids.clear();
  renderChatRail();
  renderConvModal();
}

function convSelFlip(id) {
  if (convSel.ids.has(id)) convSel.ids.delete(id);
  else convSel.ids.add(id);
}

// A row can be selected unless it is the open conversation — the server
// refuses to delete that one, and offering a checkbox that always answers
// "skipped" teaches nothing.
function convSelectable(rows) {
  return rows.filter((c) =>
    !(chatState.sessionId && c.id === chatState.sessionId));
}

// The bar above a list in selection mode: the count, Select all, and the
// one destructive verb. Rebuilt with the list it belongs to; every press
// repaints from what is already fetched, never a request.
function convSelBar(rows) {
  const bar = el("div", "cselbar");
  const selectable = convSelectable(rows);
  const n = convSel.ids.size;
  bar.appendChild(el("span", "cselcount",
    n ? `${n} selected` : "Select conversations"));
  const all = el("button", "btn small",
    selectable.length && selectable.every((c) => convSel.ids.has(c.id))
      ? "Select none" : "Select all");
  all.type = "button";
  all.addEventListener("click", () => {
    const everything = selectable.length
      && selectable.every((c) => convSel.ids.has(c.id));
    if (everything) convSel.ids.clear();
    else selectable.forEach((c) => convSel.ids.add(c.id));
    renderChatRail();
    renderConvModal();
  });
  const del = el("button", "btn small primary", "Delete");
  del.type = "button";
  del.disabled = !n;
  del.addEventListener("click", () => deleteSelectedConvs(del));
  const cancel = el("button", "btn small", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", () => convSelToggle(false));
  bar.append(all, del, cancel);
  return bar;
}

async function deleteSelectedConvs(btn) {
  const ids = [...convSel.ids];
  if (!ids.length) return;
  btn.disabled = true;
  try {
    const out = await api("api/chat/conversations/delete",
      { method: "POST", body: JSON.stringify({ ids }) });
    const n = (out.deleted || []).length;
    const skipped = (out.skipped || []).length;
    convSelToggle(false);
    toast(`${n} conversation${n === 1 ? "" : "s"} deleted`
      + (skipped ? ` — ${skipped} skipped` : ""), out.undo);
    refreshConversationLists();
  } catch (e) {
    btn.disabled = false;
    toast(e.message);
  }
}

// What the ⋯ dialog is currently showing, kept so selection presses can
// repaint without refetching the list out from under the checkboxes.
let convModalRows = [];

async function openConversations() {
  openBox("#convModal");
  const list = $("#convList");
  list.innerHTML = "";
  $("#convEmpty").classList.add("hidden");
  let data;
  try {
    data = await api(convQuery());
  } catch (e) {
    toast(e.message);
    return;
  }
  convFilter.options = data.sources || [];
  renderConvFilter($("#convFilter"), () => {});
  $("#convCwd").textContent = (chatState.info && chatState.info.cwd) || "/config";
  convModalRows = data.conversations || [];
  renderConvModal();
}

function renderConvModal() {
  if (!$("#convModal").classList.contains("open")) return;
  const list = $("#convList");
  list.innerHTML = "";
  const rows = convModalRows;
  $("#convEmpty").classList.toggle("hidden", rows.length > 0);
  if (convSel.on && rows.length) list.appendChild(convSelBar(rows));
  rows.forEach((c) => {
    const here = !!chatState.sessionId && c.id === chatState.sessionId;
    const row = el("div", "crrow");
    const btn = el("button", "convitem");
    if (convSel.on && !here) {
      btn.classList.add("hascheck");
      btn.classList.toggle("sel", convSel.ids.has(c.id));
      btn.appendChild(el("span",
        "crcheck" + (convSel.ids.has(c.id) ? " on" : "")));
    }
    btn.appendChild(el("span", "ctitle", c.title));
    const chip = sourceChip(c);
    if (chip) btn.appendChild(chip);
    btn.appendChild(el("span", "cwhen", c.age));
    if (convSel.on) {
      if (here) btn.classList.add("inert");
      else btn.addEventListener("click", () => {
        convSelFlip(c.id);
        renderConvModal();
      });
    } else {
      btn.addEventListener("click", () => resumeConversation(c));
    }
    row.appendChild(btn);
    if (!convSel.on) row.appendChild(deleteConvButton(c));
    list.appendChild(row);
  });
}

// The ✕ beside a conversation. A row is itself a button, so this cannot be
// its child — the wrapper the caller puts both in is what keeps them
// siblings. Deleting hands back an undo token and the toast grows the
// button, same as every other press that takes something away.
function deleteConvButton(c) {
  const del = el("button", "crdel", "✕");
  del.type = "button";
  tip(del, "Delete this conversation");
  del.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    del.disabled = true;
    try {
      const out = await api(
        `api/chat/conversation/${encodeURIComponent(c.id)}/delete`,
        { method: "POST" });
      toast("Conversation deleted", out.undo);
      refreshConversationLists();
    } catch (e) {
      del.disabled = false;
      toast(e.message);
    }
  });
  return del;
}

// Both surfaces onto the one list: the rail if it is on screen, and the ⋯
// dialog if it is open.
function refreshConversationLists() {
  refreshChatRail();
  if ($("#convModal").classList.contains("open")) openConversations();
}

// The wide-screen rail. Same list and same resume as the ⋯ dialog — one
// source of conversations, two ways to reach it — so a conversation started
// in the classic terminal shows up here too.
//
// Only fetched when the rail is actually on screen: below the breakpoint it
// is `display: none`, and a list nobody can see is not worth a request on
// every tab switch.
function railVisible() {
  const rail = $("#chatRail");
  return !!rail && getComputedStyle(rail).display !== "none";
}

async function refreshChatRail() {
  if (!railVisible()) return;
  try {
    const data = await api(convQuery());
    chatState.convs = data.conversations || [];
    convFilter.options = data.sources || [];
  } catch (e) {
    return;  // transient: the rail keeps whatever it last showed
  }
  renderChatRail();
}

function renderChatRail() {
  const list = $("#chatRailList");
  if (!list) return;
  renderConvFilter($("#chatRailFilter"), () => {});
  list.textContent = "";
  if (!chatState.convs.length) {
    list.appendChild(el("div", "crempty", convFilter.source === "you"
      ? "No past chats yet." : "Nothing here yet."));
    return;
  }
  if (convSel.on) list.appendChild(convSelBar(chatState.convs));
  chatState.convs.forEach((c) => {
    // The one you are in is marked rather than hidden: a list that silently
    // omits the current item makes you wonder where it went.
    const here = !!chatState.sessionId && c.id === chatState.sessionId;
    const row = el("div", "crrow");
    const btn = el("button", "critem" + (here ? " active" : ""));
    if (convSel.on && !here) {
      btn.classList.add("hascheck");
      btn.classList.toggle("sel", convSel.ids.has(c.id));
      btn.appendChild(el("span",
        "crcheck" + (convSel.ids.has(c.id) ? " on" : "")));
    }
    btn.appendChild(el("span", "ctitle", c.title));
    const foot = el("div", "crfoot");
    const chip = sourceChip(c);
    if (chip) foot.appendChild(chip);
    foot.appendChild(el("span", "cwhen", c.age));
    btn.appendChild(foot);
    if (here) btn.setAttribute("aria-current", "true");
    if (convSel.on) {
      if (here) btn.classList.add("inert");
      else btn.addEventListener("click", () => {
        convSelFlip(c.id);
        renderChatRail();
      });
    } else if (!here) {
      btn.addEventListener("click", () => resumeConversation(c));
    }
    row.appendChild(btn);
    // Not on the open one — the server refuses it anyway ("start a new
    // chat first"), and a control that only ever answers no is clutter.
    if (!here && !convSel.on) row.appendChild(deleteConvButton(c));
    list.appendChild(row);
  });
}

$("#chatRailNew").addEventListener("click", () => $("#chatNew").click());
$("#chatRailSel").addEventListener("click", () => convSelToggle());
$("#convSel").addEventListener("click", () => convSelToggle());

async function resumeConversation(conv) {
  closeBox("#convModal");
  toast("Opening that conversation…");
  try {
    const out = await api("api/chat/resume", {
      method: "POST", body: JSON.stringify({ session_id: conv.id }) });
    // The server verified the spawn: `resumed: false` means Claude Code no
    // longer holds this conversation (its store prunes old sessions) and a
    // fresh session opened instead. The transcript is on screen either
    // way; what differs is whether Claude remembers it, and that is worth
    // saying out loud rather than letting the next answer reveal it.
    if (out && out.resumed === false) {
      toast("Claude Code no longer has that conversation — the transcript "
        + "is shown, but the next message starts fresh without its context.");
    }
  } catch (e) {
    toast(e.message);
  }
}

$("#chatOpen").addEventListener("click", openConversations);
$("#convClose").addEventListener("click", () => closeBox("#convModal"));
$("#convModal").addEventListener("click", (ev) => {
  if (ev.target === $("#convModal")) closeBox("#convModal");
});

// ------------------------------------------------------- session details
//
// Claude Code files every conversation under
// ~/.claude/projects/<escaped working directory>/ and `claude --resume`
// only lists the ones belonging to the directory you are standing in. Both
// faces of this tab run in /config so they share that directory — but the
// id is still the thing you need to type, and nothing was showing it.

$("#chatInfo").addEventListener("click", async () => {
  if (chipPopFor === $("#chatInfo")) { closeChipPop(); return; }
  closeChipPop();
  // Read it fresh: the id changes with every "New chat", and a popover is
  // exactly where a stale one would go unnoticed.
  try {
    const snap = await api("api/chat/state");
    chatState.sessionId = snap.session_id || null;
    chatState.info = snap.info || {};
  } catch (e) { /* fall back to what the stream last told us */ }

  const info = chatState.info || {};
  const rows = [];
  const row = (name, value) =>
    `<div class="prow"><span class="pname">${esc(name)}</span>`
    + `<span class="pval mono">${esc(value)}</span></div>`;
  if (info.model) rows.push(row("Model", info.model));
  if (info.cwd) rows.push(row("Project", info.cwd));
  rows.push(row("Billing", chatBilledPerToken()
    ? "API key — charged per token" : "Your Claude subscription"));
  if (chatState.sessionId) {
    // No "continue in the terminal" button here: switching the tab's face
    // already carries the conversation across, and a second control for the
    // same act is how you end up unsure which one actually moves you. The
    // id and the command are still here, for a shell that isn't this one.
    rows.push(`<p class="pnote">This conversation lives in Claude Code, not in
      brAIn — which is why switching to the classic terminal carries it with
      you. Elsewhere (an SSH session, another machine), resume it by id.</p>
      <p class="pnote">One thing the chat can't do: appear in the Claude app
      on your phone. Remote Control only supports interactive sessions, and
      the chat drives Claude Code headlessly — switch to the classic
      terminal and this same conversation can register there.</p>`
      + `<div class="psid mono">${esc(chatState.sessionId)}</div>`
      + `<div class="prow pacts">`
      + `<button class="btn small" id="chatCopyResume">Copy the command</button>`
      + `</div>`);
  } else {
    rows.push(`<p class="pnote">No conversation yet — send a message and this
      is where its id will be.</p>`);
  }
  setChipPop($("#chatInfo"), "Chat session", rows.join(""));

  const copyBtn = $("#chatCopyResume");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      copyText(`claude --resume ${chatState.sessionId}`).then((ok) =>
        toast(ok ? "Copied — paste it in the terminal"
                 : `Run: claude --resume ${chatState.sessionId}`));
    });
  }
});

// ------------------------------------------------------- the model picker
//
// Which model answers the chat, chosen from the chat. The choice is the
// chat's own (`chat_model`, a panel setting): making it the global option
// would silently change what every insight run costs. Two ways in — the
// model name in the meta line, and ⋯ → Model before a first message has
// put a meta line on screen. Applying it restarts the CLI with --resume,
// so the conversation carries across the way it already does when an old
// CLI has to be stopped.

function openModelPick(anchor) {
  if (chipPopFor === anchor) { closeChipPop(); return; }
  closeChipPop();
  const current = chatState.chatModel || "";
  const def = chatState.defaultModel
    ? prettyModel(chatState.defaultModel) : "the CLI's own choice";
  // The list's own empty-id row ("CLI default") is dropped: in the chat,
  // "" means "follow the model in ⚙ Settings", and the Default row above
  // it is that — two rows with one value would both light up as current.
  const rows = [{ id: "", label: `Default — ${def}`,
                  hint: "follows the model in ⚙ Settings" }]
    .concat((chatState.models || []).filter((m) => m.id));
  const html = rows.map((m) =>
    `<button type="button" class="mpick${(m.id || "") === current ? " on" : ""}"`
    + ` data-model="${esc(m.id || "")}">${esc(m.label)}`
    + (m.hint ? `<span class="mhint">${esc(m.hint)}</span>` : "")
    + `</button>`).join("");
  setChipPop(anchor, "Chat model", html);
  document.querySelectorAll("#chipPopBody .mpick").forEach((btn) =>
    btn.addEventListener("click", () => pickChatModel(btn.dataset.model)));
}

async function pickChatModel(id) {
  closeChipPop();
  try {
    const out = await api("api/chat/model", {
      method: "POST", body: JSON.stringify({ model: id || null }) });
    chatState.chatModel = out.chat_model || "";
    // A restart re-announces the session (init → info), which is what
    // updates the name in the meta line; without one there is nothing
    // running yet and the next spawn simply takes the flag.
    toast(out.restarted
      ? "Model changed — the conversation carries on"
      : "Model set — it applies from the next message");
  } catch (e) {
    toast(e.message);
  }
}

$("#chatModel").addEventListener("click", () => openModelPick($("#chatModel")));
$("#chatModelPick").addEventListener("click", () =>
  openModelPick($("#chatModelPick")));

// Stopping our session first is the point, not a side effect: while the
// panel holds the conversation open, the terminal is being asked to resume
// something that is still in use.
async function chatHandoff() {
  let out;
  try {
    out = await api("api/chat/handoff", { method: "POST" });
  } catch (e) {
    toast(e.message);
    return;
  }
  closeChipPop();
  // The command is copied as a fallback, not as the instruction: the server
  // has already left the id where the terminal picks it up, and opened a
  // window on it if the terminal was up. Somebody who never pastes it still
  // lands in the conversation.
  const ok = await copyText(out.command);
  setTermMode("classic",
    out.opened ? "Carried over — the terminal is in this conversation"
      : ok ? "Carried over — paste the copied command in the terminal"
           : `Carried over — run: ${out.command}`);
  return out;
}

// Coming back the other way. We can't ask the tmux Claude what it is doing,
// but Claude Code writes every conversation as it goes, so the most recently
// written one IS what the terminal was last on — the server picks it up and
// resumes it here. That Claude is left running: it is somebody's shell.
async function chatAdopt() {
  try {
    return await api("api/chat/adopt", { method: "POST" });
  } catch (e) {
    // Never block the switch on it. The renderer changing is the thing that
    // was asked for; not finding a conversation to carry is a worse chat,
    // not a broken button.
    toast(e.message);
    return null;
  }
}

// One place that changes which face is in front, so the setting, the body
// class and the server can never end up saying three different things.
function setTermMode(mode, note) {
  applyTermMode(mode);
  if (state.status && state.status.settings) {
    state.status.settings.terminal_ui = mode;
  }
  saveSettings({ terminal_ui: mode }, note);
}

// The switch carries the conversation. Flipping the renderer and leaving
// the conversation behind is what made two faces feel like two rooms.
async function switchTermMode(next) {
  const btn = $("#termMode");
  if (btn) btn.disabled = true;
  try {
    if (next === "classic") {
      if (chatState.sessionId) { await chatHandoff(); return; }
      setTermMode("classic", "Classic terminal");
      return;
    }
    setTermMode("chat", "Chat terminal");
    const out = await chatAdopt();
    if (out && out.adopted) {
      toast(out.title ? `Picked up: ${out.title}` : "Picked up where you left off");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ------------------------------------------------------ command palette
//
// The list is the CLI's own, sent over the stream (`commands_changed`), so a
// command someone drops into /config/.claude/commands shows up here without
// brAIn knowing anything about it. A hardcoded list would be wrong the first
// time anybody customised their install.

// Two families, one palette. "/" is Claude Code's own; `brain` and `ha` are
// the add-on's CLIs, which are not slash commands and so were the half of
// what you can type here that nothing ever offered. Both lists come from
// the thing that owns them — the CLI announces its commands over the
// stream, the dispatchers are parsed from their own `help` — so neither can
// drift out of date with what this install actually has.
const CLI_PREFIX = /^(brain|ha|hass)(\s.*)?$/i;

function chatCmdMatches() {
  const value = $("#chatInput").value;

  if (/^\/[^\s]*$/.test(value)) {          // only while typing the name
    const term = value.slice(1).toLowerCase();
    return chatState.commands
      .filter((c) => c.name.toLowerCase().includes(term))
      .map((c) => ({ ...c, prefix: "/" }))
      .slice(0, 50);
  }

  // A CLI line, up to the point where arguments start: once you are typing
  // a value ("brain memory add \"the garage…"), suggesting commands is just
  // covering the screen.
  if (CLI_PREFIX.test(value) && !/["'\d]/.test(value)) {
    const term = value.trim().toLowerCase().replace(/\s+/g, " ");
    const matches = chatState.cli
      .filter((c) => c.name.toLowerCase().startsWith(term))
      .slice(0, 50);
    // An exact, complete match is not a suggestion — it is what you typed.
    if (matches.length === 1 && matches[0].name.toLowerCase() === term) return null;
    return matches.map((c) => ({ ...c, prefix: "" }));
  }

  return null;
}

function chatRenderCmds() {
  const box = $("#chatCmds");
  const matches = chatCmdMatches();
  if (!matches || !matches.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  chatState.cmdIndex = Math.min(chatState.cmdIndex, matches.length - 1);
  box.innerHTML = matches.map((c, i) =>
    `<button type="button" class="cmd${i === chatState.cmdIndex ? " on" : ""}"
       role="option" data-name="${esc((c.prefix || "") + c.name)}">`
    + `<span class="cname">${esc((c.prefix || "") + c.name)}</span>`
    + (c.hint ? `<span class="chint">${esc(c.hint)}</span>` : "")
    + (c.description ? `<span class="cdesc">${esc(c.description)}</span>` : "")
    + `</button>`).join("");
  box.classList.remove("hidden");
  const on = box.querySelector(".cmd.on");
  if (on) on.scrollIntoView({ block: "nearest" });
}

function chatPickCmd(name) {
  const input = $("#chatInput");
  // `name` already carries its prefix — "/" for a Claude Code command,
  // nothing for a shell one. A trailing space because most take arguments;
  // the ones that don't ignore it.
  input.value = name + " ";
  $("#chatCmds").classList.add("hidden");
  input.focus();
  chatGrow();
}

$("#chatCmds").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".cmd");
  if (btn) chatPickCmd(btn.dataset.name);
});

// ------------------------------------------------- immersive terminal

// Two independent reasons the bar folds away, and they must not clobber one
// another: `pinned` is the ⤢ press and survives a reload; `keyboard` is the
// software keyboard being up right now. Closing the keyboard restores the
// bar unless ⤢ is holding it down.
// The panel runs inside Home Assistant's ingress iframe, and a browser is
// allowed to refuse an iframe its storage (Safari does, under some privacy
// settings). Reading it must therefore never throw: an unremembered
// preference is a small loss, and a script that dies here takes every
// handler declared after it with it.
function prefGet(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function prefSet(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* not remembered */ }
}

const termChrome = {
  pinned: prefGet("brain.termFull") === "1",
  keyboard: false,
};

function applyTermChrome() {
  const onTerminal = currentView === "terminal";
  const pinned = onTerminal && termChrome.pinned;
  const kb = onTerminal && termChrome.keyboard;
  document.body.classList.toggle("term-immersive", pinned || kb);
  document.body.classList.toggle("term-kb", kb);
  const btn = $("#termExpand");
  if (btn) {
    btn.setAttribute("aria-pressed", pinned ? "true" : "false");
    const label = pinned ? "Show the brAIn bar" : "Full-screen terminal";
    btn.setAttribute("aria-label", label);
    btn.dataset.tip = label;
  }
  syncBarHeight();
}

$("#termExpand").addEventListener("click", () => {
  termChrome.pinned = !termChrome.pinned;
  prefSet("brain.termFull", termChrome.pinned ? "1" : "0");
  applyTermChrome();
});

// ----------------------------------------------------------- the ⋯ menu
//
// Five floating buttons over someone's output was five translucent squares
// on top of the text they came to read. ⤢ earns its own because it is also
// the way back from a folded bar; the rest are occasional, so they are a
// menu — one button, and no decision about which glyph means what.

function closeTermMenu() {
  $("#termMenuPop").classList.add("hidden");
  $("#termMenu").setAttribute("aria-expanded", "false");
}

$("#termMenu").addEventListener("click", () => {
  const pop = $("#termMenuPop");
  const open = pop.classList.toggle("hidden");
  $("#termMenu").setAttribute("aria-expanded", open ? "false" : "true");
  if (!open) closeChipPop();
});

// Every item closes it — a menu that stays open behind the thing it just
// opened is one more thing to dismiss.
document.querySelectorAll("#termMenuPop .tmitem").forEach((item) =>
  item.addEventListener("click", () => closeTermMenu()));

document.addEventListener("click", (ev) => {
  if ($("#termMenuPop").classList.contains("hidden")) return;
  if (ev.target.closest("#termMenuPop") || ev.target.closest("#termMenu")) return;
  closeTermMenu();
});

// ------------------------------------------------- which terminal you get
//
// Two faces on one Claude Code. The setting is server-side rather than
// per-browser because it is a property of this brAIn, not of the device
// that happened to open it — and because ⚙ Settings is where someone will
// go looking for it after switching by accident.

function applyTermMode(mode) {
  const classic = mode === "classic";
  chatState.session = classic ? "classic" : "chat";
  document.body.classList.toggle("term-classic", classic);
  const btn = $("#termMode");
  const label = classic ? "Chat" : "Classic terminal";
  btn.setAttribute("aria-label",
    classic ? "Switch to chat" : "Switch to the classic terminal");
  $("#termModeLabel").textContent = label;
  const onTab = currentView === "terminal";
  if (classic) {
    chatDisconnect();
    const frame = $("#termFrame");
    // Lazy in both directions: no shell for someone who never opens the tab,
    // and no stream for a chat nobody is looking at.
    if (onTab && frame.getAttribute("src") === "about:blank") frame.src = "terminal/";
  } else if (onTab) {
    chatConnect();
  }
  const sel = $("#setTerminalUi");
  if (sel) sel.value = classic ? "classic" : "chat";
}

function syncTermMode() {
  const s = state.status;
  const mode = (s && s.settings && s.settings.terminal_ui) || "chat";
  if (mode !== chatState.session) applyTermMode(mode);
}

$("#termMode").addEventListener("click", () => {
  switchTermMode(chatState.session === "classic" ? "chat" : "classic");
});

// The ttyd frame is the only thing in the stack that can tell whether the
// software keyboard is up: on iOS the keyboard doesn't resize an iframe's
// visual viewport, and the frame already does the awkward work of finding
// out (it has to, to keep its own toolbar above the keys). It reports the
// answer here rather than us guessing it a second time, worse.
window.addEventListener("message", (ev) => {
  const d = ev.data;
  if (!d || d.type !== "brain-keyboard") return;
  if (ev.source !== $("#termFrame").contentWindow) return;
  termChrome.keyboard = !!d.open;
  applyTermChrome();
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
  refreshFindings();
  // resume a guided sign-in if one is mid-flight (page reload)
  try {
    const st = await api("api/auth/setup/status");
    if (["starting", "awaiting_code", "working"].includes(st.phase)) pollSetup();
  } catch (e) { /* ignore */ }
})();
