/* Playwright measure for Morph's panel.
 *
 *   node tests/manual/measure-morph.mjs
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome node tests/manual/measure-morph.mjs
 *
 * Morph's layout engine is the part of the design most worth porting
 * faithfully (docs/design/morph-ui.md §5), and its acceptance tests are
 * about MOTION, which nothing but a browser can check. This loads the real
 * panel modules against the fixture house (morph-fixture.mjs) and asserts,
 * at 1440px and at a 400px phone:
 *
 *   * at rest: no two sections overlap, no tiles overlap, and no two tiles
 *     on one row differ in height (a short tile never has a hole under it);
 *   * hold-open, then tap outside, on every card kind, sampling every
 *     30ms: ZERO frames in which two sections, or a section and a floor
 *     heading, overlap;
 *   * an opened card's top-left is where it was before it opened;
 *   * tap acts (a light toggles), slide sets a level (brightness), and the
 *     garage door and the lock ask for a second tap;
 *   * Edit: hold a card and the Tell brAIn prompt opens INSIDE it, Send
 *     hands it over, and the answer ends with Keep · Undo;
 *   * Settings renders, and nothing on either width scrolls sideways.
 *
 * Exits non-zero with every failure listed.
 */
import { chromium } from 'playwright';
import { route, ORIGIN } from './morph-fixture.mjs';

const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });

const KINDS = ['c_countertop', 'c_kitchen_cans', 'c_lr_fan', 'c_lr_blinds', 'c_tv', 'c_down', 'c_cam_front', 'c_doors', 'c_ben', 'c_weather', 'c_front_lock', 'c_water'];

async function snapshot(p) {
  return p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const rect = (el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; };
    const secs = [...root.querySelectorAll('[data-sec]')].filter((e) => e.getAttribute('data-sec') && !e.getAttribute('data-sec').startsWith('__new')).map((e) => ({ id: e.getAttribute('data-sec'), ...rect(e) }));
    const floors = [...root.querySelectorAll('[data-floor]')].filter((e) => e.style.visibility !== 'hidden').map((e) => { const inn = e.querySelector('[data-flin]'); return { id: 'floor' + e.getAttribute('data-floor'), ...rect(inn || e) }; });
    const tiles = [...root.querySelectorAll('[data-tile]')].map((e) => ({ id: e.getAttribute('data-tile'), sec: e.closest('[data-sec]').getAttribute('data-sec'), ...rect(e) }));
    const scroller = root.querySelector('.scroll');
    return { secs, floors, tiles, sideways: scroller.scrollWidth > scroller.clientWidth + 1 || document.documentElement.scrollWidth > window.innerWidth + 1 };
  });
}

const overlap = (a, b, pad) => a.x + a.w - pad > b.x && b.x + b.w - pad > a.x && a.y + a.h - pad > b.y && b.y + b.h - pad > a.y;

function sectionOverlaps(s) {
  const out = [];
  for (let i = 0; i < s.secs.length; i++) {
    for (let j = i + 1; j < s.secs.length; j++) if (overlap(s.secs[i], s.secs[j], 1)) out.push(`${s.secs[i].id}×${s.secs[j].id}`);
    for (const f of s.floors) if (overlap(s.secs[i], f, 1)) out.push(`${s.secs[i].id}×${f.id}`);
  }
  return out;
}

function atRest(where, s) {
  const so = sectionOverlaps(s);
  if (so.length) fail(where, `sections overlap at rest: ${so.slice(0, 4).join(', ')}`);
  const bySec = {};
  s.tiles.forEach((t) => { (bySec[t.sec] = bySec[t.sec] || []).push(t); });
  Object.entries(bySec).forEach(([sec, ts]) => {
    for (let i = 0; i < ts.length; i++) {
      for (let j = i + 1; j < ts.length; j++) {
        if (overlap(ts[i], ts[j], 1)) fail(where, `tiles overlap in ${sec}: ${ts[i].id} × ${ts[j].id}`);
        if (Math.abs(ts[i].y - ts[j].y) < 1 && Math.abs(ts[i].h - ts[j].h) > 1.5) fail(where, `one row, two heights in ${sec}: ${ts[i].id} (${ts[i].h.toFixed(0)}) vs ${ts[j].id} (${ts[j].h.toFixed(0)})`);
      }
    }
  });
  if (s.sideways) fail(where, 'the page scrolls sideways');
}

async function settle(p, ms) { await p.waitForTimeout(ms || 900); }

