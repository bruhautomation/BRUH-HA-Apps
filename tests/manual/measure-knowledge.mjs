// Render the Knowledge tab against a house mid-measurement and assert every
// row answers the question the tab exists to answer.
//
// The failure this exists to prevent is the one the tab was built for: a
// measurement that has stopped, one that has not started, and a house with
// nothing odd in it are three silences that used to look identical from
// every screen. So the checks are about what a row SAYS as much as where it
// sits:
//
//   * all seven stores render, in order, whatever state each is in. A store
//     that drops out of the list is a store nobody can ask about, and the
//     day you install this six of the seven have nothing to say.
//   * every row carries its state chip with words in it. A row with no chip
//     is a row that cannot tell "collecting" from "stopped".
//   * a `reason` in the payload is visible on screen. "I could not look" is
//     the half that says which silence this is, and a reason rendered into a
//     node nobody can see is the same as no reason at all.
//   * pressing a row opens its drill-down, and pressing another closes the
//     first — one at a time, or seven answers become a page with no shape.
//   * the baselines chart really draws: a week with 168 buckets of data and
//     an empty <svg> look identical from a screenshot, so the nodes are
//     COUNTED.
//   * no row is under the touch floor, and nothing scrolls sideways.
//
// Plus a second pass over the Today strip, on five status shapes, because
// none is a superset of the others: everything present, a partial payload
// (segments must be omitted, not rendered as zeroes), a pass in flight with
// no elapsed and one with, and a status where nothing has run at all — which
// has to leave the strip HIDDEN rather than empty.
//
// Like measure-activity.mjs, this drives the panel's REAL renderers behind a
// stubbed fetch. A copy of renderHouse in this file would only ever agree
// with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 768, 1200];
const MIN_TARGET = 44;

// The seven stores, in the order the tab renders them, and the label each
// one has to keep. Order is part of the contract: this is a list somebody
// learns the shape of.
const STORES = [
  ['rhythm', 'When the house wakes'],
  ['baselines', 'What is normal here'],
  ['thermal', 'How rooms hold heat'],
  ['closures', 'Doors and windows'],
  ['appliances', 'Machines'],
  ['habits', 'Habits'],
  ['energy', 'Energy this week'],
];

const NOW = Math.floor(Date.now() / 1000);

// One house with all five states on it at once. That is not a realistic
// morning and it is the point: every state has to render, and the ones that
// only happen in the first fortnight of an install are exactly the ones
// nobody sees again.
const HOUSE = {
  generated_at: NOW,
  brief: {
    enabled: true, last_sent: NOW - 3 * 3600, error: '',
    text: 'The freezer has been drifting warmer for a week and the hall '
      + 'motion sensor stopped reporting on Tuesday.',
    reasons: ['base.trend', 'dev.unavailable'],
    fallback_hour: 7, wake_measured: true,
  },
  weekly: {
    enabled: true, last_sent: NOW - 2 * 86400, error: '', day: 'sun',
    text: 'Two problems turned up and both are still open.',
  },
  stores: {
    rhythm: {
      state: 'ready', have: 21, need: 7, unit: 'days', reason: '',
      ready_at: 0, updated_at: NOW - 7200,
      summary: 'Up about 07:05 on weekdays, settles about 23:10',
      detail: {},
    },
    baselines: {
      state: 'ready', have: 480, need: 480, unit: 'sensors', reason: '',
      ready_at: 0, updated_at: NOW - 30 * 3600,
      summary: '480 sensors measured, hour by hour of the week', detail: {},
    },
    thermal: {
      state: 'collecting', have: 9, need: 30, unit: 'days',
      reason: 'A month of hourly statistics is what the fit needs.',
      ready_at: NOW + 21 * 86400, updated_at: NOW - 86400,
      summary: 'Measuring how fast each room loses heat', detail: {},
    },
    closures: {
      state: 'stale', have: 6, need: 6, unit: 'doors',
      reason: 'The nightly pass has not run since Tuesday.',
      ready_at: 0, updated_at: NOW - 5 * 86400,
      summary: '6 doors and windows watched', detail: {},
    },
    appliances: {
      state: 'unavailable', have: 0, need: 0, unit: 'machines',
      reason: 'The recorder answered nothing for those power sensors.',
      ready_at: 0, updated_at: 0,
      summary: 'No machine has a measured shape', detail: {},
    },
    habits: {
      state: 'not_started', have: 0, need: 6, unit: 'days', reason: '',
      ready_at: 0, updated_at: 0,
      summary: 'Nothing you do by hand has happened often enough yet',
      detail: {},
    },
    energy: {
      state: 'collecting', have: 3, need: 7, unit: 'days',
      reason: 'Home Assistant’s energy dashboard names one grid meter.',
      ready_at: 0, updated_at: NOW - 3600,
      summary: 'Waiting on a full week of complete days', detail: {},
    },
  },
};

// A week of buckets with a deliberate hole in it: a gap in the data has to
// break the line rather than be drawn through, and 168 filled buckets would
// never exercise that.
const BUCKETS = (() => {
  const out = {};
  for (let i = 0; i < 168; i += 1) {
    if (i % 24 === 3) continue;  // nothing measured at 3am
    const hour = i % 24;
    out[String(i)] = {
      median: 18 + Math.sin((hour / 24) * Math.PI * 2) * 3,
      spread: 0.6 + (hour % 5) * 0.1,
      n: 4,
    };
  }
  return out;
})();

