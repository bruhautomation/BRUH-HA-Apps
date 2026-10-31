/* Playwright measure for the Vesper card on BRUH Minecraft's panel.
 *
 *   node tests/manual/measure-minecraft-vesper.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it;
 *    SHOTS_DIR=... for the two screenshots, default /tmp)
 *
 * Loads the real page (bruh-minecraft-server/panel/index.html, app.js,
 * style.css) at a desk (1200) and a phone on touch (390) with every api/*
 * answered by a small stateful stand-in for server.py's Vesper routes, and
 * walks the setup a parent does with no docs: Vesper off and nobody on the
 * family list (the status line says so), switch it on (it says the family
 * list is empty), tap the "Add .Kaz8044" chip, save the family (the PUT
 * carries the roster), pick a bedtime entity and "off", add a protected
 * place from someone's position (the POST carries x and z), ask a question
 * (disabled while the person is away, then the POST). Fails on: a control
 * in the card without a label; sideways scroll; a control under 40px; text
 * fields under 16px on touch; a page error from the card.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const PANEL = fileURLToPath(new URL('../../bruh-minecraft-server/panel/', import.meta.url));
const FILES = {
  'index.html': ['text/html', readFileSync(PANEL + 'index.html', 'utf8')],
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

function fakeServer() {
  const s = {
    enabled: false, bedtime: '', daily: 120, family: [], zones: [], questions: [], posts: [],
    online: ['.Kaz8044'],
  };
  const who = (player) => {
    const bare = (n) => n.replace(/^[.*]/, '').toLowerCase();
    const p = s.family.find((x) => x.players.some((n) => bare(n) === bare(player)));
    return p ? { person: p.person, role: p.role, player } : { person: player, role: 'guest', player };
  };
  const headline = () => {
    const here = s.online.map(who).filter((w) => w.role !== 'guest');
    if (!s.enabled) return { code: 'off', text: s.family.length ? 'Off. Switch Vesper on to let it play in the world with your family.' : 'Off. Add your family below, then switch Vesper on.' };
    if (!s.family.length) return { code: 'no_family', text: 'On, but nobody is on the family list yet — add your family below. Vesper leaves anyone not on the list alone.' };
    if (!here.length) return { code: 'waiting_join', text: 'On, waiting for someone from the family to join the game.' };
    return { code: 'ready', text: `On — ${here.map((w) => w.person).join(', ')} in the game. Vesper is ready.` };
  };
  const status = () => ({
    enabled: s.enabled, state: s.enabled ? 'idle' : 'off',
    settings: { enabled: s.enabled, bedtime_entity: s.bedtime, daily_actions: s.daily },
    budget: { day: '2026-10-31', actions: 3, actions_limit: s.daily, events: 1, events_limit: 40 },
    family: s.family, zones: s.zones, questions: s.questions, online: s.online.map(who),
    headline: headline(), note: '', moments: [], memory: {},
    actions: [{ id: '20261031-abcdef', t: 1761900000, kind: 'greeting', text: 'Vesper said hello to Kaz', status: 'done', undoable: false }],
  });
  const world = () => ({
    players: [{ name: '.Kaz8044', dimension: 'minecraft:overworld', x: 132, y: 64, z: -48 }],
    last_seen: { '.Kaz8044': 1761900000, '.Lev6398': 1761800000, Ben13765: 1761700000 },
  });
  const answer = (method, path, body) => {
    if (path === 'api/vesper' && method === 'GET') return [200, status()];
    if (path === 'api/world') return [200, world()];
    if (path === 'api/vesper/entities') return [200, { reachable: true, entities: [
      { entity_id: 'input_boolean.kids_bedtime', name: 'Kids bedtime', state: 'off' },
      { entity_id: 'binary_sensor.boys_door', name: "Boys' door", state: 'on' }] }];
    s.posts.push({ method, path, body });
    if (path === 'api/vesper/engine') {
      if ('on' in body) s.enabled = body.on;
      if ('bedtime_entity' in body) s.bedtime = body.bedtime_entity;
      if ('daily_actions' in body) s.daily = body.daily_actions;
      return [200, status()];
    }
    if (path === 'api/vesper/family' && method === 'PUT') {
      if (body.people.some((p) => !p.players.length)) return [400, { error: `${body.people[0].person} needs at least one in-game name.` }];
      s.family = body.people;
      return [200, { people: s.family }];
    }
    if (path === 'api/vesper/zones' && method === 'POST') {
      const z = { ...body, protect: true, kind: 'family' };
      s.zones.push(z);
      return [200, { zone: z, zones: s.zones }];
    }
    if (path === 'api/vesper/ask') {
      const q = { id: '20261031-aaaaaa', person: body.player, text: body.text, options: body.options, status: 'queued' };
      s.questions.unshift(q);
      return [201, { question: q, note: `Vesper will put two pads beside ${body.player} now.` }];
    }
    return [200, {}];
  };
  return { s, answer };
}

async function open(width, touch) {
  const ctx = await b.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch, deviceScaleFactor: touch ? 2 : 1,
  });
  const page = await ctx.newPage();
  const fake = fakeServer();
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
  return { ctx, page, fake, errors };
}

const statusText = (page) => page.$eval('#vesper-status', (e) => e.textContent);
const settle = (page) => page.waitForTimeout(250);

const audit = (width) => {
  const out = [];
  const card = document.querySelector('#vesper-card');
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

for (const [width, touch] of [[1200, false], [390, true]]) {
  const where = String(width);
  const { ctx, page, fake, errors } = await open(width, touch);
  try {
    let t = await statusText(page);
    if (!t.startsWith('Off. Add your family')) fail(where, `off with no family says "${t}"`);
    await page.click('label.vesper-switch');
    await settle(page);
    t = await statusText(page);
    if (!t.includes('nobody is on the family list')) fail(where, `on with no family says "${t}"`);
    if (!(await page.$eval('#vesper-ask-go', (e) => e.disabled))) fail(where, 'Ask is enabled with nobody on the family list');

    // 1. Family: the chip fills a row, Save PUTs it.
    const chip = page.locator('#vesper-seen button[data-seen=".Kaz8044"]');
    if (!(await chip.count())) fail(where, 'no "Add .Kaz8044" chip for the player online');
    await chip.click();
    const row = await page.$eval('#vp-players-0', (e) => e.value);
    if (row !== '.Kaz8044') fail(where, `the chip filled "${row}"`);
    await page.click('#vesper-add-person');
    await page.fill('#vp-name-1', 'Dad');
    await page.selectOption('#vp-role-1', 'reader');
    await page.click('#vesper-family-save');
    await settle(page);
    let msg = await page.$eval('#vesper-family-msg', (e) => e.textContent);
    if (!msg.includes('needs at least one in-game name')) fail(where, `an empty name is not explained: "${msg}"`);
    await page.fill('#vp-players-1', 'Ben13765');
    await page.click('#vesper-family-save');
    await settle(page);
    const put = fake.s.posts.filter((p) => p.path === 'api/vesper/family').pop();
    if (!put || put.method !== 'PUT' || put.body.people[0].players[0] !== '.Kaz8044' || put.body.people[1].role !== 'reader') {
      fail(where, `the family PUT was ${JSON.stringify(put)}`);
    }
    msg = await page.$eval('#vesper-family-msg', (e) => e.textContent);
    if (!msg.startsWith('Saved.')) fail(where, `the save said "${msg}"`);
    t = await statusText(page);
    if (!t.includes('Kaz')) fail(where, `with Kaz on the status says "${t}"`);

    // 2. Bedtime: an entity and "off", no "=" typed.
    await page.focus('#vesper-bedtime');
    await settle(page);
    const listed = await page.$$eval('#vesper-entities option', (o) => o.map((x) => x.value));
    if (!listed.includes('binary_sensor.boys_door')) fail(where, 'the bedtime list is missing entities');
    await page.fill('#vesper-bedtime', 'binary_sensor.boys_door');
    if ((await page.$eval('#vesper-bedtime-when', (e) => e.value)) !== 'off') fail(where, 'a door sensor did not pick "off"');
    await page.click('#f-vesper button[type="submit"]');
    await settle(page);
    if (fake.s.bedtime !== 'binary_sensor.boys_door=off') fail(where, `bedtime saved as "${fake.s.bedtime}"`);

    // 3. A protected place from where Kaz stands.
    await page.click('#vesper-here button[data-here=".Kaz8044"]');
    await page.fill('#vesper-zone-name', 'Our house');
    await page.click('#f-vesper-zone button[type="submit"]');
    await settle(page);
    const zone = fake.s.posts.find((p) => p.path === 'api/vesper/zones');
    if (!zone || zone.body.x !== 132 || zone.body.z !== -48) fail(where, `the zone POST was ${JSON.stringify(zone)}`);

    // 4. Ask: Dad is away (disabled, with a reason); Kaz is on.
    await page.selectOption('#vesper-ask-who', 'Dad');
    if (!(await page.$eval('#vesper-ask-go', (e) => e.disabled))) fail(where, 'Ask is enabled for somebody away');
    const why = await page.$eval('#vesper-ask-why', (e) => e.textContent);
    if (!why.includes('not in the game right now')) fail(where, `the reason was "${why}"`);
    await page.selectOption('#vesper-ask-who', 'Kaz');
    await page.fill('#vesper-ask-text', 'Do you want a castle or a farm?');
    await page.fill('#vesper-ask-a', 'castle');
    await page.fill('#vesper-ask-b', 'farm');
    await page.click('#vesper-ask-go');
    await settle(page);
    const ask = fake.s.posts.find((p) => p.path === 'api/vesper/ask');
    if (!ask || ask.body.options[0].picture !== 'minecraft:stone_bricks' || ask.body.options[1].picture !== 'minecraft:hay_block') {
      fail(where, `the ask POST was ${JSON.stringify(ask)}`);
    }

    await page.evaluate(() => document.querySelector('#vesper-card').scrollIntoView());
    for (const p of await page.evaluate(audit, width)) fail(where, p);
    const own = errors.filter((e) => /vesper|vSend|vSay/i.test(e));
    for (const e of own) fail(where, `page error: ${e}`);
    // main is the page's one scroll container; let it grow so the whole card is in the shot.
    await page.addStyleTag({ content: 'html, body, main { height: auto !important; overflow: visible !important; }' });
    await page.locator('#vesper-card').screenshot({ path: `${SHOTS_DIR}/vesper-card-${width}.png` });
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
console.log('Vesper card: ok at 1200 and 390 (screenshots in ' + SHOTS_DIR + ')');
