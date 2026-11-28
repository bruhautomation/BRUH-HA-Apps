/* Playwright measure for a card's kept versions on Morph's own page.
 *
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome node tests/manual/measure-morph-versions.mjs
 *   SHOTS=/some/folder ...   (screenshots, versions-<width>-<step>.png)
 *
 * Every version brAIn makes of a card is kept (service/versions.py), the
 * card in use among them, and the fixture answers the way morphd does. At a
 * 390px phone (touch: a two-finger tap opens the Tell, a swipe on the
 * versions bar steps, a tap marks a part) and at 1200px (a right click
 * opens it, the arrow keys step, a click marks a part):
 *
 *   * the first Send asks for versions of the card as it is (`versions`,
 *     base: the card's own key); Just do it stays a Tell;
 *   * the answer is ADDED: chips A (in use) · B · C · D, the first new one
 *     drawn IN the card's place with the card's own renderer, and nothing
 *     above the card's room moves; chips, ← → and a swipe switch;
 *   * Use this makes the shown one the card (one `versions_use`, by key,
 *     with the version seen as the card), the others stay, and switching
 *     back is the same press; Undo reverts exactly that one;
 *   * closing and opening the Tell again shows the same set;
 *   * More like this and words in the box each ADD versions of the shown
 *     one (base: its key), never replacing it;
 *   * Mark what's wrong: a tap on a part of the drawn version (here one line's
 *     chip on a readings card) toggles nothing, outlines it, and the words go with a
 *     typed reference (role, entity) for two or three alternatives, added;
 *   * Remove takes a version out (never the one in use) and Put it back
 *     returns it;
 *   * at a full set the cap moves the oldest to Removed and says so, a round
 *     that lands after the person stepped elsewhere does not jump, and Put
 *     back at a full set keeps what it put back;
 *   * a version that needs Home Assistant changes starts a Tell;
 *   * no sideways scroll, every button in the box inside it, 44px targets
 *     on touch, 16px text boxes.
 *
 * Exits non-zero with every failure listed.
 */
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';
import { route, ORIGIN } from './morph-fixture.mjs';

const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const SHOTS = process.env.SHOTS || '';
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });
const CARD = 'c_temps';
const settle = (p, ms) => p.waitForTimeout(ms || 900);
const R = (p, fn, arg) => p.evaluate(fn, arg);

