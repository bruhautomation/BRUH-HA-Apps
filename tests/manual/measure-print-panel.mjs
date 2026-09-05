/* Playwright measure for the BRUH Print panel.
 *
 * Boot the panel first:
 *   python3 tests/manual/bruh_print_demo_panel.py /tmp/bruh-print-demo &
 *   node tests/manual/measure-print-panel.mjs
 *
 * Geometry cannot see everything a person sees, but it sees the things that
 * have actually broken here, each of which is invisible from the code:
 *
 *   - a top bar 513px wide in a 390px window, because a flex item's floor is
 *     its max-content and the chips would not wrap;
 *   - a <select> laid out to its widest OPTION, taking the design tab's
 *     page-width with it;
 *   - `.btn.tiny` staying 32px on touch, because the touch-floor block sat
 *     ABOVE it in the stylesheet and equal specificity is settled by order;
 *   - an empty black toast across the bottom, because `.toast{display:flex}`
 *     beats the UA's `[hidden]` rule;
 *   - a design canvas rendered at 2x the printer's resolution and never
 *     fitted, so a 2.25" label was 1344px wide inside a 600px pane.
 *
 * And three that are about the designer being a tool you can aim with: the
 * drawable area has to be VISIBLE (nothing on screen said where the
 * printer's margin was, so people built labels flush to the edge), a box
 * dragged at the edge has to STOP at it, and a snap has to say so while it
 * is happening — a box that jumps with no line drawn reads as the editor
 * moving things on its own.
 *
 * Set SHOTS=1 to keep a screenshot per state. */
import { chromium } from 'playwright';
/* The prefix is the point: the panel is measured where ingress actually
 * mounts it, not at the root. Served at "/" every absolute asset URL works
 * by accident, which is how a panel that rendered as unstyled HTML under
 * ingress passed this measure at three widths. */
const PREFIX = process.env.DEMO_PREFIX
  || '/api/hassio_ingress/01JJRqzH5o3TtVgngV7GNA3w';
const URL = process.env.PANEL_URL || `http://127.0.0.1:8097${PREFIX}/`;
/* Same launch as every other measure in this folder: Playwright's own
 * browser by default, and CHROMIUM_PATH when it is somewhere else. An
 * absolute path baked in here is a script that runs on exactly one
 * machine — which is what shipped, and what CI caught on the first run. */
const b = await chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] }
    : { args: ['--no-sandbox'] });
const problems = [];

/* `width` is passed in rather than read from innerWidth: under Chromium's
 * mobile emulation the visual viewport WIDENS to fit an overflowing page, so
 * innerWidth grows to match scrollWidth and the comparison can never fail —
 * which is exactly what let a 513px bar pass in a 390px window. */
const audit = (width) => {
  const out = [];
  const coarse = matchMedia('(pointer: coarse)').matches;
  if (document.documentElement.scrollWidth > width + 1)
    out.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${width})`);
  for (const n of document.querySelectorAll('button, .tab, .chip, input, select, textarea')) {
    const r = n.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const name = n.id || n.className || n.tagName;
    if (n.type !== 'checkbox' && r.height < 40) out.push(`${name} is ${r.height.toFixed(0)}px tall`);
    if (coarse && ['INPUT','SELECT','TEXTAREA'].includes(n.tagName) && n.type !== 'checkbox'
        && parseFloat(getComputedStyle(n).fontSize) < 16)
      out.push(`${name} is under 16px on touch — iOS will zoom in and stay there`);
  }
  if (getComputedStyle(document.getElementById('toast')).display !== 'none')
    out.push('the toast is visible with nothing to say');
  /* A stylesheet that 404s leaves a page that still lays out, so the audit
   * has to ask whether the CSS and the JS actually arrived. Both have a
   * visible consequence: `.view` is display:none until a tab is chosen, and
   * app.js is what fills the stock picker. */
  const onScreen = [...document.querySelectorAll('.view')]
    .filter((v) => v.offsetParent !== null).length;
  if (onScreen !== 1)
    out.push(`${onScreen} views are on screen at once — style.css did not load`);
  if (!document.querySelector('#quickStock option'))
    out.push('the stock picker is empty — app.js did not load or /api/state failed');
  const canvas = document.getElementById('canvas');
  const pane = document.querySelector('.canvas-scroll');
  if (canvas && pane && canvas.getBoundingClientRect().width > pane.clientWidth)
    out.push('the design canvas is wider than its pane');
  /* Which way the text sits is ONE setting, on the Printer tab. Two controls
   * that answer the same question are two controls that can disagree about
   * a property of the roll. */
  for (const gone of ['quickRotate', 'designRotate'])
    if (document.getElementById(gone))
      out.push(`#${gone} is back — the turn is the stock's, and it is set once`);
  return [...new Set(out)];
};

