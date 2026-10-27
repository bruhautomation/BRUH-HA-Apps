// The salience list — docs/design/morph-vision.md §4.
//
// Every card and every room is an ITEM. For each item this module computes
// six numbers in [0, 1] from named sources (brAIn's measurements in
// `feed`, brAIn's cases, the entity's own state) and folds them into one
// score S, then into a band (Now, Lead, Shown, Folded) with hysteresis and
// a dwell, so a page laid out from it never flickers between two answers.
//
// It is PURE over what it is handed: no DOM, no fetches, no clock but
// `ctx.now`. The panel computes the list every ten seconds or on a salient
// event, and applies it to the page only at a quiet moment (§4.4); this
// module only says what the page would be.
//
// Three rules it never breaks:
//   * a missing source contributes 0 and says so — nothing here invents a
//     usual value (§4.7: "A page that said unusual for a Tuesday without a
//     Tuesday behind it would be the one lie that breaks the whole idea");
//   * recency only BOOSTS something that already has a reason;
//   * a habit alone (capped at 0.9) never outranks a fault.

export const BANDS = { now: { enter: 0.75, leave: 0.60 }, lead: { enter: 0.45, leave: 0.35 }, shown: { enter: 0.20, leave: 0.20 } };
export const BAND_ORDER = ['folded', 'shown', 'lead', 'now'];
export const MIN_DWELL_MS = 90000;
export const REARRANGE_SPACING_MS = 8000;
export const QUIET_TOUCH_MS = 1200;
export const QUIET_SCROLL_MS = 600;
export const NOW_MAX = 3;
export const NOW_MAX_PHONE = 2;
export const DECAY_AFTER_MS = 20 * 60000;
export const DECAY_STEP_MS = 10 * 60000;
export const ASKED_MS = 10 * 60000;
export const OCCUPIED_MS = 10 * 60000;
export const HABIT_AHEAD_MIN = 30;
export const HABIT_MIN_DAYS = 4;
export const FEED_OFFLINE_MS = 7 * 86400000;
export const HABIT_STOP_WEIGHT = 0.25;
// [from, to] in minutes past midnight: armed_home is night inside it until
// brAIn has measured the house's own settle and wake.
export const UNMEASURED_NIGHT = [19 * 60, 9 * 60];
// A habit this likely is a prediction (§7.1): the control arrives early.
export const PREDICT_MIN_H = 0.5;

const SEVERITY_U = { critical: 1.0, serious: 0.7, warning: 0.4, info: 0.15 };
const SAFETY = ['smoke', 'gas', 'carbon_monoxide', 'moisture'];
const CLOSURE_DC = ['door', 'window', 'garage_door', 'opening', 'garage', 'gate'];
const TAU_MIN = { door: 10, lock: 10, light: 20, appliance: 60, media: 5, other: 20 };
const RUNNING = ['cleaning', 'returning', 'running', 'printing', 'washing', 'drying', 'active'];

const clamp01 = (v) => Math.max(0, Math.min(1, v));
const domainOf = (eid) => String(eid || '').split('.')[0];
const isSafety = (st) => !!(st && domainOf(st.entity_id) === 'binary_sensor' && SAFETY.includes((st.attributes || {}).device_class));
const isClosure = (st) => {
  if (!st) return false;
  const d = domainOf(st.entity_id); const dc = (st.attributes || {}).device_class;
  return d === 'lock' || (d === 'binary_sensor' && CLOSURE_DC.includes(dc)) || (d === 'cover' && ['garage', 'gate', 'door'].includes(dc));
};
const isOpenState = (st) => !!st && ['on', 'open', 'opening', 'unlocked', 'unlocking'].includes(st.state);

// ---------------------------------------------------------------- periods

// Minutes since local midnight.
export function minuteOf(ms) { const d = new Date(ms); return d.getHours() * 60 + d.getMinutes(); }
const weekend = (ms) => { const w = new Date(ms).getDay(); return w === 0 || w === 6; };

