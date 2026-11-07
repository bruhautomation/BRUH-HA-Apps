// measure-shell-fit.mjs — brAIn's sidebar panel stays put on a phone.
//
//   node tests/manual/measure-shell-fit.mjs        (CHROMIUM_PATH if needed)
//
// Two things the owner saw in the Home Assistant app on an iPhone:
//
//   * #689: the panel could be dragged so that Home Assistant's OWN page
//     scrolled by the safe-area inset, shifting brAIn's header, and nothing
//     inside the panel could scroll it back. The shell (shell.js) was sized
//     to the viewport (100dvh) rather than to the space Home Assistant gives
//     it, so whatever sits above it made Home Assistant's scroller overflow.
//     Here the shell is put under a 47px strip, inside an outer scroller
//     the way Home Assistant's layout holds a panel, and this fails on any
//     overflow of the page or of an ancestor, and on a scroll of the window
//     or an ancestor that does not go straight back to 0.
//   * #690: scrolling the dashboard down hides brAIn's tab row, Home moves
//     up and grows, and the room rail (rail.js, `.srail`) grew with it, so
//     its notches resized and its floor names drifted. This hides and shows
//     the tab row and fails when any notch moves or changes size on screen.
//
// Exits non-zero with every failure listed.
import { chromium } from 'playwright';
import { ORIGIN, route, safeArea } from './morph-fixture.mjs';

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);
const settle = (p, ms) => p.waitForTimeout(ms);
const frame = (p) => p.frames().find((f) => f.url().includes('/api/hassio_ingress/abcdefghijkl/'));

async function open(browser, width, touch) {
  const ctx = await browser.newContext({ viewport: { width, height: 844 }, hasTouch: touch, isMobile: touch });
  await route(ctx, { shell: true, narrow: touch });
  const p = await ctx.newPage();
  if (touch) await safeArea(p, 47, 34);
  const errors = [];
  p.on('pageerror', (e) => errors.push(String(e.message || e)));
  await p.goto(ORIGIN + '/');
  await settle(p, 1500);
  return { ctx, p, errors };
}

// Every scroll position from the shell up through the composed tree, and
// the page's.
const SCROLLS = () => {
  const out = [];
  let n = window.__shell;
  while (n) {
    const up = n.parentNode || (n.getRootNode && n.getRootNode().host) || null;
    n = up && up.nodeType === 11 ? up.host : up;
    if (n && n.nodeType === 1) out.push({ tag: n.tagName.toLowerCase() + (n.id ? '#' + n.id : ''), top: n.scrollTop, over: n.scrollHeight - n.clientHeight });
  }
  const se = document.scrollingElement;
  out.push({ tag: 'document', top: se.scrollTop, over: se.scrollHeight - se.clientHeight });
  return out;
};

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

  // ---- #689: the shell fits the space it is given -------------------------
  for (const [width, touch] of [[390, true], [1200, false]]) {
    const where = `fit ${width}`;
    const { ctx, p, errors } = await open(browser, width, touch);
    // Home Assistant's frame of a panel: a scroller the height of the
    // screen, a strip above the panel (the inset, a toolbar) inside it.
    await p.evaluate(() => {
      document.documentElement.style.margin = '0';
      document.body.style.margin = '0';
      const outer = document.createElement('div');
      outer.id = 'haouter';
      outer.style.cssText = 'height:100vh;height:100dvh;overflow:auto';
      const strip = document.createElement('div');
      strip.style.cssText = 'height:47px';
      document.body.appendChild(outer);
      outer.appendChild(strip);
      outer.appendChild(window.__shell);
    });
    await settle(p, 600);
    let s = await p.evaluate(SCROLLS);
    s.filter((x) => x.over > 0).forEach((x) => fail(where, `${x.tag} overflows by ${x.over}px around the shell`));
    // A drag that did reach Home Assistant's page anyway: it goes back.
    await p.evaluate(() => { document.querySelector('#haouter').scrollTop = 40; window.scrollTo(0, 40); });
    await settle(p, 200);
    s = await p.evaluate(SCROLLS);
    s.filter((x) => x.top !== 0).forEach((x) => fail(where, `${x.tag} stayed scrolled to ${x.top}px`));
    if (touch) {
      // A drag on the header and on Morph's pane moves nothing outside.
      for (const [x, y] of [[200, 30], [200, 500]]) {
        await p.touchscreen.tap(x, y).catch(() => {});
        await p.mouse.move(x, y); await p.mouse.down(); await p.mouse.move(x, y - 300, { steps: 8 }); await p.mouse.up();
        await settle(p, 200);
        s = await p.evaluate(SCROLLS);
        s.filter((v) => v.top !== 0).forEach((v) => fail(where, `a drag at ${y} left ${v.tag} scrolled to ${v.top}px`));
      }
    }
    if (errors.length) fail(where, 'page errors: ' + errors.join(' | '));
    await ctx.close();
  }

  // ---- #690: the rail stays where it is when the tab row hides ------------
  {
    const where = 'rail 390';
    const { ctx, p, errors } = await open(browser, 390, true);
    const f = frame(p);
    const rail = () => p.evaluate(() => {
      const r = window.__panel && window.__panel.shadowRoot.querySelector('.srail');
      if (!r || !r.offsetHeight) return null;
      const box = r.getBoundingClientRect();
      return { top: Math.round(box.top), h: Math.round(box.height),
               notches: [...r.querySelectorAll('.srnotches i')].map((i) => { const b = i.getBoundingClientRect(); return [Math.round(b.top), Math.round(b.height)]; }) };
    });
    const nudge = () => p.evaluate(async () => { const sc = window.__panel.shadowRoot.querySelector('.scroll'); sc.scrollTop += 40; await new Promise((r) => setTimeout(r, 120)); sc.scrollTop -= 1; await new Promise((r) => setTimeout(r, 120)); });
    await f.evaluate(() => window.__post({ bars: { top: 98, bottom: 0, hidden: false } }));
    await settle(p, 500);
    await nudge();
    const shown = await rail();
    if (!shown || !shown.notches.length) fail(where, 'no rail with notches on a phone');
    else {
      await f.evaluate(() => window.__post({ bars: { top: 52, bottom: 0, hidden: true } }));
      await settle(p, 500);
      await nudge();
      const hidden = await rail();
      if (JSON.stringify(hidden) !== JSON.stringify(shown)) fail(where, `the rail moved when the tab row hid: ${JSON.stringify(shown)} → ${JSON.stringify(hidden)}`);
      await f.evaluate(() => window.__post({ bars: { top: 98, bottom: 0, hidden: false } }));
      await settle(p, 500);
      await nudge();
      const back = await rail();
      if (JSON.stringify(back) !== JSON.stringify(shown)) fail(where, `the rail moved when the tab row came back: ${JSON.stringify(shown)} → ${JSON.stringify(back)}`);
    }
    if (errors.length) fail(where, 'page errors: ' + errors.join(' | '));
    await ctx.close();
  }

  await browser.close();
  if (failures.length) { console.log(failures.join('\n')); process.exit(1); }
  console.log('measure-shell-fit: ok');
})();
