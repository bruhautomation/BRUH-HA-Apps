// Morph's cards — one per Home Assistant domain (docs/design/morph-ui.md §3).
//
// One grammar everywhere: TAP does the main thing, SLIDE sets a level, HOLD
// opens the card in place with its options and its history. One control,
// one place: brightness lives on the strip and is never repeated in the
// opened card. Each type is a small table entry the panel reads:
//
//   item    layout: span, grow, dir ('side' grows sideways, 'down' grows
//           down), want (columns when open), full (fills its row), hk (a
//           row only holds things of one kind)
//   accent  the device's colour — the opened card and its history take it
//   face    the compact face, as markup
//   more    what opens in place (options, then history)
//   tap     the main thing, as a service call, or null to open
//   slide   {get, call(pct)} for things with a level
//
// Anything a person presses inside a card carries data-act; the panel
// dispatches it. `svc` is a service call described in the markup, so a new
// control is markup, not a new handler.

import { STATUS } from './styles.js';
import { esc, mix, clamp, lightColor, lightTone, fmt, since, clock, ago, icon, friendly, shortName, UNAVAILABLE, domainOf, outdoorStale, minecraftStatus, lastSeen, isMoisture, probeOffline } from './util.js';
import * as history from './history.js';

const STRIP = { span: 1, grow: 2, dir: 'side', want: 3, hk: 's' };
const svcBtn = (label, domain, service, data, opts) => {
  const o = opts || {};
  return `<button type="button" class="wd ${o.cls || ''}" data-ctl="1" data-act="svc" data-domain="${esc(domain)}" data-service="${esc(service)}" data-data="${esc(JSON.stringify(data || {}))}"${o.pressed != null ? ` aria-pressed="${o.pressed}"` : ''}${o.confirm ? ` data-confirm="${esc(o.confirm)}"` : ''}>${esc(label)}</button>`;
};
const words = (items) => `<div class="row" style="flex-wrap:wrap;gap:0 18px">${items.join('')}</div>`;
const blockLabel = (t) => `<span class="label">${esc(t)}</span>`;
const pct = (st) => {
  const a = (st && st.attributes) || {};
  if (a.brightness != null) return Math.round(a.brightness / 2.55);
  return st && st.state === 'on' ? 100 : 0;
};
const off = (st) => !st || UNAVAILABLE.includes(st.state);
// A button, a scene or an input button that was never pressed has the state
// `unknown` (its state is when it was last pressed), and it is still a
// button: only `unavailable` or missing makes it one that cannot be pressed.
const PRESSABLE = ['button', 'input_button', 'scene'];
const dead = (ctx) => (PRESSABLE.includes(domainOf(ctx.card.entity)) ? !ctx.st || ctx.st.state === 'unavailable' : off(ctx.st));
const fanLevel = (p) => ['Low', 'Low', 'Medium', 'Medium', 'High', 'High'][Math.min(5, Math.floor(p / 20))];

// A binary sensor's two states in its device class's words, as Home
// Assistant's own translations say them (on, off): a connectivity sensor is
// Connected or Disconnected, a door Open or Closed, never "On".
export const BINARY_WORDS = {
  battery: ['Low', 'Normal'], battery_charging: ['Charging', 'Not charging'],
  carbon_monoxide: ['Detected', 'Clear'], cold: ['Cold', 'Normal'],
  connectivity: ['Connected', 'Disconnected'], door: ['Open', 'Closed'],
  garage_door: ['Open', 'Closed'], gas: ['Detected', 'Clear'], heat: ['Hot', 'Normal'],
  light: ['Light detected', 'No light'], lock: ['Unlocked', 'Locked'], moisture: ['Wet', 'Dry'],
  motion: ['Detected', 'Clear'], moving: ['Moving', 'Not moving'], occupancy: ['Detected', 'Clear'],
  opening: ['Open', 'Closed'], plug: ['Plugged in', 'Unplugged'], power: ['On', 'Off'],
  presence: ['Home', 'Away'], problem: ['Problem', 'OK'], running: ['Running', 'Not running'],
  safety: ['Unsafe', 'Safe'], smoke: ['Detected', 'Clear'], sound: ['Detected', 'Clear'],
  tamper: ['Tampering detected', 'Clear'], update: ['Update available', 'Up-to-date'],
  vibration: ['Detected', 'Clear'], window: ['Open', 'Closed'],
};

// One wording for a state everywhere: "Armed home", "Connected",
// "Unavailable", "Missing". With `hass`, Home Assistant's own words for it
// (`formatEntityState`: the device class's, in the person's language), so a
// card says what Home Assistant's own says.
export function stateWord(st, hass) {
  if (!st) return 'Missing';
  if (st.state === 'unavailable') return 'Unavailable';
  if (st.state === 'unknown') return 'Unknown';
  if (hass && typeof hass.formatEntityState === 'function') {
    try { const t = hass.formatEntityState(st); if (t && typeof t === 'string') return t; } catch (e) { /* its own words below */ }
  }
  const dc = st.attributes && st.attributes.device_class;
  if (domainOf(st.entity_id || '') === 'binary_sensor' && (st.state === 'on' || st.state === 'off')) {
    const w2 = BINARY_WORDS[dc] || ['On', 'Off'];
    return st.state === 'on' ? w2[0] : w2[1];
  }
  const w = String(st.state).replace(/_/g, ' ');
  return w ? w[0].toUpperCase() + w.slice(1) : '';
}

// A fan with a speed to set: SET_SPEED (1) and a step finer than on/off.
export const fanHasSpeed = (st) => {
  const a = (st && st.attributes) || {};
  return !!(a.percentage != null && (a.supported_features == null || (a.supported_features & 1)) && !(a.percentage_step >= 100));
};

// A light's colour, pulled a little toward the theme's ink, so a yellow or
// white bulb still reads on the light theme.
const lightAccent = (st) => `color-mix(in oklab, ${lightColor(st)} 82%, var(--lpull))`;

// The prototype's tones (docs/design/morph-ui.html): a fill runs strong at
// the left and fades toward the thumb, the strip itself is untinted (only a
// switch tints its strip, because a switch has no fill to show it is on), and
// the status line is quiet text — the colour lives in the fill and the icon.
// What a pressable word beside a state looks like: a small outlined button,
// so it is never read as one more word of the state (#756 #765).
const actSvg = (inner, fill) => `<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="${fill ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ACT_ICONS = {
  lock: actSvg('<rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path>'),
  unlock: actSvg('<rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 7.5-1.5"></path>'),
  open: actSvg('<path d="M6 15l6-6 6 6"></path>'),
  close: actSvg('<path d="M6 9l6 6 6-6"></path>'),
  stop: actSvg('<rect x="7" y="7" width="10" height="10" rx="2"></rect>', true),
  start: '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5l13 7.5-13 7.5z"></path></svg>',
  dock: '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7 9 7M5.5 9.5V20h13V9.5M10 20v-5h4v5"></path></svg>',
};
// A status line is ONE line, and what it says is chosen, not clipped: the
// facts come in the order that matters and each later one carries the width
// its tile needs to show it whole (`w<px>`, shown by styles.js's STATUS
// rules). A one-column tile says "Unavailable"; a wider one adds when it was
// last seen. `val` is a string, or the parts of one; `sep` joins them and
// `action` says a word of the tile's own sits beside the line.
export function statusHtml(val, o) {
  const opt = o || {};
  const parts = (Array.isArray(val) ? val : [val]).map((p) => (p == null ? '' : String(p))).filter(Boolean);
  if (parts.length < 2) return esc(parts[0] || '');
  const sep = opt.sep == null ? ' \u00b7 ' : opt.sep;
  let n = 0;
  return `${parts.map((p, i) => {
    const text = (i ? sep : '') + p; n += text.length;
    if (!i) return `<i>${esc(text)}</i>`;
    const need = Math.min(STATUS.max, Math.max(STATUS.min, Math.ceil((n * STATUS.charPx + STATUS.linePx + (opt.action ? STATUS.actionPx : 0)) / STATUS.step) * STATUS.step));
    return `<i class="w${need}">${esc(text)}</i>`;
  }).join('')}`;
}

export function stripFace(o) {
  const active = !!o.active;
  const accent = o.accent;
  const fillW = clamp(o.pct == null ? 0 : o.pct, 0, 100);
  const fa = o.fillA || mix(accent, 34), fb = o.fillB || mix(accent, 12);
  let layer = '';
  if ((o.kind === 'fill' || o.kind === 'slats') && fillW > 0) {
    layer = `<div aria-hidden="true" class="fill" style="width:${fillW}%;background:linear-gradient(90deg, ${fa}, ${fb})"></div>`;
    // A blind's slats are drawn over the part that is OPEN: closed is plain.
    // An expanded group's stacked rows skip the lines (plainSlats): there they
    // ran together and hid where one blind ended and the next began.
    if (o.kind === 'slats') { if (!o.plainSlats) layer += `<div aria-hidden="true" class="slats" style="width:${fillW}%"></div>`; }
    else layer += `<div aria-hidden="true" class="thumb" style="left:${fillW}%"></div>`;
  } else if (o.kind === 'lanes') {
    layer = `<div aria-hidden="true" class="lanes">${(o.lanes || []).map((l) => `<span class="lane" style="background:${l.on ? mix(l.color, 5) : 'transparent'}"><span style="width:${l.on ? Math.max(3, l.pct) : 0}%;background:linear-gradient(90deg, ${mix(l.color, 34)}, ${mix(l.color, 14)});box-shadow:inset -1.5px 0 0 ${l.on ? mix(l.color, 70) : 'transparent'}"></span></span>`).join('')}</div>`;
  }
  const isSwitch = o.kind === 'switch' && !o.action;
  // A switch that cannot be reached draws no toggle, so its word has the room.
  const sw = isSwitch && !o.dead ? `<span aria-hidden="true" class="track" style="background:${active ? mix(accent, 30) : 'transparent'};box-shadow:inset 0 0 0 1px ${active ? 'transparent' : 'var(--line2)'}"><span class="knob" style="left:${active ? 15 : 3}px;background:${active ? accent : 'var(--quiet)'}"></span></span>` : '';
  const valColor = o.valColor || (isSwitch ? (active ? accent : 'var(--muted)') : active ? 'var(--text)' : 'var(--quiet)');
  const bg = o.stripBg || (isSwitch && active ? mix(accent, 10) : 'transparent');
  return `<div class="strip" style="box-shadow:inset 0 0 0 1px ${active ? mix(accent, o.edgeMix || 30) : 'var(--line)'};background-color:${bg}">${layer}
