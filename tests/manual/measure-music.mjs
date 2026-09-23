// Render House → Music Assistant against a real overview and press Remove,
// so what the tab offers is measured rather than read.
//
// It drives the panel's REAL renderer behind a stubbed fetch — the rule
// measure-esphome follows: a copy of renderMusic in this file would only
// ever agree with itself. It fails on:
//
//   * the status line not saying, in words, that Music Assistant cannot be
//     reached (an empty tab and an unreachable server look alike otherwise),
//     or not saying which sign-in is in use when it can;
//   * a stale player missing, carrying no reason, or with no Remove — the
//     one thing this tab exists to make possible;
//   * Remove sending anything but a dry run first, or removing without the
//     second, explicit request;
//   * a player row with no name, or playback controls offered on an
//     unavailable or protected player;
//   * a provider's last error not shown;
//   * any of the tab's controls under the 44px floor on touch;
//   * the page scrolling sideways, or any page error.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openView } from './tabs.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');
const SHOTS = process.env.MA_SHOTS || '';

const CASES = [
  { width: 390, touch: true },
  { width: 1200, touch: false },
];
const MIN_TARGET = 44;

const OVERVIEW = {
  ok: true,
  server: { reachable: true, via: 'entry', url: 'http://d5369777-music-assistant:8094',
    server_version: '2.9.0', name: 'Music Assistant', signed_in_as: 'Home Assistant Integration',
    role: 'service', admin: false },
  players: [
    { player_id: 'kitchen', name: 'Kitchen', provider: 'chromecast--abc',
      provider_name: 'Chromecast', available: true, enabled: true, powered: true,
      state: 'playing', volume: 30, muted: false, group_members: [],
      now_playing: { title: 'A Song With A Rather Long Title', artist: 'Band' }, model: 'Nest Audio' },
    { player_id: 'living-room-speaker-with-a-long-identifier', name: 'Living room',
      provider: 'airplay--1', provider_name: 'AirPlay', available: false, enabled: true,
      powered: null, state: 'idle', volume: null, group_members: [], now_playing: null, model: '' },
    { player_id: 'media_player.den', name: 'Den', provider: 'hass--1', provider_name: 'Home Assistant',
      available: true, enabled: true, powered: false, state: 'idle', volume: 10,
      group_members: [], now_playing: null, model: '', protected: true },
  ],
  stale_players: [
    { player_id: 'aircast-0', name: 'AirCast 0', provider: 'aircast--2', provider_name: 'aircast--2',
      kind: 'remembered', reason: 'Music Assistant remembers this player but has not seen it since — removing it forgets it for good' },
    { player_id: 'aircast-1', name: 'AirCast 1', provider: 'aircast--2', provider_name: 'aircast--2',
      kind: 'remembered', reason: 'Music Assistant remembers this player but has not seen it since — removing it forgets it for good' },
  ],
  providers: [
    { instance_id: 'sonos--9', domain: 'sonos', name: 'Sonos', type: 'player',
      available: false, enabled: true, last_error: 'no Sonos found on the network' },
    { instance_id: 'spotify--1', domain: 'spotify', name: 'Spotify', type: 'music',
      available: true, enabled: true, last_error: '' },
  ],
  errors: [],
};

