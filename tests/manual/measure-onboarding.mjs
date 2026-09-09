// Drive the first-run flow end to end and assert every step can be read,
// pressed and — this is the one that matters — RESUMED.
//
// The flow is the only screen in the panel somebody sees exactly once, which
// is precisely why it goes wrong quietly: nobody who has already been through
// it will ever see the version that is broken. Four steps now, because 1.48
// puts a question in front of the syllabus — where brAIn may reach you —
// and a first-run flow that cannot be got past over a notify service is
// worse than one with no notify service at all.
//
// So the checks are, at every width:
//
//   * step 0 renders one press per notify service plus a "no thanks", the
//     two hour pickers can say "not set" as well as an hour, and the brief
//     is ticked by default whenever a service is picked
//   * both empty cases say WHICH empty they are — "Home Assistant did not
//     answer" is something to try again and "this house has no notify
//     service" is a fact about the house — and both offer a way past
//   * saving shows the lines to paste, readably, on screen. `writable:
//     false` is the whole reason that screen exists: brAIn is using these
//     settings and the add-on's Configuration tab will not show them
//   * the flow RESUMES: reopened with the step already answered it lands on
//     the syllabus, and reopened with it unanswered it lands on step 0. A
//     step that cannot be resumed is a step somebody answers twice or skips
//     without knowing they did
//   * the choose step renders the custom cards and the shipped ones as two
//     labelled groups, ticked independently, and says what Finish leaves
//     behind BEFORE Finish — sending no shipped ids means none of them,
//     which on a fresh install is an empty Insights tab by design
//   * nothing scrolls sideways, and no press target is under 44px on touch
//
// Like measure-knowledge.mjs and measure-activity.mjs, this drives the
// panel's REAL renderers behind a stubbed fetch. A copy of renderOnboarding
// in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 768, 1200];
const MIN_TARGET = 44;

// Two phones and a speaker, which is the shape that matters: only a
// `mobile_app_*` service can carry the answer buttons a finding
// notification puts on a message, and the step has to say which is which.
const CANDIDATES = [
  { service: 'notify.mobile_app_pixel', label: 'pixel', phone: true, buttons: true },
  { service: 'notify.mobile_app_ipad', label: 'ipad', phone: true, buttons: true },
  { service: 'notify.kitchen_speaker', label: 'kitchen speaker', phone: false, buttons: false },
];

const RECOMMENDATIONS = [
  { title: 'The garage freezer', icon: '🧊',
    focus: 'Watch the chest freezer in the garage — it is the only appliance '
      + 'here whose failure costs money quietly.',
    why: 'You have a temperature sensor on it and nothing reads it.' },
  { title: 'Morning heating', icon: '🌡️',
    focus: 'How long the bedroom takes to warm up against when the house gets up.',
    why: 'Three thermostats and a measured wake time.' },
];

const SHIPPED = [
  { id: 'energy', title: 'Energy', icon: '⚡',
    description: 'What the house used, and what moved.',
    why: 'Your energy dashboard names a grid meter.' },
  { id: 'security', title: 'Security', icon: '🔒',
    description: 'Doors, windows and locks.',
    why: 'Six door sensors and two locks.' },
];

// `notifyState` is what GET /api/onboarding/notify answers with; the three
// cases are the three this screen has to tell apart.
const NOTIFY_CASES = {
  normal: { candidates: CANDIDATES, error: '', writable: false,
            findings_notify_service: null, notify_quiet_start: null,
            notify_quiet_end: null, morning_brief: null, asked: false,
            manual: [] },
  unreachable: { candidates: [], error: 'Home Assistant did not answer',
                 writable: false, findings_notify_service: null,
                 notify_quiet_start: null, notify_quiet_end: null,
                 morning_brief: null, asked: false, manual: [] },
  none: { candidates: [], error: '', writable: false,
          findings_notify_service: null, notify_quiet_start: null,
          notify_quiet_end: null, morning_brief: null, asked: false,
          manual: [] },
};

