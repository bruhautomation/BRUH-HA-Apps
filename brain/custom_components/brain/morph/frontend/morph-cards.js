// Morph's cards as Home Assistant cards (docs/design/morph-on-lovelace.md §2.3).
//
// Every kind in cards.js's TYPES is registered here as an ordinary Lovelace
// custom card, `custom:morph-<kind>-card`, so it goes anywhere a card goes:
// any view type, any stack, HA's card picker (under Custom cards, every name
// starting "Morph ·" so they sit together), and HA's own visual editor
// (`getConfigForm`, the schema HA draws for good cards). The faces are
// cards.js's own, drawn inside `<ha-card>` with Morph's tokens mapped onto the
// theme's variables (`.t-ha`), so any Home Assistant theme dresses them and a
// Morph theme (themes/morph.yaml) gives them Morph's palette.
//
// The grammar is Morph's: TAP does the main thing, SLIDE sets a level, HOLD
// (or a tap on a card with no main thing) opens it in place with its options
// and its history, and the card grows; HA's own more-info is one press away
// from an opened card. A card given `tap_action`, `hold_action` or
// `double_tap_action` does what HA's own cards do with them instead (the
// `hass-action` event HA handles for every card). This module is loaded on
// every page (frontend.add_extra_js_url) and defines nothing twice.
//
// SIZE IS HOME ASSISTANT'S. In a sections view every kind declares a size
// in rows and columns (`SIZES`, through `getGridOptions`), the person
// resizes it with HA's own handles, and the face FILLS whatever it is given:
// a strip becomes a taller slider, a reading's sparkline takes the height, a
// camera's picture fills the card, and a card too small for its full face
// drops its secondary lines (`data-h`, measured) rather than being cut off.
// Opening a card at a fixed height lets its grid cell grow for as long as it
// is open (the cell is HA's `.card.fit-rows`; when it cannot be found the
// opened part scrolls inside the card instead).

import { TYPES } from './cards.js';
import { CSS as STYLES, FIELD_FLOOR } from './styles.js';
import { esc, friendly, clamp, hue, HUES } from './util.js';
import { morph } from './morph-dom.js';
import * as history from './history.js';

export const PREFIX = 'morph-';
export const SUFFIX = '-card';
export const tagOf = (kind) => PREFIX + kind.replace(/_/g, '-') + SUFFIX;
export const DOCS = 'https://github.com/bruhautomation/BRUH-HA-Apps/blob/main/brain/DOCS.md#morph-cards';

// What each kind is to the card picker and the editor. `domains` filters the
// entity picker; `multi` is a card over a list of entities. A kind this
// house's own copy of cards.js adds is registered too (`kindInfo`).
export const KINDS = {
  light: { name: 'Light', description: 'A light as a strip: tap toggles, slide sets the brightness, hold for colour and history.', domains: ['light'] },
  light_group: { name: 'Light group', description: 'A room of lights in one strip, each light a lane; hold for each light.', domains: ['light'], group: true },
  fan: { name: 'Fan', description: 'Tap toggles, slide sets the speed.', domains: ['fan'] },
  cover: { name: 'Cover', description: 'Blinds, shades and garage doors. Slide sets the position; a garage door asks before it opens.', domains: ['cover'] },
  lock: { name: 'Lock', description: 'Tap to lock or unlock, with a second tap to confirm.', domains: ['lock'] },
  switch: { name: 'Switch', description: 'A switch, helper, siren or automation as a strip.', domains: ['switch', 'input_boolean', 'siren', 'automation'] },
  button: { name: 'Button', description: 'A button, script or scene to run, with when it last ran.', domains: ['button', 'input_button', 'script', 'scene'] },
  vacuum: { name: 'Vacuum', description: 'Start, dock and the state of a vacuum.', domains: ['vacuum'] },
  climate: { name: 'Thermostat', description: 'The temperature on a ruler with the target band; up to four script or scene buttons.', domains: ['climate'], actions: true },
  sensor: { name: 'Sensor', description: 'A reading with today’s sparkline; hold for its history.', domains: ['sensor'] },
  readings: { name: 'Readings', description: 'Several temperature or humidity sensors on one chart.', domains: ['sensor'], multi: true },
  meter: { name: 'Meter', description: 'An energy, water or gas meter: today, and the last seven days as bars.', domains: ['sensor'] },
  media: { name: 'Media', description: 'A media player: what is playing, play and pause, volume and source.', domains: ['media_player'] },
  camera: { name: 'Camera', description: 'A snapshot every ten seconds; opened, it streams.', domains: ['camera'] },
  list: { name: 'Openings', description: 'Doors, windows, motion and leaks as a list that says what needs you.', domains: ['binary_sensor'], multi: true },
  person: { name: 'Person', description: 'Who is home, and since when.', domains: ['person'] },
  weather: { name: 'Weather', description: 'Now and the forecast.', domains: ['weather'] },
  alarm: { name: 'Alarm', description: 'The alarm’s modes as buttons; disarming asks twice.', domains: ['alarm_control_panel'] },
  scenes: { name: 'Scenes', description: 'A row of scenes, with the one last set lit.', domains: ['scene'], multi: true },
  entity: { name: 'Entity', description: 'Any entity as a strip with its state.', domains: null },
  note: { name: 'Note', description: 'A line of words on the dashboard.', note: true },
};

