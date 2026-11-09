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
 *   * there is no Settings page and no ⚙ of Morph's own (they are brAIn's
 *     ⚙ › Dashboard since 4.0), and "See the changes" asks brAIn's shell
 *     to open that section.
 *
 *   * Coming up is one short strip: dragging it moves the timeline behind
 *     a fixed reading point and the readout says what is at the point, a
 *     tap on a dot goes there, a swipe settles on an event, Now comes back,
 *     and the arrow keys step from event to event; a card's Next chip
 *     (`morph-coming-up`) unfolds it under that card's tile with nothing
 *     overlapping, holding it in Edit holds the strip and not the tile, and
 *     the same chip folds it;
 *
 *   * Ask stacks: two questions asked back to back both answer, each with
 *     its own conversation, newest first, whichever finishes first; the
 *     second does not resume the session the first is using; the busy mark
 *     is on while either runs; tapping outside folds only the finished
 *     ones; five are kept. A Tell replaced while it runs is not lost: when
 *     it lands, the strip at the top says so with Show;
 *   * a switch card with `options.header: true` rides in its room's title
 *     row as a pill (amber while on, aria-pressed, a 44px target on
 *     touch), not as a tile, also while the room is folded, and is a tile
 *     again in Edit;
 *   * the room rail on a touch screen's right edge (and not on a fine
 *     pointer): a column of notches; a vertical swipe on it scrolls the
 *     page and jumps nowhere; a pull left follows the finger with ratchet
 *     ticks and opens it (a heavy haptic), wider and still with the floor
 *     names beside it; sliding then goes room to room, the room ringed, the
 *     others dimmed and its title level with the finger, the floor names
 *     never moving; lifting closes it on that room and the dimming clears;
 *     resting on it, pulling and a tap each say what to do.
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
    // Rule 13: nothing carries a title= hover text (a tooltip floats). A
    // hosted Lovelace card is its own code, not Morph's.
    const deep = (r0) => [...r0.querySelectorAll('*')].flatMap((el) => [el, ...(el.shadowRoot ? deep(el.shadowRoot) : [])]);
    const tooltips = deep(root).filter((el) => el.hasAttribute('title') && el.tagName !== 'IFRAME' && !el.closest('[data-ll]'))
      .map((el) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''}`);
    return {
      tooltips,
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
  if (d.tooltips.length) fail(where, `rule 13: ${d.tooltips.length} element(s) carry a title= tooltip: ${[...new Set(d.tooltips)].slice(0, 4).join(', ')}`);
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
  //
  // Press only once the strip has stopped moving and is what is under the
  // press point. The checks before this one (a reply that removes a case,
  // a room that opens, a Tell's panel closing) leave the layout springing,
  // and a runner that is slower than a laptop is still springing when the
  // measure reaches here: the press then lands on whatever has moved under
  // it, the strip never hears it, and all five checks below fail with a
  // message about the drag rather than about the press. Two reads in a row
  // that agree, and the strip under the point, before the finger goes down.
  const underPoint = () => p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const vp = root.querySelector('[data-upc-vp]'); if (!vp) return null;
    vp.scrollIntoView({ block: 'center' });
    const r = vp.getBoundingClientRect();
    const x = r.left + r.width * 0.75, y = r.top + r.height / 2;
    const hit = root.elementFromPoint(x, y);
    return { x, y, top: r.top, left: r.left, width: r.width, ok: !!(hit && vp.contains(hit)), hit: hit ? `${hit.tagName.toLowerCase()}.${String(hit.className || '').trim().split(/\s+/).join('.')}` : 'nothing' };
  });
  let press = await underPoint(); let calm = 0;
  for (let i = 0; i < 60 && press && calm < 2; i++) {
    await p.waitForTimeout(100);
    const next = await underPoint();
    calm = next && next.ok && Math.abs(next.top - press.top) < 0.5 && Math.abs(next.left - press.left) < 0.5 && Math.abs(next.width - press.width) < 0.5 ? calm + 1 : 0;
    press = next;
  }
  if (!press || !press.ok) fail(where, `the press point is not on the strip after 6s of waiting for the layout to settle (it is on ${press ? press.hit : 'nothing'})`);
  const startX = press ? press.x : s.l + s.w * 0.75;
  const startY = press ? press.y : s.y;
  s = { ...s, y: startY };
  await p.mouse.move(startX, startY);
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

// A card's Next chip (the fixture's Now card, a house's own custom card)
// sends `morph-coming-up`: the strip unfolds directly under THAT card's
// tile, across its row, the board makes room with nothing overlapping at
// rest or on the way, a press on it is not a press on the card, holding it
// in Edit holds the strip (not the tile), and the same chip folds it. With
// no card asking, it is in its old place under the story.
async function comingUpUnderCard(p, name) {
  const where = `${name} coming up under a card`;
  const place = () => p.evaluate(() => {
    const P = window.__panel; const root = P.shadowRoot;
    const reg = P.upcRegion();
    const tile = root.querySelector('[data-tile="c_now"]');
    const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, b: r.bottom, r: r.right }; };
    const find = (n) => { for (const el of n.querySelectorAll('*')) { if (el.matches('[data-next-chip]')) return el; if (el.shadowRoot) { const f = find(el.shadowRoot); if (f) return f; } } return null; };
    const sec = tile && tile.closest('[data-sec]');
    const others = sec ? [...sec.querySelectorAll('[data-tile]')].filter((t) => t !== tile).map(box) : [];
    return {
      home: !!reg && reg.parentElement && reg.parentElement.classList.contains('wrap') && reg.previousElementSibling && reg.previousElementSibling.getAttribute('data-region') === 'top',
      inSlot: !!reg && !!reg.closest('[data-upc-slot]') && reg.closest('[data-tile]') === tile,
      shown: !!reg && !reg.hidden && !!reg.querySelector('[data-upc-vp]'),
      strip: box(reg && reg.querySelector('[data-upc-vp]')), tile: box(tile), chip: box(find(root)), others,
      secW: sec ? sec.getBoundingClientRect().width : 0,
      said: window.__nextShown,
    };
  });
  const press = () => p.evaluate(() => {
    const find = (n) => { for (const el of n.querySelectorAll('*')) { if (el.matches('[data-next-chip]')) return el; if (el.shadowRoot) { const f = find(el.shadowRoot); if (f) return f; } } return null; };
    const chip = find(window.__panel.shadowRoot); if (!chip) return false;
    chip.click(); return true;
  });
  let s = await place();
  if (!s.home) fail(where, 'before any card asks, Coming up is not in its place under the story');
  if (!s.chip) { fail(where, 'the fixture\'s Now card has no Next chip'); return; }
  await p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_now"]'); t.scrollIntoView({ block: 'center' }); });
  await settle(p, 400);
  const sampling = sample(p, `${where} (unfolding)`, 1400);
  if (!(await press())) fail(where, 'the Next chip could not be pressed');
  await sampling;
  await settle(p, 600);
  atRest(`${where} at rest`, await still(p));
  s = await place();
  if (!s.inSlot) fail(where, 'the Next chip did not move Coming up into its card\'s tile');
  if (!s.shown) fail(where, 'Coming up is not drawn under the card');
  if (s.said !== true) fail(where, `the card was not told the strip is showing (detail.shown = ${s.said})`);
  if (s.strip && s.chip && s.strip.y < s.chip.b - 1) fail(where, 'Coming up is not under the card that opened it (it starts above the chip)');
  if (s.strip && s.tile && (s.strip.x < s.tile.x - 1 || s.strip.r > s.tile.r + 1 || s.strip.b > s.tile.b + 1)) fail(where, 'Coming up spills out of the tile it unfolded in');
  if (s.tile && s.secW && s.tile.w < s.secW - 40) fail(where, `the card hosting Coming up does not span its row (${s.tile.w.toFixed(0)} of ${s.secW.toFixed(0)}px)`);
  for (const o of s.others) if (s.tile && overlap(s.tile, { x: o.x, y: o.y, w: o.w, h: o.h }, 1)) fail(where, 'a tile in the same room sits on top of Coming up');
  // A press on the strip is the strip's, never a tap on the card it is in.
  const before = await p.evaluate(() => JSON.stringify(window.__calls));
  if (s.strip) {
    await p.mouse.click(s.strip.x + s.strip.w * 0.8, s.strip.y + s.strip.h / 2);
    await settle(p, 900);
    const after = await p.evaluate(() => ({ view: window.__panel.s.view, calls: JSON.stringify(window.__calls) }));
    if (after.view) fail(where, `a press on Coming up opened the card under it (${after.view.id})`);
    if (after.calls !== before) fail(where, 'a press on Coming up acted on the card under it');
  }
  // Edit: holding the strip holds the strip, not the tile it sits in.
  await p.evaluate(() => window.__panel.act('edit', { dataset: {} }));
  await settle(p, 1200);
  await still(p);
  s = await place();
  if (!s.inSlot) fail(where, 'in Edit, Coming up left the card it was opened under');
  if (s.strip) {
    await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-tile="c_now"]').scrollIntoView({ block: 'center' }));
    await settle(p, 300);
    const st = (await place()).strip;
    await p.mouse.move(st.x + st.w * 0.6, st.y + st.h / 2);
    await p.mouse.down();
    await p.waitForTimeout(150);
    const mid = await p.evaluate(() => window.__panel.s.hold);
    await p.waitForTimeout(650);
    await p.mouse.up();
    await settle(p, 500);
    const held = await p.evaluate(() => ({ tell: window.__panel.s.tell && window.__panel.s.tell.kind, view: window.__panel.s.view && window.__panel.s.view.id }));
    if (mid === 'c_now') fail(where, 'holding Coming up in Edit selected the tile it sits in');
    if (held.tell !== 'upcoming') fail(where, `holding Coming up in Edit did not open Tell brAIn about Coming up (${held.tell || 'nothing'})`);
    if (held.view === 'c_now') fail(where, 'holding Coming up in Edit opened the tile it sits in');
  }
  await p.evaluate(() => { const P = window.__panel; if (P.s.tell) P.closeTell(); P.act('edit', { dataset: {} }); });
  await settle(p, 1400);
  await still(p);
  // The same chip folds it, and the board closes up again.
  await press();
  await settle(p, 1200);
  atRest(`${where} folded`, await still(p));
  s = await place();
  if (s.shown) fail(where, 'pressing the Next chip again did not fold Coming up');
  if (s.said !== false) fail(where, `the card was not told the strip folded (detail.shown = ${s.said})`);
  // Nobody asking: back in its old place.
  await p.evaluate(() => { const P = window.__panel; P.s.upcHost = null; P.s.upcShown = null; P.schedule(); });
  await settle(p, 1200);
  atRest(`${where} back home`, await still(p));
  s = await place();
  if (!s.home || !s.shown) fail(where, 'with no card asking, Coming up is not back in its place under the story');
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
  // #452: a case reads as it does on brAIn's Needs you — the chip word,
  // brAIn's detail, brAIn's labels for every press Morph can carry (Snooze
  // put back), and the assistant called by the household's name.
  const same = await p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const card = (id) => {
      const c = root.querySelector(`[data-case-card="${id}"]`);
      if (!c) return null;
      const r = c.getBoundingClientRect();
      const btns = [...c.querySelectorAll('button[data-act="case"]')];
      return { chip: (c.querySelector('.casechip') || {}).textContent || '', body: (c.querySelector('.casebody') || {}).textContent || '',
        presses: btns.map((b) => b.textContent.trim()), out: btns.filter((b) => { const q = b.getBoundingClientRect(); return q.right > r.right + 1 || q.height < 40; }).map((b) => b.textContent.trim()),
        aria: (c.querySelector('.replyin') || { getAttribute: () => '' }).getAttribute('aria-label') || '' };
    };
    return { freezer: card('f:1791000000'), guess: card('h:1791000100') };
  });
  const want = { freezer: ['Problem', ['Add to To Do', 'Dismiss', 'Snooze']], guess: ['Question', ['Snooze', "Doesn't apply"]] };
  for (const [k, [chip, presses]] of Object.entries(want)) {
    const c = same[k];
    if (!c) { fail(where, `the ${k} case is not on the page`); continue; }
    if (c.chip.trim() !== chip) fail(where, `the ${k} case wears "${c.chip}" where brAIn's Needs you says ${chip}`);
    if (JSON.stringify(c.presses) !== JSON.stringify(presses)) fail(where, `the ${k} case's presses are ${JSON.stringify(c.presses)}, brAIn's are ${JSON.stringify(presses)}`);
    if (c.out.length) fail(where, `the ${k} case's ${c.out.join(', ')} spill out of the card or are under the touch target`);
    if (!/Juniper/.test(c.aria) || /brAIn/.test(c.aria)) fail(where, `the ${k} case's reply line does not name the household's assistant: "${c.aria}"`);
  }
  if (same.freezer && !/latch may not catch/.test(same.freezer.body)) fail(where, "the freezer case does not show brAIn's detail");
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
  // Snooze reaches brAIn as a snooze, and the case goes as brAIn's list drops it.
  await p.evaluate(() => { const b = window.__panel.shadowRoot.querySelector('[data-case-card="h:1791000100"] button[data-act="case"][data-v="snooze"]'); if (b) b.click(); });
  await settle(p, 800);
  const sn = await p.evaluate(() => (window.__caseReqs || []).filter((x) => x.action === 'snooze').map((x) => x.case));
  if (!sn.includes('h:1791000100')) fail(where, 'Snooze on a case did not reach brAIn as a snooze');
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
    return { dbg: JSON.stringify({ st: P.salState && P.salState.period, ap: P.salApplied && P.salApplied.period, view: !!P.s.view, tell: !!P.s.tell, ask: (P.s.asks || []).length, alarm: P.hass.states['alarm_control_panel.house'].state, ptr: !!(P.ptr || P.mptr || P.upcD || P.drag), edit: P.s.edit }), cls: r.querySelector('[data-morph-root]').className, story: (r.querySelector('.story') || {}).textContent || '', now: [...r.querySelectorAll('.nowband [data-tile]')].map((e) => e.getAttribute('data-tile')) };
  });
  if (!/form-night/.test(n.cls)) fail(where, `the armed-night house is not in the night form (${n.cls}) ${n.dbg}`);
  if (!/Front Door is unlocked/.test(n.story)) fail(where, `the night verdict does not name the unlocked door: "${n.story}"`);
  if (n.now.length !== 1 || n.now[0] !== 'c_front_lock') fail(where, `the night page does not hold exactly the unlocked door: ${n.now.join(', ')}`);
  atRest(`${name} at night`, await snapshot(p));
  // Night does not dim the page unless the dashboard asks (#343), and a
  // room's title marks go with `room_marks: false` (#347).
  const look = () => p.evaluate(() => {
    const r = window.__panel.shadowRoot;
    const sec = r.querySelector('section.sec:not(.nowband)');
    return { filter: sec ? getComputedStyle(sec).filter : '', chips: r.querySelectorAll('.sechead .chip').length, cls: r.querySelector('[data-morph-root]').className };
  });
  const plain = await look();
  if (plain.filter !== 'none') fail(where, `night dims the rooms with no night_dim set (${plain.filter})`);
  if (!plain.chips) fail(where, 'no room title carries a mark to take away, so room_marks is not measured');
  await p.evaluate(() => { const P = window.__panel; P.dash = { ...P.dash, night_dim: true, room_marks: false }; P.render(); });
  await settle(p, 400);
  const asked = await look();
  if (!/brightness/.test(asked.filter) || !/night-dim/.test(asked.cls)) fail(where, `night_dim: true does not dim the rooms (${asked.filter})`);
  if (asked.chips) fail(where, `room_marks: false leaves ${asked.chips} mark(s) in the room titles`);
  await p.evaluate(() => { const P = window.__panel; const d = { ...P.dash }; delete d.night_dim; delete d.room_marks; P.dash = d; P.render(); });
  await settle(p, 400);
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
  await comingUpUnderCard(p, name);

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
    await p.evaluate(() => { window.__ws.length = 0; window.__panel.s.asks = []; window.__panel.schedule(); });
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
  if (!/(?:brAIn|Juniper) saw:/.test(box.text)) fail(name, 'the finished tell does not say what brAIn saw');
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

  // Settings are brAIn's since 4.0 (⚙ › Dashboard): Morph has no page of
  // its own, no ⚙ in its bar, and its "See the changes" asks the shell to
  // open brAIn's.
  const set = await p.evaluate(() => {
    const r = window.__panel.shadowRoot;
    let opened = null;
    const on = (e) => { opened = e.detail; };
    window.__panel.addEventListener('brain-open', on);
    window.__panel.act('brain-open', { dataset: { v: 'dashboard' } });
    window.__panel.removeEventListener('brain-open', on);
    return { page: !!r.querySelector('.settings'), gear: !!r.querySelector('[data-act="page"][data-v="settings"]'), opened };
  });
  if (set.page) fail(name, 'Morph still draws a Settings page of its own');
  if (set.gear) fail(name, 'Morph\'s bar still has its own ⚙');
  if (!set.opened || set.opened.view !== 'settings' || set.opened.sec !== 'dashboard') fail(name, `"See the changes" did not ask for brAIn's ⚙ › Dashboard: ${JSON.stringify(set.opened)}`);
  // Back to the dashboard at rest, as leaving Settings did: out of Edit,
  // nothing open.
  await p.evaluate(() => { const P = window.__panel; if (P.s.tell) P.closeTell(); P.s.edit = false; P.s.view = null; P.cache.clear(); P.schedule(); });
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
  // The integration's own answer beats the version: an update that changed
  // no integration code moves the version and owes no restart.
  b = await banner(() => { window.__restart = false; });
  if (b) fail('opening', `a version-only update asked for something: "${b}"`);
  b = await banner(() => { window.__restart = true; window.__fixture.state.version = ''; });
  if (!/Restart Home Assistant/.test(b)) fail('opening', `changed integration code did not ask for a restart: "${b}"`);
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

