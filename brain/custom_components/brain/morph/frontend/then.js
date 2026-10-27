// "Then": the house as it was at a moment in the last day — vision §7.2.
//
// Slide Coming up into the past and the page enters THEN: every card shows
// its state at that moment, read off the recorder. This module answers
// "what was every one of these entities at time t", fetching one hour of
// history for the visible entities at a time (with the state at the start
// of the hour, which Home Assistant includes by default) and caching it, so
// a finger dragging back through the afternoon asks for each hour once.
//
// It also reads the logbook for the dots BEHIND the reading point: what
// happened, not what is scheduled (doors, locks, people arriving, scenes,
// appliances finishing).

const HOUR = 3600000;
const CACHE = new Map();
const MAX_HOURS = 30;
let onData = () => {};
export function setOnData(fn) { onData = fn; }

function rowsFor(hass, ids, hour) {
  const key = hour + '|' + ids.join(',');
  const hit = CACHE.get(key);
  if (hit) return hit.data;
  const entry = { data: undefined };
  CACHE.set(key, entry);
  if (CACHE.size > MAX_HOURS) CACHE.delete(CACHE.keys().next().value);
  const end = Math.min(Date.now(), hour + HOUR);
  hass.callWS({ type: 'history/history_during_period', start_time: new Date(hour).toISOString(), end_time: new Date(end).toISOString(), entity_ids: ids, minimal_response: false, no_attributes: false, significant_changes_only: false })
    .then((r) => { entry.data = r || {}; })
    .catch((e) => { entry.data = { __error: String((e && e.message) || e) }; })
    .finally(() => onData());
  return entry.data;
}

// The states at `t` for `ids`, as a states map shaped like hass.states, or
// undefined while the hour is being read. An entity with no row in that
// hour keeps its current state object marked `unknown_then`, so a card
// draws without claiming a value nobody recorded.
export function statesAt(hass, ids, t) {
  if (!ids.length) return {};
  const hour = Math.floor(t / HOUR) * HOUR;
  const data = rowsFor(hass, ids.slice().sort(), hour);
  if (data === undefined) return undefined;
  const out = { ...hass.states };
  if (data.__error) return out;
  ids.forEach((eid) => {
    const rows = data[eid] || [];
    let row = null; let attrs = null;
    rows.forEach((r) => {
      const at = ((r.lu != null ? r.lu : r.lc) || 0) * 1000;
      if (r.a) attrs = r.a;
      if (at <= t) { row = r; if (r.a) attrs = r.a; }
    });
    const cur = hass.states[eid];
    if (!row) { if (cur) out[eid] = { ...cur, unknown_then: true }; return; }
    out[eid] = {
      entity_id: eid,
      state: row.s,
      attributes: { ...((cur && cur.attributes) || {}), ...(attrs || {}) },
      last_changed: new Date(((row.lc != null ? row.lc : row.lu) || 0) * 1000).toISOString(),
      last_updated: new Date(((row.lu != null ? row.lu : row.lc) || 0) * 1000).toISOString(),
    };
  });
  return out;
}

const PAST = { key: '', at: 0, data: [] };
const PAST_DOMAINS = ['lock', 'person', 'scene', 'cover', 'binary_sensor', 'vacuum'];

// What happened in the last day to the entities worth a dot, as Coming up
// events: [{at, label, kind: 'past', solid: true, eid}]. Re-read every five
// minutes; a logbook that cannot be read is no dots, not an error.
export function past(hass, ids, now) {
  const pick = ids.filter((e) => PAST_DOMAINS.includes(e.split('.')[0])).slice(0, 60).sort();
  const key = pick.join(',');
  if (!pick.length) return [];
  if (PAST.key === key && now - PAST.at < 300000) return PAST.data;
  if (PAST.key !== key || !PAST.pending) {
    PAST.key = key; PAST.pending = true; PAST.at = now;
    hass.callWS({ type: 'logbook/get_events', start_time: new Date(now - 24 * HOUR).toISOString(), end_time: new Date(now).toISOString(), entity_ids: pick })
      .then((r) => {
        PAST.data = (Array.isArray(r) ? r : []).filter((x) => x.when && x.entity_id).slice(-160).map((x) => {
          const st = hass.states[x.entity_id];
          const name = (st && st.attributes && st.attributes.friendly_name) || x.entity_id;
          return { at: x.when * 1000, label: `${name}${x.state ? ' · ' + x.state : ''}`, kind: 'past', solid: true, eid: x.entity_id };
        });
      })
      .catch(() => { PAST.data = []; })
      .finally(() => { PAST.pending = false; onData(); });
  }
  return PAST.data;
}

export function clearCache() { CACHE.clear(); PAST.key = ''; PAST.data = []; }
