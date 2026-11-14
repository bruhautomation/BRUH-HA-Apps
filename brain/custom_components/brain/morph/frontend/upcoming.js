// Coming up: one fixed reading point, and the next day sliding behind it.
//
// The strip used to be a 12-hour track with every event's name written along
// it, which is a row of labels fighting for room and truncating each other.
// Now nothing on the track has a name. A thin line stands still a little left
// of centre; the timeline moves behind it (drag, swipe, a sideways trackpad,
// the arrow keys), dots swell as they come near the line, and whatever is AT
// the line is read out beside it: when on the left, what on the right. Let go
// mid-swipe and it coasts and settles on the nearest event; leave it alone
// and it drifts back to now.
//
// Every item can be tapped and opens in place under the strip (what it is,
// when, from where, and what to do with it); the machines the dashboard names
// in `coming_up_lanes` get lanes of their own showing when they ran and what
// is running now; in the expanded view the lane names on the left are
// the switches that hide and show lanes (no key row under the strip); colors
// are an Edit-mode tool; and zoom lives on the time axis itself (drag along
// the axis, double-tap it to reset, or the small scale at its end).
//
// This module is pure over Home Assistant's states (the device lanes' past
// runs are read from the recorder here and cached): `collect` finds the
// events, `model` places them, `html` draws the strip for a cursor and
// `paint` moves an already-drawn strip to another cursor without rebuilding
// it — which is what a drag needs, sixty times a second. The panel owns the
// pointer and the state; nothing here touches it.

import { esc, clock, friendly, domainOf } from './util.js';

export const PAST_MIN = 0;           // the strip stops at now: there is no past view
export const AHEAD_MIN = 24 * 60;    // and ahead
export const ZONE_PX = 14;           // an event this close to the line is "here"
const STACK_PX = 5;                  // dots closer than this are one dot with a count
const SWELL_PX = 80;                 // how far from the line a dot starts to grow
export const IDLE_BACK_MS = 60000;   // left alone this long, it glides back to now

// Colours are Morph's own tokens; a dashed ring is a guess (an automation
// that usually runs about now), a solid one something that is scheduled.
// `key` is the word in the filter key under the strip (house change). Sun and
// moon have none: the night bands already say when it is dark, so they only
// appear, unlabelled, on the time axis of the expanded view (house change).
const KINDS = {
  timer: { color: 'var(--amber)', word: 'timer', key: 'Timers' },
  sun: { color: 'var(--peach)', word: '', key: '' },
  calendar: { color: 'var(--sky)', word: '', key: 'Calendar' },
  done: { color: 'var(--sand)', word: '', key: 'Finishing' },
  moon: { color: 'var(--indigo)', word: '', key: '' },
  date: { color: 'var(--teal)', word: '', key: 'Dates' },
  usual: { color: 'var(--violet)', word: 'usually about now', key: 'Routines' },
  past: { color: 'var(--quiet)', word: 'happened', key: '' },
  device: { color: 'var(--muted)', word: '', key: '' },
};

// The machines worth a lane: not lights, but the things whose runs are worth
// seeing at a glance. They come from the dashboard's `coming_up_lanes`
// (setLanes): each lane groups entities, `running` lists the states that
// count as running (or `not_running` the ones that do not), `attribute`
// reads an attribute instead of the state (a thermostat's hvac_action), and
// `word` is what a run is called. An entity that does not exist is skipped.
const LANE_HUES = ['lime', 'violet', 'sky', 'teal', 'sand', 'indigo', 'peach', 'rose', 'amber'];
const BLANK = ['unknown', 'unavailable', ''];
export let DEVICES = [];
let DEV_BY_EID = {};
let lanesKey = '';
const slug = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'lane';
export function setLanes(list) {
  const key = JSON.stringify(list || []);
  if (key === lanesKey) return;
  lanesKey = key;
  DEVICES = (Array.isArray(list) ? list : []).map((l, i) => {
    const ids = [].concat(l.entities || l.entity || []).filter((e) => typeof e === 'string');
    const yes = [].concat(l.running == null ? [] : l.running).map(String);
    const no = [].concat(l.not_running == null ? [] : l.not_running).map(String);
    const attr = typeof l.attribute === 'string' ? l.attribute : '';
    const val = (st) => (attr ? st.attributes && st.attributes[attr] : st.state);
    const on = (st) => {
      if (!st || BLANK.includes(st.state)) return false;
      const v = String(val(st) == null ? '' : val(st));
      if (yes.length) return yes.includes(v);
      if (no.length) return !no.includes(v) && !BLANK.includes(v);
      return ['on', 'open', 'running', 'cleaning'].includes(v);
    };
    const hue = LANE_HUES.includes(l.color) ? l.color : LANE_HUES[i % LANE_HUES.length];
    return { id: slug(l.id || l.label) + '_' + i, label: String(l.label || 'Machines'), color: `var(--${hue})`, ids, on, attr, word: typeof l.word === 'string' ? l.word : '' };
  }).filter((g) => g.ids.length);
  DEV_BY_EID = {}; DEVICES.forEach((g) => g.ids.forEach((e) => { DEV_BY_EID[e] = g; }));
  RUNS.at = 0; RUNS.data = {};
}
const runWord = (g, st) => g.word || (g.attr ? String((st && st.attributes && st.attributes[g.attr]) || 'running').replace(/_/g, ' ') : 'running');

