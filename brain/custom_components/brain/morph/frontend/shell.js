// <brain-shell> — brAIn's one sidebar entry (brAIn 4.0).
//
// brAIn and Morph were two add-ons with two sidebar entries. They are one
// now (docs/design/brain-morph-merge.md), and this panel is the screen that
// holds both:
//
//   * brAIn's own page — Insights, Ask, Memory, Settings — in a frame, from
//     the add-on's ingress address with `?shell=1`. Its top bar is THE
//     header: it gains a Home tab, and tells this panel what is pressed.
//   * Morph — the Home tab — drawn natively, over the frame's content and
//     between its bars, because Morph hosts Lovelace cards with the live
//     `hass`, which no page inside a frame has.
//
// The frame and this panel talk by `postMessage`, `{type: "brain-shell"}`,
// and only with each other (`ev.source` is the frame's window). From the
// frame: `bars` (the header's height; `bottom` is 0 since the tabs moved
// into the header), `show` (home or panel), `raise` (a popover or a dialog
// opened while Home is in front: the frame goes over Morph until it
// closes), `menu` (open Home Assistant's sidebar), `features` (a switch
// changed) and `home` (Morph's Edit, Done or YAML pressed in brAIn's
// header). To the frame: `state` (narrow, whether the dashboard is on,
// which is in front, Morph's theme, and what of Morph's belongs in the
// header) and `open` (a view or a Settings section asked for from Morph).
//
// ONE header (the owner: "there are two headers … merge them"): brAIn's
// bar, drawn in Morph's theme — dark, medium or light, the theme Morph
// renders in (`morph-chrome` from the panel, else the one it last used,
// else Home Assistant's dark mode) — and Morph's own bar is not drawn.
//
// The ingress session is this panel's to keep, the way Home Assistant's own
// ingress view keeps it: made once (`/ingress/session`), checked every
// minute (`/ingress/validate_session`) and made again when it lapses.
//
// Not an administrator, there is no ingress session to have: with the
// dashboard on such a person sees Morph alone, as they always did; with it
// off the panel is administrators only (the integration registers it so).

const here = new URL('.', import.meta.url).href;
const TYPE = 'brain-shell';
const VALIDATE_MS = 60000;
const PROPS = ['hass', 'narrow', 'route', 'panel'];
// Morph's three grounds (styles.js), for the shell's own background.
const GROUND = { dark: '#0A0C0E', medium: '#2A2D31', light: '#ECEBE6' };

function setCookie(session) {
  document.cookie = `ingress_session=${session};path=/api/hassio_ingress/;SameSite=Strict${location.protocol === 'https:' ? ';Secure' : ''}`;
}

async function supervisor(hass, endpoint, data) {
  try {
    return await hass.callWS({ type: 'supervisor/api', endpoint, method: 'post', ...(data ? { data } : {}) });
  } catch (err) {
    // A core before the websocket command: the REST route.
    const r = await hass.callApi('POST', `hassio${endpoint}`, data);
    return r && r.data ? r.data : r;
  }
}

