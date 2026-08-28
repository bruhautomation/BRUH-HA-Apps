// Drive BRight's Manual tab in a real browser and measure what it offers.
//
// This tab is a performance surface: it is used one-handed, on a phone, in
// a dark room, mid-song. So the measures are about the hand, not the eye —
// the pads have to be big enough to hit without looking, the tap pad has to
// register presses, and a gesture made before a session exists has to come
// back with the sentence that says so rather than nothing.
//
// Start the panel first:
//   python3 tests/manual/bright_demo_panel.py /tmp/bright-demo
//   node tests/manual/measure-manual.mjs
//
// Fails (exit 1) on: a pad under 70px or a control under the 44px touch
// floor (chips 40px), an empty light picker or effect rack, a tap that does
// not count, a loop press with no session that surfaces no refusal,
// sideways overflow, or any page error.
import { chromium } from 'playwright';

const URL = process.env.PANEL_URL || 'http://127.0.0.1:8095/';
const WIDTHS = [390, 820, 1280];
const TOUCH_FLOOR = 44;
const CHIP_FLOOR = 40;
const PAD_FLOOR = 70;

const browser = await chromium.launch(
	process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : { args: ['--no-sandbox'] }
);

let failures = 0;
const fail = (msg) => { console.log(`  ✕ ${msg}`); failures += 1; };
const ok = (msg) => console.log(`  ✓ ${msg}`);

for (const width of WIDTHS) {
	console.log(`\n${width}px`);
	const page = await browser.newPage({ viewport: { width, height: 900 } });
	const errors = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	page.on('console', (m) => {
		// An HTTP refusal is the panel working — this measure deliberately
		// provokes one (the no-session 409) and asserts its message
		// surfaces. Only real script errors count.
		if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) {
			errors.push(m.text());
		}
	});

	await page.goto(URL, { waitUntil: 'networkidle' });
	await page.click('.tab[data-tab="manual"]');
	await page.waitForSelector('#mnFixtures .fx-fixture', { timeout: 5000 })
		.catch(() => fail('the light picker stayed empty'));

	// The pads are the tab's whole reason: big, and above the fold's work.
	for (const [id, name] of [['btnMnDrop', 'DROP'], ['btnMnFlash', 'FLASH']]) {
		const box = await page.locator('#' + id).boundingBox();
		if (!box || box.height < PAD_FLOOR) {
			fail(`${name} pad is under ${PAD_FLOOR}px (${box ? Math.round(box.height) : 'missing'})`);
		}
	}
	const tap = await page.locator('#btnMnTap').boundingBox();
	if (!tap || tap.height < PAD_FLOOR) fail('the TAP pad is under the pad floor');
	else ok('pads clear the pad floor');

	// Everything pressable clears the touch floor (chips 40px).
	const small = await page.$$eval('#pane-manual button, #pane-manual select, #pane-manual input[type="checkbox"], #pane-manual input[type="radio"]',
		(nodes, floors) => nodes.filter((n) => {
			const r = n.getBoundingClientRect();
			if (!r.width || !r.height) return false;
			const chip = n.classList.contains('small') ||
				n.type === 'checkbox' || n.type === 'radio';
			// A checkbox/radio rides inside a label that is the real target.
			const target = chip && n.closest('label')
				? n.closest('label').getBoundingClientRect() : r;
			return target.height < (chip ? floors.chip : floors.full) - 0.5;
		}).map((n) => n.id || n.textContent.trim().slice(0, 20)),
		{ full: TOUCH_FLOOR, chip: CHIP_FLOOR });
	if (small.length) fail(`under the touch floor: ${small.join(', ')}`);
	else ok('every control clears the touch floor');

	// The effect rack drew itself from the catalog.
	const shots = await page.$$eval('#mnEffects button', (n) => n.length);
	if (shots < 6) fail(`only ${shots} one-shot effects in the rack`);
	else ok(`${shots} one-shot effects in the rack`);

	// Tapping counts, and shows a tempo once there are two.
	await page.dispatchEvent('#btnMnTap', 'pointerdown');
	await page.waitForTimeout(400);
	await page.dispatchEvent('#btnMnTap', 'pointerdown');
	const readout = await page.textContent('#mnTapReadout');
	if (!/2 taps/.test(readout) || !/BPM/.test(readout)) {
		fail(`two taps read as "${readout}"`);
	} else ok(`two taps read as "${readout.trim()}"`);

	// A loop asked for with no session running answers with the reason —
	// a round trip through the real server, not a dead button.
	await page.click('#btnMnLoopBeat');
	await page.waitForFunction(() =>
		/session/i.test(document.getElementById('mnStatus').textContent),
		{ timeout: 4000 })
		.catch(() => fail('Loop with no session surfaced no refusal'));
	ok('a loop with no session says why');
	await page.click('#btnMnTapClear');

	// The page must never scroll sideways — the body is the phone's width.
	const overflow = await page.evaluate(() =>
		document.documentElement.scrollWidth - document.documentElement.clientWidth);
	if (overflow > 1) fail(`page scrolls sideways by ${overflow}px`);
	else ok('no sideways overflow');

	if (errors.length) fail(`page errors: ${errors.join(' | ')}`);
	else ok('no page errors');

	await page.close();
}

await browser.close();
if (failures) {
	console.log(`\n${failures} failure(s)`);
	process.exit(1);
}
console.log('\nall good');
