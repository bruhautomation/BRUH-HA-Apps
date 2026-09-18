// Drive the ⚙ dialog and assert it is a thing somebody can get through.
//
// What this exists to prevent is the shape the dialog had shipped in: one
// flat scroll of a dozen headings with a paragraph of prose under nearly
// every control. Measured on the unmodified dialog, behind this same stub,
// the scrolling body was **5,910px at 390 and 3,837px at 1,200** — so the
// commonest visit (change the model, read the budget, check the login is
// still good) meant scrolling past the corpus capture and the rehearsal to
// reach it, and opening it cost five fetches nobody had asked for, two of
// which start a three-second poll.
//
// So the checks are about the reorganisation rather than about the styling:
//
//   * the body's scroll height at OPEN time is under a budget per width —
//     the number that describes "how long is this dialog".
//   * every section summary clears the touch floor, names itself, and says
//     in a second line what is behind it. A row of bare nouns is five words
//     to guess at, and this is the only thing you are guaranteed to read.
//   * no hint under a control runs past two sentences. The long version is
//     on a ? beside it, which is what the ? is FOR — a tooltip is right for
//     something wanted once, and wrong as the only copy of something wanted
//     every time, so each ? has a data-tip AND an aria-label.
//   * a section remembers being opened — across closing the dialog AND
//     across a reload, because the remembering is the whole reason a
//     disclosure is acceptable here at all.
//   * the Advanced loaders do not run until Advanced is opened. Counted on
//     the stub, because "it is lazy" is a claim about requests and nothing
//     on the screen can show it.
//   * every text control clears the 16px iOS floor at 390, and the page
//     never scrolls sideways.
//   * every element id the old dialog carried is still in the new one —
//     these are what every handler in app.js binds to, and the whole change
//     was supposed to move things rather than remove them.
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

// Before this reorganisation: 5910 at 390, 3837 at 1200. The budgets leave
// room for a font or a hairline to move and not for a section to come back
// flat, which is the regression worth failing on.
const MAX_SCROLL = { 390: 2200, 1200: 1600 };

// Every id the flat dialog carried. Handlers in app.js bind to these by
// name, and several other measure scripts drive them, so losing one is a
// dead control rather than a layout problem — which is exactly the kind of
// thing a move like this loses quietly.
const IDS = [
  'authBody', 'authRecheck', 'authShare', 'authShareNote', 'authShareState',
  'authSignin', 'authSignout', 'authUnshare', 'capBody', 'capMax', 'deepBody',
  'deepLast', 'deepRun', 'diagBody', 'diagCopy', 'diagCurious', 'diagMeasure',
  'diagRefresh', 'probBody', 'probCopyAll', 'probCopySel', 'probWrite',
  'rehearseBody', 'rehearseLast', 'rehearseRun', 'rehearseSweep', 'setBudget',
  'setBudgetVal', 'setCapture', 'setChatSessions', 'setClose', 'setEnabled',
  'setGatherMode', 'setHistoryDays', 'setKeepDays', 'setKeepRuns', 'setModel',
  'setModelCustom', 'setPlan', 'setRefresh', 'setRefreshMode', 'setSyncNote',
  'setTerminalUi', 'setTimeout', 'usageFill', 'usageMark', 'usageText',
];

// The sections, and whether the shipped markup opens them. Account and
// Insights lead because one decides whether the add-on works at all and the
// other is what the dialog is mostly for; the rest are shut.
const SECTIONS = [
  { sec: 'account', name: 'Claude account', open: true },
  { sec: 'insights', name: 'Insights', open: true },
  { sec: 'terminal', name: 'Terminal & chat', open: false },
  { sec: 'defaults', name: 'Generation defaults', open: false },
  { sec: 'advanced', name: 'Advanced', open: false },
];