<div class="sline">${icon(o.icon, { color: o.iconColor || (active ? accent : 'var(--quiet)'), active: o.iconActive != null ? o.iconActive : active, dur: o.dur, transform: o.iconTransform, partOpacity: o.partOpacity })}
<span class="nv${o.two ? ' two' : ''}"><b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(o.name)}</b><span class="vs" style="color:${valColor}">${statusHtml(o.val, { sep: o.sep, action: !!o.action })}</span></span><span class="flex1"></span>${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ''}${o.action ? `<span class="actword${o.armed ? ' armed' : ''}${o.actIcon && !o.armed ? ' hasicon' : ''}" style="--ac:${o.actionColor || accent}" aria-hidden="true"${o.armed ? '' : ` data-name="${esc(o.action + (o.actNoun ? ' ' + o.actNoun : ''))}"`}>${o.actIcon && !o.armed ? ACT_ICONS[o.actIcon] : ''}<span class="acttext">${esc(o.armed || o.action)}${o.actNoun && !o.armed ? `<span class="actnoun"> ${esc(o.actNoun)}</span>` : ''}</span></span>` : sw}</div></div>`;
}

function histBlock(ctx, label) {
  const h = history.block(ctx.hass, ctx.card, ctx.st, ctx.H, ctx.accent, ctx.name);
  return h ? (label === false ? h : `${blockLabel(label || 'History')}${h}`) : '';
}

// ------------------------------------------------------------------ light

// Colour is one slim indexed track (house change): the whites — Night (the
// light's warmest), 2700, 3750, 4200 and 5000 K — then the colours, each a
// faint point on the track, so where a point sits says what it is. A tap
// lands on the nearest point; sliding snaps from white to white and runs
// continuously through the colours. One thumb shows the light's colour now
// and glides to wherever it is sent.
const WHITES = [['Night', 0, '#ff9a4a'], ['2700', 2700, '#ffbd7a'], ['3750', 3750, '#ffdab0'], ['4200', 4200, '#ffe6cb'], ['5000', 5000, '#f3f1fb']];
export const DOT_HUES = [0, 25, 45, 120, 170, 200, 230, 270, 300, 330];
export const hueColor = (h) => `hsl(${Math.round(h)} 82% 61%)`;
const LM_CSS = `<style>.cidx{position:relative;height:44px;margin:-5px 0;touch-action:pan-y;cursor:pointer;user-select:none;-webkit-user-select:none;overflow-x:clip;border-radius:10px}.cidx:focus-visible{outline:2px solid var(--sky);outline-offset:2px}.cidx .trk{position:absolute;left:0;right:0;top:16px;height:12px;border-radius:6px;box-shadow:inset 0 0 0 1px var(--line);transition:transform .35s cubic-bezier(.22,1,.36,1)}.cidx>i{position:absolute;top:50%;width:4px;height:4px;margin:-2px 0 0 -2px;border-radius:50%;background:color-mix(in srgb,var(--bg) 45%,transparent);pointer-events:none}.cidx .thr{position:absolute;left:calc(var(--f) * 100%);top:0;bottom:0;width:0;transition:left .5s cubic-bezier(.22,1,.36,1);pointer-events:none}.cidx .th{position:absolute;top:50%;left:0;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;box-shadow:0 0 0 3px var(--surface),0 1px 3px rgba(0,0,0,.35);transition:width .2s cubic-bezier(.22,1,.36,1),height .2s cubic-bezier(.22,1,.36,1),margin .2s cubic-bezier(.22,1,.36,1),opacity .3s ease,background-color .3s ease}.cidx .th.none{opacity:0}.cidx.drag .thr{transition:left .06s linear}.cspread .cidx .thr{transition:left .38s cubic-bezier(.22,1,.36,1)!important}.cidx.drag .th{opacity:1;width:28px;height:28px;margin:-14px 0 0 -14px;transition:width .2s cubic-bezier(.22,1,.36,1),height .2s cubic-bezier(.22,1,.36,1),margin .2s cubic-bezier(.22,1,.36,1),opacity .2s ease}.cidx .trkw{right:auto;width:calc(var(--wf) * 100%);transition:width .38s cubic-bezier(.22,1,.36,1),transform .35s cubic-bezier(.22,1,.36,1)}.cidx.spec .trkw{border-radius:6px 0 0 6px}.cidx .trkh{left:calc(var(--wf) * 100%);clip-path:inset(0 calc(50% - 6px) 0 calc(50% - 6px) round 6px);opacity:0;transition:left .38s cubic-bezier(.22,1,.36,1),clip-path .38s cubic-bezier(.22,1,.36,1),opacity .2s ease}.cidx.spec .trkh{clip-path:inset(0 0 0 0 round 0 6px 6px 0);opacity:1;border-radius:0 6px 6px 0}.cidx.spec .trkh:first-child{border-radius:6px}.cidx .rbw{position:absolute;top:50%;left:calc((var(--wf) + (1 - var(--wf)) / 2) * 100%);width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:conic-gradient(from 0deg,hsl(0 82% 61%),hsl(60 82% 61%),hsl(120 82% 61%),hsl(180 82% 61%),hsl(240 82% 61%),hsl(300 82% 61%),hsl(360 82% 61%));box-shadow:0 0 0 1px var(--line);pointer-events:none;transition:left .38s cubic-bezier(.22,1,.36,1),transform .38s cubic-bezier(.22,1,.36,1),opacity .25s ease}.cidx.spec .rbw{opacity:0;transform:scale(.3)}.cidx>i{transition:left .38s cubic-bezier(.22,1,.36,1),opacity .3s ease}.cidx>i.hd{opacity:0}.cidx.spec>i.hd{opacity:1}.reduce .cidx .thr,.reduce .cidx .th,.reduce .cidx .trk{transition:none}@media (prefers-reduced-motion:reduce){.cidx .thr,.cidx .th,.cidx .trk{transition:none}}</style>`;
const HUE_WORDS = ['Red', 'Orange', 'Yellow', 'Green', 'Teal', 'Cyan', 'Blue', 'Purple', 'Magenta', 'Pink'];
// The colour track from a keyboard: arrows step between its points, Home and
// End go to the ends. (A finger or mouse is the panel's.)
let lastHass = null; let keysWired = false;
function wireColorKeys() {
  if (keysWired || typeof document === 'undefined') return;
  keysWired = true;
  document.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    const el = (e.composedPath ? e.composedPath() : []).find((n) => n && n.nodeType === 1 && n.matches('[data-huerow]'));
    if (!el || !lastHass) return;
    e.preventDefault(); e.stopPropagation();
    let pts = []; let names = []; try { pts = JSON.parse(el.dataset.pts); names = JSON.parse(el.dataset.names || '[]'); } catch (x) { return; }
    const n = pts.length; if (!n) return;
    const cur = Number(el.getAttribute('aria-valuenow'));
    const at = isFinite(cur) && el.hasAttribute('aria-valuenow') ? cur : -1;
    const up = e.key === 'ArrowRight' || e.key === 'ArrowUp';
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : up ? Math.min(n - 1, at + 1) : Math.max(0, at < 0 ? 0 : at - 1);
    const p = pts[next];
    if (p[0] === 'r') return;
    lastHass.callService('light', 'turn_on', { entity_id: el.dataset.entity, ...(p[0] === 'k' ? { color_temp_kelvin: p[1] } : { hs_color: [p[1], 100] }) });
    el.setAttribute('aria-valuenow', String(next)); el.setAttribute('aria-valuetext', names[next] || '');
  }, true);
}
function lightMore(ctx, target, st, label) {
  lastHass = ctx.hass; wireColorKeys();
  st = st || ctx.st; const a = (st && st.attributes) || {};
  const modes = a.supported_color_modes || [];
  const color = modes.some((m) => ['hs', 'rgb', 'rgbw', 'rgbww', 'xy'].includes(m));
  const temp = modes.includes('color_temp');
  if (!color && !temp) return '';
  const on = st && st.state === 'on';
  const lo = a.min_color_temp_kelvin || 2200, hi = a.max_color_temp_kelvin || 6500;
  // The points along the track: ['k', kelvin, swatch] then ['h', hue].
  const pts = []; const names = [];
  if (temp) {
    const seen = new Set();
    WHITES.forEach(([nm, kv, sw]) => { const v = Math.round(clamp(kv || lo, lo, hi)); if (!seen.has(v)) { seen.add(v); pts.push(['k', v, sw]); names.push(kv ? `${nm} K` : nm); } });
  }
  const fh = pts.length;
  // Six detents by default: the whites, then a rainbow dot. Landing on the
  // rainbow slides the whites left and opens the whole spectrum in the rest
  // of the row, which stays open until the card folds (house change, Oct 2026).
  const spec = !temp || !!(ctx.spectrum && ctx.spectrum[target]);
  if (color) { if (spec) DOT_HUES.forEach((d, i) => { pts.push(['h', d]); names.push(HUE_WORDS[i]); }); else { pts.push(['r']); names.push('Colors'); } }
  const n = pts.length; const wf = n ? fh / n : 0;
  const col = (p) => (p[0] === 'k' ? p[2] : p[0] === 'h' ? hueColor(p[1]) : '#fff');
  // Where the light is now: the nearest white, or its place among the colours.
  let pos = null; let now = null;
  if (on && a.color_mode === 'color_temp' && temp && a.color_temp_kelvin) {
    let best = 0; pts.forEach((p, i) => { if (p[0] === 'k' && Math.abs(p[1] - a.color_temp_kelvin) < Math.abs(pts[best][1] - a.color_temp_kelvin)) best = i; });
    pos = best; now = col(pts[best]);
  } else if (on && color && a.hs_color && a.hs_color[1] > 25) {
    let h = a.hs_color[0]; if (h > 345) h -= 360;
    if (!spec) pos = fh;
    else {
      const H = DOT_HUES; let k = H.length - 1;
      if (h <= H[0]) k = 0; else for (let i = 0; i < H.length - 1; i++) if (h <= H[i + 1]) { k = i + (h - H[i]) / (H[i + 1] - H[i]); break; }
      pos = fh + k;
    }
    now = hueColor(Math.max(0, h));
  }
  const wstops = WHITES.length && fh ? pts.slice(0, fh).map((p, i) => `${p[2]} ${(((i + 0.5) / fh) * 100).toFixed(2)}%`).join(',') : '';
  const hstops = DOT_HUES.map((d, j) => `${hueColor(d)} ${(((j + 0.5) / DOT_HUES.length) * 100).toFixed(2)}%`).join(',');
  const wdots = pts.slice(0, fh).map((p, i) => `<i style="left:calc(${((i + 0.5) / fh).toFixed(4)} * var(--wf) * 100%)"></i>`).join('');
  const hdots = color ? DOT_HUES.map((d, j) => `<i class="hd" style="left:calc((var(--wf) + ${((j + 0.5) / DOT_HUES.length).toFixed(4)} * (1 - var(--wf))) * 100%)"></i>`).join('') : '';
  const thumb = `<span class="thr" style="--f:${pos == null ? 0.5 : ((pos + 0.5) / n).toFixed(4)}"><span class="th${pos == null ? ' none' : ''}" style="background-color:${now || '#fff'}"></span></span>`;
  const now_i = pos == null ? null : Math.round(pos);
  const row = `<div class="cidx${spec ? ' spec' : ''}" data-huerow="1" data-ctl="1" data-entity="${esc(target)}" data-pts="${esc(JSON.stringify(pts))}" data-names="${esc(JSON.stringify(names))}" role="slider" tabindex="0" aria-label="${esc((label && label !== false ? label : 'Color'))}" aria-valuemin="0" aria-valuemax="${n - 1}"${now_i == null ? '' : ` aria-valuenow="${now_i}" aria-valuetext="${esc(names[now_i] || '')}"`} style="--wf:${wf.toFixed(4)}">${fh ? `<span class="trk trkw" style="background:linear-gradient(90deg,${wstops})"></span>` : ''}${color ? `<span class="trk trkh" style="background:linear-gradient(90deg,${hstops})"></span><b class="rbw"></b>` : ''}${wdots}${hdots}${thumb}</div>`;
  const head = label === false ? '' : blockLabel(label || 'Color');
  return `${head}${LM_CSS}${row}`;
}

const light = {
  item: STRIP,
  accent: (ctx) => (ctx.st && ctx.st.state === 'on' ? lightAccent(ctx.st) : 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on'; const p = ctx.preview != null ? ctx.preview : pct(st);
    const lit = on || ctx.preview > 0;
    return stripFace({ kind: 'fill', icon: /\b(strip|led)\b/i.test(ctx.name || '') ? 'led' : 'bulb', accent: ctx.accent, active: lit, pct: on || ctx.preview != null ? p : 0, name: ctx.name, val: off(st) ? (st ? 'Unavailable' : 'Missing') : lit ? (((st.attributes || {}).supported_color_modes || []).every((m) => m === 'onoff') ? 'On' : [`${p}%`, lightTone(st)]) : 'Off', valColor: lit ? 'var(--muted)' : 'var(--quiet)', hint: ctx.hint });
  },
  more: (ctx) => lightMore(ctx, ctx.card.entity) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'light', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (ctx.st && (ctx.st.attributes.supported_color_modes || []).some((m) => m !== 'onoff')
    ? { get: () => pct(ctx.st), call: (v) => (v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: ctx.card.entity } } : { domain: 'light', service: 'turn_on', data: { entity_id: ctx.card.entity, brightness_pct: v } }) } : null),
};

// When each light group opened (card id → time), and how its opening runs:
// it waits for the tile to start growing, then takes LG_MS (house change).
const LG_OPENED = new Map();
// In step with the engine's one spring (K = 150, ζ = 0.82): a growing tile
// waits 170 ms (engine.js) and reads as grown ~400 ms later, so the rows
// finish unrolling with the outline instead of after it.
const LG_WAIT = 170, LG_MS = 400;
// Opened rows stay compact: one short row per light (house change).
const LG_ROW = 46;

// A blind group is a light group for covers: same lanes, same opened rows
// (house change). Position stands in for brightness.
const isCG = (ctx) => ctx.card.type === 'cover_group';
// A fan group (All Fans) is one too (house change): a lane per fan, opened
// into a row per fan. Its level is speed, where a fan has one.
const isFG = (ctx) => ctx.card.type === 'fan_group';
const fanPct = (ms) => (!ms || ms.state !== 'on' ? 0 : fanHasSpeed(ms) ? ms.attributes.percentage || 0 : 100);
const fanWord = (ms, p) => (!ms ? 'Missing' : off(ms) ? 'Unavailable' : ms.state !== 'on' ? 'Off' : fanHasSpeed(ms) && p ? [fanLevel(p), `${p}%`] : 'On');
const lgIcon = (ctx) => (isCG(ctx) ? 'blinds' : isFG(ctx) ? 'fan' : 'group');
const coverPos = (ms) => (ms && ms.attributes.current_position != null ? ms.attributes.current_position : ms && ms.state === 'open' ? 100 : 0);
const coverWord = (ms, p) => (!ms ? 'Missing' : ms.state === 'opening' ? 'Opening' : ms.state === 'closing' ? 'Closing' : p >= 100 ? 'Open' : p <= 0 ? 'Closed' : p + '% open');
const lightGroup = {
  // A group is a room's worth of lights: twice a strip, and it grows down
  // into its members rather than sideways.
  item: { span: 2, grow: 3, dir: 'down', want: 4, hk: 's', soft: true },
  accent: (ctx) => (isCG(ctx) || isFG(ctx) ? 'var(--sky)' : light.accent(ctx)),
  members: (ctx) => ((ctx.st && ctx.st.attributes.entity_id) || []).filter((e) => domainOf(e) === (isCG(ctx) ? 'cover' : isFG(ctx) ? 'fan' : 'light')),
  // The members Home Assistant cannot reach: counted in the tile when there is room, and named in the opened card.
  gone: (ctx) => lightGroup.members(ctx).filter((m) => off(ctx.hass.states[m])),
  // Opened, the lane strip itself grows down: each lane becomes a tall row
  // named for its light, which is the whole face (no group name above it).
  // Tap a row to toggle that light, slide it for its level, hold it to make
  // it the active light: the colour and history below then follow it, and
  // holding it again hands them back to the whole group (house change).
  rows: (ctx, grow, mini) => lightGroup.members(ctx).map((m, i, all) => {
    const ms = ctx.hass.states[m]; const cg = isCG(ctx); const on = cg ? coverPos(ms) > 0 : ms && ms.state === 'on'; const acc = cg ? 'var(--sky)' : on ? lightAccent(ms) : 'var(--amber)';
    const pv = ctx.memberPreview && ctx.memberPreview.id === m ? ctx.memberPreview.v : null;
    const picked = ctx.member === m;
    const face = isFG(ctx) ? (() => { const sp = fanHasSpeed(ms); const fon = !!(ms && ms.state === 'on'); const p = pv != null ? pv : fanPct(ms); return stripFace({ kind: sp ? 'fill' : 'switch', icon: 'fan', accent: 'var(--sky)', active: fon || pv > 0 || picked, edgeMix: picked ? 80 : 0, pct: fon || pv != null ? p : 0, iconActive: !off(ms), dur: fanDur(fon || pv > 0, p), fillA: mix('var(--sky)', 26), fillB: mix('var(--sky)', 8), name: lightGroup.label(ctx, m), val: pv != null ? (pv <= 1 ? 'Off' : [fanLevel(pv), `${pv}%`]) : fanWord(ms, p) }); })() : cg ? stripFace({ kind: 'slats', plainSlats: true, icon: 'blinds', accent: acc, iconColor: 'var(--sky)', active: on || pv > 0 || picked, edgeMix: picked ? 80 : 28, fillA: mix(acc, 20), fillB: mix(acc, 6), pct: pv != null ? pv : coverPos(ms), iconTransform: `scaleY(${Math.max(0.08, (100 - (pv != null ? pv : coverPos(ms))) / 100).toFixed(2)})`, name: lightGroup.label(ctx, m), val: pv != null ? pv + '% open' : coverWord(ms, coverPos(ms)) }) : stripFace({ kind: 'fill', icon: 'bulb', accent: acc, active: on || pv > 0 || picked, edgeMix: picked ? 80 : 0, pct: pv != null ? pv : on ? pct(ms) : 0, name: lightGroup.label(ctx, m), val: !ms ? 'Missing' : pv != null ? pv + '%' : on ? [`${pct(ms)}%`, lightTone(ms)] : off(ms) ? 'Unavailable' : 'Off' });
    // While opening, each row starts squeezed onto its lane of the closed
    // strip (same top, same height) and grows out of it.
    const lane = (56 - (all.length - 1)) / all.length;
    const from = grow && !mini ? `--dy:${(i * (lane + 1) - i * (LG_ROW + 1)).toFixed(2)}px;--s:${(lane / LG_ROW).toFixed(4)};` : '';
    return `<div data-member="${esc(m)}"${picked || mini ? ` class="${[picked ? 'picked' : '', mini ? 'mini' : ''].filter(Boolean).join(' ')}"` : ''} style="${from}position:relative;touch-action:pan-y;cursor:pointer;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none">${face}</div>`;
  }).join(''),
  // Opened, a slim slider under the rows sets every light (or blind) in the
  // group at once (house change, Oct 2026).
  allRow: (ctx) => {
    const cg = isCG(ctx); const lit = lightGroup.lanes(ctx).filter((l) => l.on);
    // Fans with no speed have no level to set together: tapping the group does it.
    if (isFG(ctx)) {
      if (!lightGroup.members(ctx).some((m) => fanHasSpeed(ctx.hass.states[m]))) return '';
      const v = lit.length ? Math.round(lit.reduce((a, l) => a + l.pct, 0) / lit.length) : 0;
      return `<div class="lgall" data-ctl="1">${icon('fan', { size: 14 })}<span>All</span><input type="range" class="lgrange" min="0" max="100" step="1" value="${v}" style="--v:${v}%" data-act="range" data-domain="fan" data-service="set_percentage" data-key="percentage" data-entity="${esc(ctx.card.entity)}" aria-label="All fans" oninput="this.style.setProperty('--v',this.value+'%');this.nextElementSibling.textContent=this.value+'%'"><b>${v}%</b></div>`;
    }
    const v = lit.length ? Math.round(lit.reduce((a, l) => a + l.pct, 0) / lit.length) : 0;
    const what = cg ? 'blinds' : 'lights';
    return `<div class="lgall" data-ctl="1">${icon(cg ? 'blinds' : 'group', { size: 14 })}<span>All</span><input type="range" class="lgrange" min="0" max="100" step="1" value="${v}" style="--v:${v}%" data-act="range" data-domain="${cg ? 'cover' : 'light'}" data-service="${cg ? 'set_cover_position' : 'turn_on'}" data-key="${cg ? 'position' : 'brightness_pct'}" data-entity="${esc(ctx.card.entity)}" aria-label="All ${what}" oninput="this.style.setProperty('--v',this.value+'%');this.nextElementSibling.textContent=this.value+'%'"><b>${v}%</b></div>`;
  },
  // With the room's and the group's name taken off, "Can 3" is "3": a bare
  // number names nothing, so the word before it stays.
  label: (ctx, m) => {
    const n = shortName(shortName(friendly(ctx.hass, m), ctx.sec.title), ctx.name);
    return /^\d+$/.test(n) ? `${shortName(ctx.name, ctx.sec.title)} ${n}` : n;
  },
  // Every light off: a column of identical "Off" rows says what the group's
  // own line already says, so they shrink to a grid of names (still one tap
  // each, still held to pick one). Lights only, more than two of them.
  allOff: (ctx) => {
    if (isCG(ctx) || isFG(ctx) || ctx.preview != null || ctx.memberPreview) return false;
    const ms = lightGroup.members(ctx);
    return ms.length > 2 && ms.every((m) => { const st = ctx.hass.states[m]; return st && st.state === 'off'; });
  },
  face: (ctx) => {
    const st = ctx.st; const on = isCG(ctx) || isFG(ctx) ? lightGroup.lanes(ctx).some((l) => l.on) : st && st.state === 'on';
    const cid = ctx.card.id;
    if (ctx.open && lightGroup.members(ctx).length) {
      // Opening is one slow, continuous grow of the same tile: the outline
      // unrolls downward from the strip's height, each lane swells into its
      // row, the group's name stays put and the rows' names fade in. A
      // redraw mid-way picks the motion up where it is (house change).
      // The card is redrawn in place, so the timing is fixed once at the
      // start: changing it mid-way would make the running grow jump.
      if (!LG_OPENED.has(cid)) LG_OPENED.set(cid, performance.now());
      const gone = performance.now() - LG_OPENED.get(cid);
      const grow = gone < LG_WAIT + LG_MS;
      const t = `${LG_MS}ms cubic-bezier(.33,.65,.25,1) ${LG_WAIT}ms both`;
      // The group's icon, name and state never leave: they stay where the
      // closed strip had them while its lanes swell into rows beneath, and
      // the rows name their lights at the right so the two never meet. No
      // caption above, nothing fades out (house change). The rows are clear,
      // like the closed strip, with hairlines between them (house change).
      const css = `<style>.lgface{position:relative;display:flex;flex-direction:column;gap:1px;border-radius:18px;overflow:hidden;box-shadow:inset 0 0 0 1px var(--line);background:transparent}.lgface .strip{height:${LG_ROW}px;border-radius:0;background-color:transparent!important;box-shadow:none!important}.lgface>[data-member]+[data-member]::before{content:'';position:absolute;left:0;right:0;top:-1px;height:1px;background:var(--line);pointer-events:none}.lgface>[data-member].picked .strip{box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--text) 35%,transparent)!important}.lgface [data-member] .sline{flex-direction:row-reverse;gap:9px;padding:0 14px}.lgface [data-member] .nv{text-align:right;align-items:flex-end;max-width:52%}.lgface [data-member] .flex1{display:none}.lgid{position:absolute;left:0;right:0;top:0;height:56px;z-index:1;pointer-events:none}.lgid .strip{height:100%;background:none!important;box-shadow:none!important}.lgid .nv{max-width:44%}.lgall{position:relative;display:flex;align-items:center;gap:9px;height:40px;padding:0 14px;color:var(--quiet);font:600 12px 'Manrope',sans-serif}.lgall::before{content:'';position:absolute;left:0;right:0;top:-1px;height:1px;background:var(--line)}.lgall b{min-width:34px;text-align:right;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums}.lgrange{-webkit-appearance:none;appearance:none;flex:1;min-width:0;height:28px;margin:0;background:transparent;cursor:pointer}.lgrange::-webkit-slider-runnable-track{height:4px;border-radius:2px;background:linear-gradient(90deg,${ctx.accent} var(--v),var(--line2) var(--v))}.lgrange::-moz-range-track{height:4px;border-radius:2px;background:var(--line2)}.lgrange::-moz-range-progress{height:4px;border-radius:2px;background:${ctx.accent}}.lgrange::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:14px;margin-top:-5px;border-radius:50%;background:#fff;border:0;box-shadow:0 1px 3px rgba(0,0,0,.35)}.lgrange::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:#fff;border:0}.lggrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));margin-top:56px;border-top:1px solid var(--line)}.lggrid [data-member].mini .strip{height:44px}.lggrid [data-member].mini .sline{flex-direction:row;padding:0 12px}.lggrid [data-member].mini .nv{text-align:left;align-items:flex-start;max-width:none;min-width:0}.lggrid [data-member].mini .nv span{display:none}.lggrid [data-member].picked .strip{box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--text) 35%,transparent)!important}${grow ? `.lgface.grow{animation:lgclip ${t}}.lgface.grow>[data-member]{transform-origin:0 0;animation:lgrow ${t}}.lgface.grow>[data-member] .sline{animation:lgtext ${t}}@keyframes lgclip{from{clip-path:inset(0 0 calc(100% - 56px) 0 round 18px)}to{clip-path:inset(0 0 0 0 round 18px)}}@keyframes lgrow{from{transform:translateY(var(--dy)) scaleY(var(--s))}to{transform:none}}@keyframes lgtext{0%,45%{opacity:0}100%{opacity:1}}.reduce .lgface.grow,.reduce .lgface.grow>[data-member],.reduce .lgface.grow>[data-member] .sline{animation:none}@media (prefers-reduced-motion:reduce){.lgface.grow,.lgface.grow>[data-member],.lgface.grow>[data-member] .sline{animation:none}}` : ''}</style>`;
      const id = `<div class="lgid" aria-hidden="true">${stripFace({ kind: 'none', icon: lgIcon(ctx), accent: ctx.accent, active: on, name: ctx.name, val: lightGroup.summary(ctx) })}</div>`;
      // All off: the rows are a grid of names under the group's line.
      const mini = lightGroup.allOff(ctx);
      const rows = mini ? `<div class="lggrid">${lightGroup.rows(ctx, false, true)}</div>` : lightGroup.rows(ctx, grow);
      return `${css}<div class="lgface${grow ? ' grow' : ''}${mini ? ' mini' : ''}">${id}${rows}${lightGroup.allRow(ctx)}</div>`;
    }
    LG_OPENED.delete(cid);
    const lanes = lightGroup.lanes(ctx);
    // Every bulb at the same level: one fill, not a stack of identical
    // stripes (house change, Oct 2026). Lanes return the moment they differ.
    const ps = lanes.map((l) => l.pct);
    // House change, Oct 2026: the lanes and their lines always show, even
    // when every bulb is at the same level (this flattening is off).
    if (false && lanes.length > 1 && lanes.every((l) => l.on) && Math.max(...ps) - Math.min(...ps) <= 3) {
      return stripFace({ kind: isCG(ctx) ? 'slats' : 'fill', icon: isCG(ctx) ? 'blinds' : 'group', accent: lanes[0].color, iconColor: isCG(ctx) ? 'var(--sky)' : undefined, active: true, pct: Math.round(ps.reduce((a, b) => a + b, 0) / ps.length), name: ctx.name, val: lightGroup.summary(ctx), valColor: 'var(--muted)', hint: ctx.hint });
    }
    return stripFace({ kind: 'lanes', lanes, icon: lgIcon(ctx), iconColor: isFG(ctx) ? 'var(--sky)' : undefined, dur: isFG(ctx) ? fanDur(lanes.some((l) => l.on), 60) : undefined, accent: ctx.accent, active: lanes.some((l) => l.on), name: ctx.name, val: lightGroup.summary(ctx), hint: ctx.hint });
  },
  lanes: (ctx) => lightGroup.members(ctx).map((m) => { const ms = ctx.hass.states[m]; if (isFG(ctx)) { const p = ctx.preview != null ? ctx.preview : fanPct(ms); return { on: p > 0, pct: p, color: 'var(--sky)' }; } if (isCG(ctx)) { const p = ctx.preview != null ? ctx.preview : coverPos(ms); return { on: p > 0, pct: p, color: 'var(--sky)' }; } return { on: (ms && ms.state === 'on') || ctx.preview > 0, pct: ctx.preview != null ? ctx.preview : pct(ms), color: ms && ms.state === 'on' ? lightAccent(ms) : ctx.accent }; }),
  summary: (ctx) => {
    const lanes = lightGroup.lanes(ctx);
    const lit = lanes.filter((l) => l.on);
    const n = lit.length, total = lanes.length;
    // Lights that are disconnected are not "off": say so (house change, Oct 2026).
    const gone = isCG(ctx) ? 0 : lightGroup.gone(ctx).length;
    const mixed = n > 1 && lit.some((l) => l.pct !== lit[0].pct);
    const avg = n ? Math.round(lit.reduce((a, l) => a + l.pct, 0) / n) : 0;
    // The parts of one status line (statusHtml): the first is always shown, a later one only where the tile has the room.
    if (isFG(ctx)) return off(ctx.st) ? 'Unavailable' : n ? `${n === total ? 'All ' + total : n + ' of ' + total} on` : total ? `All ${total} off` : 'Off';
    if (isCG(ctx)) return off(ctx.st) ? 'Unavailable' : ctx.preview != null ? ctx.preview + '% open' : n ? [`${n === total ? 'All ' + total : n + ' of ' + total} open`, mixed ? '' : avg + '%'] : total ? `All ${total} closed` : 'Closed';
    // ONE format for a light group (#887 #967): how many of the reachable ones are on ("20 of 31 on", "All 5 on", "5 off"), then the average level of those that are on, labelled, then (where the tile has the room) how many cannot be reached. "All" only when every member answers; one light reads "On" or "Off".
    const reach = total - gone;
    const bad = gone ? gone + ' unavailable' : '';
    return off(ctx.st) ? 'Unavailable' : ctx.preview != null ? ctx.preview + '%'
      : total === 1 && !gone ? [n ? 'On' : 'Off', n ? `avg ${avg}%` : '']
        : n ? [!gone && n === total ? `All ${total} on` : `${n} of ${total} on`, `avg ${avg}%`, bad]
          : total ? [!gone ? `All ${total} off` : reach ? `${reach} off` : 'All unavailable', reach ? bad : ''] : 'Off';
  },
  more: (ctx) => {
    // Below the rows: one colour selector and one history, for the active
    // light when a row is held, otherwise for the whole group.
    const m = ctx.member; const ms = m && ctx.hass.states[m];
    if (isFG(ctx)) {
      // A held fan shows its own options (direction, oscillate, modes) and history.
      if (!ms) return histBlock(ctx);
      const nm = lightGroup.label(ctx, m);
      return fan.more({ ...ctx, card: { ...ctx.card, type: 'fan', entity: m }, st: ms, name: nm });
    }
    if (isCG(ctx)) {
      const t = ms ? m : ctx.card.entity; const a = ((ms || ctx.st) && (ms || ctx.st).attributes) || {};
      const nm = ms ? lightGroup.label(ctx, m) : 'All blinds';
      const tilt = a.current_tilt_position != null ? `${blockLabel('Tilt')}<input type="range" class="mrange" min="0" max="100" value="${a.current_tilt_position}" data-act="range" data-domain="cover" data-service="set_cover_tilt_position" data-key="tilt_position" data-entity="${esc(t)}" aria-label="Tilt">` : '';
      // No Open/Stop/Close row: the blind rows above already open and close each one.
      return tilt + histBlock(ms ? { ...ctx, card: { ...ctx.card, type: 'cover', entity: m }, st: ms, name: nm } : ctx, ms ? 'History · ' + nm : undefined);
    }
    // What the tile has no room for: which lights cannot be reached, by name.
    const gone = ms ? [] : lightGroup.gone(ctx).map((g) => lightGroup.label(ctx, g));
    const goneNote = gone.length ? `<div class="small" style="margin:0 0 8px">${gone.length} of ${lightGroup.members(ctx).length} unavailable: ${esc(gone.slice(0, 3).join(', '))}${gone.length > 3 ? ` and ${gone.length - 3} more` : ''}</div>` : '';
    if (!ms) return goneNote + lightMore(ctx, ctx.card.entity, null, 'Color · All lights') + histBlock(ctx);
    const nm = lightGroup.label(ctx, m);
    const sub = { ...ctx, card: { ...ctx.card, type: 'light', entity: m }, st: ms, accent: ms.state === 'on' ? lightAccent(ms) : ctx.accent, name: nm };
    return lightMore(ctx, m, ms, 'Color · ' + nm) + histBlock(sub, 'History · ' + nm);
  },
  tap: (ctx) => (isCG(ctx) ? cover.tap(ctx) : isFG(ctx) ? fan.tap(ctx) : light.tap(ctx)),
  slide: (ctx) => (isCG(ctx) ? cover.slide(ctx) : isFG(ctx) ? (lightGroup.members(ctx).some((m) => fanHasSpeed(ctx.hass.states[m])) ? fan.slide(ctx) : null) : { get: () => pct(ctx.st), call: (v) => (v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: ctx.card.entity } } : { domain: 'light', service: 'turn_on', data: { entity_id: ctx.card.entity, brightness_pct: v } }) }),
};

