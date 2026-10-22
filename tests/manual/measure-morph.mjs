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
 *   * Edit: hold a card and a PICTURE of it is taken and sent with the Tell
 *     (not blank, the card's size), brAIn's own steps show while it works,
 *     the answer shows before and after, Tell it more photographs it again
 *     and keeps the first turn, and a request that needs Morph's code is
 *     ASKED about ("send this as an issue?") rather than filed;
 *   * Edit: hold a card and the Tell brAIn prompt opens INSIDE it, Send
 *     hands it over, and the answer ends with Keep · Undo;
 *   * Settings renders, and nothing on either width scrolls sideways.
 *
 *   * Coming up is one short strip: dragging it moves the timeline behind
 *     a fixed reading point and the readout says what is at the point, a
 *     tap on a dot goes there, a swipe settles on an event, Now comes back,
 *     and the arrow keys step from event to event;
 *
 * Exits non-zero with every failure listed.
 */
import { chromium } from 'playwright';
import { route, ORIGIN, VERSION } from './morph-fixture.mjs';

const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });

// MORPH_ONLY=wide|phone runs one width. The fixture keeps its house in
// module state, so two widths cannot share one process concurrently; CI runs
// the two as separate processes side by side instead.
const ONLY = process.env.MORPH_ONLY || '';
const W = (rows) => rows.filter((r) => !ONLY || r[2] === ONLY);

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

// "At rest" is when nothing is moving any more, not a fixed time: entering
// Edit springs every section, and a slow machine is still springing at
// 1.2s. Wait (up to 4s more) for two snapshots 150ms apart that agree.
async function still(p) {
  let prev = await snapshot(p);
  for (let i = 0; i < 26; i++) {
    await p.waitForTimeout(150);
    const cur = await snapshot(p);
    if (JSON.stringify(cur.secs) === JSON.stringify(prev.secs)) return cur;
    prev = cur;
  }
  return prev;
}

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

// The prototype's look (docs/design/morph-ui.html), where it was lost in
// translation once: status lines in quiet text, a light group twice a strip,
// notes after a room's tiles, Coming up across the whole width, the Ask
// suggestions only while asking, and the overlay chart with its target band,
// its runs, a label column and an axis.
async function design(p, name, narrow) {
  const d = await p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const q = (s) => root.querySelector(s);
    const r = (el) => el && el.getBoundingClientRect();
    const muted = getComputedStyle(root.host).getPropertyValue('--muted').trim();
    const probe = document.createElement('span'); probe.style.color = 'var(--muted)'; q('.scroll').appendChild(probe);
    const mutedRgb = getComputedStyle(probe).color; probe.remove();
    const val = q('[data-tile="c_countertop"] .nv span');
    const grp = r(q('[data-tile="c_kitchen_cans"]')); const one = r(q('[data-tile="c_countertop"]'));
    const notesLate = [...root.querySelectorAll('[data-sec]')].every((sec) => {
      const tiles = [...sec.querySelectorAll('[data-tile]')];
      const notes = tiles.filter((t) => t.getAttribute('data-tile').startsWith('n:')).map(r);
      const rest = tiles.filter((t) => !t.getAttribute('data-tile').startsWith('n:')).map(r);
      return notes.every((n) => rest.every((x) => n.top >= x.bottom - 1));
    });
    const upc = r(q('.cu .cu-vp')), upcBox = r(q('[data-region="upcoming"]'));
    const sugs = q('.sugs');
    const ov = q('[data-tile="c_temps"]') || [...root.querySelectorAll('.ov')][0];
    return {
      muted, valColor: val && getComputedStyle(val).color, mutedRgb,
      valText: val && val.textContent,
      grpText: (q('[data-tile="c_kitchen_cans"] .nv span') || {}).textContent,
      grpW: grp && grp.width, oneW: one && one.width,
      notesLate,
      upcW: upc && upc.width, upcBoxW: upcBox && upcBox.width,
      sugsShown: !!(sugs && sugs.offsetParent),
      ovLabels: ov ? ov.querySelectorAll('.ovlab').length : 0,
      ovBand: ov ? ov.querySelectorAll('polygon').length : 0,
      ovRuns: ov ? ov.querySelectorAll('.ovruns span').length : 0,
      ovAxis: ov ? [...ov.querySelectorAll('.ovaxis span')].map((x) => x.textContent) : [],
    };
  });
  const where = `${name} design`;
  if (d.valColor !== d.mutedRgb) fail(where, `a light's status line is not quiet text (${d.valColor})`);
  if (!/^\d+% · (Warm|Soft|Daylight|Color)$/.test(d.valText || '')) fail(where, `a light's status line does not say its level and colour: "${d.valText}"`);
  if (!/^(All \d+|\d+ of \d+) · (\d+%|mixed)$|^All \d+ off$/.test(d.grpText || '')) fail(where, `a light group's status line is not the design's: "${d.grpText}"`);
  if (!narrow && !(d.grpW > d.oneW * 1.8)) fail(where, `a light group is not twice a strip (${d.grpW} vs ${d.oneW})`);
  if (!d.notesLate) fail(where, 'a note sits above its room\'s tiles');
  if (!narrow && !(d.upcW >= d.upcBoxW - 20)) fail(where, `Coming up does not use the whole width (${d.upcW} of ${d.upcBoxW})`);
  if (d.sugsShown) fail(where, 'the Ask suggestions show before anybody asks');
  if (d.ovLabels < 2) fail(where, 'the overlay chart has no label column');
  if (!d.ovBand) fail(where, 'the overlay chart draws no target band');
  if (!d.ovRuns) fail(where, 'the overlay chart draws no runs');
  if (!d.ovAxis.includes('Now')) fail(where, 'the overlay chart has no time axis');
}

