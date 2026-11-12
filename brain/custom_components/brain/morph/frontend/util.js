// Small shared helpers: escaping, colour, time, and the icon set.
//
// Icons follow the design's rule: a still outline plus ONE moving part that
// tells the state (a bulb's rays breathe when it is on, fan blades spin at
// speed, a shackle lifts when unlocked). They respect reduced motion through
// the stylesheet.

export const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const attr = esc;
export const mix = (c, p, base) => `color-mix(in oklab, ${c} ${p}%, ${base || 'transparent'})`;
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const HUES = ['amber', 'sand', 'sky', 'violet', 'teal', 'lime', 'rose', 'peach', 'indigo'];
export const hue = (h) => `var(--${HUES.includes(h) ? h : 'sky'})`;

export const domainOf = (eid) => String(eid || '').split('.')[0];

export function clock(d) {
  const dt = d instanceof Date ? d : new Date(d);
  if (isNaN(dt)) return '';
  return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function ago(iso) {
  const t = new Date(iso).getTime();
  if (!t) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 86400) return Math.round(s / 3600) + ' h ago';
  return Math.round(s / 86400) + ' d ago';
}

export function since(iso) {
  const t = new Date(iso);
  if (isNaN(t)) return '';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (t >= today) return 'since ' + clock(t);
  return 'since ' + t.toLocaleDateString([], { weekday: 'short' }) + ' ' + clock(t);
}

export function dur(ms) {
  const m = Math.round(ms / 60000);
  if (m < 60) return m + ' min';
  const h = Math.floor(m / 60), r = m % 60;
  return h + ' h' + (r ? ' ' + r + ' min' : '');
}

export function num(v, digits) {
  const n = Number(v);
  if (!isFinite(n)) return null;
  return digits == null ? n : Number(n.toFixed(digits));
}

export function fmt(v, unit) {
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  const d = Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 1;
  return n.toFixed(d).replace(/\.0$/, '') + (unit ? (unit === '%' || unit.startsWith('°') ? unit : ' ' + unit) : '');
}

// The colour a light is giving off, as a CSS colour: its own colour when
// it has one, otherwise its white read as warm, soft or daylight.
export function lightColor(st) {
  const a = (st && st.attributes) || {};
  if (a.color_mode && !['color_temp', 'brightness', 'onoff', 'white'].includes(a.color_mode) && Array.isArray(a.rgb_color)) {
    const [r, g, b] = a.rgb_color;
    return `rgb(${r}, ${g}, ${b})`;
  }
  const k = a.color_temp_kelvin || (a.color_temp ? 1e6 / a.color_temp : 0);
  if (k && k >= 4800) return 'var(--sky)';
  if (k && k >= 3400) return 'var(--sand)';
  return 'var(--amber)';
}

// `hide`: the moving part is only there while the thing is on (a bulb's rays).
// The words for a light's colour, the same split lightColor draws.
export function lightTone(st) {
  const c = lightColor(st);
  return c.startsWith('rgb') ? 'Color' : c === 'var(--sky)' ? 'Daylight' : c === 'var(--sand)' ? 'Soft' : 'Warm';
}

// What a thermostat is doing, as a floor reads it: "cooling to 72°".
export function climateDoing(st) {
  const a = (st && st.attributes) || {};
  const t = a.temperature, lo = a.target_temp_low, hi = a.target_temp_high;
  const to = t != null ? fmt(t, '°') : lo != null && hi != null ? `${fmt(lo, '')}–${fmt(hi, '°')}` : '';
  if (!st || st.state === 'off') return st ? 'HVAC off' : '';
  if (st.state === 'cool') return to ? 'cooling to ' + to : 'cooling';
  if (st.state === 'heat') return to ? 'heating to ' + to : 'heating';
  if (['heat_cool', 'auto'].includes(st.state)) return to ? 'keeping ' + to : 'auto';
  return st.state.replace('_', ' ');
}

