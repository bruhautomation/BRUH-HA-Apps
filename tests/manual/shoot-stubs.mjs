/* API stubs for tests/manual/shoot-all.mjs: the apps that are served as static
 * files (BRUH Minecraft, Bambu Studio, BRUH Browser) have no demo server, so the
 * shooter answers their /api calls from the data below. Shapes were taken from
 * the real servers; nothing here is a contract, only enough to fill every screen.
 */

// ---- BRUH Minecraft
const now = Math.floor(Date.now() / 1000);
const props = { 'level-name': 'world', motd: 'The family server', gamemode: 'survival', 'force-gamemode': 'false', difficulty: 'normal', 'max-players': '10', pvp: 'true', hardcore: 'false', 'online-mode': 'true', 'white-list': 'true', 'view-distance': '10', 'simulation-distance': '8', 'level-type': 'minecraft:normal', 'level-seed': '-4172144997902289642', 'allow-flight': 'false', 'enable-command-block': 'false', 'server-port': '25565', 'rcon.port': '25575', 'spawn-protection': '16', 'enable-rcon': 'true' };
export const MC = {
  'api/status': { running: true, setup_required: false, crash: null, memory_warning: null, state: { server_type: 'paper', memory_mb: 4096, max_players: 10 }, server_meta: { version: '1.21.4' }, stats: { reachable: true, version: '1.21.4', uptime_seconds: 93784, tps_1m: 20.0, tps_5m: 19.9, tps_15m: 19.8, latency_ms: 3, online: 2, max_players: 10, players: ['Steve_builds', 'AlexTheMiner'] } },
  'api/server/software': { server_type: 'paper', version: '1.21.4', build: 232, checked: true, bedrock_support: true, version_option: 'LATEST', components: [{ title: 'Geyser', version: '2.6.1', note: 'Bedrock players', updated_at: now - 86400 }, { title: 'Floodgate', version: '2.2.4', note: 'Bedrock sign-in', updated_at: now - 86400 }, { title: 'ViaVersion', version: '5.2.1', note: 'newer clients', updated_at: now - 86400 }] },
  'api/companion': { headline: { code: 'ok', show: true, text: 'Vesper is listening. Two of the family are in the game.' }, identity: { name: 'Vesper', active: true, by: 'brAIn', model: 'sonnet' }, online: ['Steve_builds', 'AlexTheMiner'], zones: [{ name: 'Our house', x: 120, z: -48, radius: 24, dimension: 'minecraft:overworld', protect: true }, { name: 'The farm', x: 210, z: 12, radius: 16, dimension: 'minecraft:overworld', protect: false }],
    actions: [{ id: 'a1', t: now - 600, text: 'Built a small bridge over the river', status: 'done', undoable: true }, { id: 'a2', t: now - 4000, text: 'Planted six oak saplings by the farm', status: 'done', undo_note: 'undone', undoable: false }],
    questions: [{ person: 'Alex', text: 'What should we build next?', options: [{ label: 'Castle' }, { label: 'Farm' }], answer: 'Castle', status: 'answered' }, { person: 'Steve', text: 'Is it bedtime?', options: [{ label: 'Yes' }, { label: 'No' }], status: 'expired' }],
    said: [{ t: now - 500, name: 'Vesper', to: ['Steve_builds'], by: 'Dad', text: 'Dinner is in ten minutes, find a safe spot to stop.' }] },
  'api/world': { listening: { ok: true }, players: [{ name: 'Steve_builds', x: 118, z: -40, dimension: 'minecraft:overworld' }] },
  'api/players': { known: [{ name: 'Steve_builds', online: true, op: true, whitelisted: true }, { name: 'AlexTheMiner', online: true, whitelisted: true }, { name: 'GrandmaCrafts', whitelisted: true }, { name: 'xX_Griefer_Xx', banned: true }] },
  'api/properties': { properties: props, editable: Object.keys(props).filter((k) => !/port|rcon/.test(k)), types: { 'max-players': 'int', 'view-distance': 'int', 'simulation-distance': 'int', pvp: 'bool', hardcore: 'bool', 'online-mode': 'bool', 'white-list': 'bool', 'force-gamemode': 'bool', 'allow-flight': 'bool', 'enable-command-block': 'bool', 'spawn-protection': 'int' }, enums: { gamemode: ['survival', 'creative', 'adventure', 'spectator'], difficulty: ['peaceful', 'easy', 'normal', 'hard'] }, int_ranges: { 'view-distance': [2, 32], 'simulation-distance': [2, 32] }, world_gen_only: ['level-seed', 'level-type'] },
  'api/worlds': { active: 'world', worlds: [{ name: 'world', active: true, size_bytes: 734003200, settings: { gamemode: 'survival', difficulty: 'normal', 'level-type': 'minecraft:normal', 'white-list': 'true' } }, { name: 'creative-flat', size_bytes: 52428800, settings: { gamemode: 'creative', difficulty: 'peaceful', 'level-type': 'minecraft:flat' } }, { name: 'skyblock', size_bytes: 12428800, settings: {}, curated: { id: 'skyblock', name: 'SkyBlock', version: '2.1' } }] },
  'api/curated-worlds': { install: { status: 'idle' }, worlds: [{ id: 'skyblock', name: 'SkyBlock', version: '2.1', minecraft_version: '1.21.4', server_type: 'paper', size_estimate_mb: 40, tagline: 'One tree, one island.', description: 'The classic survival challenge on a floating island with limited resources.', installed_as: 'skyblock' }, { id: 'hermit', name: 'Hermit Hills', version: '1.0', minecraft_version: '1.21.4', server_type: 'paper', size_estimate_mb: 2048, tagline: 'A hand-built adventure map.', description: 'Rolling hills, twelve villages and a hidden stronghold. Made for two to six players.', notes: 'Needs 4 GB of memory.', homepage: 'https://example.org/hermit-hills' }] },
  'api/backups': { git: [{ sha: 'aaa1', ts: now - 1200, kind: 'scheduled', players: 2 }, { sha: 'aaa2', ts: now - 2400, kind: 'scheduled', players: 2 }, { sha: 'aaa3', ts: now - 9000, kind: 'manual', players: 0 }, { sha: 'aaa4', ts: now - 20000, kind: 'before a world change', players: 0 }, { sha: 'aaa5', ts: now - 100000, kind: 'scheduled', players: 1 }, { sha: 'aaa6', ts: now - 190000, kind: 'scheduled', players: 0 }], archives: [{ name: 'world-2026-11-10.tar.gz', ts: now - 600000, size: 312345678 }, { name: 'world-2026-11-03.tar.gz', ts: now - 1200000, size: 301345678 }] },
  'api/addons': { server_type: 'paper', game_version: '1.21.4', kinds: [{ kind: 'plugin', label: 'Plugins', reach: 'Everyone on the server gets these.' }, { kind: 'datapack', label: 'Data packs', reach: 'Everyone gets these.' }, { kind: 'resourcepack', label: 'Resource packs', reach: 'Java players get these.' }], world: { running: true, restart_needed: true, changes: [{ action: 'added', title: 'Simple Voice Chat' }], items: [{ id: 'p1', kind: 'plugin', title: 'EssentialsX', version: '2.21.0', source: 'browser', status: 'active', status_text: 'Working', file: 'EssentialsX.jar', updatable: true }, { id: 'p2', kind: 'plugin', title: 'Simple Voice Chat', version: '2.5.26', source: 'browser', status: 'restart', status_text: 'Starts after a restart', file: 'voicechat.jar' }, { id: 'p3', kind: 'plugin', title: 'LuckPerms', version: '5.4.145', source: 'manual', status: 'active', status_text: 'Working', file: 'LuckPerms.jar', required_by: 'EssentialsX' }, { id: 'd1', kind: 'datapack', title: 'Terralith', version: '2.5.8', source: 'browser', status: 'active', status_text: 'Working', file: 'Terralith.zip' }, { id: 'r1', kind: 'resourcepack', title: 'Faithful 32x', version: '1.21', source: 'manual', status: 'unused', status_text: 'Not used', file: 'Faithful.zip' }] } },
  'api/addons/search': { kind: 'all', has_more: true, next_offset: 6, hits: [
    ['Chunky', 'plugin', 'Plugin', 'pop4959', 9400000, 'Pre-generates chunks, quickly and efficiently.'], ['WorldEdit', 'plugin', 'Plugin', 'sk89q', 12000000, 'An in-game voxel map editor. Build bigger things more quickly and fix griefing with a few commands, without a single mod on the player side.'], ['EssentialsX', 'plugin', 'Plugin', 'EssentialsX', 3100000, 'The essential plugin suite for Minecraft servers.'], ['Terralith', 'datapack', 'Data pack', 'Starmute', 21000000, 'Explore almost 100 brand new biomes, using just vanilla blocks.'], ['Incendium', 'datapack', 'Data pack', 'Starmute', 4200000, 'A complete nether overhaul.'], ['Faithful 32x', 'resourcepack', 'Resource pack', 'Faithful', 800000, 'The original, at double the resolution.'],
  ].map(([title, kind, kind_label, author, downloads, description], i) => ({ id: i === 2 ? 'p1' : 'h' + i, title, kind, kind_label, author, downloads, description })) },
  'api/changelog': { releases: [{ version: '2.9.0', date: '2026-11-10', html: '<ul><li>Add-on browser.</li></ul>' }] },
  'api/recommend': { error: 'not available' },
};

