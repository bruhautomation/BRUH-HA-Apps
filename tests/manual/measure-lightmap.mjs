// Render BRight's Light Map with real fixtures and assert a dot is a light
// somebody can identify, select and move.
//
// The bug this exists to prevent: a dot was a role glyph in a circle with the
// light's name in a `title` attribute. A `title` is a hover tooltip, and the
// device most likely to be dragging lights around a floor plan has no hover —
// so on a phone you dragged an anonymous circle and found out afterwards what
// you had moved. There was no selection either, so the list underneath (which
// is where Remove lived) was disconnected from the picture above it: removing
// the right light was a guess.
//
// Unlike the brAIn measures, this drives the panel's REAL renderer rather than
// hand-built markup — `renderMap()` is the thing under test, and a copy of it
// in this file would only ever agree with itself. `fetch` is stubbed before
// any script runs, so the page never needs a backend.
//
// Checks, at phone and desktop widths:
//
//   * every dot carries a visible name (not a title attribute)
//   * no name spills off the floor it is drawn on — including the corners,
//     where a 44px dot centred on x=0 hangs half outside its own coordinate
//   * tapping a dot selects it: the dot, its row in the list, and the
//     selection bar all agree on which light that is
//   * the selection bar offers the two things you would want (role, remove)
//   * every control is a real touch target
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'bright', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 40;

// Corners on purpose: x=0.02 and x=0.98 are where the label would hang off
// the floor, and a room's lights live in its corners.
const FIXTURES = [
  { kind: 'lifx', serial: 'd073d5000001', id: 'lifx-d073d5000001', role: 'lamp',
    zone: 'living', label: 'Far left corner uplighter', x: 0.02, y: 0.3 },
  { kind: 'lifx', serial: 'd073d5000002', id: 'lifx-d073d5000002', role: 'strip',
    zone: 'living', label: 'TV backlight strip behind the telly', x: 0.98, y: 0.24 },
  { kind: 'lifx', serial: 'd073d5000003', id: 'lifx-d073d5000003', role: 'candle',
    zone: 'living', label: 'Mantel candle', x: 0.5, y: 0.98, reachable: false },
  { kind: 'ha', entity_id: 'switch.party_light', id: 'switch.party_light',
    role: 'party', zone: 'living', label: 'Disco ball', x: 0.5, y: 0.5 },
];

const ROLES = ['candle', 'downlight', 'lamp', 'strip', 'party', 'laser'];

// The stub REMEMBERS what the panel posts to it. A read-only stub can only
// ever prove that a control renders, and a control that renders and does
// not save is worse than no control: it reads as done. So an upsert lands
// in the same array the next GET serves, exactly as the store does, and
// `zones` is derived on read rather than kept — which is the server's own
// contract (a zone exists as long as a light is in it).
const STUB = `
window.__fixtures = ${JSON.stringify(FIXTURES)};
window.fetch = async (url, options) => {
  const path = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (path.includes('api/map/fixture')) {
    const sent = JSON.parse((options && options.body) || '{}');
    window.__posted = sent;
    window.__fixtures = window.__fixtures
      .filter((f) => f.id !== sent.id).concat([sent]);
    return answer({ fixture: sent });
  }
  if (path.includes('api/map')) {
    const zones = [...new Set(window.__fixtures
      .map((f) => String(f.zone || '').trim()).filter(Boolean))].sort();
    return answer({ version: 1, fixtures: window.__fixtures,
                    roles: ${JSON.stringify(ROLES)}, zones });
  }
  if (path.includes('api/status')) {
    return answer({ version: 'test', options: { music_folder: '/media/music' } });
  }
  return answer({});
};
`;

const failures = [];
const note = (width, message) => failures.push(`${width}px: ${message}`);

