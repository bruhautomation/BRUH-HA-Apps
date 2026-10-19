/* Playwright measure for the GardenRX cards, Lovelace and Morph.
 *
 *   node tests/manual/measure-gardenrx-cards.mjs
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \
 *     node tests/manual/measure-gardenrx-cards.mjs
 *
 * Loads the real card file into a real browser behind a stubbed `hass` (only
 * `ha-card` is stubbed — it is Home Assistant's element) and drives it: what
 * each card shows from the sensor attributes `sensor.py` publishes, what a
 * press sends, that a press which changes the record takes two taps, that the
 * Morph flavour draws no card chrome, no tooltips and no empty-state text,
 * and that every target is 44px and nothing overflows a phone.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CARD = readFileSync(fileURLToPath(new URL(
  '../../gardenrx/custom_components/gardenrx/frontend/gardenrx-cards.js', import.meta.url)), 'utf8');

const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };

/* The attributes sensor.py publishes, in the summary's own shapes. */
const HOUSE = {
  'sensor.gardenrx_harvest_this_year': {
    entity_id: 'sensor.gardenrx_harvest_this_year', state: '12.5',
    attributes: {
      gardenrx: 'harvest', year: 2026, total_value: 41.25, picks: 3,
      by_crop: [{ crop_id: 1, crop: 'Apples', lb: 10, count: 0, value: 30, picks: 2, last_at: '2026-07-14T12:00:00Z' },
        { crop_id: 2, crop: 'Peaches', lb: 2.5, count: 0, value: 11.25, picks: 1, last_at: '2026-07-10T12:00:00Z' }],
      recent: [{ id: 7, crop_id: 1, crop: 'Apples', variety: 'Liberty', weight: 4, unit: 'lb', lb: 4, value: 12, harvested_at: '2026-07-14T12:00:00Z', notes: null }],
      units: ['lb', 'oz', 'kg', 'g', 'ct'],
      crops: [{ id: 1, name: 'Apples', group: 'Pome Fruit', phi: { active: false }, varieties: [{ id: 11, name: 'Liberty' }] },
        { id: 2, name: 'Peaches', group: 'Stone Fruit', phi: { active: true }, varieties: [] }],
      friendly_name: 'GardenRX Harvest this year',
    },
  },
  'sensor.gardenrx_last_spray': {
    entity_id: 'sensor.gardenrx_last_spray', state: '2026-07-12',
    attributes: {
      gardenrx: 'sprays', days_ago: 3, products: ['Captan 80 WDG'], crops: ['Apples'], this_year: 4, recent: [],
      queued: [{ id: 5, planned_date: '2026-07-20', notes: 'cover spray', created_at: '2026-07-10T00:00:00Z',
        products: [{ product_id: 1, brand: 'Captan 80 WDG', rate: 1, unit: 'fl oz/gal' }], crops: [{ crop_id: 1, name: 'Apples' }] }],
      phi: [{ crop_id: 2, crop: 'Peaches', active: true, days_left: 4, clear_date: '2026-07-19', product: 'Bonide' }],
    },
  },
  'sensor.gardenrx_treatments_running_low': {
    entity_id: 'sensor.gardenrx_treatments_running_low', state: '1',
    attributes: {
      gardenrx: 'inventory',
      items: [{ id: 1, product_id: 1, product: 'Captan 80 WDG', quantity: 1, unit: 'fl oz', pct: 3, low: true },
        { id: 2, product_id: 2, product: 'Neem oil', quantity: 20, unit: 'fl oz', pct: 62, low: false }],
    },
  },
};
const EMPTY = {
  'sensor.gardenrx_harvest_this_year': { entity_id: 'sensor.gardenrx_harvest_this_year', state: '0',
    attributes: { gardenrx: 'harvest', year: 2026, total_value: 0, picks: 0, by_crop: [], recent: [], units: ['lb'], crops: [] } },
  'sensor.gardenrx_last_spray': { entity_id: 'sensor.gardenrx_last_spray', state: 'unknown',
    attributes: { gardenrx: 'sprays', queued: [], phi: [], products: [], crops: [] } },
  'sensor.gardenrx_treatments_running_low': { entity_id: 'sensor.gardenrx_treatments_running_low', state: '0',
    attributes: { gardenrx: 'inventory', items: [] } },
};

const b = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : { args: ['--no-sandbox'] });