// BEGIN batch-ui
// The house reports of 2026-11-09 (#786 #755 #758 #756 #765 #767), one class
// each, every one driven on a second example the report never named:
//   * #786 every row of chips (scenes, rooms) is a 40px target on touch;
//   * #755 no field is under 16px on a phone, also one in a card's own
//     shadow root that only exists after the card has been put on the page;
//   * #758 a section's small capital labels are 4.5:1 in light and dark in
//     every form of the page (a wall display dims its rooms to a third),
//     counting the dimming;
//   * #756 a tile that pairs a state with an action draws the action as a
//     button (a border, a verb and what it acts on), apart from the state;
//   * #765 a vacuum's press is a labelled button with an icon, not a switch;
//   * #767 a tile for something the board has no icon for still has one,
//     and says how long it has been idle.
for (const [w, h, name] of W([[1200, 860, 'wide'], [390, 844, 'phone']])) {
  const touch = name === 'phone';
  const where = `batch ${name}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
  await route(ctx, { narrow: touch, shell: true });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 1800);
  await p.evaluate(() => {
    // A card whose text box is made late, deep in nested shadow roots, the way Home Assistant's own fields upgrade.
    customElements.define('mx-late-say', class extends HTMLElement {
      setConfig() { this.style.cssText = 'display:block;height:70px'; this.attachShadow({ mode: 'open' }); }
      connectedCallback() { setTimeout(() => { let root = this.shadowRoot; for (let i = 0; i < 5; i++) { const d = document.createElement('div'); root.appendChild(d); root = d.attachShadow({ mode: 'open' }); } root.innerHTML = '<input type="text" placeholder="Ask to say something in the main rooms" style="font-size:15px">'; }, 500); }
    });
    const P = window.__panel;
    P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false };
    const states = { ...P.hass.states };
    const iso = (h, m) => { const d = new Date(); d.setHours(h, m, 0, 0); return d.toISOString(); };
    const put = (e, state, attributes, at) => { states[e] = { entity_id: e, state, attributes, last_changed: at || iso(4, 2), last_updated: at || iso(4, 2) }; };
    put('water_heater.oven', 'off', { friendly_name: 'Oven' });
    put('humidifier.nursery', 'off', { friendly_name: 'Nursery Humidifier' });
    put('cover.side_gate', 'closed', { friendly_name: 'Side Gate', device_class: 'gate' });
    put('lock.shed', 'locked', { friendly_name: 'Shed' });
    put('vacuum.dot', 'cleaning', { friendly_name: 'Dot', battery_level: 64 });
    P.hass = { ...P.hass, states };
    const d = JSON.parse(JSON.stringify(P.dash));
    const yard = d.floors.flatMap((f) => f.sections).find((x) => x.id === 's_yard');
    yard.groups[0].cards.push({ id: 'c_late', type: 'lovelace', card: { type: 'custom:mx-late-say' } },
      { id: 'c_oven', type: 'entity', entity: 'water_heater.oven' }, { id: 'c_humid', type: 'entity', entity: 'humidifier.nursery' },
      { id: 'c_gate', type: 'cover', entity: 'cover.side_gate' }, { id: 'c_shed', type: 'lock', entity: 'lock.shed' }, { id: 'c_dot', type: 'vacuum', entity: 'vacuum.dot' });
    // Every room says what its first group is, so the labels are on every room, dimmed or not.
    d.floors.forEach((f) => f.sections.forEach((sec) => { if (sec.groups && sec.groups[0] && !sec.groups[0].label) sec.groups[0].label = 'Comfort'; }));
    P.dash = d; P._secEnts = null; P._watch = null; P._forceApply = true; P.engine.invalidate(); P.schedule();
  });
  await settle(p, 2600);

  // #786: every row of chips is a target on touch.
  if (touch) {
    const small = await p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('.roomw, .scenes .wd, .secscenes .wd, .scenesline .wd, .cl-acts .wd')]
      .filter((b) => b.getBoundingClientRect().width > 0 && b.getBoundingClientRect().height < 39.5)
      .map((b) => `${b.textContent.trim()} ${Math.round(b.getBoundingClientRect().width)}x${Math.round(b.getBoundingClientRect().height)}`));
    if (small.length) fail(where, `#786: chips under 40px tall: ${[...new Set(small)].slice(0, 6).join(', ')}`);
  }

  // #755: no field under 16px, the late one in nested shadow roots too.
  if (touch) {
    const fields = await p.evaluate(() => {
      const deep = (r) => [...r.querySelectorAll('*')].flatMap((el) => [el, ...(el.shadowRoot ? deep(el.shadowRoot) : [])]);
      return deep(window.__panel.shadowRoot).filter((el) => /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) && !/^(range|checkbox|radio|hidden|color)$/.test(el.type))
        .map((el) => ({ n: `${el.tagName.toLowerCase()} ${el.placeholder || el.className || ''}`.trim(), fs: parseFloat(getComputedStyle(el).fontSize) }));
    });
    if (!fields.some((f) => /main rooms/.test(f.n))) fail(where, '#755: the card with a late, deeply nested text box was not drawn');
    const small = fields.filter((f) => f.fs < 16);
    if (small.length) fail(where, `#755: fields under 16px zoom a phone on focus: ${small.map((x) => `${x.n} ${x.fs}px`).join(', ')}`);
  }

  // #758: small capital labels, counting how much the page dims them.
  for (const th of ['dark', 'light']) {
    for (const form of ['', 'still', 'away', 'night']) {
      await p.evaluate(([th, form]) => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: th }; P.form = () => form; P.schedule(); }, [th, form]);
      await settle(p, 900);
      const low = await p.evaluate(() => {
        const R = window.__panel.shadowRoot;
        const cv = document.createElement('canvas'); cv.width = cv.height = 1; const g = cv.getContext('2d', { willReadFrequently: true });
        const parse = (c) => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = c; g.fillRect(0, 0, 1, 1); const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
        const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
        const root = R.querySelector('[data-morph-root]');
        const surface = parse(getComputedStyle(root).getPropertyValue('--surface').trim() || '#000');
        const page = parse(getComputedStyle(root).getPropertyValue('--bg').trim() || '#000');
        const out = [];
        // Every small capital label, found the way #679 finds them.
        R.querySelectorAll('*').forEach((el) => {
          if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) || el.closest('[data-ll]')) return;
          const r = el.getBoundingClientRect(); if (!r.width || el.closest('.campic')) return;
          const st = getComputedStyle(el);
          if (st.textTransform !== 'uppercase' && !(parseFloat(st.fontSize) <= 13 && parseFloat(st.letterSpacing) > 0)) return;
          let alpha = 1, bright = 1;
          for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); alpha *= parseFloat(cs.opacity); const m = /brightness\(([\d.]+)\)/.exec(cs.filter || ''); if (m) bright *= parseFloat(m[1]); }
          const cs = getComputedStyle(el); const fg = parse(cs.color);
          const bg = [0, 1, 2].map((i) => surface[i] * alpha + page[i] * (1 - alpha));
          const fgc = [0, 1, 2].map((i) => (fg[i] * fg[3] + surface[i] * (1 - fg[3])) * alpha + page[i] * (1 - alpha));
          const rr = ratio(fgc.map((v) => v * bright), bg.map((v) => v * bright));
          if (rr < 4.5) out.push(`${el.textContent.trim().slice(0, 14)} ${rr.toFixed(2)}:1`);
        });
        return [...new Set(out)];
      });
      if (low.length) fail(where, `#758: ${th}${form ? ' ' + form : ''}: section labels under 4.5:1: ${low.slice(0, 5).join(', ')}`);
    }
  }
  await p.evaluate(() => { const P = window.__panel; delete P.form; P.data.state.settings = { ...(P.data.state.settings || {}), theme: 'dark' }; P.schedule(); });
  await settle(p, 900);

  // #756 #765: a state beside an action is a button apart from the state.
  {
    const tiles = await p.evaluate(() => {
      const R = window.__panel.shadowRoot;
      return ['c_garage', 'c_gate', 'c_front_lock', 'c_shed', 'c_obi', 'c_dot'].map((id) => {
        const t = R.querySelector(`[data-tile="${id}"]`); if (!t) return { id, missing: true };
        t.scrollIntoView({ block: 'center' });
        const a = t.querySelector('.actword'); const st = t.querySelector('.nv > span');
        const cs = a && getComputedStyle(a); const r = a && a.getBoundingClientRect();
        return { id, state: st ? st.textContent.trim() : '', act: a ? a.textContent.trim() : '', border: cs ? parseFloat(cs.borderTopWidth) + parseFloat(cs.borderLeftWidth) : 0,
          h: r ? Math.round(r.height) : 0, svg: !!(a && a.querySelector('svg')), label: a ? (a.getAttribute('aria-label') || a.textContent.trim()) : '',
          track: !!t.querySelector('.track'), actColor: cs ? cs.color : '', stColor: st ? getComputedStyle(st).color : '', inside: a ? r.right <= t.getBoundingClientRect().right + 0.5 : false };
      });
    });
    for (const t of tiles) {
      if (t.missing) { fail(where, `#756: the ${t.id} tile is not on the page`); continue; }
      if (!t.act) fail(where, `#756: ${t.id} pairs "${t.state}" with no action`);
      else {
        if (!t.border) fail(where, `#756: ${t.id}'s "${t.act}" has no outline, so it reads as more state text`);
        if (touch && t.h < 40) fail(where, `#756: ${t.id}'s "${t.act}" is ${t.h}px tall`);
        if (!t.inside) fail(where, `#756: ${t.id}'s "${t.act}" runs off its tile`);
      }
    }
    const by = Object.fromEntries(tiles.map((t) => [t.id, t]));
    if (by.c_garage && !/^Open door$/.test(by.c_garage.act)) fail(where, `#756: the closed garage's action says "${by.c_garage.act}", not "Open door"`);
    if (by.c_gate && !/^Open gate$/.test(by.c_gate.act)) fail(where, `#756: the closed gate's action says "${by.c_gate.act}", not "Open gate"`);
    for (const id of ['c_obi', 'c_dot']) {
      const t = by[id]; if (!t || t.missing) continue;
      if (t.track) fail(where, `#765: ${id} still draws a switch (two circles with no words)`);
      if (!t.svg) fail(where, `#765: ${id}'s button has no icon`);
      if (!/^(Start|Dock)$/.test(t.label)) fail(where, `#765: ${id}'s button is labelled "${t.label}", not Start or Dock`);
    }
    if (by.c_obi && by.c_obi.label !== 'Start') fail(where, `#765: a docked vacuum offers "${by.c_obi.label}", not Start`);
    if (by.c_dot && by.c_dot.label !== 'Dock') fail(where, `#765: a cleaning vacuum offers "${by.c_dot.label}", not Dock`);
    // Light and dark: the button's words are readable against its tile.
    for (const th of ['light', 'dark']) {
      await p.evaluate((th) => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: th }; P.schedule(); }, th);
      await settle(p, 800);
      const low = await p.evaluate(() => {
        const R = window.__panel.shadowRoot; const cv = document.createElement('canvas'); cv.width = cv.height = 1; const g = cv.getContext('2d', { willReadFrequently: true });
        const parse = (c) => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = c; g.fillRect(0, 0, 1, 1); const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
        const root = R.querySelector('[data-morph-root]'); const bg = parse(getComputedStyle(root).getPropertyValue('--surface').trim());
        return ['c_garage', 'c_obi', 'c_dot', 'c_front_lock'].map((id) => { const a = R.querySelector(`[data-tile="${id}"] .actword`); if (!a) return `${id} none`; const x = lum(parse(getComputedStyle(a).color)), y = lum(bg); const r = (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); return r < 4.5 ? `${id} ${r.toFixed(2)}:1` : ''; }).filter(Boolean);
      });
      if (low.length) fail(where, `#756 #765: ${th}: action words under 4.5:1: ${low.join(', ')}`);
    }
    await p.evaluate(() => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: 'dark' }; P.schedule(); });
    await settle(p, 600);
  }

  // #767: a tile for something with no icon of its own has one, and says how long it has been idle.
  {
    const rows = await p.evaluate(() => ['c_oven', 'c_humid'].map((id) => {
      const t = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`); if (!t) return { id, missing: true };
      const svg = t.querySelector('.sline > svg'); const path = svg ? svg.querySelector('path').getAttribute('d') : '';
      const r = svg ? svg.getBoundingClientRect() : { width: 0 };
      return { id, svg: !!svg, w: Math.round(r.width), generic: path === 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', words: (t.querySelector('.nv > span') || {}).textContent || '' };
    }));
    for (const t of rows) {
      if (t.missing) { fail(where, `#767: the ${t.id} tile is not on the page`); continue; }
      if (!t.svg || t.w < 16) fail(where, `#767: ${t.id} has a gap where its icon should be`);
      else if (t.generic) fail(where, `#767: ${t.id} shows the plain ring that stands for "no icon"`);
      if (!/^Off since /.test(t.words.trim())) fail(where, `#767: ${t.id} says "${t.words.trim()}", not how long it has been off`);
    }
  }
  if (errors.length) fail(where, `page errors: ${errors.slice(0, 2).join(' | ')}`);
  await ctx.close();
}
// END batch-ui

// #795 "the dashboard is flashing a lot": a hosted card is made once and
// kept (llCards). Home Assistant's element for a custom card can announce
// `ll-rebuild` and be a different element from the card's tag (a wrapper);
// that announcement is only meant for a card made BEFORE its tag was
// defined. When the tag was already defined it used to evict the card on
// every mount, so each render made every hosted card again. Ten hass updates
// must change nothing inside any card's slot, and llCards must hold exactly
// the hosted cards.
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
    customElements.define('morph-wrapped', class extends HTMLElement { setConfig() {} });
    // Like Home Assistant's: the element it hands back is a wrapper whose
    // name is not the card's tag, and it says `ll-rebuild` whenever it is
    // put on the page.
    customElements.define('hui-wrapped-card', class extends HTMLElement { setConfig() {} connectedCallback() { this.dispatchEvent(new Event('ll-rebuild')); } });
    window.loadCardHelpers = async () => ({ createCardElement(cfg) {
      if (cfg.type === 'custom:morph-wrapped') return document.createElement('hui-wrapped-card');
      const d = document.createElement('div'); d.textContent = 'Lovelace ' + cfg.type; return d;
    } });
    const seek = (o) => { if (!o || typeof o !== 'object') return; if (o.id === 'c_tile') { o.card = { type: 'custom:morph-wrapped' }; return; } Object.values(o).forEach(seek); };
    seek(P.dash); P.llCards.clear(); P.engine.invalidate(); P.schedule();
  });
  await settle(p, 2500);
  const r = await p.evaluate(async () => {
    const P = window.__panel;
    const slots = [...P.shadowRoot.querySelectorAll('[data-ll]')].filter((s) => !s.dataset.ll.endsWith(':detail'));
    let muts = 0;
    const mo = new MutationObserver((l) => { muts += l.filter((m) => m.type === 'childList').length; });
    slots.forEach((s) => mo.observe(s, { childList: true }));
    for (let i = 0; i < 10; i++) { P.hass = { ...P.hass, states: { ...P.hass.states } }; await new Promise((res) => setTimeout(res, 250)); }
    mo.disconnect();
    return { hosted: slots.length, kept: P.llCards.size, muts };
  });
  if (r.hosted < 2) fail('flashing', `the harness hosts ${r.hosted} cards, not 2`);
  if (r.muts) fail('flashing', `ten hass updates changed the inside of a hosted card's slot ${r.muts} times (every render made the cards again)`);
  if (r.kept !== r.hosted) fail('flashing', `llCards holds ${r.kept} cards for ${r.hosted} hosted`);
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
  const shipped = readFileSync(new URL('../../brain/custom_components/brain/morph/frontend/styles.js', import.meta.url), 'utf8');
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

