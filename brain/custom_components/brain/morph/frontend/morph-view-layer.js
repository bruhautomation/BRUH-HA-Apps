// Morph's view switches on Home Assistant's OWN sections view
// (docs/design/morph-on-lovelace.md §2.5, as of 5.1).
//
// Home Assistant lays the view out, edits it and sizes it; this only adds,
// and only what the view asks for under `morph:`:
//
//   morph:
//     rail: true    the room rail on a touch screen: swipe it left and go
//                   room to room under the thumb
//
// Nothing on the view reorders itself and no section folds: Morph keeps the
// order the view is written in, everywhere. A converted Morph dashboard
// starts with the rail on; brAIn's button on the dashboard switches it per
// tab, and so does a Tell or the view's YAML. In edit mode the rail is off.
//
// It touches HA's page only through attributes on the `.section` wrappers
// hui-sections-view draws (`data-sec`), one adopted stylesheet in that
// view's shadow root, and the
// rail's own box at the start of that shadow root, never by moving nodes
// HA's renderer owns, so a redraw by HA loses nothing and the next pass
// puts it back. Every lookup answers null rather
// than throwing: a release that moves an element turns this off, not the
// page.

import { CSS as STYLES } from './styles.js';
import { HA_THEME } from './morph-cards.js';
import { plan, entitiesOf } from './morph-features.js';
import { Scrub, SCRUB_CSS } from './scrub.js';
import { deepFind, findPanel } from './brain-layer.js';

const TICK_MS = 1000;
const HUE = ['sky', 'amber', 'teal', 'violet', 'lime', 'peach', 'sand', 'indigo', 'rose'];

export const DEFAULTS = { rail: false };

// The view's switches; a view with no `morph:` has none on.
export function optsOf(view) {
  const m = view && typeof view === 'object' && view.morph && typeof view.morph === 'object' ? view.morph : null;
  if (!m) return { ...DEFAULTS };
  return { rail: !!m.rail };
}

export const anyOn = (o) => !!(o && o.rail);

// What Morph adds inside hui-sections-view's shadow root.
export const VIEW_SHEET = `
/* The room the rail is going to (scrub.js): ringed, the others dimmed. */
:host(.mrail-dim) .section[data-sec]:not(.mrail-tgt){opacity:.5;transition:opacity .3s ease}
.section.mrail-tgt{border-radius:var(--ha-card-border-radius,12px);box-shadow:0 0 0 2px color-mix(in oklab,var(--rh,var(--primary-text-color)) 55%,transparent);transition:box-shadow .35s ease}
@media (prefers-reduced-motion:reduce){:host(.mrail-dim) .section[data-sec],.section.mrail-tgt{transition:none}}
@media (any-pointer:coarse){:host(.morph-rail) .wrapper{padding-right:30px!important}}
`;

// The rail's own box: the right edge under HA's toolbar, the same strip
// Morph's view had (styles.js draws it only on a touch screen), held INSIDE
// the view's scroll. It was a fixed, full-height box on
// document.body, and on an iPhone a vertical swipe that started on it went
// to the document, which in the Home Assistant app is not what scrolls the
// dashboard: the page stuck. Now the box is the first thing in the view, a
// sticky line of no height that stays at the top of the screen while the
// view scrolls, with the rail hanging from it at the right edge, so a swipe
// on the rail chains to the view's own scroller like a swipe anywhere else.
const RAIL_CSS = `
:host{all:initial;display:block;position:sticky;top:calc(var(--header-height,56px) + env(safe-area-inset-top,0px));height:0;z-index:5;pointer-events:none}
.morph.mrl{background:transparent;min-height:0;position:absolute;right:0;top:0;width:46px;height:calc(100vh - var(--header-height,56px) - env(safe-area-inset-top,0px));height:calc(100dvh - var(--header-height,56px) - env(safe-area-inset-top,0px));pointer-events:none}
.mrl .mrail{top:8px;bottom:calc(16px + env(safe-area-inset-bottom,0px));pointer-events:auto}
/* A Home Assistant view keeps its own scroll bar; the rail is for touch. */
@media not (any-pointer:coarse){.mrl .mrail{display:none}}
`;