// Coming up: a reading point that stays still and a timeline you drag
// behind it. Small vertically, and everything it says comes from moving it.
async function comingUp(p, name, narrow) {
  const where = `${name} coming up`;
  const read = () => p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const q = (s) => root.querySelector(s);
    const vp = q('[data-upc-vp]'); const tr = q('[data-cu-track]'); const lens = q('[data-cu-lens]');
    if (!vp) return null;
    vp.scrollIntoView({ block: 'center' });
    const r = vp.getBoundingClientRect(); const lr = lens.getBoundingClientRect();
    const inner = (sel) => { const e = q(sel); if (!e) return null; const rs = [...e.querySelectorAll('b, .cu-name, .cu-l2, .cu-when > span')].map((x) => x.getBoundingClientRect()).filter((x) => x.width); return rs.length ? { l: Math.min(...rs.map((x) => x.left)), r: Math.max(...rs.map((x) => x.right)) } : null; };
    const dots = [...root.querySelectorAll('[data-cu-dot]')].map((d) => { const b = d.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; }).filter((d) => d.x > r.left + 30 && d.x < r.right - 60);
    return {
      h: r.height, l: r.left, w: r.width, y: r.top + r.height / 2, lensX: lr.left + lr.width / 2, lensY: lr.top + lr.height / 2,
      tf: tr.style.transform, hit: lens.classList.contains('hit'),
      name: (q('[data-cu-what] .cu-name') || {}).textContent || '', when: (q('[data-cu-when]') || {}).textContent || '',
      at: window.__panel.s.upcAt, back: !q('.cu-back').hidden, dots,
      whenBox: inner('[data-cu-when]'), whatBox: inner('[data-cu-what]'), vpBox: { l: r.left, r: r.right },
      frozen: window.__panel.upcFrozen(),
    };
  });
  let s = await read();
  if (!s) { fail(where, 'there is no Coming up strip'); return; }
  if (s.h > (narrow ? 92 : 80)) fail(where, `the strip is ${s.h.toFixed(0)}px tall; it should be one short strip`);
  if (!s.name.trim() || !s.when.trim()) fail(where, `the readout says nothing at rest ("${s.when}" / "${s.name}")`);
  if (s.whenBox && s.whenBox.l < s.vpBox.l - 1) fail(where, 'the time beside the reading point runs off the left edge');
  if (s.whatBox && s.whatBox.r > s.vpBox.r + 1) fail(where, 'the name beside the reading point runs off the right edge');
  if (s.whenBox && s.whatBox && s.whenBox.r > s.whatBox.l) fail(where, 'the time and the name overlap');
  if (s.at != null) fail(where, 'the strip does not open on now');

  // Drag the timeline left, in steps: it moves under the finger, the
  // readout follows, and nothing rebuilds it mid-drag.
  const startX = s.l + s.w * 0.75;
  await p.mouse.move(startX, s.y);
  await p.mouse.down();
  const seen = new Set([s.name]); const tfs = new Set([s.tf]);
  for (let i = 1; i <= 16; i++) {
    await p.mouse.move(startX - i * 22, s.y);
    await p.waitForTimeout(25);
    const m = await read(); seen.add(m.name); tfs.add(m.tf);
    if (!m.frozen) fail(where, 'the strip is not held still while it is being dragged');
  }
  await p.waitForTimeout(150);
  await p.mouse.up();
  if (tfs.size < 8) fail(where, `the timeline did not follow the drag (${tfs.size} positions)`);
  if (seen.size < 2) fail(where, 'the readout did not change while the timeline moved under it');
  await p.waitForTimeout(900);
  s = await read();
  if (s.at == null) fail(where, 'after a drag the reading point is back at now');
  if (!s.back) fail(where, 'away from now, there is no way back to Now');

  // Now comes back.
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('.cu-back').click());
  await p.waitForTimeout(900);
  s = await read();
  if (s.at != null || s.back) fail(where, 'Now did not bring the reading point back');

  // A tap on a dot goes there, and the point says it is on something.
  const dot = s.dots.find((d) => Math.abs(d.x - s.lensX) > 40);
  if (!dot) fail(where, 'no dot on screen to tap');
  else {
    await p.mouse.click(dot.x, s.lensY);
    await p.waitForTimeout(900);
    const t = await read();
    if (!t.hit) fail(where, `tapping a dot did not put the reading point on it ("${t.name}")`);
    if (!t.dots.some((d) => Math.abs(d.x - t.lensX) < 4)) fail(where, 'the tapped dot did not land under the reading point');
  }

  // A fast swipe coasts and settles on an event, or says there is nothing.
  s = await read();
  await p.mouse.move(s.l + s.w * 0.8, s.y);
  await p.mouse.down();
  for (let i = 1; i <= 5; i++) { await p.mouse.move(s.l + s.w * 0.8 - i * 30, s.y); await p.waitForTimeout(12); }
  await p.mouse.up();
  await p.waitForTimeout(1000);
  const sw = await read();
  if (!sw.hit && sw.name !== 'Nothing here') fail(where, `a swipe did not settle anywhere sensible ("${sw.name}")`);

  // The arrow keys step from one event to the next, keeping focus.
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-upc-vp]').focus());
  await p.keyboard.press('Home');
  await p.waitForTimeout(900);
  await p.keyboard.press('ArrowRight');
  await p.waitForTimeout(900);
  const k1 = await read();
  if (!k1.hit) fail(where, `ArrowRight did not land on the next event ("${k1.name}")`);
  const focused = await p.evaluate(() => { const a = window.__panel.shadowRoot.activeElement; return !!(a && a.hasAttribute('data-upc-vp')); });
  if (!focused) fail(where, 'the strip lost keyboard focus after a step');
  await p.keyboard.press('Home');
  await p.waitForTimeout(900);
  if ((await read()).at != null) fail(where, 'Home did not go back to now');
}

