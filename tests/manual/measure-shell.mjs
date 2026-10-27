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
//     with its own bar's name and no frame.
//
// Exits non-zero with every failure listed.
import { chromium } from 'playwright';
import { ORIGIN, route } from './morph-fixture.mjs';

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);
const settle = (p, ms) => p.waitForTimeout(ms);

async function open(browser, opts, width = 1200) {
  const ctx = await browser.newContext({ viewport: { width, height: 860 } });
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

  await browser.close();
  if (failures.length) {
    console.log('measure-shell: FAIL');
    for (const f of failures) console.log('  - ' + f);
    process.exit(1);
  }
  console.log('measure-shell: all checks passed (admin with and without the dashboard, and somebody who is not an administrator)');
})();
