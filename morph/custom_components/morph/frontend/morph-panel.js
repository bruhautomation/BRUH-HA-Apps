// <morph-panel> — Morph in Home Assistant's sidebar.
//
// A custom panel, not an iframe: it is handed the live `hass` object, so
// every card reacts to the house as it changes and any Lovelace card can be
// hosted untouched. The design is docs/design/morph-ui.md; the rules that
// matter most here are §1's: nothing floats over anything, one grammar
// (tap · slide · hold), no chrome, and in Edit, tap edits and HOLD TALKS TO
// BRAIN.
//
// Data: `morph/load` returns the dashboard mirror, Morph's own state
// (settings, learning, suggestions) and brAIn's published feed (findings,
// the situation sentence). `morph/subscribe` says which of those moved, so a
// change brAIn makes appears without a reload. Writes are `morph/request`,
// which the add-on turns into a git commit — so every change has an Undo.
//
// A Tell starts with a PICTURE: the moment something is held, snap.js draws
// it and `morph/shot` files the PNG where brAIn reads it first, so "this"
// means what is on the screen. The box is a conversation (each turn keeps
// its question, its answer and its before/after pictures), it shows what
// brAIn is doing while it does it, and when brAIn says the request needs
// Morph's own code changed it asks whether to send that as an issue.

import { Engine } from './engine.js';
import { CSS as STYLES, FONTS_URL } from './styles.js';
import { TYPES, typeOf } from './cards.js';
import * as history from './history.js';
import * as snap from './snap.js';
import * as upc from './upcoming.js';
import { esc, mix, hue, HUES, clock, ago, friendly, shortName, lightColor, SPARK, MARK, domainOf, UNAVAILABLE, fmt, climateDoing } from './util.js';

const HOLD_MS = 540;
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
// Uses waiting to be sent when the connection is down; past this the oldest go.
// The card files this page has imported, by name, and the version each was
// imported at. Module-level, so a panel element rebuilt by Home Assistant
// still knows what the page already defined.
const IMPORTED = new Map();
const REDEFINED = /already been (used|defined)|already defined/i;
// Words that ask for a change to the DASHBOARD rather than a question for
// the house: a change verb, then something the page is made of.
const DASH_CHANGE = /\b(add|remove|delete|hide|show(?! me\b)|move|put|rename|make|change|resize|swap|replace|get rid of|bring back|restore|reorder|group|split|merge|drop|take (?:out|off|away))\b[\s\S]*\b(card|cards|tile|tiles|section|sections|dashboard|greeting|header|story|coming up|timeline|scenes? line|layout|column|columns|widget|chart|graph|morph|this page|the page|screen)\b/i;
const USAGE_KEEP = 400;

// Why a change to Morph's own code is paused (the add-on's morphcode.py):
// its own file changed in the update, or another of Morph's modules it
// builds on did.
function pausedWhy(r) {
  if (r && r.why === 'others' && (r.moved || []).length) return `Morph was updated and its ${r.moved.slice(0, 3).join(', ')}${r.moved.length > 3 ? ' and more' : ''} changed, which this change builds on. Morph’s own ${r.name} is running until brAIn checks the change still fits.`;
  return 'Morph’s own is running until the change is made again on the new version.';
}

class MorphPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.s = {
      edit: false, page: 'home', view: null, fading: null, previews: {}, memberPreview: null,
      tell: null, secEdit: null, ask: null, story: {}, confirm: {}, hold: null, add: null,
      sugNo: null, toast: null, yaml: null, hist: null,
    };
    this.data = null;
    this.dash = null;
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
    this._hass = h;
    if (first) this.boot();
    else this.schedule();
    this.llCards.forEach((el) => { try { el.hass = h; } catch (e) { /* a card that throws on hass is reported when it draws */ } });
  }
  get hass() { return this._hass; }
  set narrow(v) { this._narrow = v; this.schedule(); }
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
  }

  stopLive() {
    if (!this._live) return;
    this._live = false;
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
    clearInterval(this._tick);
    clearInterval(this._since);
    document.removeEventListener('visibilitychange', this._onHide);
    window.removeEventListener('pagehide', this._onHide);
  }

  boot() {
    if (this.engine) return;
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLES}</style><div class="morph t-dark" data-morph-root><div class="scroll" style="height:100vh;overflow-y:auto;overflow-x:hidden"><div class="wrap">
<div data-region="bar"></div><div data-region="lede"></div><div data-region="top"></div><div data-region="upcoming"></div><div data-region="scenes"></div><div data-region="notes"></div>
<div data-region="board"><div data-board></div></div><div data-region="settings"></div></div></div></div>`;
    if (!document.querySelector('link[data-morph-fonts]')) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = FONTS_URL; l.dataset.morphFonts = '1'; document.head.appendChild(l);
    }
    this.$ = (sel) => root.querySelector(sel);
    this.rootEl = this.$('[data-morph-root]');
    this.engine = new Engine(this.rootEl);
    this.engine.scrollEl = this.$('.scroll');
    this.engine.onSettle = () => this.audit();
    history.setOnData(() => this.schedule());
    window.addEventListener('morph-data', () => this.schedule());
    this.bindEvents();
    this.ro = new ResizeObserver(() => { cancelAnimationFrame(this._ro); this._ro = requestAnimationFrame(() => this.engine.layout(false, true)); });
    this.ro.observe(this.$('[data-board]'));
    this.load();
    this.startLive();
    try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { this.engine.invalidate(); this.engine.layout(false, true); }); } catch (e) { /* no font API */ }
  }

  async load() {
    try {
      const d = await this.hass.callWS({ type: 'morph/load' });
      const rev = d && d.mirror && d.mirror.revision;
      this.data = d;
      if (!this.s.edit || !this.dash || rev !== this.revision) {
        this.dash = (d.mirror && d.mirror.dashboard) || null;
        this.revision = rev;
      }
      this.loadModules((d.mirror && d.mirror.card_modules) || []);
      this.schedule();
    } catch (e) {
      this.data = { error: String((e && e.message) || e) };
      this.schedule();
    }
  }

  loadModules(mods) {
    const base = (this._panel && this._panel.config && this._panel.config.cards_url) || '/morph_cards';
    mods.forEach((m) => {
      const key = m.name + '@' + m.v;
      if (this.loadedModules.has(key)) return;
      this.loadedModules.add(key);
      const before = IMPORTED.get(m.name);
      IMPORTED.set(m.name, m.v);
      import(`${base}/${encodeURIComponent(m.name)}?v=${m.v}`).then(() => this.schedule()).catch((e) => {
        // A custom element cannot be defined twice on one page. When a card's
        // file changes, its new version runs and its define() throws — that
        // is the browser keeping the old one until the page reloads, not a
        // fault in the card, so it is said and offered rather than reported.
        if (before != null && before !== m.v && REDEFINED.test(String((e && e.message) || e))) {
          this.toast(`${m.name} changed. Reload the page to see the new version.`, null, 'reload');
          return;
        }
        this.report('card', `Card code ${m.name} failed to load: ${e.message || e}`, String(e && e.stack || ''), 'custom');
      });
    });
  }

  schedule() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this.render(); });
  }

  settings() { return (this.data && this.data.state && this.data.state.settings) || {}; }
  admin() { return !!(this.data && this.data.admin); }

  // -------------------------------------------------------------- render

  render() {
    if (!this.engine || !this.hass) return;
    const set = this.settings();
    const theme = set.theme && set.theme !== 'auto' ? set.theme : (this.hass.themes && this.hass.themes.darkMode === false ? 'light' : 'dark');
    this.rootEl.className = `morph t-${theme}${set.reduce_motion ? ' reduce' : ''}`;
    // boot.js draws its outline in the theme this page last used.
    if (theme !== this._savedTheme) { this._savedTheme = theme; try { localStorage.setItem('morph.theme', theme); } catch (e) { /* storage refused */ } }
    this.engine.forceReduce = !!set.reduce_motion;
    this.region('bar', this.barHtml());
    this.region('lede', this.updateHtml() + (this.s.edit && this.s.page === 'home' ? `<div class="lede">Editing · <b>hold anything to tell brAIn what to change</b> · drag a section by its title · tap a card to rename, resize or remove it</div>` : '') + this.activityHtml());
    if (this.s.page === 'settings') {
      ['top', 'upcoming', 'scenes', 'notes'].forEach((r) => this.region(r, ''));
      this.$('[data-region="board"]').hidden = true;
      this.region('settings', this.settingsHtml());
      return;
    }
    this.$('[data-region="board"]').hidden = false;
    this.region('settings', '');
    if (!this.data) { this.region('top', '<p class="sm">Opening Morph…</p>'); return; }
    this.readyOnce();
    if (this.data.error) { this.region('top', `<div class="banner bad">Morph could not load: ${esc(this.data.error)}. Is the Morph add-on started?</div>`); return; }
    if (!this.dash) { this.region('top', `<div class="banner">Morph's add-on has not written a dashboard yet. Start the Morph add-on; it builds the first one from your floors and rooms.</div>`); return; }
    const dash = this.dash;
    this.region('top', this.topHtml(dash));
    // Coming up is not rebuilt under a finger, or while it is gliding to
    // where it was let go: the rebuild would land it before it arrives.
    if (!this.upcFrozen()) this.region('upcoming', dash.coming_up !== false ? this.upcomingHtml() : '');
    this.region('scenes', (dash.scenes || []).length ? this.scenesHtml(dash) : '');
    this.region('notes', this.topNotesHtml());
    this.renderBoard(dash);
    this.tickSince();
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
  // integration), or a restart of Home Assistant (the add-on is newer than
  // the integration it has loaded, so a reload alone would not finish it).
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
    if (this.admin() && addon && integ && addon !== integ && addon !== 'dev') {
      return bar(`Morph ${addon} is installed, but Home Assistant is still running Morph ${integ}. Restart Home Assistant to finish the update.`, '');
    }
    return '';
  }

  region(name, html) {
    const el = this.$(`[data-region="${name}"]`);
    if (!el) return;
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

  barHtml() {
    const now = new Date();
    const date = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }) + ' · ' + clock(now);
    const menu = this._narrow ? `<button type="button" class="menu" data-act="menu" aria-label="Open the sidebar"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>` : '';
    const admin = this.admin();
    let right = '';
    if (this.s.page === 'settings') right = `<button type="button" class="go" data-act="page" data-v="home" style="font-size:14px;color:var(--teal)">Back to the dashboard</button>`;
    else if (this.s.edit) right = `<button type="button" class="go" data-act="yaml-toggle" style="margin-left:10px;padding:0 4px;font-size:13px;color:var(--muted)">${this.s.yaml ? 'Hide YAML' : 'YAML'}</button><button type="button" class="go" data-act="edit" style="margin-left:6px;padding:0 4px;font-size:14px;color:var(--teal)">Done</button>`;
    else if (admin) right = `<button type="button" class="go" data-act="edit" style="display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:0 4px;font-size:13px;color:var(--muted)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>Edit</button>`;
    const gear = admin && this.s.page !== 'settings' ? `<button type="button" class="go" data-act="page" data-v="settings" aria-label="Morph settings" style="margin-left:6px;padding:0 4px;color:var(--muted)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg></button>` : '';
    const toast = this.s.toast ? `<span class="rise bartoast">${esc(this.s.toast.text)}${this.s.toast.sha ? ` <button type="button" class="wd go" data-act="undo-commit" data-v="${esc(this.s.toast.sha)}" style="min-height:24px">Undo</button>` : ''}${this.s.toast.action === 'reload' ? ` <button type="button" class="wd go" data-act="reload-page" style="min-height:24px">Reload</button>` : ''}</span>` : '';
    const yaml = this.s.edit && this.s.yaml != null ? `<div style="display:flex;flex-direction:column;gap:8px;margin-top:14px"><span class="label">Raw configuration · /config/morph/dashboard.yaml</span><textarea class="code-ed" data-keep="yaml" spellcheck="false" aria-label="dashboard.yaml">${esc(this.s.yaml)}</textarea><div class="row"><button type="button" class="wd go" data-act="yaml-save">Save YAML</button><span class="small">Saved as one commit; Undo puts it back.</span></div></div>` : '';
    // On a phone a toast takes the date's place: the bar is one row and
    // Edit's own buttons must stay on it.
    const dateHtml = this.s.toast && this._narrow ? '' : `<span class="date">${esc(date)}</span>`;
    return `<div class="bar">${menu}<span class="brand">${MARK(16)}MORPH</span>${toast}<span class="flex1"></span>${dateHtml}${right}${gear}</div>${yaml}`;
  }

  // ---------------------------------------------------------------- the top

  greeting() {
    const h = new Date().getHours();
    return h < 5 ? 'Good night.' : h < 12 ? 'Good morning.' : h < 18 ? 'Good afternoon.' : 'Good evening.';
  }

  // The story: brAIn's sentence about right now when it has one, then what
  // the house itself says — each underlined phrase folds open in place.
  storyFacts(dash) {
    const H = this.hass; const facts = [];
    const sit = this.data.brain && this.data.brain.situation;
    if (sit && sit.sentence && (!sit.at || Date.now() / 1000 - sit.at < 3600)) facts.push({ id: 'brain', html: esc(sit.sentence) });
    const floorsLights = [];
    (dash.floors || []).forEach((fl) => {
      const on = [];
      this.floorEntities(fl).forEach((e) => { if (domainOf(e) === 'light' && H.states[e] && H.states[e].state === 'on' && !(H.states[e].attributes.entity_id || []).length) on.push(e); });
      if (on.length) floorsLights.push({ fl, on });
    });
    if (floorsLights.length) {
      const words = floorsLights.map((x) => `${x.on.length} on ${x.fl.title.toLowerCase().startsWith('whole') ? 'around the house' : (/^(outside|garden|yard)/i.test(x.fl.title) ? 'outside' : x.fl.title.toLowerCase())}`);
      facts.push({ id: 'lights', html: `Lights: <button type="button" class="nm hi" data-act="story" data-v="lights" aria-expanded="${!!this.s.story.lights}">${esc(words.join(', '))}</button>.`,
        more: floorsLights.map((x) => `${esc(x.fl.title)} — ${x.on.map((e) => esc(friendly(H, e))).join(', ')} <button type="button" class="wd go" data-act="svc" data-domain="light" data-service="turn_off" data-data="${esc(JSON.stringify({ entity_id: x.on }))}" style="min-height:28px">Turn off ${esc(x.fl.title.toLowerCase())}</button>`).join('<br>') });
    }
    const temps = Object.values(H.states).filter((s) => s.attributes.device_class === 'temperature' && domainOf(s.entity_id) === 'sensor' && !isNaN(parseFloat(s.state)) && this.onDash(s.entity_id));
    if (temps.length) {
      const vals = temps.map((s) => parseFloat(s.state)).sort((a, b) => a - b);
      const med = vals[Math.floor(vals.length / 2)];
      const unit = temps[0].attributes.unit_of_measurement || '°';
      const running = Object.values(H.states).filter((s) => domainOf(s.entity_id) === 'climate' && ['heating', 'cooling'].includes(s.attributes.hvac_action));
      facts.push({ id: 'temp', html: `Inside it's about <span class="hi">${esc(fmt(med, unit))}</span>${running.length ? `, and ${esc(running.map((s) => friendly(H, s.entity_id)).join(' and '))} ${running.length > 1 ? 'are' : 'is'} ${esc(running[0].attributes.hvac_action)}` : ''}.` });
    }
    const open = Object.values(H.states).filter((s) => this.onDash(s.entity_id) && ((domainOf(s.entity_id) === 'binary_sensor' && ['door', 'window', 'garage_door', 'opening', 'moisture', 'smoke', 'gas'].includes(s.attributes.device_class) && s.state === 'on') || (domainOf(s.entity_id) === 'lock' && s.state === 'unlocked') || (domainOf(s.entity_id) === 'cover' && s.attributes.device_class === 'garage' && s.state === 'open')));
    if (open.length) facts.push({ id: 'open', html: `<button type="button" class="nm warn" data-act="story" data-v="open" aria-expanded="${!!this.s.story.open}">${esc(open.length === 1 ? friendly(H, open[0].entity_id) + ' is ' + (open[0].state === 'unlocked' ? 'unlocked' : open[0].attributes.device_class === 'moisture' ? 'wet' : 'open') : open.length + ' things are open')}</button>.`,
      more: open.map((s) => `${esc(friendly(H, s.entity_id))} — since ${esc(clock(s.last_changed))} <button type="button" class="wd go" data-act="reveal" data-v="${esc(s.entity_id)}" style="min-height:28px">Show me</button>`).join('<br>') });
    const playing = Object.values(H.states).filter((s) => domainOf(s.entity_id) === 'media_player' && s.state === 'playing' && this.onDash(s.entity_id));
    if (playing.length) facts.push({ id: 'media', html: `${esc(friendly(H, playing[0].entity_id))} is playing${playing[0].attributes.media_title ? ' <span class="hi">' + esc(playing[0].attributes.media_title) + '</span>' : ''}.` });
    const away = Object.values(H.states).filter((s) => domainOf(s.entity_id) === 'person' && s.state !== 'home' && !UNAVAILABLE.includes(s.state));
    if (away.length) facts.push({ id: 'people', html: `${esc(away.map((s) => friendly(H, s.entity_id)).join(' and '))} ${away.length > 1 ? 'are' : 'is'} away.` });
    const findings = (this.data.brain && this.data.brain.findings) || [];
    const open_ = findings.filter((f) => ['open', 'needs_you'].includes(f.status));
    if (open_.length) facts.push({ id: 'brainq', html: `brAIn has <button type="button" class="nm hi" data-act="story" data-v="brainq" aria-expanded="${!!this.s.story.brainq}">${open_.length} thing${open_.length > 1 ? 's' : ''} for you</button>.`, more: open_.slice(0, 6).map((f) => esc(f.text)).join('<br>') });
    if (!facts.length) facts.push({ id: 'quiet', html: 'Everything is quiet.' });
    return facts;
  }

  topHtml(dash) {
    const holding = (k) => (this.s.hold === k ? ' holding' : '');
    const facts = dash.story !== false ? this.storyFacts(dash) : [];
    const story = facts.length ? `<div class="holdable${holding('top:story')}" data-hold="story"><p class="story">${facts.map((f) => `${f.html} ${f.more && this.s.story[f.id] ? `<span class="storyx rise" data-exp="${f.id}">${f.more}</span>` : ''}`).join(' ')}</p>${this.tellBox('story')}</div>` : '';
    const edit = this.s.edit;
    let ask = '';
    if (dash.ask !== false || edit) {
      const a = this.s.ask;
      const sugs = !a ? (edit ? TELL_SUGS.dashboard : ['Why is it warm upstairs?', 'What’s left on?', 'Is everything locked?']) : [];
      ask = `<div data-ask="1" style="display:flex;flex-direction:column;gap:6px;margin-top:6px">
<label class="askrow">${SPARK}<input class="askin" type="text" data-keep="ask" data-act-enter="ask" placeholder="${edit ? 'Tell brAIn how to change this dashboard…' : 'Ask or tell the house…'}" aria-label="${edit ? 'Tell brAIn how to change this dashboard' : 'Ask or tell the house'}"></label>
${this.tellBox('dashboard')}
${sugs.length && !(this.s.tell && this.s.tell.kind === 'dashboard') ? `<div class="sugs">${sugs.map((s) => `<button type="button" class="wd" data-act="ask-sug" data-v="${esc(s)}" style="font-size:14px;min-height:34px">${esc(s)}</button>`).join('')}</div>` : ''}
${a ? `<div class="answer rise"><span class="small">${esc(a.q)}</span><p>${esc(a.busy ? 'Thinking…' : a.answer || '')}</p>${(a.show || []).length ? `<div class="row" style="flex-wrap:wrap;gap:0 20px">${a.show.map((x) => `<button type="button" class="wd go" data-act="reveal-card" data-v="${esc(x.id)}" style="font-size:15px">Show me ${esc(x.name)}</button>`).join('')}</div>` : ''}${!a.busy && this.admin() ? `<div class="row"><button type="button" class="wd" data-act="ask-tell" style="font-size:14px;min-height:34px">Change the dashboard instead</button><span class="small">The house’s assistant answers; only this changes Morph.</span></div>` : ''}</div>` : ''}</div>`;
    }
    return `<section aria-label="Now" style="display:flex;flex-direction:column;gap:14px;max-width:980px">${dash.greeting !== false ? `<h1 class="hello">${esc(this.greeting())}</h1>` : ''}${this.data.state && this.data.state.note ? `<div class="banner">${esc(this.data.state.note)}</div>` : ''}${story}${ask}</section>`;
  }

  // Coming up: a fixed reading point with the next day sliding behind it
  // (upcoming.js). The cursor is kept as a TIME (`upcAt`, null for now), so
  // something you stopped on stays under the line as the minutes pass.
  upcomingHtml() {
    const reg = this.$('[data-region="upcoming"]');
    const w = (reg && reg.clientWidth) || (this.rootEl && this.rootEl.clientWidth) || window.innerWidth;
    const m = upc.model(this.hass, Date.now(), w < 640 ? 0.9 : 1.25);
    if (!m.stacks.length && !m.durs.length && !this.s.edit) { this._upc = null; return ''; }
    this._upc = m;
    const holding = this.s.hold === 'top:upcoming' ? ' holding' : '';
    return `<div class="holdable${holding}" data-hold="upcoming" aria-label="Coming up">${upc.html(m, this.upcCursor(m))}${this.tellBox('upcoming')}</div>`;
  }

  upcCursor(m) { return this.s.upcAt == null ? 0 : upc.clampC(m, (this.s.upcAt - m.base) / 60000); }

  upcFrozen() { return !!(this.upcD || this._upcWc != null || (this._upcGlide && performance.now() < this._upcGlide)); }

  upcRegion() { return this.$('[data-region="upcoming"]'); }

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

  // -------------------------------------------------------- notes in place

  // brAIn's findings and Morph's own suggestions, placed in the section
  // their entity lives in. Anything that belongs nowhere goes at the top.
  notes() {
    const out = {};
    const top = [];
    const H = this.hass;
    const secFor = (eid) => {
      if (!eid || !this.dash) return null;
      let found = null;
      this.eachSection((sec) => { if (!found && this.sectionEntities(sec).includes(eid)) found = sec.id; });
      if (found) return found;
      const reg = H.entities && H.entities[eid];
      const area = reg && (reg.area_id || (reg.device_id && H.devices && H.devices[reg.device_id] && H.devices[reg.device_id].area_id));
      if (area) this.eachSection((sec) => { if (!found && sec.area === area) found = sec.id; });
      return found;
    };
    const findings = ((this.data && this.data.brain && this.data.brain.findings) || []).filter((f) => ['open', 'needs_you', 'fixed', 'failed', 'planned'].includes(f.status));
    findings.slice(0, 20).forEach((f) => {
      const n = { key: 'f' + f.ts, kind: 'finding', f };
      const sid = secFor(f.entity_id);
      if (sid) (out[sid] = out[sid] || []).push(n); else if (f.severity !== 'info') top.push(n);
    });
    ((this.data && this.data.state && this.data.state.suggestions) || []).forEach((g) => {
      const n = { key: 'g' + g.id, kind: 'suggestion', g };
      let sid = g.section || null;
      if (g.card) this.eachSection((sec) => { if (this.sectionCards(sec).some((c) => c.id === g.card)) sid = sec.id; });
      if (sid) (out[sid] = out[sid] || []).push(n); else top.push(n);
    });
    return { bySec: out, top };
  }

  // A note reads as brAIn speaking, not as an alert: a soft violet wash, the
  // sentence first, then a row of words — the first one the yes, in ink,
  // the rest quiet. A serious finding warms the wash; nothing shouts.
  noteHtml(n) {
    const wash = (c) => `background:linear-gradient(100deg, ${mix(c, 11)}, ${mix('var(--teal)', 4)} 70%, transparent)`;
    const act = (attrs, label, first) => `<button type="button" class="wd${first ? ' first' : ''}" ${attrs}>${esc(label)}</button>`;
    const shell = (who, color, say, sub, acts) => `<div class="note bnote rise" data-ctl="1" style="${wash(color)}">${SPARK}<div class="bnin"><span class="sr">${esc(who)}: </span><span class="say">${esc(say)}</span>${sub}${acts ? `<div class="acts">${acts}</div>` : ''}</div></div>`;
    if (n.kind === 'finding') {
      const f = n.f;
      const color = f.severity === 'critical' ? 'var(--rose)' : f.severity === 'warning' ? 'var(--amber)' : 'var(--violet)';
      const answers = (f.answers || []).slice(0, 3);
      const acts = answers.length && this.admin() ? answers.map((a, i) => act(`data-act="finding" data-ts="${f.ts}" data-v="${esc(a.action)}"`, a.label, i === 0)).join('') : '';
      return shell('brAIn noticed', color, f.text, f.detail ? `<span class="sub">${esc(f.detail)}</span>` : '', acts);
    }
    const g = n.g;
    const tellState = g.tell ? this.tellStatus[g.tell] : null;
    let acts = '';
    let extra = '';
    if (g.status === 'doing') {
      extra = `<span class="sub">${esc((tellState && (tellState.say || (tellState.steps || []).slice(-1).map((x) => x.t)[0])) || 'brAIn is on it…')}</span>`;
    } else if (this.s.sugNo === g.id) {
      extra = `<input class="fld" type="text" data-keep="sugno" placeholder="Why not? (optional — it teaches Morph)">`;
      acts = act(`data-act="sug" data-v="no" data-id="${esc(g.id)}"`, "Don't suggest it again", true) + act('data-act="sug-cancel"', 'Cancel');
    } else if (this.admin()) {
      // A change to Morph itself is made here like any other; sending it
      // as an issue without making it is the second word.
      acts = act(`data-act="sug" data-v="do" data-id="${esc(g.id)}"`, 'Do it', true)
        + (g.kind === 'code' ? act(`data-act="sug" data-v="send" data-id="${esc(g.id)}"`, 'Send as issue') : act(`data-act="sug" data-v="not_now" data-id="${esc(g.id)}"`, 'Not now'))
        + act(`data-act="sug-no" data-id="${esc(g.id)}"`, 'No');
    }
    const sub = (g.why ? `<span class="sub">${esc(g.why)}</span>` : '') + (g.last_error ? `<span class="sub" style="color:var(--rose)">Last try: ${esc(g.last_error)}</span>` : '') + extra;
    return shell(g.kind === 'code' ? 'A change to Morph itself' : 'Morph suggests', 'var(--violet)', g.title, sub, acts);
  }

  topNotesHtml() {
    if (!this.data || !this.dash) return '';
    const { top } = this.notes();
    const problems = this.admin() ? this.problemsHtml() : '';
    if (!top.length && !problems) return '';
    return `${problems}<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">${top.slice(0, 6).map((n) => this.noteHtml(n)).join('')}</div>`;
  }

  // What dashboard.yaml says that Morph could not use. A file that does not
  // parse leaves the last good dashboard on screen (`held`), so this line is
  // the only sign the file on disk is not what you are looking at.
  problemsHtml() {
    const m = (this.data && this.data.mirror) || {};
    const list = (m.problems || []).slice(0, 4);
    return this.codeProblemsHtml() + (list.length ? this.yamlProblemsHtml(m, list) : '');
  }

  // Which Morph is running. The add-on and Home Assistant's half of Morph
  // update separately: an add-on update reaches the service and this page
  // on the next reload, while the integration Home Assistant has loaded
  // stays the old one until Home Assistant restarts.
  versionHtml(st) {
    const addon = String(st.version || '');
    const ha = String((this._panel && this._panel.config && this._panel.config.version) || '');
    if (!addon) return '';
    const stale = ha && ha !== addon && addon !== 'dev';
    return `<p class="small" style="margin:0">Morph ${esc(addon)}</p>${stale ? `<p class="sm" style="color:var(--amber);margin:0">Home Assistant is still running Morph ${esc(ha)}’s integration. Restart Home Assistant to finish the update.</p>` : ''}`;
  }

  // A change to Morph's own code that did not load (boot.js fell back), or
  // that an update paused. Both say what is running and offer the fix.
  codeProblemsHtml() {
    const out = [];
    const note = (head, body, acts) => `<div class="note" style="margin-bottom:12px;background:${mix('var(--amber)', 9)};box-shadow:inset 0 0 0 1px ${mix('var(--amber)', 25)}"><span class="small" style="color:var(--amber);font-weight:700">${esc(head)}</span>${body ? `<span class="sm">${esc(body)}</span>` : ''}${acts ? `<div class="acts">${acts}</div>` : ''}</div>`;
    if (window.__morphFallback) out.push(note('A change to Morph itself did not load, so Morph is running its own copy.', window.__morphFallback, '<button type="button" class="wd strong" data-act="page" data-v="settings">See the changes</button>'));
    const st = (this.data && this.data.state) || {};
    const names = (st.code || []).filter((r) => r.status === 'paused').map((r) => r.name).slice(0, 3);
    const why = (name) => pausedWhy((st.code || []).find((r) => r.name === name));
    // "Make it again" opens brAIn's box HERE, and the note stays until the
    // box is closed: once brAIn has written the copy it is no longer paused,
    // and a note that vanished with the box in it took the result with it.
    const t = this.s.tell;
    const mine = t && t.kind === 'code' ? t.id : '';
    if (mine && !names.includes(mine)) names.push(mine);
    names.forEach((name) => {
      if (name === mine) {
        const ph = (t.state || {}).phase;
        const asks = ph === 'done' && t.state.question && t.state.answered == null;
        const head = asks ? `brAIn needs you to choose how to bring your change to Morph’s ${name} onto the new version.` : ph === 'done' ? `Your change to Morph’s ${name}` : ph === 'failed' ? `Your change to Morph’s ${name} is still paused.` : `brAIn is making your change to Morph’s ${name} again.`;
        out.push(note(head, asks ? 'The update rewrote the part your change was in. It stays paused, and Morph’s own keeps running, until you pick.' : ph === 'done' || ph === 'failed' ? '' : 'Morph’s own keeps running until it is done. You can leave this page; it carries on.', this.tellBox('code', name)));
        return;
      }
      const running = (st.activity || []).find((a) => a.kind === 'code' && a.target === name && !['done', 'failed'].includes((this.tellStatus[a.id] || {}).phase));
      if (running) {
        out.push(note(`brAIn is making your change to Morph’s ${name} again.`, 'Morph’s own keeps running until it is done.', `<button type="button" class="wd go" data-act="activity-open" data-v="${esc(running.id)}">Show</button>`));
        return;
      }
      // The press is remembered in state, not written onto the button: the
      // panel redraws on every state change in the house, and a button
      // edited in place was back to "Make it again" before anyone saw it.
      const r = this.s.redo && this.s.redo.name === name ? this.s.redo : null;
      if (r && !r.error) {
        out.push(note(`Morph was updated, so your change to its ${name} is paused.`, why(name), `<div class="working"><span class="pulse"></span><span>Handing it to brAIn…</span><span class="small" data-since="${r.at}"></span></div>`));
        return;
      }
      const failed = r && r.error ? `<p class="sm" style="color:var(--rose);margin:0">brAIn did not start: ${esc(r.error)}</p>` : '';
      out.push(note(`Morph was updated, so your change to its ${name} is paused.`, why(name), `${failed}<button type="button" class="wd go" data-act="code-redo" data-v="${esc(name)}">${failed ? 'Try again' : 'Make it again'}</button><button type="button" class="wd" data-act="code-reset" data-v="${esc(name)}">Use Morph’s own</button>`));
    });
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
    const out = [];
    this.sectionCards(sec).forEach((c) => {
      if (c.entity) out.push(c.entity);
      (c.entities || []).forEach((e) => out.push(e));
      if (c.type === 'light_group' && this.hass.states[c.entity]) (this.hass.states[c.entity].attributes.entity_id || []).forEach((e) => out.push(e));
    });
    return out;
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

  // A room is asleep when its mode says so: a select set to Sleep, or a
  // sleep switch that is on. The time is when it went to sleep.
  asleepSince(sec) {
    const H = this.hass;
    for (const e of this.sectionEntities(sec)) {
      const s = H.states[e]; if (!s) continue;
      const d = domainOf(e);
      const isSleep = ((d === 'input_select' || d === 'select') && /^(sleep|sleeping|asleep|night)$/i.test(s.state))
        || ((d === 'input_boolean' || d === 'switch' || d === 'binary_sensor') && /sleep/i.test(e + ' ' + (s.attributes.friendly_name || '')) && s.state === 'on');
      if (isSleep) return s.last_changed;
    }
    return null;
  }

  // Somebody in the room, read off its motion, occupancy and presence
  // sensors; null when the room has none.
  presence(sec) {
    const H = this.hass;
    const ss = this.sectionEntities(sec).map((e) => H.states[e]).filter((s) => s && domainOf(s.entity_id) === 'binary_sensor' && ['motion', 'occupancy', 'presence'].includes(s.attributes.device_class) && !UNAVAILABLE.includes(s.state));
    if (!ss.length) return null;
    return ss.some((s) => s.state === 'on');
  }

  // The model the engine lays out: sections with groups of items, each item
  // carrying its type's layout parameters.
  buildModel(dash, notes) {
    const sections = [];
    (dash.floors || []).forEach((fl, fi) => {
      (fl.sections || []).forEach((sec) => {
        if (sec.hidden && !this.s.edit) return;
        const groups = [];
        const ns = notes.bySec[sec.id] || [];
        (sec.groups || []).forEach((g, gi) => {
          const items = (g.cards || []).map((c) => { const t = typeOf(c).item; return { id: c.id, span: c.span || t.span, grow: Math.max(c.span || 0, t.grow || t.span), dir: t.dir, want: t.want, full: !!t.full, hk: t.hk || 'x:' + c.id }; });
          if (this.s.edit && gi === sec.groups.length - 1) items.push({ id: `add@${sec.id}@${gi}`, span: 1, grow: 1, dir: 'down', want: 3, hk: 'x:add' });
          groups.push({ key: sec.id + ':' + gi, label: g.label || '', items });
        });
        if (this.s.edit && !(sec.groups || []).length) groups.push({ key: sec.id + ':new', label: '', items: [{ id: `add@${sec.id}@0`, span: 1, grow: 1, dir: 'down', want: 3, hk: 'x:add' }] });
        // A note follows the room's own tiles: the room first, then what
        // brAIn has to say about it (the prototype's order).
        if (ns.length) groups.push({ key: sec.id + ':notes', label: '', items: ns.map((n) => ({ id: 'n:' + sec.id + ':' + n.key, span: 4, full: true, grow: 4, hk: 'x:n' })) });
        sections.push({ id: sec.id, w: sec.width || 2, floor: fi, floorId: fl.id, groups });
      });
      if (this.s.edit) sections.push({ id: '__new@' + fi, w: 2, floor: fi, floorId: fl.id, groups: [] });
    });
    return { sections };
  }

  renderBoard(dash) {
    const board = this.$('[data-board]');
    const notes = this.notes();
    const model = this.buildModel(dash, notes);
    this.engine.model = model;
    this.engine.openId = this.s.view ? this.s.view.id : null;
    this.engine.openMode = this.s.view ? this.s.view.mode : '';
    this.engine.fadingId = this.s.fading;
    const want = new Set();
    // floors
    (dash.floors || []).forEach((fl, fi) => {
      const key = 'fl:' + fi; want.add(key);
      let el = board.querySelector(`[data-floor="${fi}"]`);
      if (!el) { el = document.createElement('div'); el.className = 'flh'; el.setAttribute('data-floor', String(fi)); el.dataset.key = key; el.dataset.hold = 'floor:' + fl.id; board.appendChild(el); }
      el.style.background = this.s.hold === 'top:floor:' + fl.id ? mix('var(--violet)', 9) : 'transparent';
      const facts = this.floorFacts(fl);
      const html = `<div data-flin="1"><div class="flrow"><h2>${esc(fl.title)}</h2><span class="flr"></span><span class="facts">${facts.map((f, i) => `<span style="color:${f.color || 'inherit'}">${esc(f.t)}</span>${i < facts.length - 1 ? '<span class="sep"> · </span>' : ''}`).join('')}</span></div>${this.tellBox('floor', fl.id)}</div>`;
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
      if (!sec) { // the ghost "Add section" in Edit
        el.querySelector('.secbg').style.cssText = 'background:transparent;box-shadow:inset 0 0 0 1.5px var(--line2)';
        this.setHtml(el.querySelector('.sechead'), `<button type="button" class="go" data-act="add-section" data-v="${esc(ms.floorId)}" style="display:inline-flex;align-items:center;gap:8px;font-size:16px;color:var(--muted)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>Add section</button>`);
        el.setAttribute('aria-label', 'Add section');
        return;
      }
      el.setAttribute('aria-label', sec.title);
      const h = hue(sec.color);
      let gc = null, gb = 0;
      this.sectionEntities(sec).forEach((e) => { const s = this.hass.states[e]; if (s && domainOf(e) === 'light' && s.state === 'on') { const b = (s.attributes.brightness || 255) / 2.55; if (b > gb) { gb = b; gc = lightColor(s); } } });
      const glow = gc ? `radial-gradient(110% 60% at 0% 0%, ${mix(gc, Math.round(5 + gb * 0.07))}, transparent 70%), ` : '';
      const sHold = this.s.hold === 'sec:' + sec.id || (this.s.tell && this.s.tell.kind === 'section' && this.s.tell.id === sec.id);
      const bg = el.querySelector('.secbg');
      bg.style.background = `${glow}radial-gradient(140% 90% at 100% 0%, ${mix(h, 11)}, transparent 60%), radial-gradient(120% 80% at 0% 100%, ${mix(h, 6)}, transparent 65%), linear-gradient(${mix(h, 4)}, ${mix(h, 4)}), var(--surface)`;
      bg.style.boxShadow = sHold ? `inset 0 0 0 2px ${mix('var(--violet)', 60)}` : this.s.edit ? `inset 0 0 0 1px ${mix(h, 40)}` : 'none';
      el.style.opacity = sec.hidden ? '0.45' : '1';
      const head = el.querySelector('.sechead');
      head.style.cursor = this.s.edit ? 'grab' : 'auto';
      head.style.touchAction = this.s.edit ? 'none' : 'auto';
      this.setHtml(head, this.secHeadHtml(sec));
      // groups
      ms.groups.forEach((g) => {
        const gk = g.key; want.add('g:' + gk);
        let gl = el.querySelector(`[data-glab="${CSS.escape(gk)}"]`);
        if (g.label) {
          if (!gl) { gl = document.createElement('div'); gl.className = 'glab'; gl.setAttribute('data-glab', gk); gl.dataset.key = 'g:' + gk; el.appendChild(gl); }
          gl.style.color = mix(h, 55, 'var(--quiet)');
          const grp = (sec.groups || [])[Number(gk.split(':').pop())];
          this.setHtml(gl, `<span>${esc(g.label)}</span>${grp && grp.note ? `<i>${esc(grp.note)}</i>` : ''}`);
        } else if (gl) gl.remove();
        g.items.forEach((it) => { want.add('t:' + it.id); this.renderTile(el, it, sec, notes); });
      });
    });
    // remove what is no longer there
    board.querySelectorAll('[data-key]').forEach((el) => {
      if (!want.has(el.dataset.key)) {
        if (el.dataset.key.startsWith('t:')) this.llCards.delete(el.dataset.key.slice(2));
        el.remove();
      }
    });
    this.engine.layout(!this._laidOut, false);
    this._laidOut = true;
  }

  sectionById(id) { let hit = null; this.eachSection((s) => { if (s.id === id) hit = s; }); return hit; }

  setHtml(el, html) { if (el.__html !== html) { el.__html = html; el.innerHTML = html; this.restoreTellText(el); } }

  secHeadHtml(sec) {
    const edit = this.s.edit;
    const open = this.s.secEdit === sec.id;
    const ents = this.sectionEntities(sec);
    // The room's line: asleep since when, how warm, and whether anyone is
    // there. What is on is already on the tiles below it.
    const temp = ents.map((e) => this.hass.states[e]).find((s) => s && s.attributes.device_class === 'temperature' && !isNaN(parseFloat(s.state)));
    const clim = temp ? null : ents.map((e) => this.hass.states[e]).find((s) => s && domainOf(s.entity_id) === 'climate' && s.attributes.current_temperature != null);
    const slept = this.asleepSince(sec);
    const here = slept ? null : this.presence(sec);
    const meta = [slept ? 'Asleep since ' + clock(slept) : '', temp ? fmt(temp.state, '°') : clim ? fmt(clim.attributes.current_temperature, '°') : '', here == null ? '' : here ? 'someone here' : 'empty'].filter(Boolean).join(' · ') + (sec.hidden ? ' · hidden' : '');
    let editor = '';
    if (edit && open) {
      const floors = (this.dash.floors || []);
      editor = `<div data-ctl="1" class="edit" style="flex-basis:100%;padding:10px 10px 8px 0">
<label class="flab">Title<input class="fld" type="text" data-keep="sec-title" data-act-change="sec-title" data-v="${esc(sec.id)}" value="${esc(sec.title)}"></label>
<div class="flab">Colour<div class="hues">${HUES.map((hn) => `<button type="button" class="hue" data-act="sec-hue" data-v="${esc(sec.id)}" data-h="${hn}" aria-label="${hn}" aria-pressed="${sec.color === hn}"><span style="background:var(--${hn});box-shadow:${sec.color === hn ? `0 0 0 3px var(--surface), 0 0 0 5px var(--${hn})` : 'none'}"></span></button>`).join('')}</div></div>
<div class="flab">Floor<div class="row" style="flex-wrap:wrap;gap:0 18px">${floors.map((f) => `<button type="button" class="wd" data-act="sec-floor" data-v="${esc(sec.id)}" data-f="${esc(f.id)}" aria-pressed="${f.sections.includes(sec)}" style="font-size:15px;font-weight:600;text-transform:none;letter-spacing:0">${esc(f.title)}</button>`).join('')}<button type="button" class="wd" data-act="sec-floor-new" data-v="${esc(sec.id)}" style="font-size:15px;text-transform:none;letter-spacing:0">New floor…</button></div></div>
<div class="flab">Width<div class="row" style="gap:0 18px">${[[1, 'Narrow'], [2, 'Medium'], [3, 'Wide'], [4, 'Widest']].map((x) => `<button type="button" class="wd" data-act="sec-width" data-v="${esc(sec.id)}" data-w="${x[0]}" aria-pressed="${(sec.width || 2) === x[0]}" style="font-size:15px;font-weight:600;text-transform:none;letter-spacing:0">${x[1]}</button>`).join('')}</div></div>
<div class="flab">Group<div class="row" style="gap:0 18px"><button type="button" class="wd" data-act="sec-group" data-v="${esc(sec.id)}" style="font-size:15px;text-transform:none;letter-spacing:0">Add a group</button></div></div>
<div class="row" style="gap:0 18px"><button type="button" class="go" data-act="sec-hide" data-v="${esc(sec.id)}" style="font-size:14px;color:var(--muted)">${sec.hidden ? 'Show section' : 'Hide section'}</button><button type="button" class="go" data-act="sec-remove" data-v="${esc(sec.id)}" style="font-size:14px;color:var(--rose)">Remove section</button></div></div>`;
    }
    const grip = edit ? '<svg aria-hidden="true" width="12" height="18" viewBox="0 0 12 18" style="flex-shrink:0;color:var(--quiet);margin-left:-8px"><path d="M3 3h.01M9 3h.01M3 9h.01M9 9h.01M3 15h.01M9 15h.01" stroke="currentColor" stroke-width="3" stroke-linecap="round"></path></svg>' : '';
    return `${grip}<div style="flex:1;min-width:0;display:flex;align-items:baseline;gap:12px"><h2>${esc(sec.title)}</h2><span class="secmeta">${esc(meta)}</span></div>${edit ? `<button type="button" class="go" data-act="sec-edit" data-v="${esc(sec.id)}" style="padding:0 8px;font-size:13px;color:var(--muted)">${open ? 'Close' : 'Edit'}</button>` : ''}${this.tellBox('section', sec.id)}${editor}`;
  }

  renderTile(secEl, it, sec, notes) {
    const id = it.id;
    let el = secEl.querySelector(`[data-tile="${CSS.escape(id)}"]`);
    if (!el) {
      el = document.createElement('div'); el.className = 'tile'; el.setAttribute('data-tile', id); el.dataset.key = 't:' + id;
      el.innerHTML = `<div class="mtile" data-mt="${esc(id)}"><div class="tc" data-tc="${esc(id)}"><div class="face" data-face="${esc(id)}"></div><div data-more></div></div></div>`;
      secEl.appendChild(el);
    }
    const mt = el.querySelector('.mtile');
    const face = el.querySelector('[data-face]');
    const moreEl = el.querySelector('[data-more]');
    // A note (brAIn finding or Morph suggestion) in place.
    if (id.startsWith('n:')) {
      const key = id.split(':').slice(2).join(':');
      const n = (notes.bySec[sec.id] || []).find((x) => x.key === key);
      mt.style.cssText = 'background:transparent;cursor:auto;touch-action:auto;user-select:text';
      this.setHtml(face, n ? this.noteHtml(n) : '');
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
    const st = card.entity ? this.hass.states[card.entity] : null;
    const open = this.s.view && this.s.view.id === id;
    const mode = open ? this.s.view.mode : '';
    const name = this.cardName(card, sec);
    const ctx = { hass: this.hass, card, st, sec, name, open, member: open ? this.s.view.member : null, H: (open && this.s.view.H) || (card.type === 'readings' ? (this.s.rfocus && this.s.rfocus[id] ? { focus: this.s.rfocus[id] } : {}) : {}), preview: this.s.previews[id] != null ? this.s.previews[id] : null, memberPreview: open ? this.s.memberPreview : null, confirm: this.s.confirm[id] && this.s.confirm[id].until > Date.now() ? this.s.confirm[id].text : '' };
    let faceHtml = '', moreHtml = '';
    try {
      ctx.accent = card.color ? hue(card.color) : T.accent(ctx);
      const slide = !this.s.edit && T.slide ? T.slide(ctx) : null;
      ctx.hint = this.s.edit ? (open ? '' : 'tap to edit · hold to tell brAIn') : (open || T.noOpen) ? '' : slide ? 'slide · tap · hold for more' : T.tap(ctx) ? 'tap · hold for more' : 'tap for more';
      faceHtml = T.face(ctx);
      // An opened card carries Morph's mark: one press opens the Tell box for
      // this card, so changing it does not mean going through Edit.
      const mark = this.admin() && !this.s.edit ? `<div class="tellmark" data-snap-skip="1"><button type="button" data-act="tell-card" data-v="${esc(id)}" aria-label="Tell brAIn what to change about ${esc(name)}" title="Tell brAIn what to change">${MARK(20)}</button></div>` : '';
      if (open && mode === 'adv') moreHtml = `<div class="more rise" data-ctl-scope="1">${mark}${T.more(ctx)}${T.host ? '' : this.moreInfoHtml(card, ctx)}</div>`;
      if (open && mode === 'edit') moreHtml = this.cardEditHtml(hit, name);
      if (open && mode === 'tell') moreHtml = `<div class="more">${this.tellBox('card', id)}</div>`;
    } catch (e) {
      faceHtml = `<div class="box"><b>${esc(name)}</b><span class="sm">This card could not be drawn.</span></div>`;
      this.report('card', String(e && e.message || e), String(e && e.stack || '').slice(0, 1500), card.type);
    }
    const holding = this.s.hold === id;
    const tell = this.s.tell && this.s.tell.kind === 'card' && this.s.tell.id === id;
    const ring = tell || holding && this.s.edit ? `inset 0 0 0 2px ${mix('var(--violet)', 60)}` : this.s.edit ? `inset 0 0 0 1px ${mix(hue(sec.color), 30)}` : open ? `inset 0 0 0 1.5px ${mix(ctx.accent || 'var(--text)', 40)}` : 'none';
    mt.style.background = open && !this.s.edit ? mix(ctx.accent || 'var(--text)', 7, 'var(--surface)') : 'transparent';
    mt.style.boxShadow = ring;
    mt.style.cursor = this.s.edit ? 'pointer' : 'default';
    mt.classList.toggle('holding', holding);
    mt.classList.toggle('sliding', this.s.previews[id] != null);
    const hb = holding ? `<span class="holdbar" style="background:${this.s.edit ? 'var(--violet)' : ctx.accent}"></span>` : '';
    let hbEl = mt.querySelector('.holdbar');
    if (hb && !hbEl) mt.insertAdjacentHTML('afterbegin', hb); else if (!hb && hbEl) hbEl.remove();
    // Morph's mark in the card's top-right corner, shown on hover where
    // there is a pointer to hover with: one press opens the Tell box for this
    // card without going through Edit. An opened card carries it among its
    // options instead (a phone has no hover), so it is not drawn twice.
    const wantMark = this.admin() && !this.s.edit && !open;
    let hmEl = mt.querySelector('.hovermark');
    if (wantMark && !hmEl) mt.insertAdjacentHTML('beforeend', `<button type="button" class="hovermark" data-snap-skip="1" data-act="tell-card" data-v="${esc(id)}" aria-label="Tell brAIn what to change about ${esc(name)}" title="Tell brAIn what to change">${MARK(18)}</button>`);
    else if (!wantMark && hmEl) hmEl.remove();
    this.setHtml(face, faceHtml);
    this.setHtml(moreEl, moreHtml);
    if (T.host) this.mountLovelace(face, card);
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
        const helpers = await window.loadCardHelpers();
        el = await helpers.createCardElement(card.card);
        el.__sig = sig;
        el.hass = this.hass;
        el.addEventListener('ll-rebuild', () => { this.llCards.delete(card.id); this.schedule(); });
        this.llCards.set(card.id, el);
      } catch (e) {
        slot.innerHTML = `<p class="sm" style="padding:12px">This Lovelace card could not be created: ${esc(e.message || e)}</p>`;
        this.report('card', `A Lovelace card failed: ${e.message || e}`, sig.slice(0, 500), String(card.card && card.card.type));
        return;
      } finally { this._llPending.delete(card.id); }
    }
    if (el.parentNode !== slot) { slot.innerHTML = ''; slot.appendChild(el); }
    if (!this._llRo) this._llRo = new ResizeObserver(() => this.engine.layout(false, true));
    this._llRo.observe(slot);
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
    const head = `<div class="row" style="min-width:0">${SPARK}<span style="font-size:13px;font-weight:600;white-space:nowrap">Tell brAIn</span><span class="small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0">${esc(t.path || '')}</span></div>`;
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
${st.payload ? `<details class="payload"><summary>What brAIn receives</summary><pre>${esc(st.payload)}</pre></details>` : ''}</div>`;
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
    if (st.phase === 'sending') return 'Handing it to brAIn';
    if (st.phase === 'waiting') return 'Waiting for brAIn to pick it up';
    return 'brAIn is working on it';
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
    if (!this.admin() || this.s.page !== 'home') return '';
    const st = (this.data && this.data.state) || {};
    const t = this.s.tell;
    const rows = (st.activity || []).filter((a) => !(t && t.tellId === a.id)).map((a) => {
      const live = this.tellStatus[a.id] || {};
      if (['done', 'failed'].includes(live.phase)) return '';
      const step = ((live.steps || []).slice(-1)[0] || {}).t || a.step || '';
      return `<div class="activity"><span class="pulse"></span><span class="lx"><b>brAIn is working on “${esc(a.text)}”</b><span>${esc([a.path, step].filter(Boolean).join(' · '))} · <span data-since="${Number(a.started) || ''}"></span></span></span><button type="button" class="wd" data-act="activity-open" data-v="${esc(a.id)}">Show</button></div>`;
    }).join('');
    const L = st.learning || {};
    const learn = L.running ? '<div class="activity"><span class="pulse"></span><span class="lx"><b>Morph is learning from how this dashboard is used</b><span>brAIn is reading the last month of use; suggestions appear where they belong.</span></span></div>' : '';
    return rows + learn;
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
    if (scope.kind === 'floor') { const fi = ((this.dash && this.dash.floors) || []).findIndex((f) => f.id === scope.id); return fi >= 0 ? R.querySelector(`[data-floor="${fi}"]`) : null; }
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
      if (e.key === 'Escape') { if (this.s.tell) this.closeTell(); else if (this.s.view) this.closeView(); return; }
      if (e.key === 'Enter' && !e.shiftKey) {
        if (t.dataset && t.dataset.tellkey) { e.preventDefault(); this.sendTell(t.value); }
        else if (t.dataset && t.dataset.actEnter) { e.preventDefault(); this.act(t.dataset.actEnter, t); }
      }
    });
    root.addEventListener('pointermove', (e) => this.scrub(e));
    root.addEventListener('pointerout', (e) => this.scrubEnd(e));
    root.addEventListener('wheel', (e) => this.upcWheel(e), { passive: false });
  }

  // Anything outside the open thing folds it back (§1.10).
  outside(e) {
    const inside = (sel) => !!(e.target.closest && e.target.closest(sel));
    if (this.s.secEdit && !inside(`[data-sec-head="${CSS.escape(this.s.secEdit)}"]`)) { this.s.secEdit = null; this.schedule(); }
    if (this.s.ask && !inside('[data-ask]') && !this.s.ask.busy) { this.s.ask = null; this.schedule(); }
    const t = this.s.tell;
    if (t && !inside('[data-tell]') && !(t.kind === 'card' && inside(`[data-tile="${CSS.escape(t.id)}"]`)) && !t.sent) { this.closeTell(); }
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
    // a member strip inside an opened light group
    const mem = t.closest && t.closest('[data-member]');
    if (mem && !this.s.edit) { const r = mem.getBoundingClientRect(); this.mptr = { id: mem.dataset.member, x0: e.clientX, y0: e.clientY, r, drag: false, el: mem, pid: e.pointerId }; return; }
    if (t.closest && t.closest('[data-ctl], button, input, textarea, select, summary, a')) return;
    const vp = !this.s.edit && t.closest && t.closest('[data-upc-vp]');
    if (vp) { this.upcDown(e, vp); return; }
    // hold-to-tell on the top regions, floors and section heads (Edit only)
    const holdable = t.closest && t.closest('[data-hold]');
    const head = t.closest && t.closest('.sechead');
    if (this.s.edit && head) { this.secDown(head.getAttribute('data-sec-head'), e); return; }
    if (this.s.edit && holdable && !t.closest('.mtile')) {
      const key = holdable.dataset.hold;
      const [kind, id] = key.includes(':') ? key.split(':') : [key, ''];
      this.holdStart('top:' + key, { kind, id }, e);
      return;
    }
    const mt = t.closest && t.closest('.mtile');
    if (!mt) return;
    const id = mt.dataset.mt;
    if (id.startsWith('n:')) return;
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
    if (this.upcD) { this.upcUp(e); return; }
    const mp = this.mptr;
    if (mp) {
      this.mptr = null;
      if (mp.drag && this.s.memberPreview) { const v = this.s.memberPreview.v; this.call(v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: mp.id } } : { domain: 'light', service: 'turn_on', data: { entity_id: mp.id, brightness_pct: v } }); setTimeout(() => { this.s.memberPreview = null; this.schedule(); }, 900); }
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
      if (p.slide && v != null) { this.call(p.slide.call(v)); const hit = this.findCard(p.id); this.track('slide', p.id, hit && hit.sec.id); }
      setTimeout(() => { delete this.s.previews[p.id]; this.schedule(); }, 1200);
      return;
    }
    if (p.held || sw) return;
    const id = p.id;
    if (id.startsWith('add@')) { if (this.s.view && this.s.view.id === id) this.closeView(); else this.openView(id, 'add'); return; }
    if (this.s.edit) { const v = this.s.view; if (v && v.id === id) this.closeView(); else this.openView(id, 'edit'); return; }
    const hit = this.findCard(id); if (!hit) return;
    const T = typeOf(hit.card);
    const ctx = { hass: this.hass, card: hit.card, st: hit.card.entity ? this.hass.states[hit.card.entity] : null };
    const tap = T.tap(ctx);
    if (tap) {
      if (tap.confirm) {
        const c = this.s.confirm[id];
        if (!c || c.until < Date.now()) { this.s.confirm[id] = { until: Date.now() + 4000, text: tap.confirm }; this.schedule(); setTimeout(() => this.schedule(), 4100); return; }
        delete this.s.confirm[id];
      }
      this.call(tap);
      this.track('toggle', id, hit.sec.id);
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

  async act(name, el) {
    const v = el.dataset.v;
    const H = this.hass;
    switch (name) {
      case 'menu': this.dispatchEvent(new Event('hass-toggle-menu', { bubbles: true, composed: true })); return;
      case 'page': this.s.page = v; this.s.edit = false; this.s.view = null; this.cache.clear(); if (v === 'settings') this.loadHistory(); this.schedule(); return;
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
        this.toast(r.ok ? 'Put back.' : r.error); this.dash = null; this.load(); if (this.s.page === 'settings') this.loadHistory(); return;
      }
      case 'restore': {
        const r = await H.callWS({ type: 'morph/request', kind: 'restore', payload: { sha: v } });
        this.toast(r.ok ? 'Restored that version. Undo is in History.' : r.error); this.dash = null; this.load(); this.loadHistory(); return;
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
      case 'finding': {
        const r = await H.callWS({ type: 'morph/finding', ts: Number(el.dataset.ts), action: v });
        this.toast(r && r.ok ? 'Told brAIn.' : 'brAIn did not take that.'); return;
      }
      case 'sug-no': this.s.sugNo = el.dataset.id; this.schedule(); return;
      case 'sug-cancel': this.s.sugNo = null; this.schedule(); return;
      case 'sug': {
        const note = v === 'no' ? ((this.shadowRoot.querySelector('input[data-keep="sugno"]') || {}).value || '') : '';
        const r = await H.callWS({ type: 'morph/request', kind: 'suggestion', payload: { id: el.dataset.id, verb: v, note } });
        this.s.sugNo = null;
        this.toast(r.ok ? (v === 'do' ? 'Handed to brAIn.' : v === 'send' ? 'Sent as an issue.' : v === 'no' ? 'Morph will not suggest that again.' : 'Later, then.') : r.error);
        this.load(); return;
      }
      // tell
      case 'tell-sug': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); if (ta) { ta.value = v; this.s.tell.draft = v; ta.focus(); } return; }
      case 'tell-send': { const ta = this.shadowRoot.querySelector('textarea[data-tellkey]'); this.sendTell(ta ? ta.value : ''); return; }
      case 'tell-cancel': this.closeTell(); return;
      case 'tell-refresh': this.dash = null; this.load(); return;
      case 'report-send': {
        const ta = this.shadowRoot.querySelector('textarea[data-keep="report"]');
        const ui = this.shadowRoot.querySelector('input[data-keep="report-ui"]');
        const text = ta ? ta.value.trim() : '';
        if (!text) { this.toast('Say what should be fixed.'); return; }
        const r = await H.callWS({ type: 'morph/request', kind: 'report', payload: { text, ui: !!(ui && ui.checked) } });
        if (r && r.ok) { this.s.report = null; if (ta) ta.value = ''; if (ui) ui.checked = false; this.toast('Sent to brAIn’s development loop.'); this.load(); } else this.toast((r && r.error) || 'Morph could not send that.');
        return;
      }
      case 'report-withdraw': {
        const r = await H.callWS({ type: 'morph/request', kind: 'report_withdraw', payload: { fp: v } });
        this.toast(r && r.ok ? 'Taken back.' : (r && r.error) || 'Morph could not take that back.'); this.load(); return;
      }
      case 'ask-tell': if (this.s.ask && this.s.ask.q) this.tellDashboard(this.s.ask.q); return;
      case 'tell-card': this.openTell({ kind: 'card', id: v, from: this.s.view && this.s.view.id === v ? 'adv' : '' }); return;
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
        this.s.tell = { kind: 'code', id: v, label: v, path: `Morph’s own ${v}`, text: `Make my change to ${v} again on the new Morph`, sent: true, tellId: r.id, state: r, turns: [] };
        this.pollTell(true); this.load(); return;
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
        const a = (((this.data && this.data.state) || {}).activity || []).find((x) => x.id === v); if (!a) return;
        const st = this.tellStatus[v] || { phase: a.phase, steps: [], started: a.started };
        this.s.tell = { kind: a.kind || 'dashboard', id: a.target || '', label: a.label, path: a.path, text: a.kind === 'code' ? String(a.text || '').split('\n')[0] : a.text, sent: true, tellId: a.id, state: st, turns: [] };
        if (a.kind === 'card' && a.target && this.findCard(a.target)) this.openView(a.target, 'tell');
        this.pollTell(true); this.schedule(); return;
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
      // settings
      case 'set': {
        const patch = {}; patch[el.dataset.k] = el.dataset.t === 'bool' ? !(this.settings()[el.dataset.k]) : el.dataset.t === 'num' ? Number(v) : v;
        const r = await H.callWS({ type: 'morph/request', kind: 'settings', payload: { patch } });
        if (r.ok) { this.data.state.settings = r.settings; this.schedule(); } else this.toast(r.error); return;
      }
      case 'learn-now': { const r = await H.callWS({ type: 'morph/request', kind: 'learn_now', payload: {} }); this.toast(r.ok ? 'Learning pass started — suggestions appear in place when it answers.' : r.error); return; }
      case 'regenerate': {
        if (!this._regenSure) { this._regenSure = true; el.textContent = 'Press again to rebuild (Undo is in History)'; return; }
        this._regenSure = false;
        const r = await H.callWS({ type: 'morph/request', kind: 'regenerate', payload: {} });
        this.toast(r.ok ? 'Rebuilt from the house.' : r.error, r.commit); this.dash = null; this.load(); this.loadHistory(); return;
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

  async ask(q) {
    q = String(q || '').trim(); if (!q) return;
    const ae = this.shadowRoot.activeElement; if (ae && ae.blur) ae.blur();
    // A request to change the DASHBOARD goes to a Tell, which can write
    // /config/morph, in Edit or not. Sent to the house's conversation agent
    // it was answered "I'll update the dashboard" by an agent with no way to
    // touch the file (house report: "it says it's making changes, but none
    // of them are actually being applied").
    if (this.s.edit || (this.admin() && DASH_CHANGE.test(q))) { this.tellDashboard(q); return; }
    this.s.ask = { q, busy: true }; this.schedule();
    this.track('ask');
    const agent = Object.values(this.hass.entities || {}).find((e) => e.platform === 'brain' && e.entity_id.startsWith('conversation.'));
    try {
      const r = await this.hass.callWS({ type: 'conversation/process', text: q, agent_id: agent ? agent.entity_id : undefined, conversation_id: this._conv || undefined });
      this._conv = r.conversation_id;
      const ans = (r.response && r.response.speech && r.response.speech.plain && r.response.speech.plain.speech) || 'No answer.';
      const show = [];
      this.eachSection((sec) => this.sectionCards(sec).forEach((c) => { const n = this.cardName(c, sec); if (show.length < 3 && n.length > 3 && ans.toLowerCase().includes(n.toLowerCase())) show.push({ id: c.id, name: n }); }));
      this.s.ask = { q, answer: ans, show };
    } catch (e) { this.s.ask = { q, answer: 'Could not ask: ' + (e.message || e) }; }
    this.schedule();
  }

  tellDashboard(q) {
    this.s.ask = null;
    this.s.tell = { kind: 'dashboard', path: 'The whole dashboard', label: 'dashboard', sent: false, draft: q, turns: [] };
    this.shoot(this.s.tell);
    this.sendTell(q);
  }

  // ------------------------------------------------------------ settings

  async loadHistory() {
    try { const r = await this.hass.callWS({ type: 'morph/request', kind: 'history', payload: { limit: 60 } }); this.s.hist = r.log || []; } catch (e) { this.s.hist = []; }
    this.schedule();
  }

  // This house's changes to Morph's own code (/config/morph/frontend/,
  // the add-on's morphcode.py): each one in use or paused by an update,
  // with the way back to Morph's own.
  codeHtml(st) {
    const rows = st.code || [];
    const head = '<span class="label">Changes to Morph itself</span>';
    if (!rows.length) return `${head}<p class="sm">None. brAIn can change any part of Morph — its header, its cards, how it lays things out. Ask in Edit, and Morph asks whether to send the change on as an issue.</p>`;
    return head + rows.map((r) => `<div class="hrow"><span class="who">${esc(r.status === 'paused' ? 'Paused' : 'In use')}</span><span class="lx" style="min-width:0"><span>${esc(r.name)}${r.kind === 'new' ? ' (new)' : ''}</span><span class="small">${esc(r.status === 'paused' ? pausedWhy(r) : r.at ? 'Changed ' + ago(new Date(r.at * 1000).toISOString()) : 'Changed just now')}</span></span>${r.status === 'paused' ? `<button type="button" class="wd go" data-act="code-redo" data-v="${esc(r.name)}">Make it again</button>` : ''}<button type="button" class="wd" data-act="code-reset" data-v="${esc(r.name)}">Use Morph’s own</button></div>`).join('');
  }

  settingsHtml() {
    if (!this.admin()) return '<div class="banner">Only an administrator can change Morph.</div>';
    const st = (this.data && this.data.state) || {}; const s = st.settings || {};
    const sw = (k, title, body) => `<div class="setrow" data-act="set" data-k="${k}" data-t="bool" role="switch" aria-checked="${!!s[k]}" tabindex="0"><span class="lx"><b>${esc(title)}</b><span>${esc(body)}</span></span><span class="sswitch${s[k] ? ' on' : ''}"><i></i></span></div>`;
    const pick = (k, opts) => `<div class="row" style="flex-wrap:wrap;gap:0 18px">${opts.map((o) => `<button type="button" class="wd" data-act="set" data-k="${k}" data-t="${typeof o[0] === 'number' ? 'num' : 'str'}" data-v="${esc(o[0])}" aria-pressed="${s[k] === o[0]}">${esc(o[1])}</button>`).join('')}</div>`;
    const brain = st.brain || {};
    const L = st.learning || {}; const sc = L.scorecard || {};
    const dl = st.devloop || {};
    const sugs = (st.suggestions || []);
    const hist = this.s.hist;
    return `<div class="settings">
<h1 class="hello" style="font-size:clamp(30px,4vw,44px)">Settings</h1>
<p class="sm" style="color:var(--amber)">Experimental — Morph is not finished and not recommended for general use yet. Keep your normal dashboards beside it.</p>
${this.versionHtml(st)}
<div class="setsec"><h2>brAIn</h2><p class="sm" style="color:${brain.state === 'ok' ? 'var(--teal)' : 'var(--amber)'}">${esc(brain.sentence || 'Unknown')}</p>
<p class="sm">In Edit, hold anything and say what should change. brAIn makes the change at once — the dashboard, a card's code, or the automation behind it — and every change has an Undo.</p>
<span class="label">Model for changes</span>${pick('tell_model', [['', 'brAIn’s default'], ['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku']])}
<span class="label">How long a hold takes</span>${pick('hold_ms', [[400, 'Quick'], [540, 'Normal'], [800, 'Slow']])}</div>
<div class="setsec"><h2>Learning</h2>
${sw('learning', 'Learn and suggest improvements', 'Morph notices how you use the dashboard and asks brAIn how it could be better. Suggestions appear in the room they are about, with Do it, Not now and No. Nothing changes until you say Do it.')}
<span class="label">How often</span>${pick('learning_hours', [[12, 'Twice a day'], [24, 'Daily'], [72, 'Every 3 days'], [168, 'Weekly']])}
<span class="label">Model for learning</span>${pick('learn_model', [['', 'brAIn’s default'], ['haiku', 'Haiku'], ['sonnet', 'Sonnet'], ['opus', 'Opus']])}
<div class="row"><button type="button" class="wd go" data-act="learn-now">Learn now</button><span class="sm">${esc(L.running ? 'A pass is running…' : L.last_note || 'No pass has run yet.')}${L.last_pass ? ' · ' + esc(ago(new Date(L.last_pass * 1000).toISOString())) : ''}</span></div>
<div class="stats"><div class="stat"><b>${sc.done || 0}</b><span>suggestions done</span></div><div class="stat"><b>${sc.declined || 0}</b><span>declined</span></div><div class="stat"><b>${sc.tells_kept || 0}<span style="font-size:16px;color:var(--quiet)"> / ${sc.tells || 0}</span></b><span>brAIn changes kept</span></div><div class="stat"><b>${sc.lessons || 0}</b><span>lessons learned</span></div></div>
${sugs.length ? `<span class="label">Waiting for you</span>${sugs.map((g) => this.noteHtml({ kind: 'suggestion', g })).join('')}` : ''}
<span class="label">What Morph has learned about this household</span><p class="small">One per line. brAIn rewrites these from what you do, decline and undo; they are yours to edit. Every change brAIn makes reads them.</p>
<textarea class="code-ed" data-keep="lessons" style="min-height:120px;white-space:pre-wrap">${esc((L.lessons || []).map((x) => '- ' + x).join('\n'))}</textarea><div><button type="button" class="wd go" data-act="lessons-save">Save lessons</button></div></div>
<div class="setsec"><h2>Improving Morph itself</h2>
${sw('report_code_issues', 'Report Morph’s own problems', 'A card that fails to draw, a layout that overlaps, a request brAIn could not carry out. They go to brAIn’s development loop, which files them in your private reports repository so they are fixed in Morph’s code.')}
${this.reportHtml(dl)}
${this.codeHtml(st)}
<p class="sm">${dl.enabled ? `${dl.waiting || 0} report${dl.waiting === 1 ? '' : 's'} waiting.` : 'Off.'} ${dl.picked_up_at ? `brAIn last picked them up ${esc(ago(new Date(dl.picked_up_at * 1000).toISOString()))}${dl.filed != null ? `, ${dl.filed} filed` : ''}.` : 'brAIn has not picked any up yet — switch on its development loop under brAIn ⚙ → Developer.'}</p></div>
<div class="setsec"><h2>Appearance</h2><span class="label">Theme</span>${pick('theme', [['auto', 'Follow Home Assistant'], ['dark', 'Dark'], ['medium', 'Medium'], ['light', 'Light']])}
${sw('reduce_motion', 'Reduce motion', 'Things move straight to where they belong instead of springing there.')}</div>
<div class="setsec"><h2>History</h2><p class="sm">Every change to the dashboard — yours, brAIn's, or a suggestion you approved — is one entry. Undo reverts one change; Restore puts the whole dashboard back as it was then.</p>
${hist == null ? '<p class="sm">Reading…</p>' : hist.length ? hist.map((h) => `<div class="hrow"><span class="who">${esc({ person: 'You', brain: 'brAIn', learning: 'Learning', outside: 'Outside', morph: 'Morph' }[h.who] || h.who)}</span><span class="lx" style="min-width:0"><span>${esc(h.message)}</span><span class="small">${esc(new Date(h.at * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }))}</span></span><button type="button" class="wd" data-act="undo-commit" data-v="${esc(h.sha)}">Undo</button><button type="button" class="wd" data-act="restore" data-v="${esc(h.sha)}">Restore</button></div>`).join('') : '<p class="sm">No history yet.</p>'}</div>
<div class="setsec"><h2>Dashboard</h2><p class="sm">The dashboard lives in /config/morph/dashboard.yaml. Edit it in Edit → YAML, by hand, or by telling brAIn.</p>
<div><button type="button" class="wd bad" data-act="regenerate">Rebuild from the house</button></div><p class="small">Builds a fresh dashboard from your floors and rooms. Your current one stays in History.</p></div>
</div>`;
  }

  // brAIn's "What do you want to fix?" box, for Morph: somebody's own words,
  // sent as they are to brAIn's development loop, which files them in the
  // private reports repository for the cloud routine to fix Morph's code.
  reportHtml(dl) {
    const mine = dl.mine || [];
    const sent = mine.length ? `<div style="display:flex;flex-direction:column;gap:4px">${mine.map((r) => `<div class="hrow"><span class="lx" style="min-width:0"><span>${esc(r.what)}</span><span class="small">${r.ui ? 'How it looks · ' : ''}${esc(ago(new Date(r.at * 1000).toISOString()))} · ${r.picked ? 'brAIn has it' : 'waiting for brAIn to pick it up'}</span></span>${r.picked ? '' : `<button type="button" class="wd" data-act="report-withdraw" data-v="${esc(r.fp)}">Take back</button>`}</div>`).join('')}</div>` : '';
    return `<span class="label">What do you want to fix in Morph?</span>
<textarea class="code-ed" data-keep="report" style="min-height:90px;white-space:pre-wrap;font-family:inherit" placeholder="The Coming up line overlaps the scenes on my phone…" aria-label="What do you want to fix in Morph?">${esc((this.s.report || {}).text || '')}</textarea>
<label class="row" style="gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" data-keep="report-ui"${(this.s.report || {}).ui ? ' checked' : ''}>It is about how Morph looks</label>
<div class="row" style="gap:0 18px;flex-wrap:wrap"><button type="button" class="wd go" data-act="report-send">Send</button><span class="sm">Your words go as they are to brAIn’s development loop, which files them as an issue in your private reports repository so Morph’s code gets fixed.</span></div>${sent}`;
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
    const key = kind + '|' + message;
    if (this.reported.has(key) || !this.hass) return;
    this.reported.add(key);
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
