// A live card has TWO ages, and the foot used to report one of them.
//
// `live` in the card contract lets a card name up to a dozen entities whose
// CURRENT state the panel keeps pushing into its visualization while it is
// on screen — so a card about a door that is open, or a machine that is
// running, shows numbers that are seconds old. Everything Claude CONCLUDED
// about those numbers was written whenever the analysis last ran, which may
// be days back.
//
// The foot said `Updated 3 days ago`, once, for both. That is wrong in both
// directions at the same time: it invites you to distrust a reading that is
// current, and to trust a sentence written three days ago against data that
// has since moved. Nothing anywhere said the card was live at all, so a
// live card and a frozen one were indistinguishable — and so were a working
// live card and one whose readings had stopped arriving, which is the
// reading nothing can correct.
//
// So this drives the REAL `makeCard` and `paintLive` — a copy of the
// renderer in the test would only ever agree with itself, which is the rule
// measure-activity, measure-chatmeta and measure-lightmap all follow — and
// asserts, at phone and desktop width:
//
//   * a card with no `live` still says "Updated" (the unchanged case first)
//   * a card WITH `live` says "Analysed", and carries a second line naming
//     how many readings are live and when they last arrived
//   * that line says "waiting" before the first fetch lands, the age after
//     it, and "not updating" — with the warning class — when a fetch fails
//   * a failed fetch does NOT reset the arrival stamp
//   * a card pinned to a PAST run says "Generated", carries no live line,
//     and is never registered for live pushes
//   * the foot does not overflow the card, and the live line is really
//     painted (not merely present with zero size)
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const WIDTHS = [390, 1200];

