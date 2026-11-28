/* Playwright measure for a card's versions on Morph's own page.
 *
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome node tests/manual/measure-morph-versions.mjs
 *   SHOTS=/some/folder ...   (screenshots, versions-<width>-<step>.png)
 *
 * A card's Tell asks brAIn for versions (service/versions.py), and the
 * fixture answers the way morphd does. At a 390px phone (touch: a
 * two-finger tap opens the Tell, a swipe on the versions bar steps) and at
 * 1200px (a right click opens it, the arrow keys step):
 *
 *   * Send asks for versions (`versions`), Just do it stays a Tell;
 *   * the answer draws version A IN the card's place, with the card's own
 *     renderer, and nothing else on the page moves;
 *   * chips Current · A · B · C, ← → and a swipe switch what is drawn;
 *   * a version that needs Home Assistant changes says so;
 *   * Change… revises one version (its label gains "· revised"), More like
 *     this asks again from the shown one, Discard writes nothing;
 *   * Use this writes the card (one request, `versions_use`), says so with
 *     Undo, and Undo puts the card back; the card's Tell then shows the
 *     card it replaced under Versions, drawn live on a tap, and Use this
 *     puts it back the same way;
 *   * no sideways scroll at 390px, 44px chips on touch, 16px text boxes.
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
  if (!btns.includes('Just do it')) fail(name, `the composing box has no Just do it: ${btns.join(' | ')}`);
  await settle(p, 800);
  const before = await others(p);

  // Send: versions.
  await R(p, () => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Make this simpler'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await click(p, '[data-act="tell-send"]');
  await settle(p, 600);
  const req = await R(p, () => window.__ws.find((m) => m.type === 'morph/request' && m.kind === 'versions'));
  if (!req || req.payload.target.id !== CARD || req.payload.text !== 'Make this simpler') fail(name, `Send did not ask for versions: ${JSON.stringify(req)}`);
  if (await R(p, () => window.__ws.some((m) => m.kind === 'tell'))) fail(name, 'Send also started a single-change Tell');
  await shot(p, name, '0-working');
  await settle(p, 3000);
  let v = await shown(p);
  if (!v || v.type !== 'sensor' || v.name !== 'Kitchen') fail(name, `version A is not drawn in the card's place: ${JSON.stringify(v)}`);
  if (!/Kitchen/.test(await faceText(p))) fail(name, 'the card face does not show version A');
  const chips = await R(p, () => [...window.__panel.shadowRoot.querySelectorAll('[data-tell] .vchip')].map((b) => { const r = b.getBoundingClientRect(); return { t: b.innerText.replace(/\s+/g, ' ').trim(), h: r.height, w: r.width, on: b.getAttribute('aria-pressed') }; }));
  if (chips.length !== 4 || !/^Current/.test(chips[0].t) || !/^A Kitchen only/.test(chips[1].t)) fail(name, `chips are not Current · A · B · C: ${JSON.stringify(chips.map((x) => x.t))}`);
  if (touch && chips.some((x) => x.h < 44 || x.w < 44)) fail(name, `a chip is under 44px on touch: ${JSON.stringify(chips)}`);
  if (!/left out because Morph could not draw it/.test(await boxText(p))) fail(name, 'the dropped version is not said');
  const after = await others(p);
  const moved = (x, y) => !y || x[0] !== y[0] || Math.abs(x[1] - y[1]) > 2 || Math.abs(x[2] - y[2]) > 2;
  if (before.some((x, i) => moved(x, after[i]))) fail(name, `cards above the card's room moved while a version was shown: ${JSON.stringify(before.map((x, i) => [x, after[i]]).filter(([x, y]) => moved(x, y)).slice(0, 3))}`);
  await shot(p, name, '1-A');

  // Chip B.
  await click(p, '[data-act="ver-show"][data-v="1"]');
  await settle(p, 500);
  v = await shown(p);
  if (!v || v.type !== 'readings' || v.name !== 'Inside') fail(name, `chip B did not draw version B: ${JSON.stringify(v)}`);
  if (!/Just the rooms people live in/.test(await boxText(p))) fail(name, 'the shown version\'s idea line is missing');
  await shot(p, name, '2-B');

  // Step to C: a swipe on touch, the arrow key with a mouse.
  if (touch) {
    const bar = await R(p, () => { const r = window.__panel.shadowRoot.querySelector('[data-vswipe]').getBoundingClientRect(); return { x: r.left + r.width * 0.75, y: r.top + r.height - 10 }; });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: bar.x, y: bar.y, id: 1 }] });
    for (let i = 1; i <= 6; i++) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: bar.x - i * 25, y: bar.y + 2, id: 1 }] }); await settle(p, 16); }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } else {
    await R(p, () => window.__panel.shadowRoot.activeElement && window.__panel.shadowRoot.activeElement.blur());
    await p.keyboard.press('ArrowRight');
  }
  await settle(p, 500);
  v = await shown(p);
  if (!v || v.name !== 'House average') fail(name, `${touch ? 'a swipe' : 'ArrowRight'} did not step to version C: ${JSON.stringify(v)}`);
  if (!/Needs in Home Assistant, made only if you use it/.test(await boxText(p))) fail(name, 'version C does not say what it needs from Home Assistant');
  await shot(p, name, '3-C-needs');
  // On to Current (it wraps), and back with the arrow buttons.
  await click(p, '[data-act="ver-step"][data-v="1"]');
  await settle(p, 400);
  if (await shown(p)) fail(name, 'stepping past C did not come back to Current');
  if (!touch) { await p.keyboard.press('ArrowLeft'); await settle(p, 300); if ((await shown(p) || {}).name !== 'House average') fail(name, 'ArrowLeft did not step back to C'); }

  // Change… revises the shown one.
  await click(p, '[data-act="ver-show"][data-v="0"]');
  await settle(p, 300);
  await click(p, '[data-act="ver-change"]');
  await settle(p, 300);
  const inp = await R(p, () => { const i = window.__panel.shadowRoot.querySelector('input[data-keep="verchange"]'); return i && parseFloat(getComputedStyle(i).fontSize); });
  if (!inp) fail(name, 'Change… opened no text box');
  else if (inp < 16) fail(name, `Change…'s text box is ${inp}px (16px floor)`);
  await R(p, () => { const i = window.__panel.shadowRoot.querySelector('input[data-keep="verchange"]'); i.value = 'Call it Rooms'; });
  await shot(p, name, '4-change');
  await click(p, '[data-act="ver-revise"]');
  await settle(p, 600);
  const rev = await R(p, () => window.__ws.filter((m) => m.kind === 'versions').slice(-1)[0]);
  if (!rev || !rev.payload.base || rev.payload.base.how !== 'revise' || rev.payload.base.index !== 0) fail(name, `Change… did not ask for a revision of A: ${JSON.stringify(rev && rev.payload)}`);
  await settle(p, 3000);
  const labels = await R(p, () => ((window.__panel.s.tell.state || {}).versions || []).map((x) => x.label));
  if (labels[0] !== 'Kitchen only · revised' || labels.length !== 3) fail(name, `the revised set is wrong: ${JSON.stringify(labels)}`);

  // More like this.
  await click(p, '[data-act="ver-more"]');
  await settle(p, 600);
  const more = await R(p, () => window.__ws.filter((m) => m.kind === 'versions').slice(-1)[0]);
  if (!more || !more.payload.base || more.payload.base.how !== 'more') fail(name, 'More like this did not ask from the shown version');
  await settle(p, 3000);

  // Use this on B (no needs): one write, Undo.
  await click(p, '[data-act="ver-show"][data-v="1"]');
  await settle(p, 300);
  await click(p, '[data-act="ver-use"]');
  await settle(p, 1200);
  const use = await R(p, () => window.__ws.filter((m) => m.kind === 'versions_use'));
  if (use.length !== 1 || use[0].payload.index !== 1 || use[0].payload.card) fail(name, `Use this did not send one versions_use for B: ${JSON.stringify(use)}`);
  let txt = await boxText(p);
  if (!/is the card now/.test(txt) || !/Undo/.test(txt)) fail(name, `Use this does not say so with Undo: ${txt.slice(0, 200)}`);
  const kept = await R(p, (id) => { const h = window.__panel.findCard(id); return h && h.card.name; }, CARD);
  if (!/Inside/.test(kept || '')) fail(name, `the dashboard did not reload with the version: ${kept}`);
  await shot(p, name, '5-used');
  await click(p, '[data-act="tell-undo"]');
  await settle(p, 1200);
  const back = await R(p, (id) => { const h = window.__panel.findCard(id); return h && h.card.name; }, CARD);
  if (back !== 'Temperature') fail(name, `Undo did not put the card back: ${back}`);
  if (!(await R(p, () => window.__ws.some((m) => m.kind === 'tell_undo')))) fail(name, 'Undo sent no tell_undo');
  await click(p, '[data-act="tell-cancel"]') || await click(p, '[data-act="tell-keep"]');
  await R(p, () => window.__panel.closeTell());
  await settle(p, 800);

  // The card's Tell again: Versions shows the card Use this replaced.
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1400);
  const hist = await R(p, () => [...window.__panel.shadowRoot.querySelectorAll('[data-tell] [data-act="ver-hist"]')].map((b) => b.innerText.replace(/\s+/g, ' ').trim()));
  if (hist.length < 2 || !/Inside/.test(hist[1])) fail(name, `the Tell box does not offer the earlier version: ${JSON.stringify(hist)}`);
  else {
    await click(p, '[data-act="ver-hist"][data-v="0"]');
    await settle(p, 500);
    v = await shown(p);
    if (!v || v.name !== 'Inside') fail(name, `tapping an earlier version did not draw it: ${JSON.stringify(v)}`);
    await shot(p, name, '6-history');
    await click(p, '[data-act="ver-use-hist"]');
    await settle(p, 1200);
    const uh = await R(p, () => window.__ws.filter((m) => m.kind === 'versions_use').slice(-1)[0]);
    if (!uh || uh.payload.card !== 'c_temps' || !uh.payload.at) fail(name, `Use this on an earlier version sent ${JSON.stringify(uh && uh.payload)}`);
    if (!/Undo/.test(await boxText(p))) fail(name, 'Use this on an earlier version offers no Undo');
    await click(p, '[data-act="tell-undo"]');
    await settle(p, 900);
    await R(p, () => window.__panel.closeTell());
    await settle(p, 600);
  }

  // Use this on a version that needs Home Assistant changes: a Tell.
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1200);
  await R(p, () => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Show the average'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await click(p, '[data-act="tell-send"]');
  await settle(p, 3200);
  await click(p, '[data-act="ver-show"][data-v="2"]');
  await settle(p, 300);
  await click(p, '[data-act="ver-use"]');
  await settle(p, 600);
  const needUse = await R(p, () => ({ tell: window.__panel.s.tell && window.__panel.s.tell.tellId, txt: (window.__panel.shadowRoot.querySelector('[data-tell]') || {}).innerText || '' }));
  if (!/^morph-t/.test(needUse.tell || '') || !/and make what it needs in Home Assistant/.test(needUse.txt)) fail(name, `Use this with needs did not start a Tell: ${JSON.stringify(needUse).slice(0, 200)}`);
  await settle(p, 2000);
  await R(p, () => window.__panel.closeTell());
  await settle(p, 500);

  // Discard writes nothing; Just do it is the single Tell.
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1200);
  await R(p, () => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Anything'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
  await click(p, '[data-act="tell-send"]');
  await settle(p, 3200);
  const nUse = await R(p, () => window.__ws.filter((m) => m.kind === 'versions_use').length);
  await click(p, '[data-act="ver-discard"]');
  await settle(p, 500);
  if (await R(p, () => !!window.__panel.s.tell)) fail(name, 'Discard left the Tell open');
  if (await shown(p)) fail(name, 'Discard left a version drawn');
  if (await R(p, () => window.__ws.filter((m) => m.kind === 'versions_use').length) !== nUse) fail(name, 'Discard wrote something');
  await R(p, (id) => window.__panel.tellAbout({ kind: 'card', id }), CARD);
  await settle(p, 1200);
  await R(p, () => { const ta = window.__panel.shadowRoot.querySelector('[data-tell] textarea'); ta.value = 'Rename this Temps'; ta.dispatchEvent(new Event('input', { bubbles: true, composed: true })); });
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