// Day, evening, night or away (§4.2), read from the house's own measured
// rhythm and its alarm, never from the clock alone: an unmeasured house has
// no evening and no night but the alarm's and its sleepers'.
//
// "Night: alarm armed" (§4.2). Which panel is the house's alarm is the
// panel's to say (`ctx.alarms`, the alarm panels on the dashboard) — the
// first panel in the states map may be a camera system's, never armed at
// bedtime. `armed_night` is night whatever the clock says; `armed_home` is
// the bedtime arming in a house that has no night mode, so it is night
// inside the measured settle-to-wake window, and — until brAIn has measured
// a rhythm — whenever it is set between 7 PM and 9 AM, because waiting for
// a measurement that may be weeks away meant a house armed for bed never
// got its night page. The window is wide on purpose: it only has to tell a
// bedtime arming from a house armed "stay" at noon, never to place bedtime.
export function alarmStates(ctx) {
  const S = ctx.states || {};
  const named = (ctx.alarms || []).map((e) => S[e]).filter(Boolean);
  if (named.length) return named;
  return Object.values(S).filter((s) => domainOf(s.entity_id) === 'alarm_control_panel');
}

export function period(ctx) {
  const S = ctx.states || {};
  const people = Object.values(S).filter((s) => domainOf(s.entity_id) === 'person');
  const home = people.filter((s) => s.state === 'home');
  if (people.length && !home.length) return 'away';
  const alarms = alarmStates(ctx);
  const armed = (word) => alarms.some((a) => a.state === word);
  if (armed('armed_night')) return 'night';
  if (armed('armed_away') && !home.length) return 'away';
  const feed = ctx.feed || {};
  const r = feed.rhythm && feed.rhythm[weekend(ctx.now) ? 'weekend' : 'weekday'];
  const m = minuteOf(ctx.now);
  if (r && r.settle != null && r.wake != null) {
    const settle = r.settle, wake = r.wake;
    const inNight = settle > wake ? (m >= settle || m < wake) : (m >= settle && m < wake);
    if (inNight || (armed('armed_home') && (m >= settle - 60 || m < wake))) return 'night';
    if (m >= settle - 150 && m < settle) return 'evening';
  } else if (armed('armed_home') && (m >= UNMEASURED_NIGHT[0] || m < UNMEASURED_NIGHT[1])) return 'night';
  // "Or every tracked person asleep": every room that can say it is asleep
  // says so, and there are at least two of them (one asleep room is a
  // child's bedtime, not the house's).
  if (ctx.allAsleep) return 'night';
  if (ctx.anyAsleep) return 'evening';
  return 'day';
}

// Whether one entity says its room is asleep (§6.4). A mode (a select set
// to Sleep), a sleep switch or sensor that is on, or a sensor whose state
// is asleep. A name that says sleep AND names a device is a control used at
// night, not a sleeper: "Sleeping headphones fan" on is a fan running, and
// it used to flip the whole house into its evening.
const SLEEP_WORD = /\b(sleep|sleeping|asleep|bedtime)\b/i;
const DEVICE_WORD = /\b(fan|fans|light|lights|lamp|headphones?|speaker|sound|noise|machine|music|tv|heater|heat|humidifier|purifier|plug|outlet|socket|blind|blinds|shade|curtain|timer|alarm clock)\b/i;
const SLEEP_STATE = /^(sleep|sleeping|asleep|night|in bed|in_bed|light sleep|deep sleep|rem)$/i;
export function sleepSignal(eid, st) {
  if (!st) return false;
  const d = domainOf(eid);
  const name = String(eid).split('.')[1].replace(/_/g, ' ') + ' ' + String((st.attributes || {}).friendly_name || '');
  if ((d === 'input_select' || d === 'select') && /^(sleep|sleeping|asleep|night)$/i.test(st.state)) return true;
  if (d === 'sensor' && SLEEP_WORD.test(name) && SLEEP_STATE.test(String(st.state))) return true;
  if (['input_boolean', 'switch', 'binary_sensor'].includes(d) && st.state === 'on' && SLEEP_WORD.test(name) && !DEVICE_WORD.test(name)) return true;
  return false;
}