// Past runs, read from the recorder for the last day and kept for five
// minutes; what is running now comes from the live state.
const RUNS = { at: 0, pending: false, data: {}, failed: false };
let onRuns = () => {};
export function setOnRuns(fn) { onRuns = fn || (() => {}); }
function loadRuns(H, now) {
  if (!H || !H.callWS || RUNS.pending || now - RUNS.at < 300000) return;
  const ids = DEVICES.flatMap((g) => g.ids).filter((e) => H.states[e]);
  if (!ids.length) return;
  RUNS.pending = true; RUNS.at = now;
  const start = now - PAST_MIN * 60000;
  H.callWS({ type: 'history/history_during_period', start_time: new Date(start).toISOString(), end_time: new Date(now).toISOString(), entity_ids: ids, minimal_response: false, no_attributes: false, significant_changes_only: false })
    .then((r) => {
      const out = {};
      Object.keys(r || {}).forEach((eid) => {
        const g = DEV_BY_EID[eid]; if (!g) return;
        const rows = (r[eid] || []).map((x) => ({ s: x.s, a: x.a, t: ((x.lu != null ? x.lu : x.lc) || 0) * 1000 })).sort((a, b) => a.t - b.t);
        let attrs = {}; const runs = []; let on = null;
        rows.forEach((x) => {
          if (x.a) attrs = { ...attrs, ...x.a };
          const st = { entity_id: eid, state: x.s, attributes: attrs };
          const isOn = g.on(st);
          if (isOn && on == null) on = { a: Math.max(start, x.t), word: runWord(g, st), clip: x.t < start };
          else if (!isOn && on != null) { runs.push([on.a, x.t, on.word, false, on.clip]); on = null; }
        });
        if (on != null) runs.push([on.a, now, on.word, true, on.clip]);
        // Gaps under two minutes are one run (a pump that blips, a stage change).
        const merged = [];
        runs.forEach((x) => { const l = merged[merged.length - 1]; if (l && x[0] - l[1] < 120000) { l[1] = x[1]; l[3] = x[3]; } else merged.push(x.slice()); });
        merged.forEach((x) => { if (x[0] <= start + 60000) x[4] = true; });
        out[eid] = merged.filter((x) => x[1] - x[0] >= 60000 || x[3]);
      });
      RUNS.data = out; RUNS.failed = false;
    })
    .catch(() => { RUNS.failed = true; })
    .finally(() => { RUNS.pending = false; onRuns(); });
}
const ORDER = ['calendar', 'timer', 'done', 'date', 'sun', 'moon', 'usual'];
// Each calendar gets its own colour, fixed by its entity id (adding a calendar
// never repaints the others), so a person's events read as theirs at a glance
// (house change). The house's own colours are left out so a calendar never
// looks like a timer (amber), finishing (sand), a date (teal) or a routine
// (violet); rose (attention) and lime (the garden) are never used. Anyone can
// repaint a key with `Colors`.
const CAL_COLORS = ['var(--sky)', 'var(--peach)', 'var(--indigo)'];
export const PALETTE = ['sky', 'indigo', 'violet', 'rose', 'peach', 'amber', 'sand', 'lime', 'teal'];
export const LANE_PX = 24;           // the distance between tracks

// The kinds (and calendars, as `cal:<entity>`) somebody has hidden with the
// key, the colours they picked for keys, and whether the strip is expanded
// into tracks: this device only.
const HIDE_KEY = 'morph-upc-hidden';
const EXP_KEY = 'morph-upc-expanded';
const COL_KEY = 'morph-upc-colors';
let hidden = new Set();
let expanded = false;
let picked = {};
let painting = false;
try {
  // Every page load starts condensed, the simplest view (household, Oct 2026).
  hidden = new Set(JSON.parse(localStorage.getItem(HIDE_KEY) || '[]'));
  picked = JSON.parse(localStorage.getItem(COL_KEY) || '{}') || {};
} catch (e) { /* storage off */ }
export function togglePainting() { painting = !painting; }
// `v` is "<key id>|<palette word>", or "reset" for every key back to its own.
export function pickColor(v) {
  if (v === 'reset') picked = {};
  else {
    const i = String(v).lastIndexOf('|'); const id = v.slice(0, i), c = v.slice(i + 1);
    if (!PALETTE.includes(c)) return;
    picked[id] = c;
  }
  try { localStorage.setItem(COL_KEY, JSON.stringify(picked)); } catch (e) { /* storage off */ }
}
const pick = (id, dflt) => (picked[id] ? `var(--${picked[id]})` : dflt);
// A lane (`cal:<entity>`, `home`, `usual`, `dev:<id>`) shown or hidden by
// tapping its name in the expanded view; hidden lanes keep a faint name.
export function toggleKind(k) {
  k = String(k || ''); if (!k) return;
  if (hidden.has(k)) hidden.delete(k); else hidden.add(k);
  try { localStorage.setItem(HIDE_KEY, JSON.stringify([...hidden])); } catch (e) { /* storage off */ }
}
export const isHidden = (k) => hidden.has(k);
// How far the strip is zoomed in, over the panel's own scale: pinch, ctrl +
// wheel (a trackpad pinch), the + and − keys or the zoom chips change it, and
// zoomed in, close events come apart and the time axis labels finer steps
// (house change). This device only.
export const ZOOM_MIN = 0.5, ZOOM_MAX = 24;
// Every page load starts all the way out (household, Oct 2026: "always start
// all the way zoomed out"); a zoom holds only until the page is reloaded.
let zoom = ZOOM_MIN;
export function getZoom() { return zoom; }
export function setZoom(z) {
  zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
  if (Math.abs(zoom - ZOOM_MIN) < 0.02) zoom = ZOOM_MIN;
  return zoom;
}
export function toggleExpanded() {
  expanded = !expanded;
  try { localStorage.setItem(EXP_KEY, expanded ? '1' : '0'); } catch (e) { /* storage off */ }
}

function calColors(H) {
  const ids = Object.keys((H && H.states) || {}).filter((e) => e.startsWith('calendar.'));
  const hash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; };
  const out = {}; ids.forEach((e) => { out[e] = CAL_COLORS[hash(e) % CAL_COLORS.length]; });
  return out;
}
const calWho = (H, eid) => friendly(H, eid).replace(/\s*calendar\s*$/i, '');
// The lane an event belongs to: also what hiding and recoloring are keyed on.
const keyOf = (e) => (e.kind === 'calendar' ? 'cal:' + (e.eid || '') : e.kind === 'device' ? e.lane
  : e.kind === 'usual' ? 'usual' : e.kind === 'sun' || e.kind === 'moon' ? 'sky' : 'home');

function parseLocal(s) {
  if (!s) return NaN;
  // Calendar times are local wall-clock strings ("2026-10-13 07:40:00").
  return Date.parse(String(s).replace(' ', 'T'));
}

function parseDur(s) {
  const m = /^(\d+):(\d{1,2}):(\d{1,2})/.exec(String(s || ''));
  return m ? ((+m[1] * 60 + +m[2]) * 60 + +m[3]) * 1000 : 0;
}

