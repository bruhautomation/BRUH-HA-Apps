// Render the Activity tab against a real day of a house and assert it says
// what HAPPENED rather than every time a value changed.
//
// The failure this exists to prevent used to be a silent one — a row whose
// cause is missing looks exactly like a row whose cause is "nobody knows" —
// and 1.56 added a louder one: a tab that groups and sorts can lose the
// thing it was grouping, and a section heading with the wrong rows under it
// is worse than the flat list it replaced. So the checks are about what a
// row and a section SAY:
//
//   * a door, a motion sensor, a person and a media player land in four
//     different sections. That is the whole restructure, and the one that
//     matters is the door: `binary_sensor` with no device class is a door,
//     a motion sensor or a leak detector, so the tab must be reading the
//     class rather than guessing from a name.
//   * a run is ONE row. A media player paused for an ad break and switched
//     off three hours later is one episode of three hours, not three rows —
//     and a motion sensor tripping nine times is one row that says nine.
//   * sensor readings are not rows at ALL, and the tab says how many it
//     left out. A list that silently drops nine tenths of its input is the
//     thing this replaced.
//   * every row something caused names it — the automation's name, the
//     person's — and it survives a phone width rather than being deleted.
//     A row nothing caused says nothing; the foot says so ONCE.
//   * Home Assistant restarting is a row, a reload's burst is one row
//     naming the integration, and a row the logbook lost track of agrees
//     with the house now.
//   * the window is called what it is — "Last 24 hours", never "Today".
//   * a row a person undid says so on the row, in words.
//   * "nobody home" is shown when it is known and absent when it is not.
//   * the top line is what the house is doing now (the situation reading),
//     and the tab's intro and each group's blurb stay cut (House ›
//     What happened): a group is its name.
//   * the cause filter is ONE "Caused by" select with no counts, never a
//     row of counted chips — the row that scrolled sideways on a phone.
//   * the paragraph is a PRESS and says it costs something; it is never
//     fetched on arrival.
//   * tapping a row opens that entity's own history, and closes it again.
//   * no row is under the touch floor, and nothing scrolls sideways.
//
// It drives the panel's REAL renderer behind a stubbed fetch — a copy of
// renderActivity in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 44;

const NOW = Math.floor(Date.now() / 1000);

// The payload the SERVER builds — `episodes.sections`' own shape, so this
// measures the renderer against what it is really handed. The grouping
// itself is arithmetic and is driven directly in tests/test_episodes.py;
// what cannot be asserted there is whether a person can read the result.
const ep = (over) => ({
  subject: '', entity_id: '', name: '', started: NOW - 3600, ended: NOW - 3600,
  count: 1, first: 'on', last: 'on', duration_s: 0, open: false,
  states: [], causes: {}, cause: 'unattributed', by_name: '', ...over,
});