async function shot(p, name, step) {
  if (!SHOTS) return;
  await R(p, (id) => window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`).scrollIntoView({ block: 'start' }), CARD);
  await settle(p, 300);
  await p.screenshot({ path: `${SHOTS}/versions-${name}-${step}.png` });
}

const shown = (p) => R(p, (id) => { const c = window.__panel.versionShown(id); return c ? { type: c.type, name: c.name || '' } : null; }, CARD);
const boxText = (p) => R(p, () => (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '');
const click = (p, sel) => R(p, (sel) => { const b = window.__panel.shadowRoot.querySelector(sel); if (!b) return false; b.click(); return true; }, sel);
const faceText = (p) => R(p, (id) => (window.__panel.shadowRoot.querySelector(`[data-tile="${id}"] [data-face]`) || {}).innerText || '', CARD);
const others = (p) => R(p, (id) => { const P = window.__panel; const top = P.shadowRoot.querySelector('[data-sec]').getBoundingClientRect().top; const sec = P.shadowRoot.querySelector(`[data-tile="${id}"]`).closest('[data-sec]'); const st = sec.getBoundingClientRect().top; return [...P.shadowRoot.querySelectorAll('[data-tile]')].filter((e) => !sec.contains(e) && e.getBoundingClientRect().top < st).slice(-12).map((e) => { const r = e.getBoundingClientRect(); return [e.getAttribute('data-tile'), Math.round(r.left), Math.round(r.top - top)]; }); }, CARD);
const chipList = (p) => R(p, () => [...window.__panel.shadowRoot.querySelectorAll('[data-tell] .vchip')].map((b) => { const r = b.getBoundingClientRect(); return { k: b.dataset.v, t: b.innerText.replace(/\s+/g, ' ').trim(), h: r.height, w: r.width, on: b.getAttribute('aria-pressed'), now: b.classList.contains('now') }; }));
const kept = (p) => R(p, () => { const t = window.__panel.s.tell; return t && t.kept ? { n: t.kept.versions.length, cur: t.kept.current, show: window.__panel.shownKey(t), keys: t.kept.versions.map((v) => v.key) } : null; });
const cardName = (p) => R(p, (id) => { const h = window.__panel.findCard(id); return h && h.card.name; }, CARD);
const lastReq = (p, kind) => R(p, (kind) => window.__ws.filter((m) => m.kind === kind).slice(-1)[0], kind);
const type = (p, words) => R(p, (words) => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); if (!ta) return false; ta.value = words; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); return true; }, words);
const showKey = async (p, key) => { await click(p, `[data-act="ver-show"][data-v="${key}"]`); await settle(p, 400); };

// Everything in the box fits: no button past its right edge, every target
// 44px on touch, every text box 16px.
async function fits(p, name, touch, where) {
  const r = await R(p, () => {
    const box = window.__panel.shadowRoot.querySelector('[data-tell]'); if (!box) return null;
    const b = box.getBoundingClientRect();
    const out = { cut: [], small: [], font: [] };
    box.querySelectorAll('button, input, textarea').forEach((el) => {
      const x = el.getBoundingClientRect(); if (!x.width) return;
      if (x.right > b.right + 1 || x.left < b.left - 1) out.cut.push(el.innerText || el.placeholder || el.tagName);
      if (el.tagName === 'BUTTON' && (x.height < 44 || x.width < 44) && !el.closest('details')) out.small.push(`${(el.innerText || el.getAttribute('aria-label') || '').trim()} ${Math.round(x.width)}x${Math.round(x.height)}`);
      if (el.tagName !== 'BUTTON' && parseFloat(getComputedStyle(el).fontSize) < 16) out.font.push(el.tagName);
    });
    out.sw = document.documentElement.scrollWidth; out.iw = window.innerWidth; out.right = b.right;
    return out;
  });
  if (!r) { fail(name, `${where}: no Tell box`); return; }
  if (r.cut.length) fail(name, `${where}: cut off at the box's edge: ${r.cut.join(' | ')}`);
  if (touch && r.small.length) fail(name, `${where}: under 44px on touch: ${r.small.join(' | ')}`);
  if (r.font.length) fail(name, `${where}: a text box under 16px`);
  if (r.sw > r.iw + 1 || r.right > r.iw + 1) fail(name, `${where}: sideways scroll (${r.sw} > ${r.iw})`);
}

for (const [w, h, name, touch] of [[390, 844, 'phone', true], [1200, 900, 'wide', false]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: touch, isMobile: touch });
  await route(ctx, { narrow: touch });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e)));
  await p.goto(ORIGIN + '/');
  await settle(p, 2500);
  await R(p, () => { window.__panel.data.state.settings = { ...(window.__panel.data.state.settings || {}), fold_rooms: false }; window.__panel._forceApply = true; window.__panel.engine.invalidate(); window.__panel.schedule(); });
  await settle(p, 1500);
  const cdp = await ctx.newCDPSession(p);
  const tap = async (x, y) => {
    if (touch) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] }); await settle(p, 60); await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); } else await p.mouse.click(x, y);
  };

  // Open the card's Tell the way a person does on this screen.
  const c = await R(p, (id) => { const el = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"]`); el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + Math.min(40, r.height / 2) }; }, CARD);
  await settle(p, 400);
  if (touch) {
    const pts = [{ x: c.x - 20, y: c.y, id: 1 }, { x: c.x + 20, y: c.y, id: 2 }];
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts });
    await settle(p, 80);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } else {
    await p.mouse.move(c.x, c.y);
    await p.mouse.click(c.x, c.y, { button: 'right' });
  }
  await settle(p, 1400);
  const t0 = await R(p, () => window.__panel.s.tell && { kind: window.__panel.s.tell.kind, id: window.__panel.s.tell.id });
  if (!t0 || t0.kind !== 'card' || t0.id !== CARD) { fail(name, `the card's Tell did not open (${JSON.stringify(t0)})`); continue; }
  const btns = await R(p, () => [...window.__panel.shadowRoot.querySelectorAll('[data-tell] button')].map((b) => b.textContent.trim()));
  if (!btns.includes('Just do it') || !btns.includes('Send for versions')) fail(name, `the box has no Just do it / Send for versions: ${btns.join(' | ')}`);
  let k = await kept(p);
  if (!k || k.n !== 1 || k.cur !== 'k0') fail(name, `the card as it is is not the one kept version: ${JSON.stringify(k)}`);
  await fits(p, name, touch, 'first open');
  await shot(p, name, '0-open');
  await settle(p, 800);
  const before = await others(p);

  // Send: versions of the card as it is, added to the set.
  await type(p, 'Make this simpler');
  await click(p, '[data-act="tell-send"]');
  await settle(p, 600);
  const req = await lastReq(p, 'versions');
  if (!req || req.payload.target.id !== CARD || req.payload.text !== 'Make this simpler' || !req.payload.base || req.payload.base.key !== 'k0' || req.payload.base.how !== 'new') fail(name, `Send did not ask for versions of the card: ${JSON.stringify(req && req.payload)}`);
  if (await R(p, () => window.__ws.some((m) => m.kind === 'tell'))) fail(name, 'Send also started a single-change Tell');
  await shot(p, name, '1-working');
  await settle(p, 3000);
  k = await kept(p);
  if (!k || k.n !== 4 || k.cur !== 'k0' || k.show !== 'k1') fail(name, `the round's versions were not added to the set, first one shown: ${JSON.stringify(k)}`);
  let v = await shown(p);
  if (!v || v.type !== 'sensor' || v.name !== 'Kitchen') fail(name, `version B is not drawn in the card's place: ${JSON.stringify(v)}`);
  if (!/Kitchen/.test(await faceText(p))) fail(name, 'the card face does not show version B');
  let chips = await chipList(p);
  if (chips.length !== 4 || !/^A ?in use Original/.test(chips[0].t) || !chips[0].now || !/^B Kitchen only/.test(chips[1].t)) fail(name, `chips are not A (in use) · B · C · D: ${JSON.stringify(chips.map((x) => x.t))}`);
  if (touch && chips.some((x) => x.h < 44 || x.w < 44)) fail(name, `a chip is under 44px on touch: ${JSON.stringify(chips)}`);
  if (!/left out/.test(await boxText(p))) fail(name, 'the dropped version is not said');
  const after = await others(p);
  const moved = (x, y) => !y || x[0] !== y[0] || Math.abs(x[1] - y[1]) > 2 || Math.abs(x[2] - y[2]) > 2;
  if (before.some((x, i) => moved(x, after[i]))) fail(name, `cards above the card's room moved while a version was shown: ${JSON.stringify(before.map((x, i) => [x, after[i]]).filter(([x, y]) => moved(x, y)).slice(0, 3))}`);
  await fits(p, name, touch, 'after a round');
  await shot(p, name, '2-B');

  // Chip C.
  await showKey(p, 'k2');
  v = await shown(p);
  if (!v || v.type !== 'readings' || v.name !== 'Inside') fail(name, `chip C did not draw version C: ${JSON.stringify(v)}`);
  if (!/Just the rooms people live in/.test(await boxText(p))) fail(name, 'the shown version\'s idea line is missing');
  if (!/Asked: “Make this simpler”/.test(await boxText(p))) fail(name, 'the shown version does not say what it was asked with');

  // Step to D: a swipe on touch, the arrow key with a mouse.
  if (touch) {
    const bar = await R(p, () => { const r = window.__panel.shadowRoot.querySelector('[data-vswipe] .vchips').getBoundingClientRect(); return { x: r.left + r.width * 0.75, y: r.top + r.height / 2 }; });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: bar.x, y: bar.y, id: 1 }] });
    for (let i = 1; i <= 6; i++) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: bar.x - i * 25, y: bar.y + 2, id: 1 }] }); await settle(p, 16); }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } else {
    await R(p, () => window.__panel.shadowRoot.activeElement && window.__panel.shadowRoot.activeElement.blur());
    await p.keyboard.press('ArrowRight');
  }
  await settle(p, 500);
  v = await shown(p);
  if (!v || v.name !== 'House average') fail(name, `${touch ? 'a swipe' : 'ArrowRight'} did not step to version D: ${JSON.stringify(v)}`);
  if (!/Needs in Home Assistant, made only if you use it/.test(await boxText(p))) fail(name, 'version D does not say what it needs from Home Assistant');
  await shot(p, name, '3-D-needs');
  await click(p, '[data-act="ver-step"][data-v="1"]');
  await settle(p, 400);
  if (await shown(p)) fail(name, 'stepping past D did not come back to A, the card as it is');
  if (await R(p, () => !!window.__panel.shadowRoot.querySelector('[data-tell] [data-act="ver-use"], [data-tell] [data-act="ver-remove"]'))) fail(name, 'the version in use offers Use this or Remove');
  if (!touch) { await p.keyboard.press('ArrowLeft'); await settle(p, 300); if ((await shown(p) || {}).name !== 'House average') fail(name, 'ArrowLeft did not step back to D'); }

  // Use this on C: the card, one write; the others stay.
  await showKey(p, 'k2');
  await click(p, '[data-act="ver-use"]');
  await settle(p, 1200);
  let use = await R(p, () => window.__ws.filter((m) => m.kind === 'versions_use'));
  if (use.length !== 1 || use[0].payload.key !== 'k2' || use[0].payload.seen !== 'k0' || use[0].payload.card !== CARD) fail(name, `Use this did not send one versions_use for C: ${JSON.stringify(use)}`);
  let txt = await boxText(p);
  if (!/is the card now/.test(txt) || !/Undo/.test(txt)) fail(name, `Use this does not say so with Undo: ${txt.slice(0, 200)}`);
  if (!/Inside/.test(await cardName(p) || '')) fail(name, `the dashboard did not reload with the version: ${await cardName(p)}`);
  k = await kept(p);
  if (!k || k.n !== 4 || k.cur !== 'k2') fail(name, `after Use this the set is not the same four with C in use: ${JSON.stringify(k)}`);
  chips = await chipList(p);
  if (!chips[2] || !chips[2].now || chips[0].now) fail(name, `the chip in use did not move to C: ${JSON.stringify(chips.map((x) => x.t))}`);
  await fits(p, name, touch, 'after Use this');
  await shot(p, name, '4-used-C');

  // A/B: switch back to A the same way, and to C again; Undo reverts the last one only.
  await showKey(p, 'k0');
  await click(p, '[data-act="ver-use"]');
  await settle(p, 1200);
  if (await cardName(p) !== 'Temperature') fail(name, `switching back to A did not put the card back: ${await cardName(p)}`);
  k = await kept(p);
  if (!k || k.n !== 4 || k.cur !== 'k0') fail(name, `switching back lost a version: ${JSON.stringify(k)}`);
  await click(p, '[data-act="ver-undo"]');
  await settle(p, 1200);
  if (!/Inside/.test(await cardName(p) || '')) fail(name, `Undo did not revert exactly the last switch: ${await cardName(p)}`);
  if (!(await R(p, () => window.__ws.some((m) => m.kind === 'tell_undo')))) fail(name, 'Undo sent no tell_undo');
  k = await kept(p);
  if (!k || k.n !== 4 || k.cur !== 'k2') fail(name, `after Undo the set is not the four with C in use: ${JSON.stringify(k)}`);

  // Close and open again: the same set.
  await R(p, () => window.__panel.closeTell());
  await settle(p, 800);
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1400);
  k = await kept(p);
  if (!k || k.n !== 4 || k.cur !== 'k2' || k.show !== 'k2') fail(name, `opening the Tell again did not show the kept set: ${JSON.stringify(k)}`);
  if (await shown(p)) fail(name, 'opening the Tell again drew something other than the card in use');

  // More like this, from B: added, B kept.
  await showKey(p, 'k1');
  await click(p, '[data-act="ver-more"]');
  await settle(p, 600);
  const more = await lastReq(p, 'versions');
  if (!more || !more.payload.base || more.payload.base.how !== 'more' || more.payload.base.key !== 'k1') fail(name, `More like this did not ask from B: ${JSON.stringify(more && more.payload)}`);
  await settle(p, 3000);
  k = await kept(p);
  if (!k || k.n !== 6 || !k.keys.includes('k1') || k.show !== 'k4') fail(name, `More like this did not add two versions and keep B: ${JSON.stringify(k)}`);

  // Words on a version (the box under it): added, the version kept.
  await showKey(p, 'k1');
  if (!/What should change in B\?/.test(await R(p, () => (window.__panel.shadowRoot.querySelector('[data-tell] textarea') || {}).placeholder || ''))) fail(name, 'the words box does not name the shown version');
  await type(p, 'Bigger numbers');
  await click(p, '[data-act="tell-send"]');
  await settle(p, 600);
  const rev = await lastReq(p, 'versions');
  if (!rev || rev.payload.base.key !== 'k1' || rev.payload.base.how !== 'new' || rev.payload.text !== 'Bigger numbers') fail(name, `words on B did not ask from B: ${JSON.stringify(rev && rev.payload)}`);
  if (rev && rev.payload.view && Object.keys(rev.payload.view).length) fail(name, 'a round on a version that is not the card sent the card\'s picture text');
  await settle(p, 3000);
  k = await kept(p);
  if (!k || k.n !== 9 || !k.keys.includes('k1')) fail(name, `words on B did not add three versions and keep B: ${JSON.stringify(k)}`);

  // Mark what's wrong on C (a readings card): tap a row, say what is wrong.
  await showKey(p, 'k2');
  await click(p, '[data-act="ver-mark"]');
  await settle(p, 400);
  if (!/Tap the part of the card above that is wrong/.test(await boxText(p))) fail(name, 'Mark what’s wrong does not say what to do');
  await shot(p, name, '5-marking');
  const calls0 = await R(p, () => window.__calls.length);
  const view0 = await R(p, () => JSON.stringify(window.__panel.s.view));
  const row = await R(p, (id) => { const tc = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"] .tc`); const el = [...tc.querySelectorAll('[data-member], [data-entity], [data-rhide]')].find((e) => !e.closest('[data-tell]') && e.getBoundingClientRect().width > 0); if (!el) return null; el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { x: r.left + Math.min(20, r.width / 2), y: r.top + r.height / 2, e: (el.getAttribute('data-member') || el.getAttribute('data-entity') || el.getAttribute('data-rhide')).split('|').pop() }; }, CARD);
  if (!row) fail(name, 'version C draws no row to mark');
  else {
    await settle(p, 300);
    const at = await R(p, (id) => { const tc = window.__panel.shadowRoot.querySelector(`[data-tile="${id}"] .tc`); const el = [...tc.querySelectorAll('[data-member], [data-entity], [data-rhide]')].find((e) => !e.closest('[data-tell]') && e.getBoundingClientRect().width > 0); const r = el.getBoundingClientRect(); return { x: r.left + Math.min(20, r.width / 2), y: r.top + r.height / 2 }; }, CARD);
    await tap(at.x, at.y);
    await settle(p, 500);
    const mark = await R(p, () => { const t = window.__panel.s.tell; return t && t.mark; });
    if (!mark || !['row', 'control'].includes(mark.role) || mark.entity !== row.e) fail(name, `the tap did not mark the row as a typed part: ${JSON.stringify(mark)}`);
    if (await R(p, () => window.__calls.length) !== calls0) fail(name, 'marking a row called a service');
    if (await R(p, () => JSON.stringify(window.__panel.s.view)) !== view0) fail(name, 'marking a row opened or changed the card');
    if (!(await R(p, (id) => !!window.__panel.shadowRoot.querySelector(`[data-tile="${id}"] .tc [data-marked]`), CARD))) fail(name, 'the marked part has no outline');
    const fs = await R(p, () => { const i = window.__panel.shadowRoot.querySelector('input[data-keep="vermark"]'); return i && parseFloat(getComputedStyle(i).fontSize); });
    if (!fs) fail(name, 'marking opened no text box'); else if (fs < 16) fail(name, `the mark's text box is ${fs}px (16px floor)`);
    await R(p, () => { const i = window.__panel.shadowRoot.querySelector('input[data-keep="vermark"]'); if (i) i.value = 'Too small to read'; });
    await fits(p, name, touch, 'marking');
    await shot(p, name, '6-marked');
    await click(p, '[data-act="ver-mark-send"]');
    await settle(p, 600);
    const mreq = await lastReq(p, 'versions');
    if (!mreq || mreq.payload.base.how !== 'mark' || mreq.payload.base.key !== 'k2' || !mreq.payload.mark || mreq.payload.mark.entity !== row.e || !mreq.payload.mark.role || mreq.payload.text !== 'Too small to read') fail(name, `the mark was not sent as a typed part of C: ${JSON.stringify(mreq && mreq.payload)}`);
    await settle(p, 3000);
    k = await kept(p);
    if (!k || k.n !== 11 || !k.keys.includes('k2')) fail(name, `the marked round did not add two versions and keep C: ${JSON.stringify(k)}`);
    await shot(p, name, '7-marked-answers');
  }

  // Remove B, then put it back.
  await showKey(p, 'k1');
  const n0 = (await kept(p) || {}).n;
  await click(p, '[data-act="ver-remove"]');
  await settle(p, 600);
  k = await kept(p);
  if (!k || k.n !== n0 - 1 || k.keys.includes('k1')) fail(name, `Remove did not take B out: ${JSON.stringify(k)}`);
  if (!/Removed B/.test(await boxText(p))) fail(name, 'Remove does not say so with Put it back');
  await fits(p, name, touch, 'after Remove');
  await shot(p, name, '8-removed');
  await click(p, '[data-act="ver-unremove"]');
  await settle(p, 600);
  k = await kept(p);
  if (!k || k.n !== n0 || !k.keys.includes('k1') || k.show !== 'k1') fail(name, `Put it back did not return B: ${JSON.stringify(k)}`);

  // A full set (the fixture's cap lowered to 11): a round that lands while
  // the person stepped elsewhere leaves them there, the cap moves the
  // oldest to Removed (said by the chips), and Put back at a full set keeps
  // the version it put back.
  await R(p, () => { window.__keep = 11; });
  await showKey(p, 'k0');
  await click(p, '[data-act="ver-remove"]');
  await settle(p, 600);
  await showKey(p, 'k1');
  await click(p, '[data-act="ver-more"]');
  await settle(p, 300);
  await showKey(p, 'k3');
  await settle(p, 3000);
  k = await kept(p);
  if (!k || k.show !== 'k3') fail(name, `a round that finished jumped away from the version the person stepped to: ${JSON.stringify(k)}`);
  if (!k || k.n !== 11) fail(name, `the cap did not hold the set at 11: ${JSON.stringify(k)}`);
  const removed = await R(p, () => (window.__panel.s.tell.kept.removed || []).map((x) => x.key));
  if (!removed.includes('k0') || removed.length < 2) fail(name, `what the cap took is not in Removed: ${JSON.stringify(removed)}`);
  if (!/11 kept; the oldest move to Removed as new ones arrive/.test(await boxText(p))) fail(name, 'a full set does not say the oldest move to Removed');
  await fits(p, name, touch, 'full set');
  await shot(p, name, '9-full');
  await click(p, '[data-act="ver-unremove"][data-v="k0"]');
  await settle(p, 600);
  k = await kept(p);
  if (!k || !k.keys.includes('k0') || k.n !== 11 || k.show !== 'k0') fail(name, `Put back at a full set lost the version it put back: ${JSON.stringify(k)}`);
  await R(p, () => { window.__keep = 0; });

  // Use this on a version that needs Home Assistant changes: a Tell.
  await showKey(p, await R(p, () => (window.__panel.s.tell.kept.versions.find((x) => (x.needs || []).length) || {}).key));
  await click(p, '[data-act="ver-use"]');
  await settle(p, 600);
  const needUse = await R(p, () => ({ tell: window.__panel.s.tell && window.__panel.s.tell.tellId, txt: (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '' }));
  if (!/^morph-t/.test(needUse.tell || '') || !/and make what it needs in Home Assistant/.test(needUse.txt)) fail(name, `Use this with needs did not start a Tell: ${JSON.stringify(needUse).slice(0, 200)}`);
  await settle(p, 2000);
  await R(p, () => window.__panel.closeTell());
  await settle(p, 500);

  // Just do it is the single Tell.
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1200);
  await type(p, 'Rename this Temps');
  await R(p, () => { window.__ws.length = 0; });
  await click(p, '[data-act="tell-now"]');
  await settle(p, 600);
  const now = await R(p, () => window.__ws.find((m) => m.type === 'morph/request' && (m.kind === 'tell' || m.kind === 'versions')));
  if (!now || now.kind !== 'tell' || now.payload.target.kind !== 'card') fail(name, `Just do it did not hand over a single Tell: ${JSON.stringify(now && now.kind)}`);
  await settle(p, 2400);
  if (!/Keep/.test(await boxText(p))) fail(name, 'Just do it does not end with Keep · Undo');

  const wide = await R(p, () => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  if (wide.sw > wide.iw + 1) fail(name, `the page scrolls sideways (${wide.sw} > ${wide.iw})`);
  if (errors.length) fail(name, `page errors: ${errors.join(' | ').slice(0, 400)}`);
  await ctx.close();
}
await browser.close();
if (problems.length) { console.log(problems.map((x) => 'FAIL ' + x).join('\n')); process.exit(1); }
console.log('measure-morph-versions: all checks passed');
