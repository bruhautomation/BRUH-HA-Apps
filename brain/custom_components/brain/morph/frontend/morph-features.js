// Morph's own features, as things a Home Assistant dashboard opts into
// (docs/design/morph-on-lovelace.md §2.5). Each is separate, so each is a
// switch:
//
//   custom:morph-view         a view type beside Masonry, Sections, Panel and
//                             Sidebar: HA's own sections, with a room that
//                             needs you lifted to the top, quiet rooms
//                             folded to one line, and the room rail on a
//                             touch screen. `morph: {order, fold, rail}` on
//                             the view turns each off.
//   custom:morph-cases-card   brAIn's cases (its one list), all of them or
//                             one room's, with the reply line and presses.
//   custom:morph-ask-card     Ask: brAIn's interpreter reads the words; a
//                             change to the dashboard becomes a Tell on the
//                             dashboard it was asked on.

import { CSS as STYLES, FIELD_FLOOR } from './styles.js';
import { HA_THEME } from './morph-cards.js';
import { caseFace, placeCase } from './cases.js';
import { Rail } from './rail.js';
import { findPanel, urlPathOf } from './brain-layer.js';
import { setHouseName, houseName, speakText } from './util.js';

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const HUE = ['sky', 'amber', 'teal', 'violet', 'lime', 'peach', 'sand', 'indigo', 'rose'];

let SHEET = null;
function sheet(extra) {
  const css = STYLES + HA_THEME + FIELD_FLOOR + extra;
  try { const s = new CSSStyleSheet(); s.replaceSync(css); return s; } catch (e) { return css; }
}
function adopt(root, extra) {
  if (!SHEET) SHEET = new Map();
  if (!SHEET.has(extra)) SHEET.set(extra, sheet(extra));
  const s = SHEET.get(extra);
  if (typeof s === 'string') root.innerHTML = `<style>${s}</style>`; else root.adoptedStyleSheets = [s];
}

// ---------------------------------------------------------------- rooms

const ON = ['on', 'open', 'opening', 'unlocked', 'unlocking', 'playing', 'heating', 'cooling', 'cleaning', 'home'];
// What needs somebody: an open door or window, an unlocked lock, a leak,
// smoke, gas, an alarm going off.
const NEEDS = { door: 'open', window: 'open', garage_door: 'open', opening: 'open', moisture: 'wet', smoke: 'smoke', gas: 'gas', carbon_monoxide: 'CO', safety: 'unsafe' };

export function entitiesOf(node, out = new Set()) {
  if (Array.isArray(node)) node.forEach((x) => entitiesOf(x, out));
  else if (node && typeof node === 'object') {
    Object.keys(node).forEach((k) => {
      const v = node[k];
      if ((k === 'entity' || k === 'entity_id') && typeof v === 'string' && v.includes('.')) out.add(v);
      else if (k === 'entities' && Array.isArray(v)) v.forEach((e) => { if (typeof e === 'string') out.add(e); else entitiesOf(e, out); });
      else entitiesOf(v, out);
    });
  }
  return out;
}

export function roomName(cfg, i) {
  const h = ((cfg && cfg.cards) || []).find((c) => c && c.type === 'heading' && c.heading);
  return (h && h.heading) || (cfg && cfg.title) || `Section ${i + 1}`;
}

const friendly = (st, e) => (st && st.attributes && st.attributes.friendly_name) || e.split('.').pop().replace(/_/g, ' ');

// One room's reading: what needs somebody (with the sentence that says so),
// what is on, and whether anything changed in the last quarter hour.
export function readRoom(cfg, i, states, now) {
  const ents = [...entitiesOf(cfg)];
  const needs = []; let on = 0; let recent = false;
  ents.forEach((e) => {
    const st = states[e]; if (!st) return;
    const d = e.split('.')[0];
    const dc = st.attributes && st.attributes.device_class;
    if (d === 'lock' && st.state === 'unlocked') needs.push(`${friendly(st, e)} is unlocked`);
    else if (d === 'binary_sensor' && st.state === 'on' && NEEDS[dc]) needs.push(`${friendly(st, e)}: ${NEEDS[dc]}`);
    else if (d === 'cover' && dc === 'garage' && st.state === 'open') needs.push(`${friendly(st, e)} is open`);
    else if (d === 'alarm_control_panel' && st.state === 'triggered') needs.push(`${friendly(st, e)} is going off`);
    if (['light', 'switch', 'fan', 'media_player', 'climate', 'vacuum', 'input_boolean', 'cover'].includes(d) && ON.includes(st.state)) on += 1;
    if (now - Date.parse(st.last_changed || 0) < 15 * 60000) recent = true;
  });
  return { i, name: roomName(cfg, i), needs, on, recent, count: ents.length };
}