// The size each kind starts at in a sections view (12 columns; a row is
// 56px and the gap 8px, so n rows is 64n - 8 px), and how small it may go.
// Measured off the faces in real Home Assistant (tests/realha): a strip is
// one row (an alarm too); a reading, a thermostat or a player two; a camera or a forecast three. A list's
// length is the house's, so it keeps HA's automatic height until somebody
// sets one.
export const SIZES = {
  strip: { columns: 6, min_columns: 3, rows: 1, min_rows: 1 },
  light_group: { columns: 12, min_columns: 6, rows: 1, min_rows: 1 },
  sensor: { columns: 6, min_columns: 3, rows: 2, min_rows: 1 },
  meter: { columns: 6, min_columns: 3, rows: 2, min_rows: 1 },
  media: { columns: 12, min_columns: 6, rows: 2, min_rows: 1 },
  alarm: { columns: 12, min_columns: 6, rows: 1, min_rows: 1 },
  climate: { columns: 12, min_columns: 6, rows: 2, min_rows: 2 },
  camera: { columns: 12, min_columns: 6, rows: 3, min_rows: 2 },
  weather: { columns: 12, min_columns: 6, rows: 3, min_rows: 1 },
  readings: { columns: 12, min_columns: 6, rows: 4, min_rows: 2 },
  list: { columns: 12, min_columns: 6, rows: 'auto', min_rows: 1 },
  scenes: { columns: 12, min_columns: 6, rows: 1, min_rows: 1 },
  note: { columns: 12, min_columns: 3, rows: 1, min_rows: 1 },
};
export const STRIPS = ['light', 'fan', 'cover', 'lock', 'switch', 'button', 'vacuum', 'person', 'entity'];
export function sizeOf(kind, T) {
  if (SIZES[kind]) return { ...SIZES[kind] };
  if (STRIPS.includes(kind)) return { ...SIZES.strip };
  // A house's own kind: its Morph size, one row per 64px it wanted.
  const it = (T && T.item) || {};
  const wide = it.full || it.span >= 2;
  return { columns: wide ? 12 : 6, min_columns: wide ? 6 : 3, rows: 'auto', min_rows: 1 };
}

// A kind this house's own copy of cards.js added: named and described from
// its key, any entity, so it is in HA's picker and editor like the rest.
export function kindInfo(kind) {
  if (KINDS[kind]) return KINDS[kind];
  const words = String(kind).replace(/[_-]+/g, ' ');
  return { name: words[0].toUpperCase() + words.slice(1), description: 'A card from this house\u2019s own Morph code.', domains: null, house: true };
}

// Morph's tokens on the theme's variables. A Morph theme sets the --morph-*
// palette; any other theme gets accents that read on light and dark alike.
export const HA_THEME = `
.t-ha{--bg:var(--primary-background-color);--surface:var(--ha-card-background,var(--card-background-color,#fff));--sunk:var(--secondary-background-color,rgba(127,127,127,.08));--line:var(--divider-color,rgba(127,127,127,.2));--line2:color-mix(in oklab,var(--primary-text-color,#888) 24%,transparent);--text:var(--primary-text-color);--muted:var(--secondary-text-color);--quiet:var(--morph-quiet,var(--secondary-text-color));--chip:color-mix(in oklab,var(--primary-text-color,#888) 7%,transparent);--hover:color-mix(in oklab,var(--primary-text-color,#888) 4%,transparent);--lpull:var(--primary-text-color);--ink:var(--morph-ink,var(--card-background-color,#fff));--amber:var(--morph-amber,#E5A04A);--sand:var(--morph-sand,#C4A86C);--sky:var(--morph-sky,#6EA2E6);--violet:var(--morph-violet,#9A84E4);--teal:var(--morph-teal,#2FA89D);--lime:var(--morph-lime,#8BB238);--rose:var(--morph-rose,#DE6E5D);--peach:var(--morph-peach,#DE8D58);--indigo:var(--morph-indigo,#7383DE)}
`;

