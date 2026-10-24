/* GardenRX — the garden's cards, for Lovelace and for Morph.
 *
 * Six elements from one file:
 *   custom:gardenrx-harvest-card    / custom:morph-gardenrx-harvest
 *   custom:gardenrx-spray-card      / custom:morph-gardenrx-spray
 *   custom:gardenrx-inventory-card  / custom:morph-gardenrx-inventory
 *
 * The Lovelace ones sit in an <ha-card> and take HA's theme; the Morph ones
 * take Morph's variables and fonts, draw no card chrome, write no empty-state
 * text and carry no hover tooltips (Morph's design rules). The integration
 * serves this file and loads it on every frontend page; the add-on also copies
 * it to /config/morph/cards when Morph is installed.
 *
 * Every number is an attribute of a GardenRX sensor, found by its `gardenrx`
 * attribute rather than its entity id, so a renamed sensor keeps its card.
 * Every press is a gardenrx.* service, answered over the connection the
 * dashboard already has — a card never reaches the add-on itself. A press that
 * changes the record takes two taps, the second within four seconds, because a
 * dialog would float over the page and one tap on "Mark sprayed" also takes
 * the spray out of the bottle.
 *
 * Plain custom elements, no imports: a card that needs a CDN is a card that
 * is blank the day it is down.
 */

const CARD_VERSION = '0.1.3';
const DOMAIN = 'gardenrx';

console.info(
  `%c GARDENRX CARDS %c ${CARD_VERSION} `,
  'background:#1f7a4d;color:#fff;font-weight:700;border-radius:3px 0 0 3px',
  'background:#16181d;color:#fff;border-radius:0 3px 3px 0',
);

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const num = (n, places = 1) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '–';
  return v.toLocaleString(undefined, { maximumFractionDigits: places, minimumFractionDigits: 0 });
};
const money = (n) => (Number.isFinite(Number(n)) ? `$${Number(n).toFixed(2)}` : '–');