// The order and folds: rooms that need somebody first (in their own order),
// then the rest as the dashboard has them; a room with nothing on and
// nothing recent folds. Pure, so it is tested under node.
export function plan(sections, states, opts, now = Date.now()) {
  const o = { order: true, fold: true, ...(opts || {}) };
  const rooms = (sections || []).map((cfg, i) => readRoom(cfg, i, states || {}, now));
  const lifted = o.order ? rooms.filter((r) => r.needs.length) : [];
  const rest = rooms.filter((r) => !lifted.includes(r));
  return [...lifted, ...rest].map((r) => ({ ...r, lifted: lifted.includes(r), fold: o.fold && !r.needs.length && !r.on && !r.recent && r.count > 0 }));
}

const VIEW_CSS = `
:host{display:block}
.morph.mv{background:transparent;min-height:0;font-family:var(--ha-font-family-body,inherit)}
.mv .scroll{display:flex;align-items:flex-start}
.mv .wrap{padding:8px clamp(8px,2vw,16px) 64px;max-width:none;gap:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,var(--mv-col,340px)),1fr));align-items:start;column-gap:16px;row-gap:16px}
.mv section.sec{position:relative;border-radius:var(--ha-card-border-radius,12px);overflow:hidden;--rc:var(--sky)}
.mv section.sec .secbg{position:absolute;inset:0;pointer-events:none;border-radius:inherit}
.mv section.sec .sechead{height:0;overflow:hidden}
.mv section.sec.lifted{box-shadow:inset 3px 0 0 var(--rose)}
.mv .why{margin:4px 8px 2px 14px;font-size:14px;font-weight:600;color:var(--rose)}
.mv .fold{display:flex;align-items:center;gap:10px;width:100%;min-height:48px;padding:0 14px;border:0;border-radius:var(--ha-card-border-radius,12px);background:var(--surface);color:var(--text);font:inherit;font-size:15px;cursor:pointer;text-align:left;box-shadow:var(--ha-card-box-shadow,none)}
.mv .fold b{font-weight:600}
.mv .fold span{color:var(--muted);font-size:14px}
`;

