// Upkeep's three pieces in their new homes: the names-and-rooms tidy and
// the assessed updates are cards in Today's queue (docs/design/
// ui-redesign-2026-10.md: a tidy-up is a "Change ready" card, an assessed
// update a card with its verdict), and the house book is House › House
// book. The Upkeep pane is gone; the overnight check and the access review
// are ⚙ › Diagnostics' and measure-settings' to hold. Each fails in a way a
// server test cannot see:
//
//   * the tidy card is a review: every change has its own tick under
//     Details, ticked by default, a 44px target on a finger; Apply sends
//     exactly what is ticked (and unticking one takes it out); a room move
//     says on the face that it changes what an automation reaches, and
//     Details names the automation; what brAIn refused is listed;
//   * an update card shows its verdict as a word, and Details carries BOTH
//     quotes it rests on and the line that brAIn never installs an update;
//     Add to To Do puts it on To Do and takes the card off the queue;
//   * Snooze and Ignore on either card hide it through `today/hide`;
//   * a house book sentence with no source chip under it reads exactly
//     like a cited one — the citation is the half that makes it a manual
//     rather than a story, so every entry must render at least one; the
//     head reads "How this house works", its first press is Add info
//     (sharing is behind ⋯), every chapter has its own Add info, every
//     line can be edited and deleted where it stands, the chapter pills
//     filter and count, and the one line a sitter is told — "codes and
//     passwords are left out" — is on screen whether or not the book is
//     shared, because it is a safety line and never folded away;
//   * a run in flight says so on the page, not only by greying a button.
//
// Nothing scrolls sideways at 390 and every press is 44px on touch. It
// drives the panel's REAL renderers behind a stubbed fetch — measure-
// activity's rule, because a copy of the renderer here would only agree
// with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';
import { openToday, posts } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const NOW = Math.floor(Date.now() / 1000);
const IDS = ['viewHousebook', 'upBook'];

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
          rooms: ['Hall'],
          sources: [{ key: 'automation:warm', label: 'Warm before wake' }] }] },
    ],
  },
  sections: [
    { key: 'automations', title: 'What the house does on its own' },
    { key: 'heating', title: 'Heating and cooling' },
    { key: 'alarms', title: 'If an alarm goes off' },
    { key: 'shutoffs', title: 'Shutoffs and where things are' },
  ],
};
BOOK.book.sections[0].entries[0].id = 'aaaaaaaaaaaa';
BOOK.book.sections[0].entries[0].rooms = ['Utility'];
BOOK.book.sections[1].entries[0].id = 'bbbbbbbbbbbb';

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
window.fetch = async (url, opts) => {
  const p = String(url);
  (window.__posts = window.__posts || []).push({ url: p,
    method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null });
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

const open = async (width, touch, bodies, view = 'housebook') => {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(bodies));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, view);
  return { context, page };
};