// The five reads behind Advanced. Any of these before Advanced is opened is
// the lazy load not being lazy.
const ADVANCED_URLS = ['api/diagnostics', 'api/reports', 'api/capture',
                       'api/doctor/deep', 'api/doctor/rehearse'];

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
  if (p.includes('api/settings')) {
    return answer({
      settings: {
        auto_enabled: true, capture: false, terminal_ui: 'chat',
        chat_max_sessions: 3, gather_mode: 'search', refresh_mode: 'changed',
        plan: 'pro', budget_percent: 25, refresh_hours: 12, history_days: 7,
        timeout_minutes: 8, history_keep_runs: 20, history_keep_days: 30,
        model: 'claude-sonnet-4-5', onboarded: true,
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
      generated_at: Math.floor(Date.now() / 1000), version: 'test',
      health: { state: 'ok', reason: '' },
      runs: { total: 12, failures: [] }, checks: { ran: 15, skipped: [] },
    });
  }
  if (p.includes('api/reports')) {
    return answer({ reports: [], dir: '/share/brain/reports', available: true, max: 30 });
  }
  if (p.includes('api/capture')) {
    return answer({ captures: [], enabled: false, max_files: 50, dir: '/data/capture' });
  }
  if (p.includes('api/baselines')) return answer({ running: false, entities: 0 });
  if (p.includes('api/doctor/rehearse')) {
    return answer({ running: false, sweeping: false, last: {}, plan: [] });
  }
  if (p.includes('api/doctor')) return answer({ running: false, last: {}, stages: [] });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
// Reported on the way out even when everything passes: the number this whole
// change is about is how long the dialog is, and a budget nobody can see the
// headroom on is a budget that gets quietly eaten.
const heights = [];

// A hint's own text, with the ? taken out of it: the button's glyph is a
// sentence terminator and its tip is the prose this is asserting is NOT on
// the page, so counting either would be counting the fix as the fault.
// `e.g.`/`i.e.` are abbreviations rather than full stops.
//
// `#usageText` is out, and the exemption is about what it IS rather than
// about it being inconvenient: it is a live reading of the account's usage
// window, stated in sentences because that is how a percentage and the time
// it rolls over read — its length belongs to the payload, and there is no
// "rest of it" to move onto a ?. Everything else here is a paragraph
// explaining a control, which is the thing being capped.
const SENTENCE_PROBE = `
window.__hintSentences = () => {
  const strip = (n) => {
    const c = n.cloneNode(true);
    c.querySelectorAll('[data-tip]').forEach((t) => t.remove());
    return c.textContent.replace(/\\s+/g, ' ').trim();
  };
  return [...document.querySelectorAll(
    '#setModal .hint, #setModal .bigcheck .subtext')]
    .filter((n) => n.id !== 'usageText')
    .map((n) => strip(n))
    .filter((t) => t)
    .map((t) => ({
      text: t,
      sentences: (t.replace(/\\b(e\\.g|i\\.e|etc)\\./gi, '$1')
        .match(/[.!?](\\s|$)/g) || []).length,
    }));
};
`;

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
  await page.addInitScript(SENTENCE_PROBE);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);

  await page.click('#settingsBtn');
  await page.waitForSelector('#setModal.open');
  await page.waitForFunction(() => document.querySelector('#setSyncNote').textContent !== '');

  // ---- how long is the dialog ------------------------------------------
  const m = await page.evaluate(() => {
    const body = document.querySelector('#setModal .edit-body');
    const secs = [...document.querySelectorAll('#setModal .setsec')].map((d) => {
      const sum = d.querySelector('summary');
      const box = sum.getBoundingClientRect();
      return {
        sec: d.dataset.sec,
        open: d.open,
        h: Math.round(box.height),
        right: box.right,
        name: (d.querySelector('.setsecname') || {}).textContent || '',
        sub: (d.querySelector('.setsecsub') || {}).textContent || '',
      };
    });
    const tips = [...document.querySelectorAll('#setModal .btn.icon.tiny')].map((b) => {
      const box = b.getBoundingClientRect();
      return {
        tip: b.getAttribute('data-tip') || '',
        label: b.getAttribute('aria-label') || '',
        inSection: (b.closest('.setsec') || {}).id || '',
        w: Math.round(box.width), h: Math.round(box.height),
      };
    });
    const small = [...document.querySelectorAll(
      '#setModal input, #setModal select, #setModal textarea')]
      .filter((c) => !['checkbox', 'radio', 'range'].includes(c.type))
      .map((c) => ({
        id: c.id || c.type,
        size: Math.round(parseFloat(getComputedStyle(c).fontSize) * 10) / 10,
      }));
    return {
      scrollH: body.scrollHeight,
      bodyRight: body.getBoundingClientRect().right,
      secs, tips, small,
      hints: window.__hintSentences(),
      missing: null,
      docWidth: document.documentElement.scrollWidth,
    };
  });

  heights.push(`${width}px ${m.scrollH}/${MAX_SCROLL[width]}px`);
  if (m.scrollH > MAX_SCROLL[width]) {
    note(where, `the dialog is ${m.scrollH}px of scroll at open, `
                + `over the ${MAX_SCROLL[width]}px budget`);
  }

  // ---- the sections ------------------------------------------------------
  if (m.secs.length !== SECTIONS.length) {
    note(where, `${m.secs.length} sections, expected ${SECTIONS.length}`);
  }
  for (const want of SECTIONS) {
    const got = m.secs.find((s) => s.sec === want.sec);
    if (!got) { note(where, `no "${want.sec}" section`); continue; }
    if (got.h < MIN_TARGET) {
      note(where, `the ${want.sec} summary is ${got.h}px, under ${MIN_TARGET}`);
    }
    if (got.name.trim() !== want.name) {
      note(where, `the ${want.sec} summary is named "${got.name.trim()}"`);
    }
    if (got.sub.trim().length < 20) {
      note(where, `the ${want.sec} summary says nothing about what is in it`);
    }
    if (got.open !== want.open) {
      note(where, `${want.sec} opens ${got.open} and should open ${want.open}`);
    }
    if (got.right > m.bodyRight + 0.5) note(where, `${want.sec} overflows the dialog`);
  }

  // ---- the prose ---------------------------------------------------------
  for (const h of m.hints) {
    if (h.sentences > 2) {
      note(where, `a hint runs to ${h.sentences} sentences: "${h.text.slice(0, 70)}…"`);
    }
  }
  if (!m.tips.length) note(where, 'no ? buttons — the long prose went nowhere');
  for (const t of m.tips) {
    if (!t.tip.trim()) note(where, `a ? in ${t.inSection} carries no data-tip`);
    if (!t.label.trim()) note(where, `a ? in ${t.inSection} carries no aria-label`);
    if (touch && (t.w < MIN_TARGET || t.h < MIN_TARGET)) {
      note(where, `a ? in ${t.inSection} is ${t.w}×${t.h}, under ${MIN_TARGET}`);
    }
  }

  // ---- the iOS floor, and the page's own width ---------------------------
  if (touch) {
    for (const c of m.small) {
      if (c.size < MIN_TEXT) {
        note(where, `#${c.id} renders at ${c.size}px, under the ${MIN_TEXT}px floor`);
      }
    }
  }
  if (m.docWidth > width) note(where, `page scrolls sideways (${m.docWidth}px)`);

  // ---- every id survived the move ---------------------------------------
  const missing = await page.evaluate(
    (ids) => ids.filter((id) => !document.getElementById(id)), IDS);
  if (missing.length) note(where, `ids lost in the move: ${missing.join(', ')}`);

  // ---- Advanced is lazy --------------------------------------------------
  try {
    const early = await page.evaluate(
      (urls) => window.__fetched.filter((u) => urls.some((x) => u.includes(x))), ADVANCED_URLS);
    if (early.length) {
      note(where, `opening ⚙ fetched ${early.length} Advanced read(s) `
                  + `before Advanced was opened: ${[...new Set(early)].join(', ')}`);
    }
    await page.click('#setsecAdvanced > summary');
    await page.waitForFunction(
      () => window.__fetched.some((u) => u.includes('api/diagnostics')), null,
      { timeout: 4000 });
    await page.waitForSelector('#probBody');
    const late = await page.evaluate(
      (urls) => urls.filter(
        (x) => !window.__fetched.some((u) => u.includes(x))), ADVANCED_URLS);
    if (late.length) {
      note(where, `opening Advanced never fetched: ${late.join(', ')}`);
    }
  } catch (e) {
    note(where, `driving Advanced failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- a section remembers ------------------------------------------------
  // Two different claims: it survives closing the dialog (the DOM is not torn
  // down, so this is cheap) and it survives a reload (which is the one the
  // pref is for). Both directions, because a store that only ever writes "1"
  // would pass a one-sided test while a section you deliberately shut came
  // back open every visit.
  try {
    await page.click('#setsecTerminal > summary');   // shut → open
    await page.click('#setsecInsights > summary');   // open → shut
    await page.click('#setClose');
    await page.click('#settingsBtn');
    let st = await page.evaluate(() => ({
      terminal: document.querySelector('#setsecTerminal').open,
      insights: document.querySelector('#setsecInsights').open,
    }));
    if (!st.terminal || st.insights) {
      note(where, `reopening the dialog forgot the sections `
                  + `(terminal ${st.terminal}, insights ${st.insights})`);
    }
    await page.reload();
    await page.waitForSelector('#settingsBtn');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    st = await page.evaluate(() => ({
      terminal: document.querySelector('#setsecTerminal').open,
      insights: document.querySelector('#setsecInsights').open,
      advanced: document.querySelector('#setsecAdvanced').open,
    }));
    if (!st.terminal) note(where, 'a section opened by hand was shut again after a reload');
    if (st.insights) note(where, 'a section shut by hand was open again after a reload');
    if (!st.advanced) note(where, 'Advanced was shut again after a reload');
    // …and a remembered-open Advanced still fetches, because "the section is
    // open" and "its rows are current" are different claims — and the polls
    // behind it are stopped when the dialog closes.
    const refetched = await page.evaluate(
      () => window.__fetched.filter((u) => u.includes('api/diagnostics')).length);
    if (!refetched) note(where, 'a remembered-open Advanced fetched nothing on reopen');
  } catch (e) {
    note(where, `driving the disclosures failed: ${String(e.message).split('\n')[0]}`);
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
