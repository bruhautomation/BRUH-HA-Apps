// The visual standard, measured: docs/design/ui-redesign-2026-10.md,
// "Visual standard" — four type sizes, a 4px spacing grid, one card, no
// letter-spaced capitals and no browser chrome on a select or a checkbox.
//
// The design doc counted, on the shipped panel, 30-odd font sizes (9.5px to
// 30px, in px, rem and em), 22 distinct uppercase labels, 11 native selects,
// a native checkbox and finding cards with a coloured bar down the left.
// Every one of those is a property a browser computes and a stylesheet can
// only describe, so this drives the panel's REAL markup, stylesheet and
// renderers behind a stubbed fetch, opens every pane and the ⚙ dialog at a
// desktop and at a phone, and reads what was painted:
//
//   * every visible piece of text is 12, 14, 16 or 20px — the four sizes,
//     with 16 doubling as the touch floor. Help's own guide (#docsBody) is
//     prose with headings of its own and an insight card's chart is a
//     sandboxed frame the panel does not style, so both are left out;
//   * no visible label is set in capitals by the stylesheet, and none is
//     letter-spaced;
//   * every visible <select> carries `.sel` and has no browser appearance,
//     and every visible checkbox and slider has none either;
//   * a card's padding, and its direct children's, is on the 4px grid, its
//     radius is 12 and its left edge is the same width as its right — and
//     the boxes that sit on a page like a card (a notice, a plan, a
//     permission question, an activity row) have no coloured left bar
//     either.
//
// It runs headless against static files, like every measure beside it.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const NOW = Math.floor(Date.now() / 1000);

const SIZES = [12, 14, 16, 20];
const GRID = 4;
const CARD_RADIUS = 12;
// Card-like boxes held to the edge rule (and only that rule).
const BOXES = ['.setup .notice', '.kstale', '.hint.warn', '.tnote', '.chatnotice',
               '.permcard', '.chatres', '.chatfinding', '.findplan', '.ideasnote',
               '.actaway', '.actsum', '.actrow', '.properror'].join(', ');

const kase = (n, extra = {}) => ({
  id: `f:${n}`, kind: 'problem', claim: `Problem number ${n} in the house`,
  detail: 'Something worth a look. It has been like this since Tuesday.',
  confidence: 0.8, stakes: 'medium',
  evidence: [{ entity_id: 'sensor.kitchen', said: 'reads 4 °C' }], actions: [],
  status: 'open', source: 'check:dev.unavailable', source_title: 'Device check',
  ts: NOW - n * 60, origin: { store: 'findings', key: n }, memory_hint: '',
  investigation: null, ended: null, severity: n === 1 ? 'critical' : 'warning',
  entity_id: 'sensor.kitchen', entity_name: 'Kitchen sensor', area: 'Kitchen',
  fix: 'Check its power and its connection.', fix_by: '', fixable: n % 2 === 0,
  finding_status: 'open', plan: {}, triage: {}, snoozed_until: 0, overflow: [],
  answers: [], more: [], situation: 'generic', ...extra,
});

