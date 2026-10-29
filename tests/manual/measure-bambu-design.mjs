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
 *  - Print not offering Auto print, Manual print and Open in Bambu Studio
 *    (each under the touch floor or spilling out of the dialog), Auto print
 *    not asking brAIn to print, Manual print not offering a tray per body,
 *    or Open in Bambu Studio not opening that version and the Studio tab;
 *  - the Files list showing a design's working files, a design row with a
 *    Delete, an import box under 16px on touch;
 *  - Find printers not listing what it found, a moved printer with no
 *    Update address, or Add not filling the form and leaving the access code;
 *  - the 3D view not moving the way Fusion 360's does, driven with real
 *    pointer events: a left drag (and Shift + middle drag, and one finger)
 *    that does not turn the part about its pivot without changing the
 *    distance; a middle or right drag (and two fingers) that does not slide
 *    it; the wheel (and a pinch) that does not zoom toward the point under
 *    the pointer; a turn past the top that flips the view over; Home or a
 *    named view that jumps rather than moves, or does not frame the whole
 *    part; no bed under the part;
 *  - a vertical drag that is not inverted by default (dragging down raises
 *    the view), or Settings' "Invert vertical drag" that does not turn it to
 *    Fusion 360's way (down lowers it) or is not remembered;
 *  - on a phone, an open part that makes the page scroll rather than its
 *    conversation (the 3D view must stay on screen), a conversation shorter
 *    than a third of the screen, or no way back to the newest message;
 *  - the version's text (what changed, warnings, dimensions) spread under
 *    the view rather than one line that opens to it;
 *  - Measure that does not snap like Fusion's: a pointer near a corner, an
 *    edge's middle, an edge, a face's centre or a face not taking that point
 *    and showing which; a distance not drawn on the line at its middle, with
 *    no ΔX/ΔY/ΔZ; a face and a point with no perpendicular distance; two
 *    faces with no angle; no list of recent measurements; Escape or Clear not
 *    clearing; a tap on a phone that does not snap;
 *  - a body's dot that does not open a colour choice (the trays first, then
 *    any colour), recolour that body, save it to the part, or go back to
 *    brAIn's colour;
 *  - no Full screen for the 3D view, or one that does not fill the window
 *    (falling back when the Fullscreen API is refused, as an ingress frame
 *    may) and leave on Escape; the body pills and measurements not visible
 *    and usable in full screen; a view that does not follow its box's size;
 *  - sideways scroll, or any page error.
 */
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

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
    { role: 'assistant', text: 'Here it is: **two bodies**, the lid in `red`.\n\n- Base: 2 walls\n- Lid: 15 % infill\n\n<b>not markup</b>', version: 1 }],
  versions: [{ n: 0, ok: true, summary: 'A first try without the lid', size_mm: [40, 30, 30],
    files: { '3mf': 'box0.3mf', step: 'box0.step', stl: 'box0.stl', bodies: { Base: 'bodies/Base.stl' } } },
  { n: 1, ok: true, summary: 'Added a press-fit lid with a 0.2 mm clearance and a finger notch on the front edge',
    size_mm: [40, 30, 36], grams: 14,
    warnings: ['The lid\'s notch is 0.8 mm thick, under two perimeters.', 'The base has a 52° overhang under the lip.'],
    dims: { wall: '2 mm', clearance: '0.2 mm', notch: '8 × 3 mm', lid: '5 mm' },
    colors: { Base: '#F4F4F2', Lid: 'red' },
    files: { '3mf': 'box.3mf', step: 'box.step', stl: 'box.stl',
      bodies: { Base: 'bodies/Base.stl', Lid: 'bodies/Lid.stl' } } }],
};
const PRINTER = { id: 'x1c', name: 'X1C', online: true, state: 'idle',
  ams: [{ slot: 0, type: 'PLA', colour: '#F2F2F2', remaining: 80 }] };
// The print options come from the panel's own table (design/options.py), so
// the dialogs are measured with the form they really build.
const OPTIONS = JSON.parse(execFileSync('python3', ['-c',
  'import json,sys; sys.path.insert(0, sys.argv[1]); from design import options; '
  + 'print(json.dumps({"ok": True, **options.catalog()}))', PANEL]).toString());
const API = {
  'api/print/options': OPTIONS,
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
  [`api/design/parts/${PART.id}/plan`]: { ok: true, printer: 'X1C', settings: PART.print_settings,
    trays: PRINTER.ams, recommended_slot: 0, machine: 'Bambu Lab X1 Carbon 0.4 nozzle',
    process: '0.20mm Standard @BBL X1C', filament: 'Bambu PLA Basic @BBL X1C',
    bodies: [{ name: 'Base', colour: '#F4F4F2', recommended_slot: 0 },
      { name: 'Lid', colour: 'red', recommended_slot: null }] },
};
const POSTS = [];
const STL = { 'bodies/Base.stl': box(0, 0, 0, 40, 30, 30), 'bodies/Lid.stl': box(0, 0, 31, 40, 30, 36) };