// The drill-down payloads, in the shapes `server.h_house_store` really
// answers with — two of the seven are a bare list and the rest name one,
// which is exactly the difference a renderer that only knows one reports as
// an empty house.
const DRILLS = {
  // rhythm.profile()
  rhythm: {
    days: 21, updated_at: NOW - 7200,
    weekday: { wakes: { at: '07:05', spread_min: 18, days: 15 },
               settles: { at: '23:10', spread_min: 24, days: 15 } },
    weekend: { wakes: { at: '08:40', spread_min: 31, days: 6 },
               settles: { at: '23:55', spread_min: 20, days: 6 } },
  },
  // _baselines_rows() — a bare list
  baselines: [
    { entity_id: 'sensor.freezer_temp', name: 'Freezer temperature',
      unit: '°C', flat: false, buckets_n: 161, trend: { per_day: 0.31 } },
    { entity_id: 'sensor.hall_humidity', name: 'Hall humidity',
      unit: '%', flat: false, buckets_n: 168, trend: null },
    { entity_id: 'sensor.boiler_flow', name: 'Boiler flow',
      unit: '°C', flat: true, buckets_n: 0, trend: null },
  ],
  // _thermal_payload()
  thermal: {
    outdoor: 'sensor.outside_temperature', unit: '°C',
    rooms: [
      { id: 'sensor.bedroom_temp', name: 'Bedroom', area: 'Bedroom',
        k: 0.081, tau_h: 12.3, gain: 1.9, warmest: 21.5, coolest: 16.1,
        hours_to_warm: 1.4 },
      { id: 'sensor.hall_temp', name: 'Hall', area: 'Hall',
        k: 0.19, tau_h: 5.2, gain: 1.1, warmest: 19.9, coolest: 13.4,
        hours_to_warm: 2.8 },
    ],
  },
  // _closure_rows() — a bare list, and each bucket is the open FRACTION
  // itself rather than the store's `{open, hours}`.
  closures: [{
    entity_id: 'binary_sensor.back_door', name: 'Back door', overall: 0.07,
    buckets: (() => {
      const b = {};
      for (let i = 0; i < 168; i += 1) {
        if (i % 17 === 0) continue;   // an hour nothing watched
        b[String(i)] = (i % 24) / 40;
      }
      return b;
    })(),
  }],
  // _appliance_detail() — the store has no shapes at all, which is the
  // `unavailable` this house is in.
  appliances: { built_at: 0, asked: 0, days: 10, hours: 14,
                live_error: '', appliances: [] },
  // _habits_payload() — `routines` is an object ABOUT the ledger with the
  // mined rows inside it, not a list of them.
  habits: {
    routines: {
      presses: 340, automated: 2,
      rows: [
        { entity_id: 'light.porch', name: 'Porch light', state: 'on',
          at: '18:40', days: 11, eligible_days: 14, share: 0.79,
          when_days: 'every day', proposable: true },
      ],
    },
    overrides: { events: 9, automations: 1, recent: [] },
    patterns: [
      { automation: 'automation.evening', name: 'Evening lights',
        events: 9, days: 6, from_hour: 7, to_hour: 9 },
    ],
  },
  // energy.week()
  energy: {
    available: true, reason: '', from: NOW - 7 * 86400, to: NOW,
    energy: { this: 71.4, last: 63.2, change_pct: 13.0, days: 7,
              days_before: 7, comparable: true, unit: 'kWh' },
    cost: { this: 18.9, last: 16.7, change_pct: 13.2, days: 7,
            days_before: 7, comparable: true, unit: 'GBP' },
  },
};

// Everything present. The two partial shapes are derived from it in the
// Today pass, so they can never drift from the full one.
const TODAY_FULL = {
  checks: { last_at: NOW - 1800, ran: 12, skipped: 1, errored: 0, created: 2,
            cleared: 1, next_at: NOW + 20000, running: false },
  baselines: { built_at: NOW - 40000, next_at: NOW + 46000, running: false,
               error: '' },
  memory: { last_filed_at: NOW - 7200, waiting: 3, running: false },
  reports: { since_yesterday: 1 },
  landed_runs_24h: 1,
};

