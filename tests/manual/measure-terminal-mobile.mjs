// Drive the classic terminal's mobile layer (brain/ttyd-assets/inject.html) in
// a real browser, on a touch device, inside an iframe the way the brAIn panel
// embeds it, and check the three things a phone does to it: paste, typing
// that arrives without a keydown, and the keyboard opening and closing.
//
// Every test the script had before this was a grep of its source, and every
// one of these failures passed them:
//
//   * Paste read the clipboard from `pointerdown`, which is not a user
//     activation for a finger, so it was refused on phones — silently, into
//     an empty catch. Chromium grants the read on a permission alone, so
//     this cannot reproduce the refusal; what it holds is that the read
//     happens once, inside an activation, and that a refused read opens a
//     box you can paste into.
//   * A multi-line paste went straight down the socket, so every newline was
//     an Enter. It has to arrive as ONE bracketed paste.
//   * The dictation fix diffed against the text it had last sent rather than
//     the textarea, so an autocorrect after ordinary typing re-sent the word.
//   * Each sample of a keyboard sliding in resized the terminal (a full
//     tmux + Claude Code redraw), and on a WebView that resizes for the
//     keyboard the panel folding its bar grew the baseline, so the bar
//     coming back read as a keyboard, which folded it again — a loop.
//   * A toolbar tap focused the terminal even with the keyboard down, which
//     popped the keyboard open.
//
// There is no ttyd and no xterm here: the page builds the three things the
// script looks for (a `.terminal`, xterm's helper textarea, a WebSocket to
// /ws) and a fake xterm that does what xterm does with an `input` event — sends
// `data` for `insertText` and nothing else. Set INJECT_PATH to run it against
// another copy of the script (that is how it was checked against the old one).
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const INJECT = process.env.INJECT_PATH
  || path.resolve(HERE, '../../brain/ttyd-assets/inject.html');
const INJECT_HTML = fs.readFileSync(INJECT, 'utf8');
const ORIGIN = 'https://terminal.test';

const failures = [];
function check(ok, what) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) failures.push(what);
}
const show = (s) => JSON.stringify(s);

// ---------------------------------------------------------------- the pages

// Runs BEFORE inject.html, exactly as the real page's order has it, so the
// script wraps this socket the way it wraps ttyd's.
const FAKE_SOCKET = `<script>
window.__sent = [];
function FakeWS(url) {
  this.url = url; this.readyState = 1; this._l = {};
}
FakeWS.prototype.send = function (buf) {
  var s = new TextDecoder().decode(buf);
  if (s[0] === '0') window.__sent.push(s.slice(1));
};
FakeWS.prototype.addEventListener = function () {};
FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
window.WebSocket = FakeWS;
</script>`;

