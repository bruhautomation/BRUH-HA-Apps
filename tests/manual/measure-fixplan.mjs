// Render the Findings tab against the four states of a plan-first fix, and
// assert that what a person reads before pressing says what pressing will do.
//
// The failure this exists to prevent is the one the plan step was added
// for, arriving one layer up: a press that changes somebody's house with
// nothing on screen first about what it is about to change. So the checks
// are about what each card SAYS and which buttons it offers.
//
//   * a planned card shows the steps it is asking consent for, and the
//     risk sentence under them — the two things the whole step exists to
//     put in front of somebody.
//   * a plan that says software should NOT make this change offers no
//     Apply, only Cancel, and says so in words rather than by a missing
//     button: a button that cannot help is worse than the sentence.
//   * a card mid-look says nothing is being changed yet and offers no
//     press at all, so the state is legible rather than a row of greyed
//     buttons.
//   * a fixed card says how many files it changed and how many service
//     calls it made BEFORE the undo beside it is pressed, because the two
//     are what the undo treats differently.
//   * nothing overflows, nothing scrolls sideways, and the steps stay
//     readable at 390px, where the card is a phone's whole width.
//
// It drives the panel's REAL `renderFindings`/`makeFinding`/`planBlock`
// behind a stubbed fetch — measure-activity's rule, because a copy of the
// renderer in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 430, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];

const NOW = Math.floor(Date.now() / 1000);
const row = (over) => ({
  ts: 0, text: '', detail: '', fix: '', severity: 'warning', fixable: true,
  entity_id: '', source: 'check:auto.trigger_unavailable',
  source_title: 'Automation checks', run_id: '', status: 'open', result: '',
  changed: [], settled_at: 0, snoozed_until: 0, checked_at: 0, triage: {},
  plan: {}, fix_started: 0, fix_ended: 0, fix_files: 0, fix_calls: 0, ...over,
});

const STEPS = [
  "Edit /config/automations.yaml: point 'Hall lights' at binary_sensor.hall "
  + 'rather than the binary_sensor.hall_old that was renamed',
  'Reload automations so Home Assistant picks the change up',
];
const RISK = 'The hall lights will not come on between the edit and the reload.';

const FINDINGS = [
  row({ ts: NOW - 60, text: 'Hall lights can never fire', status: 'planned',
        severity: 'serious', entity_id: 'automation.hall_lights',
        plan: { can_fix: true, needs_you: false, steps: STEPS, risk: RISK,
                summary: 'Its trigger entity was renamed in March, so the '
                  + 'automation is on and can never run.' } }),
  row({ ts: NOW - 120, text: 'The back door sensor battery is flat',
        status: 'planned', entity_id: 'sensor.back_door_battery',
        plan: { can_fix: false, needs_you: true, steps: [], risk: '',
                summary: 'The CR2032 has to be replaced by hand — there is '
                  + 'nothing software can do about a flat cell.' } }),
  row({ ts: NOW - 180, text: 'The porch light has no area', status: 'planning' }),
  row({ ts: NOW - 240, text: 'The landing motion rule ran every night',
        status: 'fixed', fix_started: NOW - 300, fix_ended: NOW - 250,
        fix_files: 2, fix_calls: 3,
        result: 'Corrected the trigger and reloaded automations.' }),
  // A fix from before the panel recorded what a run changed: an add-on
  // updated while a fixed row sat on the tab.
  row({ ts: NOW - 300, text: 'The garage door reported unavailable',
        status: 'fixed', result: 'Reloaded the integration.' }),
];

