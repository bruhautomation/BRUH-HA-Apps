// The queue's cards, pressed: every kind of case on Today answered from the
// card it is on, with the redesign's one row of words (docs/design/
// ui-redesign-2026-10.md, "One card", PR 4).
//
// measure-today asserts the SHAPE every card shares (one chip, one primary,
// a closed Details, three lines of body). This one asserts what each kind of
// card OFFERS and what each press SENDS, which is where the old row went
// wrong — "Yes/no questions have a 'do it' button… I don't always see a
// dismiss" — and then wrong again with Fix it · Add to list · Dismiss · Not a
// problem on every card whether or not brAIn could act:
//
//   * a problem brAIn could act on leads with Plan; one only a person can
//     fix leads with Add to list and offers no Plan; a plan waiting for
//     consent leads with Apply; a question is Yes · No · Snooze and never a
//     verb; a change brAIn made is Done · Undo and nothing else;
//   * every card a person answers carries Snooze and a way to say no
//     (Ignore, or No on a question), on the face and never behind the ⋯;
//   * the ⋯ holds at most three things, all from the vocabulary;
//   * the face names things by their friendly name and the id is under
//     Details, which is closed and opens to the source;
//   * Snooze posts the case's not_now; Ignore opens "Why? (helps brAIn
//     learn)" with "Ignore all like this", and sending both posts the
//     note to the case's wrong AND the rule's mute; a card whose producer
//     cannot be muted (safety) offers no tick;
//   * the controls the old feed carried — the filter chips, Run checks now,
//     the scorecard, the muted list, the foot — are gone and stay gone;
//   * on touch every press is 44px, and nothing scrolls sideways.
//
// It drives the panel's REAL renderers behind today-fixture's stubbed fetch
// (measure-activity's rule — a copy of the renderer here would only ever
// agree with itself).
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts, VOCAB } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;
// The old feed's controls. Each id is one a handler used to bind to, and a
// screen that grows one back is the chrome the redesign cut.
const CUT_IDS = ['findFilters', 'findRunChecks', 'findScore', 'findMuted', 'findFoot',
                 'viewTodo', 'viewProposals', 'todoBadge', 'propBadge'];
const KEPT_IDS = ['viewFindings', 'findList', 'findBadge', 'todayMore', 'todoList',
                  'todoAdd', 'todoText', 'todayStatus'];

