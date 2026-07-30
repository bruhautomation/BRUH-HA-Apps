// Render the brAIn topbar across viewport widths and assert, per width, that
// it stays a single 48px row with nothing overflowing.
//
// Every child of the bar is `flex: none` except the spacer, so items cannot
// silently compress to fake a fit: the bar either holds its content or
// scrollWidth exceeds clientWidth. That makes one cheap check exact.
//
// The panel's JS needs a live backend, so we skip it and set the header by
// hand. Three states are checked at every width. None is a superset of the
// others, because the floor band drops the usage chip in exactly the two
// states that put a chip beside it:
//
//   running   healthy login (no auth chip at all), both usage numbers, and a
//             count on both tab badges
//   paused    the same, plus the paused chip in its longest wording
//   broken    the same, plus the auth chip in its longest failure wording
//
// Measuring only one of them is how the failed-login bar came to overflow a
// 320px screen with nothing reporting it.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const PANEL = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../brain/panel');
const OUT = process.env.TOPBAR_SHOT_DIR || '';

const WIDTHS = [
  320, 360, 390, 400, 409, 410, 414, 428, 441, 449, 450, 469, 480, 500, 519,
  520, 540, 600, 700, 760, 780, 800, 804, 840, 869, 870, 880, 900, 1000, 1023,
  1089, 1099, 1100, 1200, 1440,
];
const KEEP_SHOTS = new Set([320, 390, 480, 780, 1200]);

function seed(mode) {
  const $ = (s) => document.querySelector(s);
  $('#usageChip').classList.remove('hidden');
  $('#usageChip').classList.add('ok');
  $('#usageChipPct').textContent = '19%';
  $('#usageChipText').textContent = 'session';
  $('#usageChipWeek').classList.remove('hidden');
  $('#usageChipWeekPct').textContent = '100%';
  ['#refreshAll', '#settingsBtn'].forEach((s) => $(s).classList.remove('hidden'));
  // Both tab badges carrying a count: the busiest the tabs ever get.
  ['#memBadge', '#findBadge'].forEach((s) => {
    $(s).textContent = '3';
    $(s).classList.remove('hidden');
  });
  if (mode === 'broken') {
    $('#authChip').classList.remove('hidden');
    $('#authChip').classList.add('bad');
    $('#authChipText').textContent = 'Claude auth failed';
  } else if (mode === 'paused') {
    // A healthy login shows no chip at all — what fills the space instead is
    // the paused chip, in its longest wording.
    $('#pausedChip').classList.remove('hidden');
    $('#pausedChipText').textContent = 'Usage budget reached';
  }
  // 'running' is neither: healthy, generating, usage only. It is not a subset
  // of the other two — at the floor they drop the usage chip and it doesn't.
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
    for (const mode of ['running', 'paused', 'broken']) {
      await page.setViewportSize({ width, height: 760 });
      await page.setContent(html, { waitUntil: 'load' });
      await page.addStyleTag({ path: path.join(PANEL, 'style.css') });
      await page.evaluate(seed, mode);

      const m = await page.evaluate(probe);
      const overflow = m.barScrollW > m.barClientW || m.escaped || m.docScrollW > width;
      rows.push({ width, mode, ...m, oneRow: m.lines === 1, h48: m.height === 48, overflow });

      if (OUT && mode === 'running' && KEEP_SHOTS.has(width)) {
        await page.locator('.topbar').screenshot({ path: path.join(OUT, `bar-${width}.png`) });
      }
    }
  }

  console.log('width  state    height  lines  scrollW/clientW  slack  verdict');
  let bad = 0;
  for (const r of rows) {
    const ok = r.oneRow && r.h48 && !r.overflow;
    if (!ok) bad++;
    console.log(
      String(r.width).padStart(5),
      r.mode.padEnd(8),
      String(r.height).padStart(6),
      String(r.lines).padStart(6),
      `     ${String(r.barScrollW).padStart(4)}/${String(r.barClientW).padStart(4)}`,
      String(r.slack).padStart(7),
      '  ' + (ok ? 'OK' : 'FAIL'
        + (r.oneRow ? '' : ' wrapped')
        + (r.h48 ? '' : ` height=${r.height}`)
        + (r.overflow ? ` overflow by ${r.barScrollW - r.barClientW}px` : '')),
    );
  }
  console.log(bad ? `\n${bad} case(s) failed` : '\nall widths: one row, 48px, no overflow');
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
