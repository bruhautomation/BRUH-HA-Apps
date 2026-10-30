// Ask brAIn about anything: right-click (or press and hold on touch) a card
// on Today and a small box opens at the press; Ask sends a prompt naming what
// was pressed to POST api/ask, which opens it on the SAVED face — a new chat
// conversation, or a window in Claude Code's own terminal. Holds:
//
//   * a right-click on a card opens the box, inside the viewport, with the
//     card's first line in it and a 16px text box (iOS zooms below that);
//   * Ask posts {prompt} to api/ask, and the prompt quotes the
//     card's text and carries the person's words;
//   * a right-click in a text box and a shift+right-click open nothing;
//   * on touch a press held still opens it, and one that moves does not;
//   * every press in the box is 44px tall;
//   * THE FLIP (the audit's repro): on a house whose saved face is the chat,
//     Ask on an insight card lands on a new chat conversation holding the
//     card's words, and the next status refresh (usage moved because Claude
//     ran) leaves the face and the conversation exactly there — it used to
//     put the page on an empty "New chat" while the question ran in a hidden
//     terminal;
//   * a double tap on Ask is one conversation.
//
// Driven against the REAL app.js behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const failures = [];
const note = (where, m) => failures.push(`${where}: ${m}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

for (const { width, touch } of [{ width: 1200, touch: false }, { width: 390, touch: true }]) {
  const where = `${width}px`;
  const { page } = await openToday(browser, PANEL,
    { width, touch, onError: (m) => note(where, `page error: ${m}`) });
  const card = page.locator('#findList .qcard, #findList .case, #findList article').first();
  if (!(await card.count())) { note(where, 'no card on Today to press'); continue; }
  await card.scrollIntoViewIfNeeded();
  // A scroll still settling cancels a hold, as it should; let it settle.
  await page.waitForTimeout(300);
  const box = await card.boundingBox();
  const cx = box.x + Math.min(40, box.width / 2), cy = box.y + 20;

  if (touch) {
    // Held still: opens.
    await page.evaluate(([x, y]) => {
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: x, clientY: y, pointerType: 'touch' }));
    }, [cx, cy]);
    const opened = await page.waitForSelector('#askAbout', { timeout: 3000 }).then(() => true, () => false);
    if (!opened) note(where, 'a press held still opened nothing');
    await page.evaluate(() => document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true })));
    await page.keyboard.press('Escape');
    // Moved: opens nothing.
    await page.evaluate(([x, y]) => {
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: x, clientY: y, pointerType: 'touch' }));
      document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: x + 40, clientY: y, pointerType: 'touch' }));
    }, [cx, cy]);
    await page.waitForTimeout(800);
    if (await page.locator('#askAbout').count()) note(where, 'a press that moved (a scroll) opened the box');
    await page.keyboard.press('Escape');
  }

  await page.mouse.click(cx, cy, { button: 'right' });
  const m = await page.evaluate(() => {
    const b = document.getElementById('askAbout');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    const i = b.querySelector('textarea');
    return {
      inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
      snip: b.querySelector('.aasnip').textContent,
      font: parseFloat(getComputedStyle(i).fontSize),
      heights: [...b.querySelectorAll('button')].map((x) => Math.round(x.getBoundingClientRect().height)),
    };
  });
  if (!m) { note(where, 'a right-click on a card opened nothing'); continue; }
  if (!m.inside) note(where, 'the box hangs off the screen');
  if (!m.snip.trim()) note(where, 'the box does not say what was pressed');
  if (m.font < 16) note(where, `the text box is ${m.font}px (iOS zooms under 16)`);
  if (m.heights.some((h) => h < 44)) note(where, `a press in the box is under 44px: ${m.heights.join(',')}`);
  await page.fill('#askAbout textarea', 'turn it off for the night');
  await page.click('#askAbout .btn.primary');
  await page.waitForTimeout(300);
  const sent = (await posts(page)).filter((p) => /api\/ask$/.test(p.url));
  if (!sent.length) note(where, 'Ask did not post to api/ask');
  else {
    const prompt = (sent[sent.length - 1].body || {}).prompt || '';
    if (!prompt.includes('turn it off for the night')) note(where, 'the prompt lost the words typed');
    if (!prompt.includes('> ')) note(where, 'the prompt does not quote what was pressed');
  }
  if (await page.locator('#askAbout').count()) note(where, 'the box stayed open after Ask');

  // Shift+right-click is the browser's.
  await page.evaluate(() => window.switchView && window.switchView('findings'));
  await page.keyboard.down('Shift');
  await page.mouse.click(cx, cy, { button: 'right' });
  await page.keyboard.up('Shift');
  if (await page.locator('#askAbout').count()) note(where, 'shift+right-click opened the box');
  await page.close();
}

// ---- the flip -------------------------------------------------------------
// The house's saved face is the chat. api/ask answers as the server does on
// that face: a new conversation's key. The stream (an EventSource stand-in)
// answers a connection naming that key with its snapshot: the card's words.
const FLIP = `
(() => {
  const inner = window.fetch;
  window.__pct = 10;
  window.__asked = '';
  window.__es = [];
  window.EventSource = function (url) {
    const es = { url: String(url), onmessage: null, onerror: null,
      close() { es.closed = true; }, addEventListener() {} };
    window.__es.push(es);
    setTimeout(() => {
      if (!es.onmessage) return;
      const own = es.url.includes('session_key=k-new');
      const events = own && window.__asked ? [{ type: 'user', text: window.__asked, seq: 1 }] : [];
      es.onmessage({ data: JSON.stringify({ type: 'snapshot', key: own ? 'k-new' : 'k-old',
        session_id: null, events, state: own ? 'busy' : 'ready', sessions: [] }) });
    }, 30);
    return es;
  };
  window.fetch = async (url, opts) => {
    const p = String(url);
    const answer = (body) => new Response(JSON.stringify(body), {
      status: 200, headers: { 'Content-Type': 'application/json' } });
    if (p.includes('api/status')) {
      const j = await (await inner(url, opts)).json();
      j.settings = { terminal_ui: 'chat' };
      j.usage = { used_percent: window.__pct };
      return answer(j);
    }
    if (p.includes('api/ask')) {
      window.__posts.push({ url: p, method: 'POST', body: (opts && opts.body) || '' });
      try { window.__asked = JSON.parse(opts.body).prompt; } catch (e) { /* not ours */ }
      await new Promise((r) => setTimeout(r, 150));
      return answer({ ok: true, face: 'chat', key: 'k-new', session_id: null, pending: true });
    }
    return inner(url, opts);
  };
})();`;
for (const { width, touch } of [{ width: 1200, touch: false }, { width: 390, touch: true }]) {
  const where = `flip ${width}px`;
  const { page } = await openToday(browser, PANEL,
    { width, touch, extra: FLIP, onError: (m) => note(where, `page error: ${m}`) });
  await page.evaluate(() => refreshStatus());
  await page.waitForTimeout(100);
  const look = () => page.evaluate(() => ({
    view: currentView,
    face: chatState.session,
    classic: document.body.classList.contains('term-classic'),
    key: chatState.key,
    words: [...document.querySelectorAll('#chatLog .msg, #chatLog [class*="user"]')]
      .map((n) => n.textContent).join(' | '),
  }));
  const before = await look();
  if (before.face !== 'chat') note(where, `the page did not start on the saved chat face (${before.face})`);
  // The insight card's Ask, twice in quick succession on one button.
  await page.evaluate(() => {
    const btn = document.createElement('button');
    document.body.appendChild(btn);
    askAboutReport('energy', { title: 'Energy' },
      { title: 'Energy use', summary: 'Up 12% this week' }, btn);
    askAboutReport('energy', { title: 'Energy' },
      { title: 'Energy use', summary: 'Up 12% this week' }, btn);
  });
  await page.waitForFunction(() => chatState.key === 'k-new', null, { timeout: 3000 })
    .catch(() => note(where, 'Ask did not move this viewer onto the new conversation'));
  await page.waitForTimeout(150);
  const asked = (await posts(page)).filter((p) => /api\/ask$/.test(p.url));
  if (asked.length !== 1) note(where, `a double tap on Ask posted ${asked.length} times`);
  if ((await posts(page)).some((p) => /api\/terminal\/open/.test(p.url))) {
    note(where, 'Ask on the chat face opened the terminal');
  }
  const after = await look();
  const check = (label, s) => {
    if (s.view !== 'terminal') note(where, `${label}: Ask is not on screen (${s.view})`);
    if (s.face !== 'chat' || s.classic) note(where, `${label}: the face flipped to the terminal`);
    if (s.key !== 'k-new') note(where, `${label}: the view is on ${s.key}, not the new conversation`);
    if (!s.words.includes('Energy use')) note(where, `${label}: the conversation on screen does not hold the card's words`);
  };
  check('after Ask', after);
  // Nothing the person did: usage moved because Claude ran, and the
  // status refresh comes round.
  await page.evaluate(() => { window.__pct = 11; return refreshStatus(); });
  await page.waitForTimeout(200);
  check('after the next status refresh', await look());
  await page.close();
}
await browser.close();
if (failures.length) {
  console.error('measure-askabout:\n  ' + failures.join('\n  '));
  process.exit(1);
}
console.log('measure-askabout: all checks passed');
