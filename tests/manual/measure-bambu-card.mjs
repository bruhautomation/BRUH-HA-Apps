/* Playwright measure for BRUH Bambu Studio's printer card, both hosts.
 *
 *   node tests/manual/measure-bambu-card.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it)
 *
 * Loads the real card file into a real browser against a stubbed `hass`
 * whose sensors carry the attributes sensor.py publishes, and drives it:
 * the Lovelace card inside an <ha-card>, the Morph card with Morph's
 * variables and no ha-card. Fails on a printer not rendered, print failure
 * detection's warning not shown or its Ignore not answering that alert, the
 * Last print check camera shown as the live one, a control
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
  'camera.workshop_x1c_camera': { entity_id: 'camera.workshop_x1c_camera', state: 'idle',
    attributes: { entity_picture: '/api/camera_proxy/camera.workshop_x1c_camera?token=abc' } },
  'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} },
  'camera.workshop_x1c_last_print_check': { entity_id: 'camera.workshop_x1c_last_print_check', state: 'idle',
    attributes: { entity_picture: '/api/camera_proxy/camera.workshop_x1c_last_print_check?token=zzz' } },
  'sensor.workshop_x1c_failure_detection': { entity_id: 'sensor.workshop_x1c_failure_detection', state: 'warning',
    attributes: { bruh_bambu_detection: '00m00a2b0123456', alert_id: '68f1-2', alert_level: 'warning',
      alert: 'A corner of the left part is lifting.', sentence: 'Something may be wrong with the print.' } },
};
// The entity registry the frontend carries: the camera and the status sensor
// on one device, which is how the card finds a printer's camera.
const ENTITIES = {
  'sensor.workshop_x1c_status': { entity_id: 'sensor.workshop_x1c_status', device_id: 'dev1' },
  'camera.workshop_x1c_last_print_check': { entity_id: 'camera.workshop_x1c_last_print_check', device_id: 'dev1',
    translation_key: 'last_check' },
  'camera.workshop_x1c_camera': { entity_id: 'camera.workshop_x1c_camera', device_id: 'dev1' },
  'sensor.workshop_x1c_failure_detection': { entity_id: 'sensor.workshop_x1c_failure_detection', device_id: 'dev1' },
  'sensor.a1_mini_status': { entity_id: 'sensor.a1_mini_status', device_id: 'dev2' },
};

const FRAME = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
// A 16:9 camera picture, for the shape checks.
const WIDE = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAIAAAC0SDtlAAAAE0lEQVR4nGNwCEggCTGMahgUGgA+BYcBXLYoZwAAAABJRU5ErkJggg==', 'base64');
const problems = [];
const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});

for (const [tag, morph] of [['bruh-bambu-card', false], ['morph-bambu-printer', true]]) {
  const page = await browser.newPage({ viewport: { width: 420, height: 900 }, hasTouch: true });
  page.on('pageerror', (e) => problems.push(`${tag}: page error ${e.message}`));
  // A real origin, and a camera proxy that answers with a picture — slowly,
  // so a card that blanks while a frame loads is caught doing it.
  let frames = 0;
  await page.route('http://card.test/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/camera_proxy/')) {
      frames += 1;
      await new Promise((r) => setTimeout(r, 250));
      return route.fulfill({ body: FRAME, contentType: 'image/png' });
    }
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><style>
      :root { --surface:#fff; --sunk:#eee; --text:#111; --muted:#666; --line:#ccc;
        --sky:#1e9fe0; --lime:#3a3; --rose:#c33; }</style></head><body></body></html>` });
  });
  await page.goto('http://card.test/');
  await page.evaluate(() => {
    customElements.define('ha-card', class extends HTMLElement {});
  });
  await page.addScriptTag({ content: CARD });
  await page.evaluate((e) => { window.ENTITIES = e; }, ENTITIES);
  await page.evaluate(({ tag, house }) => {
    window.calls = [];
    const card = document.createElement(tag);
    card.setConfig({});
    document.body.append(card);
    card.hass = { states: house, entities: window.ENTITIES, callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); } };
    window.card = card;
  }, { tag, house: HOUSE });
  const root = page.locator(tag);
  const text = await root.evaluate((el) => el.shadowRoot.textContent);
  for (const want of ['Workshop X1C', 'A1 mini', '42%', 'layer 112/260', '1 PLA', '220°',
    'Failure detection', 'A corner of the left part is lifting.', 'Ignore', 'Pause print']) {
    if (!text.includes(want)) problems.push(`${tag}: "${want}" is not on the card`);
  }
  if (text.includes('kitchen')) problems.push(`${tag}: a non-printer entity rendered`);
  await page.waitForFunction((t) => {
    const img = document.querySelector(t).shadowRoot.querySelector('.cam img');
    return img && img.getAttribute('src');
  }, tag, { timeout: 8000 }).catch(() => {});
  // Every frame after the first: the picture on screen is always a decoded
  // one. Setting the visible image's src blanked it while the next loaded.
  const blanks = await page.evaluate(async (t) => {
    let blank = 0;
    for (let i = 0; i < 120; i += 1) {
      const img = document.querySelector(t).shadowRoot.querySelector('.cam img');
      if (!img || !img.complete || !img.naturalWidth) blank += 1;
      await new Promise((r) => setTimeout(r, 40));
    }
    return blank;
  }, tag);
  if (blanks) problems.push(`${tag}: the camera picture was blank in ${blanks} of 120 samples (it flashes)`);
  if (frames < 3) problems.push(`${tag}: only ${frames} camera frames were asked for in ~5 s`);
  const cams = await root.evaluate((el) => [...el.shadowRoot.querySelectorAll('.cam img')].map((i) => i.getAttribute('src') || ''));
  if (cams.length !== 1 || !cams[0].startsWith('/api/camera_proxy/camera.workshop_x1c_camera?token=abc')) {
    problems.push(`${tag}: the printer's camera is not on the card (${JSON.stringify(cams)})`);
  }
  if (!(await root.evaluate((el) => !!el.shadowRoot.querySelector('[data-act="refresh"]')))) {
    problems.push(`${tag}: no Refresh`);
  }
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
  await click('[data-alert="ignore"]');
  calls = await page.evaluate(() => window.calls);
  if (JSON.stringify(calls.at(-1)) !== JSON.stringify(['bruh_bambu', 'print_alert_action',
    { printer: '00m00a2b0123456', action: 'ignore', alert: '68f1-2' }])) {
    problems.push(`${tag}: Ignore sent ${JSON.stringify(calls.at(-1))}`);
  }
  if ((await root.evaluate((el) => el.shadowRoot.querySelectorAll('.printer').length)) !== 2) {
    problems.push(`${tag}: the failure detection sensor was drawn as a printer`);
  }
  const small = await root.evaluate((el) => [...el.shadowRoot.querySelectorAll('button, select')]
    .map((b) => b.getBoundingClientRect().height).filter((h) => h < 40));
  if (small.length) problems.push(`${tag}: ${small.length} control(s) under 40 px`);
  await page.close();
}

// The card's shape at the widths it is used at.
const PRINTING_MAX = 420;
const SEEN = {};
for (const [tag] of [['bruh-bambu-card'], ['morph-bambu-printer']]) {
  for (const width of [390, 400, 500]) {
    const say = (m) => problems.push(`${tag} at ${width}: ${m}`);
    const page = await browser.newPage({ viewport: { width, height: 1400 }, hasTouch: true, isMobile: width === 390 });
    page.on('pageerror', (e) => say(`page error ${e.message}`));
    await page.route('http://card.test/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/camera_proxy/')) return route.fulfill({ body: WIDE, contentType: 'image/png' });
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head>
        <meta name="viewport" content="width=device-width, initial-scale=1"><style>
        :root { --surface:#fff; --sunk:#eee; --text:#111; --muted:#666; --line:#ccc;
          --sky:#1e9fe0; --lime:#3a3; --rose:#c33; } body { margin: 0; padding: 8px; }
        ha-card { display: block; }</style></head><body></body></html>` });
    });
    await page.goto('http://card.test/');
    await page.evaluate(() => customElements.define('ha-card', class extends HTMLElement {}));
    await page.addScriptTag({ content: CARD });
    await page.evaluate(({ t, house, ents }) => {
      const card = document.createElement(t);
      card.setConfig({});
      document.body.append(card);
      card.hass = { states: house, entities: ents, callService: () => Promise.resolve() };
    }, { t: tag, house: HOUSE, ents: ENTITIES });
    await page.waitForTimeout(900);
    const root = page.locator(tag);
    const h = await root.evaluate((el) => Math.round(el.shadowRoot.querySelector('.printer').getBoundingClientRect().height));
    SEEN[`${tag}@${width}`] = h;
    if (h > PRINTING_MAX) say(`the printing printer is ${h} px tall (at most ${PRINTING_MAX})`);
    const face = await root.evaluate((el) => {
      const p = el.shadowRoot.querySelector('.printer');
      const shown = (n) => { const r = n.getBoundingClientRect(); const cs = getComputedStyle(n);
        return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'; };
      const words = [];
      const walk = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
      for (let t = walk.nextNode(); t; t = walk.nextNode()) {
        if (t.textContent.trim() && shown(t.parentElement)) words.push(t.textContent.trim());
      }
      const cut = [...p.querySelectorAll('*')].filter((n) => shown(n) && n.scrollWidth > n.clientWidth + 1
        && getComputedStyle(n).overflow !== 'visible' && n.children.length === 0).map((n) => n.textContent.trim());
      const small = [...el.shadowRoot.querySelectorAll('button, select, summary')].filter(shown)
        .map((b) => Math.round(b.getBoundingClientRect().height)).filter((x) => x < 44);
      const pauses = [...p.querySelectorAll('button')].filter((b) => shown(b) && /^Pause/.test(b.textContent.trim())).length;
      return { words, cut, small, pauses };
    });
    const states = face.words.filter((w) => /^(running|printing)$/i.test(w));
    if (states.length !== 1) say(`the state is said ${states.length} times (${states.join(', ')})`);
    if (face.words.includes('running')) say('the raw state word "running" is on the card');
    if (face.pauses > 1) say(`${face.pauses} Pause buttons are on the face of the card`);
    if (face.cut.length) say(`text cut off: ${face.cut.join(' | ')}`);
    if (face.small.length) say(`${face.small.length} control(s) a finger presses are under 44 px (${face.small.join(', ')})`);
    if (process.env.SHOTS) await root.screenshot({ path: `${process.env.SHOTS}/bambu-card-${tag}-${width}.png` });
    await page.close();
  }
}
console.log(`heights of the printing printer: ${JSON.stringify(SEEN)}`);

await browser.close();
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('bambu card: both hosts render, act and confirm Stop');
