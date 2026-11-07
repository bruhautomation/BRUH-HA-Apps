// Loads Morph's panel, and paints straight away while it does.
//
// Home Assistant creates the panel's element only once this module has
// finished running. It used to await the whole panel (seven modules, each
// one round trip) before finishing, so a person opening Morph looked at a
// blank page for as long as that took. Now this defines a small shell,
// <morph-boot>, which draws the dashboard's outline at once, starts every
// module downloading in parallel, and puts the real <morph-panel> inside
// itself when it has loaded. The outline stays over it until the panel
// has its dashboard to show.
//
// Morph's own modules can be replaced by this house's copies
// (/config/morph/frontend/, served in their place), and a copy can break:
// when the panel does not load, this loads Morph's own instead, from
// shipped/, and leaves the reason where the panel reads it, so the page says
// what happened rather than going blank. A copy can also load and then
// throw as it draws (#706: a Tell took a feature out and left a reference
// to an import it removed, and Morph was blank): until the panel says it is
// ready, an error thrown from this house's code swaps in Morph's own the
// same way. This file is never replaced.
//
// static.py writes STAMP and MODULES in as it serves this file. STAMP names
// exactly the code being served, so the modules under s/<STAMP>/ never
// change and the browser keeps them; the panel compares it with the code
// Home Assistant now has, which is how it knows to offer a reload. Served
// as a plain file (a test), both are empty and the modules load from here.
const STAMP = '';
const MODULES = [];
// The modules this house has its own copy of in use (static.py writes them
// in). With none, what is served is Morph's own and there is nothing to
// fall back to; served as a plain file (a test), every module is watched.
const COPIES = [];
const here = new URL('.', import.meta.url).href;
const dir = STAMP ? `${here}s/${STAMP}/` : here;
const shippedDir = `${here}shipped/`;
window.__morphStamp = STAMP;

for (const name of MODULES) {
  if (document.querySelector(`link[data-morph-pre="${name}"]`)) continue;
  const l = document.createElement('link');
  l.rel = 'modulepreload';
  l.href = dir + name;
  l.dataset.morphPre = name;
  document.head.appendChild(l);
}

let loading = null;
// The element the panel is: `morph-panel`, or `morph-panel-shipped` once a
// house copy that loaded has been swapped for Morph's own (a name, once
// defined, cannot be defined again).
let panelTag = 'morph-panel';
// Whether the panel running came from this house's code, and so may yet
// fall back to Morph's own.
let fromHouse = false;
function loadPanel() {
  if (!loading) {
    loading = (async () => {
      try {
        await import(dir + 'morph-panel.js');
        if (!customElements.get('morph-panel')) throw new Error('morph-panel.js loaded but did not define the panel');
        fromHouse = !STAMP || COPIES.length > 0;
      } catch (err) {
        window.__morphFallback = String((err && err.message) || err);
        console.error('Morph: a changed file did not load, so Morph is running its own copy.', err);
        await import(shippedDir + 'morph-panel.js');
      }
    })();
  }
  return loading;
}

// Morph's own panel, after this house's copy has already defined
// `morph-panel`: the module's own `define` is steered to another name.
let shippedLoading = null;
function loadShipped() {
  if (!shippedLoading) {
    shippedLoading = (async () => {
      const reg = window.customElements;
      const get = reg.get.bind(reg);
      const define = reg.define.bind(reg);
      reg.get = (n) => (n === 'morph-panel' ? undefined : get(n));
      reg.define = (n, C, o) => (n === 'morph-panel' ? define('morph-panel-shipped', C, o) : get(n) ? undefined : define(n, C, o));
      try {
        await import(shippedDir + 'morph-panel.js');
      } finally {
        delete reg.get;
        delete reg.define;
      }
      if (!customElements.get('morph-panel-shipped')) throw new Error("Morph's own panel did not load");
      panelTag = 'morph-panel-shipped';
    })();
  }
  return shippedLoading;
}

// Whether an error came from this house's code: its file, or a frame of its
// stack, served from `dir` and not from shipped/.
function fromHouseCode(file, stack) {
  const urls = [file || '', ...String(stack || '').match(/https?:\/\/[^\s)]+/g) || []];
  return urls.some((u) => u.startsWith(dir) && !u.startsWith(shippedDir));
}

// What the outline is drawn in: the theme the panel last rendered in, else
// Home Assistant's own dark mode. Three themes, the panel's own colours.
const THEMES = { dark: ['#0A0C0E', '#15181B'], medium: ['#2A2D31', '#34383D'], light: ['#ECEBE6', '#FFFFFF'] };
function themeOf(hass) {
  try {
    const t = localStorage.getItem('morph.theme');
    if (THEMES[t]) return t;
  } catch (e) { /* storage refused */ }
  return hass && hass.themes && hass.themes.darkMode === false ? 'light' : 'dark';
}

// `shell` is brAIn's: true while brAIn's header is above the dashboard.
const PROPS = ['hass', 'narrow', 'route', 'panel', 'shell'];
const READY_AFTER_MS = 6000;

