// Drive the ⚙ page and assert it is a thing somebody can get through.
//
// What this exists to prevent is the shape ⚙ has shipped in twice. First a
// dialog that was one flat scroll — measured behind this same stub, **5,910px
// at 390 and 3,837px at 1,200**. Then eight panes on a segmented control,
// which on a phone was a select hiding seven of its eight names, with the
// model picker inside a "Usage & schedule › Advanced" fold, the Ask tab's
// settings inside "Permissions › Advanced" and the deep check inside
// "Diagnostics › Developer": the owner's words were "really bulky, hard to
// navigate sections, stuff is buried under collapsible sections".
//
// So ⚙ is a LIST of ten sections — Account, Model & usage, Permissions,
// Notifications, Cameras & calendars, Personality, Instructions,
// Diagnostics, Developer, Guide (Personality moved here from Morph's own
// Settings, because everybody uses brAIn and not everybody uses Morph;
// Memory moved OUT, to Memory › Knowledge, because a second place for what
// brAIn remembers was a place nobody could tell from the first) —
// each row saying what it is set to now, beside the section in front on a
// wide screen and as the page itself on a phone. The checks:
//
//   * the page's height at OPEN time is under a budget per width (the list
//     on a phone, the list beside Account on a desktop).
//   * there are exactly ten sections (Personality and then Instructions
//     after Cameras & calendars), named and ordered as above, one row
//     each on the list, every row clearing the touch floor and carrying a
//     second line; the list's lines say what the weekly answers ARE at open
//     time — signed in, the model, whether brAIn asks — with no press.
//   * on a phone nothing is in front at open (the list is), a row opens its
//     section, and "‹ Settings" goes back to the list; on a desktop exactly
//     one section is in front.
//   * the settings a person changes weekly — the model, the sign-in, the
//     usage and budget, the notification sentence and "Let brAIn act without
//     asking" — are each visible after ONE press from opening ⚙, with no
//     disclosure opened; and no form control anywhere in ⚙ lives inside a
//     <details> (there is no "Advanced" or "Developer" fold left).
//   * the usage budget's slider ends in a labelled "No limit: run until
//     Anthropic rate-limits" past 100%; at a percentage the line under it
//     says automatic insights stop there, with No limit it says they keep
//     running (and, while Anthropic has rate-limited, until when), and each
//     choice saves the right setting.
//   * Diagnostics opens on "Run all tests", whose result reads "N of M
//     passed · K skipped" with one row per stage: Passed / Failed / Skipped
//     in words, the reason, and the time it ran — a skipped stage is never
//     drawn as failed.
//   * there is NO "?" bubble anywhere, and no hint runs past two sentences.
//   * the safety prose stays on the page: the sharing box's backup warning,
//     the shell-command caveat under "Let brAIn act without asking" (and it
//     is still there when the line above it turns into the stale-session
//     warning), and the calendar note beside the calendar picker.
//   * Sign out is neutral at rest, never filled or coloured red.
//   * a wide page remembers the section in front, across leaving Settings
//     (⚙ is the way back) AND across a reload.
//   * the Diagnostics and Developer loaders do not run until that section
//     is opened, and opening it fills every block.
//   * ⚙ has no Memory section, and ⚙ › Memory's old address (a link or a
//     shell message naming the section) opens Memory › Knowledge's memory
//     document instead — the document, Edit, Export and the queue are
//     asserted there, in measure-knowledge.mjs. Opening ⚙ still reads no
//     memory, and "File into memory now" is still cut.
//   * Cameras & calendars reads them only when it opens.
//   * Guide lists eight groups and opens the docs, whose nav is eight
//     headings with no emoji.
//   * every visible button says one of the doc's verbs.
//   * every text control clears the 16px iOS floor at 390, the page never
//     scrolls sideways, and every element id handlers bind to is present.
//   * a search box sits above the list: words find a setting by its name and
//     the line under it, a press opens its section with it in view and
//     marked, nothing found says so, and clearing it brings the list back.
//   * every switch is a row in a group — its words on the left, the switch
//     in the right-hand column beside them, never more than 640px from the
//     start of its label on a wide screen — cameras and calendars included.
//   * ⚙'s heading carries the version (it left the header, which the owner
//     asked to be "subtle") as one link to this release's changelog anchor (`CHANGELOG.md#2185`), named, a 44px target
//     on touch, and saying "restart needed" with the restart sentence while
//     Home Assistant still runs an older integration.
//   * pressing it opens What's new in the panel: the notes newest first,
//     the releases since this browser last looked marked "New" in words, a
//     pending restart said, and the published file as the fallback when the
//     Supervisor will not hand the notes over.
//   * Diagnostics says what is wrong in words — a job by what it does, no
//     check id, job word or exit code on the face of a row, the ids under a
//     closed technical part — and the scorecard names every rule, counts in
//     words ("right 8 of 14, wrong 6") and gives a verdict.
//   * #555: Model & usage says each thing once — the session limit in the
//     slider's label and not again in the line under it, "Asking by hand
//     always runs" once — with no sub-heading repeating the section's
//     name; and no summary on the list is cut off with an ellipsis.
//   * #556: Permissions names each switch once, in plain words ("No
//     restrictions", never "YOLO"), with no heading over it saying the same,
//     and says how it differs from acting without asking.
//   * #557: Diagnostics and Developer read in plain words: no journal, no
//     daemon, no "Configuration tab", no internal id or <code> on a row —
//     a background job by what it does, a rehearsal row by what was
//     planted and its verdict in words.
//
// Drives the panel's REAL markup and its real `openSettings` /
// `restoreSettingsSections` behind a stubbed fetch. A copy of the page in
// this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 768, 1200];
const MIN_TARGET = 44;
const MIN_TEXT = 16;

// Before any reorganisation: 5910 at 390, 3837 at 1200. Six disclosures
// brought that to ~2170 and ~1600 with two of them open. Eight panes on a
// segmented control measured 1569 at 390 and 1268 at 1200 (the dialog's own
// budget then was 1750/1400). The list opens at 774 on a phone and at the
// viewport's own 900 beside Account on a desktop; the budgets leave room for
// a font or a hairline to move and not for a section to come back flat.
// The phone's list grew one row (~60px) when Personality moved in from
// Morph (886 → 945 measured), so its budget moved by that one row and no
// more; a section coming back flat is still hundreds of pixels over it.
// It grew one more row in 4.0 when Features came first (945 → 1005 at 390,
// 1022 at 768), and moved by that row again; ⚙ › Dashboard's row is hidden
// while the Morph dashboard is off, as it is here.
// And once more (#555) when the list's summaries stopped being cut off with
// an ellipsis: a summary that is the house's own words (the notification
// sentence, the personality) wraps to a second line rather than ending in
// "…", which at 390 is two rows of ~17px (1040 measured); the budget moved by
// those two lines and no more.
const MAX_SCROLL = { 390: 1055, 768: 1060, 1200: 1000 };