// ------------------------------------------------------------- fan, cover

// An off fan stands still (the owner's rule); on, its blades turn faster with
// speed, between 2.6 s and 1.1 s a turn: quicker than that strobes on a
// three-blade icon. Still is drawn as a turn of 100000 s (FAN_STILL), which
// does not visibly move, rather than as no animation, so morph-dom's
// keepPhase eases the blades up from rest and down to it.
const FAN_STILL = '100000s';
const fanDur = (on, p) => (on ? (2.6 - 1.5 * Math.min(100, Math.max(0, p || 0)) / 100).toFixed(2) + 's' : FAN_STILL);
// Colour language (house change): warm = light and power; sky = air, climate,
// water, blinds, weather; indigo = secure and at rest (locked, closed, armed);
// amber = caution (unlocked); rose = needs attention (open, triggered, sounding);
// violet = media, scenes, scripts, modes; peach = people; teal = housekeeping.
// Green is kept for the garden and irrigation, nothing else.
const fan = {
  item: STRIP,
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    // A fan with no speed control is on or off: "High · 100%" on one was a
    // speed it does not have, and sliding it called a service it refuses.
    const speed = fanHasSpeed(st);
    const p = ctx.preview != null ? ctx.preview : (speed ? st.attributes.percentage : on ? 100 : 0);
    return stripFace({ kind: speed ? 'fill' : 'switch', icon: 'fan', dead: off(st), accent: ctx.accent, active: on || ctx.preview > 0, pct: on || ctx.preview != null ? p : 0, iconActive: !off(st), dur: fanDur(on || ctx.preview > 0, p), name: ctx.name, fillA: mix(ctx.accent, 26), fillB: mix(ctx.accent, 8), val: off(st) ? stateWord(st, ctx.hass) : on || ctx.preview > 0 ? (speed && p ? [fanLevel(p), `${p}%`] : 'On') : 'Off', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    // A fan group (All Fans) is a global control: no direction switches.
    if (a.direction && !Array.isArray(a.entity_id)) parts.push(blockLabel('Direction') + words([svcBtn('Forward', 'fan', 'set_direction', { entity_id: e, direction: 'forward' }, { pressed: a.direction === 'forward' }), svcBtn('Reverse', 'fan', 'set_direction', { entity_id: e, direction: 'reverse' }, { pressed: a.direction === 'reverse' })]));
    if (a.oscillating != null) parts.push(blockLabel('Oscillate') + words([svcBtn('On', 'fan', 'oscillate', { entity_id: e, oscillating: true }, { pressed: !!a.oscillating }), svcBtn('Off', 'fan', 'oscillate', { entity_id: e, oscillating: false }, { pressed: !a.oscillating })]));
    if ((a.preset_modes || []).length) parts.push(blockLabel('Mode') + words(a.preset_modes.map((m) => svcBtn(m, 'fan', 'set_preset_mode', { entity_id: e, preset_mode: m }, { pressed: a.preset_mode === m }))));
    return parts.join('') + histBlock(ctx);
  },
  tap: (ctx) => ({ domain: 'fan', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (fanHasSpeed(ctx.st) ? { get: () => ctx.st.attributes.percentage || 0, call: (v) => ({ domain: 'fan', service: 'set_percentage', data: { entity_id: ctx.card.entity, percentage: v <= 1 ? 0 : v } }) } : null),
};

// options.details: [{ entity, name }] or entity ids. Each reading opens its
// own entity card and says how recently it changed (house change).
const DETAIL_WORDS = { problem: ['Clear', 'Detected'], running: ['Idle', 'Running'], motion: ['Clear', 'Motion'], occupancy: ['Clear', 'Occupied'] };
function detailValue(st) {
  if (!st || UNAVAILABLE.includes(st.state)) return st ? 'Unavailable' : 'Missing';
  const a = st.attributes || {}; const d = domainOf(st.entity_id);
  if (d === 'binary_sensor') { const w = DETAIL_WORDS[a.device_class] || ['Off', 'On']; return w[st.state === 'on' ? 1 : 0]; }
  if (isFinite(Number(st.state))) return fmt(st.state, a.unit_of_measurement);
  return st.state[0].toUpperCase() + st.state.slice(1);
}
function coverDetails(ctx) {
  const list = ((ctx.card.options && ctx.card.options.details) || []).map((x) => (typeof x === 'string' ? { entity: x } : x)).filter((x) => x && x.entity);
  if (!list.length) return '';
  const cells = list.map((x) => {
    const st = ctx.hass.states[x.entity]; const name = x.name || friendly(ctx.hass, x.entity);
    const alert = st && st.state === 'on' && ['problem', 'motion', 'running'].includes(st.attributes.device_class);
    return `<button type="button" class="cdt" data-ctl="1" data-act="more-info" data-v="${esc(x.entity)}"><b style="display:block;font-family:'Bricolage Grotesque',sans-serif;font-size:17px;font-weight:600;line-height:1.15;color:${alert ? (st.attributes.device_class === 'problem' ? 'var(--rose)' : 'var(--amber)') : 'var(--text)'}">${esc(detailValue(st))}</b><span style="display:block;font-size:12px;color:var(--muted)">${esc(name)}</span><span style="display:block;font-size:11px;color:var(--quiet)">${esc(st ? ago(st.last_updated) : '')}</span></button>`;
  }).join('');
  return `<style>.cdt{all:unset;cursor:pointer;min-width:0;overflow-wrap:anywhere;border-radius:8px}.cdt:focus-visible{outline:2px solid var(--sky);outline-offset:3px}</style>${blockLabel('Details')}<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:10px 14px;margin-bottom:6px">${cells}</div>`;
}
const isGarage = (st) => st && ['garage', 'gate', 'door'].includes(st.attributes.device_class);
// What a tap on a garage door or gate does, in words: Open, Close, or Stop while it moves.
const garageAct = (st) => {
  const moving = st && ['opening', 'closing'].includes(st.state);
  const action = off(st) ? '' : moving ? 'Stop' : st && ['open', 'opening'].includes(st.state) ? 'Close' : 'Open';
  return { action, noun: !action || action === 'Stop' ? '' : st.attributes.device_class === 'gate' ? 'gate' : 'door' };
};
const cover = {
  item: STRIP,
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; const pos = ctx.preview != null ? ctx.preview : (st && st.attributes.current_position != null ? st.attributes.current_position : st && st.state === 'open' ? 100 : 0);
    const open = st && ['open', 'opening'].includes(st.state);
    if (isGarage(st)) {
      // A word, not a switch: it says what a tap will do (house change).
      const moving = st && ['opening', 'closing'].includes(st.state);
      const { action, noun } = garageAct(st);
      return stripFace({ kind: 'none', icon: 'garage', accent: open ? 'var(--rose)' : 'var(--indigo)', active: open, action, armed: ctx.confirm || '', actIcon: action.toLowerCase(), actNoun: noun, actionColor: moving ? 'var(--muted)' : open ? 'var(--indigo)' : 'var(--rose)', name: ctx.name, val: stateWord(st, ctx.hass), iconTransform: open ? 'translateY(-4px)' : 'none', hint: ctx.hint });
    }
    return stripFace({ kind: 'slats', icon: 'blinds', accent: ctx.accent, iconColor: 'var(--sky)', edgeMix: 28, fillA: mix(ctx.accent, 20), fillB: mix(ctx.accent, 6), active: pos > 0, pct: pos, iconTransform: `scaleY(${Math.max(0.08, (100 - pos) / 100).toFixed(2)})`, name: ctx.name, val: off(st) ? 'Unavailable' : st.state === 'opening' ? 'Opening' : st.state === 'closing' ? 'Closing' : pos >= 100 ? 'Open' : pos <= 0 ? 'Closed' : pos + '% open', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    // A garage door's Open/Close is the word on its face; opened, it shows
    // the opener's own readings (options.details) instead (house change).
    if (isGarage(ctx.st)) return coverDetails(ctx) + histBlock(ctx);
    // Tap opens and closes, a slide sets the position: only Stop is new here,
    // and only while it moves. A group's blinds one by one is what a blind
    // group (cover_group) is for, so they are not repeated here (rule 4).
    if (ctx.st && ['opening', 'closing'].includes(ctx.st.state)) parts.push(words([svcBtn('Stop', 'cover', 'stop_cover', { entity_id: e })]));
    if (a.current_tilt_position != null) parts.push(`${blockLabel('Tilt')}<input type="range" class="mrange" min="0" max="100" value="${a.current_tilt_position}" data-act="range" data-domain="cover" data-service="set_cover_tilt_position" data-key="tilt_position" data-entity="${esc(e)}" aria-label="Tilt">`);
    return parts.join('') + histBlock(ctx);
  },
  act: (ctx) => { if (!isGarage(ctx.st)) return ''; const a = garageAct(ctx.st); return a.action ? `${a.action}${a.noun ? ' ' + a.noun : ''}` : ''; },
  tap: (ctx) => {
    const st = ctx.st; const open = st && ['open', 'opening'].includes(st.state);
    if (isGarage(st) && st && ['opening', 'closing'].includes(st.state)) return { domain: 'cover', service: 'stop_cover', data: { entity_id: ctx.card.entity } };
    if (isGarage(st) && !open) return { domain: 'cover', service: 'open_cover', data: { entity_id: ctx.card.entity }, confirm: 'Open?' };
    if (isGarage(st)) return { domain: 'cover', service: 'close_cover', data: { entity_id: ctx.card.entity } };
    return { domain: 'cover', service: 'toggle', data: { entity_id: ctx.card.entity } };
  },
  slide: (ctx) => (ctx.st && ctx.st.attributes.current_position != null && !isGarage(ctx.st) ? { get: () => ctx.st.attributes.current_position, call: (v) => ({ domain: 'cover', service: 'set_cover_position', data: { entity_id: ctx.card.entity, position: v <= 1 ? 0 : v } }) } : null),
};

// ---------------------------------------------------------- switches, locks

// Colour carries meaning (vision §9.2): power is warm, the garden is the
// only green, an automation is the house's own (violet).
const SWITCH_COLOR = { switch: 'var(--amber)', input_boolean: 'var(--violet)', siren: 'var(--rose)', automation: 'var(--violet)' };
const GARDEN = /irrigat|sprinkler|lawn|garden|drip|zone/i;
const sw = {
  item: { ...STRIP, want: 2 },
  accent: (ctx) => (GARDEN.test(ctx.card.entity + ' ' + (ctx.name || '')) ? 'var(--lime)' : SWITCH_COLOR[domainOf(ctx.card.entity)] || 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    // A switch that runs a fan (its icon says so) shows turning blades like
    // a fan card: standing still while off, turning while on (house change).
    const isFan = /fan(?!-off)/.test(String((ctx.card.icon || (st && st.attributes.icon)) || ''));
    const fanIcon = isFan ? { icon: 'fan', iconActive: !off(st), dur: fanDur(on, 100) } : { icon: 'power' };
    // options.power: a plug's power sensor shows its draw while on, or Standby
    // when it is on but drawing almost nothing (house change).
    let val = off(st) ? stateWord(st, ctx.hass) : on ? 'On' : 'Off';
    const pw = on && ctx.card.options && ctx.card.options.power && ctx.hass && ctx.hass.states[ctx.card.options.power];
    const w = pw ? parseFloat(pw.state) : NaN;
    if (isFinite(w)) val = w < 5 ? 'Standby' : `${Math.round(w)} W`;
    return stripFace({ kind: 'switch', ...fanIcon, accent: ctx.accent, active: on, name: ctx.name, dead: off(st), val, hint: ctx.hint });
  },
  more: (ctx) => histBlock(ctx),
  tap: (ctx) => ({ domain: 'homeassistant', service: 'toggle', data: { entity_id: ctx.card.entity } }),
};

// Locked is secure (indigo); unlocked is a caution (amber), which the
// salience list turns rose at night. The word on the right is what a tap
// does, and either way it takes a second tap (vision §3, 11:30 PM).
const lock = {
  item: { ...STRIP, want: 2 },
  accent: (ctx) => (ctx.st && ctx.st.state === 'unlocked' ? 'var(--amber)' : 'var(--indigo)'),
  face: (ctx) => {
    const st = ctx.st; const unlocked = st && ['unlocked', 'open', 'opening', 'unlocking'].includes(st.state);
    const locked = st && st.state === 'locked';
    const action = off(st) ? '' : unlocked ? 'Lock' : locked ? 'Unlock' : '';
    // options.sub: one reading said beside the state ("Locked · 188 mi").
    const sub = ctx.card.options && ctx.card.options.sub && ctx.hass.states[ctx.card.options.sub];
    const extra = sub && !off(sub) ? ' · ' + detailValue(sub) : '';
    return stripFace({ kind: 'none', icon: 'lock', accent: ctx.accent, active: unlocked, action, actIcon: action.toLowerCase(), armed: ctx.confirm || '', actionColor: unlocked ? 'var(--indigo)' : 'var(--amber)', name: ctx.name, val: off(st) ? stateWord(st, ctx.hass) : stateWord(st, ctx.hass) + extra, iconTransform: unlocked ? 'translateY(-3px)' : 'none', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const bat = a.battery_level != null ? `<p class="sm">Battery ${esc(a.battery_level)}%</p>` : '';
    return coverDetails(ctx) + bat + histBlock(ctx);
  },
  // Locking and unlocking both take a second tap (household rule, Oct 2026).
  // The pressable word's name, which the tile carries for a screen reader.
  act: (ctx) => (off(ctx.st) ? '' : ['unlocked', 'open', 'opening', 'unlocking'].includes(ctx.st.state) ? 'Lock' : ctx.st.state === 'locked' ? 'Unlock' : ''),
  tap: (ctx) => (ctx.st && ctx.st.state === 'locked'
    ? { domain: 'lock', service: 'unlock', data: { entity_id: ctx.card.entity }, confirm: 'Unlock?' }
    : { domain: 'lock', service: 'lock', data: { entity_id: ctx.card.entity }, confirm: 'Lock?' }),
};

// The media players a "turn everything off" button would stop: anything not
// already off, leaving out what carries the "always on" label (as Bedtime does).
// Only what is actually playing or switched on counts: an idle speaker is
// not "on" (22 idle Cast devices read as "22 on" before, Oct 2026).
const MEDIA_ACTIVE = ['playing', 'paused', 'buffering', 'on'];
const mediaOn = (hass) => Object.keys(hass.states).filter((e) => domainOf(e) === 'media_player' && MEDIA_ACTIVE.includes(hass.states[e].state)
  && !(((hass.entities || {})[e] || {}).labels || []).some((l) => /^always[ _]on$/.test(l)));

// When something happened, as a person says it: "9:14 PM", "last night
// 12:44 AM", "yesterday 9:10 PM", "Mon 8:03 PM", "Oct 2".
export const whenWord = (t) => {
  const d = new Date(Date.parse(t || '')); if (isNaN(d)) return '';
  const now = new Date(); const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dd = Math.round((day(now) - day(d)) / 86400000);
  const hm = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (dd === 0) return now.getHours() >= 12 && d.getHours() < 5 ? 'last night ' + hm : hm;
  if (dd === 1) return (d.getHours() >= 20 ? 'last night ' : 'yesterday ') + hm;
  if (dd < 7) return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + hm;
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
};
const button = {
  item: { ...STRIP, want: 2 },
  accent: () => 'var(--violet)',
  // options.all_media: the button turns off every media player that is on (house change).
  // options.panic: [siren ids]: a panic button that sounds them all on a second tap, and silences them (house change).
  face: (ctx) => {
    if (ctx.card.options && ctx.card.options.panic) { const on = panicOn(ctx); return stripFace({ kind: 'none', icon: 'shield', accent: 'var(--rose)', iconColor: 'var(--rose)', active: on.length > 0, action: on.length ? 'Silence' : 'Sound', armed: ctx.confirm || '', actionColor: on.length ? 'var(--indigo)' : 'var(--rose)', name: ctx.name, val: on.length ? 'Sirens sounding' : 'Sirens off', hint: ctx.hint }); }
    if (ctx.card.options && ctx.card.options.all_media) { const on = mediaOn(ctx.hass); const pl = on.filter((e) => ctx.hass.states[e].state === 'playing').length; return stripFace({ kind: 'none', icon: 'power', accent: ctx.accent, active: on.length > 0, name: ctx.name, val: pl ? `${pl} playing` : on.length ? `${on.length} on` : 'Nothing playing', hint: ctx.hint }); }
    const st = ctx.st; const script = domainOf(ctx.card.entity) === 'script';
    const last = st && (script ? st.attributes.last_triggered : st.state);
    const w = whenWord(last);
    const val = (script ? off(st) : !st || st.state === 'unavailable') ? stateWord(st, ctx.hass) : script && st.state === 'on' ? 'Running' : w ? (script ? 'Ran ' : 'Pressed ') + w : script ? 'Tap to run' : 'Tap to press';
    return stripFace({ kind: 'none', icon: 'play', accent: ctx.accent, active: st && st.state === 'on', name: ctx.name, val: ctx.confirm || val, valColor: ctx.confirm ? 'var(--amber)' : undefined, hint: ctx.hint });
  },
  // A panic button opens to one block per siren: its state, Sound / Silence
  // for that siren alone, its tone and its volume (the siren's own defaults,
  // which the alarm plays), then history (house change, Oct 2026).
  more: (ctx) => {
    if (!(ctx.card.options && ctx.card.options.panic)) return histBlock(ctx);
    const H = ctx.hass;
    const kin = (e, dom, word) => {
      const reg = H.entities && H.entities[e]; const dev = reg && reg.device_id;
      const ids = Object.keys(H.states).filter((x) => x.startsWith(dom + '.') && x.includes(word));
      const byDev = dev && H.entities ? ids.find((x) => H.entities[x] && H.entities[x].device_id === dev) : null;
      const stem = e.split('.')[1].replace(/_play_tone$/, '');
      return byDev || ids.find((x) => x.split('.')[1].startsWith(stem)) || null;
    };
    const rows = [].concat(ctx.card.options.panic).map((e) => {
      const st = H.states[e]; const on = st && st.state === 'on';
      const label = ((st && st.attributes.friendly_name) || e).replace(/\s*play tone$/i, '').trim();
      const toneE = kin(e, 'select', 'tone'); const volE = kin(e, 'number', 'volume'); const plugE = kin(e, 'binary_sensor', 'mains_disconnected');
      const tone = toneE && H.states[toneE]; const vol = volE && H.states[volE];
      const unplugged = plugE && H.states[plugE] && H.states[plugE].state === 'on';
      const word = !st || off(st) ? stateWord(st, ctx.hass) : on ? 'Sounding' : unplugged ? 'Off · unplugged' : 'Off';
      const nice = (o) => String(o).replace(/\.mp3/i, '').replace(/^alert\d+_/i, '').replace(/[-_]/g, ' ').replace(/\s*\((\d+) sec\)/, ' · $1 s').replace(/^\w/, (c) => c.toUpperCase());
      const opts = tone ? (tone.attributes.options || []).filter((o) => !/empty track/i.test(o)) : [];
      const toneRow = tone ? `<label class="srow"><span class="slab">Tone</span><select class="ssel" data-ctl="1" data-act-change="sel" data-entity="${esc(toneE)}" aria-label="${esc(label)} tone">${opts.map((o) => `<option value="${esc(o)}"${o === tone.state ? ' selected' : ''}>${esc(nice(o))}</option>`).join('')}</select></label>` : '';
      const v = vol && !isNaN(parseFloat(vol.state)) ? Math.round(parseFloat(vol.state) * 100) : null;
      const volRow = vol ? `<div class="srow"><span class="slab">Volume</span><input type="range" class="srange" data-ctl="1" min="0" max="100" step="1" value="${v == null ? 0 : v}" style="--v:${v == null ? 0 : v}%" data-act="range" data-domain="number" data-service="set_value" data-key="value" data-scale="0.01" data-entity="${esc(volE)}" aria-label="${esc(label)} volume" oninput="this.style.setProperty('--v',this.value+'%');this.nextElementSibling.textContent=this.value+'%'"><b class="sval">${v == null ? '—' : v + '%'}</b></div>` : '';
      return `<div class="siren${on ? ' on' : ''}"><div class="shead"><span class="sname">${esc(label)}</span><span class="sword${on ? ' hot' : unplugged ? ' warn' : ''}">${esc(word)}</span><span class="flex1"></span>${svcBtn(on ? 'Silence' : 'Sound', 'siren', on ? 'turn_off' : 'turn_on', { entity_id: e }, on ? {} : { confirm: 'Sound it?' })}</div>${toneRow}${volRow}</div>`;
    }).join('');
    const css = `<style>.siren{padding:10px 0 12px;border-top:1px solid var(--line)}.siren:first-of-type{border-top:0}.siren .shead{display:flex;align-items:center;gap:10px;min-height:36px}.siren .sname{font-weight:600;font-size:14px}.siren .sword{font-size:12.5px;color:var(--muted)}.siren .sword.hot{color:var(--rose);font-weight:700}.siren .sword.warn{color:var(--amber)}.siren .srow{display:flex;align-items:center;gap:12px;min-height:40px}.siren .slab{width:58px;flex:none;font:700 10px 'Manrope',sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--quiet)}.siren .ssel{flex:1;min-width:0;height:34px;padding:0 10px;border:0;border-radius:9px;background:color-mix(in oklab,var(--text) 6%,transparent);box-shadow:inset 0 0 0 1px var(--line);color:var(--text);font:500 14px 'Manrope',sans-serif;-webkit-appearance:none;appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 15px) 15px,calc(100% - 10px) 15px;background-size:5px 5px;background-repeat:no-repeat}.siren .srange{-webkit-appearance:none;appearance:none;flex:1;min-width:0;height:28px;margin:0;background:transparent}.siren .srange::-webkit-slider-runnable-track{height:4px;border-radius:2px;background:linear-gradient(90deg,var(--rose) var(--v),var(--line2) var(--v))}.siren .srange::-moz-range-track{height:4px;border-radius:2px;background:var(--line2)}.siren .srange::-moz-range-progress{height:4px;background:var(--rose)}.siren .srange::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;margin-top:-6px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.35)}.siren .srange::-moz-range-thumb{width:16px;height:16px;border:0;border-radius:50%;background:#fff}.siren .sval{width:40px;text-align:right;font-weight:600;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}</style>`;
    return css + blockLabel('Sirens') + rows + histBlock(ctx);
  },
  tap: (ctx) => {
    if (ctx.card.options && ctx.card.options.panic) { const all = [].concat(ctx.card.options.panic); return panicOn(ctx).length ? { domain: 'siren', service: 'turn_off', data: { entity_id: all } } : { domain: 'siren', service: 'turn_on', data: { entity_id: all }, confirm: all.length === 1 ? 'Sound the siren?' : all.length === 2 ? 'Sound both sirens?' : `Sound all ${all.length} sirens?` }; }
    // Nothing playing: a tap does nothing (it is not a request to open).
    if (ctx.card.options && ctx.card.options.all_media) { const on = mediaOn(ctx.hass); return on.length ? { domain: 'media_player', service: 'turn_off', data: { entity_id: on } } : { noop: true }; }
    // options.confirm: true or a phrase: the run takes a second tap (house change, Oct 2026).
    const d = domainOf(ctx.card.entity); const cf = ctx.card.options && ctx.card.options.confirm;
    return { domain: d === 'script' ? 'script' : d, service: d === 'script' ? 'turn_on' : 'press', data: { entity_id: ctx.card.entity }, ...(cf ? { confirm: typeof cf === 'string' ? cf : 'Tap again to run' } : {}) };
  },
};

function panicOn(ctx) { return [].concat(ctx.card.options.panic).filter((e) => ctx.hass.states[e] && ctx.hass.states[e].state === 'on'); }

const vacuum = {
  item: STRIP,
  accent: () => 'var(--teal)',
  face: (ctx) => {
    const st = ctx.st; const run = st && ['cleaning', 'returning'].includes(st.state);
    const bat = st && st.attributes.battery_level != null ? `${st.attributes.battery_level}%` : '';
    // The press is a button that says what it does, as a lock's is: Start,
    // or Dock while it cleans (the same as a tap). It was a switch with
    // nothing written on it, which a tap could not be told apart from.
    const action = vacuum.act(ctx);
    return stripFace({ kind: 'switch', icon: 'vacuum', accent: ctx.accent, active: run, name: ctx.name, val: off(st) ? stateWord(st, ctx.hass) : [stateWord(st, ctx.hass), bat], action, actIcon: action === 'Dock' ? 'dock' : 'start', armed: ctx.confirm || '', actionColor: ctx.accent, hint: ctx.hint });
  },
  act: (ctx) => (off(ctx.st) ? '' : ctx.st.state === 'cleaning' ? 'Dock' : 'Start'),
  more: (ctx) => words([svcBtn('Start', 'vacuum', 'start', { entity_id: ctx.card.entity }), svcBtn('Pause', 'vacuum', 'pause', { entity_id: ctx.card.entity }), svcBtn('Go home', 'vacuum', 'return_to_base', { entity_id: ctx.card.entity })]) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'vacuum', service: ctx.st && ctx.st.state === 'cleaning' ? 'return_to_base' : 'start', data: { entity_id: ctx.card.entity } }),
};

// ----------------------------------------------------------------- climate

// The face is the whole thermostat: what it is doing, the setpoints as
// labelled steppers (both of them in Auto), and the mode and fan as segmented
// words. Opening the card shows its detail (e.g. HVAC performance), so the
// controls are never repeated there (house change).
const MODE = { heat: ['Heat', 'var(--rose)'], cool: ['Cool', 'var(--sky)'], heat_cool: ['Auto', 'var(--muted)'], auto: ['Auto', 'var(--muted)'], dry: ['Dry', 'var(--sky)'], fan_only: ['Fan', 'var(--muted)'], off: ['Off', 'var(--quiet)'] };
const ACTION = { heating: ['Heating', 'var(--rose)'], cooling: ['Cooling', 'var(--sky)'], drying: ['Drying', 'var(--sky)'], fan: ['Fan only', 'var(--muted)'], idle: ['Idle', 'var(--quiet)'], off: ['Off', 'var(--quiet)'], preheating: ['Preheating', 'var(--rose)'], defrosting: ['Defrosting', 'var(--muted)'] };
const MODE_ORDER = ['off', 'heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only'];
const CLIMATE_CSS = `<style>
.cl-head{display:flex;align-items:center;gap:8px}
.cl-dot{width:7px;height:7px;border-radius:50%;flex:none;transition:background-color .6s ease}
.cl-dot.on{animation:clbeat 2.4s ease-in-out infinite}
@keyframes clbeat{0%,100%{box-shadow:0 0 0 0 color-mix(in oklab,currentColor 45%,transparent)}50%{box-shadow:0 0 0 4px transparent}}
.cl-act{font-size:12px;font-weight:600;transition:color .6s ease}
.cl-fan{display:inline-flex;margin:0 1px 0 4px;color:var(--quiet);transition:color .6s ease}
.cl-fan.on{color:var(--text)}
.reduce .cl-dot.on{animation:none}
@media (prefers-reduced-motion:reduce){.cl-dot.on{animation:none}}
.cl-main{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 16px;margin-top:4px}
.cl-now{display:flex;flex-direction:column;line-height:1}
.cl-now .big{font-size:36px}
.cl-now .small{margin-top:5px}
.cl-sets{display:flex;gap:14px;margin-left:auto}
.cl-set{display:flex;flex-direction:column;align-items:center;gap:1px}
.cl-lab{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--quiet)}
.cl-step{display:flex;align-items:center}
.cl-val{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:22px;font-weight:400;letter-spacing:-.02em;font-variant-numeric:tabular-nums;min-width:40px;text-align:center}
.cl-sq{position:relative;width:26px;height:26px;border-radius:50%;border:0;padding:0;background:transparent;color:var(--quiet);display:grid;place-items:center;cursor:pointer;transition:background-color .2s ease,color .2s ease}
.cl-sq::before{content:"";position:absolute;inset:-9px -5px}
.cl-val.pend{color:var(--muted)}
.cl-sq:hover{background:var(--chip);color:var(--text)}
.cl-ctl{display:flex;flex-wrap:nowrap;align-items:center;gap:6px 0;white-space:nowrap;margin-top:12px;padding-top:8px;border-top:1px solid var(--line);container-type:inline-size}
.cl-seg{display:inline-flex;gap:3px}
.cl-seg button{position:relative;border:0;margin:0;font:inherit;font-size:13px;font-weight:600;color:var(--muted);background:color-mix(in oklab,var(--text) 5%,transparent);padding:0 8px;min-height:28px;border-radius:999px;white-space:nowrap;cursor:pointer;transition:background-color .2s ease,color .2s ease}
.cl-seg button:hover{color:var(--text);background:color-mix(in oklab,var(--text) 10%,transparent)}
.cl-seg button::before{content:"";position:absolute;inset:-8px -1px}
.cl-sq:focus-visible,.cl-seg button:focus-visible{outline:2px solid var(--sky);outline-offset:2px}
.cl-short{display:none}
.cl-seg button[aria-pressed="true"]{color:var(--c,var(--text));background:color-mix(in oklab,var(--c,var(--text)) 11%,transparent)}
.cl-div{width:1px;height:14px;background:var(--line2);opacity:.6;margin:0 6px}
.cl-run{margin-left:auto;padding-left:6px;flex:0 1 auto;min-width:0}
.cl-run .cl-seg{min-width:0;max-width:100%}
.cl-run .cl-seg button{display:inline-flex;align-items:center;gap:4px;flex:0 1 auto;min-width:0}
.cl-run .cl-seg button svg{flex:none}
.cl-txt{display:inline-block;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}
.cl-seglab{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--quiet);margin:0 2px 0 4px}
/* The row never wraps (house rule), so it tightens as the card narrows: the
   Fan word goes first, then an action with a short word takes it, then an
   action with an icon is its icon alone; past that an action's word ends in
   an ellipsis (it is the one part of the row that shrinks). */
@container (max-width:470px){.cl-seglab{display:none}.cl-seg button{padding:0 7px}.cl-div{margin:0 4px}}
@container (max-width:420px){.cl-long{display:none}.cl-short{display:inline-block}}
@container (max-width:370px){.cl-run button.cl-hasic .cl-txt{display:none}}
@container (max-width:330px){.cl-seg{gap:2px}.cl-seg button{padding:0 5px}}
</style>`;
const MINUS = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"></path></svg>';
const PLUS = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>';
const segBtn = (label, domain, service, data, pressed, color) => `<button type="button"${color ? ` style="--c:${color}"` : ''} data-ctl="1" data-act="svc" data-domain="${esc(domain)}" data-service="${esc(service)}" data-data="${esc(JSON.stringify(data))}" aria-pressed="${!!pressed}">${esc(label)}</button>`;
const climateAction = (st) => {
  const a = st.attributes;
  if (off(st)) return [stateWord(st), 'var(--quiet)'];
  if (st.state === 'off') return ACTION.off;
  if (a.hvac_action) return ACTION[a.hvac_action] || [a.hvac_action, 'var(--muted)'];
  return [(MODE[st.state] || MODE.off)[0], 'var(--muted)'];
};
// Setpoints sent but not yet reported back (the panel sends them a moment
// after the last tap): the face shows them at once, muted until confirmed.
export const climatePending = new Map(); // entity → { t, lo, hi, until }

// A thermostat's own routines (`options.actions`): a script that drops the
// humidity, a boost, an away setback. Up to four, at the end of the face's
// one control row (it never wraps, house rule): each runs on tap and reads as
// pressed while it runs. Built in, so a house never has to copy this card's
// code to add one (a copy pauses on every Morph update). Each is an id, or
//   { entity, label, short, running, icon, color, modes }
// label (its name otherwise), short (the word when the row is narrow),
// running (the word while a script runs), icon (a Morph icon name), color (a
// Morph hue: sky, rose, amber, teal, violet, indigo, peach, lime, sand) and
// modes (the hvac modes it is offered in; while running it always shows).
const CLIMATE_ACTION_DOMAINS = ['script', 'button', 'input_button', 'scene'];
const CLIMATE_ACTION_HUES = ['sky', 'rose', 'amber', 'teal', 'violet', 'indigo', 'peach', 'lime', 'sand'];
function climateActions(ctx, st) {
  const list = ctx.card.options && ctx.card.options.actions;
  if (!Array.isArray(list)) return '';
  const btns = list.slice(0, 4).map((x) => {
    const o = typeof x === 'string' ? { entity: x } : x && typeof x === 'object' ? x : {};
    const id = o.entity;
    if (typeof id !== 'string') return '';
    const domain = domainOf(id);
    if (!CLIMATE_ACTION_DOMAINS.includes(domain)) return '';
    const ast = ctx.hass.states[id];
    if (!ast || ast.state === 'unavailable') return '';
    const running = domain === 'script' && ast.state === 'on';
    const modes = o.modes == null ? null : [].concat(o.modes).map(String);
    if (modes && !running && !modes.includes(st.state)) return '';
    const label = String(o.label || friendly(ctx.hass, id));
    const word = running && o.running ? String(o.running) : label;
    const text = o.short && !(running && o.running)
      ? `<span class="cl-txt cl-long">${esc(word)}</span><span class="cl-txt cl-short">${esc(String(o.short))}</span>`
      : `<span class="cl-txt">${esc(word)}</span>`;
    const hue = CLIMATE_ACTION_HUES.includes(o.color) ? `var(--${o.color})` : 'var(--violet)';
    const ic = o.icon ? icon(String(o.icon), { size: 13, active: running }) : '';
    const service = domain === 'script' || domain === 'scene' ? 'turn_on' : 'press';
    return `<button type="button"${ic ? ' class="cl-hasic"' : ''} style="--c:${hue}" data-ctl="1" data-act="svc" data-domain="${esc(domain)}" data-service="${service}" data-data="${esc(JSON.stringify({ entity_id: id }))}" aria-pressed="${running}" aria-label="${esc(running ? `${label}, running` : label)}" title="${esc(word)}">${ic}${text}</button>`;
  }).filter(Boolean);
  return btns.length ? `<span class="row cl-run" style="gap:0"><div class="cl-seg" role="group" aria-label="${esc(ctx.name)} routines">${btns.join('')}</div></span>` : '';
}
const climate = {
  item: { span: 2, grow: 3, dir: 'side', want: 4, hk: 't' },
  accent: (ctx) => (ctx.st ? climateAction(ctx.st)[1] : 'var(--quiet)'),
  face: (ctx) => {
    const st = ctx.st; if (!st) return `<div class="box"><b>${esc(ctx.name)}</b><span class="sm">Missing</span></div>`;
    const a = st.attributes; const e = ctx.card.entity;
    const cur = a.current_temperature;
    const [actWord, actColor] = climateAction(st);
    const hint = ctx.hint && ctx.hint.startsWith('tap to edit') ? ctx.hint : '';
    // #764: a thermostat that stopped answering keeps its last attributes;
    // its temperature is the last one heard, greyed, and it has no setpoints,
    // controls or running state to show until it answers again.
    if (off(st)) return goneBox(ctx, cur != null && isFinite(Number(cur)) ? Number(cur).toFixed(1) + '°' : '—', 'big');
    const fmtT = (v) => (v == null ? '—' : esc(Number.isInteger(Number(v)) ? v : Number(v).toFixed(1)) + '°');
    const pd = climatePending.get(e); const pend = pd && pd.until > Date.now() ? pd : null;
    const stepper = (label, v0, k) => { const pv = pend ? pend[k] : null; const v = pv != null ? pv : v0; const waiting = pv != null && Number(pv) !== Number(v0); return `<div class="cl-set"><span class="cl-lab"${label === 'Heat' ? ' style="color:var(--rose)"' : label === 'Cool' ? ' style="color:var(--sky)"' : ''}>${esc(label)}</span><div class="cl-step"><button type="button" class="cl-sq" data-ctl="1" data-act="tgt" data-k="${k}" data-v="-1" aria-label="Lower ${esc(ctx.name)} ${esc(label.toLowerCase())} setpoint">${MINUS}</button><span class="cl-val${waiting ? ' pend' : ''}" aria-live="polite">${fmtT(v)}</span><button type="button" class="cl-sq" data-ctl="1" data-act="tgt" data-k="${k}" data-v="1" aria-label="Raise ${esc(ctx.name)} ${esc(label.toLowerCase())} setpoint">${PLUS}</button></div></div>`; };
    let sets = '';
    if (st.state !== 'off') {
      if (a.temperature != null) sets = stepper(st.state === 'heat' ? 'Heat' : st.state === 'cool' ? 'Cool' : 'Set', a.temperature, 't');
      else if (a.target_temp_low != null || a.target_temp_high != null) sets = stepper('Heat', a.target_temp_low, 'lo') + stepper('Cool', a.target_temp_high, 'hi');
    }
    const modes = (a.hvac_modes || []).slice().sort((x, y) => MODE_ORDER.indexOf(x) - MODE_ORDER.indexOf(y));
    const fans = (a.fan_modes || []).slice().sort((x, y) => (x === 'auto' ? -1 : y === 'auto' ? 1 : 0));
    const modeSeg = modes.length ? `<div class="cl-seg" role="group" aria-label="${esc(ctx.name)} mode">${modes.map((m) => segBtn((MODE[m] || [m])[0], 'climate', 'set_hvac_mode', { entity_id: e, hvac_mode: m }, st.state === m, m === 'heat' ? 'var(--rose)' : m === 'cool' || m === 'dry' ? 'var(--sky)' : '')).join('')}</div>` : '';
    // The system's blower as a small fan beside its fan modes: still at rest,
    // turning while air is moving (house change).
    const moving = ['cooling', 'heating', 'fan', 'drying', 'preheating', 'defrosting'].includes(a.hvac_action) || a.fan_mode === 'on' || a.fan_state === 'on';
    const fanGlyph = `<span class="cl-fan${moving ? ' on' : ''}">${icon('fan', { size: 13, active: st.state !== 'unavailable', dur: moving ? '1.3s' : FAN_STILL })}</span>`;
    const fanSeg = fans.length ? `<span class="row" style="gap:0">${modeSeg ? '<span class="cl-div"></span>' : ''}${fanGlyph}<span class="cl-seglab">Fan</span><div class="cl-seg" role="group" aria-label="${esc(ctx.name)} fan">${fans.map((m) => segBtn(m[0].toUpperCase() + m.slice(1), 'climate', 'set_fan_mode', { entity_id: e, fan_mode: m }, a.fan_mode === m)).join('')}</div></span>` : '';
    // The thermostat's routines (options.actions) end the same row.
    const runSeg = climateActions(ctx, st);
    const acting = ['heating', 'cooling'].includes(a.hvac_action);
    return `${CLIMATE_CSS}<div class="box" style="box-shadow:inset 0 0 0 1px ${acting ? mix(actColor, 30) : 'var(--line)'}">
<div class="cl-head"><b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${hint ? `<span class="hint">${esc(hint)}</span>` : ''}<span class="cl-dot${['heating', 'cooling', 'drying', 'fan'].includes(a.hvac_action) ? ' on' : ''}" style="background:${actColor};color:${actColor}"></span><span class="cl-act" style="color:${actColor === 'var(--quiet)' ? 'var(--quiet)' : actColor}">${esc(actWord)}</span></div>
<div class="cl-main"><div class="cl-now"><span class="big">${cur != null ? fmtT(cur) : '—'}</span><span class="small">${a.current_humidity != null ? esc(Math.round(a.current_humidity)) + '% humidity' : 'now'}</span></div>
${sets ? `<div class="cl-sets">${sets}</div>` : `<span class="small" style="margin-left:auto">${st.state === 'off' ? 'System off' : ''}</span>`}</div>
<div class="cl-ctl">${modeSeg}${fanSeg}${runSeg}</div></div>`;
  },
  more: (ctx) => {
    // With a detail (HVAC performance) the opened card is that detail; the
    // controls already live on the face.
    if (ctx.card.options && ctx.card.options.detail) return '';
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    if ((a.preset_modes || []).length) parts.push(blockLabel('Preset') + words(a.preset_modes.map((m) => svcBtn(m, 'climate', 'set_preset_mode', { entity_id: e, preset_mode: m }, { pressed: a.preset_mode === m }))));
    return parts.join('') + histBlock(ctx, 'Runs');
  },
  tap: () => null,
};

// ---------------------------------------------------------------- readings

function warmth(v, unit) {
  const c = String(unit || '').includes('F') ? (v - 32) / 1.8 : v;
  if (!isFinite(c)) return 'var(--muted)';
  // The prototype's bands, which are fine enough to tell rooms of one house
  // apart: 69°F and under is cool, 71.5 comfortable, 73.5 warm, 75.5 hot.
  const f = c * 1.8 + 32;
  return f <= 69 ? 'var(--sky)' : f <= 71.5 ? 'var(--teal)' : f <= 73.5 ? 'var(--sand)' : f <= 75.5 ? 'var(--amber)' : 'var(--rose)';
}

function sparkline(hass, eid, color, unit) {
  const now = Date.now();
  const rows = history.stats(hass, eid, now - 86400000, now, 'hour');
  if (!rows || rows.error || rows.length < 2) return '<div style="height:22px"></div>';
  const pts = rows.filter((r) => r.mean != null && isFinite(r.mean)), vals = pts.map((r) => r.mean);
  if (vals.length < 2) return '<div style="height:22px"></div>';
  let lo = Math.min(...vals), hi = Math.max(...vals); const m = (hi - lo) * 0.18 || 1; lo -= m; hi += m;
  const d = vals.map((v, i) => (i ? 'L' : 'M') + (i / (vals.length - 1) * 200).toFixed(1) + ' ' + (22 - (v - lo) / (hi - lo) * 22).toFixed(1)).join('');
  // A line has no marks of its own, so each hour gets an unseen full-height column for the hover
  // to read (house change); the box is the div, since the helper draws into an HTML element.
  const cw = 200 / (vals.length - 1);
  const hit = pts.map((r, i) => `<rect x="${Math.max(0, i * cw - cw / 2).toFixed(1)}" y="0" width="${(Math.min(200, i * cw + cw / 2) - Math.max(0, i * cw - cw / 2)).toFixed(1)}" height="22" fill="transparent" data-tip="${esc(new Date(r.t).toLocaleTimeString([], { hour: 'numeric' }))} · ${esc(fmt(r.mean, unit))}"></rect>`).join('');
  return `<div data-hv style="height:22px"><svg viewBox="0 0 200 22" preserveAspectRatio="none" style="width:100%;height:22px;display:block">${hit}<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"></path></svg></div>`;
}

// #764: the face of something that has stopped answering, for every card
// that shows a figure: the last figure it had (or —) greyed, the state in
// words where the live state would be, and when it was last heard from.
function goneBox(ctx, figure, size, ic, more) {
  const said = more || `${stateWord(ctx.st, ctx.hass)} · ${lastSeen(ctx.st)}`;
  return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${ic || ''}<b class="ttl">${esc(ctx.name)}</b>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div><div class="rowb gonerow"><span class="${size} gone">${esc(figure)}</span><span class="sm goneword">${esc(said)}</span></div></div>`;
}

// #787: a moisture sensor that reads 0 is checked against its last day: one
// that fell straight there is a dead probe, not dry soil.
function deadProbe(ctx) {
  const st = ctx.st;
  if (!isMoisture(st) || parseFloat(st.state) !== 0) return '';
  const now = Date.now();
  const rows = history.stats(ctx.hass, ctx.card.entity, now - 86400000, now, '5minute');
  if (!Array.isArray(rows)) return '';
  return probeOffline(ctx.hass, ctx.card.entity, rows.map((r) => [r.t, r.mean]).concat([[now, 0]]));
}

const sensor = {
  item: { span: 1, grow: 2, dir: 'down', want: 3, hk: 'r' },
  accent: (ctx) => {
    const st = ctx.st; const dc = st && st.attributes.device_class;
    if (dc === 'temperature') return warmth(parseFloat(st.state), st.attributes.unit_of_measurement);
    if (dc === 'humidity') return 'var(--sky)';
    if (dc === 'power' || dc === 'energy') return 'var(--amber)';
    return 'var(--muted)';
  },
  face: (ctx) => {
    const st = ctx.st; const unit = (st && st.attributes.unit_of_measurement) || '';
    const dc = st && st.attributes.device_class;
    const mc = st ? minecraftStatus(ctx.hass, ctx.card.entity) : null;
    const ic = icon(dc === 'humidity' ? 'humid' : dc === 'temperature' ? 'thermo' : dc === 'power' || dc === 'energy' ? 'bolt' : 'dot', { color: ctx.accent, size: 16 });
    if (st && !mc && UNAVAILABLE.includes(st.state)) return goneBox(ctx, '—', 'mid', ic);
    const probe = deadProbe(ctx);
    if (probe) return goneBox(ctx, 'Offline', 'mid', ic, probe.replace(/^Sensor offline · /, ''));
    const val = !st ? 'Missing' : mc || (isNaN(parseFloat(st.state)) ? stateWord(st) : fmt(st.state, ''));
    const old = outdoorStale(ctx.hass, ctx.card.entity);
    // How recently it reported (household rule), beside the unit.
    const fresh = st ? ago(st.last_reported || st.last_updated) : '';
    const tail = [mc || isNaN(parseFloat(st && st.state)) ? '' : unit, off(st) && st ? stateWord(st) : fresh].filter(Boolean).join(' · ');
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)${old ? ';opacity:.6' : ''}"><div class="row">${ic}<b style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(ctx.name)}</b><span class="flex1"></span>${old ? `<span class="hint">${esc(old)}</span>` : ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div><div class="rowb"><span class="mid"${mc ? ' style="font-size:18px;font-weight:500;letter-spacing:0"' : ''}>${esc(val)}</span><span class="sm">${esc(tail)}</span></div>${st ? sparkline(ctx.hass, ctx.card.entity, ctx.accent, unit) : ''}</div>`;
  },
  more: (ctx) => histBlock(ctx),
  // A reading has nothing to switch: tap opens it in place (household rule).
  tap: () => null,
};

const readings = {
  item: { span: 3, grow: 4, dir: 'down', want: 4, full: true },
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const first = history.readingsFirst(ctx.hass, ctx.card.entities);
    const unit = (first && first.attributes.unit_of_measurement) || ctx.hass.config.unit_system.temperature;
    const dc = first && first.attributes.device_class;
    // Soil is coloured by how wet it is, never by warmth: 35% read as 35°C
    // and was drawn rose, as if it were hot.
    const color = isMoisture(first) ? (v) => (v < 25 ? 'var(--amber)' : v <= 45 ? 'var(--teal)' : v <= 60 ? 'var(--sky)' : 'var(--indigo)')
      : dc === 'humidity' ? (v) => (v < 35 ? 'var(--amber)' : v <= 55 ? 'var(--teal)' : v <= 60 ? 'var(--sky)' : 'var(--indigo)') : (v) => warmth(v, unit);
    return `<div class="box ov" style="box-shadow:inset 0 0 0 1px var(--line)">${history.readings(ctx.hass, ctx.card, ctx.H, color, { name: ctx.card.name || (dc === 'humidity' ? 'Humidity' : 'Temperature'), hint: ctx.hint })}</div>`;
  },
  more: () => '',
  tap: () => null,
  noOpen: true,
};

const meter = {
  item: { span: 2, grow: 3, dir: 'down', want: 3, hk: 'mt' },
  accent: (ctx) => (ctx.st && /water|gas/.test(ctx.st.attributes.device_class || '') ? 'var(--sky)' : 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const unit = (st && st.attributes.unit_of_measurement) || '';
    const seen = lastSeen(st);
    const now = Date.now(); const d0 = new Date(); d0.setHours(0, 0, 0, 0);
    const week = st ? history.stats(ctx.hass, ctx.card.entity, d0.getTime() - 6 * 86400000, now, 'day') : null;
    const ok = week && !week.error && week.length;
    // Until today has a statistics row, the last row is YESTERDAY's total,
    // and calling it today's was a day off.
    const hasToday = ok && week[week.length - 1].t >= d0.getTime();
    const today = hasToday ? week[week.length - 1].change : ok ? 0 : null;
    const vals = ok ? week.map((w) => w.change || 0) : [];
    const hi = Math.max(1e-6, ...vals);
    const bars = ok ? `<div class="cols" style="height:40px;gap:4px">${week.map((w, i) => `<span class="colbar" role="img" aria-label="${esc(new Date(w.t).toLocaleDateString([], { weekday: 'short' }) + ' · ' + fmt(vals[i], unit))}" style="flex:1;height:${Math.max(2, vals[i] / hi * 38)}px;background:${mix(ctx.accent, hasToday && i === vals.length - 1 ? 85 : 45)}"></span>`).join('')}</div>` : '';
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon(/water/.test((st && st.attributes.device_class) || '') ? 'water' : 'bolt', { color: ctx.accent, size: 16 })}<b style="font-size:13px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div><div class="rowb"><span class="mid${seen ? ' gone' : ''}">${today != null ? esc(fmt(today, '')) : '—'}</span><span class="sm">${esc(unit)} today${seen ? ' · ' + esc(seen) : ''}</span></div>${bars}</div>`;
  },
  more: (ctx) => histBlock(ctx),
  tap: () => null,
};

// ------------------------------------------------------------------ media

const media = {
  item: { span: 2, grow: 3, dir: 'side', want: 4, hk: 'm' },
  accent: () => 'var(--violet)',
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {}; const e = ctx.card.entity;
    const playing = st && st.state === 'playing';
    // #764: a player that stopped answering keeps its last track in its
    // attributes; it says it is unavailable and when it was last seen, not
    // what it was playing.
    const gone = off(st);
    const title = gone ? (st ? stateWord(st, ctx.hass) : 'Missing') : a.media_title || stateWord(st, ctx.hass);
    const sub = gone ? (st ? lastSeen(st) : '') : [a.media_artist, a.app_name || a.source].filter(Boolean).join(' · ');
    let prog = '';
    if (!gone && a.media_duration && a.media_position != null) {
      // Drawn from the last reported position and RUN to the end by the
      // stylesheet, so it moves between the player's updates rather than
      // freezing until the next one.
      const at = Date.parse(a.media_position_updated_at || '') || Date.now();
      const p0 = clamp(a.media_position / a.media_duration * 100, 0, 100);
      const left = Math.max(0, a.media_duration - a.media_position);
      const anim = playing ? `animation:mprog ${left.toFixed(1)}s linear forwards;animation-delay:-${Math.max(0, (Date.now() - at) / 1000).toFixed(1)}s;--p0:${p0.toFixed(2)}%` : '';
      prog = `<div style="height:3px;border-radius:2px;background:var(--line);margin-top:8px;overflow:hidden"><div class="mprog" style="height:3px;border-radius:2px;width:${p0.toFixed(1)}%;background:${ctx.accent};${anim}" data-k="prog-${esc(a.media_position_updated_at || '')}"></div></div>`;
    }
    const img = a.entity_picture ? `<img src="${esc(a.entity_picture)}" alt="" style="width:44px;height:44px;border-radius:10px;object-fit:cover;flex-shrink:0">` : icon(a.device_class === 'tv' ? 'tv' : 'speaker', { color: playing ? ctx.accent : 'var(--quiet)', active: playing, size: 22 });
    const t = (svc, label, path) => `<button type="button" class="sq" data-ctl="1" data-act="svc" data-domain="media_player" data-service="${svc}" data-data="${esc(JSON.stringify({ entity_id: e }))}" aria-label="${label}"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="${path}"></path></svg></button>`;
    return `<div class="box" style="box-shadow:inset 0 0 0 1px ${playing ? mix(ctx.accent, 30) : 'var(--line)'}"><div class="row">${img}<span class="nv" style="flex:1"><b>${esc(ctx.name)}</b><span style="color:${playing ? 'var(--text)' : 'var(--muted)'}">${esc(title)}</span>${sub ? `<span class="small">${esc(sub)}</span>` : ''}</span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}
${st && !off(st) && st.state !== 'off' ? `<div class="row" style="gap:4px">${t('media_previous_track', 'Previous', 'M6 6h2v12H6zM20 6v12L9 12z')}${t('media_play_pause', playing ? 'Pause' : 'Play', playing ? 'M7 5h4v14H7zM13 5h4v14h-4z' : 'M7 5l12 7-12 7z')}${t('media_next_track', 'Next', 'M16 6h2v12h-2zM4 6v12l11-6z')}</div>` : ''}</div>${prog}</div>`;
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    if (a.volume_level != null) parts.push(`${blockLabel('Volume')}<input type="range" class="mrange" min="0" max="100" value="${Math.round(a.volume_level * 100)}" data-act="range" data-domain="media_player" data-service="volume_set" data-key="volume_level" data-scale="0.01" data-entity="${esc(e)}" aria-label="Volume">`);
    if ((a.source_list || []).length) parts.push(blockLabel('Source') + words(a.source_list.slice(0, 16).map((s) => svcBtn(s, 'media_player', 'select_source', { entity_id: e, source: s }, { pressed: a.source === s }))));
    parts.push(words([svcBtn(ctx.st && ctx.st.state === 'off' ? 'Turn on' : 'Turn off', 'media_player', ctx.st && ctx.st.state === 'off' ? 'turn_on' : 'turn_off', { entity_id: e })]));
    return parts.join('') + histBlock(ctx);
  },
  tap: (ctx) => ({ domain: 'media_player', service: 'media_play_pause', data: { entity_id: ctx.card.entity } }),
};

