// measure-shell.mjs — brAIn's one sidebar entry (brAIn 4.0), the shell.
//
//   node tests/manual/measure-shell.mjs        (CHROMIUM_PATH if needed)
//
// The shell (custom_components/brain/morph/frontend/shell.js) is a Home
// Assistant custom panel holding brAIn's own page in a frame and the Morph
// dashboard drawn natively as the Home tab. This boots the real shell and
// the real Morph modules against Morph's fake house (morph-fixture.mjs),
// with a stand-in for brAIn's framed page that speaks the frame's half of
// the protocol, and checks:
//
//   * an administrator gets the ingress session (the cookie is set) and
//     brAIn's page in the frame, with ?shell=1;
//   * with the dashboard on, Morph mounts inside the shell as Home, between
//     the bars the frame reports, and is told brAIn's header is above it
//     (no brand, no ☰ of its own);
//   * the frame's "show panel" hides Home and "show home" brings it back;
//     a raise puts the frame over Morph; ☰ asks Home Assistant to open its
//     sidebar; the frame is told the state (narrow, morph, view);
//   * Morph's "See the changes" opens brAIn's ⚙ › Dashboard in the frame;
//   * with the dashboard off there is no Home, and the frame is all there is;
//   * somebody who is not an administrator gets Morph alone, full height,
//     with its own bar's name and no frame;
//   * with brAIn's REAL page in the frame, at 390 (touch) and 1200, in each
//     of Morph's three themes: exactly one header on Home and on every brAIn
//     tab — the assistant's name, the status, and Home · Insights · Ask ·
//     Memory · ⚙ inside it, Morph's Edit there on Home and no bar of
//     Morph's own; the version in ⚙ and not in the header; no tab bar along
//     the bottom; brAIn's page in the same theme as Morph (its ground is
//     Morph's #0A0C0E, #2A2D31 or #ECEBE6) and legible in it; nothing cut
//     off, no sideways scroll, every target at the floor. The owner: "there
//     are two headers … merge them".
//   * on the owner's iPhone (390, touch, a 59px safe area with the Dynamic
//     Island in it): the header's first row is the island strip — on its
//     own ground from the top of the screen, the name left of the island,
//     the status and ⚙ right of it, nothing under the island — with the
//     tabs below the strip and at most 60px of header and controls under
//     the strip before the pane's first line (the sections are under their
//     tab, the search is a 44px icon that opens a 16px field); Morph draws
//     no strip or safe-area padding of its own under it.
//   * at 390 and 1200: scrolling down hides the header (only the island
//     strip's ground stays) on Insights and on Home (Morph's scroll), Home
//     takes its place, and scrolling up or reaching the top brings it back;
//     with reduce motion it does not slide. A drag on the header moves
//     neither the page under it nor the window around brAIn, and nothing
//     lets a drag run on into Home Assistant's window.
//     SHELL_SHOT_DIR=<dir> keeps a picture of each.
//
// Exits non-zero with every failure listed.
import { chromium } from 'playwright';
import { ORIGIN, route, BRAIN_VERSION, MANY_INSIGHTS, safeArea } from './morph-fixture.mjs';

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);
const settle = (p, ms) => p.waitForTimeout(ms);

async function open(browser, opts, width = 1200, touch = false, inset = 0, motion = 'no-preference') {
  const ctx = await browser.newContext({ viewport: { width, height: 860 }, hasTouch: touch, isMobile: touch, reducedMotion: motion });
  await route(ctx, { ...opts, shell: true });
  const p = await ctx.newPage();
  if (inset) await safeArea(p, inset, 34);
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e.message || e)));
  await p.goto(ORIGIN + '/');
  await settle(p, 1500);
  return { ctx, p, errors };
}

