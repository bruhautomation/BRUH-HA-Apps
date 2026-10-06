// Drive the ⚙ dialog and assert it is a thing somebody can get through.
//
// What this exists to prevent is the shape the dialog had shipped in: one
// flat scroll of a dozen headings with a paragraph of prose under nearly
// every control. Measured on the unmodified dialog, behind this same stub,
// the scrolling body was **5,910px at 390 and 3,837px at 1,200**. It became
// six disclosures with fifteen "?" bubbles carrying the long prose; the
// redesign (docs/design/ui-redesign-2026-10.md, PR 9) makes it EIGHT named
// sections — Account, Usage & schedule, Permissions, Sources,
// Notifications, Memory, Diagnostics, Guide — and takes every "?" out,
// because a tooltip is the one place a phone cannot read.
//
// So the checks are about the reorganisation rather than about the styling:
//
//   * the body's scroll height at OPEN time is under a budget per width.
//   * there are exactly eight sections, named as the doc names them, each
//     summary clears the touch floor and says in a second line what is
//     behind it.
//   * there is NO "?" bubble anywhere in the dialog, and no hint runs past
//     two sentences: the long version is cut or in the Guide.
//   * the safety prose stays on the page: the sharing box's backup warning,
//     the shell-command caveat under "Let brAIn act without asking" (and it
//     is still there when the line above it turns into the stale-session
//     warning), and the calendar note beside the calendar picker.
//   * Sign out is neutral at rest, never filled or coloured red.
//   * a section remembers being opened, across closing the dialog AND
//     across a reload, in both directions.
//   * the Diagnostics loaders do not run until Diagnostics is opened, and
//     opening it fills every block: Anything wrong, how right it has been,
//     the measurements, the overnight check, who can reach the house, the
//     runs by kind, and ONE Export report (Share) where four copy/write
//     buttons used to be.
//   * Memory shows the document with Edit and Export, and the queue as a
//     read-only list with its count — and no "File into memory now".
//   * Sources reads the cameras and the calendars only when it opens.
//   * Guide lists eight groups and opens the docs, whose nav is eight
//     headings with no emoji.
//   * every visible button says one of the doc's verbs.
//   * every text control clears the 16px iOS floor at 390, the page never
//     scrolls sideways, and every element id handlers bind to is present.
//
// Drives the panel's REAL markup and its real `openSettings` /
// `restoreSettingsSections` behind a stubbed fetch. A copy of the dialog in
// this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 1200];
const MIN_TARGET = 44;
const MIN_TEXT = 16;

// Before any reorganisation: 5910 at 390, 3837 at 1200. Six disclosures
// brought that to ~2170 and ~1600 with two of them open. Eight sections
// with the same two open (Account and Usage & schedule) and the ? prose cut
// measured 1569 at 390 and 1268 at 1200; the budgets leave room for a font
// or a hairline to move and not for a section to come back flat.
const MAX_SCROLL = { 390: 1750, 1200: 1400 };

// The verbs a button in ⚙ may say. The doc's vocabulary, plus the few
// labels it names for this dialog itself (Sign in again, Sign out, Edit,
// Export) and the generic pair a dialog row needs (Cancel, Remove, View).
const VERBS = new Set(['Apply', 'Plan', 'Add to list', 'Snooze', 'Ignore', 'Done',
  'Restore', 'Undo', 'Ask', 'Send', 'Recheck', 'Run', 'Save', 'Share', 'Delete',
  'Sign in again', 'Sign out', 'Edit', 'Export', 'Cancel', 'Remove', 'View', '✕']);

// Every id handlers in app.js bind to, and several other measures drive.
// Losing one is a dead control rather than a layout problem.
const IDS = [
  'authBody', 'authRecheck', 'authShareTog', 'authShareNote', 'authShareCost',
  'authSignin', 'authSignout', 'capBody', 'capMax', 'deepBody',
  'deepLast', 'deepRun', 'diagBody', 'diagCopy', 'diagCurious', 'diagMeasure',
  'diagRefresh', 'probBody', 'rehearseBody', 'rehearseLast', 'rehearseRun',
  'rehearseSweep', 'setBudget', 'setBudgetVal', 'setCapture', 'setChatSessions',
  'setClose', 'setEnabled', 'setGatherMode', 'setHistoryDays', 'setKeepDays',
  'setKeepRuns', 'setModel', 'setThinking', 'setModelCustom', 'setPlan',
  'setRefresh', 'setRefreshMode', 'setSyncNote', 'setTerminalUi', 'setTimeout',
  'usageFill', 'usageMark', 'usageText', 'usageWeekFill', 'usageDetail',
  'setNotifyPolicy', 'setNotifyLearned', 'setSpeakFirst',
  'setSkipPerms', 'setSkipPermsRow', 'setSkipPermsNote', 'setSkipPermsCaveat',
  'setHouseRules', 'setHouseRulesSave', 'setCameras', 'setCalendars',
  'setCalendarsNote', 'setMemView', 'setMemEdit', 'setMemExport', 'setMemTa',
  'setMemQueue', 'setMemCount', 'diagAccuracy', 'diagMeasures', 'diagOvernight',
  'diagOvernightRun', 'diagAccess', 'diagAccessRun', 'setGuide',
];

