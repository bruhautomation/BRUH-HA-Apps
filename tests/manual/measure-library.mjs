// Assert the Library tab shows the music without being asked twice.
//
// The bug this exists to prevent: `scanLibrary` was bound to the Scan button
// and to nothing else, so the tab opened empty every single time and the
// first thing you did on it was press a button to be shown the library you
// already had. After an add-on restart that is indistinguishable from having
// lost it — which is exactly how it was reported ("I have to load my playlist
// music every time I restart"). Nothing was ever lost: the analysis lives in
// /data and always survived. It simply was never asked for.
//
// So the check is about who does the asking. It counts requests to
// `api/library` and fails if opening the tab makes none — a tab that renders
// a Scan button and waits is the regression, and it looks identical to a
// working one in a screenshot.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'bright', 'panel');
const WIDTHS = [390, 820, 1280];

const TRACKS = [
  { file: '/media/music/one.mp3', name: 'Midnight In The Kitchen',
    hash: 'a'.repeat(40), analyzed: true,
    summary: { bpm: 122, duration: 214, sections: 6, drops: 2, lyrics: false } },
  { file: '/media/music/two.flac', name: 'Second Song', hash: 'b'.repeat(40),
    analyzed: false },
];

const STUB = `
window.__libraryCalls = 0;
window.fetch = async (url) => {
  const path = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (path.includes('api/library')) {
    window.__libraryCalls += 1;
    return answer({ folder: '/media/music', exists: true,
                    folders: [{ path: '/media/music', exists: true }],
                    tracks: ${JSON.stringify(TRACKS)} });
  }
  if (path.includes('api/status')) {
    return answer({ version: 'test', options: { music_folder: '/media/music' } });
  }
  return answer({});
};
`;

const failures = [];
const note = (width, message) => failures.push(`${width}px: ${message}`);

const browser = await chromium.launch();
for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => note(width, `page error: ${error.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);

  // Opening the tab is the whole interaction. Nothing below may click Scan.
  await page.click('.tab[data-tab="library"]');
  await page.waitForFunction(() => window.__libraryCalls > 0, { timeout: 4000 })
    .catch(() => note(width, 'opening the Library tab asked for nothing'));
  await page.waitForSelector('#trackList .row', { timeout: 4000 })
    .catch(() => note(width, 'the track list stayed empty without pressing Scan'));

  const rows = await page.$$eval('#trackList .row', (nodes) => nodes.map((row) => ({
    name: row.querySelector('strong').textContent.trim(),
    summary: row.querySelector('.rtt').textContent.trim(),
  })));
  if (rows.length !== TRACKS.length) {
    note(width, `${rows.length} rows for ${TRACKS.length} tracks`);
  }
  for (const track of TRACKS) {
    if (!rows.some((row) => row.name === track.name)) {
      note(width, `"${track.name}" is missing from the list`);
    }
  }
  // An analyzed track has to say so, or the list cannot be used to decide
  // what still needs analysing — which is what the tab is for.
  const analyzed = rows.find((row) => row.name === TRACKS[0].name);
  if (analyzed && !/122/.test(analyzed.summary)) {
    note(width, `analyzed track shows no bpm: "${analyzed.summary}"`);
  }

  // Re-opening re-asks: a track added since should turn up without a restart.
  await page.click('.tab[data-tab="lab"]');
  await page.click('.tab[data-tab="library"]');
  const calls = await page.evaluate(() => window.__libraryCalls);
  if (calls < 2) note(width, `re-opening the tab did not refresh (${calls} calls)`);

  await context.close();
}
await browser.close();

if (failures.length) {
  console.error('Library tab measures FAILED:');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`Library tab: opens loaded at ${WIDTHS.join('/')}px`);
