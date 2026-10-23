/* Playwright measure for BRUH Bambu Studio's Studio tab on a phone.
 *
 *   node tests/manual/measure-bambu-studio-mobile.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it;
 *    SHOTS=dir to keep a screenshot of each width;
 *    BAMBU_PANEL=dir to serve a different copy of the panel, for a before shot)
 *
 * Drives the real panel files against stubbed answers at 390 (touch) and
 * 1200. There is no VNC server here, so noVNC's RFB module is a stand-in that
 * maps a mouse event the way noVNC 1.3 does (the event's client position
 * through the canvas's own bounds, divided by the scale it fitted to its
 * container) and records what a server would have been sent. Fails on:
 *  - the touch controls missing at 390 (Move, Drag, Scroll, Fit, Keyboard),
 *    or the stock noVNC frame still being what a phone gets;
 *  - a tap not landing on the screen pixel under the finger, before or
 *    after zooming;
 *  - a pinch not zooming, not keeping the point between the fingers under
 *    them, or zooming past fit-to-width or the maximum;
 *  - one finger not panning in Move, not turning the wheel in Scroll, or
 *    not holding the left button in Drag;
 *  - a long press not being a right click (VNC button 3);
 *  - the Keyboard button not focusing a 16px text box, or typed text, Enter
 *    and Backspace not reaching the screen;
 *  - a control under 44px, sideways scroll, or any page error;
 *  - the desktop (1200, a mouse) not getting the stock noVNC page as before.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const PANEL = process.env.BAMBU_PANEL
  || fileURLToPath(new URL('../../bruh-bambu-studio/panel/', import.meta.url));
const FB_W = 1600;
const FB_H = 900;

// A drawing of a screen: a title bar and a labelled grid, so a picture of
// it says where things are.
const DRAW = `
function drawScreen(c) {
  const g = c.getContext('2d');
  g.fillStyle = '#2b2f36'; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = '#00ae42'; g.fillRect(0, 0, c.width, 60);
  g.fillStyle = '#fff'; g.font = '28px sans-serif'; g.fillText('Bambu Studio (stand-in)', 20, 40);
  g.strokeStyle = '#555'; g.fillStyle = '#bbb'; g.font = '18px sans-serif';
  for (let x = 0; x <= c.width; x += 100) { g.beginPath(); g.moveTo(x, 60); g.lineTo(x, c.height); g.stroke(); g.fillText(String(x), x + 4, 84); }
  for (let y = 100; y <= c.height; y += 100) { g.beginPath(); g.moveTo(0, y); g.lineTo(c.width, y); g.stroke(); g.fillText(String(y), 4, y - 4); }
  g.fillStyle = '#e0352b'; g.beginPath(); g.arc(1000, 300, 14, 0, 7); g.fill();
}`;

const RFB_STUB = `${DRAW}
const log = (window.__vnc = window.__vnc || { mouse: [], keys: [], made: 0 });
export default class RFB extends EventTarget {
  constructor(target, url, options) {
    super();
    log.made += 1; log.url = url; log.options = options; log.rfb = this;
    this._screen = document.createElement('div');
    Object.assign(this._screen.style, { display: 'flex', width: '100%', height: '100%', overflow: 'auto' });
    this._canvas = document.createElement('canvas');
    this._canvas.width = ${FB_W}; this._canvas.height = ${FB_H};
    this._canvas.style.margin = 'auto';
    drawScreen(this._canvas);
    this._screen.append(this._canvas);
    target.append(this._screen);
    this._scale = 1;
    this.focusOnClick = true;
    new ResizeObserver(() => requestAnimationFrame(() => this._autoscale())).observe(this._screen);
    const pos = (ev) => {
      const b = this._canvas.getBoundingClientRect();
      const x = Math.min(Math.max(ev.clientX - b.left, 0), b.width - 1);
      const y = Math.min(Math.max(ev.clientY - b.top, 0), b.height - 1);
      return { x: x / this._scale, y: y / this._scale };
    };
    for (const type of ['mousedown', 'mouseup', 'mousemove']) {
      this._canvas.addEventListener(type, (ev) => {
        const p = pos(ev);
        log.mouse.push({ type, x: p.x, y: p.y, button: ev.button });
      });
    }
    this._canvas.addEventListener('wheel', (ev) => {
      const p = pos(ev);
      log.mouse.push({ type: 'wheel', x: p.x, y: p.y, deltaY: ev.deltaY });
    });
    setTimeout(() => { log.connected = true; this.dispatchEvent(new CustomEvent('connect')); }, 30);
  }
  _autoscale() {
    const r = this._screen.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const s = (${FB_W} / ${FB_H} >= r.width / r.height) ? r.width / ${FB_W} : r.height / ${FB_H};
    this._scale = s;
    this._canvas.style.width = s * ${FB_W} + 'px';
    this._canvas.style.height = s * ${FB_H} + 'px';
  }
  sendKey(keysym, code, down) { log.keys.push(keysym); }
  disconnect() { log.connected = false; this.dispatchEvent(new CustomEvent('disconnect')); }
  focus() {}
}`;
const KEYSYMDEF_STUB = 'export default { lookup(u) { return u < 0x100 ? u : 0x01000000 | u; } };';
const KEYSYM_STUB = `export default { XK_BackSpace: 0xff08, XK_Tab: 0xff09, XK_Return: 0xff0d,
  XK_Escape: 0xff1b, XK_Left: 0xff51, XK_Up: 0xff52, XK_Right: 0xff53, XK_Down: 0xff54 };`;
const VNC_HTML = `<!doctype html><body style="margin:0;background:#000">
<canvas id="c" width="${FB_W}" height="${FB_H}" style="width:100%"></canvas>
<script>${DRAW}; drawScreen(document.getElementById('c'));</script></body>`;

const STATE = { ok: true, version: 'dev', printers: [], jobs: [],
  studio: { installed: true, running: true, wanted: true, version: '2.3.0', install: {} },
  ha: { reason: 'ok', restart_needed: false } };

const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});
const problems = [];

async function open(label, viewport, touch) {
  const say = (m) => problems.push(`${label}: ${m}`);
  const ctx = await browser.newContext({ viewport, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => say(`page error ${e.message}`));
  await page.route('http://panel.test/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/ingress\/abc\//, '');
    const js = (body) => route.fulfill({ body, contentType: 'application/javascript' });
    if (path === 'novnc/core/rfb.js') return js(RFB_STUB);
    if (path === 'novnc/core/input/keysymdef.js') return js(KEYSYMDEF_STUB);
    if (path === 'novnc/core/input/keysym.js') return js(KEYSYM_STUB);
    if (path === 'novnc/vnc.html') return route.fulfill({ body: VNC_HTML, contentType: 'text/html' });
    if (path === 'api/state') return route.fulfill({ json: STATE });
    if (path === 'api/design/status') return route.fulfill({ json: { ok: true, brain: { state: 'absent' } } });
    if (path.startsWith('api/')) return route.fulfill({ json: { ok: true, files: [], parts: [], printers: [] } });
    const file = path || 'index.html';
    const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css'
      : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html';
    try { return route.fulfill({ body: readFileSync(join(PANEL, file)), contentType: type }); }
    catch (_) { return route.fulfill({ status: 404, body: '' }); }
  });
  // Ingress mounts the panel under a prefix; the websocket has to keep it.
  await page.goto('http://panel.test/ingress/abc/');
  return { page, say, ctx };
}

async function shot(page, name) {
  if (!process.env.SHOTS) return;
  mkdirSync(process.env.SHOTS, { recursive: true });
  await page.screenshot({ path: join(process.env.SHOTS, `${name}.png`) });
}

const view = (page) => page.evaluate(() => {
  const t = window.TouchScreen;
  const r = document.querySelector('#tsPort').getBoundingClientRect();
  return { z: t.z, ox: t.ox, oy: t.oy, left: r.left, top: r.top, w: r.width, h: r.height };
});
// The client point that shows screen pixel (fx, fy) now.
const at = (v, fx, fy) => ({ x: v.left + v.ox + fx * v.z, y: v.top + v.oy + fy * v.z });
const mouseLog = (page) => page.evaluate(() => window.__vnc.mouse.splice(0));
const near = (a, b, tol) => Math.abs(a - b) <= tol;

// ------------------------------------------------------------------ phone ---
{
  const { page, say, ctx } = await open('390 touch', { width: 390, height: 780 }, true);
  const ok = await page.waitForFunction(() => window.__vnc && window.__vnc.connected
    && window.TouchScreen && window.TouchScreen.fbW === 1600, null, { timeout: 8000 }).then(() => true, () => false);
  if (!ok) {
    say('the Studio tab never opened the screen on this page (no noVNC RFB connected)');
    await shot(page, 'studio-390');
  } else {
    await page.waitForTimeout(150);
    const setup = await page.evaluate(() => ({
      frame: !document.querySelector('#screen').hidden && !!document.querySelector('#screen').getAttribute('src'),
      shown: !document.querySelector('#touchScreen').hidden,
      url: window.__vnc.url, protocols: window.__vnc.options && window.__vnc.options.wsProtocols,
      names: [...document.querySelectorAll('#touchScreen button')].map((b) => b.textContent.trim()),
    }));
    if (setup.frame) say('the phone still gets the stock noVNC page in a frame');
    if (!setup.shown) say('the touch screen is not shown');
    if (setup.url !== 'ws://panel.test/ingress/abc/websockify') say(`the websocket is ${setup.url}, not the ingress path`);
    if (!(setup.protocols || []).includes('binary')) say('the websocket does not ask for the binary protocol the bridge speaks');
    for (const want of ['Move', 'Drag', 'Scroll', 'Fit', 'Keyboard']) {
      if (!setup.names.some((n) => n.startsWith(want))) say(`no “${want}” control`);
    }
    await shot(page, 'studio-390');

    // Fit to width first.
    let v = await view(page);
    if (!near(v.z, v.w / 1600, 0.001)) say(`the screen opens at ${v.z.toFixed(3)}, not fit to width (${(v.w / 1600).toFixed(3)})`);

    // A tap at fit is a left click on the pixel under the finger.
    await mouseLog(page);
    let p = at(v, 800, 450);
    await page.touchscreen.tap(p.x, p.y);
    await page.waitForTimeout(50);
    let got = (await mouseLog(page)).filter((m) => m.type === 'mousedown');
    if (got.length !== 1 || got[0].button !== 0 || !near(got[0].x, 800, 5) || !near(got[0].y, 450, 5)) {
      say(`a tap on (800, 450) at fit sent ${JSON.stringify(got)}`);
    }

    // Pinch out about a point: the zoom grows and the point stays put.
    const cdp = await ctx.newCDPSession(page);
    const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
    async function pinch(cx, cy, from, to, steps = 10) {
      const pts = (d) => [{ x: cx - d / 2, y: cy, id: 1 }, { x: cx + d / 2, y: cy, id: 2 }];
      await touch('touchStart', pts(from));
      for (let i = 1; i <= steps; i += 1) await touch('touchMove', pts(from + ((to - from) * i) / steps));
      await touch('touchEnd', []);
      await page.waitForTimeout(80);
    }
    v = await view(page);
    const cx = v.left + v.w / 2, cy = v.top + v.oy + 300 * v.z;
    const under = { x: (cx - v.left - v.ox) / v.z, y: (cy - v.top - v.oy) / v.z };
    await pinch(cx, cy, 60, 240);
    let v2 = await view(page);
    if (!(v2.z > v.z * 3)) say(`a pinch out from 60 to 240 px took the zoom from ${v.z.toFixed(3)} to ${v2.z.toFixed(3)}`);
    const after = { x: (cx - v2.left - v2.ox) / v2.z, y: (cy - v2.top - v2.oy) / v2.z };
    if (!near(after.x, under.x, 3) || !near(after.y, under.y, 3)) {
      say(`the pinch was not centred on the fingers: (${under.x.toFixed(0)}, ${under.y.toFixed(0)}) moved to (${after.x.toFixed(0)}, ${after.y.toFixed(0)})`);
    }
    // No click came out of a pinch.
    if ((await mouseLog(page)).some((m) => m.type === 'mousedown')) say('a pinch clicked');
    await shot(page, 'studio-390-zoomed');

    // A tap after zooming still lands on the pixel under the finger.
    await page.waitForTimeout(80);
    v = await view(page);
    const target = { x: Math.round(after.x + 40), y: Math.round(after.y + 20) };
    p = at(v, target.x, target.y);
    await page.touchscreen.tap(p.x, p.y);
    await page.waitForTimeout(50);
    got = (await mouseLog(page)).filter((m) => m.type === 'mousedown');
    if (got.length !== 1 || !near(got[0].x, target.x, 2) || !near(got[0].y, target.y, 2)) {
      say(`after zooming, a tap on (${target.x}, ${target.y}) sent ${JSON.stringify(got)}`);
    }

    // One finger in Move pans the zoomed screen and clicks nothing.
    v = await view(page);
    const sx = v.left + v.w / 2, sy = v.top + v.h / 2;
    await touch('touchStart', [{ x: sx, y: sy, id: 1 }]);
    for (let i = 1; i <= 8; i += 1) await touch('touchMove', [{ x: sx + 10 * i, y: sy + 5 * i, id: 1 }]);
    await touch('touchEnd', []);
    await page.waitForTimeout(50);
    v2 = await view(page);
    // Panning stops at the screen's edges, so the expected move is clamped.
    const clampTo = (o, content, room, centre) => (content <= room ? (centre ? (room - content) / 2 : 0)
      : Math.min(0, Math.max(room - content, o)));
    const wantX = clampTo(v.ox + 80, 1600 * v.z, v.w, true) - v.ox;
    const wantY = clampTo(v.oy + 40, 900 * v.z, v.h, false) - v.oy;
    if (!(Math.abs(wantX) > 20)) say('the pan test had no room to move the screen');
    if (!near(v2.ox - v.ox, wantX, 2) || !near(v2.oy - v.oy, wantY, 2)) {
      say(`dragging one finger 80, 40 px in Move panned by ${(v2.ox - v.ox).toFixed(0)}, ${(v2.oy - v.oy).toFixed(0)}, not ${wantX.toFixed(0)}, ${wantY.toFixed(0)}`);
    }
    if ((await mouseLog(page)).some((m) => m.type === 'mousedown')) say('panning clicked');

    // A long press is a right click: VNC button 3 (DOM button 2).
    v = await view(page);
    p = at(v, target.x, target.y);
    await touch('touchStart', [{ x: p.x, y: p.y, id: 1 }]);
    await page.waitForTimeout(800);
    await touch('touchEnd', []);
    await page.waitForTimeout(50);
    got = (await mouseLog(page)).filter((m) => m.type === 'mousedown');
    if (got.length !== 1 || got[0].button !== 2) say(`a long press sent ${JSON.stringify(got)}, not one right click`);
    else if (!near(got[0].x, target.x, 2) || !near(got[0].y, target.y, 2)) say(`a long press right-clicked at ${got[0].x}, ${got[0].y}`);

    // Scroll: one finger turns the wheel, finger up scrolling down.
    await page.waitForTimeout(500);
    await page.locator('#tsModes [data-mode="scroll"]').tap();
    await touch('touchStart', [{ x: sx, y: sy, id: 1 }]);
    for (let i = 1; i <= 10; i += 1) await touch('touchMove', [{ x: sx, y: sy - 12 * i, id: 1 }]);
    await touch('touchEnd', []);
    await page.waitForTimeout(50);
    const log = await mouseLog(page);
    const wheels = log.filter((m) => m.type === 'wheel');
    if (wheels.length < 3 || wheels.some((w) => !(w.deltaY > 0))) say(`a 120 px swipe up in Scroll sent ${wheels.length} wheel steps: ${JSON.stringify(wheels)}`);
    if (log.some((m) => m.type === 'mousedown')) say('scrolling clicked');

    // Drag: one finger holds the left button down from where it started.
    // A tap straight after a swipe stops Chrome's fling rather than clicking.
    await page.waitForTimeout(500);
    await page.locator('#tsModes [data-mode="drag"]').tap();
    await touch('touchStart', [{ x: sx, y: sy, id: 1 }]);
    for (let i = 1; i <= 6; i += 1) await touch('touchMove', [{ x: sx + 10 * i, y: sy, id: 1 }]);
    await touch('touchEnd', []);
    await page.waitForTimeout(50);
    const drag = (await mouseLog(page)).filter((m) => m.type !== 'mousemove');
    if (drag.length !== 2 || drag[0].type !== 'mousedown' || drag[0].button !== 0 || drag[1].type !== 'mouseup'
      || !(drag[1].x > drag[0].x)) say(`a drag in Drag sent ${JSON.stringify(drag)}`);
    await page.waitForTimeout(500);
    await page.locator('#tsModes [data-mode="pan"]').tap();

    // Pinch limits: far in stops at fit, far out stops at the maximum.
    v = await view(page);
    await pinch(v.left + v.w / 2, v.top + v.h / 2, 300, 4);
    v2 = await view(page);
    if (!near(v2.z, v2.w / 1600, 0.001)) say(`pinching all the way in stopped at ${v2.z.toFixed(3)}, not fit to width`);
    for (let i = 0; i < 4; i += 1) await pinch(v.left + v.w / 2, v.top + v.h / 2, 40, 300);
    v2 = await view(page);
    if (!(v2.z <= 2.0001 && v2.z >= 1.99)) say(`pinching all the way out reached ${v2.z.toFixed(3)}, not the maximum of 2`);
    const wide = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
    if (wide > 0) say(`zoomed in, the page scrolls sideways by ${wide}px`);

    // Fit puts it back.
    await page.waitForTimeout(500);
    await page.locator('#tsFit').tap();
    v2 = await view(page);
    if (!near(v2.z, v2.w / 1600, 0.001)) say(`Fit left the zoom at ${v2.z.toFixed(3)}`);

    // The keyboard: a 16px box, and what is typed reaches the screen.
    await page.evaluate(() => { window.__vnc.keys.length = 0; });
    await page.locator('#tsKeys').tap();
    const box = await page.evaluate(() => {
      const el = document.querySelector('#tsType');
      return { focused: document.activeElement === el, size: parseFloat(getComputedStyle(el).fontSize),
        shown: !el.closest('[hidden]') };
    });
    if (!box.shown || !box.focused) say('the Keyboard button does not focus a text box');
    if (box.size < 16) say(`the text box is ${box.size}px, under the 16px iOS zoom floor`);
    await page.keyboard.type('Ab1');
    await page.keyboard.press('Enter');
    await page.keyboard.press('Backspace');
    await page.locator('#tsBack').tap();
    await page.locator('#tsEnter').tap();
    const keys = await page.evaluate(() => window.__vnc.keys.slice());
    const want = [0x41, 0x62, 0x31, 0xff0d, 0xff08, 0xff08, 0xff0d];
    if (JSON.stringify(keys) !== JSON.stringify(want)) say(`typing sent ${JSON.stringify(keys)}, not ${JSON.stringify(want)}`);
    const still = await page.evaluate(() => document.activeElement === document.querySelector('#tsType'));
    if (!still) say('pressing Backspace or Enter put the keyboard away');
    await shot(page, 'studio-390-keyboard');

    // Every control is a 44px target, and nothing scrolls sideways.
    const small = await page.evaluate(() => [...document.querySelectorAll('#touchScreen button, #touchScreen input')]
      .filter((b) => !b.closest('[hidden]'))
      .map((b) => ({ b, r: b.getBoundingClientRect() }))
      .filter(({ r }) => r.height < 44 || r.width < 44)
      .map(({ b, r }) => `${(b.textContent || b.getAttribute('aria-label')).trim()} ${Math.round(r.width)}x${Math.round(r.height)}`));
    if (small.length) say(`under the touch floor: ${small.join(', ')}`);
    const unnamed = await page.evaluate(() => [...document.querySelectorAll('#touchScreen button, #touchScreen input')]
      .filter((b) => !(b.textContent.trim() || b.getAttribute('aria-label'))).length);
    if (unnamed) say(`${unnamed} control(s) with no name`);
    const sideways = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
    if (sideways > 0) say(`the page scrolls sideways by ${sideways}px`);
  }
  await ctx.close();
}

// ---------------------------------------------------------------- desktop ---
{
  const { page, say, ctx } = await open('1200', { width: 1200, height: 800 }, false);
  await page.waitForFunction(() => document.querySelector('#screen').getAttribute('src'), null, { timeout: 8000 })
    .catch(() => say('the desktop never loaded the screen'));
  const d = await page.evaluate(() => ({
    src: document.querySelector('#screen').getAttribute('src') || '',
    frame: !document.querySelector('#screen').hidden,
    touch: !!document.querySelector('#touchScreen') && !document.querySelector('#touchScreen').hidden,
    rfb: !!(window.__vnc && window.__vnc.made),
    height: document.querySelector('#screen').getBoundingClientRect().height,
  }));
  if (!d.frame || !d.src.startsWith('novnc/vnc.html?') || !d.src.includes('resize=scale')) {
    say(`the desktop does not get the stock noVNC page (src ${d.src})`);
  }
  if (!d.src.includes('path=ingress%2Fabc%2Fwebsockify')) say(`the desktop frame's websocket path is wrong (${d.src})`);
  if (d.touch) say('the desktop shows the touch controls');
  if (d.rfb) say('the desktop made a second noVNC connection on the page');
  if (d.height < 600) say(`the desktop screen is ${d.height}px tall`);
  await shot(page, 'studio-1200');
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('OK: Studio tab — pinch zoom, pan, tap, right click, scroll, drag and keyboard at 390 (touch); the stock noVNC page at 1200.');
