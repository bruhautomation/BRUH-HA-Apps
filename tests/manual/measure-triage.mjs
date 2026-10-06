// What a card says about whether brAIn looked at it, on Today (docs/design/
// ui-redesign-2026-10.md, "One card": the NEEDS A DECISION / NOT LOOKED AT
// YET prose is cut, and an item's state is words on the meta line).
//
// The failure this exists to prevent is the one triage is supposed to end:
// a card that nothing checked looking exactly like a card something did.
// The redesign moved where that is said, not whether it is said:
//
//   * a card no look has reached yet says "Unchecked" on its meta line, in
//     words, and the longer sentence about it is under Details;
//   * a card a look elevated carries what that look said, under Details —
//     "brAIn checked" and its reason — and nothing about it on the face;
//   * the unchecked card offers the same row every finding has, Add to
//     list · Check again · Dismiss · Snooze · Ignore, and each press sends the finding's own route
//     (Ignore with the reason typed into "Why? (helps brAIn learn)");
//   * a row a look set aside is in History › "Set aside by brAIn" with one
//     press, Restore, which sends the row's elevate — a verdict nothing can
//     correct is what would make this step worse than not having it;
//   * the cut labels stay off every face;
//   * nothing scrolls sideways, and on touch every press is 44px.
//
// It drives the panel's REAL renderers behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts, CUT } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

const read = (page, id) => page.evaluate(({ id, cut }) => {
  const c = document.querySelector(`[data-case-id="${id}"]`);
  if (!c) return null;
  const face = c.cloneNode(true);
  face.querySelectorAll('details').forEach((d) => d.remove());
  const det = c.querySelector(':scope > details');
  const res = cut.map((s) => new RegExp(s.source, s.flags));
  return {
    meta: [...c.querySelectorAll('.meta > *')].map((x) => x.textContent).join(' · '),
    face: face.textContent,
    details: det ? det.textContent : '',
    presses: [...c.querySelectorAll(':scope > .card-actions button')]
      .filter((b) => !b.classList.contains('icon')).map((b) => b.textContent.trim()),
    heights: [...c.querySelectorAll(':scope > .card-actions button')]
      .map((b) => Math.round(b.getBoundingClientRect().height)),
    cut: res.filter((re) => re.test(face.textContent)).map(String),
  };
}, { id, cut: CUT.map((re) => ({ source: re.source, flags: re.flags })) });

for (const { width, touch } of [{ width: 390, touch: true }, { width: 430, touch: true },
                                { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { page, context } = await openToday(browser, PANEL,
    { width, touch, onError: (m) => note(where, `page error: ${m}`) });

  const loose = await read(page, 'f:2001');
  if (!loose) note(where, 'the unchecked finding is not drawn');
  else {
    if (!/\bUnchecked\b/.test(loose.meta)) note(where, `the unchecked card's meta reads "${loose.meta}"`);
    if (!/brAIn has not looked at this one yet/.test(loose.details)) {
      note(where, 'Details does not say nothing has looked at it');
    }
    if (loose.presses.join('|') !== 'Add to list|Check again|Dismiss|Snooze|Ignore') {
      note(where, `the unchecked card offers ${loose.presses.join(' · ')}`);
    }
    if (loose.cut.length) note(where, `the unchecked card carries ${loose.cut.join(', ')}`);
    if (touch && loose.heights.some((h) => h < MIN_TARGET)) {
      note(where, `an unchecked press is under ${MIN_TARGET}px (${loose.heights.join(',')})`);
    }
  }
  const looked = await read(page, 'f:1101');
  if (!looked) note(where, 'the elevated case is not drawn');
  else {
    if (!/brAIn checked/.test(looked.details) || !/A real drift/.test(looked.details)) {
      note(where, 'Details does not carry what the look said');
    }
    if (/brAIn checked|A real drift/.test(looked.face)) {
      note(where, 'the look\'s verdict is on the face of the card');
    }
  }

  // The presses on the unchecked card, each to its own route.
  await page.locator('[data-case-id="f:2001"] .card-actions button:text-is("Dismiss")').click();
  await page.waitForTimeout(150);
  await page.locator('[data-case-id="f:2001"] .card-actions button:text-is("Snooze")').click();
  await page.waitForTimeout(150);
  await page.locator('[data-case-id="f:2001"] .card-actions button:text-is("Add to list")').click();
  await page.waitForTimeout(150);
  await page.locator('[data-case-id="f:2001"] .card-actions button:text-is("Ignore")').click();
  const form = page.locator('[data-case-id="f:2001"] .findnote');
  const hint = await form.locator('.findnotehint').textContent();
  if (hint !== 'Why? (helps brAIn learn)') note(where, `Ignore asks "${hint}"`);
  await form.locator('textarea').fill('It sleeps between motions.');
  await form.locator('.findnoteactions button', { hasText: 'Ignore' }).click();
  await page.waitForTimeout(150);
  const sent = await posts(page);
  if (!(await posts(page)).some((p) => /api\/finding\/2001$/.test(p.url)
      && p.method === 'DELETE')) note(where, 'Dismiss did not DELETE the finding');
  const want = [
    [/api\/finding\/2001\/snooze$/, (b) => b && b.for === 'week'],
    [/api\/finding\/2001\/todo$/, () => true],
    [/api\/finding\/2001\/wrong$/, (b) => b && b.note === 'It sleeps between motions.'],
  ];
  for (const [re, ok] of want) {
    const hit = sent.find((p) => re.test(p.url));
    if (!hit || !ok(hit.body)) note(where, `no press matched ${re} (${JSON.stringify(hit)})`);
  }

  // Set aside by brAIn: in Insights › History, with Restore (and Delete,
  // which clears the record and changes no decision).
  await page.evaluate(() => switchView('archive'));
  await page.waitForSelector('#histFilters button[data-filter="aside"]');
  await page.evaluate(() => document.querySelector('#histFilters button[data-filter="aside"]').click());
  const aside = await page.evaluate(() => [...document.querySelectorAll('#histList .histrow')]
    .map((r) => ({ title: r.querySelector('.histtitle').textContent,
                   presses: [...r.querySelectorAll('button:not(.histdel)')].map((b) => b.textContent.trim()) })));
  if (aside.length !== 1 || aside[0].presses.join('|') !== 'Restore') {
    note(where, `Set aside by brAIn reads ${JSON.stringify(aside)}`);
  } else {
    await page.evaluate(() => document.querySelector('#histList .histrow button').click());
    await page.waitForTimeout(150);
    const back = (await posts(page)).some((p) => /api\/finding\/7\/elevate$/.test(p.url));
    if (!back) note(where, 'Restore on a set-aside row sent no elevate');
  }

  const face = await page.evaluate((cut) => {
    const clone = document.getElementById('findList').cloneNode(true);
    clone.querySelectorAll('details').forEach((d) => d.remove());
    return cut.map((s) => new RegExp(s.source, s.flags)).filter((re) => re.test(clone.textContent))
      .map(String);
  }, CUT.map((re) => ({ source: re.source, flags: re.flags })));
  if (face.length) note(where, `the queue carries cut text: ${face.join(', ')}`);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (wide) note(where, 'the page scrolls sideways');
  await context.close();
  console.log(`${failures.length ? 'FAIL' : 'ok  '} ${where}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-triage: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-triage: an unchecked card says so in words, and a set-aside one can come back');
