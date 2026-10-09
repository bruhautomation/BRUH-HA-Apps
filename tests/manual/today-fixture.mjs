// One house, in the server's own shapes, for every measure that drives
// Today: the cases (`_cases_payload`), the findings under them, the
// suggestions (`/api/proposals`), To Do (`/api/todo`), the two cards no
// store owns (`/api/today`), History (`/api/history`) and the status line
// (`/api/status`). Kept in one file so the measures of the card, the list,
// the suggestions, the plan and the queue read the same house — a fixture
// per measure is how two of them came to disagree about what a case looks
// like.
//
// `stub(over)` returns the init script a page runs before `app.js`: it
// replaces `fetch` with these payloads and records every press it is sent
// in `window.__posts`, so a measure can assert what a button asked for.
export const NOW = Math.floor(Date.now() / 1000);

export const A = (verb, label, route, over = {}) => ({
  verb, label, route, method: 'POST', request: null, primary: false,
  note: false, prefill: '', done: label, hint: `${label} — hint`, ...over,
});

export const kase = (over) => ({
  id: '', kind: 'problem', claim: '', detail: '', confidence: null,
  stakes: 'medium', evidence: [], actions: [], status: 'open', source: '',
  source_title: '', ts: NOW, origin: { store: 'findings', key: NOW },
  memory_hint: '', investigation: null, ended: null, severity: 'warning',
  entity_id: '', entity_name: '', area: '', fix: '', fix_by: '',
  fixable: false, finding_status: 'open', plan: {}, triage: {},
  snoozed_until: 0, overflow: [], answers: [], more: [], situation: '',
  chip: 'problem', urgent: false, mutable: true,
  ...over,
});

const ask = (key) => ({ verb: 'discuss', label: 'Ask', route: `/api/finding/${key}/discuss`,
  method: 'POST', hint: 'Talk it through with brAIn.' });
const recheck = (key) => ({ verb: 'recheck', label: 'Check again',
  route: `/api/finding/${key}/recheck`, method: 'POST', hint: 'Look again.' });
const done = (key) => ({ verb: 'done', label: 'Done', route: `/api/finding/${key}/done`,
  method: 'POST', hint: "It's handled." });
// A problem's row (`answers._problem_row`): the primary, Check again on a
// check's row, Dismiss, then Snooze · Ignore.
const trio = (id, lead, check = false) => [lead,
  ...(check ? [recheck(id.slice(2))] : []),
  A('dismiss', 'Dismiss', `/api/finding/${id.slice(2)}`, { method: 'DELETE' }),
  A('not_now', 'Snooze', `/api/case/${id}/not_now`, { request: 'snooze' }),
  A('wrong', 'Ignore', `/api/case/${id}/wrong`, { note: true, request: 'wrong' })];

