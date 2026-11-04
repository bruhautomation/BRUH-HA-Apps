/**
 * The brAIn layer on a Home Assistant dashboard (frontend/brain-layer.js),
 * on a stand-in for HA's page: <home-assistant> holding a lovelace panel
 * whose cards are hui-card elements carrying the very config objects of the
 * dashboard's config, the way HA's frontend hands them out. Checks:
 *
 *   - nothing is drawn for somebody who is not an administrator;
 *   - a dashboard brAIn does not keep offers "Let brAIn change it", and
 *     the press sends morph/dashboard_morph;
 *   - picking a card: the press does NOT reach the card, the card's YAML
 *     path is found, its picture is sent, and the Tell carries the path;
 *   - a copy of a card type asks "Just this one" or "Every copy", and the
 *     choice rides as context;
 *   - the Tell's steps, its result and what changed are shown; Undo sends
 *     tell_undo; History lists commits and Restore sends the sha.
 *
 *   node tests/manual/measure-brain-layer.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { FRONTEND } from './morph-fixture.mjs';

const ORIGIN = 'http://layer.test';
const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });

const page = (admin, morphed) => `<!doctype html><html><head><meta charset="utf-8"><style>
html{--primary-color:#03a9f4;--card-background-color:#fff;--primary-text-color:#212121;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12)}
body{margin:0;background:#fafafa;font-family:Arial}
</style></head><body><script>
window.__ws = []; window.__clicks = 0;
const CFG = { title: 'Home', views: [{ title: 'Home', path: 'home', sections: [{ type: 'grid', cards: [
  { type: 'heading', heading: 'Kitchen' },
  { type: 'tile', entity: 'light.kitchen' },
  { type: 'custom:morph-type-thermo', entity: 'climate.a' } ] }] }] };
let status = 0;
const hass = { user: { is_admin: ${admin} }, states: {}, async callWS(m) {
  window.__ws.push(m);
  if (m.type === 'morph/dashboards') return { dashboards: [{ key: 'default', url_path: 'lovelace', title: 'Home', mode: 'storage', morphed: ${morphed} }], admin: ${admin} };
  if (m.type === 'morph/dashboard_morph') return { ok: true, morphed: m.on };
  if (m.type === 'morph/types') return { types: [{ slug: 'thermo', name: 'Thermostat', used: [{}, {}, {}] }] };
  if (m.type === 'morph/shot') return { shot: 'shot-1' };
  if (m.type === 'morph/tell_status') { status += 1; return status < 2 ? { phase: 'working', steps: [{ t: 'Reading Home › Kitchen' }] } : { phase: 'done', say: 'Made it bigger.', shows: ['Changed the tile card (light.kitchen) in Home › Kitchen'], commit: 'abc123', steps: [] }; }
  if (m.type === 'morph/request' && m.kind === 'tell') return { ok: true, id: 'morph-1', phase: 'sending' };
  if (m.type === 'morph/request' && m.kind === 'tell_undo') return { ok: true };
  if (m.type === 'morph/request' && m.kind === 'history') return { ok: true, log: [{ sha: 'new1', message: 'brAIn: bigger', who: 'brain', at: 1700000000 }, { sha: 'old1', message: 'Started keeping Home', who: 'morph', at: 1690000000 }] };
  if (m.type === 'morph/request' && m.kind === 'restore') return { ok: true };
  return {};
} };
customElements.define('ha-card', class extends HTMLElement {});
customElements.define('hui-card', class extends HTMLElement {
  connectedCallback() { this.innerHTML = '<ha-card style="display:block;height:60px;margin:8px;background:#fff;border:1px solid #ddd;border-radius:12px;padding:12px">' + (this.config.entity || this.config.heading) + '</ha-card>'; this.addEventListener('click', () => { window.__clicks += 1; }); }
});
customElements.define('ha-panel-lovelace', class extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); }
  connectedCallback() {
    const view = document.createElement('div');
    CFG.views[0].sections[0].cards.forEach((c) => { const el = document.createElement('hui-card'); el.config = c; view.appendChild(el); });
    this.shadowRoot.appendChild(view);
  }
});
customElements.define('home-assistant', class extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); this.hass = hass; }
  connectedCallback() { const p = document.createElement('ha-panel-lovelace'); p.panel = { url_path: 'lovelace' }; p.lovelace = { config: CFG }; this.shadowRoot.appendChild(p); }
});
history.replaceState(null, '', '/lovelace/home');
document.body.appendChild(document.createElement('home-assistant'));
</script><script type="module" src="/morph_static/test/brain-layer.js"></script></body></html>`;

async function open(admin, morphed) {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  await ctx.route(`${ORIGIN}/**`, async (r) => {
    const url = new URL(r.request().url());
    if (url.pathname.startsWith('/lovelace')) return r.fulfill({ contentType: 'text/html', body: page(admin, morphed) });
    const m = url.pathname.match(/^\/morph_static\/[^/]+\/(.+)$/);
    if (m) {
      try { return r.fulfill({ contentType: 'text/javascript', body: readFileSync(path.join(FRONTEND, path.basename(m[1])), 'utf8') }); } catch (e) { return r.fulfill({ status: 404 }); }
    }
    return r.fulfill({ status: 404, body: '' });
  });
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', (e) => p.errors.push(String(e)));
  await p.goto(`${ORIGIN}/lovelace/home`);
  await p.waitForTimeout(700);
  return p;
}
const L = (p, sel) => p.evaluate((sel) => { const l = document.querySelector('brain-layer'); return l && l.shadowRoot.querySelector(sel) ? l.shadowRoot.querySelector(sel).textContent : null; }, sel);
const press = (p, sel) => p.evaluate((sel) => { document.querySelector('brain-layer').shadowRoot.querySelector(sel).click(); }, sel);
const ws = (p, type, kind) => p.evaluate(([t, k]) => window.__ws.filter((m) => m.type === t && (!k || m.kind === k)), [type, kind]);

// Not an administrator: nothing.
let p = await open(false, true);
if (await L(p, '.fab') !== null) fail('non-admin', 'the brAIn button is drawn');
await p.context().close();

// A dashboard brAIn does not keep yet.
p = await open(true, false);
if (await L(p, '.fab') === null) fail('offer', 'no brAIn button');
await press(p, '.fab');
const offer = await L(p, '.sheet');
if (!/Let brAIn change Home/.test(offer || '')) fail('offer', `sheet says "${(offer || '').slice(0, 80)}"`);
await press(p, '[data-a="morph"]');
await p.waitForTimeout(200);
const sent = await ws(p, 'morph/dashboard_morph');
if (!(sent.length === 1 && sent[0].key === 'default' && sent[0].on === true)) fail('offer', `sent ${JSON.stringify(sent)}`);
await p.context().close();

// A kept dashboard: pick a card, tell, follow, undo.
p = await open(true, true);
await press(p, '.fab');
if (!/Tell brAIn about a card/.test(await L(p, '.sheet') || '')) fail('menu', 'no "Tell brAIn about a card"');
await press(p, '[data-a="pick"]');
await p.waitForTimeout(100);
if (!/Tap the card you mean/.test(await L(p, '.pick') || '')) fail('pick', 'no instruction while picking');
const box = await p.evaluate(() => {
  const panel = document.querySelector('home-assistant').shadowRoot.querySelector('ha-panel-lovelace');
  const r = panel.shadowRoot.querySelectorAll('hui-card')[1].getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
});
await p.mouse.move(box.x, box.y);
await p.waitForTimeout(80);
if (await p.evaluate(() => !document.querySelector('brain-layer').shadowRoot.querySelector('.ring'))) fail('pick', 'no ring on the card under the pointer');
await p.mouse.click(box.x, box.y);
await p.waitForTimeout(400);
if (await p.evaluate(() => window.__clicks)) fail('pick', 'the press reached the card');
const where = await L(p, '.sheet .sm');
if (where !== 'Home › tile card (light.kitchen)') fail('pick', `where is "${where}"`);
await p.waitForTimeout(1200);
const shots = await ws(p, 'morph/shot');
if (shots.length !== 1 || !String(shots[0].png).startsWith('data:image/png')) fail('picture', `shots sent: ${shots.length}`);
await p.evaluate(() => { document.querySelector('brain-layer').shadowRoot.querySelector('textarea').value = 'make it bigger'; });
await press(p, '[data-a="send"]');
await p.waitForTimeout(300);
const tells = await ws(p, 'morph/request', 'tell');
const tp = tells[0] && tells[0].payload;
if (!tp) fail('tell', 'no tell sent');
else {
  if (tp.target.kind !== 'lovelace' || tp.target.dashboard !== 'default') fail('tell', `target ${JSON.stringify(tp.target)}`);
  if (tp.target.at !== JSON.stringify(['views', 0, 'sections', 0, 'cards', 1])) fail('tell', `path ${tp.target.at}`);
  if (tp.text !== 'make it bigger' || tp.shot !== 'shot-1') fail('tell', `text ${tp.text} shot ${tp.shot}`);
}
await p.waitForTimeout(2500);
const done = await L(p, '.sheet');
if (!/Made it bigger\./.test(done || '') || !/Changed the tile card/.test(done || '')) fail('result', `sheet says "${(done || '').slice(0, 160)}"`);
await press(p, '[data-a="undo"]');
await p.waitForTimeout(200);
const undos = await ws(p, 'morph/request', 'tell_undo');
if (!(undos.length === 1 && undos[0].payload.id === 'morph-1')) fail('undo', JSON.stringify(undos));
if (!/Put back\./.test(await L(p, '.sheet') || '')) fail('undo', 'does not say it was put back');

// A copy of a card type: this one or every copy.
await press(p, '[data-a="close"]');
await press(p, '.fab');
await press(p, '[data-a="pick"]');
const b2 = await p.evaluate(() => {
  const panel = document.querySelector('home-assistant').shadowRoot.querySelector('ha-panel-lovelace');
  const r = panel.shadowRoot.querySelectorAll('hui-card')[2].getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
});
await p.mouse.click(b2.x, b2.y);
await p.waitForTimeout(500);
const choice = await L(p, '.sheet');
if (!/copy of the card type “Thermostat”, used in 3 places/.test(choice || '')) fail('type', `sheet says "${(choice || '').slice(0, 160)}"`);
await press(p, '[data-a="scope"][data-v="type"]');
await p.evaluate(() => { document.querySelector('brain-layer').shadowRoot.querySelector('textarea').value = 'add a boost button'; });
await press(p, '[data-a="send"]');
await p.waitForTimeout(300);
const t2 = (await ws(p, 'morph/request', 'tell'))[1];
if (!t2 || !/change the card type “thermo” itself, so every copy of it changes \(3 copies\)/.test(t2.payload.context)) fail('type', `context ${t2 && t2.payload.context}`);

// History and Restore.
await press(p, '[data-a="close"]');
await press(p, '.fab');
await press(p, '[data-a="history"]');
await p.waitForTimeout(300);
const hist = await L(p, '.sheet');
if (!/brAIn: bigger/.test(hist || '') || !/Started keeping Home/.test(hist || '')) fail('history', `sheet says "${(hist || '').slice(0, 120)}"`);
await press(p, '[data-a="restore"]');
await p.waitForTimeout(300);
const rs = await ws(p, 'morph/request', 'restore');
if (!(rs.length === 1 && rs[0].payload.sha === 'old1' && rs[0].payload.dashboard === 'default')) fail('restore', JSON.stringify(rs));
if (p.errors.length) fail('console', p.errors.slice(0, 3).join(' | '));
await browser.close();
if (problems.length) {
  console.log(`measure-brain-layer: ${problems.length} problem(s)`);
  problems.forEach((x) => console.log(' - ' + x));
  process.exit(1);
}
console.log('measure-brain-layer: ok');
