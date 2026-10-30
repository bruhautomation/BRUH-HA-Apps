/* A house for Morph's measures: the real panel modules, a stubbed `hass`.
 *
 * The panel runs inside Home Assistant's frontend, which nothing here can
 * start, so the page builds the one object the panel is handed — `hass`,
 * with `states`, `callService`, `callWS` and a `connection` — and answers
 * the websocket commands the integration registers (`morph/*`) and the core
 * ones the cards read (history, statistics, logbook, conversation,
 * forecasts) from memory. The shapes are Home Assistant's own: a fixture
 * that invents a shape only ever agrees with itself.
 *
 * The house is BRUH house's structure, in the spirit of the design
 * prototype (docs/design/morph-ui.html): three floors and a Whole house
 * floor of systems, light groups with members, thermostats, overlaid
 * readings, a lock, a garage door, media, a camera, people, and one brAIn
 * finding and one Morph suggestion to be placed in their rooms.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { stub as panelStub, INSIGHTS } from './today-fixture.mjs';

// brAIn's own panel (brain/panel), for opts.realFrame: the shell frames the
// real page rather than a stand-in, so what one screen shows — one header,
// no bottom tab bar, one theme — is measured on the real thing.
export const PANEL = fileURLToPath(new URL('../../brain/panel/', import.meta.url));
export const BRAIN_VERSION = '4.0.5';

// Enough insight cards for the Insights pane to offer its search (more
// than REPORT_SEARCH_AFTER in app.js) and to be taller than a phone, so a
// measure can scroll it: opts.insights = MANY_INSIGHTS.
export const MANY_INSIGHTS = Array.from({ length: 12 }, (_, i) => ({
  ...INSIGHTS[i % INSIGHTS.length], id: `custom-${i + 1}`,
  title: `${INSIGHTS[i % INSIGHTS.length].title} (${i + 1})`,
}));

// An iPhone's safe area (its Dynamic Island strip on top, the home
// indicator below), the way Safari and the Home Assistant app report it to
// env(safe-area-inset-*): Chromium's own override, so the page under test
// reads it exactly where a phone's would rather than from a stand-in.
export async function safeArea(page, top, bottom = 0) {
  const c = await page.context().newCDPSession(page);
  await c.send('Emulation.setSafeAreaInsetsOverride', { insets: { top, topMax: top, bottom, bottomMax: bottom, left: 0, leftMax: 0, right: 0, rightMax: 0 } });
  return c;
}

export const FRONTEND = fileURLToPath(new URL('../../brain/custom_components/brain/morph/frontend/', import.meta.url));
export const ORIGIN = 'http://morph.test';
export const VERSION = '0.5.6';
export const STAMP = 'f00dfeed0001';

const light = (id, name, on, bri, extra) => [`light.${id}`, { entity_id: `light.${id}`, state: on ? 'on' : 'off', attributes: { friendly_name: name, brightness: on ? Math.round(bri * 2.55) : null, color_mode: on ? 'color_temp' : null, supported_color_modes: ['color_temp', 'hs'], color_temp_kelvin: on ? 2700 : null, min_color_temp_kelvin: 2200, max_color_temp_kelvin: 6500, ...(extra || {}) } }];
const ago = (min) => new Date(Date.now() - min * 60000).toISOString();

export function house() {
  const S = {};
  const put = ([k, v]) => { S[k] = { last_changed: ago(40), last_updated: ago(40), ...v }; };
  for (let i = 1; i <= 6; i++) put(light(`kitchen_cans_${i}`, `Kitchen Can ${i}`, true, 35));
  put(light('kitchen_cans', 'Kitchen Cans', true, 35, { entity_id: [1, 2, 3, 4, 5, 6].map((i) => `light.kitchen_cans_${i}`) }));
  put(light('kitchen_countertop', 'Kitchen Countertop', true, 50));
  put(light('bar', 'Bar', true, 40));
  for (let i = 1; i <= 4; i++) put(light(`living_room_cans_${i}`, `Living Room Can ${i}`, true, 40));
  put(light('living_room_cans', 'Living Room Cans', true, 40, { entity_id: [1, 2, 3, 4].map((i) => `light.living_room_cans_${i}`) }));
  put(light('entryway', 'Entryway', true, 30));
  put(light('mudroom', 'Mudroom', false, 70));
  for (let i = 1; i <= 4; i++) put(light(`master_cans_${i}`, `Master Can ${i}`, false, 60));
  put(light('master_cans', 'Master Cans', false, 60, { entity_id: [1, 2, 3, 4].map((i) => `light.master_cans_${i}`) }));
  put(light('bens_nightstand', 'Ben’s Nightstand', true, 25));
  put(light('cailins_nightstand', 'Cailin’s Nightstand', false, 25));
  put(light('hue_go', 'Hue Go', true, 40, { color_mode: 'hs', hs_color: [280, 70], rgb_color: [180, 90, 255] }));
  put(light('loft', 'Loft', true, 30));
  put(light('laundry_room', 'Laundry Room', true, 80));
  put(light('front_porch', 'Front Porch', true, 70));
  put(light('string_lights', 'String Lights', true, 60, { color_mode: 'hs', hs_color: [30, 80], rgb_color: [255, 170, 60] }));
  put(light('driveway_flood', 'Driveway Flood', false, 100));
  put(['fan.living_room', { entity_id: 'fan.living_room', state: 'on', attributes: { friendly_name: 'Living Room Fan', percentage: 40, direction: 'forward', oscillating: false } }]);
  put(['fan.master', { entity_id: 'fan.master', state: 'on', attributes: { friendly_name: 'Master Fan', percentage: 30, direction: 'forward' } }]);
  put(['cover.living_room', { entity_id: 'cover.living_room', state: 'closed', attributes: { friendly_name: 'Living Room Blinds', current_position: 0, device_class: 'blind' } }]);
  put(['cover.master', { entity_id: 'cover.master', state: 'open', attributes: { friendly_name: 'Master Blinds', current_position: 60, current_tilt_position: 40, device_class: 'blind' } }]);
  put(['cover.garage_door', { entity_id: 'cover.garage_door', state: 'closed', attributes: { friendly_name: 'Garage Door', device_class: 'garage' } }]);
  put(['lock.front_door', { entity_id: 'lock.front_door', state: 'locked', attributes: { friendly_name: 'Front Door', battery_level: 81 } }]);
  put(['lock.mudroom', { entity_id: 'lock.mudroom', state: 'locked', attributes: { friendly_name: 'Mudroom Door' } }]);
  put(['switch.party_light', { entity_id: 'switch.party_light', state: 'off', attributes: { friendly_name: 'Party Light' } }]);
  put(['switch.frame_art', { entity_id: 'switch.frame_art', state: 'on', attributes: { friendly_name: 'Frame Art' } }]);
  put(['switch.irrigation', { entity_id: 'switch.irrigation', state: 'off', attributes: { friendly_name: 'Irrigation' } }]);
  put(['input_boolean.guest_mode', { entity_id: 'input_boolean.guest_mode', state: 'off', attributes: { friendly_name: 'Guest mode' } }]);
  put(['script.drop_humidity', { entity_id: 'script.drop_humidity', state: 'off', attributes: { friendly_name: 'Drop humidity' } }]);
  put(['script.movie_time', { entity_id: 'script.movie_time', state: 'off', attributes: { friendly_name: 'Movie time' } }]);
  put(['climate.downstairs', { entity_id: 'climate.downstairs', state: 'cool', attributes: { friendly_name: 'Downstairs', current_temperature: 73.2, temperature: 72, hvac_action: 'cooling', hvac_modes: ['off', 'heat', 'cool', 'heat_cool'], fan_modes: ['auto', 'on'], fan_mode: 'auto', min_temp: 58, max_temp: 82, current_humidity: 51, target_temp_step: 1 } }]);
  put(['climate.upstairs', { entity_id: 'climate.upstairs', state: 'cool', attributes: { friendly_name: 'Upstairs', current_temperature: 74.6, temperature: 73, hvac_action: 'idle', hvac_modes: ['off', 'heat', 'cool'], min_temp: 58, max_temp: 82, current_humidity: 48, target_temp_step: 1 } }]);
  const temps = [['kitchen', 'Kitchen', 72.4], ['living_room', 'Living Room', 73.1], ['master', 'Master', 74.8], ['loft', 'Loft', 75.2], ['office', 'Office', 71.6], ['attic', 'Attic', 96.3], ['outside', 'Outside', 61.5]];
  temps.forEach(([id, n, v]) => put([`sensor.${id}_temperature`, { entity_id: `sensor.${id}_temperature`, state: String(v), attributes: { friendly_name: `${n} Temperature`, device_class: 'temperature', unit_of_measurement: '°F', state_class: 'measurement' } }]));
  [['kitchen', 'Kitchen', 49], ['master', 'Master', 47], ['basement', 'Basement', 58]].forEach(([id, n, v]) => put([`sensor.${id}_humidity`, { entity_id: `sensor.${id}_humidity`, state: String(v), attributes: { friendly_name: `${n} Humidity`, device_class: 'humidity', unit_of_measurement: '%', state_class: 'measurement' } }]));
  put(['sensor.water_usage', { entity_id: 'sensor.water_usage', state: '48211', attributes: { friendly_name: 'Water usage', device_class: 'water', unit_of_measurement: 'gal', state_class: 'total_increasing' } }]);
  put(['media_player.living_room_tv', { entity_id: 'media_player.living_room_tv', state: 'playing', attributes: { friendly_name: 'Living Room TV', device_class: 'tv', media_title: 'The Bear', media_artist: 'S3 · E4', app_name: 'Apple TV', volume_level: 0.22, source_list: ['Apple TV', 'PS5', 'Antenna'], source: 'Apple TV', media_duration: 1800, media_position: 600, media_position_updated_at: ago(1) } }]);
  put(['media_player.kitchen_speaker', { entity_id: 'media_player.kitchen_speaker', state: 'idle', attributes: { friendly_name: 'Kitchen Speaker', volume_level: 0.15 } }]);
  put(['camera.front_door', { entity_id: 'camera.front_door', state: 'idle', attributes: { friendly_name: 'Front Door Camera', access_token: 'tok' } }]);
  put(['camera.driveway', { entity_id: 'camera.driveway', state: 'recording', attributes: { friendly_name: 'Driveway Camera', access_token: 'tok' } }]);
  [['front_door', 'Front Door', 'door', 'off'], ['back_door', 'Back Door', 'door', 'off'], ['garage_freezer', 'Garage Freezer', 'door', 'on'], ['office_window', 'Office Window', 'window', 'off'], ['laundry_leak', 'Laundry Leak', 'moisture', 'off']].forEach(([id, n, dc, s]) => put([`binary_sensor.${id}`, { entity_id: `binary_sensor.${id}`, state: s, attributes: { friendly_name: n, device_class: dc } }]));
  put(['person.ben', { entity_id: 'person.ben', state: 'home', attributes: { friendly_name: 'Ben' } }]);
  put(['person.cailin', { entity_id: 'person.cailin', state: 'not_home', attributes: { friendly_name: 'Cailin' } }]);
  put(['weather.home', { entity_id: 'weather.home', state: 'partlycloudy', attributes: { friendly_name: 'Home', temperature: 62, humidity: 71, wind_speed: 8, wind_speed_unit: 'mph', temperature_unit: '°F' } }]);
  put(['alarm_control_panel.house', { entity_id: 'alarm_control_panel.house', state: 'disarmed', attributes: { friendly_name: 'House alarm' } }]);
  put(['vacuum.obi', { entity_id: 'vacuum.obi', state: 'docked', attributes: { friendly_name: 'Obi', battery_level: 100 } }]);
  ['scene.kitchen_bright', 'scene.kitchen_dim', 'scene.kitchen_off', 'scene.living_room_movie', 'scene.living_room_dim', 'scene.morning', 'scene.evening', 'scene.interior_off'].forEach((e, i) => put([e, { entity_id: e, state: i === 1 || i === 6 ? ago(30) : ago(60 * 30), attributes: { friendly_name: e.split('.')[1].replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) } }]));
  put(['sun.sun', { entity_id: 'sun.sun', state: 'below_horizon', attributes: { next_rising: new Date(Date.now() + 9 * 3600000).toISOString(), next_setting: new Date(Date.now() + 2 * 3600000).toISOString() } }]);
  put(['timer.laundry', { entity_id: 'timer.laundry', state: 'active', attributes: { friendly_name: 'Washer', finishes_at: new Date(Date.now() + 31 * 60000).toISOString() } }]);
  // Coming up's other kinds: a calendar event with a length, a timer that
  // knows its duration (a running bar), and an automation that ran at this
  // time yesterday (a dashed "usually").
  const local = (ms) => { const d = new Date(ms); const p2 = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:00`; };
  put(['calendar.family', { entity_id: 'calendar.family', state: 'off', attributes: { friendly_name: 'Family', message: 'School drop-off', start_time: local(Date.now() + 5 * 3600000), end_time: local(Date.now() + 5.5 * 3600000), all_day: false } }]);
  put(['timer.print', { entity_id: 'timer.print', state: 'active', attributes: { friendly_name: '3D print — console insert v4 (PETG, 0.2 mm)', duration: '3:00:00', finishes_at: new Date(Date.now() + 95 * 60000).toISOString() } }]);
  put(['automation.porch', { entity_id: 'automation.porch', state: 'on', attributes: { friendly_name: 'Porch lights on', last_triggered: new Date(Date.now() - 21 * 3600000).toISOString() } }]);
  return S;
}

const C = (entity, extra) => ({ entity, ...(extra || {}) });
export function dashboard() {
  let n = 0;
  const id = (p) => `${p}_${++n}`;
  const card = (c) => ({ id: c.id || id('c'), ...c, type: c.type || guess(c.entity || (c.entities || [])[0]) });
  const guess = (e) => ({ light: 'light', fan: 'fan', cover: 'cover', lock: 'lock', switch: 'switch', input_boolean: 'switch', climate: 'climate', sensor: 'sensor', media_player: 'media', camera: 'camera', binary_sensor: 'list', person: 'person', weather: 'weather', vacuum: 'vacuum', alarm_control_panel: 'alarm', scene: 'scenes', script: 'button' }[String(e).split('.')[0]] || 'entity');
  const sec = (sid, title, color, width, groups, area) => ({ id: sid, title, color, width, ...(area ? { area } : {}), groups: groups.map((g) => ({ ...(g.label ? { label: g.label } : {}), cards: g.cards.map(card) })) });
  return {
    title: 'Home', story: true, ask: true, coming_up: true,
    scenes: ['scene.morning', 'scene.evening', 'scene.interior_off'],
    floors: [
      { id: 'f_first_floor', title: 'First floor', sections: [
        sec('s_kitchen', 'Kitchen', 'sand', 3, [
          { cards: [{ id: 'c_kitchen_scenes', type: 'scenes', entities: ['scene.kitchen_bright', 'scene.kitchen_dim', 'scene.kitchen_off'] }] },
          { cards: [{ id: 'c_kitchen_cans', type: 'light_group', entity: 'light.kitchen_cans', name: 'Cans' }, C('light.kitchen_countertop', { id: 'c_countertop', name: 'Countertop' }), C('light.bar', { id: 'c_bar' })] },
          { cards: [C('media_player.kitchen_speaker', { id: 'c_kspeaker', name: 'Speaker' })] },
        ], 'kitchen'),
        sec('s_living', 'Living Room', 'amber', 3, [
          { cards: [{ type: 'scenes', entities: ['scene.living_room_movie', 'scene.living_room_dim'] }] },
          { cards: [{ id: 'c_lr_cans', type: 'light_group', entity: 'light.living_room_cans', name: 'Cans' }, C('fan.living_room', { id: 'c_lr_fan', name: 'Fan' }), C('cover.living_room', { id: 'c_lr_blinds', name: 'Blinds' })] },
          { cards: [C('media_player.living_room_tv', { id: 'c_tv', name: 'TV' })] },
          { label: 'Party', cards: [C('switch.party_light', { id: 'c_party' }), C('script.movie_time', { id: 'c_movie' })] },
        ], 'living_room'),
        sec('s_entry', 'Entry', 'teal', 2, [
          // A house's own "Now" card (a hosted custom card) whose Next chip
          // opens Coming up under it (the morph-coming-up event, AGENTS.md).
          { cards: [{ id: 'c_now', type: 'lovelace', card: { type: 'custom:morph-next' } }] },
          { cards: [C('light.entryway', { id: 'c_entryway' }), C('light.mudroom', { id: 'c_mudroom' })] },
          { cards: [C('lock.front_door', { id: 'c_front_lock' }), C('cover.garage_door', { id: 'c_garage' })] },
        ], 'entry'),
      ] },
      { id: 'f_upstairs', title: 'Upstairs', sections: [
        sec('s_master', 'Master Bedroom', 'violet', 3, [
          { cards: [{ id: 'c_master_cans', type: 'light_group', entity: 'light.master_cans', name: 'Cans' }, C('light.bens_nightstand', { id: 'c_bens' }), C('light.cailins_nightstand', { id: 'c_cailins' }), C('light.hue_go', { id: 'c_huego' })] },
          { cards: [C('fan.master', { id: 'c_master_fan', name: 'Fan' }), C('cover.master', { id: 'c_master_blinds', name: 'Blinds' })] },
        ], 'master'),
        sec('s_loft', 'Loft', 'lime', 2, [
          { cards: [C('light.loft', { id: 'c_loft' }), C('switch.frame_art', { id: 'c_frame' })] },
        ], 'loft'),
        sec('s_laundry', 'Laundry', 'sky', 2, [
          { cards: [C('light.laundry_room', { id: 'c_laundry', name: 'Light' }), C('vacuum.obi', { id: 'c_obi' })] },
        ], 'laundry'),
      ] },
      { id: 'f_outside', title: 'Outside', sections: [
        sec('s_porch', 'Porch', 'peach', 2, [
          { cards: [C('light.front_porch', { id: 'c_porch' }), C('light.string_lights', { id: 'c_strings' }), C('light.driveway_flood', { id: 'c_flood' })] },
          { cards: [C('camera.front_door', { id: 'c_cam_front', name: 'Front door' }), C('camera.driveway', { id: 'c_cam_drive', name: 'Driveway' })] },
        ], 'porch'),
        sec('s_yard', 'Yard', 'lime', 2, [
          { cards: [C('switch.irrigation', { id: 'c_irrigation' }), { id: 'c_tile', type: 'lovelace', card: { type: 'tile', entity: 'sensor.outside_temperature' } }] },
        ], 'yard'),
      ] },
      { id: 'f_whole_house', title: 'Whole house', sections: [
        sec('s_climate', 'Climate', 'sky', 4, [
          { cards: [C('weather.home', { id: 'c_weather' }), C('climate.downstairs', { id: 'c_down', options: { actions: ['script.drop_humidity'] } }), C('climate.upstairs', { id: 'c_up' })] },
          { cards: [{ id: 'c_temps', type: 'readings', name: 'Temperature', entities: ['sensor.kitchen_temperature', 'sensor.living_room_temperature', 'sensor.master_temperature', 'sensor.loft_temperature', 'sensor.office_temperature', 'sensor.attic_temperature', 'sensor.outside_temperature'] }] },
          { cards: [{ id: 'c_hums', type: 'readings', name: 'Humidity', entities: ['sensor.kitchen_humidity', 'sensor.master_humidity', 'sensor.basement_humidity'] }] },
        ]),
        sec('s_security', 'Security', 'rose', 2, [
          { cards: [C('alarm_control_panel.house', { id: 'c_alarm' })] },
          { cards: [C('lock.front_door', { id: 'c_sec_front' }), C('lock.mudroom', { id: 'c_sec_mud' })] },
          { label: 'Doors and windows', cards: [{ id: 'c_doors', type: 'list', name: 'Doors and windows', entities: ['binary_sensor.front_door', 'binary_sensor.back_door', 'binary_sensor.garage_freezer', 'binary_sensor.office_window', 'binary_sensor.laundry_leak'] }] },
          { label: 'People', cards: [C('person.ben', { id: 'c_ben' }), C('person.cailin', { id: 'c_cailin' })] },
        ]),
        sec('s_water', 'Water', 'teal', 2, [
          { cards: [{ id: 'c_water', type: 'meter', entity: 'sensor.water_usage' }, C('sensor.basement_humidity', { id: 'c_bhum' })] },
        ]),
      ] },
    ],
  };
}

export function state() {
  return {
    version: VERSION,
    settings: { learning: true, learning_hours: 24, report_code_issues: true, tell_model: '', learn_model: '', theme: 'dark', reduce_motion: false, hold_ms: 540 },
    brain: { state: 'ok', sentence: 'brAIn is ready.' },
    learning: { last_pass: Date.now() / 1000 - 7200, last_note: 'Learned from 412 uses; 1 new suggestion.', scorecard: { suggested: 6, done: 3, declined: 2, open: 1, tells: 9, tells_kept: 8, tells_undone: 1, lessons: 3 }, lessons: ['Keep the Kitchen and Living Room on the first row; they are used every evening.', 'Never put the alarm on the first floor.', 'Prefer words over icons for scenes.'] },
    suggestions: [{ id: 'g1', key: 'k', title: 'Turn the living room fan light off when the room empties', why: 'You turned it off by hand on 9 of the last 14 evenings.', change: 'Add an automation that turns off the living room fan when the living room has had no motion for 15 minutes.', kind: 'house', status: 'open', section: 's_living' }],
    devloop: { enabled: true, waiting: 1, picked_up_at: Date.now() / 1000 - 3600, filed: 2 },
    note: '',
  };
}

// brAIn's published files, as Morph's integration hands them to the panel
// (contracts: /config/.brain/morph/cases.json and feed.json). The house's
// measurements are examples in brAIn's shapes: the kitchen usually sits at
// 71.5 at this hour, the back door is usually shut, the master cans have a
// habit about now.
export function brainFeed(opts) {
  const o = opts || {};
  const now = Date.now();
  const d = new Date(now); const minute = d.getHours() * 60 + d.getMinutes();
  return {
    installed: o.installed !== false,
    situation: { sentence: 'It is a quiet evening: the living room is watching TV and upstairs is winding down.', at: now / 1000 - 300 },
    findings: [],
    cases: o.cases || [
      { id: 'f:1791000000', kind: 'problem', claim: 'The garage freezer door has been open for 25 minutes.', ask: 'Close it, or tell me it is meant to be open.', detail: 'It usually closes within a minute; the latch may not catch.', severity: 'warning', stakes: 'medium', urgent: false, entity_id: 'binary_sensor.garage_freezer', evidence: [], area_id: '', source: 'check:dev.left_open', source_title: 'Left open', fixable: false, status: 'open', plan: null, todo_text: 'Close the garage freezer door.', thread: [], answers: [{ action: 'todo', label: 'Add to To Do' }, { action: 'dismiss', label: 'Dismiss' }], created_at: now / 1000 - 1500 },
      { id: 'h:1791000100', kind: 'question', claim: 'The office lamp looks like it is on a timer.', ask: 'Is it?', detail: '', severity: 'info', stakes: 'low', urgent: false, entity_id: '', evidence: [], area_id: '', source: 'curiosity', source_title: 'A guess', fixable: false, status: 'open', plan: null, todo_text: 'Check the office lamp timer.', thread: [{ who: 'brain', text: 'It turns on at 6:00 PM every weekday.', at: now / 1000 - 600 }], answers: [{ action: 'not_applicable', label: "Doesn't apply" }], created_at: now / 1000 - 900 },
    ],
    todo: o.todo || [{ id: 12, text: 'Replace the battery in the hallway motion sensor.', entity_id: '', area_id: '', snoozed_until: null, origin: '' }],
    open: 2,
    cases_at: now / 1000,
    feed: o.feed === null ? null : {
      v: 1, at: now / 1000, stale_after_s: 7200, tz: 'UTC',
      bucket: { now: 0, next: 1, until: now / 1000 + 1800 },
      rhythm: o.rhythm || { weekday: { wake: null, settle: null }, weekend: { wake: null, settle: null } },
      normal: { 'sensor.kitchen_temperature': { now: [71.5, 0.2, 40], next: [71.4, 0.2, 40], unit: '°F' }, 'sensor.master_temperature': { now: [74.6, 0.4, 40], next: [74.4, 0.4, 40], unit: '°F' } },
      doors: { 'binary_sensor.back_door': { now: 0.05, next: 0.05 }, 'lock.front_door': { now: 0.02, next: 0.02 } },
      habits: [{ entity_id: 'light.master_cans', state: 'on', minute: (minute + 10) % 1440, spread: 7, days: 'every day', share: 0.85, days_seen: 23, person: 'person.ben' }],
      people: { 'person.ben': { name: 'Ben', user_id: 'u-ben' } },
      appliances: {},
    },
    feed_mtime: now / 1000,
    status: { state: 'watching' },
  };
}

// The page: the panel, and a `hass` that answers like Home Assistant.
export function page(opts) {
  const o = opts || {};
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>html,body{margin:0;height:100%;background:#000}</style></head><body>
<script>
customElements.define('morph-next', class extends HTMLElement {
  setConfig(c) { this.c = c; if (!this.shadowRoot) this.attachShadow({ mode: 'open' }); this.draw(); }
  set hass(h) { this._h = h; this.draw(); }
  draw() {
    if (!this.shadowRoot) return;
    const ev = this._h && this._h.states['calendar.family'];
    const what = ev ? ev.attributes.message : 'Nothing';
    this.shadowRoot.innerHTML = '<style>:host{display:block;padding:14px 16px;font:15px system-ui;color:#e8e8e8}button{font:inherit;min-height:44px;padding:0 14px;border-radius:22px;border:1px solid #556;background:transparent;color:inherit}button[aria-pressed="true"]{background:#2b3140}</style><div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><b>Now</b><span>Quiet evening</span><button type="button" data-next-chip aria-pressed="' + !!this._shown + '">Next · ' + what + '</button></div>';
    this.shadowRoot.querySelector('button').onclick = () => {
      const e = new CustomEvent('morph-coming-up', { bubbles: true, composed: true, detail: {} });
      this.dispatchEvent(e);
      window.__nextShown = e.detail.shown;
      this._shown = e.detail.shown; this.draw();
    };
  }
});
</script>
<script>window.__calls = []; window.__ws = []; window.__fixture = ${JSON.stringify({ states: house(), dash: dashboard(), state: themed(state(), o.theme), brain: brainFeed(o.brain), dark: o.dark !== false })};</script>
<script type="module">
const F = window.__fixture;
let states = F.states;
let dash = F.dash; let rev = 'r1'; let tells = {}; let seq = 0;
const now = Date.now();
const listeners = [];
function series(eid, start, end, step) {
  const st = states[eid]; const base = parseFloat(st && st.state) || 50; const out = [];
  for (let t = start; t <= end; t += step) out.push({ start: t, end: t + step, mean: base + Math.sin(t / 3600000 / 3 + base) * 1.5, min: base - 2, max: base + 2, change: 120 + Math.sin(t / 86400000) * 40, state: base });
  return out;
}
const hass = {
  states, config: { unit_system: { temperature: '°F' } }, themes: { darkMode: F.dark }, user: { id: 'u-ben', is_admin: true },
  entities: { 'conversation.brain': { entity_id: 'conversation.brain', platform: 'brain' }, 'fan.living_room': { entity_id: 'fan.living_room', platform: 'zwave_js', device_id: 'dev_lr_fan' } }, devices: { dev_lr_fan: { id: 'dev_lr_fan', name: 'Living room fan' } },
  callService(domain, service, data) {
    window.__calls.push({ domain, service, data });
    const ids = [].concat((data && data.entity_id) || []);
    ids.forEach((e) => {
      const s = states[e]; if (!s) return;
      const n = { ...s, attributes: { ...s.attributes }, last_changed: new Date().toISOString() };
      if (service === 'toggle') n.state = s.state === 'on' ? 'off' : 'on';
      if (service === 'turn_on') { n.state = 'on'; if (data.brightness_pct) n.attributes.brightness = Math.round(data.brightness_pct * 2.55); }
      if (service === 'turn_off') n.state = 'off';
      if (service === 'unlock') n.state = 'unlocked';
      if (service === 'lock') n.state = 'locked';
      if (service === 'set_percentage') n.attributes.percentage = data.percentage;
      if (service === 'set_cover_position') { n.attributes.current_position = data.position; n.state = data.position > 0 ? 'open' : 'closed'; }
      states = { ...states, [e]: n };
    });
    push();
    return Promise.resolve();
  },
  async callWS(msg) {
    window.__ws.push(msg);
    const t = msg.type;
    // brAIn's shell (opts.shell): its own command, and the Supervisor's
    // ingress session the way Home Assistant's ingress view asks for it.
    if (t === 'brain/shell') return { admin: ${o.notAdmin ? 'false' : 'true'}, features: { morph: ${o.morph === false ? 'false' : 'true'}, personality: true, learning_loop: true, development_loop: false, name: 'Juniper' }, ingress_url: '/api/hassio_ingress/abcdefghijkl/', slug: 'x_brain' };
    if (t === 'supervisor/api') return msg.endpoint === '/ingress/session' ? { session: 'sess-test' } : {};
    if (t === 'morph/load') return { mirror: { revision: rev, dashboard: dash, problems: [], card_modules: window.__cardModules || [] }, state: F.state, brain: F.brain, admin: true, now: Date.now() / 1000, code: window.__code || '${STAMP}', integration: window.__integration || '${VERSION}' };
    if (t === 'morph/request') {
      const p = msg.payload || {};
      if (msg.kind === 'save') { if (p.base && p.base !== rev) return { ok: false, conflict: true, error: 'changed' }; dash = p.dashboard; rev = 'r' + (++seq + 1); return { ok: true, commit: 'abc' + seq, revision: rev }; }
      if (msg.kind === 'tell') { const id = 'morph-t' + (++seq); tells[id] = { id, phase: 'waiting', steps: [{ t: 'Reading ' + (p.target.path || ''), tone: '' }, ...(p.shot ? [{ t: 'Took a picture of it for brAIn', tone: '' }] : []), { t: 'Handed to brAIn as task ' + id, tone: '' }], payload: 'MORPH · a change request…\\nAsked: “' + p.text + '”' , text: p.text, at: Date.now(), started: Date.now() / 1000, issueAsk: /Morph cannot/.test(p.text) }; return { ok: true, ...tells[id] }; }
      // Make it again: a tell about Morph's own module, answered the way morphd.handle does.
      if (msg.kind === 'code_redo' || msg.kind === 'code_merge_all') { if (msg.kind === 'code_merge_all') p.name = 'all'; await new Promise((r) => setTimeout(r, window.__redoDelay || 0)); if (window.__redoError) return { ok: false, error: window.__redoError }; const run = Object.values(tells).find((x) => x.redo === p.name && x.phase !== 'done'); if (run) return { ok: true, already: true, ...run }; const id = 'morph-t' + (++seq); tells[id] = { id, redo: p.name, conflict: !!window.__redoConflict, phase: 'waiting', steps: [{ t: 'Reading Morph’s own code', tone: '' }, { t: 'Handed to brAIn as task ' + id, tone: '' }], text: 'Make my change to Morph’s ' + p.name + ' again on the new Morph (' + F.state.version + ').', at: Date.now(), started: Date.now() / 1000 }; F.state.activity = [{ id, kind: 'code', target: p.name, label: p.name, path: 'Morph’s own code', text: tells[id].text, phase: 'waiting', started: Date.now() / 1000 }]; return { ok: true, ...tells[id] }; }
      if (msg.kind === 'tell_answer') { const s = tells[p.id]; const o = s && s.question && s.question.options[p.choice]; if (!o || s.answered != null) return { ok: false, error: 'That question is gone.' }; s.answered = p.choice; const id = 'morph-t' + (++seq); tells[id] = { id, phase: 'waiting', steps: [{ t: 'Handed to brAIn as task ' + id, tone: '' }], text: o.request, at: Date.now(), started: Date.now() / 1000, scope: o.home_assistant ? 'house' : 'ui', makesSensor: !!o.home_assistant, redo: s.redo }; return { ok: true, ...tells[id] }; }
      if (msg.kind === 'tell_issue') { const s = tells[p.id]; if (s) s.issue = p.verb === 'send' ? 'sent' : 'declined'; return { ok: true }; }
      if (msg.kind === 'tell_undo') return { ok: true, commit: 'undo1' };
      if (msg.kind === 'report') { if (!String(p.text || '').trim()) return { ok: false, error: 'Say what should be fixed.' }; F.state.devloop = { ...F.state.devloop, mine: [{ fp: 'fp' + (++seq), what: p.text, ui: !!p.ui, at: Date.now() / 1000, picked: false }].concat(F.state.devloop.mine || []) }; return { ok: true }; }
      if (msg.kind === 'history') return { ok: true, log: [{ sha: 'abc1', who: 'brain', at: Date.now() / 1000 - 600, message: 'brAIn: Added a Pets section' }, { sha: 'abc0', who: 'person', at: Date.now() / 1000 - 7200, message: 'Moved a section' }] };
      if (msg.kind === 'converse') { const id = 'conv-t' + (++seq); tells[id] = { id, kind: 'conversation', phase: 'working', steps: [{ t: 'brAIn is thinking', tone: '' }], at: Date.now(), text: p.text, conv: true }; return { ok: true, ...tells[id] }; }
      if (msg.kind === 'habit' || msg.kind === 'lesson_add') return { ok: true };
      if (msg.kind === 'settings') { F.state.settings = { ...F.state.settings, ...p.patch }; return { ok: true, settings: F.state.settings }; }
      return { ok: true };
    }
    if (t === 'morph/tell_status') {
      const s = tells[msg.tell]; if (!s) return { phase: 'missing' };
      // window.__convEcho: each answer names its question, and a question
      // with "slow" in it takes longer, so two asked back to back finish
      // out of order (measure-morph's Ask stack).
      if (s.conv) { const echo = window.__convEcho; const wait = echo && /slow/i.test(s.text) ? 2600 : 700; if (Date.now() - s.at > wait) { s.phase = 'done'; s.say = echo ? 'You asked: ' + s.text : 'Upstairs is warm because the attic is 96° and the Upstairs thermostat is holding at 73°. The Master Fan is on.'; s.session_id = 'sess-' + s.id.replace(/[^a-z0-9]/g, '') + 'abcd'; } return { ...s }; }
      if (Date.now() - s.at > 500 && s.phase === 'waiting') { s.phase = 'working'; s.steps.push({ t: 'brAIn is on it', tone: '' }, { t: 'Looking at the screenshot', tone: '', brain: true }, { t: 'Reading dashboard.yaml', tone: '', brain: true }); }
      if (s.redo && s.conflict && Date.now() - s.at > 1500 && s.phase !== 'done') { s.phase = 'done'; s.say = 'The update rewrote the header your switch was in.'; s.steps.push({ t: 'Read both versions of ' + s.redo, tone: '' }); s.question = { text: 'The new header moved the gear into a menu. Where should the theme switch go?', options: [{ label: 'Beside the gear menu', request: 'Put the theme switch beside the new gear menu in /config/morph/frontend/' + s.redo + '.', home_assistant: false }, { label: 'Inside the gear menu', request: 'Put the theme switch inside the new gear menu in /config/morph/frontend/' + s.redo + '.', home_assistant: false }, { label: 'Use Morph’s own', request: 'Delete /config/morph/frontend/' + s.redo + '.', home_assistant: false }] }; }
      if (s.redo && Date.now() - s.at > 1500 && s.phase !== 'done') { s.phase = 'done'; s.say = 'Made the header change again on top of the new morph-panel.js.'; s.commit = 'c0de'; s.code = [s.redo]; s.reload = true; s.steps.push({ t: 'Changed Morph’s own ' + s.redo, tone: 'good' }); s.code_issue = { title: 'A header change', detail: 'brAIn changed Morph’s own ' + s.redo + '.' }; s.issue = 'asked'; F.state.code = []; F.state.activity = []; }
      if (s.makesSensor && Date.now() - s.at > 1500 && s.phase !== 'done') { s.phase = 'done'; s.say = 'Made sensor.hvac_delta and pointed the card at it.'; s.commit = 'c0ffe2'; s.house = ['sensor.hvac_delta (template sensor)']; s.shows = ['Changed the card “Fan” in Living room.']; }
      if (/history/i.test(s.text) && !s.makesSensor && Date.now() - s.at > 1500 && s.phase !== 'done') { s.phase = 'done'; s.say = 'Added the difference to the card, worked out in the card.'; s.commit = 'c0ffe1'; s.shows = ['Changed the card “Fan” in Living room.']; s.facts_filed = 2; s.question = { text: 'Keep a history of the supply/return difference?', options: [{ label: 'Calculate it in the card', request: 'Keep it in the card.', home_assistant: false }, { label: 'Make a Home Assistant sensor', request: 'Make a template sensor sensor.hvac_delta and use it.', home_assistant: true }] }; }
      if (Date.now() - s.at > 1500 && s.phase !== 'done') { s.phase = 'done'; s.say = 'Made the cans card wider and moved it to the top of the kitchen.'; s.saw = 'The Cans card, a narrow strip at the bottom of the Kitchen.'; s.commit = 'c0ffee'; s.reload = false; s.shows = ['Changed the card “Cans” in Kitchen.']; s.steps.push({ t: 'Editing dashboard.yaml', tone: '', brain: true }, { t: 'Changed dashboard.yaml', tone: 'good' }); if (s.issueAsk) { s.code_issue = { title: 'The light card cannot show two colours at once', detail: 'A split strip in the light card.' }; s.issue = 'asked'; } }
      return { ...s };
    }
    if (t === 'morph/shot') {
      if (!String(msg.png || '').startsWith('data:image/png;base64,')) throw new Error('Not a PNG.');
      window.__shots = (window.__shots || []).concat([msg.png]);
      return { shot: 'f'.repeat(31) + window.__shots.length, bytes: msg.png.length };
    }
    // A suspended connection refuses a send; the measure sets this to make one fail.
    if (t === 'morph/usage' && window.__usageFail > 0) { window.__usageFail -= 1; window.__ws.pop(); throw new Error('Connection lost'); }
    if (t === 'morph/usage' || t === 'morph/report' || t === 'morph/finding') return { ok: true };
    // brAIn's queue, answered the way its drain would: a reply is a turn,
    // brAIn's answer arrives a moment later in the case's thread.
    if (t === 'morph/case') {
      window.__caseReqs = (window.__caseReqs || []).concat([msg]);
      const c = (F.brain.cases || []).find((x) => x.id === msg.case);
      if (!c) return { ok: false, error: 'That case is gone.' };
      // A reply that also asks for a page change carries a tell on brAIn’s
      // turn; one that settles it ends the case and is said as it leaves.
      if (msg.action === 'reply' && /card|dashboard/i.test(msg.text)) setTimeout(() => { const at = Date.now() / 1000; F.brain.cases = F.brain.cases.filter((x) => x.id !== msg.case); F.brain.said = (F.brain.said || []).concat([{ case: msg.case, who: 'brain', text: 'Done — and I asked Morph to add it to the kitchen.', at, tell: { kind: 'dashboard', text: 'Add the garage freezer to the Kitchen section.' } }]); listeners.forEach((cb) => cb({ parts: ['brain'] })); }, 300);
      else if (msg.action === 'reply') setTimeout(() => { c.thread = (c.thread || []).concat([{ who: 'you', text: msg.text, at: Date.now() / 1000 }, { who: 'brain', text: 'Okay, I will leave it.', at: Date.now() / 1000 }]); listeners.forEach((cb) => cb({ parts: ['brain'] })); }, 300);
      if (['dismiss', 'todo', 'snooze'].includes(msg.action)) setTimeout(() => { F.brain.cases = F.brain.cases.filter((x) => x.id !== msg.case); listeners.forEach((cb) => cb({ parts: ['brain'] })); }, 200);
      return { ok: true };
    }
    if (t === 'morph/todo') { window.__todoReqs = (window.__todoReqs || []).concat([msg]); setTimeout(() => { F.brain.todo = (F.brain.todo || []).filter((x) => x.id !== msg.id); listeners.forEach((cb) => cb({ parts: ['brain'] })); }, 200); return { ok: true }; }
    if (t === 'morph/ask') {
      window.__asks = (window.__asks || []).concat([msg.text]);
      if (/remember/i.test(msg.text)) return { do: 'done', say: 'Remembered.' };
      if (/card|section|dashboard/i.test(msg.text)) return { do: 'tell_dashboard' };
      if (window.__askFallback) return { do: 'fallback' };
      return { do: 'conversation' };
    }
    // brAIn's personality file, as brAIn's Settings saves it; a test sets
    // window.__persona to change it (null: no file) between opens.
    if (t === 'morph/personality') {
      const p = window.__persona === undefined ? { name: 'Juniper', persona: 'Warm and brief.\\n\\nNever lectures.', growth: [{ date: '2026-08-01', text: 'Stopped saying good morning at noon.' }, { date: '2026-09-02', text: 'Learned the dog is called Biscuit.' }], updated_at: 1788300000 } : window.__persona;
      return { brain: window.__noBrain ? false : true, personality: p };
    }
    if (t === 'morph/yaml') return { text: 'title: Home\\n' };
    if (t === 'history/history_during_period') {
      const out = {}; (msg.entity_ids || []).forEach((e) => {
        const s = states[e]; const st = Date.parse(msg.start_time) / 1000;
        if (e.startsWith('climate.') && !msg.no_attributes) {
          // A thermostat's day: a setback overnight, cooling in runs.
          const tgt = (s && s.attributes.temperature) || 72;
          out[e] = Array.from({ length: 24 }, (_, i) => ({ s: s ? s.state : 'cool', lu: st + i * 3600, a: { temperature: i < 7 ? tgt + 2 : tgt, hvac_action: i % 3 === 0 ? 'cooling' : 'idle' } }));
          return;
        }
        out[e] = [{ s: s && s.state === 'on' ? 'off' : 'on', lu: st }, { s: 'on', lu: st + 3600 * 3 }, { s: 'off', lu: st + 3600 * 5 }, { s: s ? s.state : 'off', lu: st + 3600 * 7 }];
      }); return out;
    }
    if (t === 'recorder/statistics_during_period') {
      const step = msg.period === 'day' ? 86400000 : msg.period === 'hour' ? 3600000 : 300000; const out = {};
      (msg.statistic_ids || []).forEach((e) => { out[e] = series(e, Date.parse(msg.start_time), Date.parse(msg.end_time), step); }); return out;
    }
    if (t === 'logbook/get_events') return [{ when: Date.now() / 1000 - 3600, state: 'on', context_entity_id_name: 'Evening scene' }, { when: Date.now() / 1000 - 600, state: 'off', context_user_id: 'u' }];
    if (t === 'conversation/process') return { conversation_id: 'c1', response: { speech: { plain: { speech: 'Upstairs is warm because the attic is 96° and the Upstairs thermostat is holding at 73°.' } } } };
    if (t === 'call_service') return { response: { [msg.target.entity_id]: { forecast: [0, 1, 2, 3, 4].map((i) => ({ datetime: new Date(Date.now() + i * 86400000).toISOString(), temperature: 64 + i, templow: 52 + i, precipitation_probability: i === 2 ? 60 : 10 })) } } };
    return {};
  },
  connection: { subscribeMessage(cb) { listeners.push(cb); return Promise.resolve(() => {}); } },
};
window.loadCardHelpers = async () => ({ createCardElement(cfg) { const tag = String(cfg.type || ''); if (tag.startsWith('custom:') && customElements.get(tag.slice(7))) { const c = document.createElement(tag.slice(7)); c.setConfig(cfg); return c; } const el = document.createElement('div'); el.className = 'fake-ll'; el.style.cssText = 'padding:14px;border-radius:12px;background:#223;color:#cde;font:14px sans-serif'; el.textContent = 'Lovelace ' + cfg.type + ' · ' + (cfg.entity || ''); return el; } });
function push() { const h = { ...hass, states }; el.hass = h; }
// Home Assistant's order (ha-panel-custom.ts): import the module, create
// the element it names, set its properties, then put it in the page. The
// element is boot.js's shell; window.__panel is the panel inside it.
${o.shell ? `await import('${ORIGIN}/morph_static/${VERSION}/shell.js');
const el = document.createElement('brain-shell');` : `await import('${ORIGIN}/morph_static/${VERSION}/boot.js');
const el = document.createElement('morph-boot');`}
el.panel = { config: { version: '${VERSION}', cards_url: '/morph_cards' } };
el.narrow = ${o.narrow ? 'true' : 'false'};
el.hass = hass;
document.body.appendChild(el);
window.__shell = el;
${o.shell ? `window.__boot = async () => { for (let i = 0; i < 300 && !(el.shadowRoot.querySelector('morph-boot') && el.shadowRoot.querySelector('morph-boot').shadowRoot && el.shadowRoot.querySelector('morph-boot').shadowRoot.querySelector('morph-panel')); i++) await new Promise((r) => setTimeout(r, 20)); const b = el.shadowRoot.querySelector('morph-boot'); return b && b.shadowRoot ? b.shadowRoot.querySelector('morph-panel') : null; };
window.__panel = ${o.morph === false || o.noWaitMorph ? 'null' : 'await window.__boot()'};` : `await customElements.whenDefined('morph-panel');
while (!el.shadowRoot.querySelector('morph-panel')) await new Promise((r) => setTimeout(r, 10));
window.__panel = el.shadowRoot.querySelector('morph-panel');`}
window.__push = push;
</script></body></html>`;
}

// Morph's own theme setting (⚙ › Dashboard): 'dark', 'medium', 'light' or
// 'auto' (Home Assistant's dark mode).
function themed(st, theme) {
  if (theme) st.settings = { ...st.settings, theme };
  return st;
}

// The real brAIn page, as the add-on's server sends it (the version written
// in), with the measures' stubbed fetch put in front of app.js and the
// status poll carrying the switches the shell's page reads.
function realPanel(opts) {
  const o = opts || {};
  const html = readFileSync(path.join(PANEL, 'index.html'), 'utf8').replaceAll('{{VERSION}}', BRAIN_VERSION);
  const features = { morph: o.morph !== false, personality: true, name: 'Juniper', shell: true, learning_loop: true, development_loop: false };
  const extra = `<script>${panelStub(o.insights ? { insights: o.insights } : {})}
(() => { const inner = window.fetch; window.fetch = async (url, opts) => {
  // ⚙ › Dashboard's settings, kept the way Morph's service keeps them:
  // the header tabs a measure sets come back on the next read.
  const json = (b) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const dash = () => ({ theme: 'auto', hold_ms: 540, learning_hours: 24, tell_model: '', learn_model: '', fold_rooms: true, reduce_motion: false, header_tabs: window.__tabs || {} });
  if (String(url).includes('api/morph/state')) return json({ version: '1.0.0', settings: dash(), learning: {}, code: [], people: [] });
  if (String(url).includes('api/morph/request')) {
    const b = JSON.parse((opts && opts.body) || '{}');
    if (b.kind === 'settings') { const p = (b.payload && b.payload.patch) || {}; if (p.header_tabs) window.__tabs = p.header_tabs; return json({ ok: true, settings: dash() }); }
    if (b.kind === 'history') return json({ ok: true, log: [] });
    return json({ ok: true });
  }
  const r = await inner(url, opts);
  if (!String(url).includes('api/status')) return r;
  const body = await r.json();
  return new Response(JSON.stringify({ ...body, version: ${JSON.stringify(BRAIN_VERSION)}, features: ${JSON.stringify(features)} }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}; })();</script>`;
  return html.replace('<link rel="stylesheet"', `${extra}\n<link rel="stylesheet"`);
}

function framedPage() {
  return `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">
<header style="height:56px;background:#123">brAIn's bar</header>
<script>
window.__got = [];
const post = (b) => parent.postMessage({ type: 'brain-shell', ...b }, location.origin);
window.__post = post;
addEventListener('message', (ev) => { if (ev.source === parent && ev.data && ev.data.type === 'brain-shell') window.__got.push(ev.data); });
post({ ready: true }); post({ bars: { top: 56, bottom: 0 } });
</script></body></html>`;
}

export async function route(context, opts) {
  await context.route(`${ORIGIN}/**`, async (r) => {
    const url = new URL(r.request().url());
    if (url.pathname === '/' || url.pathname === '/index.html') return r.fulfill({ contentType: 'text/html', body: page(opts) });
    // brAIn's own page, framed by the shell: a stand-in that speaks the
    // shell's protocol (app.js's half), so the shell's own behaviour is
    // what is measured.
    if (url.pathname === '/api/hassio_ingress/abcdefghijkl/') return r.fulfill({ contentType: 'text/html', body: opts && opts.realFrame ? realPanel(opts) : framedPage() });
    if (opts && opts.realFrame && url.pathname.startsWith('/api/hassio_ingress/abcdefghijkl/')) {
      const rel = url.pathname.slice('/api/hassio_ingress/abcdefghijkl/'.length);
      const types = { css: 'text/css', js: 'text/javascript', svg: 'image/svg+xml', png: 'image/png' };
      const ext = rel.split('.').pop();
      if (!rel.includes('..') && types[ext]) {
        try { return r.fulfill({ contentType: types[ext], body: readFileSync(path.join(PANEL, rel)) }); } catch (e) { return r.fulfill({ status: 404, body: '' }); }
      }
      return r.fulfill({ status: 404, body: '' });
    }
    const m = url.pathname.match(/^\/morph_static\/[^/]+\/(?:s\/[0-9a-f]{12}\/)?(.+)$/);
    if (m && m[1] === 'boot.js') {
      // static.py writes the stamp and module list into boot.js, so the
      // fixture does too: the modules then load under s/<stamp>/, the path
      // a real page uses.
      const names = readdirSync(FRONTEND).filter((n) => n.endsWith('.js') && n !== 'boot.js').sort();
      const stamp = (opts && opts.stamp) || STAMP;
      const body = readFileSync(path.join(FRONTEND, 'boot.js'), 'utf8').replace("const STAMP = '';", `const STAMP = ${JSON.stringify(stamp)};`).replace('const MODULES = [];', `const MODULES = ${JSON.stringify(names)};`);
      return r.fulfill({ contentType: 'text/javascript', body });
    }
    if (m) {
      if (opts && opts.requests) opts.requests.push(url.pathname);
      if (opts && opts.moduleDelay) await new Promise((res) => setTimeout(res, opts.moduleDelay));
      // This house's copy of one of Morph's modules (static.py's rule):
      // served in place of Morph's own, except under shipped/.
      const own = (opts && opts.overrides) || {};
      if (!m[1].startsWith('shipped/') && own[m[1]] != null) return r.fulfill({ contentType: 'text/javascript', body: own[m[1]] });
      try { return r.fulfill({ contentType: 'text/javascript', body: readFileSync(path.join(FRONTEND, path.basename(m[1])), 'utf8') }); } catch (e) { return r.fulfill({ status: 404 }); }
    }
    // A house's own card code, written the way AGENTS.md's example was
    // before it guarded define(): loading a newer version throws.
    if (url.pathname.startsWith('/morph_cards/')) {
      const name = path.basename(url.pathname, '.js');
      return r.fulfill({ contentType: 'text/javascript', body: `class C extends HTMLElement { setConfig() {} set hass(h) {} }\ncustomElements.define(${JSON.stringify(name)}, C);\n` });
    }
    if (url.pathname.startsWith('/api/camera_proxy/')) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#2a3340"/><circle cx="160" cy="95" r="34" fill="#46566a"/></svg>`;
      return r.fulfill({ contentType: 'image/svg+xml', body: svg });
    }
    return r.fulfill({ status: 404, body: '' });
  });
  await context.route('https://fonts.googleapis.com/**', (r) => r.fulfill({ contentType: 'text/css', body: '' }));
}