/* The font picker: one press, a dialog, and rows a thumb can hit. A picker
 * whose rows are 32px is a list you scroll past the one you wanted. */
const checkFontPicker = async (p, name) => {
  const button = await p.$('#quickFont');
  if (!button) return problems.push(`${name}: no font picker on the Quick tab`);
  await button.click();
  await p.waitForTimeout(400);
  const rows = await p.$$eval('#modal[open] .fontrow',
    (nodes) => nodes.map((n) => n.getBoundingClientRect().height));
  if (!rows.length)
    problems.push(`${name}: the font picker opened no rows`);
  const short = rows.filter((h) => h < 44);
  if (short.length)
    problems.push(`${name}: ${short.length} font rows under 44px `
      + `(shortest ${Math.min(...rows).toFixed(0)}px)`);
  const samples = await p.$$eval('#modal[open] .fontrow img',
    (nodes) => nodes.filter((n) => n.naturalWidth > 0).length);
  if (rows.length && !samples)
    problems.push(`${name}: no font sample image loaded — the picker is a `
      + 'list of names, which is what it replaced');
  await p.keyboard.press('Escape');
  await p.waitForTimeout(200);
};

/* Add a text box, drag it at the right-hand edge, and ask the LABEL where it
 * ended up. Reading pixels back would be measuring this script's own
 * arithmetic; `S.label` is the document that gets printed. */
const dragToTheEdge = async (p, name) => {
  const box = await p.$('#overlay .el');
  if (!box) return problems.push(`${name}: no element box to drag`);
  const safe = await p.$('#overlay .safe');
  const safeBox = safe && await safe.boundingBox();
  if (!safeBox || safeBox.width < 4 || safeBox.height < 4)
    problems.push(`${name}: the printable area is not drawn — nothing on `
      + 'screen says where the printer’s margin is');

  /* Scrolled into view first, and re-measured after. On a phone the design
   * view stacks and the Print bar is `position: sticky; bottom: 0` — so the
   * canvas's own bottom sits under it, and a press aimed at a box down there
   * lands on the Print button. Not a bug in the panel; a measure that drives
   * a control it cannot actually reach is testing nothing. */
  await p.evaluate(() =>
    document.getElementById('canvas').scrollIntoView({ block: 'center' }));
  await p.waitForTimeout(250);
  const start = await box.boundingBox();
  await p.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await p.mouse.down();
  let sawGuide = false;
  for (const step of [0.3, 0.6, 1.0]) {
    await p.mouse.move(start.x + start.width / 2 + 900 * step,
                       start.y + start.height / 2, { steps: 6 });
    await p.waitForTimeout(90);
    if (await p.$('#guides .guide')) sawGuide = true;
  }
  await p.mouse.up();
  await p.waitForTimeout(500);

  if (!sawGuide)
    problems.push(`${name}: nothing snapped visibly — a box that jumps with `
      + 'no line drawn reads as the editor moving things on its own');
  const state = await p.evaluate(() => {
    const s = window.__bruhPrintState;
    if (!s || !s.label) return null;
    const stock = s.stocks.find((row) => row.id === s.label.stock);
    if (!stock) return null;
    const [w, h] = stock.drawable_mm;
    const turned = s.label.rotate === 90 || s.label.rotate === 270;
    const first = s.label.elements[0];
    return { right: first.x_mm + first.w_mm, bottom: first.y_mm + first.h_mm,
             width: turned ? h : w, height: turned ? w : h };
  });
  if (!state) return problems.push(`${name}: window.__bruhPrintState is not readable`);
  if (state.right > state.width + 0.05)
    problems.push(`${name}: the box was dragged past the printable area `
      + `(${state.right.toFixed(1)}mm of ${state.width.toFixed(1)}mm)`);
  if (state.bottom > state.height + 0.05)
    problems.push(`${name}: the box hangs below the printable area `
      + `(${state.bottom.toFixed(1)}mm of ${state.height.toFixed(1)}mm)`);
};

