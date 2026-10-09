// Drive the Ask tab — the list of your chats and a transcript — through the
// panel's REAL renderers behind a stubbed fetch, at a phone (390, touch) and
// a desktop (1200), and assert the shape the redesign gave it.
//
//   * The list opens on your conversations, and a row of pills under its
//     head (Chats · Voice · …, each with its count) switches to what brAIn
//     ran by itself, one kind at a time — and back. No selection mode, no
//     ✕ on every row. Each row has one ⋯, and its Delete hands back an Undo.
//   * On a phone Ask opens on the list, a row opens the transcript, and the
//     transcript has a visible way back. On a desktop the list is a rail
//     beside the transcript.
//   * A reply's working — tool calls, results, thinking, a background task
//     finishing — folds into ONE closed "Worked through N steps" per reply,
//     and what somebody decides on never folds: the approval card, the
//     question card and the endings a discussion offers stay in the log.
//   * "Save as report" sits under a reply's last answer and asks the same
//     question again as a report card (`report: true`), and a discussion's
//     opener offers none.
//   * No "Resume" anywhere: sending is what resumes. A discussion is
//     titled by its card, linked back to it, with the card's own verbs.
//   * Nothing under 44px on touch, nothing scrolls sideways.
//   * With no conversations at all, a phone opens on the message box — the
//     list page was "Your chats / No chats yet. / [Ask]" and a press before
//     anybody could type — and the two floating controls (⋯ and ⤢) are
//     either gone or carry their names, never bare glyphs over an empty
//     screen.
//
// A copy of the renderers in this file would only ever agree with itself,
// so it is the real app.js, measure-activity's arrangement.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 1200, touch: false },
];
const MIN_TARGET = 44;
const FINDING_TS = 1720000000;
const CARD_TITLE = 'Garage door sensor battery is at 5%';

const rs = (state, label = '', hint = '') => ({ state, label, hint });
const CONVS = [
  { id: 'c-here', title: 'Why does the porch light come on at three in the afternoon',
    modified: 0, age: '2 min ago', source: 'you', live: true, busy: false,
    needs_ok: false, row_state: rs('live', 'Live', 'Ready') },
  // A discussion: the server has already taken "Discussing: " off the title
  // and named the card it is about.
  { id: 'c-disc', title: CARD_TITLE, finding_ts: FINDING_TS, modified: 0,
    age: '1 h ago', source: 'you', live: false, busy: false, needs_ok: false,
    row_state: rs('paused') },
  { id: 'c-old', title: 'Bedroom thermostat schedule', modified: 0,
    age: '3 d ago', source: 'you', live: false, busy: false, needs_ok: false,
    row_state: rs('paused') },
];
const VOICE_CONVS = [
  { id: 'v-1', title: 'Turn the kitchen lights off', modified: 0, age: '5 min ago',
    source: 'voice', live: false, busy: false, needs_ok: false, row_state: rs('paused') },
  { id: 'v-2', title: 'What is the temperature upstairs', modified: 0, age: '1 h ago',
    source: 'voice', live: false, busy: false, needs_ok: false, row_state: rs('paused') },
];
const FINDING = {
  ts: FINDING_TS, text: CARD_TITLE, detail: 'since 3 Sep', fix: 'Replace it',
  severity: 'warning', status: 'open', entity_id: 'sensor.garage_battery',
  source: 'check:forecasts', source_title: 'Forecasts', note: '', fixable: true,
};