// The page brAIn and Morph share (docs/design/morph-vision.md): a verdict
// at the top, brAIn's cases drawn in the room they are about with a reply
// line, To Do as a section, and no second door to a Tell beside Ask.
async function vision(p, name) {
  const where = `${name} vision`;
  const v = await p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const reply = root.querySelector('.replyin[data-case="h:1791000100"]');
    const rr = reply && reply.getBoundingClientRect();
    const freezer = root.querySelector('[data-case-card="f:1791000000"]');
    return {
      story: (root.querySelector('.story') || {}).textContent || '',
      cases: root.querySelectorAll('.case').length,
      reply: rr ? { w: rr.width, h: rr.height, fs: parseFloat(getComputedStyle(reply).fontSize) } : null,
      freezerSec: freezer ? (freezer.closest('[data-sec]') || {}).getAttribute && freezer.closest('[data-sec]').getAttribute('data-sec') : null,
      todo: root.querySelectorAll('.todorow').length,
      marks: root.querySelectorAll('.secmark, .hovermark, [data-act="tell-card"], [data-act="tell-sec"]').length,
      yes: [...root.querySelectorAll('.case button')].map((b) => b.textContent.trim()).filter((t) => /^(Yes|No|Wrong)$/.test(t)),
    };
  });
  if (!v.story.trim()) fail(where, 'there is no verdict at the top of the page');
  if (v.cases < 2) fail(where, `brAIn's cases are not on the page (${v.cases})`);
  if (!v.reply) fail(where, 'a case has no reply line');
  else {
    if (v.reply.h < 36) fail(where, `the reply line is ${v.reply.h}px tall, under the touch target`);
    if (v.reply.fs < 16) fail(where, `the reply line's text is ${v.reply.fs}px, under the 16px floor`);
  }
  if (!v.freezerSec || v.freezerSec === '__cases') fail(where, `the freezer case is not drawn in the room it is about (${v.freezerSec})`);
  if (v.todo < 1) fail(where, 'To Do is not on the page');
  if (v.marks) fail(where, `${v.marks} Tell marks are on the page; Ask is the one door`);
  if (v.yes.length) fail(where, `a case carries ${v.yes.join(', ')}: a reply is read, not pressed`);
  // A reply is a turn, answered in the card.
  await p.evaluate(() => { const i = window.__panel.shadowRoot.querySelector('.replyin[data-case="h:1791000100"]'); i.focus(); i.value = 'yes, a plug timer'; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, composed: true })); });
  await settle(p, 1400);
  const t = await p.evaluate(() => ({ req: (window.__caseReqs || []).find((x) => x.action === 'reply'), turns: [...window.__panel.shadowRoot.querySelectorAll('[data-case-card="h:1791000100"] .turnline')].map((e) => e.textContent) }));
  if (!t.req || t.req.text !== 'yes, a plug timer') fail(where, `the reply was not sent as typed: ${JSON.stringify(t.req)}`);
  if (!t.turns.includes('yes, a plug timer') || t.turns.length < 3) fail(where, `the reply did not become a turn in the card: ${JSON.stringify(t.turns)}`);
  // A reply that settles the case AND asks for a page change: the case
  // leaves with brAIn's last word, and Morph runs the Tell brAIn cannot.
  await p.evaluate(() => { const i = window.__panel.shadowRoot.querySelector('.replyin[data-case="f:1791000000"]'); i.focus(); i.value = 'it is fine, and put it on the kitchen card'; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, composed: true })); });
  await settle(p, 1600);
  const told = await p.evaluate(() => ({ tell: window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell'), gone: !window.__panel.shadowRoot.querySelector('[data-case-card="f:1791000000"]'), toast: (window.__panel.shadowRoot.querySelector('.bar') || {}).innerText || '' }));
  if (!told.gone) fail(where, 'a case a reply ended is still on the page');
  if (!told.tell || !/kitchen/i.test(told.tell.payload.text || '')) fail(where, `the page change a reply asked for was not handed to a Tell: ${JSON.stringify(told.tell && told.tell.payload)}`);
  if (!/asked Morph to add it/.test(told.toast)) fail(where, `brAIn's last word on the ended case was not said: "${told.toast}"`);
  await p.evaluate(() => { if (window.__panel.s.tell) window.__panel.closeTell(); });
  await settle(p, 600);
  atRest(`${name} after a reply`, await snapshot(p));
}

// At night with the alarm armed, the page is one line about what is wrong
// and the thing itself, lifted (§11): an unlocked front door, nothing else.
async function night(p, name) {
  const where = `${name} night`;
  await p.evaluate(() => {
    const S = window.__panel.hass.states;
    const n = { ...S };
    n['alarm_control_panel.house'] = { ...S['alarm_control_panel.house'], state: 'armed_night' };
    n['binary_sensor.garage_freezer'] = { ...S['binary_sensor.garage_freezer'], state: 'off' };
    n['lock.front_door'] = { ...S['lock.front_door'], state: 'unlocked', last_changed: new Date(Date.now() - 4 * 3600000).toISOString() };
    window.__panel.hass = { ...window.__panel.hass, states: n };
  });
  await settle(p, 2500);
  const n = await p.evaluate(() => {
    const r = window.__panel.shadowRoot;
    const P = window.__panel;
    return { dbg: JSON.stringify({ st: P.salState && P.salState.period, ap: P.salApplied && P.salApplied.period, view: !!P.s.view, tell: !!P.s.tell, ask: !!P.s.ask, page: P.s.page, alarm: P.hass.states['alarm_control_panel.house'].state, ptr: !!(P.ptr || P.mptr || P.upcD || P.drag), edit: P.s.edit }), cls: r.querySelector('[data-morph-root]').className, story: (r.querySelector('.story') || {}).textContent || '', now: [...r.querySelectorAll('.nowband [data-tile]')].map((e) => e.getAttribute('data-tile')) };
  });
  if (!/form-night/.test(n.cls)) fail(where, `the armed-night house is not in the night form (${n.cls}) ${n.dbg}`);
  if (!/Front Door is unlocked/.test(n.story)) fail(where, `the night verdict does not name the unlocked door: "${n.story}"`);
  if (n.now.length !== 1 || n.now[0] !== 'c_front_lock') fail(where, `the night page does not hold exactly the unlocked door: ${n.now.join(', ')}`);
  atRest(`${name} at night`, await snapshot(p));
}

for (const [w, h, name, narrow] of W([[1440, 900, 'wide', false], [400, 860, 'phone', true]])) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: false });
  await route(ctx, { narrow });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await settle(p, 2500);
  atRest(`${name} at rest`, await snapshot(p));
  await vision(p, name);
  // A quiet room folds to one line (§6); tapping its name opens it in place.
  {
    const f = await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('section.folded .roomname'); return b ? b.closest('[data-sec]').getAttribute('data-sec') : null; });
    if (!f) fail(name, 'no quiet room is folded');
    else {
      await p.evaluate((id) => window.__panel.shadowRoot.querySelector(`[data-sec="${id}"] .roomname`).click(), f);
      await settle(p, 1400);
      const open = await p.evaluate((id) => { const el = window.__panel.shadowRoot.querySelector(`[data-sec="${id}"]`); return !!el && !el.classList.contains('folded') && el.querySelectorAll('[data-tile]').length > 0; }, f);
      if (!open) fail(name, `tapping a folded room's name (${f}) did not open it`);
      atRest(`${name} with a folded room opened`, await snapshot(p));
    }
    // The tour below opens every kind of card, so every room stays open.
    await p.evaluate(() => { window.__panel.data.state.settings = { ...(window.__panel.data.state.settings || {}), fold_rooms: false }; window.__panel._forceApply = true; window.__panel.engine.invalidate(); window.__panel.schedule(); });
    await settle(p, 1800);
  }
  await design(p, name, narrow);
  await comingUp(p, name, narrow);

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
  // The tap is a use, tied to its card and section — the learning loop's
  // only evidence. Then the page is taken out and put back the way Home
  // Assistant does with a hidden panel (the SAME element: boot() does not run
  // again), a send fails the way a suspended connection fails it, and the use
  // must still arrive: logged, kept, and sent on the next chance.
  const queued = await p.evaluate(() => window.__panel.usage.slice());
  if (!queued.some((u) => u.kind === 'toggle' && u.card === 'c_mudroom' && u.section)) fail(name, `tapping a light logged no use for its card: ${JSON.stringify(queued)}`);
  const usageSent = () => p.evaluate(() => window.__ws.filter((m) => m.type === 'morph/usage').flatMap((m) => m.events));
  await p.evaluate(() => { const el = window.__panel; const host = el.parentNode; host.removeChild(el); host.appendChild(el); });
  await settle(p, 300);
  if (!(await usageSent()).some((u) => u.card === 'c_mudroom')) fail(name, 'a use was not sent when the panel was taken out of the page');
  c = await tileCenter(p, 'c_mudroom');
  await p.mouse.click(c.x, c.y);
  await settle(p, 200);
  const before = (await usageSent()).length;
  await p.evaluate(() => { window.__usageFail = 1; window.dispatchEvent(new Event('pagehide')); });
  await settle(p, 200);
  if ((await usageSent()).length !== before) fail(name, 'the failed usage send was recorded as sent');
  if (!(await p.evaluate(() => window.__panel.usage.some((u) => u.card === 'c_mudroom')))) fail(name, 'a usage send that failed dropped its events instead of keeping them');
  await p.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await settle(p, 200);
  if ((await usageSent()).length <= before) fail(name, 'after the panel was put back, uses were not sent again (the flush stopped for good)');
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

  // A dashboard change typed into the Ask bar outside Edit is a Tell, not a
  // question for the house's assistant (which cannot touch dashboard.yaml).
  {
    await p.evaluate(() => { window.__ws.length = 0; const i = window.__panel.shadowRoot.querySelector('input[data-keep="ask"]'); i.value = 'Remove the Coming up timeline card'; window.__panel.act('ask', i); });
    await settle(p, 900);
    const sent = await p.evaluate(() => ({ tell: window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell'), conv: window.__ws.some((m) => m.type === 'morph/request' && m.kind === 'converse') }));
    if (!sent.tell || sent.tell.payload.target.kind !== 'dashboard') fail(name, 'a dashboard change in the Ask bar was not handed to brAIn as a Tell');
    if (sent.conv) fail(name, 'a dashboard change in the Ask bar became a conversation');
    await settle(p, 2200);
    await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('[data-act="tell-keep"]'); if (b) b.click(); else window.__panel.closeTell(); });
    await settle(p, 600);
    await p.evaluate(() => { window.__ws.length = 0; const i = window.__panel.shadowRoot.querySelector('input[data-keep="ask"]'); i.value = 'Why is it warm upstairs?'; window.__panel.act('ask', i); });
    await settle(p, 900);
    await settle(p, 1500);
    const q = await p.evaluate(() => ({ asked: window.__ws.some((m) => m.type === 'morph/ask'), conv: window.__ws.some((m) => m.type === 'morph/request' && m.kind === 'converse'), tell: window.__ws.some((m) => m.kind === 'tell'), offer: !!window.__panel.shadowRoot.querySelector('[data-act="ask-tell"]') }));
    if (!q.asked || !q.conv || q.tell) fail(name, 'a question was not handed to brAIn as a conversation');
    if (!q.offer) fail(name, 'an answer does not offer "Change the dashboard instead"');
    await p.evaluate(() => { window.__ws.length = 0; window.__panel.s.ask = null; window.__panel.schedule(); });
    await settle(p, 400);
  }

  // Edit: hold a card, Tell brAIn opens inside it, Send, Keep · Undo.
  await p.evaluate(() => window.__panel.act('edit', { dataset: {} }));
  await settle(p, 1200);
  atRest(`${name} in Edit`, await still(p));
  // Read the position after Edit's own layout has settled, not before.
  await settle(p, 300);
  c = await tileCenter(p, 'c_kitchen_cans');
  await p.mouse.move(c.x, c.y); await p.mouse.down(); await p.waitForTimeout(700); await p.mouse.up();
  await settle(p, 900);
  const inside = await p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_kitchen_cans"] [data-tell] textarea'); return !!t; });
  if (!inside) fail(name, 'holding a card in Edit did not open Tell brAIn inside it');
  await p.evaluate(() => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Make this wider and put it first'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-send"]').click());
  // Long enough for the answer AND the after-picture, which waits for the
  // change to draw before it is taken.
  await settle(p, 5500);
  const told = await p.evaluate(() => ({ req: window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell'), text: (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '' }));
  if (!told.req || told.req.payload.text !== 'Make this wider and put it first' || told.req.payload.target.kind !== 'card') fail(name, `the tell was not handed over as asked: ${JSON.stringify(told.req)}`);
  if (!/Undo/.test(told.text) || !/Keep/.test(told.text)) fail(name, `the finished tell does not offer Keep · Undo: ${told.text.slice(0, 200)}`);
  // The picture: taken when the card was held, sent with the request, and
  // of something — a blank or one-colour PNG is a capture that drew nothing.
  const shot = await p.evaluate(async () => {
    const sent = window.__ws.filter((m) => m.type === 'morph/shot');
    const req = window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell');
    if (!sent.length) return { n: 0 };
    const img = new Image(); img.src = sent[0].png; await img.decode();
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data; const seen = new Set();
    for (let i = 0; i < d.length; i += 4 * 97) seen.add(`${d[i] >> 4},${d[i + 1] >> 4},${d[i + 2] >> 4}`);
    return { n: sent.length, w: img.width, h: img.height, colours: seen.size, id: req && req.payload.shot, view: req && req.payload.view };
  });
  if (!shot.n) fail(name, 'holding a card took no picture of it for brAIn');
  else {
    if (shot.w < 60 || shot.h < 30) fail(name, `the picture is ${shot.w}×${shot.h}, not the card`);
    if (shot.colours < 3) fail(name, `the picture is blank (${shot.colours} colours)`);
    if (!shot.id) fail(name, 'the tell was sent without the picture it took');
    if (!shot.view || !/Cans/.test(shot.view.text || '')) fail(name, `the card's text did not ride with the picture: ${JSON.stringify(shot.view)}`);
  }
  const box = await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('[data-tell]'); return { text: b ? b.innerText : '', figs: b ? b.querySelectorAll('figure.shot img').length : 0 }; });
  if (!/Looking at the screenshot/.test(box.text)) fail(name, 'brAIn\'s own steps are not shown while it works');
  if (!/brAIn saw:/.test(box.text)) fail(name, 'the finished tell does not say what brAIn saw');
  if (!/Dashboard/.test(box.text) || !/Cans/.test(box.text)) fail(name, 'the finished tell does not say what is on the dashboard now (read back from the file)');
  if (!/Home Assistant\s*Not changed/.test(box.text) || !/GitHub\s*Nothing sent/.test(box.text)) fail(name, `the finished tell does not say Home Assistant and GitHub were left alone (${box.text.slice(0, 300)})`);
  if (box.figs < 2) fail(name, `the finished tell shows ${box.figs} picture(s), not before and after`);
  atRest(`${name} with a tell open`, await snapshot(p));
  // Tell it more: a second turn, photographed again, with the first above it.
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-more"]').click());
  await settle(p, 1200);
  const more = await p.evaluate(() => ({ shots: window.__ws.filter((m) => m.type === 'morph/shot').length, turn: !!window.__panel.shadowRoot.querySelector('[data-tell] .turn') }));
  if (more.shots < 2) fail(name, 'Tell it more did not take a new picture of how it looks now');
  if (!more.turn) fail(name, 'Tell it more lost the earlier turn of the conversation');
  // A request Morph's code cannot meet is asked about, never filed unasked.
  await p.evaluate(() => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Morph cannot do this: show both colours'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-send"]').click());
  await settle(p, 3500);
  const ask = await p.evaluate(() => ({ text: (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '', btn: !!window.__panel.shadowRoot.querySelector('[data-act="tell-issue"][data-v="send"]'), filed: window.__ws.some((m) => m.kind === 'tell_issue') }));
  if (!/send this as an issue/i.test(ask.text) || !ask.btn) fail(name, 'a request that needs Morph\'s code changed did not ask to send it as an issue');
  if (ask.filed) fail(name, 'an issue was filed before anybody said yes');
  if (ask.btn) {
    await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-issue"][data-v="send"]').click());
    await settle(p, 400);
    const sent = await p.evaluate(() => window.__ws.find((m) => m.kind === 'tell_issue'));
    if (!sent || sent.payload.verb !== 'send') fail(name, 'Send as issue did not send the answer');
  }
  const wide = await p.evaluate(() => { const vw = window.innerWidth; return [...window.__panel.shadowRoot.querySelectorAll('[data-tell] *, .bar > *')].filter((e) => e.getBoundingClientRect().right > vw + 1).slice(0, 5).map((e) => `${e.tagName}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`); });
  if (wide.length) fail(name, `the tell box or the bar (with its toast) is wider than the screen: ${wide.join(', ')}`);
  atRest(`${name} with a two-turn tell open`, await snapshot(p));

  // Settings.
  await p.evaluate(() => window.__panel.act('page', { dataset: { v: 'settings' } }));
  await settle(p, 800);
  const set = await p.evaluate(() => ({ text: window.__panel.shadowRoot.querySelector('.settings').innerText, sideways: window.__panel.shadowRoot.querySelector('.scroll').scrollWidth > window.__panel.shadowRoot.querySelector('.scroll').clientWidth + 1 }));
  for (const h of ['brAIn', 'Learning', 'Improving Morph itself', 'This device', 'Appearance', 'History', 'Dashboard']) if (!set.text.includes(h)) fail(name, `Settings has no ${h} section`);
  if (set.sideways) fail(name, 'Settings scrolls sideways');
  // "What do you want to fix?" is Ask now (vision §13.3), not a box here.
  if (/What do you want to fix in Morph\?/i.test(set.text)) fail(name, 'Settings still has its own report box beside Ask');

  await p.evaluate(() => { window.__panel.act('page', { dataset: { v: 'home' } }); if (window.__panel.s.tell) window.__panel.closeTell(); });
  await settle(p, 800);
  await night(p, name);
  if (errors.length) fail(name, `page errors: ${errors.join(' | ')}`);
  await ctx.close();
}

