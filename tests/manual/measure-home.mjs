// Render the Findings feed against one case of every kind and assert that
// each one can be answered from the screen it is on — with ONE row of
// answers, the same on every problem, and never more than four of them.
//
// The failures this exists to prevent are the ones the redesign was written
// against, in the words they arrived in: "Yes/no questions have a 'do it'
// button. There are lots of buttons. I don't always see a dismiss." — and
// then, one release later, "I don't see a dismiss button. If I just want to
// ignore something and you may bring it up later, how do I do that? This
// all feels really complicated." So the checks are about what a card
// OFFERS and how much it asks you to read first.
//
//   * every answerable case carries at most four visible presses, one of
//     them is always a way to say no (`data-verb` wrong / no / decline /
//     drop / cancel), and every card a person answers carries Dismiss
//     (`not_now`) — never behind the ⋯, never wrapped out of sight.
//   * every problem takes the same row in the same order: Fix it where
//     brAIn could act, Add to list, Dismiss, Not a problem.
//   * a question offers Yes and No and never "Do it"; a battery leads with
//     the to-do list and never a plan run; a plan waiting for consent offers
//     Apply and Cancel; a change offers Got it alone.
//   * the face of the card names things by their friendly NAME: the entity
//     chip and the claim carry "Garage Freezer", and the id is a tooltip.
//   * the evidence, the actions and the reasoning are behind one
//     disclosure, closed by default, and it opens to show them.
//   * every ending clears the touch floor at phone widths, the ⋯ opens, the
//     foot line carries the Resident's three counts, nothing scrolls
//     sideways, and every element id the tab's handlers bind to is there.
//
// It drives the panel's REAL `renderFindings`/`makeCase` behind a stubbed
// fetch — measure-activity's rule, because a copy of the renderer in this
// file would only ever agree with itself. The fixture carries the server's
// own shape (`answers`, `more`, `names`, `finding_status`), so a field the
// renderer stops reading fails here rather than on a phone.
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
  entity_id: '', entity_name: '', area: '', fix: '', fix_by: '',
  fixable: false, finding_status: 'open', plan: {}, triage: {},
  snoozed_until: 0, overflow: [], answers: [], more: [], situation: '',
  ...over,
});
// What `answers.py` hands a card: verb, label, route, and whether the press
// opens the reason box. Spelled per case the way the server spells it, so
// the renderer is driven with the real shape rather than a plausible one.
const A = (verb, label, route, over = {}) => ({
  verb, label, route, method: 'POST', request: null, primary: false,
  note: false, prefill: '', done: label, hint: `${label} — hint`, ...over,
});