const STUB = `
window.__posts = [];
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts = {}) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if ((opts.method || 'GET') !== 'GET') {
    window.__posts.push({ path: p, body: opts.body ? JSON.parse(opts.body) : null });
  }
  if (/api\\/chat\\/conversation\\/[^/]+\\/delete/.test(p)) {
    return answer({ deleted: 'c-old', undo: 'tok-1' });
  }
  if (p.includes('api/chat/conversations')) {
    window.__convAsked = (window.__convAsked || []).concat([p]);
    const voice = /source=voice/.test(p);
    if (window.__noConvs) {
      return answer({ conversations: [], current: '', sessions: [], max_sessions: 3,
                      sources: [{ id: 'you', label: 'Chats', count: 0 }] });
    }
    return answer({ conversations: voice ? ${JSON.stringify(VOICE_CONVS)} : ${JSON.stringify(CONVS)},
                    current: 'c-here',
                    sources: [{ id: 'you', label: 'Chats', count: 3 },
                              { id: 'voice', label: 'Voice', count: 55 }],
                    sessions: [], max_sessions: 3 });
  }
  if (p.includes('api/chat/resume')) {
    return answer({ ok: true, resumed: true, row_state: { state: 'paused', label: '', hint: '' } });
  }
  if (p.includes('api/generate')) return answer({ queued: ['custom-1'] });
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 1,
    });
  }
  if (p.includes('api/settings')) return answer({ settings: {}, usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/todo')) return answer({ items: [], done: [], open: 0, done_count: 0 });
  if (p.includes('api/findings')) {
    return answer({ findings: [${JSON.stringify(FINDING)}], hypotheses: [], open: 1, settled: [] });
  }
  return answer({});
};
`;

// The words the redesign cut, which must stay cut on this tab.
const CUT = [/Resume now/, /resumes this conversation/i, /Select conversations/,
  /Discussing/];
// The verbs a button on this tab may say (the redesign's vocabulary, plus
// the approval card's own answers, which are the CLI's question).
const STRIP_VERBS = new Set(['Plan', 'Done', 'Snooze', 'Ignore']);

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const visible = (sel) => `(() => {
  const n = document.querySelector(${JSON.stringify(sel)});
  if (!n) return false;
  const r = n.getBoundingClientRect();
  const cs = getComputedStyle(n);
  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden';
})()`;