// A house's card file that changes is loaded again at its new version, and
// a page can define a custom element only once: that is a reload to offer,
// never a fault to report (house report: "the name morph-scenes has already
// been used with this registry").
if (ONLY !== 'phone') { // single-width checks: run in one of the two processes
{
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  await route(ctx, { narrow: false });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await settle(p, 1800);
  for (const v of [1, 2]) {
    await p.evaluate((ver) => { window.__cardModules = [{ name: 'morph-twice.js', v: ver }]; return window.__panel.load(); }, v);
    await settle(p, 700);
  }
  const got = await p.evaluate(() => ({ reports: window.__ws.filter((m) => m.type === 'morph/report').map((m) => m.message), bar: (window.__panel.shadowRoot.querySelector('.bar') || {}).innerText || '', defined: !!customElements.get('morph-twice') }));
  if (!got.defined) fail('card code', 'the card file was never loaded');
  if (got.reports.some((x) => /morph-twice/.test(x))) fail('card code', `a changed card file was reported as a fault: ${got.reports.join(' | ')}`);
  if (!/Reload/.test(got.bar)) fail('card code', `a changed card file does not offer a reload: ${got.bar}`);
  await ctx.close();
}

// Opening Morph (house report: "super slow, leaves you on a white screen
// while it's loading", and "not clear if it needs to be reloaded"). The
// shell paints the dashboard's outline before any module has arrived, the
// modules load under s/<stamp>/ (static.py caches those for good), and a
// page whose code has moved on says which of a reload or a restart it needs.
{
  const requests = [];
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  await route(ctx, { narrow: false, moduleDelay: 1500, requests });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await p.waitForTimeout(300);
  const early = await p.evaluate(() => {
    const shell = document.querySelector('morph-boot');
    const o = shell && shell.shadowRoot.querySelector('.outline');
    return { shell: !!shell, outline: !!o, bg: o ? getComputedStyle(o).backgroundColor : '', text: o ? o.textContent : '', panel: !!(shell && shell.shadowRoot.querySelector('morph-panel')) };
  });
  if (!early.shell) fail('opening', 'the shell was not in the page while the panel loaded (Home Assistant waits on the module before creating it)');
  if (!early.outline) fail('opening', 'nothing was painted while the panel loaded');
  if (early.bg && /255, 255, 255/.test(early.bg)) fail('opening', `the outline is white (${early.bg})`);
  if (early.panel) fail('opening', 'the panel was already in place, so this did not measure the wait');
  await settle(p, 4000);
  const late = await p.evaluate(() => {
    const shell = document.querySelector('morph-boot');
    return { outline: !!shell.shadowRoot.querySelector('.outline'), drew: !!(window.__panel && window.__panel.shadowRoot.querySelector('[data-sec]')) };
  });
  if (!late.drew) fail('opening', 'the panel did not draw after loading');
  if (late.outline) fail('opening', 'the outline stayed over the dashboard after it loaded');
  const mods = requests.filter((r) => /\.js$/.test(r) && !r.endsWith('/boot.js'));
  const unstamped = mods.filter((r) => !/\/s\/[0-9a-f]{12}\//.test(r) && !r.includes('/shipped/'));
  if (!mods.length) fail('opening', 'no module requests were seen');
  if (unstamped.length) fail('opening', `modules loaded outside s/<stamp>/ (not cacheable): ${unstamped.join(', ')}`);

  const banner = async (setup) => {
    await p.evaluate(setup);
    await p.evaluate(() => window.__panel.load());
    await settle(p, 400);
    return p.evaluate(() => { const u = window.__panel.shadowRoot.querySelector('.update'); return u ? u.innerText : ''; });
  };
  let b = await banner(() => {});
  if (b) fail('opening', `a reload was offered with nothing changed: ${b}`);
  b = await banner(() => { window.__code = '0123456789ab'; });
  if (!/changed since this page opened/.test(b) || !/Reload/.test(b)) fail('opening', `moved code did not offer a reload: "${b}"`);
  b = await banner(() => { window.__code = ''; window.__integration = '9.9.9'; });
  if (!/Morph 9\.9\.9 is ready/.test(b)) fail('opening', `a newer integration did not offer a reload: "${b}"`);
  b = await banner(() => { window.__integration = ''; window.__fixture.state.version = '9.9.9'; });
  if (!/Restart Home Assistant/.test(b)) fail('opening', `a newer add-on did not ask for a restart: "${b}"`);
  await ctx.close();
}

// A hosted Lovelace card when Home Assistant's Lovelace chunk has not loaded
// (window.loadCardHelpers is not a function): a house's own custom card is
// still drawn without the helpers; with neither route the card says so in
// plain words and nothing shows the JS error.
for (const [label, define] of [['a defined custom card', true], ['no way to draw it', false]]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await route(ctx, { narrow: false });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 900);
  await p.evaluate(() => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false }; P._forceApply = true; P.engine.invalidate(); P.schedule(); });
  await settle(p, 1500);
  await p.evaluate((def) => {
    delete window.loadCardHelpers;
    window.__panel.llCards.clear();
    if (def) customElements.define('morph-now', class extends HTMLElement { setConfig(c) { this.c = c; this.textContent = 'MORPH-NOW ' + c.type; } });
    const P = window.__panel;
    let found; const seek = (o) => { if (!o || typeof o !== 'object') return; if (o.id === 'c_tile') { o.card = { type: def ? 'custom:morph-now' : 'tile', entity: 'sensor.outside_temperature' }; found = o; return; } Object.values(o).forEach(seek); };
    seek(P.dash); const slot = P.shadowRoot.querySelector('[data-ll]'); P.mountLovelace(slot.parentElement, found);
  }, define);
  await settle(p, define ? 1500 : 6500);
  const got = await p.evaluate(() => { const r = window.__panel.shadowRoot; return r.textContent; });
  if (process.env.DBG) console.log(label, await p.evaluate(() => { const s = window.__panel.shadowRoot.querySelector('[data-ll]'); return [s && s.innerHTML.slice(0, 150), [...(window.__panel._llPending || [])]]; }));
  if (define && !got.includes('MORPH-NOW custom:morph-now')) fail('lovelace helpers', `${label}: the custom card was not drawn without the helpers`);
  if (!define && !got.includes('This card could not be drawn yet; reload the page.')) fail('lovelace helpers', `${label}: the card did not show the plain message`);
  if (!define && /is not a function|not available/.test(got)) fail('lovelace helpers', `${label}: the household was shown a JS error`);
  await ctx.close();
}

