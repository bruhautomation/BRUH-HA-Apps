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

import { esc, mix, clamp, lightColor, lightTone, fmt, since, clock, icon, friendly, shortName, UNAVAILABLE, domainOf } from './util.js';
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
const fanLevel = (p) => ['Low', 'Low', 'Medium', 'Medium', 'High', 'High'][Math.min(5, Math.floor(p / 20))];

// One wording for a state everywhere: "Armed home", "Unavailable", "Missing".
export function stateWord(st) {
  if (!st) return 'Missing';
  if (st.state === 'unavailable') return 'Unavailable';
  if (st.state === 'unknown') return 'Unknown';
  const w = String(st.state).replace(/_/g, ' ');
  return w ? w[0].toUpperCase() + w.slice(1) : '';
}

// When something ran or was pressed, as a person says it: "Ran 9:14 PM",
// "Pressed Mon 8:03 PM". A script that never ran says nothing.
export function whenWord(iso) {
  const t = Date.parse(iso || '');
  if (!t) return '';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return t >= today.getTime() ? clock(t) : new Date(t).toLocaleDateString([], { weekday: 'short' }) + ' ' + clock(t);
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
export function stripFace(o) {
  const active = !!o.active;
  const accent = o.accent;
  const fillW = clamp(o.pct == null ? 0 : o.pct, 0, 100);
  const fa = o.fillA || mix(accent, 34), fb = o.fillB || mix(accent, 12);
  let layer = '';
  if ((o.kind === 'fill' || o.kind === 'slats') && fillW > 0) {
    layer = `<div aria-hidden="true" class="fill" style="width:${fillW}%;background:linear-gradient(90deg, ${fa}, ${fb})"></div>`;
    // A blind's slats are drawn over the part that is OPEN: closed is plain.
    if (o.kind === 'slats') layer += `<div aria-hidden="true" class="slats" style="width:${fillW}%"></div>`;
    else layer += `<div aria-hidden="true" class="thumb" style="left:${fillW}%"></div>`;
  } else if (o.kind === 'lanes') {
    layer = `<div aria-hidden="true" class="lanes">${(o.lanes || []).map((l) => `<span class="lane" style="background:${l.on ? mix(l.color, 5) : 'transparent'}"><span style="width:${l.on ? Math.max(3, l.pct) : 0}%;background:linear-gradient(90deg, ${mix(l.color, 34)}, ${mix(l.color, 14)});box-shadow:inset -1.5px 0 0 ${l.on ? mix(l.color, 70) : 'transparent'}"></span></span>`).join('')}</div>`;
  }
  const isSwitch = o.kind === 'switch' && !o.action;
  const sw = isSwitch ? `<span aria-hidden="true" class="track" style="background:${active ? mix(accent, 30) : 'transparent'};box-shadow:inset 0 0 0 1px ${active ? 'transparent' : 'var(--line2)'}"><span class="knob" style="left:${active ? 15 : 3}px;background:${active ? accent : 'var(--quiet)'}"></span></span>` : '';
  const valColor = o.valColor || (isSwitch ? (active ? accent : 'var(--muted)') : active ? 'var(--text)' : 'var(--quiet)');
  const bg = o.stripBg || (isSwitch && active ? mix(accent, 10) : 'transparent');
  return `<div class="strip" style="box-shadow:inset 0 0 0 1px ${active ? mix(accent, o.edgeMix || 30) : 'var(--line)'};background-color:${bg}">${layer}
<div class="sline">${icon(o.icon, { color: o.iconColor || (active ? accent : 'var(--quiet)'), active, dur: o.dur, transform: o.iconTransform, partOpacity: o.partOpacity })}
<span class="nv"><b title="${esc(o.name)}">${esc(o.name)}</b><span style="color:${valColor}">${esc(o.val)}</span></span><span class="flex1"></span>${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ''}${o.action ? `<span class="actword${o.armed ? ' armed' : ''}" style="--ac:${o.actionColor || accent}">${esc(o.armed || o.action)}</span>` : sw}</div></div>`;
}

function histBlock(ctx, label) {
  const h = history.block(ctx.hass, ctx.card, ctx.st, ctx.H, ctx.accent, ctx.name);
  return h ? (label === false ? h : `${blockLabel(label || 'History')}${h}`) : '';
}

// ------------------------------------------------------------------ light

function lightMore(ctx, target) {
  const st = ctx.st; const a = (st && st.attributes) || {};
  const modes = a.supported_color_modes || [];
  const parts = [];
  const color = modes.some((m) => ['hs', 'rgb', 'rgbw', 'rgbww', 'xy'].includes(m));
  if (color) {
    const hs = a.hs_color || [0, 0];
    parts.push(`${blockLabel('Colour')}<div class="field" data-act="field" data-entity="${esc(target)}" role="slider" aria-label="Colour">${st.state === 'on' && a.color_mode && a.color_mode !== 'color_temp' ? `<i style="left:${(hs[0] / 360 * 100).toFixed(1)}%;top:${(hs[1]).toFixed(1)}%;background:${lightColor(st)}"></i>` : ''}</div>`);
  }
  if (modes.includes('color_temp')) {
    const lo = a.min_color_temp_kelvin || 2200, hi = a.max_color_temp_kelvin || 6500;
    const ws = [['Warm', clamp(2700, lo, hi), '#ffb35c'], ['Soft', clamp(3500, lo, hi), '#ffd9a8'], ['Daylight', clamp(5200, lo, hi), '#dfeaff']];
    parts.push(`${blockLabel('Whites')}<div class="swatches">${ws.map((w) => `<button type="button" class="sw" data-ctl="1" data-act="svc" data-domain="light" data-service="turn_on" data-data="${esc(JSON.stringify({ entity_id: target, color_temp_kelvin: w[1] }))}" aria-label="${w[0]}" title="${w[0]}" style="background:${w[2]}"></button>`).join('')}</div>`);
  }
  return parts.join('');
}

const light = {
  item: STRIP,
  accent: (ctx) => (ctx.st && ctx.st.state === 'on' ? lightAccent(ctx.st) : 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on'; const p = ctx.preview != null ? ctx.preview : pct(st);
    const lit = on || ctx.preview > 0;
    return stripFace({ kind: 'fill', icon: /\b(strip|led)\b/i.test(ctx.name || '') ? 'led' : 'bulb', accent: ctx.accent, active: lit, pct: on || ctx.preview != null ? p : 0, name: ctx.name, val: off(st) ? (st ? 'Unavailable' : 'Missing') : lit ? `${p}% · ${lightTone(st)}` : 'Off', valColor: lit ? 'var(--muted)' : 'var(--quiet)', hint: ctx.hint });
  },
  more: (ctx) => lightMore(ctx, ctx.card.entity) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'light', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (ctx.st && (ctx.st.attributes.supported_color_modes || []).some((m) => m !== 'onoff')
    ? { get: () => pct(ctx.st), call: (v) => (v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: ctx.card.entity } } : { domain: 'light', service: 'turn_on', data: { entity_id: ctx.card.entity, brightness_pct: v } }) } : null),
};

