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
// This module is pure over Home Assistant's states: `collect` finds the
// events, `model` places them, `html` draws the strip for a cursor and
// `paint` moves an already-drawn strip to another cursor without rebuilding
// it — which is what a drag needs, sixty times a second. The panel owns the
// pointer and the state; nothing here touches it.

import { esc, clock, friendly, domainOf } from './util.js';

export const PAST_MIN = 60;          // how far behind now you can look
export const AHEAD_MIN = 24 * 60;    // and ahead
export const ZONE_PX = 14;           // an event this close to the line is "here"
const STACK_PX = 5;                  // dots closer than this are one dot with a count
const SWELL_PX = 80;                 // how far from the line a dot starts to grow
export const IDLE_BACK_MS = 60000;   // left alone this long, it glides back to now

// Colours are Morph's own tokens; a dashed ring is a guess (an automation
// that usually runs about now), a solid one something that is scheduled.
const KINDS = {
  timer: { color: 'var(--amber)', word: 'timer' },
  sun: { color: 'var(--peach)', word: '' },
  calendar: { color: 'var(--sky)', word: 'calendar' },
  done: { color: 'var(--lime)', word: '' },
  date: { color: 'var(--teal)', word: '' },
  usual: { color: 'var(--violet)', word: 'usually about now' },
};

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
// solid, eid}. Times are epoch milliseconds.
export function collect(H, now) {
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
    if (d === 'calendar' && a.start_time) {
      const at = parseLocal(a.start_time); const end = parseLocal(a.end_time);
      const label = a.message || friendly(H, s.entity_id);
      if (a.all_day) { if (at > now) out.push({ at, label, kind: 'calendar', solid: true, eid: s.entity_id, sub: 'all day' }); }
      else if (at && end && end > at) out.push({ at, end, label, kind: 'calendar', solid: true, eid: s.entity_id });
      else if (at) out.push({ at, label, kind: 'calendar', solid: true, eid: s.entity_id });
    }
    if (d === 'sensor' && a.device_class === 'timestamp' && /finish|done|end|complete|next|alarm|due/i.test(s.entity_id)) {
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
export function model(H, now, k) {
  const base = Math.floor(now / 60000) * 60000;
  const min = (ms) => (ms - base) / 60000;
  const evs = collect(H, now).map((e) => ({ ...e, t: min(e.at), t2: e.end != null ? min(e.end) : null }));
  const points = evs.filter((e) => e.t2 == null).sort((a, b) => a.t - b.t);
  const stacks = [];
  points.forEach((e) => {
    const s = stacks[stacks.length - 1];
    if (s && (e.t - s.t) * k < STACK_PX) s.items.push(e); else stacks.push({ t: e.t, items: [e] });
  });
  const rows = [];
  const durs = evs.filter((e) => e.t2 != null).sort((a, b) => a.t - b.t).map((e) => {
    let row = 0; while (rows[row] != null && rows[row] > e.t - 2 / k) row++;
    rows[row] = e.t2;
    return { ...e, row: Math.min(row, 1) };
  });
  const targets = [...new Set([0, ...stacks.map((s) => s.t), ...durs.filter((d) => d.t > 0).map((d) => d.t)])]
    .filter((t) => t >= -PAST_MIN && t <= AHEAD_MIN).sort((a, b) => a - b);
  return { base, k, stacks, durs, targets, nights: nights(H, base, min), ticks: ticks(base, min), minC: -PAST_MIN, maxC: AHEAD_MIN };
}

// Night, from the sun's own next rising and setting, as faint bands behind
// the track so "overnight" reads without a label.
function nights(H, base, min) {
  const sun = H && H.states && H.states['sun.sun'];
  if (!sun) return [];
  const rise = Date.parse(sun.attributes.next_rising), set = Date.parse(sun.attributes.next_setting);
  if (!rise || !set) return [];
  const day = 86400000; const out = [];
  // The sun rises before it next sets: it is night now, until it rises.
  if (rise < set) out.push([base - (PAST_MIN + 120) * 60000, rise]);
  for (let i = 0; i < 2; i++) {
    const s = set + i * day; let r = rise; while (r <= s) r += day;
    out.push([s, r]);
  }
  return out.map(([a, b]) => [min(a), min(b)]).filter(([a, b]) => b > -PAST_MIN - 60 && a < AHEAD_MIN + 60);
}

function ticks(base, min) {
  const out = [];
  const first = new Date(base - PAST_MIN * 60000); first.setMinutes(0, 0, 0);
  for (let d = new Date(first); d.getTime() <= base + (AHEAD_MIN + 120) * 60000; d.setHours(d.getHours() + 1)) {
    const h = d.getHours(); const mid = h === 0;
    out.push({ t: min(d.getTime()), major: mid || h % 3 === 0, mid,
      label: mid ? d.toLocaleDateString([], { weekday: 'short' }) : h % 3 === 0 ? d.toLocaleTimeString([], { hour: 'numeric' }) : '' });
  }
  return out;
}

export function clampC(m, c) { return Math.max(m.minC, Math.min(m.maxC, c)); }

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

// What the reading point is over at cursor `c`.
export function reading(m, c) {
  const zone = m.stacks.filter((s) => Math.abs(s.t - c) * m.k <= ZONE_PX)
    .sort((a, b) => Math.abs(a.t - c) - Math.abs(b.t - c))[0];
  if (zone) {
    const f = zone.items[0]; const n = zone.items.length;
    return { hit: true, when: when(m, zone.t), rel: rel(zone.t), color: KINDS[f.kind].color, solid: f.solid,
      name: n > 1 ? zone.items.map((i) => i.label).join(' · ') : f.label, eid: n > 1 ? '' : f.eid || '',
      extra: n > 1 ? `${n} at once` : [f.sub, KINDS[f.kind].word].filter(Boolean).join(' · ') };
  }
  const over = m.durs.filter((d) => c >= d.t - 1 && c <= d.t2 + 1);
  if (over.length) {
    const d = over[0]; const running = d.t <= 0 && c <= 0.5;
    return { hit: true, when: running ? NOW : when(m, d.t), rel: running ? 'until ' + clock(m.base + d.t2 * 60000) : rel(d.t),
      color: KINDS[d.kind].color, solid: true, name: over.map((x) => x.label).join(' · '), eid: over.length > 1 ? '' : d.eid || '',
      extra: running ? `${dur(d.t2)} left` : `until ${clock(m.base + d.t2 * 60000)} · ${dur(d.t2 - d.t)}` };
  }
  const nx = m.targets.find((t) => t > c + 0.5);
  const nxs = nx == null ? null : m.stacks.find((s) => s.t === nx) || m.durs.find((d) => d.t === nx);
  const nxName = nxs ? (nxs.items ? nxs.items[0].label : nxs.label) : '';
  const atNow = Math.abs(c) < 1;
  return { hit: false, when: atNow ? NOW : when(m, c), rel: atNow ? clock(m.base) : rel(c), color: '', solid: true,
    name: atNow ? 'Nothing right now' : 'Nothing here', eid: '',
    extra: nxs ? `next: ${nxName}, ${rel(nx - c)}` : 'nothing else in the next day' };
}

function swell(m, t, c) {
  const near = Math.max(0, 1 - (Math.abs(t - c) * m.k) / SWELL_PX);
  return (1 + 0.75 * near).toFixed(3);
}

function readoutHtml(r) {
  const dot = r.color ? `<span class="cu-dot" style="border:2px ${r.solid ? 'solid' : 'dashed'} ${r.color}"></span>` : '';
  const name = r.eid ? `<button type="button" class="cu-name go" data-act="upc" data-v="${esc(r.eid)}">${esc(r.name)}</button>` : `<span class="cu-name${r.hit ? '' : ' quiet'}">${esc(r.name)}</span>`;
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
  const r = reading(m, c); const ro = readoutHtml(r);
  const nightBands = m.nights.map(([a, b]) => `<i class="cu-night" style="left:${x(a)}px;width:${((b - a) * k).toFixed(1)}px"></i>`).join('');
  const tickMarks = m.ticks.map((t) => `<i class="cu-tick${t.major ? ' major' : ''}" style="left:${x(t.t)}px"></i>${t.label ? `<span class="cu-tl${t.mid ? ' cu-mid' : ''}" style="left:${x(t.t)}px">${esc(t.label)}</span>` : ''}`).join('');
  const bars = m.durs.map((d) => {
    const done = d.t < 0 ? Math.min(d.t2, 0) - d.t : 0;
    return `<i class="cu-bar${c >= d.t && c <= d.t2 ? ' on' : ''}${d.t2 < 0 ? ' past' : ''}" data-cu-bar="${d.t},${d.t2}" style="left:${x(d.t)}px;width:${Math.max(6, (d.t2 - d.t) * k).toFixed(1)}px;top:${d.row ? 5 : -3}px;--c:${KINDS[d.kind].color}"><i style="width:${(done * k).toFixed(1)}px"></i></i>`;
  }).join('');
  const dots = m.stacks.map((s, i) => {
    const f = s.items[0];
    return `<span class="cu-pin${s.t < -1 ? ' past' : ''}" style="left:${x(s.t)}px"><span class="cu-dot" data-cu-dot="${i}" style="border:2px ${f.solid ? 'solid' : 'dashed'} ${KINDS[f.kind].color};transform:scale(${swell(m, s.t, c)})"></span>${s.items.length > 1 ? `<span class="cu-n">${s.items.length}</span>` : ''}</span>`;
  }).join('');
  const atNow = Math.abs(c) < 1;
  return `<div class="cu" data-upc>
<div class="cu-vp" data-upc-vp tabindex="0" role="slider" aria-label="Coming up. Drag, swipe or use the arrow keys to look ahead." aria-valuemin="${m.minC}" aria-valuemax="${m.maxC}" aria-valuenow="${Math.round(c)}" aria-valuetext="${esc(spoken(r))}">
<span class="cu-lens${r.hit ? ' hit' : ''}" data-cu-lens style="--c:${r.color || 'var(--line2)'}"></span>
<div class="cu-track" data-cu-track style="transform:translateX(${(-c * k).toFixed(1)}px)">${nightBands}<i class="cu-line" style="left:${x(m.minC - 180)}px;width:${((m.maxC - m.minC + 360) * k).toFixed(1)}px"></i>${tickMarks}<i class="cu-nowm"></i>${bars}${dots}</div>
<i class="cu-ph" aria-hidden="true"></i><i class="cu-ph low" aria-hidden="true"></i>
<div class="cu-when" data-cu-when aria-hidden="true">${ro.when}</div>
<div class="cu-what" data-cu-what aria-live="polite">${ro.what}</div>
</div>
<button type="button" class="cu-back go" data-act="upc-now"${atNow ? ' hidden' : ''}>Now</button><span class="cu-hint small"${atNow ? '' : ' hidden'} aria-hidden="true">Drag to look ahead</span>
</div>`;
}

// Moves a strip `html` drew to cursor `c` without rebuilding it.
export function paint(root, m, c) {
  if (!root) return;
  const q = (s) => root.querySelector(s);
  const track = q('[data-cu-track]'); if (!track) return;
  track.style.transform = `translateX(${(-c * m.k).toFixed(1)}px)`;
  root.querySelectorAll('[data-cu-dot]').forEach((el) => {
    const s = m.stacks[+el.dataset.cuDot]; if (s) el.style.transform = `scale(${swell(m, s.t, c)})`;
  });
  root.querySelectorAll('[data-cu-bar]').forEach((el) => {
    const [a, b] = el.dataset.cuBar.split(',').map(Number); el.classList.toggle('on', c >= a && c <= b);
  });
  const r = reading(m, c); const ro = readoutHtml(r);
  const lens = q('[data-cu-lens]'); if (lens) { lens.classList.toggle('hit', r.hit); lens.style.setProperty('--c', r.color || 'var(--line2)'); }
  const w = q('[data-cu-when]'); if (w && w.innerHTML !== ro.when) w.innerHTML = ro.when;
  const wt = q('[data-cu-what]'); if (wt && wt.innerHTML !== ro.what) wt.innerHTML = ro.what;
  const vp = q('[data-upc-vp]'); if (vp) { vp.setAttribute('aria-valuenow', String(Math.round(c))); vp.setAttribute('aria-valuetext', spoken(r)); }
  const atNow = Math.abs(c) < 1;
  const back = q('.cu-back'); if (back) back.hidden = atNow;
  const hint = q('.cu-hint'); if (hint) hint.hidden = !atNow;
}