// The 3D view, driven as a person drives it. Every reading is the viewer's
// own camera (cameraState) after it settles; a missing method is a finding.
async function viewerMoves(page, say, touch, ctx) {
  const can = await page.evaluate(() => ['cameraState', 'pointAt', 'screenOf', 'boxOnScreen', 'settled']
    .filter((m) => !(design.viewer && typeof design.viewer[m] === 'function')));
  if (can.length) { say(`the 3D view cannot be read back (${can.join(', ')})`); return; }
  const settle = () => page.evaluate(() => design.viewer.settled());
  const cam = () => page.evaluate(() => design.viewer.cameraState());
  const box = await page.locator('#viewer canvas').boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  const close = (a, b, tol) => Math.abs(a - b) <= tol;
  const moved = (a, b) => Math.hypot(a.target[0] - b.target[0], a.target[1] - b.target[1], a.target[2] - b.target[2]);
  await page.evaluate(() => design.viewer.view('home'));
  await settle();
  if (!(await page.evaluate(() => !!design.viewer.scene.getObjectByName('bed')))) say('there is no bed under the part');
  const fit = await page.evaluate(() => design.viewer.boxOnScreen());
  if (fit.max > 1.0 || fit.max < 0.5) say(`Home does not frame the part (it reaches ${fit.max.toFixed(2)} of the view)`);

  if (!touch) {
    // Left drag: turns, about a pivot, at the same distance.
    let a = await cam();
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 120, cy + 10, { steps: 8 });
    await page.mouse.up();
    await settle();
    let b = await cam();
    if (close(a.az, b.az, 0.05)) say('a left drag did not turn the part');
    if (!close(a.distance, b.distance, a.distance * 0.01)) say(`a left drag changed the distance (${a.distance.toFixed(1)} → ${b.distance.toFixed(1)})`);
    // Vertical: inverted by default (dragging down raises the view), and
    // Settings turns it to Fusion 360's way (down lowers it, toward the bed).
    const setInvert = (on) => page.evaluate((v) => {
      const box = document.querySelector('#invertY');
      box.checked = v;
      box.dispatchEvent(new Event('change'));
    }, on);
    if (!(await page.locator('#viewSettings #invertY').count())) say('there is no Invert vertical drag in Settings');
    if (!(await page.locator('#invertY').isChecked())) say('Invert vertical drag is not on by default');
    for (const [invert, sign] of [[true, 1], [false, -1]]) {
      if (!invert) {
        await setInvert(false);
        const stored = await page.evaluate(() => { try { return localStorage.getItem('bambu.invertY'); } catch (_) { return 'refused'; } });
        if (stored !== '0') say(`Fusion-style vertical drag is not remembered (${stored})`);
      }
      await page.evaluate(() => design.viewer.view('front'));
      await settle();
      const before = await cam();
      await page.mouse.move(cx, cy - 60);
      await page.mouse.down();
      await page.mouse.move(cx, cy + 40, { steps: 8 });
      await page.mouse.up();
      await settle();
      const after = await cam();
      if (Math.sign(after.el - before.el) !== sign || Math.abs(after.el - before.el) < 0.2) {
        say(`a drag down ${invert ? '' : 'with Invert vertical drag off '}moved the elevation ${before.el} → ${after.el}, not ${sign < 0 ? 'down' : 'up'}`);
      }
    }
    await setInvert(true);
    // Shift + middle drag turns too.
    a = await cam();
    await page.keyboard.down('Shift');
    await page.mouse.move(cx, cy);
    await page.mouse.down({ button: 'middle' });
    await page.mouse.move(cx - 100, cy, { steps: 8 });
    await page.mouse.up({ button: 'middle' });
    await page.keyboard.up('Shift');
    await settle();
    b = await cam();
    if (close(a.az, b.az, 0.05)) say('Shift + middle drag did not turn the part');
    // Middle drag and right drag slide it.
    for (const button of ['middle', 'right']) {
      a = await cam();
      await page.mouse.move(cx, cy);
      await page.mouse.down({ button });
      await page.mouse.move(cx + 80, cy + 40, { steps: 8 });
      await page.mouse.up({ button });
      await settle();
      b = await cam();
      if (moved(a, b) < a.distance * 0.02) say(`a ${button} drag did not slide the part`);
      if (!close(a.az, b.az, 0.01) || !close(a.el, b.el, 0.01)) say(`a ${button} drag turned the part instead of sliding it`);
    }
    // The wheel zooms toward the point under the pointer.
    await page.evaluate(() => design.viewer.view('home'));
    await settle();
    const px = cx + box.width * 0.18;
    const py = cy - box.height * 0.1;
    const point = await page.evaluate(([x, y]) => design.viewer.pointAt(x, y), [px, py]);
    a = await cam();
    await page.mouse.move(px, py);
    for (let i = 0; i < 5; i += 1) await page.mouse.wheel(0, -120);
    await settle();
    b = await cam();
    if (b.distance >= a.distance * 0.95) say('the wheel did not zoom in');
    const where = await page.evaluate((p) => design.viewer.screenOf(p), point);
    if (Math.hypot(where[0] - px, where[1] - py) > 4) {
      say(`the wheel zoomed toward the middle, not the pointer (the point moved ${Math.round(Math.hypot(where[0] - px, where[1] - py))} px)`);
    }
    // A long drag up does not flip the view over the top.
    await page.mouse.move(cx, cy + 150);
    await page.mouse.down();
    await page.mouse.move(cx, cy - 400, { steps: 20 });
    await page.mouse.up();
    await settle();
    b = await cam();
    if (Math.abs(b.el) > Math.PI / 2) say('turning past the top flipped the view');
    if (b.up[2] < 0.99) say('the view lost Z as up');
  } else {
    // One finger turns; two slide; a pinch zooms toward the fingers.
    const cdp = await ctx.newCDPSession(page);
    const touchEv = (type, points) => cdp.send('Input.dispatchTouchEvent', { type,
      touchPoints: points.map(([x, y], id) => ({ x, y, id })) });
    let a = await cam();
    await touchEv('touchStart', [[cx, cy]]);
    for (let i = 1; i <= 8; i += 1) await touchEv('touchMove', [[cx + i * 12, cy]]);
    await touchEv('touchEnd', []);
    await settle();
    let b = await cam();
    if (close(a.az, b.az, 0.05)) say('one finger did not turn the part');
    if (!close(a.distance, b.distance, a.distance * 0.01)) say('one finger changed the distance');
    // One finger down raises the view too (inverted, the default).
    a = b;
    await touchEv('touchStart', [[cx, cy - 60]]);
    for (let i = 1; i <= 8; i += 1) await touchEv('touchMove', [[cx, cy - 60 + i * 12]]);
    await touchEv('touchEnd', []);
    await settle();
    b = await cam();
    if (!(b.el > a.el + 0.2)) say(`one finger down moved the elevation ${a.el} → ${b.el}, not up`);
    // The part fills the window and the conversation scrolls inside itself.
    const fits = await page.evaluate(() => ({ page: document.scrollingElement.scrollHeight - window.innerHeight,
      overflow: getComputedStyle(document.querySelector('#messages')).overflowY,
      viewer: document.querySelector('#viewer').getBoundingClientRect().bottom <= window.innerHeight }));
    if (fits.page > 2) say(`an open part makes the page scroll by ${fits.page} px instead of its conversation`);
    if (fits.overflow !== 'auto') say('the conversation does not scroll inside itself');
    if (!fits.viewer) say('the 3D view is not on screen with the conversation');
    const chatH = await page.evaluate(() => document.querySelector('.chat').getBoundingClientRect().height / window.innerHeight);
    if (chatH < 0.33) say(`the conversation is ${Math.round(chatH * 100)}% of a phone's height`);
    await page.evaluate(() => { const m = document.querySelector('#messages'); m.scrollTop = 0; m.dispatchEvent(new Event('scroll')); });
    const latest = await page.evaluate(() => { const m = document.querySelector('#messages');
      return m.scrollHeight > m.clientHeight + 40 ? !document.querySelector('#toLatest').hidden : true; });
    if (!latest) say('scrolled up, the conversation offers no way back to the newest message');
    const flipBox = await page.locator('#invertY').evaluate((el) => el.closest('label').getBoundingClientRect().height).catch(() => 0);
    if (flipBox && flipBox < 44) say(`Invert vertical drag is ${flipBox}px tall, under the touch floor`);
    a = b;
    await touchEv('touchStart', [[cx - 40, cy], [cx + 40, cy]]);
    for (let i = 1; i <= 8; i += 1) await touchEv('touchMove', [[cx - 40 + i * 8, cy + i * 6], [cx + 40 + i * 8, cy + i * 6]]);
    await touchEv('touchEnd', []);
    await settle();
    b = await cam();
    if (moved(a, b) < a.distance * 0.02) say('two fingers did not slide the part');
    if (!close(a.az, b.az, 0.02)) say('two fingers turned the part');
    a = b;
    await touchEv('touchStart', [[cx - 30, cy], [cx + 30, cy]]);
    for (let i = 1; i <= 8; i += 1) await touchEv('touchMove', [[cx - 30 - i * 8, cy], [cx + 30 + i * 8, cy]]);
    await touchEv('touchEnd', []);
    await settle();
    b = await cam();
    if (b.distance >= a.distance * 0.9) say('a pinch did not zoom in');
  }

  // Named views: animated, and each frames the part.
  for (const [name, check] of [['top', (c) => c.el > 1.4], ['front', (c) => Math.abs(c.el) < 0.05],
    ['right', (c) => Math.abs(c.el) < 0.05], ['iso', (c) => c.el > 0.3 && c.el < 0.9]]) {
    const button = page.locator(`[data-view3d="${name}"]`);
    if (!(await button.count())) { say(`there is no ${name} view`); continue; }
    const before = await cam();
    await button.click();
    const soon = await cam();
    await settle();
    const after = await cam();
    if (!check(after)) say(`the ${name} view is not looking from the ${name} (${JSON.stringify(after)})`);
    if (JSON.stringify(soon) === JSON.stringify(after) && JSON.stringify(before) !== JSON.stringify(after)) {
      say(`the ${name} view jumps rather than moves`);
    }
    const f = await page.evaluate(() => design.viewer.boxOnScreen());
    if (f.max > 1.0 || f.max < 0.45) say(`the ${name} view does not frame the part (${f.max.toFixed(2)})`);
  }

  // Full screen, and the fallback when the API is refused.
  const full = page.locator('#viewFull');
  if (!(await full.count())) { say('there is no Full screen for the 3D view'); return; }
  const vw = page.viewportSize();
  for (const refused of [false, true]) {
    if (refused) {
      await page.evaluate(() => { Element.prototype.requestFullscreen = () => Promise.reject(new Error('refused')); });
    }
    await full.click();
    await page.waitForTimeout(400);
    const r = await page.locator('#viewerWrap').boundingBox();
    if (!r || r.width < vw.width - 2 || r.height < vw.height - 2) {
      say(`Full screen${refused ? ' (API refused)' : ''} does not fill the window (${r && `${Math.round(r.width)}×${Math.round(r.height)}`})`);
    }
    const canvas = await page.evaluate(() => { const c = document.querySelector('#viewer canvas');
      return [c.clientWidth, c.clientHeight, document.querySelector('#viewer').clientWidth, document.querySelector('#viewer').clientHeight]; });
    if (Math.abs(canvas[0] - canvas[2]) > 2 || Math.abs(canvas[1] - canvas[3]) > 2) say('the 3D view did not follow its full screen size');
    // The body pills come along, visible on the screen and usable.
    const pills = page.locator('#bodyList .chip.body');
    const where = refused ? ' (API refused)' : '';
    if ((await pills.count()) !== 2) say(`full screen${where} shows ${await pills.count()} body pills`);
    for (let i = 0; i < await pills.count(); i += 1) {
      const pb = await pills.nth(i).boundingBox();
      const shown = await pills.nth(i).isVisible();
      if (!shown || !pb || !r || pb.y < r.y || pb.y + pb.height > r.y + r.height + 1 || pb.y + pb.height > vw.height + 1
          || pb.x < 0 || pb.x + pb.width > vw.width + 1) {
        say(`body pill ${i + 1} is not on the screen in full screen${where}`);
      } else {
        // On top, not under the full screen view: what is at its middle is it.
        const top = await pills.nth(i).evaluate((el) => { const b = el.getBoundingClientRect();
          const at = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
          return !!at && el.contains(at); });
        if (!top) say(`body pill ${i + 1} is covered in full screen${where}`);
      }
    }
    if ((await pills.count()) && await pills.nth(0).locator('.bodydot').count()) {
      await pills.nth(0).locator('.bodydot').click();
      const pop = page.locator('#colourPop');
      if (!(await pop.isVisible())) say(`a body's dot does not open its colours in full screen${where}`);
      await page.locator('#colourClose').click().catch(() => say(`the colour choice cannot be closed in full screen${where}`));
      const name = pills.nth(0).locator('.bodyname');
      await name.click();
      const hidden = await page.evaluate(() => !design.viewer.group.getObjectByName('Base').visible);
      if (!hidden) say(`a body pill does not hide its body in full screen${where}`);
      await name.click();
    }
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);
    const back = await page.locator('#viewerWrap').boundingBox();
    if (back && back.width >= vw.width - 2 && back.height >= vw.height - 2) say(`Escape did not leave full screen${refused ? ' (API refused)' : ''}`);
  }
  const ok = await page.evaluate(async () => {
    const v = document.querySelector('#viewer');
    v.style.height = '300px';
    await new Promise((r) => setTimeout(r, 300));
    const c = v.querySelector('canvas');
    const fits = Math.abs(c.clientHeight - 300) < 2 && Math.abs(c.height / (window.devicePixelRatio > 2 ? 2 : window.devicePixelRatio || 1) - 300) < 2;
    v.style.height = '';
    return fits;
  });
  if (!ok) say('the 3D view does not follow the size of its box');
}

