// To Do, on Today: the work somebody agreed to do (docs/design/
// ui-redesign-2026-10.md, "The first screen" — To Do sits under the
// queue; the To-do tab is gone).
//
// A chore you cannot finish from the screen it is on is indistinguishable
// from one nobody has got round to, and a list whose Done sits under the
// touch floor is one people stop using on the device they read it on. So:
//
//   * the section is headed "To Do" and carries no filter chips and no
//     badge of its own — the badge on Today is the queue's;
//   * a snoozed item is off the list until it comes back, and every row
//     shown says where it came from;
//   * every row carries two presses on its face, Done and Delete, and a ⋯
//     holding Snooze and Ignore; Delete takes it off the list and writes
//     nothing to memory;
//   * Done asks what was done (optional) and sends it with the press;
//     Snooze sends the item's not_now, Ignore its ignore;
//   * the add box says "Add to To Do…", is 16px on touch (or iOS zooms
//     the ingress frame in and never back out — the bug this measure caught
//     on its first run), is not squeezed to a sliver, and sends the text;
//   * an empty list is one line;
//   * on touch every press is 44px, and nothing scrolls sideways.
//
// It drives the panel's REAL renderTodo behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts, TODO } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

for (const { width, touch } of [{ width: 390, touch: true }, { width: 768, touch: true },
                                { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { page, context } = await openToday(browser, PANEL,
    { width, touch, onError: (m) => note(where, `page error: ${m}`) });

  const m = await page.evaluate(() => {
    const sec = document.getElementById('todoList').closest('section');
    return {
      head: sec.querySelector('h2')?.textContent || '',
      chips: sec.querySelectorAll('.findfilters, .histfilter, [role="tab"]').length,
      badge: !!document.getElementById('todoBadge'),
      rows: [...document.querySelectorAll('#todoList .todorow')].map((r) => ({
        id: r.dataset.todoId,
        title: r.querySelector('.todotitle')?.textContent || '',
        meta: r.querySelector('.item-state')?.textContent || '',
        presses: [...r.querySelectorAll('button:not(.icon)')].map((b) => b.textContent.trim()),
        menu: !!r.querySelector('button.icon'),
        heights: [...r.querySelectorAll('button')]
          .map((b) => Math.round(b.getBoundingClientRect().height)),
        right: Math.round(r.getBoundingClientRect().right),
      })),
      input: (() => {
        const i = document.getElementById('todoText');
        const b = document.querySelector('#todoAdd button');
        return { placeholder: i.placeholder, font: parseFloat(getComputedStyle(i).fontSize),
                 w: Math.round(i.getBoundingClientRect().width),
                 h: Math.round(i.getBoundingClientRect().height),
                 btnH: Math.round(b.getBoundingClientRect().height), btn: b.textContent.trim() };
      })(),
      wide: document.documentElement.scrollWidth > innerWidth + 1,
    };
  });
  if (m.head !== 'To Do') note(where, `the section is headed "${m.head}"`);
  if (m.chips) note(where, `To Do carries ${m.chips} filter chips`);
  if (m.badge) note(where, 'To Do grew a badge of its own');
  const open = TODO.items.filter((i) => !(i.snoozed_until > Date.now() / 1000));
  if (m.rows.length !== open.length) note(where, `${m.rows.length} rows for ${open.length} open items`);
  if (m.rows.some((r) => /snoozed chore/i.test(r.title))) note(where, 'a snoozed item is shown');
  for (const r of m.rows) {
    if (r.presses.join('|') !== 'Done|Delete') note(where, `row ${r.id} offers ${r.presses.join(' · ')}`);
    if (!r.menu) note(where, `row ${r.id} has no ⋯`);
    if (!r.meta) note(where, `row ${r.id} does not say where it came from`);
    if (touch && r.heights.some((h) => h < MIN_TARGET)) {
      note(where, `row ${r.id} has a press under ${MIN_TARGET}px (${r.heights.join(',')})`);
    }
    if (r.right > width + 1) note(where, `row ${r.id} overflows`);
  }
  const fromFinding = m.rows.find((r) => r.id === '2');
  // Named by the server's one wording (`source_name`), never the id the
  // row was filed under: its stored title is an asked card's id.
  if (fromFinding && (!/A question you asked/.test(fromFinding.meta)
                      || /custom-|check:|user-\d/.test(fromFinding.meta))) {
    note(where, `a moved finding reads "${fromFinding.meta}"`);
  }
  if (m.input.placeholder !== 'Add to To Do…') note(where, `add box says "${m.input.placeholder}"`);
  if (touch && m.input.font < 16) note(where, `add box is ${m.input.font}px on touch`);
  if (m.input.w < 160) note(where, `add box squeezed to ${m.input.w}px`);
  if (m.input.btn !== 'Add to To Do') note(where, `add press reads "${m.input.btn}"`);
  if (touch && (m.input.btnH < MIN_TARGET || m.input.h < MIN_TARGET)) {
    note(where, `add box ${m.input.h}px / press ${m.input.btnH}px on touch`);
  }
  if (m.wide) note(where, 'the page scrolls sideways');

  // The ⋯ holds Snooze and Ignore, and each sends its own route. Pressed
  // in the page rather than through Playwright's click, whose scroll into
  // view is a scroll — and a scroll closes a popover.
  const openMenu = async (id) => {
    await page.evaluate((i) => document.querySelector(
      `#todoList .todorow[data-todo-id="${i}"]`).scrollIntoView({ block: 'center' }), id);
    await page.waitForTimeout(150);
    await page.evaluate((i) => document.querySelector(
      `#todoList .todorow[data-todo-id="${i}"] button.icon`).click(), id);
    return page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
      .map((b) => b.textContent));
  };
  const pick = (label) => page.evaluate((l) => [...document.querySelectorAll(
    '#chipPop .cardmenuitem')].find((b) => b.querySelector('b')?.textContent === l)?.click(), label);
  const menu = await openMenu('2');
  if (menu.join('|') !== 'Snooze|Ignore') note(where, `the row's ⋯ holds ${menu.join(' | ')}`);
  await pick('Snooze');
  await page.waitForTimeout(150);
  await openMenu('1');
  await pick('Ignore');
  await page.waitForTimeout(150);

  // Done asks what was done, and sends it.
  await page.locator('#todoList .todorow[data-todo-id="1"] button:text-is("Done")').click();
  const form = page.locator('#todoList .todorow[data-todo-id="1"] .findnote');
  const hint = await form.locator('.findnotehint').textContent();
  if (!/What did you do\?/.test(hint || '')) note(where, `Done asks "${hint}"`);
  await form.locator('textarea').fill('Swapped the CR2032.');
  await form.locator('.findnoteactions button', { hasText: 'Done' }).click();
  await page.waitForTimeout(150);

  // Delete takes it off the list, and says nothing goes into memory.
  await page.locator('#todoList .todorow[data-todo-id="2"] button:text-is("Delete")').click();
  await page.waitForTimeout(150);

  // The add box sends what was typed.
  await page.fill('#todoText', 'Descale the kettle');
  await page.click('#todoAdd button');
  await page.waitForTimeout(150);

  const sent = (await posts(page)).map((p) => `${p.url.replace(/^.*?(api\/)/, '$1')} ${JSON.stringify(p.body)}`);
  const want = [
    /^api\/case\/t:2\/not_now /,
    /^api\/todo\/1\/ignore /,
    /^api\/todo\/1\/done \{"note":"Swapped the CR2032\."\}$/,
    /^api\/todo \{"text":"Descale the kettle"\}$/,
    /^api\/todo\/2 null$/,
  ];
  for (const re of want) {
    if (!sent.some((s) => re.test(s))) note(where, `no press matched ${re} in ${JSON.stringify(sent)}`);
  }
  await context.close();

  // An empty list is one line.
  const empty = await openToday(browser, PANEL, { width, touch,
    over: { todo: { items: [], done: [], open: 0, done_count: 0 } } });
  const lines = await empty.page.evaluate(() =>
    [...document.querySelectorAll('#todoList > *')].map((e) => e.textContent));
  if (lines.join('|') !== 'Nothing to do.') note(where, `an empty list reads ${JSON.stringify(lines)}`);
  await empty.context.close();
  console.log(`${failures.length ? 'FAIL' : 'ok  '} ${where}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-todo: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-todo: every row can be finished from Today, and the add box takes a thumb');