export const FEED = [
  kase({
    id: 'f:1100', severity: 'critical', stakes: 'high', chip: 'urgent', urgent: true,
    situation: 'hands', claim: 'binary_sensor.kitchen_leak is reporting water',
    detail: 'Wet since 07:12, under the sink.', entity_id: 'binary_sensor.kitchen_leak',
    entity_name: 'Kitchen Leak', area: 'Kitchen', source: 'safety',
    source_title: 'Safety', mutable: false, fix: 'Turn off the water at the stopcock.',
    origin: { store: 'findings', key: 1100 },
    answers: trio('f:1100', A('todo', 'Add to To Do', '/api/case/f:1100/do',
      { primary: true, request: 'todo' })),
    more: [ask(1100), done(1100)],
  }),
  kase({
    id: 'f:1101', severity: 'serious', stakes: 'high', confidence: 0.86,
    situation: 'generic', fixable: true,
    claim: 'sensor.garage_freezer has been six degrees warmer for a week',
    detail: 'Its own month of statistics drifts upward and no other freezer '
      + 'in the house does. The kitchen freezer, on the same circuit, has '
      + 'held its temperature to within half a degree over the same month, '
      + 'so this is not the supply and not the room: it is this one '
      + 'appliance, and the drift began on the ninth.',
    entity_id: 'sensor.garage_freezer', entity_name: 'Garage Freezer', area: 'Garage',
    fix: 'Check the door seal on sensor.garage_freezer, then the compressor relay.',
    source: 'check:base.trend', source_title: 'Drift check',
    origin: { store: 'findings', key: 1101 },
    triage: { verdict: 'elevated', reason: 'A real drift.', run_id: 'look-1', at: NOW - 600 },
    evidence: [{ entity: 'sensor.garage_freezer', value: '-12.4 °C', when: '15 Sep 08:10' }],
    answers: trio('f:1101', A('fix', 'Fix', '/api/finding/1101/fix', { primary: true, instruct: true,
      prefill: 'Check the door seal on sensor.garage_freezer, then the compressor relay.', ask: 'What should brAIn change? Edit its suggestion or write your own.' }), true),
    more: [ask(1101), done(1101)],
  }),
  kase({
    id: 'f:1102', situation: 'planned', finding_status: 'planned', fixable: true,
    claim: 'The hall automation points at a sensor that no longer exists',
    fix: 'Point it at the new sensor.',
    plan: { can_fix: true, needs_you: false, summary: 'Edit automations.yaml.',
            steps: ['Replace binary_sensor.hall_old with binary_sensor.hall.'],
            ops: [{ op: 'edit_automation' }], risk: 'The hall light will not '
              + 'come on until the new sensor first reports.' },
    source: 'check:auto.dead_ref', source_title: 'Automation check',
    origin: { store: 'findings', key: 1102 },
    answers: trio('f:1102', A('apply', 'Apply', '/api/finding/1102/apply', { primary: true }), true),
    more: [ask(1102)],
  }),
  kase({
    id: 'h:1103', kind: 'question', chip: 'question', situation: 'question',
    severity: 'info', claim: 'The garage fridge is meant to run 24/7',
    source: 'hypothesis', source_title: 'energy', mutable: false,
    origin: { store: 'hypotheses', key: 1103 },
    answers: [
      A('yes', 'Yes', '/api/case/h:1103/do', { primary: true }),
      A('no', 'No', '/api/case/h:1103/wrong', { note: true }),
      A('not_now', 'Snooze', '/api/case/h:1103/not_now', { request: 'snooze' }),
    ],
  }),
  kase({
    id: 'f:1104', kind: 'change', situation: 'change', finding_status: 'fixed',
    claim: 'brAIn pointed the porch automation at the new sensor',
    result: 'Replaced binary_sensor.porch_old and reloaded the automations.',
    source: 'check:auto.dead_ref', source_title: 'Automation check',
    origin: { store: 'findings', key: 1104 }, ended: { when: NOW - 3600 },
    fix_started: NOW - 3700, fix_ended: NOW - 3650, fix_files: 1, fix_calls: 0,
    answers: [A('ack', 'Done', '/api/case/f:1104/do', { primary: true, request: 'ack' }),
              A('unfix', 'Undo', '/api/finding/1104/unfix')],
    more: [ask(1104)],
  }),
  kase({
    id: 'f:1105', situation: 'hands', finding_status: 'planned',
    claim: 'An automation condition never passes',
    plan: { can_fix: false, needs_you: false, steps: [], ops: [], at: NOW - 600,
            summary: 'The condition is doing what it was written to do.' },
    source: 'check:auto.condition_never_passes', source_title: 'Automation check',
    origin: { store: 'findings', key: 1105 },
    answers: trio('f:1105', A('todo', 'Add to To Do', '/api/case/f:1105/do',
      { primary: true, request: 'todo' }), true),
    more: [ask(1105)],
  }),
  kase({
    id: 'f:1106', situation: 'planned', finding_status: 'planned', fixable: true,
    claim: 'The bedroom lamp is in no room',
    plan: { can_fix: true, ops: [], steps: ['Old step'], summary: 'Old summary',
            ops_refused: 'this plan was written before brAIn checked each change '
              + 'as an operation it can carry out, so there is nothing to approve' },
    source: 'check:reg.no_area', source_title: 'Registry check',
    origin: { store: 'findings', key: 1106 },
    answers: trio('f:1106', A('fix', 'Fix', '/api/finding/1106/fix', { primary: true, instruct: true }), true),
    more: [ask(1106)],
  }),
];

