// <morph-panel> — Morph in Home Assistant's sidebar.
//
// Morph is the house's face; brAIn is its mind (docs/design/morph-vision.md,
// the design this page is built against). The page is laid out by the
// house's own sense of normal and can always say why: salience.js ranks
// every card and room from brAIn's measurements (`feed.json`), brAIn's
// cases and the entities' own state, and that ONE list is drawn five ways —
// the verdict (the story's first clause, in its meaning colour), the Now
// layer (at most three cards lifted out of their rooms, MOVED not copied),
// the order and fold of the rooms, the room line, and the floors' summaries.
//
// A custom panel, not an iframe: it is handed the live `hass` object, so
// every card reacts to the house as it changes and any Lovelace card can be
// hosted untouched. One grammar (tap · slide · hold), nothing floats, no
// chrome, and the page rearranges only at a quiet moment (§4.4): never
// under a finger, during a scroll, while a card is open, or within 8 s of
// the last rearrangement, except for a safety trip.
//
// Data: `morph/load` returns the dashboard mirror, Morph's own state
// (settings, the Tell activity) and brAIn's published files (its cases, its
// measurements, the situation sentence). `morph/subscribe` says which of
// those moved. Writes are `morph/request`, which Morph's service turns into a
// git commit — so every change to the dashboard has an Undo — and answers
// to cases are brAIn's own request queue, written by `morph/case`.
//
// Ask is brAIn's chat with a dashboard in front of it: `morph/ask` hands the
// words to brAIn's interpreter on the `morph` surface, which either does
// the thing (a rule, a fact), says it is a conversation (a task that may
// continue), or says it is a change to the dashboard or to Morph itself (a
// Tell, the fast path with one commit and Undo). A Tell starts with a
// PICTURE of what it is about (snap.js), so "this" means what is on screen.

import { Engine } from './engine.js';
import { CSS as STYLES, FONTS_URL } from './styles.js';
import { floorFields } from './floor.js';
import { TYPES, typeOf, hueColor, listWord, climatePending, tileAria, sceneWords, stateWord, fanHasSpeed } from './cards.js';
import * as history from './history.js';
import * as snap from './snap.js';
import * as upc from './upcoming.js';
import * as sal from './salience.js';
import { morph } from './morph-dom.js';
import { caseFace, caseColor, placeCase } from './cases.js';
import { icon as mIcon, speakHtml, esc, mix, hue, HUES, clock, ago, friendly, shortName, lightColor, SPARK, MARK, domainOf, UNAVAILABLE, fmt, climateDoing, importWithRetry, cardPage, guardDefine, loadCard, cardUrl, cardFailure, isDashChange, ASK_CONTEXT, own, checkDoorClaims, unlockedLocks } from './util.js';
import { Scrub, SCRUB_CSS } from './scrub.js';
import { haptic } from './haptics.js';
import { attachPull, PULL_CSS } from './pull.js';
import { POLISH_CSS, markSvg, rollDigits, touchLight, pulseTile, stateColor } from './polish.js';

// A room's scene as a word: its name without the room in front ("Den - Bright",
// "Laundry Room – Bright" → "Bright") (house change).
const sceneWord = (H, e) => {
  const st = H.states[e]; const n = String((st && st.attributes.friendly_name) || e.split('.').pop().replace(/_/g, ' '));
  const r = n.replace(/^.*?\s[-–—]\s+/, '').trim(); return r ? r[0].toUpperCase() + r.slice(1) : n;
};
// The scene applied last (a scene's state is when it was applied), within 12 h.
const currentScene = (H, ids) => {
  let cur = null, bt = 0;
  ids.forEach((e) => { const t = H.states[e] ? Date.parse(H.states[e].state) : 0; if (t > bt) { bt = t; cur = e; } });
  return Date.now() - bt > 12 * 3600000 ? null : cur;
};
// brAIn's severities as colours, and a finding's first sentence.
const sevCol = (s, info = 'var(--quiet)') => (s === 'critical' || s === 'serious' ? 'var(--rose)' : s === 'warning' ? 'var(--amber)' : info);
const firstSentence = (t) => { const m = String(t || '').replace(/…$/, '').match(/^.*?[.!?](\s|$)/); return m ? m[0].trim() : String(t || '').trim(); };
// One of brAIn's steps while it works.
const stepLine = (x, cls = '') => `<div class="step${cls}"><i style="background:${x.tone === 'bad' ? 'var(--rose)' : x.tone === 'good' ? 'var(--teal)' : 'var(--violet)'}"></i><span>${esc(x.t)}</span></div>`;

const HOLD_MS = 540;
// The card types whose entities are `entity`/`entities`; a hosted Lovelace
// card, and any type a copy of cards.js adds, are read through their config.
const BUILT_IN = new Set(['light', 'light_group', 'fan', 'cover', 'lock', 'switch', 'button', 'vacuum', 'climate', 'sensor', 'readings', 'meter', 'media', 'camera', 'list', 'person', 'weather', 'alarm', 'scenes', 'entity', 'note']);
const EID_SHAPE = /^[a-z_]+\.[a-z0-9_]+$/;
// Every string in a card's config that names an entity Home Assistant has.
function entityIdsIn(v, states, out, depth) {
  if (depth > 6 || v == null) return;
  if (typeof v === 'string') { if (EID_SHAPE.test(v) && states[v] && !out.includes(v)) out.push(v); return; }
  if (Array.isArray(v)) { v.forEach((x) => entityIdsIn(x, states, out, depth + 1)); return; }
  if (typeof v === 'object') Object.keys(v).forEach((k) => { if (k !== 'id') entityIdsIn(v[k], states, out, depth + 1); });
}
// How many asked questions Ask keeps on screen, answered or not.
const ASK_KEEP = 5;
const TELL_SUGS = {
  card: ['Make this wider', 'Move it to the top of the room', 'Show its history by default'],
  section: ['Put the scenes first', 'Split this into two groups', 'Add the room’s temperature here'],
  floor: ['Show this floor first in the evening', 'Rename this floor', 'Add a section for the hallway'],
  story: ['Mention the weather first', 'Leave out the people', 'Tell me when the laundry is done'],
  upcoming: ['Add bin day', 'Show sunrise and sunset', 'Show the next calendar event'],
  scenes: ['Add a Movie scene', 'Put Bedtime first', 'Make a scene for dinner'],
  dashboard: ['Add a Pets section', 'Make a section for the garden', 'Tidy the Whole house floor'],
};
// Domains the story and Coming up read across the whole house, on the
// dashboard or not: a change in one of them redraws the page.
const LIVE_DOMAINS = new Set(['person', 'climate', 'vacuum', 'media_player', 'timer', 'sun', 'calendar', 'input_datetime', 'automation', 'alarm_control_panel']);
const KIND_WORD = { card: 'card', section: 'section', floor: 'floor', story: 'story', upcoming: 'Coming up', scenes: 'scenes', dashboard: 'dashboard' };
// Domains whose change is a salient event: the list is recomputed at once.
const SALIENT = ['lock', 'binary_sensor', 'alarm_control_panel', 'person', 'cover', 'vacuum', 'timer'];
// What a house has to be laid out from before a card is lifted: brAIn.
const NEEDS_BRAIN = 'brAIn is not running, and the dashboard is drawn from what it knows. Start brAIn.';
const agoWords = (ms) => { const m = Math.max(0, Math.round(ms / 60000)); return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };
// Uses waiting to be sent when the connection is down; past this the oldest go.
const USAGE_KEEP = 400;

// Why a change to Morph's own code is paused (the service's morphcode.py):
// its own file changed in the update, or another of Morph's modules it
// builds on did.
function pausedWhy(r) {
  // An older change that read the household's personality from a file of its
  // own (morphcode.RETIRED): the personality is brAIn's now.
  if (r && r.why === 'personality') return r.kind === 'new' ? 'Morph no longer reads this old personality file; the personality is brAIn’s now.' : 'It reads the old personality file, which Morph no longer uses, so Morph’s own is running.';
  if (r && r.why === 'others' && (r.moved || []).length) return `Morph was updated and its ${r.moved.slice(0, 3).join(', ')}${r.moved.length > 3 ? ' and more' : ''} changed, which this change builds on. Morph’s own ${r.name} is running until brAIn checks the change still fits.`;
  return 'Morph’s own version is running until you update your change.';
}

// Home Assistant defines window.loadCardHelpers only once its Lovelace chunk
// has loaded, and a panel opened directly may get here first. Wait briefly,
// then load that chunk the way Home Assistant's own panels do; null when
// neither works (the caller then tries a custom card without the helpers).
async function cardHelpers() {
  if (typeof window.loadCardHelpers === 'function') return window.loadCardHelpers();
  const until = Date.now() + 1000;
  while (Date.now() < until && typeof window.loadCardHelpers !== 'function') await new Promise((r) => setTimeout(r, 100));
  if (typeof window.loadCardHelpers !== 'function') {
    try {
      await Promise.race([customElements.whenDefined('partial-panel-resolver'), new Promise((_, no) => setTimeout(no, 1500))]);
      const ppr = document.createElement('partial-panel-resolver');
      ppr.hass = { panels: [{ url_path: 'tmp', component_name: 'lovelace' }] };
      ppr._updateRoutes();
      await ppr.routerOptions.routes.tmp.load();
      await Promise.race([customElements.whenDefined('hui-view'), new Promise((_, no) => setTimeout(no, 1500))]);
    } catch (e) { /* fall through */ }
  }
  try { if (typeof window.loadCardHelpers === 'function') return await window.loadCardHelpers(); } catch (e) { /* fall through */ }
  return null;
}

// A card's own shadow root is out of reach of Morph's styles: floor.js hands
// it the 16px field floor (floorFields).

// A house's own custom card needs nothing from Lovelace: its element is
// defined, so make it and hand it the config.
function customCardWithoutHelpers(config) {
  const tag = String((config && config.type) || '');
  if (!tag.startsWith('custom:') || !customElements.get(tag.slice(7))) throw new Error('Lovelace card helpers are not available and the card is not a defined custom element');
  const el = document.createElement(tag.slice(7));
  if (typeof el.setConfig !== 'function') throw new Error(`${tag} has no setConfig`);
  el.setConfig(config);
  return el;
}

// A switch that rides in its room's title row as a pill (`options.header:
// true`, the owner: a pause toggle "in the header of the card as a
// button"): outside Edit it is not a tile, not lifted into Now and not what
// keeps a room open; in Edit it is an ordinary tile, so it can be edited.
function isHeadCard(card) {
  return !!(card && card.type === 'switch' && card.entity && card.options && card.options.header === true);
}

class MorphPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.s = {
      edit: false, view: null, fading: null, previews: {}, memberPreview: null,
      tell: null, secEdit: null, asks: [], story: {}, confirm: {}, hold: null, add: null,
      sugNo: null, toast: null, yaml: null, hist: null,
      pending: {}, replyOpen: {}, converse: null,
    };
    // The Tell box shows one tell. A tell it stops showing while brAIn is
    // still at it (another Tell opened, the box closed) keeps running in
    // the service by its id, and the activity strip lists it while it runs;
    // the strip used to forget it the moment it finished, so its answer and
    // its Undo were nowhere on the page. Every replacement goes through
    // here, and parkTell keeps such a tell until its result is seen.
    let tellNow = null;
    this.tellsAway = [];
    Object.defineProperty(this.s, 'tell', { enumerable: true, get: () => tellNow, set: (t) => { if (tellNow && tellNow !== t) this.parkTell(tellNow, t); tellNow = t; } });
    // How the person is touching the page, for the quiet-moment gate.
    this.ui = { lastTouch: 0, pointerDown: false, lastScroll: 0, lastArrange: 0, open: false };
    this.touched = {};
    this.asked = {};
    this.salState = null;
    this.salApplied = null;
    this._salDirty = true;
    this._watchSig = '';
    try { this.suppressed = JSON.parse(localStorage.getItem('morph.notthis') || '{}') || {}; } catch (e) { this.suppressed = {}; }
    // House change, Oct 2026: the page is the same on every device for
    // everybody. No per-device mode, no owner, no habits, no usage anchors.
    try { ['morph.used', 'morph.device', 'morph.person'].forEach((k) => localStorage.removeItem(k)); } catch (e) { /* storage refused: nothing kept anyway */ }
    this.data = null;
    this.dash = null;
    // "Not now" on paused changes, keyed on which files are paused: a later
    // update that pauses something else asks again.
    try { this.notNow = localStorage.getItem('morph.notnow') || ''; } catch (e) { this.notNow = ''; }
    this.llCards = new Map();
    this.loadedModules = new Set();
    this.usage = [];
    this.reported = new Set();
    this.cache = new Map();
    this.tellStatus = {};
    this._raf = 0;
    // A page whose Home Assistant still runs an older Morph integration
    // creates <morph-panel> before this file has defined it, and sets its
    // properties on the bare element. Those would hide the setters below
    // for good, so they are taken back through them.
    for (const k of ['panel', 'narrow', 'route', 'hass']) {
      if (Object.prototype.hasOwnProperty.call(this, k)) { const v = this[k]; delete this[k]; this[k] = v; }
    }
  }

  // ------------------------------------------------------------ lifecycle

  set hass(h) {
    const first = !this._hass;
    const prev = this._hass;
    this._hass = h;
    if (!first && prev && this.engine && !this.s.edit) { try { this.glowChanges(prev, h); } catch (e) { /* no glow */ } }
    if (first) this.boot();
    else if (this.hassMatters(prev, h)) this.schedule();
    this.llCards.forEach((el) => { try { el.hass = h; } catch (e) { /* a card that throws on hass is reported when it draws */ } });
  }

  // Something on the page changed that this page did not do: its tile glows
  // once in the new state's colour (house change, Oct 2026).
  glowChanges(prev, h) {
    if (Date.now() - (this._bootAt || 0) < 8000 || (this._quietUntil && Date.now() < this._quietUntil) || this.engine.reduce()) return;
    if (!this._entTiles || this._entTilesAt !== this._modelStamp) {
      const m = new Map();
      this.$$tiles().forEach((t) => { const id = t.getAttribute('data-tile'); const hit = this.findCard(id); if (!hit) return; const es = [hit.card.entity].concat(hit.card.entities || []).filter(Boolean); es.forEach((e) => { if (!m.has(e)) m.set(e, []); m.get(e).push(t); }); });
      this._entTiles = m; this._entTilesAt = this._modelStamp;
    }
    const vh = window.innerHeight || 900;
    this._entTiles.forEach((tiles, e) => {
      const a = prev.states[e]; const b = h.states[e];
      if (!a || !b || a === b || a.state === b.state) return;
      const mine = this._mine && this._mine.get(e); if (mine && Date.now() - mine < 8000) return;
      tiles.forEach((t) => { if (!t.isConnected) return; const r = t.getBoundingClientRect(); if (r.bottom < 0 || r.top > vh) return; pulseTile(t, stateColor(e, b)); });
    });
  }

  $$tiles() { return [...this.shadowRoot.querySelectorAll('[data-board] [data-tile]')]; }

  // Home Assistant sets hass on every state change in the house, many times a
  // second here. The page is drawn again only when something it shows changed:
  // an entity on the dashboard (or named anywhere in it), one the verdict or
  // Coming up reads, or Home Assistant's own settings. State objects are
  // replaced when they change, so comparing references is exact. The 10 s
  // tick still redraws whatever the clock moves. A salient entity on the
  // page that changed has the salience list recomputed at once.
  hassMatters(a, b) {
    if (!a || !this.dash || a.themes !== b.themes || a.user !== b.user || a.config !== b.config || a.entities !== b.entities || a.language !== b.language) return true;
    if (a.states === b.states) return false;
    this.watchIds();
    const W = this._watchSet;
    let hit = false;
    for (const id in b.states) {
      const st = b.states[id];
      if (a.states[id] === st) continue;
      const mine = W.has(id);
      if (mine && SALIENT.includes(domainOf(id))) { this._salDirty = true; return true; }
      if (mine || LIVE_DOMAINS.has(domainOf(id)) || (st.attributes && st.attributes.device_class === 'timestamp') || /moon_next_|_next_pickup$|_at_street$/.test(id)) hit = true;
    }
    return hit;
  }

  // Every entity the page shows: the sections' (and their groups'
  // members), the top scenes, and any entity the dashboard names anywhere
  // (a group's `when`, a card's options).
  watchIds() {
    if (this._watch && this._watchRev === this.revision && this._watchDash === this.dash) return this._watch;
    const W = new Set();
    this.eachSection((sec) => this.sectionEntities(sec).forEach((e) => W.add(e)));
    ((this.dash && this.dash.scenes) || []).forEach((e) => W.add(e));
    const H = this._hass;
    (JSON.stringify(this.dash || {}).match(/\b[a-z_]+\.[a-z0-9_]+\b/g) || []).forEach((e) => { if (H && H.states[e]) W.add(e); });
    this._watchSet = W; this._watch = [...W]; this._watchRev = this.revision; this._watchDash = this.dash;
    return this._watch;
  }
  get hass() { return this._hass; }
  set narrow(v) { this._narrow = v; this.schedule(); }
  // Set by brAIn's shell: true while brAIn's header is above the page.
  set shell(v) { this._shell = !!v; this.schedule(); }
  get shell() { return !!this._shell; }
  set panel(p) { this._panel = p; }
  set route(r) { this._route = r; }

  connectedCallback() {
    if (this._hass && !this.engine) this.boot();
    // Home Assistant takes a panel out of the page while it is hidden (five
    // minutes in the background, another panel in front) and puts the SAME
    // element back: boot() does not run again, so whatever
    // disconnectedCallback stopped has to be started here or it stays
    // stopped — which is how the usage log went quiet for good after the
    // first time somebody switched apps.
    else if (this._hass && this.engine) { this.attachWindow(); this.startLive(); this.load(); }
  }

  disconnectedCallback() {
    this.flushUsage();
    this.stopLive();
    this.detachWindow();
  }

  // What this panel listens to outside itself. Taken off while Home Assistant
  // has the panel out of the page, so a detached panel never renders, and
  // put back when the same element returns.
  attachWindow() {
    if (this._winOn || !this._tellKey) return;
    this._winOn = true;
    window.addEventListener('keydown', this._tellKey);
  }

  detachWindow() {
    if (!this._winOn) return;
    this._winOn = false;
    window.removeEventListener('keydown', this._tellKey);
    cancelAnimationFrame(this._raf); this._raf = 0;
  }

  // The T key is this device's to switch off (Settings › Gestures).
  tellKeyOn() { try { return localStorage.getItem('morph.tellkey') !== '0'; } catch (e) { return true; } }

  get live() { return this.isConnected !== false; }

  // The live half: the subscription, the ticks, and flushing the usage log
  // when the page is hidden (the websocket is still open then; by the time
  // Home Assistant takes the panel out it has suspended the connection).
  startLive() {
    if (this._live || !this._hass) return;
    this._live = true;
    this._unsub = this.hass.connection.subscribeMessage(() => this.load(), { type: 'morph/subscribe' }).catch(() => null);
    this._tick = setInterval(() => { this.schedule(); this.flushUsage(); this.pollTell(); }, 10000);
    this._since = setInterval(() => this.tickSince(), 1000);
    this._onHide = (e) => { if (e.type === 'pagehide' || document.visibilityState === 'hidden') this.flushUsage(); };
    document.addEventListener('visibilitychange', this._onHide);
    window.addEventListener('pagehide', this._onHide);
    // Listeners on the window are this page's only while it is on the
    // page: a panel taken out by Home Assistant must not keep redrawing.
    this._onData = () => this.schedule();
    window.addEventListener('morph-data', this._onData);
    // This device's settings (whose device it is, the family form) are set
    // in brAIn's ⚙ › Dashboard, in the shell's frame: the same origin and
    // the same storage, so the change arrives here as a storage event.
    this._onStorage = (e) => { if (!e.key || e.key.startsWith('morph.')) { this._salDirty = true; this.schedule(); } };
    window.addEventListener('storage', this._onStorage);
  }

  stopLive() {
    if (!this._live) return;
    this._live = false;
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
    clearInterval(this._tick);
    clearInterval(this._since);
    clearTimeout(this._retryT);
    document.removeEventListener('visibilitychange', this._onHide);
    window.removeEventListener('pagehide', this._onHide);
    window.removeEventListener('morph-data', this._onData);
    window.removeEventListener('storage', this._onStorage);
  }

  boot() {
    if (this.engine) return;
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLES}${SCRUB_CSS}${PULL_CSS}${POLISH_CSS}</style><div class="morph t-dark" data-morph-root><div class="scroll" style="height:var(--morph-h,100vh);overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain"><div class="wrap">
<div data-region="bar"></div><div data-region="lede"></div><div data-region="top"></div><div data-region="upcoming"></div><div data-region="scenes"></div><div data-region="rooms"></div><div data-region="notes"></div>
<div data-region="board"><div data-board></div></div></div></div></div>`;
    if (!document.querySelector('link[data-morph-fonts]')) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = FONTS_URL; l.dataset.morphFonts = '1'; document.head.appendChild(l);
    }
    this.$ = (sel) => root.querySelector(sel);
    this._bootAt = Date.now();
    this.rootEl = this.$('[data-morph-root]');
    this.engine = new Engine(this.rootEl);
    this.engine.scrollEl = this.$('.scroll');
    try { attachPull(this); } catch (e) { console.error('Morph: pull to refresh did not start', e); }
    this.engine.onSettle = () => this.audit();
    history.setOnData(() => this.schedule());
    this.bindEvents();
    this.attachWindow();
    // The scrub rail down the right edge, as it was in brAIn 3.0, opened by a
    // short pull to the left (scrub.js; house change, 29 Oct 2026: "I want it
    // to look like it did back in the version 3.0.0 days").
    try { this.rail = new Scrub(this); } catch (e) { console.error('Morph: the scrub rail did not start', e); }
    // Inside brAIn's shell the scroll is also the shell's to hear: brAIn's
    // header hides while the dashboard scrolls down and returns as it
    // scrolls up (shell.js passes it to brAIn's page).
    this.$('.scroll').addEventListener('scroll', (ev) => {
      this.ui.lastScroll = Date.now(); this.onScrollAway();
      if (this.rail && !this._railF) this._railF = requestAnimationFrame(() => { this._railF = 0; this.rail.paint(); });
      // `max` is how far it can scroll, so the header can tell the bottom's
      // bounce (and the pane growing as the header goes) from a scroll up.
      if (this._shell) { const sc = ev.currentTarget; this.dispatchEvent(new CustomEvent('morph-scroll', { bubbles: true, composed: true, detail: { y: sc.scrollTop, max: Math.max(0, sc.scrollHeight - sc.clientHeight) } })); }
    }, { passive: true });
    this.ro = new ResizeObserver((ents) => { const r = ents[0] && ents[0].contentRect; if (r) this._boardW = r.width; cancelAnimationFrame(this._ro); this._ro = requestAnimationFrame(() => this.engine.layout(false, true)); });
    this.ro.observe(this.$('[data-board]'));
    this.load();
    this.startLive();
    try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { this.engine.invalidate(); this.engine.layout(false, true); }); } catch (e) { /* no font API */ }
  }

  // A load that fails is tried again, 2 s, then twice as long each time up
  // to a minute, and the banner offers the next try now.
  async load() {
    clearTimeout(this._retryT);
    try {
      const d = await this.hass.callWS({ type: 'morph/load' });
      const rev = d && d.mirror && d.mirror.revision;
      this.data = d;
      this._retryMs = 0;
      if (!this.s.edit || !this.dash || rev !== this.revision) {
        this.dash = (d.mirror && d.mirror.dashboard) || null;
        this.revision = rev;
        this._secEnts = null;
      }
      this._salDirty = true;
      this.loadModules((d.mirror && d.mirror.card_modules) || []);
      this.schedule();
    } catch (e) {
      if (!this.data || this.data.error) this.data = { error: String((e && e.message) || e) };
      this._retryMs = Math.min(60000, (this._retryMs || 1000) * 2);
      if (this.live) this._retryT = setTimeout(() => this.load(), this._retryMs);
      this.schedule();
    }
  }

  retryLoad() {
    this._retryMs = 0;
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = this.hass.connection.subscribeMessage(() => this.load(), { type: 'morph/subscribe' }).catch(() => null); }
    this.load();
  }

  loadModules(mods) {
    const base = (this._panel && this._panel.config && this._panel.config.cards_url) || '/morph_cards';
    guardDefine();
    mods.forEach((m) => {
      const key = m.name + '@' + m.v;
      if (this.loadedModules.has(key)) return;
      this.loadedModules.add(key);
      // Once per version per page, an import in flight shared, a dropped
      // fetch tried once more, and a define the page already has skipped
      // (util.loadCard / guardDefine).
      const url = cardUrl(base, m.name, m.v);
      const before = cardPage().versions.get(m.name);
      loadCard(m.name, m.v, url, () => importWithRetry(url, { load: (u) => import(u) })).then((how) => {
        // A custom element cannot be defined twice on one page. A newer
        // file whose elements the page already has shows after a reload,
        // which is said and offered rather than reported.
        if (how === 'changed') this.toast(`${m.name} changed. Reload the page to see the new version.`, null, 'reload');
        // A file brAIn was asked to fix that now loads: its suggestion
        // closes itself (learning.house_card_loaded). Said only then, so a
        // clean load is not a line per card per page.
        if (how === 'loaded' && ((this.data && this.data.state && this.data.state.suggestions) || []).some((g) => g.card_file === m.name)) {
          this.report('loaded', m.name, '');
        }
        this.schedule();
      }).catch((e) => {
        // Any failure of a card loaded again mid-session is said the same
        // way: its shared helpers (morph-motion.js, morph-kit.js) are
        // imported without a version, so the page keeps the ones it first
        // loaded, and a card that now needs a newer helper fails ("does not
        // provide an export named NA"). After a reload it loads; a card that
        // is really broken is reported then, on its first load (house fix,
        // Oct 2026).
        if (before != null && before !== m.v) {
          this.toast(`${m.name} changed. Reload the page to see the new version.`, null, 'reload');
          return;
        }
        this.report('card', cardFailure(e), `${m.name}: ${String((e && e.stack) || e || '')}`, 'custom');
      });
    });
  }

  schedule() {
    if (this._raf || !this.live) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this.render(); });
  }

  settings() { return (this.data && this.data.state && this.data.state.settings) || {}; }
  admin() { return !!(this.data && this.data.admin); }

  // -------------------------------------------------------------- render

  render() {
    if (!this.engine || !this.hass) return;
    this._roomFaults = new Map();
    if (!document.getElementById('morph-secbg-props')) {
      const st = document.createElement('style'); st.id = 'morph-secbg-props';
      st.textContent = ['--sg', '--s1', '--s2', '--s3'].map((k) => `@property ${k}{syntax:'<color>';inherits:false;initial-value:transparent}`).join('');
      document.head.appendChild(st);
    }
    this._seMemo = new Map();
    const set = this.settings();
    const theme = set.theme && set.theme !== 'auto' ? set.theme : (this.hass.themes && typeof this.hass.themes.darkMode === 'boolean' ? (this.hass.themes.darkMode ? 'dark' : 'light') : window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    // boot.js draws its outline in the theme this page last used.
    if (theme !== this._savedTheme) { this._savedTheme = theme; try { localStorage.setItem('morph.theme', theme); } catch (e) { /* storage refused */ } }
    // brAIn at work: the mark breathes and the strip's edge shimmers (house change).
    { let busy = false; try { busy = !!((this.s.asks || []).some((x) => x.busy) || false); } catch (e) { /* not busy */ }
      if (this.rootEl.classList.contains('mbusy') !== busy) this.rootEl.classList.toggle('mbusy', busy); }
    this.engine.forceReduce = !!set.reduce_motion;
    const ready = this.data && !this.data.error && this.dash && this.brainInstalled();
    if (ready) this.updateSal();
    if (ready) this.followReplies();
    const form = ready ? this.form() : '';
    this.form_ = form;
    // The root class is set only when it changes: a class written on every
    // frame restarts every transition keyed to it.
    // Night dims the page only where the dashboard asks for it
    // (`night_dim: true`): at 40 % for everybody, a household found it
    // unreadable and had no way to turn it off (#343).
    const dim = form === 'night' && this.dash && this.dash.night_dim === true;
    const cls = `morph t-${theme}${set.reduce_motion ? ' reduce' : ''}${form ? ' form-' + form : ''}${dim ? ' night-dim' : ''}${this._shell ? ' inshell' : ''}`;
    if (this.rootEl.className !== cls) this.rootEl.className = cls;
    this.region('bar', this.barHtml());
    this.chrome(theme);
    this.region('lede', this.updateHtml() + (this.s.edit ? `<div class="lede">Editing · <b>hold anything to tell ${esc(this.who())} what to change</b> · drag a section by its title · tap a card to rename, resize or remove it</div>` : '') + this.activityHtml());
    this.$('[data-region="board"]').hidden = false;
    if (!this.data) { this.region('top', '<p class="sm">Opening Morph…</p>'); return; }
    this.readyOnce();
    if (this.data.error) { this.region('top', `<div class="banner bad" role="alert">Morph could not load: ${esc(this.data.error)}. Is brAIn started, with the Morph dashboard switched on in ⚙ › Features? It is tried again on its own. <button type="button" class="wd go mini" data-act="retry-load">Try again now</button></div>`); return; }
    // A face without the mind behind it would be a dashboard pretending to
    // be this one (vision §4.7): the page is one sentence.
    if (!this.brainInstalled()) { ['upcoming', 'scenes', 'rooms', 'notes'].forEach((r) => this.region(r, '')); this.$('[data-region="board"]').hidden = true; this.region('top', `<p class="story needbrain">${esc(NEEDS_BRAIN)}</p>`); return; }
    if (!this.dash) { this.region('top', `<div class="banner">brAIn has not written the dashboard yet. It builds the first one from your floors and rooms within a minute of the Morph dashboard being switched on.</div>`); return; }
    const dash = this.dash;
    upc.setLanes(dash.coming_up_lanes);
    this.region('top', this.topHtml(dash));
    // Coming up is not rebuilt under a finger, or while it is gliding to
    // where it was let go: the rebuild would land it before it arrives.
    // Coming up is always shown, under the Now row; there is no Next chip to
    // unfold it any more (house change, Oct 2026: "just show the calendar bar
    // all the time and get rid of this next pill").
    const showUpc = dash.coming_up !== false;
    if (!showUpc) this._upc = null;
    this.homeUpcoming();
    if (!this.upcFrozen()) this.region('upcoming', showUpc ? this.upcomingHtml() : '');
    this.region('scenes', (dash.scenes || []).length ? this.scenesHtml(dash) : '');
    // The scrub rail is how the page is moved through; no room line (house change, Oct 2026).
    this.region('rooms', '');
    this.region('notes', this.admin() ? this.problemsHtml() : '');
    this.renderBoard(dash);
    this.homeUpcoming();
    // The rail reads the rooms once the layout has settled.
    if (this.rail) { clearTimeout(this._railT); this._railT = setTimeout(() => { try { this.rail.paint(); } catch (e) { /* the rail waits for the next render */ } }, 700); }
    if (Object.keys(this.s.confirm).some((k) => k.startsWith('btn:'))) this.applyConfirms();
    try { this.placeThumbs(); } catch (e) { /* the plain pressed word */ }
    try { this.pageIn(); } catch (e) { /* no motion */ }
    this.tickSince();
  }


  brainInstalled() { return !(this.data && this.data.brain && this.data.brain.installed === false); }

  // ---------------------------------------------------------- the salience

  // Every card that can be lifted, and every case, as salience items.
  salItems() {
    const items = [];
    this.eachSection((sec) => {
      if (sec.hidden) return;
      this.sectionCards(sec).forEach((c) => {
        if (['scenes', 'note', 'lovelace', 'readings'].includes(c.type) || isHeadCard(c)) return;
        const ents = c.type === 'list' ? (c.entities || []) : c.entity ? [c.entity] : [];
        if (!ents.length) return;
        items.push({ id: c.id, sec: sec.id, entities: ents, primary: ents[0] });
      });
    });
    this.casesPlaced().forEach((k) => items.push({ id: 'k:' + k.id, sec: k._sec || '__cases', entities: [], case: k }));
    return items;
  }

  brain() { return (this.data && this.data.brain) || {}; }

  feedState() {
    const b = this.brain();
    return sal.feedHealth(b.feed, Date.now(), b.feed_mtime ? b.feed_mtime * 1000 : 0);
  }

  salContext(states, now) {
    const fh = this.feedState();
    const casesByEntity = {};
    this.cases().forEach((c) => { if (c.entity_id) (casesByEntity[c.entity_id] = casesByEntity[c.entity_id] || []).push(c); });
    const occupied = {}; const asleepRooms = {}; let anyAsleep = false; let sleepers = 0; let awake = 0;
    this.eachSection((sec) => {
      const p = this.presence(sec);
      if (p) occupied[sec.id] = true;
      if (this.asleepSince(sec)) { asleepRooms[sec.id] = true; anyAsleep = true; sleepers++; } else if (this.canSleep(sec)) awake++;
    });
    // The alarm panels on the dashboard are the house's alarm; a camera
    // system's panel elsewhere in the states is not (salience.alarmStates).
    const alarms = [];
    this.eachSection((sec) => this.sectionEntities(sec).forEach((e) => { if (domainOf(e) === 'alarm_control_panel' && !alarms.includes(e)) alarms.push(e); }));
    const pins = {};
    this.eachSection((sec) => this.sectionCards(sec).forEach((c) => { if (c.pin) pins[c.id] = c.pin === true || c.pin === 'always' ? true : 'active'; }));
    const day = new Date(now).toDateString();
    const suppressed = {};
    Object.keys(this.suppressed).forEach((id) => { if (this.suppressed[id] === day) suppressed[id] = true; });
    const narrow = (this.rootEl && this.rootEl.clientWidth) < 480;
    return {
      now, states, feed: fh.usable ? this.brain().feed : null, casesByEntity, pins, suppressed, touched: this.touched, asked: this.asked,
      occupied, asleepRooms, anyAsleep, allAsleep: sleepers >= 2 && awake === 0, alarms, nowMax: narrow ? sal.NOW_MAX_PHONE : sal.NOW_MAX,
      name: (e) => friendly(this.hass, e),
    };
  }

  // The list is computed every ten seconds, or at once after a salient
  // event; the page takes it only at a quiet moment (§4.4). Values paint
  // at once; positions wait.
  updateSal() {
    const now = Date.now();
    if (!this._salDirty && this.salState && now - this.salState.at < 10000) { this.maybeApply(now); return; }
    this._salDirty = false;
    let res;
    try { res = sal.compute(this.salItems(), this.salContext(this.hass.states, now), this.salState); } catch (e) {
      this.report('panel', `The salience list could not be computed: ${e.message || e}`, String(e && e.stack || '').slice(0, 1500));
      return;
    }
    this.salState = res;
    this.maybeApply(now);
  }

  maybeApply(now) {
    const res = this.salState; if (!res) return;
    const cur = this.salApplied;
    const sig = (r) => r ? r.now.join(',') + '|' + Object.values(r.items).filter((x) => x.band !== 'folded').map((x) => x.id + ':' + x.band).sort().join(',') : '';
    if (cur && sig(cur) === sig(res)) { this.salApplied = res; return; }
    // A cut (a safety trip, a door opening at night, or a press that asked
    // for the change) goes at once; anything else urgent only skips the
    // spacing, and still waits for hands to leave the page (§4.4).
    const entering = res.now.filter((id) => (!cur || !cur.now.includes(id)) && res.items[id]);
    const urgent = this._forceApply || entering.some((id) => res.items[id].cut) ? 'cut' : entering.some((id) => res.items[id].urgent);
    const ui = { ...this.ui, open: !!this.s.view || !!this.s.tell, pointerDown: !!(this.ptr || this.mptr || this.upcD || this.drag) };
    // The house entering night or away is a change of form, not a drift:
    // it waits for hands to be off the page but not for the spacing.
    if (cur && cur.period !== res.period) ui.lastArrange = 0;
    if (!cur || this.s.edit || sal.quietMoment(ui, now, urgent)) {
      this._forceApply = false;
      this.salApplied = res;
      // A rearrangement above the viewport moves the scroll with it, so
      // nothing in view moves (§4.4).
      if (cur && !this.s.edit) this.engine.compensate = true;
      this.ui.lastArrange = now;
      this.engine.invalidate();
    } else {
      // Changes wait for the next quiet moment, and the page moves once.
      clearTimeout(this._applyT);
      this._applyT = setTimeout(() => this.schedule(), 1300);
    }
  }

  // A card at the top of its room with a because line under it.
  leadsWithReason(id) {
    if (this.s.edit) return false;
    const a = this.salOf(id); const x = this.salNow(id);
    return a.band === 'lead' && !!(x.why && x.why.kind !== 'none');
  }

  // The applied result for one item, or {} (folded, nothing to say).
  salOf(id) { return (this.salApplied && this.salApplied.items[id]) || {}; }
  // The newest result for one item: what a because line says right now.
  salNow(id) { return (this.salState && this.salState.items[id]) || {}; }

  // The page's form: night or away (§10), or the ordinary page.
  form() {
    if (this.s.edit) return '';
    const per = this.salApplied && this.salApplied.period;
    if (per === 'night') return 'night';
    if (per === 'away') return 'away';
    return '';
  }

  // boot.js keeps its outline over the page until this says there is
  // something to show: the dashboard, or the sentence saying why not.
  readyOnce() {
    if (this._ready) return;
    this._ready = true;
    this.dispatchEvent(new Event('morph-ready'));
  }

  // Whether what is on screen is what Home Assistant would serve now. A page
  // stays open for days, and an update, or brAIn changing Morph's own code,
  // only reaches it on a reload. So this says which of the two it needs:
  // a reload (the code moved, or Home Assistant restarted onto a newer Morph
  // integration), or a restart of Home Assistant (the integration's code
  // changed, so a reload alone would not finish it). A newer add-on version
  // alone is not a restart: an update that moved only the version, or only
  // the panel's files, owes none, and `restart` is the integration's answer
  // (websocket.restart_owed, the rule the panel's verdict and Repairs use).
  updateHtml() {
    const d = this.data;
    if (!d || d.error) return '';
    const loaded = String((this._panel && this._panel.config && this._panel.config.version) || '');
    const integ = String(d.integration || '');
    const addon = String((d.state && d.state.version) || '');
    const stamp = String(window.__morphStamp || '');
    const bar = (text, act) => `<div class="update rise" role="status"><span>${esc(text)}</span>${act}</div>`;
    if ((integ && loaded && integ !== loaded) || (stamp && d.code && d.code !== stamp)) {
      const what = integ && loaded && integ !== loaded ? `Morph ${integ} is ready.` : 'Morph’s code has changed since this page opened.';
      return bar(`${what} Reload to run it.`, '<button type="button" class="wd strong" data-act="reload-page">Reload</button>');
    }
    // An integration from before `restart` was sent cannot say; it is a
    // release behind by definition, so the version decides, once.
    const owed = typeof d.restart === 'boolean' ? d.restart
      : !!(addon && integ && addon !== integ && addon !== 'dev');
    if (this.admin() && owed) {
      return bar(`${addon && addon !== 'dev' ? `brAIn ${addon} is installed. ` : ''}Restart Home Assistant to load its update.`, '');
    }
    return '';
  }

  region(name, html) {
    const el = name === 'upcoming' && this._upcEl ? this._upcEl : this.$(`[data-region="${name}"]`);
    if (!el) return;
    html = this.speak(html);
    if (this.cache.get('r:' + name) === html) return;
    // A box somebody is typing in survives the rebuild: same key, same
    // text, same caret.
    const active = this.shadowRoot.activeElement;
    const keep = active && el.contains(active) && active.dataset && active.dataset.keep ? { key: active.dataset.keep, value: active.value, pos: active.selectionStart } : null;
    const refocus = active && el.contains(active) && active.hasAttribute && active.hasAttribute('data-upc-vp');
    this.cache.set('r:' + name, html);
    el.hidden = !html;
    // A sideways strip keeps where it was scrolled to across the rebuild.
    const scrolls = {}; el.querySelectorAll('[data-keepscroll]').forEach((s) => { scrolls[s.dataset.keepscroll] = s.scrollLeft; });
    morph(el, html, this.shadowRoot);
    el.querySelectorAll('[data-keepscroll]').forEach((s) => { if (scrolls[s.dataset.keepscroll] != null) s.scrollLeft = scrolls[s.dataset.keepscroll]; });
    this.restoreTellText(el);
    if (refocus) { const n = el.querySelector('[data-upc-vp]'); if (n) n.focus({ preventScroll: true }); }
    if (keep) {
      const again = el.querySelector(`[data-keep="${keep.key}"]`);
      if (again) { again.value = keep.value; again.focus(); try { again.setSelectionRange(keep.pos, keep.pos); } catch (e) { /* not a text box */ } }
    }
  }

  // What brAIn's header needs from Morph inside the shell: the theme to
  // draw itself in, and whether Edit (or Done and YAML) belongs there. Sent
  // only when it changes; the shell passes it to brAIn's page.
  chrome(theme) {
    const c = { theme, admin: this.admin(), edit: !!this.s.edit, yaml: this.s.yaml != null };
    const key = JSON.stringify(c);
    if (key === this._chromeKey) return;
    this._chromeKey = key;
    this.dispatchEvent(new CustomEvent('morph-chrome', { bubbles: true, composed: true, detail: c }));
  }

  // A press on Morph's controls in brAIn's header ('edit', 'yaml-toggle').
  chromeAct(name) {
    if (name !== 'edit' && name !== 'yaml-toggle') return;
    if (name === 'edit' && !this.admin() && !this.s.edit) return;
    this.act(name, { dataset: {} });
  }

  barToast() {
    if (!this.s.toast) return '';
    return `<div class="bar"><span class="bartoast rise" role="status" aria-live="polite">${esc(this.s.toast.text)}${this.s.toast.sha ? ` <button type="button" class="wd go mini" data-act="undo-commit" data-v="${esc(this.s.toast.sha)}">Undo</button>` : ''}${this.s.toast.action === 'reload' ? ` <button type="button" class="wd go mini" data-act="reload-page">Reload</button>` : ''}</span></div>`;
  }

  barHtml() {
    const now = new Date();
    const date = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }) + ' · ' + clock(now);
    // Inside brAIn's shell with brAIn's header above (the frame), the
    // header is brAIn's: its tabs, its ☰ and ⚙. Alone (somebody who is not
    // an administrator), the bar names the assistant and opens the sidebar.
    // Feed and Settings are brAIn's own tabs, never pages of Morph's.
    const menu = this._narrow && !this._shell ? `<button type="button" class="menu" data-act="menu" aria-label="Open the sidebar"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>` : '';
    const admin = this.admin();
    let right = '';
    if (this.s.edit) right = `<button type="button" class="go barw" data-act="yaml-toggle">${this.s.yaml ? 'Hide YAML' : 'YAML'}</button><button type="button" class="go barw strong" data-act="edit">Done</button>`;
    // The toast is announced (a live region that is always there, so a
    // screen reader hears each new one).
    const toast = `<span class="bartoast${this.s.toast ? ' rise' : ''}" role="status" aria-live="polite">${this.s.toast ? `${esc(this.s.toast.text)}${this.s.toast.sha ? ` <button type="button" class="wd go mini" data-act="undo-commit" data-v="${esc(this.s.toast.sha)}">Undo</button>` : ''}${this.s.toast.action === 'reload' ? ` <button type="button" class="wd go mini" data-act="reload-page">Reload</button>` : ''}` : ''}</span>`;
    const yaml = this.s.edit && this.s.yaml != null ? `<div class="yamlbox"><span class="label">Raw configuration · /config/morph/dashboard.yaml</span><textarea class="code-ed" data-keep="yaml" spellcheck="false" aria-label="dashboard.yaml">${esc(this.s.yaml)}</textarea><div class="row"><button type="button" class="wd go" data-act="yaml-save">Save YAML</button><span class="small">Saved as one commit; Undo puts it back.</span></div></div>` : '';
    // Inside brAIn's shell there is ONE header, brAIn's (the owner: "there
    // are two headers … merge them"): Done and YAML are drawn there from
    // `chrome()` and pressed back through `chromeAct`, and a toast is a line
    // of the page rather than a bar. Edit is a quiet pencil at the right of
    // the page's first line, under the header, never a button in it.
    if (this._shell) {
      const pen = admin && !this.s.edit ? `<button type="button" class="go editq" data-act="edit" aria-label="Edit the dashboard"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>Edit</button>` : '';
      return `${toast || pen ? `<div class="toastline">${toast}<span class="flex1"></span>${pen}</div>` : ''}${yaml}`;
    }
    if (!this.s.edit && admin) right = `<button type="button" class="go editq" data-act="edit" aria-label="Edit the dashboard"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg></button>`;
    const dateHtml = this._narrow ? '' : `<span class="date">${esc(date)}</span>`;
    return `<div class="bar">${menu}<span class="brand">${markSvg(16, Date.now() - (this._bootAt || 0) < 2500 ? 'drawin' : '')}MORPH</span>${toast}<span class="flex1"></span>${dateHtml}${right}</div>${yaml}`;
  }

  // ---------------------------------------------------------------- the top

  greeting() {
    const h = new Date().getHours();
    return h < 5 ? 'Good night.' : h < 12 ? 'Good morning.' : h < 18 ? 'Good afternoon.' : 'Good evening.';
  }

  // One clause of the verdict for one salience item, from the entity's own
  // state — never from a number nobody measured.
  clauseFor(x, states) {
    const H = this.hass;
    if (x.isCase || String(x.id).startsWith('k:')) {
      const c = this.caseById(String(x.id).slice(2));
      return c ? checkDoorClaims(c.claim || c.text || '', H) : '';
    }
    const st = states[x.eid];
    if (!st) return '';
    const name = friendly(H, x.eid);
    const is = 'is';
    const d = domainOf(x.eid); const dc = st.attributes.device_class; const i = x.inp || {};
    if (d === 'lock') return st.state === 'unlocked' ? `${name} ${is} unlocked` : st.state === 'jammed' ? `${name} ${is} jammed` : '';
    if (d === 'binary_sensor' && ['smoke', 'gas', 'carbon_monoxide', 'moisture'].includes(dc) && st.state === 'on') return `${name} detects ${dc === 'moisture' ? 'water' : dc === 'carbon_monoxide' ? 'carbon monoxide' : dc}`;
    if ((d === 'binary_sensor' || d === 'cover') && ['on', 'open', 'opening'].includes(st.state)) {
      const recent = st.last_changed && Date.now() - Date.parse(st.last_changed) < 120000;
      return recent ? `${name} just opened` : `${name} ${is} open`;
    }
    if (i.pr && i.pr.finished) return `${name} finished${i.pr.since ? ' ' + agoWords(Date.now() - i.pr.since * 1000) : ''}`;
    if (d === 'media_player' && st.state === 'playing') return `${name} ${is} playing${st.attributes.media_title ? ' ' + st.attributes.media_title : ''}`;
    if (i.pr && i.pr.running) return `${name} ${is} running${i.pr.pct != null ? ' · ' + Math.round(i.pr.pct) + '%' : ''}`;
    if (i.dv && i.dv.usual != null) return `${name} ${is} ${fmt(i.dv.value, i.dv.unit)}, usually about ${fmt(i.dv.usual, i.dv.unit)}`;
    return '';
  }

  // The verdict (§2.1): the story's first clause is the top of the
  // salience list, set in that item's colour; then at most two more as
  // plain clauses; then how many cases are waiting. Each clause is a jump.
  // Nothing salient: brAIn's own sentence about now if it has a fresh one,
  // else "Everything is at rest." in indigo.
  verdict(states) {
    const out = [];
    const res = this.salState;
    const seen = new Set();
    ((res && res.top) || []).forEach((id) => {
      if (out.length >= 3) return;
      const x = res.items[id]; if (!x) return;
      const text = this.clauseFor(x, states);
      const key = x.eid || id;
      if (!text || seen.has(key)) return;
      seen.add(key);
      out.push({ id, text, color: x.color || 'var(--text)' });
    });
    return out;
  }

  // Doors, windows and garage doors that are open right now, as clauses.
  // The story may not say everything is locked, closed or at rest while
  // one of these is open (#676): locks being locked said nothing about a
  // contact that was open.
  openClauses() {
    const H = this.hass; const out = [];
    Object.values(H.states).forEach((st) => {
      const d = domainOf(st.entity_id); const dc = (st.attributes || {}).device_class;
      const door = d === 'binary_sensor' ? ['door', 'window', 'garage_door', 'opening'].includes(dc) && st.state === 'on'
        : d === 'cover' ? ['garage', 'door', 'window'].includes(dc) && ['open', 'opening'].includes(st.state) : false;
      if (door) out.push(`${friendly(H, st.entity_id)} is open`);
    });
    return out;
  }

  // Locks that are unlocked right now, as clauses: the away line may not say
  // "Everything is locked." over one (#719).
  unlockedClauses() { return unlockedLocks(this.hass); }

  verdictHtml(dash) {
    return this.verdictHtml0(dash);
  }

  verdictHtml0(dash) {
    const fh = this.feedState();
    const offline = fh.state === 'offline' || fh.state === 'expired' ? '<span class="vq"> · brAIn offline</span>' : '';
    const sentence = (parts) => {
      const first = parts[0];
      const rest = parts.slice(1);
      return `<button type="button" class="vjump" data-act="jump" data-v="${esc(first.id)}" style="--vc:${first.color}">${esc(first.text.replace(/\.+$/, ''))}.</button>${rest.map((r) => ` <button type="button" class="vjump plain" data-act="jump" data-v="${esc(r.id)}" style="--vc:${r.color}">${esc(r.text.replace(/\.+$/, ''))}.</button>`).join('')}`;
    };
    const parts = this.verdict(this.hass.states);
    const open = this.cases().filter((c) => c.kind !== 'chore' && (c.urgent || c.severity === 'critical')).length;
    const tail = open ? ` <button type="button" class="vjump plain" data-act="jump" data-v="k:${esc((this.cases().find((c) => c.urgent || c.severity === 'critical') || {}).id || '')}">…and ${open} thing${open === 1 ? '' : 's'} need${open === 1 ? 's' : ''} you.</button>` : '';
    const opens = parts.length ? [] : this.form_ === 'away' ? [...this.openClauses(), ...this.unlockedClauses()] : this.openClauses();
    const openHtml = opens.length ? `<span style="color:var(--amber)">${esc(opens.slice(0, 2).join('. '))}${opens.length > 2 ? ` and ${opens.length - 2} more` : ''}.</span>` : '';
    if (this.form_ === 'away') {
      const sec = parts.length ? ' ' + sentence(parts) : ' ' + (openHtml || '<span style="color:var(--indigo)">Everything is locked.</span>');
      return `<p class="story"><span class="hi">Nobody is home.</span>${sec}${tail}${offline}</p>`;
    }
    if (parts.length) return `<p class="story">${sentence(parts)}${tail}${offline}</p>`;
    const sit = this.brain().situation;
    // A model's sentence was written before the doors moved: each claim about
    // one is checked against its state now, and one that no longer holds goes.
    const sentence_ = sit && sit.sentence ? checkDoorClaims(sit.sentence, this.hass) : '';
    // A model's sentence that claims everything is shut is not shown over an open door.
    const claimsAllShut = sit && /\b(every|all|everything)\b[^.]*\b(locked|closed|shut|secure)/i.test(sentence_);
    if (sit && sentence_ && !(claimsAllShut && opens.length) && (!sit.at || Date.now() / 1000 - sit.at < 3600) && this.form_ !== 'night') return `<p class="story"><span class="hi">${esc(sentence_)}</span>${tail}${offline}</p>`;
    return `<p class="story">${openHtml || '<span style="color:var(--indigo)">Everything is at rest.</span>'}${tail}${offline}</p>`;
  }

  // The clock and the outside temperature a night page carries at its top
  // right (§10.3), read from across the room.
  clockHtml() {
    if (this.form_ !== 'night') return '';
    const w = Object.values(this.hass.states).find((st) => domainOf(st.entity_id) === 'weather');
    const t = w && w.attributes.temperature != null ? `${Math.round(w.attributes.temperature)}°` : '';
    return `<div class="bigclock" aria-hidden="true"><b data-clock="1">${esc(clock(new Date()))}</b>${t ? `<span>${esc(t)}</span>` : ''}</div>`;
  }

  topHtml(dash) {
    const holding = (k) => (this.s.hold === k ? ' holding' : '');
    const story = dash.story !== false ? `<div class="holdable${holding('top:story')}" data-hold="story">${this.verdictHtml(dash)}${this.tellBox('story')}</div>` : '';
    const edit = this.s.edit;
    let ask = '';
    if ((dash.ask !== false || edit)) {
      // Every question asked keeps running and its answer stacks here,
      // newest first (the owner: "when asking multiple commands everything
      // keeps running and the answers stack up"). One slot used to be
      // overwritten by the next question, and its poll cleared with it.
      const asks = this.s.asks;
      const busy = asks.some((a) => a.busy);
      const sugs = !asks.length ? (edit ? TELL_SUGS.dashboard : ['Why is it warm upstairs?', 'What’s left on?', 'Is everything locked?']) : [];
      ask = `<div data-ask="1" aria-busy="${busy}" style="display:flex;flex-direction:column;gap:6px;margin-top:6px">
