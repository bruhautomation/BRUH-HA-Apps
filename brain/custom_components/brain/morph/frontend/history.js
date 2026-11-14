// History, per domain, from what Home Assistant actually records
// (docs/design/morph-ui.md §4). It opens in two layers, both inside the card:
//
//   1. Compact: one summary in the device's colour — a DAY STRIP for things
//      that are on or off (lights, switches, locks, covers, doors, people,
//      thermostat runs) or a 7-BAR WEEK for readings and meters — with one
//      line of context.
//   2. Extended: tap the summary. One view for every card: 24 hours or 7
//      days, the device's lane or line, a few numbers and what happened. The
//      trail starts with the device's name (Kitchen › History › Tue › 3 PM)
//      and each part of it goes back there; a day bar opens that day, and a
//      reading's hour bars open that hour's readings (day → hour). Lines are
//      read by sliding a finger along them and zoomed by dragging a mouse.
//
// Sources: `history/history_during_period` (state timelines),
// `recorder/statistics_during_period` (means, sums), `logbook/get_events`
// (who or what changed it). Every fetch is cached for a minute and asked at
// most once at a time; the panel re-renders when an answer lands.

import { esc, mix, clock, dur, fmt, icon, outdoorStale, domainOf, probeOffline } from './util.js';

const CACHE = new Map();
const MAX_CACHE = 400;
const TTL = 60000;
export const CHARTS = new Map();
let onData = () => {};
export function setOnData(fn) { onData = fn; }
// Bumped whenever an answer lands or a chart's zoom or shown lines change, so
// a drawing can be remembered until then.
let dataVer = 0;
// Morph's cards on a Home Assistant dashboard (morph-cards.js) listen too:
// the panel's one callback is the panel's, and a dashboard card is not in it.
const LISTENERS = new Set();
export function listen(fn) { LISTENERS.add(fn); return () => LISTENERS.delete(fn); }
function landed() {
  onData();
  LISTENERS.forEach((fn) => { try { fn(); } catch (e) { /* one card's redraw is not every card's */ } });
}
const changed = () => { dataVer++; landed(); };

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
    .finally(() => { entry.pending = false; entry.at = Date.now(); changed(); });
  return entry.data;
}

// ------------------------------------------------------------------ zoom
// Every time chart Morph draws can be zoomed (household rule): drag across a
// stretch with a mouse to zoom into it, double-click or "Reset zoom" to go
// back. A finger still slides along the line to read it. The zoom is kept per
// chart (a stable key), so it survives the redraws a live house causes.
const ZOOM = new Map();    // chart key → [t0, t1]
const HIDE = new Map();    // readings card id → Set of hidden entity ids
const ZOOM_MIN = 10 * 60000;
const zoomOf = (key, t0, t1) => {
  const z = ZOOM.get(key); if (!z) return null;
  const a = Math.max(t0, z[0]), b = Math.min(t1, z[1]);
  return b - a >= ZOOM_MIN / 2 ? [a, b] : null;
};
const resetChip = (key) => `<button type="button" class="hz-reset" data-ctl="1" data-zreset="${esc(key)}">Reset zoom</button>`;
const ZCSS = '<style>.hz-row{display:flex;align-items:center;gap:8px}.hz-row>.readout{flex:1;min-width:0}.hz-reset{position:relative;flex:none;border:0;margin:0;font:inherit;font-size:12px;font-weight:600;color:var(--muted);background:var(--chip);border-radius:999px;min-height:28px;padding:0 10px;cursor:pointer}.hz-reset::before{content:"";position:absolute;inset:-8px -2px}.hz-reset:hover{color:var(--text)}.hz-reset:focus-visible{outline:2px solid var(--sky);outline-offset:2px}.hz-band{position:absolute;top:0;bottom:0;background:color-mix(in srgb,var(--sky) 16%,transparent);border-left:1px solid var(--sky);border-right:1px solid var(--sky);pointer-events:none;z-index:2}</style>';
let wired = false;
function wire() {
  if (wired || typeof document === 'undefined') return;
  wired = true;
  const find = (e, sel) => { for (const n of (e.composedPath ? e.composedPath() : [])) { if (n && n.nodeType === 1 && n.matches(sel)) return n; } return null; };
  let drag = null;
  document.addEventListener('pointerdown', (e) => {
    if (e.button || e.pointerType === 'touch') return;
    const ch = find(e, '.chart[data-zkey]'); if (!ch) return;
    drag = { ch, x0: e.clientX, id: e.pointerId, r: ch.getBoundingClientRect(), band: null };
  }, true);
  document.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.band && Math.abs(e.clientX - drag.x0) < 6) return;
    if (!drag.band) { drag.band = document.createElement('span'); drag.band.className = 'hz-band'; drag.ch.appendChild(drag.band); }
    const w = drag.r.width; const a = Math.max(0, Math.min(w, drag.x0 - drag.r.left)), b = Math.max(0, Math.min(w, e.clientX - drag.r.left));
    drag.band.style.left = Math.min(a, b) + 'px'; drag.band.style.width = Math.abs(b - a) + 'px';
  }, true);
  const end = (e, apply) => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null;
    if (!d.band) return;
    d.band.remove();
    if (!apply) return;
    const c = CHARTS.get(d.ch.dataset.chart); if (!c) return;
    const f = (x) => Math.max(0, Math.min(1, (x - d.r.left) / d.r.width));
    const fa = f(Math.min(d.x0, e.clientX)), fb = f(Math.max(d.x0, e.clientX));
    if (fb - fa < 0.01) return;
    let t0 = c.t0 + fa * (c.t1 - c.t0), t1 = c.t0 + fb * (c.t1 - c.t0);
    if (t1 - t0 < ZOOM_MIN) { const m = (t0 + t1) / 2; t0 = m - ZOOM_MIN / 2; t1 = m + ZOOM_MIN / 2; }
    ZOOM.set(d.ch.dataset.zkey, [t0, t1]); changed();
  };
  document.addEventListener('pointerup', (e) => end(e, true), true);
  document.addEventListener('pointercancel', (e) => end(e, false), true);
  document.addEventListener('dblclick', (e) => { const ch = find(e, '.chart[data-zkey]'); if (ch && ZOOM.delete(ch.dataset.zkey)) changed(); }, true);
  document.addEventListener('click', (e) => {
    const z = find(e, '[data-zreset]');
    if (z) { e.stopPropagation(); if (ZOOM.delete(z.dataset.zreset)) changed(); return; }
    const h = find(e, '[data-rhide]');
    if (h) {
      e.stopPropagation();
      const [card, eid] = h.dataset.rhide.split('|');
      const set = HIDE.get(card) || new Set(); if (set.has(eid)) set.delete(eid); else set.add(eid);
      HIDE.set(card, set); changed();
    }
  }, true);
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

