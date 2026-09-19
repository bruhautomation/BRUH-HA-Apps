// Render the Home feed against one case of every kind and assert that each
// one can be answered from the screen it is on.
//
// The failure this exists to prevent is the one the whole feed is written
// against: four inboxes became one list, so a case whose ending is missing
// is not a tidy-up — it is work that has nowhere to go and a badge that can
// never read as done. So the checks are about what a card OFFERS.
//
//   * every case carries its endings, and a `change` carries exactly one,
//     because offering a decision about something brAIn already did is a
//     decision about nothing.
//   * every case says what KIND it is, in a word. Five stores sit under
//     this list and a person does five different things about them; the
//     left edge is severity, so the pill is the only thing that says which.
//   * every ending clears the touch floor at phone widths. This is the row
//     somebody presses every day, and a 32px target under a thumb is the
//     one failure reading cannot see.
//   * the ⋯ opens. The rare verbs are still real and they are behind it, so
//     a menu that does not open is thirteen verbs reduced to three.
//   * the foot line carries all three of the Resident's counts, because a
//     quiet feed and a loop that has stopped look identical without it.
//   * nothing scrolls sideways, and every element id the tab's handlers
//     bind to is still there — an id going missing is the one thing a move
//     like this loses quietly.
//
// It drives the panel's REAL `renderFindings`/`makeCase` behind a stubbed
// fetch — measure-activity's rule, because a copy of the renderer in this
// file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 1200, touch: false },
];
// A thumb. Scoped in the stylesheet to this tab's own controls, the way
// `.propask`'s and the to-do add box's are — the Findings tab's older card
// rows are deliberately not raised, and a floor asserted on both here would
// be this file holding a rule the panel does not.
const MIN_TARGET = 44;

// Every element id `app.js` binds a handler to on this view. An id that
// goes missing is a control that silently stops working, which is what the
// settings measure learned to check for the same reason.
const IDS = ['viewFindings', 'findFilters', 'findRunChecks', 'findScore',
             'findMuted', 'findList', 'findFoot', 'findBadge'];

const NOW = Math.floor(Date.now() / 1000);
const kase = (over) => ({
  id: '', kind: 'problem', claim: '', detail: '', confidence: null,
  stakes: 'medium', evidence: [], actions: [], status: 'open', source: '',
  source_title: '', ts: NOW, origin: { store: 'findings', key: NOW },
  memory_hint: '', investigation: null, ended: null, severity: 'warning',
  entity_id: '', fix: '', snoozed_until: 0, overflow: [], ...over,
});

const FEED = [
  kase({
    id: 'f:1001', kind: 'problem', severity: 'serious', stakes: 'high',
    confidence: 0.86,
    claim: 'The garage freezer has been six degrees warmer for a week',
    detail: 'Its own month of statistics drifts upward and no other freezer '
      + 'in the house does.',
    entity_id: 'sensor.garage_freezer',
    fix: 'Check the door seal, then the compressor relay.',
    fix_by: 'resident',
    source: 'resident', source_title: 'The Resident',
    origin: { store: 'findings', key: 1001 },
    investigation: { run_id: 'sess-a' },
    evidence: [
      { entity: 'sensor.garage_freezer', value: '-12.4 °C', when: '15 Sep 08:10' },
      { entity: 'sensor.kitchen_freezer', value: '-18.1 °C', when: '15 Sep 08:10' },
    ],
    actions: [
      { label: 'Tell me when it passes -10', shape: 'notify', consent: false,
        detail: 'A push, once.' },
    ],
    overflow: [
      { verb: 'done', label: 'I had already done it',
        route: '/api/finding/1001/done', method: 'POST' },
      { verb: 'discuss', label: 'Talk about it',
        route: '/api/finding/1001/discuss', method: 'POST' },
      { verb: 'mute', label: 'Stop raising these',
        route: '/api/findings/mute', method: 'POST' },
    ],
  }),
  kase({
    id: 'p:1002', kind: 'opportunity', severity: 'info', stakes: 'low',
    claim: 'Turn the porch light off at 23:10 on weekdays',
    detail: 'You have done it by hand on nine of the last twelve weekdays.',
    source: 'routines', source_title: 'routine',
    origin: { store: 'proposals', key: 1002 },
    overflow: [{ verb: 'trial', label: 'Try it for a week',
                 route: '/api/proposal/1002/trial', method: 'POST' }],
  }),
  kase({
    id: 'h:1003', kind: 'question', severity: 'info', stakes: 'low',
    claim: 'The garage fridge is meant to run 24/7',
    source: 'hypothesis', source_title: 'energy',
    origin: { store: 'hypotheses', key: 1003 },
  }),
  kase({
    id: 't:1004', kind: 'chore', severity: 'warning', stakes: 'medium',
    claim: 'Replace the hallway smoke alarm battery',
    fix: 'CR2032, behind the cover.',
    source: 'check:dev.battery', source_title: 'Battery forecast',
    origin: { store: 'todo', key: 1004 },
  }),
  kase({
    id: 'f:1005', kind: 'change', severity: 'warning', stakes: 'medium',
    claim: 'brAIn pointed the hall automation at the new sensor',
    detail: 'binary_sensor.hall_old had been renamed.',
    source: 'check:auto.dead_ref', source_title: 'Automation checks',
    origin: { store: 'findings', key: 1005 },
    overflow: [{ verb: 'unfix', label: 'Put it back',
                 route: '/api/finding/1005/unfix', method: 'POST' }],
  }),
];