// A finding the case list does not cover: still waiting for its first
// look. Counted in the queue, and shown as "Unchecked".
export const LOOSE = [
  { ts: 2001, text: 'The landing motion sensor stopped reporting', severity: 'warning',
    status: 'triaging', waiting_look: true, fixable: false,
    source: 'check:dev.unavailable', source_title: 'Device check',
    detail: 'Unavailable since 06:40.', fix: 'Check its battery.',
    entity_id: 'binary_sensor.landing_motion', triage: {}, snoozed_until: 0 },
];

export const PROPOSALS = [
  { ts: 3001000, status: 'proposed', title: 'Turn the porch light off at 23:10',
    why: 'You have done it by hand on nine of the last twelve weekdays.',
    config: { id: 'brain_routine_porch' }, kind: 'routine', snoozed_until: 0,
    replay: { would_fire: 9, days: 14 } },
  { ts: 3002000, status: 'proposed', title: 'Close the water main on a leak',
    why: 'Three leak sensors and a valve nobody has wired to them.',
    config: { id: 'brain_playbook_leak' }, kind: 'playbook', snoozed_until: 0,
    playbook: { kind: 'leak', no_trial: 'A trial replays a week with no leak in it.',
                groups: [], skipped: [] } },
];
export const INTENTS = [
  { ts: 4001000, status: 'armed', title: 'Porch light off when the guests leave',
    sentence: 'turn the porch light off when the guests leave', plain: 'Once.' },
];

export const TODAY_EXTRAS = {
  tidy: { key: 'tidy:1700000000', at: 1700000000, undo_days: 30, refused: [],
          rows: [
            { id: 'sensor.hue_0017', kind: 'name', label: 'Hue 0017 Temperature',
              value: 'Landing temperature', why: 'hardware name' },
            { id: 'light.lamp', kind: 'area', label: 'Lamp', area_name: 'Bedroom',
              from_area: '', reach: [] },
          ] },
  updates: [
    { key: 'update:update.core:2026.10.2', entity_id: 'update.core',
      title: 'Home Assistant Core', installed: '2026.10.1', latest: '2026.10.2',
      advice: { verdict: 'safe_tonight', reason: 'Nothing it changes is in your config.',
                note_quote: 'Fixed a typo in the Hue integration',
                config_quote: 'hue:' } },
  ],
};

export const TODO = {
  items: [
    { id: 1, text: 'Replace the hallway smoke alarm battery', detail: '', fix: '',
      entity_id: '', severity: 'warning', origin: 'hand', status: 'open',
      added_at: NOW - 3600, snoozed_until: 0 },
    { id: 2, text: 'Hall sensor has not reported since 3 Sep', detail: '',
      fix: 'Re-pair it', entity_id: 'binary_sensor.hall', severity: 'serious',
      origin: 'finding', source_title: 'Device check', status: 'open',
      added_at: NOW - 86400, snoozed_until: 0 },
    { id: 3, text: 'A snoozed chore', detail: '', fix: '', entity_id: '',
      severity: 'info', origin: 'hand', status: 'open', added_at: NOW - 86400,
      snoozed_until: NOW + 86400 * 3 },
  ],
  done: [], open: 3, done_count: 0,
};

export const HISTORY = {
  filters: [
    { id: 'snoozed', label: 'Snoozed', count: 1 },
    { id: 'ignored', label: 'Ignored', count: 2 },
    { id: 'done', label: 'Done', count: 1 },
    { id: 'aside', label: 'Set aside by brAIn', count: 1 },
  ],
  rows: {
    snoozed: [{ id: 'snoozed|cooling time yesterday', deletable: false,
                title: 'Cooling time yesterday', meta: '6 times since 15 Sep',
                at: NOW, since: NOW - 20 * 86400, count: 6,
                press: { label: 'Restore', steps: [{ label: 'Restore',
                  route: '/api/case/f:9/wake', body: {} }] } }],
    ignored: [
      { id: 'ignored|bathroom fan ran long', deletable: true, title: 'Bathroom fan ran long', meta: 'Ignored 4 Oct · You said: it is on a timer',
        at: NOW, since: NOW, count: 1, press: { label: 'Restore', steps: [
          { label: 'Restore', route: '/api/findings/unsettle', body: { key: 'k' } }] } },
      { id: 'ignored|everything like this', deletable: true,
        title: 'Everything like this: Sensors frozen on one value',
        meta: 'Ignored · not raised at all', at: 0, since: 0, count: 1,
        press: { label: 'Restore', steps: [{ label: 'Restore',
          route: '/api/findings/unmute', body: { source: 'check:dev.frozen' } }] } },
    ],
    done: [{ id: 'done|tidied 4 names and rooms', deletable: true, title: 'Tidied 4 names and rooms', meta: 'Applied 4 Oct', at: NOW,
             since: NOW, count: 1, press: { label: 'Undo', steps: [{ label: 'Undo',
               route: '/api/tidy/undo/b1', body: {},
               confirm: 'Puts back each field that still holds what brAIn wrote. '
                 + 'A field you changed since is left alone.' }] } }],
    aside: [{ id: 'aside|heating ran 14 hours yesterday', deletable: true,
              title: 'Heating ran 14 hours yesterday', meta: 'Set aside 3 Oct · a '
                + 'routine HVAC runtime summary', at: NOW, since: NOW, count: 1,
              press: { label: 'Restore', steps: [{ label: 'Restore',
                route: '/api/finding/7/elevate', body: {} }] } }],
  },
};

