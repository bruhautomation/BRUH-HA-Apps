/* Playwright measure for BRUH Task Manager's panel.
 *
 * Boot two demo panels first — one at Level 2, one at Level 1 with
 * Protection mode on — each mounted under an ingress-shaped prefix:
 *   python3 tests/manual/task_manager_demo_panel.py /tmp/tm-l2 8103 --level2 &
 *   python3 tests/manual/task_manager_demo_panel.py /tmp/tm-l1 8105 &
 *   node tests/manual/measure-task-manager.mjs
 *
 * What it drives, because each is a thing the page can get wrong that the
 * server's tests cannot see:
 *   - every app row and every process group actually renders, at 1200 and at
 *     390 on touch, with no sideways scroll and no control under 40px;
 *   - End process asks, then (for a process that ignored the ask) offers
 *     Force end only once the grace has passed, and the process goes;
 *   - refused processes say WHY in words, not by a missing button alone;
 *   - at Level 1 the Processes tab explains Level 2 instead of being empty,
 *     and switching Level 2 on from Settings asks first, saves, and then
 *     says the next step is Protection mode — the one step the add-on
 *     cannot take itself.
 *
 * Set SHOTS=1 to keep a screenshot per state (in SHOTS_DIR, default /tmp). */
import { chromium } from 'playwright';

const PREFIX = process.env.DEMO_PREFIX || '/api/hassio_ingress/tmDemoToken01';
const L2 = process.env.PANEL_URL || `http://127.0.0.1:8103${PREFIX}/`;
const L1 = process.env.PANEL_URL_L1 || `http://127.0.0.1:8105${PREFIX}/`;
const SHOTS = process.env.SHOTS === '1';
const SHOTS_DIR = process.env.SHOTS_DIR || '/tmp';

const b = await chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] }
    : { args: ['--no-sandbox'] });
const problems = [];
const fail = (where, what) => problems.push(`${where}: ${what}`);

const audit = (width) => {
  const out = [];
  if (document.documentElement.scrollWidth > width + 1)
    out.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${width})`);
  for (const n of document.querySelectorAll('button, .tab, input, select, textarea, a.btn')) {
    const r = n.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (n.closest('dialog:not([open])')) continue;
    if (n.type === 'checkbox') continue;
    if (r.height < 40) out.push(`${n.id || n.textContent.trim() || n.className} is ${r.height.toFixed(0)}px tall`);
    if (r.right > width + 1) out.push(`${n.id || n.textContent.trim()} ends at ${r.right.toFixed(0)}px`);
  }
  return out;
};

async function open(url, width, touch) {
  const ctx = await b.newContext({
    viewport: { width, height: touch ? 800 : 900 },
    hasTouch: touch, isMobile: touch, deviceScaleFactor: touch ? 2 : 1,
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/process/')) errors.push(`${r.status()} ${r.url()}`); });
  await page.goto(url, { waitUntil: 'networkidle' });
  const styled = await page.evaluate(() => getComputedStyle(document.querySelector('.top')).position);
  if (styled !== 'sticky') fail(`${width}`, 'the stylesheet did not load under the ingress prefix');
  return { ctx, page, errors };
}

async function shot(page, name) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS_DIR}/tm-${name}.png`, fullPage: true });
}

async function tab(page, view) {
  await page.click(`.tab[data-view="${view}"]`);
  await page.waitForTimeout(300);
}