// A copy that LOADS and then throws while drawing one room (house report
// #344: a ReferenceError in one room's state left only the clock and the
// header). That room is a line saying it could not be drawn, every other
// room draws, and the fault is reported rather than swallowed.
{
  const { readFileSync } = await import('node:fs');
  const own = readFileSync(new URL('../../brain/custom_components/brain/morph/frontend/morph-panel.js', import.meta.url), 'utf8');
  for (const [label, hook, body] of [
    ['its state', '  roomStateOf(sec) {\n', "    if (sec.id === 's_kitchen') roomGlowNotDefined.x = 1;\n"],
    ['its drawing', '  paintSection(el, sec, ms) {\n', "    if (sec.id === 's_kitchen') roomPaintNotDefined.x = 1;\n"],
  ]) {
    if (!own.includes(hook)) { fail('room fault', `${label}: the hook ${JSON.stringify(hook)} is not in morph-panel.js`); continue; }
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
    await route(ctx, { narrow: false, overrides: { 'morph-panel.js': own.replace(hook, hook + body) } });
    const p = await ctx.newPage();
    const errors = [];
    p.on('pageerror', (e) => errors.push(String(e)));
    await p.goto(ORIGIN + '/');
    await settle(p, 2500);
    const got = await p.evaluate(() => {
      const root = window.__panel && window.__panel.shadowRoot;
      const sec = (id) => root && root.querySelector(`[data-sec="${id}"]`);
      return {
        kitchen: (sec('s_kitchen') || {}).textContent || '',
        living: !!(sec('s_living') && sec('s_living').querySelector('[data-tile]')),
        porch: !!sec('s_porch'),
        reports: window.__ws.filter((m) => m.type === 'morph/report').map((m) => m.message),
      };
    });
    if (!/could not draw this room/i.test(got.kitchen)) fail('room fault', `${label}: the room that threw does not say so (${got.kitchen.slice(0, 120)})`);
    if (!got.living || !got.porch) fail('room fault', `${label}: the other rooms did not draw`);
    if (!got.reports.some((m) => /NotDefined/.test(m))) fail('room fault', `${label}: the fault was not reported (${got.reports.join(' | ')})`);
    if (errors.length) fail('room fault', `${label}: page errors: ${errors.slice(0, 2).join(' | ')}`);
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
  if (!/Handing it to (?:brAIn|Juniper)/.test(waiting)) fail(`redo ${name}`, `nothing says brAIn is being asked while the service answers (${waiting.slice(0, 120)})`);
  if (await btn.count()) fail(`redo ${name}`, 'Make it again is back while the first press is still being answered');
  await settle(p, 2200);
  await p.evaluate(() => clearInterval(window.__busy));
  const working = await notes();
  if (!/(?:brAIn|Juniper) is updating your change to Morph’s morph-panel\.js/.test(working)) fail(`redo ${name}`, `the note does not say brAIn is at it (${working.slice(0, 120)})`);
  if (!(await p.locator('.note [data-tell]').count())) fail(`redo ${name}`, 'brAIn’s box did not open in the note');
  if (await btn.count()) fail(`redo ${name}`, 'Make it again is still offered while brAIn makes it again');
  await settle(p, 2600);
  const done = await notes();
  if (!/Reload to see it/.test(done) || !/Undo/.test(done)) fail(`redo ${name}`, `the finished redo does not offer Reload and Undo (${done.slice(0, 160)})`);
  if (/is paused/.test(done)) fail(`redo ${name}`, 'the note still says the change is paused after brAIn made it again');
  // An update that rewrote the code the change was in: brAIn asks rather
  // than guessing, the change stays paused, and the answer is the next request.
  await p.evaluate(() => { window.__redoConflict = true; window.__redoDelay = 0; window.__fixture.state.code = [{ name: 'morph-panel.js', status: 'paused', kind: 'changed', at: 1 }]; window.__panel.s.tell = null; window.__panel.load(); });
  await settle(p, 700);
  await p.locator('[data-act="code-redo"]').first().click();
  await settle(p, 2600);
  const asked = await notes();
  if (!/(?:brAIn|Juniper) needs you to choose how to bring your change/.test(asked)) fail(`redo ${name}`, `a merge brAIn would not guess at does not ask (${asked.slice(0, 200)})`);
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
  await p.evaluate(() => { window.__redoDelay = 0; window.__redoError = "brAIn's Automation integration is off."; window.__fixture.state.code = [{ name: 'styles.js', status: 'paused', kind: 'changed', at: 1 }]; window.__panel.s.tell = null; window.__panel.load(); });
  await settle(p, 700);
  await p.locator('[data-act="code-redo"]').first().click();
  await settle(p, 700);
  const refused = await notes();
  if (!/(?:brAIn|Juniper) did not start: (?:brAIn|Juniper)'s Automation integration is off/.test(refused)) fail(`redo ${name}`, `a refusal is not said in the note (${refused.slice(0, 160)})`);
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
  if (!/(?:brAIn|Juniper) is updating your changes to Morph/.test(await notes())) fail(`merge all ${name}`, 'the note does not say brAIn is updating them');
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
  if (!/(?:brAIn|Juniper)’s memory\s*2 facts/.test(text)) fail(`question ${name}`, 'the facts queued for brAIn’s memory are not said');
  const wide = await p.evaluate(() => { const vw = window.innerWidth; return [...window.__panel.shadowRoot.querySelectorAll('[data-tell] *')].filter((e) => e.getBoundingClientRect().right > vw + 1).slice(0, 4).map((e) => `${e.tagName}.${e.className}`); });
  if (wide.length) fail(`question ${name}`, `the result is wider than the screen: ${wide.join(', ')}`);
  await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-act="tell-answer"][data-v="1"]').click());
  await settle(p, 300);
  const sent = await p.evaluate(() => window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'tell_answer'));
  if (!sent || sent.payload.choice !== 1) fail(`question ${name}`, `the answer was not sent as the choice pressed (${JSON.stringify(sent)})`);
  await settle(p, 3500);
  text = await box();
  if (!/Make a template sensor sensor\.hvac_delta/.test(text)) fail(`question ${name}`, `the answer did not become the next request (${text.slice(0, 200)})`);
  if (!/Home Assistant\s*sensor\.hvac_delta/.test(text) || !/Undo asks (?:brAIn|Juniper) to put these back/.test(text)) fail(`question ${name}`, `the Home Assistant change is not said with its undo (${text.slice(0, 300)})`);
  await ctx.close();
}

