// Today, measured: the one screen for deciding (docs/design/
// ui-redesign-2026-10.md, "The first screen", PR 6).
//
// What it asserts is the screen's whole contract, against the panel's REAL
// renderers behind a stubbed fetch (measure-activity's rule — a copy of the
// renderer here would only ever agree with itself):
//
//   * no sub-tab bar on Today, and the tab is called Today;
//   * the first card's top is at most 240px down at 1190 and 360px at 390;
//   * the queue shows what fits — 3 cards on a desktop, 1 on a phone — and
//     "Show N more" reveals exactly the rest;
//   * every card carries ONE status chip from the four, at most one primary
//     button, labels from the action vocabulary only (no glyphs), Snooze
//     before Ignore wherever both are, a closed Details, and a body of at
//     most three lines;
//   * "What could go wrong" is on the face of every Apply card, and the
//     line saying what Undo puts back is on the face of an applied change;
//   * the cut text stays cut outside Details;
//   * the status line reads "Watching · last look 9 min ago" and its ⋯
//     holds Recheck and the morning brief;
//   * the safety banner shows only while something is urgent;
//   * the badge equals the counted cards;
//   * To Do hides a snoozed item, History opens on four filters with a
//     duplicate rendered once with its count, and Undo's confirmation says
//     what it puts back;
//   * the empty state is one line, "Nothing needs you.";
//   * a first-time owner sees the three-step setup card in place of the
//     queue;
//   * on touch every press is 44px, and nothing scrolls sideways.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stub, COUNTED, VOCAB, CUT } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const CASES = [
  { width: 390, touch: true, top: 360, fits: 1 },
  // 240 until the segmented control (Insights · Needs you · History) went
  // above the queue: the pane is one press in from the cards now.
  { width: 1190, touch: false, top: 290, fits: 3 },
];
const MIN_TARGET = 44;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

async function open(width, touch, over) {
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(stub(over));
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  // The panel lands on the insight cards; the queue is Insights › Needs you.
  await page.waitForFunction(() => typeof switchView === 'function');
  await page.evaluate(() => switchView('findings'));
  await page.waitForFunction(() => document.querySelector('#findList')
    && (document.querySelector('#findList .qcard')
        || document.querySelector('#findList .empty-line')
        || !document.querySelector('#todaySetup').hidden));
  return { page, context };
}

const readCards = (page, cut) => page.evaluate((cutSrc) => {
  const cut = cutSrc.map((s) => new RegExp(s.source, s.flags));
  const faceText = (el) => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll('details').forEach((d) => d.remove());
    return clone.textContent;
  };
  return [...document.querySelectorAll('#findList .qcard')].map((c) => {
    const body = c.querySelector(':scope > .card-body');
    const det = c.querySelector(':scope > details');
    const buttons = [...c.querySelectorAll(':scope > .card-actions button')];
    return {
      id: c.dataset.caseId || '',
      counted: c.dataset.counted === '1',
      chips: [...c.querySelectorAll('.chip-status')].map((x) => x.dataset.kind),
      chipWord: c.querySelector('.chip-status')?.textContent || '',
      title: c.querySelector('.card-title')?.textContent || '',
      top: Math.round(c.getBoundingClientRect().top),
      bodyLines: body ? Math.round(body.getBoundingClientRect().height
        / parseFloat(getComputedStyle(body).lineHeight)) : 0,
      detailsOpen: det ? det.open : null,
      detailsSummary: det ? det.querySelector('summary').textContent.trim() : '',
      buttons: buttons.map((b) => ({
        label: b.textContent.trim(), icon: b.classList.contains('icon'),
        primary: b.classList.contains('btn-primary'),
        h: Math.round(b.getBoundingClientRect().height),
        w: Math.round(b.getBoundingClientRect().width) })),
      apply: buttons.some((b) => b.textContent.trim() === 'Apply')
        && !!c.querySelector('.qplan'),
      riskOnFace: /What could go wrong/.test(faceText(c)),
      undoOnFace: /Undo puts the files back/.test(faceText(c)),
      cutHits: cut.filter((re) => re.test(faceText(c))).map((re) => String(re)),
      right: Math.round(c.getBoundingClientRect().right),
    };
  });
}, cut.map((re) => ({ source: re.source, flags: re.flags })));

