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
//   * a trialling card says how far in it is and what the week has found,
//     in words a person would use — "you did the opposite on 1", never
//     `contradicted`. 1.42.0's trial reported nothing at all, and a card
//     that says nothing is indistinguishable from a feature that does
//     nothing, which is exactly how it read.
//   * the three states a trial can be in are three different sentences:
//     graded, not graded yet (a row that started since the last checks
//     pass — never zeros, which read as "it would never have fired"), and
//     refused (which is about brAIn, not about the automation).
//   * an accept that Home Assistant would not honour leaves the card
//     exactly where it was, with the refusal ON it. A yes that could not
//     be taken has to be readable for longer than a toast.
//   * an accept that lands takes the row away and offers Undo, because it
//     is the one press in the panel that writes to /config.
//   * "No thanks" opens the reason box IN PLACE of the buttons, inside the
//     card, so what you are explaining stays on screen while you write.
//   * the badge counts what is waiting — a trial whose week is over is
//     still waiting on you — and disappears when nothing is.
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
    // Three days in and graded: the line every other state is measured
    // against. All three verdicts are non-zero on purpose — the whole
    // point of the week is the third one.
    ts: NOW * 1000 - 1000, key: 'bbb', kind: 'automation',
    title: 'Add an "office is empty" condition to Evening lights',
    why: 'You override Evening lights on 40% of weekday evenings, always '
       + 'when the office is occupied.',
    source: 'propose.override', status: 'trialling',
    trial_started_at: NOW - 3 * 86400, trial_ends_at: NOW + 4 * 86400,
    trial_result: {
      would_fire: 6, agreed: 4, disagreed: 1, contradicted: 1,
      firings: [{ ts: NOW - 2 * 86400, verdict: 'agreed' }],
      entity_id: 'light.office', state: 'off',
      window: { start: NOW - 3 * 86400, end: NOW }, days: 3,
      evaluated_at: NOW - 600,
    },
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
  {
    // Started trialling since the last checks pass, so nothing has graded
    // it. Zeros here would read as "it would never have fired", which is
    // an answer about the automation rather than about the trial.
    ts: NOW * 1000 - 3000, key: 'ddd', kind: 'automation',
    title: 'Turn the porch light on at sunset',
    why: 'You do it by hand within twenty minutes of sunset on 9 of the '
       + 'last 14 evenings.',
    source: 'propose.routine', status: 'trialling',
    trial_started_at: NOW - 3600, trial_ends_at: NOW + 7 * 86400 - 3600,
    replay: { days: 30, would_run: 30, blocked_by_conditions: 0, triggered: 30 },
  },
  {
    // A trial brAIn could not grade. The refusal is carried whole, and the
    // card is still answerable — the replay evidence is still on it, and
    // it is still a person's decision.
    ts: NOW * 1000 - 4000, key: 'eee', kind: 'automation',
    title: 'Run the dehumidifier when the cellar goes over 65%',
    why: 'You switch it on by hand whenever the cellar humidity climbs.',
    source: 'propose.routine', status: 'trialling',
    trial_started_at: NOW - 5 * 86400, trial_ends_at: NOW + 2 * 86400,
    trial_result: {
      refused: true,
      error: 'a `webhook` trigger cannot be replayed, so this trial has '
           + 'nothing to grade',
    },
    replay: { days: 30, would_run: 11, blocked_by_conditions: 0, triggered: 11 },
  },
  {
    // The week is up. The row stays trialling — ending it is a press — so
    // the badge still counts it, and Accept is the primary action.
    ts: NOW * 1000 - 5000, key: 'fff', kind: 'automation',
    title: 'Close the blinds at 21:40 on weekdays',
    why: 'You close them within a quarter of an hour of 21:40 on 11 of the '
       + 'last 14 weekdays.',
    source: 'propose.routine', status: 'trialling',
    trial_started_at: NOW - 8 * 86400, trial_ends_at: NOW - 86400,
    trial_result: {
      would_fire: 7, agreed: 6, disagreed: 1, contradicted: 0,
      firings: [], entity_id: 'cover.lounge', state: 'closed',
      window: { start: NOW - 8 * 86400, end: NOW - 86400 }, days: 7,
      evaluated_at: NOW - 86400,
    },
    replay: { days: 30, would_run: 21, blocked_by_conditions: 0, triggered: 21 },
  },
];

const OPEN = PROPOSALS.length;
// The sentence the panel must show verbatim when Home Assistant will not
// take the change. It is the whole reason the 409 carries a body.
const REFUSAL = 'automations.yaml already has one called "Close the blinds '
  + 'at 21:40 on weekdays"';

