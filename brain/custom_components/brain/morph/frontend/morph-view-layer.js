// Morph's view switches on Home Assistant's OWN sections view
// (docs/design/morph-on-lovelace.md §2.5, as of 5.1).
//
// Home Assistant lays the view out, edits it and sizes it; this only adds,
// and only what the view asks for under `morph:`:
//
//   morph:
//     rail: true    the room rail on a touch screen: pull it left and go
//                   room to room under the thumb (rail.js, unchanged)
//     order: false  a room that needs somebody (an open door, a leak, an
//                   unlocked lock) is lifted to the top, with why
//     fold: false   a room with nothing on and nothing recent is one line,
//                   a tap opens it
//
// A converted Morph dashboard starts with the rail on and the other two
// off; brAIn's button on the dashboard switches each one per tab, and so
// does a Tell or the view's YAML. In edit mode nothing moves or folds:
// Home Assistant's editor sees the view exactly as it is stored.
//
// It touches HA's page only through styles and attributes on the
// `.section` wrappers hui-sections-view draws (CSS `order`, `data-fold`,
// `data-why`) and one adopted stylesheet in that view's shadow root, never
// by moving or adding nodes HA's renderer owns, so a redraw by HA loses
// nothing and the next pass puts it back. Every lookup answers null rather
// than throwing: a release that moves an element turns this off, not the
// page.

import { CSS as STYLES } from './styles.js';
import { HA_THEME } from './morph-cards.js';
import { plan } from './morph-features.js';
import { Rail } from './rail.js';
import { deepFind, findPanel } from './brain-layer.js';

const TICK_MS = 1000;
const HUE = ['sky', 'amber', 'teal', 'violet', 'lime', 'peach', 'sand', 'indigo', 'rose'];

export const DEFAULTS = { rail: false, order: false, fold: false };

// The view's switches; a view with no `morph:` has none on.
export function optsOf(view) {
  const m = view && typeof view === 'object' && view.morph && typeof view.morph === 'object' ? view.morph : null;
  if (!m) return { ...DEFAULTS };
  return { rail: !!m.rail, order: !!m.order, fold: !!m.fold };
}

export const anyOn = (o) => !!(o && (o.rail || o.order || o.fold));

// What Morph adds inside hui-sections-view's shadow root.
export const VIEW_SHEET = `
.section[data-why]::before{content:attr(data-why);display:block;margin:0 4px 6px;font-size:14px;font-weight:600;color:var(--morph-rose,#DE6E5D)}
.section[data-fold]>*{display:none!important}
.section[data-fold]::after{content:attr(data-fold);display:flex;align-items:center;min-height:48px;padding:0 14px;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--secondary-text-color);font-size:15px;cursor:pointer;box-shadow:var(--ha-card-box-shadow,none);border:var(--ha-card-border-width,1px) solid var(--ha-card-border-color,var(--divider-color))}
:host(.railing) .section[data-sec]:not(.railon){opacity:.55;transition:opacity .2s ease}
.section.railon{border-radius:var(--ha-card-border-radius,12px);box-shadow:0 0 0 2px color-mix(in oklab,var(--rc) 70%,transparent)}
@media (prefers-reduced-motion:reduce){:host(.railing) .section[data-sec]{transition:none}}
@media (any-pointer:coarse){:host(.morph-rail) .wrapper{padding-right:30px!important}}
`;

// The rail's own box: fixed at the right edge under HA's toolbar, the same
// strip Morph's view had (styles.js draws it only on a touch screen).
const RAIL_CSS = `
:host{all:initial}
.morph.mrl{background:transparent;min-height:0;position:fixed;right:0;top:var(--header-height,56px);bottom:0;width:28px;z-index:5;pointer-events:none}
.mrl .srail{position:absolute!important;top:0;right:0;bottom:0;height:auto!important;pointer-events:auto}
`;

let SHEETS = null;
function sheets() {
  if (SHEETS) return SHEETS;
  const mk = (css) => { try { const s = new CSSStyleSheet(); s.replaceSync(css); return s; } catch (e) { return null; } };
  SHEETS = { view: mk(VIEW_SHEET), rail: mk(STYLES + HA_THEME + RAIL_CSS) };
  return SHEETS;
}

