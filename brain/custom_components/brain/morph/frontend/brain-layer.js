// The brAIn layer on Home Assistant's own dashboards
// (docs/design/morph-on-lovelace.md §2.2).
//
// Home Assistant draws the dashboard; this only adds. For an administrator,
// on a storage-mode dashboard, a brAIn button sits at the bottom right:
//
//   - not kept yet: "Let brAIn change this dashboard" (morph/dashboard_morph);
//   - kept: Tell brAIn about a card (tap the card: its YAML path is found in
//     the dashboard's own config, its picture taken), about the whole
//     dashboard, the dashboard's history with Restore, and stop keeping it.
//
// A Tell is Morph's Tell (morph/request kind tell, target kind "lovelace"):
// brAIn edits /config/morph/dashboards/<key>.yaml, Morph saves it to Home
// Assistant, and HA redraws the dashboard on every open screen. Keep and
// Undo are the Tell's own. Everything this reaches inside Home Assistant's
// page goes through `find*` helpers that answer null rather than throw: a
// release that moves an element turns one thing here off, never the page.

import * as snap from './snap.js';

const POLL_MS = 1000;
const LIST_TTL = 8000;

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const MARK = '<svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M4 5.2A1.2 1.2 0 0 1 5.2 4H18.8A1.2 1.2 0 0 1 20 5.2V12A8 8 0 0 1 12 20H5.2A1.2 1.2 0 0 1 4 18.8Z"/><circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></svg>';

// ------------------------------------------------- finding things in HA's page

// Breadth-first through open shadow roots, bounded, for the first element
// `test` accepts.
export function deepFind(start, test, limit = 4000) {
  const queue = [start];
  let n = 0;
  while (queue.length && n < limit) {
    const node = queue.shift(); n += 1;
    if (!node) continue;
    if (node !== start && node.nodeType === 1 && test(node)) return node;
    if (node.shadowRoot) queue.push(node.shadowRoot);
    const kids = node.children || [];
    for (let i = 0; i < kids.length; i++) queue.push(kids[i]);
  }
  return null;
}

export function findPanel(doc = document) {
  const root = doc.querySelector('home-assistant');
  if (!root) return null;
  return deepFind(root, (el) => el.localName === 'ha-panel-lovelace');
}

export function urlPathOf(panel) {
  try { return (panel.panel && panel.panel.url_path) || panel.urlPath || null; } catch (e) { return null; }
}

// Where a card's config sits in the dashboard's config: the list path
// (["views", 0, "sections", 1, "cards", 2]). Found by identity first —
// Home Assistant hands each card the very object from its config — and by
// equal JSON within `scope` when a release copies it.
export function findPath(root, target, scope) {
  const seen = new Set();
  const walk = (node, path) => {
    if (node === target) return path;
    if (!node || typeof node !== 'object' || seen.has(node)) return null;
    seen.add(node);
    const keys = Array.isArray(node) ? node.map((_, i) => i) : Object.keys(node);
    for (const k of keys) { const hit = walk(node[k], path.concat([k])); if (hit) return hit; }
    return null;
  };
  const byRef = walk(root, []);
  if (byRef) return byRef;
  const want = JSON.stringify(target);
  const base = scope || [];
  let start = root;
  for (const k of base) start = start && start[k];
  const walkEq = (node, path) => {
    if (node && typeof node === 'object' && JSON.stringify(node) === want) return path;
    if (!node || typeof node !== 'object') return null;
    const keys = Array.isArray(node) ? node.map((_, i) => i) : Object.keys(node);
    for (const k of keys) { const hit = walkEq(node[k], path.concat([k])); if (hit) return hit; }
    return null;
  };
  return walkEq(start, base);
}

// The card a press landed on: the innermost element holding a card config
// (hui-card in today's frontend; a card element with its config in older
// ones), with its config.
export function cardAt(path) {
  for (const el of path) {
    if (!el || el.nodeType !== 1) continue;
    const name = el.localName || '';
    if (name === 'hui-card' && el.config) return { el, config: el.config };
    if ((name.endsWith('-card') || name === 'hui-card') && !name.startsWith('ha-') && name !== 'ha-card') {
      const cfg = el.config || el._config;
      if (cfg && typeof cfg === 'object' && cfg.type) return { el, config: cfg };
    }
  }
  return null;
}