// Unavailable stretches are hatched, not counted as off.
const HATCH = 'repeating-linear-gradient(135deg, var(--line2) 0 2px, transparent 2px 5px)';
function stripHtml(segs, start, end, color, gaps) {
  const span = end - start;
  const nowAt = Math.max(0, Math.min(100, (Date.now() - start) / span * 100));
  return `<div class="dstrip" data-hv>${(gaps || []).map((s) => `<span data-tip="Unavailable ${esc(clock(s.a))} – ${esc(clock(s.b))}" style="left:${((s.a - start) / span * 100).toFixed(2)}%;width:${Math.max(0.8, (s.b - s.a) / span * 100).toFixed(2)}%;background:${HATCH}"></span>`).join('')}${segs.map((s) => `<span data-tip="${esc(clock(s.a))} – ${esc(clock(s.b))}" style="left:${((s.a - start) / span * 100).toFixed(2)}%;width:${Math.max(0.8, (s.b - s.a) / span * 100).toFixed(2)}%;background:${color}"></span>`).join('')}<i aria-hidden="true" style="position:absolute;top:0;bottom:0;left:${nowAt.toFixed(2)}%;width:1.5px;margin-left:-.75px;background:var(--muted);opacity:.7"></i></div>
<div class="ticks"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span></div>`;
}
const isGap = (r) => r.s === 'unavailable' || r.s === 'unknown';

function barsHtml(points, color, act, fmtv, labelOf) {
  const vals = points.map((p) => p.v).filter((v) => v != null && isFinite(v));
  if (!vals.length) return '<p class="sm">Nothing recorded for this stretch.</p>';
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1;
  return `<div class="cols" data-hv>${points.map((p) => {
    const h = p.v == null ? 2 : Math.max(3, ((p.v - lo) / (hi - lo || 1)) * 64);
    const tip = `${esc(labelOf(p) || new Date(p.t).toLocaleTimeString([], { hour: 'numeric' }))} · ${esc(fmtv(p.v))}`;
    const inner = `<span class="colv">${p.v == null ? '' : esc(fmtv(p.v))}</span><span class="colbar" style="height:${h}px;background:${mix(color, p.hot ? 85 : 55)}"></span><span class="coll">${esc(labelOf(p))}</span>`;
    // A bar that opens nothing is not a button.
    return act ? `<button type="button" class="colb" data-act="${act}" data-v="${p.t}" data-tip="${tip}" aria-label="${esc(labelOf(p))}: ${esc(fmtv(p.v))}">${inner}</button>` : `<span class="colb" style="cursor:default" data-tip="${tip}">${inner}</span>`;
  }).join('')}</div>`;
}