/* A label drawn at 90° is designed as the long strip it reads as, and the
 * picture under the overlay has to be that strip — not the tall sheet that
 * comes off the roll. The two disagreed for every wrap-around label: the
 * box being dragged sat over one part of the strip while the words it
 * described were drawn sideways somewhere else, which is invisible from the
 * code (both the overlay and the image are "right", in different frames)
 * and obvious from a screenshot. */
const checkTurnedCanvas = async (p, name) => {
  /* The stock picker lives in the ⋯ sheet now — the design bar is the add
   * strip and one button, because five rows of bar put the label being
   * designed at y=590 of a 780px phone. */
  await p.click('#designMore');
  await p.waitForTimeout(300);
  await p.selectOption('#designStock', 'ed1f-060wh');
  await p.click('#designSheetDone');
  await p.waitForTimeout(900);
  const shape = await p.evaluate(() => {
    const s = window.__bruhPrintState;
    const image = document.getElementById('designPreview');
    const canvas = document.getElementById('canvas').getBoundingClientRect();
    return { rotate: s?.label?.rotate, imgW: image.naturalWidth,
             imgH: image.naturalHeight, w: canvas.width, h: canvas.height };
  });
  if (shape.rotate !== 90)
    problems.push(`${name}: a 0.56" × 3.44" stock should design at 90°, got ${shape.rotate}`);
  if (!(shape.imgW > shape.imgH))
    problems.push(`${name}: the design preview of a turned label is the printed `
      + `sheet (${shape.imgW}×${shape.imgH}), not the strip the overlay describes`);
  if (!(shape.w > shape.h))
    problems.push(`${name}: the design canvas of a turned label is taller than wide`);
};

/* ── The phone budget ──────────────────────────────────────────────────
 *
 * Every number below was MEASURED on this demo at 390 x 780 — an iPhone
 * once Home Assistant's own header has taken its ~56px — and each is the
 * value that was actually reached plus a little room, never a target
 * somebody liked the look of. What they replaced, measured the same way:
 *
 *   persistent chrome 247px (32% of the screen before any content),
 *   the design canvas starting at y=590 with 166px of height left,
 *   the Quick preview at y=899 — off the bottom of a 780px screen, on the
 *   one tab whose whole point is that you see what you are about to print.
 *
 * Now: 96 / 254 / 379. The budgets are the headroom above those. */
const PHONE = { w: 390, h: 780 };
/* The tab strip alone, once the status row has scrolled away. */
const CHROME_PINNED_MAX = 110;
/* Everything above the first content, unscrolled. */
const CHROME_TOP_MAX = 165;
/* Where the design workspace starts. */
const CANVAS_TOP_MAX = 280;

/* A control behind a disclosure is fine; a control behind nothing is a
 * control that is gone. Every secondary thing moved on a phone is opened
 * here and asked whether it is really there and really hittable. */