const STUB = `
window.__house = ${JSON.stringify(HOUSE)};
window.__drills = ${JSON.stringify(DRILLS)};
window.__buckets = ${JSON.stringify(BUCKETS)};
window.__today = ${JSON.stringify(TODAY_FULL)};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body, status) => new Response(JSON.stringify(body), {
    status: status || 200, headers: { 'Content-Type': 'application/json' } });
  // Before the bare \`api/knowledge\` branch: these paths contain it.
  if (p.includes('api/knowledge/card/')) {
    // The 409 is not an error state — the measurement really has no answer
    // right now — so it has to reach the panel as a sentence.
    if (window.__refuseRefresh) {
      return answer({ error: 'that measurement does not have an answer right now',
                      state: 'stale', reason: '' }, 409);
    }
    window.__refreshed = (window.__refreshed || 0) + 1;
    return answer({ id: p.split('api/knowledge/card/')[1].split('/')[0],
                    queued: true });
  }
  if (p.includes('api/knowledge/cards')) {
    return answer(window.__cards || { cards: [], pending: [], running: [] });
  }
  if (p.includes('api/knowledge/house/')) {
    const id = p.split('api/knowledge/house/')[1].split('?')[0];
    return answer(window.__drills[id] || {});
  }
  if (p.includes('api/knowledge/house')) return answer(window.__house);
  // h_baselines: the store's own progress, and the ONE entity under
  // \`baseline\` — the chart is about the entity, not the store.
  if (p.includes('api/baselines')) {
    return answer({
      built_at: ${NOW - 30 * 3600}, tz: 'Europe/London', days: 30,
      measured: 480, stale: false, running: false, last: {},
      entity_id: 'sensor.freezer_temp',
      baseline: { name: 'Freezer temperature', unit: '\\u00b0C',
                  buckets: window.__buckets, flat: false,
                  overall: { median: 18.2, spread: 0.7, n: 700 },
                  trend: { per_day: 0.31 } },
    });
  }
  if (p.includes('api/knowledge')) {
    return answer({
      inbox: [{ id: 'a1', ts: ${NOW - 900}, source: 'analyst',
                text: 'The garage fridge runs all night on purpose.' }],
      inbox_pending: 1,
      shared_memory: '# Home Memory\\n\\n- The hall light is on a timer.\\n',
      memory_state: { merging: false, running: false, stale_hours: 0, error: '' },
    });
  }
  if (p.includes('api/memory/state')) {
    return answer({ memory_state: { merging: false, running: false } });
  }
  // The shape the panel actually READS. /api/status is dereferenced
  // unguarded in several places, so a stub that omits a key throws a page
  // error seconds later — which this file fails on, and which has nothing
  // to do with the tab under test.
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
      today: window.__today,
    });
  }
  if (p.includes('api/onboarding')) return answer({ onboarded: true });
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

async function openPanel(width, extra, touch) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    ...(touch ? { hasTouch: true, isMobile: true } : {}),
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(`${width}px`, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  if (extra) await page.addInitScript(extra);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  return { context, page };
}

// ---------------------------------------------------------------- the tab
for (const width of WIDTHS) {
  const { context, page } = await openPanel(width);
  await page.click('.viewtab[data-view="memory"]');
  await page.waitForSelector('#kStores .krow');

  const m = await page.evaluate(() => {
    const seen = (node) => {
      if (!node) return false;
      const cs = getComputedStyle(node);
      return cs.display !== 'none' && cs.visibility !== 'hidden'
        && node.getBoundingClientRect().height > 0;
    };
    const host = document.getElementById('kStores').getBoundingClientRect();
    return {
      rows: [...document.querySelectorAll('#kStores .krow')].map((r) => {
        const box = r.getBoundingClientRect();
        const why = r.querySelector('.kwhy');
        const chip = r.querySelector('.kchip');
        return {
          store: r.dataset.store,
          state: r.dataset.state,
          name: (r.querySelector('.kname') || {}).textContent || '',
          summary: (r.querySelector('.ksum') || {}).textContent || '',
          chip: chip ? chip.textContent.trim() : '',
          why: why ? why.textContent.trim() : '',
          whyShown: seen(why),
          h: Math.round(box.height),
          right: box.right,
        };
      }),
      briefText: (document.getElementById('kBrief') || {}).textContent || '',
      // The four sections, in order, by the headings and hosts that name
      // them. Order is the contract: this is a page somebody reads down.
      sections: [...document.querySelectorAll(
        '#viewMemory h2, #viewMemory label')].map((n) => n.textContent.trim()),
      hostRight: host.right,
      docWidth: document.documentElement.scrollWidth,
    };
  });

  if (m.rows.length !== STORES.length) {
    note(`${width}px`, `${m.rows.length} store rows for ${STORES.length} stores`);
  }
  STORES.forEach(([id, label], i) => {
    const row = m.rows[i];
    if (!row) { note(`${width}px`, `no row for ${id}`); return; }
    if (row.store !== id) {
      note(`${width}px`, `row ${i} is ${row.store}, expected ${id}`);
    }
    if (row.name.trim() !== label) {
      note(`${width}px`, `${id} is called "${row.name.trim()}", not "${label}"`);
    }
    if (!row.chip) note(`${width}px`, `${id} renders no state chip`);
    if (!row.summary.trim()) note(`${width}px`, `${id} renders no summary`);
    if (row.h < MIN_TARGET) {
      note(`${width}px`, `row ${id} is ${row.h}px, under ${MIN_TARGET}`);
    }
    if (row.right > m.hostRight + 0.5) note(`${width}px`, `row ${id} overflows`);
    // The reason is the half that says WHICH silence this is.
    const expected = String(HOUSE.stores[id].reason || '');
    if (expected && !row.whyShown) {
      note(`${width}px`, `${id} has a reason and does not show it`);
    }
    if (expected && row.why && !expected.startsWith(row.why.slice(0, 12))) {
      note(`${width}px`, `${id} shows a reason that is not its own`);
    }
  });
  // The chips have to distinguish the states, not just exist.
  const chipOf = (id) => (m.rows.find((r) => r.store === id) || {}).chip || '';
  if (!/not started/i.test(chipOf('habits'))) {
    note(`${width}px`, `a not_started store's chip says "${chipOf('habits')}"`);
  }
  if (!/9 of 30 days/.test(chipOf('thermal'))) {
    note(`${width}px`, `a collecting store's chip says "${chipOf('thermal')}"`);
  }
  if (!/first answer/.test(chipOf('thermal'))) {
    note(`${width}px`, 'a collecting store with a ready_at does not say when');
  }
  if (!/updated/.test(chipOf('rhythm'))) {
    note(`${width}px`, `a ready store's chip says "${chipOf('rhythm')}"`);
  }
  if (!/stale since/.test(chipOf('closures'))) {
    note(`${width}px`, `a stale store's chip says "${chipOf('closures')}"`);
  }
  if (!/not available/i.test(chipOf('appliances'))) {
    note(`${width}px`, `an unavailable store's chip says "${chipOf('appliances')}"`);
  }
  // The brief is the first thing on the tab and it is this morning's words.
  if (!/freezer has been drifting/.test(m.briefText)) {
    note(`${width}px`, 'the brief section does not carry this morning’s text');
  }
  if (!/This morning/.test(m.briefText)) {
    note(`${width}px`, 'the brief does not say when it was sent');
  }
  // Four sections, in order.
  const order = ['This morning', 'What brAIn has measured',
                 'What it remembers', 'Waiting to be filed'];
  const found = order.map((h) => m.sections.indexOf(h));
  found.forEach((at, i) => {
    if (at < 0) note(`${width}px`, `section "${order[i]}" is missing`);
  });
  if (found.every((at) => at >= 0)) {
    for (let i = 1; i < found.length; i += 1) {
      if (found[i] < found[i - 1]) {
        note(`${width}px`,
          `"${order[i]}" comes before "${order[i - 1]}"`);
        break;
      }
    }
  }
  if (m.docWidth > width + 0.5) {
    note(`${width}px`, `page scrolls sideways (${m.docWidth}px)`);
  }

  // A drill-down opens, and only one is open at a time.
  await page.click('#kStores .krow[data-store="rhythm"]');
  await page.waitForSelector('.kdrill[data-store="rhythm"] .ktable', { timeout: 5000 })
    .catch(() => note(`${width}px`, 'the rhythm drill-down never drew a table'));
  const rhythmText = await page.evaluate(() => {
    const d = document.querySelector('.kdrill[data-store="rhythm"]');
    return d ? d.textContent : '';
  });
  if (!/07:05/.test(rhythmText) || !/Weekends/.test(rhythmText)) {
    note(`${width}px`, 'the rhythm drill-down does not show both halves of the week');
  }
  if (!/±/.test(rhythmText)) {
    note(`${width}px`, 'the rhythm drill-down drops the spread');
  }

  await page.click('#kStores .krow[data-store="thermal"]');
  await page.waitForTimeout(120);
  const openCount = await page.evaluate(
    () => document.querySelectorAll('.kdrill').length);
  if (openCount !== 1) {
    note(`${width}px`, `${openCount} drill-downs open at once`);
  }
  const thermalText = await page.evaluate(() => {
    const d = document.querySelector('.kdrill[data-store="thermal"]');
    return d ? d.textContent : '';
  });
  if (!/Bedroom/.test(thermalText) || !/12\.3/.test(thermalText)) {
    note(`${width}px`, 'the thermal drill-down does not list the rooms');
  }
  // Sorted by τ: the fastest-losing room is the one somebody is looking for.
  if (thermalText.indexOf('Hall') > thermalText.indexOf('Bedroom')) {
    note(`${width}px`, 'thermal rooms are not sorted by time constant');
  }

  // A store with no rows says why, in its own words, rather than nothing.
  await page.click('#kStores .krow[data-store="appliances"]');
  await page.waitForTimeout(150);
  const apText = await page.evaluate(() => {
    const d = document.querySelector('.kdrill[data-store="appliances"]');
    return d ? d.textContent : '';
  });
  if (!/recorder answered nothing/.test(apText)) {
    note(`${width}px`, `an empty drill-down does not say why: "${apText.trim()}"`);
  }

  // Closures: a 7x24 grid per entity, with the unwatched hours drawn
  // differently from the never-open ones.
  await page.click('#kStores .krow[data-store="closures"]');
  await page.waitForTimeout(150);
  const heat = await page.evaluate(() => {
    const d = document.querySelector('.kdrill[data-store="closures"]');
    if (!d) return null;
    return {
      grids: d.querySelectorAll('.kheatgrid').length,
      cells: d.querySelectorAll('.kcell').length,
      unwatched: d.querySelectorAll('.kcell.unwatched').length,
      days: d.querySelectorAll('.kheatday').length,
    };
  });
  if (!heat || heat.grids !== 1) {
    note(`${width}px`, 'the closures drill-down drew no heatmap');
  } else {
    if (heat.cells !== 168) {
      note(`${width}px`, `the heatmap has ${heat.cells} cells, not 168`);
    }
    if (heat.days !== 7) {
      note(`${width}px`, `the heatmap has ${heat.days} day labels, not 7`);
    }
    if (!heat.unwatched) {
      note(`${width}px`, 'an unwatched hour is drawn like a watched one');
    }
  }

  // Baselines: the search box, then a chart that really draws. A blank
  // <svg> and a week of data look identical from a screenshot, so count.
  await page.click('#kStores .krow[data-store="baselines"]');
  await page.waitForSelector('.kdrill[data-store="baselines"] .kfind', { timeout: 5000 })
    .catch(() => note(`${width}px`, 'the baselines drill-down has no search box'));
  const findBox = await page.evaluate(() => {
    const el = document.querySelector('.kdrill[data-store="baselines"] .kfind');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { size: parseFloat(cs.fontSize),
             h: Math.round(el.getBoundingClientRect().height) };
  });
  // A text control under 16px zooms iOS in and never back out.
  if (findBox && findBox.size < 16) {
    note(`${width}px`, `the sensor search box is ${findBox.size}px, under 16`);
  }
  await page.fill('.kdrill[data-store="baselines"] .kfind', 'freezer');
  await page.waitForTimeout(80);
  const picks = await page.evaluate(() => [...document.querySelectorAll(
    '.kdrill[data-store="baselines"] .kpick')].map((b) => ({
      text: b.textContent.trim(),
      h: Math.round(b.getBoundingClientRect().height),
    })));
  if (picks.length !== 1) {
    note(`${width}px`, `the sensor filter matched ${picks.length}, not 1`);
  }
  picks.forEach((p) => {
    if (p.h < MIN_TARGET) {
      note(`${width}px`, `sensor "${p.text}" is ${p.h}px, under ${MIN_TARGET}`);
    }
  });
  if (picks.length) {
    await page.click('.kdrill[data-store="baselines"] .kpick');
    await page.waitForSelector('.kweek', { timeout: 5000 })
      .catch(() => note(`${width}px`, 'picking a sensor drew no week chart'));
    const chart = await page.evaluate(() => {
      const svg = document.querySelector('.kweek');
      if (!svg) return null;
      const box = svg.getBoundingClientRect();
      return {
        nodes: svg.querySelectorAll('*').length,
        bands: svg.querySelectorAll('.kband').length,
        lines: svg.querySelectorAll('.kline').length,
        ticks: [...svg.querySelectorAll('.ktick')].map((t) => t.textContent),
        now: svg.querySelectorAll('.know').length,
        w: Math.round(box.width), h: Math.round(box.height),
        foot: (document.querySelector('.kchartfoot') || {}).textContent || '',
      };
    });
    if (!chart) {
      note(`${width}px`, 'no week chart at all');
    } else {
      // A gap every 24 buckets means seven segments, so a chart drawn as
      // one path through the holes would show up here as one.
      if (chart.nodes < 20) {
        note(`${width}px`, `the week chart drew ${chart.nodes} nodes — blank`);
      }
      if (chart.bands < 2 || chart.lines < 2) {
        note(`${width}px`, `the chart drew ${chart.bands} bands and `
          + `${chart.lines} lines — the gaps are not breaking the line`);
      }
      if (!chart.now) note(`${width}px`, 'the chart does not mark this hour');
      if (!chart.ticks.some((t) => /Mon/.test(t))) {
        note(`${width}px`, 'the chart has no day labels');
      }
      if (!chart.ticks.some((t) => /°C/.test(t))) {
        note(`${width}px`, 'the chart has no labelled value ticks');
      }
      if (chart.w < 100 || chart.h < 60) {
        note(`${width}px`, `the chart laid out at ${chart.w}x${chart.h}`);
      }
      if (!/168 hours/.test(chart.foot)) {
        note(`${width}px`, 'the chart does not say how much of the week it has');
      }
    }
  }

  const after = await page.evaluate(
    () => document.documentElement.scrollWidth);
  if (after > width + 0.5) {
    note(`${width}px`, `page scrolls sideways with a drill-down open (${after}px)`);
  }

  console.log(`${failures.length ? 'ok? ' : 'ok  '}${String(width).padStart(4)}px  `
    + `${m.rows.length} stores, 4 sections, drill-downs open one at a time`);
  await context.close();
}