// ------------------------------------------------------------------
// Ask stacks, the header switch, the room rail (owner requests).
const SHOTS = process.env.MORPH_SHOTS || '';
async function shot(p, file) {
  if (!SHOTS) return;
  await p.screenshot({ path: `${SHOTS}/${file}.png` });
}
async function touchPath(p, pts, stepMs, holdMs) {
  const cdp = await p.context().newCDPSession(p);
  const [x0, y0] = pts[0];
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y: y0 }] });
  if (holdMs) await p.waitForTimeout(holdMs);
  for (const [x, y] of pts.slice(1)) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y }] }); await p.waitForTimeout(stepMs || 16); }
  return { end: async () => { await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await cdp.detach(); }, cdp };
}

for (const [w, h, name] of W([[1200, 860, 'wide'], [390, 844, 'phone']])) {
  const touch = name === 'phone';
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
  await route(ctx, { narrow: touch });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 1500);
  const where = `owner ${name}`;

  // 1. Two questions back to back: both answer, stacked newest first.
  {
    await p.evaluate(() => { window.__convEcho = true; window.__ws.length = 0; });
    const askIt = (q) => p.evaluate((q) => { const i = window.__panel.shadowRoot.querySelector('input[data-keep="ask"]'); i.value = q; window.__panel.act('ask', i); }, q);
    await askIt('Which lights are on, slow please?');
    await p.waitForTimeout(150);
    await askIt('Is the porch light on?');
    await settle(p, 400);
    const busy = await p.evaluate(() => { const a = window.__panel.shadowRoot.querySelector('[data-ask]'); return a && a.getAttribute('aria-busy'); });
    if (busy !== 'true') fail(where, `the Ask line does not say it is busy while two questions run (aria-busy=${busy})`);
    await shot(p, `ask-stack-running-${name}`);
    await settle(p, 1000);
    const mid = await p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('[data-ask] .answer')].map((e) => e.innerText.replace(/\s+/g, ' ')));
    if (!mid.some((t) => /You asked: Is the porch light on\?/.test(t))) fail(where, `the second question's answer did not arrive while the first ran (${mid.join(' | ').slice(0, 200)})`);
    const busy2 = await p.evaluate(() => { const a = window.__panel.shadowRoot.querySelector('[data-ask]'); return a && a.getAttribute('aria-busy'); });
    if (busy2 !== 'true') fail(where, 'the busy mark went off while the first question was still running');
    await settle(p, 2600);
    const both = await p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('[data-ask] .answer')].map((e) => e.innerText.replace(/\s+/g, ' ')));
    if (!both.some((t) => /You asked: Which lights are on, slow please\?/.test(t))) fail(where, `the first question's answer was lost when a second was asked (${both.join(' | ').slice(0, 240)})`);
    if (both.length < 2 || !/Is the porch light on/.test(both[0]) || !/Which lights are on/.test(both[1])) fail(where, `the answers are not stacked newest first (${both.join(' | ').slice(0, 240)})`);
    const convs = await p.evaluate(() => window.__ws.filter((m) => m.type === 'morph/request' && m.kind === 'converse').map((m) => m.payload));
    if (convs.length !== 2) fail(where, `two questions did not start two conversations (${convs.length})`);
    else if (convs[1].session) fail(where, `the second question resumed a session while the first was still using it (${convs[1].session})`);
    const idle = await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-ask]').getAttribute('aria-busy'));
    if (idle !== 'false') fail(where, 'the busy mark stays on after every question answered');
    await shot(p, `ask-stack-${name}`);
    // Outside folds the finished ones only.
    await askIt('Anything left on, slow?');
    await settle(p, 300);
    await p.mouse.click(4, Math.round(h * 0.6));
    await settle(p, 300);
    const left = await p.evaluate(() => [...window.__panel.shadowRoot.querySelectorAll('[data-ask] .answer')].map((e) => e.innerText.replace(/\s+/g, ' ')));
    if (left.length !== 1 || !/Anything left on/.test(left[0])) fail(where, `tapping outside did not fold exactly the finished answers (${left.join(' | ').slice(0, 200)})`);
    for (let i = 0; i < 6; i++) await askIt(`Question ${i}?`);
    await settle(p, 3200);
    const kept = await p.evaluate(() => window.__panel.shadowRoot.querySelectorAll('[data-ask] .answer').length);
    if (kept !== 5) fail(where, `Ask keeps ${kept} answers, not the last 5`);
    await p.mouse.click(4, Math.round(h * 0.6));
    await p.evaluate(() => { window.__convEcho = false; });
    await settle(p, 400);
  }

  // 1b. A Tell replaced while it runs: its result is said when it lands.
  {
    await p.evaluate(() => { window.__panel.tellDashboard('Make the kitchen card wider'); });
    await settle(p, 300);
    await p.evaluate(() => { window.__panel.tellDashboard('Move the porch section first'); });
    await settle(p, 2000);
    await p.evaluate(() => window.__panel.pollTell());
    await settle(p, 500);
    const strip = await p.evaluate(() => (window.__panel.shadowRoot.querySelector('[data-region="lede"]') || {}).innerText || '');
    if (!/finished “Make the kitchen card wider”/.test(strip)) fail(where, `a Tell replaced while it ran left no trace when it finished (${strip.slice(0, 160)})`);
    const back = p.locator('[data-region="lede"] [data-act="tell-back"]');
    if (await back.count()) {
      await back.first().click();
      await settle(p, 500);
      const box = await p.evaluate(() => ((window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || ''));
      if (!/Make the kitchen card wider/.test(box) || !/Undo/.test(box)) fail(where, `Show did not open the earlier Tell's result with its Undo (${box.slice(0, 160)})`);
    }
    await p.evaluate(() => { window.__panel.s.tell = null; window.__panel.tellsAway = []; window.__panel.schedule(); });
    await settle(p, 400);
  }

  // 2. A switch card with options.header rides in its room's title row.
  {
    await p.evaluate(() => {
      const P = window.__panel; const d = JSON.parse(JSON.stringify(P.dash));
      const yard = d.floors.flatMap((f) => f.sections).find((s) => s.id === 's_yard');
      yard.groups[0].cards.push({ id: 'c_pause', type: 'switch', entity: 'input_boolean.guest_mode', name: 'Pause watering', options: { header: true } });
      P.dash = d; P._secEnts = null; P._watch = null; P._forceApply = true; P.engine.invalidate(); P.render();
    });
    await settle(p, 1200);
    const read = () => p.evaluate(() => {
      const r = window.__panel.shadowRoot; const sec = r.querySelector('[data-sec="s_yard"]');
      const pill = sec && sec.querySelector('.sechead [data-act="head-toggle"]');
      const b = pill && pill.getBoundingClientRect();
      return { folded: !!sec && sec.classList.contains('folded'), pill: !!pill, text: pill ? pill.textContent.trim() : '', pressed: pill ? pill.getAttribute('aria-pressed') : null, h: b ? b.height : 0, title: pill ? pill.hasAttribute('title') : false, tile: !!r.querySelector('[data-tile="c_pause"]'), color: pill ? getComputedStyle(pill).color : '' };
    });
    let got = await read();
    if (!got.pill) fail(where, `a header switch is not in its room's title row (folded: ${got.folded})`);
    if (got.tile) fail(where, 'a header switch is drawn as a tile as well');
    if (got.pill && got.text !== 'Pause watering') fail(where, `the header switch is not named by its card (${got.text})`);
    if (got.pill && got.pressed !== 'false') fail(where, `an off header switch is not aria-pressed=false (${got.pressed})`);
    if (got.title) fail(where, 'the header switch carries a title tooltip');
    if (touch && got.pill && got.h < 44) fail(where, `the header switch is under the 44px touch floor (${got.h})`);
    await p.evaluate(() => { const el = window.__panel.shadowRoot.querySelector('[data-sec="s_yard"]'); el.scrollIntoView({ block: 'center' }); });
    await settle(p, 300);
    await shot(p, `header-pill-off-${name}`);
    if (got.pill) {
      await p.evaluate(() => { window.__calls = []; });
      await p.locator('[data-sec="s_yard"] [data-act="head-toggle"]').click();
      await settle(p, 500);
      const calls = await p.evaluate(() => window.__calls);
      if (!calls.some((c) => c.domain === 'homeassistant' && c.service === 'toggle' && [].concat(c.data.entity_id).includes('input_boolean.guest_mode'))) fail(where, `tapping the header switch did not toggle it (${JSON.stringify(calls)})`);
      got = await read();
      if (got.pressed !== 'true') fail(where, `an on header switch is not aria-pressed=true (${got.pressed})`);
      await shot(p, `header-pill-on-${name}`);
      // Folded: still there.
      const folded = await p.evaluate(async () => { const P = window.__panel; P.s.unfold.s_yard = 0; P.foldNow = 's_yard'; P._forceApply = true; P.engine.invalidate(); P.schedule(); await new Promise((r) => setTimeout(r, 900)); const sec = P.shadowRoot.querySelector('[data-sec="s_yard"]'); return { folded: sec.classList.contains('folded'), pill: !!sec.querySelector('.sechead [data-act="head-toggle"]') }; });
      if (folded.folded && !folded.pill) fail(where, 'the header switch is gone while its room is folded');
      // Edit: a tile again, no pill.
      await p.evaluate(() => window.__panel.act('edit', { dataset: {} }));
      await settle(p, 1200);
      const ed = await p.evaluate(() => { const r = window.__panel.shadowRoot; return { pill: !!r.querySelector('[data-sec="s_yard"] .sechead [data-act="head-toggle"]'), tile: !!r.querySelector('[data-tile="c_pause"]') }; });
      if (ed.pill) fail(where, 'the header switch is drawn in the title row in Edit');
      if (!ed.tile) fail(where, 'the header switch is not an editable tile in Edit');
      await p.evaluate(() => window.__panel.act('edit', { dataset: {} }));
      await settle(p, 1200);
      await p.evaluate(() => window.__panel.hass.callService('homeassistant', 'toggle', { entity_id: 'input_boolean.guest_mode' }));
    }
    atRest(`${where} with a header switch`, await still(p));
  }

  // 3. The room rail (touch only): a vertical swipe scrolls, a pull left
  // opens the notched rail (wider, still, the floor names beside it), and
  // without lifting, sliding goes room to room: the room is ringed, the
  // others dim, and its title sits level with the finger. Lifting lands on
  // it and closes the rail.
  if (!touch) {
    const drawn = await p.evaluate(() => { const r = window.__panel.shadowRoot.querySelector('[data-rail]'); return r ? r.getBoundingClientRect().width : 0; });
    if (drawn > 0) fail(where, `the room rail is drawn on a fine pointer (${drawn}px wide)`);
    await shot(p, `rail-none-${name}`);
  }
  if (touch) {
    await p.evaluate(() => { const P = window.__panel; P.$('.scroll').scrollTop = 0; });
    await settle(p, 500);
    const rail = await p.evaluate(() => { const r = window.__panel.shadowRoot.querySelector('[data-rail]'); if (!r) return null; const b = r.getBoundingClientRect(); return { x: b.left, w: b.width, right: b.right, top: b.top, h: b.height }; });
    if (!rail || rail.w < 4) fail(where, 'there is no room rail on the right edge of a touch screen');
    else {
      const rx = rail.x + rail.w / 2;
      const state = () => p.evaluate(() => {
        const P = window.__panel; const R = P.shadowRoot; const r = R.querySelector('[data-rail]');
        const panel = r.querySelector('.srpanel');
        const notches = [...r.querySelectorAll('.srnotches i')].map((i) => { const b = i.getBoundingClientRect(); return { id: i.getAttribute('data-r'), x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; });
        const floors = [...r.querySelectorAll('[data-floor-label]')].map((f) => { const b = f.getBoundingClientRect(); return { t: f.textContent, x: Math.round(b.left), y: Math.round(b.top) }; });
        const secs = [...R.querySelectorAll('[data-board] section[data-sec]')].filter((e) => !e.getAttribute('data-sec').startsWith('__'));
        const on = secs.find((e) => e.classList.contains('railon'));
        const dim = secs.filter((e) => e !== on && e.offsetHeight > 24).map((e) => parseFloat(getComputedStyle(e).opacity));
        const h2 = on && (on.querySelector('.sechead h2') || on.querySelector('.sechead'));
        const hb = h2 && h2.getBoundingClientRect();
        const ring = on ? getComputedStyle(on.querySelector('.secbg')).boxShadow : '';
        return {
          top: P.$('.scroll').scrollTop, jumps: P.railJumps || 0, open: r.classList.contains('open'),
          width: panel ? panel.getBoundingClientRect().width : 0,
          text: r.innerText.replace(/\s+/g, ' ').trim(),
          title: !!r.querySelector('[title]') || r.hasAttribute('title'),
          notches, floors, on: on ? on.getAttribute('data-sec') : '',
          titleY: hb ? hb.top + hb.height / 2 : null,
          ring, dimMax: dim.length ? Math.max(...dim) : 1, dimMin: dim.length ? Math.min(...dim) : 1,
          bubble: r.querySelector('.srtip') && !r.querySelector('.srtip').hidden ? r.querySelector('.srtip').innerText.trim() : '',
        };
      });
      // Nothing of the rail is over the page while it rests.
      const over = await p.evaluate(() => { const r = window.__panel.shadowRoot.querySelector('[data-rail]').getBoundingClientRect(); return [...window.__panel.shadowRoot.querySelectorAll('[data-sec], .wrap > *')].filter((e) => { const b = e.getBoundingClientRect(); return b.width && b.right > r.left + 0.5 && b.bottom > r.top && b.top < r.bottom; }).map((e) => e.getAttribute('data-sec') || e.className || e.tagName).slice(0, 4); });
      if (over.length) fail(where, `the rail lies over the page: ${over.join(', ')}`);
      // The rail is a column of notches: one per room, vertical rectangles,
      // and never a list of room names.
      const b0 = await state();
      if (b0.notches.length < 3) fail(where, `the rail does not draw a notch per room (${b0.notches.length})`);
      if (b0.notches.some((n) => n.h <= n.w)) fail(where, `a notch is not a vertical rectangle (${JSON.stringify(b0.notches.slice(0, 3))})`);
      if (b0.text) fail(where, `the resting rail carries words (${b0.text.slice(0, 80)})`);
      await shot(p, `rail-closed-${name}`);
      // A vertical swipe that starts on the rail scrolls the page.
      const pts = [[rx, 640]]; for (let i = 1; i <= 12; i++) pts.push([rx + (i % 2), 640 - i * 30]);
      const sw = await touchPath(p, pts, 16);
      await sw.end();
      await settle(p, 700);
      const b1 = await state();
      if (b1.top - b0.top < 80) fail(where, `a vertical swipe on the rail did not scroll the page (${b0.top} → ${b1.top})`);
      if (b1.jumps !== b0.jumps || b1.open) fail(where, 'a vertical swipe on the rail jumped to a room or opened the rail');
      await p.evaluate(() => { window.__panel.$('.scroll').scrollTop = 0; });
      await settle(p, 400);
      // Resting on it says what to do.
      const rest = await touchPath(p, [[rx, 420]], 16, 400);
      const r1 = await state();
      if (!/Pull left to open the rooms/.test(r1.text)) fail(where, `resting on the rail does not say "Pull left to open the rooms" (${r1.text.slice(0, 80)})`);
      await rest.end();
      await settle(p, 300);
      const r2 = await state();
      if (!/A little further left, then slide up or down to a room/.test(r2.text)) fail(where, `a tap on the rail leaves no hint (${r2.text.slice(0, 80)})`);
      if (r2.jumps !== b0.jumps || r2.open) fail(where, 'a tap on the rail jumped to a room');
      await settle(p, 2600);
      const r3 = await state();
      if (/A little further left/.test(r3.text)) fail(where, 'the rail\'s hint does not go away');
      // A short pull: the rail follows the finger, with ratchet ticks, and
      // does not open yet.
      await p.evaluate(() => { window.__haptics = []; window.addEventListener('haptic', (e) => window.__haptics.push(e.detail)); });
      const fy = 420;
      const pull = await touchPath(p, [[rx, fy], [rx - 3, fy], [rx - 6, fy], [rx - 10, fy]], 30);
      const r4 = await state();
      if (!/Keep pulling left/.test(r4.text)) fail(where, `a pull does not say "Keep pulling left" (${r4.text.slice(0, 80)})`);
      if (!(r4.width > b0.width + 2)) fail(where, `the rail does not follow a pull (${b0.width} → ${r4.width})`);
      if (r4.open) fail(where, 'a 10px pull already opened the rail');
      const tick = await p.evaluate(() => window.__haptics.slice());
      if (tick.filter((k) => k === 'selection').length < 2) fail(where, `the pull gave no ratchet ticks (${JSON.stringify(tick)})`);
      // ...on to 16px: open, a heavy tap; wider, still, floor names beside.
      for (const x of [rx - 12, rx - 16]) { await pull.cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: fy }] }); await p.waitForTimeout(30); }
      const r5 = await state();
      if (!r5.open) fail(where, 'a 16px pull left did not open the rail');
      const hap = await p.evaluate(() => window.__haptics.slice());
      if (!hap.includes('heavy')) fail(where, `opening the rail gave no heavy haptic (${JSON.stringify(hap)})`);
      if (!(r5.width > b0.width + 8)) fail(where, `the open rail is not wider (${b0.width} → ${r5.width})`);
      if (r5.floors.length < 2) fail(where, `the open rail does not name the floors beside it (${JSON.stringify(r5.floors)})`);
      if (r5.bubble) fail(where, `the open rail shows a room name or a tip by the finger (${r5.bubble})`);
      // Without lifting: down the rail, room to room.
      let maxOff = 0, scrubs = 0;
      const offs = [];
      const notchY = r5.notches.map((n) => n.y + n.h / 2);
      // Visit a room in the middle of the screen, then rooms further down.
      const aims = notchY.filter((y) => y > 300 && y < 560).slice(0, 3);
      for (const y of aims) {
        for (let k = 1; k <= 4; k++) { await pull.cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: rx - 16, y: Math.round(fy + (y - fy) * k / 4) }] }); await p.waitForTimeout(16); }
        await settle(p, 700);
        const m = await state();
        scrubs++;
        if (m.open !== true) fail(where, 'the rail closed while the finger was still down');
        if (!m.on) { fail(where, `sliding to a notch at ${Math.round(y)} lit no room`); continue; }
        if (!/inset/.test(m.ring) || m.ring === 'none') fail(where, `the room the rail is on is not ringed (${m.ring})`);
        if (m.dimMax > 0.6) fail(where, `the other rooms are not dimmed while scrubbing (opacity up to ${m.dimMax})`);
        if (JSON.stringify(m.floors) !== JSON.stringify(r5.floors)) fail(where, `the floor names moved while scrubbing (${JSON.stringify(r5.floors)} → ${JSON.stringify(m.floors)})`);
        const still = JSON.stringify(m.notches.map((n) => [n.x, n.w])) === JSON.stringify(r5.notches.map((n) => [n.x, n.w]));
        if (!still) fail(where, 'the notches move sideways or scale while the rail is open');
        if (Math.abs(m.width - r5.width) > 0.5) fail(where, `the open rail changes width while scrubbing (${r5.width} → ${m.width})`);
        const off = Math.abs(m.titleY - y);
        offs.push(Math.round(off)); maxOff = Math.max(maxOff, off);
      }
      await shot(p, `rail-open-${name}`);
      if (!scrubs) fail(where, 'no notch to slide to in the middle of the screen');
      if (maxOff > 15) fail(where, `the room's title is not level with the finger while scrubbing (off by ${offs.join(', ')}px)`);
      const r6 = await state();
      if (r6.jumps <= b0.jumps) fail(where, 'sliding the opened rail did not go to a room');
      if (r6.top <= 0) fail(where, 'sliding the opened rail did not move the page');
      await pull.end();
      await settle(p, 300);
      const r7 = await state();
      if (r7.open) fail(where, 'the rail stays open after the finger lifts');
      if (r7.floors.length) fail(where, 'the floor names stay after the finger lifts');
      if (Math.abs(r7.width - b0.width) > 0.5) fail(where, `the rail does not close to its resting width (${r7.width})`);
      if (r7.dimMin < 0.9) fail(where, `the other rooms stay dimmed after the finger lifts (${r7.dimMin})`);
      const hap2 = await p.evaluate(() => window.__haptics.slice());
      if (hap2[hap2.length - 1] !== 'light') fail(where, `landing gave no light haptic (${JSON.stringify(hap2)})`);
      await shot(p, `rail-landed-${name}`);
      await settle(p, 1200);
      const r8 = await state();
      if (r8.on) fail(where, 'the landed room keeps its ring');
      if (r1.title || r4.title || r5.title) fail(where, 'the rail\'s tip is a title tooltip');
    }
  }
  const sw = await snapshot(p);
  if (sw.sideways) fail(where, 'the page scrolls sideways');
  if (errors.length) fail(where, `page errors: ${errors.slice(0, 2).join(' | ')}`);
  await ctx.close();
}