// `options.detail`: a Lovelace card that belongs inside an opened card (a
// thermostat's performance chart) is folded away on the face and shown only
// while the card is open, without the rooms overlapping either way.
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await route(ctx, { narrow: false });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 900);
  await p.evaluate(() => {
    const P = window.__panel;
    P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false }; P._forceApply = true;
    const seek = (o) => { if (!o || typeof o !== 'object') return; if (o.id === 'c_up') { o.options = { detail: { type: 'tile', entity: 'sensor.outside_temperature' } }; return; } Object.values(o).forEach(seek); };
    seek(P.dash); P.engine.invalidate(); P.schedule();
  });
  await settle(p, 1500);
  const text = () => p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_up"]'); return t ? t.textContent : ''; });
  if ((await text()).includes('Lovelace tile')) fail('detail', 'options.detail was drawn on a closed card');
  await p.evaluate(() => window.__panel.openView('c_up', 'adv'));
  await settle(p, 1500);
  if (!(await text()).includes('Lovelace tile')) fail('detail', 'options.detail was not drawn when the card opened');
  { const so = sectionOverlaps(await snapshot(p)); if (so.length) fail('detail', `sections overlap with the detail open: ${so.join(', ')}`); }
  await p.evaluate(() => window.__panel.closeView ? window.__panel.closeView() : (window.__panel.s.view = null, window.__panel.schedule()));
  await settle(p, 1500);
  if ((await text()).includes('Lovelace tile')) fail('detail', 'options.detail stayed on the face after the card closed');
  await ctx.close();
}

