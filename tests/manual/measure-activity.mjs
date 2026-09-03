// Render the Activity tab against a real day of a house and assert every row
// answers the question the tab exists to answer.
//
// The failure this exists to prevent is not a layout bug, it is a silent one:
// a row whose cause is missing looks exactly like a row whose cause is
// "nobody knows", and both look exactly like a working tab. So the checks
// are about what a row SAYS as much as where it sits:
//
//   * every row names a cause — the automation's name, the person's name, or
//     "no cause recorded" in as many words. A blank is a bug.
//   * the cause survives a phone width. It moves to its own line there; it
//     does not get deleted, because the name of the automation that did
//     something is the whole row.
//   * tapping a row opens that entity's own history, and closes it again.
//   * the overrides block is present when there are overrides and absent
//     when there are none — it is evidence, and evidence you always show is
//     evidence nobody reads.
//   * no row is under the touch floor, and nothing scrolls sideways.
//
// Like measure-lightmap.mjs and unlike the older brAIn measures, this drives
// the panel's REAL renderer behind a stubbed fetch. A copy of renderActivity
// in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 44;

// A day with one of everything, including the two cases that are easy to get
// wrong: an automation a person started by hand (both causes are true and
// only one is proximate), and a change nothing claims.
const NOW = Math.floor(Date.now() / 1000);
const ACTIONS = [
  { ts: NOW - 300, entity_id: 'light.kitchen', name: 'Kitchen', state: 'off',
    cause: 'person', by: 'u1', by_name: 'Ben', root_user: 'u1',
    root_user_name: 'Ben' },
  { ts: NOW - 360, entity_id: 'light.kitchen', name: 'Kitchen', state: 'on',
    cause: 'automation', by: 'automation.evening',
    by_name: 'Evening lights when it gets dark', root_user: '',
    root_user_name: '' },
  { ts: NOW - 900, entity_id: 'climate.hall', name: 'Hall thermostat',
    state: 'heat', cause: 'brain', by: '', by_name: 'brAIn',
    root_user: '', root_user_name: '' },
  { ts: NOW - 1800, entity_id: 'switch.kettle', name: 'Kettle', state: 'on',
    cause: 'voice', by: '', by_name: 'Assist', root_user: '',
    root_user_name: '' },
  { ts: NOW - 5400, entity_id: 'cover.garage', name: 'Garage door',
    state: 'open', cause: 'script', by: 'script.leaving', by_name: 'Leaving',
    root_user: 'u1', root_user_name: 'Ben' },
  { ts: NOW - 9000, entity_id: 'binary_sensor.back_door', name: 'Back door',
    state: 'on', cause: 'unattributed', by: '', by_name: '', root_user: '',
    root_user_name: '' },
];
const OVERRIDES = [
  { ts: NOW - 300, entity_id: 'light.kitchen', name: 'Kitchen',
    from_state: 'on', to_state: 'off', by: 'automation.evening',
    by_name: 'Evening lights when it gets dark', by_cause: 'automation',
    person: 'Ben', after_s: 60 },
];
const COUNTS = { brain: 1, automation: 1, script: 1, scene: 0, voice: 1,
                 person: 1, unattributed: 1 };