export class MorphView extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    adopt(this.shadowRoot, VIEW_CSS);
    this.rootEl = document.createElement('div');
    this.rootEl.className = 'morph mv t-ha';
    this.rootEl.innerHTML = '<div class="scroll"><div class="wrap" data-board></div><div class="srail"></div></div>';
    this.shadowRoot.appendChild(this.rootEl);
    this.board = this.rootEl.querySelector('[data-board]');
    this.open = new Set();
    this.applied = null;
    this.lastMove = 0;
    this.lastTouch = 0;
    this.railJumps = 0;
    this.rootEl.addEventListener('pointerdown', () => { this.lastTouch = Date.now(); });
    this.rootEl.addEventListener('click', (e) => {
      const b = e.target.closest && e.target.closest('[data-unfold]');
      if (b) { this.open.add(Number(b.dataset.unfold)); this.draw(true); }
    });
    // The rail's host: its model, the page's scrolling, a room's colour.
    const self = this;
    this.engine = {
      sc: null,
      get model() { return { sections: (self.applied || []).filter((r) => !self.folded(r)).map((r) => ({ id: 's' + r.i, floorId: '' })) }; },
      scroller() { return self.scroller(); },
      scrollY() { return self.scroller().scrollTop; },
      scrollTo(y) { self.scroller().scrollTop = y; },
      reduce() { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); },
    };
  }

  setConfig(config) { this._config = config || {}; this.draw(true); }

  set hass(h) { this._hass = h; this.draw(false); }

  get hass() { return this._hass; }

  set sections(list) { this._sections = list || []; this.draw(true); }

  set cards(list) { this._cards = list || []; this.draw(true); }

  set lovelace(l) { this._lovelace = l; this.draw(true); }

  set badges(b) { this._badges = b; }

  get opts() { return { order: true, fold: true, rail: true, ...((this._config && this._config.morph) || {}) }; }

  folded(r) { return r.fold && !this.open.has(r.i); }

  // What scrolls this view: the nearest scrolling ancestor through shadow
  // roots, else the window (HA has used both), as the one shape the rail
  // reads.
  scroller() {
    if (this._sc) return this._sc;
    let n = this.parentNode || this.getRootNode().host;
    while (n && n !== document.documentElement) {
      if (n.nodeType === 1) {
        const oy = getComputedStyle(n).overflowY;
        if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight + 1) { this._sc = n; break; }
      }
      n = n.parentNode || (n.getRootNode && n.getRootNode().host);
    }
    if (!this._sc) {
      this._sc = {
        isConnected: true,
        getBoundingClientRect: () => ({ top: 0, left: 0, width: innerWidth, height: innerHeight, bottom: innerHeight, right: innerWidth }),
        get scrollTop() { return window.scrollY; },
        set scrollTop(v) { window.scrollTo(0, v); },
        get scrollHeight() { return document.documentElement.scrollHeight; },
        get clientHeight() { return innerHeight; },
        addEventListener: (n2, f, o) => window.addEventListener(n2, f, o),
      };
    }
    if (!this._scHeard) { this._scHeard = true; this._sc.addEventListener('scroll', () => this.paintRail(), { passive: true }); }
    return this._sc;
  }

  paintRail() {
    if (!this.rail || this._railF) return;
    this._railF = requestAnimationFrame(() => { this._railF = 0; try { this.rail.paint(); } catch (e) { /* no rail */ } });
  }

  railColor(id) { return `var(--${HUE[Number(String(id).slice(1)) % HUE.length]})`; }

  railFloor() { return ''; }

  // A new order is taken only at a quiet moment (Morph's rule): not under a
  // finger, not seconds after the last change, unless a room newly needs
  // somebody.
  draw(force) {
    if (!this._hass || !this._config) return;
    const cfgs = (this._config.sections || []);
    const editing = !!(this._lovelace && this._lovelace.editMode);
    const next = plan(cfgs, this._hass.states, editing ? { order: false, fold: false } : this.opts);
    const sig = (p) => p.map((r) => `${r.i}${r.fold ? 'f' : ''}${r.lifted ? 'l' : ''}`).join(',');
    const urgent = next.some((r) => r.lifted && !(this.applied || []).some((a) => a.i === r.i && a.lifted));
    const quiet = Date.now() - this.lastTouch > 1200 && Date.now() - this.lastMove > 8000;
    if (!this.applied || force || urgent || (quiet && sig(next) !== sig(this.applied))) {
      if (this.applied && sig(next) !== sig(this.applied)) this.lastMove = Date.now();
      this.applied = next;
    } else {
      // Same order; the words (why a room is lifted, what is on) are fresh.
      this.applied = this.applied.map((a) => ({ ...next.find((r) => r.i === a.i), lifted: a.lifted, fold: a.fold }));
    }
    this.layout();
  }

  layout() {
    const els = this._sections || [];
    const want = [];
    (this.applied || []).forEach((r) => {
      const id = 's' + r.i;
      let sec = this.board.querySelector(`section[data-sec="${id}"]`);
      if (!sec) {
        sec = document.createElement('section');
        sec.className = 'sec';
        sec.setAttribute('data-sec', id);
        sec.innerHTML = '<div class="secbg"></div><div class="sechead"><h2></h2></div><p class="why" hidden></p><div class="body"></div><button type="button" class="fold" hidden></button>';
      }
      sec.style.setProperty('--rc', this.railColor(id));
      sec.querySelector('h2').textContent = r.name;
      sec.classList.toggle('lifted', !!r.lifted);
      const why = sec.querySelector('.why');
      why.hidden = !(r.lifted && r.needs.length);
      why.textContent = r.needs.slice(0, 2).join(' · ');
      const fold = sec.querySelector('.fold');
      const body = sec.querySelector('.body');
      const folded = this.folded(r);
      fold.hidden = !folded;
      body.hidden = folded;
      if (folded) {
        fold.dataset.unfold = String(r.i);
        fold.innerHTML = `<b>${esc(r.name)}</b><span>${r.count} thing${r.count === 1 ? '' : 's'}, nothing on</span>`;
      }
      const el = els[r.i];
      if (el && el.parentNode !== body) body.appendChild(el);
      if (el && this._hass) el.hass = this._hass;
      want.push(sec);
    });
    // In order, moving only what moved.
    want.forEach((sec, k) => { if (this.board.children[k] !== sec) this.board.insertBefore(sec, this.board.children[k] || null); });
    [...this.board.children].forEach((c) => { if (!want.includes(c)) c.remove(); });
    const railEl = this.rootEl.querySelector('.srail');
    if (this.opts.rail && !this.rail) this.rail = new Rail(railEl, this);
    railEl.hidden = !this.opts.rail;
    if (this.rail) this.paintRail();
  }
}