// ----------------------------------------------------------------- camera

const CAM_STATE = { idle: 'Quiet', streaming: 'Live', recording: 'Recording' };
const camera = {
  item: { span: 1, grow: 2, dir: 'side', want: 3, hk: 'c' },
  accent: () => 'var(--indigo)',
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {};
    const bucket = Math.floor(Date.now() / 10000);
    const live = st && !UNAVAILABLE.includes(st.state);
    // A closed tile is a snapshot every 10 s, so it says Still; an opened
    // one streams, and only then says Live (household rule).
    const src = live && a.access_token ? `/api/camera_proxy/${encodeURIComponent(ctx.card.entity)}?token=${encodeURIComponent(a.access_token)}&t=${bucket}` : '';
    const sub = !st ? 'Missing' : off(st) ? stateWord(st) : ctx.open ? 'Live' : CAM_STATE[st.state] === 'Live' ? 'Still' : CAM_STATE[st.state] || stateWord(st);
    const stream = ctx.open && live && a.access_token ? `/api/camera_proxy_stream/${encodeURIComponent(ctx.card.entity)}?token=${encodeURIComponent(a.access_token)}` : '';
    const pic = stream || src;
    return `<div class="camtile" style="box-shadow:inset 0 0 0 1px ${st && st.state === 'recording' ? mix(ctx.accent, 30) : 'var(--line)'}"><div class="camhead"><b>${esc(ctx.name)}</b><span class="flex1"></span><span class="small">${esc(sub)}</span></div><div class="campic"${ctx.open ? ' style="height:auto;aspect-ratio:16/9"' : ''}><span class="camnone">${esc(!st || UNAVAILABLE.includes(st.state) ? 'Offline' : pic ? (stream ? 'Loading the picture…' : 'No picture yet') : 'No picture')}</span>${pic ? `<img class="cam" src="${esc(pic)}" alt="${esc(ctx.name)}" loading="lazy" onerror="this.style.visibility='hidden';this.previousElementSibling.textContent='No picture'">` : ''}${live ? `<span class="live"><i${stream ? '' : ' class="still"'}></i>${stream ? 'LIVE' : 'Still'}</span>` : ''}${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div></div>`;
  },
  more: (ctx) => histBlock(ctx, 'Events'),
  tap: () => null,
};

