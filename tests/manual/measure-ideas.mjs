// Render House › Reports' Suggested row and assert an idea can be judged
// from the card it is on, and that the row says nothing it does not need to.
//
// Ideas used to be a tab of their own with an intro paragraph, a two-
// sentence empty state and a "Last looked…" foot. The redesign (House ›
// Reports) folded them into one row under the reports: its name and Run,
// and the ideas when there are any. An idea is still a proposal to spend
// money on a recurring report, so what somebody needs before saving one is
// the evidence from THIS house and the question it would answer every run.
//
// So the checks are about what a card SAYS, and what the row no longer says:
//
//   * every idea carries both blocks — why this house, and what it would
//     answer — each under a heading of its own.
//   * every idea carries Save (primary) and Ignore, in the doc's words.
//   * the cut prose stays cut: no intro, no "hasn't looked yet" or "nothing
//     new to suggest" sentence, no "Last looked" foot. An empty row is its
//     name and Run.
//   * the one silence that IS a fault — the last look failed — is still
//     said, because a failed run and a well-covered house look alike
//     otherwise.
//   * a pass in flight says so on the page and not only by greying Run.
//   * Ignore opens a box to say why, at 16px on touch, and what is typed is
//     what the dismissal carries.
//   * nothing scrolls sideways, and the ids the handlers bind to are there.
//
// It drives the panel's REAL `renderIdeas` behind a stubbed fetch —
// measure-activity's rule, because a copy of the renderer in this file
// would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView, controlOverlaps } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];

// Every element id `app.js` binds a handler to on this view.
const IDS = ['viewInsights', 'ideasRow', 'ideasRun', 'ideasList', 'ideasNote'];

// Prose the redesign cut from the row. None of it may come back.
const CUT = [/Nothing here is generating/i, /hasn't looked for ideas yet/i,
             /Nothing new to suggest/i, /Last looked/i, /looks again once a week/i,
             /Suggest ideas/i, /Ideas for new cards/i];

const NOW = Math.floor(Date.now() / 1000);
const IDEAS = [
  { id: 1, title: 'Heat pump against everything else',
    icon: '⚡',
    focus: 'Compare sensor.heat_pump_energy against the rest of the grid '
      + 'draw, month over month.',
    why: 'The heat pump is 58% of your winter usage and nothing on the '
      + 'dashboard separates it from the rest.',
    question: 'What share of this month went to heating, and is that '
      + 'moving?',
    status: 'open', added_at: NOW - 3600, run_id: 'sess-a',
    category_id: '', ended_at: 0 },
  { id: 2, title: 'Garage freezer, on its own',
    icon: '🌡',
    focus: 'Track sensor.garage_freezer against its own measured baseline.',
    why: 'It has drifted six degrees over a month while the kitchen one '
      + 'has not moved.',
    question: 'Is the garage freezer still holding its temperature?',
    status: 'open', added_at: NOW - 7200, run_id: 'sess-a',
    category_id: '', ended_at: 0 },
];

const payload = (over) => ({
  ideas: IDEAS, open: IDEAS.length, running: false, last_run: NOW - 86400,
  last_error: '', last_count: IDEAS.length, runs: 3, answered: 4,
  writable: true, due: false, ...over,
});

