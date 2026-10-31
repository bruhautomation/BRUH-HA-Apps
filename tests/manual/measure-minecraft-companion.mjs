/* Playwright measure for BRUH Minecraft's panel: the Companion card and the
 * header's version and changelog link (#593, #594).
 *
 *   node tests/manual/measure-minecraft-companion.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it;
 *    SHOTS_DIR=... for the screenshots, default /tmp)
 *
 * Loads the real page (bruh-minecraft-server/panel/index.html, app.js,
 * style.css) at a desk (1200) and a phone on touch (390) with every api/*
 * answered by a small stateful stand-in for server.py's routes, twice:
 *
 *   - with no brAIn: the Companion card is not there, and one line says
 *     "Install brAIn to have a companion play in the world.";
 *   - with brAIn: the card is named as brAIn names it (Juniper), its status
 *     line is the panel's headline, a protected place is added from where a
 *     player stands (the POST carries x and z), a question goes on the pads
 *     (the POST carries the pictures), Undo reaches the action's route, and
 *     what it said is listed. A deaf feed shows its warning at the top.
 *
 * And the header: "v<version> · changelog" is visible and inside the
 * viewport at both widths, opens the notes in the panel newest first, and
 * "Updated since you last looked" shows after an update until they are
 * opened. Fails on: a control in the card without a label; sideways scroll;
 * a control under 40px; text fields under 16px on touch; the Stop button or
 * the healthy/TPS figures under 4.5:1; a page error from the card.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const PANEL = fileURLToPath(new URL('../../bruh-minecraft-server/panel/', import.meta.url));
const VERSION = '1.17.8';
const FILES = {
  'index.html': ['text/html', readFileSync(PANEL + 'index.html', 'utf8').replaceAll('__VERSION__', VERSION)],
  'app.js': ['application/javascript', readFileSync(PANEL + 'app.js', 'utf8')],
  'style.css': ['text/css', readFileSync(PANEL + 'style.css', 'utf8')],
};
const SHOTS_DIR = process.env.SHOTS_DIR || '/tmp';
const BASE = 'http://panel.test/api/hassio_ingress/token/';

const b = await chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] }
    : { args: ['--no-sandbox'] });
const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);

function fakeServer(brain, deaf) {
  const s = { zones: [], questions: [], posts: [], online: ['.Kaz8044', 'BenMC13765'] };
  const status = () => ({
    brain, active: true, name: 'Juniper', state: 'idle',
    identity: { name: 'Juniper', colour: 'aqua', active: true, by: 'brAIn', model: 'haiku' },
    online: s.online, zones: s.zones, questions: s.questions,
    actions: [{ id: '20261031-abcdef', t: 1761900000, kind: 'build', text: 'Juniper built a little bridge beside .Kaz8044 (asked by Dad)', status: 'done', undoable: true }],
    said: [{ id: '20261031-111111', t: 1761900100, to: ['BenMC13765'], name: 'Juniper', text: 'Done — a little oak bridge is up beside Kaz.', by: 'brAIn' }],
    listening: deaf ? { ok: false, why: 'Dad came on without the usual join line in the server\'s log.' } : { ok: true },
    headline: brain
      ? { code: 'ready', show: true, text: 'Juniper is on. brAIn decides what it does; everything it did is below and can be undone.' }
      : { code: 'no_brain', show: false, text: 'Install brAIn to have a companion play in the world.' },
    accounts: { java: true, bedrock: true },
  });
  const world = () => ({
    players: [{ name: '.Kaz8044', dimension: 'minecraft:overworld', x: 132, y: 64, z: -48 }],
    listening: deaf ? { ok: false, why: 'Dad came on without the usual join line in the server\'s log.' } : { ok: true },
  });
  const changelog = () => ({ version: VERSION, releases: [
    { version: '1.17.8', date: '', body: '### Added\n\n- **Game events for Home Assistant.** Every chat line…' },
    { version: '1.17.7', date: '', body: '### Changed\n\n- The card is a setup you can follow.' },
  ] });
  const answer = (method, path, body) => {
    if (path === 'api/companion' && method === 'GET') return [200, status()];
    if (path === 'api/world') return [200, world()];
    if (path === 'api/changelog') return [200, changelog()];
    if (path === 'api/status' || path === 'api/players') return [200, { running: true, stats: { tps_1m: 20, tps_5m: 20, tps_15m: 20 } }];
    s.posts.push({ method, path, body });
    if (path === 'api/companion/zones' && method === 'POST') {
      const z = { ...body, protect: true, kind: 'family' };
      s.zones.push(z);
      return [200, { zone: z, zones: s.zones }];
    }
    if (path === 'api/companion/ask') {
      const q = { id: '20261031-aaaaaa', player: body.player, person: body.player, text: body.question, options: body.options, status: 'queued' };
      s.questions.unshift(q);
      return [201, { question: q, note: `Two pads go beside ${body.player} now.` }];
    }
    if (path.startsWith('api/companion/actions/')) return [200, { action: { status: 'undone' }, restored: 2, changed: 0 }];
    return [200, {}];
  };
  return { s, answer };
}

async function open(width, touch, { brain = true, deaf = false, seen = null } = {}) {
  const ctx = await b.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch, deviceScaleFactor: touch ? 2 : 1,
  });
  if (seen !== null) {
    await ctx.addInitScript((v) => { try { localStorage.setItem('bruh-minecraft.changelog.seen', v); } catch { /* none */ } }, seen);
  }
  const page = await ctx.newPage();
  const fake = fakeServer(brain, deaf);
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('dialog', (d) => d.accept());
  await page.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (!url.pathname.startsWith('/api/hassio_ingress/token/')) return route.abort();
    const rel = url.pathname.slice('/api/hassio_ingress/token/'.length) || 'index.html';
    if (FILES[rel]) return route.fulfill({ contentType: FILES[rel][0], body: FILES[rel][1] });
    if (rel.startsWith('api/')) {
      const [code, body] = fake.answer(req.method(), rel, req.postData() ? JSON.parse(req.postData()) : null);
      return route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
    }
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);
  return { ctx, page, fake, errors };
}