// ------------------------------------------------------------------ inputs

function deviation(st, feed, now) {
  if (!st) return { d: 0 };
  const eid = st.entity_id;
  const n = feed && feed.normal && feed.normal[eid];
  const v = parseFloat(st.state);
  if (n && n.now && isFinite(v)) {
    const [median, spread] = n.now;
    if (spread > 0 && isFinite(median)) {
      const z = Math.abs(v - median) / spread;
      return { d: clamp01((z - 2) / 4), usual: median, unit: n.unit || (st.attributes || {}).unit_of_measurement || '', value: v };
    }
  }
  const door = feed && feed.doors && feed.doors[eid];
  if (door && door.now != null && isClosure(st)) {
    const openShare = Number(door.now);
    const p = isOpenState(st) ? openShare : 1 - openShare;
    return { d: clamp01(1 - p), share: openShare };
  }
  return { d: 0, unmeasured: true };
}

function urgency(st, cases) {
  let u = 0; let c = null;
  (cases || []).forEach((x) => { const v = SEVERITY_U[x.severity] || 0.15; if (v > u) { u = v; c = x; } });
  if (isSafety(st) && st.state === 'on') return { u: 1, safety: true, c };
  return { u, c };
}

function progress(st, feed, now) {
  if (!st) return { g: 0 };
  const a = (feed && feed.appliances && feed.appliances[st.entity_id]) || null;
  if (a && a.state === 'finished') return { g: 0.9, finished: true, since: a.since };
  if (a && a.state === 'running') return { g: 0.5, running: true };
  const d = domainOf(st.entity_id);
  if (d === 'vacuum' && RUNNING.includes(st.state)) return { g: 0.5, running: true };
  if (d === 'timer' && st.state === 'active') return { g: 0.5, running: true };
  if (d === 'media_player' && st.state === 'playing') return { g: 0.5, running: true, media: true };
  if (d === 'sensor' && /print|progress/.test(st.entity_id) && (st.attributes || {}).unit_of_measurement === '%') {
    const p = parseFloat(st.state);
    if (isFinite(p) && p > 0 && p < 100) return { g: 0.5, running: true, pct: p };
  }
  if (d === 'switch' && /irrigat|sprinkler|zone/i.test(st.entity_id) && st.state === 'on') return { g: 0.5, running: true };
  return { g: 0 };
}

const kindForTau = (st) => {
  const d = domainOf(st && st.entity_id);
  if (d === 'lock' || isClosure(st)) return 'door';
  if (d === 'light') return 'light';
  if (d === 'media_player') return 'media';
  if (d === 'vacuum' || d === 'timer' || d === 'sensor') return 'appliance';
  return 'other';
};

function recency(st, now) {
  if (!st || !st.last_changed) return 0;
  const dt = Math.max(0, now - Date.parse(st.last_changed));
  return Math.exp(-dt / (TAU_MIN[kindForTau(st)] * 60000));
}

// A habit the viewer is likely to act on in the next half hour: a measured
// time of day, on this kind of day, for a state the entity is not in now.
function habit(st, feed, ctx) {
  if (!st) return { h: 0 };
  const rows = ((feed && feed.habits) || []).filter((x) => x.entity_id === st.entity_id && (x.days_seen || 0) >= HABIT_MIN_DAYS);
  const m = minuteOf(ctx.now); const we = weekend(ctx.now);
  let best = null;
  rows.forEach((x) => {
    if (x.days === 'weekdays' && we) return;
    if (x.days === 'weekends' && !we) return;
    if (x.state && String(x.state) === String(st.state)) return;
    const spread = Math.max(1, x.spread || 0);
    const start = x.minute - spread; // the window opens one spread early
    let ahead = start - m; if (ahead < -720) ahead += 1440; if (ahead > 720) ahead -= 1440;
    if (ahead > HABIT_AHEAD_MIN || ahead < -(spread * 2 + 20)) return;
    const w = (ctx.habitWeights && ctx.habitWeights[st.entity_id] != null) ? ctx.habitWeights[st.entity_id] : 1;
    // Two ignored windows in a row and the prediction stops (§7.1): each
    // halves the weight, so a quarter is two ignored and silence.
    if (w <= HABIT_STOP_WEIGHT) return;
    const h = Math.min(0.9, (x.share || 0)) * w;
    if (!best || h > best.h) best = { h, row: x };
  });
  if (!best) return { h: 0 };
  return { h: best.h, person: best.row.person || null, minute: best.row.minute, spread: best.row.spread };
}

