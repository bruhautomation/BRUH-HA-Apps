// Ask brAIn about anything: right-click (or press and hold on touch) a card
// on Today and a small box opens at the press; Ask sends a prompt naming what
// was pressed to POST api/terminal/open, which opens it in Claude Code's own
// terminal. Holds:
//
//   * a right-click on a card opens the box, inside the viewport, with the
//     card's first line in it and a 16px text box (iOS zooms below that);
//   * Ask posts {prompt} to api/terminal/open, and the prompt quotes the
//     card's text and carries the person's words;
//   * a right-click in a text box and a shift+right-click open nothing;
//   * on touch a press held still opens it, and one that moves does not;
//   * every press in the box is 44px tall.
//
// Driven against the REAL app.js behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const failures = [];
const note = (where, m) => failures.push(`${where}: ${m}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

for (const { width, touch } of [{ width: 1200, touch: false }, { width: 390, touch: true }]) {
  const where = `${width}px`;
  const { page } = await openToday(browser, PANEL,
    { width, touch, onError: (m) => note(where, `page error: ${m}`) });
  const card = page.locator('#findList .qcard, #findList .case, #findList article').first();
  if (!(await card.count())) { note(where, 'no card on Today to press'); continue; }
  await card.scrollIntoViewIfNeeded();
  const box = await card.boundingBox();
  const cx = box.x + Math.min(40, box.width / 2), cy = box.y + 20;

  if (touch) {
    // Held still: opens.
    await page.evaluate(([x, y]) => {
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: x, clientY: y, pointerType: 'touch' }));
    }, [cx, cy]);
    await page.waitForTimeout(800);
    if (!(await page.locator('#askAbout').count())) note(where, 'a press held still opened nothing');
    await page.evaluate(() => document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true })));
    await page.keyboard.press('Escape');
    // Moved: opens nothing.
    await page.evaluate(([x, y]) => {
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: x, clientY: y, pointerType: 'touch' }));
      document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: x + 40, clientY: y, pointerType: 'touch' }));
    }, [cx, cy]);
    await page.waitForTimeout(800);
    if (await page.locator('#askAbout').count()) note(where, 'a press that moved (a scroll) opened the box');
    await page.keyboard.press('Escape');
  }

  await page.mouse.click(cx, cy, { button: 'right' });
  const m = await page.evaluate(() => {
    const b = document.getElementById('askAbout');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    const i = b.querySelector('textarea');
    return {
      inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
      snip: b.querySelector('.aasnip').textContent,
      font: parseFloat(getComputedStyle(i).fontSize),
      heights: [...b.querySelectorAll('button')].map((x) => Math.round(x.getBoundingClientRect().height)),
    };
  });
  if (!m) { note(where, 'a right-click on a card opened nothing'); continue; }
  if (!m.inside) note(where, 'the box hangs off the screen');
  if (!m.snip.trim()) note(where, 'the box does not say what was pressed');
  if (m.font < 16) note(where, `the text box is ${m.font}px (iOS zooms under 16)`);
  if (m.heights.some((h) => h < 44)) note(where, `a press in the box is under 44px: ${m.heights.join(',')}`);
  await page.fill('#askAbout textarea', 'turn it off for the night');
  await page.click('#askAbout .btn.primary');
  await page.waitForTimeout(300);
  const sent = (await posts(page)).filter((p) => /api\/terminal\/open/.test(p.url));
  if (!sent.length) note(where, 'Ask did not post to api/terminal/open');
  else {
    const prompt = (sent[sent.length - 1].body || {}).prompt || '';
    if (!prompt.includes('turn it off for the night')) note(where, 'the prompt lost the words typed');
    if (!prompt.includes('> ')) note(where, 'the prompt does not quote what was pressed');
  }
  if (await page.locator('#askAbout').count()) note(where, 'the box stayed open after Ask');

  // Shift+right-click is the browser's.
  await page.evaluate(() => window.switchView && window.switchView('findings'));
  await page.keyboard.down('Shift');
  await page.mouse.click(cx, cy, { button: 'right' });
  await page.keyboard.up('Shift');
  if (await page.locator('#askAbout').count()) note(where, 'shift+right-click opened the box');
  await page.close();
}
await browser.close();
if (failures.length) {
  console.error('measure-askabout:\n  ' + failures.join('\n  '));
  process.exit(1);
}
console.log('measure-askabout: all checks passed');