const insight = {
  id: 'energy', category: 'energy', title: 'Energy use this week',
  summary: 'The house used 12% less than last week. Most of it was the heat pump.',
  html: '<!doctype html><p>chart</p>', generated_at: new Date(NOW * 1000 - 3600e3).toISOString(),
  tags: ['energy'], highlights: [{ label: 'This week', value: '142 kWh', delta: '-12%' }],
  meta: {},
};

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/cases')) {
    return answer({ cases: ${JSON.stringify([1, 2, 3, 4].map((n) => kase(n)))}, names: {},
                    open: 4, ledger: {}, resident: {}, eventbus: {}, watching: 0 });
  }
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [],
                    scorecard: [], muted: [] });
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: { onboarded: true },
      usage: { five_hour: 42, seven_day: 17, source: 'account' },
      auto: { enabled: true }, jobs: {}, queue_size: 0,
      categories: [{ id: 'energy', title: 'Energy', icon: '⚡', description: '',
                     enabled: true, refresh_hold: null, next_due: ${NOW} + 4 * 3600 }],
      findings_open: 4,
      today: {
        checks: { last_at: ${NOW} - 600, ran: 45, created: 2, cleared: 1,
                  next_at: ${NOW} + 20000 },
        baselines: { built_at: ${NOW} - 30000 },
        memory: { last_filed_at: ${NOW} - 4000, waiting: 3 },
        claude_runs_24h: 73,
      },
    });
  }
  if (p.includes('api/onboarding')) return answer({ state: 'done', onboarded: true });
  if (p.includes('api/insights')) return answer({ insights: [${JSON.stringify(insight)}] });
  if (p.includes('api/todo')) {
    return answer({ items: [{ id: 1, text: 'Replace the hall smoke alarm battery',
                              detail: 'It reads 8%.', created_at: ${NOW} - 86400,
                              origin: 'finding' }],
                    done: [], open: 1, done_count: 0 });
  }
  if (p.includes('api/scenes/areas')) {
    return answer({ areas: [{ area: 'Lounge', lights: 4 }], min_lights: 2 });
  }
  if (p.includes('api/proposals')) return answer({ proposals: [], open: 0, rooms: [] });
  if (p.includes('api/ideas')) return answer({ ideas: [], state: {} });
  if (p.includes('api/settings')) {
    return answer({ settings: { auto_enabled: true, budget_pct: 25, model: '',
                                terminal_ui: 'chat', chat_max_sessions: 3 },
                    options: {}, models: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

// Everything on screen that the standard is about, read in one pass.
function readPage({ sizes, grid, radius, boxes: BOXES }) {
  const out = { sizes: [], upper: [], spaced: [], selects: [], boxes: [], cards: [], read: 0, picks: 0 };
  const visible = (n) => {
    if (!n.isConnected) return false;
    if (n.closest('#docsBody, .tipbox, [hidden], .hidden')) return false;
    if (typeof n.checkVisibility === 'function'
        && !n.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const label = (n) => {
    const id = n.id ? `#${n.id}` : '';
    const cls = typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).join('.') : '';
    return `${n.tagName.toLowerCase()}${id}${cls}`;
  };
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const text = t.textContent.trim();
    if (!text) continue;
    const host = t.parentElement;
    if (!host || seen.has(host) || ['SCRIPT', 'STYLE', 'OPTION', 'TEMPLATE'].includes(host.tagName)) continue;
    seen.add(host);
    if (!visible(host)) continue;
    out.read += 1;
    const cs = getComputedStyle(host);
    const px = Math.round(parseFloat(cs.fontSize) * 100) / 100;
    if (!sizes.includes(px)) out.sizes.push(`${label(host)} "${text.slice(0, 30)}" at ${px}px`);
    if (cs.textTransform === 'uppercase') out.upper.push(`${label(host)} "${text.slice(0, 30)}"`);
    const ls = parseFloat(cs.letterSpacing);
    if (cs.letterSpacing !== 'normal' && ls > 0.3) {
      out.spaced.push(`${label(host)} "${text.slice(0, 30)}" letter-spacing ${cs.letterSpacing}`);
    }
  }
  for (const c of document.querySelectorAll('input, textarea, select, button')) {
    if (!visible(c) || seen.has(c)) continue;
    if (['checkbox', 'radio', 'range', 'hidden'].includes(c.type)) continue;
    const px = Math.round(parseFloat(getComputedStyle(c).fontSize) * 100) / 100;
    if (!sizes.includes(px)) out.sizes.push(`${label(c)} control at ${px}px`);
  }
  for (const s of document.querySelectorAll('select')) {
    if (!visible(s)) continue;
    out.picks += 1;
    const cs = getComputedStyle(s);
    if (!s.classList.contains('sel') || cs.appearance !== 'none') {
      out.selects.push(`${label(s)} (appearance ${cs.appearance})`);
    }
  }
  for (const b of document.querySelectorAll('input[type="checkbox"], input[type="range"]')) {
    if (!visible(b)) continue;
    const cs = getComputedStyle(b);
    if (cs.appearance !== 'none') out.boxes.push(`${label(b)} (appearance ${cs.appearance})`);
  }
  const offGrid = (cs) => ['Top', 'Right', 'Bottom', 'Left']
    .map((k) => parseFloat(cs[`padding${k}`]))
    .filter((v) => Math.abs(v / grid - Math.round(v / grid)) > 0.01);
  for (const card of document.querySelectorAll('.card, .finding, .card-x')) {
    if (!visible(card)) continue;
    const cs = getComputedStyle(card);
    const bad = offGrid(cs);
    if (bad.length) out.cards.push(`${label(card)} padding ${cs.padding}`);
    if (parseFloat(cs.borderTopLeftRadius) !== radius) {
      out.cards.push(`${label(card)} radius ${cs.borderTopLeftRadius}`);
    }
    if (cs.borderLeftWidth !== cs.borderRightWidth || cs.borderLeftColor !== cs.borderRightColor) {
      out.cards.push(`${label(card)} has a left bar (${cs.borderLeftWidth} ${cs.borderLeftColor})`);
    }
    if (cs.boxShadow !== 'none') out.cards.push(`${label(card)} has a shadow`);
    for (const child of card.children) {
      if (!visible(child)) continue;
      const ccs = getComputedStyle(child);
      if (offGrid(ccs).length) out.cards.push(`${label(card)} > ${label(child)} padding ${ccs.padding}`);
    }
  }
  // Boxes that are not a card but sit on a page like one — a notice, a
  // plan, a permission question — take the same rule about the edge: one
  // edge all the way round, never a coloured bar down the left.
  for (const box of document.querySelectorAll(BOXES)) {
    if (!visible(box)) continue;
    const cs = getComputedStyle(box);
    if (cs.borderLeftWidth !== cs.borderRightWidth || cs.borderLeftColor !== cs.borderRightColor) {
      out.cards.push(`${label(box)} has a left bar (${cs.borderLeftWidth} ${cs.borderLeftColor})`);
    }
  }
  return out;
}

const totals = { screens: 0, text: 0, selects: 0 };
// A pane that painted nothing passes every check above, so each one has to
// have put some text on the screen for its silence to count.
const MIN_TEXT = 5;
async function check(page, where) {
  const r = await page.evaluate(readPage, { sizes: SIZES, grid: GRID, radius: CARD_RADIUS, boxes: BOXES });
  const uniq = (xs) => [...new Set(xs)];
  for (const s of uniq(r.sizes)) note(where, `text off the type scale: ${s}`);
  for (const s of uniq(r.upper)) note(where, `set in capitals: ${s}`);
  for (const s of uniq(r.spaced)) note(where, `letter-spaced: ${s}`);
  for (const s of uniq(r.selects)) note(where, `a native select: ${s}`);
  for (const s of uniq(r.boxes)) note(where, `a native control: ${s}`);
  for (const s of uniq(r.cards)) note(where, `card: ${s}`);
  if (r.read < MIN_TEXT) note(where, `only ${r.read} pieces of text were on screen — did it render?`);
  totals.screens += 1;
  totals.text += r.read;
  totals.selects += r.picks;
  if (process.env.TOKENS_VERBOSE) console.log(`${where}: ${r.read} text, ${r.picks} selects`);
}

const VIEWS = ['findings', 'insights', 'todo', 'ideas', 'proposals', 'terminal',
               'memory', 'activity', 'upkeep', 'docs'];

for (const [width, height, touch] of [[1200, 900, false], [390, 791, true]]) {
  const context = await browser.newContext({
    viewport: { width, height }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.waitForTimeout(300);
  for (const view of VIEWS) {
    const where = `${width}px ${view}`;
    try {
      await openView(page, view);
    } catch (e) {
      note(where, `could not open the pane: ${e.message.split('\n')[0]}`);
      continue;
    }
    await page.waitForTimeout(250);
    await check(page, where);
  }
  // ⚙, every section open.
  const where = `${width}px settings`;
  try {
    await page.click('#settingsBtn');
    await page.waitForSelector('#setModal.open', { timeout: 3000 });
    await page.evaluate(() => {
      for (const d of document.querySelectorAll('#setModal details')) d.open = true;
        for (const s of document.querySelectorAll('#setModal .setsec')) s.hidden = false;
    });
    await page.waitForTimeout(300);
    await check(page, where);
  } catch (e) {
    note(where, `could not open ⚙: ${e.message.split('\n')[0]}`);
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-tokens: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`measure-tokens: OK — ${totals.text} pieces of text on ${totals.screens} screens `
  + `on the type scale, ${totals.selects} selects all styled, no capitals, cards on the grid`);