const stub = (body) => `
window.__ideas = ${JSON.stringify(body)};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.__calls = [];
window.fetch = async (url, opts) => {
  const p = String(url);
  window.__calls.push({ url: p, method: (opts || {}).method || 'GET',
                        body: (opts || {}).body || '' });
  const answer = (b) => new Response(JSON.stringify(b), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/ideas')) return answer(window.__ideas);
  // The shape the panel actually READS, not a plausible-looking one — a
  // stub that omits a key throws a page error seconds later, which this
  // file fails on and which has nothing to do with the tab under test.
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: window.__cats || [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const read = (page, ids) => page.evaluate((wanted) => {
  const cards = [...document.querySelectorAll('#ideasList .finding')];
  const note_ = document.getElementById('ideasNote');
  const btn = document.getElementById('ideasRun');
  return {
    cards: cards.map((c) => ({
      title: (c.querySelector('.findtitle') || {}).textContent || '',
      // The meta row's own spacing. The first cut of this renderer used a
      // class the stylesheet has no rule for, so the pill and the date
      // laid out touching — "⚡ ideasuggested 1 h ago" — which reads as
      // one broken word and which the rest of this file passed straight
      // over. Measured as the gap between the two, on the same line.
      metaGap: (() => {
        const row = c.querySelector('.findmeta, .findline');
        if (!row) return -1;
        const kids = [...row.children];
        if (kids.length < 2) return 999;
        const a = kids[0].getBoundingClientRect();
        const b = kids[1].getBoundingClientRect();
        if (Math.round(b.top) !== Math.round(a.top)) return 999;
        return Math.round(b.left - a.right);
      })(),
      heads: [...c.querySelectorAll('.findfixlabel')]
        .map((h) => h.textContent.trim()),
      blocks: [...c.querySelectorAll('.findfix')].map((b) => ({
        head: (b.querySelector('.findfixlabel') || {}).textContent || '',
        body: (b.querySelector('span:not(.findfixlabel)') || {})
          .textContent || '',
      })),
      verbs: [...c.querySelectorAll('.findactions button')].map((b) => ({
        label: b.textContent.trim(),
        primary: b.classList.contains('primary'),
        h: Math.round(b.getBoundingClientRect().height),
      })),
      right: Math.round(c.getBoundingClientRect().right),
    })),
    empty: (document.querySelector('#ideasList .findempty') || {})
      .textContent || '',
    note: note_ && !note_.hidden ? note_.textContent.trim() : '',
    button: btn ? btn.textContent.trim() : '',
    disabled: btn ? btn.disabled : false,
    row: (document.getElementById('ideasRow') || {}).textContent || '',
    rowShown: (() => {
      const r = document.getElementById('ideasRow');
      return !!(r && r.getBoundingClientRect().height > 0);
    })(),
    missing: wanted.filter((i) => !document.getElementById(i)),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
}, ids);

const open = async (width, touch, body) => {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(body));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'insights');
  return { context, page };
};

for (const { width, touch } of CASES) {
  const { context, page } = await open(width, touch, payload());
  await page.waitForSelector('#ideasList .finding');
  const view = await read(page, IDS);

  if (view.missing.length) {
    note(`${width}px`, `element id(s) gone: ${view.missing.join(', ')}`);
  }
  if (view.cards.length !== IDEAS.length) {
    note(`${width}px`, `${view.cards.length} cards for ${IDEAS.length} ideas`);
  }
  if (!view.rowShown) note(`${width}px`, 'the Suggested row is not on Reports');

  for (const card of view.cards) {
    if (!card.title.trim()) note(`${width}px`, 'an idea renders no title');
    if (card.metaGap < 4) {
      note(`${width}px`,
           `"${card.title}" runs its meta row together (${card.metaGap}px gap)`);
    }
    // The two blocks the page rests on. A title says the subject; only
    // these say whether the card is worth a run every refresh interval.
    const heads = card.heads.join(' | ').toLowerCase();
    if (!/why this house/.test(heads)) {
      note(`${width}px`, `"${card.title}" does not say why this house (${heads})`);
    }
    if (!/what it would answer/.test(heads)) {
      note(`${width}px`,
           `"${card.title}" does not say what it would answer (${heads})`);
    }
    for (const b of card.blocks) {
      if (!b.body.trim()) {
        note(`${width}px`,
             `"${card.title}" heads "${b.head.trim()}" with nothing under it`);
      }
    }
    const labels = card.verbs.map((v) => v.label).join(' | ');
    if (labels !== 'Save | Ignore') {
      note(`${width}px`, `"${card.title}" offers ${labels}, not Save | Ignore`);
    }
    // Saving it is the press the row exists for, so it leads.
    const primary = card.verbs.filter((v) => v.primary).map((v) => v.label);
    if (primary.length !== 1 || primary[0] !== 'Save') {
      note(`${width}px`,
           `"${card.title}" makes ${primary.join(' | ') || 'nothing'} primary`);
    }
    if (card.right > view.viewport + 1) {
      note(`${width}px`, `"${card.title}" hangs off the side`);
    }
  }
  for (const cut of CUT) {
    if (cut.test(view.row)) note(`${width}px`, `cut prose is back: ${cut}`);
  }
  if (view.button !== 'Run') note(`${width}px`, `the row's button reads "${view.button}"`);
  if (view.docWidth > view.viewport + 1) {
    note(`${width}px`, `page scrolls sideways (${view.docWidth} > ${view.viewport})`);
  }
  console.log(`${String(width).padStart(5)}  ${view.cards.length} ideas  `
    + `button "${view.button}"`);
  await context.close();
}

