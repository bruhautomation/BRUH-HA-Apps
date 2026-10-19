/* Playwright measure for BRUH Bambu Studio's Design and Files tabs.
 *
 *   node tests/manual/measure-bambu-design.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it;
 *    THREE_DIR=... to use three.js files already on disk instead of
 *    fetching three@0.160.0 from jsDelivr, the version the Dockerfile vendors)
 *
 * Drives the real panel files (index.html, app.js, design.js, viewer.js,
 * style.css) against stubbed API answers, at a phone (touch) and a desktop
 * width. Fails on:
 *  - a body not drawn in the colour its version gives it (a white body
 *    must be light, a red one red, in the rendered pixels, not just the
 *    material);
 *  - the controls help missing, not opening by itself the first time,
 *    leading with the wrong device's gestures, outside the 3D view, not
 *    closing on an outside tap, or under the touch floor;
 *  - the body key missing a body or not hiding one;
 *  - the Files list showing a design's working files, a design row with a
 *    Delete, an import box under 16px on touch;
 *  - Find printers not listing what it found, a moved printer with no
 *    Update address, or Add not filling the form and leaving the access code;
 *  - sideways scroll, or any page error.
 */
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const PANEL = fileURLToPath(new URL('../../bruh-bambu-studio/panel/', import.meta.url));
const THREE = { 'three.module.min.js': 'build/three.module.min.js',
  'OrbitControls.js': 'examples/jsm/controls/OrbitControls.js',
  'STLLoader.js': 'examples/jsm/loaders/STLLoader.js' };

async function vendor(name) {
  if (process.env.THREE_DIR && existsSync(join(process.env.THREE_DIR, name))) {
    return readFileSync(join(process.env.THREE_DIR, name));
  }
  const r = await fetch(`https://cdn.jsdelivr.net/npm/three@0.160.0/${THREE[name]}`);
  if (!r.ok) throw new Error(`three.js ${name}: HTTP ${r.status}`);
  return Buffer.from(await r.arrayBuffer());
}
const VENDOR = {};
for (const name of Object.keys(THREE)) VENDOR[name] = await vendor(name);

function box(x0, y0, z0, x1, y1, z1) {
  const v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
    [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
  const faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]];
  return `solid b\n${faces.map((f) => `facet normal 0 0 0\nouter loop\n${
    f.map((i) => `vertex ${v[i].join(' ')}`).join('\n')}\nendloop\nendfacet`).join('\n')}\nendsolid b\n`;
}

const PART = {
  id: 'box-a1b2c3', name: 'Two-colour box', state: 'idle', updated: 1, current: 1,
  print_settings: { colour: 'white', material: 'PLA' },
  messages: [{ role: 'user', text: 'A white box with a red lid' },
    { role: 'assistant', text: 'Here it is.', version: 1 }],
  versions: [{ n: 1, ok: true, summary: 'First version', size_mm: [40, 30, 36],
    colors: { Base: '#F4F4F2', Lid: 'red' },
    files: { '3mf': 'box.3mf', step: 'box.step', stl: 'box.stl',
      bodies: { Base: 'bodies/Base.stl', Lid: 'bodies/Lid.stl' } } }],
};
const PRINTER = { id: 'x1c', name: 'X1C', online: true, state: 'idle',
  ams: [{ slot: 0, type: 'PLA', colour: '#F2F2F2', remaining: 80 }] };
const API = {
  'api/state': { ok: true, version: 'dev', printers: [PRINTER], jobs: [],
    studio: { installed: true, running: false, wanted: false, install: {} } },
  'api/printers': { ok: true, printers: [PRINTER],
    models: ['X1C', 'X1E', 'X1', 'P1S', 'P1P', 'P2S', 'A1', 'A1 mini', 'H2D', 'H2S'] },
  'api/files': { ok: true, root: '/share/bambu', files: [
    { path: 'imports/3D Benchy/3dbenchy.stl', name: '3dbenchy.stl', size: 11e6, modified: 2,
      sliced: false, project: false },
    { path: 'designs/box-a1b2c3/v1/box.3mf', name: 'Two-colour box.3mf', size: 2e5, modified: 1,
      sliced: false, project: false, design: 'box-a1b2c3', version: 1 }] },
  'api/design/status': { ok: true, brain: { state: 'ok' }, cad: true, viewer: true },
  'api/design/parts': { ok: true, parts: [{ id: PART.id, name: PART.name, versions: 1, current: 1,
    state: 'idle', updated: 1 }] },
  [`api/design/parts/${PART.id}`]: { ok: true, part: PART },
};
const STL = { 'bodies/Base.stl': box(0, 0, 0, 40, 30, 30), 'bodies/Lid.stl': box(0, 0, 31, 40, 30, 36) };

const problems = [];
const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH, args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] }
  : { args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });

