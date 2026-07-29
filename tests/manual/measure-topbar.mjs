// Render the BRain topbar across viewport widths and assert, per width, that
// it stays a single 48px row with nothing overflowing.
//
// Every child of the bar is `flex: none` except the spacer, so items cannot
// silently compress to fake a fit: the bar either holds its content or
// scrollWidth exceeds clientWidth. That makes one cheap check exact.
//
// The panel's JS needs a live backend, so we skip it and set the header into
// the state the phone screenshot showed: authenticated, a usage chip with a
// reset time, and the insights-view action buttons visible.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const PANEL = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../brain/panel');
const OUT = process.env.TOPBAR_SHOT_DIR || '';

const WIDTHS = [
  320, 360, 390, 400, 401, 414, 428, 469, 470, 480, 540, 600, 700, 760, 780,
  800, 804, 805, 840, 880, 900, 1000, 1023, 1099, 1100, 1200, 1440,
];
const KEEP_SHOTS = new Set([320, 390, 480, 780, 1200]);

// Busiest realistic header state.
function seed() {
  const $ = (s) => document.querySelector(s);
  $('#authChip').classList.add('ok');
  $('#authChipText').textContent = 'Claude · subscription';
  $('#usageChip').classList.remove('hidden');
  $('#usageChip').classList.add('ok');
  $('#usageChipPct').textContent = '19%';
  $('#usageChipText').textContent = 'used · resets 12:00 PM';
  ['#refreshAll', '#settingsBtn'].forEach((s) => $(s).classList.remove('hidden'));
  // Both tab badges present: the busiest the bar ever gets.
  ['#memBadge', '#findBadge'].forEach((s) => {
    $(s).textContent = '3';
    $(s).classList.remove('hidden');
  });
}

function probe() {
  const bar = document.querySelector('.topbar');
  const br = bar.getBoundingClientRect();
  const kids = [...bar.children]
    .filter((el) => getComputedStyle(el).display !== 'none')
    .map((el) => el.getBoundingClientRect())
    .filter((r) => r.width > 0);

  // A wrap means two items sit on separate lines. Differing tops alone just
  // means items of different heights are centred against each other.
  let lines = 1;
  const sorted = [...kids].sort((a, b) => a.top - b.top);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].top >= sorted[i - 1].bottom - 0.5) lines++;
  }

  return {
    height: Math.round(br.height),
    lines,
    escaped: kids.some((r) => r.bottom > br.bottom + 0.5 || r.top < br.top - 0.5),
    barScrollW: bar.scrollWidth,
    barClientW: bar.clientWidth,
    slack: Math.round(bar.querySelector('.spacer').getBoundingClientRect().width),
    docScrollW: document.documentElement.scrollWidth,
  };
}

(async () => {
  const browser = await chromium.launch(
    process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const page = await browser.newPage();

  const html = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8')
    .replace(/<script[^>]*src=[^>]*><\/script>/g, '');

  const rows = [];
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 760 });
    await page.setContent(html, { waitUntil: 'load' });
    await page.addStyleTag({ path: path.join(PANEL, 'style.css') });
    await page.evaluate(seed);

    const m = await page.evaluate(probe);
    const overflow = m.barScrollW > m.barClientW || m.escaped || m.docScrollW > width;
    rows.push({ width, ...m, oneRow: m.lines === 1, h48: m.height === 48, overflow });

    if (OUT && KEEP_SHOTS.has(width)) {
      await page.locator('.topbar').screenshot({ path: path.join(OUT, `bar-${width}.png`) });
    }
  }

  console.log('width  height  lines  scrollW/clientW  slack  verdict');
  let bad = 0;
  for (const r of rows) {
    const ok = r.oneRow && r.h48 && !r.overflow;
    if (!ok) bad++;
    console.log(
      String(r.width).padStart(5),
      String(r.height).padStart(7),
      String(r.lines).padStart(6),
      `     ${String(r.barScrollW).padStart(4)}/${String(r.barClientW).padStart(4)}`,
      String(r.slack).padStart(7),
      '  ' + (ok ? 'OK' : 'FAIL'
        + (r.oneRow ? '' : ' wrapped')
        + (r.h48 ? '' : ` height=${r.height}`)
        + (r.overflow ? ` overflow by ${r.barScrollW - r.barClientW}px` : '')),
    );
  }
  console.log(bad ? `\n${bad} width(s) failed` : '\nall widths: one row, 48px, no overflow');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