const open = async (name, { width = 400, touch = false } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push(`${name}: page error — ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`${name}: console error — ${m.text()}`); });
  await page.setContent('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<style>body{margin:0;padding:8px;--surface:#fff;--sunk:#eee;--text:#111;--muted:#555;--line:#ccc;--lime:#3a3;--amber:#b80;--rose:#c33}</style>'
    + '</head><body><div id="host"></div></body></html>');
  await page.evaluate(() => {
    customElements.define('ha-card', class extends HTMLElement {
      connectedCallback() {
        if (!this.shadowRoot) this.attachShadow({ mode: 'open' }).innerHTML = '<style>:host{display:block}</style><slot></slot>';
      }
    });
    window.__calls = [];
    window.__hass = (states, answer) => ({
      states,
      callWS(msg) {
        window.__calls.push(msg);
        if (answer && answer.reject) return Promise.reject(new Error(answer.reject));
        return Promise.resolve({ response: (answer && answer.response) || { ok: true } });
      },
    });
  });
  await page.addScriptTag({ content: CARD });
  return { page, ctx };
};

const build = (page, tag, config, states, answer) => page.evaluate(async ([t, cfg, house, ans]) => {
  const card = document.createElement(t);
  window.__card = card;
  card.setConfig(cfg);
  card.hass = window.__hass(house, ans);
  document.getElementById('host').append(card);
  await new Promise((r) => setTimeout(r, 50));
}, [tag, config, states, answer ?? null]);

// What a person reads: the shadow root's text, less the stylesheet.
const text = (page) => page.evaluate(() => [...window.__card.shadowRoot.childNodes]
  .filter((n) => n.nodeName !== 'STYLE').map((n) => n.textContent).join(' ').replace(/\s+/g, ' '));
const click = (page, sel) => page.evaluate(async (s) => {
  const el = window.__card.shadowRoot.querySelector(s);
  if (!el) return false;
  el.click();
  await new Promise((r) => setTimeout(r, 50));
  return true;
}, sel);
const calls = (page) => page.evaluate(() => window.__calls);

const layout = async (page, name) => {
  const r = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    const small = [];
    for (const el of root.querySelectorAll('button, input, select')) {
      const box = el.getBoundingClientRect();
      if (box.width && box.height < 44) small.push(`${el.tagName.toLowerCase()} ${box.height.toFixed(0)}px`);
    }
    return { small, overflow: document.documentElement.scrollWidth > window.innerWidth, titled: root.querySelectorAll('[title]').length };
  });
  check(!r.small.length, `${name}: targets under 44px — ${r.small.join(', ')}`);
  check(!r.overflow, `${name}: the page scrolls sideways`);
  return r;
};

/* ── Harvest ── */
for (const [tag, morph] of [['gardenrx-harvest-card', false], ['morph-gardenrx-harvest', true]]) {
  const { page, ctx } = await open(tag, { width: 390, touch: true });
  await build(page, tag, {}, HOUSE, { response: { ok: true, weight: 3, unit: 'lb', crop: 'Apples', value: 9, phi_warning: null } });
  const t = await text(page);
  check(t.includes('12.5 lb'), `${tag}: the season total is missing (${t.slice(0, 120)})`);
  check(t.includes('Apples') && t.includes('Peaches'), `${tag}: the crops are missing`);
  check(t.includes('Liberty'), `${tag}: the recent pick's variety is missing`);
  const chrome = await page.evaluate(() => !!window.__card.shadowRoot.querySelector('ha-card'));
  check(chrome === !morph, `${tag}: ${morph ? 'Morph draws no ha-card' : 'Lovelace sits in an ha-card'}`);
  const r = await layout(page, tag);
  if (morph) check(!r.titled, `${tag}: Morph carries no hover tooltips (title=)`);

  // Log a pick: crop, then the variety the crop offers, then an amount.
  const disabled = await page.evaluate(() => window.__card.shadowRoot.querySelector('[data-act="log"]').disabled);
  check(disabled, `${tag}: Log harvest is pressable before a crop and an amount are given`);
  await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const crop = root.querySelector('[data-f="crop"]');
    crop.value = '1'; crop.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 30));
    const v = window.__card.shadowRoot.querySelector('[data-f="variety"]');
    v.value = '11'; v.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 30));
    const w = window.__card.shadowRoot.querySelector('[data-f="weight"]');
    w.value = '3'; w.dispatchEvent(new Event('input'));
  });
  await click(page, '[data-act="log"]');
  await page.waitForTimeout(80);
  const logged = (await calls(page)).find((c) => c.service === 'log_harvest');
  check(logged && logged.domain === 'gardenrx' && logged.return_response === true
    && logged.service_data.crop === 1 && logged.service_data.variety === 11 && logged.service_data.weight === 3
    && logged.service_data.unit === 'lb' && /^\d{4}-\d{2}-\d{2}$/.test(logged.service_data.date),
  `${tag}: Log harvest sent ${JSON.stringify(logged)}`);
  check((await text(page)).includes('Logged 3 lb of Apples'), `${tag}: the result of the log is not said`);

  // Delete takes two taps.
  await click(page, '[data-del="7"]');
  check(!(await calls(page)).some((c) => c.service === 'delete_harvest'), `${tag}: one tap deleted a pick`);
  check((await text(page)).includes('Tap again'), `${tag}: the first tap does not say what the second does`);
  await click(page, '[data-del="7"]');
  await page.waitForTimeout(80);
  const del = (await calls(page)).find((c) => c.service === 'delete_harvest');
  check(del && del.service_data.id === 7, `${tag}: the second tap did not delete pick 7`);
  await ctx.close();
}