// A line chart read by sliding a finger (and zoomed by dragging a mouse).
// The series are kept in CHARTS so the panel's pointer handler can answer
// "what was it at this instant". `opts.key` names the chart for good, so its
// zoom and the panel's scrub survive redraws.
export function lineChart(series, t0, t1, opts) {
  const o = opts || {};
  wire();
  const key = 'l:' + (o.key || series.map((s) => s.id).join(','));
  const z = zoomOf(key, t0, t1); if (z) { t0 = z[0]; t1 = z[1]; }
  const inRange = (s) => { const p = s.pts; let a = 0, b = p.length; while (a < p.length - 1 && p[a + 1][0] < t0) a++; while (b > 1 && p[b - 2][0] > t1) b--; return p.slice(a, b); };
  const shown = series.map((s) => ({ ...s, pts: inRange(s) }));
  const all = shown.flatMap((s) => s.pts.filter((p) => p[0] >= t0 && p[0] <= t1).map((p) => p[1])).filter((v) => isFinite(v));
  if (!all.length) return `<p class="sm">Nothing recorded for this stretch.</p>${z ? ZCSS + resetChip(key) : ''}`;
  let lo = Math.min(...all), hi = Math.max(...all);
  const m = (hi - lo) * 0.15 || 1; lo -= m; hi += m;
  if (o.band) { lo = Math.min(lo, o.band[0] - 1); hi = Math.max(hi, o.band[1] + 1); }
  const H = o.height || 120, W = 600;
  const X = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  CHARTS.set(key, { series: shown, t0, t1, unit: o.unit || '' });
  if (CHARTS.size > 60) CHARTS.delete(CHARTS.keys().next().value);
  const focus = o.focus;
  const paths = shown.map((s) => {
    const d = s.pts.filter((p) => isFinite(p[1])).map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
    const dim = focus && focus !== s.id;
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${dim ? 1.2 : 2}" stroke-linejoin="round" stroke-linecap="round" opacity="${dim ? 0.25 : 1}" vector-effect="non-scaling-stroke"></path>`;
  }).join('');
  const band = o.band ? `<rect x="0" width="${W}" y="${Y(o.band[1]).toFixed(1)}" height="${Math.max(1, Y(o.band[0]) - Y(o.band[1])).toFixed(1)}" fill="${mix(o.bandColor || 'var(--teal)', 12)}"></rect>` : '';
  const runs = (o.runs || []).map((r) => `<rect x="${X(r.a).toFixed(1)}" width="${Math.max(1, X(r.b) - X(r.a)).toFixed(1)}" y="${H + 6}" height="5" rx="2" fill="${r.color || 'var(--teal)'}"></rect>`).join('');
  const SH = H + (o.runs ? 14 : 2);
  // Labels at the end of each line, in HTML beside the plot (an SVG drawn to
  // fit its box would stretch them), nudged apart so they never collide.
  let labels = '';
  if (shown.length > 1) {
    const ends = shown.map((s) => { const last = s.pts.filter((p) => isFinite(p[1]) && p[0] <= t1).slice(-1)[0]; return last ? { s, y: Y(last[1]) } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    labels = `<div aria-hidden="true" style="position:relative;flex:none;width:84px;height:${SH}px">${ends.map((e) => `<span style="position:absolute;left:0;right:0;top:${(e.y - 8).toFixed(1)}px;font-size:11px;line-height:16px;color:${e.s.color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:${focus && focus !== e.s.id ? 0.35 : 1}">${esc(e.s.short || e.s.name)}</span>`).join('')}</div>`;
  }
  // One line: its highest and lowest values in a quiet gutter, so a chart
  // always says what it measures (a bare line read as decoration; Oct 2026).
  if (!labels && shown.length === 1) {
    const rmin = Math.min(...all), rmax = Math.max(...all);
    const fv = (v) => (Math.abs(rmax - rmin) < 10 ? Math.round(v * 10) / 10 : Math.round(v)) + (o.unit && o.unit.length <= 2 ? o.unit : '');
    labels = `<div aria-hidden="true" style="position:relative;flex:none;width:44px;height:${SH}px;font-size:11px;line-height:16px;color:var(--quiet);font-variant-numeric:tabular-nums"><span style="position:absolute;right:0;top:${Math.max(0, Y(rmax) - 8).toFixed(1)}px">${esc(fv(rmax))}</span>${rmax !== rmin ? `<span style="position:absolute;right:0;top:${Math.min(SH - 16, Y(rmin) - 8).toFixed(1)}px">${esc(fv(rmin))}</span>` : ''}</div>`;
  }
  // When: the start, the middle and the end under the plot.
  const tl = (t) => { const d = new Date(t); return t1 - t0 > 36 * 3600000 ? d.toLocaleDateString([], { weekday: 'short' }) : d.toLocaleTimeString([], { hour: 'numeric' }); };
  const xt = `<div aria-hidden="true" style="display:flex;justify-content:space-between;font-size:11px;color:var(--quiet);margin-top:4px;padding-right:${labels ? (shown.length > 1 ? 92 : 52) : 0}px"><span>${esc(tl(t0))}</span><span>${esc(tl((t0 + t1) / 2))}</span><span>${esc(tl(t1))}</span></div>`;
  const chart = `<div class="chart" data-chart="${esc(key)}" data-zkey="${esc(key)}" data-ctl="1" style="flex:1;min-width:0"><svg viewBox="0 0 ${W} ${SH}" preserveAspectRatio="none" style="height:${SH}px;overflow:hidden">${band}${paths}${runs}</svg><span class="scrub" hidden></span></div>`;
  return `${ZCSS}${labels ? `<div style="display:flex;gap:8px">${chart}${labels}</div>` : chart}${o.noTicks ? '' : xt}<div class="hz-row"><div class="readout" data-readout="${esc(key)}">${esc(o.caption || '')}</div>${z ? resetChip(key) : ''}</div>`;
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

// ------------------------------------------------------------------ the history view
// Opened from a card's compact history (house change): the same view for every
// card, the one the doors card made. A range switch (24 hours or 7 days), the
// device's own lane on a timeline (7 days: one row per day), a few plain
// numbers, and what happened, newest first. Readings and meters get the same
// frame with a line or bars in place of the lane.

const HX_DAY = 86400000;
// A day bar that was tapped opens that day; the range words choose again.
function hxRange(H, now) {
  if (H.day != null && !H.range) { const a = dayStart(H.day); return { week: false, start: a, end: Math.min(now, a + HX_DAY), day: a }; }
  const week = H.range === 'week'; return { week, start: week ? dayStart(now - 6 * HX_DAY) : now - HX_DAY, end: now };
}
function hxWhen(t) {
  const d0 = dayStart(Date.now());
  if (t >= d0) return clock(t);
  if (t >= d0 - HX_DAY) return 'Yesterday ' + clock(t);
  return new Date(t).toLocaleDateString([], { weekday: 'short' }) + ' ' + clock(t);
}
// History belongs to its device (rule 11): it starts with the device's icon
// and name in its colour, then the range words.
const HX_CSS = '<style>.hx-rg button{position:relative}.hx-rg button::before{content:"";position:absolute;inset:-9px -3px}.hx-rg button:focus-visible{outline:2px solid var(--sky);outline-offset:2px}.hx-who{display:inline-flex;align-items:center;gap:7px;min-width:0;min-height:32px;padding:0;border:0;margin:0;background:none;font:inherit;font-size:13px;font-weight:600;color:var(--c);cursor:pointer}.hx-who:focus-visible,.hx-top .crumb:focus-visible{outline:2px solid var(--sky);outline-offset:2px}.hx-who span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}</style>';
// The trail: the device's name goes back to the card's summary, History to
// the 24-hour (or 7-day) view, the day back to that day; the last part is
// where the view is now.
const hxHour = (H) => (H.depth >= 2 && H.hour != null ? Number(H.hour) : null);
function hxHead(name, H, color, ic) {
  const day = H.day != null && !H.range;
  const hour = hxHour(H);
  const r = H.range === 'week' ? 'week' : 'day';
  const words = [['day', '24 hours'], ['week', '7 days']].map(([k, l]) => `<button type="button" data-act="h-range" data-v="${k}" aria-pressed="${!day && hour == null && r === k}">${l}</button>`);
  const crumbs = [];
  const sep = '<span class="small" aria-hidden="true">›</span>';
  if (day || hour != null) {
    crumbs.push(`<button type="button" class="crumb" data-act="h-range" data-v="${r}">History</button>`);
    const d = day ? H.day : hour;
    const dw = esc(new Date(d).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }));
    crumbs.push(hour != null && day ? `<button type="button" class="crumb" data-act="h-back" data-v="1">${dw}</button>` : `<span class="crumb" aria-current="page" style="cursor:default">${dw}</span>`);
    if (hour != null) crumbs.push(`<span class="crumb" aria-current="page" style="cursor:default">${esc(clock(hour))}</span>`);
  }
  const who = `<button type="button" class="hx-who" data-act="h-back" data-v="0" aria-label="${esc(name || '')}: back to the summary">${icon(ic || 'dot', { color, size: 15 })}<span>${esc(name || '')}</span></button>`;
  return `${HX_CSS}<div class="hx-top"><div class="crumbs">${who}${crumbs.map((c) => sep + c).join('')}</div><div class="hx-rg">${words.join('')}</div></div>`;
}
const iconOf = (card, st) => {
  const dc = st && st.attributes && st.attributes.device_class;
  return { light: 'bulb', light_group: 'group', fan: 'fan', fan_group: 'fan', cover: 'blinds', cover_group: 'blinds', lock: 'lock', switch: 'power', climate: 'thermo', person: 'person', media: 'speaker', camera: 'camera', vacuum: 'vacuum', alarm: 'shield', button: 'play', list: 'door' }[card.type]
    || (dc === 'temperature' ? 'thermo' : dc === 'humidity' ? 'humid' : /water|gas/.test(dc || '') ? 'water' : dc === 'power' || dc === 'energy' ? 'bolt' : 'dot');
};
const hxNums = (nums) => `<div class="hx-nums">${nums.map(([v, l]) => `<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('')}</div>`;

// The lane chart: one row for 24 hours, one row per day for 7 days.
function hxLanes(segs, start, end, week, color, word, gaps) {
  const W = 600, left = week ? 40 : 0, lane = week ? 9 : 14, rowH = lane + (week ? 6 : 8);
  const rows = [];
  if (week) for (let t = start; t < end; t += HX_DAY) rows.push({ a: t, b: t + HX_DAY, label: new Date(t).toLocaleDateString([], { weekday: 'short' }) });
  else rows.push({ a: start, b: end, label: '' });
  const wpx = W - left; let k = 0;
  let svg = `<svg viewBox="0 0 ${W} ${rows.length * rowH + 14}" role="img" aria-label="${esc(word)} over ${week ? 'the last 7 days' : 'the last 24 hours'}"><defs><pattern id="hxhatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.6" height="5" fill="var(--line2)"/></pattern></defs>`;
  let grid = '';
  rows.forEach((r, i) => {
    const y = i * rowH; const len = r.b - r.a;
    if (week) svg += `<text x="0" y="${y + lane - 1}">${esc(r.label)}</text>`;
    const filled = Math.max(0, Math.min(1, (end - r.a) / len)) * wpx;
    svg += `<rect x="${left}" y="${y}" width="${filled.toFixed(1)}" height="${lane}" rx="${(lane / 2.4).toFixed(1)}" fill="var(--sunk)"/>`;
    (gaps || []).forEach((sp) => {
      const a = Math.max(sp.a, r.a), b = Math.min(sp.b, r.b, end);
      if (b <= a) return;
      svg += `<rect x="${(left + ((a - r.a) / len) * wpx).toFixed(1)}" y="${y}" width="${Math.max(2, ((b - a) / len) * wpx).toFixed(1)}" height="${lane}" fill="url(#hxhatch)" data-tip="Unavailable ${esc(hxWhen(a))} · ${esc(dur(b - a))}"/>`;
    });
    segs.forEach((sp) => {
      const a = Math.max(sp.a, r.a), b = Math.min(sp.b, r.b, end);
      if (b <= a) return;
      const x = left + ((a - r.a) / len) * wpx, w = Math.max(3, ((b - a) / len) * wpx);
      svg += `<rect class="sp" style="animation-delay:${Math.min(k++ * 16, 360)}ms" x="${x.toFixed(1)}" y="${y}" width="${w.toFixed(1)}" height="${lane}" rx="${(lane / 2.4).toFixed(1)}" fill="${color}" data-tip="${esc(word)} ${esc(hxWhen(a))} · ${esc(dur(b - a))}"/>`;
    });
  });
  const by = rows.length * rowH + 10;
  if (week) {
    ['12a', '6a', '12p', '6p', '12a'].forEach((t, i) => { svg += `<text x="${(left + i * wpx / 4).toFixed(1)}" y="${by}" text-anchor="${i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}">${t}</text>`; });
  } else {
    const first = new Date(start); first.setMinutes(0, 0, 0); first.setHours(Math.ceil((first.getHours() + 1) / 6) * 6);
    for (let t = first.getTime(); t < end; t += 6 * 3600000) {
      const x = left + ((t - start) / (end - start)) * wpx; if (x > W - 28) break;
      grid += `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="0" y2="${by - 9}" stroke="var(--line)" stroke-dasharray="2 3"/>`;
      svg += `<text x="${x.toFixed(1)}" y="${by}" text-anchor="middle">${esc(new Date(t).toLocaleTimeString([], { hour: 'numeric' }))}</text>`;
    }
    svg += `<text x="${W}" y="${by}" text-anchor="end">now</text>`;
  }
  return `<div class="hx-tl" data-hv>${svg.replace('</defs>', '</defs>' + grid)}</svg></div>`;
}

function hxWords(card, runs) {
  if (runs) return { on: 'Ran', off: 'Stopped', noun: ['run', 'runs'], what: 'Running' };
  if (card.type === 'lock') return { on: 'Unlocked', off: 'Locked', noun: ['unlock', 'unlocks'], what: 'Unlocked' };
  if (['cover', 'cover_group', 'list'].includes(card.type)) return { on: 'Opened', off: 'Closed', noun: ['opening', 'openings'], what: 'Open' };
  if (card.type === 'person') return { on: 'Arrived', off: 'Left', noun: ['arrival', 'arrivals'], what: 'Home' };
  return { on: 'Turned on', off: 'Turned off', noun: ['time on', 'times on'], what: 'On' };
}

function hxStates(hass, card, st, H, color, name, runs, test) {
  const { week, start, end: now } = hxRange(H, Date.now());
  const head = hxHead(name, H, color, iconOf(card, st));
  const rows = timeline(hass, card.entity, start, now, runs);
  const book = logbook(hass, card.entity, start, now);
  // Who or what changed it: the logbook entry at the same moment.
  const byAt = (t) => { if (!Array.isArray(book)) return ''; const x = book.find((b) => Math.abs(b.t - t) < 3000 && b.by); return x ? ' · by ' + x.by : ''; };
  if (rows === undefined) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Reading history…</p></div>`;
  if (rows.error) return `<div class="hx" style="--c:${color}">${head}<p class="sm">History could not be read: ${esc(rows.error)}</p></div>`;
  const segs = segments(rows, start, now, test);
  const gaps = segments(rows, start, now, isGap);
  const w = hxWords(card, runs);
  const began = segs.filter((sg) => sg.a > start + 1000);
  const longest = segs.reduce((m, sg) => Math.max(m, sg.b - sg.a), 0);
  const total = segs.reduce((m, sg) => m + (sg.b - sg.a), 0);
  const last = began.length ? began[began.length - 1].a : null;
  const span = week ? 'in 7 days' : 'in 24 h';
  const nums = hxNums([
    [String(began.length), `${began.length === 1 ? w.noun[0] : w.noun[1]} ${span}`],
    [last ? hxWhen(last) : '—', `last ${w.on.toLowerCase()}`],
    [longest ? dur(longest) : '—', `longest · ${total ? dur(total) + ' in all' : 'never'}`],
  ]);
  const ev = [];
  segs.forEach((sg, i) => {
    const live = i === segs.length - 1 && test(rows[rows.length - 1] || {});
    if (sg.a > start + 1000) ev.push({ t: sg.a, on: true, txt: (live ? `${w.on} · still ${w.what.toLowerCase()}` : `${w.on} · for ${dur(sg.b - sg.a)}`) + byAt(sg.a) });
    if (!live && sg.b < now - 1000) ev.push({ t: sg.b, on: false, txt: w.off + byAt(sg.b) });
  });
  ev.sort((x, y) => y.t - x.t);
  const list = ev.length
    ? `<div class="hx-lg">${ev.slice(0, 10).map((e) => `<div><i style="background:${e.on ? color : 'var(--line2)'}"></i>${esc(e.txt)}<em>${esc(hxWhen(e.t))}</em></div>`).join('')}</div>`
    : `<p class="sm">Nothing changed ${week ? 'this week' : 'in the last 24 hours'}.</p>`;
  return `<div class="hx" style="--c:${color}">${head}${hxLanes(segs, start, now, week, color, w.what, gaps)}${nums}${list}</div>`;
}

