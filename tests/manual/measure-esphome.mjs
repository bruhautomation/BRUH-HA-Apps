// Render House → ESPHome against a real device list and drive the editor, so
// what a row offers and what the dialog shows are measured rather than read.
//
// It drives the panel's REAL renderer behind a stubbed fetch — the rule
// measure-activity and measure-todo follow: a copy of renderEsphome in this
// file would only ever agree with itself. It fails on:
//
//   * a device row with no name, no file name, or no Edit;
//   * Install offered while the dashboard is unreachable, or the status line
//     not saying WHY in words when it is (an empty list and an unreachable
//     dashboard look alike, and only the sentence tells them apart);
//   * the editor opening without the file's text, or the console not showing
//     a job's lines and its ending in words;
//   * the YAML box under 16px on touch — `#espText` is id-qualified and so
//     outranks the panel's text floor, which is the iOS zoom trap;
//   * any of the tab's own controls under the 44px floor on touch;
//   * the page scrolling sideways, or any page error.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const SHOTS = process.env.ESP_SHOTS || '';

const CASES = [
  { width: 390, touch: true },
  { width: 768, touch: false },
  { width: 1200, touch: false },
];
const MIN_TARGET = 44;

const YAML = `substitutions:
  name: porch-light
  friendly_name: Porch Light

esphome:
  name: \${name}
  friendly_name: \${friendly_name}

esp32:
  board: esp32dev
`;

const DEVICES = [
  { configuration: 'porch-light.yaml', name: 'porch-light',
    friendly_name: 'Porch Light', platform: 'esp32', board: 'esp32dev',
    comment: '', error: '', is_device: true, mtime: 1, size: 10,
    address: 'porch-light.local', deployed_version: '2026.8.0',
    current_version: '2026.9.0', update_available: true, online: true,
    loaded_integrations: ['api'], ha_device_id: 'd1', ha_name: 'Porch Light',
    area_id: 'porch', entity_count: 4, update_entity: 'update.porch_light_firmware',
    protected: false, job: null },
  { configuration: 'garage-door-controller-with-a-long-name.yaml',
    name: 'garage-door', friendly_name: '', platform: 'esp8266', board: 'd1_mini',
    comment: 'Ratgdo on the garage opener', error: '', is_device: true,
    mtime: 1, size: 10, address: '', deployed_version: '', current_version: '',
    update_available: false, online: false, loaded_integrations: [],
    ha_device_id: '', ha_name: '', area_id: '', entity_count: 0,
    update_entity: '', protected: true, job: null },
  { configuration: 'common.yaml', name: '', friendly_name: '', platform: '',
    board: '', comment: '', error: '', is_device: false, mtime: 1, size: 5,
    address: '', deployed_version: '', current_version: '',
    update_available: false, online: null, loaded_integrations: [],
    ha_device_id: '', ha_name: '', area_id: '', entity_count: 0,
    update_entity: '', protected: false, job: null },
];

