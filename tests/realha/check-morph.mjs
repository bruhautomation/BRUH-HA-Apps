// Morph on a REAL Home Assistant (docs/design/morph-on-lovelace.md §5).
//
//   python tests/realha/ha_rig.py up  <dir>     # HA running, owner onboarded
//   node   tests/realha/check-morph.mjs <dir> [out]
//   python tests/realha/ha_rig.py down <dir>
//
// Every other check of Morph's Home Assistant half runs on stand-ins for
// HA's page; this one runs in Home Assistant's own frontend, so what it
// passes is what a house sees. One line per check, PASS or FAIL, and the
// exit code is the number that failed. With `out`, the pictures are kept.
//
//  1. The converted Morph dashboard (convert.py, the real one) saves as a
//     sections dashboard and every card draws: no error card anywhere.
//  2. A Morph card FILLS the cell HA gives it, at every size somebody can
//     choose, and drops lines rather than spilling out of a small one.
//  3. Holding a card open at a fixed size grows its cell, and closing puts
//     it back (where the HA release has the cell; otherwise it scrolls).
//  4. HA's own visual editor edits a Morph card: every key it reads is in
//     the form, and the Layout tab is there.
//  5. Morph's view switches on HA's own sections view: a room that needs
//     somebody is lifted with why, and edit mode moves nothing.
//  6. brAIn's eyes: morph/eyes signs a page in as brAIn's system user, an
//     administrator, and the screenshot guard drops a service call.

import fs from 'node:fs';
import { chromium, rig, signedIn, ws, dashboard, deep } from './rig.mjs';