// The hour a bar was tapped for: that hour's readings, with the hour before
// and the two after for context (the shipped drill-down's last step).
function hxHourView(hass, card, st, H, color, name, unit, hour) {
  const head = hxHead(name, H, color, iconOf(card, st));
  const now = Date.now();
  const a = hour - 3600000, b = Math.min(now, hour + 7200000);
  const rows = timeline(hass, card.entity, a, b);
  if (rows === undefined) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Reading the hour…</p></div>`;
  if (rows.error) return `<div class="hx" style="--c:${color}">${head}<p class="sm">History could not be read: ${esc(rows.error)}</p></div>`;
  const pts = rows.map((r) => [Math.max(a, r.t), parseFloat(r.s)]).filter((p) => isFinite(p[1]));
  if (!pts.length) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Nothing recorded around ${esc(clock(hour))}: Home Assistant has recorded nothing for it then.</p></div>`;
  const fv = (v) => fmt(v, unit);
  const vals = pts.map((p) => p[1]);
  return `<div class="hx" style="--c:${color}">${head}${lineChart([{ id: card.entity, name, color, pts }], a, b, { unit, key: 'hx:' + card.entity + ':h' + hour })}${hxNums([[`${fv(Math.min(...vals))} – ${fv(Math.max(...vals))}`, 'low – high'], [String(pts.length), pts.length === 1 ? 'reading' : 'readings']])}</div>`;
}
const hourLabel = (p) => { const h = new Date(p.t).getHours(); return h % 6 === 0 ? (h === 0 ? '12a' : h === 12 ? '12p' : (h % 12) + (h < 12 ? 'a' : 'p')) : ''; };
const NONE_YET = 'Home Assistant has recorded nothing for it yet.';

