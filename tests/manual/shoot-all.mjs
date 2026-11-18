/* Screenshot every add-on's panel at four widths, for before/after comparison
 * of a UI change (docs/notes/ui-standard.md). A hand tool, not a gate.
 *
 *   node tests/manual/shoot-all.mjs                 # every app
 *   node tests/manual/shoot-all.mjs --app minecraft # one (repeat --app for more)
 *   SHOT_DIR=/tmp/before node tests/manual/shoot-all.mjs
 *   SHOT_DIR=/tmp/after  node tests/manual/shoot-all.mjs   # then compare the folders
 *   SHOT_SCHEME=dark, SHOT_QUERY='?shell=1' (brain only): dark scheme, or the in-shell page
 *
 * Output: SHOT_DIR/<app>/<view>-<width>.png (default SHOT_DIR /tmp/ui-shots),
 * full page, light scheme, at 390 (an emulated touch phone), 768, 1280 and 1920.
 *
 * Apps: brain, print, bright, taskmanager (each runs its own real server from
 * a tests/manual/*_demo_panel.py, started and stopped here) and minecraft,
 * bambu, browser (served as static files from the panel directory, their /api
 * answered by the stubs in shoot-stubs.mjs). Morph is the Home tab inside
 * brAIn's panel only with Home Assistant behind it, so it is not shot here.
 *
 * Skipped on purpose: GardenRX (a Next.js build) and BRUH Cooking (an npm
 * build). Shoot those from their own dev servers.
 *
 * Needs python3 with aiohttp and the repo's test requirements for the demo
 * servers. Bambu's 3D view needs three.js: point BAMBU_VENDOR at a folder with
 * three.module.min.js, OrbitControls.js and STLLoader.js (the Dockerfile pins
 * them), or the view is left blank and every other screen is unaffected.
 *
 * Playwright resolves like the other tests/manual scripts, falling back to
 * the global install in this container. CHROMIUM_PATH picks another browser. */
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as S from './shoot-stubs.mjs';

let chromium;
try { ({ chromium } = await import('playwright')); } catch (_) {
  ({ chromium } = (await import('/opt/node22/lib/node_modules/playwright/index.js')).default);
}

const HERE = new URL('.', import.meta.url).pathname;
const ROOT = join(HERE, '..', '..');
const OUT = process.env.SHOT_DIR || '/tmp/ui-shots';
const WIDTHS = [390, 768, 1280, 1920];
const argv = process.argv.slice(2);
const ONLY = argv.flatMap((a, i) => (a === '--app' ? [argv[i + 1]] : []));

const servers = [];
const failures = [];
const mine = mkdtempSync(join(tmpdir(), 'shoot-all-'));

function serve(script, args, env, url, log) {
  const child = spawn('python3', [join(HERE, script), ...args], {
    cwd: ROOT, detached: true, env: { ...process.env, ...env },
    stdio: ['ignore', 'ignore', 'ignore'],
  });
  servers.push(child);
  return { child, url, log };
}
async function ready(url, ms = 40000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try { if ((await fetch(url)).status < 500) return; } catch (_) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`${url} did not come up`);
}
function stopAll() {
  for (const c of servers) { try { process.kill(-c.pid, 'SIGTERM'); } catch (_) { /* gone */ } }
  try { rmSync(mine, { recursive: true, force: true }); } catch (_) { /* fine */ }
}
process.on('exit', stopAll);
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { stopAll(); process.exit(1); });

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : { args: ['--no-sandbox'] });