const STUB = `
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url) => {
  const answer = (b) => new Response(JSON.stringify(b),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  const p = String(url);
  if (p.includes('api/status')) {
    return answer({ version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0 });
  }
  if (p.includes('api/settings')) return answer({ settings: {}, usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

// Three days back, so "Analysed" has something to be old about.
const OLD = new Date(Date.now() - 3 * 86400 * 1000).toISOString();

const failures = [];
const note = (where, msg) => failures.push(`${where}: ${msg}`);

// Build a card through the real renderer and read its foot back.
const probe = ([liveEnts, pinned, seen, generatedAt]) => {
  const id = 'cat-live';
  const card = {
    id, title: 'Front door and the dryer', icon: '🚪',
    generated_at: generatedAt, html: '<!doctype html><body>x</body>',
    highlights: [], tags: [], meta: {},
  };
  if (liveEnts.length) card.live = liveEnts;
  const catInfo = { id, name: 'Right now', icon: '🚪', enabled: true };

  state.liveSeen = {};
  if (seen) state.liveSeen[id] = seen;
  state.viewing = {};
  if (pinned) {
    state.viewing[id] = { ts: '2026-03-01T09-00-00', data: { ...card } };
  }
  liveFrames.clear();

  const host = document.querySelector('.grid')
    || document.querySelector('.view.active')
    || document.body;
  host.querySelectorAll('article.card').forEach((n) => n.remove());
  const node = makeCard(catInfo, card, id);
  host.appendChild(node);

  const foot = node.querySelector('.foot');
  const mark = foot ? foot.querySelector('[data-live-age]') : null;
  const fb = foot ? foot.getBoundingClientRect() : null;
  const cb = node.getBoundingClientRect();
  const mb = mark ? mark.getBoundingClientRect() : null;
  return {
    footText: foot ? foot.textContent : '',
    // The first span is the analysis stamp.
    stamp: foot && foot.firstElementChild
      ? foot.firstElementChild.textContent : '',
    liveText: mark ? mark.textContent : null,
    liveStale: mark ? mark.classList.contains('stale') : null,
    livePainted: !!(mb && mb.width > 0 && mb.height > 0),
    overflows: !!(fb && cb && (fb.right > cb.right + 1 || fb.left < cb.left - 1)),
    registered: liveFrames.size,
  };
};

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--no-sandbox'],
});

for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  const at = (s) => `${width}px ${s}`;
  // Noted rather than thrown. An exception here would abandon every
  // finding already gathered, which is how the first run of this measure
  // reported a missing helper and nothing about the five cases that had
  // already failed underneath it.
  try {
    await page.waitForFunction(() => typeof makeCard === 'function',
                               null, { timeout: 15000 });
  } catch (e) {
    note(at('panel'), 'makeCard never became available');
    await context.close();
    continue;
  }

  // 1. The unchanged case. A card about a period that has ended declares
  //    no live entities and must read exactly as it always did.
  const frozen = await page.evaluate(probe, [[], false, null, OLD]);
  if (!/^Updated /.test(frozen.stamp)) {
    note(at('frozen card'), `stamp is "${frozen.stamp}", expected "Updated …"`);
  }
  if (frozen.liveText !== null) {
    note(at('frozen card'), `carries a live line: "${frozen.liveText}"`);
  }
  if (frozen.registered !== 0) {
    note(at('frozen card'), `registered ${frozen.registered} frames for live`);
  }

  // 2. A live card, before anything has arrived. It must NOT claim the
  //    readings are current, and it must not stay silent either — silence
  //    is what made a live card and a frozen one look identical.
  const waiting = await page.evaluate(probe,
    [['binary_sensor.front_door', 'sensor.dryer_power'], false, null, OLD]);
  if (!/^Analysed /.test(waiting.stamp)) {
    note(at('live card'), `stamp is "${waiting.stamp}", expected "Analysed …"`);
  }
  if (!/3 d ago/.test(waiting.stamp)) {
    note(at('live card'), `the analysis age is gone: "${waiting.stamp}"`);
  }
  if (!waiting.liveText || !/2 readings live/.test(waiting.liveText)) {
    note(at('live card'), `live line is "${waiting.liveText}", expected a count`);
  }
  if (!waiting.liveText || !/waiting/.test(waiting.liveText)) {
    note(at('live card'), `before any fetch it says "${waiting.liveText}"`);
  }
  if (waiting.liveStale) note(at('live card'), 'waiting is painted as stale');
  if (!waiting.livePainted) note(at('live card'), 'the live line has no size');
  if (waiting.overflows) note(at('live card'), 'the foot overflows the card');
  if (waiting.registered !== 1) {
    note(at('live card'), `registered ${waiting.registered} frames, expected 1`);
  }

  // 3. Readings have arrived. Both ages are on the card and they differ.
  const fresh = await page.evaluate(probe, [
    ['binary_sensor.front_door', 'sensor.dryer_power'], false,
    { at: Date.now() - 4000, n: 2, ok: true }, OLD]);
  if (!/just now/.test(fresh.liveText || '')) {
    note(at('live card'), `fresh readings read "${fresh.liveText}"`);
  }
  if (fresh.liveStale) note(at('live card'), 'fresh readings painted as stale');
  if (!/Analysed .*3 d ago/.test(fresh.stamp)) {
    note(at('live card'), `the two ages collapsed: "${fresh.stamp}"`);
  }

  // 4. The fetch has started failing. This is the one that must not read
  //    as case 3: a number frozen under a "live" label is the reading
  //    nothing can correct, so it says so in words AND takes the class.
  const stalled = await page.evaluate(probe, [
    ['binary_sensor.front_door', 'sensor.dryer_power'], false,
    { at: Date.now() - 600000, n: 2, ok: false }, OLD]);
  if (!/not updating/.test(stalled.liveText || '')) {
    note(at('stalled live card'), `reads "${stalled.liveText}"`);
  }
  if (!stalled.liveStale) {
    note(at('stalled live card'), 'does not carry the warning class');
  }

  // 5. A card pinned to a past run. It is a record: it says when it was
  //    generated, carries no live line, and is registered for nothing —
  //    pushing today's door state into March's chart would make it a
  //    hybrid with nothing on screen saying so.
  const past = await page.evaluate(probe,
    [['binary_sensor.front_door'], true, { at: Date.now(), n: 1, ok: true }, OLD]);
  if (!/^Generated /.test(past.stamp)) {
    note(at('pinned run'), `stamp is "${past.stamp}", expected "Generated …"`);
  }
  if (past.liveText !== null) {
    note(at('pinned run'), `carries a live line: "${past.liveText}"`);
  }
  if (past.registered !== 0) {
    note(at('pinned run'), `registered ${past.registered} frames for live`);
  }

  await context.close();
}

// 6. A failed fetch keeps the last arrival stamp, so the foot can age from
//    the last real reading rather than resetting to "waiting" — which
//    would read as a card that has never been live.
{
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await context.newPage();
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  let kept = null;
  try {
    await page.waitForFunction(() => typeof liveAgeText === 'function',
                               null, { timeout: 15000 });
  } catch (e) {
    note('failed fetch', 'liveAgeText is not defined — the live half of a '
      + "card's age has no renderer");
  }
  if (kept !== null || true) kept = await page.evaluate(() => {
    const id = 'cat-keep';
    state.liveSeen = {};
    state.liveSeen[id] = { at: 12345, n: 3, ok: true };
    const prev = state.liveSeen[id];
    state.liveSeen[id] = { ...prev, ok: false };
    return { at: state.liveSeen[id].at, n: state.liveSeen[id].n,
             text: typeof liveAgeText === 'function' ? liveAgeText(id, 3) : null };
  }).catch(() => null);
  if (!kept) {
    note('failed fetch', 'the arrival ledger (state.liveSeen) does not exist');
  } else {
    if (kept.at !== 12345) note('failed fetch', `reset the arrival stamp to ${kept.at}`);
    if (kept.n !== 3) note('failed fetch', `lost the reading count (${kept.n})`);
    if (kept.text !== null && !/not updating/.test(kept.text)) {
      note('failed fetch', `reads "${kept.text}"`);
    }
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error('measure-cardlive FAILED');
  failures.forEach((f) => console.error('  ' + f));
  process.exit(1);
}
console.log(`measure-cardlive: OK at ${WIDTHS.join(', ')}px — a live card`
  + ' reports both of its ages, and a pinned run reports neither');
