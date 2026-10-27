/* BRUH Bambu Studio — one card for 3D printers, in two hosts.
 *
 * This file defines two elements:
 *   custom:bruh-bambu-card     a Lovelace card (an <ha-card>, HA's theme)
 *   custom:morph-bambu-printer the same card for Morph (Morph's variables
 *                              and fonts, no ha-card, nothing floats)
 * run.sh copies it to /config/www/bruh_bambu (the integration registers it
 * with the frontend) and, when Morph is installed, to /config/morph/cards.
 *
 * It reads the `Status` sensor of each printer — every figure the card
 * shows is an attribute there, and `bruh_bambu_printer` is how a printer's
 * sensor is found — and it acts through the bruh_bambu services over the
 * connection the dashboard already has. Plain custom elements, no imports:
 * a card that needs a CDN is a card that is blank the day it is down.
 *
 * The camera is the printer's `camera.*` entity on the same device (the
 * integration makes one per printer), shown through Home Assistant's own
 * camera proxy and refreshed every two seconds while the card is on screen.
 * Its <img> is kept across redraws, or every state change would blank it.
 *
 * Print failure detection is its own sensor on the same device (marked
 * `bruh_bambu_detection`); when it is on the card shows what it is doing
 * and, while an alert is open, what brAIn saw with the buttons that answer
 * it — Ignore and Pause for a warning, Resume and Stop for a paused print.
 *
 * The face of a printer is its name and state, the camera, the progress
 * with the time left, failure detection's line (or its open alert, with
 * the buttons that answer it), the temperatures, and Pause or Resume.
 * Everything else (Stop, speed, the light, Refresh, Reconnect and the AMS
 * trays) is behind the printer's ⋯, a drawer that opens in the card's own
 * flow. An open alert brings its own Pause, so the card's goes to the drawer.
 *
 * Stop takes two presses, the second within four seconds. A dialog would
 * float over the page (Morph forbids that), and one press on a ten-hour
 * print is the press nobody can take back.
 */

const CARD_VERSION = '0.3.0';
const DOMAIN = 'bruh_bambu';

console.info(
  `%c BRUH BAMBU CARD %c ${CARD_VERSION} `,
  'background:#00ae42;color:#fff;font-weight:700;border-radius:3px 0 0 3px',
  'background:#16181d;color:#fff;border-radius:0 3px 3px 0',
);

const SPEEDS = ['silent', 'standard', 'sport', 'ludicrous'];
// The status sensor's states in the words a person reads.
const STATE_WORDS = { idle: 'Idle', prepare: 'Preparing', running: 'Printing', pause: 'Paused',
  finish: 'Finished', failed: 'Failed', slicing: 'Slicing', offline: 'Offline', unknown: 'Unknown',
  removed: 'Removed', connecting: 'Connecting' };