// ------------------------------------------------------------ today strip
// Three shapes, because none is a superset of the others: everything
// present, a payload missing most of it (segments must be OMITTED, not
// rendered as zeroes), and a pass in flight.
const TODAY_CASES = [
  ['all present', TODAY_FULL, (t) => {
    if (!/Checks ran/.test(t)) return 'no checks segment';
    if (!/12 ran, 1 could not look/.test(t)) return 'the skip count is missing';
    if (!/2 new findings/.test(t)) return 'the new findings are missing';
    if (!/next /.test(t)) return 'the next pass is missing';
    if (!/Baselines rebuilt/.test(t)) return 'no baselines segment';
    if (!/Memory filed/.test(t) || !/3 waiting/.test(t)) return 'no memory segment';
    if (!/1 problem since yesterday/.test(t)) return 'no problems segment';
    if (!/Problems/.test(t)) return 'the problems segment does not say where';
    if (!/1 run landed in the last day/.test(t)) return 'no landed-runs segment';
    return '';
  }],
  ['partial', {
    checks: { last_at: NOW - 600, ran: 9, skipped: 0, errored: 0, created: 0,
              cleared: 0, next_at: 0, running: false },
    baselines: { built_at: 0, running: false, error: '' },
    memory: { last_filed_at: 0, waiting: 0, running: false },
    reports: { since_yesterday: 0 },
    landed_runs_24h: 0,
  }, (t) => {
    if (!/Checks ran/.test(t)) return 'no checks segment';
    // A zero is not news, and rendering one is how the line becomes noise.
    if (/could not look/.test(t)) return 'a zero skip count was rendered';
    if (/new finding/.test(t)) return 'a zero finding count was rendered';
    if (/Baselines/.test(t)) return 'baselines rendered with no build';
    if (/Memory/.test(t)) return 'memory rendered with nothing filed';
    if (/problem/.test(t)) return 'a zero problem count was rendered';
    if (/landed/.test(t)) return 'a zero run count was rendered';
    return '';
  }],
  // What `_today_state` really sends today: a `running` flag and no elapsed.
  // A strip that needed the elapsed would say "(0s)" about a pass that has
  // been going three minutes, which is a confident wrong number.
  ['running', {
    checks: { last_at: NOW - 60, ran: 0, skipped: 0, errored: 0, created: 0,
              cleared: 0, next_at: null, running: true },
    baselines: { built_at: null, next_at: null, running: true, error: '' },
    memory: { last_filed_at: NOW - 100, waiting: 2, running: true },
    reports: { since_yesterday: 0 },
    landed_runs_24h: 0,
  }, (t) => {
    if (!/Checks running/.test(t)) return 'a running pass does not say so';
    if (!/Baselines rebuilding/.test(t)) return 'a running rebuild does not say so';
    if (!/Memory filing now/.test(t)) return 'a running consolidation does not say so';
    if (/\(0s\)/.test(t)) return 'an unknown elapsed rendered as "(0s)"';
    return '';
  }],
  // And when the server DOES do the subtraction, the number is shown: the
  // question is not "how long does this take" but "is it still working".
  ['running timed', {
    checks: { last_at: NOW - 60, ran: 0, skipped: 0, errored: 0, created: 0,
              cleared: 0, next_at: null, running: true, running_for: 95 },
    baselines: { built_at: null, running: false, error: '' },
    memory: { last_filed_at: 0, waiting: 0, running: false },
    reports: { since_yesterday: 0 },
    landed_runs_24h: 0,
  }, (t) => {
    if (!/Checks running/.test(t)) return 'a running pass does not say so';
    if (!/1m 35s/.test(t)) return 'a known elapsed is not rendered';
    return '';
  }],
  // Nothing has run at all. The strip must be HIDDEN rather than empty: a
  // rule that sets a display beats `.hidden` unless it is `!important`, and
  // what is left is a bar of chrome saying nothing.
  ['nothing yet', {}, () => ''],
];