async function open(app, w, prepare) {
  const phone = w < 500;
  const ctx = await browser.newContext({
    viewport: { width: w, height: phone ? 844 : 900 }, deviceScaleFactor: 1, colorScheme: process.env.SHOT_SCHEME || 'light',
    isMobile: phone, hasTouch: phone,
  });
  const page = await ctx.newPage();
  // Without real three.js (BAMBU_VENDOR) Bambu's 3D view throws; that is expected.
  page.on('pageerror', (e) => app === 'bambu' && !process.env.BAMBU_VENDOR ? null : failures.push(`${app} ${w}: page error ${String(e.message).split('\n')[0]}`));
  // SHOT_INSHELL=1: the brAIn page as it is drawn inside Morph's shell (the class the page sets when framed).
  if (process.env.SHOT_INSHELL) await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => document.documentElement.classList.add('in-shell')));
  if (prepare) await prepare(page);
  return { ctx, page };
}
// Full-page capture; `scroller` is an inner scroll container to grow the page to.
async function shot(page, app, view, w, scroller) {
  await page.mouse.move(w - 2, 2).catch(() => {});
  await page.waitForTimeout(350);
  if (scroller) {
    const base = page.viewportSize().height;
    const extra = await page.evaluate((sel) => { const m = document.querySelector(sel); return m ? m.scrollHeight - m.clientHeight : 0; }, scroller);
    await page.setViewportSize({ width: w, height: Math.min(base + Math.max(extra, 0), 9000) });
    await page.waitForTimeout(150);
  }
  mkdirSync(join(OUT, app), { recursive: true });
  await page.screenshot({ path: join(OUT, app, `${view}-${w}.png`), fullPage: true });
  if (scroller) await page.setViewportSize({ width: w, height: page.viewportSize().height }).catch(() => {});
}
// Run one step; a screen that cannot be reached is reported, not fatal.
async function step(app, view, w, fn) {
  try { await fn(); } catch (e) { failures.push(`${app}/${view} ${w}: ${String(e.message).split('\n')[0]}`); }
}
const MIME = { js: 'application/javascript', mjs: 'application/javascript', css: 'text/css', svg: 'image/svg+xml', html: 'text/html', json: 'application/json' };
const NOVNC = '<html><body style="margin:0;background:#2b2b2b;color:#aaa;font:14px sans-serif;display:grid;place-items:center;height:100vh">noVNC (stub)</body></html>';
// Serve a panel directory on a fake origin; `api(path, request)` answers /api calls.
function staticPanel(dir, api, extra) {
  return async (page) => {
    await page.route('http://panel.test/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname.slice(1);
      if (extra) { const done = await extra(route, path, url); if (done) return; }
      if (path.startsWith('novnc/')) return route.fulfill({ body: NOVNC, contentType: 'text/html' });
      if (path.startsWith('api/')) return api(route, path, url);
      const file = path || 'index.html';
      try { return await route.fulfill({ body: readFileSync(join(dir, file)), contentType: MIME[file.split('.').pop()] || 'application/octet-stream' }); } catch (_) { return route.fulfill({ status: 404, body: '' }); }
    });
  };
}
async function tabs(app, w, page, attr, names, opts = {}) {
  for (const name of names) {
    await step(app, name, w, async () => {
      await page.click(`.tab[${attr}="${name}"]`);
      await page.waitForTimeout(opts.settle || 700);
      await shot(page, app, name, w, opts.scroller);
    });
  }
}

