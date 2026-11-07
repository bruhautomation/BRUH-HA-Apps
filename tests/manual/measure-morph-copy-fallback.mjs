// measure-morph-copy-fallback.mjs — a house copy of Morph's panel that
// loads and then throws as it draws is replaced by Morph's own (#706).
//
//   node tests/manual/measure-morph-copy-fallback.mjs   (CHROMIUM_PATH if needed)
//
// A Tell took a feature out of this house's copy of morph-panel.js and left
// a reference to an import it had removed. The module imported fine, so
// boot.js kept it, and every render threw: Morph was blank. Here the copy
// is Morph's own with one such reference in `render()` (and, second, in
// `boot()`, a different place the same mistake can be), served as an
// in-use copy the way static.py serves one, and this fails unless Morph's
// own panel draws the dashboard and the page says a change did not load,
// with the reason. A throw placed right after the panel says it is ready
// (third) is the same failure. A working copy (fourth) must stay in use, and
// so must one beside an error from a module that is not a copy (fifth).
//
// Exits non-zero with every failure listed.
import { chromium } from 'playwright';
import { readFileSync, readdirSync } from 'node:fs';
import { ORIGIN, route, FRONTEND, STAMP } from './morph-fixture.mjs';

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);
const own = readFileSync(new URL('../../brain/custom_components/brain/morph/frontend/morph-panel.js', import.meta.url), 'utf8');

const cases = [
  ['render', '  render() {\n', '    removedHelperNotImported(this);\n', true],
  ['boot', '  boot() {\n', '    alsoRemovedNotImported();\n', true],
  // After the panel has said it is ready, but before the dashboard's body
  // is drawn: the reviewer's case, blank before the watch outlasted ready.
  ['after ready', '    this.readyOnce();\n', '    removedAfterReadyNotImported();\n', true],
  ['a working copy', '  render() {\n', '    window.__houseCopyRan = true;\n', false],
  // A working copy while an error is reported from a served module that is
  // NOT a copy in use: that is not the copy failing, so it stays.
  ['an unrelated error', '  render() {\n', "    window.__houseCopyRan = true; if (!window.__unrelated) { window.__unrelated = 1; setTimeout(() => window.dispatchEvent(new ErrorEvent('error', { filename: new URL('engine.js', import.meta.url).href, message: 'unrelated' })), 0); }\n", false],
];

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  for (const [label, hook, body, broken] of cases) {
    if (!own.includes(hook)) { fail(label, `the hook ${JSON.stringify(hook)} is not in morph-panel.js`); continue; }
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
    await route(ctx, { narrow: false, overrides: { 'morph-panel.js': own.replace(hook, hook + body) }, noWaitMorph: true });
    // boot.js as static.py serves it with this copy in use: the stamp,
    // the modules and the copies written in.
    await ctx.route(/\/morph_static\/[^/]+\/boot\.js$/, (r) => {
      const names = readdirSync(FRONTEND).filter((n) => n.endsWith('.js') && n !== 'boot.js').sort();
      const src = readFileSync(new URL('boot.js', 'file://' + FRONTEND), 'utf8')
        .replace("const STAMP = '';", `const STAMP = ${JSON.stringify(STAMP)};`)
        .replace('const MODULES = [];', `const MODULES = ${JSON.stringify(names)};`)
        .replace('const COPIES = [];', 'const COPIES = ["morph-panel.js"];');
      return r.fulfill({ contentType: 'text/javascript', body: src });
    });
    const p = await ctx.newPage();
    await p.goto(ORIGIN + '/').catch(() => {});
    await p.waitForTimeout(4000);
    const got = await p.evaluate(() => {
      const boot = document.querySelector('morph-boot');
      const root = boot && boot.shadowRoot;
      const panel = root && (root.querySelector('morph-panel-shipped') || root.querySelector('morph-panel'));
      const pr = panel && panel.shadowRoot;
      const sections = pr ? pr.querySelectorAll('[data-board] section[data-sec]').length : 0;
      return { tag: panel ? panel.tagName.toLowerCase() : '', sections, fallback: window.__morphFallback || '',
               note: pr ? pr.textContent.includes('did not load, so Morph is running its own copy') : false,
               ran: !!window.__houseCopyRan };
    }).catch((e) => ({ error: String(e) }));
    if (got.error) { fail(label, got.error); await ctx.close(); continue; }
    if (!got.sections) fail(label, `the dashboard did not draw (${got.tag || 'no panel'})`);
    if (broken) {
      if (got.tag !== 'morph-panel-shipped') fail(label, `Morph's own panel did not take the copy's place (${got.tag})`);
      if (!/NotImported/.test(got.fallback)) fail(label, `the reason was not kept: "${got.fallback}"`);
      if (!got.note) fail(label, 'the page does not say a change did not load');
    } else {
      if (got.tag !== 'morph-panel' || got.fallback) fail(label, `a working copy was replaced (${got.tag}, "${got.fallback}")`);
      if (!got.ran) fail(label, 'the working copy did not run');
    }
    await ctx.close();
  }
  await browser.close();
  if (failures.length) { console.log(failures.join('\n')); process.exit(1); }
  console.log('measure-morph-copy-fallback: ok');
})();
