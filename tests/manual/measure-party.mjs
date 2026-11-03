// Measure BRight's Party tab on a phone: it must fit the window, and nothing
// on it may sit on top of anything else.
//
// The failure this exists to catch is geometry, which reading the markup
// cannot show: a <select> sized to its longest option (a speaker's full
// name) pushes the card wider than the window, and a row of `nowrap` or
// fixed-width controls puts one control on top of the next. Both look fine
// at 1280px and are broken at 390px — the one width the tab is used at,
// with the music already playing.
//
// Static fixture, like measure-lightmap: the panel's own index.html with
// fetch stubbed, so it needs no server.
//
//   node tests/manual/measure-party.mjs
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'bright', 'panel');
const WIDTHS = [360, 390, 820, 1280];

const TRACKS = [1, 2, 3].map((n) => ({
  file: `/media/music/track-${n}.mp3`,
  name: `A Rather Long Song Title Number ${n} (Extended Club Mix)`,
  hash: String(n).repeat(40), analyzed: true,
  show: { tier: n === 2 ? 'claude' : 'director' },
  summary: { bpm: 120 + n, duration: 200, sections: 5, drops: 1, lyrics: false },
}));

// Long names on purpose: a select is as wide as its widest option, so this
// is what makes the speaker and scene pickers misbehave.
const STUB = `
window.fetch = async (url) => {
  const path = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (path.includes('api/library')) {
    return answer({ folder: '/media/music', exists: true,
      folders: [{ path: '/media/music', exists: true }],
      tracks: ${JSON.stringify(TRACKS)} });
  }
  if (path.includes('api/calibrate/profiles')) {
    return answer({ profiles: [
      { entity_id: 'media_player.living_room_sonos_arc_ultra_with_the_sub_and_both_rears' },
      { entity_id: 'media_player.kitchen' }] });
  }
  if (path.includes('domain=scene')) {
    return answer({ entities: [
      { entity_id: 'scene.a', name: 'Evening relaxed warm white with dimmed hallway lights' }] });
  }
  if (path.includes('api/parties')) return answer({ parties: [] });
  if (path.includes('api/status')) {
    return answer({ version: 'test', options: { music_folder: '/media/music' } });
  }
  return answer({});
};
`;

const failures = [];
const note = (label, message) => failures.push(`${label}: ${message}`);

const overlap = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
  && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : {});
for (const scheme of ['dark', 'light']) {
  for (const width of WIDTHS) {
    const label = `${width}px ${scheme}`;
    const context = await browser.newContext({
      viewport: { width, height: 900 }, colorScheme: scheme });
    const page = await context.newPage();
    page.on('pageerror', (error) => note(label, `page error: ${error.message}`));
    await page.addInitScript(STUB);
    await page.goto(`file://${path.join(PANEL, 'index.html')}`);
    await page.click('.tab[data-tab="party"]');
    await page.waitForSelector('#partySet .party-pick');
    await page.waitForFunction(
      () => document.querySelectorAll('#partyPlayer option').length > 1);
    await page.waitForTimeout(150);

    const found = await page.evaluate(() => {
      const box = (el) => {
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
      };
      const pane = document.getElementById('pane-party');
      const out = { page: document.documentElement.scrollWidth,
        window: document.documentElement.clientWidth, wide: [], pairs: [],
        bg: getComputedStyle(document.body).backgroundColor,
        ink: getComputedStyle(document.body).color };
      for (const el of pane.querySelectorAll('select, input, button, .card')) {
        if (!el.offsetParent) continue;
        const r = el.getBoundingClientRect();
        if (r.right > out.window + 0.5 || r.left < -0.5) {
          out.wide.push((el.id || el.className || el.tagName) + ' ' +
            Math.round(r.left) + '-' + Math.round(r.right));
        }
      }
      // Controls that sit on each other: every visible form control and
      // button on the pane, compared in pairs. Rows are allowed to contain
      // their own controls, so only leaf controls are compared.
      // A control scrolled out of the set's own box is clipped, not
      // overlapping, so it is not compared.
      const setBox = box(document.getElementById('partySet'));
      const leaves = [...pane.querySelectorAll('select, input, button')]
        .filter((el) => el.offsetParent !== null)
        .filter((el) => {
          if (!el.closest('#partySet')) return true;
          const b = box(el);
          return b.top >= setBox.top - 1 && b.bottom <= setBox.bottom + 1;
        });
      for (let i = 0; i < leaves.length; i += 1) {
        for (let j = i + 1; j < leaves.length; j += 1) {
          const a = box(leaves[i]); const b = box(leaves[j]);
          if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
            && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) {
            const name = (el) => el.id || el.className || el.tagName;
            out.pairs.push(name(leaves[i]) + ' over ' + name(leaves[j]));
          }
        }
      }
      return out;
    });
    if (found.page > found.window) {
      note(label, `the page is ${found.page}px in a ${found.window}px window`);
    }
    for (const w of found.wide) note(label, `runs off the window: ${w}`);
    for (const p of found.pairs) note(label, `overlap: ${p}`);

    // Follows the colour scheme: a light scheme may not keep the dark stage.
    const lum = (css) => {
      const m = css.match(/[\d.]+/g).map(Number);
      return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
    };
    const bg = lum(found.bg);
    if (scheme === 'light' && bg < 0.6) note(label, `background stays dark (${found.bg})`);
    if (scheme === 'dark' && bg > 0.4) note(label, `background is light (${found.bg})`);
    if (Math.abs(lum(found.ink) - bg) < 0.5) {
      note(label, `text ${found.ink} on ${found.bg} is unreadable`);
    }
    await context.close();
  }
}
await browser.close();

if (failures.length) {
  console.error('Party tab measures FAILED:');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`Party tab: fits and keeps clear at ${WIDTHS.join('/')}px, dark and light`);