// --------------------------------------------------------- brAIn's cases

const CASES_CSS = `
:host{display:block}
.morph.mx{background:transparent;min-height:0;font-family:var(--ha-font-family-body,inherit);padding:4px 0}
.mx .case{padding:12px 16px;border-top:1px solid var(--line)}
.mx .case:first-child{border-top:0}
.mx .note{padding:14px 16px;color:var(--muted);font-size:14px}
.mx h2{font-size:16px;font-weight:600;margin:10px 16px 2px}
`;

async function connection() {
  for (let i = 0; i < 300; i++) {
    const root = document.querySelector('home-assistant');
    if (root && root.hass && root.hass.connection) return root.hass.connection;
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
}

// One shared read of brAIn's published files for every case card on the
// page, refreshed when the integration says brAIn's files moved.
const FEED = { data: null, cards: new Set(), started: false };
async function startFeed(hass) {
  if (FEED.started) return;
  FEED.started = true;
  const load = async () => {
    try { FEED.data = await hass.callWS({ type: 'morph/load' }); } catch (e) { FEED.data = FEED.data || { error: String((e && e.message) || e) }; }
    setHouseName(FEED.data);
    FEED.cards.forEach((c) => c.render());
  };
  await load();
  const conn = await connection();
  if (conn) { try { await conn.subscribeMessage((ev) => { if ((ev.parts || []).includes('brain')) load(); }, { type: 'morph/subscribe' }); } catch (e) { /* loaded once */ } }
}

export class MorphCasesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    adopt(this.shadowRoot, CASES_CSS);
    this.card = document.createElement('ha-card');
    this.body = document.createElement('div');
    this.body.className = 'morph mx t-ha';
    this.card.appendChild(this.body);
    this.shadowRoot.appendChild(this.card);
    this.pending = {};
    this.body.addEventListener('click', (e) => this.press(e));
    this.body.addEventListener('keydown', (e) => {
      const el = e.target;
      if (e.key === 'Enter' && el.dataset && el.dataset.actEnter === 'case-reply') { e.preventDefault(); this.send(el.dataset.case, 'reply', el.value); }
    });
  }

  static getConfigForm() {
    return { schema: [{ name: 'title', selector: { text: {} } }, { name: 'area', selector: { area: {} } }, { name: 'entities', selector: { entity: { multiple: true } } }],
      computeLabel: (s) => ({ title: 'Title', area: 'Only cases about this area', entities: 'Or only cases about these' }[s.name]),
      computeHelper: (s) => (s.name === 'area' ? speakText('Leave both empty for every case brAIn has.') : undefined) };
  }

  static getStubConfig() { return { title: 'brAIn' }; }

  setConfig(c) { this._config = { ...(c || {}) }; this.render(); }

  set hass(h) { const first = !this._hass; this._hass = h; if (first) { FEED.cards.add(this); startFeed(h); this.render(); } }

  connectedCallback() { FEED.cards.add(this); }

  disconnectedCallback() { FEED.cards.delete(this); }

  getCardSize() { return 3; }

  getGridOptions() { return { columns: 12, rows: 'auto' }; }

  cases() {
    const all = ((FEED.data && FEED.data.brain && FEED.data.brain.cases) || []).filter((c) => c && c.id);
    const c = this._config || {};
    const ents = new Set([].concat(c.entities || []).map((e) => (typeof e === 'string' ? e : e && e.entity)).filter(Boolean));
    if (!c.area && !ents.size) return all;
    const states = (this._hass && this._hass.states) || {};
    const reg = (this._hass && this._hass.entities) || {};
    const areaOf = (e) => (reg[e] && reg[e].area_id) || '';
    return all.filter((k) => placeCase(k, (eid, area) => {
      if (eid && ents.has(eid)) return 'here';
      if (eid && c.area && areaOf(eid) === c.area && states[eid]) return 'here';
      if (area && c.area && area === c.area) return 'here';
      return null;
    }) === 'here');
  }

  render() {
    if (!this._config) return;
    const who = houseName();
    const admin = !!(this._hass && this._hass.user && this._hass.user.is_admin);
    const name = (eid) => { const st = this._hass && this._hass.states[eid]; return st && st.attributes.friendly_name; };
    const list = this.cases();
    const title = this._config.title ? `<h2>${esc(this._config.title)}</h2>` : '';
    let inner;
    if (!FEED.data) inner = `<p class="note">Reading ${esc(who)}'s cases…</p>`;
    else if (FEED.data.error) inner = `<p class="note">${esc(who)}'s cases could not be read: ${esc(FEED.data.error)}</p>`;
    else if (!list.length) { this.style.display = 'none'; return; } else inner = list.map((c) => caseFace(c, { admin, who, name, pending: this.pending[c.id] || '' })).join('');
    this.style.display = '';
    const keep = {};
    this.body.querySelectorAll('input.replyin').forEach((i) => { keep[i.dataset.case] = i.value; });
    this.body.innerHTML = title + inner;
    this.body.querySelectorAll('input.replyin').forEach((i) => { if (keep[i.dataset.case]) i.value = keep[i.dataset.case]; });
  }

  press(e) {
    const b = e.target.closest && e.target.closest('[data-act="case"]');
    if (b) this.send(b.dataset.case, b.dataset.v, '');
  }

  async send(id, action, text) {
    this.pending[id] = speakText('Sent. brAIn answers here.');
    this.render();
    let r;
    try { r = await this._hass.callWS({ type: 'morph/case', case: id, action, text: text || '' }); } catch (err) { r = { ok: false, error: String((err && err.message) || err) }; }
    this.pending[id] = r.ok ? this.pending[id] : r.error;
    this.render();
  }
}

