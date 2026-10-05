// What the panel spends on chrome before content, at a phone and at a wide
// desktop — measured on the real markup, stylesheet and renderers behind a
// stubbed fetch.
//
// It exists for a read-only walkthrough on a real house that found, at a
// 393px phone, the Home sub-tab strip scrolling sideways with Proposals cut
// off at the edge, the status strip above the cards wrapped to five lines
// each opening with a stray separator bar, and the Help tab putting sixty
// links before a word of the guide; and, at 1448px, the Findings feed in a
// column holding about 55% of the width with the right half empty, beside a
// Proposals tab with a narrower centred column, a heading of its own and
// the browser's unstyled select.
//
//   phone (390, touch):
//     * there are three tabs on one row, each a 44px target, and no
//       sub-tab strip on Today or on House — the strip that scrolled
//       sideways is gone, not shortened;
//     * no status strip sits over the reports (House > Reports cut it);
//     * the guide (⚙ > Guide) opens on the guide: the contents are a shut
//       fold whose summary names the section, the page starts above the
//       fold, and the fold opens to the links.
//   wide (1448):
//     * Today's queue and Your list share one column that uses the width,
//       and there is no Proposals pane beside it with a heading and a
//       column of its own — a suggestion is a card in that queue.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stub } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

async function open(width, height, touch) {
  const context = await browser.newContext({
    viewport: { width, height }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub());
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  return { context, page };
}

// ---------------------------------------------------------------- phone
{
  const where = '390px';
  const { context, page } = await open(390, 791, true);
  await page.waitForSelector('#findList .qcard');

  const bar = await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.viewtab')]
      .filter((b) => getComputedStyle(b).display !== 'none');
    return {
      tabs: tabs.map((b) => {
        const r = b.getBoundingClientRect();
        return { label: b.textContent.trim(), top: Math.round(r.top),
                 right: r.right, h: Math.round(r.height) };
      }),
      strip: !document.querySelector('#subtabs').hidden,
      vw: window.innerWidth,
    };
  });
  if (bar.tabs.length !== 3) note(where, `${bar.tabs.length} tabs, not 3`);
  if (bar.strip) note(where, 'Today shows a sub-tab strip');
  for (const t of bar.tabs) {
    if (t.right > bar.vw + 0.5) note(where, `"${t.label}" is cut off at the edge`);
    if (t.h < MIN_TARGET) note(where, `"${t.label}" is ${t.h}px tall`);
  }
  if (new Set(bar.tabs.map((t) => t.top)).size > 1) {
    note(where, `the tabs take ${new Set(bar.tabs.map((t) => t.top)).size} rows, not 1`);
  }

  // The status strip used to sit over the Insights cards. House > Reports
  // cut it (the redesign: a report is its headline and its age), so what
  // is measured now is that it stays cut — a strip of checks and runs over
  // the reports is the chrome this file exists to keep off a phone.
  await page.click('.viewtab[data-group="house"]');
  await page.waitForSelector('#viewInsights.active');
  if (await page.evaluate(() => !document.querySelector('#subtabs').hidden)) {
    note(where, 'House shows a sub-tab strip under its own control');
  }
  const strip2 = await page.evaluate(() => {
    const s = document.querySelector('#viewInsights #todayStrip');
    return s ? Math.round(s.getBoundingClientRect().height) : null;
  });
  if (strip2) note(where, `a ${strip2}px status strip is back over the reports`);

  // The guide (⚙ › Guide, no tab of its own): the guide first, the
  // contents behind a fold.
  await page.evaluate(() => switchView('docs'));
  await page.waitForSelector('#docsBody h1, #docsBody h2');
  const docs = await page.evaluate(() => {
    const fold = document.querySelector('#docsNavFold');
    const bodyTop = Math.round(document.querySelector('#docsBody')
      .getBoundingClientRect().top);
    if (!fold) return { missing: true, bodyTop, vh: window.innerHeight };
    const sum = fold.querySelector('summary').getBoundingClientRect();
    return {
      open: fold.open,
      sumH: Math.round(sum.height),
      current: document.querySelector('#docsNavCurrent').textContent.trim(),
      bodyTop,
      vh: window.innerHeight,
    };
  });
  if (docs.missing) {
    note(where, `Help has no contents fold; the guide starts at ${docs.bodyTop}px`);
    await context.close();
  } else {
  if (docs.open) note(where, 'Help opens with its contents expanded above the guide');
  if (docs.sumH < MIN_TARGET) note(where, `the contents fold is ${docs.sumH}px tall`);
  if (!docs.current) note(where, 'the contents fold does not name the section shown');
  if (docs.bodyTop > docs.vh * 0.6) {
    note(where, `the guide starts at ${docs.bodyTop}px of a ${docs.vh}px screen`);
  }
  await page.click('#docsNavFold > summary');
  const links = await page.evaluate(() =>
    [...document.querySelectorAll('#docsNav .docslink')]
      .filter((b) => b.getBoundingClientRect().height > 0).length);
  if (links < 10) note(where, `opening the contents shows ${links} links`);
  await page.click('#docsNav .docslink:nth-child(3)');
  const after = await page.evaluate(() => document.querySelector('#docsNavFold').open);
  if (after) note(where, 'picking a section leaves the contents open over the page');

  const docW = await page.evaluate(() => document.documentElement.scrollWidth);
  if (docW > 390) note(where, `the page scrolls sideways (${docW}px)`);
  await context.close();
  }
}