function viewerWeight(person, ctx) {
  if (!person) return 1;
  const v = ctx.viewer || {};
  if (v.device === 'family') {
    const st = (ctx.states || {})[person];
    return st && st.state !== 'home' ? 0 : 1;
  }
  if (v.person) return v.person === person ? 1 : 0.35;
  return 1;
}

// The six inputs for one entity, with what they were read from.
export function inputs(st, ctx) {
  const feed = ctx.feed || {};
  const dv = deviation(st, feed, ctx.now);
  const ur = urgency(st, (ctx.casesByEntity || {})[st && st.entity_id]);
  const pr = progress(st, feed, ctx.now);
  const hb = habit(st, feed, ctx);
  const r = recency(st, ctx.now);
  const v = viewerWeight(hb.person, ctx);
  return { d: dv.d, u: ur.u, g: pr.g, h: hb.h, r, v, dv, ur, pr, hb };
}

// ------------------------------------------------------------------ score

// §4.2's reweighting for the house's period.
export function reweight(inp, st, per) {
  const o = { ...inp };
  const d = domainOf(st && st.entity_id);
  if (per === 'evening') {
    if (d === 'media_player') o.g = Math.min(1, o.g * 1.2);
    if (o.asleepRoom) o.d = Math.min(1, o.d * 1.5);
  } else if (per === 'night') {
    if ((d === 'lock' || isClosure(st)) && isOpenState(st)) o.d = 1;
    if (d === 'light') o.d *= 0.5;
    o.h *= 0.3;
  } else if (per === 'away') {
    if (d === 'lock' || isClosure(st) || d === 'camera' || isSafety(st)) o.d = Math.min(1, o.d * 1.5);
    if (d === 'light' || d === 'media_player') o.h = 0;
  }
  return o;
}

export function score(i) {
  const core = 1 - (1 - i.u) * (1 - i.d) * (1 - 0.8 * i.g) * (1 - 0.7 * i.h * i.v);
  const boost = i.d + i.u + i.g > 0 ? 0.15 * i.r : 0;
  return Math.max(0, Math.min(1, core + boost));
}

// The band S enters, given where it was (hysteresis): entering a band
// needs its enter threshold, staying needs only its leave threshold.
export function bandFor(S, was) {
  const wasI = BAND_ORDER.indexOf(was || 'folded');
  for (let i = BAND_ORDER.length - 1; i >= 1; i--) {
    const name = BAND_ORDER[i]; const b = BANDS[name];
    if (S >= b.enter) return name;
    if (wasI >= i && S >= b.leave) return name;
  }
  return 'folded';
}

// ----------------------------------------------------------- the reasons