// -------------------------------------------------------------- the lists

const WORDS = {
  door: ['Open', 'Closed'], window: ['Open', 'Closed'], garage_door: ['Open', 'Closed'], opening: ['Open', 'Closed'],
  moisture: ['Wet', 'Dry'], smoke: ['Smoke', 'Clear'], gas: ['Gas', 'Clear'], carbon_monoxide: ['CO', 'Clear'],
  motion: ['Motion', 'Clear'], occupancy: ['Occupied', 'Empty'], presence: ['Here', 'Away'], lock: ['Unlocked', 'Locked'],
  battery: ['Low', 'OK'], problem: ['Problem', 'OK'], safety: ['Unsafe', 'Safe'], vibration: ['Shaking', 'Still'],
};
// Two tones: something open, wet or smoking wants attention (rose); a room
// with motion or someone in it is only activity (amber).
const ACTIVITY = ['motion', 'occupancy', 'presence', 'vibration'];
// Something a person switched on (a zone, a pump, a valve) is activity too: only a sensor reading open, wet or smoking is something that needs them.
const isActivity = (st) => !!(st && (ACTIVITY.includes(st.attributes.device_class) || !/^binary_sensor\./.test(st.entity_id || 'binary_sensor.')));
export const listWord = (st) => {
  if (!st) return ['Missing', false];
  if (UNAVAILABLE.includes(st.state)) return ['Unavailable', false];
  const valve = /^valve\./.test(st.entity_id || '');
  const w = WORDS[st.attributes.device_class] || BINARY_WORDS[st.attributes.device_class] || (valve ? ['Open', 'Closed'] : ['On', 'Off']);
  const on = st.state === 'on' || (valve && ['open', 'opening'].includes(st.state));
  return [on ? w[0] : w[1], on];
};
// One row of a list. The BRUH Minecraft server's Online sensor reads the
// server's status (who is playing, or Offline), and a server that answers is
// not something open that wants attention.
const listRow = (ctx, e) => {
  const st = ctx.hass.states[e]; const mc = st ? minecraftStatus(ctx.hass, e) : null;
  const [w, on] = mc ? [mc, false] : listWord(st);
  return { e, w, on, mc: !!mc, act: isActivity(st), name: shortName(friendly(ctx.hass, e), ctx.sec.title), st };
};
const list = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: (ctx) => {
    const rows = (ctx.card.entities || []).map((e) => listRow(ctx, e));
    if (rows.some((r) => r.on && !r.act)) return 'var(--rose)';
    if (rows.some((r) => r.on)) return 'var(--amber)';
    return 'var(--indigo)';
  },
  face: (ctx) => {
    const rows = (ctx.card.entities || []).map((e) => listRow(ctx, e));
    // A list with nothing in it is not drawn outside Edit (morph-panel's modelSection); in Edit it says how to fill it, not "All quiet" over no rows.
    if (!rows.length) return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line);min-height:56px;padding:8px 14px;justify-content:center">${ctx.card.name ? `<b style="font-size:14px">${esc(ctx.name)}</b>` : ''}<span class="small">Nothing in this list yet. Hold it and tell brAIn what to add.</span></div>`;
    rows.sort((a, b) => (b.on - a.on) || (a.act - b.act));
    const openRows = rows.filter((r) => r.on);
    const attention = openRows.filter((r) => !r.act);
    const tone = attention.length ? 'var(--rose)' : openRows.length ? 'var(--amber)' : 'var(--teal)';
    // "All closed" in the kind's own word when every row is one kind.
    const kinds = new Set(rows.map((r) => (r.st && r.st.attributes.device_class) || ''));
    const mc = rows.length === 1 && rows[0].mc;
    // The summary counts; it never names a row and repeats its state, because the rows are right under it ("Zone 2 on" over a row that says "Zone 2 · On" said it twice).
    const summary = mc ? rows[0].w : openRows.length
      ? (openRows.length === 1 ? (attention.length ? '1 needs you' : '1 active') : `${openRows.length} of ${rows.length} ${attention.length ? 'need you' : 'active'}`)
      : kinds.size === 1 && rows[0] ? `All ${listWord({ ...rows[0].st, state: 'off' })[0].toLowerCase()}` : 'All quiet';
    // Closed, a list is one 56px row (household, Oct 2026: door cards took a
    // row per sensor to say one thing): an icon, the summary, and each sensor
    // as a short "Name word · time" segment that opens its history.
    if (!ctx.open) {
      const nm = (ctx.card.options && ctx.card.options.names) || {};
      const one = rows.length === 1 && rows[0];
      const head = one ? `${nm[one.e] || one.name} ${one.w.toLowerCase()}` : summary;
      const seg = (r) => `<button type="button" class="lseg" data-ctl="1" data-act="member" data-v="${esc(r.e)}" data-member="${esc(r.e)}" aria-pressed="${ctx.member === r.e}">${one ? '' : `${esc(nm[r.e] || r.name)} <span style="color:${r.on ? (r.act ? 'var(--amber)' : 'var(--rose)') : 'var(--quiet)'};font-weight:600">${esc(r.w.toLowerCase())}</span> `}${r.st ? esc(since(r.st.last_changed).replace('since ', '')) : ''}</button>`;
      return `<style>.lseg{all:unset;cursor:pointer;border-radius:6px;white-space:nowrap}.lseg:hover{color:var(--text)}.lseg:focus-visible{outline:2px solid var(--sky)}</style><div class="box" style="box-shadow:inset 0 0 0 1px ${openRows.length ? mix(tone, 35) : 'var(--line)'};min-height:56px;padding:8px 14px;justify-content:center"><div class="row" style="gap:12px">${icon(rows.some((r) => r.st && ['door', 'window', 'garage_door', 'opening'].includes(r.st.attributes.device_class)) ? 'door' : 'shield', { color: tone, active: !!attention.length, size: 20 })}<span class="nv" style="flex:1;min-width:0"><b style="font-size:14px;color:${openRows.length ? tone : 'var(--text)'}">${esc(head)}</b><span class="small" style="display:flex;flex-wrap:wrap;gap:0 10px">${rows.slice(0, 6).map(seg).join('')}</span></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div></div>`;
    }
    const shown = rows;
    return `<div class="box" style="box-shadow:inset 0 0 0 1px ${openRows.length ? mix(tone, 35) : 'var(--line)'};padding:12px 12px 8px 16px"><div class="rowb">${ctx.card.name ? `<b style="font-size:14px">${esc(ctx.name)}</b>` : ''}<span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${tone}">${esc(summary)}</span></div>
${shown.map((r) => `<button type="button" class="lrow" data-ctl="1" data-act="member" data-v="${esc(r.e)}" data-member="${esc(r.e)}" aria-pressed="${ctx.member === r.e}" style="padding:0 4px;min-height:44px;align-items:center"><span class="lx"><span>${esc(r.name)}</span></span><span style="font-size:13px;font-weight:600;color:${r.on ? (r.act ? 'var(--amber)' : 'var(--rose)') : 'var(--quiet)'}">${esc(r.w)}</span><span class="small">${r.st ? esc(since(r.st.last_changed)) : ''}</span></button>`).join('')}${rows.length > shown.length ? `<span class="small" style="padding:4px">+${rows.length - shown.length} more</span>` : ''}</div>`;
  },
  more: (ctx) => {
    if (!ctx.member) return '';
    const st = ctx.hass.states[ctx.member];
    return history.block(ctx.hass, { entity: ctx.member, type: 'list' }, st, ctx.H, ctx.accent, friendly(ctx.hass, ctx.member));
  },
  tap: () => null,
};