for (const [label, viewport, touch] of [['phone', { width: 390, height: 844 }, true],
  ['desktop', { width: 1280, height: 900 }, false]]) {
  const say = (m) => problems.push(`${label}: ${m}`);
  const ctx = await browser.newContext({ viewport, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => say(`page error ${e.message}`));
  await page.route('http://panel.test/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.slice(1);
    if (path.startsWith('vendor/')) {
      return route.fulfill({ body: VENDOR[path.slice(7)], contentType: 'application/javascript' });
    }
    if (path.endsWith('/file')) {
      return route.fulfill({ body: STL[url.searchParams.get('path')] || '', contentType: 'model/stl' });
    }
    if (path === 'api/printers/scan') {
      return route.fulfill({ json: { ok: true, job: { state: 'done', networks: ['192.168.1.0/24'],
        found: [{ host: '192.168.1.60', serial: '01S00C123456789', model: 'P1P' },
          { host: '192.168.1.77', serial: 'X1CSERIAL0001', model: 'X1C', known: 'x1c',
            name: 'X1C', moved: true, saved_host: '192.168.1.50' }] } } });
    }
    if (path.startsWith('api/')) {
      if (route.request().method() !== 'GET') return route.fulfill({ json: { ok: true } });
      return route.fulfill({ json: API[path] || { ok: false, error: `no stub for ${path}` },
        status: API[path] ? 200 : 404 });
    }
    const file = path || 'index.html';
    const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css'
      : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html';
    return route.fulfill({ body: readFileSync(join(PANEL, file)), contentType: type });
  });
  await page.goto('http://panel.test/');
  await page.evaluate(() => { try { localStorage.clear(); } catch (_) { /* fine */ } });
  await page.locator('#designTab').waitFor({ state: 'visible' });
  await page.locator('#designTab').click();
  await page.locator('.partrow').first().click();
  await page.waitForFunction(() => typeof design !== 'undefined' && design.viewer && design.viewer.group.children.length === 2,
    null, { timeout: 15000 }).catch(() => say('the two bodies never loaded'));
  await page.waitForTimeout(600);

  // Colour: what the materials say, and what the pixels show.
  const colours = await page.evaluate(() => design.viewer.group.children.map((m) => [m.name, `#${m.material.color.getHexString()}`]));
  const byName = Object.fromEntries(colours);
  if (byName.Base !== '#f4f4f2') say(`Base is ${byName.Base}, not the white its version gives it`);
  if (byName.Lid !== '#ff0000') say(`Lid is ${byName.Lid}, not red`);
  const pixels = await page.evaluate(() => {
    const c = document.querySelector('#viewer canvas');
    const g = document.createElement('canvas');
    g.width = c.width; g.height = c.height;
    const x = g.getContext('2d');
    x.drawImage(c, 0, 0);
    const d = x.getImageData(0, 0, g.width, g.height).data;
    let red = 0; let light = 0; let brightest = 0;
    for (let i = 0; i < d.length; i += 4) {
      const [r, gg, b] = [d[i], d[i + 1], d[i + 2]];
      if (r > 140 && gg < 80 && b < 80) red += 1;
      if (r > 175 && gg > 175 && b > 170 && Math.max(r, gg, b) - Math.min(r, gg, b) < 25) {
        light += 1;
        brightest = Math.max(brightest, Math.min(r, gg, b));
      }
    }
    return { red, light, brightest };
  });
  // White is white: the lit face of a white body near full white, not a
  // grey that reads as a grey part.
  if (pixels.brightest < 225) say(`the white base's brightest face is ${pixels.brightest}/255 — it reads grey`);
  if (pixels.red < 200) say(`the red lid barely shows in the render (${pixels.red} red pixels)`);
  if (pixels.light < 200) say(`the white base barely shows in the render (${pixels.light} light pixels)`);

  // The controls help: open by itself the first time, the right gestures first.
  const help = page.locator('#viewHelp');
  const btn = page.locator('#viewHelpBtn');
  // A missing element is a finding, never a throw: a throw would drop every
  // finding already gathered and report only the timeout.
  if (!(await help.count()) || !(await btn.count())) {
    say('there is no controls help on the 3D view');
  } else {
  if (!(await help.isVisible())) say('the controls help did not open by itself the first time');
  const first = await help.evaluate((el) => el.querySelector('[data-input]')?.dataset.input);
  if (first !== (touch ? 'touch' : 'mouse')) say(`the help leads with ${first} gestures`);
  const [hb, vb] = await Promise.all([help.boundingBox(), page.locator('#viewer').boundingBox()]);
  if (hb && vb && (hb.x < vb.x - 1 || hb.x + hb.width > vb.x + vb.width + 1 || hb.y < vb.y - 1
      || hb.y + hb.height > vb.y + vb.height + 1)) {
    say('the controls help hangs outside the 3D view');
  }
  const clipped = await help.evaluate((el) => el.scrollHeight - el.clientHeight);
  if (touch && clipped > 2) say(`the controls help has to be scrolled on a phone (${clipped} px hidden)`);
  await page.locator('#measureOut').click();
  if (await help.isVisible()) say('the help did not close on a tap elsewhere');
  const bb = await btn.boundingBox();
  if (touch && (bb.width < 44 || bb.height < 44)) say(`the ? is ${bb.width}×${bb.height}, under the 44 px touch floor`);
  await btn.click();
  if (!(await help.isVisible())) say('the ? did not open the help');
  await btn.click();
  if (await help.isVisible()) say('the ? did not close the help again');
  }

  // The body key.
  const chips = page.locator('#bodyList .chip.body');
  if ((await chips.count()) !== 2) {
    say(`the body key shows ${await chips.count()} bodies, not 2`);
  } else {
    await chips.nth(1).click();
    const lidShown = await page.evaluate(() => design.viewer.group.getObjectByName('Lid').visible);
    if (lidShown) say('tapping a body in the key did not hide it');
  }

  const wide = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (wide > 1) say(`the Design tab scrolls sideways by ${wide} px`);

  // Files: what was brought in, and the design once, with no Delete.
  await page.locator('.tab[data-view="files"]').click();
  await page.locator('#fileList .file').first().waitFor();
  const rows = await page.locator('#fileList .file').allTextContents();
  if (rows.length !== 2) say(`the Files list has ${rows.length} rows, not 2`);
  const design = rows.find((r) => r.includes('Designed with brAIn'));
  if (!design) say('the designed part has no row saying so');
  else if (/Delete/.test(design)) say('the designed part offers Delete in the Files list');
  if (rows.some((r) => r.includes('designs/'))) say('a design working path is shown in the Files list');
  if (!(await page.locator('#importUrl').count())) {
    say('there is no box to import a link');
  } else {
    const fs = await page.locator('#importUrl').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    if (touch && fs < 16) say(`the import box is ${fs}px on touch; iOS zooms under 16`);
  }
  const wideFiles = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (wideFiles > 1) say(`the Files tab scrolls sideways by ${wideFiles} px`);

  // Printers: Find lists what is new and what moved; Add leaves only the code.
  await page.locator('.tab[data-view="printers"]').click();
  const scanBtn = page.locator('#scanBtn');
  if (!(await scanBtn.count())) {
    say('there is no Find printers button');
  } else {
    const sb = await scanBtn.boundingBox();
    if (touch && sb.height < 44) say(`Find printers is ${sb.height}px tall, under the touch floor`);
    await scanBtn.click();
    const found = page.locator('#scanResults .file');
    await found.first().waitFor({ timeout: 5000 }).catch(() => say('Find printers showed nothing'));
    const texts = await found.allTextContents();
    if (texts.length !== 2) say(`Find printers listed ${texts.length} printers, not 2`);
    if (!texts.some((t) => /Update address/.test(t) && t.includes('192.168.1.50'))) {
      say('a printer that moved does not offer to update its address');
    }
    const add = page.locator('#scanResults button', { hasText: 'Add' });
    if (await add.count()) {
      await add.first().click();
      const form = await page.evaluate(() => {
        const f = document.querySelector('#printerForm');
        return { host: f.host.value, serial: f.serial.value, model: f.model.value, name: f.name.value,
          focused: document.activeElement && document.activeElement.name,
          hint: !document.querySelector('#codeHint').hidden,
          open: document.querySelector('#addPrinter').open };
      });
      if (form.host !== '192.168.1.60' || form.serial !== '01S00C123456789' || form.name !== 'Bambu P1P'
          || form.model !== 'P1P') {
        say(`Add did not fill the form from the scan (${JSON.stringify(form)})`);
      }
      if (!form.open || form.focused !== 'access_code') say('Add did not leave the access code to type');
      if (!form.hint) say('Add does not say where the access code is');
    } else {
      say('a new printer has no Add');
    }
  }
  const widePrinters = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (widePrinters > 1) say(`the Printers tab scrolls sideways by ${widePrinters} px`);
  if (process.env.SHOTS) {
    await page.screenshot({ path: `${process.env.SHOTS}/printers-${label}.png`, fullPage: true });
    await page.locator('.tab[data-view="design"]').click();
    await page.locator('#bodyList .chip.body').nth(1).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${process.env.SHOTS}/design-${label}.png`, fullPage: true });
    await page.locator('#viewHelpBtn').click();
    await page.locator('#viewer').screenshot({ path: `${process.env.SHOTS}/help-${label}.png` });
  }
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.log(`FAIL\n${problems.map((p) => `  - ${p}`).join('\n')}`);
  process.exit(1);
}
console.log('OK: colours, controls help, body key, Files list and Find printers at 390 (touch) and 1280.');
