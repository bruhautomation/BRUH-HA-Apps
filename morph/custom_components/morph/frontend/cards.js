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

import { esc, mix, clamp, lightColor, fmt, since, clock, icon, friendly, shortName, UNAVAILABLE, domainOf } from './util.js';
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

export function stripFace(o) {
  const active = !!o.active;
  const accent = o.accent;
  const fillW = clamp(o.pct == null ? 0 : o.pct, 0, 100);
  let layer = '';
  if (o.kind === 'fill' && fillW > 0) {
    layer = `<div aria-hidden="true" class="fill" style="width:${fillW}%;background:linear-gradient(90deg, ${mix(accent, 26)}, ${mix(accent, 52)})"></div><div aria-hidden="true" class="thumb" style="left:${fillW}%"></div>`;
  } else if (o.kind === 'slats') {
    layer = `<div aria-hidden="true" class="slats" style="width:${100 - fillW}%"></div>${fillW > 0 ? `<div aria-hidden="true" class="fill" style="width:${fillW}%;background:linear-gradient(90deg, ${mix(accent, 14)}, ${mix(accent, 30)})"></div>` : ''}`;
  } else if (o.kind === 'lanes') {
    layer = `<div aria-hidden="true" class="lanes">${(o.lanes || []).map((l) => `<span class="lane" style="background:${l.on ? mix(l.color, 8) : 'transparent'}"><span style="width:${l.on ? l.pct : 0}%;background:linear-gradient(90deg, ${mix(l.color, 22)}, ${mix(l.color, 50)});box-shadow:inset -1.5px 0 0 ${l.on ? mix(l.color, 80) : 'transparent'}"></span></span>`).join('')}</div>`;
  }
  const sw = o.kind === 'switch' ? `<span aria-hidden="true" class="track" style="background:${active ? mix(accent, 30) : 'transparent'};box-shadow:inset 0 0 0 1px ${active ? 'transparent' : 'var(--line2)'}"><span class="knob" style="left:${active ? 15 : 3}px;background:${active ? accent : 'var(--quiet)'}"></span></span>` : '';
  return `<div class="strip" style="box-shadow:inset 0 0 0 1px ${active ? mix(accent, 32) : 'var(--line)'};background-color:${active ? mix(accent, 9) : 'transparent'}">${layer}
<div class="sline">${icon(o.icon, { color: active ? accent : 'var(--quiet)', active, dur: o.dur, transform: o.iconTransform, partOpacity: o.partOpacity })}
<span class="nv"><b>${esc(o.name)}</b><span style="color:${o.valColor || (active ? accent : 'var(--muted)')}">${esc(o.val)}</span></span><span class="flex1"></span>${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ''}${sw}</div></div>`;
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
  accent: (ctx) => (ctx.st && ctx.st.state === 'on' ? lightColor(ctx.st) : 'var(--amber)'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on'; const p = ctx.preview != null ? ctx.preview : pct(st);
    return stripFace({ kind: 'fill', icon: 'bulb', accent: ctx.accent, active: on || ctx.preview > 0, pct: on || ctx.preview != null ? p : 0, name: ctx.name, val: off(st) ? (st ? 'Unavailable' : 'Missing') : on || ctx.preview > 0 ? p + '%' : 'Off', hint: ctx.hint });
  },
  more: (ctx) => lightMore(ctx, ctx.card.entity) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'light', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (ctx.st && (ctx.st.attributes.supported_color_modes || []).some((m) => m !== 'onoff')
    ? { get: () => pct(ctx.st), call: (v) => (v <= 1 ? { domain: 'light', service: 'turn_off', data: { entity_id: ctx.card.entity } } : { domain: 'light', service: 'turn_on', data: { entity_id: ctx.card.entity, brightness_pct: v } }) } : null),
};