function hxReading(hass, card, st, H, color, name, meter, unit) {
  const hour = hxHour(H);
  if (hour != null) return hxHourView(hass, card, st, H, color, name, unit, hour);
  const { week, start, end: now, day } = hxRange(H, Date.now());
  const head = hxHead(name, H, color, iconOf(card, st));
  const fv = (v) => fmt(v, unit);
  if (meter) {
    const pts = stats(hass, card.entity, start, now, week ? 'day' : 'hour');
    if (pts === undefined) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Reading history…</p></div>`;
    if (pts.error || !pts.length) return `<div class="hx" style="--c:${color}">${head}<p class="sm">No statistics for this one yet: ${NONE_YET}</p></div>`;
    const vals = pts.map((p) => ({ t: p.t, v: p.change }));
    const sum = vals.reduce((m, p) => m + (p.v || 0), 0);
    const peak = vals.reduce((m, p) => (p.v != null && (!m || p.v > m.v) ? p : m), null);
    const label = (p) => (week ? new Date(p.t).toLocaleDateString([], { weekday: 'short' }) : hourLabel(p));
    // A day's bar opens that day; an hour's bar opens that hour.
    return `<div class="hx" style="--c:${color}">${head}${barsHtml(vals, color, week ? 'h-day' : 'h-hour', fv, label)}${hxNums([[fv(sum), week ? 'in 7 days' : day != null ? 'that day' : 'in 24 h'], [peak ? fv(peak.v) : '—', week ? 'busiest day' : 'busiest hour'], [peak ? (week ? new Date(peak.t).toLocaleDateString([], { weekday: 'long' }) : clock(peak.t)) : '—', week ? 'on' : 'at']])}</div>`;
  }
  let pts;
  if (week) {
    const hrs = stats(hass, card.entity, start, now, 'hour');
    if (hrs === undefined) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Reading history…</p></div>`;
    pts = (hrs.error ? [] : hrs).map((p) => [p.t, p.mean]);
  } else {
    const rows = timeline(hass, card.entity, start, now);
    if (rows === undefined) return `<div class="hx" style="--c:${color}">${head}<p class="sm">Reading history…</p></div>`;
    pts = (rows.error ? [] : rows).map((r) => [r.t, parseFloat(r.s)]);
  }
  const vals = pts.map((p) => p[1]).filter((v) => v != null && isFinite(v));
  if (!vals.length) return `<div class="hx" style="--c:${color}">${head}<p class="sm">No history ${week ? 'in the last 7 days' : day != null ? 'that day' : 'in the last 24 hours'}: ${NONE_YET}</p></div>`;
  const lo = Math.min(...vals), hi = Math.max(...vals), avg = vals.reduce((a, v) => a + v, 0) / vals.length;
  // Under the line, a way down: in 7 days each day opens that day; in a day
  // (or the last 24 hours) each hour's average is a bar that opens that hour.
  let drill = '';
  if (week) {
    const days = []; for (let t = start; t < now; t += HX_DAY) days.push(t);
    drill = `<div class="row" style="flex-wrap:wrap;gap:0 14px">${days.map((d) => `<button type="button" class="wd" data-act="h-day" data-v="${d}">${esc(new Date(d).toLocaleDateString([], { weekday: 'short' }))}</button>`).join('')}</div>`;
  } else {
    const hrs = stats(hass, card.entity, start, now, 'hour');
    if (Array.isArray(hrs) && hrs.length > 1) drill = `<span class="small">Each hour · tap one for its readings</span>${barsHtml(hrs.map((p) => ({ t: p.t, v: p.mean })), color, 'h-hour', fv, hourLabel)}`;
  }
  return `<div class="hx" style="--c:${color}">${head}${lineChart([{ id: card.entity, name, color, pts }], start, now, { unit, key: 'hx:' + card.entity + ':' + (week ? 'w' : day != null ? day : 'd') })}${hxNums([[day != null ? fv(pts[pts.length - 1][1]) : fv(parseFloat(st.state)), day != null ? 'at day end' : 'now'], [`${fv(lo)} – ${fv(hi)}`, 'low – high'], [fv(avg), week ? 'average · 7 days' : day != null ? 'average · that day' : 'average · 24 h']])}${drill}</div>`;
}

// ------------------------------------------------------------------ blocks