const stub = (reachable) => `
window.__esp = {
  dir: '/config/esphome', dir_exists: true,
  dashboard: ${reachable
    ? "{ reachable: true, via: 'ingress', version: '2026.9.0', addon: { name: 'ESPHome Device Builder' } }"
    : "{ reachable: false, reason: 'brAIn could not reach an ESPHome dashboard: no ESPHome add-on is installed. Editing files still works.' }"},
  devices: ${JSON.stringify(DEVICES)},
  importable: [{ name: 'athom-plug', friendly_name: 'Athom Plug' }],
  ha_registry_ok: true, secret_keys: ['wifi_ssid', 'wifi_password'],
  platforms: [{ id: 'esp32', label: 'ESP32', board: 'esp32dev' }],
  jobs: [],
};
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body, status) => new Response(JSON.stringify(body), {
    status: status || 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/esphome/config/') && p.endsWith('/validate')) {
    return answer({ ok: true, job: { id: 'j1', kind: 'validate', label: 'Validate',
      configuration: 'porch-light.yaml', state: 'running', lines: ['INFO Reading configuration'],
      total: 1 } });
  }
  if (p.includes('api/esphome/job/j1')) {
    return answer({ ok: true, job: { id: 'j1', kind: 'validate', label: 'Validate',
      configuration: 'porch-light.yaml', state: 'succeeded', exit_code: 0,
      lines: ['INFO Configuration is valid!'], total: 2 } });
  }
  if (p.includes('api/esphome/config/')) {
    return answer({ ok: true, configuration: 'porch-light.yaml',
      content: ${JSON.stringify(YAML)}, mtime: 1, name: 'porch-light', error: '' });
  }
  if (p.includes('api/esphome')) return answer(window.__esp);
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth',
      auth_source: 'panel', auth_check: { state: 'ok', error: '' },
      model: 'default', settings: {}, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/settings')) return answer({});
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/findings')) return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const readList = (page) => page.evaluate(() => {
  const rows = [...document.querySelectorAll('#espList .espdev')];
  const size = (b) => ({ label: b.textContent.trim(), disabled: b.disabled,
    h: Math.round(b.getBoundingClientRect().height) });
  return {
    status: document.getElementById('espStatus').textContent,
    rows: rows.map((r) => ({
      name: (r.querySelector('.espdevname b') || {}).textContent || '',
      file: (r.querySelector('.espfile') || {}).textContent || '',
      badges: [...r.querySelectorAll('.espbadge')].map((b) => b.textContent),
      buttons: [...r.querySelectorAll('.espacts > .btn, .espmore > summary')].map(size),
      right: r.getBoundingClientRect().right,
    })),
    head: [...document.querySelectorAll('#viewEsphome .espactions .btn')].map(size),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  };
});

for (const { width, touch } of CASES) {
  for (const reachable of [true, false]) {
    const where = `${width}px ${reachable ? 'reachable' : 'unreachable'}`;
    const context = await browser.newContext({
      viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch });
    const page = await context.newPage();
    page.on('pageerror', (error) => note(where, `page error: ${error.message}`));
    await page.addInitScript(stub(reachable));
    await page.goto(`file://${path.join(PANEL, 'index.html')}`);
    await openView(page, 'esphome');
    await page.waitForSelector('#espList .espdev');
    const list = await readList(page);

    if (list.rows.length !== DEVICES.length) {
      note(where, `${list.rows.length} rows for ${DEVICES.length} files`);
    }
    for (const row of list.rows) {
      if (!row.name.trim() || !row.file.trim()) note(where, 'a row has no name or file');
      if (!row.buttons.some((b) => b.label === 'Edit')) note(where, `${row.file} has no Edit`);
      const install = row.buttons.find((b) => b.label === 'Install');
      if (install && !reachable && !install.disabled) {
        note(where, `${row.file} offers Install with no dashboard`);
      }
      if (row.right > list.viewport + 1) note(where, `${row.file} hangs off the page`);
      if (touch) {
        for (const b of row.buttons) {
          if (b.h < MIN_TARGET) note(where, `"${b.label}" is ${b.h}px on touch`);
        }
      }
    }
    if (!list.rows[0].badges.includes('Update available')) {
      note(where, 'a device behind the dashboard\'s version does not say so');
    }
    if (!list.rows.some((r) => r.badges.includes('Protected'))) {
      note(where, 'a protected device does not say so');
    }
    if (!reachable && !/could not reach/i.test(list.status)) {
      note(where, `status does not say the dashboard is unreachable: "${list.status}"`);
    }
    if (reachable && !/Connected/.test(list.status)) {
      note(where, `status does not say it is connected: "${list.status}"`);
    }
    if (touch) {
      for (const b of list.head) {
        if (b.h < MIN_TARGET) note(where, `"${b.label}" is ${b.h}px on touch`);
      }
    }
    if (list.docWidth > list.viewport + 1) {
      note(where, `the page scrolls sideways (${list.docWidth} > ${list.viewport})`);
    }
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/esp-list-${width}-${reachable}.png` });

    // The editor, and a job's console under it.
    if (reachable) {
      await page.click('#espList .espdev .espacts .btn');
      await page.waitForFunction(() => document.getElementById('espText').value.includes('esphome:'));
      const font = await page.evaluate(() =>
        parseFloat(getComputedStyle(document.getElementById('espText')).fontSize));
      if (touch && font < 16) note(where, `the YAML box is ${font}px on touch`);
      await page.click('#espValidate');
      await page.waitForFunction(() =>
        document.getElementById('espOut').textContent.includes('valid'), null, { timeout: 5000 })
        .catch(() => note(where, 'the console never showed the job finishing'));
      const con = await page.evaluate(() => ({
        title: document.getElementById('espConTitle').textContent,
        out: document.getElementById('espOut').textContent,
        stopHidden: document.getElementById('espStop').hidden,
        docWidth: document.documentElement.scrollWidth,
        buttons: [...document.querySelectorAll('.esprow .btn')].map((b) =>
          Math.round(b.getBoundingClientRect().height)),
      }));
      if (!/finished/.test(con.title)) note(where, `console title says "${con.title}"`);
      if (!con.out.includes('Reading configuration')) note(where, 'the first line was lost');
      if (!con.stopHidden) note(where, 'Stop is offered on a finished job');
      if (touch && con.buttons.some((h) => h < MIN_TARGET)) {
        note(where, `an editor button is under ${MIN_TARGET}px on touch`);
      }
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/esp-edit-${width}.png` });
    }
    await context.close();
  }
}

await browser.close();
if (failures.length) {
  console.error(`measure-esphome: ${failures.length} failure(s)`);
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log('measure-esphome: ok');
