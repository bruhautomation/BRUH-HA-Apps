// Render the To-do tab against a real list and assert every row can be acted
// on — because the failure this exists to prevent is a silent one.
//
// A chore you cannot finish from the screen it is on is indistinguishable
// from a chore nobody has got round to, and a list whose Done button sits
// under the touch floor is one people stop using on the device they read it
// on. So the checks are about what a row OFFERS as much as where it sits:
//
//   * every open row carries both verbs — Done, and taking it off the list —
//     and a finished one carries exactly one, which is putting it back.
//   * a finished row says it is finished IN WORDS. The strike-through and
//     the fade are reinforcement; status by colour alone is what the design
//     system forbids, and this row is read at a glance.
//   * a moved finding says where it came from, because that is the half that
//     decides what taking it off the list does — a finding's key is released
//     and a hand-added one has none.
//   * the "Done" filter is absent until something is in it, so a fresh list
//     is one chip rather than a row of empty ones.
//   * the add form is reachable and not squeezed to a sliver at 390px.
//   * nothing is under the touch floor ON TOUCH, and nothing scrolls
//     sideways. The floor is a `@media (pointer: coarse)` rule, so the
//     phone widths here run in a context that reports a coarse pointer and
//     the desktop ones do not — measuring 40px against a mouse render is
//     measuring a rule that was never meant to apply.
//
// It drives the panel's REAL renderer behind a stubbed fetch, the rule
// measure-activity and measure-lightmap follow: a copy of renderTodo in this
// file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