const SECTIONS = [
  // Home Assistant restarting, and an integration moving all its devices
  // at once — one row each, not a page of them.
  { id: 'system', label: 'Home Assistant', reads: 'span', total: 2,
    changes: 48, blurb: 'Home Assistant itself stopping and starting.',
    episodes: [
      ep({ subject: 'system', kind: 'restart', entity_id: '',
           name: 'Home Assistant restarted', first: 'stopped',
           last: 'started', count: 2, started: NOW - 11000,
           ended: NOW - 10910, duration_s: 90 }),
      ep({ subject: 'system', kind: 'mass', entity_id: '',
           name: '23 devices from UniFi', first: 'unavailable', last: 'home',
           count: 46, devices: 23, integration: 'UniFi',
           entities: ['device_tracker.office_ap', 'device_tracker.gateway'],
           started: NOW - 4000, ended: NOW - 3988, duration_s: 12 }),
    ] },
  // The thermostat the logbook lost track of: its old episode closed at
  // the live last_changed, and the live state as a row of its own.
  { id: 'climate', label: 'Heating & cooling', reads: 'span', total: 2,
    changes: 1, blurb: 'What each room was asked to be.',
    episodes: [
      ep({ subject: 'climate', entity_id: 'climate.downstairs',
           name: 'Downstairs', first: 'unavailable', last: 'unavailable',
           count: 0, open: true, from_live: true, near_restart: NOW - 10910,
           started: NOW - 10850, ended: NOW - 10850, duration_s: 10850 }),
      ep({ subject: 'climate', entity_id: 'climate.downstairs',
           name: 'Downstairs', first: 'heat_cool', last: 'heat_cool',
           live: 'unavailable', started: NOW - 60000, ended: NOW - 10850,
           duration_s: 49150 }),
    ] },
  { id: 'people', label: 'People', reads: 'moment', total: 1, changes: 1,
    blurb: 'Who came and went.',
    episodes: [ep({ subject: 'people', entity_id: 'person.ben', name: 'Ben',
                    first: 'home', last: 'home', open: true,
                    started: NOW - 1800, ended: NOW - 1800,
                    duration_s: 1800, cause: 'unattributed' })] },
  { id: 'openings', label: 'Doors, windows & blinds', reads: 'span',
    total: 1, changes: 2, blurb: 'What was opened, and for how long.',
    episodes: [ep({ subject: 'openings', entity_id: 'binary_sensor.back_door',
                    name: 'Back door', first: 'on', last: 'off', count: 2,
                    started: NOW - 9000, ended: NOW - 8940, duration_s: 60,
                    cause: 'unattributed' })] },
  { id: 'media', label: 'Media', reads: 'span', total: 1, changes: 4,
    blurb: 'What played, where, and for how long.',
    episodes: [ep({ subject: 'media', entity_id: 'media_player.lounge',
                    name: 'Lounge TV', first: 'playing', last: 'off',
                    count: 4, started: NOW - 14400, ended: NOW - 3600,
                    duration_s: 10800, cause: 'person', by_name: 'Ben' })] },
  { id: 'motion', label: 'Cameras & motion', reads: 'count', total: 1,
    changes: 9, blurb: 'Counted rather than listed.',
    episodes: [ep({ subject: 'motion', entity_id: 'binary_sensor.hall_motion',
                    name: 'Hall motion', first: 'on', last: 'off', count: 9,
                    started: NOW - 7200, ended: NOW - 6700, duration_s: 500,
                    cause: 'unattributed' })] },
  { id: 'lights', label: 'Lights & switches', reads: 'span', total: 3,
    changes: 3, blurb: 'The bulk of what a house does.',
    episodes: [
      ep({ subject: 'lights', entity_id: 'light.kitchen', name: 'Kitchen',
           first: 'on', last: 'off', count: 2, started: NOW - 360,
           ended: NOW - 300, duration_s: 60, cause: 'automation',
           by_name: 'Evening lights when it gets dark', undid: 'Evening lights' }),
      ep({ subject: 'lights', entity_id: 'switch.kettle', name: 'Kettle',
           first: 'on', last: 'on', open: true, started: NOW - 1800,
           ended: NOW - 1800, duration_s: 1800, cause: 'voice',
           by_name: 'Assist' }),
      ep({ subject: 'lights', entity_id: 'light.hall', name: 'Hall lamp',
           first: 'on', last: 'off', started: NOW - 5400, ended: NOW - 5000,
           duration_s: 400, cause: 'brain', by_name: 'brAIn' }),
    ] },
];
const TOTAL_ROWS = SECTIONS.reduce((n, s) => n + s.episodes.length, 0);
const COUNTS = { brain: 1, automation: 2, script: 0, scene: 0, voice: 1,
                 person: 4, unattributed: 12 };