// The terminal as the script finds it, plus xterm's input behaviour. MODE
// picks which paste route exists: 'term' (ttyd's window.term.paste), 'event'
// (xterm's paste listener on the textarea) or 'none'.
function frameHtml(mode) {
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
${FAKE_SOCKET}
${INJECT_HTML}
<style>html,body{margin:0;height:100%} #terminal-container{height:100%}
.terminal{height:calc(100% - 10px);background:#111}
.xterm-helper-textarea{position:absolute;left:-9999px;top:0;width:10px;height:10px}</style>
</head><body><div id="terminal-container"><div class="terminal xterm">
<textarea class="xterm-helper-textarea"></textarea><div class="xterm-viewport"></div></div></div>
<script>
window.__pastes = [];
var ta = document.querySelector('.xterm-helper-textarea');
var sock = new WebSocket('wss://terminal.test/ws');
// xterm: an insertText input is sent as-is; nothing else is.
ta.addEventListener('input', function (e) {
  if (e.inputType === 'insertText' && e.data) sock.send(new TextEncoder().encode('0' + e.data));
});
var MODE = ${JSON.stringify(mode)};
if (MODE === 'term') window.term = { paste: function (t) { window.__pastes.push(['term', t]); } };
if (MODE === 'event') ta.addEventListener('paste', function (e) {
  window.__pastes.push(['event', e.clipboardData.getData('text/plain')]); e.preventDefault();
});
</script></body></html>`;
}

// The panel: an iframe that folds its own bar (FOLD px) away while the frame
// says the keyboard is up. `webview` is the height the WebView gives the page,
// which the Companion app shrinks for a keyboard.
const PARENT_HTML = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0} iframe{display:block;border:0;width:100%}</style></head><body>
<iframe id="termFrame" allow="clipboard-read; clipboard-write"></iframe>
<script>
window.__kb = [];
var FOLD = 80, folded = false, webview = 700;
var frame = document.getElementById('termFrame');
function layout() { frame.style.height = (webview - (folded ? 0 : FOLD)) + 'px'; }
window.setWebview = function (h) { webview = h; layout(); };
window.addEventListener('message', function (ev) {
  if (!ev.data || ev.data.type !== 'brain-keyboard') return;
  window.__kb.push(!!ev.data.open);
  folded = !!ev.data.open; layout();
});
layout();
</script></body></html>`;

// A top-window visualViewport the frame can read, which the test moves the
// way iOS moves the real one while the keyboard slides in.
const FAKE_VV = `
(() => {
  const vv = new EventTarget();
  vv.height = window.innerHeight; vv.width = window.innerWidth;
  vv.offsetTop = 0; vv.offsetLeft = 0; vv.scale = 1; vv.pageTop = 0; vv.pageLeft = 0;
  Object.defineProperty(window, 'visualViewport', { configurable: true, get: () => vv });
  window.__vv = vv;
})();`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function openPanel(browser, { mode = 'none', viewport, fakeVV = false, clipboard = true }) {
  const context = await browser.newContext({
    viewport, hasTouch: true, isMobile: true, deviceScaleFactor: 2,
  });
  if (clipboard) await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: ORIGIN });
  await context.route(`${ORIGIN}/**`, (route) => {
    const u = new URL(route.request().url());
    const body = u.pathname === '/frame.html' ? frameHtml(mode) : PARENT_HTML;
    route.fulfill({ status: 200, contentType: 'text/html', body });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  if (fakeVV) await page.addInitScript({ content: `if (window === window.top) {${FAKE_VV}}` });
  await page.goto(`${ORIGIN}/`);
  await page.evaluate(() => { document.getElementById('termFrame').src = '/frame.html'; });
  let frame = null;
  for (let i = 0; i < 50 && !frame; i++) {
    frame = page.frames().find((f) => f.url().endsWith('/frame.html')) || null;
    if (!frame) await sleep(100);
  }
  await frame.waitForSelector('#bruh-bar', { state: 'attached' });
  await sleep(200);
  return { context, page, frame, errors };
}

const sent = (frame) => frame.evaluate(() => window.__sent.slice());
const clearSent = (frame) => frame.evaluate(() => { window.__sent.length = 0; });
const focusTa = (frame) => frame.evaluate(() => document.querySelector('.xterm-helper-textarea').focus());
const taFocused = (frame) => frame.evaluate(() =>
  document.activeElement === document.querySelector('.xterm-helper-textarea'));

// ------------------------------------------------------------------- paste

async function pasteChecks(browser) {
  const viewport = { width: 390, height: 780 };
  const TEXT = 'first line\nsecond line';
  const BRACKETED = '\x1b[200~first line\rsecond line\x1b[201~';

  // 1. The read has to happen with a user activation live, and the text has
  //    to reach xterm's own paste. Recorded rather than inferred: Chromium
  //    grants a read on a permission alone, so success says nothing about
  //    whether a phone would have refused it.
  {
    const { context, frame, errors } = await openPanel(browser, { mode: 'term', viewport });
    await frame.evaluate((t) => {
      window.__readCalls = [];
      navigator.clipboard.readText = function () {
        window.__readCalls.push(!!(navigator.userActivation && navigator.userActivation.isActive));
        return Promise.resolve(t);
      };
    }, TEXT);
    await focusTa(frame);
    await frame.tap('[data-bruh-key="paste"]');
    await sleep(300);
    const calls = await frame.evaluate(() => window.__readCalls);
    const pastes = await frame.evaluate(() => window.__pastes);
    check(calls.length === 1, `paste: the button reads the clipboard once (${calls.length} reads)`);
    check(calls[0] === true, 'paste: the read happens during a user activation (a tap, not a pointerdown)');
    check(pastes.length === 1 && pastes[0][0] === 'term' && pastes[0][1] === TEXT,
      `paste: the text goes through xterm's own paste (window.term), got ${show(pastes)}`);
    check((await sent(frame)).length === 0, 'paste: nothing is typed down the socket beside it');
    check(errors.length === 0, `paste: no page errors ${show(errors)}`);
    await context.close();
  }

  // 2. No window.term: a synthetic paste event reaches xterm's listener.
  {
    const { context, frame } = await openPanel(browser, { mode: 'event', viewport });
    await frame.evaluate((t) => { navigator.clipboard.readText = () => Promise.resolve(t); }, TEXT);
    await frame.tap('[data-bruh-key="paste"]');
    await sleep(300);
    const pastes = await frame.evaluate(() => window.__pastes);
    check(pastes.length === 1 && pastes[0][0] === 'event' && pastes[0][1] === TEXT,
      `paste: with no window.term, xterm's paste listener gets it, got ${show(pastes)}`);
    check((await sent(frame)).length === 0, 'paste: and it is not ALSO typed down the socket');
    await context.close();
  }

  // 3. No xterm paste path at all: one bracketed paste, newlines as CR, so a
  //    two-line paste is not a submitted first line.
  {
    const { context, frame } = await openPanel(browser, { mode: 'none', viewport });
    await frame.evaluate((t) => { navigator.clipboard.readText = () => Promise.resolve(t); }, TEXT);
    await frame.tap('[data-bruh-key="paste"]');
    await sleep(300);
    const s = await sent(frame);
    check(s.join('') === BRACKETED, `paste: the floor is one bracketed paste, got ${show(s)}`);
    await context.close();
  }

  // 4. A refused read opens a box you can paste into; Send delivers it.
  for (const how of ['refused', 'absent']) {
    const { context, frame, errors } = await openPanel(browser, { mode: 'none', viewport });
    await frame.evaluate((how) => {
      if (how === 'refused') {
        navigator.clipboard.readText = () => Promise.reject(new DOMException('no', 'NotAllowedError'));
      } else {
        Object.defineProperty(navigator, 'clipboard', { configurable: true, get: () => undefined });
      }
    }, how);
    await focusTa(frame);
    await frame.tap('[data-bruh-key="paste"]');
    await sleep(300);
    const sheet = await frame.evaluate(() => {
      const s = document.getElementById('bruh-paste');
      const box = document.getElementById('bruh-paste-box');
      if (!s || getComputedStyle(s).display === 'none') return null;
      const r = box.getBoundingClientRect();
      const btns = ['bruh-paste-send', 'bruh-paste-cancel'].map((id) =>
        document.getElementById(id).getBoundingClientRect().height);
      return {
        focused: document.activeElement === box,
        font: parseFloat(getComputedStyle(box).fontSize),
        onScreen: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
        btns, why: document.getElementById('bruh-paste-why').textContent,
      };
    });
    check(!!sheet, `paste (${how}): a refused read opens the paste box instead of doing nothing`);
    if (sheet) {
      check(sheet.focused, `paste (${how}): the box has focus, so a long-press offers Paste`);
      check(sheet.font >= 16, `paste (${how}): the box is ≥16px, so iOS does not zoom (${sheet.font}px)`);
      check(sheet.onScreen, `paste (${how}): the box is on screen`);
      check(sheet.btns.every((h) => h >= 44), `paste (${how}): its buttons are ≥44px (${sheet.btns})`);
      check(sheet.why.length > 20, `paste (${how}): it says why it opened`);
      await frame.fill('#bruh-paste-box', TEXT);
      await frame.tap('#bruh-paste-send');
      await sleep(200);
      const s = await sent(frame);
      check(s.join('') === BRACKETED, `paste (${how}): Send delivers one bracketed paste, got ${show(s)}`);
      const hidden = await frame.evaluate(() =>
        getComputedStyle(document.getElementById('bruh-paste')).display === 'none');
      check(hidden, `paste (${how}): the box closes after Send`);
      check(await taFocused(frame), `paste (${how}): the terminal has focus again`);
    }
    check(errors.length === 0, `paste (${how}): no page errors ${show(errors)}`);
    await context.close();
  }
}

// ------------------------------------------------------------------ typing

async function typingChecks(browser) {
  const { context, frame, errors } = await openPanel(browser, { viewport: { width: 390, height: 780 } });
  await focusTa(frame);
  await sleep(50);

  // Typing xterm handles: a keydown, the character in the box, an insertText.
  // The fake xterm sends it; the dictation fix must not send it again.
  async function type(word) {
    for (const ch of word) {
      await frame.evaluate((ch) => {
        const ta = document.querySelector('.xterm-helper-textarea');
        ta.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true }));
        ta.value += ch;
        ta.dispatchEvent(new InputEvent('input', { inputType: 'insertText', data: ch, bubbles: true }));
      }, ch);
      await sleep(20);
    }
    await sleep(150);   // past the 100ms keydown window
  }
  // Input with no keydown behind it: what dictation, autocorrect and a
  // predictive-text tap all look like.
  async function replace(value, inputType, data = null) {
    await frame.evaluate(([value, inputType, data]) => {
      const ta = document.querySelector('.xterm-helper-textarea');
      ta.value = value;
      ta.dispatchEvent(new InputEvent('input', { inputType, data, bubbles: true }));
    }, [value, inputType, data]);
    await sleep(30);
  }

  await clearSent(frame);
  await type('teh');
  await replace('the ', 'insertReplacementText');
  let s = (await sent(frame)).join('');
  // On the terminal: "teh", two backspaces, "he " → "the ".
  check(s === 'teh\x7f\x7fhe ', `typing: autocorrect after typing sends only the correction, got ${show(s)}`);

  await clearSent(frame);
  await frame.evaluate(() => { document.querySelector('.xterm-helper-textarea').value = ''; });
  await type('hi');
  await replace('hi', 'insertText', null);   // a no-op re-delivery
  s = (await sent(frame)).join('');
  check(s === 'hi', `typing: a re-delivery that changes nothing sends nothing, got ${show(s)}`);

  // Dictation: each interim result carries the whole transcript so far.
  await clearSent(frame);
  await frame.evaluate(() => { document.querySelector('.xterm-helper-textarea').value = ''; });
  await frame.evaluate(() => document.querySelector('.xterm-helper-textarea')
    .dispatchEvent(new FocusEvent('focusin', { bubbles: true })));
  for (const v of ['t', 'tes', 'testing', 'testing can', 'testing can you']) {
    await replace(v, 'insertText', v);
  }
  s = (await sent(frame)).join('');
  check(s === 'testing can you', `typing: dictation's growing transcript is sent once, got ${show(s)}`);

  // A paste's input event is xterm's; diffing it would type it out.
  await clearSent(frame);
  await frame.evaluate(() => { document.querySelector('.xterm-helper-textarea').value = ''; });
  await type('a');
  await replace('ahello\nworld', 'insertFromPaste');
  s = (await sent(frame)).join('');
  check(s === 'a', `typing: a paste's input event is left to xterm, got ${show(s)}`);

  check(errors.length === 0, `typing: no page errors ${show(errors)}`);
  await context.close();
}