// Three insight cards, in `/api/insights`' shape with the server's derived
// `entities` (what each card names). Not in the default stub — the measures
// of the queue never open the cards — so a measure passes `{ insights:
// INSIGHTS }`. One with a chart, one whose page draws nothing (its words
// and tiles are the card), and one whose page is a single line: the three
// heights a card's frame has to follow rather than reserve.
const CHART_HTML = '<!doctype html><html><head><style>body{margin:0}</style></head>'
  + '<body><svg viewBox="0 0 400 260" width="100%" height="260">'
  + '<rect x="10" y="10" width="380" height="240" fill="#2a78d6"/></svg></body></html>';
export const INSIGHTS = [
  { id: 'custom-1', category: 'custom', icon: '🧊', eyebrow: 'Freezers',
    title: 'The garage freezer is drifting warmer',
    summary: 'Yes — sensor.garage_freezer has drifted six degrees in a week. '
      + 'The kitchen one has not.',
    highlights: [{ label: 'Now', value: '-12.4 °C' }, { label: 'A week ago', value: '-18.1 °C' }],
    entities: ['sensor.garage_freezer'], html: CHART_HTML,
    generated_at: new Date((NOW - 3600) * 1000).toISOString(), tags: [], meta: {} },
  { id: 'custom-2', category: 'custom', icon: '🔒', eyebrow: 'Security',
    title: 'The alarm was disarmed at 4:17 by an automation',
    summary: 'automation.night_disarm turned the alarm off at 04:17 while everyone '
      + 'was asleep. Nobody pressed anything.',
    highlights: [{ label: 'Disarmed', value: '04:17' }, { label: 'By', value: 'Night disarm' },
                 { label: 'People home', value: '2' }, { label: 'Doors opened', value: '0' }],
    entities: ['alarm_control_panel.home', 'automation.night_disarm'],
    live: ['alarm_control_panel.home'],
    html: '<!doctype html><html><head><style>body{margin:0}</style></head><body></body></html>',
    generated_at: new Date((NOW - 7200) * 1000).toISOString(), tags: [], meta: {} },
  { id: 'custom-3', category: 'custom', icon: '💡', eyebrow: 'Lighting',
    title: 'The porch light ran all night', summary: 'It stayed on from 19:02 to 07:40.',
    highlights: [], entities: [], html: '<p style="margin:0">On for 12 h 38 min.</p>',
    generated_at: new Date((NOW - 9200) * 1000).toISOString(), tags: [], meta: {} },
];

export const NAMES = {
  'sensor.garage_freezer': { name: 'Garage Freezer', area: 'Garage' },
  'binary_sensor.kitchen_leak': { name: 'Kitchen Leak', area: 'Kitchen' },
  'binary_sensor.hall_old': { name: 'Hall (old)', area: 'Hall' },
  'binary_sensor.hall': { name: 'Hall', area: 'Hall' },
};

// The cards Today counts, by construction of the fixture: every case, the
// loose finding, every suggestion, the tidy card and the update. The armed
// one-off is waiting on the house and counted by nothing.
export const COUNTED = FEED.length + LOOSE.length + PROPOSALS.length + 1
  + TODAY_EXTRAS.updates.length;