class MorphBoot extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._v = {};
    this.inner = null;
  }

  connectedCallback() {
    if (!this._drawn) this.draw();
    loadPanel().then(() => this.mount(), (err) => this.failed(err));
  }

  draw() {
    this._drawn = true;
    const [bg, tile] = THEMES[themeOf(this._v.hass)];
    const tiles = Array.from({ length: 6 }, (_, i) => `<i style="animation-delay:${i * 90}ms"></i>`).join('');
    this.shadowRoot.innerHTML = `<style>
:host{display:block;position:relative;height:100%;min-height:var(--morph-h,100vh);background:${bg}}
.outline{position:absolute;inset:0;z-index:2;background:${bg};padding:22px clamp(12px,3vw,32px);box-sizing:border-box;overflow:hidden;transition:opacity .18s ease}
.outline.gone{opacity:0;pointer-events:none}
.outline b,.outline i{display:block;background:${tile};border-radius:16px;animation:pulse 1.4s ease-in-out infinite}
.outline b{height:28px;width:min(320px,60%);border-radius:10px;margin:6px 0 26px}
.outline div{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
.outline i{height:116px}
.outline p{position:absolute;left:0;right:0;bottom:24px;text-align:center;margin:0;font:13px system-ui,sans-serif;color:#8a929b}
@keyframes pulse{50%{opacity:.55}}
@media (prefers-reduced-motion:reduce){.outline b,.outline i{animation:none}.outline{transition:none}}
</style><div class="outline" role="status" aria-label="Opening Morph"><b></b><div>${tiles}</div><p>Opening Morph…</p></div>`;
  }

  mount() {
    if (this.inner) return;
    const el = document.createElement(panelTag);
    this.inner = el;
    el.addEventListener('morph-ready', () => { this.unwatch(); this.ready(); }, { once: true });
    // A copy of the panel written before this shell existed never says it
    // is ready; the outline does not stay over it for good.
    setTimeout(() => this.ready(), READY_AFTER_MS);
    if (fromHouse && panelTag === 'morph-panel') this.watch();
    // In the page first, then its properties: the order Home Assistant uses,
    // and the one in which the panel loads its dashboard once, not twice.
    try {
      this.shadowRoot.appendChild(el);
      for (const k of PROPS) if (this._v[k] !== undefined) el[k] = this._v[k];
    } catch (err) {
      if (!this._watching) throw err;
      this.broke(err);
    }
  }

  // Until the panel is ready, an error thrown from this house's code (as
  // it draws, in a timer or a promise) is the copy failing.
  watch() {
    this._watching = true;
    this._onErr = (ev) => { if (fromHouseCode(ev.filename, ev.error && ev.error.stack)) this.broke(ev.error || ev.message); };
    this._onRej = (ev) => { const r = ev.reason; if (fromHouseCode('', r && r.stack)) this.broke(r); };
    window.addEventListener('error', this._onErr);
    window.addEventListener('unhandledrejection', this._onRej);
    this._watchT = setTimeout(() => this.unwatch(), READY_AFTER_MS + 4000);
  }

  unwatch() {
    if (!this._watching) return;
    this._watching = false;
    window.removeEventListener('error', this._onErr);
    window.removeEventListener('unhandledrejection', this._onRej);
    clearTimeout(this._watchT);
  }

  // The house's copy threw before it drew anything: Morph's own takes its
  // place, and the reason goes where the panel says it.
  async broke(err) {
    if (this._broke) return;
    this._broke = true;
    this.unwatch();
    const why = String((err && err.message) || err);
    window.__morphFallback = why;
    console.error('Morph: a changed file failed as it drew, so Morph is running its own copy.', err);
    try {
      await loadShipped();
    } catch (e) {
      this.failed(e);
      return;
    }
    const old = this.inner;
    this.inner = null;
    try { if (old) old.remove(); } catch (e) { /* a broken copy can throw going too */ }
    this.mount();
  }

  ready() {
    const o = this.shadowRoot.querySelector('.outline');
    if (!o || o.classList.contains('gone')) return;
    o.classList.add('gone');
    setTimeout(() => o.remove(), 220);
  }

  failed(err) {
    const o = this.shadowRoot.querySelector('.outline p');
    if (o) o.textContent = `Morph could not load: ${(err && err.message) || err}. Reload the page to try again.`;
  }
}

for (const k of PROPS) {
  Object.defineProperty(MorphBoot.prototype, k, {
    configurable: true,
    get() { return this._v[k]; },
    set(v) { this._v[k] = v; if (this.inner) this.inner[k] = v; },
  });
}

if (!customElements.get('morph-boot')) customElements.define('morph-boot', MorphBoot);
// Served without a stamp, this is either a test or a Home Assistant still
// running the Morph integration from before the shell, which creates
// <morph-panel> itself as soon as this module finishes. Finishing only once
// the panel is defined keeps that page working until it restarts.
if (STAMP) loadPanel(); else await loadPanel();