const settle = (page) => page.waitForTimeout(250);

const audit = (width) => {
  const out = [];
  const card = document.querySelector('#companion-card');
  if (document.documentElement.scrollWidth > width + 1) out.push(`the page scrolls sideways (${document.documentElement.scrollWidth})`);
  if (card.scrollWidth > card.clientWidth + 1) out.push(`the card overflows (${card.scrollWidth} > ${card.clientWidth})`);
  for (const n of card.querySelectorAll('input, select, textarea')) {
    const named = (n.labels && n.labels.length) || n.getAttribute('aria-label');
    if (!named) out.push(`#${n.id} has no label`);
    const r = n.getBoundingClientRect();
    if (n.type === 'checkbox' || !r.width) continue;
    if (r.height < 40) out.push(`#${n.id} is ${r.height.toFixed(0)}px tall`);
    if (r.right > width + 1) out.push(`#${n.id} ends at ${r.right.toFixed(0)}px`);
    if (matchMedia('(pointer: coarse)').matches && parseFloat(getComputedStyle(n).fontSize) < 16) {
      out.push(`#${n.id} text is ${getComputedStyle(n).fontSize} on touch`);
    }
  }
  for (const n of card.querySelectorAll('button')) {
    const r = n.getBoundingClientRect();
    if (!r.width) continue;
    if (r.height < 40) out.push(`button "${n.textContent.trim()}" is ${r.height.toFixed(0)}px tall`);
    if (r.right > width + 1) out.push(`button "${n.textContent.trim()}" ends at ${r.right.toFixed(0)}px`);
  }
  return out;
};