const frame = (p) => p.frames().find((f) => f.url().includes('/api/hassio_ingress/abcdefghijkl/'));

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

  // ---- an administrator, the dashboard on --------------------------------
  {
    const where = 'admin, dashboard on';
    const { ctx, p, errors } = await open(browser, {});
    const s = await p.evaluate(() => {
      const sh = window.__shell.shadowRoot;
      const f = sh.querySelector('iframe');
      const home = sh.querySelector('.home');
      const r = home.getBoundingClientRect();
      return { src: f.getAttribute('src') || '', framed: !f.hidden, homeShown: !home.hidden, top: Math.round(r.top),
               morph: !!home.querySelector('morph-boot'), shellProp: !!(home.querySelector('morph-boot') || {}).shell,
               session: window.__ws.some((m) => m.type === 'supervisor/api' && m.endpoint === '/ingress/session') };
    });
    // The cookie is scoped to /api/hassio_ingress/, so this page cannot read
    // it back; the browser says whether it was set.
    s.cookie = (await ctx.cookies(ORIGIN + '/api/hassio_ingress/abcdefghijkl/'))
      .map((c) => `${c.name}=${c.value}`).join('; ');
    if (!s.session) fail(where, 'no ingress session was asked for');
    if (!/ingress_session=sess-test/.test(s.cookie)) fail(where, `the ingress cookie is not set (${s.cookie})`);
    if (!s.framed || s.src !== '/api/hassio_ingress/abcdefghijkl/?shell=1') fail(where, `brAIn's page is not in the frame (${s.src})`);
    if (!s.homeShown || !s.morph) fail(where, 'Morph is not mounted as Home');
    if (s.top !== 56) fail(where, `Home does not start under brAIn's bar (top ${s.top})`);
    if (!s.shellProp) fail(where, 'Morph was not told brAIn\'s header is above it');
    const bar = await p.evaluate(() => { const r = window.__panel && window.__panel.shadowRoot; return r ? { brand: !!r.querySelector('.bar .brand'), menu: !!r.querySelector('.bar .menu') } : null; });
    if (!bar) fail(where, 'Morph\'s panel never drew');
    else if (bar.brand) fail(where, 'Morph still draws its own brand under brAIn\'s header');
    const f = frame(p);
    if (!f) fail(where, 'the framed page did not load');
    else {
      const got = await f.evaluate(() => window.__got.filter((m) => m.state).pop());
      if (!got || got.state.morph !== true || got.state.view !== 'home') fail(where, `the frame was not told the state: ${JSON.stringify(got)}`);
      await f.evaluate(() => window.__post({ show: 'panel' }));
      await settle(p, 200);
      if (!(await p.evaluate(() => window.__shell.shadowRoot.querySelector('.home').hidden))) fail(where, '"show panel" did not hide Home');
      await f.evaluate(() => window.__post({ show: 'home' }));
      await settle(p, 200);
      if (await p.evaluate(() => window.__shell.shadowRoot.querySelector('.home').hidden)) fail(where, '"show home" did not bring Home back');
      await f.evaluate(() => window.__post({ raise: true }));
      await settle(p, 150);
      if (!(await p.evaluate(() => window.__shell.classList.contains('raised')))) fail(where, 'a raise did not put the frame over Morph');
      await f.evaluate(() => window.__post({ raise: false }));
      await p.evaluate(() => { window.__menu = 0; window.__shell.addEventListener('hass-toggle-menu', () => { window.__menu++; }); });
      await f.evaluate(() => window.__post({ menu: true }));
      await settle(p, 150);
      if ((await p.evaluate(() => window.__menu)) !== 1) fail(where, '☰ did not ask Home Assistant to open its sidebar');
      await f.evaluate(() => window.__post({ bars: { top: 105, bottom: 0 } }));
      await settle(p, 150);
      const top = await p.evaluate(() => Math.round(window.__shell.shadowRoot.querySelector('.home').getBoundingClientRect().top));
      if (top !== 105) fail(where, `Home did not follow the bar's new height (${top})`);
      await p.evaluate(() => window.__panel && window.__panel.act('brain-open', { dataset: { v: 'dashboard' } }));
      await settle(p, 200);
      const open = await f.evaluate(() => window.__got.filter((m) => m.open).pop());
      if (!open || open.open.view !== 'settings' || open.open.sec !== 'dashboard') fail(where, `"See the changes" did not open ⚙ › Dashboard: ${JSON.stringify(open)}`);
      if (!(await p.evaluate(() => window.__shell.shadowRoot.querySelector('.home').hidden))) fail(where, 'opening brAIn\'s page left Home over it');
    }
    if (errors.length) fail(where, `page errors: ${errors.join(' | ')}`);
    await ctx.close();
  }

  // ---- an administrator, the dashboard off ------------------------------
  {
    const where = 'admin, dashboard off';
    const { ctx, p, errors } = await open(browser, { morph: false });
    const s = await p.evaluate(() => { const sh = window.__shell.shadowRoot; return { framed: !sh.querySelector('iframe').hidden, home: !sh.querySelector('.home').hidden, morph: !!sh.querySelector('morph-boot') }; });
    if (!s.framed) fail(where, 'brAIn\'s page is not shown');
    if (s.home || s.morph) fail(where, 'Home is there with the dashboard off');
    if (errors.length) fail(where, `page errors: ${errors.join(' | ')}`);
    await ctx.close();
  }

  // ---- somebody who is not an administrator -----------------------------
  {
    const where = 'not an administrator';
    const { ctx, p, errors } = await open(browser, { notAdmin: true, narrow: true }, 390);
    const s = await p.evaluate(() => {
      const sh = window.__shell.shadowRoot;
      const home = sh.querySelector('.home');
      const r = home.getBoundingClientRect();
      return { framed: !sh.querySelector('iframe').hidden, session: window.__ws.some((m) => m.type === 'supervisor/api'), home: !home.hidden, top: Math.round(r.top), bottom: Math.round(window.innerHeight - r.bottom) };
    });
    if (s.framed || s.session) fail(where, 'brAIn\'s page or an ingress session was opened for somebody who may not have one');
    if (!s.home || s.top !== 0 || s.bottom !== 0) fail(where, `Morph is not the whole page (top ${s.top}, bottom ${s.bottom})`);
    const bar = await p.evaluate(() => { const r = window.__panel && window.__panel.shadowRoot; return r ? { brand: ((r.querySelector('.bar .brand') || {}).textContent || '').trim(), menu: !!r.querySelector('.bar .menu') } : null; });
    if (!bar) fail(where, 'Morph\'s panel never drew');
    else {
      if (!/JUNIPER/.test(bar.brand)) fail(where, `Morph's own bar does not name the assistant (${bar.brand})`);
      if (!bar.menu) fail(where, 'there is no ☰ on a phone without brAIn\'s header');
    }
    if (errors.length) fail(where, `page errors: ${errors.join(' | ')}`);
    await ctx.close();
  }

  // ---- the header on the owner's phone, and a header that gets out of the way
  // The owner's iPhone, in the Home Assistant app's full screen: a 59px safe
  // area on top with the Dynamic Island in its middle (126px wide at 390).
  // The owner: the header "clashes with the Dynamic Island", "I don't like
  // those menu buttons up there all the time; maybe collapsible and goes
  // away when you're not at the top", and "on a phone the shell takes about
  // 170px before any content … Make it subtle, collapsible"; and "dragging
  // brAIn's header scrolls the outer window and cuts content off".
  const INSET = 59;
  const ISLAND = { left: 132, right: 258 };
  const CHROME_MAX = 60;
  const head = (f) => f.evaluate(() => {
    const shown = (n) => !!n && n.getClientRects().length > 0 && getComputedStyle(n).display !== 'none'
      && getComputedStyle(n).visibility !== 'hidden' && Number(getComputedStyle(n).opacity) > 0.1;
    const box = (n) => { const r = n.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height) }; };
    const bar = document.querySelector('.topbar');
    const cs = getComputedStyle(bar);
    // What stands between the header and the pane's first line: the
    // section control, a select, the search row.
    const rows = ['#segNav', '#segNavSel', '#reportSearch'].map((q) => document.querySelector(q))
      .filter((n) => shown(n) && !n.closest('.topbar') && getComputedStyle(n).position !== 'fixed');
    const strip = ['#shellMenu', '.topbar .brandlink', '#statusDot', '#settingsBtn']
      .map((q) => [q, document.querySelector(q)]).filter(([, n]) => shown(n)).map(([q, n]) => ({ q, ...box(n) }));
    const targets = [...bar.querySelectorAll('button, a, input')].filter(shown).map((n) => ({ q: n.id || n.className, ...box(n) }));
    const search = [...bar.querySelectorAll('button')].find((n) => shown(n) && /search/i.test(n.getAttribute('aria-label') || ''));
    const input = document.querySelector('#reportSearch');
    return {
      bar: box(bar), padTop: parseFloat(cs.paddingTop), hairline: parseFloat(cs.borderBottomWidth),
      motion: cs.transitionDuration, touchAction: cs.touchAction,
      chrome: box(bar).b + rows.reduce((a, n) => a + box(n).h, 0), rows: rows.map((n) => n.id),
      strip, targets, tabsTop: Math.min(...[...document.querySelectorAll('.viewtabs .viewtab')].filter(shown).map((n) => box(n).t)),
      settings: shown(document.querySelector('#settingsBtn')) && box(document.querySelector('#settingsBtn')).b > 1,
      search: search ? { id: search.id, ...box(search) } : null,
      input: shown(input) ? { ...box(input), font: parseFloat(getComputedStyle(input).fontSize), value: input.value } : null,
      overscroll: [getComputedStyle(document.documentElement).overscrollBehaviorY, getComputedStyle(document.body).overscrollBehaviorY],
      y: Math.round(window.scrollY), view: typeof currentView === 'string' ? currentView : '',
    };
  });
  // Scroll the page in the frame (or Morph's, on Home) in steps, the way a
  // thumb does: the header reads the direction, not one jump.
  const scrollFrame = async (f, by) => {
    await f.evaluate(async (d) => { const n = 8; for (let i = 0; i < n; i++) { window.scrollBy(0, d / n); await new Promise((r) => setTimeout(r, 30)); } }, by);
  };
  const scrollMorph = async (p, by) => {
    await p.evaluate(async (d) => { const sc = window.__panel.shadowRoot.querySelector('.scroll'); const n = 8; for (let i = 0; i < n; i++) { sc.scrollTop += d / n; await new Promise((r) => setTimeout(r, 30)); } }, by);
  };
  const homeTop = (p) => p.evaluate(() => Math.round(window.__shell.shadowRoot.querySelector('.home').getBoundingClientRect().top));
  async function getsOutOfTheWay(p, f, where, width, theme, touch, inset) {
    const shot = async (name) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/shell-${width}-${theme}-${name}.png` }); };
    // ---- Home: Morph draws no strip or safe-area padding of its own ----
    const mo = await p.evaluate(() => {
      const r = window.__panel.shadowRoot;
      const wrap = r.querySelector('.wrap');
      return { pad: parseFloat(getComputedStyle(wrap).paddingTop), first: Math.round(wrap.getBoundingClientRect().top), host: getComputedStyle(window.__shell).overscrollBehaviorY };
    });
    const top0 = await homeTop(p);
    if (mo.pad > 24 || mo.first - top0 > 1) fail(`${where}, Home`, `Morph pads its page ${mo.pad}px (starts ${mo.first - top0}px under brAIn's header): a second strip`);
    if (mo.host !== 'none') fail(`${where}, Home`, `the shell lets a drag run on into Home Assistant's window (overscroll-behavior ${mo.host})`);
    let h = await head(f);
    if (top0 !== h.bar.h) fail(`${where}, Home`, `Home starts at ${top0}, not under the ${h.bar.h}px header`);
    // ---- Home: scrolling Morph down hides the header, up brings it back
    await scrollMorph(p, 600);
    await settle(p, 450);
    h = await head(f);
    let t = await homeTop(p);
    if (h.bar.b > inset + 1 || h.settings) fail(`${where}, Home`, `scrolling the dashboard down leaves the header on screen (its foot at ${h.bar.b}px)`);
    if (t > inset + 1) fail(`${where}, Home`, `the dashboard does not take the header's place when it hides (Home starts at ${t}px)`);
    await shot('home-scrolled');
    await scrollMorph(p, -120);
    await settle(p, 450);
    h = await head(f);
    t = await homeTop(p);
    if (h.bar.t < 0 || !h.settings) fail(`${where}, Home`, 'scrolling the dashboard up does not bring the header back');
    if (t !== h.bar.h) fail(`${where}, Home`, `with the header back, Home starts at ${t}, not under it (${h.bar.h})`);
    await p.evaluate(() => { window.__panel.shadowRoot.querySelector('.scroll').scrollTop = 0; });
    // ---- Insights ----
    await f.evaluate(() => { switchView('insights'); window.scrollTo(0, 0); });
    await settle(p, 500);
    h = await head(f);
    const here = `${where}, Insights`;
    await shot('rest');
    if (touch) {
      // The island strip: the header starts at the top of the screen on its
      // own ground, the name left of the island, the status and ⚙ right of
      // it, nothing under the island itself, the tabs below the strip.
      if (h.bar.t !== 0) fail(here, `the header starts ${h.bar.t}px down, leaving the island strip without its ground`);
      if (h.hairline < 1) fail(here, 'the header has no hairline under it');
      for (const x of h.targets) {
        if (x.t < inset && x.r > ISLAND.left && x.l < ISLAND.right) fail(here, `${x.q} is under the Dynamic Island (${x.l}–${x.r} × ${x.t}–${x.b})`);
      }
      for (const x of h.strip) {
        if (x.t < 0 || x.b > inset + 1) fail(here, `${x.q} is not in the island strip (${x.t}–${x.b}, the strip is 0–${inset})`);
      }
      const brand = h.strip.find((x) => x.q === '.topbar .brandlink');
      if (!brand || brand.r > ISLAND.left) fail(here, `the name is not left of the island (${brand ? `${brand.l}–${brand.r}` : 'missing'})`);
      for (const q of ['#statusDot', '#settingsBtn']) {
        const x = h.strip.find((y) => y.q === q);
        if (!x || x.l < ISLAND.right) fail(here, `${q} is not right of the island (${x ? `${x.l}–${x.r}` : 'missing'})`);
      }
      if (h.tabsTop < inset) fail(here, `the tabs start at ${h.tabsTop}px, inside the island strip`);
      // Below the strip, at rest: at most 60px before the pane's first line.
      const below = h.chrome - inset;
      if (below > CHROME_MAX) fail(here, `${below}px of header and controls sit under the island strip before any content (${h.chrome}px in all; ${h.rows.join(', ') || 'the header alone'}), over ${CHROME_MAX}`);
      // The sections are in the tab row: the Insights tab opens them.
      await f.click('.viewtab[data-group="insights"]');
      await settle(p, 300);
      const secs = await f.evaluate(() => [...document.querySelectorAll('button, [role="tab"], option')].filter((n) => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden' && /^Needs you|^History/.test(n.textContent.trim()) && !n.closest('#subtabs')).map((n) => ({ t: n.textContent.trim(), h: Math.round(n.getBoundingClientRect().height), tag: n.tagName })));
      const hist = secs.find((x) => /^History/.test(x.t) && x.tag === 'BUTTON');
      if (!hist) fail(here, `pressing the Insights tab offers no History (${JSON.stringify(secs)})`);
      else {
        if (hist.h < 44) fail(here, `History in the section list is ${hist.h}px tall`);
        await shot('sections');
        await f.locator('button:visible', { hasText: /^History$/ }).first().click();
        await settle(p, 300);
        const v = await f.evaluate(() => currentView);
        if (v !== 'archive') fail(here, `History in the section list opened "${v}"`);
      }
      await f.evaluate(() => { switchView('insights'); window.scrollTo(0, 0); });
      await settle(p, 300);
      // The search is an icon in the header that opens the field.
      if (!h.search) fail(here, `with ${MANY_INSIGHTS.length} insight cards there is no search icon in the header`);
      else {
        if (h.search.w < 44 || h.search.h < 44) fail(here, `the search icon is ${h.search.w}×${h.search.h}`);
        await f.click(`#${h.search.id}`);
        await settle(p, 300);
        let s2 = await head(f);
        if (!s2.input) fail(here, 'pressing the search icon does not open the search field');
        else {
          if (s2.input.font < 16) fail(here, `the search field's text is ${s2.input.font}px (iOS zooms under 16)`);
          if (s2.input.l < 0 || s2.input.r > width) fail(here, 'the search field is cut off');
          await f.fill('#reportSearch', 'freezer');
          await settle(p, 200);
          const n = await f.evaluate(() => document.querySelectorAll('#grid > *').length);
          if (n >= MANY_INSIGHTS.length) fail(here, `searching "freezer" still shows ${n} cards`);
          await shot('search');
          await f.click(`#${h.search.id}`);
          await settle(p, 300);
          s2 = await head(f);
          const left = await f.evaluate(() => document.querySelector('#reportSearch').value);
          if (s2.input || left) fail(here, `pressing the search icon again leaves the field open ("${left}")`);
        }
      }
    }
    // ---- Insights: down hides the header, up brings it back, the top too
    await scrollFrame(f, 700);
    await settle(p, 450);
    h = await head(f);
    if (h.bar.b > inset + 1 || h.settings) fail(here, `scrolling down leaves the header on screen (its foot at ${h.bar.b}px, ⚙ ${h.settings ? 'shown' : 'gone'})`);
    if (inset && h.bar.b < inset - 1) fail(here, `the hidden header leaves the island strip bare (its foot at ${h.bar.b}px)`);
    await shot('scrolled');
    await scrollFrame(f, -120);
    await settle(p, 450);
    h = await head(f);
    if (h.bar.t < 0 || !h.settings) fail(here, `scrolling back up does not bring the header back (its top at ${h.bar.t}px)`);
    await shot('scrolledup');
    await scrollFrame(f, 300);
    await settle(p, 300);
    await f.evaluate(() => window.scrollTo(0, 0));
    await settle(p, 450);
    h = await head(f);
    if (h.bar.t < 0 || !h.settings) fail(here, 'reaching the top does not bring the header back');
    // ---- a drag on the header never moves Home Assistant's window --------
    if (touch) {
      if (h.overscroll.some((o) => o !== 'none')) fail(here, `brAIn's page lets a drag run on into the window around it (overscroll-behavior ${h.overscroll.join('/')})`);
      if (!/none|pinch-zoom/.test(h.touchAction)) fail(here, `a drag on the header is passed through (touch-action ${h.touchAction})`);
      await p.evaluate(() => { const d = document.createElement('div'); d.id = '__tall'; d.style.height = '1200px'; document.body.appendChild(d); window.scrollTo(0, 0); });
      // A thumb's drag, as the touchscreen sends it: dy < 0 is the finger
      // moving up, which scrolls a page down.
      const c = await p.context().newCDPSession(p);
      const drag = async (x, y, dy) => {
        await c.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
        for (let i = 1; i <= 12; i++) {
          await c.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y + (dy * i) / 12 }] });
          await settle(p, 16);
        }
        await c.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        await settle(p, 600);
      };
      await drag(width / 2, h.tabsTop + 20, -300);
      await drag(width / 2, h.tabsTop + 20, 300);
      const outer = await p.evaluate(() => window.scrollY);
      const under = await f.evaluate(() => window.scrollY);
      if (outer !== 0) fail(here, `dragging the header scrolled the window around brAIn by ${outer}px`);
      if (under !== 0) fail(here, `dragging the header scrolled the page under it by ${under}px`);
      await p.evaluate(() => window.scrollTo(0, 0));
      // On the pane's own text rather than a card's chart, which is a page
      // of its own with its own scrolling.
      const at = await f.evaluate((top) => { for (let y = top; y < innerHeight - 120; y += 10) { const e = document.elementFromPoint(innerWidth / 2, y); if (e && e.tagName !== 'IFRAME' && !e.closest('.topbar')) return y; } return 600; }, h.bar.b + 40);
      await drag(width / 2, at, -300);
      const inner = await f.evaluate(() => window.scrollY);
      const outer2 = await p.evaluate(() => window.scrollY);
      if (inner <= 0) fail(here, 'a drag on the pane does not scroll it');
      if (outer2 !== 0) fail(here, `a drag on the pane scrolled the window around brAIn by ${outer2}px`);
      await p.evaluate(() => { document.getElementById('__tall').remove(); window.scrollTo(0, 0); });
      await f.evaluate(() => window.scrollTo(0, 0));
      await settle(p, 400);
    }
    await f.evaluate(() => switchView('home'));
    await settle(p, 400);
  }

  // ---- one header, brAIn's real page, Morph's three themes ---------------
  const THEMES = { dark: '#0a0c0e', medium: '#2a2d31', light: '#ecebe6' };
  const SHOTS = process.env.SHELL_SHOT_DIR || '';
  const hex = (rgb) => { const m = String(rgb).match(/\d+(\.\d+)?/g) || []; return '#' + m.slice(0, 3).map((n) => Math.round(+n).toString(16).padStart(2, '0')).join(''); };
  for (const width of [390, 1200]) {
    for (const theme of Object.keys(THEMES)) {
      const where = `one header, ${width}px, ${theme}`;
      const touch = width <= 430;
      const inset = touch ? INSET : 0;
      const { ctx, p, errors } = await open(browser, { realFrame: true, theme, narrow: touch, insights: MANY_INSIGHTS }, width, touch, inset);
      const f = frame(p);
      if (!f) { fail(where, 'brAIn\'s page did not load in the frame'); await ctx.close(); continue; }
      try {
        await f.waitForFunction(() => typeof switchView === 'function' && document.querySelector('#homeTab') && !document.querySelector('#homeTab').hidden, null, { timeout: 6000 });
      } catch (e) { fail(where, 'the Home tab never appeared in brAIn\'s header'); }
      await settle(p, 600);
      // Every header on the screen: brAIn's bar, and any bar Morph draws.
      const look = async (view) => {
        const fr = await f.evaluate((ver) => {
          const shown = (n) => !!n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden' && getComputedStyle(n).display !== 'none';
          const bar = document.querySelector('.topbar');
          const br = bar.getBoundingClientRect();
          const inBar = (n) => { if (!n) return false; const r = n.getBoundingClientRect(); return shown(n) && r.top >= br.top - 1 && r.bottom <= br.bottom + 1; };
          const tabs = [...document.querySelectorAll('.viewtabs .viewtab')].filter(shown);
          const names = tabs.map((t) => (t.querySelector('span:not(.badge)') || t).textContent.trim());
          const tabbar = document.querySelector('.viewtabs');
          const lum = (c) => { const m = String(c).match(/\d+(\.\d+)?/g).slice(0, 3).map((v) => { v = +v / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]; };
          const ratio = (a, b) => { const x = lum(a); const y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
          // What a box is drawn on: its own background over its parents',
          // alpha and all (a bar that is 88% of the ground is not the ground).
          const ground = (n) => {
            const layers = [];
            for (; n; n = n.parentElement) {
              const m = (getComputedStyle(n).backgroundColor.match(/[\d.]+/g) || []).map(Number);
              const a = m.length > 3 ? m[3] : 1;
              if (m.length >= 3 && a > 0) { layers.push([m[0], m[1], m[2], a]); if (a >= 1) break; }
            }
            let c = [255, 255, 255];
            for (const [r, g, b, a] of layers.reverse()) c = [r * a + c[0] * (1 - a), g * a + c[1] * (1 - a), b * a + c[2] * (1 - a)];
            return `rgb(${c.map(Math.round).join(', ')})`;
          };
          const brand = bar.querySelector('.brandlink');
          const edit = document.querySelector('#shellEdit');
          const status = [document.querySelector('#statusDot'), ...document.querySelectorAll('.topbar .chip')].filter(inBar);
          const cut = [...bar.querySelectorAll('button, a, span')].filter((n) => shown(n) && n.scrollWidth > n.clientWidth + 1 && getComputedStyle(n).overflow === 'hidden').map((n) => n.id || n.className || n.textContent.trim().slice(0, 20));
          const small = [...bar.querySelectorAll('button, a')].filter(shown).map((n) => ({ n: n.id || n.textContent.trim().slice(0, 16) || n.className, h: Math.round(n.getBoundingClientRect().height), w: Math.round(n.getBoundingClientRect().width) })).filter((x) => x.h < 44 || x.w < 44);
          return {
            headers: [bar].filter(shown).length + [...document.querySelectorAll('header, [role="banner"]')].filter((n) => n !== bar && shown(n) && n.getBoundingClientRect().top < 4 && !n.closest('.topbar')).length,
            barH: Math.round(br.height), names, tabsInBar: tabs.every(inBar), tabbarFixed: shown(tabbar) && getComputedStyle(tabbar).position === 'fixed',
            bottomBar: tabs.some((t) => t.getBoundingClientRect().top > window.innerHeight / 2),
            settings: inBar(document.querySelector('#settingsBtn')),
            brand: shown(brand) ? brand.innerText.replace(/\s+/g, ' ').trim() : '', status: status.length,
            verInBar: [...bar.querySelectorAll('*')].some((n) => shown(n) && n.children.length === 0 && n.textContent.includes(ver)),
            verInSettings: (() => { const v = document.querySelector('#setModal #versionText'); return shown(v) && v.textContent.includes(ver); })(),
            edit: inBar(edit) ? edit.textContent.trim() : '',
            theme: document.documentElement.dataset.theme || '', ground: ground(document.body), barGround: ground(bar),
            plane: getComputedStyle(document.documentElement).getPropertyValue('--plane').trim(),
            tabInk: tabs.length ? ratio(getComputedStyle(tabs.find((t) => !t.classList.contains('active')) || tabs[0]).color, ground(bar)) : 0,
            bodyInk: ratio(getComputedStyle(document.body).color, getComputedStyle(document.documentElement).getPropertyValue('--plane').trim() ? ground(document.querySelector('main') || document.body) : 'rgb(255,255,255)'),
            sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
            cut, small, ver,
          };
        }, BRAIN_VERSION);
        const mo = await p.evaluate(() => {
          const sh = window.__shell.shadowRoot;
          const home = sh.querySelector('.home');
          const r = window.__panel && window.__panel.shadowRoot;
          const shown = (n) => !!n && n.getClientRects().length > 0 && getComputedStyle(n).display !== 'none';
          const hr = home.getBoundingClientRect();
          return { homeShown: !home.hidden, bars: r ? [...r.querySelectorAll('.bar')].filter(shown).length : -1,
                   theme: r ? ((r.querySelector('.morph') || {}).className || '') : '', bottomGap: Math.round(window.innerHeight - hr.bottom),
                   editing: !!(window.__panel && window.__panel.s && window.__panel.s.edit) };
        });
        const here = `${where}, ${view}`;
        const headers = fr.headers + (view === 'Home' && mo.homeShown ? mo.bars : 0);
        if (headers !== 1) fail(here, `${headers} headers are on screen (brAIn's ${fr.headers}, Morph's ${view === 'Home' ? mo.bars : 0}), not one`);
        if (fr.tabbarFixed || fr.bottomBar) fail(here, 'the tabs are a bar along the bottom rather than in the header');
        if (view === 'Home' && mo.bottomGap !== 0) fail(here, `Home stops ${mo.bottomGap}px above the bottom, where a tab bar was`);
        for (const n of ['Home', 'Insights', 'Ask', 'Memory']) if (!fr.names.includes(n)) fail(here, `the header has no ${n} (it has ${fr.names.join(', ')})`);
        if (!fr.tabsInBar) fail(here, 'a tab is outside the header');
        if (!fr.settings) fail(here, '⚙ is not in the header');
        // The name is the header's; the version moved to ⚙ (the owner: the
        // header should be "subtle"), so it is in Settings and not here.
        if (!/Juniper/.test(fr.brand)) fail(here, `the header does not say the name ("${fr.brand}")`);
        if (fr.verInBar) fail(here, 'the version is still in the header');
        if (view === 'Settings' && !fr.verInSettings) fail(here, `⚙ does not show the version ${fr.ver}`);
        if (!fr.status) fail(here, 'the header carries no status');
        if (view === 'Home' && fr.edit !== 'Edit') fail(here, `Morph's Edit is not in the header ("${fr.edit}")`);
        if (view !== 'Home' && fr.edit) fail(here, 'Edit is in the header on a brAIn tab');
        if (fr.theme !== theme) fail(here, `brAIn's page is in theme "${fr.theme}", not Morph's "${theme}"`);
        if (hex(fr.barGround) !== THEMES[theme]) fail(here, `the header's ground is ${hex(fr.barGround)}, not Morph's ${THEMES[theme]}`);
        if (view !== 'Home' && hex(fr.ground) !== THEMES[theme]) fail(here, `the page's ground is ${hex(fr.ground)}, not Morph's ${THEMES[theme]}`);
        if (!new RegExp(`t-${theme}`).test(mo.theme)) fail(here, `Morph drew in "${mo.theme}"`);
        if (fr.tabInk < 4.5) fail(here, `a tab's name is ${fr.tabInk.toFixed(2)}:1 against the header`);
        if (view !== 'Home' && fr.bodyInk < 4.5) fail(here, `the page's text is ${fr.bodyInk.toFixed(2)}:1 against its ground`);
        if (fr.sideways) fail(here, 'brAIn\'s page scrolls sideways');
        if (fr.cut.length) fail(here, `cut off in the header: ${fr.cut.join(', ')}`);
        if (touch && fr.small.length) fail(here, `under the 44px floor in the header: ${fr.small.map((x) => `${x.n} ${x.w}×${x.h}`).join(', ')}`);
        if (SHOTS) await p.screenshot({ path: `${SHOTS}/shell-${width}-${theme}-${view.toLowerCase()}.png` });
        return { fr, mo };
      };
      await look('Home');
      await getsOutOfTheWay(p, f, where, width, theme, touch, inset);
      // Edit in the one header puts Morph in edit mode.
      const editBtn = await f.$('#shellEdit');
      if (editBtn && await editBtn.isVisible()) {
        await editBtn.click();
        await settle(p, 300);
        const ed = await p.evaluate(() => !!(window.__panel && window.__panel.s && window.__panel.s.edit));
        if (!ed) fail(where, 'Edit in the header did not put Morph in edit mode');
        const done = await f.evaluate(() => (document.querySelector('#shellEdit') || {}).textContent || '');
        if (!/Done/.test(done)) fail(where, `while editing the header says "${done.trim()}", not Done`);
        await editBtn.click();
        await settle(p, 300);
      }
      for (const [view, name] of [['insights', 'Insights'], ['terminal', 'Ask'], ['memory', 'Memory']]) {
        await f.evaluate((v) => switchView(v), view);
        await settle(p, 400);
        await look(name);
      }
      await f.evaluate(() => openSettings());
      await settle(p, 500);
      await look('Settings');
      if (errors.length) fail(where, `page errors: ${errors.join(' | ')}`);
      await ctx.close();
    }
  }

  // ---- reduce motion: the header shows and hides, it does not slide ------
  {
    const where = 'reduce motion, 390px';
    const { ctx, p, errors } = await open(browser, { realFrame: true, theme: 'dark', narrow: true, insights: MANY_INSIGHTS }, 390, true, INSET, 'reduce');
    const f = frame(p);
    try {
      await f.waitForFunction(() => typeof switchView === 'function', null, { timeout: 6000 });
      await f.evaluate(() => switchView('insights'));
      await settle(p, 500);
      let h = await head(f);
      if (h.motion.split(',').some((d) => parseFloat(d) > 0)) fail(where, `the header still animates (${h.motion})`);
      await scrollFrame(f, 700);
      await settle(p, 100);
      h = await head(f);
      if (h.bar.b > INSET + 1) fail(where, 'scrolling down does not hide the header');
    } catch (e) { fail(where, `could not drive the page: ${String(e.message).split('\n')[0]}`); }
    if (errors.length) fail(where, `page errors: ${errors.join(' | ')}`);
    await ctx.close();
  }

  await browser.close();
  if (failures.length) {
    console.log('measure-shell: FAIL');
    for (const f of failures) console.log('  - ' + f);
    process.exit(1);
  }
  console.log('measure-shell: all checks passed (admin with and without the dashboard, somebody who is not an administrator, one header over brAIn\'s real page at 390 with a Dynamic Island and at 1200 in three themes, hiding on scroll, and reduce motion)');
})();