// Morph's own code, changed by the house: a copy is served in place of
// Morph's own, and a copy that fails to load falls back to Morph's own with
// a sentence saying so (boot.js, static.py).
{
  const { readFileSync } = await import('node:fs');
  const shipped = readFileSync(new URL('../../morph/custom_components/morph/frontend/styles.js', import.meta.url), 'utf8');
  for (const [label, overrides, broken] of [
    ['a working copy', { 'styles.js': shipped.replace('`;\n', '.hello{color:rgb(1, 2, 3)!important}\n`;\n') }, false],
    ['a broken copy', { 'util.js': 'export const esc = (;' }, true],
  ]) {
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
    await route(ctx, { narrow: false, overrides });
    const p = await ctx.newPage();
    await p.goto(ORIGIN + '/');
    await settle(p, 2500);
    const got = await p.evaluate(() => {
      const root = window.__panel && window.__panel.shadowRoot;
      const hello = root && root.querySelector('.hello');
      return { drew: !!hello, color: hello ? getComputedStyle(hello).color : '', fallback: window.__morphFallback || '', note: root ? root.textContent.includes('did not load, so Morph is running its own copy') : false };
    });
    if (!got.drew) fail('own code', `${label}: the panel did not draw`);
    if (!broken && got.color !== 'rgb(1, 2, 3)') fail('own code', `${label} was not served in place of Morph's own (${got.color})`);
    if (broken && !got.fallback) fail('own code', `${label}: Morph did not fall back to its own copy`);
    if (broken && !got.note) fail('own code', `${label}: the page does not say a change did not load`);
    await ctx.close();
  }
}

} // one process only

