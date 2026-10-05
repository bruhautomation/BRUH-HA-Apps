// The phone, measured: docs/design/ui-redesign-2026-10.md, PR 10 — "Bottom
// tab bar, 56 px header with status dot and ⚙, 44 px targets, no
// sideways-scrolling chip rows, Ask opens on the list."
//
// measure-topbar holds the bar's own shape at every width with the panel's
// JS refused; this drives the REAL panel (markup, stylesheet and renderers)
// behind the shared Today fixture, opens every pane and ⚙, and reads what
// was painted at a phone (390, touch), the narrowest phone (320, touch) and
// a desktop (1200):
//
//   * on a phone the header is one row no taller than 56px holding the
//     logo, the status dot and ⚙ — no chip, no tab — and the three tabs are
//     a bar fixed along the bottom, inside the screen, each a named 44px
//     target;
//   * nothing a pane draws ends under that bar: scrolled to the bottom, the
//     pane's last pixel is above the bar's top edge;
//   * nothing scrolls sideways — not the page, and not a row inside it
//     (code, a transcript's pre and a text box are allowed their own);
//   * the status dot opens the disclosure with the status sentence, and a
//     trouble chip's press is in it;
//   * Ask opens on the list of your conversations, not a transcript;
//   * no visible button carries an emoji or an arrow glyph (a bare ⋯ or ✕
//     with an aria-label is an icon button, and allowed), and no "?" bubble
//     is anywhere;
//   * on a desktop the tabs are in the header row and there is no dot.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stub, NOW } from './today-fixture.mjs';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const HEADER_MAX = 56;
const MIN_TARGET = 44;
const VIEWS = ['findings', 'terminal', 'insights', 'memory', 'housebook', 'activity', 'docs'];