// Measure, the way Fusion's does: it snaps to what is near the pointer,
// draws the distance on the line, and says more when faces are picked.
async function measureTool(page, say, touch) {
  const can = await page.evaluate(() => ['snapAt', 'measureState']
    .filter((m) => !(design.viewer && typeof design.viewer[m] === 'function')));
  if (can.length) { say(`Measure cannot be read back (${can.join(', ')})`); return; }
  const settle = () => page.evaluate(() => design.viewer.settled());
  const screen = (p) => page.evaluate((q) => design.viewer.screenOf(q), p);
  const state = () => page.evaluate(() => design.viewer.measureState());
  const near = (a, b, tol) => a && b && Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) <= tol;
  await page.locator('#measureBtn').click();
  await page.evaluate(() => design.viewer.view('iso'));
  await settle();
  const off = touch ? 9 : 5;
  const pick = async (p, dx = off, dy = off * 0.6) => {
    const [x, y] = await screen(p);
    if (touch) await page.touchscreen.tap(x + dx, y + dy);
    else await page.mouse.click(x + dx, y + dy);
    await page.waitForTimeout(120);
  };
  if (!touch) {
    for (const [kind, point, want, tol] of [
      ['vertex', [40, 0, 36], [40, 0, 36], 0.05],
      ['midpoint', [20, 0, 36], [20, 0, 36], 0.05],
      ['edge', [9, 0, 36], [9, 0, 36], 2.5],
      ['centre', [20, 15, 36], [20, 15, 36], 0.05],
      ['face', [11, 9, 36], [11, 9, 36], 2.5]]) {
      const [x, y] = await screen(point);
      const dx = kind === 'edge' ? 0 : kind === 'face' || kind === 'centre' ? 3 : 4;
      const dy = kind === 'edge' ? 4 : 3;
      await page.mouse.move(x + dx, y + dy);
      await page.waitForTimeout(100);
      const got = await page.evaluate(([px, py]) => design.viewer.snapAt(px, py), [x + dx, y + dy]);
      const mark = await page.evaluate(() => { const m = document.querySelector('#viewer .snapmark');
        return m && !m.hidden && getComputedStyle(m).display !== 'none' ? m.dataset.kind : null; });
      if (!got || got.kind !== kind) say(`near ${kind === 'centre' ? "a face's centre" : `a ${kind}`} Measure snapped to ${got && got.kind}`);
      else if (!near(got.point, want, tol)) say(`the ${kind} snap took ${got.point.map((v) => v.toFixed(2))}, not ${want}`);
      if (mark !== kind) say(`the snap marker shows ${mark} near a ${kind}`);
    }
  }
  // Corner to corner: the distance on the line, at its middle.
  await pick([40, 0, 36]);
  await pick([0, 0, 36], -off, off * 0.6);
  let m = await state();
  const last = m.results[m.results.length - 1];
  if (!last || Math.abs(last.distance - 40) > 0.01) say(`corner to corner measured ${last && last.distance}, not 40 (no snap)`);
  else if (Math.abs(last.dx - 40) > 0.01 || last.dy > 0.01 || last.dz > 0.01) say(`ΔX/ΔY/ΔZ read ${last.dx}/${last.dy}/${last.dz}`);
  const mid = await screen([20, 0, 36]);
  if (!m.label || !m.label.visible || !/40\.00/.test(m.label.text)) say(`the line carries no distance (${JSON.stringify(m.label)})`);
  else if (Math.hypot(m.label.x - mid[0], m.label.y - mid[1]) > 40) say(`the distance is drawn ${Math.round(Math.hypot(m.label.x - mid[0], m.label.y - mid[1]))} px from the line's middle`);
  const out = await page.locator('#measureOut').textContent();
  if (!/ΔX/.test(out) || !/ΔZ/.test(out)) say(`the measurement does not say ΔX/ΔY/ΔZ (${out})`);
  // A face, then a corner: how far that corner is from the face's plane.
  // Well inside the face: a phone's wider snap reaches an edge 9 mm away.
  await pick([16, 12, 36], 0, 0);
  await pick([40, 0, 0], off, -off * 0.6);
  m = await state();
  const perp = m.results[m.results.length - 1];
  if (!perp || perp.perpendicular == null || Math.abs(perp.perpendicular - 36) > 0.05) say(`face to corner gave no 36 mm perpendicular (${JSON.stringify(perp)})`);
  // Two faces at right angles: the angle between them.
  // Well inside the face: a phone's wider snap reaches an edge 9 mm away.
  await pick([16, 12, 36], 0, 0);
  await pick([12, 0, 10], 0, 0);
  m = await state();
  const ang = m.results[m.results.length - 1];
  if (!ang || ang.angle == null || Math.abs(ang.angle - 90) > 0.5) say(`two faces at right angles gave ${ang && ang.angle}°`);
  const listed = await page.locator('#measureList li').count();
  if (listed < 3) say(`the recent measurements list ${listed}, not the last 3`);
  await page.keyboard.press('Escape');
  m = await state();
  if (m.points.length || (m.label && m.label.visible)) say('Escape did not clear the measurement');
  const clear = page.locator('#measureClear');
  if (!(await clear.count())) say('there is no Clear for the measurements');
  else {
    const cb = await clear.boundingBox();
    if (touch && cb && cb.height < 44) say(`Clear is ${cb.height}px tall, under the touch floor`);
    await clear.click();
    if (await page.locator('#measureList li').count()) say('Clear did not empty the list');
  }
  await page.locator('#measureBtn').click();
}