// The verbs a button in ⚙ may say. The doc's vocabulary, plus the few
// labels it names for this dialog itself (Sign in again, Sign out, Edit,
// Export) and the generic pair a dialog row needs (Cancel, Remove, View).
const VERBS = new Set(['Apply', 'Fix', 'Add to To Do', 'Snooze', 'Ignore', 'Done',
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
  'setNav', 'viewSettings', 'deepSummary', 'deepBox', 'setEnabled', 'setGatherMode', 'setHistoryDays', 'setKeepDays',
  'setKeepRuns', 'setModel', 'setThinking', 'setModelCustom', 'setPlan',
  'setRefresh', 'setRefreshMode', 'setSyncNote', 'setTerminalUi', 'setTimeout',
  'usageFill', 'usageMark', 'usageText', 'usageWeekFill', 'usageDetail',
  'setNotifyPolicy', 'setNotifyLearned', 'setSpeakFirst',
  'setSkipPerms', 'setSkipPermsRow', 'setSkipPermsNote', 'setSkipPermsCaveat',
  'setHouseRules', 'setHouseRulesSave', 'setCameras', 'setCalendars',
  'setCalendarsNote', 'diagAccuracy', 'diagMeasures', 'diagOvernight',
  'diagOvernightRun', 'diagAccess', 'diagAccessRun', 'setGuide',
  'setSearch', 'setSearchResults', 'versionChip', 'versionText',
  'whatsNewModal', 'whatsNewBody', 'whatsNewClose', 'whatsNewRestart',
  'persName', 'persText', 'persSave', 'persAsk', 'persGrowth', 'setSumPersonality',
];

// The sections, in order, and which one a wide page lands on the first
// time. A phone lands on the list, with none of them in front.
const SECTIONS = [
  { sec: 'features', name: 'Features', open: false },
  // Shown only while the Morph dashboard is on, and this house has it off.
  { sec: 'dashboard', name: 'Dashboard', open: false, offHere: true },
  { sec: 'account', name: 'Account', open: true },
  { sec: 'usage', name: 'Model & usage', open: false },
  { sec: 'permissions', name: 'Permissions', open: false },
  { sec: 'notifications', name: 'Notifications', open: false },
  { sec: 'sources', name: 'Cameras & calendars', open: false },
  { sec: 'personality', name: 'Personality', open: false },
  { sec: 'instructions', name: 'Instructions', open: false },
  { sec: 'diagnostics', name: 'Diagnostics', open: false },
  { sec: 'developer', name: 'Developer', open: false },
  { sec: 'guide', name: 'Guide', open: false },
];

// The weekly answers: each must be visible after one press on its row,
// with nothing folded open.
const WEEKLY = [
  { id: 'authBody', sec: 'account', what: 'the sign-in' },
  { id: 'setModel', sec: 'usage', what: 'the model' },
  { id: 'usageFill', sec: 'usage', what: 'the usage bar' },
  { id: 'setBudget', sec: 'usage', what: 'the budget' },
  { id: 'setNotifyPolicy', sec: 'notifications', what: 'the notification sentence' },
  { id: 'setSkipPerms', sec: 'permissions', what: '"Let brAIn act without asking"' },
];

// The reads behind Diagnostics and Developer. Any of these before its
// section is opened is the lazy load not being lazy.
const DIAG_URLS = ['api/diagnostics', 'api/reports', 'api/doctor/deep',
                   'api/sre', 'api/access', 'api/knowledge/house'];
const DEV_URLS = ['api/capture', 'api/doctor/rehearse'];
const LAZY_URLS = [...DIAG_URLS, ...DEV_URLS, 'api/instructions', 'api/personality',
                   'api/presence'];

const CUT = ['Copy selected', 'Copy all', 'Write a report now',
             'Copy for a bug report', 'File into memory now', 'Check it now',
             'Measure the house now', 'Run deep check', 'Rehearse…'];

const NOW = Math.floor(Date.now() / 1000);

// A persona moved over from Morph's old PERSONA object: labelled parts, the
// way personality.py's import renders them. The sections the page must draw
// from it, in order, by their plain titles.
const PERSONA_OUTLINE = [
  'line: The evening star of the house, steady and a little wry.',
  'born: 2026-03-14',
  'who_i_am:',
  '  - a keeper of small routines',
  '  - plain-spoken',
  'how_i_am: Calm first, quick second.',
  'voice:',
  '  rules:',
  '    - one sentence for what changed',
  '  tone: warm',
  'never:',
  '  - lecture',
  'name_why: Named for the star that comes out first.',
  'still_working_out: when to speak up at night, and how softly.',
].join('\n');
const PERSONA_TITLES = ['Tagline', 'Born', 'Who I am', 'How I am', 'Voice', 'Never',
  'Why the name', 'Still working out'];
// What the old cap left of a longer persona: the outline padded to ~3,996
// characters and ended with "…".
const PERSONA_CUT = ' ' + 'It keeps the house quiet in the evening. '.repeat(90).slice(0, 3995 - PERSONA_OUTLINE.length - 1).trimEnd() + '…';

const STUB = `
const PERSONA_OUTLINE = ${JSON.stringify(PERSONA_OUTLINE)};
const PERSONA_CUT = ${JSON.stringify(PERSONA_CUT)};
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
  if (p.includes('api/personality')) {
    if (opts && opts.method === 'PUT') {
      (window.__personaPuts = window.__personaPuts || []).push(JSON.parse(opts.body));
    }
    // The persona as Morph's old PERSONA object moved over: an outline of
    // labelled parts. With window.__personaCut it ends the way the old
    // 4,000-character cap cut it.
    const sent = opts && opts.method === 'PUT' ? JSON.parse(opts.body) : null;
    const persona = sent ? sent.persona : PERSONA_OUTLINE + (window.__personaCut ? PERSONA_CUT : '');
    return answer({ set: true, name: 'Juniper', persona,
      summary: 'Juniper · The evening star of the house, steady and a little wry.',
      cut_at_old_limit: !sent && !!window.__personaCut,
      growth: [{ date: '2026-10-29', at: 1793336400, by: 'self',
                 text: 'Keeps evening messages to one line; the longer ones went unanswered.' },
               { date: '2026-09-20', text: 'Stopped announcing the heating twice.' },
               { date: '2026-08-02', text: 'Calls the side door the garden door.' }],
      updated_at: ${NOW}, path: '/config/.brain/personality.json',
      limits: { name: 60, persona: 32000, growth: 500 } });
  }
  if (p.includes('api/presence')) {
    // The presence loop's section (⚙ › Personality › How … is growing):
    // two invented people, an idea each, a note, a retired kind and two
    // touches it sent with their reasons.
    if (opts && opts.method === 'POST') {
      (window.__presencePosts = window.__presencePosts || []).push(JSON.parse(opts.body));
    }
    return answer({ on: true, why: '', name: 'Juniper', reflected: 'Today 03:12',
      budget: { per_day: 1, per_week: 3, house_day: 3, hours: '08:00–21:00' },
      people: [
        { person: 'person.wren', name: 'Wren', paused: false,
          ideas: [{ id: 'a1b2', kind: 'evening', kind_label: 'Evening check-in',
                    text: 'Evening, Wren — the bins go out tonight.',
                    reason: 'Wren asked when the bins go out on Monday.' }],
          notes: [{ id: 'n1', text: 'Likes a heads-up about the bins.' }],
          retired: [{ kind: 'morning', kind_label: 'Morning check-in' }] },
        { person: 'person.ilo_long_named_person', name: 'Ilo Marguerite-Okonkwo', paused: true,
          ideas: [{ id: 'c3d4', kind: 'arrival', kind_label: 'Welcome home',
                    text: 'Welcome back, Ilo. The heating came on twenty minutes ago so the house is warm.',
                    reason: 'Ilo said on Tuesday the hall is cold when they get in.' }],
          notes: [], retired: [] }],
      touches: [
        { id: 'e5f6', name: 'Wren', kind_label: 'Welcome home', when: 'Yesterday 17:42',
          text: 'Welcome back, Wren — the porch light is on.', channel: 'phone',
          reason: 'Wren asked for the porch light at dusk.', reaction: 'thanks', reaction_label: 'Thanks' },
        { id: 'a7b8', name: 'Ilo Marguerite-Okonkwo', kind_label: 'Morning check-in', when: 'Tuesday 08:30',
          text: 'Morning, Ilo. Rain from eleven, the washing is better inside.', channel: 'speaker',
          reason: 'Ilo hangs washing out on Tuesdays.', reaction: 'spoken', reaction_label: 'Said aloud' }] });
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
    if ('budget_no_limit' in sent) window.__noLimit = sent.budget_no_limit === true;
    if ('budget_percent' in sent) window.__budgetPct = sent.budget_percent;
    return answer({
      ...(window.__permSessions !== undefined
        ? { permission_sessions: window.__permSessions } : {}),
      settings: {
        auto_enabled: true, capture: false, terminal_ui: 'chat',
        chat_max_sessions: 3, gather_mode: 'search', refresh_mode: 'changed',
        plan: 'pro', budget_percent: window.__budgetPct || 25,
        budget_no_limit: window.__noLimit === true, refresh_hours: 12, history_days: 7,
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
               window_tokens: 42000, plan_label: 'Pro', budget_percent: window.__budgetPct || 25,
               no_limit: window.__noLimit === true, blocked: false,
               rate_limited_until: window.__rateLimitedUntil || null,
               resets_at: ${NOW} + 7200, week_resets_at: ${NOW} + 200000 },
      options_synced: true, model_label: 'Claude Sonnet 4.5',
      personality_summary: 'Juniper · The evening star of the house, steady and a little wry.',
    });
  }
  if (p.includes('api/status')) {
    return answer({
      version: '2.18.5', authenticated: true, auth_type: 'oauth_token',
      integration: window.__restartPending
        ? { loaded: '2.18.4', required: '2.18.5', restart_pending: true }
        : { loaded: '2.18.5', required: '2.18.5', restart_pending: false },
      ...(window.__restartPending ? { status: { state: 'needs_restart',
        label: 'Needs restart', sentence: 'Restart Home Assistant to finish updating brAIn' } } : {}),
      auth_source: 'local', auth_check: { state: 'ok', error: '' },
      model: 'claude-sonnet-4-5', settings: { onboarded: true },
      usage: { percent: 18, source: 'account' }, auto: { enabled: true },
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/changelog')) {
    if (window.__changelogFails) {
      return answer({ version: '2.18.5', sections: [],
                      error: 'The Supervisor did not answer.' });
    }
    return answer({ version: '2.18.5', error: '', sections: [
      { version: '2.18.5', text: '### Fixed\\n\\n- **Health** speaks plainly.' },
      { version: '2.18.4', text: '### Added\\n\\n- What is new, in the panel.' },
      { version: '2.18.3', text: '### Changed\\n\\n- An older change.' },
    ] });
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
      health: { state: 'ok', reason: '' },
      // Two rows in the shape \`reports.faults\` sends: the machine fields
      // the development loop fingerprints, and the words a person reads.
      faults: [
        { where: 'Run (memory)', what: 'ended crash (6 times)',
          detail: 'claude exited 1; last at Mon 14:13',
          title: 'Filing facts into memory',
          sentence: 'It did not finish (6 times in the last day, last at Mon 14:13). '
            + 'brAIn tries again on its own; if it keeps happening, use Report a problem below.',
          technical: 'Run (memory): ended crash (6 times); claude exited 1; last at Mon 14:13' },
        { where: 'Producer Sensors frozen on one value (check:dev.frozen)',
          what: 'ignored 3 of 4 times', detail: 'this rule is firing on a healthy house',
          title: 'Sensors frozen on one value',
          sentence: '3 marked wrong of 4 answers. brAIn has asked on Needs you whether '
            + 'to stop raising these; answer it there.',
          technical: 'check:dev.frozen: 3 wrong, 1 confirmed' },
        { where: 'Looks', what: '9 findings are still waiting for a look',
          detail: 'The oldest has waited 5 h 0 min.' },
      ],
      runs: { total: 12, failures: [] }, checks: { ran: 15, skipped: [] },
      journal: { claude_runs: 12, runs: 12, by_outcome: { ok: 40, error: 2 }, failures: [] },
      daemons: {
        usage_tracker: { running: true, what: 'the usage tracker' },
        assist_listener: { running: false, not_used: 'not used (fast mode)', expected: false, what: 'the voice listener' },
        ttyd: { running: false, not_used: 'not used (enable_terminal is off)', expected: false, what: 'the terminal' },
        automation_listener: { running: false, expected: true, what: 'the automation listener' },
      },
      proposals: { intents: { armed: 2, fired: 1, refused: 0, queued: 0, ttl_days: 14 } },
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
    // A finished rehearsal, its rows as rehearsal.score sends them.
    return answer({ running: false, sweeping: false, plan: [], leftovers: [], last: {
      finished_at: ${NOW} - 900,
      checks: { planted: 2, found: 1, extra: 0, rows: [
        { id: 'brain_test_dead_ref', name: 'An automation naming a light that does not exist',
          check: 'auto.dead_ref', verdict: 'found', reported: ['x'] },
        { id: 'brain_test_dead_service', name: 'An automation calling an action that does not exist',
          check: 'auto.dead_service', verdict: 'missed', reported: [] }] },
      analyst: { ran: false, error: 'skipped' },
      cleanup: { ok: true, sentence: 'Everything it planted was removed.' },
      cleared: { at: ${NOW} - 800, ok: true, removed: [] } } });
  }
  if (p.includes('api/doctor')) {
    // One finished run: three passed, one failed, two skipped — one over a
    // failed precondition and one over a switch that is off.
    const st = (name, title, state, sentence, at) => ({ name, title, state, sentence,
      detail: '', proves: '', seconds: 3, at });
    const stages = [
      st('snapshot_claude', 'A plain Claude run', 'ok', 'Claude answered.', ${NOW} - 600),
      st('analyst_tools', 'Reading the house', 'ok', 'It read 3 entities.', ${NOW} - 560),
      st('chat', 'The chat', 'failed', 'The chat did not answer within its limit.', ${NOW} - 500),
      st('memory', 'Memory', 'ok', 'A fact went in and came back out.', ${NOW} - 450),
      st('fixer_dry', 'A fix, rehearsed', 'skipped',
         'Not run because chat did not pass — it would fail for the same reason and say so twice.', ${NOW} - 450),
      st('automation', 'The automation listener', 'skipped',
         'The Automation integration is off (enable_automation_integration).', ${NOW} - 449),
    ];
    return answer({ running: false, stages: [], stage_catalog: [],
      last: { started_at: ${NOW} - 620, finished_at: ${NOW} - 449, stages, verdict: 'failed',
              counts: { ok: 3, failed: 1, skipped: 2 } } });
  }
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
      // The rows as \`server._scorecard\` sends them: a name, the count in
      // words and a verdict, with the id kept on \`source\`.
      scorecard: [{ source: 'check:dev.frozen', title: 'Sensors frozen on one value',
                    name: 'Sensors frozen on one value', count_words: 'right 8 of 14, wrong 6',
                    verdict: 'trusted', confirmed: 8, total: 14, wrong: 6 },
                  { source: 'check:forecast.decline', title: 'Declining readings',
                    name: 'Declining readings', count_words: 'right 0 of 3, wrong 3',
                    verdict: 'doubtful', confirmed: 0, total: 3, wrong: 3 },
                  { source: 'user-1789499215', title: 'user-1789499215',
                    name: 'Laundry watch', count_words: 'right 3 of 4, wrong 1',
                    verdict: 'trusted', confirmed: 3, total: 4, wrong: 1 }],
      muted: [{ source: 'check:auto.conflict', title: 'Automations that fight' }] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
// A step that cannot be driven at all ends the run, with everything found
// before it: a page with no way to a section is a failure, not a crash.
process.on('uncaughtException', (e) => {
  console.error('measure-settings: FAIL');
  for (const f of failures) console.error('  ' + f);
  console.error('  stopped: ' + String(e.message).split('\n')[0]);
  process.exit(1);
});
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
  .filter((b) => b.offsetParent !== null && !b.hidden && !b.classList.contains('krow')
    && !b.classList.contains('setnavbtn') && !b.classList.contains('setback')
    && !b.classList.contains('setresult') && !b.classList.contains('instrrow')
    && !b.classList.contains('instrback'))
  .map((b) => b.textContent.replace(/\\s+/g, ' ').trim());
`;

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

// Put one section in front the way a person would: its row on the list —
// which on a phone means "‹ Settings" first when a section is in front.
const showSection = async (page, sec) => {
  const button = page.locator(`#setNav .setnavbtn[data-sec="${sec}"]`);
  if (!await button.isVisible()) {
    await page.locator('#setModal .setsec:not([hidden]) .setback').click({ timeout: 3000 });
  }
  await button.click({ timeout: 3000 });
  await page.waitForFunction((s) => !document.querySelector(`#setModal .setsec[data-sec="${s}"]`).hidden,
    sec, { timeout: 3000 });
};

for (const width of WIDTHS) {
  const touch = width <= 430;
  // Below 900px the list is the page until a row is pressed.
  const narrow = width < 900;
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
  await page.waitForFunction(() => !!document.querySelector('#authBody p'));

  // ---- how long is the page, and what is on the control ----------------
  const m = await page.evaluate(() => {
    const body = document.querySelector('#setModal');
    const navBtns = [...document.querySelectorAll('#setNav .setnavbtn')];
    const secs = [...document.querySelectorAll('#setModal .setsec')].map((d, i) => {
      const btn = navBtns[i];
      const box = btn ? btn.getBoundingClientRect() : { height: 0, right: 0 };
      return {
        sec: d.dataset.sec, open: !d.hidden, h: Math.round(box.height), right: box.right,
        rowShown: !!btn && btn.offsetParent !== null,
        button: btn ? (btn.querySelector('.setnavname') || {}).textContent || '' : '',
        buttonFor: btn ? btn.dataset.sec : '',
        name: (d.querySelector('.setsecname') || {}).textContent || '',
        sum: btn ? (btn.querySelector('.setnavsum') || {}).textContent || '' : '',
      };
    });
    // A form control inside a <details> is a setting somebody has to open
    // a fold to reach.
    const folded = [...document.querySelectorAll(
      '#setModal details input, #setModal details select, #setModal details textarea, '
      + '#setModal details button')].map((c) => c.id || c.tagName);
    const folds = [...document.querySelectorAll('#setModal details')]
      .filter((dd) => !dd.classList.contains('authdetails'))
      .map((dd) => dd.id || (dd.querySelector('summary') || {}).textContent || 'details');
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
      scrollH: document.documentElement.scrollHeight,
      bodyRight: Math.max(body.getBoundingClientRect().right, window.innerWidth),
      secs, bubbles, small, folded, folds,
      index: document.querySelector('#setModal').classList.contains('setindex'),
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
    note(where, `the page is ${m.scrollH}px tall at open, over the ${MAX_SCROLL[width]}px budget`);
  }

  // ---- the sections ------------------------------------------------------
  if (m.folded.length) note(where, `controls inside a fold: ${m.folded.join(', ')}`);
  if (m.folds.length) note(where, `folds left in ⚙: ${m.folds.join(', ')}`);
  if (m.secs.length !== SECTIONS.length) {
    note(where, `${m.secs.length} sections, expected ${SECTIONS.length}`);
  }
  SECTIONS.forEach((want, i) => {
    const got = m.secs.find((s) => s.sec === want.sec);
    if (!got) { note(where, `no "${want.sec}" section`); return; }
    if (m.secs[i] && m.secs[i].sec !== want.sec) {
      note(where, `section ${i + 1} is "${m.secs[i].sec}", expected "${want.sec}"`);
    }
    if (touch && got.h < MIN_TARGET && !want.offHere) note(where, `the ${want.sec} control is ${got.h}px, under ${MIN_TARGET}`);
    if (got.name.trim() !== want.name) note(where, `the ${want.sec} section is named "${got.name.trim()}"`);
    if (got.button !== want.name || got.buttonFor !== want.sec) {
      note(where, `the control's button for ${want.sec} reads "${got.button}"`);
    }
    if (got.sum.trim().length < 8) note(where, `the ${want.sec} row has no second line`);
    if (!got.rowShown && !want.offHere) note(where, `the ${want.sec} row is not on screen at open`);
    const wantOpen = narrow ? false : want.open;
    if (got.open !== wantOpen) note(where, `${want.sec} is shown ${got.open} and should be ${wantOpen}`);
    if (got.right > m.bodyRight + 0.5) note(where, `the ${want.sec} row overflows the page`);
  });
  const shownNow = m.secs.filter((x) => x.open).length;
  if (narrow ? shownNow !== 0 || !m.index : shownNow !== 1) {
    note(where, `${shownNow} sections shown at open (${narrow ? 'a narrow page opens on the list' : 'want 1'})`);
  }
  // The list itself says the weekly answers, with no press.
  const sumOf = (sec) => (m.secs.find((x) => x.sec === sec) || {}).sum || '';
  if (!/^Signed in/.test(sumOf('account'))) note(where, `the Account row reads "${sumOf('account')}"`);
  if (!/Claude Sonnet 4\.5 · 18% of this session/.test(sumOf('usage'))) {
    note(where, `the Model & usage row reads "${sumOf('usage')}"`);
  }
  if (sumOf('permissions') !== 'Asks before it acts') note(where, `the Permissions row reads "${sumOf('permissions')}"`);
  if (!/water/.test(sumOf('notifications'))) note(where, `the Notifications row reads "${sumOf('notifications')}"`);
  if (!/Juniper/.test(sumOf('personality'))) note(where, `the Personality row reads "${sumOf('personality')}"`);

  // ---- no "?" bubble, and no hint past two sentences ---------------------
  if (m.bubbles.length) note(where, `"?" bubbles remain: ${m.bubbles.join(', ')}`);
  for (const h of m.hints) {
    if (h.sentences > 2) note(where, `a hint runs to ${h.sentences} sentences: "${h.text.slice(0, 70)}…"`);
  }
  for (const gone of CUT) {
    if (m.allText.includes(gone)) note(where, `"${gone}" is back in ⚙`);
  }
  if (/💡/.test(m.allText)) note(where, 'the token tips came back');

  // ---- every weekly setting is one press away, with nothing unfolded ------
  for (const w of WEEKLY) {
    try {
      await page.click('#settingsBtn');        // leave …
      await page.click('#settingsBtn');        // … and open ⚙ afresh
      await page.waitForSelector('#setModal.open');
      await page.click(`#setNav .setnavbtn[data-sec="${w.sec}"]`);   // the one press
      const seen = await page.evaluate((id) => {
        const n = document.getElementById(id);
        if (!n || n.offsetParent === null) return false;
        const r = n.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && !n.closest('details:not([open])');
      }, w.id);
      if (!seen) note(where, `${w.what} is not visible one press after opening ⚙`);
      // The budget is a slider a thumb has to land on: the 44px floor, not
      // the 16px of its own round thumb.
      if (touch && w.id === 'setBudget') {
        const h = await page.evaluate(() => Math.round(
          document.getElementById('setBudget').getBoundingClientRect().height));
        if (h < MIN_TARGET) note(where, `the budget slider is ${h}px tall, under ${MIN_TARGET}`);
      }
    } catch (e) {
      note(where, `reaching ${w.what} failed: ${String(e.message).split('\n')[0]}`);
    }
  }
  // ---- the budget: a labelled "No limit" past 100%, and what each means ---
  try {
    await showSection(page, 'usage');
    const budget = () => page.evaluate(() => {
      const n = document.querySelector('#setBudgetNote');
      const own = window.__hintSentences().find((h) => h.text
        === n.textContent.replace(/\s+/g, ' ').trim());
      return {
        label: document.querySelector('label[for="setBudget"]').textContent.replace(/\s+/g, ' ').trim(),
        note: n.textContent.replace(/\s+/g, ' ').trim(),
        noteShown: n.offsetParent !== null,
        sentences: own ? own.sentences : -1,
        scale: (document.querySelector('#setModal .budgetscale') || {}).textContent || '',
        max: Number(document.querySelector('#setBudget').max),
        valuetext: document.querySelector('#setBudget').getAttribute('aria-valuetext') || '',
        markHidden: document.querySelector('#usageMark').classList.contains('hidden'),
        put: (window.__puts || []).slice(-1)[0] || null,
      };
    });
    const slide = (v) => page.evaluate((val) => {
      const r = document.querySelector('#setBudget');
      r.value = String(val);
      r.dispatchEvent(new Event('input', { bubbles: true }));
      r.dispatchEvent(new Event('change', { bubbles: true }));
    }, v);
    let b = await budget();
    if (!/up to 25% of each 5-hour session/.test(b.label)) note(where, `the budget reads "${b.label}"`);
    // #555: the line under the slider says what happens at the limit the
    // label names, never the limit again.
    if (/25%|session limit/.test(b.note) || !/wait|reset/.test(b.note) || !b.noteShown) note(where, `the line under the budget says the limit again or not what happens at it: "${b.note}"`);
    {
      const u = await page.evaluate(() => {
        const sec = document.querySelector('#setsecUsage');
        // The section's first thing under its name: a sub-heading there
        // would only say part of the name again.
        const first = sec.querySelector('.setsecbody').firstElementChild;
        return { text: sec.innerText.replace(/\s+/g, ' '), first: first && first.matches('.sethead') ? first.textContent.trim() : '',
                 name: sec.querySelector('.setsecname').textContent.trim() };
      });
      const byHand = (u.text.match(/Asking by hand always runs/g) || []).length;
      if (byHand !== 1) note(where, `Model & usage says "Asking by hand always runs" ${byHand} times`);
      const words = u.name.toLowerCase().split(/[^a-z]+/).filter(Boolean);
      if (u.first && words.includes(u.first.toLowerCase())) note(where, `the first sub-heading repeats the section's name: ${u.first}`);
    }
    if (!/No limit/.test(b.scale) || b.max <= 100) note(where, 'the budget slider offers no "No limit" past 100%');
    if (b.sentences > 2) note(where, `the budget line runs to ${b.sentences} sentences`);

    await slide(b.max);
    await page.waitForFunction(() => /No limit/.test(
      document.querySelector('#setBudgetVal').textContent), null, { timeout: 4000 });
    await page.waitForTimeout(200);
    b = await budget();
    if (!b.put || b.put.budget_no_limit !== true || 'budget_percent' in b.put) {
      note(where, `choosing No limit saved ${JSON.stringify(b.put)}`);
    }
    if (!/No limit: run until Anthropic rate-limits/.test(b.label)) note(where, `No limit is labelled "${b.label}"`);
    if (!/No limit/.test(b.valuetext)) note(where, `the slider announces "${b.valuetext}"`);
    // #555: the label says "until Anthropic rate-limits"; the line says
    // what follows, not that again.
    if (!/keep going/.test(b.note) || !/pause/.test(b.note) || /rate-limit/.test(b.note)) note(where, `No limit's line does not say it keeps going and then pauses, once: "${b.note}"`);
    if (!b.markHidden) note(where, 'a budget mark is still drawn with No limit chosen');
    if (b.sentences > 2) note(where, `the No limit line runs to ${b.sentences} sentences`);

    await page.evaluate(async () => {
      window.__rateLimitedUntil = Math.floor(Date.now() / 1000) + 3600;
      renderSettingsForm(await api('api/settings'));
    });
    b = await budget();
    if (!/Paused/.test(b.note) || !/until \d/.test(b.note)) note(where, `a rate-limit pause is not said with its end: "${b.note}"`);
    await page.evaluate(() => { window.__rateLimitedUntil = null; });

    await slide(100);
    await page.waitForFunction(() => /up to 100%/.test(
      document.querySelector('#setBudgetVal').textContent), null, { timeout: 4000 });
    await page.waitForTimeout(200);
    b = await budget();
    if (!b.put || b.put.budget_percent !== 100 || b.put.budget_no_limit !== false) {
      note(where, `going back to 100% saved ${JSON.stringify(b.put)}`);
    }
    if (/100%/.test(b.note) || !/wait/.test(b.note)) note(where, `at 100% the line under the budget says the limit again or not that they wait: "${b.note}"`);
    if (b.markHidden) note(where, 'the budget mark stayed hidden after a percentage was chosen');
    await slide(25);
    await page.waitForTimeout(200);
  } catch (e) {
    note(where, `driving the budget failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- the version in ⚙'s heading: a link to this release's changelog ----
  try {
    await page.waitForFunction(() => /2\.18\.5/.test(
      (document.querySelector('#versionChip') || {}).textContent || ''), null, { timeout: 4000 });
    const v = await page.evaluate(() => {
      const a = document.querySelector('#versionChip');
      const r = a.getBoundingClientRect();
      return { tag: a.tagName, text: a.textContent.replace(/\s+/g, ' ').trim(),
               href: a.getAttribute('href'), target: a.getAttribute('target'),
               rel: a.getAttribute('rel') || '', name: a.getAttribute('aria-label') || '',
               w: Math.round(r.width), h: Math.round(r.height),
               inBar: !!a.closest('.topbar'), inSettings: !!a.closest('#setModal .setpagehead'),
               shown: a.offsetParent !== null };
    });
    if (v.tag !== 'A') note(where, `the version is a <${v.tag}>, not a link`);
    if (!v.shown || !v.inSettings) note(where, 'the version is not in ⚙\'s heading');
    if (v.inBar) note(where, 'the version is still in the header');
    if (!/^v2\.18\.5$/.test(v.text)) note(where, `the version reads "${v.text}"`);
    if (v.href !== 'https://github.com/bruhautomation/BRUH-HA-Apps/blob/main/brain/CHANGELOG.md#2185') {
      note(where, `the version links to "${v.href}"`);
    }
    if (v.target !== '_blank' || !/noopener/.test(v.rel)) note(where, 'the changelog does not open in a new tab');
    if (!/2\.18\.5/.test(v.name) || !/changelog/i.test(v.name)) note(where, `the version's name is "${v.name}"`);
    if (touch && Math.min(v.w, v.h) < MIN_TARGET) note(where, `the version link is ${v.w}x${v.h}`);
    await page.evaluate(async () => { window.__restartPending = true; await refreshStatus(); });
    const rv = await page.evaluate(() => {
      const a = document.querySelector('#versionChip');
      return { text: a.textContent.replace(/\s+/g, ' ').trim(), title: a.getAttribute('title') || '',
               name: a.getAttribute('aria-label') || '' };
    });
    if (!/^v2\.18\.5 · restart needed$/.test(rv.text)) note(where, `a pending restart reads "${rv.text}"`);
    if (!/Restart Home Assistant/.test(rv.title) || !/Restart Home Assistant/.test(rv.name)) {
      note(where, `a pending restart is not named: "${rv.title}"`);
    }
    await page.evaluate(async () => { window.__restartPending = false; await refreshStatus(); });
  } catch (e) {
    note(where, `reading the version failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- What's new: the version opens the release notes in the panel -----
  // Read off the Supervisor (`/api/changelog`), newest first, the releases
  // since this browser last looked marked as new, a pending restart said,
  // and the published file as the fallback when the notes will not come.
  try {
    const open = async () => {
      await page.click('#versionChip');
      await page.waitForSelector('#whatsNewModal.open', { timeout: 4000 });
      await page.waitForFunction(() => !/Loading/.test(
        document.querySelector('#whatsNewBody').textContent), null, { timeout: 4000 });
    };
    const read = () => page.evaluate(() => {
      const box = document.querySelector('#whatsNewModal .box').getBoundingClientRect();
      const close = document.querySelector('#whatsNewClose').getBoundingClientRect();
      return {
        url: location.href,
        versions: [...document.querySelectorAll('#whatsNewBody .wnrel')].map((r) => r.dataset.version),
        fresh: [...document.querySelectorAll('#whatsNewBody .wnrel.new')].map((r) => r.dataset.version),
        newWords: [...document.querySelectorAll('#whatsNewBody .wnrel.new .wnnew')]
          .map((n) => n.textContent.trim()),
        bold: !!document.querySelector('#whatsNewBody .wnrel b'),
        restart: (document.querySelector('#whatsNewRestart') || { hidden: true }).hidden ? ''
          : document.querySelector('#whatsNewRestart').textContent,
        text: document.querySelector('#whatsNewBody').textContent.replace(/\s+/g, ' '),
        link: (() => { const a = document.querySelector('#whatsNewBody a.wnfallback');
          return a ? { href: a.getAttribute('href'), target: a.getAttribute('target') } : null; })(),
        right: box.right, vw: document.documentElement.clientWidth,
        closeH: Math.round(close.height), closeW: Math.round(close.width),
        sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    const shut = () => page.click('#whatsNewClose');
    await page.evaluate(() => { try { localStorage.setItem('brain.whatsnew.seen', '2.18.3'); } catch (e) { /* */ } });
    const before = page.url();
    await open();
    const w = await read();
    if (w.url !== before) note(where, 'the version left the panel instead of opening What\'s new');
    if (w.versions.join(',') !== '2.18.5,2.18.4,2.18.3') note(where, `What's new lists ${w.versions.join(',')}`);
    if (w.fresh.join(',') !== '2.18.5,2.18.4') note(where, `the new releases marked are ${w.fresh.join(',') || 'none'}`);
    if (!w.newWords.length || w.newWords.some((x) => !/new/i.test(x))) note(where, 'a new release is marked by colour alone');
    if (!w.bold) note(where, 'the notes are not rendered as markdown');
    if (w.restart) note(where, 'a restart is mentioned with none pending');
    if (w.right > w.vw + 0.5 || w.sideways) note(where, 'What\'s new is wider than the screen');
    if (touch && Math.min(w.closeH, w.closeW) < MIN_TARGET) note(where, `What's new's close is ${w.closeW}x${w.closeH}`);
    await shut();
    await open();
    const again = await read();
    if (again.fresh.length) note(where, `releases still marked new after reading them: ${again.fresh.join(',')}`);
    await shut();
    await page.evaluate(async () => { window.__restartPending = true; await refreshStatus(); });
    await open();
    const r = await read();
    if (!/restart/i.test(r.restart) || !/Home Assistant/.test(r.restart)) {
      note(where, `What's new does not say a restart is still owed ("${r.restart}")`);
    }
    await shut();
    await page.evaluate(async () => { window.__restartPending = false; await refreshStatus(); });
    await page.evaluate(() => { window.__changelogFails = true; });
    await open();
    const f = await read();
    if (!/did not answer/.test(f.text)) note(where, 'a release-notes failure is not said');
    if (!f.link || !/CHANGELOG\.md/.test(f.link.href) || f.link.target !== '_blank') {
      note(where, 'a release-notes failure offers no link to the published notes');
    }
    await shut();
    await page.evaluate(() => { window.__changelogFails = false; });
  } catch (e) {
    note(where, `driving What's new failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- search: words find a setting, and pressing it opens the section ---
  try {
    await page.click('#settingsBtn');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    const box = await page.evaluate(() => {
      const n = document.querySelector('#setSearch');
      const r = n ? n.getBoundingClientRect() : { top: 0, height: 0 };
      const list = document.querySelector('#setNav .setnavlist').getBoundingClientRect();
      return { shown: !!n && n.offsetParent !== null, above: r.top < list.top,
               h: Math.round(r.height), size: n ? parseFloat(getComputedStyle(n).fontSize) : 0 };
    });
    if (!box.shown || !box.above) note(where, 'there is no search box above the list');
    if (touch && box.size < MIN_TEXT) note(where, `the search box is ${box.size}px`);
    if (touch && box.h < MIN_TARGET) note(where, `the search box is ${box.h}px tall`);
    for (const [words, sec, target] of [['subscription', 'usage', 'setPlan'],
                                        ['say aloud', 'notifications', 'setSpeakFirst'],
                                        ['conversations running', 'permissions', 'setChatSessions'],
                                        // How Ask opens: the face a person switches, found by
                                        // either word they would type for it.
                                        ['terminal', 'permissions', 'setTerminalUi'],
                                        ['chat', 'permissions', 'setTerminalUi']]) {
      await page.fill('#setSearch', words);
      const hits = await page.evaluate(() => [...document.querySelectorAll('#setSearchResults .setresult')]
        .filter((b) => b.offsetParent !== null).map((b) => ({ text: b.textContent, sec: b.dataset.sec,
          h: Math.round(b.getBoundingClientRect().height) })));
      if (!hits.length) { note(where, `searching "${words}" found nothing`); continue; }
      if (hits[0].sec !== sec) note(where, `searching "${words}" first finds ${hits[0].sec}: "${hits[0].text}"`);
      if (touch && hits.some((h) => h.h < MIN_TARGET)) note(where, `a search result is under ${MIN_TARGET}px`);
      await page.click('#setSearchResults .setresult');
      await page.waitForFunction((s) => !document.querySelector(`#setModal .setsec[data-sec="${s}"]`).hidden,
        sec, { timeout: 3000 });
      const landed = await page.evaluate((id) => {
        const n = document.getElementById(id);
        const r = n.getBoundingClientRect();
        return { inView: r.bottom > 0 && r.top < window.innerHeight,
                 flashed: !!document.querySelector('#setModal .setflash')
                   && document.querySelector('#setModal .setflash').contains(n) };
      }, target);
      if (!landed.inView) note(where, `searching "${words}" did not bring #${target} into view`);
      if (!landed.flashed) note(where, `searching "${words}" did not mark #${target}`);
      if (narrow) await page.locator('#setModal .setsec:not([hidden]) .setback').click();
    }
    await page.fill('#setSearch', 'zzqx nothing like this');
    const none = await page.evaluate(() => document.querySelector('#setSearchResults').textContent);
    if (!/No setting matches/.test(none)) note(where, `an empty search says "${none.trim()}"`);
    await page.fill('#setSearch', '');
    const back = await page.evaluate(() => document.querySelectorAll('#setNav .setnavbtn:not([hidden])').length
      === [...document.querySelectorAll('#setNav .setnavbtn:not([hidden])')].filter((b) => b.offsetParent !== null).length);
    if (!back) note(where, 'clearing the search did not bring the list back');
  } catch (e) {
    note(where, `driving the search failed: ${String(e.message).split('\n')[0]}`);
  }

  await showSection(page, 'account');
  const acct = await page.evaluate(() => ({
    backupVisible: document.querySelector('#authShareCost').offsetParent !== null,
  }));
  m.backupVisible = acct.backupVisible;

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
  await showSection(page, 'notifications');
  const learned = await page.evaluate(() => {
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

  // ---- a date is a minute, not a second -----------------------------------
  const seconds = await page.evaluate(() =>
    (document.querySelector('#setModal').innerText.match(/\b\d{1,2}:\d{2}:\d{2}\b/g) || []));
  if (seconds.length) note(where, `a time is shown to the second: ${seconds.join(', ')}`);

  // ---- Memory moved to Knowledge: ⚙ has none, and its address goes there ---
  // The document, Edit, Export and the queue are measured where they live
  // now (measure-knowledge.mjs); what is asserted HERE is that ⚙ no longer
  // holds them and that the old way in still arrives somewhere.
  try {
    const before = await page.evaluate(
      () => window.__fetched.filter((u) => /api\/knowledge($|\?)/.test(u)).length);
    if (before) note(where, 'opening ⚙ read the memory');
    const left = await page.evaluate(() => ({
      row: !!document.querySelector('#setNav .setnavbtn[data-sec="memory"]'),
      sec: !!document.querySelector('#setModal .setsec[data-sec="memory"]'),
      ids: ['setMemView', 'setMemEdit', 'setMemExport', 'setMemQueue']
        .filter((id) => document.getElementById(id)),
    }));
    if (left.row || left.sec) note(where, '⚙ still has a Memory section');
    if (left.ids.length) note(where, `⚙'s memory controls are still on the page: ${left.ids.join(', ')}`);
    await page.evaluate(() => showSettingsSection('memory'));
    await page.waitForFunction(() => currentView === 'memory'
      && !document.querySelector('#kDocBody').hidden, null, { timeout: 4000 });
    await page.waitForFunction(() => /garage fridge/.test(document.querySelector('#kDocView').textContent),
      null, { timeout: 4000 });
    await page.evaluate(() => openSettings());
  } catch (e) {
    note(where, `⚙ › Memory's old address did not open the document: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Diagnostics is lazy, and opening it fills every block -------------
  try {
    const early = await page.evaluate(
      (urls) => window.__fetched.filter((u) => urls.some((x) => u.includes(x))), LAZY_URLS);
    if (early.length) {
      note(where, `opening ⚙ fetched ${early.length} Diagnostics read(s) before it was `
                  + `opened: ${[...new Set(early)].join(', ')}`);
    }
    await showSection(page, 'diagnostics');
    await page.waitForFunction(() => /12 records read/.test(
      document.querySelector('#diagOvernight').textContent), null, { timeout: 5000 });
    const late = await page.evaluate(
      (urls) => urls.filter((x) => !window.__fetched.some((u) => u.includes(x))), DIAG_URLS);
    if (late.length) note(where, `opening Diagnostics never fetched: ${late.join(', ')}`);
    const devEarly = await page.evaluate(
      (urls) => window.__fetched.filter((u) => urls.some((x) => u.includes(x))), DEV_URLS);
    if (devEarly.length) note(where, `Diagnostics fetched Developer's reads: ${devEarly.join(', ')}`);

    // Run all tests: first in the section, the answer as its header, a row
    // per stage in words with the reason and the time; skipped is skipped.
    await page.waitForSelector('#deepBody .testrow', { timeout: 4000 });
    const t = await page.evaluate(() => {
      const body = document.querySelector('#setsecDiagnostics .setsecbody');
      const first = body.firstElementChild;
      const run = document.querySelector('#deepRun');
      return {
        first: first ? first.id : '',
        heading: (document.querySelector('#deepBox .testsname') || {}).textContent || '',
        run: run.textContent.trim(), runLabel: run.getAttribute('aria-label'),
        runTop: Math.round(run.getBoundingClientRect().top - body.getBoundingClientRect().top),
        runH: Math.round(run.getBoundingClientRect().height),
        summary: document.querySelector('#deepSummary').textContent,
        summaryShown: !document.querySelector('#deepSummary').hidden,
        rows: [...document.querySelectorAll('#deepBody .testrow')].map((r) => ({
          cls: r.className,
          word: (r.querySelector('.testword') || {}).textContent || '',
          title: (r.querySelector('.testtitle') || {}).textContent || '',
          reason: (r.querySelector('.testreason') || {}).textContent || '',
          time: (r.querySelector('.testtime') || {}).textContent || '',
          right: r.getBoundingClientRect().right,
        })),
        bodyRight: body.getBoundingClientRect().right,
      };
    });
    if (t.first !== 'deepBox') note(where, `Diagnostics opens on "${t.first}", not Run all tests`);
    if (t.heading !== 'Run all tests' || t.runLabel !== 'Run all tests') {
      note(where, `the tests control reads "${t.heading}" / "${t.runLabel}"`);
    }
    if (t.runTop > 120) note(where, `Run all tests' button is ${t.runTop}px down the section`);
    if (touch && t.runH < MIN_TARGET) note(where, `Run all tests' button is ${t.runH}px`);
    if (t.summary !== '3 of 4 passed · 2 skipped' || !t.summaryShown) {
      note(where, `the tests header reads "${t.summary}"`);
    }
    if (t.rows.length !== 6) note(where, `${t.rows.length} test rows, not 6`);
    const words = t.rows.map((r) => r.word).join(',');
    if (words !== 'Passed,Passed,Failed,Passed,Skipped,Skipped') note(where, `the test rows say ${words}`);
    t.rows.forEach((r) => {
      if (!/\b\d{1,2}:\d{2}\b/.test(r.time)) note(where, `the "${r.title}" row has no time ("${r.time}")`);
      if (r.reason.length < 8) note(where, `the "${r.title}" row gives no reason`);
      if (r.right > t.bodyRight + 0.5) note(where, `the "${r.title}" row overflows`);
      if (r.word === 'Skipped' && /failed/.test(r.cls)) note(where, `a skipped row is drawn as failed: ${r.title}`);
    });
    if (!/Automation integration is off/.test(t.rows.map((r) => r.reason).join(' '))) {
      note(where, 'a skipped row does not say why in plain words');
    }
    const d = await page.evaluate(() => ({
      first: (document.querySelector('#diagBody .drow .dk') || {}).textContent || '',
      accuracy: document.querySelector('#diagAccuracy').textContent,
      // What a person reads without opening anything: the rows' text with
      // every closed technical part left out.
      ...(() => {
        const shown = (sel) => {
          const box = document.querySelector(sel).cloneNode(true);
          box.querySelectorAll('details').forEach((dd) => dd.remove());
          // Elements read side by side are words apart, as on the screen.
          box.querySelectorAll('*').forEach((n) => n.append(' '));
          return box.textContent.replace(/\s+/g, ' ');
        };
        const tech = (sel) => [...document.querySelectorAll(`${sel} details`)]
          .map((dd) => ({ open: dd.open, text: dd.textContent.replace(/\s+/g, ' ') }));
        return { faultText: shown('#diagBody'), faultTech: tech('#diagBody'),
                 accuracyShown: shown('#diagAccuracy'), accuracyTech: tech('#diagAccuracy'),
                 accuracyButtons: [...document.querySelectorAll('#diagAccuracy button')]
                   .map((b) => b.textContent.trim()) };
      })(),
      measures: document.querySelectorAll('#kStores .krow').length,
      measureText: document.querySelector('#diagMeasures').textContent,
      access: document.querySelector('#diagAccess').textContent,
      runs: !!document.querySelector('#diagRuns'),
      share: document.querySelector('#diagCopy').textContent.trim(),
      buttons: window.__visibleButtons(),
      hints: window.__hintSentences(),
      bubbles: document.querySelectorAll('#setModal .btn.icon.tiny').length,
    }));
    if (d.first !== 'Anything wrong?') note(where, `Diagnostics opens on "${d.first}"`);
    // The fault list in words: a job's name, a sentence, the ids folded.
    if (!/Filing facts into memory/.test(d.faultText)) note(where, 'a failed job is not named in words');
    for (const word of ['check:dev', 'Producer', 'Run (memory)', 'exited 1', 'crash']) {
      if (d.faultText.includes(word)) note(where, `the fault list shows "${word}" without a press`);
    }
    // The one vocabulary Needs you and History are held to (measure-today's
    // RAW_WORDS): no producer id and no machine word on the face.
    for (const [what, text] of [['fault list', d.faultText], ['scorecard', d.accuracyShown]]) {
      const raw = text.match(/check:[a-z]|\buser-\d|\bcustom-[a-z0-9]|\bProducer\b|\bRun \(/g);
      if (raw) note(where, `the ${what} shows ${[...new Set(raw)].join(', ')}`);
    }
    if (!d.faultTech.some((t) => /claude exited 1/.test(t.text) && !t.open)) {
      note(where, 'the exit code is not kept under a closed technical part');
    }
    if (!/Needs you/.test(d.faultText)) note(where, 'a rule with a question open does not point at it');
    // The scorecard: names, the count in words, a verdict, no bare ids.
    if (!/right 8 of 14, wrong 6/.test(d.accuracyShown)) note(where, 'the accuracy rows are missing');
    if (!/Laundry watch/.test(d.accuracyShown)) note(where, 'a card you made is not named');
    if (!/\btrusted\b/.test(d.accuracyShown) || !/\bdoubtful\b/.test(d.accuracyShown)) {
      note(where, 'the scorecard has no verdict words');
    }
    if (/user-\d|custom-\d|check:\S|\d+\/\d+/.test(d.accuracyShown)) {
      note(where, `the scorecard shows an id or a bare pair: "${d.accuracyShown.slice(0, 120)}"`);
    }
    if (!d.accuracyTech.some((t) => /check:forecast\.decline/.test(t.text))) {
      note(where, 'a rule\'s id is not kept under its row');
    }
    if (!d.accuracyButtons.includes('Ignore') || !d.accuracyButtons.includes('Restore')) {
      note(where, `the scorecard's presses are ${JSON.stringify(d.accuracyButtons)}`);
    }
    if (!/Automations that fight/.test(d.accuracy)) note(where, 'a muted producer is not listed');
    if (d.measures !== 7) note(where, `${d.measures} measurement rows, not 7`);
    if (!/4 of 10 days/.test(d.measureText)) note(where, 'a collecting measurement does not say how far');
    if (!/worth a PIN/.test(d.access)) note(where, 'the access review sentence is missing');
    if (d.runs) note(where, 'Runs is still in Diagnostics (it lives on Ask now)');
    if (d.share !== 'Share') note(where, `Export report's button says "${d.share}"`);
    for (const label of d.buttons) {
      if (!VERBS.has(label)) note(where, `a Diagnostics button says "${label}"`);
    }
    for (const h of d.hints) {
      if (h.sentences > 2) note(where, `a hint runs to ${h.sentences} sentences: "${h.text.slice(0, 70)}…"`);
    }
    if (d.bubbles) note(where, `${d.bubbles} "?" bubbles in Diagnostics`);

    // Report a problem: a ticked problem file is what Share copies.
    await page.waitForSelector('#probBody .probcheck', { timeout: 4000 });
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
    await page.evaluate(() => {
      const box = document.querySelector('.copyfallback, #copyFallback');
      if (box) box.remove();
    });
  } catch (e) {
    note(where, `driving Diagnostics failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Developer: its own section, read when it opens --------------------
  try {
    await showSection(page, 'developer');
    await page.waitForFunction((urls) => urls.every((x) => window.__fetched.some((u) => u.includes(x))),
      DEV_URLS, { timeout: 4000 }).catch(() => note(where, 'opening Developer did not read the rehearsal and captures'));
    const dv = await page.evaluate(() => ({
      buttons: window.__visibleButtons(),
      // The development loop's switch is in Features (brAIn 4.0); its
      // repository and streams stay here.
      shown: ['rehearseRun', 'setCapture', 'devloopOffNote'].filter(
        (id) => document.getElementById(id).closest('.setsec').hidden),
      bubbles: document.querySelectorAll('#setModal .btn.icon.tiny').length,
    }));
    if (dv.shown.length) note(where, `not in Developer: ${dv.shown.join(', ')}`);
    for (const label of dv.buttons) {
      if (!VERBS.has(label)) note(where, `a Developer button says "${label}"`);
    }
    if (dv.bubbles) note(where, `${dv.bubbles} "?" bubbles under Developer`);
    // #557: Diagnostics and Developer in plain words.
    await page.waitForSelector('#rehearseBody .drow', { timeout: 4000 }).catch(() => note(where, 'the last rehearsal\'s rows were not drawn'));
    for (const sec of ['developer', 'diagnostics']) {
      await showSection(page, sec);
      await page.waitForTimeout(300);
      const plain = await page.evaluate((x) => {
        const n = document.querySelector(`#setModal .setsec[data-sec="${x}"]`);
        // What a person reads: closed technical parts and tooltips aside.
        const text = n.innerText.replace(/\s+/g, ' ');
        const code = [...n.querySelectorAll('code')].filter((c) => c.offsetParent !== null && !c.closest('details:not([open])')).map((c) => c.textContent);
        return { text, code };
      }, sec);
      for (const [re, what] of [[/journal/i, 'a journal'], [/daemon/i, 'a daemon'], [/Configuration tab/i, 'the add-on\'s Configuration tab'],
        [/brain_test_/, 'a planted id'], [/\bauto\.dead_/, 'a check id'], [/\b[a-z]+_[a-z_]+ —/, 'a process name']]) {
        if (re.test(plain.text)) note(where, `${sec} says ${what}: "${(plain.text.match(new RegExp('.{0,40}' + re.source + '.{0,40}', re.flags)) || [''])[0]}"`);
      }
      if (plain.code.length) note(where, `${sec} shows code on its face: ${plain.code.join(', ')}`);
    }
    const rh = await page.evaluate(() => document.querySelector('#rehearseBody').innerText.replace(/\s+/g, ' '));
    if (!/An automation naming a light that does not exist/.test(rh) || !/Found/.test(rh) || !/Missed/.test(rh)) note(where, `the rehearsal's rows do not say what was planted and what happened: "${rh.slice(0, 160)}"`);
  } catch (e) {
    note(where, `driving Developer failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- #556: Permissions names each switch once, in plain words ---------
  try {
    await showSection(page, 'permissions');
    const pm = await page.evaluate(() => {
      const sec = document.querySelector('#setsecPermissions');
      const heads = [...sec.querySelectorAll('.sethead')].filter((n) => n.offsetParent !== null).map((n) => n.textContent.trim());
      const labels = [...sec.querySelectorAll('.bigcheck b')].map((n) => n.textContent.trim());
      const yolo = document.querySelector('#setYoloRow');
      return { text: sec.innerText, heads, labels,
               label: yolo ? yolo.querySelector('b').textContent.trim() : '',
               sub: yolo ? yolo.querySelector('.subtext').textContent.replace(/\s+/g, ' ').trim() : '' };
    });
    if (/YOLO/i.test(pm.text)) note(where, 'Permissions still says "YOLO"');
    const twice = pm.heads.filter((h) => pm.labels.some((l) => l.toLowerCase().includes(h.toLowerCase()) || h.toLowerCase().includes(l.toLowerCase())));
    if (twice.length) note(where, `Permissions says ${twice.join(', ')} as a heading and again as a switch`);
    if (!/^No restrictions$/.test(pm.label)) note(where, `the second switch reads "${pm.label}", not "No restrictions"`);
    if (!/without asking/.test(pm.sub)) note(where, `the second switch does not say how it differs from acting without asking: "${pm.sub}"`);
  } catch (e) {
    note(where, `driving Permissions' names failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- #555: no summary on the list is cut off ----------------------------
  try {
    if (narrow) await page.locator('#setModal .setsec:not([hidden]) .setback').click({ timeout: 3000 }).catch(() => {});
    const cut = await page.evaluate(() => [...document.querySelectorAll('#setNav .setnavsum')]
      .filter((n) => n.offsetParent !== null && (n.scrollWidth > n.clientWidth + 1 || getComputedStyle(n).textOverflow === 'ellipsis'))
      .map((n) => n.textContent.trim()));
    if (cut.length) note(where, `cut off on the list: ${cut.join(' | ')}`);
  } catch (e) {
    note(where, `reading the list's summaries failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- every switch is a row: words on the left, the switch beside them ---
  try {
    for (const sec of ['account', 'usage', 'permissions', 'notifications', 'developer']) {
      await showSection(page, sec);
      if (sec === 'developer') {
        await page.evaluate(() => { document.querySelector('#devloopBody').hidden = false; });
      }
      const rows = await page.evaluate(() => [...document.querySelectorAll(
        '#setModal .setsec:not([hidden]) input[type="checkbox"]')]
        .filter((i) => i.offsetParent !== null && !i.closest('#setCameras, #setCalendars, #probBody'))
        .map((i) => {
          const label = i.closest('label');
          const lr = label.getBoundingClientRect();
          const ir = i.getBoundingClientRect();
          const words = [...label.children].filter((c) => c !== i);
          const textRight = Math.max(...words.map((c) => c.getBoundingClientRect().right));
          const textLeft = Math.min(...words.map((c) => c.getBoundingClientRect().left));
          return { id: i.id || i.dataset.devStream || '?', rowW: Math.round(ir.right - lr.left),
                   right: ir.left >= textRight - 0.5 && ir.left > textLeft,
                   grouped: !!i.closest('.setgroup'), h: Math.round(lr.height) };
        }));
      for (const r of rows) {
        if (!r.right) note(where, `${sec}: the switch #${r.id} is not to the right of its words`);
        if (!narrow && r.rowW > 640) note(where, `${sec}: #${r.id} sits ${r.rowW}px from its label`);
        if (!r.grouped) note(where, `${sec}: the switch #${r.id} is not in a group`);
        if (touch && r.h < MIN_TARGET) note(where, `${sec}: the #${r.id} row is ${r.h}px`);
      }
      if (sec === 'developer') {
        await page.evaluate(() => { document.querySelector('#devloopBody').hidden = true; });
      }
    }
  } catch (e) {
    note(where, `measuring the switch rows failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- the page remembers its section, and ⚙ is the way back -------------
  try {
    await showSection(page, 'permissions');
    await page.click('#settingsBtn');          // ⚙ again leaves Settings
    const left = await page.evaluate(() => ({
      open: document.querySelector('#setModal').classList.contains('open'),
      view: document.querySelector('#viewSettings').classList.contains('active'),
    }));
    if (left.open || left.view) note(where, 'pressing ⚙ on Settings did not go back');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    // A wide page brings back the section that was in front; a phone opens
    // on the list every time, where every section is one press away.
    const front = () => page.evaluate(() => ({
      perms: !document.querySelector('#setsecPermissions').hidden,
      index: document.querySelector('#setModal').classList.contains('setindex')
        && document.querySelector('#setNav').offsetParent !== null
        && [...document.querySelectorAll('#setModal .setsec')].every((x) => x.hidden),
    }));
    let st = await front();
    if (narrow ? !st.index : !st.perms) {
      note(where, narrow ? 'coming back to Settings on a phone did not open on the list'
                        : 'coming back to Settings forgot the section that was in front');
    }
    await page.reload();
    await page.waitForSelector('#settingsBtn');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    st = await front();
    if (narrow ? !st.index : !st.perms) {
      note(where, narrow ? 'a reload did not open Settings on the list'
                        : 'a reload forgot the section that was in front');
    }
    if (narrow) {
      await showSection(page, 'permissions');
      await page.click('#setsecPermissions .setback');
      st = await front();
      if (!st.index) note(where, '"‹ Settings" did not go back to the list');
      await showSection(page, 'permissions');
    }
    // Permissions read the house rules when it was put in front.
    await page.waitForFunction(() => /heating above 23/.test(
      document.querySelector('#setHouseRules').value), null, { timeout: 4000 })
      .catch(() => note(where, 'the house rules were not read into Permissions'));
    const early = await page.evaluate(
      (urls) => window.__fetched.filter((u) => urls.some((x) => u.includes(x))), LAZY_URLS);
    if (early.length) note(where, `Settings on Permissions fetched Diagnostics reads: ${early.join(', ')}`);
    await showSection(page, 'diagnostics');
    await page.reload();
    await page.waitForSelector('#settingsBtn');
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open');
    if (narrow) await showSection(page, 'diagnostics');
    if (!await page.evaluate(() => !document.querySelector('#setsecDiagnostics').hidden)) {
      note(where, 'Diagnostics was not in front again after a reload');
    }
    await page.waitForFunction(() => window.__fetched.some((u) => u.includes('api/diagnostics')),
      null, { timeout: 4000 }).catch(() => note(where, 'a remembered Diagnostics fetched nothing on reopen'));
    // Each daemon gets a word, and a stopped one the reason: off because the
    // switch is off, or stopped when it should be running.
    await page.waitForSelector('#diagBody .drow', { timeout: 4000 }).catch(() => {});
    const diag = await page.evaluate(() => document.getElementById('diagBody').textContent.replace(/\s+/g, ' '));
    // #557: each by what it does, never its process name or an option key.
    if (!/The usage tracker — running/.test(diag)) note(where, 'a running background job is not said to be running');
    if (!/The voice listener — off — fast mode/.test(diag)) note(where, 'a background job that is off does not say why');
    if (!/The terminal — off — its switch is off/.test(diag)) note(where, 'a background job behind a switch that is off does not say so');
    if (!/The automation listener — stopped — it should be running/.test(diag)) note(where, 'a wanted background job that is down is not called stopped');
    if (!/One-time asks.*2 armed, 1 fired.*Each runs once, when what you described happens/.test(diag)) {
      note(where, 'one-off asks are not described as running once, when, and where the result goes');
    }
  } catch (e) {
    note(where, `driving the sections failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Sources: cameras and calendars, read when it opens ---------------
  try {
    const before = await page.evaluate(
      () => window.__fetched.filter((u) => u.includes('api/cameras') || u.includes('api/occasions')).length);
    if (before) note(where, 'opening ⚙ read the cameras or calendars before Sources was opened');
    await showSection(page, 'sources');
    await page.waitForSelector('#setCameras .setcam', { timeout: 5000 });
    await page.waitForSelector('#setCalendars input[data-cal]', { timeout: 5000 });
    const src = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#setCameras .setcam')];
      const note = document.querySelector('#setCalendarsNote');
      return {
        rows: rows.map((r) => ({ id: r.querySelector('input').dataset.entity,
          // The switch sits in the right-hand column, after the words.
          switchRight: r.querySelector('input').getBoundingClientRect().left
            >= r.querySelector('span').getBoundingClientRect().right - 0.5,
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
      if (!r.switchRight) note(where, `camera row ${i}'s switch is not to the right of its name`);
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
    await showSection(page, 'permissions');
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
      showSettingsSection('permissions');
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
    // Every select in the two sections that have them says its whole
    // choice, with no fold to open first.
    const cutIn = () => page.evaluate(() => {
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
    const cut = await cutIn();
    await showSection(page, 'usage');
    cut.push(...await cutIn());
    cut.filter((x) => !(touch && x.startsWith('#setModel '))).forEach(
      (c) => note(where, `a select cuts its text: ${c}`));
  } catch (e) {
    note(where, `driving the permission switch failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Personality: the persona as sections, one box to edit it ---------
  // It lives in brAIn now (it was Morph's). The owner: "the personality in
  // brAIn settings still looks clipped … bring back the rich formatting /
  // sections". So the stored outline reads as titled sections (Tagline,
  // Born, Who I am …), Edit turns them into the one box in the same place,
  // Save sends it, the growth log stays newest first and read-only, and a
  // persona the old 4,000 cap cut says so once.
  try {
    await showSection(page, 'personality');
    await page.waitForFunction(() => document.querySelector('#persName').value === 'Juniper'
      && document.querySelectorAll('#persSections .perssec').length > 0,
      null, { timeout: 4000 });
    const pers = await page.evaluate(() => {
      const shown = (n) => !!n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== 'hidden';
      const sec = document.querySelector('#setsecPersonality');
      return {
        text: document.querySelector('#persText').value,
        boxShown: shown(document.querySelector('#persText')),
        boxes: [...sec.querySelectorAll('textarea')].filter(shown).length,
        titles: [...document.querySelectorAll('#persSections .perssec .perssectitle')].map((x) => x.textContent.trim()),
        body: document.querySelector('#persSections').textContent,
        rawLabels: /(^|\n)\s*(line|born|who_i_am|name_why):/.test(document.querySelector('#persSections').innerText),
        cutNotes: [...sec.querySelectorAll('.perscut')].filter(shown).length,
        row: (document.querySelector('#setSumPersonality') || {}).textContent || '',
        growth: [...document.querySelectorAll('#persGrowth .persline')].map((x) => x.textContent),
        font: parseFloat(getComputedStyle(document.querySelector('#persText')).fontSize),
        nameFont: parseFloat(getComputedStyle(document.querySelector('#persName')).fontSize),
        inputs: document.querySelectorAll('#persGrowth input, #persGrowth textarea, #persGrowth button').length,
        editH: Math.round((document.querySelector('#persEdit') || { getBoundingClientRect: () => ({ height: 0 }) }).getBoundingClientRect().height),
        saveH: Math.round(document.querySelector('#persSave').getBoundingClientRect().height),
        askH: Math.round(document.querySelector('#persAsk').getBoundingClientRect().height),
        sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });
    if (!/evening star/.test(pers.text)) note(where, `the persona box reads "${pers.text.slice(0, 60)}"`);
    if (pers.titles.join(' | ') !== PERSONA_TITLES.join(' | ')) {
      note(where, `the persona's sections are [${pers.titles.join(' | ')}], not [${PERSONA_TITLES.join(' | ')}]`);
    }
    if (pers.rawLabels) note(where, 'the sections show the outline\'s raw labels (line:, born:, …)');
    for (const words of ['The evening star of the house', 'a keeper of small routines', 'one sentence for what changed', 'Named for the star']) {
      if (!pers.body.includes(words)) note(where, `the sections leave out "${words}"`);
    }
    if (pers.boxShown || pers.boxes) note(where, 'the persona is a box beside its sections rather than sections with Edit');
    if (pers.cutNotes) note(where, 'a whole persona says it was cut off');
    if (/line:/.test(pers.row) || !/evening star/.test(pers.row)) note(where, `the Personality row reads "${pers.row}"`);
    if (pers.growth[0] !== 'Stopped announcing the heating twice.') {
      note(where, `the growth log is not newest first: ${pers.growth.join(' | ')}`);
    }
    if (pers.inputs) note(where, 'the growth log is editable');
    if (touch && (pers.saveH < MIN_TARGET || pers.askH < MIN_TARGET || pers.editH < MIN_TARGET)) {
      note(where, `Edit is ${pers.editH}px, Save ${pers.saveH}px and Ask ${pers.askH}px on a finger`);
    }
    if (pers.sideways) note(where, 'the Personality page scrolls sideways');
    // PERSONA_SHOT_DIR=<dir>: keep a picture of the sections, for a person to look at.
    if (process.env.PERSONA_SHOT_DIR) await page.screenshot({ path: `${process.env.PERSONA_SHOT_DIR}/persona-${width}.png` });
    await page.click('#persEdit');
    const editing = await page.evaluate(() => {
      const shown = (n) => !!n && n.getClientRects().length > 0;
      const sec = document.querySelector('#setsecPersonality');
      return { box: shown(document.querySelector('#persText')), sections: shown(document.querySelector('#persSections')),
               boxes: [...sec.querySelectorAll('textarea')].filter(shown).length,
               font: parseFloat(getComputedStyle(document.querySelector('#persText')).fontSize),
               nameFont: parseFloat(getComputedStyle(document.querySelector('#persName')).fontSize) };
    });
    if (!editing.box || editing.sections || editing.boxes !== 1) {
      note(where, `Edit did not put the one box where the sections were (box ${editing.box}, sections ${editing.sections}, ${editing.boxes} boxes)`);
    }
    if (touch && (editing.font < 16 || editing.nameFont < 16)) {
      note(where, `the personality fields are ${editing.nameFont}px / ${editing.font}px on a finger`);
    }
    await page.fill('#persText', 'line: Warmer, and brief.');
    await page.click('#persSave');
    await page.waitForFunction(() => (window.__personaPuts || []).length === 1, null, { timeout: 4000 });
    const sent = await page.evaluate(() => window.__personaPuts[0]);
    if (sent.persona !== 'line: Warmer, and brief.' || sent.name !== 'Juniper') {
      note(where, `Save sent ${JSON.stringify(sent)}`);
    }
    await page.waitForFunction(() => document.querySelector('#persSections').getClientRects().length > 0
      && /Warmer, and brief/.test(document.querySelector('#persSections').textContent), null, { timeout: 4000 })
      .catch(() => note(where, 'after Save the page does not show the saved persona as sections'));
    const row = await page.evaluate(() => document.querySelector('#setSumPersonality').textContent);
    if (/line:/.test(row)) note(where, `after Save the Personality row reads "${row}"`);

    // A persona the old 4,000 cap cut: said once, and the paste offered.
    await page.evaluate(() => { window.__personaCut = true; });
    await page.evaluate(() => loadPersonality());
    await page.waitForFunction(() => document.querySelectorAll('#setsecPersonality .perscut').length > 0, null, { timeout: 4000 })
      .catch(() => {});
    const cut = await page.evaluate(() => {
      const shown = (n) => !!n && n.getClientRects().length > 0;
      const notes = [...document.querySelectorAll('#setsecPersonality .perscut')].filter(shown);
      const secs = document.querySelector('#persSections').textContent.trim();
      return { n: notes.length, words: notes.map((x) => x.textContent).join(' '), endsCut: secs.endsWith('…'),
               box: document.querySelector('#persText').value };
    });
    if (process.env.PERSONA_SHOT_DIR) await page.screenshot({ path: `${process.env.PERSONA_SHOT_DIR}/persona-cut-${width}.png`, fullPage: true });
    if (cut.n !== 1) note(where, `a persona cut at the old limit is said ${cut.n} times, not once`);
    else if (!/cut off/i.test(cut.words) || !/paste/i.test(cut.words)) note(where, `the cut-off note reads "${cut.words}"`);
    if (cut.endsCut) note(where, 'a persona cut at the old limit is shown ending in "…" as if whole');
    if (!cut.box.endsWith('…')) note(where, 'the stored text was changed rather than shown as it is');
    await page.evaluate(() => { window.__personaCut = false; });
  } catch (e) {
    note(where, `driving the personality failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Personality › How … is growing (the presence loop) -----------------
  // Its own notes are here and not in the growth list above (nothing twice),
  // every idea, note, retired kind and touch has its one press, every press
  // clears the touch floor on a finger, no person's id is in the words, and
  // a press sends the right request.
  try {
    await showSection(page, 'personality');
    await page.waitForFunction(() => document.querySelectorAll('#presBody .presrow').length > 0,
      null, { timeout: 4000 });
    const pres = await page.evaluate(() => {
      const box = document.querySelector('#presBody');
      const rows = [...box.querySelectorAll('.presrow')];
      return {
        head: document.querySelector('#presHead').textContent,
        what: document.querySelector('#presWhat').textContent,
        rows: rows.length,
        text: box.innerText,
        growth: [...document.querySelectorAll('#persGrowth .persline')].map((x) => x.textContent),
        buttons: [...box.querySelectorAll('button')].map((b) => ({
          // offsetHeight, not the rect: the section slides in under a
          // transform, and a rect read mid-slide is the button scaled.
          label: b.textContent, h: b.offsetHeight,
          right: Math.round(b.getBoundingClientRect().right) })),
        fonts: [...box.querySelectorAll('.presline, .pressub, .preshead')]
          .map((n) => parseFloat(getComputedStyle(n).fontSize)),
        sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
        // A full-page screenshot earlier in the run (PERSONA_SHOT_DIR) drops
        // the touch emulation; the finger check is only honest while it holds.
        coarse: matchMedia('(pointer: coarse)').matches,
      };
    });
    if (pres.head !== 'How Juniper is growing') note(where, `the presence heading reads "${pres.head}"`);
    if (!/one message a person a day/.test(pres.what)) note(where, `the presence line reads "${pres.what}"`);
    if (!pres.text.includes('Keeps evening messages to one line')) note(where, 'its own growth note is not under How … is growing');
    if (pres.growth.some((g) => /Keeps evening messages/.test(g))) note(where, 'its own growth note is listed twice');
    if (/person\.|[a-z_]+\.[a-z0-9_]{3,}/.test(pres.text)) note(where, 'an id is in the presence section\'s words');
    for (const words of ['the bins go out tonight', 'Likes a heads-up about the bins', 'Less like this: Morning check-in',
                         'Not now', 'Said aloud', 'Wren asked for the porch light']) {
      if (!pres.text.includes(words)) note(where, `the presence section leaves out "${words}"`);
    }
    const labels = new Set(pres.buttons.map((b) => b.label));
    for (const want of ['Remove', 'Skip', 'Never', 'Restore', 'Less like this']) {
      if (!labels.has(want)) note(where, `the presence section has no ${want}`);
    }
    if (touch && pres.coarse) {
      pres.buttons.filter((b) => b.h < MIN_TARGET)
        .forEach((b) => note(where, `the presence button "${b.label}" is ${b.h}px on a finger`));
    }
    pres.buttons.filter((b) => b.right > width + 1)
      .forEach((b) => note(where, `the presence button "${b.label}" runs off the page`));
    if (pres.fonts.some((f) => f < 12)) note(where, `presence text is ${Math.min(...pres.fonts)}px`);
    if (pres.sideways) note(where, 'the presence section scrolls the page sideways');
    // PRESENCE_SHOT_DIR=<dir>: pictures of the section (run it without
    // PERSONA_SHOT_DIR, whose full-page shot drops the touch emulation).
    if (process.env.PRESENCE_SHOT_DIR) {
      await page.locator('#presHead').evaluate((n) => n.scrollIntoView({ block: 'start' }));
      await page.screenshot({ path: `${process.env.PRESENCE_SHOT_DIR}/presence-${width}.png` });
      await page.locator('#presBody .presrow').last().evaluate((n) => n.scrollIntoView({ block: 'end' }));
      await page.screenshot({ path: `${process.env.PRESENCE_SHOT_DIR}/presence-${width}-end.png` });
    }
    await page.locator('#presBody button', { hasText: 'Skip' }).first().click();
    await page.waitForFunction(() => (window.__presencePosts || []).length > 0, null, { timeout: 4000 });
    const post = await page.evaluate(() => window.__presencePosts[0]);
    if (post.do !== 'skip' || post.person !== 'person.wren' || post.id !== 'a1b2') {
      note(where, `Skip sent ${JSON.stringify(post)}`);
    }
    await page.locator('#presBody button', { hasText: 'Less like this' }).first().click();
    await page.waitForFunction(() => (window.__presencePosts || []).length > 1, null, { timeout: 4000 });
    const less = await page.evaluate(() => window.__presencePosts[1]);
    if (less.do !== 'react' || less.reaction !== 'less' || less.id !== 'e5f6') {
      note(where, `Less like this sent ${JSON.stringify(less)}`);
    }
    await page.evaluate(() => { window.__presencePosts = []; });
  } catch (e) {
    note(where, `driving How … is growing failed: ${String(e.message).split('\n')[0]}`);
  }

  // ---- Guide: eight groups, and it opens the docs -------------------------
  try {
    await showSection(page, 'guide');
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
            + `(page height ${heights.join(', ')})`);
