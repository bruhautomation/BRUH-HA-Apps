// Screenshot the seeded brAIn panel for the documentation: every pane the
// website and the add-on README show, light and dark, plus the insight card,
// its Refine and Share dialogs, the picture Share produces, and a phone.
//
// Start the panel first:  python3 tests/manual/demo_panel.py /tmp/brain-demo
// Then:                   SHOT_DIR=shots node tests/manual/shoot-docs.mjs
//
// The demo has no Home Assistant behind it, so the panes that read one —
// ESPHome, Music Assistant, Activity, Ideas and the Share dialog's dashboard
// list — are answered here with the SAME fixtures their measure scripts drive
// the real renderers with, read out of those files rather than copied, so a
// docs screenshot can never show a shape the panel does not render.
//
// Convert to webp at 1600px wide (phone shots 780px) for the site's
// apps/brain/images/, and copy the ones the add-on README uses into
// docs/images/.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR || 'shots';
const BASE = process.env.SHOT_BASE || 'http://127.0.0.1:8099/';
const CARD = 'custom-1723';   // the humidity card in demo_home.py
const NOW = Math.floor(Date.now() / 1000);
fs.mkdirSync(OUT, { recursive: true });

// A fixture out of a measure script: the literal after `const NAME = `.
function fixture(file, name, close) {
  const src = fs.readFileSync(path.join(HERE, file), 'utf8');
  const m = src.match(new RegExp(`const ${name} = ([\\s\\S]*?\\n${close});`));
  if (!m) throw new Error(`${name} not found in ${file}`);
  const ep = (over) => ({
    subject: '', entity_id: '', name: '', started: NOW - 3600, ended: NOW - 3600,
    count: 1, first: 'on', last: 'on', duration_s: 0, open: false, states: [],
    causes: {}, cause: 'unattributed', by_name: '', ...over,
  });
  // eslint-disable-next-line no-new-func
  return new Function('ep', 'NOW', `return (${m[1]});`)(ep, NOW);
}

const ESP = {
  dir: '/config/esphome', dir_exists: true,
  dashboard: { reachable: true, via: 'ingress', version: '2026.9.0',
    addon: { name: 'ESPHome Device Builder' } },
  devices: fixture('measure-esphome.mjs', 'DEVICES', '\\]'),
  importable: [], ha_registry_ok: true, secret_keys: ['wifi_ssid', 'wifi_password'],
  platforms: [{ id: 'esp32', label: 'ESP32', board: 'esp32dev' }], jobs: [],
};
const MA = fixture('measure-music.mjs', 'OVERVIEW', '\\}');
const IDEAS = {
  ideas: fixture('measure-ideas.mjs', 'IDEAS', '\\]'), open: 2, running: false,
  last_run: NOW - 86400, last_error: '', last_count: 2, runs: 3, answered: 4,
  writable: true, due: false,
};
const ACTIVITY = {
  available: true, error: '', start: NOW - 86400, end: NOW, hours: 24,
  sections: fixture('measure-activity.mjs', 'SECTIONS', '\\]'),
  away: [{ start: NOW - 20000, end: NOW - 1800 }],
  counts: { brain: 1, automation: 2, script: 0, scene: 0, voice: 1, person: 4, unattributed: 12 },
  causes: ['brain', 'automation', 'script', 'scene', 'voice', 'person', 'unattributed'],
  capped: false, dropped: 1842, changes: 20, episodes: 7,
};
const DASHBOARDS = { dashboards: [
  { url_path: null, title: 'Overview', editable: true, reason: '',
    views: [{ index: 0, title: 'Home' }, { index: 1, title: 'Climate' }] },
  { url_path: 'map', title: 'Map', editable: false,
    reason: 'This dashboard is written in YAML — copy the YAML below into it.', views: [] },
] };