// --------------------------------------------------------------- keyboard

async function keyboardChecks(browser) {
  // iOS: the keyboard is only visible in the TOP window's visualViewport,
  // which reports a dozen heights as it slides in.
  {
    const viewport = { width: 390, height: 844 };
    const { context, page, frame, errors } = await openPanel(browser, { viewport, fakeVV: true });
    await frame.evaluate(() => {
      window.__barH = [];
      new MutationObserver(() => {
        window.__barH.push(document.documentElement.style.getPropertyValue('--bruh-bar-h'));
      }).observe(document.documentElement, { attributes: true, attributeFilter: ['style'] });
    });
    await page.evaluate(() => { window.__kb.length = 0; });
    await focusTa(frame);
    for (let i = 1; i <= 12; i++) {
      await page.evaluate((i) => {
        window.__vv.height = window.innerHeight - Math.round(336 * i / 12);
        window.__vv.dispatchEvent(new Event('resize'));
      }, i);
      await sleep(16);
    }
    await sleep(700);
    const openWrites = (await frame.evaluate(() => window.__barH.slice())).length;
    const kbOpen = await page.evaluate(() => window.__kb.slice());
    const barMoved = await frame.evaluate(() => document.getElementById('bruh-bar').style.transform);
    check(openWrites === 1, `keyboard: opening resizes the terminal once, not per sample (${openWrites} resizes)`);
    check(show(kbOpen) === '[true]', `keyboard: the panel is told once that it opened, got ${show(kbOpen)}`);
    check(/translateY\(-336px\)/.test(barMoved), `keyboard: the toolbar sits on the keys (${barMoved})`);

    await frame.evaluate(() => { window.__barH.length = 0; });
    await page.evaluate(() => { window.__kb.length = 0; });
    await frame.evaluate(() => document.querySelector('.xterm-helper-textarea').blur());
    for (let i = 11; i >= 0; i--) {
      await page.evaluate((i) => {
        window.__vv.height = window.innerHeight - Math.round(336 * i / 12);
        window.__vv.dispatchEvent(new Event('resize'));
      }, i);
      await sleep(16);
    }
    await sleep(700);
    const closeWrites = (await frame.evaluate(() => window.__barH.slice())).length;
    const kbClose = await page.evaluate(() => window.__kb.slice());
    check(closeWrites === 1, `keyboard: closing resizes the terminal once (${closeWrites} resizes)`);
    check(show(kbClose) === '[false]', `keyboard: the panel is told once that it closed, got ${show(kbClose)}`);
    check(errors.length === 0, `keyboard: no page errors ${show(errors)}`);
    await context.close();
  }

  // The Companion app: the WebView shrinks for the keyboard, and the panel
  // folds its bar in answer, which makes the frame taller. After that round
  // trip, tapping the terminal with NO keyboard must not read as one.
  // Wider than 500px and taller than 500px at every step, so the phone-only
  // guess in computeGap stays out of it; taller than wide at every step, so
  // the baseline is always the portrait one (a frame that flips orientation
  // between samples is compared against a different baseline and hides the
  // case entirely).
  {
    const viewport = { width: 600, height: 1200 };
    const { context, page, frame } = await openPanel(browser, { viewport });
    await page.evaluate(() => window.setWebview(1100));
    await sleep(300);
    await page.evaluate(() => { window.__kb.length = 0; });
    await focusTa(frame);
    await sleep(500);
    await page.evaluate(() => window.setWebview(700));     // keyboard up
    await sleep(600);
    await frame.evaluate(() => document.querySelector('.xterm-helper-textarea').blur());
    await page.evaluate(() => window.setWebview(1100));    // keyboard down
    await sleep(800);
    const roundTrip = await page.evaluate(() => window.__kb.slice());
    check(show(roundTrip) === '[true,false]',
      `keyboard (WebView resizes): open then closed, got ${show(roundTrip)}`);
    await page.evaluate(() => { window.__kb.length = 0; });
    await focusTa(frame);                                   // no keyboard this time
    await sleep(800);
    const phantom = await page.evaluate(() => window.__kb.slice());
    check(!phantom.includes(true),
      `keyboard (WebView resizes): a tap with no keyboard is not read as one, got ${show(phantom)}`);
    await context.close();
  }

  // A toolbar tap with the keyboard DOWN must not open it; with it up, it
  // must stay up.
  {
    const { context, frame } = await openPanel(browser, { viewport: { width: 390, height: 780 } });
    await frame.evaluate(() => document.querySelector('.xterm-helper-textarea').blur());
    await frame.tap('[data-bruh-key="esc"]');
    await sleep(100);
    check(!(await taFocused(frame)), 'toolbar: ESC with the keyboard down leaves it down');
    check((await sent(frame)).join('') === '\x1b', 'toolbar: and still sends ESC');
    await focusTa(frame);
    await frame.tap('[data-bruh-key="up"]');
    await sleep(100);
    check(await taFocused(frame), 'toolbar: ↑ with the keyboard up leaves it up');
    await context.close();
  }
}

