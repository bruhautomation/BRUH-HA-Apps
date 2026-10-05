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
//     * the sub-tab strip never scrolls sideways, every pane is on screen,
//       Home's five fit on one row, and each is a 44px target;
//     * no status strip sits over the reports (House > Reports cut it);
//     * Help opens on the guide: the contents are a shut fold whose summary
//       names the section, the page starts above the fold, and the fold
//       opens to the links.
//   wide (1448):
//     * the Findings feed lays its cards two abreast and uses the width;
//     * Proposals sits in the same column under the same heading as
//       Findings, and its room picker is a styled select.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;
const NOW = Math.floor(Date.now() / 1000);

const kase = (n) => ({
  id: `f:${n}`, kind: 'problem', claim: `Problem number ${n} in the house`,
  detail: 'Something worth a look.', confidence: 0.8, stakes: 'medium',
  evidence: [], actions: [], status: 'open', source: 'check:dev.unavailable',
  source_title: 'Device check', ts: NOW - n, origin: { store: 'findings', key: n },
  memory_hint: '', investigation: null, ended: null, severity: 'warning',
  entity_id: '', entity_name: '', area: '', fix: 'Check it.', fix_by: '',
  fixable: false, finding_status: 'open', plan: {}, triage: {},
  snoozed_until: 0, overflow: [], answers: [], more: [], situation: 'generic',
});

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/cases')) {
    return answer({ cases: ${JSON.stringify([1, 2, 3, 4].map(kase))}, names: {},
                    open: 4, ledger: {}, resident: {}, eventbus: {}, watching: 0 });
  }
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [],
                    scorecard: [], muted: [] });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: { onboarded: true }, usage: {},
      auto: { enabled: true }, categories: [], jobs: {}, queue_size: 0,
      findings_open: 4,
      today: {
        checks: { last_at: ${NOW} - 600, ran: 45, created: 2, cleared: 1,
                  next_at: ${NOW} + 20000 },
        baselines: { built_at: ${NOW} - 30000 },
        memory: { last_filed_at: ${NOW} - 4000, waiting: 3 },
        claude_runs_24h: 73,
      },
    });
  }
  if (p.includes('api/onboarding')) return answer({ state: 'done', onboarded: true });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/todo')) return answer({ items: [], done: [], open: 0, done_count: 0 });
  if (p.includes('api/scenes/areas')) {
    return answer({ areas: [{ area: 'Lounge', lights: 4 }], min_lights: 2 });
  }
  if (p.includes('api/proposals')) return answer({ proposals: [], open: 0, rooms: [] });
  return answer({});
};
`;

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
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  return { context, page };
}

const subtab = (page, view) => page.click(`.subtab[data-view="${view}"]`);

// ---------------------------------------------------------------- phone
{
  const where = '390px';
  const { context, page } = await open(390, 791, true);
  await page.click('.viewtab[data-group="home"]');
  await page.waitForSelector('#findList .finding');
  // Every badge lit, one of them two digits: the widest the strip gets on
  // an ordinary house, and the case the walkthrough's phone was in.
  await page.evaluate(() => {
    updateIdeasBadge(3);
    updateTodoBadge(12);
    const b = document.querySelector('#propBadge');
    b.textContent = '4';
    b.classList.remove('hidden');
  });

  const strip = await page.evaluate(() => {
    const nav = document.querySelector('#subtabs');
    const tabs = [...nav.querySelectorAll('.subtab')]
      .filter((b) => getComputedStyle(b).display !== 'none');
    return {
      scroll: nav.scrollWidth, client: nav.clientWidth,
      overflowX: getComputedStyle(nav).overflowX,
      tabs: tabs.map((b) => {
        const r = b.getBoundingClientRect();
        return { label: b.textContent.trim(), top: Math.round(r.top),
                 right: r.right, h: Math.round(r.height) };
      }),
      vw: window.innerWidth,
    };
  });
  if (strip.tabs.length !== 5) note(where, `${strip.tabs.length} Home panes shown, not 5`);
  if (strip.scroll > strip.client + 1 || /auto|scroll/.test(strip.overflowX)) {
    note(where, `the sub-tab strip scrolls sideways (${strip.scroll} > ${strip.client}, `
                + `overflow-x ${strip.overflowX})`);
  }
  for (const t of strip.tabs) {
    if (t.right > strip.vw + 0.5) note(where, `"${t.label}" is cut off at the edge`);
    if (t.h < MIN_TARGET) note(where, `"${t.label}" is ${t.h}px tall`);
  }
  if (new Set(strip.tabs.map((t) => t.top)).size > 1) {
    note(where, `Home's panes take ${new Set(strip.tabs.map((t) => t.top)).size} rows, not 1`);
  }

  // The status strip used to sit over the Insights cards. House > Reports
  // cut it (the redesign: a report is its headline and its age), so what
  // is measured now is that it stays cut — a strip of checks and runs over
  // the reports is the chrome this file exists to keep off a phone.
  await subtab(page, 'insights');
  await page.waitForSelector('#viewInsights.active');
  const strip2 = await page.evaluate(() => {
    const s = document.querySelector('#viewInsights #todayStrip');
    return s ? Math.round(s.getBoundingClientRect().height) : null;
  });
  if (strip2) note(where, `a ${strip2}px status strip is back over the reports`);

  // Help: the guide first, the contents behind a fold.
  await page.click('.viewtab[data-group="help"]');
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
  await page.click('.viewtab[data-group="home"]');
  await page.waitForSelector('#findList .finding');
  const feed = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('#findList .finding')]
      .map((c) => c.getBoundingClientRect());
    const wrap = document.querySelector('.wrap').getBoundingClientRect();
    const list = document.querySelector('#findList').getBoundingClientRect();
    const h2 = document.querySelector('#viewFindings .findhead h2');
    return {
      cards: cards.map((r) => ({ top: Math.round(r.top), left: Math.round(r.left) })),
      share: list.width / wrap.width,
      left: Math.round(list.left),
      h2: getComputedStyle(h2).fontSize,
    };
  });
  if (feed.cards.length >= 2) {
    const [a, b] = feed.cards;
    if (a.top !== b.top || a.left === b.left) {
      note(where, 'the first two findings are not side by side');
    }
  }
  if (feed.share < 0.9) {
    note(where, `the Findings feed uses ${Math.round(feed.share * 100)}% of the width`);
  }

  await subtab(page, 'proposals');
  await page.waitForSelector('#viewProposals.active, #viewProposals[class*="active"]');
  await page.waitForFunction(() => document.querySelector('#sceneArea').options.length > 1,
    null, { timeout: 4000 }).catch(() => {});
  const prop = await page.evaluate(() => {
    const head = document.querySelector('#viewProposals .prophead h2');
    const wrap = document.querySelector('#viewProposals .propwrap').getBoundingClientRect();
    const sel = getComputedStyle(document.querySelector('#sceneArea'));
    return {
      left: Math.round(wrap.left), h2: getComputedStyle(head).fontSize,
      styled: document.querySelector('#sceneArea').classList.contains('sel'),
      appearance: sel.appearance,
    };
  });
  if (Math.abs(prop.left - feed.left) > 1) {
    note(where, `Proposals starts at ${prop.left}px and Findings at ${feed.left}px`);
  }
  if (prop.h2 !== feed.h2) note(where, `Proposals' heading is ${prop.h2}, Findings' ${feed.h2}`);
  if (!prop.styled || prop.appearance !== 'none') {
    note(where, `the room picker is the browser's own select (appearance ${prop.appearance})`);
  }
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