export function stub(over = {}) {
  const data = {
    cases: FEED, names: NAMES, loose: LOOSE, insights: [], proposals: PROPOSALS, intents: INTENTS,
    extras: TODAY_EXTRAS, todo: TODO, history: HISTORY, firstLookDone: true,
    open: COUNTED, brief: { sent_at: NOW - 7200, text: 'Quiet night. The garage '
      + 'freezer is still drifting; nothing else needs you.' },
    status: { state: 'watching', label: 'Watching', sentence: 'Watching',
              since: null, back_at: null, last_look_at: NOW - 540 },
    ...over,
  };
  return `
window.__today = ${JSON.stringify(data)};
window.__posts = [];
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const d = window.__today;
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (opts && opts.method && opts.method !== 'GET') {
    window.__posts.push({ url: p, method: opts.method, body: opts.body || '' });
  }
  if (p.includes('api/cases')) {
    return answer({ cases: d.cases, names: d.names, open: d.open, ledger: {},
                    resident: {}, eventbus: { connected: true }, watching: 0 });
  }
  if (p.includes('api/findings')) {
    return answer({ findings: d.loose, hypotheses: [], open: d.open, settled: [],
                    scorecard: [], muted: [] });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: d.open,
      queue_count: d.open, status: d.status, brief: d.brief,
      first_look_done: d.firstLookDone,
    });
  }
  if (p.includes('api/onboarding')) return answer({ onboarded: true, state: 'done' });
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: d.insights });
  if (p.includes('api/todo')) return answer(d.todo);
  if (p.includes('api/proposals')) {
    return answer({ proposals: d.proposals, intents: d.intents,
                    counts: { open: d.proposals.length } });
  }
  if (p.includes('api/history')) return answer(d.history);
  if (p.includes('api/today')) return answer(d.extras);
  return answer({});
};
`;
}

// Every label a button on Today may carry: the design doc's vocabulary,
// plus Yes and No — the answer to a question rather than a verb.
export const VOCAB = new Set(['Apply', 'Fix', 'Add to To Do', 'Snooze', 'Ignore',
  'Done', 'Restore', 'Undo', 'Ask', 'Send', 'Recheck', 'Check again', 'Dismiss',
  'Run', 'Save', 'Share',
  'Delete', 'Yes', 'No', 'Cancel', 'Change']);

// What the redesign cut from the face of a card, and must stay cut. Allowed
// inside Details, nowhere else on Today.
export const CUT = [
  /needs a decision/i, /not looked at yet/i, /not checked first/i,
  /a fix may not call brain services/i, /run checks now/i, /how right it's been/i,
  /what's waiting on you/i, /looked \d+ times? today/i, /\d+ checks ran/i,
  /\bFix it\b/, /\bDismiss\b/, /Not a problem/, /press Wrong/i,
  /Stop raising these/, /written before brAIn checked/i,
];

// Open the panel on Today behind this fixture, and wait for the queue (or
// the empty line, or the setup card) to be drawn. `onError` takes every page
// error, because a measure that swallowed one would pass over a renderer
// that threw half-way down the queue. Every card is drawn, not the first
// screenful: the measures that use this are about the cards.
export async function openToday(browser, panelDir, { width, touch = false, over = {},
  onError = () => {}, extra = '' } = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => onError(e.message));
  await page.addInitScript(stub(over));
  // A measure's own answers for a route, wrapped round the stub's fetch.
  if (extra) await page.addInitScript(extra);
  await page.goto(`file://${panelDir}/index.html`);
  // The panel lands on the insight cards; the queue is Insights › Needs you.
  await page.waitForFunction(() => typeof switchView === 'function');
  await page.evaluate(() => switchView('findings'));
  await page.waitForFunction(() => document.querySelector('#findList')
    && (document.querySelector('#findList .qcard')
        || document.querySelector('#findList .empty-line')
        || !document.querySelector('#todaySetup').hidden));
  await page.evaluate(() => {
    const b = document.getElementById('todayMore');
    if (b && !b.hidden) b.click();
  });
  return { page, context };
}

// The presses a page sent, as {url, method, body} with the body parsed.
export const posts = (page) => page.evaluate(() => window.__posts.map((p) => {
  let body = null;
  try { body = p.body ? JSON.parse(p.body) : null; } catch (e) { body = p.body; }
  return { url: p.url, method: p.method, body };
}));