// What changes because the card is in a Lovelace grid and not in Morph's
// layout engine: the tile is in the flow (the engine positioned it), the card
// is ha-card's, and Morph's own ring would draw a second border inside it.
// In a grid cell (`:host([grid])`, HA sets `layout = "grid"` in a sections
// view) the face fills the cell: every wrapper down to the face is the
// cell's height, a strip stretches, and the part of a box that is a picture
// (a sparkline, the week's bars, a camera, a chart) takes what is left. The
// measured height (`data-h`: xs under 80px, s under 136px) drops what does
// not fit, a line at a time, instead of cutting the card off.
export const LOCAL = `
:host{display:block}
:host([grid]){height:100%}
ha-card{overflow:hidden;height:100%}
.morph.mc{min-height:0;background:transparent;font-family:var(--ha-font-family-body,var(--primary-font-family,inherit));font-size:15px}
.mc .mtile{position:relative;inset:auto;border-radius:0;background:transparent;outline:none}
.mc .tc{position:relative}
:host([grid]) ha-card>div,:host([grid]) .morph.mc,:host([grid]) .mc .mtile{height:100%}
:host([grid]) .mc .tc{height:100%;display:flex;flex-direction:column}
:host([grid]) .mc .face{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
:host([grid]) .mc .face>*{flex:1 1 auto;min-height:0}
:host([grid]) .mc .strip{height:auto;min-height:0}
:host([grid]) .mc .box,:host([grid]) .mc .camtile{min-height:0;overflow:hidden}
:host([grid]) .mc .box>svg:last-child,:host([grid]) .mc .box>.cols:last-child,:host([grid]) .mc .box>div:last-child:empty{flex:1 1 auto;min-height:12px;margin-top:auto}
:host([grid]) .mc .box>.cols:last-child{height:auto!important;align-items:flex-end}
:host([grid]) .mc .box>svg:last-child{height:auto!important}
:host([grid]) .mc .box>:last-child{margin-top:auto}
:host([grid]) .mc .box.ov .ovrow{flex:1 1 auto;min-height:60px}
:host([grid]) .mc .box.ov .ovplot,:host([grid]) .mc .box.ov .ovplot svg{height:100%!important}
:host([grid]) .mc .camtile{display:flex;flex-direction:column}
:host([grid]) .mc .campic{flex:1 1 auto;height:auto;min-height:40px}
:host([grid]) .mc .notecard,:host([grid]) .mc .note{height:100%}
:host([grid]) .mc .box>*{flex-shrink:0}
:host([grid]) .mc.open .face{flex:0 0 auto}
:host([grid]) .mc.open .more{flex:1 1 auto;min-height:0;overflow:auto}
:host([opened]) ha-card>div,:host([opened]) .morph.mc,:host([opened]) .mc .mtile,:host([opened]) .mc .tc{height:auto}
:host([opened]) .mc.open .more{overflow:visible}
.mc[data-h="s"] .box>.row.small:last-child:not(.cl-acts){display:none}
:host([grid]) .mc .chart svg{max-height:none}
.mc[data-h="s"] .box>svg:last-child,.mc[data-h="s"] .box>.cols:last-child{min-height:8px}
.mc[data-h="xs"] .box{flex-direction:row;align-items:center;gap:10px;padding:0 14px}
.mc[data-h="xs"] .box>*:not(:first-child):not(.rowb){display:none}
.mc[data-h="xs"] .box>:first-child{flex:1 1 auto;min-width:0}
.mc[data-h="xs"] .box>.rowb{flex:0 0 auto}
.mc[data-h="xs"] .box .mid,.mc[data-h="xs"] .box .big{font-size:20px}
.mc[data-h="xs"] .camhead{display:none}
.mc[data-w="narrow"] .sline .nv span,.mc[data-w="narrow"] .box .sm{display:none}
.mc .mcicon{flex-shrink:0;display:inline-flex}
.mc .mcdetail:empty{display:none}
.mc .strip,.mc .box,.mc .camtile{box-shadow:none!important;border-radius:0}
.mc .more{padding:4px 14px 14px}
.mc .hint{display:none}
.mc .moreinfo{display:flex;gap:0 18px;flex-wrap:wrap;margin-top:6px}
.mc .mcerr{padding:14px 16px}
`;

let SHEET = null;
function sheet() {
  if (SHEET !== null) return SHEET;
  try {
    SHEET = new CSSStyleSheet();
    SHEET.replaceSync(STYLES + HA_THEME + LOCAL + FIELD_FLOOR);
  } catch (e) {
    SHEET = false; // an older browser: a <style> per card
  }
  return SHEET;
}

const asList = (v) => (Array.isArray(v) ? v : v == null || v === '' ? [] : [v])
  .map((x) => (typeof x === 'string' ? x : x && typeof x === 'object' ? x.entity : null))
  .filter((x) => typeof x === 'string' && x);

let SEQ = 0;

// A Lovelace config as the card cards.js draws. `room` is the section's
// title Morph used to shorten names ("Kitchen Cans" in the Kitchen is "Cans").
export function toCard(kind, config, id) {
  const c = config || {};
  const card = { id: id || 'mc', type: kind };
  if (c.entity) card.entity = String(c.entity);
  const ents = asList(c.entities);
  if (ents.length) card.entities = ents;
  if (c.name) card.name = String(c.name);
  if (c.text) card.text = String(c.text);
  if (HUES.includes(c.color)) card.color = c.color;
  card.options = { ...(c.options && typeof c.options === 'object' ? c.options : {}) };
  if (c.actions) card.options.actions = asList(c.actions);
  if (c.detail && typeof c.detail === 'object') card.options.detail = c.detail;
  if (typeof c.icon === 'string' && c.icon) card.icon = c.icon;
  return card;
}

