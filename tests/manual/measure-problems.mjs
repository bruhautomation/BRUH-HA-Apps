// Drive the ⚙ dialog's Problems section and assert it can be used.
//
// The failure this exists to prevent is the one every report surface in
// this add-on has had: a list that renders and cannot be acted on. So the
// checks are about what a row OFFERS as much as where it sits:
//
//   * every report renders one row with its own checkbox, its headline, a
//     repeat count where there is one, and a delete — a row without its
//     checkbox cannot be copied with the others, which is the whole reason
//     there are checkboxes.
//   * Copy selected sends exactly the ticked names, and Copy all sends all
//     of them, to /api/reports/copy — the panel asks the server for the
//     combined text rather than stitching files itself.
//   * Write a report now POSTs /api/reports/run and the list refreshes.
//   * ✕ on a row DELETEs that name and the row goes.
//   * the empty state says, in words, when a file would appear.
//   * on a phone every control clears the touch floor, and nothing scrolls
//     sideways.
//
// Drives the panel's REAL renderer (reportRows / loadReports in app.js)
// behind a stubbed fetch. A copy of the renderer in this file would only
// ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 44;

const NOW = Math.floor(Date.now() / 1000);
const REPORTS = [
  { name: '2026-09-08-0912-run.txt', ts: NOW - 1800, kind: 'run',
    headline: 'insight run ended timeout: took too long', count: 3, bytes: 4210 },
  { name: '2026-09-08-0340-health.txt', ts: NOW - 21600, kind: 'health',
    headline: 'health went ok → degraded: the automation listener is not running',
    count: 1, bytes: 3980 },
  { name: '2026-09-07-2201-notify.txt', ts: NOW - 60000, kind: 'notify',
    headline: 'notification via mobile_app_phone failed', count: 1, bytes: 2210 },
];

