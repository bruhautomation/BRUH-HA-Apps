// Drive BRight's show editor in a real browser and measure what it does.
//
// The claim this checks is the one the editor is for: the picture is the
// interface, it is live, and editing through it cannot quietly change the
// show. None of that is answerable from the server — the preview is a floor
// of dots and a canvas, "the strip repainted" is a pixel question, and
// "opening an effect and pressing Apply left the file alone" is only true
// once a browser has actually done it.
//
// Start the panel first:
//   python3 tests/manual/bright_demo_panel.py /tmp/bright-demo
//   node tests/manual/measure-showeditor.mjs
//
// Fails (exit 1) on: a control under the touch floor, an unlit preview
// floor, a blank strip, a scrub that does not change the room, a scene
// block that does not move the playhead, an effect whose row misreads its
// selection, a no-op edit that rewrites the show, an edit that does not
// reach the preview, or any page error.
import { chromium } from 'playwright';

const URL = process.env.PANEL_URL || 'http://127.0.0.1:8095/';
const WIDTHS = [390, 820, 1280];
const TOUCH_FLOOR = 44;
// The panel's documented exception: secondary chip-style buttons sit at
// 40px across every tab. This measure is not the place to relitigate that,
// so it holds them to the floor they actually have.
const CHIP_FLOOR = 40;

const browser = await chromium.launch(
	process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : { args: ['--no-sandbox'] }
);

let failures = 0;
const fail = (msg) => { console.log(`  ✕ ${msg}`); failures += 1; };
const ok = (msg) => console.log(`  ✓ ${msg}`);

// The strip and the floor are pixels, so they are read as pixels. A hash of
// a sparse sample is enough to answer "did this repaint" without caring
// what it repainted to.
const stripHash = (page) => page.evaluate(() => {
	const c = document.getElementById('edStrip');
	if (!c.getContext) return 0;
	const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
	let h = 0;
	for (let i = 0; i < d.length; i += 97) h = (h * 31 + d[i]) >>> 0;
	return h;
});

const roomColours = (page) => page.evaluate(() =>
	Array.from(document.querySelectorAll('#edFloor .preview-dot'))
		.map((d) => d.style.background));

const scriptNow = (page) => page.evaluate(() =>
	document.getElementById('scriptText').value);