function ago(days) {
  if (days == null) return '';
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(String(iso).length <= 10 ? `${iso}T12:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** The GardenRX sensor carrying `gardenrx: <kind>`, or one named in config. */
function findSensor(hass, kind, configured) {
  if (!hass) return null;
  if (configured) return hass.states[configured] || null;
  for (const id of Object.keys(hass.states)) {
    if (!id.startsWith('sensor.')) continue;
    const s = hass.states[id];
    if (s.attributes && s.attributes.gardenrx === kind) return s;
  }
  return null;
}

const css = (morph) => `
  :host { display: block;
    --g-surface: ${morph ? 'var(--surface)' : 'var(--ha-card-background, var(--card-background-color, #fff))'};
    --g-sunk: ${morph ? 'var(--sunk)' : 'var(--secondary-background-color, #f1f3f5)'};
    --g-text: ${morph ? 'var(--text)' : 'var(--primary-text-color, #14202b)'};
    --g-muted: ${morph ? 'var(--muted)' : 'var(--secondary-text-color, #5b6b79)'};
    --g-line: ${morph ? 'var(--line)' : 'var(--divider-color, #d9e0e6)'};
    --g-accent: ${morph ? 'var(--lime)' : 'var(--success-color, #1f7a4d)'};
    --g-on-accent: ${morph ? 'var(--bg, #111)' : '#fff'};
    --g-warn: ${morph ? 'var(--amber)' : 'var(--warning-color, #b7791f)'};
    --g-bad: ${morph ? 'var(--rose)' : 'var(--error-color, #c62828)'};
    font-family: ${morph ? "'Manrope', sans-serif" : 'inherit'}; color: var(--g-text); }
  .wrap { padding: ${morph ? '4px 2px' : '16px'}; display: grid; gap: 14px; }
  .title { font-weight: 600; font-size: 15px; }
  .hero { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .big { font-family: ${morph ? "'Bricolage Grotesque', sans-serif" : 'inherit'};
    font-size: 30px; font-weight: 700; line-height: 1; }
  .muted { color: var(--g-muted); font-size: 13px; }
  .list { display: grid; gap: 8px; }
  .row { display: flex; align-items: center; gap: 10px; justify-content: space-between; min-height: 32px; }
  .row .grow { flex: 1; min-width: 0; }
  .name { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
  .bar { height: 6px; border-radius: 3px; background: var(--g-sunk); overflow: hidden; margin-top: 4px; }
  .bar > i { display: block; height: 100%; background: var(--g-accent); border-radius: 3px; }
  .bar.low > i { background: var(--g-bad); }
  .bar.mid > i { background: var(--g-warn); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: 12px; padding: 3px 9px; border-radius: 999px; background: var(--g-sunk); }
  .chip.bad { background: color-mix(in srgb, var(--g-bad) 16%, transparent); color: var(--g-bad); }
  .section { display: grid; gap: 8px; }
  .label { font-size: 12px; font-weight: 600; color: var(--g-muted); letter-spacing: .02em; }
  button, select, input { font: inherit; font-size: 14px; color: var(--g-text); }
  button { min-height: 44px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--g-line);
    background: var(--g-surface); cursor: pointer; }
  button.primary { background: var(--g-accent); border-color: var(--g-accent); color: var(--g-on-accent); font-weight: 600; }
  button.armed { background: var(--g-bad); border-color: var(--g-bad); color: #fff; }
  button:disabled { opacity: .55; cursor: default; }
  select, input { min-height: 44px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--g-line);
    background: var(--g-surface); min-width: 0; }
  @media (pointer: coarse) { select, input { font-size: 16px; } }
  .form { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
  .form .wide { grid-column: 1 / -1; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .err { color: var(--g-bad); font-size: 13px; }
  .ok { color: var(--g-accent); font-size: 13px; }
  .warn { color: var(--g-warn); font-size: 13px; }
  .empty { color: var(--g-muted); font-size: 13px; }
`;

class GardenCard extends HTMLElement {
  static morph = false;
  static kind = '';

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._armed = null;
    this._key = '';
    this._busy = false;
    this._note = null;
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
  }

  static getStubConfig() { return {}; }

  getCardSize() { return 4; }

  set hass(hass) {
    this._hass = hass;
    const s = findSensor(hass, this.constructor.kind, this._config && this._config.entity);
    this._sensor = s;
    // hass is set on every state change in the house; draw only when what
    // this card shows has moved.
    const key = JSON.stringify([s && s.state, s && s.attributes, this._armed, this._busy, this._note]);
    if (key === this._key) return;
    this._key = key;
    this._paint();
  }

  _redraw() { this._key = ''; if (this._hass) this.hass = this._hass; }

  /** A service call whose response the card reads. */
  async _call(service, data) {
    this._busy = true;
    this._note = null;
    this._redraw();
    try {
      const r = await this._hass.callWS({
        type: 'call_service', domain: DOMAIN, service, service_data: data, return_response: true,
      });
      return (r && r.response) || {};
    } catch (e) {
      this._note = { kind: 'err', text: (e && e.message) || String(e) };
      return null;
    } finally {
      this._busy = false;
      this._redraw();
    }
  }

  /** Two taps within four seconds; returns true on the second. */
  _confirm(id) {
    if (this._armed === id) {
      this._armed = null;
      clearTimeout(this._disarm);
      return true;
    }
    this._armed = id;
    clearTimeout(this._disarm);
    this._disarm = setTimeout(() => { this._armed = null; this._redraw(); }, 4000);
    this._redraw();
    return false;
  }

  _paint() {
    const morph = this.constructor.morph;
    // Keep whatever is being typed across a redraw.
    const active = this.shadowRoot.activeElement;
    const focusKey = active && active.dataset ? active.dataset.f : null;
    const inner = this._render(this._sensor, morph);
    this.shadowRoot.innerHTML = `<style>${css(morph)}</style>${morph ? inner : `<ha-card>${inner}</ha-card>`}`;
    this._bind();
    if (focusKey) {
      const el = this.shadowRoot.querySelector(`[data-f="${focusKey}"]`);
      if (el) el.focus();
    }
  }

  _noteHtml() {
    return this._note ? `<div class="${this._note.kind}">${esc(this._note.text)}</div>` : '';
  }

  _missing(morph, what) {
    return morph ? '' : `<div class="wrap"><div class="empty">No GardenRX ${what} sensor yet. Start the GardenRX add-on and set up the GardenRX integration.</div></div>`;
  }

  _render() { return ''; }
  _bind() {}
}

/* ── Harvest ─────────────────────────────────────────────────────────── */

class GardenHarvestCard extends GardenCard {
  static kind = 'harvest';

  setConfig(config) {
    super.setConfig({ show_form: true, crops: 6, recent: 5, ...(config || {}) });
    this._form = { crop: '', variety: '', weight: '', unit: 'lb', date: todayLocal() };
  }

  getCardSize() { return 6; }

  _render(s, morph) {
    if (!s) return this._missing(morph, 'harvest');
    const a = s.attributes || {};
    const cfg = this._config;
    const byCrop = (a.by_crop || []).slice(0, cfg.crops);
    const top = byCrop.reduce((m, c) => Math.max(m, Number(c.lb) || 0), 0) || 1;
    const crops = a.crops || [];
    const f = this._form;
    const chosen = crops.find((c) => String(c.id) === String(f.crop));
    const varieties = chosen ? chosen.varieties || [] : [];
    const recent = (a.recent || []).slice(0, cfg.recent);

    const totals = `<div class="hero"><span class="big">${num(s.state)} lb</span>
      <span class="muted">${money(a.total_value)} · ${a.picks || 0} pick${a.picks === 1 ? '' : 's'} in ${esc(a.year || '')}</span></div>`;

    const bars = byCrop.length ? `<div class="list">${byCrop.map((c) => `<div>
        <div class="row"><span class="name">${esc(c.crop)}</span>
          <span class="muted">${num(c.lb)} lb${c.value ? ` · ${money(c.value)}` : ''}</span></div>
        <div class="bar"><i style="width:${Math.max(3, Math.round((Number(c.lb) / top) * 100))}%"></i></div></div>`).join('')}</div>`
      : morph ? '' : '<div class="empty">Nothing picked yet this year.</div>';

    const form = cfg.show_form && crops.length ? `<div class="section"><div class="label">Log a harvest</div>
      <div class="form">
        <select data-f="crop" aria-label="Crop"><option value="">Crop…</option>
          ${crops.map((c) => `<option value="${c.id}" ${String(c.id) === String(f.crop) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>
        ${varieties.length ? `<select data-f="variety" aria-label="Variety"><option value="">Any variety</option>
          ${varieties.map((v) => `<option value="${v.id}" ${String(v.id) === String(f.variety) ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select>` : ''}
        <input data-f="weight" type="number" inputmode="decimal" min="0" step="any" placeholder="Amount" aria-label="Amount" value="${esc(f.weight)}">
        <select data-f="unit" aria-label="Unit">${(a.units || ['lb']).map((u) => `<option ${u === f.unit ? 'selected' : ''}>${esc(u)}</option>`).join('')}</select>
        <input data-f="date" type="date" aria-label="Date" value="${esc(f.date)}">
        <div class="actions wide"><button class="primary" data-act="log" ${this._busy || !f.crop || !(Number(f.weight) > 0) ? 'disabled' : ''}>Log harvest</button></div>
      </div></div>` : '';

    const picks = recent.length ? `<div class="section"><div class="label">Recent picks</div><div class="list">
      ${recent.map((h) => {
        const armed = this._armed === `h${h.id}`;
        return `<div class="row"><div class="grow"><div class="name">${esc(h.crop || 'Unknown crop')}${h.variety ? ` · ${esc(h.variety)}` : ''}</div>
          <div class="muted">${num(h.weight, 2)} ${esc(h.unit)} · ${esc(shortDate(h.harvested_at))}${h.value ? ` · ${money(h.value)}` : ''}</div></div>
          <button class="${armed ? 'armed' : ''}" data-del="${h.id}" aria-label="Delete this pick" ${this._busy ? 'disabled' : ''}>${armed ? 'Tap again' : 'Delete'}</button></div>`;
      }).join('')}</div></div>` : '';

    return `<div class="wrap">${cfg.title ? `<div class="title">${esc(cfg.title)}</div>` : ''}
      ${totals}${bars}${form}${this._noteHtml()}${picks}</div>`;
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll('[data-f]').forEach((el) => {
      const ev = el.tagName === 'SELECT' || el.type === 'date' ? 'change' : 'input';
      el.addEventListener(ev, () => {
        this._form[el.dataset.f] = el.value;
        if (el.dataset.f === 'crop') this._form.variety = '';
        // Typing in the amount box only toggles the button; a full redraw
        // per keystroke would be wasted work.
        if (el.dataset.f === 'weight') {
          const btn = root.querySelector('[data-act="log"]');
          if (btn) btn.disabled = this._busy || !this._form.crop || !(Number(this._form.weight) > 0);
          return;
        }
        this._redraw();
      });
    });
    const log = root.querySelector('[data-act="log"]');
    if (log) log.addEventListener('click', () => this._log());
    root.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!this._confirm(`h${b.dataset.del}`)) return;
      const r = await this._call('delete_harvest', { id: Number(b.dataset.del) });
      if (r) this._note = { kind: 'ok', text: 'Pick deleted.' };
      this._redraw();
    }));
  }

  async _log() {
    const f = this._form;
    const data = { crop: Number(f.crop), weight: Number(f.weight), unit: f.unit, date: f.date };
    if (f.variety) data.variety = Number(f.variety);
    const r = await this._call('log_harvest', data);
    if (!r) return;
    this._form = { ...f, weight: '' };
    this._note = r.phi_warning
      ? { kind: 'warn', text: `Logged. ${r.phi_warning}` }
      : { kind: 'ok', text: `Logged ${num(r.weight, 2)} ${r.unit} of ${r.crop}${r.value ? ` (${money(r.value)})` : ''}.` };
    this._redraw();
  }
}

/* ── Sprays ──────────────────────────────────────────────────────────── */

class GardenSprayCard extends GardenCard {
  static kind = 'sprays';

  setConfig(config) {
    super.setConfig({ show_queue: true, show_phi: true, ...(config || {}) });
  }

  getCardSize() { return 5; }

  _render(s, morph) {
    if (!s) return this._missing(morph, 'spray');
    const a = s.attributes || {};
    const cfg = this._config;
    const last = s.state && s.state !== 'unknown' && s.state !== 'unavailable'
      ? `<div class="hero"><span class="big">${esc(ago(a.days_ago))}</span>
          <span class="muted">last spray · ${esc(shortDate(s.state))}${a.this_year ? ` · ${a.this_year} this year` : ''}</span></div>
        <div class="muted">${esc((a.products || []).join(', '))}${(a.crops || []).length ? ` on ${esc(a.crops.join(', '))}` : ''}</div>`
      : morph ? '' : '<div class="empty">No sprays logged yet.</div>';

    const phi = cfg.show_phi && (a.phi || []).length ? `<div class="section"><div class="label">Don't harvest yet</div>
      <div class="chips">${a.phi.map((p) => `<span class="chip bad">${esc(p.crop)} · ${p.days_left} day${p.days_left === 1 ? '' : 's'}${p.clear_date ? ` (from ${esc(shortDate(p.clear_date))})` : ''}</span>`).join('')}</div></div>` : '';

    const queued = cfg.show_queue && (a.queued || []).length ? `<div class="section"><div class="label">Queued</div><div class="list">
      ${a.queued.map((q) => {
        const done = this._armed === `d${q.id}`;
        const drop = this._armed === `r${q.id}`;
        return `<div class="section"><div class="row"><div class="grow">
            <div class="name">${esc((q.products || []).map((p) => p.brand).join(' + ') || 'Spray')}</div>
            <div class="muted">${esc((q.crops || []).map((c) => c.name).join(', '))}${q.planned_date ? ` · planned ${esc(shortDate(q.planned_date))}` : ''}</div>
            ${q.notes ? `<div class="muted">${esc(q.notes)}</div>` : ''}</div></div>
          <div class="actions">
            <button class="${done ? 'armed' : 'primary'}" data-done="${q.id}" ${this._busy ? 'disabled' : ''}>${done ? 'Tap again to log it' : 'Mark sprayed'}</button>
            <button class="${drop ? 'armed' : ''}" data-drop="${q.id}" ${this._busy ? 'disabled' : ''}>${drop ? 'Tap again' : 'Remove'}</button>
          </div></div>`;
      }).join('')}</div></div>` : '';

    return `<div class="wrap">${cfg.title ? `<div class="title">${esc(cfg.title)}</div>` : ''}
      ${last}${phi}${this._noteHtml()}${queued}</div>`;
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll('[data-done]').forEach((b) => b.addEventListener('click', async () => {
      if (!this._confirm(`d${b.dataset.done}`)) return;
      const data = { id: Number(b.dataset.done) };
      if (this._config.volume_gallons) data.volume_gallons = Number(this._config.volume_gallons);
      const r = await this._call('complete_queued_spray', data);
      if (r) this._note = { kind: 'ok', text: `Spray logged${r.deducted && r.deducted.length ? `; ${r.deducted.join(', ')} taken from stock` : ''}.` };
      this._redraw();
    }));
    root.querySelectorAll('[data-drop]').forEach((b) => b.addEventListener('click', async () => {
      if (!this._confirm(`r${b.dataset.drop}`)) return;
      const r = await this._call('delete_queued_spray', { id: Number(b.dataset.drop) });
      if (r) this._note = { kind: 'ok', text: 'Queued spray removed.' };
      this._redraw();
    }));
  }
}

/* ── Inventory ───────────────────────────────────────────────────────── */

class GardenInventoryCard extends GardenCard {
  static kind = 'inventory';

  setConfig(config) {
    super.setConfig({ max_items: 8, low_only: false, ...(config || {}) });
  }

  _render(s, morph) {
    if (!s) return this._missing(morph, 'stock');
    const a = s.attributes || {};
    const cfg = this._config;
    const items = (a.items || []).filter((i) => !cfg.low_only || i.low).slice(0, cfg.max_items);
    const low = Number(s.state) || 0;
    const head = `<div class="hero"><span class="big">${low}</span>
      <span class="muted">running low${(a.items || []).length ? ` of ${a.items.length} in stock` : ''}</span></div>`;
    const list = items.length ? `<div class="list">${items.map((i) => {
      const cls = i.pct == null ? '' : i.pct <= 20 ? 'low' : i.pct <= 50 ? 'mid' : '';
      return `<div><div class="row"><span class="name">${esc(i.product)}</span>
          <span class="muted">${num(i.quantity, 2)} ${esc(i.unit)}${i.pct != null ? ` · ${i.pct}%` : ''}</span></div>
        ${i.pct != null ? `<div class="bar ${cls}"><i style="width:${Math.max(2, i.pct)}%"></i></div>` : ''}</div>`;
    }).join('')}</div>` : morph ? '' : '<div class="empty">Nothing in stock yet. Add products on the GardenRX panel\'s Inventory page.</div>';
    return `<div class="wrap">${cfg.title ? `<div class="title">${esc(cfg.title)}</div>` : ''}${head}${list}</div>`;
  }
}

/* ── Morph flavours ──────────────────────────────────────────────────── */

class MorphGardenHarvest extends GardenHarvestCard { static morph = true; }
class MorphGardenSpray extends GardenSprayCard { static morph = true; }
class MorphGardenInventory extends GardenInventoryCard { static morph = true; }

// Guarded: Morph loads a changed card file again, and a page may define a
// name only once (and the integration loads this file too).
const ELEMENTS = [
  ['gardenrx-harvest-card', GardenHarvestCard],
  ['gardenrx-spray-card', GardenSprayCard],
  ['gardenrx-inventory-card', GardenInventoryCard],
  ['morph-gardenrx-harvest', MorphGardenHarvest],
  ['morph-gardenrx-spray', MorphGardenSpray],
  ['morph-gardenrx-inventory', MorphGardenInventory],
];
for (const [name, cls] of ELEMENTS) {
  if (!customElements.get(name)) customElements.define(name, cls);
}

window.customCards = window.customCards || [];
for (const [type, name, description] of [
  ['gardenrx-harvest-card', 'GardenRX harvest', "This year's harvest by crop, recent picks, and a form to log one."],
  ['gardenrx-spray-card', 'GardenRX sprays', 'The last spray, crops in a pre-harvest interval, and queued sprays to mark done.'],
  ['gardenrx-inventory-card', 'GardenRX stock', 'Treatment stock, lowest first.'],
]) {
  if (!window.customCards.some((c) => c.type === type)) {
    window.customCards.push({ type, name, description, preview: true });
  }
}