const STUB = `
window.__findings = {
  findings: ${JSON.stringify(FINDINGS)},
  hypotheses: [], open: 3, settled: [], scorecard: [],
};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/findings')) return answer(window.__findings);
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 3,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/todo')) {
    return answer({ items: [], done: [], open: 0, done_count: 0 });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const read = (page) => page.evaluate(() => {
  const cards = [...document.querySelectorAll('#findList .finding')];
  return {
    cards: cards.map((c) => {
      const box = c.getBoundingClientRect();
      const plan = c.querySelector('.findplan');
      return {
        title: c.querySelector('.findtitle')?.textContent || '',
        state: c.querySelector('.findstate')?.textContent.trim() || '',
        planLabel: plan?.querySelector('.findplanlabel')?.textContent || '',
        steps: [...(plan?.querySelectorAll('.findsteps li') || [])]
          .map((li) => li.textContent.trim()),
        risk: plan?.querySelector('.findrisk')?.textContent || '',
        foot: c.querySelector('.findfixfoot')?.textContent || '',
        phase: c.querySelector('.findactions .phase')?.textContent.trim() || '',
        verbs: [...c.querySelectorAll('.findactions button')]
          .map((b) => b.textContent.trim()),
        right: Math.round(box.right),
      };
    }),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
});

for (const { width, touch } of CASES) {
  const context = await browser.newContext({
    viewport: { width, height: 1200 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.click('.viewtab[data-view="findings"]');
  await page.waitForSelector('#findList .finding');

  const live = await read(page);
  if (live.cards.length !== FINDINGS.length) {
    note(`${width}px`,
         `${live.cards.length} cards, expected ${FINDINGS.length} — a plan `
         + 'waiting on somebody is not on the work list');
  }

  const can = live.cards.find((c) => /Hall lights/.test(c.title));
  const cannot = live.cards.find((c) => /battery/.test(c.title));
  const looking = live.cards.find((c) => /porch/.test(c.title));
  const fixed = live.cards.find((c) => /landing/i.test(c.title));

  // The steps are what a person is consenting to, so they have to be on
  // the card whole — not summarised, not behind a disclosure.
  if (!can) {
    note(`${width}px`, 'the planned card is not rendered at all');
  } else {
    if (can.steps.length !== STEPS.length) {
      note(`${width}px`,
           `${can.steps.length} steps shown, expected ${STEPS.length}`);
    }
    for (const step of STEPS) {
      if (!can.steps.some((s) => s.includes(step.slice(0, 40)))) {
        note(`${width}px`, `a step is missing from the card: ${step.slice(0, 40)}…`);
      }
    }
    if (!can.risk.includes(RISK)) {
      note(`${width}px`, 'the plan does not say what could go wrong');
    }
    if (!/what could go wrong/i.test(can.risk)) {
      note(`${width}px`,
           'the risk line is marked by colour alone — it has to say in words '
           + 'what kind of sentence it is');
    }
    if (!can.verbs.some((v) => /Apply/i.test(v))) {
      note(`${width}px`, 'a plan brAIn can carry out offers no Apply');
    }
    if (!can.verbs.some((v) => /Cancel/i.test(v))) {
      note(`${width}px`, 'a plan offers no way to say no');
    }
  }

  // The one that must not read as the other: no Apply, and the reason in
  // words rather than as a button that is simply missing.
  if (!cannot) {
    note(`${width}px`, 'the refused plan is not rendered at all');
  } else {
    if (cannot.verbs.some((v) => /Apply/i.test(v))) {
      note(`${width}px`,
           'a plan that needs a person offers Apply, which cannot help');
    }
    if (!cannot.verbs.some((v) => /Cancel/i.test(v))) {
      note(`${width}px`, 'a refused plan offers nothing to press');
    }
    if (cannot.steps.length) {
      note(`${width}px`,
           'a refused plan lists steps, which reads as a plan to approve');
    }
    if (!cannot.planLabel || cannot.planLabel === (can?.planLabel || '')) {
      note(`${width}px`,
           `a refused plan is headed "${cannot.planLabel}" — the same words `
           + 'as one brAIn would carry out');
    }
  }

  // Mid-look: no press, and the state said rather than implied.
  if (!looking) {
    note(`${width}px`, 'the card being looked at is not rendered');
  } else {
    if (looking.verbs.length) {
      note(`${width}px`,
           `a card mid-look offers ${looking.verbs.length} button(s) while a `
           + 'run is out');
    }
    if (!/nothing is being changed/i.test(looking.phase)) {
      note(`${width}px`,
           `a card mid-look says "${looking.phase}" — it has to say that `
           + 'nothing has been changed yet');
    }
  }

  // The two numbers, read before the undo rather than discovered by it.
  if (!fixed) {
    note(`${width}px`, 'the fixed card is not rendered');
  } else {
    if (!/2 files/.test(fixed.foot) || !/3 service calls/.test(fixed.foot)) {
      note(`${width}px`,
           `a fixed card's foot reads "${fixed.foot}" — it has to say what `
           + 'the fix changed and what it called');
    }
    if (!/not reversed/i.test(fixed.foot)) {
      note(`${width}px`,
           'the foot does not say the service calls are not reversed, which '
           + 'is the difference the undo turns on');
    }
    if (!fixed.verbs.some((v) => /Undo/i.test(v))) {
      note(`${width}px`, 'a fixed card offers no undo');
    }
    if (!fixed.verbs.some((v) => /Got it/i.test(v))) {
      note(`${width}px`, 'a fixed card lost its ending');
    }
  }

  // The one that must not offer a press it cannot honour: a run from
  // before the window was kept. "I could not tell" is a sentence, not a
  // button that answers "there was nothing to do".
  const unrecorded = live.cards.find((c) => /garage/i.test(c.title));
  if (!unrecorded) {
    note(`${width}px`, 'the unrecorded fix is not rendered');
  } else {
    if (unrecorded.verbs.some((v) => /Undo/i.test(v))) {
      note(`${width}px`,
           'a fix whose window was never recorded offers an undo that can '
           + 'only answer "nothing to put back" about a house it changed');
    }
    if (!/did not record/i.test(unrecorded.foot)) {
      note(`${width}px`,
           `an unrecorded fix's foot reads "${unrecorded.foot}" — it has to `
           + 'say that brAIn cannot tell, not that nothing changed');
    }
  }

  for (const card of live.cards) {
    if (card.right > live.viewport) {
      note(`${width}px`, `"${card.title}" overflows by ${card.right - live.viewport}px`);
    }
  }
  if (live.docWidth > live.viewport + 1) {
    note(`${width}px`,
         `the page scrolls sideways (${live.docWidth} > ${live.viewport})`);
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-fixplan: FAILED');
  for (const line of failures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log('measure-fixplan: ok');