for (const { width, touch } of CASES) {
  const where = `${width}px`;
  const context = await browser.newContext({
    viewport: { width, height: 860 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'terminal');
  await page.evaluate(() => { chatState.sessionId = 'c-here'; });
  await page.evaluate(() => refreshChatRail());
  // Attached, not visible: a list the page does not show is a failure to
  // report below, not a timeout to throw.
  await page.waitForSelector('#chatRailList .crrow', { state: 'attached', timeout: 5000 })
    .catch(() => note(where, 'the list rendered no rows'));

  // ---- the list ------------------------------------------------------
  const list = await page.evaluate(() => {
    const rail = document.querySelector('#chatRail');
    const r = rail.getBoundingClientRect();
    const chat = document.querySelector('#termChat').getBoundingClientRect();
    return {
      onList: document.body.classList.contains('ask-list'),
      railW: Math.round(r.width),
      chatShown: chat.width > 0 && chat.height > 0,
      rows: [...document.querySelectorAll('#chatRailList .crrow')].map((row) => {
        const b = row.querySelector('.critem').getBoundingClientRect();
        const m = row.querySelector('.crmore');
        const mr = m ? m.getBoundingClientRect() : null;
        return {
          title: row.querySelector('.ctitle').textContent,
          h: Math.round(b.height),
          more: !!m,
          moreH: mr ? Math.round(mr.height) : 0,
          moreShown: !!m && Number(getComputedStyle(m).opacity) > 0,
        };
      }),
      pills: [...document.querySelectorAll('#chatRailKinds .crkind')].map((b) => ({
        source: b.dataset.source,
        on: b.classList.contains('active'),
        h: Math.round(b.getBoundingClientRect().height),
        shown: b.getBoundingClientRect().width > 0,
      })),
      railTitle: document.querySelector('#chatRailTitle').textContent,
      select: document.querySelectorAll('.crcheck, .cselbar, #chatRailSel, #convSel').length,
      del: document.querySelectorAll('.crdel').length,
      modal: !!document.querySelector('#convModal'),
    };
  });
  if (touch) {
    if (!list.onList) note(where, 'Ask did not open on the list');
    if (list.chatShown) note(where, 'the transcript is on screen behind the list');
    if (list.railW < width - 2) note(where, `the list is ${list.railW}px of a ${width}px screen`);
  } else {
    if (list.onList) note(where, 'a desktop got the phone list page');
    if (list.railW < 200) note(where, 'no rail beside the transcript');
    if (!list.chatShown) note(where, 'no transcript beside the rail');
  }
  if (list.rows.length !== 3) note(where, `${list.rows.length} rows of 3`);
  if (list.pills.map((b) => b.source).join() !== 'you,voice') {
    note(where, `the kind pills are ${JSON.stringify(list.pills.map((b) => b.source))}`);
  }
  if (!(list.pills[0] || {}).on) note(where, 'Ask does not open on your chats');
  if (list.railTitle !== 'Your chats') note(where, `the list is headed "${list.railTitle}"`);
  for (const b of list.pills) {
    if (!b.shown) note(where, `the ${b.source} pill is not on screen`);
    if (touch && b.h < MIN_TARGET) note(where, `the ${b.source} pill is ${b.h}px`);
  }

  // ---- a pill switches the list to that kind, and back ----------------
  try {
    await page.click('#chatRailKinds .crkind[data-source="voice"]');
    await page.waitForFunction(() =>
      [...document.querySelectorAll('#chatRailList .ctitle')]
        .some((t) => /kitchen lights/.test(t.textContent)), null, { timeout: 4000 });
    const v = await page.evaluate(() => ({
      asked: (window.__convAsked || []).slice(-1)[0] || '',
      rows: document.querySelectorAll('#chatRailList .crrow').length,
      title: document.querySelector('#chatRailTitle').textContent,
      on: document.querySelector('#chatRailKinds .crkind.active')?.dataset.source,
      wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    }));
    if (!/source=voice/.test(v.asked)) note(where, `Voice asked for ${v.asked}`);
    if (v.rows !== 2) note(where, `Voice lists ${v.rows} rows of 2`);
    if (v.title !== 'Voice') note(where, `under Voice the list is headed "${v.title}"`);
    if (v.on !== 'voice') note(where, 'the Voice pill did not light');
    if (v.wide) note(where, 'the pills scroll the page sideways');
    await page.click('#chatRailKinds .crkind[data-source="you"]');
    await page.waitForFunction(() =>
      document.querySelectorAll('#chatRailList .crrow').length === 3, null, { timeout: 4000 });
  } catch (e) {
    note(where, `switching kinds failed: ${e.message.split('\n')[0]}`);
  }
  if (list.select) note(where, 'a selection mode is still offered');
  if (list.del) note(where, `${list.del} ✕ on the rows`);
  if (list.modal) note(where, 'the old conversations dialog is still in the page');
  for (const row of list.rows) {
    if (row.h < MIN_TARGET) note(where, `"${row.title}" row is ${row.h}px`);
    if (!row.more) note(where, `"${row.title}" has no ⋯`);
    if (touch && row.moreH < MIN_TARGET) note(where, `"${row.title}" ⋯ is ${row.moreH}px`);
    if (touch && !row.moreShown) note(where, `"${row.title}" ⋯ is invisible on touch`);
    if (/^Discussing/.test(row.title)) note(where, 'a discussion is still titled "Discussing"');
  }

  // ---- ⋯ › Delete, with an Undo ----------------------------------------
  try {
    await page.evaluate(() => { window.__posts.length = 0; });
    const last = page.locator('#chatRailList .crrow').nth(2);
    await last.hover().catch(() => {});
    await last.locator('.crmore').click();
    await page.waitForSelector('#chipPop:not(.hidden) .crmenudel');
    const items = await page.evaluate(() =>
      [...document.querySelectorAll('#chipPop .cardmenuitem b')].map((b) => b.textContent));
    if (items.join() !== 'Delete') note(where, `the row menu offers ${JSON.stringify(items)}`);
    await page.click('#chipPop .crmenudel');
    await page.waitForFunction(() => window.__posts.some((x) => /delete$/.test(x.path)),
      null, { timeout: 3000 });
    await page.waitForSelector('#toast .toastundo', { timeout: 3000 });
    const undo = await page.textContent('#toast .toastundo');
    if (undo !== 'Undo') note(where, `the delete toast offers "${undo}"`);
  } catch (e) {
    note(where, `⋯ › Delete did not work: ${String(e.message).split('\n')[0]}`);
  }

  // ---- a row opens the transcript; the phone has a way back -------------
  await page.evaluate(() => resumeConversation({ id: 'c-old' }));
  await page.evaluate(() => { chatState.sessionId = 'c-old'; renderChatHead(); });
  const opened = await page.evaluate(`({
    onList: document.body.classList.contains('ask-list'),
    chat: ${visible('#termChat')},
    back: ${visible('#chatBack')},
    backH: Math.round(document.querySelector('#chatBack').getBoundingClientRect().height),
    title: document.querySelector('#chatHeadTitle').textContent,
    fabs: ${visible('#termMenu')} && ${visible('#termExpand')},
  })`);
  if (opened.onList) note(where, 'opening a row stayed on the list');
  if (!opened.chat) note(where, 'opening a row showed no transcript');
  if (!opened.fabs) note(where, 'Chat options / Full-screen terminal are not on screen');
  if (touch) {
    if (!opened.back) note(where, 'a transcript has no way back to the list');
    if (opened.backH < MIN_TARGET) note(where, `the back button is ${opened.backH}px`);
    if (opened.title !== 'Bedroom thermostat schedule') {
      note(where, `the head says "${opened.title}"`);
    }
    await page.click('#chatBack');
    const back = await page.evaluate(() => document.body.classList.contains('ask-list'));
    if (!back) note(where, 'the back button did not return to the list');
    await page.evaluate(() => askShow('chat'));
  } else if (opened.back) {
    note(where, 'a back button beside a rail that is already the list');
  }

  // ---- one reply, folded --------------------------------------------------
  const replied = await page.evaluate(([finding, ts]) => {
    state.findings = [finding];
    chatState.runState = 'ready';
    chatReset();
    const evs = [
      { type: 'user', text: 'Which of my devices have stopped reporting?' },
      { type: 'thinking', text: 'Look at the unavailable ones first.' },
      { type: 'tool', id: 't1', name: 'Bash', summary: 'ls /config', input: '{}' },
      { type: 'tool_result', id: 't1', ok: true, text: 'automations.yaml' },
      { type: 'permission', id: 'perm-1', tool: 'Edit', summary: 'automations.yaml',
        input: '{"file_path":"/config/automations.yaml"}' },
      { type: 'tool', id: 't2', name: 'mcp__home-assistant__get_history',
        summary: 'sensor.garage_battery', input: '{}' },
      { type: 'tool_result', id: 't2', ok: false, text: 'timeout' },
      { type: 'text', text: 'Let me check one more thing.' },
      { type: 'background', status: 'completed', summary: 'scan', text: 'done' },
      { type: 'text', text: 'Two devices have stopped: the garage sensor and the porch PIR.' },
      { type: 'resolutions', id: 'res-1', finding_ts: ts,
        options: [{ label: 'Replaced the battery', verb: 'done' }] },
      { type: 'result', duration_ms: 2100, turns: 3 },
      { type: 'user', text: 'And the porch?' },
      { type: 'tool', id: 't3', name: 'ToolSearch', summary: 'porch', input: '{}' },
      { type: 'tool_result', id: 't3', ok: true, text: 'binary_sensor.porch' },
      { type: 'text', text: 'The porch PIR last reported on Tuesday.' },
      { type: 'result', duration_ms: 900, turns: 1 },
    ];
    evs.forEach((ev) => {
      if (ev.type === 'permission') chatPermission(ev); else chatRender(ev);
    });
    const log = document.querySelector('#chatLog');
    const folds = [...log.querySelectorAll('details.steps')];
    // checkVisibility, not a box: a closed <details> hides its content
    // with content-visibility, which can leave a box behind.
    const shown = (n) => !!n && n.checkVisibility({ visibilityProperty: true });
    return {
      folds: folds.map((f) => ({
        label: f.querySelector('.steplabel').textContent,
        open: f.open,
        steps: f.querySelector('.stepsbody').childElementCount,
        parent: f.parentElement === log,
      })),
      rowsShown: [...log.querySelectorAll('.toolcall, .think')].filter(shown).length,
      rowsLoose: [...log.querySelectorAll('.toolcall, .think')]
        .filter((n) => !n.closest('details.steps')).length,
      perm: shown(log.querySelector('.permcard')) && !log.querySelector('.steps .permcard'),
      res: shown(log.querySelector('.chatres')) && !log.querySelector('.steps .chatres'),
      saves: [...log.querySelectorAll('.savereport')].map((b) => ({
        text: b.textContent,
        answer: b.closest('.msg.bot').textContent.slice(0, 20),
        h: Math.round(b.getBoundingClientRect().height),
      })),
      docWidth: document.documentElement.scrollWidth,
    };
  }, [FINDING, FINDING_TS]);
  if (replied.folds.length !== 2) note(where, `${replied.folds.length} folds for 2 replies`);
  const [first, second] = replied.folds;
  if (first) {
    if (first.label !== 'Worked through 4 steps · 1 failed') {
      note(where, `the first fold says "${first.label}"`);
    }
    if (first.open) note(where, 'the fold is open by default');
  }
  if (second && second.label !== 'Worked through 1 step') {
    note(where, `the second fold says "${second.label}"`);
  }
  if (replied.rowsShown) note(where, `${replied.rowsShown} tool row(s) on screen by default`);
  if (replied.rowsLoose) note(where, `${replied.rowsLoose} tool row(s) outside any fold`);
  if (!replied.perm) note(where, 'the approval card is folded away or not shown');
  if (!replied.res) note(where, 'the resolutions card is folded away or not shown');
  if (replied.saves.length !== 2) {
    note(where, `${replied.saves.length} "Save as report" buttons for 2 replies`);
  }
  for (const s of replied.saves) {
    if (s.text !== 'Save as report') note(where, `the save button says "${s.text}"`);
    if (/^Let me check/.test(s.answer)) note(where, 'Save as report sits on the preamble');
    if (touch && s.h < MIN_TARGET) note(where, `Save as report is ${s.h}px`);
  }
  if (replied.docWidth > width + 0.5) note(where, `page scrolls sideways (${replied.docWidth}px)`);

  // ---- Save as report asks again as a report card -------------------------
  await page.evaluate(() => { window.__posts.length = 0; });
  await page.locator('#chatLog .savereport').first().click();
  await page.waitForFunction(() => window.__posts.length > 0, null, { timeout: 3000 })
    .catch(() => {});
  const saved = await page.evaluate(() => window.__posts[0] || {});
  if (!/api\/generate$/.test(saved.path || '')) {
    note(where, `Save as report went to ${saved.path || '(nowhere)'}`);
  } else if (!(saved.body && saved.body.report === true
               && saved.body.question === 'Which of my devices have stopped reporting?')) {
    note(where, `Save as report sent ${JSON.stringify(saved.body)}`);
  }

  // ---- a discussion: the card, linked, with the card's verbs -------------
  const disc = await page.evaluate(async ([ts, title]) => {
    chatReset();
    chatRender({ type: 'user', text: `Discussing: ${title}\nSeverity: warning\nYou flagged this.` });
    chatRender({ type: 'text', text: 'It is real.' });
    await restoreChatFinding(ts);
    const strip = document.querySelector('#chatFinding');
    return {
      bubble: document.querySelector('#chatLog .msg.user .dtitle')?.textContent || '',
      saves: document.querySelectorAll('#chatLog .savereport').length,
      strip: !strip.classList.contains('hidden'),
      title: document.querySelector('#chatFindingText').textContent,
      verbs: [...strip.querySelectorAll('.cfacts .btn')]
        .filter((b) => !b.classList.contains('hidden')).map((b) => b.textContent.trim()),
      heights: [...strip.querySelectorAll('.cfacts .btn, #chatFindingText')]
        .map((b) => Math.round(b.getBoundingClientRect().height)),
    };
  }, [FINDING_TS, CARD_TITLE]);
  if (disc.bubble !== CARD_TITLE) note(where, `the opener reads "${disc.bubble}"`);
  if (disc.saves) note(where, 'a discussion opener offers Save as report');
  if (!disc.strip) note(where, 'the discussed card is not above the composer');
  if (disc.title !== CARD_TITLE) note(where, `the strip names "${disc.title}"`);
  for (const v of disc.verbs) {
    if (!STRIP_VERBS.has(v)) note(where, `the strip has a "${v}" button`);
  }
  if (disc.verbs.length !== 4) note(where, `the strip offers ${disc.verbs.join(', ')}`);
  if (touch) {
    disc.heights.forEach((h) => { if (h < MIN_TARGET) note(where, `a strip control is ${h}px`); });
  }

  // ---- the composer: no Resume -------------------------------------------
  const comp = await page.evaluate(() => {
    const out = {};
    for (const [state, hint] of [['paused', ''],
      ['paused_room', 'brAIn keeps 3 chats running at once. Sending picks this one back up and pauses the quietest']]) {
      chatState.composer = { state, label: state === 'paused' ? '' : 'Paused to make room', hint };
      renderComposerState();
      const host = document.querySelector('#chatState');
      out[state] = {
        shown: getComputedStyle(host).display !== 'none',
        button: document.querySelector('#chatStateAct').textContent,
      };
    }
    return out;
  });
  if (comp.paused.shown) note(where, 'a plain pause still draws the composer line');
  if (comp.paused_room.button) note(where, `a cap's pause offers "${comp.paused_room.button}"`);

  // ---- the card link goes back to Today -----------------------------------
  await page.click('#chatFindingText');
  const went = await page.evaluate(() => currentView);
  if (went !== 'findings') note(where, `the card's title went to "${went}"`);
  await openView(page, 'terminal');

  // ---- cut text stays cut -------------------------------------------------
  const text = await page.evaluate(() => document.querySelector('#viewTerminal').innerText);
  for (const re of CUT) {
    if (re.test(text)) note(where, `cut text is back: ${re}`);
  }
  const html = await page.evaluate(() => document.body.innerHTML);
  if (/Resume now/.test(html)) note(where, '"Resume now" is still in the page');

  console.log(`${String(width).padStart(5)}  list ${list.rows.length} rows · folds `
    + replied.folds.map((f) => `"${f.label}"`).join(', '));
  await context.close();
}

// Nothing to list: a phone opens on the composer.
for (const { width, touch } of CASES) {
  const where = `${width}px empty`;
  const context = await browser.newContext({
    viewport: { width, height: 860 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.addInitScript('window.__noConvs = true;');
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'terminal');
  await page.waitForTimeout(600);
  const m = await page.evaluate(() => {
    const shown = (n) => {
      if (!n) return false;
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== 'hidden';
    };
    const fab = (id) => {
      const n = document.getElementById(id);
      return { shown: shown(n), said: n ? (n.innerText || '').trim() : '' };
    };
    return { composer: shown(document.getElementById('chatInput')),
             list: document.body.classList.contains('ask-list'),
             menu: fab('termMenu'), expand: fab('termExpand') };
  });
  if (!m.composer) note(where, 'no message box with nothing to list');
  if (touch && m.list) note(where, 'a phone opens on an empty list');
  if (touch) {
    for (const [name, f] of [['⋯', m.menu], ['⤢', m.expand]]) {
      if (f.shown && !f.said) note(where, `the ${name} control floats there unnamed`);
    }
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-ask: ${failures.length} failure(s)`);
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log(`measure-ask: OK across ${CASES.map((c) => c.width).join(', ')}px`);