// The because line (§11): one sentence out of a closed set, in the item's
// meaning colour. Never a reason without a measurement behind it.
export function because(x, ctx) {
  const name = ctx.name || ((e) => e);
  if (x.pinned) return { text: x.pinned === 'active' ? 'kept here while it is on' : 'kept here', color: 'var(--violet)', kind: 'pinned' };
  if (x.asked) return { text: 'because you asked', color: 'var(--violet)', kind: 'asked' };
  const i = x.inp;
  if (!i) return null;
  if (i.ur.safety) return { text: 'tripped', color: 'var(--rose)', kind: 'urgency' };
  if (i.ur.c && i.u >= i.d && i.u >= i.g) return { text: i.ur.c.claim || i.ur.c.text || 'brAIn noticed this', color: i.u >= 0.7 ? 'var(--rose)' : 'var(--amber)', kind: 'urgency' };
  if (i.pr.finished) return { text: i.pr.since ? `finished ${agoWords(ctx.now - i.pr.since * 1000)}` : 'finished', color: 'var(--amber)', kind: 'progress' };
  if (i.pr.running && i.g >= i.d) return { text: i.pr.pct != null ? `in progress · ${Math.round(i.pr.pct)}%` : 'in progress', color: 'var(--amber)', kind: 'progress' };
  if (i.d > 0) {
    if (i.dv.usual != null) return { text: `${fmtv(i.dv.value, i.dv.unit)}, usually about ${fmtv(i.dv.usual, i.dv.unit)} at this hour`, color: i.d >= 0.7 ? 'var(--rose)' : 'var(--amber)', kind: 'deviation' };
    if (i.dv.share != null) return { text: x.night && x.open ? 'open at night' : `unusual for ${clockWords(ctx.now)}`, color: x.night ? 'var(--rose)' : 'var(--amber)', kind: 'deviation' };
    if (x.night) return { text: 'open at night', color: 'var(--rose)', kind: 'deviation' };
  }
  if (i.h > 0) {
    const who = i.hb.person && ctx.viewer && ctx.viewer.person !== i.hb.person ? `${name(i.hb.person)} usually does this now` : 'you usually do this now';
    return { text: who, color: 'var(--violet)', kind: 'habit' };
  }
  if (i.dv.unmeasured && x.S >= BANDS.shown.enter) return { text: 'no usual yet', color: 'var(--quiet)', kind: 'none' };
  return null;
}