const I = (base, part, cls, origin, hide) => ({ base, part, cls: cls || '', origin: origin || '50% 50%', hide: !!hide });
export const ICONS = {
  bulb: I('M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2v.2h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z', 'M4.6 4.6l1 1M19.4 4.6l-1 1M2.4 10h1.4M20.2 10h1.4', 'breathe', '12px 9px', true),
  group: I('M4 5h4v3H4zM10 5h4v3h-4zM16 5h4v3h-4z', 'M5 10.5l-1 4M7 10.5l1 4M11 10.5l-1 4M13 10.5l1 4M17 10.5l-1 4M19 10.5l1 4', 'breathe', '12px 9px', true),
  led: I('M3 18h18', 'M3 12.5c3-4 6-4 9 0s6 4 9 0', 'wave', '12px 12px'),
  fan: I('M13.6 12a1.6 1.6 0 1 1-3.2 0 1.6 1.6 0 0 1 3.2 0z', 'M12 10.4C11 6 12 3 15 3c2 0 2 3-1.5 7.5M13.6 12.6c4 1.6 6.4 4 5 6.5-1 1.8-3.6.6-5.6-4.4M10.6 13c-2.8 3.4-6 4.2-7.2 1.8-.9-1.8 1.4-3.3 6.6-3.6', 'spin', '12px 12px'),
  blinds: I('M3 4h18M12 4v1.5', 'M5 7h14M5 10h14M5 13h14M5 16h14M5 19h14', '', '12px 6px'),
  lock: I('M6 11h12v10H6zM12 15v2', 'M8 11V7a4 4 0 0 1 8 0v4'),
  power: I('M12 3v8', 'M7 6.5a7 7 0 1 0 10 0'),
  thermo: I('M14 14.76V4.5a2 2 0 0 0-4 0v10.26a4 4 0 1 0 4 0z', 'M12 9v8', '', '50% 100%'),
  humid: I('M12 3s6 7 6 11.2a6 6 0 0 1-12 0C6 10 12 3 12 3z', 'M9.5 14.5a2.6 2.6 0 0 0 2.5 2.5', 'breathe'),
  tv: I('M3 6h18v12H3zM8 21h8', 'M10 9.5l4.5 2.5-4.5 2.5z'),
  speaker: I('M7 3h10v18H7z', 'M12 16a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 7h.01'),
  camera: I('M3 7h4l2-3h6l2 3h4v13H3z', 'M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'breathe'),
  door: I('M5 21h14M7 21V3h10v18', 'M14 12.5h.01'),
  person: I('M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21a8 8 0 0 1 16 0'),
  sun: I('M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z', 'M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4', 'spin'),
  cloud: I('M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z', 'M8 21h.01M12 21h.01M16 21h.01', 'bob'),
  vacuum: I('M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2', 'spin'),
  bolt: I('M13 2L4 14h7l-1 8 9-12h-7z', 'M13 2L4 14h7l-1 8 9-12h-7z', 'breathe'),
  water: I('M12 3s6 7 6 11.2a6 6 0 0 1-12 0C6 10 12 3 12 3z', 'M8 15h8', 'bob'),
  shield: I('M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z', 'M9 12l2 2 4-4'),
  garage: I('M3 21V9l9-6 9 6v12', 'M6 12h12M6 15h12M6 18h12', '', '50% 40%'),
  play: I('M5 4l14 8-14 8z', 'M5 4l14 8-14 8z', 'breathe'),
  dot: I('M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z'),
  // A plain appliance: a body, its control row and a door. The picture for anything the board has no picture for.
  appliance: I('M5 3h14v18H5zM5 8h14', 'M8.5 5.5h.01M12 5.5h.01M15.5 5.5h.01M8 12h8v6H8z', 'breathe'),
  brain: I('M12 3c.7 4.4 2.3 6.1 6.8 6.8-4.5.7-6.1 2.4-6.8 6.8-.7-4.4-2.3-6.1-6.8-6.8C9.7 9.1 11.3 7.4 12 3z', 'M19 14.5c.3 1.9 1 2.6 2.9 2.9-1.9.3-2.6 1-2.9 2.9-.3-1.9-1-2.6-2.9-2.9 1.9-.3 2.6-1 2.9-2.9z'),
};

// An icon: the still outline, then the part that moves.
export function icon(kind, opts) {
  const o = opts || {};
  const ic = ICONS[kind] || ICONS.dot;
  const size = o.size || 18;
  const color = o.color || 'currentColor';
  const cls = o.active ? ic.cls : '';
  const dur = o.dur ? `animation-duration:${o.dur};` : '';
  const tf = o.transform ? `transform:${o.transform};` : '';
  const op = o.partOpacity != null ? `opacity:${o.partOpacity};` : ic.hide && !o.active ? 'opacity:0;' : '';
  return `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="color:${color}"><path d="${ic.base}"></path><g class="${cls}" style="transform-box:view-box;transform-origin:${ic.origin};${tf}${dur}${op}transition:transform .6s cubic-bezier(.25,1,.3,1),opacity .4s ease"><path d="${ic.part}"></path></g></svg>`;
}

// Morph's mark, light and minimal: a tile with three square corners and one
// rounded all the way into the arc of a circle, with a dot at that circle's
// centre (branding/morph/). It is the press in an opened card that says
// "change this", so it is drawn in the current colour and stays quiet.
export const MARK = (size = 18) => `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" style="flex-shrink:0"><path d="M4 5.2A1.2 1.2 0 0 1 5.2 4H18.8A1.2 1.2 0 0 1 20 5.2V12A8 8 0 0 1 12 20H5.2A1.2 1.2 0 0 1 4 18.8Z"/><circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></svg>`;

export const SPARK = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" style="flex-shrink:0"><path d="M12 3c.7 4.4 2.3 6.1 6.8 6.8-4.5.7-6.1 2.4-6.8 6.8-.7-4.4-2.3-6.1-6.8-6.8C9.7 9.1 11.3 7.4 12 3z" fill="var(--violet)"></path><path d="M19 14.5c.3 1.9 1 2.6 2.9 2.9-1.9.3-2.6 1-2.9 2.9-.3-1.9-1-2.6-2.9-2.9 1.9-.3 2.6-1 2.9-2.9z" fill="var(--teal)"></path></svg>';

export function friendly(hass, eid, fallback) {
  const st = hass && hass.states[eid];
  return (st && st.attributes && st.attributes.friendly_name) || fallback || String(eid || '').split('.').pop().replace(/_/g, ' ');
}

// What may sit between a room's name and the rest: spaces and the separators
// people type ("Kitchen - Bread Stretch"). generator.py strips the same set.
const SEPARATORS = ' \t-\u2013\u2014:|/\u00b7,';
const isSep = (ch) => SEPARATORS.includes(ch);

// "Kitchen Cans" in the Kitchen reads "Cans", and "Kitchen - Bread Stretch"
// reads "Bread Stretch": the separator goes with the room. The room has to end
// at a separator, so "Kitchenette Lamp" stays whole.
export function shortName(name, room) {
  const n = String(name || '');
  const r = String(room || '');
  if (!r || n.length <= r.length || n.slice(0, r.length).toLowerCase() !== r.toLowerCase() || !isSep(n[r.length])) return n;
  let i = r.length;
  while (i < n.length && isSep(n[i])) i += 1;
  let j = n.length;
  while (j > i && isSep(n[j - 1])) j -= 1;
  const rest = n.slice(i, j);
  return rest ? rest[0].toUpperCase() + rest.slice(1) : n;
}

export const UNAVAILABLE = ['unavailable', 'unknown'];

// #764: a freezer whose entity had stopped answering showed its last
// temperature, its target and a running timer under an "unavailable" badge,
// as if they were live. Home Assistant sets `last_changed` when an entity goes
// unavailable, so that is when it was last heard from, and it is all a tile
// can honestly say about it now: "last seen 4:02 PM", "last seen Mon 4:02
// PM", "last seen Oct 30". Empty for anything that is answering.
export function lastSeen(st) {
  if (!st || !UNAVAILABLE.includes(st.state)) return '';
  const t = Date.parse(st.last_changed || st.last_updated || '');
  if (!t) return 'not answering';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (t >= today.getTime()) return 'last seen ' + clock(t);
  if (t >= today.getTime() - 6 * 86400000) return 'last seen ' + new Date(t).toLocaleDateString([], { weekday: 'short' }) + ' ' + clock(t);
  return 'last seen ' + new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// A module whose FETCH failed (a request dropped on the way through the
// cloud link, a restart mid-load) is a different thing from one whose code
// threw: the first is worth one more try, the second would only run its
// side effects twice. These are the three browsers' words for the first.
const FETCH_FAILED = /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module/i;
export const fetchFailed = (e) => FETCH_FAILED.test(String((e && e.message) || e || ''));

// Import a module, trying a failed fetch once more on a fresh URL (a failed
// module fetch may be remembered by its URL). `load` is the importer, so the
// caller's own `import()` resolves relative to the caller.
export function importWithRetry(url, opts) {
  const load = (opts && opts.load) || ((u) => import(u));
  const delay = opts && opts.delay != null ? opts.delay : 1500;
  return load(url).catch((e) => {
    if (!fetchFailed(e)) throw e;
    const again = url + (url.includes('?') ? '&' : '?') + 'retry=' + Date.now().toString(36);
    return new Promise((r) => setTimeout(r, delay)).then(() => load(again));
  });
}

// ------------------------------------------------------------- card files

// What this PAGE has loaded, kept on the window rather than in a module:
// an update serves Morph's modules from a new URL, which runs them again
// without a reload, and a module-level record starts empty while the
// browser still holds every element the old one defined. Reading that as
// "never loaded" is how one card file defined twice was filed as a fault
// once per card.
export function cardPage(root = globalThis) {
  if (!root.__morphCardPage) {
    root.__morphCardPage = { versions: new Map(), inflight: new Map(), redefined: new Set(), reported: new Set(), guarded: false };
  }
  return root.__morphCardPage;
}

// A custom element is defined once per page, and a card file that runs
// again (a new version, or Morph's own modules loaded again) asks again.
// The browser answers that by throwing, which stops the rest of the file:
// so a second define of a name that is already there is skipped and
// remembered, and the element already registered goes on drawing.
export function guardDefine(registry = globalThis.customElements, page = cardPage()) {
  if (!registry || page.guarded || registry.__morphGuarded) return;
  const define = registry.define.bind(registry);
  registry.define = (name, cls, opts) => {
    if (registry.get(name)) { page.redefined.add(String(name)); return; }
    return define(name, cls, opts);
  };
  registry.__morphGuarded = true;
  page.guarded = true;
}

export const REDEFINED = /already been (used|defined)|already defined/i;

// Load one card file (`start()` imports it): once per version per page, sharing an import that is
// already in flight, and trying a dropped fetch once more. Answers what
// happened — 'loaded', 'changed' (a newer file whose elements this page
// already has: it shows after a reload) or 'same' — and throws only for a
// file that really failed.
// A registry row by id, read only off the object's OWN keys: an id is
// somebody's text, and "constructor" or "toString" otherwise reads one of
// Object.prototype's functions back as the row (#332).
export function own(obj, key) {
  return obj && key != null && Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : undefined;
}

export function cardUrl(base, name, v) {
  return `${base}/${encodeURIComponent(name)}?v=${v}`;
}

export function loadCard(name, v, url, start, page = cardPage()) {
  if (page.inflight.has(url)) return page.inflight.get(url);
  const before = page.versions.get(name);
  if (before === v) return Promise.resolve('same');
  const seen = page.redefined.size;
  const job = Promise.resolve().then(start).then(
    () => (before != null && page.redefined.size > seen ? 'changed' : 'loaded'),
    (e) => {
      if (REDEFINED.test(String((e && e.message) || e))) return before != null ? 'changed' : 'loaded';
      throw e;
    }).then((r) => { page.versions.set(name, v); return r; })
    .finally(() => page.inflight.delete(url));
  page.inflight.set(url, job);
  return job;
}

// What a failed card file is reported as: the cause, with the file's own
// name and address taken out, so five cards failing for one reason are
// one fault rather than five.
export function cardFailure(e) {
  if (fetchFailed(e)) return 'Card code could not be fetched';
  const said = String((e && e.message) || e || '').replace(/\S*\/morph_cards\/\S*/g, '').replace(/\s+/g, ' ').trim();
  return `Card code failed to load: ${said || 'unknown error'}`;
}

// ------------------------------------------------------------- the Ask bar

// Words that ask for a change to the DASHBOARD rather than a question or a
// command for the house: a change verb, then something the page is made
// of. Two narrowings, because the house's own devices share the page's
// nouns: a noun used as the name of a thing ("the card table lamp", "the
// chart room light") is not the page; and a device command ("turn on…",
// "dim…", "open…") is the house's unless it names the page outright.
const CHANGE_VERB = /\b(add|remove|delete|hide|show(?! me\b)|move|put|rename|make|change|resize|swap|replace|get rid of|bring back|restore|reorder|group|split|merge|drop|take (?:out|off|away))\b/i;
const PAGE_NOUN = /\b(card|cards|tile|tiles|section|sections|dashboard|greeting|header|story|coming up|timeline|scenes? line|layout|column|columns|widget|chart|graph|morph|this page|the page|screen)\b(?!\s+(?:table|tables|room|rooms|reader|readers|game|games|lamp|lamps|light|lights|shelf|desk|player|printer)\b)/i;
const DEVICE_COMMAND = /^\s*(?:please\s+)?(?:turn\s+(?:on|off|up|down)|switch\s+(?:on|off)|dim|brighten|open|close|lock|unlock|start|stop|play|pause|set|run|arm|disarm)\b/i;
const LOVELACE = /\blovelace\b/i;
const PAGE_ITSELF = /\b(dashboard|morph|this page|the page|layout)\b/i;

export function isDashChange(q) {
  q = String(q || '');
  const verb = CHANGE_VERB.exec(q);
  if (!verb) return false;
  if (!PAGE_NOUN.test(q.slice(verb.index))) return false;
  if (DEVICE_COMMAND.test(q) && !PAGE_ITSELF.test(q)) return false;
  // A Lovelace dashboard is Home Assistant's, not Morph's page: the
  // request goes to brAIn, which changes it with brain.update_dashboard,
  // rather than to a Tell about /config/morph.
  if (LOVELACE.test(q)) return false;
  return true;
}

// The context the house's conversation agent is given with an Ask: it
// cannot write Morph's files, so it must never say it changed Morph's page
// (house report: "it says it's making changes, but none of them are
// applied"). A Lovelace dashboard is a different thing it CAN change, and
// a sentence that said "you cannot change the dashboard" was read as
// "brAIn can't change config" about Lovelace too.
export const ASK_CONTEXT = 'This question comes from the Ask bar on Morph, the house’s dashboard. Morph’s own page is changed with Morph’s Tell, not from here: if the person asks for a change to Morph’s page, say so (hold the thing in Edit, or press “Change the dashboard instead”) and do not claim to have changed it. A Lovelace dashboard is different: when you can act, change it with get_dashboard and call_service brain.update_dashboard (backed up first).';

// ---------------------------------------------------------------- claims
// A sentence brAIn wrote about a door, lock or garage (the situation line, a
// case's claim) was written before the state it describes moved: it said a
// lock was unlocked beside a lock that read locked, and told the owner to
// close a garage that was closed (#719, #734). Each sentence is checked
// against the entities as they are NOW, every time the story is drawn.
//
// Only what a sentence ASSERTS about now is checked: "is unlocked", "is
// still open", "left open", "close the garage", "all doors are locked". A
// noun is not a claim ("the front door lock battery is low" says nothing
// about whether it is locked), a battery, offline or health sentence is never
// one, a request or a question is not one, and a sentence that tells the
// past ("was unlocked at 3 pm, now locked") is judged only by where it ends.
// "Locked"/"unlocked" is judged by locks only and "open"/"closed" by door,
// window and garage contacts and covers only: they are two facts.
//
// The two directions are not alike. A warning ("is unlocked", "close the
// garage") goes only when EVERYTHING it could be about says otherwise; an
// ambiguous one, or one about nothing the house can see, stays, because a
// true warning is never hidden. A reassurance ("is locked", "everything is
// shut") goes when ANYTHING it covers is unlocked or open, because that is
// the direction that protects the house. A sentence of two claims loses only
// the clause that no longer holds.
const CLAIM_GENERIC = new Set(['lock', 'locks', 'door', 'doors', 'sensor', 'contact', 'opening', 'cover', 'window', 'windows', 'the', 'a', 'an', 'garage', 'gate', 'deadbolt', 'smart', 'entry']);
const CLAIM_NOUNS = [['garage', /\bgarages?\b/i], ['window', /\bwindows?\b/i], ['gate', /\bgates?\b/i], ['door', /\bdoors?\b/i]];
// What makes a clause no claim about now at all.
const NOT_STATE = /\b(?:batter(?:y|ies)|offline|unavailable|unreachable|not\s+responding|signal|firmware|update|health|disconnected|connection|jammed|stuck)\b/i;
const NOT_ASSERTED = /\?|\b(?:if|whether|check|make\s+sure|ensure|confirm|verify|remember)\b/i;
const PAST = /\b(?:was|were|had)\b(?!\s+(?:left|still)\b)|\b(?:earlier|ago|yesterday|last\s+(?:night|evening|week))\b|\bat\s+\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)|\bat\s+\d{1,2}:\d\d\b/i;
// A state asserted now: a present verb, then the state.
const ASSERT = /\b(?:is|are|isn['’]t|aren['’]t|remains?|stays?|still|now|left|been|sits?|stands?)\b\s+(?:(?:still|now|currently|wide|all|both|fully)\s+)*(not\s+)?(unlocked|locked|open|ajar|closed|shut|secured?)\b|['’]s\s+(?:(?:still|now|wide)\s+)*(not\s+)?(unlocked|locked|open|ajar|closed|shut|secured?)\b/gi;
const IMPERATIVE = /\b(close|shut|lock)\s+(?:the|your|that|this|up)\b/gi;
const UNIVERSAL = /\b(?:all|every|everything|each|both|the\s+house|the\s+home|whole\s+house)\b/i;
const NONE_OF = /\b(?:no|nothing|none|neither)\b/i;
const VERB = /\b(?:is|are|was|were|isn['’]t|aren['’]t|has|have|had|remains?|stays?|left|close|shut|lock|unlock|opened|detects?|detected|found|needs?|should|must|will|can|running|playing|done)\b|['’]s\b/i;
const CONTINUES = /^(?:it|they|this|that|which|who|so|then|should|must|needs?|is|are|was|were|has|have|had|now|still|please)\b/i;
const DETERMINER = /^(?:the|a|an|your|my|our|every|all|nothing|no|each|both|it)\b/i;
const POINTS_BACK = /^(?:please\s+)?(?:(?:close|shut|lock|secure|check)\s+(?:it|them|that|this)\b|(?:it|they|that)\s+(?:is|are|should|needs?)\b)/i;
const SPLIT = /(\s*[,;]\s*(?:and|but|while|whereas|yet)?\s*|\s+(?:and|but|while|whereas|yet)\s+)/i;

function claimEntities(states) {
  const out = [];
  Object.values(states || {}).forEach((st) => {
    if (!st || !st.entity_id) return;
    const d = domainOf(st.entity_id); const a = st.attributes || {}; const dc = a.device_class || '';
    const name = String(a.friendly_name || st.entity_id.split('.')[1].replace(/_/g, ' '));
    const tokens = name.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w && !CLAIM_GENERIC.has(w));
    if (d === 'lock') {
      out.push({ kind: 'lock', classes: ['door'], tokens, safe: st.state === 'locked', bad: ['unlocked', 'unlocking', 'open', 'opening', 'jammed'].includes(st.state) });
    } else if (d === 'binary_sensor' && !dc) {
      // A contact sensor nobody gave a device class is still what a line
      // means when the line NAMES it ("Binary sensor 200 is open"): it can
      // confirm or clear that line, and is never part of "everything".
      out.push({ kind: 'open', classes: ['door', 'window', 'garage', 'gate'], tokens, weak: true, safe: st.state === 'off', bad: st.state === 'on' });
    } else if (d === 'cover' || (d === 'binary_sensor' && ['door', 'garage_door', 'window', 'opening'].includes(dc))) {
      const text = `${dc} ${name}`; let classes = [];
      if (/garage/i.test(text)) classes = ['garage', 'door'];
      else if (/window/i.test(text)) classes = ['window'];
      else if (/gate/i.test(text)) classes = ['gate'];
      else if (/door|opening/i.test(text)) classes = ['door'];
      if (!classes.length) return;
      const cover = d === 'cover';
      out.push({ kind: 'open', classes, tokens, safe: cover ? st.state === 'closed' : st.state === 'off', bad: cover ? ['open', 'opening', 'closing'].includes(st.state) : st.state === 'on' });
    }
  });
  return out;
}

// The claims one clause makes about now: [{kind, unsafe, all, at}].
function claimsOf(g) {
  if (NOT_STATE.test(g) || NOT_ASSERTED.test(g)) return [];
  const out = [];
  const add = (word, neg, at) => {
    const w = word.toLowerCase();
    if (/^secured?$/.test(w)) { if (!neg) out.push({ kind: 'lock', unsafe: false, at }, { kind: 'open', unsafe: false, at }); return; }
    const kind = /lock/.test(w) ? 'lock' : 'open';
    let unsafe = ['unlocked', 'open', 'ajar'].includes(w);
    if (neg) unsafe = !unsafe;
    out.push({ kind, unsafe, at });
  };
  let m;
  ASSERT.lastIndex = 0;
  while ((m = ASSERT.exec(g))) {
    const verb = m[0].toLowerCase();
    const neg = !!(m[1] || m[3]) || /n['’]t\b/.test(verb);
    add(m[2] || m[4], neg, m.index);
  }
  IMPERATIVE.lastIndex = 0;
  while ((m = IMPERATIVE.exec(g))) out.push({ kind: m[1].toLowerCase() === 'lock' ? 'lock' : 'open', unsafe: true, at: m.index });
  const all = UNIVERSAL.test(g);
  const none = NONE_OF.test(g);
  out.forEach((c) => {
    // "Nothing is open", "no door is unlocked": a reassurance about all.
    if (none && c.unsafe) { c.unsafe = false; c.all = true; } else c.all = all && !c.unsafe;
  });
  out.sort((x, y) => x.at - y.at);
  // A clause that tells the past is judged by where it ends.
  return PAST.test(g) ? out.slice(-1) : out;
}

// What a claim could be about, among the house's entities.
function covered(c, g, ents) {
  const nouns = CLAIM_NOUNS.filter(([, re]) => re.test(g)).map(([n]) => n);
  let pool = ents.filter((e) => e.kind === c.kind);
  if (c.kind === 'open' && nouns.length) {
    const want = nouns.includes('garage') ? ['garage', ...nouns.filter((n) => n !== 'door')] : nouns;
    pool = pool.filter((e) => e.classes.some((k) => want.includes(k)));
  }
  const w = new Set(g.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean));
  const named = pool.filter((e) => e.tokens.length && e.tokens.every((t) => w.has(t)));
  // A sensor with no class counts only when the line names it.
  pool = pool.filter((e) => !e.weak);
  if (c.all) return pool;
  if (named.length) return named;
  const some = pool.filter((e) => e.tokens.some((t) => w.has(t)));
  if (some.length) return some;
  const about = c.kind === 'lock' ? /\b(?:doors?|locks?|deadbolts?)\b/i.test(g) : nouns.length > 0;
  return about ? pool : [];
}

function holds(c, g, ents) {
  const of = covered(c, g, ents);
  if (!of.length) return true;
  return c.unsafe ? !of.every((e) => e.safe) : !of.some((e) => e.bad);
}

// One sentence as clauses: split at "and", "but", commas and semicolons,
// then a clause that continues the one before ("it should be closed", "now
// locked") goes with it, and a fragment with no verb ("The front" of "the
// front and back doors") goes with the clause after it.
function clausesOf(body) {
  const bits = body.split(SPLIT);
  let parts = [{ sep: '', text: bits[0] }];
  for (let i = 1; i < bits.length; i += 2) parts.push({ sep: bits[i], text: bits[i + 1] || '' });
  const back = [];
  parts.forEach((p) => {
    const prev = back[back.length - 1];
    if (prev && CONTINUES.test(p.text.trim())) prev.text += p.sep + p.text;
    else back.push({ ...p });
  });
  const out = [];
  for (let i = 0; i < back.length; i++) {
    const p = back[i]; const next = back[i + 1];
    if (next && !VERB.test(p.text) && (p.text.trim().split(/\s+/).length <= 3 || !DETERMINER.test(next.text.trim()))) {
      next.text = p.text + next.sep + next.text; next.sep = p.sep; continue;
    }
    out.push(p);
  }
  return out;
}

export function checkDoorClaims(text, hass) {
  const ents = claimEntities(hass && hass.states);
  const sentences = String(text || '').trim().split(/(?<=[.!?])\s+/).filter(Boolean);
  const kept = [];
  // What follows a dropped line and only points back at it ("Close it before
  // bed.") has nothing left to point at, so it goes with it.
  let cut = false;
  sentences.forEach((s) => {
    const m = s.match(/^([\s\S]*?)([.!?]*)$/); const body = m[1]; const end = m[2];
    const parts = clausesOf(body);
    let gone = cut;
    const keep = parts.filter((p) => {
      const ok = claimsOf(p.text).every((c) => holds(c, p.text, ents)) && !(gone && POINTS_BACK.test(p.text.trim()));
      gone = !ok;
      return ok;
    });
    cut = !keep.length || keep.length < parts.length ? gone : false;
    if (keep.length === parts.length) { kept.push(s); return; }
    if (!keep.length) return;
    let out = keep.map((p, i) => (i ? p.sep : '') + p.text).join('').trim();
    out = out.charAt(0).toUpperCase() + out.slice(1);
    kept.push(out + (end || '.'));
  });
  return kept.join(' ');
}

// The locks that are unlocked now, as clauses, for a line that would
// otherwise say everything is locked.
export function unlockedLocks(hass) {
  return Object.values((hass && hass.states) || {}).filter((st) => st && domainOf(st.entity_id) === 'lock' && ['unlocked', 'unlocking', 'open', 'jammed'].includes(st.state))
    .map((st) => `${friendly(hass, st.entity_id)} is ${st.state === 'jammed' ? 'jammed' : st.state === 'open' ? 'open' : 'unlocked'}`);
}

// ---------------------------------------------------------------- old readings
// #688: the weather card said 57° while the outdoor chip beside it said
// 62.6°, drawn like a live reading. Home Assistant's frontend states carry
// `last_changed` and `last_updated` only, and a
// steady reading's `last_updated` is as old as a dead sensor's, so age alone
// says nothing. The panel marks an outdoor reading only when two things it
// has disagree: the reading is more than a degree off the weather entity's
// temperature AND its value has not changed for STALE_MIN minutes. It then
// says what was measured — the value has not changed since a time — and is
// dimmed; it does not claim the sensor is dead.
export const STALE_MIN = 30;
const OUTDOOR = /\b(?:outside|outdoors?|exterior|external|garden|yard|porch|patio|deck|balcony|driveway|weather)\b/i;
export function outdoorStale(hass, eid, now) {
  const S = (hass && hass.states) || {}; const st = S[eid];
  if (!st || domainOf(eid) !== 'sensor') return '';
  const a = st.attributes || {};
  if (a.device_class !== 'temperature' && !/°/.test(a.unit_of_measurement || '')) return '';
  if (!OUTDOOR.test(`${a.friendly_name || ''} ${eid.split('.')[1].replace(/_/g, ' ')}`)) return '';
  const v = parseFloat(st.state);
  const w = Object.values(S).find((x) => x && domainOf(x.entity_id) === 'weather' && x.attributes && isFinite(parseFloat(x.attributes.temperature)));
  if (!isFinite(v) || !w) return '';
  if (Math.abs(v - parseFloat(w.attributes.temperature)) <= 1) return '';
  const t = Date.parse(st.last_changed || st.last_updated || '');
  if (!t || ((now || Date.now()) - t) / 60000 < STALE_MIN) return '';
  return `unchanged since ${clock(t)}`;
}

// ---------------------------------------------------------------- Minecraft
// What a tile for the BRUH Minecraft server says: whether it answers, and
// who is playing. Only the Online sensor and the Players online sensor stand
// for the server; every other entity of it (version, last backup, buttons)
// keeps its own value. The siblings are found through the entity registry's
// device, else by the integration's own prefix.
export function minecraftStatus(hass, eid) {
  const reg = (hass && hass.entities) || {}; const own = reg[eid];
  const role = /^binary_sensor\..*_online$/.test(eid || '') ? 'online' : /^sensor\..*_players_online$/.test(eid || '') ? 'players' : '';
  if (!role) return null;
  const S = hass.states; let sib;
  if (own) {
    if (own.platform !== 'bruh_minecraft') return null;
    const same = Object.keys(reg).filter((e) => reg[e].device_id && reg[e].device_id === own.device_id);
    sib = (dom, suffix) => same.find((e) => e.startsWith(dom + '.') && e.endsWith(suffix));
  } else {
    if (!/^(binary_sensor|sensor)\.bruh_minecraft_server_/.test(eid)) return null;
    sib = (dom, suffix) => `${dom}.bruh_minecraft_server${suffix}`;
  }
  const on = S[sib('binary_sensor', '_online')];
  if (!on || on.state !== 'on') return 'Offline';
  const pl = S[sib('sensor', '_players_online')];
  const n = pl ? parseInt(pl.state, 10) : NaN;
  const names = pl && Array.isArray(pl.attributes.players) ? pl.attributes.players.map((p) => (p && p.name) || p).filter(Boolean) : [];
  const tps = S[sib('sensor', '_tps_1m')]; const t = tps ? parseFloat(tps.state) : NaN;
  const who = !pl || isNaN(n) ? 'Online' : n <= 0 ? 'Online · nobody playing' : `${n} playing${names.length ? ': ' + names.join(', ') : ''}`;
  return who + (isFinite(t) ? ` · ${Math.round(t)} TPS` : '');
}

// ---------------------------------------------------------------- dead probes
// #787: a soil probe fell from 47% to a flat 0% and was drawn as bone-dry
// soil. Soil dries over hours; a moisture reading that lands on exactly 0
// straight from 10 or more (the reading before it, or any within the 15
// minutes before it) is a probe that stopped answering, was pulled out of the
// soil or lost its battery. Soil that dried down through the low numbers to 0
// is a real 0% and is left alone. `pts` is [time, value] in time order, the
// last one now.
export const CLIFF_FROM = 10;
const CLIFF_MS = 15 * 60000;
export function isMoisture(st) {
  if (!st || domainOf(st.entity_id) !== 'sensor') return false;
  const a = st.attributes || {};
  if (a.unit_of_measurement && a.unit_of_measurement !== '%') return false;
  return a.device_class === 'moisture' || /\b(soil|moisture)\b/i.test(`${a.friendly_name || ''} ${String(st.entity_id).replace(/_/g, ' ')}`);
}
export function fellToZero(pts) {
  const v = (pts || []).filter((p) => p && isFinite(p[1]));
  if (!v.length || v[v.length - 1][1] !== 0) return false;
  let i = v.length - 1;
  while (i > 0 && v[i - 1][1] === 0) i -= 1;
  if (i === 0) return false;
  const t0 = v[i][0];
  for (let j = i - 1; j >= 0; j -= 1) {
    if (j < i - 1 && t0 - v[j][0] > CLIFF_MS) break;
    if (v[j][1] >= CLIFF_FROM) return true;
  }
  return false;
}
// The probe's battery, as its own sensor says it (a voltage or a percentage),
// from the same device, else from an entity named like it, else its own
// battery_level attribute: "battery 1.6 V".
export function batteryOf(hass, eid) {
  const S = (hass && hass.states) || {}; const reg = (hass && hass.entities) || {};
  const own = reg[eid]; const stem = String(eid).split('.')[1].replace(/_?(soil_)?moisture$/, '');
  const ids = own && own.device_id ? Object.keys(reg).filter((e) => e !== eid && reg[e].device_id === own.device_id)
    : stem ? Object.keys(S).filter((e) => e !== eid && domainOf(e) === 'sensor' && e.split('.')[1].startsWith(stem)) : [];
  const b = ids.map((e) => S[e]).find((s) => s && isFinite(parseFloat(s.state)) && /battery/i.test(`${s.entity_id} ${s.attributes.friendly_name || ''} ${s.attributes.device_class || ''}`));
  if (b) return 'battery ' + fmt(b.state, b.attributes.unit_of_measurement || '');
  const lvl = S[eid] && S[eid].attributes && S[eid].attributes.battery_level;
  return lvl != null && isFinite(Number(lvl)) ? `battery ${lvl}%` : '';
}
// What a moisture tile says instead of 0% when its probe went dead, or ''.
export function probeOffline(hass, eid, pts) {
  const st = hass && hass.states && hass.states[eid];
  if (!isMoisture(st) || !fellToZero(pts)) return '';
  const bat = batteryOf(hass, eid);
  return 'Sensor offline · check the probe' + (bat ? ' · ' + bat : '');
}