const lightGroup = {
  // A group is a room's worth of lights: twice a strip, and it grows down
  // into its members rather than sideways.
  item: { span: 2, grow: 3, dir: 'down', want: 4, hk: 's' },
  accent: light.accent,
  members: (ctx) => ((ctx.st && ctx.st.attributes.entity_id) || []).filter((e) => domainOf(e) === 'light'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    const lanes = lightGroup.members(ctx).map((m) => { const ms = ctx.hass.states[m]; return { on: (ms && ms.state === 'on') || ctx.preview > 0, pct: ctx.preview != null ? ctx.preview : pct(ms), color: ms && ms.state === 'on' ? lightColor(ms) : ctx.accent }; });
    const lit = lanes.filter((l) => l.on);
    const n = lit.length, total = lanes.length;
    const mixed = n > 1 && lit.some((l) => l.pct !== lit[0].pct);
    const avg = n ? Math.round(lit.reduce((a, l) => a + l.pct, 0) / n) : 0;
    const val = off(st) ? 'Unavailable' : ctx.preview != null ? ctx.preview + '%'
      : n ? `${n === total ? 'All ' + total : n + ' of ' + total} · ${mixed ? 'mixed' : avg + '%'}` : total ? `All ${total} off` : 'Off';
    return stripFace({ kind: 'lanes', lanes, icon: 'group', accent: ctx.accent, active: n > 0, name: ctx.name, val, hint: ctx.hint });
  },
  more: (ctx) => {
    const members = lightGroup.members(ctx);
    const strips = members.map((m) => {
      const ms = ctx.hass.states[m]; const on = ms && ms.state === 'on'; const acc = on ? lightAccent(ms) : 'var(--amber)';
      const pv = ctx.memberPreview && ctx.memberPreview.id === m ? ctx.memberPreview.v : null;
      return `<div class="notecard" data-member="${esc(m)}" style="position:relative;touch-action:pan-y">${stripFace({ kind: 'fill', icon: 'bulb', accent: acc, active: on || pv > 0, pct: pv != null ? pv : on ? pct(ms) : 0, name: shortName(shortName(friendly(ctx.hass, m), ctx.sec.title), ctx.name), val: !ms ? 'Missing' : pv != null ? pv + '%' : on ? pct(ms) + '%' : 'Off' })}</div>`;
    }).join('');
    return `${blockLabel('Each light')}<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px">${strips}</div>${lightMore(ctx, ctx.card.entity)}${histBlock(ctx)}`;
  },
  tap: light.tap,
  slide: (ctx) => ({ get: () => pct(ctx.st), call: (v) => (v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: ctx.card.entity } } : { domain: 'light', service: 'turn_on', data: { entity_id: ctx.card.entity, brightness_pct: v } }) }),
};

