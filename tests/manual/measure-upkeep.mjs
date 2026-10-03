// Render House → Upkeep and assert each of its four sections can be acted
// on from what it shows.
//
// The pane exists for four decisions, and each fails in a way a server test
// cannot see:
//
//   * a house book sentence with no source chip under it reads exactly
//     like a cited one — the citation is the half that makes it a manual
//     rather than a story, so every entry must render at least one;
//   * the tidy table is a review: every row has its own tick, the tick is
//     a 44px target on a finger, the Apply button counts what is ticked
//     (and the count moves when a box is unticked), and an area move says
//     which automation it changes — on the row, not in a tooltip;
//   * an upgrade verdict is shown with BOTH quotes it rests on, and an
//     update nobody has asked about offers the question rather than a
//     blank; an update list brAIn could not read says so, which is a
//     different sentence from "nothing is waiting";
//   * a run in flight says so on the page, not only by greying a button.
//
// Nothing scrolls sideways at 390, every button in the pane is 44px on
// touch, and the ids the handlers bind to are all still there. It drives
// the panel's REAL renderers behind a stubbed fetch — measure-activity's
// rule, because a copy of the renderer here would only agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const NOW = Math.floor(Date.now() / 1000);
const IDS = ['viewUpkeep', 'upBook', 'upTidy', 'upUpdates', 'upHealth'];

const BOOK = {
  running: false, last_error: '', last_note: '', held: '', subject: '',
  opted_in: true, unreadable: false,
  published: { at: NOW - 600, path: '/local/brain/book/house-book-0123456789abcdef0123456789abcdef.html' },
  book: {
    at: NOW - 3600, uncited: 1, redacted: 0, run_id: 'hb1',
    sections: [
      { key: 'alarms', title: 'If an alarm goes off', entries: [
        { text: 'If the utility leak alarm sounds, the house closes the mains '
            + 'water valve and texts Ben. Check under the washing machine first.',
          sources: [{ key: 'automation:brain_playbook_leak', label: 'Leak: close the water' },
                    { key: 'entity:switch.mains_valve', label: 'Mains valve' }] }] },
      { key: 'heating', title: 'Heating and cooling', entries: [
        { text: 'The hall thermostat warms the house from 06:30 on weekdays.',
          sources: [{ key: 'automation:warm', label: 'Warm before wake' }] }] },
    ],
  },
};

const TIDY = {
  running: false, last_error: '', last_note: '', held: '', subject: '',
  unreadable: false, undo_days: 30,
  proposal: {
    at: NOW - 300, run_id: 't1', dropped: 0,
    rows: [
      { id: 'r0', kind: 'name', target: 'entity',
        subject: 'switch.plug_00158d0004a1b2c3', value: 'Lounge lamp plug',
        label: 'Plug 00158d0004a1b2c3', why: 'It powers the lounge lamp.' },
      { id: 'r1', kind: 'area', target: 'device', subject: 'dev-lamp',
        value: 'lounge', area_name: 'Lounge', from_area: '', label: 'Reading lamp',
        why: 'Its plug is in the lounge.',
        reach: [{ id: 'lights-out', alias: 'Lounge lights out at 23:00',
                  area: 'Lounge', change: 'will now reach it' }] },
      { id: 'r2', kind: 'alias', target: 'entity', subject: 'light.ceiling',
        value: 'big light', label: 'Lounge ceiling', why: 'What everybody calls it.' },
    ],
    refused: [{ kind: 'area', subject: 'dev-x', value: 'Conservatory',
                label: 'Fan', refused: 'that room does not exist in Home Assistant' }],
  },
  batches: [{ id: 'b1', at: NOW - 86400, undone_at: 0,
              entries: [{ target: 'entity', subject: 'light.a', before: {}, after: {} }] }],
};

const UPGRADES = {
  running: false, last_error: '', last_note: '', held: '', subject: '',
  readable: true,
  updates: [
    { entity_id: 'update.core', title: 'Home Assistant Core',
      installed: '2026.10.3', latest: '2026.11.0',
      advice: { verdict: 'wait', checked: true,
                reason: 'Your lounge template light still uses white_value, '
                  + 'which this release removes.',
                note_quote: 'the `white_value` attribute has been removed from template lights',
                config_quote: "white_value_template: '{{ 200 }}'",
                edit: 'Remove white_value_template from the lounge light.' } },
    { entity_id: 'update.zigbee2mqtt', title: 'Zigbee2MQTT',
      installed: '1.40.0', latest: '1.41.0', advice: null },
  ],
};