const browser = await chromium.launch();
for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(width, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.tab[data-tab="map"]');
  await page.waitForSelector('.map-dot');

  const named = await page.evaluate(() => {
    const dots = [...document.querySelectorAll('.map-dot')];
    return dots.map((dot) => {
      const label = dot.querySelector('.dot-name');
      return { id: dot.dataset.id, name: label ? label.textContent.trim() : '' };
    });
  });
  for (const dot of named) {
    if (!dot.name) note(width, `dot ${dot.id} renders no name`);
  }
  if (named.length !== FIXTURES.length) {
    note(width, `${named.length} dots for ${FIXTURES.length} lights`);
  }

  const spills = await page.evaluate(() => {
    const floor = document.getElementById('mapFloor').getBoundingClientRect();
    return [...document.querySelectorAll('.map-dot')].flatMap((dot) => {
      const box = dot.querySelector('.dot-name').getBoundingClientRect();
      const out = [];
      if (box.left < floor.left - 0.5) out.push(`${dot.dataset.id} left`);
      if (box.right > floor.right + 0.5) out.push(`${dot.dataset.id} right`);
      if (box.bottom > floor.bottom + 0.5) out.push(`${dot.dataset.id} bottom`);
      return out;
    });
  });
  for (const spill of spills) note(width, `name hangs off the floor: ${spill}`);

  // Select the way a person does, and check the three places agree.
  await page.locator('.map-dot').nth(1).click();
  await page.waitForTimeout(120);
  const selection = await page.evaluate(() => {
    const dot = document.querySelector('.map-dot.selected');
    const row = document.querySelector('#mapList .row.selected');
    const bar = document.getElementById('mapSelection');
    return {
      dot: dot && dot.dataset.id,
      row: row && row.dataset.id,
      barText: bar.textContent,
      hasRole: !!bar.querySelector('select'),
      hasZone: !!bar.querySelector('.zone-pick'),
      hasRemove: [...bar.querySelectorAll('button')]
        .some((b) => /remove/i.test(b.textContent)),
      // Inputs are measured too. The 44px floor was once written inside
      // `.demo-controls`, so it covered the controls that existed and
      // nothing added afterwards — which is how the role picker shipped at
      // the browser's default 19px. Anything added to this bar gets
      // measured by having been added.
      targets: [...bar.querySelectorAll('button, select, input')]
        .map((el) => Math.round(el.getBoundingClientRect().height)),
    };
  });
  const expected = FIXTURES[1];
  if (selection.dot !== expected.id) {
    note(width, `tapping a dot selected ${selection.dot} on the map`);
  }
  if (selection.row !== expected.id) {
    note(width, `the list did not follow the map (row: ${selection.row})`);
  }
  if (!selection.barText.includes(expected.label)) {
    note(width, 'the selection bar does not name the selected light');
  }
  if (!selection.hasRole) note(width, 'no role picker on the selected light');
  if (!selection.hasZone) {
    // Zone was settable only while ADDING a bulb, so the answer to "these
    // four are the kitchen" was to remove them and add them again.
    note(width, 'no zone field on the selected light');
  }
  if (!selection.hasRemove) note(width, 'no way to remove the selected light');
  for (const height of selection.targets) {
    if (height < MIN_TARGET) {
      note(width, `selection control is ${height}px tall (min ${MIN_TARGET})`);
    }
  }

  // A field that renders and does not save is worse than no field: it
  // reads as done. So type a zone, blur it, reload the map from the
  // server, and check the light came back wearing it.
  await page.fill('.zone-pick', 'Measured Zone');
  await page.locator('.zone-pick').blur();
  await page.waitForTimeout(400);
  const stored = await page.evaluate(async (id) => {
    const body = await (await fetch('api/map')).json();
    const fixture = (body.fixtures || []).find((f) => f.id === id);
    return { zone: fixture && fixture.zone, zones: body.zones || [],
             posted: window.__posted };
  }, expected.id);
  // The whole fixture has to go, not just the zone: the endpoint is an
  // upsert and a partial payload is a light that loses its role or its
  // place on the floor.
  for (const key of ['id', 'kind', 'role', 'x', 'y']) {
    if (stored.posted && stored.posted[key] === undefined) {
      note(width, `the save left ${key} out of the fixture it posted`);
    }
  }
  if (stored.zone !== 'Measured Zone') {
    note(width, `the zone did not save (server says ${stored.zone ?? 'nothing'})`);
  }
  if (!stored.zones.includes('Measured Zone')) {
    note(width, 'the saved zone is missing from the map payload, so nothing '
      + 'downstream can offer it');
  }

  await context.close();
}
await browser.close();

if (failures.length) {
  console.error('Light Map layout failures:');
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log(`Light Map: names, selection and targets OK at ${WIDTHS.join(', ')}px`);
