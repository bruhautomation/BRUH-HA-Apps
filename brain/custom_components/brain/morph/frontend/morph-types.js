// Card types: a card brAIn builds once, used on any dashboard
// (docs/design/morph-on-lovelace.md §2.3; the files are cardtypes.py's).
//
// Each type in /config/morph/types is the custom card
// `custom:morph-type-<slug>`, listed in HA's card picker as "Morph · <name>"
// with HA's own visual editor for its variables. A copy holds only its
// variables; what it draws is the type as it is NOW, so when brAIn changes
// the type every copy on every open dashboard redraws at once (the
// integration says `types` moved on morph/subscribe).
//
//   template  a Lovelace card config with [[variable]] placeholders, drawn by
//             HA's own card helpers: built-in and HACS cards alike
//   element   types/<slug>.js, whose default export is the card's class
//
// This house's own card code (/config/morph/cards/*.js) is loaded here too,
// so a card Morph's panel could draw draws on a Home Assistant dashboard.

export const PREFIX = 'morph-type-';
const REG = new Map(); // slug -> type row
const LIVE = new Map(); // slug -> Set of live copies
const ELEMENTS = new Map(); // module url -> inner tag
let LOADED = false;
let SEQ = 0;

// "[[name]]" alone is the value itself (a list stays a list); inside a longer
// string it is the value as text. A variable nobody set leaves its key out.
const WHOLE = /^\[\[\s*([a-z_][a-z0-9_]*)\s*\]\]$/;
const PART = /\[\[\s*([a-z_][a-z0-9_]*)\s*\]\]/g;
export function expand(node, vars) {
  if (typeof node === 'string') {
    const m = node.match(WHOLE);
    if (m) return vars[m[1]];
    return node.replace(PART, (_, k) => (vars[k] == null ? '' : typeof vars[k] === 'object' ? JSON.stringify(vars[k]) : String(vars[k])));
  }
  if (Array.isArray(node)) return node.map((x) => expand(x, vars)).filter((x) => x !== undefined);
  if (node && typeof node === 'object') {
    const out = {};
    Object.keys(node).forEach((k) => { const v = expand(node[k], vars); if (v !== undefined) out[k] = v; });
    return out;
  }
  return node;
}

// A copy's variables over the type's defaults.
export function varsOf(def, config) {
  const vars = {};
  (def.variables || []).forEach((v) => { if (v.default !== undefined) vars[v.name] = v.default; });
  Object.keys(config || {}).forEach((k) => { if (k !== 'type') vars[k] = config[k]; });
  return vars;
}

export function missing(def, config) {
  const vars = varsOf(def, config);
  return (def.variables || []).filter((v) => v.required && (vars[v.name] == null || vars[v.name] === '')).map((v) => v.label || v.name);
}

export function formOf(def) {
  const labels = {}; const helpers = {};
  (def.variables || []).forEach((v) => { labels[v.name] = v.label || v.name; if (v.helper) helpers[v.name] = v.helper; });
  return {
    schema: (def.variables || []).map((v) => ({ name: v.name, required: !!v.required, selector: v.selector || { text: {} } })),
    computeLabel: (s) => labels[s.name] || s.name,
    computeHelper: (s) => helpers[s.name],
  };
}

export function stubOf(def, hass) {
  const cfg = { type: 'custom:' + PREFIX + def.slug };
  const ids = Object.keys((hass && hass.states) || {}).sort();
  (def.variables || []).forEach((v) => {
    if (v.default !== undefined) { cfg[v.name] = v.default; return; }
    const ent = v.selector && v.selector.entity;
    if (!ent || !v.required) return;
    const filt = [].concat(ent.filter || []).concat(ent.domain ? [{ domain: ent.domain }] : []);
    const doms = filt.flatMap((f) => [].concat(f.domain || []));
    const pick = ids.filter((e) => !doms.length || doms.includes(e.split('.')[0]));
    cfg[v.name] = ent.multiple ? pick.slice(0, 3) : pick[0] || '';
  });
  return cfg;
}

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function helpers() {
  for (let i = 0; i < 100 && typeof window.loadCardHelpers !== 'function'; i++) await new Promise((r) => setTimeout(r, 100));
  return typeof window.loadCardHelpers === 'function' ? window.loadCardHelpers() : null;
}

async function elementTag(def) {
  if (ELEMENTS.has(def.module)) return ELEMENTS.get(def.module);
  const mod = await import(def.module);
  const Cls = mod && mod.default;
  if (typeof Cls !== 'function') throw new Error(`types/${def.slug}.js has no default export (the card's class).`);
  // A new version of the code is a new tag: a page defines a name once.
  const tag = `${PREFIX}${def.slug}-v${(SEQ += 1)}`;
  customElements.define(tag, class extends Cls {});
  ELEMENTS.set(def.module, tag);
  return tag;
}

export class MorphTypeCard extends HTMLElement {
  static get slug() { return ''; }

  constructor() {
    super();
    this._n = 0;
  }

  get slug() { return this.constructor.slug; }

  setConfig(config) {
    if (!config || typeof config !== 'object') throw new Error('Invalid configuration');
    this._config = { ...config };
    this.build();
  }

  set hass(h) {
    this._hass = h;
    if (this._inner) this._inner.hass = h;
  }

  get hass() { return this._hass; }

