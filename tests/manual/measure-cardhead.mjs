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

// ------------------------------------------------------------- the foot
// The head pass above builds its markup by hand, because it is about how a
// long title and a long category share one row. The foot is about what the
// server SAYS, so it drives the panel's real `makeCard` behind a stubbed
// fetch — a copy of the renderer in this file would only ever agree with
// itself, and both of these fields are new server fields that a hand-built
// fixture would go on rendering long after the panel stopped.
//
// Two things have to be readable there:
//
//   * `made_because` — why this run happened. Without it a card that
//     refreshed itself overnight is a card that changed for reasons nobody
//     can see, which is the whole reason the field exists. It must never be
//     truncated to nothing: the foot wraps rather than squeezing it out.
//   * the refresh HOLD. With `refresh_mode: changed` a card past its
//     interval has no `next_due` at all — the scheduler is waiting for
//     something the card reads to move, which has no date. The foot has to
//     say that rather than falling through to a countdown it does not have.
const NOW_ISO = new Date().toISOString();
const FOOT_STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      jobs: {}, queue_size: 0, findings_open: 0, today: {},
      categories: [
        // Waiting on its inputs: no next_due, a hold with a reason.
        { id: 'held', title: 'Energy', icon: '⚡', description: '',
          enabled: true, next_due: null,
          refresh_hold: { why: 'nothing it reads has changed',
                          at: ${Math.floor(Date.now() / 1000)} } },
        // The ordinary case, so the countdown is proved still to render.
        { id: 'due', title: 'Climate', icon: '🌡️', description: '',
          enabled: true, refresh_hold: null,
          next_due: ${Math.floor(Date.now() / 1000) + 4 * 3600} },
      ],
    });
  }
  if (p.includes('api/insights')) {
    return answer({ insights: [
      { id: 'held', category: 'held', title: 'What the house used this week',
        summary: 'Down 8% on last week.', highlights: [], html: '<p>e</p>',
        generated_at: '${NOW_ISO}', tags: [],
        made_because: '3 more finding(s) on the list',
        inputs_fingerprint: { parts: { findings: 'abc' } },
        meta: { duration_ms: 41000, cost: { total: 32100, input: 30000,
                                            output: 2100, cached: 0 } } },
      { id: 'due', category: 'due', title: 'How the rooms held heat',
        summary: 'The hall is the fast one.', highlights: [], html: '<p>c</p>',
        generated_at: '${NOW_ISO}', tags: [],
        made_because: 'you asked',
        meta: { duration_ms: 22000, cost: { total: 18000, input: 17000,
                                            output: 1000, cached: 0 } } },
    ] });
  }
  if (p.includes('api/onboarding')) return answer({ onboarded: true });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  if (p.includes('api/knowledge/cards')) {
    return answer({ cards: [], pending: [], running: [] });
  }
  return answer({});
};
`;

for (const width of [390, 768, 1200]) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page2 = await context.newPage();
  page2.on('pageerror', (e) => {
    console.log(`        - page error: ${e.message}`);
    failures += 1;
  });
  await page2.addInitScript(FOOT_STUB);
  await page2.goto(`file://${path.join(PANEL, 'index.html')}`);
  await page2.waitForSelector('.card[data-id="held"] .foot', { timeout: 5000 })
    .catch(() => { console.log('        - no card foot rendered'); failures += 1; });

  const f = await page2.evaluate(() => {
    const read = (id) => {
      const card = document.querySelector(`.card[data-id="${id}"]`);
      if (!card) return null;
      const foot = card.querySelector('.foot');
      const because = foot.querySelector('.because');
      const hold = foot.querySelector('.hold');
      const seen = (n) => {
        if (!n) return false;
        const cs = getComputedStyle(n);
        const r = n.getBoundingClientRect();
        return cs.display !== 'none' && cs.visibility !== 'hidden'
          && r.width > 0 && r.height > 0;
      };
      return {
        text: foot.textContent,
        because: because ? because.textContent.trim() : '',
        becauseSeen: seen(because),
        // Truncated to nothing is the failure this is about: half a reason
        // reads as a rendering fault rather than as a reason.
        becauseClipped: because
          ? because.scrollWidth > because.clientWidth + 1 : false,
        hold: hold ? hold.textContent.trim() : '',
        holdSeen: seen(hold),
        overflows: foot.getBoundingClientRect().right
          > card.getBoundingClientRect().right + 0.5,
      };
    };
    return { held: read('held'), due: read('due'),
             docWidth: document.documentElement.scrollWidth };
  });

  const problems = [];
  const held = f.held;
  const due = f.due;
  if (!held || !due) {
    problems.push('one of the two cards did not render');
  } else {
    if (!held.becauseSeen) problems.push('made_because is not on the foot');
    if (!/3 more finding/.test(held.because)) {
      problems.push(`made_because reads "${held.because}"`);
    }
    if (held.becauseClipped) problems.push('made_because is clipped');
    if (/inputs_fingerprint|parts|abc/.test(held.text)) {
      problems.push('the inputs fingerprint reached the screen');
    }
    // The hold wins over the countdown, and the countdown is still there
    // for a card that has one.
    if (!held.holdSeen) problems.push('a held card does not say it is waiting');
    if (!/Waiting for something to change/.test(held.hold)) {
      problems.push(`the hold reads "${held.hold}"`);
    }
    if (!/nothing it reads has changed/.test(held.hold)) {
      problems.push('the hold drops the reason the server gave');
    }
    if (/next /.test(held.text)) {
      problems.push('a held card also renders a countdown it does not have');
    }
    if (!/you asked/.test(due.because)) {
      problems.push(`the second card's reason reads "${due.because}"`);
    }
    if (!/next /.test(due.text)) {
      problems.push('an ordinary card lost its countdown');
    }
    if (due.holdSeen) problems.push('a card with no hold rendered one');
    if (held.overflows || due.overflows) problems.push('the foot overflows the card');
  }
  if (f.docWidth > width + 0.5) {
    problems.push(`page scrolls sideways (${f.docWidth}px)`);
  }

  console.log(`${problems.length ? 'FAIL' : 'ok  '} ${String(width).padStart(4)}px  `
    + `foot: reason + ${held && held.holdSeen ? 'hold' : 'no hold'}`);
  for (const p of problems) { console.log(`        - ${p}`); failures++; }
  await context.close();
}

await browser.close();
console.log(failures ? `\n${failures} problem(s)` : '\nall widths ok');
process.exit(failures ? 1 : 0);