const FEED = [
  kase({
    id: 'f:1001', kind: 'problem', severity: 'serious', stakes: 'high',
    confidence: 0.86, situation: 'hands',
    claim: 'sensor.garage_freezer has been six degrees warmer for a week',
    detail: 'Its own month of statistics drifts upward and no other freezer '
      + 'in the house does. The kitchen freezer, on the same circuit, has '
      + 'held its temperature to within half a degree over the same month, '
      + 'so this is not the supply and not the room: it is this one '
      + 'appliance, and the drift began on the ninth.',
    entity_id: 'sensor.garage_freezer', entity_name: 'Garage Freezer',
    area: 'Garage',
    fix: 'Check the door seal on sensor.garage_freezer, then the compressor relay.',
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
    answers: [
      A('todo', 'Add to list', '/api/case/f:1001/do', { primary: true, request: 'todo' }),
      A('not_now', 'Dismiss', '/api/case/f:1001/not_now', { request: 'snooze' }),
      A('wrong', 'Not a problem', '/api/case/f:1001/wrong', { note: true, request: 'wrong' }),
    ],
    more: [
      { verb: 'done', label: "I've already fixed it",
        route: '/api/finding/1001/done', method: 'POST' },
      { verb: 'discuss', label: 'Talk about it',
        route: '/api/finding/1001/discuss', method: 'POST' },
      { verb: 'mute', label: 'Stop raising these',
        route: '/api/findings/mute', method: 'POST' },
    ],
  }),
  kase({
    id: 'f:1006', kind: 'problem', severity: 'warning', stakes: 'medium',
    situation: 'automation',
    claim: 'The porch automation is switched off',
    detail: 'It has been off since 3 Sep and nothing has turned it on.',
    entity_id: 'automation.porch_light', entity_name: 'Porch Light',
    fix: 'Turn it back on, or delete it if it is not coming back.',
    fixable: true,
    source: 'check:auto.forgotten_off', source_title: 'Automation check',
    origin: { store: 'findings', key: 1006 },
    answers: [
      A('fix', 'Fix it', '/api/finding/1006/fix', { primary: true }),
      A('todo', 'Add to list', '/api/case/f:1006/do', { request: 'todo' }),
      A('not_now', 'Dismiss', '/api/case/f:1006/not_now', { request: 'snooze' }),
      A('wrong', 'Not a problem', '/api/case/f:1006/wrong', { note: true, request: 'wrong' }),
    ],
    more: [
      { verb: 'discuss', label: 'Talk about it',
        route: '/api/finding/1006/discuss', method: 'POST' },
      { verb: 'recheck', label: 'Check again',
        route: '/api/finding/1006/recheck', method: 'POST' },
    ],
  }),
  kase({
    id: 'f:1007', kind: 'problem', severity: 'serious', stakes: 'high',
    situation: 'battery',
    claim: 'Mudroom battery is low',
    detail: '0% as of 22 Sep in the Kitchen.',
    entity_id: 'sensor.mudroom_battery', entity_name: 'Mudroom Battery',
    area: 'Kitchen',
    fix: 'Replace the battery.',
    source: 'check:dev.battery_low', source_title: 'Device check',
    origin: { store: 'findings', key: 1007 },
    answers: [
      A('todo', 'Add to list', '/api/case/f:1007/do', { primary: true, request: 'todo' }),
      A('not_now', 'Dismiss', '/api/case/f:1007/not_now', { request: 'snooze' }),
      A('wrong', 'Not a problem', '/api/case/f:1007/wrong', { note: true, request: 'wrong' }),
    ],
    more: [{ verb: 'done', label: "I've already fixed it",
             route: '/api/finding/1007/done', method: 'POST' }],
  }),
  kase({
    id: 'f:1008', kind: 'problem', severity: 'warning', stakes: 'medium',
    situation: 'planned', finding_status: 'planned', fixable: true,
    claim: 'The hall automation points at a sensor that no longer exists',
    entity_id: 'automation.hall', entity_name: 'Hall',
    fix: 'Point it at the new sensor.',
    plan: { can_fix: true, needs_you: false, summary: 'Edit automations.yaml.',
            steps: ['Replace binary_sensor.hall_old with binary_sensor.hall.'],
            risk: 'None worth naming.' },
    source: 'check:auto.dead_ref', source_title: 'Automation check',
    origin: { store: 'findings', key: 1008 },
    answers: [
      A('apply', 'Apply', '/api/finding/1008/apply', { primary: true }),
      A('cancel', "Don't change it", '/api/finding/1008/cancel'),
      A('wrong', 'Not a problem', '/api/case/f:1008/wrong', { note: true }),
    ],
  }),
  kase({
    id: 'p:1002', kind: 'opportunity', severity: 'info', stakes: 'low',
    situation: 'opportunity',
    claim: 'Turn the porch light off at 23:10 on weekdays',
    detail: 'You have done it by hand on nine of the last twelve weekdays.',
    source: 'routines', source_title: 'routine',
    origin: { store: 'proposals', key: 1002 },
    answers: [
      A('accept', 'Make the change', '/api/case/p:1002/do', { primary: true }),
      A('trial', 'Try it for a week', '/api/proposal/1002/trial'),
      A('not_now', 'Dismiss', '/api/case/p:1002/not_now', { request: 'snooze' }),
      A('decline', 'No thanks', '/api/case/p:1002/wrong', { note: true }),
    ],
    more: [],
  }),
  kase({
    id: 'h:1003', kind: 'question', severity: 'info', stakes: 'low',
    situation: 'question',
    claim: 'The garage fridge is meant to run 24/7',
    source: 'hypothesis', source_title: 'energy',
    origin: { store: 'hypotheses', key: 1003 },
    answers: [
      A('yes', 'Yes', '/api/case/h:1003/do', { primary: true }),
      A('no', 'No', '/api/case/h:1003/wrong', { note: true }),
      A('not_now', 'Dismiss', '/api/case/h:1003/not_now', { request: 'snooze' }),
    ],
    more: [],
  }),
  kase({
    id: 'f:1005', kind: 'change', severity: 'warning', stakes: 'medium',
    situation: 'change', finding_status: 'fixed',
    claim: 'brAIn pointed the hall automation at the new sensor',
    detail: 'binary_sensor.hall_old had been renamed.',
    source: 'check:auto.dead_ref', source_title: 'Automation check',
    origin: { store: 'findings', key: 1005 },
    fix_started: NOW - 60, fix_ended: NOW - 30, fix_files: 1, fix_calls: 0,
    answers: [
      A('ack', 'Got it', '/api/case/f:1005/do', { primary: true, request: 'ack' }),
      A('unfix', 'Undo the fix', '/api/finding/1005/unfix'),
    ],
  }),
];