// A body's dot opens its colours: the AMS trays first, then any colour.
async function bodyColours(page, say, touch, label) {
  const lid = page.locator('#bodyList .chip.body').nth(1);
  const dot = lid.locator('.bodydot');
  if (!(await dot.count())) { say("a body's pill has no colour dot to press"); return; }
  const colourOf = () => page.evaluate(() => `#${design.viewer.group.getObjectByName('Lid').material.color.getHexString()}`);
  const saved = () => POSTS.filter((p) => p.label === label && p.body.body_colours).map((p) => p.body.body_colours);
  await dot.click();
  const pop = page.locator('#colourPop');
  if (!(await pop.isVisible())) { say("the Lid's dot did not open a colour choice"); return; }
  if (!/print/i.test(await pop.textContent())) say('the colour choice does not say that the colour is what it prints in');
  const swatch = pop.locator('.swatch[data-colour="#F2F2F2"]');
  if (!(await swatch.count())) say("the colour choice does not offer the AMS tray's colour");
  else {
    if (touch) {
      const sb = await swatch.boundingBox();
      if (sb.width < 44 || sb.height < 44) say(`a tray swatch is ${sb.width}×${sb.height}, under the touch floor`);
    }
    await swatch.click();
    await page.waitForTimeout(200);
    if ((await colourOf()) !== '#f2f2f2') say(`choosing the tray's colour left the Lid ${await colourOf()}`);
    const last = saved().pop();
    if (!last || last.Lid !== '#F2F2F2') say(`choosing a colour did not save it to the part (${JSON.stringify(last)})`);
    const bg = await dot.locator('i').evaluate((i) => getComputedStyle(i).backgroundColor);
    if (bg !== 'rgb(242, 242, 242)') say(`the Lid's dot shows ${bg} after the change`);
    if (await pop.isVisible()) say('the colour choice stayed open after a colour was chosen');
  }
  await dot.click();
  const pick = page.locator('#colourPick');
  if (!(await pick.count())) say('the colour choice offers no other colour');
  else {
    await pick.evaluate((i) => { i.value = '#00ff00'; i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); });
    await page.waitForTimeout(200);
    if ((await colourOf()) !== '#00ff00') say(`a colour from the picker left the Lid ${await colourOf()}`);
    if ((saved().pop() || {}).Lid !== '#00FF00') say('a colour from the picker was not saved');
  }
  if (!(await pop.isVisible())) await dot.click();
  const reset = page.locator('#colourReset');
  if (!(await reset.count())) say("there is no way back to brAIn's colour");
  else {
    await reset.click();
    await page.waitForTimeout(200);
    if ((await colourOf()) !== '#ff0000') say(`going back to brAIn's colour left the Lid ${await colourOf()}`);
    if ((saved().pop() || {}).Lid !== null) say("going back to brAIn's colour was not saved");
  }
  if (await pop.isVisible()) await page.locator('#colourClose').click();
}

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
    if (route.request().method() === 'POST' && /^api\/design\/parts\/[^/]+\/(message|studio)$/.test(path)) {
      POSTS.push({ label, path, body: route.request().postDataJSON() });
      return route.fulfill({ json: { ok: true, part: PART, studio: {} } });
    }
    if (route.request().method() === 'POST' && path === `api/design/parts/${PART.id}`) {
      const body = route.request().postDataJSON();
      POSTS.push({ label, path, body });
      const chosen = { ...(PART.body_colours || {}) };
      for (const [name, colour] of Object.entries(body.body_colours || {})) {
        if (colour === null) delete chosen[name];
        else chosen[name] = { colour: colour.toUpperCase(), over: PART.versions[1].colors[name] || '' };
      }
      PART.body_colours = chosen;
      return route.fulfill({ json: { ok: true, part: PART } });
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

  // brAIn answers in Markdown; it is drawn as rich text, and markup in it stays text.
  const md = await page.evaluate(() => {
    const m = document.querySelector('#messages .msg.assistant .md');
    return m && { strong: m.querySelectorAll('strong').length, code: m.querySelectorAll('code').length,
      li: m.querySelectorAll('li').length, b: m.querySelectorAll('b').length, text: m.textContent };
  });
  if (!md) say('the reply is not drawn as Markdown');
  else {
    if (md.strong !== 1 || md.code !== 1 || md.li !== 2) say(`Markdown drew ${JSON.stringify(md)}`);
    if (md.b || !md.text.includes('<b>not markup</b>')) say('HTML in a reply was rendered rather than shown');
    if (md.text.includes('**')) say('the reply still shows the asterisks');
  }

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
  await page.locator('#messages').click();
  if (await help.isVisible()) say('the help did not close on a tap elsewhere');
  const bb = await btn.boundingBox();
  if (touch && (bb.width < 44 || bb.height < 44)) say(`the ? is ${bb.width}×${bb.height}, under the 44 px touch floor`);
  await btn.click();
  if (!(await help.isVisible())) say('the ? did not open the help');
  await btn.click();
  if (await help.isVisible()) say('the ? did not close the help again');
  }

  // The version: one line under the view, the rest a press away.
  const info = page.locator('#partInfo');
  if (!(await info.count())) say('the version has no one-line summary under the view');
  else {
    if (await info.evaluate((d) => d.open)) say("the version's details are open by default");
    const line = await info.locator('summary').innerText();
    for (const want of ['v1 of 2', '40 × 30 × 36 mm', '14 g', '2 warnings']) {
      if (!line.includes(want)) say(`the version's line does not say “${want}” (${line})`);
    }
    const lineH = (await info.boundingBox()).height;
    if (lineH > 52) say(`the closed version line is ${Math.round(lineH)}px tall`);
    if (await page.locator('#versionInfo').isVisible()) say("the version's text shows while it is closed");
    await info.locator('summary').click();
    const opened = await page.locator('#versionInfo').innerText();
    for (const want of ['press-fit lid', 'under two perimeters', 'clearance: 0.2 mm']) {
      if (!opened.includes(want)) say(`the version's details do not say “${want}”`);
    }
    if ((await page.locator('#versions .chip').count()) !== 2) say("the version's details do not offer both versions");
    await info.locator('summary').click();
  }
  if (await page.locator('#measureOut').isVisible()) say('a line of measure text shows under the view while nothing is measured');

  // The body key.
  const chips = page.locator('#bodyList .chip.body');
  if ((await chips.count()) !== 2) {
    say(`the body key shows ${await chips.count()} bodies, not 2`);
  } else if (!(await chips.nth(1).locator('.bodyname').count())) {
    say("a body's pill has no name to press to hide it");
  } else {
    await chips.nth(1).locator('.bodyname').click();
    const lidShown = await page.evaluate(() => design.viewer.group.getObjectByName('Lid').visible);
    if (lidShown) say('tapping a body in the key did not hide it');
    await chips.nth(1).locator('.bodyname').click();
    if (touch) {
      for (const part of ['.bodydot', '.bodyname']) {
        const bb = await chips.nth(1).locator(part).boundingBox();
        if (bb && (bb.height < 44 || (part === '.bodydot' && bb.width < 44))) say(`a pill's ${part.slice(5)} is ${Math.round(bb.width)}×${Math.round(bb.height)}, under the touch floor`);
      }
    }
  }

  await viewerMoves(page, say, touch, ctx);
  await measureTool(page, say, touch);
  await bodyColours(page, say, touch, label);

  const wide = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
  if (wide > 1) say(`the Design tab scrolls sideways by ${wide} px`);

  // Print: three ways, each a real target, each doing what it says.
  await page.locator('#partPrint').click();
  const choice = page.locator('#printChoice');
  if (!(await choice.isVisible())) {
    say('Print did not offer a choice');
    // Whatever opened instead is closed, so the rest is still measured.
    await page.evaluate(() => document.querySelectorAll('dialog[open]').forEach((d) => d.close()));
  } else {
    const box = await choice.boundingBox();
    for (const [id, words] of [['#pcAuto', 'Auto print'], ['#pcManual', 'Manual print'],
      ['#pcStudio', 'Open in Bambu Studio']]) {
      const b = page.locator(id);
      if (!(await b.count()) || !(await b.isVisible())) { say(`Print does not offer ${words}`); continue; }
      if (!(await b.textContent()).includes(words)) say(`${id} does not say ${words}`);
      const bb = await b.boundingBox();
      if (touch && bb.height < 44) say(`${words} is ${bb.height}px tall, under the touch floor`);
      if (bb.x < box.x - 1 || bb.x + bb.width > box.x + box.width + 1) say(`${words} spills out of the dialog`);
    }
    await page.locator('#pcManual').click();
    const selects = page.locator('#dpTrays .bodytray select');
    await selects.first().waitFor({ timeout: 5000 }).catch(() => say('Manual print offers no tray per body'));
    if ((await selects.count()) === 2) {
      const values = await selects.evaluateAll((els) => els.map((e) => e.value));
      if (values.join() !== '0,external') say(`the body trays start at ${values}, not the closest colour`);
    }
    await page.locator('#dpCancel').click();
    await page.locator('#partPrint').click();
    await page.locator('#pcAuto').click();
    await page.waitForTimeout(200);
    const asked = POSTS.find((p) => p.label === label && p.path.endsWith('/message'));
    if (!asked || !/Print this part now/.test(asked.body.text)) say('Auto print did not ask brAIn to print');
    await page.locator('#partPrint').click();
    await page.locator('#pcStudio').click();
    await page.waitForTimeout(200);
    const opened = POSTS.find((p) => p.label === label && p.path.endsWith('/studio'));
    if (!opened || opened.body.version !== 1) say('Open in Bambu Studio did not open this version');
    if (!(await page.evaluate(() => document.body.classList.contains('studio-open')))) {
      say('Open in Bambu Studio did not go to the Studio tab');
    }
    await page.locator('#designTab').click();
  }

  // Files: what was brought in, and the design once, with no Delete.
  await page.locator('.tab[data-view="files"]').click();
  await page.locator('#fileList .frow').first().waitFor();
  const rows = await page.locator('#fileList .frow').allTextContents();
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

  // Settings: Find lists what is new and what moved; Add leaves only the code.
  await page.locator('.tab[data-view="settings"]').click();
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
  if (widePrinters > 1) say(`the Settings tab scrolls sideways by ${widePrinters} px`);
  if (process.env.SHOTS) {
    await page.screenshot({ path: `${process.env.SHOTS}/printers-${label}.png`, fullPage: true });
    await page.locator('.tab[data-view="design"]').click();
    await page.locator('#bodyList .chip.body .bodyname').nth(1).click().catch(() => {});
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${process.env.SHOTS}/design-${label}.png`, fullPage: true });
    await page.locator('#viewHelpBtn').click();
    await page.locator('#viewer').screenshot({ path: `${process.env.SHOTS}/help-${label}.png` });
    await page.locator('#viewHelpBtn').click();
    await page.locator('#bodyList .chip.body .bodyname').nth(1).click().catch(() => {});
    await page.evaluate(() => design.viewer.view('iso'));
    await page.evaluate(() => design.viewer.settled());
    await page.locator('#measureBtn').click();
    for (const [p, dx] of [[[40, 0, 36], 5], [[0, 30, 36], -5]]) {
      const [x, y] = await page.evaluate((q) => design.viewer.screenOf(q), p);
      if (touch) await page.touchscreen.tap(x + dx, y + 3); else await page.mouse.click(x + dx, y + 3);
      await page.waitForTimeout(150);
    }
    if (!touch) {
      const [x, y] = await page.evaluate((q) => design.viewer.screenOf(q), [20, 0, 36]);
      await page.mouse.move(x + 3, y + 3);
      await page.waitForTimeout(200);
    }
    await page.locator('#viewerWrap').screenshot({ path: `${process.env.SHOTS}/measure-${label}.png` });
    await page.locator('#bodyList .chip.body .bodydot').nth(1).click().catch(() => {});
    await page.waitForTimeout(150);
    await page.locator('#viewerWrap').screenshot({ path: `${process.env.SHOTS}/colour-${label}.png` });
    await page.keyboard.press('Escape');
    await page.locator('#viewFull').click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${process.env.SHOTS}/fullscreen-${label}.png` });
    await page.keyboard.press('Escape');
  }
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.log(`FAIL\n${problems.map((p) => `  - ${p}`).join('\n')}`);
  process.exit(1);
}
console.log('OK: colours, controls help, body key, Print choices, Files list and Find printers at 390 (touch) and 1280.');