// The house reports of 2026-11-04 (#662 #664 #676 #677 #678 #679 #682), one
// class each, driven here on a second example the report never named:
//   * Then mode is gone: Coming up cannot be slid into the past;
//   * with the greeting, story and Ask off, no empty region takes a gap and
//     the first card sits near brAIn's header, Edit still reachable;
//   * the story never says everything is locked or at rest over an open
//     door, a window or a garage door;
//   * no form control is under 16px on a phone, in a card's own shadow root
//     too;
//   * every card id in the dashboard is on screen, a card with nothing to
//     show says so, and none is a tile of no height;
//   * small capital labels are 4.5:1 against what they sit on, in all three
//     themes, and Home Assistant's light mode draws the light theme;
//   * every button Morph draws shows an icon or words and has a name.
for (const [w, h, name] of W([[1200, 860, 'wide'], [390, 844, 'phone']])) {
  const touch = name === 'phone';
  const where = `reports ${name}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
  await route(ctx, { narrow: touch, shell: true });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 2000);
  await p.evaluate(() => {
    customElements.define('mx-test-say', class extends HTMLElement {
      setConfig(c) { this.c = c; if (!this.shadowRoot) { this.attachShadow({ mode: 'open' }).innerHTML = '<input class="say" type="text" placeholder="Say something" style="font-size:15px"><textarea style="font-size:14px"></textarea>'; } }
    });
    customElements.define('mx-test-none', class extends HTMLElement { setConfig(c) { this.c = c; } });
    const P = window.__panel;
    P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false };
    const d = JSON.parse(JSON.stringify(P.dash));
    const yard = d.floors.flatMap((f) => f.sections).find((x) => x.id === 's_yard');
    yard.groups[0].cards.push({ id: 'c_say', type: 'lovelace', card: { type: 'custom:mx-test-say' } }, { id: 'c_nothing', type: 'lovelace', card: { type: 'custom:mx-test-none' } }, { id: 'c_pause2', type: 'switch', entity: 'input_boolean.guest_mode', name: 'Pause 2', options: { header: true } });
    P.dash = d; P._secEnts = null; P._watch = null; P._forceApply = true; P.engine.invalidate(); P.schedule();
  });
  await settle(p, 2200);

  // #677: no form control under 16px on a phone, anywhere (a card's own shadow root too).
  if (touch) {
    const small = await p.evaluate(() => {
      const deep = (r) => [...r.querySelectorAll('*')].flatMap((el) => [el, ...(el.shadowRoot ? deep(el.shadowRoot) : [])]);
      return deep(window.__panel.shadowRoot).filter((el) => /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) && !/^(range|checkbox|radio|hidden|color)$/.test(el.type))
        .map((el) => ({ n: `${el.tagName.toLowerCase()}.${String(el.className || '').split(' ')[0]}`, fs: parseFloat(getComputedStyle(el).fontSize) })).filter((x) => x.fs < 16);
    });
    if (small.length) fail(where, `#677: form controls under 16px zoom a phone on focus: ${small.map((x) => `${x.n} ${x.fs}px`).join(', ')}`);
    const n = await p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_say"]'); const c = t && t.querySelector('[data-ll]').firstElementChild; return c && c.shadowRoot ? c.shadowRoot.querySelectorAll('input,textarea').length : 0; });
    if (!n) fail(where, '#677: the test card with a text box in its own shadow root was not drawn');
  }

  // #678: every card id is on screen with a size, or says it has nothing to show.
  {
    const gone = await p.evaluate(() => {
      const P = window.__panel; const R = P.shadowRoot; const ids = [];
      const seek = (o) => { if (!o || typeof o !== 'object') return; if (typeof o.id === 'string' && o.type && !o.groups && !o.sections) ids.push(o.id); Object.values(o).forEach(seek); };
      seek(P.dash.floors);
      return ids.filter((id) => {
        const el = R.querySelector(`[data-tile="${CSS.escape(id)}"]`) || R.querySelector(`[data-card="${CSS.escape(id)}"]`);
        const r = el && el.getBoundingClientRect();
        return !(r && r.width > 0 && r.height > 0);
      });
    });
    if (gone.length) fail(where, `#678: cards listed in the dashboard that are not on screen: ${gone.join(', ')}`);
    const none = await p.evaluate(() => { const t = window.__panel.shadowRoot.querySelector('[data-tile="c_nothing"]'); return t ? { text: t.textContent.trim(), h: t.getBoundingClientRect().height } : null; });
    if (!none || !/nothing to show/i.test(none.text) || none.h < 20) fail(where, `#678: a card with nothing to draw does not say so (${JSON.stringify(none)})`);
  }

  // #679: small capital labels are 4.5:1 in every theme; Home Assistant's light mode is the light theme.
  {
    for (const th of ['dark', 'medium', 'light']) {
      await p.evaluate((th) => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: th }; P.schedule(); }, th);
      await settle(p, 700);
      const low = await p.evaluate(() => {
        const R = window.__panel.shadowRoot;
        const cv = document.createElement('canvas'); cv.width = cv.height = 1; const g = cv.getContext('2d', { willReadFrequently: true });
        const parse = (c) => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = c; g.fillRect(0, 0, 1, 1); const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
        const bgOf = (el) => { const chain = []; for (let e = el; e; e = e.parentElement || (e.getRootNode() && e.getRootNode().host)) chain.push(e); let base = [255, 255, 255]; for (const e of chain.reverse()) { const c = parse(getComputedStyle(e).backgroundColor); if (c[3] > 0) base = base.map((b, i) => b * (1 - c[3]) + c[i] * c[3]); } return base; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
        const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
        const out = [];
        R.querySelectorAll('*').forEach((el) => {
          if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) || el.closest('[data-ll]')) return;
          const cs = getComputedStyle(el);
          if (cs.textTransform !== 'uppercase' && !(parseFloat(cs.fontSize) <= 13 && parseFloat(cs.letterSpacing) > 0)) return;
          const fg = parse(cs.color); const bg = bgOf(el);
          const f = fg.slice(0, 3).map((v, i) => v * fg[3] + bg[i] * (1 - fg[3]));
          const r = ratio(f, bg);
          if (r < 4.5) out.push(`${el.textContent.trim().slice(0, 18)} ${r.toFixed(2)}:1`);
        });
        return { cls: R.querySelector('[data-morph-root]').className, low: out };
      });
      if (!low.cls.includes('t-' + th)) fail(where, `#679: theme ${th} was not drawn (${low.cls})`);
      if (low.low.length) fail(where, `#679: ${th}: small labels under 4.5:1: ${low.low.join(', ')}`);
    }
    await p.evaluate(() => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: 'auto' }; P.hass = { ...P.hass, themes: { darkMode: false } }; P.schedule(); });
    await settle(p, 700);
    const cl = await p.evaluate(() => window.__panel.shadowRoot.querySelector('[data-morph-root]').className);
    if (!/t-light/.test(cl)) fail(where, `#679: Home Assistant's light mode draws the dark palette (${cl})`);
    await p.evaluate(() => { const P = window.__panel; P.hass = { ...P.hass, themes: { darkMode: true } }; P.schedule(); });
    await settle(p, 500);
  }

  // #682: every button Morph draws shows an icon or words and has a name.
  {
    const bare = await p.evaluate(() => {
      const R = window.__panel.shadowRoot;
      return [...R.querySelectorAll('button, [role="button"]')].filter((b) => !b.closest('[data-ll]') && b.getBoundingClientRect().width > 0).filter((b) => {
        const shows = b.textContent.trim() || b.querySelector('svg, img, i, span[style*="background"]');
        const named = b.textContent.trim() || b.getAttribute('aria-label');
        return !shows || !named;
      }).map((b) => `${b.className || b.tagName}${b.dataset.act ? '[' + b.dataset.act + ']' : ''}`);
    });
    if (bare.length) fail(where, `#682: buttons with no icon or words, or no name: ${[...new Set(bare)].join(', ')}`);
  }

  // #662: Coming up stops at now. Drag the strip toward the past: it stays at now.
  {
    const vp = await p.evaluate(() => { const v = window.__panel.shadowRoot.querySelector('[data-upc-vp]'); if (!v) return null; v.scrollIntoView({ block: 'center' }); const r = v.getBoundingClientRect(); return { x: r.left + r.width * 0.5, y: r.top + r.height / 2 }; });
    if (!vp) fail(where, '#662: there is no Coming up strip');
    else {
      await settle(p, 400);
      const v2 = await p.evaluate(() => { const v = window.__panel.shadowRoot.querySelector('[data-upc-vp]'); const r = v.getBoundingClientRect(); return { x: r.left + r.width * 0.5, y: r.top + r.height / 2 }; });
      await p.mouse.move(v2.x, v2.y); await p.mouse.down();
      for (let i = 1; i <= 12; i++) { await p.mouse.move(v2.x + i * 25, v2.y); await p.waitForTimeout(20); }
      await p.mouse.up();
      await settle(p, 900);
      const st = await p.evaluate(() => { const P = window.__panel; return { at: P.s.upcAt, then: P.shadowRoot.querySelector('[data-morph-root]').classList.contains('then'), rule: !!P.shadowRoot.querySelector('.thenrule'), setThen: typeof P.setThen, hv: typeof P.hassView, min: P._upc && P._upc.minC, now: Date.now() }; });
      if (st.at != null && st.at < st.now - 90000) fail(where, `#662: Coming up was slid into the past (${new Date(st.at).toISOString()})`);
      if (st.then || st.rule || st.setThen !== 'undefined' || st.hv !== 'undefined') fail(where, `#662: Then mode is still in the page (${JSON.stringify(st)})`);
      if (st.min != null && st.min < 0) fail(where, `#662: the strip reaches ${st.min} minutes into the past`);
      await p.evaluate(() => window.__panel.shadowRoot.querySelector('.cu-back') && window.__panel.shadowRoot.querySelector('.cu-back').click());
    }
  }

  // #676: the story never says everything is locked or at rest over an open door.
  {
    const said = await p.evaluate(async () => {
      const P = window.__panel; const H = P.hass; const states = { ...H.states };
      // The words a person reads, from the markup the story would draw.
      const words = (html) => { const t = document.createElement('template'); t.innerHTML = html; return t.content.textContent; };
      const put = (eid, state, attrs) => { states[eid] = { entity_id: eid, state, attributes: attrs, last_changed: new Date(Date.now() - 6 * 3600000).toISOString(), last_updated: new Date().toISOString() }; };
      const out = {};
      // Locks locked, a garage door and a window open, nobody home: the away line.
      Object.keys(states).filter((e) => e.startsWith('lock.')).forEach((e) => { states[e] = { ...states[e], state: 'locked' }; });
      put('binary_sensor.spare_window', 'on', { device_class: 'window', friendly_name: 'Spare Window' });
      put('cover.shed_door', 'open', { device_class: 'garage', friendly_name: 'Shed Door' });
      P.hass = { ...H, states }; P.form_ = 'away';
      const html = P.verdictHtml(P.dash);
      out.away = words(html);
      P.form_ = '';
      out.plain = words(P.verdictHtml(P.dash));
      P.brain().situation = { sentence: 'Every door is locked and the house is quiet.', at: Date.now() / 1000 };
      out.sit = words(P.verdictHtml(P.dash));
      // And with nothing open the same words may stand.
      delete states['binary_sensor.spare_window']; delete states['cover.shed_door'];
      P.hass = { ...H, states };
      out.shut = words(P.verdictHtml(P.dash));
      P.hass = H; P.schedule();
      return out;
    });
    const claim = /\b(everything|every door|all doors?)\b[^.]*\b(locked|closed|shut|secure|at rest)/i;
    for (const k of ['away', 'plain', 'sit']) if (claim.test(said[k]) && !/Spare Window|Shed Door/.test(said[k])) fail(where, `#676: the story claims all is shut over an open door (${k}: "${said[k]}")`);
    if (!/Spare Window is open/.test(said.away) || /Everything is locked/.test(said.away)) fail(where, `#676: the away story does not name the open window ("${said.away}")`);
    if (/Every door is locked/.test(said.sit)) fail(where, `#676: a sentence claiming every door is locked was shown over an open one ("${said.sit}")`);
  }

  // #719 #734: brAIn's sentence is checked against the doors as they are now.
  {
    const said = await p.evaluate(async () => {
      const P = window.__panel; const H = P.hass; const states = {};
      const words = (html) => { const t = document.createElement('template'); t.innerHTML = html; return t.content.textContent; };
      Object.entries(H.states).forEach(([e, s]) => { if (!/^(lock|cover|binary_sensor)\./.test(e)) states[e] = s; });
      const put = (eid, state, attrs) => { states[eid] = { entity_id: eid, state, attributes: attrs, last_changed: new Date(Date.now() - 6 * 3600000).toISOString(), last_updated: new Date().toISOString() }; };
      put('lock.claims_front', 'locked', { friendly_name: 'Front Door Lock' });
      put('cover.claims_garage', 'closed', { device_class: 'garage', friendly_name: 'Garage Door' });
      // Nothing salient, so the story is brAIn's sentence (or the away line).
      const verdict = P.verdict; P.verdict = () => [];
      P.hass = { ...H, states }; P.form_ = '';
      const say = (sentence) => { P.brain().situation = { sentence, at: Date.now() / 1000 }; return words(P.verdictHtml(P.dash)); };
      const out = {};
      out.unlocked = say('The front door is still unlocked.');
      out.garage = say('Close the garage before bed.');
      out.battery = say('The front door lock battery is low.');
      out.past = say('The front door was unlocked at 3 pm, now locked.');
      put('lock.claims_back', 'unlocked', { friendly_name: 'Back Door Lock' });
      P.hass = { ...H, states };
      out.all = say('All doors are locked.');
      P.form_ = 'away'; out.away = words(P.verdictHtml(P.dash)); P.form_ = '';
      P.verdict = verdict; P.hass = H; P.schedule();
      return out;
    });
    if (/unlocked/.test(said.unlocked)) fail(where, `#719: the story says a locked lock is unlocked ("${said.unlocked}")`);
    if (/Close the garage/.test(said.garage)) fail(where, `#734: the story says to close a closed garage ("${said.garage}")`);
    if (!/battery is low/.test(said.battery)) fail(where, `#719: a battery sentence about a locked lock was hidden ("${said.battery}")`);
    if (!/now locked/.test(said.past)) fail(where, `#719: a past unlock that ends locked was hidden ("${said.past}")`);
    if (/All doors are locked/.test(said.all)) fail(where, `#719: "All doors are locked" over an unlocked lock ("${said.all}")`);
    if (/Everything is locked/.test(said.away) || !/Back Door Lock is unlocked/.test(said.away)) fail(where, `#719: the away line does not name the unlocked lock ("${said.away}")`);
  }
  await ctx.close();

  // #664: with the greeting, story and Ask off and no clock, no empty region
  // takes a gap, the first card is near brAIn's header and Edit is reachable.
  {
    const ctx2 = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
    await route(ctx2, { narrow: touch, shell: true });
    const p2 = await ctx2.newPage();
    await p2.goto(ORIGIN + '/');
    await p2.waitForFunction(() => window.__panel && window.__panel.data);
    await settle(p2, 1800);
    await p2.evaluate(() => {
      const P = window.__panel; const d = JSON.parse(JSON.stringify(P.dash));
      d.greeting = false; d.story = false; d.ask = false; d.coming_up = false; d.scenes = [];
      P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false };
      P.dash = d; P._forceApply = true; P.engine.invalidate(); P.schedule();
    });
    await settle(p2, 1800);
    await shot(p2, `no-top-${name}`);
    const g = await p2.evaluate(() => {
      const P = window.__panel; const R = P.shadowRoot; const host = P.getBoundingClientRect();
      const kids = [...R.querySelector('.wrap').children].filter((c) => c.hasAttribute('data-region'));
      const empties = kids.filter((c) => !c.hidden && c.getBoundingClientRect().height < 1 && getComputedStyle(c).display !== 'none').map((c) => c.getAttribute('data-region'));
      const first = [...R.querySelectorAll('section.sec, .flh')].filter((e) => e.getBoundingClientRect().height > 0).map((e) => e.getBoundingClientRect().top).sort((a, b) => a - b)[0];
      const edit = R.querySelector('[data-act="edit"]'); const eb = edit && edit.getBoundingClientRect();
      const hit = eb ? R.elementFromPoint(eb.left + eb.width / 2, eb.top + eb.height / 2) : null;
      const rooms = R.querySelector('[data-region="rooms"]'); const rb = rooms && !rooms.hidden && getComputedStyle(rooms).display !== 'none' ? rooms.getBoundingClientRect() : null;
      return { empties, gap: first - (rb ? rb.bottom : host.top), roomline: !!rb, pencilOverRooms: !!(eb && R.querySelector('.roomline') && (() => { const r = R.querySelector('.roomline').getBoundingClientRect(); return r.right > eb.left && r.left < eb.right && r.bottom > eb.top && r.top < eb.bottom; })()), edit: !!eb && eb.width > 0, reach: !!(hit && (hit === edit || edit.contains(hit))), top: R.querySelector('[data-region="top"]').hidden };
    });
    if (!g.top) fail(`reports ${name}`, '#664: the top region is drawn with nothing in it');
    if (g.empties.length) fail(`reports ${name}`, `#664: empty regions that are not hidden: ${g.empties.join(', ')}`);
    if (g.pencilOverRooms) fail(`reports ${name}`, '#664: the Edit pencil sits on top of the room line');
    if (g.gap > 34) fail(`reports ${name}`, `#664: the first card is ${g.gap.toFixed(0)}px below brAIn's header with nothing on top (limit 34)`);
    if (!g.edit || !g.reach) fail(`reports ${name}`, `#664: Edit is not reachable with nothing on top (${JSON.stringify(g)})`);
    await ctx2.close();
  }
  if (errors.length) fail(where, `page errors: ${errors.slice(0, 2).join(' | ')}`);
}