// ------------------------------------------------- person, weather, alarm

const person = {
  item: { span: 1, grow: 2, dir: 'down', want: 2, hk: 's' },
  accent: (ctx) => (ctx.st && ctx.st.state === 'home' ? 'var(--peach)' : 'var(--quiet)'),
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {};
    const home = st && st.state === 'home';
    const where = !st ? 'Missing' : home ? 'Home' : st.state === 'not_home' ? 'Away' : st.state;
    // The initial is always drawn; a photo lies over it and is hidden if it does not load, so a missing picture never shows a broken-image mark or its alt text.
    const av = `<span class="avatar" style="background:${mix(ctx.accent, 25)};color:${ctx.accent}">${esc((ctx.name || '?')[0])}${a.entity_picture ? `<img src="${esc(a.entity_picture)}" alt="" onerror="this.style.visibility='hidden'">` : ''}</span>`;
    return `<div class="strip" style="box-shadow:inset 0 0 0 1px ${home ? mix(ctx.accent, 30) : 'var(--line)'};background:${home ? mix(ctx.accent, 8) : 'transparent'}"><div class="sline">${av}<span class="nv"><b>${esc(ctx.name)}</b><span class="vs" style="color:${ctx.accent}">${statusHtml(st ? [where, since(st.last_changed).replace('since ', '')] : [where])}</span></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div></div>`;
  },
  more: (ctx) => histBlock(ctx, 'Today'),
  tap: () => null,
};