  connectedCallback() {
    if (!LIVE.has(this.slug)) LIVE.set(this.slug, new Set());
    LIVE.get(this.slug).add(this);
    if (!this._inner && !this._note) this.build();
  }

  disconnectedCallback() {
    const s = LIVE.get(this.slug); if (s) s.delete(this);
  }

  getCardSize() {
    try { return (this._inner && this._inner.getCardSize && this._inner.getCardSize()) || 2; } catch (e) { return 2; }
  }

  getGridOptions() {
    try { if (this._inner && this._inner.getGridOptions) return this._inner.getGridOptions(); } catch (e) { /* the type's own */ }
    const def = REG.get(this.slug);
    return (def && def.grid) || { columns: 12, rows: 'auto' };
  }

  static getConfigForm() { const def = REG.get(this.slug); return def ? formOf(def) : { schema: [] }; }

  static getStubConfig(hass) { const def = REG.get(this.slug); return def ? stubOf(def, hass) : { type: 'custom:' + PREFIX + this.slug }; }

  note(text) {
    this._inner = null;
    this._note = text;
    this.innerHTML = `<ha-card><div style="padding:14px 16px;color:var(--secondary-text-color)">${esc(text)}</div></ha-card>`;
  }

  // Draw the type as it is now. Called again whenever the type changes.
  async build() {
    if (!this._config) return;
    const n = (this._n += 1);
    const def = REG.get(this.slug);
    if (!def) { this.note(LOADED ? `brAIn has no card type “${this.slug}” any more.` : 'Loading…'); return; }
    if (def.error) { this.note(`The card type “${def.name || this.slug}” does not read: ${def.error}`); return; }
    const want = missing(def, this._config);
    if (want.length) { this.note(`Choose ${want.join(', ')}.`); return; }
    let el;
    try {
      const vars = varsOf(def, this._config);
      if (def.kind === 'element') {
        el = document.createElement(await elementTag(def));
        if (el.setConfig) el.setConfig({ ...vars, type: this._config.type });
      } else {
        const h = await helpers();
        const cfg = expand(def.card, vars);
        const ctag = String((cfg && cfg.type) || '');
        const madeEarly = ctag.startsWith('custom:') && !customElements.get(ctag.slice(7));
        el = h ? h.createCardElement(cfg) : null;
        if (!el) throw new Error('Home Assistant’s card helpers did not load.');
        // Only a stand-in made before its card was defined has anything to
        // rebuild; anything else would redraw this card on every mount.
        el.addEventListener('ll-rebuild', (e) => { e.stopPropagation(); if (madeEarly && this._inner === el) this.build(); });
      }
    } catch (e) {
      if (n === this._n) this.note(`The card type “${def.name}” could not be drawn: ${(e && e.message) || e}`);
      return;
    }
    if (n !== this._n) return; // a newer build is on its way
    if (this._hass) el.hass = this._hass;
    this._note = null;
    this._inner = el;
    this.replaceChildren(el);
    this.dispatchEvent(new Event('iron-resize', { bubbles: true, composed: true }));
  }
}

function define(def) {
  const tag = PREFIX + def.slug;
  if (!customElements.get(tag)) {
    customElements.define(tag, class extends MorphTypeCard { static get slug() { return def.slug; } });
  }
  window.customCards = window.customCards || [];
  const entry = window.customCards.find((c) => c && c.type === tag);
  const row = { type: tag, name: `Morph · ${def.name || def.slug}`, description: def.description || 'A card type brAIn built for this house.', preview: true };
  if (entry) Object.assign(entry, row); else window.customCards.push(row);
}

const LOADED_MODULES = new Set();

// Take a new list of types: define the new ones, redraw every copy of a type
// that changed, and say on the copies of a type that went.
export function apply(list) {
  const seen = new Set();
  (list.types || []).forEach((def) => {
    if (!def || !def.slug) return;
    seen.add(def.slug);
    const before = REG.get(def.slug);
    REG.set(def.slug, def);
    define(def);
    if (!before || JSON.stringify(before) !== JSON.stringify(def)) (LIVE.get(def.slug) || new Set()).forEach((c) => c.build());
  });
  [...REG.keys()].filter((k) => !seen.has(k)).forEach((k) => { REG.delete(k); (LIVE.get(k) || new Set()).forEach((c) => c.build()); });
  (list.modules || []).forEach((url) => {
    if (LOADED_MODULES.has(url)) return;
    LOADED_MODULES.add(url);
    import(url).catch((e) => console.warn('brAIn: a house card did not load', url, e)); // eslint-disable-line no-console
  });
  LOADED = true;
}

export function registry() { return REG; }

// The connection is the page's own: Home Assistant's root element holds hass.
async function connection() {
  for (let i = 0; i < 300; i++) {
    const root = document.querySelector('home-assistant');
    const conn = root && root.hass && root.hass.connection;
    if (conn) return conn;
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
}

export async function start() {
  const conn = await connection();
  if (!conn) return;
  const load = async () => {
    try { apply(await conn.sendMessagePromise({ type: 'morph/types' })); } catch (e) { LOADED = true; }
  };
  await load();
  try {
    await conn.subscribeMessage((ev) => { if (ev && (ev.parts || []).includes('types')) load(); }, { type: 'morph/subscribe' });
  } catch (e) { /* an older integration: types load once per page */ }
}

if (typeof window !== 'undefined' && window.customElements && !window.__morphTypes) {
  window.__morphTypes = true;
  start();
}
