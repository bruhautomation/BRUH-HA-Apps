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
//     groups draws every card — except Questions for you, which shows ONE
//     question and a line saying how many follow;
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
//   * the badge equals the counted cards, and (#554) the badge, the line
//     over the insight cards, the section's own count and the groups'
//     counts are one number off one list: the armed one-off — drawn, and
//     not a decision — sits in its own "Set to run once" group with no
//     count, so the counts on the headings add up to the badge;
//   * every answerable card says who acts in ONE line under its title —
//     "brAIn can fix this." over Go ahead or Apply, "This needs you." over
//     Add to To Do or Done, "brAIn needs an answer." over Yes — never both
//     and never neither (#451);
//   * To Do hides a snoozed item, History opens on five filters with a
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
import { stub, COUNTED, VOCAB, CUT, INSIGHTS, openEverything, FEED, LOOSE, kase, A, posts,
  openToday } from './today-fixture.mjs';
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
        w: Math.round(b.getBoundingClientRect().width),
        t: Math.round(b.getBoundingClientRect().top) })),
      who: [...c.querySelectorAll(':scope > .qwho')].map((w) => ({
        line: w.textContent.trim(), kind: w.dataset.who || '' })),
      edge: parseFloat(getComputedStyle(c).borderLeftWidth) || 0,
      edgeColor: getComputedStyle(c).borderLeftColor,
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
    // The tabs on screen: Home is there only while the Morph dashboard is on.
    tabs: [...document.querySelectorAll('.viewtab')].filter((b) => !b.hidden).map((b) =>
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
  // One urgent case, and it is the first card on screen: the card already
  // says Urgent and names the problem, so a banner repeating it is the same
  // thing twice. (Structural assertion moved by this redesign: it used to
  // require the banner to name "Kitchen Leak".)
  if (chrome.banner) {
    note(where, `the banner repeats the leading urgent card: "${chrome.bannerText}"`);
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
  // (#554, a structural assertion this batch moved: the one-off used to sit
  // under Chores and suggestions and its heading counted it, so the groups
  // added to 16 under a badge of 15. It is a group of its own now, with no
  // count, and the counted headings add up to the badge.)
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
  if (names !== 'Problems|Questions for you|Chores and suggestions|Tidy-ups|Set to run once') {
    note(where, `the queue's groups read ${names || '(none)'}`);
  }
  if (groups.filter((g) => g.open).map((g) => g.group).join('|') !== 'problems') {
    note(where, `open groups: ${groups.filter((g) => g.open).map((g) => g.group).join(', ')}`);
  }
  const counted = groups.filter((g) => !Number.isNaN(g.count)).reduce((n, g) => n + g.count, 0);
  if (counted !== COUNTED) note(where, `the group counts add to ${counted}, not ${COUNTED}`);
  const waitingGroup = groups.find((g) => g.group === 'waiting');
  if (!waitingGroup || !Number.isNaN(waitingGroup.count)) note(where, `the armed one-off is not a group of its own without a count: ${JSON.stringify(waitingGroup)}`);
  // One list, one number: the tab's badge, the section's count and the
  // line over the insight cards all say what the headings add up to.
  {
    const nums = await page.evaluate(() => ({
      badge: document.getElementById('findBadge')?.textContent || '',
      seg: document.getElementById('segNeedsCount')?.textContent || '',
      strip: (document.getElementById('needsStripCount')?.textContent.match(/^(\d+)/) || [])[1] || '',
    }));
    for (const [k, v] of Object.entries(nums)) {
      if (v !== String(counted)) note(where, `the ${k} says ${v || 'nothing'} where the groups add to ${counted}`);
    }
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
  if (process.env.SHOTS_DIR) {
    await page.locator('#findList .qwaiting').first().scrollIntoViewIfNeeded().catch(() => {});
    await page.screenshot({ path: path.join(process.env.SHOTS_DIR, `needs-you-${width}-${process.env.SHOTS_TAG || 'after'}.png`) });
  }
  if (waiting.length !== 1 || !/^2 cards are waiting for brAIn's first look/.test(waiting[0].text)
      || !waiting[0].first) {
    note(where, `the waiting line reads ${JSON.stringify(waiting)}`);
  } else if (/[()]/.test(waiting[0].text)) {
    note(where, `the waiting line carries a bracketed label: ${waiting[0].text}`);
  }
  await openEverything(page);
  cards = await readCards(page, CUT);
  // Questions are asked one at a time: the group's heading counts them
  // all, its body holds the first and one line saying how many follow.
  const asked = groups.find((g) => g.group === 'questions')?.count || 0;
  const held = Math.max(0, asked - 1);
  if (cards.length !== total - held) {
    note(where, `${cards.length} cards after Show more, not ${total - held}`);
  }
  {
    const q = await page.evaluate(() => {
      const g = document.querySelector('#findList .qgroup[data-group="questions"]');
      return g ? { cards: g.querySelectorAll('.qcard').length,
                   next: g.querySelector('.qnextline')?.textContent || '' } : null;
    });
    const line = held === 1 ? '1 more question after this one.'
      : `${held} more questions after this one.`;
    if (!q) note(where, 'no Questions for you group');
    else if (q.cards !== 1) note(where, `${q.cards} question cards shown at once, not 1`);
    else if (held && q.next !== line) note(where, `the questions group says "${q.next}", not "${line}"`);
  }
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
  if (cards.filter((c) => c.counted).length !== COUNTED - held) {
    note(where, `${cards.filter((c) => c.counted).length} counted cards, not ${COUNTED - held}`);
  }

  for (const card of cards) {
    const id = card.id || card.title.slice(0, 30);
    // Who acts (#451): every answerable card says, in ONE line, whose move
    // it is, and its primary press is the one that line promises.
    const lead = card.buttons.find((b) => b.primary);
    if (lead) {
      if (card.who.length !== 1) {
        note(where, `${id} carries ${card.who.length} who-acts lines`);
      } else {
        const { line, kind } = card.who[0];
        const fits = { brain: ['Go ahead', 'Apply'], you: ['Add to To Do', 'Done'],
                       answer: ['Yes', 'Send'], told: ['Done', 'Restore'] }[kind];
        if (!fits) note(where, `${id} who-acts line is "${line}" (${kind})`);
        else if (!fits.includes(lead.label)) {
          note(where, `${id} says "${line}" over a primary "${lead.label}"`);
        }
        if (/can fix|can set/.test(line) && /needs you/.test(line)) {
          note(where, `${id} says both who acts: "${line}"`);
        }
      }
    }
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
    // "Sometimes the question it asks is irrelevant": every question card
    // offers Doesn't apply on its face, beside Yes and No.
    if (isQuestion && !card.buttons.some((b) => b.label === "Doesn't apply")) {
      note(where, `${id} is a question with no "Doesn't apply" on its face`);
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
    // One row of answers on a phone: a problem's row (primary, Check
    // again, Dismiss, Snooze, Ignore, ⋯) wrapped to two rows at 390, so one
    // urgent card filled the screen. Check again and Dismiss fold into the
    // ⋯ there; the primary, Snooze, Ignore and the ⋯ stay.
    if (width <= 640 && card.buttons.length) {
      const tops = new Set(card.buttons.map((b) => b.t));
      if (tops.size > 1) {
        note(where, `${id}'s answers wrap to ${tops.size} rows: ${presses.map((b) => b.label).join(' · ')}`);
      }
    }
  }
  // Urgent is set apart from the ordinary problems by more than its chip's
  // dot: a band down the card's leading edge, in the urgent colour.
  {
    const urgent = cards.find((c) => c.id === 'f:1100');
    const plain = cards.find((c) => c.id === 'f:1101');
    if (!urgent || urgent.edge < 3) note(where, `the urgent card has no leading band (${urgent?.edge}px)`);
    else if (plain && (plain.edge >= 3 && plain.edgeColor === urgent.edgeColor)) {
      note(where, 'an ordinary problem wears the urgent band');
    }
  }
  // At 390 the folded presses are still there, behind the ⋯ — Check
  // again first — and send what they sent from the row.
  if (width <= 640) {
    await page.evaluate(() => window.scrollTo(0, 0));
    const dots = page.locator('[data-case-id="f:1101"] .card-actions .btn.icon');
    if (!(await dots.count())) note(where, 'the freezer card has no ⋯');
    else {
      await dots.first().evaluate((b) => b.click());
      const items = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
        .map((b) => b.textContent));
      if (items[0] !== 'Check again' || items[1] !== 'Dismiss') {
        note(where, `the folded ⋯ holds ${items.join(' | ')}`);
      }
      if (items.length > 3) note(where, `the ⋯ holds ${items.length}`);
      const n = items.indexOf('Dismiss');
      if (n >= 0) {
        await page.evaluate((i) => document.querySelector(
          `#chipPop .cardmenuitem[data-i="${i}"]`).click(), n);
        await page.waitForTimeout(150);
        const sent = await posts(page);
        if (!sent.some((p) => /api\/finding\/1101$/.test(p.url) && p.method === 'DELETE')) {
          note(where, `the folded Dismiss sent ${JSON.stringify(sent.map((p) => p.url))}`);
        }
      }
      await page.keyboard.press('Escape');
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
  if (hist.filters.join('|') !== 'Snoozed|Ignored|Done|Set aside by brAIn|Changes brAIn made') {
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

  // Two urgent cases: the banner says a count and no title; one urgent case
  // that is not on screen is named, with a press to reach it.
  {
    const second = { ...FEED[0], id: 'f:1199', claim: 'sensor.cellar_leak is reporting water',
      entity_name: 'Cellar Leak', origin: { store: 'findings', key: 1199 } };
    const { page: p4, context: c4 } = await open(width, touch, {
      cases: [FEED[0], second, ...FEED.slice(1)] });
    const two = await p4.evaluate(() => ({
      shown: !document.getElementById('todayBanner').hidden,
      text: document.getElementById('todayBanner').textContent,
      press: !!document.querySelector('#todayBanner button'),
    }));
    if (!two.shown || !/2 urgent/.test(two.text) || /Leak/.test(two.text)) {
      note(where, `two urgent cases read "${two.text}" (shown ${two.shown})`);
    }
    if (!two.press) note(where, 'the urgent count has no press to reach the cards');
    await c4.close();
  }

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
  // A row about several things: a count line, and Show all opens every
  // one of them by name (#437).
  const list = await page.evaluate(() => {
    const c = document.querySelector('[data-case-id="f:1102"]');
    const line = c && c.querySelector(':scope > .qitems');
    if (!line) return null;
    const btn = line.querySelector('button');
    const ul = c.querySelector(':scope > .qitemlist');
    const before = { text: line.textContent.trim(), hidden: !ul || ul.hidden,
      h: btn ? Math.round(btn.getBoundingClientRect().height) : 0,
      right: Math.round(line.getBoundingClientRect().right),
      cardRight: Math.round(c.getBoundingClientRect().right) };
    if (btn) btn.click();
    const after = [...c.querySelectorAll(':scope > .qitemlist li')]
      .filter((li) => li.offsetParent !== null).map((li) => li.textContent.trim());
    return { before, after, label: btn ? btn.textContent.trim() : '' };
  });
  if (!list) note(where, 'the card about several things has no count line');
  else {
    if (!/^8 entities/.test(list.before.text)) note(where, `the count line reads "${list.before.text}"`);
    if (!list.before.hidden) note(where, 'the full list is open before Show all is pressed');
    if (list.before.h < (touch ? MIN_TARGET : 24)) note(where, `Show all is ${list.before.h}px tall`);
    if (list.before.right > list.before.cardRight + 1) note(where, 'the count line overflows the card');
    if (list.after.length !== 8) note(where, `Show all opened ${list.after.length} of 8 items`);
    if (list.after.some((t) => /^[a-z_]+\.[a-z0-9_]+$/.test(t))) note(where, 'the list shows an id');
    if (!list.after.includes('the select \u201cupstairs hallway ceiling light scene mode\u201d')) {
      note(where, `the list cut a long name: ${JSON.stringify(list.after)}`);
    }
    if (list.label !== 'Hide') note(where, `the press reads "${list.label}" once open`);
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
  detail: 'About the dryer vent.', fix: 'Your answer goes into the house book: the plain-language guide brAIn writes for anyone looking after this house.',
  answers: [
    A('answer', 'Send', '/api/house_book/question/1300/answer', { primary: true,
      note: true, done: 'Filed into memory for the house book',
      ask: 'Your answer goes into memory exactly as you write it.',
      placeholder: 'Behind the boiler, the red lever.' }),
    A('not_now', 'Snooze', '/api/case/f:1300/not_now'),
    A('not_applicable', "Doesn't apply", '/api/case/f:1300/not_applicable')],
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
  fix: 'Your answer goes into the house book: the plain-language guide brAIn writes for anyone looking after this house.', triage: {}, snoozed_until: 0 };
// A question brAIn asked about the house is answered the same way, posted
// to its own route (`findings_store.as_asked`).
const ASKED = { ts: 2302, text: 'Why does the porch light come on at 3am on weekdays?',
  kind: 'question', asked: true, severity: 'info', status: 'open', fixable: false,
  source: 'resident', source_title: 'brAIn', detail: 'Still open from an earlier conversation.',
  triage: { verdict: 'elevated' }, snoozed_until: 0,
  who: { who: 'answer', line: 'brAIn needs an answer.', press: 'Send' } };
// Questions are asked one at a time, so each is answered on a page where
// it is the one in front: the other questions are left off that page.
const NOT_QUESTIONS = FEED.filter((c) => c.group !== 'questions');
const GAP_PAGES = [
  { id: 'f:1300', words: 'Behind the dryer, a wall switch.',
    url: 'api/house_book/question/1300/answer',
    cases: [GAP, CANT, ...NOT_QUESTIONS], loose: [...LOOSE] },
  { id: 'f:2301', words: 'Under the sink.', url: 'api/house_book/question/2301/answer',
    cases: [CANT, ...NOT_QUESTIONS], loose: [...LOOSE, OLD_GAP] },
  { id: 'f:2302', words: 'The dog goes out then.', url: 'api/question/2302/answer',
    cases: [CANT, ...NOT_QUESTIONS], loose: [...LOOSE, ASKED] },
];
for (const { width, touch } of [{ width: 390, touch: true }, { width: 1190, touch: false }]) {
 for (const gp of GAP_PAGES) {
  const where = `${width}px gap ${gp.id}`;
  const { page, context } = await open(width, touch, {
    cases: gp.cases, loose: gp.loose, devloop: true, open: COUNTED + 3 });
  await openEverything(page);
  const faces = await page.evaluate((ids) => ids.map((id) => {
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
             fixHead: !!c.querySelector(':scope > .qfix'),
             group: c.closest('.qgroup')?.dataset.group || '' };
  }), [gp.id]);
  for (const f of faces) {
    if (!f.found) { note(where, `${f.id} is not on Today`); continue; }
    if (f.group !== 'questions') note(where, `${f.id} is under ${f.group}, not Questions for you`);
    if (!f.box || !f.send) note(where, `${f.id} has no answer box and Send on its face`);
    if (f.disabled !== true) note(where, `${f.id}'s Send is pressable with nothing typed`);
    if (touch && f.fs < 16) note(where, `${f.id}'s answer box is ${f.fs}px on touch`);
    if (touch && f.sendH < MIN_TARGET) note(where, `${f.id}'s Send is ${f.sendH}px tall`);
    if (f.todo) note(where, `${f.id} offers Add to To Do for a question`);
    if (f.fixHead) note(where, `${f.id} shows a Fix block over a question`);
  }
  {
    const sel = `[data-case-id="${gp.id}"] .gapanswer`;
    if (await page.locator(sel).count()) {
      await page.fill(`${sel} textarea`, gp.words);
      await page.click(`${sel} button[data-verb="answer"]`);
      await page.waitForTimeout(200);
    }
  }
  const sent = await posts(page);
  const hit = sent.find((pp) => pp.url.endsWith(gp.url));
  if (!hit || !hit.body || hit.body.note !== gp.words) {
    note(where, `Send did not post {note: "${gp.words}"} to ${gp.url} (${JSON.stringify(hit)})`);
  }
  if (gp.id !== 'f:1300') { await context.close(); continue; }
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
}

// Insights under the "N things need you" strip: nothing between the strip
// and the first thing under it but the section gap. An empty heading row
// (the pane's title is the segmented control's on a phone, and the search
// shows past eight reports) and an empty grid each took their own margin,
// which stacked into a band of nothing under the strip.
for (const [width, insights] of [[390, []], [390, INSIGHTS], [1190, []]]) {
  const where = `${width}px insights (${insights.length} cards)`;
  const { page, context } = await open(width, width < 640, { insights });
  await page.evaluate(() => switchView('insights'));
  await page.waitForTimeout(600);
  const boxes = await page.evaluate(() => [...document.querySelectorAll('#dash > *')]
    .map((e) => ({ id: e.id || e.className, r: e.getBoundingClientRect() }))
    .filter((b) => b.r.height > 0)
    .map((b) => ({ id: b.id, top: Math.round(b.r.top), bottom: Math.round(b.r.bottom) })));
  if (!boxes.length || boxes[0].id !== 'needsStrip') {
    note(where, `the strip is not first: ${boxes.map((b) => b.id).join(', ')}`);
  } else if (boxes[1] && boxes[1].top - boxes[0].bottom > 28) {
    note(where, `${boxes[1].top - boxes[0].bottom}px of nothing under the strip, above ${boxes[1].id}`);
  }
  await context.close();
}

// Grouped by consequence: a security finding is read with the problems,
// straight after the urgent ones and above a serious fault that is only
// the house's, and the registry's housekeeping (an unused helper, a lamp
// with no room) is folded under ONE closed, counted "Tidy-ups" line. A
// house had its security findings sitting level with exactly those rows.
for (const width of [390, 1190]) {
  const where = `${width}px (consequence)`;
  const sec = kase({
    id: 'f:1401', severity: 'info', situation: 'generic', chip: 'problem', group: 'problems',
    claim: 'Home Assistant banned an address after failed logins',
    source: 'check:sec.login_bans', source_title: 'Security check',
    origin: { store: 'findings', key: 1401 },
    answers: [A('todo', 'Add to To Do', '/api/case/f:1401/do', { primary: true }),
              A('not_now', 'Snooze', '/api/case/f:1401/not_now'),
              A('wrong', 'Ignore', '/api/case/f:1401/wrong', { note: true })] });
  const tidy = (id, claim, src) => kase({
    id, severity: 'info', chip: 'tidy', group: 'tidy', situation: 'generic', claim,
    source: src, source_title: 'Registry check', origin: { store: 'findings', key: Number(id.slice(2)) },
    answers: [A('fix', 'Go ahead', `/api/finding/${id.slice(2)}/fix`, { primary: true }),
              A('not_now', 'Snooze', `/api/case/${id}/not_now`),
              A('wrong', 'Ignore', `/api/case/${id}/wrong`, { note: true })] });
  const cases = [FEED[1], sec, FEED[0],
    tidy('f:1402', 'A helper nothing uses', 'check:reg.unused_helper'),
    tidy('f:1403', 'The porch lamp is in no room', 'check:reg.no_area')];
  const { page, context } = await open(width, width < 640, {
    cases, loose: [], proposals: [], intents: [], extras: {}, open: cases.length });
  await page.waitForTimeout(300);
  const got = await page.evaluate(() => ({
    groups: [...document.querySelectorAll('#findList > .qgroup')].map((g) => ({
      group: g.dataset.group, name: g.querySelector('.qgroupname')?.textContent || '',
      count: Number(g.querySelector('.qgroupcount')?.textContent || 'NaN'),
      open: g.querySelector('.qgrouphead')?.getAttribute('aria-expanded') === 'true',
      cards: g.querySelectorAll('.qcard').length })),
  }));
  const t = got.groups.find((g) => g.group === 'tidy');
  if (!t || t.name !== 'Tidy-ups' || t.count !== 2 || t.open || t.cards) {
    note(where, `the tidy-ups are not one closed counted line: ${JSON.stringify(t)}`);
  }
  if (got.groups[0]?.group !== 'problems') note(where, `the queue opens on ${got.groups[0]?.group}`);
  await page.evaluate(() => { todayState.showAll = true; renderFindings(); });
  const order = await page.evaluate(() => [...document.querySelectorAll(
    '#findList .qgroup[data-group="problems"] .qcard')].map((c) => c.dataset.caseId));
  if (order.join('|') !== 'f:1100|f:1401|f:1101') {
    note(where, `problems read ${order.join(', ')}, not urgent, security, then the rest`);
  }
  await context.close();
}

// Respond: the first press on every finding card ("I don't think I want
// the enter text box all the time. The first button should be Respond,
// clicking that opens the text box", the owner). No box shows by default;
// Respond is the first button in the answer row and the row stays one row
// on a phone; pressing it shows the box under the row with focus in it and
// a Send button, 16px on a finger (iOS zooms the ingress frame below that)
// with 44px targets; Escape or a second press puts it away, and what was
// typed is still there when it opens again, through a repaint too. What is
// sent is POSTed to /api/case/<id>/respond, the card polls the answer, and
// what brAIn said is painted: in the toast, with Undo when an ending was
// taken, and on the card as its last turn.
const RESPOND_ANSWER = `
(() => {
  const inner = window.fetch;
  window.fetch = async (url, opts) => {
    const p = String(url);
    if (p.includes('api/case/') && p.endsWith('/respond')) {
      const ok = (b) => new Response(JSON.stringify(b), {
        status: 200, headers: { 'Content-Type': 'application/json' } });
      if (opts && opts.method === 'POST') {
        window.__posts.push({ url: p, method: 'POST', body: opts.body || '' });
        return ok({ started: true });
      }
      return ok({ state: 'done', say: "Noted — brAIn will remember why and won't raise this again.",
                  undo: 'tok-respond', routes: ['case_ending'], ended: false });
    }
    return inner(url, opts);
  };
})();`;
const readRespond = (page, id) => page.evaluate((id) => {
  const c = document.querySelector(`#findList .qcard[data-case-id="${id}"]`);
  if (!c) return null;
  const form = c.querySelector(':scope > .qrespond');
  const input = form && form.querySelector('input');
  const go = form && form.querySelector('button[type="submit"]');
  const actions = c.querySelector(':scope > .card-actions');
  const r = c.getBoundingClientRect();
  const fr = form && form.getBoundingClientRect();
  const shown = !!(form && !form.hidden && getComputedStyle(form).display !== 'none' && fr.height > 0);
  return {
    shown, value: input ? input.value : null,
    focused: !!(input && document.activeElement === input),
    font: input ? parseFloat(getComputedStyle(input).fontSize) : 0,
    inH: input ? Math.round(input.getBoundingClientRect().height) : 0,
    goH: go ? Math.round(go.getBoundingClientRect().height) : 0,
    goLabel: go ? go.textContent.trim() : '',
    under: !!(shown && actions && fr.top >= actions.getBoundingClientRect().bottom - 1),
    inside: !!(shown && fr.left >= r.left - 1 && fr.right <= r.right + 1),
    expanded: c.querySelector('.qrespondopen')?.getAttribute('aria-expanded') || '',
  };
}, id);
for (const { width, touch } of [{ width: 390, touch: true }, { width: 1200, touch: false }]) {
  const where = `${width}px (respond)`;
  const { page, context } = await openToday(browser, PANEL, {
    width, touch, extra: RESPOND_ANSWER,
    onError: (m) => note(where, `page error: ${m}`) });
  await page.waitForTimeout(300);
  const cardsNow = await page.evaluate(() => [...document.querySelectorAll('#findList .qcard')]
    .filter((c) => /^f:/.test(c.dataset.caseId || '') && c.dataset.situation !== 'gap')
    .map((c) => {
      const form = c.querySelector(':scope > .qrespond');
      const actions = c.querySelector(':scope > .card-actions');
      const first = actions && actions.querySelector(':scope > button');
      const open = c.querySelector('.qrespondopen');
      const presses = actions ? [...actions.querySelectorAll(':scope > button')] : [];
      return {
        id: c.dataset.caseId, has: !!form,
        boxShown: !!(form && !form.hidden && getComputedStyle(form).display !== 'none'),
        anyInput: [...c.querySelectorAll('input[type="text"], textarea')]
          .some((x) => x.offsetParent !== null),
        first: first ? first.textContent.trim() : '',
        openH: open ? Math.round(open.getBoundingClientRect().height) : 0,
        rows: new Set(presses.map((b) => Math.round(b.getBoundingClientRect().top))).size,
      };
    }));
  if (!cardsNow.length) note(where, 'no finding card was drawn');
  for (const b of cardsNow) {
    if (!b.has) { note(where, `${b.id} has no Respond box`); continue; }
    if (b.boxShown || b.anyInput) note(where, `${b.id} shows a text box before Respond is pressed`);
    if (b.first !== 'Respond') note(where, `${b.id}: the first button is "${b.first}", not Respond`);
    if (touch && b.openH < MIN_TARGET) note(where, `${b.id}: Respond is ${b.openH}px on a finger`);
    if (width <= 640 && b.rows > 1) note(where, `${b.id}: with Respond the row wraps to ${b.rows} rows`);
  }
  const target = cardsNow.find((b) => b.has);
  if (target) {
    const card = `#findList .qcard[data-case-id="${target.id}"]`;
    // Press Respond: the box opens under the row, focused.
    await page.click(`${card} .qrespondopen`);
    let b = await readRespond(page, target.id);
    if (!b.shown) note(where, 'Respond did not open the box');
    if (!b.focused) note(where, 'the box opened without focus in it');
    if (b.expanded !== 'true') note(where, `Respond says aria-expanded="${b.expanded}" when open`);
    if (!b.under) note(where, 'the Respond box is not under the answer row');
    if (!b.inside) note(where, 'the Respond box spills out of its card');
    if (b.goLabel !== 'Send') note(where, `the box's button reads "${b.goLabel}"`);
    if (touch && b.font < 16) note(where, `the Respond box is ${b.font}px on a finger`);
    if (touch && (b.goH < MIN_TARGET || b.inH < MIN_TARGET)) {
      note(where, `the Respond box is ${b.inH}px and Send ${b.goH}px on a finger`);
    }
    // A draft survives Escape, a second press and a repaint.
    await page.fill(`${card} .qrespond input`, 'half a thought');
    await page.keyboard.press('Escape');
    b = await readRespond(page, target.id);
    if (b.shown) note(where, 'Escape did not put the box away');
    await page.click(`${card} .qrespondopen`);
    b = await readRespond(page, target.id);
    if (!b.shown || b.value !== 'half a thought') note(where, `the draft after Escape reads "${b.value}"`);
    await page.click(`${card} .qrespondopen`);
    b = await readRespond(page, target.id);
    if (b.shown) note(where, 'a second press did not put the box away');
    await page.evaluate(() => renderFindings());
    await page.click(`${card} .qrespondopen`);
    b = await readRespond(page, target.id);
    if (!b.shown || b.value !== 'half a thought') note(where, `the draft after a repaint reads "${b.value}"`);
    // Send, and the answer is painted.
    await page.evaluate((id) => {
      const d = window.__today;
      const words = "It's off on purpose for the Task Manager. Remember that.";
      const thread = [{ who: 'you', text: words, at: 1 },
        { who: 'brain', text: "Noted — brAIn will remember why and won't raise this again.", at: 2 }];
      d.cases = d.cases.map((c) => (c.id === id ? { ...c, thread } : c));
      d.loose = d.loose.map((f) => (`f:${f.ts}` === id ? { ...f, thread } : f));
    }, target.id);
    await page.fill(`${card} .qrespond input`, "It's off on purpose for the Task Manager. Remember that.");
    await page.click(`${card} .qrespond button[type="submit"]`);
    await page.waitForFunction(() => /won't raise this again/.test(
      document.getElementById('toast')?.textContent || ''), null, { timeout: 8000 })
      .catch(() => note(where, 'the answer never reached the toast'));
    const after = await page.evaluate((id) => {
      const t = document.getElementById('toast');
      const c = document.querySelector(`#findList .qcard[data-case-id="${id}"]`);
      const form = c && c.querySelector(':scope > .qrespond');
      return {
        undo: !!(t && [...t.querySelectorAll('button')].some((x) => x.textContent === 'Undo')),
        turn: c ? (c.querySelector('.qthread')?.textContent || '') : '',
        boxShown: !!(form && !form.hidden),
      };
    }, target.id);
    if (!after.undo) note(where, 'the answer\'s toast carries no Undo');
    if (!/brAIn.*won't raise this again/.test(after.turn)) {
      note(where, `the card does not show what brAIn said (${after.turn || 'nothing'})`);
    }
    if (after.boxShown) note(where, 'the box is still open after its answer landed');
    const sent = (await posts(page)).filter((x) => /\/respond$/.test(x.url));
    if (sent.length !== 1 || !/Task Manager/.test((sent[0].body || {}).text || '')) {
      note(where, `the press sent ${JSON.stringify(sent)}`);
    }
  }
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (wide > 1) note(where, `page scrolls sideways (${wide}px)`);
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(`measure-today: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-today: ok');
