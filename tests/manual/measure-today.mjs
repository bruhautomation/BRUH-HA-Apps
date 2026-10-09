// Today, measured: the one screen for deciding (docs/design/
// ui-redesign-2026-10.md, "The first screen", PR 6).
//
// What it asserts is the screen's whole contract, against the panel's REAL
// renderers behind a stubbed fetch (measure-activity's rule — a copy of the
// renderer here would only ever agree with itself):
//
//   * no sub-tab bar on Today, and the tab is called Today;
//   * the first card's top is at most 240px down at 1190 and 360px at 390;
//   * the queue reads in groups — Problems, Questions, Chores and
//     suggestions, Tidy-ups — each a heading with its count, only the lead
//     one open by itself, and the problems worst first (urgent, then
//     serious, then the rest, a change brAIn made after the faults): a
//     serious fault sat seventh under a finished print and a mute question
//     on a real house;
//   * the lead group shows what fits — 3 cards on a desktop, 1 on a phone —
//     and "Show N more" reveals exactly the rest of it; opening the other
//     groups draws every card;
//   * a row no look has judged says "Unchecked" on its card and is counted
//     once, in one line at the top of the queue — never a stock "nothing
//     looked" sentence on each card, face or Details;
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
//   * on touch every press is 44px, and nothing scrolls sideways;
//   * History opens on ONE intro line — the filter's own — and not a
//     paragraph under the heading saying the same thing;
//   * a card is as tall as what it holds: a question's answers sit right
//     under it rather than on the floor of a row its neighbour set, and an
//     insight card carries no blank band above its foot — not from a
//     taller neighbour, not from a frame that drew nothing, and not from a
//     one-line frame held at a minimum height;
//   * an insight card and a finding about the same thing say so, each
//     with a link to the other.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stub, COUNTED, VOCAB, CUT, INSIGHTS, openEverything, FEED, LOOSE, kase, A, posts }
  from './today-fixture.mjs';
