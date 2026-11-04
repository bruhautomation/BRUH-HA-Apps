// The house layer undoes a bad change by itself (panel/house_ui.py revert +
// panel/house-layer.js's health check), driven in a real browser over http,
// with the page's head rendered by the REAL house_ui.py. Holds:
//
//   * a new house.css that hides the header fails the page's check, and the
//     page asks for exactly that version to be taken back, then reloads ONCE
//     (a page still broken after the reload says so instead of looping);
//   * a new house.js that throws is taken back on its own: house.css, which
//     did nothing wrong, is not blamed;
//   * new versions that leave the page whole are confirmed, both of them;
//   * a version already confirmed (`good`) is not judged again: no verdict.
//
// The verdicts are recorded in the page instead of reaching a server: what is
// measured is what the page decides and asks for. Run with
// `node tests/manual/measure-house-undo.mjs` where `playwright` resolves.
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { stub } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const failures = [];
const note = (where, m) => failures.push(`${where}: ${m}`);
const index = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8').replaceAll('{{VERSION}}', 'test');
const TYPES = { '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

async function scenario(where, files, { confirmed = false } = {}) {
  const UI = fs.mkdtempSync(path.join(os.tmpdir(), 'house-undo-ui-'));
  const STATE = fs.mkdtempSync(path.join(os.tmpdir(), 'house-undo-state-'));
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(UI, name), text);
  const env = { ...process.env, BRAIN_HOUSE_UI_DIR: UI, BRAIN_HOUSE_STATE_DIR: STATE };
  if (confirmed) {
    // Mark every file's current version good, the way confirm() does.
    execFileSync('python3', ['-c', `
import sys; sys.path.insert(0, sys.argv[1])
import house_ui
for row in house_ui.listing():
    assert house_ui.confirm(row["name"], row["v"])
`, PANEL], { env });
  }
  const page = execFileSync('python3', [path.join(PANEL, 'house_ui.py'), 'on'], { input: index, env }).toString();
  let loads = 0;
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/') {
      loads += 1;
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(page);
      return;
    }
    const name = url.pathname.slice(1);
    const dir = (name === 'house.css' || name === 'house.js') ? UI : PANEL;
    const file = path.join(dir, path.basename(name));
    if (!fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'text/plain' });
    res.end(fs.readFileSync(file));
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const tab = await context.newPage();
  await tab.addInitScript(stub({}));
  // After the stub: record the page's verdicts in sessionStorage, which
  // survives the reload a revert asks for.
  await tab.addInitScript(() => {
    const inner = window.fetch;
    window.fetch = async (url, opts) => {
      if (String(url).includes('api/house/outcome')) {
        const seen = JSON.parse(sessionStorage.getItem('measure.outcomes') || '[]');
        const body = JSON.parse(opts.body);
        seen.push(body);
        sessionStorage.setItem('measure.outcomes', JSON.stringify(seen));
        const answer = body.outcome === 'revert' ? { reverted: true, restored: 'none' } : { confirmed: true };
        return new Response(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return inner(url, opts);
    };
  });
  await tab.goto(`http://127.0.0.1:${server.address().port}/`);
  await tab.waitForTimeout(9000);
  const outcomes = await tab.evaluate(() => JSON.parse(sessionStorage.getItem('measure.outcomes') || '[]'));
  await context.close();
  server.close();
  fs.rmSync(UI, { recursive: true, force: true });
  fs.rmSync(STATE, { recursive: true, force: true });
  return { outcomes, loads };
}

{
  const where = 'house.css hides the header';
  const { outcomes, loads } = await scenario(where, { 'house.css': 'header.topbar { display: none !important; }\n' });
  const reverts = outcomes.filter((o) => o.outcome === 'revert');
  if (!reverts.length) note(where, `no revert asked for (${JSON.stringify(outcomes)})`);
  else {
    if (reverts.some((o) => o.name !== 'house.css')) note(where, 'something other than house.css was blamed');
    if (!/topbar/.test(reverts[0].why)) note(where, `the reason does not name the header: "${reverts[0].why}"`);
    if (!reverts[0].v) note(where, 'the verdict does not name the version');
  }
  if (loads !== 2) note(where, `the page loaded ${loads} times; one reload was expected`);
}
{
  const where = 'house.js throws';
  const { outcomes } = await scenario(where, {
    'house.css': '.topbar { outline: 1px solid red; }\n',
    'house.js': "throw new Error('house boom');\n",
  });
  const reverts = outcomes.filter((o) => o.outcome === 'revert');
  // The recorded server never really takes the file away, so the one
  // reload meets the same version and asks again; it is never house.css.
  if (!reverts.length || reverts.some((o) => o.name !== 'house.js')) note(where, `expected house.js alone taken back: ${JSON.stringify(outcomes)}`);
  else if (!/house boom/.test(reverts[0].why)) note(where, `the reason does not carry the error: "${reverts[0].why}"`);
}
{
  const where = 'both fine';
  const { outcomes, loads } = await scenario(where, {
    'house.css': '.topbar { outline: 1px solid red; }\n',
    'house.js': "document.documentElement.dataset.houseRan = '1';\n",
  });
  const names = outcomes.filter((o) => o.outcome === 'confirm').map((o) => o.name).sort();
  if (names.join() !== 'house.css,house.js') note(where, `expected both confirmed: ${JSON.stringify(outcomes)}`);
  if (loads !== 1) note(where, `the page reloaded (${loads} loads)`);
}
{
  const where = 'already confirmed';
  const { outcomes } = await scenario(where, { 'house.css': 'header.topbar { display: none !important; }\n' }, { confirmed: true });
  if (outcomes.length) note(where, `a confirmed version was judged again: ${JSON.stringify(outcomes)}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-house-undo: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('measure-house-undo: a header-hiding house.css and a throwing house.js are taken back (one reload), good versions confirmed, confirmed ones left alone');
