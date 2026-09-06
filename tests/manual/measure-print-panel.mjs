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
  /* The four knobs, and the two buttons that served them. They are not
     hidden, they are gone: a correction somebody guesses is a guess whatever
     it is called, and every one of these was a box to type a millimetre
     into. What replaced them is one button per bay that prints. */
  for (const gone of ['printOffset', 'offsetStock', 'offsetFeed',
                      'offsetAcross', 'offsetMedia', 'offsetGap',
                      'offsetHeadScale', 'offsetCalibrate', 'offsetSave'])
    if (document.getElementById(gone))
      out.push(`#${gone} is back — the offsets were replaced by Line up this `
        + 'roll, not moved');
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
  /* The canvas IS the printable area, so there is no rectangle drawn
     inside it any more and nothing on it to aim away from — what has to be
     true instead is that the picture and the overlay share an origin. The
     overlay's millimetres have always been the canvas's; the image under
     them used to be the whole sheet, and every box was offset by the stock's
     margin in code to compensate. If that offset were still there, an
     element at 0,0 would draw a margin's width in from the corner. */
  const originGap = await p.evaluate(() => {
    const image = document.getElementById('designPreview');
    const first = document.querySelector('#overlay .el');
    if (!image || !first) return null;
    const a = image.getBoundingClientRect();
    const b = first.getBoundingClientRect();
    const s = window.__bruhPrintState;
    const el = s && s.label && s.label.elements[0];
    if (!el) return null;
    const perMm = a.width / (s.stocks.find((r) => r.id === s.label.stock)
      .drawable_mm[(s.label.rotate === 90 || s.label.rotate === 270) ? 1 : 0]);
    return { drawn: b.x - a.x, want: el.x_mm * perMm, perMm };
  });
  if (!originGap)
    problems.push(`${name}: no element box to measure the overlay against`);
  else if (Math.abs(originGap.drawn - originGap.want) > 2)
    problems.push(`${name}: the overlay is offset from the picture by `
      + `${(originGap.drawn - originGap.want).toFixed(1)}px — the box being `
      + 'dragged and the ink it describes are in different places');

  /* And the caption says how big that canvas is, which is the one fact the
     tab cannot show any other way now the marks are gone. */
  const legend = await p.$eval('#canvasLegend', (n) => n.textContent.trim())
    .catch(() => '');
  if (!/Drawing on [\d.]+ × [\d.]+mm/.test(legend))
    problems.push(`${name}: the canvas caption does not say how big it is `
      + `("${legend.slice(0, 60)}")`);

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
/* The design bar's picker is a button and a dialog, not a <select>, so
 * `selectOption` has nothing to drive. Two presses, through the real
 * control — which is also what makes this a test OF the control rather than
 * of `S.label.stock`. */
const pickStock = async (p, id) => {
  await p.click('#designStock');
  await p.waitForTimeout(300);
  await p.click(`#modalBody .stockrow:nth-child(${id === 'ed1f-060wh' ? 2 : 1})`);
  await p.waitForTimeout(300);
};

