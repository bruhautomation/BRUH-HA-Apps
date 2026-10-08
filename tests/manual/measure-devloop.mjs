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
            issue_url: 'https://github.com/me/brain-house-reports/issues/12' }],
};

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const body = p.includes('api/devloop') ? ${JSON.stringify(PAYLOAD)} : {};
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
};`;

const problems = [];
const note = (where, what) => problems.push(`${where}: ${what}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });

for (const [width, touch] of [[390, true], [1200, false]]) {
  const where = `${width}px`;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
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
  await page.evaluate(() => showSettingsSection('diagnostics'));
  await page.evaluate(() => { document.querySelector('#setDiagDeveloper').open = true; });
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
  if (m.rows.length !== 7) note(where, `${m.rows.length} stream rows, expected 7 (every stream but What do you want to fix?)`);
  m.rows.forEach((r, i) => {
    if (!r.toggle || !r.run) note(where, `stream row ${i} is missing its switch or its Run`);
    if (r.hours.join(',') !== '0,1,3,6,12,24,168') note(where, `stream row ${i} offers hours ${r.hours}`);
  });
  if (!m.look) note(where, 'the What do you want to fix? box or its Send is missing');
  if (!m.caps) note(where, 'the daily caps were not painted');
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
console.log('measure-devloop: OK at 390 and 1200px');
