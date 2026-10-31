/* Playwright measure for BRUH Minecraft's world card in Morph.
 *
 *   node tests/manual/measure-minecraft-card.mjs
 *   (CHROMIUM_PATH=... when the browser is not where Playwright expects it)
 *
 * Loads the real card file (custom_components/bruh_minecraft/frontend/
 * bruh-minecraft-world.js) into a real browser with Morph's variables, at
 * a phone (390) and a desk (1200), against a stubbed `hass` whose sensors
 * carry what worldview.py publishes. Fails on: the world's time, day or
 * weather missing; a player or where they are missing (a Bedrock name with
 * its dot included); Vesper's current job, its progress or a finished
 * build's picture missing; the feed missing; anything about TPS or latency;
 * any button, hover text or floating element (Morph's rules); text under
 * 11 px; the card wider than its column; a page error. Then the quiet
 * states: nobody on, the server down, and an integration without the
 * world sensors.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CARD = readFileSync(fileURLToPath(new URL(
  '../../bruh-minecraft-server/custom_components/bruh_minecraft/frontend/bruh-minecraft-world.js',
  import.meta.url)), 'utf8');

const NOW = Date.now();
const iso = (s) => new Date(NOW - s * 1000).toISOString();
const P = 'sensor.bruh_minecraft_server_';
const st = (key, state, attributes = {}) => ({ entity_id: P + key, state: String(state), attributes });

const HOUSE = {
  [`${P}world_time`]: st('world_time', 'sunset', { hour: 19, clock: '19:00', day: 41 }),
  [`${P}world_day`]: st('world_day', 41),
  [`${P}world_weather`]: st('world_weather', 'rain', { source: 'the server' }),
  [`${P}players_online`]: st('players_online', 2, {
    players: ['Alex', '.KidPlays'],
    details: [
      { name: 'Alex', dimension: 'Overworld', x: 100, y: 64, z: -20, near: 'Watchtower',
        where: 'Overworld · near Watchtower', gamemode: 'survival', health: 18.5, food: 17 },
      { name: '.KidPlays', dimension: 'Nether', x: -8, y: 70, z: 4, near: null,
        where: 'Nether · -8, 70, 4', gamemode: 'creative', health: 20, food: 20 },
    ] }),
  [`${P}world_feed`]: st('world_feed', '.KidPlays was slain by Zombie', {
    events: [
      { time: iso(30), kind: 'death', player: '.KidPlays', text: '.KidPlays was slain by Zombie' },
      { time: iso(200), kind: 'advancement', player: 'Alex', text: 'Alex made the advancement Stone Age' },
      { time: iso(400), kind: 'chat', player: 'Alex', text: 'Alex: look at the tower, it is getting really tall now and I think we need more glass' },
      { time: iso(900), kind: 'build', player: 'Vesper', text: 'Vesper started building Watchtower' },
      { time: iso(1200), kind: 'join', player: '.KidPlays', text: '.KidPlays joined' },
      { time: iso(1300), kind: 'save', player: null, text: 'The world was saved' },
    ],
    last_seen: { Alex: iso(5), '.KidPlays': iso(5) } }),
  [`${P}vesper_building`]: st('vesper_building', 'Watchtower', {
    progress: 40, part: 'curiosity', queued: 2,
    current: { id: '20261031-abcdef', title: 'Watchtower', part: 'curiosity', status: 'building',
      progress: 40, started: iso(900) },
    recent: [
      { id: '20261030-000001', title: 'North wall', part: 'memory', status: 'done', progress: 100,
        finished: iso(7200), image: '/local/minecraft/20261030-000001.png?v=1' },
      { id: '20261030-000002', title: 'Lantern path', part: 'senses', status: 'done', progress: 100,
        finished: iso(9000), image: null },
    ] }),
  [`${P}last_save`]: st('last_save', iso(240)),
  [`${P}last_backup`]: st('last_backup', iso(3600)),
  [`${P}tps_1m`]: st('tps_1m', 19.9),
  [`${P}latency_ms`]: st('latency_ms', 3),
  'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} },
};

// A 2x2 PNG for the build picture.
const PIC = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFklEQVR42mNk+M9QzwAEjDAGNzYAAAWsAZEGmfP9AAAAAElFTkSuQmCC', 'base64');

const problems = [];
const browser = await chromium.launch(process.env.CHROMIUM_PATH
  ? { executablePath: process.env.CHROMIUM_PATH } : {});

async function mount(width, column, house) {
  const page = await browser.newPage({ viewport: { width, height: 1400 }, hasTouch: width < 600 });
  page.on('pageerror', (e) => problems.push(`${width}: page error ${e.message}`));
  await page.route('http://card.test/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/local/minecraft/')) {
      return route.fulfill({ body: PIC, contentType: 'image/png' });
    }
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><style>
      :root { --surface:#15181B; --sunk:#0A0C0E; --text:#eee; --muted:#9aa; --line:#333;
        --amber:#e0a030; --rose:#e05060; --violet:#9a7cf0; --sky:#4ab0e0; --lime:#6c6; }
      body { margin:0; padding:16px; background:#0A0C0E; font-family: Manrope, sans-serif; }
      #col { width:${column}px; background: var(--surface); padding: 14px; box-sizing: border-box; }
      </style></head><body><div id="col"></div></body></html>` });
  });
  await page.goto('http://card.test/');
  await page.addScriptTag({ content: CARD });
  await page.evaluate((house) => {
    const card = document.createElement('morph-minecraft-world');
    card.setConfig({});
    document.getElementById('col').append(card);
    card.hass = { states: house, entities: {} };
    window.card = card;
  }, house);
  return page;
}

const text = (page) => page.evaluate(() => window.card.shadowRoot.textContent.replace(/\s+/g, ' '));

for (const [width, column] of [[390, 358], [1200, 520]]) {
  const page = await mount(width, column, HOUSE);
  const t = await text(page);
  for (const want of ['19:00', 'Day 41', 'Sunset', 'Raining', 'On now · 2', 'Alex',
    'Overworld · near Watchtower', '.KidPlays', 'Nether · -8, 70, 4', 'creative', '♥ 19/20',
    'Vesper is building', 'Watchtower', 'curiosity · 40%', 'North wall',
    'Lantern path', '.KidPlays was slain by Zombie', 'Alex made the advancement Stone Age',
    'Saved 4 min ago', 'backed up 1 h ago']) {
    if (want && !t.includes(want)) problems.push(`${width}: "${want}" is not on the card`);
  }
  if (/tps|latency/i.test(t)) problems.push(`${width}: the card mentions TPS or latency`);
  if (t.includes('The world was saved')) problems.push(`${width}: a save is in the feed`);
  if (t.includes('kitchen')) problems.push(`${width}: a non-Minecraft entity rendered`);
  const audit = await page.evaluate(() => {
    const root = window.card.shadowRoot;
    const all = [...root.querySelectorAll('*')];
    const small = all.filter((el) => el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
      && parseFloat(getComputedStyle(el).fontSize) < 11).map((el) => el.className || el.tagName);
    const fixed = all.filter((el) => ['fixed', 'sticky'].includes(getComputedStyle(el).position)).length;
    const col = document.getElementById('col').getBoundingClientRect();
    const wide = all.filter((el) => el.getBoundingClientRect().right > col.right + 0.5).map((el) => el.className || el.tagName);
    const img = root.querySelector('.shot img');
    return { buttons: root.querySelectorAll('button, [role=button], a, input, select').length,
      titles: root.querySelectorAll('[title]').length, fixed, small, wide,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      img: img ? img.getAttribute('src') : null, bar: root.querySelector('.bar i')?.style.width,
      height: window.card.getBoundingClientRect().height };
  });
  if (audit.buttons) problems.push(`${width}: ${audit.buttons} controls on a card that should have none`);
  if (audit.titles) problems.push(`${width}: hover text (title=) on ${audit.titles} elements`);
  if (audit.fixed) problems.push(`${width}: ${audit.fixed} floating elements`);
  if (audit.small.length) problems.push(`${width}: text under 11px: ${audit.small.join(', ')}`);
  if (audit.wide.length) problems.push(`${width}: wider than its column: ${audit.wide.slice(0, 5).join(', ')}`);
  if (audit.overflow) problems.push(`${width}: the page scrolls sideways`);
  if (!audit.img || !audit.img.startsWith('/local/minecraft/')) problems.push(`${width}: the finished build's picture is not shown`);
  if (audit.bar !== '40%') problems.push(`${width}: the progress bar is ${audit.bar}`);
  await page.waitForFunction(() => {
    const img = window.card.shadowRoot.querySelector('.shot img');
    return img && img.complete && img.naturalWidth > 0;
  }, null, { timeout: 5000 }).catch(() => problems.push(`${width}: the build picture did not load`));
  console.log(`${width}px: card ${Math.round(audit.height)}px tall`);
  await page.screenshot({ path: `/tmp/measure-minecraft-card-${width}.png`, fullPage: true }).catch(() => {});

  // A state change redraws; an identical one does not.
  const redrawn = await page.evaluate((house) => {
    const before = window.card.shadowRoot.querySelector('.wrap');
    window.card.hass = { states: { ...house }, entities: {} };
    const same = window.card.shadowRoot.querySelector('.wrap') === before;
    const next = JSON.parse(JSON.stringify(house));
    next['sensor.bruh_minecraft_server_vesper_building'].attributes.current.progress = 55;
    window.card.hass = { states: next, entities: {} };
    return { same, now: window.card.shadowRoot.querySelector('.bar i').style.width };
  }, HOUSE);
  if (!redrawn.same) problems.push(`${width}: an unchanged hass redrew the card`);
  if (redrawn.now !== '55%') problems.push(`${width}: progress did not follow the sensor (${redrawn.now})`);
  await page.close();
}

// Nobody on: who was on last, and still the world and Vesper.
{
  const quiet = JSON.parse(JSON.stringify(HOUSE));
  quiet[`${P}players_online`] = st('players_online', 0, { players: [], details: [] });
  const page = await mount(390, 358, quiet);
  const t = await text(page);
  if (!t.includes('Nobody is on. Last on: Alex just now')) problems.push(`nobody on: "${t.slice(0, 200)}"`);
  if (!t.includes('Watchtower')) problems.push('nobody on: Vesper is gone from the card');
  await page.close();
}
// The server down: the world says so, the history stays.
{
  const down = JSON.parse(JSON.stringify(HOUSE));
  down[`${P}world_time`] = st('world_time', 'unknown');
  down[`${P}world_day`] = st('world_day', 'unknown');
  down[`${P}players_online`] = st('players_online', 0, { players: [], details: [] });
  const page = await mount(390, 358, down);
  const t = await text(page);
  if (!t.includes('The world is not running right now.')) problems.push(`down: "${t.slice(0, 200)}"`);
  if (!t.includes('slain by Zombie')) problems.push('down: the feed is gone');
  await page.close();
}
// An integration without the world sensors.
{
  const page = await mount(390, 358, { 'light.kitchen': HOUSE['light.kitchen'] });
  const t = await text(page);
  if (!t.includes('Update the BRUH Minecraft add-on')) problems.push(`no sensors: "${t.slice(0, 200)}"`);
  await page.close();
}

await browser.close();
if (problems.length) {
  console.error(`FAIL (${problems.length})\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log('OK: the world card says what is going on, at 390 and 1200, with no controls');
