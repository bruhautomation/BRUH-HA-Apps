/**
 * Morph's features on a Home Assistant dashboard (frontend/morph-features.js):
 *
 *   - custom:morph-view arranges HA's own sections: a room that needs
 *     somebody is lifted to the top with why, a quiet room folds to one line
 *     and opens on a tap, `morph: {order: false, fold: false}` keeps HA's
 *     order and everything open, and edit mode never folds or reorders;
 *   - on a touch screen the room rail is drawn with one notch per open room,
 *     and `morph: {rail: false}` turns it off;
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
  return [...v.shadowRoot.querySelectorAll('section.sec')].map((s) => ({ name: s.querySelector('h2').textContent, lifted: s.classList.contains('lifted'), why: s.querySelector('.why').hidden ? '' : s.querySelector('.why').textContent, folded: !s.querySelector('.fold').hidden, fold: s.querySelector('.fold').textContent, has: !!s.querySelector('hui-section') }));
});

let p = await open(false);
await p.evaluate(() => window.__mkView());
await p.waitForTimeout(150);
let v = await view(p);
if (v.map((r) => r.name).join() !== 'Entry,Kitchen,Bedroom') fail('order', `rooms in order ${v.map((r) => r.name)}`);
if (!v[0].lifted || v[0].why !== 'Front Door is unlocked') fail('lifted', JSON.stringify(v[0]));
if (v[1].folded || !v[1].has) fail('kitchen', `an active room is folded or empty ${JSON.stringify(v[1])}`);
if (!v[2].folded || !/Bedroom.*nothing on/.test(v[2].fold)) fail('fold', JSON.stringify(v[2]));
await p.evaluate(() => document.querySelector('morph-view').shadowRoot.querySelectorAll('.fold')[2].click());
await p.waitForTimeout(100);
v = await view(p);
if (v[2].folded || !v[2].has) fail('unfold', 'a tap did not open the folded room');
await p.evaluate(() => window.__mkView({ order: false, fold: false }));
await p.waitForTimeout(100);
v = await view(p);
if (v.map((r) => r.name).join() !== 'Kitchen,Bedroom,Entry' || v.some((r) => r.folded)) fail('options off', JSON.stringify(v.map((r) => [r.name, r.folded])));
await p.evaluate(() => window.__mkView(null, true));
await p.waitForTimeout(100);
v = await view(p);
if (v.map((r) => r.name).join() !== 'Kitchen,Bedroom,Entry' || v.some((r) => r.folded)) fail('edit mode', JSON.stringify(v.map((r) => [r.name, r.folded])));
const rail0 = await p.evaluate(() => { const r = document.querySelector('morph-view').shadowRoot.querySelector('.srail'); return getComputedStyle(r).display; });
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
const rail = await p.evaluate(() => { const r = document.querySelector('morph-view').shadowRoot.querySelector('.srail'); return { display: getComputedStyle(r).display, notches: r.querySelectorAll('.srnotches i').length }; });
if (rail.display === 'none' || rail.notches !== 2) fail('rail', `phone rail ${JSON.stringify(rail)} (want 2 notches: Entry and Kitchen; Bedroom is folded)`);
await p.evaluate(() => window.__mkView({ rail: false }));
await p.waitForTimeout(200);
const off = await p.evaluate(() => { const r = document.querySelector('morph-view').shadowRoot.querySelector('.srail'); return r.hidden; });
if (!off) fail('rail', 'morph: {rail: false} still draws the rail');
if (p.errors.length) fail('console (phone)', p.errors.slice(0, 3).join(' | '));
await browser.close();
if (problems.length) {
  console.log(`measure-morph-features: ${problems.length} problem(s)`);
  problems.forEach((x) => console.log(' - ' + x));
  process.exit(1);
}
console.log('measure-morph-features: ok');