const APPS = {
  async brain() {
    const dir = join(mine, 'brain');
    const port = 18199;
    serve('demo_panel.py', [dir], { DEMO_PORT: String(port) });
    const url = `http://127.0.0.1:${port}/`;
    await ready(url);
    const { openView } = await import('./tabs.mjs');
    const VIEWS = ['insights', 'findings', 'archive', 'terminal', 'memory', 'activity', 'housebook', 'docs'];
    const SECS = ['usage', 'permissions', 'diagnostics', 'personality', 'features', 'notifications'];
    for (const w of WIDTHS) {
      const { ctx, page } = await open('brain', w);
      await page.goto(url + (process.env.SHOT_QUERY || ''), { waitUntil: 'networkidle' });
      await page.waitForTimeout(900);
      for (const v of VIEWS) {
        await step('brain', v, w, async () => {
          if (v !== 'insights') { await openView(page, v); await page.waitForTimeout(700); }
          await shot(page, 'brain', v, w);
        });
      }
      await step('brain', 'settings', w, async () => {
        await page.click('#settingsBtn');
        await page.waitForTimeout(700);
        await shot(page, 'brain', 'set-index', w);
        for (const sec of SECS) {
          await step('brain', `set-${sec}`, w, async () => {
            const btn = page.locator(`#setNav .setnavbtn[data-sec="${sec}"]`);
            if (!(await btn.isVisible())) await page.locator('#setModal .setsec:not([hidden]) .setback').click({ timeout: 3000 });
            await btn.click({ timeout: 3000 });
            await page.waitForTimeout(700);
            await shot(page, 'brain', `set-${sec}`, w);
          });
        }
      });
      await ctx.close();
    }
  },

  async print() {
    const port = 18197;
    const prefix = '/api/hassio_ingress/01JJRqzH5o3TtVgngV7GNA3w/';
    serve('bruh_print_demo_panel.py', [join(mine, 'print')], { DEMO_PORT: String(port) });
    await ready(`http://127.0.0.1:${port}${prefix}`);
    for (const w of WIDTHS) {
      const { ctx, page } = await open('print', w);
      await page.goto(`http://127.0.0.1:${port}${prefix}`, { waitUntil: 'load' });
      await page.waitForTimeout(1200);
      await tabs('print', w, page, 'data-view', ['quick', 'design', 'templates', 'printer', 'history']);
      await step('print', 'printer-open', w, async () => {
        await page.click('.tab[data-view="printer"]');
        await page.evaluate(() => document.querySelectorAll('#viewPrinter details').forEach((d) => { d.open = true; }));
        await shot(page, 'print', 'printer-open', w);
      });
      await ctx.close();
    }
  },

  async bright() {
    const port = 18195;
    serve('bright_demo_panel.py', [join(mine, 'bright')], { DEMO_PORT: String(port) });
    const url = `http://127.0.0.1:${port}/`;
    await ready(url);
    for (const w of WIDTHS) {
      const { ctx, page } = await open('bright', w);
      await page.goto(url, { waitUntil: 'load' });
      await page.waitForTimeout(1500);
      await tabs('bright', w, page, 'data-tab', ['lab', 'map', 'effects', 'library', 'shows', 'manual', 'calibrate', 'party'], { settle: 900 });
      await ctx.close();
    }
  },

  async taskmanager() {
    const prefix = '/api/hassio_ingress/tmDemoToken01/';
    serve('task_manager_demo_panel.py', [join(mine, 'tm2'), '18203', '--level2'], {});
    serve('task_manager_demo_panel.py', [join(mine, 'tm1'), '18213'], {});
    await Promise.all([ready(`http://127.0.0.1:18203${prefix}`), ready(`http://127.0.0.1:18213${prefix}`)]);
    for (const w of WIDTHS) {
      for (const [lvl, port] of [['l2', 18203], ['l1', 18213]]) {
        const { ctx, page } = await open('taskmanager', w);
        await step('taskmanager', lvl, w, async () => {
          await page.goto(`http://127.0.0.1:${port}${prefix}`, { waitUntil: 'networkidle' });
          await page.waitForFunction(() => document.querySelectorAll('#appList .app').length >= 8, null, { timeout: 15000 });
          await page.waitForFunction(() => /%/.test(document.querySelector('#mCpu').textContent), null, { timeout: 15000 });
          if (lvl === 'l2') {
            await shot(page, 'taskmanager', 'apps', w);
            await page.click('.tab[data-view="processes"]');
            await page.waitForFunction(() => document.querySelectorAll('#procList .group').length >= 6, null, { timeout: 15000 });
            await page.evaluate(() => { for (const g of [...document.querySelectorAll('#procList .group')].slice(0, 3)) g.open = true; });
            await shot(page, 'taskmanager', 'processes', w);
            await page.click('.tab[data-view="settings"]');
            await shot(page, 'taskmanager', 'settings', w);
          } else {
            await page.click('.tab[data-view="processes"]');
            await shot(page, 'taskmanager', 'l1-processes', w);
            await page.click('.tab[data-view="settings"]');
            await shot(page, 'taskmanager', 'l1-settings', w);
          }
        });
        await ctx.close();
      }
    }
  },

  async minecraft() {
    const json = (body) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    const api = (setup) => (route, path) => {
      if (path === 'api/logs/tail') {
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ['[12:01:04 INFO]: Done (8.412s)! For help, type "help"', '[12:03:11 INFO]: Steve_builds joined the game', '[12:05:02 WARN]: Can\'t keep up! Is the server overloaded?', '[12:07:19 INFO]: AlexTheMiner joined the game'].map((l) => `data: ${l}\n\n`).join('') });
      }
      const body = path === 'api/status' && setup ? { ...S.MC[path], setup_required: true } : (S.MC[path] ?? {});
      return route.fulfill(json(body));
    };
    const dir = join(ROOT, 'bruh-minecraft-server', 'panel');
    for (const w of WIDTHS) {
      const { ctx, page } = await open('minecraft', w, staticPanel(dir, api(false)));
      await page.goto('http://panel.test/index.html');
      await page.waitForTimeout(700);
      await tabs('minecraft', w, page, 'data-tab', ['dashboard', 'console', 'players', 'properties', 'addons', 'backups', 'worlds'], { settle: 500, scroller: 'main' });
      await ctx.close();
      const wiz = await open('minecraft', w, staticPanel(dir, api(true)));
      await wiz.page.goto('http://panel.test/index.html');
      await wiz.page.waitForTimeout(900);
      await step('minecraft', 'wizard', w, () => shot(wiz.page, 'minecraft', 'wizard', w));
      await wiz.ctx.close();
    }
  },

  async bambu() {
    const dir = S.PANEL;
    const vendor = process.env.BAMBU_VENDOR || '';
    const stub = { 'three.module.min.js': 'export const Scene=class{},PerspectiveCamera=class{},WebGLRenderer=class{},Color=class{},Group=class{},Vector3=class{},Box3=class{},Mesh=class{},MeshStandardMaterial=class{},AmbientLight=class{},DirectionalLight=class{},GridHelper=class{},BufferGeometry=class{},Float32BufferAttribute=class{},MathUtils={},DoubleSide=2;',
      'OrbitControls.js': 'export class OrbitControls{}', 'STLLoader.js': 'export class STLLoader{}' };
    const API = S.bambuApi();
    const extra = async (route, path, url) => {
      if (path.startsWith('vendor/')) {
        const name = path.slice(7);
        const real = vendor && join(vendor, name);
        await route.fulfill({ body: real && existsSync(real) ? readFileSync(real) : (stub[name] || ''), contentType: 'application/javascript' });
        return true;
      }
      if (path.endsWith('/file')) { await route.fulfill({ body: S.STL[url.searchParams.get('path')] || '', contentType: 'model/stl' }); return true; }
      if (path === 'api/printer/camera') { await route.fulfill({ body: S.FRAME, contentType: 'image/jpeg' }); return true; }
      if (/api\/(watch\/image|thumb|printer\/thumb)$/.test(path) || path.endsWith('/thumb')) { await route.fulfill({ body: S.PICTURE, contentType: 'image/png' }); return true; }
      return false;
    };
    const api = (running) => (route, path) => {
      if (path === 'api/printers/scan') return route.fulfill({ json: { ok: true, job: { state: 'done', networks: ['192.168.1.0/24'], found: [{ host: '192.168.1.62', serial: '01S00C123456789', model: 'P1P' }] } } });
      if (route.request().method() !== 'GET') return route.fulfill({ json: { ok: true, part: S.PART } });
      let j = API[path];
      if (path === 'api/state' && running) j = { ...API[path], studio: { installed: true, running: true, wanted: true, install: {} } };
      return route.fulfill({ json: j || { ok: true } });
    };
    for (const w of WIDTHS) {
      const { ctx, page } = await open('bambu', w, staticPanel(dir, api(false), extra));
      await page.goto('http://panel.test/');
      await page.evaluate(() => { try { localStorage.clear(); } catch (_) { /* fine */ } });
      await step('bambu', 'studio-stopped', w, async () => {
        await page.locator('.tab[data-view="studio"]').click();
        await shot(page, 'bambu', 'studio-stopped', w);
      });
      await step('bambu', 'printers', w, async () => {
        await page.locator('.tab[data-view="printers"]').click();
        await page.locator('.printer').first().waitFor({ timeout: 5000 });
        await page.waitForTimeout(800);
        await shot(page, 'bambu', 'printers', w);
        await page.evaluate(() => document.querySelectorAll('.printer[data-id="a1"] details.more').forEach((d) => { d.open = true; d.dispatchEvent(new Event('toggle')); }));
        await page.waitForTimeout(600);
        await shot(page, 'bambu', 'printers-open', w);
      });
      await step('bambu', 'files', w, async () => {
        await page.locator('.tab[data-view="files"]').click();
        await page.locator('.frow').first().waitFor({ timeout: 5000 });
        await shot(page, 'bambu', 'files', w);
        await page.locator('.frow button.primary, .frow .factions button').first().click().catch(() => {});
        await page.waitForTimeout(500);
        if (await page.locator('dialog[open]').count()) {
          await page.evaluate(() => document.querySelectorAll('dialog[open] details').forEach((d) => { d.open = true; }));
          await shot(page, 'bambu', 'dialog-print', w);
          await page.locator('#printCancel').click().catch(() => {});
        }
      });
      await step('bambu', 'design', w, async () => {
        await page.locator('#designTab').click();
        await page.locator('.partrow').first().waitFor({ timeout: 5000 });
        await shot(page, 'bambu', 'design-list', w);
        await page.locator('.partrow').first().click();
        await page.waitForTimeout(1800);
        await shot(page, 'bambu', 'design-part', w);
        await page.keyboard.press('Escape');
      });
      await step('bambu', 'settings', w, async () => {
        await page.locator('.tab[data-view="settings"]').click();
        await page.waitForTimeout(500);
        await page.locator('#scanBtn').click().catch(() => {});
        await page.waitForTimeout(600);
        await shot(page, 'bambu', 'settings', w);
        await page.evaluate(() => document.querySelectorAll('#viewSettings details').forEach((d) => { d.open = true; }));
        await shot(page, 'bambu', 'settings-open', w);
      });
      await ctx.close();
      const r = await open('bambu', w, staticPanel(dir, api(true), extra));
      await r.page.goto('http://panel.test/');
      await step('bambu', 'studio-running', w, async () => {
        await r.page.locator('.tab[data-view="studio"]').click();
        await shot(r.page, 'bambu', 'studio-running', w);
      });
      await r.ctx.close();
    }
  },

  async browser() {
    const dir = join(ROOT, 'bruh-browser', 'panel');
    for (const [name, data] of Object.entries(S.browserVariants())) {
      for (const w of WIDTHS) {
        const api = (route, path) => route.fulfill({ json: path === 'api/state' ? data : { ok: true } });
        const { ctx, page } = await open('browser', w, staticPanel(dir, api));
        await page.goto('http://panel.test/');
        await page.waitForTimeout(500);
        await step('browser', name, w, () => shot(page, 'browser', name, w));
        await ctx.close();
      }
    }
  },
};

const names = Object.keys(APPS).filter((n) => !ONLY.length || ONLY.includes(n));
for (const unknown of ONLY.filter((n) => !APPS[n])) failures.push(`unknown app "${unknown}" (apps: ${Object.keys(APPS).join(', ')})`);
for (const name of names) {
  const started = Date.now();
  try { await APPS[name](); console.log(`${name.padEnd(12)} ${((Date.now() - started) / 1000).toFixed(1)}s`); } catch (e) { failures.push(`${name}: ${e.message}`); }
}
await browser.close();
stopAll();
console.log(`screenshots in ${OUT}`);
if (failures.length) { console.log(`\n${failures.length} problem(s):\n${failures.join('\n')}`); process.exitCode = 1; }
