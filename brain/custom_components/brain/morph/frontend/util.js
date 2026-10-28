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
