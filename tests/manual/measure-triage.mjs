// Render the Findings tab against rows that HAVE been looked at, and assert
// that what a person reads tells them which is which.
//
// The failure this exists to prevent is the one triage is supposed to end,
// arriving one layer up: a card that nothing checked looking exactly like a
// card something did. So the checks are about what each row SAYS.
//
//   * a live card that a run elevated carries the reason it was elevated,
//     because "brAIn checked, and here is what it looked at" is the whole
//     of what this step buys a person — and one that nothing could check
//     says THAT, in words, for the same reason a to-do row says "done" in
//     words rather than by a strike-through: status by colour alone is
//     what the design system forbids, and this line is read at 13px.
//   * the "Looked at" filter exists once something is in it and not
//     before, so a house with nothing held is one fewer chip.
//   * every held row says what was checked and offers exactly one verb,
//     which puts it back. A held row with nothing to press is a verdict
//     nothing can correct, which is the thing that would make this step
//     worse than not having it.
//   * the view opens with the sentence that says what the list IS. Without
//     it, problems under a tab read as problems you have, and these are
//     the ones brAIn is saying you do not.
//   * nothing overflows, nothing scrolls sideways, and the chips clear the
//     touch floor on touch.
//
// It drives the panel's REAL `renderFindings`/`makeHeld`/`triageLine`
// behind a stubbed fetch — measure-activity's rule, because a copy of the
// renderer in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 430, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];
// A chip, not a card button. The panel's touch floor is scoped per control
// and `.fchip` carries one; `.findactions .btn` deliberately does not, and
// asserting it here and nowhere else would be one tab holding a rule its
// sibling does not.
const MIN_CHIP = 40;

const NOW = Math.floor(Date.now() / 1000);
const row = (over) => ({
  ts: 0, text: '', detail: '', fix: '', severity: 'warning', fixable: true,
  entity_id: '', source: 'check:dev.frozen', source_title: 'Device checks',
  run_id: '', status: 'open', result: '', changed: [], settled_at: 0,
  snoozed_until: 0, checked_at: 0, triage: {}, ...over,
});

const FINDINGS = [
  row({ ts: NOW - 60, text: 'The freezer has been 6 degrees warmer for a week',
        detail: 'now -12C, usually -18C', entity_id: 'sensor.freezer',
        severity: 'serious',
        triage: { verdict: 'elevated', at: NOW - 55, run_id: 'sess-a',
                  elevated_by_person: false,
                  reason: 'its own month of statistics really does drift '
                    + 'upward and no other freezer in the house does' } }),
  row({ ts: NOW - 120, text: 'The disk is 91% full',
        detail: '4.1 GB free', severity: 'warning',
        triage: { verdict: 'untriaged', at: NOW - 110, run_id: '',
                  elevated_by_person: false,
                  reason: 'The usage budget is spent, so nothing looked at '
                    + 'this before showing it.' } }),
  row({ ts: NOW - 180, text: 'The pantry contact has not changed in 9 days',
        detail: 'last change 3 Sep', entity_id: 'binary_sensor.pantry',
        status: 'held',
        triage: { verdict: 'held', at: NOW - 170, run_id: 'sess-b',
                  elevated_by_person: false,
                  reason: 'its history shows it moved twice last month — it '
                    + 'is a cupboard, not a stuck sensor' } }),
  row({ ts: NOW - 240, text: 'The nozzle is reading 220C',
        detail: 'outside -40 to 60C', entity_id: 'sensor.printer_nozzle',
        status: 'held',
        triage: { verdict: 'held', at: NOW - 230, run_id: 'sess-b',
                  elevated_by_person: false,
                  reason: 'it is named nozzle and sits on a 3D printer, so '
                    + 'that is an ordinary reading' } }),
];

