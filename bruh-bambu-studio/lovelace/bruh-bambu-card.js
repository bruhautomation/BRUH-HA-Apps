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
 * Stop takes two presses, the second within four seconds. A dialog would
 * float over the page (Morph forbids that), and one press on a ten-hour
 * print is the press nobody can take back.
 */

const CARD_VERSION = '0.1.2';
const DOMAIN = 'bruh_bambu';

console.info(
  `%c BRUH BAMBU CARD %c ${CARD_VERSION} `,
  'background:#00ae42;color:#fff;font-weight:700;border-radius:3px 0 0 3px',
  'background:#16181d;color:#fff;border-radius:0 3px 3px 0',
);

const SPEEDS = ['silent', 'standard', 'sport', 'ludicrous'];

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
    font-family: ${morph ? "'Manrope', sans-serif" : 'inherit'}; color: var(--b-text); }
  .wrap { padding: ${morph ? '4px 2px' : '16px'}; display: grid; gap: 14px; }
  .printer { display: grid; gap: 8px; }
  .printer + .printer { border-top: 1px solid var(--b-line); padding-top: 14px; }
  .head { display: flex; align-items: center; gap: 8px; }
  .name { font-weight: 700; font-size: 16px; flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip { padding: 2px 10px; border-radius: 999px; font-size: 12px; background: var(--b-sunk);
    text-transform: capitalize; }
  .chip.live { background: var(--b-live); color: #fff; }
  .chip.bad { background: var(--b-bad); color: #fff; }
  .pct { font-family: ${morph ? "'Bricolage Grotesque', sans-serif" : 'inherit'};
    font-size: 30px; font-weight: 700; line-height: 1; }
  .row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .muted { color: var(--b-muted); font-size: 13px; }
  .bar { height: 6px; border-radius: 3px; background: var(--b-sunk); overflow: hidden; }
  .bar > i { display: block; height: 100%; background: var(--b-accent); }
  .stats { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; }
  .stats b { font-weight: 600; }
  .ams { display: flex; gap: 6px; flex-wrap: wrap; }
  .tray { display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
    padding: 2px 8px; border: 1px solid var(--b-line); border-radius: 999px; }
  .tray i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--b-line); }
  .controls { display: flex; gap: 6px; flex-wrap: wrap; }
  button, select { font: inherit; font-size: 14px; min-height: 40px; padding: 0 12px;
    border-radius: 10px; border: 1px solid var(--b-line); background: var(--b-surface);
    color: var(--b-text); cursor: pointer; }
  button.primary { background: var(--b-accent); border-color: var(--b-accent); color: #fff; }
  button.danger { color: var(--b-bad); }
  button.armed { background: var(--b-bad); border-color: var(--b-bad); color: #fff; }
  .err { color: var(--b-bad); font-size: 13px; }
  .empty { color: var(--b-muted); }
`;

class BruhBambuCard extends HTMLElement {
  static morph = false;

  setConfig(config) {
    this._config = { show_ams: true, show_controls: true, ...(config || {}) };
    this._armed = null;
    this._key = '';
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
  }

  static getStubConfig() { return {}; }

  getCardSize() { return 4; }

  set hass(hass) {
    this._hass = hass;
    const printers = this._printers();
    const key = JSON.stringify(printers.map((p) => [p.entity, p.state, p.attrs])) + this._armed;
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
      const chipClass = ['offline', 'unknown', 'removed', 'failed'].includes(p.state) ? 'bad' : live ? 'live' : '';
      const pct = a.progress != null && (live || p.state === 'finish') ? `${a.progress}%` : '';
      const ams = cfg.show_ams && Array.isArray(a.ams) && a.ams.length
        ? `<div class="ams">${a.ams.map((t) => `<span class="tray" title="${esc(t.type)}"><i style="background:${esc(t.colour || 'transparent')}"></i>${t.slot + 1} ${esc(t.type)}${t.remaining != null ? ` ${t.remaining}%` : ''}</span>`).join('')}</div>` : '';
      const id = esc(a.bruh_bambu_printer);
      const controls = cfg.show_controls && p.state !== 'offline' ? `<div class="controls">
          ${p.state === 'pause' ? `<button class="primary" data-act="resume_print" data-id="${id}">Resume</button>`
            : live ? `<button data-act="pause_print" data-id="${id}">Pause</button>` : ''}
          ${live ? `<button class="${this._armed === a.bruh_bambu_printer ? 'armed' : 'danger'}" data-stop="${id}">${this._armed === a.bruh_bambu_printer ? 'Tap again to stop' : 'Stop'}</button>` : ''}
          ${live ? `<select data-speed="${id}" aria-label="Speed">${SPEEDS.map((s) => `<option ${s === a.speed ? 'selected' : ''}>${s}</option>`).join('')}</select>` : ''}
          <button data-light="${id}" data-on="${a.chamber_light ? '0' : '1'}">${a.chamber_light ? 'Light off' : 'Light on'}</button>
        </div>` : '';
      return `<div class="printer">
        <div class="head"><span class="name">${esc(a.printer_name || a.friendly_name)}</span>
          <span class="chip ${chipClass}">${esc(p.state)}</span></div>
        ${live || pct ? `<div class="row"><span class="pct">${pct}</span>
          <span class="muted">${esc(a.file || '')}${a.remaining_min != null && live ? ` · ${duration(a.remaining_min)} left · done ${finishAt(a.remaining_min)}` : ''}${a.layer != null && a.total_layers ? ` · layer ${a.layer}/${a.total_layers}` : ''}</span></div>
          <div class="bar"><i style="width:${Math.max(0, Math.min(100, a.progress || 0))}%"></i></div>` : ''}
        <div class="stats"><span>Nozzle <b>${temp(a.nozzle_c, a.nozzle_target_c)}</b></span>
          <span>Bed <b>${temp(a.bed_c, a.bed_target_c)}</b></span>
          ${a.chamber_c != null ? `<span>Chamber <b>${Math.round(a.chamber_c)}°</b></span>` : ''}
          ${a.hms_count ? `<span class="err">${a.hms_count} printer message${a.hms_count > 1 ? 's' : ''}</span>` : ''}</div>
        ${a.connection_error ? `<div class="err">${esc(a.connection_error)}</div>` : ''}
        ${ams}${controls}</div>`;
    }).join('') : `<div class="empty">No printers yet. Add one on the BRUH Bambu Studio panel's Printers tab.</div>`;
    const inner = `<div class="wrap">${cfg.title ? `<div class="name">${esc(cfg.title)}</div>` : ''}${body}
      ${this._error ? `<div class="err">${esc(this._error)}</div>` : ''}</div>`;
    this.shadowRoot.innerHTML = `<style>${css(morph)}</style>${morph ? inner : `<ha-card>${inner}</ha-card>`}`;
    this.shadowRoot.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () =>
      this._call(b.dataset.act, { printer: b.dataset.id })));
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
    description: 'Progress, time left, temperatures and AMS for your Bambu Lab printers, with pause, resume, stop, speed and light.',
    preview: true,
  });
}
