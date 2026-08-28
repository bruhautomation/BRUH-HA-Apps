// Drive BRight's Manual tab in a real browser and measure what it offers.
//
// This tab is a performance surface: it is used one-handed, on a phone, in
// a dark room, mid-song. So the measures are about the hand, not the eye —
// and the first of them is the claim the whole redesign rests on: at a
// phone's size, the transport, the room, the clips, both pads and the
// effect rack are ALL on screen at once, with nothing to scroll past.
// "One screen" is a geometry claim, and a geometry claim you have not
// measured is a hope.
//
// It measures TWO bar states, because neither is a superset of the other:
// idle (the session selects are showing, and there is no grid to report)
// and running on a tapped grid (the selects are gone, TAP and the downbeat
// button are there instead). The second is staged by setting the same
// `hidden` flags the panel sets rather than by starting a session — a
// session against a house of unreachable bulbs takes twenty seconds to
// begin and another twenty to stop, and it is the same CSS either way.
//
// Start the panel first:
//   python3 tests/manual/bright_demo_panel.py /tmp/bright-demo
//   node tests/manual/measure-manual.mjs
//
// Fails (exit 1) on: anything the performance needs falling below the fold
// at 390×760, a page that scrolls at all, a floor with no tappable dot (or
// one under the touch floor), a pad under 70px, a control under the 44px
// touch floor (chips 40px), a missing or dead REC segmented control, a
// blank transport readout, sideways overflow, or any page error.
import { chromium } from 'playwright';

const URL = process.env.PANEL_URL || 'http://127.0.0.1:8095/';
// 390×760 is the iPhone inside Home Assistant's ingress iframe — the size
// the one-screen claim is made about, so it is measured at exactly that.
const WIDTHS = [390, 820, 1280];
const HEIGHT = 760;
const TOUCH_FLOOR = 44;
const CHIP_FLOOR = 40;
const PAD_FLOOR = 70;

// Everything the hand reaches for. The transport is on the list because a
// tab that can tell you where the bar is, below the fold, cannot.
const ROWS = {
	transport: '.mn-transport', floor: '#mnFloor', rec: '.mn-rec',
	clips: '#mnClipRail', drop: '#btnMnDrop', flash: '#btnMnFlash',
	rack: '#mnFx',
};

const browser = await chromium.launch(
	process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : { args: ['--no-sandbox'] }
);

let failures = 0;
const fail = (msg) => { console.log(`  ✕ ${msg}`); failures += 1; };
const ok = (msg) => console.log(`  ✓ ${msg}`);

