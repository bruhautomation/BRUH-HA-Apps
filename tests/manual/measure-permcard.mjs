// Drive the chat's approval card, and the way out of asking from it.
//
// The card is where the asking happens, so it is where "Let brAIn act
// without asking" has to be findable: "Stop asking…" opens ⚙ at the switch,
// and "Always allow" answers with the rule the CLI itself suggested. Both
// are easy to get quietly wrong in ways no server test can see — a button
// that renders under a discussion (which names its own mode and must keep
// asking), a scope line still on screen after the card was answered, a
// dialog that opens shut on the section the switch lives in, or answers
// that are not thumb targets on the phone the chat is meant for.
//
// So this loads the panel's REAL markup and app.js behind a stubbed fetch,
// renders cards through the real `chatPermission`, presses the real
// buttons, and checks:
//
//   * a card the CLI offered a suggestion on shows Allow once, Don't allow
//     and Always allow, and says in words what Always allow adds and for
//     how long;
//   * pressing Always allow POSTs `always: true` for that request id, and
//     the answered card says "Always allowed" with the offer gone;
//   * a discussion's card (no suggestion, `stop_asking: false`) offers
//     neither way out;
//   * "Stop asking…" opens ⚙ with Permissions open, the switch's row
//     marked and inside the dialog's visible area;
//   * at 390 every answer is at least 44px tall, and nothing scrolls
//     sideways;
//   * in a reply, neither the approval card nor a question card is folded
//     into the "Worked through N steps" disclosure the tool calls go into.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 1200];
const MIN_TARGET = 44;