// The silences. Nobody having asked and a well-covered house are both an
// empty row with its name and Run — the prose that told them apart was cut —
// while the one that is a fault, a look that failed, is still said.
const SILENCES = [
  ['never asked', { ideas: [], open: 0, runs: 0, last_run: 0, last_count: 0 }, null],
  ['a failed look', { ideas: [], open: 0, runs: 2,
                      last_error: 'the reply did not parse' },
   /didn't finish/i],
  ['nothing to add', { ideas: [], open: 0, runs: 2, last_count: 0 }, null],
];
for (const [name, over, want] of SILENCES) {
  const { context, page } = await open(1200, false, payload(over));
  await page.waitForSelector('#ideasRun');
  if (want) {
    await page.waitForFunction(
      (src) => new RegExp(src, 'i').test(
        document.querySelector('#ideasList .findempty')?.textContent || ''),
      want.source, { timeout: 5000 }).catch(() => {});
  } else {
    await page.waitForTimeout(300);
  }
  const view = await read(page, IDS);
  if (want && !want.test(view.empty)) {
    note(name, `the row says "${view.empty.trim()}", not ${want}`);
  }
  if (!want && view.empty.trim()) {
    note(name, `an empty row carries a sentence: "${view.empty.trim()}"`);
  }
  if (!view.rowShown || view.button !== 'Run') {
    note(name, 'the empty row lost its name and Run');
  }
  for (const cut of CUT) {
    if (cut.test(view.row)) note(name, `cut prose is back: ${cut}`);
  }
  console.log(`  ${name.padEnd(16)} "${view.empty.trim().slice(0, 56)}"`);
  await context.close();
}

// A pass in flight. The sentence is on the page, not only in the button.
{
  const { context, page } = await open(1200, false,
    payload({ running: true, ideas: [], open: 0 }));
  await page.waitForSelector('#ideasRun');
  const view = await read(page, IDS);
  if (!view.disabled) note('running', 'the button is still pressable');
  if (!/running/i.test(view.button)) {
    note('running', `the button reads "${view.button}" while a pass is going`);
  }
  if (!view.note.trim()) {
    note('running', 'nothing on the page says a pass is running');
  }
  if (view.empty.trim()) {
    note('running', `an empty-state sentence shows mid-pass: "${view.empty}"`);
  }
  console.log(`  ${'running'.padEnd(16)} "${view.note.slice(0, 56)}…"`);
  await context.close();
}

// The reason a no. Ignore opens a box in place of the
// buttons, the box is a 16px control on touch (or iOS zooms the ingress
// frame in and never back out), it is optional, and what is typed is what
// the route receives — the half that rules out a FAMILY of cards rather
// than one title.
for (const { width, touch } of CASES) {
  const { context, page } = await open(width, touch, payload());
  await page.waitForSelector('#ideasList .finding');
  const card = page.locator('#ideasList .finding').first();
  await card.locator('.findactions button', { hasText: 'Ignore' }).click();
  const area = card.locator('.ideanote textarea');
  if (!(await area.count())) {
    note(`${width}px`, 'refusing an idea opens no box to say why');
    await context.close();
    continue;
  }
  const size = await area.evaluate((n) => parseFloat(getComputedStyle(n).fontSize));
  if (touch && size < 16) {
    note(`${width}px`, `the reason box is ${size}px on touch (iOS zooms under 16)`);
  }
  if (await card.locator('.findactions').isVisible()) {
    note(`${width}px`, 'the buttons stay on screen beside the reason box');
  }
  await area.fill('we do not care about standby power');
  await card.locator('.ideanote button', { hasText: 'Ignore' }).click();
  await page.waitForFunction(() => window.__calls.some(
    (c) => c.method === 'POST' && /dismiss/.test(c.url)), null,
    { timeout: 5000 }).catch(() => {});
  const posted = await page.evaluate(() => window.__calls.find(
    (c) => c.method === 'POST' && /dismiss/.test(c.url)));
  if (!posted) {
    note(`${width}px`, 'the reason box sent nothing');
  } else if (!/standby power/.test(posted.body)) {
    note(`${width}px`, `the dismissal carried "${posted.body}", not the reason`);
  }
  console.log(`  ${String(width).padStart(4)}px reason box ${size}px, `
    + `sent ${posted ? posted.body : 'nothing'}`);
  await context.close();
}

// The Schedule list under the reports: every recurring card with its
// cadence, last run, next run and a switch — one compact row each, the switch
// a 44px target on touch, and a press on it writes `enabled` through the
// route the card's own Enable uses.
for (const { width, touch } of CASES) {
  const { context, page } = await open(width, touch, payload());
  await page.evaluate(() => {
    window.__cats = [
      // A long name, the shape a real house's cards come with: the name has
      // to wrap inside its own column, never run under the cells beside it.
      { id: 'energy', title: 'Two Dehumidifiers: What the Damp Cost Over the Whole Winter',
        icon: '💧', enabled: true, refresh_hours: 24,
        generated_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
        next_due: Date.now() / 1000 + 5 * 3600, job: {} },
      { id: 'climate', title: 'Climate', icon: '🌡', enabled: true, schedule: ['07:00', '19:00'],
        generated_at: null, refresh_hold: { why: 'nothing it reads has changed', at: 1 }, job: {} },
      { id: 'security', title: 'Security', icon: '🔒', enabled: false, refresh_hours: 12,
        generated_at: new Date(Date.now() - 86400e3).toISOString(), job: {} },
    ];
    window.__fetchLog = [];
    return refreshStatus().then(() => render());
  });
  await page.waitForSelector('#schedList .scheditem', { state: 'attached' });
  // Closed, nothing it holds may sit over the presses below it: the house's
  // own photographs found a card's name lying over a Run button.
  for (const o of await controlOverlaps(page, '#viewInsights')) {
    note(`${width}px schedule closed`, `controls overlap: ${o}`);
  }
  await page.click('#schedRow summary');
  const sched = await page.evaluate(() => ({
    rows: [...document.querySelectorAll('#schedList .scheditem')].map((r) => ({
      text: r.textContent.replace(/\s+/g, ' ').trim(),
      togH: Math.round(r.querySelector('.schedtog').getBoundingClientRect().height),
      togW: Math.round(r.querySelector('.schedtog').getBoundingClientRect().width),
      on: r.querySelector('input').checked,
      right: r.getBoundingClientRect().right,
      // Every child's box against every other's, and the name's text
      // against its own box: an overlap is ink drawn over a control.
      overlaps: (() => {
        const kids = [...r.children].map((k) => [k.className, k.getBoundingClientRect()]);
        const hits = [];
        for (let a = 0; a < kids.length; a++) {
          for (let b = a + 1; b < kids.length; b++) {
            const [na, ra] = kids[a]; const [nb, rb] = kids[b];
            const x = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
            const y = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
            if (x > 1 && y > 1) hits.push(`${na} over ${nb}`);
          }
        }
        const nm = r.querySelector('.schedname');
        if (nm.scrollWidth > nm.clientWidth + 1) hits.push('the name runs out of its own box');
        return hits;
      })() })),
    count: document.getElementById('schedCount').textContent,
    docWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
  }));
  const at = `${width}px schedule`;
  if (sched.rows.length !== 3) note(at, `${sched.rows.length} rows for 3 cards`);
  const want = [/every 24 h/, /at 07:00, 19:00/, /every 12 h/];
  sched.rows.forEach((r, i) => {
    if (want[i] && !want[i].test(r.text)) note(at, `row ${i} does not say its cadence: "${r.text}"`);
    if (touch && (r.togH < 44 || r.togW < 44)) note(at, `row ${i} switch is ${r.togW}x${r.togH}`);
    if (r.right > sched.viewport + 0.5) note(at, `row ${i} overflows the viewport`);
    for (const o of r.overlaps) note(at, `row ${i}: ${o}`);
  });
  if (!/3 h ago/.test(sched.rows[0].text)) note(at, 'the last run is not dated');
  if (!/in 5 h/.test(sched.rows[0].text)) note(at, `the next run is not dated: "${sched.rows[0].text}"`);
  if (!/waiting — nothing it reads has changed/.test(sched.rows[1].text)) note(at, 'a held card does not say why it waits');
  if (!/not yet/.test(sched.rows[1].text)) note(at, 'a card that never ran does not say so');
  if (sched.rows[2].on || !/off/.test(sched.rows[2].text)) note(at, 'a disabled card is not shown off');
  if (sched.count !== '2 of 3 on') note(at, `the count reads "${sched.count}"`);
  if (sched.docWidth > sched.viewport + 0.5) note(at, 'the page scrolls sideways');
  for (const o of await controlOverlaps(page, '#viewInsights')) note(at, `controls overlap: ${o}`);
  await page.click('#schedList .scheditem:nth-child(3) .schedtog');
  await page.waitForFunction(() => window.__calls.some(
    (c) => c.method === 'PUT' && /api\/prompt\/security/.test(c.url)), null, { timeout: 5000 })
    .catch(() => note(at, 'the switch wrote nothing'));
  const put = await page.evaluate(() => window.__calls.find(
    (c) => c.method === 'PUT' && /api\/prompt\/security/.test(c.url)));
  if (put && !/"enabled":true/.test(put.body)) note(at, `the switch sent ${put.body}`);
  console.log(`  ${String(width).padStart(4)}px schedule ${sched.rows.length} rows, ${sched.count}`);
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-ideas: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nevery idea can be judged from its card, and the Suggested row '
  + 'says only what it needs to');
