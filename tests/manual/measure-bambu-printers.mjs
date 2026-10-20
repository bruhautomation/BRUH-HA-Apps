/* Playwright measure for BRUH Bambu Studio's Printers tab and print dialogs.
 *
 *   node tests/manual/measure-bambu-printers.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it;
 *    SHOTS=dir to keep a screenshot of each width)
 *
 * Drives the real panel files against stubbed answers at a phone (touch) and
 * a desktop width. Fails on:
 *  - a printer card without its camera picture, the state pill, the stage,
 *    the progress ring, the time left, the AMS trays (the one feeding marked)
 *    or the external spool;
 *  - Refresh or Reconnect missing, or not sending what they say;
 *  - the camera's <img> being replaced by a redraw (it must survive polls);
 *  - "On the printer" not listing the printer's jobs with their pictures;
 *  - the Home Assistant card not offering the restart it says is needed;
 *  - a print dialog without the build plate, the start options and the
 *    slicer settings grouped, or Print by object;
 *  - the print choice's three texts not starting at one left edge;
 *  - a control under the touch floor, sideways scroll, or any page error.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

const PANEL = fileURLToPath(new URL('../../bruh-bambu-studio/panel/', import.meta.url));
const FRAME = Buffer.from('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', 'base64');
const PICTURE = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABOUlEQVR4nO2byxHCMAxEDWXQDHVQIXXQDG3ASZcMjPWzVp7sOyvWar1ODknGIIQQQshZuVQ3vD/fn1nN63Er07W8kWbgGSsNWbZwxuBHVhiRvuCKwY9kGnHNWmiMmuGz+6Q4WTX4L6JpCCcAOXxG/5AB6OGFiA63AV2GF7x6XAZ0G17w6Ep9CuyI2YCuuy9Y9ZkM6D68YNHJI6At3GX3Ba1eJkBTtNvuCxrdTABaABoaMCvY9fwLM/1MAFoAGhqAFoCGBqAFoKEBaAFopgZUvqhcwUw/E4AWgIYGaIp2vQ9odDMB2sLdUqDVywRYindJgUWnOQHdTbDq4xHwXNQ1BR5d7gR0M8GrJ3QEupgQ0RG+B6BNiPZPFV/5DiHL+NSnQFUaMvvwW+HsBY+c9mvxf3T7X4AQQgg5MV8oP3RaaaB+6QAAAABJRU5ErkJggg==', 'base64');
const OPTIONS = JSON.parse(execFileSync('python3', ['-c',
  'import json,sys; sys.path.insert(0, sys.argv[1]); from design import options; '
  + 'print(json.dumps({"ok": True, **options.catalog()}))', PANEL]).toString());

const A1 = { id: 'a1', name: 'Workshop A1', model: 'A1', host: '192.168.1.60', serial: 'A1SERIAL',
  online: true, state: 'running', printing: true, stage: 'Changing filament', progress: 42,
  remaining_min: 95, layer: 84, total_layers: 200, file: 'Gear rotor', speed: 'standard',
  nozzle_c: 219.6, nozzle_target_c: 220, bed_c: 60.2, bed_target_c: 60, chamber_c: null,
  chamber_light: true, nozzle_diameter: '0.4', wifi: '-48dBm',
  fans: { part: 100, aux: 40, chamber: null, heatbreak: 100 },
  ams: [{ slot: 0, type: 'PLA', name: 'Bambu PLA Basic', colour: '#FFFFFF', remaining: 80 },
    { slot: 1, type: 'PLA', name: 'Bambu PLA Matte', colour: '#18C241', remaining: 35 },
    { slot: 2, type: 'PETG', name: null, colour: '#202020', remaining: null },
    { slot: 3, type: 'PLA', name: null, colour: '#E0352B', remaining: 10 }],
  ams_units: [{ id: 0, humidity: 4, temp_c: 27 }], active_tray: 1,
  external_spool: { slot: 'external', type: 'TPU', colour: '#FFA500', remaining: null },
  hms: ['0700_2000_0002_0001'], hms_count: 1, error_code: null,
  camera: { kind: 'jpeg', streaming: true, frame_age_s: 0.4, error: '' },
  job_picture: 'api/thumb?path=sliced%2Frotor.gcode.3mf', connection_error: '' };
const X1 = { id: 'x1', name: 'X1C', model: 'X1C', host: '192.168.1.61', serial: 'X1SERIAL',
  online: true, state: 'finish', printing: false, progress: 100, file: 'Benchy', speed: 'standard',
  nozzle_c: 32, bed_c: 30, chamber_c: 28, chamber_light: false, ams: [], ams_units: [],
  hms: [], camera: { kind: 'disabled', streaming: false, error: '' }, connection_error: '' };
const STATE = { ok: true, version: 'dev', printers: [A1, X1], jobs: [],
  studio: { installed: true, running: false, wanted: false, install: {} },
  ha: { reason: 'not_loaded', restart_needed: true, deployed: '0.2.0', running: null,
    lovelace_card: true, morph_installed: true, morph_card: true } };
const STORAGE = { ok: true, printer: 'Workshop A1', files: [
  { name: 'rotor.gcode.3mf', dir: false, size: 2.4e6, date: 'Oct 20 10:02', printable: true,
    picture: 'api/printer/thumb?printer=a1&name=rotor.gcode.3mf&size=2400000' },
  { name: 'plate.gcode', dir: false, size: 8e5, date: 'Oct 19 09:00', printable: true, picture: null },
  { name: 'timelapse', dir: true, size: 0 }] };
const FILES = { ok: true, root: '/share/bambu', files: [
  { path: 'imports/rotor.stl', name: 'rotor.stl', size: 3e6, modified: 1760000000, sliced: false, project: false }] };

const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});
const problems = [];
const COMMANDS = [];

async function run(label, viewport, touch) {
  const say = (m) => problems.push(`${label}: ${m}`);
  const ctx = await browser.newContext({ viewport, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => say(`page error ${e.message}`));
  await page.route('http://panel.test/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.slice(1);
    const method = route.request().method();
    if (path === 'api/printer/camera') return route.fulfill({ body: FRAME, contentType: 'image/jpeg' });
    if (path === 'api/thumb' || path === 'api/printer/thumb') return route.fulfill({ body: PICTURE, contentType: 'image/png' });
    if (path === 'api/printer/command') {
      COMMANDS.push({ label, ...route.request().postDataJSON() });
      return route.fulfill({ json: { ok: true, acknowledged: true, note: '' } });
    }
    const stubs = { 'api/state': STATE, 'api/print/options': OPTIONS, 'api/printer/storage': STORAGE,
      'api/files': FILES, 'api/design/status': { ok: true, brain: { state: 'ok' }, cad: true, viewer: true },
      'api/design/parts': { ok: true, parts: [] },
      'api/printers': { ok: true, printers: STATE.printers, models: ['A1', 'X1C'] } };
    if (path.startsWith('api/')) {
      if (method === 'GET' && stubs[path]) return route.fulfill({ json: stubs[path] });
      return route.fulfill({ json: { ok: true } });
    }
    const file = path || 'index.html';
    const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css'
      : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html';
    try { return route.fulfill({ body: readFileSync(join(PANEL, file)), contentType: type }); }
    catch (_) { return route.fulfill({ status: 404, body: '' }); }
  });
  await page.goto('http://panel.test/');
  await page.locator('.tab[data-view="printers"]').click();
  const card = page.locator('.printer[data-id="a1"]');
  await card.waitFor();
  await page.waitForFunction(() => {
    const img = document.querySelector('.printer[data-id="a1"] .camimg');
    return img && img.naturalWidth > 0;
  }, null, { timeout: 10000 }).catch(() => say('the camera picture never appeared'));
  const text = await card.innerText();
  for (const want of ['Printing', 'Changing filament', '42', '1 h 35 min', 'left', '84/200', 'AMS',
    'Spool holder', 'TPU', '0700_2000_0002_0001', 'Refresh', 'Reconnect', 'Pause', 'Stop', 'On the printer']) {
    if (!text.includes(want)) say(`the printer card does not show “${want}”`);
  }
  if ((await card.locator('.spool').count()) !== 5) say('the card does not show four AMS trays and the spool holder');
  if ((await card.locator('.spool.active').count()) !== 1) say('the tray feeding the nozzle is not marked');
  if (!(await card.locator('.ring').count())) say('no progress ring');
  const before = await card.locator('.camimg').elementHandle();
  await page.evaluate(() => refresh());
  await page.waitForTimeout(300);
  const same = await page.evaluate((img) => img.isConnected, before);
  if (!same) say('a redraw replaced the camera picture');

  await card.getByRole('button', { name: 'Refresh' }).click();
  await card.getByRole('button', { name: 'Reconnect' }).click();
  await page.waitForTimeout(200);
  const mine = COMMANDS.filter((c) => c.label === label).map((c) => c.action);
  if (!mine.includes('refresh')) say('Refresh did not ask for a report');
  if (!mine.includes('reconnect')) say('Reconnect did not reconnect');

  await card.locator('details[data-k="storage"] > summary').click();
  await card.locator('.pfile').first().waitFor().catch(() => say('On the printer listed nothing'));
  if ((await card.locator('.pfile').count()) !== 2) say('On the printer did not list the two jobs');
  const pic = await card.locator('.pfile img').first().evaluate((i) => i.complete && i.naturalWidth > 0).catch(() => false);
  if (!pic) say("a job on the printer has no picture");

  const ha = page.locator('#haCard');
  if (!(await ha.getByRole('button', { name: 'Restart Home Assistant' }).count())) {
    say('the Home Assistant card does not offer the restart it needs');
  }
  if (!(await ha.innerText()).includes('custom:bruh-bambu-card')) say('the Home Assistant card does not say how to add the card');

  const wide = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (wide > 1) say(`the Printers tab scrolls sideways by ${wide} px`);
  if (touch) {
    const small = await page.evaluate(() => [...document.querySelectorAll('#viewPrinters button, #viewPrinters summary')]
      .filter((b) => b.offsetParent && b.getBoundingClientRect().height < 40)
      .map((b) => (b.getAttribute('aria-label') || b.textContent).trim().slice(0, 30)));
    if (small.length) say(`under the touch floor: ${small.join(', ')}`);
  }
  if (process.env.SHOTS) {
    mkdirSync(process.env.SHOTS, { recursive: true });
    await page.screenshot({ path: join(process.env.SHOTS, `printers-${label}.png`), fullPage: true });
  }

  // A printer that is printing offers no second print from its storage.
  if (!(await card.locator('.pfile').first().getByRole('button', { name: 'Print' }).isDisabled())) {
    say('a busy printer offers to print a stored job');
  }

  await page.locator('.tab[data-view="files"]').click();
  await page.locator('#fileList .frow').first().waitFor();
  if (!(await page.locator('#fileList .frow img.fthumb').count())) say('a file row has no picture');
  await page.locator('#fileList .frow').first().getByRole('button', { name: 'Print' }).click();
  await page.locator('#printDialog[open]').waitFor();
  const dialog = await page.locator('#printDialog').innerText();
  for (const want of ['Build plate', 'Speed after it starts', 'Bed levelling', 'Timelapse', 'Copies',
    'Slicer settings', 'Filament']) {
    if (!dialog.includes(want)) say(`the print dialog has no “${want}”`);
  }
  await page.locator('#printDialog .optmore > summary').click();
  const opened = await page.locator('#printDialog').innerText();
  for (const want of ['Quality', 'Strength', 'Support', 'Adhesion', 'Layout', 'Print order', 'Ironing', 'Multi-colour']) {
    if (!opened.toLowerCase().includes(want.toLowerCase())) say(`the slicer settings have no “${want}”`);
  }
  if (!(await page.locator('select[name="s:print_sequence"] option[value="by object"]').count())) {
    say('the print dialog cannot print by object');
  }
  const over = await page.locator('#printDialog').evaluate((d) => d.scrollWidth - d.clientWidth);
  if (over > 1) say(`the print dialog scrolls sideways by ${over} px`);
  if (process.env.SHOTS) await page.screenshot({ path: join(process.env.SHOTS, `dialog-${label}.png`) });
  await page.locator('#printCancel').click();

  // The print choice: three cards, their words on one left edge.
  await page.evaluate(() => document.querySelector('#printChoice').showModal());
  const lefts = await page.locator('#printChoice .ctext').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().left)));
  if (new Set(lefts).size !== 1) say(`the print choices start at different places: ${lefts.join(', ')}`);
  if (process.env.SHOTS) await page.screenshot({ path: join(process.env.SHOTS, `choice-${label}.png`) });
  await ctx.close();
}

await run('390', { width: 390, height: 844 }, true);
await run('1280', { width: 1280, height: 900 }, false);
await browser.close();
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('OK: printer cards (camera, status, AMS, storage), Home Assistant, print dialogs and choices at 390 (touch) and 1280.');