const checkTurnedCanvas = async (p, name) => {
  /* Switched on the design bar. It went into the ⋯ sheet when the bar was
   * five rows tall, and came back when the person using it pointed out that
   * which label you are drawing on is the paper rather than a setting —
   * driven here rather than clicked through the sheet, because a run that
   * still opened the sheet would pass whichever place the control was in. */
  await pickStock(p, 'ed1f-060wh');
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

/* ── Lining a roll up, driven ──────────────────────────────────────────
 *
 * The whole of 0.9.0 from the panel's side, at the width it is least likely
 * to fit: the wizard is a drawing and five number boxes inside a dialog that
 * is 94vw of a 390px phone. Every failure this replaced was a control nobody
 * had ever measured narrow — a 413px page in a 390px window survived a
 * release on this very tab — and the offset dialog it replaces had SIX
 * boxes, so the arithmetic here is worse rather than better.
 *
 * It drives the real thing end to end because there is no other way to know
 * it works: the demo panel's only stand-in is the USB write, so the print
 * goes through the real renderer and the readings through the real
 * derivation. A test that stubbed either would be a test of the stub.
 */
const lineUpWizard = async (p, name, width) => {
  /* Forgotten first, so the run starts from the same place whether or not
     the demo's /data has been wiped since the last one. It is also the only
     drive Forget gets, and it is the press that has to leave a roll printing
     byte-for-byte what the add-on shipped with. */
  const forget = await p.$('#forgetCal-left');
  if (forget) { await forget.click(); await p.waitForTimeout(700); }
  const state = await p.$('#bays .calstate');
  if (!state)
    return problems.push(`${name}: the bay says nothing about whether this `
      + 'roll has been lined up');
  const before = (await state.textContent()).trim();
  if (!/not lined up/i.test(before))
    problems.push(`${name}: Forget left the bay saying "${before}"`);

  /* Looked up AFTER the Forget, which re-renders every bay: a handle taken
     before it is a node that is no longer in the page. */
  const bay = await p.$('#lineUp-left');
  if (!bay) return problems.push(`${name}: no "Line up this roll" on the left bay`);
  await bay.click();
  await p.waitForTimeout(400);
  /* Asked rather than clicked into. A `page.click` on a control that is not
     there is thirty seconds of timeout and a stack trace, which reads as a
     flaky selector — the same failure this script's own header is about. */
  const print = await p.$('#lineUp[data-step="print"] #lineUpPrint');
  if (!print) return problems.push(`${name}: step 1 did not render`);
  await print.click();
  await p.waitForTimeout(900);

  /* Step 2: the drawing and the five boxes, all of them on a screen 390px
   * wide. `fit` is measured against the VIEWPORT rather than against the
   * dialog, because a dialog that overflows the screen is the same failure
   * as a page that does. */
  const step = await p.$('#lineUp[data-step="read"]');
  if (!step) return problems.push(`${name}: step 2 did not render after Print`);
  const shape = await p.evaluate((w) => {
    const out = [];
    const wrap = document.getElementById('lineUp');
    for (const node of wrap.querySelectorAll('*')) {
      const box = node.getBoundingClientRect();
      if (!box.width) continue;
      if (box.right > w + 1 || box.left < -1)
        out.push(`${node.id || node.className || node.tagName} runs to `
          + `${box.right.toFixed(0)}px of ${w}`);
    }
    const svg = document.getElementById('calSvg');
    if (!svg) out.push('there is no drawing on the reading step');
    else if (svg.getBoundingClientRect().height < 60)
      out.push('the drawing is drawn but has no height');
    for (const letter of ['X1', 'X2', 'Y1', 'Y2']) {
      const input = document.getElementById(`cal${letter}`);
      if (!input) { out.push(`reading ${letter} has no box`); continue; }
      const box = input.getBoundingClientRect();
      if (box.height < 44)
        out.push(`#cal${letter} is ${box.height.toFixed(0)}px tall`);
      if (parseFloat(getComputedStyle(input).fontSize) < 16)
        out.push(`#cal${letter} is under 16px — iOS will zoom in and stay there`);
      /* The badge on the box is what ties it to the badge on the drawing.
         Without it the picture names five points and the form names five
         boxes, and nothing joins them. */
      if (!input.closest('.calfield').querySelector('.calbadge'))
        out.push(`#cal${letter} has no badge, so the drawing points at nothing`);
    }
    if (document.documentElement.scrollWidth > w + 1)
      out.push(`the page scrolls sideways with the wizard open `
        + `(${document.documentElement.scrollWidth} > ${w})`);
    return out;
  }, width);
  for (const bad of shape) problems.push(`${name}: ${bad}`);

  /* The owner's own roll, as coordinates on the grid: the label's top edge
     is above the grid — the printer starts 4.7mm after the die cut, so
     there is no scale up there to read — which is Y1 = 0, and its bottom
     edge falls at 27 of a 31.75mm label. That is the same 4.7mm, derived
     rather than asked for. X2 is blank on purpose: a label wider than the
     print head has nothing printed at its right edge, and an empty box has
     to reach the server as null rather than as the zero `Number('')` would
     make it. */
  const apply = await p.$('#calApply');
  const boxes = await Promise.all(
    ['calX1', 'calY1', 'calY2'].map((id) => p.$(`#${id}`)));
  if (!apply || boxes.some((box) => !box))
    return problems.push(`${name}: the reading step is missing a box or the `
      + 'Apply, so there is nothing to drive');
  for (const [box, value] of [[boxes[0], '0'], [boxes[1], '0'],
                              [boxes[2], '27']])
    await box.fill(value);
  await apply.click();
  await p.waitForTimeout(1200);

  const done = await p.evaluate(() => {
    const wrap = document.getElementById('lineUp');
    const sentence = wrap && wrap.querySelector('.calsentence');
    return { step: wrap && wrap.dataset.step,
             sentence: sentence ? sentence.textContent.trim() : '',
             check: !!document.getElementById('calCheck') };
  });
  if (done.step !== 'done')
    problems.push(`${name}: Apply left the wizard on "${done.step}"`);
  if (!done.sentence)
    problems.push(`${name}: nothing said what the readings meant`);
  /* And it has to be the RIGHT answer: Y1 = 0 with Y2 = 27 on a 31.75mm
     label is a 4.75mm dead zone, which is the owner's own roll read to the
     whole millimetre a printed scale actually offers — 4.8 to the one
     decimal place every sentence here uses. A wizard that stored something
     else would still render a sentence. */
  else if (!/can.t put ink on the first 4\.8mm/i.test(done.sentence))
    problems.push(`${name}: the owner's readings did not derive a 4.8mm dead `
      + `zone ("${done.sentence.slice(0, 90)}")`);
  if (!done.check)
    problems.push(`${name}: no check label to print, which is the only way `
      + 'to see whether the answer was right');

  /* Back to the numbers from the end of the wizard, which is the half of
     the loop that did not exist: every ending used to be Close, so a check
     label that came back short of an edge meant closing the dialog, finding
     the bay and starting again from an empty form. */
  const back = await p.$('#calBack');
  if (!back) problems.push(`${name}: the wizard ends with no way back to the `
    + 'numbers, so a wrong reading is a fresh start');
  else {
    await back.click();
    await p.waitForTimeout(500);
    const kept = await p.evaluate(() => {
      const wrap = document.getElementById('lineUp');
      const value = (id) => {
        const node = document.getElementById(id);
        return node ? node.value : null;
      };
      return { step: wrap && wrap.dataset.step,
               y2: value('calY2'), y1: value('calY1'),
               again: !!document.getElementById('calPrintAgain'),
               check: !!document.getElementById('calCheckHere'),
               holds: ['Leading', 'Trailing', 'Left', 'Right']
                 .map((side) => value('calHold' + side)) };
    });
    if (kept.step !== 'read')
      problems.push(`${name}: "Change the numbers" left the wizard on `
        + `"${kept.step}"`);
    /* Filled in from what is STORED, which is the whole complaint: an empty
       form makes a small adjustment a re-measurement. Y1 is 0 and Y2 is
       27 — the readings that produced the answer in force. */
    if (kept.y1 !== '0' || kept.y2 !== '27')
      problems.push(`${name}: the readings came back as Y1=${kept.y1} `
        + `Y2=${kept.y2}, not the 0 and 27 that produced the stored answer`);
    /* And both prints are on that step, which is what makes it a loop. */
    if (!kept.again)
      problems.push(`${name}: no way to print the grid again without closing `
        + 'the wizard');
    if (!kept.check)
      problems.push(`${name}: a lined-up roll is offered no check label from `
        + 'the step that reads it');
    /* One box per edge, and their ids are built from the side key rather
       than written down — so this is the only place they can be checked at
       all. A grep in the Python suite can see the table; only a rendered
       form can see the four inputs it produced. */
    if (kept.holds.some((v) => v === null))
      problems.push(`${name}: the area to print on has boxes for `
        + `${kept.holds.filter((v) => v !== null).length} of its four edges`);

    /* Then type all four, apply, and read the stored bands back. This is
       the thing that was refused — an area smaller than the one the printer
       can reach — so a run that only checked the boxes existed would pass
       on four fields that stored nothing, or on four that all wrote the
       same one. */
    const apply2 = await p.$('#calApply');
    const want = { Leading: 1.5, Trailing: 4.8, Left: 3.0, Right: 2.0 };
    if (apply2 && !kept.holds.some((v) => v === null)) {
      for (const [side, value] of Object.entries(want))
        await (await p.$('#calHold' + side)).fill(String(value));
      await apply2.click();
      await p.waitForTimeout(1200);
      const held = await p.evaluate(() => {
        const s = window.__bruhPrintState;
        const row = (s?.stocks || []).find((x) => x.id === 'edcc-082wh');
        return row ? { holds: row.holds_mm, dead: row.dead_leading_mm,
                       printable: row.printable_feed_mm, feed: row.feed_mm,
                       across: row.printable_across_mm,
                       label: row.across_mm }
                   : null;
      });
      if (!held) problems.push(`${name}: the stock row vanished after Apply`);
      else {
        const got = held.holds || [];
        const expect = [want.Leading, want.Trailing, want.Left, want.Right];
        expect.forEach((value, index) => {
          if (Math.abs((got[index] ?? -1) - value) > 0.11)
            problems.push(`${name}: asked for ${value}mm at `
              + `${['the top', 'the bottom', 'the left', 'the right'][index]} `
              + `and the roll holds ${got[index]}`);
        });
        /* And each comes off its own axis. The feed axis loses the dead
           band, the two feed holds and the stock's 2mm border either end;
           the across axis loses the two across holds and the same border,
           and nothing else — a band subtracted from the wrong edge is
           invisible until somebody prints one. */
        const feed = held.feed - held.dead - want.Leading - want.Trailing - 4;
        if (Math.abs(held.printable - feed) > 0.11)
          problems.push(`${name}: the printable length is ${held.printable}mm `
            + `where the four insets down the label leave ${feed.toFixed(2)}`);
        const across = held.label - want.Left - want.Right - 4;
        if (Math.abs(held.across - across) > 0.11)
          problems.push(`${name}: the printable width is ${held.across}mm `
            + `where the bands across the label leave ${across.toFixed(2)}`);
      }

      /* And the one press that does arithmetic on those bands. The top of a
         label loses the printer's own dead band AND anything held at the
         top; the bottom loses only what is held there — so evening them up
         is an addition, and a button that typed the dead band alone would
         leave them uneven on exactly the roll somebody had set a top band
         on. Driven rather than read, because both halves are numbers this
         script must not compute for itself: what is asserted is that the
         two blank edges of the stored box come out the same. */
      const even = await p.$('#calEven');
      if (!even)
        problems.push(`${name}: a roll whose ends do not match is offered no `
          + 'way to even them up');
      else {
        await even.click();
        await p.waitForTimeout(1400);
        const box = await p.evaluate(() => {
          const s = window.__bruhPrintState;
          const row = (s?.stocks || []).find((x) => x.id === 'edcc-082wh');
          if (!row) return null;
          return { feed: row.feed_mm, printable: row.printable_feed_mm,
                   dead: row.dead_leading_mm, holds: row.holds_mm };
        });
        if (!box) problems.push(`${name}: the stock row vanished after Even`);
        else {
          const above = 2 + box.dead + box.holds[0];
          const below = box.feed - box.printable - above;
          if (Math.abs(above - below) > 0.11)
            problems.push(`${name}: the blank edges still do not match — `
              + `${above.toFixed(2)}mm above, ${below.toFixed(2)}mm below`);
        }
      }
    }
  }

  const close = await p.$('#lineUpClose');
  if (!close) return problems.push(`${name}: the wizard has no way out but Escape`);
  await close.click();
  await p.waitForTimeout(700);
  const after = await p.$eval('#bays .calstate', (n) => n.textContent.trim());
  if (after === before)
    problems.push(`${name}: the bay still says "${after}" after a roll was `
      + 'lined up');
  if (!/lined up/i.test(after))
    problems.push(`${name}: the bay does not say the roll is lined up `
      + `("${after}")`);
  if (!/4\.8 mm in/.test(after))
    problems.push(`${name}: the bay does not name the dead zone that was `
      + `just measured ("${after}")`);
  /* And it names every edge that is held, in the person's own words. A
     sentence that reported only one of four would be a roll reading back
     less than it is doing. */
  for (const edge of ['top', 'bottom', 'left', 'right'])
    if (!new RegExp(`at the ${edge}`).test(after))
      problems.push(`${name}: the bay does not say what is held at the `
        + `${edge} ("${after}")`);
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
/* Where the design workspace starts.
 *
 * 300 rather than 280 since the design bar gained the label picker. At 390px
 * the bar's three controls want 428px of a 362px row, so it wraps to two —
 * measured at 306 with an element on the label and the label itself
 * ending at y=497 of 780, against 266 and 457 before. The 40px is bought deliberately: the alternative was the
 * add strip absorbing the whole difference, which took it to 32px with its
 * own buttons laid out underneath the picker. Both numbers are a long way
 * from the failure this budget exists for, which was a canvas starting at
 * y=590 with 166px of height left. */
const CANVAS_TOP_MAX = 315;

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

/* The one thing that put the stock picker in the sheet in the first place.
 *
 * `width: auto` sizes a <select> to its WIDEST OPTION, and the stock names
 * run to "2.25" × 1.25" — Chemical-Resistant Cryo Labels". Uncapped, that
 * laid out 431px inside a 390px window and took the page with it — so the
 * cap is the price of having the control on the bar, and this is what
 * proves it is being paid. The row it sits in is measured too: a flex
 * item's floor is its max-content, so a capped select inside an uncapped
 * label is the same bug one element out. */
const designStockFits = async (p, name, width) => {
  const out = await p.evaluate((w) => {
    const bad = [];
    const pick = document.getElementById('designStock');
    if (!pick) return ['#designStock is not in the page'];
    const bar = document.querySelector('.design-bar');
    for (const [what, node] of [['the picker', pick],
                                ['the design bar', bar]]) {
      const box = node.getBoundingClientRect();
      if (box.right > w + 1 || box.left < -1)
        bad.push(`${what} runs from ${box.left.toFixed(0)} to `
          + `${box.right.toFixed(0)}px of ${w}`);
    }
    if (document.documentElement.scrollWidth > w + 1)
      bad.push('the design tab scrolls sideways with the picker on the bar '
        + `(${document.documentElement.scrollWidth} > ${w})`);
    /* The measurement that sent the <select> away, kept as the check.
     * The add strip is the PRIMARY control on this tab and it is what gives
     * way in the row, so a picker beside it has to leave it something to
     * scroll — at 15px its own buttons rendered underneath the picker and a
     * click on one timed out on a control that was there and covered. */
    const strip = document.getElementById('addBar').getBoundingClientRect();
    if (strip.width < 120)
      bad.push(`the add strip is down to ${strip.width.toFixed(0)}px, so the `
        + 'primary control on this tab is a sliver');
    /* The FIRST button has to be inside the strip and reachable. Deliberately
     * only the first: the strip scrolls, so every button past its right edge
     * is laid out beyond it and covered by the page at every width — that is
     * what a scroller does, and a check that read it as a fault would fail on
     * a healthy 340px strip exactly as loudly as on the broken 32px one. The
     * width floor above is what separates them; this is what proves the
     * strip's own content starts inside it. */
    const first = document.querySelector('#addBar .btn');
    if (first) {
      const box = first.getBoundingClientRect();
      if (box.right > strip.right + 1)
        bad.push('the first add button does not fit inside the strip');
      else {
        const on = document.elementFromPoint(box.left + box.width / 2,
                                             box.top + box.height / 2);
        if (on && !on.closest('#addBar'))
          bad.push('the first add button is covered by '
            + `${on.id || on.className || on.tagName}`);
      }
    }
    return bad;
  }, width);
  for (const bad of out) problems.push(`${name}: ${bad}`);
};

const phoneBudget = async (p, name) => {
  /* Persistent chrome is measured SCROLLED, because that is the only state
   * in which "persistent" means anything: the bar is sticky with a negative
   * top, so what is left pinned is the tab strip and nothing else.
   *
   * But the NUMBER comes from the geometry rather than from where the page
   * happened to stop, and that distinction cost a real debugging session.
   * A page has to be a screenful taller than its own chrome before it can
   * scroll the status row all the way off, and a tab whose content got
   * SHORTER — which is a good thing — stops half way and reads as chrome
   * that would not pin. Measured off `tabs.bottom` this run reported 134px
   * against a 110px budget on a bar that had not moved at all since the run
   * before, because a note had been deleted from the page beneath it.
   *
   * The bar is `position: sticky; top: -(status row)`, so what stays is its
   * own height less that row, whatever is under it. The scroll is still
   * driven, and what it is asked is the question it can actually answer:
   * the tabs are still there afterwards. */
  await p.evaluate(() => scrollTo(0, 4000));
  await p.waitForTimeout(400);
  const pinned = await p.evaluate(() => {
    const tabs = document.querySelector('.tabs').getBoundingClientRect();
    const bar = document.querySelector('.topbar');
    const style = getComputedStyle(bar);
    return { bottom: tabs.bottom, top: tabs.top,
             stays: bar.getBoundingClientRect().height
                    + parseFloat(style.top || '0'),
             scrolled: window.scrollY };
  });
  if (pinned.stays > CHROME_PINNED_MAX)
    problems.push(`${name}: ${pinned.stays.toFixed(0)}px of chrome stays `
      + `pinned (budget ${CHROME_PINNED_MAX})`);
  if (pinned.scrolled > 4) {
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
  await lineUpWizard(p, 'phone-printer', PHONE.w);
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
  /* The stock picker is on the bar and has to be usable there at 390px —
   * which is the whole risk of putting it back, because a <select> sized to
   * its widest option is what took the page sideways the first time. */
  await reachable(p, 'phone-design', async () => {}, ['designStock']);
  await designStockFits(p, 'phone-design', PHONE.w);
  /* Name, the text-direction sentence and the snap toggle stayed in the ⋯
   * sheet, and Rotate went to the props pane where every other per-box
   * control already lives. */
  await reachable(p, 'phone-design', () => p.click('#designMore'),
    ['designName', 'designSnap']);
  await p.click('#designSheetDone');
  await p.waitForTimeout(300);
  await reachable(p, 'phone-design', async () => {}, ['designRotateEl']);
  await dragToTheEdge(p, 'phone-design');
});
await b.close();
if (problems.length) { console.error('FAILED:\n- ' + problems.join('\n- ')); process.exit(1); }
console.log('measure-panel: clean at every width');
