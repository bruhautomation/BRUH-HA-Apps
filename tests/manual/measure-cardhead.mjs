// Render one insight card at real phone widths and assert the head lays out
// the way it is meant to.
//
// The bug this exists to prevent: the head used to be a single flex row of
// icon + category + title + SIX `flex: none` icon buttons. On a 390px card
// the buttons took roughly 250px, leaving the words about 120px — so the
// category (which wraps) ran to three lines and the title (which ellipsises)
// was cut to "Upstair…". Exactly backwards: the eyebrow is the part you can
// afford to lose, and the title is what the card IS.
//
// So the checks are, at every width:
//
//   * the title renders more than a truncation stub — measured against the
//     full text, not against a pixel count, because "did it fit" is the
//     question and font metrics differ per platform
//   * the category is ONE line (it is the thing that gives way)
//   * the head does not overflow the card
//   * every button in the head is a real touch target (>=40px)
//
// Standalone like measure-topbar.mjs: the panel's JS wants a live backend,
// so the markup is built by hand to match what makeCard() emits.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

// The card from the screenshot that started this: a long category name and a
// long title, which is the case that broke.
const CATEGORY = 'Upstairs vs Downstairs Cooling';
const TITLE = 'Upstairs runs 94% more cooling than downstairs on hot days';

const WIDTHS = [320, 360, 390, 430, 768, 1024, 1440];
const MIN_TARGET = 40;

const page_html = `
<main class="wrap"><div class="view active"><div class="grid">
  <article class="card">
    <div class="card-head">
      <span class="cicon">🌡️</span>
      <div class="ctitles">
        <div class="cat">${CATEGORY}</div>
        <h3>${TITLE}</h3>
      </div>
      <div class="actions">
        <button class="btn icon">⤢</button>
        <button class="btn icon">⋯</button>
      </div>
    </div>
    <div class="summary">On today's hot day upstairs logged 8h 28m of cooling
      vs downstairs' 4h 22m.</div>
  </article>
</div></div></main>`;

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage();
let failures = 0;

for (const width of WIDTHS) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto('about:blank');
  await page.setContent(page_html);
  await page.addStyleTag({ path: path.join(PANEL, 'style.css') });
  await page.evaluate(() => document.documentElement.style.setProperty('--bar-h', '56px'));

  const m = await page.evaluate(() => {
    const head = document.querySelector('.card-head');
    const card = document.querySelector('.card');
    const h3 = head.querySelector('h3');
    const cat = head.querySelector('.cat');
    const lineHeight = (node) => {
      const r = node.getBoundingClientRect();
      const cs = getComputedStyle(node);
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
      return Math.round(r.height / lh);
    };
    return {
      headRight: head.getBoundingClientRect().right,
      cardRight: card.getBoundingClientRect().right,
      titleWidth: h3.getBoundingClientRect().width,
      titleLines: lineHeight(h3),
      titleScrollW: h3.scrollWidth,
      titleClientW: h3.clientWidth,
      catLines: lineHeight(cat),
      docWidth: document.documentElement.scrollWidth,
      targets: [...head.querySelectorAll('button')].map((b) => {
        const r = b.getBoundingClientRect();
        return { text: b.textContent.trim(), w: Math.round(r.width), h: Math.round(r.height) };
      }),
    };
  });

  const problems = [];
  // The title is allowed to clamp at two lines, but it must be given the
  // room to USE them — a one-line title cut off mid-word is the old bug.
  if (m.titleLines < 2 && m.titleScrollW > m.titleClientW + 1) {
    problems.push(`title truncated on one line (${m.titleScrollW}px into ${m.titleClientW}px)`);
  }
  if (m.catLines !== 1) problems.push(`category ran to ${m.catLines} lines`);
  if (m.headRight > m.cardRight + 0.5) problems.push('head overflows the card');
  if (m.docWidth > width + 0.5) problems.push(`page scrolls sideways (${m.docWidth}px)`);
  for (const t of m.targets) {
    if (t.w < MIN_TARGET || t.h < MIN_TARGET) {
      problems.push(`target "${t.text}" is ${t.w}x${t.h}, under ${MIN_TARGET}px`);
    }
  }

  const status = problems.length ? 'FAIL' : 'ok  ';
  console.log(`${status} ${String(width).padStart(4)}px  `
    + `title ${Math.round(m.titleWidth)}px/${m.titleLines}ln  cat ${m.catLines}ln  `
    + `buttons ${m.targets.length}`);
  for (const p of problems) { console.log(`        - ${p}`); failures++; }
}

await browser.close();
console.log(failures ? `\n${failures} problem(s)` : '\nall widths ok');
process.exit(failures ? 1 : 0);
