// History, per domain, from what Home Assistant actually records
// (docs/design/morph-ui.md §4). It opens in two layers, both inside the card:
//
//   1. Compact: one summary in the device's colour — a DAY STRIP for things
//      that are on or off (lights, switches, locks, covers, doors, people,
//      thermostat runs) or a 7-BAR WEEK for readings and meters — with one
//      line of context.
//   2. Extended: tap the summary. The trail starts with the device's name
//      (Kitchen › History › Tue); bars are what you tap to go deeper
//      (day → hours → that hour's readings); lines are read by sliding a
//      finger along them.
//
// Sources: `history/history_during_period` (state timelines),
// `recorder/statistics_during_period` (means, sums), `logbook/get_events`
// (who or what changed it). Every fetch is cached for a minute and asked at
// most once at a time; the panel re-renders when an answer lands.

import { esc, mix, clock, dur, fmt } from './util.js';

const CACHE = new Map();
const MAX_CACHE = 400;
const TTL = 60000;
export const CHARTS = new Map();
let onData = () => {};
export function setOnData(fn) { onData = fn; }

// The last answer per question regardless of window, so a window that
// rolls over to the next minute keeps showing the previous answer while the
// new one loads. A chart that blanked for a moment would change its card's
// height and send the sections around it moving for nothing.
const LAST = new Map();

function cached(key, fetcher) {
  const family = key.split('|').filter((_, i) => i < 2).join('|') + '|' + key.split('|').slice(-1)[0];
  const hit = CACHE.get(key);
  if (hit && (hit.pending || Date.now() - hit.at < TTL)) return hit.data !== undefined ? hit.data : LAST.get(family);
  const entry = { pending: true, at: Date.now(), data: hit ? hit.data : LAST.get(family) };
  CACHE.set(key, entry);
  if (CACHE.size > MAX_CACHE) CACHE.delete(CACHE.keys().next().value);
  fetcher().then((d) => { entry.data = d; LAST.set(family, d); }).catch((e) => { entry.data = { error: String(e && e.message || e) }; })
    .finally(() => { entry.pending = false; entry.at = Date.now(); onData(); });
  return entry.data;
}

const iso = (ms) => new Date(ms).toISOString();
// Every caller passes "now", which moves every frame; a key built from it
// would be a new fetch per render. Windows are taken to the minute.
const q = (ms) => Math.floor(ms / 60000) * 60000;
const dayStart = (ms) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };

export function timeline(hass, eid, start, end, attrs) {
  start = q(start); end = q(end) + 60000;
  return cached(`tl|${eid}|${start}|${end}|${attrs ? 1 : 0}`, async () => {
    const r = await hass.callWS({ type: 'history/history_during_period', start_time: iso(start), end_time: iso(end), entity_ids: [eid], minimal_response: !attrs, no_attributes: !attrs, significant_changes_only: false });
    const rows = (r && r[eid]) || [];
    let last = start / 1000;
    return rows.map((x) => { const t = x.lu != null ? x.lu : x.lc != null ? x.lc : last; last = t; return { s: x.s, t: t * 1000, a: x.a || null }; });
  });
}

export function stats(hass, eid, start, end, period) {
  start = q(start); end = q(end) + 60000;
  return cached(`st|${eid}|${start}|${end}|${period}`, async () => {
    const r = await hass.callWS({ type: 'recorder/statistics_during_period', start_time: iso(start), end_time: iso(end), statistic_ids: [eid], period: period, types: ['mean', 'min', 'max', 'change', 'state'] });
    return ((r && r[eid]) || []).map((x) => ({ t: typeof x.start === 'number' ? x.start : Date.parse(x.start), mean: x.mean, min: x.min, max: x.max, change: x.change, state: x.state }));
  });
}

