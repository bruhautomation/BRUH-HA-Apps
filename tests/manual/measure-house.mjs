// Render the Insights and Memory tabs and assert each is one control over
// its sections, and that Insights carries only insight cards.
//
// The three tabs are Insights · Ask · Memory. Two of them hold more than
// one pane and navigate on ONE segmented control (`#segNav`) under the bar:
//
//   * Insights — Insights · Needs you · History (#viewInsights,
//     #viewFindings, #viewArchive). The panel lands on the cards.
//   * Memory — Knowledge · Timeline · House book (#viewMemory,
//     #viewActivity, #viewHousebook).
//
// Buttons on a pointer and one styled select.sel on a phone, showing only
// the current tab's sections, and on no pane of Ask. The cards pane carries
// cards with a headline and "Updated N ago", the deep review and a
// Suggested row — and NOT the checks/memory/runs strip, the "problems since
// yesterday" press, a second ask box or the tag chips. A search field
// appears only past eight cards. Nothing scrolls sideways on a phone, and
// every control is a 44px target on a finger.
//
// It drives the panel's REAL renderers behind a stubbed fetch — a copy of
// the renderer here would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const MIN_TARGET = 44;
const NOW = Math.floor(Date.now() / 1000);
const ISO = new Date(Date.now() - 15 * 3600 * 1000).toISOString();

const GROUPS = {
  insights: [
    ['insights', 'Insights', 'viewInsights'],
    ['findings', 'Needs you', 'viewFindings'],
    ['archive', 'History', 'viewArchive'],
  ],
  memory: [
    ['memory', 'Knowledge', 'viewMemory'],
    ['activity', 'Timeline', 'viewActivity'],
    ['housebook', 'House book', 'viewHousebook'],
  ],
};
const SEGMENTS = GROUPS.insights;

const insight = (i) => ({
  id: `custom-${i}`, category: 'custom', title: `Report number ${i} about the house`,
  summary: i === 3 ? 'The freezer is fine.' : 'Nothing odd overnight.',
  highlights: [], html: '<p>chart</p>', generated_at: ISO,
  tags: ['energy', 'climate', 'doors', 'lights', 'heating', 'solar', 'water',
         'security', 'batteries', 'network', 'garden', 'kitchen', 'garage',
         'night', 'morning', 'weekend'],
  eyebrow: 'Energy and climate', question: 'How is the house?',
  made_because: 'you asked',
  meta: { duration_ms: 30000, cost: { total: 51400, input: 50000, output: 1400, cached: 0 } },
});

const stub = (count) => `
window.__insights = ${JSON.stringify(Array.from({ length: count }, (_, i) => insight(i + 1)))};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (b) => new Response(JSON.stringify(b), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/status')) {
    return answer({ version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
      today: { checks: { last_at: ${NOW} - 600, ran: 46, skipped: 0, errored: 0,
                         created: 0, cleared: 0, next_at: ${NOW} + 3600, running: false },
               memory: { last_filed_at: ${NOW} - 3600, waiting: 13, running: false },
               reports: { since_yesterday: 1 }, claude_runs_24h: 207 } });
  }
  if (p.includes('api/insights')) return answer({ insights: window.__insights });
  if (p.includes('api/ideas')) {
    return answer({ ideas: [{ id: 1, title: 'Heat pump against everything else',
      icon: '⚡', why: 'It is most of your winter usage.',
      question: 'What share went to heating?', status: 'open',
      added_at: ${NOW} - 3600 }], open: 1, running: false, runs: 2,
      last_run: ${NOW} - 86400, last_error: '', last_count: 1 });
  }
  if (p.includes('api/deep-review')) {
    return answer({ running: false, authenticated: true,
      estimate: { tokens: 167000, basis: 'what the last 1 review cost', percent: 11 },
      latest: { id: 1, at: ${NOW} - 86400, model: 'opus', tokens: 167000,
                summary: 'Mostly well set up.', observations: [] }, history: [] });
  }
  if (p.includes('api/facts/browse')) {
    return answer({ facts: [{ id: 'f1', text: 'The garage fridge runs all night.',
      subject: 'area:garage', source: 'correction', observed: '2026-09-12',
      run_id: '', run_source: '', predicate: '' }], total: 1, all: 1,
      facets: { kinds: { area: 1, entity: 0, house: 0 }, sources: {} } });
  }
  if (p.includes('api/house_book')) {
    return answer({ book: { at: ${NOW} - 7200, uncited: 0, sections: [
      { title: 'Heating', entries: [{ text: 'The heating comes on at six.',
        sources: [{ key: 'automation:x', label: 'Morning heat' }] }] }] },
      published: null, running: false });
  }
  if (p.includes('api/situation')) {
    return answer({ house_mode: 'asleep', sentence: 'Everyone is in.', frame: {} });
  }
  if (p.includes('api/activity')) {
    return answer({ available: true, sections: [{ id: 'lights', label: 'Lights',
      blurb: 'The bulk of what a house does.', total: 1, reads: 'span',
      episodes: [{ entity_id: 'light.kitchen', name: 'Kitchen light', started: ${NOW} - 600,
        ended: ${NOW} - 300, first: 'on', last: 'off', duration_s: 300, count: 1,
        cause: 'automation', by_name: 'Evening lights' }] }],
      away: [], counts: { automation: 1, person: 3 }, dropped: 0, changes: 1, episodes: 1 });
  }
  if (p.includes('api/findings')) return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  if (p.includes('api/onboarding')) return answer({ onboarded: true });
  return answer({});
};
`;

