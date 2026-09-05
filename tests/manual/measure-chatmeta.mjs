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


// ---------------------------------------------------------------------------
// The second pass: what a conversation row says about its own live session.
//
// A row can carry two marks — a quiet "answering…" while a turn it is
// writing runs on in the background, and a badge when it is waiting on a
// person. Both are new, both sit beside a title that is already competing
// for the width, and the surface differs by screen: the rail is
// display:none below 1100px, so on a phone the ⋯ dialog is the only place
// these can be read. So both are measured, at the width each one is the
// answer for.
//
// Unlike the pass above this drives the panel's REAL renderers behind a
// stubbed fetch (the same arrangement measure-activity.mjs uses): a copy of
// renderChatRail in this file would only ever agree with itself.
const LIVE_WIDTHS = [390, 1200];
const MIN_TARGET = 44;

const CONVS = [
  { id: 'c-busy', title: 'Why does the porch light come on at three in the '
      + 'afternoon when nobody is home', modified: 0, age: '2 min ago',
    source: 'you', live: true, busy: true, needs_ok: false },
  { id: 'c-ask', title: 'Tidy up the kitchen automations', modified: 0,
    age: '9 min ago', source: 'you', live: true, busy: false, needs_ok: true },
  { id: 'c-live', title: 'Bedroom thermostat schedule', modified: 0,
    age: '1 h ago', source: 'you', live: true, busy: false, needs_ok: false },
  { id: 'c-cold', title: 'An older one nothing is holding open', modified: 0,
    age: '3 d ago', source: 'you', live: false, busy: false, needs_ok: false },
];
const SESSIONS = CONVS.filter((c) => c.live).map((c) => ({
  session_id: c.id, state: c.busy ? 'busy' : 'ready', live: true,
  busy: c.busy, needs_ok: c.needs_ok, attached: c.id === 'c-live',
  title: c.title, busy_since: 0, last_activity: 0,
}));

const LIVE_STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/chat/conversations')) {
    return answer({ conversations: ${JSON.stringify(CONVS)},
                    current: 'c-live',
                    sources: [{ id: 'you', label: 'Chats', blurb: '', count: 4 }],
                    sessions: ${JSON.stringify(SESSIONS)}, max_sessions: 3 });
  }
  if (p.includes('api/chat/state')) {
    return answer({ type: 'snapshot', events: [], state: 'ready', error: '',
                    session_id: 'c-live', info: {}, commands: [], context: {},
                    cli: [], models: [], chat_model: '', default_model: '',
                    default_model_label: '', permission: null,
                    sessions: ${JSON.stringify(SESSIONS)}, max_sessions: 3 });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/settings')) return answer({ settings: {}, usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

async function livePass(browser, note) {
  for (const width of LIVE_WIDTHS) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
    await page.addInitScript(LIVE_STUB);
    await page.goto(`file://${path.join(PANEL, 'index.html')}`);
    await page.click('.viewtab[data-view="terminal"]');

    // The rail on a wide screen, the ⋯ dialog on a phone — whichever of the
    // two a person at this width actually has.
    const wide = await page.evaluate(() =>
      getComputedStyle(document.querySelector('#chatRail')).display !== 'none');
    const selector = wide ? '#chatRailList .crrow' : '#convList .crrow';
    await page.evaluate(async (isWide) => {
      chatState.sessionId = 'c-live';
      if (isWide) await refreshChatRail();
      else await openConversations();
    }, wide);
    await page.waitForSelector(selector);

    const m = await page.evaluate((sel) => {
      const rows = [...document.querySelectorAll(sel)];
      const host = rows[0].parentElement.getBoundingClientRect();
      return {
        surface: sel,
        hostRight: host.right,
        rows: rows.map((r) => {
          const box = r.getBoundingClientRect();
          const mark = r.querySelector('.crbusy, .crask');
          const title = r.querySelector('.ctitle');
          const ms = mark && getComputedStyle(mark);
          return {
            id: r.querySelector('.critem, .convitem').textContent.slice(0, 24),
            mark: mark ? mark.className : '',
            markText: mark ? mark.textContent.trim() : '',
            markShown: !!(ms && ms.display !== 'none'
                          && ms.visibility !== 'hidden' && Number(ms.opacity) > 0),
            markRight: mark ? mark.getBoundingClientRect().right : 0,
            titleRight: title ? title.getBoundingClientRect().right : 0,
            h: Math.round(box.height),
            right: box.right,
          };
        }),
        docWidth: document.documentElement.scrollWidth,
      };
    }, selector);

    const marks = m.rows.map((r) => r.mark).join(' ');
    if (!/crbusy/.test(marks)) note(`${width}px`, 'no row says it is answering');
    if (!/crask/.test(marks)) note(`${width}px`, 'no row says it needs an OK');

    // The marks have to survive a turn ending. `chatState.live` is the
    // message node partial text streams into and is set to null when an
    // answer completes; the marks live in `chatState.liveSessions`. For a
    // release the two shared one name — the second definition in the
    // literal won, so streamed text rendered into a plain object and the
    // rail threw on the first repaint after a turn. A repaint here, with no
    // fetch to rebuild the map, is exactly that moment.
    let after = -1;
    try {
      after = await page.evaluate((isWide) => {
        chatState.live = null;
        chatState.liveText = '';
        if (isWide) renderChatRail(); else renderConvModal();
        return [...document.querySelectorAll('.crbusy, .crask')].length;
      }, wide);
    } catch (e) {
      note(`${width}px`, `repainting after a turn ended threw: ${e.message.split('\n')[0]}`);
    }
    if (after >= 0 && after < 2) {
      note(`${width}px`, `the marks did not survive a turn ending: ${after} left`);
    }
    // Three live rows, two marks: a row whose session is live but quiet is
    // deliberately unmarked, because "has a process" is not news.
    if (m.rows.filter((r) => r.mark).length !== 2) {
      note(`${width}px`, `${m.rows.filter((r) => r.mark).length} marks, expected 2`);
    }
    for (const row of m.rows) {
      if (row.mark && !row.markShown) {
        note(`${width}px`, `${row.id}: the mark is hidden rather than shown`);
      }
      if (row.mark && !row.markText) {
        note(`${width}px`, `${row.id}: a mark with no words in it`);
      }
      if (row.mark && row.markRight > m.hostRight + 0.5) {
        note(`${width}px`, `${row.id}: the mark hangs off the list`);
      }
      if (row.right > m.hostRight + 0.5) {
        note(`${width}px`, `${row.id}: the row overflows the list`);
      }
      if (row.h < MIN_TARGET) {
        note(`${width}px`, `${row.id} is ${row.h}px, under ${MIN_TARGET}`);
      }
    }
    if (m.docWidth > width + 0.5) {
      note(`${width}px`, `page scrolls sideways (${m.docWidth}px)`);
    }
    console.log(`${String(width).padStart(5)} ${m.surface.padEnd(20)} `
      + m.rows.map((r) => r.markText || '—').join(' | '));
    await context.close();
  }
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

  console.log('\nwidth surface              row marks');
  const failures = [];
  await livePass(browser, (where, message) => failures.push(`${where}: ${message}`));
  failures.forEach((f) => console.log('  ' + f));
  console.log(failures.length
    ? `\n${failures.length} problem(s) with the live-session marks`
    : `\nboth widths: "answering…" and "Needs your OK" render inside the row`);

  await browser.close();
  process.exit(bad || failures.length ? 1 : 0);
})();
