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
// The second pass: what a conversation row says about its own session.
//
// Every row says which of seven states it is in, out of one server-side
// derivation (`row_state`): a live process is "Live", one answering says
// so, one waiting on a person carries the badge, one the cap paused says
// "Paused to make room", one whose context Claude Code no longer holds
// says "Context lost", a card run is a "Record" — and a plainly paused
// conversation, the ordinary case, draws nothing. They sit beside a title
// that is already competing for the width, and the surface differs by
// screen: the rail is display:none below 1100px, so on a phone the ⋯
// dialog is the only place these can be read. So all of them are measured,
// at the width each surface is the answer for.
//
// Unlike the pass above this drives the panel's REAL renderers behind a
// stubbed fetch (the same arrangement measure-activity.mjs uses): a copy of
// renderChatRail in this file would only ever agree with itself.
const LIVE_WIDTHS = [390, 1200];
const MIN_TARGET = 44;

// The server's own vocabulary, as `chat_session.ROW_STATES` ships it.
const ROW_STATES = {
  live: { label: 'Live', hint: 'Ready' },
  answering: { label: 'Answering…', hint: 'Claude is answering' },
  needs_ok: { label: 'Needs your OK', hint: 'Claude is waiting for your approval' },
  paused: { label: '', hint: 'Your next message resumes this conversation with its context' },
  paused_room: { label: 'Paused to make room',
    hint: 'brAIn keeps 3 chats running at once. Sending resumes this one and '
      + 'pauses the quietest' },
  context_lost: { label: 'Context lost',
    hint: 'Claude Code no longer has this conversation. You can read it; a new '
      + 'message starts fresh from here' },
  record: { label: 'Record', hint: 'A card run, shown to be read. It cannot be continued' },
};
const rs = (state) => ({ state, ...ROW_STATES[state] });
// Which pill class each state draws, and the one that draws none.
const PILL_OF = {
  live: 'crlive', answering: 'crbusy', needs_ok: 'crask', paused: '',
  paused_room: 'crpaused', context_lost: 'crlost', record: 'crrecord',
};
const PILL_SEL = '.crbusy, .crask, .crlive, .crpaused, .crlost, .crrecord';

const CONVS = [
  { id: 'c-busy', title: 'Why does the porch light come on at three in the '
      + 'afternoon when nobody is home', modified: 0, age: '2 min ago',
    source: 'you', live: true, busy: true, needs_ok: false,
    row_state: rs('answering') },
  { id: 'c-ask', title: 'Tidy up the kitchen automations', modified: 0,
    age: '9 min ago', source: 'you', live: true, busy: false, needs_ok: true,
    row_state: rs('needs_ok') },
  { id: 'c-live', title: 'Bedroom thermostat schedule', modified: 0,
    age: '1 h ago', source: 'you', live: true, busy: false, needs_ok: false,
    row_state: rs('live') },
  { id: 'c-room', title: 'Garage door sensor that keeps dropping off',
    modified: 0, age: '2 h ago', source: 'you', live: false, busy: false,
    needs_ok: false, row_state: rs('paused_room') },
  { id: 'c-lost', title: 'A chat from a store the CLI has since pruned',
    modified: 0, age: '2 d ago', source: 'you', live: false, busy: false,
    needs_ok: false, row_state: rs('context_lost') },
  { id: 'c-cold', title: 'An older one nothing is holding open', modified: 0,
    age: '3 d ago', source: 'you', live: false, busy: false, needs_ok: false,
    row_state: rs('paused') },
  { id: 'c-record', title: 'Analyse the upstairs heating', modified: 0,
    age: '5 d ago', source: 'card', view_only: true, live: false, busy: false,
    needs_ok: false, row_state: rs('record') },
];
const EXPECT_PILL = Object.fromEntries(
  CONVS.map((c) => [c.title.slice(0, 24), PILL_OF[c.row_state.state]]));
