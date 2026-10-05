// The plan a fix run wrote, on the card that would carry it out (docs/
// design/ui-redesign-2026-10.md, "One card": keep the plan, Apply and Undo,
// and keep "What could go wrong" visible on an Apply card).
//
// The failure this exists to prevent is a press that changes somebody's
// house with nothing on screen first about what it is about to change —
// and its mirror, a change made with nothing on screen about what Undo will
// put back. So the checks are about what each card SAYS before its press:
//
//   * a planned card shows "What Apply will change", the steps in friendly
//     names, and "What could go wrong", all on its face; Apply is its one
//     primary and sends the finding's apply;
//   * a plan brAIn will not carry out says "brAIn can't apply this" with
//     its reason and offers neither Apply nor Plan;
//   * a plan written before brAIn checked each step reads "This plan is out
//     of date." and offers Plan, never Apply;
//   * a card whose plan is being written says nothing is changing yet, and
//     one being applied says so — neither offers a press;
//   * a change brAIn made says how many files and service calls BEFORE its
//     Undo, in the words Undo acts on, and a change with service calls
//     offers Restore under its ⋯;
//   * nothing overflows and nothing scrolls sideways.
//
// It drives the panel's REAL renderers behind today-fixture's stubbed fetch.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openToday, posts, FEED, kase, NOW } from './today-fixture.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

// Two cases in flight, and a change made with service calls.
const EXTRA = [
  kase({ id: 'f:1201', situation: 'planning', finding_status: 'planning', fixable: true,
         claim: 'The porch light automation never fires',
         origin: { store: 'findings', key: 1201 }, answers: [] }),
  kase({ id: 'f:1202', situation: 'fixing', finding_status: 'fixing', fixable: true,
         claim: 'The hall light automation is off', origin: { store: 'findings', key: 1202 },
         answers: [] }),
  kase({ id: 'f:1203', kind: 'change', situation: 'change', finding_status: 'fixed',
         claim: 'brAIn turned the landing heater back to its schedule',
         origin: { store: 'findings', key: 1203 }, ended: { when: NOW - 600 },
         fix_started: NOW - 700, fix_ended: NOW - 650, fix_files: 2, fix_calls: 1,
         answers: [{ verb: 'ack', label: 'Done', route: '/api/case/f:1203/do',
                     method: 'POST', primary: true },
                   { verb: 'unfix', label: 'Undo', route: '/api/finding/1203/unfix',
                     method: 'POST' }] }),
];

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

const read = (page, id) => page.evaluate((i) => {
  const c = document.querySelector(`[data-case-id="${i}"]`);
  if (!c) return null;
  const face = c.cloneNode(true);
  face.querySelectorAll('details').forEach((d) => d.remove());
  const presses = [...c.querySelectorAll(':scope > .card-actions button')]
    .filter((b) => !b.classList.contains('icon'));
  return {
    face: face.textContent,
    presses: presses.map((b) => b.textContent.trim()),
    primary: presses.filter((b) => b.classList.contains('btn-primary')).map((b) => b.textContent.trim()),
    steps: [...c.querySelectorAll(':scope > .qplan li')].map((li) => li.textContent),
    phase: c.querySelector('.phase')?.textContent || '',
    right: Math.round(c.getBoundingClientRect().right),
  };
}, id);

for (const { width, touch } of [{ width: 390, touch: true }, { width: 768, touch: false },
                                { width: 1200, touch: false }]) {
  const where = `${width}px`;
  const { page, context } = await openToday(browser, PANEL, { width, touch,
    over: { cases: [...FEED, ...EXTRA] }, onError: (m) => note(where, `page error: ${m}`) });

  const planned = await read(page, 'f:1102');
  if (!planned) note(where, 'the planned card is not drawn');
  else {
    if (!/What Apply will change/.test(planned.face)) note(where, 'the plan is not on the face');
    if (planned.steps.length !== 1 || !/Hall \(old\)/.test(planned.steps[0])
        || /binary_sensor\./.test(planned.steps[0])) {
      note(where, `the steps read ${JSON.stringify(planned.steps)}`);
    }
    if (!/What could go wrong: The hall light will not come on/.test(planned.face)) {
      note(where, '"What could go wrong" is not on the face of the Apply card');
    }
    if (planned.primary.join() !== 'Apply') note(where, `the planned card leads with ${planned.primary}`);
  }
  const refused = await read(page, 'f:1105');
  if (!refused || !/brAIn can't apply this/.test(refused.face)
      || !/doing what it was written to do/.test(refused.face)) {
    note(where, 'a refused plan does not say so, with its reason');
  }
  if (refused && refused.presses.some((p) => p === 'Apply' || p === 'Plan')) {
    note(where, `a refused plan offers ${refused.presses.join(' · ')}`);
  }
  const legacy = await read(page, 'f:1106');
  if (!legacy || !/This plan is out of date\./.test(legacy.face)) {
    note(where, 'a legacy plan does not say it is out of date');
  }
  if (legacy && (legacy.presses.includes('Apply') || legacy.primary.join() !== 'Plan')) {
    note(where, `a legacy plan offers ${legacy.presses.join(' · ')}`);
  }
  for (const [id, re] of [['f:1201', /nothing is changing yet/], ['f:1202', /Applying/]]) {
    const c = await read(page, id);
    if (!c || !re.test(c.phase)) note(where, `${id} reads "${c && c.phase}"`);
    if (c && c.presses.length) note(where, `${id} offers ${c.presses.join(' · ')} mid-run`);
  }
  const change = await read(page, 'f:1203');
  if (!change || !/brAIn changed 2 files and made 1 service call\. Undo puts the files back; the service calls are listed, not reversed\./
      .test(change.face)) {
    note(where, `a change reads "${change && change.face}"`);
  }
  if (change && change.presses.join('|') !== 'Done|Undo') {
    note(where, `a change offers ${change.presses.join(' · ')}`);
  }
  await page.evaluate(() => document.querySelector('[data-case-id="f:1203"]')
    .scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(150);
  await page.evaluate(() => document.querySelector(
    '[data-case-id="f:1203"] .card-actions .btn.icon')?.click());
  const menu = await page.evaluate(() => [...document.querySelectorAll('#chipPop .cardmenuitem b')]
    .map((b) => b.textContent));
  if (!menu.includes('Restore')) note(where, `a change with service calls offers ${menu.join(' | ')}`);
  await page.evaluate(() => document.body.click());

  // Apply sends the finding's own apply.
  await page.evaluate(() => [...document.querySelectorAll('[data-case-id="f:1102"] .card-actions button')]
    .find((b) => b.textContent.trim() === 'Apply').click());
  await page.waitForTimeout(150);
  if (!(await posts(page)).some((p) => /api\/finding\/1102\/apply$/.test(p.url))) {
    note(where, 'Apply sent nothing to the finding\'s apply');
  }
  const over = await page.evaluate(() => [...document.querySelectorAll('#findList .qcard')]
    .filter((c) => c.getBoundingClientRect().right > innerWidth + 1).length);
  if (over) note(where, `${over} cards overflow`);
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
    note(where, 'the page scrolls sideways');
  }
  await context.close();
  console.log(`${failures.length ? 'FAIL' : 'ok  '} ${where}`);
}

await browser.close();
if (failures.length) {
  console.error(`measure-fixplan: ${failures.length} failure(s)`);
  failures.forEach((f) => console.error(`  ${f}`));
  process.exit(1);
}
console.log('measure-fixplan: every plan says what it will change, and every change what Undo puts back');
