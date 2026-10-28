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
//     tab — the assistant's name and version, the status, and Home ·
//     Insights · Ask · Memory · ⚙ inside it, Morph's Edit there on Home and
//     no bar of Morph's own; no tab bar along the bottom; brAIn's page in
//     the same theme as Morph (its ground is Morph's #0A0C0E, #2A2D31 or
//     #ECEBE6) and legible in it; nothing cut off, no sideways scroll, every
//     target at the floor. The owner: "there are two headers … merge them".
//     SHELL_SHOT_DIR=<dir> keeps a picture of each.
//
// Exits non-zero with every failure listed.
import { chromium } from 'playwright';
import { ORIGIN, route, BRAIN_VERSION } from './morph-fixture.mjs';

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);
const settle = (p, ms) => p.waitForTimeout(ms);

async function open(browser, opts, width = 1200, touch = false) {
  const ctx = await browser.newContext({ viewport: { width, height: 860 }, hasTouch: touch, isMobile: touch });
  await route(ctx, { ...opts, shell: true });
  const p = await ctx.newPage();
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

  // ---- one header, brAIn's real page, Morph's three themes ---------------
  const THEMES = { dark: '#0a0c0e', medium: '#2a2d31', light: '#ecebe6' };
  const SHOTS = process.env.SHELL_SHOT_DIR || '';
  const hex = (rgb) => { const m = String(rgb).match(/\d+(\.\d+)?/g) || []; return '#' + m.slice(0, 3).map((n) => Math.round(+n).toString(16).padStart(2, '0')).join(''); };
  for (const width of [390, 1200]) {
    for (const theme of Object.keys(THEMES)) {
      const where = `one header, ${width}px, ${theme}`;
      const touch = width <= 430;
      const { ctx, p, errors } = await open(browser, { realFrame: true, theme, narrow: touch }, width, touch);
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
          const brand = document.querySelector('#versionChip');
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
        if (!/Juniper/.test(fr.brand) || !fr.brand.includes(fr.ver)) fail(here, `the header does not say the name and version ("${fr.brand}")`);
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

  await browser.close();
  if (failures.length) {
    console.log('measure-shell: FAIL');
    for (const f of failures) console.log('  - ' + f);
    process.exit(1);
  }
  console.log('measure-shell: all checks passed (admin with and without the dashboard, somebody who is not an administrator, and one header over brAIn\'s real page at 390 and 1200 in three themes)');
})();
