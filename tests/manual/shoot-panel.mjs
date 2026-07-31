// Screenshot the live seeded brAIn panel, one PNG per tab, at a size that
// suits a docs page rather than a 4K monitor.
//
// Start the panel first:  python3 tests/manual/demo_panel.py /tmp/brain-demo
// Then:                   SHOT_DIR=shots node tests/manual/shoot-panel.mjs
//
// Light and dark for every tab, plus one phone shot — the two-row bar is a
// real part of the story and only shows up under the breakpoint. The pointer
// is parked off-canvas before each capture because a tab still under the
// cursor keeps its tooltip open, and a tooltip in a docs screenshot reads as
// chrome rather than as content.
import { chromium } from 'playwright';
import path from 'node:path';

const OUT = process.env.SHOT_DIR || 'shots';
const BASE = 'http://127.0.0.1:8099/';
const WIDTH = Number(process.env.SHOT_W || 1280);
const HEIGHT = Number(process.env.SHOT_H || 860);

const TABS = [
  ['insights', 'panel-insights'],
  ['findings', 'panel-findings'],
  ['terminal', 'panel-terminal'],
  ['memory', 'panel-memory'],
  ['docs', 'panel-docs'],
];

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const theme of ['light', 'dark']) {
  const ctx = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 2,
    colorScheme: theme,
  });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') console.log('  js:', m.text()); });

  for (const [view, name] of TABS) {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForTimeout(900);
    if (view !== 'insights') {
      await page.click(`.viewtab[data-view="${view}"]`);
      await page.waitForTimeout(600);
    }
    // Park the pointer off-canvas: a tab still under the cursor keeps its
    // tooltip open, and a tooltip in a docs screenshot reads as chrome.
    await page.mouse.move(WIDTH - 2, HEIGHT - 2);
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(OUT, `${name}-${theme}.png`) });
    console.log(`${name}-${theme}.png`);
  }
  await ctx.close();
}

// A phone shot: the two-row bar is a real part of the story.
const phone = await browser.newContext({
  viewport: { width: 390, height: 800 },
  deviceScaleFactor: 3,
  colorScheme: 'dark',
  isMobile: true,
  hasTouch: true,
});
const p = await phone.newPage();
await p.goto(BASE, { waitUntil: 'networkidle' });
await p.waitForTimeout(1200);
await p.screenshot({ path: path.join(OUT, 'panel-phone-dark.png') });
console.log('panel-phone-dark.png');
await phone.close();

await browser.close();