// The `.section` wrappers of a sections view, each with the index of its
// config (the hui-section's path), in the order HA drew them.
export function sectionsOf(view) {
  const root = view && view.shadowRoot;
  if (!root) return [];
  const out = [];
  root.querySelectorAll('.section').forEach((div) => {
    const hs = div.querySelector('hui-section') || deepFind(div, (n) => n.localName === 'hui-section', 50);
    // `path` on current releases, `index` on older ones (2025.1).
    const path = hs && hs.path;
    const i = Array.isArray(path) ? Number(path[path.length - 1]) : hs && Number.isInteger(hs.index) ? hs.index : NaN;
    if (Number.isInteger(i)) out.push({ div, i });
  });
  return out;
}

export function currentView(doc = document) {
  const panel = findPanel(doc);
  if (!panel) return null;
  return deepFind(panel, (n) => n.localName === 'hui-sections-view', 3000);
}

export function viewConfig(view) {
  try {
    const cfg = view.lovelace && view.lovelace.config;
    return (cfg && cfg.views && cfg.views[view.index]) || null;
  } catch (e) { return null; }
}

// The nearest scrolling ancestor through shadow roots, else the window,
// as the one shape the rail reads (morph-features.js's MorphView does the
// same for Morph's own view).
export function scrollerOf(el) {
  let n = el;
  while (n && n !== document.documentElement) {
    if (n.nodeType === 1) {
      const oy = getComputedStyle(n).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight + 1) return n;
    }
    n = n.parentNode || (n.getRootNode && n.getRootNode().host);
  }
  return {
    isConnected: true,
    getBoundingClientRect: () => ({ top: 0, left: 0, width: innerWidth, height: innerHeight, bottom: innerHeight, right: innerWidth }),
    get scrollTop() { return window.scrollY; },
    set scrollTop(v) { window.scrollTo(0, v); },
    get scrollHeight() { return document.documentElement.scrollHeight; },
    get clientHeight() { return innerHeight; },
    addEventListener: (n2, f, o) => window.addEventListener(n2, f, o),
  };
}

const foldWords = (r) => `${r.name} · ${r.count} thing${r.count === 1 ? '' : 's'}, nothing on`;