const SESSIONS = CONVS.filter((c) => c.live).map((c) => ({
  session_id: c.id, state: c.busy ? 'busy' : 'ready', live: true,
  busy: c.busy, needs_ok: c.needs_ok, attached: c.id === 'c-live',
  title: c.title, busy_since: 0, last_activity: 0, row_state: c.row_state,
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
                    sources: [{ id: 'you', label: 'Chats', blurb: '', count: 6 },
                              { id: 'card', label: 'Cards', blurb: '', count: 1 }],
                    sessions: ${JSON.stringify(SESSIONS)}, max_sessions: 3 });
  }
  if (p.includes('api/chat/state')) {
    return answer({ type: 'snapshot', events: [], state: 'ready', error: '',
                    session_id: 'c-live', info: {}, commands: [], context: {},
                    cli: [], models: [], chat_model: '', default_model: '',
                    default_model_label: '', permission: null,
                    sessions: ${JSON.stringify(SESSIONS)}, max_sessions: 3,
                    composer_state: ${JSON.stringify(rs('live'))} });
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

    const m = await page.evaluate(([sel, pillSel]) => {
      const rows = [...document.querySelectorAll(sel)];
      const host = rows[0].parentElement.getBoundingClientRect();
      return {
        surface: sel,
        hostRight: host.right,
        rows: rows.map((r) => {
          const box = r.getBoundingClientRect();
          const mark = r.querySelector(pillSel);
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
    }, [selector, PILL_SEL]);

    // Every row says what it is, and says the right thing: each of the
    // six pills on the row that earned it, and no pill at all on the one
    // plainly paused conversation — the ordinary case is not news.
    if (m.rows.length !== CONVS.length) {
      note(`${width}px`, `${m.rows.length} rows rendered of ${CONVS.length}`);
    }
    for (const row of m.rows) {
      const want = EXPECT_PILL[row.id];
      if (want === undefined) {
        note(`${width}px`, `${row.id}: a row the fixture does not know`);
      } else if (want && row.mark !== want) {
        note(`${width}px`, `${row.id}: pill is "${row.mark || 'none'}", expected ${want}`);
      } else if (!want && row.mark) {
        note(`${width}px`, `${row.id}: a paused row drew a pill (${row.mark})`);
      }
    }
    const pillCount = Object.values(EXPECT_PILL).filter(Boolean).length;

    // The marks have to survive a turn ending. `chatState.live` is the
    // message node partial text streams into and is set to null when an
    // answer completes; the marks live in `chatState.liveSessions`. For a
    // release the two shared one name — the second definition in the
    // literal won, so streamed text rendered into a plain object and the
    // rail threw on the first repaint after a turn. A repaint here, with no
    // fetch to rebuild the map, is exactly that moment.
    let after = -1;
    try {
      after = await page.evaluate(([isWide, pillSel]) => {
        chatState.live = null;
        chatState.liveText = '';
        if (isWide) renderChatRail(); else renderConvModal();
        return [...document.querySelectorAll(pillSel)].length;
      }, [wide, PILL_SEL]);
    } catch (e) {
      note(`${width}px`, `repainting after a turn ended threw: ${e.message.split('\n')[0]}`);
    }
    if (after >= 0 && after < pillCount) {
      note(`${width}px`, `the marks did not survive a turn ending: ${after} of ${pillCount} left`);
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


// ---------------------------------------------------------------------------
// The third pass: the line above the message box.
//
// `composer_state` is the attached conversation's own row state, and the
// panel renders it as a sentence and ONE control — Stop while answering,
// New chat when ready, Resume now for either kind of pause, Start fresh
// when the context is gone, Ask about it on a record. Six states are
// pushed through the real renderer at both widths; each has to change the
// sentence AND the button, and the button has to be a real target on a
// phone, because "Resume now" is the press somebody makes there.
const COMPOSER_CASES = [
  ['live', 'Ready', 'New chat'],
  ['answering', 'Claude is answering', 'Stop'],
  ['paused', 'resumes this conversation', 'Resume now'],
  ['paused_room', 'pauses the quietest', 'Resume now'],
  ['context_lost', 'no longer has this conversation', 'Start fresh'],
  ['record', 'cannot be continued', 'Ask about it'],
];

async function composerPass(browser, note) {
  for (const width of LIVE_WIDTHS) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    page.on('pageerror', (e) => note(`${width}px composer`, `page error: ${e.message}`));
    await page.addInitScript(LIVE_STUB);
    await page.goto(`file://${path.join(PANEL, 'index.html')}`);
    await page.click('.viewtab[data-view="terminal"]');
    // Attached, not visible: on an empty chat it is hidden by design.
    await page.waitForSelector('#chatState', { state: 'attached' });

    // A fresh chat with nothing in it says nothing — "Ready · New chat"
    // on an empty conversation would offer a no-op, and the 44px it would
    // take is what pushes the meta line under a 320px phone's fold. So
    // the line is hidden on an empty live chat, and shown the moment the
    // conversation has anything in it.
    const blank = await page.evaluate(() => {
      chatState.record = null;
      chatState.composer = { state: 'live', label: 'Live', hint: 'Ready' };
      renderComposerState();
      const hiddenWhenEmpty = getComputedStyle(document.querySelector('#chatState')).display === 'none';
      const msg = document.createElement('div');
      msg.className = 'msg bot';
      msg.textContent = 'Sample answer. '.repeat(20);
      chatAppend(msg);
      renderComposerState();
      const shownWithContent = getComputedStyle(document.querySelector('#chatState')).display !== 'none';
      return { hiddenWhenEmpty, shownWithContent };
    });
    if (!blank.hiddenWhenEmpty) note(`${width}px composer`, 'an empty live chat draws the line');
    if (!blank.shownWithContent) note(`${width}px composer`, 'the line stays hidden once there is a conversation');

    const seenText = new Set();
    const seenButton = [];
    const line = [];
    for (const [state, needle, button] of COMPOSER_CASES) {
      const m = await page.evaluate((s) => {
        chatState.record = null;
        chatState.busyStart = s.state === 'answering' ? Date.now() - 14000 : 0;
        chatState.composer = s;
        renderComposerState();
        const host = document.querySelector('#chatState');
        const btn = document.querySelector('#chatStateAct');
        const box = btn.getBoundingClientRect();
        const cs = getComputedStyle(btn);
        const stop = document.querySelector('#chatStop');
        return {
          state: host.dataset.state,
          pill: host.querySelector('.cs-pill').textContent,
          text: host.querySelector('.cs-text').textContent,
          button: btn.textContent,
          h: Math.round(box.height),
          w: Math.round(box.width),
          shown: cs.display !== 'none' && cs.visibility !== 'hidden' && box.width > 0,
          right: host.getBoundingClientRect().right,
          // The square Stop icon in the bar stands down while the line
          // offers a labelled Stop — one Stop, not two.
          iconStopShown: getComputedStyle(stop).display !== 'none'
            && !stop.classList.contains('hidden'),
          docWidth: document.documentElement.scrollWidth,
        };
      }, rs(state));
      const where = `${width}px composer/${state}`;
      if (m.state !== state) note(where, `data-state is "${m.state}"`);
      if (!m.text.includes(needle)) note(where, `text "${m.text}" lacks "${needle}"`);
      if (state === 'answering' && !/· 1[34] s$/.test(m.text)) {
        note(where, `answering does not count seconds: "${m.text}"`);
      }
      if (m.button !== button) note(where, `button is "${m.button}", expected "${button}"`);
      if (!m.shown) note(where, 'the button is not shown');
      if (m.h < MIN_TARGET) note(where, `button is ${m.h}px tall, under ${MIN_TARGET}`);
      if (m.right > width + 0.5) note(where, `the line overflows the viewport (${m.right})`);
      if (m.docWidth > width + 0.5) note(where, `page scrolls sideways (${m.docWidth}px)`);
      if (state === 'paused' && m.pill) note(where, `a plain pause drew a pill "${m.pill}"`);
      if (state !== 'paused' && !m.pill) note(where, 'no pill');
      if (state === 'answering' && m.iconStopShown) {
        note(where, 'two Stops: the bar icon is still shown beside the labelled one');
      }
      seenText.add(m.text.replace(/ · \d+ s$/, ''));
      seenButton.push(m.button);
      line.push(`${state}: "${m.button}" ${m.h}px`);
    }
    // The sentence changes with every state, and the button with every
    // state that asks for a different thing.
    if (seenText.size !== COMPOSER_CASES.length) {
      note(`${width}px composer`, `${seenText.size} distinct sentences for ${COMPOSER_CASES.length} states`);
    }
    if (new Set(seenButton).size !== 5) {
      note(`${width}px composer`, `${new Set(seenButton).size} distinct buttons, expected 5`);
    }
    console.log(`${String(width).padStart(5)} ${line.join(' | ')}`);
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
    ? `\n${failures.length} problem(s) with the row pills`
    : `\nboth widths: every row says which of the seven states it is in`);

  console.log('\nwidth composer line: state → button');
  const composerFailures = [];
  await composerPass(browser, (where, message) =>
    composerFailures.push(`${where}: ${message}`));
  composerFailures.forEach((f) => console.log('  ' + f));
  console.log(composerFailures.length
    ? `\n${composerFailures.length} problem(s) with the composer line`
    : '\nboth widths: six states, six sentences, one control each');

  await browser.close();
  process.exit(bad || failures.length || composerFailures.length ? 1 : 0);
})();