export function logbook(hass, eid, start, end) {
  start = q(start); end = q(end) + 60000;
  return cached(`lb|${eid}|${start}|${end}`, async () => {
    const r = await hass.callWS({ type: 'logbook/get_events', start_time: iso(start), end_time: iso(end), entity_ids: [eid] });
    return (r || []).map((x) => ({ t: (x.when || 0) * 1000, state: x.state, message: x.message, by: x.context_entity_id_name || x.context_name || (x.context_user_id ? 'a person' : '') || x.context_event_type || '', via: x.context_domain || '' }));
  });
}

// Which kind of history a card has.
export function kindOf(type, st) {
  const dc = st && st.attributes && st.attributes.device_class;
  if (type === 'meter' || (st && st.attributes && ['total', 'total_increasing'].includes(st.attributes.state_class))) return 'meter';
  if (type === 'sensor' || type === 'readings' || (st && !isNaN(parseFloat(st.state)) && type === 'entity')) return 'reading';
  if (type === 'climate') return 'runs';
  if (dc === 'temperature' || dc === 'humidity') return 'reading';
  return 'strip';
}

const ACTIVE = ['on', 'open', 'opening', 'unlocked', 'playing', 'home', 'heat', 'cool', 'heating', 'cooling', 'cleaning', 'detected', 'wet', 'triggered', 'armed_away', 'armed_home', 'armed_night'];
export const isActive = (s) => ACTIVE.includes(String(s));

function segments(rows, start, end, test) {
  const out = []; let cur = null;
  (rows || []).forEach((r, i) => {
    const t = Math.max(start, r.t);
    const on = test(r);
    if (on && !cur) cur = { a: t };
    if (!on && cur) { out.push({ a: cur.a, b: t }); cur = null; }
    if (i === rows.length - 1 && cur) out.push({ a: cur.a, b: Math.min(end, Date.now()) });
  });
  return out;
}

function stripHtml(segs, start, end, color) {
  const span = end - start;
  return `<div class="dstrip">${segs.map((s) => `<span style="left:${((s.a - start) / span * 100).toFixed(2)}%;width:${Math.max(0.8, (s.b - s.a) / span * 100).toFixed(2)}%;background:${color}"></span>`).join('')}</div>
<div class="ticks"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>Now</span></div>`;
}

function barsHtml(points, color, act, fmtv, labelOf) {
  const vals = points.map((p) => p.v).filter((v) => v != null && isFinite(v));
  if (!vals.length) return '<p class="sm">Nothing recorded for this stretch.</p>';
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1;
  return `<div class="cols">${points.map((p) => {
    const h = p.v == null ? 2 : Math.max(3, ((p.v - lo) / (hi - lo || 1)) * 64);
    return `<button type="button" class="colb" data-act="${act}" data-v="${p.t}" aria-label="${esc(labelOf(p))}: ${esc(fmtv(p.v))}"><span class="colv">${p.v == null ? '' : esc(fmtv(p.v))}</span><span class="colbar" style="height:${h}px;background:${mix(color, p.hot ? 85 : 55)}"></span><span class="coll">${esc(labelOf(p))}</span></button>`;
  }).join('')}</div>`;
}