/* A PHI warning on a logged pick is said, as a warning. */
{
  const { page, ctx } = await open('phi');
  await build(page, 'gardenrx-harvest-card', {}, HOUSE,
    { response: { ok: true, weight: 1, unit: 'lb', crop: 'Peaches', phi_warning: 'Picked 4 days inside the pre-harvest interval for Bonide (safe from 2026-07-19).' } });
  await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const crop = root.querySelector('[data-f="crop"]'); crop.value = '2'; crop.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 30));
    const w = window.__card.shadowRoot.querySelector('[data-f="weight"]'); w.value = '1'; w.dispatchEvent(new Event('input'));
  });
  await click(page, '[data-act="log"]');
  await page.waitForTimeout(80);
  const warn = await page.evaluate(() => window.__card.shadowRoot.querySelector('.warn')?.textContent || '');
  check(warn.includes('pre-harvest interval'), `phi: the warning was not shown (${warn})`);
  await ctx.close();
}

/* A refusal is shown in the card, in the add-on's words. */
{
  const { page, ctx } = await open('refusal');
  await build(page, 'gardenrx-spray-card', {}, HOUSE, { reject: 'No queued spray has id 5 — it may already have been logged.' });
  await click(page, '[data-done="5"]');
  await click(page, '[data-done="5"]');
  await page.waitForTimeout(80);
  const err = await page.evaluate(() => window.__card.shadowRoot.querySelector('.err')?.textContent || '');
  check(err.includes('already have been logged'), `refusal: the error was not shown (${err})`);
  await ctx.close();
}

/* ── Sprays ── */
for (const [tag, morph] of [['gardenrx-spray-card', false], ['morph-gardenrx-spray', true]]) {
  const { page, ctx } = await open(tag, { width: 390, touch: true });
  await build(page, tag, { volume_gallons: 2 }, HOUSE, { response: { ok: true, deducted: ['2 fl oz'] } });
  const t = await text(page);
  check(t.includes('3 days ago'), `${tag}: the last spray's age is missing`);
  check(t.includes('Peaches · 4 days'), `${tag}: the pre-harvest interval is missing`);
  check(t.includes('cover spray'), `${tag}: the queued spray is missing`);
  const r = await layout(page, tag);
  if (morph) check(!r.titled, `${tag}: Morph carries no hover tooltips`);
  await click(page, '[data-done="5"]');
  check(!(await calls(page)).length, `${tag}: one tap logged a spray`);
  await click(page, '[data-done="5"]');
  await page.waitForTimeout(80);
  const done = (await calls(page)).find((c) => c.service === 'complete_queued_spray');
  check(done && done.service_data.id === 5 && done.service_data.volume_gallons === 2,
    `${tag}: Mark sprayed sent ${JSON.stringify(done)}`);
  check((await text(page)).includes('2 fl oz taken from stock'), `${tag}: what came out of stock is not said`);
  await ctx.close();
}

/* ── Stock ── */
for (const [tag] of [['gardenrx-inventory-card'], ['morph-gardenrx-inventory']]) {
  const { page, ctx } = await open(tag, { width: 390 });
  await build(page, tag, {}, HOUSE);
  const order = await page.evaluate(() => [...window.__card.shadowRoot.querySelectorAll('.name')].map((n) => n.textContent));
  check(order[0] === 'Captan 80 WDG', `${tag}: the lowest is not first (${order})`);
  check(await page.evaluate(() => !!window.__card.shadowRoot.querySelector('.bar.low')), `${tag}: a 3% bottle is not drawn as low`);
  await layout(page, tag);
  await ctx.close();
}

/* ── Empty houses: Lovelace says so, Morph draws nothing extra ── */
for (const tag of ['gardenrx-harvest-card', 'gardenrx-spray-card', 'gardenrx-inventory-card']) {
  const { page, ctx } = await open(`${tag}-empty`);
  await build(page, tag, {}, EMPTY);
  check(await page.evaluate(() => !!window.__card.shadowRoot.querySelector('.empty')), `${tag}: an empty garden says nothing in Lovelace`);
  await ctx.close();
  const morphTag = tag.replace('gardenrx-', 'morph-gardenrx-').replace('-card', '');
  const m = await open(`${morphTag}-empty`);
  await build(m.page, morphTag, {}, EMPTY);
  check(await m.page.evaluate(() => !window.__card.shadowRoot.querySelector('.empty')), `${morphTag}: Morph draws empty-state text`);
  await m.ctx.close();
}

/* No sensor at all: Lovelace explains, Morph stays out of the way. */
{
  const { page, ctx } = await open('missing');
  await build(page, 'gardenrx-harvest-card', {}, {});
  check((await text(page)).includes('GardenRX'), 'missing: a card with no sensor says nothing about why');
  await build(page, 'morph-gardenrx-harvest', {}, {});
  check((await text(page)).trim() === '', 'missing: the Morph card writes text with no sensor');
  await ctx.close();
}

await b.close();
if (problems.length) {
  console.error(`${problems.length} problem(s):\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log('GardenRX cards: every case passed.');