let SHEETS = null;
function sheets() {
  if (SHEETS) return SHEETS;
  const mk = (css) => { try { const s = new CSSStyleSheet(); s.replaceSync(css); return s; } catch (e) { return null; } };
  SHEETS = { view: mk(VIEW_SHEET), rail: mk(STYLES + HA_THEME + SCRUB_CSS + RAIL_CSS) };
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

export class ViewLayer {
  constructor() {
    this.view = null;
    this.applied = null;
    this.railBox = null;
    this.rail = null;
    this._sc = null;
  }

  // The rail's host (scrub.js): HA's `.section` wrappers are the rooms, in
  // the order the view has them; their names are each section's heading.
  railHost(wrap) {
    const self = this;
    return {
      root: wrap,
      scroller: () => self.scroller(),
      get hass() { return self.view && self.view.hass; },
      hidden: () => false,
      board: () => self.view,
      reduce: () => !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches),
      still: () => {},
      // HA's toolbar over the scroller: the rail box's sticky top is its foot.
      cover() {
        const sc = self.scroller();
        const top = self.railBox ? self.railBox.getBoundingClientRect().top : 0;
        return Math.max(0, top - sc.getBoundingClientRect().top);
      },
      rooms() {
        const cfgs = (viewConfig(self.view) || {}).sections || [];
        const byI = new Map((self.applied || []).map((r) => [r.i, r]));
        return sectionsOf(self.view).filter(({ div }) => div.offsetParent !== null && div.offsetHeight >= 40).map(({ div, i }) => {
          const r = byI.get(i);
          return { id: 's' + i, el: div, title: r ? r.name : '', icon: '', ents: [...entitiesOf(cfgs[i] || {})], rc: '', floor: 0, floorTitle: '', cases: 0 };
        });
      },
    };
  }

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
    this.applied = plan(cfg.sections || [], states);
    secs.forEach(({ div, i }) => { div.setAttribute('data-sec', 's' + i); });
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
    const root = this.view && this.view.shadowRoot;
    if (!root) { this.railOff(); return; }
    // HA redrew the view, or this is another one: the box goes back in.
    if (this.railBox && this.railBox.parentNode !== root) this.railOff();
    if (!this.railBox) {
      const host = document.createElement('morph-rail-box');
      const sr = host.attachShadow({ mode: 'open' });
      const sh = sheets().rail;
      if (sh) sr.adoptedStyleSheets = [sh];
      const wrap = document.createElement('div');
      wrap.className = 'morph mrl t-ha';
      sr.appendChild(wrap);
      root.insertBefore(host, root.firstChild);
      this.railBox = host;
      try { this.rail = new Scrub(null, this.railHost(wrap)); } catch (e) { this.rail = null; }
    }
    this.paintRail();
  }

  railOff() {
    if (this.rail) { try { this.rail.destroy(); } catch (e) { /* gone */ } }
    if (this.railBox) { this.railBox.remove(); this.railBox = null; }
    this.rail = null;
  }

  // Off this view: everything put back the way HA drew it.
  leave() {
    const view = this.view;
    if (view && view.shadowRoot) {
      view.shadowRoot.querySelectorAll('.section').forEach((div) => {
        // `order`, `data-why`, `data-fold` and `role` were this layer's until
        // 5.3.0; a page still carrying them from an older load is put back.
        div.style.removeProperty('order');
        ['data-why', 'data-fold', 'role', 'data-sec'].forEach((a) => div.removeAttribute(a));
        div.classList.remove('railon', 'mrail-tgt');
      });
      view.classList.remove('railing', 'mrail-dim');
      view.classList.remove('morph-rail');
    }
    this.railOff();
    this.applied = null;
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