// The sections, in order, and whether the shipped markup opens them.
const SECTIONS = [
  { sec: 'account', name: 'Account', open: true },
  { sec: 'usage', name: 'Usage & schedule', open: true },
  { sec: 'permissions', name: 'Permissions', open: false },
  { sec: 'sources', name: 'Sources', open: false },
  { sec: 'notifications', name: 'Notifications', open: false },
  { sec: 'memory', name: 'Memory', open: false },
  { sec: 'diagnostics', name: 'Diagnostics', open: false },
  { sec: 'guide', name: 'Guide', open: false },
];

// The reads behind Diagnostics. Any of these before it is opened is the
// lazy load not being lazy.
const DIAG_URLS = ['api/diagnostics', 'api/reports', 'api/capture',
                   'api/doctor/deep', 'api/doctor/rehearse', 'api/sre',
                   'api/access', 'api/knowledge/house'];

const CUT = ['Copy selected', 'Copy all', 'Write a report now',
             'Copy for a bug report', 'File into memory now', 'Check it now',
             'Measure the house now', 'Run deep check', 'Rehearse…'];

const NOW = Math.floor(Date.now() / 1000);

const STUB = `
window.__fetched = [];
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  window.__fetched.push(p);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/cameras')) {
    return answer({
      cameras: [
        { entity_id: 'camera.porch', name: 'Porch', allowed: true },
        { entity_id: 'camera.garden_long_name_that_wraps_on_a_phone',
          name: 'The garden camera over the vegetable beds', allowed: false },
        { entity_id: 'camera.roborock_s7_map', name: 'Roborock S7 Map', allowed: false },
        { entity_id: 'camera.upstairs_map', name: 'Upstairs map', allowed: true },
      ],
      allowed: ['camera.porch', 'camera.upstairs_map'], per_day: 12, used_today: 3, error: '',
      registry_read: true,
    });
  }
  if (p.includes('api/occasions')) {
    return answer({ available: [
      { entity_id: 'calendar.family', name: 'Family' },
      { entity_id: 'calendar.bins', name: 'Bin collection' }],
      calendars: ['calendar.bins'] });
  }
  if (p.includes('api/house-rules')) {
    return answer({ rules: [{ text: 'never turn the heating above 23', compiled: true }] });
  }
  if (p.includes('api/settings') && opts && opts.method === 'PUT') {
    (window.__puts = window.__puts || []).push(JSON.parse(opts.body));
  }
  if (p.includes('api/settings')) {
    const put = !!(opts && opts.method === 'PUT');
    const sent = put ? JSON.parse(opts.body || '{}') : {};
    if (put && window.__refusePut) {
      return new Response("brAIn could not save that to the add-on's options, "
        + 'so it is still asking.', { status: 409 });
    }
    if ('dangerously_skip_permissions' in sent) {
      window.__skipPerms = sent.dangerously_skip_permissions === true;
    }
    return answer({
      ...(window.__permSessions !== undefined
        ? { permission_sessions: window.__permSessions } : {}),
      settings: {
        auto_enabled: true, capture: false, terminal_ui: 'chat',
        chat_max_sessions: 3, gather_mode: 'search', refresh_mode: 'changed',
        plan: 'pro', budget_percent: 25, refresh_hours: 12, history_days: 7,
        timeout_minutes: 8, history_keep_runs: 20, history_keep_days: 30,
        model: 'claude-sonnet-4-5', onboarded: true,
        dangerously_skip_permissions: window.__skipPerms === true,
        notify_policy: 'wake me for water or smoke; batteries can wait',
        speak_first: true,
        notify_policy_learned: [{ id: 'a1b2c3d4', subject: 'Garden lights',
          clause: 'Notifications about Garden lights (light.garden) can wait '
                  + 'for the morning list, unless they are critical.', at: 1756000000 }],
      },
      models: [{ id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5',
                 group: 'Recommended', hint: 'the everyday one' }],
      usage: { source: 'account', used_percent: 18, week_percent: 9,
               window_tokens: 42000, plan_label: 'Pro',
               resets_at: ${NOW} + 7200, week_resets_at: ${NOW} + 200000 },
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
    return answer({
      authenticated: true, type: 'oauth_token', source: 'local',
      saved_at: 1756000000, can_share: true,
      auth_check: { state: 'ok', error: '', checked_at: 1756000000, running: false },
      recheck_seconds: 21600,
      shared_path: '/config/.brain/secrets/claude_auth.json',
      stores: { local: { present: true, saved_at: 1756000000 },
                cli: { present: false }, shared: { present: false } },
    });
  }
  if (p.includes('api/diagnostics')) {
    return answer({
      generated_at: ${NOW}, version: 'test',
      health: { state: 'ok', reason: '' }, faults: [],
      runs: { total: 12, failures: [] }, checks: { ran: 15, skipped: [] },
    });
  }
  if (p.includes('api/reports')) {
    return answer({ reports: [
      { name: '2026-09-08-0912-run.txt', ts: ${NOW} - 1800, kind: 'run',
        headline: 'insight run ended timeout', count: 1, bytes: 400 }],
      dir: '/share/brain/reports', available: true, max: 30 });
  }
  if (p.includes('api/capture')) {
    return answer({ captures: [], enabled: false, max_files: 50, dir: '/data/capture' });
  }
  if (p.includes('api/baselines')) return answer({ running: false, entities: 0 });
  if (p.includes('api/doctor/rehearse')) {
    return answer({ running: false, sweeping: false, last: {}, plan: [] });
  }
  if (p.includes('api/doctor')) return answer({ running: false, last: {}, stages: [] });
  if (p.includes('api/sre')) {
    return answer({ running: false, last: { at: ${NOW} - 3600, records: 12, causes: 1,
                                            filed: 1, cleared: 0 } });
  }
  if (p.includes('api/access')) {
    return answer({ running: false, at: ${NOW} - 7200, open: 1,
                    sentence: 'Two admins; the front door lock is worth a PIN.' });
  }
  if (p.includes('api/knowledge/house')) {
    return answer({ stores: {
      rhythm: { state: 'collecting', have: 4, need: 10, unit: 'days' },
      baselines: { state: 'ready', updated_at: ${NOW} - 3600, summary: '258 sensors' },
      thermal: { state: 'unavailable', reason: 'No outdoor thermometer.' },
    } });
  }
  if (p.includes('api/knowledge')) {
    return answer({
      shared_memory: '# Home Memory\\n\\n## Preferences\\n- The garage fridge runs 24/7.',
      inbox: [{ ts: ${NOW} - 60, source: 'panel', text: 'The porch light is on a timer.' },
              { ts: ${NOW} - 30, source: 'voice', text: 'Mia calls the lounge the den.' }],
      inbox_pending: 5, memory_state: { merging: false },
    });
  }
  if (p.includes('api/chat/conversations')) {
    const src = (p.match(/source=([^&]+)/) || [])[1] || 'you';
    return answer({
      conversations: src === 'voice'
        ? [{ id: 'v1', title: 'Turn on the lounge lights', age: '2 h ago', source: 'voice' }]
        : [],
      sources: [
        { id: 'you', label: 'Chats', count: 31 },
        { id: 'voice', label: 'Voice', count: 55, blurb: 'what Assist asked' },
        { id: 'card', label: 'Cards', count: 15 },
      ],
    });
  }
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [],
      scorecard: [{ source: 'check:dev.frozen', title: 'Sensors frozen on one value',
                    confirmed: 8, total: 14, wrong: 6 },
                  { source: 'check:forecast.decline', title: 'Declining readings',
                    confirmed: 0, total: 3, wrong: 3 }],
      muted: [{ source: 'check:auto.conflict', title: 'Automations that fight' }] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const heights = [];

// A hint's own text, sentence-counted. `e.g.`/`i.e.` are abbreviations
// rather than full stops. `#usageText` is out: it is a live reading of the
// account's usage stated in sentences, and its length belongs to the
// payload. Everything else here explains a control, which is what is capped.
const SENTENCE_PROBE = `
window.__hintSentences = () => {
  return [...document.querySelectorAll(
    '#setModal .hint, #setModal .bigcheck .subtext')]
    .filter((n) => n.id !== 'usageText')
    .map((n) => n.textContent.replace(/\\s+/g, ' ').trim())
    .filter((t) => t)
    .map((t) => ({
      text: t,
      sentences: (t.replace(/\\b(e\\.g|i\\.e|etc)\\./gi, '$1')
        .match(/[.!?](\\s|$)/g) || []).length,
    }));
};
window.__visibleButtons = () => [...document.querySelectorAll(
  '#setModal button, #setModal a.btn')]
  .filter((b) => b.offsetParent !== null && !b.hidden && !b.classList.contains('krow'))
  .map((b) => b.textContent.replace(/\\s+/g, ' ').trim());
`;

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const width of WIDTHS) {
  const touch = width <= 430;
  const context = await browser.newContext({
    viewport: { width, height: touch ? 740 : 900 }, hasTouch: touch, isMobile: touch,
  });
  const page = await context.newPage();
  const where = `${width}px`;
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.addInitScript(SENTENCE_PROBE);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);

  await page.click('#settingsBtn');
  await page.waitForSelector('#setModal.open');
  await page.waitForFunction(() => document.querySelector('#setSyncNote').textContent !== '');
  await page.waitForSelector('#authBody p');

  // ---- how long is the dialog ------------------------------------------
  const m = await page.evaluate(() => {
    const body = document.querySelector('#setModal .edit-body');
    const secs = [...document.querySelectorAll('#setModal .setsec')].map((d) => {
      const sum = d.querySelector('summary');
      const box = sum.getBoundingClientRect();
      return {
        sec: d.dataset.sec, open: d.open, h: Math.round(box.height), right: box.right,
        name: (d.querySelector('.setsecname') || {}).textContent || '',
        sub: (d.querySelector('.setsecsub') || {}).textContent || '',
      };
    });
    // A "?" bubble is a button whose label is a question mark, or the
    // `.btn.icon.tiny` it was built from, or any data-tip but Close's.
    const bubbles = [...document.querySelectorAll('#setModal button, #setModal [data-tip]')]
      .filter((b) => b.textContent.trim() === '?' || b.matches('.btn.icon.tiny')
        || (b.hasAttribute('data-tip') && b.id !== 'setClose'))
      .map((b) => b.id || b.getAttribute('aria-label') || b.textContent.trim());
    const small = [...document.querySelectorAll(
      '#setModal input, #setModal select, #setModal textarea')]
      .filter((c) => !['checkbox', 'radio', 'range'].includes(c.type))
      .map((c) => ({ id: c.id || c.type,
        size: Math.round(parseFloat(getComputedStyle(c).fontSize) * 10) / 10 }));
    const signout = document.querySelector('#authSignout');
    const recheck = document.querySelector('#authRecheck');
    const so = getComputedStyle(signout);
    const rc = getComputedStyle(recheck);
    const visible = (n) => !!n && n.offsetParent !== null
      && getComputedStyle(n).visibility !== 'hidden';
    const caveat = document.querySelector('#setSkipPermsCaveat');
    return {
      scrollH: body.scrollHeight,
      bodyRight: body.getBoundingClientRect().right,
      secs, bubbles, small,
      hints: window.__hintSentences(),
      docWidth: document.documentElement.scrollWidth,
      signout: { cls: signout.className, color: so.color, bg: so.backgroundColor,
                 border: so.borderColor, recheckColor: rc.color, recheckBg: rc.backgroundColor },
      backup: (document.querySelector('.sharebox') || {}).textContent || '',
      backupVisible: visible(document.querySelector('#authShareCost')),
      caveat: caveat ? caveat.textContent.replace(/\s+/g, ' ').trim() : '',
      shareTog: (() => { const t = document.querySelector('#authShareTog');
        return t && t.type === 'checkbox' && t.classList.contains('tog'); })(),
      authBody: document.querySelector('#authBody').textContent,
      usageWeek: document.querySelector('#usageWeekFill').style.width,
      buttons: window.__visibleButtons(),
      allText: document.querySelector('#setModal').textContent,
    };
  });

  heights.push(`${width}px ${m.scrollH}/${MAX_SCROLL[width]}px`);
  if (m.scrollH > MAX_SCROLL[width]) {
    note(where, `the dialog is ${m.scrollH}px of scroll at open, over the ${MAX_SCROLL[width]}px budget`);
  }

  // ---- the sections ------------------------------------------------------
  if (m.secs.length !== SECTIONS.length) {
    note(where, `${m.secs.length} sections, expected ${SECTIONS.length}`);
  }
  SECTIONS.forEach((want, i) => {
    const got = m.secs.find((s) => s.sec === want.sec);
    if (!got) { note(where, `no "${want.sec}" section`); return; }
    if (m.secs[i] && m.secs[i].sec !== want.sec) {
      note(where, `section ${i + 1} is "${m.secs[i].sec}", expected "${want.sec}"`);
    }
    if (got.h < MIN_TARGET) note(where, `the ${want.sec} summary is ${got.h}px, under ${MIN_TARGET}`);
    if (got.name.trim() !== want.name) note(where, `the ${want.sec} summary is named "${got.name.trim()}"`);
    if (got.sub.trim().length < 20) note(where, `the ${want.sec} summary says nothing about what is in it`);
    if (got.open !== want.open) note(where, `${want.sec} opens ${got.open} and should open ${want.open}`);
    if (got.right > m.bodyRight + 0.5) note(where, `${want.sec} overflows the dialog`);
  });

  // ---- no "?" bubble, and no hint past two sentences ---------------------
  if (m.bubbles.length) note(where, `"?" bubbles remain: ${m.bubbles.join(', ')}`);
  for (const h of m.hints) {
    if (h.sentences > 2) note(where, `a hint runs to ${h.sentences} sentences: "${h.text.slice(0, 70)}…"`);
  }
  for (const gone of CUT) {
    if (m.allText.includes(gone)) note(where, `"${gone}" is back in ⚙`);
  }
  if (/💡/.test(m.allText)) note(where, 'the token tips came back');

  // ---- safety prose stays on the page -------------------------------------
  if (!/backup/i.test(m.backup) || !m.backupVisible) {
    note(where, 'the sharing box does not show that a shared login travels in backups');
  }
  if (!m.shareTog) note(where, 'sharing is not a toggle (input.tog)');
  if (m.caveat !== "Protected entities are refused through brAIn's own tools, not every shell command.") {
    note(where, `the shell-command caveat reads "${m.caveat}"`);
  }

  // ---- Account: a one-line answer, Recheck, a neutral Sign out ----------
  if (!/Signed in/.test(m.authBody)) note(where, 'the account section does not say it is signed in');
  if (/danger/.test(m.signout.cls)) note(where, 'Sign out still carries the danger class');
  if (m.signout.color !== m.signout.recheckColor || m.signout.bg !== m.signout.recheckBg) {
    note(where, `Sign out is not neutral at rest (${m.signout.color} on ${m.signout.bg})`);
  }
  if (m.usageWeek !== '9%') note(where, `the week bar reads "${m.usageWeek}", not 9%`);

  // ---- every visible button says a verb ----------------------------------
  for (const label of m.buttons) {
    if (!VERBS.has(label)) note(where, `a button says "${label}"`);
  }

  // ---- the notification sentence, and a learned line's Remove ------------
  await page.click('#setsecNotify > summary');
  const learned = await page.evaluate(() => {
    const fold = document.querySelector('#setNotifyLearned details');
    if (fold) fold.open = true;
    return [...document.querySelectorAll('#setNotifyLearned .setlearnedrow')].map((r) => ({
      h: Math.round(r.querySelector('button').getBoundingClientRect().height),
      text: r.textContent }));
  });
  if (learned.length !== 1) note(where, `${learned.length} learned lines rendered, expected 1`);
  for (const l of learned) {
    if (touch && l.h < MIN_TARGET) note(where, `a learned line's Remove is ${l.h}px`);
    if (!/Garden lights/.test(l.text)) note(where, 'a learned line does not say what it is');
  }
  const pol = await page.evaluate(() => ({
    policy: document.querySelector('#setNotifyPolicy').value,
    speak: document.querySelector('#setSpeakFirst').checked,
  }));
  if (!/water/.test(pol.policy)) note(where, 'the notification sentence did not render what was saved');
  if (!pol.speak) note(where, 'the speak-first box did not render the saved yes');

  // ---- the iOS floor, and the page's own width ---------------------------
  if (touch) {
    for (const c of m.small) {
      if (c.size < MIN_TEXT) note(where, `#${c.id} renders at ${c.size}px, under the ${MIN_TEXT}px floor`);
    }
  }
  if (m.docWidth > width) note(where, `page scrolls sideways (${m.docWidth}px)`);

  // ---- every id survived the move ---------------------------------------
  const missing = await page.evaluate((ids) => ids.filter((id) => !document.getElementById(id)), IDS);
  if (missing.length) note(where, `ids lost in the move: ${missing.join(', ')}`);

  // ---- "How hard brAIn thinks" is inactive under a chosen model ----------
  const think = await page.evaluate(() => ({
    disabled: document.querySelector('#setThinking').disabled,
    note: (document.querySelector('#setThinkingNote') || {}).textContent || '',
  }));
  if (!think.disabled) note(where, 'the thinking tiers look live under a chosen model');
  if (!/Not used while a model is chosen/.test(think.note)) {
    note(where, `the thinking line does not say why it is off: "${think.note}"`);
  }

  // ---- one scrollbar ------------------------------------------------------
  const overlay = await page.evaluate(() => {
    const md = document.querySelector('#setModal');
    return { scroll: md.scrollHeight, client: md.clientHeight };
  });
  if (overlay.scroll > overlay.client) {
    note(where, `the overlay scrolls as well as the dialog (${overlay.scroll} > ${overlay.client})`);
  }

  // ---- a date is a minute, not a second -----------------------------------
  const seconds = await page.evaluate(() =>
    (document.querySelector('#setModal').innerText.match(/\b\d{1,2}:\d{2}:\d{2}\b/g) || []));
  if (seconds.length) note(where, `a time is shown to the second: ${seconds.join(', ')}`);

  // ---- Memory: the document, Edit, Export, the queue and its count -------
  try {
    const before = await page.evaluate(
      () => window.__fetched.filter((u) => /api\/knowledge($|\?)/.test(u)).length);
    if (before) note(where, 'opening ⚙ read the memory before Memory was opened');
    await page.click('#setsecMemory > summary');
    await page.waitForFunction(() => document.querySelector('#setMemCount').textContent !== '',
      null, { timeout: 4000 });
    const mem = await page.evaluate(() => ({
      count: document.querySelector('#setMemCount').textContent,
      rows: document.querySelectorAll('#setMemQueue .setmemitem').length,
      more: document.querySelector('#setMemQueue').textContent,
      doc: document.querySelector('#setMemView').textContent,
      exportHref: document.querySelector('#setMemExport').getAttribute('href'),
      buttons: [...document.querySelectorAll('#setsecMemory button, #setsecMemory a')]
        .filter((b) => b.offsetParent !== null).map((b) => b.textContent.trim()),
    }));
    if (mem.count !== '5') note(where, `the queue count reads "${mem.count}", not 5`);
    if (mem.rows !== 2) note(where, `${mem.rows} queued lines rendered, not 2`);
    if (!/3 more/.test(mem.more)) note(where, 'the queue does not say what it is not showing');
    if (!/garage fridge/.test(mem.doc)) note(where, 'the memory document did not render');
    if (mem.exportHref !== 'api/memory/export') note(where, 'Export does not link the export');
    if (mem.buttons.join('|') !== 'Edit|Export') note(where, `Memory offers ${mem.buttons.join(', ')}`);
    await page.click('#setMemEdit');
    const editing = await page.evaluate(() => !document.querySelector('#setMemTa').classList.contains('hidden')
      && /garage fridge/.test(document.querySelector('#setMemTa').value));
    if (!editing) note(where, 'Edit does not open the document as text');
    await page.click('#setMemCancel');
  } catch (e) {
    note(where, `driving Memory failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Diagnostics is lazy, and opening it fills every block -------------
  try {
    const early = await page.evaluate(
      (urls) => window.__fetched.filter((u) => urls.some((x) => u.includes(x))), DIAG_URLS);
    if (early.length) {
      note(where, `opening ⚙ fetched ${early.length} Diagnostics read(s) before it was `
                  + `opened: ${[...new Set(early)].join(', ')}`);
    }
    await page.click('#setsecDiagnostics > summary');
    await page.waitForFunction(() => /12 records read/.test(
      document.querySelector('#diagOvernight').textContent), null, { timeout: 5000 });
    const late = await page.evaluate(
      (urls) => urls.filter((x) => !window.__fetched.some((u) => u.includes(x))), DIAG_URLS);
    if (late.length) note(where, `opening Diagnostics never fetched: ${late.join(', ')}`);
    const d = await page.evaluate(() => ({
      first: (document.querySelector('#diagBody .drow .dk') || {}).textContent || '',
      accuracy: document.querySelector('#diagAccuracy').textContent,
      measures: document.querySelectorAll('#kStores .krow').length,
      measureText: document.querySelector('#diagMeasures').textContent,
      access: document.querySelector('#diagAccess').textContent,
      runs: !!document.querySelector('#diagRuns'),
      share: document.querySelector('#diagCopy').textContent.trim(),
      dev: document.querySelector('#setDiagDeveloper').open,
      buttons: window.__visibleButtons(),
      hints: window.__hintSentences(),
      bubbles: document.querySelectorAll('#setModal .btn.icon.tiny').length,
    }));
    if (d.first !== 'Anything wrong?') note(where, `Diagnostics opens on "${d.first}"`);
    if (!/8 of 14 confirmed/.test(d.accuracy)) note(where, 'the accuracy rows are missing');
    if (!/Automations that fight/.test(d.accuracy)) note(where, 'a muted producer is not listed');
    if (d.measures !== 7) note(where, `${d.measures} measurement rows, not 7`);
    if (!/4 of 10 days/.test(d.measureText)) note(where, 'a collecting measurement does not say how far');
    if (!/worth a PIN/.test(d.access)) note(where, 'the access review sentence is missing');
    if (d.runs) note(where, 'Runs is still in Diagnostics (it lives on Ask now)');
    if (d.share !== 'Share') note(where, `Export report's button says "${d.share}"`);
    if (d.dev) note(where, 'Developer opens expanded');
    for (const label of d.buttons) {
      if (!VERBS.has(label)) note(where, `a Diagnostics button says "${label}"`);
    }
    for (const h of d.hints) {
      if (h.sentences > 2) note(where, `a hint runs to ${h.sentences} sentences: "${h.text.slice(0, 70)}…"`);
    }
    if (d.bubbles) note(where, `${d.bubbles} "?" bubbles in Diagnostics`);

    // Export report: a ticked problem file is what Share copies.
    await page.click('#setDiagDeveloper > summary');
    await page.check('#probBody .probcheck');
    await page.evaluate(() => {
      window.__copied = null;
      const real = window.fetch;
      window.fetch = async (u, o) => {
        if (String(u).includes('api/reports/copy')) {
          window.__copied = JSON.parse(o.body);
          return new Response('the report', { status: 200 });
        }
        return real(u, o);
      };
    });
    await page.click('#diagCopy');
    await page.waitForFunction(() => window.__copied, null, { timeout: 4000 });
    const sent = await page.evaluate(() => window.__copied.names);
    if (JSON.stringify(sent) !== JSON.stringify(['2026-09-08-0912-run.txt'])) {
      note(where, `Share sent ${JSON.stringify(sent)} with one problem ticked`);
    }
    const devBubbles = await page.evaluate(() => document.querySelectorAll('#setModal .btn.icon.tiny').length);
    if (devBubbles) note(where, `${devBubbles} "?" bubbles under Developer`);
    await page.evaluate(() => {
      const box = document.querySelector('.copyfallback, #copyFallback');
      if (box) box.remove();
    });
  } catch (e) {
    note(where, `driving Diagnostics failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- a section remembers ------------------------------------------------
  try {
    await page.evaluate(() => {
      document.querySelector('#setsecPermissions').open = false;
      document.querySelector('#setsecUsage').open = true;
    });
    await page.click('#setsecPermissions > summary');   // shut → open
    await page.click('#setsecUsage > summary');         // open → shut
    await page.click('#setClose');
    await page.click('#settingsBtn');
    let st = await page.evaluate(() => ({
      perms: document.querySelector('#setsecPermissions').open,
      usage: document.querySelector('#setsecUsage').open,
    }));
    if (!st.perms || st.usage) {
      note(where, `reopening the dialog forgot the sections (permissions ${st.perms}, usage ${st.usage})`);
    }
    await page.reload();
    await page.waitForSelector('#settingsBtn');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    st = await page.evaluate(() => ({
      perms: document.querySelector('#setsecPermissions').open,
      usage: document.querySelector('#setsecUsage').open,
      diag: document.querySelector('#setsecDiagnostics').open,
    }));
    if (!st.perms) note(where, 'a section opened by hand was shut again after a reload');
    if (st.usage) note(where, 'a section shut by hand was open again after a reload');
    if (!st.diag) note(where, 'Diagnostics was shut again after a reload');
    await page.waitForFunction(() => window.__fetched.some((u) => u.includes('api/diagnostics')),
      null, { timeout: 4000 }).catch(() => note(where, 'a remembered-open Diagnostics fetched nothing on reopen'));
    // Permissions read the house rules when it opened.
    await page.waitForFunction(() => /heating above 23/.test(
      document.querySelector('#setHouseRules').value), null, { timeout: 4000 })
      .catch(() => note(where, 'the house rules were not read into Permissions'));
  } catch (e) {
    note(where, `driving the disclosures failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Sources: cameras and calendars, read when it opens ---------------
  try {
    const before = await page.evaluate(
      () => window.__fetched.filter((u) => u.includes('api/cameras') || u.includes('api/occasions')).length);
    if (before) note(where, 'opening ⚙ read the cameras or calendars before Sources was opened');
    await page.click('#setsecSources > summary');
    await page.waitForSelector('#setCameras .setcam', { timeout: 5000 });
    await page.waitForSelector('#setCalendars input[data-cal]', { timeout: 5000 });
    const src = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#setCameras .setcam')];
      const note = document.querySelector('#setCalendarsNote');
      return {
        rows: rows.map((r) => ({ id: r.querySelector('input').dataset.entity,
          h: Math.round(r.getBoundingClientRect().height),
          checked: r.querySelector('input').checked, right: r.getBoundingClientRect().right })),
        text: document.getElementById('setCameras').textContent,
        cals: [...document.querySelectorAll('#setCalendars input[data-cal]')]
          .map((t) => ({ id: t.dataset.cal, on: t.checked, tog: t.classList.contains('tog'),
                         h: Math.round(t.closest('label').getBoundingClientRect().height) })),
        calNote: note.textContent.replace(/\s+/g, ' ').trim(),
        calNoteVisible: note.offsetParent !== null,
        bodyRight: document.querySelector('#setsecSources .setsecbody').getBoundingClientRect().right,
        allText: document.querySelector('#setsecSources').textContent,
      };
    });
    if (src.rows.length !== 3) note(where, `${src.rows.length} camera rows, not 3`);
    if (src.rows.some((r) => r.id === 'camera.roborock_s7_map')) note(where, 'an unticked vacuum map is listed as a camera');
    if (!src.rows.some((r) => r.id === 'camera.upstairs_map')) note(where, 'a ticked vacuum map was hidden');
    if (!/1 vacuum map is left out/.test(src.text)) note(where, 'the camera list does not say a vacuum map was left out');
    src.rows.forEach((r, i) => {
      if (r.h < MIN_TARGET) note(where, `camera row ${i} is ${r.h}px`);
      if (r.right > src.bodyRight + 0.5) note(where, `camera row ${i} overflows`);
    });
    if (!/3 of 12/.test(src.text)) note(where, 'the camera list does not say how many looks are used');
    if (src.cals.length !== 2) note(where, `${src.cals.length} calendars listed, not 2`);
    if (!src.cals.some((c) => c.id === 'calendar.bins' && c.on)) note(where, 'a chosen calendar is not ticked');
    if (src.cals.some((c) => !c.tog)) note(where, 'a calendar tick is not a toggle');
    if (src.cals.some((c) => c.h < MIN_TARGET)) note(where, 'a calendar row is under the touch floor');
    if (!/^Only what is ticked is read/.test(src.calNote) || !/never as an instruction/.test(src.calNote)
        || !src.calNoteVisible) {
      note(where, `the calendar safety note is missing beside the picker: "${src.calNote}"`);
    }
    if (/No calendars yet/.test(src.allText)) note(where, 'the old empty-calendar sentence is back');
    await page.click('#setCameras .setcam:nth-child(2) input');
    await page.waitForTimeout(200);
    let put = await page.evaluate(() => (window.__puts || []).slice(-1)[0] || null);
    if (!put || JSON.stringify(put.camera_confirm || null)
        !== JSON.stringify(['camera.porch', 'camera.garden_long_name_that_wraps_on_a_phone',
                            'camera.upstairs_map'])) {
      note(where, `ticking a camera saved ${JSON.stringify(put)}`);
    }
    await page.click('#setCalendars input[data-cal="calendar.family"]');
    await page.waitForTimeout(200);
    put = await page.evaluate(() => (window.__puts || []).slice(-1)[0] || null);
    if (!put || JSON.stringify(put.occasion_calendars || null)
        !== JSON.stringify(['calendar.family', 'calendar.bins'])) {
      note(where, `ticking a calendar saved ${JSON.stringify(put)}`);
    }
  } catch (e) {
    note(where, `driving Sources failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- the permission switch says what it did NOT reach -------------------
  try {
    const line = () => page.evaluate(() => {
      const n = document.querySelector('#setSkipPermsNote');
      const own = window.__hintSentences().find((h) => h.text
        === n.textContent.replace(/\s+/g, ' ').trim());
      return { text: n.textContent, warn: n.classList.contains('warn'),
               sentences: own ? own.sentences : -1,
               caveat: document.querySelector('#setSkipPermsCaveat').textContent,
               caveatShown: document.querySelector('#setSkipPermsCaveat').offsetParent !== null };
    });
    let got = await line();
    if (got.warn) note(where, 'the permission line warns with nothing running');
    if (!/next terminal session/.test(got.text)) note(where, `the permission line does not say when it applies: "${got.text}"`);
    if (/stay refused/.test(got.text)) note(where, 'the permission line still claims protected entities "stay refused"');

    await page.evaluate(async () => {
      window.__permSessions = { acting: 1, asking: 0 };
      renderSettingsForm(await api('api/settings'));
    });
    got = await line();
    if (!got.warn || !/still acts without asking/.test(got.text) || !/\/exit/.test(got.text)) {
      note(where, `an open session still acting is not said: "${got.text}"`);
    }
    if (got.sentences > 2) note(where, `the still-acting line runs to ${got.sentences} sentences`);
    if (!/not every shell command/.test(got.caveat) || !got.caveatShown) {
      note(where, 'the shell-command caveat went away when the stale-session warning appeared');
    }

    await page.evaluate(() => {
      window.__permSessions = { acting: 0, asking: 1 };
      window.__refusePut = true;
      document.querySelector('#setsecPermissions').open = true;
    });
    await page.click('#setSkipPerms');
    await page.waitForFunction(() => /still asking/.test(document.querySelector('#toast').textContent),
      null, { timeout: 4000 });
    if (await page.evaluate(() => document.querySelector('#setSkipPerms').checked)) {
      note(where, 'a refused save left the switch showing a value that did not save');
    }
    await page.evaluate(() => { window.__refusePut = false; });
    await page.click('#setSkipPerms');
    await page.waitForFunction(() => /already open still asks/.test(document.querySelector('#toast').textContent),
      null, { timeout: 4000 });
    got = await line();
    if (!/already open still asks/.test(got.text) || !got.warn) note(where, `an open session still asking is not said: "${got.text}"`);
    if (got.sentences > 2) note(where, `the still-asking line runs to ${got.sentences} sentences`);
    const toastText = await page.evaluate(() => document.querySelector('#toast').textContent);
    if (/stay refused/.test(toastText)) note(where, 'the toast still claims protected entities "stay refused"');
    // Advanced keeps the two terminal settings, and its selects say their
    // whole choice once the fold is open.
    await page.click('#setPermsAdvanced > summary');
    const cut = await page.evaluate(() => {
      const ctx = document.createElement('canvas').getContext('2d');
      const out = [];
      document.querySelectorAll('#setModal select').forEach((sel) => {
        if (!sel.clientWidth) return;   // inside a fold nobody has opened
        const cs = getComputedStyle(sel);
        ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        const room = sel.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        const o = sel.options[sel.selectedIndex];
        if (o && ctx.measureText(o.textContent).width > room) out.push(`#${sel.id} "${o.textContent}"`);
      });
      return out;
    });
    cut.filter((x) => !(touch && x.startsWith('#setModel '))).forEach(
      (c) => note(where, `a select cuts its text: ${c}`));
  } catch (e) {
    note(where, `driving the permission switch failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Guide: eight groups, and it opens the docs -------------------------
  try {
    await page.click('#setsecGuide > summary');
    await page.waitForSelector('#setGuide .setguidelink');
    const links = await page.evaluate(() => [...document.querySelectorAll('#setGuide .setguidelink')]
      .map((a) => ({ text: a.firstChild.textContent, h: Math.round(a.getBoundingClientRect().height) })));
    if (links.length !== 8) note(where, `the guide lists ${links.length} groups, not 8`);
    links.forEach((l) => { if (l.h < MIN_TARGET) note(where, `the guide link "${l.text}" is ${l.h}px`); });
    await page.click('#setGuide .setguidelink');
    await page.waitForFunction(() => document.querySelector('#viewDocs').classList.contains('active'),
      null, { timeout: 4000 });
    const docs = await page.evaluate(() => ({
      modal: document.querySelector('#setModal').classList.contains('open'),
      groups: [...document.querySelectorAll('#docsNav .docsgroup')].map((g) => g.textContent),
      titles: [...document.querySelectorAll('#docsNav .docslinktitle')].map((t) => t.textContent),
      body: document.querySelector('#docsBody').textContent,
      icons: (window.BRAIN_DOCS || []).filter((s) => 'icon' in s).length,
    }));
    if (docs.modal) note(where, 'the guide opened behind ⚙');
    if (docs.groups.length !== 8) note(where, `the docs nav has ${docs.groups.length} groups, not 8`);
    const emoji = docs.titles.filter((t) => /\p{Extended_Pictographic}/u.test(t));
    if (emoji.length) note(where, `docs nav rows carry emoji: ${emoji.slice(0, 3).join(', ')}`);
    if (docs.icons) note(where, `${docs.icons} docs sections still carry an icon`);
    if (/already has nerves/.test(docs.body)) note(where, 'the marketing hero line is back in the guide');
    if (!/Back up Home Assistant first/.test(docs.body)) note(where, 'the guide lost the backup box');
  } catch (e) {
    note(where, `driving the guide failed: ${String(e.message).split('\n')[0]}`);
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-settings: FAIL');
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log(`measure-settings: OK across ${WIDTHS.join(', ')}px `
            + `(dialog scroll ${heights.join(', ')})`);