function fmtv(v, unit) {
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  const s = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1).replace(/\.0$/, '');
  return s + (unit ? (unit.startsWith('°') || unit === '%' ? unit : ' ' + unit) : '');
}
function agoWords(ms) {
  const m = Math.max(0, Math.round(ms / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60); return `${h} h ago`;
}
function clockWords(ms) { return new Date(ms).toLocaleTimeString([], { hour: 'numeric' }); }

// ----------------------------------------------------------- the whole list

// `items`: [{id, sec, entities: [eid], primary: eid, caseIds?: [], case?: case}]
// `prev`:  the previous result's `state` ({id: {band, since, liftedAt}})
// Returns {items: {id: {...}}, rooms: {sec: {S, occupied}}, now: [ids], top: [ids], state, period}.
export function compute(items, ctx, prev) {
  const per = ctx.period || period(ctx);
  const now = ctx.now;
  const P = (prev && prev.state) || {};
  const out = {};
  const S = ctx.states || {};
  items.forEach((it) => {
    let best = null;
    const ents = it.entities && it.entities.length ? it.entities : [it.primary];
    ents.forEach((eid) => {
      const st = S[eid];
      if (!st && !it.case) return;
      let inp = inputs(st, ctx);
      inp.asleepRoom = !!(ctx.asleepRooms && ctx.asleepRooms[it.sec]);
      inp = reweight(inp, st, per);
      const sc = score(inp);
      if (!best || sc > best.S) best = { S: sc, inp, eid, st };
    });
    if (it.case) {
      const u = SEVERITY_U[it.case.severity] || 0.15;
      const inp = { d: 0, u, g: 0, h: 0, r: 0, v: 1, dv: { d: 0 }, ur: { u, c: it.case }, pr: {}, hb: {} };
      const sc = score(inp);
      if (!best || sc > best.S) best = { S: sc, inp, eid: it.case.entity_id || '', st: null, isCase: true };
    }
    if (!best) { out[it.id] = { id: it.id, sec: it.sec, S: 0, band: 'folded' }; return; }
    let Sx = best.S;
    const was = P[it.id] || {};
    // A pin keeps a card in Now; a pin "while it is on" only while it is.
    const pin = ctx.pins && ctx.pins[it.id];
    const pinnedNow = pin === true || (pin === 'active' && best.st && (isOpenState(best.st) || ['playing', 'cleaning', 'heating', 'cooling'].includes(best.st.state) || best.inp.g > 0));
    const asked = ctx.asked && ctx.asked[it.id] && ctx.asked[it.id] > now;
    if (pinnedNow || asked) Sx = Math.max(Sx, 0.8);
    // A prediction is a control arriving early (§7.1): into Now on a
    // personal device, to the top of its room on a family one. The score
    // alone cannot carry it there — a habit at its 0.9 cap is 0.63 — so
    // the lift is a floor, and in Now a prediction takes only the places
    // nothing with a reason of its own wanted (it never outranks a fault).
    const predicted = !!(best.inp.h > 0 && best.inp.h * (best.inp.v == null ? 1 : best.inp.v) >= PREDICT_MIN_H && !best.isCase);
    if (predicted) Sx = Math.max(Sx, ctx.viewer && ctx.viewer.device === 'family' ? BANDS.lead.enter : BANDS.now.enter);
    // Not this: suppressed for today, whatever lifted it.
    if (ctx.suppressed && ctx.suppressed[it.id]) Sx = Math.min(Sx, BANDS.lead.enter - 0.01);
    // Decay: in Now and untouched past its window.
    if (was.band === 'now' && was.liftedAt && !pinnedNow && !asked && !best.inp.ur.safety) {
      const touched = (ctx.touched && ctx.touched[it.id]) || 0;
      const from = Math.max(was.liftedAt, touched);
      const win = best.inp.h > 0 && best.inp.hb.spread ? (best.inp.hb.spread * 2 + 20) * 60000 : DECAY_AFTER_MS;
      const over = now - from - win;
      if (over > 0) Sx *= Math.pow(0.5, over / DECAY_STEP_MS);
    }
    let band = bandFor(Sx, was.band);
    // Dwell: a band entered stays at least MIN_DWELL_MS before a lower one takes it.
    const wasI = BAND_ORDER.indexOf(was.band || 'folded');
    if (was.band && BAND_ORDER.indexOf(band) < wasI && was.since && now - was.since < MIN_DWELL_MS) band = was.band;
    // Urgent goes at once (§4.4): a safety trip, a serious case, and a
    // door or lock that just opened at night — the 3 AM moment, a cut.
    const justOpened = best.st && best.st.last_changed && now - Date.parse(best.st.last_changed) < 120000;
    // A cut is the one change that goes even under a hand (a safety trip,
    // a door opening at night); everything else urgent only skips the
    // spacing between rearrangements (§4.4).
    const cut = !!(best.inp.ur.safety || (per === 'night' && best.st && isOpenState(best.st) && (domainOf(best.st.entity_id) === 'lock' || isClosure(best.st)) && justOpened));
    const urgent = cut || best.inp.u >= 0.7;
    const night = per === 'night' && best.st && (domainOf(best.st.entity_id) === 'lock' || isClosure(best.st));
    const x = { id: it.id, sec: it.sec, S: Sx, band, eid: best.eid, inp: best.inp, urgent, cut, isCase: !!best.isCase, pinned: pinnedNow ? pin : null, asked, night, open: best.st && isOpenState(best.st), predicted: predicted && !(ctx.suppressed && ctx.suppressed[it.id]) };
    x.why = because(x, ctx);
    x.color = colorOf(x);
    out[it.id] = x;
  });
  // Now: at most N, highest first; the rest wait at the top of their room.
  const max = ctx.nowMax || NOW_MAX;
  const mere = (x) => (x.predicted && !(x.inp.u || x.inp.d || x.inp.g) && !x.pinned && !x.asked ? 1 : 0);
  const nowIds = Object.values(out).filter((x) => x.band === 'now').sort((a, b) => mere(a) - mere(b) || b.S - a.S || String(a.id).localeCompare(String(b.id)));
  // One thing is lifted once: two cards for the same lock (the Entry and
  // the Security room both carry it) are one card in Now, the first.
  const seenE = new Set(); const kept = [];
  // At night the page is the one thing that is wrong (§11): Now holds only
  // what the night floors lift (an open closure, an unlocked lock), an
  // urgent trip, a rose case or a pin. A warm room waits for the morning.
  const nightOk = (x) => x.urgent || (x.night && x.open) || x.pinned || (x.isCase && x.color === 'var(--rose)');
  nowIds.forEach((x) => {
    const k = x.eid || x.id;
    if (per === 'night' && !nightOk(x)) { x.band = 'lead'; return; }
    if (seenE.has(k) || kept.length >= max) { x.band = 'lead'; x.waiting = !seenE.has(k); x.twin = seenE.has(k); return; }
    seenE.add(k); kept.push(x);
  });
  const now_ = kept.map((x) => x.id);
  const state = {};
  Object.values(out).forEach((x) => {
    const was = P[x.id] || {};
    state[x.id] = { band: x.band, since: was.band === x.band ? was.since || now : now, liftedAt: x.band === 'now' ? (was.band === 'now' ? was.liftedAt || now : now) : 0 };
  });
  // Rooms: the max of their items, plus 0.1 when occupied.
  const rooms = {};
  Object.values(out).forEach((x) => {
    const r = rooms[x.sec] || (rooms[x.sec] = { S: 0, top: null });
    if (x.S > r.S) { r.S = x.S; r.top = x.id; }
  });
  Object.keys(ctx.occupied || {}).forEach((sec) => {
    if (ctx.occupied[sec]) { const r = rooms[sec] || (rooms[sec] = { S: 0, top: null }); r.S = Math.min(1, r.S + 0.1); r.occupied = true; }
  });
  const top = Object.values(out).filter((x) => x.S >= BANDS.lead.enter && x.why && x.why.kind !== 'none').sort((a, b) => b.S - a.S).map((x) => x.id);
  return { items: out, rooms, now: now_, top, state, period: per, at: now };
}

// The meaning colour (§9.2) for an item.
export function colorOf(x) {
  if (!x || !x.inp) return 'var(--text)';
  if (x.urgent || (x.night && x.open)) return 'var(--rose)';
  if (x.asked || x.pinned || (x.inp.h > x.inp.d && x.inp.h > x.inp.g)) return 'var(--violet)';
  if (x.inp.d > 0 || x.inp.u > 0 || x.inp.pr.finished) return 'var(--amber)';
  return 'var(--text)';
}

// Whether the page may rearrange now (§4.4). `ui`: {lastTouch, pointerDown,
// open, lastScroll, lastArrange}; `urgent`: true for an item entering Now
// with u ≥ 0.7, 'cut' for a safety trip or a door opening at night.
export function quietMoment(ui, now, urgent) {
  // A cut (a safety trip, a door opening at night) goes at once, whatever
  // hands are on the page: that is the one moment speed beats grace.
  if (urgent === 'cut') return true;
  if (ui.pointerDown) return false;
  if (ui.open) return false;
  if (now - (ui.lastTouch || 0) < QUIET_TOUCH_MS) return false;
  if (now - (ui.lastScroll || 0) < QUIET_SCROLL_MS) return false;
  // Anything else urgent (a case at u ≥ 0.7 entering Now) is exempt from
  // the spacing and nothing else (§4.4).
  if (!urgent && now - (ui.lastArrange || 0) < REARRANGE_SPACING_MS) return false;
  return true;
}

// A feed older than its own stale_after_s is brAIn offline (said, and still
// used); past a week it is not used at all (state-only salience).
export function feedHealth(feed, nowMs, mtimeMs) {
  if (!feed || !feed.v) return { state: 'none', usable: false };
  const at = (mtimeMs || (feed.at || 0) * 1000);
  const age = nowMs - at;
  if (age > FEED_OFFLINE_MS) return { state: 'expired', usable: false };
  if (age > (feed.stale_after_s || 7200) * 1000) return { state: 'offline', usable: true };
  return { state: 'ok', usable: true };
}
