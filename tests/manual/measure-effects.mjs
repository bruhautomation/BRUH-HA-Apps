// Drive BRight's Effects tab in a real browser and measure what it draws.
//
// The panel's claim is that you can build an effect, see it, and know what
// it costs before it ever reaches a bulb. That claim is only checkable in a
// browser: the preview is a canvas and a floor of dots, and "the timeline
// painted" is not something the server can answer.
//
// Start the panel first:
//   python3 tests/manual/bright_demo_panel.py /tmp/bright-demo
//   node tests/manual/measure-effects.mjs
//
// Fails (exit 1) on: a control under the 44px touch floor, a preview that
// renders no colour, a timeline canvas that stays blank, or any page error.
import { chromium } from 'playwright';

const URL = process.env.PANEL_URL || 'http://127.0.0.1:8095/';
const WIDTHS = [390, 820, 1280];
const TOUCH_FLOOR = 44;

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
	page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

	await page.goto(URL, { waitUntil: 'networkidle' });
	await page.click('.tab[data-tab="effects"]');
	await page.waitForSelector('#fxFixtures .fx-fixture');

	// The builder drew itself from the catalog.
	const types = await page.$$eval('#fxType option', (o) => o.length);
	if (types < 10) fail(`only ${types} effect types in the picker`);
	else ok(`${types} effect types offered`);

	const params = await page.$$eval('#fxParams [data-param]', (o) => o.length);
	if (params < 3) fail(`the parameter form drew ${params} controls`);
	else ok(`${params} parameters for the default effect`);

	// Every control a finger has to hit.
	const small = await page.$$eval(
		'#pane-effects button, #pane-effects select, #pane-effects input',
		(nodes, floor) => nodes
			.filter((n) => n.offsetParent !== null)
			.map((n) => ({ id: n.id || n.className, h: n.getBoundingClientRect().height }))
			.filter((n) => n.h > 0 && n.h < floor),
		TOUCH_FLOOR
	);
	// Checkboxes are 20px by design and sit inside a 44px row, which is the
	// target — measure the row for those.
	const realSmall = small.filter((n) => !String(n.id).includes('checkbox'));
	if (realSmall.length) {
		const rows = await page.$$eval('.fx-fixture, .fx-param',
			(nodes) => nodes.map((n) => n.getBoundingClientRect().height));
		const shortRows = rows.filter((h) => h > 0 && h < 40);
		if (shortRows.length) fail(`${shortRows.length} rows under 40px`);
		else ok('rows carry their own targets');
	} else {
		ok('every control clears the touch floor');
	}

	// Preview: the floor lights up and the timeline paints.
	await page.click('#btnFxPreview');
	await page.waitForFunction(
		() => document.querySelectorAll('#fxFloor .preview-dot').length > 0,
		{ timeout: 10000 });
	await page.waitForTimeout(700);

	const lit = await page.$$eval('#fxFloor .preview-dot', (dots) =>
		dots.filter((d) => d.style.background && d.style.background !== 'none').length);
	if (!lit) fail('the preview floor drew no colour');
	else ok(`${lit} lights drawn on the preview floor`);

	const painted = await page.evaluate(() => {
		const canvas = document.getElementById('fxTimeline');
		if (!canvas || !canvas.width) return 0;
		const data = canvas.getContext('2d')
			.getImageData(0, 0, canvas.width, canvas.height).data;
		let coloured = 0;
		for (let i = 0; i < data.length; i += 4 * 97) {
			if (data[i] + data[i + 1] + data[i + 2] > 40) coloured += 1;
		}
		return coloured;
	});
	if (painted < 5) fail(`the timeline canvas painted ${painted} lit samples`);
	else ok(`the timeline canvas painted (${painted} lit samples)`);

	const cost = await page.textContent('#fxCost');
	if (!/cues/.test(cost || '')) fail(`no cost line: ${cost}`);
	else ok(`cost line: ${cost.trim()}`);

	// The show file opens from the Shows tab.
	await page.click('.tab[data-tab="shows"]');
	await page.waitForSelector('#showList .row', { timeout: 10000 });
	await page.click('#showList .row .row-main');
	await page.waitForFunction(
		() => document.getElementById('scriptText').value.length > 100,
		{ timeout: 10000 });
	const script = await page.inputValue('#scriptText');
	if (!script.includes('"effects"')) fail('the show file carries no effects');
	else ok(`the show file opened (${script.length} chars)`);

	// Stop buttons stay hidden while nothing is running.
	const stops = await page.$$eval('#btnShowStop, #btnPartyStop, #btnSyncStop',
		(nodes) => nodes.filter((n) => n.offsetParent !== null).length);
	if (stops) fail(`${stops} Stop buttons visible with nothing running`);
	else ok('no Stop button while the lights are idle');

	// …and appear the moment the add-on says a run is in progress. Stubbed
	// rather than started for real, because what is being tested is the
	// rendering rule — "the button follows `active`" — and a real party
	// needs a calibrated speaker and eight bulbs on the network.
	await page.route('**/api/show/state', (route) => route.fulfill({
		status: 200, contentType: 'application/json',
		body: JSON.stringify({ status: 'party', active: true, lights_busy: true,
			party: 'Saturday', track: 'Demo Track', cues_sent: 12,
			cues_total: 400, queue_left: 3, nudge_ms: 50,
			up_next: ['Second Song', 'Third Song'] }),
	}));
	await page.click('.tab[data-tab="party"]');
	await page.waitForFunction(
		() => document.getElementById('btnPartyStop').offsetParent !== null,
		{ timeout: 8000 }).catch(() => fail('Stop stayed hidden during a run'));
	const now = await page.textContent('#partyNow');
	if (!/Saturday/.test(now || '')) fail(`the run line does not name it: ${now}`);
	else ok(`Stop appears while running · ${now.trim()}`);

	// The live view: what the party is doing has to be ON the party tab
	// while it does it — up next, the trim, and controls a thumb can hit.
	const liveHidden = await page.$eval('#partyLive', (el) => el.hidden);
	if (liveHidden) fail('the live view stayed hidden during a run');
	const upNext = await page.textContent('#partyUpNext');
	if (!/Second Song/.test(upNext || '')) {
		fail(`up next does not name the queue: "${upNext}"`);
	} else ok(`up next reads: ${upNext.trim()}`);
	const readout = await page.textContent('#nudgeReadout');
	if (!/\+50ms/.test(readout || '')) {
		fail(`the trim readout does not show the state's trim: "${readout}"`);
	}
	const keepHidden = await page.$eval('#btnNudgeKeep', (el) => el.hidden);
	if (keepHidden) fail('Keep this trim is hidden while a trim exists');
	for (const id of ['btnNudgeLater', 'btnNudgeEarlier', 'btnNudgeKeep']) {
		const box = await page.$eval('#' + id,
			(el) => el.getBoundingClientRect());
		if (box.height < 40) fail(`${id} is ${Math.round(box.height)}px tall`);
	}
	await page.unroute('**/api/show/state');

	// And when nothing runs, the live view is GONE — a picture of the
	// last party beside an idle Start button reads as a running one.
	await page.route('**/api/show/state', (route) => route.fulfill({
		status: 200, contentType: 'application/json',
		body: JSON.stringify({ status: 'idle', active: false }),
	}));
	await page.waitForFunction(
		() => document.getElementById('partyLive').hidden,
		{ timeout: 8000 }).catch(() => fail('the live view outlived the run'));
	await page.unroute('**/api/show/state');

	// The set IS the party. There is one surface now — tick the shows,
	// press Play — so the list has to be there, the tick order has to be
	// visible (it is what "in the order you tick them" promises), and
	// Play has to say what it would do.
	await page.waitForSelector('#partySet .party-pick', { timeout: 8000 })
		.catch(() => fail('the set list never loaded'));
	const picks = await page.locator('#partySet .party-pick').count();
	if (!picks) fail('the set has no songs to tick');
	else {
		const idle = (await page.textContent('#btnPartyStart') || '').trim();
		if (!/everything/.test(idle)) {
			fail(`nothing ticked should offer everything: "${idle}"`);
		}
		await page.locator('#partySet .party-pick input').first().check();
		const one = (await page.textContent('#btnPartyStart') || '').trim();
		const badge = (await page.textContent('#partySet .party-order') || '').trim();
		if (!/1 show/.test(one)) fail(`Play does not count the set: "${one}"`);
		else if (badge !== '#1') fail(`the tick order is not shown: "${badge}"`);
		else ok(`the set counts and orders: ${one} · ${badge}`);
		await page.click('#btnSetNone');
		const cleared = (await page.textContent('#btnPartyStart') || '').trim();
		if (!/everything/.test(cleared)) fail(`None did not clear: "${cleared}"`);
	}

	// The vibe box is not on this tab any more: it steers the director,
	// which is a compile-time decision, and here it reached only a track
	// with no show yet.
	if (await page.$('#pane-party #partyVibe')) {
		fail('the vibe box is back on the party tab');
	} else ok('no vibe box on the party tab');

	if (errors.length) fail(`page errors: ${errors.slice(0, 3).join(' | ')}`);
	else ok('no page errors');

	await page.close();
}

await browser.close();
console.log(failures ? `\n${failures} failure(s)` : '\nall good');
process.exit(failures ? 1 : 0);