for (const [name, payload, check] of TODAY_CASES) {
  for (const width of [390, 1200]) {
    const { context, page } = await openPanel(width,
      `window.__today = ${JSON.stringify(payload)};`);
    if (name === 'nothing yet') {
      await page.waitForTimeout(400);
    } else {
      await page.waitForSelector('#todayStrip .tseg', { timeout: 5000 })
        .catch(() => note(`today/${name}/${width}px`, 'the strip rendered nothing'));
    }
    const m = await page.evaluate(() => {
      const strip = document.getElementById('todayStrip');
      if (!strip) return null;
      const box = strip.getBoundingClientRect();
      return {
        text: strip.textContent,
        hidden: strip.classList.contains('hidden'),
        right: box.right,
        segs: [...strip.querySelectorAll('.tseg')].map((s) => ({
          seg: s.dataset.seg,
          press: s.classList.contains('press'),
          h: Math.round(s.getBoundingClientRect().height),
        })),
        wrapRight: (document.getElementById('dash') || document.body)
          .getBoundingClientRect().right,
        docWidth: document.documentElement.scrollWidth,
      };
    });
    if (!m) {
      note(`today/${name}/${width}px`, 'no strip element');
    } else if (name === 'nothing yet') {
      // An empty line above the ask bar is the `.toast { display: flex }`
      // bug: a rule with a display beats `[hidden]`, and what is left is a
      // strip of chrome saying nothing on the tab that has least room.
      if (!m.hidden) note(`today/${name}/${width}px`, 'an empty strip is shown');
      if (m.segs.length) {
        note(`today/${name}/${width}px`, `${m.segs.length} segments from nothing`);
      }
      console.log(`${failures.length ? 'ok? ' : 'ok  '}today ${name.padEnd(13)} `
        + `${String(width).padStart(4)}px  hidden`);
    } else {
      if (m.hidden) note(`today/${name}/${width}px`, 'the strip is hidden');
      const why = check(m.text);
      if (why) note(`today/${name}/${width}px`, why);
      m.segs.forEach((s) => {
        if (s.press && s.h < MIN_TARGET) {
          note(`today/${name}/${width}px`,
            `the ${s.seg} press is ${s.h}px, under ${MIN_TARGET}`);
        }
      });
      if (m.right > m.wrapRight + 0.5) {
        note(`today/${name}/${width}px`, 'the strip overflows the dashboard');
      }
      if (m.docWidth > width + 0.5) {
        note(`today/${name}/${width}px`,
          `page scrolls sideways (${m.docWidth}px)`);
      }
      console.log(`${failures.length ? 'ok? ' : 'ok  '}today ${name.padEnd(11)} `
        + `${String(width).padStart(4)}px  ${m.segs.length} segments`);
    }
    await context.close();
  }
}