// The panes beyond Today read a few routes the Today fixture leaves empty;
// give them enough to draw something, and a trouble state for the dot.
const EXTRA = `
(() => {
  const inner = window.fetch;
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  window.fetch = async (url, opts) => {
    const p = String(url);
    if (p.includes('api/insights')) {
      return answer({ insights: [{ id: 'energy', category: 'energy',
        title: 'Energy use this week',
        summary: 'The house used 12% less than last week. Most of it was the heat pump.',
        html: '<!doctype html><p>chart</p>',
        generated_at: new Date(${NOW} * 1000 - 3600e3).toISOString(),
        tags: ['energy'], highlights: [], meta: {} }] });
    }
    if (p.includes('api/chat/conversations')) {
      return answer({ conversations: [
        { id: 'c1', title: 'Why is the hall light on at night?', updated_at: ${NOW} - 600,
          source: 'you', messages: 4 },
        { id: 'c2', title: 'Discussing: Garage freezer drifting', updated_at: ${NOW} - 7200,
          source: 'you', messages: 6, finding_ts: 1101 },
      ], counts: { you: 2 }, sources: [] });
    }
    if (p.includes('api/status')) {
      const r = await inner(url, opts);
      const body = await r.json();
      body.authenticated = true;
      body.auth_check = { state: 'failed', error: 'expired' };
      return answer(body);
    }
    return inner(url, opts);
  };
})();
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

// What the viewport shows, read in one pass.
function readScreen({ min }) {
  const vw = window.innerWidth;
  const visible = (n) => {
    if (!n.isConnected) return false;
    if (n.closest('[hidden], .hidden, .tipbox')) return false;
    if (typeof n.checkVisibility === 'function'
        && !n.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const name = (n) => `${n.tagName.toLowerCase()}${n.id ? '#' + n.id : ''}`
    + (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const bar = document.querySelector('.topbar');
  const tabbar = document.querySelector('.viewtabs');
  const fixed = getComputedStyle(tabbar).position === 'fixed';
  const br = bar.getBoundingClientRect();
  const tr = tabbar.getBoundingClientRect();
  const header = [...bar.children]
    .filter((el) => el !== tabbar && !el.classList.contains('spacer') && visible(el))
    .map((el) => el.id || el.getAttribute('class').split(' ')[0]);
  const tabs = [...document.querySelectorAll('.viewtab')].map((t) => {
    const r = t.getBoundingClientRect();
    const label = [...t.querySelectorAll('span:not(.badge)')]
      .filter((s) => visible(s)).map((s) => s.textContent.trim()).join('');
    return { label, w: Math.round(r.width), h: Math.round(r.height),
             inside: r.left >= -0.5 && r.right <= vw + 0.5 };
  });
  // Rows that scroll sideways inside the page. A block of code, a text box
  // and a frame are allowed their own scroll; a row of chips is not.
  const sideways = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    if (['PRE', 'CODE', 'TEXTAREA', 'IFRAME', 'TABLE', 'INPUT'].includes(el.tagName)) continue;
    if (el.closest('pre, table, .xterm, #docsBody table')) continue;
    const cs = getComputedStyle(el);
    if (!['auto', 'scroll'].includes(cs.overflowX)) continue;
    if (el.scrollWidth > el.clientWidth + 1) sideways.push(name(el));
  }
  // Buttons whose label carries a glyph, and "?" bubbles.
  const GLYPH = /[←-⇿⌀-⏿☀-➿⤀-⥿⬀-⯿＋\u{1F300}-\u{1FAFF}]/u;
  const ICON_OK = new Set(['⋯', '✕', '×', '…']);
  const glyphs = [];
  const bubbles = [];
  const small = [];
  for (const b of document.querySelectorAll('button, [role="button"], a.btn')) {
    if (!visible(b)) continue;
    const text = b.textContent.replace(/\s+/g, ' ').trim();
    if (text === '?') bubbles.push(name(b));
    if (text && GLYPH.test(text) && !(ICON_OK.has(text) && b.getAttribute('aria-label'))) {
      glyphs.push(`${name(b)} "${text.slice(0, 30)}"`);
    }
  }
  for (const n of document.querySelectorAll('.tip, .qmark, .help-q')) {
    if (visible(n)) bubbles.push(name(n));
  }
  for (const b of [...document.querySelectorAll('.topbar button')]) {
    if (!visible(b)) continue;
    const r = b.getBoundingClientRect();
    if (Math.min(r.width, r.height) < min - 0.5 && !b.classList.contains('chip')) {
      small.push(`${name(b)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  // Where the pane in front ends, scrolled all the way down.
  const view = document.querySelector('.view.active');
  const vr = view ? view.getBoundingClientRect() : null;
  let lastBottom = 0;
  if (view) {
    for (const el of view.querySelectorAll('*')) {
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.position === 'fixed') continue;
      lastBottom = Math.max(lastBottom, el.getBoundingClientRect().bottom);
    }
  }
  return {
    vw, docW: document.documentElement.scrollWidth,
    headerH: Math.round(br.height), header, fixed,
    tabbarTop: tr.top, tabbarBottom: tr.bottom, innerH: window.innerHeight,
    tabs, sideways, glyphs, bubbles, small,
    viewBottom: vr ? vr.bottom : 0, lastBottom,
    askList: document.body.classList.contains('ask-list'),
  };
}

