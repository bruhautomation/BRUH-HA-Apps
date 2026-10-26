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
 *  - print failure detection without its status, the open alert with what
 *    brAIn saw beside what the print should be, the plan of looks over the
 *    layers, the history, or Resume not answering that alert;
 *  - a printer with detection off not offering the switch that turns it on;
 *  - the camera box not keeping the stream's own shape (a square stream in a
 *    16:9 box, letterboxed), or anything but controls drawn over the picture
 *    (the progress line that ran across the bottom of the feed);
 *  - a picture on the printer that failed once (the printer's storage busy)
 *    never shown, or a file with no picture drawn as a word ("GCODE");
 *  - something said twice on the card: the speed as a tile beside its own
 *    switch, the stage over the camera and in the job;
 *  - an AMS's four trays not on one row at a phone's width;
 *  - removing a printer as a bare ✕ beside Refresh;
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
  job_picture: 'api/thumb?path=sliced%2Frotor.gcode.3mf', connection_error: '',
  failure_detection: { enabled: true, mode: 'pause', sensitivity: 'medium', light: true, plate_watch: true,
    status: 'failure', sentence: 'The print failed and was paused.', view: 'ok',
    brain: { state: 'ok', sentence: 'ok' }, plate: { state: 'printing', why: '' }, print_id: '68f1a2b3',
    alert: { id: '68f1a2b3-1', level: 'failure', problem: 'spaghetti', open: true, paused: true, check: 3,
      summary: 'Spaghetti is building up behind the left part.', confidence: 0.91, at: Date.now() / 1000 - 90,
      image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
    last: { n: 3, layer: 84, decision: 'failure', summary: 'Spaghetti is building up behind the left part.',
      confidence: 0.91, at: Date.now() / 1000 - 90, image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
    next: { layer: 120, kind: 'bridge', reason: 'Bridges start at layer 118.' },
    expected_url: 'api/watch/image?printer=a1&name=68f1a2b3%2Fexpected.png',
    plan: { source: 'gcode', total_layers: 200, checkpoints: [
      { layer: 2, kind: 'first_layer', reason: 'The first layer is down.', state: 'done', decision: 'ok' },
      { layer: 9, kind: 'early', reason: 'A couple of millimetres up.', state: 'done', decision: 'ok' },
      { layer: 84, kind: 'colour', reason: 'Filament changes at layer 83.', state: 'done', decision: 'failure' },
      { layer: 120, kind: 'bridge', reason: 'Bridges start at layer 118.', state: 'planned' },
      { layer: 200, kind: 'last', reason: 'The last layers.', state: 'planned' }] },
    looks: { used: 3, budget: 8, checks: 3 }, ignored: [] } };
const X1 = { id: 'x1', name: 'X1C', model: 'X1C', host: '192.168.1.61', serial: 'X1SERIAL',
  online: true, state: 'finish', printing: false, progress: 100, file: 'Benchy', speed: 'standard',
  nozzle_c: 32, bed_c: 30, chamber_c: 28, chamber_light: false, ams: [], ams_units: [],
  hms: [], camera: { kind: 'disabled', streaming: false, error: '' }, connection_error: '',
  failure_detection: { enabled: false, mode: 'pause', sensitivity: 'medium', light: true, plate_watch: true,
    status: 'off', sentence: 'Print failure detection is off.', view: 'unknown', plate: { state: 'unknown' },
    alert: null, last: null, next: null, plan: { checkpoints: [] }, looks: { used: 0, budget: 8 } } };
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

const HISTORY = { ok: true, checks: [
  { n: 3, layer: 84, decision: 'failure', summary: 'Spaghetti is building up behind the left part.', confidence: 0.91,
    why: 'Filament changes at layer 83.', at: Date.now() / 1000 - 90, expected: true,
    image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
  { n: 1, layer: 2, decision: 'ok', summary: 'The first layer is down evenly.', confidence: 0.88,
    why: 'The first layer is down.', at: Date.now() / 1000 - 4000, image_url: null }], alerts: [], errors: [] };
const WATCH = [];
const THUMB_FAILED = new Set();

const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});
const problems = [];
const COMMANDS = [];

async function run(label, viewport, touch) {
  const say = (m) => problems.push(`${label}: ${m}`);
  const ctx = await browser.newContext({ viewport, hasTouch: touch, isMobile: touch,
    colorScheme: process.env.SCHEME === 'dark' ? 'dark' : 'light' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => say(`page error ${e.message}`));
  await page.route('http://panel.test/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.slice(1);
    const method = route.request().method();
    if (path === 'api/printer/camera') {
      // Slowly, so a card that blanks while the next frame loads is caught.
      await new Promise((r) => setTimeout(r, 250));
      // The X1C's camera is square, so a box that keeps 16:9 shows bars.
      if (url.searchParams.get('printer') === 'x1') return route.fulfill({ body: PICTURE, contentType: 'image/png' });
      return route.fulfill({ body: FRAME, contentType: 'image/jpeg' });
    }
    if (path === 'api/printer/thumb' && !THUMB_FAILED.has(label)) {
      // The printer's storage is busy the first time it is asked.
      THUMB_FAILED.add(label);
      return route.fulfill({ status: 502, json: { ok: false, error: 'Could not read the picture: timed out' } });
    }
    if (path === 'api/watch/action' || path === 'api/watch/settings') {
      WATCH.push({ label, path, ...route.request().postDataJSON() });
      return route.fulfill({ json: { ok: true, note: 'Done.' } });
    }
    if (path === 'api/watch/image') return route.fulfill({ body: PICTURE, contentType: 'image/png' });
    if (path === 'api/thumb' || path === 'api/printer/thumb') return route.fulfill({ body: PICTURE, contentType: 'image/png' });
    if (path === 'api/printer/command') {
      COMMANDS.push({ label, ...route.request().postDataJSON() });
      return route.fulfill({ json: { ok: true, acknowledged: true, note: '' } });
    }
    const stubs = { 'api/state': STATE, 'api/print/options': OPTIONS, 'api/printer/storage': STORAGE,
      'api/files': FILES, 'api/design/status': { ok: true, brain: { state: 'ok' }, cad: true, viewer: true },
      'api/design/parts': { ok: true, parts: [] }, 'api/watch': HISTORY,
      'api/watch/targets': { ok: true, targets: ['notify.mobile_app_pixel'] },
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
  // The picture on screen is always a decoded frame: no blank between frames.
  const blanks = await page.evaluate(async () => {
    let blank = 0;
    for (let i = 0; i < 100; i += 1) {
      const img = document.querySelector('.printer[data-id="a1"] .camimg');
      if (!img || !img.complete || !img.naturalWidth) blank += 1;
      await new Promise((r) => setTimeout(r, 40));
    }
    return blank;
  });
  if (blanks) say(`the camera picture was blank in ${blanks} of 100 samples (it flashes)`);
  // The picture box keeps the stream's own shape, at every width.
  await page.waitForFunction(() => {
    const img = document.querySelector('.printer[data-id="x1"] .camimg');
    return img && img.naturalWidth > 0;
  }, null, { timeout: 10000 }).catch(() => say("the X1C's camera picture never appeared"));
  await page.waitForTimeout(100);
  for (const id of ['a1', 'x1']) {
    const fit = await page.evaluate((pid) => {
      const img = document.querySelector(`.printer[data-id="${pid}"] .camimg`);
      const box = img && img.closest('.camwrap').getBoundingClientRect();
      return img && img.naturalWidth ? { box: box.width / box.height, img: img.naturalWidth / img.naturalHeight } : null;
    }, id);
    if (!fit) say(`${id}: no camera box to measure`);
    else if (Math.abs(fit.box - fit.img) > 0.02) {
      say(`${id}: the camera box is ${fit.box.toFixed(2)}:1 for a ${fit.img.toFixed(2)}:1 stream`);
    }
  }
  if (await card.locator('.camwrap .cambar').count()) say('a bar is drawn across the bottom of the camera picture');
  const overPicture = await page.evaluate(() => [...document.querySelectorAll('.printer[data-id="a1"] .camwrap *')]
    .filter((e) => e.offsetParent && getComputedStyle(e).position === 'absolute'
      && !e.closest('.camover') && !e.matches('.cam, .camimg, .camback, .camnote')).map((e) => e.className));
  if (overPicture.length) say(`drawn over the camera picture: ${overPicture.join(', ')}`);
  if ((await card.locator('.tile', { hasText: 'Speed' }).count()) && (await card.locator('.seg[aria-label="Speed"]').count())) {
    say('the speed is shown as a tile beside its own switch');
  }
  const stageTimes = await card.evaluate((c) => (c.innerText.match(/Changing filament/g) || []).length);
  if (stageTimes !== 1) say(`the stage is said ${stageTimes} times`);
  const rows = await card.locator('.amsunit').first().locator('.spool').evaluateAll((els) => new Set(els.map((e) => Math.round(e.getBoundingClientRect().top))).size);
  if (rows !== 1) say(`the AMS's four trays take ${rows} rows`);
  if (await card.locator('.phead > button[aria-label^="Remove"]').count()) say('Remove is a bare ✕ beside Refresh');
  if (!(await card.locator('.phead details.pmenu').count())) say('the printer has no ⋯ menu for removing it');
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
  // The job's picture loads lazily once the list opens: wait for it rather
  // than reading it the instant the row appears.
  const pic = await page.waitForFunction(() => {
    const i = document.querySelector('.printer[data-id="a1"] .pfile img');
    return i && i.complete && i.naturalWidth > 0;
  }, null, { timeout: 12000 }).then(() => true).catch(() => false);
  if (!pic) say("a job on the printer has no picture (a read that failed once was never tried again)");
  const words = await card.locator('.pfile .nopic').evaluateAll((els) => els.map((e) => e.textContent.trim()).filter(Boolean));
  if (words.length) say(`a file with no picture is drawn as words: ${words.join(', ')}`);

  // Print failure detection.
  const watch = card.locator('section.watch');
  const wtext = await watch.innerText();
  for (const want of ['Print failure detection', 'Print paused', 'Spaghetti is building up', '91% sure',
    'What brAIn saw', 'What it should be', 'Where it looks', 'Planned from the print', 'Layer 120',
    'Resume — not a failure', 'Stop print', 'Check now']) {
    if (!wtext.includes(want)) say(`failure detection does not show “${want}”`);
  }
  if ((await watch.locator('.wtick').count()) !== 5) say('the plan does not show its five looks on the layer line');
  if ((await watch.locator('.wtick.bad').count()) !== 1) say('the failed look is not marked on the layer line');
  const pics = await page.waitForFunction(() => [...document.querySelectorAll('.printer[data-id="a1"] .wpics img')]
    .every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 5000 }).then(() => true).catch(() => false);
  if (!pics) say("the alert's pictures did not load");
  await watch.getByRole('button', { name: 'Resume — not a failure' }).click();
  await page.waitForTimeout(200);
  const resumed = WATCH.find((c) => c.label === label && c.action === 'resume');
  if (!resumed || resumed.alert !== '68f1a2b3-1' || resumed.printer !== 'a1') say('Resume did not answer the alert it is on');
  await card.locator('details[data-k="watchhist"] > summary').click();
  await card.locator('.wcheck').first().waitFor().catch(() => say('the looks this print are not listed'));
  if ((await card.locator('.wcheck').count()) !== 2) say('the history does not list both looks');
  await card.locator('details[data-k="watchset"] > summary').click();
  const set = await card.locator('details[data-k="watchset"]').innerText();
  for (const want of ['Warn and pause', 'Only warn', 'Relaxed', 'Balanced', 'Careful', 'Alerts go to']) {
    if (!set.includes(want)) say(`the detection settings have no “${want}”`);
  }
  const x1 = page.locator('.printer[data-id="x1"] section.watch');
  if (!(await x1.innerText()).includes('moments a print is most likely to fail')) say('detection off does not say what it does');
  await x1.locator('.switch input').click();
  await page.waitForTimeout(200);
  if (!WATCH.some((c) => c.label === label && c.path === 'api/watch/settings' && c.printer === 'x1' && c.enabled === true)) {
    say('the switch did not turn detection on');
  }
  const wideWatch = await watch.evaluate((el) => el.scrollWidth - el.clientWidth);
  if (wideWatch > 1) say(`failure detection scrolls sideways by ${wideWatch} px`);

  const ha = page.locator('#haCard');
  if (!(await ha.getByRole('button', { name: 'Restart Home Assistant' }).count())) {
    say('the Home Assistant card does not offer the restart it needs');
  }
  if (!(await ha.innerText()).includes('custom:bruh-bambu-card')) say('the Home Assistant card does not say how to add the card');

  const wide = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (wide > 1) say(`the Printers tab scrolls sideways by ${wide} px`);
  if (touch) {
    const small = await page.evaluate(() => [...document.querySelectorAll('#viewPrinters button, #viewPrinters summary, #viewPrinters .switch')]
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
  if (process.env.SHOTS) await page.screenshot({ path: join(process.env.SHOTS, `files-${label}.png`), fullPage: true });
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