export function viewIndex(cfg, pathname) {
  const views = (cfg && cfg.views) || [];
  const seg = String(pathname || '').split('/').filter(Boolean)[1];
  if (seg == null) return 0;
  const byPath = views.findIndex((v) => v && v.path === seg);
  if (byPath >= 0) return byPath;
  const n = Number(seg);
  return Number.isInteger(n) && n >= 0 && n < views.length ? n : 0;
}

export function cardLabel(c) {
  if (!c || typeof c !== 'object') return 'card';
  let t = String(c.type || 'card');
  if (t.startsWith('custom:')) t = t.slice(7);
  const who = c.name || c.title || c.heading || c.entity;
  return who ? `${t} card (${who})` : `${t} card`;
}

// ------------------------------------------------------------- the layer

const CSS = `
:host{all:initial}
*{box-sizing:border-box}
.fab{position:fixed;right:20px;bottom:calc(20px + env(safe-area-inset-bottom,0px));z-index:7;width:52px;height:52px;border-radius:16px;border:0;cursor:pointer;display:flex;align-items:center;justify-content:center;
  background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.25))}
.fab:focus-visible{outline:2px solid var(--primary-text-color);outline-offset:2px}
.sheet{position:fixed;right:20px;bottom:calc(84px + env(safe-area-inset-bottom,0px));z-index:7;width:min(420px,calc(100vw - 32px));max-height:min(70vh,640px);overflow:auto;
  background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121);border-radius:var(--ha-card-border-radius,12px);
  box-shadow:0 8px 28px rgba(0,0,0,.28);font-family:var(--ha-font-family-body,Roboto,sans-serif);font-size:15px;line-height:1.45;padding:14px 16px 16px}
.sheet h2{font-size:16px;font-weight:600;margin:0 0 6px}
.sm{font-size:14px;color:var(--secondary-text-color,#727272);margin:0 0 8px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
button.b{font:inherit;font-size:15px;min-height:40px;padding:0 14px;border-radius:10px;border:1px solid var(--divider-color,rgba(0,0,0,.12));background:transparent;color:inherit;cursor:pointer}
button.b.go{background:var(--primary-color,#03a9f4);border-color:transparent;color:var(--text-primary-color,#fff)}
button.b[aria-pressed="true"]{border-color:var(--primary-color,#03a9f4);box-shadow:inset 0 0 0 1px var(--primary-color,#03a9f4)}
button.menu{display:block;width:100%;text-align:left;font:inherit;font-size:15px;min-height:44px;padding:8px 10px;border:0;border-radius:8px;background:transparent;color:inherit;cursor:pointer}
button.menu:hover{background:color-mix(in srgb,var(--primary-text-color,#000) 6%,transparent)}
textarea{width:100%;min-height:84px;font:inherit;font-size:16px;padding:10px;border-radius:10px;border:1px solid var(--divider-color,rgba(0,0,0,.2));background:var(--secondary-background-color,transparent);color:inherit;resize:vertical}
.shot{max-width:100%;max-height:160px;border-radius:8px;display:block;margin:6px 0;border:1px solid var(--divider-color,rgba(0,0,0,.12))}
.steps{margin:8px 0 0;padding:0;list-style:none;font-size:14px}
.steps li{padding:2px 0;color:var(--secondary-text-color)}
.steps li.good{color:var(--success-color,#2e7d32)} .steps li.bad{color:var(--error-color,#c62828)}
.say{margin:10px 0 0;font-size:15px}
.shows{margin:6px 0 0;padding-left:18px;font-size:14px}
.hist{margin:0;padding:0;list-style:none}
.hist li{display:flex;gap:8px;align-items:center;justify-content:space-between;padding:6px 0;border-top:1px solid var(--divider-color,rgba(0,0,0,.08));font-size:14px}
.hist li span{min-width:0}
.pick{position:fixed;left:50%;top:calc(12px + env(safe-area-inset-top,0px));transform:translateX(-50%);z-index:8;display:flex;gap:12px;align-items:center;padding:8px 8px 8px 16px;border-radius:12px;
  background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);font-family:var(--ha-font-family-body,Roboto,sans-serif);font-size:15px;box-shadow:0 4px 16px rgba(0,0,0,.25)}
.pick button{font:inherit;min-height:40px;padding:0 14px;border-radius:10px;border:0;background:rgba(255,255,255,.2);color:inherit;cursor:pointer}
.ring{position:fixed;z-index:6;pointer-events:none;border-radius:var(--ha-card-border-radius,12px);box-shadow:0 0 0 3px var(--primary-color,#03a9f4),0 0 0 9999px rgba(0,0,0,.18);transition:all .12s ease}
@media (prefers-reduced-motion:reduce){.ring{transition:none}}
`;

