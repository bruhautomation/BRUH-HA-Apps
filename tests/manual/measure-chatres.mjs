// Render the resolutions card against a real finding and assert every option
// says what pressing it will do — because the failure this exists to prevent
// is a person pressing a sentence and getting a different ending.
//
// Claude offers the ways a finding could end as buttons inside the
// conversation about it. The label is both the button and what gets
// recorded, so what the card must never do is put a label on screen without
// the consequence beside it: "Replace the CR2032" and "Replaced the CR2032"
// are one letter apart and land in different places — a chore on a list, and
// a line in memory claiming work that has not happened.
//
// So the checks are about what a row OFFERS as much as where it sits:
//
//   * every option renders its own label AND a line saying where the press
//     lands. Three verbs, three different consequences, none of them
//     guessable from the label alone.
//   * the press target is the whole row, so the consequence is inside the
//     thing you press rather than beside it — the question card's own shape,
//     and the reason it has that shape.
//   * a card whose finding has been settled already offers NOTHING and says
//     so in words. The transcript replays this card after a reload, and by
//     then the finding may have been ended on the Findings tab or from a
//     phone; buttons that would settle something already gone is the one
//     thing it must not show.
//   * a card in a conversation that is not about a finding says that too,
//     rather than rendering buttons that settle nothing.
//   * nothing is under the touch floor ON TOUCH, and nothing scrolls
//     sideways at 390px.
//
// It drives the panel's REAL `chatResolutionsNode`, the rule measure-activity
// and measure-todo follow: a copy of it in this file would only ever agree
// with itself — and this card is model-authored content in a person's
// decision path, which is the last place to measure a reimplementation.
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
// A thumb. Scoped in the stylesheet to this card rather than raised
// globally, the way `.propask`'s is: a press here settles a finding.
const MIN_TARGET = 44;

const FINDING_TS = 1720000000;
const OPTIONS = [
  { label: 'Replaced the CR2032', verb: 'done' },
  { label: 'Replace the CR2032 in the garage sensor', verb: 'todo' },
  { label: 'That cupboard is never opened', verb: 'wrong' },
];

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
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
  if (p.includes('api/todo')) {
    return answer({ items: [], done: [], open: 0, done_count: 0 });
  }
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

// One card, drawn by the panel's own renderer into the chat log it lives in,
// and measured. `finding` is whether the list holds the finding it is about.
const draw = (page, { ts, options, finding }) => page.evaluate(
  ({ ts, options, finding, FINDING_TS }) => {
    // Bare names, not window.*: these are top-level `const`s in a classic
    // script, which are not properties of window — the mistake this file's
    // sibling made on its first run.
    state.findings = finding
      ? [{ ts: FINDING_TS, text: 'Garage door sensor battery is at 5%',
           detail: 'since 3 Sep', fix: 'Replace it', severity: 'warning',
           status: 'open', entity_id: 'sensor.garage_battery',
           source: 'check:forecasts', source_title: 'Forecasts', note: '',
           fixable: true }]
      : [];
    chatState.chosen = {};
    const log = document.getElementById('chatLog');
    log.textContent = '';
    log.appendChild(chatResolutionsNode(
      { type: 'resolutions', id: 'toolu_res', finding_ts: ts, options }));
    const card = log.querySelector('.chatres');
    const box = card.getBoundingClientRect();
    return {
      head: (card.querySelector('.creshead') || {}).textContent || '',
      note: (card.querySelector('.cresnote') || {}).textContent || '',
      rows: [...card.querySelectorAll('.cresopt')].map((b) => {
        const r = b.getBoundingClientRect();
        return {
          label: (b.querySelector('.creslabel') || {}).textContent || '',
          does: (b.querySelector('.cresdoes') || {}).textContent || '',
          tag: b.tagName,
          h: Math.round(r.height),
          w: Math.round(r.width),
          right: Math.round(r.right),
        };
      }),
      cardRight: Math.round(box.right),
      docWidth: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
    };
  }, { ts, options, finding, FINDING_TS });

for (const { width, touch } of CASES) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(`${width}px`, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="terminal"]');
  // Attached, not visible: `.chatlog:empty` is `display: none`, so the log
  // does not exist to look at until something is in it — which is what the
  // draw below puts there.
  await page.waitForSelector('#chatLog', { state: 'attached' });

  const live = await draw(page, { ts: FINDING_TS, options: OPTIONS, finding: true });

  if (live.rows.length !== OPTIONS.length) {
    note(`${width}px`, `${live.rows.length} rows for ${OPTIONS.length} options`);
  }
  if (!live.head.trim()) note(`${width}px`, 'the card has no heading');
  for (const row of live.rows) {
    if (!row.label.trim()) note(`${width}px`, 'an option renders no label');
    // The half that cannot be left to the label. Without it "Replace the
    // CR2032" and "Replaced the CR2032" are the same button.
    if (!row.does.trim()) {
      note(`${width}px`, `"${row.label}" does not say what pressing it does`);
    }
    // One press target per option, with the consequence inside it.
    if (row.tag !== 'BUTTON') {
      note(`${width}px`, `"${row.label}" is a ${row.tag}, not a button`);
    }
    if (touch && row.h < MIN_TARGET) {
      note(`${width}px`, `"${row.label}" is ${row.h}px tall on touch`);
    }
    if (row.right > live.viewport) {
      note(`${width}px`, `"${row.label}" runs ${row.right - live.viewport}px off the side`);
    }
  }
  // Three verbs, three different sentences: a card that said the same thing
  // three times would be a card that has stopped distinguishing them.
  const said = new Set(live.rows.map((r) => r.does.trim()));
  if (said.size !== live.rows.length) {
    note(`${width}px`, `${live.rows.length} options share ${said.size} consequence(s)`);
  }
  if (live.docWidth > live.viewport) {
    note(`${width}px`, `the page scrolls sideways (${live.docWidth} > ${live.viewport})`);
  }

  // Settled already: the replayed card, after the finding has gone.
  const gone = await draw(page, { ts: FINDING_TS, options: OPTIONS, finding: false });
  if (gone.rows.length) {
    note(`${width}px`, `${gone.rows.length} buttons offered for a settled finding`);
  }
  if (!/settled/i.test(gone.note)) {
    note(`${width}px`, `a settled card says "${gone.note || '(nothing)'}"`);
  }

  // And a conversation that is not about a finding at all.
  const loose = await draw(page, { ts: 0, options: OPTIONS, finding: true });
  if (loose.rows.length) {
    note(`${width}px`, `${loose.rows.length} buttons offered with no finding`);
  }
  if (!/finding/i.test(loose.note)) {
    note(`${width}px`, `a subjectless card says "${loose.note || '(nothing)'}"`);
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-chatres: FAILED');
  for (const line of failures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(`measure-chatres: ok (${CASES.length} widths)`);
