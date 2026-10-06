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
  // Show the sign-in screen even though a credential exists. Without it the
  // screen was reachable only while `authenticated` was false, so the one
  // state that most needs it — a stored credential that has stopped working
  // — was the one state with no way in.
  showSignIn: false,
  insights: [],
  findings: [],
  // Guesses waiting to be confirmed. They come down the findings endpoint
  // because they are the same job as a finding — something only the person
  // who lives here can answer — and one list is what makes "nothing waiting"
  // a thing the tab can ever say.
  hypotheses: [],
  // What has been answered. The ledger is a dedup index the server reads and
  // NOT a second list of work — which is why it is offered behind a filter
  // that appears only once there is something in it, and why the only thing
  // you can do to a row is stop it suppressing the report. It is the one
  // route to `POST /api/findings/unsettle`, which had no caller at all.
  settled: [],
  // The feed. One object over the four stores, derived server-side — never
  // a fifth list held here, because a second copy of "is this still open"
  // is a second answer and the one time they disagree is the one time
  // somebody is looking.
  cases: [],
  // What the Resident did today, the state of its queue and of the event
  // subscription. It rides the same payload as the cases because it is read
  // in exactly one place, which is the line under them.
  caseMeta: {},
  findFilter: "live",
  // The to-do list: work you have accepted. A separate store from findings
  // on purpose — an item outlives the card that raised it, which is the
  // whole feature — so it is a separate fetch and a separate count.
  todo: [],
  todoDone: [],
  todoOpen: 0,
  todoFilter: "open",
  filter: "all",
  editingTags: null, // card id whose tag row is in edit mode
  pollTimer: null,
  setupTimer: null,
  frameSeq: 0,
  history: {},    // id -> [{ts, generated_at, title}] newest first (lazy)
  prevLatest: {}, // id -> full previous-run object (for "prev:" diffs)
  viewing: {},    // id -> {ts, data, prev} when a card is pinned to a past run
  // id -> {at, n, ok} — when live readings last ARRIVED for a card, how
  // many, and whether the last attempt got through. A live card has TWO
  // ages and the foot used to report one of them; see `liveAgeText`.
  liveSeen: {},
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
  // A poll behind a dialog nobody has open is a request per viewer per
  // interval for an answer nobody is reading — the same rule the
  // Diagnostics section itself follows.
  if (sel === "#setModal" && typeof stopDeepPoll === "function") {
    stopDeepPoll();
    stopRehearsePoll();
  }
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
// `action` is the other kind of button a toast can carry: a label and
// something to do, for a message that is not about undoing anything —
// "that chat needs your OK", whose whole point is being one press from the
// conversation asking. Same lifetime as Undo's, for the same reason.
function toast(msg, undo, action) {
  const t = $("#toast");
  t.textContent = "";
  t.appendChild(el("span", null, msg));
  // Only while the toast is up: the button is the offer, and the offer
  // expires with it. The token expires server-side too, so a stale one is
  // refused rather than acting on a decision made five minutes ago.
  t.classList.toggle("undoable", !!undo || !!action);
  if (action && !undo) {
    const btn = el("button", "toastundo", action.label);
    btn.addEventListener("click", () => {
      t.classList.remove("show");
      action.run();
    });
    t.appendChild(btn);
  }
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
        // An accepted proposal's undo answers with the whole proposals
        // payload, the row back on it — the same "re-render from what
        // came back" the accept itself does.
        if (data.proposals) {
          propState.data = data;
          renderProposals();
        }
        t.classList.remove("show");
        // `undone: false` means the row could not go back — the analyst
        // re-reported it while the toast was up, so the list already holds
        // a newer version and overwriting it would lose what happened
        // since. Say which, rather than claiming a success. A batch restore
        // reports its count, and a partial one says both numbers — "put
        // back" over a half-restored list would lie about the other half.
        toast(data.undone ? "Put back"
                          // Undoing an accept reverses three things —
                          // the file, the reload, the row — and says
                          // which one it could not. The automation may
                          // still be running, and "It's already back on
                          // the list" would be a lie about that.
                          : data.error ? data.error
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

// The other direction, for the scheduler's next_due (epoch seconds).
function timeUntil(epochS) {
  const mins = Math.round((epochS * 1000 - Date.now()) / 60000);
  if (mins < 2) return "due now";
  if (mins < 60) return `in ${mins} min`;
  if (mins < 48 * 60) return `in ${Math.round(mins / 60)} h`;
  return `in ${Math.round(mins / 1440)} d`;
}

// Height auto-sizing: a script appended to every srcdoc posts its content
// height; sandboxed frames can't be measured from outside. It measures the
// body's CHILDREN, not the body: a chart that styles `html,body{height:100%}`
// reports the frame's own height back, the frame never grows, and the
// chart below the fold sat behind a scrollbar inside the card.

// JSON is not script-safe on its own: `JSON.stringify` leaves `<` alone, so
// an id containing `</script>` would close the tag it is embedded in and the
// rest would be parsed as markup. Escaping `<` covers `</script`, `<script`
// and `<!--` in one go, and `<` is still the same string to the parser.
const jsonInScript = (v) => JSON.stringify(v).replace(/</g, "\\u003c");

const SIZE_SNIPPET = (id) => `<script>(function(){var last=0;function post(){var b=document.body;if(!b)return;var bottom=0,kids=b.children;for(var i=0;i<kids.length;i++){var r=kids[i].getBoundingClientRect();if(!r.width&&!r.height)continue;bottom=Math.max(bottom,Math.max(r.bottom,r.top+kids[i].scrollHeight)+(parseFloat(getComputedStyle(kids[i]).marginBottom)||0));}var cs=getComputedStyle(b);var h=bottom>0?bottom+window.scrollY+(parseFloat(cs.paddingBottom)||0):Math.max(b.offsetHeight,b.getBoundingClientRect().height);h=Math.ceil(h);if(h>0&&Math.abs(h-last)>2){last=h;parent.postMessage({type:"bruh-size",id:${jsonInScript(id)},h:h},"*");}}try{var ro=new ResizeObserver(post);ro.observe(document.body);window.addEventListener("load",function(){for(var i=0;i<document.body.children.length;i++)ro.observe(document.body.children[i]);});}catch(e){}window.addEventListener("load",post);setTimeout(post,400);setTimeout(post,1200);})();<\/script>`;

// The other direction, and the reason issue #300 asked for one: a card is
// one Claude run rendered to a document, written once — so a card about
// something happening NOW is frozen at the moment it was made. A card may
// declare `live` entities in its JSON; the panel fetches their current
// states while the card is on screen and posts them in here.
//
// The frame has no network of its own (the contract says so, and the
// sandbox enforces it), so this IS the channel. `window.brainLive(cb)`
// hands the callback whatever has arrived already and then every refresh
// after, which is what lets a visualization register at any point during
// its own load without racing the first message.
//
// It is deliberately a one-way push. A frame that could ASK for an
// entity would be model-authored script choosing what to read out of the
// house through the panel's credential; what it gets is what its own
// author declared, fixed when the card was written.
const LIVE_SNIPPET = (id) => `<script>(function(){var cbs=[],last=null;window.brainLive=function(fn){if(typeof fn!=="function")return;cbs.push(fn);if(last){try{fn(last);}catch(e){}}};window.addEventListener("message",function(ev){var d=ev.data;if(!d||d.type!=="bruh-live"||d.id!==${jsonInScript(id)}||!d.states)return;last=d.states;for(var i=0;i<cbs.length;i++){try{cbs[i](last);}catch(e){}}});})();<\/script>`;

// Which frames want live data, and the one timer that serves all of them.
// One timer rather than one per card: a dashboard with six live cards
// would otherwise be six independent polls drifting against each other,
// and the whole point of the interval is that it is gentle.
const liveFrames = new Map();   // frameId -> {insightId, entities}
let livePoll = null;
let livePollS = 15;

function watchLive(frameId, insight) {
  const ents = Array.isArray(insight.live) ? insight.live : [];
  if (!ents.length) return;
  liveFrames.set(frameId, { insightId: insight.id, entities: ents });
  if (!livePoll) livePoll = setTimeout(liveTick, 300);
}

// Frames are rebuilt on every render, so the map would grow without
// bound; a frame whose element has gone is dropped as it is noticed
// rather than tracked separately, which keeps the bookkeeping in one
// place and cannot leak a card the user has navigated away from.
async function liveTick() {
  livePoll = null;
  const wanted = new Map();
  liveFrames.forEach((v, frameId) => {
    const frame = document.querySelector(
      `iframe[data-frame="${CSS.escape(String(frameId))}"]`);
    // Gone from the DOM, or holding a different card now: a re-render
    // built a new frame and this id names nothing. Dropped, or the map
    // grows for the life of the session.
    if (!frame || !frame.isConnected) { liveFrames.delete(frameId); return; }
    // Rendered nowhere — a closed modal, a tab you are not on. SKIPPED
    // rather than dropped: nobody is looking, so it must not cost a
    // request, but `renderIfChanged` deliberately does not rebuild an
    // iframe it does not have to, so a dropped entry would never be
    // registered again and the card would come back permanently frozen.
    if (frame.offsetParent === null && !frame.getClientRects().length) return;
    if (!wanted.has(v.insightId)) wanted.set(v.insightId, []);
    wanted.get(v.insightId).push({ frameId, frame });
  });
  for (const [insightId, frames] of wanted) {
    try {
      const d = await api(`api/insight/${insightId}/live`);
      if (d.poll_s) livePollS = d.poll_s;
      const states = d.states || {};
      frames.forEach(({ frameId, frame }) => {
        if (!frame.contentWindow) return;
        frame.contentWindow.postMessage(
          { type: "bruh-live", id: frameId, states }, "*");
      });
      // When readings last ARRIVED, which is the one age the card could
      // not report: `generated_at` is when Claude wrote the prose, and on
      // a live card the numbers beside it are seconds old.
      state.liveSeen[insightId] = {
        at: Date.now(), n: Object.keys(states).length, ok: true,
      };
    } catch (e) {
      // A refresh that did not arrive leaves the card showing what it
      // last had, which is the same thing a card with no live entities
      // shows and is never worse than blanking it — but it must not go on
      // claiming the readings are current. The arrival stamp is KEPT so
      // the foot can age from the last real one rather than resetting.
      const prev = state.liveSeen[insightId] || {};
      state.liveSeen[insightId] = { ...prev, ok: false };
    }
  }
  // Painted from the tick rather than by re-rendering the card:
  // `renderIfChanged` deliberately does not rebuild an iframe it does not
  // have to, and a re-render every 15s to move one word would rebuild
  // every visualization on the page.
  paintLiveAge();
  if (liveFrames.size) livePoll = setTimeout(liveTick, livePollS * 1000);
}

// How old the live half of a card is, in the foot's own voice. Three
// states and they are three different claims: nothing has arrived yet,
// readings are current, and the last fetch did not get through — the
// third is the one that must not read as the second, because a frozen
// number under a "live" label is the reading nothing can correct.
// A report says one age, "Updated", and the readings a live card keeps
// current say nothing while they are arriving — they are as current as the
// screen. What is never silent is the fault: readings that have stopped
// arriving say so, from the last one that did, because a frozen number
// under a live chart is the reading nothing can correct.
function liveAgeText(insightId, declared) {
  const seen = state.liveSeen[insightId];
  if (!seen || !seen.at || seen.ok) return "";
  const n = seen.n || declared || 0;
  return `· ${n} live reading${n === 1 ? "" : "s"} not updating since `
    + timeAgo(new Date(seen.at).toISOString());
}

// Text AND the class, from one function, so the two can never disagree
// about whether this card's readings are arriving. The words carry the
// state on their own and the colour only reinforces it — status by colour
// alone is what the design system forbids, and this line is read at
// 11.5px in a muted row.
function paintLive(span) {
  const id = span.dataset.liveAge;
  const seen = state.liveSeen[id];
  span.textContent = liveAgeText(id, Number(span.dataset.liveN) || 0);
  span.classList.toggle("stale", !!(seen && seen.at && !seen.ok));
}

function paintLiveAge() {
  document.querySelectorAll("[data-live-age]").forEach(paintLive);
}

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
  // The expanded view may be as tall as the screen allows; a card in the
  // grid stops at 760 so one tall chart cannot push the rest off the page.
  const cap = frame.id === "modalFrame" ? Math.max(320, window.innerHeight - 160) : 760;
  frame.style.height = Math.min(Math.max(d.h, 120), cap) + "px";
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
  // The chip only ever renders for trouble, and trouble is exactly when
  // there is something to press: it went to the sign-in screen from nowhere
  // before, so the panel could report a failed login and offer no way to
  // answer it.
  chip.title = settled ? chip.title : chip.title + " — press to fix the sign-in";

  // Four states, not three: not connected → connect; asked for the sign-in
  // screen → connect (with a way back); connected but never onboarded → the
  // first-run flow; onboarded → the dashboard.
  const signIn = !s.authenticated || state.showSignIn;
  const ready = s.authenticated && obState.onboarded && !state.showSignIn;
  $("#setup").classList.toggle("hidden", !signIn);
  $("#setupBack").classList.toggle("hidden", !s.authenticated);
  $("#setupTitle").textContent = s.authenticated
    ? "Sign in to Claude again" : "Connect your Claude account";
  $("#onboard").classList.toggle("hidden", signIn || obState.onboarded);
  $("#dash").classList.toggle("hidden", !ready);
  $("#settingsBtn").classList.toggle("hidden", !s.authenticated);
  // `enable_insights: false` takes the one tab only ever filled by a
  // Claude run the scheduler would have queued; Findings stays, since the
  // house checks cost nothing and still file there — and so does
  // Proposals, which the checks pass fills too and which is now the one
  // surface a proposal is offered on.
  const insightsOn = s.insights_enabled !== false;
  document.querySelectorAll('.subtab[data-view="insights"], #segNav .segbtn[data-view="insights"]')
    .forEach((b) => b.classList.toggle("gone", !insightsOn));
  document.querySelectorAll('.viewtab[data-group="insights"]')
    .forEach((b) => { b.dataset.view = insightsOn ? "insights" : "findings"; });
  // Signing in and the first run live where the decisions go (Needs you),
  // so a panel that is not ready yet lands there rather than on an empty
  // grid of cards.
  if ((!insightsOn || !ready) && currentView === "insights") {
    switchView("findings");
  } else {
    syncTabs(currentView);
    syncSegNav(currentView);
  }
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
const USAGE_PILL_AT = 80;

function usagePillWanted(u) {
  if (!u) return false;
  if (u.blocked) return true;
  return (Number(u.used_percent) || 0) > USAGE_PILL_AT
    || (Number(u.week_percent) || 0) > USAGE_PILL_AT;
}

function renderUsageChip() {
  const s = state.status;
  const chip = $("#usageChip");
  const u = s && s.authenticated && s.usage;
  // The numbers live in ⚙ → Usage & schedule. The header carries them only
  // when they are news: past USAGE_PILL_AT in either window, or with
  // automatic insights paused by the budget. A pill reading "Session 3%"
  // on every visit is a reading nobody acts on, beside a status line that
  // already says whether brAIn is working.
  if (!u || u.used_percent == null || !usagePillWanted(u)) {
    chip.classList.add("hidden");
    if (chipPopFor === chip) closeChipPop();
    return;
  }
  const hasWeek = u.week_percent != null;
  // An estimate is a different reading, and the pill has to say so on its
  // face. When the tracker fails the fallback counts brAIn's own insight
  // runs, which on a home that mostly uses the terminal and the chat is 0%
  // that never moves — a live-looking number that is neither live nor the
  // account's. The `~` is the same prefix the spinner's token estimate
  // uses, and the dot carries the trouble so nothing gains a second chip.
  const est = u.source !== "account";
  $("#usageChipPct").textContent = `${est ? "~" : ""}${Math.round(u.used_percent)}%`;
  $("#usageChipWeekPct").textContent = hasWeek ? `${Math.round(u.week_percent)}%` : "";
  $("#usageChipWeek").classList.toggle("hidden", !hasWeek);
  chip.classList.toggle("ok", !u.blocked && !est);
  chip.classList.toggle("warn", !!u.blocked || est);
  chip.removeAttribute("title");
  chip.setAttribute("aria-label",
    `Claude usage — session ${est ? "an estimated " : ""}`
    + `${Math.round(u.used_percent)}%`
    + (hasWeek ? `, week ${Math.round(u.week_percent)}%` : "")
    + (est ? ". Your account's own usage is unavailable." : "")
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
  setChipPop($("#usageChip"), "Claude usage", usagePopHtml());
}

// The usage disclosure's body, shared by the pill and the phone's status
// dot, so a phone reads the same two windows and the same notes.
function usagePopHtml() {
  const u = (state.status && state.status.usage) || {};
  const rows = [];
  const row = (name, pct, when) =>
    `<div class="prow"><span class="pname">${esc(name)}`
    + (when ? `<span class="pwhen">${esc(when)}</span>` : "")
    + `</span><span class="pval">${Math.round(pct)}%</span></div>`;
  rows.push(row(u.source === "account" ? "Session · 5 hours"
                                       : "Session · 5 hours (estimated)",
    u.used_percent || 0,
    u.resets_at ? `resets ${fmtClock(u.resets_at)}` : ""));
  if (u.week_percent != null) {
    rows.push(row("This week", u.week_percent,
      u.week_resets_at ? `resets ${fmtDayClock(u.week_resets_at)}` : ""));
  }
  const trouble = limitsNote(u);
  if (trouble) rows.push(trouble);
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
  return rows.join("");
}

// Why the percentage above is an estimate rather than the account's own.
//
// When the usage tracker fails, its file goes stale, the panel falls back
// to counting brAIn's own insight runs against a rough plan allowance, and
// the weekly window disappears entirely — so on a home that mostly uses the
// terminal and the chat the pill sits at 0% and never moves. That is
// indistinguishable from a broken sensor, and the only thing this popover
// used to say about it was "sign in with your Claude subscription", which
// sends somebody who IS signed in to redo the one thing that was working.
//
// The tracker knows exactly what stopped it, so its own status is what gets
// said, with the two codes people misread spelled out: a rate limit is the
// endpoint's, not the account's, and an API key has no window to report.
function limitsNote(u) {
  const lim = u && u.limits;
  if (!lim || !lim.code) return "";
  const back = lim.next_attempt
    ? ` brAIn tries again at <b>${esc(fmtClock(lim.next_attempt))}</b>.` : "";
  const say = (head, body) =>
    `<p class="pnote"><b>${head}</b> ${body}${back}</p>`;
  switch (lim.code) {
    case "no_oauth_token":
      return say("Your account's real usage is not available.",
        `Nothing has signed in with a Claude subscription yet — the figure `
        + `above is an estimate from brAIn's own runs. Sign in from `
        + `<b>⚙ › Account</b>.`);
    case "api_key_has_no_usage_limits":
      return say("An API key has no usage window.",
        `It bills per token instead, so there is no session or weekly `
        + `percentage to report. The figure above is brAIn's own spend `
        + `against a rough allowance.`);
    case "http_401":
      return say("Anthropic refused the saved credential.",
        `The sign-in has expired or been revoked, so the figure above is an `
        + `estimate. Signing in again restores the real numbers.`);
    case "oauth_token_lacks_usage_scope":
      return say("This sign-in cannot read your usage.",
        `The saved token runs Claude perfectly, but <b>ha login</b> is built `
        + `on <b>claude setup-token</b>, which asks Anthropic only for `
        + `permission to run Claude — so running it again will not help. `
        + `Open <b>⚙ › Account › Sign in again</b> and choose `
        + `<b>Sign in to your Claude account</b>: it asks for the permission `
        + `this figure needs, no terminal involved, and the real numbers come `
        + `back on the next poll.`);
    case "oauth_token_awaiting_refresh":
      // Bounded: `usage_store` flips `needs_nothing` off once this has
      // stood for hours, because "wait" is only an answer while waiting
      // can work — and the sentence has to change with it, or a stuck
      // tracker reads exactly like a working one for a day.
      if (lim.stuck) {
        return say("Your sign-in's token has lapsed and brAIn has not "
          + "managed to renew it.",
          `brAIn renews it itself and has been trying for hours without an `
          + `answer it can use, so something is in the way — the add-on log `
          + `says what. The figure above is an estimate meanwhile. If the log `
          + `says the renewal was refused, sign in again from `
          + `<b>⚙ › Account › Sign in again</b>.`);
      }
      return say("Your sign-in is fine — its token is between refreshes.",
        `An access token lives for a few hours and brAIn renews it itself `
        + `on the next poll. Nothing is wrong and <b>signing in again will `
        + `not make it arrive sooner</b>. The figure above is an estimate `
        + `until then.`);
    case "http_403":
      return say("Anthropic refused to show your usage.",
        `It did not say why. The figure above is an estimate; signing in `
        + `again from <b>⚙ › Account › Sign in again</b> is what `
        + `usually fixes it.`);
    case "http_429":
      return say("Anthropic is rate-limiting the usage endpoint itself.",
        `This is not your account's usage and no amount of quota clears it. `
        + `The figure above is an estimate until it lifts.`);
    case "network_error":
      return say("brAIn could not reach Anthropic.",
        `The figure above is an estimate from brAIn's own runs until the `
        + `connection comes back.`);
    case "not_running":
      return say("The usage tracker has not reported yet.",
        `It writes its first reading shortly after the add-on starts; until `
        + `then the figure above is an estimate.`);
    case "stale":
      return say("The usage tracker has stopped reporting.",
        `The figure above is an estimate from brAIn's own runs. The add-on `
        + `log says what happened.`);
    default:
      return say("brAIn could not read your account's usage.",
        `The tracker reported <b>${esc(lim.code)}</b>, so the figure above `
        + `is an estimate from brAIn's own runs.`);
  }
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
  if (id.startsWith("fix-")) return "A plan for a finding";
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
        + `<b>${esc(u.plan_label || "plan")}</b> allowance — which is what the `
        + `percentage above is measured from while your account's own usage `
        + `is unavailable.`)
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
  renderStatusDot();
}

// The phone's header holds the logo, one dot and ⚙ (docs/design/ui-
// redesign-2026-10.md, PR 10): the three chips above are a wider screen's.
// So the dot carries the worst of what they and the status line would say,
// and pressing it opens the same disclosure with each of them in words and
// the press each chip itself is. Nothing the chips report is lost on a
// phone — it is one press further away, which is where a reading that is
// not news belongs anyway. Its colour is never the only signal: the label
// says the state, and the popover says it in a sentence.
const DOT_RANK = { watching: 0, needs_restart: 1, paused: 1, degraded: 2, signed_out: 3 };

function statusDotState() {
  const s = state.status || {};
  let kind = (s.status && s.status.state) || "watching";
  const raise = (k) => {
    if ((DOT_RANK[k] || 0) > (DOT_RANK[kind] || 0)) kind = k;
  };
  if (!$("#authChip").classList.contains("hidden")) {
    raise($("#authChip").classList.contains("busy") ? "paused" : "signed_out");
  }
  if (!$("#pausedChip").classList.contains("hidden")) raise("paused");
  const u = s.usage || {};
  if (!$("#usageChip").classList.contains("hidden") && u.blocked) raise("paused");
  return kind;
}

function statusDotSentence() {
  const st = (state.status && state.status.status) || {};
  if (st.state === "watching" || !st.state) {
    return st.last_look_at ? `Watching · last look ${agoWords(st.last_look_at)}` : "Watching";
  }
  return (st.sentence || st.label || "Watching").replace(/\.$/, "");
}

function renderStatusDot() {
  const dot = $("#statusDot");
  if (!dot) return;
  const kind = statusDotState();
  dot.dataset.state = kind;
  dot.setAttribute("aria-label", `brAIn: ${statusDotSentence()}. Press for detail.`);
  if (chipPopFor === dot) fillStatusPop();
}

function fillStatusPop() {
  const dot = $("#statusDot");
  const rows = [`<p class="pnote">${esc(statusDotSentence())}</p>`];
  const press = (id, text) =>
    `<button type="button" class="chip clickable dotpress" data-press="${id}">`
    + `<span class="dot"></span><span>${esc(text)}</span></button>`;
  if (!$("#authChip").classList.contains("hidden")) {
    rows.push(press("authChip", $("#authChipText").textContent));
  }
  if (!$("#pausedChip").classList.contains("hidden")) {
    rows.push(press("pausedChip", $("#pausedChipText").textContent));
  }
  if (!$("#usageChip").classList.contains("hidden")) rows.push(usagePopHtml());
  setChipPop(dot, "brAIn", rows.join(""));
}

$("#statusDot").addEventListener("click", () =>
  toggleChipPop($("#statusDot"), fillStatusPop));
// A press inside the dot's disclosure is the chip's own press, so the two
// routes cannot come to mean different things.
$("#chipPop").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-press]");
  if (!b) return;
  const chip = document.getElementById(b.dataset.press);
  closeChipPop();
  if (chip) chip.click();
});

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
  // An anchor with no box is an anchor that has gone: ⋯ → Model opens this
  // from a menu item, and the same press closes the menu behind it. There
  // is nothing left to measure against, so the next reposition would put
  // the popover in the top-left corner of the screen — measured at (8, 6)
  // after a resize. Same call as `scroll` makes: a popover that has lost
  // the thing it points at is dismissed, not relocated.
  if (!a.width && !a.height) { closeChipPop(); return; }
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

  // Two sign-ins, and the difference is an OAuth SCOPE rather than a style.
  // `account` is `claude auth login`, which asks Anthropic for `user:profile`
  // among others and so can read the usage figures; `token` is
  // `claude setup-token`, which asks for `user:inference` alone and is the
  // only one of the two that can be copied into the file the other BRUH
  // add-ons read. Neither replaces the other — see `engine.FLOW_MODES`.
  const startSetup = async (mode) => {
    const btns = [$("#setupStart"), $("#setupStartToken")];
    btns.forEach((b) => { if (b) b.disabled = true; });
    $("#setupErr").classList.add("hidden");
    try {
      await api("api/auth/setup/start", {
        method: "POST", body: JSON.stringify({ mode }),
      });
      pollSetup();
    } catch (e) {
      showSetupError(e.message);
      btns.forEach((b) => { if (b) b.disabled = false; });
    }
  };

  $("#setupStart").addEventListener("click", () => startSetup("account"));
  $("#setupStartToken").addEventListener("click", () => startSetup("token"));

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
    state.showSignIn = false;   // same reason as the guided flow's `done`
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
  if ($("#setupStartToken")) $("#setupStartToken").disabled = false;
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
  const was = pollSetup.lastPhase;
  pollSetup.lastPhase = st.phase;
  // "done" is a state the server keeps reporting for as long as the
  // credential lives, so the toast is for ARRIVING there — from a phase
  // this page watched — never for finding it there on a tab switch.
  if (st.phase === "done"
      && !["starting", "awaiting_code", "working"].includes(was)) return;
  if (st.phase === "done") {
    phaseChip.classList.remove("busy");
    phaseChip.classList.add("ok");
    phaseText.textContent = "Connected!";
    toast("Claude account connected");
    resetSetupUI();
    // A sign-in that succeeded is the end of asking for the sign-in screen.
    // Without this the screen is sticky in exactly the case it was added
    // for — signing in AGAIN over a credential that had stopped working —
    // because `authenticated` was already true and so nothing else here
    // would ever take it down.
    state.showSignIn = false;
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

// ⋯ › Past versions: every run this report has kept, newest first, in the
// same popover the menu used. Picking one pins the card to it (the card
// then says so, with a way back to the latest).
async function openPastVersions(id, insight, card) {
  const anchor = card && card.querySelector(".card-head .actions .btn.icon");
  if (!anchor) return;
  await loadHistory(id);
  const entries = historyEntries(id, insight);
  const cur = state.viewing[id] ? state.viewing[id].ts : "";
  const rows = entries.map((ts, i) =>
    `<button class="cardmenuitem${ts === cur ? " on" : ""}" data-i="${i}">`
    + `<span class="cmtext"><b>${esc(ts ? fmtRun(ts) : "Latest")}</b></span></button>`)
    .join("");
  setChipPop(anchor, "Past versions", entries.length > 1
    ? `<div class="cardmenu">${rows}</div>`
    : "<p>Only the latest version so far.</p>");
  $("#chipPop").querySelectorAll(".cardmenuitem").forEach((row) =>
    row.addEventListener("click", () => {
      closeChipPop();
      viewRun(id, entries[Number(row.dataset.i)] || null);
    }));
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

// `live` decides whether this frame is offered live readings. A card
// pinned to a PAST run must not be: paging back is how you see what the
// card said in March, and pushing today's door state into March's
// visualization makes it a hybrid of that run's prose and this
// afternoon's numbers — which is the two-ages confusion in its worst
// form, because nothing on screen could tell you it had happened.
function makeFrame(insight, live = true) {
  const wrapper = el("div", "viz");
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("title", insight.title || "Insight visualization");
  frame.setAttribute("loading", "lazy");
  const frameId = `${insight.id}-${state.frameSeq++}`;
  frame.dataset.frame = frameId;
  frame.srcdoc = insight.html + SIZE_SNIPPET(frameId) + LIVE_SNIPPET(frameId);
  wrapper.appendChild(frame);
  if (live) watchLive(frameId, insight);
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
  sel.className = "sel histsel";
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
    // `items` may be a function, read at the press: a menu whose rows
    // follow a poll (Today's status line) is built once and asked then.
    const list = typeof items === "function" ? items() : items;
    const rows = list.map(([icon, label, hint], i) =>
      `<button class="cardmenuitem" data-i="${i}">`
      + (icon ? `<span class="cmicon">${esc(icon)}</span>` : "")
      + `<span class="cmtext"><b>${esc(label)}</b>`
      + `<small>${esc(hint)}</small></span></button>`).join("");
    setChipPop(btn, "", `<div class="cardmenu">${rows}</div>`);
    $("#chipPop").querySelectorAll(".cardmenuitem").forEach((row) =>
      row.addEventListener("click", () => {
        closeChipPop();
        list[Number(row.dataset.i)][3]();
      }));
  });
  return btn;
}

// "Make this an automation": what a card says the house is missing, from
// its menu. The server already offered what it could on the Proposals tab
// (`_offer_card_opportunities`) — this is the door for the rest: one it did
// not send (paused, the day's cap, a question rather than a rule) goes into
// the ask bar for a person to read and send, and a card with none still
// offers the bar with "When " in it, because a person reading a card is the
// moment they think of the rule. Never sent from here: the ask bar is where
// somebody can read what they are about to ask for.
function cardAutomationItems(shown) {
  const opps = Array.isArray(shown.opportunities) ? shown.opportunities : [];
  const items = opps.slice(0, 2).map((opp) => (opp.queued
    ? ["", "See the automation it suggested",
      `On Today: “${opp.text}”`,
      () => switchView("findings")]
    : ["", "Make this an automation",
      `“${opp.text}”${opp.why ? ` — not offered yet: ${opp.why}` : ""}`,
      () => seedAsk(opp.sentence || opp.text)]));
  if (!opps.some((opp) => !opp.queued)) {
    items.push(["", "Make an automation from this",
      "Describe it in the ask bar — brAIn replays it over your history "
      + "before it offers it", () => seedAsk("When ")]);
  }
  return items;
}

function seedAsk(text) {
  // Asking is the Ask tab's: the sentence goes into the chat's composer for
  // a person to read and send.
  switchView("terminal");
  const input = $("#chatInput");
  if (!input) return;
  input.value = text;
  input.dispatchEvent(new Event("input"));
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
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
  // The line over the title says what the card is ABOUT. An asked card
  // used to say CUSTOM there — where it came from, which nobody needs
  // telling — so it is headed by its topics now (`eyebrow`, derived once
  // on the server), and the question it was asked as lives in Refine.
  const catName = catInfo ? catInfo.title
    : ((insight && insight.eyebrow) || "Your question");
  const catRow = el("div", "cat", catName);
  const asked = (shown && shown.question) || (insight && insight.question);
  if (!catInfo && asked) tip(catRow, `You asked: “${asked}”`);
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
  // Two controls on a report: Ask, and ⋯ for the rest. Ask is the one
  // thing people want from a report they are reading — say what should be
  // different, or ask about it — and it opens the card's own dialog, which
  // also holds what a card's definition can change (its schedule and
  // prompt, making an asked one recurring, turning it into an automation).
  // Expanding is the card itself: pressing it opens it full size.
  if ((catInfo || insight) && !view) {
    const ask = el("button", "btn small cardask", "Ask");
    ask.type = "button";
    tip(ask, "Ask about this report, or say what should change");
    ask.disabled = active;
    ask.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openRefine(id, catInfo, insight);
    });
    actions.appendChild(ask);
  }

  const menu = [];
  if (shown) {
    menu.push(["", "Share", "Copy it as a picture, or put it on a dashboard",
      () => openShare(shown)]);
  }
  if (insight && (catInfo || String(id).startsWith("custom-"))) {
    menu.push(["", "Past versions", "Read what this report said before",
      () => openPastVersions(id, insight, card)]);
  }
  if (!active && !view && (catInfo || insight)) {
    menu.push(["", "Run", "Make this report again now",
      () => generate(id, (insight && insight.question) || job.question, true)]);
  }
  // Delete is every card's — including one whose only trace is a job, so a
  // failed question can be cleared away instead of sitting there forever.
  // A still-running job is left alone: the worker would just re-register it.
  if (catInfo || insight || (fallbackId && !active)) {
    menu.push(["", "Delete", "Delete this report and its history",
      () => deleteCard(id, catInfo, catName)]);
  }
  if (menu.length) actions.appendChild(cardMenuButton(menu));
  head.appendChild(actions);
  card.appendChild(head);
  if (shown) {
    card.classList.add("opens");
    card.addEventListener("click", (ev) => {
      if (ev.target.closest("button, a, input, select, textarea, summary, .histpill")) return;
      openModal(shown, !view);
    });
  }

  if (view) {
    const pill = el("div", "histpill");
    pill.appendChild(el("span", null, `Viewing ${fmtRun(view.ts)}`));
    const back = el("button", "btn small", "Latest");
    back.addEventListener("click", () => viewRun(id, null));
    pill.appendChild(back);
    card.appendChild(pill);
  }

  // the question shows while the answer is still generating too, so an
  // in-flight "Ask" card says what it's working on
  // An answered card does not repeat its question: the title and the
  // answer are what it is for, and the question is one press away in
  // Refine. A card still working, or one that failed, has nothing else to
  // say what it is about, so it shows the question until it does.
  const question = (shown && shown.question) || job.question;
  if (question && (active || !shown)) {
    card.appendChild(el("div", "summary asking", `“${question}”`));
  }

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
    if (shown.summary) card.appendChild(summaryNode(shown.summary));
    if (shown.highlights && shown.highlights.length) {
      const prevData = view ? view.prev : state.prevLatest[id];
      const prevHls = (prevData && prevData.highlights) || [];
      const hls = el("div", "highlights");
      // Tiles in even rows: four across, three for five or six (a row of
      // four over a lone fifth is the ragged shape this replaced), and two
      // on a narrow card. The count is the markup's; the widths are CSS's.
      const n = shown.highlights.filter((h) => h && h.label).length;
      hls.dataset.n = String(Math.min(n, 6));
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
    card.appendChild(makeFrame(shown, !view));
    // Tags belong to the card, not to the run being viewed — editing them
    // while pinned to March's run must still change the card's tags.
    // Tags head the card (an asked card's eyebrow IS its topic tags) and
    // filter from the bar above the grid, so the chip row under every card
    // said them a second time. It is back while you edit them.
    if (insight && state.editingTags === id) {
      const tagRow = makeTagRow(insight);
      if (tagRow) card.appendChild(tagRow);
    }
    const foot = el("div", "foot");
    // One age, the one a reader asks about: when brAIn last wrote this.
    // Tokens, the reason it ran and when it runs next are Diagnostics'
    // business, not the report's. A live card still says so when its
    // readings stop arriving — a frozen number under a live chart is the
    // one thing on a report that must not pass in silence.
    const liveEnts = (!view && Array.isArray(shown.live)) ? shown.live : [];
    foot.appendChild(el("span", "cardage",
      view ? `From ${fmtRun(view.ts)}` : `Updated ${timeAgo(shown.generated_at)}`));
    if (liveEnts.length) {
      const live = el("span", "livemark", "");
      live.dataset.liveAge = id;
      live.dataset.liveN = String(liveEnts.length);
      paintLive(live);
      foot.appendChild(live);
    }
    card.appendChild(foot);
  } else if (job.state === "error") {
    const box = el("div", "errbox");
    box.appendChild(el("div", null, "Generation failed"));
    const code = el("code", null, job.error || "unknown error");
    box.appendChild(code);
    const retry = el("button", "btn small", "Try again");
    retry.style.marginTop = "10px";
    retry.addEventListener("click", () => generate(id, question, true));
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

// A named button on a card's head: an icon and a word, and on a narrow
// card the icon alone (the word is hidden by a container query, and the
// tooltip and aria-label still carry it).
function cardActionButton(icon, label, hint, run) {
  const btn = el("button", "btn cardact");
  btn.type = "button";
  const glyph = el("span", "caicon", icon);
  glyph.setAttribute("aria-hidden", "true");
  btn.appendChild(glyph);
  btn.appendChild(el("span", "calabel", label));
  tip(btn, hint);
  btn.addEventListener("click", run);
  return btn;
}

// The summary opens with the answer ("Yes — dehumidify first.") and the
// contract asks for exactly that, so the first sentence is set in the
// card's ink and the reason after it in the quieter colour. A summary
// that is one sentence is left as it is: bolding the whole of it says
// nothing. The server splits it the same way for the dashboard page.
function splitLead(text) {
  const m = String(text || "").match(/^(.{3,160}?[.!?])\s+(\S[\s\S]*)$/);
  return m ? [m[1], m[2]] : ["", String(text || "")];
}

function summaryNode(text) {
  const node = el("div", "summary");
  const [lead, rest] = splitLead(text);
  if (lead) {
    node.appendChild(el("strong", "lead", lead));
    node.appendChild(document.createTextNode(` ${rest}`));
  } else {
    node.textContent = rest;
  }
  return node;
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

// One wrapping line above the cards: what brAIn has done for itself since
// you last looked. Every number is read off the /api/status poll that is
// already running, so it costs no request of its own — and a segment whose
// data is absent is OMITTED rather than rendered as a zero, because "no
// checks pass has finished" and "the pass found nothing" are different
// reports of the same quiet house and only one of them is news.
//
// A pass that is running says so, and says how long it has been going WHEN
// the server has done that subtraction — `elapsedLabel` answers an unknown
// elapsed with silence rather than a confident "(0s)", and the subtraction
// stays the server's so a phone with a wrong clock still reads right.
function renderToday(today) {
  const strip = $("#todayStrip");
  if (!strip) return;
  strip.textContent = "";
  const t = today || {};
  const segs = [];

  const checks = t.checks || {};
  if (checks.running) {
    segs.push(["checks", `Checks running${elapsedLabel(checks.running_for)}`, null]);
  } else if (checks.last_at) {
    const bits = [`Checks ran ${whenAt(checks.last_at)}`];
    const ran = Number(checks.ran) || 0;
    const skipped = Number(checks.skipped) || 0;
    const errored = Number(checks.errored) || 0;
    // "12 ran, 1 could not look" — a skipped check did not find nothing, and
    // it is the same check `clear_resolved` may not clear a row for.
    let part = `${ran} ran`;
    if (skipped) part += `, ${skipped} could not look`;
    if (errored) part += `, ${errored} errored`;
    bits.push(part);
    const created = Number(checks.created) || 0;
    const cleared = Number(checks.cleared) || 0;
    if (created) bits.push(`${created} new finding${created === 1 ? "" : "s"}`);
    if (cleared) bits.push(`${cleared} cleared`);
    if (checks.next_at) bits.push(`next ${whenAt(checks.next_at)}`);
    segs.push(["checks", bits.join(" · "), null]);
  }

  const base = t.baselines || {};
  if (base.running) {
    segs.push(["baselines", `Baselines rebuilding${elapsedLabel(base.running_for)}`, null]);
  } else if (base.error) {
    segs.push(["baselines", `Baselines: ${base.error}`, null]);
  } else if (base.built_at) {
    segs.push(["baselines", `Baselines rebuilt ${whenAt(base.built_at)}`, null]);
  }

  const mem = t.memory || {};
  if (mem.running) {
    segs.push(["memory", `Memory filing now${elapsedLabel(mem.running_for)}`, null]);
  } else if (mem.last_filed_at) {
    const waiting = Number(mem.waiting) || 0;
    segs.push(["memory", `Memory filed ${agoAt(mem.last_filed_at)}`
      + (waiting ? `, ${waiting} waiting` : ""), null]);
  }

  // The one segment that is a press: a problem report is a file somebody has
  // to read, and the place to read it is behind ⚙ — so say where rather than
  // making them go and find it.
  const problems = Number((t.reports || {}).since_yesterday) || 0;
  if (problems) {
    segs.push(["reports",
      `${problems} problem${problems === 1 ? "" : "s"} since yesterday`,
      openProblems]);
  }

  // Claude runs — rows a model ran for, not the checks passes beside them
  // (the checks have their own segment). It is what tells a quiet add-on
  // from a stopped one, which is why the window is said out loud rather
  // than left as "today", and why it says WHAT it counts.
  const runs = Number(t.claude_runs_24h) || 0;
  if (runs) {
    segs.push(["runs",
      `${runs} Claude run${runs === 1 ? "" : "s"} in the last day`, null]);
  }

  strip.classList.toggle("hidden", !segs.length);
  segs.forEach(([id, text, press]) => {
    const node = press ? el("button", "tseg press", text) : el("span", "tseg", text);
    node.dataset.seg = id;
    if (press) {
      node.type = "button";
      node.appendChild(el("span", "tsegwhere", "⚙ › Diagnostics"));
      node.addEventListener("click", press);
    }
    strip.appendChild(node);
  });
  // On a phone the strip is one line until asked: five segments wrapped to
  // five lines above the first card, which is a record of what brAIn did for
  // itself pushing what is waiting on you below the fold. The first segment
  // and any press stay; the rest are behind "+N more" (CSS hides it, and
  // the segments, only under the phone breakpoint — a wide screen has the
  // room for all of them on one line).
  const folded = segs.filter(([, , press], i) => i > 0 && !press).length;
  if (folded) {
    const more = el("button", "tsegmore", `+${folded} more`);
    more.type = "button";
    more.setAttribute("aria-expanded", String(strip.classList.contains("open")));
    more.addEventListener("click", () => {
      const open = strip.classList.toggle("open");
      more.setAttribute("aria-expanded", String(open));
      more.textContent = open ? "Less" : `+${folded} more`;
    });
    if (strip.classList.contains("open")) more.textContent = "Less";
    strip.appendChild(more);
  }
}

// ⚙ opens on the Diagnostics/Problems half; the section is already loaded by
// openSettings, so all this owes is putting it in front of somebody.
function openProblems() {
  openSettings();
  setTimeout(() => {
    const box = $("#probBody");
    if (box) box.scrollIntoView({ block: "center" });
  }, 60);
}

// Past this many reports a search field appears above them.
const REPORT_SEARCH_AFTER = 8;

function render() {
  const s = state.status;
  if (!s) return;
  renderAuth();
  renderToday(s.today);
  // Today's status line, banner and setup card follow the poll; the queue
  // under them is repainted by the presses and fetches that move it.
  renderTodayChrome();
  if (currentView === "findings") {
    // The setup card going away is the queue's cue to appear.
    const list = $("#findList");
    if (list && list.hidden !== !$("#todaySetup").hidden) renderFindings();
  }
  syncSegNav();
  if (!s.authenticated) return;

  // A search field once there are more reports than a screen or two holds.
  // It matches the headline, the summary, the eyebrow and the tags, so the
  // one-tap tag filter it replaced is a word typed instead.
  const search = $("#reportSearch");
  const many = state.insights.length > REPORT_SEARCH_AFTER;
  if (search) {
    search.hidden = !many;
    if (!many && state.query) { state.query = ""; search.value = ""; }
  }
  const q = many ? String(state.query || "").trim().toLowerCase() : "";

  // cards
  const grid = $("#grid");
  grid.textContent = "";
  const matches = (i) => !q || [i.title, i.summary, i.eyebrow, i.category_title,
    ...effectiveTags(i)].some((t) => String(t || "").toLowerCase().includes(q));
  const customs = state.insights.filter((i) => i.category === "custom");
  // custom in-flight jobs that have no stored insight yet
  Object.keys(s.jobs || {}).forEach((jid) => {
    if (jid.startsWith("custom-") && !insightFor(jid) &&
        ACTIVE_STATES.concat("error").includes(s.jobs[jid].state)) {
      customs.unshift({ id: jid, category: "custom", category_title: "Custom", icon: "✨", virtual: true });
    }
  });
  customs.forEach((i) => {
    if (i.virtual ? !!q : !matches(i)) return;
    // a virtual card has no insight yet — makeCard works off the job id
    grid.appendChild(makeCard(null, i.virtual ? null : i, i.id));
  });
  s.categories.forEach((c) => {
    const ins = insightFor(c.id);
    // not-yet-generated placeholders only clutter a search
    if (q && !(ins && matches(ins)) && !c.title.toLowerCase().includes(q)) return;
    grid.appendChild(makeCard(c, ins));
  });
}

// Rebuild only when something meaningful changed (avoid iframe reloads)
let lastRenderKey = "";
function renderIfChanged() {
  const s = state.status;
  const key = JSON.stringify({
    auth: s && [s.authenticated, s.auth_check.state, s.auth_source],
    // Asking for the sign-in screen is state this render reads, so it has
    // to be in the key. Without it, opening the screen over a credential
    // that already exists changes none of the three auth fields above —
    // and neither does signing in again successfully, so the screen went
    // up and never came down. Which is the failure in the one case the
    // screen was added for.
    signIn: state.showSignIn,
    jobs: s && s.jobs,
    // a card pinned to a past run keys on that run, not generated_at — the
    // poll loop must not clobber it when the latest regenerates elsewhere
    gen: state.insights.map((i) => i.id
      + (state.viewing[i.id] ? "@" + state.viewing[i.id].ts : i.generated_at)
      + ":t" + effectiveTags(i).join(",")),
    view: Object.keys(state.viewing).map((k) => k + state.viewing[k].ts),
    cats: s && s.categories.map((c) =>
      [c.id, c.title, c.icon, c.enabled, c.focus_overridden, c.refresh_hours,
       c.schedule,
       // The hold is rendered in the foot, so it has to be in the key or a
       // card that started waiting says "next in 3 h" until something
       // unrelated repaints. Its REASON only — the store re-stamps `at` on
       // every scheduler pass that holds, and keying on that would reload
       // every card's iframe every few minutes.
       c.refresh_hold ? c.refresh_hold.why : ""]),
    tagEdit: state.editingTags,
    paused: s && [s.settings && s.settings.auto_enabled, s.usage && s.usage.blocked],
    usage: s && s.usage && [s.usage.used_percent, s.usage.resets_at],
    // The Today strip is rendered by `render`, so what it reads has to be in
    // the key — otherwise a checks pass finishing while somebody is looking
    // changes nothing on screen until the next unrelated repaint.
    today: s && s.today,
    // Today's status line, brief link and setup card.
    status: s && [s.status, s.brief, s.first_look_done, obState.onboarded],
    query: state.query,
  });
  if (key !== lastRenderKey) {
    lastRenderKey = key;
    render();
  }
}

// ------------------------------------------------------------------ actions

// `inPlace` regenerates an asked card as itself. Without it, handing a
// question over is asking it afresh — which is what the ask bar means,
// and what Regenerate used to do by accident: a second card with the
// same answer, the first left where it was.
async function generate(categoryOrId, question, inPlace = false) {
  try {
    const custom = !!(categoryOrId && categoryOrId.startsWith("custom-"));
    const body = custom && (inPlace || !question)
      ? { id: categoryOrId, question: question || "" }
      : question
        ? { question }
        : { category: categoryOrId };
    const res = await api("api/generate", { method: "POST", body: JSON.stringify(body) });
    // The interpreter read the sentence (`interpret`) and may have sent it
    // more than one way at once. `routes` is what it read; every key below
    // is where each part landed, and each says so in its own words.
    if (res && Array.isArray(res.routes)) {
      showRouted(res);
      if ((res.queued || []).length) { await refreshStatus(); fastPoll(); }
      return;
    }
    // "learn about the boiler" isn't a card — the server routed it to a study
    // session instead, and there is nothing on the dashboard to wait for.
    if (res && "learning" in res) {
      toast(res.learning
        ? `Studying ${res.learning} — it runs in the background; what it finds `
          + "lands in Memory and Findings"
        : "Studying whatever brAIn knows least about — check Memory shortly");
      return;
    }
    // "when the guests leave…" is not a question about the house, so it never
    // becomes a card. It goes to the same queue the `brain.intent` service
    // writes to, and what comes back is a card on Proposals — including when
    // brAIn will not arm it, because a sentence somebody typed always gets an
    // answer. Naming where to look is the whole toast: nothing appears here.
    // "design my evening for the living room" is a room, not a question.
    // A refusal comes back on the request (composing is deterministic and
    // costs one fetch) and an offer does not, because naming the four is
    // a Claude run and a request cannot wait on one.
    if (res && ("scenes" in res || (res.refused && "area" in res))) {
      toast(res.refused
        ? res.refused
        : `Designing four scenes for the ${res.scenes} — ${res.lights} `
          + "lights. They land on Proposals in a moment, with a preview.");
      return;
    }
    if (res && "intent" in res) {
      toast("Working out what that means — it lands on Proposals in a moment. "
        + "Nothing runs until you accept it.");
      return;
    }
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  }
}

// What the interpreter did with one sentence, said once. The parts are the
// same toasts the ask bar's patterns always produced, joined, plus the two
// the patterns never had: a fact kept, and a "why" being looked into.
function showRouted(res) {
  const said = [];
  if ((res.queued || []).length) said.push("Making a card for that");
  if ("intent" in res) {
    said.push("working out the automation — it lands on Proposals, and "
      + "nothing runs until you accept it");
  }
  if ("learning" in res) {
    said.push(res.learning ? `studying ${res.learning} in the background`
      : "studying what brAIn knows least about");
  }
  if ((res.remembered || []).length) said.push("kept that in memory");
  if ("scenes" in res) said.push(`designing four scenes for the ${res.scenes}`);
  if (res.refused) said.push(res.refused);
  if (res.explain) {
    said.push("looking into why");
    watchExplain(res.explain);
  }
  if (said.length) {
    const text = said.join("; ");
    toast(text.charAt(0).toUpperCase() + text.slice(1) + ".");
  }
}

// A why-answer, polled until it lands. One at a time: a second question
// replaces the first, because the block under the bar is one answer.
let explainWatch = null;
async function watchExplain(id) {
  const box = $("#askExplain");
  if (!box) return;
  explainWatch = id;
  box.classList.remove("hidden");
  box.replaceChildren(el("p", "askexplain-wait", "Looking into why…"));
  for (let i = 0; i < 120 && explainWatch === id; i++) {
    let got = null;
    try {
      got = await api(`api/explain/${encodeURIComponent(id)}`);
    } catch (e) {
      got = { state: "error", answer: e.message };
    }
    if (got && got.state !== "running") {
      if (explainWatch === id) renderExplain(box, got);
      return;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

function renderExplain(box, got) {
  const head = el("div", "askexplain-head");
  head.append(el("b", null, got.question || "Why"));
  const close = el("button", "btn small ghost", "✕");
  tip(close, "Close this answer");
  close.type = "button";
  close.addEventListener("click", () => {
    explainWatch = null;
    box.classList.add("hidden");
    box.replaceChildren();
  });
  head.append(close);
  const body = [head, el("p", "askexplain-answer", got.answer || "")];
  if ((got.cited || []).length) {
    const list = el("ul", "askexplain-cited");
    got.cited.forEach((c) => list.append(el("li", null, c)));
    body.push(list);
  }
  if (got.offer) {
    // The change is the NEXT turn, not this one: it fills the bar and the
    // person sends it, which is the card menu's "Make this an automation".
    const next = el("button", "btn small", got.offer);
    next.type = "button";
    tip(next, "Put this in the question bar to ask for it");
    next.addEventListener("click", () => seedAsk(got.offer));
    body.push(next);
  }
  box.replaceChildren(...body);
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
  // The dot reads the status line's own state, which the render key above
  // does not carry, so it is repainted on every poll — one attribute.
  renderStatusDot();
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
        refreshToday(),
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

// `live` for `makeFrame`'s reason: expanding a card pinned to a past run
// must not overlay today's readings on March's visualization.
function openModal(insight, live = true) {
  $("#modalIcon").textContent = insight.icon || "✨";
  $("#modalTitle").textContent = insight.title || "";
  const frame = $("#modalFrame");
  const frameId = `modal-${state.frameSeq++}`;
  frame.dataset.frame = frameId;
  // A reused element keeps the last card's height until this one reports.
  frame.style.height = "";
  frame.srcdoc = insight.html + SIZE_SNIPPET(frameId) + LIVE_SNIPPET(frameId);
  openBox("#modal");
  // The expanded view is where a live card is most worth being live —
  // it is the one you sit and watch. `#modalFrame` is a reused element
  // rather than a rebuilt one, so it stays in the DOM after the modal
  // closes; `liveTick`'s visibility test is what stops it being polled
  // for the rest of the session.
  if (live) watchLive(frameId, insight);
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
  // Closed, and emptied: the dialog is one element reused for every card,
  // so a prompt left open from the last one would greet this card with
  // another card's blocks — the same trap `setChatFinding` clears.
  $("#editPrompt").hidden = true;
  $("#editPromptSections").textContent = "";
  $("#editPromptText").value = "";
  openBox("#editModal");
}

// The whole prompt, rebuilt rather than replayed. Half the blocks in it
// are live — the findings block, what brAIn has measured, what this card
// said last time — so showing a stored copy of what produced the card on
// screen would be showing a house that has moved on. What somebody
// iterating needs is "what will be sent if I press Save & regenerate",
// and that is what this asks for.
async function loadPromptView() {
  const box = $("#editPrompt");
  const secs = $("#editPromptSections");
  const text = $("#editPromptText");
  box.hidden = false;
  $("#editShowPrompt").disabled = true;
  secs.textContent = "";
  text.value = "";
  $("#editPromptSize").textContent = "Building it…";
  try {
    const d = await api(`api/prompt/${editCatId}/preview`);
    secs.innerHTML = (d.sections || []).map((sec) =>
      `<div class="psec"><span class="pname${sec.yours ? " pmine" : ""}">`
      + `${esc(sec.name)}</span>`
      + `<span class="pwhat">${esc(sec.what || "")}</span>`
      + `<span class="psize">${sec.chars ? fmtChars(sec.chars) : "—"}</span></div>`
    ).join("");
    text.value = d.system + "\n\n" + d.prompt;
    // `~` on the token figure everywhere it appears: it is derived from a
    // character count, not counted, and a bare number here would be read
    // as the one on the bill.
    $("#editPromptSize").textContent =
      `${fmtChars(d.chars)} · ~${fmtChars(d.tokens)} tokens · `
      + `${d.mode === "search" ? "search mode — the data section is a map and "
        + "the run fetches what it needs" : "snapshot mode — the whole home "
        + "is posted with the prompt"}`;
  } catch (e) {
    $("#editPromptSize").textContent = e.message;
  } finally {
    $("#editShowPrompt").disabled = false;
  }
}

function fmtChars(n) {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

$("#editShowPrompt").addEventListener("click", loadPromptView);
$("#editPromptHide").addEventListener("click", () => {
  $("#editPrompt").hidden = true;
});
$("#editPromptCopy").addEventListener("click", () =>
  copyOrSelect($("#editPromptText").value, "Prompt copied"));


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
  const week = usage.week_percent;
  const weekFill = $("#usageWeekFill");
  if (weekFill) {
    weekFill.style.width = (week == null ? 0 : Math.min(100, week)) + "%";
    weekFill.parentElement.classList.toggle("hidden", week == null);
    const weekLabel = weekFill.parentElement.previousElementSibling;
    if (weekLabel) weekLabel.classList.toggle("hidden", week == null);
  }
  const spent = usage.window_tokens >= 1000
    ? `${Math.round(usage.window_tokens / 1000)}k` : String(usage.window_tokens || 0);
  const reset = usage.resets_at ? `, resets ${fmtClock(usage.resets_at)}` : "";
  // The weekly window isn't budgeted against, but it is the one that ends a
  // Claude plan's week — so it is stated wherever the session is.
  const weekLine = week == null ? ""
    : ` Week ${Math.round(week)}%`
      + (usage.week_resets_at ? `, resets ${fmtDayClock(usage.week_resets_at)}.` : ".");
  $("#usageText").textContent = (usage.source === "account"
    ? `Session ${Math.round(usage.used_percent || 0)}%${reset}.`
    : `Session about ${Math.round(usage.used_percent || 0)}% (≈${spent} tokens by brAIn, `
      + `an estimate)${reset}.`) + weekLine + ` Budget mark at ${budgetPct}%.`;
  // Why the figure is an estimate, when it is one, and what brAIn's own
  // runs spent: the same two blocks the header pill's popover carries.
  const detail = $("#usageDetail");
  if (detail) {
    let html = "";
    try { html = limitsNote(usage) + spendRows(usage); } catch (e) { html = ""; }
    detail.innerHTML = html;
  }
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
  syncThinking(current);
}

// "How hard brAIn thinks" shifts the tiers each job runs on, and a model
// chosen above replaces the tiers for every run — so with one chosen the
// select changes nothing. It used to look exactly as live as when it
// mattered; now it is disabled and its line says why. The saved value is
// kept, so choosing the automatic model again brings it back as it was.
const THINKING_NOTE = "Every run is tiered by its job (Haiku looks, Sonnet thinks, "
  + "Opus acts); this shifts the tiers.";

function syncThinking(model) {
  const sel = $("#setThinking");
  const note = $("#setThinkingNote");
  const fixed = Boolean(model) && model !== CUSTOM_MODEL;
  if (sel) sel.disabled = fixed;
  if (note) {
    note.textContent = fixed
      ? "Not used while a model is chosen above: every run uses that model. "
        + "Pick CLI default to use the tiers."
      : THINKING_NOTE;
  }
}

function renderSettingsForm(data) {
  $("#setEnabled").checked = data.settings.auto_enabled !== false;
  $("#setCapture").checked = data.settings.capture === true;
  $("#setTerminalUi").value = data.settings.terminal_ui || "chat";
  $("#setChatSessions").value = String(data.settings.chat_max_sessions || 3);
  // Only an explicit true ticks it: a value that arrived missing or
  // malformed is asking, which is what the terminal and the chat will do.
  $("#setSkipPerms").checked = data.settings.dangerously_skip_permissions === true;
  renderSkipPermsNote(data);
  $("#setGatherMode").value = data.settings.gather_mode || "search";
  $("#setRefreshMode").value = data.settings.refresh_mode || "changed";
  $("#setThinking").value = data.settings.thinking || "normal";
  $("#setPlan").value = data.settings.plan || "pro";
  $("#setBudget").value = data.settings.budget_percent;
  $("#setBudgetVal").textContent = data.settings.budget_percent + "%";
  renderUsageMeter(data.usage, data.settings.budget_percent);
  Object.entries(OPTION_FIELDS).forEach(([id, key]) => {
    const val = data.settings[key];
    $("#" + id).value = val == null ? "" : String(val);
  });
  renderModelField(data);
  renderNotifyPolicy(data.settings || {});
  $("#setSyncNote").textContent = data.options_synced
    ? "The same settings as the add-on's Configuration tab."
    : "Saved in the panel only until the Supervisor answers.";
}

// ⚙ is eight `<details>`, and a section remembers whether it was open —
// somebody who lives in Diagnostics should not have to reopen it every
// visit, and a disclosure that forgets is one people stop using. `prefGet`
// can throw or answer null (an ingress iframe may be refused storage), so
// the markup's own `open` is the fallback rather than an assumed shut.
const SET_SECTIONS = ["account", "usage", "permissions", "sources",
                      "notifications", "memory", "diagnostics", "guide"];
const setSectionKey = (name) => "brain.set." + name;

// What opening a section has to fetch. Nothing here runs on the way into
// the dialog unless its section is already open: a dozen reads for
// somebody who came to change the model is the cost this arrangement is
// about.
const SET_LOADERS = {
  permissions: () => loadSetHouseRules(),
  sources: () => { loadCameras(); loadSetCalendars(); },
  memory: () => loadSetMemory(),
  diagnostics: () => loadAdvanced(),
  guide: () => renderSetGuide(),
};

function restoreSettingsSections() {
  SET_SECTIONS.forEach((name) => {
    const box = document.querySelector(`.setsec[data-sec="${name}"]`);
    if (!box) return;
    const saved = prefGet(setSectionKey(name));
    if (saved === "1") box.open = true;
    else if (saved === "0") box.open = false;
    box.addEventListener("toggle", () => {
      prefSet(setSectionKey(name), box.open ? "1" : "0");
      if (box.open && SET_LOADERS[name]) SET_LOADERS[name]();
    });
  });
}

// The readings behind Diagnostics, fetched the first time that section is
// opened and never on the way into the dialog. Two of them start a 3s poll,
// so loading them eagerly paid for a request every three seconds behind a
// section nobody had looked at. `openSettings` is what resets this, not
// the section closing: a reading already on screen is still the reading.
// Opening the dialog again DOES reset it — `closeBox` stops the deep-check
// and rehearsal polls, so a second visit with Diagnostics already open has
// to ask again or a run in flight goes quiet on the one screen that
// reports it.
let advancedLoaded = false;

function loadAdvanced() {
  if (advancedLoaded) return;
  advancedLoaded = true;
  loadDiagnostics();
  loadReports();
  loadCaptures();
  loadDeep(true);
  loadRehearsal(true);
  loadDiagAccuracy();
  loadDiagMeasures();
  loadDiagUpkeep();
}

// The line under "Let brAIn act without asking". The switch reaches a
// terminal session only when it STARTS — ttyd re-attaches to the same tmux
// session on every visit — so a flip leaves any open one as it began: still
// acting after "off", still asking after "on". The server counts what is
// running (`permission_sessions`, null when it could not look) and this
// says which open session did not get the current value, and how to end
// it. Nothing here ends one: a terminal is somebody's work.
// The caveat (protected entities are refused through brAIn's own tools,
// not every shell command) is its own line under this one and is never
// replaced: it is the half of the switch that is about safety.
const SKIP_PERMS_NOTE = "Applies to the next terminal session and chat message.";

function skipPermsStale(data) {
  const on = data.settings && data.settings.dangerously_skip_permissions === true;
  const live = data.permission_sessions || null;
  if (!live) return "";
  const acting = Number(live.acting) || 0;
  const asking = Number(live.asking) || 0;
  if (!on && acting > 0) {
    return acting > 1
      ? `${acting} terminal sessions started while this was on are still open and still act without asking. End them with /exit; the next one asks.`
      : "A terminal session started while this was on is still open and still acts without asking. End it with /exit; the next one asks.";
  }
  if (on && asking > 0) {
    return asking > 1
      ? `${asking} terminal sessions already open still ask. End them with /exit and the next one won't.`
      : "The terminal session already open still asks. End it with /exit and the next one won't.";
  }
  return "";
}

function renderSkipPermsNote(data) {
  const note = $("#setSkipPermsNote");
  if (!note) return;
  const stale = skipPermsStale(data);
  note.textContent = stale || SKIP_PERMS_NOTE;
  note.classList.toggle("warn", !!stale);
}

// Open ⚙ at one control: the section it lives in opened, the control
// scrolled into view, focused and briefly marked. What "Stop asking" on a
// chat approval card does — the switch is found where the asking happens,
// and flipped where its consequences are written down.
async function openSettingsAt(id) {
  await openSettings();
  const target = document.getElementById(id);
  if (!target) return;
  const sec = target.closest(".setsec");
  if (sec && !sec.open) sec.open = true;
  const row = target.closest(".setrow") || target;
  row.scrollIntoView({ block: "center" });
  try { target.focus({ preventScroll: true }); } catch (e) { /* not focusable */ }
  row.classList.add("setflash");
  setTimeout(() => row.classList.remove("setflash"), 2400);
}

async function openSettings() {
  openBox("#setModal");
  loadAuth();
  advancedLoaded = false;
  camerasLoaded = false;
  setCalendarsState.data = null;
  // A section's open state survived the close (it is remembered), so a
  // visit that lands on an already-expanded section still has to fetch:
  // the section being open is not the same claim as its rows being current.
  SET_SECTIONS.forEach((name) => {
    const box = document.querySelector(`.setsec[data-sec="${name}"]`);
    if (box && box.open && SET_LOADERS[name]) SET_LOADERS[name]();
  });
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
// `note` may be a function of the saved payload, for a toast whose words
// depend on what the server found (the permission switch's). Answers the
// payload, or null when the save failed, so a control can put itself back.
async function saveSettings(fields, note) {
  try {
    const data = await api("api/settings", {
      method: "PUT", body: JSON.stringify(fields) });
    renderSettingsForm(data);
    if (state.status) {
      state.status.settings = data.settings;
      state.status.usage = data.usage;
    }
    // ⚙ is reachable from the Terminal tab, and the chat's picker names the
    // global model on its Default row. That row only ever came from the
    // stream's opening snapshot, so changing the model here left the
    // *highlighted* row naming the model you had just replaced — which
    // reads as a save that did not take.
    chatState.defaultModel = data.settings.model || "";
    chatState.defaultModelLabel = data.model_label || "";
    renderUsageChip();
    renderPausedChip();
    toast((typeof note === "function" ? note(data) : note) || "Saved");
    return data;
  } catch (e) {
    toast(e.message);
    return null;
  }
}

$("#settingsBtn").addEventListener("click", openSettings);
// Once, at load: the sections are static markup, so their listeners are not
// something a render can leak.
restoreSettingsSections();

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
// --------------------------------------------------------------- diagnostics
// The ⚙ dialog's read-only half. It renders /api/diagnostics — the same
// payload the integration's Download-diagnostics button serves and `brain
// report` bundles — because a run journal nothing reads back is a run
// journal that only exists in a bug report somebody else has to ask for.
//
// It is fetched when the dialog opens and on ⟳, never on a timer: this is
// something you look at, and a poll behind a dialog nobody has open is a
// request per viewer per interval for an answer that changes hourly.
let diagPayload = null;

// `key` is TEXT and is escaped here; `value` is markup and is the caller's
// to escape. A caller that wants its key indented asks for `sub`, because
// the alternative is what the rehearsal block did: pass `&nbsp;&nbsp;` as
// part of the key, have it escaped exactly as promised, and render the
// six literal characters `&nbsp;` down the middle of the Settings dialog.
// Indentation is presentation and belongs in the stylesheet; a caller
// smuggling markup through an escaped argument can only ever be a bug.
function diagRow(key, value, bad, sub) {
  return `<div class="drow"><div class="dk${sub ? " dsub" : ""}">${esc(key)}</div>`
       + `<div class="dv${bad ? " dbad" : ""}">${value}</div></div>`;
}

function diagCounts(byOutcome) {
  const entries = Object.entries(byOutcome || {})
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) return "nothing yet";
  return entries.map(([word, n]) => `${n} ${esc(word)}`).join(" · ");
}

// Everything wrong right now, at the top of the dialog and at the top of
// the report — one list, one derivation, from the payload the server
// already assembles. Reading a fault used to mean knowing which of a
// dozen sections it would be in, which is the same reason the report
// grew this section: the facts were all there and none was findable.
function faultRows(d) {
  const rows = (d && d.faults) || [];
  if (!rows.length) {
    return [diagRow("Anything wrong?",
      "Nothing — every check ran, every daemon is up, no run failed in the "
      + "last day and the health verdict is ok.")];
  }
  const out = [diagRow("Anything wrong?",
    `${rows.length} thing${rows.length > 1 ? "s" : ""} to look at`, true)];
  rows.forEach((r) => out.push(diagRow(
    r.where || "?",
    esc(r.what || "")
    + (r.detail ? ` <span class="hint">${esc(r.detail)}</span>` : ""),
    true, true)));
  return out;
}

function renderDiagnostics(d) {
  diagPayload = d;
  const j = d.journal || {};
  const c = d.checks || {};
  const ok = (j.by_outcome || {}).ok || 0;
  const failures = j.failures || [];
  const rows = faultRows(d);
  // The verdict first, because it is the one line somebody who is not
  // debugging should have to read. Everything below it is the evidence.
  const h = d.health || {};
  rows.push(diagRow("brAIn", esc(h.reason || h.state || "unknown"),
    h.state && h.state !== "ok"));
  if (h.fix) rows.push(diagRow("What to do", esc(h.fix), true));
  if ((h.problems || []).length > 1) {
    const more = h.problems.slice(1, 5).map(
      (p) => `<li>${esc(p.what)} &mdash; ${esc(p.fix)}</li>`);
    rows.push(diagRow("Also", `<ul>${more.join("")}</ul>`, true));
  }
  rows.push(diagRow("Add-on version",
    esc((d.versions || {}).addon || "unknown")));
  // `claude --version` answers "2.1.290 (Claude Code)", which under a row
  // called Claude Code says its own name twice.
  rows.push(diagRow("Claude Code",
    esc(String((d.versions || {}).claude_cli || "not found").replace(/\s*\(Claude Code\)\s*$/, "")),
    !(d.versions || {}).claude_cli));
  rows.push(diagRow("Claude sign-in",
    esc((d.auth || {}).state || "unknown"),
    (d.auth || {}).state !== "ok"));
  // `claude_runs` is the Claude runs; `by_outcome` counts every journal
  // line (checks passes and summary rows too), so it is labelled as such.
  rows.push(diagRow("Claude runs, last 24h",
    `${j.claude_runs ?? j.runs ?? 0} — journal lines by outcome: `
      + diagCounts(j.by_outcome),
    (j.runs || 0) > 0 && ok < (j.runs || 0)));
  if (c && c.finished_at) {
    const errs = Object.keys(c.errors || {}).length;
    const skipped = Object.keys(c.skipped || {});
    rows.push(diagRow("House checks, last pass",
      `${timeAgo(new Date(c.finished_at * 1000).toISOString())} — `
      + `${(c.ran || []).length} ran, ${skipped.length} skipped, `
      + `${errs} errored`, errs > 0 || !!c.error));
    rows.push(diagRow("Filed by that pass",
      `${(c.created || []).length} new, ${c.refreshed || 0} updated, `
      + `${(c.cleared || []).length} cleared`));
    // A skipped check is not a quiet check: it could not look, and it is
    // also the one that may not clear a row. Saying which, and why, is the
    // difference between "all clear" and "I did not ask".
    if (skipped.length) {
      const why = skipped.slice(0, 5).map((id) =>
        `<li><b>${esc(id)}</b> — ${esc(c.skipped[id])}</li>`);
      rows.push(diagRow("Could not run", `<ul>${why.join("")}</ul>`));
    }
  } else {
    rows.push(diagRow("House checks", "no pass has finished yet"));
  }
  const b = d.baselines || {};
  rows.push(diagRow("What's normal here",
    b.built_at
      ? `${b.measured} sensors measured ${timeAgo(new Date(b.built_at * 1000).toISOString())}`
        + (b.stale ? " — stale" : "")
      : "not measured yet (the first pass runs overnight)",
    !!b.stale && !!b.built_at));
  {
    const fd = d.findings || {};
    rows.push(diagRow("Findings open", String(fd.open ?? 0)
      + (fd.waiting_look ? ` (${fd.waiting_look} still waiting for brAIn's first look)` : "")));
  }
  const n = d.notify || {};
  if (n.service) {
    // A hold queue nobody can see is a queue that silently swallows: this
    // row is what tells "quiet hours are working" from "the flush died".
    const window_ = (n.quiet_start === null || n.quiet_end === null)
      ? "no quiet hours"
      : `quiet ${String(n.quiet_start).padStart(2, "0")}:00–`
        + `${String(n.quiet_end).padStart(2, "0")}:00 ${esc(n.tz || "UTC")}`
        + (n.quiet_now ? " (now)" : "");
    const held = n.held
      ? `, ${n.held} held` + (n.held_since
        ? ` since ${timeAgo(new Date(n.held_since * 1000).toISOString())}`
        : "")
      : "";
    rows.push(diagRow("Notifications",
      `at ${esc(n.min_severity || "serious")} and up — ${window_}${held}`));
  }
  // Overnight self-healing. Three silences look identical from outside —
  // it is off, it is not the window yet, and it does not know when the
  // house is quiet — and only the last one needs anything doing.
  const heal = d.healing || {};
  if (!heal.enabled) {
    rows.push(diagRow("Overnight repairs", "off"));
  } else {
    const tried = heal.attempts || [];
    const worked = tried.filter((a) => a.ok).length;
    let line = tried.length
      ? `${tried.length} tried last night, ${worked} accepted`
        + (heal.last_run
          ? ` — ${timeAgo(new Date(heal.last_run * 1000).toISOString())}`
          : "")
      : "on, nothing repaired yet";
    if ((heal.skips || []).length) line += `, ${heal.skips.length} skipped`;
    rows.push(diagRow("Overnight repairs", esc(line)));
    // The reason it will not run is the row worth having: a self-healer
    // that has never run reads exactly like one with nothing to do.
    if (heal.reason) {
      rows.push(diagRow("Not running because", esc(heal.reason),
        /has not been measured/.test(heal.reason)));
    }
    const bad = tried.filter((a) => !a.ok).slice(0, 3).map((a) =>
      `<li>${esc(a.sentence || a.remedy || "a repair")} — `
      + `${esc(String(a.error || "failed").slice(0, 120))}</li>`);
    if (bad.length) {
      rows.push(diagRow("Repairs that failed", `<ul>${bad.join("")}</ul>`, true));
    }
  }
  // Checks that run and are not on the tab. One line per trialled check,
  // because "14 rows over 9 days, 11 agree with what was filed" is the
  // number somebody reads before moving an id out of `checks.SHADOW` —
  // which is a code change, deliberately: a producer that promoted itself
  // on a threshold would be a threshold nobody can see deciding what a
  // house is told.
  const sh = d.shadow_checks || {};
  const trialled = sh.checks || [];
  if (trialled.length || (sh.total || 0) > 0) {
    const byCheck = sh.by_check || {};
    const items = Object.keys(byCheck).sort().map((id) => {
      const r = byCheck[id] || {};
      if (!r.rows) {
        return `<li><b>${esc(id)}</b> — nothing found yet</li>`;
      }
      return `<li><b>${esc(id)}</b> — ${r.rows} row`
        + `${r.rows === 1 ? "" : "s"} over ${r.days} day`
        + `${r.days === 1 ? "" : "s"}, ${r.agreed} agree with what was `
        + "filed</li>";
    });
    rows.push(diagRow("Checks in shadow", `<ul>${items.join("")}</ul>`));
  }
  // What brAIn has measured about the house, one line each. The payload has
  // carried these since the stores existed and the dialog drew none of them,
  // so a rhythm that never gathered enough days and one that had were the
  // same silence — and this is the screen somebody is on when they are
  // asking exactly that. The Knowledge tab is where the numbers are; these
  // are here because a bug report has to carry them too.
  const rhythm = d.rhythm || {};
  if (rhythm.days != null || rhythm.wake || rhythm.settle) {
    const say = (part) => (part && part.at)
      ? `${esc(part.at)} ±${Math.round(Number(part.spread_min) || 0)}m` : "not yet";
    rows.push(diagRow("When the house wakes",
      `weekdays ${say((rhythm.weekday || {}).wakes || rhythm.wake)}, `
      + `settles ${say((rhythm.weekday || {}).settles || rhythm.settle)}`
      + (rhythm.days != null ? ` — ${rhythm.days} days recorded` : "")));
  }
  const th = d.thermal || {};
  if (th.measured != null || th.built_at) {
    // With no outdoor reference there is no model at all, and that is a
    // sentence rather than a zero: "no climate findings" and "no room could
    // be measured against anything" look identical from everywhere else.
    rows.push(diagRow("How rooms hold heat",
      th.reason ? esc(th.reason)
        // Pluralised on the count it sits beside: "1 of 8 rooms", never
        // "1 of 8 room".
        : `${th.measured ?? 0} of ${th.asked ?? "?"} room`
          + `${(th.asked ?? th.measured) === 1 ? "" : "s"} measured`
          + (th.outdoor ? ` against ${esc(th.outdoor)}` : "")
          + (th.built_at
              ? ` — ${timeAgo(new Date(th.built_at * 1000).toISOString())}` : ""),
      !!th.reason));
  }
  const cl = d.closures || {};
  if (cl.measured != null || cl.built_at) {
    rows.push(diagRow("Doors and windows",
      `${cl.measured ?? 0} of ${cl.asked ?? "?"} watched`
      + (cl.built_at
          ? ` — ${timeAgo(new Date(cl.built_at * 1000).toISOString())}`
          : " — no pass has run")));
  }
  const ap = d.appliances || {};
  if (ap.measured != null || ap.built_at || ap.error) {
    rows.push(diagRow("Machines",
      ap.error ? esc(ap.error)
        : `${ap.measured ?? 0} of ${ap.asked ?? "?"} power sensors have a shape`
          + (ap.chore_capable != null
              ? `, ${ap.chore_capable} look like a chore` : "")
          + (ap.built_at
              ? ` — ${timeAgo(new Date(ap.built_at * 1000).toISOString())}` : ""),
      !!ap.error));
  }
  const rt = d.routines || {};
  if (rt.presses != null || rt.would_propose != null) {
    rows.push(diagRow("Habits",
      `${rt.presses ?? 0} press${(rt.presses === 1) ? "" : "es"} kept across `
      + `${rt.entities ?? 0} entities, ${rt.would_propose ?? 0} look like a habit`
      + (rt.automated_keys != null
          ? `, ${rt.automated_keys} already automated` : "")));
  }
  // Why somebody does what they do, and — far more often — why brAIn is
  // not currently asking. A feature that asks one question a day is quiet
  // nearly all the time, so "nothing it cannot account for", "asked
  // already this morning" and "the loop died in March" are three silences
  // that look identical from every other surface, and this is the only
  // place they are told apart.
  const cu = d.curiosity || {};
  if (cu.error) {
    rows.push(diagRow("Why you did something", esc(cu.error), true));
  } else if (cu.enabled != null) {
    const b = cu.budget || {};
    const counts = cu.counts || {};
    const ev = cu.evidence || {};
    const parts = [];
    if (!cu.enabled) {
      parts.push("<b>off</b> — turn on <i>Ask why you did something</i> in "
        + "the add-on configuration");
    } else if (ev.state === "collecting") {
      // A floor's cost is silence. Say which floor.
      parts.push(`watching — ${esc(ev.note || "not enough days yet")}`);
    } else {
      parts.push(`${cu.manual_actions ?? 0} manual action`
        + `${cu.manual_actions === 1 ? "" : "s"} kept, `
        + `${cu.curious_total ?? 0} brAIn cannot account for`);
      parts.push(`asked ${b.day ?? 0} of ${b.per_day ?? 1} today, `
        + `${b.week ?? 0} of ${b.per_week ?? 3} this week`);
      if (cu.holding) parts.push(esc(cu.holding));
      parts.push(`worked out ${counts.explained ?? 0}, asked you about `
        + `${counts.guessed ?? 0}, could not tell ${counts.unknown ?? 0}`);
    }
    const queue = (cu.curious_about || []).slice(0, 5).map((c) =>
      `<li>${esc(c.why || c.subject || "")}`
      + (c.skip ? ` <i>— ${esc(c.skip)}</i>` : "") + "</li>");
    const learned = (cu.learned || []).slice(0, 4).map((r) =>
      `<li><b>${esc(r.name || r.subject || "")}</b> — ${esc(r.because || "")}`
      + (r.filed ? ` <i>(${esc(r.filed)})</i>` : "") + "</li>");
    rows.push(diagRow("Why you did something",
      `<ul>${parts.map((t) => `<li>${t}</li>`).join("")}</ul>`
      + (queue.length ? `<p class="hint">Curious about:</p><ul>${queue.join("")}</ul>` : "")
      + (learned.length ? `<p class="hint">Lately:</p><ul>${learned.join("")}</ul>` : "")));
  }
  // The roll-call, because "the consolidator is not running" is invisible
  // from every other line in this dialog — and an EMPTY roll-call is /proc
  // unreadable, which is a different claim from seven dead daemons.
  // `{name: {running: bool, …}}`. Each value is an OBJECT, so the truthiness
  // of the value says nothing — every daemon would read as running, which is
  // exactly the reassuring lie this row exists to stop.
  const daemons = d.daemons;
  const names = (daemons && typeof daemons === "object" && !Array.isArray(daemons))
    ? Object.keys(daemons) : [];
  if (names.length) {
    const up = (n) => !!(daemons[n] || {}).running;
    // `not_used` is the server's reason a stopped one was never asked for
    // (`health.not_used_reason`) — "not used (fast mode)" rather than a
    // bare "not running" beside a verdict that says everything is fine.
    const items = names.sort().map((n) => {
      const row = daemons[n] || {};
      const said = up(n) ? "running"
        : (row.not_used ? String(row.not_used) : "not running");
      return `<li><b>${esc(n)}</b> — ${esc(said)}</li>`;
    });
    // The roll-call is DESCRIPTIVE — some of these are correctly absent
    // because the option behind them is off — so a stopped one is not
    // painted as a fault here. `health.py` is what interprets it against
    // the options, and its verdict is the row at the top of this dialog.
    rows.push(diagRow("Background daemons", `<ul>${items.join("")}</ul>`));
  } else if (daemons) {
    // An empty roll-call is /proc unreadable, not seven dead daemons.
    rows.push(diagRow("Background daemons", "could not read /proc"));
  }
  rows.push(...actingDiagRows(d));
  if (failures.length) {
    const items = failures.slice(0, 5).map((f) =>
      `<li><b>${esc(f.source || "?")}</b> · ${esc(f.outcome || "?")}`
      + (f.error ? ` — ${esc(String(f.error).slice(0, 160))}` : "") + "</li>");
    rows.push(diagRow("Recent failures", `<ul>${items.join("")}</ul>`, true));
  }
  $("#diagBody").innerHTML = rows.join("");
}

async function loadDiagnostics() {
  $("#diagBody").textContent = "Loading…";
  try {
    renderDiagnostics(await api("api/diagnostics"));
  } catch (e) {
    diagPayload = null;
    $("#diagBody").textContent = "Could not read diagnostics: " + e.message;
  }
  // The nightly pass may be running right now, in which case the button
  // has to say so rather than offer a press that answers 409.
  measureState(false);
  curiousState(false);
}

// Export report (Share) is the one export. With problem files ticked under
// Developer it copies exactly those, as one text; with none ticked it writes
// a report file first and copies THAT: the same single text file a failure
// would have written (with the full diagnostics appended), so what lands in
// an issue is one readable file rather than raw JSON, and the same file
// `brain report` produces. It replaced four buttons (Copy selected, Copy
// all, Write a report now, Copy for a bug report) that were four spellings
// of one wish. `copyOrSelect` carries the textarea fallback: an ingress
// iframe may be refused the clipboard outright, and there is no way to ask
// in advance.
$("#diagCopy").addEventListener("click", async () => {
  const btn = $("#diagCopy");
  const ticked = [...document.querySelectorAll("#probBody .probcheck:checked")]
    .map((box) => box.value);
  if (ticked.length) {
    btn.disabled = true;
    try { await copyReports(ticked); } finally { btn.disabled = false; }
    return;
  }
  btn.disabled = true;
  try {
    const made = await api("api/reports/run", { method: "POST", body: "{}" });
    const text = await reportText(made.name);
    await copyOrSelect(text, `Report copied — ${made.name} is under `
                             + `/share/brain/reports too`);
    loadReports();
  } catch (e) {
    // The report could not be written (no /share, or the write failed):
    // the raw payload is still the honest thing to hand over.
    if (!diagPayload) { toast("Could not write a report: " + e.message); return; }
    await copyOrSelect(JSON.stringify(diagPayload, null, 2),
                       "Report could not be written; diagnostics copied instead");
  } finally {
    btn.disabled = false;
  }
});
$("#diagRefresh").addEventListener("click", () => {
  advancedLoaded = false;
  loadAdvanced();
});

// A measurement pass, asked for rather than waited for. Every store on the
// rows above is written by one nightly pass, so a fix to any of them was
// invisible for up to a day and could not be checked at all — the route to
// start one has existed since the loop did and had no caller anywhere, which
// is the "a button that exists only in prose" rule with the button missing
// instead of the prose. The pass takes minutes, so this starts it and reads
// the outcome back off `/api/baselines` rather than holding a request open.
let measurePoll = null;

async function measureState(poll) {
  try {
    const d = await api("api/baselines");
    const btn = $("#diagMeasure");
    btn.disabled = !!d.running;
    btn.textContent = d.running ? "Running…" : "Run";
    clearTimeout(measurePoll);
    measurePoll = d.running && poll
      ? setTimeout(() => measureState(true), 5000) : null;
    if (!d.running && poll) {
      // Finished: the rows above are what the press was about, so they
      // have to be the thing that changes on screen when it lands.
      loadDiagnostics();
      loadDiagMeasures();
      const last = d.last || {};
      toast(last.error
        ? `Measured, with something missing — ${last.error}`
        : `Measured: ${last.measured || 0} sensors, ${last.closures || 0} doors `
          + `and windows, ${last.appliances || 0} machines, ${last.rooms || 0} rooms`);
    }
  } catch (e) {
    clearTimeout(measurePoll);
    measurePoll = null;
    $("#diagMeasure").disabled = false;
  }
}

$("#diagMeasure").addEventListener("click", async () => {
  const btn = $("#diagMeasure");
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    // A 409 means one is already going, which is an answer rather than an
    // error: both presses are watching the same pass.
    await api("api/baselines/run", { method: "POST" });
    toast("Measuring — this reads a month of statistics and takes a few minutes");
  } catch (e) {
    toast(e.message);
  }
  measureState(true);
});

// One press, and it spends a Claude run — which is why it says so on the
// button rather than in a tooltip, and why it is worded as a question
// rather than as a refresh. It starts the run and reads the outcome back
// off `/api/curiosity`, `diagMeasure`'s clock: a run is minutes of model
// time and ingress will not hold a request open for it.
//
// It carries its own in-flight state rather than sharing the measure
// button's, BRUH Print's rule about a pair of controls: a button that
// greys itself out while the other one runs is a pair nobody can tell
// apart.
let curiousPoll = null;

async function curiousState(poll) {
  const btn = $("#diagCurious");
  if (!btn) return;
  try {
    const d = await api("api/curiosity");
    btn.disabled = !!d.running;
    btn.textContent = d.running ? "Running…" : "Run";
    // Renders only while there is something to ask about — the `Forget`
    // rule: a button that cannot do anything is a control asking to be
    // understood. `curious_total` counts the eligible ones, held or not,
    // because the press deliberately ignores the daily budget.
    btn.hidden = !(d.enabled && (d.curious_total || 0) > 0);
    const row = btn.closest(".row");
    if (row) {
      row.hidden = btn.hidden;
      const intro = row.previousElementSibling;
      const head = intro && intro.previousElementSibling;
      if (intro) intro.hidden = btn.hidden;
      if (head) head.hidden = btn.hidden;
    }
    clearTimeout(curiousPoll);
    curiousPoll = d.running && poll
      ? setTimeout(() => curiousState(true), 5000) : null;
    if (!d.running && poll) {
      // The rows above are what the press was about, so they are what has
      // to change on screen when it lands.
      loadDiagnostics();
      const last = (d.learned || [])[0] || {};
      toast(last.because
        ? `${last.status === "explained" ? "Worked it out" :
            last.status === "guessed" ? "A guess, and a question for you" :
            "Could not tell"}: ${last.because}`
        : "Nothing came back — the add-on log says why");
    }
  } catch (e) {
    clearTimeout(curiousPoll);
    curiousPoll = null;
    btn.disabled = false;
  }
}

$("#diagCurious")?.addEventListener("click", async () => {
  const btn = $("#diagCurious");
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const r = await api("api/curiosity/ask", { method: "POST" });
    toast(r.why ? `Asking: ${r.why}` : "Asking — this takes a few minutes");
  } catch (e) {
    toast(e.message);
  }
  curiousState(true);
});

// ------------------------------------------------------------ problem reports
// One row per file under /share/brain/reports, newest first, with a
// checkbox so the two or three about the thing being reported can be
// copied as one text. Fetched when the dialog opens and on Refresh, never
// on a timer: nothing here changes unless something fails.
function reportRows(data) {
  const rows = data.reports || [];
  if (!rows.length) {
    return "<p class=\"hint tight probempty\">No problems recorded. When a run fails "
         + "or brAIn's health changes, one text file appears here.</p>";
  }
  return rows.map((r) => {
    const when = r.ts ? timeAgo(new Date(r.ts * 1000).toISOString()) : "";
    const count = r.count > 1 ? ` <span class="probcount">×${r.count}</span>` : "";
    return `<div class="prow" data-report="${esc(r.name)}">`
      + `<label class="probpick"><input type="checkbox" class="probcheck" `
      + `value="${esc(r.name)}" aria-label="Select ${esc(r.name)}">`
      + `<span class="probwhen">${esc(when)}</span>`
      + `<span class="probhead">${esc(r.headline || r.name)}${count}</span></label>`
      + `<button class="btn tiny probdel" data-prob-del="${esc(r.name)}" `
      + `aria-label="Delete ${esc(r.name)}">Delete</button>`
      + `</div>`;
  }).join("");
}

async function loadReports() {
  const box = $("#probBody");
  if (!box) return;
  box.textContent = "Loading…";
  try {
    box.innerHTML = reportRows(await api("api/reports"));
  } catch (e) {
    box.textContent = "Could not list problem reports: " + e.message;
  }
}

async function reportText(name) {
  const resp = await fetch(`api/reports/${encodeURIComponent(name)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.text();
}

async function copyReports(names) {
  if (!names.length) { toast("Nothing to copy"); return; }
  const resp = await fetch("api/reports/copy", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names }),
  });
  if (!resp.ok) { toast(`Could not read the reports (HTTP ${resp.status})`); return; }
  const text = await resp.text();
  await copyOrSelect(text, `${names.length} report${names.length === 1 ? "" : "s"} `
                           + "copied — paste into the issue");
}

$("#probBody").addEventListener("click", async (ev) => {
  const del = ev.target.closest("[data-prob-del]");
  if (!del) return;
  const name = del.dataset.probDel;
  try {
    await api(`api/reports/${encodeURIComponent(name)}`, { method: "DELETE" });
    del.closest(".prow")?.remove();
    if (!$("#probBody").querySelector(".prow")) loadReports();
  } catch (e) {
    toast("Could not delete: " + e.message);
  }
});

// ------------------------------------------------------------- captured runs
// The list under the capture switch: what has been recorded, and the three
// things a person may do with one. Fetched when the dialog opens and after
// every press, never on a timer — nothing here changes unless a card runs.
//
// View is deliberately the first control. Everything else about capture is
// designed so nothing leaves the add-on without a press, and a press you
// make without being able to read what you are sending is not consent.
function capRows(data) {
  const rows = data.captures || [];
  if (!data.enabled && !rows.length) {
    return "<p class=\"hint tight\">Nothing recorded. Switch capture on above "
         + "and the next card run writes the first one.</p>";
  }
  if (!rows.length) {
    return "<p class=\"hint tight\">Capture is on; the next card run writes "
         + "the first file. Nothing has run yet.</p>";
  }
  return rows.map((r) => {
    const when = r.captured_at
      ? timeAgo(new Date(r.captured_at * 1000).toISOString()) : "just now";
    const what = r.question
      ? `“${esc(r.question.slice(0, 70))}”`
      : esc(r.category || r.source || "a card");
    // The labels count is the number that says whether an entry is worth
    // contributing: a capture with no ending on it is a prompt and a reply
    // and nothing to score them against.
    const labels = r.labels
      ? `${r.labels} ending${r.labels === 1 ? "" : "s"} recorded`
      : "no endings yet";
    return `<div class="drow"><div class="dk">${esc(when)}</div>`
      + `<div class="dv">${what} — ${r.findings} finding`
      + `${r.findings === 1 ? "" : "s"}, ${esc(labels)}`
      + `<div class="row tight">`
      + `<button class="btn tiny" data-cap-view="${esc(r.run_id)}">View</button>`
      + `<button class="btn tiny" data-cap-export="${esc(r.run_id)}">Export</button>`
      + `<button class="btn tiny" data-cap-del="${esc(r.run_id)}">Delete</button>`
      + `</div></div></div>`;
  }).join("");
}

async function loadCaptures() {
  const box = $("#capBody");
  if (!box) return;
  box.textContent = "Loading…";
  try {
    const data = await api("api/capture");
    $("#capMax").textContent = String(data.max_files || 50);
    box.innerHTML = capRows(data);
  } catch (e) {
    box.textContent = "Could not list captured runs: " + e.message;
  }
}

// The same fallback `diagCopy` uses, and for the same reason: an ingress
// iframe may be refused the clipboard outright, and a failure that only
// says so leaves the text nowhere a person can reach it.
async function copyOrSelect(text, okMessage) {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMessage);
    return;
  } catch (e) { /* fall through to the textarea */ }
  const box = document.createElement("textarea");
  box.value = text;
  box.style.cssText = "position:fixed;left:0;top:0;width:100%;height:60vh;z-index:99";
  document.body.appendChild(box);
  box.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch (e2) { copied = false; }
  if (copied) { box.remove(); toast(okMessage); return; }
  toast("This browser will not let the panel copy — the text is selected, "
        + "press Ctrl/Cmd+C, then Esc");
  box.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") box.remove();
  });
  box.addEventListener("blur", () => box.remove());
}

// Delegated, because these rows are rebuilt on every load.
$("#capBody").addEventListener("click", async (ev) => {
  const view = ev.target.closest("[data-cap-view]");
  const exp = ev.target.closest("[data-cap-export]");
  const del = ev.target.closest("[data-cap-del]");
  try {
    if (view) {
      const id = view.getAttribute("data-cap-view");
      const entry = await api("api/capture/" + encodeURIComponent(id));
      const text = JSON.stringify(entry, null, 2);
      const pre = document.createElement("pre");
      pre.className = "capview";
      pre.textContent = text;
      const holder = view.closest(".drow");
      const already = holder.querySelector(".capview");
      if (already) { already.remove(); return; }
      holder.appendChild(pre);
      const copy = document.createElement("button");
      copy.className = "btn tiny";
      copy.textContent = "Copy this run";
      copy.addEventListener("click", () => copyOrSelect(text, "Capture copied"));
      holder.appendChild(copy);
      return;
    }
    if (exp) {
      const id = exp.getAttribute("data-cap-export");
      const out = await api("api/capture/" + encodeURIComponent(id) + "/export",
                            { method: "POST" });
      toast("Exported to " + out.path);
      return;
    }
    if (del) {
      const id = del.getAttribute("data-cap-del");
      await api("api/capture/" + encodeURIComponent(id), { method: "DELETE" });
      loadCaptures();
    }
  } catch (e) {
    toast("That did not work: " + e.message);
  }
});

// ------------------------------------------------------------- deep check
// `brain doctor --deep` from the dialog. Fetched when pressed and while a
// run is in flight, and NEVER on a timer once it is done: a deep run is a
// handful of Claude turns, so a poll behind a closed dialog would be a
// question nobody asked with a bill attached to it.
const DEEP_MARK = { ok: "✓", failed: "✗", skipped: "–" };
let deepPoll = null;

function renderDeep(d) {
  const stages = d.running ? (d.stages || []) : ((d.last || {}).stages || d.stages || []);
  const body = $("#deepBody");
  body.hidden = !stages.length && !d.running;
  const rows = stages.map((s) => diagRow(
    `${DEEP_MARK[s.state] || "·"} ${esc(s.title || s.name)}`,
    `${esc(s.sentence || "")}`
    + (s.detail ? `<div class="hint tight">${esc(s.detail)}</div>` : ""),
    s.state === "failed"));
  if (d.running) {
    // The catalog is what lets a stage that has not started yet be a row
    // rather than nothing: a list that grows from empty reads as a run
    // that is stuck on whatever it is doing.
    (d.stage_catalog || []).slice(stages.length).forEach((s) =>
      rows.push(diagRow(`· ${esc(s.title)}`,
        `<span class="hint">${esc(s.proves)}</span>`)));
  }
  body.innerHTML = rows.join("");
  const last = d.last || {};
  const c = last.counts || {};
  $("#deepLast").textContent = d.running
    ? "Running — this takes a few minutes."
    : (last.finished_at
      ? `Last run ${timeAgo(new Date(last.finished_at * 1000).toISOString())}: `
        + `${c.ok || 0} passed, ${c.failed || 0} failed, ${c.skipped || 0} skipped`
      : "Not run on this install yet.");
  $("#deepRun").disabled = !!d.running;
}

function stopDeepPoll() {
  clearTimeout(deepPoll);
  deepPoll = null;
}

async function loadDeep(poll) {
  try {
    const d = await api("api/doctor/deep");
    renderDeep(d);
    if (d.running && poll) {
      clearTimeout(deepPoll);
      deepPoll = setTimeout(() => loadDeep(true), 3000);
    } else {
      clearTimeout(deepPoll);
      deepPoll = null;
    }
  } catch (e) {
    $("#deepLast").textContent = "Could not read the deep check: " + e.message;
  }
}

$("#deepRun").addEventListener("click", async () => {
  $("#deepRun").disabled = true;
  try {
    // A 409 means one is already going — which is an answer, not an error:
    // both presses are watching the same run.
    await api("api/doctor/deep", { method: "POST" });
    toast("Deep check started — it spends a few Claude turns and makes "
      + "one reversible change to a test helper it creates");
  } catch (e) {
    toast(e.message);
  }
  loadDeep(true);
});

// -------------------------------------------------------------- rehearsal
// The consent step is the server's: a POST with no consent answers 428 with
// the exact list of what would be created, and this renders that list as
// the question. Nothing is created until the second POST.
let rehearsePoll = null;

function renderRehearsal(d) {
  const last = d.last || {};
  const body = $("#rehearseBody");
  const c = last.checks || {};
  const a = last.analyst || {};
  const clean = last.cleanup || {};
  const rows = [];
  if (last.finished_at) {
    rows.push(diagRow("Checks",
      `${c.found || 0} of ${c.planted || 0} planted defects found`
      + (c.extra ? `, ${c.extra} reported that were not planted` : ""),
      (c.found || 0) < (c.planted || 0) || !!c.extra));
    (c.rows || []).forEach((r) => rows.push(diagRow(
      r.id,
      `${esc(r.verdict)} <span class="hint">${esc(r.check || "")}</span>`,
      r.verdict === "missed" || r.verdict === "false positive", true)));
    rows.push(diagRow("Analyst", a.ran
      ? `found ${a.found || 0} of ${a.planted || 0}`
        + ` — recall ${Math.round((a.recall || 0) * 100)}%,`
        + ` precision ${Math.round((a.precision || 0) * 100)}%`
        + ` on ${esc(a.model || "the default model")}`
        // Which of the two paths produced the number. A card slides from
        // searching to the snapshot when the search runs out of room, so
        // a score with no note on how it was reached is one nobody can
        // compare against last month's.
        + (a.fallback
          ? ` <span class="hint">via the snapshot path — the search run `
            + `did not land${a.searched_error
              ? ` (${esc(a.searched_error)})` : ""}</span>`
          : "")
      : `did not run — ${esc(a.error || "unknown")}`, !a.ran));
    // What an earlier run left behind, and what this one had to take out
    // before it could start. Silent on a clean house — but never silent
    // when it removed something, because that line is the only evidence
    // a previous rehearsal failed to clean up.
    const swept = last.swept || {};
    if (swept.sentence) {
      rows.push(diagRow("Before starting", esc(swept.sentence), !swept.ran));
    }
    rows.push(diagRow("Cleanup", esc(clean.sentence || "?"), !clean.ok));
    // A sweep that ran afterwards is the newer claim about the house, and
    // it goes UNDER the cleanup rather than over it: the run's own failure
    // is the evidence a cleanup failed, and deleting it would leave the
    // record agreeing with itself about a problem that did happen.
    const cleared = last.cleared || {};
    if (cleared.at) {
      const took = (cleared.removed || []).length
        ? ` <span class="hint">took out ${esc((cleared.removed || []).join(", "))}</span>`
        : "";
      rows.push(diagRow("Cleared up since",
        (cleared.ok ? "nothing named brain_test_* is left"
          : "could not finish — " + esc((cleared.left || []).join(", ") || "?"))
        + took,
        !cleared.ok));
    }
    if (last.error) rows.push(diagRow("Error", esc(last.error), true));
  }
  body.innerHTML = rows.join("");
  body.hidden = !rows.length;
  const step = (d.progress || {}).step;
  const busy = !!(d.running || d.sweeping);
  $("#rehearseLast").textContent = d.sweeping
    ? "Clearing up…"
    : (d.running
      ? `Rehearsing — ${step || "starting"}…`
      : (last.finished_at
        ? `Last rehearsal ${timeAgo(new Date(last.finished_at * 1000).toISOString())}`
        : "Not rehearsed on this install yet."));
  $("#rehearseRun").disabled = busy;
  // The button exists only while there is something for it to take out —
  // `leftovers` is the server's derivation, so this and the fault row in
  // the report cannot disagree about whether the house is clean.
  const left = d.leftovers || [];
  const sweep = $("#rehearseSweep");
  sweep.hidden = !left.length;
  sweep.disabled = busy;
  sweep.title = left.length
    ? "Still in the house: " + left.join(", ")
    : "";
}

async function loadRehearsal(poll) {
  try {
    const d = await api("api/doctor/rehearse");
    renderRehearsal(d);
    clearTimeout(rehearsePoll);
    rehearsePoll = (d.running || d.sweeping) && poll
      ? setTimeout(() => loadRehearsal(true), 3000) : null;
  } catch (e) {
    $("#rehearseLast").textContent = "Could not read the rehearsal: " + e.message;
  }
}

function stopRehearsePoll() {
  clearTimeout(rehearsePoll);
  rehearsePoll = null;
}

$("#rehearseRun").addEventListener("click", async () => {
  // The offer comes off the GET rather than off a POST this expects to
  // fail: the 428 is the API's contract for every other caller, and a
  // button that has to provoke an error to read a list is a button that
  // cannot tell a refusal from a network problem.
  let offer;
  try {
    offer = await api("api/doctor/rehearse");
  } catch (e) {
    toast(e.message);
    return;
  }
  if (offer.refused) { toast(offer.refused); return; }
  const lines = (offer.plan || []).map(
    (r) => `• ${r.id}\n    ${r.what}`).join("\n");
  const cannot = (offer.not_rehearsable || []).map(
    (r) => `• ${r.check} — ${r.why}`).join("\n");
  if (!window.confirm(
    "A rehearsal creates these in your Home Assistant, runs the checks and "
    + "the analyst against them, then removes them:\n\n" + lines
    + (cannot ? "\n\nIt cannot rehearse these in one pass:\n" + cannot : "")
    + "\n\nGo ahead?")) return;
  $("#rehearseRun").disabled = true;
  try {
    await api("api/doctor/rehearse",
      { method: "POST", body: JSON.stringify({ consent: true }) });
    toast("Rehearsal started — it writes to automations.yaml and takes it back out");
  } catch (e) {
    toast(e.message);
  }
  loadRehearsal(true);
});

// No confirmation, because nothing is created: this removes what the
// rehearsal's own leftovers scan already sees under `brain_test_*`, which
// is brAIn's own litter and the thing `brain doctor` sent you here about.
// Asking "are you sure you want to delete the thing you were just warned
// about" is the offer nobody can answer usefully.
$("#rehearseSweep").addEventListener("click", async () => {
  $("#rehearseSweep").disabled = true;
  try {
    await api("api/doctor/rehearse/sweep", { method: "POST" });
    toast("Clearing up what the last rehearsal left behind…");
  } catch (e) {
    toast(e.message);
  }
  loadRehearsal(true);
});

// ------------------------------------------------------- Claude account
// The panel could sign you in and could never show you what it had signed
// you in with, nor sign you out, nor share that login with the other BRUH
// add-ons — all three of which the terminal could do. So a login that died
// was answerable only from a command line, and `ha login --status` reported
// a perfectly good panel sign-in as "not set up" because it only ever read
// its own file.

function fmtSaved(epoch) {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  // No seconds: "3:52:44 PM" is precision nobody reads a sign-in date for.
  return isNaN(d.getTime()) ? "" : d.toLocaleString([], {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit" });
}

// Where the credential in use came from. `source` is the field that makes a
// confusing report diagnosable — "the terminal works and the panel doesn't"
// is two stores answering differently, and nothing used to name them.
const AUTH_SOURCE = {
  local: ["Signed in here", "Stored by this panel, in the add-on's own storage."],
  shared: ["The shared login", "Published to /config for every BRUH add-on to read."],
  cli: ["Claude Code's own login", "From the panel's account sign-in, or `claude auth login` / `ha login` in a terminal."],
};

function renderAuthBox(a) {
  authState = a;
  const rows = [];
  const c = a.auth_check || {};
  if (!a.authenticated) {
    rows.push('<p class="authbad"><b>Not connected.</b> brAIn cannot analyze anything, '
      + "answer questions, or run the chat until it has a Claude credential.</p>");
  } else {
    // The answer first, in one line: signed in, and when a real Claude
    // turn last said so. Where the credential came from and the three
    // stores are the evidence, so they sit behind Details.
    const checked = c.checked_at ? ` · checked ${esc(fmtClock(c.checked_at))}` : "";
    rows.push(`<p class="authline"><b>Signed in</b>${checked}</p>`);
  }

  // The verdict, in its own words. A credential that is *shaped* right is
  // not one that works, and the only liveness signal a pasted token has is
  // a 401 when something uses it — so what a real `claude -p` turn last
  // answered is the only honest line here.
  const verdict = {
    ok: ["ok", "Verified with Claude."],
    failed: ["bad", "Claude rejected it: " + (c.error || "no reason given")],
    checking: ["busy", "Verifying with Claude…"],
    unchecked: ["", "Not verified yet. Recheck asks Claude now."],
  }[c.state] || ["", "Not verified yet."];
  rows.push(`<p class="authverdict ${verdict[0]}">${esc(verdict[1])}</p>`);

  // Every store, not only the one that answered — the same reason
  // `ha login --status` reports three lines. A panel that can see only its
  // own file says "not signed in" to somebody who is.
  const st = a.stores || {};
  const store = (on, name, note) =>
    `<li class="${on ? "on" : "off"}">${on ? "✓" : "—"} ${esc(name)}`
    + (note ? ` <span class="subtext">${esc(note)}</span>` : "") + "</li>";
  const detail = [];
  if (a.authenticated) {
    const [where, why] = AUTH_SOURCE[a.source] || ["Signed in", ""];
    const kind = a.type === "api_key" ? "an Anthropic API key"
      : a.type === "cli_login" ? "a Claude Code session login"
      : "a Claude subscription token";
    const saved = fmtSaved(a.saved_at);
    detail.push(`<p><b>${esc(where)}</b>, using ${esc(kind)}.`
      + (saved ? ` Saved ${esc(saved)}.` : "")
      + `<br><span class="subtext">${esc(why)}</span></p>`);
  }
  detail.push("<ul class=\"authstores\">"
    + store(st.local && st.local.present, "This panel's own store", "/data/secrets")
    + store(st.cli && st.cli.present, "Claude Code's login",
            (st.cli && st.cli.present) ? "live (it refreshes itself)" : "none, or expired")
    + store(st.shared && st.shared.present, "Shared with other add-ons", "/config/.brain/secrets")
    + "</ul>");
  const wasOpen = !!document.querySelector("#authBody .authdetails[open]");
  rows.push(`<details class="authdetails"${wasOpen ? " open" : ""}>`
    + `<summary>Details</summary>${detail.join("")}</details>`);
  $("#authBody").innerHTML = rows.join("");

  // -- the sharing half: one switch, and a line that changes with it --
  const shared = !!(st.shared && st.shared.present);
  const tog = $("#authShareTog");
  tog.checked = shared;
  tog.disabled = !shared && !a.can_share;
  $("#authShareNote").textContent = shared
    ? "Other BRUH add-ons are using this login. The token stays valid until you "
      + "revoke it at claude.ai."
    : a.can_share
      ? "One sign-in for the whole family of add-ons."
      // The refusal that has to be a sentence: a Claude Code session token
      // is live, useful, and unshareable, and a switch that failed on press
      // would read as a broken feature rather than as a real distinction.
      : a.authenticated
        ? "This is Claude Code's own session login, which refreshes itself and cannot "
          + "be shared. Sign in again with a token to share one."
        : "Sign in first.";
  $("#authSignout").classList.toggle("hidden", !a.authenticated);
}

let authState = null;

async function loadAuth() {
  $("#authBody").textContent = "Loading…";
  try {
    renderAuthBox(await api("api/auth"));
  } catch (e) {
    authState = null;
    $("#authBody").textContent = "Could not read the credential state: " + e.message;
  }
}

$("#authSignin").addEventListener("click", () => {
  closeBox("#setModal");
  openSignIn();
});

$("#authRecheck").addEventListener("click", async () => {
  try {
    await api("api/auth/recheck", { method: "POST" });
    toast("Asking Claude…");
    // The check is a real run and takes a moment; the verdict lands on the
    // status poll, so read it back rather than claiming an answer we do not
    // have yet.
    setTimeout(() => { loadAuth(); refreshStatus().catch(() => {}); }, 2500);
  } catch (e) { toast(e.message); }
});

$("#authShareTog").addEventListener("change", async () => {
  const tog = $("#authShareTog");
  const on = tog.checked;
  tog.disabled = true;
  try {
    renderAuthBox(await api(on ? "api/auth/share" : "api/auth/unshare", { method: "POST" }));
    toast(on ? "Shared — other BRUH add-ons will pick this login up" : "Stopped sharing");
  } catch (e) {
    tog.checked = !on;
    tog.disabled = false;
    toast(e.message);
  }
});

// Signing out while a shared copy exists and NOT removing it is a sign-out
// that does nothing: the server reads that file two branches below its own,
// so the next request reports you signed in again. The box is ticked and
// the sentence says what each choice leaves behind, rather than the panel
// deciding on somebody's behalf about the one file other add-ons read.
$("#authSignout").addEventListener("click", async () => {
  const shared = !!(authState && authState.stores
    && authState.stores.shared && authState.stores.shared.present);
  const msg = shared
    ? "Sign out of Claude?\n\nA copy of this login is shared with the other BRUH "
      + "add-ons. Press OK to remove that too (otherwise brAIn will simply read it "
      + "back and you will still be signed in).\n\nThe token stays valid at "
      + "claude.ai either way — revoke it there to end it for good."
    : "Sign out of Claude?\n\nThe token stays valid at claude.ai — revoke it there "
      + "to end it for good.";
  if (!confirm(msg)) return;
  try {
    await api("api/auth/logout", { method: "POST", body: JSON.stringify({ shared }) });
    closeBox("#setModal");
    state.showSignIn = false;
    await refreshStatus();
    render();
    toast("Signed out");
  } catch (e) { toast(e.message); }
});

// Opening the sign-in screen from anywhere: the chip, ⚙, or the gate.
//
// Through `renderIfChanged`, never a bare `renderAuth()`. A direct render
// paints the screen but leaves `lastRenderKey` holding the state from
// BEFORE it opened — so the poll that follows the sign-in computes a key
// equal to the stale one, skips the render, and the screen stays up over a
// credential that has just been accepted. The flag is in the key precisely
// so this bookkeeping is the render's job and not each caller's.
function openSignIn() {
  state.showSignIn = true;
  switchView("findings");
  resetSetupUI();
  renderIfChanged();
  window.scrollTo(0, 0);
}

$("#setupBack").addEventListener("click", async () => {
  state.showSignIn = false;
  // Same reason as openSignIn: the key has to move with the flag, or the
  // next poll reads a state the screen is no longer in.
  renderIfChanged();
  await refreshStatus().catch(() => {});
});

// The chip renders only for trouble (see renderAuth), so a press on it is
// always somebody answering that trouble.
$("#authChip").addEventListener("click", openSignIn);

$("#setEnabled").addEventListener("change", () =>
  saveSettings({ auto_enabled: $("#setEnabled").checked }));
// Switching it on records nothing that has already happened: the next card
// run is the first one captured, so the list is refreshed rather than
// expected to change.
$("#setCapture").addEventListener("change", async () => {
  await saveSettings({ capture: $("#setCapture").checked });
  loadCaptures();
});
$("#setPlan").addEventListener("change", () =>
  saveSettings({ plan: $("#setPlan").value }));
$("#setGatherMode").addEventListener("change", () =>
  saveSettings({ gather_mode: $("#setGatherMode").value }));
// A card's foot reads this back as either a countdown or a hold, so the
// status poll has to be told: switching to "always" clears every hold and
// leaving it on "changed" is what puts them there.
$("#setRefreshMode").addEventListener("change", async () => {
  await saveSettings({ refresh_mode: $("#setRefreshMode").value });
  await refreshStatus();
  render();
});
// Applies to the next switch rather than immediately: lowering it does not
// go round shutting conversations down, it means the next one you open
// closes the oldest idle one to make room.
$("#setChatSessions").addEventListener("change", () =>
  saveSettings({ chat_max_sessions: Number($("#setChatSessions").value) }));
// One switch with two doors: saving it writes the add-on's own
// `dangerously_skip_permissions` option, so the Configuration tab moves with
// it, and the server republishes it to the file a terminal session reads
// when it starts. The chat picks it up on its next message. The toast says
// what changed and what did NOT: a terminal session already open keeps the
// setting it started with, in both directions, and "off" is the direction
// where saying otherwise would be a lie about something still acting.
function skipPermsToast(on, data) {
  const parts = [on
    ? "On — new terminal sessions and the chat's next message act without asking."
    : "Off — new terminal sessions and the chat's next message ask first."];
  const stale = skipPermsStale(data);
  if (stale) parts.push(stale);
  else parts.push("A chat answer already being written finishes first.");
  if ((data.saved_locally || []).includes("dangerously_skip_permissions")) {
    parts.push("Saved in brAIn only: the add-on's Configuration tab could not be updated.");
  }
  return parts.join(" ");
}

$("#setSkipPerms").addEventListener("change", async () => {
  const box = $("#setSkipPerms");
  const on = box.checked;
  const data = await saveSettings({ dangerously_skip_permissions: on },
    (saved) => skipPermsToast(on, saved));
  // A refused save leaves the switch where it was, and so does the box.
  if (!data) box.checked = !on;
});
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
  syncThinking(sel.value);
  saveSettings({ model: sel.value });
});
$("#setModelCustom").addEventListener("change", () =>
  saveSettings({ model: $("#setModelCustom").value.trim() }));
$("#setThinking").addEventListener("change", () =>
  saveSettings({ thinking: $("#setThinking").value }));
$("#setClose").addEventListener("click", () => closeBox("#setModal"));
$("#setModal").addEventListener("click", (ev) => {
  if (ev.target === $("#setModal")) closeBox("#setModal");
});

// ------------------------------------------------------------ refine modal
// Editing a card by saying what should be different. A card is a Claude run
// rendered once, so the only honest edit is another run — told the change,
// shown the card as it stands, and asked to keep everything else. What it
// was told stays on the card as standing feedback (the box is ticked by
// default), which is what stops the next scheduled run quietly undoing it;
// the list under the box is those, each with a ✕. This replaced "Give
// feedback", which was the same store behind a second dialog and only for
// recurring cards.

const refineState = { id: null, catInfo: null, insight: null };

// A few changes people actually ask for, one press into the box. They add
// to what is there rather than replacing it, so two can be combined.
const REFINE_IDEAS = [
  "Compare with last week",
  "Look further back",
  "Fewer numbers",
  "Just the chart",
  "Explain it more simply",
];

function fmtWhen(ts) {
  const d = new Date(ts * 1000);
  return isNaN(d.getTime()) ? "" :
    d.toLocaleString([], { month: "short", day: "numeric" });
}

async function renderRefineKept() {
  const wrapEl = $("#refineKeptWrap");
  const list = $("#refineKept");
  const id = refineState.id;
  let entries = [];
  try {
    entries = (await api(`api/insight/${id}/feedback`)).feedback || [];
  } catch (e) {
    entries = [];
  }
  if (refineState.id !== id) return;
  list.textContent = "";
  wrapEl.classList.toggle("hidden", !entries.length);
  entries.slice().reverse().forEach((f) => {
    const row = el("div", "fbrow");
    const txt = el("div", "fbtext");
    txt.appendChild(el("div", null, f.text));
    txt.appendChild(el("div", "when", fmtWhen(f.ts)));
    row.appendChild(txt);
    const del = el("button", "btn icon", "✕");
    tip(del, "Stop asking this of the card on future runs");
    del.addEventListener("click", async () => {
      try {
        await api(`api/insight/${id}/feedback/${f.ts}`, { method: "DELETE" });
        renderRefineKept();
      } catch (e) {
        toast(e.message);
      }
    });
    row.appendChild(del);
    list.appendChild(row);
  });
}

function openRefine(id, catInfo, insight) {
  refineState.id = id;
  refineState.catInfo = catInfo;
  refineState.insight = insight;
  const name = catInfo ? catInfo.title
    : ((insight && insight.title) || "this card");
  $("#refineTitle").textContent = `Ask about ${name}`;
  fillRefineMore(id, catInfo, insight);
  $("#refineText").value = "";
  $("#refineKeep").checked = true;
  const chips = $("#refineChips");
  chips.textContent = "";
  REFINE_IDEAS.forEach((idea) => {
    const chip = el("button", "refinechip", idea);
    chip.type = "button";
    chip.addEventListener("click", () => {
      const box = $("#refineText");
      const now = box.value.trim().replace(/[.;,]$/, "");
      box.value = now ? `${now}; ${idea.toLowerCase()}` : idea;
      box.focus();
    });
    chips.appendChild(chip);
  });
  // What the card was built from, so "what should change" has something
  // to be a change TO — the question for an asked card, the focus for a
  // recurring one. This is the one place an asked card's question is shown.
  const from = $("#refineFrom");
  from.textContent = "";
  const basis = insight && insight.question
    ? `“${insight.question}”`
    : (catInfo && catInfo.focus ? catInfo.focus : "");
  if (basis) {
    from.appendChild(el("b", null, insight && insight.question
      ? "You asked: " : "What it looks at: "));
    from.appendChild(document.createTextNode(basis));
  }
  from.classList.toggle("hidden", !basis);
  $("#refineKeptWrap").classList.add("hidden");
  openBox("#refineModal");
  setTimeout(() => $("#refineText").focus(), 50);
  renderRefineKept();
}

async function sendRefine() {
  const note = $("#refineText").value.trim();
  if (!note) { toast("Say what should change first"); return; }
  const btn = $("#refineGo");
  btn.disabled = true;
  try {
    await api(`api/insight/${refineState.id}/refine`, {
      method: "POST",
      body: JSON.stringify({ note, remember: $("#refineKeep").checked }),
    });
    closeBox("#refineModal");
    toast("Regenerating with your change — the old version stays in the "
      + "card's history");
    await refreshStatus();
    fastPoll();
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

$("#refineGo").addEventListener("click", sendRefine);
$("#refineText").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) sendRefine();
});
$("#refineCancel")?.addEventListener("click", () => closeBox("#refineModal"));
$("#refineChat")?.addEventListener("click", () => {
  const ins = refineState.insight;
  const name = (ins && ins.title) || (refineState.catInfo && refineState.catInfo.title)
    || "this report";
  const note = $("#refineText").value.trim();
  closeBox("#refineModal");
  seedAsk(`About my report “${name}”: ${note}`);
});

// The links under Ask: what a report's DEFINITION can change. A recurring
// card's schedule and prompt, an asked card's name or making it recurring,
// and turning what it found into an automation (drafted in the Ask tab,
// where a person reads it before it is sent).
function fillRefineMore(id, catInfo, insight) {
  const box = $("#refineMore");
  if (!box) return;
  box.textContent = "";
  const links = [];
  const link = (label, run) => {
    const a = el("a", "refinelink", label);
    a.href = "#";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      closeBox("#refineModal");
      run();
    });
    links.push(a);
  };
  if (catInfo) {
    link("Change its schedule and prompt",
      () => (catInfo.user ? openUserEdit(catInfo) : openEdit(catInfo)));
  } else if (insight) {
    link("Rename it", () => openNameEdit(insight));
    if (insight.category === "custom" && insight.question) {
      link("Make it recurring", () => openNewInsight({
        title: (insight.title || insight.question).slice(0, 60),
        icon: insight.icon || "✨",
        focus: "Answer this question about the home, keeping the analysis "
          + `fresh each run: "${insight.question}"`,
      }));
    }
  }
  const shown = (state.viewing[id] && state.viewing[id].data) || insight;
  if (shown) {
    cardAutomationItems(shown).forEach(([, label, , run]) => link(label, run));
  }
  links.forEach((a) => box.appendChild(a));
  box.hidden = !links.length;
}
$("#refineClose").addEventListener("click", () => closeBox("#refineModal"));
$("#refineModal").addEventListener("click", (ev) => {
  if (ev.target === $("#refineModal")) closeBox("#refineModal");
});

// ---------------------------------------------------------------- findings
// The findings store, as Today reads it. Memory is what is TRUE of this
// home, a hypothesis is what brAIn might have wrong about it, and a
// finding is what is BROKEN in it. The cards are drawn by Today's one
// card (`makeCase`); this is the fetch, the presses only a finding has,
// and the reason box every card shares.

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
// it. `settled` is the ledger and it is NOT a work list: settling writes the
// answer into memory and deletes the row, and memory is where that answer is
// read from afterwards. It is kept here for one press — "let brAIn raise it
// again" — and it is counted by no badge, because nothing on it is waiting.
function takeFindings(data) {
  state.findings = data.findings || [];
  state.hypotheses = data.hypotheses || [];
  state.settled = data.settled || [];
  // Deliberately NOT the badge. That counts CASES — the four stores, one
  // question — and `data.open` here is the findings store's own half, so
  // setting it from both would be two answers to "how much is waiting on
  // me" taking turns. `takeCases` owns it, and `syncFeed` is what every
  // press on this tab calls to keep it true.
}

// The badge count always comes from the server (findings_store owns what
// "unsettled" means) — deriving a second answer here is how the tab and the
// list end up disagreeing about how much is waiting.
function updateFindBadge(n) {
  const badge = $("#findBadge");
  if (!badge) return;
  badge.textContent = n ? String(n) : "";
  badge.classList.toggle("hidden", !n);
  const seg = $("#segNeedsCount");
  if (seg) { seg.textContent = n ? String(n) : ""; seg.hidden = !n; }
  // The line over the insight cards: the cards are what the tab opens on,
  // and a decision that only lived one press away would be one nobody saw.
  state.needsCount = n || 0;
  renderNeedsStrip();
}

function renderNeedsStrip() {
  const strip = $("#needsStrip");
  if (!strip) return;
  const n = state.needsCount || 0;
  strip.hidden = !n;
  if (!n) return;
  const cases = state.cases || [];
  const urgent = cases.filter((c) => c.urgent);
  strip.classList.toggle("urgent", urgent.length > 0);
  $("#needsStripCount").textContent =
    `${n} thing${n === 1 ? "" : "s"} need${n === 1 ? "s" : ""} you`;
  const lead = (urgent[0] || cases[0] || {}).claim;
  $("#needsStripSub").textContent = lead ? prettyText(lead) : "Problems, questions and suggestions to decide on";
}
$("#needsStrip")?.addEventListener("click", () => switchView("findings"));

// Every finding button goes through here: all six endpoints answer with the
// same {findings, hypotheses, open}, so there is one place that knows what
// to do with it. `note` is the homeowner's reason, sent with the endings
// that have somewhere to put it.
async function findAction(finding, verb, done, btns, note, extra) {
  btns.forEach((b) => { b.disabled = true; });
  const del = verb === "forget";
  // `extra` is for a field only one caller has: a resolution pressed in the
  // chat sends the step it named as the to-do item's `fix`, because what the
  // conversation worked out is a better instruction than what the check
  // could say without looking.
  const body = { ...(note ? { note } : {}), ...(extra || {}) };
  try {
    const data = await api(
      del ? `api/finding/${finding.ts}` : `api/finding/${finding.ts}/${verb}`,
      { method: del ? "DELETE" : "POST",
        ...(Object.keys(body).length ? { body: JSON.stringify(body) } : {}) });
    takeFindings(data);
    syncFeed();
    // Accepting one moves it to the other list, so that tab's count moves
    // with it. Every other verb answers without these keys and leaves the
    // to-do list exactly as it was.
    if (data.todo) updateTodoBadge(data.todo.open);
    if (data.added) { state.todo.unshift(data.added); state.todoOpen += 1; }
    renderFindings();
    // `undo` is present on the presses that took a row away, and absent on
    // Fix it (a Claude run is already touching the house) and on the snooze
    // (it took nothing away, and has "Bring it back now").
    toast(done, data.undo);
    // Both halves of Fix it start a Claude run, so both want the faster
    // poll that notices it finishing. Cancel and the undo change a row and
    // start nothing, so neither does.
    if (verb === "fix" || verb === "apply") {
      refreshStatus().catch(() => {}); fastPoll();
    }
  } catch (e) {
    toast(e.message);
    btns.forEach((b) => { b.disabled = false; });
  }
}

// Ask the producer to look again. Unlike every other press on a finding
// this asserts nothing — it is not an ending, it takes no note, and it
// hands back no undo token, because there is nothing to undo: either the
// check still reports the problem or it does not.
//
// Three answers, and the third is the one worth being careful about. It
// cleared; it is still there (and the detail is now current, which is
// often the actual answer — "9 days left" becoming "2 days left" is the
// row telling you something); or the check COULD NOT LOOK, in which case
// nothing changes and the row stays exactly as it was. "I could not look"
// and "it went away" are different claims and only the second may take a
// row off the list — `clear_resolved`'s rule, reached by a press.
async function recheckFinding(f, btns, button) {
  btns.forEach((b) => { b.disabled = true; });
  // A checks pass is seconds, not milliseconds — long enough that a row
  // of greyed-out buttons is the only thing on screen and reads as
  // nothing happening. The control that was pressed says what it is
  // doing, which is the one place somebody is already looking.
  const was = button ? button.textContent : "";
  if (button) button.textContent = "Checking…";
  try {
    const data = await api(`api/finding/${f.ts}/recheck`, { method: "POST" });
    takeFindings(data);
    renderFindings();
    if (!data.checked) {
      toast(`Could not check that again — ${data.why}`);
      return;
    }
    if (data.cleared) {
      // Said in the words of what happened rather than "cleared": the
      // problem going away on its own is the good outcome and worth
      // naming as one.
      toast(data.also_cleared
        ? `Gone — and ${data.also_cleared} other${data.also_cleared > 1 ? "s" : ""}`
          + " that check found are gone too"
        : "Gone — that check doesn't see it any more");
      return;
    }
    // "Still there" is the commonest answer and the one that has to say
    // what it checked: the card now carries `confirmed just now`, so the
    // toast names the check rather than repeating the row.
    // A new row is not on the tab yet — everything a producer files waits
    // for a look first — so the toast says where it went rather than
    // sending somebody to a list that has not got it.
    toast(data.created
      ? "Still there — and it found something new, which brAIn is looking "
        + "at before showing you"
      : `Still there — ${esc(f.source_title || "that check")} looked again `
        + "just now and reported it");
  } catch (e) {
    toast(e.message);
  } finally {
    btns.forEach((b) => { b.disabled = false; });
    if (button) button.textContent = was;
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
  // A situation's own commonest reason, offered as text rather than as a
  // hint: it is one tap to send and still edits, where a placeholder is
  // the thing somebody has to retype.
  if (opts.prefill) ta.value = opts.prefill;
  form.appendChild(ta);
  // An optional box beside the note, for the one ending that has a second
  // thing to say: "Wrong — and stop raising these". `opts.check` is its
  // label; what it sends rides back to `onSend` as the third argument.
  let check = null;
  if (opts.check) {
    const line = el("label", "findnotecheck");
    check = document.createElement("input");
    check.type = "checkbox";
    line.appendChild(check);
    line.appendChild(el("span", null, opts.check));
    form.appendChild(line);
  }
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
    onSend(ta.value.trim(), [send, cancel], !!(check && check.checked));
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
    // Ask on a card opens the conversation about it, not the list.
    askShow("chat");
    chatConnect();
    await api(`api/finding/${f.ts}/discuss`, { method: "POST" });
    setChatFinding(f);
  } catch (e) {
    toast(e.message);
  } finally {
    btns.forEach((b) => { b.disabled = false; });
  }
}

// Whether there is a window to undo out of. The server refuses the press
// without one, so this is the card holding the same rule rather than a
// second answer to it.
function findCanUndo(f) {
  return !!(f.fix_started && f.fix_ended);
}

// What the fix actually did, on a card that is offering to undo it. The
// two numbers are separate because the undo treats them differently and
// the difference is the thing worth knowing BEFORE pressing: files come
// back, service calls are listed. A run that changed neither says so, or
// the button looks like it is offering something it is not.
function fixFootLine(f) {
  const files = f.fix_files || 0;
  const calls = f.fix_calls || 0;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  // A run from before the window was recorded. "I could not tell" and
  // "nothing changed" are different claims, and only the second may sit
  // under a button offering to put it back — so this one says which, and
  // `findCanUndo` takes the button away rather than offering a press that
  // would answer "there was nothing to do" about a house that was changed.
  if (!findCanUndo(f)) {
    return "brAIn did not record what this fix changed — it ran before the "
      + "panel kept that window. `brain undo` in the terminal lists every "
      + "file Claude has edited.";
  }
  if (!files && !calls) {
    return "It changed no files and called no services — undoing it would "
      + "put nothing back.";
  }
  const parts = [];
  if (files) parts.push(`changed ${plural(files, "file")}`);
  if (calls) parts.push(`made ${plural(calls, "service call")}`);
  return `brAIn ${parts.join(" and ")}. Undo puts the files back`
    + (calls ? "; the service calls are listed, not reversed." : ".");
}

// One line about whether anything looked at this finding before it
// reached the tab, plus the way into the conversation that did.
//
// Absent entirely for a row from a producer that never needed triaging
// (an insight run had already read the house) — a badge on every card
// saying nothing happened is a badge people stop reading.
function triageLine(f) {
  const t = f.triage || {};
  if (!t.verdict && f.waiting_look) {
    const box = el("p", "findtriage unchecked");
    box.appendChild(el("span", "findtriagelabel", "Not looked at yet"));
    box.appendChild(el("span", null, "brAIn has not looked at this one yet, "
      + "so it is shown as it was filed rather than left waiting out of sight."));
    return box;
  }
  if (!t.verdict) return null;
  const box = el("p", "findtriage");
  const untriaged = t.verdict === "untriaged";
  const reason = stripSignalRefs(t.reason || "");
  if (untriaged) {
    box.classList.add("unchecked");
    box.appendChild(el("span", "findtriagelabel", "Not checked first"));
    if (reason) box.appendChild(el("span", null, reason));
  } else if (t.elevated_by_person) {
    // Two speakers, so two labels. The person's press heads the line, and
    // the sentence under it is brAIn's — said as brAIn's, or it reads as
    // if the person had written "this is not a fault".
    const when = t.elevated_at ? ` on ${shortDate(t.elevated_at)}` : "";
    box.appendChild(el("span", "findtriagelabel", `You brought this back${when}`));
    if (reason) {
      box.appendChild(el("span", "findtriagesaid",
        `${t.verdict === "held" ? "brAIn had said" : "brAIn checked"}: ${reason}`));
    }
  } else {
    box.appendChild(el("span", "findtriagelabel", "brAIn checked"));
    if (reason) box.appendChild(el("span", null, reason));
  }
  // Only a run that looked has a record to open. An untriaged row's run
  // id, where it has one, is the look that FAILED — and a button promising
  // "what it checked" beside "Not checked first" contradicts the label.
  if (t.run_id && !untriaged) box.appendChild(triageLink(f));
  return box;
}

// "signal 7": the first look's own numbering, which an older reply cites.
// The server takes it out of new reasons (`resident.strip_signal_refs`);
// this is the same rule for a reason stored before that.
const SIGNAL_LIST = String.raw`#?\s*\d+(?:\s*(?:,|and|&|or|-|–)\s*#?\s*\d+)*`;
const SIGNAL_PAREN = new RegExp(
  String.raw`\s*\(\s*(?:signals?|rows?|items?)\s*` + SIGNAL_LIST + String.raw`\s*\)`, "gi");
const SIGNAL_REF = new RegExp(
  String.raw`\b(signals?|rows?|items?)\s*` + SIGNAL_LIST + String.raw`\b`, "gi");
function stripSignalRefs(text) {
  const s = String(text || "");
  if (!/\d/.test(s)) return s;
  const out = s.replace(SIGNAL_PAREN, "").replace(SIGNAL_REF, (m, noun) => {
    const plural = /s$/i.test(noun);
    const base = noun.replace(/s$/i, "").toLowerCase();
    const word = plural ? `other ${base}s` : `another ${base}`;
    return /^[A-Z]/.test(noun) ? word[0].toUpperCase() + word.slice(1) : word;
  }).replace(/\s{2,}/g, " ").trim();
  return out || s;
}

// "3 Oct" — a date with no year, for a line about something recent.
function shortDate(epoch) {
  return new Date(epoch * 1000).toLocaleDateString(
    [], { month: "short", day: "numeric" });
}

// Where a finding came from, on one line. A long title ends in an
// ellipsis, so the whole of it rides in the element's title.
function srcChip(text) {
  const chip = el("span", "findsrc", text);
  chip.title = text;
  return chip;
}

// The record of the run that judged it. Opened through the same reader
// every other engine-store run uses: those turns ran under the analyst's
// read-only scoping, so they are read and never resumed.
function triageLink(f) {
  const t = f.triage || {};
  const btn = el("button", "btn tiny ghost", "See what it checked");
  tip(btn, "Opens the conversation brAIn had about this finding. It is a "
    + "record — you can read it and ask a new chat about it, not continue it.");
  btn.addEventListener("click", () => viewConversation({
    id: t.run_id,
    source: "triage",
    title: f.text || "",
    age: t.at ? timeAgo(new Date(t.at * 1000).toISOString()) : "",
  }));
  return btn;
}

const LEGACY_PLAN_MARK = "this plan was written before brAIn checked";
function planRefused(plan) {
  if (!plan || typeof plan !== "object" || !Object.keys(plan).length) return false;
  if (plan.can_fix && (plan.ops || []).length) return false;
  if (!(plan.summary || (plan.steps || []).length || plan.at
        || plan.ops_refused || plan.needs_you)) return false;
  return !String(plan.ops_refused || "").startsWith(LEGACY_PLAN_MARK);
}

// ===================================================================== Today
// docs/design/ui-redesign-2026-10.md, "The first screen". One screen for
// deciding: a safety banner only while something is urgent, the status
// line, the queue, Your list and the History drawer. Every finding,
// question, suggestion, name tidy and assessed update is the SAME card —
// a meta line with one status chip, a title, at most three lines of body,
// the fix in two, one Details disclosure and one row of presses — because
// a queue whose cards are five different shapes is a queue somebody has
// to learn five times. The presses on a case are still the server's
// (`answers.py`); this file lays them out and holds no table of what a
// verb does.

const CHIP_WORDS = {
  urgent: "Urgent", problem: "Problem", tidy: "Tidy-up", suggestion: "Suggestion" };

const todayState = {
  showAll: false,          // "Show N more" was pressed this visit
  extras: { tidy: null, updates: [] },  // /api/today: the cards no store owns
  history: null,           // /api/history, fetched when the drawer opens
  histFilter: "snoozed",
  histBusy: false,
  ticked: null,            // tidy rows ticked on the card (null: all of them)
  briefOpen: false,
};

// How many cards fit before "Show N more": one on a phone, three on a
// desktop — the design doc's numbers, so the first screen is decisions and
// not a scroll.
function todayFits() {
  return window.matchMedia("(max-width: 699px)").matches ? 1 : 3;
}

// "9 min ago", the status line's own words (`brain_status.ago`), worked out
// here against the viewer's clock so the line moves between polls.
function agoWords(epoch) {
  const s = Math.max(0, Date.now() / 1000 - (Number(epoch) || 0));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

// "Wed" inside a week, "12 Oct" past it — a snooze's own words.
function untilWords(epoch) {
  const secs = (Number(epoch) || 0) - Date.now() / 1000;
  const d = new Date(epoch * 1000);
  if (secs < 6 * 86400) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

// ---- the card --------------------------------------------------------------

function statusChip(kind) {
  const known = Object.prototype.hasOwnProperty.call(CHIP_WORDS, kind);
  const chip = el("span", "chip-status", CHIP_WORDS[known ? kind : "problem"]);
  chip.dataset.kind = known ? kind : "problem";
  return chip;
}

// The shell every card on Today is built from. `meta` is plain text after
// the chip — an item's state is words, never a second chip.
function qCard({ id, chip, meta, title, body, counted = true }) {
  const card = el("article", "card-x qcard");
  if (id) card.dataset.caseId = id;
  card.dataset.chip = CHIP_WORDS[chip] ? chip : "problem";
  if (counted) card.dataset.counted = "1";
  const line = el("div", "meta");
  line.appendChild(statusChip(chip));
  (meta || []).filter(Boolean).forEach((t) => line.appendChild(el("span", "item-state", t)));
  card.appendChild(line);
  card.appendChild(el("h3", "card-title", prettyText(title || "")));
  if (body) card.appendChild(el("p", "card-body", prettyText(body)));
  return card;
}

// "Fix", then what to do in two lines. Who would do it is said by the
// primary button under it (Plan, Apply or Add to list), so the heading is
// one word.
function qFix(text) {
  const box = el("div", "qfix");
  box.appendChild(el("span", "qfixhead", "Fix"));
  box.appendChild(el("p", "qfixtext", prettyText(text)));
  return box;
}

function qDetails() {
  const box = el("details", "qdetails");
  box.appendChild(el("summary", null, "Details"));
  return box;
}

function qDetailLine(box, label, text) {
  if (!text) return;
  const p = el("p", "qdline");
  p.appendChild(el("span", "qdlabel", label));
  p.appendChild(el("span", null, prettyText(text)));
  box.appendChild(p);
}

function qButton(label, primary) {
  return el("button", primary ? "btn-primary" : "btn-secondary", label);
}

// The words for how sure, and how much it matters. Words and never a
// number: 0.62 and 0.68 are the same claim.
const CASE_STAKES = { high: "matters a lot", medium: "worth knowing", low: "minor" };
function caseConfidence(value) {
  if (typeof value !== "number") return "";
  if (value >= 0.8) return "confident";
  if (value >= 0.5) return "fairly sure";
  return "not sure";
}

// What the meta line says after the chip: where it came from, and the
// item's state as words — "Snoozed until Wed", "Unchecked", "Applying".
// A guess's topic is the id of the card it came out of ("user-1790086617"
// for one you asked), which is what the store keeps and nothing a person
// has ever seen. The card it names is on the Insights tab, by its title.
function sourceTitleText(title) {
  const t = String(title || "");
  if (!t) return "";
  const card = state.insights.find((i) => i.id === t || i.category === t);
  if (card) return card.eyebrow || card.category_title || card.title || t;
  if (/^user-\d+$/.test(t)) return "Your question";
  return t;
}

function caseMeta(row) {
  const out = [];
  if (row.source_title) out.push(sourceTitleText(row.source_title));
  const fs = row.finding_status;
  if (fs === "planning") out.push("Planning");
  else if (fs === "planned") out.push("Plan ready");
  else if (fs === "fixing") out.push("Applying");
  else if (fs === "fixed") out.push(row.ended && row.ended.when
    ? `Applied ${shortDate(row.ended.when)}` : "Applied");
  if (row.waiting_look) out.push("Unchecked");
  if (row.snoozed_until && row.snoozed_until * 1000 > Date.now()) {
    out.push(`Snoozed until ${untilWords(row.snoozed_until)}`);
  }
  if (row.checked_at) {
    out.push("confirmed " + timeAgo(new Date(row.checked_at * 1000).toISOString()));
  }
  return out;
}

// The plan a read-only run wrote, on the card that would carry it out.
// "What could go wrong" stays on the face of an Apply card — it is the
// other half of what somebody is consenting to — and a plan that is out of
// date or that brAIn will not carry out says so in one line.
function casePlanNode(row) {
  const plan = row.plan || {};
  const legacy = String(plan.ops_refused || "").startsWith(LEGACY_PLAN_MARK);
  if (row.finding_status === "planned" && legacy) {
    return el("p", "qplanline", "This plan is out of date.");
  }
  if (planRefused(plan)) {
    const box = el("div", "qplanline");
    box.appendChild(el("span", "qfixhead", "brAIn can't apply this"));
    if (plan.summary) box.appendChild(el("p", "qfixtext", prettyText(plan.summary)));
    return box;
  }
  if (row.finding_status !== "planned" && row.finding_status !== "planning") return null;
  const box = el("div", "qplan");
  box.appendChild(el("span", "qfixhead", "What Apply will change"));
  if (plan.summary) box.appendChild(el("p", "qfixtext", prettyText(plan.summary)));
  if ((plan.steps || []).length) {
    const list = el("ol", "findsteps");
    plan.steps.forEach((s) => list.appendChild(el("li", null, prettyText(s))));
    box.appendChild(list);
  }
  if (plan.risk) box.appendChild(el("p", "findrisk", `What could go wrong: ${plan.risk}`));
  return box;
}

// Everything that makes a claim checkable, behind one disclosure: where it
// came from, why, what was read, the full steps and diff of a plan, the
// entity's id, and any rows a run refused.
function caseDetailsBody(box, row) {
  qDetailLine(box, "Source", sourceTitleText(row.source_title) || row.source || "");
  if (row.detail && row.detail.length > 180) qDetailLine(box, "In full", row.detail);
  const why = [caseConfidence(row.confidence), CASE_STAKES[row.stakes] || ""]
    .filter(Boolean).join(" · ");
  qDetailLine(box, "Why", why);
  if (row.entity_id) {
    qDetailLine(box, "Entity", [row.entity_name, row.area].filter(Boolean).join(" · "));
    box.appendChild(el("code", "qdid", row.entity_id));
  }
  if ((row.evidence || []).length) {
    const list = el("ul", "caseevlist");
    row.evidence.slice(0, 6).forEach((item) => {
      const li = el("li", null);
      const name = el("span", "caseevent", prettyText(item.entity || ""));
      if (item.entity) name.title = item.entity;
      li.appendChild(name);
      li.appendChild(el("span", "caseevval", prettyText(item.value || "")));
      if (item.when) li.appendChild(el("span", "caseevwhen", item.when));
      list.appendChild(li);
    });
    qDetailLine(box, "What it read", " ");
    box.appendChild(list);
  }
  if ((row.actions || []).length) {
    const list = el("ul", "caseactlist");
    row.actions.slice(0, 6).forEach((act) => {
      const li = el("li", null);
      li.appendChild(el("span", "caseactlabel", prettyText(act.label || "")));
      li.appendChild(el("span", "caseactconsent",
        act.consent ? "would ask you first" : "brAIn can do this"));
      list.appendChild(li);
    });
    qDetailLine(box, "What could be done", " ");
    box.appendChild(list);
  }
  const plan = row.plan || {};
  if (plan.ops_refused && !String(plan.ops_refused).startsWith(LEGACY_PLAN_MARK)) {
    qDetailLine(box, "Not in the plan", plan.ops_refused);
  }
  if (plan.can_fix) planContract(box, { ...plan, ops_refused: "" });
  if (row.result) qDetailLine(box, "Last time brAIn looked", row.result);
  if ((row.changed || []).length) {
    const list = el("ul", "findchanged");
    row.changed.slice(0, 8).forEach((c) => list.appendChild(el("li", null, prettyText(c))));
    box.appendChild(list);
  }
  const seen = triageLine(caseTriageRow(row));
  if (seen) box.appendChild(seen);
}

// A case in the shape `triageLine` reads.
function caseTriageRow(row) {
  const look = (row.triage && row.triage.verdict) ? row.triage : (row.investigation
    ? { verdict: "elevated", reason: "", run_id: row.investigation.run_id }
    : null);
  return look ? { triage: look, text: row.claim } : { triage: {} };
}

// The line under a card whose run is in flight: nothing to press, and a
// card with no buttons and no sentence reads as dead.
function phaseLine(text) {
  const busy = el("div", "phase");
  busy.appendChild(el("span", "orbit"));
  busy.appendChild(el("span", null, text));
  return busy;
}

// The answers that are a "no" open the reason box. Ignore's is the one
// with a tick box: "Ignore all like this" mutes the rule that raised it,
// which is what "Stop raising these" used to be a separate press for.
const IGNORE_VERBS = new Set(["wrong", "decline", "drop", "no"]);

function makeCase(row) {
  const card = qCard({
    id: row.id, chip: row.chip || (row.urgent ? "urgent" : "problem"),
    meta: caseMeta(row), title: row.claim, body: row.detail,
  });
  card.dataset.situation = row.situation || "";

  const plan = casePlanNode(row);
  const ran = row.finding_status === "fixed" || row.finding_status === "needs_you";
  if (row.fix && !ran && !(plan && plan.classList.contains("qplan"))) {
    card.appendChild(qFix(row.fix));
  }
  if (plan) card.appendChild(plan);
  if (row.finding_status === "fixed") {
    // What Undo will put back, before anybody presses it: safety-critical,
    // so it is on the face of the card and not behind Details.
    card.appendChild(el("p", "qundoline", fixFootLine(row)));
  } else if (row.finding_status === "needs_you" && row.result) {
    card.appendChild(el("p", "qfixtext", prettyText(String(row.result).split("\n\n")[0])));
  }

  const more = qDetails();
  caseDetailsBody(more, row);
  card.appendChild(more);

  const actions = el("div", "card-actions");
  const btns = [];
  btns.card = card;
  btns.actions = actions;
  const answers = row.answers || [];
  if (!answers.length) {
    if (row.finding_status === "planning") {
      actions.appendChild(phaseLine("Working out what it would change — nothing is changing yet"));
    } else if (row.finding_status === "fixing") {
      actions.appendChild(phaseLine("Applying — this can take a few minutes"));
    }
  }
  answers.forEach((answer) => {
    const btn = qButton(answer.label, answer.primary);
    btn.dataset.verb = answer.verb;
    btns.push(btn);
    actions.appendChild(btn);
    btn.addEventListener("click", () => answer.note
      ? askThenRun(row, answer, btns)
      : runAnswer(row, answer, btns));
  });
  const menu = caseOverflow(row, btns);
  if (menu) { btns.push(menu); actions.appendChild(menu); }
  card.appendChild(actions);
  return card;
}

// ---- presses on a case -------------------------------------------------------

function syncFeed() {
  return refreshCases().then(() => {
    if (currentView === "findings") renderFindings();
  });
}

async function refreshCases() {
  try {
    takeCases(await api("api/cases"));
  } catch (e) {
    // Transient: the screen keeps what it last showed rather than blanking.
  }
}

function takeCases(data) {
  if (!data) return;
  state.cases = data.cases || [];
  state.names = data.names || {};
  updateFindBadge(data.open);
}

function absorbAnswer(data) {
  if (!data) return;
  if (Array.isArray(data.cases)) takeCases(data);
  if (Array.isArray(data.findings)) takeFindings(data);
}

// Everything a press can have moved, read together before the screen is
// painted: the queue, the findings it is derived from, Your list and the
// suggestions — a row moved by a press must not be drawn off a stale copy
// of the list it left.
async function refreshToday() {
  await Promise.all([refreshCases(), refreshFindings(), refreshTodo(),
                     refreshProposalData(), refreshTodayExtras()]);
}

async function runAnswer(row, answer, btns, note, ignoreAll) {
  const finding = caseAsFinding(row);
  if (answer.verb === "recheck" && finding) {
    return recheckFinding(finding, btns, btns.find((b) => b.dataset.verb === "recheck"));
  }
  if (answer.verb === "discuss" && finding) return discussFinding(finding, btns);
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(answer.route.replace(/^\//, ""), {
      method: answer.method || "POST",
      ...(note ? { body: JSON.stringify({ note }) } : {}),
    });
    absorbAnswer(data);
    // "Ignore all like this": the rule that raised it stops raising
    // anything, through the same route the mute always had.
    let muted = "";
    if (ignoreAll && row.source && row.mutable) {
      try {
        await api("api/findings/mute", {
          method: "POST", body: JSON.stringify({ source: row.source }) });
        muted = " — and everything like it";
      } catch (e) {
        muted = ` — but could not stop the rest: ${e.message}`;
      }
    }
    await refreshToday();
    renderFindings();
    const when = data && data.snoozed_until;
    toast(when ? `Snoozed until ${untilWords(when)}`
               : (answer.done || answer.label) + muted, data && data.undo);
    if (answer.verb === "fix" || answer.verb === "apply") {
      refreshStatus().catch(() => {}); fastPoll();
    }
  } catch (e) {
    toast(e.message || "that didn't work");
    btns.forEach((b) => { b.disabled = false; });
  }
}

function askThenRun(row, answer, btns) {
  const ignore = IGNORE_VERBS.has(answer.verb) && answer.verb !== "no";
  openNoteForm(btns.card, btns.actions,
    (text, formBtns, all) => runAnswer(row, answer, btns.concat(formBtns), text, all), {
      hint: answer.ask || (ignore ? "Why? (helps brAIn learn)"
        : answer.verb === "no" ? "Why not? (helps brAIn learn)" : "Optional."),
      placeholder: answer.placeholder || answer.prefill
        || "That sensor always reads on — it's not stuck.",
      send: answer.label,
      prefill: answer.prefill || "",
      check: ignore && answer.verb === "wrong" && row.mutable
        ? "Ignore all like this" : "",
    });
}

// The ⋯: at most three of Ask, Recheck, Done, Plan, Run — the server's
// `more`, as words with no glyph in front of them.
function caseOverflow(row, btns) {
  const items = (row.more || []).map((item) => [
    "", item.label, item.hint || "", () => runCaseOverflow(row, item, btns),
  ]);
  // A change brAIn made with service calls can have them put back, one
  // entity at a time — the before-state the chokepoint recorded.
  const f = caseAsFinding(row);
  if (f && row.finding_status === "fixed" && (row.fix_calls || 0) > 0) {
    items.push(["", "Restore", "Set what brAIn's service calls changed back to "
      + "how it was before. You press this; brAIn never does it on its own.",
      () => restoreCalls(f, btns)]);
  }
  return items.length ? cardMenuButton(items.slice(0, 3)) : null;
}

async function runCaseOverflow(row, item, btns) {
  const finding = caseAsFinding(row);
  if (item.verb === "discuss" && finding) return discussFinding(finding, btns);
  if (item.verb === "recheck" && finding) return recheckFinding(finding, btns);
  return runAnswer(row, item, btns);
}

async function restoreCalls(f, btns) {
  btns.forEach((x) => { x.disabled = true; });
  try {
    const data = await api(`api/finding/${f.ts}/restore`, { method: "POST" });
    takeFindings(data);
    await refreshToday();
    renderFindings();
    const back = (data.restored || []).filter((r) => r.restored).length;
    toast(`Restored ${back} of ${(data.restored || []).length}`);
  } catch (e) {
    toast("Could not restore them: " + e.message);
    btns.forEach((x) => { x.disabled = false; });
  }
}

function caseAsFinding(row) {
  const origin = row.origin || {};
  if (origin.store !== "findings") return null;
  return {
    ts: origin.key, text: row.claim, detail: row.detail, fix: row.fix,
    severity: row.severity, source: row.source,
    source_title: row.source_title, entity_id: row.entity_id,
    status: "open", triage: {},
  };
}

// Every entity id in a sentence, as the name a person knows it by. Ids
// the last checks pass never saw stay ids, which is honest.
function prettyText(text) {
  const names = state.names || {};
  return String(text || "").replace(/\b[a-z_]+\.[a-z0-9_]+\b/g, (id) =>
    (names[id] && names[id].name) ? names[id].name : id);
}

// ---- cards no case covers --------------------------------------------------

// A finding the case list does not cover — a row still waiting for a first
// look, or every row when the list could not be built. Shown as the same
// card with the three presses every finding has, because "I could not
// build the queue" must never render a house with problems as a house
// with none.
function makeLooseFinding(f) {
  const card = qCard({
    id: `f:${f.ts}`, chip: f.severity === "critical" ? "urgent"
      : f.severity === "info" ? "tidy" : "problem",
    meta: [f.source_title, f.waiting_look || !(f.triage || {}).verdict ? "Unchecked" : ""],
    title: f.text, body: f.detail,
  });
  if (f.fix) card.appendChild(qFix(f.fix));
  const more = qDetails();
  qDetailLine(more, "Source", f.source_title || f.source || "");
  if (f.entity_id) more.appendChild(el("code", "qdid", f.entity_id));
  const seen = triageLine(f);
  if (seen) more.appendChild(seen);
  card.appendChild(more);
  const actions = el("div", "card-actions");
  const btns = [];
  btns.card = card;
  btns.actions = actions;
  const press = (label, primary, fn) => {
    const b = qButton(label, primary);
    btns.push(b);
    actions.appendChild(b);
    b.addEventListener("click", fn);
  };
  press("Add to list", true, () => looseAction(`api/finding/${f.ts}/todo`, null,
    "On your list", btns));
  press("Snooze", false, () => looseAction(`api/finding/${f.ts}/snooze`,
    { for: "week" }, "Snoozed", btns));
  press("Ignore", false, () => openNoteForm(card, actions, (note, formBtns) =>
    looseAction(`api/finding/${f.ts}/wrong`, note ? { note } : null,
      "Ignored — brAIn won't raise this again", btns.concat(formBtns)), {
    hint: "Why? (helps brAIn learn)",
    placeholder: "That sensor always reads on — it's not stuck.",
    send: "Ignore",
  }));
  card.appendChild(actions);
  return card;
}

function makeLooseQuestion(h) {
  const card = qCard({ id: `h:${h.ts}`, chip: "suggestion",
    meta: ["A guess to confirm"], title: h.text || h.claim || "", body: h.why || "" });
  const actions = el("div", "card-actions");
  const btns = [];
  btns.card = card;
  btns.actions = actions;
  const yes = qButton("Yes", true);
  const no = qButton("No", false);
  btns.push(yes, no);
  actions.append(yes, no);
  yes.addEventListener("click", () => looseAction(`api/hypothesis/${h.ts}/confirm`,
    null, "Filed into memory", btns));
  no.addEventListener("click", () => openNoteForm(card, actions, (note, formBtns) =>
    looseAction(`api/hypothesis/${h.ts}/reject`, note ? { note } : null, "Noted",
      btns.concat(formBtns)), {
    hint: "Why not? (helps brAIn learn)", placeholder: "", send: "No" }));
  card.appendChild(actions);
  return card;
}

async function looseAction(path, body, done, btns) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(path, {
      method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
    absorbAnswer(data);
    await refreshToday();
    renderFindings();
    toast(done, data && data.undo);
  } catch (e) {
    toast(e.message || "that didn't work");
    btns.forEach((b) => { b.disabled = false; });
  }
}

// ---- suggestions (the proposals store) --------------------------------------

async function refreshProposalData() {
  try {
    propState.data = await api("api/proposals");
  } catch (err) {
    propState.data = propState.data
      || { proposals: [], intents: [], counts: { open: 0 }, error: String(err) };
  }
}

async function refreshProposals() {
  await refreshProposalData();
  renderProposals();
}

// The proposals store has no tab of its own any more: its cards are in
// Today's queue, so a change to it repaints Today.
function renderProposals() {
  if (currentView === "findings") renderFindings();
}

function propSnoozed(row) {
  return (Number(row.snoozed_until) || 0) * 1000 > Date.now();
}

function makeSuggestion(row) {
  const trial = row.status === "trialling";
  const over = trial && propTrialOver(row);
  const meta = [];
  if (row.playbook) meta.push("Playbook");
  if (row.scene) meta.push("Scenes");
  if (row.edits) meta.push("Edits your rule");
  if (trial) meta.push(over ? "Trial over" : "On trial");
  const spoken = row.spoken && typeof row.spoken === "object" ? row.spoken : null;
  const replay = (row.playbook || row.scene) ? ""
    : (spoken && spoken.case ? spoken.case : propReplayLine(row));
  const card = qCard({ id: `p:${row.ts}`, chip: "suggestion", meta,
    title: row.title || "A suggestion", body: row.why || replay });
  if (trial) card.appendChild(el("p", "qfixtext", propTrialLine(row)));

  const more = qDetails();
  if (row.why && replay) qDetailLine(more, "Replay", replay);
  if (row.playbook) {
    const block = propPlaybookBlock(row);
    if (block) more.appendChild(block);
    if (row.playbook.no_trial) qDetailLine(more, "No trial", row.playbook.no_trial);
    more.appendChild(propRehearsal(row));
  }
  if (row.scene) {
    const block = propSceneBlock(row);
    if (block) more.appendChild(block);
    if (!row.config) qDetailLine(more, "Not offered", row.refused || "");
  }
  card.appendChild(more);

  if (propState.errorFor === row.ts) {
    const box = el("p", "qerror", propState.error);
    box.setAttribute("role", "alert");
    card.appendChild(box);
  }

  const actions = el("div", "card-actions");
  const btns = [];
  btns.card = card;
  btns.actions = actions;
  const add = (b) => { btns.push(b); actions.appendChild(b); return b; };
  const busy = !!propState.busy;
  if (!row.scene || row.config) {
    const yes = add(qButton(propState.busy === row.ts && propState.busyVerb === "accept"
      ? "Applying…" : "Apply", true));
    yes.addEventListener("click", () => propAct(row.ts, "accept"));
  }
  const later = add(qButton("Snooze", false));
  later.addEventListener("click", async () => {
    btns.forEach((b) => { b.disabled = true; });
    try {
      const data = await api(`api/case/p:${row.ts}/not_now`, { method: "POST" });
      await refreshProposalData();
      renderFindings();
      toast(data && data.snoozed_until
        ? `Snoozed until ${untilWords(data.snoozed_until)}` : "Snoozed");
    } catch (e) {
      toast(e.message || "that didn't work");
      btns.forEach((b) => { b.disabled = false; });
    }
  });
  const no = add(qButton("Ignore", false));
  no.addEventListener("click", () => openNoteForm(card, actions,
    (note) => propAct(row.ts, "decline", { note }), {
      hint: "Why? (helps brAIn learn)",
      placeholder: "We already turn that off by hand on purpose.",
      send: "Ignore",
    }));
  if (row.status === "proposed" && !row.playbook && !row.scene && !row.intent) {
    const menu = cardMenuButton([["", "Run", "Try it for a week first: replay it "
      + "over the days since and grade each firing against what you did. "
      + "Nothing is switched on.", () => propAct(row.ts, "trial")]]);
    add(menu);
  }
  btns.forEach((b) => { b.disabled = busy; });
  card.appendChild(actions);
  return card;
}

// A one-off sentence brAIn armed (or refused to). Not a decision — it is
// waiting on the house — so it is drawn as a card and counted by nothing.
function makeIntent(row) {
  const word = { armed: "Armed", fired: "It fired", refused: "Not armed" }[row.status]
    || row.status;
  const card = qCard({ id: `i:${row.ts}`, chip: "suggestion", counted: false,
    meta: [word, row.overdue ? "Waiting a fortnight" : ""],
    title: row.title || row.sentence || "A one-off", body: propIntentLine(row) });
  const more = qDetails();
  if (row.sentence) qDetailLine(more, "You asked", `“${row.sentence}”`);
  if (row.plain) qDetailLine(more, "brAIn understood", row.plain);
  card.appendChild(more);
  if (propState.errorFor === row.ts) {
    const box = el("p", "qerror", propState.error);
    box.setAttribute("role", "alert");
    card.appendChild(box);
  }
  const actions = el("div", "card-actions");
  const refused = row.status === "refused";
  const go = qButton(refused ? "Done" : "Delete", row.status === "fired" || refused);
  go.disabled = !!propState.busy;
  go.addEventListener("click", () => {
    if (!refused && !window.confirm("Delete this automation from automations.yaml? "
      + "It is snapshotted first, and the toast can put it back.")) return;
    propRemoveIntent(row.ts, refused);
  });
  actions.appendChild(go);
  card.appendChild(actions);
  return card;
}

// ---- the two cards no store owns: a name tidy, an assessed update -----------

async function refreshTodayExtras() {
  try {
    todayState.extras = await api("api/today");
  } catch (e) {
    // Keep what we had: an empty extras list is "nothing to tidy", and a
    // fetch that failed is not that.
  }
}

const TIDY_KIND_WORDS = { name: "Rename", area: "Room", alias: "Alias" };

function tidyRowText(row) {
  const after = row.kind === "area" ? row.area_name : row.value;
  const before = row.kind === "area" ? (row.from_area || "no room") : row.label;
  return row.kind === "alias"
    ? `${row.label}: also answer to “${after}”`
    : `${before} → ${after}`;
}

function makeTidyCard(t) {
  const rows = t.rows || [];
  if (!todayState.ticked) todayState.ticked = new Set(rows.map((r) => r.id));
  const counts = {};
  rows.forEach((r) => { counts[r.kind] = (counts[r.kind] || 0) + 1; });
  const body = Object.entries(counts).map(([k, n]) =>
    `${TIDY_KIND_WORDS[k] || k} ${n}`).join(", ");
  const card = qCard({ id: t.key, chip: "tidy", meta: ["Change ready"],
    title: `Tidy ${rows.length} name${rows.length === 1 ? "" : "s"} and rooms`,
    body: `${body}. Untick any you disagree with under Details.` });
  const reach = rows.filter((r) => (r.reach || []).length).length;
  if (reach) {
    card.appendChild(el("p", "qfixtext", reach === 1
      ? "1 room move changes what an automation reaches — it is listed under Details."
      : `${reach} room moves change what an automation reaches — they are listed under Details.`));
  }
  const more = qDetails();
  const list = el("div", "qtidylist");
  rows.forEach((row) => {
    const label = el("label", "qtidyrow");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = todayState.ticked.has(row.id);
    box.addEventListener("change", () => {
      if (box.checked) todayState.ticked.add(row.id); else todayState.ticked.delete(row.id);
      apply.textContent = "Apply";
      apply.disabled = !todayState.ticked.size;
    });
    label.appendChild(box);
    const text = el("span", null, `${TIDY_KIND_WORDS[row.kind] || row.kind}: ${tidyRowText(row)}`);
    label.appendChild(text);
    list.appendChild(label);
    (row.reach || []).forEach((r) => list.appendChild(el("p", "qdline",
      `Changes what “${r.alias}” reaches: it ${r.change} (${r.area}).`)));
  });
  more.appendChild(list);
  (t.refused || []).forEach((r) => qDetailLine(more, "Refused",
    `${r.label || r.subject} → ${r.value}: ${r.refused}`));
  qDetailLine(more, "Undo", `For ${t.undo_days || 30} days, from History › Done. `
    + "It puts back each field that still holds what brAIn wrote.");
  card.appendChild(more);

  const actions = el("div", "card-actions");
  const btns = [];
  const apply = qButton("Apply", true);
  apply.disabled = !todayState.ticked.size;
  apply.addEventListener("click", async () => {
    btns.forEach((b) => { b.disabled = true; });
    try {
      const data = await api("api/tidy/apply", {
        method: "POST", body: JSON.stringify({ ids: [...todayState.ticked] }) });
      todayState.ticked = null;
      const n = ((data && data.result && data.result.applied) || []).length;
      await refreshToday();
      renderFindings();
      toast(`Applied ${n} — Undo is in History for ${t.undo_days || 30} days`);
    } catch (e) {
      toast(e.message || "that didn't work");
      btns.forEach((b) => { b.disabled = false; });
    }
  });
  btns.push(apply);
  actions.appendChild(apply);
  todayHideButtons(t.key, card.querySelector(".card-title").textContent, btns, actions);
  card.appendChild(actions);
  return card;
}

const UPDATE_WORDS = { safe_tonight: "Safe tonight", wait: "Wait", unknown: "Can't tell" };

function makeUpdateCard(u) {
  const advice = u.advice || {};
  const card = qCard({ id: u.key, chip: advice.verdict === "wait" ? "problem" : "tidy",
    meta: [UPDATE_WORDS[advice.verdict] || "Assessed", `${u.installed || "?"} → ${u.latest || "?"}`],
    title: `Update ${u.title || u.entity_id}`, body: advice.reason || "" });
  const more = qDetails();
  qDetailLine(more, "From the release notes", advice.note_quote || "");
  qDetailLine(more, "From your configuration", advice.config_quote || "");
  if (advice.edit) {
    qDetailLine(more, "The change brAIn would make first", " ");
    more.appendChild(el("pre", "qdpre", advice.edit));
  }
  qDetailLine(more, "Note", "brAIn never installs an update itself.");
  card.appendChild(more);
  const actions = el("div", "card-actions");
  const btns = [];
  const list = qButton("Add to list", true);
  list.addEventListener("click", async () => {
    btns.forEach((b) => { b.disabled = true; });
    try {
      takeTodo(await api("api/todo", { method: "POST", body: JSON.stringify({
        text: `Update ${u.title || u.entity_id} to ${u.latest || "the new version"}`,
        detail: advice.reason || "" }) }));
      await api("api/today/hide", { method: "POST", body: JSON.stringify({
        key: u.key, how: "listed", title: u.title || "" }) });
      await refreshToday();
      renderFindings();
      toast("On your list");
    } catch (e) {
      toast(e.message || "that didn't work");
      btns.forEach((b) => { b.disabled = false; });
    }
  });
  btns.push(list);
  actions.appendChild(list);
  todayHideButtons(u.key, `Update ${u.title || u.entity_id}`, btns, actions);
  card.appendChild(actions);
  return card;
}

// Snooze and Ignore on a card no store owns (`today.hide`).
function todayHideButtons(key, title, btns, actions) {
  [["Snooze", "snoozed"], ["Ignore", "ignored"]].forEach(([label, how]) => {
    const b = qButton(label, false);
    b.addEventListener("click", async () => {
      btns.forEach((x) => { x.disabled = true; });
      try {
        const data = await api("api/today/hide", { method: "POST",
          body: JSON.stringify({ key, how, title }) });
        todayState.extras = { tidy: data.tidy, updates: data.updates || [] };
        updateFindBadge(data.open);
        renderFindings();
        toast(how === "snoozed" ? `Snoozed until ${untilWords(data.snoozed_until)}`
          : "Ignored — it is in History if you want it back");
      } catch (e) {
        toast(e.message || "that didn't work");
        btns.forEach((x) => { x.disabled = false; });
      }
    });
    btns.push(b);
    actions.appendChild(b);
  });
}

// ---- the screen --------------------------------------------------------------

// The cards, in the order the doc gives: urgent first, then problems and
// questions in the server's own band order, then suggestions, the name
// tidy and the updates. The case list is the server's (`_cases_payload`),
// and anything live it does not cover is drawn after it.
function todayCards() {
  const feed = state.cases || [];
  const covered = new Set(feed.map((c) => c.id));
  const loose = (state.findings || []).filter((f) =>
    ["open", "planning", "planned", "fixing", "fixed", "failed", "needs_you"]
      .includes(f.status) || f.waiting_look)
    .filter((f) => !findings_isSnoozed(f) && !covered.has(`f:${f.ts}`));
  const looseClaims = (state.hypotheses || []).filter((h) => !covered.has(`h:${h.ts}`));
  const props = ((propState.data && propState.data.proposals) || [])
    .filter((r) => !propSnoozed(r));
  const intents = (propState.data && propState.data.intents) || [];
  const extras = todayState.extras || {};
  const out = [];
  feed.forEach((c) => out.push(() => makeCase(c)));
  looseClaims.forEach((h) => out.push(() => makeLooseQuestion(h)));
  loose.forEach((f) => out.push(() => makeLooseFinding(f)));
  props.forEach((r) => out.push(() => makeSuggestion(r)));
  if (extras.tidy) out.push(() => makeTidyCard(extras.tidy));
  (extras.updates || []).forEach((u) => out.push(() => makeUpdateCard(u)));
  intents.forEach((r) => out.push(() => makeIntent(r)));
  return out;
}

function renderFindings() {
  renderTodayChrome();
  const list = $("#findList");
  const moreBtn = $("#todayMore");
  if (!list) return;
  list.textContent = "";
  const setupShown = !$("#todaySetup").hidden;
  list.hidden = setupShown;
  if (setupShown) {
    moreBtn.hidden = true;
  } else {
    const cards = todayCards();
    if (!cards.length) {
      list.appendChild(el("p", "empty-line", "Nothing needs you."));
      moreBtn.hidden = true;
    } else {
      const fits = todayFits();
      const shown = todayState.showAll ? cards.length : Math.min(fits, cards.length);
      cards.slice(0, shown).forEach((make) => list.appendChild(make()));
      const rest = cards.length - shown;
      moreBtn.hidden = rest <= 0;
      moreBtn.textContent = `Show ${rest} more`;
    }
  }
  renderTodo();
  renderHistory();
}

// The parts of Today that follow the status poll: the banner, the status
// line and the setup card. Cheap, and safe to repaint on every poll —
// nothing in them holds a half-typed reason the way a card can.
function renderTodayChrome() {
  renderTodayBanner();
  renderTodayStatus();
  renderTodaySetup();
}

function renderTodayBanner() {
  renderNeedsStrip();
  const box = $("#todayBanner");
  if (!box) return;
  const urgent = (state.cases || []).filter((c) => c.urgent);
  box.textContent = "";
  box.hidden = !urgent.length;
  if (!urgent.length) return;
  box.appendChild(statusChip("urgent"));
  box.appendChild(el("span", null, urgent.length === 1
    ? prettyText(urgent[0].claim)
    : `${urgent.length} urgent: ${prettyText(urgent[0].claim)}`));
}

function renderTodayStatus() {
  const s = state.status || {};
  const st = s.status || {};
  const line = $("#todayStatus");
  if (!line) return;
  const kind = st.state || "watching";
  line.dataset.state = kind;
  let text = st.sentence || st.label || "Watching";
  if (kind === "watching") {
    text = st.last_look_at ? `Watching · last look ${agoWords(st.last_look_at)}` : "Watching";
  }
  $("#todayStatusText").textContent = text.replace(/\.$/, "");
  // Built once and asked at the press, so a poll repainting the line never
  // pulls the menu out from under somebody reading it.
  const host = $("#todayStatusMenuHost");
  if (!host.firstChild) host.appendChild(cardMenuButton(todayStatusItems));
  renderTodayBrief();
}

function todayStatusItems() {
  const s = state.status || {};
  const items = [["", "Recheck", "Run the house checks now. Nothing changes in the "
    + "house; new problems land in the queue.", () => todayRecheck()]];
  if (s.brief && s.brief.text) {
    items.push(["", "Read this morning's brief", "What brAIn sent at "
      + fmtClock(s.brief.sent_at), () => {
        todayState.briefOpen = !todayState.briefOpen;
        renderTodayBrief();
      }]);
  }
  return items;
}

function renderTodayBrief() {
  const box = $("#todayBrief");
  const brief = (state.status || {}).brief;
  if (!box) return;
  box.hidden = !(todayState.briefOpen && brief && brief.text);
  box.textContent = box.hidden ? "" : brief.text;
}

async function todayRecheck() {
  toast("Checking the house…");
  try {
    const res = await api("api/checks/run", { method: "POST" });
    if (res.error) toast(res.error);
    else {
      const fresh = (res.created || []).length;
      const gone = (res.cleared || []).length;
      toast(`Checked: ${fresh} new, ${gone} cleared`);
    }
    await refreshToday();
    renderFindings();
  } catch (e) {
    toast(e.message);
  }
}

// The first-run card: three steps in place of the queue until the first
// look has finished. The sign-in and onboarding screens are the steps'
// own bodies (`adoptSetupScreens` moved them here), so there is still one
// copy of each.
const SETUP_STEPS = ["Sign in", "Choose what brAIn may change", "First look"];

function renderTodaySetup() {
  const card = $("#todaySetup");
  const s = state.status;
  if (!card || !s) return;
  const signedIn = !!s.authenticated && !state.showSignIn;
  const onboarded = !!obState.onboarded;
  // An older server says nothing about the first look; nothing said is
  // read as done, because a setup card over an established house's queue
  // is the one wrong answer here.
  const looked = s.first_look_done !== false;
  const step = !signedIn ? 0 : !onboarded ? 1 : !looked ? 2 : 3;
  card.hidden = step === 3;
  if (step === 3) return;
  const steps = $("#todaySetupSteps");
  steps.textContent = "";
  SETUP_STEPS.forEach((name, i) => {
    const li = el("li", "todaystep" + (i === step ? " now" : i < step ? " done" : ""));
    li.appendChild(el("span", null, name));
    li.appendChild(el("span", "item-state",
      i < step ? "Done" : i === step ? (i === 2 ? "Running" : "Now") : "Next"));
    steps.appendChild(li);
  });
  const wait = $("#todaySetupWait");
  if (wait) wait.hidden = step !== 2;
}

// Moved, not copied: every handler is bound to these ids, so the setup
// card's body IS the sign-in and onboarding screens.
function adoptSetupScreens() {
  const body = $("#todaySetupBody");
  if (!body) return;
  ["#setup", "#onboard"].forEach((sel) => {
    const node = $(sel);
    if (node && node.parentElement !== body) body.appendChild(node);
  });
  if (!$("#todaySetupWait")) {
    const wait = el("p", "item-state", "brAIn is taking its first look at the "
      + "house. The queue appears here when it finishes.");
    wait.id = "todaySetupWait";
    wait.hidden = true;
    body.appendChild(wait);
  }
}

$("#todayMore")?.addEventListener("click", () => {
  todayState.showAll = true;
  renderFindings();
});

// ---- Your list -----------------------------------------------------------

async function refreshTodo() {
  try {
    takeTodo(await api("api/todo"));
  } catch (err) {
    console.warn("could not load Your list", err);
  }
}

function takeTodo(data) {
  if (!data) return;
  state.todo = data.items || [];
  state.todoDone = data.done || [];
  state.todoOpen = data.open || 0;
  if (data.findings) state.findings = data.findings;
}

// The tab badge is the queue's; Your list carries no badge of its own.
function updateTodoBadge() {}

async function todoAction(item, path, method, message, btns, body) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(path, {
      method,
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    takeTodo(data);
    await refreshToday();
    renderFindings();
    if (message) toast(message, data.undo);
  } catch (err) {
    btns.forEach((b) => { b.disabled = false; });
    toast(err.message || "that didn't work");
  }
}

function renderTodo() {
  const list = $("#todoList");
  if (!list) return;
  list.textContent = "";
  const rows = (state.todo || []).filter((i) =>
    !((Number(i.snoozed_until) || 0) * 1000 > Date.now()));
  if (!rows.length) {
    list.appendChild(el("p", "empty-line", "Nothing on your list."));
    return;
  }
  rows.forEach((i) => list.appendChild(makeTodo(i)));
}

function makeTodo(item) {
  const row = el("div", "todorow");
  row.dataset.todoId = item.id;
  const text = el("div", "todotext");
  text.appendChild(el("span", "todotitle", prettyText(item.text)));
  const meta = [item.origin === "finding" ? (item.source_title || "From a finding") : "Added by you"];
  if (item.added_at) meta.push("added " + timeAgo(new Date(item.added_at * 1000).toISOString()));
  text.appendChild(el("span", "item-state", meta.join(" · ")));
  if (item.fix) text.appendChild(el("span", "todofix", prettyText(item.fix)));
  row.appendChild(text);
  const actions = el("div", "todoactions");
  const btns = [];
  const done = qButton("Done", false);
  btns.push(done);
  actions.appendChild(done);
  done.addEventListener("click", () => openNoteForm(row, actions,
    (note, formBtns) => todoAction(item, `api/todo/${item.id}/done`, "POST",
      "Done — written into memory", btns.concat(formBtns), note ? { note } : null), {
      hint: "What did you do? Optional — it goes into memory.",
      placeholder: "Replaced the CR2032 — it's a 3-monthly job on that one.",
      send: "Done",
    }));
  const menu = cardMenuButton([
    ["", "Snooze", "Off the list for a week; it comes back by itself.",
      () => todoAction(item, `api/case/t:${item.id}/not_now`, "POST", "Snoozed", btns)],
    ["", "Ignore", item.origin === "finding"
      ? "Off the list, and brAIn will not raise it again."
      : "Off the list for good.",
      () => todoAction(item, `api/todo/${item.id}/ignore`, "POST", "Ignored", btns)],
  ]);
  btns.push(menu);
  actions.appendChild(menu);
  row.appendChild(actions);
  return row;
}

// ---- History ---------------------------------------------------------------

async function refreshHistory() {
  try {
    todayState.history = await api("api/history");
  } catch (e) {
    todayState.history = todayState.history || { filters: [], rows: {}, error: e.message };
  }
}

// What each filter holds, said once above its rows, so the list explains
// itself rather than being a pile of titles under a word.
const HIST_HINTS = {
  snoozed: "Put off for now — each comes back by itself on the date shown. Restore brings it back now.",
  ignored: "Things you told brAIn aren't a problem. It won't raise them again unless you restore them.",
  done: "Things you finished or brAIn fixed. Restore puts one back on your list.",
  aside: "Things brAIn looked at and decided weren't worth your time. Restore if you disagree.",
};

function histRowsShown() {
  const data = todayState.history;
  if (!data) return [];
  const rows = (data.rows || {})[todayState.histFilter] || [];
  const q = (todayState.histQuery || "").trim().toLowerCase();
  if (!q) return rows;
  const words = q.split(/\s+/).filter(Boolean);
  return rows.filter((r) => {
    const hay = `${r.title || ""} ${r.meta || ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

function renderHistory() {
  const chips = $("#histFilters");
  const list = $("#histList");
  if (!chips || !list) return;
  const data = todayState.history;
  chips.textContent = "";
  list.textContent = "";
  const hint = $("#histHint");
  const clearBtn = $("#histClear");
  if (!data) {
    list.appendChild(el("p", "empty-line", "Loading…"));
    if (clearBtn) clearBtn.hidden = true;
    return;
  }
  // Land on the first filter that holds something, rather than an empty
  // one, until somebody picks.
  const filters = data.filters || [];
  if (!todayState.histPicked) {
    const first = filters.find((f) => f.count > 0);
    if (first) todayState.histFilter = first.id;
  }
  filters.forEach((f) => {
    const on = todayState.histFilter === f.id;
    const b = el("button", "pill" + (on ? " active" : ""));
    b.type = "button";
    b.appendChild(el("span", null, f.label));
    b.appendChild(el("span", "pillcount", String(f.count)));
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.dataset.filter = f.id;
    b.addEventListener("click", () => {
      todayState.histFilter = f.id;
      todayState.histPicked = true;
      renderHistory();
    });
    chips.appendChild(b);
  });
  if (hint) hint.textContent = HIST_HINTS[todayState.histFilter] || "";
  const rows = histRowsShown();
  const deletable = rows.filter((r) => r.deletable);
  if (clearBtn) {
    clearBtn.hidden = !deletable.length;
    clearBtn.textContent = todayState.histQuery
      ? `Delete ${deletable.length} shown` : `Delete all ${deletable.length}`;
  }
  if (!rows.length) {
    const empty = el("div", "emptystate");
    empty.appendChild(el("div", "emptyico", "✓"));
    empty.appendChild(el("p", null, todayState.histQuery
      ? "Nothing here matches." : "Nothing here."));
    list.appendChild(empty);
    return;
  }
  rows.forEach((r) => list.appendChild(makeHistoryRow(r)));
}

async function deleteHistory(rows, btns) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    todayState.history = await api("api/history/clear", {
      method: "POST",
      body: JSON.stringify({ items: rows.map((r) => ({ id: r.id, at: r.at || 0 })) }),
    });
    renderHistory();
    toast(rows.length === 1 ? "Deleted from history" : `Deleted ${rows.length} from history`);
  } catch (e) {
    toast(e.message || "that didn't work");
    btns.forEach((b) => { b.disabled = false; });
  }
}

const HIST_ICONS = { snoozed: "◷", ignored: "⊘", done: "✓", aside: "↘" };

function makeHistoryRow(r) {
  const row = el("div", "histrow");
  row.dataset.filter = todayState.histFilter;
  row.appendChild(el("span", "histico", HIST_ICONS[todayState.histFilter] || "•"));
  const text = el("div", "histtext");
  text.appendChild(el("span", "histtitle", prettyText(r.title)));
  text.appendChild(el("span", "item-state", r.meta || ""));
  row.appendChild(text);
  const press = r.press || {};
  const actions = el("div", "histactions");
  const btn = qButton(press.label || "Restore", false);
  const btns = [btn];
  btn.addEventListener("click", async () => {
    const confirmText = (press.steps || []).map((s) => s.confirm).find(Boolean);
    if (confirmText && !window.confirm(confirmText)) return;
    btns.forEach((b) => { b.disabled = true; });
    try {
      for (const step of press.steps || []) {
        await api(step.route.replace(/^\//, ""), {
          method: "POST",
          ...(step.body && Object.keys(step.body).length
            ? { body: JSON.stringify(step.body) } : {}),
        });
      }
      await Promise.all([refreshToday(), refreshHistory()]);
      renderFindings();
      toast(press.label === "Undo" ? "Put back" : "Restored");
    } catch (e) {
      toast(e.message || "that didn't work");
      btns.forEach((b) => { b.disabled = false; });
    }
  });
  actions.appendChild(btn);
  if (r.deletable) {
    const del = el("button", "btn icon histdel");
    del.type = "button";
    del.setAttribute("aria-label", "Delete from history");
    tip(del, "Delete from history — your answer stands");
    del.innerHTML = '<svg viewBox="0 0 24 24" class="ico" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
    btns.push(del);
    del.addEventListener("click", () => deleteHistory([r], btns));
    actions.appendChild(del);
  }
  row.appendChild(actions);
  return row;
}

(function wireHistory() {
  const search = $("#histSearch");
  if (search) {
    search.addEventListener("input", () => {
      todayState.histQuery = search.value;
      renderHistory();
    });
  }
  const clearBtn = $("#histClear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      const rows = histRowsShown().filter((r) => r.deletable);
      if (!rows.length) return;
      if (!window.confirm(`Delete ${rows.length} item${rows.length === 1 ? "" : "s"} `
        + "from history?\n\nYour answers stand — brAIn won't raise them again. "
        + "This only clears the record.")) return;
      deleteHistory(rows, [clearBtn]);
    });
  }
})();

// ---------------------------------------------------------------------------
// Ideas — proposed cards, on their own page
// ---------------------------------------------------------------------------
// The separation from Insights is the whole design and not a layout
// choice: an idea costs nothing until it is taken, where a card costs a
// run every refresh interval for ever. So this page can afford to offer
// eight things nobody wants, and the Insights tab cannot.

const ideasState = { ideas: [], running: false, lastRun: 0, lastError: "",
                     lastCount: 0, runs: 0, open: 0 };

function takeIdeas(data) {
  if (!data) return;
  ideasState.ideas = data.ideas || [];
  ideasState.running = !!data.running;
  ideasState.lastRun = data.last_run || 0;
  ideasState.lastError = data.last_error || "";
  ideasState.lastCount = data.last_count || 0;
  ideasState.runs = data.runs || 0;
  ideasState.open = data.open || 0;
  updateIdeasBadge(ideasState.open);
}

function updateIdeasBadge(n) {
  const badge = $("#ideasBadge");
  if (!badge) return;
  badge.textContent = n ? String(n) : "";
  badge.classList.toggle("hidden", !n);
}

async function refreshIdeas() {
  try {
    takeIdeas(await api("api/ideas"));
  } catch (err) {
    console.warn("could not load the ideas", err);
  }
}

// A pass is minutes of work, so the page polls while one is in flight and
// stops the moment it is not — `h_ideas_run` starts the run and does not
// await it, so this is the only thing that will notice it finished.
let ideasPoll = null;

function ideasWatch() {
  if (ideasPoll) return;
  ideasPoll = setInterval(async () => {
    await refreshIdeas();
    renderIdeas();
    if (!ideasState.running) { clearInterval(ideasPoll); ideasPoll = null; }
  }, 4000);
}

async function ideasRun(btn) {
  if (btn) btn.disabled = true;
  try {
    takeIdeas(await api("api/ideas/run", { method: "POST" }));
    renderIdeas();
    ideasWatch();
  } catch (err) {
    toast(err.message || "that didn't work");
    if (btn) btn.disabled = false;
  }
}

async function ideaAction(idea, verb, message, btns) {
  btns.forEach((b) => { b.disabled = true; });
  try {
    const data = await api(`api/idea/${idea.id}/${verb}`, { method: "POST" });
    takeIdeas(data);
    renderIdeas();
    // Accepting made a card, so the tab that draws cards is now stale.
    if (verb === "accept") {
      refreshInsights().then(render).catch(() => {});
    }
    toast(message);
  } catch (err) {
    btns.forEach((b) => { b.disabled = false; });
    toast(err.message || "that didn't work");
  }
}

// One idea. Three things and then two presses: what it would be called,
// why THIS house, and the question it would answer every run. The last is
// the one that says whether it is worth having — a title tells you the
// subject and only the question tells you what would arrive.
function makeIdea(idea) {
  const card = el("div", "finding idea");
  // `findmeta` and not a class of its own: every card in the panel uses
  // it for this row, and it is what supplies the gap and the caps. The
  // first cut invented `findline`, which matches no rule in the
  // stylesheet, so the pill and the date rendered as one run-on word.
  const line = el("div", "findmeta");
  line.appendChild(el("span", "findstate", "Suggested report"));
  if (idea.added_at) {
    line.appendChild(el("span", "findchecked",
      "suggested " + timeAgo(new Date(idea.added_at * 1000).toISOString())));
  }
  card.appendChild(line);
  card.appendChild(el("h3", "findtitle", idea.title || ""));

  if (idea.why) {
    const box = el("div", "findfix");
    box.appendChild(el("span", "findfixlabel", "Why this house"));
    box.appendChild(el("span", null, idea.why));
    card.appendChild(box);
  }
  if (idea.question) {
    const box = el("div", "findfix");
    box.appendChild(el("span", "findfixlabel", "What it would answer"));
    box.appendChild(el("span", null, idea.question));
    card.appendChild(box);
  }

  const actions = el("div", "findactions");
  const btns = [];
  const add = (node) => { btns.push(node); actions.appendChild(node); return node; };

  const take = add(el("button", "btn small primary", "Save"));
  tip(take, "Keep it as a report. It runs on the ordinary schedule from "
    + "then on, and you can change or delete it like any report.");
  take.addEventListener("click", () => ideaAction(
    idea, "accept", "Saved — it's with your reports now", btns));

  const no = add(el("button", "btn small ghost", "Ignore"));
  tip(no, "brAIn won't suggest it again; say why if you like.");
  no.addEventListener("click", () => ideaReasonBox(idea, card, actions));

  card.appendChild(actions);
  return card;
}

// What the page says when there is nothing on it, which is three
// different things: nobody has asked yet, the last run failed, or brAIn
// looked and had nothing to add. Only the second is a fault, and the
// third is a good answer about a well-covered house — rendering them the
// same way is what teaches somebody to press the button again.
function ideasEmptyText() {
  // Only the fault is said. Nobody having asked yet and a well-covered
  // house are both an empty row with its Run beside it.
  if (ideasState.running || !ideasState.lastError) return "";
  return `The last look didn't finish: ${ideasState.lastError}`;
}

function renderIdeas() {
  const list = $("#ideasList");
  if (!list) return;
  const btn = $("#ideasRun");
  if (btn) {
    btn.disabled = ideasState.running;
    btn.textContent = ideasState.running ? "Running…" : "Run";
    tip(btn, "Look for reports this house is missing — one Claude run");
  }

  const note = $("#ideasNote");
  if (note) {
    // The in-flight sentence is on the page and not only in the button,
    // because a run is minutes long and a greyed-out button is the same
    // thing a failed one looks like.
    const words = ideasState.running
      ? "Looking for reports this house is missing — a few minutes." : "";
    note.textContent = words;
    note.hidden = !words;
  }

  list.textContent = "";
  if (!ideasState.ideas.length) {
    const words = ideasEmptyText();
    if (words) list.appendChild(el("p", "findempty", words));
  } else {
    ideasState.ideas.forEach((i) => list.appendChild(makeIdea(i)));
  }
  const row = $("#ideasRow");
  if (row) row.classList.toggle("empty", !ideasState.ideas.length);
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

// One fact, with its provenance. The subject chip says what it is about,
// the source says who taught it, and a run id the ledger knows becomes a
// button that opens that run in the reader every other engine-store run
// opens in — provenance a person can follow rather than a hash in a file.
const FACT_SUBJECT_WORDS = { house: "The house" };
function factSubjectLabel(subject) {
  const s = String(subject || "house");
  if (FACT_SUBJECT_WORDS[s]) return FACT_SUBJECT_WORDS[s];
  if (s.startsWith("area:")) {
    // A folded facet carries every id it covers ("area:a|area:b"); the first names it.
    const words = s.split("|")[0].slice(5).replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  if (s.startsWith("person:")) return s.slice(7);
  return s;
}

// The subject as a person reads it: the entity's friendly name where the
// last checks pass knew one (with the id kept in the tooltip, because the
// id is what a check and a tool name), an area's word, a person's name.
function factSubjectText(f) {
  const name = String(f.subject_name || "").trim();
  const s = String(f.subject || "house");
  if (name && !s.startsWith("area:")) return name;
  return name || factSubjectLabel(s);
}

const FACT_KIND_WORDS = {
  "": "All", house: "House", area: "Rooms", entity: "Devices",
  person: "People", rule: "Rules you set",
};
// What a person narrows by. "All" is the chip that clears the others, and a
// kind this house holds nothing of is left out.
const FACT_CHIPS = ["", "area", "entity", "house", "rule"];

function makeFactRow(f) {
  // The fact, and what it is about. Who taught it, when, and the run it
  // came from are the row's detail — opened by pressing the row — because
  // a list read top to bottom is read for what it says, and the
  // provenance is what you go looking for about one line.
  const row = el("div", "fbitem kfact");
  const txt = el("div", "txt");
  const open = el("button", "kfactopen");
  open.type = "button";
  open.setAttribute("aria-expanded", "false");
  open.appendChild(el("span", "kfacttext", f.text));
  txt.appendChild(open);
  // What it is about, as a chip that narrows the list to it — the quickest
  // way from one fact to everything else brAIn knows about that thing.
  const subj = el("button", "kfactsubj" + (factSubjectText(f) !== String(f.subject || "") ? " named" : ""),
    factSubjectText(f));
  subj.type = "button";
  tip(subj, `Show everything about ${factSubjectText(f)}`);
  subj.addEventListener("click", () => pickFactSubject(String(f.subject || "house")));
  txt.appendChild(subj);
  const detail = el("div", "when kfactdetail hidden");
  const bits = [kSourceLabel(f.source)];
  if (f.observed) bits.push(f.observed);
  if (f.subject && factSubjectText(f) !== f.subject) bits.push(f.subject);
  if (f.predicate && String(f.predicate).startsWith("exception:")) {
    bits.push("stands " + String(f.predicate).slice(10) + " down");
  }
  detail.appendChild(el("span", null, bits.filter(Boolean).join(" · ")));
  if (f.run_id && f.run_source) {
    const see = el("button", "btn tiny ghost kfactrun", "See the run");
    see.type = "button";
    see.addEventListener("click", () => viewConversation({
      id: f.run_id, source: f.run_source,
      title: kSourceLabel(f.source) + " run", age: f.observed || "",
    }));
    detail.appendChild(see);
  }
  txt.appendChild(detail);
  open.addEventListener("click", () => {
    const shut = detail.classList.toggle("hidden");
    open.setAttribute("aria-expanded", shut ? "false" : "true");
  });
  row.appendChild(txt);
  const forget = async () => {
    if (!window.confirm(`Delete this fact?\n\n“${f.text}”\n\nbrAIn stops `
      + "using it. Anything already written in the memory document stays "
      + "there until you edit it.")) return;
    try {
      await api(`api/fact/${encodeURIComponent(f.id)}/forget`,
                { method: "POST" });
      factsView.rows = factsView.rows.filter((r) => r.id !== f.id);
      factsView.total = Math.max(0, factsView.total - 1);
      factsView.all = Math.max(0, factsView.all - 1);
      paintFacts();
      toast("Deleted");
    } catch (e) {
      toast(e.message);
    }
  };
  // Delete is on the row, never behind a menu: a fact that is wrong is
  // the commonest reason anybody opens this list.
  const del = el("button", "btn icon factdel");
  del.type = "button";
  del.setAttribute("aria-label", "Delete this fact");
  tip(del, "Delete — brAIn stops using this fact");
  del.innerHTML = '<svg viewBox="0 0 24 24" class="ico" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
  del.addEventListener("click", forget);
  row.appendChild(del);
  return row;
}

// The browser's state. One request per change of search, filter or sort,
// and "Show more" appends the next page rather than refetching the ones
// already on screen.
const FACTS_PAGE = 50;
const factsView = {
  q: "", kind: "", source: "", sort: "newest", subject: "",
  rows: [], total: 0, all: 0, facets: null, seq: 0, error: "",
  subjectFind: "",
};

function pickFactSubject(subject) {
  factsView.subject = factsView.subject === subject ? "" : subject;
  loadFacts(true);
  const host = $("#kKnown");
  if (host && host.scrollIntoView && window.matchMedia("(max-width: 899px)").matches) {
    host.scrollIntoView({ block: "start", behavior: "smooth" });
  }
}

async function loadFacts(reset = true) {
  if (!$("#kKnown")) return;
  const seq = ++factsView.seq;
  const params = new URLSearchParams({
    q: factsView.q, kind: factsView.kind, source: factsView.source,
    subject: factsView.subject,
    sort: factsView.sort, limit: String(FACTS_PAGE),
    offset: String(reset ? 0 : factsView.rows.length),
  });
  let data;
  try {
    data = await api("api/facts/browse?" + params.toString());
  } catch (e) {
    if (seq !== factsView.seq) return;
    factsView.error = "Could not read the facts: " + e.message;
    paintFacts();
    return;
  }
  // A slow answer to an older search must not paint over a newer one.
  if (seq !== factsView.seq) return;
  factsView.error = "";
  factsView.rows = reset ? (data.facts || [])
    : factsView.rows.concat(data.facts || []);
  factsView.total = Number(data.total) || 0;
  factsView.all = Number(data.all) || 0;
  factsView.facets = data.facets || null;
  paintFacts();
}

function paintFactChips() {
  const host = $("#kKnownKinds");
  if (!host) return;
  host.textContent = "";
  // A chip is a filter and the list under it says how many there are; the
  // count on each is how many a press would show.
  const kinds = (factsView.facets || {}).kinds || {};
  const total = Object.values(kinds).reduce((a, b) => a + (Number(b) || 0), 0);
  FACT_CHIPS.forEach((k) => {
    const n = k ? (Number(kinds[k]) || 0) : total;
    if (k && !n && factsView.kind !== k) return;
    const on = factsView.kind === k;
    const chip = el("button", "pill" + (on ? " active" : ""));
    chip.type = "button";
    chip.appendChild(el("span", null, FACT_KIND_WORDS[k]));
    chip.appendChild(el("span", "pillcount", String(n)));
    chip.setAttribute("aria-pressed", on ? "true" : "false");
    chip.addEventListener("click", () => {
      factsView.kind = k;
      loadFacts(true);
    });
    host.appendChild(chip);
  });
}

const FACT_SOURCE_NONE = "Anyone";
function paintFactSources() {
  const sel = $("#kKnownSource");
  if (!sel) return;
  const sources = (factsView.facets || {}).sources || {};
  sel.textContent = "";
  const all = el("option", null, `Taught by: ${FACT_SOURCE_NONE}`);
  all.value = "";
  sel.appendChild(all);
  Object.entries(sources).forEach(([src, n]) => {
    if (!src) return;
    const opt = el("option", null, `${kSourceLabel(src)} (${n})`);
    opt.value = src;
    sel.appendChild(opt);
  });
  if (factsView.source && !(factsView.source in sources)) {
    const opt = el("option", null, kSourceLabel(factsView.source));
    opt.value = factsView.source;
    sel.appendChild(opt);
  }
  sel.value = factsView.source;
}

function factSubjectName(s) {
  return s.name || factSubjectLabel(s.id);
}

// Every room and device brAIn has said something about, with how many: a
// rail on a wide screen and a select on a phone. Devices sit under the room
// they are in, so "what does it know about the kitchen" is one look.
function paintFactSubjects() {
  const subjects = ((factsView.facets || {}).subjects || []).slice();
  const rail = $("#kSubjects");
  const sel = $("#kSubjectSel");
  const find = (factsView.subjectFind || "").trim().toLowerCase();
  const byName = (a, b) => factSubjectName(a).localeCompare(factSubjectName(b));
  const rooms = subjects.filter((s) => s.kind === "area").sort(byName);
  const house = subjects.filter((s) => s.kind === "house" || s.kind === "person" || s.kind === "check");
  const devices = subjects.filter((s) => s.kind === "entity");
  const byArea = new Map();
  devices.forEach((d) => {
    const k = d.area || "";
    if (!byArea.has(k)) byArea.set(k, []);
    byArea.get(k).push(d);
  });
  const areaNames = [...byArea.keys()].sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
  if (sel) {
    sel.textContent = "";
    const all = el("option", null, "About: anything");
    all.value = "";
    sel.appendChild(all);
    const addGroup = (label, rows) => {
      if (!rows.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      rows.forEach((r) => {
        const opt = el("option", null, `${factSubjectName(r)} (${r.count})`);
        opt.value = r.id;
        g.appendChild(opt);
      });
      sel.appendChild(g);
    };
    addGroup("House", house);
    addGroup("Rooms", rooms);
    areaNames.forEach((a) => addGroup(a ? `Devices · ${a}` : "Devices · no room",
      byArea.get(a).slice().sort(byName)));
    if (factsView.subject && !subjects.some((s) => s.id === factsView.subject)) {
      const opt = el("option", null, factSubjectLabel(factsView.subject));
      opt.value = factsView.subject;
      sel.appendChild(opt);
    }
    sel.value = factsView.subject;
  }
  if (!rail) return;
  rail.textContent = "";
  const match = (s) => !find || factSubjectName(s).toLowerCase().includes(find)
    || String(s.id).toLowerCase().includes(find) || String(s.area || "").toLowerCase().includes(find);
  const item = (s, indent) => {
    const on = factsView.subject === s.id;
    const b = el("button", "ksub" + (on ? " active" : "") + (indent ? " dev" : ""));
    b.type = "button";
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.appendChild(el("span", "ksubname", factSubjectName(s)));
    b.appendChild(el("span", "ksubcount", String(s.count)));
    if (s.name && s.name !== s.id) tip(b, s.id);
    b.addEventListener("click", () => pickFactSubject(s.id));
    return b;
  };
  const allBtn = el("button", "ksub" + (factsView.subject ? "" : " active"));
  allBtn.type = "button";
  allBtn.appendChild(el("span", "ksubname", "Everything"));
  allBtn.appendChild(el("span", "ksubcount", String(factsView.total && !factsView.subject
    ? factsView.total : subjects.reduce((a, s) => a + s.count, 0))));
  allBtn.addEventListener("click", () => { factsView.subject = ""; loadFacts(true); });
  rail.appendChild(allBtn);
  let any = false;
  const section = (label, rows, indent) => {
    const shown = rows.filter(match);
    if (!shown.length) return;
    any = true;
    rail.appendChild(el("div", "ksubhead", label));
    shown.forEach((r) => rail.appendChild(item(r, indent)));
  };
  section("House", house, false);
  section("Rooms", rooms, false);
  areaNames.forEach((a) => section(a ? a : "Devices with no room",
    byArea.get(a).slice().sort(byName), true));
  if (!any) {
    rail.appendChild(el("div", "kempty small", find ? "No room or device matches."
      : "Nothing is filed under a room or device yet."));
  }
}

function paintFactActive() {
  const box = $("#kActive");
  if (!box) return;
  box.textContent = "";
  const parts = [];
  if (factsView.subject) {
    const s = ((factsView.facets || {}).subjects || []).find((x) => x.id === factsView.subject);
    parts.push(["About", s ? factSubjectName(s) : factSubjectLabel(factsView.subject),
      () => { factsView.subject = ""; }]);
  }
  if (factsView.kind) parts.push(["Kind", FACT_KIND_WORDS[factsView.kind], () => { factsView.kind = ""; }]);
  if (factsView.source) parts.push(["Taught by", kSourceLabel(factsView.source), () => { factsView.source = ""; }]);
  if (factsView.q) parts.push(["Words", `“${factsView.q}”`, () => {
    factsView.q = ""; const i = $("#kKnownSearch"); if (i) i.value = "";
  }]);
  box.hidden = !parts.length;
  parts.forEach(([label, value, clear]) => {
    const tag = el("button", "filtertag");
    tag.type = "button";
    tag.appendChild(el("span", "ftlabel", label));
    tag.appendChild(el("span", null, value));
    tag.appendChild(el("span", "ftx", "✕"));
    tag.setAttribute("aria-label", `Remove filter ${label}: ${value}`);
    tag.addEventListener("click", () => { clear(); loadFacts(true); });
    box.appendChild(tag);
  });
  if (parts.length > 1) {
    const all = el("button", "btn-tertiary", "Clear all");
    all.type = "button";
    all.addEventListener("click", () => {
      factsView.subject = ""; factsView.kind = ""; factsView.source = ""; factsView.q = "";
      const i = $("#kKnownSearch"); if (i) i.value = "";
      loadFacts(true);
    });
    box.appendChild(all);
  }
}

function paintFacts() {
  const host = $("#kKnown");
  if (!host) return;
  host.textContent = "";
  paintFactChips();
  paintFactSources();
  paintFactSubjects();
  paintFactActive();
  const more = $("#kKnownMore");
  if (factsView.error) {
    host.appendChild(el("div", "kempty", factsView.error));
    if (more) more.classList.add("hidden");
    return;
  }
  const rows = factsView.rows;
  const filtered = factsView.q || factsView.kind || factsView.source || factsView.subject;
  if (!rows.length) {
    host.appendChild(el("div", "kempty", filtered
      ? "No facts match."
      : "Nothing yet. Tell brAIn something above."));
    if (more) more.classList.add("hidden");
    return;
  }
  if (filtered || factsView.total !== factsView.all) {
    host.appendChild(el("div", "kfsum",
      `${factsView.total} of ${factsView.all} facts`));
  }
  // Grouped by subject when sorted that way: the server sorts by the
  // subject's name, so a group is a run of consecutive rows.
  let group = null;
  rows.forEach((f) => {
    if (factsView.sort === "subject") {
      const key = String(f.subject || "house");
      if (key !== group) {
        group = key;
        const head = el("div", "kfgroup", factSubjectText(f));
        if (factSubjectText(f) !== key) tip(head, key);
        host.appendChild(head);
      }
    }
    host.appendChild(makeFactRow(f));
  });
  const hidden = Math.max(0, factsView.total - rows.length);
  if (hidden) {
    host.appendChild(el("div", "kmore", `…and ${hidden} more.`));
  }
  if (more) {
    more.classList.toggle("hidden", !hidden);
    more.textContent = `Show ${Math.min(FACTS_PAGE, hidden)} more`;
  }
}

(function wireFactsBrowser() {
  const search = $("#kKnownSearch");
  if (!search) return;
  let timer = 0;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      factsView.q = search.value.trim();
      loadFacts(true);
    }, 250);
  });
  const sort = $("#kKnownSort");
  if (sort) sort.addEventListener("change", () => {
    factsView.sort = sort.value;
    loadFacts(true);
  });
  const source = $("#kKnownSource");
  if (source) source.addEventListener("change", () => {
    factsView.source = source.value;
    loadFacts(true);
  });
  const more = $("#kKnownMore");
  if (more) more.addEventListener("click", () => loadFacts(false));
  const subjSel = $("#kSubjectSel");
  if (subjSel) subjSel.addEventListener("change", () => {
    factsView.subject = subjSel.value;
    loadFacts(true);
  });
  const find = $("#kSubjectFind");
  if (find) find.addEventListener("input", () => {
    factsView.subjectFind = find.value;
    paintFactSubjects();
  });
})();

// The list and its count, drawn from the one payload that carries both.
function takeQueue(inbox, pending) {
  const items = inbox || [];
  const factsEl = $("#kFacts");
  if (!factsEl) return;
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
  // What it knows is one list: the facts, searched and filtered on the
  // server. The memory document and its filing queue are brAIn's own
  // machinery and are read only where they are mounted (⚙ › Memory), so
  // the knowledge payload is fetched only when that markup is present.
  loadFacts(true);
  if (!$("#kMemView") && !$("#kFacts")) return;
  let data;
  try {
    data = await api("api/knowledge");
  } catch (e) {
    toast("Could not load knowledge: " + e.message);
    return;
  }
  memState.lastState = data.memory_state;
  takeQueue(data.inbox, data.inbox_pending);
  renderMemory(data);
}

// ------------------------------------------------------ what it has measured
//
// Seven stores brAIn builds on its own, plus what it said this morning. Each
// one was readable from nowhere before this: a rhythm that has not gathered
// enough days, a baseline pass that stopped running and a house with nothing
// odd in it were three silences that looked identical from every screen.
//
// The row is the answer and the drill-down is the evidence. The row is a
// button because pressing it does something, and 44px because a row people
// miss is a row they stop pressing — the same rule `.actrow` carries.

const HOUSE_STORES = [
  ["rhythm", "When the house wakes"],
  ["baselines", "What is normal here"],
  ["thermal", "How rooms hold heat"],
  ["closures", "Doors and windows"],
  ["appliances", "Machines"],
  ["habits", "Habits"],
  ["energy", "Energy this week"],
];

async function refreshHouse() {
  // Two reads, in parallel, because they answer one question between them:
  // how far along each measurement is, and — for the ones that have landed
  // — the card brAIn wrote when it did. A tab that paid for them in series
  // would spinner over the half that had already arrived.
  await Promise.all([
    (async () => {
      try {
        houseState.data = await api("api/knowledge/house");
        houseState.error = "";
      } catch (e) {
        houseState.data = null;
        houseState.error = "Could not read what brAIn has measured: " + e.message;
      }
    })(),
    refreshMilestones(),
    refreshDeepReview(),
  ]);
  renderHouse();
}

// The milestone cards, and what is still being waited for. A card that
// exists and a measurement that has not landed are the same question asked
// at two different times, so they come from one endpoint and are rendered
// against one list of rows — a pending line under a store's own row reads
// as "this arrives when this lands", where a separate list at the bottom
// reads as a card that is missing.
async function refreshMilestones() {
  try {
    const data = await api("api/knowledge/cards");
    houseState.cards = {};
    (data.cards || []).forEach((c) => {
      if (c && c.store) houseState.cards[c.store] = c;
    });
    houseState.pending = data.pending || [];
    houseState.running = data.running || [];
  } catch (e) {
    // A tab that cannot read its cards still has seven measurements to
    // show, so this is not the tab's error — it is the absence of cards.
    houseState.cards = {};
    houseState.pending = [];
    houseState.running = [];
  }
}

const houseState = {
  data: null,      // the /api/knowledge/house payload
  error: "",       // why we could not read it — a sentence, never a blank tab
  open: "",        // which store's drill-down is open; one at a time
  cards: {},       // store id -> its milestone card, when one has been made
  pending: [],     // the milestones with no card yet, as {id, store, title}
  running: [],     // the milestone jobs in flight, as job states
  detail: {},      // store id -> its drill-down payload, fetched once
  entity: "",      // baselines: which entity's week is drawn
  buckets: null,   // baselines: that entity's 168 buckets
  filter: "",      // baselines: the search box
};

// Epoch seconds through the same two formatters everything else uses, so a
// stamp on this tab and a stamp in the ⚙ dialog can never read differently.
function agoAt(epoch) {
  const n = Number(epoch) || 0;
  if (!n) return "";
  return timeAgo(new Date(n * 1000).toISOString());
}

// "1:45 PM" — `fmtClock`'s shape, which is the one the rest of the panel
// uses. It was "01:45 PM" (`hour: "2-digit"`) here alone.
function clockAt(epoch) {
  const n = Number(epoch) || 0;
  if (!n) return "";
  return fmtClock(n);
}

// A clock time that says which day when it is not today. A bare "02:20 PM"
// read at 1:55 PM is a time that has not happened yet; the stamp was
// yesterday's.
function whenAt(epoch) {
  const n = Number(epoch) || 0;
  if (!n) return "";
  const d = new Date(n * 1000);
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(d) - day(new Date())) / 86400000);
  const clock = clockAt(n);
  if (diff === 0) return clock;
  if (diff === -1) return `yesterday ${clock}`;
  if (diff === 1) return `tomorrow ${clock}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${clock}`;
}

function dateAt(epoch) {
  const n = Number(epoch) || 0;
  if (!n) return "";
  return new Date(n * 1000).toLocaleDateString([],
    { month: "short", day: "numeric" });
}

// What each state says, in the store's own units. `collecting` is the one
// that has to carry a number: "not started" and "still going" are the same
// empty row otherwise, and only the second is worth waiting for.
function storeChipText(s) {
  const state = String(s.state || "not_started");
  if (state === "collecting") {
    const have = Number(s.have) || 0;
    const need = Number(s.need) || 0;
    const unit = s.unit || "days";
    let text = need ? `${have} of ${need} ${unit}` : `${have} ${unit}`;
    if (s.ready_at) text += ` · first answer ~${dateAt(s.ready_at)}`;
    return text;
  }
  if (state === "ready") {
    const ago = agoAt(s.updated_at);
    return ago ? `updated ${ago}` : "ready";
  }
  if (state === "stale") {
    const ago = agoAt(s.updated_at);
    return ago ? `stale since ${ago}` : "stale";
  }
  if (state === "unavailable") return "not available";
  return "not started";
}

// One row: the name, what it currently says, and the chip. `reason` sits
// under the summary whenever there is one — it is the "I could not look"
// half, and a state with no explanation under it is a state nobody can act
// on.
function makeStoreRow(id, name, store) {
  const s = store || {};
  const state = String(s.state || "not_started");
  const row = el("button", "krow");
  row.type = "button";
  row.dataset.store = id;
  row.dataset.state = state;
  row.setAttribute("aria-expanded", houseState.open === id ? "true" : "false");

  const txt = el("div", "ktxt");
  txt.appendChild(el("div", "kname", name));
  const summary = String(s.summary || "").trim();
  txt.appendChild(el("div", "ksum", summary
    || (state === "ready" ? "measured" : "nothing to show yet")));
  const reason = String(s.reason || "").trim();
  if (reason) txt.appendChild(el("div", "kwhy", reason));
  // A card behind a row nobody presses is a card nobody reads, so the row
  // says it has one. It is a mark on the row rather than the card itself
  // because seven sandboxed frames on one tab is the same "two open at
  // once" problem the drill-downs already answer.
  if (houseState.cards[id]) txt.appendChild(el("span", "kcardmark", "Card"));
  row.appendChild(txt);

  row.appendChild(el("span", "kchip", storeChipText(s)));
  row.addEventListener("click", () => toggleStore(id));
  return row;
}

// What a milestone job is doing, for the pending line. `queued` and
// `generating` are the two the endpoint sends; anything else is a state
// this panel does not know and says nothing about rather than guessing.
function milestoneRunning(store) {
  return (houseState.running || []).some((j) =>
    j && (j.store === store || j.milestone === store || j.id === store));
}

// The one line a measurement with no card yet gets, under its own row.
// Deliberately not a card-shaped placeholder: nothing has been written, and
// a greyed-out card reads as one that failed to load.
function makePendingLine(store, title) {
  const line = el("div", "kpending");
  line.dataset.store = store;
  line.appendChild(el("span", "kpendmark", "○"));
  line.appendChild(el("span", null, milestoneRunning(store)
    ? `Writing “${title}” now…`
    : `“${title}” — this card arrives when this measurement lands.`));
  return line;
}

// A milestone card, rendered the way an insight card is: title, summary,
// highlights, then the sandboxed visualization through `makeFrame`, which
// is the one route from an `html` payload to a frame. There is no
// regenerate/edit/feedback/delete menu — a milestone is not a card you
// keep re-running, it is the thing brAIn wrote the day it worked something
// out — so the single control is "make it again from the numbers as they
// are now".
function makeMilestoneCard(card) {
  const box = el("article", "card kcard");
  box.dataset.milestone = card.id;

  const head = el("div", "card-head");
  head.appendChild(el("span", "cicon", "🎓"));
  const titles = el("div", "ctitles");
  titles.appendChild(el("div", "cat", "What brAIn worked out"));
  titles.appendChild(el("h3", null, card.title || "A measurement landed"));
  head.appendChild(titles);
  box.appendChild(head);

  if (card.summary) box.appendChild(el("div", "summary", card.summary));

  const highlights = Array.isArray(card.highlights) ? card.highlights : [];
  if (highlights.length) {
    const hls = el("div", "highlights");
    highlights.forEach((h) => {
      if (!h || !h.label) return;
      const cell = el("div", "hl");
      cell.appendChild(el("div", "l", String(h.label)));
      cell.appendChild(el("div", "v", String(h.value != null ? h.value : "—")));
      hls.appendChild(cell);
    });
    box.appendChild(hls);
  }

  if (card.html) box.appendChild(makeFrame(card));

  const foot = el("div", "foot");
  const when = dateAt(card.made_at);
  if (when) foot.appendChild(el("span", null, `Made ${when}`));
  const because = String(card.made_because || "").trim();
  if (because) foot.appendChild(el("span", "because", `· ${because}`));
  foot.appendChild(el("span", "spacer"));
  const again = el("button", "btn small", "Make this again");
  tip(again, "Write this card again from the numbers as they are now");
  again.addEventListener("click", () => remakeMilestone(card.id, again));
  foot.appendChild(again);
  box.appendChild(foot);
  return box;
}

// The one control. A 409 here is not a failure: the measurement really has
// no answer at the moment (a store rebuilt from a shorter history, a meter
// removed), and the endpoint says so in a sentence — so it is a toast in
// the ordinary voice rather than a red error about something nobody did
// wrong.
async function remakeMilestone(id, btn) {
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch(`api/knowledge/card/${encodeURIComponent(id)}/refresh`,
      { method: "POST", headers: { "Content-Type": "application/json" } });
    let body = {};
    try { body = await resp.json(); } catch (e) { body = {}; }
    if (!resp.ok) {
      toast(body.error || `Could not make it again (HTTP ${resp.status})`);
      return;
    }
    toast(body.queued
      ? "Writing it again — it'll appear here when it lands"
      : "Already being written");
    await refreshMilestones();
    renderHouse();
  } catch (e) {
    toast(e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderHouse() {
  const host = $("#kStores");
  const briefBox = $("#kBrief");
  if (!host || !briefBox) return;
  host.textContent = "";
  briefBox.textContent = "";

  if (houseState.error) {
    briefBox.appendChild(el("div", "kempty", houseState.error));
    host.appendChild(el("div", "kempty", houseState.error));
    return;
  }
  const data = houseState.data || {};
  renderBrief(briefBox, data);

  const stores = data.stores || {};
  const pending = {};
  (houseState.pending || []).forEach((m) => {
    if (m && m.store) pending[m.store] = m;
  });
  HOUSE_STORES.forEach(([id, name]) => {
    host.appendChild(makeStoreRow(id, name, stores[id]));
    // The pending line rides with its row, always — it is one muted
    // sentence, and what it says is about this measurement.
    if (pending[id]) {
      host.appendChild(makePendingLine(id, pending[id].title || name));
    }
    // The card opens with the row, above the evidence: the row is the
    // answer, the card is what brAIn wrote about it, and the drill-down
    // is the numbers underneath.
    if (houseState.open === id) {
      if (houseState.cards[id]) {
        host.appendChild(makeMilestoneCard(houseState.cards[id]));
      }
      host.appendChild(makeDrill(id));
    }
  });
}

// What brAIn said this morning, or the one sentence explaining why it said
// nothing. "Off" and "nothing was worth saying" are different answers and
// only the first has something to do about it — which is why the off case
// names the tab the switch is on rather than saying "no brief today".
function renderBrief(box, data) {
  const brief = data.brief || {};
  if (!brief.enabled) {
    box.appendChild(el("p", "kbrieftext off",
      "The morning brief is off — turn it on in the add-on's Configuration "
      + "tab once a notify service is set."));
    return;
  }
  const text = String(brief.text || "").trim();
  if (text) {
    const when = new Date((Number(brief.last_sent) || 0) * 1000);
    const today = new Date();
    const sameDay = when.toDateString() === today.toDateString();
    box.appendChild(el("div", "kbriefwhen", brief.last_sent
      ? (sameDay ? `This morning, ${clockAt(brief.last_sent)}`
                 : `${dateAt(brief.last_sent)}, ${clockAt(brief.last_sent)}`)
      : "The last brief"));
    box.appendChild(el("p", "kbrieftext", text));
  } else if (brief.error) {
    box.appendChild(el("p", "kbrieftext off",
      `The last brief did not go out: ${brief.error}`));
  } else {
    // The brief's whole design is a refusal — it is silent most mornings on
    // purpose — so silence is reported as the working state it is.
    box.appendChild(el("p", "kbrieftext off",
      "Nothing was worth saying this morning. The brief only goes out when "
      + "something has changed."));
  }
  // The week's report rides under it when there is one: same kind of thing,
  // a different window, and nowhere else to read it back.
  const weekly = data.weekly || {};
  const wtext = String(weekly.text || "").trim();
  if (weekly.enabled && wtext) {
    box.appendChild(el("div", "kbriefwhen",
      weekly.last_sent ? `This week — ${dateAt(weekly.last_sent)}` : "This week"));
    box.appendChild(el("p", "kbrieftext", wtext));
  }
}

// One drill-down at a time: two open at once turns a list of seven answers
// into a page nobody can see the shape of.
async function toggleStore(id) {
  if (houseState.open === id) {
    houseState.open = "";
    renderHouse();
    return;
  }
  houseState.open = id;
  renderHouse();
  if (houseState.detail[id] !== undefined) return;
  try {
    houseState.detail[id] = await api(`api/knowledge/house/${id}`);
  } catch (e) {
    houseState.detail[id] = { error: e.message };
  }
  if (houseState.open === id) renderHouse();
}

// A store's payload holds its rows under whichever name that store calls
// them. Reading several is not laxness — it is the same "I could not tell"
// rule the checks carry: a shape we do not recognise is reported as nothing
// measured, never as an empty house.
function houseRows(payload, keys) {
  // Two of these routes answer with a bare list (`_baselines_rows`,
  // `_closure_rows`) and the rest with an object naming one. Both are the
  // route's own shape and neither is wrong; what would be wrong is a
  // renderer that only knows one and reports the other as an empty house.
  if (Array.isArray(payload)) return payload.slice();
  for (const key of keys) {
    const value = payload && payload[key];
    if (Array.isArray(value)) return value.slice();
    if (value && typeof value === "object") {
      return Object.keys(value).map((k) => ({ id: k, entity_id: k, ...value[k] }));
    }
  }
  return [];
}

function drillEmpty(id, message) {
  const box = el("div", "kdrill");
  box.dataset.store = id;
  box.appendChild(el("div", "kempty", message));
  return box;
}

function num(v, digits) {
  const n = Number(v);
  if (!isFinite(n)) return "";
  return digits ? n.toFixed(digits) : String(Math.round(n));
}

function makeDrill(id) {
  const payload = houseState.detail[id];
  if (payload === undefined) return drillEmpty(id, "Reading…");
  if (payload && payload.error) {
    return drillEmpty(id, `Could not read it: ${payload.error}`);
  }
  const store = ((houseState.data || {}).stores || {})[id] || {};
  const box = el("div", "kdrill");
  box.dataset.store = id;
  const drawn = ({
    rhythm: drillRhythm, baselines: drillBaselines, thermal: drillThermal,
    closures: drillClosures, appliances: drillAppliances, habits: drillHabits,
    energy: drillEnergy,
  }[id] || (() => null))(box, payload || {});
  if (!drawn) {
    // Nothing to draw is the store's own answer, in the store's own words:
    // "no ZHA in this house" and "the pass has not run" are different, and
    // only the store knows which this is.
    box.appendChild(el("div", "kempty", store.reason
      || "Nothing measured yet — it fills in as the house records more."));
  }
  return box;
}

function drillTable(box, head, rows) {
  if (!rows.length) return false;
  const wrap = el("div", "ktablewrap");
  const table = el("table", "ktable");
  const thead = el("thead");
  const hr = el("tr");
  head.forEach((h) => hr.appendChild(el("th", null, h)));
  thead.appendChild(hr);
  table.appendChild(thead);
  const body = el("tbody");
  rows.forEach((cells) => {
    const tr = el("tr");
    cells.forEach((c) => tr.appendChild(el("td", null, c)));
    body.appendChild(tr);
  });
  table.appendChild(body);
  wrap.appendChild(table);
  box.appendChild(wrap);
  return true;
}

// ---- rhythm: when the house gets up and when it settles, weekdays and
// weekends apart, because one number over both is wrong on all seven days.
function drillRhythm(box, payload) {
  const rows = [];
  [["weekday", "Weekdays"], ["weekend", "Weekends"]].forEach(([key, label]) => {
    const part = payload[key] || {};
    const cell = (shape) => {
      if (!shape || !shape.at) return "not measured yet";
      const spread = Number(shape.spread_min) || 0;
      return spread ? `${shape.at} ± ${Math.round(spread)} min` : shape.at;
    };
    const days = (part.wakes || {}).days || (part.settles || {}).days || 0;
    rows.push([label, cell(part.wakes), cell(part.settles),
               days ? `${days} days` : "—"]);
  });
  return drillTable(box, ["", "Wakes", "Settles", "Measured over"], rows);
}

// ---- baselines: 480-odd entities is a list nobody scrolls, so it is a
// search box, and the week itself is a picture — 168 numbers in a table is
// data rather than an answer.
function drillBaselines(box, payload) {
  const rows = houseRows(payload, ["entities", "rows", "measured"]);
  if (!rows.length) return false;

  const find = el("input", "kfind");
  find.type = "search";
  find.placeholder = "Find a sensor…";
  find.setAttribute("aria-label", "Find a sensor");
  find.value = houseState.filter;
  find.addEventListener("input", () => {
    houseState.filter = find.value;
    paintBaselineList(list, rows);
  });
  box.appendChild(find);

  const list = el("div", "kfindlist");
  box.appendChild(list);
  paintBaselineList(list, rows);

  const chart = el("div", "kchart");
  chart.id = "kBaselineChart";
  box.appendChild(chart);
  paintBaselineChart(chart);
  return true;
}

function paintBaselineList(list, rows) {
  const q = houseState.filter.trim().toLowerCase();
  list.textContent = "";
  const shown = rows.filter((r) => !q
    || String(r.entity_id || "").toLowerCase().includes(q)
    || String(r.name || "").toLowerCase().includes(q)).slice(0, 40);
  if (!shown.length) {
    list.appendChild(el("div", "kempty", "Nothing here by that name."));
    return;
  }
  shown.forEach((r) => {
    const id = String(r.entity_id || r.id || "");
    const btn = el("button", "kpick" + (houseState.entity === id ? " on" : ""),
      r.name || id);
    btn.type = "button";
    if (r.flat) btn.appendChild(el("span", "kflag", "flat"));
    btn.addEventListener("click", () => pickBaseline(id, r.name || id));
    list.appendChild(btn);
  });
}

async function pickBaseline(entityId, name) {
  houseState.entity = entityId;
  houseState.entityName = name || entityId;
  houseState.buckets = null;
  renderHouse();
  let data;
  try {
    const res = await api(`api/baselines?entity_id=${encodeURIComponent(entityId)}`);
    // The route answers with the whole store's progress and the one entity
    // under `baseline`; the entity is what the chart is about.
    data = res.baseline || (res.buckets ? res : null)
      || { empty: true, error: res.error || "" };
  } catch (e) {
    data = { error: e.message };
  }
  if (houseState.entity !== entityId) return;
  houseState.buckets = data;
  const chart = $("#kBaselineChart");
  if (chart) paintBaselineChart(chart);
}

const SVG_NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs) => {
  const node = document.createElementNS(SVG_NS, tag);
  Object.keys(attrs || {}).forEach((k) => node.setAttribute(k, attrs[k]));
  return node;
};
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// The bucket index Home Assistant's own week uses: hour of the week, Monday
// first. `getDay()` is Sunday-first, so the shift is not cosmetic — an
// unshifted "now" marker points at the wrong day, which is the one thing a
// marker must not do.
function nowBucket() {
  const now = new Date();
  return ((now.getDay() + 6) % 7) * 24 + now.getHours();
}

// A week of one sensor: the median as a line, the spread as a band around
// it, and a mark where we are now. A bucket with no samples breaks the line
// rather than being drawn through — "nothing measured at 3am on a Tuesday"
// is not the same claim as a number.
function paintBaselineChart(chart) {
  chart.textContent = "";
  if (!houseState.entity) {
    chart.appendChild(el("div", "kempty",
      "Pick a sensor to see what it normally reads, hour by hour."));
    return;
  }
  const data = houseState.buckets;
  if (!data) {
    chart.appendChild(el("div", "kempty", "Reading…"));
    return;
  }
  if (data.error) {
    chart.appendChild(el("div", "kempty", `Could not read it: ${data.error}`));
    return;
  }
  if (data.flat) {
    chart.appendChild(el("div", "kempty",
      "This one never moves, so it has no spread and no baseline — which is "
      + "an answer, not a gap."));
    return;
  }
  const buckets = data.buckets || {};
  const points = [];
  for (let i = 0; i < 168; i += 1) {
    const b = buckets[String(i)] || buckets[i];
    if (!b || !isFinite(Number(b.median))) { points.push(null); continue; }
    points.push({ i, m: Number(b.median), s: Math.abs(Number(b.spread) || 0) });
  }
  const real = points.filter(Boolean);
  if (!real.length) {
    chart.appendChild(el("div", "kempty",
      "No hour of the week has enough samples yet."));
    return;
  }

  const W = 700;
  const H = 190;
  const PAD_L = 46;
  const PAD_B = 22;
  const PAD_T = 10;
  let lo = Math.min(...real.map((p) => p.m - p.s));
  let hi = Math.max(...real.map((p) => p.m + p.s));
  if (hi - lo < 1e-6) { hi += 0.5; lo -= 0.5; }
  const x = (i) => PAD_L + (i / 167) * (W - PAD_L - 8);
  const y = (v) => PAD_T + (1 - (v - lo) / (hi - lo)) * (H - PAD_T - PAD_B);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, class: "kweek",
    role: "img",
    "aria-label": `What ${houseState.entityName || houseState.entity} normally reads, `
      + "per hour of the week",
  });

  // Day boundaries, labelled. A chart of 168 unlabelled columns is a
  // texture; the labels are what make it a week.
  for (let d = 0; d < 7; d += 1) {
    if (d) svg.appendChild(svgEl("line", {
      class: "kgrid", x1: x(d * 24), x2: x(d * 24), y1: PAD_T, y2: H - PAD_B }));
    const tick = svgEl("text", {
      class: "ktick", x: x(d * 24 + 12), y: H - 6, "text-anchor": "middle" });
    tick.textContent = DAY_NAMES[d];
    svg.appendChild(tick);
  }
  // Two value ticks: the top and the bottom of what this sensor does.
  const unit = data.unit ? ` ${data.unit}` : "";
  [[hi, PAD_T + 4], [lo, H - PAD_B]].forEach(([v, ty]) => {
    const t = svgEl("text", { class: "ktick", x: PAD_L - 6, y: ty,
                              "text-anchor": "end" });
    t.textContent = `${num(v, Math.abs(v) < 10 ? 1 : 0)}${unit}`;
    svg.appendChild(t);
  });

  // The band and the line, in segments: a gap in the data is a gap here.
  let run = [];
  const flush = () => {
    if (run.length > 1) {
      const top = run.map((p) => `${x(p.i)},${y(p.m + p.s)}`);
      const bottom = run.slice().reverse().map((p) => `${x(p.i)},${y(p.m - p.s)}`);
      svg.appendChild(svgEl("polygon", {
        class: "kband", points: top.concat(bottom).join(" ") }));
      svg.appendChild(svgEl("polyline", {
        class: "kline", points: run.map((p) => `${x(p.i)},${y(p.m)}`).join(" ") }));
    } else if (run.length === 1) {
      svg.appendChild(svgEl("circle", {
        class: "kline", cx: x(run[0].i), cy: y(run[0].m), r: 1.6 }));
    }
    run = [];
  };
  points.forEach((p) => { if (p) run.push(p); else flush(); });
  flush();

  // Where we are now, so the picture answers "is this hour unusual" without
  // anybody counting columns.
  const nb = nowBucket();
  svg.appendChild(svgEl("line", {
    class: "know", x1: x(nb), x2: x(nb), y1: PAD_T, y2: H - PAD_B }));

  chart.appendChild(svg);
  const foot = el("div", "kchartfoot",
    `${houseState.entityName || houseState.entity} · ${real.length} of 168 hours measured`
    + (data.overall && isFinite(Number(data.overall.median))
        ? ` · usually ${num(data.overall.median, 1)}${unit}` : "")
    + (data.trend && data.trend.per_day
        ? ` · drifting ${num(data.trend.per_day, 2)}${unit} a day` : ""));
  chart.appendChild(foot);
}

// ---- thermal: two numbers per room, sorted by the one people have an
// intuition for. τ is the time constant — how long the room takes to give up
// most of its heat — and it is the reciprocal of the loss rate.
function drillThermal(box, payload) {
  const rooms = houseRows(payload, ["rooms", "entities", "rows"]);
  if (!rooms.length) return false;
  const sorted = rooms.slice().sort((a, b) =>
    (Number(a.tau_h) || 1e9) - (Number(b.tau_h) || 1e9));
  const rows = sorted.map((r) => [
    r.name || r.entity_id || r.id || "",
    num(r.k, 3) || "—",
    num(r.tau_h, 1) || "—",
    r.gain != null ? `${num(r.gain, 2)}°/h` : "—",
    r.hours_to_warm != null ? `${num(r.hours_to_warm, 1)} h` : "—",
  ]);
  const ok = drillTable(box,
    ["Room", "Loss k /h", "τ hours", "Gain", "To warm"], rows);
  thermalReference(box, payload);
  return ok;
}

// Every room above is measured against ONE outdoor thermometer, so which
// one, and why, is said under the table — and the person who knows better
// can change it. A reference nobody can check is one nobody can correct.
// Drawn even when no room was measured, because a wrong reference is the
// likeliest reason none was. The choice is a panel setting
// (`thermal_outdoor`) and takes effect at the next measuring pass, which
// is started on the spot rather than left for tonight.
function thermalReference(box, payload) {
  const cands = Array.isArray(payload.outdoor_candidates)
    ? payload.outdoor_candidates : [];
  if (!payload.outdoor && !cands.length) return;
  const wrap = el("div", "kref");
  wrap.appendChild(el("div", "kfoot", payload.outdoor
    ? `Measured against ${payload.outdoor}${payload.unit ? ` (${payload.unit})` : ""}.`
    : "No outdoor reference yet."));
  if (payload.outdoor_why) wrap.appendChild(el("div", "kfoot", payload.outdoor_why));
  const choice = payload.outdoor_choice || "";
  if (choice && choice !== payload.outdoor) {
    wrap.appendChild(el("div", "kfoot",
      `${choice} was chosen and is measured against from the next measuring pass.`));
  }
  if (cands.length) {
    const label = el("label", "kreflabel", "Outdoor reference ");
    const sel = el("select", "sel");
    sel.appendChild(new Option("Let brAIn choose", ""));
    const listed = new Set();
    cands.forEach((c) => {
      listed.add(c.entity_id);
      sel.appendChild(new Option(
        `${c.name || c.entity_id} (${c.entity_id})`
        + (c.ruled_out ? ` — ${c.ruled_out}` : ""), c.entity_id));
    });
    if (choice && !listed.has(choice)) sel.appendChild(new Option(choice, choice));
    sel.value = choice;
    sel.addEventListener("change", async () => {
      sel.disabled = true;
      try {
        await api("api/settings", {
          method: "PUT", body: JSON.stringify({ thermal_outdoor: sel.value || null }) });
        // A 409 is a pass already running, which will read the choice too.
        await api("api/baselines/run", { method: "POST" }).catch(() => null);
        toast(sel.value
          ? `Re-measuring the rooms against ${sel.value} — a few minutes`
          : "Re-measuring, with brAIn choosing the reference — a few minutes");
      } catch (e) {
        toast(e.message);
      } finally {
        sel.disabled = false;
      }
    });
    label.appendChild(sel);
    wrap.appendChild(label);
  }
  box.appendChild(wrap);
}

// ---- closures: how much of each hour of the week each door is open. A
// number per hour is the measurement; the block is what makes it readable.
function drillClosures(box, payload) {
  const rows = houseRows(payload, ["entities", "closures", "rows"]);
  if (!rows.length) return false;
  rows.slice(0, 12).forEach((r) => {
    const wrap = el("div", "kheat");
    wrap.appendChild(el("div", "kheatname",
      `${r.name || r.entity_id || r.id}`
      + (r.overall != null ? ` — open ${num(Number(r.overall) * 100)}% of the time` : "")));
    const grid = el("div", "kheatgrid");
    const buckets = r.buckets || {};
    for (let d = 0; d < 7; d += 1) {
      const label = el("span", "kheatday", DAY_NAMES[d]);
      grid.appendChild(label);
      for (let h = 0; h < 24; h += 1) {
        const key = String(d * 24 + h);
        // The route sends the open fraction itself; the store it reads keeps
        // `{open, hours}`. Either is a fraction and neither is a missing
        // bucket — which is `null`/absent, and a different claim.
        const raw = key in buckets ? buckets[key] : buckets[d * 24 + h];
        const value = (raw && typeof raw === "object") ? raw.open : raw;
        const cell = el("span", "kcell");
        if (value === undefined || value === null) {
          // An hour nobody watched is a different answer from an hour it was
          // never open in, and both are invisible if they share a colour.
          cell.classList.add("unwatched");
          cell.title = `${DAY_NAMES[d]} ${h}:00 — not watched`;
        } else {
          const open = Math.max(0, Math.min(1, Number(value) || 0));
          cell.style.opacity = String(0.10 + open * 0.90);
          cell.title = `${DAY_NAMES[d]} ${h}:00 — open ${num(open * 100)}%`;
        }
        grid.appendChild(cell);
      }
    }
    wrap.appendChild(grid);
    box.appendChild(wrap);
  });
  box.appendChild(el("div", "kfoot",
    "Darker is more often open. A pale square is an hour nothing watched."));
  return true;
}

// ---- appliances: the watts this machine itself runs at, never a number
// somebody typed, plus what it is doing right now.
function drillAppliances(box, payload) {
  const rows = houseRows(payload, ["appliances", "entities", "rows"]);
  if (!rows.length) return false;
  const table = rows.map((r) => [
    r.name || r.entity_id || r.id || "",
    r.idle_w != null ? `${num(r.idle_w)} W` : "—",
    r.busy_w != null ? `${num(r.busy_w)} W` : "—",
    r.threshold_w != null ? `${num(r.threshold_w)} W` : "—",
    r.settle_min != null ? `${num(r.settle_min)} min` : "—",
    // What it is doing NOW is a live fetch and can fail on its own — an
    // empty `now` is the recorder not answering, which is not "idle".
    ((r.now || {}).state || r.state || "—"),
  ]);
  const ok = drillTable(box,
    ["Machine", "Idle", "Running", "Threshold", "Quiet phase", "Now"], table);
  if (ok && payload.live_error) {
    box.appendChild(el("div", "kfoot",
      `What each is doing now could not be read: ${payload.live_error}`));
  }
  return ok;
}

// ---- habits: what you do by hand often enough to be a habit, and the rules
// you keep undoing. Both are counts with denominators — a count on its own
// reports "six times in a fortnight" and "six times in two months" the same.
function drillHabits(box, payload) {
  // `routines` is an object about the ledger with the mined rows inside it,
  // not a list — reading it as one would turn three counts into three rows.
  const habits = houseRows(payload.routines || {}, ["rows"]);
  const patterns = houseRows(payload, ["patterns"]);
  let drew = false;
  if (habits.length) {
    box.appendChild(el("h4", "kdrillhead", "What you do by hand"));
    drew = drillTable(box, ["What", "When", "Days", "Share", "Offer it?"],
      habits.map((r) => [
        `${r.name || r.entity_id || r.id || ""} → ${r.state || ""}`,
        r.at || "—",
        r.days != null ? `${r.days} of ${r.eligible_days ?? "?"}` : "—",
        r.share != null ? `${num(Number(r.share) * 100)}%` : "—",
        r.proposable === false ? "no" : (r.proposable ? "yes" : "—"),
      ])) || drew;
  }
  if (patterns.length) {
    box.appendChild(el("h4", "kdrillhead", "Rules you keep undoing"));
    drew = drillTable(box, ["Automation", "Times", "Days", "When"],
      patterns.map((r) => [
        r.name || r.automation || r.id || "",
        String(r.events ?? r.count ?? "—"),
        String(r.days ?? "—"),
        (r.from_hour != null && r.to_hour != null)
          ? `${String(r.from_hour).padStart(2, "0")}:00–${String(r.to_hour).padStart(2, "0")}:00`
          : "—",
      ])) || drew;
  }
  return drew;
}

// ---- energy: last week against the week before, both seven complete local
// days, because half of today against seven full days is a fall that is
// nothing but the clock.
function drillEnergy(box, payload) {
  // `available: false` is the store's own answer with its own reason on it —
  // "no energy configuration" and "the recorder had nothing to say" send
  // somebody to two different places, and neither is an empty table.
  if (payload.available === false) return false;
  const halves = [["energy", "Electricity"], ["cost", "Cost"]]
    .map(([key, label]) => [label, payload[key]])
    .filter(([, half]) => half && (half.this != null || half.last != null));
  if (!halves.length) return false;
  const rows = halves.map(([label, half]) => {
    const pct = half.change_pct;
    // The unit rides on each half, because a cost and a consumption are two
    // different units and one `unit` for both quotes the wrong one.
    const unit = half.unit ? ` ${half.unit}` : "";
    return [
      label,
      `${num(half.this, 1)}${unit}`,
      `${num(half.last, 1)}${unit}`,
      pct == null ? "not comparable"
                  : `${pct > 0 ? "+" : ""}${num(pct, 1)}%`,
      half.days != null ? `${half.days} days` : "—",
    ];
  });
  return drillTable(box,
    ["", "This week", "Week before", "Change", "Complete"], rows);
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
  btn.textContent = busy ? "Filing…" : "File into memory now";
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
  if (!$("#kMemMerging")) return;
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
    : "Queued — it lands at the next consolidation…";

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
    staleBox.textContent = `The last attempt to file memory did not finish: `
      + `${st.error}`;
  } else if (stale) {
    const when = stale >= 48 ? `${Math.round(stale / 24)} days`
                             : `${Math.round(stale)} hours`;
    staleBox.textContent = `Nothing has been filed into memory for ${when}, `
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
  if (!$("#kMemView")) return;
  const has = !!memState.text.trim();
  $("#kMemView").innerHTML = has ? mdToHtml(memState.text) : "";
  $("#kMemView").classList.toggle("hidden", !has);
  $("#kMemEmpty").classList.toggle("hidden", has);
}

function setMemEditing(on) {
  memState.editing = on;
  memState.dirty = false;
  if (!$("#kMemTa")) return;
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

$("#kMemEdit")?.addEventListener("click", () => {
  $("#kMemTa").value = memState.text.trim() ? memState.text : MEM_TEMPLATE;
  setMemEditing(true);
});
$("#kMemTa")?.addEventListener("input", () => {
  memState.dirty = true;
  $("#kMemDirty").classList.remove("hidden");
});
$("#kMemCancel")?.addEventListener("click", () => {
  if (memState.dirty &&
      !window.confirm("Discard your unsaved memory edits?")) return;
  setMemEditing(false);
  renderKnowledge();
});
// Run a consolidation pass now instead of waiting for the daily one. The
// document below is rewritten by it, so unsaved manual edits have to be
// settled first — same rule as teaching it a fact.
$("#kConsolidate")?.addEventListener("click", async () => {
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

$("#kMemSave")?.addEventListener("click", async () => {
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
      b.appendChild(el("span", "docslinktitle", sec.title));
      if (snippet) b.appendChild(el("span", "docssnippet", snippet));
      if (count > 1) b.appendChild(el("span", "docscount", `${count} matches`));
      b.addEventListener("click", () => selectDocs(sec.id));
      nav.appendChild(b);
    });
    return;
  }

  // Eight named groups, each a heading over its pages. No glyph on a row:
  // the title is what a page is called, and sixty emoji in one column were
  // sixty more things to read past.
  docGroups().forEach((g) => {
    nav.appendChild(el("div", "docsgroup", g.name));
    g.sections.forEach((sec) => {
      const b = el("button", "docslink"
        + (sec.id === docsState.section ? " active" : ""));
      b.appendChild(el("span", "docslinktitle", sec.title));
      b.addEventListener("click", () => selectDocs(sec.id));
      nav.appendChild(b);
    });
  });
}

// The guide's sections, grouped as `build-docs.py` emits them (already in
// group order). A section with no group is shown under "More" rather than
// dropped: a missing heading must not be a missing page.
function docGroups() {
  const out = [];
  (window.BRAIN_DOCS || []).forEach((sec) => {
    const name = sec.group || "More";
    let g = out.find((x) => x.name === name);
    if (!g) { g = { name, sections: [] }; out.push(g); }
    g.sections.push(sec);
  });
  return out;
}

// The contents fold. Wherever the nav sits beside the page it is always open
// (its summary is not rendered there); where it stacks above the page it
// starts shut, closes again once a section is picked, and opens while a
// search is typed so the hits are what you see.
const DOCS_NARROW = "(max-width: 860px)";
function docsNarrow() {
  return Boolean(window.matchMedia && window.matchMedia(DOCS_NARROW).matches);
}
function setDocsFold(open) {
  const fold = $("#docsNavFold");
  if (fold) fold.open = open || !docsNarrow();
}

function selectDocs(id, opts) {
  const sections = window.BRAIN_DOCS || [];
  const sec = sections.find((s) => s.id === id) || sections[0];
  if (!sec) return;
  const cur = $("#docsNavCurrent");
  if (cur) cur.textContent = sec.title;
  if (!(opts && opts.keepFold)) setDocsFold(false);
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
  setDocsFold(Boolean(docsState.query.trim()));
  // Jump straight to the best match so typing feels like it does something.
  if (hits && hits.length) selectDocs(hits[0].sec.id, { keepFold: true });
  else renderDocsNav();
});
if (window.matchMedia) {
  const mq = window.matchMedia(DOCS_NARROW);
  const onChange = () => setDocsFold(false);
  if (mq.addEventListener) mq.addEventListener("change", onChange);
}

// ----------------------------------------------------------- onboarding
// A fresh install has no cards. brAIn studies the home first, then
// proposes cards grounded in what it found — a generic card about a house
// it has never looked at is noise on every run, so there is deliberately
// no canned fallback.

const obState = { onboarded: true, phase: "learning", learning: null,
                  recommendations: [], shipped: [], sparse: false, missing: "",
                  notify: null,       // the step-0 answers, from onboarding.state()
                  notifyData: null,   // GET /api/onboarding/notify, fetched once
                  notifyManual: null, // the lines to paste, after a save
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

// Step 0's own payload: which notify services this house has, plus whatever
// was answered before. Fetched once, and a failure is not a step nobody can
// get past — the screen renders with an empty list and a Skip, which is the
// same shape the endpoint's own `error` produces.
async function loadNotifyStep() {
  if (obState.notifyData || obState.notifyLoading) return;
  obState.notifyLoading = true;
  try {
    obState.notifyData = await api("api/onboarding/notify");
  } catch (e) {
    obState.notifyData = { candidates: [], error: e.message, writable: false,
                           manual: [] };
  }
  obState.notifyLoading = false;
  renderOnboarding();
}

function hourOptions(sel, value) {
  sel.textContent = "";
  // The empty option is first and it is not a zero: "not set" and "midnight"
  // are different answers, and a picker that cannot say the first turns "no
  // quiet hours" into a silence from 00:00.
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "—";
  sel.appendChild(none);
  for (let h = 0; h < 24; h += 1) {
    const opt = document.createElement("option");
    opt.value = String(h);
    opt.textContent = `${String(h).padStart(2, "0")}:00`;
    sel.appendChild(opt);
  }
  sel.value = value == null || value === "" ? "" : String(Number(value));
}

function renderNotifyStep() {
  const data = obState.notifyData || {};
  const stored = obState.notify || {};
  const candidates = data.candidates || [];
  const list = $("#obNotifyList");
  list.textContent = "";

  const err = $("#obNotifyErr");
  // Two different empties. "Home Assistant did not answer" is something to
  // try again; "this house has no notify service" is a fact about the house
  // that nothing here can change — reporting either as the other sends
  // somebody off to fix the wrong thing.
  const reason = candidates.length ? ""
    : (data.error
      ? `${data.error} — brAIn could not list your notify services.`
      : "This house has no notify service set up, so there is nowhere for "
        + "brAIn to send anything yet. Add one in Home Assistant and you can "
        + "point brAIn at it later under ⚙ Settings.");
  err.textContent = reason;
  err.classList.toggle("hidden", !reason);

  const chosen = data.findings_notify_service
    || stored.findings_notify_service || "";
  candidates.forEach((c) => {
    const row = el("label", "obcard");
    const radio = el("input");
    radio.type = "radio";
    radio.name = "obnotify";
    radio.value = c.service;
    radio.checked = c.service === chosen;
    row.appendChild(radio);
    const body = el("div", "obcardbody");
    body.appendChild(el("div", "obcardtitle", c.label || c.service));
    body.appendChild(el("div", "obcardwhy", c.service));
    // Only a mobile app can carry the answer buttons a finding notification
    // puts on a message, which is the difference between reading about a
    // problem and settling it from the notification.
    body.appendChild(el("div", "obcardfocus", c.buttons
      ? "A phone — can carry answer buttons, so you can settle a finding "
        + "straight from the notification."
      : "Takes a message. No answer buttons on this one."));
    row.appendChild(body);
    list.appendChild(row);
  });

  // "No thanks" is an answer rather than the absence of one — it is what
  // stops the step being asked again, and it is offered even where there is
  // nothing to pick, because saying no is still worth recording.
  const none = el("label", "obcard");
  const noneRadio = el("input");
  noneRadio.type = "radio";
  noneRadio.name = "obnotify";
  noneRadio.value = "";
  noneRadio.checked = !chosen;
  none.appendChild(noneRadio);
  const noneBody = el("div", "obcardbody");
  noneBody.appendChild(el("div", "obcardtitle", "No thanks — don't notify me"));
  noneBody.appendChild(el("div", "obcardfocus",
    "Everything still lands on Today. Nothing reaches your phone."));
  none.appendChild(noneBody);
  list.appendChild(none);

  hourOptions($("#obQuietStart"), data.notify_quiet_start != null
    ? data.notify_quiet_start : stored.notify_quiet_start);
  hourOptions($("#obQuietEnd"), data.notify_quiet_end != null
    ? data.notify_quiet_end : stored.notify_quiet_end);
  // On by default whenever a service is picked, because that is the whole
  // point of having asked — a stored `false` is somebody's answer and is
  // kept, which is why the server stores it as an explicit boolean. It
  // follows the PICK and not just the stored value: on a fresh install
  // nothing is chosen when this first renders, so a box read once at render
  // time is a box that is off for everybody who then picks a phone.
  const brief = data.morning_brief;
  $("#obBrief").checked = brief == null ? !!chosen : !!brief;
  obState.briefTouched = brief != null;
  // The quiet hours and the brief are about a service; with none to pick,
  // they are boxes that decide nothing.
  $("#obNotifyOpts").classList.toggle("hidden", !candidates.length);
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
  const chose = obState.phase === "choosing"
    && (obState.recommendations.length || (obState.shipped || []).length
        || obState.sparse);
  // Step 0 comes first and it is RESUMABLE: `onboarding.state()` carries
  // whether it has been asked, so a browser closed on this screen reopens on
  // it rather than skipping the one question the rest of the flow assumes an
  // answer to. The manual block is a state of its own, because refreshing
  // the flow marks the step answered and would take the lines to paste away
  // with it.
  const asked = !!(obState.notify || {}).asked;
  const manual = !!(obState.notifyManual && obState.notifyManual.length);
  const step0 = !manual && !asked && !ready && !chose;
  if (step0) {
    loadNotifyStep();
    if (obState.notifyData) renderNotifyStep();
  }

  $("#obNotify").classList.toggle("hidden", !step0 || !obState.notifyData);
  $("#obManual").classList.toggle("hidden", !manual);
  $("#obLearn").classList.toggle("hidden", step0 || manual || ready || chose);
  $("#obRecommend").classList.toggle("hidden",
    step0 || manual || !ready || chose);
  $("#obChoose").classList.toggle("hidden",
    step0 || manual || !chose || obState.sparse);
  $("#obSparse").classList.toggle("hidden",
    step0 || manual || !chose || !obState.sparse);

  if (learning.complete && !learning.memory_ready) {
    $("#obLearnHint").textContent =
      "Studied everything — waiting for what it found to be filed into memory.";
  }

  // What the sessions have found, as it lands — newest first, a handful.
  // Shown while learning and while the suggestions are one press away,
  // never over the step-0 question or the list of cards to tick.
  const found = Array.isArray(learning.reveals) ? learning.reveals : [];
  const foundList = $("#obFoundList");
  foundList.textContent = "";
  found.forEach((r) => {
    const li = el("li", "obfoundrow");
    if (r.topic) li.appendChild(el("span", "obfoundtopic", r.topic));
    li.appendChild(el("span", "obfoundfact", r.fact));
    foundList.appendChild(li);
  });
  $("#obFound").classList.toggle("hidden",
    step0 || manual || chose || !found.length);

  // The one automation to try, when the recommend pass found a reason.
  const tryRule = obState.try_rule;
  $("#obTryBlock").classList.toggle("hidden", !tryRule || !tryRule.sentence);
  if (tryRule && tryRule.sentence) {
    $("#obTryText").textContent = tryRule.sentence;
    $("#obTryWhy").textContent = tryRule.why || "";
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
  $("#obCustomHead").classList.toggle("hidden",
    !obState.recommendations.length);

  // The shipped half: cards that already exist in the code and that this
  // house has the entities for. Ticked independently of the custom ones,
  // because they are a different kind of thing — one set gets CREATED from
  // what brAIn learned, the other is admitted to this home's set.
  const shipped = obState.shipped || [];
  const shipList = $("#obShipped");
  shipList.textContent = "";
  shipped.forEach((cat) => {
    const row = el("label", "obcard");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.dataset.shipped = cat.id;
    row.appendChild(cb);
    const body = el("div", "obcardbody");
    body.appendChild(el("div", "obcardtitle",
      `${cat.icon || "✨"}  ${cat.title}`));
    if (cat.why) body.appendChild(el("div", "obcardwhy", cat.why));
    body.appendChild(el("div", "obcardfocus", cat.description || ""));
    row.appendChild(body);
    shipList.appendChild(row);
  });
  $("#obShippedBlock").classList.toggle("hidden", !shipped.length);
  obChooseNote();
}

// What Finish will actually leave behind. Sending no shipped ids means NONE
// of them, and on a fresh install that is an empty Insights tab by design —
// which is a fine thing to choose and a terrible thing to discover, so the
// step says it before the button rather than the tab saying it after.
function obChooseNote() {
  const note = $("#obChooseNote");
  if (!note) return;
  const picked = $("#obChoose").querySelectorAll(
    "input[data-index]:checked, input[data-shipped]:checked").length;
  note.textContent = picked
    ? `${picked} card${picked === 1 ? "" : "s"} will be on your Insights tab. `
      + "You can add, edit or remove cards any time."
    : "Nothing is ticked, so your Insights tab will start empty. That is a "
      + "real choice — you can ask a question or add a card whenever you like.";
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

// Step 0. `writable: false` on the payload is the whole reason there is a
// second screen after this one: the answers are stored and used, and the
// add-on's Configuration tab will not show them, so the lines to paste are
// handed over rather than implied.
async function obSaveNotify(service, btn) {
  const body = {
    service,
    quiet_start: $("#obQuietStart").value || null,
    quiet_end: $("#obQuietEnd").value || null,
    brief: $("#obBrief").checked,
  };
  const res = await obCall("api/onboarding/notify", body, btn);
  if (!res) return;   // obCall has already toasted the sentence a 400 sends
  obState.notify = { ...(obState.notify || {}), ...res, asked: true };
  obState.notifyData = null;
  obState.notifyManual = res.manual || [];
  if (obState.notifyManual.length) {
    $("#obManualText").textContent = obState.notifyManual.join("\n");
  }
  renderOnboarding();
}

// The brief follows the pick until somebody touches it, and then it is
// theirs. Delegated, because the radios are rebuilt on every render — and
// on `#obNotify` rather than on the list, since the tick box is outside it.
$("#obNotify").addEventListener("change", (ev) => {
  const t = ev.target;
  if (!t) return;
  if (t.id === "obBrief") { obState.briefTouched = true; return; }
  if (t.name === "obnotify" && !obState.briefTouched) {
    $("#obBrief").checked = !!t.value;
  }
});

$("#obNotifySave").addEventListener("click", (ev) => {
  const picked = $("#obNotifyList").querySelector("input:checked");
  obSaveNotify(picked ? picked.value : "", ev.target);
});

// Skip is an answer too — it records that the step was asked, so a flow
// resumed tomorrow does not open on a question somebody has already
// declined. A server that will not take it must not trap the flow either,
// so the step stands down locally whatever happened.
$("#obNotifySkip").addEventListener("click", async (ev) => {
  await obCall("api/onboarding/notify",
    { service: "", quiet_start: null, quiet_end: null, brief: false },
    ev.target);
  obState.notify = { ...(obState.notify || {}), asked: true };
  obState.notifyManual = null;
  renderOnboarding();
});

$("#obManualCopy").addEventListener("click", () =>
  copyOrSelect((obState.notifyManual || []).join("\n"), "Copied"));

$("#obManualNext").addEventListener("click", () => {
  obState.notifyManual = null;
  renderOnboarding();
});

$("#obStart").addEventListener("click", async (ev) => {
  const res = await obCall("api/onboarding/learn", undefined, ev.target);
  if (!res) return;
  // The syllabus takes the better part of half an hour, and for the whole of
  // it the Insights tab used to say nothing at all — indistinguishable, on a
  // first install, from an add-on that does not work. One card is already
  // generating, so say that rather than leaving somebody to find an empty
  // tab and draw the obvious conclusion.
  const first = res.first_card
    ? " Your first card is being written now — it'll be on the Insights tab."
    : "";
  toast((res.queued.length
    ? `Studying ${res.queued.length} topic(s) — this runs in the background`
    : "Already studied — checking what it found") + first);
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

// Two lists, one press. `shipped` is sent explicitly on every accept, so an
// empty array really does mean none of them — the server reads a missing key
// the same way, and the note above the button has already said what that
// leaves behind.
$("#obAccept").addEventListener("click", async (ev) => {
  const picked = Array.from($("#obList").querySelectorAll("input:checked"))
    .map((cb) => Number(cb.dataset.index));
  const shipped = Array.from($("#obShipped").querySelectorAll("input:checked"))
    .map((cb) => cb.dataset.shipped);
  const tryIt = !$("#obTryBlock").classList.contains("hidden")
    && $("#obTry").checked;
  const res = await obCall("api/onboarding/accept",
    { accept: picked, shipped, try_rule: tryIt }, ev.target);
  if (!res) return;
  obState.onboarded = true;
  const total = picked.length + shipped.length;
  const tried = res.tried
    ? " One automation is being simulated — its week starts on Today."
    : "";
  toast((total
    ? `${total} card${total === 1 ? "" : "s"} on your Insights tab.`
    : "Done — your Insights tab starts empty.") + tried);
  await Promise.all([refreshStatus(), refreshInsights()]);
  render();
});

// The note counts what is ticked across both lists, so it has to be
// recomputed as they are ticked — delegated, because the rows are rebuilt on
// every render.
$("#obChoose").addEventListener("change", (ev) => {
  if (ev.target && ev.target.type === "checkbox") obChooseNote();
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

// ------------------------------------------------------------- proposals
//
// The fifth kind of knowledge, and the only list in the panel that is not
// about something being wrong. It gets its own tab rather than a row on
// Findings for the reason the store's own header gives: a list of things
// you might want beside a list of things that are broken makes both
// worse.

const propState = {
  data: null,
  busy: 0,          // ts of the row a press is in flight for
  busyVerb: "",     // and which press, so the card can say "Adding it…"
  noteFor: 0,       // ts of the row whose reason box is open
  errorFor: 0,      // ts of the row whose accept was refused
  error: "",        // and the sentence it was refused with, verbatim
};

// The three verdicts, said the way somebody would say them. "Contradicted"
// is the word the store uses and it is the one nobody would use out loud:
// what it means is that you put the thing back the other way, and the card
// has to say that rather than make somebody learn a vocabulary to read it.
const TRIAL_WORDS = [
  ["agreed", "you did the same on"],
  ["disagreed", "nothing happened on"],
  ["contradicted", "you did the opposite on"],
];

function propTrialOver(row) {
  const ends = Number(row.trial_ends_at) || 0;
  return !!ends && Date.now() / 1000 >= ends;
}

// Which day of the week this is. `trial_result.days` is the server's own
// count of whole elapsed days and is preferred wherever there is one, so
// the card and the store cannot disagree about how far in this is; the
// clock is the fallback for a row nothing has graded yet.
function propTrialDay(row) {
  const started = Number(row.trial_started_at) || 0;
  const ends = Number(row.trial_ends_at) || 0;
  const total = started && ends
    ? Math.max(1, Math.round((ends - started) / 86400))
    : (propState.data?.trial_days || 7);
  const result = row.trial_result;
  const graded = result && !result.refused && result.days != null;
  const elapsed = graded
    ? Number(result.days) || 0
    : (started ? (Date.now() / 1000 - started) / 86400 : 0);
  return { day: Math.min(total, Math.max(1, Math.floor(elapsed))), total };
}

// Every number here comes off the payload. `firings` is capped at 50 and
// the counts are not, so adding the list up on the client would be a
// second answer to the same question that goes quietly wrong in the one
// week busy enough to matter.
function propTrialCounts(result) {
  const fired = Number(result.would_fire) || 0;
  const parts = [
    `would have fired ${fired} ${fired === 1 ? "time" : "times"}`,
  ];
  TRIAL_WORDS.forEach(([key, words]) => {
    const n = Number(result[key]) || 0;
    // The three add up to the firing count, so a zero clause carries
    // nothing and costs the end of a line somebody has to read.
    if (n) parts.push(`${words} ${n}`);
  });
  return parts.join(" · ");
}

function propTrialLine(row) {
  const over = propTrialOver(row);
  const { day, total } = propTrialDay(row);
  const lead = over ? "Trial over:" : `Day ${day} of ${total} ·`;
  const result = row.trial_result;
  // `refused` is branched on FIRST and its sentence is carried whole. A
  // trial brAIn could not replay has no counts at all, and rendering the
  // missing ones as zeros would say "it would never have fired" — a
  // different answer, about the automation rather than about brAIn.
  if (result && result.refused) {
    return `${lead} brAIn could not grade this trial — ${result.error
      || "this automation cannot be replayed"}`;
  }
  // Nothing has graded it yet: a row that started trialling since the
  // last checks pass. Saying so is not the same as showing zeros, which
  // read as a week of the automation never firing.
  if (!result) {
    return over
      ? `${lead} it was never graded — no checks pass ran while it was on trial.`
      : `${lead} replaying in shadow, nothing graded yet — the first report `
        + "lands at the next checks pass.";
  }
  if (!(Number(result.would_fire) || 0)) {
    return `${lead} it would not have fired ${over ? "at all" : "yet"}.`;
  }
  return `${lead} ${propTrialCounts(result)}.`;
}

function propReplayLine(row) {
  const r = row.replay;
  if (!r) return "";
  if (r.refused || r.error) return `Not replayable: ${r.error || "unknown"}`;
  // A proposal that EDITS an automation has two numbers and its whole
  // case is the pair: what the rule does today, and what it would do with
  // the condition on it. One of those on its own is a fact about an
  // automation rather than an argument for changing it.
  const was = row.replay_before;
  if (was && !was.refused && !was.error) {
    const before = was.would_run ?? 0;
    const after = r.would_run ?? 0;
    const days = Math.round(r.days ?? was.days ?? 30);
    const head = `Over the last ${days} days it ran ${before} `
      + `${before === 1 ? "time" : "times"}. With this condition it would `
      + `have run ${after}`;
    if (after === before) {
      // Worth saying out loud rather than dressing up: over the window
      // the recorder can answer for, the change would have made no
      // difference, and that is something to know before saying yes.
      return head + " — the same. Nothing it did in that window fell "
        + "inside those hours.";
    }
    const fewer = before - after;
    return head + ` — ${fewer} fewer, in the hours you keep putting it back.`;
  }
  const ran = r.would_run ?? 0;
  const blocked = r.blocked_by_conditions ?? 0;
  let line = `Over the last ${r.days ?? 30} days it would have run `
    + `${ran} ${ran === 1 ? "time" : "times"}`;
  if (blocked) line += `, with ${blocked} blocked by its conditions`;
  return line + ".";
}

// `api()` throws the response *text* on anything but a 2xx, which is the
// right shape everywhere else and the wrong one here: an accept that is
// refused answers 409 with a sentence AND the whole list, the row still
// on it. Losing that payload to an exception would mean refetching to
// find out nothing had changed.
async function propPost(ts, path, body) {
  const resp = await fetch(`api/proposal/${ts}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  return { ok: resp.ok, status: resp.status, data };
}

async function propAct(ts, path, body) {
  if (propState.busy) return;
  propState.busy = ts;
  propState.busyVerb = path;
  propState.errorFor = 0;
  propState.error = "";
  renderProposals();
  try {
    const { ok, status, data } = await propPost(ts, path, body);
    if (!ok) {
      // A refused yes is not a failure to mention in passing. The row is
      // still open and still in `proposals`, so the list re-renders from
      // the payload and the sentence goes ON THE CARD, where the buttons
      // were — a toast is gone in three seconds and this is the thing
      // somebody has to read before they can decide what to do instead.
      if (data && data.proposals) propState.data = data;
      const why = (data && data.error) || `HTTP ${status}`;
      if (data && (data.proposals || []).some((r) => r.ts === ts)) {
        propState.errorFor = ts;
        propState.error = why;
      } else {
        toast(why);
        if (!data || !data.proposals) await refreshProposals();
      }
      return;
    }
    propState.data = data;
    if (data.undo) {
      // The one press in the panel that changes /config, so the one that
      // owes a way back: the same toast-and-token contract every ending
      // on the Findings tab uses, and the same Undo button. The alias is
      // the proposal's own title by construction — `automation_writer`
      // writes it as the alias — so the toast names what somebody will
      // now find in their automations list.
      const alias = data.alias || data.proposal?.title || "the automation";
      // An edit did not add anything, and a toast saying it did would
      // send somebody looking for a second automation that is not there.
      toast(data.proposal?.edits
        ? `Changed “${alias}” in your automations`
        : `Added “${alias}” to your automations`, data.undo);
    } else if (data.learned) {
      toast("Noted — brAIn has written that down.");
    }
  } catch (err) {
    toast(String(err && err.message ? err.message : err));
    await refreshProposals();
  } finally {
    propState.busy = 0;
    propState.busyVerb = "";
    propState.noteFor = 0;
    renderProposals();
  }
}

// ---- playbooks -----------------------------------------------------------
//
// An emergency playbook's evidence is not a replay — there is no week
// with a smoke alarm in it — it is the LIST of what the automation would
// act on. So the card renders that list, grouped by what happens to each
// group, with anything protected shown as skipped rather than silently
// dropped: seeing that brAIn knows the valve is there and knows it may
// not touch it is the whole point of showing it.

// The config is never capped and this list is, so an over-long group says
// what it is not showing rather than disagreeing with the count quietly —
// the same rule the memory queue's list and count follow.
function propTargetLine(group, cap) {
  const targets = group.targets || [];
  const names = targets.slice(0, cap).map((t) => t.name || t.entity_id);
  const rest = targets.length - names.length;
  return names.join(", ") + (rest > 0 ? `, and ${rest} more` : "");
}

function propPlaybookBlock(row) {
  const book = row.playbook;
  if (!book) return null;
  const wrap = el("div", "propbook");
  const cap = book.card_max || 12;

  const sensors = book.sensors || [];
  if (sensors.length) {
    const where = [...new Set(sensors.map((s) => s.area).filter(Boolean))];
    wrap.appendChild(el("p", "propbookset",
      `Runs when any of ${sensors.length} sensor`
      + `${sensors.length === 1 ? "" : "s"} goes off`
      + (where.length ? ` — ${where.slice(0, 4).join(", ")}` : "") + "."));
  }

  (book.groups || []).forEach((group) => {
    const line = el("div", "propgroup");
    line.appendChild(el("span", "propverb",
      `${group.verb} (${(group.targets || []).length})`));
    line.appendChild(el("span", "propnames", propTargetLine(group, cap)));
    wrap.appendChild(line);
  });

  if ((book.notify || []).length) {
    const line = el("div", "propgroup");
    line.appendChild(el("span", "propverb", "Tells you"));
    line.appendChild(el("span", "propnames",
      `${book.notify.join(", ")} — naming the room it happened in`));
    wrap.appendChild(line);
  }

  (book.skipped || []).slice(0, cap).forEach((skip) => {
    const line = el("div", "propgroup skipped");
    line.appendChild(el("span", "propverb", "Skipped: protected"));
    line.appendChild(el("span", "propnames", skip.name || skip.entity_id));
    wrap.appendChild(line);
  });

  // The sentence that says what this will never do. It is on the card
  // rather than only in the docs because this is where somebody decides.
  if (book.note) wrap.appendChild(el("p", "propbooknote", book.note));
  return wrap;
}

// The rehearsal is fetched when the disclosure opens, never with the
// card: it reads every state in the house, and a tab of five playbooks
// would ask for that five times before anybody looked at one.
async function propRehearse(ts, body) {
  body.textContent = "";
  body.appendChild(el("p", "propbookset", "Reading the house…"));
  let data = null;
  try {
    data = await api(`api/playbook/${ts}/rehearsal`);
  } catch (err) {
    body.textContent = "";
    body.appendChild(el("p", "propbookset",
      `Could not read the current states: ${err && err.message ? err.message : err}`));
    return;
  }
  body.textContent = "";
  (data.groups || []).forEach((group) => {
    const line = el("div", "propgroup");
    const already = group.already
      ? ` (${group.already} already ${group.to || "there"})` : "";
    line.appendChild(el("span", "propverb",
      `${group.count} → ${group.to || "changed"}${already}`));
    line.appendChild(el("span", "propnames",
      (group.targets || []).map((t) => `${t.name || t.entity_id} — ${t.state}`)
        .join(", ")));
    body.appendChild(line);
  });
  if (!(data.groups || []).length) {
    body.appendChild(el("p", "propbookset",
      "This one only sends a notification."));
  }
  body.appendChild(el("p", "propbooknote", data.note || ""));
}

function propRehearsal(row) {
  const box = el("details", "propreh");
  const sum = el("summary", null, "Rehearse it — show me what it would do");
  box.appendChild(sum);
  const body = el("div", "propbookrows");
  box.appendChild(body);
  let loaded = false;
  box.addEventListener("toggle", () => {
    if (!box.open || loaded) return;
    loaded = true;
    propRehearse(row.ts, body);
  });
  return box;
}

// ---- scene swatches ------------------------------------------------------
//
// The payload carries HSV, because that is what a bulb holds — the frames
// ARE the colours the room will be. This is the only conversion the panel
// does, and it is here rather than on the server for the same reason
// BRight's preview does it here: a picture converted from something the
// house does not use is a picture of the conversion.

function propSwatchCss(light) {
  if (!light.on) return "transparent";
  const h = Number(light.h) || 0;
  const s = Math.max(0, Math.min(1, Number(light.s) || 0));
  const v = Math.max(0, Math.min(1, Number(light.v) || 0));
  // A dark swatch on a dark panel is invisible, so the LEVEL is drawn as
  // the swatch's own lightness floor rather than as its only signal: a
  // 10% night scene has to be readable as "on and very low", not as an
  // empty square that looks like "off".
  const l = 0.28 + 0.55 * v;
  return `hsl(${h} ${Math.round(s * 100)}% ${Math.round(l * 100)}%)`;
}

const SCENE_CAP_WORDS = {
  colour_temp: "colour temperature",
  colour: "colour only",
  brightness: "brightness only",
  onoff: "on/off only",
};

function propSceneBlock(row) {
  const scene = row.scene;
  if (!scene) return null;
  const wrap = el("div", "propscenes");
  (scene.preview || []).forEach((mood) => {
    const line = el("div", "propmood");
    line.appendChild(el("span", "propmoodname", mood.name));
    const strip = el("div", "propswatches");
    (mood.lights || []).forEach((light) => {
      const dot = el("span", `propswatch${light.on ? "" : " off"}`);
      dot.style.background = propSwatchCss(light);
      // The name and what the bulb can be told, because a swatch with no
      // label is a colour nobody can act on — and "on/off only" is why
      // one of them is a plain square.
      dot.dataset.tip = `${light.name} — ${
        light.on ? SCENE_CAP_WORDS[light.capability] || light.capability
                 : "off in this scene"}`;
      strip.appendChild(dot);
    });
    line.appendChild(strip);
    wrap.appendChild(line);
  });
  // Named under the swatches rather than in a tooltip: on a phone there
  // is no hover, and which bulb is which is the whole reading.
  const names = (scene.lights || []).map((l) => l.name).join(" · ");
  if (names) wrap.appendChild(el("p", "propscenelights", names));
  (scene.skipped || []).forEach((skip) => {
    const line = el("div", "propgroup skipped");
    line.appendChild(el("span", "propverb", "Skipped: protected"));
    line.appendChild(el("span", "propnames", skip.name || skip.entity_id));
    wrap.appendChild(line);
  });
  return wrap;
}

// ---- one-off intents -----------------------------------------------------
//
// Not proposals: a proposal is waiting on an answer and these are waiting on
// the HOUSE (or, for a refusal, on being read once). So they are counted
// apart and the badge never moves for them — but they share the card, because
// what somebody wants from both is the same: what it is, what it did, and one
// press.

function propIntentWhen(ts) {
  return ts ? whenAt(ts) : "";
}

function propIntentLine(row) {
  if (row.status === "refused") return row.refused || "brAIn will not arm this.";
  if (row.status === "fired") {
    const when = propIntentWhen(row.fired_at);
    return `It fired${when ? ` at ${when}` : ""} and switched itself off. It `
      + "is still in your automations until you remove it.";
  }
  if (row.overdue) {
    // A label, never a deletion. A fortnight of silence almost always means
    // the thing already happened and nobody told the house — and the answer
    // to that is a sentence with a press on it, not a file that changed
    // while somebody was not looking.
    return "It has been waiting a fortnight and has never fired. Remove it if "
      + "what you were waiting for already happened.";
  }
  return "Armed and waiting. It runs once, then switches itself off.";
}

async function propRemoveIntent(ts, refused) {
  if (propState.busy) return;
  propState.busy = ts;
  propState.busyVerb = "remove";
  renderProposals();
  try {
    const resp = await fetch(`api/intent/${ts}/remove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    let data = null;
    try { data = await resp.json(); } catch { data = null; }
    if (!resp.ok) {
      // The same contract an accept's refusal has: the row is still there and
      // the sentence goes on it, because this one reaches /config too.
      if (data && data.proposals) propState.data = data;
      propState.errorFor = ts;
      propState.error = (data && data.error) || `HTTP ${resp.status}`;
      return;
    }
    propState.data = data;
    if (data.undo) {
      toast(refused ? "Ignored" : "Removed it from your automations",
        data.undo);
    }
  } catch (err) {
    toast(String(err && err.message ? err.message : err));
    await refreshProposals();
  } finally {
    propState.busy = 0;
    propState.busyVerb = "";
    renderProposals();
  }
}

// ------------------------------------------------------------- activity
// What changed, and what changed it.
//
// Everything here is one fetch of Home Assistant's own logbook, mined
// server-side. Nothing is cached and nothing is stored: the window is a
// question somebody is asking now, and a cached copy of a stream is a
// second thing to keep true. Leaving the tab and coming back re-asks,
// which is also what makes "Later" mean now.
const actState = {
  end: null,        // epoch seconds; null means "up to now"
  hours: 24,
  cause: "",
  area: "",         // a room's name, or "-" for the things in none
  kind: "",         // an episodes subject: lights, doors, people…
  q: "",            // words in a device's name
  data: null,
  loading: false,
  open: "",         // "entity_id|started" of the row whose history is expanded
  why: null,
  // The one thing on this tab that spends. Kept per window rather than
  // per visit, and cleared by every window change (`refreshActivity`),
  // because a paragraph about Tuesday under Wednesday's rows is the one
  // answer worse than none.
  summary: null,
  summaryBusy: false,
  summaryError: "",
};

const CAUSE_WORDS = {
  brain: "brAIn",
  automation: "Automation",
  script: "Script",
  scene: "Scene",
  voice: "Voice",
  person: "Person",
  unattributed: "No cause recorded",
};

function actTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([],
    { hour: "2-digit", minute: "2-digit" });
}

// The window is a rolling one — `hours` back from `end` — so it is named as
// one. It was labelled "Today" and opened on yesterday evening's rows,
// which is the label lying about the list under it.
function actDayLabel(end, hours) {
  const h = hours || 24;
  if (!end) return `Last ${h} hours`;
  const d = new Date(end * 1000);
  return `${h} hours to `
    + d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })
    + ", " + actTime(end);
}

async function refreshActivity() {
  actState.loading = true;
  // The window is about to change (a day step, a cause filter), so what
  // was said about the old one no longer describes what is on screen.
  // The server caches it against the window, so coming back is free.
  actState.summary = null;
  actState.summaryError = "";
  renderActivity();
  const q = new URLSearchParams({ hours: String(actState.hours) });
  if (actState.end) q.set("end", String(Math.round(actState.end)));
  if (actState.cause) q.set("cause", actState.cause);
  if (actState.area) q.set("area", actState.area);
  if (actState.kind) q.set("kind", actState.kind);
  if (actState.q) q.set("q", actState.q);
  try {
    actState.data = await api("api/activity?" + q.toString());
  } catch (e) {
    // A window that could not be fetched is not an empty window, and the
    // difference is the whole design of this tab — so it says which.
    actState.data = { available: false, error: String(e.message || e),
                      actions: [], overrides: [], counts: {}, total: 0 };
  }
  actState.loading = false;
  renderActivity();
}

function renderActFilters(counts) {
  // One "Caused by" picker, no counts: the list under it is the count, and
  // a cause this window holds nothing for is left out because picking it
  // could only ever empty the list. The one somebody picked stays, so a
  // window that no longer holds it still shows what is selected.
  const sel = $("#actCause");
  if (!sel) return;
  const kinds = Object.keys(CAUSE_WORDS)
    .filter((k) => (counts[k] || 0) > 0 || actState.cause === k);
  sel.textContent = "";
  const all = el("option", null, "Anything");
  all.value = "";
  sel.appendChild(all);
  kinds.forEach((k) => {
    const opt = el("option", null, CAUSE_WORDS[k]);
    opt.value = k;
    sel.appendChild(opt);
  });
  sel.value = actState.cause;
}

// The room picker and the kind pills, off the window's own facets, which the
// server counts before those two filters — so a picker never offers only
// what is already on screen. A room or kind somebody picked stays listed
// when the window no longer holds it.
function renderActNarrow(data) {
  const sel = $("#actArea");
  if (sel) {
    const areas = data.areas || [];
    sel.textContent = "";
    const all = el("option", null, "Every room");
    all.value = "";
    sel.appendChild(all);
    areas.forEach((a) => {
      const opt = el("option", null, `${a.label} (${a.count})`);
      opt.value = a.id;
      sel.appendChild(opt);
    });
    if (actState.area && !areas.some((a) => a.id === actState.area)) {
      const opt = el("option", null, actState.area === "-" ? "No room" : actState.area);
      opt.value = actState.area;
      sel.appendChild(opt);
    }
    sel.value = actState.area;
  }
  const host = $("#actKinds");
  if (host) {
    host.textContent = "";
    const kinds = data.kinds || [];
    host.hidden = kinds.length < 2 && !actState.kind;
    const total = kinds.reduce((a, k) => a + k.count, 0);
    const all = [{ id: "", label: "Everything", count: total }].concat(kinds);
    // On a phone the same choice is one select: nine pills wrapped to five
    // rows, and with the filters above them the first screen of the tab
    // held no events at all.
    const pick = el("select", "sel actkindsel");
    pick.setAttribute("aria-label", "What kind of thing");
    all.forEach((k) => {
      const opt = el("option", null, `${k.label} (${k.count})`);
      opt.value = k.id;
      pick.appendChild(opt);
    });
    pick.value = actState.kind || "";
    pick.addEventListener("change", () => {
      actState.kind = pick.value;
      actState.open = "";
      refreshActivity();
    });
    host.appendChild(pick);
    all.forEach((k) => {
      const on = actState.kind === k.id;
      const b = el("button", "pill" + (on ? " active" : ""));
      b.type = "button";
      b.appendChild(el("span", null, k.label));
      b.appendChild(el("span", "pillcount", String(k.count)));
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.addEventListener("click", () => {
        actState.kind = k.id;
        actState.open = "";
        refreshActivity();
      });
      host.appendChild(b);
    });
  }
}

// How long an episode covered, in the units a person would say it in.
function epFor(secs) {
  const s = Math.max(0, Math.round(secs || 0));
  if (s < 60) return s + " s";
  const m = Math.round(s / 60);
  if (m < 60) return m + " min";
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h}h ${rest}m` : `${h}h`;
}

// What one row of this section is ABOUT. The three sentences are three
// different claims about the same shape of record and the SERVER decides
// which (`episodes.SUBJECTS[].reads`), because a renderer guessing would be
// a fourth answer: a momentary motion sensor's "span" is an artefact of
// when it last happened to fire, and reading it as a duration is how a
// hall sensor comes out as "on for 83 minutes".
function epWhen(ep, reads) {
  const at = actTime(ep.started);
  if (reads === "moment") {
    return ep.open ? `since ${at}` : `at ${at}`;
  }
  if (reads === "count") {
    const span = ep.count > 1 ? ` · ${at}–${actTime(ep.ended)}` : ` · ${at}`;
    return `${ep.count}×${span}`;
  }
  if (ep.open) return `since ${at} · ${epFor(ep.duration_s)} so far`;
  if (ep.duration_s < 60) return at;
  return `${at}–${actTime(ep.ended)} · ${epFor(ep.duration_s)}`;
}

// The state, in as few words as it takes. A single-change episode is one
// word; a run is where it started and where it ended.
function epStates(ep) {
  if (!ep.last || ep.last === ep.first) return ep.first || "";
  return `${ep.first} → ${ep.last}`;
}

// Empty for a row nothing claims. That was "No cause recorded" on every
// such row — 14,249 of 15,098 on a real house — which is one fact said
// fourteen thousand times; the foot says it once instead. A row nothing
// caused that began around a restart says so, because that IS its cause.
function epCause(ep) {
  if (!ep.cause || ep.cause === "unattributed") {
    return ep.near_restart ? "Around the Home Assistant restart" : "";
  }
  return (CAUSE_WORDS[ep.cause] || ep.cause) + (ep.by_name ? ": " + ep.by_name : "");
}

// What the house says now, where it disagrees with the logbook. A row
// read off `/states` rather than the logbook says where it came from,
// because the change it stands for is one the logbook did not record.
function epNote(ep) {
  if (ep.from_live) return "Home Assistant's current state — the logbook has no row for it";
  if (ep.live) return `now ${ep.live}`;
  return "";
}

function epKey(ep) {
  return (ep.entity_id || ep.kind || "") + "|" + Math.round(ep.started);
}

// When the house was empty — the one thing on this tab that Home Assistant
// holds every fact for and has never said, and the reason it is above the
// list rather than in it: it is the context the rows below are read in.
function renderAwayBand(host, away) {
  if (!away || !away.length) return;
  const box = el("div", "actaway");
  box.appendChild(el("span", "actawaylabel", "Nobody home"));
  box.appendChild(el("span", null, away.slice(0, 6).map((s) =>
    `${actTime(s.start)}–${s.ongoing ? "now" : actTime(s.end)}`).join(" · ")));
  host.appendChild(box);
}

// The paragraph, and the press that buys it. Rendered as three states,
// because "nobody has asked" and "it could not answer" are different
// things and only one of them is worth pressing again.
function renderSummary(host) {
  const sum = actState.summary;
  if (sum && sum.text) {
    const box = el("div", "actsum");
    box.appendChild(el("p", null, sum.text));
    const foot = el("div", "actsumfoot");
    foot.appendChild(el("span", null, sum.cached
      ? "brAIn read this window earlier" : "brAIn read this window"));
    const again = el("button", "btn tiny ghost", "Ask again");
    tip(again, "Spends one Claude run on this window. The rest of this tab "
      + "costs nothing and never has.");
    again.addEventListener("click", () => askActivitySummary(true));
    foot.appendChild(again);
    box.appendChild(foot);
    host.appendChild(box);
    return;
  }
  const row = el("div", "actask");
  const btn = el("button", "btn small",
    actState.summaryBusy ? "Reading the day…" : "Ask");
  btn.disabled = !!actState.summaryBusy;
  tip(btn, "What does this add up to? One Claude run over what is on "
    + "this screen; everything else here is read from the logbook.");
  btn.addEventListener("click", () => askActivitySummary(false));
  row.appendChild(btn);
  if (actState.summaryError) {
    row.appendChild(el("span", "actaskerr", actState.summaryError));
  }
  host.appendChild(row);
}

async function askActivitySummary(again) {
  if (actState.summaryBusy) return;
  actState.summaryBusy = true;
  actState.summaryError = "";
  if (again) actState.summary = null;
  renderActivity();
  const q = new URLSearchParams({ hours: String(actState.hours) });
  if (actState.end) q.set("end", String(Math.round(actState.end)));
  try {
    const data = await api("api/activity/summary?" + q.toString(),
                           { method: "POST" });
    actState.summary = { text: data.summary || "", cached: !!data.cached,
                         run_id: data.run_id || "" };
  } catch (e) {
    actState.summaryError = e.message || String(e);
  }
  actState.summaryBusy = false;
  renderActivity();
}


// The top line of What happened: the situation reading, in its own words.
// One read per visit, the same `/api/situation` the Resident keeps current.
async function refreshActNow() {
  let d = null;
  try { d = await api("api/situation"); } catch (_err) { d = null; }
  const node = $("#actNow");
  if (!node) return;
  node.textContent = "";
  if (!d) { node.hidden = true; return; }
  const mode = HOUSE_MODE_WORDS[d.house_mode] ? d.house_mode : "unknown";
  node.appendChild(el("b", "actnowmode", HOUSE_MODE_WORDS[mode]));
  if (d.sentence) {
    const names = d.names || {};
    const said = prettyText(String(d.sentence).replace(/\b[a-z_]+\.[a-z0-9_]+\b/g,
      (id) => names[id] || id));
    node.appendChild(el("span", "actnowsaid" + (d.sentence_stale ? " stale" : ""),
      d.sentence_stale ? `Earlier: ${said}` : said));
  }
  node.hidden = false;
}

function renderActivity() {
  const list = $("#actList");
  if (!list) return;
  const data = actState.data;
  $("#actRange").textContent = actDayLabel(actState.end, actState.hours);
  // "Later" is meaningless on the window that already ends now.
  $("#actNext").disabled = !actState.end;
  const head = $("#actSummary");
  if (head) head.textContent = "";

  if (actState.loading && !data) {
    list.innerHTML = `<div class="actempty">Reading the logbook&hellip;</div>`;
    return;
  }
  if (!data) { list.innerHTML = ""; return; }

  if (!data.available) {
    renderActFilters({});
    list.innerHTML = `<div class="actempty">Home Assistant's logbook could not be `
      + `read, so nothing here can say what happened or what caused it.`
      + (data.error ? ` <code>${esc(data.error)}</code>` : "")
      + ` The <code>logbook</code> integration is part of the default config; `
      + `if it has been removed from <code>configuration.yaml</code>, this tab `
      + `and the "automations you keep undoing" check both go quiet.</div>`;
    return;
  }

  renderActFilters(data.counts || {});
  renderActNarrow(data);
  const sections = data.sections || [];
  if (head) {
    renderAwayBand(head, data.away);
    if (sections.length) renderSummary(head);
  }

  if (!sections.length && (actState.area || actState.kind || actState.q)) {
    list.innerHTML = `<div class="actempty">Nothing matches in this window. `
      + `Try another room, a longer window, or clear the search.</div>`;
    return;
  }
  if (!sections.length) {
    list.innerHTML = `<div class="actempty">Nothing happened in this window.`
      + (data.dropped
         ? ` ${data.dropped.toLocaleString()} sensor readings did arrive — `
           + `a reading is not something that happened, so they are not listed.`
         : "")
      + `</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  sections.forEach((sec) => frag.appendChild(actSection(sec)));
  // What this list is NOT showing, said out loud. A view that silently
  // drops nine tenths of its input is the one it replaced.
  const foot = el("div", "actfoot");
  const shown = `${data.episodes} thing${data.episodes === 1 ? "" : "s"} `
    + `happened, across ${data.changes.toLocaleString()} changes`;
  foot.textContent = data.dropped
    ? `${shown}. ${data.dropped.toLocaleString()} sensor readings are not `
      + `listed — a reading is not something that happened.`
    : `${shown}.`;
  // Once, here, rather than on every row it is true of.
  const orphans = (data.counts || {}).unattributed || 0;
  if (orphans) {
    foot.textContent += ` ${orphans.toLocaleString()} of the changes have no `
      + `recorded cause: a wall switch and a device's own integration reach `
      + `Home Assistant the same way, so a row with nothing beside it is one `
      + `the logbook could not attribute.`;
  }
  frag.appendChild(foot);
  list.innerHTML = "";
  list.appendChild(frag);
}

function actSection(sec) {
  const box = el("section", "actsec");
  box.dataset.section = sec.id;
  const h = el("div", "actsechead");
  h.appendChild(el("h3", null, sec.label));
  h.appendChild(el("span", "actseccount", sec.total > sec.episodes.length
    ? `${sec.episodes.length} of ${sec.total}`
    : String(sec.total)));
  box.appendChild(h);
  sec.episodes.forEach((ep) => {
    const key = epKey(ep);
    const row = document.createElement("button");
    row.className = "actrow";
    row.dataset.cause = ep.cause;
    row.dataset.key = key;
    row.dataset.entity = ep.entity_id || "";
    if (ep.kind) row.dataset.kind = ep.kind;
    const cause = epCause(ep);
    const note = epNote(ep);
    row.innerHTML = `<span class="what"><b>${esc(ep.name)}</b>`
      + `<span class="st">${esc(epStates(ep))}</span></span>`
      + `<span class="when">${esc(epWhen(ep, sec.reads))}</span>`
      + (cause ? `<span class="cause">${esc(cause)}</span>` : "")
      + (note ? `<span class="actnote">${esc(note)}</span>` : "")
      + (ep.undid
         ? `<span class="actundid">a person undid ${esc(ep.undid)}</span>` : "");
    // A restart names no entity, so there is no history to open under it.
    if (!ep.entity_id && ep.kind !== "mass") row.disabled = true;
    box.appendChild(row);
    if (actState.open === key) {
      const why = el("div", "actwhy");
      why.innerHTML = ep.kind === "mass" ? actMassHtml(ep) : actWhyHtml(ep);
      box.appendChild(why);
    }
  });
  return box;
}

// A collapsed burst opens onto the entities it collapsed — already in the
// payload, so nothing is fetched.
function actMassHtml(ep) {
  const ids = ep.entities || [];
  const more = (ep.devices || ids.length) - ids.length;
  return `<div>${esc(String(ep.devices || ids.length))} entities changed `
    + `together, with nothing recorded as the cause — an integration `
    + `reloading or reconnecting does this:</div>`
    + ids.map((id) => `<div><code>${esc(id)}</code></div>`).join("")
    + (more > 0 ? `<div>and ${esc(String(more))} more</div>` : "");
}

function actWhyHtml(ep) {
  const why = actState.why;
  if (!why || why.entity_id !== ep.entity_id) return "Reading&hellip;";
  if (!why.changes.length) {
    return `Nothing else changed <code>${esc(ep.entity_id)}</code> in this window.`;
  }
  return `<div>Everything that changed <code>${esc(ep.entity_id)}</code> `
    + `in this window, newest first:</div>`
    + why.changes.map((c) => {
      // Escaped as one string rather than assembled from escaped parts:
      // `CAUSE_WORDS[c.cause] || c.cause` falls through to whatever the
      // server called an unknown cause, and that fallback was the one
      // piece of this row reaching innerHTML unescaped — which the
      // sibling renderer above does not do, and the difference between
      // two renderers of the same thing is exactly how that happens.
      const cause = c.cause === "unattributed"
        ? CAUSE_WORDS.unattributed
        : `${CAUSE_WORDS[c.cause] || c.cause}${c.by_name ? " · " + c.by_name : ""}`;
      return `<div><span class="t">${esc(actTime(c.ts))}</span> &rarr; `
        + `${esc(c.state)} &mdash; ${esc(cause)}</div>`;
    }).join("");
}

async function actOpenRow(key, entityId) {
  if (actState.open === key) { actState.open = ""; actState.why = null;
                               renderActivity(); return; }
  actState.open = key;
  actState.why = null;
  renderActivity();
  // A collapsed burst carries its own list; there is no one entity to ask.
  if (!entityId) return;
  const q = new URLSearchParams({ hours: String(actState.hours) });
  if (actState.end) q.set("end", String(Math.round(actState.end)));
  try {
    const data = await api(
      `api/activity/entity/${encodeURIComponent(entityId)}?` + q.toString());
    actState.why = data;
  } catch (e) {
    actState.why = { entity_id: entityId, changes: [] };
  }
  // The row may have gone (a filter press, a day step) while this was in
  // flight; renderActivity draws whatever is open now, which may be nothing.
  if (actState.open === key) renderActivity();
}

$("#actArea")?.addEventListener("change", (ev) => {
  actState.area = ev.currentTarget.value;
  actState.open = "";
  refreshActivity();
});
$("#actHours")?.addEventListener("change", (ev) => {
  actState.hours = Number(ev.currentTarget.value) || 24;
  actState.open = "";
  refreshActivity();
});
(function wireActSearch() {
  const input = $("#actSearch");
  if (!input) return;
  let timer = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      actState.q = input.value.trim();
      actState.open = "";
      refreshActivity();
    }, 300);
  });
})();

$("#actCause")?.addEventListener("change", (ev) => {
  actState.cause = ev.currentTarget.value;
  actState.open = "";
  refreshActivity();
});

// Delegated: every row in this list is rebuilt on each render.
document.addEventListener("click", (ev) => {
  const row = ev.target.closest && ev.target.closest(".actrow");
  if (!row) return;
  actOpenRow(row.dataset.key, row.dataset.entity);
});

$("#actPrev").addEventListener("click", () => {
  actState.end = (actState.end || Date.now() / 1000) - actState.hours * 3600;
  actState.open = "";
  refreshActivity();
});
$("#actNext").addEventListener("click", () => {
  if (!actState.end) return;
  const next = actState.end + actState.hours * 3600;
  // Stepping forward past now lands on the live window, which is what
  // "Later" means at the end of the list rather than a window ending in
  // the future with nothing in it.
  actState.end = next >= Date.now() / 1000 - 60 ? null : next;
  actState.open = "";
  refreshActivity();
});

// ---------------------------------------------------------------- views
// Insights / Ask / Memory, and the Guide behind ⚙. The Memory pane reuses the
// knowledge dialog's markup verbatim — it is relocated out of the modal at
// startup rather than duplicated, so every id (and every handler bound to
// one) keeps working untouched. The insight cards are the pane the panel
// lands on.
let currentView = "insights";
// The groups that navigate on the segmented control under the bar, and the
// panes in each, in the order the control shows them.
const SEG_GROUPS = {
  insights: ["insights", "findings", "archive"],
  memory: ["memory", "activity", "housebook"],
};

// Which of the three tabs a pane lives under: a tab is a group. Read off the
// markup rather than written down twice — `data-group` on each sub-tab is
// the one place the grouping is spelled.
function groupOf(name) {
  const sub = document.querySelector(`.subtab[data-view="${name}"]`);
  if (sub) return sub.dataset.group;
  for (const [g, views] of Object.entries(SEG_GROUPS)) {
    if (views.includes(name)) return g;
  }
  return "insights";
}
// The pane each group was last on, so pressing Ask after Memory brings the
// chat back rather than the group's opening pane; pressing the group you
// are already in goes to that opening pane.
const groupLast = {};

function syncTabs(name) {
  const group = groupOf(name);
  groupLast[group] = name;
  document.querySelectorAll(".viewtab").forEach((b) => {
    const on = b.dataset.group === group;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  let shown = 0;
  document.querySelectorAll(".subtab").forEach((b) => {
    const mine = b.dataset.group === group && !b.classList.contains("gone");
    b.hidden = !mine;
    if (mine) shown++;
    b.classList.toggle("active", b.dataset.view === name);
    b.setAttribute("aria-selected", b.dataset.view === name ? "true" : "false");
  });
  // A strip with one button is a label, not navigation — and the two
  // groups with more than one pane navigate on their own segmented control.
  const strip = $("#subtabs");
  const show = shown >= 2 && !SEG_GROUPS[group];
  strip.hidden = !show;
  document.body.classList.toggle("has-subtabs", show);
}

// The segmented control over the tab you are on. Shown on a group's panes
// and nowhere else — and not over the sign-in or first-run screens, which
// are not a place to navigate from.
function syncSegNav(name = currentView) {
  const seg = $("#segNav");
  if (!seg) return;
  const group = groupOf(name);
  const views = SEG_GROUPS[group];
  const gated = name === "findings" && $("#todaySetup") && !$("#todaySetup").hidden;
  const on = !!views && !gated;
  seg.hidden = !on;
  seg.dataset.group = group;
  document.body.classList.toggle("house-view", on && group === "memory");
  document.body.classList.toggle("seg-view", on);
  if (!on) return;
  const sel = $("#segNavSel");
  if (sel) sel.textContent = "";
  seg.querySelectorAll(".segbtn").forEach((b) => {
    const inGroup = b.dataset.group === group;
    const gone = b.classList.contains("gone");
    b.hidden = !inGroup || gone;
    const mine = b.dataset.view === name;
    b.classList.toggle("active", mine);
    b.setAttribute("aria-selected", mine ? "true" : "false");
    if (inGroup && !gone && sel) {
      // The label only: the count beside "Needs you" is not part of its name.
      const opt = el("option", null, (b.childNodes[0] || b).textContent.trim());
      opt.value = b.dataset.view;
      sel.appendChild(opt);
    }
  });
  if (sel) sel.value = name;
}
function switchView(name) {
  // The To-do, Proposals and Upkeep panes are Needs you's now: a deep link, a
  // toast or an older caller that names either lands on the one screen
  // holding both.
  if (name === "todo" || name === "proposals" || name === "upkeep") name = "findings";
  // Ideas are a row on Insights now, so a link to the old pane lands there.
  if (name === "ideas") name = "insights";
  // History was a drawer on Today; it is a pane of its own now.
  if (name === "history") name = "archive";
  if (name === currentView) return;
  if (currentView === "memory" && memState.editing && memState.dirty &&
      !window.confirm("Discard your unsaved memory edits?")) return;
  if (currentView === "memory" && memState.editing) setMemEditing(false);

  currentView = name;
  // The terminal takes the viewport, so the page behind it stops scrolling
  // — two scrollers stacked is why a swipe sometimes moved the wrong one.
  document.body.classList.toggle("term-open", name === "terminal");
  syncTabs(name);
  syncSegNav(name);
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view" + name[0].toUpperCase() + name.slice(1)));

  if (name === "findings") {
    // Draw what we have, then again once every list the screen reads has
    // landed: the queue, the findings under it, the suggestions, Your list
    // and the two cards no store owns.
    renderFindings();
    refreshToday().then(renderFindings);
  }
  if (name === "terminal") {
    if (chatState.session === "classic") {
      const frame = $("#termFrame");
      // Lazy: don't start a shell session for someone who never opens the tab.
      if (frame.getAttribute("src") === "about:blank") frame.src = "terminal/";
    } else {
      chatConnect();
      restoreChatFinding();
      // A phone opens Ask on the list of your chats, never straight into
      // whichever transcript was last on screen.
      askShow("list");
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
  // Same shape: draw what we have, then again once the fetch lands, so
  // opening the tab is never a blank frame. And pick the poll back up if
  // a pass started before you navigated away — a run outlives the page.
  // Reports carries the Suggested row and the deep review, so both are
  // read when it is opened, from what we have and again once they land.
  if (name === "insights") {
    renderIdeas();
    refreshIdeas().then(() => {
      renderIdeas();
      if (ideasState.running) ideasWatch();
    });
    refreshDeepReview();
  }
  if (name === "memory") renderKnowledge();
  if (name === "archive") {
    renderHistory();
    refreshHistory().then(renderHistory);
  }
  if (name === "housebook") {
    renderUpBook();
    api("api/house_book").catch((e) => ({ fetch_error: e.message }))
      .then((book) => {
        upState.book = book;
        renderUpBook();
        if (book && book.running) upWatch("book", "api/house_book");
      });
  }
  if (name === "docs") renderDocs();
  // Re-fetched on every entry rather than kept: the window ends "now", and
  // a timeline showing the state of the house when you last looked is the
  // one thing a timeline may not do.
  if (name === "activity") {
    actState.end = null; actState.open = ""; refreshActivity(); refreshActNow();
  }
}

document.querySelectorAll(".viewtab").forEach((b) =>
  b.addEventListener("click", () => {
    const group = b.dataset.group;
    const again = groupOf(currentView) === group;
    let target = again ? b.dataset.view : (groupLast[group] || b.dataset.view);
    // A pane switched off (Insights with `enable_insights: false`) hands
    // the press to the first pane of the group that is still there.
    const sub = document.querySelector(`.subtab[data-view="${target}"]`);
    if (sub && sub.classList.contains("gone")) {
      const first = document.querySelector(
        `.subtab[data-group="${group}"]:not(.gone)`);
      if (first) target = first.dataset.view;
    }
    switchView(target);
  }));
document.querySelectorAll(".subtab").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view)));
document.querySelectorAll("#segNav .segbtn").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view)));
$("#segNavSel")?.addEventListener("change", (ev) =>
  switchView(ev.currentTarget.value));
syncTabs(currentView);
syncSegNav(currentView);

// Add one by hand. Nothing here is required beyond the sentence: a to-do
// list that made you pick a severity before it would take a note is a form,
// and the whole point of this one is that it takes what brAIn cannot see.
$("#ideasRun").addEventListener("click", (ev) => ideasRun(ev.currentTarget));

$("#todoAdd").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = $("#todoText");
  const text = input.value.trim();
  if (!text) return;
  const btn = ev.currentTarget.querySelector("button");
  btn.disabled = true;
  try {
    takeTodo(await api("api/todo", {
      method: "POST", body: JSON.stringify({ text }),
    }));
    input.value = "";
    // Whichever filter was showing, what you just added is on the open
    // list — landing on "Done" after adding something would read as the
    // add having failed.
    state.todoFilter = "open";
    renderTodo();
  } catch (err) {
    toast(err.message || "could not add that");
  } finally {
    btn.disabled = false;
  }
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
    toast(res.added ? "Learned — brAIn will remember that" : "Already known");
    if (res.merging && $("#kMemMerging")) {
      $("#kMemMerging").classList.remove("hidden");
      pollMemoryMerge();
    }
    renderKnowledge();
  } catch (e) { toast(e.message); }
});
// Relocate the knowledge dialog's body wherever a `#memoryHost` is mounted
// and retire the dialog shell. House no longer mounts one (the memory
// document is ⚙'s), so with neither present this does nothing.
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
  chosen: {},        // resolutions card id -> the option pressed, this session
  ready: false,      // has a snapshot been drawn
  session: "chat",   // "chat" | "classic"
  runState: "idle",
  sessionId: null,   // the CLI's id for this conversation — what `--resume` takes
  info: {},          // model, cwd, version, api_key_source, from the CLI itself
  context: {},       // {tokens, window} — how full the conversation is
  models: [],        // the same choices ⚙ offers, for the chat's own picker
  chatModel: "",     // the stored chat override; "" = follow the global model
  defaultModel: "",  // the global model the chat defers to when unset
  defaultModelLabel: "",  // …written out, for the picker's Default row
  convs: [],       // past conversations, for the wide-screen sidebar
  liveSessions: {},  // session id -> {live, busy, needs_ok} for the rail's marks
  maxSessions: 0,    // how many may hold a process at once (chat_max_sessions)
  composer: null,    // {state, label, hint}: what sending into this chat will do
  record: null,      // {id, title, text} while a card/fix run is open to be read
  commands: [],      // its slash commands, as it advertises them
  cli: [],           // the brain/ha dispatchers, parsed from their own help
  cmdIndex: 0,       // highlighted row in the command palette
  finding: null,     // the finding this conversation is about, if any
  findingTs: 0,      // …as the conversation itself says (the snapshot's)
  steps: null,       // this reply's "Worked through N steps" fold
  question: "",      // what this reply answers, for "Save as report"
  answerNode: null,  // the reply's last answer, which carries that button
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

// The panel already has an escaping markdown renderer for the guide, and
// this is exactly the content that needs one: it escapes first, so a model
// that echoes a <script> back at you renders it as text.
function chatMarkdown(text) {
  const node = el("div", "msg bot");
  node.innerHTML = renderMarkdown(String(text || ""));
  return node;
}

// One reply's working, folded into one line.
//
// A reply that reads three things and runs a search used to be four rows of
// tool names above the answer, and a long one was a screen of them — the
// working, at the same weight as what it was for. Every tool call, its
// result, the thinking and a backgrounded task finishing go into ONE
// disclosure per reply, "Worked through N steps", closed. What is never in
// it: the answer, an approval card, a question card and the endings a
// discussion offers. Those are where somebody decides something, and a
// decision folded away is a decision nobody makes — the CLI is blocked on
// the first two.
function chatStepsFold() {
  const have = chatState.steps;
  if (have && have.isConnected) return have;
  const box = el("details", "steps");
  const sum = el("summary");
  sum.appendChild(el("span", "tdot"));
  sum.appendChild(el("span", "steplabel", ""));
  box.appendChild(sum);
  box.appendChild(el("div", "stepsbody"));
  chatState.steps = box;
  // Above an answer that is still streaming, never under it: the working
  // came first.
  const wasBottom = chatAtBottom();
  if (chatState.live && chatState.live.parentNode === chatLog()) {
    chatLog().insertBefore(box, chatState.live);
  } else {
    chatLog().appendChild(box);
  }
  $("#chatEmpty").classList.add("hidden");
  if (wasBottom) chatScroll(true);
  return box;
}

function chatStepAdd(node) {
  const box = chatStepsFold();
  box.querySelector(".stepsbody").appendChild(node);
  chatStepsLabel(box);
  return node;
}

// The count, and the two things worth knowing without opening it: that
// something failed, and that something was not permitted. A step still
// running keeps the dot pulsing, which is the fold's whole liveness.
function chatStepsLabel(box) {
  if (!box) return;
  const body = box.querySelector(".stepsbody");
  const n = body.childElementCount;
  const failed = body.querySelectorAll(".toolcall.bad").length;
  const denied = body.querySelectorAll(".toolcall.denied").length;
  let text = `Worked through ${n} step${n === 1 ? "" : "s"}`;
  if (failed) text += ` · ${failed} failed`;
  if (denied) text += ` · ${denied} not permitted`;
  box.querySelector(".steplabel").textContent = text;
  box.classList.toggle("running", !!body.querySelector(".toolcall.running, .think.live"));
  box.classList.toggle("bad", !!failed);
}

// A reply ends where the next message starts (or the turn's result lands);
// the next reply's working gets a fold of its own.
function chatEndReply() {
  chatState.steps = null;
}

// "Save as report" under a reply's answer: the question the person typed,
// asked again as a card under House, so an answer worth keeping outlives
// the conversation it was given in. One button per reply, on its LAST
// answer — a reply that says "let me look" before the real answer would
// otherwise offer to save the preamble.
function chatOfferReport(node) {
  if (!node || !chatState.question) return;
  const prev = chatState.answerNode;
  if (prev && prev !== node) {
    const old = prev.querySelector(".msgacts");
    if (old) old.remove();
  }
  chatState.answerNode = node;
  if (node.querySelector(".msgacts")) return;
  const question = chatState.question;
  const row = el("div", "msgacts");
  const save = el("button", "btn tiny ghost savereport", "Save as report");
  save.type = "button";
  save.title = "Ask this again as a report card under House";
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await api("api/generate", {
        method: "POST", body: JSON.stringify({ question, report: true }) });
      row.textContent = "";
      row.appendChild(el("span", "msgsaved", "Saving as a report under House"));
      toast("Saving as a report — it will be under House when it is ready");
    } catch (e) {
      save.disabled = false;
      toast(e.message);
    }
  });
  row.appendChild(save);
  node.appendChild(row);
}

const DISCUSS_PREFIX = "Discussing: ";

// Whether a message is a question worth saving: not a slash command, and
// not the opener Discuss sends on a card's behalf.
function chatReportable(text) {
  const t = String(text || "").trim();
  return !!t && !t.startsWith("/") && !t.startsWith(DISCUSS_PREFIX);
}

// The Discuss opener is a page of context brAIn handed Claude about the
// card — evidence rows, what the first look said, the run that raised it.
// In the transcript it is the card's title, with the rest one press down:
// that context is what the answer was written against, so it stays
// readable, but it is not something the person said.
function chatUserNode(text) {
  const row = el("div", "msg user");
  const t = String(text || "");
  if (!t.startsWith(DISCUSS_PREFIX)) {
    row.appendChild(el("div", "bubble", t));
    return row;
  }
  const nl = t.indexOf("\n");
  const title = (nl < 0 ? t : t.slice(0, nl)).slice(DISCUSS_PREFIX.length).trim();
  const rest = nl < 0 ? "" : t.slice(nl + 1).trim();
  const bubble = el("div", "bubble discuss");
  bubble.appendChild(el("div", "dtitle", title));
  if (rest) {
    const more = el("details", "dmore");
    more.appendChild(el("summary", null, "What brAIn told Claude about this card"));
    more.appendChild(el("div", "dbody", rest));
    bubble.appendChild(more);
  }
  row.appendChild(bubble);
  return row;
}

// What a tool call is called on screen. The CLI names a Home Assistant
// read `mcp__home-assistant__get_all_states`, which is a wire name — the
// person reading the steps wants "Get all states". The raw name stays in
// the tooltip, because it is what a log, a permission rule and a bug
// report all key on.
const TOOL_WORDS = {
  Bash: "Command", Read: "Read file", Write: "Write file", Edit: "Edit file",
  MultiEdit: "Edit file", NotebookEdit: "Edit notebook", Glob: "Find files",
  Grep: "Search files", LS: "List folder", WebFetch: "Fetch page",
  WebSearch: "Web search", TodoWrite: "Plan", Task: "Sub-task",
  Agent: "Sub-task", ToolSearch: "Load tools", AskUserQuestion: "Question",
};

function toolDisplayName(name) {
  const raw = String(name || "tool");
  if (TOOL_WORDS[raw]) return TOOL_WORDS[raw];
  const m = raw.match(/^mcp__[^_].*?__(.+)$/);
  const bare = (m ? m[1] : raw).replace(/[_-]+/g, " ").trim();
  if (!m && !/[_-]/.test(raw)) return raw;
  return bare ? bare.charAt(0).toUpperCase() + bare.slice(1) : raw;
}

function toolDisplaySummary(name, summary) {
  const s = String(summary || "");
  if (name !== "ToolSearch") return s;
  const sel = s.match(/^select:(.*)$/);
  if (!sel) return s;
  return sel[1].split(",").map((t) => toolDisplayName(t.trim()).toLowerCase())
    .filter(Boolean).join(", ");
}

function chatToolNode(ev) {
  const box = el("details", "toolcall running");
  const sum = el("summary");
  sum.appendChild(el("span", "tdot"));
  const tname = el("span", "tname", toolDisplayName(ev.name));
  if (ev.name && toolDisplayName(ev.name) !== ev.name) tname.title = ev.name;
  sum.appendChild(tname);
  sum.appendChild(el("span", "tsum", toolDisplaySummary(ev.name, ev.summary)));
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

// A turn Claude Code injected itself — a backgrounded task finishing. It
// lives in the person's half of the conversation, which is why it used to
// render as a bubble of raw XML "they" had typed; the server classifies it
// (conversations.injected_event) and this draws it as one collapsed row in
// the tool calls' shape, with the task's own report as markdown inside.
function chatBackgroundNode(ev) {
  const failed = /fail|error|kill/i.test(ev.status || "");
  const box = el("details", "toolcall bgtask " + (failed ? "bad" : "ok"));
  const sum = el("summary");
  sum.appendChild(el("span", "tdot"));
  sum.appendChild(el("span", "tname",
                     failed ? "Background task failed" : "Background task finished"));
  sum.appendChild(el("span", "tsum", ev.summary || ""));
  box.appendChild(sum);
  const body = el("div", "tbody");
  body.innerHTML = renderMarkdown(String(ev.text || ""));
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
  // next thing Claude says will look strange. Inside its fold, whose line
  // says so ("· 1 failed") without opening it.
  if (!ev.ok) box.open = true;
  chatStepsLabel(box.closest("details.steps"));
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
  chatComposerTick();
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
    chatStepAdd(box);
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
  chatStepsLabel(entry.box.closest("details.steps"));
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
  const buttons = [allow, deny];
  // "Always allow" only where the CLI itself suggested a rule — the server
  // hands back exactly that suggestion, and says how long it lasts, so the
  // line under the row is the whole of what the press adds.
  let always = null;
  if (ev.always) {
    always = el("button", "btn small", "Always allow");
    buttons.push(always);
  }
  allow.addEventListener("click", () =>
    chatPermissionPost({ id: ev.id, allow: true }, buttons));
  deny.addEventListener("click", () =>
    chatPermissionPost({ id: ev.id, allow: false }, buttons));
  if (always) {
    always.addEventListener("click", () =>
      chatPermissionPost({ id: ev.id, allow: true, always: true }, buttons));
  }
  row.append(allow, deny);
  if (always) row.appendChild(always);
  card.appendChild(row);
  if (ev.always) {
    const until = ev.always_until === "conversation"
      ? "for the rest of this conversation"
      : "in the terminal and every chat, until the add-on restarts";
    card.appendChild(el("div", "permscope",
      `Always allow adds ${ev.always} — ${until}.`));
  }
  // The switch that stops the asking altogether, found where the asking
  // happens. It opens ⚙ at the switch rather than flipping it: the dialog
  // is where what stays guarded is written down, and a one-press "never ask
  // again" on a card about one command is a bigger answer than the
  // question. This card still wants its own answer either way.
  if (ev.stop_asking) {
    const foot = el("div", "permfoot");
    const stop = el("button", "btn small ghost permstop", "Stop asking…");
    stop.type = "button";
    stop.title = "Open the switch that lets brAIn act without asking";
    stop.addEventListener("click", () => openSettingsAt("setSkipPerms"));
    foot.appendChild(stop);
    card.appendChild(foot);
  }
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
      ev.answered ? (ev.allow ? (q ? "Answered" : (ev.always ? "Always allowed" : "Allowed"))
                              : (q ? "Skipped" : "Not allowed"))
                  : "Withdrawn"));
  }
  // What the buttons offered goes with them: a line about what "Always
  // allow" would add, under a card already answered, reads as still on offer.
  card.querySelectorAll(".permscope, .permfoot").forEach((n) => n.remove());
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
      chatEndReply();
      chatState.question = chatReportable(ev.text)
        ? String(ev.text).trim().slice(0, 500) : "";
      chatState.answerNode = null;
      chatAppend(chatUserNode(ev.text), true);
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
    case "text": {
      const streamed = chatState.live;
      const node = chatSealLive(ev.text) ? streamed : chatAppend(chatMarkdown(ev.text));
      chatOfferReport(node);
      chatStatus();
      break;
    }
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
      chatStepAdd(box);
      break;
    }
    case "tool": {
      chatCloseLiveThink();
      chatSealLive();
      const node = chatStepAdd(chatToolNode(ev));
      if (ev.id) chatState.tools.set(ev.id, node);
      chatStatus(`Running ${ev.name || "a tool"}…`);
      break;
    }
    case "tool_result":
      chatToolResult(ev);
      chatStatus("Working…");
      break;
    case "background":
      chatSealLive();
      chatStepAdd(chatBackgroundNode(ev));
      break;
    case "resolutions":
      chatCloseLiveThink();
      chatSealLive();
      chatAppend(chatResolutionsNode(ev));
      chatStatus();
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
      chatEndReply();
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
    case "sessions":
      // Which conversations are holding a process, and which of those are
      // answering or waiting on somebody. Pushed rather than polled: it
      // only ever changes when something else already had an event to send.
      chatState.liveSessions = {};
      (ev.sessions || []).forEach((s) => { chatState.liveSessions[s.session_id] = s; });
      chatComposerFromSessions(ev.sessions || []);
      renderChatRail();
      break;
    case "switched":
      // The view moved to another conversation. Reconnect rather than
      // patching this stream: the first frame of the new one is the new
      // session's snapshot, which is the contract the stream has always
      // had — no client has to stitch "what it was" onto "what happened
      // next".
      chatDisconnect();
      chatConnect();
      break;
    case "session_asks": {
      // A conversation nobody is looking at is waiting on an approval, and
      // its card times itself out. The rail's badge is the other half of
      // this and it is not enough on a phone, where there is no rail.
      const who = ev.title ? `“${ev.title}”` : "Another chat";
      toast(`${who} needs your OK${ev.tool ? " — " + ev.tool : ""}`, null,
            { label: "Open it",
              run: () => resumeConversation({ id: ev.session_id }) });
      refreshChatRail();
      break;
    }
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
  const info = chatState.info || {};
  const model = info.model || "";
  const ctx = chatState.context || {};
  box.classList.toggle("hidden", !model && !ctx.tokens);
  // The name is the server's — see chat_session.pretty_model. Parsing a
  // model id needs its version read, and a second reading of that in here
  // drifted from the one the context window already uses: it printed both
  // Haiku 4.5 and a hypothetical Haiku 4.9 as "Claude Haiku 4", so picking
  // between them changed nothing you could see.
  $("#chatModel").textContent = info.model_label || model;
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
  chatState.steps = null;
  chatState.question = "";
  chatState.answerNode = null;
  $("#chatEmpty").classList.remove("hidden");
  renderComposerState();
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
  chatComposerOnState(runState);
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
      chatState.defaultModelLabel = ev.default_model_label || "";
      // The rail's marks are right on the first paint rather than on the
      // first thing that happens to move.
      chatState.liveSessions = {};
      (ev.sessions || []).forEach((s) => { chatState.liveSessions[s.session_id] = s; });
      chatState.maxSessions = ev.max_sessions || chatState.maxSessions;
      // What sending will do, derived server-side by the same function
      // the rows use. Set BEFORE chatSetState, which only ever flips it
      // between answering and ready off a `state` it has no history for.
      chatState.composer = ev.composer_state || chatState.composer;
      chatMeta();
      chatState.cli = ev.cli || chatState.cli;
      restoreChatFinding(ev.finding_ts || 0);
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
      renderChatHead();
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
  // From the list page there is nothing on screen to leave, so nothing to
  // confirm.
  if (!askOnList() && chatLog().childElementCount && !window.confirm(
    "Start a new chat? This one is kept — you can reopen it from your "
    + "chats.")) return;
  try { await api("api/chat/new", { method: "POST" }); }
  catch (e) { toast(e.message); return; }
  askShow("chat");
  refreshChatRail();
});

// ------------------------------------------------- what sending will do
//
// The line above the message box. A conversation whose process the cap
// paused, one whose context Claude Code no longer holds, and a live one
// look identical from the transcript alone — and the moment that matters
// is the one just before Send. So the server says which it is
// (`composer_state`, the same derivation every row in the rail gets) and
// this draws the sentence and the ONE control that fits it. Nothing here
// decides a state: the two local flips below (a `state` event landing
// before the `sessions` event that follows it) only ever move between
// "answering" and "live", and the server's next word replaces them.
const COMPOSER_LOCAL = {
  answering: { state: "answering", label: "Answering…", hint: "Claude is answering" },
  live: { state: "live", label: "Live", hint: "Ready" },
};
// No control for either kind of pause: sending is what picks a paused
// conversation back up, so a "Resume now" beside the box was a second
// button for what Send already does. A plain pause says nothing at all;
// a cap's pause keeps its sentence, because it says what sending costs.
const COMPOSER_ACTION = {
  live: "New chat",
  answering: "Stop",
  needs_ok: "",
  paused: "",
  paused_room: "",
  context_lost: "Start fresh",
  record: "Ask about it",
};

function composerCurrent() {
  if (chatState.record) return { state: "record", ...composerRecordText() };
  return chatState.composer || COMPOSER_LOCAL.live;
}

function composerRecordText() {
  // The record's hint is the server's wording for the state, when a
  // snapshot has ever carried one; the record itself only names the run.
  return { label: "Record",
           hint: "A card run, shown to be read. It cannot be continued" };
}

function renderComposerState() {
  const host = $("#chatState");
  if (!host) return;
  const cs = composerCurrent();
  // A fresh chat with nothing in it says nothing: "Ready · New chat" on
  // an empty conversation offers a no-op (the server reuses the empty
  // session), and the line costs 44px that a 320px phone does not have.
  // Every other state is worth its sentence whatever is on screen.
  const blank = (cs.state === "live" && !chatState.record
    && chatLog().childElementCount === 0)
    // A state with nothing to say (a plain pause) says nothing.
    || (!cs.label && !cs.hint && !COMPOSER_ACTION[cs.state]);
  host.classList.toggle("hidden", blank);
  host.dataset.state = cs.state || "";
  host.querySelector(".cs-pill").textContent = cs.label || "";
  host.querySelector(".cs-text").textContent = cs.hint || "";
  const act = $("#chatStateAct");
  act.textContent = COMPOSER_ACTION[cs.state] || "";
  act.classList.toggle("primary", cs.state === "context_lost");
  chatComposerTick();
}

// The elapsed seconds on "Claude is answering", kept by the same 1s tick
// as the status line in the log — one clock, two readouts.
function chatComposerTick() {
  const host = $("#chatState");
  if (!host || host.dataset.state !== "answering") return;
  const cs = composerCurrent();
  const s = chatState.busyStart
    ? Math.round((Date.now() - chatState.busyStart) / 1000) : 0;
  host.querySelector(".cs-text").textContent =
    (cs.hint || "Claude is answering") + (s >= 1 ? ` · ${s} s` : "");
}

// A `state` event: busy is answering, and ready after answering is live.
// Anything historical (paused, context lost) is left for the server's
// `sessions` event, which follows every state change and carries the
// derived answer — this only bridges the gap for a chat the CLI has not
// named yet, which `sessions` skips.
function chatComposerOnState(runState) {
  const was = (chatState.composer || {}).state;
  if (runState === "busy") {
    if (was !== "answering" && was !== "needs_ok") {
      chatState.composer = COMPOSER_LOCAL.answering;
    }
    if (!chatState.busyStart) chatState.busyStart = Date.now();
  } else if (was === "answering" || was === "needs_ok") {
    chatState.composer = COMPOSER_LOCAL.live;
  }
  renderComposerState();
}

function chatComposerFromSessions(rows) {
  const mine = rows.find((s) => s.attached && s.row_state);
  if (mine) chatState.composer = mine.row_state;
  renderComposerState();
}

$("#chatStateAct").addEventListener("click", () => {
  const state = composerCurrent().state;
  if (state === "answering") $("#chatStop").click();
  else if (state === "live") $("#chatNew").click();
  else if (state === "context_lost") startFresh();
  else if (state === "record") askAboutRecord();
});

// Start fresh: the new-chat path without its confirm. The confirm asks
// whether you are sure about leaving a conversation Claude still holds,
// and this one it does not.
async function startFresh() {
  try { await api("api/chat/new", { method: "POST" }); }
  catch (e) { toast(e.message); }
  refreshChatRail();
}

// Ask about it: a record cannot be continued, so the honest offer is a
// NEW conversation with the record quoted into the composer — pre-filled
// and never sent, because what you want to ask about it is yours to type.
async function askAboutRecord() {
  const rec = chatState.record;
  if (!rec) return;
  closeBox("#convViewModal");
  chatState.record = null;
  try { await api("api/chat/new", { method: "POST" }); }
  catch (e) { toast(e.message); return; }
  refreshChatRail();
  const input = $("#chatInput");
  const quoted = (rec.text || "").trim();
  input.value = `About the run ${rec.title} (${rec.id}): `
    + (quoted ? `\n\n> ${quoted.split("\n").join("\n> ")}\n\n` : "");
  chatGrow();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  renderComposerState();
}

$("#convViewAsk").addEventListener("click", askAboutRecord);

document.querySelectorAll(".chatseeds .seed").forEach((btn) =>
  btn.addEventListener("click", () => {
    // A seed with a blank in it fills the box and waits for the blank.
    if (btn.dataset.fill) {
      const input = $("#chatInput");
      input.value = btn.dataset.fill;
      chatGrow();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      return;
    }
    chatSend(btn.textContent);
  }));

// --------------------------------------------------- the finding on trial
//
// A discussion is about one finding, and the decisions about that finding
// have to be reachable from inside it. Otherwise agreeing to a fix at the
// end of a conversation means going back to the other tab and finding the
// card again, which is where a decision goes to die.
//
// It follows the conversation on screen: the snapshot says which card the
// conversation is about (`finding_ts`, kept in the transcript's own meta),
// so reopening a discussion from the list brings its card back with it,
// and opening any other conversation takes it away.

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
  renderChatHead();
  if (!f) return;
  $("#chatFindingText").textContent = cardTitleOf(f);
  $("#chatFindingFix").classList.toggle("hidden", !f.fixable);
}

// What a card is called on Today: a Resident case leads with its claim,
// a check's row with its sentence.
function cardTitleOf(f) {
  return String((f && (f.claim || f.text)) || "");
}

// The snapshot's word on which card this conversation is about. A card
// that has since been settled is no longer a decision, so the strip stays
// down for it — the conversation is still there to read.
async function restoreChatFinding(ts) {
  if (ts === undefined) ts = chatState.findingTs;
  chatState.findingTs = Number(ts) || 0;
  if (!chatState.findingTs) { setChatFinding(null); return; }
  const want = chatState.findingTs;
  const find = () => (state.findings || []).find((x) => Number(x.ts) === want);
  if (find()) { setChatFinding(find()); return; }
  // The list may not be loaded yet on a cold start — fetch it once.
  try {
    takeFindings(await api("api/findings"));
  } catch (e) { /* the strip simply stays down */ }
  if (chatState.findingTs !== want) return;   // moved on meanwhile
  setChatFinding(find() || null);
}

// "Show this card": Today, scrolled to the card the conversation is about.
// The feed draws its cards after its own fetch, so this waits for the card
// rather than for a fixed time; a card that has gone (settled, cleared)
// just leaves Today open, which is where it would have been.
function showCardOnToday(ts) {
  switchView("findings");
  let tries = 0;
  const look = () => {
    const card = document.querySelector(`[data-case-id="f:${ts}"]`)
      || document.querySelector(`[data-ts="${ts}"]`);
    if (card) {
      card.scrollIntoView({ block: "center" });
      card.classList.add("cardflash");
      setTimeout(() => card.classList.remove("cardflash"), 2400);
    } else if (++tries < 20) {
      setTimeout(look, 150);
    }
  };
  look();
}

$("#chatFindingText").addEventListener("click", () => {
  if (chatState.finding) showCardOnToday(chatState.finding.ts);
});

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
// Fix it buys the read-only look here too, so the toast says that rather
// than announcing a change nothing has made — and it names where the steps
// land, because this strip closes on the press and the plan is on the card.
$("#chatFindingFix").addEventListener("click", () =>
  chatFindingAction("fix",
    "Working out what it would change — the steps land on the card in Today"));
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

// ------------------------------------------------- settling it from the chat
//
// The strip above the composer carries the four endings a finding always
// has; this carries the one the CONVERSATION arrived at. Discussing a
// finding is how you work out what to actually do about it, and until now
// that answer had nowhere to go but a reason box you had to retype it into.
//
// Claude offers them by calling `offer_resolutions`, which changes nothing:
// the panel reads the call off the stream it was already reading and draws
// the buttons. Three rules make that safe to press.
//
// The PRESS is the consent — nothing is settled until one happens, and it
// goes to the same route the tab's own buttons use. The LABEL is the record:
// one string, the button and the note it writes, so nothing is recorded that
// a person did not read first. And no resolution TOUCHES the house: the
// verbs are the three that record a decision, so the worst a mis-tap can do
// is settle a finding, which the toast's Undo takes back whole. "Fix it" is
// deliberately not offerable here — it is the one button that sends Claude
// at the house, it stays on the strip where it is pressed deliberately, and
// it does not end a finding anyway.
//
// What each press DOES is written beside it rather than left to the label,
// because "Replace the CR2032" and "Replaced the CR2032" are one word apart
// and land in different places.
const RESOLUTION_KINDS = {
  done: {
    does: "Marks it fixed, and puts that into memory",
    toast: "Fixed — that's gone into memory",
  },
  todo: {
    does: "Adds it to your to-do list; memory waits until you tick it off",
    toast: "On your to-do list",
  },
  wrong: {
    does: "Tells brAIn it has misread your house, so it stops reporting it",
    toast: "Noted — brAIn won't raise it again",
  },
  // Not an ending: the card keeps the finding and takes this sentence as
  // "What you'd need to do". The consequence line has to say that the
  // finding stays, because the three rows beside it all take it away.
  advice: {
    does: "Puts this on the card as what to do — the finding stays open",
    toast: "Updated what to do on the card",
  },
  // The change the conversation agreed, made the way every change on a
  // card is made: a read-only plan of exactly this, which waits on the
  // card for Apply, and then an Undo. The conversation itself does not
  // act — that is what makes it a conversation rather than a side door.
  plan: {
    does: "brAIn works out exactly this change for you to read — nothing "
      + "changes until you press Apply on the card",
    toast: "Working out exactly that — the steps land on the card, and "
      + "nothing changes until you press Apply",
  },
};

function chatResolutionsNode(ev) {
  const box = el("div", "chatres");
  box.appendChild(el("div", "creshead", "How this could end"));
  const body = el("div", "cresbody");
  box.appendChild(body);
  const options = (ev.options || []).filter((o) => RESOLUTION_KINDS[o.verb]);

  // Whether there is anything to press is DERIVED, never remembered: the
  // transcript replays this card after a reload, and by then the finding may
  // have been settled here, on the Findings tab, or from a phone. Reading
  // the list each paint is what makes those agree — and a card offering to
  // settle something that is already gone is the one thing it must not do.
  const paint = () => {
    body.textContent = "";
    const chose = chatState.chosen[ev.id];
    if (chose) {
      body.appendChild(el("p", "cresnote", `You chose: ${chose}`));
      return;
    }
    if (!ev.finding_ts) {
      body.appendChild(el("p", "cresnote", "This conversation isn't about a "
        + "finding, so there is nothing here to settle."));
      return;
    }
    const f = (state.findings || []).find((x) => x.ts === ev.finding_ts);
    if (!f) {
      body.appendChild(el("p", "cresnote", "That finding has been settled "
        + "already, so there is nothing left to press."));
      return;
    }
    options.forEach((option) => {
      // The row IS the button, with what it does inside it — the question
      // card's own shape, for the question card's own reason: what a press
      // means is half the value of an option, and it must be inside the
      // thing you press rather than beside it.
      const btn = el("button", "cresopt");
      btn.appendChild(el("span", "creslabel", option.label));
      btn.appendChild(el("span", "cresdoes", RESOLUTION_KINDS[option.verb].does));
      body.appendChild(btn);
      btn.addEventListener("click", () => chooseResolution(
        ev, option, f, [...body.querySelectorAll("button")], paint));
    });
  };
  paint();
  return box;
}

async function chooseResolution(ev, option, finding, btns, paint) {
  const spec = RESOLUTION_KINDS[option.verb];
  if (!spec) return;
  if (option.verb === "plan") {
    // Not an ending either: the row moves to `planning`, and the plan
    // lands on its card. The press is Fix it's own route with the agreed
    // change as the run's brief — one plan path, whichever surface asked.
    btns.forEach((b) => { b.disabled = true; });
    try {
      const data = await api(`api/finding/${finding.ts}/fix`, {
        method: "POST", body: JSON.stringify({ change: option.label }) });
      takeFindings(data);
      syncFeed();
      renderFindings();
      refreshStatus().catch(() => {}); fastPoll();
      toast(spec.toast);
      chatState.chosen[ev.id] = option.label;
      paint();
    } catch (e) {
      toast(e.message);
      btns.forEach((b) => { b.disabled = false; });
    }
    return;
  }
  if (option.verb === "advice") {
    // The one press here that ends nothing: the sentence goes onto the
    // card and the finding stays, so the strip stays too and the card
    // records the choice without reading the list for the row's absence.
    btns.forEach((b) => { b.disabled = true; });
    try {
      const data = await api(`api/finding/${finding.ts}/advice`, {
        method: "POST", body: JSON.stringify({ fix: option.label }) });
      takeFindings(data);
      renderFindings();
      toast(spec.toast);
      chatState.chosen[ev.id] = option.label;
      paint();
    } catch (e) {
      toast(e.message);
      btns.forEach((b) => { b.disabled = false; });
    }
    return;
  }
  await findAction(finding, option.verb, spec.toast, btns, option.label,
                   option.verb === "todo" ? { fix: option.label } : null);
  // findAction reports its own failures and re-enables the row, so success
  // is read the way the paint reads it: the row is gone from the list. A
  // refused press (a full to-do list) leaves the buttons exactly as they
  // were, which is what lets somebody press a different one.
  if ((state.findings || []).some((x) => x.ts === finding.ts)) return;
  chatState.chosen[ev.id] = option.label;
  // Settled: it is no longer a decision waiting on you, so the strip goes
  // the same way it does when the strip's own buttons are pressed.
  if (chatState.finding && chatState.finding.ts === finding.ts) {
    setChatFinding(null);
  }
  paint();
}

// ------------------------------------------------------- conversations
//
// The list is Claude Code's, not ours: it files every conversation under
// the working directory, and both faces of this tab stand in /config. So a
// session started in the classic terminal is here beside one started in the
// chat, and picking either replays it into this pane and carries on.
//
// It opens on YOUR conversations. The same store holds every run the
// add-on makes there — voice, the automation listener, the memory pass,
// the Resident, card and fix runs — and those are reached from the pills
// under the list's head (`api/chat/conversations?source=…`), one kind at a
// time, so your own chats are never buried under machine prompts and the
// machines' are one press away rather than inside ⚙. The kind you picked
// is remembered; the server only offers kinds that have actually run here.

// What a conversation row says about itself: the pill for its
// `row_state`, which the server derives once for the rail, the composer
// line and the resume route alike. Seven states, six pills: a plain
// "paused" conversation — no process, the ordinary case — draws nothing,
// because most rows are that and it is not news. Everything that IS news is
// a word on the row: a live process ("Live", quiet), one answering, one
// waiting on a person (the loudest, because the approval card behind it
// declines itself if nobody comes), one the cap paused ("Paused to make
// room" — opening it is what picks it back up), one whose context Claude
// Code no longer holds, and a record.
//
// The stream's listing wins over the fetched row: it is refreshed the
// moment anything moves, where the row is as old as the last request.
const CONV_PILLS = {
  live: "crlive",
  answering: "crbusy",
  needs_ok: "crask",
  paused_room: "crpaused",
  context_lost: "crlost",
  record: "crrecord",
};

function convRowState(row) {
  const pushed = chatState.liveSessions[row.id];
  if (pushed && pushed.row_state) return pushed.row_state;
  if (row.row_state) return row.row_state;
  // A row from before the server said: the three flags it did carry.
  const live = pushed || (row.live ? { busy: row.busy, needs_ok: row.needs_ok } : null);
  if (row.view_only) return { state: "record", label: "Record" };
  if (!live) return { state: "paused", label: "" };
  if (live.needs_ok) return { state: "needs_ok", label: "Needs your OK" };
  if (live.busy) return { state: "answering", label: "Answering…" };
  return { state: "live", label: "Live" };
}

function convMark(row) {
  const rs = convRowState(row);
  const cls = CONV_PILLS[rs.state];
  if (!cls || !rs.label) return null;
  return el("span", cls, rs.label);
}

// Which kind of conversation the list shows: "you" (the default), or one
// of the background faces the server names in `sources`.
const CONV_SOURCE_KEY = "brain.ask.source";
chatState.convSource = prefGet(CONV_SOURCE_KEY) || "you";
chatState.convSources = [];

function convQuery() {
  return `api/chat/conversations?source=${encodeURIComponent(chatState.convSource || "you")}`;
}

// A row's ⋯. One item today — Delete — and a menu rather than a ✕ on every
// row: a column of ✕s is a column of the most destructive control in the
// list, each one the width of a thumb from the row it would delete. The
// row itself is a button, so this cannot be its child; the wrapper the
// caller puts both in is what keeps them siblings.
function convRowMenu(c) {
  const more = el("button", "crmore");
  more.type = "button";
  more.setAttribute("aria-label", "More for this chat");
  more.setAttribute("aria-haspopup", "true");
  more.innerHTML = '<svg viewBox="0 0 24 24" class="ico" aria-hidden="true">'
    + '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
    + '<circle cx="19" cy="12" r="1.6"/></svg>';
  more.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (chipPopFor === more) { closeChipPop(); return; }
    closeChipPop();
    setChipPop(more, "", '<div class="cardmenu">'
      + '<button class="cardmenuitem crmenudel" type="button">'
      + '<span class="cmtext"><b>Delete</b>'
      + '<small>You can undo it for a few minutes</small></span></button></div>');
    $("#chipPop").querySelector(".crmenudel").addEventListener("click", () => {
      closeChipPop();
      deleteConversation(c, more);
    });
  });
  return more;
}

// Deleting hands back an undo token and the toast grows the button, same as
// every other press that takes something away.
async function deleteConversation(c, btn) {
  if (btn) btn.disabled = true;
  const remove = () => api(
    `api/chat/conversation/${encodeURIComponent(c.id)}/delete`,
    { method: "POST" });
  try {
    let out;
    try {
      out = await remove();
    } catch (e) {
      // The server refuses to delete a conversation something is
      // holding open — deleting the ground a live session stands on
      // either kills it or quietly forks it. A refusal with no way to
      // satisfy it is a dead end, so this offers the way: close the
      // session, then delete. Never silently, because closing one that
      // is mid-answer loses the answer.
      if (!/close it first/.test(e.message)) throw e;
      if (!window.confirm(
        "That conversation still has a live Claude session. Close it and "
        + "delete? Anything it is still writing is lost.")) {
        if (btn) btn.disabled = false;
        return;
      }
      await api(`api/chat/session/${encodeURIComponent(c.id)}/close`,
                { method: "POST" });
      out = await remove();
    }
    toast("Conversation deleted", out.undo);
    refreshConversationLists();
  } catch (e) {
    if (btn) btn.disabled = false;
    toast(e.message);
  }
}

// The one list, wherever it is on screen.
function refreshConversationLists() {
  refreshChatRail();
}

// The list: a rail beside the transcript on a wide screen, and the page Ask
// opens on below that (`askShow`). A conversation started in the classic
// terminal shows up here too.
//
// Only fetched when the list is actually on screen: in a narrow transcript
// it is `display: none`, and a list nobody can see is not worth a request
// on every tab switch.
function railVisible() {
  const rail = $("#chatRail");
  return !!rail && getComputedStyle(rail).display !== "none";
}

async function refreshChatRail() {
  if (!railVisible()) return;
  try {
    const data = await api(convQuery());
    chatState.convs = data.conversations || [];
    chatState.convSources = data.sources || [];
  } catch (e) {
    return;  // transient: the rail keeps whatever it last showed
  }
  // A kind remembered from a visit when it had runs, and none now (the
  // store prunes): back to your chats rather than an empty list with no
  // pill lit to explain it.
  if (chatState.convSource !== "you"
      && !chatState.convSources.some((o) => o.id === chatState.convSource)) {
    pickConvSource("you");
    return;
  }
  renderConvKinds();
  renderChatRail();
  renderChatHead();
}

function pickConvSource(id) {
  chatState.convSource = id;
  prefSet(CONV_SOURCE_KEY, id);
  chatState.convs = [];
  renderConvKinds();
  renderChatRail();
  refreshChatRail();
}

// The pills: Chats first, then every background face that has run here,
// each with its count. A house where nothing but you has driven Claude
// gets no pill row at all — one pill is a label, not a choice.
function renderConvKinds() {
  const host = $("#chatRailKinds");
  if (!host) return;
  const kinds = chatState.convSources.filter((o) => o.id === "you" || o.count);
  const current = kinds.find((o) => o.id === chatState.convSource);
  const title = $("#chatRailTitle");
  if (title) {
    title.textContent = !current || current.id === "you" ? "Your chats" : current.label;
  }
  const hint = $("#chatRailHint");
  if (hint) {
    const blurb = current && current.id !== "you" ? current.blurb || "" : "";
    hint.textContent = blurb ? blurb.charAt(0).toUpperCase() + blurb.slice(1) : "";
    hint.hidden = !blurb;
  }
  host.textContent = "";
  host.hidden = kinds.length < 2;
  if (host.hidden) return;
  kinds.forEach((o) => {
    const on = o.id === chatState.convSource;
    const b = el("button", "pill crkind" + (on ? " active" : ""));
    b.type = "button";
    b.dataset.source = o.id;
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.appendChild(document.createTextNode(o.label));
    b.appendChild(el("span", "pillcount", String(o.count)));
    if (o.blurb) b.title = o.blurb;
    b.addEventListener("click", () => { if (!on) pickConvSource(o.id); });
    host.appendChild(b);
  });
}

function renderChatRail() {
  const list = $("#chatRailList");
  if (!list) return;
  list.textContent = "";
  if (!chatState.convs.length && chatState.convSource !== "you") {
    list.appendChild(el("div", "crempty", "None kept."));
    return;
  }
  if (!chatState.convs.length) {
    const empty = el("div", "crempty");
    empty.appendChild(el("p", null, "No chats yet."));
    // On the list page this is the whole screen, so the way to start one
    // is on it rather than only in the corner.
    const start = el("button", "btn small primary", "Ask");
    start.type = "button";
    start.addEventListener("click", () => $("#chatNew").click());
    empty.appendChild(start);
    list.appendChild(empty);
    return;
  }
  chatState.convs.forEach((c) => {
    // The one you are in is marked rather than hidden: a list that silently
    // omits the current item makes you wonder where it went. On the list
    // page it is also the way back into it.
    const here = !!chatState.sessionId && c.id === chatState.sessionId;
    const row = el("div", "crrow");
    const btn = el("button", "critem" + (here ? " active" : ""));
    btn.type = "button";
    btn.appendChild(el("span", "ctitle", c.title));
    const foot = el("div", "crfoot");
    const mark = convMark(c);
    if (mark) foot.appendChild(mark);
    foot.appendChild(el("span", "cwhen", c.age));
    btn.appendChild(foot);
    if (here) btn.setAttribute("aria-current", "true");
    if (c.view_only) {
      // A card or fix run: a record to read, never a place to type.
      btn.addEventListener("click", () => viewConversation(c));
    } else if (here) {
      btn.addEventListener("click", () => askShow("chat"));
    } else {
      btn.addEventListener("click", () => resumeConversation(c));
    }
    row.appendChild(btn);
    // Card and fix runs live in the engine's own store, which this list's
    // delete cannot reach.
    if (!c.view_only) row.appendChild(convRowMenu(c));
    list.appendChild(row);
  });
}

$("#chatRailNew").addEventListener("click", () => $("#chatNew").click());

// ------------------------------------------------- the list page (narrow)
//
// Below the rail's breakpoint there is no room for a list beside a
// transcript, and the tab used to open straight into the last transcript
// with the list two presses deep in ⋯ — the reported "no way back to the
// list". So Ask opens on the list there, picking a row (or starting a chat)
// opens the transcript, and the transcript's head carries the way back.
// On a wide screen none of this applies: the rail is the list.
const ASK_WIDE = "(min-width: 900px)";

function askNarrow() {
  return !window.matchMedia(ASK_WIDE).matches;
}

function askOnList() {
  return document.body.classList.contains("ask-list");
}

function askShow(page) {
  const list = page === "list" && askNarrow() && chatState.session !== "classic";
  document.body.classList.toggle("ask-list", list);
  if (list) refreshChatRail();
  renderChatHead();
}

// The transcript's head on a narrow screen: what this conversation is. A
// discussion is called by its card, which is the link back to it.
function renderChatHead() {
  const title = $("#chatHeadTitle");
  if (!title) return;
  const f = chatState.finding;
  const row = chatState.sessionId
    && (chatState.convs || []).find((c) => c.id === chatState.sessionId);
  title.textContent = f ? cardTitleOf(f)
    : row ? row.title
    : chatLog().childElementCount ? "Chat" : "New chat";
}

$("#chatBack").addEventListener("click", () => askShow("list"));
$("#chatOpen").addEventListener("click", () => askShow("list"));
window.matchMedia(ASK_WIDE).addEventListener("change", () => {
  if (!askNarrow()) document.body.classList.remove("ask-list");
  refreshChatRail();
});

async function resumeConversation(conv) {
  askShow("chat");
  // Nothing to wait for when the process is already there — the switch is
  // a change of attachment. A "one moment" toast over something instant is
  // a toast that teaches people to expect a wait.
  const held = chatState.liveSessions[conv.id];
  if (!held) toast("Opening that conversation…");
  try {
    // `spawn: false`: opening a conversation is reading it. Its transcript
    // comes over now and the Claude process starts with the first message
    // you send — not one per conversation you happened to look at.
    const out = await api("api/chat/resume", {
      method: "POST",
      body: JSON.stringify({ session_id: conv.id, spawn: false }) });
    // The row's state rides back so the composer line is right before the
    // reconnect's snapshot lands — and a fallback is a state on the line
    // ("Context lost") rather than only the toast below, which vanishes.
    if (out && out.row_state) {
      chatState.composer = out.row_state;
      renderComposerState();
    }
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

// A card or fix run opens as a record, not a conversation. Its turns ran
// under the analyst's read-only scoping (or the fixer's), so the chat never
// resumes one — what you get is exactly what brAIn sent to Claude about the
// house and what came back, tool calls and all.
async function viewConversation(conv) {
  openBox("#convViewModal");
  $("#convViewTitle").textContent = { fix: "Fix run", triage: "Checking a finding" }[conv.source]
    || "Card run";
  $("#convViewMeta").textContent = `${conv.title} · ${conv.age}`;
  const log = $("#convViewLog");
  log.textContent = "Loading…";
  // While a record is open the composer says so and offers the one thing
  // that fits: asking a new chat about it. Set before the fetch, so the
  // line is right even if the replay is slow or fails.
  chatState.record = { id: conv.id, title: conv.title || "", text: "" };
  renderComposerState();
  let data;
  try {
    data = await api(`api/chat/conversation/${encodeURIComponent(conv.id)}/view`);
  } catch (e) {
    log.textContent = e.message;
    return;
  }
  log.textContent = "";
  const events = data.events || [];
  renderReplayInto(log, events);
  // What "Ask about it" quotes: the run's last words, bounded — a card
  // run's final text is its verdict, and 600 characters of it is context
  // for a question, not a second copy of the transcript.
  const last = events.filter((ev) => ev.type === "text" && ev.text).pop();
  if (chatState.record && chatState.record.id === conv.id) {
    chatState.record.text = last ? String(last.text).slice(0, 600) : "";
  }
}

// A machine run's opening turn is the prompt brAIn built — a card run's is
// pages of focus, measurements and data — and drawn as a bubble it buried
// the answer several screens down. A long one is its first line with the
// rest one press away, `chatUserNode`'s shape for a Discuss opener.
const REPLAY_PROMPT_FOLD = 400;

// A line cut to `max` characters at a word, with an ellipsis that says it
// was cut. Slicing mid-word ("Every sensor it builds t") reads as a typo.
function clipWords(text, max) {
  const t = String(text || "");
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return (space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.—-]+$/, "") + "…";
}

function replayUserNode(text) {
  const t = String(text || "");
  if (t.length <= REPLAY_PROMPT_FOLD) {
    const row = el("div", "msg user");
    row.appendChild(el("div", "bubble", t));
    return row;
  }
  const row = el("div", "msg user");
  const bubble = el("div", "bubble discuss");
  const first = t.split("\n").find((line) => line.trim()) || t;
  bubble.appendChild(el("div", "dtitle", clipWords(first.trim(), 160)));
  const more = el("details", "dmore");
  more.appendChild(el("summary", null, "What brAIn asked Claude"));
  more.appendChild(el("div", "dbody", t));
  bubble.appendChild(more);
  row.appendChild(bubble);
  return row;
}

function closeConvView() {
  closeBox("#convViewModal");
  chatState.record = null;
  renderComposerState();
}

// The replay's five event shapes, drawn with the same nodes the chat uses —
// but into a given host, with the call→result pairing held locally, because
// this renderer must never touch the live chat's state.
function renderReplayInto(host, events) {
  const tools = new Map();
  events.forEach((ev) => {
    if (ev.type === "user") {
      host.appendChild(replayUserNode(ev.text));
    } else if (ev.type === "text") {
      host.appendChild(chatMarkdown(ev.text));
    } else if (ev.type === "background") {
      host.appendChild(chatBackgroundNode(ev));
    } else if (ev.type === "thinking") {
      const box = el("details", "think");
      box.appendChild(el("summary", null, "Thinking"));
      const body = el("div", "tbody");
      body.innerHTML = renderMarkdown(ev.text || "");
      box.appendChild(body);
      host.appendChild(box);
    } else if (ev.type === "tool") {
      const node = chatToolNode(ev);
      node.classList.remove("running");   // a record has no spinner to earn
      host.appendChild(node);
      if (ev.id) tools.set(ev.id, node);
    } else if (ev.type === "tool_result") {
      const box = tools.get(ev.id);
      if (!box) return;
      box.classList.add(ev.ok ? "ok" : "bad");
      const body = box.querySelector(".tbody");
      body.appendChild(el("div", "tlabel", ev.ok ? "Result" : "Error"));
      const pre = el("pre");
      pre.appendChild(el("code", null, ev.text || "(no output)"));
      body.appendChild(pre);
    }
  });
  if (!host.childElementCount) {
    host.appendChild(el("div", "crempty",
      "Nothing to show — this run left no readable transcript."));
  }
}

$("#convViewClose").addEventListener("click", closeConvView);
$("#convViewModal").addEventListener("click", (ev) => {
  if (ev.target === $("#convViewModal")) closeConvView();
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
    ? (chatState.defaultModelLabel || chatState.defaultModel)
    : "the CLI's own choice";
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
    // The meta line is the only confirmation a pick landed, and the event
    // that would refresh it (init → info) does not arrive until the next
    // message — a restarted --resume process says nothing until spoken to.
    // So the response carries the server-made label (same parser as the
    // info event; never a second regex here) and the line updates now. A
    // pick that resolves to "let the CLI choose" has no name to show yet,
    // so the Default label stands in until the next init says for sure.
    chatState.info = Object.assign({}, chatState.info, {
      model: out.model || "",
      model_label: out.model_label || chatState.defaultModelLabel || "default",
    });
    chatMeta();
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
// but the handoff left a record and Claude Code writes every conversation
// as it goes, so the server picks the conversation the chat handed over —
// or the one the terminal has written to since — and never one a chat in
// the background is still holding (`chat_session.pick_adopted`). It opens
// it through the registry, so nothing here is stopped to make the switch.
// That Claude is left running: it is somebody's shell.
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
      setTermMode("classic", "Ask now opens as the classic terminal");
      return;
    }
    setTermMode("chat", "Ask now opens as chat");
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
  // Saved, not peeked: the same setting ⚙ → Terminal & chat changes.
  btn.setAttribute("aria-label",
    classic ? "Switch to chat (Ask opens this way from now on)"
      : "Switch to the classic terminal (Ask opens this way from now on)");
  $("#termModeLabel").textContent = label;
  const onTab = currentView === "terminal";
  if (classic) {
    chatDisconnect();
    // One shell, no list: the list page is the chat face's alone.
    document.body.classList.remove("ask-list");
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

// ------------------------------------------------------------ share modal
// Taking a card somewhere else, two ways. As a picture: the card's face —
// title, answer, numbers and chart, no menus and no token count — drawn to
// a PNG you can paste into a message. On a dashboard: brAIn adds a Webpage
// card to the dashboard and view you pick, which is what used to be a
// block of YAML and four steps in another app. The YAML is still here for
// the one case brAIn cannot write, a dashboard kept in YAML.
//
// The chart is model-authored script in a sandboxed frame with no origin
// of its own, so nothing out here can read it. The frame draws ITSELF
// (`snapInFrame`, injected into its srcdoc) and posts back a PNG; this side
// only ever sees pixels. It is a fresh frame at one fixed width rather than
// the one on screen, so a card shared from a phone is the same picture as
// one shared from a desktop.

let cardInfoCache = null;
const shareState = {
  insight: null, blob: null, url: null, dashboards: [], seq: 0, info: null,
};
const SHARE_WIDTH = 720;
const SNAP_FRAME_WIDTH = 664;

// Runs INSIDE the chart's frame, as source text: nothing here may close
// over anything from the panel. It clones the page, inlines the few
// computed styles an animation leaves behind (a line drawn in with a dash
// offset is invisible without them once animations are switched off), and
// draws the clone through an SVG foreignObject onto a canvas.
function snapInFrame(ID) {
  function styles() {
    var out = [];
    var tags = document.querySelectorAll("style");
    for (var i = 0; i < tags.length; i++) out.push(tags[i].textContent);
    return out.join("\n");
  }
  function snap(scale) {
    return new Promise(function (resolve, reject) {
      var body = document.body;
      var w = Math.ceil(document.documentElement.clientWidth || body.scrollWidth);
      var h = Math.ceil(Math.max(body.scrollHeight, body.getBoundingClientRect().height));
      var clone = body.cloneNode(true);
      var src = body.getElementsByTagName("*");
      var dst = clone.getElementsByTagName("*");
      var keep = ["opacity", "transform", "transform-origin", "stroke-dasharray",
        "stroke-dashoffset", "fill-opacity", "stroke-opacity", "visibility", "clip-path"];
      for (var i = 0; i < src.length && i < dst.length; i++) {
        var node = src[i];
        if (node.tagName && node.tagName.toLowerCase() === "canvas") {
          try {
            var pic = document.createElement("img");
            pic.src = node.toDataURL();
            pic.setAttribute("style", "width:" + node.clientWidth + "px;height:" + node.clientHeight + "px");
            dst[i].parentNode.replaceChild(pic, dst[i]);
          } catch (e) { /* a tainted canvas is left out of the picture */ }
          continue;
        }
        var anims = node.getAnimations ? node.getAnimations() : [];
        if (!anims.length) continue;
        var cs = getComputedStyle(node);
        var inline = "";
        for (var j = 0; j < keep.length; j++) {
          var v = cs.getPropertyValue(keep[j]);
          if (v) inline += keep[j] + ":" + v + " !important;";
        }
        dst[i].setAttribute("style", (dst[i].getAttribute("style") || "") + ";" + inline);
      }
      var scripts = clone.getElementsByTagName("script");
      for (var k = scripts.length - 1; k >= 0; k--) scripts[k].parentNode.removeChild(scripts[k]);
      var text = styles();
      var css = text.replace(/(^|[\s,}>])(?::root|html|body)(?=[\s,{:.#\[>])/g, "$1.brsnap");
      var names = text.match(/--[\w-]+/g) || [];
      var rootStyle = getComputedStyle(document.documentElement);
      var vars = "";
      var seen = {};
      for (var n = 0; n < names.length; n++) {
        if (seen[names[n]]) continue;
        seen[names[n]] = 1;
        var val = rootStyle.getPropertyValue(names[n]);
        if (val) vars += names[n] + ":" + val.trim() + ";";
      }
      var bs = getComputedStyle(body);
      var wrap = document.createElement("div");
      wrap.className = "brsnap";
      wrap.setAttribute("style", vars + "width:" + w + "px;margin:0;font-family:" + bs.fontFamily
        + ";color:" + bs.color + ";font-size:" + bs.fontSize + ";line-height:" + bs.lineHeight + ";");
      var sheet = document.createElement("style");
      sheet.textContent = css + "\n*{animation:none !important;transition:none !important}";
      wrap.appendChild(sheet);
      while (clone.firstChild) wrap.appendChild(clone.firstChild);
      var xml = new XMLSerializer().serializeToString(wrap);
      var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h
        + '"><foreignObject x="0" y="0" width="100%" height="100%">' + xml + "</foreignObject></svg>";
      var img = new Image();
      img.onload = function () {
        try {
          var canvas = document.createElement("canvas");
          canvas.width = w * scale;
          canvas.height = h * scale;
          var ctx = canvas.getContext("2d");
          ctx.scale(scale, scale);
          ctx.drawImage(img, 0, 0);
          resolve({ png: canvas.toDataURL("image/png"), w: w, h: h });
        } catch (e) { reject(e); }
      };
      img.onerror = function () { reject(new Error("the chart could not be drawn")); };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
  }
  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (!d || d.type !== "bruh-snap" || d.id !== ID || ev.source !== parent) return;
    snap(d.scale || 2).then(function (r) {
      parent.postMessage({ type: "bruh-snapped", id: ID, png: r.png, w: r.w, h: r.h }, "*");
    }, function (e) {
      parent.postMessage({ type: "bruh-snapped", id: ID, error: String((e && e.message) || e) }, "*");
    });
  });
}

const SNAP_SNIPPET = (id) =>
  `<script>(${snapInFrame.toString()})(${jsonInScript(id)});<\/script>`;

function askSnap(frame, frameId) {
  return new Promise((resolve, reject) => {
    let timer = null;
    const onMsg = (ev) => {
      const d = ev.data;
      if (!d || d.type !== "bruh-snapped" || d.id !== frameId) return;
      if (ev.source !== frame.contentWindow) return;
      done();
      if (d.error || !d.png) reject(new Error(d.error || "no picture"));
      else resolve(d);
    };
    const done = () => {
      clearTimeout(timer);
      window.removeEventListener("message", onMsg);
    };
    timer = setTimeout(() => { done(); reject(new Error("the chart did not answer")); }, 8000);
    window.addEventListener("message", onMsg);
    frame.contentWindow.postMessage({ type: "bruh-snap", id: frameId, scale: 2 }, "*");
  });
}

async function snapChart(insight) {
  if (!insight.html) return null;
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("tabindex", "-1");
  frame.className = "snapframe";
  frame.style.width = `${SNAP_FRAME_WIDTH}px`;
  const frameId = `snap-${state.frameSeq++}`;
  frame.dataset.frame = frameId;
  frame.srcdoc = insight.html + SIZE_SNIPPET(frameId) + SNAP_SNIPPET(frameId);
  document.body.appendChild(frame);
  try {
    await new Promise((res) => {
      frame.addEventListener("load", res, { once: true });
      setTimeout(res, 5000);
    });
    // The contract allows a draw-in of up to 800ms; a picture taken during
    // it is a chart half drawn.
    await new Promise((res) => setTimeout(res, 1100));
    return await askSnap(frame, frameId);
  } finally {
    frame.remove();
  }
}

// A PNG the chart's frame sent, as pixels. Only a base64 PNG data URL is
// accepted, it is decoded here rather than loaded, and anything else is no
// chart at all.
async function chartBitmap(png) {
  const m = typeof png === "string"
    && png.match(/^data:image\/png;base64,([A-Za-z0-9+/]+={0,2})$/);
  if (!m) return null;
  try {
    const raw = atob(m[1]);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return await createImageBitmap(new Blob([bytes], { type: "image/png" }));
  } catch (e) {
    return null;
  }
}

function shareEyebrow(insight) {
  if (insight.eyebrow) return insight.eyebrow;
  const named = insight.category_title;
  if (named && named !== "Custom") return named;
  const cats = (state.status && state.status.categories) || [];
  const cat = cats.find((c) => c.id === insight.category);
  return cat ? cat.title : "";
}

// The card's face, laid out in the panel's own colours and drawn to a PNG.
async function composeCardImage(insight, chart) {
  const root = getComputedStyle(document.documentElement);
  const v = (name, fallback) => root.getPropertyValue(name).trim() || fallback;
  const surface = v("--surface", "#ffffff");
  const ink = v("--ink", "#0a1622");
  const ink2 = v("--ink-2", "#33506a");
  const ink3 = v("--ink-3", "#7e96aa");
  const tile = v("--surface-2", "#e8f1f8");
  const line = v("--hairline", "rgba(10,22,34,0.1)");
  const font = 'system-ui,-apple-system,"Segoe UI",sans-serif';
  const add = (parent, tag, style, text) => {
    const node = document.createElement(tag);
    node.setAttribute("style", style);
    if (text != null) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  };
  const box = add(null, "div", `width:${SHARE_WIDTH}px;box-sizing:border-box;`
    + `padding:26px 28px 20px;background:${surface};color:${ink};font-family:${font};`
    + "display:flex;flex-direction:column;gap:14px");
  const head = add(box, "div", "display:flex;flex-direction:column;gap:3px");
  const eyebrow = shareEyebrow(insight);
  if (eyebrow) add(head, "div", `font-size:12px;font-weight:600;color:${ink3}`, eyebrow);
  add(head, "div", "font-size:20px;font-weight:600;line-height:1.4", insight.title || "");
  if (insight.summary) {
    const [lead, rest] = splitLead(insight.summary);
    const sum = add(box, "div", `font-size:14px;line-height:1.45;color:${ink2}`);
    if (lead) add(sum, "strong", `color:${ink}`, lead);
    sum.appendChild(document.createTextNode(lead ? ` ${rest}` : rest));
  }
  const hls = (insight.highlights || []).filter((h) => h && h.label).slice(0, 6);
  if (hls.length) {
    const cols = hls.length <= 4 ? hls.length : 3;
    const grid = add(box, "div", "display:grid;gap:8px;"
      + `grid-template-columns:repeat(${cols},minmax(0,1fr))`);
    hls.forEach((h) => {
      const t = add(grid, "div", `background:${tile};border-radius:10px;padding:10px 12px;`
        + "display:flex;flex-direction:column;gap:3px");
      add(t, "div", `font-size:12px;color:${ink3}`, String(h.label));
      add(t, "div", "font-size:20px;font-weight:600;line-height:1.2",
        String(h.value != null ? h.value : "—"));
      if (h.delta) add(t, "div", `font-size:12px;color:${ink2}`, String(h.delta));
    });
  }
  // The chart is NOT an <img> in the markup. Its PNG arrives in a message
  // from a frame running model-authored script, so nothing it sends is
  // ever used as a URL: the bytes are decoded into a bitmap, a spacer of
  // the right height holds its place in the layout, and the bitmap is
  // painted onto the canvas at the spacer's position afterwards.
  const bitmap = chart ? await chartBitmap(chart.png) : null;
  let spacer = null;
  if (bitmap) {
    const inner = SHARE_WIDTH - 56;
    spacer = add(box, "div", `width:${inner}px;`
      + `height:${Math.round(inner * bitmap.height / bitmap.width)}px`);
  }
  const foot = add(box, "div", `display:flex;justify-content:space-between;`
    + `padding-top:10px;border-top:1px solid ${line};font-size:12px;color:${ink3}`);
  add(foot, "span", "font-weight:700", "brAIn");
  const when = insight.generated_at ? new Date(insight.generated_at) : null;
  add(foot, "span", "", when && !isNaN(when.getTime())
    ? `Analysed ${when.toLocaleString([], {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
    : "");

  const holder = add(document.body, "div", "position:fixed;left:-20000px;top:0");
  holder.appendChild(box);
  try {
    const height = Math.ceil(box.getBoundingClientRect().height);
    const slot = spacer ? {
      x: spacer.offsetLeft, y: spacer.offsetTop,
      w: spacer.offsetWidth, h: spacer.offsetHeight,
    } : null;
    const xml = new XMLSerializer().serializeToString(box);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${SHARE_WIDTH}" `
      + `height="${height}"><foreignObject x="0" y="0" width="100%" height="100%">`
      + `${xml}</foreignObject></svg>`;
    const img = new Image();
    await new Promise((res, rej) => {
      img.onload = res;
      img.onerror = () => rej(new Error("the card could not be drawn"));
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    });
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = SHARE_WIDTH * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = surface;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    if (bitmap && slot) ctx.drawImage(bitmap, slot.x, slot.y, slot.w, slot.h);
    return await new Promise((res, rej) => canvas.toBlob(
      (b) => (b ? res(b) : rej(new Error("no image"))), "image/png"));
  } finally {
    holder.remove();
  }
}

async function drawShare(seq) {
  const shot = $("#shareShot");
  const note = $("#shareShotNote");
  const insight = shareState.insight;
  let chart = null;
  let chartErr = "";
  try {
    chart = await snapChart(insight);
  } catch (e) {
    chartErr = e.message;
  }
  if (seq !== shareState.seq) return;
  let blob = null;
  try {
    blob = await composeCardImage(insight, chart);
  } catch (e) {
    if (seq !== shareState.seq) return;
    shot.textContent = "";
    shot.appendChild(el("span", "hint",
      `This browser would not draw the card as a picture (${e.message}). `
      + "Adding it to a dashboard below still works."));
    return;
  }
  if (seq !== shareState.seq) return;
  if (shareState.url) URL.revokeObjectURL(shareState.url);
  shareState.blob = blob;
  shareState.url = URL.createObjectURL(blob);
  shot.textContent = "";
  const img = el("img");
  img.src = shareState.url;
  img.alt = `Picture of the card “${insight.title || ""}”`;
  shot.appendChild(img);
  $("#shareCopy").disabled = false;
  $("#shareDownload").disabled = false;
  // Said, never silent: a picture with the chart missing looks like a
  // card that never had one.
  note.textContent = chartErr
    ? `The chart could not be included (${chartErr}) — the picture has the `
      + "answer and the numbers."
    : "";
  note.classList.toggle("hidden", !chartErr);
}

async function copyShareImage() {
  const blob = shareState.blob;
  if (!blob) return;
  try {
    if (!navigator.clipboard || !window.ClipboardItem || !window.isSecureContext) {
      throw new Error("no clipboard");
    }
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    toast("Copied — paste the picture anywhere");
  } catch (e) {
    // Home Assistant's ingress frame and several phones refuse an image on
    // the clipboard outright, with no way to ask first. The picture is on
    // screen, which is the fallback: right-click or long-press it.
    toast("This browser won't let brAIn copy a picture — right-click or "
      + "long-press the picture above to copy it, or use Download");
  }
}

function downloadShareImage() {
  if (!shareState.url) return;
  const title = (shareState.insight && shareState.insight.title) || "brain-card";
  const name = title.toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "").slice(0, 60) || "brain-card";
  const a = document.createElement("a");
  a.href = shareState.url;
  a.download = `${name}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// How tall the dashboard card should be, as Home Assistant's Webpage card
// wants it: a percentage of its width. Read off the card as it is drawn
// here, because that is the best guess anybody has of how tall the page
// will be; a card that is not on screen gets an ordinary shape.
function shareAspect(show) {
  const id = shareState.insight && shareState.insight.id;
  const card = id && document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  const target = card && (show === "chart" ? card.querySelector(".viz iframe") : card);
  if (!target) return show === "chart" ? 60 : 90;
  const r = target.getBoundingClientRect();
  if (!r.width || !r.height) return show === "chart" ? 60 : 90;
  const pad = show === "chart" ? 0 : -40;   // no head buttons, no foot
  return Math.round(Math.min(Math.max((r.height + pad) / r.width * 100, 25), 300));
}

function shareUrl(show) {
  const info = shareState.info;
  if (!info || !shareState.insight) return "";
  const url = `${info.local_dir}/${shareState.insight.id}${info.local_suffix}`;
  return show === "chart" ? url : url.replace(/\.html$/, ".card.html");
}

function fillShareYaml() {
  const show = $("#shareShow").value;
  const url = shareUrl(show);
  if (!url) return;
  const lines = ["type: iframe", `url: ${url}`, `aspect_ratio: ${shareAspect(show)}%`];
  if (show === "chart") {
    lines.push(`title: ${(shareState.insight.title || "Insight")
      .replace(/[:#"\n]/g, " ").trim()}`);
  }
  $("#cardYaml").textContent = lines.join("\n");
}

function onShareDash() {
  const d = shareState.dashboards[Number($("#shareDash").value)];
  const views = $("#shareView");
  views.textContent = "";
  const warn = $("#shareDashWarn");
  const reason = d ? d.reason : "";
  warn.textContent = reason;
  warn.classList.toggle("hidden", !reason);
  (d && d.views ? d.views : []).forEach((view) => {
    const opt = el("option", null, view.title);
    opt.value = String(view.index);
    views.appendChild(opt);
  });
  views.disabled = !(d && d.views && d.views.length);
  $("#shareAdd").disabled = !(d && d.editable && d.views && d.views.length);
  if (d && d.editable && !(d.views || []).length) {
    warn.textContent = "This dashboard has no views yet — add one in Home Assistant first.";
    warn.classList.remove("hidden");
  }
}

async function loadShareDashboards(seq) {
  const sel = $("#shareDash");
  sel.textContent = "";
  sel.appendChild(el("option", null, "Loading…"));
  sel.disabled = true;
  $("#shareView").textContent = "";
  $("#shareAdd").disabled = true;
  let res = null;
  try {
    res = await api("api/dashboards");
  } catch (e) {
    res = { dashboards: [], error: e.message };
  }
  if (seq !== shareState.seq) return;
  shareState.dashboards = res.dashboards || [];
  sel.textContent = "";
  shareState.dashboards.forEach((d, i) => {
    const opt = el("option", null, d.editable ? d.title : `${d.title} (can't add here)`);
    opt.value = String(i);
    sel.appendChild(opt);
  });
  sel.disabled = !shareState.dashboards.length;
  const first = shareState.dashboards.findIndex((d) => d.editable);
  if (first >= 0) sel.value = String(first);
  if (res.error && !shareState.dashboards.length) {
    const warn = $("#shareDashWarn");
    warn.textContent = res.error;
    warn.classList.remove("hidden");
    return;
  }
  onShareDash();
}

async function addShareToDashboard() {
  const d = shareState.dashboards[Number($("#shareDash").value)];
  if (!d || !shareState.insight) return;
  const show = $("#shareShow").value;
  const btn = $("#shareAdd");
  btn.disabled = true;
  const note = $("#shareDashNote");
  try {
    const res = await api(`api/card/${shareState.insight.id}/dashboard`, {
      method: "POST",
      body: JSON.stringify({
        url_path: d.url_path, view: Number($("#shareView").value),
        show, aspect: shareAspect(show),
      }),
    });
    note.textContent = `Added to ${d.title} → ${res.view}. It shows the latest `
      + "run and changes whenever brAIn refreshes this card.";
    toast(`Added to ${d.title} → ${res.view}`);
  } catch (e) {
    note.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function openShare(insight) {
  shareState.seq += 1;
  const seq = shareState.seq;
  shareState.insight = insight;
  shareState.blob = null;
  $("#shareTitle").textContent = `Share — ${insight.title || "card"}`;
  const shot = $("#shareShot");
  shot.textContent = "";
  shot.appendChild(el("span", "hint", "Drawing the card…"));
  $("#shareShotNote").classList.add("hidden");
  $("#shareCopy").disabled = true;
  $("#shareDownload").disabled = true;
  $("#shareDashWarn").classList.add("hidden");
  $("#shareDashNote").textContent = "";
  $("#cardYaml").textContent = "Loading…";
  openBox("#shareModal");
  drawShare(seq);
  loadShareDashboards(seq);
  try {
    if (!cardInfoCache) cardInfoCache = await api("api/card_info");
  } catch (e) {
    $("#cardYaml").textContent = "Could not load card info: " + e.message;
    return;
  }
  if (seq !== shareState.seq) return;
  shareState.info = cardInfoCache;
  if (!cardInfoCache.www_cards) {
    $("#cardYaml").textContent = "Dashboard cards are unavailable: the add-on could "
      + "not write to /config/www. Check that the /config mount is writable and "
      + "restart the add-on.";
    return;
  }
  fillShareYaml();
  // The panel shares Home Assistant's origin (ingress), so it can check
  // that /local is really being served before promising a card will load.
  try {
    const probe = await fetch(shareUrl("card"), { cache: "no-store" });
    if (!probe.ok) throw new Error(String(probe.status));
  } catch (e) {
    if (seq !== shareState.seq) return;
    const warn = $("#shareDashWarn");
    warn.textContent = "Home Assistant isn't serving brAIn's cards yet — its www "
      + "folder was just created. Restart Home Assistant once (Settings → System → "
      + "⋮ → Restart Home Assistant), then the card will load.";
    warn.classList.remove("hidden");
  }
}

$("#shareCopy").addEventListener("click", copyShareImage);
$("#shareDownload").addEventListener("click", downloadShareImage);
$("#shareDash").addEventListener("change", onShareDash);
$("#shareShow").addEventListener("change", fillShareYaml);
$("#shareAdd").addEventListener("click", addShareToDashboard);
$("#cardCopy").addEventListener("click", () => {
  copyText($("#cardYaml").textContent).then((ok) =>
    toast(ok ? "YAML copied — paste it into a dashboard card" :
      "Copy failed — select the YAML and copy manually"));
});
$("#shareClose").addEventListener("click", () => closeBox("#shareModal"));
$("#shareModal").addEventListener("click", (ev) => {
  if (ev.target === $("#shareModal")) closeBox("#shareModal");
});

// ------------------------------------------------------------------ boot

$("#reportSearch")?.addEventListener("input", (ev) => {
  state.query = ev.currentTarget.value;
  render();
});

$("#askForm")?.addEventListener("submit", async (ev) => {
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
    if (["starting", "awaiting_code", "working"].includes(st.phase)) pollSetup();
  }).catch(() => {});
});

(async function init() {
  adoptSetupScreens();
  bindSetup();
  try {
    await Promise.all([refreshStatus(), refreshInsights()]);
  } catch (e) {
    toast("Could not reach the add-on: " + e.message);
  }
  await refreshOnboarding();
  render();
  fastPoll();
  // Today is where the panel lands, so its lists are fetched at boot: the
  // queue, the findings under it, the suggestions, Your list and the two
  // cards no store owns. The badge is the queue's count.
  refreshToday().then(() => { if (currentView === "findings") renderFindings(); });
  // Reports' two rows under the grid are read when Reports is opened; at
  // boot only if the panel happens to land there.
  if (currentView === "insights") {
    refreshIdeas().then(renderIdeas);
    refreshDeepReview();
  }
  // resume a guided sign-in if one is mid-flight (page reload)
  try {
    const st = await api("api/auth/setup/status");
    if (["starting", "awaiting_code", "working"].includes(st.phase)) pollSetup();
  } catch (e) { /* ignore */ }
})();

// --------------------------------------------------------------- upkeep
// Home Assistant's own maintainer: the house book, names and rooms, the
// upgrade advisor and the overnight check. Five GETs read what each has;
// every press STARTS a run and the section polls its own GET until the run
// is no longer `running` — a run is minutes, and ingress will not hold a
// request that long. Drawn from what we have, then again once the fetch
// lands, so opening the tab is never a blank frame.
const upState = {
  tidy: null, upgrades: null, sre: null, book: null, access: null,
  ticked: new Set(), polls: {},
};

async function refreshUpkeep() {
  const get = (path) => api(path).catch((e) => ({ fetch_error: e.message }));
  const [tidy, upgrades, sre, book, access] = await Promise.all([
    get("api/tidy"), get("api/upgrades"), get("api/sre"),
    get("api/house_book"), get("api/access")]);
  Object.assign(upState, { tidy, upgrades, sre, book, access });
  // A new proposal ticks every row by default: the table is a review, and
  // untick-what-you-disagree-with is one press per objection.
  const rows = ((tidy && tidy.proposal) || {}).rows || [];
  const ids = new Set(rows.map((r) => r.id));
  if (![...upState.ticked].every((i) => ids.has(i)) || !upState.ticked.size) {
    upState.ticked = ids;
  }
}

function renderUpkeep() {
  renderUpBook();
}

// Poll one section's GET while its run is in flight.
function upWatch(key, path) {
  clearTimeout(upState.polls[key]);
  const tick = async () => {
    try {
      upState[key] = await api(path);
    } catch (e) { /* keep what we had */ }
    renderUpkeep();
    if (upState[key] && upState[key].running
        && currentView === "housebook") {
      upState.polls[key] = setTimeout(tick, 3000);
    } else if (key === "tidy") {
      await refreshUpkeep();
      renderUpkeep();
    }
  };
  upState.polls[key] = setTimeout(tick, 1500);
}

async function upPress(btn, key, path, body, done) {
  btn.disabled = true;
  try {
    const data = await api(path, {
      method: "POST", ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (data && typeof data === "object" && key) upState[key] = { ...upState[key], ...data };
    if (done) toast(done(data));
    renderUpkeep();
    if (data && data.running) upWatch(key, `api/${key === "book" ? "house_book" : key}`);
    return data;
  } catch (e) {
    toast(e.message || "that didn't work");
    btn.disabled = false;
    return null;
  }
}

function upLine(text, cls) {
  return el("p", "upline" + (cls ? " " + cls : ""), text);
}

function upStatus(state, runningText) {
  const box = el("div", "upstatus");
  if (!state) return box;
  if (state.fetch_error) box.appendChild(upLine("Could not ask the add-on: " + state.fetch_error, "warn"));
  if (state.running) box.appendChild(upLine(runningText, "busy"));
  if (state.last_error) box.appendChild(upLine("The last run did not finish: " + state.last_error, "warn"));
  if (state.held) box.appendChild(upLine("Not run on its schedule: " + state.held, "muted"));
  return box;
}

function upButton(label, hint, primary) {
  const b = el("button", "btn small" + (primary ? " primary" : ""), label);
  if (hint) tip(b, hint);
  return b;
}

// -- the house book
function renderUpBook() {
  const host = $("#upBook");
  if (!host) return;
  const st = upState.book || {};
  host.textContent = "";
  host.appendChild(upStatus(st, "Writing the house book…"));
  const book = st.book;
  // Two presses. Run writes it (or rewrites it); Share puts a copy at a
  // private address for a sitter's phone. The sentence under Share is what
  // that sitter is told too, so it is on screen whether or not it is shared.
  const actions = el("div", "upactions bookactions");
  const run = upButton("Run",
    book ? "Rewrite the house book now — one Claude run"
      : "Write the house book — one Claude run over your automations, "
        + "scripts, scenes and what brAIn has learned", !book);
  run.disabled = !!st.running;
  run.addEventListener("click", () => upPress(run, "book", "api/house_book/run", null,
    () => "Writing — it takes a minute or two"));
  actions.appendChild(run);
  if (book && !st.published) {
    const pub = upButton("Share",
      "Puts a copy at a private address Home Assistant serves, for a sitter's phone");
    pub.addEventListener("click", () => upPress(pub, "book", "api/house_book/publish", null,
      () => "Shared — the link is below"));
    actions.appendChild(pub);
  }
  host.appendChild(actions);
  host.appendChild(upLine("Every sentence names what it came from; codes and "
    + "passwords are left out.", "muted booksafe"));
  if (st.published) {
    const wrap = el("div", "uplink");
    const url = location.origin + st.published.path;
    const a = el("a", null, url);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    wrap.appendChild(a);
    const revoke = upButton("Delete",
      "Takes the link down: deletes the copy and changes the address, so the "
      + "old link stops working even for somebody who saved it");
    revoke.addEventListener("click", () => {
      if (!window.confirm("Delete the shared link? Anybody who has it loses "
        + "the house book; the book itself stays here.")) return;
      upPress(revoke, "book", "api/house_book/revoke", null,
        () => "Link deleted — it no longer works");
    });
    wrap.appendChild(revoke);
    host.appendChild(wrap);
  }
  if (!book) {
    if (!st.running) host.appendChild(upLine("No house book yet.", "muted"));
    return;
  }
  const when = book.at ? timeAgo(new Date(book.at * 1000).toISOString()) : "";
  host.appendChild(upLine(`Updated ${when}`
    + (book.uncited ? ` · ${book.uncited} sentence${book.uncited === 1 ? "" : "s"} left out for citing nothing brAIn could check` : ""), "muted"));
  for (const section of book.sections || []) {
    const sec = el("div", "upbooksec");
    sec.appendChild(el("h3", null, section.title));
    const ul = el("ul", "upbooklist");
    for (const entry of section.entries || []) {
      const li = el("li");
      li.appendChild(el("span", null, entry.text));
      const chips = el("span", "upchips");
      for (const src of entry.sources || []) chips.appendChild(el("span", "upchip", src.label));
      li.appendChild(chips);
      ul.appendChild(li);
    }
    sec.appendChild(ul);
    host.appendChild(sec);
  }
}

// The names-and-rooms table and the assessed updates are cards in Today's
// queue (makeTidyCard / makeUpdateCard); the overnight check and the access
// review are ⚙ › Diagnostics'. Nothing of the Upkeep pane is left but the
// house book above, which House › House book renders.

// ------------------------------------------------------------ the house now
// The words for what the house is doing (`/api/situation`, built by
// `panel/situation.py`), read by House › What happened's top line. The
// situation panel and calendar picker that sat over the old Findings feed
// are gone: the line is What happened's, the calendars are ⚙ › Sources'.
// The mode is a WORD and never a colour alone.
const HOUSE_MODE_WORDS = {
  home: "Someone's home",
  away: "Nobody's home",
  asleep: "Settled for the night",
  waking: "Waking up",
  guests: "Guests are here",
  unknown: "Not sure what the house is doing",
};
// ---------------------------------------------------------------------------
// Who hears what, when — the household's notification sentence (W2D)
// ---------------------------------------------------------------------------
//
// One sentence in the household's own words, saved on change like every
// other control in ⚙, and under it the lines a learned suggestion added —
// each on its own row with its own Remove, because a clause spliced into
// somebody's sentence is one they cannot find again to take out. The box
// is not overwritten while it has focus: `refreshOpenSettings` already
// skips a dialog with focus inside it, and a save re-renders only after
// the change that triggered it has landed.
function renderNotifyPolicy(settings) {
  // Speaking first is strictly opt-in, so only an explicit true ticks it:
  // a setting that arrived missing or malformed reads as off.
  const speak = $("#setSpeakFirst");
  if (speak) speak.checked = settings.speak_first === true;
  const box = $("#setNotifyPolicy");
  if (!box) return;
  if (document.activeElement !== box) box.value = settings.notify_policy || "";
  const list = $("#setNotifyLearned");
  const learned = Array.isArray(settings.notify_policy_learned)
    ? settings.notify_policy_learned : [];
  const wasOpen = !!list.querySelector("details[open]");
  list.textContent = "";
  list.classList.toggle("hidden", !learned.length);
  if (!learned.length) return;
  // Behind a disclosure that names how many: each line is a long sentence
  // (it names its subject both ways, for a person and for a model), and a
  // dialog measured against a height budget cannot spend a paragraph per
  // answer somebody once gave. It stays open across a re-render, because
  // a Remove re-renders and closing the list under the press reads as the
  // press having taken everything.
  const fold = document.createElement("details");
  fold.open = wasOpen;
  fold.appendChild(el("summary", null, learned.length === 1
    ? "1 line added from your answers"
    : `${learned.length} lines added from your answers`));
  learned.forEach((item) => {
    const row = el("div", "setlearnedrow");
    row.appendChild(el("span", "setlearnedtext", item.clause || ""));
    const remove = el("button", "btn ghost", "Remove");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove: " + (item.clause || ""));
    remove.addEventListener("click", () => {
      const keep = learned.filter((c) => c.id !== item.id);
      saveSettings({ notify_policy_learned: keep }, "Removed — that line no longer applies");
    });
    row.appendChild(remove);
    fold.appendChild(row);
  });
  list.appendChild(fold);
}

$("#setNotifyPolicy").addEventListener("change", () =>
  saveSettings({ notify_policy: $("#setNotifyPolicy").value.trim() },
    "Saved — brAIn will time and word notifications by it"));

$("#setSpeakFirst").addEventListener("change", () => {
  const on = $("#setSpeakFirst").checked;
  saveSettings({ speak_first: on }, on
    ? "On — an urgent problem is said aloud where somebody is, then sent to the phone"
    : "Off — problems go to the phone only");
});

// ---------------------------------------------------------------------------
// Every change is a contract: what a plan will do, exactly; the restore a
// fix's calls can be undone with; and what the acting half has done lately.
// ---------------------------------------------------------------------------

// The typed half of a plan, under its steps: why it cannot be applied, what
// will be different, how brAIn will check it held, and — for an edit to an
// automation — the exact bytes it will change and what a replay of the
// old and new config says. Every sentence here is the server's; this only
// lays them out.
function planContract(box, plan) {
  if (plan.ops_refused) box.appendChild(el("p", "findrisk", plan.ops_refused));
  if (!plan.can_fix) return;
  if (plan.expected_effect) {
    box.appendChild(el("p", "planeffect", `Once it works: ${plan.expected_effect}`));
  }
  (plan.preview || []).forEach((p) => {
    if (!p || !p.diff) return;
    const det = el("details", "plandiff");
    det.appendChild(el("summary", null, "The exact change to automations.yaml"));
    det.appendChild(el("pre", null, p.diff));
    box.appendChild(det);
    const line = planReplayLine(p);
    if (line) box.appendChild(el("p", "planreplay", line));
  });
  if (plan.verify_text) box.appendChild(el("p", "planverify", plan.verify_text));
}

function planReplayLine(p) {
  const r = p.replay;
  if (p.replay_note) return p.replay_note;
  if (!r) return "";
  if (r.refused || r.error) return `brAIn could not replay it: ${r.error || "unknown"}`;
  const days = Math.round(r.days ?? 7);
  const after = r.would_run ?? 0;
  const was = p.replay_before;
  const times = (n) => `${n} ${n === 1 ? "time" : "times"}`;
  if (was && !was.refused && !was.error) {
    return `Over the last ${days} days it ran ${times(was.would_run ?? 0)} as it `
      + `is; with this change it would have run ${times(after)}.`;
  }
  return `Over the last ${days} days the changed automation would have run ${times(after)}.`;
}

// A press, never a timer: the server sets each entity back to the state the
// chokepoint recorded before brAIn's call, then reads it again and answers
// per entity. Refusals (protected, less secure, a reading) come back as
// lines too, so the toast is the summary and the card carries the detail.
function addRestoreButton(f, add, btns) {
  const b = add(el("button", "btn small ghost", "⟲  Put them back"));
  tip(b, "Set what brAIn's service calls changed back to how brAIn recorded "
    + "it before. Each entity answers for itself; you press this, brAIn "
    + "never does it on its own.");
  b.addEventListener("click", async () => {
    btns.forEach((x) => { x.disabled = true; });
    try {
      const data = await api(`api/finding/${f.ts}/restore`, { method: "POST" });
      takeFindings(data);
      syncFeed();
      renderFindings();
      const back = (data.restored || []).filter((r) => r.restored).length;
      const total = (data.restored || []).length;
      toast(`Put back ${back} of ${total} — the card says which`);
    } catch (e) {
      toast("Could not put them back: " + e);
      btns.forEach((x) => { x.disabled = false; });
    }
  });
}

function actingDiagRows(d) {
  const a = (d && d.acting) || null;
  if (!a) return [];
  if (a.error) return [diagRow("Changes and the action gate", esc(a.error), true)];
  const iv = a.interventions || {};
  const g = a.gate || {};
  const t = a.tripwire || {};
  const fu = a.followup || {};
  const items = [
    `<li>${iv.rows ?? 0} change${iv.rows === 1 ? "" : "s"} brAIn made: `
      + `${iv.watching ?? 0} being watched, ${iv.held ?? 0} held, `
      + `${iv.regressed ?? 0} came back, ${iv.could_not_check ?? 0} could not be checked`
      + (iv.next_look_at ? ` — next look ${esc(timeUntil(iv.next_look_at))}` : "")
      + "</li>",
    `<li>Follow-up looks: ${fu.looks ?? 0} taken, ${fu.deferred ?? 0} held by a gate`
      + (fu.last_error ? ` — <i>${esc(fu.last_error)}</i>` : "") + "</li>",
    `<li>Action gate: ${g.asked ?? 0} asked — ${g.allow ?? 0} let through, `
      + `${g.ask ?? 0} asked you, ${g.deny ?? 0} refused (${g.fast_path ?? 0} with no `
      + `model, ${g.undecided ?? 0} undecided)</li>`,
    `<li>Tripwire: ${t.entities ? `${t.entities} guarded` : "none set up"}`
      + (t.tripped ? `, tripped ${t.tripped} time${t.tripped === 1 ? "" : "s"}` : "")
      + (t.file_error ? ` — <i>${esc(t.file_error)}</i>` : "") + "</li>",
  ];
  const hr = a.house_rules || {};
  items.push(`<li>House rules: ${hr.rules ? `${hr.compiled ?? 0} of ${hr.rules} `
    + "checked on every action" : "none written"}`
    + ((hr.not_compiled || []).length ? ` — <i>not understood: `
      + `${(hr.not_compiled || []).map(esc).join("; ")}</i>` : "")
    + (hr.error ? ` — <i>${esc(hr.error)}</i>` : "") + "</li>");
  const button = t.entities ? "" : '<button class="btn small" id="tripwireMake" '
    + 'aria-label="Run: make a tripwire entity">Run</button> '
    + '<span class="hint">Make a tripwire entity nothing should ever act on.</span>';
  return [diagRow("Changes and the action gate",
    `<ul>${items.join("")}</ul>${button}`,
    !!(iv.error || t.file_error || hr.error))];
}

// House rules, in ⚙ → Permissions. Read when that section opens; saved by
// a press, because a rule is compiled once (one Claude run) on the save.
async function loadSetHouseRules() {
  const box = $("#setHouseRules");
  if (!box || document.activeElement === box) return;
  try {
    const data = await api("api/house-rules");
    box.value = (data.rules || []).map((r) => r.text).join("\n");
    const missed = (data.rules || []).filter((r) => r.compiled === false);
    $("#setHouseRulesNote").textContent = missed.length
      ? `${missed.length} not understood: ${missed[0].error || missed[0].text}` : "";
  } catch (err) { /* the box stays as it was; saving still works */ }
}

$("#setHouseRulesSave").addEventListener("click", async () => {
  const btn = $("#setHouseRulesSave");
  const rules = $("#setHouseRules").value.split("\n").map((t) => t.trim())
    .filter(Boolean);
  btn.disabled = true;
  try {
    const data = await api("api/house-rules", {
      method: "POST", body: JSON.stringify({ rules }) });
    const missed = (data.rules || []).filter((r) => !r.compiled);
    $("#setHouseRulesNote").textContent = missed.length
      ? `${missed.length} not understood: ${missed[0].error}` : "";
    toast(missed.length
      ? `Saved — ${missed.length} not understood: ${missed[0].error}`
      : "House rules saved");
    if (advancedLoaded) loadDiagnostics();
  } catch (err) {
    toast("Could not save the rules: " + err);
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------- ⚙ → Diagnostics' readings
// What used to be spread over four other screens — how right brAIn has
// been (Findings), what it has measured (Knowledge), the overnight check
// and the access review (Upkeep), and the background runs (the Ask tab's
// chips) — read here, because they inspect brAIn rather than the house.
// Each block is its own fetch and its own sentence when that fetch fails:
// one unreadable reading must not blank the other four.

function diagEmpty(host, text) {
  host.textContent = "";
  host.appendChild(el("p", "hint tight", text));
}

// How right each producer has been, from the endings people gave. A row
// needs SET_SCORE_MIN endings before it is a track record rather than an
// anecdote. A producer that has never been right and has been wrong three
// times is offered Ignore — the mute that stops the rule, where answering
// each card one at a time only stops one wording.
const SET_SCORE_MIN = 3;

async function loadDiagAccuracy() {
  const host = $("#diagAccuracy");
  if (!host) return;
  let data;
  try {
    data = await api("api/findings");
  } catch (e) {
    diagEmpty(host, "Could not read the scorecard: " + e.message);
    return;
  }
  host.textContent = "";
  const muted = data.muted || [];
  const mutedIds = new Set(muted.map((m) => m.source));
  const rows = (data.scorecard || []).filter(
    (r) => r.total >= SET_SCORE_MIN && !mutedIds.has(r.source));
  if (!rows.length && !muted.length) {
    diagEmpty(host, "Not enough answers yet. A producer is scored once you have "
      + `answered ${SET_SCORE_MIN} of its cards.`);
    return;
  }
  rows.forEach((r) => {
    const row = el("div", "drow");
    row.appendChild(el("div", "dk", r.title || r.source || "?"));
    const v = el("div", "dv" + (!r.confirmed && r.wrong ? " dbad" : ""),
      `${r.confirmed} of ${r.total} confirmed`);
    if (r.source && !r.confirmed && r.wrong >= 3) {
      const stop = el("button", "btn tiny", "Ignore");
      stop.setAttribute("aria-label", `Ignore: stop raising ${r.title || r.source}`);
      stop.addEventListener("click", () => setMute(r.source, true, stop));
      v.appendChild(document.createTextNode(" "));
      v.appendChild(stop);
    }
    row.appendChild(v);
    host.appendChild(row);
  });
  muted.forEach((m) => {
    const row = el("div", "drow");
    row.appendChild(el("div", "dk", m.title || m.source));
    const v = el("div", "dv", "Not raised any more ");
    const again = el("button", "btn tiny", "Restore");
    again.setAttribute("aria-label", `Restore: raise ${m.title || m.source} again`);
    again.addEventListener("click", () => setMute(m.source, false, again));
    v.appendChild(again);
    row.appendChild(v);
    host.appendChild(row);
  });
}

async function setMute(source, on, btn) {
  btn.disabled = true;
  try {
    await api(on ? "api/findings/mute" : "api/findings/unmute", {
      method: "POST", body: JSON.stringify({ source }) });
    toast(on ? "Not raising these any more" : "brAIn will raise these again");
  } catch (e) {
    toast(e.message);
  }
  loadDiagAccuracy();
}

// The seven measurements brAIn builds on its own, and this morning's brief:
// House's own renderer (renderHouse), mounted here, so a row still opens its
// drill-down — the thermal one is where the outdoor reference is chosen.
async function loadDiagMeasures() {
  if (!$("#kStores")) return;
  await refreshHouse();
}

// The overnight health check and the access review: what each last found,
// and a Run that starts one now. Both runs take minutes, so the press
// starts it and this reads the outcome back while it is running.
const setUpkeep = { sre: null, access: null, poll: 0 };

function setUpkeepLine(host, text, bad) {
  host.appendChild(el("p", "upline" + (bad ? " warn" : ""), text));
}

function renderDiagUpkeep() {
  const sre = setUpkeep.sre || {};
  const host = $("#diagOvernight");
  if (host) {
    host.textContent = "";
    if (sre.fetch_error) setUpkeepLine(host, "Could not ask the add-on: " + sre.fetch_error, true);
    if (sre.running) setUpkeepLine(host, "Reading the log and the mesh…");
    if (sre.last_error) setUpkeepLine(host, "The last run did not finish: " + sre.last_error, true);
    const last = sre.last;
    if (last) {
      const when = timeAgo(new Date(last.at * 1000).toISOString());
      setUpkeepLine(host, last.note ? `Last run ${when}: ${last.note}.`
        : `Last run ${when}: ${last.records} record${last.records === 1 ? "" : "s"} read, `
          + `${last.causes} cause${last.causes === 1 ? "" : "s"} found, `
          + `${last.filed} new, ${last.cleared} cleared.`);
    } else if (!sre.running && !sre.fetch_error) {
      setUpkeepLine(host, "It runs once a night, after 03:00, and costs nothing on a quiet night.");
    }
    $("#diagOvernightRun").disabled = !!sre.running;
  }
  const access = setUpkeep.access || {};
  const box = $("#diagAccess");
  if (box) {
    box.textContent = "";
    if (access.fetch_error) setUpkeepLine(box, "Could not ask the add-on: " + access.fetch_error, true);
    if (access.running) setUpkeepLine(box, "Reviewing…");
    if (access.last_error) setUpkeepLine(box, "The last review did not finish: " + access.last_error, true);
    if (access.sentence) {
      box.appendChild(el("p", "upsentence", access.sentence));
      if (access.at) {
        setUpkeepLine(box, "Reviewed " + timeAgo(new Date(access.at * 1000).toISOString()));
      }
    } else if (!access.running && !access.fetch_error) {
      setUpkeepLine(box, "A sentence once a week about users, what voice can reach and "
        + "add-on privileges.");
    }
    if (access.open) {
      setUpkeepLine(box, `${access.open} security finding${access.open === 1 ? "" : "s"} `
        + "waiting on you.");
    }
    $("#diagAccessRun").disabled = !!access.running;
  }
}

async function loadDiagUpkeep() {
  const get = (path) => api(path).catch((e) => ({ fetch_error: e.message }));
  const [sre, access] = await Promise.all([get("api/sre"), get("api/access")]);
  setUpkeep.sre = sre;
  setUpkeep.access = access;
  renderDiagUpkeep();
  clearTimeout(setUpkeep.poll);
  if ((sre && sre.running) || (access && access.running)) {
    setUpkeep.poll = setTimeout(() => {
      if ($("#setModal").classList.contains("open")) loadDiagUpkeep();
    }, 3000);
  }
}

async function runDiagUpkeep(btn, path, said) {
  btn.disabled = true;
  try {
    await api(path, { method: "POST" });
    toast(said);
  } catch (e) {
    toast(e.message || "that didn't work");
  }
  loadDiagUpkeep();
}

$("#diagOvernightRun").addEventListener("click", () => runDiagUpkeep(
  $("#diagOvernightRun"), "api/sre/run", "Checking — anything it finds arrives as a card"));
$("#diagAccessRun").addEventListener("click", () => runDiagUpkeep(
  $("#diagAccessRun"), "api/access/run", "Reviewing…"));

// --------------------------------------------------------- ⚙ → Memory
// The memory document and the queue waiting to be filed into it. The queue
// files itself once a day (sooner when it grows), so there is no button
// to force a pass here — only a read-only list and its count, read in one
// call so the two cannot disagree. The document is edited in place: Edit
// opens it as text and Save writes it back, and a pass that lands while
// you are editing never overwrites the box.
const setMem = { text: "", editing: false, dirty: false };

async function loadSetMemory() {
  let data;
  try {
    data = await api("api/knowledge");
  } catch (e) {
    $("#setMemView").textContent = "Could not read memory: " + e.message;
    return;
  }
  const items = data.inbox || [];
  const pending = Number(data.inbox_pending);
  const count = Number.isFinite(pending) ? pending : items.length;
  $("#setMemCount").textContent = String(count);
  const queue = $("#setMemQueue");
  queue.textContent = "";
  if (!items.length) {
    queue.appendChild(el("p", "hint tight", "Nothing waiting."));
  }
  items.slice().reverse().forEach((f) => {
    const row = el("div", "setmemitem");
    row.appendChild(el("span", "setmemtext", f.text || ""));
    if (f.source) row.appendChild(el("span", "hint", ` ${f.source}`));
    queue.appendChild(row);
  });
  const hidden = Math.max(0, count - items.length);
  if (hidden) queue.appendChild(el("p", "hint tight", `…and ${hidden} more waiting.`));
  if (setMem.editing) return;
  setMem.text = data.shared_memory || "";
  const view = $("#setMemView");
  if (setMem.text.trim()) {
    view.innerHTML = mdToHtml(setMem.text);
  } else {
    view.textContent = "Nothing learned yet. Edit starts the document.";
  }
}

function setMemEditing(on) {
  setMem.editing = on;
  setMem.dirty = false;
  $("#setMemTa").classList.toggle("hidden", !on);
  $("#setMemView").classList.toggle("hidden", on);
  $("#setMemEdit").classList.toggle("hidden", on);
  $("#setMemSave").classList.toggle("hidden", !on);
  $("#setMemCancel").classList.toggle("hidden", !on);
}

$("#setMemEdit").addEventListener("click", () => {
  $("#setMemTa").value = setMem.text.trim() ? setMem.text
    : (typeof MEM_TEMPLATE === "string" ? MEM_TEMPLATE : "# Home Memory\n");
  setMemEditing(true);
  $("#setMemTa").focus();
});
$("#setMemTa").addEventListener("input", () => { setMem.dirty = true; });
$("#setMemCancel").addEventListener("click", () => {
  if (setMem.dirty && !window.confirm("Discard your unsaved memory edits?")) return;
  setMemEditing(false);
  loadSetMemory();
});
$("#setMemSave").addEventListener("click", async () => {
  const text = $("#setMemTa").value;
  const btn = $("#setMemSave");
  btn.disabled = true;
  try {
    await api("api/memory", { method: "PUT", body: JSON.stringify({ text }) });
    setMem.text = text;
    setMemEditing(false);
    toast("Memory saved");
    loadSetMemory();
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
});

// ------------------------------------------------- ⚙ → Sources: calendars
// Which calendars brAIn may read for what is coming up. Off until somebody
// ticks one: a calendar is the most personal thing a house holds. Its
// safety note is on the page beside the list, never behind anything.
const setCalendarsState = { data: null, saving: false };

async function loadSetCalendars() {
  const host = $("#setCalendars");
  if (!host) return;
  if (setCalendarsState.data) { renderSetCalendars(); return; }
  try {
    setCalendarsState.data = await api("api/occasions");
  } catch (e) {
    host.textContent = "Could not read the calendars: " + e.message;
    return;
  }
  renderSetCalendars();
}

function renderSetCalendars() {
  const host = $("#setCalendars");
  const data = setCalendarsState.data || {};
  const available = data.available || [];
  const chosen = new Set(data.calendars || []);
  host.textContent = "";
  if (!available.length) {
    host.appendChild(el("p", "hint tight", "No calendars found in Home Assistant."));
    return;
  }
  available.forEach((cal) => {
    const label = el("label", "setcam");
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.className = "tog";
    tick.checked = chosen.has(cal.entity_id);
    tick.dataset.cal = cal.entity_id;
    tick.addEventListener("change", saveSetCalendars);
    label.appendChild(tick);
    label.appendChild(el("span", null, cal.name || cal.entity_id));
    host.appendChild(label);
  });
}

async function saveSetCalendars() {
  if (setCalendarsState.saving) return;
  setCalendarsState.saving = true;
  const picked = [...document.querySelectorAll("#setCalendars input[data-cal]")]
    .filter((t) => t.checked).map((t) => t.dataset.cal);
  try {
    await api("api/settings", { method: "PUT",
      body: JSON.stringify({ occasion_calendars: picked }) });
    if (setCalendarsState.data) setCalendarsState.data.calendars = picked;
    toast(picked.length ? "brAIn will read those calendars tonight."
      : "brAIn will not read any calendar.");
  } catch (err) {
    toast("Could not save: " + err.message);
  } finally {
    setCalendarsState.saving = false;
  }
}

// ---------------------------------------------------------- ⚙ → Guide
// The docs, by group. Help left the tab bar (it is not a daily job), so
// this is the way in: each group opens the docs pane at its first page.
function renderSetGuide() {
  const nav = $("#setGuide");
  if (!nav || nav.childElementCount) return;
  docGroups().forEach((g) => {
    const link = el("a", "setguidelink", g.name);
    link.href = "#";
    link.appendChild(el("span", "setguidesub", g.sections.map((x) => x.title)
      .slice(0, 3).join(" · ") + (g.sections.length > 3 ? " …" : "")));
    link.addEventListener("click", (ev) => {
      ev.preventDefault();
      openGuide(g.sections[0].id);
    });
    nav.appendChild(link);
  });
}

function openGuide(sectionId) {
  closeBox("#setModal");
  switchView("docs");
  if (sectionId) selectDocs(sectionId);
  window.scrollTo(0, 0);
}

// Delegated, because the diagnostics body is rebuilt on every open.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest && e.target.closest("#tripwireMake");
  if (!btn) return;
  btn.disabled = true;
  try {
    const r = await api("api/security/honeytoken", { method: "POST" });
    toast(r.created ? "Tripwire made — nothing should ever act on it"
                    : "The tripwire is already there");
    loadDiagnostics();
  } catch (err) {
    toast("Could not make the tripwire: " + err);
    btn.disabled = false;
  }
});


// ---------------------------------------------- ideas: the reason a no
//
// "Not for this house" took nothing but the title, so the next pass was
// told only that ONE wording had been turned down and could offer the
// same kind of card under another — "we don't care about standby power"
// is a sentence that rules out a family of ideas, and nothing on the page
// could carry it. The route always took a reason (`ideas.dismiss`); this
// is the box. It opens IN PLACE of the buttons, inside the card, for the
// reason every other reason box in the panel does — you are explaining
// this card and it has to stay on screen while you write — and it is never
// required: an empty box is a plain dismissal, because a mandatory field
// fills with "no".
function ideaReasonBox(idea, card, actions) {
  if (card.querySelector(".propnote")) return;
  actions.classList.add("hidden");
  const box = el("div", "propnote ideanote");
  const area = el("textarea");
  area.placeholder = "Why not? (optional — it rules out cards like this one, "
    + "not just this title)";
  area.rows = 2;
  area.maxLength = 200;
  box.appendChild(area);
  const row = el("div", "propbtns");
  const send = el("button", "btn small", "Ignore");
  const back = el("button", "btn small ghost", "Back");
  send.addEventListener("click", async () => {
    send.disabled = true;
    back.disabled = true;
    const reason = area.value.trim();
    try {
      takeIdeas(await api(`api/idea/${idea.id}/dismiss`, {
        method: "POST", body: JSON.stringify({ reason }) }));
      renderIdeas();
      toast(reason ? "Won't suggest that, or anything like it"
        : "Won't suggest that again");
    } catch (err) {
      send.disabled = false;
      back.disabled = false;
      toast(err.message || "that didn't work");
    }
  });
  back.addEventListener("click", () => {
    box.remove();
    actions.classList.remove("hidden");
  });
  row.append(send, back);
  box.appendChild(row);
  card.appendChild(box);
  area.focus();
}


// ---------------------------------------------------------------------------
// The deep review (House → Knowledge). The one run on the top tier, and only
// by a press: the button says what it will roughly cost before it is
// pressed (an estimate read off the reviews this house has already paid
// for, and a first guess before there are any), and what the review said
// stays here to be read. It files nothing on any other tab.
// ---------------------------------------------------------------------------
const reviewState = { data: null, error: "", timer: null, pressing: false };

async function refreshDeepReview() {
  try {
    reviewState.data = await api("api/deep-review");
    reviewState.error = "";
  } catch (e) {
    reviewState.error = "Could not read the deep review: " + e.message;
  }
  renderDeepReview();
  // While one is running the tab watches for it landing — and only while
  // the tab is the one on screen: a poll behind a pane nobody is looking at
  // is a request per minute for an answer nobody will read.
  clearTimeout(reviewState.timer);
  if (reviewState.data && reviewState.data.running && currentView === "insights") {
    reviewState.timer = setTimeout(refreshDeepReview, 8000);
  }
}

function reviewCostText(est) {
  // The price, in the one unit a person can weigh: a share of the session
  // window it spends. Tokens, the model and how the estimate was made are
  // in the button's tooltip, for whoever wants them.
  if (!est || !Number(est.tokens)) return "";
  if (est.percent !== null && est.percent !== undefined) {
    return `~${est.percent}% of a session`;
  }
  return `~${Math.max(1, Math.round(Number(est.tokens) / 1000))}k tokens`;
}

function reviewDate(epoch) {
  const n = Number(epoch) || 0;
  if (!n) return "";
  return new Date(n * 1000).toLocaleDateString([], { day: "numeric", month: "short" });
}

const REVIEW_KIND_WORD = {
  problem: "Problem", opportunity: "Could be better",
  question: "Worth asking", working: "Working well",
};

function renderDeepReview() {
  const box = $("#kReview");
  if (!box) return;
  box.textContent = "";
  if (reviewState.error) {
    box.appendChild(el("p", "kbrieftext off", reviewState.error));
    return;
  }
  const d = reviewState.data;
  if (!d) return;

  const run = el("div", "kreviewrun");
  const btn = el("button", "btn small", d.running ? "Running…" : "Run");
  btn.type = "button";
  btn.disabled = Boolean(d.running) || reviewState.pressing || !d.authenticated;
  const est = d.estimate || {};
  tip(btn, "Claude's top model reads the whole house with read-only tools and "
    + "says what it adds up to. It changes nothing and files nothing."
    + (Number(est.tokens) ? ` About ${Math.round(Number(est.tokens) / 1000)}k `
      + `tokens — an estimate: ${est.basis}.` : ""));
  btn.addEventListener("click", () => runDeepReview(btn));
  run.appendChild(btn);
  run.appendChild(el("span", "kreviewcost", d.running
    ? `Started ${agoAt(d.started_at)}`
    : reviewCostText(d.estimate)));
  box.appendChild(run);

  if (!d.authenticated) {
    box.appendChild(el("p", "kbrieftext off",
      "Connect your Claude account first — ⚙ › Account."));
  }
  if (d.last_error) {
    box.appendChild(el("p", "kbrieftext off",
      `The last review did not finish: ${d.last_error}`));
  }
  if (d.error) box.appendChild(el("p", "kbrieftext off", d.error));

  const r = d.latest;
  if (!r) return;
  box.appendChild(el("div", "kbriefwhen", reviewDate(r.at)));
  if (r.summary) box.appendChild(el("p", "kbrieftext", r.summary));
  if (r.one_thing) {
    const one = el("div", "kreviewone");
    one.appendChild(el("div", "kreviewlabel", "The one thing this month"));
    one.appendChild(el("p", "kbrieftext", r.one_thing));
    box.appendChild(one);
  }
  const obs = Array.isArray(r.observations) ? r.observations : [];
  if (obs.length) {
    const list = el("ul", "kreviewobs");
    obs.forEach((o) => {
      const li = el("li", "kreviewob");
      li.appendChild(el("div", "kreviewlabel",
        REVIEW_KIND_WORD[o.kind] || "Problem"));
      li.appendChild(el("div", "kreviewtitle", prettyText(String(o.title || ""))));
      if (o.detail) li.appendChild(el("p", "kreviewdetail", prettyText(String(o.detail))));
      list.appendChild(li);
    });
    box.appendChild(list);
  }
  const older = Array.isArray(d.history) ? d.history : [];
  if (older.length) {
    box.appendChild(el("p", "kreviewcost",
      "Earlier: " + older.map((h) => reviewDate(h.at)).filter(Boolean).join(", ")));
  }
}

async function runDeepReview(btn) {
  reviewState.pressing = true;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("api/deep-review/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    let body = {};
    try { body = await resp.json(); } catch (e) { body = {}; }
    if (!resp.ok) {
      toast(body.error || `Could not start a review (HTTP ${resp.status})`);
    } else {
      reviewState.data = body;
      toast("Reviewing the house — it lands under Insights in a few minutes");
    }
  } catch (e) {
    toast(e.message);
  } finally {
    reviewState.pressing = false;
    refreshDeepReview();
  }
}


// ---------------------------------------------------------------------------
// ⚙ → Cameras. One tick per camera brAIn may look at
// on its own; empty until somebody ticks one. Read when the section opens,
// never on the way into the dialog, and saved through the ordinary
// settings PUT, so there is one route that changes a setting.
// ---------------------------------------------------------------------------
let camerasLoaded = false;

async function loadCameras() {
  if (camerasLoaded) return;
  camerasLoaded = true;
  const box = $("#setCameras");
  if (!box) return;
  try {
    renderCameras(await api("api/cameras"));
  } catch (e) {
    camerasLoaded = false;
    box.textContent = "Could not read your cameras: " + e.message;
  }
}

function renderCameras(data) {
  const box = $("#setCameras");
  if (!box) return;
  box.textContent = "";
  const all = Array.isArray(data.cameras) ? data.cameras : [];
  // A robot vacuum publishes its floor map as a camera entity, and a house
  // with a few of them had nine "cameras" here that show no room at all.
  // Left out unless one is already ticked, because a tick nobody can see is
  // a tick nobody can take back.
  const cams = all.filter((c) => c.allowed || !isMapCamera(c));
  const maps = all.length - cams.length;
  if (!cams.length && !maps) {
    box.appendChild(el("p", "hint tight", data.registry_read
      ? "This house has no cameras brAIn can see."
      : "brAIn has not read your devices yet — this list fills in after the first house check."));
    return;
  }
  cams.forEach((cam) => {
    const label = el("label", "check setcam");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(cam.allowed);
    input.dataset.entity = cam.entity_id;
    input.addEventListener("change", saveCameras);
    label.appendChild(input);
    const words = el("span", null, cam.name || cam.entity_id);
    if (cam.name && cam.name !== cam.entity_id) {
      words.appendChild(el("span", "subtext", ` ${cam.entity_id}`));
    }
    label.appendChild(words);
    box.appendChild(label);
  });
  if (maps) {
    box.appendChild(el("p", "hint tight", maps === 1
      ? "1 vacuum map is left out — it is published as a camera but shows no room."
      : `${maps} vacuum maps are left out — they are published as cameras but show no room.`));
  }
  const used = Number(data.used_today) || 0;
  const cap = Number(data.per_day) || 0;
  box.appendChild(el("p", "hint tight", data.error
    ? `brAIn will not look at any camera until it can count again: ${data.error}`
    : `Looked ${used} of ${cap} times today.`));
}

// A map, not a view: the object id says so (`camera.roborock_s7_map`,
// `camera.downstairs_map_2`), which is how vacuum integrations name them.
function isMapCamera(cam) {
  const object = String(cam.entity_id || "").split(".").pop();
  return /(^|_)map(_|$)/.test(object);
}

async function saveCameras() {
  const picked = [...document.querySelectorAll("#setCameras input[data-entity]")]
    .filter((i) => i.checked).map((i) => i.dataset.entity);
  await saveSettings({ camera_confirm: picked },
    picked.length ? `brAIn may look at ${picked.length} camera${picked.length > 1 ? "s" : ""}`
      : "brAIn will not look at any camera on its own");
}