/* -- Level 2 --------------------------------------------------------------- */
for (const [width, touch] of [[1200, false], [390, true]]) {
  const where = `L2 ${width}`;
  const { ctx, page, errors } = await open(L2, width, touch);
  try {
    await page.waitForFunction(() => document.querySelectorAll('#appList .app').length >= 8, null, { timeout: 15000 });
    await page.waitForFunction(() => /%/.test(document.querySelector('#mCpu').textContent), null, { timeout: 15000 });
    const badge = await page.textContent('#levelBadge');
    if (!/Level 2/.test(badge)) fail(where, `the badge says "${badge}"`);
    const first = await page.textContent('#appList .app strong');
    if (first !== 'Studio Code Server') fail(where, `the busiest app is not first (${first})`);
    const stopBtn = await page.$('#appList .app .btn.danger');
    if (!stopBtn) fail(where, 'no Stop button on a started app');
    for (const p of await page.evaluate(audit, width)) fail(`${where} apps`, p);
    await shot(page, `apps-${width}`);

    // Restart asks first and says what it costs.
    await page.click('#appList .app:has-text("Mosquitto broker") button:has-text("Restart")');
    await page.waitForSelector('#confirm[open]');
    const lines = await page.$$eval('#confirmLines li', (ls) => ls.map((l) => l.textContent));
    if (!lines.some((l) => /mqtt/.test(l))) fail(where, `the restart dialog does not name the integration that talks to it: ${lines.join(' | ')}`);
    await shot(page, `confirm-${width}`);
    await page.click('#confirm button[value="go"]');
    await page.waitForFunction(() => /restarted/.test(document.querySelector('#toast').textContent), null, { timeout: 15000 });

    await tab(page, 'processes');
    await page.waitForFunction(() => document.querySelectorAll('#procList .group').length >= 6, null, { timeout: 15000 });
    const kernelShown = await page.$('#procList .group[data-group="kernel"]');
    if (kernelShown) fail(where, 'kernel threads are shown without being asked for');
    for (const p of await page.evaluate(audit, width)) fail(`${where} processes`, p);
    const coreWhy = await page.evaluate(() => {
      const g = document.querySelector('#procList .group[data-group="core"]');
      return g ? g.querySelector('.gwhy')?.textContent || '' : 'missing';
    });
    if (!/Restart/.test(coreWhy)) fail(where, `Home Assistant's processes do not say why they cannot be ended: "${coreWhy}"`);

    if (width === 1200) {
      // End the stubborn process: asked, then Force end once the grace passes.
      const group = '#procList .group[data-group="addon:a0d7b954_vscode"]';
      if (!(await page.$(`${group}[open]`))) await page.click(`${group} > summary`);
      await shot(page, `processes-${width}`);
      const row = `${group} .proc:has(.pid:text-is("pid 602"))`;
      await page.click(`${row} button:has-text("End")`);
      await page.waitForSelector('#confirm[open]');
      await page.click('#confirm button[value="go"]');
      await page.waitForFunction(() => /still running/.test(document.querySelector('#toast').textContent), null, { timeout: 15000 });
      await page.waitForSelector(`${row} button:has-text("Force end in")`, { timeout: 10000 });
      await page.waitForSelector(`${row} button:text-is("Force end")`, { timeout: 20000 });
      await page.click(`${row} button:text-is("Force end")`);
      await page.waitForSelector('#confirm[open]');
      await page.click('#confirm button[value="go"]');
      await page.waitForFunction(() => /has ended/.test(document.querySelector('#toast').textContent), null, { timeout: 15000 });
    }

    await tab(page, 'settings');
    for (const p of await page.evaluate(audit, width)) fail(`${where} settings`, p);
    const done = await page.$$eval('#l2Steps li.done', (ls) => ls.length);
    if (done !== 3) fail(where, `${done} of 3 Level 2 steps are ticked on an active Level 2`);
    await shot(page, `settings-${width}`);
  } catch (e) {
    fail(where, String(e).split('\n')[0]);
    await shot(page, `failure-l2-${width}`);
  }
  for (const e of errors) fail(where, e);
  await ctx.close();
}

/* -- Level 1 --------------------------------------------------------------- */
for (const [width, touch] of [[1200, false], [390, true]]) {
  const where = `L1 ${width}`;
  const { ctx, page, errors } = await open(L1, width, touch);
  try {
    await page.waitForFunction(() => document.querySelectorAll('#appList .app').length >= 8, null, { timeout: 15000 });
    const badge = await page.textContent('#levelBadge');
    if (!/Level 1/.test(badge)) fail(where, `the badge says "${badge}"`);
    if (await page.$('#appList .app button:has-text("Processes")')) fail(where, 'a Processes button at Level 1');
    await tab(page, 'processes');
    if (await page.isHidden('#procOff')) fail(where, 'the Processes tab does not explain Level 2');
    await shot(page, `l1-processes-${width}`);
    await tab(page, 'settings');
    if (!(await page.isDisabled('#optEnding'))) fail(where, 'Allow ending is offered while Level 2 is off');
    for (const p of await page.evaluate(audit, width)) fail(`${where} settings`, p);
    await shot(page, `l1-settings-${width}`);
    if (width === 1200) {
      await page.click('#optProcessView');
      await page.waitForSelector('#confirm[open]');
      const lines = await page.$$eval('#confirmLines li', (ls) => ls.map((l) => l.textContent).join(' '));
      if (!/Protection mode/.test(lines)) fail(where, 'turning Level 2 on does not say Protection mode has to be turned off');
      await page.click('#confirm button[value="go"]');
      await page.waitForFunction(() => /Protection mode is still on/.test(document.querySelector('#l2Sentence').textContent), null, { timeout: 15000 });
      const ticked = await page.$$eval('#l2Steps li.done', (ls) => ls.map((l) => l.dataset.step));
      if (ticked.join() !== 'option') fail(where, `after switching on, the ticked steps are ${ticked.join() || 'none'}`);
      await shot(page, `l1-switched-on-${width}`);
      // Put it back, so the next run starts from Level 1 again.
      await page.click('#optProcessView');
      await page.waitForFunction(() => /^Level 1/.test(document.querySelector('#l2Sentence').textContent), null, { timeout: 15000 });
    }
  } catch (e) {
    fail(where, String(e).split('\n')[0]);
    await shot(page, `failure-l1-${width}`);
  }
  for (const e of errors) fail(where, e);
  await ctx.close();
}

await b.close();
if (problems.length) {
  console.log(`${problems.length} problem(s):`);
  for (const p of problems) console.log(`  - ${p}`);
  process.exit(1);
}
console.log('BRUH Task Manager panel: all checks passed');
