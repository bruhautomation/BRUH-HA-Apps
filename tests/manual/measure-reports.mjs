// House › Reports reads one verdict per card, one card per subject, and one
// line for every card that is all fine about nothing.
//
// A house's Reports pane had three failures reading could see and nothing
// measured: each card wrote its judgement into its prose a different way
// ("Verdict: normal.", "Needs action.", "Nothing to fix."), two cards told
// one heat pump's story with different numbers side by side, and four cards
// saying nothing had happened buried the one that needed action. So this
// drives the REAL `render()` (a copy of the renderer would only agree with
// itself) over the shapes `/api/insights` sends, and fails on:
//
//   * a card carrying more than one verdict chip, or a chip that is not one
//     of the three words, or a summary that LEADS with a verdict sentence
//   * a quiet card drawn as a card, or no "All quiet" line naming them all
//   * an older card the server marked `superseded_by` drawn as a card, or
//     the newer card without the line that opens it
//   * a quiet name under the 44px touch floor on a phone, a press on one
//     that opens nothing, or sideways scroll
//
// `PANEL_DIR` points it at another copy of the panel (the before shots).
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = process.env.PANEL_DIR
  || path.resolve(HERE, '..', '..', 'brain', 'panel');
const SHOTS = process.env.SHOTS_DIR || '';
const WIDTHS = [390, 1200];

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const answer = (b) => new Response(JSON.stringify(b),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  const p = String(url);
  if (p.includes('api/status')) {
    return answer({ version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0 });
  }
  if (p.includes('api/settings')) return answer({ settings: {}, usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

const NOW = new Date(Date.now() - 2 * 3600 * 1000).toISOString().slice(0, 19);
const OLDER = new Date(Date.now() - 30 * 3600 * 1000).toISOString().slice(0, 19);
const card = (id, title, summary, extra = {}) => ({
  id, category: 'custom', icon: '✨', category_title: 'Custom', question: null,
  title, summary, highlights: [], tags: [], html: '', generated_at: NOW,
  entities: [], ...extra,
});
// What /api/insights sends for one replayed house: one card with a real
// problem, four all-fine cards about nothing, and a heat pump told twice.
const SET = [
  card('custom-freezer', 'Garage freezer: 9 °F and rising',
    'It rose from 0 °F to 9 °F since 06:00; the door switch read closed.',
    { verdict: 'needs action',
      highlights: [{ label: 'Freezer', value: '9 °F', status: 'serious' }] }),
  card('custom-heat', 'Heat pump: 6 h of heating today',
    'Heat pump supply air held 41 °C through the morning.',
    { verdict: 'all fine', entities: ['sensor.heat_pump_supply'] }),
  card('custom-air', 'Air handler: 0 h by 13:11',
    'The air handler had not run by 13:11.',
    { verdict: 'all fine', generated_at: OLDER, superseded_by: 'custom-heat',
      entities: ['sensor.heat_pump_runtime'] }),
  card('custom-q1', 'Den cooling', 'No cooling since Sat 17 Oct.',
    { verdict: 'all fine', quiet: true }),
  card('custom-q2', 'Spare room heaters', 'Neither unit has run since Tue.',
    { verdict: 'all fine', quiet: true }),
  card('custom-q3', 'Dryer vent', 'The drum cleared in 41 min.',
    { verdict: 'all fine', quiet: true }),
  card('custom-q4', 'Garage door', 'Nothing changed since Mon.',
    { verdict: 'all fine', quiet: true }),
];
const QUIET = ['Den cooling', 'Spare room heaters', 'Dryer vent', 'Garage door'];
const VERDICTS = ['All fine', 'Worth a look', 'Needs action'];
const VERDICT_LEAD = /^(verdict:|needs action\b|all (fine|good|clear|normal)\b|normal\b|fine\b|nothing to (fix|do)\b|no action\b|this needs (one|a) (change|fix)\b|neither \w+ is broken\b|worth a look\b)/i;

const failures = [];
const note = (where, msg) => failures.push(`${where}: ${msg}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--no-sandbox'],
});

for (const width of WIDTHS) {
  const touch = width < 600;
  const context = await browser.newContext({
    viewport: { width, height: 1100 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  const at = (s) => `${width}px ${s}`;
  try {
    await page.waitForFunction(() => typeof render === 'function'
      && typeof switchView === 'function' && state.status, null, { timeout: 15000 });
  } catch (e) {
    note(at('panel'), 'the panel never booted');
    await context.close();
    continue;
  }
  await page.evaluate((set) => {
    switchView('insights');
    state.insights = set;
    state.cases = [];
    render();
  }, SET);
  await page.waitForTimeout(300);
  const m = await page.evaluate(() => {
    const grid = document.querySelector('#grid');
    const cards = [...grid.querySelectorAll('article.card')].map((c) => {
      const summary = c.querySelector('.summary');
      return {
        id: c.dataset.id,
        chips: [...c.querySelectorAll('.vchip')].map((x) => x.textContent.trim()),
        summary: summary ? summary.textContent.trim() : '',
        links: [...c.querySelectorAll('.xlink')].map((x) => x.textContent.trim()),
      };
    });
    const line = grid.querySelector('.quietline');
    const names = line ? [...line.querySelectorAll('.quietname')].map((b) => {
      const r = b.getBoundingClientRect();
      return { text: b.textContent.trim(), w: r.width, h: r.height };
    }) : [];
    return {
      cards, line: line ? line.textContent.trim() : null, names,
      docWidth: document.documentElement.scrollWidth,
    };
  });

  const ids = m.cards.map((c) => c.id);
  for (const want of ['custom-freezer', 'custom-heat']) {
    if (!ids.includes(want)) note(at('cards'), `${want} is not drawn`);
  }
  for (const folded of ['custom-air', 'custom-q1', 'custom-q2', 'custom-q3', 'custom-q4']) {
    if (ids.includes(folded)) note(at('cards'), `${folded} is drawn as a card of its own`);
  }
  for (const c of m.cards) {
    if (c.chips.length > 1) note(at(c.id), `carries ${c.chips.length} verdicts: ${c.chips.join(', ')}`);
    for (const chip of c.chips) {
      if (!VERDICTS.includes(chip)) note(at(c.id), `a verdict outside the three words: "${chip}"`);
    }
    if (VERDICT_LEAD.test(c.summary)) note(at(c.id), `summary leads with a verdict: "${c.summary}"`);
  }
  const freezer = m.cards.find((c) => c.id === 'custom-freezer');
  if (freezer && freezer.chips[0] !== 'Needs action') {
    note(at('custom-freezer'), `chip reads "${freezer.chips[0] || ''}"`);
  }
  const heat = m.cards.find((c) => c.id === 'custom-heat');
  if (heat && !heat.links.some((l) => /Earlier report on this/.test(l)
      && /Air handler/.test(l))) {
    note(at('custom-heat'), 'the older card about the heat pump is not folded under it');
  }
  if (!m.line || !/^All quiet:/.test(m.line)) {
    note(at('quiet'), 'no "All quiet" line');
  } else {
    const named = m.names.map((n) => n.text);
    for (const q of QUIET) if (!named.includes(q)) note(at('quiet'), `"${q}" is not named`);
  }
  if (touch) {
    for (const n of m.names) {
      if (n.h < 44) note(at('quiet'), `"${n.text}" is ${Math.round(n.h)}px tall, under 44`);
    }
  }
  if (m.docWidth > width + 0.5) note(at('page'), `scrolls sideways (${m.docWidth}px)`);

  // After the measuring: a full-page shot resizes the page for a moment,
  // and a target read during that is the shot's, not the panel's.
  if (SHOTS) {
    await page.screenshot({ path: path.join(SHOTS, `reports-${width}.png`), fullPage: true });
  }
  if (m.names.length) {
    await page.locator('.quietline .quietname').first().click();
    const open = await page.evaluate(() => !!document.querySelector('#modal.open'));
    if (!open) note(at('quiet'), 'pressing a quiet name opens nothing');
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-reports FAILED');
  failures.forEach((f) => console.error('  ' + f));
  process.exit(1);
}
console.log(`measure-reports: OK at ${WIDTHS.join(', ')}px — one verdict per`
  + ' card, one card per subject, and one line for the quiet ones');