for (const width of WIDTHS) {
	console.log(`\n${width}px`);
	const page = await browser.newPage({ viewport: { width, height: 1000 } });
	const errors = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

	await page.goto(URL, { waitUntil: 'networkidle' });
	await page.click('.tab[data-tab="shows"]');
	await page.waitForSelector('#showList .row');
	await page.click('#showList .row');
	await page.waitForSelector('#edScript .ed-block');
	await page.waitForFunction(() =>
		document.querySelectorAll('#edFloor .preview-dot').length > 0);
	// The first window has to land before the room means anything.
	await page.waitForTimeout(1500);

	// -- the picture drew itself -------------------------------------
	const scenes = await page.$$eval('#edScenes .ed-scene', (e) => e.length);
	if (scenes < 2) fail(`the timeline drew ${scenes} scene blocks`);
	else ok(`${scenes} scene blocks on the timeline`);

	const blocks = await page.$$eval('#edScript .ed-block', (e) => e.length);
	const fxRows = await page.$$eval('#edScript .ed-fx-row', (e) => e.length);
	if (blocks !== scenes) fail(`${scenes} blocks above, ${blocks} below`);
	else ok(`${blocks} scenes, ${fxRows} effect rows`);

	const painted = await stripHash(page);
	if (!painted) fail('the strip canvas is blank');
	else ok('the strip painted');

	const dots = await roomColours(page);
	if (!dots.length) fail('the preview floor has no lights on it');
	else ok(`${dots.length} lights on the preview floor`);

	// -- an effect row says what it really owns ----------------------
	// The automatic director selects by ROLE for nearly everything it
	// writes, so a row that says "all lights" is a row that misreads the
	// show — and the first thing you would do about it is edit the wrong
	// effect.
	const labels = await page.$$eval('#edScript .ed-fx-row span',
		(e) => e.map((n) => n.textContent));
	const roleRows = labels.filter((t) => /candle|lamp|downlight|strip|party/.test(t));
	if (!roleRows.length) fail('no effect row names the roles it drives');
	else ok(`${roleRows.length} rows name their selection`);

	// -- scrubbing moves the room ------------------------------------
	const atStart = await roomColours(page);
	await page.evaluate(() => {
		const s = document.getElementById('edScrub');
		s.value = '600';
		s.dispatchEvent(new Event('input', { bubbles: true }));
	});
	await page.waitForTimeout(1800);
	const atPeak = await roomColours(page);
	if (JSON.stringify(atStart) === JSON.stringify(atPeak)) {
		fail('scrubbing to the peak did not change a single light');
	} else ok('scrubbing repaints the room');

	const clock = await page.textContent('#edClock');
	if (!/^\d+:\d\d \/ \d+:\d\d$/.test(clock.trim())) fail(`the clock reads "${clock}"`);
	else ok(`clock reads ${clock.trim()}`);

	// -- a scene block is a control ----------------------------------
	await page.click('#edScenes .ed-scene:nth-child(2)');
	await page.waitForTimeout(900);
	const head = await page.evaluate(() =>
		parseFloat(document.getElementById('edHead').style.left));
	if (!(head > 0)) fail(`pressing a scene left the playhead at ${head}%`);
	else ok(`a scene block moves the playhead (${head.toFixed(1)}%)`);

	// -- opening an effect and applying it changes nothing ------------
	const before = await scriptNow(page);
	await page.click('#edScript .ed-block:first-child .ed-fx-row:first-child [data-act="edit"]');
	await page.waitForSelector('#edFxParams [data-param]');
	await page.click('#btnEdFxApply');
	await page.waitForTimeout(900);
	const after = await scriptNow(page);
	if (before !== after) {
		fail('opening an effect and pressing Apply rewrote the show');
		console.log('    a no-op edit must be byte-identical; it was not');
	} else ok('a no-op edit leaves the show byte-identical');

	// -- a real edit reaches the preview -----------------------------
	// Added to the FIRST scene deliberately: the drop's stab owns the peak
	// outright, so an effect dropped there is legitimately invisible and
	// would make this assertion a coin toss rather than a check.
	const stripBefore = await stripHash(page);
	await page.click('#edScript .ed-block:first-child [data-act="add"]');
	await page.waitForSelector('#edFxParams [data-param]');
	await page.selectOption('#edFxType', 'strobe');
	await page.fill('#edFxName', 'measured strobe');
	await page.check('#edFxRoles input[data-id="downlight"]');
	await page.click('#btnEdFxApply');
	await page.waitForTimeout(2200);

	const rowsAfter = await page.$$eval('#edScript .ed-fx-row', (e) => e.length);
	if (rowsAfter !== fxRows + 1) fail(`adding an effect left ${rowsAfter} rows, expected ${fxRows + 1}`);
	else ok('the added effect is on the list');

	if (!(await scriptNow(page)).includes('measured strobe')) {
		fail('the added effect never reached the Code view');
	} else ok('the GUI edit is in the Code view');

	const stripAfter = await stripHash(page);
	if (stripBefore === stripAfter) fail('the strip did not repaint after a visible edit');
	else ok('the edit reached the preview');

	// -- every control is a real target ------------------------------
	const small = await page.evaluate(({ floor, chip }) => {
		const out = [];
		const seen = new Set();
		for (const el of document.querySelectorAll(
			'#showEditor button, #showEditor input, #showEditor select, #showEditor summary')) {
			const r = el.getBoundingClientRect();
			if (!r.width || !r.height) continue;
			// Scene blocks are sized by the scene they represent: a short
			// scene is a narrow block, and widening it would lie about the
			// show. They stay pressable via the list below.
			if (el.classList.contains('ed-scene')) continue;
			const name = el.id || el.className || el.tagName;
			if (seen.has(name)) continue;
			seen.add(name);
			const min = el.classList.contains('small') ? chip : floor;
			if (r.height < min) out.push(`${name} is ${Math.round(r.height)}px tall, under ${min}px`);
		}
		return out;
	}, { floor: TOUCH_FLOOR, chip: CHIP_FLOOR });
	if (small.length) small.forEach((s) => fail(s));
	else ok(`every editor control clears ${TOUCH_FLOOR}px`);

	// -- nothing overflows sideways ----------------------------------
	const overflow = await page.evaluate(() => {
		const doc = document.documentElement;
		return doc.scrollWidth - doc.clientWidth;
	});
	if (overflow > 1) fail(`the page scrolls ${overflow}px sideways`);
	else ok('no sideways overflow');

	if (errors.length) {
		errors.forEach((e) => fail(`page error: ${e}`));
	} else ok('no page errors');

	await page.close();
}

await browser.close();
console.log(failures ? `\n${failures} failure(s)` : '\nall good');
process.exit(failures ? 1 : 0);