// A copy an update paused: "Make it again" has to answer where it was
// pressed. It shipped answering with a line in the header and leaving the
// note exactly as it was, which read as nothing happening.
for (const [w, h, name] of W([[1440, 900, 'wide'], [400, 860, 'phone']])) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(name === 'phone' ? { hasTouch: true } : {}) });
  await route(ctx, { narrow: name === 'phone' });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await p.evaluate(() => { window.__fixture.state.code = [{ name: 'morph-panel.js', status: 'paused', kind: 'changed', at: 1 }]; window.__panel.load(); });
  await settle(p, 900);
  const notes = () => p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('.note')].map((n) => n.textContent.replace(/\s+/g, ' ')).join(' | '));
  const btn = p.locator('[data-act="code-redo"]');
  if (!(await btn.count())) { fail(`redo ${name}`, 'no Update on a paused copy'); await ctx.close(); continue; }
  // The service answers slowly while the house keeps changing (each change
  // redraws the panel): the note has to say it is working the whole time.
  await p.evaluate(() => { window.__redoDelay = 2500; window.__busy = setInterval(() => window.__push && window.__push(), 200); });
  await btn.first().click();
  await settle(p, 900);
  const waiting = await notes();
  if (!/Handing it to brAIn/.test(waiting)) fail(`redo ${name}`, `nothing says brAIn is being asked while the service answers (${waiting.slice(0, 120)})`);
  if (await btn.count()) fail(`redo ${name}`, 'Make it again is back while the first press is still being answered');
  await settle(p, 2200);
  await p.evaluate(() => clearInterval(window.__busy));
  const working = await notes();
  if (!/brAIn is updating your change to Morph’s morph-panel\.js/.test(working)) fail(`redo ${name}`, `the note does not say brAIn is at it (${working.slice(0, 120)})`);
  if (!(await p.locator('.note [data-tell]').count())) fail(`redo ${name}`, 'brAIn’s box did not open in the note');
  if (await btn.count()) fail(`redo ${name}`, 'Make it again is still offered while brAIn makes it again');
  await settle(p, 2600);
  const done = await notes();
  if (!/Reload to see it/.test(done) || !/Undo/.test(done)) fail(`redo ${name}`, `the finished redo does not offer Reload and Undo (${done.slice(0, 160)})`);
  if (/is paused/.test(done)) fail(`redo ${name}`, 'the note still says the change is paused after brAIn made it again');
  await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('[data-act="page"][data-v="settings"]'); b && b.click(); });
  await settle(p, 700);
  if (!(await p.evaluate((v) => window.__panel.shadowRoot.textContent.includes('Morph ' + v), VERSION))) fail(`redo ${name}`, 'Settings does not say which Morph is running');
  await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('[data-act="page"][data-v="home"]'); b && b.click(); });
  await settle(p, 700);
  // An update that rewrote the code the change was in: brAIn asks rather
  // than guessing, the change stays paused, and the answer is the next request.
  await p.evaluate(() => { window.__redoConflict = true; window.__redoDelay = 0; window.__fixture.state.code = [{ name: 'morph-panel.js', status: 'paused', kind: 'changed', at: 1 }]; window.__panel.s.tell = null; window.__panel.load(); });
  await settle(p, 700);
  await p.locator('[data-act="code-redo"]').first().click();
  await settle(p, 2600);
  const asked = await notes();
  if (!/brAIn needs you to choose how to bring your change/.test(asked)) fail(`redo ${name}`, `a merge brAIn would not guess at does not ask (${asked.slice(0, 200)})`);
  if (!/It stays paused/.test(asked)) fail(`redo ${name}`, 'the question does not say the change stays paused');
  if ((await p.locator('.note [data-act="tell-answer"]').count()) !== 3) fail(`redo ${name}`, 'the ways to resolve it are not buttons in the note');
  await p.locator('.note [data-act="tell-answer"][data-v="1"]').click();
  await settle(p, 400);
  const answered = await p.evaluate(() => window.__ws.filter((m) => m.kind === 'tell_answer').pop());
  if (!answered || answered.payload.choice !== 1) fail(`redo ${name}`, 'the pressed answer was not sent');
  await settle(p, 2600);
  const after = await notes();
  if (!/Put the theme switch inside the new gear menu/.test(after)) fail(`redo ${name}`, `the answer did not become the next request in the note (${after.slice(0, 200)})`);
  await p.evaluate(() => { window.__redoConflict = false; });
  // A press brAIn could not take says why, in the note, and can be tried again.
  await p.evaluate(() => { window.__redoDelay = 0; window.__redoError = 'brAIn is installed but its Automation integration is off.'; window.__fixture.state.code = [{ name: 'styles.js', status: 'paused', kind: 'changed', at: 1 }]; window.__panel.s.tell = null; window.__panel.load(); });
  await settle(p, 700);
  await p.locator('[data-act="code-redo"]').first().click();
  await settle(p, 700);
  const refused = await notes();
  if (!/brAIn did not start: brAIn is installed but its Automation integration is off/.test(refused)) fail(`redo ${name}`, `a refusal is not said in the note (${refused.slice(0, 160)})`);
  if (!(await p.locator('[data-act="code-redo"]').count())) fail(`redo ${name}`, 'a refused press cannot be tried again');
  // Several copies paused: ONE note with Update and Not now, and Update is
  // one press for all of them (owner: one press, not one per file, and two
  // plain words).
  await p.evaluate(() => { window.__redoError = ''; window.__redoDelay = 0; window.__fixture.state.code = [{ name: 'styles.js', status: 'paused', kind: 'changed', at: 1 }, { name: 'cards.js', status: 'paused', kind: 'changed', at: 1 }]; window.__fixture.state.activity = []; window.__panel.s.tell = null; window.__panel.s.redo = null; window.__panel.load(); });
  await settle(p, 700);
  const two = await notes();
  if (!/2 of your changes to it are paused/.test(two)) fail(`merge all ${name}`, `two paused copies are not one note (${two.slice(0, 160)})`);
  const labels = await p.evaluate(() => { const n = [...window.__panel.shadowRoot.querySelectorAll('.note')].find((x) => /are paused/.test(x.textContent)); return n ? [...n.querySelectorAll('.acts button')].map((b) => b.textContent.trim()) : []; });
  if (JSON.stringify(labels) !== JSON.stringify(['Update', 'Not now'])) fail(`merge all ${name}`, `the choices are not Update and Not now (${labels.join(', ')})`);
  if (/keep it|Tell Morph/i.test(two)) fail(`merge all ${name}`, 'the note still talks about keeping or telling Morph');
  if (await p.locator('.note [data-act="code-redo"]').count()) fail(`merge all ${name}`, 'two paused copies still offer one press per file');
  await p.locator('.note [data-act="code-merge-all"]').click();
  await settle(p, 900);
  const sent = await p.evaluate(() => window.__ws.filter((m) => m.kind === 'code_merge_all').length);
  if (sent !== 1) fail(`merge all ${name}`, `Update sent ${sent} merge requests, not one`);
  if (!/brAIn is updating your changes to Morph/.test(await notes())) fail(`merge all ${name}`, 'the note does not say brAIn is updating them');
  await settle(p, 2600);
  // Not now hides the note and leaves everything paused.
  await p.evaluate(() => { window.__fixture.state.code = [{ name: 'styles.js', status: 'paused', kind: 'changed', at: 1 }, { name: 'cards.js', status: 'paused', kind: 'changed', at: 1 }]; window.__fixture.state.activity = []; window.__panel.s.tell = null; window.__panel.s.redo = null; window.__panel.load(); });
  await settle(p, 700);
  await p.locator('.note [data-act="code-not-now"]').click();
  await settle(p, 500);
  if (/are paused/.test(await notes())) fail(`merge all ${name}`, 'Not now did not put the note away');
  await p.evaluate(() => { try { localStorage.removeItem('morph.notnow'); } catch (e) { /* none */ } window.__panel.notNow = ''; });
  await ctx.close();
}