import { controlOverlaps } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const CASES = [
  { width: 390, touch: true, top: 360, fits: 1 },
  // 240 until the segmented control (Insights · Needs you · History) went
  // above the queue: the pane is one press in from the cards now. 290 until
  // the queue was read in groups: the first card now sits under the line
  // counting what no look has judged and the Problems heading (+56px). On
  // a phone the same two fit inside the 360 that was already there.
  { width: 1190, touch: false, top: 350, fits: 3 },
];
const MIN_TARGET = 44;
// What no screen a person reads may print: a producer's id (`check:…`,
// `user-…`, `custom-…`) or the machine's own words for itself.
const RAW_WORDS = /check:[a-z]|\buser-\d|\bcustom-[a-z0-9]|\bProducer\b|\bRun \(/;

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
  // The groups, before anything is opened: four headings in order, each
  // with its count, the lead one open and the rest closed.
  const groups = await page.evaluate(() => [...document.querySelectorAll(
    '#findList > .qgroup')].map((g) => ({
    group: g.dataset.group,
    name: g.querySelector('.qgroupname')?.textContent || '',
    count: Number(g.querySelector('.qgroupcount')?.textContent || 'NaN'),
    open: g.querySelector('.qgrouphead')?.getAttribute('aria-expanded') === 'true',
    h: Math.round(g.querySelector('.qgrouphead')?.getBoundingClientRect().height || 0),
  })));
  const names = groups.map((g) => g.name).join('|');
  if (names !== 'Problems|Questions|Chores and suggestions|Tidy-ups') {
    note(where, `the queue's groups read ${names || '(none)'}`);
  }
  if (groups.filter((g) => g.open).map((g) => g.group).join('|') !== 'problems') {
    note(where, `open groups: ${groups.filter((g) => g.open).map((g) => g.group).join(', ')}`);
  }
  if (groups.reduce((n, g) => n + g.count, 0) !== total) {
    note(where, `the group counts add to ${groups.reduce((n, g) => n + g.count, 0)}, not ${total}`);
  }
  if (touch) {
    for (const g of groups) if (g.h < MIN_TARGET) note(where, `the ${g.name} heading is ${g.h}px`);
  }
  const problems = groups.find((g) => g.group === 'problems')?.count || 0;
  if (chrome.moreText !== `Show ${problems - fits} more`) {
    note(where, `"${chrome.moreText}" where "Show ${problems - fits} more" was due`);
  }
  // One line at the top of the queue about the rows nothing has judged:
  // the serious fault the stale sweep showed, and the loose row still
  // waiting. Before it, every such card carried its own stock sentence.
  const waiting = await page.evaluate(() => [...document.querySelectorAll('#findList .qwaiting')]
    .map((n) => ({ text: n.textContent, first: n === document.querySelector('#findList').firstElementChild })));
  if (waiting.length !== 1 || !/^2 cards are waiting for brAIn's first look/.test(waiting[0].text)
      || !waiting[0].first) {
    note(where, `the waiting line reads ${JSON.stringify(waiting)}`);
  }
  await openEverything(page);
  cards = await readCards(page, CUT);
  if (cards.length !== total) note(where, `${cards.length} cards after Show more, not ${total}`);
  // No press sits on another, Details closed: a closed disclosure's "See
  // what it checked" was reported by the house's own photographs lying
  // over the card's and the To Do row's buttons.
  for (const o of await controlOverlaps(page, '#viewFindings')) note(where, `controls overlap: ${o}`);
  // One vocabulary: a producer is named in words, never by the id it was
  // filed under — Details and To Do included (textContent reads a closed
  // disclosure too).
  {
    const raw = await page.evaluate((src) => {
      const re = new RegExp(src, 'g');
      return document.getElementById('viewFindings').textContent.match(re) || [];
    }, RAW_WORDS.source);
    if (raw.length) note(where, `raw ids or machine words on Needs you: ${[...new Set(raw)].join(', ')}`);
  }
  if (process.env.SHOT_DIR) {
    await page.screenshot({ path: path.join(process.env.SHOT_DIR, `today-${width}-open.png`),
                            fullPage: true });
  }
  // The problems, worst first: urgent, then serious, then the rest, and
  // the change brAIn made after them. A chore never sits above a fault.
  const order = await page.evaluate(() => [...document.querySelectorAll(
    '#findList .qgroup[data-group="problems"] .qcard')].map((c) => c.dataset.caseId));
  const want = ['f:1100', 'f:1101', 'f:1109'];
  if (order.slice(0, 3).join('|') !== want.join('|')) {
    note(where, `problems open with ${order.slice(0, 3).join(', ')}, not ${want.join(', ')}`);
  }
  if (order[order.length - 1] !== 'f:1104') note(where, `the change is not last: ${order.join(', ')}`);
  const allIds = cards.map((c) => c.id);
  if (allIds.indexOf('f:1107') < allIds.indexOf('f:1109')) {
    note(where, 'the finished print sits above the serious fault');
  }
  // "Unchecked" on the card nothing judged, and no stock sentence on any
  // card, Details included.
  const unchecked = await page.evaluate(() => ({
    meta: [...document.querySelectorAll('[data-case-id="f:1109"] .meta .item-state')]
      .map((x) => x.textContent).join(' · '),
    loose: [...document.querySelectorAll('[data-case-id="f:2001"] .meta .item-state')]
      .map((x) => x.textContent).join(' · '),
    stock: [...document.querySelectorAll('#findList .qcard')].filter((c) =>
      /nothing finished looking|has not looked at this one|not looked at yet|not checked first|look at this one did not finish/i
        .test(c.textContent)).map((c) => c.dataset.caseId),
  }));
  if (!unchecked.meta.split(' · ').includes('Unchecked')) note(where, `f:1109 meta reads "${unchecked.meta}"`);
  if (!unchecked.loose.split(' · ').includes('Unchecked')) note(where, `f:2001 meta reads "${unchecked.loose}"`);
  if (unchecked.stock.length) note(where, `a stock "nothing looked" sentence on ${unchecked.stock.join(', ')}`);
  if (cards.filter((c) => c.counted).length !== COUNTED) {
    note(where, `${cards.filter((c) => c.counted).length} counted cards, not ${COUNTED}`);
  }

  for (const card of cards) {
    const id = card.id || card.title.slice(0, 30);
    if (card.chips.length !== 1) note(where, `${id} carries ${card.chips.length} status chips`);
    if (!['urgent', 'problem', 'tidy', 'suggestion', 'question'].includes(card.chips[0])) {
      note(where, `${id} chip is "${card.chips[0]}"`);
    }
    if (!['Urgent', 'Problem', 'Tidy-up', 'Suggestion', 'Question'].includes(card.chipWord)) {
      note(where, `${id} chip word "${card.chipWord}"`);
    }
    // A Yes / No / Snooze card is a question, and says so: it wore
    // "Suggestion" beside the proposals, which ask for an Apply.
    const isQuestion = card.buttons.some((b) => b.label === 'Yes')
      && card.buttons.some((b) => b.label === 'No');
    if (isQuestion && card.chipWord !== 'Question') {
      note(where, `${id} is a question wearing "${card.chipWord}"`);
    }
    if (!isQuestion && card.chipWord === 'Question') {
      note(where, `${id} wears "Question" and offers no Yes / No`);
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
  for (const f of ['snoozed', 'ignored', 'done', 'aside']) {
    await page.click(`#histFilters button[data-filter="${f}"]`);
    const raw = await page.evaluate((src) => document.getElementById('viewArchive')
      .textContent.match(new RegExp(src, 'g')) || [], RAW_WORDS.source);
    if (raw.length) note(where, `raw ids or machine words in History › ${f}: ${[...new Set(raw)].join(', ')}`);
  }
  await page.click('#histFilters button[data-filter="snoozed"]');
  // One intro line, the filter's own: a paragraph under the heading said
  // what History is and what Restore does, and the filter's line under the
  // search box said it again.
  const intro = await page.evaluate(() => [...document.querySelectorAll('#viewArchive .panesub')]
    .filter((n) => n.offsetParent && n.textContent.trim()).length);
  if (intro) note(where, 'History opens on two intro lines');
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

// A card is as tall as what it holds. At 1200 the queue and the insight
// grid are two columns, and every card used to be stretched to its row's
// tallest: a question's Yes/No/Snooze sat ~100px under its Details and a
// text-and-tiles report carried 250-450px of nothing above its foot. A
// report whose page drew nothing reserved the frame's 320px, and a page of
// one line was held at 120px, so even a phone had blank bands.
const BLANK_MAX = 28;
for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `${width}px cards`;
  const { page, context } = await open(width, touch, { insights: INSIGHTS });
  await openEverything(page);
  await page.waitForTimeout(300);
  const q = await page.evaluate(() => {
    const c = document.querySelector('[data-case-id="h:1103"]');
    if (!c) return null;
    const det = c.querySelector(':scope > details');
    const act = c.querySelector(':scope > .card-actions');
    return { gap: Math.round(act.getBoundingClientRect().top
      - (det || c.querySelector('.card-title')).getBoundingClientRect().bottom) };
  });
  if (!q) note(where, 'no question card');
  else if (q.gap > BLANK_MAX) note(where, `a question's answers sit ${q.gap}px under it`);
  // The finding names the card it came up on, and the link goes there.
  const from = await page.evaluate(() => {
    const x = document.querySelector('[data-case-id="f:1101"] .xlink');
    return x ? x.textContent.trim() : '';
  });
  if (!/^From The garage freezer is drifting warmer/.test(from)) {
    note(where, `the freezer finding links to its card as "${from}"`);
  }
  await page.evaluate(() => switchView('insights'));
  await page.waitForFunction(() => document.querySelectorAll('#grid .card').length === 3);
  // Each card in view in turn, so a lazy frame loads and reports its size.
  for (const id of ['custom-1', 'custom-2', 'custom-3']) {
    await page.evaluate((i) => document.querySelector(`#grid .card[data-id="${i}"]`)
      .scrollIntoView({ block: 'center' }), id);
    await page.waitForTimeout(700);
  }
  await page.waitForTimeout(600);
  const cards = await page.evaluate(() => [...document.querySelectorAll('#grid .card')].map((c) => {
    const foot = c.querySelector(':scope > .foot');
    const viz = c.querySelector(':scope > .viz');
    const vizH = viz && getComputedStyle(viz).display !== 'none'
      ? Math.round(viz.getBoundingClientRect().height) : 0;
    let bottom = 0;
    [...c.children].forEach((k) => {
      if (k === foot || k === viz) return;
      bottom = Math.max(bottom, k.getBoundingClientRect().bottom);
    });
    if (vizH) bottom = Math.max(bottom, viz.getBoundingClientRect().bottom);
    const x = c.querySelector('.xlink');
    return { id: c.dataset.id, vizH, gap: Math.round(foot.getBoundingClientRect().top - bottom),
             link: x ? x.textContent.trim() : '' };
  }));
  const by = Object.fromEntries(cards.map((c) => [c.id, c]));
  if (!(by['custom-1']?.vizH >= 200)) note(where, `the chart was not kept (${by['custom-1']?.vizH}px)`);
  if (by['custom-2']?.vizH) note(where, `a page that drew nothing still takes ${by['custom-2'].vizH}px`);
  if (!(by['custom-3']?.vizH > 0 && by['custom-3'].vizH <= 60)) {
    note(where, `a one-line page takes ${by['custom-3']?.vizH}px`);
  }
  for (const c of cards) {
    if (c.gap > BLANK_MAX) note(where, `${c.id} has ${c.gap}px of blank above its foot`);
  }
  if (!/^Also on Needs you: Garage Freezer has been six degrees warmer/.test(by['custom-1']?.link || '')) {
    note(where, `the freezer card links to its finding as "${by['custom-1']?.link}"`);
  }
  if (by['custom-3']?.link) note(where, `a card nothing else names links to "${by['custom-3'].link}"`);
  // Following the link lands on that finding.
  if (!await page.locator('#grid .card[data-id="custom-1"] .xlink a').count()) {
    await context.close();
    continue;
  }
  await page.click('#grid .card[data-id="custom-1"] .xlink a');
  await page.waitForTimeout(300);
  const landed = await page.evaluate(() => ({ view: currentView,
    shown: !!document.querySelector('[data-case-id="f:1101"]')?.offsetParent }));
  if (landed.view !== 'findings' || !landed.shown) note(where, `the link lands on ${JSON.stringify(landed)}`);
  await page.click('[data-case-id="f:1101"] .xlink a');
  await page.waitForTimeout(300);
  if (await page.evaluate(() => currentView) !== 'insights') note(where, 'the finding\'s link does not open the card');
  await context.close();
}

// A house-book gap question is answered on its card: a box and Send on the
// face, never a button that opens one, and the same on a row an older
// release left waiting for a look (report #166: "I can't actually answer
// it, there's no send"). What Send posts is the typed answer to the
// question's own route. And a card that says brAIn cannot do something
// offers "Report to brAIn" behind its ⋯ while the development loop is on,
// sent through the "What do you want to fix?" route.
const GAP = kase({
  id: 'f:1300', kind: 'question', chip: 'question', situation: 'gap',
  group: 'questions', severity: 'info', source: 'house_book',
  source_title: 'House book', origin: { store: 'findings', key: 1300 },
  claim: 'Where is the dryer vent booster blower, and can it be switched off by hand?',
  detail: 'About the dryer vent.', fix: 'Answer it here and the house book will say so.',
  answers: [
    A('answer', 'Send', '/api/house_book/question/1300/answer', { primary: true,
      note: true, done: 'Filed into memory for the house book',
      ask: 'Your answer goes into memory exactly as you write it.',
      placeholder: 'Behind the boiler, the red lever.' }),
    A('not_now', 'Snooze', '/api/case/f:1300/not_now'),
    A('wrong', 'Ignore', '/api/case/f:1300/wrong', { note: true })],
});
const CANT = kase({
  id: 'f:1301', situation: 'hands', origin: { store: 'findings', key: 1301 },
  claim: "brAIn can't turn the dryer booster off: it has no switch in Home Assistant",
  detail: 'It is on a plain plug.', source: 'resident', source_title: 'brAIn',
  answers: [A('todo', 'Add to To Do', '/api/case/f:1301/do', { primary: true }),
    A('not_now', 'Snooze', '/api/case/f:1301/not_now'),
    A('wrong', 'Ignore', '/api/case/f:1301/wrong', { note: true })],
  more: [{ verb: 'discuss', label: 'Ask', route: '/api/finding/1301/discuss', hint: 'Talk.' }],
});
const OLD_GAP = { ts: 2301, text: 'House book: Where is the stopcock?', severity: 'info',
  status: 'triaging', waiting_look: true, fixable: false, source: 'house_book',
  source_title: 'House book', detail: 'About the water main.',
  fix: 'Answer it here and the house book will say so.', triage: {}, snoozed_until: 0 };
for (const { width, touch } of [{ width: 390, touch: true }, { width: 1190, touch: false }]) {
  const where = `${width}px gap`;
  const { page, context } = await open(width, touch, {
    cases: [GAP, CANT, ...FEED], loose: [...LOOSE, OLD_GAP], devloop: true,
    open: COUNTED + 3 });
  await openEverything(page);
  const faces = await page.evaluate(() => ['f:1300', 'f:2301'].map((id) => {
    const c = document.querySelector(`[data-case-id="${id}"]`)
      || [...document.querySelectorAll('#findList .qcard')].find((x) => x.dataset.id === id);
    if (!c) return { id, found: false };
    const box = c.querySelector(':scope > .gapanswer textarea');
    const send = c.querySelector(':scope > .gapanswer button[data-verb="answer"]');
    const fs = box ? parseFloat(getComputedStyle(box).fontSize) : 0;
    return { id, found: true, box: !!box && !!box.offsetParent, send: !!send && !!send.offsetParent,
             disabled: send ? send.disabled : null, fs,
             sendH: send ? send.getBoundingClientRect().height : 0,
             todo: [...c.querySelectorAll('.card-actions button')].some((b) => /To Do/.test(b.textContent)),
             fixHead: !!c.querySelector(':scope > .qfix') };
  }));
  for (const f of faces) {
    if (!f.found) { note(where, `${f.id} is not on Today`); continue; }
    if (!f.box || !f.send) note(where, `${f.id} has no answer box and Send on its face`);
    if (f.disabled !== true) note(where, `${f.id}'s Send is pressable with nothing typed`);
    if (touch && f.fs < 16) note(where, `${f.id}'s answer box is ${f.fs}px on touch`);
    if (touch && f.sendH < MIN_TARGET) note(where, `${f.id}'s Send is ${f.sendH}px tall`);
    if (f.todo) note(where, `${f.id} offers Add to To Do for a question`);
    if (f.fixHead) note(where, `${f.id} shows a Fix block over a question`);
  }
  for (const [id, words] of [['f:1300', 'Behind the dryer, a wall switch.'],
                             ['f:2301', 'Under the sink.']]) {
    const sel = `[data-case-id="${id}"] .gapanswer`;
    if (!await page.locator(sel).count()) continue;
    await page.fill(`${sel} textarea`, words);
    await page.click(`${sel} button[data-verb="answer"]`);
    await page.waitForTimeout(200);
  }
  const sent = await posts(page);
  const want = { 'api/house_book/question/1300/answer': 'Behind the dryer, a wall switch.',
                 'api/house_book/question/2301/answer': 'Under the sink.' };
  for (const [url, note_] of Object.entries(want)) {
    const hit = sent.find((pp) => pp.url.endsWith(url));
    if (!hit || !hit.body || hit.body.note !== note_) {
      note(where, `Send did not post {note: "${note_}"} to ${url} (${JSON.stringify(hit)})`);
    }
  }
  // Report to brAIn, behind the ⋯ of the card that says brAIn can't.
  const menuBtn = page.locator('[data-case-id="f:1301"] .card-actions .btn.icon');
  if (!await menuBtn.count()) {
    note(where, 'the "can\'t" card has no ⋯');
  } else {
    await menuBtn.first().click();
    const items = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
      .map((b) => b.textContent));
    const i = items.indexOf('Report to brAIn');
    if (i < 0) note(where, `the "can't" card's ⋯ offers ${items.join(', ')}`);
    else {
      await page.evaluate((n) => document.querySelector(
        `#chipPop .cardmenuitem[data-i="${n}"]`).click(), i);
      await page.waitForTimeout(200);
      const look = (await posts(page)).find((pp) => pp.url.endsWith('api/devloop/look'));
      if (!look || !/dryer booster/.test(look.body?.topic || '')) {
        note(where, `Report to brAIn posted ${JSON.stringify(look)}`);
      }
    }
  }
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(`measure-today: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-today: ok');