const reachable = async (p, name, open, ids) => {
  await open();
  await p.waitForTimeout(350);
  const found = await p.evaluate((wanted) => wanted.map((id) => {
    const node = document.getElementById(id);
    if (!node) return `#${id} is not in the page at all`;
    const box = node.getBoundingClientRect();
    if (!box.width || !box.height) return `#${id} is not rendered`;
    /* A checkbox is 22px by the touch floor's own rule; its label is the
     * target, so it is measured on the row it sits in. */
    const target = node.type === 'checkbox'
      ? (node.closest('.check') || node).getBoundingClientRect() : box;
    if (target.height < 40) return `#${id} is ${target.height.toFixed(0)}px tall`;
    return null;
  }), ids);
  for (const bad of found.filter(Boolean)) problems.push(`${name}: ${bad}`);
};

const phoneBudget = async (p, name) => {
  /* Persistent chrome is measured SCROLLED, because that is the only state
   * in which "persistent" means anything: the bar is sticky with a negative
   * top, so what is left pinned is the tab strip and nothing else. */
  await p.evaluate(() => scrollTo(0, 4000));
  await p.waitForTimeout(400);
  const pinned = await p.evaluate(() => {
    const tabs = document.querySelector('.tabs').getBoundingClientRect();
    const bar = document.querySelector('.topbar').getBoundingClientRect();
    return { bottom: tabs.bottom, top: tabs.top, barTop: bar.top,
             scrolled: window.scrollY };
  });
  if (pinned.scrolled > 4) {
    if (pinned.bottom > CHROME_PINNED_MAX)
      problems.push(`${name}: ${pinned.bottom.toFixed(0)}px of chrome stays `
        + `pinned (budget ${CHROME_PINNED_MAX})`);
    /* The tabs must still BE there. A bar that scrolled the navigation away
     * with the status row would pass a height budget by disappearing. */
    if (pinned.top < -1 || pinned.bottom < 40)
      problems.push(`${name}: the tab strip scrolled off the top with the `
        + 'status row — navigation is the half that stays');
  }
  await p.evaluate(() => scrollTo(0, 0));
  await p.waitForTimeout(300);
  const top = await p.evaluate(() =>
    document.querySelector('.topbar').getBoundingClientRect().height);
  if (top > CHROME_TOP_MAX)
    problems.push(`${name}: ${top.toFixed(0)}px of chrome above the first `
      + `content (budget ${CHROME_TOP_MAX})`);
};

const run = async (w, h, name, touch, steps) => {
  const ctx = await b.newContext({ viewport: { width: w, height: h },
    deviceScaleFactor: 2, hasTouch: touch, isMobile: touch,
    colorScheme: name.includes('dark') ? 'dark' : 'light' });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
  p.on('console', (m) => { if (m.type() === 'error') problems.push(`${name} console: ${m.text()}`); });
  await p.goto(URL, { waitUntil: 'networkidle' });
  /* Before driving anything: did the page's own assets arrive? A stylesheet
   * that 404s leaves a page that still lays out, and a script that 404s
   * leaves controls that never appear — so every `click` times out and the
   * failure reads as a flaky selector rather than as "the panel did not
   * load". Ask first, and say which. */
  const arrived = await p.evaluate(() => {
    const bad = [];
    if (!getComputedStyle(document.body).backgroundColor
        || getComputedStyle(document.querySelector('.topbar')).position !== 'sticky')
      bad.push('style.css did not load (the page is unstyled)');
    if (typeof window.__bruhPrintReady === 'undefined')
      bad.push('app.js did not load');
    return bad;
  });
  if (arrived.length) {
    problems.push(`${name}: ${arrived.join('; ')}`);
    await ctx.close();
    return;
  }
  if (steps) await steps(p);
  await p.waitForTimeout(900);
  const found = await p.evaluate(audit, w);
  if (found.length) problems.push(`${name}: ${found.join('; ')}`);
  if (process.env.SHOTS) await p.screenshot({ path: `${name}.png` });
  await ctx.close();
};

