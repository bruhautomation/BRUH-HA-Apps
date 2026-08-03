// Hover every visible [data-tip] control on the Findings tab, at five widths,
// and assert its tooltip lands inside the viewport.
//
// It didn't. Tooltips were a `::after` per control at `position: absolute;
// right: -4px` with a 240px max-width, so the bubble hung LEFTWARD from the
// control's right edge: anything whose right edge sat under ~236px from the
// viewport's left ran its text off the side of the screen. That was four of
// the six buttons under a finding at 390px and still two of them at 1100px,
// because the findings list starts at the left margin. Nothing in CSS can
// see the viewport edge, so nothing in CSS could have fixed it — the panel
// places one shared fixed-position element in JS and clamps it.
//
//   node tests/manual/measure-tooltips.mjs
//
// Playwright resolves from the repo's own node_modules; set CHROMIUM_PATH if
// it can't find a browser itself. Run it after adding a control with a
// tooltip, or after touching placeTip/.tipbox — a bubble that opens off the
// screen is invisible, and invisible is indistinguishable from "no tooltip".
import { chromium } from 'playwright';
import path from 'node:path';

const PANEL = path.resolve(
  path.dirname(new URL(import.meta.url).pathname), '../../brain/panel');
const OUT = process.env.TIP_SHOT_DIR || '';

const WIDTHS = [320, 390, 768, 1100, 1440];

// One of each card the tab draws, so both action rows are measured: a guess
// (two buttons) and a finding (six, which is the row that wrapped).
const PAYLOAD = {
  findings: [{
    ts: 1750000001, text: 'Front porch motion sensor has been on for 8 days',
    detail: 'sensor.front_porch_motion has reported `on` continuously since 26 Jul.',
    fix: 'Reload the Zigbee integration and re-pair the sensor.',
    severity: 'warning', fixable: true, entity_id: 'binary_sensor.front_porch_motion',
    source: 'devices', source_title: 'Device Health', status: 'open',
    result: '', changed: [], settled_at: 0, snoozed_until: 0,
  }],
  hypotheses: [{
    ts: 1750000009, text: 'The garage fridge is meant to run 24/7',
    topic: 'energy', status: 'open', settled_at: 0, note: '',
  }],
  open: 2, snoozed: 0, settled: [],
};

async function serveP(page) {
  await page.route('**/*', async (route) => {
    const url = route.request().url();
    const file = url.split('/').pop().split('?')[0];
    if (url.includes('api/findings')) {
      return route.fulfill({ contentType: 'application/json',
                             body: JSON.stringify(PAYLOAD) });
    }
    // The panel's JS needs a backend for everything else and does not get
    // one: this measures layout, not behaviour.
    if (url.includes('/api/')) return route.fulfill({ status: 500, body: '{}' });
    if (['index.html', ''].includes(file)) {
      return route.fulfill({ path: path.join(PANEL, 'index.html'),
                             contentType: 'text/html' });
    }
    try { return route.fulfill({ path: path.join(PANEL, file) }); }
    catch { return route.fulfill({ status: 404, body: '' }); }
  });
}

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
let bad = 0;

for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await serveP(page);
  await page.goto('http://panel/index.html');
  await page.waitForTimeout(600);
  await page.evaluate(() =>
    document.querySelector('.viewtab[data-view="findings"]').click());
  await page.waitForTimeout(600);
  // The toast is a fixed overlay and would sit on top of the shots.
  await page.evaluate(() => {
    const t = document.querySelector('#toast');
    if (t) t.remove();
  });

  console.log(`--- ${width}px ---`);
  const controls = await page.locator(
    '.finding [data-tip]:visible, .topbar [data-tip]:visible').all();
  for (const c of controls) {
    const label = ((await c.textContent()) || (await c.getAttribute('data-tip')))
      .replace(/\s+/g, ' ').trim().slice(0, 22);
    await c.hover();
    // Longer than the panel's own open delay, so a miss is a miss and not a race.
    await page.waitForTimeout(300);
    const m = await page.evaluate((vw) => {
      const box = document.querySelector('.tipbox');
      if (!box || !box.classList.contains('on')) return null;
      const r = box.getBoundingClientRect();
      return { left: Math.round(r.left), right: Math.round(r.right),
               top: Math.round(r.top), bottom: Math.round(r.bottom),
               vw, vh: document.documentElement.clientHeight };
    }, width);
    // A tooltip that never opened is as broken as one off the screen, and
    // looks the same to the person who wanted to read it.
    if (!m) { bad++; console.log(`MISSING ${label}`); continue; }
    const off = m.left < 0 || m.right > m.vw || m.top < 0 || m.bottom > m.vh;
    if (off) {
      bad++;
      console.log(`CLIPPED ${label.padEnd(24)} x [${m.left}, ${m.right}] `
        + `y [${m.top}, ${m.bottom}] in ${m.vw}x${m.vh}`);
    } else {
      console.log(`ok      ${label.padEnd(24)} x [${m.left}, ${m.right}]`);
    }
  }
  if (OUT) {
    await page.locator('.finding [data-tip]:visible').first().hover();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, `tip-${width}.png`) });
  }
  await page.close();
}
await browser.close();

console.log(bad ? `\n${bad} tooltip(s) off screen or missing`
                : '\nevery tooltip opened, and inside the viewport');
process.exit(bad ? 1 : 0);