const stub = (reachable) => `
window.__ma = ${reachable ? JSON.stringify(OVERVIEW)
    : JSON.stringify({ ok: true, server: { reachable: false,
      reason: 'brAIn could not reach Music Assistant: Home Assistant has no Music Assistant integration and there is no Supervisor to ask.' },
      players: [], stale_players: [], providers: [] })};
window.__removes = [];
window.confirm = () => true;
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body, status) => new Response(JSON.stringify(body), {
    status: status || 200, headers: { 'Content-Type': 'application/json' } });
  if (p.includes('api/music-assistant/players/remove')) {
    const body = JSON.parse((opts && opts.body) || '{}');
    window.__removes.push(body);
    if (body.dry_run) {
      return answer({ ok: true, dry_run: true, candidates: body.player_ids.map((id) =>
        ({ player_id: id, name: id, kind: 'remembered', reason: 'gone' })) });
    }
    return answer({ ok: true, dry_run: false, removed: body.player_ids,
      held_by_provider: [], failed: [] });
  }
  if (p.includes('api/music-assistant')) return answer(window.__ma);
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

const read = (page) => page.evaluate(() => {
  const size = (b) => ({ label: b.textContent.trim(), disabled: b.disabled,
    h: Math.round(b.getBoundingClientRect().height) });
  const cards = (sel) => [...document.querySelectorAll(sel)].map((r) => ({
    name: (r.querySelector('.espdevname b') || {}).textContent || '',
    text: r.textContent,
    badges: [...r.querySelectorAll('.espbadge')].map((b) => b.textContent),
    buttons: [...r.querySelectorAll('.espacts > .btn, .espmore > summary, .marow .btn, .espdevhead > .btn')].map(size),
    right: r.getBoundingClientRect().right,
  }));
  return {
    status: document.getElementById('maStatus').textContent,
    stale: cards('#maStale .espdev'),
    staleRows: [...document.querySelectorAll('#maStale .marow')].map((r) => r.textContent),
    players: cards('#maPlayers .espdev'),
    providers: cards('#maProviders .espdev'),
    head: [...document.querySelectorAll('#viewMusic .espactions .btn')].map(size),
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
    await openView(page, 'music');
    await page.waitForFunction(() =>
      !/Looking for/.test(document.getElementById('maStatus').textContent));
    const v = await read(page);

    if (!reachable) {
      if (!/could not reach/i.test(v.status)) note(where, `status does not say why: "${v.status}"`);
      if (v.players.length || v.stale.length) note(where, 'rows drawn for a server nobody reached');
    } else {
      if (!/Connected/.test(v.status) || !/music_assistant_token/.test(v.status)) {
        note(where, `status does not say who brAIn is signed in as and what that allows: "${v.status}"`);
      }
      if (v.staleRows.length !== OVERVIEW.stale_players.length) {
        note(where, `${v.staleRows.length} stale rows for ${OVERVIEW.stale_players.length}`);
      }
      for (const r of v.staleRows) if (!/remembers/.test(r)) note(where, `stale row with no reason: ${r}`);
      const staleButtons = (v.stale[0] || { buttons: [] }).buttons;
      if (!staleButtons.some((b) => /Remove all/.test(b.label))) note(where, 'no Remove all');
      if (staleButtons.filter((b) => b.label === 'Remove').length !== OVERVIEW.stale_players.length) {
        note(where, 'a stale player has no Remove');
      }
      if (v.players.length !== OVERVIEW.players.length) note(where, `${v.players.length} player rows`);
      for (const p of v.players) if (!p.name.trim()) note(where, 'a player row has no name');
      const gone = v.players.find((p) => p.name === 'Living room');
      if (!gone || !gone.badges.includes('Unavailable')) note(where, 'an unavailable player does not say so');
      if (gone && gone.buttons.some((b) => /Pause|Play|Next/.test(b.label) && !b.disabled)) {
        note(where, 'playback offered on an unavailable player');
      }
      const den = v.players.find((p) => p.name === 'Den');
      if (!den || !den.badges.includes('Protected')) note(where, 'a protected player does not say so');
      if (den && den.buttons.some((b) => /Play|Next|Turn/.test(b.label) && !b.disabled)) {
        note(where, 'controls offered on a protected player');
      }
      if (!v.providers.some((p) => p.text.includes('no Sonos found'))) note(where, 'a provider error is not shown');
      if (touch) {
        for (const c of [...v.stale, ...v.players, ...v.providers]) {
          for (const b of c.buttons) if (b.h < MIN_TARGET) note(where, `"${b.label}" is ${b.h}px on touch`);
        }
      }
      for (const c of [...v.stale, ...v.players, ...v.providers]) {
        if (c.right > v.viewport + 1) note(where, `"${c.name}" hangs off the page`);
      }

      // Remove: a dry run first, then the real one, never the real one alone.
      await page.click('#maStale .marow .btn');
      await page.waitForFunction(() => window.__removes.length >= 2, null, { timeout: 5000 })
        .catch(() => note(where, 'Remove never sent its second request'));
      const sent = await page.evaluate(() => window.__removes);
      if (!sent[0] || sent[0].dry_run !== true) note(where, 'Remove did not start with a dry run');
      if (!sent[1] || sent[1].dry_run !== false) note(where, 'Remove did not follow with the real run');
      if (sent[1] && JSON.stringify(sent[1].player_ids) !== '["aircast-0"]') {
        note(where, `Remove sent ${JSON.stringify(sent[1].player_ids)}`);
      }
    }
    if (touch) {
      for (const b of v.head) if (b.h < MIN_TARGET) note(where, `"${b.label}" is ${b.h}px on touch`);
    }
    if (v.docWidth > v.viewport + 1) note(where, `the page scrolls sideways (${v.docWidth} > ${v.viewport})`);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/ma-${width}-${reachable}.png`, fullPage: true });
    await context.close();
  }
}

await browser.close();
if (failures.length) {
  console.error(`measure-music: ${failures.length} failure(s)`);
  for (const f of failures) console.error('  ' + f);
  process.exit(1);
}
console.log('measure-music: ok');
