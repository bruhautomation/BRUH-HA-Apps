// measure-devloop.mjs — ⚙ › Diagnostics › Developer › Help develop brAIn,
// switched ON. measure-settings drives the dialog with the loop off, which
// hides every control this section has; this drives the real markup and
// the real `paintDevloop` with a payload shaped like `_devloop_payload`.
//
// Fails on: a stream row missing its switch, schedule or Run; a select that
// does not offer the server's hours; the What do you want to fix? box or the caps missing;
// a target under 44px or a text control under 16px on touch; sideways
// scroll; a page error.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '../../brain/panel');
const NOW = Math.floor(Date.now() / 1000);

const PAYLOAD = {
  settings: {
    enabled: true, review: false, repo: 'me/brain-house-reports',
    streams: { faults: true, scorecard: true, wrongs: true, unmet: false,
               snapshot: false, gaps: true, ideas: false, look: true },
    schedule: { faults: 1, scorecard: 24, wrongs: 24, unmet: 24, snapshot: 168,
                gaps: 168, ideas: 168, look: 0 },
    max_issues_per_day: 10, max_runs_per_day: 4,
  },
  streams: [
    ['faults', 'Faults: what is broken, from the fault list in ⚙ › Diagnostics'],
    ['scorecard', 'Scorecard: how right each rule was, for this release'],
    ['wrongs', 'Wrongs: rules you keep marking Wrong, with your reasons'],
    ['unmet', 'Unmet requests: things you asked the chat for that brAIn could not do'],
    ['snapshot', 'House shape: an aliased outline of this house, for UI audits'],
    ['gaps', 'Gaps: where brAIn falls short on this house (one Claude run)'],
    ['ideas', 'Ideas: features this house would use (one Claude run)'],
    ['look', 'What do you want to fix?: your words, turned into an issue (one Claude run each)'],
  ].map(([name, label]) => ({ name, label })),
  hours: [0, 1, 3, 6, 12, 24, 168],
  caps: { max_issues_per_day: [0, 50], max_runs_per_day: [0, 24] },
  looks: { running: '', last: null },
  token_set: true,
  status: { last_run: { faults: NOW - 600 }, runs_left: 3, error: '' },
  queue: [{ fp: '0123456789abcdef', stream: 'faults', where: 'Daemons',
            what: 'not running: automation_listener', state: 'sent', seen: 4,
            last_seen: NOW - 600, issue: 12,
            issue_url: 'https://github.com/me/brain-house-reports/issues/12' },
          // Pressed Send and held by the day's cap: it must say so, and
          // what ends the wait, never promise a send.
          { fp: 'fedcba9876543210', stream: 'faults', where: 'Runs',
            what: 'card ended timeout 3 times', state: 'ready', seen: 2,
            last_seen: NOW - 300 },
          // Held because sending failed: the error is the reason.
          { fp: 'abcdefabcdefabcd', stream: 'faults', where: 'Checks',
            what: 'could not look', state: 'ready', seen: 1,
            last_seen: NOW - 200, error: 'GitHub answered 502' },
          // Waiting for a press: tickable, and sent in one batch.
          { fp: '1111222233334444', stream: 'gaps', where: 'Gaps',
            what: 'the brief never names the room', state: 'pending', seen: 1,
            last_seen: NOW - 100 },
          // Fixed by the cloud, and one somebody archived: off the default
          // view, each under its own pill.
          { fp: '5555666677778888', stream: 'look', where: 'Fix: settings',
            what: 'settings too crowded', state: 'sent', seen: 1, verdict: 'fixed',
            last_seen: NOW - 5000, issue: 9,
            issue_url: 'https://github.com/me/brain-house-reports/issues/9' },
          { fp: '9999aaaabbbbcccc', stream: 'faults', where: 'Old',
            what: 'archived fault', state: 'sent', seen: 1, archived: true,
            archived_why: 'you', last_seen: NOW - 9000 }],
  held: { limit: 10, today: 10, full: true, frees_at: NOW + 3 * 3600 },
};

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.__posts = [];
window.fetch = async (url, opts) => {
  const p = String(url);
  if (opts && opts.method === 'POST') window.__posts.push({ url: p, body: opts.body || '' });
  const body = p.includes('api/devloop') ? ${JSON.stringify(PAYLOAD)} : {};
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
};`;

const problems = [];
const note = (where, what) => problems.push(`${where}: ${what}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });

