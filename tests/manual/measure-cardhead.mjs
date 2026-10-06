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
        <button class="btn small cardask">Ask</button>
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
      titleScrollH: h3.scrollHeight,
      titleClientH: h3.clientHeight,
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
  // And it is never clamped at all. Refine and Share joined the head in
  // 2.8, four buttons are ~170px of a phone's row, and the first cut came
  // out "Downstairs dries 15…" — which is why a narrow card gives the title
  // a row of its own under the buttons.
  if (m.titleScrollH > m.titleClientH + 1) {
    problems.push(`title clamped (${m.titleScrollH}px of text in ${m.titleClientH}px)`);
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
// long title and a long category share one row. The rest drives the
// panel's real `makeCard` behind a stubbed fetch — a copy of the renderer
// in this file would only ever agree with itself.
//
// A report is read, not decided, so what it carries is its headline and
// one age (docs/design/ui-redesign-2026-10.md, House › Reports):
//
//   * the foot says "Updated N ago" and nothing else — no token count, no
//     reason it ran, no refresh hold, no next-due countdown. The stub hands
//     the renderer every one of those so their absence is a claim, not a
//     fixture that never had them.
//   * the head carries Ask and ⋯ and nothing else (✎ ↗ ⤢ and the ‹ Latest ▾
//     steppers are cut), ⋯ holds exactly Share · Past versions · Run ·
//     Delete, and a press on the card opens it full size.
//   * Ask opens the card's dialog, whose links still reach "Make this an
//     automation" (drafted into the Ask tab's composer, never sent) and
//     "See the automation it suggested" (Today, where suggestions are queued).
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
        { id: 'held', title: 'Energy', icon: '⚡', description: '',
          enabled: true, next_due: null,
          refresh_hold: { why: 'nothing it reads has changed',
                          at: ${Math.floor(Date.now() / 1000)} } },
        { id: 'due', title: 'Climate', icon: '🌡️', description: '',
          enabled: true, refresh_hold: null,
          next_due: ${Math.floor(Date.now() / 1000) + 4 * 3600} },
      ],
    });
  }
  if (p.includes('api/insight/') && p.includes('/history')) {
    return answer({ runs: [] });
  }
  if (p.includes('api/insight/') && p.includes('/feedback')) {
    return answer({ feedback: [] });
  }
  if (p.includes('api/insights')) {
    return answer({ insights: [
      { id: 'held', category: 'held', title: 'What the house used this week',
        summary: 'Down 8% on last week.', highlights: [], html: '<p>e</p>',
        generated_at: '${NOW_ISO}', tags: ['energy', 'solar'],
        made_because: '3 new findings',
        inputs_fingerprint: { parts: { findings: 'abc' } },
        opportunities: [{ text: 'When the back door opens after sunset, '
            + 'turn on the patio light',
          sentence: 'When the back door opens after sunset, turn on the '
            + 'patio light',
          entities: ['light.patio'], queued: false,
          why: 'automatic runs are paused' }],
        meta: { duration_ms: 41000, cost: { total: 32100, input: 30000,
                                            output: 2100, cached: 0 } } },
      { id: 'due', category: 'due', title: 'How the rooms held heat',
        summary: 'The hall is the fast one.', highlights: [], html: '<p>c</p>',
        generated_at: '${NOW_ISO}', tags: [],
        made_because: 'you asked',
        opportunities: [{ text: 'Turn the porch light off at midnight',
          sentence: 'From now on, turn the porch light off at midnight',
          entities: [], queued: true, why: '' }],
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

const CUT_FROM_A_CARD = [
  /tokens/i, /3 new findings/, /you asked/, /Waiting for something/,
  /\bnext\b/, /Analysed/, /readings live/, /Make recurring/, /#energy/,
];

for (const width of [390, 768, 1200]) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page2 = await context.newPage();
  page2.on('pageerror', (e) => {
    console.log(`        - page error: ${e.message}`);
    failures += 1;
  });
  await page2.addInitScript(FOOT_STUB);
  await page2.goto(`file://${path.join(PANEL, 'index.html')}`);
  // The panel opens on Today now; the cards are House › Reports.
  await page2.waitForFunction(() => typeof switchView === 'function');
  await page2.evaluate(() => switchView('insights'));
  await page2.waitForSelector('.card[data-id="held"] .foot', { timeout: 5000 })
    .catch(() => { console.log('        - no card foot rendered'); failures += 1; });

  const f = await page2.evaluate(() => {
    const read = (id) => {
      const card = document.querySelector(`.card[data-id="${id}"]`);
      if (!card) return null;
      const foot = card.querySelector('.foot');
      return {
        foot: foot.textContent.replace(/\s+/g, ' ').trim(),
        card: card.textContent.replace(/\s+/g, ' ').trim(),
        head: [...card.querySelectorAll('.card-head .actions button')]
          .map((b) => b.textContent.trim()),
        tagRows: card.querySelectorAll('.tagrow, .tagchip').length,
        steppers: card.querySelectorAll('.hist, .histsel, .hstep').length,
        overflows: foot.getBoundingClientRect().right
          > card.getBoundingClientRect().right + 0.5,
      };
    };
    return { held: read('held'), due: read('due'),
             filters: document.querySelectorAll('#filters .fchip, .fchip').length,
             askBar: !!document.getElementById('askForm'),
             docWidth: document.documentElement.scrollWidth };
  });

  const problems = [];
  const held = f.held;
  const due = f.due;
  if (!held || !due) {
    problems.push('one of the two cards did not render');
  } else {
    for (const c of [held, due]) {
      if (!/^Updated /.test(c.foot)) problems.push(`the foot reads "${c.foot}"`);
      for (const cut of CUT_FROM_A_CARD) {
        if (cut.test(c.card)) problems.push(`cut text is back on a card: ${cut}`);
      }
      if (JSON.stringify(c.head) !== JSON.stringify(['Ask', '⋯'])) {
        problems.push(`the head carries ${JSON.stringify(c.head)}, not Ask · ⋯`);
      }
      if (c.tagRows) problems.push('a card renders tag chips');
      if (c.steppers) problems.push('a card renders the ‹ Latest ▾ steppers');
      if (c.overflows) problems.push('the foot overflows the card');
    }
    if (/inputs_fingerprint|parts|abc/.test(held.card)) {
      problems.push('the inputs fingerprint reached the screen');
    }
  }
  if (f.filters) problems.push(`${f.filters} tag chips above the reports`);
  if (f.askBar) problems.push('the second ask box is back on Reports');
  if (f.docWidth > width + 0.5) {
    problems.push(`page scrolls sideways (${f.docWidth}px)`);
  }

  // ⋯ holds exactly the four, in the doc's order.
  const menu = await page2.evaluate(async () => {
    const card = document.querySelector('.card[data-id="held"]');
    const more = [...card.querySelectorAll('.actions button')]
      .find((b) => b.textContent.trim() === '⋯');
    more.click();
    await new Promise((r) => setTimeout(r, 50));
    const rows = [...document.querySelectorAll('#chipPop .cardmenuitem b')]
      .map((b) => b.textContent);
    document.body.click();
    return rows;
  });
  if (JSON.stringify(menu) !== JSON.stringify(['Share', 'Past versions', 'Run', 'Delete'])) {
    problems.push(`⋯ holds ${JSON.stringify(menu)}`);
  }

  // A press on the card (not on a control) opens it full size.
  const opened = await page2.evaluate(async () => {
    const card = document.querySelector('.card[data-id="held"]');
    card.querySelector('.summary').click();
    await new Promise((r) => setTimeout(r, 50));
    const on = document.getElementById('modal').classList.contains('open');
    document.getElementById('modalClose').click();
    return on;
  });
  if (!opened) problems.push('pressing the card does not open it');

  // Ask: the card's dialog, and the automation links inside it.
  const ask = (id) => page2.evaluate(async (cardId) => {
    const card = document.querySelector(`.card[data-id="${cardId}"]`);
    [...card.querySelectorAll('.actions button')]
      .find((b) => b.textContent.trim() === 'Ask').click();
    await new Promise((r) => setTimeout(r, 60));
    return {
      open: document.getElementById('refineModal').classList.contains('open'),
      title: document.getElementById('refineTitle').textContent,
      send: document.getElementById('refineGo').textContent.trim(),
      links: [...document.querySelectorAll('#refineMore .refinelink')]
        .map((a) => a.textContent),
    };
  }, id);
  const pressLink = (label) => page2.evaluate(async (want) => {
    const a = [...document.querySelectorAll('#refineMore .refinelink')]
      .find((x) => x.textContent === want);
    if (!a) return null;
    a.click();
    await new Promise((r) => setTimeout(r, 80));
    const input = document.getElementById('chatInput');
    return {
      value: input ? input.value : null,
      ask: !!document.querySelector('#viewTerminal.active'),
      today: !!document.querySelector('#viewFindings.active'),
    };
  }, label);

  const heldAsk = await ask('held');
  if (!heldAsk.open) problems.push('Ask does not open the card\'s dialog');
  if (heldAsk.send !== 'Send') problems.push(`the dialog's button reads "${heldAsk.send}"`);
  if (!heldAsk.links.includes('Make this an automation')) {
    problems.push(`the dialog does not offer the automation (${JSON.stringify(heldAsk.links)})`);
  } else {
    const after = await pressLink('Make this an automation');
    if (!after || !after.ask) problems.push('the automation link did not open the Ask tab');
    if (!after || after.value !== 'When the back door opens after sunset, turn on the patio light') {
      problems.push(`the composer holds "${after && after.value}"`);
    }
  }
  await page2.evaluate(() => {
    document.getElementById('chatInput').value = '';
    document.querySelector('.viewtab[data-group="insights"]').click();
  });
  await page2.evaluate(() => {
    const b = document.querySelector('#segNav .segbtn[data-view="insights"]');
    if (b) b.click();
  });
  const dueAsk = await ask('due');
  if (!dueAsk.links.includes('See the automation it suggested')) {
    problems.push(`a card whose suggestion was offered does not point at it (${JSON.stringify(dueAsk.links)})`);
  } else {
    const after = await pressLink('See the automation it suggested');
    // A suggestion is a card in Today's queue now; Proposals is not a tab.
    if (!after || !after.today) problems.push('"See the automation" did not open Today');
  }

  console.log(`${problems.length ? 'FAIL' : 'ok  '} ${String(width).padStart(4)}px  `
    + 'foot: one age; head: Ask · ⋯; menu: four');
  for (const p of problems) { console.log(`        - ${p}`); failures++; }
  await context.close();
}

await browser.close();
console.log(failures ? `\n${failures} problem(s)` : '\nall widths ok');
process.exit(failures ? 1 : 0);