// ---- BRUH Bambu Studio
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
export const PANEL = new URL('../../bruh-bambu-studio/panel/', import.meta.url).pathname;
export const FRAME = Buffer.from('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', 'base64');
export const PICTURE = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABOUlEQVR4nO2byxHCMAxEDWXQDHVQIXXQDG3ASZcMjPWzVp7sOyvWar1ODknGIIQQQshZuVQ3vD/fn1nN63Er07W8kWbgGSsNWbZwxuBHVhiRvuCKwY9kGnHNWmiMmuGz+6Q4WTX4L6JpCCcAOXxG/5AB6OGFiA63AV2GF7x6XAZ0G17w6Ep9CuyI2YCuuy9Y9ZkM6D68YNHJI6At3GX3Ba1eJkBTtNvuCxrdTABaABoaMCvY9fwLM/1MAFoAGhqAFoCGBqAFoKEBaAFopgZUvqhcwUw/E4AWgIYGaIp2vQ9odDMB2sLdUqDVywRYindJgUWnOQHdTbDq4xHwXNQ1BR5d7gR0M8GrJ3QEupgQ0RG+B6BNiPZPFV/5DiHL+NSnQFUaMvvwW+HsBY+c9mvxf3T7X4AQQgg5MV8oP3RaaaB+6QAAAABJRU5ErkJggg==', 'base64');
export const OPTIONS = JSON.parse(execFileSync('python3', ['-c',
  'import json,sys; sys.path.insert(0, sys.argv[1]); from design import options; '
  + 'print(json.dumps({"ok": True, **options.catalog()}))', PANEL]).toString());

