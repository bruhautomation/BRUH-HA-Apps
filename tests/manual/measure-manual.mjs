// Drive BRight's Manual tab in a real browser and measure what it offers.
//
// This tab is a performance surface: it is used one-handed, on a phone, in
// a dark room, mid-song. So the measures are about the hand, not the eye —
// and the first of them is the claim the whole redesign rests on: at a
// phone's size, the room, the loop button, both pads and the effect rack
// are ALL on screen at once. "One screen" is a geometry claim, and a
// geometry claim you have not measured is a hope.
//
// Start the panel first:
//   python3 tests/manual/bright_demo_panel.py /tmp/bright-demo
//   node tests/manual/measure-manual.mjs
//
// Fails (exit 1) on: anything the performance needs falling below the fold
// at 390×760, a floor with no tappable dot (or one under the touch floor),
// a tapped dot that does not reach the readout, a pad under 70px, a control
// under the 44px touch floor (chips 40px), sideways overflow, or any page
// error.
import { chromium } from 'playwright';

const URL = process.env.PANEL_URL || 'http://127.0.0.1:8095/';
// 390×760 is the iPhone inside Home Assistant's ingress iframe — the size
// the one-screen claim is made about, so it is measured at exactly that.
const WIDTHS = [390, 820, 1280];
const HEIGHT = 760;
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
	console.log(`\n${width}×${HEIGHT}`);
	const page = await browser.newPage({ viewport: { width, height: HEIGHT } });
	const errors = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	page.on('console', (m) => {
		// Two deliberate refusals are not script errors. An HTTP refusal is
		// the panel working (a gesture with no session answers 409), and a
		// live socket that will not open is the fallback path this tab is
		// required to survive — one console.warn, then one POST per
		// gesture, which is what the rest of this file measures either way.
		if (m.type() === 'error' &&
			!/Failed to load resource/.test(m.text()) &&
			!/WebSocket/i.test(m.text())) {
			errors.push(m.text());
		}
	});

	await page.goto(URL, { waitUntil: 'networkidle' });
	await page.click('.tab[data-tab="manual"]');
	await page.waitForSelector('#mnFloor .mn-dot', { timeout: 5000 })
		.catch(() => fail('the floor drew no lights'));

	// THE claim: with the session row idle (setup open, nothing running),
	// everything you perform with is inside the viewport.
	const below = await page.evaluate((h) => {
		const want = { floor: '#mnFloor', loop: '#btnMnLoop', drop: '#btnMnDrop',
			flash: '#btnMnFlash', rack: '#mnFx' };
		const out = [];
		for (const [name, sel] of Object.entries(want)) {
			const el = document.querySelector(sel);
			if (!el) { out.push(`${name} is missing`); continue; }
			const r = el.getBoundingClientRect();
			if (r.height < 1) out.push(`${name} has no height`);
			else if (r.bottom > h + 0.5) {
				out.push(`${name} ends ${Math.round(r.bottom - h)}px below the fold`);
			}
		}
		return out;
	}, HEIGHT);
	if (below.length) fail(`off the one screen: ${below.join(', ')}`);
	else ok('room, Loop, DROP, FLASH and the rack are all on one screen');

	// The dots are the instrument, so they are targets like any other.
	const dots = await page.$$eval('#mnFloor .mn-dot', (nodes, floor) => ({
		count: nodes.length,
		small: nodes.filter((n) => {
			const r = n.getBoundingClientRect();
			return r.width < floor - 0.5 || r.height < floor - 0.5;
		}).length,
	}), TOUCH_FLOOR);
	if (!dots.count) fail('no tappable lights on the floor');
	else if (dots.small) fail(`${dots.small} light dot(s) under ${TOUCH_FLOOR}px`);
	else ok(`${dots.count} light dots, all ≥${TOUCH_FLOOR}px`);

	// The pads are the tab's panic buttons: big, and hit without looking.
	for (const [id, name] of [['btnMnDrop', 'DROP'], ['btnMnFlash', 'FLASH']]) {
		const box = await page.locator('#' + id).boundingBox();
		if (!box || box.height < PAD_FLOOR) {
			fail(`${name} pad is under ${PAD_FLOOR}px (${box ? Math.round(box.height) : 'missing'})`);
		}
	}
	ok('pads clear the pad floor');

	// Everything pressable clears the touch floor (chips 40px).
	const small = await page.$$eval('#pane-manual button, #pane-manual select',
		(nodes, floors) => nodes.filter((n) => {
			const r = n.getBoundingClientRect();
			if (!r.width || !r.height) return false;
			const chip = n.classList.contains('small') ||
				n.closest('.mn-fx') !== null;
			return r.height < (chip ? floors.chip : floors.full) - 0.5;
		}).map((n) => n.id || n.textContent.trim().slice(0, 20)),
		{ full: TOUCH_FLOOR, chip: CHIP_FLOOR });
	if (small.length) fail(`under the touch floor: ${small.join(', ')}`);
	else ok('every control clears the touch floor');

	// The rack drew itself from the catalog, and scrolls sideways rather
	// than costing the screen a second row.
	const rack = await page.evaluate(() => {
		const strip = document.getElementById('mnFx');
		return { chips: strip.querySelectorAll('button').length,
			rows: strip.getBoundingClientRect().height };
	});
	if (rack.chips < 6) fail(`only ${rack.chips} chips in the rack`);
	else if (rack.rows > 72) fail(`the rack is ${Math.round(rack.rows)}px — more than one row`);
	else ok(`${rack.chips} chips in a ${Math.round(rack.rows)}px rack`);

	// Tapping a bulb counts, and two of them read as a tempo — the tap
	// buffer is what Loop and the rack both aim with.
	const dot = page.locator('#mnFloor .mn-dot').first();
	await dot.dispatchEvent('pointerdown');
	await page.waitForTimeout(400);
	await dot.dispatchEvent('pointerdown');
	const readout = await page.textContent('#mnTapReadout');
	if (!/2 taps/.test(readout) || !/BPM/.test(readout)) {
		fail(`two taps on a bulb read as "${readout}"`);
	} else ok(`two taps on a bulb read as "${readout.trim()}"`);

	// Closing the pattern with no session says why, over whichever
	// transport is up — a round trip through the real server.
	await page.click('#btnMnLoop');
	await page.waitForFunction(() =>
		document.getElementById('mnStatus').textContent.trim().length > 0,
		{ timeout: 4000 })
		.catch(() => fail('Loop with no session surfaced no refusal'));
	ok('a loop with no session says something');

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