// ------------------------------------------------------------- fan, cover

const fan = {
  item: STRIP,
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    // A fan with no speed control is on or off: "High · 100%" on one was a
    // speed it does not have, and sliding it called a service it refuses.
    const speed = fanHasSpeed(st);
    const p = ctx.preview != null ? ctx.preview : (speed ? st.attributes.percentage : on ? 100 : 0);
    // 2.6 s a turn at the bottom to 1.1 s at the top: faster strobed.
    return stripFace({ kind: speed ? 'fill' : 'switch', icon: 'fan', accent: ctx.accent, active: on || ctx.preview > 0, pct: on || ctx.preview != null ? p : 0, dur: (2.6 - (p || 0) / 100 * 1.5).toFixed(2) + 's', name: ctx.name, fillA: mix(ctx.accent, 26), fillB: mix(ctx.accent, 8), val: off(st) ? stateWord(st) : on || ctx.preview > 0 ? (speed && p ? `${fanLevel(p)} · ${p}%` : 'On') : 'Off', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    if (a.direction) parts.push(blockLabel('Direction') + words([svcBtn('Forward', 'fan', 'set_direction', { entity_id: e, direction: 'forward' }, { pressed: a.direction === 'forward' }), svcBtn('Reverse', 'fan', 'set_direction', { entity_id: e, direction: 'reverse' }, { pressed: a.direction === 'reverse' })]));
    if (a.oscillating != null) parts.push(blockLabel('Oscillate') + words([svcBtn('On', 'fan', 'oscillate', { entity_id: e, oscillating: true }, { pressed: !!a.oscillating }), svcBtn('Off', 'fan', 'oscillate', { entity_id: e, oscillating: false }, { pressed: !a.oscillating })]));
    if ((a.preset_modes || []).length) parts.push(blockLabel('Mode') + words(a.preset_modes.map((m) => svcBtn(m, 'fan', 'set_preset_mode', { entity_id: e, preset_mode: m }, { pressed: a.preset_mode === m }))));
    return parts.join('') + histBlock(ctx);
  },
  tap: (ctx) => ({ domain: 'fan', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (fanHasSpeed(ctx.st) ? { get: () => ctx.st.attributes.percentage || 0, call: (v) => ({ domain: 'fan', service: 'set_percentage', data: { entity_id: ctx.card.entity, percentage: v <= 1 ? 0 : v } }) } : null),
};

const isGarage = (st) => st && ['garage', 'gate', 'door'].includes(st.attributes.device_class);
const cover = {
  item: STRIP,
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; const pos = ctx.preview != null ? ctx.preview : (st && st.attributes.current_position != null ? st.attributes.current_position : st && st.state === 'open' ? 100 : 0);
    const open = st && ['open', 'opening'].includes(st.state);
    if (isGarage(st)) {
      // The word says what a tap will do: Open, Close, or Stop while it
      // moves. The old switch could only ever open the door.
      const moving = st && ['opening', 'closing'].includes(st.state);
      const action = off(st) ? '' : moving ? 'Stop' : open ? 'Close' : 'Open';
      return stripFace({ kind: 'switch', icon: 'garage', accent: open ? 'var(--amber)' : 'var(--indigo)', active: open, name: ctx.name, val: stateWord(st), action, armed: ctx.confirm || '', actionColor: open ? 'var(--amber)' : 'var(--indigo)', iconTransform: open ? 'translateY(-4px)' : 'none', hint: ctx.hint });
    }
    return stripFace({ kind: 'slats', icon: 'blinds', accent: ctx.accent, iconColor: 'var(--sky)', edgeMix: 28, fillA: mix(ctx.accent, 20), fillB: mix(ctx.accent, 6), active: pos > 0, pct: pos, iconTransform: `scaleY(${Math.max(0.08, (100 - pos) / 100).toFixed(2)})`, name: ctx.name, val: off(st) ? 'Unavailable' : st.state === 'opening' ? 'Opening' : st.state === 'closing' ? 'Closing' : pos >= 100 ? 'Open' : pos <= 0 ? 'Closed' : pos + '% open', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    parts.push(words([svcBtn('Open', 'cover', 'open_cover', { entity_id: e }), svcBtn('Stop', 'cover', 'stop_cover', { entity_id: e }), svcBtn('Close', 'cover', 'close_cover', { entity_id: e })]));
    if (a.current_tilt_position != null) parts.push(`${blockLabel('Tilt')}<input type="range" class="mrange" min="0" max="100" value="${a.current_tilt_position}" data-act="range" data-domain="cover" data-service="set_cover_tilt_position" data-key="tilt_position" data-entity="${esc(e)}" aria-label="Tilt">`);
    return parts.join('') + histBlock(ctx);
  },
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
const SWITCH_COLOR = { switch: 'var(--amber)', input_boolean: 'var(--sand)', siren: 'var(--rose)', automation: 'var(--violet)' };
const GARDEN = /irrigat|sprinkler|lawn|garden|drip|zone/i;
const sw = {
  item: { ...STRIP, want: 2 },
  accent: (ctx) => (GARDEN.test(ctx.card.entity + ' ' + (ctx.name || '')) ? 'var(--lime)' : SWITCH_COLOR[domainOf(ctx.card.entity)] || 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    return stripFace({ kind: 'switch', icon: /fan/i.test(ctx.name || '') ? 'fan' : 'power', dur: '1.6s', accent: ctx.accent, active: on, name: ctx.name, val: off(st) ? stateWord(st) : on ? 'On' : 'Off', hint: ctx.hint });
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
    const action = off(st) ? '' : unlocked ? 'Lock' : 'Unlock';
    return stripFace({ kind: 'switch', icon: 'lock', accent: ctx.accent, active: unlocked || (st && st.state === 'locked'), name: ctx.name, val: stateWord(st), action, armed: ctx.confirm || '', actionColor: ctx.night && unlocked ? 'var(--rose)' : ctx.accent, iconTransform: unlocked ? 'translateY(-3px)' : 'none', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const bat = a.battery_level != null ? `<p class="sm">Battery ${esc(a.battery_level)}%</p>` : '';
    return bat + histBlock(ctx);
  },
  // Unlocking from a dashboard is the one tap that needs a second tap.
  tap: (ctx) => (ctx.st && ctx.st.state === 'locked'
    ? { domain: 'lock', service: 'unlock', data: { entity_id: ctx.card.entity }, confirm: 'Unlock?' }
    : { domain: 'lock', service: 'lock', data: { entity_id: ctx.card.entity }, confirm: 'Lock?' }),
};

const button = {
  item: { ...STRIP, want: 2 },
  accent: () => 'var(--violet)',
  face: (ctx) => {
    const st = ctx.st; const script = domainOf(ctx.card.entity) === 'script';
    const last = st && (script ? st.attributes.last_triggered : st.state);
    const w = whenWord(last);
    const val = off(st) ? stateWord(st) : script && st.state === 'on' ? 'Running' : w ? (script ? 'Ran ' : 'Pressed ') + w : script ? 'Tap to run' : 'Tap to press';
    return stripFace({ kind: 'none', icon: 'play', accent: ctx.accent, active: st && st.state === 'on', name: ctx.name, val, hint: ctx.hint });
  },
  more: (ctx) => histBlock(ctx),
  tap: (ctx) => {
    const d = domainOf(ctx.card.entity);
    return { domain: d === 'script' ? 'script' : d, service: d === 'script' ? 'turn_on' : 'press', data: { entity_id: ctx.card.entity } };
  },
};

const vacuum = {
  item: STRIP,
  accent: () => 'var(--sand)',
  face: (ctx) => {
    const st = ctx.st; const run = st && ['cleaning', 'returning'].includes(st.state);
    const bat = st && st.attributes.battery_level != null ? ` · ${st.attributes.battery_level}%` : '';
    return stripFace({ kind: 'switch', icon: 'vacuum', accent: ctx.accent, active: run, name: ctx.name, val: off(st) ? stateWord(st) : stateWord(st) + bat, hint: ctx.hint });
  },
  more: (ctx) => words([svcBtn('Start', 'vacuum', 'start', { entity_id: ctx.card.entity }), svcBtn('Pause', 'vacuum', 'pause', { entity_id: ctx.card.entity }), svcBtn('Go home', 'vacuum', 'return_to_base', { entity_id: ctx.card.entity })]) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'vacuum', service: ctx.st && ctx.st.state === 'cleaning' ? 'return_to_base' : 'start', data: { entity_id: ctx.card.entity } }),
};

// ----------------------------------------------------------------- climate

const MODE = { heat: ['Heating', 'var(--peach)'], cool: ['Cooling', 'var(--sky)'], heat_cool: ['Auto', 'var(--teal)'], auto: ['Auto', 'var(--teal)'], dry: ['Drying', 'var(--sky)'], fan_only: ['Fan', 'var(--sky)'], off: ['Off', 'var(--quiet)'] };
const ACTION = { heating: 'Heating', cooling: 'Cooling', drying: 'Drying', fan: 'Fan', idle: 'Holding', off: 'Off' };
const climate = {
  item: { span: 2, grow: 3, dir: 'side', want: 4, hk: 't' },
  accent: (ctx) => (MODE[ctx.st && ctx.st.state] || MODE.off)[1],
  face: (ctx) => {
    const st = ctx.st; if (!st) return `<div class="box"><b>${esc(ctx.name)}</b><span class="sm">Missing</span></div>`;
    const a = st.attributes; const unit = ctx.hass.config.unit_system.temperature || '°';
    const cur = a.current_temperature; const tgt = a.temperature != null ? a.temperature : a.target_temp_low;
    const lo = a.min_temp != null ? a.min_temp : 7, hi = a.max_temp != null ? a.max_temp : 35;
    const P = (v) => clamp(((v - lo) / (hi - lo || 1)) * 100, 0, 100);
    const action = a.hvac_action ? ACTION[a.hvac_action] || a.hvac_action : (MODE[st.state] || MODE.off)[0];
    const band = tgt != null && cur != null ? [Math.min(P(cur), P(tgt)), Math.max(P(cur), P(tgt))] : null;
    const acting = ['heating', 'cooling'].includes(a.hvac_action);
    return `<div class="box" style="box-shadow:inset 0 0 0 1px ${acting ? mix(ctx.accent, 30) : 'var(--line)'}">
<div class="rowb"><b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${ctx.accent}">${esc(action)}</span></div>
<div class="row"><span class="big">${cur != null ? esc(Number(cur).toFixed(1)) + '°' : '—'}</span><span class="flex1"></span>
${tgt != null ? `<div data-ctl="1" class="row" style="gap:4px"><button type="button" class="sq" data-act="tgt" data-v="-1" aria-label="Lower ${esc(ctx.name)} target"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"></path></svg></button><span style="min-width:54px;text-align:center;display:flex;flex-direction:column;line-height:1.1"><span style="font-size:20px;font-weight:600;font-variant-numeric:tabular-nums">${esc(tgt)}°</span><span class="small">target</span></span><button type="button" class="sq" data-act="tgt" data-v="1" aria-label="Raise ${esc(ctx.name)} target"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg></button></div>` : ''}</div>
<div aria-hidden="true" class="ruler"><div style="left:0;right:0;top:7px;height:2px;border-radius:1px;background:var(--line)"></div>${band ? `<div style="top:6px;height:4px;border-radius:2px;left:${band[0]}%;width:${band[1] - band[0]}%;background:${st.state === 'off' ? 'transparent' : mix(ctx.accent, 45)}"></div>` : ''}${cur != null ? `<div style="top:1px;width:2px;height:14px;border-radius:1px;left:${P(cur)}%;background:var(--text)"></div>` : ''}${tgt != null ? `<div style="top:2px;width:8px;height:12px;margin-left:-4px;border-radius:3px;left:${P(tgt)}%;background:${ctx.accent};transition:left .6s cubic-bezier(.25,1,.3,1)"></div>` : ''}</div>
<div class="row small" style="justify-content:space-between"><span>${lo}${esc(unit)}</span><span>${a.current_humidity != null ? esc(a.current_humidity) + '% humidity' : ''}</span><span>${hi}${esc(unit)}</span></div></div>`;
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    if ((a.hvac_modes || []).length) parts.push(blockLabel('Mode') + words(a.hvac_modes.map((m) => svcBtn((MODE[m] || [m])[0], 'climate', 'set_hvac_mode', { entity_id: e, hvac_mode: m }, { pressed: ctx.st.state === m }))));
    if ((a.fan_modes || []).length) parts.push(blockLabel('Fan') + words(a.fan_modes.map((m) => svcBtn(m, 'climate', 'set_fan_mode', { entity_id: e, fan_mode: m }, { pressed: a.fan_mode === m }))));
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

function sparkline(hass, eid, color) {
  const now = Date.now();
  const rows = history.stats(hass, eid, now - 86400000, now, 'hour');
  if (!rows || rows.error || rows.length < 2) return '<div style="height:22px"></div>';
  const vals = rows.map((r) => r.mean).filter((v) => v != null && isFinite(v));
  if (vals.length < 2) return '<div style="height:22px"></div>';
  let lo = Math.min(...vals), hi = Math.max(...vals); const m = (hi - lo) * 0.18 || 1; lo -= m; hi += m;
  const d = vals.map((v, i) => (i ? 'L' : 'M') + (i / (vals.length - 1) * 200).toFixed(1) + ' ' + (22 - (v - lo) / (hi - lo) * 22).toFixed(1)).join('');
  return `<svg viewBox="0 0 200 22" preserveAspectRatio="none" style="width:100%;height:22px;display:block"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"></path></svg>`;
}

const sensor = {
  item: { span: 1, grow: 2, dir: 'down', want: 3, hk: 'r' },
  accent: (ctx) => {
    const st = ctx.st; const dc = st && st.attributes.device_class;
    if (dc === 'temperature') return warmth(parseFloat(st.state), st.attributes.unit_of_measurement);
    if (dc === 'humidity') return 'var(--sky)';
    if (dc === 'power' || dc === 'energy') return 'var(--amber)';
    return 'var(--teal)';
  },
  face: (ctx) => {
    const st = ctx.st; const unit = (st && st.attributes.unit_of_measurement) || '';
    const dc = st && st.attributes.device_class;
    const val = !st ? 'Missing' : UNAVAILABLE.includes(st.state) ? '—' : isNaN(parseFloat(st.state)) ? st.state : fmt(st.state, '');
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon(dc === 'humidity' ? 'humid' : dc === 'temperature' ? 'thermo' : dc === 'power' || dc === 'energy' ? 'bolt' : 'dot', { color: ctx.accent, size: 16 })}<b style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div><div class="rowb"><span class="mid">${esc(val)}</span><span class="sm">${esc(isNaN(parseFloat(st && st.state)) ? '' : unit)}</span></div>${st ? sparkline(ctx.hass, ctx.card.entity, ctx.accent) : ''}</div>`;
  },
  more: (ctx) => histBlock(ctx),
  tap: () => null,
};

const readings = {
  item: { span: 3, grow: 4, dir: 'down', want: 4, full: true },
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const first = ctx.hass.states[(ctx.card.entities || [])[0]];
    const unit = first && first.attributes.unit_of_measurement;
    const dc = first && first.attributes.device_class;
    const color = dc === 'humidity' ? (v) => (v < 35 ? 'var(--amber)' : v <= 55 ? 'var(--teal)' : v <= 60 ? 'var(--sky)' : 'var(--indigo)') : (v) => warmth(v, unit);
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
    const now = Date.now(); const d0 = new Date(); d0.setHours(0, 0, 0, 0);
    const week = st ? history.stats(ctx.hass, ctx.card.entity, d0.getTime() - 6 * 86400000, now, 'day') : null;
    const ok = week && !week.error && week.length;
    // Until today has a statistics row, the last row is YESTERDAY's total,
    // and calling it today's was a day off.
    const lastRow = ok ? week[week.length - 1] : null;
    const today = lastRow && lastRow.t >= d0.getTime() ? lastRow.change : ok ? 0 : null;
    const vals = ok ? week.map((w) => w.change || 0) : [];
    const hi = Math.max(1e-6, ...vals);
    const bars = ok ? `<div class="cols" style="height:40px;gap:4px">${week.map((w, i) => `<span class="colbar" title="${esc(new Date(w.t).toLocaleDateString([], { weekday: 'short' }) + ' · ' + fmt(vals[i], unit))}" style="flex:1;height:${Math.max(2, vals[i] / hi * 38)}px;background:${mix(ctx.accent, i === vals.length - 1 ? 85 : 45)}"></span>`).join('')}</div>` : '';
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon(/water/.test((st && st.attributes.device_class) || '') ? 'water' : 'bolt', { color: ctx.accent, size: 16 })}<b style="font-size:13px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div><div class="rowb"><span class="mid">${today != null ? esc(fmt(today, '')) : '—'}</span><span class="sm">${esc(unit)} today</span></div>${bars}</div>`;
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
    const title = a.media_title || (st && !off(st) ? (st.state === 'off' ? 'Off' : st.state[0].toUpperCase() + st.state.slice(1)) : 'Unavailable');
    const sub = [a.media_artist, a.app_name || a.source].filter(Boolean).join(' · ');
    let prog = '';
    if (a.media_duration && a.media_position != null) {
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
    const src = a.access_token ? `/api/camera_proxy/${encodeURIComponent(ctx.card.entity)}?token=${encodeURIComponent(a.access_token)}&t=${bucket}` : '';
    const sub = !st ? 'Missing' : UNAVAILABLE.includes(st.state) ? 'Unavailable' : CAM_STATE[st.state] || st.state[0].toUpperCase() + st.state.slice(1);
    const live = st && !UNAVAILABLE.includes(st.state);
    // A closed tile is a snapshot every 10 s, so it says Still; an opened
    // one streams, and only then says Live.
    const stream = ctx.open && a.access_token ? `/api/camera_proxy_stream/${encodeURIComponent(ctx.card.entity)}?token=${encodeURIComponent(a.access_token)}` : '';
    const pic = stream || src;
    return `<div class="camtile" style="box-shadow:inset 0 0 0 1px ${st && st.state === 'recording' ? mix(ctx.accent, 30) : 'var(--line)'}"><div class="camhead"><b title="${esc(ctx.name)}">${esc(ctx.name)}</b><span class="flex1"></span><span class="small">${esc(sub)}</span></div><div class="campic">${pic ? `<img class="cam" src="${esc(pic)}" alt="${esc(ctx.name)}" loading="lazy" onerror="this.style.visibility='hidden'">` : ''}${live ? `<span class="live"><i${stream ? '' : ' class="still"'}></i>${stream ? 'LIVE' : 'Still'}</span>` : ''}${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div></div>`;
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
const isActivity = (st) => !!(st && ACTIVITY.includes(st.attributes.device_class));
export const listWord = (st) => {
  if (!st) return ['Missing', false];
  if (UNAVAILABLE.includes(st.state)) return ['Unavailable', false];
  const w = WORDS[st.attributes.device_class] || ['On', 'Off'];
  const on = st.state === 'on';
  return [on ? w[0] : w[1], on];
};
const list = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: (ctx) => {
    const sts = (ctx.card.entities || []).map((e) => ctx.hass.states[e]);
    if (sts.some((st) => listWord(st)[1] && !isActivity(st))) return 'var(--rose)';
    if (sts.some((st) => listWord(st)[1])) return 'var(--amber)';
    return 'var(--indigo)';
  },
  face: (ctx) => {
    const rows = (ctx.card.entities || []).map((e) => { const st = ctx.hass.states[e]; const [w, on] = listWord(st); return { e, w, on, act: isActivity(st), name: shortName(friendly(ctx.hass, e), ctx.sec.title), st }; });
    rows.sort((a, b) => (b.on - a.on) || (a.act - b.act));
    const openRows = rows.filter((r) => r.on);
    const attention = openRows.filter((r) => !r.act);
    const tone = attention.length ? 'var(--rose)' : openRows.length ? 'var(--amber)' : 'var(--quiet)';
    // "All closed" in the kind's own word when every row is one kind.
    const kinds = new Set(rows.map((r) => (r.st && r.st.attributes.device_class) || ''));
    const summary = openRows.length
      ? `${openRows.length === 1 ? openRows[0].name : openRows.length + ' of ' + rows.length} ${openRows.length === 1 ? openRows[0].w.toLowerCase() : attention.length ? 'need you' : 'active'}`
      : kinds.size === 1 && rows[0] ? `All ${listWord({ ...rows[0].st, state: 'off' })[0].toLowerCase()}` : 'All quiet';
    const shown = ctx.open ? rows : rows.slice(0, 6);
    return `<div class="box" style="box-shadow:inset 0 0 0 1px ${attention.length ? mix('var(--rose)', 35) : 'var(--line)'};padding:12px 12px 8px 16px"><div class="rowb">${ctx.card.name ? `<b style="font-size:14px">${esc(ctx.name)}</b>` : ''}<span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${tone}">${esc(summary)}</span></div>
${shown.map((r) => `<button type="button" class="lrow" data-ctl="1" data-act="member" data-v="${esc(r.e)}" data-member="${esc(r.e)}" aria-pressed="${ctx.member === r.e}" style="padding:7px 4px;min-height:44px"><span class="lx"><span>${esc(r.name)}</span></span><span style="font-size:13px;font-weight:600;color:${r.on ? (r.act ? 'var(--amber)' : 'var(--rose)') : 'var(--quiet)'}">${esc(r.w)}</span><span class="small">${r.st ? esc(since(r.st.last_changed).replace('since ', '')) : ''}</span></button>`).join('')}${rows.length > shown.length ? `<span class="small" style="padding:4px">+${rows.length - shown.length} more · hold to see them</span>` : ''}</div>`;
  },
  more: (ctx) => {
    if (!ctx.member) return '<p class="sm">Tap a row for its history.</p>';
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
    const av = a.entity_picture ? `<img class="avatar" src="${esc(a.entity_picture)}" alt="">` : `<span class="avatar" style="background:${mix(ctx.accent, 25)};color:${ctx.accent}">${esc((ctx.name || '?')[0])}</span>`;
    return `<div class="strip" style="box-shadow:inset 0 0 0 1px ${home ? mix(ctx.accent, 30) : 'var(--line)'};background:${home ? mix(ctx.accent, 8) : 'transparent'}"><div class="sline">${av}<span class="nv"><b>${esc(ctx.name)}</b><span style="color:${ctx.accent}">${esc(where)} ${st ? '· ' + esc(since(st.last_changed).replace('since ', '')) : ''}</span></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div></div>`;
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
const weather = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: () => 'var(--amber)',
  face: (ctx) => {
    const st = ctx.st; if (!st) return `<div class="box"><b>${esc(ctx.name)}</b><span class="sm">Missing</span></div>`;
    const a = st.attributes; const unit = a.temperature_unit || '°';
    const days = forecast(ctx.hass, ctx.card.entity, 'daily') || [];
    const sunny = ['sunny', 'clear-night', 'partlycloudy'].includes(st.state);
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon(sunny ? 'sun' : 'cloud', { color: ctx.accent, active: true, size: 22, dur: '26s' })}<span class="big">${a.temperature != null ? esc(Math.round(a.temperature)) + '°' : '—'}</span><span class="nv" style="margin-left:6px"><b>${esc(WEATHER[st.state] || st.state)}</b><span class="small">${a.humidity != null ? esc(a.humidity) + '% humidity' : ''}${a.wind_speed != null ? ' · wind ' + esc(Math.round(a.wind_speed)) + ' ' + esc(a.wind_speed_unit || '') : ''}</span></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div>
${days.length ? `<div class="row" style="justify-content:space-between;margin-top:8px">${days.slice(0, 5).map((d) => `<span style="display:flex;flex-direction:column;align-items:center;gap:2px;font-size:12px"><span class="small">${esc(new Date(d.datetime).toLocaleDateString([], { weekday: 'short' }))}</span><b>${esc(Math.round(d.temperature))}°</b><span class="small">${d.templow != null ? esc(Math.round(d.templow)) + '°' : ''}</span></span>`).join('')}</div>` : ''}<span class="sr">${esc(unit)}</span></div>`;
  },
  more: (ctx) => {
    const hours = forecast(ctx.hass, ctx.card.entity, 'hourly') || [];
    if (!hours.length) return '<p class="sm">No hourly forecast from this weather service.</p>';
    const pts = hours.slice(0, 24).map((h) => [Date.parse(h.datetime), h.temperature]);
    return blockLabel('Next 24 hours') + history.lineChart([{ id: 'f', name: 'Temperature', color: 'var(--amber)', pts }], pts[0][0], pts[pts.length - 1][0], { unit: '°' }) +
      `<p class="sm">${hours.slice(0, 24).filter((h) => (h.precipitation_probability || 0) >= 40).length ? 'Rain likely at ' + esc(clock(hours.find((h) => (h.precipitation_probability || 0) >= 40).datetime)) : 'No rain in the next day.'}</p>`;
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
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon('shield', { color: ctx.accent, size: 18 })}<b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${ctx.accent}">${esc(ctx.confirm || stateWord(st))}</span></div>
${a.code_format ? '<p class="small">Needs a code — hold to enter it.</p>' : words(alarmModes(st).map((m) => svcBtn(m[1], 'alarm_control_panel', m[2], { entity_id: ctx.card.entity }, { pressed: st && st.state === m[0], confirm: m[0] === 'disarmed' ? 'Tap again to disarm' : '' })))}</div>`;
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const code = a.code_format ? `${blockLabel('Code')}<input class="fld" type="password" inputmode="numeric" data-alarm-code="1" autocomplete="off" aria-label="Alarm code">${words(alarmModes(ctx.st).map((m) => `<button type="button" class="wd" data-ctl="1" data-act="alarm" data-service="${m[2]}">${m[1]}</button>`))}` : '';
    return code + histBlock(ctx);
  },
  tap: () => null,
};

// ------------------------------------------------------- scenes, the rest

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
    return `<div class="scenes">${ids.map((e) => `<button type="button" class="wd" data-ctl="1" data-act="scene" data-v="${esc(e)}" aria-pressed="${cur === e}">${esc(shortName(friendly(ctx.hass, e), ctx.sec.title))}</button>`).join('')}</div>`;
  },
  more: () => '',
  tap: () => null,
  noOpen: true,
};

const entity = {
  item: { ...STRIP, dir: 'down', want: 2 },
  accent: () => 'var(--teal)',
  face: (ctx) => {
    const st = ctx.st; const unit = (st && st.attributes.unit_of_measurement) || '';
    return stripFace({ kind: 'none', icon: 'dot', accent: ctx.accent, active: st && st.state === 'on', name: ctx.name, val: !st ? 'Missing' : isNaN(parseFloat(st.state)) ? st.state : fmt(st.state, unit), valColor: 'var(--muted)', hint: ctx.hint });
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

export const TYPES = { light, light_group: lightGroup, fan, cover, lock, switch: sw, button, vacuum, climate, sensor, readings, meter, media, camera, list, person, weather, alarm, scenes, entity, note, lovelace };

// A card whose entity is unavailable or missing opens in place with its
// history rather than calling a service that will refuse.
Object.values(TYPES).forEach((T) => {
  const tap = T.tap; const slide = T.slide;
  if (tap) T.tap = (ctx) => (ctx.card && ctx.card.entity && off(ctx.st) ? null : tap(ctx));
  if (slide) T.slide = (ctx) => (ctx.card && ctx.card.entity && off(ctx.st) ? null : slide(ctx));
});

// A tile's role for a screen reader: a slider when it has a level, a switch
// when a tap toggles it, a button that opens otherwise.
export function tileAria(T, ctx, name) {
  const slide = T.slide ? T.slide(ctx) : null;
  const tap = T.tap ? T.tap(ctx) : null;
  const word = ctx.st ? stateWord(ctx.st) : '';
  if (slide) { const v = slide.get(); return { role: 'slider', label: name, value: `${v}%`, now: v }; }
  if (tap && !tap.confirm) return { role: 'switch', label: name, checked: !!(ctx.st && ['on', 'open', 'unlocked', 'playing'].includes(ctx.st.state)), value: word };
  return { role: 'button', label: `${name}${word ? ', ' + word : ''}`, expanded: !!ctx.open };
}

export function typeOf(card) {
  return TYPES[card.type] || TYPES.entity;
}

export const isFull = (card) => !!typeOf(card).item.full;