for (const { width, touch, top, fits } of CASES) {
  const where = `${width}px`;
  const { page, context } = await open(width, touch);
  await page.waitForTimeout(300);

  const chrome = await page.evaluate(() => ({
    subtabs: !document.getElementById('subtabs').hidden,
    tab: document.querySelector('.viewtab[data-group="insights"] span')?.textContent || '',
    tabs: [...document.querySelectorAll('.viewtab')].map((b) =>
      b.querySelector('span:not(.badge)')?.textContent || ''),
    badge: document.getElementById('findBadge')?.textContent || '',
    status: document.getElementById('todayStatusText')?.textContent || '',
    banner: !document.getElementById('todayBanner').hidden,
    bannerText: document.getElementById('todayBanner').textContent,
    more: document.getElementById('todayMore'),
    moreText: document.getElementById('todayMore').hidden ? ''
      : document.getElementById('todayMore').textContent,
    setup: !document.getElementById('todaySetup').hidden,
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
    title: document.querySelector('#viewFindings h2.t-title, #viewFindings .findhead'),
  }));
  if (chrome.subtabs) note(where, 'Needs you shows a sub-tab bar');
  if (chrome.tab.trim() !== 'Insights') note(where, `the tab is "${chrome.tab}", not Insights`);
  if (chrome.tabs.join('|') !== 'Insights|Ask|Memory') {
    note(where, `the tabs are ${chrome.tabs.join(' | ')}`);
  }
  if (chrome.title) note(where, 'Today carries an intro heading');
  if (chrome.setup) note(where, 'the setup card shows over an established house');
  if (!/^Watching · last look 9 min ago$/.test(chrome.status.trim())) {
    note(where, `status line reads "${chrome.status}"`);
  }
  if (!chrome.banner || !/Kitchen Leak/.test(chrome.bannerText)) {
    note(where, `the urgent banner is missing or unnamed: "${chrome.bannerText}"`);
  }
  if (chrome.badge !== String(COUNTED)) {
    note(where, `badge ${chrome.badge} for ${COUNTED} counted cards`);
  }
  if (chrome.docWidth > chrome.viewport + 1) {
    note(where, `page scrolls sideways (${chrome.docWidth} > ${chrome.viewport})`);
  }

  let cards = await readCards(page, CUT);
  if (cards.length !== fits) note(where, `${cards.length} cards before Show more, not ${fits}`);
  if (cards.length && cards[0].top > top) {
    note(where, `the first card starts at ${cards[0].top}px (budget ${top})`);
  }
  const total = COUNTED + 1;   // the armed one-off is drawn and not counted
  if (chrome.moreText !== `Show ${total - fits} more`) {
    note(where, `"${chrome.moreText}" where "Show ${total - fits} more" was due`);
  }
  if (process.env.SHOT_DIR) {
    await page.screenshot({ path: path.join(process.env.SHOT_DIR, `today-${width}.png`),
                            fullPage: true });
  }
  await page.click('#todayMore');
  cards = await readCards(page, CUT);
  if (cards.length !== total) note(where, `${cards.length} cards after Show more, not ${total}`);
  if (cards.filter((c) => c.counted).length !== COUNTED) {
    note(where, `${cards.filter((c) => c.counted).length} counted cards, not ${COUNTED}`);
  }

  for (const card of cards) {
    const id = card.id || card.title.slice(0, 30);
    if (card.chips.length !== 1) note(where, `${id} carries ${card.chips.length} status chips`);
    if (!['urgent', 'problem', 'tidy', 'suggestion'].includes(card.chips[0])) {
      note(where, `${id} chip is "${card.chips[0]}"`);
    }
    if (!['Urgent', 'Problem', 'Tidy-up', 'Suggestion'].includes(card.chipWord)) {
      note(where, `${id} chip word "${card.chipWord}"`);
    }
    const presses = card.buttons.filter((b) => !b.icon);
    if (presses.filter((b) => b.primary).length > 1) note(where, `${id} has two primaries`);
    for (const b of presses) {
      if (!VOCAB.has(b.label)) note(where, `${id} button "${b.label}" is not in the vocabulary`);
      if (/^[^\w]/.test(b.label)) note(where, `${id} button "${b.label}" starts with a glyph`);
    }
    const labels = presses.map((b) => b.label);
    const s = labels.indexOf('Snooze');
    const i = labels.indexOf('Ignore');
    if (s >= 0 && i >= 0 && s > i) note(where, `${id} puts Ignore before Snooze`);
    if (card.detailsOpen === true) note(where, `${id} Details is open by default`);
    if (card.detailsOpen !== null && card.detailsSummary !== 'Details') {
      note(where, `${id} disclosure is "${card.detailsSummary}"`);
    }
    if (card.bodyLines > 3) note(where, `${id} body runs ${card.bodyLines} lines`);
    if (card.apply && !card.riskOnFace) {
      note(where, `${id} offers Apply with "What could go wrong" off its face`);
    }
    if (card.cutHits.length) note(where, `${id} carries cut text: ${card.cutHits.join(', ')}`);
    if (card.right > chrome.viewport + 1) note(where, `${id} overflows (${card.right})`);
    if (touch) {
      for (const b of card.buttons) {
        if (b.h < MIN_TARGET) note(where, `${id} "${b.label}" is ${b.h}px tall`);
      }
    }
  }
  const change = cards.find((c) => c.id === 'f:1104');
  if (!change || !change.undoOnFace) note(where, 'the applied change hides what Undo puts back');
  const legacy = await page.evaluate(() =>
    document.querySelector('[data-case-id="f:1106"] .qplanline')?.textContent || '');
  if (legacy.trim() !== 'This plan is out of date.') {
    note(where, `a legacy plan reads "${legacy}"`);
  }
  const refused = await page.evaluate(() =>
    document.querySelector('[data-case-id="f:1105"] .qplanline .qfixhead')?.textContent || '');
  if (refused !== "brAIn can't apply this") note(where, `a refused plan reads "${refused}"`);

  // The page's own text, outside every card's Details.
  const pageCut = await page.evaluate((cutSrc) => {
    const clone = document.getElementById('viewFindings').cloneNode(true);
    clone.querySelectorAll('details').forEach((d) => d.remove());
    clone.querySelectorAll('#setup, #onboard').forEach((d) => d.remove());
    const text = clone.textContent;
    return cutSrc.map((s) => new RegExp(s.source, s.flags)).filter((re) => re.test(text))
      .map(String);
  }, CUT.map((re) => ({ source: re.source, flags: re.flags })));
  if (pageCut.length) note(where, `Today carries cut text: ${pageCut.join(', ')}`);

  // The status line's menu. Scrolled to first: a scroll closes a popover,
  // and the click's own scroll-into-view would close this one.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  await page.click('#todayStatusMenuHost .btn.icon');
  const menu = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
    .map((b) => b.textContent));
  if (menu.join('|') !== "Recheck|Read this morning's brief") {
    note(where, `status menu holds ${menu.join(' | ')}`);
  }
  await page.click('#chipPop .cardmenuitem[data-i="1"]');
  const brief = await page.evaluate(() => !document.getElementById('todayBrief').hidden
    && document.getElementById('todayBrief').textContent);
  if (!brief || !/Quiet night/.test(brief)) note(where, 'the brief does not open');

  // Ignore on a mutable case opens the one optional question and the tick.
  await page.click('[data-case-id="f:1101"] .card-actions button:text-is("Ignore")');
  const form = await page.evaluate(() => {
    const f = document.querySelector('[data-case-id="f:1101"] .findnote');
    return f ? { hint: f.querySelector('.findnotehint')?.textContent || '',
                 check: f.querySelector('.findnotecheck')?.textContent || '' } : null;
  });
  if (!form) note(where, 'Ignore opens no reason box');
  else {
    if (form.hint !== 'Why? (helps brAIn learn)') note(where, `Ignore asks "${form.hint}"`);
    if (form.check !== 'Ignore all like this') note(where, `Ignore's tick reads "${form.check}"`);
  }

  // To Do.
  const list = await page.evaluate(() => ({
    rows: [...document.querySelectorAll('#todoList .todorow .todotitle')].map((t) => t.textContent),
    buttons: [...document.querySelectorAll('#todoList .todorow button:not(.icon)')]
      .map((b) => b.textContent.trim()),
    placeholder: document.getElementById('todoText').placeholder,
    addH: Math.round(document.querySelector('#todoAdd button').getBoundingClientRect().height),
  }));
  if (list.rows.some((r) => /snoozed chore/i.test(r))) note(where, 'a snoozed list item shows');
  if (list.rows.length !== 2) note(where, `${list.rows.length} list rows, not 2`);
  if (list.buttons.some((b) => b !== 'Done' && b !== 'Delete')) note(where, `list rows carry ${list.buttons.join(' | ')}`);
  if (list.placeholder !== 'Add to To Do…') note(where, `add box says "${list.placeholder}"`);
  if (touch && list.addH < MIN_TARGET) note(where, `Add to To Do is ${list.addH}px`);

  if (touch) {
    const small = await page.evaluate((min) => [...document.querySelectorAll(
      '#viewFindings button, #viewFindings summary')]
      .filter((b) => b.offsetParent !== null)
      .map((b) => ({ t: b.textContent.trim().slice(0, 24),
                     h: Math.round(b.getBoundingClientRect().height) }))
      .filter((b) => b.h < min), MIN_TARGET);
    if (small.length) note(where, `under the touch floor: ${JSON.stringify(small.slice(0, 6))}`);
  }

  // History is a pane of its own now (Insights › History): four filters,
  // grouped rows, Restore on each and Delete on every row but a snooze.
  const histOnToday = await page.evaluate(() => !!document.getElementById('todayHistory'));
  if (histOnToday) note(where, 'History is still a drawer on Needs you');
  await page.evaluate(() => switchView('archive'));
  await page.waitForSelector('#histFilters button');
  await page.click('#histFilters button[data-filter="snoozed"]');
  const hist = await page.evaluate(() => ({
    filters: [...document.querySelectorAll('#histFilters button')].map((b) =>
      b.querySelector('span').textContent),
    hint: document.getElementById('histHint').textContent,
    rows: [...document.querySelectorAll('#histList .histrow')].map((r) => ({
      title: r.querySelector('.histtitle').textContent,
      meta: r.querySelector('.item-state').textContent,
      press: r.querySelector('button').textContent,
      del: !!r.querySelector('.histdel') })),
  }));
  if (hist.filters.join('|') !== 'Snoozed|Ignored|Done|Set aside by brAIn') {
    note(where, `History filters: ${hist.filters.join(' | ')}`);
  }
  if (!hist.hint) note(where, 'History does not say what a filter holds');
  const cooling = hist.rows.filter((r) => /Cooling time/.test(r.title));
  if (cooling.length !== 1 || !/^6 times since/.test(cooling[0]?.meta || '')) {
    note(where, `the duplicate reads ${JSON.stringify(cooling)}`);
  }
  if (hist.rows.some((r) => r.press !== 'Restore')) note(where, 'a Snoozed row is not Restore');
  if (hist.rows.some((r) => r.del)) note(where, 'a Snoozed row offers Delete');
  await page.click('#histFilters button[data-filter="done"]');
  const doneDel = await page.evaluate(() => [...document.querySelectorAll(
    '#histList .histrow')].filter((r) => r.querySelector('.histdel')).length);
  if (!doneDel) note(where, 'no Done row offers Delete');
  let confirmText = '';
  page.once('dialog', (d) => { confirmText = d.message(); d.dismiss(); });
  await page.click('#histList .histrow button');
  await page.waitForTimeout(100);
  if (!/Puts back each field/.test(confirmText)) {
    note(where, `Undo confirms with "${confirmText}"`);
  }
  if (touch) {
    const small = await page.evaluate((min) => [...document.querySelectorAll(
      '#viewArchive button')]
      .filter((b) => b.offsetParent !== null)
      .map((b) => ({ t: b.textContent.trim().slice(0, 24),
                     h: Math.round(b.getBoundingClientRect().height),
                     w: Math.round(b.getBoundingClientRect().width) }))
      .filter((b) => b.h < min || b.w < min), MIN_TARGET);
    if (small.length) note(where, `History under the touch floor: ${JSON.stringify(small.slice(0, 6))}`);
  }
  await context.close();

  // The empty house: one line, no banner.
  {
    const { page: p2, context: c2 } = await open(width, touch, {
      cases: [], loose: [], proposals: [], intents: [], open: 0,
      extras: { tidy: null, updates: [] } });
    const empty = await p2.evaluate(() => ({
      lines: [...document.querySelectorAll('#findList > *')].map((e) => e.textContent),
      banner: !document.getElementById('todayBanner').hidden,
      more: !document.getElementById('todayMore').hidden,
    }));
    if (empty.lines.join('|') !== 'Nothing needs you.') {
      note(where, `empty queue reads ${JSON.stringify(empty.lines)}`);
    }
    if (empty.banner) note(where, 'the banner shows over an empty house');
    if (empty.more) note(where, '"Show more" shows over an empty queue');
    await c2.close();
  }

  // A first-time owner: the setup card stands in for the queue.
  {
    const { page: p3, context: c3 } = await open(width, touch, { firstLookDone: false });
    const setup = await p3.evaluate(() => ({
      shown: !document.getElementById('todaySetup').hidden,
      queue: !document.getElementById('findList').hidden,
      steps: [...document.querySelectorAll('#todaySetupSteps li > span:first-child')]
        .map((s) => s.textContent),
      running: document.querySelector('#todaySetupSteps li.now .item-state')?.textContent,
    }));
    if (!setup.shown) note(where, 'no setup card before the first look');
    if (setup.queue) note(where, 'the queue shows beside the setup card');
    if (setup.steps.join('|') !== 'Sign in|Choose what brAIn may change|First look') {
      note(where, `setup steps: ${setup.steps.join(' | ')}`);
    }
    if (setup.running !== 'Running') note(where, `the first look reads "${setup.running}"`);
    await c3.close();
  }
}

await browser.close();
if (failures.length) {
  console.error(`measure-today: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-today: ok');