const STUB = `
window.__findings = {
  findings: ${JSON.stringify(FINDINGS)},
  hypotheses: [], open: 2, settled: [], scorecard: [],
};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/findings')) return answer(window.__findings);
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 2,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/todo')) {
    return answer({ items: [], done: [], open: 0, done_count: 0 });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const read = (page) => page.evaluate(() => {
  const cards = [...document.querySelectorAll('#findList .finding')];
  return {
    lede: document.querySelector('#findList .findlede')?.textContent || '',
    chips: [...document.querySelectorAll('#findFilters .fchip')].map((b) => ({
      label: b.textContent.trim(),
      h: Math.round(b.getBoundingClientRect().height),
    })),
    cards: cards.map((c) => {
      const box = c.getBoundingClientRect();
      const line = c.querySelector('.findtriage');
      return {
        title: c.querySelector('.findtitle')?.textContent || '',
        held: c.classList.contains('held'),
        state: [...c.querySelectorAll('.findstate')]
          .map((s) => s.textContent.trim()).join(' '),
        triage: line ? line.textContent.trim() : '',
        triageLabel: line?.querySelector('.findtriagelabel')?.textContent || '',
        unchecked: !!line && line.classList.contains('unchecked'),
        record: [...(line?.querySelectorAll('button') || [])]
          .map((b) => b.textContent.trim()),
        verbs: [...c.querySelectorAll('.findactions button')]
          .map((b) => b.textContent.trim()),
        right: Math.round(box.right),
      };
    }),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
});

for (const { width, touch } of CASES) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="findings"]');
  await page.waitForSelector('#findList .finding');

  const live = await read(page);

  // The live list is what triage let through, and nothing it held.
  if (live.cards.length !== 2) {
    note(`${width}px`, `${live.cards.length} live cards, expected 2`);
  }
  for (const card of live.cards) {
    if (card.held) note(`${width}px`, `"${card.title}" is held and on the work list`);
    if (!card.triage) {
      note(`${width}px`, `"${card.title}" does not say whether anything checked it`);
      continue;
    }
    if (card.triage.length < 30) {
      note(`${width}px`, `"${card.title}" says only "${card.triage}"`);
    }
  }
  const checked = live.cards.find((c) => /freezer/i.test(c.title));
  const unchecked = live.cards.find((c) => /disk/i.test(c.title));
  if (checked && !/checked/i.test(checked.triageLabel)) {
    note(`${width}px`, `a checked card is labelled "${checked.triageLabel}"`);
  }
  if (checked && !checked.record.length) {
    note(`${width}px`, 'a checked card offers no way to read what it checked');
  }
  // The one that must not read as the other. The colour is reinforcement;
  // the words are the claim.
  if (unchecked) {
    if (!/not checked/i.test(unchecked.triageLabel)) {
      note(`${width}px`,
           `an unchecked card is labelled "${unchecked.triageLabel}" — it `
           + 'reads exactly like one that was checked');
    }
    if (!unchecked.unchecked) {
      note(`${width}px`, 'an unchecked card is not marked as one');
    }
    if (unchecked.record.length) {
      note(`${width}px`, 'an unchecked card offers a conversation to read');
    }
  }
  if (checked && unchecked && checked.triageLabel === unchecked.triageLabel) {
    note(`${width}px`,
         `a checked and an unchecked card both say "${checked.triageLabel}"`);
  }

  const lookedChip = live.chips.find((c) => /^Looked at/.test(c.label));
  if (!lookedChip) {
    note(`${width}px`,
         `no "Looked at" chip (${live.chips.map((c) => c.label).join(', ')})`);
  } else {
    if (touch && lookedChip.h < MIN_CHIP) {
      note(`${width}px`, `the chip is ${lookedChip.h}px tall on touch`);
    }
    await page.evaluate(() => {
      state.findFilter = 'held';         // eslint-disable-line no-undef
      renderFindings();                  // eslint-disable-line no-undef
    });
    await page.waitForSelector('#findList .finding.held');
    const held = await read(page);
    if (!held.lede || held.lede.length < 40) {
      note(`${width}px`,
           'the Looked-at view opens without saying what the list is, so it '
           + 'reads as problems you have');
    }
    if (held.cards.length !== 2) {
      note(`${width}px`, `${held.cards.length} held cards, expected 2`);
    }
    for (const card of held.cards) {
      if (!card.state) {
        note(`${width}px`, `"${card.title}" does not say it is not being shown`);
      }
      if (!card.triage) {
        note(`${width}px`, `"${card.title}" does not say what was checked`);
      }
      if (!card.record.length) {
        note(`${width}px`,
             `"${card.title}" offers no way to read the conversation behind it`);
      }
      if (card.verbs.length !== 1 || !/front/i.test(card.verbs.join(' '))) {
        note(`${width}px`,
             `"${card.title}" carries ${card.verbs.length} verb(s): `
             + `${card.verbs.join(' | ')} — a held row needs exactly one, and `
             + 'it is the one that puts it back');
      }
      if (card.right > held.viewport + 1) {
        note(`${width}px`, `"${card.title}" hangs off the side`);
      }
    }
    // The two reasons must differ, or the view has stopped distinguishing
    // the rows it is explaining — measure-chatres' own rule.
    const reasons = new Set(held.cards.map((c) => c.triage));
    if (held.cards.length > 1 && reasons.size < held.cards.length) {
      note(`${width}px`, 'two held rows carry the same explanation');
    }
    if (held.docWidth > held.viewport + 1) {
      note(`${width}px`,
           `page scrolls sideways (${held.docWidth} > ${held.viewport})`);
    }
  }

  // ...and a house with nothing held is offered no chip at all.
  let empty = null;
  try {
    await page.evaluate((rows) => {
      window.__findings = { findings: rows, hypotheses: [], open: 2,
                            settled: [], scorecard: [] };
    }, FINDINGS.filter((f) => f.status !== 'held'));
    empty = await page.evaluate(async () => {
      await refreshFindings();           // eslint-disable-line no-undef
      state.findFilter = 'live';         // eslint-disable-line no-undef
      renderFindings();                  // eslint-disable-line no-undef
      return [...document.querySelectorAll('#findFilters .fchip')]
        .map((b) => b.textContent.trim());
    });
  } catch (e) {
    // Notes rather than throws: measure-cardlive's first run abandoned
    // nineteen findings it had already gathered to report one helper.
    note(`${width}px`, `could not re-render with nothing held: ${e.message}`);
  }
  if (empty && empty.some((l) => /^Looked at/.test(l))) {
    note(`${width}px`, 'the "Looked at" chip is offered with nothing in it');
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-triage: %d problem(s)\n', failures.length);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('measure-triage: the Looked-at view says what it is, every row '
  + 'says what was checked, and nothing unchecked reads as checked.');
