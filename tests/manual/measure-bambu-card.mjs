/* Playwright measure for BRUH Bambu Studio's printer card, both hosts.
 *
 *   node tests/manual/measure-bambu-card.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it)
 *
 * Loads the real card file into a real browser against a stubbed `hass`
 * whose sensors carry the attributes sensor.py publishes, and drives it:
 * the Lovelace card inside an <ha-card>, the Morph card with Morph's
 * variables and no ha-card. Fails on a printer not rendered, a control
 * that does not call the service it says, a Stop that stops on one press,
 * a control under 40 px, or a page error.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CARD = readFileSync(fileURLToPath(
  new URL('../../bruh-bambu-studio/lovelace/bruh-bambu-card.js', import.meta.url)), 'utf8');

const HOUSE = {
  'sensor.workshop_x1c_status': {
    entity_id: 'sensor.workshop_x1c_status', state: 'running',
    attributes: { bruh_bambu_printer: '00m00a2b0123456', printer_name: 'Workshop X1C',
      printing: true, progress: 42, remaining_min: 83, layer: 112, total_layers: 260,
      file: 'benchy', nozzle_c: 219.8, nozzle_target_c: 220, bed_c: 55, bed_target_c: 55,
      speed: 'standard', chamber_light: true,
      ams: [{ slot: 0, type: 'PLA', colour: '#E8E8E8', remaining: 80 },
        { slot: 1, type: 'PETG', colour: '#111111', remaining: 60 }] } },
  'sensor.a1_mini_status': {
    entity_id: 'sensor.a1_mini_status', state: 'idle',
    attributes: { bruh_bambu_printer: '03919c1234', printer_name: 'A1 mini', printing: false,
      nozzle_c: 27, bed_c: 25, chamber_light: false } },
  'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} },
};

const problems = [];
const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});

for (const [tag, morph] of [['bruh-bambu-card', false], ['morph-bambu-printer', true]]) {
  const page = await browser.newPage({ viewport: { width: 420, height: 900 }, hasTouch: true });
  page.on('pageerror', (e) => problems.push(`${tag}: page error ${e.message}`));
  await page.setContent(`<!doctype html><html><head><style>
      :root { --surface:#fff; --sunk:#eee; --text:#111; --muted:#666; --line:#ccc;
        --sky:#1e9fe0; --lime:#3a3; --rose:#c33; }</style></head><body></body></html>`);
  await page.evaluate(() => {
    customElements.define('ha-card', class extends HTMLElement {});
  });
  await page.addScriptTag({ content: CARD });
  await page.evaluate(({ tag, house }) => {
    window.calls = [];
    const card = document.createElement(tag);
    card.setConfig({});
    document.body.append(card);
    card.hass = { states: house, callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); } };
    window.card = card;
  }, { tag, house: HOUSE });
  const root = page.locator(tag);
  const text = await root.evaluate((el) => el.shadowRoot.textContent);
  for (const want of ['Workshop X1C', 'A1 mini', '42%', 'layer 112/260', '1 PLA', '220°']) {
    if (!text.includes(want)) problems.push(`${tag}: "${want}" is not on the card`);
  }
  if (text.includes('kitchen')) problems.push(`${tag}: a non-printer entity rendered`);
  const hasCard = await root.evaluate((el) => !!el.shadowRoot.querySelector('ha-card'));
  if (hasCard === morph) problems.push(`${tag}: ha-card ${morph ? 'present in Morph' : 'missing in Lovelace'}`);

  const click = (sel) => root.evaluate((el, s) => el.shadowRoot.querySelector(s).click(), sel);
  await click('[data-act="pause_print"]');
  await click('[data-stop]');
  let calls = await page.evaluate(() => window.calls);
  if (calls.some((c) => c[1] === 'stop_print')) problems.push(`${tag}: one press stopped the print`);
  const armed = await root.evaluate((el) => el.shadowRoot.querySelector('[data-stop]').textContent);
  if (!armed.includes('again')) problems.push(`${tag}: Stop did not ask for a second press`);
  await click('[data-stop]');
  await click('[data-light="03919c1234"]');
  calls = await page.evaluate(() => window.calls);
  const want = [['bruh_bambu', 'pause_print', { printer: '00m00a2b0123456' }],
    ['bruh_bambu', 'stop_print', { printer: '00m00a2b0123456' }],
    ['bruh_bambu', 'set_light', { printer: '03919c1234', on: true }]];
  if (JSON.stringify(calls) !== JSON.stringify(want)) {
    problems.push(`${tag}: calls were ${JSON.stringify(calls)}`);
  }
  const small = await root.evaluate((el) => [...el.shadowRoot.querySelectorAll('button, select')]
    .map((b) => b.getBoundingClientRect().height).filter((h) => h < 40));
  if (small.length) problems.push(`${tag}: ${small.length} control(s) under 40 px`);
  await page.close();
}

await browser.close();
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('bambu card: both hosts render, act and confirm Stop');
