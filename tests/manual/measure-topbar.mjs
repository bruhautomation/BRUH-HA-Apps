// Render the brAIn topbar across viewport widths and assert, per width, that
// it lays out as intended and that everything in it is big enough to hit.
//
// Two shapes, not five. At >=1240px the bar is a single 56px row with every
// tab named. Below that it is the two-row bar: status and actions on top,
// the tabs on a full-width strip of their own underneath, still named. So
// the check is no longer "always one row" — it is "the shape this width is
// supposed to have, with nothing spilling out of it and no target under
// 44px". Either way all five tabs carry their names: no width gets a row of
// bare glyphs.
//
// Every child of the bar is `flex: none` except the spacer, so items cannot
// silently compress to fake a fit: the bar either holds its content or it
// wraps. Above the phone breakpoint wrapping is the failure; below it,
// wrapping is the layout, and overflow is the failure.
//
// The panel's JS needs a live backend, so we skip it and set the header by
// hand. Three states are checked at every width. None is a superset of the
// others, because the trouble states put a second chip beside the usage pill
// and that is what decides whether the phone bar runs to a third row:
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

// The width at which the tabs leave the row for a strip of their own, and
// the smallest a touch target is allowed to be. Both are also in style.css;
// if they move, they move in both places.
//
// There is one width here, not two. The bar used to have a middle band —
// one row with the tab labels deleted — which is the shape a laptop with
// the HA sidebar open actually rendered, so the compromise was what most
// people saw. Labels now leave only when the whole row does.
const PHONE_MAX = 1239;
// Tabs and icon buttons are 44px, the smallest a target has any business
// being on a touchscreen. Chips are pills of text and sit at 40 — still a
// real target, just not a square one.
const MIN_TOUCH = 44;
const MIN_CHIP = 40;

const WIDTHS = [
  320, 340, 360, 375, 379, 380, 390, 400, 414, 428, 480, 500, 540, 600, 640, 700, 720,
  768, 800, 900, 959, 960, 1000, 1024, 1100, 1199, 1200, 1239, 1240, 1280, 1440, 1920,
];
const KEEP_SHOTS = new Set([320, 390, 480, 800, 1100, 1280]);

function seed(mode) {
  const $ = (s) => document.querySelector(s);
  $('#usageChip').classList.remove('hidden');
  $('#usageChip').classList.add('ok');
  $('#usageChipPct').textContent = '19%';
  $('#usageChipWeek').classList.remove('hidden');
  $('#usageChipWeekPct').textContent = '100%';
  // The bar's only button now. "Refresh all" used to sit beside it: an
  // unlabelled circular arrow that queued a Claude run for every card, next
  // to the pill reporting the usage those runs spend.
  $('#settingsBtn').classList.remove('hidden');
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
    // the paused chip. There is only one wording left: "usage budget
    // reached" used to have a chip of its own, next to a usage pill already
    // reporting the number it was about, and saying it twice is what pushed
    // the bar onto a second row.
    $('#pausedChip').classList.remove('hidden');
    $('#pausedChipText').textContent = 'Auto insights off';
  }
  // 'running' is neither: healthy, generating, usage only.
}

function probe(floors) {
  const bar = document.querySelector('.topbar');
  const br = bar.getBoundingClientRect();
  const kids = [...bar.children]
    .filter((el) => getComputedStyle(el).display !== 'none')
    .map((el) => el.getBoundingClientRect())
    .filter((r) => r.width > 0);

  // A row break means two items sit on separate lines. Differing tops alone
  // just means items of different heights are centred against each other.
  let rows = 1;
  const sorted = [...kids].sort((a, b) => a.top - b.top);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].top >= sorted[i - 1].bottom - 0.5) rows++;
  }

  // Everything you can press, measured as rendered.
  const targets = [...bar.querySelectorAll('.viewtab, .btn.icon, .chip.clickable')]
    .filter((el) => getComputedStyle(el).display !== 'none')
    .map((el) => {
      const r = el.getBoundingClientRect();
      return {
        w: Math.round(r.width),
        h: Math.round(r.height),
        id: el.id || el.dataset.view || 'target',
        min: el.classList.contains('chip') ? floors.chip : floors.touch,
      };
    })
    .filter((t) => t.w > 0);

  // Tab labels are the point of the phone strip — check they actually render
  // rather than merely being un-hidden.
  const labelled = [...bar.querySelectorAll('.viewtab span:not(.badge)')]
    .filter((el) => getComputedStyle(el).display !== 'none').length;

  return {
    height: Math.round(br.height),
    rows,
    escaped: kids.some((r) => r.bottom > br.bottom + 0.5 || r.top < br.top - 0.5),
    barScrollW: bar.scrollWidth,
    barClientW: bar.clientWidth,
    docScrollW: document.documentElement.scrollWidth,
    labelled,
    // "Smallest" means furthest below its own floor, not fewest pixels — a
    // 40px chip is fine and a 40px tab is not.
    undersized: targets.filter((t) => Math.min(t.w, t.h) < t.min)
      .map((t) => `${t.id} ${t.w}x${t.h}<${t.min}`),
    smallest: targets.reduce(
      (a, t) => (Math.min(t.w, t.h) < Math.min(a.w, a.h) ? t : a), targets[0]),
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

      const m = await page.evaluate(probe, { touch: MIN_TOUCH, chip: MIN_CHIP });
      const phone = width <= PHONE_MAX;
      const overflow = m.barScrollW > m.barClientW || m.escaped || m.docScrollW > width;
      // Above the breakpoint: one 56px row, labels on only where they fit.
      // Below it: the tabs on a row of their own with their names showing,
      // and a third row only when a trouble chip joins the usage pill.
      const shape = phone
        ? m.rows >= 2 && m.rows <= (mode === 'running' ? 2 : 3) && m.labelled === 5
        : m.rows === 1 && m.height === 56 && m.labelled === 5;
      const touch = !!m.smallest && m.undersized.length === 0;
      rows.push({ width, mode, ...m, phone, shape, touch, overflow });

      if (OUT && mode === 'running' && KEEP_SHOTS.has(width)) {
        await page.locator('.topbar').screenshot({ path: path.join(OUT, `bar-${width}.png`) });
      }
    }
  }

  console.log('width  state     height  rows  scrollW/clientW  smallest target    verdict');
  let bad = 0;
  for (const r of rows) {
    const ok = r.shape && r.touch && !r.overflow;
    if (!ok) bad++;
    const t = r.smallest ? `${r.smallest.id} ${r.smallest.w}x${r.smallest.h}` : '—';
    console.log(
      `${String(r.width).padStart(5)}  ${r.mode.padEnd(8)} ${String(r.height).padStart(6)} `
      + `${String(r.rows).padStart(5)}  ${String(r.barScrollW).padStart(6)}/`
      + `${String(r.barClientW).padEnd(6)}   ${t.padEnd(18)} `
      + (ok ? 'ok' : [!r.shape && `SHAPE rows=${r.rows} h=${r.height} labels=${r.labelled}`,
                      !r.touch && `TOUCH ${r.undersized.join(', ') || 'no targets'}`,
                      r.overflow && `OVERFLOW +${r.barScrollW - r.barClientW}px`]
        .filter(Boolean).join(' ')));
  }
  console.log(bad
    ? `\n${bad}/${rows.length} case(s) failed`
    : `\nall ${rows.length} cases: right shape, no overflow, `
      + `every tab and button >=${MIN_TOUCH}px and every chip >=${MIN_CHIP}px`);

  await browser.close();
  process.exit(bad ? 1 : 0);
})();