class BrainShell extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._v = {};
    this.info = null;
    this.view = 'home';
    this.raised = false;
    this.bars = { top: 0, bottom: 0 };
    this._onMessage = (ev) => this.message(ev);
    this._onOpen = (ev) => this.openInFrame((ev.detail && ev.detail.view) || 'insights', ev.detail && ev.detail.sec);
    this.chrome = null;
    this._onChrome = (ev) => { this.chrome = ev.detail || null; this.sync(); };
  }

  // The theme the one header is drawn in: Morph's, as it renders; the one
  // it last rendered in; Home Assistant's dark mode.
  theme() {
    const t = this.chrome && this.chrome.theme;
    if (GROUND[t]) return t;
    try { const saved = localStorage.getItem('morph.theme'); if (GROUND[saved]) return saved; } catch (e) { /* storage refused */ }
    const h = this._v.hass;
    return h && h.themes && h.themes.darkMode === false ? 'light' : 'dark';
  }

  connectedCallback() {
    window.addEventListener('message', this._onMessage);
    this.addEventListener('brain-open', this._onOpen);
    this.addEventListener('morph-chrome', this._onChrome);
    if (!this._drawn) this.draw();
    if (this._v.hass && !this.info) this.start();
  }

  disconnectedCallback() {
    window.removeEventListener('message', this._onMessage);
    this.removeEventListener('brain-open', this._onOpen);
    this.removeEventListener('morph-chrome', this._onChrome);
    clearInterval(this._validate);
    this._validate = null;
  }

  draw() {
    this._drawn = true;
    this.shadowRoot.innerHTML = `<style>
:host{display:block;position:relative;height:100vh;height:100dvh;overflow:hidden;background:var(--brain-ground,var(--primary-background-color,#0A0C0E))}
iframe{position:absolute;inset:0;width:100%;height:100%;border:0;display:block;background:transparent;z-index:1}
iframe[hidden]{display:none}
.home{position:absolute;left:0;right:0;top:var(--brain-top,0px);bottom:var(--brain-bottom,0px);z-index:2;overflow:hidden;--morph-h:calc(100vh - var(--brain-top,0px) - var(--brain-bottom,0px));--morph-h:calc(100dvh - var(--brain-top,0px) - var(--brain-bottom,0px))}
.home[hidden]{display:none}
:host(.raised) iframe{z-index:3}
.say{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;text-align:center;font:16px/1.5 system-ui,sans-serif;color:var(--primary-text-color,#e6e6e6)}
.say[hidden]{display:none}
.say a{color:var(--primary-color,#4fb3ff)}
</style><iframe title="brAIn" allow="clipboard-read; clipboard-write; microphone; fullscreen" hidden></iframe><div class="home" hidden></div><div class="say" role="status">Opening brAIn…</div>`;
    this.frame = this.shadowRoot.querySelector('iframe');
    this.homeEl = this.shadowRoot.querySelector('.home');
    this.sayEl = this.shadowRoot.querySelector('.say');
  }

  say(html) {
    this.sayEl.innerHTML = html;
    this.sayEl.hidden = !html;
  }

  async start() {
    if (this._starting) return;
    this._starting = true;
    try {
      this.info = await this._v.hass.callWS({ type: 'brain/shell' });
    } catch (err) {
      this._starting = false;
      this.say(`brAIn could not load: ${String((err && err.message) || err)}. Reload the page to try again.`);
      return;
    }
    this._starting = false;
    this.view = this.morphOn() ? 'home' : 'panel';
    if (this.info.admin && this.info.ingress_url) {
      await this.openFrame();
    } else if (!this.morphOn()) {
      this.say(this.info.admin
        ? 'brAIn has not said where its page is yet. It does within a minute of starting; reload this page then.'
        : 'Only an administrator can open brAIn.');
    }
    this.sync();
  }

  morphOn() { return !!(this.info && this.info.features && this.info.features.morph); }
  hasFrame() { return !!(this.frame && this.frame.getAttribute('src')); }

  async openFrame() {
    const hass = this._v.hass;
    try {
      const r = await supervisor(hass, '/ingress/session');
      this.session = r && r.session;
      if (!this.session) throw new Error('the Supervisor gave no session');
      setCookie(this.session);
    } catch (err) {
      const slug = this.info.slug;
      this.say(`brAIn's page could not be opened here (${String((err && err.message) || err)}).${slug ? ` <a href="/hassio/ingress/${slug}" target="_top">Open it directly</a>.` : ''}`);
      return;
    }
    clearInterval(this._validate);
    this._validate = setInterval(() => this.validate(), VALIDATE_MS);
    this.frame.src = `${this.info.ingress_url}?shell=1`;
    this.frame.hidden = false;
    this.say('');
  }

  async validate() {
    const hass = this._v.hass;
    if (!hass || !this.session) return;
    try {
      await supervisor(hass, '/ingress/validate_session', { session: this.session });
      setCookie(this.session);
    } catch (err) {
      try {
        const r = await supervisor(hass, '/ingress/session');
        if (r && r.session) { this.session = r.session; setCookie(r.session); }
      } catch (e) { /* the next minute tries again */ }
    }
  }

  // Morph is mounted the first time Home is shown, and taken down when the
  // dashboard is switched off.
  async mountMorph() {
    if (this.morph || this._mounting) return;
    this._mounting = true;
    try {
      await import(here + 'boot.js');
      const el = document.createElement('morph-boot');
      this.morph = el;
      el.shell = this.hasFrame();
      this.homeEl.appendChild(el);
      for (const k of PROPS) if (this._v[k] !== undefined) el[k] = this._v[k];
    } finally {
      this._mounting = false;
    }
  }

  unmountMorph() {
    if (!this.morph) return;
    this.morph.remove();
    this.morph = null;
  }

  sync() {
    const morph = this.morphOn();
    if (!morph && this.view === 'home') this.view = 'panel';
    const framed = this.hasFrame();
    const home = morph && (this.view === 'home' || !framed);
    if (morph) this.mountMorph(); else this.unmountMorph();
    if (this.morph) this.morph.shell = framed;
    this.homeEl.hidden = !home;
    this.style.setProperty('--brain-top', `${framed ? this.bars.top : 0}px`);
    this.style.setProperty('--brain-bottom', `${framed ? this.bars.bottom : 0}px`);
    this.classList.toggle('raised', !!(home && framed && this.raised));
    if (home || framed) this.say('');
    const theme = this.theme();
    this.style.setProperty('--brain-ground', GROUND[theme]);
    const c = this.chrome || {};
    // Morph's Edit belongs in the header while Morph is mounted and the
    // person may edit it (or is editing it).
    const edit = !!(morph && this.morph && (c.admin || c.edit));
    this.post({ state: { narrow: !!this._v.narrow, morph, view: home ? 'home' : 'panel', theme,
                         home: { edit, editing: !!c.edit, yaml: !!c.yaml } } });
  }

  post(body) {
    if (!this.hasFrame() || !this.frame.contentWindow) return;
    try { this.frame.contentWindow.postMessage({ type: TYPE, ...body }, location.origin); } catch (e) { /* the frame is loading */ }
  }

  openInFrame(view, sec) {
    if (!this.hasFrame()) return;
    this.view = 'panel';
    this.post({ open: { view, sec: sec || '' } });
    this.sync();
  }

  async message(ev) {
    if (!this.frame || ev.source !== this.frame.contentWindow) return;
    const d = ev.data;
    if (!d || d.type !== TYPE) return;
    if (d.ready) { this.sync(); return; }
    if (d.bars) {
      const top = Math.max(0, Math.round(Number(d.bars.top) || 0));
      const bottom = Math.max(0, Math.round(Number(d.bars.bottom) || 0));
      if (top !== this.bars.top || bottom !== this.bars.bottom) { this.bars = { top, bottom }; this.sync(); }
      return;
    }
    if (d.show === 'home' || d.show === 'panel') {
      this.view = d.show === 'home' && this.morphOn() ? 'home' : 'panel';
      this.raised = false;
      this.sync();
      return;
    }
    if (typeof d.raise === 'boolean') {
      if (d.raise !== this.raised) { this.raised = d.raise; this.sync(); }
      return;
    }
    if (d.home === 'edit' || d.home === 'yaml-toggle') {
      const panel = this.morph && this.morph.shadowRoot && this.morph.shadowRoot.querySelector('morph-panel');
      if (panel && typeof panel.chromeAct === 'function') panel.chromeAct(d.home);
      return;
    }
    if (d.menu) { this.dispatchEvent(new Event('hass-toggle-menu', { bubbles: true, composed: true })); return; }
    if (d.features) {
      try { this.info = { ...this.info, ...(await this._v.hass.callWS({ type: 'brain/shell' })) }; } catch (e) { /* the next press asks again */ }
      this.sync();
    }
  }
}

for (const k of PROPS) {
  Object.defineProperty(BrainShell.prototype, k, {
    configurable: true,
    get() { return this._v[k]; },
    set(v) {
      const first = k === 'hass' && !this._v.hass;
      this._v[k] = v;
      if (this.morph) this.morph[k] = v;
      if (first && this.isConnected && !this.info) this.start();
      if (k === 'narrow' && this.info) this.sync();
    },
  });
}

if (!customElements.get('brain-shell')) customElements.define('brain-shell', BrainShell);