const STUB = `
window.__activity = {
  available: true, error: '', start: ${NOW - 86400}, end: ${NOW}, hours: 24,
  sections: ${JSON.stringify(SECTIONS)},
  away: [{ start: ${NOW - 20000}, end: ${NOW - 1800} }],
  counts: ${JSON.stringify(COUNTS)},
  causes: ['brain','automation','script','scene','voice','person','unattributed'],
  capped: false, dropped: 1842, changes: 20, episodes: ${TOTAL_ROWS},
};
window.__empty = false;
window.__summaryCalls = 0;
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/activity/summary')) {
    window.__summaryCalls += 1;
    await new Promise((r) => setTimeout(r, 120));
    return answer({ summary: 'A quiet evening: the TV ran for three hours '
      + 'and the kitchen light came on by itself and was switched back off.',
      start: 0, end: 0, run_id: 'sess-1', cached: false });
  }
  if (p.includes('api/activity/entity/')) {
    const id = decodeURIComponent(p.split('api/activity/entity/')[1].split('?')[0]);
    // Deliberately slow. A row's history is a real round trip, so the pane
    // opens on 'Reading…' and fills afterwards — and an instant stub hides
    // that, which is how the first version of this file asserted on the
    // interim state and passed locally while failing in CI.
    await new Promise((r) => setTimeout(r, 150));
    return answer({ available: true, error: '', entity_id: id,
                    changes: [{ ts: ${NOW} - 300, state: 'off',
                                cause: 'person', by_name: 'Ben' }] });
  }
  if (p.includes('api/situation')) {
    return answer({ house_mode: 'home', sentence: 'Two people are in; the '
      + 'lounge TV is on.', sentence_stale: false, frame: {} });
  }
  if (p.includes('api/activity')) {
    (window.__activityQueries = window.__activityQueries || []).push(p);
    if (window.__empty) {
      return answer({ available: true, error: '', sections: [], away: [],
                      counts: {}, dropped: 40, changes: 0, episodes: 0,
                      capped: false });
    }
    return answer(window.__activity);
  }
  // The shape the panel actually READS, not a plausible-looking one.
  // /api/status is dereferenced unguarded in several places, so a stub
  // that omits a key throws a page error seconds later — which this file
  // fails on, and which has nothing to do with the tab under test.
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
  await openView(page, 'activity');
  await page.waitForSelector('.actrow');

  const m = await page.evaluate(() => {
    const wrap = document.querySelector('.actwrap').getBoundingClientRect();
    const secs = [...document.querySelectorAll('.actsec')];
    return {
      sections: secs.map((s) => ({
        id: s.dataset.section,
        heading: s.querySelector('h3')?.textContent.trim() || '',
        blurb: s.querySelector('.actsecblurb')?.textContent.trim() || '',
        count: s.querySelector('.actseccount')?.textContent.trim() || '',
        entities: [...s.querySelectorAll('.actrow')].map((r) => r.dataset.entity),
        rows: [...s.querySelectorAll('.actrow')].map((r) => {
          const box = r.getBoundingClientRect();
          const cause = r.querySelector('.cause');
          const cs = cause && getComputedStyle(cause);
          return {
            entity: r.dataset.entity,
            kind: r.dataset.cause,
            rkind: r.dataset.kind || '',
            disabled: r.disabled,
            note: r.querySelector('.actnote')?.textContent.trim() || '',
            causeText: cause ? cause.textContent.trim() : '',
            causeShown: !!(cs && cs.display !== 'none' && cs.visibility !== 'hidden'),
            when: r.querySelector('.when')?.textContent.trim() || '',
            undid: r.querySelector('.actundid')?.textContent.trim() || '',
            words: r.textContent,
            h: Math.round(box.height),
            right: box.right,
          };
        }),
      })),
      away: document.querySelector('.actaway')?.textContent.trim() || '',
      range: document.querySelector('#actRange')?.textContent.trim() || '',
      askLabel: document.querySelector('.actask button')?.textContent.trim() || '',
      now: document.querySelector('#actNow')?.textContent.trim() || '',
      nowShown: !document.querySelector('#actNow')?.hidden,
      pane: document.querySelector('#viewActivity')?.textContent || '',
      chips: document.querySelectorAll('#viewActivity .fchip').length,
      selectIsSel: !!document.querySelector('#actCause.sel'),
      summaryShown: !!document.querySelector('.actsum'),
      foot: document.querySelector('.actfoot')?.textContent.trim() || '',
      filters: [...document.querySelectorAll('#actCause option')]
        .map((b) => b.textContent.trim()),
      wrapRight: wrap.right,
      docWidth: document.documentElement.scrollWidth,
      summaryCalls: window.__summaryCalls,
    };
  });

  // The restructure itself: four kinds of thing, four sections, in the
  // server's order and not the browser's.
  const ids = m.sections.map((s) => s.id);
  if (ids.join(",") !== SECTIONS.map((s) => s.id).join(",")) {
    note(`${width}px`, `sections are ${ids.join(", ")}`);
  }
  for (const sec of m.sections) {
    if (!sec.heading) note(`${width}px`, `section ${sec.id} renders no heading`);
    if (sec.blurb) {
      note(`${width}px`, `section ${sec.id} still carries its cut intro`);
    }
    if (!sec.count) note(`${width}px`, `section ${sec.id} shows no count`);
  }
  // The load-bearing one: a door must not be filed with the motion.
  const where = (entity) => (m.sections.find(
    (s) => s.entities.includes(entity)) || {}).id || '(nowhere)';
  for (const [entity, want] of [
    ['binary_sensor.back_door', 'openings'],
    ['binary_sensor.hall_motion', 'motion'],
    ['person.ben', 'people'],
    ['media_player.lounge', 'media'],
    ['light.kitchen', 'lights'],
  ]) {
    if (where(entity) !== want) {
      note(`${width}px`, `${entity} is under "${where(entity)}", not "${want}"`);
    }
  }

  const rows = m.sections.flatMap((s) => s.rows);
  if (rows.length !== TOTAL_ROWS) {
    note(`${width}px`, `${rows.length} rows for ${TOTAL_ROWS} episodes`);
  }
  for (const row of rows) {
    const label = row.entity || row.rkind;
    // A row something caused names it; a row nothing caused says nothing,
    // because the foot says it once — 14,249 rows each reading "No cause
    // recorded" was one fact said fourteen thousand times.
    if (row.kind !== 'unattributed' && !row.causeText) {
      note(`${width}px`, `${label} renders no cause`);
    }
    if (row.causeText && !row.causeShown) {
      note(`${width}px`, `${label}'s cause is hidden rather than moved`);
    }
    if (/no cause/i.test(row.causeText)) {
      note(`${width}px`, `${label} repeats "no cause recorded" on the row`);
    }
    if (!row.when) note(`${width}px`, `${row.entity} does not say when`);
    if (row.h < MIN_TARGET) {
      note(`${width}px`, `row ${row.entity} is ${row.h}px, under ${MIN_TARGET}`);
    }
    if (row.right > m.wrapRight + 0.5) {
      note(`${width}px`, `row ${row.entity} overflows the list`);
    }
  }
  // A run is one row and it says how long it ran for, which is the whole
  // difference from the logbook this replaced.
  const tv = rows.find((r) => r.entity === 'media_player.lounge');
  if (tv && !/\b3h\b/.test(tv.when)) {
    note(`${width}px`, `a three-hour programme reads "${tv.when}"`);
  }
  // ...and a momentary sensor is counted rather than timed, because its
  // span is an artefact of when it last happened to fire.
  const motion = rows.find((r) => r.entity === 'binary_sensor.hall_motion');
  if (motion && !/9×/.test(motion.when)) {
    note(`${width}px`, `nine trips read as "${motion.when}"`);
  }
  if (motion && /\bh\b|min/.test(motion.when)) {
    note(`${width}px`, `a momentary sensor is reported as a duration: `
      + `"${motion.when}"`);
  }
  // A person is a moment, not a span.
  const ben = rows.find((r) => r.entity === 'person.ben');
  if (ben && !/^since /.test(ben.when)) {
    note(`${width}px`, `an arrival reads "${ben.when}"`);
  }
  // ...and the foot says it once, in words.
  if (!/no\s+recorded cause/i.test(m.foot)) {
    note(`${width}px`, 'the foot does not say once that some changes have no cause');
  }
  // A rolling window is named as one: "Today" over yesterday's rows was
  // the label lying about the list under it.
  if (m.range !== 'Last 24 hours') {
    note(`${width}px`, `the window is labelled "${m.range}"`);
  }
  // The restart is a row, and what began around it says so.
  const restart = rows.find((r) => r.rkind === 'restart');
  if (!restart || !/restarted/.test(restart.words)) {
    note(`${width}px`, 'the Home Assistant restart is not a row');
  }
  if (restart && !restart.disabled) {
    note(`${width}px`, 'the restart row offers a history it does not have');
  }
  const nowRow = rows.find((r) => r.entity === 'climate.downstairs'
    && /unavailable/.test(r.words) && !/heat_cool/.test(r.words));
  if (!nowRow || !/restart/i.test(nowRow.causeText)) {
    note(`${width}px`, 'the unavailable thermostat does not name the restart');
  }
  if (nowRow && !/current state/i.test(nowRow.note)) {
    note(`${width}px`, 'a row read off the live state does not say so');
  }
  if (nowRow && !/^since /.test(nowRow.when)) {
    note(`${width}px`, `the live state reads "${nowRow.when}", not "since"`);
  }
  const stale = rows.find((r) => /heat_cool/.test(r.words));
  if (stale && /so far/.test(stale.when)) {
    note(`${width}px`, `heat_cool still claims to be going: "${stale.when}"`);
  }
  if (stale && !/now unavailable/.test(stale.note)) {
    note(`${width}px`, 'the stale episode does not say what it is now');
  }
  const mass = rows.find((r) => r.rkind === 'mass');
  if (!mass || !/23 devices from UniFi/.test(mass.words)) {
    note(`${width}px`, 'a reload is not one row naming the integration');
  }
  // An override is on the row, in words — not a count in a block above it.
  const undone = rows.find((r) => r.entity === 'light.kitchen');
  if (undone && !/undid/i.test(undone.undid)) {
    note(`${width}px`, 'the row a person undid does not say so');
  }
  // What was left out, said out loud.
  if (!/1,842|1842/.test(m.foot)) {
    note(`${width}px`, `the foot does not say what was dropped: "${m.foot}"`);
  }
  if (!/reading/i.test(m.foot)) {
    note(`${width}px`, 'the foot does not say why readings are not listed');
  }
  if (!/Nobody home/i.test(m.away)) {
    note(`${width}px`, 'the empty-house band is missing with a span to show');
  }
  // The paragraph is a press and it has not been pressed.
  if (m.summaryCalls !== 0) {
    note(`${width}px`, `the summary ran ${m.summaryCalls}× without a press`);
  }
  if (m.summaryShown) note(`${width}px`, 'a summary is shown with none asked for');
  if (m.askLabel !== 'Ask') {
    note(`${width}px`, `the summary press reads "${m.askLabel}", not Ask`);
  }
  if (!m.nowShown || !/^Someone's home/.test(m.now)) {
    note(`${width}px`, `the top line is "${m.now}", not the house's situation`);
  }
  for (const cut of [/Not every state change/, /no Claude run, nothing spent/,
                     /What does this add up to/, /Tap a row/,
                     /Home Assistant itself stopping and starting/]) {
    if (cut.test(m.pane)) note(`${width}px`, `cut text is back: ${cut}`);
  }

  if (!m.selectIsSel) note(`${width}px`, 'no "Caused by" select.sel rendered');
  if (m.chips) note(`${width}px`, `${m.chips} filter chips are back`);
  if (m.filters[0] !== 'Anything') {
    note(`${width}px`, `the select opens on "${m.filters[0]}"`);
  }
  if (m.filters.some((f) => /\d|·/.test(f))) {
    note(`${width}px`, `a cause carries a count: ${m.filters.join(' | ')}`);
  }
  if (m.filters.some((f) => /^Scene/.test(f))) {
    note(`${width}px`, 'a filter is offered for a cause with no rows');
  }
  if (m.docWidth > width + 0.5) {
    note(`${width}px`, `page scrolls sideways (${m.docWidth}px)`);
  }

  // Picking a cause asks the server for that cause, and nothing else.
  await page.evaluate(() => { window.__activityQueries = []; });
  await page.selectOption('#actCause', 'automation');
  await page.waitForFunction(() => (window.__activityQueries || [])
    .some((q) => /cause=automation/.test(q)), null, { timeout: 5000 })
    .catch(() => note(`${width}px`, 'picking a cause asked the server nothing'));
  await page.selectOption('#actCause', '');
  await page.waitForSelector('.actrow');

  // Tapping a row opens that entity's history, and tapping it again closes it.
  // A collapsed burst opens onto what it collapsed, with no fetch.
  // Noted rather than thrown when it is missing, like every wait here: a
  // throw abandons everything else this pass would have found.
  const massRow = page.locator('.actrow[data-kind="mass"]');
  if (await massRow.count()) {
    await massRow.click();
    await page.waitForSelector('.actwhy');
    const massWhy = await page.evaluate(
      () => document.querySelector('.actwhy')?.textContent || '');
    if (!/device_tracker\.office_ap/.test(massWhy)) {
      note(`${width}px`, 'the burst does not list what it collapsed');
    }
    await massRow.click();
    await page.waitForTimeout(80);
  }

  const benRow = '.actrow[data-entity="person.ben"]';
  await page.locator(benRow).click();
  await page.waitForSelector('.actwhy');
  // The pane appears on 'Reading…' and fills when the fetch lands, so
  // settling is what is being waited for.
  let settled = true;
  try {
    await page.waitForFunction(() => {
      const box = document.querySelector('.actwhy');
      return box && !/Reading/.test(box.textContent);
    }, null, { timeout: 5000 });
  } catch {
    settled = false;
    note(`${width}px`, 'history pane never stopped saying "Reading…"');
  }
  const why = await page.evaluate(() => ({
    text: document.querySelector('.actwhy')?.textContent || '',
    count: document.querySelectorAll('.actwhy').length,
  }));
  if (why.count !== 1) note(`${width}px`, `${why.count} history panes open at once`);
  if (settled && !/person\.ben/.test(why.text)) {
    note(`${width}px`, 'history pane does not name the entity');
  }
  await page.locator(benRow).click();
  await page.waitForTimeout(80);
  if (await page.locator('.actwhy').count()) {
    note(`${width}px`, 'a second tap did not close the history pane');
  }

  console.log(`${failures.length ? 'ok? ' : 'ok  '}${String(width).padStart(4)}px  `
    + `${m.sections.length} sections, ${rows.length} rows, `
    + `${m.filters.length} filters`);
  await context.close();
}

