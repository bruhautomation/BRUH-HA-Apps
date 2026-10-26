// What a typed request is told it is doing, through the panel's REAL
// `generate` behind a stubbed fetch, at a phone (390, touch) and a desktop
// (1200).
//
// Scenes and rules asked for were always toasted as "They land on
// Proposals in a moment" / "Nothing runs until you accept it" — true with
// "Let brAIn act without asking" off, and a lie with it (or YOLO mode) on,
// when the server writes them straight away and says so (`say`,
// `intent_say`). The toast says the server's sentence when it has one, and
// the old one only when it does not; neither names a tab that no longer
// exists.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const CASES = [
  { width: 390, touch: true },
  { width: 1200, touch: false },
];

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.__generate = {};
window.fetch = async (url, opts = {}) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/generate')) return answer(window.__generate);
  if (p.includes('api/status')) {
    return answer({ version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {}, categories: [],
      jobs: {}, queue_size: 0, findings_open: 0 });
  }
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) return answer({ findings: [], hypotheses: [], open: 0 });
  if (p.includes('api/todo')) return answer({ items: [], done: [], open: 0 });
  return answer({});
};
`;

// What each shape of answer must toast, and what it must not.
const SHAPES = [
  { name: 'scenes written straight away',
    res: { queued: [], scenes: 'Den', lights: 3, count: 4, acts: true,
           say: 'brAIn is writing 4 lighting moods for the Den into your scenes now.' },
    want: /writing 4 lighting moods for the Den/, not: /accept|Proposals/ },
  { name: 'scenes offered',
    res: { queued: [], scenes: 'Den', lights: 3, count: 4, acts: false,
           say: 'brAIn is designing 4 lighting moods for the Den — they will be offered for you to accept.' },
    want: /offered for you to accept/, not: /Proposals/ },
  { name: 'an older server that sends no sentence',
    res: { queued: [], scenes: 'Den', lights: 3 },
    want: /Designing four scenes for the Den/, not: /Proposals/ },
  { name: 'a rule written straight away',
    res: { queued: [], intent: 'q1', intent_say: 'brAIn is writing that as an automation now.' },
    want: /writing that as an automation now/, not: /Nothing runs until you accept/ },
  { name: 'a rule read by the interpreter and written',
    res: { queued: [], routes: ['standing_rule'], intent: 'q1',
           intent_say: 'brAIn is writing that as an automation now.' },
    want: /writing that as an automation now/, not: /nothing runs until you accept/i },
];

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const { width, touch } of CASES) {
  const where = `${width}px`;
  const context = await browser.newContext({
    viewport: { width, height: 860 }, hasTouch: touch, isMobile: touch });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(where, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page.waitForFunction(() => typeof generate === 'function', null,
    { timeout: 5000 }).catch(() => note(where, 'the panel did not load'));
  for (const shape of SHAPES) {
    const said = await page.evaluate(async (res) => {
      window.__generate = res;
      await generate(null, 'make the den cosy');
      const t = document.querySelector('#toast');
      const r = t.getBoundingClientRect();
      return { text: t.textContent, w: r.width, right: r.right };
    }, shape.res);
    if (!shape.want.test(said.text)) note(where, `${shape.name}: toasted "${said.text}"`);
    if (shape.not.test(said.text)) note(where, `${shape.name}: still says "${said.text}"`);
    if (said.right > width + 1) note(where, `${shape.name}: the toast runs off the screen`);
    if (process.env.SHOTS && shape === SHAPES[0]) {
      await page.screenshot({ path: path.join(process.env.SHOTS,
        `asktoast-${width}${process.env.SHOT_TAG || ''}.png`) });
    }
  }
  await context.close();
}

await browser.close();
if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log(`ok: ${SHAPES.length} answers toasted at ${CASES.length} widths`);
