// Suggestions on Today: what the proposals store offers, as cards in the one
// queue (docs/design/ui-redesign-2026-10.md — the Proposals tab is gone and
// a suggestion is a card with the Suggestion chip).
//
// The failure this exists to prevent is not a layout bug. It is a card that
// looks fine and quietly loses the one thing that makes a suggestion
// answerable: the evidence. A card with a title and two buttons is a
// suggestion from nowhere, and the honest answer to one of those is always
// no. So the checks are about what a card SAYS as much as what it sends:
//
//   * every suggestion carries its evidence on its face — the "why", or what
//     the replay found over the person's own history;
//   * a trialling card says how far in it is and what the week found, in
//     words a person would use ("you did the opposite on 1", never
//     `contradicted`), and the three states a trial can be in — graded, not
//     graded yet, refused — are three different sentences;
//   * an accept Home Assistant would not honour leaves the card where it was
//     with the refusal ON it, readable for longer than a toast; an accept
//     that lands takes the row away and offers Undo, because it writes to
//     /config;
//   * Ignore opens "Why? (helps brAIn learn)" in place of the buttons,
//     inside the card, 16px on touch, and sends the reason with the decline;
//     Snooze sends the suggestion's not_now; ⋯ › Run starts a trial;
//   * an emergency playbook shows what it would ACT ON under Details —
//     protected targets as skipped, the sentence that it never unlocks a
//     door — and offers no trial, saying why;
//   * a one-off waiting on the house is drawn and counted by nothing, and
//     its Delete asks first and then sends the remove;
//   * every press is 44px on touch, and nothing scrolls sideways.
//
// Drives the panel's REAL renderers behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts, PROPOSALS, NOW } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;

const TRIALS = [
  { ts: 3003000, status: 'trialling', title: 'Add an "office is empty" condition',
    why: 'You override Evening lights on 40% of weekday evenings.', config: { id: 'x' },
    kind: 'condition', snoozed_until: 0,
    trial_started_at: NOW - 3 * 86400, trial_ends_at: NOW + 4 * 86400,
    trial_result: { would_fire: 6, agreed: 4, disagreed: 1, contradicted: 1, days: 3 } },
  { ts: 3004000, status: 'trialling', title: 'Hall light off at midnight', why: 'Nine nights.',
    config: { id: 'y' }, kind: 'routine', snoozed_until: 0,
    trial_started_at: NOW - 3600, trial_ends_at: NOW + 6 * 86400, trial_result: null },
  { ts: 3005000, status: 'trialling', title: 'Fan off when the bathroom is dry',
    why: 'Every shower.', config: { id: 'z' }, kind: 'routine', snoozed_until: 0,
    trial_started_at: NOW - 86400, trial_ends_at: NOW + 6 * 86400,
    trial_result: { refused: true, error: 'a webhook trigger cannot be replayed' } },
];
const ALL = [...PROPOSALS.map((p) => (p.kind === 'playbook'
  ? { ...p, playbook: { ...p.playbook, note: 'It never unlocks a door.',
                        skipped: [{ entity_id: 'lock.front', name: 'Front door lock' }],
                        groups: [{ verb: 'Closes', targets: [{ name: 'Mains valve' }] }] } }
  : p)), ...TRIALS];