const dir = process.argv[2];
const out = process.argv[3] || '';
const r = rig(dir);
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`); };
const shot = async (page, name) => { if (out) await page.screenshot({ path: `${out}/${name}.png`, fullPage: true }); };

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const errors = [];
try {
  const ctx = await signedIn(browser, r);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(r.url + 'lovelace/0');
  await page.waitForTimeout(3000);
  const version = await page.evaluate(() => document.querySelector('home-assistant').hass.config.version);
  console.log(`Home Assistant ${version}`);

  // ---------------------------------------------------------------- 1
  const converted = JSON.parse(fs.readFileSync(`${dir}/converted.json`, 'utf8')).config;
  await dashboard(page, 'morph-home', converted, 'Home');
  await page.goto(r.url + 'morph-home/downstairs');
  await page.waitForTimeout(6000);
  await page.addScriptTag({ content: deep });
  const drawn = await page.evaluate(() => {
    const cards = window.__deepAll('hui-card');
    return {
      n: cards.length,
      errors: window.__deepAll('hui-error-card').map((e) => (e._config && e._config.error) || e.textContent.trim()).slice(0, 5),
      morph: cards.filter((c) => c.config && /^custom:morph-/.test(c.config.type) && c.firstElementChild && c.firstElementChild.shadowRoot && c.firstElementChild.shadowRoot.querySelector('.morph')).length,
      kinds: [...new Set(cards.map((c) => c.config && c.config.type))],
    };
  });
  const views = converted.views.map((v) => v.type);
  check('the converted dashboard is Home Assistant sections views', views.every((t) => t === 'sections'), views.join(','));
  check('every card of the converted dashboard draws', drawn.n > 15 && !drawn.errors.length, `${drawn.n} cards, ${drawn.morph} Morph cards${drawn.errors.length ? `; errors: ${drawn.errors.join(' | ')}` : ''}`);
  const heading = converted.views[0].sections.flatMap((s) => s.cards).find((c) => c.type === 'heading' && c.entities);
  check('a switch from a room’s title row is on its heading', heading && heading.entities[0].entity === 'switch.decorative_lights');
  await shot(page, 'converted');

  // ---------------------------------------------------------------- 2, 3
  const K = (k, e, g) => ({ type: `custom:morph-${k}-card`, ...e, ...(g ? { grid_options: g } : {}) });
  const sizes = [
    ['light', { entity: 'light.kitchen_lights' }, { columns: 6, rows: 1 }],
    ['light', { entity: 'light.bed_light' }, { columns: 6, rows: 3 }],
    ['sensor', { entity: 'sensor.outside_humidity' }, { columns: 3, rows: 1 }],
    ['sensor', { entity: 'sensor.outside_temperature' }, { columns: 12, rows: 4 }],
    ['climate', { entity: 'climate.heatpump' }, { columns: 12, rows: 2 }],
    ['camera', { entity: 'camera.demo_camera' }, { columns: 6, rows: 4 }],
    ['weather', { entity: 'weather.demo_weather_north' }, { columns: 6, rows: 1 }],
    ['media', { entity: 'media_player.kitchen' }, { columns: 12, rows: 1 }],
    ['readings', { entities: ['sensor.outside_temperature'] }, { columns: 12, rows: 6 }],
  ];
  await dashboard(page, 'morph-sizes', { views: [{ title: 'Sizes', path: 'sizes', type: 'sections', max_columns: 1, sections: [
    { type: 'grid', cards: [{ type: 'heading', heading: 'Sizes' }, ...sizes.map(([k, e, g]) => K(k, e, g)),
      K('light', { entity: 'light.office_rgbw_lights', detail: { type: 'entities', entities: ['light.office_rgbw_lights'] } })] }] }] }, 'Sizes');
  await page.goto(r.url + 'morph-sizes/sizes');
  await page.waitForTimeout(5000);
  await page.addScriptTag({ content: deep });
  const fit = await page.evaluate(() => window.__deepAll('hui-card').filter((c) => c.config && c.config.grid_options).map((c) => {
    const el = c.firstElementChild;
    const card = el.shadowRoot.querySelector('ha-card');
    const face = el.shadowRoot.querySelector('.face');
    const mc = el.shadowRoot.querySelector('.morph');
    const cell = c.getBoundingClientRect().height;
    return { kind: c.config.type, rows: c.config.grid_options.rows, cell: Math.round(cell), card: Math.round(card.getBoundingClientRect().height),
      face: Math.round(face ? face.getBoundingClientRect().height : 0), spill: Math.round(mc.scrollHeight - card.clientHeight), grid: el.hasAttribute('grid') };
  }));
  for (const f of fit) {
    const want = f.rows * 64 - 8;
    check(`${f.kind.replace('custom:morph-', '')} at ${f.rows} row(s) fills its cell`,
      f.grid && Math.abs(f.cell - want) <= 2 && f.face >= f.card - 4 && f.spill <= 2,
      `cell ${f.cell}px (want ${want}), face ${f.face}px, spill ${f.spill}px`);
  }
  await shot(page, 'sizes');

  const office = await page.evaluateHandle(() => window.__deepAll('morph-light-card').find((e) => e._config.entity === 'light.office_rgbw_lights'));
  await office.evaluate((e) => e.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(300);
  const before = await office.evaluate((e) => Math.round(e.parentElement.getBoundingClientRect().height));
  const box = await office.evaluate((e) => { const b = e.getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
  await page.mouse.move(box.x, box.y); await page.mouse.down(); await page.waitForTimeout(700); await page.mouse.up();
  await page.waitForTimeout(2500);
  const opened = await office.evaluate((e) => ({ open: e._open, grown: !!e._grown, cell: Math.round(e.parentElement.getBoundingClientRect().height),
    detail: !!e.shadowRoot.querySelector('.mcdetail > *'), clipped: (() => { const c = e.shadowRoot.querySelector('ha-card'); const m = e.shadowRoot.querySelector('.morph'); return Math.round(m.scrollHeight - c.clientHeight); })() }));
  if (opened.grown) {
    check('holding a card opens it and its cell grows', opened.open && opened.cell > before + 100 && opened.clipped <= 2, `${before}px → ${opened.cell}px`);
  } else {
    check('holding a card opens it; it scrolls inside its cell (this release has no fit-rows cell)', opened.open, `${opened.cell}px`);
  }
  check('the card under an opened card (detail) is mounted', opened.detail);
  await shot(page, 'opened');
  await office.evaluate((e) => e.toggleOpen(false));
  await page.waitForTimeout(400);
  const closed = await office.evaluate((e) => Math.round(e.parentElement.getBoundingClientRect().height));
  check('closing it puts its cell back', Math.abs(closed - before) <= 2, `${closed}px`);

  // ---------------------------------------------------------------- 4
  await page.goto(r.url + 'morph-sizes/sizes?edit=1');
  await page.waitForTimeout(4000);
  await page.addScriptTag({ content: deep });
  await page.evaluate(() => { const c = window.__deepAll('hui-card-edit-mode')[0] || window.__deepAll('hui-card')[0]; c.dispatchEvent(new CustomEvent('ll-edit-card', { detail: { path: [0, 0, 1] }, bubbles: true, composed: true })); });
  await page.waitForTimeout(3000);
  const form = await page.evaluate(() => {
    const f = window.__deepAll('ha-form').find((x) => (x.schema || []).some((s) => s.name === 'entity'));
    const names = [];
    const walk = (list) => (list || []).forEach((s) => { if (s.name) names.push(s.name); walk(s.schema); });
    if (f) walk(f.schema);
    // A tab says its name as text on current releases, as `label` (mwc-tab) on older ones.
    const tabs = window.__deepAll('*').filter((e) => /tab/.test(e.localName)).map((e) => String(e.label || e.textContent || '').trim());
    return { names, layout: tabs.some((t) => /^Layout$/i.test(t)), yamlOnly: !f };
  });
  for (const key of ['entity', 'name', 'icon', 'room', 'color', 'tap_action', 'hold_action', 'double_tap_action', 'detail']) {
    check(`the visual editor has ${key}`, form.names.includes(key));
  }
  check('the editor has HA’s Layout tab', form.layout);
  await shot(page, 'editor');

  // ---------------------------------------------------------------- 5
  const sec = (name, cards) => ({ type: 'grid', cards: [{ type: 'heading', heading: name }, ...cards] });
  await dashboard(page, 'morph-rooms', { views: [{ title: 'Rooms', path: 'rooms', type: 'sections', morph: { rail: true, order: true, fold: true }, sections: [
    sec('Bedroom', [K('light', { entity: 'light.bed_light' })]),
    sec('Back door', [K('lock', { entity: 'lock.kitchen_door' })]),
  ] }] }, 'Rooms');
  await page.goto(r.url + 'morph-rooms/rooms');
  await page.waitForTimeout(4500);
  await page.addScriptTag({ content: deep });
  const lifted = await page.evaluate(() => window.__deepAll('.section').filter((d) => d.hasAttribute('data-sec')).map((d) => [d.getAttribute('data-sec'), d.style.order, d.getAttribute('data-why')]));
  const door = lifted.find((x) => x[0] === 's1');
  check('a room that needs somebody is lifted, with why', door && door[1] === '0' && /unlocked/.test(door[2] || ''), JSON.stringify(lifted));
  await page.goto(r.url + 'morph-rooms/rooms?edit=1');
  await page.waitForTimeout(3500);
  await page.addScriptTag({ content: deep });
  const still = await page.evaluate(() => window.__deepAll('.section').filter((d) => d.style.order || d.hasAttribute('data-fold')).length);
  check('in edit mode nothing is moved or folded', still === 0);

  // ---------------------------------------------------------------- 6
  const eyes = await ws(page, { type: 'morph/eyes' });
  const listed = (eyes.dashboards || []).find((d) => d.url_path === 'morph-rooms');
  check('morph/eyes lists every dashboard with its tabs', listed && listed.views[0].path === 'rooms');
  const guard = fs.readFileSync(`${dir}/guard.js`, 'utf8');
  const eyesCtx = await signedIn(browser, { url: r.url, token: eyes.access_token });
  await eyesCtx.addInitScript({ content: guard });
  const seen = await eyesCtx.newPage();
  await seen.goto(r.url + 'morph-rooms/rooms');
  await seen.waitForTimeout(4000);
  const who = await seen.evaluate(() => { const h = document.querySelector('home-assistant').hass; return [h.user.name, h.user.is_admin]; });
  check('brAIn’s eyes sign in as its own system user, an administrator', who[0] === 'brAIn (screenshots)' && who[1], who.join(', '));
  const lightBefore = await seen.evaluate(() => document.querySelector('home-assistant').hass.states['light.bed_light'].state);
  await seen.evaluate(() => { document.querySelector('home-assistant').hass.callService('light', 'toggle', { entity_id: 'light.bed_light' }); });
  await seen.waitForTimeout(1500);
  const lightAfter = await page.evaluate(() => document.querySelector('home-assistant').hass.states['light.bed_light'].state);
  const held = await seen.evaluate(() => window.__brainHeldSockets || []);
  check('the screenshot guard drops a service call', lightAfter === lightBefore && held.includes('message call_service'), `${lightBefore} → ${lightAfter}`);
  await shot(seen, 'eyes');
} catch (e) {
  check('the checks ran to the end', false, String((e && e.stack) || e).slice(0, 400));
} finally {
  await browser.close();
}
const own = errors.filter((m) => /morph|brAIn|brain-layer/i.test(m));
check('no Morph module threw on the page', !own.length, own.slice(0, 3).join(' | '));
const failed = results.filter((x) => !x.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed);