// A width and whether the device reading it has a coarse pointer, because
// the touch floor is a `@media (pointer: coarse)` rule and a context that
// reports a mouse does not match it. Asserting 40px against a desktop
// render measures the wrong thing and fails on every button — which is what
// the first run of this file did, at four widths, twice each.
const CASES = [
  { width: 390, touch: true },
  { width: 430, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];
// A thumb. The panel's touch floor is scoped per control rather than
// raised globally, so this applies to what this tab adds — its add form —
// and not to the card row it shares with the Findings tab.
const MIN_TARGET = 44;

const NOW = Math.floor(Date.now() / 1000);
const ITEMS = [
  { id: 1, text: 'Hall sensor has not reported since 3 Sep',
    detail: 'last seen 3 Sep', fix: 'Re-pair it',
    entity_id: 'binary_sensor.hall', severity: 'serious', origin: 'finding',
    source: 'check:devices', source_title: 'Device checks',
    finding_key: 'hall sensor', run_id: '', status: 'open',
    added_at: NOW - 86400 * 2, done_at: 0, note: '' },
  { id: 2, text: 'Replace the hallway smoke alarm battery', detail: '',
    fix: '', entity_id: '', severity: 'warning', origin: 'hand',
    source: '', source_title: '', finding_key: '', run_id: '',
    status: 'open', added_at: NOW - 3600, done_at: 0, note: '' },
];
const DONE = [
  { id: 3, text: 'Re-pair the bedroom blind', detail: '', fix: '',
    entity_id: '', severity: 'info', origin: 'hand', source: '',
    source_title: '', finding_key: '', run_id: '', status: 'done',
    added_at: NOW - 86400 * 3, done_at: NOW - 7200,
    note: 'held the button for ten seconds' },
];

const STUB = `
window.__todo = {
  items: ${JSON.stringify(ITEMS)}, done: ${JSON.stringify(DONE)},
  open: ${ITEMS.length}, done_count: ${DONE.length},
};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/todo')) return answer(window.__todo);
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

const read = (page) => page.evaluate(() => {
  const rows = [...document.querySelectorAll('#todoList .finding')];
  const form = document.getElementById('todoAdd').getBoundingClientRect();
  const input = document.getElementById('todoText').getBoundingClientRect();
  return {
    rows: rows.map((r) => {
      const box = r.getBoundingClientRect();
      return {
        title: (r.querySelector('.findtitle') || {}).textContent || '',
        state: [...r.querySelectorAll('.findstate')]
          .map((s) => s.textContent.trim()).join(' '),
        words: r.textContent,
        verbs: [...r.querySelectorAll('.findactions button')].map((b) => ({
          label: b.textContent.trim(),
          w: Math.round(b.getBoundingClientRect().width),
          h: Math.round(b.getBoundingClientRect().height),
        })),
        struck: !!r.className.match(/\bst-done\b/),
        right: box.right,
      };
    }),
    chips: [...document.querySelectorAll('#todoFilters .fchip')]
      .map((b) => ({ label: b.textContent.trim(),
                     h: Math.round(b.getBoundingClientRect().height) })),
    badge: (document.getElementById('todoBadge') || {}).textContent || '',
    formRows: new Set([...document.querySelectorAll('#todoAdd > *')]
      .map((e) => Math.round(e.getBoundingClientRect().top))).size,
    inputWidth: Math.round(input.width),
    inputHeight: Math.round(input.height),
    inputFont: parseFloat(getComputedStyle(
      document.getElementById('todoText')).fontSize),
    addHeight: Math.round(document.querySelector('#todoAdd button')
      .getBoundingClientRect().height),
    formWidth: Math.round(form.width),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
});

for (const { width, touch } of CASES) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(`${width}px`, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="todo"]');
  await page.waitForSelector('#todoList .finding');

  const open = await read(page);

  if (open.rows.length !== ITEMS.length) {
    note(`${width}px`, `${open.rows.length} rows for ${ITEMS.length} items`);
  }
  // The badge counts accepted work, which is a different number from the
  // Findings badge: moving a card across moves the count with it, and that
  // is the whole point of the move.
  if (open.badge !== String(ITEMS.length)) {
    note(`${width}px`, `badge reads "${open.badge}", not ${ITEMS.length}`);
  }
  for (const row of open.rows) {
    if (!row.title.trim()) note(`${width}px`, 'a row renders no title');
    if (!row.state) note(`${width}px`, `"${row.title}" does not say where it came from`);
    const labels = row.verbs.map((v) => v.label).join(' | ');
    if (!/Done/.test(labels)) {
      note(`${width}px`, `"${row.title}" offers no way to finish it (${labels})`);
    }
    if (!/Off the list/.test(labels)) {
      note(`${width}px`, `"${row.title}" offers no way off the list (${labels})`);
    }
    if (row.struck) note(`${width}px`, `"${row.title}" is open and reads as done`);
    // Deliberately NOT a touch-floor assertion on these. They are the
    // Findings tab's own `.findactions .btn` row, whose height the panel's
    // touch floor does not raise — that block is scoped per control and
    // says in as many words that the rest of the panel's card buttons are
    // a separate, real problem. A floor asserted here and nowhere else
    // would be one tab holding a rule its sibling does not, which is the
    // inconsistency rather than the fix.
    if (row.verbs.length < 2) {
      note(`${width}px`, `"${row.title}" offers ${row.verbs.length} verb(s)`);
    }
  }
  // A moved finding and a hand-added chore do different things when taken
  // off the list, so the row has to say which it is.
  const froms = open.rows.map((r) => r.state);
  if (!froms.some((s) => /finding/i.test(s))) {
    note(`${width}px`, 'no row says it came from a finding');
  }
  if (!froms.some((s) => /you/i.test(s))) {
    note(`${width}px`, 'no row says it was added by hand');
  }

  // The chips are `.fchip`, shared with the Findings tab — same argument.
  if (!open.chips.some((c) => /^To do/.test(c.label))) {
    note(`${width}px`, `no "To do" chip (${open.chips.map((c) => c.label)})`);
  }

  // The add form is the whole of "add one yourself", so it has to be usable
  // at the width people read this on: one row, and a box wide enough to
  // type a sentence into rather than a sliver beside a button.
  if (open.formRows !== 1) {
    note(`${width}px`, `the add form wraps to ${open.formRows} rows`);
  }
  if (open.inputWidth < 160) {
    note(`${width}px`, `the add box is ${open.inputWidth}px wide`);
  }
  // The two floors this tab's own control does carry: a thumb-sized target,
  // scoped in the stylesheet the way `.propask`'s is, and 16px of text —
  // under that iOS zooms the ingress iframe in on focus and never back out.
  if (touch) {
    if (open.inputHeight < MIN_TARGET) {
      note(`${width}px`, `the add box is ${open.inputHeight}px tall on touch`);
    }
    if (open.addHeight < MIN_TARGET) {
      note(`${width}px`, `Add is ${open.addHeight}px tall on touch`);
    }
    if (open.inputFont < 16) {
      note(`${width}px`, `the add box is ${open.inputFont}px text on touch`);
    }
  }
  if (open.docWidth > open.viewport + 1) {
    note(`${width}px`, `page scrolls sideways (${open.docWidth} > ${open.viewport})`);
  }

  // Now the Done filter, which must exist here and must not have existed
  // on a list with nothing finished.
  const doneChip = open.chips.find((c) => /^Done/.test(c.label));
  if (!doneChip) {
    note(`${width}px`, 'no "Done" chip with a finished chore on the list');
  } else {
    await page.click('#todoFilters .fchip:nth-child(2)');
    await page.waitForSelector('#todoList .finding.st-done');
    const finished = await read(page);
    for (const row of finished.rows) {
      if (!/done /i.test(row.words)) {
        note(`${width}px`, `"${row.title}" is finished and does not say so in words`);
      }
      if (!row.struck) note(`${width}px`, `"${row.title}" is not marked finished`);
      const labels = row.verbs.map((v) => v.label).join(' | ');
      if (row.verbs.length !== 1 || !/Put it back/.test(labels)) {
        note(`${width}px`,
             `a finished row carries ${row.verbs.length} verb(s): ${labels}`);
      }

    }
  }

  // ...and an empty list says what to do rather than nothing at all.
  //
  // `state` and the render functions are top-level bindings in a classic
  // script, so `const state` is a global NAME and not a property of
  // `window` — reaching for `window.state` gets undefined, which is what
  // the first run of this file did. Bare names it is.
  //
  // And every probe notes rather than throws: measure-cardlive's own first
  // run abandoned nineteen findings it had already gathered because one
  // helper was missing, and reported the missing helper.
  let empty = null;
  try {
    await page.evaluate(() => {
      window.__todo = { items: [], done: [], open: 0, done_count: 0 };
    });
    empty = await page.evaluate(async () => {
      await refreshTodo();               // eslint-disable-line no-undef
      state.todoFilter = 'open';         // eslint-disable-line no-undef
      renderTodo();                      // eslint-disable-line no-undef
      return {
        text: document.querySelector('#todoList .findempty')?.textContent || '',
        chips: [...document.querySelectorAll('#todoFilters .fchip')]
          .map((b) => b.textContent.trim()),
        badge: document.getElementById('todoBadge').textContent,
        hidden: document.getElementById('todoBadge').classList.contains('hidden'),
      };
    });
  } catch (error) {
    note(`${width}px`, `could not empty the list: ${error.message}`);
  }
  if (empty) {
    if (!empty.text.trim()) note(`${width}px`, 'an empty list renders nothing');
    if (empty.chips.length !== 1) {
      note(`${width}px`,
           `an empty list offers ${empty.chips.length} chips: ${empty.chips}`);
    }
    if (!empty.hidden || empty.badge) {
      note(`${width}px`,
           `the badge stays at "${empty.badge}" with nothing on the list`);
    }
  }

  console.log(`${String(width).padStart(5)}  ${open.rows.length} rows  `
    + `badge ${open.badge}  chips ${open.chips.length}  `
    + `add box ${open.inputWidth}px of ${open.formWidth}px`);
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`\n${failures.length} failure(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('\nevery row can be finished or dropped, every finished one says so '
  + 'in words, the add form fits, and nothing is under the touch floor');