// The press, once — and what it costs, said before it is pressed.
{
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note('summary', `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'activity');
  await page.waitForSelector('.actask button');
  await page.click('.actask button');
  let ok = true;
  try {
    await page.waitForSelector('.actsum', { timeout: 5000 });
  } catch {
    ok = false;
    note('summary', 'the paragraph never arrived after a press');
  }
  if (ok) {
    const out = await page.evaluate(() => ({
      text: document.querySelector('.actsum p')?.textContent || '',
      again: !!document.querySelector('.actsumfoot button'),
      calls: window.__summaryCalls,
      asks: document.querySelectorAll('.actask').length,
    }));
    if (!/three hours/.test(out.text)) note('summary', 'the paragraph is not shown');
    if (!out.again) note('summary', 'no way to ask again');
    if (out.calls !== 1) note('summary', `${out.calls} runs for one press`);
    if (out.asks) note('summary', 'the ask button is still offered beside it');
  }
  console.log('ok  the paragraph is one press and one run');
  await context.close();
}

// A quiet window says so, and still says what it left out.
{
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note('empty', `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.addInitScript('window.__empty = true;');
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'activity');
  await page.waitForSelector('.actempty');
  const out = await page.evaluate(() => ({
    text: document.querySelector('.actempty')?.textContent || '',
    away: document.querySelectorAll('.actaway').length,
    ask: document.querySelectorAll('.actask').length,
    secs: document.querySelectorAll('.actsec').length,
  }));
  if (out.secs) note('empty', `${out.secs} section headings with nothing in them`);
  if (out.away) note('empty', 'an empty-house band with nothing to show');
  // Nothing to summarise is nothing to spend on.
  if (out.ask) note('empty', 'the summary is offered over an empty window');
  if (!/40/.test(out.text)) {
    note('empty', 'a quiet window does not say what it left out');
  }
  console.log('ok  empty window: one sentence, no headings, nothing to spend');
  await context.close();
}

await browser.close();
for (const f of failures) console.log(`  - ${f}`);
console.log(failures.length ? `\n${failures.length} problem(s)` : '\nall widths ok');
process.exit(failures.length ? 1 : 0);