export const A1 = { id: 'a1', name: 'Workshop A1', model: 'A1', host: '192.168.1.60', serial: 'A1SERIAL',
  online: true, state: 'running', printing: true, stage: 'Changing filament', progress: 42,
  remaining_min: 95, layer: 84, total_layers: 200, file: 'Gear rotor', speed: 'standard',
  nozzle_c: 219.6, nozzle_target_c: 220, bed_c: 60.2, bed_target_c: 60, chamber_c: null,
  chamber_light: true, nozzle_diameter: '0.4', wifi: '-48dBm',
  fans: { part: 100, aux: 40, chamber: null, heatbreak: 100 },
  ams: [{ slot: 0, type: 'PLA', name: 'Bambu PLA Basic', colour: '#FFFFFF', remaining: 80 },
    { slot: 1, type: 'PLA', name: 'Bambu PLA Matte', colour: '#18C241', remaining: 35 },
    { slot: 2, type: 'PETG', name: null, colour: '#202020', remaining: null },
    { slot: 3, type: 'PLA', name: null, colour: '#E0352B', remaining: 10 }],
  ams_units: [{ id: 0, humidity: 4, temp_c: 27 }], active_tray: 1,
  external_spool: { slot: 'external', type: 'TPU', colour: '#FFA500', remaining: null },
  hms: ['0700_2000_0002_0001'], hms_count: 1, error_code: null,
  camera: { kind: 'jpeg', streaming: true, frame_age_s: 0.4, error: '' },
  job_picture: 'api/thumb?path=sliced%2Frotor.gcode.3mf', connection_error: '',
  failure_detection: { enabled: true, mode: 'pause', sensitivity: 'medium', light: true, plate_watch: true,
    status: 'failure', sentence: 'The print failed and was paused.', view: 'ok',
    brain: { state: 'ok', sentence: 'ok' }, plate: { state: 'printing', why: '' }, print_id: '68f1a2b3',
    alert: { id: '68f1a2b3-1', level: 'failure', problem: 'spaghetti', open: true, paused: true, check: 3,
      summary: 'Spaghetti is building up behind the left part.', confidence: 0.91, at: Date.now() / 1000 - 90,
      image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
    last: { n: 3, layer: 84, decision: 'failure', summary: 'Spaghetti is building up behind the left part.',
      confidence: 0.91, at: Date.now() / 1000 - 90, image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
    next: { layer: 120, kind: 'bridge', reason: 'Bridges start at layer 118.' },
    expected_url: 'api/watch/image?printer=a1&name=68f1a2b3%2Fexpected.png',
    plan: { source: 'gcode', total_layers: 200, checkpoints: [
      { layer: 2, kind: 'first_layer', reason: 'The first layer is down.', state: 'done', decision: 'ok' },
      { layer: 9, kind: 'early', reason: 'A couple of millimetres up.', state: 'done', decision: 'ok' },
      { layer: 84, kind: 'colour', reason: 'Filament changes at layer 83.', state: 'done', decision: 'failure' },
      { layer: 120, kind: 'bridge', reason: 'Bridges start at layer 118.', state: 'planned' },
      { layer: 200, kind: 'last', reason: 'The last layers.', state: 'planned' }] },
    looks: { used: 3, budget: 8, checks: 3 }, ignored: [] } };
export const X1 = { id: 'x1', name: 'X1C', model: 'X1C', host: '192.168.1.61', serial: 'X1SERIAL',
  online: true, state: 'finish', printing: false, progress: 100, file: 'Benchy', speed: 'standard',
  nozzle_c: 32, bed_c: 30, chamber_c: 28, chamber_light: false, ams: [], ams_units: [],
  hms: [], camera: { kind: 'disabled', streaming: false, error: '' }, connection_error: '',
  failure_detection: { enabled: false, mode: 'pause', sensitivity: 'medium', light: true, plate_watch: true,
    status: 'off', sentence: 'Print failure detection is off.', view: 'unknown', plate: { state: 'unknown' },
    alert: null, last: null, next: null, plan: { checkpoints: [] }, looks: { used: 0, budget: 8 } } };
export const STATE = { ok: true, version: 'dev', printers: [A1, X1], jobs: [],
  studio: { installed: true, running: false, wanted: false, install: {} },
  ha: { reason: 'not_loaded', restart_needed: true, deployed: '0.2.0', running: null,
    lovelace_card: true, morph_installed: true, morph_card: true } };
export const STORAGE = { ok: true, printer: 'Workshop A1', files: [
  { name: 'rotor.gcode.3mf', dir: false, size: 2.4e6, date: 'Oct 20 10:02', mtime: 1760954520, printable: true,
    picture: 'api/printer/thumb?printer=a1&name=rotor.gcode.3mf&size=2400000' },
  { name: 'plate.gcode', dir: false, size: 8e5, date: 'Oct 19 09:00', mtime: 1760864400, printable: true, picture: null },
  { name: 'timelapse', dir: true, size: 0 }] };
export const FILES = { ok: true, root: '/share/bambu', files: [
  { path: 'imports/rotor.stl', name: 'rotor.stl', size: 3e6, modified: 1760000000, sliced: false, project: false }] };

export const HISTORY = { ok: true, checks: [
  { n: 3, layer: 84, decision: 'failure', summary: 'Spaghetti is building up behind the left part.', confidence: 0.91,
    why: 'Filament changes at layer 83.', at: Date.now() / 1000 - 90, expected: true,
    image_url: 'api/watch/image?printer=a1&name=68f1a2b3%2F3.jpg' },
  { n: 1, layer: 2, decision: 'ok', summary: 'The first layer is down evenly.', confidence: 0.88,
    why: 'The first layer is down.', at: Date.now() / 1000 - 4000, image_url: null }], alerts: [], errors: [] };
export function box(x0, y0, z0, x1, y1, z1) {
  const v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
    [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
  const faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]];
  return `solid b\n${faces.map((f) => `facet normal 0 0 0\nouter loop\n${
    f.map((i) => `vertex ${v[i].join(' ')}`).join('\n')}\nendloop\nendfacet`).join('\n')}\nendsolid b\n`;
}

export const PART = {
  id: 'box-a1b2c3', name: 'Two-colour box', state: 'idle', updated: 1, current: 1,
  print_settings: { colour: 'white', material: 'PLA' },
  messages: [{ role: 'user', text: 'A white box with a red lid' },
    { role: 'assistant', text: 'Here it is: **two bodies**, the lid in `red`.\n\n- Base: 2 walls\n- Lid: 15 % infill\n\n<b>not markup</b>', version: 1 }],
  versions: [{ n: 0, ok: true, summary: 'A first try without the lid', size_mm: [40, 30, 30],
    files: { '3mf': 'box0.3mf', step: 'box0.step', stl: 'box0.stl', bodies: { Base: 'bodies/Base.stl' } } },
  { n: 1, ok: true, summary: 'Added a press-fit lid with a 0.2 mm clearance and a finger notch on the front edge',
    size_mm: [40, 30, 36], grams: 14,
    warnings: ['The lid\'s notch is 0.8 mm thick, under two perimeters.', 'The base has a 52° overhang under the lip.'],
    dims: { wall: '2 mm', clearance: '0.2 mm', notch: '8 × 3 mm', lid: '5 mm' },
    colors: { Base: '#F4F4F2', Lid: 'red' },
    files: { '3mf': 'box.3mf', step: 'box.step', stl: 'box.stl',
      bodies: { Base: 'bodies/Base.stl', Lid: 'bodies/Lid.stl' } } }],
};
export const STL = { 'bodies/Base.stl': box(0, 0, 0, 40, 30, 30), 'bodies/Lid.stl': box(0, 0, 31, 40, 30, 36) };

export function bambuApi() {

  const now = Date.now() / 1000;
  const FL = { ok: true, root: '/share/bambu', files: [
    { path: 'imports/rotor.stl', name: 'rotor.stl', size: 3e6, modified: now - 100, sliced: false, project: false },
    { path: 'sliced/rotor.gcode.3mf', name: 'rotor.gcode.3mf', size: 2.4e6, modified: now - 500, sliced: true, project: false,
      seconds: 5700, grams: 38, filament_use: [{ type: 'PLA', colour: '#FFFFFF', grams: 30 }, { type: 'PLA', colour: '#18C241', grams: 8 }] },
    { path: 'imports/3D Benchy/3dbenchy.3mf', name: '3dbenchy.3mf', size: 11e6, modified: now - 900, sliced: false, project: true, plates: [1, 2, 3] },
    { path: 'designs/box-a1b2c3/v1/box.3mf', name: 'Two-colour box.3mf', size: 2e5, modified: now - 2000, sliced: false, project: false, design: 'box-a1b2c3', version: 1 },
    { path: 'imports/A very long folder name for a download/Cable management clip with a long descriptive name v3 (final).stl', name: 'Cable management clip with a long descriptive name v3 (final).stl', size: 4e5, modified: now - 4000, sliced: false, project: false },
  ] };
  const ST = { ...STATE, jobs: [
    { id: 'j1', kind: 'import', state: 'running', url: 'https://www.printables.com/model/3161', phase: 'downloading', progress: 40 },
    { id: 'j2', kind: 'slice', state: 'failed', file: 'rotor.stl', error: 'The slicer said the model is outside the plate.' }] };
  const API = {
    'api/state': ST, 'api/print/options': OPTIONS, 'api/printer/storage': STORAGE, 'api/files': FL,
    'api/design/status': { ok: true, brain: { state: 'ok' }, cad: true, viewer: true },
    'api/design/parts': { ok: true, parts: [
      { id: PART.id, name: PART.name, versions: 1, current: 1, state: 'idle', updated: 1 },
      { id: 'hook-1', name: 'Wall hook for headphones', versions: 3, current: 3, state: 'idle', updated: 1 },
      { id: 'brk-2', name: 'Bracket', versions: 0, current: 0, state: 'working', updated: 1 }] },
    [`api/design/parts/${PART.id}`]: { ok: true, part: PART },
    [`api/design/parts/${PART.id}/plan`]: { ok: true, printer: 'Workshop A1', settings: PART.print_settings,
      trays: A1.ams, recommended_slot: 0, machine: 'Bambu Lab A1 0.4 nozzle', process: '0.20mm Standard @BBL A1', filament: 'Bambu PLA Basic @BBL A1',
      bodies: [{ name: 'Base', colour: '#F4F4F2', recommended_slot: 0 }, { name: 'Lid', colour: 'red', recommended_slot: 3 }] },
    'api/watch': HISTORY, 'api/watch/targets': { ok: true, targets: ['notify.mobile_app_pixel'] },
    'api/printers': { ok: true, printers: ST.printers, models: ['A1', 'X1C', 'P1S'] },
    'api/settings': { ok: true, preferences: { design_model: 'default', look_model: 'haiku', design_notes: 'Walls 2 mm.', print_notes: '' },
      models: [{ value: 'default', label: "brAIn's choice" }, { value: 'haiku', label: 'Haiku' }], notes_max: 4000, design_brief: 'You are designing a part for FDM printing…' },
  };
  return API;
}

// ---- BRUH Browser
export function browserVariants() {
  const now = Date.now() / 1000;
  const steps = (st) => [
    { n: 1, title: 'Install the Claude extension', status: st[0], detail: 'The Claude extension is installed in this Chrome.' },
    { n: 2, title: 'Sign the extension in to claude.ai', status: st[1], detail: 'The extension has not said who is signed in yet.' },
    { n: 3, title: 'Sign Claude Code in', status: st[2], detail: 'Claude Code is not signed in.' },
    { n: 4, title: 'Let it act without asking', status: st[3], detail: 'Not proved yet: the Test shows whether the extension still asks.' },
    { n: 5, title: 'Test', status: st[4], detail: 'Not run yet.' }];
  const cart = { store: 'Walmart', currency: 'USD', delivery: 'Tomorrow, 8–9 am', total: 64.37,
    items: [{ name: 'Oat milk, unsweetened, 64 fl oz', quantity: 2, price: 7.96 }, { name: 'Bananas, bunch', quantity: 1, price: 1.62 },
      { name: 'Great Value large white eggs, 18 count', quantity: 1, price: 4.12 }, { name: 'Sourdough loaf', quantity: 1, price: 5.48 }],
    fees: [{ name: 'Delivery', amount: 7.95 }, { name: 'Tax', amount: 3.24 }], substitutions: ['Oatly → Planet Oat'], left_out: ['Blueberries (out of stock)'] };
  const history = [
    { id: 't9', state: 'done', prompt: 'Add my usual groceries plus oat milk to the cart at Walmart', created_at: now - 600, cart },
    { id: 't8', state: 'failed', prompt: 'Find the opening hours of the municipal recycling centre and say whether it is open on Sunday', created_at: now - 7200 },
    { id: 't7', state: 'stopped', prompt: 'Look at my old Walmart orders and learn what I usually buy', created_at: now - 90000 },
    { id: 't6', state: 'done', prompt: 'Setup test', created_at: now - 190000, order_placed: true, cart: { total: 12.5, currency: 'USD' } }];
  const browsers = { native: false, own_device: 'd1', default: 'own', listed_at: now, browsers: [
    { label: 'Chrome on homeassistant', name: 'homeassistant', osPlatform: 'Linux', own: true, default: true, deviceId: 'd1' },
    { label: 'Chrome on MacBook Pro', name: 'Work', osPlatform: 'macOS', own: false, default: false, deviceId: 'd2' }] };
  const profiles = [{ id: 'walmart', store: 'Walmart', updated_at: now - 4000,
    items: [{ key: 'a', name: 'Oat milk', variant: 'Planet Oat, unsweetened', quantity: 2, every: 7, last_bought: '2026-11-10' },
      { key: 'b', name: 'Bananas', quantity: 1, every: 'weekly' }, { key: 'c', name: 'Great Value large white eggs, 18 count', variant: '', quantity: 1 }],
    brands: ['Planet Oat', 'Great Value'], avoid: ['Anything with peanuts'] }];
  const base = { ok: true, approval_window_minutes: 30, chrome: { running: true, sandbox_note: '', restarts: 0, terminal_open: false } };
  const VARIANTS = {
    ready: { ...base, ready: true, setup: steps(['done', 'done', 'done', 'done', 'done']), browsers, profiles, history,
      current: { id: 't9', state: 'done', prompt: 'Add my usual groceries plus oat milk to the cart at Walmart', kind: 'errand', source: 'brAIn', browser_label: 'this app\'s Chrome',
        created_at: now - 600, finished_at: now - 300, steps: 41, answer: 'The cart is ready. Blueberries were out of stock and I swapped Oatly for Planet Oat.', cart } },
    setup: { ...base, ready: false, chrome: { running: true, sandbox_note: 'Chrome runs without its own sandbox here; the add-on\'s AppArmor profile confines it instead.', restarts: 0, terminal_open: false },
      setup: steps(['done', 'not_yet', 'not_yet', 'unknown', 'not_yet']), browsers: { native: true, browsers: [], default: 'own' }, profiles: [], history: [], current: null },
    asking: { ...base, ready: true, setup: steps(['done', 'done', 'done', 'done', 'done']), browsers, profiles, history,
      current: { id: 't10', state: 'needs_you', prompt: 'Order the usual from Walmart for delivery tomorrow morning', kind: 'errand', source: 'brAIn', created_at: now - 120, steps: 17,
        question: { kind: 'choice', text: 'Blueberries are out of stock. Which should I add instead?', money: true, options: ['Driscoll\'s raspberries, 6 oz — $3.98', 'Frozen blueberries, 16 oz — $2.74', 'Leave them out'] } } },
    running: { ...base, ready: true, setup: steps(['done', 'done', 'done', 'done', 'done']), browsers, profiles, history,
      current: { id: 't11', state: 'running', prompt: 'Find the cheapest 1 kg spool of white PETG', kind: 'errand', source: 'brAIn', created_at: now - 20, steps: 4, progress: 'Reading the search results' } },
  };
  return VARIANTS;
}
