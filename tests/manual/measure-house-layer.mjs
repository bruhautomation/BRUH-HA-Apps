// The house's own layer over brAIn's page (panel/house_ui.py +
// panel/house-layer.js), driven in a real browser over http, with the page's
// head rendered by the REAL house_ui.py exactly as the server renders it.
// Holds:
//
//   * house.css is applied (it is linked after style.css, so it wins);
//   * a house.js that THROWS still ran up to its throw, the shipped page
//     keeps working (the views switch, ⚙ opens), and ⚙ › Instructions shows
//     one line naming the error — and no other page error happened;
//   * ?nohouse=1 skips both: house.css not applied, house.js never
//     requested, and the page says the layer is off for this visit;
//   * "off on this device" (the row's switch) takes house.css away and
//     never loads house.js, and the row says so;
//   * the row is a ⚙ switch row like every other, so it clears the 44px
//     touch floor.
//
// The stub fetch from today-fixture answers the panel's API.
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { stub } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const failures = [];
const note = (where, m) => failures.push(`${where}: ${m}`);

const UI = fs.mkdtempSync(path.join(os.tmpdir(), 'house-ui-'));
fs.writeFileSync(path.join(UI, 'house.css'),
  '.topbar { outline: 3px solid rgb(255, 0, 255) !important; }\n');
fs.writeFileSync(path.join(UI, 'house.js'),
  "document.documentElement.dataset.houseRan = '1';\nthrow new Error('house boom');\n");

const index = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8').replaceAll('{{VERSION}}', 'test');
const render = (off) => execFileSync('python3', [path.join(PANEL, 'house_ui.py'), off ? 'off' : 'on'],
  { input: index, env: { ...process.env, BRAIN_HOUSE_UI_DIR: UI } }).toString();
const pages = { on: render(false), off: render(true) };
if (!pages.on.includes('href="house.css?v=')) note('render', 'house.css is not linked by house_ui.render');
if (pages.off.includes('href="house.css')) note('render', 'house.css is linked in safe mode');

const requested = [];
const TYPES = { '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  requested.push(url.pathname);
  if (url.pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(url.searchParams.get('nohouse') === '1' ? pages.off : pages.on);
    return;
  }
  const name = url.pathname.slice(1);
  const dir = (name === 'house.css' || name === 'house.js') ? UI : PANEL;
  const file = path.join(dir, path.basename(name));
  if (!fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'text/plain' });
  res.end(fs.readFileSync(file));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

async function open(where, { query = '', width = 1200, touch = false, deviceOff = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(stub({}));
  if (deviceOff) await page.addInitScript(() => { try { localStorage.setItem('brain.house.off', '1'); } catch (e) { /* */ } });
  requested.length = 0;
  await page.goto(`${ORIGIN}/${query}`);
  await page.waitForFunction(() => typeof switchView === 'function');
  await page.waitForTimeout(400);
  return { page, context, errors };
}

const outline = (page) => page.evaluate(() => getComputedStyle(document.querySelector('.topbar')).outlineColor);
const ran = (page) => page.evaluate(() => document.documentElement.dataset.houseRan === '1');
async function row(page) {
  await page.evaluate(async () => { await openSettings(); showSettingsSection('instructions'); });
  await page.waitForTimeout(200);
  return page.evaluate(() => {
    const r = document.getElementById('houseLayer');
    if (!r || !r.offsetParent) return null;
    const label = r.querySelector('label');
    return {
      line: document.getElementById('houseLayerLine').textContent,
      checked: document.getElementById('setHouseLayer').checked,
      height: Math.round(label.getBoundingClientRect().height),
      font: parseFloat(getComputedStyle(label.querySelector('b')).fontSize),
    };
  });
}

for (const { width, touch } of [{ width: 1200, touch: false }, { width: 390, touch: true }]) {
  // On, with a house.js that throws.
  {
    const where = `${width}px on`;
    const { page, context, errors } = await open(where, { width, touch });
    if ((await outline(page)) !== 'rgb(255, 0, 255)') note(where, 'house.css is not applied');
    if (!(await ran(page))) note(where, 'house.js did not run');
    const others = errors.filter((m) => !/house boom/.test(m));
    if (others.length) note(where, `the shipped page threw: ${others.join(' | ')}`);
    await page.evaluate(() => switchView('findings'));
    if (!(await page.evaluate(() => !!document.querySelector('#findList')))) note(where, 'Today did not draw');
    const r = await row(page);
    if (!r) note(where, 'no House changes row in ⚙ › Instructions');
    else {
      if (!/house boom/.test(r.line)) note(where, `the row does not name the error: "${r.line}"`);
      if (!r.checked) note(where, 'the switch reads off while the layer is on');
      if (r.height < 44) note(where, `the row is ${r.height}px, under the 44px floor`);
    }
    await context.close();
  }
  // Safe mode.
  {
    const where = `${width}px ?nohouse=1`;
    const { page, context, errors } = await open(where, { width, touch, query: '?nohouse=1' });
    if ((await outline(page)) === 'rgb(255, 0, 255)') note(where, 'house.css applied in safe mode');
    if (await ran(page)) note(where, 'house.js ran in safe mode');
    if (requested.includes('/house.js')) note(where, 'house.js was requested in safe mode');
    if (errors.length) note(where, `page errors: ${errors.join(' | ')}`);
    const said = await page.evaluate(() => document.getElementById('toast').textContent);
    if (!/off for this visit/i.test(said)) note(where, `no notice that the layer is off (toast: "${said}")`);
    const r = await row(page);
    if (!r || !/nohouse=1/.test(r.line)) note(where, 'the row does not say safe mode is why it is off');
    await context.close();
  }
  // Off on this device.
  {
    const where = `${width}px device off`;
    const { page, context } = await open(where, { width, touch, deviceOff: true });
    if ((await outline(page)) === 'rgb(255, 0, 255)') note(where, 'house.css still applied');
    if (await ran(page)) note(where, 'house.js ran while off on this device');
    const r = await row(page);
    if (!r) note(where, 'no row to turn it back on');
    else {
      if (r.checked) note(where, 'the switch reads on');
      if (!/Off on this device/.test(r.line)) note(where, `the row says "${r.line}"`);
    }
    await context.close();
  }
}

await browser.close();
server.close();
fs.rmSync(UI, { recursive: true, force: true });
if (failures.length) {
  console.error(`measure-house-layer: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('measure-house-layer: house.css applied, a throwing house.js contained, ?nohouse=1 and device-off honoured, at 1200 and 390');
