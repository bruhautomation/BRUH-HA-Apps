import { chromium } from 'playwright';
import { route, ORIGIN } from './morph-fixture.mjs';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] });
for (const [w,h,touch] of [[390,844,true],[1200,860,false]]) {
const ctx = await browser.newContext({ viewport: { width: w, height: h }, ...(touch ? { hasTouch: true, isMobile: true } : {}) });
await route(ctx, { narrow: touch, shell: true });
const p = await ctx.newPage();
await p.goto(ORIGIN + '/');
await p.waitForFunction(() => window.__panel && window.__panel.data);
await p.waitForTimeout(1500);
await p.evaluate(() => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), fold_rooms: false }; P._forceApply = true; P.engine.invalidate(); P.schedule(); });
await p.waitForTimeout(1500);
for (const th of ['dark','medium','light']) {
  await p.evaluate((th) => { const P = window.__panel; P.data.state.settings = { ...(P.data.state.settings || {}), theme: th }; P.schedule(); }, th);
  await p.waitForTimeout(800);
  const out = await p.evaluate(() => { const R = window.__panel.shadowRoot; const o = []; R.querySelectorAll('.glab').forEach((g) => { const key = g.dataset.glab; const bg = R.querySelector(`[data-gbg="${CSS.escape(key)}"]`); const sec = g.closest('[data-sec]'); o.push([g.textContent, sec.dataset.sec, getComputedStyle(g).color, bg ? getComputedStyle(bg).backgroundColor + ' ' + getComputedStyle(bg).backgroundImage.slice(0,60) : null, getComputedStyle(sec.querySelector('.secbg')).backgroundImage.slice(0,80), getComputedStyle(g).opacity, getComputedStyle(sec).opacity]); }); return o; });
  console.log(w, th, JSON.stringify(out.filter((x)=>/^(People|Comfort|Lights|Alarm|Doors|Routines)$/.test(x[0]))));
}
await ctx.close(); }
await browser.close();
