// History › Changes brAIn made, measured (#453).
//
// "A running list of all the actions that brain has taken and changes it
// made. Each action should have an undo button next to it." Against the
// panel's REAL `renderHistory` behind `today-fixture.mjs`'s stubbed fetch,
// at 390 (touch) and 1200, it fails on:
//
//   * no "Changes brAIn made" filter in History, or one that lists nothing;
//   * a row with no name;
//   * a row with neither an Undo nor a sentence saying why it has none, or
//     with both;
//   * an Undo that does not confirm what it puts back, or does not post the
//     route the row named;
//   * a row's "when · from where" line missing;
//   * a press under the 44px touch floor, or a page that scrolls sideways.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CHANGES, openToday, posts } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const [width, touch] of [[390, true], [1200, false]]) {
  const where = `${width}px`;
  const errors = [];
  const { page, context } = await openToday(browser, PANEL, {
    width, touch, onError: (m) => errors.push(m) });
  await page.evaluate(() => switchView('archive'));
  await page.waitForSelector('#histFilters button', { timeout: 5000 }).catch(() => {});
  const pill = await page.$('#histFilters button[data-filter="changes"]');
  if (!pill) {
    note(where, 'History has no "Changes brAIn made" filter');
    await context.close();
    continue;
  }
  const label = await pill.evaluate((b) => b.querySelector('span').textContent);
  if (label !== 'Changes brAIn made') note(where, `the filter is called "${label}"`);
  await pill.click();
  await page.waitForTimeout(150);
  const rows = await page.evaluate(() => [...document.querySelectorAll(
    '#histList .histrow')].map((r) => ({
    title: r.querySelector('.histtitle')?.textContent.trim() || '',
    meta: r.querySelector('.item-state')?.textContent.trim() || '',
    undo: [...r.querySelectorAll('button')].filter((b) => b.textContent.trim() === 'Undo').length,
    reason: r.querySelector('.histreason')?.textContent.trim() || '',
    right: Math.round(r.getBoundingClientRect().right),
  })));
  if (rows.length !== CHANGES.rows.length) {
    note(where, `${rows.length} rows, not ${CHANGES.rows.length}`);
  }
  rows.forEach((r, i) => {
    const id = r.title || `row ${i}`;
    if (!r.title) note(where, `row ${i} has no name`);
    if (!r.meta || !r.meta.includes('·')) note(where, `${id}: when and where read "${r.meta}"`);
    if (!r.undo && !r.reason) note(where, `${id} has neither Undo nor a reason`);
    if (r.undo && r.reason) note(where, `${id} has both Undo and a reason`);
    if (r.undo > 1) note(where, `${id} has ${r.undo} Undo buttons`);
  });
  const hint = await page.evaluate(() => document.getElementById('histHint').textContent);
  if (!/Undo puts one back/.test(hint)) note(where, `the filter's line reads "${hint}"`);

  // Undo confirms, then posts the row's own route.
  let confirmText = '';
  page.once('dialog', (d) => { confirmText = d.message(); d.accept(); });
  await page.click('#histList .histrow button');
  await page.waitForTimeout(250);
  if (!/Puts each device back/.test(confirmText)) {
    note(where, `Undo confirms with "${confirmText}"`);
  }
  const sent = (await posts(page)).map((p) => p.url);
  if (!sent.some((u) => u.includes('api/changes/call/1.000000/undo'))) {
    note(where, `Undo posted ${JSON.stringify(sent)}`);
  }

  const layout = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth, view: window.innerWidth }));
  if (layout.doc > layout.view + 1) note(where, `scrolls sideways (${layout.doc} > ${layout.view})`);
  if (touch) {
    const small = await page.evaluate(() => [...document.querySelectorAll(
      '#viewArchive button')].filter((b) => b.offsetParent !== null)
      .map((b) => ({ t: b.textContent.trim().slice(0, 20),
                     h: Math.round(b.getBoundingClientRect().height),
                     w: Math.round(b.getBoundingClientRect().width) }))
      .filter((b) => b.h < 44 || b.w < 44));
    if (small.length) note(where, `under the touch floor: ${JSON.stringify(small)}`);
  }
  if (errors.length) note(where, `page errors: ${errors.join(' | ')}`);
  await context.close();
}

await browser.close();
if (failures.length) {
  console.log(`FAIL (${failures.length})`);
  failures.forEach((f) => console.log(`  ${f}`));
  process.exit(1);
}
console.log('OK: Changes brAIn made lists every change with its Undo or its reason.');