const read = (page) => page.evaluate((ids) => {
  const box = (n) => n.getBoundingClientRect();
  const q = (s) => [...document.querySelectorAll(s)];
  return {
    missing: ids.filter((i) => !document.getElementById(i)),
    visible: !!document.querySelector('#viewUpkeep.active'),
    bookVisible: !!document.querySelector('#viewHousebook.active'),
    bookInUpkeep: !!document.querySelector('#viewUpkeep #upBook'),
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
    bookButtons: q('#viewHousebook button').filter((b) => b.offsetParent).map((b) => ({
      label: b.textContent.trim(), h: Math.round(box(b).height),
      disabled: b.disabled })),
    buttons: q('#viewUpkeep button').filter((b) => b.offsetParent).map((b) => ({
      label: b.textContent.trim(), h: Math.round(box(b).height),
      disabled: b.disabled })),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
}, IDS);

const ALL = { book: BOOK, tidy: TIDY, upgrades: UPGRADES, sre: SRE, access: ACCESS };

// Today's two cards no store owns, in `/api/today`'s shape: the tidy as the
// proposal itself, and the update the server assessed.
const EXTRAS = {
  tidy: { key: 'tidy:1700000000', at: 1700000000, undo_days: 30,
          rows: TIDY.proposal.rows, refused: TIDY.proposal.refused },
  updates: [{ key: 'update:update.core:2026.11.0', ...UPGRADES.updates[0] }],
};

for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { context, page } = await openToday(browser, PANEL, { width, touch,
    over: { extras: EXTRAS }, onError: (m) => note(where, `page error: ${m}`) });
  const read2 = () => page.evaluate(() => {
    const card = (sel) => document.querySelector(`[data-case-id="${sel}"]`);
    const face = (c) => { const x = c.cloneNode(true);
      x.querySelectorAll('details').forEach((d) => d.remove()); return x.textContent; };
    const t = card('tidy:1700000000');
    const u = card('update:update.core:2026.11.0');
    const presses = (c) => [...c.querySelectorAll(':scope > .card-actions button')]
      .filter((b) => !b.classList.contains('icon')).map((b) => b.textContent.trim());
    return {
      tidy: t && {
        chip: t.querySelector('.chip-status').textContent,
        meta: [...t.querySelectorAll('.meta .item-state')].map((x) => x.textContent),
        face: face(t), details: t.querySelector('details').textContent,
        rows: [...t.querySelectorAll('.qtidyrow')].map((r) => {
          t.querySelector('details').open = true;
          const box = r.getBoundingClientRect();
          return { text: r.textContent, checked: r.querySelector('input').checked,
                   h: Math.round(box.height), right: Math.round(box.right) };
        }),
        presses: presses(t),
      },
      update: u && {
        chip: u.querySelector('.chip-status').textContent,
        meta: [...u.querySelectorAll('.meta .item-state')].map((x) => x.textContent),
        details: u.querySelector('details').textContent, presses: presses(u),
        right: Math.round(u.getBoundingClientRect().right),
      },
      docWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
    };
  });
  const v = await read2();
  if (!v.tidy) note(where, 'the tidy card is not in the queue');
  else {
    if (v.tidy.chip !== 'Tidy-up') note(where, `the tidy card's chip is "${v.tidy.chip}"`);
    if (!v.tidy.meta.includes('Change ready')) note(where, `the tidy card's meta is ${v.tidy.meta}`);
    if (v.tidy.rows.length !== 3) note(where, `${v.tidy.rows.length} tidy rows, not 3`);
    for (const r of v.tidy.rows) {
      if (!r.checked) note(where, `a new tidy row starts unticked: "${r.text.slice(0, 40)}"`);
      if (touch && r.h < 44) note(where, `a tidy row is ${r.h}px tall on a finger`);
      if (r.right > v.viewport + 1) note(where, 'a tidy row hangs off the side');
    }
    if (!/1 room move changes what an automation reaches/.test(v.tidy.face)) {
      note(where, 'the room move is not said on the face of the card');
    }
    if (!/Lounge lights out at 23:00/.test(v.tidy.details)) {
      note(where, 'Details does not name the automation the room move changes');
    }
    if (!/Conservatory/.test(v.tidy.details)) note(where, 'what brAIn refused is not listed');
    // A room row names the thing that moves, not just the two rooms.
    if (!v.tidy.rows.some((r) => /Reading lamp: no room → Lounge/.test(r.text))) {
      note(where, `the room row does not say what moves: ${v.tidy.rows.map((r) => r.text)}`);
    }
    if (v.tidy.presses.join('|') !== 'Apply|Snooze|Ignore') {
      note(where, `the tidy card offers ${v.tidy.presses.join(' · ')}`);
    }
  }
  if (!v.update) note(where, 'the update card is not in the queue');
  else {
    if (!v.update.meta.includes('Wait')) note(where, `the update's meta is ${v.update.meta}`);
    if (!/white_value` attribute has been removed/.test(v.update.details)
        || !/white_value_template/.test(v.update.details)) {
      note(where, 'Details does not carry both quotes the verdict rests on');
    }
    if (!/never installs an update itself/.test(v.update.details)) {
      note(where, 'the update card does not say brAIn never installs');
    }
    if (v.update.presses.join('|') !== 'Add to To Do|Snooze|Ignore') {
      note(where, `the update card offers ${v.update.presses.join(' · ')}`);
    }
    if (v.update.right > v.viewport + 1) note(where, 'the update card hangs off the side');
  }

  // Untick one, Apply: what is sent is what is ticked.
  await page.evaluate(() => {
    const t = document.querySelector('[data-case-id="tidy:1700000000"]');
    t.querySelector('details').open = true;
    t.querySelector('.qtidyrow input').click();
  });
  await page.evaluate(() => [...document.querySelectorAll(
    '[data-case-id="tidy:1700000000"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Apply').click());
  await page.waitForTimeout(150);
  // Snooze the update; Add it to the list.
  await page.evaluate(() => [...document.querySelectorAll(
    '[data-case-id="update:update.core:2026.11.0"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Snooze').click());
  await page.waitForTimeout(150);
  // "No, do this instead": Change on a row opens an editor, and Save sends
  // the new value for that row and nothing else.
  await page.evaluate(() => {
    const t = document.querySelector('[data-case-id="tidy:1700000000"]');
    t.querySelector('details').open = true;
    t.querySelector('.qtidychange').click();
  });
  const editor = await page.evaluate(() => {
    const f = document.querySelector('[data-case-id="tidy:1700000000"] .qtidyedit');
    return f ? { input: !!f.querySelector('input, select'),
                 save: [...f.querySelectorAll('button')].map((b) => b.textContent.trim()) } : null;
  });
  if (!editor || !editor.input) note(where, 'Change opens no editor');
  else if (editor.save.join('|') !== 'Save|Cancel') note(where, `the editor offers ${editor.save}`);
  await page.evaluate(() => {
    const f = document.querySelector('[data-case-id="tidy:1700000000"] .qtidyedit');
    const i = f.querySelector('input');
    if (i) { i.value = 'TV plug'; }
    [...f.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Save').click();
  });
  await page.waitForTimeout(150);
  const sent = await posts(page);
  const revise = sent.find((p) => /api\/tidy\/row\/r0$/.test(p.url));
  if (!revise || revise.body.value !== 'TV plug') {
    note(where, `Change sent ${JSON.stringify(revise && revise.body)}`);
  }
  const apply = sent.find((p) => /api\/tidy\/apply$/.test(p.url));
  if (!apply || JSON.stringify(apply.body.ids) !== JSON.stringify(['r1', 'r2'])) {
    note(where, `Apply sent ${JSON.stringify(apply && apply.body)}`);
  }
  const hide = sent.find((p) => /api\/today\/hide$/.test(p.url));
  if (!hide || hide.body.how !== 'snoozed' || hide.body.key !== 'update:update.core:2026.11.0') {
    note(where, `Snooze sent ${JSON.stringify(hide && hide.body)}`);
  }
  if (v.docWidth > v.viewport + 1) note(where, `page scrolls sideways (${v.docWidth})`);
  if (touch) {
    const small = await page.evaluate(() => [...document.querySelectorAll(
      '[data-case-id^="tidy:"] button, [data-case-id^="update:"] button')]
      .filter((b) => b.offsetParent).map((b) => Math.round(b.getBoundingClientRect().height))
      .filter((h) => h < 44));
    if (small.length) note(where, `presses under 44px: ${small.join(',')}`);
  }
  console.log(`${String(width).padStart(5)}  tidy ${v.tidy ? v.tidy.rows.length : 0} rows · `
    + `update ${v.update ? v.update.meta.join(' ') : 'missing'}`);
  await context.close();
}

// Add to To Do on an update card: on To Do, and off the queue.
{
  const { context, page } = await openToday(browser, PANEL, { width: 1200,
    over: { extras: EXTRAS }, onError: (m) => note('add to list', `page error: ${m}`) });
  await page.evaluate(() => [...document.querySelectorAll(
    '[data-case-id="update:update.core:2026.11.0"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Add to To Do').click());
  await page.waitForTimeout(200);
  const sent = await posts(page);
  const todo = sent.find((p) => /api\/todo$/.test(p.url));
  const listed = sent.find((p) => /api\/today\/hide$/.test(p.url));
  if (!todo || !/Update Home Assistant Core to 2026\.11\.0/.test(todo.body.text)) {
    note('add to list', `the list was sent ${JSON.stringify(todo && todo.body)}`);
  }
  if (!listed || listed.body.how !== 'listed') {
    note('add to list', `the card was hidden with ${JSON.stringify(listed && listed.body)}`);
  }
  await context.close();
}

// House › House book: a pane of its own, Add info leading, sharing behind
// ⋯, the cited entries with their own Edit and Delete, the chapter pills,
// and the safety line.
const SAFETY = 'Every sentence names what it came from; codes and passwords are left out.';
for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `book ${width}px`;
  for (const [state, book] of [['shared', BOOK], ['not shared', { ...BOOK, published: null }]]) {
    const { context, page } = await open(width, touch, { ...ALL, book }, 'housebook');
    await page.waitForSelector('#upBook .upbooklist li', { timeout: 5000 })
      .catch(() => note(where, `${state}: the book never rendered`));
    const v = await page.evaluate(() => {
      const box = (n) => n.getBoundingClientRect();
      const q = (s) => [...document.querySelectorAll(s)];
      return {
        missing: ['viewHousebook', 'upBook', 'bookAdd', 'bookAddModal']
          .filter((i) => !document.getElementById(i)),
        visible: !!document.querySelector('#viewHousebook.active'),
        sub: (document.querySelector('#viewHousebook .panesub') || {}).textContent || '',
        entries: q('#upBook .upbooklist li').map((li) => ({
          text: li.firstChild ? li.firstChild.textContent : '',
          chips: li.querySelectorAll('.upchip').length,
          acts: [...li.querySelectorAll('.bookact')].map((b) => b.getAttribute('aria-label')),
        })),
        secAdds: q('#upBook .booksecadd').length,
        gaps: q('#upBook .bookgaps .pill').map((b) => b.textContent),
        pills: q('#bookSecs .pill').map((b) => b.textContent),
        link: (document.querySelector('#upBook .uplink a') || {}).textContent || '',
        text: (document.getElementById('upBook') || {}).textContent || '',
        safe: [...document.querySelectorAll('#upBook .booksafe')].map((n) => ({
          text: n.textContent.trim(), shown: box(n).height > 0 })),
        buttons: q('#viewHousebook button').filter((b) => b.offsetParent).map((b) => ({
          label: (b.textContent.trim() || b.getAttribute('aria-label') || ''),
          h: Math.round(box(b).height) })),
        seg: !document.getElementById('houseSeg')?.hidden,
        docWidth: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
      };
    });
    if (v.missing.length) note(where, `element id(s) gone: ${v.missing.join(', ')}`);
    if (!v.visible) note(where, 'House book is not the pane in front');
    if (!v.seg) note(where, 'the House segmented control is not shown over the book');
    if (v.sub.trim() !== 'How this house works.') note(where, `the head says "${v.sub}"`);
    if (/sitter|partner/i.test(v.sub)) note(where, 'the head still names a sitter or a partner');
    if (v.entries.length !== 2) note(where, `${v.entries.length} book entries, not 2`);
    for (const e of v.entries) {
      if (!e.chips) note(where, `a book sentence carries no source: "${e.text.slice(0, 50)}"`);
      if (e.acts.join('|') !== 'Edit this line|Delete this line') {
        note(where, `a line offers ${JSON.stringify(e.acts)}, not Edit and Delete`);
      }
    }
    if (v.secAdds !== 2) note(where, `${v.secAdds} chapters carry their own Add info, not 2`);
    if (v.gaps.length !== 2) note(where, `the unwritten chapters read ${JSON.stringify(v.gaps)}`);
    if (width > 640 && v.pills.length !== 3) {
      note(where, `the chapter pills read ${JSON.stringify(v.pills)}`);
    }
    if (!/left out for citing nothing/.test(v.text)) {
      note(where, 'the book does not say a sentence was left out uncited');
    }
    if (v.safe.length !== 1 || v.safe[0].text !== SAFETY || !v.safe[0].shown) {
      note(where, `${state}: the safety line reads ${JSON.stringify(v.safe)}`);
    }
    const labels = v.buttons.map((b) => b.label);
    if (labels[0] !== 'Add info') note(where, `${state}: the first press is "${labels[0]}", not Add info`);
    if (labels.includes('Run') || labels.includes('Share')) {
      note(where, `${state}: Run or Share is back on the page (${labels.join(' · ')})`);
    }
    // Sharing is behind ⋯.
    await page.click('#bookMoreHost button');
    const menu = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
      .map((b) => b.textContent));
    if (state === 'not shared' && !menu.includes('Share a copy')) {
      note(where, `⋯ offers ${JSON.stringify(menu)}, no Share a copy`);
    }
    if (state === 'shared') {
      if (!/house-book-/.test(v.link)) note(where, 'the shared link is not shown');
      if (!labels.includes('Stop sharing')) note(where, 'no way to take the shared link down');
      if (menu.includes('Share a copy')) note(where, 'Share is offered over a book already shared');
    }
    await page.keyboard.press('Escape');
    await page.mouse.click(5, 300);
    for (const cut of [/Rewrite it now/, /Publish a link/, /Take the link down/,
                       /Write the house book —/]) {
      if (cut.test(v.text)) note(where, `cut label is back: ${cut}`);
    }
    if (touch) {
      for (const b of v.buttons) {
        if (b.h < 44) note(where, `"${b.label}" is ${b.h}px tall on a finger`);
      }
    }
    if (v.docWidth > v.viewport + 1) {
      note(where, `page scrolls sideways (${v.docWidth} > ${v.viewport})`);
    }
    if (state === 'not shared') {
      // A chapter pill narrows the book to that chapter and shows its tag.
      if (width > 640) {
        await page.evaluate(() => [...document.querySelectorAll('#bookSecs .pill')]
          .find((b) => /Heating/.test(b.textContent)).click());
        const n = await page.evaluate(() => ({
          lis: document.querySelectorAll('#upBook .upbooklist li').length,
          tag: document.querySelector('#bookActive')?.hidden === false,
        }));
        if (n.lis !== 1 || !n.tag) note(where, `a chapter pill shows ${n.lis} lines, tag ${n.tag}`);
        await page.evaluate(() => document.querySelector('#bookActive .filtertag').click());
      }
      // Edit is in place, and Save posts the new words for that line.
      await page.click('#upBook li[data-id="aaaaaaaaaaaa"] .bookact');
      const editing = await page.evaluate(() => !!document.querySelector('#upBook textarea.bookedit'));
      if (!editing) note(where, 'Edit opened no box in place');
      await page.fill('#upBook textarea.bookedit', 'The leak alarm shuts the water.');
      await page.evaluate(() => [...document.querySelectorAll('#upBook .bookeditrow button')]
        .find((b) => b.textContent === 'Save').click());
      await page.waitForTimeout(200);
      const sent = await page.evaluate(() => window.__posts.filter((x) => x.method === 'POST'));
      const edit = sent.find((x) => /house_book\/entry\/aaaaaaaaaaaa$/.test(x.url));
      if (!edit || edit.body.text !== 'The leak alarm shuts the water.') {
        note(where, `Save sent ${JSON.stringify(edit)}`);
      }
      // Add info on a chapter opens the box for that chapter, and blank asks
      // brAIn to fill it in.
      await page.evaluate(() => document.querySelector('#upBook .booksecadd').click());
      const dlg = await page.evaluate(() => ({
        open: document.querySelector('#bookAddModal').classList.contains('open'),
        title: document.querySelector('#bookAddTitle').textContent,
        ph: document.querySelector('#bookAddText').placeholder,
        go: document.querySelector('#bookAddGo').textContent,
      }));
      if (!dlg.open || !/Add to/.test(dlg.title)) note(where, `Add info opened ${JSON.stringify(dlg)}`);
      if (!/leave this blank/i.test(dlg.ph)) note(where, `the box says "${dlg.ph}"`);
      await page.click('#bookAddGo');
      await page.waitForTimeout(200);
      const adds = await page.evaluate(() => window.__posts.filter((x) => /house_book\/add$/.test(x.url)));
      if (!adds.length || adds[0].body.text !== '' || !adds[0].body.section) {
        note(where, `a blank chapter Add info sent ${JSON.stringify(adds)}`);
      }
    }
    if (process.env.UPKEEP_SHOT_DIR) {
      await page.evaluate(() => document.querySelectorAll('.modal.open').forEach((m) => m.classList.remove('open')));
      await page.screenshot({ path: path.join(process.env.UPKEEP_SHOT_DIR,
        `book-${width}-${state.replace(' ', '')}.png`), fullPage: true });
    }
    console.log(`${String(width).padStart(5)}  book (${state}): ${v.entries.length} entries  `
      + `presses ${labels.join(' · ')}`);
    await context.close();
  }
}

// A run in flight, said in words.
{
  const { context, page } = await open(1200, false, {
    ...ALL, book: { ...BOOK, running: true } }, 'housebook');
  await page.waitForFunction(() => /Writing the house book/.test(
    document.getElementById('upBook')?.textContent || ''), null,
    { timeout: 5000 }).catch(() => {});
  const v = await read(page);
  if (!/Writing the house book/.test(v.bookText)) {
    note('running', 'nothing on the page says the book is being written');
  }
  const run = v.bookButtons.find((b) => b.label === 'Add info');
  if (!run || !run.disabled) note('running', 'Add info is still pressable while the book is written');
  await context.close();
}
await browser.close();
if (failures.length) {
  console.error(`measure-upkeep: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nthe tidy, the updates and the house book can each be acted on from what they show');