const SRE = {
  running: false, last_error: '', last_note: '', held: '', subject: '',
  last: { at: NOW - 30000, records: 12, causes: 1, filed: 1, cleared: 0,
          note: '', ran: true },
};
const ACCESS = {
  running: false, last_error: '', last_note: '', held: '', subject: '',
  sentence: 'Two people can administer this house, and the front door lock '
    + 'answers to Alexa — worth a PIN.',
  at: NOW - 86400 * 2, open: 1,
};

const stub = (bodies) => `
window.__up = ${JSON.stringify(bodies)};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (b) => new Response(JSON.stringify(b), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/tidy')) return answer(window.__up.tidy);
  if (p.includes('api/upgrades')) return answer(window.__up.upgrades);
  if (p.includes('api/sre')) return answer(window.__up.sre);
  if (p.includes('api/house_book')) return answer(window.__up.book);
  if (p.includes('api/access')) return answer(window.__up.access);
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
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

const open = async (width, touch, bodies) => {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(bodies));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'upkeep');
  return { context, page };
};

const read = (page) => page.evaluate((ids) => {
  const box = (n) => n.getBoundingClientRect();
  const q = (s) => [...document.querySelectorAll(s)];
  return {
    missing: ids.filter((i) => !document.getElementById(i)),
    visible: !!document.querySelector('#viewUpkeep.active'),
    entries: q('#upBook .upbooklist li').map((li) => ({
      text: li.firstChild ? li.firstChild.textContent : '',
      chips: li.querySelectorAll('.upchip').length,
    })),
    link: (document.querySelector('#upBook .uplink a') || {}).textContent || '',
    rows: q('#upTidy .uprow').map((r) => ({
      text: r.textContent,
      tick: !!r.querySelector('input[type="checkbox"]'),
      checked: (r.querySelector('input[type="checkbox"]') || {}).checked,
      h: Math.round(box(r).height),
      right: Math.round(box(r).right),
      reach: r.querySelectorAll('.upreach').length,
    })),
    apply: (q('#upTidy .upactions button').find((b) => /Apply/.test(b.textContent))
            || {}).textContent || '',
    refused: (document.querySelector('#upTidy .uprefused summary') || {}).textContent || '',
    undo: q('#upTidy .upbatch button').length,
    updates: q('#upUpdates .upupdate').map((u) => ({
      text: u.textContent,
      verdict: (u.querySelector('.upchip.verdict') || {}).textContent || '',
      quotes: u.querySelectorAll('.upquote').length,
      ask: (u.querySelector('button') || {}).textContent || '',
      right: Math.round(box(u).right),
    })),
    updatesText: (document.getElementById('upUpdates') || {}).textContent || '',
    bookText: (document.getElementById('upBook') || {}).textContent || '',
    health: (document.getElementById('upHealth') || {}).textContent || '',
    buttons: q('#viewUpkeep button').filter((b) => b.offsetParent).map((b) => ({
      label: b.textContent.trim(), h: Math.round(box(b).height),
      disabled: b.disabled })),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
}, IDS);

const ALL = { book: BOOK, tidy: TIDY, upgrades: UPGRADES, sre: SRE, access: ACCESS };

for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { context, page } = await open(width, touch, ALL);
  await page.waitForSelector('#upTidy .uprow', { timeout: 5000 })
    .catch(() => note(where, 'the tidy table never rendered'));
  await page.waitForSelector('#upUpdates .upupdate', { timeout: 5000 }).catch(() => {});
  const v = await read(page);
  if (v.missing.length) note(where, `element id(s) gone: ${v.missing.join(', ')}`);
  if (!v.visible) note(where, 'the Upkeep pane is not the one in front');

  if (v.entries.length !== 2) note(where, `${v.entries.length} book entries, not 2`);
  for (const e of v.entries) {
    if (!e.chips) note(where, `a book sentence carries no source: "${e.text.slice(0, 50)}"`);
  }
  if (!/left out for citing nothing/.test(v.bookText)) {
    note(where, 'the book does not say a sentence was left out uncited');
  }
  if (!/house-book-/.test(v.link)) note(where, 'the published link is not shown');
  if (!/Take the link down/.test(v.bookText)) note(where, 'no way to take the link down');

  if (v.rows.length !== 3) note(where, `${v.rows.length} tidy rows, not 3`);
  for (const r of v.rows) {
    if (!r.tick) note(where, `a tidy row has no tick: "${r.text.slice(0, 40)}"`);
    if (!r.checked) note(where, `a new proposal row starts unticked: "${r.text.slice(0, 40)}"`);
    if (touch && r.h < 44) note(where, `a tidy row is ${r.h}px tall on a finger`);
    if (r.right > v.viewport + 1) note(where, 'a tidy row hangs off the side');
  }
  const area = v.rows.find((r) => /Reading lamp/.test(r.text));
  if (!area || !area.reach) {
    note(where, 'the room move does not say which automation it changes');
  } else if (!/Lounge lights out/.test(area.text)) {
    note(where, 'the room move names no automation');
  }
  if (!/Apply 3 ticked/.test(v.apply)) note(where, `Apply reads "${v.apply}"`);
  if (!/1 suggestion brAIn refused/.test(v.refused)) {
    note(where, `the refused rows are not counted: "${v.refused}"`);
  }
  if (v.undo !== 1) note(where, `${v.undo} Undo buttons for 1 batch`);

  // Untick one: the count is what will be written, so it has to move.
  await page.locator('#upTidy .uprow input[type="checkbox"]').first().click();
  const after = await read(page);
  if (!/Apply 2 ticked/.test(after.apply)) {
    note(where, `unticking a row left Apply reading "${after.apply}"`);
  }

  const core = v.updates.find((u) => /Home Assistant Core/.test(u.text));
  if (!core || core.verdict !== 'Wait') note(where, 'the advised update shows no verdict word');
  if (core && core.quotes !== 2) note(where, `the verdict shows ${core.quotes} quotes, not 2`);
  const z2m = v.updates.find((u) => /Zigbee2MQTT/.test(u.text));
  if (!z2m || !/safe tonight/i.test(z2m.ask)) {
    note(where, 'an update nobody asked about does not offer the question');
  }
  for (const u of v.updates) {
    if (u.right > v.viewport + 1) note(where, 'an update card hangs off the side');
  }
  if (!/worth a PIN/.test(v.health)) note(where, 'the access review sentence is missing');
  if (!/12 records read/.test(v.health)) note(where, 'the overnight check does not say what it read');

  if (touch) {
    for (const b of v.buttons) {
      if (b.h < 44) note(where, `"${b.label}" is ${b.h}px tall on a finger`);
    }
  }
  if (v.docWidth > v.viewport + 1) {
    note(where, `page scrolls sideways (${v.docWidth} > ${v.viewport})`);
  }
  console.log(`${String(width).padStart(5)}  ${v.entries.length} book entries  `
    + `${v.rows.length} tidy rows  ${v.updates.length} updates  ${v.buttons.length} buttons`);
  await context.close();
}

// Two states that must not read alike: an update list brAIn could not read,
// and an empty one. And a run in flight, said in words.
{
  const { context, page } = await open(1200, false, {
    ...ALL,
    upgrades: { ...UPGRADES, readable: false, updates: [] },
    book: { ...BOOK, running: true },
  });
  await page.waitForFunction(() => /could not look/.test(
    document.getElementById('upUpdates')?.textContent || ''), null,
    { timeout: 5000 }).catch(() => {});
  const v = await read(page);
  if (!/could not look/.test(v.updatesText)) {
    note('unreadable', `the update list says "${v.updatesText.slice(0, 80)}"`);
  }
  if (/Nothing is waiting/.test(v.updatesText)) {
    note('unreadable', 'an unread list reads as "nothing is waiting"');
  }
  if (!/Writing the house book/.test(v.bookText)) {
    note('running', 'nothing on the page says the book is being written');
  }
  const run = v.buttons.find((b) => /Rewrite|Write the house book/.test(b.label));
  if (!run || !run.disabled) note('running', 'the write button is still pressable');
  await context.close();
}
{
  const { context, page } = await open(1200, false, {
    ...ALL, upgrades: { ...UPGRADES, updates: [] } });
  await page.waitForFunction(() => /Nothing is waiting/.test(
    document.getElementById('upUpdates')?.textContent || ''), null,
    { timeout: 5000 }).catch(() => {});
  const v = await read(page);
  if (!/Nothing is waiting/.test(v.updatesText)) {
    note('empty', `an empty update list says "${v.updatesText.slice(0, 80)}"`);
  }
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(`measure-upkeep: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nevery section of Upkeep can be acted on from what it shows');