// ------------------------------------------------------------------
// The layout batch of 2026-11-07: eight things a house reported, each one a
// CLASS (every card kind that draws the same way), measured on the batch
// floor of the fixture at 390 with touch and at 1200.
for (const [w, h, name] of W([[1200, 860, 'wide'], [390, 844, 'phone']])) {
  const touch = name === 'phone';
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
  await route(ctx, { narrow: touch, batch: true });
  // A person's photo and a camera's picture that do not load.
  await ctx.route(`${ORIGIN}/local/**`, (r) => r.fulfill({ status: 404, body: '' }));
  await ctx.route(`${ORIGIN}/api/camera_proxy/camera.porch_cam*`, (r) => r.fulfill({ status: 404, body: '' }));
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await p.waitForFunction(() => window.__panel && window.__panel.data);
  await settle(p, 1500);
  await p.evaluate(() => { window.__panel.data.state.settings = { ...(window.__panel.data.state.settings || {}), fold_rooms: false }; window.__panel._forceApply = true; window.__panel.engine.invalidate(); window.__panel.schedule(); });
  await settle(p, 2200);
  const at = `layout batch ${name}`;
  const grab = async (id, file) => {
    await p.evaluate((id) => { const el = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`); if (el) el.scrollIntoView({ block: 'center' }); }, id);
    await settle(p, 500);
    await shot(p, `${file}-${name}`);
  };
  const facts = await p.evaluate(() => {
    const root = window.__panel.shadowRoot;
    const R = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
    const hit = (e) => { const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2; const top = root.elementFromPoint(x, y); return !!top && (top === e || e.contains(top) || top.contains(e)); };
    const tile = (id) => root.querySelector(`[data-tile="${id}"]`);
    const sect = (id) => root.querySelector(`[data-sec="${id}"]`);
    const overlap = (a, b) => Math.min(a.r, b.r) - Math.max(a.l, b.l) > 1 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 1;
    const clipped = (e) => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1;
    const out = { vw: window.innerWidth, coarse: matchMedia('(pointer:coarse)').matches };
    // 1. The climate card's controls: none overlaps another or is caught by the tile's edge.
    const cl = tile('cb_clim'); cl.scrollIntoView({ block: 'center' });
    const ctl = [...cl.querySelectorAll('button')].filter((b) => b.getBoundingClientRect().width > 0);
    out.climate = { n: ctl.length, overlaps: [], caught: [], short: [] };
    ctl.forEach((a, i) => { ctl.slice(i + 1).forEach((b) => { if (overlap(R(a), R(b))) out.climate.overlaps.push(`${a.getAttribute('aria-label') || a.textContent.trim()} x ${b.getAttribute('aria-label') || b.textContent.trim()}`); }); if (!hit(a)) out.climate.caught.push(a.getAttribute('aria-label') || a.textContent.trim()); });
    // A routine's chip sits clear of the ruler, the humidity line and the tile's own edge.
    const box = cl.querySelector('.box'); const ruler = cl.querySelector('.ruler');
    out.climate.crowd = [];
    [...cl.querySelectorAll('.cl-acts .wd')].forEach((c) => {
      const cr = R(c);
      if (ruler && overlap(cr, R(ruler))) out.climate.crowd.push(`${c.textContent.trim()} sits on the ruler`);
      [...cl.querySelectorAll('.box > .row.small span')].forEach((hs) => { if (overlap(cr, R(hs))) out.climate.crowd.push(`${c.textContent.trim()} sits on "${hs.textContent.trim()}"`); });
      if (box && cr.b > R(box).b - 3) out.climate.crowd.push(`${c.textContent.trim()} touches the tile's bottom edge`);
    });
    // 2 + 8. Strips: the subtitle is whole and starts beside the icon, never under it; an action word is whole and inside its strip.
    out.strips = [];
    ['cb_bed', 'cb_media', 'cb_movie', 'cb_l1', 'cb_l2', 'cb_l3'].forEach((id) => {
      const t = tile(id); t.scrollIntoView({ block: 'center' });
      const st = t.querySelector('.strip'); const nv = t.querySelector('.nv'); const ic = t.querySelector('.sline > svg'); const act = t.querySelector('.actword');
      const sub = nv.querySelector('span');
      out.strips.push({ id, sub: sub.textContent, subClipped: clipped(sub), underIcon: ic ? R(sub).l < R(ic).r - 1 : false, act: act ? act.textContent : '', actClipped: act ? clipped(act) || R(act).r > R(st).r + 0.5 || R(act).l < R(nv).r - 1 : false, tile: R(t) });
    });
    out.stripOverlaps = [];
    const sr = ['cb_l1', 'cb_l2', 'cb_l3', 'cb_bed', 'cb_media', 'cb_movie'].map((id) => [id, R(tile(id))]);
    sr.forEach((a, i) => sr.slice(i + 1).forEach((b) => { if (overlap(a[1], b[1])) out.stripOverlaps.push(`${a[0]} x ${b[0]}`); }));
    // 3. Two sections of one width share a width and a left edge; a group's label never lands on another's.
    const o = R(sect('s_b_over')), s = R(sect('s_b_sec'));
    out.sections = { over: o, sec: s };
    out.labels = [];
    ['s_b_over', 's_b_sec'].forEach((sid) => { const labs = [...sect(sid).querySelectorAll('.glab')]; labs.forEach((a, i) => labs.slice(i + 1).forEach((b) => { if (overlap(R(a), R(b))) out.labels.push(`${a.textContent.trim()} x ${b.textContent.trim()}`); })); });
    // 4. Cameras: the name, and a state when there is no picture.
    out.cams = ['cb_c1', 'cb_c2', 'cb_c3'].map((id) => { const t = tile(id); t.scrollIntoView({ block: 'center' }); const pic = t.querySelector('.campic'); const img = pic.querySelector('img.cam'); return { id, name: (t.querySelector('.camhead b') || {}).textContent, pic: pic.innerText.trim(), img: !!img, imgOk: !!img && img.complete && img.naturalWidth > 0 }; });
    // 5. Scene chips, every kind that draws them.
    out.chips = [...root.querySelectorAll('.scenes .wd, .secscenes .wd, .scenesline .wd, .cl-acts .wd')].filter((b) => b.getBoundingClientRect().width > 0).map((b) => ({ t: b.textContent.trim(), r: R(b), cls: b.parentElement.className }));
    out.chipGaps = [];
    out.chips.forEach((a, i) => out.chips.slice(i + 1).forEach((b) => { const sameRow = Math.abs(a.r.t - b.r.t) < 6; if (sameRow && Math.min(a.r.r, b.r.r) - Math.max(a.r.l, b.r.l) > -6 && Math.min(a.r.b, b.r.b) - Math.max(a.r.t, b.r.t) > 1) out.chipGaps.push(`${a.t} / ${b.t}`); }));
    // A section with nothing beside it in its band reaches the floor's width, or the width of the section below it.
    const uo = R(sect('s_u_over')), us = R(sect('s_u_sec'));
    out.unequal = { over: uo, sec: us, board: R(root.querySelector('[data-board]')) };
    // A line of facts under a floor's or a room's title wraps; it never ends in an ellipsis.
    out.runOn = [...root.querySelectorAll('.facts, .secmeta')].filter((e) => e.getBoundingClientRect().width > 0 && (clipped(e) || getComputedStyle(e).textOverflow === 'ellipsis')).map((e) => e.textContent.trim().slice(0, 40));
    // 6. The equipment list: no row cut off mid-word, and a count when it is not all shown.
    const eq = tile('cb_equip'); eq.scrollIntoView({ block: 'center' });
    out.equip = { rows: [...eq.querySelectorAll('.lrow')].length, cut: [...eq.querySelectorAll('.lrow *')].filter((e) => getComputedStyle(e).textOverflow === 'ellipsis' && clipped(e)).map((e) => e.textContent.trim()), more: (eq.textContent.match(/\+\d+ more/) || [])[0] || '' };
    // 7. People: an initial in a circle, never a picture's alt text.
    out.people = ['cb_p1', 'cb_p2'].map((id) => { const t = tile(id); t.scrollIntoView({ block: 'center' }); const imgs = [...t.querySelectorAll('img')]; return { id, imgs: imgs.filter((i) => !(i.complete && i.naturalWidth > 0) && getComputedStyle(i).visibility !== 'hidden').length, initial: (t.querySelector('.avatar') || {}).textContent, avatar: t.querySelector('.avatar') ? getComputedStyle(t.querySelector('.avatar')).display : '', text: t.innerText.replace(/\s+/g, ' ').trim() }; });
    return out;
  });
  await grab('cb_clim', 'b2-climate'); await grab('cb_bed', 'b2-strips'); await grab('cb_l2', 'b2-locks'); await grab('cb_p1', 'b2-people'); await grab('cb_c1', 'b2-cams'); await grab('cb_equip', 'b2-equip'); await grab('cb_scenes', 'b2-scenes');
  const cl = facts.climate;
  if (cl.n < 5) fail(at, `1: the climate card draws only ${cl.n} controls`);
  if (cl.overlaps.length) fail(at, `1: climate controls overlap each other: ${cl.overlaps.join(', ')}`);
  if (cl.crowd.length) fail(at, `1: a climate routine chip is crowded: ${cl.crowd.join('; ')}`);
  if (cl.caught.length) fail(at, `1: a climate control's middle is caught by something else (the tile's edge): ${cl.caught.join(', ')}`);
  for (const t of facts.strips) {
    if (t.subClipped) fail(at, `2: ${t.id}'s subtitle "${t.sub}" is cut off`);
    if (t.underIcon) fail(at, `2: ${t.id}'s subtitle starts under its icon`);
    if (t.actClipped) fail(at, `8: ${t.id}'s "${t.act}" button is cut off or crowds its tile's name`);
  }
  if (facts.stripOverlaps.length) fail(at, `8: tiles overlap: ${facts.stripOverlaps.join(', ')}`);
  if (Math.abs(facts.sections.over.w - facts.sections.sec.w) > 2 || Math.abs(facts.sections.over.l - facts.sections.sec.l) > 2) fail(at, `3: House Overview is ${facts.sections.over.w.toFixed(0)}px wide at ${facts.sections.over.l.toFixed(0)} and Security ${facts.sections.sec.w.toFixed(0)}px at ${facts.sections.sec.l.toFixed(0)}`);
  {
    const u = facts.unequal;
    const sameBand = Math.abs(u.over.t - u.sec.t) < 2;
    if (!sameBand && Math.abs(u.over.w - u.board.w) > 2 && Math.abs(u.over.w - u.sec.w) > 2) fail(at, `3: a section alone in its band is ${u.over.w.toFixed(0)}px wide of a ${u.board.w.toFixed(0)}px floor, and the one below it is ${u.sec.w.toFixed(0)}px`);
    if (process.env.MORPH_NUMBERS) console.log(name, 'unequal', JSON.stringify({ over: [u.over.l, u.over.t, u.over.w], sec: [u.sec.l, u.sec.t, u.sec.w], board: u.board.w }));
  }
  if (facts.labels.length) fail(at, `3: group labels overlap: ${facts.labels.join(', ')}`);
  for (const c of facts.cams) {
    if (!c.name) fail(at, `4: ${c.id} does not show its camera's name`);
    if (!c.imgOk && !/offline|unavailable|loading|no picture/i.test(c.pic)) fail(at, `4: ${c.id} (${c.name}) has no picture and says nothing (inside the picture: "${c.pic}")`);
  }
  const floor = 40; // the panel's own touch floor for a .wd (docs/notes/morph.md)
  for (const c of facts.chips) {
    if (c.r.h < floor - 0.5) fail(at, `5: scene chip "${c.t}" in .${c.cls.split(' ')[0]} is ${c.r.w.toFixed(0)}x${c.r.h.toFixed(0)}px, under ${floor}`);
    if (c.r.w < floor - 0.5) fail(at, `5: scene chip "${c.t}" in .${c.cls.split(' ')[0]} is only ${c.r.w.toFixed(0)}px wide, under ${floor}`);
    if (c.r.r > facts.vw + 1 || c.r.l < -1) fail(at, `5: scene chip "${c.t}" runs off the screen (${c.r.l.toFixed(0)}..${c.r.r.toFixed(0)} of ${facts.vw})`);
  }
  if (facts.chipGaps.length) fail(at, `5: scene chips touch their neighbours: ${facts.chipGaps.slice(0, 4).join(', ')}`);
  if (facts.runOn.length) fail(at, `6: a line of facts is cut off with an ellipsis: ${facts.runOn.join(' | ')}`);
  if (facts.equip.cut.length) fail(at, `6: equipment rows are cut off: ${facts.equip.cut.join(' | ')}`);
  if (facts.equip.rows < 7 && !facts.equip.more) fail(at, `6: equipment shows ${facts.equip.rows} of 7 and does not say how many more`);
  for (const q of facts.people) {
    if (q.imgs) fail(at, `7: ${q.id} shows a picture that did not load (${q.imgs}); its text: "${q.text.slice(0, 80)}"`);
    if (!q.initial || q.initial.trim().length !== 1) fail(at, `7: ${q.id} has no initial-letter circle (${q.initial})`);
  }
  if (errors.length) fail(at, `page errors: ${errors.slice(0, 2).join(' | ')}`);
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error(`measure-morph: ${problems.length} problem(s)`);
  problems.forEach((x) => console.error('  - ' + x));
  process.exit(1);
}
console.log('measure-morph: all checks passed');