const STUB = `
window.__proposals = {
  proposals: ${JSON.stringify(PROPOSALS)},
  counts: { proposed: 3, trialling: 3, accepted: 0, declined: 0, open: ${OPEN} },
  trial_days: 7, routine_min_days: 6,
};
window.__empty = false;
// Which accept the stub should refuse. The 409 path is not an error path:
// the row is still open, still in the payload, and the sentence has to
// reach the card rather than a toast that is gone in three seconds.
window.__refuse = ${PROPOSALS[5].ts};
window.__refusal = ${JSON.stringify(REFUSAL)};
window.__undone = null;
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body, status) => new Response(JSON.stringify(body), {
    status: status || 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/undo/')) {
    window.__undone = p.split('api/undo/')[1];
    return answer({ undone: true, reverted: true, reloaded: true,
                    restored_proposal: true, ...window.__proposals });
  }
  if (p.includes('api/proposal/')) {
    const ts = Number(p.split('api/proposal/')[1].split('/')[0]);
    const verb = p.split('/').pop();
    // A refused accept answers 409 WITH the list, the row still on it.
    if (verb === 'accept' && ts === window.__refuse) {
      return answer({ error: window.__refusal, ...window.__proposals }, 409);
    }
    // Every ending removes the row, so the stub answers with the list
    // minus it — the shape the real route returns.
    const row = window.__proposals.proposals.find((r) => r.ts === ts);
    window.__proposals = {
      ...window.__proposals,
      proposals: window.__proposals.proposals.filter((r) => r.ts !== ts),
      counts: { ...window.__proposals.counts,
                open: window.__proposals.counts.open - 1 },
      learned: 'Declined the suggestion.',
    };
    if (verb === 'accept') {
      return answer({ ...window.__proposals, proposal: row,
                      learned: 'Accepted the suggestion.',
                      automation: 'brain_' + ts,
                      entity_id: 'automation.' + ts,
                      undo: 'tok-' + ts });
    }
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
`;

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

  const read = () => page.evaluate((floor) => {
    const cards = [...document.querySelectorAll('.propcard')];
    const wrap = document.querySelector('.propwrap').getBoundingClientRect();
    const badge = document.querySelector('#propBadge');
    return {
      count: cards.length,
      docWidth: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      badge: badge ? { text: badge.textContent,
                       hidden: badge.classList.contains('hidden') } : null,
      hints: document.querySelectorAll('.prophint').length,
      cards: cards.map((c) => ({
        title: (c.querySelector('.proptitle') || {}).textContent || '',
        why: (c.querySelector('.propwhy') || {}).textContent || '',
        replay: (c.querySelector('.propreplay') || {}).textContent || '',
        trial: (c.querySelector('.proptrial') || {}).textContent || '',
        error: (c.querySelector('.properror') || {}).textContent || '',
        pill: (c.querySelector('.pilltrial') || {}).textContent || '',
        buttons: [...c.querySelectorAll('.propbtns button')].map((b) => ({
          label: b.textContent.trim(),
          primary: b.classList.contains('primary'),
          h: b.getBoundingClientRect().height,
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

  const m = await read();
  const where = `${width}px`;
  // A wait that times out is a real failure, and it has to arrive as the
  // sentence describing what did not happen rather than as a Playwright
  // stack about a selector — the panel not doing the thing IS the report.
  const waitOr = async (promise, message) => {
    try {
      await promise;
      return true;
    } catch {
      note(where, message);
      return false;
    }
  };
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
  // Three trialling rows are open, and the one whose week is up is still
  // waiting on somebody.
  if (!m.badge || m.badge.hidden || m.badge.text !== String(OPEN)) {
    note(where, `badge should read ${OPEN}, got ${JSON.stringify(m.badge)}`);
  }
  // The "graded again every few hours" sentence, once for the list.
  if (m.hints !== 1) {
    note(where, `expected one trial hint on the list, found ${m.hints}`);
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

  // --- the graded trial: the line 1.42.0 could not draw at all.
  const graded = m.cards[1];
  if (!/day 3 of 7/i.test(graded.trial)) {
    note(where, `graded trial does not say how far in it is: "${graded.trial}"`);
  }
  if (!/would have fired 6 times/i.test(graded.trial)) {
    note(where, `graded trial does not say what it would have done: `
              + `"${graded.trial}"`);
  }
  // Three verdicts, in words somebody would use. `contradicted` is the
  // store's word and nobody's: what it means is that you put the thing
  // back the other way, and folding it into "disagreed" would report a
  // change actively unwanted as merely unproven.
  [/you did the same on 4/i, /nothing happened on 1/i,
   /you did the opposite on 1/i].forEach((re) => {
    if (!re.test(graded.trial)) {
      note(where, `graded trial is missing ${re} — got "${graded.trial}"`);
    }
  });
  if (/contradicted|disagreed|agreed on/i.test(graded.trial)) {
    note(where, `graded trial uses the store's vocabulary: "${graded.trial}"`);
  }

  // --- nothing has graded it yet, which is not the same as zeros.
  const fresh = m.cards[3];
  if (!/nothing graded yet/i.test(fresh.trial)) {
    note(where, `an ungraded trial must say so, got "${fresh.trial}"`);
  }
  if (/would have fired 0|fired 0 times/i.test(fresh.trial)) {
    note(where, `an ungraded trial reports zeros: "${fresh.trial}"`);
  }

  // --- a trial brAIn could not replay. Its sentence is carried whole,
  // and the card is still a person's to answer.
  const refusedTrial = m.cards[4];
  if (!refusedTrial.trial.includes('webhook')) {
    note(where, `a refused trial must carry its reason, got `
              + `"${refusedTrial.trial}"`);
  }
  if (refusedTrial.buttons.length < 2) {
    note(where, 'a refused trial is still a decision — it has lost its buttons');
  }

  // --- the week is up. The row is still on the list, and accepting is
  // now the primary thing to do with it.
  const done = m.cards[5];
  if (!/^trial over/i.test(done.trial)) {
    note(where, `a finished trial must say so, got "${done.trial}"`);
  }
  if (!/would have fired 7 times/i.test(done.trial)) {
    note(where, `a finished trial must carry its result: "${done.trial}"`);
  }
  if (!done.buttons.some((b) => b.primary)) {
    note(where, 'a finished trial offers no primary action');
  }

  // --- the refused replay still has to be answerable, and has to say why
  // there is no number rather than showing a blank line.
  if (!/not replayable/i.test(m.cards[2].replay)) {
    note(where, `a refused replay must say so, got "${m.cards[2].replay}"`);
  }

  // --- an accept Home Assistant will not honour. The card stays put and
  // the sentence lands on it, because a toast is gone before somebody has
  // read a filename.
  await page.click('.propcard:nth-child(6) .propbtns button:first-child');
  const landed = await waitOr(
    page.waitForSelector('.propcard .properror'),
    'a refused accept never put its sentence on the card — a toast is gone '
    + 'in three seconds and this is what somebody has to read');
  if (landed) {
    const refused = await read();
    if (refused.count !== PROPOSALS.length) {
      note(where, `a refused accept changed the list (${refused.count} cards)`);
    }
    const stillThere = refused.cards[5];
    if (!stillThere.error.includes(REFUSAL)) {
      note(where, `the refusal is not on the card: "${stillThere.error}"`);
    }
    if (stillThere.buttons.length !== 1
        || !/dismiss/i.test(stillThere.buttons[0].label)) {
      note(where, 'the refusal has no way back to the buttons');
    }
    await page.click('.propcard:nth-child(6) .properror button');
    await waitOr(
      page.waitForFunction(() => !document.querySelector('.properror')),
      'the refusal would not dismiss');
    const back = await read();
    if (back.cards[5].buttons.length < 2) {
      note(where, 'the buttons did not come back after dismissing the refusal');
    }
  }

  // --- an accept that lands. The row goes, and the toast offers Undo,
  // because this is the one press in the panel that writes to /config.
  await page.click('.propcard:nth-child(2) .propbtns button:first-child');
  await waitOr(
    page.waitForFunction((n) =>
      document.querySelectorAll('.propcard').length === n,
    PROPOSALS.length - 1),
    'an accepted proposal stayed on the list');
  const toast = await page.evaluate(() => {
    const t = document.querySelector('#toast');
    const undo = t.querySelector('.toastundo');
    return {
      shown: t.classList.contains('show'),
      text: t.textContent,
      undo: undo ? undo.getBoundingClientRect().height : 0,
    };
  });
  if (!toast.shown) note(where, 'an accepted proposal says nothing');
  if (!/added .* to your automations/i.test(toast.text)) {
    note(where, `the accept toast does not name what was added: `
              + `"${toast.text}"`);
  }
  if (!toast.undo) note(where, 'an accepted proposal offers no Undo');
  else if (touch && toast.undo < MIN_TARGET) {
    note(where, `the Undo control is ${Math.round(toast.undo)}px — under the `
              + `${MIN_TARGET}px touch floor, and it expires with the toast`);
  }
  // And pressing it goes back through the one undo path the panel has.
  if (toast.undo) {
    await page.click('#toast .toastundo');
    await waitOr(page.waitForFunction(() => window.__undone !== null),
                 'Undo pressed and nothing was undone');
  }

  // --- "No thanks" opens the reason box in place of the buttons, inside
  // the card — you are explaining something and it has to stay on screen.
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