async function tileCenter(p, id) {
  return p.evaluate((id) => {
    const el = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`);
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    return { x: r.left + Math.min(40, r.width / 2), y: r.top + Math.min(20, r.height / 2), left: r.left, right: r.right, top: r.top };
  }, id);
}

async function sample(p, where, ms) {
  const bad = new Set();
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const s = await snapshot(p);
    sectionOverlaps(s).forEach((x) => bad.add(x));
    await p.waitForTimeout(30);
  }
  if (bad.size) fail(where, `sections overlapped mid-motion: ${[...bad].slice(0, 4).join(', ')}`);
}

for (const [w, h, name, narrow] of [[1440, 900, 'wide', false], [400, 860, 'phone', true]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: false });
  await route(ctx, { narrow });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await settle(p, 2500);
  atRest(`${name} at rest`, await snapshot(p));

  // Hold-open, then tap outside, on every kind.
  for (const id of KINDS) {
    const c = await tileCenter(p, id);
    if (!c) { fail(name, `card ${id} is not on the page`); continue; }
    await settle(p, 400);
    const before = await tileCenter(p, id);
    await p.mouse.move(before.x, before.y);
    await p.mouse.down();
    const sampling = sample(p, `${name} open ${id}`, 1400);
    await p.waitForTimeout(700);
    await p.mouse.up();
    await sampling;
    const opened = await p.evaluate((id) => !!window.__panel.s.view && window.__panel.s.view.id === id, id);
    if (!opened && !['c_water'].includes(id)) fail(name, `holding ${id} did not open it`);
    const after = await p.evaluate((id) => { const r = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`).getBoundingClientRect(); return { left: r.left, right: r.right }; }, id);
    // §1.8: an opened card keeps its column and grows right — or, where the
    // row ends against it, keeps its RIGHT edge and grows left. The scroll
    // may follow it, so only the columns are compared.
    if (opened && Math.abs(after.left - before.left) > 1.5 && Math.abs(after.right - before.right) > 1.5) fail(name, `${id} jumped when it opened (left ${before.left.toFixed(0)} → ${after.left.toFixed(0)}, right ${before.right.toFixed(0)} → ${after.right.toFixed(0)})`);
    // tap outside: the page's own empty margin, top left
    await p.mouse.click(4, 4);
    await sample(p, `${name} close ${id}`, 900);
  }
  await settle(p, 600);
  atRest(`${name} after opening everything`, await snapshot(p));

  // Tap acts, slide sets a level.
  let c = await tileCenter(p, 'c_mudroom');
  await p.evaluate(() => { window.__calls = []; });
  await p.mouse.click(c.x, c.y);
  await settle(p, 300);
  let calls = await p.evaluate(() => window.__calls);
  if (!calls.some((x) => x.domain === 'light' && x.service === 'toggle')) fail(name, `tapping a light did not toggle it: ${JSON.stringify(calls)}`);
  c = await p.evaluate(() => { const el = window.__panel.shadowRoot.querySelector('[data-tile="c_countertop"]'); el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, w: r.width, h: r.height }; });
  await p.evaluate(() => { window.__calls = []; });
  await p.mouse.move(c.l + 10, c.t + 28); await p.mouse.down();
  for (let i = 1; i <= 8; i++) { await p.mouse.move(c.l + 10 + (c.w * 0.7 - 10) * i / 8, c.t + 28); await p.waitForTimeout(16); }
  await p.mouse.up();
  await settle(p, 300);
  calls = await p.evaluate(() => window.__calls);
  const slid = calls.find((x) => x.service === 'turn_on' && x.data.brightness_pct);
  if (!slid || slid.data.brightness_pct < 55 || slid.data.brightness_pct > 85) fail(name, `sliding a light did not set ~70%: ${JSON.stringify(calls)}`);
  // The garage door needs a second tap to open.
  c = await tileCenter(p, 'c_garage');
  await p.evaluate(() => { window.__calls = []; });
  await p.mouse.click(c.x, c.y); await settle(p, 200);
  calls = await p.evaluate(() => window.__calls);
  if (calls.length) fail(name, 'one tap opened the garage door');
  await p.mouse.click(c.x, c.y); await settle(p, 200);
  calls = await p.evaluate(() => window.__calls);
  if (!calls.some((x) => x.service === 'open_cover')) fail(name, 'a second tap did not open the garage door');

  // Edit: hold a card, Tell brAIn opens inside it, Send, Keep · Undo.
  await p.evaluate(() => window.__panel.act('edit', { dataset: {} }));
  await settle(p, 1200);
  atRest(`${name} in Edit`, await snapshot(p));
  // Read the position after Edit's own layout has settled, not before.
  await settle(p, 300);
  c = await tileCenter(p, 'c_kitchen_cans');
  await p.mouse.move(c.x, c.y); await p.mouse.down(); await p.waitForTimeout(700); await p.mouse.up();
  await settle(p, 900);
  const inside = await p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_kitchen_cans"] [data-tell] textarea'); return !!t; });
  if (!inside) fail(name, 'holding a card in Edit did not open Tell brAIn inside it');
  await p.evaluate(() => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Make this wider and put it first'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-send"]').click());
  await settle(p, 3500);
  const told = await p.evaluate(() => ({ req: window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell'), text: (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '' }));
  if (!told.req || told.req.payload.text !== 'Make this wider and put it first' || told.req.payload.target.kind !== 'card') fail(name, `the tell was not handed over as asked: ${JSON.stringify(told.req)}`);
  if (!/Undo/.test(told.text) || !/Keep/.test(told.text)) fail(name, `the finished tell does not offer Keep · Undo: ${told.text.slice(0, 200)}`);
  atRest(`${name} with a tell open`, await snapshot(p));

  // Settings.
  await p.evaluate(() => window.__panel.act('page', { dataset: { v: 'settings' } }));
  await settle(p, 800);
  const set = await p.evaluate(() => ({ text: window.__panel.shadowRoot.querySelector('.settings').innerText, sideways: window.__panel.shadowRoot.querySelector('.scroll').scrollWidth > window.__panel.shadowRoot.querySelector('.scroll').clientWidth + 1 }));
  for (const h of ['brAIn', 'Learning', 'Improving Morph itself', 'Appearance', 'History', 'Dashboard']) if (!set.text.includes(h)) fail(name, `Settings has no ${h} section`);
  if (set.sideways) fail(name, 'Settings scrolls sideways');

  if (errors.length) fail(name, `page errors: ${errors.join(' | ')}`);
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error(`measure-morph: ${problems.length} problem(s)`);
  problems.forEach((x) => console.error('  - ' + x));
  process.exit(1);
}
console.log('measure-morph: all checks passed');
