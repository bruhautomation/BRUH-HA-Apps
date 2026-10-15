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

// Stretches the record says nothing about (unavailable, unknown): drawn
// hatched, never as "off".
const GAP = ['unavailable', 'unknown'];
function gaps(rows, start, end) { return segments(rows, start, end, (r) => GAP.includes(String(r.s))); }

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

// A day strip covers midnight to midnight: its right edge is the next
// midnight (it said "Now"), and now is a mark of its own.
function stripHtml(segs, start, end, color, holes) {
  const span = end - start;
  const nowAt = Math.max(0, Math.min(100, (Date.now() - start) / span * 100));
  const bar = (s, bg, cls) => `<span${cls ? ` class="${cls}"` : ''} style="left:${((s.a - start) / span * 100).toFixed(2)}%;width:${Math.max(0.8, (s.b - s.a) / span * 100).toFixed(2)}%;${bg ? `background:${bg}` : ''}"></span>`;
  return `<div class="dstrip">${(holes || []).map((s) => bar(s, '', 'gap')).join('')}${segs.map((s) => bar(s, color)).join('')}<i class="dnow" style="left:${nowAt.toFixed(2)}%"></i></div>
<div class="ticks"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span></div>`;
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

// A chart's key is what it shows, so a redraw keeps a finger's place: a new
// key on every render dropped the scrub state each time the house moved.
const chartKey = (o, series) => 'c' + (o.key || series.map((s) => s.id).join('+')).replace(/[^a-z0-9_+.-]/gi, '_').slice(0, 120);
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
  const key = chartKey(o, series);
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
  // Labels at the end of each line, nudged apart so they never collide —
  // as HTML beside the plot: SVG text inside a viewBox drawn with
  // preserveAspectRatio="none" came out stretched.
  let labels = '';
  if (series.length > 1) {
    const ends = series.map((s) => { const last = s.pts.filter((p) => isFinite(p[1])).slice(-1)[0]; return last ? { s, y: Y(last[1]) } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    labels = `<div class="chlabs" aria-hidden="true">${ends.map((e) => `<span style="top:${(e.y - 7).toFixed(1)}px;color:${e.s.color};opacity:${focus && focus !== e.s.id ? 0.35 : 1}">${esc(e.s.short || e.s.name)}</span>`).join('')}</div>`;
  }
  const hh = H + (o.runs ? 14 : 2);
  return `<div class="chart${labels ? ' haslabs' : ''}" data-chart="${key}"><svg viewBox="0 0 ${W} ${hh}" preserveAspectRatio="none" style="height:${hh}px">${band}${paths}${runs}</svg><span class="scrub" hidden></span>${labels}</div><div class="readout" data-readout="${key}">${esc(o.caption || 'Slide along the line to read it.')}</div>`;
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
        const holes = gaps(rows, d0, now);
        const total = segs.reduce((a, s) => a + (s.b - s.a), 0);
        const word = runs ? 'Ran' : card.type === 'lock' ? 'Unlocked' : ['cover', 'list'].includes(card.type) ? 'Open' : card.type === 'person' ? 'Home' : 'On';
        const changes = rows.length;
        return `<button type="button" class="lrow" data-act="h-open" style="border-top:0;flex-direction:column;align-items:stretch;gap:6px"><span class="rowb"><b style="font-size:13px">${esc(word)} ${esc(dur(total))} today</b><span class="small">${changes} change${changes === 1 ? '' : 's'} · tap for who and when</span></span>${stripHtml(segs, d0, d0 + 86400000, mix(color, 70), holes)}</button>`;
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

// Many readings of one kind, overlaid (§3.3, and the prototype's chart):
// one line per room coloured by how warm it is now; a column of labels
// beside the plot that follow the line ends (or the finger) and pick a line
// out when tapped; under the lines, what the house was aiming for (the
// thermostats' target over the day, or a fixed comfortable band) and when
// the system actually ran; then a time axis, and the extremes (attic,
// outside) on one quiet line of their own so they do not flatten the rest.

const OV = new Map(); // chart key → what the overlay needs to answer a finger
export const SERIES = ['var(--sky)', 'var(--amber)', 'var(--violet)', 'var(--teal)', 'var(--peach)', 'var(--sand)', 'var(--indigo)', 'var(--lime)', 'var(--rose)'];
const CH = 150;       // plot height, px (the viewBox is 600 × CH)
const LABEL_GAP = 19;

function hhmm(ms) {
  const m = Math.round(ms / 60000); const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} h${r ? ' ' + r + ' m' : ''}` : `${r} m`;
}

// The value of a stepwise series at an instant (the last point at or before).
function valueAt(pts, t) {
  let v = null;
  for (const p of pts) { if (p[0] > t) break; if (isFinite(p[1])) v = p[1]; }
  if (v == null) { const f = pts.find((p) => isFinite(p[1])); v = f ? f[1] : null; }
  return v;
}

// A thermostat's history as [time, [low, high] | null, action]. A fetch
// that failed answers `{error}`, not a list, and a chart with no target band
// is still a chart, so anything but a list is no band.
function climateTargets(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.map((r) => {
    const a = r.a || {};
    const lo = a.target_temp_low != null ? a.target_temp_low : a.temperature;
    const hi = a.target_temp_high != null ? a.target_temp_high : a.temperature;
    return [r.t, r.s === 'off' || lo == null ? null : [Number(lo), Number(hi)], a.hvac_action || null];
  });
}

function labelsHtml(o, at) {
  const { lines, yOf, focus, unit, digits } = o;
  let lab = lines.map((l) => { const v = at == null ? l.now : valueAt(l.pts, at); return { l, v, y: v == null ? CH : yOf(v) }; }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < lab.length; i++) lab[i].y = Math.max(lab[i].y, lab[i - 1].y + LABEL_GAP);
  const over = lab.length ? lab[lab.length - 1].y - (CH - 9) : 0;
  if (over > 0) { lab[lab.length - 1].y -= over; for (let i = lab.length - 2; i >= 0; i--) lab[i].y = Math.min(lab[i].y, lab[i + 1].y - LABEL_GAP); }
  return lab.map((x) => `<button type="button" class="ovlab" data-act="r-focus" data-v="${esc(x.l.id)}" aria-pressed="${focus === x.l.id}" style="top:${(x.y - 9).toFixed(1)}px;opacity:${focus && focus !== x.l.id ? 0.45 : 1}"><span class="sw" style="background:${x.l.color}"></span><span class="nm">${esc(x.l.short)}</span><b style="color:${x.l.valColor || 'inherit'}">${x.v == null ? '—' : esc(Number(x.v).toFixed(digits) + unit)}</b></button>`).join('');
}

// What the overlay says under a finger: the labels' values, a dot on every
// line, and the time (with what the house was aiming for then).
export function overlayAt(key, frac) {
  const o = OV.get(key); if (!o) return null;
  const t = o.t0 + frac * (o.t1 - o.t0);
  const dots = o.lines.map((l) => { const v = valueAt(l.pts, t); return v == null ? '' : `<span class="ovdot" style="left:${(frac * 100).toFixed(2)}%;top:${o.yOf(v).toFixed(1)}px;background:${l.color};opacity:${o.focus && o.focus !== l.id ? 0.25 : 1}"></span>`; }).join('');
  const b = o.bandAt ? o.bandAt(t) : null;
  const sub = clock(t) + (b ? ` · ${o.bandWord} ${fmt(b[0], '')}${b[1] !== b[0] ? '–' + fmt(b[1], '') : ''}${o.unit}` : '');
  return { labels: labelsHtml(o, t), dots, sub };
}
export function overlayRest(key) {
  const o = OV.get(key); if (!o) return null;
  return { labels: labelsHtml(o, null), dots: '', sub: o.sub };
}

function sparkPts(pts, w, h) {
  const v = pts.filter((p) => isFinite(p[1]));
  if (v.length < 2) return '';
  const t0 = v[0][0], t1 = v[v.length - 1][0];
  let lo = Math.min(...v.map((p) => p[1])), hi = Math.max(...v.map((p) => p[1])); if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  return v.map((p) => `${((p[0] - t0) / (t1 - t0 || 1) * w).toFixed(1)},${(1 + (1 - (p[1] - lo) / (hi - lo)) * (h - 2)).toFixed(1)}`).join(' ');
}

export function readings(hass, card, H, colorFor, head) {
  const hd = head || {};
  const ids = (card.entities || []).filter((e) => hass.states[e]);
  const header = (sub) => `<div class="ovhead"><b>${esc(hd.name || '')}</b><span class="ovsub" data-ovsub="1">${esc(sub || '')}</span><span class="flex1"></span>${hd.hint ? `<span class="hint">${esc(hd.hint)}</span>` : ''}</div>`;
  if (!ids.length) return header('') + '<p class="sm">None of these sensors exist.</p>';
  const now = Date.now(), t0 = now - 86400000;
  const opts = card.options || {};
  const first = hass.states[ids[0]];
  const unitRaw = first.attributes.unit_of_measurement || '';
  const dc = first.attributes.device_class;
  // What these lines ARE: a soil-moisture card was called "rooms", given a
  // degree sign and drawn under the thermostats' target band.
  const moisture = dc === 'moisture' || /moist|soil/i.test(ids.join(' '));
  const temperature = !moisture && (dc === 'temperature' || /°/.test(unitRaw));
  const humidity = !moisture && !temperature && (dc === 'humidity' || unitRaw === '%');
  const unit = temperature ? '°' : unitRaw === '%' ? '%' : unitRaw ? ' ' + unitRaw : '';
  const digits = humidity || moisture || unitRaw === '%' ? 0 : 1;
  const what = moisture ? 'line' : temperature || humidity ? 'room' : 'line';
  const series = [];
  let pending = false;
  ids.forEach((eid) => {
    const rows = stats(hass, eid, t0, now, '5minute');
    if (rows === undefined) { pending = true; return; }
    const pts = Array.isArray(rows) && rows.length ? rows.map((p) => [p.t, p.mean]) : [];
    const st = hass.states[eid];
    const nm = st.attributes.friendly_name || eid;
    // A line's colour is its place in a fixed palette, so two rooms never
    // share one; the reading's own warmth colours its value instead.
    series.push({ id: eid, name: nm, short: nm.replace(/\s*(temperature|humidity|temp|moisture)$/i, ''), color: SERIES[series.length % SERIES.length], valColor: colorFor(parseFloat(st.state)), pts, now: parseFloat(st.state) });
  });
  if (pending && !series.length) return header('') + '<p class="sm">Reading the day…</p>';
  // Extremes (an attic, the outside) leave the plot for the line below it.
  const meds = series.map((x) => x.now).filter(isFinite).sort((a, b) => a - b);
  const med = meds[Math.floor(meds.length / 2)];
  const spread = meds.length > 3 ? (meds[Math.floor(meds.length * 0.75)] - meds[Math.floor(meds.length * 0.25)]) || 2 : Infinity;
  const main = series.filter((x) => !isFinite(spread) || Math.abs(x.now - med) <= 3 * spread);
  const extreme = series.filter((x) => !main.includes(x));
  (opts.env || []).forEach((eid) => {
    const st = hass.states[eid]; if (!st || series.some((x) => x.id === eid)) return;
    const rows = stats(hass, eid, t0, now, '5minute');
    const nm = st.attributes.friendly_name || eid;
    extreme.push({ id: eid, short: nm.replace(/\s*(temperature|humidity|temp)$/i, ''), color: 'var(--muted)', now: parseFloat(st.state), pts: Array.isArray(rows) ? rows.map((p) => [p.t, p.mean]) : [] });
  });

  // What the house was aiming for: a band the card names, or the
  // thermostats' own target through the day.
  let bandAt = null; let bandWord = humidity ? 'comfortable' : 'target'; let runs = []; let runsLabel = '';
  let bandColor = humidity ? 'var(--sky)' : 'var(--teal)';
  if (Array.isArray(opts.band) && opts.band.length === 2) {
    const fixed = [Number(opts.band[0]), Number(opts.band[1])];
    bandAt = () => fixed;
  } else if (temperature) {
    const climates = (opts.climate ? [].concat(opts.climate) : Object.keys(hass.states).filter((e) => e.startsWith('climate.'))).filter((e) => hass.states[e]).slice(0, 4);
    const tls = climates.map((c) => climateTargets(timeline(hass, c, t0, now, true))).filter((r) => r.length);
    if (tls.length) {
      const at = (rows, t) => { let cur = null; for (const r of rows) { if (r[0] > t) break; cur = r; } return cur || rows[0]; };
      bandAt = (t) => {
        const bs = tls.map((rows) => at(rows, t)[1]).filter(Boolean);
        if (!bs.length) return null;
        return [Math.min(...bs.map((b) => b[0])), Math.max(...bs.map((b) => b[1]))];
      };
      // When it actually ran: any thermostat heating or cooling.
      const acts = {};
      tls.forEach((rows) => rows.forEach((r, i) => {
        const a = r[2]; if (a !== 'cooling' && a !== 'heating') return;
        const end = i + 1 < rows.length ? rows[i + 1][0] : now;
        runs.push({ a: Math.max(t0, r[0]), b: Math.min(now, end), color: a === 'cooling' ? 'var(--teal)' : 'var(--rose)' });
        acts[a] = (acts[a] || 0) + (Math.min(now, end) - Math.max(t0, r[0]));
      }));
      const top = Object.entries(acts).sort((a, b) => b[1] - a[1])[0];
      if (top) runsLabel = `${top[0] === 'cooling' ? 'Cooling' : 'Heating'} · ${hhmm(top[1])}`;
    }
  }
  if (opts.runs && hass.states[opts.runs]) {
    const rows = timeline(hass, opts.runs, t0, now);
    if (rows && !rows.error) {
      const segs = segments(rows, t0, now, (r) => isActive(r.s));
      runs = segs.map((x) => ({ ...x, color: bandColor }));
      runsLabel = `${(hass.states[opts.runs].attributes.friendly_name || opts.runs)} · ${hhmm(segs.reduce((a, x) => a + (x.b - x.a), 0))}`;
    }
  }

  // Scale: every line and the band.
  const vals = main.flatMap((x) => x.pts.map((p) => p[1])).filter((v) => v != null && isFinite(v));
  const BN = 96; const bandPts = [];
  if (bandAt) for (let i = 0; i < BN; i++) { const t = t0 + (i / (BN - 1)) * (now - t0); const b = bandAt(t); bandPts.push([t, b]); if (b) vals.push(b[0], b[1]); }
  if (!vals.length) return header('') + '<p class="sm">Nothing recorded for this stretch.</p>';
  let lo = Math.min(...vals), hi = Math.max(...vals); const m = (hi - lo) * 0.12 || 1; lo -= m; hi += m;
  const X = (t) => ((t - t0) / (now - t0)) * 600;
  const yOf = (v) => 3 + (1 - (v - lo) / (hi - lo)) * (CH - 6);
  const focus = H.focus;
  const lines = main.map((x) => ({ ...x, pts: x.pts.filter((p) => p[1] != null && isFinite(p[1])) }));
  const polys = lines.map((l) => `<polyline points="${l.pts.map((p) => X(p[0]).toFixed(1) + ',' + yOf(p[1]).toFixed(1)).join(' ')}" vector-effect="non-scaling-stroke" stroke-width="${focus === l.id ? 2.4 : 1.6}" stroke-linejoin="round" stroke-linecap="round" style="fill:none;stroke:${l.color};opacity:${focus ? (focus === l.id ? 1 : 0.14) : 0.9}"></polyline>`).join('');
  // The band as one shape; a stretch with no target (the system off) breaks it.
  let band = '';
  if (bandPts.length) {
    const runsOf = []; let cur = [];
    bandPts.forEach((bp) => { if (bp[1]) cur.push(bp); else if (cur.length) { runsOf.push(cur); cur = []; } });
    if (cur.length) runsOf.push(cur);
    band = runsOf.filter((r) => r.length > 1).map((r) => `<polygon points="${r.map((bp) => X(bp[0]).toFixed(1) + ',' + yOf(bp[1][1]).toFixed(1)).concat(r.slice().reverse().map((bp) => X(bp[0]).toFixed(1) + ',' + yOf(bp[1][0]).toFixed(1))).join(' ')}" style="fill:${mix(bandColor, 9)}"></polygon>`).join('');
  }
  const nowBand = bandAt ? bandAt(now) : null;
  const sub = `${lines.length} ${what}${lines.length === 1 ? '' : 's'}${nowBand ? ` · ${bandWord} ${fmt(nowBand[0], '')}${nowBand[1] !== nowBand[0] ? '–' + fmt(nowBand[1], '') : ''}${unit}` : ''}`;
  const key = chartKey({ key: 'ov-' + (card.id || ids.join('+')) }, lines);
  const o = { t0, t1: now, lines, yOf, focus, unit, digits, bandAt, bandWord, sub };
  OV.set(key, o); if (OV.size > 30) OV.delete(OV.keys().next().value);
  CHARTS.set(key, { series: lines, t0, t1: now, unit });
  if (CHARTS.size > 60) CHARTS.delete(CHARTS.keys().next().value);

  const PH = (t) => Math.max(0, Math.min(100, (t - t0) / (now - t0) * 100));
  const runsRow = runs.length ? `<div class="ovrow" style="margin-top:8px;align-items:center"><div class="ovruns" aria-hidden="true">${runs.map((r) => `<span style="left:${PH(r.a).toFixed(2)}%;width:${Math.max(0.8, PH(r.b) - PH(r.a)).toFixed(2)}%;background:${r.color}"></span>`).join('')}</div><span class="ovside small">${esc(runsLabel)}</span></div>` : '';
  // The axis: midnight, 6 AM, noon, 6 PM where they fall, and Now.
  const ticks = [];
  const d = new Date(t0); d.setMinutes(0, 0, 0);
  for (let t = d.getTime(); t <= now; t += 3600000) {
    const h = new Date(t).getHours();
    if (h % 6 || t < t0 + 1.5 * 3600000 || t > now - 3.6 * 3600000) continue;
    ticks.push(`<span style="left:${PH(t).toFixed(2)}%;transform:translateX(-50%)">${h === 0 ? 'Midnight' : h === 12 ? 'Noon' : clock(t).replace(':00', '')}</span>`);
  }
  ticks.push('<span style="left:100%;transform:translateX(-100%)">Now</span>');
  const axis = `<div class="ovrow" aria-hidden="true" style="margin-top:4px"><div class="ovaxis">${ticks.join('')}</div><span class="ovside"></span></div>`;
  const env = extreme.length ? `<div class="ovenv">${extreme.map((x) => `<div class="ovenvi"><span class="nm">${esc(x.short)}</span><b style="color:${x.color}">${isFinite(x.now) ? esc(Number(x.now).toFixed(digits) + unit) : '—'}</b><svg width="56" height="14" viewBox="0 0 56 14" aria-hidden="true"><polyline points="${sparkPts(x.pts, 56, 14)}" stroke-width="1.25" style="fill:none;stroke:${x.color};opacity:.6"></polyline></svg></div>`).join('')}</div>` : '';
  return `${header(sub)}<div class="ovrow" data-ctl="1" style="margin-top:10px"><div class="chart ovplot" data-chart="${key}" data-ov="1" role="img" aria-label="${esc(hd.name || 'Readings')}, last 24 hours, one line per room. Slide along it to read any moment."><svg width="100%" height="${CH}" viewBox="0 0 600 ${CH}" preserveAspectRatio="none" aria-hidden="true">${band}${polys}</svg><span class="scrub" hidden></span><div class="ovdots" data-ovdots="${key}"></div></div><div class="ovside ovlabels" data-ovlabels="${key}">${labelsHtml(o, null)}</div></div>${runsRow}${axis}${env}`;
}

export function clearCache() { CACHE.clear(); }