// Why a config cannot be drawn, in words, or ''.
export function problem(kind, config) {
  if (!TYPES[kind]) return `Morph has no card kind "${kind}".`;
  const k = kindInfo(kind);
  const c = config || {};
  if (k.note) return c.text ? '' : 'A note needs its text.';
  if (k.multi) return asList(c.entities).length ? '' : 'Choose at least one entity.';
  if (k.house) return '';
  return c.entity ? '' : 'Choose an entity.';
}

const LABELS = { entity: 'Entity', entities: 'Entities', name: 'Name', icon: 'Icon', room: 'Room', color: 'Colour', text: 'Text', actions: 'Buttons (scripts, scenes or buttons, up to four)',
  interactions: 'Interactions', tap_action: 'Tap', hold_action: 'Hold', double_tap_action: 'Double tap', detail: 'Card shown when it is opened' };
const HELPERS = { room: 'The room it sits in: a name that starts with it is shortened ("Kitchen Cans" reads "Cans").', color: 'Leave empty to colour it by what it is.',
  icon: 'Leave empty for Morph\u2019s own moving icon.',
  tap_action: 'Leave empty for Morph\u2019s own: tap does the main thing (toggle, run, open).',
  hold_action: 'Leave empty for Morph\u2019s own: hold opens the card in place with its options and history.',
  detail: 'Any Lovelace card (its YAML), shown under the card while it is open: a graph, a history, another card.' };

// The interactions every card has, in HA's own words and selectors (the
// tile card's `ui_action`), folded under one heading like HA's own editors.
const INTERACTIONS = {
  name: 'interactions', type: 'expandable', flatten: true, title: 'Interactions', icon: 'mdi:gesture-tap',
  schema: [
    { name: 'tap_action', selector: { ui_action: {} } },
    { name: 'hold_action', selector: { ui_action: {} } },
    { name: 'double_tap_action', selector: { ui_action: {} } },
  ],
};

// HA's visual editor draws this (ha-form): the same editor every good card
// has, and EVERY key a Morph card reads is in it, so nothing is YAML-only.
export function configForm(kind) {
  const k = kindInfo(kind);
  const filter = k.domains ? { filter: [{ domain: k.domains }] } : {};
  const schema = [];
  if (k.note) {
    schema.push({ name: 'text', required: true, selector: { text: { multiline: true } } });
  } else if (k.multi) {
    schema.push({ name: 'entities', required: true, selector: { entity: { multiple: true, ...filter } } });
    schema.push({ name: 'name', selector: { text: {} } });
  } else {
    schema.push({ name: 'entity', required: !k.house, selector: { entity: { ...filter } } });
    schema.push({ name: 'name', selector: { text: {} } });
  }
  if (!k.note) schema.push({ name: 'icon', selector: { icon: {} }, context: { icon_entity: 'entity' } });
  if (k.actions) schema.push({ name: 'actions', selector: { entity: { multiple: true, filter: [{ domain: ['script', 'scene', 'button', 'input_button'] }] } } });
  if (!k.note) {
    schema.push({ type: 'grid', name: '', schema: [
      { name: 'room', selector: { text: {} } },
      { name: 'color', selector: { select: { mode: 'dropdown', options: HUES.map((h) => ({ value: h, label: h[0].toUpperCase() + h.slice(1) })) } } },
    ] });
  }
  if (!k.note) {
    schema.push(INTERACTIONS);
    schema.push({ name: 'detail', selector: { object: {} } });
  }
  return {
    schema,
    computeLabel: (s) => LABELS[s.name] || s.title || s.name,
    computeHelper: (s) => HELPERS[s.name],
  };
}

// What the picker shows before anyone chooses: the first fitting entity.
export function stubConfig(kind, hass) {
  const k = kindInfo(kind);
  const type = 'custom:' + tagOf(kind);
  if (k.note) return { type, text: 'A note for the house.' };
  const states = (hass && hass.states) || {};
  const ids = Object.keys(states).sort();
  const fits = (e) => !k.domains || k.domains.includes(e.split('.')[0]);
  let pick = ids.filter(fits);
  if (k.group) pick = pick.filter((e) => Array.isArray(states[e].attributes && states[e].attributes.entity_id));
  if (kind === 'meter') pick = pick.filter((e) => ['energy', 'water', 'gas'].includes(states[e].attributes.device_class));
  if (kind === 'readings') pick = pick.filter((e) => ['temperature', 'humidity'].includes(states[e].attributes.device_class));
  if (kind === 'list') pick = pick.filter((e) => ['door', 'window', 'garage_door', 'opening', 'motion', 'moisture'].includes(states[e].attributes.device_class));
  if (k.multi) return { type, entities: pick.slice(0, 4) };
  return { type, entity: pick[0] || '' };
}

// Masonry's measure: 50px a unit (HA's CARD_SIZE_HEIGHT).
const SIZE = (kind, T) => { const s = sizeOf(kind, T); return typeof s.rows === 'number' ? Math.max(1, Math.round((s.rows * 64 - 8) / 50)) : (T.item.full || T.item.span >= 2 ? 3 : 1); };