// The landed accept and the refused one, answered the way the server does.
const EXTRA = `
(() => {
  const inner = window.fetch;
  window.fetch = async (url, opts) => {
    const p = String(url);
    const d = window.__today;
    const json = (status, body) => new Response(JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' } });
    if (/api\\/proposal\\/3001000\\/accept$/.test(p)) {
      await inner(url, opts);
      d.proposals = d.proposals.filter((r) => r.ts !== 3001000);
      return json(200, { proposals: d.proposals, intents: d.intents, counts: {},
                         undo: 'tok', alias: 'Porch light off' });
    }
    if (/api\\/proposal\\/3003000\\/accept$/.test(p)) {
      await inner(url, opts);
      return json(409, { proposals: d.proposals, intents: d.intents, counts: {},
                         error: 'Home Assistant would not load it: unknown trigger platform' });
    }
    // Every other press on a suggestion or a one-off answers with the
    // list, as the server's routes do — an empty body would read as a
    // store with nothing in it.
    if (/api\\/(proposal|intent)\\//.test(p)) {
      await inner(url, opts);
      return json(200, { proposals: d.proposals, intents: d.intents, counts: {} });
    }
    return inner(url, opts);
  };
})();
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

const read = (page) => page.evaluate(() => [...document.querySelectorAll(
  '#findList .qcard[data-case-id^="p:"], #findList .qcard[data-case-id^="i:"]')].map((c) => {
  const face = c.cloneNode(true);
  face.querySelectorAll('details').forEach((d) => d.remove());
  const presses = [...c.querySelectorAll(':scope > .card-actions button')];
  return {
    id: c.dataset.caseId, counted: c.dataset.counted === '1',
    chip: c.querySelector('.chip-status').textContent,
    body: c.querySelector('.card-body')?.textContent || '',
    face: face.textContent, details: c.querySelector('details')?.textContent || '',
    presses: presses.filter((b) => !b.classList.contains('icon')).map((b) => b.textContent.trim()),
    menu: presses.some((b) => b.classList.contains('icon')),
    heights: presses.map((b) => Math.round(b.getBoundingClientRect().height)),
    right: Math.round(c.getBoundingClientRect().right),
    error: c.querySelector('.qerror')?.textContent || '',
  };
}));

for (const { width, touch } of [{ width: 390, touch: true }, { width: 768, touch: true },
                                { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { page, context } = await openToday(browser, PANEL, { width, touch, extra: EXTRA,
    over: { proposals: ALL }, onError: (m) => note(where, `page error: ${m}`) });
  page.on('dialog', (d) => d.accept());
  let cards = await read(page);
  const by = (id) => cards.find((c) => c.id === id);
  for (const p of ALL) {
    const c = by(`p:${p.ts}`);
    if (!c) { note(where, `p:${p.ts} is not drawn`); continue; }
    if (c.chip !== 'Suggestion') note(where, `p:${p.ts} chip is "${c.chip}"`);
    if (!c.body.trim()) note(where, `p:${p.ts} carries no evidence on its face`);
    if (c.presses.slice(0, 3).join('|') !== 'Apply|Snooze|Ignore') {
      note(where, `p:${p.ts} offers ${c.presses.join(' · ')}`);
    }
    if (!c.counted) note(where, `p:${p.ts} is not counted`);
    if (touch && c.heights.some((h) => h < MIN_TARGET)) {
      note(where, `p:${p.ts} has a press under ${MIN_TARGET}px (${c.heights.join(',')})`);
    }
    if (c.right > width + 1) note(where, `p:${p.ts} overflows`);
  }
  const graded = by('p:3003000');
  if (!graded || !/Day 3 of 7 · would have fired 6 times/.test(graded.face)
      || !/did the opposite on 1/i.test(graded.face) || /contradicted/.test(graded.face)) {
    note(where, `the graded trial reads "${graded && graded.face}"`);
  }
  const fresh = by('p:3004000');
  if (!fresh || !/nothing graded yet/.test(fresh.face) || /would have fired 0/.test(fresh.face)) {
    note(where, `the ungraded trial reads "${fresh && fresh.face}"`);
  }
  const refusedTrial = by('p:3005000');
  if (!refusedTrial || !/could not grade this trial — a webhook trigger cannot be replayed/
    .test(refusedTrial.face)) {
    note(where, `the refused trial reads "${refusedTrial && refusedTrial.face}"`);
  }
  const book = by('p:3002000');
  if (book) {
    if (!/Skipped: protected/.test(book.details) || !/Front door lock/.test(book.details)) {
      note(where, 'the playbook does not show its protected target as skipped');
    }
    if (!/never unlocks a door/.test(book.details)) note(where, 'the playbook hides "never unlocks"');
    if (!/No trial/.test(book.details)) note(where, 'the playbook does not say why there is no trial');
    if (book.menu) note(where, 'the playbook offers a trial under its ⋯');
  }
  const intent = by('i:4001000');
  if (!intent) note(where, 'the armed one-off is not drawn');
  else {
    if (intent.counted) note(where, 'the armed one-off is counted');
    if (intent.presses.join('|') !== 'Delete') note(where, `the one-off offers ${intent.presses}`);
  }

  // Snooze, ⋯ › Run, Ignore with a reason.
  await page.evaluate(() => [...document.querySelectorAll('[data-case-id="p:3004000"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Snooze').click());
  await page.waitForTimeout(150);
  await page.evaluate(() => document.querySelector('[data-case-id="p:3001000"]')
    .scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(150);
  await page.evaluate(() => document.querySelector('[data-case-id="p:3001000"] .card-actions .btn.icon').click());
  const menu = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
    .map((b) => b.textContent));
  if (menu.join('|') !== 'Run') note(where, `a plain suggestion's ⋯ holds ${menu.join(' | ')}`);
  await page.evaluate(() => document.querySelector('#chipPop .cardmenuitem')?.click());
  await page.waitForTimeout(200);
  await page.evaluate(() => [...document.querySelectorAll('[data-case-id="p:3004000"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Ignore').click());
  const form = page.locator('[data-case-id="p:3004000"] .findnote');
  const inPlace = await page.evaluate(() => {
    const c = document.querySelector('[data-case-id="p:3004000"]');
    return { form: !!c.querySelector('.findnote'),
             hidden: c.querySelector(':scope > .card-actions').classList.contains('hidden'),
             hint: c.querySelector('.findnotehint')?.textContent || '',
             font: parseFloat(getComputedStyle(c.querySelector('.findnote textarea')).fontSize) };
  });
  if (!inPlace.form || !inPlace.hidden) note(where, 'Ignore does not open in place of the buttons');
  if (inPlace.hint !== 'Why? (helps brAIn learn)') note(where, `Ignore asks "${inPlace.hint}"`);
  if (touch && inPlace.font < 16) note(where, `the reason box is ${inPlace.font}px on touch`);
  await form.locator('textarea').fill('We leave it on for the dog.');
  await form.locator('.findnoteactions button', { hasText: 'Ignore' }).click();
  await page.waitForTimeout(200);

  // A refused accept stays, with the reason on the card.
  await page.evaluate(() => [...document.querySelectorAll('[data-case-id="p:3003000"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Apply').click());
  await page.waitForTimeout(250);
  cards = await read(page);
  const stuck = cards.find((c) => c.id === 'p:3003000');
  if (!stuck) note(where, 'a refused accept took the card away');
  else if (!/would not load it/.test(stuck.error)) note(where, `the refusal reads "${stuck.error}"`);

  // A landed accept takes the card away, and the toast offers Undo.
  await page.evaluate(() => [...document.querySelectorAll('[data-case-id="p:3001000"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Apply').click());
  await page.waitForTimeout(250);
  cards = await read(page);
  if (cards.some((c) => c.id === 'p:3001000')) note(where, 'a landed accept left the card');
  const toast = await page.evaluate(() => ({
    text: document.getElementById('toast')?.textContent || '',
    undo: !!document.querySelector('#toast button') }));
  if (!/Added “Porch light off”/.test(toast.text) || !toast.undo) {
    note(where, `the accept's toast reads ${JSON.stringify(toast)}`);
  }

  // Delete on the one-off asks first, then removes.
  await page.evaluate(() => document.querySelector('[data-case-id="i:4001000"] .card-actions button').click());
  await page.waitForTimeout(200);

  const sent = (await posts(page)).map((p) => `${p.url.replace(/^.*?(api\/)/, '$1')} ${JSON.stringify(p.body)}`);
  for (const re of [/^api\/case\/p:3004000\/not_now /, /^api\/proposal\/3001000\/trial /,
                    /^api\/proposal\/3004000\/decline .*We leave it on for the dog/,
                    /^api\/proposal\/3003000\/accept /, /^api\/proposal\/3001000\/accept /,
                    /^api\/intent\/4001000\/remove /]) {
    if (!sent.some((s) => re.test(s))) note(where, `no press matched ${re}`);
  }
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
    note(where, 'the page scrolls sideways');
  }
  await context.close();
  console.log(`${failures.length ? 'FAIL' : 'ok  '} ${where}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-proposals: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-proposals: every suggestion carries its evidence and says what each press did');