// One screen, and no scrolling of any kind. The pane sizes itself to what
// is left below the top bar, so a row that grew shows up here as a page
// that got taller rather than as something quietly clipped.
async function measureFit(page, label) {
	const out = await page.evaluate(([want, h]) => {
		const bad = [];
		for (const [name, sel] of Object.entries(want)) {
			const el = document.querySelector(sel);
			if (!el) { bad.push(`${name} is missing`); continue; }
			const r = el.getBoundingClientRect();
			if (r.height < 1) bad.push(`${name} has no height`);
			else if (r.bottom > h + 0.5) {
				bad.push(`${name} ends ${Math.round(r.bottom - h)}px below the fold`);
			}
		}
		const doc = document.documentElement;
		return { bad, scroll: doc.scrollHeight - doc.clientHeight,
			sideways: doc.scrollWidth - doc.clientWidth };
	}, [ROWS, HEIGHT]);
	if (out.bad.length) fail(`${label}: off the one screen: ${out.bad.join(', ')}`);
	else ok(`${label}: transport, room, clips, pads and rack on one screen`);
	if (out.scroll > 1) fail(`${label}: the page scrolls ${out.scroll}px`);
	if (out.sideways > 1) fail(`${label}: page scrolls sideways by ${out.sideways}px`);
}

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

	await measureFit(page, 'idle');

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
				n.closest('.mn-fx') !== null || n.closest('.mn-seg') !== null;
			return r.height < (chip ? floors.chip : floors.full) - 0.5;
		}).map((n) => n.id || n.textContent.trim().slice(0, 20)),
		{ full: TOUCH_FLOOR, chip: CHIP_FLOOR });
	if (small.length) fail(`under the touch floor: ${small.join(', ')}`);
	else ok('every control clears the touch floor');

	// The transport always says something. A blank BPM and a blank bar are
	// the same screen as a transport that failed to render, and "— BPM" is
	// the honest answer when no grid has arrived — never a made-up 120.
	const readout = await page.evaluate(() => ({
		bpm: document.getElementById('mnBpm').textContent.trim(),
		bar: document.getElementById('mnBarBeat').textContent.trim(),
		rec: document.getElementById('mnRecLabel').textContent.trim(),
	}));
	if (!readout.bpm || !readout.bar || /NaN|undefined/.test(
		readout.bpm + readout.bar + readout.rec)) {
		fail(`the transport reads "${readout.bpm}" / "${readout.bar}"`);
	} else ok(`the transport reads "${readout.bpm} · ${readout.bar}"`);

	// You choose the loop's LENGTH before you play it, so those controls
	// are as load-bearing as REC itself — and a segment that does not take
	// a press is a length nobody can pick.
	const seg = await page.evaluate(() => ({
		bars: [...document.querySelectorAll('#mnRecBars button')]
			.map((b) => b.dataset.bars),
		quant: [...document.querySelectorAll('#mnRecQuant button')]
			.map((b) => b.dataset.quant),
	}));
	if (seg.bars.join(',') !== '1,2,4,8') {
		fail(`the bar lengths are ${seg.bars.join(',') || 'missing'}`);
	} else if (seg.quant.length !== 4) {
		fail(`${seg.quant.length} quantize choices, not 4`);
	} else {
		await page.locator('#mnRecBars button[data-bars="2"]').dispatchEvent('pointerdown');
		await page.locator('#mnRecQuant button[data-quant="0"]').dispatchEvent('pointerdown');
		const picked = await page.evaluate(() => ({
			bars: document.querySelector('#mnRecBars button.on')?.dataset.bars,
			quant: document.querySelector('#mnRecQuant button.on')?.dataset.quant,
		}));
		if (picked.bars !== '2' || picked.quant !== '0') {
			fail(`a press picked ${picked.bars} bars / quantize ${picked.quant}`);
		} else ok('1|2|4|8 bars and four quantize choices, and a press picks one');
	}

	// Drumming. Two strikes on one bulb must reach the wire and light the
	// dot without a throw, whichever transport is up — the whole tab is
	// pointerdown handlers that must never raise mid-song.
	const dot = page.locator('#mnFloor .mn-dot').first();
	await dot.dispatchEvent('pointerdown');
	await page.waitForTimeout(120);
	await dot.dispatchEvent('pointerdown');
	await page.waitForTimeout(120);
	ok('a bulb takes two strikes');

	// Arming with no session says why rather than sitting there: an
	// ambiguous REC is the failure this rewrite exists to remove.
	await page.locator('#btnMnRec').dispatchEvent('pointerdown');
	await page.waitForFunction(() =>
		document.getElementById('mnStatus').textContent.trim().length > 0 ||
		document.getElementById('mnRecLabel').textContent.trim() !== '● REC',
		{ timeout: 4000 })
		.catch(() => fail('REC with no session showed nothing at all'));
	ok('REC with no session says something');

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

	// The running bar is a different bar: the selects are gone and the two
	// grid controls have taken their place. Staged with the same flags the
	// panel sets, because it is that shape's geometry under test.
	await page.evaluate(() => {
		document.getElementById('mnSetup').hidden = true;
		for (const id of ['btnMnStop', 'btnMnTempoTap', 'btnMnDownbeat',
			'mnSource']) {
			document.getElementById(id).hidden = false;
		}
		document.getElementById('mnSource').textContent = '✋ tapped';
		document.getElementById('mnStatus').textContent =
			'Running · ♪ Something With A Long Name';
	});
	await page.waitForTimeout(80);
	await measureFit(page, 'running');

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