export class BrainLayer extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.s = { open: false, mode: 'menu', list: null, listAt: 0, row: null, tell: null, hist: null, err: '', picking: false };
    this._onPick = this.onPick.bind(this);
    this._onHover = this.onHover.bind(this);
    this._onKey = (e) => { if (e.key === 'Escape') { if (this.s.picking) this.stopPick(); else this.close(); } };
    this.shadowRoot.addEventListener('click', (e) => this.onClick(e));
    this.shadowRoot.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && e.target.localName === 'textarea') { e.preventDefault(); this.send(); }
    });
  }

  get hass() { const r = document.querySelector('home-assistant'); return r && r.hass; }

  // Called on every navigation: which dashboard this is, and whether brAIn
  // keeps it. Nothing is drawn off a dashboard, or for a non-administrator.
  async refresh() {
    const hass = this.hass;
    const panel = findPanel();
    this.panel = panel;
    if (!hass || !panel || !(hass.user && hass.user.is_admin)) { this.s.row = null; this.render(); return; }
    const url = urlPathOf(panel);
    if (!this.s.list || Date.now() - this.s.listAt > LIST_TTL) {
      try {
        const r = await hass.callWS({ type: 'morph/dashboards' });
        this.s.list = r.dashboards || []; this.s.listAt = Date.now();
      } catch (e) { this.s.list = []; this.s.listAt = Date.now(); }
    }
    this.s.row = this.s.list.find((d) => d.url_path === url) || null;
    if (this.s.hasMorph == null) {
      // Whether there is a Morph dashboard of the old kind to bring over.
      try {
        const m = await hass.callWS({ type: 'morph/load' });
        const d = m && m.mirror && m.mirror.dashboard;
        this.s.hasMorph = !!(d && (d.floors || []).some((f) => (f.sections || []).length));
      } catch (e) { this.s.hasMorph = false; }
    }
    this.render();
  }

  lovelace() { try { return this.panel && this.panel.lovelace; } catch (e) { return null; } }

  open(mode) { this.s.open = true; this.s.mode = mode || 'menu'; this.s.err = ''; this.render(); }

  close() { this.s.open = false; if (this.s.tell && this.s.tell.poll) clearTimeout(this.s.tell.poll); this.s.tell = null; this.render(); }

  async morphIt(on) {
    const r = await this.hass.callWS({ type: 'morph/dashboard_morph', key: this.s.row.key, on });
    if (!r.ok) { this.s.err = r.error; this.render(); return; }
    this.s.listAt = 0;
    await this.refresh();
    this.open('menu');
  }

  // Morph's own dashboard (dashboard.yaml) as a Home Assistant dashboard
  // of its own: the service writes the config (convert.py), Home
  // Assistant's own commands create and save it, and brAIn keeps it.
  async bringOver() {
    this.open('convert');
    this.s.conv = { phase: 'working' }; this.render();
    const hass = this.hass;
    const r = await hass.callWS({ type: 'morph/request', kind: 'convert', payload: {} });
    if (!r.ok) { this.s.conv = { phase: 'failed', error: r.error }; this.render(); return; }
    const exists = (this.s.list || []).some((d) => d.url_path === r.url_path);
    if (exists) { this.s.conv = { phase: 'failed', error: `There is already a dashboard at /${r.url_path}. Delete or rename it in Settings › Dashboards, then try again.` }; this.render(); return; }
    try {
      await hass.callWS({ type: 'lovelace/dashboards/create', url_path: r.url_path, title: r.title, icon: 'mdi:view-dashboard-variant', show_in_sidebar: true, require_admin: false, mode: 'storage' });
      await hass.callWS({ type: 'lovelace/config/save', url_path: r.url_path, config: r.config });
      await hass.callWS({ type: 'morph/dashboard_morph', key: r.url_path, on: true });
    } catch (e) { this.s.conv = { phase: 'failed', error: String((e && e.message) || e) }; this.render(); return; }
    this.s.listAt = 0;
    this.s.conv = { phase: 'done', report: r.report || [], url: '/' + r.url_path };
    this.render();
  }

  go(url) {
    history.pushState(null, '', url);
    window.dispatchEvent(new CustomEvent('location-changed', { detail: { replace: false } }));
    this.close();
  }

  // ---------------------------------------------------------- pick a card

  startPick() {
    this.s.open = false; this.s.picking = true; this.render();
    ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'contextmenu', 'touchstart', 'touchend'].forEach((n) => window.addEventListener(n, this._onPick, { capture: true, passive: false }));
    window.addEventListener('pointermove', this._onHover, { capture: true, passive: true });
    window.addEventListener('keydown', this._onKey, true);
  }

  stopPick() {
    this.s.picking = false;
    ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'contextmenu', 'touchstart', 'touchend'].forEach((n) => window.removeEventListener(n, this._onPick, { capture: true }));
    window.removeEventListener('pointermove', this._onHover, { capture: true });
    window.removeEventListener('keydown', this._onKey, true);
    this.ring(null);
    this.render();
  }

  inLayer(e) { return (e.composedPath ? e.composedPath() : []).includes(this); }

  onHover(e) {
    if (this.inLayer(e)) return;
    const hit = cardAt(e.composedPath ? e.composedPath() : []);
    this.ring(hit ? hit.el : null);
  }

  ring(el) {
    let r = this.shadowRoot.querySelector('.ring');
    if (!el) { if (r) r.remove(); return; }
    if (!r) { r = document.createElement('div'); r.className = 'ring'; this.shadowRoot.appendChild(r); }
    const b = el.getBoundingClientRect();
    Object.assign(r.style, { left: b.left + 'px', top: b.top + 'px', width: b.width + 'px', height: b.height + 'px' });
  }

  onPick(e) {
    if (this.inLayer(e)) return;
    // Nothing on the dashboard acts while a card is being picked.
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    if (e.type !== 'click') return;
    const hit = cardAt(e.composedPath ? e.composedPath() : []);
    if (!hit) return;
    this.stopPick();
    this.tellAbout(hit);
  }

  // ---------------------------------------------------------------- Tell

  tellAbout(hit) {
    const ll = this.lovelace();
    const cfg = ll && ll.config;
    const view = viewIndex(cfg, location.pathname);
    let at = hit ? findPath(cfg, hit.config, ['views', view]) : null;
    if (hit && !at) at = ['views', view];
    const card = hit ? hit.config : null;
    const typeSlug = card && typeof card.type === 'string' && card.type.startsWith('custom:morph-type-') ? card.type.slice(18) : '';
    const v = cfg && cfg.views && cfg.views[view];
    const where = hit ? `${(v && (v.title || v.path)) || 'This view'} › ${cardLabel(card)}` : 'The whole dashboard';
    this.s.tell = { at: hit ? at : [], label: hit ? `the ${cardLabel(card)}` : 'the dashboard', where, entity: (card && card.entity) || '', typeSlug, scope: 'one', shot: null, phase: 'compose', state: null };
    if (hit) this.shoot(hit.el);
    if (typeSlug) this.typeCount(typeSlug);
    this.open('tell');
    setTimeout(() => { const ta = this.shadowRoot.querySelector('textarea'); if (ta) ta.focus(); }, 50);
  }

  async typeCount(slug) {
    try {
      const r = await this.hass.callWS({ type: 'morph/types' });
      const t = (r.types || []).find((x) => x.slug === slug);
      if (this.s.tell && t) { this.s.tell.typeName = t.name; this.s.tell.copies = (t.used || []).length; this.render(); }
    } catch (e) { /* the choice is offered without the count */ }
  }

  shoot(el) {
    const t = this.s.tell;
    let job;
    try { job = snap.prepare(el, { background: getComputedStyle(document.body).backgroundColor }); } catch (e) { t.shot = { status: 'failed', error: String(e) }; return; }
    t.shot = { status: 'taking', view: job.view };
    job.render().then(async (r) => {
      if (!r.png) { t.shot = { status: 'failed', error: r.error, view: job.view }; this.render(); return; }
      t.shot = { status: 'uploading', url: snap.blobUrl(r.png), view: job.view };
      this.render();
      try {
        const res = await this.hass.callWS({ type: 'morph/shot', png: r.png });
        t.shot = { ...t.shot, status: 'ready', id: res.shot };
      } catch (e) { t.shot = { ...t.shot, status: 'failed', error: String((e && e.message) || e) }; }
      this.render();
    }).catch((e) => { t.shot = { status: 'failed', error: String(e) }; this.render(); });
  }

  async send() {
    const t = this.s.tell; if (!t) return;
    const ta = this.shadowRoot.querySelector('textarea');
    const text = ((ta && ta.value) || '').trim();
    if (!text) return;
    t.text = text; t.phase = 'sending'; this.render();
    const shot = t.shot && t.shot.status === 'ready' ? t.shot.id : '';
    const view = t.shot && t.shot.status !== 'ready' ? { ...(t.shot.view || {}), error: t.shot.error || '' } : undefined;
    const context = t.typeSlug ? (t.scope === 'type'
      ? `The person chose to change the card type “${t.typeSlug}” itself, so every copy of it changes${t.copies ? ` (${t.copies} copies)` : ''}.`
      : `The person chose to change only this copy of the card type “${t.typeSlug}”, not the type.`) : '';
    const target = { kind: 'lovelace', dashboard: this.s.row.key, at: JSON.stringify(t.at || []), label: t.label, path: t.where, entity: t.entity };
    try {
      const r = await this.hass.callWS({ type: 'morph/request', kind: 'tell', payload: { target, text, previous: t.previous || '', shot, view, context } });
      if (!r.ok) { t.phase = 'compose'; this.s.err = r.error || 'brAIn could not take that.'; this.render(); return; }
      t.id = r.id; t.phase = 'working'; this.s.err = '';
      this.follow();
    } catch (e) { t.phase = 'compose'; this.s.err = String((e && e.message) || e); }
    this.render();
  }

  async follow() {
    const t = this.s.tell; if (!t || !t.id) return;
    try {
      const st = await this.hass.callWS({ type: 'morph/tell_status', tell: t.id });
      t.state = st;
      if (st.phase === 'done' || st.phase === 'failed') { t.phase = st.phase; this.render(); return; }
    } catch (e) { /* asked again */ }
    this.render();
    t.poll = setTimeout(() => this.follow(), POLL_MS);
  }

  async undo() {
    const t = this.s.tell; if (!t || !t.id) return;
    const r = await this.hass.callWS({ type: 'morph/request', kind: 'tell_undo', payload: { id: t.id } });
    t.undone = !!r.ok; this.s.err = r.ok ? '' : r.error; this.render();
  }

  async answer(i) {
    const t = this.s.tell; if (!t || !t.id) return;
    const r = await this.hass.callWS({ type: 'morph/request', kind: 'tell_answer', payload: { id: t.id, choice: i } });
    if (!r.ok) { this.s.err = r.error; this.render(); return; }
    t.previous = t.id; t.id = r.id; t.phase = 'working'; t.state = null; this.follow();
  }

  more() {
    const t = this.s.tell; if (!t) return;
    t.previous = t.id; t.id = null; t.phase = 'compose'; t.state = null; t.undone = false; this.render();
  }

  // ------------------------------------------------------------- History

  async history() {
    this.open('history');
    this.s.hist = null; this.render();
    const r = await this.hass.callWS({ type: 'morph/request', kind: 'history', payload: { dashboard: this.s.row.key, limit: 40 } });
    this.s.hist = r.ok ? r.log || [] : []; this.s.err = r.ok ? '' : r.error; this.render();
  }

  async restore(sha) {
    const r = await this.hass.callWS({ type: 'morph/request', kind: 'restore', payload: { dashboard: this.s.row.key, sha, title: this.s.row.title } });
    this.s.err = r.ok ? '' : r.error;
    if (r.ok) await this.history(); else this.render();
  }

  // -------------------------------------------------------------- events

  onClick(e) {
    const b = e.target.closest && e.target.closest('[data-a]');
    if (!b) return;
    const a = b.dataset.a; const v = b.dataset.v;
    const go = {
      fab: () => (this.s.open ? this.close() : this.open('menu')),
      close: () => this.close(),
      menu: () => this.open('menu'),
      morph: () => this.morphIt(true),
      unmorph: () => this.morphIt(false),
      pick: () => this.startPick(),
      cancel: () => this.stopPick(),
      whole: () => this.tellAbout(null),
      convert: () => this.bringOver(),
      go: () => this.go(v),
      history: () => this.history(),
      restore: () => this.restore(v),
      send: () => this.send(),
      undo: () => this.undo(),
      answer: () => this.answer(Number(v)),
      more: () => this.more(),
      scope: () => { this.s.tell.scope = v; this.render(); },
    }[a];
    if (go) { e.preventDefault(); Promise.resolve(go()).catch((err) => { this.s.err = String((err && err.message) || err); this.render(); }); }
  }

  // -------------------------------------------------------------- render

  render() {
    const row = this.s.row;
    if (!row) { this.shadowRoot.innerHTML = ''; return; }
    const keepDraft = this.shadowRoot.querySelector('textarea');
    const draft = keepDraft ? keepDraft.value : '';
    let sheet = '';
    if (this.s.open) sheet = `<div class="sheet" role="dialog" aria-label="brAIn">${this.sheetHtml(row)}${this.s.err ? `<p class="sm" style="color:var(--error-color,#c62828)">${esc(this.s.err)}</p>` : ''}</div>`;
    const pick = this.s.picking ? '<div class="pick" role="status">Tap the card you mean<button type="button" data-a="cancel">Cancel</button></div>' : '';
    const ring = this.shadowRoot.querySelector('.ring');
    this.shadowRoot.innerHTML = `<style>${CSS}</style>${pick}${sheet}<button type="button" class="fab" data-a="fab" aria-label="brAIn" aria-expanded="${this.s.open}">${MARK}</button>`;
    if (ring) this.shadowRoot.appendChild(ring);
    const ta = this.shadowRoot.querySelector('textarea');
    if (ta && draft) ta.value = draft;
  }

  // Offered until the Morph dashboard has been brought over.
  convertOffer(top) {
    if (!this.s.hasMorph || (this.s.list || []).some((d) => d.url_path === 'morph-home')) return '';
    const b = '<button type="button" class="menu" data-a="convert">Bring over your Morph dashboard…</button>';
    return top ? `${b}<hr style="border:0;border-top:1px solid var(--divider-color,rgba(0,0,0,.1));margin:8px 0">` : b;
  }

  sheetHtml(row) {
    const mode = this.s.mode;
    if (mode === 'menu') {
      if (row.mode !== 'storage') return `<h2>${esc(row.title)}</h2><p class="sm">This dashboard is kept in YAML files, which Home Assistant cannot save. brAIn can change dashboards made in Home Assistant's own editor.</p>`;
      if (!row.morphed) {
        return `${this.convertOffer(true)}<h2>Let brAIn change ${esc(row.title)}?</h2><p class="sm">Then you can tell brAIn what to change on any card, tab or the whole dashboard, and it changes here, live. Every change is kept, so any one can be undone, including edits made in Home Assistant's own editor.</p><div class="row"><button type="button" class="b go" data-a="morph">Let brAIn change it</button><button type="button" class="b" data-a="close">Not now</button></div>`;
      }
      return `<h2>${esc(row.title)}</h2>
<button type="button" class="menu" data-a="pick">Tell brAIn about a card…</button>
<button type="button" class="menu" data-a="whole">Tell brAIn about this dashboard…</button>
<button type="button" class="menu" data-a="history">History and undo</button>
<button type="button" class="menu" data-a="unmorph">Stop letting brAIn change this dashboard</button>${this.convertOffer()}`;
    }
    if (mode === 'convert') {
      const c = this.s.conv || {};
      if (c.phase === 'working') return '<h2>Bringing over your Morph dashboard…</h2>';
      if (c.phase === 'failed') return `<h2>Not brought over</h2><p class="sm">${esc(c.error)}</p><div class="row"><button type="button" class="b" data-a="menu">Back</button></div>`;
      const notes = c.report && c.report.length ? `<p class="sm">What did not come along exactly:</p><ul class="shows">${c.report.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
      return `<h2>Your Morph dashboard is here now</h2><p class="sm">It is a Home Assistant dashboard of its own in the sidebar, laid out by Morph's view, with every card brought over. Morph's old panel is left as it was.</p>${notes}<div class="row"><button type="button" class="b go" data-a="go" data-v="${esc(c.url)}">Open it</button><button type="button" class="b" data-a="close">Later</button></div>`;
    }
    if (mode === 'history') {
      const h = this.s.hist;
      const rows = h == null ? '<p class="sm">Reading the history…</p>' : h.length ? `<ul class="hist">${h.map((c, i) => `<li><span>${esc(c.message)}<br><span class="sm">${esc(new Date(c.at * 1000).toLocaleString())} · ${esc(c.who)}</span></span>${i ? `<button type="button" class="b" data-a="restore" data-v="${esc(c.sha)}">Restore</button>` : '<span class="sm">Now</span>'}</li>`).join('')}</ul>` : '<p class="sm">No changes yet.</p>';
      return `<h2>History of ${esc(row.title)}</h2>${rows}<div class="row"><button type="button" class="b" data-a="menu">Back</button></div>`;
    }
    const t = this.s.tell;
    if (!t) return '';
    const pic = t.shot && t.shot.url ? `<img class="shot" alt="The card as it is now" src="${esc(t.shot.url)}">` : t.shot && t.shot.status === 'taking' ? '<p class="sm">Taking a picture of it…</p>' : '';
    const head = `<h2>Tell brAIn</h2><p class="sm">${esc(t.where)}</p>${pic}`;
    if (t.phase === 'compose' || t.phase === 'sending') {
      const choice = t.typeSlug ? `<p class="sm" style="margin-top:8px">This is a copy of the card type “${esc(t.typeName || t.typeSlug)}”${t.copies ? `, used in ${t.copies} place${t.copies === 1 ? '' : 's'}` : ''}. Change:</p><div class="row" style="margin-top:0"><button type="button" class="b" data-a="scope" data-v="one" aria-pressed="${t.scope === 'one'}">Just this one</button><button type="button" class="b" data-a="scope" data-v="type" aria-pressed="${t.scope === 'type'}">Every copy</button></div>` : '';
      return `${head}${choice}<textarea aria-label="What should change" placeholder="What should change?"${t.phase === 'sending' ? ' disabled' : ''}></textarea>
<div class="row"><button type="button" class="b go" data-a="send"${t.phase === 'sending' ? ' disabled' : ''}>${t.phase === 'sending' ? 'Sending…' : 'Send'}</button><button type="button" class="b" data-a="close">Cancel</button></div>`;
    }
    const st = t.state || {};
    const steps = (st.steps || []).slice(-8).map((s) => `<li class="${esc(s.tone || '')}">${esc(s.t)}</li>`).join('');
    const said = t.text ? `<p class="sm">You asked: “${esc(t.text)}”</p>` : '';
    if (t.phase === 'working') return `${head}${said}<ul class="steps" aria-live="polite">${steps || '<li>Handing it to brAIn…</li>'}</ul>`;
    const shows = (st.shows || []).length ? `<ul class="shows">${st.shows.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
    const q = st.question && st.answered == null ? `<p class="say">${esc(st.question.text)}</p><div class="row">${st.question.options.map((o, i) => `<button type="button" class="b" data-a="answer" data-v="${i}">${esc(o.label)}</button>`).join('')}</div>` : '';
    const undo = (st.commit || (st.house || []).length) && !t.undone ? '<button type="button" class="b" data-a="undo">Undo</button>' : '';
    return `${head}${said}<p class="say">${esc(st.say || '')}</p>${shows}${t.undone ? '<p class="sm">Put back.</p>' : ''}${q}
<div class="row"><button type="button" class="b go" data-a="close">Keep</button>${undo}<button type="button" class="b" data-a="more">Change something else</button></div>`;
  }
}

if (typeof window !== 'undefined' && window.customElements && !customElements.get('brain-layer')) {
  customElements.define('brain-layer', BrainLayer);
  const layer = document.createElement('brain-layer');
  const mount = () => { if (!layer.isConnected) document.body.appendChild(layer); layer.refresh(); };
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
  // Home Assistant navigates without reloading: it fires location-changed.
  window.addEventListener('location-changed', () => setTimeout(() => layer.refresh(), 60));
  window.addEventListener('popstate', () => setTimeout(() => layer.refresh(), 60));
  // The panel is created after this module runs on a cold load.
  let tries = 0;
  const early = setInterval(() => { tries += 1; layer.refresh(); if (layer.panel || tries > 20) clearInterval(early); }, 500);
}
