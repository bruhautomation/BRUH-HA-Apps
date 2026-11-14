/**
 * Morph's features on a Home Assistant dashboard (frontend/morph-features.js):
 *
 *   - custom:morph-view draws HA's own sections in the order they are
 *     written: nothing is lifted and no room folds (5.3.0);
 *   - the room rail (scrub.js) is drawn with one notch per room plus the
 *     top, a swipe left on it opens it and sliding goes room to room, and
 *     `morph: {rail: false}` turns it off;
 *   - the cases card draws brAIn's cases (all, or one area's) and a press
 *     goes to brAIn's queue (morph/case);
 *   - the Ask card answers from brAIn's interpreter, and a change to the
 *     dashboard it is on becomes a Tell on that dashboard.
 *
 *   node tests/manual/measure-morph-features.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { FRONTEND } from './morph-fixture.mjs';

const ORIGIN = 'http://features.test';
const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ['--no-sandbox'] });
const old = new Date(Date.now() - 3600e3).toISOString();

const PAGE = `<!doctype html><html><head><meta charset="utf-8"><style>
html{--primary-background-color:#fafafa;--card-background-color:#fff;--primary-text-color:#212121;--secondary-text-color:#727272;--divider-color:rgba(0,0,0,.12);--primary-color:#03a9f4}
body{margin:0;background:var(--primary-background-color);font-family:Arial}
</style></head><body><script>
window.__ws = [];
const S = (s, a) => ({ state: s, attributes: a || {}, last_changed: '${old}' });
window.__hass = { user: { is_admin: true }, entities: { 'light.kitchen': { area_id: 'kitchen' } }, states: {
  'light.kitchen': S('on', { friendly_name: 'Kitchen Cans' }),
  'light.bedroom': S('off', { friendly_name: 'Bedroom Lamp' }),
  'lock.front': S('unlocked', { friendly_name: 'Front Door' }),
}, async callWS(m) {
  window.__ws.push(m);
  if (m.type === 'morph/load') return { brain: { cases: [
    { id: 'f:1', kind: 'problem', claim: 'The kitchen cans flicker', entity_id: 'light.kitchen', answers: [{ action: 'fix', label: 'Fix' }, { action: 'dismiss', label: 'Dismiss' }] },
    { id: 'f:2', kind: 'question', claim: 'Is the garage freezer new?', area_id: 'garage' } ] }, features: { name: 'Juniper' } };
  if (m.type === 'morph/case') return { ok: true };
  if (m.type === 'morph/ask') return m.text.includes('bigger') ? { do: 'tell_dashboard', tell_text: 'make the kitchen bigger' } : { do: 'done', say: 'The front door is unlocked.' };
  if (m.type === 'morph/dashboards') return { dashboards: [{ key: 'default', url_path: 'lovelace', title: 'Home', morphed: true }] };
  if (m.type === 'morph/request') return { ok: true, id: 'morph-9' };
  if (m.type === 'morph/tell_status') return { phase: 'done', say: 'Made the kitchen bigger.' };
  return {};
}, connection: { subscribeMessage: () => Promise.resolve(() => {}) } };
customElements.define('ha-card', class extends HTMLElement {});
customElements.define('hui-section', class extends HTMLElement {
  connectedCallback() { this.innerHTML = '<div style="height:120px;background:#fff;border-radius:12px;padding:12px">' + this.config.cards[0].heading + '</div>'; }
});
const root = document.createElement('home-assistant');
root.attachShadow({ mode: 'open' });
root.hass = window.__hass;
const panel = document.createElement('ha-panel-lovelace');
panel.panel = { url_path: 'lovelace' };
root.shadowRoot.appendChild(panel);
document.body.appendChild(root);
window.__mkView = (morph, editing) => {
  document.querySelector('morph-view')?.remove();
  const sections = [
    { type: 'grid', cards: [{ type: 'heading', heading: 'Kitchen' }, { type: 'tile', entity: 'light.kitchen' }] },
    { type: 'grid', cards: [{ type: 'heading', heading: 'Bedroom' }, { type: 'tile', entity: 'light.bedroom' }] },
    { type: 'grid', cards: [{ type: 'heading', heading: 'Entry' }, { type: 'tile', entity: 'lock.front' }] },
  ];
  const v = document.createElement('morph-view');
  v.setConfig({ type: 'custom:morph-view', sections, ...(morph ? { morph } : {}) });
  v.lovelace = { editMode: !!editing, config: {} };
  v.sections = sections.map((c) => { const e = document.createElement('hui-section'); e.config = c; return e; });
  v.hass = window.__hass;
  document.body.appendChild(v);
  return v;
};
</script><script type="module" src="/morph_static/test/morph-features.js"></script></body></html>`;

async function open(touch) {
  const ctx = await browser.newContext(touch ? { viewport: { width: 400, height: 800 }, hasTouch: true, isMobile: true } : { viewport: { width: 1200, height: 900 } });
  await ctx.route(`${ORIGIN}/**`, async (r) => {
    const url = new URL(r.request().url());
    if (url.pathname === '/') return r.fulfill({ contentType: 'text/html', body: PAGE });
    const m = url.pathname.match(/^\/morph_static\/[^/]+\/(.+)$/);
    if (m) { try { return r.fulfill({ contentType: 'text/javascript', body: readFileSync(path.join(FRONTEND, path.basename(m[1])), 'utf8') }); } catch (e) { return r.fulfill({ status: 404 }); } }
    return r.fulfill({ status: 404, body: '' });
  });
  const p = await ctx.newPage();
  p.errors = [];
  p.on('pageerror', (e) => p.errors.push(String(e)));
  await p.goto(`${ORIGIN}/`);
  await p.waitForFunction(() => !!customElements.get('morph-view'), null, { timeout: 5000 }).catch(() => fail('load', 'morph-view never defined'));
  return p;
}
const view = (p) => p.evaluate(() => {
  const v = document.querySelector('morph-view');
  return [...v.shadowRoot.querySelectorAll('section.sec')].map((s) => ({ name: s.querySelector('h2').textContent, has: !!s.querySelector('hui-section') }));
});

let p = await open(false);
await p.evaluate(() => window.__mkView());
await p.waitForTimeout(150);
let v = await view(p);
if (v.map((r) => r.name).join() !== 'Kitchen,Bedroom,Entry') fail('order', `rooms in order ${v.map((r) => r.name)} (want the written order)`);
if (v.some((r) => !r.has)) fail('rooms', `a room is drawn empty ${JSON.stringify(v)}`);
await p.evaluate(() => window.__mkView(null, true));
await p.waitForTimeout(100);
v = await view(p);
if (v.map((r) => r.name).join() !== 'Kitchen,Bedroom,Entry') fail('edit mode', JSON.stringify(v.map((r) => r.name)));
const rail0 = await p.evaluate(() => { const r = document.querySelector('morph-view').shadowRoot.querySelector('.mrail'); return r ? getComputedStyle(r).display : 'none'; });
if (rail0 !== 'none') fail('rail', `the rail is drawn on a fine pointer (${rail0})`);

// Cases: all, then one area's; a press reaches brAIn's queue.
const cases = await p.evaluate(async () => {
  const mk = (cfg) => { const c = document.createElement('morph-cases-card'); c.setConfig(cfg); document.body.appendChild(c); c.hass = window.__hass; return c; };
  const all = mk({ title: 'brAIn' }); const kitchen = mk({ area: 'kitchen' });
  await new Promise((r) => setTimeout(r, 300));
  const claims = (c) => [...c.shadowRoot.querySelectorAll('.claim')].map((x) => x.textContent);
  const out = { all: claims(all), kitchen: claims(kitchen) };
  kitchen.shadowRoot.querySelector('[data-act="case"]').click();
  await new Promise((r) => setTimeout(r, 100));
  out.sent = window.__ws.filter((m) => m.type === 'morph/case');
  return out;
});
if (cases.all.length !== 2) fail('cases', `all: ${cases.all}`);
if (cases.kitchen.join() !== 'The kitchen cans flicker') fail('cases', `kitchen: ${cases.kitchen}`);
if (!(cases.sent.length === 1 && cases.sent[0].case === 'f:1' && cases.sent[0].action === 'fix')) fail('cases', `sent ${JSON.stringify(cases.sent)}`);

// Ask: an answer, then a change to this dashboard as a Tell on it.
const ask = await p.evaluate(async () => {
  const a = document.createElement('morph-ask-card'); a.setConfig({}); a.hass = window.__hass; document.body.appendChild(a);
  const say = async (t) => { a.shadowRoot.querySelector('input').value = t; a.shadowRoot.querySelector('form').requestSubmit(); await new Promise((r) => setTimeout(r, 1500)); return a.shadowRoot.querySelector('.ans').textContent; };
  const one = await say('is the door locked?');
  const two = await say('make the kitchen bigger');
  return { one, two, tell: window.__ws.find((m) => m.type === 'morph/request') };
});
if (ask.one !== 'The front door is unlocked.') fail('ask', `answer "${ask.one}"`);
if (ask.two !== 'Made the kitchen bigger.') fail('ask', `tell ended "${ask.two}"`);
if (!ask.tell || ask.tell.payload.target.kind !== 'lovelace' || ask.tell.payload.target.dashboard !== 'default' || ask.tell.payload.text !== 'make the kitchen bigger') fail('ask', `tell ${JSON.stringify(ask.tell)}`);
if (p.errors.length) fail('console', p.errors.slice(0, 3).join(' | '));
await p.context().close();

// A phone: the rail, one notch per open room; off by the view's option.
p = await open(true);
await p.evaluate(() => window.__mkView());
await p.waitForTimeout(300);
const rail = await p.evaluate(() => { const r = document.querySelector('morph-view').shadowRoot.querySelector('.mrail'); if (!r) return null; const b = r.getBoundingClientRect(); return { notches: r.querySelectorAll('.mrail-seg').length, x: b.right - 8, y: b.top + 4, h: b.height }; });
if (!rail || rail.notches !== 4) fail('rail', `phone rail ${JSON.stringify(rail)} (want 4 notches: the top and three rooms)`);
if (rail) {
  // Rooms taller than the screen, so going to the last one has to scroll.
  await p.evaluate(() => { document.querySelector('morph-view').style.setProperty('--mv-col', '5000px'); document.querySelector('morph-view').shadowRoot.querySelectorAll('hui-section > div').forEach((d) => { d.style.height = '1600px'; }); });
  await p.waitForTimeout(400);
  await p.mouse.move(rail.x, rail.y + rail.h * 0.1); await p.mouse.down();
  for (let i = 1; i <= 8; i++) { await p.mouse.move(rail.x - i * 3, rail.y + rail.h * 0.1); await p.waitForTimeout(16); }
  for (let i = 1; i <= 8; i++) { await p.mouse.move(rail.x - 24, rail.y + rail.h * (0.1 + i * 0.1)); await p.waitForTimeout(30); }
  await p.mouse.up(); await p.waitForTimeout(1200);
  const lit = await p.evaluate(() => ({ y: window.scrollY, open: !!document.querySelector('morph-view').shadowRoot.querySelector('.mrail.open') }));
  if (lit.open) fail('rail', 'the rail stayed open after the finger lifted');
  if (!(lit.y > 0)) fail('rail', `sliding down the rail did not move the page (scrollY ${lit.y})`);
}
await p.evaluate(() => window.__mkView({ rail: false }));
await p.waitForTimeout(200);
const off = await p.evaluate(() => !document.querySelector('morph-view').shadowRoot.querySelector('.mrail'));
if (!off) fail('rail', 'morph: {rail: false} still draws the rail');
if (p.errors.length) fail('console (phone)', p.errors.slice(0, 3).join(' | '));
await browser.close();
if (problems.length) {
  console.log(`measure-morph-features: ${problems.length} problem(s)`);
  problems.forEach((x) => console.log(' - ' + x));
  process.exit(1);
}
console.log('measure-morph-features: ok');