// The entities whose state a card draws, so a new `hass` redraws only the
// cards it concerns.
export function watched(card, hass) {
  const out = new Set();
  if (card.entity) out.add(card.entity);
  (card.entities || []).forEach((e) => out.add(e));
  ((card.options && card.options.actions) || []).forEach((e) => out.add(typeof e === 'string' ? e : e && e.entity));
  const st = card.entity && hass && hass.states[card.entity];
  const members = st && st.attributes && st.attributes.entity_id;
  if (Array.isArray(members)) members.forEach((e) => out.add(e));
  out.delete(undefined);
  return out;
}

export class MorphCard extends HTMLElement {
  static get kind() { return 'entity'; }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._id = 'mc' + (SEQ += 1);
    this._open = false;
    this._preview = null;
    this._member = null;
    this._H = {};
    this._confirm = null;
    this._g = null;
    this._raf = 0;
    this._layout = '';
    this._detail = null;
    this._grown = null;
    const sh = sheet();
    if (sh) this.shadowRoot.adoptedStyleSheets = [sh];
    else this.shadowRoot.innerHTML = `<style>${STYLES + HA_THEME + LOCAL + FIELD_FLOOR}</style>`;
    // ha-card is made once and only what is inside it is redrawn: the
    // in-place redraw (morph-dom) never descends into a custom element.
    const card = document.createElement('ha-card');
    this._root = document.createElement('div');
    card.appendChild(this._root);
    this.shadowRoot.appendChild(card);
    this._haCard = card;
    // What the cell gives the card, measured: the face drops lines to fit.
    if (typeof ResizeObserver === 'function') {
      this._ro = new ResizeObserver(() => this._measure());
      this._ro.observe(card);
    }
    const on = (n, f, o) => this.shadowRoot.addEventListener(n, f.bind(this), o);
    on('pointerdown', this._down); on('pointermove', this._move); on('pointerup', this._up); on('pointercancel', this._cancel);
    on('click', this._click); on('change', this._change); on('keydown', this._key);
    on('contextmenu', (e) => { if (this._g) e.preventDefault(); });
  }

  get kind() { return this.constructor.kind; }

  // HA says "grid" for a card in a sections view: the face fills the cell.
  set layout(v) { this._layout = v || ''; this.toggleAttribute('grid', this._layout === 'grid'); }

  get layout() { return this._layout; }

  _measure() {
    const r = this._haCard.getBoundingClientRect();
    const box = this._root.firstElementChild;
    if (!box || !r.height) return;
    const fixed = this._layout === 'grid' && !this._open;
    const h = !fixed ? '' : r.height < 80 ? 'xs' : r.height < 136 ? 's' : '';
    const w = r.width && r.width < 180 ? 'narrow' : '';
    if ((box.dataset.h || '') !== h) { if (h) box.dataset.h = h; else delete box.dataset.h; }
    if ((box.dataset.w || '') !== w) { if (w) box.dataset.w = w; else delete box.dataset.w; }
  }

  setConfig(config) {
    if (!config || typeof config !== 'object') throw new Error('Invalid configuration');
    this._config = { ...config };
    this._card = toCard(this.kind, this._config, this._id);
    if (this._detail && JSON.stringify(this._detail.cfg) !== JSON.stringify(this._card.options.detail || null)) this._detail = null;
    this._draw();
  }

  set hass(h) {
    const prev = this._hass;
    this._hass = h;
    if (this._detail && this._detail.el) this._detail.el.hass = h;
    if (!this._card) return;
    if (!prev || prev.themes !== h.themes || [...watched(this._card, h)].some((e) => prev.states[e] !== h.states[e])) {
      if (this._preview != null && this._previewAt && Date.now() - this._previewAt > 400) this._preview = null;
      this._draw();
    }
  }

  get hass() { return this._hass; }

  connectedCallback() {
    if (!this._unlisten) this._unlisten = history.listen(() => this._draw());
    this._draw();
  }

  disconnectedCallback() {
    if (this._unlisten) { this._unlisten(); this._unlisten = null; }
    if (this._open) this._shrink();
  }

  getCardSize() { return SIZE(this.kind, TYPES[this.kind] || TYPES.entity) + (this._open ? 4 : 0); }

  // Sections view: the kind's size (SIZES), which the person changes with
  // HA's own handles; the face fills whatever it is given.
  getGridOptions() { return sizeOf(this.kind, TYPES[this.kind] || TYPES.entity); }

  static getConfigForm() { return configForm(this.kind); }

  static getStubConfig(hass) { return stubConfig(this.kind, hass); }

  ctx() {
    const T = TYPES[this.kind] || TYPES.entity;
    const hass = this._hass;
    const card = this._card;
    const st = card.entity ? hass.states[card.entity] || null : null;
    const name = card.name || (card.entity ? friendly(hass, card.entity) : kindInfo(this.kind).name || '');
    const ctx = { hass, card, st, sec: { title: this._config.room || '' }, name, open: this._open, member: this._member,
      H: this._H, preview: this._preview, memberPreview: null,
      confirm: this._confirm && this._confirm.until > Date.now() ? this._confirm.text : '', night: false };
    ctx.accent = card.color ? hue(card.color) : T.accent(ctx);
    ctx.hint = '';
    return { T, ctx };
  }

  _draw() {
    if (this._raf) return;
    const run = () => { this._raf = 0; this._render(); };
    this._raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(run) : (run(), 0);
  }

  _render() {
    if (!this._hass || !this._card) return;
    const why = problem(this.kind, this._config);
    let html;
    if (why) {
      html = `<div class="morph mc t-ha"><p class="sm mcerr">${esc(why)}</p></div>`;
    } else {
      let face = '', more = '';
      let aria = '';
      try {
        const { T, ctx } = this.ctx();
        face = withIcon(T.face(ctx), this._card.icon);
        if (this._open && !T.noOpen) more = `<div class="more rise">${T.more(ctx)}${this._card.options.detail ? '<div class="mcdetail" data-morph-keep></div>' : ''}${this._moreInfo(ctx)}</div>`;
        const slide = T.slide ? T.slide(ctx) : null;
        const tap = T.tap ? T.tap(ctx) : null;
        const role = slide ? 'slider' : tap && !tap.confirm ? 'switch' : 'button';
        aria = ` tabindex="0" role="${role}" aria-label="${esc(ctx.name)}"${role === 'slider' ? ` aria-valuemin="0" aria-valuemax="100" aria-valuenow="${esc(slide.get())}"` : ''}${role === 'button' ? ` aria-expanded="${this._open}"` : ''}`;
      } catch (e) {
        face = `<div class="box"><span class="sm">This card could not be drawn: ${esc((e && e.message) || e)}</span></div>`;
      }
      html = `<div class="morph mc t-ha${this._open ? ' open' : ''}"><div class="mtile"${aria}><div class="tc"><div class="face" data-face>${face}</div>${more}</div></div></div>`;
    }
    if (!this._root.firstElementChild) this._root.innerHTML = html;
    else morph(this._root, html, this.shadowRoot);
    this._mountDetail();
    this._measure();
  }

  // `detail`: a Lovelace card under the opened card, made once and kept.
  async _mountDetail() {
    const slot = this._root.querySelector('.mcdetail');
    const cfg = this._card && this._card.options.detail;
    if (!slot || !cfg) return;
    if (this._detail && this._detail.el) { if (this._detail.el.parentNode !== slot) slot.appendChild(this._detail.el); return; }
    if (this._detail) return; // on its way
    this._detail = { cfg, el: null };
    const mine = this._detail;
    try {
      const helpers = typeof window.loadCardHelpers === 'function' ? await window.loadCardHelpers() : null;
      if (!helpers || this._detail !== mine) return;
      const el = helpers.createCardElement(cfg);
      if (this._hass) el.hass = this._hass;
      mine.el = el;
      const now = this._root.querySelector('.mcdetail');
      if (now) now.appendChild(el);
    } catch (e) {
      mine.el = document.createElement('p');
      mine.el.className = 'sm';
      mine.el.textContent = `The card under this one could not be drawn: ${(e && e.message) || e}`;
    }
  }

  // HA's own dialog for what an opened card shows.
  _moreInfo(ctx) {
    const ids = ctx.card.entities || [];
    const eid = ctx.member || ctx.card.entity || (ids.length === 1 ? ids[0] : '');
    if (!eid || !this._hass.states[eid]) return '';
    return `<div class="moreinfo"><button type="button" class="wd" data-ctl="1" data-act="more-info" data-v="${esc(eid)}">Details</button></div>`;
  }

  _fire(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }

  _haptic(kind) { this._fire('haptic', kind); }

  _call(c) {
    if (!c || !this._hass) return;
    const p = this._hass.callService(c.domain, c.service, c.data || {});
    if (p && p.catch) p.catch((err) => this._fire('hass-notification', { message: `${c.domain}.${c.service}: ${(err && err.message) || err}` }));
  }

  toggleOpen(force) {
    const T = TYPES[this.kind] || TYPES.entity;
    if (T.noOpen) return;
    this._open = force == null ? !this._open : !!force;
    if (!this._open) { this._H = {}; this._member = null; }
    this._render();
    if (this._open) this._grow(); else this._shrink();
    this._fire('iron-resize');
  }

  // The grid cell this card sits in at a fixed height: HA's own `.card`
  // wrapper with `fit-rows`, the parent of hui-card. Null anywhere else.
  _cell() {
    let n = this.parentElement || null;
    for (let i = 0; i < 3 && n; i++, n = n.parentElement || (n.getRootNode && n.getRootNode().host) || null) {
      if (n.classList && n.classList.contains('fit-rows')) return n;
    }
    return null;
  }

  // Open at a fixed height: the cell grows to the opened card for as long
  // as it is open (rows of 64px, HA's own), and every card after it makes
  // room the way a sections view always does. Without a cell to grow (an
  // older or newer HA), the opened part scrolls inside the card.
  _grow() {
    const cell = this._cell();
    if (!cell) return;
    const fit = () => {
      if (!this._open) return;
      // The card's own height while open (`:host([opened])` lets it be its
      // content's, not the cell's), so growing never feeds itself.
      const want = Math.max(1, Math.ceil((this._root.getBoundingClientRect().height + 8) / 64));
      cell.style.setProperty('height', 'auto');
      cell.style.setProperty('min-height', `${want * 64 - 8}px`);
      cell.style.setProperty('grid-row', `span ${want}`);
    };
    this._grown = { cell, fit };
    this.setAttribute('opened', '');
    fit();
    if (typeof ResizeObserver === 'function') {
      this._grown.ro = new ResizeObserver(fit);
      this._grown.ro.observe(this._root);
    }
  }

  _shrink() {
    const g = this._grown;
    this.removeAttribute('opened');
    if (!g) return;
    if (g.ro) g.ro.disconnect();
    ['height', 'min-height', 'grid-row'].forEach((p) => g.cell.style.removeProperty(p));
    this._grown = null;
  }

  // HA's own actions, when the card has them: the event every HA card fires
  // and HA's page carries out (navigate, more-info, toggle, perform-action…).
  _action(kind) {
    const key = `${kind}_action`;
    const a = this._config && this._config[key];
    if (!a || typeof a !== 'object' || !a.action) return false;
    if (a.action === 'none') return true;
    this._fire('hass-action', { config: { entity: this._card.entity, ...this._config }, action: kind });
    return true;
  }

  tap() {
    if (this._action('tap')) return;
    const { T, ctx } = this.ctx();
    const t = T.tap ? T.tap(ctx) : null;
    if (!t) { this.toggleOpen(); return; }
    if (t.confirm) {
      if (this._confirm && this._confirm.until > Date.now()) { this._confirm = null; this._call(t); this._haptic('success'); this._render(); return; }
      this._confirm = { text: t.confirm, until: Date.now() + 4000 };
      this._haptic('warning');
      this._render();
      setTimeout(() => this._render(), 4100);
      return;
    }
    this._haptic('light');
    this._call(t);
  }

  _inControl(e) {
    const p = e.composedPath ? e.composedPath() : [];
    return p.some((n) => n && n.dataset && (n.dataset.ctl || n.dataset.act)) || p.some((n) => n && n.classList && n.classList.contains('more'));
  }

  _down(e) {
    if (e.button > 0 || this._inControl(e)) return;
    const face = this.shadowRoot.querySelector('[data-face]');
    if (!face) return;
    const { T, ctx } = this.ctx();
    const slide = T.slide ? T.slide(ctx) : null;
    this._g = { x: e.clientX, y: e.clientY, id: e.pointerId, w: face.getBoundingClientRect().width || 200, slide, from: slide ? slide.get() : 0, moved: false, sliding: false, held: false };
    this._g.timer = setTimeout(() => {
      if (!this._g || this._g.moved) return;
      this._g.held = true;
      this._haptic('medium');
      if (!this._action('hold')) this.toggleOpen();
    }, 500);
  }

  _move(e) {
    const g = this._g;
    if (!g || e.pointerId !== g.id) return;
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (!g.sliding && !g.moved && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
      g.moved = true;
      clearTimeout(g.timer);
      if (g.slide && Math.abs(dx) > Math.abs(dy)) {
        g.sliding = true;
        try { e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); } catch (err) { /* capture is a nicety */ }
      } else { this._g = null; return; }
    }
    if (g.sliding) {
      e.preventDefault();
      this._preview = Math.round(clamp(g.from + dx / g.w * 100, 0, 100));
      this._previewAt = Date.now();
      this._render();
    }
  }

  _up(e) {
    const g = this._g;
    if (!g || e.pointerId !== g.id) return;
    clearTimeout(g.timer);
    this._g = null;
    if (g.sliding) {
      if (g.slide && this._preview != null) { this._call(g.slide.call(this._preview)); this._haptic('selection'); }
      this._previewAt = Date.now();
      setTimeout(() => { if (this._previewAt && Date.now() - this._previewAt >= 1500) { this._preview = null; this._render(); } }, 1600);
      return;
    }
    if (!g.moved && !g.held) {
      const dbl = this._config && this._config.double_tap_action;
      if (!dbl || !dbl.action) { this.tap(); return; }
      if (this._dbl) { clearTimeout(this._dbl); this._dbl = 0; this._action('double_tap'); return; }
      this._dbl = setTimeout(() => { this._dbl = 0; this.tap(); }, 250);
    }
  }

  _cancel() {
    if (this._g) clearTimeout(this._g.timer);
    this._g = null;
  }

  _key(e) {
    if (e.target.closest && e.target.closest('[data-act],input,textarea,select')) return;
    const { T, ctx } = this.ctx();
    const slide = T.slide ? T.slide(ctx) : null;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.tap(); return; }
    if (e.key === 'Escape' && this._open) { this.toggleOpen(false); return; }
    if (slide && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      e.preventDefault();
      this._call(slide.call(clamp(slide.get() + (e.key === 'ArrowRight' ? 10 : -10), 0, 100)));
    }
  }

  _change(e) {
    const el = e.target;
    if (el.dataset && el.dataset.act === 'range') {
      const scale = parseFloat(el.dataset.scale || '1');
      this._call({ domain: el.dataset.domain, service: el.dataset.service, data: { entity_id: el.dataset.entity, [el.dataset.key]: Number(el.value) * scale } });
    }
  }

  _click(e) {
    const el = e.target.closest && e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act; const v = el.dataset.v;
    if (act === 'field') {
      const r = el.getBoundingClientRect();
      const h = Math.round(clamp((e.clientX - r.left) / r.width, 0, 1) * 360);
      const s = Math.round(clamp((e.clientY - r.top) / r.height, 0, 1) * 100);
      this._call({ domain: 'light', service: 'turn_on', data: { entity_id: el.dataset.entity, hs_color: [h, Math.max(8, s)] } });
      return;
    }
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') return;
    e.preventDefault();
    e.stopPropagation();
    switch (act) {
      case 'svc': {
        if (el.dataset.confirm) {
          const k = 'svc:' + el.dataset.service + el.dataset.data;
          if (!(this._confirm && this._confirm.key === k && this._confirm.until > Date.now())) {
            this._confirm = { key: k, until: Date.now() + 4000 }; el.textContent = el.dataset.confirm; return;
          }
          this._confirm = null;
        }
        let data = {};
        try { data = JSON.parse(el.dataset.data || '{}'); } catch (err) { data = {}; }
        this._call({ domain: el.dataset.domain, service: el.dataset.service, data });
        return;
      }
      case 'scene': this._call({ domain: 'scene', service: 'turn_on', data: { entity_id: v } }); return;
      case 'tgt': {
        const st = this._hass.states[this._card.entity]; if (!st) return;
        const unit = String((this._hass.config && this._hass.config.unit_system && this._hass.config.unit_system.temperature) || '');
        const step = st.attributes.target_temp_step || (unit.includes('F') ? 1 : 0.5);
        const cur = st.attributes.temperature != null ? st.attributes.temperature : st.attributes.target_temp_low;
        this._call({ domain: 'climate', service: 'set_temperature', data: { entity_id: this._card.entity, temperature: Math.round((cur + step * Number(v)) * 10) / 10 } });
        return;
      }
      case 'member': this._member = v; this._H = { depth: 0 }; this.toggleOpen(true); return;
      case 'more-info': this._fire('hass-more-info', { entityId: v }); return;
      case 'h-open': this._H = { depth: 1, day: null }; this._render(); return;
      case 'h-day': this._H = { depth: 1, day: Number(v) }; this._render(); return;
      case 'h-hour': this._H = { ...this._H, depth: 2, hour: Number(v) }; this._render(); return;
      case 'h-back': { const d = Number(v); this._H = d === 0 ? { depth: 0 } : { ...this._H, depth: d }; this._render(); return; }
      case 'r-focus': this._H = { focus: this._H.focus === v ? null : v }; this._render(); return;
      default:
    }
  }
}

