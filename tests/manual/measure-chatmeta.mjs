// Render the Terminal tab in chat mode and assert the meta line under the
// composer — the model name and the context pill — is actually visible, at
// every width, top to bottom.
//
// It wasn't, anywhere, and worst on a wide screen. #viewTerminal cancels
// .wrap's padding with negative margins; body.term-open zeroes the wrap's
// bottom padding, but the view kept a negative BOTTOM margin, which shortens
// .wrap — whose overflow:hidden then clipped the last ~20px of the view.
// That was the meta line, half-swallowed. A second 6px came from scoping the
// -12px margins to the bar's breakpoint (1239px) when the padding they
// cancel changes at 640px. Geometry alone can't catch either: the line's
// getBoundingClientRect was in the right place, it just wasn't painted — so
// this measures with elementFromPoint, which sees clipping.
//
// The panel's JS needs a live backend, so it is skipped and the state set by
// hand, syncBarHeight included (--bar-h is written from the measured bar,
// exactly as app.js does it).
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const PANEL = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../brain/panel');
const OUT = process.env.CHATMETA_SHOT_DIR || '';

const WIDTHS = [320, 390, 480, 640, 641, 800, 1000, 1100, 1239, 1240, 1400, 1440, 1920, 2560];
const KEEP_SHOTS = new Set([390, 800, 1440]);

function probe() {
  const $ = (s) => document.querySelector(s);
  // what switchView('terminal') does
  document.body.classList.add('term-open');
  document.querySelectorAll('.view').forEach((v) =>
    v.classList.toggle('active', v.id === 'viewTerminal'));
  // the meta line as the live panel shows it after the first turn
  $('#chatMeta').classList.remove('hidden');
  $('#chatModel').textContent = 'Claude Sonnet 5';
  $('#chatCtx').classList.remove('hidden');
  $('#chatCtx').textContent = '132k / 1000k context · 13%';
  const msg = document.createElement('div');
  msg.className = 'msg bot';
  msg.textContent = 'Sample answer. '.repeat(80);
  $('#chatLog').appendChild(msg);
  // what syncBarHeight does
  const h = Math.round($('.topbar').getBoundingClientRect().height);
  if (h > 0) document.documentElement.style.setProperty('--bar-h', h + 'px');

  const meta = $('#chatMeta').getBoundingClientRect();
  const x = Math.round(meta.left + Math.min(80, meta.width / 2));
  const inMeta = (y) => {
    const el = document.elementFromPoint(x, Math.round(y));
    return !!el && !!el.closest('#chatMeta');
  };
  return {
    bar: h,
    metaTop: Math.round(meta.top),
    metaBottom: Math.round(meta.bottom),
    inViewport: meta.bottom <= window.innerHeight + 0.5,
    // Painted, not merely positioned: the top of the line, its middle, and
    // its last text pixels all have to hit the meta line itself.
    painted: inMeta(meta.top + 2) && inMeta((meta.top + meta.bottom) / 2)
      && inMeta(meta.bottom - 3),
  };
}

(async () => {
  const browser = await chromium.launch(
    process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const page = await browser.newPage();
  await page.route('**/*.js', (route) => route.abort());
  const html = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8');

  console.log('width   bar  metaTop..Bottom  verdict');
  let bad = 0;
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 760 });
    await page.setContent(html, { waitUntil: 'load' });
    await page.addStyleTag({ path: path.join(PANEL, 'style.css') });
    const m = await page.evaluate(probe);
    const ok = m.inViewport && m.painted;
    if (!ok) bad++;
    console.log(
      `${String(width).padStart(5)} ${String(m.bar).padStart(5)}  `
      + `${String(m.metaTop).padStart(7)}..${String(m.metaBottom).padEnd(7)}  `
      + (ok ? 'ok' : [!m.inViewport && 'BELOW VIEWPORT',
                      !m.painted && 'CLIPPED'].filter(Boolean).join(' ')));
    if (OUT && KEEP_SHOTS.has(width)) {
      await page.screenshot({ path: path.join(OUT, `chatmeta-${width}.png`) });
    }
  }
  console.log(bad
    ? `\n${bad}/${WIDTHS.length} width(s) clip the meta line`
    : `\nall ${WIDTHS.length} widths: the model and context line is fully visible`);

  await browser.close();
  process.exit(bad ? 1 : 0);
})();