const LEDGER = { day: '2026-09-19', looked: 96, investigated: 3, acted: 0,
                 tokens: { haiku: 240000, sonnet: 61000 } };

const STUB = `
window.__cases = {
  cases: ${JSON.stringify(FEED)},
  open: ${FEED.length},
  ledger: ${JSON.stringify(LEDGER)},
  resident: { running: false, queue_len: 4, waiting: 0, hot_pending: 0,
              last_error: "" },
  eventbus: { connected: true, events_seen: 8123, signals_emitted: 41,
              idle_reason: "" },
  watching: 6,
};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/cases')) return answer(window.__cases);
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [],
                    scorecard: [], muted: [] });
  }
  // The shape the panel actually READS, not a plausible-looking one — a
  // stub that omits a key throws a page error seconds later, which this
  // file fails on and which has nothing to do with the tab under test.
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 5,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/todo')) {
    return answer({ items: [], done: [], open: 0, done_count: 0 });
  }
  if (p.includes('api/proposals')) {
    return answer({ proposals: [], open: 0, rooms: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const read = (page) => page.evaluate((ids) => {
  const cards = [...document.querySelectorAll('#findList .finding')];
  return {
    cards: cards.map((c) => {
      const box = c.getBoundingClientRect();
      return {
        id: c.dataset.caseId || '',
        kind: (c.className.match(/\bk-([a-z]+)\b/) || [])[1] || '',
        pill: c.querySelector('.casekind')?.textContent || '',
        cert: c.querySelector('.casecert')?.textContent || '',
        title: c.querySelector('.findtitle')?.textContent || '',
        evidence: [...c.querySelectorAll('.caseevlist li')].map((li) => li.textContent),
        actionRows: [...c.querySelectorAll('.caseactlist li')].map((li) => li.textContent),
        words: c.textContent,
        verbs: [...c.querySelectorAll('.findactions button')].map((b) => ({
          label: b.textContent.trim(),
          h: Math.round(b.getBoundingClientRect().height),
          w: Math.round(b.getBoundingClientRect().width),
          icon: b.classList.contains('icon'),
        })),
        right: Math.round(box.right),
      };
    }),
    foot: document.getElementById('findFoot')?.textContent || '',
    footShown: !document.getElementById('findFoot')?.hidden,
    badge: document.getElementById('findBadge')?.textContent || '',
    tabLabel: document.querySelector('.viewtab[data-view="findings"] span')
      ?.textContent || '',
    missing: ids.filter((i) => !document.getElementById(i)),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
}, IDS);

for (const { width, touch } of CASES) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="findings"]');
  await page.waitForSelector('#findList .finding');

  const feed = await read(page);

  if (feed.missing.length) {
    note(`${width}px`, `element id(s) gone: ${feed.missing.join(', ')}`);
  }
  if (!/^Home$/i.test(feed.tabLabel.trim())) {
    note(`${width}px`, `the tab is called "${feed.tabLabel.trim()}", not Home`);
  }
  if (feed.cards.length !== FEED.length) {
    note(`${width}px`, `${feed.cards.length} cards for ${FEED.length} cases`);
  }

  const kinds = new Set();
  for (const card of feed.cards) {
    kinds.add(card.kind);
    if (!card.title.trim()) note(`${width}px`, `${card.id} renders no claim`);
    // A pill, in words. The left edge is severity, so without it nothing on
    // the card says which of five stores it came out of.
    if (!card.pill.trim()) {
      note(`${width}px`, `${card.id} (${card.kind}) has no kind pill`);
    }
    const labels = card.verbs.map((v) => v.label);
    if (!card.verbs.length) {
      note(`${width}px`, `${card.id} offers no way to answer it`);
    }
    if (card.kind === 'change') {
      // One ending. A change is news to read, and the only honest answer to
      // news brAIn made itself is that you have read it.
      const endings = card.verbs.filter((v) => !v.icon);
      if (endings.length !== 1 || !/Got it/i.test(endings[0].label)) {
        note(`${width}px`,
             `a change offers ${endings.length} ending(s): ${labels.join(' | ')}`);
      }
    } else {
      for (const want of [/Do it/i, /Not now/i, /Wrong/i]) {
        if (!labels.some((l) => want.test(l))) {
          note(`${width}px`,
               `${card.id} is missing ${want} (${labels.join(' | ')})`);
        }
      }
    }
    // A number is a false precision on a card; the words are the claim.
    if (/\b0\.\d+\b/.test(card.cert)) {
      note(`${width}px`, `${card.id} renders a confidence as a number: "${card.cert}"`);
    }
    if (touch) {
      for (const v of card.verbs) {
        if (v.h < MIN_TARGET) {
          note(`${width}px`,
               `"${v.label}" on ${card.id} is ${v.h}px tall on touch`);
        }
        if (v.icon && v.w < MIN_TARGET) {
          note(`${width}px`, `the ⋯ on ${card.id} is ${v.w}px wide on touch`);
        }
      }
    }
    if (card.right > feed.viewport + 1) {
      note(`${width}px`, `${card.id} hangs off the side`);
    }
  }
  for (const want of ['problem', 'opportunity', 'question', 'chore', 'change']) {
    if (!kinds.has(want)) note(`${width}px`, `no ${want} case rendered`);
  }
  // The evidence and the actions are the two halves that make a claim
  // checkable and a press predictable.
  const investigated = feed.cards.find((c) => c.id === 'f:1001');
  if (investigated) {
    if (investigated.evidence.length !== 2) {
      note(`${width}px`,
           `the investigated case shows ${investigated.evidence.length} evidence row(s)`);
    }
    if (!investigated.actionRows.length) {
      note(`${width}px`, 'the investigated case does not say what Do it would do');
    } else if (!/consent|asks you/i.test(investigated.actionRows.join(' '))) {
      note(`${width}px`, 'an action row does not say what consent it needs');
    }
  }

  // The foot line. Three counts, because a quiet feed and a loop that has
  // stopped look identical without them.
  if (!feed.footShown || !feed.foot.trim()) {
    note(`${width}px`, 'the Resident line is not on the page');
  } else {
    for (const [what, re] of [['looked', /looked\s+96\s+time/i],
                              ['investigated', /investigated\s+3/i],
                              ['changed', /changed nothing/i]]) {
      if (!re.test(feed.foot)) {
        note(`${width}px`, `the foot line does not say ${what}: "${feed.foot}"`);
      }
    }
    if (!/watch/i.test(feed.foot)) {
      note(`${width}px`, 'the foot line does not say what is being watched');
    }
  }
  if (feed.docWidth > feed.viewport + 1) {
    note(`${width}px`, `page scrolls sideways (${feed.docWidth} > ${feed.viewport})`);
  }

  // The ⋯ opens. The rare verbs are still real; a menu that does not open
  // is thirteen verbs reduced to three rather than moved behind one.
  let menu = null;
  try {
    await page.click('#findList .finding[data-case-id="f:1001"] .findactions .btn.icon');
    menu = await page.evaluate(() =>
      [...document.querySelectorAll('#chipPop .cardmenuitem')]
        .map((b) => b.textContent.trim()));
  } catch (e) {
    // Notes rather than throws: measure-cardlive's first run abandoned
    // nineteen findings it had already gathered to report one helper.
    note(`${width}px`, `the ⋯ menu did not open: ${e.message}`);
  }
  if (menu && menu.length < 3) {
    note(`${width}px`, `the ⋯ menu holds ${menu.length} row(s)`);
  }

  console.log(`${String(width).padStart(5)}  ${feed.cards.length} cases  `
    + `kinds ${[...kinds].join('/')}  badge ${feed.badge}  `
    + `menu ${menu ? menu.length : 0} rows`);
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-home: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nevery case can be answered from the card it is on, every kind '
  + 'says what it is, and the Resident line says what it did today');
