/**
 * Morph's cards as Home Assistant cards (frontend/morph-cards.js), driven the
 * way Home Assistant drives a custom card: the element is created by its tag,
 * `setConfig` is called with a Lovelace config, `hass` is set, and the card
 * lives inside a stand-in `<ha-card>`. Checks:
 *
 *   - every kind is defined, listed in window.customCards as "Morph · …",
 *     answers getConfigForm (an entity selector) and getStubConfig;
 *   - every kind draws a face from the fixture house, with no error words;
 *   - the face takes the theme's colours (HA's variables, not Morph's own);
 *   - tap toggles a light, slide sets its brightness, hold opens it in
 *     place with Details, which fires hass-more-info;
 *   - a lock asks twice; a bad config says what is missing.
 *
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome node tests/manual/measure-morph-cards.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { house, FRONTEND } from './morph-fixture.mjs';

const ORIGIN = 'http://cards.test';
const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<style>
html{--primary-background-color:#fafafa;--card-background-color:#ffffff;--primary-text-color:#212121;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);--ha-font-family-body:Arial}
body{margin:0;padding:16px;background:var(--primary-background-color)}
#grid{display:grid;grid-template-columns:repeat(2,360px);gap:12px}
</style></head><body><div id="grid"></div>
<script>
window.__calls = []; window.__events = [];
customElements.define('ha-card', class extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }).innerHTML = '<style>:host{display:block;background:var(--card-background-color);border-radius:12px;border:1px solid var(--divider-color)}</style><slot></slot>'; }
});
let states = ${JSON.stringify(house())};
window.__hass = {
  states, config: { unit_system: { temperature: '°F' } }, themes: { darkMode: false },
  user: { is_admin: true },
  callService(domain, service, data) {
    window.__calls.push({ domain, service, data });
    const ids = [].concat((data && data.entity_id) || []);
    ids.forEach((e) => {
      const s = states[e]; if (!s) return;
      const n = { ...s, attributes: { ...s.attributes } };
      if (service === 'toggle') n.state = s.state === 'on' ? 'off' : 'on';
      if (service === 'turn_on') { n.state = 'on'; if (data.brightness_pct) n.attributes.brightness = Math.round(data.brightness_pct * 2.55); }
      if (service === 'unlock') n.state = 'unlocked';
      if (service === 'lock') n.state = 'locked';
      states = { ...states, [e]: n };
    });
    window.__hass = { ...window.__hass, states };
    document.querySelectorAll('#grid > *').forEach((c) => { c.hass = window.__hass; });
    return Promise.resolve();
  },
  callWS() { return Promise.resolve([]); },
  connection: { subscribeMessage: () => Promise.resolve(() => {}) },
};
// Home Assistant's root element and its connection, answering morph/types
// and morph/subscribe the way the integration does.
window.__types = { types: [], modules: [] };
window.__subs = [];
const root = document.createElement('home-assistant');
root.hass = { connection: {
  sendMessagePromise: (m) => Promise.resolve(m.type === 'morph/types' ? JSON.parse(JSON.stringify(window.__types)) : {}),
  subscribeMessage: (cb, m) => { if (m.type === 'morph/subscribe') window.__subs.push(cb); return Promise.resolve(() => {}); },
} };
document.body.appendChild(root);
window.__typesMoved = () => window.__subs.forEach((cb) => cb({ parts: ['types'] }));
// HA's card helpers: an element that shows the config it was made from.
customElements.define('hui-stub-card', class extends HTMLElement {
  setConfig(c) { this.cfg = c; this.textContent = 'STUB ' + JSON.stringify(c); }
  set hass(h) { this._h = h; }
  getCardSize() { return 3; }
});
window.loadCardHelpers = () => Promise.resolve({ createCardElement: (c) => { const e = document.createElement('hui-stub-card'); e.setConfig(c); return e; } });
['hass-more-info', 'haptic', 'iron-resize'].forEach((n) => document.addEventListener(n, (e) => window.__events.push({ n, d: e.detail })));
</script>
<script type="module" src="/morph_static/test/morph-ha.js"></script>
</body></html>`;

const context = await browser.newContext({ viewport: { width: 900, height: 1400 } });
await context.route(`${ORIGIN}/**`, async (r) => {
  const url = new URL(r.request().url());
  if (url.pathname === '/') return r.fulfill({ contentType: 'text/html', body: PAGE });
  const m = url.pathname.match(/^\/morph_static\/[^/]+\/(.+)$/);
  if (m) {
    try { return r.fulfill({ contentType: 'text/javascript', body: readFileSync(path.join(FRONTEND, path.basename(m[1])), 'utf8') }); } catch (e) { return r.fulfill({ status: 404 }); }
  }
  if (url.pathname.startsWith('/morph_types/')) {
    const v = url.searchParams.get('v');
    return r.fulfill({ contentType: 'text/javascript', body: `export default class extends HTMLElement { setConfig(c) { this.c = c; this.textContent = 'ELEMENT v${v} ' + c.label; } set hass(h) {} }` });
  }
  if (url.pathname.startsWith('/api/camera_proxy')) return r.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>' });
  return r.fulfill({ status: 404, body: '' });
});
const p = await context.newPage();
const errors = [];
p.on('pageerror', (e) => errors.push(String(e)));
p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await p.goto(`${ORIGIN}/`);
await p.waitForFunction(() => (window.customCards || []).length >= 21, null, { timeout: 8000 }).catch(() => fail('load', 'Morph cards were never listed in window.customCards'));

const listed = await p.evaluate(() => (window.customCards || []).filter((c) => !c.type.startsWith('morph-type-') && !['morph-cases-card', 'morph-ask-card'].includes(c.type)).map((c) => ({ type: c.type, name: c.name, preview: c.preview })));
if (listed.length !== 21) fail('picker', `expected 21 Morph cards listed, got ${listed.length}`);
listed.forEach((c) => { if (!/^Morph · /.test(c.name)) fail('picker', `${c.type} is named "${c.name}", not "Morph · …"`); });

// Every kind: defined, an editor schema, a stub, and a face drawn from it.
const kinds = await p.evaluate(async () => {
  const out = [];
  for (const c of window.customCards.filter((x) => !x.type.startsWith('morph-type-') && !['morph-cases-card', 'morph-ask-card'].includes(x.type))) {
    const El = customElements.get(c.type);
    const row = { type: c.type, defined: !!El };
    if (!El) { out.push(row); continue; }
    const form = El.getConfigForm && El.getConfigForm();
    row.schema = form && Array.isArray(form.schema) ? form.schema.map((s) => s.name) : null;
    row.selector = form && form.schema[0] && Object.keys(form.schema[0].selector || {})[0];
    const stub = El.getStubConfig(window.__hass);
    row.stub = stub;
    const el = document.createElement(c.type);
    el.setConfig(stub);
    el.hass = window.__hass;
    document.getElementById('grid').appendChild(el);
    out.push(row);
  }
  await new Promise((r) => setTimeout(r, 400));
  document.querySelectorAll('#grid > *').forEach((el, i) => {
    const root = el.shadowRoot;
    const face = root && root.querySelector('[data-face]');
    out[i].text = (root && root.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    out[i].face = !!(face && face.innerHTML.trim());
    out[i].h = el.getBoundingClientRect().height;
    out[i].grid = el.getGridOptions && el.getGridOptions();
  });
  return out;
});
for (const k of kinds) {
  const w = k.type;
  if (!k.defined) { fail(w, 'not defined'); continue; }
  if (!k.schema || !k.schema.length) fail(w, 'getConfigForm has no schema');
  if (w !== 'morph-note-card' && k.selector !== 'entity') fail(w, `first editor field is ${k.selector}, not an entity picker`);
  if (!k.stub || k.stub.type !== 'custom:' + w) fail(w, `stub config ${JSON.stringify(k.stub)}`);
  if (!k.face) fail(w, `draws no face (${k.text})`);
  if (/could not be drawn|Choose an entity|Choose at least/i.test(k.text)) fail(w, `says: ${k.text}`);
  if (k.h < 40) fail(w, `only ${k.h}px tall`);
  if (!k.grid || ![6, 12].includes(k.grid.columns)) fail(w, `grid options ${JSON.stringify(k.grid)}`);
}

// The theme is HA's: the card's text colour is --primary-text-color.
const ink = await p.evaluate(() => {
  const el = document.querySelector('morph-light-card');
  const m = el.shadowRoot.querySelector('.morph');
  return getComputedStyle(m).color;
});
if (ink !== 'rgb(33, 33, 33)') fail('theme', `text is ${ink}, not the theme's --primary-text-color`);

// Light: tap toggles, slide sets brightness, hold opens it in place.
async function fresh(cfg) {
  return p.evaluate((cfg) => {
    const el = document.createElement(cfg.type.slice(7));
    el.id = 'probe'; el.setConfig(cfg); el.hass = window.__hass;
    document.getElementById('probe')?.remove();
    document.body.prepend(el);
    window.__calls.length = 0; window.__events.length = 0;
    return true;
  }, cfg);
}
async function box() {
  return p.evaluate(() => { const r = document.getElementById('probe').shadowRoot.querySelector('[data-face]').getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
}
await fresh({ type: 'custom:morph-light-card', entity: 'light.kitchen_countertop' });
await p.waitForTimeout(200);
let b = await box();
await p.mouse.click(b.x + 30, b.y + b.h / 2);
await p.waitForTimeout(150);
let calls = await p.evaluate(() => window.__calls);
if (!calls.some((c) => c.domain === 'light' && c.service === 'toggle')) fail('light tap', `no toggle (${JSON.stringify(calls)})`);

await fresh({ type: 'custom:morph-light-card', entity: 'light.kitchen_countertop' });
await p.waitForTimeout(200);
b = await box();
await p.mouse.move(b.x + b.w * 0.2, b.y + b.h / 2);
await p.mouse.down();
for (let i = 1; i <= 10; i++) await p.mouse.move(b.x + b.w * (0.2 + 0.05 * i), b.y + b.h / 2);
await p.mouse.up();
await p.waitForTimeout(150);
calls = await p.evaluate(() => window.__calls);
const set = calls.find((c) => c.service === 'turn_on' && c.data.brightness_pct);
if (!set) fail('light slide', `no brightness set (${JSON.stringify(calls)})`);
else if (set.data.brightness_pct < 60 || set.data.brightness_pct > 100) fail('light slide', `brightness ${set.data.brightness_pct} after sliding half the width from 50%`);

await fresh({ type: 'custom:morph-light-card', entity: 'light.kitchen_countertop' });
await p.waitForTimeout(200);
b = await box();
const before = await p.evaluate(() => document.getElementById('probe').getBoundingClientRect().height);
await p.mouse.move(b.x + 30, b.y + b.h / 2);
await p.mouse.down();
await p.waitForTimeout(650);
await p.mouse.up();
await p.waitForTimeout(250);
const opened = await p.evaluate(() => {
  const el = document.getElementById('probe');
  return { h: el.getBoundingClientRect().height, more: !!el.shadowRoot.querySelector('.more'), details: !!el.shadowRoot.querySelector('[data-act="more-info"]'), calls: window.__calls.length };
});
if (!opened.more || opened.h <= before + 20) fail('light hold', `did not open in place (${before} → ${opened.h})`);
if (opened.calls) fail('light hold', 'a hold also toggled the light');
if (!opened.details) fail('light hold', 'no Details button');
else {
  await p.evaluate(() => document.getElementById('probe').shadowRoot.querySelector('[data-act="more-info"]').click());
  const ev = await p.evaluate(() => window.__events.find((e) => e.n === 'hass-more-info'));
  if (!ev || ev.d.entityId !== 'light.kitchen_countertop') fail('details', `hass-more-info not fired for the light (${JSON.stringify(ev)})`);
}

// A lock asks first.
const lockId = await p.evaluate(() => Object.keys(window.__hass.states).find((e) => e.startsWith('lock.')));
if (lockId) {
  await fresh({ type: 'custom:morph-lock-card', entity: lockId });
  await p.waitForTimeout(200);
  b = await box();
  await p.mouse.click(b.x + 30, b.y + b.h / 2);
  await p.waitForTimeout(120);
  const first = await p.evaluate(() => window.__calls.length);
  await p.mouse.click(b.x + 30, b.y + b.h / 2);
  await p.waitForTimeout(120);
  const second = await p.evaluate(() => window.__calls.length);
  if (first !== 0 || second !== 1) fail('lock', `calls after one tap ${first}, after two ${second}`);
}

// A config with nothing chosen says what is missing.
await fresh({ type: 'custom:morph-light-card' });
await p.waitForTimeout(200);
const said = await p.evaluate(() => document.getElementById('probe').shadowRoot.textContent);
if (!/Choose an entity/.test(said)) fail('empty config', `says "${said.trim().slice(0, 80)}"`);

// Card types: a template drawn by HA's helpers, then the type changes and
// every copy redraws; an element type from its own code.
const TPL = { slug: 'thermo-buttons', type: 'custom:morph-type-thermo-buttons', name: 'Thermostat with buttons', kind: 'template', rev: 1,
  variables: [{ name: 'entity', label: 'Thermostat', required: true, selector: { entity: { filter: [{ domain: 'climate' }] } } }, { name: 'title', default: 'Climate' }],
  card: { type: 'vertical-stack', title: '[[title]]', cards: [{ type: 'thermostat', entity: '[[entity]]' }] } };
await p.evaluate((t) => { window.__types = { types: [t], modules: [] }; window.__typesMoved(); }, TPL);
await p.waitForFunction(() => !!customElements.get('morph-type-thermo-buttons'), null, { timeout: 4000 }).catch(() => fail('types', 'morph-type-thermo-buttons never defined'));
const tpl = await p.evaluate(async () => {
  const El = customElements.get('morph-type-thermo-buttons');
  const listed = (window.customCards || []).find((c) => c.type === 'morph-type-thermo-buttons');
  const form = El.getConfigForm();
  const stub = El.getStubConfig(window.__hass);
  const mk = () => { const e = document.createElement('morph-type-thermo-buttons'); e.setConfig({ type: 'custom:morph-type-thermo-buttons', entity: 'climate.downstairs' }); e.hass = window.__hass; document.body.appendChild(e); return e; };
  const a = mk(); const b = mk();
  const none = document.createElement('morph-type-thermo-buttons'); none.setConfig({ type: 'custom:morph-type-thermo-buttons' }); document.body.appendChild(none);
  await new Promise((r) => setTimeout(r, 300));
  return { listed: listed && listed.name, form: form.schema.map((s) => s.name), stub, a: a.textContent, b: b.textContent, none: none.textContent };
});
if (tpl.listed !== 'Morph · Thermostat with buttons') fail('types', `picker name ${tpl.listed}`);
if (tpl.form.join() !== 'entity,title') fail('types', `editor fields ${tpl.form}`);
if (!/^climate\./.test(tpl.stub.entity || '') || tpl.stub.title !== 'Climate') fail('types', `stub ${JSON.stringify(tpl.stub)}`);
if (!tpl.a.includes('"entity":"climate.downstairs"') || !tpl.a.includes('"title":"Climate"')) fail('types', `template not expanded: ${tpl.a}`);
if (!/Choose Thermostat/.test(tpl.none)) fail('types', `a copy with nothing chosen says "${tpl.none}"`);
const changed = { ...TPL, rev: 2, card: { type: 'vertical-stack', title: '[[title]] now', cards: [{ type: 'thermostat', entity: '[[entity]]' }, { type: 'button', name: 'Boost' }] } };
await p.evaluate((t) => { window.__types = { types: [t], modules: [] }; window.__typesMoved(); }, changed);
await p.waitForTimeout(400);
const after = await p.evaluate(() => [...document.querySelectorAll('morph-type-thermo-buttons')].slice(0, 2).map((e) => e.textContent));
if (!after.every((t) => t.includes('Climate now') && t.includes('Boost'))) fail('types', `copies did not follow the changed type: ${after.join(' | ').slice(0, 200)}`);
const ELT = { slug: 'pets', type: 'custom:morph-type-pets', name: 'Pets', kind: 'element', rev: 5, module: '/morph_types/pets.js?v=5', variables: [{ name: 'label', default: 'Dogs' }] };
await p.evaluate((t) => { window.__types = { types: [t], modules: [] }; window.__typesMoved(); }, ELT);
await p.waitForTimeout(300);
const pets = await p.evaluate(async () => { const e = document.createElement('morph-type-pets'); e.setConfig({ type: 'custom:morph-type-pets' }); document.body.appendChild(e); await new Promise((r) => setTimeout(r, 400)); return e.textContent; });
if (pets !== 'ELEMENT v5 Dogs') fail('types', `element type drew "${pets}"`);
await p.evaluate((t) => { window.__types = { types: [{ ...t, rev: 6, module: '/morph_types/pets.js?v=6' }], modules: [] }; window.__typesMoved(); }, ELT);
await p.waitForTimeout(500);
const pets2 = await p.evaluate(() => document.querySelector('morph-type-pets').textContent);
if (pets2 !== 'ELEMENT v6 Dogs') fail('types', `element type did not follow its new code: "${pets2}"`);
const gone = await p.evaluate(async () => { window.__types = { types: [], modules: [] }; window.__typesMoved(); await new Promise((r) => setTimeout(r, 300)); return document.querySelector('morph-type-pets').textContent; });
if (!/no card type/.test(gone)) fail('types', `a copy of a deleted type says "${gone}"`);

if (errors.length) fail('console', errors.slice(0, 5).join(' | '));
if (process.env.SHOT) await p.screenshot({ path: process.env.SHOT, fullPage: true });
await browser.close();
if (problems.length) {
  console.log(`measure-morph-cards: ${problems.length} problem(s)`);
  problems.forEach((x) => console.log(' - ' + x));
  process.exit(1);
}
console.log('measure-morph-cards: ok (21 kinds)');