// ------------------------------------------------------------------ Ask

const ASK_CSS = `
:host{display:block}
.morph.ma{background:transparent;min-height:0;font-family:var(--ha-font-family-body,inherit);padding:12px 16px}
.ma form{display:flex;gap:8px}
.ma input{flex:1;min-width:0;font:inherit;font-size:16px;min-height:44px;padding:0 12px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--text)}
.ma button{font:inherit;min-height:44px;padding:0 16px;border-radius:10px;border:0;background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);cursor:pointer}
.ma .ans{margin:10px 2px 0;font-size:15px}
.ma .ans.quiet{color:var(--muted);font-size:14px}
`;

export class MorphAskCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    adopt(this.shadowRoot, ASK_CSS);
    const card = document.createElement('ha-card');
    this.body = document.createElement('div');
    this.body.className = 'morph ma t-ha';
    this.body.innerHTML = '<form><input type="text" aria-label="Ask or tell the house" autocomplete="off"><button type="submit">Ask</button></form><p class="ans quiet" aria-live="polite"></p>';
    card.appendChild(this.body);
    this.shadowRoot.appendChild(card);
    this.body.querySelector('form').addEventListener('submit', (e) => { e.preventDefault(); this.ask(); });
  }

  static getConfigForm() { return { schema: [{ name: 'placeholder', selector: { text: {} } }], computeLabel: () => 'What the empty line says' }; }

  static getStubConfig() { return { placeholder: 'Ask or tell the house…' }; }

  setConfig(c) {
    this._config = { ...(c || {}) };
    this.body.querySelector('input').placeholder = this._config.placeholder || 'Ask or tell the house…';
  }

  // The box's label names the assistant the way the household does.
  render() { this.body.querySelector('input').setAttribute('aria-label', speakText('Ask or tell brAIn')); }

  connectedCallback() { FEED.cards.add(this); this.render(); }

  disconnectedCallback() { FEED.cards.delete(this); }

  set hass(h) { const first = !this._hass; this._hass = h; if (first) startFeed(h); }

  getCardSize() { return 2; }

  getGridOptions() { return { columns: 12, rows: 'auto' }; }

  say(text, quiet) { const p = this.body.querySelector('.ans'); p.textContent = text; p.classList.toggle('quiet', !!quiet); }

  // Which dashboard this card is on, and whether brAIn keeps it: a change
  // asked for here is a Tell on this dashboard.
  async dashboard() {
    const url = urlPathOf(findPanel() || {});
    try {
      const r = await this._hass.callWS({ type: 'morph/dashboards' });
      return (r.dashboards || []).find((d) => d.url_path === url && d.morphed) || null;
    } catch (e) { return null; }
  }

  async ask() {
    const input = this.body.querySelector('input');
    const text = input.value.trim();
    if (!text || !this._hass) return;
    input.value = '';
    this.say('Asking…', true);
    let r;
    try { r = await this._hass.callWS({ type: 'morph/ask', text }); } catch (e) { r = { do: 'fallback' }; }
    if (r.do === 'done') { this.say(r.say || 'Done.'); return; }
    if (r.do === 'tell_dashboard' || r.do === 'tell_code') {
      const d = await this.dashboard();
      if (!d) { this.say(speakText('That is a change to a dashboard: open the brAIn button on a dashboard brAIn keeps and tell it there.'), true); return; }
      const out = await this._hass.callWS({ type: 'morph/request', kind: 'tell', payload: { target: { kind: 'lovelace', dashboard: d.key, at: '[]', label: 'the dashboard', path: d.title }, text: r.tell_text || text } });
      if (!out.ok) { this.say(speakText(out.error || 'brAIn could not take that.'), true); return; }
      this.follow(out.id);
      return;
    }
    if (r.do === 'conversation') {
      const out = await this._hass.callWS({ type: 'morph/request', kind: 'converse', payload: { text } });
      if (!out.ok && out.error) { this.say(out.error, true); return; }
      this.follow(out.id);
      return;
    }
    // brAIn could not read it: the house's own conversation agent answers.
    try {
      const a = await this._hass.callWS({ type: 'conversation/process', text });
      const sp = a && a.response && a.response.speech && a.response.speech.plain;
      this.say((sp && sp.speech) || 'No answer.');
    } catch (e) { this.say('No answer.', true); }
  }

  async follow(id) {
    for (let i = 0; i < 900 && id; i++) {
      let st = null;
      try { st = await this._hass.callWS({ type: 'morph/tell_status', tell: id }); } catch (e) { /* asked again */ }
      if (st && (st.phase === 'done' || st.phase === 'failed')) { this.say(st.say || 'Done.'); return; }
      const steps = (st && st.steps) || [];
      this.say(speakText(steps.length ? steps[steps.length - 1].t : 'brAIn is on it…'), true);
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
}

export function register(win = globalThis) {
  const reg = win.customElements;
  if (!reg.get('morph-view')) reg.define('morph-view', MorphView);
  if (!reg.get('morph-cases-card')) reg.define('morph-cases-card', MorphCasesCard);
  if (!reg.get('morph-ask-card')) reg.define('morph-ask-card', MorphAskCard);
  win.customCards = win.customCards || [];
  const add = (row) => { if (!win.customCards.some((c) => c && c.type === row.type)) win.customCards.push(row); };
  add({ type: 'morph-cases-card', name: 'Morph · brAIn’s cases', description: 'What brAIn wants you to know or decide, with a reply line: every case, or one room’s.', preview: false });
  add({ type: 'morph-ask-card', name: 'Morph · Ask', description: 'Ask or tell the house. A change to this dashboard becomes a Tell, made here.', preview: true });
}

if (typeof window !== 'undefined' && window.customElements) register(window);