for (const [width, touch, scheme] of [[390, true, 'light'], [390, true, 'dark'],
                                      [1200, false, 'light'], [1200, false, 'dark']]) {
  const where = `${width}px ${scheme}`;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch, colorScheme: scheme });
  const page = await context.newPage();
  page.on('pageerror', (e) => {
    if (/devloop|devStreams|devLook|devCap/i.test(e.stack || e.message)) {
      note(where, `page error: ${e.message}`);
    }
  });
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.waitForFunction(() => typeof openSettings === 'function');
  await page.evaluate(() => openSettings());
  await page.waitForSelector('#setModal.open');
  await page.evaluate(() => showSettingsSection('developer'));
  await page.evaluate(() => loadDevloop());
  await page.waitForFunction(() => !document.querySelector('#devloopBody').hidden,
    null, { timeout: 4000 }).catch(() => note(where, 'the section never opened'));

  const m = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#devStreams .setrow')];
    const visible = (el) => el && el.offsetParent !== null;
    const targets = [...document.querySelectorAll(
      '#devloopBody button, #devloopBody select, #devloopBody input')].filter(visible);
    const texts = [...document.querySelectorAll(
      '#devloopBody input[type="text"], #devloopBody input[type="password"], '
      + '#devloopBody input[type="number"], #devloopBody select')].filter(visible);
    return {
      rows: rows.map((r) => ({
        toggle: !!r.querySelector('[data-dev-stream]'),
        hours: [...(r.querySelector('[data-dev-hours]')?.options || [])].map((o) => o.value),
        run: !!r.querySelector('[data-dev-run]'),
        left: Math.round(r.getBoundingClientRect().left),
        // The switch is beside its name, in the card's right-hand column.
        gap: (() => {
          const t = r.querySelector('[data-dev-stream]');
          const b = r.querySelector('label b');
          return t && b ? Math.round(t.getBoundingClientRect().left - b.getBoundingClientRect().left) : 9999;
        })(),
        nameRight: (() => {
          const t = r.querySelector('[data-dev-stream]');
          const b = r.querySelector('label > span');
          return t && b ? t.getBoundingClientRect().left >= b.getBoundingClientRect().right - 0.5 : false;
        })(),
      })),
      look: visible(document.querySelector('#devLook')) && visible(document.querySelector('#devLookRun')),
      caps: document.querySelector('#devCapIssues').value === '10'
        && document.querySelector('#devCapRuns').value === '4',
      // A checkbox's target is its whole label, which is what a thumb hits.
      small: targets.filter((t) => (t.type === 'checkbox'
          ? (t.closest('label') || t) : t).getBoundingClientRect().height < 44)
        .map((t) => t.id || t.getAttribute('data-dev-run') || t.getAttribute('data-dev-hours') || t.tagName),
      tiny: texts.filter((t) => parseFloat(getComputedStyle(t).fontSize) < 16)
        .map((t) => t.id || t.tagName),
      sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });
  // A held report says why and what ends the wait; "will be sent" read
  // as brAIn stalling.
  const queue = await page.evaluate(() => [...document.querySelectorAll('#devQueue .drow')]
    .map((r) => ({ state: ((r.querySelector('.dk')?.textContent.trim() || '') + ' '
                     + (r.querySelector('.devheld')?.textContent.trim() || '')).trim(),
                   what: r.querySelector('.dv')?.textContent || '' })));
  if (queue.some((q) => /will be sent/.test(q.state))) note(where, 'a row still says "will be sent"');
  const stateOf = (re) => (queue.find((q) => re.test(q.what)) || {}).state || '';
  const capped = stateOf(/card ended timeout/);
  if (!/limit of 10 new issues/.test(capped) || !/Daily limits/.test(capped)
      || !/after/.test(capped)) {
    note(where, `a report held by the cap reads "${capped}"`);
  }
  const failed = stateOf(/could not look/);
  if (!/GitHub answered 502/.test(failed)) note(where, `a failed send reads "${failed}"`);
  if (m.rows.length !== 7) note(where, `${m.rows.length} stream rows, expected 7 (every stream but What do you want to fix?)`);
  // Seven cards: two columns on a wide screen, one on a phone, each with
  // its switch to the right of its name and never a page's width from it.
  const columns = new Set(m.rows.map((r) => r.left)).size;
  if (width >= 900 && columns !== 2) note(where, `the streams are in ${columns} column(s), not 2`);
  if (width < 600 && columns !== 1) note(where, `the streams are in ${columns} columns on a phone`);
  m.rows.forEach((r, i) => {
    if (!r.nameRight) note(where, `stream row ${i}'s switch is not to the right of its name`);
    if (r.gap > 360) note(where, `stream row ${i}'s switch is ${r.gap}px from its name`);
    if (!r.toggle || !r.run) note(where, `stream row ${i} is missing its switch or its Run`);
    if (r.hours.join(',') !== '0,1,3,6,12,24,168') note(where, `stream row ${i} offers hours ${r.hours}`);
  });
  if (!m.look) note(where, 'the What do you want to fix? box or its Send is missing');
  if (!m.caps) note(where, 'the daily caps were not painted');
  // The reports list: a status in words on every row, filters by status
  // and by kind, fixed and archived rows off the default view, Archive on
  // every row, a batch Send over ticked rows, the issue link, and the line
  // saying where what was done is written (report #167).
  const rl = await page.evaluate(() => {
    const q = document.querySelector('#devQueue');
    const rows = () => [...q.querySelectorAll('.drow')];
    const out = {
      statusPills: q.querySelectorAll('[data-dev-status]').length,
      kindPills: q.querySelectorAll('[data-dev-kind]').length,
      words: rows().map((r) => r.querySelector('.devstatus')?.textContent.trim() || ''),
      shown: rows().map((r) => r.dataset.fp),
      archive: rows().every((r) => r.querySelector('[data-dev-archive], [data-dev-unarchive]')),
      link: !!q.querySelector('a[href*="/issues/12"]'),
      hint: /written on its issue/.test(q.textContent),
      batch: !!q.querySelector('[data-dev-send-picked]'),
      archiveAll: !!q.querySelector('[data-dev-archive-shown]'),
    };
    q.querySelector('[data-dev-status="fixed"]')?.click();
    out.fixed = rows().map((r) => r.dataset.fp);
    q.querySelector('[data-dev-status="archived"]')?.click();
    out.archived = rows().map((r) => r.dataset.fp);
    out.unarchive = !!q.querySelector('[data-dev-unarchive]');
    q.querySelector('[data-dev-status="active"]')?.click();
    for (const fp of ['1111222233334444', 'abcdefabcdefabcd']) {
      const box = q.querySelector(`[data-dev-pick="${fp}"]`);
      if (box) { box.checked = true; box.dispatchEvent(new Event('change', { bubbles: true })); }
    }
    q.querySelector('[data-dev-send-picked]')?.click();
    return out;
  });
  await page.waitForTimeout(200);
  const posts = await page.evaluate(() => window.__posts);
  if (rl.statusPills < 4 || rl.kindPills < 2) note(where, 'the reports list has no status and kind filters');
  const WORDS = /^(Open|Open · waiting for you|Sent|Sent · no longer seen|Fixed|Declined|Not brAIn's|Duplicate|Closed|Never sent|Archived|Archived · no longer seen)$/;
  rl.words.forEach((w, i) => { if (!WORDS.test(w)) note(where, `report ${i} reads "${w}", not a status in words`); });
  if (rl.shown.includes('5555666677778888') || rl.shown.includes('9999aaaabbbbcccc')) {
    note(where, 'a fixed or archived report is on the default view');
  }
  if (!rl.fixed.includes('5555666677778888')) note(where, 'the Fixed filter does not show the fixed report');
  if (!rl.archived.includes('9999aaaabbbbcccc') || !rl.unarchive) note(where, 'the Archived filter has no Unarchive');
  if (!rl.archive || !rl.archiveAll) note(where, 'a report has no Archive, or there is no Archive all shown');
  if (!rl.link) note(where, 'a sent report does not link to its issue');
  if (!rl.hint) note(where, 'nothing says what was done is written on the issue');
  const batch = posts.find((pp) => /api\/devloop\/send$/.test(pp.url));
  if (!rl.batch || !batch) note(where, 'no batch Send for ticked reports');
  else {
    const fps = (JSON.parse(batch.body || '{}').fps || []).sort().join(',');
    if (fps !== '1111222233334444,abcdefabcdefabcd') note(where, `batch Send posted ${fps}`);
  }

  // Every switch on the page is the Settings switch: as wide as the
  // other sections' (`--toggle-w` × `--toggle-h`), wider than tall, to the
  // right of its words on the same row, and on reads unlike off. A touch
  // rule once gave every input here a 44px min-height, which stood each
  // switch on end (report: "toggles vertical or weird looking").
  const sw = await page.evaluate(() => {
    // The size every Settings switch is drawn at: the dialog's own
    // `--toggle-w`/`--toggle-h`, which a rule that stretches one input
    // does not change.
    const root = getComputedStyle(document.querySelector('#setModal'));
    const px = (v) => parseFloat(v);
    const want = { w: px(root.getPropertyValue('--toggle-w')), h: px(root.getPropertyValue('--toggle-h')) };
    const sec = document.querySelector('#setsecDeveloper') || document.querySelector('#devloopBody');
    const toggles = [...sec.querySelectorAll('input[type="checkbox"]')]
      .filter((t) => t.offsetParent && (t.classList.contains('tog') || t.closest('label.check, label.bigcheck')));
    const rows = toggles.map((t) => {
      const r = t.getBoundingClientRect();
      const label = t.closest('label');
      const words = label && label.querySelector(':scope > span, b');
      const wr = words ? words.getBoundingClientRect() : null;
      return { id: t.id || t.getAttribute('data-dev-stream') || '?', w: r.width, h: r.height,
               right: !wr || r.left >= wr.right - 0.5,
               sameRow: !wr || (r.top < wr.bottom && r.bottom > wr.top),
               bg: getComputedStyle(t).backgroundColor, on: t.checked };
    });
    return { want, rows };
  });
  const ons = new Set(sw.rows.filter((r) => r.on).map((r) => r.bg));
  const offs = new Set(sw.rows.filter((r) => !r.on).map((r) => r.bg));
  if ([...ons].some((c) => offs.has(c))) note(where, 'a switch reads the same on as off');
  if (sw.rows.length < 10) note(where, `only ${sw.rows.length} switches found on Developer`);
  sw.rows.forEach((r) => {
    if (r.h >= r.w) note(where, `switch ${r.id} stands on end: ${Math.round(r.w)}x${Math.round(r.h)}`);
    if (Math.abs(r.w - sw.want.w) > 0.5 || Math.abs(r.h - sw.want.h) > 0.5) {
      note(where, `switch ${r.id} is ${Math.round(r.w)}x${Math.round(r.h)}, not the Settings switch's ${sw.want.w}x${sw.want.h}`);
    }
    if (!r.right || !r.sameRow) note(where, `switch ${r.id} is not to the right of its words on one row`);
  });
  if (touch && m.small.length) note(where, `targets under 44px: ${m.small.join(', ')}`);
  if (touch && m.tiny.length) note(where, `text controls under 16px: ${m.tiny.join(', ')}`);
  if (m.sideways) note(where, 'the page scrolls sideways');
  await context.close();
}
await browser.close();

if (problems.length) {
  console.error('measure-devloop: FAILED');
  for (const p of problems) console.error('  ' + p);
  process.exit(1);
}
console.log('measure-devloop: OK at 390 and 1200px, light and dark');