const stub = (notifyCase, asked) => `
window.__posted = [];
window.__ob = {
  onboarded: false,
  phase: 'learning',
  learning: { topics: ['How this home is named', 'When it is occupied',
                       'What it uses', 'How it behaves', 'What breaks'],
              done: [], complete: false, memory_ready: false },
  notify: { findings_notify_service: null, notify_quiet_start: null,
            notify_quiet_end: null, morning_brief: null,
            asked: ${asked ? 'true' : 'false'}, manual: [] },
  recommendations: [], shipped: [], sparse: false, missing: '',
};
window.__notify = ${JSON.stringify(NOTIFY_CASES[notifyCase])};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const post = !!(opts && String(opts.method || '').toUpperCase() === 'POST');
  const body = post && opts.body ? JSON.parse(opts.body) : null;
  const answer = (b, s) => new Response(JSON.stringify(b), {
    status: s || 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/onboarding/notify')) {
    if (!post) return answer(window.__notify);
    window.__posted.push(['notify', body]);
    const fields = {
      findings_notify_service: body.service || null,
      notify_quiet_start: body.quiet_start,
      notify_quiet_end: body.quiet_end,
      morning_brief: !!body.brief,
    };
    const manual = [];
    if (fields.findings_notify_service) {
      manual.push('findings_notify_service: "' + fields.findings_notify_service + '"');
    }
    if (fields.notify_quiet_start) {
      manual.push('notify_quiet_start: "' + fields.notify_quiet_start + '"');
    }
    if (fields.notify_quiet_end) {
      manual.push('notify_quiet_end: "' + fields.notify_quiet_end + '"');
    }
    if (fields.morning_brief) manual.push('morning_brief: true');
    // The server records that the step was asked, which is what makes the
    // flow resumable — so the stub does too.
    window.__ob.notify = { ...fields, asked: true, manual };
    return answer({ ...fields, manual });
  }
  if (p.includes('api/onboarding/learn')) {
    window.__posted.push(['learn', body]);
    // The syllabus is queued AND one card starts generating: for the whole
    // half hour the Insights tab used to say nothing at all.
    window.__ob.learning = { ...window.__ob.learning,
                             done: window.__ob.learning.topics.slice(),
                             complete: true, memory_ready: true };
    return answer({ queued: window.__ob.learning.topics.slice(),
                    first_card: 'overview' });
  }
  if (p.includes('api/onboarding/recommend')) {
    window.__posted.push(['recommend', body]);
    const out = { recommendations: ${JSON.stringify(RECOMMENDATIONS)},
                  shipped: ${JSON.stringify(SHIPPED)},
                  sparse: false, missing: '' };
    Object.assign(window.__ob, out, { phase: 'choosing' });
    return answer(out);
  }
  if (p.includes('api/onboarding/accept')) {
    window.__posted.push(['accept', body]);
    window.__ob.onboarded = true;
    return answer({ created: [], onboarded: true, shipped: body.shipped || [] });
  }
  if (p.includes('api/onboarding/skip')) {
    window.__posted.push(['skip', body]);
    window.__ob.onboarded = true;
    return answer({ onboarded: true });
  }
  if (p.includes('api/onboarding')) return answer(window.__ob);
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0, today: {},
    });
  }
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  if (p.includes('api/knowledge/cards')) {
    return answer({ cards: [], pending: [], running: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

async function open(width, notifyCase, asked) {
  // The narrow widths are driven AS touch devices: the 44px floor lives in
  // a `pointer: coarse` block, and a context with a fine pointer would
  // measure the desktop density and call it a pass.
  const touch = width <= 768;
  const context = await browser.newContext({
    viewport: { width, height: 1000 },
    ...(touch ? { hasTouch: true, isMobile: true } : {}),
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(notifyCase, !!asked));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.waitForSelector('#onboard:not(.hidden)', { timeout: 5000 })
    .catch(() => note(`${width}px`, 'the first-run flow never appeared'));
  return { context, page, touch };
}

// Which step is on screen. Exactly one of them may be, or the flow is a
// screen somebody is looking at with no idea what it wants from them.
const readStep = (page) => page.evaluate(() => {
  const ids = ['obNotify', 'obManual', 'obLearn', 'obRecommend', 'obChoose',
               'obSparse'];
  const shown = ids.filter((id) => {
    const n = document.getElementById(id);
    return n && !n.classList.contains('hidden')
      && n.getBoundingClientRect().height > 0;
  });
  return { shown, docWidth: document.documentElement.scrollWidth };
});

// Every press target on the flow: buttons, selects, and the card-shaped
// labels that hold the radios and tick boxes. Deliberately not the bare
// <input>s — the label IS the target, which is why they are labels.
const readTargets = (page) => page.evaluate(() => {
  const nodes = [...document.querySelectorAll(
    '#onboard button, #onboard select, #onboard .obcard')];
  return nodes.filter((n) => {
    const cs = getComputedStyle(n);
    const r = n.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.height > 0;
  }).map((n) => ({
    what: (n.textContent || n.id || n.tagName).trim().slice(0, 40),
    h: Math.round(n.getBoundingClientRect().height),
    w: Math.round(n.getBoundingClientRect().width),
  }));
});

async function checkTargets(page, at, touch) {
  if (!touch) return;
  const targets = await readTargets(page);
  targets.forEach((t) => {
    if (t.h < MIN_TARGET) {
      note(at, `"${t.what}" is ${t.h}px tall, under ${MIN_TARGET}`);
    }
  });
}

// ------------------------------------------------- the walk, at each width
for (const width of WIDTHS) {
  const { context, page, touch } = await open(width, 'normal', false);
  const at = `${width}px`;

  // ---- step 0
  let step = await readStep(page);
  if (step.shown.join(',') !== 'obNotify') {
    note(at, `a fresh flow opens on [${step.shown.join(', ')}], not step 0`);
  }
  if (step.docWidth > width + 0.5) {
    note(at, `step 0 scrolls sideways (${step.docWidth}px)`);
  }

  const notify = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#obNotifyList .obcard')];
    const start = document.getElementById('obQuietStart');
    const end = document.getElementById('obQuietEnd');
    return {
      rows: rows.map((r) => ({
        value: (r.querySelector('input') || {}).value,
        text: r.textContent.replace(/\s+/g, ' ').trim(),
        checked: !!(r.querySelector('input') || {}).checked,
      })),
      startOpts: start ? start.options.length : 0,
      endOpts: end ? end.options.length : 0,
      startFirst: start && start.options.length ? start.options[0].value : null,
      startValue: start ? start.value : null,
      brief: (document.getElementById('obBrief') || {}).checked,
      err: (document.getElementById('obNotifyErr') || {}).textContent || '',
      errShown: !document.getElementById('obNotifyErr').classList.contains('hidden'),
      optsShown: !document.getElementById('obNotifyOpts').classList.contains('hidden'),
    };
  });

  // One row per service, plus "no thanks" — which is an answer, not the
  // absence of one, and is what stops the step being asked again.
  if (notify.rows.length !== CANDIDATES.length + 1) {
    note(at, `${notify.rows.length} notify choices for ${CANDIDATES.length} services`);
  }
  const noThanks = notify.rows[notify.rows.length - 1];
  if (!noThanks || noThanks.value !== '' || !/No thanks/i.test(noThanks.text)) {
    note(at, 'there is no "no thanks" option on step 0');
  }
  if (!noThanks || !noThanks.checked) {
    note(at, 'nothing is selected on step 0 by default');
  }
  // A phone is the one that can carry answer buttons, and the step has to
  // say so — that is the difference between reading about a problem and
  // settling it from the notification.
  const phoneRow = notify.rows.find((r) => r.value === CANDIDATES[0].service);
  if (!phoneRow || !/answer buttons/i.test(phoneRow.text)) {
    note(at, 'a mobile_app service is not marked as carrying answer buttons');
  }
  const speakerRow = notify.rows.find((r) => r.value === CANDIDATES[2].service);
  if (speakerRow && /can carry answer buttons/i.test(speakerRow.text)) {
    note(at, 'a non-phone service claims it can carry answer buttons');
  }
  // 24 hours plus "not set". A picker that cannot say the second turns "no
  // quiet hours" into a silence from midnight.
  if (notify.startOpts !== 25 || notify.endOpts !== 25) {
    note(at, `hour pickers have ${notify.startOpts}/${notify.endOpts} options, not 25`);
  }
  if (notify.startFirst !== '' || notify.startValue !== '') {
    note(at, 'the hour picker cannot say "not set"');
  }
  if (notify.errShown) note(at, `an error is shown with services present: "${notify.err}"`);
  if (!notify.optsShown) note(at, 'the quiet hours are hidden with services present');
  await checkTargets(page, `${at}/step0`, touch);

  // Pick a phone, set quiet hours, and save. The brief defaults ON whenever
  // a service is picked, because that is the point of having asked.
  await page.click(`#obNotifyList .obcard:has(input[value="${CANDIDATES[0].service}"])`);
  await page.selectOption('#obQuietStart', '22');
  await page.selectOption('#obQuietEnd', '7');
  const briefAfterPick = await page.evaluate(() =>
    document.getElementById('obBrief').checked);
  if (!briefAfterPick) {
    note(at, 'the morning brief is not ticked by default with a service picked');
  }
  await page.click('#obNotifySave');
  await page.waitForSelector('#obManual:not(.hidden)', { timeout: 5000 })
    .catch(() => note(at, 'saving step 0 never showed the lines to paste'));

  const sent = await page.evaluate(() =>
    (window.__posted.find((r) => r[0] === 'notify') || [])[1]);
  if (!sent || sent.service !== CANDIDATES[0].service) {
    note(at, `step 0 sent ${JSON.stringify(sent)}`);
  } else {
    if (sent.quiet_start !== '22' || sent.quiet_end !== '7') {
      note(at, `the quiet hours went as ${sent.quiet_start}/${sent.quiet_end}`);
    }
    if (sent.brief !== true) note(at, 'the brief tick did not reach the server');
  }

  // `writable: false` is load-bearing: the panel cannot write these into
  // the add-on's options, so the lines have to be READABLE on screen, not
  // just available behind a Copy button that an ingress iframe may refuse.
  const manual = await page.evaluate(() => {
    const box = document.getElementById('obManualText');
    if (!box) return null;
    const cs = getComputedStyle(box);
    const r = box.getBoundingClientRect();
    return {
      text: box.textContent,
      lines: box.textContent.split('\n').filter((l) => l.trim()).length,
      visible: cs.display !== 'none' && cs.visibility !== 'hidden'
        && r.height > 0 && r.width > 0,
      selectable: cs.userSelect !== 'none',
      clipped: box.scrollHeight > box.clientHeight + 2,
      panel: document.getElementById('obManual').textContent,
      docWidth: document.documentElement.scrollWidth,
    };
  });
  if (!manual || !manual.visible) {
    note(at, 'the lines to paste are not on screen');
  } else {
    if (manual.lines !== 4) {
      note(at, `${manual.lines} lines to paste, expected 4: "${manual.text}"`);
    }
    if (!/findings_notify_service/.test(manual.text)) {
      note(at, 'the manual block does not name the notify option');
    }
    if (!/morning_brief: true/.test(manual.text)) {
      note(at, 'the manual block drops the morning brief');
    }
    if (!manual.selectable) note(at, 'the lines to paste cannot be selected');
    if (manual.clipped) note(at, 'the lines to paste are clipped');
    // The sentence is the half that says why this screen exists at all.
    if (!/brAIn is using these now/.test(manual.panel)) {
      note(at, 'the manual block does not say brAIn is already using them');
    }
    if (!/Configuration tab/.test(manual.panel)) {
      note(at, 'the manual block does not name where to paste them');
    }
    if (manual.docWidth > width + 0.5) {
      note(at, `the manual block scrolls sideways (${manual.docWidth}px)`);
    }
  }
  await checkTargets(page, `${at}/manual`, touch);

  // ---- step 1: the syllabus
  await page.click('#obManualNext');
  step = await readStep(page);
  if (step.shown.join(',') !== 'obLearn') {
    note(at, `after step 0 the flow shows [${step.shown.join(', ')}]`);
  }
  const topics = await page.evaluate(() =>
    document.querySelectorAll('#obTopics .obstep').length);
  if (topics !== 5) note(at, `${topics} syllabus topics, expected 5`);
  await checkTargets(page, `${at}/learn`, touch);

  await page.click('#obStart');
  await page.waitForTimeout(250);
  // One card is already generating, so the tab is not empty for half an
  // hour with nothing saying why.
  const toastText = await page.evaluate(() =>
    (document.getElementById('toast') || {}).textContent || '');
  if (!/first card/i.test(toastText)) {
    note(at, `starting the syllabus said "${toastText}" — nothing about the first card`);
  }

  // ---- step 2: recommend
  step = await readStep(page);
  if (step.shown.join(',') !== 'obRecommend') {
    note(at, `after starting the syllabus the flow shows [${step.shown.join(', ')}]`);
  }
  await page.click('#obGo');
  await page.waitForSelector('#obChoose:not(.hidden)', { timeout: 5000 })
    .catch(() => note(at, 'the recommend step never reached the choices'));

  // ---- step 3: choose, two groups
  const choose = await page.evaluate(() => {
    const heads = [...document.querySelectorAll('#obChoose .obh3')]
      .filter((h) => !h.classList.contains('hidden'))
      .map((h) => h.textContent.trim());
    const custom = [...document.querySelectorAll('#obList .obcard')];
    const shipped = [...document.querySelectorAll('#obShipped .obcard')];
    return {
      heads,
      custom: custom.length,
      shipped: shipped.length,
      shippedBlock: !document.getElementById('obShippedBlock')
        .classList.contains('hidden'),
      shippedIds: shipped.map((r) => (r.querySelector('input') || {}).dataset.shipped),
      allTicked: [...document.querySelectorAll('#obChoose input:checked')].length,
      note: (document.getElementById('obChooseNote') || {}).textContent || '',
      shippedText: shipped.map((r) => r.textContent.replace(/\s+/g, ' ').trim()),
      docWidth: document.documentElement.scrollWidth,
    };
  });
  if (choose.custom !== RECOMMENDATIONS.length) {
    note(at, `${choose.custom} custom cards for ${RECOMMENDATIONS.length}`);
  }
  if (!choose.shippedBlock || choose.shipped !== SHIPPED.length) {
    note(at, `${choose.shipped} shipped cards for ${SHIPPED.length}`);
  }
  // Two groups, each named. One list holding both is one list somebody
  // ticks without noticing half of it means something different.
  if (choose.heads.length !== 2) {
    note(at, `the choose step has ${choose.heads.length} group headings`);
  }
  if (!choose.heads.some((h) => /ship with brAIn/i.test(h))) {
    note(at, `the shipped group is labelled [${choose.heads.join(' | ')}]`);
  }
  if (!choose.shippedText.some((t) => /grid meter/.test(t))) {
    note(at, 'a shipped card does not say why it fits this house');
  }
  if (choose.allTicked !== RECOMMENDATIONS.length + SHIPPED.length) {
    note(at, `${choose.allTicked} boxes ticked out of `
      + `${RECOMMENDATIONS.length + SHIPPED.length}`);
  }
  if (choose.docWidth > width + 0.5) {
    note(at, `the choose step scrolls sideways (${choose.docWidth}px)`);
  }
  await checkTargets(page, `${at}/choose`, touch);

  // Untick everything: sending no shipped ids means NONE, and on a fresh
  // install that is an empty Insights tab. A real choice, and a terrible
  // thing to discover afterwards — so the step says it before Finish.
  await page.evaluate(() => {
    document.querySelectorAll('#obChoose input:checked').forEach((cb) => {
      cb.checked = false;
      cb.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  const emptyNote = await page.evaluate(() =>
    document.getElementById('obChooseNote').textContent);
  if (!/empty/i.test(emptyNote)) {
    note(at, `with nothing ticked the step says "${emptyNote}"`);
  }

  // And the shipped half is ticked INDEPENDENTLY: one shipped card back on,
  // no custom ones, and the accept has to carry exactly that.
  await page.evaluate((id) => {
    const cb = document.querySelector(`#obShipped input[data-shipped="${id}"]`);
    cb.checked = true;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  }, SHIPPED[0].id);
  await page.click('#obAccept');
  await page.waitForTimeout(250);
  const accepted = await page.evaluate(() =>
    (window.__posted.find((r) => r[0] === 'accept') || [])[1]);
  if (!accepted) {
    note(at, 'Finish sent nothing');
  } else {
    if ((accepted.accept || []).length !== 0) {
      note(at, `Finish sent custom ${JSON.stringify(accepted.accept)}`);
    }
    if (!Array.isArray(accepted.shipped)
        || accepted.shipped.join(',') !== SHIPPED[0].id) {
      note(at, `Finish sent shipped ${JSON.stringify(accepted.shipped)}`);
    }
  }

  console.log(`${failures.length ? 'ok? ' : 'ok  '}${String(width).padStart(4)}px  `
    + `step 0 → syllabus → recommend → choose (2 groups)`);
  await context.close();
}

// ------------------------------------------------------------ resuming it
// The step has to survive the browser being closed on it: `onboarding
// .state()` carries whether it was asked, and a flow that ignored that
// would ask a second time or, worse, skip the one question the rest of it
// assumes an answer to.
for (const [asked, expected] of [[false, 'obNotify'], [true, 'obLearn']]) {
  const { context, page } = await open(768, 'normal', asked);
  const step = await readStep(page);
  if (step.shown.join(',') !== expected) {
    note(`resume/asked=${asked}`,
      `reopened on [${step.shown.join(', ')}], expected ${expected}`);
  }
  console.log(`${failures.length ? 'ok? ' : 'ok  '}resume  asked=${String(asked).padEnd(5)} `
    + `lands on ${step.shown.join(', ') || 'nothing'}`);
  await context.close();
}

// ------------------------------------------------------------ the empties
// Two different empties, and only one of them is something to try again.
// Reporting either as the other sends somebody off to fix the wrong thing —
// and both have to be skippable, because a first-run flow nobody can get
// past over a notify service is the worst outcome on this screen.
for (const [name, expect] of [
  ['unreachable', /did not answer/],
  ['none', /no notify service/i],
]) {
  const { context, page, touch } = await open(390, name, false);
  const m = await page.evaluate(() => ({
    step: !document.getElementById('obNotify').classList.contains('hidden'),
    err: (document.getElementById('obNotifyErr') || {}).textContent || '',
    errShown: !document.getElementById('obNotifyErr').classList.contains('hidden'),
    rows: document.querySelectorAll('#obNotifyList .obcard').length,
    optsShown: !document.getElementById('obNotifyOpts').classList.contains('hidden'),
    skip: (() => {
      const b = document.getElementById('obNotifySkip');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      return { text: b.textContent.trim(), h: Math.round(r.height),
               shown: r.height > 0 };
    })(),
    docWidth: document.documentElement.scrollWidth,
  }));
  const at = `empty/${name}`;
  if (!m.step) note(at, 'step 0 is not on screen at all');
  if (!m.errShown || !expect.test(m.err)) {
    note(at, `the empty case says "${m.err}"`);
  }
  // "No thanks" is still there, because saying no is still an answer.
  if (m.rows !== 1) note(at, `${m.rows} choices with no services`);
  // The quiet hours and the brief decide nothing with no service to pick.
  if (m.optsShown) note(at, 'the quiet hours are offered with no service to pick');
  if (!m.skip || !m.skip.shown) note(at, 'there is no way past this step');
  if (m.skip && touch && m.skip.h < MIN_TARGET) {
    note(at, `Skip is ${m.skip.h}px, under ${MIN_TARGET}`);
  }
  if (m.docWidth > 390.5) note(at, `it scrolls sideways (${m.docWidth}px)`);

  // Skipping is an answer too: it records that the step was asked, so a
  // flow resumed tomorrow does not open on a question already declined.
  await page.click('#obNotifySkip');
  await page.waitForTimeout(200);
  const after = await readStep(page);
  if (after.shown.join(',') !== 'obLearn') {
    note(at, `skipping landed on [${after.shown.join(', ')}]`);
  }
  const posted = await page.evaluate(() =>
    window.__posted.filter((r) => r[0] === 'notify').length);
  if (!posted) note(at, 'skipping recorded nothing, so the step asks again');

  console.log(`${failures.length ? 'ok? ' : 'ok  '}empty   ${name.padEnd(12)} `
    + `says why, and skips past`);
  await context.close();
}

await browser.close();
for (const f of failures) console.log(`  - ${f}`);
console.log(failures.length ? `\n${failures.length} problem(s)` : '\nall widths ok');
process.exit(failures.length ? 1 : 0);
