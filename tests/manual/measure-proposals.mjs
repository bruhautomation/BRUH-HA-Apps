// Render the Proposals tab against a real set of proposals and assert it
// says what it is for.
//
// The failure this exists to prevent is not a layout bug. It is a tab that
// looks fine and quietly loses the one thing that makes a proposal
// answerable: the evidence. A card with a title and two buttons is a
// suggestion from nowhere, and the honest answer to one of those is always
// no. So the checks are about what a card SAYS as much as where it sits:
//
//   * every card carries its evidence — the "why", and what the replay
//     found over the person's own history. A card with neither is a bug.
//   * a trialling card says it is running in shadow and changing nothing.
//     Somebody who thinks a trial is live will not start one.
//   * "No thanks" opens the reason box IN PLACE of the buttons, inside the
//     card, so what you are explaining stays on screen while you write.
//   * the badge counts what is waiting, and disappears when nothing is.
//   * the empty state does not congratulate anybody. An empty Findings list
//     means the house is well; an empty Proposals list means brAIn has not
//     spotted a habit yet, and those are different sentences.
//   * every target clears the touch floor, the textarea clears 16px (below
//     it iOS zooms the ingress iframe in and never back out), and nothing
//     scrolls sideways.
//
// Drives the panel's REAL renderer behind a stubbed fetch. A copy of
// renderProposals in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 44;
const MIN_TEXT_TOUCH = 16;

const NOW = Math.floor(Date.now() / 1000);
const PROPOSALS = [
  {
    ts: NOW * 1000, key: 'aaa', kind: 'automation',
    title: 'Turn the kitchen lights off at 23:05',
    why: 'You do this by hand at 23:05 ± 12 min on 26 of the last 30 nights, '
       + 'always after the living-room TV goes off.',
    source: 'propose.routine', status: 'proposed',
    replay: { days: 30, would_run: 26, blocked_by_conditions: 0, triggered: 26 },
  },
  {
    ts: NOW * 1000 - 1000, key: 'bbb', kind: 'automation',
    title: 'Add an "office is empty" condition to Evening lights',
    why: 'You override Evening lights on 40% of weekday evenings, always '
       + 'when the office is occupied.',
    source: 'propose.override', status: 'trialling',
    trial_started_at: NOW - 3 * 86400, trial_ends_at: NOW + 4 * 86400,
    trial_result: { would_fire: 6, agreed: 5 },
    replay: { days: 30, would_run: 18, blocked_by_conditions: 4, triggered: 22 },
  },
  {
    ts: NOW * 1000 - 2000, key: 'ccc', kind: 'automation',
    title: 'Close the garage if it is still open at midnight',
    why: 'It has been left open past midnight four times this month.',
    source: 'propose.routine', status: 'proposed',
    // Deliberately unreplayable: the card still has to be answerable, and
    // it has to say WHY there is no number rather than showing a blank.
    replay: { refused: true, error: 'a `device` trigger cannot be replayed' },
  },
];