// A face's own icon (the first one drawn) swapped for HA's when the card
// sets `icon` (an mdi: name): same size and colour, so the face reads the
// same with a person's icon in it.
export function withIcon(html, name) {
  if (!name || typeof name !== 'string') return html;
  return String(html).replace(/<svg aria-hidden="true" width="(\d+)"[^>]*?style="color:([^"]*)"[\s\S]*?<\/svg>/, (_, w, color) => `<span class="mcicon" style="color:${color}"><ha-icon icon="${esc(name)}" style="--mdc-icon-size:${w}px;width:${w}px;height:${w}px"></ha-icon></span>`);
}

// One element per kind, and one entry each in HA's card picker.
export function register(win = globalThis) {
  // Defined only when the name is free: this module runs again on a new
  // version, and HA's page must never meet a throwing define (nor a patched
  // one, which is why util.guardDefine is not used on HA's own registry).
  const define = (tag, El) => { if (!win.customElements.get(tag)) win.customElements.define(tag, El); };
  win.customCards = win.customCards || [];
  const listed = new Set(win.customCards.map((c) => c && c.type));
  // Every kind cards.js draws: Morph's own, and the ones a house's own copy
  // of cards.js adds (that copy is what this page was served), so a house
  // card is a card on HA's dashboards too, not a plain entity strip.
  const kinds = [...Object.keys(KINDS), ...Object.keys(TYPES).filter((k) => !KINDS[k] && k !== 'lovelace' && !(TYPES[k] && TYPES[k].host))];
  kinds.forEach((kind) => {
    if (!TYPES[kind]) return;
    const tag = tagOf(kind);
    const El = class extends MorphCard { static get kind() { return kind; } };
    define(tag, El);
    if (listed.has(tag)) return;
    const k = kindInfo(kind);
    win.customCards.push({
      type: tag,
      name: `Morph · ${k.name}`,
      description: k.description,
      preview: true,
      documentationURL: DOCS,
      getEntitySuggestion: k.note || k.multi ? undefined : (hass, entityId) => {
        if (k.domains && !k.domains.includes(String(entityId).split('.')[0])) return null;
        if (k.group && !Array.isArray(((hass.states[entityId] || {}).attributes || {}).entity_id)) return null;
        return { label: `Morph · ${k.name}`, config: { type: 'custom:' + tag, entity: entityId } };
      },
    });
  });
}

if (typeof window !== 'undefined' && window.customElements) register(window);
