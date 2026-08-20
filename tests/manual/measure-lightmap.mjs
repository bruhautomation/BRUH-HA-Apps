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

const STUB = `
window.fetch = async (url) => {
  const path = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (path.includes('api/map')) {
    return answer({ version: 1, fixtures: ${JSON.stringify(FIXTURES)},
                    roles: ${JSON.stringify(ROLES)} });
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
      hasRemove: [...bar.querySelectorAll('button')]
        .some((b) => /remove/i.test(b.textContent)),
      targets: [...bar.querySelectorAll('button, select')]
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
  if (!selection.hasRemove) note(width, 'no way to remove the selected light');
  for (const height of selection.targets) {
    if (height < MIN_TARGET) {
      note(width, `selection control is ${height}px tall (min ${MIN_TARGET})`);
    }
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