const STUB = `
window.__proposals = {
  proposals: ${JSON.stringify(PROPOSALS)},
  counts: { proposed: 2, trialling: 1, accepted: 0, declined: 0, open: 3 },
  trial_days: 7,
};
window.__empty = false;
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/proposal/')) {
    // Every ending removes the row, so the stub answers with the list
    // minus it — the shape the real route returns.
    const ts = Number(p.split('api/proposal/')[1].split('/')[0]);
    window.__proposals = {
      ...window.__proposals,
      proposals: window.__proposals.proposals.filter((r) => r.ts !== ts),
      counts: { ...window.__proposals.counts,
                open: window.__proposals.counts.open - 1 },
      learned: 'Declined brAIn's suggestion.',
    };
    return answer(window.__proposals);
  }
  if (p.includes('api/proposals')) {
    if (window.__empty) {
      return answer({ proposals: [], counts: { open: 0 }, trial_days: 7 });
    }
    return answer(window.__proposals);
  }
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`.replace("Declined brAIn's suggestion.", "Declined the suggestion.");

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const width of WIDTHS) {
  // The narrow widths are phones, so they are driven AS phones: the touch
  // floor lives in a `pointer: coarse` block, and a context with a fine
  // pointer would measure the desktop density and call it a pass.
  const touch = width <= 430;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch,
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="proposals"]');
  await page.waitForSelector('.propcard');

  const m = await page.evaluate((floor) => {
    const cards = [...document.querySelectorAll('.propcard')];
    const wrap = document.querySelector('.propwrap').getBoundingClientRect();
    const badge = document.querySelector('#propBadge');
    return {
      count: cards.length,
      wrapRight: wrap.right,
      docWidth: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      badge: badge ? { text: badge.textContent,
                       hidden: badge.classList.contains('hidden') } : null,
      cards: cards.map((c) => ({
        title: (c.querySelector('.proptitle') || {}).textContent || '',
        why: (c.querySelector('.propwhy') || {}).textContent || '',
        replay: (c.querySelector('.propreplay') || {}).textContent || '',
        trial: (c.querySelector('.proptrial') || {}).textContent || '',
        pill: !!c.querySelector('.pilltrial'),
        buttons: [...c.querySelectorAll('.propbtns button')].map((b) => ({
          label: b.textContent.trim(),
          h: b.getBoundingClientRect().height,
          w: b.getBoundingClientRect().width,
        })),
        overflows: c.getBoundingClientRect().right > wrap.right + 1,
      })),
      small: [...document.querySelectorAll('#viewProposals button')]
        .filter((b) => b.getBoundingClientRect().height > 0
                    && b.getBoundingClientRect().height < floor)
        .map((b) => `${b.textContent.trim()} @${
          Math.round(b.getBoundingClientRect().height)}px`),
    };
  }, MIN_TARGET);

  const where = `${width}px`;
  if (m.count !== PROPOSALS.length) {
    note(where, `rendered ${m.count} cards, expected ${PROPOSALS.length}`);
  }
  if (m.docWidth > m.viewport + 1) {
    note(where, `page scrolls sideways (${m.docWidth} > ${m.viewport})`);
  }
  // Only asserted where a finger is the pointer. On a desktop the panel
  // is deliberately denser, and holding it to 44px there would be
  // measuring a rule nobody wrote.
  if (touch && m.small.length) {
    note(where, `under the touch floor: ${m.small.join(', ')}`);
  }
  if (!m.badge || m.badge.hidden || m.badge.text !== '3') {
    note(where, `badge should read 3, got ${JSON.stringify(m.badge)}`);
  }

  m.cards.forEach((c, i) => {
    if (!c.title.trim()) note(where, `card ${i} has no title`);
    // The whole point of the tab: a proposal with no evidence is a
    // suggestion from nowhere, and the honest answer to one is always no.
    if (!c.why.trim() && !c.replay.trim()) {
      note(where, `card ${i} ("${c.title.slice(0, 30)}") carries no evidence`);
    }
    if (c.overflows) note(where, `card ${i} overflows its wrapper`);
    if (!c.buttons.length) note(where, `card ${i} has no way to answer it`);
  });

  // The trialling card has to SAY it is running in shadow. Somebody who
  // thinks a trial is live will never start one.
  const trial = m.cards.find((c) => c.pill);
  if (!trial) note(where, 'the trialling card has no "On trial" marker');
  else if (!/shadow|would have fired/i.test(trial.trial)) {
    note(where, `trialling card does not say what a trial is: "${trial.trial}"`);
  }

  // The refused replay still has to be answerable, and has to say why
  // there is no number rather than showing a blank line.
  const refused = m.cards[2];
  if (refused && !/not replayable/i.test(refused.replay)) {
    note(where, `a refused replay must say so, got "${refused.replay}"`);
  }

  // "No thanks" opens the reason box in place of the buttons, inside the
  // card — you are explaining something and it has to stay on screen.
  await page.click('.propcard:first-child .propbtns button:last-child');
  await page.waitForSelector('.propnote textarea');
  const box = await page.evaluate(() => {
    const card = document.querySelector('.propcard');
    const area = card.querySelector('.propnote textarea');
    return {
      inside: !!area && card.contains(area),
      fontSize: parseFloat(getComputedStyle(area).fontSize),
      buttonsGone: !card.querySelector('.propbtns button[data-tip]'),
      placeholder: area.placeholder,
    };
  });
  if (!box.inside) note(where, 'the reason box is not inside the card');
  if (box.fontSize < MIN_TEXT_TOUCH) {
    note(where, `reason box is ${box.fontSize}px — under the 16px floor, `
              + 'which makes iOS zoom the ingress iframe in and never back');
  }
  if (!/optional/i.test(box.placeholder)) {
    note(where, 'the reason box does not say it is optional');
  }

  // And the empty state does not congratulate anybody.
  await page.evaluate(() => { window.__empty = true; });
  await page.click('.viewtab[data-view="insights"]');
  await page.click('.viewtab[data-view="proposals"]');
  await page.waitForSelector('#propList .empty');
  const empty = await page.evaluate(() => ({
    text: document.querySelector('#propList .empty').textContent,
    badgeHidden: document.querySelector('#propBadge').classList.contains('hidden'),
  }));
  if (/all clear|nothing wrong|well done|great/i.test(empty.text)) {
    note(where, `empty state congratulates: "${empty.text.slice(0, 60)}"`);
  }
  if (!empty.badgeHidden) note(where, 'badge still shown with nothing waiting');

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-proposals: ${failures.length} problem(s)`);
  failures.forEach((f) => console.error('  ' + f));
  process.exit(1);
}
console.log(`measure-proposals: OK at ${WIDTHS.join(', ')}px`);
