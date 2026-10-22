// Drive the classic terminal's Talk button (brain/ttyd-assets/inject.html) in
// a real Chromium on a touch device, with Chromium's fake microphone, against
// the real voice routes (brain/panel/voice_mic.py) and the real arecord
// stand-in (brain/scripts/brain-arecord.py). voice_harness.py plays Claude
// Code in voice mode's tap setting: a space starts arecord with the CLI's own
// argv, the next space SIGTERMs it, and what arecord wrote to stdout is what
// the CLI would have transcribed.
//
// It fails on: a first press that does not set Claude Code's voice mode to
// tap; a press that never starts the recording, or does not say so on the
// button; audio that is silent, the wrong rate, or not there; a second press
// that does not stop it; anything left recording; a page error.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = `http://127.0.0.1:${PORT}`;
const CONFIG = fs.mkdtempSync(path.join(os.tmpdir(), 'brain-voice-'));

const failures = [];
function check(ok, what) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) failures.push(what);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const harness = spawn('python3', [path.join(HERE, 'voice_harness.py'), String(PORT), CONFIG],
  { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise((resolve, reject) => {
  harness.stdout.on('data', (d) => { if (String(d).includes('ready')) resolve(); });
  harness.on('exit', (c) => reject(new Error(`harness exited ${c}`)));
});

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
    '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
});
try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 780 }, hasTouch: true, isMobile: true,
  });
  await context.grantPermissions(['microphone'], { origin: BASE });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(`${BASE}/terminal/`);
  await page.waitForSelector('[data-bruh-key="mic"]');
  const mic = '[data-bruh-key="mic"]';
  const result = async () => (await fetch(`${BASE}/test/result`)).json();
  const typed = () => page.evaluate(() => window.__typed.slice());
  const label = () => page.textContent(mic);

  check(/Talk/.test(await label()), `the toolbar has a Talk button ("${await label()}")`);

  // 1. Voice mode is off: the first press turns it on in tap mode, through
  //    the CLI's own /voice, and records nothing.
  await page.tap(mic);
  await sleep(1500);
  check((await typed()).includes('/voice tap\r'), `a first press types /voice tap (${JSON.stringify(await typed())})`);
  check((await result()).spaces === 0, 'and starts no recording');
  check(/Talk/.test(await label()), 'and the button is back to Talk');

  // What /voice tap writes, so the next press records.
  fs.writeFileSync(path.join(CONFIG, 'settings.json'),
    JSON.stringify({ voiceEnabled: true, voice: { enabled: true, mode: 'tap' } }));

  // 2. Press: the CLI is asked to listen and the button says so.
  await page.tap(mic);
  let on = false;
  for (let i = 0; i < 40 && !on; i++) { await sleep(100); on = /Send/.test(await label()); }
  check(on, `a press starts the recording and the button says Send ("${await label()}")`);
  check((await result()).running, 'arecord is running');
  await sleep(2000);

  // 3. Press again: the CLI is told to stop, and what it heard is speech-
  //    shaped: about two seconds of 16 kHz mono, not silence.
  await page.tap(mic);
  let r = await result();
  for (let i = 0; i < 40 && r.running; i++) { await sleep(100); r = await result(); }
  check(!r.running, 'the second press stops arecord');
  check(r.spaces === 2, `exactly two spaces were typed (${r.spaces})`);
  console.log(`     page sent ${r.page_seconds.toFixed(2)} s in all`);
  check(r.seconds > 1.5 && r.seconds < 4, `about two seconds of 16 kHz audio reached the CLI (${r.seconds.toFixed(2)} s)`);
  check(r.rms > 100, `the audio is the microphone, not silence (rms ${r.rms.toFixed(0)})`);
  check(r.code === 0, `arecord ended cleanly (${r.code})`);
  await sleep(800);
  check(/Talk/.test(await label()), `the button is back to Talk ("${await label()}")`);
  check(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
  await context.close();
} finally {
  await browser.close();
  harness.kill();
  fs.rmSync(CONFIG, { recursive: true, force: true });
}

if (failures.length) {
  console.log(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log('\nall voice checks passed');