const json = (b) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(b) });
async function stubs(page) {
  await page.route('**/api/ideas', (r) => r.fulfill(json(IDEAS)));
  await page.route('**/api/dashboards', (r) => r.fulfill(json(DASHBOARDS)));
  await page.route('**/local/brain/**', (r) => r.fulfill({ status: 200, body: 'ok' }));
  await page.route('**/api/scenes/areas', (r) => r.fulfill(json({ areas: [
    { area: 'Living room', lights: 6 }, { area: 'Kitchen', lights: 4 }] })));
  await page.route(/api\/esphome(\?.*)?$/, (r) => r.fulfill(json(ESP)));
  await page.route(/api\/music-assistant(\?.*)?$/, (r) => r.fulfill(json(MA)));
  await page.route(/api\/activity(\?.*)?$/, (r) => r.fulfill(json(ACTIVITY)));
}

const VIEWS = [
  ['findings', 'panel-findings'], ['insights', 'panel-insights'], ['ideas', 'panel-ideas'],
  ['todo', 'panel-todo'], ['proposals', 'panel-proposals'], ['terminal', 'panel-chat'],
  ['memory', 'panel-knowledge'], ['activity', 'panel-activity'],
  ['esphome', 'panel-esphome'], ['music', 'panel-music'],
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
for (const theme of ['light', 'dark']) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 },
    deviceScaleFactor: 2, colorScheme: theme });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('  page error:', e.message));
  await stubs(page);
  const go = async (view) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForTimeout(900);
    await openView(page, view);
    await page.waitForTimeout(1800);
    // A control still under the pointer keeps its tooltip open.
    await page.mouse.move(1278, 858);
    await page.waitForTimeout(400);
  };
  for (const [view, name] of VIEWS) {
    await go(view);
    await page.screenshot({ path: path.join(OUT, `${name}-${theme}.png`) });
    console.log(`${name}-${theme}.png`);
  }

  // The card, and what its two named buttons open.
  await go('insights');
  const card = page.locator(`.card[data-id="${CARD}"]`);
  await card.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -130));
  await page.waitForTimeout(1200);
  await card.screenshot({ path: path.join(OUT, `insight-card-${theme}.png`) });
  await card.locator('.cardact', { hasText: 'Refine' }).click();
  await page.waitForTimeout(500);
  await page.fill('#refineText', 'Compare it with upstairs, and use the last 7 days');
  await page.mouse.move(1278, 858);
  await page.waitForTimeout(300);
  await page.locator('#refineModal .box').screenshot({ path: path.join(OUT, `insight-refine-${theme}.png`) });
  await page.click('#refineClose');
  await card.locator('.cardact', { hasText: 'Share' }).click();
  await page.waitForSelector('#shareShot img', { timeout: 15000 });
  await page.mouse.move(1278, 858);
  await page.waitForTimeout(400);
  await page.locator('#shareModal .box').screenshot({ path: path.join(OUT, `insight-share-${theme}.png`) });
  const bytes = await page.evaluate(async () => {
    const r = await fetch(document.querySelector('#shareShot img').src);
    return Array.from(new Uint8Array(await r.arrayBuffer()));
  });
  fs.writeFileSync(path.join(OUT, `insight-export-${theme}.png`), Buffer.from(bytes));
  console.log(`insight card, refine, share, export — ${theme}`);
  await ctx.close();
}

const phone = await browser.newContext({ viewport: { width: 390, height: 800 },
  deviceScaleFactor: 3, colorScheme: 'dark', isMobile: true, hasTouch: true });
const p = await phone.newPage();
await stubs(p);
await p.goto(BASE, { waitUntil: 'networkidle' });
await p.waitForTimeout(1500);
await p.screenshot({ path: path.join(OUT, 'panel-phone-dark.png') });
await openView(p, 'insights');
await p.waitForTimeout(1500);
const pc = p.locator(`.card[data-id="${CARD}"]`);
await pc.scrollIntoViewIfNeeded();
await p.waitForTimeout(1500);
await pc.screenshot({ path: path.join(OUT, 'insight-card-phone-dark.png') });
console.log('phone shots');
await browser.close();
