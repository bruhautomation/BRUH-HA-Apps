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

const I = (base, part, cls, origin) => ({ base, part, cls: cls || '', origin: origin || '50% 50%' });
export const ICONS = {
  bulb: I('M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z', 'M12 -.5v1.6M4.2 3.2l1.1 1.1M19.8 3.2l-1.1 1.1M1.5 10h1.6M20.9 10h1.6', 'breathe'),
  group: I('M7 18h4M8 21h2M9 4a4.5 4.5 0 0 0-3 7.9c.5.5.8 1.2.8 2.1h4.4c0-.9.3-1.6.8-2.1A4.5 4.5 0 0 0 9 4zM17 8a3 3 0 0 0-2 5.3c.4.4.5.8.5 1.4h3c0-.6.1-1 .5-1.4A3 3 0 0 0 17 8z', 'M9 .5v1.4M17 5v1.2', 'breathe'),
  fan: I('M12 13.6a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z', 'M12 10.4C12 6 9.3 3 7.4 4s.1 5 4.6 6.4M13.6 12c4.4 0 7.4-2.7 6.4-4.6s-5-.1-6.4 4.6M12 13.6c0 4.4 2.7 7.4 4.6 6.4s-.1-5-4.6-6.4M10.4 12C6 12 3 14.7 4 16.6s5 .1 6.4-4.6', 'spin'),
  blinds: I('M3 3h18M5 3v18M19 3v18', 'M5 7h14M5 11h14M5 15h14M5 19h14', '', '50% 0%'),
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
  const op = o.partOpacity != null ? `opacity:${o.partOpacity};` : '';
  return `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="color:${color}"><path d="${ic.base}"></path><g class="${cls}" style="transform-box:view-box;transform-origin:${ic.origin};${tf}${dur}${op}transition:transform .6s cubic-bezier(.25,1,.3,1),opacity .4s ease"><path d="${ic.part}"></path></g></svg>`;
}

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