// A card brAIn worked a number out for: the result says where each change
// landed, brAIn's question is buttons, and the button that changes Home
// Assistant says so and starts the next request. An opened card offers
// Home Assistant's own details dialog and, for an admin, the device page.
for (const [w, h, name] of W([[1440, 900, 'wide'], [400, 860, 'phone']])) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(name === 'phone' ? { hasTouch: true } : {}) });
  await route(ctx, { narrow: name === 'phone' });
  const p = await ctx.newPage();
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 900);
  await p.evaluate(() => window.__panel.openView('c_lr_fan', 'adv'));
  await settle(p, 900);
  const info = await p.evaluate(() => { const r = window.__panel.shadowRoot; return { details: !!r.querySelector('[data-tile="c_lr_fan"] [data-act="more-info"][data-v="fan.living_room"]'), device: !!r.querySelector('[data-tile="c_lr_fan"] [data-act="open-device"][data-v="dev_lr_fan"]') }; });
  if (!info.details) fail(`more-info ${name}`, 'an opened card does not offer Home Assistant’s details');
  if (!info.device) fail(`more-info ${name}`, 'an opened card on a device does not offer its device page');
  if (info.details) {
    const seen = await p.evaluate(() => new Promise((res) => { window.addEventListener('hass-more-info', (e) => res(e.detail && e.detail.entityId), { once: true }); window.__panel.shadowRoot.querySelector('[data-act="more-info"]').click(); setTimeout(() => res(null), 1000); }));
    if (seen !== 'fan.living_room') fail(`more-info ${name}`, `Details did not ask Home Assistant for its dialog (${seen})`);
  }
  if (info.device) {
    const where = await p.evaluate(() => new Promise((res) => { window.addEventListener('location-changed', () => res(location.pathname), { once: true }); window.__panel.shadowRoot.querySelector('[data-act="open-device"]').click(); setTimeout(() => res(null), 1000); }));
    if (where !== '/config/devices/device/dev_lr_fan') fail(`more-info ${name}`, `Device page did not go to the device (${where})`);
    await p.evaluate(() => history.pushState(null, '', '/'));
  }
  const btns = await p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('.moreinfo button')].map((b) => b.getBoundingClientRect().height));
  if (name === 'phone' && btns.some((x) => x < 40)) fail(`more-info ${name}`, `a details button is under the touch floor (${btns.join(', ')})`);
  // Tell brAIn about it; the fixture answers with a question.
  await p.evaluate(() => window.__panel.openTell({ kind: 'card', id: 'c_lr_fan', from: 'adv' }));
  await settle(p, 600);
  await p.evaluate(() => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Show the supply/return difference with its history'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  const scopeLine = await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-tell]').innerText);
  if (!/Home Assistant is changed only if you ask/.test(scopeLine) || !/nothing goes to GitHub unless you say yes/.test(scopeLine)) fail(`question ${name}`, 'the Tell box does not say what a request may touch before it is sent');
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-send"]').click());
  await settle(p, 3500);
  const box = () => p.evaluate(() => (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '');
  let text = await box();
  if (!/Keep a history of the supply\/return difference/.test(text)) fail(`question ${name}`, `brAIn’s question is not on screen (${text.slice(0, 200)})`);
  if (!/changes Home Assistant/.test(text)) fail(`question ${name}`, 'the answer that changes Home Assistant does not say so');
  if (!/brAIn’s memory\s*2 facts/.test(text)) fail(`question ${name}`, 'the facts queued for brAIn’s memory are not said');
  const wide = await p.evaluate(() => { const vw = window.innerWidth; return [...window.__panel.shadowRoot.querySelectorAll('[data-tell] *')].filter((e) => e.getBoundingClientRect().right > vw + 1).slice(0, 4).map((e) => `${e.tagName}.${e.className}`); });
  if (wide.length) fail(`question ${name}`, `the result is wider than the screen: ${wide.join(', ')}`);
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-answer"][data-v="1"]').click());
  await settle(p, 300);
  const sent = await p.evaluate(() => window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell_answer'));
  if (!sent || sent.payload.choice !== 1) fail(`question ${name}`, `the answer was not sent as the choice pressed (${JSON.stringify(sent)})`);
  await settle(p, 3500);
  text = await box();
  if (!/Make a template sensor sensor\.hvac_delta/.test(text)) fail(`question ${name}`, `the answer did not become the next request (${text.slice(0, 200)})`);
  if (!/Home Assistant\s*sensor\.hvac_delta/.test(text) || !/Undo asks brAIn to put these back/.test(text)) fail(`question ${name}`, `the Home Assistant change is not said with its undo (${text.slice(0, 300)})`);
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error(`measure-morph: ${problems.length} problem(s)`);
  problems.forEach((x) => console.error('  - ' + x));
  process.exit(1);
}
console.log('measure-morph: all checks passed');