for (const { width, touch } of [
  { width: 390, touch: true }, { width: 320, touch: true }, { width: 1200, touch: false },
]) {
  const phone = width <= 640;
  const context = await browser.newContext({
    viewport: { width, height: 800 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub());
  await page.addInitScript(EXTRA);
  await page.goto(`file://${PANEL}/index.html`);
  await page.waitForFunction(() => document.querySelector('#findList .qcard'));
  await page.waitForTimeout(300);

  for (const view of VIEWS) {
    const where = `${width}px ${view}`;
    try {
      await openView(page, view);
    } catch (e) {
      note(where, `could not open the pane: ${e.message.split('\n')[0]}`);
      continue;
    }
    await page.waitForTimeout(250);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(100);
    const r = await page.evaluate(readScreen, { min: MIN_TARGET });
    if (r.docW > r.vw) note(where, `the page scrolls sideways (${r.docW}px in ${r.vw}px)`);
    for (const s of new Set(r.sideways)) note(where, `a row scrolls sideways: ${s}`);
    for (const g of new Set(r.glyphs)) note(where, `a button label carries a glyph: ${g}`);
    for (const b of new Set(r.bubbles)) note(where, `a "?" bubble: ${b}`);
    for (const s of r.small) note(where, `a header target is under ${MIN_TARGET}px: ${s}`);
    if (phone) {
      if (r.headerH > HEADER_MAX) note(where, `the header is ${r.headerH}px, over ${HEADER_MAX}`);
      const allowed = new Set(['wordmark', 'statusDot', 'settingsBtn']);
      const extra = r.header.filter((h) => !allowed.has(h));
      if (extra.length) note(where, `the header holds more than logo, dot and ⚙: ${extra}`);
      for (const need of ['statusDot', 'settingsBtn']) {
        if (!r.header.includes(need)) note(where, `the header has no ${need}`);
      }
      if (!r.fixed) note(where, 'the tabs are not a bar fixed to the bottom');
      if (Math.abs(r.tabbarBottom - r.innerH) > 1) {
        note(where, `the tab bar ends at ${Math.round(r.tabbarBottom)}, not the screen's bottom ${r.innerH}`);
      }
      for (const t of r.tabs) {
        if (!t.label) note(where, 'a tab has no name');
        if (Math.min(t.w, t.h) < MIN_TARGET) note(where, `tab "${t.label}" is ${t.w}x${t.h}`);
        if (!t.inside) note(where, `tab "${t.label}" is off the screen`);
      }
      // Nothing the pane draws ends under the bar.
      const end = Math.max(r.lastBottom, view === 'terminal' ? r.viewBottom : 0);
      if (end > r.tabbarTop + 1) {
        note(where, `the pane ends at ${Math.round(end)}, under the tab bar at ${Math.round(r.tabbarTop)}`);
      }
      if (view === 'terminal' && !r.askList) note(where, 'Ask did not open on the list');
    } else {
      if (r.fixed) note(where, 'the desktop tabs are a fixed bottom bar');
      if (r.header.includes('statusDot')) note(where, 'the desktop header shows the status dot');
      if (r.headerH !== 56) note(where, `the desktop header is ${r.headerH}px`);
    }
  }

  // ⚙, every section open.
  {
    const where = `${width}px settings`;
    try {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.click('#settingsBtn');
      await page.waitForSelector('#setModal:not(.hidden)', { timeout: 3000 });
      await page.evaluate(() => {
        for (const d of document.querySelectorAll('#setModal details')) d.open = true;
      });
      await page.waitForTimeout(300);
      const r = await page.evaluate(readScreen, { min: MIN_TARGET });
      if (r.docW > r.vw) note(where, `the page scrolls sideways (${r.docW}px in ${r.vw}px)`);
      for (const s of new Set(r.sideways)) note(where, `a row scrolls sideways: ${s}`);
      for (const g of new Set(r.glyphs)) note(where, `a button label carries a glyph: ${g}`);
      for (const b of new Set(r.bubbles)) note(where, `a "?" bubble: ${b}`);
      await page.keyboard.press('Escape');
      await page.evaluate(() => {
        const m = document.querySelector('#setModal');
        if (m && !m.classList.contains('hidden')) {
          (m.querySelector('[data-close], .close, #setClose') || {}).click?.();
        }
      });
    } catch (e) {
      note(where, `could not open ⚙: ${e.message.split('\n')[0]}`);
    }
  }

  // The dot: one press opens the status sentence and the trouble chip's
  // own press; a phone only.
  if (phone) {
    const where = `${width}px status dot`;
    try {
      await page.evaluate(() => switchView('findings'));
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(200);
      const state = await page.getAttribute('#statusDot', 'data-state');
      if (state !== 'signed_out') note(where, `a failed sign-in reads as "${state}"`);
      await page.click('#statusDot');
      await page.waitForSelector('#chipPop:not(.hidden)', { timeout: 2000 });
      const pop = await page.evaluate(() => {
        const p = document.querySelector('#chipPop');
        const r = p.getBoundingClientRect();
        return {
          text: p.textContent,
          presses: [...p.querySelectorAll('[data-press]')].map((b) => b.dataset.press),
          inside: r.left >= 0 && r.right <= window.innerWidth,
        };
      });
      if (!/Watching|last look/.test(pop.text)) note(where, 'the disclosure has no status sentence');
      if (!pop.presses.includes('authChip')) note(where, 'the failed sign-in has no press in it');
      if (!pop.inside) note(where, 'the disclosure is off the screen');
    } catch (e) {
      note(where, `the dot did not open: ${e.message.split('\n')[0]}`);
    }
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-phone: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('measure-phone: OK — at 390 and 320 the header is the logo, the dot and ⚙ '
  + `in ${HEADER_MAX}px, the three tabs are a bottom bar nothing ends under, nothing `
  + 'scrolls sideways, Ask opens on its list, and no button carries a glyph; at 1200 the '
  + 'tabs are in the header');
