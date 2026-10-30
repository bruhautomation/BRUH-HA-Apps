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
import { TYPES, typeOf, tileAria, stateWord } from './cards.js';
import * as history from './history.js';
import * as snap from './snap.js';
import * as upc from './upcoming.js';
import * as sal from './salience.js';
import * as then from './then.js';
import { morph } from './morph-dom.js';
import { caseFace, todoFace, caseColor, placeCase } from './cases.js';
import { Rail } from './rail.js';
import { esc, mix, hue, HUES, clock, ago, friendly, shortName, lightColor, SPARK, MARK, domainOf, UNAVAILABLE, fmt, climateDoing, importWithRetry, cardPage, guardDefine, loadCard, cardUrl, cardFailure, isDashChange, ASK_CONTEXT, own } from './util.js';

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
const KIND_WORD = { card: 'card', section: 'section', floor: 'floor', story: 'story', upcoming: 'Coming up', scenes: 'scenes', dashboard: 'dashboard' };
// A wall tablet left alone this long settles into its still form (§10.3).
const STILL_AFTER_MS = 90000;
// A room unfolded by hand stays open this long untouched, then refolds at
// the next quiet moment.
const UNFOLD_MS = 2 * 60000;
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

// A card's `options.detail`, when it is a Lovelace card config: the deeper
// view (a performance chart under a thermostat) that belongs in the opened
// card rather than on the face. A built-in card that hosts Lovelace itself
// has no second slot.
function detailCard(card) {
  const d = card && card.options && card.options.detail;
  if (!d || typeof d !== 'object' || Array.isArray(d) || typeof d.type !== 'string' || card.type === 'lovelace') return null;
  return d;
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
      secEdit: null, asks: [], story: {}, confirm: {}, hold: null, add: null,
      sugNo: null, toast: null, yaml: null, hist: null, persona: undefined, upcHost: null, upcShown: null,
      unfold: {}, pending: {}, replyOpen: {}, todoOpen: null, thenAt: null,
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
    // The days each card was used on this device, for anchors (§4.4: used
    // on four of the last seven days, it keeps its slot in its room).
    try { this.used = JSON.parse(localStorage.getItem('morph.used') || '{}') || {}; } catch (e) { this.used = {}; }
    // Predictions on screen now, {id: {eid, at}}: one that leaves untouched
    // is an ignored window, reported once (§7.1).
    this._pred = {};
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
    if (first) this.boot();
    else if (this.hassMatters(prev, h)) this.schedule();
    this.llCards.forEach((el) => { try { el.hass = h; } catch (e) { /* a card that throws on hass is reported when it draws */ } });
  }

  // Home Assistant sets `hass` on every state change in the house; a
  // redraw is only owed when something this page reads changed — an entity
  // the dashboard names, a person, the sun, a calendar or timer, the theme.
  hassMatters(prev, h) {
    if (!prev || !this.dash) return true;
    if (prev.themes !== h.themes || prev.config !== h.config || prev.user !== h.user) return true;
    const ids = this.watchIds();
    let hit = false;
    for (const e of ids) {
      const a = prev.states[e], b = h.states[e];
      if (a !== b) {
        hit = true;
        if (SALIENT.includes(domainOf(e))) { this._salDirty = true; break; }
      }
    }
    if (hit) return true;
    if (prev.states === h.states) return false;
    // Coming up reads the house's timers, calendars and timestamps.
    for (const e in h.states) {
      const d = domainOf(e);
      if ((d === 'timer' || d === 'calendar' || d === 'sun' || d === 'person' || d === 'alarm_control_panel') && prev.states[e] !== h.states[e]) return true;
    }
    return false;
  }

  watchIds() {
    if (this._watch && this._watchRev === this.revision) return this._watch;
    const set = new Set();
    this.eachSection((s) => this.sectionEntities(s).forEach((e) => set.add(e)));
    (this.dash.scenes || []).forEach((e) => set.add(e));
    this._watch = [...set]; this._watchRev = this.revision;
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
    else if (this._hass && this.engine) { this.startLive(); this.load(); }
  }

  disconnectedCallback() {
    this.flushUsage();
    this.stopLive();
  }

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
    root.innerHTML = `<style>${STYLES}</style><div class="morph t-dark" data-morph-root><div class="scroll" style="height:var(--morph-h,100vh);overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain"><div class="wrap">
<div data-region="thenrule"></div><div data-region="bar"></div><div data-region="lede"></div><div data-region="top"></div><div data-region="upcoming"></div><div data-region="scenes"></div><div data-region="rooms"></div><div data-region="notes"></div>
<div data-region="board"><div data-board></div></div></div><div class="srail" data-rail aria-hidden="true"></div></div></div>`;
    if (!document.querySelector('link[data-morph-fonts]')) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = FONTS_URL; l.dataset.morphFonts = '1'; document.head.appendChild(l);
    }
    this.$ = (sel) => root.querySelector(sel);
    this._bootAt = Date.now();
    this.rootEl = this.$('[data-morph-root]');
    // Coming up's element is kept, because it may be moved into a card's
    // tile (a Next chip, `morph-coming-up`) and the tile can go.
    this._upcEl = this.$('[data-region="upcoming"]');
    this.engine = new Engine(this.rootEl);
    this.engine.scrollEl = this.$('.scroll');
    this.engine.onSettle = () => this.audit();
    history.setOnData(() => this.schedule());
    then.setOnData(() => this.schedule());
    this.bindEvents();
    // The room rail on a touch screen's right edge (rail.js): a column of
    // notches beside the content, opened by a short pull to the left.
    this.rail = new Rail(this.$('[data-rail]'), this);
    // Inside brAIn's shell the scroll is also the shell's to hear: brAIn's
    // header hides while the dashboard scrolls down and returns as it
    // scrolls up (shell.js passes it to brAIn's page).
    this.$('.scroll').addEventListener('scroll', (ev) => {
      this.ui.lastScroll = Date.now();
      if (!this._railF) this._railF = requestAnimationFrame(() => { this._railF = 0; this.rail.paint(); });
      if (this._shell) this.dispatchEvent(new CustomEvent('morph-scroll', { bubbles: true, composed: true, detail: { y: ev.currentTarget.scrollTop } }));
    }, { passive: true });
    this.ro = new ResizeObserver(() => { cancelAnimationFrame(this._ro); this._ro = requestAnimationFrame(() => this.engine.layout(false, true)); });
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
      if (!this._personaAsked) { this._personaAsked = true; this.loadPersona(); }
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
    const set = this.settings();
    const theme = set.theme && set.theme !== 'auto' ? set.theme : (this.hass.themes && this.hass.themes.darkMode === false ? 'light' : 'dark');
    // boot.js draws its outline in the theme this page last used.
    if (theme !== this._savedTheme) { this._savedTheme = theme; try { localStorage.setItem('morph.theme', theme); } catch (e) { /* storage refused */ } }
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
    const cls = `morph t-${theme}${set.reduce_motion ? ' reduce' : ''}${form ? ' form-' + form : ''}${dim ? ' night-dim' : ''}${this.s.thenAt ? ' then' : ''}`;
    if (this.rootEl.className !== cls) this.rootEl.className = cls;
    this.region('thenrule', this.s.thenAt ? `<div class="thenrule" style="width:${(Math.min(1, (Date.now() - this.s.thenAt) / 86400000) * 100).toFixed(1)}%"></div>` : '');
    this.region('bar', this.barHtml());
    this.chrome(theme);
    this.region('lede', this.updateHtml() + (this.s.edit ? `<div class="lede">Editing · <b>hold anything to tell ${esc(this.who())} what to change</b> · drag a section by its title · tap a card to rename, resize or remove it</div>` : '') + this.activityHtml());
    this.$('[data-region="board"]').hidden = false;
    if (!this.data) { this.region('top', '<p class="sm">Opening Morph…</p>'); return; }
    this.readyOnce();
    if (this.data.error) { this.region('top', `<div class="banner bad">Morph could not load: ${esc(this.data.error)}. Is brAIn started, with the Morph dashboard switched on in ⚙ › Features? It is tried again on its own. <button type="button" class="wd go" data-act="retry-load">Try again now</button></div>`); return; }
    // A face without the mind behind it would be a dashboard pretending to
    // be this one (vision §4.7): the page is one sentence.
    if (!this.brainInstalled()) { ['upcoming', 'scenes', 'rooms', 'notes'].forEach((r) => this.region(r, '')); this.$('[data-region="board"]').hidden = true; this.region('top', `<p class="story needbrain">${esc(NEEDS_BRAIN)}</p>`); return; }
    if (!this.dash) { this.region('top', `<div class="banner">brAIn has not written the dashboard yet. It builds the first one from your floors and rooms within a minute of the Morph dashboard being switched on.</div>`); return; }
    const dash = this.dash;
    this.prepareThen();
    this.region('top', this.topHtml(dash));
    this.region('scenes', (dash.scenes || []).length ? this.scenesHtml(dash) : '');
    this.region('rooms', this.roomLineHtml(dash));
    this.region('notes', this.admin() ? this.problemsHtml() : '');
    this.renderBoard(dash);
    this.applyConfirms();
    this.tickSince();
  }

  // THEN (vision §7.2): the house at the moment Coming up was slid back to,
  // read off the recorder. Cards draw from `hassView()`; nothing can be
  // pressed; the verdict is in the past tense.
  prepareThen() {
    if (!this.s.thenAt) { this.thenStates = null; this.thenSal = null; return; }
    const st = then.statesAt(this.hass, this.watchIds(), this.s.thenAt);
    this.thenStates = st || null;
    if (!st) { this.thenSal = null; return; }
    try { this.thenSal = sal.compute(this.salItems().filter((i) => !i.case), { ...this.salContext(st, this.s.thenAt), pins: {}, asked: {}, touched: {} }, null); } catch (e) { this.thenSal = null; }
  }

  hassView() { return this.s.thenAt && this.thenStates ? { ...this.hass, states: this.thenStates } : this.hass; }

  setThen(t) {
    const was = this.s.thenAt;
    this.s.thenAt = t;
    if (!!was !== !!t || (t && Math.abs(t - was) > 30000)) this.schedule();
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

  // Who is looking (§4.5): a personal device is its owner's, a family one
  // (a wall tablet) weighs every home person's habits alike.
  viewer() {
    let device = 'personal';
    try { device = localStorage.getItem('morph.device') === 'family' ? 'family' : 'personal'; } catch (e) { /* storage refused: personal */ }
    let person = null;
    try { person = localStorage.getItem('morph.person') || null; } catch (e) { /* none */ }
    if (!person) {
      const uid = this.hass.user && this.hass.user.id;
      const people = (this.brain().feed && this.brain().feed.people) || {};
      Object.keys(people).forEach((p) => { if (uid && people[p].user_id === uid) person = p; });
      if (!person) Object.values(this.hass.states).forEach((st) => { if (domainOf(st.entity_id) === 'person' && uid && st.attributes.user_id === uid) person = st.entity_id; });
    }
    return { device, person };
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
      now, states, feed: fh.usable ? this.brain().feed : null, casesByEntity, viewer: this.viewer(),
      habitWeights: this.settings().habit_weights || {}, pins, suppressed, touched: this.touched, asked: this.asked,
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
    try { this.notePredictions(res); } catch (e) { /* bookkeeping only */ }
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

  // An anchor (§4.4): a card used on four of the last seven days keeps its
  // slot in its room whatever its score.
  anchored(id) {
    const days = this.used[id]; if (!days || days.length < 4) return false;
    const week = Date.now() - 7 * 86400000;
    return days.filter((d) => Date.parse(d) >= week - 86400000).length >= 4;
  }

  // A prediction that leaves the page untouched is an ignored window: its
  // habit's weight halves, and two in a row stop it (§7.1). Reported once
  // per window, and only by the device whose owner it predicted for.
  notePredictions(res) {
    const on = (x) => x && x.predicted && ['now', 'lead'].includes(x.band);
    Object.values(res.items).forEach((x) => { if (on(x) && !this._pred[x.id]) this._pred[x.id] = { eid: x.eid, at: res.at }; });
    Object.keys(this._pred).forEach((id) => {
      if (on(res.items[id])) return;
      const p = this._pred[id]; delete this._pred[id];
      if ((this.touched[id] || 0) >= p.at || !p.eid || !this.admin()) return;
      const k = 'morph.ignored:' + p.eid + ':' + new Date(p.at).toDateString();
      try { if (localStorage.getItem(k)) return; localStorage.setItem(k, '1'); } catch (e) { /* storage refused: report anyway */ }
      this.hass.callWS({ type: 'morph/request', kind: 'habit', payload: { entity: p.eid, used: false } }).catch(() => {});
    });
  }

  // A card at the top of its room with a because line under it.
  leadsWithReason(id) {
    if (this.s.edit || this.s.thenAt) return false;
    const a = this.salOf(id); const x = this.salNow(id);
    return a.band === 'lead' && !!(x.why && x.why.kind !== 'none');
  }

  // The applied result for one item, or {} (folded, nothing to say).
  salOf(id) { return (this.salApplied && this.salApplied.items[id]) || {}; }
  // The newest result for one item: what a because line says right now.
  salNow(id) { return (this.salState && this.salState.items[id]) || {}; }

  // The page's form: night, away or still (§10), or the ordinary page.
  form() {
    if (this.s.edit || this.s.thenAt) return '';
    const per = this.salApplied && this.salApplied.period;
    if (per === 'night') return 'night';
    if (per === 'away') return 'away';
    if (this.viewer().device === 'family' && Date.now() - (this.ui.lastTouch || this._bootAt || 0) > STILL_AFTER_MS) return 'still';
    return '';
  }

  // A confirm waiting for its second tap survives a redraw: the button says
  // it again from the state, not from an edit the rebuild undid.
  applyConfirms() {
    const now = Date.now();
    this.shadowRoot.querySelectorAll('[data-confirm]').forEach((el) => {
      const k = 'btn:' + el.dataset.service + el.dataset.data;
      const c = this.s.confirm[k];
      if (c && c.until > now) el.textContent = el.dataset.confirm;
    });
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
    const el = name === 'upcoming' ? this.upcRegion() : this.$(`[data-region="${name}"]`);
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
    el.innerHTML = html;
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

  barHtml() {
    const now = new Date();
    const date = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }) + ' · ' + clock(now);
    // Inside brAIn's shell with brAIn's header above (the frame), the
    // header is brAIn's: its tabs, its ☰ and ⚙. Alone (somebody who is not
    // an administrator), the bar names the assistant and opens the sidebar.
    const menu = this._narrow && !this._shell ? `<button type="button" class="menu" data-act="menu" aria-label="Open the sidebar"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>` : '';
    const admin = this.admin();
    let right = '';
    if (this.s.edit) right = `<button type="button" class="go" data-act="yaml-toggle" style="margin-left:10px;padding:0 4px;font-size:13px;color:var(--muted)">${this.s.yaml ? 'Hide YAML' : 'YAML'}</button><button type="button" class="go" data-act="edit" style="margin-left:6px;padding:0 4px;font-size:14px;color:var(--teal)">Done</button>`;
    else if (admin) right = `<button type="button" class="go" data-act="edit" style="display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:0 4px;font-size:13px;color:var(--muted)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>Edit</button>`;
    // Settings are brAIn's (⚙ › Dashboard), in brAIn's header.
    const toast = this.s.toast ? `<span class="rise bartoast">${esc(this.s.toast.text)}${this.s.toast.sha ? ` <button type="button" class="wd go" data-act="undo-commit" data-v="${esc(this.s.toast.sha)}" style="min-height:24px">Undo</button>` : ''}${this.s.toast.action === 'reload' ? ` <button type="button" class="wd go" data-act="reload-page" style="min-height:24px">Reload</button>` : ''}</span>` : '';
    const yaml = this.s.edit && this.s.yaml != null ? `<div style="display:flex;flex-direction:column;gap:8px;margin-top:14px"><span class="label">Raw configuration · /config/morph/dashboard.yaml</span><textarea class="code-ed" data-keep="yaml" spellcheck="false" aria-label="dashboard.yaml">${esc(this.s.yaml)}</textarea><div class="row"><button type="button" class="wd go" data-act="yaml-save">Save YAML</button><span class="small">Saved as one commit; Undo puts it back.</span></div></div>` : '';
    // On a phone a toast takes the date's place: the bar is one row and
    // Edit's own buttons must stay on it.
    // Inside brAIn's shell there is ONE header, brAIn's (the owner: "there
    // are two headers … merge them"): Edit, YAML and Done are drawn there
    // from `chrome()` and pressed back through `chromeAct`, the date gives
    // way to the page's own clock, and a toast is a line of the page rather
    // than a bar.
    // Edit at rest is Morph's own, and quiet: a small pencil on the
    // page's first line, under brAIn's header (the owner: Edit "should be
    // more subtle and under the [header]"); Done and YAML stay in the header
    // while editing.
    if (this._shell) {
      const edit = admin && !this.s.edit ? `<button type="button" class="go editquiet" data-act="edit"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>Edit</button>` : '';
      return `${toast || edit ? `<div class="toastline">${toast}<span class="flex1"></span>${edit}</div>` : ''}${yaml}`;
    }
    const dateHtml = this.s.toast && this._narrow ? '' : `<span class="date">${esc(date)}</span>`;
    const brand = this._shell ? '' : `<span class="brand">${MARK(16)}${esc(this.who().toUpperCase())}</span>`;
    return `<div class="bar">${menu}${brand}${toast}<span class="flex1"></span>${dateHtml}${right}</div>${yaml}`;
  }

  // ---------------------------------------------------------------- the top

  greeting() {
    const h = new Date().getHours();
    return h < 5 ? 'Good night.' : h < 12 ? 'Good morning.' : h < 18 ? 'Good afternoon.' : 'Good evening.';
  }

  // One clause of the verdict for one salience item, in the present or
  // the past tense, from the entity's own state — never from a number
  // nobody measured.
  clauseFor(x, states, past) {
    const H = this.hass;
    if (x.isCase || String(x.id).startsWith('k:')) {
      const c = this.caseById(String(x.id).slice(2));
      return c && !past ? (c.claim || c.text || '') : '';
    }
    const st = states[x.eid];
    if (!st) return '';
    const name = friendly(H, x.eid);
    const is = past ? 'was' : 'is';
    const d = domainOf(x.eid); const dc = st.attributes.device_class; const i = x.inp || {};
    if (d === 'lock') return st.state === 'unlocked' ? `${name} ${is} unlocked` : st.state === 'jammed' ? `${name} ${is} jammed` : '';
    if (d === 'binary_sensor' && ['smoke', 'gas', 'carbon_monoxide', 'moisture'].includes(dc) && st.state === 'on') return `${name} ${past ? 'detected' : 'detects'} ${dc === 'moisture' ? 'water' : dc === 'carbon_monoxide' ? 'carbon monoxide' : dc}`;
    if ((d === 'binary_sensor' || d === 'cover') && ['on', 'open', 'opening'].includes(st.state)) {
      const recent = !past && st.last_changed && Date.now() - Date.parse(st.last_changed) < 120000;
      return recent ? `${name} just opened` : `${name} ${is} open`;
    }
    if (i.pr && i.pr.finished) return `${name} ${past ? 'had finished' : 'finished'}${i.pr.since && !past ? ' ' + agoWords(Date.now() - i.pr.since * 1000) : ''}`;
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
  verdict(states, past, top) {
    const out = [];
    const res = past || this.salState;
    const seen = new Set();
    ((top || (res && res.top)) || []).forEach((id) => {
      if (out.length >= 3) return;
      const x = res.items[id]; if (!x) return;
      const text = this.clauseFor(x, states, !!past);
      const key = x.eid || id;
      if (!text || seen.has(key)) return;
      seen.add(key);
      out.push({ id, text, color: x.color || 'var(--text)' });
    });
    return out;
  }

  verdictHtml(dash) {
    const fh = this.feedState();
    const offline = fh.state === 'offline' || fh.state === 'expired' ? '<span class="vq"> · brAIn offline</span>' : '';
    const sentence = (parts) => {
      const first = parts[0];
      const rest = parts.slice(1);
      return `<button type="button" class="vjump" data-act="jump" data-v="${esc(first.id)}" style="--vc:${first.color}">${esc(first.text)}.</button>${rest.map((r) => ` <button type="button" class="vjump plain" data-act="jump" data-v="${esc(r.id)}" style="--vc:${r.color}">${esc(r.text)}.</button>`).join('')}`;
    };
    if (this.s.thenAt) {
      const states = this.thenStates || this.hass.states;
      const res = this.thenSal;
      const parts = res ? this.verdict(states, res, res.top) : [];
      const at = clock(this.s.thenAt);
      return `<p class="story">${parts.length ? `<span class="vthen">At ${esc(at)}</span> ${sentence(parts)}` : `<span class="vthen">At ${esc(at)}</span> <span>everything was at rest.</span>`}</p>`;
    }
    const parts = this.verdict(this.hass.states);
    const open = this.cases().filter((c) => c.kind !== 'chore').length;
    const tail = open ? ` <button type="button" class="vjump plain" data-act="jump" data-v="k:${esc((this.cases()[0] || {}).id || '')}">…and ${open} thing${open === 1 ? '' : 's'} need${open === 1 ? 's' : ''} you.</button>` : '';
    if (this.form_ === 'away') {
      const sec = parts.length ? ' ' + sentence(parts) : ' <span style="color:var(--indigo)">Everything is locked.</span>';
      return `<p class="story"><span class="hi">Nobody is home.</span>${sec}${tail}${offline}</p>`;
    }
    if (parts.length) return `<p class="story">${sentence(parts)}${tail}${offline}</p>`;
    const sit = this.brain().situation;
    if (sit && sit.sentence && (!sit.at || Date.now() / 1000 - sit.at < 3600) && this.form_ !== 'night') return `<p class="story"><span class="hi">${esc(sit.sentence)}</span>${tail}${offline}</p>`;
    return `<p class="story"><span style="color:var(--indigo)">Everything is at rest.</span>${tail}${offline}</p>`;
  }

  // The clock and the outside temperature a still, night or away page
  // carries at its top right (§10.3), read from across the room.
  clockHtml() {
    if (!['still', 'night'].includes(this.form_)) return '';
    const w = Object.values(this.hass.states).find((st) => domainOf(st.entity_id) === 'weather');
    const t = w && w.attributes.temperature != null ? `${Math.round(w.attributes.temperature)}°` : '';
    return `<div class="bigclock" aria-hidden="true"><b data-clock="1">${esc(clock(new Date()))}</b>${t ? `<span>${esc(t)}</span>` : ''}</div>`;
  }

  topHtml(dash) {
    const holding = (k) => (this.s.hold === k ? ' holding' : '');
    const story = dash.story !== false ? `<div class="holdable${holding('top:story')}" data-hold="story">${this.verdictHtml(dash)}${this.tellBox('story')}</div>` : '';
    const edit = this.s.edit;
    let ask = '';
    if ((dash.ask !== false || edit) && !this.s.thenAt) {
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
    return `<section aria-label="Now" class="topsec" style="display:flex;flex-direction:column;gap:14px;max-width:980px">${this.clockHtml()}${dash.greeting !== false && this.form_ !== 'night' ? `<h1 class="hello">${esc(this.greeting())}</h1>` : ''}${this.data.state && this.data.state.note ? `<div class="banner">${esc(this.data.state.note)}</div>` : ''}${story}${ask}</section>`;
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
    const reg = this.upcRegion();
    const w = (reg && reg.isConnected && reg.clientWidth) || (this.rootEl && this.rootEl.clientWidth) || window.innerWidth;
    const now = Date.now();
    const m = upc.model(this.hass, now, w < 640 ? 0.9 : 1.25, this.dash ? then.past(this.hass, this.watchIds(), now).concat(this.predictionEvents(now)) : []);
    if (!m.stacks.length && !m.durs.length && !this.s.edit) { this._upc = null; return ''; }
    this._upc = m;
    const holding = this.s.hold === 'top:upcoming' ? ' holding' : '';
    return `<div class="holdable${holding}" data-hold="upcoming" aria-label="Coming up">${upc.html(m, this.upcCursor(m))}${this.tellBox('upcoming')}</div>`;
  }

  // Each prediction's next measured time as a dashed violet dot on Coming
  // up (§7.1): a habit with four days behind it, for something on the
  // page, whose weight has not stopped it. Nothing hand-set.
  predictionEvents(now) {
    const feed = this.feedState().usable ? (this.brain().feed || {}) : {};
    const weights = this.settings().habit_weights || {};
    const out = [];
    (feed.habits || []).forEach((h) => {
      if (!h || !h.entity_id || (h.days_seen || 0) < sal.HABIT_MIN_DAYS || h.minute == null) return;
      if (!this.onDash(h.entity_id)) return;
      if (weights[h.entity_id] != null && weights[h.entity_id] <= sal.HABIT_STOP_WEIGHT) return;
      for (let add = 0; add < 2; add++) {
        const d = new Date(now); d.setDate(d.getDate() + add); d.setHours(0, Math.round(h.minute), 0, 0);
        const we = d.getDay() === 0 || d.getDay() === 6;
        if ((h.days === 'weekdays' && we) || (h.days === 'weekends' && !we)) continue;
        if (d.getTime() <= now - 60000 || d.getTime() > now + upc.AHEAD_MIN * 60000) continue;
        out.push({ at: d.getTime(), label: friendly(this.hass, h.entity_id), kind: 'usual', solid: false, eid: h.entity_id, sub: 'usually about now' });
        break;
      }
    });
    return out;
  }

  // A card asks for Coming up with a `morph-coming-up` event (bubbling,
  // composed) — a house's Now card's Next chip. It opens under the tile the
  // event came from, the same press again folds it, `detail.open` says
  // which outright, and `detail.shown` is written back so the chip can
  // draw itself pressed.
  onComingUp(e) {
    const path = e.composedPath ? e.composedPath() : [];
    const tile = path.find((n) => n && n.nodeType === 1 && n.hasAttribute('data-tile'));
    const host = tile ? tile.getAttribute('data-tile') : null;
    const d = e.detail && typeof e.detail === 'object' ? e.detail : null;
    const here = this.upcShownNow() && this.s.upcHost === host;
    const open = d && typeof d.open === 'boolean' ? d.open : !here;
    if (open) { this.s.upcHost = host; this.s.upcShown = true; } else this.s.upcShown = false;
    if (d) { try { d.shown = open; } catch (er) { /* a frozen detail */ } }
    this.schedule();
  }

  upcShownNow() { return !!(this.dash && this.dash.coming_up !== false && this.s.upcShown !== false); }

  // The model item Coming up sits under: the card the chip was pressed in,
  // while it is on the board.
  upcHostItem(model) {
    const host = this.s.upcHost;
    if (!host || !this.upcShownNow()) return null;
    for (const sec of model.sections) for (const g of sec.groups) for (const it of g.items) if (it.id === host) return it;
    return null;
  }

  // Back under the story before any tile is redrawn: a tile that no longer
  // hosts it drops its slot, and the strip must not go with it.
  homeUpcoming() {
    const el = this.upcRegion(); if (!el) return;
    const slot = el.parentElement && el.parentElement.hasAttribute('data-upc-slot') ? el.parentElement : null;
    const hostTile = slot && slot.closest('[data-tile]');
    if (slot && this._upcHosting && hostTile && hostTile.getAttribute('data-tile') === this._upcHosting) return;
    const top = this.$('[data-region="top"]');
    if (el.isConnected && !slot) return;
    if (top) top.after(el);
  }

  // Into the host's slot, then drawn (or emptied) at its width. Coming up
  // is not rebuilt under a finger, or while it is gliding to where it was
  // let go: the rebuild would land it before it arrives.
  placeUpcoming(dash) {
    const el = this.upcRegion(); if (!el) return;
    if (this._upcHosting) {
      const tile = this.$(`[data-tile="${CSS.escape(this._upcHosting)}"]`);
      const slot = tile && tile.querySelector('[data-upc-slot]');
      if (slot && el.parentElement !== slot) slot.appendChild(el);
    }
    if (!this.upcFrozen()) this.region('upcoming', dash.coming_up !== false && this.s.upcShown !== false ? this.upcomingHtml() : '');
  }

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
    // Behind the line is THEN: the page shows the house at that moment.
    this.setThen(c < -1 ? m.base + c * 60000 : null);
    clearTimeout(this._upcIdle);
    if (c !== 0) this._upcIdle = setTimeout(() => { if (!this.upcD && this._upc) this.upcGo(this._upc, 0); }, upc.IDLE_BACK_MS);
    if (still) this.schedule();
  }

  upcDown(e, vp) {
    const m = this._upc; if (!m) return;
    const tr = vp.querySelector('[data-cu-track]'); if (tr) tr.classList.remove('glide');
    clearTimeout(this._upcIdle); clearTimeout(this._upcGlideT); this._upcGlide = 0;
    const lens = vp.querySelector('[data-cu-lens]'); const lr = lens && lens.getBoundingClientRect();
    const c0 = this.upcCursor(m);
    this.upcD = { x0: e.clientX, c0, c: c0, lx: e.clientX, lt: performance.now(), v: 0, moved: false, vp, pid: e.pointerId, px: lr ? lr.left + lr.width / 2 : e.clientX };
  }

  upcMove(e) {
    const d = this.upcD; const m = this._upc; if (!d || !m) return;
    const dx = e.clientX - d.x0;
    if (!d.moved) { if (Math.abs(dx) < 6) return; d.moved = true; try { d.vp.setPointerCapture(d.pid); } catch (er) { /* fine */ } }
    const now = performance.now(); const dt = now - d.lt;
    if (dt > 0) d.v = 0.7 * ((e.clientX - d.lx) / dt) + 0.3 * d.v;
    d.lx = e.clientX; d.lt = now;
    d.c = upc.clampC(m, d.c0 - dx / m.k);
    upc.paint(this.upcRegion(), m, d.c);
  }

  // A tap goes to what is nearest where it landed; a swipe coasts on its
  // speed and settles on the nearest event, if one is close.
  upcUp(e) {
    const d = this.upcD; this.upcD = null; const m = this._upc;
    if (!d || !m) return;
    if (!d.moved) {
      const t = d.c0 + (e.clientX - d.px) / m.k;
      const s = upc.snap(m, t, 24 / m.k);
      this.upcGo(m, s != null ? s : t);
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
    if (!vp || !m || this.s.edit || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
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
    const H = this.hass; let cur = null, bt = 0;
    dash.scenes.forEach((e) => { const t = H.states[e] ? Date.parse(H.states[e].state) : 0; if (t > bt) { bt = t; cur = e; } });
    if (Date.now() - bt > 12 * 3600000) cur = null;
    const holding = this.s.hold === 'top:scenes' ? ' holding' : '';
    return `<div class="holdable scenesline${holding}" data-hold="scenes"><span class="label" style="margin-right:4px">Scenes</span>${dash.scenes.map((e) => `<button type="button" class="wd" data-act="scene" data-v="${esc(e)}" aria-pressed="${cur === e}">${esc(friendly(H, e))}</button>`).join('')}${this.tellBox('scenes')}</div>`;
  }

  // ------------------------------------------------------------- the cases

  // brAIn's one list (§13.1), as brAIn published it. Morph keeps none of
  // its own: a finding, a question, a suggestion — Morph's own learning
  // suggestions included, which brAIn files with source `morph` — is a case
  // here, answered here, and answered everywhere.
  cases() {
    const b = this.brain();
    const list = Array.isArray(b.cases) ? b.cases : [];
    return list.filter((c) => c && c.id && c.kind !== 'chore');
  }

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

  todos() {
    const b = this.brain();
    const now = Date.now() / 1000;
    return (Array.isArray(b.todo) ? b.todo : []).filter((t) => t && t.id != null && !(t.snoozed_until && t.snoozed_until > now)).map((t) => {
      let area = '';
      if (own(this.hass.areas, t.area_id)) area = own(this.hass.areas, t.area_id).name;
      return { ...t, area_name: area };
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
    if (this._placed && this._placedKey === this.brain().cases_at + '|' + this.revision) return this._placed;
    const out = this.cases().map((c) => ({ ...c, _sec: placeCase(c, (e, a) => this.secFor(e, a)) || '__cases' }));
    this._placed = out; this._placedKey = this.brain().cases_at + '|' + this.revision;
    return out;
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
    if (!this._secEnts || this._secEntsRev !== this.revision) { this._secEnts = new WeakMap(); this._secEntsRev = this.revision; }
    const hit = this._secEnts.get(sec); if (hit) return hit;
    const out = [];
    this.sectionCards(sec).forEach((c) => {
      if (c.entity) out.push(c.entity);
      (c.entities || []).forEach((e) => out.push(typeof e === 'string' ? e : (e && e.entity) || ''));
      if (c.type === 'light_group' && this.hass.states[c.entity]) (this.hass.states[c.entity].attributes.entity_id || []).forEach((e) => out.push(e));
      // A hosted Lovelace card or a custom card type carries its entities
      // in its own config, in whatever shape it likes; every string in it
      // that names an entity Home Assistant has is one this room shows.
      // Without it a case about the thermostat in a hosted card was placed
      // as if the room did not show it.
      if (!BUILT_IN.has(c.type)) entityIdsIn(c.card || c, this.hass.states, out, 0);
    });
    const done = [...new Set(out.filter(Boolean))];
    if (Object.keys(this.hass.states || {}).length) this._secEnts.set(sec, done);
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

  // What a person wants to know about a floor at a glance: how warm it is
  // and what the air is doing, whether lights are on, who is asleep, and
  // anything left open.
  floorFacts(fl) {
    const H = this.hass; const facts = [];
    const ents = [...new Set(this.floorEntities(fl))];
    const clim = ents.map((e) => H.states[e]).filter((s) => s && domainOf(s.entity_id) === 'climate');
    const temps = ents.map((e) => H.states[e]).filter((s) => s && s.attributes.device_class === 'temperature' && !isNaN(parseFloat(s.state)));
    const c = clim[0];
    if (c) {
      const a = c.attributes; const cur = a.current_temperature;
      const doing = climateDoing(c);
      facts.push({ t: [cur != null ? fmt(cur, '°') : '', doing].filter(Boolean).join(' · ') });
    } else if (temps.length) {
      const v = temps.map((s) => parseFloat(s.state)).sort((a, b) => a - b);
      facts.push({ t: fmt(v[Math.floor(v.length / 2)], temps[0].attributes.unit_of_measurement || '°') });
    }
    const lights = ents.filter((e) => domainOf(e) === 'light' && H.states[e] && H.states[e].state === 'on' && !(H.states[e].attributes.entity_id || []).length).length;
    facts.push({ t: lights ? `${lights} light${lights > 1 ? 's' : ''} on` : 'Lights off', color: lights ? '' : 'var(--quiet)' });
    const asleep = (fl.sections || []).filter((sec) => this.asleepSince(sec));
    if (asleep.length) facts.push({ t: asleep.length === 1 ? `${asleep[0].title} asleep` : `${asleep.length} rooms asleep`, color: 'var(--violet)' });
    const open = ents.filter((e) => { const s = H.states[e]; return s && ((domainOf(e) === 'binary_sensor' && ['door', 'window', 'garage_door', 'moisture'].includes(s.attributes.device_class) && s.state === 'on') || (domainOf(e) === 'lock' && s.state === 'unlocked')); });
    open.slice(0, 2).forEach((e) => facts.push({ t: `${friendly(H, e)} ${H.states[e].state === 'unlocked' ? 'unlocked' : 'open'}`, color: 'var(--rose)' }));
    return facts;
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

  // A room's state (§6): attention, asleep, occupied, active, or idle
  // (folded to a line). Edit never folds; a room unfolded by hand stays
  // open until two minutes after it was last touched.
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
    const lifted = items.some((x) => res.now.includes(x.id));
    const byHand = this.s.unfold[sec.id] && this.s.unfold[sec.id] > Date.now();
    if (this.asleepSince(sec) && !byHand) return 'asleep';
    const form = this.form_;
    if ((form === 'night' || form === 'away') && !byHand) return 'idle';
    const shown = items.some((x) => x.band !== 'folded' && !res.now.includes(x.id));
    const here = this.presence(sec);
    if (byHand) return here ? 'occupied' : 'active';
    if (here) return 'occupied';
    if (shown) return 'active';
    if (this.settings().fold_rooms === false) return 'active';
    // A room with no presence sensor cannot say it is empty: one with
    // something on stays open rather than being folded on a guess.
    // A header switch (a pause) is a setting, not something left on.
    const cards = this.sectionCards(sec);
    const headOnly = new Set(cards.filter(isHeadCard).map((c) => c.entity).filter((e) => !cards.some((c) => !isHeadCard(c) && c.entity === e)));
    if (here == null && !lifted && this.sectionEntities(sec).some((e) => { if (headOnly.has(e)) return false; const st = this.hass.states[e]; return st && ['light', 'fan', 'media_player', 'switch'].includes(domainOf(e)) && ['on', 'playing'].includes(st.state); })) return 'active';
    return 'idle';
  }

  // What stays visible under an asleep room's line (§6.4): the thing its
  // sleeper usually needs at night — a night habit's card, else its fan,
  // else its first switch.
  nightControl(sec) {
    const cards = this.sectionCards(sec).filter((c) => c.entity && !['scenes', 'note', 'lovelace', 'readings'].includes(c.type) && !isHeadCard(c));
    const habits = ((this.brain().feed || {}).habits) || [];
    const nightly = (e) => habits.some((h) => h.entity_id === e && (h.minute >= 1200 || h.minute < 360));
    return cards.find((c) => nightly(c.entity)) || cards.find((c) => domainOf(c.entity) === 'fan') || cards.find((c) => ['switch', 'input_boolean'].includes(domainOf(c.entity))) || null;
  }

  // The floors in the order the list puts them, and the rooms in each,
  // from the ROOM SCORE (§4.2: the max of its items, plus 0.1 occupied)
  // read through the bands. A room keeps its place in its floor unless it
  // is two full bands above folded — leading or Now, or needing attention
  // (§4.4's anchor rule for rooms); four fixed buckets with "occupied" as
  // one of them sent every room somebody walked into to the top of every
  // device. On a family device an occupied room rises one place (§6.3).
  // Read from the APPLIED list, so it moves only when quiet.
  orderedFloors(dash) {
    const res = this.salApplied;
    const family = this.viewer().device === 'family';
    const rank = (sec) => {
      if (this.s.edit || !res) return 0;
      if (this.roomState(sec) === 'attention') return 3;
      const room = res.rooms && res.rooms[sec.id];
      const b = sal.BAND_ORDER.indexOf(sal.bandFor(room ? room.S : 0, 'folded'));
      return b >= 2 ? b : 0;
    };
    const floors = (dash.floors || []).map((fl, fi) => {
      const secs = (fl.sections || []).map((sec, i) => ({ sec, i, r: rank(sec), occ: !this.s.edit && !!res && family && !!this.presence(sec) }));
      secs.sort((a, b) => b.r - a.r || a.i - b.i);
      for (let i = 1; i < secs.length; i++) {
        if (secs[i].occ && !secs[i - 1].occ && secs[i].r === secs[i - 1].r && !secs[i - 1].rose) { const t = secs[i - 1]; secs[i - 1] = secs[i]; secs[i] = t; secs[i - 1].rose = true; }
      }
      return { fl, fi, secs: secs.map((x) => x.sec), r: Math.max(0, ...secs.map((x) => x.r)) };
    });
    // A floor rises only for something leading in it, not for occupancy.
    floors.sort((a, b) => (b.r >= 2 ? 1 : 0) - (a.r >= 2 ? 1 : 0) || a.fi - b.fi);
    return floors;
  }

  itemOf(c) { const t = typeOf(c).item; return { id: c.id, span: c.span || t.span, grow: Math.max(c.span || 0, t.grow || t.span), dir: t.dir, want: t.want, full: !!t.full, hk: t.hk || 'x:' + c.id }; }

  // The model the engine lays out: sections with groups of items, each item
  // carrying its type's layout parameters. Floor -1 is the Now band: no
  // heading, no border, the lifted cards (moved out of their rooms). The
  // first floor also carries the house-wide cases and To Do, each a
  // section only while it holds something.
  buildModel(dash) {
    const sections = [];
    const res = this.salApplied;
    const lifted = new Set(!this.s.edit && res ? res.now : []);
    const placed = this.casesPlaced();
    const floors = this.orderedFloors(dash);
    this._floorsOrdered = floors;
    if (lifted.size) {
      const items = [...lifted].map((id) => {
        if (id.startsWith('k:')) return { id, span: 2, grow: 3, dir: 'down', want: 3, hk: 'now' };
        const hit = this.findCard(id); if (!hit) return null;
        const it = this.itemOf(hit.card);
        // Lifted cards share one row kind, so a lone one is its own size
        // (a lock is two columns, not a banner across the page).
        return { ...it, hk: 'now', full: false, grow: Math.max(2, it.span) };
      }).filter(Boolean);
      if (items.length) sections.push({ id: '__now', w: 99, floor: -1, floorId: '__now', groups: [{ key: '__now:0', label: '', items }] });
    }
    floors.forEach((F, rank) => {
      const fl = F.fl;
      if (rank === 0 && !this.s.edit) {
        const house = placed.filter((k) => k._sec === '__cases' && !lifted.has('k:' + k.id));
        if (house.length) sections.push({ id: '__cases', w: 2, floor: rank, floorId: fl.id, groups: [{ key: '__cases:0', label: '', items: house.map((k) => ({ id: 'k:' + k.id, span: 2, grow: 3, dir: 'down', want: 3, hk: 'x:k' })) }] });
        if (this.todos().length) sections.push({ id: '__todo', w: 2, floor: rank, floorId: fl.id, groups: [{ key: '__todo:0', label: '', items: [{ id: 'td:list', span: 2, grow: 4, dir: 'down', want: 3, full: true, hk: 'x:td' }] }] });
      }
      F.secs.forEach((sec) => {
        if (sec.hidden && !this.s.edit) return;
        try { this.modelSection(sec, fl, rank, lifted, placed, res, sections); } catch (e) {
          this.roomFault(sec, e);
          sections.push({ id: sec.id, w: sec.width || 2, floor: rank, floorId: fl.id, groups: [] });
        }
      });
      if (this.s.edit) sections.push({ id: '__new@' + rank, w: 2, floor: rank, floorId: fl.id, groups: [] });
    });
    return { sections };
  }

  // One room's part of the model. Its own function so a room that throws
  // is caught by itself (buildModel) and the rest of the house still draws.
  modelSection(sec, fl, rank, lifted, placed, res, sections) {
    const groups = [];
    const state = this.roomState(sec);
    const ks = placed.filter((k) => k._sec === sec.id && !lifted.has('k:' + k.id));
    if (state === 'idle') { sections.push({ id: sec.id, w: sec.width || 2, floor: rank, floorId: fl.id, groups: [], folded: true }); return; }
    if (state === 'asleep') {
      const c = this.nightControl(sec);
      sections.push({ id: sec.id, w: sec.width || 2, floor: rank, floorId: fl.id, groups: c && !lifted.has(c.id) ? [{ key: sec.id + ':night', label: '', items: [this.itemOf(c)] }] : [], folded: true });
      return;
    }
    (sec.groups || []).forEach((g, gi) => {
      let cards = (g.cards || []).filter((c) => !lifted.has(c.id) && (this.s.edit || !isHeadCard(c)));
      // An item the list says leads its room goes first in its group.
      // An anchor keeps its slot whatever its score (§4.4): the
      // others are ordered around it.
      if (res && !this.s.edit) {
        const lead = (c) => (res.items[c.id] && res.items[c.id].band === 'lead' ? 1 : 0);
        const fixed = cards.map((c) => this.anchored(c.id));
        const free = cards.map((c, i) => ({ c, i })).filter((x) => !fixed[x.i]).sort((a, b) => lead(b.c) - lead(a.c) || a.i - b.i).map((x) => x.c);
        cards = cards.map((c, i) => (fixed[i] ? c : free.shift()));
      }
      // A card that leads its room carries a because line, so it is a
      // row of its own kind: beside plain strips of its type it was a
      // row of two heights (the engine's §5 rule).
      const items = cards.map((c) => { const it = this.itemOf(c); return this.leadsWithReason(c.id) ? { ...it, hk: it.hk + ':lead' } : it; });
      if (this.s.edit && gi === sec.groups.length - 1) items.push({ id: `add@${sec.id}@${gi}`, span: 1, grow: 1, dir: 'down', want: 3, hk: 'x:add' });
      if (items.length || g.label) groups.push({ key: sec.id + ':' + gi, label: g.label || '', items });
    });
    if (this.s.edit && !(sec.groups || []).length) groups.push({ key: sec.id + ':new', label: '', items: [{ id: `add@${sec.id}@0`, span: 1, grow: 1, dir: 'down', want: 3, hk: 'x:add' }] });
    // A case follows the room's own things (§13.2: "under the
    // hallway's lights, after its things").
    if (ks.length && !this.s.edit) groups.push({ key: sec.id + ':cases', label: '', items: ks.map((k) => ({ id: 'k:' + k.id, span: 2, grow: 4, dir: 'down', want: 3, hk: 'x:k' })) });
    sections.push({ id: sec.id, w: sec.width || 2, floor: rank, floorId: fl.id, groups });
  }

  renderBoard(dash) {
    const board = this.$('[data-board]');
    const model = this.buildModel(dash);
    // Coming up unfolds under the card whose Next chip opened it, across
    // that card's row, and in its own place under the story otherwise.
    const hostIt = this.upcHostItem(model);
    this._upcHosting = hostIt ? hostIt.id : null;
    if (hostIt) hostIt.full = true;
    this.homeUpcoming();
    this.engine.model = model;
    this.engine.openId = this.s.view ? this.s.view.id : null;
    this.engine.openMode = this.s.view ? this.s.view.mode : '';
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
      const facts = this.floorFacts(fl);
      const rooms = this.roomWords(F.secs, rank);
      const html = headless ? '<div data-flin="1"></div>' : `<div data-flin="1"><div class="flrow"><h2>${esc(fl.title)}</h2><span class="flr"></span><span class="facts">${facts.map((f, i) => `<span style="color:${f.color || 'inherit'}">${esc(f.t)}</span>${i < facts.length - 1 ? '<span class="sep"> · </span>' : ''}`).join('')}</span></div>${rooms ? `<div class="flrooms">${rooms}</div>` : ''}${this.tellBox('floor', fl.id)}</div>`;
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
            gl.style.color = mix(hue(sec.color), 55, 'var(--quiet)');
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
    this.placeUpcoming(dash);
    board.querySelectorAll('[data-key]').forEach((el) => {
      if (/^(fl|sec|g|t):/.test(el.dataset.key) && !want.has(el.dataset.key)) {
        if (el.dataset.key.startsWith('t:')) this.llCards.delete(el.dataset.key.slice(2));
        el.remove();
      }
    });
    this.engine.layout(!this._laidOut, false);
    this._laidOut = true;
    if (this.rail) this.rail.paint();
  }

  // A room's background, its glow and its state (§6, §9.1): a tint of its
  // own colour at 3% idle, 6% occupied, indigo at 4% asleep; a rose rule
  // down the left edge while it needs attention.
  paintSection(el, sec, ms) {
    el.setAttribute('aria-label', sec.title);
    const h = hue(sec.color);
    const state = this.roomState(sec);
    el.dataset.state = state;
    let gc = null, gb = 0;
    if (state !== 'idle' && state !== 'asleep') this.sectionEntities(sec).forEach((e) => { const s = this.hass.states[e]; if (s && domainOf(e) === 'light' && s.state === 'on') { const b = (s.attributes.brightness || 255) / 2.55; if (b > gb) { gb = b; gc = lightColor(s); } } });
    const glow = gc ? `radial-gradient(110% 60% at 0% 0%, ${mix(gc, Math.round(5 + gb * 0.07))}, transparent 70%), ` : '';
    const sHold = this.s.hold === 'sec:' + sec.id || (this.s.tell && this.s.tell.kind === 'section' && this.s.tell.id === sec.id);
    const bg = el.querySelector('.secbg');
    const tint = state === 'asleep' ? `linear-gradient(${mix('var(--indigo)', 4)}, ${mix('var(--indigo)', 4)})` : `linear-gradient(${mix(h, state === 'occupied' ? 6 : state === 'idle' ? 3 : 4)}, ${mix(h, state === 'occupied' ? 6 : state === 'idle' ? 3 : 4)})`;
    bg.style.background = state === 'idle' || state === 'asleep' ? `${tint}, var(--surface)` : `${glow}radial-gradient(140% 90% at 100% 0%, ${mix(h, 11)}, transparent 60%), radial-gradient(120% 80% at 0% 100%, ${mix(h, 6)}, transparent 65%), ${tint}, var(--surface)`;
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
    el.classList.remove('folded');
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
  setHtml(el, html) { html = this.speak(html); if (el.__html !== html) { el.__html = html; morph(el, html, this.shadowRoot); this.restoreTellText(el); } }

  // The words of a room line (§2.6): every room, by state. A dot before a
  // room that needs attention; asleep rooms dimmed; idle ones quiet.
  roomWords(secs, rank) {
    if (this.s.edit) return '';
    return secs.filter((sec) => !sec.hidden).map((sec) => {
      const st = this.roomState(sec);
      return `<button type="button" class="roomw rs-${st}" data-act="room" data-v="${esc(sec.id)}">${st === 'attention' ? '<i class="rdot"></i>' : ''}${esc(sec.title)}</button>`;
    }).join('');
  }

  // On a phone the room line is its own sticky row under the header, for
  // the whole house; on a wider screen the floor headings carry it.
  roomLineHtml(dash) {
    if (this.s.edit || this.s.thenAt) return '';
    const floors = this._floorsOrdered || this.orderedFloors(dash);
    const rows = floors.map((F) => `<span class="rlfloor">${esc(F.fl.title)}</span>${this.roomWords(F.secs)}`).join('');
    return rows ? `<nav class="roomline" aria-label="Rooms">${rows}</nav>` : '';
  }

  // Door and motion chips for a room's title line: a word only while open
  // or moving.
  // `room_marks: false` in dashboard.yaml takes them off every room (#347).
  chipsHtml(sec) {
    if (this.dash && this.dash.room_marks === false) return '';
    const H = this.hass; const out = [];
    this.sectionEntities(sec).forEach((e) => {
      const st = H.states[e]; if (!st || domainOf(e) !== 'binary_sensor') return;
      const dc = st.attributes.device_class;
      if (['door', 'window', 'garage_door', 'opening'].includes(dc)) out.push(`<span class="chip${st.state === 'on' ? ' on rose' : ''}"><i></i>${st.state === 'on' ? esc(shortName(friendly(H, e), sec.title)) + ' open' : ''}</span>`);
      if (['motion', 'occupancy', 'presence'].includes(dc)) out.push(`<span class="chip${st.state === 'on' ? ' on amber' : ''}"><i></i>${st.state === 'on' ? 'moving' : ''}</span>`);
    });
    return out.slice(0, 4).join('');
  }

  secHeadHtml(sec, state) {
    const edit = this.s.edit;
    const open = this.s.secEdit === sec.id;
    const ents = this.sectionEntities(sec);
    const H = this.hass;
    // The room's line: asleep, how warm (and what is usual, when brAIn has
    // measured it), whether anyone is there. What is on is on the tiles.
    const temp = ents.map((e) => H.states[e]).find((s) => s && s.attributes.device_class === 'temperature' && !isNaN(parseFloat(s.state)));
    const clim = temp ? null : ents.map((e) => H.states[e]).find((s) => s && domainOf(s.entity_id) === 'climate' && s.attributes.current_temperature != null);
    const slept = this.asleepSince(sec);
    const here = slept ? null : this.presence(sec);
    const usual = temp && this.feedState().usable ? (((this.brain().feed || {}).normal || {})[temp.entity_id] || {}).now : null;
    const tword = temp ? fmt(temp.state, '°') + (state === 'occupied' && usual ? ` · usually ${fmt(usual[0], '')}` : '') : clim ? fmt(clim.attributes.current_temperature, '°') : '';
    const res = this.salApplied;
    // A card lifted into Now leaves a one-word trace here, in its colour.
    const traces = !edit && res ? res.now.map((id) => res.items[id]).filter((x) => x && x.sec === sec.id && !String(x.id).startsWith('k:')).map((x) => {
      const hit = this.findCard(x.id);
      return hit ? `<button type="button" class="trace" data-act="jump" data-v="${esc(x.id)}" style="color:${x.color}">${esc(this.cardName(hit.card, sec))}, above</button>` : '';
    }).join('') : '';
    const needs = this.casesPlaced().filter((k) => k._sec === sec.id).length;
    const meta = [slept ? 'asleep' : '', tword, here == null || slept ? '' : here ? 'someone here' : '', sec.hidden ? 'hidden' : ''].filter(Boolean).join(' · ');
    // Scene words in the title row, one tap even when the room is folded.
    const scenes = []; this.sectionCards(sec).forEach((c) => { if (c.type === 'scenes') (c.entities || []).forEach((e) => scenes.push(e)); });
    const folded = state === 'idle' || state === 'asleep';
    // A header switch (`options.header`): a pill at the right of the title
    // row, folded or not, amber while on. In Edit it is a tile instead.
    const pills = edit ? '' : this.sectionCards(sec).filter(isHeadCard).map((c) => {
      const st = H.states[c.entity]; const on = !!st && st.state === 'on';
      const dead = !st || st.state === 'unavailable';
      return `<button type="button" class="shtog${on ? ' on' : ''}" data-act="head-toggle" data-v="${esc(c.entity)}" data-card="${esc(c.id)}" aria-pressed="${on}"${dead ? ' disabled' : ''}><i aria-hidden="true"></i>${esc(this.cardName(c, sec))}</button>`;
    }).join('');
    const sceneWords = folded && !edit && scenes.length ? `<span class="secscenes">${scenes.slice(0, 5).map((e) => `<button type="button" class="wd" data-act="scene" data-v="${esc(e)}">${esc(shortName(friendly(H, e), sec.title))}</button>`).join('')}</span>` : '';
    // Folded with a light on: a warm underline for the share that is on.
    const lights = ents.filter((e) => domainOf(e) === 'light' && H.states[e] && !(H.states[e].attributes.entity_id || []).length);
    const lit = lights.filter((e) => H.states[e].state === 'on').length;
    const under = folded && lit ? `<i class="litline" style="width:${Math.round(lit / lights.length * 100)}%"></i>` : '';
    const because = state === 'attention' && res ? (() => { const x = Object.values(res.items).find((y) => y.sec === sec.id && ['lead', 'now'].includes(y.band) && y.why && !res.now.includes(y.id)); return x ? `<p class="secbecause" style="color:${x.why.color}">${esc(x.why.text)}</p>` : ''; })() : '';
    let editor = '';
    if (edit && open) {
      const floors = (this.dash.floors || []);
      editor = `<div data-ctl="1" class="edit" style="flex-basis:100%;padding:10px 10px 8px 0">
<label class="flab">Title<input class="fld" type="text" data-keep="sec-title" data-act-change="sec-title" data-v="${esc(sec.id)}" value="${esc(sec.title)}"></label>
<div class="flab">Color<div class="hues">${HUES.map((hn) => `<button type="button" class="hue" data-act="sec-hue" data-v="${esc(sec.id)}" data-h="${hn}" aria-label="${hn}" aria-pressed="${sec.color === hn}"><span style="background:var(--${hn});box-shadow:${sec.color === hn ? `0 0 0 3px var(--surface), 0 0 0 5px var(--${hn})` : 'none'}"></span></button>`).join('')}</div></div>
<div class="flab">Floor<div class="row" style="flex-wrap:wrap;gap:0 18px">${floors.map((f) => `<button type="button" class="wd" data-act="sec-floor" data-v="${esc(sec.id)}" data-f="${esc(f.id)}" aria-pressed="${f.sections.includes(sec)}" style="font-size:15px;font-weight:600;text-transform:none;letter-spacing:0">${esc(f.title)}</button>`).join('')}<button type="button" class="wd" data-act="sec-floor-new" data-v="${esc(sec.id)}" style="font-size:15px;text-transform:none;letter-spacing:0">New floor…</button></div></div>
<div class="flab">Width<div class="row" style="gap:0 18px">${[[1, 'Narrow'], [2, 'Medium'], [3, 'Wide'], [4, 'Widest']].map((x) => `<button type="button" class="wd" data-act="sec-width" data-v="${esc(sec.id)}" data-w="${x[0]}" aria-pressed="${(sec.width || 2) === x[0]}" style="font-size:15px;font-weight:600;text-transform:none;letter-spacing:0">${x[1]}</button>`).join('')}</div></div>
<div class="flab">Group<div class="row" style="gap:0 18px"><button type="button" class="wd" data-act="sec-group" data-v="${esc(sec.id)}" style="font-size:15px;text-transform:none;letter-spacing:0">Add a group</button></div></div>
<div class="row" style="gap:0 18px"><button type="button" class="go" data-act="sec-hide" data-v="${esc(sec.id)}" style="font-size:14px;color:var(--muted)">${sec.hidden ? 'Show section' : 'Hide section'}</button><button type="button" class="go" data-act="sec-remove" data-v="${esc(sec.id)}" style="font-size:14px;color:var(--rose)">Remove section</button></div></div>`;
    }
    const grip = edit ? '<svg aria-hidden="true" width="12" height="18" viewBox="0 0 12 18" style="flex-shrink:0;color:var(--quiet);margin-left:-8px"><path d="M3 3h.01M9 3h.01M3 9h.01M9 9h.01M3 15h.01M9 15h.01" stroke="currentColor" stroke-width="3" stroke-linecap="round"></path></svg>' : '';
    // The room's name is a button: tap it to fold or unfold the room.
    const name = edit ? `<h2>${esc(sec.title)}</h2>` : `<h2><button type="button" class="roomname" data-act="room-toggle" data-v="${esc(sec.id)}" aria-expanded="${!folded}">${esc(sec.title)}</button></h2>`;
    return `${grip}<div class="sectitle">${name}<span class="secmeta">${esc(meta)}</span>${needs ? `<span class="needs">${needs} need${needs === 1 ? 's' : ''} you</span>` : ''}${traces}${sceneWords}<span class="flex1"></span>${this.chipsHtml(sec)}${pills}${under}</div>${because}${edit ? `<button type="button" class="go" data-act="sec-edit" data-v="${esc(sec.id)}" style="padding:0 8px;font-size:13px;color:var(--muted)">${open ? 'Close' : 'Edit'}</button>` : ''}${this.tellBox('section', sec.id)}${editor}`;
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
    const mt = el.querySelector('.mtile');
    const face = el.querySelector('[data-face]');
    const moreEl = el.querySelector('[data-more]');
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
      this.setHtml(face, c ? caseFace(c, { pending, family: this.viewer().device === 'family', replyOpen: !!this.s.replyOpen[c.id], admin: this.admin(), who: this.who(), name: (eid) => (this.hass.states[eid] ? friendly(this.hass, eid) : '') }) + why : '');
      this.setHtml(moreEl, '');
      return;
    }
    if (id === 'td:list') {
      mt.style.cssText = 'background:transparent;cursor:auto;touch-action:pan-y';
      this.setHtml(face, todoFace(this.todos(), this.hass, { open: this.s.todoOpen, sliding: this.tdD && this.tdD.slid ? this.tdD.id : null, slideWord: 'Snooze a week' }));
      this.setHtml(moreEl, '');
      return;
    }
    // The ghost "Add card" in Edit.
    if (id.startsWith('add@')) {
      const open = this.s.view && this.s.view.id === id;
      mt.style.cssText = `background:${open ? 'var(--surface)' : 'transparent'};box-shadow:inset 0 0 0 1.5px var(--line2);cursor:pointer`;
      this.setHtml(face, `<div class="sline" style="height:56px;color:var(--muted)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg><b style="font-size:14px">Add card</b></div>`);
      this.setHtml(moreEl, open ? this.addCardHtml(sec, Number(id.split('@')[2])) : '');
      return;
    }
    const hit = this.findCard(id); if (!hit) return;
    const card = hit.card; const T = typeOf(card);
    const hv = this.hassView();
    const st = card.entity ? hv.states[card.entity] : null;
    const open = this.s.view && this.s.view.id === id;
    const mode = open ? this.s.view.mode : '';
    const name = this.cardName(card, hit.sec);
    const lifted = ms && ms.id === '__now';
    const x = this.salNow(id);
    const ctx = { hass: hv, card, st, sec: hit.sec, name, open, member: open ? this.s.view.member : null, H: (open && this.s.view.H) || (card.type === 'readings' ? (this.s.rfocus && this.s.rfocus[id] ? { focus: this.s.rfocus[id] } : {}) : {}), preview: this.s.previews[id] != null ? this.s.previews[id] : null, memberPreview: open ? this.s.memberPreview : null, confirm: this.s.confirm[id] && this.s.confirm[id].until > Date.now() ? this.s.confirm[id].text : '', night: this.salApplied && this.salApplied.period === 'night' };
    let faceHtml = '', moreHtml = '';
    try {
      ctx.accent = card.color ? hue(card.color) : T.accent(ctx);
      const slide = !this.s.edit && !this.s.thenAt && T.slide ? T.slide(ctx) : null;
      ctx.hint = this.s.edit ? (open ? '' : `tap to edit · hold to tell ${this.who()}`) : (open || T.noOpen || this.s.thenAt) ? '' : slide ? 'slide · tap · hold for more' : T.tap(ctx) ? 'tap · hold for more' : 'tap for more';
      faceHtml = T.face(ctx);
      // The because line (§11): one sentence, in the item's meaning colour,
      // on a card the list lifted or put at the top of its room. Hold it to
      // ask brAIn why.
      // Whether it leads is the APPLIED list's word (the row it sits in was
      // laid out from it, `leadsWithReason`); what it says is the newest.
      if (!this.s.edit && !this.s.thenAt && x.why && (lifted || this.leadsWithReason(id)) && x.why.kind !== 'none') faceHtml += `<p class="because" data-why="${esc(id)}" style="color:${x.why.color}">${esc(x.why.text)}</p>`;
      else if (lifted && x.why) faceHtml += `<p class="because" data-why="${esc(id)}" style="color:${x.why.color}">${esc(x.why.text)}</p>`;
      if (open && mode === 'adv') moreHtml = `<div class="more rise" data-ctl-scope="1">${this.keepHtml(card, lifted || x.band === 'lead')}${T.more(ctx)}${detailCard(card) ? `<div class="ll" data-ll="${esc(id)}:detail"></div>` : ''}${T.host ? '' : this.moreInfoHtml(card, ctx)}</div>`;
      if (open && mode === 'edit') moreHtml = this.cardEditHtml(hit, name);
      if (open && mode === 'tell') moreHtml = `<div class="more">${this.tellBox('card', id)}</div>`;
    } catch (e) {
      faceHtml = `<div class="box"><b>${esc(name)}</b><span class="sm">This card could not be drawn.</span></div>`;
      this.report('card', String(e && e.message || e), String(e && e.stack || '').slice(0, 1500), card.type);
    }
    const holding = this.s.hold === id;
    const tell = this.s.tell && this.s.tell.kind === 'card' && this.s.tell.id === id;
    const ring = tell || holding && this.s.edit ? `inset 0 0 0 2px ${mix('var(--violet)', 60)}` : this.s.edit ? `inset 0 0 0 1px ${mix(hue(hit.sec.color), 30)}` : open ? `inset 0 0 0 1.5px ${mix(ctx.accent || 'var(--text)', 40)}` : lifted && x.urgent ? 'inset 3px 0 0 var(--rose)' : 'none';
    mt.style.background = open && !this.s.edit ? mix(ctx.accent || 'var(--text)', 7, 'var(--surface)') : lifted ? 'var(--surface)' : 'transparent';
    mt.style.boxShadow = ring;
    mt.style.cursor = this.s.edit ? 'pointer' : 'default';
    mt.classList.toggle('holding', holding);
    mt.classList.toggle('lifted', !!lifted);
    mt.classList.toggle('sliding', this.s.previews[id] != null);
    // Every tile is a Tab stop with its role, name and value.
    if (!T.noOpen || T.tap(ctx)) {
      try {
        const aria = tileAria(T, ctx, name);
        mt.setAttribute('tabindex', '0'); mt.setAttribute('role', aria.role); mt.setAttribute('aria-label', aria.label);
        if (aria.role === 'slider') { mt.setAttribute('aria-valuenow', String(aria.now)); mt.setAttribute('aria-valuemin', '0'); mt.setAttribute('aria-valuemax', '100'); mt.setAttribute('aria-valuetext', aria.value); } else ['aria-valuenow', 'aria-valuemin', 'aria-valuemax', 'aria-valuetext'].forEach((a) => mt.removeAttribute(a));
        if (aria.role === 'switch') mt.setAttribute('aria-checked', String(aria.checked)); else mt.removeAttribute('aria-checked');
        if (aria.role === 'button') mt.setAttribute('aria-expanded', String(!!open)); else mt.removeAttribute('aria-expanded');
      } catch (e) { /* a type whose tap throws is reported when it draws */ }
    }
    const hb = holding ? `<span class="holdbar" style="background:${this.s.edit ? 'var(--violet)' : ctx.accent}"></span>` : '';
    let hbEl = mt.querySelector('.holdbar');
    if (hb && !hbEl) mt.insertAdjacentHTML('afterbegin', hb); else if (!hb && hbEl) hbEl.remove();
    if (id === this._upcHosting) faceHtml += '<div class="upcslot" data-key="upcslot" data-upc-slot data-morph-keep></div>';
    this.setHtml(face, faceHtml);
    this.setHtml(moreEl, moreHtml);
    if (T.host) this.mountLovelace(face, card);
    // `options.detail`: a Lovelace card shown only while this card is open.
    // Mounted the first time and kept (llCards), so opening it again does
    // not load it again.
    const detail = open && mode === 'adv' ? detailCard(card) : null;
    if (detail) this.mountLovelace(moreEl, { id: id + ':detail', card: detail });
  }

  // The two extra words on a card the list lifted or led (§11): Keep here
  // (a pin, written to dashboard.yaml so every device keeps it) and Not this
  // (sinks it for today; a habit loses half its weight).
  keepHtml(card, shown) {
    if (!shown && !card.pin) return '';
    if (!this.admin()) return '';
    return `<div class="row keeprow" style="gap:0 18px">${card.pin ? `<button type="button" class="wd" data-act="unpin" data-v="${esc(card.id)}">Stop keeping it here</button>` : `<button type="button" class="wd go" data-act="keep" data-v="${esc(card.id)}">Keep here</button>`}<button type="button" class="wd" data-act="not-this" data-v="${esc(card.id)}">Not this</button></div>`;
  }

  // Home Assistant's own pages for what an opened card shows: the entity's
  // more-info dialog (history, attributes, settings, related) and, for an
  // admin, its device page. The dialog is Home Assistant's, opened the way
  // a Lovelace card opens it, so it is whatever this core's dialog is.
  moreInfoHtml(card, ctx) {
    const ids = card.entities || [];
    const eid = ctx.member || card.entity || (ids.length === 1 ? ids[0] : '');
    if (!eid || !this.hass.states[eid]) return '';
    const reg = this.hass.entities && this.hass.entities[eid];
    const dev = reg && reg.device_id;
    const who = ctx.member ? friendly(this.hass, eid) : '';
    const btn = (act, v, label) => `<button type="button" class="wd" data-ctl="1" data-act="${act}" data-v="${esc(v)}">${esc(label)}</button>`;
    return `<div class="moreinfo">${btn('more-info', eid, who ? `${who}: details` : 'Details')}${dev && this.admin() ? btn('open-device', dev, 'Device page') : ''}</div>`;
  }

  async mountLovelace(face, card) {
    const slot = face.querySelector('[data-ll]'); if (!slot) return;
    let el = this.llCards.get(card.id);
    const sig = JSON.stringify(card.card);
    if (el && el.__sig !== sig) { el = null; }
    if (!el) {
      if (this._llPending && this._llPending.has(card.id)) return;
      (this._llPending = this._llPending || new Set()).add(card.id);
      try {
        const ctag = String((card.card && card.card.type) || '');
        // A defined custom card needs nothing from Lovelace; do not wait for it.
        const direct = typeof window.loadCardHelpers !== 'function' && ctag.startsWith('custom:') && window.customElements && !!customElements.get(ctag.slice(7));
        const helpers = direct ? null : await cardHelpers();
        // A custom card mounted before its element is defined shows
        // "Configuration error" for good: wait (up to 4 s) for it first.
        const tag = String((card.card && card.card.type) || '');
        if (tag.startsWith('custom:') && window.customElements && !customElements.get(tag.slice(7))) {
          await Promise.race([customElements.whenDefined(tag.slice(7)), new Promise((r) => setTimeout(r, 4000))]);
        }
        if (helpers) el = await helpers.createCardElement(card.card);
        else el = customCardWithoutHelpers(card.card);
        el.__sig = sig;
        el.hass = this.hass;
        el.addEventListener('ll-rebuild', () => { this.llCards.delete(card.id); this.schedule(); });
        this.llCards.set(card.id, el);
      } catch (e) {
        slot.innerHTML = '<p class="sm" style="padding:12px">This card could not be drawn yet; reload the page.</p>';
        this.report('card', `A Lovelace card failed: ${e.message || e}`, sig.slice(0, 500), String(card.card && card.card.type));
        return;
      } finally { this._llPending.delete(card.id); }
    }
    if (el.parentNode !== slot) { slot.innerHTML = ''; slot.appendChild(el); }
    // One observer, one lay-out per frame, each slot observed once.
    if (!this._llRo) this._llRo = new ResizeObserver(() => { cancelAnimationFrame(this._llRaf); this._llRaf = requestAnimationFrame(() => this.engine.layout(false, true)); });
    if (!slot.__llObserved) { slot.__llObserved = true; this._llRo.observe(slot); }
  }

  // ------------------------------------------------------------- editing

  cardEditHtml(hit, name) {
    const { card, sec } = hit;
    const T = typeOf(card);
    const sections = []; this.eachSection((s, fl) => sections.push({ id: s.id, label: `${fl.title} › ${s.title}` }));
    const yaml = JSON.stringify(card, null, 2);
    return `<div class="edit" data-ctl="1">
<label class="flab">Name<input class="fld" type="text" data-keep="card-name" data-act-change="card-name" data-v="${esc(card.id)}" value="${esc(card.name || '')}" placeholder="${esc(name)}"></label>
<div class="flab">Size<div class="row" style="gap:0 18px">${[[0, 'Auto'], [1, 'Small'], [2, 'Medium'], [3, 'Large']].map((x) => `<button type="button" class="wd" data-act="card-span" data-v="${esc(card.id)}" data-w="${x[0]}" aria-pressed="${(card.span || 0) === x[0]}" style="font-size:15px;font-weight:600;text-transform:none;letter-spacing:0">${x[1]}</button>`).join('')}</div></div>
<label class="flab">Move to<select class="fld" data-act-change="card-move" data-v="${esc(card.id)}">${sections.map((s) => `<option value="${esc(s.id)}"${s.id === sec.id ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
<details class="payload"><summary>Card YAML (as JSON)</summary><textarea class="code-ed" data-keep="card-yaml" style="min-height:140px" spellcheck="false">${esc(yaml)}</textarea><button type="button" class="wd go" data-act="card-yaml" data-v="${esc(card.id)}">Save this card</button></details>
<div class="row" style="gap:0 18px"><button type="button" class="go" data-act="card-remove" data-v="${esc(card.id)}" style="font-size:14px;color:var(--rose)">Remove card</button><span class="flex1"></span><span class="small">${esc(T === TYPES.lovelace ? 'Lovelace card' : card.type)}</span></div></div>`;
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
    const sugs = (TELL_SUGS[kind] || []).map((s) => `<button type="button" class="wd" data-act="tell-sug" data-v="${esc(s)}" style="font-size:13px;min-height:34px">${esc(s)}</button>`).join('');
    const head = `<div class="row" style="min-width:0">${SPARK}<span style="font-size:13px;font-weight:600;white-space:nowrap">Tell ${esc(this.who())}</span><span class="small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0">${esc(t.path || '')}</span></div>`;
    const scope = composing ? `<span class="small">${kind === 'code' ? 'Changes Morph’s own code for this house.' : 'Changes this dashboard only.'} Home Assistant is changed only if you ask (“make a sensor for…”), and nothing goes to GitHub unless you say yes.</span>` : '';
    if (composing) {
      return `<div data-ctl="1" data-tell="1" class="tell rise" style="margin-top:6px">${head}${turns}${this.shotHtml(t.shot, t.turns && t.turns.length ? 'How it looks now — brAIn sees this' : 'What brAIn will see')}
<textarea class="tellin" rows="3" data-keep="tell" data-tellkey="${esc(kind + ':' + (id || ''))}" aria-label="What should change" placeholder="${esc(kind === 'dashboard' ? 'Add a Pets section with the feeder and water bowl…' : t.turns && t.turns.length ? 'What should it do differently?' : 'Say what should change…')}"></textarea>${scope}
<div class="row" style="flex-wrap:wrap;gap:0 16px">${t.turns && t.turns.length ? '' : sugs}<span class="flex1"></span><button type="button" class="wd" data-act="tell-cancel" style="font-size:14px;min-height:36px">${t.turns && t.turns.length ? 'Close' : 'Cancel'}</button><button type="button" class="wd" data-act="tell-send" style="font-size:14px;font-weight:700;min-height:36px;color:var(--violet)">Send</button></div></div>`;
    }
    const all = st.steps || [];
    const SHOW = 7;
    const line = (x, i, arr) => `<div class="step${arr && i === arr.length - 1 ? ' rise' : ''}${x.brain ? ' bstep' : ''}"><i style="background:${x.tone === 'bad' ? 'var(--rose)' : x.tone === 'good' ? 'var(--teal)' : 'var(--violet)'}"></i><span>${esc(x.t)}</span></div>`;
    const earlier = all.length > SHOW ? all.slice(0, all.length - SHOW) : [];
    const folded = earlier.length + (st.folded || 0);
    const steps = (folded ? `<details class="earlier"><summary>${folded} earlier step${folded === 1 ? '' : 's'}</summary>${earlier.map((x) => line(x)).join('')}</details>` : '') + all.slice(-SHOW).map(line).join('');
    const working = !done ? `<div class="working"><span class="pulse"></span><span>${esc(this.phaseWords(st))}</span><span class="small" data-since="${Number(st.started) || ''}"></span></div>` : '';
    const picture = t.shot && t.shot.url ? this.pairHtml(t.shot.url, t.after) : t.shot && t.shot.status === 'failed' ? `<span class="small">No picture this time (${esc(t.shot.error || 'it could not be drawn')}); brAIn was given the card’s text instead.</span>` : '';
    // No `rise` here: this box is rebuilt each time brAIn takes a step, and
    // replaying the blur-in on every rebuild made it flicker as it worked.
    return `<div data-ctl="1" data-tell="1" class="tell" style="margin-top:6px">${head}${turns}
<span style="font-size:14px">“${esc(t.text)}”</span>${picture}
<div class="steps">${steps || '<div class="step"><i style="background:var(--violet)"></i><span>Handing it to brAIn…</span></div>'}</div>${working}
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
      if (stale) parts.push('<span style="color:var(--amber)">This screen has not caught up yet. <button type="button" class="wd go" data-act="tell-refresh" style="min-height:28px">Refresh</button></span>');
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
    const learn = L.running ? '<div class="activity"><span class="pulse"></span><span class="lx"><b>Morph is learning from how this dashboard is used</b><span>brAIn is reading the last month of use; suggestions appear where they belong.</span></span></div>' : '';
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
      // An OPEN card is its face: the opened part below it is the editor
      // or the Tell box, and a picture of that is a card in a large hole.
      const tile = R.querySelector(`[data-tile="${CSS.escape(scope.id || '')}"]`);
      const more = tile && tile.querySelector('[data-more]');
      return more && more.childElementCount ? (tile.querySelector('[data-face]') || tile) : tile;
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
  shoot(t) {
    const el = this.targetEl(t);
    if (!el) { t.shot = { status: 'failed', error: 'Morph could not find it on the page', view: {}, png: '' }; return; }
    let bg = '';
    try { bg = getComputedStyle(this.rootEl).backgroundColor; } catch (e) { /* no background to lay it on */ }
    const job = snap.prepare(el, { background: bg, fontsUrl: FONTS_URL });
    const shot = { status: 'taking', view: job.view, png: '', error: '', id: '' };
    t.shot = shot;
    shot.ready = (async () => {
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

  openTell(scope) {
    if (!this.admin()) return;
    const path = this.pathOf(scope);
    this.s.tell = { ...scope, path, text: '', sent: false, draft: '', turns: [] };
    this.shoot(this.s.tell);
    if (scope.kind === 'card') this.openView(scope.id, 'tell');
    else if (this.s.view) this.closeView();
    this.s.hold = null;
    this.schedule();
    setTimeout(() => { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); if (ta) { try { ta.focus({ preventScroll: true }); } catch (e) { ta.focus(); } } }, 360);
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
    const cur = this.s.view;
    if (cur && cur.id === id && cur.mode === mode) return;
    this.engine.originId = id;
    if (cur && cur.id !== id) { this.s.fading = cur.id; clearTimeout(this._fadeT); this._fadeT = setTimeout(() => { this.s.fading = null; this.schedule(); }, 520); }
    this.s.view = { id, mode, member: cur && cur.id === id ? cur.member : null, H: { depth: 0 } };
    if (mode === 'adv') { const hit = this.findCard(id); this.track('open', id, hit && hit.sec.id); }
    this.schedule();
  }

  closeView() {
    const cur = this.s.view; if (!cur) return;
    if (this.s.tell && this.s.tell.kind === 'card' && this.s.tell.id === cur.id) this.s.tell = null;
    this.engine.originId = cur.id;
    this.s.view = null; this.s.fading = cur.id; this.s.memberPreview = null;
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
    root.addEventListener('pointerdown', () => { this.ui.lastTouch = Date.now(); if (this.form_ === 'still') this.schedule(); }, true);
    root.addEventListener('keydown', () => { this.ui.lastTouch = Date.now(); }, true);
    // The Ask suggestions only show while the field has focus, so pressing
    // one must not take the focus away first (Safari never focuses a button).
    root.addEventListener('mousedown', (e) => { if (e.target.closest && e.target.closest('[data-act="ask-sug"]')) e.preventDefault(); });
    root.addEventListener('pointerdown', (e) => this.onDown(e));
    root.addEventListener('pointermove', (e) => this.onMove(e));
    root.addEventListener('pointerup', (e) => this.onUp(e));
    root.addEventListener('pointercancel', () => this.cancelPtr());
    root.addEventListener('contextmenu', (e) => { if (e.target.closest && e.target.closest('.mtile, [data-hold], .sechead, .flh')) e.preventDefault(); });
    root.addEventListener('click', (e) => this.onClick(e));
    root.addEventListener('change', (e) => this.onChange(e));
    root.addEventListener('input', (e) => {
      const t = e.target;
      if (t.dataset && t.dataset.tellkey && this.s.tell) this.s.tell.draft = t.value;
      // The report box keeps its words through Settings' own re-renders.
      if (t.dataset && t.dataset.keep === 'report') this.s.report = { ...(this.s.report || {}), text: t.value };
      if (t.dataset && t.dataset.keep === 'report-ui') this.s.report = { ...(this.s.report || {}), ui: t.checked };
    });
    root.addEventListener('keydown', (e) => {
      const t = e.target;
      if (t.dataset && t.dataset.upcVp != null && this._upc && ['ArrowRight', 'ArrowLeft', 'Home'].includes(e.key)) {
        e.preventDefault();
        const m = this._upc; const c = this.upcCursor(m);
        const n = e.key === 'Home' ? 0 : upc.step(m, c, e.key === 'ArrowRight' ? 1 : -1);
        if (n != null) this.upcGo(m, n);
        return;
      }
      if (e.key === 'Escape') {
        if (this.s.tell) this.closeTell(); else if (this.s.view) { const id = this.s.view.id; this.closeView(); const mt = this.shadowRoot.querySelector(`[data-mt="${CSS.escape(id)}"]`); if (mt) mt.focus({ preventScroll: true }); }
        return;
      }
      // `/` goes to Ask, from anywhere that is not a text box.
      if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')) {
        const a = this.shadowRoot.querySelector('input[data-keep="ask"]');
        if (a) { e.preventDefault(); a.focus(); }
        return;
      }
      // A focused tile: Enter or Space taps it, Shift+Enter opens it, the
      // arrows move a level by ten.
      if (t.classList && t.classList.contains('mtile') && !this.s.edit) {
        const id = t.dataset.mt;
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (e.shiftKey || e.key === 'ContextMenu') this.openView(id, 'adv'); else this.tapCard(id); return; }
        if (e.key === 'ContextMenu') { e.preventDefault(); this.openView(id, 'adv'); return; }
        if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
          const hit = this.findCard(id); if (!hit) return;
          const T = typeOf(hit.card); const ctx = { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null };
          const sl = T.slide ? T.slide(ctx) : null; if (!sl) return;
          e.preventDefault();
          const v = Math.max(0, Math.min(100, sl.get() + (['ArrowRight', 'ArrowUp'].includes(e.key) ? 10 : -10)));
          this.call(sl.call(v)); this.noteUse(id);
          return;
        }
      }
      if ((e.key === 'Enter' || e.key === ' ') && t.dataset && t.dataset.todo != null && !(e.target.closest && e.target.closest('button'))) { e.preventDefault(); this.todoDone(t.dataset.todo); return; }
      if (e.key === 'Enter' && !e.shiftKey) {
        if (t.dataset && t.dataset.tellkey) { e.preventDefault(); this.sendTell(t.value); }
        else if (t.dataset && t.dataset.actEnter) { e.preventDefault(); this.act(t.dataset.actEnter, t); }
      }
    });
    root.addEventListener('pointermove', (e) => this.scrub(e));
    root.addEventListener('pointerout', (e) => this.scrubEnd(e));
    root.addEventListener('wheel', (e) => this.upcWheel(e), { passive: false });
    root.addEventListener('morph-coming-up', (e) => this.onComingUp(e));
  }

  // Anything outside the open thing folds it back (§1.10).
  outside(e) {
    const inside = (sel) => !!(e.target.closest && e.target.closest(sel));
    if (this.s.secEdit && !inside(`[data-sec-head="${CSS.escape(this.s.secEdit)}"]`)) { this.s.secEdit = null; this.schedule(); }
    // Outside Ask, the answers that are finished fold away; a question
    // still being answered stays until it is.
    if (this.s.asks.some((a) => !a.busy) && !inside('[data-ask]')) { this.s.asks = this.s.asks.filter((a) => a.busy); this.schedule(); }
    const t = this.s.tell;
    if (t && !inside('[data-tell]') && !(t.kind === 'card' && inside(`[data-tile="${CSS.escape(t.id)}"]`)) && !t.sent) { this.closeTell(); }
    if (this.s.todoOpen != null && !inside(`[data-todo="${CSS.escape(String(this.s.todoOpen))}"]`)) { this.s.todoOpen = null; this.schedule(); }
    const v = this.s.view;
    if (v && !inside(`[data-tile="${CSS.escape(v.id)}"]`)) {
      if (inside('[data-tile]') && !this.s.edit) this.swallow = performance.now();
      this.closeView();
    }
  }

  onDown(e) {
    if (e.button != null && e.button !== 0) return;
    this.outside(e);
    const t = e.target;
    // A To Do row: tap ticks it off, slide right snoozes it a week, hold
    // opens its options.
    const tr = t.closest && t.closest('[data-todo]');
    if (tr && !(t.closest('button'))) {
      const id = tr.dataset.todo;
      this.tdD = { id, x0: e.clientX, y0: e.clientY, slid: false, held: false, pid: e.pointerId, el: tr };
      clearTimeout(this.tdT);
      this.tdT = setTimeout(() => { if (this.tdD && this.tdD.id === id && !this.tdD.slid) { this.tdD.held = true; this.s.todoOpen = id; this.schedule(); } }, this.holdMs());
      return;
    }
    // Hold a because line to ask brAIn why (§11).
    const why = t.closest && t.closest('[data-why]');
    if (why && !this.s.edit) {
      const wid = why.dataset.why;
      clearTimeout(this.whyT);
      this.whyT = setTimeout(() => { this.ptr = null; this.askWhy(wid); }, this.holdMs());
    }
    // a member strip inside an opened light group
    const mem = t.closest && t.closest('[data-member]');
    if (mem && !this.s.edit) { const r = mem.getBoundingClientRect(); this.mptr = { id: mem.dataset.member, x0: e.clientX, y0: e.clientY, r, drag: false, el: mem, pid: e.pointerId }; return; }
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
    if (id.startsWith('k:') || id.startsWith('td:')) return;
    // THEN is a picture of the past: nothing on it can be pressed.
    if (this.s.thenAt) return;
    const hit = id.startsWith('add@') ? null : this.findCard(id);
    const T = hit ? typeOf(hit.card) : null;
    const ctx = hit ? { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null } : null;
    const slide = hit && !this.s.edit && T.slide ? T.slide(ctx) : null;
    const r = mt.getBoundingClientRect();
    this.ptr = { id, x0: e.clientX, y0: e.clientY, drag: false, held: false, el: mt, r, slide, pid: e.pointerId, noOpen: T && T.noOpen };
    if (id.startsWith('add@')) return;
    clearTimeout(this.holdT);
    if (this.s.edit) {
      this.s.hold = id; this.schedule();
      this.holdT = setTimeout(() => { if (this.ptr && this.ptr.id === id && !this.ptr.drag) { this.ptr.held = true; this.openTell({ kind: 'card', id }); } }, this.holdMs());
      return;
    }
    if (!(T && T.noOpen)) {
      this.holdT = setTimeout(() => { if (this.ptr && this.ptr.id === id && !this.ptr.drag) { this.ptr.held = true; this.s.hold = null; if (!(this.s.view && this.s.view.id === id)) this.openView(id, 'adv'); } }, this.holdMs());
      this.s.hold = id; this.schedule();
    }
  }

  holdMs() { return this.settings().hold_ms || HOLD_MS; }

  onMove(e) {
    if (this.upcD) { this.upcMove(e); return; }
    const td = this.tdD;
    if (td) {
      const dx = e.clientX - td.x0, dy = e.clientY - td.y0;
      if (!td.slid && Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx)) { clearTimeout(this.tdT); this.tdD = null; return; }
      if (!td.slid && dx > 14 && Math.abs(dx) > Math.abs(dy)) { td.slid = true; clearTimeout(this.tdT); try { td.el.setPointerCapture(td.pid); } catch (er) { /* fine */ } }
      if (td.slid) { td.el.style.transform = `translateX(${Math.max(0, Math.min(140, dx)).toFixed(0)}px)`; td.dx = dx; if ((dx > 60) !== !!td.armed) { td.armed = dx > 60; this.schedule(); } }
      return;
    }
    if (this.whyT && Math.hypot(e.movementX || 0, e.movementY || 0) > 8) clearTimeout(this.whyT);
    const mp = this.mptr;
    if (mp) {
      const dx = e.clientX - mp.x0, dy = e.clientY - mp.y0;
      if (!mp.drag) { if (Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy)) { mp.drag = true; try { mp.el.setPointerCapture(mp.pid); } catch (er) { /* fine */ } } else if (Math.abs(dy) > 10) { this.mptr = null; return; } }
      if (mp.drag) { this.s.memberPreview = { id: mp.id, v: Math.round(Math.max(0, Math.min(100, ((e.clientX - mp.r.left) / mp.r.width) * 100))) }; this.schedule(); }
      return;
    }
    if (this.drag) { this.secMove(e); return; }
    if (this.thold && Math.hypot(e.clientX - this.thold.x, e.clientY - this.thold.y) > 8) this.holdEnd();
    const p = this.ptr; if (!p || p.held) return;
    const dx = e.clientX - p.x0, dy = e.clientY - p.y0;
    if (!p.drag) {
      if (p.slide && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) { p.drag = true; clearTimeout(this.holdT); this.s.hold = null; try { p.el.setPointerCapture(p.pid); } catch (er) { /* fine */ } }
      else if (Math.hypot(dx, dy) > 10) { clearTimeout(this.holdT); this.ptr = null; this.s.hold = null; this.schedule(); return; }
    }
    if (p.drag) { this.s.previews[p.id] = Math.round(Math.min(100, Math.max(0, ((e.clientX - p.r.left) / p.r.width) * 100))); this.schedule(); }
  }

  onUp(e) {
    clearTimeout(this.whyT);
    if (this.upcD) { this.upcUp(e); return; }
    const td = this.tdD;
    if (td) {
      this.tdD = null; clearTimeout(this.tdT);
      td.el.style.transform = '';
      if (td.slid) { if (td.dx > 60) this.todoAct('snooze', td.id); else this.schedule(); return; }
      if (!td.held) this.todoDone(td.id);
      return;
    }
    const mp = this.mptr;
    if (mp) {
      this.mptr = null;
      if (mp.drag && this.s.memberPreview) { const v = this.s.memberPreview.v; this.call(v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: mp.id } } : { domain: 'light', service: 'turn_on', data: { entity_id: mp.id, brightness_pct: v } }); this.settlePreview('member', mp.id, v); }
      else if (!mp.drag) this.call({ domain: 'light', service: 'toggle', data: { entity_id: mp.id } });
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
      this.settlePreview('card', p.id, v);
      return;
    }
    if (p.held || sw) return;
    const id = p.id;
    if (id.startsWith('add@')) { if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'add'); return; }
    if (this.s.edit) { const v = this.s.view; if (v && v.id === id) this.closeView(); else this.openView(id, 'edit'); return; }
    this.tapCard(id);
  }

  // A slid level is shown until the device reports it (up to 5 s), rather
  // than for a fixed second that let the old value flash back first.
  settlePreview(kind, id, v) {
    const start = Date.now();
    const done = () => { if (kind === 'member') this.s.memberPreview = null; else delete this.s.previews[id]; this.schedule(); };
    const check = () => {
      const hit = kind === 'card' ? this.findCard(id) : null;
      const eid = kind === 'member' ? id : hit && hit.card.entity;
      const st = eid && this.hass.states[eid];
      const now = st ? (st.attributes.brightness != null ? Math.round(st.attributes.brightness / 2.55) : st.attributes.percentage != null ? st.attributes.percentage : st.attributes.current_position) : null;
      if (v == null || now == null || Math.abs(now - v) <= 2 || (v <= 1 && st.state === 'off') || Date.now() - start > 5000) { done(); return; }
      setTimeout(check, 250);
    };
    setTimeout(check, 300);
  }

  // A press on a card counts as using it: it resets the card's decay, and
  // a habit's prediction that was used gets its full weight back.
  noteUse(id) {
    this.touched[id] = Date.now();
    delete this._pred[id];
    const day = new Date().toDateString();
    const days = (this.used[id] || []).filter((d) => d !== day);
    days.push(day);
    this.used[id] = days.slice(-7);
    try { localStorage.setItem('morph.used', JSON.stringify(this.used)); } catch (e) { /* storage refused: no anchors on this device */ }
    const x = this.salNow(id);
    if (x.inp && x.inp.h > 0 && x.eid && this.admin()) this.hass.callWS({ type: 'morph/request', kind: 'habit', payload: { entity: x.eid, used: true } }).catch(() => {});
  }

  tapCard(id) {
    const hit = this.findCard(id); if (!hit) return;
    const T = typeOf(hit.card);
    const ctx = { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null };
    const tap = T.tap(ctx);
    if (tap) {
      if (tap.confirm) {
        const c = this.s.confirm[id];
        if (!c || c.until < Date.now()) { this.s.confirm[id] = { until: Date.now() + 3000, text: tap.confirm }; this.schedule(); setTimeout(() => this.schedule(), 3100); return; }
        delete this.s.confirm[id];
      }
      this.call(tap);
      this.track('toggle', id, hit.sec.id);
      this.noteUse(id);
    } else if (!T.noOpen) {
      if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'adv');
    }
  }

  cancelPtr() {
    if (this.upcD) { const d = this.upcD; this.upcD = null; if (this._upc) this.upcGo(this._upc, d.c); return; }
    clearTimeout(this.holdT); this.holdEnd(); if (this.ptr && this.ptr.drag) return; this.ptr = null; if (this.s.hold) { this.s.hold = null; this.schedule(); } }

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
    if (el.dataset.act === 'field') { this.pickColor(el, e); return; }
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
  }

  call(c) {
    if (!c) return;
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
      case 'room': this.unfoldRoom(v, true); return;
      case 'room-toggle': {
        const sec = this.sectionById(v); if (!sec) return;
        const st = this.roomState(sec);
        if (st === 'idle' || st === 'asleep') this.unfoldRoom(v, false);
        else { this.s.unfold[v] = 0; this.foldNow = v; this._forceApply = true; this.engine.invalidate(); this.schedule(); }
        return;
      }
      case 'case': {
        const r = await this.caseRequest(el.dataset.case, v, '');
        this.toast(r && r.ok ? ({ dismiss: 'Dismissed.', todo: 'Added to To Do.', snooze: 'Snoozed.', not_applicable: 'Closed.', fix: `${this.who()} is working out a plan.`, apply: `${this.who()} is making the change.` }[v] || `Told ${this.who()}.`) : (r && r.error) || `${this.who()} did not take that.`);
        return;
      }
      case 'case-reply': {
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
      case 'todo': this.todoAct(v, el.dataset.id); return;
      case 'keep': this.mutate('Kept a card in Now', (d) => { const h = this.cardIn(d, v); if (!h) return false; h.c.pin = true; }); this.lesson(v, true); return;
      case 'unpin': this.mutate('Stopped keeping a card in Now', (d) => { const h = this.cardIn(d, v); if (!h) return false; delete h.c.pin; }); return;
      case 'not-this': {
        this.suppressed[v] = new Date().toDateString();
        try { localStorage.setItem('morph.notthis', JSON.stringify(this.suppressed)); } catch (e) { /* storage refused: for this visit only */ }
        const x = this.salNow(v);
        if (x.inp && x.inp.h > 0 && x.eid) H.callWS({ type: 'morph/request', kind: 'habit', payload: { entity: x.eid, used: false } }).catch(() => {});
        this.closeView(); this._salDirty = true; this._forceApply = true; this.schedule(); return;
      }
      case 'device': {
        try { localStorage.setItem('morph.device', v === 'family' ? 'family' : 'personal'); } catch (e) { /* storage refused */ }
        this._salDirty = true; this.schedule(); return;
      }
      case 'device-person': {
        try { if (v) localStorage.setItem('morph.person', v); else localStorage.removeItem('morph.person'); } catch (e) { /* storage refused */ }
        this._salDirty = true; this.schedule(); return;
      }
      case 'menu': this.dispatchEvent(new Event('hass-toggle-menu', { bubbles: true, composed: true })); return;
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
        const ta = this.shadowRoot.querySelector('textarea[data-keep="yaml"]');
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
          const k = 'btn:' + el.dataset.service + el.dataset.data;
          const c = this.s.confirm[k];
          if (!c || c.until < Date.now()) { this.s.confirm[k] = { until: Date.now() + 4000 }; el.textContent = el.dataset.confirm; return; }
          delete this.s.confirm[k];
        }
        let data = {}; try { data = JSON.parse(el.dataset.data || '{}'); } catch (e) { /* none */ }
        this.call({ domain: el.dataset.domain, service: el.dataset.service, data });
        { const at = this.tileOf(el); this.track('toggle', at.card, at.section, data.entity_id && String(data.entity_id)); }
        return;
      }
      case 'head-toggle': { const hit = this.findCard(el.dataset.card); this.call({ domain: 'homeassistant', service: 'toggle', data: { entity_id: v } }); this.track('toggle', el.dataset.card, hit && hit.sec.id); return; }
      case 'scene': this.call({ domain: 'scene', service: 'turn_on', data: { entity_id: v } }); this.track('scene', null, null, v); return;
      case 'tgt': {
        const tile = el.closest('[data-tile]'); const hit = tile && this.findCard(tile.getAttribute('data-tile')); if (!hit) return;
        const st = H.states[hit.card.entity]; if (!st) return;
        const step = st.attributes.target_temp_step || (String(H.config.unit_system.temperature).includes('F') ? 1 : 0.5);
        const cur = st.attributes.temperature != null ? st.attributes.temperature : st.attributes.target_temp_low;
        this.call({ domain: 'climate', service: 'set_temperature', data: { entity_id: hit.card.entity, temperature: Math.round((cur + step * Number(v)) * 10) / 10 } });
        this.track('slide', hit.card.id, hit.sec.id); return;
      }
      case 'member': {
        const tile = el.closest('[data-tile]'); const id = tile && tile.getAttribute('data-tile');
        if (!id) return;
        if (!(this.s.view && this.s.view.id === id)) this.openView(id, 'adv');
        this.s.view.member = v; this.s.view.H = { depth: 0 }; this.schedule(); return;
      }
      case 'h-open': if (this.s.view) { this.s.view.H = { depth: 1, day: null }; this.track('history', this.s.view.id); this.schedule(); } return;
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
      case 'ask-sug': {
        const inp = this.shadowRoot.querySelector('input[data-keep="ask"]');
        if (inp) inp.value = v;
        this.act('ask', inp || { value: v, dataset: {} }); return;
      }
      case 'ask': this.ask(el.value || ''); if (el.value != null && el.tagName === 'INPUT') el.value = ''; return;
      // tell
      case 'tell-sug': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); if (ta) { ta.value = v; this.s.tell.draft = v; ta.focus(); } return; }
      case 'tell-send': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); this.sendTell(ta ? ta.value : ''); return; }
      case 'tell-cancel': this.closeTell(); return;
      case 'tell-refresh': this.dash = null; this.load(); return;
      case 'ask-tell': { const a = this.s.asks.find((x) => x.key === v); if (a) { this.askDrop(a); this.tellDashboard(a.q); } return; }
      case 'tell-keep': this.closeTell(); this.load(); return;
      case 'reload-page': location.reload(); return;
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
      case 'sec-hue': this.mutate('Changed a section’s colour', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.color = el.dataset.h; }); return;
      case 'sec-width': this.mutate('Changed a section’s width', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.width = Number(el.dataset.w); }); return;
      case 'sec-floor': this.mutate('Moved a section to another floor', (d) => { const h = this.sectionIn(d, v); const f = d.floors.find((x) => x.id === el.dataset.f); if (!h || !f || h.f === f) return false; h.f.sections.splice(h.i, 1); f.sections.push(h.s); }); return;
      case 'sec-floor-new': this.mutate('Added a floor', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.f.sections.splice(h.i, 1); d.floors.push({ title: 'New floor', sections: [h.s] }); }); return;
      case 'sec-group': this.mutate('Added a group', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.s.groups = h.s.groups || []; h.s.groups.push({ label: 'New group', cards: [] }); }); return;
      case 'sec-hide': this.mutate('Hid or showed a section', (d) => { const h = this.sectionIn(d, v); if (!h) return false; if (h.s.hidden) delete h.s.hidden; else h.s.hidden = true; }); return;
      case 'sec-remove': this.s.secEdit = null; this.mutate('Removed a section', (d) => { const h = this.sectionIn(d, v); if (!h) return false; h.f.sections.splice(h.i, 1); }); return;
      case 'add-section': this.mutate('Added a section', (d) => { const f = d.floors.find((x) => x.id === v); if (!f) return false; f.sections.push({ title: 'New section', color: HUES[(f.sections.length + 3) % HUES.length], width: 2, groups: [{ cards: [] }] }); }); return;
      case 'card-name': this.mutate('Renamed a card', (d) => { const h = this.cardIn(d, v); if (!h) return false; if (el.value.trim()) h.c.name = el.value.trim(); else delete h.c.name; }); return;
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
    if (!id.startsWith('k:')) {
      const hit = this.findCard(id);
      if (hit) { const st = this.roomState(hit.sec); if (st === 'idle' || st === 'asleep') this.unfoldRoom(hit.sec.id, false); }
    }
    this.engine.invalidate(); this.schedule();
    setTimeout(() => { const el = this.$(`[data-tile="${CSS.escape(id)}"]`); if (el) this.engine.scrollToEl(el, 200); }, 120);
  }

  unfoldRoom(secId, scroll) {
    this.s.unfold[secId] = Date.now() + UNFOLD_MS;
    this._forceApply = true; this.engine.invalidate(); this.schedule();
    clearTimeout(this._unfoldT); this._unfoldT = setTimeout(() => this.schedule(), UNFOLD_MS + 500);
    if (scroll) setTimeout(() => { const el = this.$(`[data-sec="${CSS.escape(secId)}"]`); if (el) this.engine.scrollToEl(el, 90); }, 80);
  }

  // An answer to one of brAIn's cases, through brAIn's own request queue.
  async caseRequest(cid, action, text) {
    try { return await this.hass.callWS({ type: 'morph/case', case: cid, action, text: text || '' }); } catch (e) { return { ok: false, error: String((e && e.message) || e) }; }
  }

  todoDone(id) {
    this.s.pending['todo:' + id] = Date.now();
    this.todoAct('done', id);
  }

  async todoAct(action, id) {
    let r;
    const payload = { action, id: Number(id) };
    if (action === 'snooze') payload.days = 7;
    try { r = await this.hass.callWS({ type: 'morph/todo', ...payload }); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
    this.s.todoOpen = null;
    this.toast(r && r.ok ? ({ done: 'Ticked off.', snooze: 'Snoozed a week.', drop: 'Deleted.' }[action] || 'Done.') : (r && r.error) || 'brAIn did not take that.');
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

  // The household's name for the assistant, which is how Morph's own words
  // name it (#452): brAIn's switches carry it (`features.name`, "brAIn"
  // while Personality is off), and brAIn's personality (morph/personality,
  // read once) stands in for an integration that does not send it.
  who() {
    const f = this.data && this.data.features;
    if (f && typeof f.name === 'string' && f.name.trim()) return f.name.trim();
    const p = this.s.persona && this.s.persona.personality;
    const n = p && typeof p.name === 'string' ? p.name.trim() : '';
    return n || 'brAIn';
  }

  // With Personality on, nothing on the page says "brAIn": the product's
  // name, in exactly that spelling, is the household's name for it. Never
  // inside a box somebody types in (a textarea's text is what they save),
  // and `brain` in lower case is a path or a command and is left alone.
  speak(html) {
    const name = this.who();
    if (!html || name === 'brAIn' || html.indexOf('brAIn') < 0) return html;
    const safe = esc(name);
    return html.split(/(<textarea[\s\S]*?<\/textarea>)/).map((part, i) => (i % 2 ? part : part.replace(/\bbrAIn\b/g, safe))).join('');
  }

  // Ask brAIn's shell to show brAIn's own page: a view, or a Settings
  // section. Outside the shell (a test page) there is nothing to open.
  openBrain(view, sec) {
    this.dispatchEvent(new CustomEvent('brain-open', { bubbles: true, composed: true, detail: { view: view || 'insights', sec: sec || '' } }));
  }

  async loadPersona() {
    try { this.s.persona = await this.hass.callWS({ type: 'morph/personality' }); } catch (e) { this.s.persona = { brain: null, personality: null }; }
    this.schedule();
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