const STUB = `
window.__posted = [];
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/chat/permission')) {
    window.__posted.push(JSON.parse((opts && opts.body) || '{}'));
    return answer({ ok: true });
  }
  if (p.includes('api/settings')) {
    return answer({
      settings: {
        auto_enabled: true, capture: false, terminal_ui: 'chat',
        chat_max_sessions: 3, gather_mode: 'search', refresh_mode: 'changed',
        plan: 'pro', budget_percent: 25, refresh_hours: 12, history_days: 7,
        timeout_minutes: 8, history_keep_runs: 20, history_keep_days: 30,
        model: 'claude-sonnet-4-5', onboarded: true,
        dangerously_skip_permissions: false,
      },
      models: [{ id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5',
                 group: 'Recommended', hint: 'the everyday one' }],
      usage: { source: 'account', used_percent: 18, week_percent: 9,
               window_tokens: 42000, plan_label: 'Pro',
               resets_at: Math.floor(Date.now() / 1000) + 7200,
               week_resets_at: Math.floor(Date.now() / 1000) + 200000 },
      options_synced: true, model_label: 'Claude Sonnet 4.5',
    });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth_token',
      auth_source: 'local', auth_check: { state: 'ok', error: '' },
      model: 'claude-sonnet-4-5', settings: { onboarded: true },
      usage: { percent: 18, source: 'account' }, auto: { enabled: true },
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/onboarding')) return answer({ state: 'done', onboarded: true });
  if (p.endsWith('api/auth')) {
    return answer({ authenticated: true, type: 'oauth_token', source: 'local',
      auth_check: { state: 'ok', error: '', running: false },
      stores: { local: { present: true }, cli: { present: false },
                shared: { present: false } } });
  }
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

// A card the CLI offered "always" on, and one from a discussion — the
// shapes `ChatSession._take_permission_request` emits.
const OFFERED = {
  type: 'permission', id: 'perm-1', tool: 'Bash', kind: 'permission',
  questions: [], summary: 'ls /config/packages', input: '{\n  "command": "ls /config/packages"\n}',
  always: 'Bash(ls:*)', always_until: 'restart', stop_asking: true,
};
const DISCUSSING = {
  type: 'permission', id: 'perm-2', tool: 'mcp__home-assistant__call_service',
  kind: 'permission', questions: [], summary: 'light.turn_on', input: '{}',
  always: '', always_until: '', stop_asking: false,
};

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const width of WIDTHS) {
  const touch = width <= 430;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch,
  });
  const page = await context.newPage();
  const where = `${width}px`;
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.waitForSelector('#settingsBtn');

  // ---- a card the CLI offered "always" on --------------------------------
  // Rendered through the real `chatPermission`, then lifted into a visible
  // wrapper: the chat log lives in a tab that is not in front, and a card
  // measured inside a hidden pane measures as nothing.
  const offered = await page.evaluate((ev) => {
    chatPermission(ev);
    const card = chatState.permCard;
    const wrap = document.createElement('div');
    wrap.id = 'probe';
    wrap.style.cssText = 'padding:12px;display:flex;flex-direction:column;';
    document.body.prepend(wrap);
    wrap.appendChild(card);
    const btns = [...card.querySelectorAll('.permrow .btn')].map((b) => {
      const r = b.getBoundingClientRect();
      return { text: b.textContent.trim(), h: Math.round(r.height), right: r.right };
    });
    const stop = card.querySelector('.permstop');
    const sr = stop ? stop.getBoundingClientRect() : null;
    return {
      btns,
      scope: (card.querySelector('.permscope') || {}).textContent || '',
      stop: stop ? { text: stop.textContent.trim(), h: Math.round(sr.height) } : null,
      cardRight: card.getBoundingClientRect().right,
      docWidth: document.documentElement.scrollWidth,
    };
  }, OFFERED);

  const labels = offered.btns.map((b) => b.text);
  for (const want of ['Allow once', "Don't allow", 'Always allow']) {
    if (!labels.includes(want)) note(where, `no "${want}" on a card that offered one`);
  }
  if (!/Bash\(ls:\*\)/.test(offered.scope)) {
    note(where, `the scope line does not say what Always allow adds: "${offered.scope}"`);
  }
  if (!/restarts/.test(offered.scope)) {
    note(where, `the scope line does not say how long it lasts: "${offered.scope}"`);
  }
  if (!offered.stop) note(where, 'no "Stop asking…" on a card that should offer it');
  if (touch) {
    for (const b of offered.btns) {
      if (b.h < MIN_TARGET) note(where, `"${b.text}" is ${b.h}px, under ${MIN_TARGET}`);
    }
    if (offered.stop && offered.stop.h < MIN_TARGET) {
      note(where, `"Stop asking…" is ${offered.stop.h}px, under ${MIN_TARGET}`);
    }
  }
  if (offered.cardRight > width + 0.5) note(where, 'the card hangs off the screen');
  if (offered.docWidth > width) note(where, `page scrolls sideways (${offered.docWidth}px)`);

  // ---- Always allow posts the yes, and the answered card drops the offer --
  try {
    await page.click('#probe .permrow .btn:has-text("Always allow")');
    await page.waitForFunction(() => window.__posted.length > 0, null, { timeout: 3000 });
    const posted = await page.evaluate(() => window.__posted[0]);
    if (!(posted.id === 'perm-1' && posted.allow === true && posted.always === true)) {
      note(where, `Always allow posted ${JSON.stringify(posted)}`);
    }
    const done = await page.evaluate(() => {
      chatPermissionDone({ id: 'perm-1', answered: true, allow: true, always: true });
      const card = document.querySelector('#probe .permcard');
      return {
        note: (card.querySelector('.permnote') || {}).textContent || '',
        leftovers: card.querySelectorAll('.permscope, .permfoot, .permrow').length,
      };
    });
    if (done.note !== 'Always allowed') note(where, `the answered card says "${done.note}"`);
    if (done.leftovers) note(where, 'the answered card still shows what it offered');
  } catch (e) {
    note(where, `pressing Always allow failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- a discussion offers no way out of asking -----------------------
  const discussing = await page.evaluate((ev) => {
    chatPermission(ev);
    const card = chatState.permCard;
    return {
      always: [...card.querySelectorAll('.permrow .btn')]
        .some((b) => /Always/.test(b.textContent)),
      scope: !!card.querySelector('.permscope'),
      stop: !!card.querySelector('.permstop'),
    };
  }, DISCUSSING);
  if (discussing.always || discussing.scope) {
    note(where, 'a discussion card offers Always allow');
  }
  if (discussing.stop) note(where, 'a discussion card offers "Stop asking…"');

  // ---- in a reply, the cards stand outside the folded working --------------
  // Tool calls and thinking fold into one "Worked through N steps" per
  // reply. An approval card and a question card are questions the CLI is
  // blocked on, so they must never be inside it.
  const inReply = await page.evaluate(([offered]) => {
    chatState.runState = 'busy';
    chatReset();
    const log = document.querySelector('#chatLog');
    const out = {};
    chatRender({ type: 'user', text: 'Tidy the packages folder' });
    chatRender({ type: 'tool', id: 't1', name: 'Bash', summary: 'ls', input: '{}' });
    chatRender({ type: 'tool_result', id: 't1', ok: true, text: 'a.yaml' });
    chatRender(offered);
    const perm = log.querySelector('.permcard');
    out.permFolded = !!(perm && perm.closest('details.steps'));
    out.permThere = !!perm;
    chatRender({ type: 'permission_done', id: offered.id, answered: true, allow: true });
    chatRender({ type: 'tool', id: 't2', name: 'Edit', summary: 'a.yaml', input: '{}' });
    chatRender({ type: 'permission', id: 'q-1', kind: 'question', tool: 'AskUserQuestion',
      questions: [{ question: 'Which file?', header: 'File', multi: false,
        options: [{ label: 'a.yaml', description: '' }] }] });
    const q = log.querySelector('.qcard');
    out.questionFolded = !!(q && q.closest('details.steps'));
    out.questionThere = !!q;
    out.folds = log.querySelectorAll('details.steps').length;
    chatState.runState = 'idle';
    return out;
  }, [{ ...OFFERED, id: 'perm-r' }]);
  if (!inReply.permThere) note(where, 'no approval card rendered in a reply');
  if (inReply.permFolded) note(where, 'the approval card was folded into the steps');
  if (!inReply.questionThere) note(where, 'no question card rendered in a reply');
  if (inReply.questionFolded) note(where, 'the question card was folded into the steps');
  if (inReply.folds !== 1) note(where, `${inReply.folds} step folds for one reply`);

  // ---- Stop asking opens ⚙ at the switch ---------------------------------
  try {
    await page.evaluate((ev) => {
      chatPermission(ev);
      document.querySelector('#probe').appendChild(chatState.permCard);
    }, { ...OFFERED, id: 'perm-3' });
    await page.click('#probe .permcard:last-child .permstop');
    await page.waitForSelector('#setModal.open');
    await page.waitForFunction(
      () => document.querySelector('#setSkipPermsRow').classList.contains('setflash'),
      null, { timeout: 4000 });
    const landed = await page.evaluate(() => {
      const sec = document.querySelector('#setsecPermissions');
      const row = document.querySelector('#setSkipPermsRow').getBoundingClientRect();
      return {
        open: !sec.hidden,
        inView: row.top >= -1 && row.bottom <= window.innerHeight + 1,
        checked: document.querySelector('#setSkipPerms').checked,
      };
    });
    if (!landed.open) note(where, '"Stop asking…" opened ⚙ on another section than Permissions');
    if (!landed.inView) note(where, 'the switch is not in view after "Stop asking…"');
    if (landed.checked) note(where, 'the switch rendered on over a saved off');
  } catch (e) {
    note(where, `"Stop asking…" did not land on the switch: ${String(e.message).split('\n')[0]}`);
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-permcard: ${failures.length} failure(s)`);
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log(`measure-permcard: OK across ${WIDTHS.join(', ')}px`);