/* The Quick tab's whole point is type it, LOOK at it, print it, so the
 * picture has to be on the screen you are typing on. It was at y=899 of a
 * 780px phone, under 510px of form. */
const previewIsOnScreen = async (p, name, height) => {
  const seen = await p.evaluate(() => {
    const image = document.getElementById('quickPreview');
    const box = image.getBoundingClientRect();
    return { on: image.classList.contains('on'), drawn: image.naturalWidth > 0,
             top: box.top, bottom: box.bottom, height: box.height };
  });
  if (!seen.on || !seen.drawn)
    return problems.push(`${name}: no preview rendered, so there is nothing `
      + 'to say is on screen');
  if (seen.bottom > height)
    problems.push(`${name}: the preview ends at y=${seen.bottom.toFixed(0)} of `
      + `${height} — the label you are typing is off the bottom of the screen`);
};

/* Where the design workspace starts, and whether the label got the room the
 * pane can give it. The label's own aspect ratio decides how tall it is
 * drawn — a 2.25 x 1.25 label in a 328px pane is 166px and nothing here can
 * make it taller — so what is asked is that it is WIDTH-limited: nothing
 * above it is taking size away from it. */
const canvasBudget = async (p, name, height) => {
  const seen = await p.evaluate(() => {
    const pane = document.querySelector('.canvas-scroll');
    const canvas = document.getElementById('canvas');
    const paneBox = pane.getBoundingClientRect();
    const box = canvas.getBoundingClientRect();
    return { paneTop: paneBox.top, paneH: paneBox.height, bottom: box.bottom,
             width: box.width, avail: pane.clientWidth - 28 };
  });
  if (seen.paneTop > CANVAS_TOP_MAX)
    problems.push(`${name}: the design canvas starts at y=`
      + `${seen.paneTop.toFixed(0)} (budget ${CANVAS_TOP_MAX})`);
  if (seen.bottom > height)
    problems.push(`${name}: the label being designed ends at y=`
      + `${seen.bottom.toFixed(0)} of ${height} — off the first screen`);
  if (seen.width < seen.avail - 2)
    problems.push(`${name}: the canvas is ${seen.width.toFixed(0)}px wide in a `
      + `pane that offers ${seen.avail.toFixed(0)}px`);
};

await run(1440, 900, 'wide-quick', false, async (p) => {
  await p.fill('#quickText', 'Chest freezer — chili');
  await p.waitForTimeout(600);
  /* The desktop keeps its own shapes. The phone drops the wordmark because
   * Home Assistant's header says the same words one row above it, and folds
   * three status chips into one because they are one control drawn as
   * three — neither is an improvement at 1440px, where the room is not the
   * scarce thing, and a fix that quietly took the wide layout with it would
   * be a phone-only panel. */
  const wide = await p.evaluate(() => {
    const shown = (id) => {
      const node = document.getElementById(id) || document.querySelector(id);
      return !!node && node.getBoundingClientRect().height > 0;
    };
    return { wordmark: shown('.wordmark'), one: shown('statusChip'),
             printer: shown('printerChip'), left: shown('rollLeft') };
  });
  if (!wide.wordmark) problems.push('wide-quick: the wordmark is gone at 1440px');
  if (!wide.printer || !wide.left)
    problems.push('wide-quick: the three status chips are gone at 1440px');
  if (wide.one)
    problems.push('wide-quick: the phone’s one-chip status is rendered at '
      + '1440px as well — that is four chips answering one question');
  await checkFontPicker(p, 'wide-quick');
});
await run(1100, 820, 'laptop-design-dark', false, async (p) => {
  await p.click('[data-view="design"]'); await p.waitForTimeout(500);
  await p.click('#addBar button:nth-child(1)');
  await p.waitForTimeout(700);
  await dragToTheEdge(p, 'laptop-design-dark');
  await checkTurnedCanvas(p, 'laptop-design-dark');
});
await run(820, 900, 'tablet-printer', true, (p) => p.click('[data-view="printer"]'));
/* The Printer tab at a phone's width, which nothing measured until now — and
 * it was scrolling sideways there (413px of page in a 390px window) because
 * a <select> laid out to its widest option set the min-content of the row
 * holding it, so the row's own `max-width: 100%` resolved against a width
 * the select had caused. The same bug the design bar's stock picker had, on
 * the one tab no run visited narrow. */
