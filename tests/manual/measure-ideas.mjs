// Render the Ideas tab and assert an idea can be judged from the card it is
// on, and that an empty page says WHICH kind of empty it is.
//
// The failure this exists to prevent is the one that makes the page
// pointless rather than broken. An idea is a proposal to spend money on a
// recurring card, so what somebody needs before ticking one is not the
// title — it is the evidence from THIS house and the question the card
// would answer every run. A page of titles is a page of guesses, and it
// looks exactly like a page of good ideas.
//
// So the checks are about what a card SAYS:
//
//   * every idea carries both blocks — why this house, and what it would
//     answer — each under a heading of its own. They are the two the whole
//     page rests on; the title alone says the subject and nothing else.
//   * every idea carries both presses, and the accepting one is primary.
//     An idea you cannot take is a card that cannot be made.
//   * an empty page says which of THREE silences it is: nobody has asked
//     yet, the last look failed, or brAIn looked and had nothing to add.
//     Only the second is a fault, and rendering them alike is what teaches
//     somebody to press the button again. This is `house.py`'s rule about
//     a measurement that has not started, one tab over.
//   * a pass in flight says so ON THE PAGE and not only by grey-ing the
//     button, because a run is minutes long and a disabled button is what
//     a failed one looks like too.
//   * nothing scrolls sideways, and the ids the handlers bind to are all
//     still there.
//
// It drives the panel's REAL `renderIdeas` behind a stubbed fetch —
// measure-activity's rule, because a copy of the renderer in this file
// would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];

// Every element id `app.js` binds a handler to on this view.
const IDS = ['viewIdeas', 'ideasRun', 'ideasList', 'ideasNote', 'ideasFoot',
             'ideasBadge'];

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
window.fetch = async (url) => {
  const p = String(url);
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
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
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
    foot: (document.getElementById('ideasFoot') || {}).textContent || '',
    badge: (document.getElementById('ideasBadge') || {}).textContent || '',
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
  await openView(page, 'ideas');
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
  if (view.badge !== String(IDEAS.length)) {
    note(`${width}px`, `badge reads "${view.badge}", not ${IDEAS.length}`);
  }

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
    if (!/Add this card/i.test(labels)) {
      note(`${width}px`, `"${card.title}" offers no way to take it (${labels})`);
    }
    if (!/Not for this house/i.test(labels)) {
      note(`${width}px`, `"${card.title}" offers no way to refuse it (${labels})`);
    }
    // Taking it is the press the page exists for, so it leads.
    const primary = card.verbs.filter((v) => v.primary).map((v) => v.label);
    if (primary.length !== 1 || !/Add this card/i.test(primary[0] || '')) {
      note(`${width}px`,
           `"${card.title}" makes ${primary.join(' | ') || 'nothing'} primary`);
    }
    if (card.right > view.viewport + 1) {
      note(`${width}px`, `"${card.title}" hangs off the side`);
    }
  }
  if (!/looked/i.test(view.foot)) {
    note(`${width}px`, `the foot does not say when it last looked: "${view.foot}"`);
  }
  if (!/week/i.test(view.foot)) {
    note(`${width}px`, 'the foot does not say it looks again on its own');
  }
  if (view.docWidth > view.viewport + 1) {
    note(`${width}px`, `page scrolls sideways (${view.docWidth} > ${view.viewport})`);
  }
  console.log(`${String(width).padStart(5)}  ${view.cards.length} ideas  `
    + `badge ${view.badge}  button "${view.button}"`);
  await context.close();
}

// The three silences. A page with nothing on it is the ordinary state of
// this tab for most of a week, so what it says in that state IS the tab
// most of the time.
const SILENCES = [
  ['never asked', { ideas: [], open: 0, runs: 0, last_run: 0, last_count: 0 },
   /hasn't looked for ideas yet/i],
  ['a failed look', { ideas: [], open: 0, runs: 2,
                      last_error: 'the reply did not parse' },
   /didn't finish/i],
  ['nothing to add', { ideas: [], open: 0, runs: 2, last_count: 0 },
   /nothing new to suggest/i],
];
const said = new Map();
for (const [name, over, want] of SILENCES) {
  const { context, page } = await open(1200, false, payload(over));
  await page.waitForSelector('#ideasList .findempty');
  const view = await read(page, IDS);
  if (!want.test(view.empty)) {
    note(name, `the empty page says "${view.empty.trim()}", not ${want}`);
  }
  said.set(name, view.empty.trim());
  console.log(`  ${name.padEnd(16)} "${view.empty.trim().slice(0, 56)}…"`);
  await context.close();
}
// Three silences, three sentences. All three legitimately end by offering
// the button, so what is asserted is that they are not the SAME sentence —
// if any two are, the page has stopped telling those two states apart,
// which is the whole reason this block exists.
for (const [a] of SILENCES) {
  for (const [b] of SILENCES) {
    if (a < b && said.get(a) && said.get(a) === said.get(b)) {
      note('the empty page', `"${a}" and "${b}" say the same thing`);
    }
  }
}

// A pass in flight. The sentence is on the page, not only in the button.
{
  const { context, page } = await open(1200, false,
    payload({ running: true, ideas: [], open: 0 }));
  await page.waitForSelector('#ideasRun');
  const view = await read(page, IDS);
  if (!view.disabled) note('running', 'the button is still pressable');
  if (!/looking/i.test(view.button)) {
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

await browser.close();

if (failures.length) {
  console.error(`measure-ideas: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nevery idea can be judged from its card, and an empty page '
  + 'says which silence it is');