// ----------------------------------------------------------------- wide
{
  const where = '1448px';
  const { context, page } = await open(1448, 900, false);
  await page.waitForSelector('#findList .qcard');
  const today = await page.evaluate(() => {
    const wrap = document.querySelector('.wrap').getBoundingClientRect();
    const list = document.querySelector('#findList').getBoundingClientRect();
    const mine = document.querySelector('#todoList').getBoundingClientRect();
    return {
      share: list.width / wrap.width,
      left: Math.round(list.left), mineLeft: Math.round(mine.left),
      cards: document.querySelectorAll('#findList .qcard').length,
      proposals: !!document.getElementById('viewProposals'),
      todo: !!document.getElementById('viewTodo'),
    };
  });
  if (today.share < 0.9) note(where, `Today's queue uses ${Math.round(today.share * 100)}% of the width`);
  if (today.left !== today.mineLeft) {
    note(where, `the queue starts at ${today.left}px and Your list at ${today.mineLeft}px`);
  }
  if (today.cards !== 3) note(where, `${today.cards} cards before "Show more", not 3`);
  if (today.proposals) note(where, 'a Proposals pane is back beside Today');
  if (today.todo) note(where, 'a To-do pane is back beside Today');
  await context.close();
}

// ------------------------------------------------- the header usage pill
// The session and week numbers live in ⚙ → Usage & schedule. The header
// carries them only when they are news: past 80% in either window, or with
// automatic insights paused by the budget (the redesign's PR 9). Driven
// through the real `renderUsageChip` over the real `state.status`.
{
  const where = 'usage pill';
  const { context, page } = await open(1448, 900, false);
  const shown = (u) => page.evaluate((usage) => {
    state.status = { ...(state.status || {}), authenticated: true, usage };
    renderUsageChip();
    return !document.querySelector('#usageChip').classList.contains('hidden');
  }, u);
  if (await shown({ source: 'account', used_percent: 18, week_percent: 9 })) {
    note(where, 'the pill shows at 18% with nothing paused');
  }
  if (await shown({ source: 'account', used_percent: 80, week_percent: 40 })) {
    note(where, 'the pill shows at exactly 80%');
  }
  if (!await shown({ source: 'account', used_percent: 85, week_percent: 40 })) {
    note(where, 'the pill stays hidden at 85% of the session');
  }
  if (!await shown({ source: 'account', used_percent: 20, week_percent: 91 })) {
    note(where, 'the pill stays hidden at 91% of the week');
  }
  if (!await shown({ source: 'account', used_percent: 30, week_percent: 10, blocked: true,
                     budget_percent: 25 })) {
    note(where, 'the pill stays hidden while automatic insights are paused');
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.log('measure-chrome: FAIL');
  failures.forEach((f) => console.log('  ' + f));
  process.exit(1);
}
console.log('measure-chrome: OK at 390 and 1448px');
