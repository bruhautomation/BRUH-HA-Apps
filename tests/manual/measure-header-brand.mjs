// The top bar's mark (⚙ › Personality › Header): brAIn's logo, the
// assistant's name, or the house's own text and/or picture. The panel's JS
// needs a live backend, so app.js is not run; instead `headerMark` and
// `applyHeader` are lifted out of it and run in the page against a stub
// `state`, so the choice AND the CSS it lands on are both what ships.
//
// At 390 (touch, in the shell, where the mark must stay left of the island)
// and 1200, for every choice: the right mark is the one showing and no other,
// the picture is the wordmark's height (28px, 24 on a phone in the shell),
// nothing is wider than the in-shell cap (70px) there, and nothing overflows.
//
//   node tests/manual/measure-header-brand.mjs        (SHOT_DIR=… saves shots)
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const PANEL = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../brain/panel');
const SHOTS = process.env.SHOT_DIR || '';
const js = fs.readFileSync(path.join(PANEL, 'app.js'), 'utf8');
const lift = (name) => {
  const start = js.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} is not in app.js`);
  const end = js.indexOf('\n}\n', start) + 3;
  return js.slice(start, end);
};
const SRC = `${lift('headerMark')}\n${lift('applyHeader')}\nwindow.applyHeader = applyHeader;`;
// A real 60x20 PNG (azure), so the image decodes and has a width.
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADwAAAAUCAYAAADRA14pAAAAN0lEQVR4nO3PMQ0AMAwEsSAJ9VIrkwZGpY+H28/V575N1e8BYGBgYGBg4D0BpwecHnB6wOkBpzfUHzv1WOCGQwAAAABJRU5ErkJggg==';

const CASES = [
  { name: 'default, personality off', st: { features: {}, header: {} }, want: 'logo' },
  { name: 'default, personality on', st: { features: { personality: true, name: 'Juniper' }, header: {} }, want: 'text:Juniper' },
  { name: 'logo chosen while named', st: { features: { personality: true, name: 'Juniper' }, header: { brand: 'logo' } }, want: 'logo' },
  { name: 'name chosen, no name', st: { features: {}, header: { brand: 'name' } }, want: 'logo' },
  { name: 'custom text', st: { features: {}, header: { brand: 'custom', text: 'The Hendersons Home' } }, want: 'text:The Hendersons Home' },
  { name: 'custom picture', st: { features: {}, header: { brand: 'custom', image: PNG } }, want: 'img' },
  { name: 'custom both', st: { features: {}, header: { brand: 'custom', text: 'Casa', image: PNG } }, want: 'both' },
  { name: 'custom empty', st: { features: {}, header: { brand: 'custom' } }, want: 'logo' },
];
const SHELLS = [{ width: 390, touch: true, shell: true }, { width: 1200, touch: false, shell: false }];

async function run({ st, shell, src }) {
  const root = document.documentElement;
  if (shell) root.classList.add('in-shell');
  window.state = { status: st };
  window.$ = (s) => document.querySelector(s);
  new Function(src)();
  const f = st.features || {};
  if (f.personality && f.name) root.classList.add('named');
  window.applyHeader();
  const pic = document.querySelector('#brandImg');
  if (pic.getAttribute('src')) await pic.decode().catch(() => {});
  const vis = (el) => el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
  const wm = document.querySelector('.wordmark');
  const nm = document.querySelector('#brandName');
  const im = document.querySelector('#brandImg');
  const mk = document.querySelector('#brandMark').getBoundingClientRect();
  const imr = vis(im) ? im.getBoundingClientRect() : null;
  const nmr = vis(nm) ? nm.getBoundingClientRect() : null;
  const kids = [...document.querySelector('.topbar').children]
    .filter((e) => getComputedStyle(e).display !== 'none').map((e) => e.getBoundingClientRect());
  return {
    logo: vis(wm), text: vis(nm) ? nm.textContent : null, img: !!imr,
    imgH: imr ? Math.round(imr.height) : 0, imgW: imr ? Math.round(imr.width) : 0,
    nameW: nmr ? Math.round(nmr.width) : 0,
    markRight: Math.round(mk.right), markH: Math.round(mk.height),
    docW: root.scrollWidth, innerW: window.innerWidth,
    escaped: kids.some((r) => r.right > window.innerWidth + 0.5),
  };
}

(async () => {
  const browser = await chromium.launch(
    process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const html = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8');
  const bad = [];
  for (const sh of SHELLS) {
    const ctx = await browser.newContext({ viewport: { width: sh.width, height: 700 }, hasTouch: sh.touch });
    const page = await ctx.newPage();
    await page.route('**/*.js', (route) => route.abort());
    for (const c of CASES) {
      await page.setContent(html, { waitUntil: 'load' });
      await page.addStyleTag({ path: path.join(PANEL, 'style.css') });
      const m = await page.evaluate(run, { st: c.st, shell: sh.shell, src: SRC });
      const fails = [];
      const want = c.want;
      if (want === 'logo' && !(m.logo && !m.text && !m.img)) fails.push('expected the wordmark alone');
      if (want.startsWith('text:') && !(m.text === want.slice(5) && !m.logo && !m.img)) fails.push(`expected the text "${want.slice(5)}" alone, got ${JSON.stringify(m)}`);
      if (want === 'img' && !(m.img && !m.logo && !m.text)) fails.push('expected the picture alone');
      if (want === 'both' && !(m.img && m.text && !m.logo) && !(sh.shell && m.img && !m.logo)) fails.push('expected picture and text');
      if (m.img) {
        const h = sh.shell && sh.width <= 640 ? 24 : 28;
        if (m.imgH !== h) fails.push(`picture is ${m.imgH}px tall, want ${h}`);
        if (sh.shell && m.imgW > 70) fails.push(`picture is ${m.imgW}px wide past the island cap`);
      }
      if (sh.shell && m.nameW > 70) fails.push(`text is ${m.nameW}px wide past the island cap`);
      if (m.docW > m.innerW || m.escaped) fails.push('overflows the screen');
      if (m.markH < 44) fails.push(`mark target is ${m.markH}px tall`);
      if (fails.length) bad.push(`${sh.width} ${c.name}: ${fails.join('; ')}`);
      console.log(`${fails.length ? 'FAIL' : 'ok  '} ${sh.width} ${c.name}`);
      if (SHOTS) {
        fs.mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({ path: path.join(SHOTS, `${sh.width}-${c.name.replace(/[^a-z]+/gi, '-')}.png`), clip: { x: 0, y: 0, width: sh.width, height: 120 } });
      }
    }
    await ctx.close();
  }
  await browser.close();
  if (bad.length) { console.error('\n' + bad.join('\n')); process.exit(1); }
  console.log('\nheader brand: every choice draws the right mark');
})();