export class ViewLayer {
  constructor() {
    this.view = null;
    this.applied = null;
    this.open = new Set();
    this.lastMove = 0;
    this.lastTouch = 0;
    this.heard = new WeakSet();
    this.railBox = null;
    this.rail = null;
    this._sc = null;
    // The rail's host: rail.js reads these (Morph's view and engine shape).
    const self = this;
    this.engine = {
      sc: null,
      get model() { return { sections: (self.applied || []).filter((r) => !self.folded(r)).map((r) => ({ id: 's' + r.i, floorId: '' })) }; },
      scroller() { return self.scroller(); },
      scrollY() { return self.scroller().scrollTop; },
      scrollTo(y) { self.scroller().scrollTop = y; },
      reduce() { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); },
    };
    // rail.js looks rooms up as `[data-board] section[data-sec]` in its
    // host's shadow root and lights the room it is on; here the rooms are
    // HA's `.section` wrappers, marked `data-sec`.
    this.shadowRoot = { querySelectorAll: (sel) => this.railRooms(sel) };
    this.rootEl = { classList: { add: (c) => this.view && this.view.classList.add(c), remove: (c) => this.view && this.view.classList.remove(c) } };
  }

  railRooms(sel) {
    const all = this.view && this.view.shadowRoot ? [...this.view.shadowRoot.querySelectorAll('.section[data-sec]')] : [];
    if (/railon/.test(sel)) return all.filter((d) => d.classList.contains('railon'));
    return all;
  }

  railColor(id) { return `var(--morph-${HUE[Number(String(id).slice(1)) % HUE.length]},var(--primary-color))`; }

  railFloor() { return ''; }

  folded(r) { return r.fold && !this.open.has(r.i); }

  scroller() {
    if (this._sc && (this._sc.isConnected !== false)) return this._sc;
    this._sc = scrollerOf(this.view);
    this._sc.addEventListener('scroll', () => this.paintRail(), { passive: true });
    return this._sc;
  }

  paintRail() {
    if (!this.rail || this._railF) return;
    this._railF = requestAnimationFrame(() => { this._railF = 0; try { this.rail.paint(); } catch (e) { /* no rail */ } });
  }

  // One pass: find the view, read its switches, put things where they go.
  tick(doc = document) {
    const view = currentView(doc);
    if (view !== this.view) this.leave();
    this.view = view;
    const cfg = view && viewConfig(view);
    const opts = optsOf(cfg);
    if (!view || !cfg || !anyOn(opts)) { this.leave(); return; }
    this.adopt(view);
    const editing = !!(view.lovelace && view.lovelace.editMode);
    const secs = sectionsOf(view);
    const states = (view.hass && view.hass.states) || {};
    const next = plan(cfg.sections || [], states, editing ? { order: false, fold: false } : { order: opts.order, fold: opts.fold });
    const sig = (p) => p.map((r) => `${r.i}${r.fold ? 'f' : ''}${r.lifted ? 'l' : ''}`).join(',');
    const urgent = next.some((r) => r.lifted && !(this.applied || []).some((a) => a.i === r.i && a.lifted));
    const quiet = Date.now() - this.lastTouch > 1200 && Date.now() - this.lastMove > 8000;
    if (!this.applied || editing || urgent || (quiet && sig(next) !== sig(this.applied))) {
      if (this.applied && sig(next) !== sig(this.applied)) this.lastMove = Date.now();
      this.applied = next;
    } else {
      this.applied = this.applied.map((a) => ({ ...(next.find((r) => r.i === a.i) || a), lifted: a.lifted, fold: a.fold }));
    }
    const pos = new Map(this.applied.map((r, k) => [r.i, k]));
    const byI = new Map(this.applied.map((r) => [r.i, r]));
    secs.forEach(({ div, i }) => {
      const r = byI.get(i);
      div.setAttribute('data-sec', 's' + i);
      if (!this.heard.has(div)) {
        this.heard.add(div);
        div.addEventListener('pointerdown', () => { this.lastTouch = Date.now(); }, { passive: true });
        div.addEventListener('click', (e) => {
          if (!div.hasAttribute('data-fold')) return;
          e.stopPropagation();
          this.open.add(Number(String(div.getAttribute('data-sec')).slice(1)));
          this.tick(doc);
        }, true);
      }
      const ordered = opts.order && !editing && r;
      if (ordered) div.style.setProperty('order', String(pos.get(i))); else div.style.removeProperty('order');
      const why = ordered && r.lifted && r.needs.length ? r.needs.slice(0, 2).join(' · ') : '';
      if (why) div.setAttribute('data-why', why); else div.removeAttribute('data-why');
      if (r && !editing && this.folded(r)) { div.setAttribute('data-fold', foldWords(r)); div.setAttribute('role', 'button'); } else { div.removeAttribute('data-fold'); div.removeAttribute('role'); }
    });
    this.railOn(opts.rail && !editing);
    view.classList.toggle('morph-rail', !!(opts.rail && !editing));
  }

  adopt(view) {
    const s = sheets().view;
    const root = view.shadowRoot;
    if (!s || !root || root.adoptedStyleSheets.includes(s)) return;
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, s];
  }

  railOn(on) {
    if (!on) { this.railOff(); return; }
    if (!this.railBox) {
      const host = document.createElement('morph-rail-box');
      const sr = host.attachShadow({ mode: 'open' });
      const sh = sheets().rail;
      if (sh) sr.adoptedStyleSheets = [sh];
      const wrap = document.createElement('div');
      wrap.className = 'morph mrl t-ha';
      const el = document.createElement('div');
      el.className = 'srail';
      wrap.appendChild(el);
      sr.appendChild(wrap);
      document.body.appendChild(host);
      this.railBox = host;
      try { this.rail = new Rail(el, this); } catch (e) { this.rail = null; }
    }
    this.paintRail();
  }

  railOff() {
    if (this.railBox) { this.railBox.remove(); this.railBox = null; }
    this.rail = null;
  }

  // Off this view: everything put back the way HA drew it.
  leave() {
    const view = this.view;
    if (view && view.shadowRoot) {
      view.shadowRoot.querySelectorAll('.section').forEach((div) => {
        div.style.removeProperty('order');
        ['data-why', 'data-fold', 'role', 'data-sec'].forEach((a) => div.removeAttribute(a));
        div.classList.remove('railon');
      });
      view.classList.remove('railing');
      view.classList.remove('morph-rail');
    }
    this.railOff();
    this.applied = null;
    this.open = new Set();
    this._sc = null;
    this.view = null;
  }
}

export function start(win = window) {
  if (win.__morphViewLayer) return win.__morphViewLayer;
  const layer = new ViewLayer();
  win.__morphViewLayer = layer;
  const run = () => { try { layer.tick(win.document); } catch (e) { /* the page goes on */ } };
  win.setInterval(run, TICK_MS);
  win.addEventListener('location-changed', () => setTimeout(run, 50));
  run();
  return layer;
}

if (typeof window !== 'undefined' && window.customElements) start(window);