const cap = (w) => String(w || '').replace(/^./, (c) => c.toUpperCase());

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function duration(min) {
  if (min == null) return '';
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

function finishAt(min) {
  if (min == null || min <= 0) return '';
  const t = new Date(Date.now() + min * 60000);
  return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function temp(now, target) {
  if (now == null) return '–';
  return target ? `${Math.round(now)}°/${Math.round(target)}°` : `${Math.round(now)}°`;
}

const css = (morph) => `
  :host { display: block;
    --b-surface: ${morph ? 'var(--surface)' : 'var(--ha-card-background, var(--card-background-color, #fff))'};
    --b-sunk: ${morph ? 'var(--sunk)' : 'var(--secondary-background-color, #f1f3f5)'};
    --b-text: ${morph ? 'var(--text)' : 'var(--primary-text-color, #14202b)'};
    --b-muted: ${morph ? 'var(--muted)' : 'var(--secondary-text-color, #5b6b79)'};
    --b-line: ${morph ? 'var(--line)' : 'var(--divider-color, #d9e0e6)'};
    --b-accent: ${morph ? 'var(--sky)' : 'var(--primary-color, #1e9fe0)'};
    --b-live: ${morph ? 'var(--lime)' : 'var(--success-color, #1f9d55)'};
    --b-bad: ${morph ? 'var(--rose)' : 'var(--error-color, #c62828)'};
    --b-warn: #c77700;
    font-family: ${morph ? "'Manrope', sans-serif" : 'inherit'}; color: var(--b-text); }
  .wrap { padding: ${morph ? '4px 2px' : '12px 16px 14px'}; display: grid; gap: 12px; }
  .printer { display: grid; gap: 6px; min-width: 0; }
  .printer + .printer { border-top: 1px solid var(--b-line); padding-top: 12px; }
  .head { display: flex; align-items: center; gap: 8px; min-height: 44px; }
  .name { font-weight: 700; font-size: 16px; flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .state { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--b-muted); white-space: nowrap; }
  .state i { width: 8px; height: 8px; border-radius: 50%; background: var(--b-muted); }
  .state.live i { background: var(--b-live); }
  .state.warn i { background: var(--b-warn); }
  .state.bad { color: var(--b-bad); }
  .state.bad i { background: var(--b-bad); }
  /* The picture at a size a dashboard can carry, in the stream's own shape. */
  .cam { position: relative; aspect-ratio: 16 / 9; width: min(100%, 320px); justify-self: center;
    border-radius: 12px; overflow: hidden; background: var(--b-sunk); }
  .cam img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: block; }
  .job { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; column-gap: 10px; row-gap: 2px; }
  .pct { font-family: ${morph ? "'Bricolage Grotesque', sans-serif" : 'inherit'};
    font-size: 22px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .pct small { font-size: 14px; font-weight: 500; color: var(--b-muted); margin-left: 6px; }
  .job .muted { grid-column: 1; }
  .job > button { grid-row: 1 / span 2; grid-column: 2; }
  .muted { color: var(--b-muted); font-size: 13px; overflow-wrap: anywhere; }
  .bar { height: 4px; border-radius: 2px; background: var(--b-sunk); overflow: hidden; }
  .bar > i { display: block; height: 100%; background: var(--b-accent); }
  .stats { display: flex; gap: 4px 14px; flex-wrap: wrap; font-size: 13px; color: var(--b-muted); }
  .stats b { font-weight: 600; color: var(--b-text); }
  .ams { display: flex; gap: 6px; flex-wrap: wrap; }
  .tray { display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
    padding: 2px 8px; border: 1px solid var(--b-line); border-radius: 999px; }
  .tray i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--b-line); }
  .tray.active { border-color: var(--b-live); box-shadow: 0 0 0 1px var(--b-live); }
  .controls { display: flex; gap: 6px; flex-wrap: wrap; }
  button, select { font: inherit; font-size: 14px; min-height: 44px; padding: 0 14px;
    border-radius: 10px; border: 1px solid var(--b-line); background: var(--b-surface);
    color: var(--b-text); cursor: pointer; }
  button.primary { background: var(--b-accent); border-color: var(--b-accent); color: #fff; }
  button.danger { color: var(--b-bad); }
  button.armed { background: var(--b-bad); border-color: var(--b-bad); color: #fff; }
  button.more { width: 44px; padding: 0; border-color: transparent; background: transparent;
    font-size: 20px; line-height: 1; color: var(--b-muted); }
  button.more[aria-expanded="true"] { background: var(--b-sunk); color: var(--b-text); }
  /* Everything else, in the card's own flow (nothing floats over a
     dashboard): shut, it takes no room and nothing in it can be reached. */
  .drawer { display: grid; grid-template-rows: 0fr; }
  .drawer > div { min-height: 0; overflow: hidden; display: grid; gap: 8px; }
  .drawer.shut > div { visibility: hidden; }
  .drawer:not(.shut) { grid-template-rows: 1fr; padding: 8px 0 2px; border-top: 1px solid var(--b-line); }
  .err { color: var(--b-bad); font-size: 13px; }
  .empty { color: var(--b-muted); }
  .watch { display: grid; gap: 6px; padding: 8px 10px; border-radius: 12px; background: var(--b-sunk); font-size: 13px; }
  .watch.quiet { padding: 0; background: none; color: var(--b-muted); }
  .watch.warn { background: color-mix(in srgb, #f0a63c 20%, var(--b-surface)); }
  .watch.bad { background: color-mix(in srgb, var(--b-bad) 18%, var(--b-surface)); }
  .watch .line { display: flex; align-items: center; gap: 6px; }
  .watch svg { width: 16px; height: 16px; fill: currentColor; flex: none; }
  .watch.bad svg { color: var(--b-bad); }
  .watch b { font-weight: 700; }
  .watch .say { font-size: 14px; font-weight: 600; }
  .watch .answer { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .watch .answer .muted { flex: 1 1 120px; }
`;

const SHIELD = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M11,7H13V13H11V7M11,15H13V17H11V15Z"/></svg>';
const WATCH_WORDS = { idle: 'Ready for the next print', watching: 'Watching', looking: 'brAIn is looking',
  basic: 'Watching (without brAIn)', warning: 'Warning', failure: 'Print failed', covered: 'Camera covered — not checking',
  dark: 'Too dark to see — not checking', frozen: 'Camera frozen — not checking', no_camera: 'No camera — not checking' };

class BruhBambuCard extends HTMLElement {
  static morph = false;

  setConfig(config) {
    this._config = { show_ams: true, show_controls: true, show_camera: true, ...(config || {}) };
    this._cams = this._cams || {};
    this._armed = null;
    this._open = this._open || new Set();
    this._key = '';
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
  }

  static getStubConfig() { return {}; }

  getCardSize() { return 3; }

  set hass(hass) {
    this._hass = hass;
    const printers = this._printers();
    const key = JSON.stringify(printers.map((p) => {
      const d = this._detectionOf(p);
      return [p.entity, p.state, p.attrs, d && d.state, d && d.attributes];
    })) + this._armed + [...this._open].join();
    if (key === this._key) return;
    this._key = key;
    this._render(printers);
  }

  _printers() {
    const hass = this._hass;
    if (!hass) return [];
    const wanted = this._config.entity || this._config.entities;
    const ids = wanted ? [].concat(wanted)
      : Object.keys(hass.states).filter((id) => id.startsWith('sensor.')
        && hass.states[id].attributes && hass.states[id].attributes.bruh_bambu_printer);
    return ids.map((id) => hass.states[id]).filter(Boolean)
      .map((s) => ({ entity: s.entity_id, state: s.state, attrs: s.attributes }));
  }

  _detectionOf(p) {
    const hass = this._hass;
    const pid = p.attrs.bruh_bambu_printer;
    const id = Object.keys(hass.states).find((e) => e.startsWith('sensor.')
      && hass.states[e].attributes && hass.states[e].attributes.bruh_bambu_detection === pid);
    return id ? hass.states[id] : null;
  }

  _watchHtml(p, id) {
    const d = this._detectionOf(p);
    if (!d || ['off', 'unknown', 'unavailable'].includes(d.state) || this._config.show_detection === false) return '';
    const a = d.attributes;
    const tone = d.state === 'failure' ? 'bad' : ['warning', 'covered', 'dark', 'frozen', 'no_camera'].includes(d.state) ? 'warn' : '';
    if (a.alert_id) {
      const buttons = d.state === 'failure' && a.alert_paused
        ? `<button class="primary" data-alert="resume" data-id="${id}" data-a="${esc(a.alert_id)}">Resume — not a failure</button>
           <button class="${this._armed === `alert:${a.alert_id}` ? 'armed' : 'danger'}" data-alert="stop" data-id="${id}" data-a="${esc(a.alert_id)}">${this._armed === `alert:${a.alert_id}` ? 'Tap again to stop' : 'Stop print'}</button>`
        : `<button data-alert="pause" data-id="${id}" data-a="${esc(a.alert_id)}">Pause print</button>
           <button data-alert="ignore" data-id="${id}" data-a="${esc(a.alert_id)}">Ignore</button>`;
      // What brAIn saw first, then the answers beside the detection's state.
      return `<div class="watch ${tone}"><div class="line">${SHIELD}<div class="say">${esc(a.alert)}</div></div><div class="answer"><span class="muted">Failure detection · ${esc(WATCH_WORDS[d.state] || d.state)}</span>${buttons}</div></div>`;
    }
    // Nothing to answer: one quiet line, and the next look where it is known.
    const next = d.state === 'watching' && a.next_look_layer ? ` · next look at layer ${esc(a.next_look_layer)}` : '';
    return `<div class="watch quiet ${tone}"><div class="line">${SHIELD}<b>Failure detection</b><span>${esc(WATCH_WORDS[d.state] || d.state)}${next}</span></div></div>`;
  }

  _cameraOf(p) {
    const hass = this._hass;
    const reg = hass.entities || {};
    const device = reg[p.entity] && reg[p.entity].device_id;
    if (!device) return null;
    // The live camera, not the Last print check one on the same device.
    const id = Object.keys(reg).find((e) => e.startsWith('camera.') && reg[e].device_id === device
      && !(reg[e].translation_key === 'last_check' || /_last_print_check$/.test(e)));
    return id && hass.states[id] ? id : null;
  }

  _camImg(id) {
    let cam = this._cams[id];
    if (!cam) {
      const img = document.createElement('img');
      img.alt = '';
      cam = this._cams[id] = { img, timer: null };
    }
    if (!cam.timer) {
      // The proxy's token rotates, so the address is read fresh each time.
      const tick = () => {
        const state = this._hass && this._hass.states[id];
        const base = state && state.attributes.entity_picture;
        if (!(this.isConnected && base && document.visibilityState === 'visible')) {
          cam.timer = setTimeout(tick, 2000);
          return;
        }
        // Decoded off screen and swapped in whole: setting the visible
        // image's src blanked it while each frame loaded, so the feed flashed.
        const next = new Image();
        next.src = `${base}${base.includes('?') ? '&' : '?'}t=${Date.now()}`;
        next.decode().then(() => {
          next.alt = cam.img.alt;
          next.className = cam.img.className;
          if (cam.img.isConnected) cam.img.replaceWith(next);
          cam.img = next;
          // The box keeps the stream's own shape (16:9 or 4:3).
          if (next.naturalWidth && next.naturalHeight) {
            cam.ratio = `${next.naturalWidth} / ${next.naturalHeight}`;
            const box = next.parentElement;
            if (box) box.style.aspectRatio = cam.ratio;
          }
        }, () => {})
          .finally(() => { cam.timer = setTimeout(tick, 2000); });
      };
      tick();
    }
    return cam.img;
  }

  disconnectedCallback() {
    for (const cam of Object.values(this._cams || {})) { clearTimeout(cam.timer); cam.timer = null; }
  }

  connectedCallback() {
    if (this._hass) { this._key = ''; this.hass = this._hass; }
  }

  _call(service, data) {
    return this._hass.callService(DOMAIN, service, data).catch((e) => {
      this._error = e.message || String(e);
      this._key = '';
      this.hass = this._hass;
    });
  }

  _stop(p) {
    const id = p.attrs.bruh_bambu_printer;
    if (this._armed === id) {
      this._armed = null;
      this._call('stop_print', { printer: id });
      return;
    }
    this._armed = id;
    this._key = '';
    this.hass = this._hass;
    clearTimeout(this._disarm);
    this._disarm = setTimeout(() => { this._armed = null; this._key = ''; this.hass = this._hass; }, 4000);
  }

  _render(printers) {
    const morph = this.constructor.morph;
    const cfg = this._config;
    const body = printers.length ? printers.map((p) => {
      const a = p.attrs;
      const live = a.printing;
      const id = esc(a.bruh_bambu_printer);
      const offline = p.state === 'offline';
      const tone = ['offline', 'unknown', 'removed', 'failed'].includes(p.state) ? 'bad'
        : p.state === 'pause' ? 'warn' : live ? 'live' : '';
      const open = this._open.has(a.bruh_bambu_printer);
      const trays = [...(Array.isArray(a.ams) ? a.ams : []), ...(a.external_spool ? [a.external_spool] : [])];
      const ams = cfg.show_ams && trays.length
        ? `<div class="ams">${trays.map((t) => `<span class="tray${a.active_tray === t.slot ? ' active' : ''}" title="${esc(t.name || t.type)}"><i style="background:${esc(t.colour || 'transparent')}"></i>${t.slot === 'external' ? 'Ext' : t.slot + 1} ${esc(t.type)}${t.remaining != null ? ` ${t.remaining}%` : ''}</span>`).join('')}</div>` : '';
      const camId = cfg.show_camera && !offline ? this._cameraOf(p) : null;
      const cam = camId ? `<div class="cam" data-cam="${esc(camId)}"></div>` : '';
      const detection = this._detectionOf(p);
      // An open alert brings its own Pause: the card's moves to the drawer.
      const alertPause = detection && detection.attributes.alert_id && !(detection.state === 'failure' && detection.attributes.alert_paused);
      const pauseBtn = cfg.show_controls && !offline ? (p.state === 'pause'
        ? `<button class="primary" data-act="resume_print" data-id="${id}">Resume</button>`
        : live ? `<button data-act="pause_print" data-id="${id}">Pause</button>` : '') : '';
      const armed = this._armed === a.bruh_bambu_printer;
      const drawerControls = cfg.show_controls ? (offline
        ? `<div class="controls"><button data-act="reconnect" data-id="${id}">Reconnect</button></div>`
        : `<div class="controls">
          ${alertPause ? pauseBtn : ''}
          ${live ? `<button class="${armed ? 'armed' : 'danger'}" data-stop="${id}">${armed ? 'Tap again to stop' : 'Stop'}</button>` : ''}
          ${live ? `<select data-speed="${id}" aria-label="Speed">${SPEEDS.map((sp) => `<option value="${sp}" ${sp === a.speed ? 'selected' : ''}>${cap(sp)}</option>`).join('')}</select>` : ''}
          <button data-light="${id}" data-on="${a.chamber_light ? '0' : '1'}">${a.chamber_light ? 'Light off' : 'Light on'}</button>
          <button data-act="refresh" data-id="${id}" title="Ask for a full report (after changing a spool)">Refresh</button>
          ${a.connection_error ? `<button data-act="reconnect" data-id="${id}">Reconnect</button>` : ''}
        </div>`) : '';
      const pct = a.progress != null && (live || p.state === 'finish') ? a.progress : null;
      const left = a.remaining_min != null && live ? `${duration(a.remaining_min)} left · done ${finishAt(a.remaining_min)}` : '';
      const job = live || pct != null ? `<div class="job">
          <span class="pct">${pct != null ? `${pct}%` : ''}${left ? `<small>${left}</small>` : ''}</span>
          <span class="muted">${[a.file, a.layer != null && a.total_layers ? `layer ${a.layer}/${a.total_layers}` : '', live ? a.stage : ''].filter(Boolean).map(esc).join(' · ')}</span>
          ${alertPause ? '' : pauseBtn}
        </div>
        <div class="bar"><i style="width:${Math.max(0, Math.min(100, a.progress || 0))}%"></i></div>`
        : pauseBtn ? `<div class="controls">${pauseBtn}</div>` : '';
      const drawer = ams || drawerControls;
      return `<div class="printer">
        <div class="head"><span class="name">${esc(a.printer_name || a.friendly_name)}</span>
          <span class="state ${tone}"><i></i>${esc(STATE_WORDS[p.state] || cap(p.state))}</span>
          ${drawer ? `<button class="more" data-more="${id}" aria-expanded="${open}" aria-label="More for ${esc(a.printer_name || a.friendly_name)}">⋯</button>` : ''}</div>
        ${cam}
        ${job}
        ${this._watchHtml(p, id)}
        <div class="stats"><span>Nozzle <b>${temp(a.nozzle_c, a.nozzle_target_c)}</b></span>
          <span>Bed <b>${temp(a.bed_c, a.bed_target_c)}</b></span>
          ${a.chamber_c != null ? `<span>Chamber <b>${Math.round(a.chamber_c)}°</b></span>` : ''}
          ${a.hms_count ? `<span class="err">${a.hms_count} printer message${a.hms_count > 1 ? 's' : ''}</span>` : ''}</div>
        ${a.connection_error ? `<div class="err">${esc(a.connection_error)}</div>` : ''}
        ${drawer ? `<div class="drawer${open ? '' : ' shut'}"${open ? '' : ' aria-hidden="true"'}><div>${drawerControls}${ams}</div></div>` : ''}
      </div>`;
    }).join('') : `<div class="empty">No printers yet. Add one on the BRUH Bambu Studio panel's Printers tab.</div>`;
    const inner = `<div class="wrap">${cfg.title ? `<div class="name">${esc(cfg.title)}</div>` : ''}${body}
      ${this._error ? `<div class="err">${esc(this._error)}</div>` : ''}</div>`;
    this.shadowRoot.innerHTML = `<style>${css(morph)}</style>${morph ? inner : `<ha-card>${inner}</ha-card>`}`;
    this.shadowRoot.querySelectorAll('[data-cam]').forEach((box) => {
      box.prepend(this._camImg(box.dataset.cam));
      const ratio = this._cams[box.dataset.cam] && this._cams[box.dataset.cam].ratio;
      if (ratio) box.style.aspectRatio = ratio;
    });
    this.shadowRoot.querySelectorAll('[data-more]').forEach((b) => b.addEventListener('click', () => {
      const key = printers.find((p) => esc(p.attrs.bruh_bambu_printer) === b.dataset.more).attrs.bruh_bambu_printer;
      if (this._open.has(key)) this._open.delete(key); else this._open.add(key);
      this._key = '';
      this.hass = this._hass;
    }));
    this.shadowRoot.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () =>
      this._call(b.dataset.act, { printer: b.dataset.id })));
    this.shadowRoot.querySelectorAll('[data-alert]').forEach((b) => b.addEventListener('click', () => {
      // Stop takes two presses here too (no dialog: Morph forbids floating ones).
      if (b.dataset.alert === 'stop' && this._armed !== `alert:${b.dataset.a}`) {
        this._armed = `alert:${b.dataset.a}`;
        this._key = '';
        this.hass = this._hass;
        clearTimeout(this._disarm);
        this._disarm = setTimeout(() => { this._armed = null; this._key = ''; this.hass = this._hass; }, 4000);
        return;
      }
      this._armed = null;
      this._call('print_alert_action', { printer: b.dataset.id, action: b.dataset.alert, alert: b.dataset.a });
    }));
    this.shadowRoot.querySelectorAll('[data-stop]').forEach((b) => b.addEventListener('click', () =>
      this._stop(printers.find((p) => p.attrs.bruh_bambu_printer === b.dataset.stop))));
    this.shadowRoot.querySelectorAll('[data-speed]').forEach((s) => s.addEventListener('change', () =>
      this._call('set_speed', { printer: s.dataset.speed, speed: s.value })));
    this.shadowRoot.querySelectorAll('[data-light]').forEach((b) => b.addEventListener('click', () =>
      this._call('set_light', { printer: b.dataset.light, on: b.dataset.on === '1' })));
    this._error = '';
  }
}

class MorphBambuPrinter extends BruhBambuCard {
  static morph = true;
}

// Guarded: a file loaded twice (Morph reloads a changed card) may define a
// name only once.
if (!customElements.get('bruh-bambu-card')) customElements.define('bruh-bambu-card', BruhBambuCard);
if (!customElements.get('morph-bambu-printer')) customElements.define('morph-bambu-printer', MorphBambuPrinter);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'bruh-bambu-card')) {
  window.customCards.push({
    type: 'bruh-bambu-card',
    name: 'BRUH Bambu printers',
    description: 'Camera, progress, time left, temperatures, AMS and print failure detection for your Bambu Lab printers, with pause, resume, stop, speed, light and refresh.',
    preview: true,
  });
}