// The name map the server sends beside the feed, off the last checks pass.
const NAMES = {
  'sensor.garage_freezer': { name: 'Garage Freezer', area: 'Garage' },
  'sensor.kitchen_freezer': { name: 'Kitchen Freezer', area: 'Kitchen' },
  'sensor.mudroom_battery': { name: 'Mudroom Battery', area: 'Kitchen' },
  'automation.porch_light': { name: 'Porch Light', area: '' },
  'automation.hall': { name: 'Hall', area: '' },
};

const LEDGER = { day: '2026-09-19', looked: 96, investigated: 3, acted: 0,
                 tokens: { haiku: 240000, sonnet: 61000 } };

const STUB = `
window.__cases = {
  cases: ${JSON.stringify(FEED)},
  names: ${JSON.stringify(NAMES)},
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
        situation: c.dataset.situation || '',
        pill: c.querySelector('.casekind')?.textContent || '',
        cert: c.querySelector('.casecert')?.textContent || '',
        title: c.querySelector('.findtitle')?.textContent || '',
        evidence: [...c.querySelectorAll('.caseevlist li')].map((li) => li.textContent),
        // The fix block, as two separate reads: the heading says WHOSE
        // fix it is and the sentence is the fix. They were one line and
        // one string before, which is how the heading came to be a
        // sentence prefix nobody could tell from the sentence.
        fixHead: c.querySelector('.findfix .findfixlabel')?.textContent || '',
        fixText: c.querySelector('.findfix span:not(.findfixlabel)')
          ?.textContent || '',
        fixStacked: (() => {
          const box = c.querySelector('.findfix');
          if (!box) return true;
          const h = box.querySelector('.findfixlabel');
          const t = box.querySelector('span:not(.findfixlabel)');
          if (!h || !t) return true;
          return Math.round(t.getBoundingClientRect().top)
            >= Math.round(h.getBoundingClientRect().bottom);
        })(),
        actionRows: [...c.querySelectorAll('.caseactlist li')].map((li) => li.textContent),
        words: c.textContent,
        entityChip: c.querySelector('.findentity')?.textContent || '',
        entityTip: c.querySelector('.findentity')?.title || '',
        detail: c.querySelector('.finddetail')?.textContent || '',
        hasMore: !!c.querySelector('.detailmore'),
        details: (() => {
          const d = c.querySelector('details.casemore');
          if (!d) return null;
          const r = d.querySelector('summary').getBoundingClientRect();
          return { open: d.open, h: Math.round(r.height),
                   summary: d.querySelector('summary').textContent.trim() };
        })(),
        planShown: !!c.querySelector('.findplan'),
        verbs: [...c.querySelectorAll('.findactions button')].map((b) => ({
          label: b.textContent.trim(),
          verb: b.dataset.verb || '',
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
  // `SHOT_DIR=/some/dir` saves what was measured, for a person to look at.
  if (process.env.SHOT_DIR) {
    await page.screenshot({ path: path.join(process.env.SHOT_DIR, `home-${width}.png`),
                            fullPage: true });
  }

  if (feed.missing.length) {
    note(`${width}px`, `element id(s) gone: ${feed.missing.join(', ')}`);
  }
  if (!/^Home$/i.test(feed.tabLabel.trim())) {
    note(`${width}px`, `the tab is called "${feed.tabLabel.trim()}", not Home`);
  }
  if (feed.cards.length !== FEED.length) {
    note(`${width}px`, `${feed.cards.length} cards for ${FEED.length} cases`);
  }

  const NO = new Set(['wrong', 'no', 'decline', 'drop', 'cancel']);
  const kinds = new Set();
  for (const card of feed.cards) {
    kinds.add(card.kind);
    if (!card.title.trim()) note(`${width}px`, `${card.id} renders no claim`);
    // A pill, in words. The left edge is severity, so without it nothing on
    // the card says which of five stores it came out of.
    if (!card.pill.trim()) {
      note(`${width}px`, `${card.id} (${card.kind}) has no kind pill`);
    }
    const endings = card.verbs.filter((v) => !v.icon);
    const labels = endings.map((v) => v.label);
    if (!endings.length) {
      note(`${width}px`, `${card.id} offers no way to answer it`);
    }
    // At most four: the fixed row. Five would be the one that wraps a
    // press somebody wanted out of sight.
    if (endings.length > 4) {
      note(`${width}px`, `${card.id} offers ${endings.length} buttons: ${labels.join(' | ')}`);
    }
    // Dismiss is on every card a person answers — the press that was
    // missing — and it is called Dismiss, in the same place each time.
    const answerable = !['change', 'planned', 'watching'].includes(
      card.situation || card.kind);
    if (answerable && card.kind !== 'change') {
      const dismiss = endings.find((v) => v.verb === 'not_now');
      if (!dismiss) {
        note(`${width}px`, `${card.id} has no Dismiss (${labels.join(' | ')})`);
      } else if (dismiss.label !== 'Dismiss') {
        note(`${width}px`, `${card.id}'s snooze is called "${dismiss.label}", not Dismiss`);
      }
    }
    // Every problem takes the same row in the same order, so a row can be
    // read without reading the words.
    if (card.kind === 'problem' && answerable) {
      const tail = endings.map((v) => v.verb).filter((v) => v !== 'fix');
      if (tail.join(',') !== 'todo,not_now,wrong') {
        note(`${width}px`, `${card.id} breaks the fixed row: ${labels.join(' | ')}`);
      }
      const words = endings.map((v) => v.label).filter((l) => l !== 'Fix it');
      if (words.join(',') !== 'Add to list,Dismiss,Not a problem') {
        note(`${width}px`, `${card.id} uses its own words: ${labels.join(' | ')}`);
      }
    }
    // ...and one of them is always a way to say no, except on a change
    // (news to read).
    if (card.kind !== 'change' && !endings.some((v) => NO.has(v.verb))) {
      note(`${width}px`, `${card.id} has no way to say no (${labels.join(' | ')})`);
    }
    // Never the old catch-all. "Do it" on a question, on a battery and on
    // a plan meant three different things, and none of them was said.
    if (labels.some((l) => /^✓?\s*Do it$/i.test(l))) {
      note(`${width}px`, `${card.id} still offers "Do it"`);
    }
    if (card.kind === 'change') {
      // Got it leads. The undo is offered beside it, never a decision.
      if (!/Got it/i.test(labels[0] || '')) {
        note(`${width}px`, `a change leads with "${labels[0]}", not Got it`);
      }
    }
    // A number is a false precision on a card; the words are the claim.
    if (/\b0\.\d+\b/.test(card.cert)) {
      note(`${width}px`, `${card.id} renders a confidence as a number: "${card.cert}"`);
    }
    // No entity id on the face where the server knew a name for it.
    if (/\b(sensor|automation|binary_sensor)\.[a-z_]+\b/.test(card.title)) {
      note(`${width}px`, `${card.id} names an entity id in its title: "${card.title}"`);
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
      if (card.details && card.details.h < MIN_TARGET) {
        note(`${width}px`, `the disclosure on ${card.id} is ${card.details.h}px tall on touch`);
      }
    }
    if (card.right > feed.viewport + 1) {
      note(`${width}px`, `${card.id} hangs off the side`);
    }
  }

  // The buttons that FIT. Each is the situation's own row, and the wrong
  // one is the complaint this feed was rewritten against.
  const expect = {
    'h:1003': ['yes', 'no', 'not_now'],
    'f:1007': ['todo', 'not_now', 'wrong'],
    'f:1008': ['apply', 'cancel', 'wrong'],
    'f:1006': ['fix', 'todo', 'not_now', 'wrong'],
    'p:1002': ['accept', 'trial', 'not_now', 'decline'],
  };
  for (const [id, verbs] of Object.entries(expect)) {
    const card = feed.cards.find((c) => c.id === id);
    if (!card) continue;
    const got = card.verbs.filter((v) => !v.icon).map((v) => v.verb);
    if (got.join(',') !== verbs.join(',')) {
      note(`${width}px`, `${id} offers ${got.join(',')}, wanted ${verbs.join(',')}`);
    }
  }
  const battery = feed.cards.find((c) => c.id === 'f:1007');
  if (battery && battery.verbs.some((v) => v.verb === 'fix')) {
    note(`${width}px`, 'a battery offers a plan run');
  }
  const planned = feed.cards.find((c) => c.id === 'f:1008');
  if (planned && !planned.planShown) {
    note(`${width}px`, 'a plan waiting for consent is not shown on its card');
  }

  // Pretty names. The chip carries the name and the room; the id is the
  // tooltip; the claim's id was replaced.
  const freezer = feed.cards.find((c) => c.id === 'f:1001');
  if (freezer) {
    if (!/Garage Freezer/.test(freezer.entityChip) || !/Garage/.test(freezer.entityChip)) {
      note(`${width}px`, `the entity chip reads "${freezer.entityChip}"`);
    }
    if (freezer.entityTip !== 'sensor.garage_freezer') {
      note(`${width}px`, `the entity id is not in the chip's tooltip ("${freezer.entityTip}")`);
    }
    if (!/Garage Freezer has been six degrees/.test(freezer.title)) {
      note(`${width}px`, `the claim still carries the id: "${freezer.title}"`);
    }
    if (!/Garage Freezer/.test(freezer.fixText)) {
      note(`${width}px`, `the fix still carries the id: "${freezer.fixText}"`);
    }
    // A long detail is clamped with a More, never truncated silently and
    // never shown whole on the face.
    if (!freezer.hasMore) {
      note(`${width}px`, 'a five-sentence detail is shown whole with no More');
    }
    if (!freezer.details) {
      note(`${width}px`, 'the investigated case has no disclosure');
    } else if (freezer.details.open) {
      note(`${width}px`, 'the disclosure is open by default');
    } else if (!freezer.evidence.length) {
      note(`${width}px`, 'the disclosure holds no evidence rows');
    }
  }

  // Never a chore: an accepted finding lives on the To-do tab, and one on
  // this feed is a finding with no way onto the list.
  if (kinds.has('chore')) note(`${width}px`, 'a chore case rendered on the feed');
  for (const want of ['problem', 'opportunity', 'question', 'change']) {
    if (!kinds.has(want)) note(`${width}px`, `no ${want} case rendered`);
  }

  // Whose fix it is. The feed headed every `fix` sentence "You'd need to",
  // one hardcoded string, so a row brAIn could act on told somebody to do
  // it by hand while the same card's ⋯ offered to work the change out.
  // Both headings have to be reachable or the one that is missing is the
  // one nobody sees is wrong.
  const heads = { 'f:1006': /how brain would fix it/i,
                  'f:1001': /how you'd fix it/i,
                  'f:1007': /how you'd fix it/i };
  for (const [id, want] of Object.entries(heads)) {
    const card = feed.cards.find((c) => c.id === id);
    if (!card) continue;
    if (!want.test(card.fixHead.replace(/\u2019/g, "'"))) {
      note(`${width}px`,
           `${id} heads its fix "${card.fixHead.trim()}", not ${want}`);
    }
    // A heading that sits on the sentence's own baseline reads as its
    // first words, which is what made "YOU'D NEED TO  Turn it back on"
    // two subjects. Styled as a heading, it has to sit like one.
    if (!card.fixStacked) {
      note(`${width}px`, `${id} puts its fix heading inline with the fix`);
    }
    // The sentence has to stand on its own, because every `fix` a check
    // writes is already a capitalised imperative.
    if (!card.fixText.trim()) {
      note(`${width}px`, `${id} renders a fix heading with no fix under it`);
    }
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
      note(`${width}px`, 'the investigated case does not say what could be done');
    } else if (!/ask you|can do this/i.test(investigated.actionRows.join(' '))) {
      note(`${width}px`, 'an action row does not say what consent it needs');
    }
  }

  // The disclosure opens, and the More opens the rest of the detail.
  try {
    await page.click('#findList .finding[data-case-id="f:1001"] details.casemore summary');
    await page.click('#findList .finding[data-case-id="f:1001"] .detailmore');
    const opened = await page.evaluate(() => {
      const c = document.querySelector('#findList .finding[data-case-id="f:1001"]');
      return {
        open: c.querySelector('details.casemore').open,
        rows: c.querySelectorAll('.caseevlist li').length,
        detail: c.querySelector('.finddetail').textContent,
        more: !!c.querySelector('.detailmore'),
      };
    });
    if (!opened.open || opened.rows !== 2) {
      note(`${width}px`, `the disclosure did not open onto the evidence (${opened.rows} rows)`);
    }
    if (opened.more || !/began on the ninth/.test(opened.detail)) {
      note(`${width}px`, 'More did not open the rest of the detail');
    }
  } catch (e) {
    note(`${width}px`, `the disclosure could not be driven: ${e.message}`);
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
  // The rare press lives behind the ⋯ and the snooze does not: Dismiss is
  // on the row, so a menu offering it again is the same press twice.
  if (menu && !menu.some((row) => /already fixed it/i.test(row))) {
    note(`${width}px`, '"I\'ve already fixed it" is not behind the ⋯');
  }
  if (menu && menu.some((row) => /^(Later|Dismiss)\b/i.test(row))) {
    note(`${width}px`, 'the ⋯ offers the snooze a second time');
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
console.log('\nevery case offers the presses that fit it and a way to say no, '
  + 'names things by name, keeps its reasoning one press away, and the '
  + 'Resident line says what it did today');