const WEATHER = { 'clear-night': 'Clear', cloudy: 'Cloudy', fog: 'Fog', hail: 'Hail', lightning: 'Storms', 'lightning-rainy': 'Storms', partlycloudy: 'Partly cloudy', pouring: 'Pouring', rainy: 'Rain', snowy: 'Snow', 'snowy-rainy': 'Sleet', sunny: 'Sunny', windy: 'Windy', 'windy-variant': 'Windy', exceptional: 'Unusual' };
const FORECASTS = new Map();
function forecast(hass, eid, kind) {
  const key = eid + '|' + kind; const hit = FORECASTS.get(key);
  if (hit && Date.now() - hit.at < 1800000) return hit.data;
  if (hit && hit.pending) return hit.data;
  const entry = { pending: true, at: Date.now(), data: hit ? hit.data : null }; FORECASTS.set(key, entry);
  hass.callWS({ type: 'call_service', domain: 'weather', service: 'get_forecasts', service_data: { type: kind }, target: { entity_id: eid }, return_response: true })
    .then((r) => { entry.data = (r && r.response && r.response[eid] && r.response[eid].forecast) || []; })
    .catch(() => { entry.data = []; })
    .finally(() => { entry.pending = false; entry.at = Date.now(); window.dispatchEvent(new Event('morph-data')); });
  return entry.data;
}
const WX_METRICS = [
  { id: 'temp', word: 'Temp', key: 'temperature', name: 'Temperature', unit: '°', color: 'var(--amber)' },
  { id: 'humidity', word: 'Humidity', key: 'humidity', name: 'Humidity', unit: '%', color: 'var(--teal)' },
  { id: 'rain', word: 'Rain', key: 'precipitation_probability', name: 'Chance of rain', unit: '%', color: 'var(--sky)' },
  { id: 'clouds', word: 'Clouds', key: 'cloud_coverage', name: 'Cloud cover', unit: '%', color: 'var(--violet)' },
  { id: 'radar', word: 'Radar' },
];
// The days ahead (Oct 2026): from 6 PM the row starts at tomorrow (today is
// mostly over), and each day is its low and high on one shared scale, so a
// heat spell or a cold front reads at a glance instead of as columns of
// numbers spread across the card.
function wxDays(all) {
  const now = new Date(); const today = now.toDateString();
  const days = all.filter((d) => !(now.getHours() >= 18 && new Date(d.datetime).toDateString() === today)).slice(0, 5);
  if (!days.length) return '';
  const lows = days.map((d) => (d.templow != null ? d.templow : d.temperature)); const highs = days.map((d) => d.temperature);
  const lo = Math.min(...lows), hi = Math.max(...highs), sp = Math.max(1, hi - lo);
  const P = (v) => (((v - lo) / sp) * 100).toFixed(1);
  return `<div style="display:grid;grid-template-columns:repeat(${days.length},minmax(0,1fr));gap:4px 14px;margin-top:10px">${days.map((d, i) => {
    const dl = lows[i], dh = highs[i];
    return `<div style="min-width:0;display:flex;flex-direction:column;gap:3px;font-size:12px"><span class="small">${esc(i === 0 && new Date(d.datetime).toDateString() === today ? 'Today' : new Date(d.datetime).toLocaleDateString([], { weekday: 'short' }))}</span><span style="display:flex;justify-content:space-between;font-variant-numeric:tabular-nums"><span class="small">${d.templow != null ? esc(Math.round(dl)) + '°' : ''}</span><b>${esc(Math.round(dh))}°</b></span><span aria-hidden="true" style="position:relative;height:4px;border-radius:2px;background:var(--chip)"><i style="position:absolute;top:0;bottom:0;left:${P(dl)}%;right:${(100 - +P(dh)).toFixed(1)}%;border-radius:2px;background:linear-gradient(90deg,var(--sky),${dh >= 85 ? 'var(--peach)' : dh >= 72 ? 'var(--amber)' : 'var(--teal)'})"></i></span></div>`;
  }).join('')}</div>`;
}