// A house with nothing measured at all still renders seven rows: a store
// that vanishes when it has nothing to say is the silence this tab exists
// to end.
{
  const { context, page } = await openPanel(1200,
    'window.__house = { generated_at: 0, brief: { enabled: false }, '
    + 'weekly: { enabled: false }, stores: {} };');
  await page.click('.viewtab[data-view="memory"]');
  await page.waitForSelector('#kStores .krow');
  const m = await page.evaluate(() => ({
    rows: document.querySelectorAll('#kStores .krow').length,
    chips: [...document.querySelectorAll('#kStores .kchip')]
      .map((c) => c.textContent.trim()),
    brief: (document.getElementById('kBrief') || {}).textContent || '',
  }));
  if (m.rows !== STORES.length) {
    note('empty house', `${m.rows} rows on a fresh install`);
  }
  if (m.chips.some((c) => !c)) note('empty house', 'a row has no chip');
  if (!/morning brief is off/.test(m.brief)) {
    note('empty house', 'a disabled brief does not say so, or where to turn it on');
  }
  if (!/Configuration/.test(m.brief)) {
    note('empty house', 'the disabled brief does not name the tab the switch is on');
  }
  console.log('ok  empty house: seven rows, every one saying not started');
  await context.close();
}

// -------------------------------------------------------- milestone cards
// A measurement that has landed gets a card written about it, and one that
// has not gets a line saying it is coming. Both belong WITH the store's own
// row — the failure this exists to prevent is a list of cards at the bottom
// of the tab, where a card and the measurement it is about are two things
// nobody can connect, and a missing card reads as a card that failed.
//
//   * the card renders under the row it belongs to, not somewhere else
//   * it carries `made_because` — a card with no reason on it is a card
//     that appeared for reasons nobody can see, which is the whole thing
//     this field was added for
//   * the ONE control is there and is a real touch target. There is no
//     regenerate/edit/delete menu: this is not a card you keep re-running
//   * a pending entry is tied to its own row, by position and by data-store
//   * a 409 from the refresh is a sentence, never a red failure
const CARDS = {
  cards: [{
    id: 'rhythm', kind: 'milestone', store: 'rhythm',
    title: 'This house gets up at about 07:05',
    summary: 'Three weeks of mornings, and the weekdays are tighter than '
      + 'the weekends by half an hour.',
    highlights: [
      { label: 'Weekdays', value: '07:05' },
      { label: 'Weekends', value: '08:40' },
      { label: 'Measured over', value: '21 days' },
    ],
    html: '<!doctype html><html><body><p>rhythm</p></body></html>',
    made_at: NOW - 3600,
    made_because: 'the wake time settled',
    mark: { days: 21 },
  }],
  // Two still coming, so a row with a card and a row without both render.
  pending: [
    { id: 'thermal', store: 'thermal', title: 'How these rooms hold heat' },
    { id: 'habits', store: 'habits', title: 'Something you do by hand' },
  ],
  running: [{ state: 'generating', milestone: 'thermal', store: 'thermal' }],
};