<label class="askrow">${SPARK}<input class="askin" type="text" data-keep="ask" data-act-enter="ask" placeholder="${edit ? `Tell ${esc(this.who())} how to change this dashboard…` : 'Ask or tell the house…'}" aria-label="${edit ? `Tell ${esc(this.who())} how to change this dashboard` : 'Ask or tell the house'}">${busy ? '<span class="pulse askbusy" aria-hidden="true"></span>' : ''}</label>
${this.tellBox('dashboard')}
${sugs.length && !(this.s.tell && this.s.tell.kind === 'dashboard') ? `<div class="sugs">${sugs.map((s) => `<button type="button" class="wd" data-act="ask-sug" data-v="${esc(s)}" style="font-size:14px;min-height:34px">${esc(s)}</button>`).join('')}</div>` : ''}
${asks.map((a) => this.answerHtml(a)).join('')}</div>`;
    }
    // The clock sits in line with the ask bar (its underline level with the
    // clock's foot), not laid over it and the Coming up strip below.
    const clk = this.clockHtml();
    const hello = dash.greeting !== false && this.form_ !== 'night' ? `<h1 class="hello">${esc(this.greeting())}</h1>` : '';
    const note = this.data.state && this.data.state.note ? `<div class="banner">${esc(this.data.state.note)}</div>` : '';
    const inner = `${hello}${note}${story}${clk ? `<div class="topline">${ask || '<div></div>'}${clk}</div>` : ask}`;
    if (!inner) return '';
    return `<section aria-label="Now" class="topsec" style="display:flex;flex-direction:column;gap:14px;max-width:980px">${inner}</section>`;
  }

  // One asked question and its answer (or what brAIn is doing about it).
  answerHtml(a) {
    const conv = a.conv;
    const busyWords = conv && conv.state ? ((conv.state.steps || []).slice(-1)[0] || {}).t || `${this.who()} is thinking` : 'Thinking';
    return `<div class="answer rise" data-k="ask-${a.key}" role="status" aria-live="polite"><span class="small">${esc(a.q)}</span><p>${a.busy ? '<span class="pulse" aria-hidden="true"></span>' : ''}${esc(a.busy ? busyWords + '…' : a.answer || '')}</p>${(a.show || []).length ? `<div class="row" style="flex-wrap:wrap;gap:0 20px">${a.show.map((x) => `<button type="button" class="wd go showme" data-act="reveal-card" data-v="${esc(x.id)}" style="font-size:15px">Show me ${esc(x.name)}</button>`).join('')}</div>` : ''}${a.undo ? `<div class="row"><button type="button" class="wd strong" data-act="undo-commit" data-v="${esc(a.undo)}">Undo</button></div>` : ''}${!a.busy && this.admin() && a.kind !== 'tell' ? `<div class="row"><button type="button" class="wd" data-act="ask-tell" data-v="${a.key}" style="font-size:14px;min-height:34px">Change the dashboard instead</button></div>` : ''}</div>`;
  }

  // Coming up: a fixed reading point with the next day sliding behind it
  // (upcoming.js). The cursor is kept as a TIME (`upcAt`, null for now), so
  // something you stopped on stays under the line as the minutes pass.
  upcomingHtml() {
    // The board's width, as its ResizeObserver last measured it: reading it
    // here would force a layout in the middle of the render.
    const w = this._boardW || window.innerWidth;
    const now = Date.now();
    const m = upc.model(this.hass, now, (w < 640 ? 0.9 : 1.25) * upc.getZoom(), []); // Then mode is gone (house change, Nov 2026): nothing from the past.
    if (!m.stacks.length && !m.durs.length && !(m.kinds || []).length && !this.s.edit) { this._upc = null; return ''; }
    this._upc = m;
    // Repainting the calendars' colors is an Edit-mode tool (house change).
    m.edit = !!this.s.edit;
    // Whatever is at the line can be open in place (house change, Oct 2026).
    m.open = !!this.s.upcOpen; m.focusLane = this.s.upcOpen ? this.s.upcLane || null : null; m.onDash = (e) => this.onDash(e);
    m.sel = this.s.upcOpen && m.expanded ? this.s.upcSel || null : null;
    if (!this._upcRunsWired) { this._upcRunsWired = true; upc.setOnRuns(() => { if (!this.upcFrozen()) this.schedule(); }); }
    const holding = this.s.hold === 'top:upcoming' ? ' holding' : '';
    return `<div class="holdable${holding}" data-hold="upcoming" aria-label="Coming up">${upc.html(m, this.upcCursor(m))}${this.tellBox('upcoming')}</div>`;
  }

  // The Now row's Next chip (cards/morph-now.js): the next few things Coming
  // up holds, and the strip it unfolds in place (house change, Oct 2026).
  upcNext(n = 2) {
    const now = Date.now();
    return upc.collect(this.hass, now, []).filter((e) => e.at > now && ['calendar', 'timer', 'done', 'date', 'sun'].includes(e.kind))
      .sort((a, b) => a.at - b.at).slice(0, n).map((e) => ({ label: (e.more && e.more.title) || e.label, at: e.at, kind: e.kind }));
  }
  upcomingShown() { return true; }
  // Coming up unfolds right under the assistant's card: in the Now card's own slot,
  // below its chips, so the Next chip opens it where it is (house change,
  // Oct 2026: "it should be under the assistant's card"). Without a Now card on
  // the page it keeps its place at the top. The slot is watched for size, so
  // the board makes room as it opens.
  homeUpcoming() {
    const el = this._upcEl || (this._upcEl = this.$('[data-region="upcoming"]')); if (!el) return;
    const now = this.$('[data-board] morph-now');
    const slot = now && now.parentNode;
    if (slot) {
      if (el.parentNode !== slot || el.previousSibling !== now) now.after(el);
      el.style.marginTop = now.childElementCount ? '10px' : '';
    } else {
      const home = this.$('[data-region="scenes"]');
      if (home && el.nextSibling !== home) home.before(el);
      el.style.marginTop = '';
    }
  }
  toggleUpcoming() { this.s.upcShow = !this.s.upcShow; if (!this.s.upcShow) { this.s.upcOpen = false; this.s.upcAt = null; } haptic('medium'); this.schedule(); window.dispatchEvent(new CustomEvent('morph-upcoming')); }

  upcCursor(m) { return this.s.upcAt == null ? 0 : upc.clampC(m, (this.s.upcAt - m.base) / 60000); }

  upcFrozen() { return !!(this.upcD || this._upcWc != null || (this._upcGlide && performance.now() < this._upcGlide)); }

  upcRegion() { return this._upcEl || this.$('[data-region="upcoming"]'); }

  // Puts the reading point on `c` (minutes from now): glides there, then
  // lets the next render draw it at rest. Left away from now, it drifts back.
  upcGo(m, c, glide = true) {
    c = upc.clampC(m, c);
    if (Math.abs(c) < 0.5) c = 0;
    this.s.upcAt = c === 0 ? null : m.base + c * 60000;
    const el = this.upcRegion();
    const tr = el && el.querySelector('[data-cu-track]');
    const still = !glide || !tr || (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
    if (!still) {
      tr.classList.add('glide');
      this._upcGlide = performance.now() + 620;
      clearTimeout(this._upcGlideT);
      this._upcGlideT = setTimeout(() => { tr.classList.remove('glide'); this._upcGlide = 0; this.schedule(); }, 640);
    }
    upc.paint(el, m, c);
    clearTimeout(this._upcIdle);
    if (c !== 0) this._upcIdle = setTimeout(() => { if (!this.upcD && this._upc) this.upcGo(this._upc, 0); }, upc.IDLE_BACK_MS);
    if (still) this.schedule();
  }

  // Zooms the strip to `z` about the reading line (the cursor is a time, so
  // what is under the line stays there) and redraws it at the new scale.
  upcZoom(z) {
    const before = upc.getZoom(); if (upc.setZoom(z) === before) return;
    this.region('upcoming', this.upcomingHtml());
  }

  // Zoom glides there, about the reading line, with a tick when it lands.
  upcZoomTo(z) {
    cancelAnimationFrame(this._upcZt);
    const z0 = upc.getZoom(); if (Math.abs(z - z0) < 0.001) return;
    const t0 = performance.now(); const D = this.engine.reduce() ? 0 : 300;
    const stepf = (now) => {
      const p = D ? Math.min(1, (now - t0) / D) : 1; const ez = 1 - Math.pow(1 - p, 3);
      this.upcZoom(z0 * Math.pow(z / z0, ez));
      if (p < 1) this._upcZt = requestAnimationFrame(stepf); else haptic('selection');
    };
    this._upcZt = requestAnimationFrame(stepf);
  }

  // A detent for every zoom step crossed while dragging the axis or pinching.
  upcZoomTick(z) {
    const STEPS = [0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24];
    const i = STEPS.filter((x) => z >= x - 1e-6).length;
    if (this._upcZi != null && i !== this._upcZi) haptic(z <= upc.ZOOM_MIN + 1e-3 || z >= upc.ZOOM_MAX - 1e-3 ? 'heavy' : 'selection');
    this._upcZi = i;
  }

  upcDown(e, vp) {
    const m = this._upc; if (!m) return;
    // A second finger on the strip turns the drag into a pinch (house change).
    const d0 = this.upcD;
    if (d0 && d0.pid !== e.pointerId && !d0.pinch) {
      try { vp.setPointerCapture(e.pointerId); } catch (er) { /* fine */ }
      d0.pinch = { a: d0.pid, ax: d0.lx, b: e.pointerId, bx: e.clientX, z0: upc.getZoom(), c: d0.c };
      d0.pinch.s0 = Math.max(24, Math.abs(d0.pinch.bx - d0.pinch.ax));
      d0.moved = true;
      return;
    }
    const tr = vp.querySelector('[data-cu-track]'); if (tr) tr.classList.remove('glide');
    clearTimeout(this._upcIdle); clearTimeout(this._upcGlideT); this._upcGlide = 0;
    const lens = vp.querySelector('[data-cu-lens]'); const lr = lens && lens.getBoundingClientRect();
    const c0 = this.upcCursor(m);
    this.upcD = { x0: e.clientX, y0: e.clientY, c0, c: c0, lx: e.clientX, lt: performance.now(), v: 0, moved: false, vp, pid: e.pointerId, px: lr ? lr.left + lr.width / 2 : e.clientX };
    // On the time axis (below the lanes), a drag zooms: right to look closer,
    // left to see more; a double tap there goes back to the whole day.
    // (Measured from the axis itself: the lens is hidden when expanded.)
    const axEl = vp.querySelector('.cu-tl') ? [...vp.querySelectorAll('.cu-tl')].map((x) => x.getBoundingClientRect()).find((x) => x.height) : null;
    const axTop = axEl ? axEl.top - 6 : lr && lr.height ? lr.bottom + 1 : Infinity;
    if (e.clientY > axTop) { this.upcD.axis = { z0: upc.getZoom() }; this._upcZi = null; this.upcZoomTick(upc.getZoom()); }
  }

  upcMove(e) {
    const d = this.upcD; const m = this._upc; if (!d || !m) return;
    if (d.pinch) {
      const p = d.pinch; if (p.done) return;
      if (e.pointerId === p.a) p.ax = e.clientX; else if (e.pointerId === p.b) p.bx = e.clientX; else return;
      const z = p.z0 * Math.max(24, Math.abs(p.bx - p.ax)) / p.s0;
      if (Math.abs(z - upc.getZoom()) / upc.getZoom() < 0.03) return;
      this.upcZoomTick(Math.max(upc.ZOOM_MIN, Math.min(upc.ZOOM_MAX, z)));
      cancelAnimationFrame(this._upcZf);
      this._upcZf = requestAnimationFrame(() => { this.s.upcAt = p.c === 0 ? null : m.base + p.c * 60000; this.upcZoom(z); });
      return;
    }
    const dx = e.clientX - d.x0;
    if (!d.moved) {
      if (Math.abs(dx) < 6) return;
      // A mostly vertical stroke is the page scrolling, not a look into the past (house change).
      if (!d.axis && Math.abs(e.clientY - d.y0) > Math.abs(dx) * 0.6) { this.upcD = null; return; }
      d.moved = true; try { d.vp.setPointerCapture(d.pid); } catch (er) { /* fine */ }
      // Moving the strip folds what was open at the line.
      if (this.s.upcOpen && !d.axis) { this.s.upcOpen = false; const dt0 = this.upcRegion() && this.upcRegion().querySelector('[data-cu-detail]'); if (dt0) dt0.remove(); }
    }
    if (d.axis) {
      const z = Math.max(upc.ZOOM_MIN, Math.min(upc.ZOOM_MAX, d.axis.z0 * Math.exp(dx / 140)));
      this.upcZoomTick(z);
      cancelAnimationFrame(this._upcZf);
      this._upcZf = requestAnimationFrame(() => this.upcZoom(z));
      return;
    }
    const now = performance.now(); const dt = now - d.lt;
    if (dt > 0) d.v = 0.7 * ((e.clientX - d.lx) / dt) + 0.3 * d.v;
    d.lx = e.clientX; d.lt = now;
    d.c = upc.clampC(m, d.c0 - dx / m.k);
    upc.paint(this.upcRegion(), m, d.c);
  }

  // A tap goes to what is nearest where it landed; a swipe coasts on its
  // speed and settles on the nearest event, if one is close.
  upcUp(e) {
    const d = this.upcD; const m = this._upc;
    // A pinch ends when its first finger lifts; the other is let go quietly.
    if (d && d.pinch) {
      if (d.pinch.done) { this.upcD = null; if (this._upc) this.upcGo(this._upc, d.pinch.c, false); return; }
      d.pinch.done = true; return;
    }
    this.upcD = null;
    if (!d || !m) return;
    if (d.axis) {
      if (d.moved) return;
      // A double tap on the axis: all the way out again.
      const now = performance.now();
      if (this._upcAxisTap && now - this._upcAxisTap < 320) { this._upcAxisTap = 0; this.upcZoomTo(upc.ZOOM_MIN); return; }
      this._upcAxisTap = now;
      return;
    }
    if (!d.moved) {
      // Where the tap landed, in time: from the track itself (x = 0 is now).
      // (It was measured from the press, which for a tap is always the line,
      // so every tap read whatever sat under the line; fixed Oct 2026.)
      const tr = d.vp.querySelector('[data-cu-track]'); const trx = tr ? tr.getBoundingClientRect().left : d.px;
      const t = tr ? (e.clientX - trx) / m.k : d.c0 + (e.clientX - d.px) / m.k;
      // Expanded: select exactly what is under the finger, in the row it is
      // in, and leave the strip where it is (household, Oct 2026).
      if (m.expanded) {
        let lane = null, best = 1e9;
        this.upcRegion().querySelectorAll('.cu-ln').forEach((b) => { const r = b.getBoundingClientRect(); const dy = Math.abs(e.clientY - (r.top + r.height / 2)); if (dy < best) { best = dy; lane = b.dataset.v; } });
        const sel = lane && best <= 16 ? upc.pickAt(m, lane, t) : null;
        const same = sel && this.s.upcSel && this.s.upcOpen && this.s.upcSel.lane === sel.lane && this.s.upcSel.t === sel.t && this.s.upcSel.label === sel.label;
        this.s.upcSel = same ? null : sel; this.s.upcOpen = !!(sel && !same);
        haptic(this.s.upcOpen ? 'light' : 'selection');
        this.region('upcoming', this.upcomingHtml());
        return;
      }
      // Condensed: a tap brings what is nearest it to the line and opens it
      // in place; a tap on nothing folds what was open (house change).
      // Expanded, the tap belongs to the lane it landed on: inside a bar it
      // stays where it is, otherwise it goes to that lane's nearest item.
      const lens = d.vp.querySelector('[data-cu-lens]'); const lr = lens && lens.getBoundingClientRect();
      const lane = m.expanded && lr ? upc.laneAt(m, e.clientY - (lr.top + 12)) : null;
      this.s.upcLane = lane ? lane.id : null;
      const ls = lane ? upc.laneSnap(lane, t, 40 / m.k) : null;
      const s = ls != null ? ls : upc.snap(m, t, 24 / m.k);
      const was = !!this.s.upcOpen;
      this.s.upcOpen = s != null;
      if (s != null) haptic('light'); else if (was) haptic('selection');
      this.upcGo(m, s != null ? s : t);
      if (s != null && Math.abs(s - d.c0) < 0.5) this.region('upcoming', this.upcomingHtml());
      return;
    }
    if (performance.now() - d.lt > 90) d.v = 0;
    const proj = upc.clampC(m, d.c - (d.v * 260) / m.k);
    const s = upc.snap(m, proj, 60 / m.k);
    this.upcGo(m, s != null ? s : proj);
  }

  // A sideways trackpad or a tilted wheel scrubs; an ordinary scroll still
  // scrolls the page.
  upcWheel(e) {
    const vp = e.target.closest && e.target.closest('[data-upc-vp]');
    const m = this._upc;
    if (!vp || !m || this.s.edit) return;
    // A trackpad pinch (and ctrl + wheel) zooms the strip, not the page.
    if (e.ctrlKey) { e.preventDefault(); this.upcZoom(upc.getZoom() * Math.exp(-e.deltaY * 0.01)); return; }
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    e.preventDefault();
    const tr = vp.querySelector('[data-cu-track]'); if (tr) tr.classList.remove('glide');
    clearTimeout(this._upcIdle);
    this._upcWc = upc.clampC(m, (this._upcWc != null ? this._upcWc : this.upcCursor(m)) + (e.deltaX / m.k) * 0.7);
    upc.paint(this.upcRegion(), m, this._upcWc);
    clearTimeout(this._upcWt);
    this._upcWt = setTimeout(() => {
      const c = this._upcWc; this._upcWc = null;
      const s = upc.snap(m, c, 30 / m.k);
      this.upcGo(m, s != null ? s : c);
    }, 170);
  }

  scenesHtml(dash) {
    const H = this.hass; const cur = currentScene(H, dash.scenes);
    const holding = this.s.hold === 'top:scenes' ? ' holding' : '';
    // The prefix every scene shares becomes the label ("Interior lights:
    // Nightvision · Off") instead of being said on every word (Oct 2026).
    const names = dash.scenes.map((e) => friendly(H, e)); const ws = sceneWords(names);
    const m = /^(.+?)\s+[-–]\s+/.exec(names[0] || ''); const label = ws[0] !== names[0] && m ? m[1] : 'Scenes';
    return `<div class="holdable scenesline${holding}" data-hold="scenes"><span class="label" style="margin-right:4px">${esc(label)}</span>${dash.scenes.map((e, i) => `<button type="button" class="wd" data-act="scene" data-v="${esc(e)}" aria-pressed="${cur === e}">${esc(ws[i])}</button>`).join('')}${this.tellBox('scenes')}</div>`;
  }

  // ------------------------------------------------------------- the cases

  // brAIn's one list (§13.1), as brAIn published it. Morph keeps none of
  // its own: a finding, a question, a suggestion — Morph's own learning
  // suggestions included, which brAIn files with source `morph` — is a case
  // here, answered here, and answered everywhere.
  cases() {
    const b = this.brain();
    const list = Array.isArray(b.cases) ? b.cases : [];
    const gone = this.answeredCases(list);
    return list.filter((c) => c && c.id && c.kind !== 'chore' && !gone.has(c.id) && !this.caseSettled(c) && !this.caseHealed(c));
  }

  // A problem about something being offline whose evidence is all reporting
  // again has healed, whoever fixed it and wherever: every place a case is
  // drawn goes through cases(), so it leaves them all at once instead of
  // waiting for brAIn to re-check it (Oct 2026).
  caseHealed(c) {
    if (c.kind !== 'problem' || !/\b(offline|unavailable|unreachable|not responding|disconnected|dropped off)\b/i.test(c.claim || c.text || '')) return false;
    const S = this.hass && this.hass.states;
    const ev = [...new Set((c.evidence || []).filter((e) => typeof e === 'string' && e.includes('.')))];
    if (!S || !ev.length) return false;
    return ev.every((e) => S[e] && !['unavailable', 'unknown'].includes(S[e].state));
  }

  // A reply brAIn took ("I'll remember that.", "Done.", "Noted.") ends the
  // case: it leaves instead of sitting there with its answer (Oct 2026).
  caseSettled(c) {
    const th = Array.isArray(c.thread) ? c.thread : [];
    if (th.length < 2 || !th.some((t) => t && t.who === 'you')) return false;
    const last = th[th.length - 1] || {};
    if (last.who === 'you' || last.tell) return false;
    const w = String(last.text || '').trim();
    return w.length < 120 && !/\?/.test(w) && /^(i['’]ll remember|i will remember|remembered|noted|got it|done|thanks|thank you|okay|ok\b|saved|added|i['’]ve (noted|remembered|saved|added))/i.test(w);
  }

  // Cases answered from this page (Dismiss, To Do, Snooze…) leave at once,
  // rather than waiting for brAIn to publish its list again. One stays
  // hidden until brAIn's list drops it, or until brAIn has published twice
  // more than two minutes after the press and still lists it (brAIn kept
  // it); an hour at most. Kept in localStorage so a reload does not bring
  // it back meanwhile.
  answeredCases(list) {
    if (!this._answered) { try { this._answered = JSON.parse(localStorage.getItem('morph.answered') || '{}') || {}; } catch (e) { this._answered = {}; } }
    const a = this._answered; const at = Number(this.brain().cases_at) || 0; const now = Date.now() / 1000;
    const ids = new Set((list || []).map((c) => c && c.id));
    let changed = false;
    Object.keys(a).forEach((id) => {
      const t = Number(a[id]) || 0;
      if (now - t > 3600 || (this.data && !ids.has(id)) || (at && at > t + 120 && ids.has(id))) { delete a[id]; changed = true; }
    });
    if (changed) this.saveAnswered();
    return new Set(Object.keys(a));
  }

  markAnswered(cid) {
    this.answeredCases(this.brain().cases);
    this._answered[cid] = Date.now() / 1000;
    this.saveAnswered();
    this._placed = null; this._salDirty = true; this._forceApply = true; this.schedule();
  }

  saveAnswered() { try { localStorage.setItem('morph.answered', JSON.stringify(this._answered || {})); } catch (e) { /* storage refused: for this visit only */ } }

  // Whether a room's (or the house's, '__cases') folded cases are open.
  notesOpen(key) { return !!(this.s.notesOpen && this.s.notesOpen[key]); }
  caseById(id) { return this.cases().find((c) => c.id === id) || null; }

  // What brAIn answered to a reply sent from THIS page. Two things a turn
  // can carry that only Morph can act on: a page or Morph change the reply
  // also asked for (`tell`, which brAIn cannot run — Morph's Tell does, once,
  // and only here, where the words were typed), and brAIn's last word on a
  // case the reply ended (`said`: the card has gone, so the sentence is said
  // as it leaves). Read from the published files on every render; a pending
  // reply older than ten minutes is forgotten.
  followReplies() {
    const b = this.brain(); const said = Array.isArray(b.said) ? b.said : [];
    const now = Date.now();
    this._told = this._told || new Set();
    Object.keys(this.s.pending).forEach((cid) => {
      const p = this.s.pending[cid];
      if (!p || typeof p !== 'object' || !p.at || !/^[fhpt]:/.test(cid)) return;
      if (now - p.at > 600000) { delete this.s.pending[cid]; return; }
      const c = this.caseById(cid);
      const turns = (c ? c.thread || [] : said.filter((x) => x.case === cid)).filter((t) => t && t.who !== 'you' && (Number(t.at) || 0) * 1000 >= p.at - 5000);
      turns.forEach((t) => {
        const mark = cid + '@' + t.at;
        if (t.tell && t.tell.text && !this._told.has(mark)) { this._told.add(mark); this.tellDashboard(String(t.tell.text), t.tell.kind === 'code'); }
      });
      if (!c && turns.length) { this.toast(String(turns[turns.length - 1].text || 'Done.')); delete this.s.pending[cid]; }
      else if (c && turns.length) delete this.s.pending[cid];
    });
  }

  // The section a thing on the page belongs in: the section that shows
  // the entity, else the section whose area is the entity's (or `area`).
  secFor(eid, area) {
    const H = this.hass;
    let found = null;
    if (eid) this.eachSection((sec) => { if (!found && !sec.hidden && this.sectionEntities(sec).includes(eid)) found = sec.id; });
    if (found) return found;
    const reg = eid && own(H.entities, eid);
    const a = area || (reg && (reg.area_id || (reg.device_id && own(H.devices, reg.device_id) && own(H.devices, reg.device_id).area_id)));
    if (a) this.eachSection((sec) => { if (!found && !sec.hidden && sec.area === a) found = sec.id; });
    // A section with no `area` set is matched by its title against the
    // area's name, which is how most rooms are written by hand.
    const an = a && own(H.areas, a) && String(own(H.areas, a).name || '').trim().toLowerCase();
    if (!found && an) this.eachSection((sec) => { if (!found && !sec.hidden && !sec.area && String(sec.title || '').trim().toLowerCase() === an) found = sec.id; });
    return found;
  }

  // Every case with the section it is drawn in (`_sec`; '__cases' is the
  // house-wide section on the first floor). A case about the house, or
  // about a thing on no section, is house-wide.
  casesPlaced() {
    // brAIn's cases are never drawn on the page: they live in brAIn's own
    // Needs you, with the To Do list.
    return [];
  }

  // What dashboard.yaml says that Morph could not use. A file that does not
  // parse leaves the last good dashboard on screen (`held`), so this line is
  // the only sign the file on disk is not what you are looking at.
  problemsHtml() {
    const m = (this.data && this.data.mirror) || {};
    const list = (m.problems || []).slice(0, 4);
    return this.codeProblemsHtml() + (list.length ? this.yamlProblemsHtml(m, list) : '');
  }

  // A change to Morph's own code that did not load (boot.js fell back), or
  // that an update paused. Both say what is running and offer the fix.
  codeProblemsHtml() {
    const out = [];
    const note = (head, body, acts) => `<div class="note" style="margin-bottom:12px;background:${mix('var(--amber)', 9)};box-shadow:inset 0 0 0 1px ${mix('var(--amber)', 25)}"><span class="small" style="color:var(--amber);font-weight:700">${esc(head)}</span>${body ? `<span class="sm">${esc(body)}</span>` : ''}${acts ? `<div class="acts">${acts}</div>` : ''}</div>`;
    if (window.__morphFallback) out.push(note('A change to Morph itself did not load, so Morph is running its own copy.', window.__morphFallback, '<button type="button" class="wd strong" data-act="brain-open" data-v="dashboard">See the changes</button>'));
    const st = (this.data && this.data.state) || {};
    const paused = (st.code || []).filter((r) => r.status === 'paused').map((r) => r.name);
    const why = (name) => pausedWhy((st.code || []).find((r) => r.name === name));
    // The two choices an update leaves, in two words and one line: Update
    // merges this house's changes into the new version (every paused copy
    // in one press), Not now keeps Morph's own running and the copies
    // paused for later. Owner: the old wording about telling Morph to keep
    // things did not say what either press did.
    const choice = (act, v, key) => `<button type="button" class="wd go" data-act="${act}" data-v="${esc(v)}">Update</button><button type="button" class="wd" data-act="code-not-now" data-v="${esc(key)}">Not now</button><span class="small">Update merges your changes into the new version. Not now keeps Morph’s own version running; your changes stay paused and you can update them later from this note.</span>`;
    // brAIn's box opens HERE, and the note stays until the box is closed:
    // once brAIn has written the copy it is no longer paused, and a note
    // that vanished with the box in it took the result with it.
    const t = this.s.tell;
    const mine = t && t.kind === 'code' ? t.id : '';
    const phaseOf = () => (t.state || {}).phase;
    if (mine === 'all') {
      const ph = phaseOf();
      const asks = ph === 'done' && t.state.question && t.state.answered == null;
      const head = asks ? 'brAIn needs you to choose how to bring one of your changes onto the new version.' : ph === 'done' ? 'Your changes to Morph' : ph === 'failed' ? 'Your changes to Morph are still paused.' : 'brAIn is updating your changes to Morph.';
      out.push(note(head, asks ? 'The update rewrote the part that change was in. It stays paused, and Morph’s own keeps running, until you pick; the rest of the update carries on after.' : ph === 'done' || ph === 'failed' ? '' : 'Morph’s own keeps running until it is done. You can leave this page; it carries on.', this.tellBox('code', 'all')));
      return out.join('');
    }
    const all = (st.activity || []).find((a) => a.kind === 'code' && a.target === 'all' && !['done', 'failed'].includes((this.tellStatus[a.id] || {}).phase));
    if (all) {
      out.push(note('brAIn is updating your changes to Morph.', 'Morph’s own keeps running until it is done.', `<button type="button" class="wd go" data-act="activity-open" data-v="${esc(all.id)}">Show</button>`));
      return out.join('');
    }
    const names = paused.slice(0, 6);
    if (mine && !names.includes(mine)) names.push(mine);
    const rest = [];
    names.forEach((name) => {
      if (name === mine) {
        const ph = phaseOf();
        const asks = ph === 'done' && t.state.question && t.state.answered == null;
        const head = asks ? `brAIn needs you to choose how to bring your change to Morph’s ${name} onto the new version.` : ph === 'done' ? `Your change to Morph’s ${name}` : ph === 'failed' ? `Your change to Morph’s ${name} is still paused.` : `brAIn is updating your change to Morph’s ${name}.`;
        out.push(note(head, asks ? 'The update rewrote the part your change was in. It stays paused, and Morph’s own keeps running, until you pick.' : ph === 'done' || ph === 'failed' ? '' : 'Morph’s own keeps running until it is done. You can leave this page; it carries on.', this.tellBox('code', name)));
        return;
      }
      const running = (st.activity || []).find((a) => a.kind === 'code' && a.target === name && !['done', 'failed'].includes((this.tellStatus[a.id] || {}).phase));
      if (running) {
        out.push(note(`brAIn is updating your change to Morph’s ${name}.`, 'Morph’s own keeps running until it is done.', `<button type="button" class="wd go" data-act="activity-open" data-v="${esc(running.id)}">Show</button>`));
        return;
      }
      rest.push(name);
    });
    if (!rest.length) return out.join('');
    // The press is remembered in state, not written onto the button: the
    // panel redraws on every state change in the house, and a button
    // edited in place was back to Update before anyone saw it.
    const key = rest.join(',');
    const r = this.s.redo && this.s.redo.name === (rest.length > 1 ? 'all' : rest[0]) ? this.s.redo : null;
    const head = rest.length > 1 ? `Morph was updated, so ${rest.length} of your changes to it are paused: ${rest.join(', ')}.` : `Morph was updated, so your change to its ${rest[0]} is paused.`;
    const body = rest.length > 1 ? 'Morph’s own versions are running until they are updated.' : why(rest[0]);
    if (r && !r.error) {
      out.push(note(head, body, `<div class="working"><span class="pulse"></span><span>Handing it to brAIn…</span><span class="small" data-since="${r.at}"></span></div>`));
      return out.join('');
    }
    if (!r && this.notNow === key) return out.join('');
    const failed = r && r.error ? `<p class="sm" style="color:var(--rose);margin:0">brAIn did not start: ${esc(r.error)}</p>` : '';
    out.push(note(head, body, failed + choice(rest.length > 1 ? 'code-merge-all' : 'code-redo', rest.length > 1 ? 'all' : rest[0], key)));
    return out.join('');
  }

  yamlProblemsHtml(m, list) {
    const color = m.held ? 'var(--rose)' : 'var(--amber)';
    const head = m.held ? 'dashboard.yaml could not be read, so this is the last version that could.' : 'Some of dashboard.yaml was skipped.';
    return `<div class="note" style="margin-bottom:12px;background:${mix(color, 9)};box-shadow:inset 0 0 0 1px ${mix(color, 25)}"><span class="small" style="color:${color};font-weight:700">${esc(head)}</span>${list.map((p) => `<span class="sm" style="display:block">${esc(p)}</span>`).join('')}</div>`;
  }

  // ---------------------------------------------------------------- board

  eachSection(fn) { (this.dash && this.dash.floors || []).forEach((fl, fi) => (fl.sections || []).forEach((sec) => fn(sec, fl, fi))); }
  sectionCards(sec) { const out = []; (sec.groups || []).forEach((g) => (g.cards || []).forEach((c) => out.push(c))); return out; }

  sectionEntities(sec) {
    // Asked for many times a render (header, story, chips); worked out once a render.
    const memo = this._seMemo && this._seMemo.get(sec); if (memo) return memo;
    const out = [];
    this.sectionCards(sec).forEach((c) => {
      if (c.entity) out.push(c.entity);
      (c.entities || []).forEach((e) => out.push(typeof e === 'string' ? e : (e && e.entity) || ''));
      if ((c.type === 'light_group' || c.type === 'cover_group' || c.type === 'fan_group') && this.hass.states[c.entity]) (this.hass.states[c.entity].attributes.entity_id || []).forEach((e) => out.push(e));
      // A hosted Lovelace card or a custom card type carries its entities
      // in its own config, in whatever shape it likes; every string in it
      // that names an entity Home Assistant has is one this room shows.
      // Without it a case about the thermostat in a hosted card was placed
      // as if the room did not show it.
      if (!BUILT_IN.has(c.type)) entityIdsIn(c.card || c, this.hass.states, out, 0);
    });
    this.headItems(sec).forEach((h) => out.push(h.entity));
    const done = [...new Set(out.filter(Boolean))];
    if (this._seMemo && Object.keys(this.hass.states || {}).length) this._seMemo.set(sec, done);
    return done;
  }
  floorEntities(fl) { const out = []; (fl.sections || []).forEach((s) => this.sectionEntities(s).forEach((e) => out.push(e))); return out; }
  onDash(eid) {
    if (!this._onDash || this._onDashRev !== this.revision) {
      this._onDash = new Set(); this._onDashRev = this.revision;
      this.eachSection((s) => this.sectionEntities(s).forEach((e) => this._onDash.add(e)));
    }
    return this._onDash.has(eid);
  }

  findCard(id) {
    let hit = null;
    this.eachSection((sec, fl) => (sec.groups || []).forEach((g, gi) => (g.cards || []).forEach((c, ci) => { if (c.id === id) hit = { card: c, sec, fl, g, gi, ci }; })));
    return hit;
  }

  cardName(card, sec) {
    if (card.name) return card.name;
    if (card.entity) {
      const full = friendly(this.hass, card.entity);
      const short = shortName(full, sec.title);
      if (short === full) return full;
      // Two cards in one section must not read the same: where another card
      // here would show this shortened name too, both keep their full names.
      const clash = this.sectionCards(sec).some((c) => c !== card && c.entity && c.entity !== card.entity
        && String(c.name || shortName(friendly(this.hass, c.entity), sec.title)).toLowerCase() === short.toLowerCase());
      return clash ? full : short;
    }
    if (card.type === 'lovelace') return (card.card && (card.card.title || card.card.name)) || 'Card';
    return card.type;
  }

  // A room is asleep when its mode says so: a select set to Sleep, a sleep
  // switch or sensor that is on, or a sensor reading asleep. A switch whose
  // name says sleep but names a DEVICE is a control used at night — "Sleeping
  // headphones fan" turned on is a fan running, not a room asleep — and
  // reading it as one put the whole house into its evening. The room's own
  // sleep sensors are often not on the dashboard, so the entities in the
  // room's area are read too. The time is when it went to sleep.
  asleepSince(sec) {
    const H = this.hass;
    const ents = new Set(this.sectionEntities(sec));
    this.areaEntities(sec).forEach((e) => ents.add(e));
    // A room with its own sleep tracker ("In bed" / "Up")
    // is asleep only when the tracker says so. Its mode left on night or a
    // nightlight's "Sleep Sync" switch held children's rooms asleep all
    // morning (house change, Oct 2026).
    let tracked = false;
    for (const e of ents) {
      const s = H.states[e]; if (!s) continue;
      const t = sal.sleepTracker(e, s);
      if (t === 'asleep') return s.last_changed;
      if (t === 'awake') tracked = true;
    }
    if (tracked) return null;
    for (const e of ents) {
      const s = H.states[e]; if (!s) continue;
      if (sal.sleepSignal(e, s)) return s.last_changed;
    }
    return null;
  }

  // Whether this room has anything that could say it is asleep at all.
  canSleep(sec) {
    const H = this.hass;
    const ents = new Set(this.sectionEntities(sec)); this.areaEntities(sec).forEach((e) => ents.add(e));
    for (const e of ents) {
      const st = H.states[e]; if (!st) continue;
      const d = domainOf(e);
      if (d.endsWith('select')) { if ((st.attributes.options || []).some((o) => /^(sleep|sleeping|asleep|night)$/i.test(o))) return true; continue; }
      if (sal.sleepSignal(e, { ...st, state: d === 'sensor' ? 'asleep' : 'on' })) return true;
    }
    return false;
  }

  // Every entity Home Assistant places in this room's area (its own area,
  // or its device's), for the signals a room carries that nobody put on
  // the page. Cached per revision and per registry, because it is asked of
  // every room on every render.
  areaEntities(sec) {
    const H = this.hass;
    if (!sec || !sec.area || !H.entities) return [];
    if (!this._areaEnts || this._areaEntsKey !== H.entities || this._areaEntsDev !== H.devices) {
      // A Map, never an object: an area id is somebody's text, and one
      // called "constructor" or "toString" read Object.prototype's function
      // back and took salience down (#332).
      const by = new Map();
      Object.values(H.entities).forEach((r) => {
        if (!r || !r.entity_id || r.hidden || r.disabled_by) return;
        const a = r.area_id || (r.device_id && own(H.devices, r.device_id) && own(H.devices, r.device_id).area_id);
        if (typeof a !== 'string' || !a) return;
        if (!by.has(a)) by.set(a, []);
        by.get(a).push(r.entity_id);
      });
      this._areaEnts = by; this._areaEntsKey = H.entities; this._areaEntsDev = H.devices;
    }
    return this._areaEnts.get(String(sec.area)) || [];
  }

  // Somebody in the room, read off its motion, occupancy and presence
  // sensors; null when the room has none.
  presence(sec) {
    const H = this.hass;
    const ss = this.sectionEntities(sec).map((e) => H.states[e]).filter((s) => s && domainOf(s.entity_id) === 'binary_sensor' && ['motion', 'occupancy', 'presence'].includes(s.attributes.device_class) && !UNAVAILABLE.includes(s.state));
    if (!ss.length) return null;
    return ss.some((s) => s.state === 'on');
  }

  whenMet(w) {
    const st = w && w.entity && this.hass.states[w.entity];
    if (!st) return false;
    const want = [].concat(w.state == null ? [] : w.state).map(String);
    const not = [].concat(w.state_not == null ? [] : w.state_not).map(String);
    return (!want.length || want.includes(st.state)) && !not.includes(st.state);
  }

  // A room's state (§6): attention, asleep, occupied or active. Rooms never
  // fold: every room always shows all of its cards.
  // A room's state, and a room whose state throws (a copy of this file
  // with a mistake in it, a card's data no code expected) is drawn as a
  // line saying so rather than taking the page down with it (#344).
  roomState(sec) {
    try { return this.roomStateOf(sec); } catch (e) { this.roomFault(sec, e); return 'active'; }
  }

  // One room that could not be built or drawn: remembered for this render
  // so the room says so, and reported through Morph's fault ledger once
  // per page (`report` → errors.jsonl → devloop.note_fault).
  roomFault(sec, e) {
    const id = sec && sec.id != null ? String(sec.id) : '';
    if (!this._roomFaults) this._roomFaults = new Map();
    if (!this._roomFaults.has(id)) this._roomFaults.set(id, String((e && e.message) || e || 'unknown error'));
    const said = `${(e && e.name) || 'Error'}: ${String((e && e.message) || e || 'unknown error')}`;
    this.report('panel', `A room could not be drawn: ${said}`, `${id}: ${String((e && e.stack) || said)}`);
  }

  roomStateOf(sec) {
    if (this.s.edit) return 'active';
    const res = this.salApplied;
    const items = res ? Object.values(res.items).filter((x) => x.sec === sec.id) : [];
    const attention = items.some((x) => ['now', 'lead'].includes(x.band) && !x.twin && x.inp && (x.inp.u > 0 || (x.night && x.open) || x.inp.d >= 0.5) && !res.now.includes(x.id))
      || items.some((x) => x.isCase && ['now', 'lead'].includes(x.band) && x.color === 'var(--rose)');
    if (attention) return 'attention';
    if (this.asleepSince(sec)) return 'asleep';
    return this.presence(sec) ? 'occupied' : 'active';
  }

  // The floors in the order the list puts them, and the rooms in each,
  // from the ROOM SCORE (§4.2: the max of its items, plus 0.1 occupied)
  // read through the bands. A room keeps its place in its floor unless it
  // is two full bands above folded — leading or Now, or needing attention
  // (§4.4's anchor rule for rooms); four fixed buckets with "occupied" as
  // one of them sent every room somebody walked into to the top of every
  // device.
  // Read from the APPLIED list, so it moves only when quiet.
  // House change, Oct 2026: floors and rooms always keep the order the
  // dashboard gives them. Several people use this page and learn where
  // things are; nothing moves because of motion, presence or a score.
  orderedFloors(dash) {
    return (dash.floors || []).map((fl, fi) => ({ fl, fi, secs: fl.sections || [], r: 0 }));
  }

  // The board's grid is twice as fine as a section's width (house change):
  // strip cards (lights, switches, fans, blinds, locks, buttons) take half
  // a column, so a row holds twice as many; everything else keeps its size.
  itemOf(c) {
    // An alarm shown as one switch (options.toggle) is a strip like any switch:
    // half a column, sized and resized the way switches are (house change).
    const t = c.type === 'alarm' && c.options && c.options.toggle ? { span: 1, grow: 2, dir: 'side', want: 3, hk: 's' } : typeOf(c).item;
    // A custom card can ask to start small (card: compact: true): it sits among the
    // compact tiles and, when it asks to open, takes its section's whole width (house change).
    const small = c.type === 'lovelace' && !!(c.card && c.card.compact);
    // A control is one column, always: a span on it is ignored (the one width
    // rule, household, Oct 2026).
    const compact = t.hk === 's' || small;
    // Light and blind groups are compact too: half a column, like a single light.
    const span = compact ? 1 : (c.span || t.span) * 2;
    if (small) return { id: c.id, span: 1, grow: 2, dir: 'side', want: 999, full: false, soft: false, compact: true, hk: 'cc:' + c.card.type };
    // A card with a detail (a thermostat's HVAC performance) opens across its
    // whole section, so the air path and charts get room (house change).
    const wide = !!(c.options && c.options.detail && typeof c.options.detail === 'object');
    return { id: c.id, span, grow: Math.max(span, (compact ? (t.span || 1) * 2 : Math.max(c.span || 0, t.grow || t.span) * 2)), dir: wide ? 'side' : t.dir, want: wide ? 999 : (t.want || 2) * 2, full: !!t.full, soft: !!t.soft, compact, hk: t.hk || 'x:' + c.id };
  }
  // The model the engine lays out: sections with groups of items, each item
  // carrying its type's layout parameters. Floor -1 is the Now band: no
  // heading, no border, the lifted cards (moved out of their rooms). The
  // first floor also carries the house-wide cases and To Do, each a
  // section only while it holds something.
  // A floor's first section that holds nothing but scenes ("Downstairs":
  // Morning, Bright…) is drawn in the floor's own heading instead of as a
  // strip of its own under a title that says the same word (Oct 2026). A
  // floor drawn without a heading keeps it as a section.
  floorScenesSec(fl) {
    if (this.s.edit || fl.heading === false || (this.dash && (this.dash.floors || []).length === 1)) return null;
    const sec = (fl.sections || [])[0];
    if (!sec || sec.hidden) return null;
    const cards = this.sectionCards(sec);
    return cards.length && cards.every((c) => c.type === 'scenes') ? sec : null;
  }

  buildModel(dash) {
    const sections = [];
    const res = this.salApplied;
    // Nothing is lifted out of its room into a Now band (house change, Oct 2026).
    const lifted = new Set();
    const placed = this.casesPlaced();
    const floors = this.orderedFloors(dash);
    this._floorsOrdered = floors;
    if (lifted.size) {
      const items = [...lifted].map((id) => {
        if (id.startsWith('k:')) return { id, span: 4, grow: 6, dir: 'down', want: 6, hk: 'now' };
        const hit = this.findCard(id); if (!hit) return null;
        const it = this.itemOf(hit.card);
        // Lifted cards share one row kind, so a lone one is its own size
        // (a lock is two columns, not a banner across the page).
        return { ...it, hk: 'now', full: false, grow: Math.max(4, it.span) };
      }).filter(Boolean);
      if (items.length) sections.push({ id: '__now', w: 99, floor: -1, floorId: '__now', groups: [{ key: '__now:0', label: '', items }] });
    }
    floors.forEach((F, rank) => {
      const fl = F.fl;
      // The findings and To Do rows sit under the floor's first section, so
      // Now is the top card under Coming up (household, Oct 2026).
      const behind = [];
      let flushed = false;
      const flush = () => { if (!flushed) { flushed = true; behind.forEach((x) => sections.push(x)); } };
      F.secs.forEach((sec, si) => {
        if (si === 1) flush();
        if (sec.hidden && !this.s.edit) return;
        if (this.floorScenesSec(fl) === sec) return; // its scenes ride in the floor heading
        try { this.modelSection(sec, fl, rank, lifted, placed, res, sections); } catch (e) {
          this.roomFault(sec, e);
          sections.push({ id: sec.id, w: (sec.width || 2) * 2, floor: rank, floorId: fl.id, groups: [] });
        }
      });
      flush();
      if (this.s.edit) sections.push({ id: '__new@' + rank, w: 4, floor: rank, floorId: fl.id, groups: [] });
    });
    return { sections };
  }

  // One room's part of the model. Its own function so a room that throws
  // is caught by itself (buildModel) and the rest of the house still draws.
  modelSection(sec, fl, rank, lifted, placed, res, sections) {
    const groups = [];
    const state = this.roomState(sec);
    // Rooms never fold: every room shows all of its cards.
    (sec.groups || []).forEach((g, gi) => {
      // A group with `when: {entity, state}` shows only while that entity is
      // in one of those states (Edit always shows it) (house change).
      if (g.when && !this.s.edit && !this.whenMet(g.when)) return;
      // The add-on drops a group's `when`, so a card may carry it as
      // `options.when` instead; a group whose cards are all hidden goes too.
      const shown = (c) => this.s.edit || !(c.options && c.options.when) || this.whenMet(c.options.when);
      let cards = (g.cards || []).filter((c) => !lifted.has(c.id) && !this.isHeadCard(c) && shown(c));
      // Cards keep their configured order (house change, Oct 2026).
      // A card that leads its room carries a because line, so it is a
      // row of its own kind: beside plain strips of its type it was a
      // row of two heights (the engine's §5 rule).
      const items = cards.map((c) => { const it = this.itemOf(c); return this.leadsWithReason(c.id) ? { ...it, hk: it.hk + ':lead' } : it; });
      if (this.s.edit && gi === sec.groups.length - 1) items.push({ id: `add@${sec.id}@${gi}`, span: 2, grow: 2, dir: 'down', want: 6, hk: 'x:add' });
      if (!items.length) return; // a group that only carried title-row cards, or whose cards were lifted
      groups.push({ key: sec.id + ':' + gi, label: g.label || '', items });
    });
    if (this.s.edit && !(sec.groups || []).length) groups.push({ key: sec.id + ':new', label: '', items: [{ id: `add@${sec.id}@0`, span: 2, grow: 2, dir: 'down', want: 6, hk: 'x:add' }] });
    sections.push({ id: sec.id, w: (sec.width || 2) * 2, floor: rank, floorId: fl.id, groups });
  }

  renderBoard(dash) {
    const board = this.$('[data-board]');
    // brAIn's cases are placed in the rooms they are about.
    const model = this.buildModel(dash);
    this._modelStamp = (this._modelStamp || 0) + 1;
    this.engine.model = model;
    // A compact tile being slid widens in place (house change): the engine
    // treats it as a light kind of "open" that never shows more content.
    this.engine.openId = this.s.view ? this.s.view.id : this.s.slideWide || null;
    this.engine.openMode = this.s.view ? this.s.view.mode : this.s.slideWide ? 'slide' : '';
    // A tile that already took its own row keeps it while it is slid again.
    this.engine.slideHeld = !!(this.s.slideWide && this.ptr && this.ptr.drag && this.ptr.id === this.s.slideWide);
    this.engine.fadingId = this.s.fading;
    const want = new Set();
    const floors = this._floorsOrdered || [];
    // A one-floor dashboard has no floor heading at all; a floor may turn
    // its own off (`heading: false`).
    const oneFloor = floors.length === 1;
    this.engine.floorHead = { '-1': 0 };
    floors.forEach((F, rank) => {
      const fl = F.fl;
      const key = 'fl:' + fl.id; want.add(key);
      let el = board.querySelector(`[data-fid="${CSS.escape(fl.id)}"]`);
      if (!el) { el = document.createElement('div'); el.className = 'flh'; el.dataset.fid = fl.id; el.dataset.key = key; el.dataset.hold = 'floor:' + fl.id; board.appendChild(el); }
      el.setAttribute('data-floor', String(rank));
      const headless = (oneFloor || fl.heading === false) && !this.s.edit;
      if (headless) this.engine.floorHead[String(rank)] = 0;
      el.style.background = this.s.hold === 'top:floor:' + fl.id ? mix('var(--violet)', 9) : 'transparent';
      const fs = headless ? null : this.floorScenesSec(fl); const fsc = fs && this.sectionCards(fs).find((c) => c.type === 'scenes');
      const fscenes = fsc ? this.secScenesHtml({ ...fs, title: fl.title }, fsc.entities || []).replace('class="secscenes"', 'class="secscenes flsc"') : '';
      const rooms = ''; // no room words under a floor: the scrub rail moves the page (house change, Oct 2026)
      const html = headless ? '<div data-flin="1"></div>' : `<div data-flin="1"><div class="flrow"><h2>${esc(fl.title)}</h2>${fscenes}<span class="flr"></span></div>${rooms ? `<div class="flrooms">${rooms}</div>` : ''}${this.tellBox('floor', fl.id)}</div>`;
      this.setHtml(el, html);
    });
    // sections
    model.sections.forEach((ms) => {
      const sec = this.sectionById(ms.id);
      const key = 'sec:' + ms.id; want.add(key);
      let el = board.querySelector(`[data-sec="${CSS.escape(ms.id)}"]`);
      if (!el) {
        el = document.createElement('section'); el.className = 'sec'; el.setAttribute('data-sec', ms.id); el.dataset.key = key;
        el.innerHTML = `<div class="secbg"></div><div class="sechead" data-sec-head="${esc(ms.id)}"></div>`;
        board.appendChild(el);
      }
      el.classList.toggle('nowband', ms.id === '__now');
      el.classList.toggle('folded', !!ms.folded);
      // A section holding one card is that card: no room box or heading around
      // it, so a card never sits inside a box of its own (house change, Oct 2026:
      // "If a section has one card, it should just be one card"). Edit keeps the box.
      // Counted from what is drawn, so a card hidden by its `when` does not count.
      // A room (a section with an `area`) always keeps its box and name, even
      // round one light card (house change, Oct 2026: "inside of another section
      // that says the room like the other rooms").
      const soloIds = sec && !sec.area && !this.s.edit ? ms.groups.flatMap((g) => g.items.map((it) => it.id)) : [];
      const solo = soloIds.length === 1 ? this.sectionCards(sec).find((c) => c.id === soloIds[0]) : null;
      el.classList.toggle('solo', !!solo);
      el.classList.toggle('solo-lv', !!solo && solo.type === 'lovelace');
      const headEl = el.querySelector('.sechead');
      if (ms.id === '__now' || ms.id === '__cases' || ms.id === '__todo') {
        el.querySelector('.secbg').style.cssText = ms.id === '__now' ? 'background:transparent' : 'background:var(--surface)';
        el.setAttribute('aria-label', ms.id === '__now' ? 'Now' : ms.id === '__todo' ? 'To Do' : 'For the whole house');
        headEl.classList.toggle('nohead', ms.id !== '__todo');
        this.setHtml(headEl, ms.id === '__todo' ? '<div style="flex:1;min-width:0;display:flex;align-items:baseline;gap:12px"><h2>To Do</h2></div>' : '');
      } else if (!sec) { // the ghost "Add section" in Edit
        el.querySelector('.secbg').style.cssText = 'background:transparent;box-shadow:inset 0 0 0 1.5px var(--line2)';
        headEl.classList.remove('nohead');
        this.setHtml(headEl, `<button type="button" class="go" data-act="add-section" data-v="${esc(ms.floorId)}" style="display:inline-flex;align-items:center;gap:8px;font-size:16px;color:var(--muted)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>Add section</button>`);
        el.setAttribute('aria-label', 'Add section');
      } else if (this._roomFaults && this._roomFaults.has(String(sec.id))) {
        this.paintBroken(el, sec, ms);
        return;
      } else {
        headEl.classList.remove('nohead');
        try {
          this.paintSection(el, sec, ms);
        } catch (e) {
          this.roomFault(sec, e);
          this.paintBroken(el, sec, ms);
          return;
        }
      }
      // groups
      try {
        ms.groups.forEach((g) => {
          const gk = g.key; want.add('g:' + gk);
          let gl = el.querySelector(`[data-glab="${CSS.escape(gk)}"]`);
          if (g.label && sec) {
            if (!gl) { gl = document.createElement('div'); gl.className = 'glab'; gl.setAttribute('data-glab', gk); gl.dataset.key = 'g:' + gk; el.appendChild(gl); }
            gl.style.color = mix(hue(sec.color), 55, 'var(--text)');
            const grp = (sec.groups || [])[Number(gk.split(':').pop())];
            this.setHtml(gl, `<span>${esc(g.label)}</span>${grp && grp.note ? `<i>${esc(grp.note)}</i>` : ''}`);
          } else if (gl) gl.remove();
          g.items.forEach((it) => { want.add('t:' + it.id); this.renderTile(el, it, sec, ms); });
        });
      } catch (e) {
        if (!sec) throw e;
        this.roomFault(sec, e);
        this.paintBroken(el, sec, ms);
      }
    });
    // remove what is no longer there
    // Only the board's own bookkeeping keys: a control inside a card may
    // carry a data-key of its own (a range's attribute name), and it is not
    // the board's to remove.
    board.querySelectorAll('[data-key]').forEach((el) => {
      if (/^(fl|sec|g|t):/.test(el.dataset.key) && !want.has(el.dataset.key)) {
        if (el.dataset.key.startsWith('t:')) this.llCards.delete(el.dataset.key.slice(2));
        if (this._llRo) el.querySelectorAll('[data-ll]').forEach((sl) => { if (sl.__llObserved) { sl.__llObserved = false; this._llRo.unobserve(sl); } });
        el.remove();
      }
    });
    const away = this._awaySnap; this._awaySnap = null;
    this.engine.layout(!this._laidOut || !!away, false);
    this._laidOut = true;
    if (this.rail) this.rail.paint();
    // A card that closed above the screen gave its height back: move the
    // scroll by exactly what the first card in view moved, so nothing on
    // screen shifts under the person (house change).
    if (away && away.el && away.el.isConnected) {
      const dy = away.el.getBoundingClientRect().top - away.y;
      if (Math.abs(dy) > 0.5) { const sc = this.engine.scroller(); if (sc) sc.scrollTop += dy; else window.scrollBy(0, dy); }
    }
  }

  // An opened card that has scrolled well out of view closes by itself. One
  // above the screen closes at once (no spring, no fade) with the scroll
  // corrected; one below just closes, since nothing in view depends on it.
  onScrollAway() {
    if (this._awayRaf) return;
    this._awayRaf = requestAnimationFrame(() => {
      this._awayRaf = 0;
      const v = this.s.view;
      const wideId = !v && this.s.slideWide && !(this.ptr && this.ptr.drag) ? this.s.slideWide : null;
      if (!wideId && (!v || this.s.edit || v.mode !== 'adv' || this.s.tell)) return;
      const tile = this.shadowRoot.querySelector(`[data-tile="${CSS.escape(wideId || v.id)}"]`); if (!tile) return;
      const sc = this.engine.scroller();
      const vt = sc ? sc.getBoundingClientRect().top : 0, vb = sc ? sc.getBoundingClientRect().bottom : window.innerHeight;
      const r = tile.getBoundingClientRect();
      const above = r.bottom < vt - 40, below = r.top > vb + 40;
      if (!above && !below) return;
      if (above) {
        // Anchor on the column the card lived in (on a wide board only that
        // column moves; on a phone there is one column and this is exact).
        const secEl = tile.closest('[data-sec]'); const sr = secEl ? secEl.getBoundingClientRect() : r;
        let anchor = null, ay = Infinity, fb = null, fy = Infinity;
        this.shadowRoot.querySelectorAll('[data-tile]').forEach((el) => {
          if (el === tile) return;
          const b = el.getBoundingClientRect(); const t = b.top;
          if (t < vt || t >= vb) return;
          const sameCol = b.left < sr.right - 1 && b.right > sr.left + 1;
          if (sameCol && t < ay) { ay = t; anchor = el; }
          if (t < fy) { fy = t; fb = el; }
        });
        if (!anchor) { anchor = fb; ay = fy; }
        this._awaySnap = { el: anchor, y: ay };
      }
      if (wideId) { clearTimeout(this._slideT); this.s.slideWide = null; this.schedule(); return; }
      this.closeView();
      if (above) { clearTimeout(this._fadeT); this.s.fading = null; }
    });
  }

  // A room's background, its glow and its state (§6, §9.1): a tint of its
  // own colour at 3% idle, 6% occupied, indigo at 4% asleep; a rose rule
  // down the left edge while it needs attention.
  paintSection(el, sec, ms) {
    el.setAttribute('aria-label', sec.title);
    const h = hue(sec.color);
    const state = this.roomState(sec);
    el.dataset.state = state;
    const quiet = state === 'idle' || state === 'asleep';
    // A folded room's tiles are out of reach of Tab and screen readers.
    el.querySelectorAll(':scope > .tile').forEach((t) => { if (t.inert !== !!ms.folded) t.inert = !!ms.folded; });
    let gc = null, gb = 0;
    if (!quiet) this.sectionEntities(sec).forEach((e) => { const s = this.hass.states[e]; if (s && domainOf(e) === 'light' && s.state === 'on') { const b = (s.attributes.brightness || 255) / 2.55; if (b > gb) { gb = b; gc = lightColor(s); } } });
    const sHold = this.s.hold === 'sec:' + sec.id || (this.s.tell && this.s.tell.kind === 'section' && this.s.tell.id === sec.id);
    const bg = el.querySelector('.secbg');
    // The wash is four registered colours the stylesheet layers and
    // transitions, so a room's glow fades as its lights or its state change
    // instead of snapping; --secK softens it on the light theme (house change, Oct 2026).
    const tk = (c, p) => `color-mix(in oklab, ${c} calc(${p}% * var(--secK, 1)), transparent)`;
    const sv = {
      '--sg': gc ? tk(gc, Math.round(5 + gb * 0.07)) : 'transparent',
      '--s1': quiet ? 'transparent' : tk(h, 11),
      '--s2': quiet ? 'transparent' : tk(h, 6),
      '--s3': state === 'asleep' ? tk('var(--indigo)', 4) : tk(h, state === 'occupied' ? 6 : state === 'idle' ? 3 : 4),
    };
    Object.keys(sv).forEach((k) => { if (bg.style.getPropertyValue(k) !== sv[k]) bg.style.setProperty(k, sv[k]); });
    if (bg.style.background) bg.style.background = '';
    bg.style.boxShadow = sHold ? `inset 0 0 0 2px ${mix('var(--violet)', 60)}` : this.s.edit ? `inset 0 0 0 1px ${mix(h, 40)}` : state === 'attention' ? 'inset 3px 0 0 var(--rose)' : 'none';
    el.style.opacity = sec.hidden ? '0.45' : '1';
    const head = el.querySelector('.sechead');
    head.style.cursor = this.s.edit ? 'grab' : 'auto';
    head.style.touchAction = this.s.edit ? 'none' : 'auto';
    this.setHtml(head, this.secHeadHtml(sec, state));
  }

  // A room that threw while it was built or drawn (#344): its title and one
  // line saying so, its tiles taken away, so it lays out as an empty room
  // and every other room draws as usual. The fault went to the ledger in
  // roomFault.
  paintBroken(el, sec, ms) {
    ms.groups = [];
    el.querySelectorAll('[data-key]').forEach((t) => {
      if (/^(g|t):/.test(t.dataset.key)) {
        if (t.dataset.key.startsWith('t:')) this.llCards.delete(t.dataset.key.slice(2));
        t.remove();
      }
    });
    el.classList.remove('folded', 'solo', 'solo-lv');
    el.setAttribute('aria-label', String(sec.title || ''));
    el.querySelector('.secbg').style.cssText = 'background:var(--surface)';
    const head = el.querySelector('.sechead');
    head.classList.remove('nohead');
    this.setHtml(head, `<div class="secbroken" style="flex:1;min-width:0"><h2>${esc(sec.title || '')}</h2><p class="sm" style="margin:2px 0 0;color:var(--muted)">Morph could not draw this room. The fault has been reported.</p></div>`);
  }

  // The room rail's colour for a room on the board, and a floor's name.
  railColor(id) { const sec = this.sectionById(id); return sec ? mix(hue(sec.color), 80) : 'var(--quiet)'; }
  railFloor(id) { const fl = ((this.dash && this.dash.floors) || []).find((f) => String(f.id) === String(id)); return fl ? String(fl.title || '') : ''; }

  sectionById(id) { let hit = null; this.eachSection((s) => { if (s.id === id) hit = s; }); return hit; }

  // A morph, not a replacement: only what differs changes, so an animation
  // does not restart and a <details> keeps its place (morph-dom.js).
  setHtml(el, html) { html = this.speak(html); if (el.__html !== html) { el.__html = html; morph(el, html, this.shadowRoot); this.restoreTellText(el); if (!this.engine.reduce()) rollDigits(el, !!((this.ptr && this.ptr.drag) || this.mptr || this.hptr || this.s.slideWide || Object.keys(this.s.previews || {}).length || this.s.memberPreview)); } }

  // The words of a room line (§2.6): every room, by state. A dot before a
  // room that needs attention; asleep rooms dimmed; idle ones quiet.
  roomWords(secs, rank) {
    if (this.s.edit) return '';
    return secs.filter((sec) => !sec.hidden).map((sec) => {
      const st = this.roomState(sec);
      return `<button type="button" class="roomw rs-${st}" data-act="room" data-v="${esc(sec.id)}">${st === 'attention' ? '<i class="rdot"></i>' : ''}${esc(sec.title)}</button>`;
    }).join('');
  }


  // Sensors the household put in a room's header (`head:` on the section,
  // entity ids or {entity, name}): a small chip each, rose while open or
  // moving. Tapping one unfolds its day in place under the header; the
  // name there opens Home Assistant's entity dialog (house change).
  // A room's title row carries its scenes and its door/motion chips. Morph's
  // compiler keeps only cards, so these travel as cards: a `scenes` card and a
  // `list` card marked options.header; they are drawn in the title row and
  // never as tiles (house change).
  isHeadCard(c) { return !!c && !this.s.edit && (c.type === 'scenes' || (c.type === 'list' && c.options && c.options.header) || (c.type === 'switch' && c.options && c.options.header)); }
  headCards(sec) { const out = []; (sec.groups || []).forEach((g) => (g.cards || []).forEach((c) => { if (this.isHeadCard(c)) out.push(c); })); return out; }
  headItems(sec) {
    const fromCards = [];
    this.headCards(sec).filter((c) => c.type === 'list').forEach((c) => (c.entities || []).forEach((e) => fromCards.push({ entity: e, name: c.options.names && c.options.names[e] })));
    return (sec.head || []).map((h) => (typeof h === 'string' ? { entity: h } : h)).concat(fromCards).filter((h) => h && h.entity);
  }

  // The card that shows an entity in full in another room of Morph, if any.
  cardShowing(eid, notSec, loose) {
    const q = eid.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(loose ? q : `"${q}"`);
    let hit = null;
    this.eachSection((s) => {
      if (hit || s === notSec || s.hidden) return;
      this.sectionCards(s).forEach((c) => { if (!hit && !this.isHeadCard(c) && re.test(JSON.stringify(c))) hit = { id: c.id, title: s.title }; });
    });
    return hit;
  }

  // On a phone the room line is its own sticky row under the header, for
  // the whole house; on a wider screen the floor headings carry it.
  roomLineHtml(dash) {
    if (this.s.edit) return '';
    const floors = this._floorsOrdered || this.orderedFloors(dash);
    const rows = floors.map((F) => `<span class="rlfloor">${esc(F.fl.title)}</span>${this.roomWords(F.secs)}`).join('');
    return rows ? `<nav class="roomline" aria-label="Rooms">${rows}</nav>` : '';
  }

  secHeadHtml(sec, state) {
    const edit = this.s.edit;
    const open = this.s.secEdit === sec.id;
    const ents = this.sectionEntities(sec);
    const H = this.hass;
    // The room's line: asleep, how warm (and what is usual, when brAIn has
    // measured it), whether anyone is there. What is on is on the tiles.
    // A temperature a card below already shows (a climate card, a sensor's
    // own card) is not repeated beside the title.
    const shown = new Set(); this.sectionCards(sec).forEach((c) => { if (c.entity) shown.add(c.entity); (c.entities || []).forEach((e) => shown.add(e)); });
    const hasClimate = [...shown].some((e) => domainOf(e) === 'climate');
    const temp = hasClimate ? null : ents.map((e) => H.states[e]).find((s) => s && !shown.has(s.entity_id) && s.attributes.device_class === 'temperature' && !isNaN(parseFloat(s.state)));
    const slept = this.asleepSince(sec);
    // The header's own motion chips already say whether anyone is there.
    const chipsSay = this.headItems(sec).some((h) => { const x = H.states[h.entity]; return x && ['motion', 'occupancy', 'presence'].includes(x.attributes.device_class); });
    const here = slept || chipsSay ? null : this.presence(sec);
    const usual = temp && this.feedState().usable ? (((this.brain().feed || {}).normal || {})[temp.entity_id] || {}).now : null;
    const tword = temp ? fmt(temp.state, '°') + (state === 'occupied' && usual ? ` · usually ${fmt(usual[0], '')}` : '') : '';
    const res = this.salApplied;
    const needs = this.casesPlaced().filter((k) => k._sec === sec.id).length;
    const meta = [tword, here == null || slept ? '' : here ? 'someone here' : '', sec.hidden ? 'hidden' : ''].filter(Boolean).join(' · ');
    const because = state === 'attention' && res ? (() => { const x = Object.values(res.items).find((y) => y.sec === sec.id && ['lead', 'now'].includes(y.band) && y.why && !res.now.includes(y.id)); return x ? `<p class="secbecause" style="color:${x.why.color}">${esc(x.why.text)}</p>` : ''; })() : '';
    let editor = '';
    if (edit && open) {
      const floors = (this.dash.floors || []);
      editor = `<div data-ctl="1" class="edit" style="flex-basis:100%;padding:10px 10px 8px 0">
<label class="flab">Title<input class="fld" type="text" data-keep="sec-title" data-act-change="sec-title" data-v="${esc(sec.id)}" value="${esc(sec.title)}"></label>
<div class="flab">Color<div class="hues">${HUES.map((hn) => `<button type="button" class="hue" data-act="sec-hue" data-v="${esc(sec.id)}" data-h="${hn}" aria-label="${hn}" aria-pressed="${sec.color === hn}"><span style="background:var(--${hn});box-shadow:${sec.color === hn ? `0 0 0 3px var(--surface), 0 0 0 5px var(--${hn})` : 'none'}"></span></button>`).join('')}</div></div>
<div class="flab">Floor<div class="row" style="flex-wrap:wrap;gap:0 18px">${floors.map((f) => `<button type="button" class="wd opt" data-act="sec-floor" data-v="${esc(sec.id)}" data-f="${esc(f.id)}" aria-pressed="${f.sections.includes(sec)}">${esc(f.title)}</button>`).join('')}<button type="button" class="wd opt light" data-act="sec-floor-new" data-v="${esc(sec.id)}">New floor…</button></div></div>
<div class="flab">Width<div class="row" style="gap:0 18px">${[[1, 'Narrow'], [2, 'Medium'], [3, 'Wide'], [4, 'Widest']].map((x) => `<button type="button" class="wd opt" data-act="sec-width" data-v="${esc(sec.id)}" data-w="${x[0]}" aria-pressed="${(sec.width || 2) === x[0]}">${x[1]}</button>`).join('')}</div></div>
<div class="flab">Group<div class="row" style="gap:0 18px"><button type="button" class="wd opt light" data-act="sec-group" data-v="${esc(sec.id)}">Add a group</button></div></div>
<div class="row" style="gap:0 18px"><button type="button" class="go barw" data-act="sec-hide" data-v="${esc(sec.id)}">${sec.hidden ? 'Show section' : 'Hide section'}</button><button type="button" class="go barw bad" data-act="sec-remove" data-v="${esc(sec.id)}">Remove section</button></div></div>`;
    }
    const grip = edit ? '<svg aria-hidden="true" width="12" height="18" viewBox="0 0 12 18" style="flex-shrink:0;color:var(--quiet);margin-left:-8px"><path d="M3 3h.01M9 3h.01M3 9h.01M9 9h.01M3 15h.01M9 15h.01" stroke="currentColor" stroke-width="3" stroke-linecap="round"></path></svg>' : '';
    // The room's scenes ride in its title row as words (house change), one
    // tap even when the room is folded.
    const sc = this.headCards(sec).find((c) => c.type === 'scenes');
    // A switch card marked options.header rides in the title row as a pill button (house change, Oct 2026: "Disable yard automations" in the header).
    const tg = !edit && this.headCards(sec).find((c) => c.type === 'switch' && c.entity);
    const tgs = tg && H.states[tg.entity];
    const toggle = tgs ? `<button type="button" class="shtog" data-snap-skip="1" data-act="rmk-svc" data-v="homeassistant.toggle|${esc(tg.entity)}" data-on="${tgs.state === 'on' ? 1 : 0}" aria-pressed="${tgs.state === 'on'}" aria-label="${esc(this.cardName(tg, sec))}">${esc(this.cardName(tg, sec))}</button>` : '';
    const scenes = !edit && ((sec.scenes || []).length || sc) ? this.secScenesHtml(sec, sc ? sc.entities || [] : sec.scenes) : '';
    // Each room's own faint icon before its name, so rooms tell apart at a glance (house change, Oct 2026).
    const ric = sec.icon ? `<ha-icon class="secic" icon="${esc(sec.icon)}" aria-hidden="true" style="color:${mix(hue(sec.color), 45, 'var(--quiet)')}"></ha-icon>` : '';
    const name = edit ? `<h2>${ric}${esc(sec.title)}</h2>` : `<h2 style="position:relative">${ric}${esc(sec.title)}</h2>`;
    // Nothing rides at the right of a room's title line: no door or motion
    // chips and no marks. The scenes sit under it as one segmented control.
    return `${grip}<div class="secline" style="position:relative">${name}<span class="secmeta">${esc(meta)}</span>${needs ? `<span class="needs">${needs} need${needs === 1 ? 's' : ''} you</span>` : ''}${scenes}${toggle}</div>${edit ? '' : this.sleepAskHtml(sec)}${because}${edit ? `<button type="button" class="go barw" data-act="sec-edit" data-v="${esc(sec.id)}" aria-expanded="${open}">${open ? 'Close' : 'Edit'}</button>` : ''}${this.tellBox('section', sec.id)}${editor}`;
  }

  // The scene highlight is one thumb that glides to the scene in use; its
  // place is remembered so a redraw never snaps it back (house change).
  pageIn() {
    const f = this._pageFrom; if (!f || this.engine.reduce()) { this._pageFrom = null; return; }
    this._pageFrom = null;
    const el = f.page === 'settings' ? this.$('[data-region="settings"]') : f.page === 'feed' ? this.$('[data-region="feed"]') : this.$('[data-region="board"]');
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (f.x != null) el.style.transformOrigin = `${Math.round(f.x - r.left)}px ${Math.round(Math.max(0, f.y - r.top))}px`;
    el.animate([{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'none' }], { duration: 420, easing: 'cubic-bezier(.22,1,.36,1)' });
  }

  placeThumbs() {
    this._segPos = this._segPos || {};
    this.shadowRoot.querySelectorAll('.secscenes').forEach((g) => {
      const th = g.querySelector('.segthumb'); if (!th) return;
      const on = g.querySelector('[aria-pressed="true"]'); const key = (g.getAttribute('aria-label') || '').replace(/ scenes$/, '');
      if (!on) { th.classList.remove('on'); delete this._segPos[key]; return; }
      const x = on.offsetLeft, w = on.offsetWidth; if (!w) return;
      const cur = this._segPos[key];
      if (!cur || cur[0] !== x || cur[1] !== w) { this._segPos[key] = [x, w]; g.style.setProperty('--tx', x + 'px'); g.style.setProperty('--tw', w + 'px'); }
      if (!th.classList.contains('on')) requestAnimationFrame(() => th.classList.add('on'));
    });
  }

  secScenesHtml(sec, list) {
    const H = this.hass; const ids = list || sec.scenes || [];
    const cur = currentScene(H, ids);
    // One rule with the scenes card: the prefix they all share goes; scenes
    // from different areas keep the area that tells them apart.
    // The section's own name never repeats in its scenes ("Downstairs - Bright" under Downstairs).
    const own = new RegExp('^' + String(sec.title || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s+[-–]\\s+', 'i');
    const full = (e) => { const st = H.states[e]; const n = String((st && st.attributes.friendly_name) || e.split('.').pop().replace(/_/g, ' ')); return sec.title ? n.replace(own, '') : n; };
    const words = sceneWords(ids.map(full)).map((w, i) => (w === full(ids[i]) && ids.length === 1 ? sceneWord(H, ids[i]) : w));
    const sp = (this._segPos || {})[sec.title] || null;
    return `<span class="secscenes" role="group" aria-label="${esc(sec.title)} scenes" style="--n:${ids.length}${sp ? `;--tx:${sp[0]}px;--tw:${sp[1]}px` : ''}"><i class="segthumb${sp ? ' on' : ''}" aria-hidden="true"></i>${ids.map((e, i) => `<button type="button" class="wd" data-act="scene" data-v="${esc(e)}" aria-pressed="${cur === e}">${esc(words[i])}</button>`).join('')}</span>`;
  }

  renderTile(secEl, it, sec, ms) {
    const id = it.id;
    let el = secEl.querySelector(`[data-tile="${CSS.escape(id)}"]`);
    if (!el) {
      // Lifted into Now, or sent home: the same element, moved, so it
      // travels from where it was (engine.moveTile) rather than appearing.
      const elsewhere = this.$(`[data-tile="${CSS.escape(id)}"]`);
      if (elsewhere) {
        const from = elsewhere.closest('[data-sec]');
        if (from) this.engine.moveTile(id, from.getAttribute('data-sec'));
        el = elsewhere;
      } else {
        el = document.createElement('div'); el.className = 'tile'; el.setAttribute('data-tile', id); el.dataset.key = 't:' + id;
        el.innerHTML = `<div class="mtile" data-mt="${esc(id)}"><div class="tc" data-tc="${esc(id)}"><div class="face" data-face="${esc(id)}"></div><div data-more></div></div></div>`;
      }
      secEl.appendChild(el);
    }
    // A card's detail (options.detail, any Lovelace card) is drawn inside the
    // same tile below its face, e.g. a climate zone's performance card.
    // The tile's own parts are found by position, never by a bare attribute:
    // a custom card drawn in the face may use [data-more] or [data-detail]
    // inside itself (the water card does), and must not be mistaken for them.
    const TC = ':scope > .mtile > .tc > ';
    let detailEl = el.querySelector(TC + '[data-detail]');
    if (!detailEl) { el.querySelector(TC + '[data-more]').insertAdjacentHTML('afterend', `<div data-detail="${esc(id)}" data-ctl="1"></div>`); detailEl = el.querySelector(TC + '[data-detail]'); }
    const mt = el.querySelector(':scope > .mtile');
    const face = el.querySelector(TC + '[data-face]');
    const moreEl = el.querySelector(TC + '[data-more]');
    this.engine.watchSize(face);
    // A case (brAIn's) in place: claim, ask, reply line, the words.
    if (id.startsWith('k:')) {
      const c = this.caseById(id.slice(2));
      const color = caseColor(c);
      mt.style.cssText = `background:${mix(color, 6, 'var(--surface)')};box-shadow:inset 3px 0 0 ${color};cursor:auto;touch-action:auto;user-select:text`;
      const pend = this.s.pending[c ? c.id : ''];
      const pending = pend && c && (c.thread || []).length <= pend.n ? (Date.now() - pend.at > 90000 ? `${this.who()} has not answered yet.` : pend.word || `Sent. ${this.who()} answers here.`) : '';
      if (pend && !pending) delete this.s.pending[c.id];
      const x = this.salOf(id);
      const why = ms && ms.id === '__now' && x.why ? `<p class="because" style="color:${x.why.color}">${esc(x.why.text)}</p>` : '';
      this.setHtml(face, c ? caseFace(c, { pending, replyOpen: !!this.s.replyOpen[c.id], admin: this.admin(), who: this.who(), name: (eid) => (this.hass.states[eid] ? friendly(this.hass, eid) : '') }) + why : '');
      this.setHtml(moreEl, '');
      return;
    }
    // The folded summary of brAIn's cases (and, house-wide, the To Do list).
    if (id.startsWith('kf:')) {
      const key = id.slice(3);
      const ks = this.casesPlaced().filter((k) => k._sec === key);
      const nTodo = 0;
      const open = this.notesOpen(key);
      const color = ks.length ? ks.map(caseColor).find((c) => c === 'var(--rose)') || caseColor(ks[0]) : 'var(--muted)';
      const parts = [];
      if (ks.length) parts.push(`${ks.length} from ${this.who()}`);
      if (nTodo) parts.push(`${nTodo} To Do`);
      mt.style.cssText = 'background:transparent;box-shadow:inset 0 0 0 1px var(--line2);cursor:pointer';
      this.setHtml(face, `<button type="button" class="mnotes-fold" data-act="notes-toggle" data-v="${esc(key)}" aria-expanded="${open}"><span class="mnotes-dot" style="background:${color}"></span><b>${esc(parts.join(' · '))}</b><span class="mnotes-word">${open ? 'Hide' : 'Show'}</span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="transform:rotate(${open ? 180 : 0}deg);transition:transform .3s"><path d="M6 9l6 6 6-6"/></svg></button>`);
      this.setHtml(moreEl, '');
      return;
    }
    // The ghost "Add card" in Edit.
    if (id.startsWith('add@')) {
      const open = this.s.view && this.s.view.id === id;
      mt.style.cssText = `background:${open ? 'var(--surface)' : 'transparent'};box-shadow:inset 0 0 0 1.5px var(--line2);cursor:pointer`;
      this.tileA11y(mt, 'Add card', null, open, false);
      this.setHtml(face, `<div class="sline" style="height:56px;color:var(--muted)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg><b style="font-size:14px">Add card</b></div>`);
      this.setHtml(moreEl, open ? this.addCardHtml(sec, Number(id.split('@')[2])) : '');
      return;
    }
    const hit = this.findCard(id); if (!hit) return;
    const card = hit.card; const T = typeOf(card);
    const hv = this.hass;
    const st = card.entity ? hv.states[card.entity] : null;
    const open = this.s.view && this.s.view.id === id;
    const mode = open ? this.s.view.mode : '';
    const name = this.cardName(card, hit.sec);
    const lifted = ms && ms.id === '__now';
    const x = this.salNow(id);
    const ctx = { hass: hv, card, st, sec: hit.sec, name, open, member: open ? this.s.view.member : null, colour: open ? this.s.view.colour || null : null, spectrum: open ? this.s.view.spectrum || null : null, H: (open && this.s.view.H) || (card.type === 'readings' ? (this.s.rfocus && this.s.rfocus[id] ? { focus: this.s.rfocus[id] } : {}) : {}), preview: this.s.previews[id] != null ? this.s.previews[id] : null, memberPreview: open ? this.s.memberPreview : null, confirm: this.s.confirm[id] && this.s.confirm[id].until > Date.now() ? this.s.confirm[id].text : '', night: this.salApplied && this.salApplied.period === 'night' };
    let faceHtml = '', moreHtml = '';
    try {
      ctx.accent = card.color ? hue(card.color) : T.accent(ctx);
      const slide = !this.s.edit && T.slide ? T.slide(ctx) : null;
      ctx.hint = this.s.edit ? (open ? '' : `tap to edit · hold to tell ${this.who()}`) : (open || T.noOpen) ? '' : slide ? 'slide · tap · hold to open' : T.tap(ctx) ? 'tap · hold to open' : 'tap to open';
      faceHtml = T.face(ctx);
      // The because line (§11): one sentence, in the item's meaning colour,
      // on a card the list lifted or put at the top of its room. Hold it to
      // ask brAIn why.
      // Whether it leads is the APPLIED list's word (the row it sits in was
      // laid out from it, `leadsWithReason`); what it says is the newest.
      if (!this.s.edit && x.why && (lifted || this.leadsWithReason(id)) && x.why.kind !== 'none') faceHtml += `<p class="because" data-why="${esc(id)}" style="color:${x.why.color}">${esc(x.why.text)}</p>`;
      else if (lifted && x.why) faceHtml += `<p class="because" data-why="${esc(id)}" style="color:${x.why.color}">${esc(x.why.text)}</p>`;
      if (open && mode === 'adv') moreHtml = `<div class="more rise" data-ctl-scope="1">${this.keepHtml(card, lifted || x.band === 'lead')}${T.more(ctx)}${T.host ? '' : this.moreInfoHtml(card, ctx)}</div>`;
      if (open && mode === 'edit') moreHtml = this.cardEditHtml(hit, name);
      // While brAIn is being told about a card, the card stays OPENED above
      // the Tell box, so the picture brAIn gets (and the person sees) is the
      // expanded card, not just its face (house change).
      if (open && mode === 'tell') moreHtml = `<div class="more">${T.noOpen ? '' : `<div data-ctl-scope="1">${T.more(ctx)}</div>`}${this.tellBox('card', id)}</div>`;
    } catch (e) {
      faceHtml = `<div class="box"><b>${esc(name)}</b><span class="sm">This card could not be drawn.</span></div>`;
      this.report('card', String(e && e.message || e), String(e && e.stack || '').slice(0, 1500), card.type);
    }
    const holding = this.s.hold === id;
    const tell = this.s.tell && this.s.tell.kind === 'card' && this.s.tell.id === id;
    const detail = card.options && card.options.detail && typeof card.options.detail === 'object' ? card.options.detail : null;
    const acting = st && ['heating', 'cooling'].includes(st.attributes.hvac_action);
    const ring = tell || holding && this.s.edit ? `inset 0 0 0 2px ${mix('var(--violet)', 60)}` : this.s.edit ? `inset 0 0 0 1px ${mix(hue(hit.sec.color), 30)}` : open ? `inset 0 0 0 1.5px ${mix(card.type === 'climate' && !acting ? 'var(--sky)' : ctx.accent || 'var(--text)', card.type === 'climate' && !acting ? 28 : 40)}` : lifted && x.urgent ? 'inset 3px 0 0 var(--rose)' : detail ? `inset 0 0 0 1px ${acting ? mix(ctx.accent || 'var(--text)', 30) : 'var(--line)'}` : 'none';
    // An opened thermostat leans blue: a faint sky wash rather than its
    // (often grey) action colour, which read as tan over the sky section (house change).
    const cool = card.type === 'climate';
    const openBg = cool ? `linear-gradient(165deg, ${mix('var(--sky)', 9, 'var(--surface)')}, ${mix('var(--sky)', 3, 'var(--surface)')} 60%, ${mix('var(--teal)', 4, 'var(--surface)')})` : mix(ctx.accent || 'var(--text)', 7, 'var(--surface)');
    // Lights, blinds and fans (and their groups) keep their own look when they
    // open: their strips carry the colour, so no white wash behind (house change).
    const groupLook = ['light', 'light_group', 'cover', 'cover_group', 'fan', 'fan_group'].includes(card.type);
    const ownLook = card.type === 'lovelace' && card.card && card.card.compact; // it draws its own surface
    // An opened light, blind or fan stays clear of any wash, but it is opaque in
    // the section's own base tint, so a neighbour stepping aside never shows
    // through it mid-move (Oct 2026).
    const secBase = `color-mix(in oklab, ${hue(hit.sec.color)} calc(4% * var(--secK, 1)), var(--surface))`;
    mt.style.background = open && !this.s.edit && !ownLook ? (groupLook ? secBase : openBg) : lifted ? 'var(--surface)' : 'transparent';
    mt.classList.toggle('isopen', !!open);
    let aria = null; if (!this.s.edit) { try { aria = tileAria(T, ctx, name); } catch (e) { aria = null; } }
    this.tileA11y(mt, name, st, T.noOpen ? null : open, !this.s.edit && !!T.slide, aria);
    mt.style.boxShadow = ownLook ? 'none' : ring;
    mt.style.cursor = this.s.edit ? 'pointer' : 'default';
    mt.classList.toggle('holding', holding);
    mt.classList.toggle('lifted', !!lifted);
    mt.classList.toggle('sliding', this.s.previews[id] != null);
    const hb = holding ? `<span class="holdbar" style="background:${this.s.edit ? 'var(--violet)' : ctx.accent}"></span>` : '';
    let hbEl = mt.querySelector('.holdbar');
    if (hb && !hbEl) mt.insertAdjacentHTML('afterbegin', hb); else if (!hb && hbEl) hbEl.remove();
    this.setHtml(face, faceHtml);
    // Closing: what the card had opened fades while the tile shrinks, instead
    // of vanishing the instant the tile starts to close (house change).
    if (!moreHtml && this.s.fading === id && moreEl.firstChild) {
      moreEl.style.transition = 'opacity .24s var(--ease)'; moreEl.style.opacity = '0'; moreEl.style.pointerEvents = 'none';
    } else {
      moreEl.style.transition = ''; moreEl.style.opacity = ''; moreEl.style.pointerEvents = '';
      this.setHtml(moreEl, moreHtml);
    }
    if (T.host) this.mountLovelace(face, card);
    // The detail stays folded away until the card is opened, unless the card
    // asks for it always (options.detail_shown: true), e.g. a thermostat that
    // carries its HVAC performance on its face (house change).
    const detailAlways = !!detail && card.options.detail_shown === true;
    const showDetail = !!detail && (detailAlways || open && (!this.s.edit || mode === 'tell'));
    if (!showDetail && this.s.fading === id && detailEl.style.display !== 'none' && detailEl.firstChild) {
      detailEl.style.transition = 'opacity .24s var(--ease)'; detailEl.style.opacity = '0'; detailEl.style.pointerEvents = 'none';
    } else {
      detailEl.style.transition = ''; detailEl.style.opacity = ''; detailEl.style.pointerEvents = '';
      detailEl.style.display = showDetail ? '' : 'none';
    }
    if (detail && (showDetail || detailEl.firstChild)) {
      const did = id + ':detail';
      if (!detailEl.querySelector('[data-ll]')) detailEl.innerHTML = `<div class="ll" data-ll="${esc(did)}"></div>`;
      this.mountLovelace(detailEl, { id: did, card: detail });
    } else if (!detail && detailEl.firstChild) { detailEl.innerHTML = ''; this.llCards.delete(id + ':detail'); }
  }

  // Keyboard and screen readers (house change): every card is a stop on Tab,
  // named with what it is and what it is doing. The keys are in tileKey().
  tileA11y(mt, name, st, open, slides, aria) {
    const set = (k, v) => { if (v == null) { if (mt.hasAttribute(k)) mt.removeAttribute(k); } else if (mt.getAttribute(k) !== v) mt.setAttribute(k, v); };
    set('tabindex', '0');
    // cards.js says what the card is (slider, switch or button, with its
    // value); without that it is a named group.
    const A = aria || {};
    const slider = A.role === 'slider';
    set('aria-valuemin', slider ? '0' : null); set('aria-valuemax', slider ? '100' : null);
    set('aria-valuenow', slider ? String(A.now) : null); set('aria-valuetext', slider ? A.value : null);
    set('aria-checked', A.role === 'switch' ? String(!!A.checked) : null);
    set('role', A.role || 'group');
    set('aria-roledescription', A.role ? null : 'card');
    set('aria-label', slider || A.role === 'switch' ? name : A.role === 'button' && A.label ? A.label : (st ? `${name}, ${this.stateWords(st)}` : name));
    set('aria-expanded', open == null ? null : String(!!open));
    set('aria-keyshortcuts', slides ? 'Enter Shift+Enter ArrowLeft ArrowRight' : 'Enter Shift+Enter');
  }

  stateWords(st) {
    if (UNAVAILABLE.includes(st.state)) return 'unavailable';
    const a = st.attributes; const d = domainOf(st.entity_id);
    if (d === 'light' && st.state === 'on' && a.brightness != null) return `on, ${Math.round(a.brightness / 2.55)}%`;
    if (d === 'cover' && a.current_position != null) return `${st.state}, ${a.current_position}% open`;
    if (d === 'fan' && st.state === 'on' && a.percentage != null) return `on, ${a.percentage}%`;
    if (d === 'climate') return `${String(st.state).replace(/_/g, ' ')}${a.current_temperature != null ? `, ${fmt(a.current_temperature, '°')}` : ''}`;
    return `${String(st.state).replace(/_/g, ' ')}${a.unit_of_measurement ? ' ' + a.unit_of_measurement : ''}`;
  }

  // The card grammar from a keyboard: Enter or Space taps, Shift+Enter (or the
  // menu key) is the hold, the arrow keys slide the level 10 at a time.
  tileKey(e, id) {
    if (id.startsWith('k:') || id.startsWith('kf:')) return false;
    const enter = e.key === 'Enter' || e.key === ' ';
    if (enter && !e.shiftKey) { e.preventDefault(); this.tapTile(id); return true; }
    if ((e.key === 'Enter' && e.shiftKey) || e.key === 'ContextMenu') {
      e.preventDefault();
      if (this.s.edit) { if (!id.startsWith('add@')) this.openTell({ kind: 'card', id }); return true; }
      const hit = this.findCard(id); if (!hit || typeOf(hit.card).noOpen) return true;
      if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'adv');
      return true;
    }
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !this.s.edit) {
      const hit = this.findCard(id); if (!hit) return false;
      const T = typeOf(hit.card);
      const sl = T.slide ? T.slide({ hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null }) : null;
      if (!sl) return false;
      e.preventDefault();
      const kb = (this._kbLevel = this._kbLevel || {});
      const was = kb[id] && kb[id].until > Date.now() ? kb[id].v : Number(sl.get ? sl.get() : 0) || 0;
      const v = Math.max(0, Math.min(100, Math.round(was / 10) * 10 + (e.key === 'ArrowRight' ? 10 : -10)));
      kb[id] = { v, until: Date.now() + 2500 };
      this.s.previews[id] = v; this.schedule();
      this.call(sl.call(v)); this.noteUse(id);
      this.settlePreview(hit.card.entity, () => { if (!(kb[id] && kb[id].until > Date.now() + 1500)) delete this.s.previews[id]; });
      return true;
    }
    return false;
  }

  // The two extra words on a card the list lifted or led (§11): Keep here
  // (a pin, written to dashboard.yaml so every device keeps it) and Not this
  // (sinks it for today).
  keepHtml(card, shown) {
    if (!shown && !card.pin) return '';
    if (!this.admin()) return '';
    return `<div class="row keeprow" style="gap:0 18px">${card.pin ? `<button type="button" class="wd" data-act="unpin" data-v="${esc(card.id)}">Stop keeping it here</button>` : `<button type="button" class="wd go" data-act="keep" data-v="${esc(card.id)}">Keep here</button>`}<button type="button" class="wd" data-act="not-this" data-v="${esc(card.id)}">Not this</button></div>`;
  }

  // An opened card's way to its device page, for an admin. Its entity's
  // own Home Assistant card opens from a tap on its name (house change).
  moreInfoHtml(card, ctx) {
    const ids = card.entities || [];
    const eid = ctx.member || card.entity || (ids.length === 1 ? ids[0] : '');
    if (!eid || !this.hass.states[eid]) return '';
    const reg = this.hass.entities && this.hass.entities[eid];
    const dev = reg && reg.device_id;
    if (!dev || !this.admin() || !this.s.edit) return ''; // only in Edit: in use it was chrome (Oct 2026)
    return `<div class="moreinfo"><button type="button" class="wd" data-ctl="1" data-act="open-device" data-v="${esc(dev)}">Device page</button></div>`;
  }

  async mountLovelace(face, card) {
    const slot = face.querySelector('[data-ll]'); if (!slot) return;
    let el = this.llCards.get(card.id);
    const sig = JSON.stringify(card.card);
    if (el && el.__sig !== sig) { el = null; }
    if (!el) {
      if (this._llPending && this._llPending.has(card.id)) return;
      (this._llPending = this._llPending || new Set()).add(card.id);
      // A custom card whose code is still loading (a card file just added,
      // or a resource) would be made as Home Assistant's "Configuration
      // error" placeholder; wait for its definition a moment first, and if
      // it still lands as the placeholder, rebuild once it is defined
      // (house change: the ll-rebuild event can fire before we listen).
      const type = card.card && card.card.type;
      const tag = typeof type === 'string' && type.startsWith('custom:') ? type.slice(7) : '';
      try {
        // A defined custom card needs nothing from Lovelace; do not wait for it.
        const direct = typeof window.loadCardHelpers !== 'function' && !!tag && !!window.customElements && !!customElements.get(tag);
        const helpers = direct ? null : await cardHelpers();
        if (tag && !customElements.get(tag)) await Promise.race([customElements.whenDefined(tag), new Promise((r) => setTimeout(r, 4000))]);
        // Only a card made BEFORE its code was defined can be the error
        // placeholder. Checking `el.localName !== tag` instead rebuilt any
        // card that comes back wrapped on every render, forever: the whole
        // dashboard re-created its cards on each state change (flashing,
        // cameras restarting). Fixed 2026-11-09.
        const undefinedAtMake = !!tag && !customElements.get(tag);
        if (helpers) el = await helpers.createCardElement(card.card);
        else el = customCardWithoutHelpers(card.card);
        el.__sig = sig;
        el.hass = this.hass;
        const rebuild = () => { if (this.llCards.get(card.id) === el) { this.llCards.delete(card.id); this.schedule(); } };
        el.addEventListener('ll-rebuild', rebuild);
        if (undefinedAtMake) customElements.whenDefined(tag).then(rebuild);
        this.llCards.set(card.id, el);
      } catch (e) {
        slot.innerHTML = '<p class="sm" style="padding:12px">This card could not be drawn yet; reload the page.</p>';
        this.report('card', `A Lovelace card failed: ${e.message || e}`, sig.slice(0, 500), String(card.card && card.card.type));
        return;
      } finally { this._llPending.delete(card.id); }
    }
    if (el.parentNode !== slot) { slot.innerHTML = ''; slot.appendChild(el); }
    // One observer, one lay-out per frame, each slot observed once.
    floorFields(el);
    this.markEmptyCard(slot, el);
    if (!this._llRo) this._llRo = new ResizeObserver((ents) => { this.llCards.forEach((c) => floorFields(c)); ents.forEach((en) => { const sl = en.target; const c = sl.firstElementChild; if (c && sl.classList.contains('ll')) this.markEmptyCard(sl, c); }); cancelAnimationFrame(this._llRaf); this._llRaf = requestAnimationFrame(() => this.engine.layout(false, true)); });
    if (!slot.__llObserved) { slot.__llObserved = true; this._llRo.observe(slot); }
  }

  // A hosted card with nothing to draw (a conditional or alert card whose
  // condition is false) is a tile of no height, which is a card that is
  // gone: nobody can find it, hold it or ask about it. It says so in one
  // quiet line instead (#678).
  markEmptyCard(slot, el) {
    if (!slot || !el || !slot.isConnected) return;
    const none = slot.querySelector(':scope > .llnone');
    const boxed = (n) => n && (n.offsetHeight > 0 || n.getClientRects().length > 0 && n.getBoundingClientRect().height > 0);
    const kids = Array.from(el.children || []).concat(el.shadowRoot ? Array.from(el.shadowRoot.children) : []);
    const empty = el.offsetHeight === 0 && el.getBoundingClientRect().height === 0 && !kids.some(boxed);
    if (empty && !none) { const n = document.createElement('span'); n.className = 'llnone'; n.textContent = 'Nothing to show right now'; slot.appendChild(n); }
    else if (!empty && none) none.remove();
  }

  // ------------------------------------------------------------- editing

  cardEditHtml(hit, name) {
    const { card, sec } = hit;
    const T = typeOf(card);
    const sections = []; this.eachSection((s, fl) => sections.push({ id: s.id, label: `${fl.title} › ${s.title}` }));
    const yaml = JSON.stringify(card, null, 2);
    return `<div class="edit" data-ctl="1">
<label class="flab">Name<input class="fld" type="text" data-keep="card-name" data-act-change="card-name" data-v="${esc(card.id)}" value="${esc(card.name || '')}" placeholder="${esc(name)}"></label>
<div class="flab">Size<div class="row" style="gap:0 18px">${[[0, 'Auto'], [1, 'Small'], [2, 'Medium'], [3, 'Large']].map((x) => `<button type="button" class="wd opt" data-act="card-span" data-v="${esc(card.id)}" data-w="${x[0]}" aria-pressed="${(card.span || 0) === x[0]}">${x[1]}</button>`).join('')}</div></div>
${card.type === 'switch' && card.entity ? `<div class="flab">In the title row<div class="row" style="gap:0 18px"><button type="button" class="wd opt" data-act="card-head" data-v="${esc(card.id)}" aria-pressed="${isHeadCard(card)}">${isHeadCard(card) ? 'Shown as a button' : 'Show as a button'}</button><span class="small">beside ${esc(sec.title)}’s name, instead of a tile</span></div></div>` : ''}
<label class="flab">Move to<select class="fld" data-act-change="card-move" data-v="${esc(card.id)}">${sections.map((s) => `<option value="${esc(s.id)}"${s.id === sec.id ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
<details class="payload"><summary>Card YAML (as JSON)</summary><textarea class="code-ed" data-keep="card-yaml" style="min-height:140px" spellcheck="false">${esc(yaml)}</textarea><button type="button" class="wd go" data-act="card-yaml" data-v="${esc(card.id)}">Save this card</button></details>
<div class="row" style="gap:0 18px"><button type="button" class="go barw bad" data-act="card-remove" data-v="${esc(card.id)}">Remove card</button><span class="flex1"></span><span class="small">${esc(T === TYPES.lovelace ? 'Lovelace card' : card.type)}</span></div></div>`;
  }

  addCardHtml(sec, gi) {
    const H = this.hass;
    const near = Object.keys(H.states).filter((e) => { const r = H.entities && H.entities[e]; const area = r && (r.area_id || (r.device_id && H.devices && H.devices[r.device_id] && H.devices[r.device_id].area_id)); return sec.area && area === sec.area && !this.onDash(e); }).slice(0, 12);
    return `<div class="edit" data-ctl="1">
${near.length ? `<div class="flab">From ${esc(sec.title)}<div class="row" style="flex-wrap:wrap;gap:0 14px">${near.map((e) => `<button type="button" class="wd" data-act="add-entity" data-v="${esc(sec.id)}" data-g="${gi}" data-e="${esc(e)}" style="font-size:14px;text-transform:none;letter-spacing:0;font-weight:500">${esc(shortName(friendly(H, e), sec.title))}</button>`).join('')}</div></div>` : ''}
<label class="flab">Any entity<input class="fld" type="text" list="morph-entities" data-keep="add-entity" placeholder="light.kitchen" data-act-enter="add-typed" data-v="${esc(sec.id)}" data-g="${gi}"></label>
<datalist id="morph-entities">${Object.keys(H.states).slice(0, 3000).map((e) => `<option value="${esc(e)}">`).join('')}</datalist>
<label class="flab">Or any Lovelace card (YAML or JSON)<textarea class="code-ed" data-keep="add-ll" style="min-height:90px" placeholder="type: tile&#10;entity: sensor.outside"></textarea></label>
<div class="row" style="gap:0 18px"><button type="button" class="wd go" data-act="add-ll" data-v="${esc(sec.id)}" data-g="${gi}">Add Lovelace card</button><button type="button" class="wd" data-act="close">Cancel</button></div></div>`;
  }

  // Every Edit change is applied to the document here and saved at once:
  // one commit each, so every change has an Undo.
  mutate(message, fn) {
    if (!this.dash) return;
    const draft = JSON.parse(JSON.stringify(this.dash));
    if (fn(draft) === false) return;
    // New things get an id now, so the page can draw them before the add-on
    // has normalised the file; the add-on keeps an id it is given.
    const rid = () => Math.random().toString(36).slice(2, 8);
    (draft.floors || []).forEach((f) => { if (!f.id) f.id = 'f_new_' + rid(); (f.sections || []).forEach((sec) => { if (!sec.id) sec.id = 's_new_' + rid(); (sec.groups || []).forEach((g) => (g.cards || []).forEach((c) => { if (!c.id) c.id = 'c_new_' + rid(); })); }); });
    this.dash = draft;
    this._onDash = null;
    this._secEnts = null;
    this.engine.invalidate();
    this.schedule();
    this.saveQueue = (this.saveQueue || Promise.resolve()).then(() => this.save(message));
  }

  async save(message) {
    try {
      const r = await this.hass.callWS({ type: 'morph/request', kind: 'save', payload: { dashboard: this.dash, base: this.revision, message } });
      if (r && r.ok) { this.revision = r.revision; this.toast(message, r.commit); this.track('edit', null, null, message); }
      else { this.toast((r && r.error) || 'Morph could not save that.'); if (r && r.conflict) { this.dash = null; this.load(); } }
    } catch (e) { this.toast('Morph could not save that: ' + (e.message || e)); }
  }

  toast(text, sha, action) {
    clearTimeout(this._toastT);
    this.s.toast = { text, sha, action };
    this._toastT = setTimeout(() => { this.s.toast = null; this.schedule(); }, 9000);
    this.schedule();
  }

  sectionIn(d, id) { let hit = null; d.floors.forEach((f) => f.sections.forEach((s, i) => { if (s.id === id) hit = { f, s, i }; })); return hit; }
  cardIn(d, id) { let hit = null; d.floors.forEach((f) => f.sections.forEach((s) => (s.groups || []).forEach((g) => (g.cards || []).forEach((c, i) => { if (c.id === id) hit = { f, s, g, c, i }; })))); return hit; }

  // ------------------------------------------------------------ tell brAIn

  // The prompt that opens IN PLACE of what was held (§7). It is a
  // conversation: earlier turns stay above, the picture brAIn is given is
  // shown, and while brAIn works its own steps arrive here as it takes them.
  tellBox(kind, id) {
    const t = this.s.tell;
    if (!t || t.kind !== kind || (id && t.id !== id)) return '';
    const st = t.state || {};
    const composing = !t.sent;
    const done = ['done', 'failed'].includes(st.phase);
    const turns = (t.turns || []).map((u) => `<div class="turn"><span class="q">“${esc(u.text)}”</span>${u.say ? `<p class="a">${esc(u.say)}</p>` : ''}${this.pairHtml(u.before, u.after)}</div>`).join('');
    const acts = [];
    if (done) {
      // A change to Morph's own code runs once the page reloads.
      if (st.commit && !st.undone && (st.code || []).length) acts.push('<button type="button" class="wd go" data-act="reload-page">Reload to see it</button>', '<button type="button" class="wd strong" data-act="tell-undo">Undo</button>');
      else if (st.cards && st.commit && !st.undone) acts.push('<button type="button" class="wd go" data-act="reload-page">Reload to see it</button>', '<button type="button" class="wd strong" data-act="tell-undo">Undo</button>');
      else if (st.commit && !st.undone && !st.unchanged) acts.push('<button type="button" class="wd go" data-act="tell-keep">Keep</button>', '<button type="button" class="wd strong" data-act="tell-undo">Undo</button>');
      else if (st.commit && !st.undone) acts.push('<button type="button" class="wd go" data-act="tell-keep">Close</button>', '<button type="button" class="wd strong" data-act="tell-undo">Undo</button>');
      else if (st.undone) acts.push('<span class="sm">Put back.</span>');
      else acts.push('<button type="button" class="wd go" data-act="tell-keep">Done</button>');
      acts.push('<button type="button" class="wd" data-act="tell-more">Tell it more</button>');
    }
    const sugs = [].map((s) => `<button type="button" class="wd sug small" data-act="tell-sug" data-v="${esc(s)}">${esc(s)}</button>`).join('');
    const head = `<div class="row" style="min-width:0">${SPARK}<span style="font-size:13px;font-weight:600;white-space:nowrap">Tell ${esc(this.who())}</span><span class="small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0">${esc(t.path || '')}</span></div>`;
    const scope = composing ? `<span class="small">${kind === 'code' ? 'Changes Morph’s own code for this house.' : 'Changes this dashboard only.'} Home Assistant is changed only if you ask (“make a sensor for…”), and nothing goes to GitHub unless you say yes.</span>` : '';
    if (composing) {
      return `<div data-ctl="1" data-tell="1" class="tell rise" style="margin-top:6px">${head}${turns}${this.shotHtml(t.shot, t.turns && t.turns.length ? 'How it looks now — brAIn sees this' : 'What brAIn will see')}
<textarea class="tellin" rows="3" data-keep="tell" data-tellkey="${esc(kind + ':' + (id || ''))}" aria-label="What should change" placeholder="${esc(kind === 'dashboard' ? 'Add a Pets section with the feeder and water bowl…' : t.turns && t.turns.length ? 'What should it do differently?' : 'Say what should change…')}"></textarea>${scope}
<div class="row" style="flex-wrap:wrap;gap:0 16px">${t.turns && t.turns.length ? '' : sugs}<span class="flex1"></span><button type="button" class="wd" data-act="tell-cancel" style="font-size:14px;min-height:36px">${t.turns && t.turns.length ? 'Close' : 'Cancel'}</button><button type="button" class="wd" data-act="tell-send" style="font-size:14px;font-weight:700;min-height:36px;color:var(--violet)">Send</button></div></div>`;
    }
    const all = st.steps || [];
    const SHOW = 7;
    const line = (x, i, arr) => stepLine(x, `${arr && i === arr.length - 1 ? ' rise' : ''}${x.brain ? ' bstep' : ''}`);
    const earlier = all.length > SHOW ? all.slice(0, all.length - SHOW) : [];
    const folded = earlier.length + (st.folded || 0);
    const steps = (folded ? `<details class="earlier"><summary>${folded} earlier step${folded === 1 ? '' : 's'}</summary>${earlier.map((x) => line(x)).join('')}</details>` : '') + all.slice(-SHOW).map(line).join('');
    const working = !done ? `<div class="working"><span class="pulse"></span><span>${esc(this.phaseWords(st))}</span><span class="small" data-since="${Number(st.started) || ''}"></span></div>` : '';
    const picture = t.shot && t.shot.url ? this.pairHtml(t.shot.url, t.after) : t.shot && t.shot.status === 'failed' ? `<span class="small">No picture this time (${esc(t.shot.error || 'it could not be drawn')}); brAIn was given the card’s text instead.</span>` : '';
    // No `rise` here: this box is rebuilt each time brAIn takes a step, and
    // replaying the blur-in on every rebuild made it flicker as it worked.
    return `<div data-ctl="1" data-tell="1" class="tell" style="margin-top:6px">${head}${turns}
<span style="font-size:14px">“${esc(t.text)}”</span>${picture}
<div class="steps" role="log" aria-live="polite" aria-label="brAIn's steps">${steps || '<div class="step"><i style="background:var(--violet)"></i><span>Handing it to brAIn…</span></div>'}</div>${working}
${done ? `<p class="rise" style="font-size:14px;line-height:1.5${st.unchanged || st.phase === 'failed' ? ';color:var(--amber)' : ''}">${esc(st.say || '')}</p>${this.whatHtml(st, kind)}${st.saw ? `<p class="sm">brAIn saw: ${esc(st.saw)}</p>` : ''}${st.needs_person ? `<p class="sm" style="color:var(--amber)">Left for you: ${esc(st.needs_person)}</p>` : ''}${this.questionHtml(st, t)}${this.issueHtml(st)}<div class="row" style="flex-wrap:wrap;gap:0 18px">${acts.join('')}</div>` : ''}
${st.payload ? `<details class="payload"><summary>What ${esc(this.who())} receives</summary><pre>${esc(st.payload)}</pre></details>` : ''}</div>`;
  }

  // What a request touched, one line per place it could have: the
  // dashboard (read back off the file, not taken from brAIn's words), Home
  // Assistant, Morph's own code, brAIn's memory and GitHub. Every line is
  // there whether or not anything happened in that place, so "it only
  // changed the dashboard" is something a person reads, not infers.
  whatHtml(st, kind) {
    const row = (k, v, tone) => `<div class="what"><span class="wk">${esc(k)}</span><span class="wv"${tone ? ` style="color:${tone}"` : ''}>${v}</span></div>`;
    const rows = [];
    const shows = st.shows || [];
    const stale = st.revision && this.data && this.data.mirror && this.data.mirror.revision !== st.revision;
    if (kind !== 'code') {
      const parts = shows.map((x) => `<span>${esc(x)}</span>`);
      if (st.cards) parts.push('<span>Custom card code changed</span>');
      if (stale) parts.push('<span style="color:var(--amber)">This screen has not caught up yet. <button type="button" class="wd go mini" data-act="tell-refresh">Refresh</button></span>');
      rows.push(row('Dashboard', parts.length ? parts.join('') : st.undone ? 'Put back' : 'Nothing changed', parts.length ? '' : 'var(--muted)'));
    }
    const house = st.house || [];
    rows.push(row('Home Assistant', house.length ? house.map((x) => `<span>${esc(x)}</span>`).join('') + (st.undone ? '<span class="small">brAIn was asked to put these back.</span>' : '<span class="small">Undo asks brAIn to put these back.</span>') : 'Not changed', house.length ? '' : 'var(--muted)'));
    if ((st.code || []).length || kind === 'code') rows.push(row('Morph’s code', (st.code || []).length ? `${esc(st.code.join(', '))}<span class="small">Runs after a reload.</span>` : 'Not changed', (st.code || []).length ? '' : 'var(--muted)'));
    if (st.facts_filed) rows.push(row('brAIn’s memory', `${st.facts_filed} fact${st.facts_filed === 1 ? '' : 's'} about the house queued`));
    const issue = st.code_issue;
    rows.push(row('GitHub', !issue ? 'Nothing sent' : st.issue === 'sent' ? 'Sent to your private reports repository' : st.issue === 'declined' ? 'Not sent' : 'Not sent — it asks below', issue && st.issue === 'sent' ? 'var(--teal)' : 'var(--muted)'));
    return `<div class="whatlist rise">${rows.join('')}</div>`;
  }

  // A choice brAIn left for the person, as buttons. The answer is the next
  // request, started from the option stored with this tell; one that
  // changes Home Assistant says so on the button.
  questionHtml(st, t) {
    const q = st.question;
    if (!q || st.undone) return '';
    if (st.answered != null) return `<p class="sm">You chose: ${esc((q.options[st.answered] || {}).label || '')}</p>`;
    const busy = t && t.answering;
    return `<div class="issue askq rise"><b>${esc(q.text)}</b><div class="row" style="flex-wrap:wrap;gap:6px 18px">${q.options.map((o, i) => `<button type="button" class="wd go" data-act="tell-answer" data-v="${i}"${busy ? ' disabled' : ''}>${esc(o.label)}</button>${o.home_assistant ? '<span class="small">changes Home Assistant</span>' : ''}`).join('')}</div>${busy ? '<div class="working"><span class="pulse"></span><span>Handing it to brAIn…</span></div>' : ''}</div>`;
  }

  shotHtml(shot, caption) {
    if (!shot) return '';
    if (shot.url) return `<figure class="shot${this.s.tell && this.s.tell.zoom ? ' zoom' : ''}" data-act="shot-zoom"><img src="${shot.url}" alt="${esc(caption)}"><figcaption>${esc(caption)}${shot.status === 'uploading' ? ' · sending…' : ''}</figcaption></figure>`;
    if (shot.status === 'failed') return `<span class="small">No picture this time (${esc(shot.error || 'it could not be drawn')}); brAIn gets the card’s text instead.</span>`;
    return '<span class="small">Taking a picture of it for brAIn…</span>';
  }

  pairHtml(before, after) {
    if (!before && !after) return '';
    const fig = (src, cap) => src ? `<figure class="shot${this.s.tell && this.s.tell.zoom ? ' zoom' : ''}" data-act="shot-zoom"><img src="${src}" alt="${cap}"><figcaption>${cap}</figcaption></figure>` : '';
    return `<div class="shots">${fig(before, after ? 'Before' : 'What brAIn saw')}${fig(after, 'After')}</div>`;
  }

  issueHtml(st) {
    const issue = st.code_issue;
    if (!issue) return '';
    if (st.issue === 'sent') return '<p class="sm" style="color:var(--teal)">Sent as an issue to brAIn’s development loop.</p>';
    if (st.issue === 'declined') return '';
    // brAIn changed Morph itself (st.code), or could not and said what
    // Morph would need. Either way the question is whether Morph should
    // have it for everybody.
    const made = (st.code || []).length && !st.undone;
    return `<div class="issue rise"><b>${made ? 'brAIn changed Morph itself.' : 'This needs a change to Morph itself.'}</b><span>${esc(issue.title)}</span>${issue.detail ? `<span class="sm">${esc(issue.detail)}</span>` : ''}<span>${made ? 'Would you like to open an issue to update Morph’s code, so everybody gets this? The change goes with it.' : 'Would you like to send this as an issue, so Morph’s code gets fixed?'} It goes to brAIn’s development loop and on to your private reports repository.</span><div class="row" style="flex-wrap:wrap;gap:0 18px"><button type="button" class="wd go" data-act="tell-issue" data-v="send">${made ? 'Open an issue' : 'Send as issue'}</button><button type="button" class="wd" data-act="tell-issue" data-v="no">No</button></div></div>`;
  }

  phaseWords(st) {
    if (st.phase === 'sending') return `Handing it to ${this.who()}`;
    if (st.phase === 'waiting') return `Waiting for ${this.who()} to pick it up`;
    return `${this.who()} is working on it`;
  }

  elapsed(started) {
    if (!started) return '';
    const s = Math.max(0, Math.round(Date.now() / 1000 - started));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
  }

  // How long brAIn has been at it, written into the spans that ask for it
  // rather than into the HTML: a box whose markup changed every second
  // would be rebuilt every second.
  tickSince() {
    if (!this.shadowRoot) return;
    this.shadowRoot.querySelectorAll('[data-since]').forEach((el) => {
      const txt = this.elapsed(Number(el.dataset.since));
      if (el.textContent !== txt) el.textContent = txt;
    });
  }

  // What brAIn is doing for Morph right now. A tell keeps running when its
  // box is closed or the page is reloaded, and this is how that stays seen.
  activityHtml() {
    if (!this.admin()) return '';
    const st = (this.data && this.data.state) || {};
    const t = this.s.tell;
    const rows = (st.activity || []).filter((a) => !(t && t.tellId === a.id)).map((a) => {
      const live = this.tellStatus[a.id] || {};
      if (['done', 'failed'].includes(live.phase)) return '';
      const step = ((live.steps || []).slice(-1)[0] || {}).t || a.step || '';
      return `<div class="activity"><span class="pulse"></span><span class="lx"><b>${esc(this.who())} is working on “${esc(a.text)}”</b><span>${esc([a.path, step].filter(Boolean).join(' · '))} · <span data-since="${Number(a.started) || ''}"></span></span></span><button type="button" class="wd" data-act="activity-open" data-v="${esc(a.id)}">Show</button></div>`;
    }).join('');
    const L = st.learning || {};
    const learn = L.running ? '<div class="activity"><span class="pulse"></span><span class="lx"><b>Morph is learning from how this dashboard is used</b><span>brAIn is reading the last month of use; its suggestions appear on the Feed.</span></span></div>' : '';
    return rows + this.tellsAwayHtml() + learn;
  }

  parkTell(old, next) {
    if (!old.tellId || ['done', 'failed'].includes(old.state && old.state.phase)) return;
    if (next && (next.tellId === old.tellId || next.previous === old.tellId)) return;
    this.tellsAway = [old, ...this.tellsAway.filter((x) => x.tellId !== old.tellId)].slice(0, ASK_KEEP);
  }

  // A parked tell that has finished: what brAIn said, and Show opens its
  // box again with Keep and Undo.
  tellsAwayHtml() {
    return this.tellsAway.map((t) => {
      const st = this.tellStatus[t.tellId];
      if (!st || !['done', 'failed'].includes(st.phase)) return '';
      return `<div class="activity" data-k="away-${esc(t.tellId)}"><span class="lx"><b>${esc(this.who())} ${st.phase === 'failed' ? 'could not finish' : 'finished'} “${esc(t.text)}”</b><span>${esc(String(st.say || '').split('\n')[0].slice(0, 200))}</span></span><button type="button" class="wd" data-act="tell-back" data-v="${esc(t.tellId)}">Show</button></div>`;
    }).join('');
  }

  restoreTellText(el) {
    const ta = el.querySelector && el.querySelector('textarea[data-tellkey]');
    if (ta && this.s.tell && this.s.tell.draft) ta.value = this.s.tell.draft;
  }

  // Where a held thing is on the page, for its picture.
  targetEl(scope) {
    const R = this.shadowRoot;
    if (scope.kind === 'card') {
      // The whole tile, opened part and detail included: the Tell box is
      // left out of the picture by its data-tell. Only the editor (Edit) is
      // not the card, so a card open in Edit is pictured by its face.
      const tile = R.querySelector(`[data-tile="${CSS.escape(scope.id || '')}"]`);
      const v = this.s.view;
      return tile && v && v.id === scope.id && v.mode === 'edit' ? (tile.querySelector('.tc > [data-face]') || tile) : tile;
    }
    if (scope.kind === 'section') return R.querySelector(`[data-sec="${CSS.escape(scope.id || '')}"]`);
    if (scope.kind === 'floor') return R.querySelector(`[data-fid="${CSS.escape(scope.id || '')}"]`);
    if (['story', 'upcoming', 'scenes'].includes(scope.kind)) return R.querySelector(`[data-hold="${scope.kind}"]`);
    if (scope.kind === 'code') return null; // Morph's own module: nothing on the page is it
    return R.querySelector('[data-board]');
  }

  // Photograph what was held. Must run BEFORE the panel re-renders: the
  // clone is taken now and drawn later, so the picture is the card as it
  // was, not the editor that is about to open over it.
  // `wait` (a promise) delays the picture until a card has been opened and
  // its detail drawn, so brAIn sees the card expanded (house change).
  shoot(t, wait) {
    const shot = { status: 'taking', view: {}, png: '', error: '', id: '' };
    t.shot = shot;
    const prep = () => {
      const el = this.targetEl(t);
      if (!el) { shot.status = 'failed'; shot.error = 'Morph could not find it on the page'; return null; }
      let bg = '';
      try { bg = getComputedStyle(this.rootEl).backgroundColor; } catch (e) { /* no background to lay it on */ }
      const job = snap.prepare(el, { background: bg, fontsUrl: FONTS_URL });
      shot.view = job.view;
      return job;
    };
    const first = wait ? null : prep();
    if (!wait && !first) return;
    shot.ready = (async () => {
      let job = first;
      if (wait) { try { await wait; } catch (e) { /* take it as it is */ } job = prep(); if (!job) { this.schedule(); return; } }
      const r = await job.render();
      shot.notes = r.notes || [];
      if (!r.png) { shot.status = 'failed'; shot.error = r.error; this.schedule(); return; }
      shot.url = snap.blobUrl(r.png);
      shot.status = 'uploading'; this.schedule();
      try {
        const res = await this.hass.callWS({ type: 'morph/shot', png: r.png });
        shot.id = res.shot; shot.status = 'ready';
      } catch (e) {
        shot.status = 'failed'; shot.error = `it could not be sent (${(e && e.message) || e})`;
      }
      this.schedule();
    })();
  }

  // What is under a point, as a Tell scope: a card, a room, a part of the top of
  // the page, a floor, or else the dashboard.
  scopeAt(el) {
    const c = (s) => (el && el.closest ? el.closest(s) : null);
    const tile = c('[data-tile]');
    if (tile) { const id = tile.getAttribute('data-tile'); if (id && !id.startsWith('add@')) return { kind: 'card', id }; }
    const sec = c('[data-sec]'); if (sec) return { kind: 'section', id: sec.getAttribute('data-sec') };
    const hold = c('[data-hold]');
    if (hold) { const k = hold.getAttribute('data-hold'); if (['story', 'upcoming', 'scenes'].includes(k)) return { kind: k, id: '' }; }
    const fl = c('[data-floor]');
    if (fl) { const f = ((this.dash && this.dash.floors) || [])[Number(fl.getAttribute('data-floor'))]; if (f) return { kind: 'floor', id: f.id }; }
    return { kind: 'dashboard', id: '' };
  }
  // Drop whatever one finger had started (a hold, a slide, a widened tile), without acting on it.
  quietPointer() {
    clearTimeout(this.holdT); clearTimeout(this.mholdT); clearTimeout(this.tholdT);
    if (this.ptr && this.s.previews[this.ptr.id] != null) delete this.s.previews[this.ptr.id];
    this.ptr = null; this.mptr = null; this.thold = null; this.s.hold = null; this.schedule();
  }
  tellAbout(scope) {
    if (!this.admin() || !scope) return;
    haptic('medium');
    this.openTell(scope);
  }

  openTell(scope) {
    if (!this.admin()) return;
    const path = this.pathOf(scope);
    this.s.tell = { ...scope, path, text: '', sent: false, draft: '', turns: [] };
    if (scope.kind === 'card') {
      // Open the card first and photograph it once its opened part and
      // detail have drawn: a collapsed face is not what is being changed.
      this.openView(scope.id, 'tell');
      this.render();
      this.shoot(this.s.tell, this.settleCard(scope.id));
    } else {
      this.shoot(this.s.tell);
      if (this.s.view) this.closeView();
    }
    this.s.hold = null;
    this.schedule();
    setTimeout(() => { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); if (ta) { try { ta.focus({ preventScroll: true }); } catch (e) { ta.focus(); } } }, 360);
  }

  // Resolves once an opened card has drawn: two frames, then (for a card
  // with a Lovelace detail) until that detail has content, at most ~1.5 s.
  async settleCard(id) {
    const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
    await frame(); await frame();
    const hit = this.findCard(id);
    const hasDetail = !!(hit && hit.card.options && hit.card.options.detail);
    const until = performance.now() + 1500;
    while (hasDetail && performance.now() < until) {
      const slot = this.shadowRoot.querySelector(`[data-tile="${CSS.escape(id)}"] .tc > [data-detail] [data-ll]`);
      if (slot && slot.childElementCount) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    // Let custom cards and the open animation finish drawing.
    await new Promise((r) => setTimeout(r, 450));
  }

  pathOf(scope) {
    if (scope.kind === 'card') {
      const hit = this.findCard(scope.id);
      if (hit) { scope.label = this.cardName(hit.card, hit.sec); scope.entity = hit.card.entity || ''; return `${hit.fl.title} › ${hit.sec.title} › ${scope.label}${scope.entity ? ' · ' + scope.entity : ''}`; }
    }
    if (scope.kind === 'section') { const s = this.sectionById(scope.id); let fl = null; this.eachSection((x, f) => { if (x.id === scope.id) fl = f; }); if (s) { scope.label = s.title; return `${fl ? fl.title + ' › ' : ''}${s.title}`; } }
    if (scope.kind === 'floor') { const f = (this.dash.floors || []).find((x) => x.id === scope.id); if (f) { scope.label = f.title; return f.title; } }
    scope.label = KIND_WORD[scope.kind] || 'dashboard';
    return scope.kind === 'dashboard' ? 'The whole dashboard' : KIND_WORD[scope.kind];
  }

  async sendTell(text) {
    const t = this.s.tell; if (!t) return;
    const ae = this.shadowRoot.activeElement; if (ae && ae.blur) ae.blur();
    text = String(text || '').trim();
    if (!text) return;
    t.text = text; t.sent = true; t.state = { phase: 'sending', steps: [] };
    this.track('tell', t.kind === 'card' ? t.id : null, t.kind === 'section' ? t.id : null);
    this.schedule();
    const shot = t.shot;
    if (shot && shot.ready && shot.status !== 'ready' && shot.status !== 'failed') {
      t.state = { phase: 'sending', steps: [{ t: 'Finishing the picture of it', tone: '' }] }; this.schedule();
      await Promise.race([shot.ready, new Promise((r) => setTimeout(r, 6000))]);
    }
    const view = shot ? { ...(shot.view || {}), error: shot.status === 'ready' ? '' : (shot.error || 'the picture was not ready in time') } : { error: 'no picture was taken' };
    try {
      const r = await this.hass.callWS({ type: 'morph/request', kind: 'tell', payload: { target: { kind: t.kind, id: t.id || '', label: t.label || '', path: t.path || '', entity: t.entity || '' }, text, previous: t.previous || '', shot: (shot && shot.status === 'ready' && shot.id) || '', view } });
      if (!r || !r.ok) { t.state = { phase: 'failed', say: (r && r.error) || 'Morph could not hand this to brAIn.', steps: [] }; this.schedule(); return; }
      t.tellId = r.id;
      this.pollTell(true);
    } catch (e) { t.state = { phase: 'failed', say: String(e.message || e), steps: [] }; this.schedule(); }
  }

  async pollTell(soon) {
    const t = this.s.tell;
    this.tellStatus = this.tellStatus || {};
    const ids = [];
    if (t && t.tellId && !['done', 'failed'].includes(t.state && t.state.phase)) ids.push(t.tellId);
    ((this.data && this.data.state && this.data.state.suggestions) || []).forEach((g) => { if (g.status === 'doing' && g.tell) ids.push(g.tell); });
    ((this.data && this.data.state && this.data.state.activity) || []).forEach((a) => { if (!ids.includes(a.id) && !['done', 'failed'].includes((this.tellStatus[a.id] || {}).phase)) ids.push(a.id); });
    // A parked tell is asked after until it lands, whether or not the
    // service still lists it as running: the list drops it as it finishes.
    this.tellsAway.forEach((x) => { if (!ids.includes(x.tellId) && !['done', 'failed'].includes((this.tellStatus[x.tellId] || {}).phase)) ids.push(x.tellId); });
    for (const id of ids) {
      try {
        const st = await this.hass.callWS({ type: 'morph/tell_status', tell: id });
        this.tellStatus[id] = st;
        if (t && t.tellId === id) {
          const was = t.state && t.state.phase;
          t.state = st;
          if (st.phase === 'done' && was !== 'done') {
            // The same thing, photographed again once the change has drawn:
            // before and after side by side, and the next turn starts here.
            // Always read the dashboard again: what the person is told and
            // what their screen shows must be the same file.
            const after = () => setTimeout(() => this.afterShot(t), 1200);
            this.load().then(after);
          }
        }
      } catch (e) { /* the next tick asks again */ }
    }
    this.schedule();
    if (soon && t && t.tellId && !['done', 'failed'].includes(t.state && t.state.phase)) { clearTimeout(this._tellT); this._tellT = setTimeout(() => this.pollTell(true), 1200); }
  }

  afterShot(t) {
    if (this.s.tell !== t) return;
    const el = this.targetEl(t);
    if (!el) return;
    snap.prepare(el, { background: getComputedStyle(this.rootEl).backgroundColor, fontsUrl: FONTS_URL }).render().then((r) => {
      if (r.png && this.s.tell === t) { t.after = snap.blobUrl(r.png); this.schedule(); }
    });
  }

  closeTell() {
    const t = this.s.tell; if (!t) return;
    this.s.tell = null;
    // A Tell opened from Morph's mark in an opened card goes back to that
    // card; one opened by holding it in Edit closes it.
    if (t.kind === 'card' && this.s.view && this.s.view.id === t.id) {
      if (t.from === 'adv' && !this.s.edit) this.openView(t.id, 'adv'); else this.closeView();
    }
    this.schedule();
  }

  // ----------------------------------------------------------- open/close

  openView(id, mode) {
    this.s.slideWide = null; clearTimeout(this._slideT);
    const cur = this.s.view;
    if (cur && cur.id === id && cur.mode === mode) return;
    this.engine.originId = id;
    if (cur && cur.id !== id) { this.s.fading = cur.id; clearTimeout(this._fadeT); this._fadeT = setTimeout(() => { this.s.fading = null; this.schedule(); }, 520); }
    this.s.view = { id, mode, member: cur && cur.id === id ? cur.member : null, H: { depth: 0 } };
    if (mode === 'adv') { const hit = this.findCard(id); this.track('open', id, hit && hit.sec.id); haptic('medium'); }
    this.schedule();
  }

  closeView() {
    const cur = this.s.view; if (!cur) return;
    if (this.s.tell && this.s.tell.kind === 'card' && this.s.tell.id === cur.id) this.s.tell = null;
    this.engine.originId = cur.id;
    this.s.view = null; this.s.fading = cur.id; this.s.memberPreview = null;
    haptic('light');
    clearTimeout(this._fadeT); this._fadeT = setTimeout(() => { this.s.fading = null; this.schedule(); }, 520);
    this.schedule();
  }

  revealCard(id) {
    const el = this.shadowRoot.querySelector(`[data-tile="${CSS.escape(id)}"]`);
    this.openView(id, 'adv');
    if (el) this.engine.scrollToEl(el);
  }

  revealEntity(eid) {
    let hit = null;
    this.eachSection((sec) => this.sectionCards(sec).forEach((c) => { if (!hit && (c.entity === eid || (c.entities || []).includes(eid))) hit = c; }));
    if (hit) { this.revealCard(hit.id); if (hit.entities) this.s.view.member = eid; }
  }

  // ---------------------------------------------------------------- events

  bindEvents() {
    const root = this.shadowRoot;
    root.addEventListener('pointerdown', () => { this.ui.lastTouch = Date.now(); }, true);
    root.addEventListener('keydown', () => { this.ui.lastTouch = Date.now(); }, true);
    // The Ask suggestions only show while the field has focus, so pressing
    // one must not take the focus away first (Safari never focuses a button).
    root.addEventListener('mousedown', (e) => { if (e.target.closest && e.target.closest('[data-act="ask-sug"]')) e.preventDefault(); });
    root.addEventListener('pointerdown', (e) => this.onDown(e));
    root.addEventListener('pointermove', (e) => this.onMove(e));
    root.addEventListener('pointerup', (e) => this.onUp(e));
    root.addEventListener('pointercancel', () => this.cancelPtr());
    // Tell brAIn about anything: tap it with two fingers (or right-click it).
    // Nothing in Morph uses two fingers, so it never toggles, slides or opens
    // anything on the way (house change).
    root.addEventListener('pointerdown', (e) => { this._lastPtrType = e.pointerType; }, true);
    // Pinch-zoom stays the browser's: the touch is never taken at the start,
    // only a two-finger tap that stayed still is read as a Tell, at its end.
    root.addEventListener('touchstart', (e) => {
      if (e.touches.length === 2 && !this.s.edit && this.admin()) {
        const a = e.touches[0], b = e.touches[1];
        this._two = { scope: this.scopeAt(a.target), at: performance.now(), x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2, moved: false };
        this.quietPointer();
      } else if (e.touches.length > 2) this._two = null;
    }, { passive: true });
    root.addEventListener('touchmove', (e) => {
      const g = this._two; if (!g || e.touches.length < 2) return;
      const x = (e.touches[0].clientX + e.touches[1].clientX) / 2, y = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      // A pinch spreads the fingers; a pan moves them: either is not a tap.
      const sp = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      if (g.sp == null) g.sp = sp;
      if (Math.hypot(x - g.x, y - g.y) > 24 || Math.abs(sp - g.sp) > 24) g.moved = true;
    }, { passive: true });
    root.addEventListener('touchend', (e) => {
      const g = this._two; if (!g) return;
      if (e.touches.length) return; // wait for the last finger
      this._two = null;
      if (g.moved || performance.now() - g.at >= 900) return;
      e.preventDefault(); // no click from either finger
      this._swallowClickUntil = performance.now() + 500;
      this.tellAbout(g.scope);
    }, { passive: false });
    root.addEventListener('click', (e) => { if (this._swallowClickUntil && performance.now() < this._swallowClickUntil) { e.stopPropagation(); e.preventDefault(); } }, true);
    root.addEventListener('contextmenu', (e) => {
      if (!e.target.closest) return;
      // A mouse's right click opens the Tell box; a long press (which some phones
      // report as a right click) stays a hold.
      // Only on what a Tell can be about (a card, a room's title, a floor, the
      // top regions): the browser's own menu stays everywhere else.
      if (this._lastPtrType === 'mouse' && !this.s.edit && this.admin() && e.target.closest('.mtile, .sechead, .flh, [data-hold]') && !e.target.closest('input, textarea, [contenteditable], [data-tell], a, select')) { e.preventDefault(); this.quietPointer(); this.tellAbout(this.scopeAt(e.target)); return; }
      if (e.target.closest('.mtile, [data-hold], .sechead, .flh')) e.preventDefault();
    });
    // With a keyboard: point at anything and press T (nothing pointed at: the
    // whole dashboard). Listened for on the window, since the page itself
    // usually has the focus, not Morph (house change).
    root.addEventListener('pointermove', (e) => { if (e.pointerType === 'mouse') this._hoverEl = e.target; }, { passive: true });
    this.addEventListener('pointerleave', () => { this._hoverEl = null; });
    this._tellKey = (e) => {
      if (e.key !== 't' && e.key !== 'T') return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.repeat || !this.isConnected || this.s.edit || this.s.tell || !this.admin() || !this.tellKeyOn()) return;
      const p = e.composedPath ? e.composedPath() : [e.target];
      if (p.some((n) => n && n.nodeType === 1 && (n.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(n.tagName)))) return;
      // What is pointed at, else what has the keyboard's focus, else the dashboard.
      const foc = this.shadowRoot.activeElement;
      const el = this._hoverEl && this._hoverEl.isConnected ? this._hoverEl : foc && foc !== this ? foc : null;
      e.preventDefault(); this.quietPointer(); this.tellAbout(el ? this.scopeAt(el) : { kind: 'dashboard', id: '' });
    };
    root.addEventListener('click', (e) => this.onClick(e));
    root.addEventListener('change', (e) => this.onChange(e));
    // A group's All slider: a tap toggles every light or blind in it, like
    // tapping the group's own bars; a slide sets them all (house change).
    root.addEventListener('pointerdown', (e) => { const t = e.target; if (t && t.classList && t.classList.contains('lgrange')) this._allTap = { el: t, x: e.clientX, y: e.clientY, v: t.value, moved: false }; }, true);
    root.addEventListener('pointermove', (e) => { const a = this._allTap; if (a && Math.hypot(e.clientX - a.x, e.clientY - a.y) > 6) a.moved = true; }, true);
    root.addEventListener('change', (e) => {
      const a = this._allTap; const t = e.target;
      if (!a || a.el !== t) return;
      this._allTap = null;
      if (a.moved) return;
      e.stopImmediatePropagation();
      t.value = a.v; t.style.setProperty('--v', a.v + '%'); if (t.nextElementSibling) t.nextElementSibling.textContent = a.v + '%';
      const eid = t.dataset.entity; const d = eid.split('.')[0];
      this.call({ domain: d === 'cover' ? 'cover' : 'light', service: 'toggle', data: { entity_id: eid } });
    }, true);
    root.addEventListener('pointerup', () => { const a = this._allTap; if (a) setTimeout(() => { if (this._allTap === a) this._allTap = null; }, 300); }, true);
    // Range sliders (a group's All, a blind's tilt) are felt in steps too.
    root.addEventListener('input', (e) => { const t = e.target; if (t && t.type === 'range' && !(this._allTap && this._allTap.el === t && !this._allTap.moved)) { const v = Number(t.value); const w = t.__hv != null ? t.__hv : v; t.__hv = v; this.detent(null, w, v); } });
    root.addEventListener('input', (e) => {
      const t = e.target;
      // Coming up's zoom slider zooms as it slides (house change).
      if (t.dataset && t.dataset.upcZs != null) { this.upcZoom(upc.fromSlider(Number(t.value))); return; }
      if (t.dataset && t.dataset.tellkey && this.s.tell) this.s.tell.draft = t.value;
      // The report box keeps its words through Settings' own re-renders.
      if (t.dataset && t.dataset.keep === 'report') this.s.report = { ...(this.s.report || {}), text: t.value };
      if (t.dataset && t.dataset.keep === 'feedq') this.s.feedDraft = t.value;
      if (t.dataset && t.dataset.keep === 'report-ui') this.s.report = { ...(this.s.report || {}), ui: t.checked };
    });
    root.addEventListener('keydown', (e) => {
      const t = e.target;
      if (t.dataset && t.dataset.upcVp != null && this._upc && ['+', '=', '-', '_'].includes(e.key) && !e.ctrlKey && !e.metaKey) {
        e.preventDefault(); this.upcZoom(upc.getZoom() * (e.key === '+' || e.key === '=' ? 1.5 : 1 / 1.5)); return;
      }
      if (t.dataset && t.dataset.upcVp != null && this._upc && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault(); this.s.upcOpen = !this.s.upcOpen; this.region('upcoming', this.upcomingHtml()); return;
      }
      if (t.dataset && t.dataset.upcVp != null && this._upc && ['ArrowRight', 'ArrowLeft', 'Home'].includes(e.key)) {
        e.preventDefault();
        const m = this._upc; const c = this.upcCursor(m);
        const n = e.key === 'Home' ? 0 : upc.step(m, c, e.key === 'ArrowRight' ? 1 : -1);
        if (n != null) this.upcGo(m, n);
        return;
      }
      // A focused card takes the card grammar's keys (house change).
      if (t.classList && t.classList.contains('mtile') && t.dataset.mt && this.tileKey(e, t.dataset.mt)) return;
      // Anything else that acts and can take focus (Settings' switches, a
      // header chip's row) answers Enter and Space like a button.
      if ((e.key === 'Enter' || e.key === ' ') && t.dataset && t.dataset.act && t.hasAttribute('tabindex') && !/^(BUTTON|INPUT|TEXTAREA|SELECT|A)$/.test(t.tagName)) { e.preventDefault(); this.act(t.dataset.act, t); return; }
      if (e.key === 'Escape') { if (this.s.tell) this.closeTell(); else if (this.s.view) { const id = this.s.view.id; this.closeView(); const tile = this.shadowRoot.querySelector(`[data-mt="${CSS.escape(id)}"]`); if (tile && this.shadowRoot.activeElement && tile.contains(this.shadowRoot.activeElement)) tile.focus({ preventScroll: true }); } return; }
      // `/` goes to Ask, from anywhere that is not a text box.
      if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')) {
        const a = this.shadowRoot.querySelector('input[data-keep="ask"]');
        if (a) { e.preventDefault(); a.focus(); }
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        if (t.dataset && t.dataset.tellkey) { e.preventDefault(); this.sendTell(t.value); }
        else if (t.dataset && t.dataset.actEnter) { e.preventDefault(); this.act(t.dataset.actEnter, t); }
      }
    });
    // A compact custom card asks for its tile to open or close (house change); it
    // follows .isopen on its tile for when Morph closes it (a tap outside, a scroll away).
    root.addEventListener('morph-tile', (e) => {
      const tile = e.target && e.target.closest && e.target.closest('[data-tile]'); if (!tile) return;
      const id = tile.getAttribute('data-tile');
      if (e.detail && e.detail.open) this.openView(id, 'adv'); else if (this.s.view && this.s.view.id === id) this.closeView();
    });
    // Hover on every chart Morph draws itself (house change): the shared helper in morph-motion.js.
    const useHv = () => window.__morphHover && window.__morphHover(root, this);
    if (window.__morphHover) useHv(); else window.addEventListener('morph-motion-ready', useHv, { once: true });
    root.addEventListener('pointermove', (e) => this.scrub(e));
    root.addEventListener('pointerout', (e) => this.scrubEnd(e));
    root.addEventListener('wheel', (e) => this.upcWheel(e), { passive: false });
  }

  // Anything outside the open thing folds it back (§1.10).
  outside(e) {
    const inside = (sel) => !!(e.target.closest && e.target.closest(sel));
    const inTile = (id) => e.tile != null ? e.tile === id : inside(`[data-tile="${CSS.escape(id)}"]`);
    if (this.s.secEdit && !inside(`[data-sec-head="${CSS.escape(this.s.secEdit)}"]`)) { this.s.secEdit = null; this.schedule(); }
    // Outside Ask, the answers that are finished fold away; a question
    // still being answered stays until it is.
    if (this.s.asks.some((a) => !a.busy) && !inside('[data-ask]')) { this.s.asks = this.s.asks.filter((a) => a.busy); this.schedule(); }
    if (Object.values(this.s.story).some(Boolean) && !inside('p.story')) { this.s.story = {}; this.schedule(); }
    const t = this.s.tell;
    if (t && !inside('[data-tell]') && !(t.kind === 'card' && inTile(t.id)) && !t.sent) { this.closeTell(); }
    if (this.s.upcOpen && !inside('[data-upc], [data-cu-detail]')) { this.s.upcOpen = false; if (this._upc) this.region('upcoming', this.upcomingHtml()); }
    const v = this.s.view;
    if (v && !inTile(v.id)) {
      if ((e.tile != null || inside('[data-tile]')) && !this.s.edit) this.swallow = performance.now();
      this.closeView();
    }
  }

  onDown(e) {
    if (e.button != null && e.button !== 0) return;
    // A tap outside folds what is open (rule 10): decided on release, so a
    // scroll that starts outside does not close it mid-gesture.
    // The tile is noted now: opening a card redraws its face, so by release the
    // pressed element may be detached and no longer inside any tile (house change).
    const downTile = e.target.closest && e.target.closest('[data-tile]');
    this._lastPress = { x: e.clientX, y: e.clientY, at: Date.now() };
    this._outDown = { target: e.target, x: e.clientX, y: e.clientY, tile: downTile ? downTile.getAttribute('data-tile') : null };
    // Touching any other card folds a widened tile back (house change); so does
    // scrolling it away. Touching the widened tile itself keeps it.
    if (this.s.slideWide) {
      const other = e.target.closest && e.target.closest('[data-tile]');
      if (other && other.getAttribute('data-tile') !== this.s.slideWide) { clearTimeout(this._slideT); this.s.slideWide = null; this.schedule(); }
    }
    const t = e.target;
    // Pressing on the colour dots and sliding runs between them (house change).
    const hr = t.closest && t.closest('[data-huerow]');
    if (hr && !this.s.edit) { this.hueDown(hr, e); return; }
    // Hold a because line to ask brAIn why (§11).
    const why = t.closest && t.closest('[data-why]');
    if (why && !this.s.edit) {
      const wid = why.dataset.why;
      clearTimeout(this.whyT);
      this.whyT = setTimeout(() => { this.ptr = null; this.askWhy(wid); }, this.holdMs());
    }
    // a member strip inside an opened light group
    const mem = t.closest && t.closest('[data-member]');
    if (mem && !this.s.edit) {
      const r = mem.getBoundingClientRect(); const mp = { id: mem.dataset.member, x0: e.clientX, y0: e.clientY, r, drag: false, held: false, el: mem, pid: e.pointerId };
      // Holding a light in an opened group opens its own options and history
      // under it; holding it again folds them (house change).
      clearTimeout(this.mholdT);
      this.mholdT = setTimeout(() => { if (this.mptr !== mp || mp.drag) return; mp.held = true; haptic('medium'); const v = this.s.view; if (v) { v.member = v.member === mp.id ? null : mp.id; v.colour = null; v.H = { depth: 0 }; this.schedule(); } }, this.holdMs());
      this.mptr = mp; return;
    }
    // Inside an expanded card, a TAP on a reading that carries its entity
    // (data-eid) opens Home Assistant's own card for it (house rule).
    const er = !this.s.edit && t.closest && t.closest('[data-eid]');
    if (er && this.s.view && er.closest(`[data-tile="${CSS.escape(this.s.view.id)}"]`)) {
      this.eidTap = { eid: er.getAttribute('data-eid'), x: e.clientX, y: e.clientY };
      return;
    }
    if (t.closest && t.closest('[data-ctl], button, input, textarea, select, summary, a')) return;
    const vp = !this.s.edit && t.closest && t.closest('[data-upc-vp]');
    if (vp) { this.upcDown(e, vp); return; }
    // Coming up unfolded under a card is not part of that card: a press on
    // it is not a tap on the card, and a hold in Edit holds the strip.
    const strip = t.closest && t.closest('[data-region="upcoming"]');
    if (strip && !this.s.edit) return;
    // hold-to-tell on the top regions, floors and section heads (Edit only)
    const holdable = t.closest && t.closest('[data-hold]');
    const head = t.closest && t.closest('.sechead');
    if (this.s.edit && head) { this.secDown(head.getAttribute('data-sec-head'), e); return; }
    if (this.s.edit && holdable && (!t.closest('.mtile') || strip)) {
      const key = holdable.dataset.hold;
      const [kind, id] = key.includes(':') ? key.split(':') : [key, ''];
      this.holdStart('top:' + key, { kind, id }, e);
      return;
    }
    const mt = t.closest && t.closest('.mtile');
    if (!mt) return;
    const id = mt.dataset.mt;
    if (id.startsWith('k:') || id.startsWith('kf:')) return;
    // THEN is a picture of the past: nothing on it can be pressed.
    const hit = id.startsWith('add@') ? null : this.findCard(id);
    const T = hit ? typeOf(hit.card) : null;
    const ctx = hit ? { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null } : null;
    // An opened card never toggles or slides from its body: only its face
    // does, and an opened light group only through its rows (house change).
    const quiet = !!(hit && !this.s.edit && this.s.view && this.s.view.id === id && (!(t.closest && t.closest('.face')) || ['light_group', 'cover_group', 'fan_group'].includes(hit.card.type)));
    const slide = hit && !this.s.edit && !quiet && T.slide ? T.slide(ctx) : null;
    const r = mt.getBoundingClientRect();
    // In an opened card, a tap on its own name opens Home Assistant's entity
    // card (house rule); on the compact face the name is part of the card.
    const nb = hit && hit.card.entity && !this.s.edit && this.s.view && this.s.view.id === id && t.closest && t.closest('b');
    const onName = !!(nb && mt.contains(nb) && nb.textContent.trim() === String(this.cardName(hit.card, hit.sec) || '').trim());
    this.ptr = { id, x0: e.clientX, y0: e.clientY, drag: false, held: false, el: mt, r, slide, pid: e.pointerId, noOpen: T && T.noOpen, onName, quiet };
    if (id.startsWith('add@')) return;
    clearTimeout(this.holdT);
    if (this.s.edit) {
      this.s.hold = id; this.schedule();
      this.holdT = setTimeout(() => { if (this.ptr && this.ptr.id === id && !this.ptr.drag) { this.ptr.held = true; this.openTell({ kind: 'card', id }); } }, this.holdMs());
      return;
    }
    if (!(T && T.noOpen)) {
      this.holdT = setTimeout(() => {
        if (!(this.ptr && this.ptr.id === id && !this.ptr.drag)) return;
        this.ptr.held = true; this.s.hold = null;
        // A hold opens the card in place, with its options and history (rule 2).
        if (!(this.s.view && this.s.view.id === id)) this.openView(id, 'adv');
      }, this.holdMs());
      this.s.hold = id; this.schedule();
    }
  }

  // A slid level is felt in steps of 10 %, and its ends firmer (house change, Oct 2026).
  detent(p, was, now) {
    if (was == null || was === now) return;
    if (now === 0 || now === 100) { haptic('heavy'); return; }
    if (Math.floor(was / 10) !== Math.floor(now / 10)) { haptic('light'); return; }
    if (Math.floor(was / 2) !== Math.floor(now / 2)) haptic('selection');
  }

  holdMs() { return this.settings().hold_ms || HOLD_MS; }

  onMove(e) {
    if (this.hptr) { this.hueMove(e); return; }
    if (this.upcD) { this.upcMove(e); return; }
    if (this.whyT && Math.hypot(e.movementX || 0, e.movementY || 0) > 8) clearTimeout(this.whyT);
    const mp = this.mptr;
    if (mp) {
      const dx = e.clientX - mp.x0, dy = e.clientY - mp.y0;
      if (mp.held) return;
      if (!mp.drag) { if (Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy) && !(mp.id.startsWith('fan.') && !fanHasSpeed(this.hass.states[mp.id]))) { mp.drag = true; clearTimeout(this.mholdT); try { mp.el.setPointerCapture(mp.pid); } catch (er) { /* fine */ } } else if (Math.abs(dy) > 10) { clearTimeout(this.mholdT); this.mptr = null; return; } }
      if (mp.drag) { const nv = Math.round(Math.max(0, Math.min(100, ((e.clientX - mp.r.left) / mp.r.width) * 100))); this.detent(mp, this.s.memberPreview && this.s.memberPreview.id === mp.id ? this.s.memberPreview.v : null, nv); this.s.memberPreview = { id: mp.id, v: nv }; this.schedule(); }
      return;
    }
    if (this.drag) { this.secMove(e); return; }
    if (this.thold && Math.hypot(e.clientX - this.thold.x, e.clientY - this.thold.y) > 8) this.holdEnd();
    const p = this.ptr; if (!p || p.held) return;
    const dx = e.clientX - p.x0, dy = e.clientY - p.y0;
    if (!p.drag) {
      if (p.slide && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) {
        p.drag = true; clearTimeout(this.holdT); this.s.hold = null; try { p.el.setPointerCapture(p.pid); } catch (er) { /* fine */ }
        // A small tile widens as you slide it, so the level has room; the level
        // then follows how far the finger moves, not where it sits (house change).
        if (p.r.width < 260 && !(this.s.view && this.s.view.id === p.id)) {
          clearTimeout(this._slideT); this.s.slideWide = p.id;
          let v0 = 0; try { v0 = Number(p.slide.get ? p.slide.get() : 0) || 0; } catch (er) { /* fine */ }
          p.rel = { v0, x0: e.clientX, span: Math.max(220, p.r.width * 2.4) };
        }
      }
      else if (Math.hypot(dx, dy) > 10) { clearTimeout(this.holdT); this.ptr = null; this.s.hold = null; this.schedule(); return; }
    }
    if (p.drag) {
      const v = p.rel ? p.rel.v0 + ((e.clientX - p.rel.x0) / p.rel.span) * 100 : ((e.clientX - p.r.left) / p.r.width) * 100;
      const nv = Math.round(Math.min(100, Math.max(0, v)));
      this.detent(p, this.s.previews[p.id], nv);
      this.s.previews[p.id] = nv; this.schedule();
    }
  }

  onUp(e) {
    const od = this._outDown; this._outDown = null;
    if (od && Math.hypot(e.clientX - od.x, e.clientY - od.y) <= 10) this.outside(od);
    // A tap on a reading or name that carries its entity (data-eid) in an
    // opened card opens Home Assistant's own card for it (house rule).
    const et = this.eidTap; this.eidTap = null;
    if (et && Math.hypot(e.clientX - et.x, e.clientY - et.y) <= 10) { this._swallowClickUntil = performance.now() + 400; this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: et.eid }, bubbles: true, composed: true })); return; }
    if (this.hptr) { this.hueUp(e); return; }
    clearTimeout(this.whyT);
    if (this.upcD) { this.upcUp(e); return; }
    const mp = this.mptr;
    if (mp) {
      this.mptr = null; clearTimeout(this.mholdT);
      if (mp.held) return;
      if (mp.drag && this.s.memberPreview) { const v = this.s.memberPreview.v; this.call(mp.id.startsWith('fan.') ? { domain: 'fan', service: v <= 1 ? 'turn_off' : 'set_percentage', data: v <= 1 ? { entity_id: mp.id } : { entity_id: mp.id, percentage: v } } : mp.id.startsWith('cover.') ? { domain: 'cover', service: 'set_cover_position', data: { entity_id: mp.id, position: v <= 1 ? 0 : v } } : v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: mp.id } } : { domain: 'light', service: 'turn_on', data: { entity_id: mp.id, brightness_pct: v } }); this.settlePreview(mp.id, () => { this.s.memberPreview = null; }); }
      // Tapping a light in an opened group toggles that light; sliding sets
      // its level, holding opens its options (house change).
      else if (!mp.drag) this.call({ domain: mp.id.split('.')[0], service: 'toggle', data: { entity_id: mp.id } });
      { const at = this.tileOf(mp.el); this.track('toggle', at.card, at.section, mp.id); }
      return;
    }
    if (this.drag) { this.secUp(); return; }
    this.holdEnd();
    const p = this.ptr; clearTimeout(this.holdT); this.ptr = null;
    if (this.s.hold) { this.s.hold = null; this.schedule(); }
    const sw = this.swallow && performance.now() - this.swallow < 700; this.swallow = 0;
    if (!p) return;
    if (p.drag) {
      const v = this.s.previews[p.id];
      if (p.slide && v != null) { this.call(p.slide.call(v)); const hit = this.findCard(p.id); this.track('slide', p.id, hit && hit.sec.id); this.noteUse(p.id); }
      const hit = this.findCard(p.id);
      this.settlePreview(hit && hit.card.entity, () => { delete this.s.previews[p.id]; });
      // Let go: a tile that took the free room at its row's end gives it back
      // at once. It never moved column or row, so nothing else moves (rule 8).
      if (this.s.slideWide === p.id) { this.ptr = null; clearTimeout(this._slideT); this.s.slideWide = null; this.schedule(); }
      return;
    }
    if (p.held || sw) return;
    this.tapTile(p.id, p);
  }

  // The tap on a card (rule 2, house rule): it does the card's main thing —
  // toggles, runs, applies. A card with no main thing (a sensor, a reading)
  // opens in place instead. In an opened card, its name opens Home
  // Assistant's own card for the entity. Shared by pointer and keyboard.
  tapTile(id, p = {}) {
    if (id.startsWith('add@')) { if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'add'); return; }
    if (this.s.edit) { const v = this.s.view; if (v && v.id === id) this.closeView(); else this.openView(id, 'edit'); return; }
    this.tapCard(id, p);
  }

  // A press on a card counts as using it: it resets the card's decay.
  noteUse(id) {
    this.touched[id] = Date.now();
  }

  tapCard(id, p = {}) {
    const hit = this.findCard(id); if (!hit) return;
    const T = typeOf(hit.card);
    const ctx = { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null };
    // A tap anywhere on an opened card's own body folds it back; its name is
    // not special (household: open and close by tapping the card).
    if (p.quiet || p.onName) { if (this.s.view && this.s.view.id === id) this.closeView(); return; }
    const tap = T.tap(ctx);
    if (tap && tap.moreInfo) {
      this._swallowClickUntil = performance.now() + 400;
      this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: tap.moreInfo }, bubbles: true, composed: true }));
      this.track('open', id, hit.sec.id);
      return;
    }
    if (tap && tap.noop) return; // e.g. "turn all media off" when nothing is on
    if (tap) {
      if (tap.confirm) {
        const c = this.s.confirm[id];
        if (!c || c.until < Date.now()) { haptic('warning'); this.s.confirm[id] = { until: Date.now() + 4000, text: tap.confirm }; this.schedule(); setTimeout(() => this.schedule(), 4100); return; }
        delete this.s.confirm[id];
      }
      this.call(tap);
      { const lp = this._lastPress; const tile = this.$(`[data-tile="${CSS.escape(id)}"]`); if (lp && tile && Date.now() - lp.at < 1500) { let col = 'var(--text)'; try { col = hit.card.color ? hue(hit.card.color) : T.accent(ctx); } catch (e) { /* plain */ } if (!this.engine.reduce()) touchLight(tile, lp.x, lp.y, col); } }
      this.track('toggle', id, hit.sec.id);
      this.noteUse(id);
    } else if (!T.noOpen) {
      if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'adv');
    }
  }

  // The colour track: a tap lands on the nearest point; a sideways slide (or
  // a press held still) lifts the thumb, which snaps from white to white and
  // runs continuously through the colours; letting go sets it (house change).
  hueDown(row, e) {
    const hp = { row, ent: row.dataset.entity, x0: e.clientX, y0: e.clientY, pid: e.pointerId, on: false, v: null, k: null };
    this.hptr = hp;
    clearTimeout(this.hueT);
    this.hueT = setTimeout(() => { if (this.hptr === hp && !hp.on) this.hueStart(hp, e.clientX); }, 240);
  }

  // A redraw mid-slide replaces the row; carry on with the new one.
  hueRow(hp) {
    if (hp.row.isConnected) return hp.row;
    const r = this.rootEl.querySelector(`[data-huerow][data-entity="${CSS.escape(hp.ent)}"]`);
    if (r) { hp.row = r; if (hp.on) r.classList.add('drag'); }
    return hp.row;
  }

  hueStart(hp, x) {
    hp.on = true; const row = this.hueRow(hp); row.classList.add('drag');
    try { row.setPointerCapture(hp.pid); } catch (er) { /* fine */ }
    haptic('selection');
    this.hueAt(hp, x, false);
  }

  hueAt(hp, x, snap) {
    const row = this.hueRow(hp); let pts;
    try { pts = JSON.parse(row.dataset.pts || '[]'); } catch (er) { return; }
    const n = pts.length; if (!n) return;
    const r = row.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (x - r.left) / (r.width || 1)));
    const k = Math.max(0, Math.min(n - 1, f * n - 0.5));
    const fh = pts.findIndex((p) => p[0] === 'h');
    let pos, v, c;
    // The rainbow dot: landing on it opens the spectrum in place; nothing is
    // sent until a colour is picked from it (house change, Oct 2026).
    const rb = pts.findIndex((p) => p[0] === 'r');
    if (rb >= 0 && Math.round(k) === rb) {
      hp.v = null; hp.k = rb;
      if (this.s.view) {
        this.s.view.spectrum = { ...(this.s.view.spectrum || {}), [hp.ent]: true };
        hp.opened = x;
        const more = row.closest('.tc > [data-more]'); if (more) more.__html = null;
        row.removeAttribute('data-pin');
        haptic('heavy');
        // A dragged row is left alone by redraws (morph-dom); let this one
        // through so it opens under the finger, then hold it again.
        if (!hp.spread) {
          hp.spread = true; row.classList.remove('drag');
          this.rootEl.classList.add('cspread'); clearTimeout(this._spreadT); this._spreadT = setTimeout(() => this.rootEl.classList.remove('cspread'), 420);
          this.schedule();
          setTimeout(() => { if (this.hptr === hp) this.hueRow(hp).classList.add('drag'); }, 80);
        }
      }
      const thr = row.querySelector('.thr'); if (thr) thr.style.setProperty('--f', ((rb + 0.5) / n).toFixed(4));
      return;
    }
    // Just opened under the finger: nothing is picked until it moves on.
    if (hp.opened != null && Math.abs(x - hp.opened) < 8) return;
    hp.opened = null;
    let shown = null;
    if (snap || fh < 0 || k < fh - 0.5) {
      // Whites (and any tap) sit on their points; while sliding, the thumb is
      // drawn toward the nearest one rather than jumping to it (house change).
      pos = Math.round(k); const p = pts[pos];
      if (!snap) shown = pos + (k - pos) * 0.35;
      v = p[0] === 'k' ? { color_temp_kelvin: p[1] } : { hs_color: [p[1], 90] };
      c = p[0] === 'k' ? p[2] : hueColor(p[1]);
    } else {
      pos = Math.max(k, fh); const i = Math.floor(pos), j = Math.min(n - 1, i + 1);
      const h = Math.round(pts[i][1] + (pts[j][1] - pts[i][1]) * (pos - i));
      v = { hs_color: [((h % 360) + 360) % 360, 90] }; c = hueColor(h);
    }
    // Felt (house change, Oct 2026): each white is a big bump; the colours
    // turn like a scroll wheel, a fine tick every 10° of hue; crossing from
    // the whites into the colours is a big bump too.
    if (snap || fh < 0 || pos < fh) {
      if ((hp.k != null && hp.k !== pos) || (hp.k == null && hp.wheel != null)) haptic('heavy');
      hp.k = pos; hp.wheel = null;
    } else {
      const w = Math.floor((((v.hs_color[0] % 360) + 360) % 360) / 10);
      if (hp.k != null) haptic('heavy'); else if (hp.wheel != null && w !== hp.wheel) haptic('selection');
      hp.k = null; hp.wheel = w;
    }
    hp.v = v;
    const thr = row.querySelector('.thr'); const th = row.querySelector('.th');
    if (thr) thr.style.setProperty('--f', (((shown != null ? shown : pos) + 0.5) / n).toFixed(4));
    if (th) { th.classList.remove('none'); th.style.backgroundColor = c; }
  }

  hueMove(e) {
    const hp = this.hptr;
    const dx = e.clientX - hp.x0, dy = e.clientY - hp.y0;
    if (!hp.on) {
      if (Math.abs(dx) > 5 && Math.abs(dx) > Math.abs(dy)) { clearTimeout(this.hueT); this.hueStart(hp, e.clientX); }
      else if (Math.abs(dy) > 10) { clearTimeout(this.hueT); this.hptr = null; }
      return;
    }
    e.preventDefault && e.preventDefault();
    this.hueAt(hp, e.clientX, false);
  }

  hueUp() {
    const hp = this.hptr; this.hptr = null; clearTimeout(this.hueT);
    if (!hp) return;
    // Not lifted: a tap, which lands on the nearest point.
    if (!hp.on) this.hueAt(hp, hp.x0, true);
    const row = this.hueRow(hp); row.classList.remove('drag');
    if (hp.k != null) { try { const n = JSON.parse(row.dataset.pts || '[]').length; const thr = row.querySelector('.thr'); if (thr && n) thr.style.setProperty('--f', ((hp.k + 0.5) / n).toFixed(4)); } catch (er) { /* fine */ } }
    // The thumb stays where it was let go until the light has answered, so
    // it does not hop back to the old colour first (house change).
    if (hp.v) {
      row.setAttribute('data-pin', String(Date.now() + 2500));
      const more = row.closest('.tc > [data-more]');
      setTimeout(() => { if (more) more.__html = null; this.schedule(); }, 2600);
    }
    this.hueSwallow = performance.now();
    if (hp.v) this.call({ domain: 'light', service: 'turn_on', data: { entity_id: hp.ent, ...hp.v } });
  }

  // A slid level stays drawn until the device reports back (or 5 s pass),
  // so the fill does not drop to the old level and climb again (house change).
  settlePreview(eid, clear) {
    const st0 = eid && this.hass.states[eid];
    const lu = st0 && st0.last_updated;
    const t0 = Date.now();
    const tick = () => {
      const st = eid && this.hass.states[eid];
      const moved = st && st.last_updated !== lu;
      if (moved || !st || Date.now() - t0 > 5000) { setTimeout(() => { clear(); this.schedule(); }, moved ? 250 : 0); return; }
      setTimeout(tick, 200);
    };
    setTimeout(tick, 400);
  }

  cancelPtr() {
    this._outDown = null; this.eidTap = null;
    if (this.upcD) { const d = this.upcD; this.upcD = null; if (this._upc) this.upcGo(this._upc, d.c); return; }
    // The browser took the touch over (a swipe that drifted vertical): a
    // widened tile gives its room back.
    if (this.s.slideWide) { clearTimeout(this._slideT); this.s.slideWide = null; this.schedule(); }
    clearTimeout(this.holdT); if (this.hptr && !this.hptr.on) { clearTimeout(this.hueT); this.hptr = null; } if (this.mptr && !this.mptr.drag) { clearTimeout(this.mholdT); this.mptr = null; } this.holdEnd(); if (this.ptr && this.ptr.drag) return; this.ptr = null; if (this.s.hold) { this.s.hold = null; this.schedule(); } }

  holdStart(key, scope, e) {
    clearTimeout(this.tholdT);
    this.thold = { key, x: e.clientX, y: e.clientY };
    this.s.hold = key; this.schedule();
    this.tholdT = setTimeout(() => { if (this.thold && this.thold.key === key) { this.thold = null; this.openTell(scope); } }, this.holdMs());
  }

  holdEnd() { clearTimeout(this.tholdT); if (this.thold) { this.thold = null; if (this.s.hold) { this.s.hold = null; this.schedule(); } } }

  // Drag a section by its title while editing; the others make room live.
  secDown(id, e) {
    if (!id) return;
    const o = this.engine.it['s:' + id]; const b = this.$('[data-board]'); if (!o || !b) return;
    const br = b.getBoundingClientRect();
    this.drag = { id, ox: e.clientX - br.left - o.x, oy: e.clientY - br.top - o.y, x: o.x, y: o.y, moved: false, sx: e.clientX, sy: e.clientY };
    try { e.target.setPointerCapture(e.pointerId); } catch (er) { /* fine */ }
    this.holdStart('sec:' + id, { kind: 'section', id }, e);
  }

  secMove(e) {
    const d = this.drag; if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 6) return;
    this.holdEnd();
    const br = this.$('[data-board]').getBoundingClientRect();
    d.x = e.clientX - br.left - d.ox; d.y = e.clientY - br.top - d.oy; d.moved = true;
    this.engine.drag = d;
    const o = this.engine.it['s:' + d.id];
    if (o) { o.x = d.x; o.y = d.y; o.vx = o.vy = 0; o.live = true; o.el.style.zIndex = '5'; o.el.style.boxShadow = '0 24px 60px rgba(0,0,0,.45)'; this.engine.paint(o); }
    const px = e.clientX - br.left, py = e.clientY - br.top; let target = null;
    Object.keys(this.engine.it).forEach((k) => { if (!k.startsWith('s:') || k === 's:' + d.id) return; const q = this.engine.it[k]; if (px > q.x + 20 && px < q.x + q.w - 20 && py > q.y + 20 && py < q.y + q.h - 20) target = k.slice(2); });
    if (target && target !== d.last && performance.now() - (d.at || 0) > 420) {
      d.last = target; d.at = performance.now(); d.target = target;
      // Reorder live, without a save, so the others make room under the finger.
      const draft = this.dash; const from = this.sectionIn(draft, d.id);
      if (target.startsWith('__new@')) {
        const fi = Number(target.split('@')[1]); const f = draft.floors[fi];
        if (from && f && from.f !== f) { from.f.sections.splice(from.i, 1); f.sections.push(from.s); this.engine.invalidate(); this.schedule(); }
      } else {
        const to = this.sectionIn(draft, target);
        if (from && to) { from.f.sections.splice(from.i, 1); const ti = to.f.sections.indexOf(to.s); to.f.sections.splice(ti, 0, from.s); this.engine.invalidate(); this.schedule(); }
      }
    }
    this.engine.run();
  }

  secUp() {
    this.holdEnd();
    const d = this.drag; this.drag = null; this.engine.drag = null;
    if (!d) return;
    const o = this.engine.it['s:' + d.id]; if (o) { o.el.style.boxShadow = ''; o.live = true; }
    if (d.moved && d.target) this.mutate('Moved a section', () => true);
    this.engine.layout(false, true);
  }

  scrub(e) {
    const ch = e.target.closest && e.target.closest('.chart[data-chart]');
    if (!ch) return;
    const r = ch.getBoundingClientRect(); const svg = ch.querySelector('svg');
    const vb = svg.viewBox.baseVal; const plotW = vb && vb.width > 600 ? r.width * (600 / vb.width) : r.width;
    const frac = Math.max(0, Math.min(1, (e.clientX - r.left) / plotW));
    const line = ch.querySelector('.scrub'); line.hidden = false; line.style.left = (frac * plotW) + 'px';
    const out = this.shadowRoot.querySelector(`[data-readout="${ch.dataset.chart}"]`);
    if (out) out.innerHTML = history.scrubAt(ch.dataset.chart, frac);
    if (ch.dataset.ov) this.paintOverlay(ch, history.overlayAt(ch.dataset.chart, frac));
  }

  // The overlay chart answers a finger in place: its labels follow the
  // instant, a dot sits on every line, and the header says the time.
  paintOverlay(ch, at) {
    if (!at) return;
    const key = ch.dataset.chart; const box = ch.closest('.ov') || ch.parentElement;
    const labs = box.querySelector(`[data-ovlabels="${key}"]`); if (labs) labs.innerHTML = at.labels;
    const dots = box.querySelector(`[data-ovdots="${key}"]`); if (dots) dots.innerHTML = at.dots;
    const sub = box.querySelector('[data-ovsub]'); if (sub) sub.textContent = at.sub;
  }

  scrubEnd(e) {
    const ch = e.target.closest && e.target.closest('.chart[data-chart]');
    if (!ch || (e.relatedTarget && ch.contains(e.relatedTarget))) return;
    const line = ch.querySelector('.scrub'); if (line) line.hidden = true;
    if (ch.dataset.ov) this.paintOverlay(ch, history.overlayRest(ch.dataset.chart));
  }

  onClick(e) {
    const el = e.target.closest && e.target.closest('[data-act]');
    if (!el) return;
    if (this.hueSwallow && performance.now() - this.hueSwallow < 500 && el.closest('[data-huerow]')) { this.hueSwallow = 0; return; }
    if (el.dataset.act === 'field') { this.pickColor(el, e); return; }
    if (el.dataset.act === 'rail') { this.pickRail(el, e); return; }
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') return;
    e.preventDefault();
    this.act(el.dataset.act, el);
  }

  onChange(e) {
    const el = e.target;
    if (el.dataset.act === 'range') {
      const scale = parseFloat(el.dataset.scale || '1');
      this.call({ domain: el.dataset.domain, service: el.dataset.service, data: { entity_id: el.dataset.entity, [el.dataset.key]: Number(el.value) * scale } });
      return;
    }
    if (el.dataset.actChange) this.act(el.dataset.actChange, el);
  }

  pickColor(el, e) {
    const r = el.getBoundingClientRect();
    const h = Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * 360);
    const s = Math.round(Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) * 100);
    this.call({ domain: 'light', service: 'turn_on', data: { entity_id: el.dataset.entity, hs_color: [h, Math.max(8, s)] } });
    // The colour field folds away once a colour is picked (house change).
    if (this.s.view && this.s.view.colour) { this.s.view.colour = null; this.schedule(); }
  }

  // The colour rail: whites on its left part (warm to daylight), hues on
  // the rest (house change).
  pickRail(el, e) {
    const r = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const wf = parseFloat(el.dataset.wf || '0');
    const data = { entity_id: el.dataset.entity };
    if (x < wf || wf >= 1) { const lo = Number(el.dataset.lo), hi = Number(el.dataset.hi); data.color_temp_kelvin = Math.round(lo + (hi - lo) * (x / wf)); }
    else data.hs_color = [Math.round(((x - wf) / (1 - wf || 1)) * 360) % 360, 88];
    this.call({ domain: 'light', service: 'turn_on', data });
    const i = el.querySelector('i');
    if (i) i.style.left = (Math.max(0.012, Math.min(0.988, x)) * 100).toFixed(2) + '%';
  }

  // Armed confirm buttons ("Tap again"), kept on their button across redraws;
  // with `k` and `orig`, that one button gets its own words back.
  applyConfirms(k, orig) {
    const root = this.shadowRoot; if (!root) return;
    root.querySelectorAll('[data-act="svc"][data-confirm]').forEach((b) => {
      const key = 'btn:' + b.dataset.service + b.dataset.data;
      const c = this.s.confirm[key];
      if (c && c.until > Date.now()) { if (b.textContent !== c.text) b.textContent = c.text; }
      else if (k === key && orig != null && b.textContent !== orig) b.textContent = orig;
    });
  }

  // A room marked `sleep_guard: true` asks first while its sleeper is asleep
  // (a child's room): anything this page would do to the room (a light, the fan, a
  // scene, a slide) is held, and the room's header asks to send it. Once
  // confirmed, the room stays unlocked for a short while so a slide or two
  // more does not ask again.
  sleepGuard(c) {
    if (this.s.edit) return null;
    const d = c.data || {}; const ids = [].concat(d.entity_id || (c.target && c.target.entity_id) || []).map(String);
    if (!ids.length) return null;
    let hit = null;
    this.eachSection((sec) => {
      if (hit || !sec.sleep_guard || !this.asleepSince(sec)) return;
      if ((this._sleepOk || {})[sec.id] > Date.now()) return;
      const ents = new Set(this.sectionEntities(sec)); this.areaEntities(sec).forEach((e) => ents.add(e));
      this.headCards(sec).forEach((x) => (x.entities || []).forEach((e) => ents.add(e)));
      (sec.scenes || []).forEach((e) => ents.add(e));
      if (ids.some((e) => ents.has(e))) hit = sec;
    });
    return hit;
  }

  sleepAskHtml(sec) {
    const a = this.s.sleepAsk;
    if (!a || a.sec !== sec.id || a.until < Date.now()) return '';
    const who = String(sec.title || '').replace(/[’']s\s+room$/i, '') || 'This room';
    return `<div class="sleepask" data-ctl="1" role="alert"><svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg><span>${esc(who)} is asleep</span><button type="button" class="wd" data-act="sleep-ok" data-v="${esc(sec.id)}">Send anyway</button></div>`;
  }

  call(c) {
    if (!c) return;
    { const ids = [].concat((c.data || {}).entity_id || []).map(String); const now = Date.now(); this._mine = this._mine || new Map(); ids.forEach((e) => this._mine.set(e, now)); if (['scene', 'script', 'automation', 'input_select'].includes(c.domain) || ids.some((e) => /^(scene|script|light\.(everything|inside|downstairs|upstairs|outside))/.test(e))) this._quietUntil = now + 6000; }
    const g = this.sleepGuard(c);
    if (g) {
      const ask = (this.s.sleepAsk = { sec: g.id, c, until: Date.now() + 6000 });
      haptic('warning');
      this.engine.invalidate(); this.schedule();
      setTimeout(() => { if (this.s.sleepAsk === ask) { this.s.sleepAsk = null; this.s.previews = {}; this.engine.invalidate(); this.schedule(); } }, 6100);
      return;
    }
    // Every action the page sends is felt (house change, Oct 2026).
    haptic(c.domain === 'scene' ? 'medium' : 'light');
    const p = this.hass.callService(c.domain, c.service, c.data || {});
    if (p && p.catch) p.catch((err) => this.toast(`${c.domain}.${c.service}: ${err.message || err}`));
  }

  // Every press, with its failure said rather than lost as an unhandled
  // rejection.
  act(name, el) {
    return this.doAct(name, el).catch((e) => this.toast(`That did not work: ${(e && e.message) || e}`));
  }

  async doAct(name, el) {
    const v = el.dataset.v;
    const H = this.hass;
    switch (name) {
      case 'retry-load': this.retryLoad(); return;
      // A clause of the verdict, a trace, or a room word: scroll the thing
      // it names under the sentence, already unfolded.
      case 'jump': this.jumpTo(v); return;
      case 'notes-toggle': this.s.notesOpen = { ...(this.s.notesOpen || {}), [v]: !this.notesOpen(v) }; this.engine.invalidate(); this.schedule(); return;
      case 'room': this.scrollToRoom(v); return;
      case 'case': {
        const r = await this.caseRequest(el.dataset.case, v, '');
        if (r && r.ok && ['dismiss', 'todo', 'snooze', 'not_applicable'].includes(v)) this.markAnswered(el.dataset.case);
        this.toast(r && r.ok ? ({ dismiss: 'Dismissed.', todo: 'Added to To Do.', snooze: 'Snoozed.', not_applicable: 'Closed.', fix: `${this.who()} is working out a plan.`, apply: `${this.who()} is making the change.` }[v] || `Told ${this.who()}.`) : (r && r.error) || `${this.who()} did not take that.`);
        return;
      }
      case 'case-reply': {
        if (el.tagName === 'BUTTON') { const row = el.closest('.replyrow'); const inp = row && row.querySelector('.replyin'); if (!inp) return; el = inp; }
        const text = String(el.value || '').trim(); if (!text) return;
        const cid = el.dataset.case;
        const c = this.caseById(cid);
        this.s.pending[cid] = { at: Date.now(), n: (c && c.thread ? c.thread.length : 0), word: `Sent. ${this.who()} answers here.` };
        el.value = '';
        const r = await this.caseRequest(cid, 'reply', text);
        if (!r || !r.ok) { delete this.s.pending[cid]; this.toast((r && r.error) || `${this.who()} did not take that.`); }
        this.schedule(); return;
      }
      case 'case-open-reply': this.s.replyOpen[el.dataset.case] = true; this.schedule(); return;
      case 'keep': this.mutate('Kept a card in Now', (d) => { const h = this.cardIn(d, v); if (!h) return false; h.c.pin = true; }); this.lesson(v, true); return;
      case 'unpin': this.mutate('Stopped keeping a card in Now', (d) => { const h = this.cardIn(d, v); if (!h) return false; delete h.c.pin; }); return;
      case 'not-this': {
        this.suppressed[v] = new Date().toDateString();
        try { localStorage.setItem('morph.notthis', JSON.stringify(this.suppressed)); } catch (e) { /* storage refused: for this visit only */ }
        this.closeView(); this._salDirty = true; this._forceApply = true; this.schedule(); return;
      }
      case 'menu': this.dispatchEvent(new Event('hass-toggle-menu', { bubbles: true, composed: true })); return;
      // Back to the dashboard, in Edit.
      case 'edit-dash':
        this.s.edit = true; this.s.view = null; this.s.tell = null; this.s.secEdit = null; this.s.yaml = null;
        this.engine.invalidate(); this.cache.clear(); haptic('medium'); this.schedule();
        { const sc = this.$('.scroll'); if (sc) sc.scrollTop = 0; }
        return;
      // brAIn's own page, in the shell's frame: ⚙ › Dashboard for Morph's
      // settings, or a view (Insights, Ask).
      case 'brain-open': this.openBrain(v === 'dashboard' ? 'settings' : v, v === 'dashboard' ? 'dashboard' : ''); return;
      case 'edit':
        this.s.edit = !this.s.edit; this.s.view = null; this.s.tell = null; this.s.secEdit = null; this.s.yaml = null;
        this.engine.invalidate(); this.cache.clear(); if (!this.s.edit) this.load(); this.schedule(); return;
      case 'yaml-toggle':
        if (this.s.yaml != null) { this.s.yaml = null; this.schedule(); return; }
        try { const r = await H.callWS({ type: 'morph/yaml' }); this.s.yaml = r.text || ''; } catch (e) { this.toast(String(e.message || e)); }
        this.schedule(); return;
      case 'yaml-save': {
        const ta = this.shadowRoot.querySelector('textarea[data-keep="yaml"]'); if (!ta) return;
        const r = await H.callWS({ type: 'morph/request', kind: 'save_yaml', payload: { text: ta.value } });
        if (r.ok) { this.toast('Saved dashboard.yaml', r.commit); this.s.yaml = null; this.dash = null; this.load(); } else this.toast(r.error || 'Not saved.');
        return;
      }
      case 'undo-commit': {
        const r = await H.callWS({ type: 'morph/request', kind: 'undo_commit', payload: { sha: v } });
        this.toast(r.ok ? 'Put back.' : r.error); this.dash = null; this.load(); return;
      }
      case 'svc': {
        if (el.dataset.confirm) {
          // "Tap again" stays on the button for its 4 s however often the card
          // redraws (applyConfirms), then the button reads as it did.
          const k = 'btn:' + el.dataset.service + el.dataset.data;
          const c = this.s.confirm[k];
          if (!c || c.until < Date.now()) {
            const entry = (this.s.confirm[k] = { until: Date.now() + 4000, text: el.dataset.confirm, orig: el.textContent });
            this.applyConfirms();
            setTimeout(() => { if (this.s.confirm[k] === entry) { delete this.s.confirm[k]; this.applyConfirms(k, entry.orig); } }, 4100);
            return;
          }
          const orig = c.orig; delete this.s.confirm[k]; this.applyConfirms(k, orig);
        }
        let data = {}; try { data = JSON.parse(el.dataset.data || '{}'); } catch (e) { /* none */ }
        this.call({ domain: el.dataset.domain, service: el.dataset.service, data });
        { const at = this.tileOf(el); this.track('toggle', at.card, at.section, data.entity_id && String(data.entity_id)); }
        return;
      }
      // A picker in a card (a siren's tone): pick that option (house change, Oct 2026).
      case 'sel': if (el.dataset.entity && el.value) this.call({ domain: el.dataset.entity.split('.')[0] === 'input_select' ? 'input_select' : 'select', service: 'select_option', data: { entity_id: el.dataset.entity, option: el.value } }); return;
      case 'sleep-ok': {
        const a = this.s.sleepAsk; if (!a || a.sec !== v) return;
        this._sleepOk = { ...(this._sleepOk || {}), [v]: Date.now() + 90000 };
        haptic('success');
        this.s.sleepAsk = null; this.engine.invalidate(); this.call(a.c); this.schedule();
        return;
      }
      case 'scene': {
        this.call({ domain: 'scene', service: 'turn_on', data: { entity_id: v } }); this.track('scene', null, null, v);
        // The highlight moves now, and the room's lights ripple outward from the words (house change).
        const grp = el.closest('.secscenes'); if (grp) { grp.querySelectorAll('[aria-pressed]').forEach((b) => b.setAttribute('aria-pressed', String(b === el))); this.placeThumbs(); }
        const secEl = el.closest('[data-sec]');
        if (secEl && !this.engine.reduce()) {
          const o = el.getBoundingClientRect(); const ox = o.left + o.width / 2, oy = o.top + o.height / 2;
          const lights = [...secEl.querySelectorAll(':scope > .tile[data-tile]')].filter((t) => { const h2 = this.findCard(t.getAttribute('data-tile')); return !!(h2 && h2.card.entity && h2.card.entity.startsWith('light.')); });
          lights.map((t) => { const r = t.getBoundingClientRect(); return { t, d: Math.hypot(r.left + r.width / 2 - ox, r.top + r.height / 2 - oy) }; }).sort((a, b) => a.d - b.d).forEach((x, i) => {
            const m = x.t.querySelector('.mtile'); if (!m) return; m.style.animationDelay = (i * 35) + 'ms'; m.classList.remove('mripple'); void m.offsetWidth; m.classList.add('mripple'); setTimeout(() => { m.classList.remove('mripple'); m.style.animationDelay = ''; }, 900 + i * 35);
          });
        }
        return;
      }
      case 'head-toggle': { const hit = this.findCard(el.dataset.card); this.call({ domain: 'homeassistant', service: 'toggle', data: { entity_id: v } }); this.track('toggle', el.dataset.card, hit && hit.sec.id); return; }
      case 'tgt': {
        const tile = el.closest('[data-tile]'); const hit = tile && this.findCard(tile.getAttribute('data-tile')); if (!hit) return;
        const st = H.states[hit.card.entity]; if (!st) return;
        const step = st.attributes.target_temp_step || (String(H.config.unit_system.temperature).includes('F') ? 1 : 0.5);
        // A range (heat/cool) thermostat takes both setpoints together; taps
        // in quick succession build on the last one sent, not the stale state.
        const a = st.attributes; const k = el.dataset.k || (a.temperature != null ? 't' : 'lo');
        const r1 = (x) => Math.round(x * 10) / 10;
        const pd = climatePending.get(hit.card.entity); const pend = pd && pd.until > Date.now() ? pd : null;
        const lim = (x) => Math.min(a.max_temp != null ? a.max_temp : 99, Math.max(a.min_temp != null ? a.min_temp : 0, x));
        let data;
        if (k === 't' || a.target_temp_low == null || a.target_temp_high == null) {
          const base = pend && pend.t != null ? pend.t : a.temperature != null ? a.temperature : a.target_temp_low;
          data = { entity_id: hit.card.entity, temperature: r1(lim(base + step * Number(v))) };
        } else {
          let lo = pend && pend.lo != null ? pend.lo : a.target_temp_low, hi = pend && pend.hi != null ? pend.hi : a.target_temp_high;
          const gap = step * 2;
          if (k === 'lo') { lo = lim(lo + step * Number(v)); if (hi - lo < gap) hi = lim(lo + gap); } else { hi = lim(hi + step * Number(v)); if (hi - lo < gap) lo = lim(hi - gap); }
          data = { entity_id: hit.card.entity, target_temp_low: r1(lo), target_temp_high: r1(hi) };
        }
        // The face shows the new setpoint at once (muted until the thermostat
        // reports it); quick taps are gathered and sent once, 0.6 s after the last.
        const eid = hit.card.entity;
        climatePending.set(eid, { t: data.temperature, lo: data.target_temp_low, hi: data.target_temp_high, until: Date.now() + 8000 });
        this.schedule();
        this._tgtT = this._tgtT || {};
        clearTimeout(this._tgtT[eid]);
        this._tgtT[eid] = setTimeout(() => { delete this._tgtT[eid]; this.call({ domain: 'climate', service: 'set_temperature', data }); }, 600);
        this.track('slide', hit.card.id, hit.sec.id); return;
      }
      case 'colour': if (this.s.view) { this.s.view.colour = this.s.view.colour === v ? null : v; this.schedule(); } return;
      case 'member': {
        const tile = el.closest('[data-tile]'); const id = tile && tile.getAttribute('data-tile');
        if (!id) return;
        if (!(this.s.view && this.s.view.id === id)) this.openView(id, 'adv');
        this.s.view.member = v; this.s.view.H = { depth: 0 }; this.schedule(); return;
      }
      case 'h-open': if (this.s.view) { this.s.view.H = { depth: 1, day: null }; this.track('history', this.s.view.id); this.schedule(); } return;
      case 'h-range': if (this.s.view) { this.s.view.H = { ...this.s.view.H, depth: 1, range: v === 'week' ? 'week' : 'day' }; this.schedule(); } return;
      case 'h-day': if (this.s.view) { this.s.view.H = { depth: 1, day: Number(v) }; this.schedule(); } return;
      case 'h-hour': if (this.s.view) { this.s.view.H = { ...this.s.view.H, depth: 2, hour: Number(v) }; this.schedule(); } return;
      case 'h-back': if (this.s.view) { const d = Number(v); this.s.view.H = d === 0 ? { depth: 0 } : { ...this.s.view.H, depth: d }; this.schedule(); } return;
      case 'r-focus': {
        const tile = el.closest('[data-tile]'); const id = tile && tile.getAttribute('data-tile');
        this.s.rfocus = this.s.rfocus || {};
        this.s.rfocus[id] = this.s.rfocus[id] === v ? null : v; this.schedule(); return;
      }
      case 'alarm': {
        const tile = el.closest('[data-tile]'); const hit = tile && this.findCard(tile.getAttribute('data-tile'));
        const code = tile.querySelector('[data-alarm-code]');
        if (hit) this.call({ domain: 'alarm_control_panel', service: el.dataset.service, data: { entity_id: hit.card.entity, code: code ? code.value : undefined } });
        if (code) code.value = '';
        return;
      }
      case 'story': this.s.story[v] = !this.s.story[v]; this.schedule(); return;
      case 'reveal': this.revealEntity(v); return;
      case 'reveal-card': this.revealCard(v); return;
      case 'upc': if (v) this.revealEntity(v); return;
      case 'upc-now': if (this._upc) this.upcGo(this._upc, 0); return;
      case 'upc-kind': upc.toggleKind(v); haptic('selection'); this.region('upcoming', this.upcomingHtml()); return;
      case 'upc-open': this.s.upcOpen = !this.s.upcOpen; haptic(this.s.upcOpen ? 'light' : 'selection'); this.region('upcoming', this.upcomingHtml()); return;
      case 'upc-exp': upc.toggleExpanded(); this.region('upcoming', this.upcomingHtml()); return;
      case 'upc-paint': upc.togglePainting(); this.region('upcoming', this.upcomingHtml()); return;
      case 'upc-color': upc.pickColor(v); this.region('upcoming', this.upcomingHtml()); return;
      case 'upc-zoom': this.upcZoomTo(v === 'reset' ? upc.ZOOM_MIN : v === 'in' ? (upc.getZoom() <= upc.ZOOM_MIN ? 2 : upc.getZoom() * 1.5) : upc.getZoom() / 1.5); return;
      case 'ask-sug': {
        const inp = this.shadowRoot.querySelector('input[data-keep="ask"]');
        if (inp) inp.value = v;
        this.act('ask', inp || { value: v, dataset: {} }); return;
      }
      case 'ask': this.ask(el.value || ''); if (el.value != null && el.tagName === 'INPUT') el.value = ''; return;
      // The Feed's answers to brAIn's findings and Morph's suggestions (house change).
      case 'finding': {
        const r = await H.callWS({ type: 'morph/finding', ts: Number(el.dataset.ts), action: v });
        if (r && r.ok) this.markAnswered('f:' + el.dataset.ts);
        this.toast(r && r.ok ? 'Told brAIn.' : 'brAIn did not take that.'); return;
      }
      case 'sug-no': this.s.sugNo = el.dataset.id; this.schedule(); return;
      case 'sug-cancel': this.s.sugNo = null; this.schedule(); return;
      case 'sug': {
        const note = v === 'no' ? ((this.shadowRoot.querySelector('input[data-keep="sugno"]') || {}).value || '') : '';
        // Show the press at once: "Do it" turns into the working line, the
        // other answers drop the card, until the server's answer is in.
        const busy = this.s.sugBusy = this.s.sugBusy || {};
        busy[el.dataset.id] = v; this.s.sugNo = null; this.schedule();
        let r;
        try { r = await H.callWS({ type: 'morph/request', kind: 'suggestion', payload: { id: el.dataset.id, verb: v, note } }); } catch (e) { r = { ok: false, error: String(e.message || e) }; }
        if (!r.ok) delete busy[el.dataset.id];
        else setTimeout(() => { delete busy[el.dataset.id]; this.schedule(); }, 6000);
        this.toast(r.ok ? (v === 'do' ? 'Handed to brAIn.' : v === 'send' ? 'Sent as an issue.' : v === 'no' ? 'Morph will not suggest that again.' : 'Later, then.') : r.error);
        this.load(); return;
      }
      // tell
      case 'tell-sug': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); if (ta) { ta.value = v; this.s.tell.draft = v; ta.focus(); } return; }
      case 'tell-send': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); this.sendTell(ta ? ta.value : ''); return; }
      case 'tell-cancel': this.closeTell(); return;
      case 'tell-refresh': this.dash = null; this.load(); return;
      case 'ask-tell': { const a = this.s.asks.find((x) => x.key === v); if (a) { this.askDrop(a); this.tellDashboard(a.q); } return; }
      case 'tell-keep': this.closeTell(); this.load(); return;
      case 'reload-page': location.reload(); return;
      case 'tellkey': try { localStorage.setItem('morph.tellkey', this.tellKeyOn() ? '0' : '1'); } catch (e) { /* storage refused */ } this.cache.delete('r:settings'); this.schedule(); return;
      case 'code-reset': {
        const r = await H.callWS({ type: 'morph/request', kind: 'code_reset', payload: { name: v } });
        if (r.ok) { this.toast(`Morph’s own ${v} is back. Reloading…`, r.commit); setTimeout(() => location.reload(), 900); } else this.toast(r.error);
        return;
      }
      case 'code-redo': {
        // The press opens brAIn's box in the note it was made from: steps
        // while it works, then the result with Reload and Undo. A toast in
        // the header and an unchanged note read as nothing happening.
        if (this.s.redo && this.s.redo.name === v && !this.s.redo.error) return;
        this.s.redo = { name: v, at: Date.now() / 1000 }; this.schedule();
        let r;
        try { r = await H.callWS({ type: 'morph/request', kind: 'code_redo', payload: { name: v } }); } catch (e) { r = { ok: false, error: String(e.message || e) }; }
        if (!r || !r.ok || !r.id) { this.s.redo = { name: v, error: (r && r.error) || 'Morph could not hand that to brAIn.' }; this.schedule(); this.load(); return; }
        this.s.redo = null;
        this.s.tell = { kind: 'code', id: v, label: v, path: `Morph’s own ${v}`, text: `Update my change to ${v} for the new Morph`, sent: true, tellId: r.id, state: r, turns: [] };
        this.pollTell(true); this.load(); return;
      }
      case 'code-merge-all': {
        // Update with several copies paused: ONE Tell and one commit for
        // every one of them, conflicts asked as questions in the same box.
        if (this.s.redo && this.s.redo.name === 'all' && !this.s.redo.error) return;
        this.s.redo = { name: 'all', at: Date.now() / 1000 }; this.schedule();
        let r;
        try { r = await H.callWS({ type: 'morph/request', kind: 'code_merge_all', payload: {} }); } catch (e) { r = { ok: false, error: String(e.message || e) }; }
        if (!r || !r.ok || !r.id) { this.s.redo = { name: 'all', error: (r && r.error) || 'Morph could not hand that to brAIn.' }; this.schedule(); this.load(); return; }
        this.s.redo = null;
        this.s.tell = { kind: 'code', id: 'all', label: 'paused copies', path: 'Morph’s own code', text: 'Update all my changes for the new Morph', sent: true, tellId: r.id, state: r, turns: [] };
        this.pollTell(true); this.load(); return;
      }
      case 'code-not-now': {
        this.notNow = v; this.s.redo = null;
        try { localStorage.setItem('morph.notnow', v); } catch (e) { /* storage refused: hidden until the page reloads */ }
        this.schedule(); return;
      }
      case 'tell-undo': {
        const t = this.s.tell; if (!t || !t.tellId) return;
        const r = await H.callWS({ type: 'morph/request', kind: 'tell_undo', payload: { id: t.tellId } });
        if (r.ok) {
          t.state = { ...t.state, undone: true, say: r.follow ? 'The dashboard is back. brAIn is putting back what it changed in Home Assistant.' : 'Put back.' }; this.dash = null; this.load();
          // Morph's own code went back too: it runs once the page reloads.
          if ((t.state.code || []).length) { this.toast('Put back. Reloading to run Morph’s own code…'); setTimeout(() => location.reload(), 900); }
        }
        else this.toast(r.error);
        this.schedule(); return;
      }
      case 'tell-more': {
        const t = this.s.tell;
        const turns = [...(t.turns || []), { text: t.text, say: (t.state && t.state.say) || '', before: t.shot && t.shot.url, after: t.after }];
        this.s.tell = { kind: t.kind, id: t.id, label: t.label, entity: t.entity, path: t.path, text: '', sent: false, draft: '', previous: t.tellId, turns };
        if (t.kind !== 'code') this.shoot(this.s.tell); // brAIn sees how it looks NOW
        this.schedule(); return;
      }
      case 'rmk-svc': { const i = v.indexOf('|'); const [d, sv] = v.slice(0, i).split('.'); haptic('light'); this.call({ domain: d, service: sv, data: { entity_id: v.slice(i + 1) } }); return; }
      case 'more-info': this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: v }, bubbles: true, composed: true })); return;
      case 'open-device': window.history.pushState(null, '', `/config/devices/device/${encodeURIComponent(v)}`); window.dispatchEvent(new CustomEvent('location-changed', { detail: { replace: false } })); return;
      case 'tell-answer': {
        const t = this.s.tell; if (!t || !t.tellId || t.answering) return;
        const q = t.state && t.state.question; const o = q && q.options[Number(v)]; if (!o) return;
        t.answering = true; this.schedule();
        let r;
        try { r = await H.callWS({ type: 'morph/request', kind: 'tell_answer', payload: { id: t.tellId, choice: Number(v) } }); } catch (e) { r = { ok: false, error: String(e.message || e) }; }
        t.answering = false;
        if (!r || !r.ok || !r.id) { this.toast((r && r.error) || 'Morph could not hand that to brAIn.'); this.schedule(); return; }
        const turns = [...(t.turns || []), { text: t.text, say: (t.state && t.state.say) || '', before: t.shot && t.shot.url, after: t.after }];
        this.s.tell = { kind: t.kind, id: t.id, label: t.label, entity: t.entity, path: t.path, text: o.request, sent: true, tellId: r.id, state: r, previous: t.tellId, turns };
        this.pollTell(true); return;
      }
      case 'tell-issue': {
        const t = this.s.tell; if (!t || !t.tellId) return;
        const r = await H.callWS({ type: 'morph/request', kind: 'tell_issue', payload: { id: t.tellId, verb: v } });
        if (r.ok) { t.state = { ...t.state, issue: v === 'send' ? 'sent' : 'declined' }; if (v === 'send') this.toast('Sent as an issue.'); }
        else this.toast(r.error);
        this.schedule(); return;
      }
      case 'shot-zoom': { if (this.s.tell) { this.s.tell.zoom = !this.s.tell.zoom; this.schedule(); } return; }
      case 'activity-open': {
        // A tell this page parked is the same object again, its turns and
        // its picture with it.
        if (this.tellsAway.some((x) => x.tellId === v)) { await this.doAct('tell-back', el); this.pollTell(true); return; }
        const a = (((this.data && this.data.state) || {}).activity || []).find((x) => x.id === v); if (!a) return;
        const st = this.tellStatus[v] || { phase: a.phase, steps: [], started: a.started };
        this.s.tell = { kind: a.kind || 'dashboard', id: a.target || '', label: a.label, path: a.path, text: a.kind === 'code' ? String(a.text || '').split('\n')[0] : a.text, sent: true, tellId: a.id, state: st, turns: [] };
        if (a.kind === 'card' && a.target && this.findCard(a.target)) this.openView(a.target, 'tell');
        this.pollTell(true); this.schedule(); return;
      }
      // feed
      case 'tell-back': {
        const t = this.tellsAway.find((x) => x.tellId === v); if (!t) return;
        this.tellsAway = this.tellsAway.filter((x) => x !== t);
        t.state = this.tellStatus[v] || t.state;
        this.s.tell = t;
        if (t.kind === 'card' && t.id && this.findCard(t.id)) this.openView(t.id, 'tell');
        this.schedule(); return;
      }
      case 'close': this.closeView(); return;
      // editing
      case 'sec-edit': this.s.secEdit = this.s.secEdit === v ? null : v; this.schedule(); return;
      case 'sec-title': this.mutate(`Renamed ${el.value}`, (d) => { const h = this.sectionIn(d, v); if (!h || !el.value.trim()) return false; h.s.title = el.value.trim(); }); return;
      case 'sec-hue': this.mutate('Changed a section’s color', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.color = el.dataset.h; }); return;
      case 'sec-width': this.mutate('Changed a section’s width', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.width = Number(el.dataset.w); }); return;
      case 'sec-floor': this.mutate('Moved a section to another floor', (d) => { const h = this.sectionIn(d, v); const f = d.floors.find((x) => x.id === el.dataset.f); if (!h || !f || h.f === f) return false; h.f.sections.splice(h.i, 1); f.sections.push(h.s); }); return;
      case 'sec-floor-new': this.mutate('Added a floor', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.f.sections.splice(h.i, 1); d.floors.push({ title: 'New floor', sections: [h.s] }); }); return;
      case 'sec-group': this.mutate('Added a group', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.groups = h.s.groups || []; h.s.groups.push({ label: 'New group', cards: [] }); }); return;
      case 'sec-hide': this.mutate('Hid or showed a section', (d) => { const h = this.sectionIn(d, v); if (!h) return false; if (h.s.hidden) delete h.s.hidden; else h.s.hidden = true; }); return;
      case 'sec-remove': this.s.secEdit = null; this.mutate('Removed a section', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.f.sections.splice(h.i, 1); }); return;
      case 'add-section': this.mutate('Added a section', (d) => { const f = d.floors.find((x) => x.id === v); if (!f) return false; f.sections.push({ title: 'New section', color: HUES[(f.sections.length + 3) % HUES.length], width: 2, groups: [{ cards: [] }] }); }); return;
      case 'card-name': this.mutate('Renamed a card', (d) => { const h = this.cardIn(d, v); if (!h) return false; if (el.value.trim()) h.c.name = el.value.trim(); else delete h.c.name; }); return;
      case 'card-head': { const on = !isHeadCard(this.findCard(v) && this.findCard(v).card); this.mutate(on ? 'Moved a switch to its title row' : 'Moved a switch back to a tile', (d) => { const h = this.cardIn(d, v); if (!h || h.c.type !== 'switch') return false; const o = { ...(h.c.options || {}) }; if (on) o.header = true; else delete o.header; if (Object.keys(o).length) h.c.options = o; else delete h.c.options; }); } return;
      case 'card-span': this.mutate('Resized a card', (d) => { const h = this.cardIn(d, v); if (!h) return false; const w = Number(el.dataset.w); if (w) h.c.span = w; else delete h.c.span; }); return;
      case 'card-move': this.closeView(); this.mutate('Moved a card', (d) => { const h = this.cardIn(d, v); const to = this.sectionIn(d, el.value); if (!h || !to || h.s === to.s) return false; h.g.cards.splice(h.i, 1); to.s.groups = to.s.groups || []; if (!to.s.groups.length) to.s.groups.push({ cards: [] }); to.s.groups[to.s.groups.length - 1].cards.push(h.c); }); return;
      case 'card-remove': this.closeView(); this.mutate('Removed a card', (d) => { const h = this.cardIn(d, v); if (!h) return false; h.g.cards.splice(h.i, 1); }); return;
      case 'card-yaml': {
        const ta = el.closest('details').querySelector('textarea');
        let obj; try { obj = JSON.parse(ta.value); } catch (e) { this.toast('That is not valid JSON: ' + e.message); return; }
        this.mutate('Edited a card', (d) => { const h = this.cardIn(d, v); if (!h) return false; h.g.cards[h.i] = { ...obj, id: v }; });
        return;
      }
      case 'add-entity': this.addCard(v, Number(el.dataset.g), { entity: el.dataset.e }); return;
      case 'add-typed': { const e = String(el.value || '').trim(); if (!H.states[e]) { this.toast(`${e || 'That'} is not an entity in this house.`); return; } this.addCard(v, Number(el.dataset.g), { entity: e }); return; }
      case 'add-ll': {
        const ta = el.closest('.edit').querySelector('textarea[data-keep="add-ll"]');
        const card = this.parseCard(ta.value);
        if (!card) { this.toast('That card could not be read — give it a `type:` line.'); return; }
        this.addCard(v, Number(el.dataset.g), card); return;
      }
      // settings
      case 'set': {
        const patch = {}; patch[el.dataset.k] = el.dataset.t === 'bool' ? !(this.settings()[el.dataset.k]) : el.dataset.t === 'num' ? Number(v) : v;
        const r = await H.callWS({ type: 'morph/request', kind: 'settings', payload: { patch } });
        if (r.ok) { this.data.state.settings = r.settings; this.schedule(); } else this.toast(r.error); return;
      }
      case 'learn-now': { const r = await H.callWS({ type: 'morph/request', kind: 'learn_now', payload: {} }); this.toast(r.ok ? 'Learning pass started — its suggestions appear on the Feed when it answers.' : r.error); return; }
      case 'regenerate': {
        // Armed for 4 s, drawn from state, so it never stays armed unseen.
        const c = this.s.confirm.regen;
        if (!c || c.until < Date.now()) { this.s.confirm.regen = { until: Date.now() + 4000 }; this.schedule(); setTimeout(() => this.schedule(), 4100); return; }
        delete this.s.confirm.regen;
        const r = await H.callWS({ type: 'morph/request', kind: 'regenerate', payload: {} });
        this.toast(r.ok ? 'Rebuilt from the house.' : r.error, r.commit); this.dash = null; this.load(); return;
      }
      case 'lessons-save': {
        const ta = this.shadowRoot.querySelector('textarea[data-keep="lessons"]');
        const lessons = ta.value.split('\n').map((x) => x.replace(/^[-*]\s*/, '').trim()).filter(Boolean);
        const r = await H.callWS({ type: 'morph/request', kind: 'lessons', payload: { lessons } });
        this.toast(r.ok ? 'Lessons saved.' : r.error); this.load(); return;
      }
      default:
    }
  }

  parseCard(text) {
    text = String(text || '').trim(); if (!text) return null;
    try { const o = JSON.parse(text); return o && o.type ? o : null; } catch (e) { /* not JSON — read it as simple YAML */ }
    // A small YAML reader for the common case: `key: value` lines and
    // indented lists. Anything richer goes through the YAML view or brAIn.
    const out = {}; let listKey = null;
    for (const raw of text.split('\n')) {
      if (!raw.trim() || raw.trim().startsWith('#')) continue;
      const li = raw.match(/^\s+-\s+(.*)$/);
      if (li && listKey) { out[listKey].push(li[1].trim()); continue; }
      const m = raw.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
      if (!m) return null;
      if (m[2] === '') { out[m[1]] = []; listKey = m[1]; continue; }
      listKey = null;
      const val = m[2].trim().replace(/^['"]|['"]$/g, '');
      out[m[1]] = val === 'true' ? true : val === 'false' ? false : isFinite(Number(val)) && val !== '' ? Number(val) : val;
    }
    return out.type ? out : null;
  }

  addCard(secId, gi, card) {
    this.closeView();
    this.mutate(`Added ${card.entity || card.type || 'a card'}`, (d) => {
      const h = this.sectionIn(d, secId); if (!h) return false;
      h.s.groups = h.s.groups || [];
      while (h.s.groups.length <= gi) h.s.groups.push({ cards: [] });
      h.s.groups[gi].cards = h.s.groups[gi].cards || [];
      h.s.groups[gi].cards.push(card);
    });
  }

  // ------------------------------------------------------------------- ask

  // Ask (§13.3): brAIn's chat with a dashboard in front of it. An admin's
  // words go to brAIn's interpreter on the `morph` surface, which does the
  // thing, says it is a conversation, or says it is a change to the
  // dashboard or to Morph itself (a Tell). No answer from the interpreter
  // is the old behaviour exactly: a dashboard change by its words goes to
  // a Tell, anything else to the house's conversation agent. Somebody who
  // is not an administrator asks the house's agent, as Assist would.
  async ask(q) {
    q = String(q || '').trim(); if (!q) return;
    const ae = this.shadowRoot.activeElement; if (ae && ae.blur) ae.blur();
    if (this.s.edit) { this.tellDashboard(q); return; }
    const a = this.askAdd(q);
    this.track('ask');
    if (this.admin()) {
      let r = null;
      try { r = await this.hass.callWS({ type: 'morph/ask', text: q }); } catch (e) { r = null; }
      const how = r && r.do;
      if (how === 'done') { this.askSet(a, r.say || 'Done.'); return; }
      if (how === 'tell_dashboard' || how === 'tell_code') { this.askDrop(a); this.tellDashboard(q, how === 'tell_code'); return; }
      if (how === 'conversation') { this.converse(a); return; }
      // fallback: the interpreter did not answer (offline, no credential).
      if (isDashChange(q)) { this.askDrop(a); this.tellDashboard(q); return; }
      if (how === 'fallback' || !r) { const ok = await this.converse(a, true); if (ok) return; }
    }
    await this.askAgent(a);
  }

  // The stack of questions (newest first, the last ASK_KEEP): each one its
  // own entry, its own conversation and its own poll, so a second question
  // never cuts the first one off. A finished entry past the cap goes first;
  // one still running goes only when five newer ones are asked.
  askAdd(q) {
    this._askSeq = (this._askSeq || 0) + 1;
    const a = { key: String(this._askSeq), q, busy: true };
    const list = [a, ...this.s.asks];
    while (list.length > ASK_KEEP) {
      let i = -1;
      for (let j = list.length - 1; j > 0; j--) if (!list[j].busy) { i = j; break; }
      const gone = list.splice(i > 0 ? i : list.length - 1, 1)[0];
      clearTimeout(gone.t);
    }
    this.s.asks = list;
    this.schedule();
    return a;
  }

  askSet(a, answer) {
    a.busy = false; a.answer = answer; clearTimeout(a.t);
    this.liftNamed(answer, a);
    this.schedule();
  }

  askDrop(a) { clearTimeout(a.t); this.s.asks = this.s.asks.filter((x) => x !== a); this.schedule(); }

  // A conversation with brAIn (a task that may continue): the session is
  // kept, so the next question resumes it, and it is the same conversation
  // brAIn's own Ask tab can pick up. Only while no other conversation from
  // this page is in flight: two turns resuming one session at once would
  // race for it, so a question asked while another runs starts its own.
  async converse(a, quiet) {
    const others = this.s.asks.some((x) => x !== a && x.busy && x.conv);
    let r;
    try { r = await this.hass.callWS({ type: 'morph/request', kind: 'converse', payload: { text: a.q, session: others ? '' : (this.s.convSession || '') } }); } catch (e) { r = null; }
    if (!r || !r.ok || !r.id) {
      if (quiet) return false;
      this.askSet(a, (r && r.error) || `${this.who()} did not take that.`); return false;
    }
    a.conv = { id: r.id, state: r };
    this.schedule();
    this.pollConverse(a);
    return true;
  }

  async pollConverse(a) {
    const c = a.conv; if (!c || !a.busy) return;
    try {
      const st = await this.hass.callWS({ type: 'morph/tell_status', tell: c.id });
      c.state = st;
      if (st.phase === 'done' || st.phase === 'failed' || st.phase === 'missing') {
        if (st.session_id) this.s.convSession = st.session_id;
        this.askSet(a, st.say || (st.phase === 'failed' ? `${this.who()} could not answer.` : 'No answer.'));
        return;
      }
    } catch (e) { /* asked again below */ }
    this.schedule();
    // Dropped from the stack (five newer questions): nobody reads it.
    if (!this.s.asks.includes(a)) return;
    clearTimeout(a.t); a.t = setTimeout(() => this.pollConverse(a), 1200);
  }

  async askAgent(a) {
    const q = a.q;
    const agent = Object.values(this.hass.entities || {}).find((e) => e.platform === 'brain' && e.entity_id.startsWith('conversation.'));
    try {
      // The agent is told, beside the words, that Morph's page is changed
      // with a Tell (and a Lovelace dashboard with brain.update_dashboard). A Home Assistant whose conversation/process
      // does not take extra_system_prompt refuses the key, so the question
      // is asked again without it rather than not at all.
      const msg = { type: 'conversation/process', text: q, agent_id: agent ? agent.entity_id : undefined, conversation_id: this._conv || undefined };
      let r;
      try { r = await this.hass.callWS({ ...msg, extra_system_prompt: ASK_CONTEXT }); } catch (e) {
        if (!/extra|invalid|not allowed/i.test(String((e && (e.message || e.code)) || e))) throw e;
        r = await this.hass.callWS(msg);
      }
      this._conv = r.conversation_id;
      this.askSet(a, (r.response && r.response.speech && r.response.speech.plain && r.response.speech.plain.speech) || 'No answer.');
    } catch (e) { this.askSet(a, 'Could not ask: ' + (e.message || e)); }
  }

  // One question to brAIn's conversation agent, from Ask or the Feed. The
  // agent is told, beside the words, that Morph's page is changed with a Tell
  // (and a Lovelace dashboard with brain.update_dashboard). A Home Assistant whose conversation/process does not take
  // extra_system_prompt refuses the key, so the question is asked again
  // without it rather than not at all.
  async agentAsk(text, conv) {
    const agent = Object.values(this.hass.entities || {}).find((e) => e.platform === 'brain' && e.entity_id.startsWith('conversation.'));
    const msg = { type: 'conversation/process', text, agent_id: agent ? agent.entity_id : undefined, conversation_id: conv || undefined };
    let r;
    try { r = await this.hass.callWS({ ...msg, extra_system_prompt: ASK_CONTEXT }); } catch (e) {
      if (!/extra|invalid|not allowed/i.test(String((e && (e.message || e.code)) || e))) throw e;
      r = await this.hass.callWS(msg);
    }
    return { conv: (r && r.conversation_id) || conv || '', speech: (r && r.response && r.response.speech && r.response.speech.plain && r.response.speech.plain.speech) || 'No answer.' };
  }

  // What an answer names on the page lifts into Now for ten minutes with
  // "because you asked" (§7.3), and the sentence offers Show me.
  liftNamed(ans, a) {
    const show = [];
    const low = String(ans || '').toLowerCase();
    this.eachSection((sec) => this.sectionCards(sec).forEach((c) => {
      if (['scenes', 'note', 'lovelace'].includes(c.type)) return;
      const n = this.cardName(c, sec);
      if (show.length < 3 && n.length > 3 && low.includes(n.toLowerCase())) show.push({ id: c.id, name: n });
    }));
    if (a) a.show = show;
    const until = Date.now() + sal.ASKED_MS;
    show.forEach((x) => { this.asked[x.id] = until; });
    if (show.length) { this._salDirty = true; this._forceApply = true; }
  }

  // Hold a because line: ask brAIn why, and the answer unfolds under Ask.
  askWhy(id) {
    const x = this.salNow(id);
    const hit = this.findCard(id);
    const c = id.startsWith('k:') ? this.caseById(id.slice(2)) : null;
    const name = hit ? this.cardName(hit.card, hit.sec) : c ? c.claim : '';
    if (!name) return;
    const q = `Why is ${name} ${x.why ? '“' + x.why.text + '”' : 'shown at the top'}?`;
    const inp = this.shadowRoot.querySelector('input[data-keep="ask"]');
    if (inp) inp.scrollIntoView({ block: 'center' });
    this.ask(q);
  }

  // Scroll the thing a clause or a trace names under the sentence,
  // already unfolded.
  jumpTo(id) {
    if (!id) return;
    if (id.startsWith('k:')) {
      // A case behind its folded summary row: open that row first.
      const k = this.casesPlaced().find((x) => 'k:' + x.id === id);
      if (k && !this.notesOpen(k._sec)) this.s.notesOpen = { ...(this.s.notesOpen || {}), [k._sec]: true };
    } else {
      const hit = this.findCard(id);
    }
    this.engine.invalidate(); this.schedule();
    setTimeout(() => { const el = this.$(`[data-tile="${CSS.escape(id)}"]`); if (el) this.engine.scrollToEl(el, 200); }, 120);
  }

  scrollToRoom(secId) {
    const el = this.$(`[data-sec="${CSS.escape(secId)}"]`); if (el) this.engine.scrollToEl(el, 90);
  }

  // An answer to one of brAIn's cases, through brAIn's own request queue.
  async caseRequest(cid, action, text) {
    try { return await this.hass.callWS({ type: 'morph/case', case: cid, action, text: text || '' }); } catch (e) { return { ok: false, error: String((e && e.message) || e) }; }
  }

  // A pin is written to LEARNED.md too, so the household's own rule is
  // where every Tell reads it.
  lesson(cardId, keep) {
    const hit = this.findCard(cardId); if (!hit) return;
    this.hass.callWS({ type: 'morph/request', kind: 'lesson_add', payload: { text: `${this.cardName(hit.card, hit.sec)} stays at the top of the page${keep ? '' : ' no more'} (you)` } }).catch(() => {});
  }

  tellDashboard(q, code) {
    this.s.tell = { kind: 'dashboard', path: code ? 'Morph itself' : 'The whole dashboard', label: code ? 'Morph itself' : 'dashboard', sent: false, draft: q, turns: [] };
    this.shoot(this.s.tell);
    this.sendTell(q);
  }

  // ---------------------------------------------------------------- feed



  // ------------------------------------------------------------ settings
  // The household's name for the assistant, which is how Morph's own words
  // name it (#452): brAIn's switches carry it (`features.name`, "brAIn"
  // while Personality is off), on every load. Before the first load there is
  // no name to say but "brAIn".
  who() {
    const f = this.data && this.data.features;
    return f && typeof f.name === 'string' && f.name.trim() ? f.name.trim() : 'brAIn';
  }

  // With Personality on, nothing on the page says "brAIn": the product's
  // name, in exactly that spelling, is the household's name for it. Never
  // inside a box somebody types in (a textarea's text is what they save),
  // and `brain` in lower case is a path or a command and is left alone.
  speak(html) { return speakHtml(html, this.who()); }

  // Ask brAIn's shell to show brAIn's own page: a view, or a Settings
  // section. Outside the shell (a test page) there is nothing to open.
  openBrain(view, sec) {
    this.dispatchEvent(new CustomEvent('brain-open', { bubbles: true, composed: true, detail: { view: view || 'insights', sec: sec || '' } }));
  }

  // ---------------------------------------------------------- learning io

  track(kind, card, section, detail) {
    this.usage.push({ kind, card: card || undefined, section: section || undefined, detail: detail || undefined });
    if (this.usage.length >= 40) this.flushUsage();
  }

  // A send that failed (the connection suspended, a reconnect in progress)
  // puts its events back for the next tick rather than dropping them: the
  // splice used to take them off the queue first and the catch threw them
  // away, so every use made just before the app went to the background was
  // lost. Capped, so a connection that never comes back cannot grow it.
  flushUsage() {
    if (!this.usage.length || !this.hass || this._flushing) return;
    const events = this.usage.splice(0, 50);
    this._flushing = true;
    let sent;
    try { sent = Promise.resolve(this.hass.callWS({ type: 'morph/usage', events })); } catch (e) { sent = Promise.reject(e); }
    sent.catch(() => { this.usage = events.concat(this.usage).slice(-USAGE_KEEP); })
      .finally(() => { this._flushing = false; });
  }

  // Which card and section a control inside a tile belongs to, so a press on
  // a button or a light-group member counts toward the card it is on.
  tileOf(el) {
    const tile = el && el.closest && el.closest('[data-tile]');
    const hit = tile && this.findCard(tile.getAttribute('data-tile'));
    return hit ? { card: hit.card.id, section: hit.sec.id } : { card: null, section: null };
  }

  report(kind, message, detail, cardType) {
    // Once per page, not per panel element: Home Assistant rebuilds the
    // element, and Morph's modules run again after an update.
    const key = kind + '|' + message;
    const page = cardPage().reported;
    if (this.reported.has(key) || page.has(key) || !this.hass) return;
    this.reported.add(key);
    page.add(key);
    this.hass.callWS({ type: 'morph/report', kind, message: String(message).slice(0, 300), detail: String(detail || '').slice(0, 2000), card_type: String(cardType || '') }).catch(() => {});
  }

  // The §5 test, on the live page: once things settle, no two sections may
  // overlap. A failure is a fault in Morph's code, so it is reported.
  audit() {
    if (this.drag || this.s.view) return;
    const bad = this.engine.overlaps();
    if (bad.length) this.report('layout', `Sections overlap at rest (${bad.length} pair${bad.length > 1 ? 's' : ''})`, JSON.stringify({ pairs: bad.slice(0, 5), width: this.$('[data-board]').clientWidth }));
  }
}

if (!customElements.get('morph-panel')) customElements.define('morph-panel', MorphPanel);
