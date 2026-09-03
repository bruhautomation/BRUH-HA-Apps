/* Playwright measure for the BRUH Print panel.
 *
 * Boot the panel first:
 *   python3 tests/manual/bruh_print_demo_panel.py /tmp/bruh-print-demo &
 *   node tests/manual/measure-print-panel.mjs
 *
 * Geometry cannot see everything a person sees, but it sees the five things
 * that have actually broken here, each of which is invisible from the code:
 *
 *   - a top bar 513px wide in a 390px window, because a flex item's floor is
 *     its max-content and the chips would not wrap;
 *   - a <select> laid out to its widest OPTION, taking the design tab's
 *     page-width with it;
 *   - `.btn.tiny` staying 32px on touch, because the touch-floor block sat
 *     ABOVE it in the stylesheet and equal specificity is settled by order;
 *   - an empty black toast across the bottom, because `.toast{display:flex}`
 *     beats the UA's `[hidden]` rule;
 *   - a design canvas rendered at 2x the printer's resolution and never
 *     fitted, so a 2.25" label was 1344px wide inside a 600px pane.
 *
 * Set SHOTS=1 to keep a screenshot per state. */
import { chromium } from 'playwright';
/* The prefix is the point: the panel is measured where ingress actually
 * mounts it, not at the root. Served at "/" every absolute asset URL works
 * by accident, which is how a panel that rendered as unstyled HTML under
 * ingress passed this measure at three widths. */
const PREFIX = process.env.DEMO_PREFIX
  || '/api/hassio_ingress/01JJRqzH5o3TtVgngV7GNA3w';
const URL = process.env.PANEL_URL || `http://127.0.0.1:8097${PREFIX}/`;
/* Same launch as every other measure in this folder: Playwright's own
 * browser by default, and CHROMIUM_PATH when it is somewhere else. An
 * absolute path baked in here is a script that runs on exactly one
 * machine — which is what shipped, and what CI caught on the first run. */
const b = await chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] }
    : { args: ['--no-sandbox'] });
const problems = [];

/* `width` is passed in rather than read from innerWidth: under Chromium's
 * mobile emulation the visual viewport WIDENS to fit an overflowing page, so
 * innerWidth grows to match scrollWidth and the comparison can never fail —
 * which is exactly what let a 513px bar pass in a 390px window. */
const audit = (width) => {
  const out = [];
  const coarse = matchMedia('(pointer: coarse)').matches;
  if (document.documentElement.scrollWidth > width + 1)
    out.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${width})`);
  for (const n of document.querySelectorAll('button, .tab, .chip, input, select, textarea')) {
    const r = n.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const name = n.id || n.className || n.tagName;
    if (n.type !== 'checkbox' && r.height < 40) out.push(`${name} is ${r.height.toFixed(0)}px tall`);
    if (coarse && ['INPUT','SELECT','TEXTAREA'].includes(n.tagName) && n.type !== 'checkbox'
        && parseFloat(getComputedStyle(n).fontSize) < 16)
      out.push(`${name} is under 16px on touch — iOS will zoom in and stay there`);
  }
  if (getComputedStyle(document.getElementById('toast')).display !== 'none')
    out.push('the toast is visible with nothing to say');
  /* A stylesheet that 404s leaves a page that still lays out, so the audit
   * has to ask whether the CSS and the JS actually arrived. Both have a
   * visible consequence: `.view` is display:none until a tab is chosen, and
   * app.js is what fills the stock picker. */
  const onScreen = [...document.querySelectorAll('.view')]
    .filter((v) => v.offsetParent !== null).length;
  if (onScreen !== 1)
    out.push(`${onScreen} views are on screen at once — style.css did not load`);
  if (!document.querySelector('#quickStock option'))
    out.push('the stock picker is empty — app.js did not load or /api/state failed');
  const canvas = document.getElementById('canvas');
  const pane = document.querySelector('.canvas-scroll');
  if (canvas && pane && canvas.getBoundingClientRect().width > pane.clientWidth)
    out.push('the design canvas is wider than its pane');
  return [...new Set(out)];
};

const run = async (w, h, name, touch, steps) => {
  const ctx = await b.newContext({ viewport: { width: w, height: h },
    deviceScaleFactor: 2, hasTouch: touch, isMobile: touch,
    colorScheme: name.includes('dark') ? 'dark' : 'light' });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
  p.on('console', (m) => { if (m.type() === 'error') problems.push(`${name} console: ${m.text()}`); });
  await p.goto(URL, { waitUntil: 'networkidle' });
  /* Before driving anything: did the page's own assets arrive? A stylesheet
   * that 404s leaves a page that still lays out, and a script that 404s
   * leaves controls that never appear — so every `click` times out and the
   * failure reads as a flaky selector rather than as "the panel did not
   * load". Ask first, and say which. */
  const arrived = await p.evaluate(() => {
    const bad = [];
    if (!getComputedStyle(document.body).backgroundColor
        || getComputedStyle(document.querySelector('.topbar')).position !== 'sticky')
      bad.push('style.css did not load (the page is unstyled)');
    if (typeof window.__bruhPrintReady === 'undefined')
      bad.push('app.js did not load');
    return bad;
  });
  if (arrived.length) {
    problems.push(`${name}: ${arrived.join('; ')}`);
    await ctx.close();
    return;
  }
  if (steps) await steps(p);
  await p.waitForTimeout(900);
  const found = await p.evaluate(audit, w);
  if (found.length) problems.push(`${name}: ${found.join('; ')}`);
  if (process.env.SHOTS) await p.screenshot({ path: `${name}.png` });
  await ctx.close();
};

await run(1440, 900, 'wide-quick', false, (p) => p.fill('#quickText', 'Buffer A pH 7.4'));
await run(1100, 820, 'laptop-design-dark', false, async (p) => {
  await p.click('[data-view="design"]'); await p.waitForTimeout(500);
  await p.click('#addBar button:nth-child(1)');
});
await run(820, 900, 'tablet-printer', true, (p) => p.click('[data-view="printer"]'));
await run(390, 780, 'phone-quick', true, (p) => p.fill('#quickText', 'HEK293T p14'));
await run(390, 780, 'phone-design', true, async (p) => {
  await p.click('[data-view="design"]'); await p.waitForTimeout(500);
  await p.click('#addBar button:nth-child(3)');
});
await b.close();
if (problems.length) { console.error('FAILED:\n- ' + problems.join('\n- ')); process.exit(1); }
console.log('measure-panel: clean at every width');