const weather = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; if (!st) return `<div class="box"><b>${esc(ctx.name)}</b><span class="sm">Missing</span></div>`;
    if (off(st)) return goneBox(ctx, '—', 'big');
    const a = st.attributes; const unit = a.temperature_unit || '°';
    const days = forecast(ctx.hass, ctx.card.entity, 'daily') || [];
    const sunny = ['sunny', 'clear-night', 'partlycloudy'].includes(st.state);
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon(sunny ? 'sun' : 'cloud', { color: ctx.accent, active: true, size: 22, dur: '26s' })}<span class="big">${a.temperature != null ? esc(Math.round(a.temperature)) + '°' : '—'}</span><span class="nv" style="margin-left:6px"><b>${esc(WEATHER[st.state] || st.state)}</b><span class="small">${a.humidity != null ? esc(a.humidity) + '% humidity' : ''}${a.wind_speed != null ? ' · wind ' + esc(Math.round(a.wind_speed)) + ' ' + esc(a.wind_speed_unit || '') : ''}</span></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div>
${wxDays(days)}<span class="sr">${esc(unit)}</span></div>`;
  },
  // Words switch what the next-24-hours chart shows (the 'member' act keeps
  // the choice on the open card); Radar swaps the chart for a live map. A
  // metric the card's own service lacks is read from `options.forecast_from`.
  more: (ctx) => {
    const panning = ctx.member === 'radar-live';
    const show = panning ? 'radar' : WX_METRICS.find((m) => m.id === ctx.member) ? ctx.member : 'temp';
    const pick = words(WX_METRICS.map((m) => `<button type="button" class="wd" data-ctl="1" data-act="member" data-v="${m.id}" aria-pressed="${m.id === show}">${m.word}</button>`));
    if (show === 'radar') {
      const c = ctx.hass.config || {}; const o = ctx.card.options || {};
      const lat = Number(o.radar_lat != null ? o.radar_lat : c.latitude).toFixed(3), lon = Number(o.radar_lon != null ? o.radar_lon : c.longitude).toFixed(3);
      const src = `https://www.rainviewer.com/map.html?loc=${lat},${lon},${o.radar_zoom || 7}&oFa=0&oC=1&oU=0&oCS=1&oF=0&oAP=1&c=3&o=83&lm=1&layer=radar&sm=1&sn=1`;
      // The map does not take the page's swipes until it is tapped (another
      // network page inside the card should not steal a scroll).
      return pick + `<div data-ctl="1"${panning ? '' : ' data-act="member" data-v="radar-live"'} style="margin-top:8px;border-radius:12px;overflow:hidden;cursor:${panning ? 'auto' : 'pointer'}"><iframe src="${esc(src)}" title="Rain radar" loading="lazy" style="display:block;width:100%;height:300px;border:0;background:var(--sunk);pointer-events:${panning ? 'auto' : 'none'}"></iframe></div>`;
    }
    const m = WX_METRICS.find((x) => x.id === show);
    const sources = [ctx.card.entity, ...[].concat((ctx.card.options || {}).forecast_from || [])];
    let hours = []; let from = null;
    for (const eid of sources) {
      const h = (forecast(ctx.hass, eid, 'hourly') || []).slice(0, 24).filter((x) => typeof x[m.key] === 'number');
      if (h.length >= 2) { hours = h; from = eid; break; }
    }
    if (!hours.length) return pick + `<p class="sm">No hourly ${esc(m.word.toLowerCase())} forecast from this weather service.</p>`;
    const pts = hours.map((h) => [Date.parse(h.datetime), h[m.key]]);
    let note = '';
    if (show === 'rain') { const wet = hours.find((h) => h.precipitation_probability >= 40); note = wet ? 'Rain likely at ' + clock(wet.datetime) + '.' : 'No rain in the next day.'; }
    if (from !== ctx.card.entity) note += (note ? ' ' : '') + 'From ' + friendly(ctx.hass, from) + '.';
    // The metric words sit beside the chart's own label, not as a tab row above it.
    return `<div style="display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 16px">${blockLabel('Next 24 hours')}${pick}</div>` + history.lineChart([{ id: 'f', name: m.name, color: m.color, pts }], pts[0][0], pts[pts.length - 1][0], { unit: m.unit, key: 'wx:' + ctx.card.entity + ':' + show }) +
      (note ? `<p class="sm">${esc(note)}</p>` : '');
  },
  tap: () => null,
};

// The modes a panel offers, filtered by what it says it supports (ARM_HOME
// 1, ARM_AWAY 2, ARM_NIGHT 4); a panel that says nothing offers all.
const ALARM = [['disarmed', 'Off', 'alarm_disarm', 0], ['armed_home', 'Home', 'alarm_arm_home', 1], ['armed_away', 'Away', 'alarm_arm_away', 2], ['armed_night', 'Night', 'alarm_arm_night', 4]];
const alarmModes = (st) => { const f = st && st.attributes.supported_features; return ALARM.filter((m) => !m[3] || f == null || (f & m[3])); };
const alarm = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: (ctx) => (ctx.st && ctx.st.state === 'triggered' ? 'var(--rose)' : ctx.st && ctx.st.state.startsWith('armed') ? 'var(--indigo)' : 'var(--quiet)'),
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {};
    // options.toggle: a house that only uses Home and Off gets one switch between them.
    if (alarmToggle(ctx)) {
      const armed = st && st.state.startsWith('armed');
      const val = off(st) ? stateWord(st, ctx.hass) : ctx.confirm || (st.state === 'disarmed' ? 'Off' : st.state === 'armed_home' ? 'Home' : stateWord(st, ctx.hass));
      return stripFace({ kind: 'switch', icon: 'shield', accent: ctx.accent, active: armed || (st && st.state === 'triggered'), name: ctx.name, val, hint: ctx.hint });
    }
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon('shield', { color: ctx.accent, size: 18 })}<b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${ctx.accent}">${esc(ctx.confirm || stateWord(st, ctx.hass))}</span></div>
${a.code_format || off(st) ? '' : words(alarmModes(st).map((m) => svcBtn(m[1], 'alarm_control_panel', m[2], { entity_id: ctx.card.entity }, { pressed: st && st.state === m[0], confirm: m[0] === 'disarmed' ? 'Tap again to disarm' : '' })))}</div>`;
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const code = a.code_format ? `${blockLabel('Code')}<input class="fld" type="password" inputmode="numeric" data-alarm-code="1" autocomplete="off" aria-label="Alarm code">${words(alarmModes(ctx.st).map((m) => `<button type="button" class="wd" data-ctl="1" data-act="alarm" data-service="${m[2]}">${m[1]}</button>`))}` : '';
    return code + coverDetails(ctx) + histBlock(ctx);
  },
  // Toggle: Off arms Home; anything armed or triggered disarms, on a second tap.
  tap: (ctx) => {
    if (!alarmToggle(ctx) || off(ctx.st)) return null;
    const data = { entity_id: ctx.card.entity };
    return ctx.st.state === 'disarmed'
      ? { domain: 'alarm_control_panel', service: 'alarm_arm_home', data }
      : { domain: 'alarm_control_panel', service: 'alarm_disarm', data, confirm: 'Disarm the alarm?' };
  },
};
function alarmToggle(ctx) {
  const a = (ctx.st && ctx.st.attributes) || {};
  return !!(ctx.card.options && ctx.card.options.toggle) && !a.code_format;
}

// ------------------------------------------------------- scenes, the rest

// Scene words without the prefix they all share: "Den - Bright", "Den - Dim"
// read Bright, Dim. Scenes from different areas (a house-wide row) keep their
// whole names, since there the prefix is what tells them apart.
export function sceneWords(names) {
  const parts = names.map((n) => /^(.+?)\s+[-–]\s+(.+)$/.exec(String(n)));
  const p0 = parts[0] && parts[0][1].toLowerCase();
  const shared = parts.length > 0 && parts.every((m) => m && m[1].toLowerCase() === p0);
  return names.map((n, i) => (shared ? parts[i][2] : n));
}
function activeScene(hass, ids) {
  let best = null, bt = 0;
  ids.forEach((e) => { const st = hass.states[e]; const t = st ? Date.parse(st.state) : 0; if (t > bt) { bt = t; best = e; } });
  return Date.now() - bt < 12 * 3600000 ? best : null;
}
const scenes = {
  item: { span: 3, grow: 4, full: true },
  accent: () => 'var(--violet)',
  face: (ctx) => {
    const ids = ctx.card.entities || [];
    const cur = activeScene(ctx.hass, ids);
    const names = sceneWords(ids.map((e) => shortName(friendly(ctx.hass, e), ctx.sec.title)));
    return `<div class="scenes">${ids.map((e, i) => `<button type="button" class="wd" data-ctl="1" data-act="scene" data-v="${esc(e)}" aria-pressed="${cur === e}">${esc(names[i])}</button>`).join('')}</div>`;
  },
  more: () => '',
  tap: () => null,
  noOpen: true,
};

// A tile for something with no card of its own (an oven, a humidifier, a
// valve) still has a picture: by what it is called, then by its domain, and
// never the empty ring that read as a gap where the icon should be (#767).
const APPLIANCE = /\b(oven|stove|range|cooktop|cooker|microwave|dishwasher|washer|washing|dryer|fridge|freezer|kettle|toaster|coffee|fryer|grill|heater)\b/i;
const DOMAIN_ICON = { water_heater: 'thermo', humidifier: 'humid', dehumidifier: 'humid', valve: 'water', fan: 'fan', camera: 'camera', media_player: 'speaker', siren: 'bolt', remote: 'tv' };
const entityIcon = (ctx) => (APPLIANCE.test(`${ctx.name} ${ctx.card.entity}`) ? 'appliance' : DOMAIN_ICON[domainOf(ctx.card.entity)] || 'appliance');
// "Off since 4:02 PM": what it is doing and for how long, when it is idle.
const IDLE = ['off', 'idle', 'standby', 'closed', 'stopped', 'paused', 'docked', 'locked'];
const entity = {
  item: { ...STRIP, dir: 'down', want: 2 },
  accent: () => 'var(--quiet)',
  face: (ctx) => {
    const st = ctx.st; const unit = (st && st.attributes.unit_of_measurement) || '';
    const mc = st ? minecraftStatus(ctx.hass, ctx.card.entity) : null;
    const idle = st && !mc && IDLE.includes(st.state) && !unit;
    const val = !st ? 'Missing' : mc || (off(st) ? `${stateWord(st, ctx.hass)}${lastSeen(st) ? ' \u00b7 ' + lastSeen(st) : ''}` : idle ? [stateWord(st, ctx.hass), since(st.last_changed)] : isNaN(parseFloat(st.state)) ? stateWord(st, ctx.hass) : fmt(st.state, unit));
    return stripFace({ kind: 'none', two: off(st), sep: idle ? ' ' : ' \u00b7 ', icon: entityIcon(ctx), accent: ctx.accent, active: st && st.state === 'on', name: ctx.name, val, valColor: 'var(--muted)', hint: ctx.hint });
  },
  more: (ctx) => histBlock(ctx),
  tap: () => null,
};

const note = {
  item: { span: 2, grow: 4, full: true },
  accent: () => 'var(--quiet)',
  face: (ctx) => `<div class="note" style="background:var(--chip)"><p>${esc(ctx.card.text || '')}</p></div>`,
  more: () => '',
  tap: () => null,
  noOpen: true,
};

const lovelace = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: () => 'var(--violet)',
  face: (ctx) => `<div class="ll" data-ll="${esc(ctx.card.id)}"></div>`,
  more: () => '',
  tap: () => null,
  noOpen: true,
  host: true,
};

export const hollowList = (c) => !!c && c.type === 'list' && !(c.entities || []).length;
export const TYPES = { light, light_group: lightGroup, cover_group: lightGroup, fan_group: lightGroup, fan, cover, lock, switch: sw, button, vacuum, climate, sensor, readings, meter, media, camera, list, person, weather, alarm, scenes, entity, note, lovelace };

// A thing that is unavailable (or missing) is not switched or slid: a tap
// opens it in place instead, where its history shows when it went away, so a
// tap never ends in a service error.
const gone = (ctx) => !!(ctx && ctx.card && ctx.card.entity) && dead(ctx);
new Set(Object.values(TYPES)).forEach((T) => {
  const tap = T.tap, slide = T.slide;
  if (tap) T.tap = (ctx) => (gone(ctx) ? null : tap(ctx));
  if (slide) T.slide = (ctx) => (gone(ctx) ? null : slide(ctx));
});

// A tile's role for a screen reader: a slider when it has a level, a switch
// when a tap toggles it, a button that opens otherwise.
export function tileAria(T, ctx, name) {
  const slide = T.slide ? T.slide(ctx) : null;
  const tap = T.tap ? T.tap(ctx) : null;
  const word = ctx.st ? stateWord(ctx.st, ctx.hass) : '';
  if (slide) { const v = slide.get(); return { role: 'slider', label: name, value: `${v}%`, now: v }; }
  // A tile that shows a pressable word beside its state is a button named by
  // both: "Garage, Closed. Open door" (the word itself is hidden from readers).
  const act = T.act ? T.act(ctx) : '';
  if (act) return { role: 'button', label: `${name}${word ? ', ' + word : ''}. ${act}`, expanded: !!ctx.open };
  if (tap && !tap.confirm && !tap.noop) return { role: 'switch', label: name, checked: !!(ctx.st && ['on', 'open', 'unlocked', 'playing'].includes(ctx.st.state)), value: word };
  return { role: 'button', label: `${name}${word ? ', ' + word : ''}`, expanded: !!ctx.open };
}

export function typeOf(card) {
  return TYPES[card.type] || TYPES.entity;
}

export const isFull = (card) => !!typeOf(card).item.full;