// WCAG contrast of an element's text against the first opaque ground behind it.
const contrastOf = (sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const rgb = (c) => (c.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  let bg = null;
  for (let n = el; n; n = n.parentElement) {
    const c = rgb(getComputedStyle(n).backgroundColor);
    if (c.length >= 3 && (c.length < 4 || c[3] > 0.95)) { bg = c; break; }
  }
  bg = bg || [255, 255, 255];
  const fg = rgb(getComputedStyle(el).color);
  const [a, z] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (z + 0.05);
};

for (const [width, touch] of [[1200, false], [390, true]]) {
  const where = String(width);
  // Without brAIn: no companion, one line why.
  {
    const { ctx, page, errors } = await open(width, touch, { brain: false });
    try {
      if (await page.locator('#companion-card').isVisible()) fail(where, 'the companion card shows with no brAIn');
      const line = await page.locator('#companion-absent').textContent();
      if (!(await page.locator('#companion-absent').isVisible()) || !line.includes('Install brAIn')) fail(where, `no brAIn says "${line}"`);
      for (const e of errors) fail(where, `page error (no brAIn): ${e}`);
    } finally { await ctx.close(); }
  }
  // With brAIn, after an update, with a deaf feed.
  const { ctx, page, fake, errors } = await open(width, touch, { brain: true, deaf: true, seen: '1.17.7' });
  try {
    // The header: the version link, visible and inside the viewport.
    const link = page.locator('#version-link');
    if (!(await link.isVisible())) fail(where, 'the version link is not visible');
    const box = await link.boundingBox();
    if (!box || box.x < 0 || box.x + box.width > width + 1 || box.y > 300) fail(where, `the version link is at ${JSON.stringify(box)}`);
    const text = (await link.textContent()).trim();
    if (text !== `v${VERSION} · changelog`) fail(where, `the link reads "${text}"`);
    if (!(await page.locator('#version-new').isVisible())) fail(where, 'no "updated" marker after an update');
    await link.click();
    await settle(page);
    const heads = await page.$$eval('#changelog-body h3', (h) => h.map((x) => x.textContent));
    if (!heads[0] || !heads[0].startsWith('v1.17.8') || !heads[1].startsWith('v1.17.7')) fail(where, `the notes read ${JSON.stringify(heads)}`);
    if (!heads[0].includes('New')) fail(where, 'the release since last look is not marked New');
    await page.screenshot({ path: `${SHOTS_DIR}/minecraft-changelog-${width}.png` });
    await page.click('#changelog-close');
    if (await page.locator('#version-new').isVisible()) fail(where, 'the marker stays after the notes were read');

    // Contrast (#594).
    for (const sel of ['#btn-stop']) {
      const r = await page.evaluate(contrastOf, sel);
      if (r === null || r < 4.5) fail(where, `${sel} contrast is ${r && r.toFixed(2)}`);
    }

    // The deaf feed.
    const warn = page.locator('#feed-warning');
    if (!(await warn.isVisible()) || !(await warn.textContent()).includes('join line')) fail(where, 'no deaf-feed warning');

    // The card, named as brAIn names it.
    const title = await page.locator('#companion-title').textContent();
    if (title !== 'Juniper') fail(where, `the card is titled "${title}"`);
    const status = await page.locator('#companion-status').textContent();
    if (!status.startsWith('Juniper is on.')) fail(where, `the status says "${status}"`);

    // A protected place from where Kaz stands.
    await page.click('#companion-here button[data-here=".Kaz8044"]');
    await page.fill('#companion-zone-name', 'Our house');
    await page.click('#f-companion-zone button[type="submit"]');
    await settle(page);
    const zone = fake.s.posts.find((p) => p.path === 'api/companion/zones');
    if (!zone || zone.body.x !== 132 || zone.body.z !== -48) fail(where, `the zone POST was ${JSON.stringify(zone)}`);

    // A question on the pads.
    await page.selectOption('#companion-ask-who', '.Kaz8044');
    await page.fill('#companion-ask-text', 'Do you want a castle or a farm?');
    await page.fill('#companion-ask-a', 'castle');
    await page.dispatchEvent('#companion-ask-a', 'change');
    await page.fill('#companion-ask-b', 'farm');
    await page.dispatchEvent('#companion-ask-b', 'change');
    await page.click('#companion-ask-go');
    await settle(page);
    const ask = fake.s.posts.find((p) => p.path === 'api/companion/ask');
    if (!ask || ask.body.options[0].picture !== 'minecraft:stone_bricks' || ask.body.options[1].picture !== 'minecraft:hay_block') {
      fail(where, `the ask POST was ${JSON.stringify(ask)}`);
    }

    // Undo, and what it said.
    await page.click('button[data-companion-undo="20261031-abcdef"]');
    await settle(page);
    if (!fake.s.posts.some((p) => p.path === 'api/companion/actions/20261031-abcdef/undo')) fail(where, 'Undo did not reach its route');
    const said = await page.$$eval('#companion-said li', (l) => l.map((x) => x.textContent.replace(/\s+/g, ' ')));
    if (!said[0] || !said[0].includes('Juniper to BenMC13765') || !said[0].includes('oak bridge')) fail(where, `what it said reads "${said[0]}"`);

    await page.evaluate(() => document.querySelector('#companion-card').scrollIntoView());
    for (const p of await page.evaluate(audit, width)) fail(where, p);
    for (const e of errors) fail(where, `page error: ${e}`);
    await page.addStyleTag({ content: 'html, body, main { height: auto !important; overflow: visible !important; }' });
    await page.locator('#companion-card').screenshot({ path: `${SHOTS_DIR}/minecraft-companion-card-${width}.png` });
    await page.locator('header.topbar').screenshot({ path: `${SHOTS_DIR}/minecraft-header-${width}.png` });
  } catch (e) {
    fail(where, String(e));
  } finally {
    await ctx.close();
  }
}
await b.close();
if (problems.length) {
  console.log(problems.join('\n'));
  process.exit(1);
}
console.log('Companion card and header: ok at 1200 and 390 (screenshots in ' + SHOTS_DIR + ')');