await run(PHONE.w, PHONE.h, 'phone-printer', true, async (p) => {
  await p.click('[data-view="printer"]');
  await p.waitForTimeout(700);
  await phoneBudget(p, 'phone-printer');
  /* "Where the printing starts" is the fourth button on the printer card,
   * and the card's foot is the narrowest row on this tab. A control added
   * to it is a control nobody has measured at 390px until it is measured
   * here — which is exactly how a 413px page in a 390px window survived a
   * release. Its dialog is where the two offsets are typed, so the boxes
   * and the calibration print are checked in the same open. */
  await reachable(p, 'phone-printer', async () => {}, ['printOffset']);
  await reachable(p, 'phone-printer', () => p.click('#printOffset'),
    ['offsetStock', 'offsetFeed', 'offsetAcross', 'offsetMedia', 'offsetGap',
     'offsetHeadScale', 'offsetCalibrate', 'offsetSave']);
  /* Signed, so it must not carry a `min` that the browser will refuse a
   * minus against — the whole measured case is a negative feed offset. */
  const signed = await p.evaluate(() => ['offsetFeed', 'offsetAcross']
    .filter((id) => document.getElementById(id).min !== ''));
  for (const id of signed)
    problems.push(`phone-printer: #${id} has a min, so the negative offset `
      + 'this control exists for cannot be typed into it');
  await p.keyboard.press('Escape');
  await p.waitForTimeout(300);
});
await run(PHONE.w, PHONE.h, 'phone-quick', true, async (p) => {
  await p.fill('#quickText', 'Spare keys');
  await p.waitForTimeout(900);
  await previewIsOnScreen(p, 'phone-quick', PHONE.h);
  await phoneBudget(p, 'phone-quick');
  /* Everything the reorder moved below the preview. A disclosure is one
   * press; a control that is not in the page is gone. */
  await reachable(p, 'phone-quick', () => p.click('#quickMore summary'),
    ['quickStock', 'quickCopies', 'quickFont', 'quickUpper',
     'quickToDesign', 'quickToTemplate']);
  /* Still open from the check above, which is where the font picker lives
   * on a phone. */
  await checkFontPicker(p, 'phone-quick');
  await p.click('#quickMore summary');
  await p.waitForTimeout(200);
});
await run(PHONE.w, PHONE.h, 'phone-design', true, async (p) => {
  await p.click('[data-view="design"]'); await p.waitForTimeout(500);
  await p.click('#addBar button:nth-child(3)');
  await p.waitForTimeout(900);
  await canvasBudget(p, 'phone-design', PHONE.h);
  await phoneBudget(p, 'phone-design');
  /* Stock, name, the text-direction sentence and the snap toggle all left
   * the design bar for the ⋯ sheet, and Rotate went to the props pane where
   * every other per-box control already lives. */
  await reachable(p, 'phone-design', () => p.click('#designMore'),
    ['designStock', 'designName', 'designSnap']);
  await p.click('#designSheetDone');
  await p.waitForTimeout(300);
  await reachable(p, 'phone-design', async () => {}, ['designRotateEl']);
  await dragToTheEdge(p, 'phone-design');
});
await b.close();
if (problems.length) { console.error('FAILED:\n- ' + problems.join('\n- ')); process.exit(1); }
console.log('measure-panel: clean at every width');