const lightGroup = {
  item: STRIP,
  accent: light.accent,
  members: (ctx) => ((ctx.st && ctx.st.attributes.entity_id) || []).filter((e) => domainOf(e) === 'light'),
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    const lanes = lightGroup.members(ctx).map((m) => { const ms = ctx.hass.states[m]; return { on: (ms && ms.state === 'on') || ctx.preview > 0, pct: ctx.preview != null ? ctx.preview : pct(ms), color: ms && ms.state === 'on' ? lightColor(ms) : ctx.accent }; });
    const n = lanes.filter((l) => l.on).length;
    return stripFace({ kind: 'lanes', lanes, icon: 'group', accent: ctx.accent, active: on, name: ctx.name, val: off(st) ? 'Unavailable' : on ? (ctx.preview != null ? ctx.preview + '%' : `${n} of ${lanes.length} on · ${pct(st)}%`) : 'Off', hint: ctx.hint });
  },
  more: (ctx) => {
    const members = lightGroup.members(ctx);
    const strips = members.map((m) => {
      const ms = ctx.hass.states[m]; const on = ms && ms.state === 'on'; const acc = on ? lightColor(ms) : 'var(--amber)';
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
  accent: () => 'var(--teal)',
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on'; const p = ctx.preview != null ? ctx.preview : (st && st.attributes.percentage != null ? st.attributes.percentage : on ? 100 : 0);
    return stripFace({ kind: 'fill', icon: 'fan', accent: ctx.accent, active: on || ctx.preview > 0, pct: on || ctx.preview != null ? p : 0, dur: (2.4 - (p || 0) / 50).toFixed(2) + 's', name: ctx.name, val: off(st) ? 'Unavailable' : on ? (p ? p + '%' : 'On') : 'Off', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    if (a.direction) parts.push(blockLabel('Direction') + words([svcBtn('Forward', 'fan', 'set_direction', { entity_id: e, direction: 'forward' }, { pressed: a.direction === 'forward' }), svcBtn('Reverse', 'fan', 'set_direction', { entity_id: e, direction: 'reverse' }, { pressed: a.direction === 'reverse' })]));
    if (a.oscillating != null) parts.push(blockLabel('Oscillate') + words([svcBtn('On', 'fan', 'oscillate', { entity_id: e, oscillating: true }, { pressed: !!a.oscillating }), svcBtn('Off', 'fan', 'oscillate', { entity_id: e, oscillating: false }, { pressed: !a.oscillating })]));
    if ((a.preset_modes || []).length) parts.push(blockLabel('Mode') + words(a.preset_modes.map((m) => svcBtn(m, 'fan', 'set_preset_mode', { entity_id: e, preset_mode: m }, { pressed: a.preset_mode === m }))));
    return parts.join('') + histBlock(ctx);
  },
  tap: (ctx) => ({ domain: 'fan', service: 'toggle', data: { entity_id: ctx.card.entity } }),
  slide: (ctx) => (ctx.st && ctx.st.attributes.percentage != null ? { get: () => ctx.st.attributes.percentage || 0, call: (v) => ({ domain: 'fan', service: 'set_percentage', data: { entity_id: ctx.card.entity, percentage: v <= 1 ? 0 : v } }) } : null),
};

const isGarage = (st) => st && ['garage', 'gate', 'door'].includes(st.attributes.device_class);
const cover = {
  item: STRIP,
  accent: () => 'var(--sky)',
  face: (ctx) => {
    const st = ctx.st; const pos = ctx.preview != null ? ctx.preview : (st && st.attributes.current_position != null ? st.attributes.current_position : st && st.state === 'open' ? 100 : 0);
    const open = st && ['open', 'opening'].includes(st.state);
    if (isGarage(st)) {
      return stripFace({ kind: 'switch', icon: 'garage', accent: open ? 'var(--rose)' : 'var(--teal)', active: open, name: ctx.name, val: off(st) ? 'Unavailable' : ctx.confirm || (st.state[0].toUpperCase() + st.state.slice(1)), iconTransform: open ? 'translateY(-4px)' : 'none', hint: ctx.hint });
    }
    return stripFace({ kind: 'slats', icon: 'blinds', accent: ctx.accent, active: pos > 0, pct: pos, iconTransform: `scaleY(${(0.35 + 0.65 * (1 - pos / 100)).toFixed(2)})`, name: ctx.name, val: off(st) ? 'Unavailable' : st.state === 'opening' ? 'Opening' : st.state === 'closing' ? 'Closing' : pos >= 100 ? 'Open' : pos <= 0 ? 'Closed' : pos + '% open', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {}; const e = ctx.card.entity; const parts = [];
    parts.push(words([svcBtn('Open', 'cover', 'open_cover', { entity_id: e }), svcBtn('Stop', 'cover', 'stop_cover', { entity_id: e }), svcBtn('Close', 'cover', 'close_cover', { entity_id: e })]));
    if (a.current_tilt_position != null) parts.push(`${blockLabel('Tilt')}<input type="range" class="mrange" min="0" max="100" value="${a.current_tilt_position}" data-act="range" data-domain="cover" data-service="set_cover_tilt_position" data-key="tilt_position" data-entity="${esc(e)}" aria-label="Tilt">`);
    return parts.join('') + histBlock(ctx);
  },
  tap: (ctx) => {
    const st = ctx.st; const open = st && ['open', 'opening'].includes(st.state);
    if (isGarage(st) && !open) return { domain: 'cover', service: 'open_cover', data: { entity_id: ctx.card.entity }, confirm: 'Tap again to open' };
    return { domain: 'cover', service: 'toggle', data: { entity_id: ctx.card.entity } };
  },
  slide: (ctx) => (ctx.st && ctx.st.attributes.current_position != null && !isGarage(ctx.st) ? { get: () => ctx.st.attributes.current_position, call: (v) => ({ domain: 'cover', service: 'set_cover_position', data: { entity_id: ctx.card.entity, position: v <= 1 ? 0 : v } }) } : null),
};

// ---------------------------------------------------------- switches, locks

const SWITCH_COLOR = { switch: 'var(--lime)', input_boolean: 'var(--lime)', siren: 'var(--rose)', automation: 'var(--violet)' };
const sw = {
  item: { ...STRIP, want: 2 },
  accent: (ctx) => SWITCH_COLOR[domainOf(ctx.card.entity)] || 'var(--lime)',
  face: (ctx) => {
    const st = ctx.st; const on = st && st.state === 'on';
    return stripFace({ kind: 'switch', icon: 'power', accent: ctx.accent, active: on, name: ctx.name, val: off(st) ? (st ? 'Unavailable' : 'Missing') : on ? 'On' : 'Off', hint: ctx.hint });
  },
  more: (ctx) => histBlock(ctx),
  tap: (ctx) => ({ domain: 'homeassistant', service: 'toggle', data: { entity_id: ctx.card.entity } }),
};

const lock = {
  item: { ...STRIP, want: 2 },
  accent: (ctx) => (ctx.st && ctx.st.state === 'unlocked' ? 'var(--rose)' : 'var(--teal)'),
  face: (ctx) => {
    const st = ctx.st; const unlocked = st && ['unlocked', 'open', 'opening', 'unlocking'].includes(st.state);
    return stripFace({ kind: 'switch', icon: 'lock', accent: ctx.accent, active: unlocked || (st && st.state === 'locked'), name: ctx.name, val: off(st) ? 'Unavailable' : ctx.confirm || st.state[0].toUpperCase() + st.state.slice(1), iconTransform: unlocked ? 'translateY(-3px)' : 'none', hint: ctx.hint });
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const bat = a.battery_level != null ? `<p class="sm">Battery ${esc(a.battery_level)}%</p>` : '';
    return bat + histBlock(ctx);
  },
  // Unlocking from a dashboard is the one tap that needs a second tap.
  tap: (ctx) => (ctx.st && ctx.st.state === 'locked'
    ? { domain: 'lock', service: 'unlock', data: { entity_id: ctx.card.entity }, confirm: 'Tap again to unlock' }
    : { domain: 'lock', service: 'lock', data: { entity_id: ctx.card.entity } }),
};

const button = {
  item: { ...STRIP, want: 2 },
  accent: () => 'var(--violet)',
  face: (ctx) => stripFace({ kind: 'none', icon: 'play', accent: ctx.accent, active: ctx.st && ctx.st.state === 'on', name: ctx.name, val: ctx.st && domainOf(ctx.card.entity) === 'script' && ctx.st.state === 'on' ? 'Running' : 'Tap to run', hint: ctx.hint }),
  more: (ctx) => histBlock(ctx),
  tap: (ctx) => {
    const d = domainOf(ctx.card.entity);
    return { domain: d === 'script' ? 'script' : d, service: d === 'script' ? 'turn_on' : 'press', data: { entity_id: ctx.card.entity } };
  },
};

const vacuum = {
  item: STRIP,
  accent: () => 'var(--lime)',
  face: (ctx) => {
    const st = ctx.st; const run = st && ['cleaning', 'returning'].includes(st.state);
    const bat = st && st.attributes.battery_level != null ? ` · ${st.attributes.battery_level}%` : '';
    return stripFace({ kind: 'switch', icon: 'vacuum', accent: ctx.accent, active: run, name: ctx.name, val: off(st) ? 'Unavailable' : st.state[0].toUpperCase() + st.state.slice(1) + bat, hint: ctx.hint });
  },
  more: (ctx) => words([svcBtn('Start', 'vacuum', 'start', { entity_id: ctx.card.entity }), svcBtn('Pause', 'vacuum', 'pause', { entity_id: ctx.card.entity }), svcBtn('Go home', 'vacuum', 'return_to_base', { entity_id: ctx.card.entity })]) + histBlock(ctx),
  tap: (ctx) => ({ domain: 'vacuum', service: ctx.st && ctx.st.state === 'cleaning' ? 'return_to_base' : 'start', data: { entity_id: ctx.card.entity } }),
};

// ----------------------------------------------------------------- climate

const MODE = { heat: ['Heating', 'var(--rose)'], cool: ['Cooling', 'var(--teal)'], heat_cool: ['Auto', 'var(--lime)'], auto: ['Auto', 'var(--lime)'], dry: ['Drying', 'var(--sky)'], fan_only: ['Fan', 'var(--sky)'], off: ['Off', 'var(--quiet)'] };
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
  return c < 16 ? 'var(--sky)' : c < 20 ? 'var(--teal)' : c < 23 ? 'var(--lime)' : c < 26 ? 'var(--amber)' : 'var(--rose)';
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
    const color = dc === 'humidity' ? (v) => (v < 35 ? 'var(--amber)' : v > 60 ? 'var(--sky)' : 'var(--teal)') : (v) => warmth(v, unit);
    return `<div class="box" style="padding:12px 14px">${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<div class="rowb"><b style="font-size:14px">${esc(ctx.card.name || (dc === 'humidity' ? 'Humidity' : 'Temperature'))}</b><span class="small">last 24 h · tap a name to pick it out</span></div><div data-ctl="1">${history.readings(ctx.hass, ctx.card, ctx.H, color)}</div></div>`;
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
    const today = ok ? week[week.length - 1].change : null;
    const vals = ok ? week.map((w) => w.change || 0) : [];
    const hi = Math.max(1e-6, ...vals);
    const bars = ok ? `<div class="cols" style="height:40px;gap:4px">${vals.map((v, i) => `<span class="colbar" style="flex:1;height:${Math.max(2, v / hi * 38)}px;background:${mix(ctx.accent, i === vals.length - 1 ? 85 : 45)}"></span>`).join('')}</div>` : '';
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
      const pos = a.media_position + (playing && a.media_position_updated_at ? (Date.now() - Date.parse(a.media_position_updated_at)) / 1000 : 0);
      prog = `<div style="height:3px;border-radius:2px;background:var(--line);margin-top:8px"><div style="height:3px;border-radius:2px;width:${clamp(pos / a.media_duration * 100, 0, 100).toFixed(1)}%;background:${ctx.accent}"></div></div>`;
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

const camera = {
  item: { span: 1, grow: 2, dir: 'side', want: 3, hk: 'c' },
  accent: () => 'var(--rose)',
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {};
    const bucket = Math.floor(Date.now() / 10000);
    const src = a.access_token ? `/api/camera_proxy/${encodeURIComponent(ctx.card.entity)}?token=${encodeURIComponent(a.access_token)}&t=${bucket}` : '';
    return `<div style="position:relative;border-radius:18px;overflow:hidden;box-shadow:inset 0 0 0 1px var(--line)">${src ? `<img class="cam" src="${esc(src)}" alt="${esc(ctx.name)}" loading="lazy">` : '<div class="cam"></div>'}<div class="row" style="position:absolute;left:0;right:0;bottom:0;padding:8px 12px;background:linear-gradient(transparent, rgba(0,0,0,.55));color:#fff"><b style="font-size:13px">${esc(ctx.name)}</b><span class="flex1"></span><span style="font-size:12px;opacity:.8">${st ? esc(st.state) : 'Missing'}</span></div>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}</div>`;
  },
  more: (ctx) => histBlock(ctx, 'Events'),
  tap: () => null,
};

// -------------------------------------------------------------- the lists

const WORDS = {
  door: ['Open', 'Closed'], window: ['Open', 'Closed'], garage_door: ['Open', 'Closed'], opening: ['Open', 'Closed'],
  moisture: ['Wet', 'Dry'], smoke: ['Smoke', 'Clear'], gas: ['Gas', 'Clear'], carbon_monoxide: ['CO', 'Clear'],
  motion: ['Motion', 'Still'], occupancy: ['Occupied', 'Empty'], presence: ['Here', 'Away'], lock: ['Unlocked', 'Locked'],
  battery: ['Low', 'OK'], problem: ['Problem', 'OK'], safety: ['Unsafe', 'Safe'], vibration: ['Shaking', 'Still'],
};
const listWord = (st) => {
  if (!st) return ['Missing', false];
  if (UNAVAILABLE.includes(st.state)) return ['Unavailable', false];
  const w = WORDS[st.attributes.device_class] || ['On', 'Off'];
  const on = st.state === 'on';
  return [on ? w[0] : w[1], on];
};
const list = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: (ctx) => ((ctx.card.entities || []).some((e) => listWord(ctx.hass.states[e])[1]) ? 'var(--rose)' : 'var(--teal)'),
  face: (ctx) => {
    const rows = (ctx.card.entities || []).map((e) => { const st = ctx.hass.states[e]; const [w, on] = listWord(st); return { e, w, on, name: shortName(friendly(ctx.hass, e), ctx.sec.title), st }; });
    rows.sort((a, b) => (b.on - a.on));
    const openRows = rows.filter((r) => r.on);
    const summary = openRows.length ? `${openRows.length === 1 ? openRows[0].name : openRows.length + ' of ' + rows.length} ${openRows.length === 1 ? openRows[0].w.toLowerCase() : 'need you'}` : `All ${rows[0] ? listWord(rows[0].st)[0].toLowerCase() : 'quiet'}`;
    const shown = ctx.open ? rows : rows.slice(0, 6);
    return `<div class="box" style="box-shadow:inset 0 0 0 1px ${openRows.length ? mix('var(--rose)', 35) : 'var(--line)'};padding:12px 12px 8px 16px"><div class="rowb"><b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${openRows.length ? 'var(--rose)' : 'var(--teal)'}">${esc(summary)}</span></div>
${shown.map((r) => `<button type="button" class="lrow" data-ctl="1" data-act="member" data-v="${esc(r.e)}" style="padding:7px 4px"><span class="lx"><span>${esc(r.name)}</span></span><span style="font-size:13px;font-weight:600;color:${r.on ? 'var(--rose)' : 'var(--quiet)'}">${esc(r.w)}</span><span class="small">${r.st ? esc(since(r.st.last_changed).replace('since ', '')) : ''}</span></button>`).join('')}${rows.length > shown.length ? `<span class="small" style="padding:4px">+${rows.length - shown.length} more · hold to see them</span>` : ''}</div>`;
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
  accent: (ctx) => (ctx.st && ctx.st.state === 'home' ? 'var(--teal)' : 'var(--sky)'),
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

const ALARM = [['disarmed', 'Off', 'alarm_disarm'], ['armed_home', 'Home', 'alarm_arm_home'], ['armed_away', 'Away', 'alarm_arm_away'], ['armed_night', 'Night', 'alarm_arm_night']];
const alarm = {
  item: { span: 2, grow: 3, dir: 'down', want: 3 },
  accent: (ctx) => (ctx.st && ctx.st.state === 'triggered' ? 'var(--rose)' : ctx.st && ctx.st.state.startsWith('armed') ? 'var(--teal)' : 'var(--quiet)'),
  face: (ctx) => {
    const st = ctx.st; const a = (st && st.attributes) || {};
    return `<div class="box" style="box-shadow:inset 0 0 0 1px var(--line)"><div class="row">${icon('shield', { color: ctx.accent, size: 18 })}<b style="font-size:14px">${esc(ctx.name)}</b><span class="flex1"></span>${ctx.hint ? `<span class="hint">${esc(ctx.hint)}</span>` : ''}<span style="font-size:13px;font-weight:700;color:${ctx.accent}">${esc(ctx.confirm || (st ? st.state.replace('_', ' ') : 'Missing'))}</span></div>
${a.code_format ? '<p class="small">Needs a code — hold to enter it.</p>' : words(ALARM.map((m) => svcBtn(m[1], 'alarm_control_panel', m[2], { entity_id: ctx.card.entity }, { pressed: st && st.state === m[0], confirm: m[0] === 'disarmed' ? 'Tap again to disarm' : '' })))}</div>`;
  },
  more: (ctx) => {
    const a = (ctx.st && ctx.st.attributes) || {};
    const code = a.code_format ? `${blockLabel('Code')}<input class="fld" type="password" inputmode="numeric" data-alarm-code="1" autocomplete="off">${words(ALARM.map((m) => `<button type="button" class="wd" data-ctl="1" data-act="alarm" data-service="${m[2]}">${m[1]}</button>`))}` : '';
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

export function typeOf(card) {
  return TYPES[card.type] || TYPES.entity;
}

export const isFull = (card) => !!typeOf(card).item.full;