const failures = [];
const note = (where, m) => failures.push(`${where}: ${m}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

const open = async (width, touch, count) => {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(count));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await openView(page, 'insights');
  await page.waitForSelector('#grid .card', { timeout: 5000 })
    .catch(() => note(`${width}px`, 'no report rendered'));
  return { context, page };
};

const seg = (page) => page.evaluate(() => {
  const nav = document.getElementById('segNav');
  const box = (n) => n.getBoundingClientRect();
  const shown = (n) => !!n && getComputedStyle(n).display !== 'none' && box(n).height > 0;
  const btns = [...document.querySelectorAll('#segNav .segbtn')];
  const sel = document.getElementById('segNavSel');
  return {
    shown: shown(nav),
    buttons: btns.filter(shown).map((b) => ({
      label: (b.childNodes[0] || b).textContent.trim(), view: b.dataset.view,
      active: b.classList.contains('active'), h: Math.round(box(b).height) })),
    select: shown(sel) ? { value: sel.value, isSel: sel.classList.contains('sel'),
      h: Math.round(box(sel).height),
      options: [...sel.options].filter((o) => !o.hidden).map((o) => o.textContent.trim()) } : null,
    active: (document.querySelector('.view.active') || {}).id || '',
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
});

for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const at = `${width}px`;
  const { context, page } = await open(width, touch, 3);
  let s = await seg(page);
  if (!s.shown) note(at, 'the section control is not shown over the insight cards');
  const labels = SEGMENTS.map(([, l]) => l);
  if (touch) {
    if (!s.select || !s.select.isSel) note(at, 'a phone does not get one select.sel');
    else {
      if (JSON.stringify(s.select.options) !== JSON.stringify(labels)) {
        note(at, `the select offers ${JSON.stringify(s.select.options)}`);
      }
      if (s.select.h < MIN_TARGET) note(at, `the select is ${s.select.h}px tall`);
    }
    if (s.buttons.length) note(at, 'the segment buttons render beside the phone select');
  } else {
    if (JSON.stringify(s.buttons.map((b) => b.label)) !== JSON.stringify(labels)) {
      note(at, `the segments read ${JSON.stringify(s.buttons.map((b) => b.label))}`);
    }
    if (s.select) note(at, 'the phone select renders on a pointer');
  }

  // Reports: what it carries and what stays cut.
  const r = await page.evaluate(() => {
    const dash = document.getElementById('dash');
    const card = document.querySelector('#grid .card');
    return {
      text: dash ? dash.textContent : '',
      strip: !!document.getElementById('todayStrip'),
      askBox: !!document.getElementById('askForm'),
      chips: dash ? dash.querySelectorAll('.fchip, .tagchip').length : 0,
      search: !(document.getElementById('reportSearch') || {}).hidden,
      foot: card ? card.querySelector('.foot').textContent.replace(/\s+/g, ' ').trim() : '',
      ask: card ? [...card.querySelectorAll('.card-head .actions button')]
        .map((b) => ({ t: b.textContent.trim(), h: Math.round(b.getBoundingClientRect().height) })) : [],
      review: !!document.querySelector('#dash #kReview .kreviewrun'),
      suggested: !!document.querySelector('#dash #ideasRow #ideasList .finding'),
      rowButtons: [...document.querySelectorAll('#dash .reportrow button')]
        .filter((b) => b.offsetParent)
        .map((b) => ({ t: b.textContent.trim(), h: Math.round(b.getBoundingClientRect().height) })),
    };
  });
  for (const cut of [/Checks ran/, /Claude runs?/, /since yesterday/, /Every answer becomes a card/,
                     /tokens/i, /#energy/, /Make recurring/, /Analysed/]) {
    if (cut.test(r.text)) note(at, `cut text is back over the insight cards: ${cut}`);
  }
  if (r.strip) note(at, 'the checks/memory/runs strip is back over the insight cards');
  if (r.askBox) note(at, 'the second ask box is back over the insight cards');
  if (r.chips) note(at, `${r.chips} tag chips over the insight cards`);
  if (r.search) note(at, 'a search field shows over three reports');
  if (!/^Updated /.test(r.foot)) note(at, `a card's foot reads "${r.foot}"`);
  if (JSON.stringify(r.ask.map((b) => b.t)) !== JSON.stringify(['Ask', '⋯'])) {
    note(at, `a card's head carries ${JSON.stringify(r.ask.map((b) => b.t))}`);
  }
  if (!r.review) note(at, 'the deep review is not a row under the insight cards');
  if (!r.suggested) note(at, 'the Suggested row shows no idea');
  if (touch) {
    for (const b of [...r.ask, ...r.rowButtons]) {
      if (b.h < MIN_TARGET) note(at, `"${b.t}" is ${b.h}px tall on a finger`);
    }
  }
  if (s.docWidth > s.viewport + 1) note(at, `Insights scrolls sideways (${s.docWidth}px)`);

  // Every segment opens its own pane, and the control follows — and shows
  // only the sections of the tab it is on.
  for (const [group, segments] of Object.entries(GROUPS)) {
  await page.click(`.viewtab[data-group="${group}"]`);
  await page.waitForTimeout(250);
  s = await seg(page);
  const want = segments.map(([, l]) => l);
  const got = touch ? (s.select || {}).options || [] : s.buttons.map((b) => b.label);
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    note(at, `on ${group} the control offers ${JSON.stringify(got)}`);
  }
  for (const [view, label, id] of segments) {
    if (touch) await page.selectOption('#segNavSel', view);
    else await page.click(`#segNav .segbtn[data-view="${view}"]`);
    await page.waitForTimeout(250);
    s = await seg(page);
    if (s.active !== id) note(at, `${label} opened #${s.active}, not #${id}`);
    if (!s.shown) note(at, `the section control is gone on ${label}`);
    if (touch && s.select && s.select.value !== view) {
      note(at, `on ${label} the select reads "${s.select.value}"`);
    }
    if (!touch) {
      const on = s.buttons.filter((b) => b.active).map((b) => b.label);
      if (on.join() !== label) note(at, `on ${label} the lit segment is ${on.join() || 'none'}`);
    }
    if (s.docWidth > s.viewport + 1) note(at, `${label} scrolls sideways (${s.docWidth}px)`);
  }
  }
  // The Timeline's top line is the house's situation.
  await openView(page, 'activity');
  await page.waitForFunction(() => !document.getElementById('actNow')?.hidden, null,
    { timeout: 5000 }).catch(() => {});
  const top = await page.evaluate(() => (document.getElementById('actNow') || {}).textContent || '');
  if (!/^Settled for the night/.test(top)) note(at, `the Timeline opens on "${top}"`);

  // On Ask the control is not shown.
  await openView(page, 'terminal');
  await page.waitForTimeout(150);
  s = await seg(page);
  if (s.shown) note(at, 'the section control shows on Ask');
  console.log(`${failures.length ? 'ok? ' : 'ok  '}${String(width).padStart(5)}px  `
    + `${touch ? 'select' : 'segments'}, cards cut, six panes over two tabs`);
  await context.close();
}

// Past eight reports a search field appears, and it narrows the grid.
{
  const { context, page } = await open(1200, false, 10);
  const shown = await page.evaluate(() => !document.getElementById('reportSearch').hidden);
  if (!shown) note('search', 'no search field over ten cards');
  await page.fill('#reportSearch', 'freezer');
  await page.waitForTimeout(150);
  const n = await page.evaluate(() => document.querySelectorAll('#grid .card').length);
  if (n !== 1) note('search', `"freezer" left ${n} cards, not 1`);
  console.log(`${failures.length ? 'ok? ' : 'ok  '}  search: shown past eight, narrows to ${n}`);
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(`measure-house: ${failures.length} problem(s)\n`);
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('\nInsights and Memory are each one control over three panes, and the cards pane carries only cards');