const STUB = `
window.__activity = {
  available: true, error: '', start: ${NOW - 86400}, end: ${NOW},
  actions: ${JSON.stringify(ACTIONS)},
  overrides: ${JSON.stringify(OVERRIDES)},
  counts: ${JSON.stringify(COUNTS)},
  total: ${ACTIONS.length}, capped: false,
};
window.__empty = false;
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/activity/entity/')) {
    const id = decodeURIComponent(p.split('api/activity/entity/')[1].split('?')[0]);
    // Deliberately slow. A row's history is a real round trip, so the pane
    // opens on 'Reading…' and fills afterwards — and an instant stub hides
    // that, which is how the first version of this file asserted on the
    // interim state and passed locally while failing in CI.
    await new Promise((r) => setTimeout(r, 150));
    return answer({ available: true, error: '', entity_id: id,
                    changes: window.__activity.actions.filter(
                      (a) => a.entity_id === id) });
  }
  if (p.includes('api/activity')) {
    if (window.__empty) {
      return answer({ available: true, error: '', actions: [], overrides: [],
                      counts: {}, total: 0, capped: false });
    }
    return answer(window.__activity);
  }
  // The shape the panel actually READS, not a plausible-looking one.
  // /api/status is dereferenced unguarded in several places (the auth
  // chip's auth_check.state, the grid's categories and jobs), so a stub
  // that omits a key throws a page error seconds later — which this file
  // fails on, and which has nothing to do with the tab under test. Same
  // lesson as BRight's demo panel seeding a registry shape nothing read.
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

for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(`${width}px`, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="activity"]');
  await page.waitForSelector('.actrow');

  const m = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.actrow')];
    const wrap = document.querySelector('.actwrap').getBoundingClientRect();
    return {
      rows: rows.map((r) => {
        const box = r.getBoundingClientRect();
        const cause = r.querySelector('.cause');
        const cs = cause && getComputedStyle(cause);
        return {
          entity: r.dataset.entity,
          kind: r.dataset.cause,
          causeText: cause ? cause.textContent.trim() : '',
          causeShown: !!(cs && cs.display !== 'none' && cs.visibility !== 'hidden'),
          w: Math.round(box.width), h: Math.round(box.height),
          right: box.right,
        };
      }),
      hours: document.querySelectorAll('.acthour').length,
      overrides: !document.getElementById('actOverrides').hidden,
      overrideText: document.getElementById('actOverrides').textContent,
      filters: [...document.querySelectorAll('#actFilters .fchip')]
        .map((b) => b.textContent.trim()),
      wrapRight: wrap.right,
      docWidth: document.documentElement.scrollWidth,
    };
  });

  if (m.rows.length !== ACTIONS.length) {
    note(`${width}px`, `${m.rows.length} rows for ${ACTIONS.length} actions`);
  }
  for (const row of m.rows) {
    if (!row.causeText) note(`${width}px`, `${row.entity} renders no cause`);
    if (!row.causeShown) {
      note(`${width}px`, `${row.entity}'s cause is hidden rather than moved`);
    }
    if (row.h < MIN_TARGET) {
      note(`${width}px`, `row ${row.entity} is ${row.h}px, under ${MIN_TARGET}`);
    }
    if (row.right > m.wrapRight + 0.5) {
      note(`${width}px`, `row ${row.entity} overflows the list`);
    }
  }
  // The unattributed row has to say so in words. A dot with no text beside
  // it is the row a person reads as "brAIn does not know how to show this".
  const orphan = m.rows.find((r) => r.kind === 'unattributed');
  if (orphan && !/no cause/i.test(orphan.causeText)) {
    note(`${width}px`, `unattributed row says "${orphan.causeText}"`);
  }
  // An automation somebody started by hand carries both halves.
  const script = m.rows.find((r) => r.kind === 'script');
  if (script && !/started by Ben/i.test(script.causeText)) {
    note(`${width}px`, `script row lost its root user: "${script.causeText}"`);
  }
  if (!m.overrides) note(`${width}px`, 'overrides block hidden with an override');
  if (!/Evening lights/.test(m.overrideText)) {
    note(`${width}px`, 'overrides block does not name the automation');
  }
  if (!m.filters.length) note(`${width}px`, 'no cause filters rendered');
  // A filter for a cause the window does not hold can only empty the list.
  if (m.filters.some((f) => /^Scene/.test(f))) {
    note(`${width}px`, 'a filter is offered for a cause with no rows');
  }
  if (m.docWidth > width + 0.5) {
    note(`${width}px`, `page scrolls sideways (${m.docWidth}px)`);
  }

  // Tapping a row opens that entity's history, and tapping it again closes it.
  await page.locator('.actrow').first().click();
  await page.waitForSelector('.actwhy');
  // The pane appears on 'Reading…' and fills when the fetch lands, so
  // settling is what is being waited for. Waiting on the element alone
  // measures whichever the race happened to reach first.
  let settled = true;
  try {
    await page.waitForFunction(() => {
      const el = document.querySelector('.actwhy');
      return el && !/Reading/.test(el.textContent);
    }, null, { timeout: 5000 });
  } catch {
    settled = false;
    note(`${width}px`, 'history pane never stopped saying "Reading…"');
  }
  const why = await page.evaluate(() => {
    const el = document.querySelector('.actwhy');
    return { text: el.textContent, count: document.querySelectorAll('.actwhy').length };
  });
  if (why.count !== 1) note(`${width}px`, `${why.count} history panes open at once`);
  if (settled && !/light\.kitchen/.test(why.text)) {
    note(`${width}px`, 'history pane does not name the entity');
  }
  await page.locator('.actrow').first().click();
  await page.waitForTimeout(80);
  if (await page.locator('.actwhy').count()) {
    note(`${width}px`, 'a second tap did not close the history pane');
  }

  console.log(`${failures.length ? 'ok? ' : 'ok  '}${String(width).padStart(4)}px  `
    + `${m.rows.length} rows, ${m.hours} hour headings, `
    + `${m.filters.length} filters, overrides ${m.overrides ? 'shown' : 'hidden'}`);
  await context.close();
}

// A quiet window says nothing rather than showing an empty evidence block.
{
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note('empty', `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.addInitScript('window.__empty = true;');
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="activity"]');
  await page.waitForSelector('.actempty');
  const shown = await page.evaluate(
    () => !document.getElementById('actOverrides').hidden);
  if (shown) note('empty', 'overrides block shown on a window with none');
  console.log('ok  empty window: one sentence, no evidence block');
  await context.close();
}

await browser.close();
for (const f of failures) console.log(`  - ${f}`);
console.log(failures.length ? `\n${failures.length} problem(s)` : '\nall widths ok');
process.exit(failures.length ? 1 : 0);