// What each case in the fixture must lead with, and what it may never offer.
const ROWS = {
  'f:1100': { lead: 'Add to list', never: ['Plan', 'Apply'] },
  'f:1101': { lead: 'Plan', never: ['Apply'] },
  'f:1102': { lead: 'Apply', never: ['Plan'] },
  'h:1103': { lead: 'Yes', exact: ['Yes', 'No', 'Snooze'] },
  'f:1104': { lead: 'Done', exact: ['Done', 'Undo'] },
  'f:1105': { lead: 'Add to list', never: ['Plan', 'Apply'] },
  'f:1106': { lead: 'Plan', never: ['Apply'] },
};

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { page, context } = await openToday(browser, PANEL,
    { width, touch, onError: (m) => note(where, `page error: ${m}`) });

  const ids = await page.evaluate((list) => list.filter((id) => document.getElementById(id)),
    CUT_IDS);
  if (ids.length) note(where, `cut controls are back: ${ids.join(', ')}`);
  const missing = await page.evaluate((list) => list.filter((id) => !document.getElementById(id)),
    KEPT_IDS);
  if (missing.length) note(where, `ids a handler binds to are gone: ${missing.join(', ')}`);

  const cards = await page.evaluate(() => [...document.querySelectorAll('#findList .qcard')]
    .map((c) => {
      const face = c.cloneNode(true);
      face.querySelectorAll('details').forEach((d) => d.remove());
      const presses = [...c.querySelectorAll(':scope > .card-actions button')]
        .filter((b) => !b.classList.contains('icon'));
      return {
        id: c.dataset.caseId,
        labels: presses.map((b) => b.textContent.trim()),
        primary: presses.filter((b) => b.classList.contains('btn-primary'))
          .map((b) => b.textContent.trim()),
        heights: [...c.querySelectorAll(':scope > .card-actions button')]
          .map((b) => Math.round(b.getBoundingClientRect().height)),
        menu: !!c.querySelector(':scope > .card-actions .btn.icon'),
        face: face.textContent,
      };
    }));
  for (const [id, want] of Object.entries(ROWS)) {
    const card = cards.find((c) => c.id === id);
    if (!card) { note(where, `${id} is not drawn`); continue; }
    if (card.primary.length !== 1 || card.primary[0] !== want.lead) {
      note(where, `${id} leads with ${JSON.stringify(card.primary)}, not ${want.lead}`);
    }
    if (card.labels[0] !== want.lead) note(where, `${id}'s first press is "${card.labels[0]}"`);
    if (want.exact && card.labels.join('|') !== want.exact.join('|')) {
      note(where, `${id} offers ${card.labels.join(' · ')}`);
    }
    for (const n of want.never || []) {
      if (card.labels.includes(n)) note(where, `${id} offers ${n}`);
    }
    if (id !== 'f:1104') {
      if (!card.labels.includes('Snooze')) note(where, `${id} has no Snooze on its face`);
      if (!card.labels.includes('Ignore') && !card.labels.includes('No')) {
        note(where, `${id} has no way to say no on its face`);
      }
    }
    if (card.labels.length > 4) note(where, `${id} carries ${card.labels.length} presses`);
    if (touch && card.heights.some((h) => h < MIN_TARGET)) {
      note(where, `${id} has a press under ${MIN_TARGET}px (${card.heights.join(',')})`);
    }
  }
  const freezer = cards.find((c) => c.id === 'f:1101');
  if (freezer && /sensor\.garage_freezer/.test(freezer.face)) {
    note(where, 'the face names sensor.garage_freezer by its id');
  }
  if (freezer && !/Garage Freezer/.test(freezer.face)) note(where, 'the face lost the name');

  // Details: closed, and it opens to where the claim came from and the id.
  const det = await page.evaluate(() => {
    const d = document.querySelector('[data-case-id="f:1101"] > details');
    if (!d) return null;
    const closed = !d.open;
    d.open = true;
    return { closed, text: d.textContent,
             id: d.querySelector('code.qdid')?.textContent || '' };
  });
  if (!det) note(where, 'the freezer card has no Details');
  else {
    if (!det.closed) note(where, 'Details is open by default');
    if (!/Drift check/.test(det.text)) note(where, 'Details does not say where the claim came from');
    if (det.id !== 'sensor.garage_freezer') note(where, `Details shows the id as "${det.id}"`);
  }

  // The ⋯: at most three, all words from the vocabulary.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.locator('[data-case-id="f:1101"] .card-actions .btn.icon').click();
  const menu = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
    .map((b) => b.textContent));
  if (!menu.length) note(where, 'the ⋯ opens nothing');
  if (menu.length > 3) note(where, `the ⋯ holds ${menu.length}: ${menu.join(' | ')}`);
  for (const m of menu) if (!VOCAB.has(m)) note(where, `the ⋯ offers "${m}"`);
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.body.click());

  // Snooze sends the case's not_now.
  await page.locator('[data-case-id="f:1102"] .card-actions button:text-is("Snooze")').click();
  await page.waitForTimeout(150);
  let sent = await posts(page);
  if (!sent.some((p) => /api\/case\/f:1102\/not_now$/.test(p.url))) {
    note(where, `Snooze sent ${JSON.stringify(sent.map((p) => p.url))}`);
  }

  // Ignore with a reason and the tick: the wrong and the mute, both.
  await page.locator('[data-case-id="f:1101"] .card-actions button:text-is("Ignore")').click();
  const form = page.locator('[data-case-id="f:1101"] .findnote');
  await form.locator('textarea').fill('It is a chest freezer in a hot garage.');
  const tick = form.locator('.findnotecheck input');
  if (!(await tick.count())) note(where, 'Ignore offers no "Ignore all like this"');
  else await tick.check();
  const fontSize = await form.locator('textarea').evaluate((t) => getComputedStyle(t).fontSize);
  if (touch && parseFloat(fontSize) < 16) note(where, `the reason box is ${fontSize} on touch`);
  await form.locator('.findnoteactions button', { hasText: 'Ignore' }).click();
  await page.waitForTimeout(200);
  sent = await posts(page);
  const wrong = sent.find((p) => /api\/case\/f:1101\/wrong$/.test(p.url));
  if (!wrong || wrong.body?.note !== 'It is a chest freezer in a hot garage.') {
    note(where, `Ignore sent ${JSON.stringify(wrong)}`);
  }
  const mute = sent.find((p) => /api\/findings\/mute$/.test(p.url));
  if (!mute || mute.body?.source !== 'check:base.trend') {
    note(where, `"Ignore all like this" sent ${JSON.stringify(mute)}`);
  }

  // A safety card cannot have its rule muted, so it offers no tick.
  await page.locator('[data-case-id="f:1100"] .card-actions button:text-is("Ignore")').click();
  const safetyTick = await page.locator('[data-case-id="f:1100"] .findnote .findnotecheck').count();
  if (safetyTick) note(where, 'a safety card offers "Ignore all like this"');

  const wide = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (wide) note(where, 'the page scrolls sideways');
  await context.close();
  console.log(`${failures.length ? 'FAIL' : 'ok  '} ${where}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-home: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-home: every card offers its own row, and every press says what it sent');