// --------------------------------------------------------------- the panel
//
// On a phone the chat face of Ask opens on the list of your chats. The
// classic face is one shell with no list, so it must open straight on the
// terminal — the list page taking the screen over a terminal would be a
// phone with no terminal on it — and the two floating controls (Chat
// options and Full-screen terminal) stay on screen in both.
const PANEL = path.resolve(HERE, '../../brain/panel');
const PANEL_STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/status')) {
    return answer({ version: 'test', authenticated: true, auth_type: 'oauth',
      auth_check: { state: 'ok', error: '' }, model: 'default',
      settings: { terminal_ui: 'classic' }, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0 });
  }
  if (p.includes('api/chat/conversations')) {
    return answer({ conversations: [{ id: 'c1', title: 'A chat', age: '1 h ago',
      modified: 0, source: 'you', row_state: { state: 'paused', label: '', hint: '' } }],
      sources: [], sessions: [], max_sessions: 3 });
  }
  return answer({});
};
`;

async function panelChecks(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 780 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  // ttyd is not here; the frame's own document is not what this measures.
  await page.route('**/terminal/**', (route) => route.fulfill({ body: '<!doctype html><p>tty' }));
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(PANEL_STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  const shown = (sel) => page.evaluate((s) => {
    const n = document.querySelector(s);
    return !!n && n.checkVisibility() && n.getBoundingClientRect().height > 0;
  }, sel);

  // The chat face: Ask opens on the list, and a row opens the transcript.
  await page.evaluate(() => { applyTermMode('chat'); });
  await page.evaluate(() => switchView('terminal'));
  await page.evaluate(() => refreshChatRail());
  check(await page.evaluate(() => document.body.classList.contains('ask-list')),
    'panel: on a phone the chat face opens on the list of your chats');
  check(await shown('#chatRail') && !(await shown('#termChat')),
    'panel: the list is the screen, with no transcript behind it');
  check(await shown('#termMenu') && await shown('#termExpand'),
    'panel: Chat options and Full-screen terminal are on the list page');
  await page.evaluate(() => askShow('chat'));
  check(await shown('#chatBack'), 'panel: a transcript has a way back to the list');

  // The classic face: the terminal, never the list.
  await page.evaluate(() => switchView('findings'));
  await page.evaluate(() => { applyTermMode('classic'); });
  await page.evaluate(() => switchView('terminal'));
  check(!(await page.evaluate(() => document.body.classList.contains('ask-list'))),
    'panel: the classic face does not open on the list');
  check(await shown('#termFrame'), 'panel: the classic face shows the terminal');
  check(!(await shown('#chatRail')), 'panel: no list over the classic terminal');
  check(await shown('#termMenu') && await shown('#termExpand'),
    'panel: Chat options and Full-screen terminal are over the terminal');
  check(errors.length === 0, `panel: no page errors ${show(errors)}`);
  await context.close();
}

// --------------------------------------------------------------------- run

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  await pasteChecks(browser);
  await typingChecks(browser);
  await keyboardChecks(browser);
  await panelChecks(browser);
} catch (e) {
  failures.push(`the measure itself failed: ${e && e.stack || e}`);
  console.log(`FAIL the measure itself failed: ${e && e.stack || e}`);
} finally {
  await browser.close();
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nall terminal mobile checks passed');