let chartSeq = 0;
// A line chart read by sliding a finger. The series are kept in CHARTS so
// the panel's pointer handler can answer "what was it at this instant".
export function lineChart(series, t0, t1, opts) {
  const o = opts || {};
  const all = series.flatMap((s) => s.pts.map((p) => p[1])).filter((v) => isFinite(v));
  if (!all.length) return '<p class="sm">Nothing recorded for this stretch.</p>';
  let lo = Math.min(...all), hi = Math.max(...all);
  const m = (hi - lo) * 0.15 || 1; lo -= m; hi += m;
  if (o.band) { lo = Math.min(lo, o.band[0] - 1); hi = Math.max(hi, o.band[1] + 1); }
  const H = o.height || 120, W = 600;
  const X = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  const key = 'c' + (++chartSeq);
  CHARTS.set(key, { series, t0, t1, unit: o.unit || '' });
  if (CHARTS.size > 60) CHARTS.delete(CHARTS.keys().next().value);
  const focus = o.focus;
  const paths = series.map((s) => {
    const d = s.pts.filter((p) => isFinite(p[1])).map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
    const dim = focus && focus !== s.id;
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${dim ? 1.2 : 2}" stroke-linejoin="round" stroke-linecap="round" opacity="${dim ? 0.25 : 1}" vector-effect="non-scaling-stroke"></path>`;
  }).join('');
  const band = o.band ? `<rect x="0" width="${W}" y="${Y(o.band[1]).toFixed(1)}" height="${Math.max(1, Y(o.band[0]) - Y(o.band[1])).toFixed(1)}" fill="${mix(o.bandColor || 'var(--teal)', 12)}"></rect>` : '';
  const runs = (o.runs || []).map((r) => `<rect x="${X(r.a).toFixed(1)}" width="${Math.max(1, X(r.b) - X(r.a)).toFixed(1)}" y="${H + 6}" height="5" rx="2" fill="${r.color || 'var(--teal)'}"></rect>`).join('');
  // Labels at the end of each line, nudged apart so they never collide.
  let labels = '';
  if (series.length > 1) {
    const ends = series.map((s) => { const last = s.pts.filter((p) => isFinite(p[1])).slice(-1)[0]; return last ? { s, y: Y(last[1]) } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
    labels = ends.map((e) => `<text x="${W + 6}" y="${e.y + 4}" font-size="11" fill="${e.s.color}" opacity="${focus && focus !== e.s.id ? 0.35 : 1}">${esc(e.s.short || e.s.name)}</text>`).join('');
  }
  return `<div class="chart" data-chart="${key}"><svg viewBox="0 0 ${series.length > 1 ? W + 90 : W} ${H + (o.runs ? 14 : 2)}" preserveAspectRatio="none" style="height:${H + (o.runs ? 14 : 2)}px">${band}${paths}${runs}${labels}</svg><span class="scrub" hidden></span></div><div class="readout" data-readout="${key}">${esc(o.caption || 'Slide along the line to read it.')}</div>`;
}

export function scrubAt(key, frac) {
  const c = CHARTS.get(key); if (!c) return '';
  const t = c.t0 + frac * (c.t1 - c.t0);
  const parts = c.series.map((s) => {
    let best = null; let bd = Infinity;
    s.pts.forEach((p) => { const d = Math.abs(p[0] - t); if (d < bd && isFinite(p[1])) { bd = d; best = p; } });
    return best ? `<span style="color:${s.color}">${esc(s.short || s.name)} ${esc(fmt(best[1], c.unit))}</span>` : '';
  }).filter(Boolean);
  return `<b>${esc(clock(t))}</b> · ${parts.join(' · ')}`;
}

// ------------------------------------------------------------------ blocks

function trail(name, crumbs) {
  return `<div class="crumbs"><button type="button" class="crumb" data-act="h-back" data-v="0">${esc(name)}</button>${crumbs.map((c, i) => `<span class="small">›</span><button type="button" class="crumb" data-act="h-back" data-v="${i + 1}">${esc(c)}</button>`).join('')}</div>`;
}

export function block(hass, card, st, H, color, name) {
  const eid = card.entity;
  if (!eid || !st) return '';
  const kind = kindOf(card.type, st);
  const now = Date.now();
  const d0 = dayStart(now);
  const unit = (st.attributes && st.attributes.unit_of_measurement) || '';
  try {
    if (kind === 'strip' || kind === 'runs') {
      const runs = kind === 'runs';
      if (!H.depth) {
        const rows = timeline(hass, eid, d0, now, runs);
        if (rows === undefined) return '<p class="sm">Reading history…</p>';
        if (rows.error) return `<p class="sm">History could not be read: ${esc(rows.error)}</p>`;
        const test = runs ? (r) => ['heating', 'cooling', 'drying', 'fan'].includes(r.a && r.a.hvac_action) : (r) => isActive(r.s);
        const segs = segments(rows, d0, now, test);
        const total = segs.reduce((a, s) => a + (s.b - s.a), 0);
        const word = runs ? 'Ran' : card.type === 'lock' ? 'Unlocked' : ['cover', 'list'].includes(card.type) ? 'Open' : card.type === 'person' ? 'Home' : 'On';
        const changes = rows.length;
        return `<button type="button" class="lrow" data-act="h-open" style="border-top:0;flex-direction:column;align-items:stretch;gap:6px"><span class="rowb"><b style="font-size:13px">${esc(word)} ${esc(dur(total))} today</b><span class="small">${changes} change${changes === 1 ? '' : 's'} · tap for who and when</span></span>${stripHtml(segs, d0, d0 + 86400000, mix(color, 70))}</button>`;
      }
      const day = H.day || d0;
      const rows = logbook(hass, eid, day, Math.min(now, day + 86400000));
      const head = trail(name, ['History', new Date(day).toLocaleDateString([], { weekday: 'short' })]);
      if (rows === undefined) return head + '<p class="sm">Reading the logbook…</p>';
      if (rows.error) return head + `<p class="sm">The logbook could not be read: ${esc(rows.error)}</p>`;
      const days = [6, 5, 4, 3, 2, 1, 0].map((i) => d0 - i * 86400000);
      const pick = `<div class="row" style="flex-wrap:wrap;gap:0 14px">${days.map((d) => `<button type="button" class="wd" data-act="h-day" data-v="${d}" aria-pressed="${d === day}">${esc(new Date(d).toLocaleDateString([], { weekday: 'short' }))}</button>`).join('')}</div>`;
      const list = rows.length ? rows.slice().reverse().slice(0, 40).map((r) => `<div class="lrow" style="cursor:default"><span class="lt">${esc(clock(r.t))}</span><span class="lx"><span>${esc(r.state || r.message || '')}</span>${r.by ? `<span class="lw">by ${esc(r.by)}</span>` : ''}</span></div>`).join('') : '<p class="sm">Nothing changed that day.</p>';
      return head + pick + list;
    }
    if (kind === 'reading' || kind === 'meter') {
      const meter = kind === 'meter';
      const val = (p) => (meter ? p.change : p.mean);
      const fv = (v) => fmt(v, unit);
      if (!H.depth) {
        const week = stats(hass, eid, d0 - 6 * 86400000, now, 'day');
        if (week === undefined) return '<p class="sm">Reading history…</p>';
        if (week.error || !week.length) {
          const rows = timeline(hass, eid, now - 86400000, now);
          if (!rows || rows.error) return '<p class="sm">No long-term statistics for this one.</p>';
          return lineChart([{ id: eid, name, color, pts: rows.map((r) => [r.t, parseFloat(r.s)]) }], now - 86400000, now, { unit });
        }
        const pts = week.map((p) => ({ t: p.t, v: val(p) }));
        const today = pts[pts.length - 1];
        return `<div class="rowb"><b style="font-size:13px">${meter ? 'Today ' + esc(fv(today && today.v)) : 'Daily average · 7 days'}</b><span class="small">tap a day for its hours</span></div>${barsHtml(pts.map((p) => ({ ...p, hot: p.t === (today && today.t) })), color, 'h-day', fv, (p) => new Date(p.t).toLocaleDateString([], { weekday: 'short' }))}`;
      }
      const day = H.day || d0;
      if (H.depth === 1) {
        const hours = stats(hass, eid, day, Math.min(now, day + 86400000), 'hour');
        const head = trail(name, ['History', new Date(day).toLocaleDateString([], { weekday: 'short' })]);
        if (hours === undefined) return head + '<p class="sm">Reading the day…</p>';
        if (hours.error) return head + `<p class="sm">${esc(hours.error)}</p>`;
        return head + barsHtml(hours.map((p) => ({ t: p.t, v: val(p) })), color, 'h-hour', fv, (p) => { const h = new Date(p.t).getHours(); return h % 6 === 0 ? (h === 0 ? '12a' : h === 12 ? '12p' : (h % 12) + (h < 12 ? 'a' : 'p')) : ''; });
      }
      const hour = H.hour || day;
      const rows = timeline(hass, eid, hour - 3600000, Math.min(now, hour + 7200000));
      const head = trail(name, ['History', new Date(day).toLocaleDateString([], { weekday: 'short' }), clock(hour)]);
      if (rows === undefined) return head + '<p class="sm">Reading the hour…</p>';
      if (rows.error) return head + `<p class="sm">${esc(rows.error)}</p>`;
      return head + lineChart([{ id: eid, name, color, pts: rows.map((r) => [r.t, parseFloat(r.s)]) }], hour - 3600000, Math.min(now, hour + 7200000), { unit });
    }
  } catch (e) {
    return `<p class="sm">History could not be drawn: ${esc(e.message || e)}</p>`;
  }
  return '';
}

// Many readings of one kind, overlaid (§3.3): one line per sensor coloured
// by how warm it is now, labels at the line ends, slide to read every value
// at one instant, tap a name to pick it out, and extremes (attic, outside)
// on one quiet line below so they do not flatten the rest.
export function readings(hass, card, H, colorFor) {
  const ids = (card.entities || []).filter((e) => hass.states[e]);
  if (!ids.length) return '<p class="sm">None of these sensors exist.</p>';
  const now = Date.now(), t0 = now - 86400000;
  const series = [];
  let pending = false;
  ids.forEach((eid) => {
    const rows = stats(hass, eid, t0, now, '5minute');
    if (rows === undefined) { pending = true; return; }
    const pts = rows && !rows.error && rows.length ? rows.map((p) => [p.t, p.mean]) : [];
    const st = hass.states[eid];
    series.push({ id: eid, name: (st.attributes.friendly_name || eid), short: (st.attributes.friendly_name || eid).replace(/\s*(temperature|humidity|temp)$/i, ''), color: colorFor(parseFloat(st.state)), pts, now: parseFloat(st.state) });
  });
  if (pending && !series.length) return '<p class="sm">Reading the day…</p>';
  const meds = series.map((s) => s.now).filter(isFinite).sort((a, b) => a - b);
  const med = meds[Math.floor(meds.length / 2)];
  const spread = meds.length > 3 ? (meds[Math.floor(meds.length * 0.75)] - meds[Math.floor(meds.length * 0.25)]) || 2 : Infinity;
  const main = series.filter((s) => !isFinite(spread) || Math.abs(s.now - med) <= 3 * spread);
  const extreme = series.filter((s) => !main.includes(s));
  const unit = (hass.states[ids[0]].attributes.unit_of_measurement) || '';
  let band = null;
  if (card.options && Array.isArray(card.options.band)) band = card.options.band;
  const legend = `<div class="legend">${main.map((s) => `<button type="button" class="wd" data-act="r-focus" data-v="${esc(s.id)}" aria-pressed="${H.focus === s.id}" style="color:${s.color}">${esc(s.short)} ${esc(fmt(s.now, unit))}</button>`).join('')}</div>`;
  const chart = lineChart(main, t0, now, { unit, focus: H.focus, height: 150, band, caption: 'Slide along it to read every room at that moment.' });
  const ext = extreme.length ? `<div class="small" style="margin-top:6px">${extreme.map((s) => `<span style="color:${s.color}">${esc(s.short)} ${esc(fmt(s.now, unit))}</span>`).join(' · ')}</div>${lineChart(extreme, t0, now, { unit, height: 50, caption: ' ' })}` : '';
  return legend + chart + ext;
}

export function clearCache() { CACHE.clear(); }