for (const width of WIDTHS) {
  // The narrow widths are driven AS phones: the 44px floor on this card's
  // one control lives in a `pointer: coarse` block, and a context with a
  // fine pointer would measure the desktop density and call it a pass.
  const touch = width <= 768;
  const { context, page } = await openPanel(width,
    `window.__cards = ${JSON.stringify(CARDS)};`, touch);
  const at = `milestones/${width}px`;
  await page.click('.viewtab[data-view="memory"]');
  await page.waitForSelector('#kStores .krow');

  // The pending lines are always on screen — they are one muted sentence,
  // and what they say is about that measurement.
  const pend = await page.evaluate(() => {
    const kids = [...document.getElementById('kStores').children];
    return [...document.querySelectorAll('#kStores .kpending')].map((n) => {
      const i = kids.indexOf(n);
      const before = i > 0 ? kids[i - 1] : null;
      return {
        store: n.dataset.store,
        text: n.textContent.trim(),
        afterRow: !!(before && before.classList.contains('krow')
                     && before.dataset.store === n.dataset.store),
      };
    });
  });
  if (pend.length !== CARDS.pending.length) {
    note(at, `${pend.length} pending lines for ${CARDS.pending.length} pending`);
  }
  pend.forEach((row) => {
    if (!row.afterRow) {
      note(at, `the pending line for ${row.store} is not tied to its row`);
    }
    if (!row.text) note(at, `the pending line for ${row.store} says nothing`);
  });
  // A card that is coming and one being written now are different answers.
  const thermalPend = pend.find((r) => r.store === 'thermal');
  if (thermalPend && !/Writing/.test(thermalPend.text)) {
    note(at, `a milestone being written now says "${thermalPend.text}"`);
  }
  const habitsPend = pend.find((r) => r.store === 'habits');
  if (habitsPend && !/arrives when/.test(habitsPend.text)) {
    note(at, `a milestone still waiting says "${habitsPend.text}"`);
  }
  // A card behind a press nobody has a reason to make is a card nobody
  // reads, so the row it opens says it has one.
  const marked = await page.evaluate(() => [...document.querySelectorAll(
    '#kStores .krow')].filter((r) => r.querySelector('.kcardmark'))
    .map((r) => r.dataset.store));
  if (marked.join(',') !== 'rhythm') {
    note(at, `rows marked as having a card: [${marked.join(', ')}]`);
  }

  await page.click('#kStores .krow[data-store="rhythm"]');
  await page.waitForSelector('.kcard', { timeout: 5000 })
    .catch(() => note(at, 'opening a measured row drew no milestone card'));

  const card = await page.evaluate((floor) => {
    const box = document.querySelector('.kcard');
    if (!box) return null;
    const kids = [...document.getElementById('kStores').children];
    const i = kids.indexOf(box);
    const row = i > 0 ? kids[i - 1] : null;
    const foot = box.querySelector('.foot');
    const again = [...box.querySelectorAll('.foot .btn')]
      .find((b) => /again/i.test(b.textContent));
    const rect = box.getBoundingClientRect();
    const host = document.getElementById('kStores').getBoundingClientRect();
    return {
      // Under its own row: the card is what brAIn wrote about THAT
      // measurement, and a list of them at the bottom is a list of answers
      // to questions nobody can see.
      afterRow: !!(row && row.classList.contains('krow')
                   && row.dataset.store === 'rhythm'),
      title: (box.querySelector('h3') || {}).textContent || '',
      summary: (box.querySelector('.summary') || {}).textContent || '',
      highlights: box.querySelectorAll('.highlights .hl').length,
      frames: box.querySelectorAll('iframe').length,
      foot: foot ? foot.textContent : '',
      because: (box.querySelector('.foot .because') || {}).textContent || '',
      again: again ? Math.round(again.getBoundingClientRect().height) : 0,
      againShort: again ? again.getBoundingClientRect().height < floor : false,
      // No regenerate/edit/feedback/delete menu: a milestone is not a card
      // you keep re-running, and a ⋯ offering to delete it would be a
      // second way to lose the one thing this tab is for.
      menus: box.querySelectorAll('.card-head .actions').length,
      overflows: rect.right > host.right + 0.5,
      docWidth: document.documentElement.scrollWidth,
    };
  }, MIN_TARGET);

  if (!card) {
    note(at, 'no milestone card at all');
  } else {
    if (!card.afterRow) note(at, 'the milestone card is not under its own row');
    if (!/07:05/.test(card.title)) note(at, `the card's title is "${card.title}"`);
    if (!card.summary.trim()) note(at, 'the card renders no summary');
    if (card.highlights !== 3) {
      note(at, `the card drew ${card.highlights} highlights, not 3`);
    }
    if (card.frames !== 1) {
      note(at, `the card drew ${card.frames} frames for its visualization`);
    }
    // The card exists BECAUSE something happened, and the foot is where it
    // says so. Without it a card that appeared overnight is a card nobody
    // can account for.
    if (!card.because.trim()) note(at, 'the milestone card carries no made_because');
    if (!/the wake time settled/.test(card.because)) {
      note(at, `made_because reads "${card.because.trim()}"`);
    }
    if (!/Made /.test(card.foot)) note(at, 'the card does not say when it was made');
    if (!card.again) note(at, 'the card has no "Make this again" control');
    // Asked where the rule lives. The 44px floor on this control is in a
    // `pointer: coarse` block, the same scope the proposals' and the
    // account section's floors use — a fine pointer keeps the density the
    // rest of the panel's small buttons are drawn at.
    if (touch && card.againShort) {
      note(at, `"Make this again" is ${card.again}px, under ${MIN_TARGET}`);
    }
    if (card.menus) note(at, 'the milestone card grew a ⋯ menu');
    if (card.overflows) note(at, 'the milestone card overflows the list');
    if (card.docWidth > width + 0.5) {
      note(at, `page scrolls sideways with a card open (${card.docWidth}px)`);
    }
  }

  // The one control, pressed. A refusal comes back as a sentence in the
  // ordinary voice — nothing is broken, the measurement simply has no
  // answer at this moment — so it must not read as a failed request.
  await page.evaluate(() => { window.__refuseRefresh = true; });
  await page.click('.kcard .foot .btn');
  await page.waitForTimeout(200);
  const refused = await page.evaluate(() => {
    const t = document.getElementById('toast');
    return { text: t ? t.textContent : '', shown: !!t && t.classList.contains('show') };
  });
  if (!refused.shown || !/does not have an answer/.test(refused.text)) {
    note(at, `a refused refresh said "${refused.text}" (shown: ${refused.shown})`);
  }
  await page.evaluate(() => { window.__refuseRefresh = false; });
  await page.click('.kcard .foot .btn');
  await page.waitForTimeout(200);
  const asked = await page.evaluate(() => window.__refreshed || 0);
  if (!asked) note(at, 'pressing "Make this again" asked the server for nothing');

  console.log(`${failures.length ? 'ok? ' : 'ok  '}milestones `
    + `${String(width).padStart(4)}px  1 card under its row, `
    + `${pend.length} pending lines`);
  await context.close();
}

await browser.close();
for (const f of failures) console.log(`  - ${f}`);
console.log(failures.length ? `\n${failures.length} problem(s)` : '\nall widths ok');
process.exit(failures.length ? 1 : 0);