const STUB = `
window.__calls = [];
window.__reports = ${JSON.stringify(REPORTS)};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const method = (opts && opts.method) || 'GET';
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  const text = (body) => new Response(body, {
    status: 200, headers: { 'Content-Type': 'text/plain' } });
  if (p.endsWith('api/reports')) {
    return answer({ reports: window.__empty ? [] : window.__reports,
                    dir: '/share/brain/reports', available: true, max: 30 });
  }
  if (p.endsWith('api/reports/copy')) {
    const body = JSON.parse(opts.body);
    window.__calls.push({ what: 'copy', names: body.names });
    return text(body.names.map((n) => '==== ' + n + ' ====\\n(text)').join('\\n'));
  }
  if (p.endsWith('api/reports/run')) {
    window.__calls.push({ what: 'run' });
    const made = { name: '2026-09-08-1200-manual.txt', ts: Math.floor(Date.now() / 1000),
                   kind: 'manual', headline: 'report requested', count: 1, bytes: 90000 };
    window.__reports = [made, ...window.__reports];
    return answer({ name: made.name, path: '/share/brain/reports/' + made.name });
  }
  const one = p.match(/api\\/reports\\/([^/?]+)$/);
  if (one) {
    const name = decodeURIComponent(one[1]);
    if (method === 'DELETE') {
      window.__calls.push({ what: 'delete', name });
      window.__reports = window.__reports.filter((r) => r.name !== name);
      return answer({ deleted: true });
    }
    return text('2026-09-08 12:00 · brAIn test · ' + name + '\\n\\nWhat happened:\\n(text)');
  }
  if (p.endsWith('api/auth')) {
    return answer({ authenticated: true, type: 'oauth_token', source: 'local',
      saved_at: 1756000000, can_share: true,
      auth_check: { state: 'ok', error: '', checked_at: Math.floor(Date.now() / 1000),
                    running: false },
      recheck_seconds: 21600, shared_path: '/config/.brain/secrets/claude_auth.json',
      stores: { local: { present: true, saved_at: 1756000000 },
                cli: { present: false }, shared: { present: false } } });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth_token',
      auth_source: 'local', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: { onboarded: true }, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/onboarding')) return answer({ state: 'done', onboarded: true });
  if (p.includes('api/settings')) return answer({ settings: {}, models: [], usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/diagnostics')) return answer({});
  if (p.includes('api/capture')) return answer({ captures: [], enabled: false, max_files: 50 });
  if (p.includes('api/doctor')) return answer({});
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

// A refused clipboard leaves the text selected in a fixed textarea for the
// person to copy by hand. Headless may or may not refuse; either way the
// box has to go before the next press — and NOT via Escape, which is also
// the dialog's own close key.
const clearCopyBox = (page) => page.evaluate(() => {
  document.querySelectorAll('body > textarea').forEach((t) => t.remove());
});

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const width of WIDTHS) {
  const touch = width <= 430;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch,
  });
  const page = await context.newPage();
  const where = `${width}px`;
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);

  await page.click('#settingsBtn');
  await page.waitForSelector('#probBody .prow');

  const m = await page.evaluate((min) => {
    const body = document.querySelector('#probBody');
    const bodyBox = body.getBoundingClientRect();
    const rows = [...body.querySelectorAll('.prow')].map((r) => {
      const box = r.getBoundingClientRect();
      const check = r.querySelector('input.probcheck');
      const pick = r.querySelector('.probpick');
      const del = r.querySelector('.probdel');
      return {
        name: r.dataset.report,
        hasCheck: !!check,
        checkValue: check ? check.value : '',
        headline: (r.querySelector('.probhead') || {}).textContent || '',
        count: (r.querySelector('.probcount') || {}).textContent || '',
        when: (r.querySelector('.probwhen') || {}).textContent || '',
        pickH: pick ? Math.round(pick.getBoundingClientRect().height) : 0,
        delW: del ? Math.round(del.getBoundingClientRect().width) : 0,
        delH: del ? Math.round(del.getBoundingClientRect().height) : 0,
        right: box.right,
      };
    });
    const buttons = [...document.querySelectorAll('.probbtns .btn')].map((b) => ({
      label: b.textContent.trim(),
      h: Math.round(b.getBoundingClientRect().height),
      w: Math.round(b.getBoundingClientRect().width),
      visible: b.getBoundingClientRect().width > 0,
    }));
    return {
      rows, buttons, bodyRight: bodyBox.right,
      docWidth: document.documentElement.scrollWidth,
      hint: (document.querySelector('#probBody + .probbtns') ? 'ok' : 'missing'),
    };
  }, MIN_TARGET);

  if (m.rows.length !== REPORTS.length) {
    note(where, `${m.rows.length} rows for ${REPORTS.length} reports`);
  }
  for (const row of m.rows) {
    if (!row.hasCheck) note(where, `${row.name} has no checkbox`);
    if (row.checkValue !== row.name) {
      note(where, `${row.name}'s checkbox carries "${row.checkValue}"`);
    }
    if (!row.headline.trim()) note(where, `${row.name} renders no headline`);
    if (!row.when.trim()) note(where, `${row.name} renders no time`);
    if (!row.delW) note(where, `${row.name} has no delete`);
    if (row.right > m.bodyRight + 0.5) note(where, `${row.name} overflows the list`);
    if (touch && row.pickH < MIN_TARGET) {
      note(where, `${row.name}'s row is ${row.pickH}px, under ${MIN_TARGET}`);
    }
    if (touch && (row.delH < MIN_TARGET || row.delW < MIN_TARGET)) {
      note(where, `${row.name}'s ✕ is ${row.delW}×${row.delH}, under ${MIN_TARGET}`);
    }
  }
  const repeated = m.rows.find((r) => r.name === REPORTS[0].name);
  if (repeated && !/×3/.test(repeated.count)) {
    note(where, `the repeated report does not show its count ("${repeated.count}")`);
  }
  const labels = m.buttons.map((b) => b.label);
  for (const want of ['Copy selected', 'Copy all', 'Write a report now']) {
    if (!labels.includes(want)) note(where, `no "${want}" button`);
  }
  for (const b of m.buttons) {
    if (!b.visible) note(where, `"${b.label}" is not visible`);
    if (touch && b.h < MIN_TARGET) note(where, `"${b.label}" is ${b.h}px, under ${MIN_TARGET}`);
  }
  if (m.docWidth > width) note(where, `page scrolls sideways (${m.docWidth}px)`);

  // ---- the actions actually reach the server -----------------------------
  // Inside a try so a structural failure above (a row with no checkbox)
  // reports as itself rather than as a timeout on the press that needed it.
  try {
  await page.check(`#probBody .probcheck[value="${REPORTS[0].name}"]`);
  await page.check(`#probBody .probcheck[value="${REPORTS[2].name}"]`);
  await page.click('#probCopySel');
  await page.waitForFunction(() => window.__calls.some((c) => c.what === 'copy'));
  await clearCopyBox(page);
  let calls = await page.evaluate(() => window.__calls);
  const sel = calls.find((c) => c.what === 'copy');
  if (!sel || sel.names.join() !== [REPORTS[0].name, REPORTS[2].name].join()) {
    note(where, `Copy selected sent ${JSON.stringify(sel && sel.names)}`);
  }
  await page.evaluate(() => { window.__calls = []; });
  await page.click('#probCopyAll');
  await page.waitForFunction(() => window.__calls.some((c) => c.what === 'copy'));
  await clearCopyBox(page);
  calls = await page.evaluate(() => window.__calls);
  const all = calls.find((c) => c.what === 'copy');
  if (!all || all.names.length !== REPORTS.length) {
    note(where, `Copy all sent ${JSON.stringify(all && all.names)}`);
  }

  await page.evaluate(() => { window.__calls = []; });
  await page.click('#probWrite');
  await page.waitForFunction(() => document.querySelectorAll('#probBody .prow').length === 4);
  calls = await page.evaluate(() => window.__calls);
  if (!calls.some((c) => c.what === 'run')) note(where, 'Write a report now sent nothing');

  await page.evaluate(() => { window.__calls = []; });
  await page.click(`#probBody [data-prob-del="${REPORTS[1].name}"]`);
  await page.waitForFunction(
    (name) => !document.querySelector(`#probBody .prow[data-report="${name}"]`),
    REPORTS[1].name);
  calls = await page.evaluate(() => window.__calls);
  if (!calls.some((c) => c.what === 'delete' && c.name === REPORTS[1].name)) {
    note(where, '✕ did not delete the row it was on');
  }
  } catch (e) {
    note(where, `driving the controls failed: ${String(e.message).split('\n')[0]}`);
  }

  await context.close();

  // ---- the empty state says when a file would appear ---------------------
  const empty = await browser.newContext({ viewport: { width, height: 900 } });
  const page2 = await empty.newPage();
  page2.on('pageerror', (e) => note(where, `empty: page error: ${e.message}`));
  await page2.addInitScript(STUB);
  await page2.addInitScript('window.__empty = true;');
  await page2.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page2.click('#settingsBtn');
  await page2.waitForSelector('#probBody .probempty');
  const emptyText = await page2.$eval('#probBody', (el) => el.textContent);
  if (!/No problems recorded/.test(emptyText) || !/one text file appears here/.test(emptyText)) {
    note(where, `empty state says "${emptyText.trim()}"`);
  }
  await empty.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-problems: FAIL');
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log(`measure-problems: OK across ${WIDTHS.join(', ')}px`);