// A card may carry options.also: more sensors whose history opens beneath
// its own (a freezer's humidity under its temperature).
export function block(hass, card, st, H, color, name) {
  const main = blockOne(hass, card, st, H, color, name);
  const also = (card.options && card.options.also) || [];
  const extra = (Array.isArray(also) ? also : [also]).map((e) => {
    const s2 = hass.states[e]; if (!s2) return '';
    const nm = (s2.attributes && s2.attributes.friendly_name) || e;
    const h = blockOne(hass, { ...card, entity: e, options: {} }, s2, H, color, nm);
    return h ? `<div class="sm" style="margin-top:10px;font-weight:600">${esc(nm)}</div>${h}` : '';
  }).join('');
  return main + extra;
}
function blockOne(hass, card, st, H, color, name) {
  const eid = card.entity;
  if (!eid || !st) return '';
  const kind = kindOf(card.type, st);
  const now = Date.now();
  const d0 = dayStart(now);
  const unit = (st.attributes && st.attributes.unit_of_measurement) || '';
  try {
    if (kind === 'strip' || kind === 'runs') {
      const runs = kind === 'runs';
      const test = runs ? (r) => ['heating', 'cooling', 'drying', 'fan'].includes(r.a && r.a.hvac_action) : (r) => isActive(r.s);
      if (!H.depth) {
        const rows = timeline(hass, eid, d0, now, runs);
        if (rows === undefined) return '<p class="sm">Reading history…</p>';
        if (rows.error) return `<p class="sm">History could not be read: ${esc(rows.error)}</p>`;
        const segs = segments(rows, d0, now, test);
        const holes = runs ? [] : gaps(rows, d0, now);
        const total = segs.reduce((a, s) => a + (s.b - s.a), 0);
        const word = runs ? 'Ran' : card.type === 'lock' ? 'Unlocked' : ['cover', 'list'].includes(card.type) ? 'Open' : card.type === 'person' ? 'Home' : 'On';
        const changes = rows.length;
        return `<button type="button" class="lrow" data-act="h-open" style="border-top:0;flex-direction:column;align-items:stretch;gap:6px"><span class="rowb"><b style="font-size:13px">${esc(word)} ${esc(dur(total))} today</b><span class="small">${changes} change${changes === 1 ? '' : 's'}</span></span>${stripHtml(segs, d0, d0 + 86400000, mix(color, 70), holes)}</button>`;
      }
      return hxStates(hass, card, st, H, color, name, runs, test);
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
          return lineChart([{ id: eid, name, color, pts: rows.map((r) => [r.t, parseFloat(r.s)]) }], now - 86400000, now, { unit, key: 'blk:' + eid });
        }
        const pts = week.map((p) => ({ t: p.t, v: val(p) }));
        const today = pts[pts.length - 1];
        return `<div class="rowb"><b style="font-size:13px">${meter ? 'Today ' + esc(fv(today && today.v)) : 'Daily average · 7 days'}</b></div>${barsHtml(pts.map((p) => ({ ...p, hot: p.t === (today && today.t) })), color, 'h-day', fv, (p) => new Date(p.t).toLocaleDateString([], { weekday: 'short' }))}`;
      }
      return hxReading(hass, card, st, H, color, name, meter, unit);
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
// One hue per line, in the order the card lists its sensors, so two rooms
// never share a colour; how warm a room is shows in its value instead (the
// house's order).
export const SERIES = ['var(--sky)', 'var(--peach)', 'var(--violet)', 'var(--teal)', 'var(--amber)', 'var(--indigo)', 'var(--rose)', 'var(--sand)', 'var(--lime)'];
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
  let lab = lines.map((l) => { let v = at == null ? l.now : valueAt(l.pts, at); if (v != null && !isFinite(v)) v = null; return { l, v, y: v == null ? CH : yOf(v) }; }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < lab.length; i++) lab[i].y = Math.max(lab[i].y, lab[i - 1].y + LABEL_GAP);
  const over = lab.length ? lab[lab.length - 1].y - (CH - 9) : 0;
  if (over > 0) { lab[lab.length - 1].y -= over; for (let i = lab.length - 2; i >= 0; i--) lab[i].y = Math.min(lab[i].y, lab[i + 1].y - LABEL_GAP); }
  return lab.map((x) => `<span class="ovlab" style="top:${(x.y - 9).toFixed(1)}px;cursor:default;opacity:${focus && focus !== x.l.id ? 0.45 : x.l.old && at == null ? 0.55 : 1}"><span class="sw" style="background:${x.l.color}"></span><span class="nm">${esc(x.l.short)}</span>${x.v == null ? `<b style="color:var(--quiet)">${x.l.dead && at == null ? 'offline' : '—'}</b>` : `<b style="color:${x.l.valColor || (!o.valueColor ? 'var(--text)' : o.valueColor(x.v))}">${esc(Number(x.v).toFixed(digits) + unit)}</b>`}</span>`).join('');
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

const RMEMO = new Map(); // card id → { k, html }
// Time labels for any stretch: 4–6 round times, Midnight and Noon by name.
function axisTicks(t0, t1) {
  const span = t1 - t0; const M = 60000;
  const step = [10, 15, 30, 60, 120, 180, 360, 720].map((x) => x * M).find((x) => span / x <= 6) || 1440 * M;
  const out = []; const d = new Date(t0); d.setSeconds(0, 0);
  let t = Math.ceil(d.getTime() / step) * step;
  // Round to local hours for steps of an hour or more.
  if (step >= 60 * M) { const h = new Date(t0); h.setMinutes(0, 0, 0); t = h.getTime(); while (t < t0 || new Date(t).getHours() % (step / (60 * M))) t += 60 * M; }
  for (; t <= t1; t += step) {
    const f = (t - t0) / span; if (f < 0.06 || f > 0.86) continue;
    const dt = new Date(t); const h = dt.getHours(), mi = dt.getMinutes();
    out.push([f, mi === 0 && h === 0 ? 'Midnight' : mi === 0 && h === 12 ? 'Noon' : clock(t).replace(':00', '')]);
  }
  return out;
}
// The sensor a chart of readings takes its kind and unit from: its first
// sensor, since a thermostat's own state is its mode, not a reading.
export const readingsFirst = (hass, ids) => {
  const S = hass.states; const own = (ids || []).filter((e) => S[e]);
  return S[own.find((e) => domainOf(e) !== 'climate') || own[0]];
};

export function readings(hass, card, H, colorFor, head) {
  wire();
  const hd = head || {};
  const ids = (card.entities || []).filter((e) => hass.states[e]);
  const header = (sub) => `<div class="ovhead"><b>${esc(hd.name || '')}</b><span class="ovsub" data-ovsub="1">${esc(sub || '')}</span><span class="flex1"></span>${hd.hint ? `<span class="hint">${esc(hd.hint)}</span>` : ''}</div>`;
  if (!ids.length) return header('') + '<p class="sm">None of these sensors exist.</p>';
  const now = Date.now(), d0 = now - 86400000;
  const key = 'r:' + (card.id || ids.join(','));
  const hidden = HIDE.get(card.id || key) || new Set();
  const z = zoomOf(key, d0, now);
  const t0 = z ? z[0] : d0, t1 = z ? z[1] : now;
  // Drawn once per minute, per answer and per change to what it shows: a
  // live house sets hass many times a second.
  const mk = [dataVer, Math.floor(now / 60000), H.focus || '', [...hidden].join(','), z ? z.join('-') : '', hd.name || '', hd.hint || '', ids.map((e) => hass.states[e].state).join(',')].join('|');
  const hit = RMEMO.get(key); if (hit && hit.k === mk) return hit.html;
  const opts = card.options || {};
  const first = readingsFirst(hass, ids);
  const thermostats = domainOf(first.entity_id) === 'climate';
  const unitRaw = thermostats ? (hass.config && hass.config.unit_system && hass.config.unit_system.temperature) || '°' : first.attributes.unit_of_measurement || '';
  const dc = first.attributes.device_class;
  // What these lines ARE: a soil-moisture card was called "rooms", given a
  // degree sign and drawn under the thermostats' target band.
  const moisture = dc === 'moisture' || /moist|soil/i.test(ids.join(' '));
  const temperature = !moisture && (dc === 'temperature' || /°/.test(unitRaw));
  const humidity = !moisture && !temperature && (dc === 'humidity' || unitRaw === '%');
  const unit = temperature ? '°' : unitRaw === '%' ? '%' : unitRaw ? ' ' + unitRaw : '';
  // Temperature and humidity lines are rooms; anything else (soil moisture) is sensors.
  const what = temperature || humidity ? 'room' : 'sensor';
  // A thermostat's reading is its own sensor: an attribute, not its state.
  const attr = humidity ? 'current_humidity' : 'current_temperature';
  // #764: a thermostat that stopped answering keeps its last attributes, so
  // its reading is nothing (no live label, no line to now) while its state
  // is unavailable or unknown, now and in each history row.
  const valueOf = (eid, s, a) => GAP.includes(String(s)) ? NaN : parseFloat(domainOf(eid) === 'climate' ? (a || {})[attr] : s);
  const series = [];
  let pending = false;
  ids.forEach((eid) => {
    // #757: a chart of rooms drew no lines although every room had a
    // reading. Statistics exist only for a sensor with a state_class, and
    // never for a thermostat, so a room with none is read from its recorded
    // history instead (a thermostat's with its attributes).
    const rows = stats(hass, eid, d0, now, '5minute');
    if (rows === undefined) { pending = true; return; }
    let pts = Array.isArray(rows) ? rows.map((p) => [p.t, p.mean]).filter((p) => p[1] != null && isFinite(p[1])) : [];
    const st = hass.states[eid];
    const cur = valueOf(eid, st.state, st.attributes);
    if (!pts.length) {
      const tl = timeline(hass, eid, d0, now, domainOf(eid) === 'climate');
      if (tl === undefined) pending = true;
      pts = Array.isArray(tl) ? tl.map((r) => [Math.max(d0, r.t), valueOf(eid, r.s, r.a)]).filter((p) => isFinite(p[1])) : [];
      if (pts.length && isFinite(cur)) pts.push([now, cur]);
    }
    // #787: a moisture probe that fell straight to 0 is drawn up to the
    // fall and read as a probe to check, never as 0%.
    const dead = probeOffline(hass, eid, isFinite(cur) ? pts.concat([[now, cur]]) : pts);
    if (dead) { let i = pts.length; while (i > 0 && pts[i - 1][1] === 0) i -= 1; pts = pts.slice(0, i); }
    const nm = st.attributes.friendly_name || eid;
    // A line's colour is its place in a fixed palette, so two rooms never
    // share one; the reading's own warmth colours its value instead.
    series.push({ id: eid, old: outdoorStale(hass, eid), dead, name: nm, short: nm.replace(/\s*(temperature|humidity|temp|moisture)$/i, ''), color: SERIES[series.length % SERIES.length], valColor: colorFor(cur), pts, now: dead ? NaN : cur });
  });
  if (pending && !series.some((x) => x.pts.length)) return header('') + '<p class="sm">Reading the day…</p>';
  const digits = humidity || moisture || unitRaw === '%' ? 0 : temperature ? 1 : Math.abs(series[0] ? series[0].now : 0) >= 100 ? 0 : 1;
  // A prefix every name shares ("Soil - Trees", "Soil - Garden") says what the
  // card's own title already says; drop it so the labels beside the plot fit.
  if (series.length > 1) {
    const m = series[0].short.match(/^(.+?\s[-–:]\s)/);
    if (m && series.every((x) => x.short.startsWith(m[1]) && x.short.length > m[1].length)) series.forEach((x) => { x.short = x.short.slice(m[1].length); });
  }
  // Extremes (an attic, the outside) leave the plot for the line below it;
  // a reading with nothing now (it stopped answering) keeps its place.
  const meds = series.map((x) => x.now).filter(isFinite).sort((a, b) => a - b);
  const med = meds[Math.floor(meds.length / 2)];
  const spread = meds.length > 3 ? (meds[Math.floor(meds.length * 0.75)] - meds[Math.floor(meds.length * 0.25)]) || 2 : Infinity;
  const main = series.filter((x) => !isFinite(spread) || !isFinite(x.now) || Math.abs(x.now - med) <= 3 * spread);
  const extreme = series.filter((x) => !main.includes(x));
  (opts.env || []).forEach((eid) => {
    const st = hass.states[eid]; if (!st || series.some((x) => x.id === eid)) return;
    const rows = stats(hass, eid, d0, now, '5minute');
    const nm = st.attributes.friendly_name || eid;
    extreme.push({ id: eid, old: outdoorStale(hass, eid), short: nm.replace(/\s*(temperature|humidity|temp)$/i, ''), color: 'var(--muted)', now: parseFloat(st.state), pts: Array.isArray(rows) ? rows.map((p) => [p.t, p.mean]) : [] });
  });

  // What the house was aiming for: a band the card names, or the
  // thermostats' own target through the day.
  let bandAt = null; const bandWord = humidity ? 'comfortable' : 'target'; let runs = []; let runsLabel = '';
  const bandColor = humidity ? 'var(--sky)' : 'var(--teal)';
  if (Array.isArray(opts.band) && opts.band.length === 2) {
    const fixed = [Number(opts.band[0]), Number(opts.band[1])];
    bandAt = () => fixed;
  } else if (temperature) {
    const climates = (opts.climate ? [].concat(opts.climate) : Object.keys(hass.states).filter((e) => e.startsWith('climate.'))).filter((e) => hass.states[e] && !GAP.includes(hass.states[e].state)).slice(0, 4);
    const tls = climates.map((c) => climateTargets(timeline(hass, c, d0, now, true))).filter((r) => r.length);
    if (tls.length) {
      // The last row at or before t, by halving (rows are in time order).
      const at = (rows, t) => { let a = 0, b = rows.length - 1; if (rows[0][0] > t) return rows[0]; while (a < b) { const m = (a + b + 1) >> 1; if (rows[m][0] <= t) a = m; else b = m - 1; } return rows[a]; };
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
        runs.push({ a: Math.max(d0, r[0]), b: Math.min(now, end), color: a === 'cooling' ? 'var(--teal)' : 'var(--rose)' });
        acts[a] = (acts[a] || 0) + (Math.min(now, end) - Math.max(d0, r[0]));
      }));
      const top = Object.entries(acts).sort((a, b) => b[1] - a[1])[0];
      if (top) runsLabel = `${top[0] === 'cooling' ? 'Cooling' : 'Heating'} · ${hhmm(top[1])}`;
    }
  }
  if (opts.runs && hass.states[opts.runs]) {
    const rows = timeline(hass, opts.runs, d0, now);
    if (rows && !rows.error) {
      const segs = segments(rows, d0, now, (r) => isActive(r.s));
      runs = segs.map((x) => ({ ...x, color: bandColor }));
      runsLabel = `${(hass.states[opts.runs].attributes.friendly_name || opts.runs)} · ${hhmm(segs.reduce((a, x) => a + (x.b - x.a), 0))}`;
    }
  }

  // Scale: every shown line (within the stretch drawn) and the band.
  const lines = main.filter((x) => !hidden.has(x.id)).map((x) => {
    const p = x.pts.filter((q) => q[1] != null && isFinite(q[1]));
    let a = 0, b = p.length; while (a < p.length - 1 && p[a + 1][0] < t0) a++; while (b > 1 && p[b - 2][0] > t1) b--;
    return { ...x, pts: p.slice(a, b) };
  });
  const vals = lines.flatMap((x) => x.pts.filter((q) => q[0] >= t0 && q[0] <= t1).map((q) => q[1]));
  const BN = 96; const bandPts = [];
  if (bandAt) for (let i = 0; i < BN; i++) { const t = t0 + (i / (BN - 1)) * (t1 - t0); const b = bandAt(t); bandPts.push([t, b]); if (b && lines.length) vals.push(b[0], b[1]); }
  const chips = main.length > 1 ? `<div class="ovchips" role="group" aria-label="Lines shown">${main.map((x) => `<button type="button" class="ovchip" data-ctl="1" data-rhide="${esc((card.id || key) + '|' + x.id)}" aria-pressed="${!hidden.has(x.id)}"><i style="background:${x.color}"></i>${esc(x.short)}</button>`).join('')}</div>` : '';
  const CSS = '<style>.ovchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.ovchip{position:relative;display:inline-flex;align-items:center;gap:6px;min-height:28px;padding:0 10px;border:0;margin:0;border-radius:999px;background:var(--chip);color:var(--muted);font:inherit;font-size:12px;font-weight:600;cursor:pointer;transition:color .25s var(--ease)}.ovchip::before{content:"";position:absolute;inset:-8px -2px}.ovchip i{width:8px;height:8px;border-radius:50%;flex:none}.ovchip[aria-pressed="false"]{color:var(--quiet);text-decoration:line-through;text-decoration-color:var(--line2)}.ovchip[aria-pressed="false"] i{background:none!important;box-shadow:inset 0 0 0 1.5px var(--line2)}.ovchip:hover{color:var(--text)}.ovchip:focus-visible{outline:2px solid var(--sky);outline-offset:2px}</style>';
  const done = (html) => { RMEMO.set(key, { k: mk, html }); if (RMEMO.size > 30) RMEMO.delete(RMEMO.keys().next().value); return html; };
  // Nothing at all in the day is said as what it is: Home Assistant has no
  // record of these yet (not an empty stretch of a zoom).
  const never = lines.length && main.every((x) => !x.pts.length);
  const empty = !lines.length ? 'Every line is hidden.' : never ? `No history for these ${what}s in the last 24 hours: Home Assistant has recorded nothing for them yet.` : 'Nothing recorded for this stretch.';
  if (!vals.length) return done(CSS + ZCSS + header('') + chips + `<p class="sm">${empty}</p>${z ? resetChip(key) : ''}`);
  let lo = Math.min(...vals), hi = Math.max(...vals); const m = (hi - lo) * 0.12 || 1; lo -= m; hi += m;
  const X = (t) => ((t - t0) / (t1 - t0)) * 600;
  const yOf = (v) => 3 + (1 - (v - lo) / (hi - lo)) * (CH - 6);
  const focus = H.focus;
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
  const o = { t0, t1, lines, yOf, focus, unit, digits, bandAt, bandWord, sub, valueColor: colorFor };
  OV.set(key, o); if (OV.size > 30) OV.delete(OV.keys().next().value);
  CHARTS.set(key, { series: lines, t0, t1, unit });
  if (CHARTS.size > 60) CHARTS.delete(CHARTS.keys().next().value);

  const PH = (t) => Math.max(0, Math.min(100, (t - t0) / (t1 - t0) * 100));
  const vis = runs.map((r) => ({ ...r, a: Math.max(r.a, t0), b: Math.min(r.b, t1) })).filter((r) => r.b > r.a);
  const runsRow = vis.length ? `<div class="ovrow" style="margin-top:8px;align-items:center"><div class="ovruns" aria-hidden="true">${vis.map((r) => `<span style="left:${PH(r.a).toFixed(2)}%;width:${Math.max(0.8, PH(r.b) - PH(r.a)).toFixed(2)}%;background:${r.color}"></span>`).join('')}</div><span class="ovside small">${esc(runsLabel)}</span></div>` : '';
  // The axis: round times where they fall, and Now at the end (or the end
  // of the zoomed stretch).
  const ticks = axisTicks(t0, t1).map(([f, l]) => `<span style="left:${(f * 100).toFixed(2)}%;transform:translateX(-50%)">${esc(l)}</span>`);
  ticks.push(`<span style="left:100%;transform:translateX(-100%)">${now - t1 < 60000 ? 'Now' : esc(clock(t1))}</span>`);
  const axis = `<div class="ovrow" aria-hidden="true" style="margin-top:4px"><div class="ovaxis">${ticks.join('')}</div><span class="ovside">${z ? resetChip(key) : ''}</span></div>`;
  const env = extreme.length ? `<div class="ovenv">${extreme.map((x) => `<div class="ovenvi${x.old ? ' stale' : ''}"><span class="nm">${esc(x.short)}</span><b style="color:${x.color}">${isFinite(x.now) ? esc(Number(x.now).toFixed(digits) + unit) : '—'}</b>${x.old ? `<span class="age">${esc(x.old)}</span>` : ''}<svg width="56" height="14" viewBox="0 0 56 14" aria-hidden="true"><polyline points="${sparkPts(x.pts, 56, 14)}" stroke-width="1.25" style="fill:none;stroke:${x.color};opacity:.6"></polyline></svg></div>`).join('')}</div>` : '';
  const notes = series.filter((x) => x.dead).map((x) => `<p class="sm ovnote">${esc(x.short)}: ${esc(x.dead.replace(/^Sensor offline/, 'sensor offline'))}.</p>`).join('')
    + (lines.some((l) => !l.pts.length) ? `<p class="sm ovnote">No history in the last 24 hours for ${esc(lines.filter((l) => !l.pts.length).map((l) => l.short).join(', '))}: Home Assistant has recorded nothing for ${lines.filter((l) => !l.pts.length).length === 1 ? 'it' : 'them'} yet.</p>` : '');
  return done(`${CSS}${ZCSS}${header(sub)}${chips}<div class="ovrow" data-ctl="1" style="margin-top:10px"><div class="chart ovplot" data-chart="${esc(key)}" data-zkey="${esc(key)}" data-ov="1" role="img" aria-label="${esc(hd.name || 'Readings')}, ${z ? 'zoomed' : 'last 24 hours'}, one line per ${what}. Slide along it to read any moment."><svg width="100%" height="${CH}" viewBox="0 0 600 ${CH}" preserveAspectRatio="none" aria-hidden="true" style="overflow:hidden">${band}${polys}</svg><span class="scrub" hidden></span><div class="ovdots" data-ovdots="${esc(key)}"></div></div><div class="ovside ovlabels" data-ovlabels="${esc(key)}">${labelsHtml(o, null)}</div></div>${runsRow}${axis}${notes}${env}`);
}

export function clearCache() { CACHE.clear(); }