// Everything worth reading out in the next day, as {at, end?, label, kind,
// solid, eid}. Times are epoch milliseconds. `extra` is what the panel adds
// from outside the states: a habit's measured time.
export function collect(H, now, extra) {
  const out = [];
  const lo = now - PAST_MIN * 60000, hi = now + AHEAD_MIN * 60000;
  Object.values((H && H.states) || {}).forEach((s) => {
    const d = domainOf(s.entity_id); const a = s.attributes || {};
    if (d === 'timer' && s.state === 'active' && a.finishes_at) {
      const end = Date.parse(a.finishes_at); const dur = parseDur(a.duration);
      if (end) out.push(dur ? { at: end - dur, end, label: friendly(H, s.entity_id), kind: 'timer', solid: true, eid: s.entity_id }
        : { at: end, label: friendly(H, s.entity_id), kind: 'timer', solid: true, eid: s.entity_id, sub: 'finishes' });
    }
    if (d === 'sun') {
      if (a.next_setting) out.push({ at: Date.parse(a.next_setting), label: 'Sunset', kind: 'sun', solid: true });
      if (a.next_rising) out.push({ at: Date.parse(a.next_rising), label: 'Sunrise', kind: 'sun', solid: true });
    }
    // The moon: any sensor named for the moon's next rising, setting, full or
    // new moon (AstroWeather's today), so a renamed or different source still works.
    const mm = d === 'sensor' && /moon_next_(rising|setting|full_moon|new_moon)$/.exec(s.entity_id);
    if (mm) {
      const at = Date.parse(s.state);
      const nm = { rising: 'Moonrise', setting: 'Moonset', full_moon: 'Full moon', new_moon: 'New moon' }[mm[1]];
      if (at > now && nm) out.push({ at, label: nm, kind: 'moon', solid: true, eid: s.entity_id });
    }
    if (d === 'calendar' && a.start_time) {
      const at = parseLocal(a.start_time); const end = parseLocal(a.end_time);
      const who = friendly(H, s.entity_id).replace(/\s*calendar\s*$/i, '');
      const label = (a.message || friendly(H, s.entity_id)) + (who ? ' · ' + who : '');
      const more = { title: a.message || '', who, loc: a.location || '', desc: a.description || '' };
      if (a.all_day) {
        // An all-day event still on today shows at now, not hidden because its midnight start has passed.
        if (end > now || at > now) out.push({ at: Math.max(at, now), label, kind: 'calendar', solid: true, eid: s.entity_id, sub: at > now ? 'all day' : 'all day today', more });
      }
      else if (at && end && end > at) out.push({ at, end, label, kind: 'calendar', solid: true, eid: s.entity_id, more });
      else if (at) out.push({ at, label, kind: 'calendar', solid: true, eid: s.entity_id, more });
    }
    if (d === 'sensor' && !mm && a.device_class === 'timestamp' && /finish|done|end|complete|next|alarm|due/i.test(s.entity_id)) {
      const at = Date.parse(s.state);
      if (at > now) out.push({ at, label: friendly(H, s.entity_id), kind: /finish|done|end|complete/i.test(s.entity_id) ? 'done' : 'date', solid: true, eid: s.entity_id });
    }
    if (d === 'input_datetime' && a.has_date && a.has_time && a.timestamp) {
      const at = a.timestamp * 1000;
      if (at > now) out.push({ at, label: friendly(H, s.entity_id), kind: 'date', solid: true, eid: s.entity_id });
    }
    if (d === 'automation' && s.state === 'on' && a.last_triggered) {
      // What usually happens: an automation that ran at a clock time in the
      // last day and a half is likely to run at that time again.
      const lt = new Date(a.last_triggered); const ago = now - lt.getTime();
      if (ago > 3600000 && ago < 36 * 3600000) {
        const next = new Date(now); next.setHours(lt.getHours(), lt.getMinutes(), 0, 0);
        if (next.getTime() <= now) next.setDate(next.getDate() + 1);
        out.push({ at: next.getTime(), label: friendly(H, s.entity_id), kind: 'usual', solid: false, eid: s.entity_id });
      }
    }
  });
  // The machines: past runs from the recorder, and what is running now from
  // the live state (so a run that just started shows before the next read).
  loadRuns(H, now);
  DEVICES.forEach((g) => g.ids.forEach((eid) => {
    const st = H && H.states && H.states[eid]; if (!st) return;
    const raw = friendly(H, eid).replace(/\s+(print status|current status|current stage|stage|running|status)$/i, '').trim();
    const nm = g.ids.length === 1 ? g.label : raw.split(/\s+/).filter((w, i, a) => i === 0 || w.toLowerCase() !== a[i - 1].toLowerCase()).join(' ');
    const runs = (RUNS.data[eid] || []).map((x) => x.slice());
    const live = g.on(st);
    const last = runs[runs.length - 1];
    if (live && !(last && last[3])) runs.push([Math.max(Date.parse(st.last_changed) || now, lo), now, runWord(g, st), true]);
    if (!live && last && last[3]) { last[3] = false; last[1] = Math.min(last[1], Date.parse(st.last_changed) || last[1]); }
    runs.forEach(([a, b, word, running, clip]) => out.push({ at: a, end: running ? Math.max(b, now) + 1 : b, label: nm, kind: 'device', lane: 'dev:' + g.id, solid: true, eid, running, word, clip: !!clip, sub: running ? `${word} now` : word }));
  }));
  // Anything a caller adds (`extra`) that is past, or a routine's usual time.
  (extra || []).forEach((e) => { if (e && e.at > 0 && (e.at <= now || e.kind === 'usual')) out.push(e); });
  const seen = new Set();
  return out.filter((e) => {
    if (!(e.at > 0)) return false;
    const last = e.end != null ? e.end : e.at;
    if (last < lo || e.at > hi) return false;
    const key = (e.eid || e.label) + '@' + e.at;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

// Places the events for a scale of `k` pixels a minute. Every time inside is
// in minutes from `base` (now, to the minute, so the drawing only changes
// once a minute rather than on every render).
//
// Events sit on lanes. Condensed (the default) is one track: what is
// scheduled as dots, the usual routines as small faint marks under them, and
// no sun or moon. Expanded gives each calendar its own labelled track, then
// Home (timers, finishing, dates), Routines, and the sun and moon unlabelled
// on the time axis (house change).
export function model(H, now, k, extra) {
  const base = Math.floor(now / 60000) * 60000;
  const min = (ms) => (ms - base) / 60000;
  const all = collect(H, now, extra);
  const cc = calColors(H);
  const devColor = {}; DEVICES.forEach((g) => { devColor['dev:' + g.id] = g.color; });
  const laneColor = (id) => pick(id, id.startsWith('cal:') ? (cc[id.slice(4)] || KINDS.calendar.color) : devColor[id] || (id === 'usual' ? KINDS.usual.color : 'var(--muted)'));
  const colorOf = (e) => (e.kind === 'calendar' || e.kind === 'device' || e.kind === 'usual' ? laneColor(keyOf(e)) : pick(keyOf(e) === 'home' ? e.kind : keyOf(e), KINDS[e.kind].color));
  const calIds = [...new Set(all.filter((e) => e.kind === 'calendar' && e.eid).map((e) => e.eid))].sort();
  const devIds = DEVICES.filter((g) => all.some((e) => e.lane === 'dev:' + g.id)).map((g) => g);
  // Condensed is one track: calendars and the house's own things together,
  // routines as faint marks, and of the machines only what is running now.
  // Expanded gives every calendar, the house, each machine and the routines
  // a lane of its own, named on the left (house change).
  // Expanded keeps only what somebody would read (household, Oct 2026): the
  // sun and moon live on the weather card, routine guesses and automations
  // that already ran were noise between the real things.
  const inView = (e) => (expanded ? !['sun', 'moon', 'usual', 'past'].includes(e.kind) : e.kind !== 'sun' && e.kind !== 'moon' && e.kind !== 'usual' && (e.kind !== 'device' || e.running));
  const evs = all.filter((e) => inView(e) && !hidden.has(keyOf(e)))
    .map((e) => ({ ...e, color: colorOf(e), t: min(e.at), t2: e.end != null ? min(e.end) : null }));
  const laneOf = (e) => (!expanded ? (e.kind === 'usual' ? 'faint' : 'main') : keyOf(e));
  const any = (id) => all.some((e) => keyOf(e) === id && (expanded || inView(e)));
  const defs = expanded
    ? [...calIds.map((eid) => ({ id: 'cal:' + eid, label: calWho(H, eid) })),
      ...(all.some((e) => e.kind === 'calendar' && !e.eid) ? [{ id: 'cal:', label: 'Calendar' }] : []),
      { id: 'home', label: 'House' },
      // A machine gets a lane only if it ran in the last 12 hours or is running
      // now; an empty row is not worth a line (household, Oct 2026).
      ...devIds.filter((g) => all.some((e) => e.lane === 'dev:' + g.id && (e.running || (e.end != null ? e.end : e.at) > now - 12 * 3600e3))).map((g) => ({ id: 'dev:' + g.id, label: g.label }))].filter((d) => any(d.id) && all.some((e) => keyOf(e) === d.id && inView(e))).map((d) => ({ ...d, color: laneColor(d.id), off: hidden.has(d.id) }))
    : [{ id: 'main', label: '', color: 'var(--muted)' }];
  const has = (id) => evs.some((e) => laneOf(e) === id);
  const lanes = (expanded ? defs : defs.filter((d) => has(d.id) || has('faint'))).map((d) => ({ ...d, small: false }));
  if (!lanes.length) lanes.push({ id: expanded ? 'none' : 'main', label: '', small: false });
  lanes.forEach((l, i) => { l.y = i * LANE_PX; });
  if (expanded && has('sky')) lanes.push({ id: 'sky', label: '', small: true, y: lanes.length * LANE_PX });
  if (has('faint')) { const h = lanes.find((l) => l.id === 'main'); lanes.unshift({ id: 'faint', label: '', small: true, y: h ? h.y : 0 }); }
  lanes.forEach((l) => {
    const mine = l.off ? [] : evs.filter((e) => laneOf(e) === l.id);
    l.stacks = [];
    mine.filter((e) => e.t2 == null).sort((a, b) => a.t - b.t).forEach((e) => {
      const st = l.stacks[l.stacks.length - 1];
      if (st && (e.t - st.t) * k < STACK_PX) st.items.push(e); else l.stacks.push({ t: e.t, items: [e] });
    });
    const rows = [];
    l.durs = mine.filter((e) => e.t2 != null).sort((a, b) => a.t - b.t).map((e) => {
      let row = 0; while (rows[row] != null && rows[row] > e.t - 2 / k) row++;
      rows[row] = e.t2;
      return { ...e, row: Math.min(row, 1) };
    });
  });
  const stacks = lanes.flatMap((l) => l.stacks); const durs = lanes.flatMap((l) => l.durs);
  const targets = [...new Set([0, ...stacks.map((st) => st.t), ...durs.filter((d) => d.t > -PAST_MIN).map((d) => d.t)])]
    .filter((t) => t >= -PAST_MIN && t <= AHEAD_MIN).sort((a, b) => a - b);
  const rowsN = Math.max(0, lanes.filter((l) => l.id !== 'faint').length - 1);
  // What can be recolored (Edit mode): every lane there is, condensed or not.
  const keys = [...calIds.map((eid) => ({ id: 'cal:' + eid, label: calWho(H, eid) })),
    ...devIds.map((g) => ({ id: 'dev:' + g.id, label: g.label })), { id: 'usual', label: 'Routines' }]
    .filter((d) => all.some((e) => keyOf(e) === d.id)).map((d) => ({ ...d, color: laneColor(d.id) }));
  return { base, k, lanes, rows: rowsN, expanded, stacks, durs, targets, keys, kinds: keys.map((x) => x.id), nights: nights(H, base, min), ticks: ticks(base, min, k), minC: -PAST_MIN, maxC: AHEAD_MIN };
}

// Night, from the sun's own next rising and setting, as faint bands behind
// the track so "overnight" reads without a label.
function nights(H, base, min) {
  const sun = H && H.states && H.states['sun.sun'];
  if (!sun) return [];
  const rise = Date.parse(sun.attributes.next_rising), set = Date.parse(sun.attributes.next_setting);
  if (!rise || !set) return [];
  const day = 86400000; const out = [];
  // Every night from two days back to tomorrow: each sunset (the next one,
  // stepped a day at a time) to the first sunrise after it. A night in
  // progress starts at the last sunset, not at an arbitrary point.
  for (let i = -2; i <= 1; i++) {
    const s = set + i * day; let r = rise;
    while (r <= s) r += day;
    while (r - day > s) r -= day;
    out.push([s, r]);
  }
  return out.map(([a, b]) => [min(a), min(b)]).filter(([a, b]) => b > -PAST_MIN - 60 && a < AHEAD_MIN + 60);
}

// Labels every 3 hours at the panel's own scale; zoomed in, every hour, half
// hour, quarter hour or five minutes, whichever leaves room between labels.
function ticks(base, min, k) {
  const out = [];
  const lab = [5, 15, 30, 60, 180].find((s) => s * k >= 90) || 180;
  const tk = lab >= 60 ? 60 : lab === 5 ? 5 : lab / 3 >= 5 ? lab / 3 : 5;
  const first = new Date(base - PAST_MIN * 60000); first.setMinutes(0, 0, 0);
  for (let d = new Date(first); d.getTime() <= base + (AHEAD_MIN + 120) * 60000; d.setMinutes(d.getMinutes() + tk)) {
    const h = d.getHours(), mn = d.getMinutes(); const mid = h === 0 && mn === 0;
    const all = h * 60 + mn; const on = all % lab === 0;
    out.push({ t: min(d.getTime()), major: mid || on, mid,
      label: mid ? d.toLocaleDateString([], { weekday: 'short' }) : on ? (mn ? clock(d) : d.toLocaleTimeString([], { hour: 'numeric' })) : '' });
  }
  return out;
}

// The lane at `y` pixels below the first lane's line, or null.
export function laneAt(m, y) {
  let best = null, bd = 13;
  (m.lanes || []).forEach((l) => { if (l.id === 'faint') return; const d = Math.abs(l.y - y); if (d < bd) { bd = d; best = l; } });
  return best;
}
// Where a tap on lane `l` at time `t` should go: inside a bar, right there;
// otherwise the nearest thing on that lane within `tol` minutes.
export function laneSnap(l, t, tol) {
  if (!l) return null;
  const inBar = (l.durs || []).find((d) => t >= d.t - 0.5 && t <= d.t2 + 0.5);
  if (inBar) return t;
  let best = null, bd = Infinity;
  (l.stacks || []).forEach((st) => { const d = Math.abs(st.t - t); if (d < bd) { bd = d; best = st.t; } });
  (l.durs || []).forEach((du) => { [du.t, du.t2].forEach((x) => { const d = Math.abs(x - t); if (d < bd) { bd = d; best = du.t; } }); });
  return bd <= tol ? best : null;
}

export function clampC(m, c) { return Math.max(0, m.minC, Math.min(m.maxC, c)); }

// The nearest place worth stopping within `tolMin` minutes, or null.
export function snap(m, c, tolMin) {
  let best = null, bd = Infinity;
  m.targets.forEach((t) => { const d = Math.abs(t - c); if (d < bd) { bd = d; best = t; } });
  return bd <= tolMin ? best : null;
}

export function step(m, c, dir) {
  if (dir > 0) return m.targets.find((t) => t > c + 0.5);
  const before = m.targets.filter((t) => t < c - 0.5);
  return before.length ? before[before.length - 1] : undefined;
}

function dur(mins) {
  // Minutes stop mattering a few hours out: "in 10 h", not "in 10 h 4 min".
  const m = Math.round(Math.abs(mins)); const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} h${r && h < 3 ? ` ${r} min` : ''}` : `${r} min`;
}

function rel(mins) {
  if (Math.abs(mins) < 1) return 'now';
  return mins > 0 ? 'in ' + dur(mins) : dur(mins) + ' ago';
}

// {day, time}: the day only when it is not today, so a wide strip can say
// "Tomorrow 8:00 AM" and a phone can put the day on the line under it.
function when(m, mins) {
  const at = new Date(m.base + mins * 60000);
  const today = new Date(m.base); today.setHours(0, 0, 0, 0);
  const days = Math.floor((at - today) / 86400000);
  return { day: days === 0 ? '' : days === 1 ? 'Tomorrow' : at.toLocaleDateString([], { weekday: 'short' }), time: clock(at) };
}
const NOW = { day: '', time: 'Now' };

// What the reading point is over at cursor `c`, across every lane: the
// nearest stack, and anything on another lane at the same moment.
export function reading(m, c) {
  const near = m.lanes.flatMap((l) => l.stacks.map((s) => ({ s, small: l.small })))
    .filter(({ s }) => Math.abs(s.t - c) * m.k <= ZONE_PX)
    .sort((a, b) => (Math.abs(a.s.t - c) - Math.abs(b.s.t - c)) || (a.small - b.small));
  if (near.length) {
    const t0 = near[0].s.t;
    const items = near.filter(({ s }) => Math.abs(s.t - t0) * m.k < STACK_PX).flatMap(({ s }) => s.items);
    const f = items[0]; const n = items.length;
    return { hit: true, t: t0, items, when: when(m, t0), rel: rel(t0), color: f.color, solid: f.solid,
      name: n > 1 ? items.map((i) => i.label).join(' · ') : f.label, eid: n > 1 ? '' : f.eid || '',
      extra: n > 1 ? `${n} at once` : [f.sub, KINDS[f.kind].word].filter(Boolean).join(' · ') };
  }
  const over = m.durs.filter((d) => c >= d.t - 1 && c <= d.t2 + 1);
  if (over.length) {
    const d = over[0];
    if (d.kind === 'device') {
      const live = d.running && c >= -1;
      return { hit: true, t: d.t, items: over, when: live ? NOW : when(m, d.t), rel: live ? `since ${clock(m.base + d.t * 60000)}` : rel(d.t),
        color: d.color, solid: true, name: over.map((x) => x.label).join(' · '), eid: over.length > 1 ? '' : d.eid || '',
        extra: live ? `${d.word} · ${dur(-d.t)} so far` : `${d.word} ${dur(d.t2 - d.t)} · until ${clock(m.base + d.t2 * 60000)}` };
    }
    const running = d.t <= 0 && c <= 0.5;
    return { hit: true, t: d.t, items: over, when: running ? NOW : when(m, d.t), rel: running ? 'until ' + clock(m.base + d.t2 * 60000) : rel(d.t),
      color: d.color, solid: true, name: over.map((x) => x.label).join(' · '), eid: over.length > 1 ? '' : d.eid || '',
      extra: running ? `${dur(d.t2)} left` : `until ${clock(m.base + d.t2 * 60000)} · ${dur(d.t2 - d.t)}` };
  }
  const nx = m.targets.find((t) => t > c + 0.5);
  const nxs = nx == null ? null : m.stacks.find((s) => s.t === nx) || m.durs.find((d) => d.t === nx);
  const nxName = nxs ? (nxs.items ? nxs.items[0].label : nxs.label) : '';
  const atNow = Math.abs(c) < 1;
  const nh = (m.kinds || []).filter((k) => hidden.has(k)).length;
  return { hit: false, items: [], when: atNow ? NOW : when(m, c), rel: atNow ? clock(m.base) : rel(c), color: '', solid: true,
    name: atNow ? 'Nothing right now' : 'Nothing here', eid: '',
    extra: nxs ? `next: ${nxName}, ${rel(nx - c)}` : nh ? `${nh} ${nh === 1 ? 'kind' : 'kinds'} hidden` : 'nothing else in the next day' };
}

// Expanded, a tap selects the very bar or dot under the finger (household,
// Oct 2026): m.sel = { lane, t, label } (label null for a stack of dots).
const isSel = (m, laneId, t, label) => !!(m.sel && m.sel.lane === laneId && Math.abs(m.sel.t - t) < 0.01 && (m.sel.label == null || m.sel.label === label));
function selItems(m) {
  if (!m.sel) return [];
  const l = m.lanes.find((x) => x.id === m.sel.lane); if (!l) return [];
  const d = l.durs.find((x) => isSel(m, l.id, x.t, x.label)); if (d) return [d];
  const st = l.stacks.find((x) => Math.abs(x.t - m.sel.t) < 0.01); return st ? st.items : [];
}
// What the expanded strip's header says: the selected thing, or just now.
export function selReading(m) {
  const items = selItems(m);
  if (!items.length) return { hit: false, items: [], when: NOW, rel: clock(m.base), color: '', solid: true, name: '', eid: '', extra: '' };
  const f = items[0]; const live = f.running && f.t2 != null;
  return { hit: true, t: f.t, items, when: live ? NOW : when(m, f.t), rel: live ? `since ${clock(m.base + f.t * 60000)}` : rel(f.t), color: f.color, solid: f.solid !== false,
    name: items.map((i) => (i.kind === 'calendar' && i.more && i.more.title) || i.label).join(' · '), eid: items.length > 1 ? '' : f.eid || '',
    extra: f.t2 != null ? (live ? `${f.word || 'running'} · ${dur(-f.t)} so far` : `${clock(m.base + f.t * 60000)} – ${clock(m.base + f.t2 * 60000)} · ${dur(f.t2 - f.t)}`) : [f.sub, KINDS[f.kind] && KINDS[f.kind].word].filter(Boolean).join(' · ') };
}
// Where on the expanded strip a tap landed: the lane by its name's row, the
// time by the track itself; the nearest bar or dot in that lane, if close.
export function pickAt(m, laneId, t) {
  const l = m.lanes.find((x) => x.id === laneId); if (!l || l.off) return null;
  const tol = 10 / m.k;
  const d = l.durs.filter((x) => t >= x.t - tol && t <= x.t2 + tol).sort((a, b) => (a.t2 - a.t) - (b.t2 - b.t))[0];
  if (d) return { lane: l.id, t: d.t, label: d.label };
  const st = l.stacks.map((x) => ({ x, d: Math.abs(x.t - t) * m.k })).filter((o) => o.d <= 22).sort((a, b) => a.d - b.d)[0];
  return st ? { lane: l.id, t: st.x.t, label: null } : null;
}

function swell(m, t, c, small) {
  if (small || m.expanded) return '1';
  const near = Math.max(0, 1 - (Math.abs(t - c) * m.k) / SWELL_PX);
  return (1 + 0.75 * near).toFixed(3);
}

function readoutHtml(r) {
  const dot = r.color ? `<span class="cu-dot" style="border:2px ${r.solid ? 'solid' : 'dashed'} ${r.color}"></span>` : '';
  // Whatever is at the line opens in place when its name is tapped (house change).
  const name = r.hit ? `<button type="button" class="cu-name go" data-act="upc-open" aria-expanded="${!!r.open}">${esc(r.name)}</button>` : `<span class="cu-name quiet">${esc(r.name)}</span>`;
  const day = r.when.day;
  return {
    when: `<b>${day ? `<span class="cu-day">${esc(day)} </span>` : ''}${esc(r.when.time)}</b><span>${day ? `<span class="cu-day2">${esc(day.toLowerCase() === 'tomorrow' ? 'tomorrow' : day)} · </span>` : ''}${esc(r.rel)}</span>`,
    what: `<span class="cu-l1">${dot}${name}</span>${r.extra ? `<span class="cu-l2">${esc(r.extra)}</span>` : ''}`,
  };
}

function spoken(r) { return [r.when.day, r.when.time].filter(Boolean).join(' ') + ', ' + r.name; }

// The whole strip, at cursor `c`.
export function html(m, c) {
  const k = m.k; const x = (t) => (t * k).toFixed(1);
  const r = m.expanded ? selReading(m) : reading(m, c); r.open = !!m.open && r.hit; const ro = readoutHtml(r);
  const nightBands = m.nights.map(([a, b]) => `<i class="cu-night" style="left:${x(a)}px;width:${((b - a) * k).toFixed(1)}px"></i>`).join('');
  const tickMarks = m.ticks.map((t) => `<i class="cu-tick${t.major ? ' major' : ''}" style="left:${x(t.t)}px"></i>${t.label ? `<span class="cu-tl${t.mid ? ' cu-mid' : ''}" style="left:${x(t.t)}px">${esc(t.label)}</span>` : ''}`).join('');
  const lines = m.lanes.filter((l) => l.id !== 'faint').map((l) => `<i class="cu-line" style="top:${l.y - 1}px;left:${x(m.minC - 180)}px;width:${((m.maxC - m.minC + 360) * k).toFixed(1)}px"></i>`).join('');
  const bars = m.lanes.map((l) => l.durs.map((d) => {
    const done = d.t < 0 ? Math.min(d.t2, 0) - d.t : 0;
    return `<i class="cu-bar${!m.expanded && c >= d.t && c <= d.t2 ? ' on' : ''}${isSel(m, l.id, d.t, d.label) ? ' sel' : ''}${d.t2 < 0 ? ' past' : ''}" data-cu-bar="${d.t},${d.t2}" style="left:${x(d.t)}px;width:${Math.max(6, (d.t2 - d.t) * k).toFixed(1)}px;top:${l.y + (d.row ? 5 : -3)}px;--c:${d.color}"><i style="width:${(done * k).toFixed(1)}px"></i></i>`;
  }).join('')).join('');
  const dots = m.lanes.map((l, li) => l.stacks.map((s, i) => {
    const f = s.items[0];
    return `<span class="cu-pin${l.small ? ' small' : ''}${s.t < -1 ? ' past' : ''}${isSel(m, l.id, s.t, null) ? ' sel' : ''}" style="left:${x(s.t)}px;top:${l.y - 11}px"><span class="cu-dot" data-cu-dot="${li}:${i}" style="${l.small ? `background:${f.color}` : `border:2px ${f.solid ? 'solid' : 'dashed'} ${f.color}`};transform:scale(${swell(m, s.t, c, l.small)})"></span>${s.items.length > 1 && !l.small ? `<span class="cu-n">${s.items.length}</span>` : ''}</span>`;
  }).join('')).join('');
  // Expanded, each lane's name is its switch: tap to hide or show the lane;
  // a hidden lane keeps its name, faint (house change).
  const laneNames = m.lanes.some((l) => l.label && !l.small) ? `<div class="cu-lanes" role="group" aria-label="Lanes on Coming up">${m.lanes.filter((l) => l.label && !l.small).map((l) => `<button type="button" class="cu-ln${l.off ? ' off' : ''}" data-act="upc-kind" data-v="${esc(l.id)}" aria-pressed="${!l.off}" style="top:calc(var(--ty) + ${l.y}px);--c:${l.color}">${esc(l.label)}</button>`).join('')}</div>` : '';
  const atNow = Math.abs(c) < 1;
  const out = zoom <= ZOOM_MIN;
  wire();
  // The key (and the zoom slider) is not chrome on the page: it shows while
  // the strip is in use, when it is expanded, or when it is hiding something
  // (so what is hidden can always be shown again).
  const keysOn = m.expanded || m.edit || Date.now() < engagedUntil || (m.kinds || []).some((k) => hidden.has(k));
  return `${KEY_CSS}<div class="cu${m.expanded ? ' exp' : ''}${keysOn ? ' cu-on' : ''}" data-upc style="--rows:${m.rows}">
<div class="cu-vp" data-upc-vp tabindex="0" role="slider" aria-label="Coming up. Drag, swipe or use the arrow keys to look ahead; pinch, or plus and minus, to zoom." aria-valuemin="${m.minC}" aria-valuemax="${m.maxC}" aria-valuenow="${Math.round(c)}" aria-valuetext="${esc(spoken(r))}">
<span class="cu-lens${r.hit ? ' hit' : ''}" data-cu-lens style="--c:${r.color || 'var(--line2)'}"></span>
<div class="cu-track" data-cu-track style="transform:translateX(${(-c * k).toFixed(1)}px)">${nightBands}${lines}${tickMarks}<i class="cu-nowm"></i>${bars}${dots}</div>
<i class="cu-ph" aria-hidden="true"></i><i class="cu-ph low" aria-hidden="true"></i>
<i class="cu-axis" aria-hidden="true"></i>
<div class="cu-when" data-cu-when aria-hidden="true">${ro.when}</div>
<div class="cu-what" data-cu-what aria-live="polite">${ro.what}</div>
</div>
${laneNames}
<button type="button" class="cu-zb${out ? '' : ' on'}${(m.keys || []).length ? '' : ' solo'}" data-act="upc-zoom" data-v="${out ? 'in' : 'reset'}" aria-label="${out ? 'Zoom in on Coming up' : `Zoomed ${esc(zoomText())}, all the way out again`}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>${out ? '' : `<span>${esc(zoomText())}</span>`}</button>
<button type="button" class="cu-back go" data-act="upc-now"${atNow ? ' hidden' : ''}>Now</button>
${(m.keys || []).length ? `<button type="button" class="cu-fold" data-act="upc-exp" aria-expanded="${m.expanded}" aria-label="${m.expanded ? 'Condense to one track' : 'Expand into one track per calendar'}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${m.expanded ? 'M7 4l5 5 5-5M7 20l5-5 5 5' : 'M7 9l5-5 5 5M7 15l5 5 5-5'}"/></svg></button>` : ''}
${editHtml(m)}
</div>${detailHtml(m, r, c)}`;
}

// What is at the line, opened in place under the strip (house change): what
// it is, when, from where, and what can be done with it.
function detailHtml(m, r, c) {
  if (!m.open) return '';
  if (m.expanded) { r = selReading(m); if (!r.hit) return ''; }
  else if (m.focusLane) {
    const l = m.lanes.find((x) => x.id === m.focusLane);
    let mine = (r.items || []).filter((e) => keyOf(e) === m.focusLane);
    if (!mine.length && l) mine = [...l.durs.filter((d) => c >= d.t - 1 && c <= d.t2 + 1), ...l.stacks.filter((st) => Math.abs(st.t - c) * m.k <= ZONE_PX).flatMap((st) => st.items)];
    if (mine.length) r = { ...r, hit: true, items: mine, name: mine.map((e) => e.label).join(' · ') };
  }
  if (!r.hit || !(r.items || []).length) return '';
  const at = (t) => { const w = when(m, t); return (w.day ? w.day + ' ' : '') + w.time; };
  const rows = r.items.slice(0, 6).map((e) => {
    const mo = e.more || {};
    const g = e.kind === 'device' ? DEVICES.find((x) => 'dev:' + x.id === e.lane) : null;
    const src = e.kind === 'calendar' ? (mo.who ? `${mo.who} · calendar` : 'Calendar') : g ? g.label : e.kind === 'timer' ? 'Timer' : e.kind === 'done' ? 'Finishing' : e.kind === 'date' ? 'Date' : e.kind === 'usual' ? 'Usually about now' : e.kind === 'past' ? 'Happened' : e.kind === 'sun' || e.kind === 'moon' ? 'Sky' : '';
    const title = e.kind === 'calendar' && mo.title ? mo.title : e.label;
    const t2 = e.t2 != null ? e.t2 : null;
    const span = t2 != null ? (e.clip ? (e.running ? 'all day so far' : `until ${at(t2)}`) : e.running ? `${at(e.t)} – now · ${dur(-e.t)} so far` : `${at(e.t)} – ${clock(m.base + t2 * 60000)} · ${dur(t2 - e.t)}`) : at(e.t);
    const relw = e.running ? (e.word || 'running') + ' now' : t2 != null && e.t < 0 && t2 > 0 ? 'on now' : e.clip ? rel(t2) : rel(e.t);
    const acts = e.eid ? `<span class="cu-acts">${m.onDash && m.onDash(e.eid) ? `<button type="button" class="cu-act" data-act="upc" data-v="${esc(e.eid)}">Show on the page</button>` : ''}<button type="button" class="cu-act" data-act="more-info" data-v="${esc(e.eid)}">Details</button></span>` : '';
    return `<div class="cu-it" style="--c:${e.color}"><span class="cu-idot${e.solid === false ? ' dash' : ''}"></span><div class="cu-ib"><b>${esc(title)}</b><span class="cu-iw">${esc(span)} · ${esc(relw)}</span>${src && src !== title ? `<span class="cu-is">${esc(src)}${e.sub && !e.running && e.kind !== 'device' ? ' · ' + esc(e.sub) : ''}</span>` : ''}${mo.loc ? `<span class="cu-is">${esc(mo.loc)}</span>` : ''}${mo.desc ? `<p class="cu-id">${esc(String(mo.desc).slice(0, 280))}</p>` : ''}${acts}</div></div>`;
  }).join('');
  return `<div class="cu-detail" data-cu-detail role="region" aria-label="${esc(r.name)}">${rows}${r.items.length > 6 ? `<span class="cu-is">and ${r.items.length - 6} more at the same moment</span>` : ''}</div>`;
}

// Recoloring the lanes is an Edit-mode tool (household rule): a quiet
// "Colors" word in Edit, opening a row of swatches per lane in place.
function editHtml(m) {
  const ks = m.keys || [];
  if (!m.edit || !ks.length) return '';
  const pal = painting ? `<div class="cu-pal" role="group" aria-label="Colors on Coming up">${ks.map((kk) => `<span class="cu-pg"><span class="cu-pn">${esc(kk.label)}</span>${PALETTE.map((p) => {
    const on = kk.color === `var(--${p})`;
    return `<button type="button" class="cu-sw${on ? ' on' : ''}" data-act="upc-color" data-v="${esc(kk.id + '|' + p)}" aria-pressed="${on}" aria-label="${esc(kk.label)} ${p}" style="--c:var(--${p})"></button>`;
  }).join('')}</span>`).join('')}${Object.keys(picked).length ? '<button type="button" class="cu-key" data-act="upc-color" data-v="reset">Reset</button>' : ''}</div>` : '';
  return `<div class="cu-keys"><button type="button" class="cu-key" data-act="upc-paint" aria-expanded="${painting}">Colors</button></div>${pal}`;
}

const KEY_CSS = `<style>
.cu-what{right:76px}
.cu-fold{position:absolute;top:2px;right:0;width:32px;height:32px;display:flex;align-items:center;justify-content:center;padding:0;border:0;border-radius:8px;background:none;color:var(--quiet);cursor:pointer;transition:color .2s var(--ease)}.cu-fold:hover{color:var(--text)}.cu-fold:focus-visible{outline:2px solid var(--sky);outline-offset:0}
.cu .cu-lanes{pointer-events:none;z-index:2}
.cu .cu-ln{pointer-events:auto;background:linear-gradient(90deg,var(--bg) 70%,transparent);border:0;margin:0;font:inherit;font-size:11px;font-weight:600;cursor:pointer;-webkit-tap-highlight-color:transparent;transition:color .25s ease,opacity .25s ease}
.cu .cu-ln::before{content:"";position:absolute;inset:-6px -2px}
.cu .cu-ln.off{color:var(--quiet)!important;opacity:.55;text-decoration:line-through;text-decoration-color:var(--line2)}
.cu .cu-ln:focus-visible{outline:2px solid var(--sky);outline-offset:2px;border-radius:6px}
.cu-axis{position:absolute;left:0;right:0;bottom:0;height:22px;cursor:ew-resize}
.cu-zb{position:absolute;right:36px;top:7px;z-index:3;display:inline-flex;align-items:center;gap:4px;height:22px;padding:0 6px;border:0;border-radius:11px;background:none;color:var(--quiet);font:600 11px/1 'Manrope',sans-serif;font-variant-numeric:tabular-nums;cursor:pointer;transition:color .2s ease,background-color .2s ease}
.cu-zb:hover{color:var(--text)}.cu-zb.on{color:var(--text);background:color-mix(in oklab,var(--text) 8%,transparent)}
.cu-zb::before{content:"";position:absolute;inset:-5px -4px}.cu-zb.solo{right:0}
.cu-back{right:44px!important}
.cu-detail{display:flex;flex-direction:column;gap:10px;margin:6px 0 4px;padding:12px 14px;border-radius:14px;background:color-mix(in oklab,var(--surface) 70%,transparent);box-shadow:inset 0 0 0 1px var(--line);animation:cuopen .32s cubic-bezier(.22,1,.36,1)}
@keyframes cuopen{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.cu-it{display:flex;gap:12px;align-items:flex-start}
.cu-idot{flex:none;width:10px;height:10px;margin-top:5px;border-radius:50%;background:var(--c)}.cu-idot.dash{background:none;border:2px dashed var(--c)}
.cu-ib{display:flex;flex-direction:column;gap:2px;min-width:0}
.cu-ib b{font-size:15px;font-weight:600;color:var(--text)}
.cu-iw{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.cu-is{font-size:12.5px;color:var(--quiet)}
.cu-id{margin:4px 0 0;font-size:13px;line-height:1.45;color:var(--muted);white-space:pre-wrap}
.cu-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.cu-act{min-height:32px;padding:0 12px;border:0;border-radius:9px;background:color-mix(in oklab,var(--text) 7%,transparent);color:var(--text);font:600 12.5px 'Manrope',sans-serif;cursor:pointer}
.cu-keys{display:flex;gap:14px;margin-top:2px}
.cu-key{display:inline-flex;align-items:center;gap:6px;background:none;border:0;padding:6px 0;margin:0;font:inherit;font-size:12px;font-weight:600;color:var(--muted);cursor:pointer;position:relative;min-height:32px}
.cu-sw{position:relative}.cu-sw::after{content:"";position:absolute;inset:-11px -2px}
@media (prefers-reduced-motion:reduce){.cu-detail{animation:none}}
</style>`;
// The strip counts as in use for a while after any touch, click or key on it.
const ENGAGE_MS = 12000;
let engagedUntil = 0, engageT = 0, wired = false;
function wire() {
  if (wired || typeof document === 'undefined') return;
  wired = true;
  const on = (e) => {
    const path = e.composedPath ? e.composedPath() : [];
    const cu = path.find((n) => n && n.nodeType === 1 && n.matches('[data-upc]'));
    if (!cu) return;
    engagedUntil = Date.now() + ENGAGE_MS;
    cu.classList.add('cu-on');
    clearTimeout(engageT);
    engageT = setTimeout(() => { if (Date.now() >= engagedUntil && !cu.classList.contains('exp') && !cu.querySelector('.cu-key[aria-pressed="false"]')) cu.classList.remove('cu-on'); }, ENGAGE_MS + 50);
  };
  ['pointerdown', 'keydown', 'focusin'].forEach((ev) => document.addEventListener(ev, on, true));
}

// The zoom slider runs on a log scale, so each stretch of it zooms by the
// same factor.
const ZSPAN = Math.log(ZOOM_MAX / ZOOM_MIN);
function toSlider(z) { return Math.round(Math.log(z / ZOOM_MIN) / ZSPAN * 1000); }
export function fromSlider(v) { return ZOOM_MIN * Math.exp(Math.max(0, Math.min(1000, v)) / 1000 * ZSPAN); }
function zoomText() { const r = zoom / ZOOM_MIN; return `${r < 10 ? r.toFixed(1).replace(/\.0$/, '') : Math.round(r)}×`;
}

// Moves a strip `html` drew to cursor `c` without rebuilding it.
export function paint(root, m, c) {
  if (!root) return;
  const q = (s) => root.querySelector(s);
  const track = q('[data-cu-track]'); if (!track) return;
  track.style.transform = `translateX(${(-c * m.k).toFixed(1)}px)`;
  root.querySelectorAll('[data-cu-dot]').forEach((el) => {
    const [li, si] = el.dataset.cuDot.split(':').map(Number); const l = m.lanes[li];
    const s = l && l.stacks[si]; if (s) el.style.transform = `scale(${swell(m, s.t, c, l.small)})`;
  });
  root.querySelectorAll('[data-cu-bar]').forEach((el) => {
    const [a, b] = el.dataset.cuBar.split(',').map(Number); el.classList.toggle('on', c >= a && c <= b);
  });
  // Expanded, the header names what was tapped; scrubbing does not change it.
  if (m.expanded) { const vp0 = q('[data-upc-vp]'); if (vp0) vp0.setAttribute('aria-valuenow', String(Math.round(c))); const back0 = q('.cu-back'); if (back0) back0.hidden = Math.abs(c) < 1; return; }
  const r = reading(m, c); const ro = readoutHtml(r);
  const lens = q('[data-cu-lens]'); if (lens) { lens.classList.toggle('hit', r.hit); lens.style.setProperty('--c', r.color || 'var(--line2)'); }
  const w = q('[data-cu-when]'); if (w && w.innerHTML !== ro.when) w.innerHTML = ro.when;
  const wt = q('[data-cu-what]'); if (wt && wt.innerHTML !== ro.what) wt.innerHTML = ro.what;
  const vp = q('[data-upc-vp]'); if (vp) { vp.setAttribute('aria-valuenow', String(Math.round(c))); vp.setAttribute('aria-valuetext', spoken(r)); }
  const atNow = Math.abs(c) < 1;
  const back = q('.cu-back'); if (back) back.hidden = atNow;
  const hint = q('.cu-hint'); if (hint) hint.hidden = !atNow;
}
