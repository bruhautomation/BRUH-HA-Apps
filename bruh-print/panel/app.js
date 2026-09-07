/* BRUH Print — the panel.
 *
 * Three things in here are worth knowing before changing anything.
 *
 * The designer NEVER invents a value it was not given. An editor that
 * quietly rewrites what it opens is one people stop trusting: opening a
 * label, changing nothing and pressing Print has to produce byte-identical
 * JSON. So element props are only written when the control that owns them
 * was actually touched, and the element catalog's own defaults come from the
 * server rather than from a second copy of them here.
 *
 * Every preview is the SERVER's render. There is no canvas drawing of what a
 * label might look like — the overlay is boxes for dragging, and the picture
 * under it is a PNG from the same renderer that packs the printer's bytes. A
 * preview drawn here would be a preview of this file's idea of the label.
 *
 * And storage access goes through prefGet/prefSet, because a browser may
 * refuse an iframe its localStorage and a throw at the top level takes out
 * every handler declared below it.
 */
'use strict';

/* A flag the layout measure looks for. app.js failing to load leaves a page
 * that still renders — unstyled, with every view stacked — and every
 * subsequent click timing out on a control that was never built, which
 * reads as a flaky selector rather than as "the panel did not load". */
window.__bruhPrintReady = true;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const prefGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
const prefSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* refused */ } };

/* ── State ──────────────────────────────────────────────────────────── */
const S = {
  stocks: [], rolls: [], templates: [], fonts: [], settings: {},
  catalog: { elements: {}, rotations: [0, 90, 180, 270] },
  printer: null, printers: [], history: [],
  label: null, selected: -1, template: null, dirty: false,
  problems: [],
};

/* Read-only, and only so the layout measure can ask what the label actually
 * became after it dragged something. Geometry is what a browser can see; the
 * millimetres behind it are not, and a measure that re-derived them from
 * pixels would be measuring its own arithmetic. */
window.__bruhPrintState = S;

/* ── Fetch ──────────────────────────────────────────────────────────── */
/* The leading slash is stripped so every request resolves against the page's
 * own base. Ingress serves this panel under /api/hassio_ingress/<token>/, so
 * an absolute "/api/state" is a request to Home Assistant's own root — which
 * is what shipped, and why the panel loaded as unstyled HTML with every view
 * stacked: style.css and app.js 404'd the same way. Same helper brAIn's
 * `api()` has, for the same reason. */
const relative = (path) => String(path).replace(/^\//, "");

async function api(path, options = {}) {
  const response = await fetch(relative(path), {
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    ...options,
  });
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) {
    if (!response.ok) throw new Error(`${path} answered ${response.status}`);
    return response;
  }
  const data = await response.json();
  /* The server's own sentence, never the status code. "panel answered HTTP
   * 409" is what a person reads when the body said which roll holds what. */
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || `${path} answered ${response.status}`);
    error.payload = data;
    throw error;
  }
  return data;
}

const post = (path, payload) => api(path, { method: 'POST', body: JSON.stringify(payload || {}) });
const del = (path) => api(path, { method: 'DELETE' });

/* ── Toast ──────────────────────────────────────────────────────────── */
let toastTimer = 0;
function toast(message, kind, action) {
  const box = $('toast'), button = $('toastAction');
  $('toastText').textContent = message;
  box.className = 'toast' + (kind ? ' ' + kind : '');
  box.hidden = false;
  button.hidden = !action;
  if (action) {
    button.textContent = action.label;
    button.onclick = () => { box.hidden = true; action.run(); };
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, action ? 9000 : 4500);
}
const fail = (error) => toast(error.message || String(error), 'bad');

/* ── Tooltips ───────────────────────────────────────────────────────── */
/* One shared fixed box, measured and clamped — CSS cannot see the viewport
 * edge, and an absolutely positioned bubble hanging off a control near the
 * left margin is a tooltip that is simply not there. */
let tipTimer = 0;
function showTip(target) {
  const text = target.getAttribute('data-tip');
  if (!text) return;
  const box = $('tipbox');
  box.textContent = text;
  box.hidden = false;
  const rect = target.getBoundingClientRect();
  const size = box.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - size.width / 2;
  left = Math.max(8, Math.min(left, innerWidth - size.width - 8));
  let top = rect.bottom + 8;
  if (top + size.height > innerHeight - 8) top = rect.top - size.height - 8;
  box.style.left = left + 'px';
  box.style.top = Math.max(8, top) + 'px';
}
const hideTip = () => { $('tipbox').hidden = true; };
const dismissTip = () => { clearTimeout(tipTimer); hideTip(); };

document.addEventListener('pointerover', (event) => {
  const target = event.target.closest('[data-tip]');
  if (!target) return;
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => showTip(target), 150);
});
document.addEventListener('pointerout', dismissTip);
/* dismiss, not hide: a tooltip still inside its open delay is measured when
 * it opens — after the scroll — so cancelling the pending one is what stops
 * a tooltip vanishing for good when the page settles a scroll. */
addEventListener('scroll', dismissTip, true);

/* ── Views ──────────────────────────────────────────────────────────── */
function show(view) {
  document.querySelectorAll('.view').forEach((node) =>
    node.classList.toggle('is-on', node.id === 'view' + view[0].toUpperCase() + view.slice(1)));
  document.querySelectorAll('.tab').forEach((node) =>
    node.classList.toggle('is-on', node.dataset.view === view));
  prefSet('bruhprint.view', view);
  if (view === 'design') renderDesign();
  if (view === 'printer') renderPrinter();
  if (view === 'history') renderHistory();
  if (view === 'templates') renderTemplates();
}
$('tabs').addEventListener('click', (event) => {
  const tab = event.target.closest('.tab');
  if (tab) show(tab.dataset.view);
});

/* ── State load ─────────────────────────────────────────────────────── */
async function loadState() {
  const data = await api('/api/state');
  Object.assign(S, {
    stocks: data.stocks, rolls: data.rolls, templates: data.templates,
    fonts: data.fonts, settings: data.settings, catalog: data.catalog,
    printer: data.printer, printers: data.printers, history: data.history,
  });
  S.printerError = data.printer_error;
  S.ambiguous = data.ambiguous;
  renderBar();
  fillPickers();
  return data;
}

const stockById = (id) => S.stocks.find((s) => s.id === id) || null;

/* How tall the status row is, published to the stylesheet.
 *
 * Below 1100px the bar is `position: sticky` with a NEGATIVE top of exactly
 * this height, which is what lets the wordmark-and-status row scroll away
 * while the tab strip pins: navigation deserves to be permanent and a status
 * readout does not. It has to be measured rather than assumed, because
 * whether the chips wrapped is a function of the width and of what is in
 * them — and a value larger than the row's real height would take the tabs
 * off the top of the screen with it, which is the one failure mode here. */
function syncBarHeight() {
  const bar = document.querySelector('.bar-main');
  if (!bar) return;
  document.documentElement.style.setProperty(
    '--barmain-h', Math.round(bar.getBoundingClientRect().height) + 'px');
}
addEventListener('resize', syncBarHeight);

function renderBar() {
  const dot = $('printerDot'), name = $('printerName');
  if (S.printer) {
    dot.className = 'dot good';
    name.textContent = S.printer.name.replace(/^LabelWriter /, 'LW ');
  } else if (S.ambiguous) {
    dot.className = 'dot warn';
    name.textContent = `${S.printers.length} printers — pick one`;
  } else {
    dot.className = 'dot bad';
    name.textContent = 'No printer';
  }
  for (const roll of S.rolls) {
    const chip = $('roll' + roll.side[0].toUpperCase() + roll.side.slice(1));
    const stock = stockById(roll.stock);
    chip.innerHTML = '';
    chip.append(el('span', 'side', roll.side === 'left' ? 'L' : 'R'));
    /* The SIZE, not the name. "Chemical-Resistant Cryo Labels" is 240px of
     * bar on a phone and it is not the fact being checked — standing at the
     * printer you are asking "is the big one in the left bay", which the
     * measurements answer and the name does not. The name is in the tooltip
     * and on the Printer tab, so nothing is hidden, it is a shorter complete
     * label rather than a truncated long one. */
    chip.append(el('span', null, stock ? stock.label : 'empty'));
    chip.classList.toggle('empty', !roll.loaded);
    chip.setAttribute('data-tip', stock
      ? `${roll.side} roll: ${stock.name} ${stock.label}. About ${roll.remaining} left. Press to change.`
      : `BRUH Print does not know what is in the ${roll.side} roll. Press to say.`);
    /* A single-roll printer has one bay, and a chip offering a choice that
     * does not exist is a control that lies. */
    chip.hidden = roll.side === 'right' && !!S.printer && !S.printer.twin;
  }
  renderOneChip();
  syncBarHeight();
}

/* The phone's status chip: one control, because all three were one control
 * drawn as three — every one of them presses through to the Printer tab.
 * What it carries is what you check standing at the printer: is it there,
 * and what is in the bays. The names are in the tooltip and on the Printer
 * tab, so this is a shorter COMPLETE label rather than a truncated long
 * one — the same trade the three chips already made by showing sizes. */
function renderOneChip() {
  const dot = $('statusDot'), text = $('statusText'), chip = $('statusChip');
  if (!chip) return;
  const twin = !S.printer || S.printer.twin;
  const bays = S.rolls
    .filter((roll) => !(roll.side === 'right' && !twin))
    .map((roll) => {
      const stock = stockById(roll.stock);
      return `${roll.side === 'left' ? 'L' : 'R'} ${stock ? stock.label : 'empty'}`;
    });
  if (S.printer) {
    dot.className = 'dot good';
    text.textContent = bays.join(' \u00b7 ') || S.printer.name;
  } else if (S.ambiguous) {
    dot.className = 'dot warn';
    text.textContent = `${S.printers.length} printers — pick one`;
  } else {
    dot.className = 'dot bad';
    text.textContent = 'No printer';
  }
  const loaded = S.rolls
    .filter((roll) => roll.loaded && stockById(roll.stock))
    .map((roll) => `the ${roll.side} roll holds ${stockById(roll.stock).name} `
      + `${stockById(roll.stock).label}`);
  chip.setAttribute('data-tip',
    (S.printer ? S.printer.name : 'No printer found')
    + (loaded.length ? ` \u2014 ${loaded.join(', ')}` : '')
    + '. Press for the Printer tab.');
}

/* What you can print on: the stock that is actually in the printer.
 *
 * The full catalog is a list of every label BRUH Print has ever heard of,
 * and offering it on the Quick tab means the commonest first action is
 * choosing between fourteen rows of which two are real — then being refused
 * for picking one of the twelve. The catalog belongs on the Printer tab,
 * where the question is "what did I just load"; everywhere else the answer
 * is already known and the picker should only be able to be right.
 *
 * A printer with nothing recorded falls back to the whole catalog rather
 * than to an empty picker: an empty select is a panel that looks broken,
 * and somebody who has not filled the Printer tab in yet still wants to
 * print. */
function loadedStocks() {
  const on = S.stocks.filter((stock) => stock.loaded);
  return on.length ? on : S.stocks;
}

/* How a stock is named in a picker, in one place because there are three of
 * them — the Quick tab's, the design bar's and the Printer tab's bays — and
 * three copies of a join is three chances for two pickers to disagree about
 * what the same roll is called.
 *
 * The NAME leads, and it took shipping the other order to see why.
 *
 * The size led, on the argument that a closed <select> shows the front of
 * its option and two rolls of one brand would truncate to the same string.
 * True of the CATALOG's names, which are what is printed on the box you
 * reorder by — and beside the point, because a person picking a label is
 * not shopping. They are asking *which of my rolls is this*, and once a
 * roll can be renamed (0.13.0) the answer to that is the name they gave it.
 * `2.25" × 1.25"` and `1.0" × 2.0"` are two measurements to compare before
 * you have chosen anything; `Address Labels` and `Removable 3/4" x 2"` are
 * the two rolls. The size is still on every surface, one line down or one
 * press away, which is where a detail belongs. */
const stockOptionText = (stock) => `${stock.name} — ${stock.label}`;

/* The design bar's own picker: a button that says what is loaded and opens
 * a list, the way the font picker already works one control over.
 *
 * It is not a <select> because of a number rather than a preference. A
 * <select> lays out to its widest option, and these run to `2.25" × 1.25" —
 * Chemical-Resistant Cryo Labels`; capped hard enough to fit a 390px row it
 * still took 164px, which with ⋯ beside it left the add strip 15px wide
 * with its own buttons rendering underneath the picker — measured, and the
 * click that found it timed out on a control that was there and covered.
 * What the button shows is the SIZE, which is the half that identifies a
 * roll and the half a truncated <select> would have lost.
 *
 * `dataset.value` rather than `.value`, and the id is unchanged: every
 * reader asks this control which stock is on screen and still does. */
function setStockButton(button, id) {
  if (!button) return;
  const rows = loadedStocks();
  const chosen = rows.find((s) => s.id === id)
    || rows.find((s) => s.id === S.settings.default_stock) || rows[0];
  button.dataset.value = chosen ? chosen.id : '';
  /* The NAME, capped, with the size in the dialog this opens.
   *
   * It said the size, and the measurement that justified that is still
   * true: the design bar is one flex line whose base sizes are its
   * controls' own content, so a picker that grows with its text pushes the
   * add strip onto a row of its own — one row to two at 900px, two to three
   * at 390px. What was wrong was the conclusion. The fix for a control that
   * must not grow is a CAP, not a shorter fact: `.designstock` is capped
   * and the name ellipsises inside it, so a long catalog name loses its
   * tail rather than taking the row, and the caret sits outside the
   * truncation because a picker with no caret is not a picker.
   *
   * `designStockFits` asserts the row count at 390 and at 1100, which is
   * what keeps that cap honest — re-run it rather than reasoning about the
   * number, and note that 900px is the tightest width rather than the
   * narrowest: below it the bar has already given way to two rows. */
  const name = el('span', 'designstockname', chosen ? chosen.name : 'No label');
  button.textContent = '';
  button.append(name, el('span', 'caret', '\u25be'));
  button.title = chosen ? `${chosen.name} — ${chosen.label}` : '';
}

const designStockValue = () => $('designStock').dataset.value || '';

/* One row per stock: what the roll is called, and its size under it.
 *
 * A row has two lines and so does not have to choose, which is what makes
 * this the surface that settles the order for the two that do — the name is
 * the heading because the name is what you are picking, and the size reads
 * as what it is, a fact about the thing named above it. `loadedStocks` is
 * what fills it, so the design tab offers exactly what the Quick tab does:
 * what is in the printer. */
function openStockPicker(current, onPick) {
  const body = $('modalBody');
  body.innerHTML = '';
  body.append(el('h2', null, 'Which label'));
  body.append(el('p', 'lede',
    'What this design is drawn on. It sets the size of the canvas, which '
    + 'way the text runs, and which boxes end up off the edge.'));
  const list = el('div', 'stocklist');
  for (const stock of loadedStocks()) {
    const row = el('button', 'btn stockrow' + (stock.id === current ? ' on' : ''));
    row.append(el('b', null, stock.name));
    row.append(el('span', 'muted', stock.label));
    row.onclick = () => { $('modal').close(); onPick(stock.id); };
    list.append(row);
  }
  if (!list.childElementCount)
    list.append(el('p', 'muted', 'Nothing is recorded as loaded, so there is '
      + 'nothing to choose. The Printer tab is where you say what is in each '
      + 'bay.'));
  body.append(list);
  const actions = el('div', 'actions');
  const close = el('button', 'btn', 'Close');
  close.onclick = () => $('modal').close();
  actions.append(close);
  body.append(actions);
  $('modal').showModal();
}

function fillPickers() {
  const options = (select, keep) => {
    const previous = keep ?? select.value;
    const rows = loadedStocks();
    select.innerHTML = '';
    for (const stock of rows) {
      const option = el('option', null, stockOptionText(stock));
      option.value = stock.id;
      select.append(option);
    }
    if (previous && rows.some((s) => s.id === previous)) select.value = previous;
    else if (rows.some((s) => s.id === S.settings.default_stock))
      select.value = S.settings.default_stock;
    else select.value = (rows[0] || {}).id || '';
  };
  options($('quickStock'), prefGet('bruhprint.stock', null));
  setStockButton($('designStock'), S.label ? S.label.stock : null);

  const quickFont = $('quickFont');
  const keptFont = quickFontValue() || S.settings.default_font;
  setFontButton(quickFont,
    S.fonts.some((f) => f.key === keptFont) ? keptFont : (S.fonts[0] || {}).key);
  updateTurnLines();
  quickSummary();

  if (!$('addBar').childElementCount) buildAddBar();
}

/* ── Which way the text sits ────────────────────────────────────────────
 *
 * ONE setting, and it belongs to the stock. A 0.56 × 3.44 tube wrap reads
 * along the roll and a 2.25 × 1.25 address label reads across it — always,
 * for that stock — so asking per print was asking a question whose answer
 * never changes, in three places (the Quick tab, the design bar and the
 * Printer tab) that could disagree with each other. What is left in the two
 * working views is a SENTENCE saying what will happen; the Printer tab is
 * the one place it is decided. */
const turnWords = (turn) => (Number(turn) === 90 || Number(turn) === 270
  ? 'Text runs along the roll' : 'Text runs across the label');

function updateTurnLines() {
  /* One clause shorter than it was: the preview beside it SHOWS which way
   * the text runs, so the half of this sentence worth keeping is the half
   * that says where to change it. */
  const quick = stockById($('quickStock').value);
  const quickLine = $('quickTurnLine');
  quickLine.textContent = quick
    ? `${turnWords(quick.turn)} — change it on the Printer tab` : '';
  const designLine = $('designTurnLine');
  designLine.textContent = S.label
    ? `${turnWords(S.label.rotate)} — change it on the Printer tab` : '';
  quickSummary();
}

/* ── Font picker ────────────────────────────────────────────────────────
 *
 * A <select> of family names shows you the one thing a font choice is not
 * about. Every sample here is drawn by the SERVER, through the same
 * `_draw_text` the printer's bytes come out of — a CSS font-family preview
 * would be showing the browser's idea of "Monospace" beside a label that
 * prints in DejaVu Sans Mono, which is the failure a preview exists to
 * prevent, moved somewhere new.
 *
 * Nothing is fetched until the dialog opens: one image per font, cached for
 * a day, so the second open costs nothing and the first costs a few
 * kilobytes of 1-bit PNG. */
const fontName = (key) =>
  (S.fonts.find((f) => f.key === key) || {}).name || key || 'Font';
const fontSample = (key, text) => relative(
  `/api/font/${encodeURIComponent(key)}/sample.png`
  + (text ? `?text=${encodeURIComponent(text)}` : ''));

function setFontButton(button, key) {
  if (!button) return;
  button.dataset.value = key || '';
  button.innerHTML = '';
  const image = el('img', 'fsample');
  image.alt = '';
  image.src = fontSample(key, 'Aa Bb 0123');
  button.append(image, el('span', 'fname', fontName(key)));
}

const quickFontValue = () => $('quickFont').dataset.value || '';

function openFontPicker(current, onPick) {
  const body = $('modalBody');
  body.innerHTML = '';
  body.append(el('h2', null, 'Font'));
  body.append(el('p', 'lede',
    'Each line is drawn by the same renderer that packs the printer\u2019s '
    + 'bytes, so what you see is what comes out.'));

  const list = el('div', 'fontlist');
  const rows = [];
  for (const font of S.fonts) {
    const row = el('button', 'fontrow' + (font.key === current ? ' sel' : ''));
    row.type = 'button';
    row.dataset.value = font.key;
    const image = el('img', 'fsample');
    image.alt = '';
    image.src = fontSample(font.key);
    row.append(image, el('span', 'fname', font.name));
    row.onclick = () => { $('modal').close(); onPick(font.key); };
    list.append(row);
    rows.push(row);
  }
  body.append(list);

  const close = el('button', 'btn', 'Cancel');
  close.onclick = () => $('modal').close();
  const actions = el('div', 'actions');
  actions.append(close);
  body.append(actions);

  /* Arrow keys and Enter, because this replaced a <select> and a select is
   * keyboard-navigable. Escape is the <dialog>'s own. */
  let at = Math.max(0, rows.findIndex((r) => r.dataset.value === current));
  list.onkeydown = (event) => {
    const step = event.key === 'ArrowDown' ? 1
      : event.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    at = (at + step + rows.length) % rows.length;
    rows[at].focus();
  };
  $('modal').showModal();
  if (rows[at]) rows[at].focus();
}

$('quickFont').addEventListener('click', () => {
  openFontPicker(quickFontValue(), (key) => {
    setFontButton($('quickFont'), key);
    quickSummary();
    quickPreview();
  });
});

/* ── Quick ──────────────────────────────────────────────────────────── */
/* What is behind the disclosure, said on its own summary line.
 *
 * It keeps the NOUNS, because a closed row reading "2.25" × 1.25" · Sans
 * Bold" answers a question nobody asked and not the one they did, which is
 * where the label picker went. And it carries the two answers the preview
 * above it cannot show: which stock this is going to — that names the roll,
 * so it is the thing you check every time — and how many. The font, the
 * capitals and the direction are all in the picture. */
function quickSummary() {
  /* The nouns, and nothing else.
   *
   * This line is the CLOSED state of a disclosure, so every word in it is
   * paid for on every visit to the tab whether or not anybody wanted it —
   * and the two things it used to add were both answered better one line
   * further down. The stock's name is on the picker inside, and the picture
   * beside it is that label; the leading dead band stopped being a fact
   * about the job at all in 0.12.0, when the canvas became the printable
   * box, so it was describing a correction that no longer moves anybody's
   * artwork. What a summary owes is what is behind the fold. */
  const line = $('quickMoreSummary');
  if (!line) return;
  const copies = Number($('quickCopies').value) || 1;
  line.textContent = copies > 1
    ? `Label, copies, font \u00b7 ${copies} copies`
    : 'Label, copies, font';
}

let quickTimer = 0;
let quickSeq = 0;
function quickPayload(printIt) {
  /* No `rotate`. The server takes the stock's own answer when none is sent,
   * which is the whole point of there being one setting: a quick print
   * cannot disagree with the Printer tab, because it never says. */
  return {
    text: $('quickText').value,
    stock: $('quickStock').value,
    font: quickFontValue(),
    copies: Number($('quickCopies').value) || 1,
    uppercase: $('quickUpper').checked,
    ...(printIt ? { print: true } : { scale: 2 }),
  };
}

async function quickPreview() {
  const text = $('quickText').value.trim();
  const image = $('quickPreview');
  if (!text) {
    image.classList.remove('on');
    $('quickPlaceholder').hidden = false;
    $('quickFit').textContent = '';
    return;
  }
  const seq = ++quickSeq;
  try {
    const data = await post('/api/quick', quickPayload(false));
    /* Out-of-order replies are the ordinary case here: this fires on every
     * keystroke and a longer word renders slower. Dropping a stale reply is
     * what stops the preview flicking back to what you typed two letters
     * ago. */
    if (seq !== quickSeq) return;
    image.src = data.png;
    image.classList.add('on');
    $('quickPlaceholder').hidden = true;
    $('quickFit').textContent =
      `${data.fit.lines.length} line${data.fit.lines.length > 1 ? 's' : ''}, `
      + `${data.fit.size_mm}mm tall`;
    S.label = data.label;
    notes($('quickNotes'), data.notes);
  } catch (error) {
    if (seq !== quickSeq) return;
    notes($('quickNotes'), [error.message]);
  }
}

function notes(list, items) {
  list.innerHTML = '';
  for (const item of items || []) list.append(el('li', null, item));
}

const debouncedQuick = () => { clearTimeout(quickTimer); quickTimer = setTimeout(quickPreview, 260); };
['quickText', 'quickStock', 'quickUpper']
  .forEach((id) => $(id).addEventListener('input', () => {
    if (id === 'quickStock') {
      prefSet('bruhprint.stock', $('quickStock').value);
      updateTurnLines();
    }
    quickSummary();
    debouncedQuick();
  }));
/* Copies changes nothing about the picture, so it does not redraw one — but
 * it does change the summary, which is the only place the number shows once
 * the disclosure is shut. */
$('quickCopies').addEventListener('input', quickSummary);

$('quickPrint').addEventListener('click', async () => {
  const button = $('quickPrint');
  const copies = Number($('quickCopies').value) || 1;
  const limit = Number(S.settings.confirm_over_copies || 10);
  if (copies > limit && !confirm(`Print ${copies} labels?`)) return;
  button.disabled = true;
  try {
    const data = await post('/api/quick', quickPayload(true));
    toast(`Printed ${data.printed} on the ${data.side} roll.`, 'good');
    notes($('quickNotes'), data.notes);
    await loadState();
  } catch (error) { fail(error); } finally { button.disabled = false; }
});

$('quickToDesign').addEventListener('click', () => {
  if (!S.label) return toast('Type something first.');
  loadLabel(structuredClone(S.label));
  show('design');
});
$('quickToTemplate').addEventListener('click', () => {
  if (!S.label) return toast('Type something first.');
  loadLabel(structuredClone(S.label));
  saveTemplateDialog();
});

/* ── Designer ───────────────────────────────────────────────────────── */
function buildAddBar() {
  const bar = $('addBar');
  bar.innerHTML = '';
  for (const [key, spec] of Object.entries(S.catalog.elements)) {
    const button = el('button', 'btn');
    button.append(el('span', null, spec.icon || '+'), el('span', null, spec.name));
    button.setAttribute('data-tip', spec.help || spec.name);
    button.onclick = () => addElement(key);
    bar.append(button);
  }
}

function blankLabel() {
  const id = designStockValue() || S.settings.default_stock;
  const stock = stockById(id);
  return {
    stock: id,
    /* A NEW label takes the stock's own direction; a SAVED one keeps
     * whatever it was drawn at. Those are different questions — the first is
     * "which way does this label read", which the stock answers, and the
     * second is "what did somebody lay out", which only the file knows. */
    rotate: stock ? Number(stock.turn) || 0 : 0,
    name: '', invert: false, elements: [],
  };
}

function loadLabel(label) {
  S.label = label || blankLabel();
  S.selected = -1;
  S.problems = [];
  setStockButton($('designStock'), S.label.stock);
  $('designName').value = S.label.name || '';
  updateTurnLines();
  renderDesign();
}

function canvasMm() {
  const stock = stockById(S.label.stock);
  if (!stock) return { w: 50, h: 25 };
  const [w, h] = stock.drawable_mm;
  return (S.label.rotate === 90 || S.label.rotate === 270) ? { w: h, h: w } : { w, h };
}

let designTimer = 0;
function renderDesign() {
  if (!S.label) loadLabel(null);
  clearTimeout(designTimer);
  designTimer = setTimeout(refreshPreview, 200);
  drawOverlay();
  drawProps();
  drawLayers();
}

/* Out-of-order replies are the ordinary case once the preview fires while a
 * box is being dragged: a bigger label renders slower, so the answer to
 * where the box was two hundred milliseconds ago can arrive after the answer
 * to where it is. Same guard `quickSeq` has, for the same reason. */
let previewSeq = 0;
async function refreshPreview() {
  const seq = ++previewSeq;
  try {
    const response = await fetch(relative('/api/preview'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      /* `view: 'canvas'`: the sheet turned back the way this label is DRAWN.
       * The overlay's coordinates are the canvas's, and on a 90° tube wrap
       * the printed sheet is a tall strip with the words on their side — so
       * the box being dragged and the ink it described sat in two different
       * places, which is what made a wrap-around label undesignable. The
       * Quick and Templates previews keep the sheet: that is what comes out
       * of the printer. */
      body: JSON.stringify({ label: S.label, scale: 2, view: 'canvas' }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `preview answered ${response.status}`);
    }
    const blob = await response.blob();
    if (seq !== previewSeq) return;
    const image = $('designPreview');
    const previous = image.src;
    image.src = URL.createObjectURL(blob);
    image.classList.add('on');
    if (previous.startsWith('blob:')) URL.revokeObjectURL(previous);
    image.onload = fitCanvas;
    notes($('designNotes'), JSON.parse(response.headers.get('X-Label-Notes') || '[]'));
    /* The same messages, keyed to the element each is about, so a barcode
     * that will not fit is outlined on the canvas rather than described in a
     * sentence under six identical boxes. */
    S.problems = JSON.parse(response.headers.get('X-Label-Problems') || '[]');
    markProblems();
  } catch (error) {
    if (seq !== previewSeq) return;
    notes($('designNotes'), [error.message]);
  }
}

/* Which boxes are outlined in red, and there is exactly one source for it.
 *
 * `S.problems` comes off the render — a barcode that will not fit, a fixed
 * size that clips. There used to be a second, client-side source: the band
 * this roll's printer cannot reach and the band somebody asked to keep
 * clear, both hatched on a canvas that was the whole sheet, with anything
 * lying in one outlined here. The canvas IS the printable box now, so a box
 * cannot lie in either — the areas are not on the canvas to reach into, and
 * a rule about them would be a rule about nothing.
 *
 * Applied to the boxes already on screen rather than by rebuilding them:
 * this lands mid-drag, and rebuilding the overlay would take the element out
 * from under the finger holding it. */
function markProblems() {
  const bad = new Set((S.problems || []).map((p) => p.index));
  const boxes = $('overlay').querySelectorAll('.el');
  boxes.forEach((box, index) => box.classList.toggle('bad', bad.has(index)));
  const print = $('designPrint');
  const count = bad.size;
  /* Still enabled: the rule here is that a print is refused only when it
   * cannot be right, and a barcode that will not fit is usually still the
   * label somebody wanted — always their decision rather than this one's. */
  print.setAttribute('data-tip', count
    ? (count === 1
        ? 'One box has a problem — it is outlined in red, and the notes under '
          + 'the label say what. It will still print.'
        : `${count} boxes have a problem — they are outlined in red, and the `
          + 'notes under the label say what. It will still print.')
    : 'Send this label to the printer.');
}

/* The preview is rendered at 2x the printer's resolution for crispness, which
 * on a 2.25" label is 1344px — wider than the pane on most screens and taller
 * than the window on a rotated 3.44" one. So the PNG stays at 2x and the
 * CANVAS is sized to fit; the overlay reads the element's laid-out size
 * rather than the image's natural size, which is what keeps a dragged box
 * under the finger at any zoom. */
const CANVAS_MAX_H = 520;

function fitCanvas() {
  const canvas = $('canvas');
  const image = $('designPreview');
  if (!image.naturalWidth) return;
  const scroll = $('canvas-scroll') || document.querySelector('.canvas-scroll');
  const available = Math.max(160, (scroll?.clientWidth || 600) - 28);
  const zoom = Math.min(1, available / image.naturalWidth,
                        CANVAS_MAX_H / image.naturalHeight);
  canvas.style.width = Math.round(image.naturalWidth * zoom) + 'px';
  canvas.style.height = Math.round(image.naturalHeight * zoom) + 'px';
  image.style.width = '100%';
  image.style.height = '100%';
  /* Never while a box is being dragged: `drawOverlay` rebuilds every box,
   * and rebuilding the one under the finger takes its pointer capture with
   * it — the drag simply stops, halfway, with the box left where the last
   * frame put it. The live preview fires during a drag, which is what makes
   * this reachable at all. */
  if (!dragActive) drawOverlay(); else markProblems();
}

addEventListener('resize', () => { if (S.label) fitCanvas(); });

function round1(value) {
  return Math.round(Number(value) * 10) / 10;
}

/* ── The printable area, and nothing else ──────────────────────────────
 *
 * The canvas used to be the whole sheet with three things drawn on it to
 * aim away from: a dashed rectangle around the stock's own margin, a hatched
 * strip where a 2.25" label overhangs a 2.24" head, and a hatched band where
 * this roll's printer lays no ink. Each was honest and each asked the same
 * thing of a person — lay a label out, then move it off the parts that were
 * never yours. They are one inset on the printable box now (`printable_box`
 * in `stores/stock.py`, applied by `render` and cropped to by the designer's
 * own preview), so the picture IS the canvas: everything on it prints, and
 * there is nothing left to warn about.
 *
 * That also makes the drag overlay exact rather than nearly right. Its
 * millimetres were always the canvas's while the image underneath was the
 * sheet, which is why every box was offset by the margin in code — and why
 * getting that offset wrong was a millimetre of drift that only showed on
 * the smallest labels. There is no offset to get wrong. */

function drawOverlay() {
  const overlay = $('overlay');
  const image = $('designPreview');
  const frame = image.getBoundingClientRect();
  const mm = canvasMm();
  const scaleX = frame.width ? frame.width / mm.w : 4;
  const scaleY = frame.height ? frame.height / mm.h : 4;

  overlay.innerHTML = '';

  const guides = el('div', 'guides');
  guides.id = 'guides';
  overlay.append(guides);

  S.label.elements.forEach((element, index) => {
    const box = el('div', 'el' + (index === S.selected ? ' sel' : ''));
    box.style.left = element.x_mm * scaleX + 'px';
    box.style.top = element.y_mm * scaleY + 'px';
    box.style.width = Math.max(6, element.w_mm * scaleX) + 'px';
    box.style.height = Math.max(6, element.h_mm * scaleY) + 'px';
    box.append(el('span', 'tag', describe(element)));
    const grip = el('span', 'grip');
    box.append(grip);
    dragging(box, grip, index, scaleX, scaleY, mm);
    overlay.append(box);
  });
  markProblems();
}

function describe(element) {
  const props = element.props || {};
  if (element.type === 'text') return (props.text || 'Text').split('\n')[0].slice(0, 22);
  if (element.type === 'barcode') return '||| ' + (props.data || '').slice(0, 16);
  if (element.type === 'qr') return '▣ ' + (props.data || '').slice(0, 16);
  return S.catalog.elements[element.type]?.name || element.type;
}

/* A press that never travels is a tap. Without the threshold, selecting an
 * element on a touchscreen nudges it — you cannot put a finger down without
 * moving a pixel. */
const TAP_SLOP = 4;

/* ── Snapping ───────────────────────────────────────────────────────────
 *
 * Six screen pixels, converted to millimetres per axis so the tolerance is
 * the same distance under the finger at any zoom. Three kinds of target and
 * they are not equal: an edge or a centre is something a person is aiming
 * at, and the 1mm grid is ambient — it must never win over an alignment that
 * is one millimetre away, which is exactly the case where a grid snap feels
 * like the editor fighting you. So the grid is ranked last and draws no
 * guide line, because a line that appears every millimetre is noise. */
const SNAP_PX = 6;
const snapOn = () => prefGet('bruhprint.snap', '1') !== '0';

function snapTargets(axis, index, mm) {
  const size = axis === 'x' ? mm.w : mm.h;
  const out = [{ at: 0 }, { at: size / 2 }, { at: size }];
  S.label.elements.forEach((other, at) => {
    if (at === index) return;
    const start = axis === 'x' ? other.x_mm : other.y_mm;
    const extent = axis === 'x' ? other.w_mm : other.h_mm;
    out.push({ at: start }, { at: start + extent / 2 }, { at: start + extent });
  });
  return out;
}

function snap(edges, targets, tol) {
  let best = null;
  for (const edge of edges) {
    for (const target of targets) {
      const distance = Math.abs(target.at - edge);
      if (distance > tol) continue;
      if (!best || distance < best.distance)
        best = { distance, delta: target.at - edge, at: target.at };
    }
    /* The grid, ranked below every real target: only considered when nothing
     * above matched, so an edge 0.9mm away always beats the whole millimetre
     * next to it. */
    if (!best) {
      const whole = Math.round(edge);
      if (Math.abs(whole - edge) <= tol)
        best = { distance: Math.abs(whole - edge), delta: whole - edge,
                 at: whole, grid: true };
    }
  }
  return best;
}

function showGuide(axis, at, scaleX, scaleY) {
  const guides = $('guides');
  if (!guides) return;
  const line = el('div', 'guide ' + axis);
  if (axis === 'x') line.style.left = at * scaleX + 'px';
  else line.style.top = at * scaleY + 'px';
  guides.append(line);
}
const clearGuides = () => { const g = $('guides'); if (g) g.innerHTML = ''; };

/* True from the first travelled pixel to pointerup. Read by `fitCanvas`,
 * which must not rebuild the overlay while a box is being held. */
let dragActive = false;
let liveAt = 0;
/* Slow enough that a drag is not a request per frame, fast enough that the
 * glyphs visibly re-fit while the box is still moving — which is the whole
 * point: a text box's size is the thing being chosen, and seeing it only
 * after you let go means letting go to find out. */
const LIVE_MS = 150;

function dragging(box, grip, index, scaleX, scaleY, mm) {
  let mode = null, startX = 0, startY = 0, origin = null, moved = false;

  const begin = (event, which) => {
    event.preventDefault();
    event.stopPropagation();
    mode = which; moved = false;
    startX = event.clientX; startY = event.clientY;
    origin = { ...S.label.elements[index] };
    select(index);
    box.setPointerCapture?.(event.pointerId);
  };

  const move = (event) => {
    if (!mode) return;
    const dx = (event.clientX - startX), dy = (event.clientY - startY);
    if (!moved && Math.abs(dx) < TAP_SLOP && Math.abs(dy) < TAP_SLOP) return;
    moved = true;
    dragActive = true;
    const element = S.label.elements[index];
    const tolX = SNAP_PX / scaleX, tolY = SNAP_PX / scaleY;
    clearGuides();

    if (mode === 'move') {
      let x = clamp(origin.x_mm + dx / scaleX, 0, mm.w - element.w_mm);
      let y = clamp(origin.y_mm + dy / scaleY, 0, mm.h - element.h_mm);
      if (snapOn()) {
        const hit = snap([x, x + element.w_mm / 2, x + element.w_mm],
                         snapTargets('x', index, mm), tolX);
        if (hit) {
          x = clamp(x + hit.delta, 0, mm.w - element.w_mm);
          if (!hit.grid) showGuide('x', hit.at, scaleX, scaleY);
        }
        const down = snap([y, y + element.h_mm / 2, y + element.h_mm],
                          snapTargets('y', index, mm), tolY);
        if (down) {
          y = clamp(y + down.delta, 0, mm.h - element.h_mm);
          if (!down.grid) showGuide('y', down.at, scaleX, scaleY);
        }
      }
      element.x_mm = x;
      element.y_mm = y;
    } else {
      let w = clamp(origin.w_mm + dx / scaleX, 1, mm.w - element.x_mm);
      let h = clamp(origin.h_mm + dy / scaleY, 1, mm.h - element.y_mm);
      if (snapOn()) {
        const hit = snap([element.x_mm + w], snapTargets('x', index, mm), tolX);
        if (hit) {
          w = clamp(w + hit.delta, 1, mm.w - element.x_mm);
          if (!hit.grid) showGuide('x', hit.at, scaleX, scaleY);
        }
        const down = snap([element.y_mm + h], snapTargets('y', index, mm), tolY);
        if (down) {
          h = clamp(h + down.delta, 1, mm.h - element.y_mm);
          if (!down.grid) showGuide('y', down.at, scaleX, scaleY);
        }
      }
      element.w_mm = w;
      element.h_mm = h;
    }
    clampElement(element, mm);
    box.style.left = element.x_mm * scaleX + 'px';
    box.style.top = element.y_mm * scaleY + 'px';
    box.style.width = Math.max(6, element.w_mm * scaleX) + 'px';
    box.style.height = Math.max(6, element.h_mm * scaleY) + 'px';

    /* Live, throttled. Autofit text is the reason: the size of the glyphs IS
     * the thing being chosen when you drag a text box's corner, and it only
     * exists on the server. */
    const now = Date.now();
    if (now - liveAt > LIVE_MS) { liveAt = now; refreshPreview(); }
  };

  const end = () => {
    if (!mode) return;
    mode = null;
    dragActive = false;
    clearGuides();
    if (moved) { markDirty(); drawProps(); }
  };

  box.addEventListener('pointerdown', (e) => begin(e, 'move'));
  grip.addEventListener('pointerdown', (e) => begin(e, 'resize'));
  box.addEventListener('pointermove', move);
  box.addEventListener('pointerup', end);
  box.addEventListener('pointercancel', end);
}

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const round = (element) => {
  /* Tenths of a millimetre. A drag produces a float with fifteen decimals,
   * and a saved template full of 12.700000000000001 is a diff nobody can
   * read and a file that is not byte-identical after a no-op edit. */
  for (const key of ['x_mm', 'y_mm', 'w_mm', 'h_mm'])
    element[key] = Math.round(element[key] * 10) / 10;
};

function markDirty() { S.dirty = true; clearTimeout(designTimer); designTimer = setTimeout(refreshPreview, 220); }

/* Selecting toggles a class; it does NOT rebuild the overlay.
 *
 * It used to, and that is why dragging never worked from the first press:
 * `begin` selects and then calls `setPointerCapture`, and by then the box it
 * was called on had been replaced by a fresh one — a detached element throws
 * `InvalidStateError`, the capture is lost, and every `pointermove` after it
 * goes to a node whose `mode` was never set. The drag simply did nothing,
 * which from a finger is indistinguishable from a box that will not move.
 * Callers that change the LIST of elements still redraw; picking one of them
 * is not a change to the list. */
function select(index) {
  S.selected = index;
  $('overlay').querySelectorAll('.el').forEach((box, at) =>
    box.classList.toggle('sel', at === index));
  drawProps();
  drawLayers();
}

function addElement(kind) {
  const spec = S.catalog.elements[kind];
  if (!spec) return;
  const mm = canvasMm();
  const props = {};
  for (const [name, meta] of Object.entries(spec.fields)) props[name] = meta.default;
  if (kind === 'text') props.text = 'Text';
  const element = {
    type: kind,
    x_mm: Math.round(mm.w * 0.08 * 10) / 10,
    y_mm: Math.round(mm.h * 0.1 * 10) / 10,
    w_mm: Math.round(mm.w * 0.6 * 10) / 10,
    h_mm: Math.round(mm.h * (kind === 'qr' ? 0.6 : 0.3) * 10) / 10,
    props,
  };
  if (kind === 'qr') element.w_mm = element.h_mm = Math.round(Math.min(mm.w, mm.h) * 0.6 * 10) / 10;
  S.label.elements.push(element);
  // The list changed, so the overlay is rebuilt here rather than by the
  // selection — `select` only toggles a class now, and a box that appears
  // 220ms later (when the preview lands) is a box you cannot grab yet.
  drawOverlay();
  select(S.label.elements.length - 1);
  markDirty();
}

/* Every box stays on the label, from every route in: dragged, resized,
 * typed, nudged, aligned or turned. One function, because five call sites
 * asking separately is five chances for a new one to forget. */
function clampElement(element, mm) {
  round(element);
  /* Floored to a tenth, not clamped to the raw limit. The drawable width of
   * a 2.25" stock is 53.15mm, and rounding a box's x to a tenth AFTER
   * clamping it against that rounds it back up to 53.2 — a box a twentieth
   * of a millimetre off the label, every time, from the one place that was
   * supposed to stop exactly that. Round first, then floor the ceiling. */
  const down = (value) => Math.floor(Math.max(0, value) * 10) / 10;
  element.w_mm = Math.max(0.1, Math.min(element.w_mm, down(mm.w)));
  element.h_mm = Math.max(0.1, Math.min(element.h_mm, down(mm.h)));
  element.x_mm = clamp(element.x_mm, 0, down(mm.w - element.w_mm));
  element.y_mm = clamp(element.y_mm, 0, down(mm.h - element.h_mm));
}

/* One millimetre.
 *
 * It was half, on the argument that half is the smallest move worth making;
 * what that produced was a box sitting at 6.5mm and a person asking for
 * whole millimetres. A label is a few centimetres of paper read at arm's
 * length and nothing on one is placed to half a millimetre — the drag
 * already offers finer than that, so it is the ARROWS that are the coarse,
 * exact control. The nudge also rounds to the millimetre BEFORE it moves,
 * or four presses from a dragged 6.4 land on 2.4: an arrow that carries the
 * fraction it started from can never reach a round number, which is the
 * whole reason somebody reaches for one. */
const NUDGE_MM = 1;

function alignTools(element, mm) {
  /* Three named rows, and the name is the half that was missing.
   *
   * This was two rows of glyphs — eight in the first, four in the second —
   * with what each one did in a tooltip, on a pane whose commonest device
   * has no hover. `⇤ ⇔ ⇥ ⤒ ⇕ ⤓ ↔ ↕` in a line is not eight controls, it is
   * one illegible strip, and the person using it said so. What separates
   * them is the question each answers: the first row is where the box sits
   * ACROSS the label, the second where it sits DOWN it, the third moves it
   * by a millimetre. The same eight actions, each under the word that says
   * which axis it is about — which is also what lets the two `Fill`s be
   * called Fill rather than `↔ Fill` and `↕ Fill`. */
  const holder = el('div', 'tools');

  const group = (caption) => {
    const row = el('div', 'toolgroup');
    row.append(el('span', null, caption));
    holder.append(row);
    return row;
  };
  const put = (row, label, tip, run) => {
    const button = el('button', 'btn', label);
    button.type = 'button';
    button.setAttribute('data-tip', tip);
    button.onclick = () => {
      run();
      clampElement(element, mm);
      markDirty(); drawOverlay(); drawProps();
    };
    row.append(button);
    return button;
  };

  const across = group('Across');
  put(across, '⇤', 'Against the left of the printable area',
      () => { element.x_mm = 0; });
  put(across, '⇔', 'Centred across the label',
      () => { element.x_mm = (mm.w - element.w_mm) / 2; });
  put(across, '⇥', 'Against the right of the printable area',
      () => { element.x_mm = mm.w - element.w_mm; });
  put(across, 'Fill', 'As wide as the printable area',
      () => { element.x_mm = 0; element.w_mm = mm.w; });

  const down = group('Down');
  put(down, '⤒', 'Against the top of the printable area',
      () => { element.y_mm = 0; });
  put(down, '⇕', 'Centred down the label',
      () => { element.y_mm = (mm.h - element.h_mm) / 2; });
  put(down, '⤓', 'Against the bottom of the printable area',
      () => { element.y_mm = mm.h - element.h_mm; });
  put(down, 'Fill', 'As tall as the printable area',
      () => { element.y_mm = 0; element.h_mm = mm.h; });

  const nudges = group('Nudge 1 mm');
  for (const [label, tip, dx, dy] of [
    ['←', 'A millimetre left', -NUDGE_MM, 0],
    ['→', 'A millimetre right', NUDGE_MM, 0],
    ['↑', 'A millimetre up', 0, -NUDGE_MM],
    ['↓', 'A millimetre down', 0, NUDGE_MM],
  ]) {
    put(nudges, label, tip, () => {
      if (dx) element.x_mm = Math.round(element.x_mm) + dx;
      if (dy) element.y_mm = Math.round(element.y_mm) + dy;
    });
  }
  return holder;
}

/* Which element types can be turned. It is read off the SERVER's catalog
 * rather than listed here, so a new type that carries a `rotate` field gets
 * the button by having one — and a QR code, a box and a rule, which look the
 * same whichever way up they are, never grow a control that does nothing. */
const canTurn = (element) => !!(element
  && S.catalog.elements[element.type]?.fields?.rotate);

function rotateSelected() {
  const element = S.label.elements[S.selected];
  if (!canTurn(element)) return;
  const turns = S.catalog.elements[element.type].fields.rotate.choices;
  const at = turns.indexOf(Number(element.props.rotate) || 0);
  const next = turns[(at + 1) % turns.length];
  /* A quarter turn swaps which dimension the content runs along, so the box
   * follows it — turning text inside a box that stayed wide is a line that
   * wraps to nothing. Half turns leave the shape alone. */
  if ((Number(element.props.rotate) % 180) !== (Number(next) % 180)) {
    const width = element.w_mm;
    element.w_mm = element.h_mm;
    element.h_mm = width;
  }
  element.props.rotate = next;
  clampElement(element, canvasMm());
  markDirty(); drawOverlay(); drawProps();
}

/* The sheet reads the stored answer rather than remembering one of its own:
 * it is opened and closed, and a tick-box that keeps its own state is a
 * second answer to a question `snapOn()` already has. */
function syncDesignSheet() {
  $('designSnap').checked = snapOn();
}

function drawProps() {
  const holder = $('props'), empty = $('propsEmpty');
  const element = S.label.elements[S.selected];
  holder.hidden = !element;
  empty.hidden = !!element;
  if (!element) return;

  const spec = S.catalog.elements[element.type];
  holder.innerHTML = '';
  holder.append(el('h3', null, spec.name));
  if (spec.help) holder.append(el('p', 'lede', spec.help));

  const mm = canvasMm();
  /* Named, and stepped in whole millimetres.
   *
   * `X (mm)` and `W (mm)` are the axes' names and not the box's: what a
   * person is placing is a rectangle on a label, and Left/Top/Width/Height
   * are what that rectangle's four numbers are called everywhere else they
   * are met. The unit moves to the caption above the row, which is where it
   * belongs — it is the same unit four times. The step is 1 for the reason
   * `NUDGE_MM` is: a spinner that walks in halves is a spinner that walks
   * off a round number and cannot get back to one. */
  const geometry = el('div', 'row');
  for (const [key, label] of [['x_mm', 'Left'], ['y_mm', 'Top'],
                              ['w_mm', 'Width'], ['h_mm', 'Height']]) {
    const field = el('label', 'field');
    field.append(el('span', null, label));
    const input = el('input');
    input.type = 'number'; input.step = '1'; input.value = round1(element[key]);
    input.oninput = () => {
      /* Typed values are clamped the same way dragged ones are. Without it
       * the one route into the designer that could put a box off the label
       * was the keyboard — and the renderer clamps at print time, so the
       * only sign was a label that came out different from the screen. */
      element[key] = Number(input.value) || 0;
      clampElement(element, mm);
      input.value = round1(element[key]);
      markDirty(); drawOverlay();
    };
    field.append(input);
    geometry.append(field);
  }
  holder.append(el('p', 'toolcap', 'Where it sits on the label, in millimetres'));
  holder.append(geometry);

  holder.append(alignTools(element, mm));

  for (const [name, meta] of Object.entries(spec.fields)) {
    /* Except `rotate`, which the ⟳ button below already is — and is the
     * better of the two, because turning a box a quarter swaps which
     * dimension its contents run along and the button swaps the box with
     * it, where a plain `<select>` of 0/90/180/270 left a turned line of
     * text in a box that stayed wide. Two controls for one thing is one
     * too many, and this pair disagreed about what the thing was. */
    if (name === 'rotate') continue;
    holder.append(propField(element, name, meta));
  }

  /* The three verbs that act on this box, in one row.
   *
   * Rotate was down with the align and nudge tools, which are all about
   * WHERE the box is; turning it is the same kind of thing as copying it or
   * deleting it, and this is the row those live in. It keeps the id the
   * design bar gave it, because that is the name every handler and test
   * already uses. */
  const row = el('div', 'actions');
  const rotate = el('button', 'btn', '⟳ Rotate');
  rotate.type = 'button';
  rotate.id = 'designRotateEl';
  rotate.disabled = !canTurn(element);
  rotate.setAttribute('data-tip', canTurn(element)
    ? 'Turn this box a quarter — the box turns with it, so the words still '
      + 'have room.'
    : `A ${S.catalog.elements[element.type]?.name || element.type} looks the `
      + 'same whichever way up it is, so there is nothing to turn.');
  rotate.onclick = rotateSelected;
  const duplicate = el('button', 'btn', 'Duplicate');
  duplicate.onclick = () => {
    const copy = structuredClone(element);
    copy.y_mm = Math.round((copy.y_mm + copy.h_mm + 1) * 10) / 10;
    clampElement(copy, canvasMm());
    S.label.elements.push(copy);
    drawOverlay();
    select(S.label.elements.length - 1);
    markDirty();
  };
  const remove = el('button', 'btn danger', 'Delete');
  remove.onclick = () => {
    S.label.elements.splice(S.selected, 1);
    S.selected = -1;
    markDirty(); drawOverlay(); drawProps(); drawLayers();
  };
  row.append(rotate, duplicate, remove);
  holder.append(row);
}

function propField(element, name, meta) {
  const field = el('label', 'field');
  field.append(el('span', null, meta.label || name));
  let input;

  if (meta.type === 'bool') {
    field.className = 'check';
    field.innerHTML = '';
    input = el('input'); input.type = 'checkbox';
    input.checked = !!element.props[name];
    field.append(input, el('span', null, meta.label || name));
  } else if (meta.type === 'choice') {
    input = el('select');
    for (const choice of meta.choices) {
      const option = el('option', null, String(choice));
      option.value = String(choice);
      input.append(option);
    }
    input.value = String(element.props[name]);
  } else if (meta.type === 'font') {
    /* The same picker the Quick tab has, because there is one question here
     * and it is "what will the words look like". `input.value` is read by
     * the shared oninput below, so the button carries one. */
    input = el('button', 'fontpick');
    input.type = 'button';
    input.value = element.props[name] || '';
    setFontButton(input, input.value);
    input.onclick = () => openFontPicker(input.value, (key) => {
      input.value = key;
      setFontButton(input, key);
      element.props[name] = key;
      markDirty();
    });
  } else if (meta.type === 'number') {
    input = el('input');
    input.type = 'number'; input.step = '0.1';
    if (meta.min != null) input.min = meta.min;
    if (meta.max != null) input.max = meta.max;
    input.value = element.props[name];
  } else if (name === 'text') {
    input = el('textarea'); input.rows = 2; input.value = element.props[name] || '';
  } else {
    input = el('input'); input.value = element.props[name] ?? '';
  }

  input.oninput = () => {
    const raw = meta.type === 'bool' ? input.checked : input.value;
    if (meta.type === 'number') element.props[name] = Number(raw) || 0;
    else if (meta.type === 'choice' && typeof meta.choices[0] === 'number')
      element.props[name] = Number(raw);
    else element.props[name] = raw;
    markDirty();
    if (name === 'text' || name === 'data') drawOverlay();
  };
  if (meta.type !== 'bool') field.append(input);
  if (meta.help) field.append(el('span', 'muted', meta.help));
  return field;
}

function drawLayers() {
  const list = $('layers');
  list.innerHTML = '';
  if (!S.label.elements.length) return;
  S.label.elements.forEach((element, index) => {
    const row = el('button', 'layer' + (index === S.selected ? ' sel' : ''));
    row.append(el('span', 'lk', S.catalog.elements[element.type]?.icon || '·'));
    row.append(el('span', 'lt', describe(element)));
    row.onclick = () => select(index);
    list.append(row);
  });
}

$('designStock').addEventListener('click', () => {
  openStockPicker(designStockValue(), (id) => {
    setStockButton($('designStock'), id);
    S.label.stock = id;
    /* Changing the stock is choosing a different label, so the direction
     * comes with it — a tube wrap reads along the roll and an address label
     * reads across it, and carrying the old answer over is how you get a
     * design laid out sideways on a stock that never reads that way. */
    const stock = stockById(S.label.stock);
    if (stock) S.label.rotate = Number(stock.turn) || 0;
    updateTurnLines();
    markDirty(); drawOverlay(); drawProps();
  });
});
$('designMore').addEventListener('click', () => {
  syncDesignSheet();
  $('designSheet').showModal();
});
$('designSheetDone').addEventListener('click', () => $('designSheet').close());
$('designSnap').addEventListener('change', () => {
  prefSet('bruhprint.snap', $('designSnap').checked ? '1' : '0');
});
$('designName').addEventListener('input', () => { S.label.name = $('designName').value; });
$('overlay').addEventListener('pointerdown', (event) => {
  if (event.target.id === 'overlay') select(-1);
});

$('designPrint').addEventListener('click', async () => {
  const copies = Number($('designCopies').value) || 1;
  const limit = Number(S.settings.confirm_over_copies || 10);
  if (copies > limit && !confirm(`Print ${copies} labels?`)) return;
  const button = $('designPrint');
  button.disabled = true;
  try {
    const data = await post('/api/print', {
      label: S.label, copies, source: 'designer',
    });
    toast(`Printed ${data.printed} on the ${data.side} roll.`, 'good');
    notes($('designNotes'), data.notes);
    await loadState();
  } catch (error) { fail(error); } finally { button.disabled = false; }
});

$('designSaveTemplate').addEventListener('click', saveTemplateDialog);

function saveTemplateDialog() {
  const body = $('modalBody');
  body.innerHTML = '';
  body.append(el('h2', null, 'Save as a template'));
  body.append(el('p', 'lede',
    'Anywhere you write {{something}} in a text, a barcode or a QR code '
    + 'becomes a box to fill in — here, in the Lovelace card, and in '
    + 'automations. {{date}} and {{time}} fill themselves in.'));

  const nameField = el('label', 'field');
  nameField.append(el('span', null, 'Name'));
  const nameInput = el('input');
  nameInput.value = S.label.name || '';
  nameInput.placeholder = 'Freezer bag';
  nameField.append(nameInput);

  const descField = el('label', 'field');
  descField.append(el('span', null, 'What it is for'));
  const descInput = el('input');
  descInput.placeholder = 'Goes round a 2ml tube';
  descField.append(descInput);

  const found = placeholdersOf(S.label);
  const holes = el('p', 'lede', found.length
    ? 'Fields on this template: ' + found.join(', ')
    : 'No {{fields}} in this label — it will print exactly as it is.');

  const row = el('div', 'actions');
  const save = el('button', 'btn primary', 'Save');
  const cancel = el('button', 'btn', 'Cancel');
  save.onclick = async () => {
    if (!nameInput.value.trim()) return toast('Give it a name.');
    try {
      await post('/api/template', {
        name: nameInput.value.trim(),
        description: descInput.value,
        label: S.label,
        copies: Number($('designCopies').value) || 1,
      });
      $('modal').close();
      await loadState();
      toast('Template saved.', 'good');
      show('templates');
    } catch (error) { fail(error); }
  };
  cancel.onclick = () => $('modal').close();
  row.append(save, cancel);
  body.append(nameField, descField, holes, row);
  $('modal').showModal();
}

function placeholdersOf(label) {
  const found = [];
  for (const element of label.elements || []) {
    for (const key of ['text', 'data']) {
      const value = String((element.props || {})[key] || '');
      for (const match of value.matchAll(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g))
        if (!found.includes(match[1])) found.push(match[1]);
    }
  }
  return found;
}

/* ── Templates ──────────────────────────────────────────────────────── */
function renderTemplates() {
  const cards = $('templateCards');
  cards.innerHTML = '';
  if (!S.templates.length) {
    cards.append(el('p', 'lede',
      'No templates yet. Design a label, write {{sample}} where the changing '
      + 'part goes, and press "Save as template".'));
    return;
  }
  for (const template of S.templates) {
    const card = el('button', 'card' + (S.template?.id === template.id ? ' sel' : ''));
    card.append(el('h3', null, template.name));
    const stock = stockById(template.stock);
    card.append(el('div', 'sub',
      (template.description || (stock ? stock.name : template.stock))));
    const foot = el('div', 'foot');
    foot.append(el('span', 'sub',
      template.fields.length ? `${template.fields.length} field${template.fields.length > 1 ? 's' : ''}`
        : 'no fields'));
    if (template.use_count) foot.append(el('span', 'sub', `· used ${template.use_count}×`));
    card.append(foot);
    card.onclick = () => pickTemplate(template);
    cards.append(card);
  }
}

function pickTemplate(template) {
  S.template = template;
  renderTemplates();
  const form = $('templateForm');
  form.hidden = false;
  form.innerHTML = '';
  form.append(el('h3', null, template.name));

  const inputs = {};
  for (const field of template.fields) {
    const wrap = el('label', 'field');
    wrap.append(el('span', null, field.label));
    const input = field.multiline ? el('textarea') : el('input');
    input.value = field.default || '';
    if (field.hint) input.placeholder = field.hint;
    input.oninput = () => templatePreview(template, inputs);
    wrap.append(input);
    if (field.hint) wrap.append(el('span', 'muted', field.hint));
    inputs[field.key] = input;
    form.append(wrap);
  }

  const row = el('div', 'actions');
  const copiesField = el('label', 'field inline');
  copiesField.append(el('span', null, 'Copies'));
  const copies = el('input');
  copies.type = 'number'; copies.min = '1'; copies.value = String(template.copies || 1);
  copiesField.append(copies);

  const print = el('button', 'btn primary big', 'Print');
  print.onclick = async () => {
    print.disabled = true;
    try {
      const data = await post(`/api/template/${template.id}/print`, {
        fields: values(inputs), copies: Number(copies.value) || 1,
      });
      toast(`Printed ${data.printed} on the ${data.side} roll.`, 'good');
      notes($('templateNotes'), data.notes);
      await loadState();
    } catch (error) { fail(error); } finally { print.disabled = false; }
  };

  const edit = el('button', 'btn', 'Edit design');
  edit.onclick = () => { loadLabel(structuredClone(template.label)); show('design'); };
  const remove = el('button', 'btn danger', 'Delete');
  remove.onclick = async () => {
    if (!confirm(`Delete the template "${template.name}"?`)) return;
    try {
      await del(`/api/template/${template.id}`);
      S.template = null;
      $('templateForm').hidden = true;
      await loadState(); renderTemplates();
      toast('Template deleted.');
    } catch (error) { fail(error); }
  };

  row.append(copiesField, print, edit, remove);
  form.append(row);
  templatePreview(template, inputs);
}

const values = (inputs) => Object.fromEntries(
  Object.entries(inputs).map(([key, input]) => [key, input.value]));

let templateSeq = 0;
async function templatePreview(template, inputs) {
  const seq = ++templateSeq;
  try {
    const data = await post(`/api/template/${template.id}/preview`,
      { fields: values(inputs), scale: 2 });
    if (seq !== templateSeq) return;
    const image = $('templatePreview');
    image.src = data.png;
    image.classList.add('on');
    $('templatePlaceholder').hidden = true;
    const messages = [...data.notes];
    if (data.missing.length)
      messages.unshift(`Still empty: ${data.missing.join(', ')}. Printing will `
        + `refuse until they are filled in.`);
    notes($('templateNotes'), messages);
  } catch (error) {
    if (seq === templateSeq) notes($('templateNotes'), [error.message]);
  }
}

/* ── Printer tab ────────────────────────────────────────────────────── */
function renderPrinter() {
  const cards = $('printerCards');
  cards.innerHTML = '';
  if (!S.printers.length) {
    const card = el('div', 'card');
    card.append(el('h3', null, 'No printer found'));
    card.append(el('div', 'sub', S.printerError
      || 'Plug a DYMO LabelWriter in over USB. It needs its own power brick — '
      + 'a LabelWriter with no power does not appear on the bus at all.'));
    const retry = el('button', 'btn', 'Look again');
    retry.onclick = async () => { await api('/api/printers'); await loadState(); renderPrinter(); };
    const foot = el('div', 'foot'); foot.append(retry);
    card.append(foot);
    cards.append(card);
  }
  for (const printer of S.printers) {
    const card = el('div', 'card' + (S.printer?.key === printer.key ? ' sel' : ''));
    card.append(el('h3', null, printer.name));
    card.append(el('div', 'sub',
      `${printer.dots} dots across (${printer.printable_in}"), ${printer.dpi}dpi`
      + (printer.twin ? ' · two rolls' : ' · one roll')
      + (printer.serial ? ` · ${printer.serial}` : '')));
    if (!printer.recognised)
      card.append(el('div', 'sub',
        'Not a model BRUH Print knows by name, so it is being driven as a '
        + '450. If labels come out the wrong width, tell us the model.'));
    if (printer.authenticated_media)
      card.append(el('div', 'sub',
        'This generation checks an RFID tag on the roll and refuses stock '
        + 'that does not carry one. Nothing here can work around that.'));
    const foot = el('div', 'foot');
    const mine = S.printer?.key === printer.key;
    const use = el('button', 'btn tiny', mine ? 'In use' : 'Use this one');
    use.setAttribute('data-tip', mine
      ? 'Everything prints to this one. It only matters when more than one '
        + 'LabelWriter is plugged in — press another to move printing there.'
      : 'Send every print to this printer instead. Remembered by serial, so '
        + 'it survives a reboot that renumbers the USB bus.');
    use.disabled = mine && S.printers.length < 2;
    use.onclick = async () => {
      try { await post('/api/printer/select', { printer: printer.key }); await loadState(); renderPrinter(); }
      catch (error) { fail(error); }
    };
    const status = el('button', 'btn tiny', 'Ask the printer');
    status.setAttribute('data-tip',
      'Asks the printer how it is, right now — paper out, lid open, busy, '
      + 'or ready. It prints nothing.');
    status.onclick = async () => {
      try { const data = await api('/api/printer/status'); toast(`${printer.name}: ${data.status}.`, data.status_ok ? 'good' : 'bad'); }
      catch (error) { fail(error); }
    };
    /* The descriptors, on a button. This add-on has been debugged twice by
     * somebody standing at the printer reading a panel that could not say
     * what it had found — and the descriptors are always readable even when
     * the printer answers nothing. */
    const usb = el('button', 'btn tiny', 'USB details');
    usb.setAttribute('data-tip',
      'Which interfaces and endpoints this printer exposes, and which one '
      + 'BRUH Print is using. Worth copying into a bug report.');
    usb.onclick = async () => {
      try {
        const data = await api('/api/printer/usb');
        const body = $('modalBody');
        body.innerHTML = '';
        body.append(el('h3', null, 'USB details'));
        body.append(el('p', 'lede', data.using || ''));
        body.append(el('p', 'lede', `Status: ${data.status}`));
        const pre = el('pre', 'usbdump');
        pre.textContent = (data.interfaces || []).map((i) =>
          `interface ${i.interface} alt ${i.altsetting}  `
          + `class ${i.class} protocol ${i.protocol}\n`
          + i.endpoints.map((e) =>
            `    ${e.address}  ${e.type} ${e.direction}  ${e.packet} bytes`)
            .join('\n')).join('\n\n') || 'no interfaces reported';
        body.append(pre);
        const close = el('button', 'btn', 'Close');
        close.onclick = () => $('modal').close();
        body.append(close);
        $('modal').showModal();
      } catch (error) { fail(error); }
    };
    /* Three buttons, all of them about the PRINTER. Lining a roll up is
     * about a roll, and a roll lives in a bay — so it is a control on the
     * bay below rather than a fourth button here that has to ask which one
     * you meant. The two that used to be here went with the four knobs they
     * served: the ruler measured a stock and this measures the paper, and
     * "Where the printing starts" was a dialog of boxes to type guesses
     * into. */
    foot.append(use, status, usb);
    card.append(foot);
    cards.append(card);
  }

  const bays = $('bays');
  bays.innerHTML = '';
  const twin = !S.printer || S.printer.twin;
  for (const roll of S.rolls) {
    if (roll.side === 'right' && !twin) continue;
    const bay = el('div', 'bay');
    const title = el('h3', null, roll.side === 'left' ? 'Left roll' : 'Right roll');
    bay.append(title);

    const select = el('select');
    const none = el('option', null, '— empty —'); none.value = '';
    select.append(none);
    for (const stock of S.stocks) {
      const option = el('option', null, stockOptionText(stock));
      option.value = stock.id;
      select.append(option);
    }
    select.value = roll.stock || '';
    select.onchange = async () => {
      try {
        if (select.value) await post(`/api/roll/${roll.side}`, { stock: select.value });
        else await del(`/api/roll/${roll.side}`);
        await loadState(); renderPrinter();
        toast(select.value ? 'Roll updated.' : 'Roll marked empty.', 'good');
      } catch (error) { fail(error); }
    };
    bay.append(select);

    const stock = stockById(roll.stock);
    if (stock && S.settings.track_remaining !== false) {
      /* The bar is a control, not a readout. The count is an estimate that
       * drifts the moment somebody prints from another machine or throws
       * half a roll away, so the fix has to be where the wrong number is —
       * press the bar, type the truth. A number you can see and cannot
       * correct is a number you stop reading. */
      const full = stock.per_roll || roll.remaining || 1;
      const gauge = el('button', 'remaining');
      gauge.setAttribute('data-tip',
        'An estimate, counted down from what you set when you loaded the '
        + 'roll — nothing on a LabelWriter reports the real level. Press to '
        + 'correct it.');
      const bar = el('div', 'bar');
      const fillEl = el('i');
      fillEl.style.width = clamp(roll.remaining / full * 100, 0, 100) + '%';
      bar.append(fillEl);
      gauge.append(bar, el('span', 'est',
        `About ${roll.remaining} left — press to correct`));
      const setCount = async () => {
        const typed = prompt(
          `How many ${stock.name} labels are left on the ${roll.side} roll?`,
          String(roll.remaining));
        if (typed === null) return;
        const count = Number(typed);
        if (!Number.isFinite(count) || count < 0)
          return toast('That is not a number of labels.', 'bad');
        try {
          await post(`/api/roll/${roll.side}`,
                     { stock: stock.id, remaining: Math.round(count) });
          await loadState(); renderPrinter();
          toast('Count updated.', 'good');
        } catch (error) { fail(error); }
      };
      gauge.onclick = setCount;
      bay.append(gauge);

      const reset = el('button', 'btn tiny', 'Full roll');
      reset.setAttribute('data-tip',
        `Put the count back to a full roll of ${stock.per_roll || '?'} — `
        + 'what you press when you drop a new one in.');
      reset.onclick = async () => {
        try { await post(`/api/roll/${roll.side}`, { stock: stock.id, remaining: stock.per_roll }); await loadState(); renderPrinter(); toast('Counted as a full roll.', 'good'); }
        catch (error) { fail(error); }
      };
      const foot = el('div', 'foot'); foot.append(reset);
      bay.append(foot);
    } else if (stock) {
      bay.append(el('div', 'est',
        'Not counting what is left. Turn it back on under Settings below.'));
    }
    bay.append(lineUpBlock(roll, stock));
    bays.append(bay);
  }

  const table = $('stockTable');
  table.innerHTML = '';
  for (const stock of S.stocks) {
    const row = el('div', 'strow');
    row.append(el('span', 'nm', stock.name));
    /* The two numbers, in words. "2.25" × 1.25"" is the vendor's order and
     * says nothing about which one the head covers — which is the single
     * most common way a label comes out sideways, and it was written here in
     * the one notation that cannot answer it. */
    /* The margin rides with the two measurements, because it is the third
     * number that decides how big the artwork comes out and it was visible
     * nowhere on this screen — a roll somebody had given a 5mm border to
     * printed small labels floating in white with nothing on the panel
     * saying why. */
    row.append(el('span', 'dim',
      `${stock.across_in}\u2033 across \u00b7 ${stock.feed_in || '\u2014'}`
      + `${stock.feed_in ? '\u2033 along the roll' : ' (continuous)'}`
      + ` \u00b7 ${stock.margin_mm}mm border`));
    if (stock.sku) row.append(el('span', 'sku', stock.sku));
    /* One pill where three used to be, and it says a state rather than a
     * number: what a lined-up roll does is a sentence, and the sentence is
     * on the bay above where the roll actually is. Three pills carrying
     * three signed millimetres were three corrections a person could read
     * as one, which is how somebody types a paper position into a
     * registration offset. */
    if (stock.calibrated) {
      const pill = el('span', 'pill lined', 'lined up');
      pill.setAttribute('data-tip',
        'Somebody has printed the calibration labels for this roll and typed '
        + 'what they read. Press "Line up this roll" on its bay above to do '
        + 'it again, or Forget to go back to what the add-on shipped with.');
      row.append(pill);
    }
    if (stock.loaded)
      row.append(el('span', 'pill in', `in the ${stock.loaded_side} roll`));
    row.append(el('span', 'spacer'));
    // Everything after the spacer is a control, right-aligned together.

    /* ONE setting for which way text sits, and this is where it lives. It
     * used to be asked in three places — here, on the Quick tab and in the
     * design bar — which is three controls that can disagree about a
     * property of the roll. `turn_set` is the difference between a shape
     * BRUH Print guessed from and an answer somebody gave; they diverge the
     * moment the measurements are swapped. */
    /* The name is a LABEL beside the picker rather than the first three
     * words of every option. A <select> lays out to its widest option, so
     * "Text direction: automatic — along the roll" made a 373px control in
     * a 338px row on a phone — and what the browser cut off was the end,
     * which is the half that says what automatic decided. The label is once,
     * the answer is in the option, and both are readable. */
    const turnWrap = el('label', 'field inline turnfield');
    turnWrap.append(el('span', null, 'Text direction'));
    const turn = el('select', 'turnpick');
    /* "Automatic" that does not say what it decided is a setting you cannot
     * check without printing one, so the derived answer rides in the
     * option's own text and the closed select reads as the answer. */
    const derived = stock.turn === 90 ? 'along the roll' : 'across the label';
    for (const [value, text] of [
      ['', `Automatic \u2014 ${derived}`],
      ['0', 'Across the label'],
      ['90', 'Along the roll'],
    ]) {
      const option = el('option', null, text);
      option.value = value;
      turn.append(option);
    }
    turn.value = stock.turn_set ? String(stock.turn) : '';
    turn.setAttribute('data-tip',
      'Which way the words sit on this label, every time one is printed — '
      + 'the Quick tab and the designer both follow it. Automatic reads it '
      + 'off the shape: a stock much longer than it is wide is a wrap-around '
      + 'label and its text runs along the roll.');
    turn.onchange = async () => {
      try {
        await post(`/api/stock/${stock.id}/turn`,
                   { turn: turn.value === '' ? null : Number(turn.value) });
        await loadState(); renderPrinter(); fillPickers();
        toast('Saved.', 'good');
      } catch (error) { fail(error); }
    };
    turnWrap.append(turn);
    row.append(turnWrap);

    /* "Edit" is a verb with no object, which is the pattern that already
     * cost this panel two controls nobody could name — and the object here
     * is the one people came looking for and could not find. The first
     * thing behind this button is what the roll is CALLED: a catalog row
     * says "Chemical-Resistant Cryo Labels" and the roll in the bay is the
     * freezer labels, and nothing on the screen suggested that was
     * somebody's to change. */
    const edit = el('button', 'btn tiny', 'Rename or resize');
    edit.setAttribute('data-tip',
      'What this roll is called, the two measurements, the margin and how '
      + 'many are on a roll. This is also where you say the two numbers are '
      + 'the wrong way round.');
    edit.onclick = () => editStockDialog(stock);
    const remove = el('button', 'btn tiny danger', stock.builtin ? 'Hide' : 'Delete');
    remove.onclick = async () => {
      try { await del(`/api/stock/${stock.id}`); await loadState(); renderPrinter(); }
      catch (error) { fail(error); }
    };
    row.append(edit, remove);
    table.append(row);
  }

  const settings = $('settings');
  settings.innerHTML = '';
  const toggles = [
    ['enforce_stock', 'Refuse a label whose stock is not in the roll',
      'On by default. Printing a 2.25" raster onto a 0.56" roll runs across '
      + 'the liner, once per copy.'],
    ['quick_uppercase', 'Quick labels are UPPERCASE', ''],
    ['track_remaining', 'Keep an estimate of how many labels are left',
      'Counted down from whatever you set when you loaded the roll. Nothing '
      + 'on a LabelWriter reports the real level, so it is only as good as '
      + 'the last time you told it. Turn this off to just print.'],
  ];
  /* Not a toggle: three named shapes for the bytes, because whether a given
   * LabelWriter firmware takes every command in the preamble is the one
   * thing this add-on cannot find out from inside a container. A printer
   * that accepts a job and prints nothing is otherwise a guessing game
   * played one release at a time. */
  const modeWrap = el('label', 'field');
  modeWrap.append(el('span', null, 'If nothing comes out'));
  const mode = el('select');
  for (const [value, text] of [
    ['standard', 'Standard — recommended'],
    ['compact', 'Compact — smaller jobs, not every printer understands it'],
    ['bare', 'Bare minimum — no roll select (Twin Turbo picks its own bay)'],
  ]) {
    const option = el('option', null, text);
    option.value = value;
    mode.append(option);
  }
  mode.value = S.settings.print_mode || 'standard';
  mode.onchange = async () => {
    try { await post('/api/settings', { print_mode: mode.value }); await loadState(); }
    catch (error) { fail(error); }
  };
  modeWrap.append(mode);
  settings.append(modeWrap);
  settings.append(el('p', 'lede',
    'The printer takes the job and prints nothing? Change this, then press '
    + 'Print a check label on a bay above. Standard is what everything is '
    + 'tested against; '
    + 'try the others in order. Tell us which one worked — a LabelWriter '
    + 'cannot be asked which commands it understands, so this is the only '
    + 'way to find out. Bare minimum also drops the darkness and speed '
    + 'commands.'));

  /* Darkness and speed. Both are commands in the same preamble, so `bare`
   * above overrides both — it sends neither, which is the whole reason it
   * exists, and the lede on that select says so. */
  for (const [key, label, fallback, options, lede] of [
    ['density', 'Darkness', 'dark', [
      ['dark', 'Dark — recommended'],
      ['normal', "Normal — the printer's own default"],
      ['medium', 'Medium'],
      ['light', 'Light'],
    ], 'How much heat the head puts into each dot. A LabelWriter left to '
      + 'itself prints at Normal, which on ordinary thermal stock comes out '
      + 'faint. Turn it down if labels smudge or the paper curls.'],
    ['quality', 'Print speed', 'graphics', [
      ['graphics', "Slow & dark — recommended (the printer's "
        + '"barcodes and graphics" mode)'],
      ['text', 'Fast (text mode)'],
    ], 'The slow mode steps the paper at 600 lines to the inch instead of '
      + '300, so the head dwells twice as long over every line: darker, and '
      + "more accurate for barcodes and QR codes. Fast is the printer's "
      + 'own default and roughly halves the time a long run takes.'],
  ]) {
    const wrap = el('label', 'field');
    wrap.append(el('span', null, label));
    const select = el('select');
    for (const [value, text] of options) {
      const option = el('option', null, text);
      option.value = value;
      select.append(option);
    }
    select.value = S.settings[key] || fallback;
    select.onchange = async () => {
      try { await post('/api/settings', { [key]: select.value }); await loadState(); }
      catch (error) { fail(error); }
    };
    wrap.append(select);
    settings.append(wrap);
    settings.append(el('p', 'lede', lede));
  }

  for (const [key, label, help] of toggles) {
    const wrap = el('label', 'check');
    const input = el('input'); input.type = 'checkbox';
    input.checked = !!S.settings[key];
    input.onchange = async () => {
      try { await post('/api/settings', { [key]: input.checked }); await loadState(); }
      catch (error) { fail(error); }
    };
    wrap.append(input, el('span', null, label));
    settings.append(wrap);
    if (help) settings.append(el('p', 'lede', help));
  }
}

/* ── Lining a roll up ────────────────────────────────────────────────────
 *
 * Every release from 0.6.0 to 0.8.x answered a misaligned label by adding a
 * box to type a millimetre into, and by 0.8.4 there were four of them —
 * across offset, feed offset, paper position, gap — with four different
 * signs, four different meanings, and no way for a person holding a wrong
 * label to tell which one was theirs. The owner printed, measured, typed,
 * printed again, and asked for the boxes to go. They were right: a
 * correction somebody guesses is a guess whatever it is called, and the
 * printer had already answered every question that mattered on a piece of
 * paper nobody was reading properly.
 *
 * So there is one control per bay and it prints. Two labels come out, six
 * numbers are read off them with the label's own printed ladders, and
 * `calibration.derive` decides which of the three things this printer is
 * doing. Six rather than five because the two signs are read off opposite
 * ends: a printer starting EARLY cuts the ladder and the number at the die
 * cut is the distance, while one starting LATE prints nothing at all up
 * there, so its dead band is only measurable from the far edge against the
 * label's catalogued length — which means both ends of both copies.
 * Nothing here does arithmetic on a reading: what is typed goes to the
 * server as it was typed, because a panel that adjusted a number on its way
 * in would be a seventh place a millimetre could be wrong.
 */

/* One millimetre, written the same way everywhere it is shown. A bay
 * sentence saying 4.7 and a wizard saying 4.70 are two readings of one
 * measurement to anybody who did not write them. */
const mmText = (value) => `${Number(value).toFixed(1)} mm`;

/* What this roll does, in the roll's own words.
 *
 * `Not lined up yet` is a different sentence from `prints from the die cut`
 * and that difference is the whole of `Calibration.measured`: a printer that
 * needs no correction stores seven default numbers, and a panel that could
 * not tell it from one nobody has measured would offer the wizard for ever
 * to the person who least needs it. */
/* The held-edge half of `calibrationSentence`, or '' where nothing is held.
 *
 * Reads `holds_mm` — the four-list the store publishes — and falls back to
 * the older `hold_trailing_mm` spelling, because a panel is served once and
 * then answers requests from an add-on that may have been updated under it. */
function calHoldClause(stock) {
  const raw = Array.isArray(stock.holds_mm)
    ? stock.holds_mm
    : [0, Number(stock.hold_trailing_mm) || 0, 0, 0];
  const held = CAL_SIDES
    .map(([, name], index) => [name, Number(raw[index]) || 0])
    .filter(([, value]) => value > 0);
  if (!held.length) return '';
  const same = held.every(([, value]) => value === held[0][1]);
  const names = listWords(held.map(([name]) => name.toLowerCase()));
  if (same)
    return `you asked for ${mmText(held[0][1])} clear at the ${names}`;
  return 'you asked to keep clear ' + listWords(
    held.map(([name, value]) => `${mmText(value)} at the ${name.toLowerCase()}`));
}

/* `a, b and c` — an English list, because this lands mid-sentence in prose
 * somebody reads rather than in a table. */
function listWords(words) {
  if (words.length < 2) return words[0] || '';
  return words.slice(0, -1).join(', ') + ' and ' + words[words.length - 1];
}

function calibrationSentence(stock) {
  if (!stock) return 'Nothing is in this bay, so there is nothing to line up.';
  if (!stock.calibrated) return 'Not lined up yet.';
  const cal = stock.calibration || {};
  const bits = [];
  if (cal.across_mm)
    bits.push(`sits ${mmText(cal.across_mm)} along the head`);
  /* `dead_leading_mm` and not `start_mm`, because the two differ exactly
   * where a person reads them: a negative start is not a dead band, it is a
   * job that feeds before it prints, and the whole label is usable. */
  if (stock.dead_leading_mm)
    bits.push(`the printer starts ${mmText(stock.dead_leading_mm)} in`);
  else if (cal.start_mm < 0)
    bits.push(`every job feeds ${mmText(-cal.start_mm)} before it prints`);
  /* Said in the person's own words — "you asked" — because it is the one
   * thing in this sentence nothing measured, and a roll reading back a
   * choice as though it were a fact about the printer is how somebody
   * concludes their machine is worse than it is.
   *
   * All four in ONE clause, named by side, in `CAL_SIDES`' order so the
   * sentence reads in the order the boxes are laid out. Four clauses would
   * push a roll with a border on every edge into a sentence nobody finishes,
   * and the sizes are usually the same number anyway — which the joined form
   * shows and four separate clauses would hide. */
  const held = calHoldClause(stock);
  if (held) bits.push(held);
  if (cal.after_tear_mm)
    bits.push('the first label after a tear-off starts '
      + `${mmText(stock.first_label_dead_mm)} in`);
  if (cal.job_start === 'reset')
    bits.push('every job opens with the printer’s own reset');
  if (!bits.length) return 'Lined up: prints from the die cut.';
  return `Lined up: ${bits.join('; ')}.`;
}

/* The bay's own block: what this roll does, one press that measures it, and
 * two small things you do afterwards.
 *
 * It is on the BAY and not on the printer card because it is a fact about a
 * roll — where the sense hole sits relative to the die cut is punched into
 * the paper — and a Twin Turbo with two rolls genuinely has two answers. A
 * button on the card would have to ask which one you meant, which is the
 * question the bay has already answered by being the bay. */
function lineUpBlock(roll, stock) {
  const wrap = el('div', 'calbay');
  /* Continuous paper has no die cuts, so it has no sense holes and no top of
   * form — there is nothing on it for a reading to be measured from, and the
   * calibration label's own ladder is drawn against a label length it does
   * not have. Said here rather than left to be found at the end of two
   * printed labels and a refusal about a number that was never on the
   * paper. */
  const rollable = !!stock && !!stock.feed_in;
  wrap.append(el('p', 'calstate', rollable
    ? calibrationSentence(stock)
    : (stock
        ? 'Continuous paper has no die cuts, so there is no top of form to '
          + 'line up to.'
        : calibrationSentence(stock))));

  const go = el('button', 'btn primary wide', 'Line up this roll');
  go.id = `lineUp-${roll.side}`;
  go.disabled = !rollable;
  go.setAttribute('data-tip', rollable
    ? 'Prints one label with a numbered grid and asks where the label\u2019s '
      + 'four edges fall on it. Re-open it any time — the numbers come back '
      + 'filled in, so a small change is one box.'
    : (stock
        ? 'Nothing to measure: the printer finds the top of a label by the '
          + 'hole punched between two of them, and continuous paper has '
          + 'neither.'
        : 'Pick what is in this bay first. Where the printing starts is a '
          + 'property of the roll, so there is nothing to measure until '
          + 'there is one.'));
  go.onclick = () => lineUpDialog(stock, roll.side);
  wrap.append(go);

  /* The last label of a job left inside the printer rather than pushed out
   * to the tear bar. Only a roll whose calibration asked for it ends that
   * way, so the button that gets it out only exists there — a Feed on every
   * bay is a control that does nothing on nearly all of them. */
  const cal = (stock && stock.calibration) || {};
  if (cal.ending === 'hold')
    wrap.append(el('p', 'est',
      'The last label is held inside so the next print lines up; press to '
      + 'feed it out.'));

  const foot = el('div', 'foot');
  const check = el('button', 'btn tiny', 'Print a check label');
  check.id = `checkLabel-${roll.side}`;
  /* Offered on continuous paper, unlike the wizard: a frame drawn around
   * everything this roll can print on is a real answer there — it is the
   * artwork's own length — and it is the fastest way to see that a job is
   * coming out at all. */
  check.disabled = !stock;
  check.setAttribute('data-tip',
    'One label: a frame around everything this roll can print on. If it '
    + 'reaches all four edges the roll is lined up, and a missing side says '
    + 'which way it is out.');
  check.onclick = async () => {
    try {
      const data = await post('/api/printer/check',
                              { stock: stock.id, side: roll.side });
      toast(`Check label printed on the ${data.side} roll.`, 'good');
    } catch (error) { fail(error); }
  };
  foot.append(check);

  if (cal.ending === 'hold') {
    const feed = el('button', 'btn tiny', 'Feed');
    feed.id = `feedRoll-${roll.side}`;
    feed.setAttribute('data-tip',
      'Moves the paper to the tear bar. It prints nothing.');
    feed.onclick = async () => {
      try { await post('/api/printer/feed', { side: roll.side }); toast('Fed to the tear bar.', 'good'); }
      catch (error) { fail(error); }
    };
    foot.append(feed);
  }

  /* Only where there is something to forget. A button that clears nothing
   * is a control asking to be understood, and the answer would be "it does
   * what has already happened". */
  if (stock && stock.calibrated) {
    const forget = el('button', 'btn tiny danger', 'Forget');
    forget.id = `forgetCal-${roll.side}`;
    forget.setAttribute('data-tip',
      'Throws the measurement away and prints exactly what the add-on '
      + 'shipped with. Not a reset to a guessed default — to nothing.');
    forget.onclick = async () => {
      try {
        await del(`/api/stock/${stock.id}/calibration`);
        await loadState(); renderPrinter(); fillPickers();
        toast('Forgotten. This roll prints as it did before.', 'good');
      } catch (error) { fail(error); }
    };
    foot.append(forget);
  }
  wrap.append(foot);
  return wrap;
}


/* ── The wizard ──────────────────────────────────────────────────────────
 *
 * Three steps and a picture. It reuses `#modal` — the panel has one dialog
 * and every dialog in it is markup written into `#modalBody`, so a second
 * one would be a second thing to keep true about focus, Escape and the
 * backdrop.
 *
 * **Four coordinates, because the question is where the printable area is.**
 * 0.9.x asked it as an offset — how far is the first row from the die cut,
 * and which way — and that is not a thing drawn on a label. It has to be
 * inferred, from which end of a scale got cut and from one copy compared
 * against another, and the sign is exactly the part nobody can see. Hence
 * three hypotheses, six readings, two prints, and two of the six read from
 * the opposite end of the label to the thing they were about.
 *
 * A rectangle is drawn on the label. The grid covers the whole area the
 * printer can reach and the paper lies on it, so its four edges are read the
 * way a point is read off graph paper — no sign, no inference, no case to
 * decide first. See `calibration.py` for the arithmetic and for the one
 * thing the grid cannot show (a top edge above the grid, which reads 0
 * because that is what a coordinate does at the end of a scale).
 *
 * The four readings and their instructions live in one table, because the
 * drawing, the fields and the request all have to agree about which letter
 * names which number. Three copies of that mapping is three chances for the
 * label on screen to point at the wrong box.
 *
 * **What is on screen is the instruction; the argument for it is not.** A
 * person standing at a printer holding a label does not need an argument,
 * they need to be told what to look at — so a reading is three things and
 * nothing else: what to look for (`how`, in ink), what to type, and what to
 * do when the obvious thing is not there (`note`, the aside, which may never
 * carry anything needed to get the number right).
 */
const CAL_READINGS = [
  ['x1', 'X1', 'Left edge of the label',
    'The number on a black strip where the label’s left-hand edge falls.',
    'The strip’s numbers count up from left to right. If they count down, '
    + 'turn the label round.'],
  ['x2', 'X2', 'Right edge of the label',
    'The number on that same strip where the label’s right-hand edge falls.',
    'Leave it empty if the strip stops short of the edge — that means the '
    + 'label is wider than the print head, so there is nothing printed out '
    + 'there to read. Everything else still works without it.'],
  ['y1', 'Y1', 'Top edge of the label',
    ['The number in a plain column where the label’s top edge falls.',
     'If the top edge is above the grid — the grid’s own 0 is printed with '
     + 'blank label above it — then Y1 is 0. The grid starts where the '
     + 'printer starts, and nothing can be printed higher up than that.'],
    'That blank band is normal and it is not measured here, because there is '
    + 'nothing printed inside it to read. How deep it is comes out of Y2 and '
    + 'the label’s catalogued length.'],
  ['y2', 'Y2', 'Bottom edge of the label',
    'The number in that same column where the label’s bottom edge falls.',
    'The grid runs on past the end of the label and into the next one, so '
    + 'this edge is always on it — that overrun is the whole reason the '
    + 'sheet is longer than a label.'],
];

/* The four edges of the area to print in, in the order they are asked.
 *
 * A separate table from `CAL_READINGS` and deliberately so: those four are
 * COORDINATES a person reads off a printed grid, and these four are
 * DISTANCES they choose. Sharing one table would put a preference among the
 * measurements at the moment it stops being obvious which is which — and
 * the readings work precisely because none of them is a preference.
 *
 * `leading`/`trailing` rather than `top`/`bottom` in the key, because that
 * is what the printer's own axes call them and what the stored field is;
 * the NAME is top and bottom, because that is what a person holding the
 * label is looking at. */
const CAL_SIDES = [
  ['leading', 'Top'],
  ['trailing', 'Bottom'],
  ['left', 'Left'],
  ['right', 'Right'],
];

/* Two things to do rather than four questions: one pair across the label,
 * one pair down it. They are also the two scales, so the grouping is what
 * says which scale each pair is read from. */
const CAL_GROUPS = [
  ['Across the label', ['x1', 'x2'],
    'Both off a black strip — white numbers on black, running across the '
    + 'label. There are several down the sheet; they all say the same thing, '
    + 'so use whichever is nearest the edge you are reading.'],
  ['Down the label', ['y1', 'y2'],
    'Both off a plain column — black numbers on white, running down the '
    + 'label, counting from 0 at the first row the printer laid.'],
];

/* The readings that would produce the calibration this roll already has.
 *
 * Not "what you typed last time" — nothing keeps that, and it would be the
 * wrong thing to keep anyway: what matters is the answer in force, and this
 * is the only honest way to show it back in the units it was given in. Three
 * of the four fall straight out of the stored numbers, because `derive` is
 * arithmetic and arithmetic runs backwards:
 *
 *   X1  IS `across_mm`. The left edge is stored as it was read.
 *   Y1  is 0 for a roll whose printer starts late (the leading edge was
 *       above the grid), and `-start_mm` for one that starts early, which
 *       is the coordinate the die cut cut the scale at.
 *   Y2  is Y1 plus the label's own length for the early roll, and the
 *       catalogued length less the dead band for the late one.
 *
 * X2 is the one that cannot come back, and that is not an oversight: the
 * right edge sets NOTHING on a `Calibration` — it is read to say whether
 * the roll measures what its stock row claims, and that is a sentence
 * rather than a stored number. An empty box is the honest answer, and the
 * field already explains what leaving it empty means.
 *
 * `derive` is what proves this, and the claim is worth stating exactly:
 * handed these four it returns the calibration they came from, so a person
 * who changes nothing and presses Apply changes nothing. Measured over four
 * applications it is a FIXED POINT for every answer this wizard stored —
 * which is not free, and is the reason the display rounds to a tenth: a
 * reading is a tenth of a millimetre, `start_mm` is derived as
 * `catalog - Y2` and carries two, and showing back a number nobody could
 * have read off the scale is what would make each visit move it. The one
 * case that is not exact is a roll calibrated by an older release, where
 * `start_mm` came from somewhere other than a reading; there it settles on
 * its nearest tenth at the first Apply, which is under a millimetre and
 * under one dot of the print head. That is the whole point — it is what
 * makes changing ONE number a small adjustment rather than a
 * re-measurement. */
function calStoredReadings(stock) {
  const blank = { x1: '', x2: '', y1: '', y2: '' };
  if (!stock || !stock.calibrated) return blank;
  const cal = stock.calibration || {};
  const catalog = Number(stock.feed_mm) || 0;
  const start = Number(cal.start_mm) || 0;
  const length = (cal.length_mm === null || cal.length_mm === undefined)
    ? catalog : (Number(cal.length_mm) || 0);
  /* One decimal, because that is what the boxes step in and what a person
   * reading a printed millimetre scale can honestly claim. A stored 4.7
   * that came back as 4.7000000000000002 would read as a machine number
   * somebody is not allowed to touch. */
  const mm = (value) => (Number.isFinite(value) ? String(Math.round(value * 10) / 10) : '');
  const y1 = start < 0 ? -start : 0;
  const y2 = start < 0 ? y1 + length : Math.max(0, catalog - start);
  return { x1: mm(Number(cal.across_mm) || 0), x2: '', y1: mm(y1), y2: mm(y2) };
}

/* The four bands this roll is set to keep clear, as strings for the boxes.
 *
 * Unlike the readings these need no reconstruction — they are stored
 * exactly as they were typed, because nothing derived them. What they still
 * need is the same rule the readings follow: a zero comes back as an EMPTY
 * box rather than as "0", because the placeholder already says `nothing`
 * and a form of four zeroes reads as four decisions somebody made. */
/* What the trailing band has to be for the two blank edges to match.
 *
 * The top of a label loses the printer's own dead band AND whatever was
 * asked for at the top; the bottom loses only what was asked for there. So
 * evening them up is one addition — and it lives here rather than in the two
 * buttons that press it, because a control on the reading step and a control
 * on the done step giving different answers to "make these match" is the
 * kind of disagreement nobody would think to look for. The stock's own
 * margin is on both ends by definition and cancels. */
function evenTrailing(dead, leading) {
  return Math.round(((Number(dead) || 0) + (Number(leading) || 0)) * 100) / 100;
}

function calStoredHolds(stock) {
  const held = (stock && stock.holds_mm) || [];
  const out = {};
  CAL_SIDES.forEach(([side], index) => {
    const value = Number(held[index]) || 0;
    out[side] = value ? String(value) : '';
  });
  return out;
}

function lineUpDialog(stock, side) {
  if (!stock) return;
  /* No `stock &&` here, unlike `lineUpBlock` one function up: that one is
   * drawn for an EMPTY bay too and really can be handed nothing, and this
   * one has just returned on it. Carrying the guard across was CodeQL's
   * "useless conditional", and it is worth the fix rather than a dismissal —
   * a redundant test reads as "this might be null", which contradicts the
   * line above it and is how the next reader adds a second one. */
  const cal = stock.calibration || {};
  const state = {
    stock, side, notes: [], message: '',
    readings: calStoredReadings(stock),
    holds: calStoredHolds(stock),
  };
  const body = $('modalBody');
  body.innerHTML = '';
  const wrap = el('div', 'calwiz');
  wrap.id = 'lineUp';
  body.append(wrap);
  /* A roll that has been lined up already opens on the numbers rather than
   * on the press that prints. Coming back to this is almost always a
   * nudge — one edge read again, or a band held at the bottom — and making
   * that start with a wasted label is what made it a thing people put off.
   * The grid is one press away at the top of that step. */
  if (stock.calibrated) calReadStep(state, wrap);
  else calPrintStep(state, wrap, '');
  $('modal').showModal();
}

/* Every step ends the same way: a row of actions with Close on it. A dialog
 * whose only exit is Escape is a dialog somebody is stuck in on a phone,
 * where there is no Escape key. */
function calActions(wrap, ...buttons) {
  const actions = el('div', 'actions');
  const close = el('button', 'btn', 'Close');
  close.id = 'lineUpClose';
  close.onclick = async () => {
    $('modal').close();
    try { await loadState(); renderPrinter(); fillPickers(); }
    catch (error) { fail(error); }
  };
  actions.append(...buttons, close);
  wrap.append(actions);
}

function calPrintStep(state, wrap, why) {
  wrap.dataset.step = 'print';
  wrap.innerHTML = '';
  wrap.append(el('h2', null, `Line up ${state.stock.name}`));
  wrap.append(el('p', 'lede', why
    || 'Where a printer starts laying ink on a roll is a property of that '
       + 'roll, and nothing can work it out without printing something and '
       + 'looking at it. One label prints with a numbered grid on it; you '
       + 'read off where the label’s four edges fall, and this roll is lined '
       + 'up for good.'));
  /* Said before the press and not after it: this sheet is drawn to the whole
   * print head and run on past the end of the label, so part of it lands on
   * the backing and part on the label after it. Both are deliberate and both
   * are what makes the grid an instrument — somebody who finds that out by
   * looking at the platen is somebody the panel lied to by omission. */
  wrap.append(el('p', 'muted small',
    'The grid is drawn to the full width of the print head and runs on past '
    + 'the end of the label, so some of the ink lands on the backing and on '
    + 'the next label. That is the part that tells you where the paper is.'));

  const go = el('button', 'btn primary big wide', 'Print');
  go.id = 'lineUpPrint';
  go.onclick = async () => {
    go.disabled = true;
    try {
      const data = await post('/api/printer/calibrate',
        { stock: state.stock.id, side: state.side });
      state.notes = data.notes || [];
      state.message = '';
      calReadStep(state, wrap);
    } catch (error) { go.disabled = false; fail(error); }
  };
  wrap.append(go);
  calActions(wrap);
}

/* How to hold the label and what is printed on it, said before the first box
 * and not inside one.
 *
 * Three things a person cannot get off the paper: which end is the top (the
 * scale counts away from the leading edge, which is knowable only from the
 * renderer), which of the two scales is which, and what the marks are a
 * scale OF. Every one of the four readings is meaningless without all three,
 * and none of them is obvious to anybody who has not read the renderer. */
const CAL_HOLDING = [
  ['Which way up', 'Hold the label so the plain columns count downwards. '
    + 'The end with the small numbers is the top, and it is the end that '
    + 'came out of the printer first.'],
  ['Which scale is which', 'The white numbers on the black strips run '
    + 'ACROSS the label — those are X. The black numbers in the plain '
    + 'columns run DOWN it — those are Y.'],
  ['What the numbers are', 'Millimetres, counting from the corner the '
    + 'printer starts at. Every scale has a number every 5mm and a tick '
    + 'every 1mm, so where an edge falls between two numbers you count the '
    + 'ticks — an edge two ticks past the 25 reads 27.'],
];

/* The two labels this step can print, at the top of it.
 *
 * Lining a roll up is a LOOP — read, apply, look at what came out, change
 * one number — and the wizard shipped as a line: the only route back to a
 * printed label was to close the dialog, find the bay, press a button on
 * the card, and open the wizard again, which lost every number on the way.
 * So both prints live where the numbers are typed, each named for what it
 * puts out rather than for what it is for.
 *
 * The check label is offered only for a roll that has an answer stored,
 * because that is what it draws: a frame around the printable area as this
 * roll is currently set, which on a roll nobody has measured is a frame
 * around the whole label and tells you nothing. `Forget`'s rule — a button
 * that would do nothing is a control asking to be understood.
 *
 * Neither one leaves the step or clears a box. That is the whole feature. */
function calPrintRow(state, wrap) {
  const row = el('div', 'calprints');
  const again = el('button', 'btn', 'Print the grid again');
  again.id = 'calPrintAgain';
  again.setAttribute('data-tip',
    'One label with the numbered grid on it — the same sheet you read '
    + 'these numbers off. Nothing you have typed is cleared.');
  again.onclick = async () => {
    again.disabled = true;
    try {
      const data = await post('/api/printer/calibrate',
        { stock: state.stock.id, side: state.side });
      state.notes = data.notes || [];
      toast('Grid printed. Read it and change what needs changing.', 'good');
      calReadStep(state, wrap);
    } catch (error) { fail(error); } finally { again.disabled = false; }
  };
  row.append(again);

  if (state.stock.calibrated) {
    const check = el('button', 'btn', 'Print a check label');
    check.id = 'calCheckHere';
    check.setAttribute('data-tip',
      'One label with a frame around the area this roll prints in AS IT IS '
      + 'SET NOW — not as the boxes below say. Press Apply first to check '
      + 'a change.');
    check.onclick = async () => {
      check.disabled = true;
      try {
        await post('/api/printer/check',
                   { stock: state.stock.id, side: state.side });
        toast('Check label printed.', 'good');
      } catch (error) { fail(error); } finally { check.disabled = false; }
    };
    row.append(check);
  }
  wrap.append(row);
}

function calReadStep(state, wrap) {
  wrap.dataset.step = 'read';
  wrap.innerHTML = '';
  wrap.append(el('h2', null, 'Where the label sits on the grid'));
  if (state.message) wrap.append(el('p', 'calsentence', state.message));
  calPrintRow(state, wrap);
  wrap.append(el('p', 'lede',
    'Four numbers off the label with the grid on it: where each of its edges '
    + 'falls. Every one is a millimetre read off a scale printed on the same '
    + 'label, so there is nothing to measure with and nothing to convert.'));
  /* Said once, above the boxes, and only where they are not empty. A person
   * who does not know a field was filled in for them is a person who reads
   * a number they never measured as one they did. */
  if (state.stock.calibrated)
    wrap.append(el('p', 'muted small',
      'These are filled in from what this roll is set to now, so you can '
      + 'change one and press Apply. The right-hand edge is the exception '
      + 'and starts empty: it is read to check the stock’s own measurements '
      + 'and is not part of the answer.'));

  const holding = el('dl', 'calhold');
  for (const [term, says] of CAL_HOLDING) {
    holding.append(el('dt', null, term));
    holding.append(el('dd', null, says));
  }
  wrap.append(holding);

  const split = el('div', 'calsplit');
  split.append(calDrawing());

  const fields = {};
  const list = el('div', 'calfields');
  const byKey = new Map(CAL_READINGS.map((row) => [row[0], row]));
  for (const [title, keys, lede] of CAL_GROUPS) {
    const group = el('div', 'calgroup');
    group.append(el('h3', null, title));
    group.append(el('p', null, lede));
    list.append(group);
    for (const [key, letter, name, how, note] of keys.map((k) => byKey.get(k))) {
      const field = el('label', 'field calfield');
      const head = el('span', 'calhead');
      head.append(el('i', 'calbadge', letter), el('b', null, name));
      field.append(head);
      /* The instruction, in ink. An array is a line per case, which is what
       * the one reading with a boundary needs — and a single grey span
       * carrying the rule, the exception and the reason together is what
       * made the old top reading unanswerable. */
      const steps = el('span', 'calhow');
      for (const line of (Array.isArray(how) ? how : [how]))
        steps.append(el('span', 'calcase', line));
      field.append(steps);
      const input = el('input');
      input.type = 'number';
      input.step = '0.1';
      /* Every one of the four is a COORDINATE on a scale that starts at 0,
       * so none of them can be negative — and a minus sign here is somebody
       * carrying over the old offset's convention, where it meant "the other
       * way". There is no other way now: the rectangle decides the sign. The
       * server refuses one too; this is the keyboard's half. */
      input.min = '0';
      input.inputMode = 'decimal';
      input.id = `cal${letter}`;
      input.value = state.readings[key];
      if (key === 'x2') input.placeholder = 'empty if the strip stops short';
      input.oninput = () => { state.readings[key] = input.value; };
      field.append(input);
      if (note) field.append(el('span', 'muted', note));
      fields[key] = input;
      list.append(field);
    }
  }
  /* The four numbers on this screen that are not read off anything.
   *
   * They are in their own group, under their own heading, because
   * everything above is a coordinate of the PAPER and these are a choice
   * about where to print on it — and the whole reason the four readings
   * work is that none of them is a preference. Mixing a preference in among
   * them would undo that at the moment it stops being obvious.
   *
   * 0.11.0 shipped ONE of these, at the bottom, and the argument for that
   * was wrong in a way worth writing down: it said a band held at the top
   * only pushes artwork further from the middle, so the only band worth
   * having is the one that evens out a printer starting late. True of the
   * feed axis, and it answers the wrong question — a person setting a
   * border is not compensating for a machine, they are saying where on the
   * label the printing goes, and the across axis has no dead band to
   * compensate for at all. `margin_mm` is the even border on all four
   * sides; this is the uneven one, which is the only kind a stock row
   * cannot express. */
  const choice = el('div', 'calgroup calchoice');
  choice.append(el('h3', null, 'Where to print on it'));
  choice.append(el('p', null,
    'Everything above says where the PAPER is — what the printer can reach. '
    + 'This is the area to use inside that, one number per edge. Leave them '
    + 'at nothing and labels use everything the printer can give them.'));
  list.append(choice);

  const holdInputs = {};
  const grid = el('div', 'calsides');
  for (const [side, name] of CAL_SIDES) {
    const field = el('label', 'field calfield calside');
    const head = el('span', 'calhead');
    head.append(el('b', null, name));
    field.append(head);
    const input = el('input');
    input.type = 'number';
    input.step = '0.1';
    input.min = '0';
    input.inputMode = 'decimal';
    input.id = `calHold${side[0].toUpperCase()}${side.slice(1)}`;
    input.placeholder = 'nothing';
    input.value = state.holds[side] || '';
    input.oninput = () => { state.holds[side] = input.value; };
    field.append(input);
    holdInputs[side] = input;
    grid.append(field);
  }
  list.append(grid);
  /* One sentence under the four rather than a note per box, and that is a
   * measurement rather than a preference: two of the four had one, which
   * left the grid's rows different heights and its two columns ragged — a
   * form that looks like a mistake before anybody has typed in it. What
   * those notes said is the same fact about all four anyway. */
  list.append(el('p', 'muted small calsidenote',
    'These are on top of what the printer already cannot reach: the band at '
    + 'the leading edge on a roll that starts late, and the far edge of a '
    + 'label wider than the print head. The designer draws the label without '
    + 'any of it, so what you lay out is what comes back, and a check '
    + 'label’s frame comes in to meet it.'));

  /* Offered only where the number it would type is known, which is after an
   * Apply. It reads the roll's OWN dead band off the stock row rather than
   * working it out from the boxes above — that arithmetic lives in
   * `derive` and a second copy of it here is a second answer to where the
   * printing starts. */
  const dead = Number(state.stock.dead_leading_mm) || 0;
  if (dead > 0) {
    const match = el('button', 'btn tiny', 'Even up the ends');
    match.id = 'calHoldMatch';
    match.type = 'button';
    match.setAttribute('data-tip',
      'The printer can’t reach the first ' + mmText(dead) + ' of this '
      + 'label, so the bottom is set to that plus whatever you asked for at '
      + 'the top — which leaves the same blank edge at each end.');
    /* Read when it is PRESSED, not when it is drawn: the top box is one
     * control away and this is the number it changes. A figure baked into
     * the label would go stale the moment somebody typed in it, which on a
     * button whose whole job is to agree with that box is worse than no
     * figure at all. */
    match.onclick = () => {
      holdInputs.trailing.value =
        String(evenTrailing(dead, holdInputs.leading.value));
      state.holds.trailing = holdInputs.trailing.value;
    };
    list.append(match);
  }

  split.append(list);
  wrap.append(split);

  const notesList = el('ul', 'notes');
  notes(notesList, state.notes);
  wrap.append(notesList);

  const apply = el('button', 'btn primary big wide', 'Apply');
  apply.id = 'calApply';
  apply.onclick = async () => {
    const readings = {};
    for (const [key] of CAL_READINGS) {
      const typed = String(fields[key].value).trim();
      /* An empty box reaches the server as null and never as 0. `Number('')`
       * is zero, and zero is a real coordinate here — it is what the top
       * edge reads when the label starts above the grid — so a box that
       * silently became it would not be a slightly wrong calibration, it
       * would be a different rectangle. */
      readings[key] = typed === '' ? null : Number(typed);
    }
    /* A hold is the one kind of field here where an empty box and a typed
     * 0 mean the same thing — keep nothing clear — so it may become a
     * number, where a reading may not. */
    const holds = {};
    for (const [side] of CAL_SIDES) {
      const typed = String(holdInputs[side].value).trim();
      holds[side] = typed === '' ? null : Number(typed);
    }
    apply.disabled = true;
    try {
      const data = await post(
        `/api/stock/${state.stock.id}/calibration`, { readings, holds });
      await loadState(); renderPrinter(); fillPickers();
      state.stock = stockById(state.stock.id) || state.stock;
      state.message = data.sentence;
      if (data.calibration === null) calReadStep(state, wrap);
      else calDoneStep(state, wrap, data);
    } catch (error) { apply.disabled = false; fail(error); }
  };
  wrap.append(apply);
  calActions(wrap);
}

function calDoneStep(state, wrap, data) {
  wrap.dataset.step = 'done';
  wrap.innerHTML = '';
  wrap.append(el('h2', null, 'Lined up'));
  wrap.append(el('p', 'calsentence', data.sentence));

  /* Offered, never applied. Two measurements that match the catalog's the
   * other way round is evidence about somebody's stock row, and quietly
   * swapping a roll's dimensions on one reading is exactly the sort of
   * helpful correction that loses a measurement they made with a ruler. */
  if (data.swap_suggested) {
    wrap.append(el('p', 'lede',
      'Those two measurements match this stock’s the other way round, so '
      + 'the roll is probably described back to front. Swapping exchanges '
      + 'them and clears what was just measured — it was read off a label '
      + 'the wrong way round — so line the roll up again afterwards.'));
    const swap = el('button', 'btn wide', 'These are the wrong way round');
    swap.id = 'calSwap';
    swap.onclick = async () => {
      try {
        await post(`/api/stock/${state.stock.id}/swap`, {});
        await loadState(); renderPrinter(); fillPickers();
        state.stock = stockById(state.stock.id) || state.stock;
        state.readings = { x1: '', x2: '', y1: '', y2: '' };
        calPrintStep(state, wrap,
          'Swapped. Run Line up again — the numbers you just typed were '
          + 'read off a label the other way round.');
      } catch (error) { fail(error); }
    };
    wrap.append(swap);
  }

  /* The moment the asymmetry becomes a known number, which is the only
   * moment it can be offered as one press. It is not on the reading step's
   * own terms — nothing there knows the dead band until Apply has derived
   * it — and it is not a default, because a roll somebody wants printed
   * edge to edge is a roll that should get every millimetre it has. */
  const dead = Number(state.stock.dead_leading_mm) || 0;
  const holds = calStoredHolds(state.stock);
  const want = evenTrailing(dead, holds.leading);
  const held = Number(holds.trailing) || 0;
  if (dead > 0 && Math.abs(held - want) > 0.05) {
    wrap.append(el('p', 'lede',
      `The printer can’t reach the first ${mmText(dead)} of this label, so `
      + 'the blank edge at the top is that much deeper than the one at the '
      + `bottom. Keeping ${mmText(want)} clear at the bottom makes them `
      + 'match — it costs that much printable length and nothing else.'));
    const even = el('button', 'btn wide', 'Make the blank edges match');
    even.id = 'calEven';
    even.onclick = async () => {
      even.disabled = true;
      /* The other three carried over rather than cleared: this press is
       * about the two ends of the feed axis and must not quietly drop a
       * band somebody set on the across one — which is also why the number
       * it types is `dead` PLUS whatever is held at the top. */
      state.holds = { ...holds, trailing: String(want) };
      try {
        const readings = {};
        for (const [key] of CAL_READINGS) {
          const value = String(state.readings[key] ?? '').trim();
          readings[key] = value === '' ? null : Number(value);
        }
        const answer = await post(
          `/api/stock/${state.stock.id}/calibration`, {
            readings, holds: state.holds,
          });
        await loadState(); renderPrinter(); fillPickers();
        state.stock = stockById(state.stock.id) || state.stock;
        state.message = answer.sentence;
        if (answer.calibration === null) calReadStep(state, wrap);
        else calDoneStep(state, wrap, answer);
      } catch (error) { even.disabled = false; fail(error); }
    };
    wrap.append(even);
  }

  const check = el('button', 'btn primary big wide', 'Print a check label');
  check.id = 'calCheck';
  check.onclick = async () => {
    try {
      await post('/api/printer/check',
                 { stock: state.stock.id, side: state.side });
      toast('Check label printed.', 'good');
    } catch (error) { fail(error); }
  };
  wrap.append(check);
  wrap.append(el('p', 'lede',
    'One label with a frame drawn around everything this roll can print on. '
    + 'All four sides showing means the answer was right; a missing side '
    + 'says which way it is still out.'));

  /* The way back, which the wizard did not have. Every ending here used to
   * be Close, so a frame that came back short of one edge meant closing the
   * dialog, finding the bay and starting again from an empty form — which
   * is what "I cannot see the old settings" was, one step further on. */
  const back = el('button', 'btn wide', 'Change the numbers');
  back.id = 'calBack';
  back.setAttribute('data-tip',
    'Back to the four coordinates, filled in with what is stored now.');
  back.onclick = () => {
    state.readings = calStoredReadings(state.stock);
    state.holds = calStoredHolds(state.stock);
    state.message = '';
    calReadStep(state, wrap);
  };
  wrap.append(back);
  calActions(wrap);
}


/* ── The drawing ─────────────────────────────────────────────────────────
 *
 * Drawn here rather than shipped as an asset, for the same reason nothing
 * else in this panel is: an image in the container is a second copy of what
 * the label looks like, and it goes stale the day the grid changes without
 * anybody noticing.
 *
 * It is ONE picture now, where 0.9.1 needed two — a map of six read points
 * and a second figure for the two procedures the top reading was. Four
 * coordinates on a grid need neither: there is one rule, the picture shows
 * it, and the case that used to need its own figure is drawn as the ordinary
 * thing it is. The label is deliberately drawn OVERLAPPING the top of the
 * grid, because that is the common roll — the printer starts a few
 * millimetres after the die cut, so the label's top edge is above the first
 * row it can lay and Y1 reads 0. Drawing the label tidily inside the grid
 * would show the rarer case and leave the ordinary one to prose.
 *
 * It is not to scale: the overlap is drawn far deeper than the few
 * millimetres it usually is, because a diagram honest about the proportions
 * shows nothing at all.
 */
const SVGNS = 'http://www.w3.org/2000/svg';
const svgEl = (name, attrs) => {
  const node = document.createElementNS(SVGNS, name);
  for (const [key, value] of Object.entries(attrs || {}))
    node.setAttribute(key, String(value));
  return node;
};
const svgText = (x, y, text, attrs) => {
  const node = svgEl('text', { x, y, ...(attrs || {}) });
  node.textContent = text;
  return node;
};

/* One badge: the circle and its letters, at the point being read. Every one
 * of the four is drawn by this, so a badge on the picture and a badge on a
 * field cannot come out looking like different things. */
function svgBadge(group, x, y, letter) {
  group.append(svgEl('circle', { cx: x, cy: y, r: 6.4, class: 'calb' }));
  group.append(svgText(x, y + 2.1, letter, { class: 'calbt' }));
}

function calDrawing() {
  const svg = svgEl('svg', {
    id: 'calSvg', class: 'calsvg', viewBox: '0 0 132 112',
    role: 'img', 'aria-label':
      'The printed grid with a label lying on it: X1 and X2 where the '
      + 'label\u2019s left and right edges fall on the scale across, Y1 and '
      + 'Y2 where its top and bottom edges fall on the scale running down',
  });

  /* The grid is everything the printer can reach and the label is a piece of
   * paper lying on it, so the label is drawn as an OUTLINE and the grid runs
   * straight through it. The first cut filled it, which is the picture the
   * wrong way round: it hid the very marks the four readings are taken from,
   * and the black strip — the one thing X1 and X2 are read against — was
   * visible only on the parts of the sheet that miss the paper. */
  const GX = 22, GY = 24, GW = 104, GH = 80;
  svg.append(svgEl('rect', { x: GX, y: GY, width: GW, height: GH,
                             class: 'calgrid' }));
  for (let n = 1; n < 13; n += 1)
    svg.append(svgEl('line', { x1: GX + n * 8, y1: GY, x2: GX + n * 8,
                               y2: GY + GH, class: 'calrule' }));
  for (let n = 1; n < 10; n += 1)
    svg.append(svgEl('line', { x1: GX, y1: GY + n * 8, x2: GX + GW,
                               y2: GY + n * 8, class: 'calrule' }));

  /* The across scale, INSIDE the grid where it is really printed, white on
   * black — which on the paper is the only thing telling the two scales
   * apart, so a picture that drew them alike would teach the wrong
   * recognition. */
  const BAND = GY + 18;
  svg.append(svgEl('rect', { x: GX, y: BAND, width: GW, height: 5.6,
                             class: 'calband' }));
  for (let n = 0; n <= 13; n += 1)
    svg.append(svgEl('line', { x1: GX + n * 8, y1: BAND, x2: GX + n * 8,
                               y2: BAND + (n % 5 === 0 ? 5.6 : 2.8),
                               class: 'calnotch' }));

  /* The scale running down, in the margin: ticks, and the numbers that make
   * it a scale rather than a rule. 0 is at the grid's own top edge, which is
   * the first row the printer lays and the origin both Y readings count
   * from. */
  svg.append(svgEl('rect', { x: GX, y: GY - 0.9, width: GW, height: 1.8,
                             class: 'calbar' }));
  for (let n = 0; n <= 9; n += 1) {
    const y = GY + n * 8;
    svg.append(svgEl('line', { x1: GX - 3, y1: y, x2: GX - 0.5, y2: y,
                               class: 'calrung' }));
    if (n % 5 === 0)
      svg.append(svgText(GX - 5, y + 1.7, String(n * 5),
                         { class: 'calnum', 'text-anchor': 'end' }));
  }

  /* The label, overlapping the top of the grid — the ordinary roll, where
   * the printer starts a few millimetres after the die cut and the label's
   * top edge is above the first row it can lay. Drawing it tidily inside the
   * grid would show the rarer case and leave the common one to prose. */
  const LX = 46, LW = 60, LTOP = 15, LBOT = GY + 58;
  svg.append(svgEl('rect', { x: LX, y: LTOP, width: LW, height: GY - LTOP,
                             class: 'calblank' }));
  svg.append(svgEl('rect', { x: LX, y: LTOP, width: LW, height: LBOT - LTOP,
                             class: 'calpaper' }));
  svg.append(svgText(LX + LW / 2, GY - 4.4, 'no ink here', { class: 'calt' }));

  /* X1 and X2: the label's two side edges, carried up out of the grid to
   * their own badges. The leader is on the edge because the edge is what is
   * read; the badge is clear of the drawing because a badge inside it is a
   * mark competing with the marks. */
  for (const [x, letter] of [[LX, 'X1'], [LX + LW, 'X2']]) {
    svg.append(svgEl('line', { x1: x, y1: LTOP, x2: x, y2: 13,
                               class: 'calleader' }));
    svgBadge(svg, x, 6.6, letter);
  }

  /* Y1 and Y2 sit in the margin at the height of the edge each is read at,
   * and Y1's leader is the whole rule in one mark: its edge is up there, the
   * scale starts down here at 0, so the reading is the scale's own 0. */
  svg.append(svgEl('line', { x1: LX, y1: LTOP, x2: LX + LW, y2: LTOP,
                             class: 'caledge' }));
  svg.append(svgEl('line', { x1: 10, y1: LTOP + 7, x2: 10, y2: GY - 1,
                             class: 'calleader' }));
  svg.append(svgEl('line', { x1: 10, y1: LTOP, x2: LX, y2: LTOP,
                             class: 'calleader' }));
  svgBadge(svg, 10, LTOP, 'Y1');

  svg.append(svgEl('line', { x1: LX, y1: LBOT, x2: LX + LW, y2: LBOT,
                             class: 'caledge' }));
  svg.append(svgEl('line', { x1: 10, y1: LBOT, x2: LX, y2: LBOT,
                             class: 'calleader' }));
  svgBadge(svg, 10, LBOT, 'Y2');
  return svg;
}


/* One roll, edited in one place.
 *
 * The two measurements are the whole reason this dialog exists, and they are
 * labelled by what they DO rather than by the order the vendor prints them
 * in. "These are the wrong way round" is the old Swap button with a sentence
 * for a name: `Swap to 1.25" × 2.25"` described its arithmetic and left the
 * question — which of these numbers is which? — unanswered right next to it.
 */
function editStockDialog(stock) {
  const body = $('modalBody');
  body.innerHTML = '';
  body.append(el('h2', null, stock.name));
  body.append(el('p', 'lede',
    'Across the print head is the width the head covers in one pass. Along '
    + 'the roll is how far the paper travels for one label. Nothing here can '
    + 'work out which is which \u2014 but lining the roll up measures both '
    + 'edges of the real paper, and says so if they look transposed.'));

  const fields = {};
  const field = (key, label, value, step, hint) => {
    const wrap = el('label', 'field');
    wrap.append(el('span', null, label));
    const input = el('input');
    input.type = 'number';
    input.step = step;
    input.min = '0';
    input.value = value;
    wrap.append(input);
    if (hint) wrap.append(el('span', 'muted', hint));
    fields[key] = input;
    return wrap;
  };

  /* The name is yours, and saying so is the point.
   *
   * A built-in row arrives called what is printed on the box you reorder by
   * — which is the right default and the wrong thing to read on a picker
   * six months later, when the roll is the freezer labels. Editing one
   * saves an override, so a future release correcting the catalog cannot
   * take a name back off somebody. */
  const name = el('label', 'field');
  name.append(el('span', null, 'Name'));
  const nameInput = el('input');
  nameInput.value = stock.name;
  name.append(nameInput);
  name.append(el('span', 'muted',
    'Call it whatever you call the roll. It is the name every label picker '
    + 'shows, here and on the Quick tab and in the designer.'));
  body.append(name);

  const sizes = el('div', 'row');
  sizes.append(field('across', 'Across the print head (in)', stock.across_in, '0.01'));
  sizes.append(field('feed', 'Along the roll (in)', stock.feed_in, '0.01',
                     '0 for continuous stock'));
  /* Beside the two measurements, because it is the third number that decides
   * how big anything printed on this roll comes out — and it was a bare
   * "Margin (mm)" at the bottom of the dialog, which is a noun with no
   * consequence attached. A roll carrying a 5mm border prints artwork a
   * centimetre smaller than the label and nothing said so. */
  sizes.append(field('margin', 'Blank border kept clear of the edge (mm)',
                     stock.margin_mm, '0.1',
                     `Artwork gets ${stock.drawable_mm[0]} \u00d7 `
                     + `${stock.drawable_mm[1]}mm of this label. Two is the `
                     + 'default; more is a smaller label.'));
  body.append(sizes);

  const swap = el('button', 'btn', 'These are the wrong way round');
  swap.type = 'button';
  swap.setAttribute('data-tip',
    'Exchanges the two numbers and saves. If a label comes out rotated with '
    + 'the text running off the edge, this is what is wrong.');
  swap.onclick = async () => {
    try {
      await post(`/api/stock/${stock.id}/swap`, {});
      $('modal').close();
      await loadState(); renderPrinter(); fillPickers();
      toast('Swapped. Line up this roll again \u2014 what it measured was '
        + 'read off a label the other way round.', 'good');
    } catch (error) { fail(error); }
  };
  body.append(swap);

  const rest = el('div', 'row');
  rest.append(field('count', 'Labels per roll', stock.per_roll, '1'));
  body.append(rest);

  /* No route to the calibration from here. Where the printing starts is a
   * property of a roll in a bay, and this dialog edits a row in a catalog —
   * a stock that is in neither bay has nothing to line up, and a button
   * offering it would have to ask which bay it meant. */

  const actions = el('div', 'actions');
  const save = el('button', 'btn primary', 'Save');
  save.onclick = async () => {
    if (!nameInput.value.trim()) return toast('Give it a name.');
    try {
      await post('/api/stock', {
        id: stock.id,
        name: nameInput.value.trim(),
        sku: stock.sku,
        across_in: Number(fields.across.value),
        feed_in: Number(fields.feed.value),
        margin_mm: Number(fields.margin.value),
        per_roll: Number(fields.count.value) || 0,
      });
      $('modal').close();
      await loadState(); renderPrinter(); fillPickers();
      toast('Saved.', 'good');
    } catch (error) { fail(error); }
  };
  const cancel = el('button', 'btn', 'Cancel');
  cancel.onclick = () => $('modal').close();
  actions.append(save, cancel);
  body.append(actions);
  $('modal').showModal();
}

$('addStock').addEventListener('click', async () => {
  try {
    await post('/api/stock', {
      name: $('newStockName').value,
      sku: $('newStockSku').value,
      across_in: Number($('newStockAcross').value),
      feed_in: Number($('newStockFeed').value),
      per_roll: Number($('newStockCount').value) || 0,
      /* Omitted rather than sent as 0 when the box is empty: the server's
       * default is the right answer for a roll nobody has measured, and a
       * literal zero would be a stock with no margin at all. */
      ...($('newStockMargin').value === ''
        ? {} : { margin_mm: Number($('newStockMargin').value) }),
    });
    ['newStockName', 'newStockSku', 'newStockAcross', 'newStockFeed',
     'newStockCount', 'newStockMargin']
      .forEach((id) => { $(id).value = ''; });
    await loadState(); renderPrinter();
    toast('Stock added.', 'good');
  } catch (error) { fail(error); }
});

/* Roll chips in the bar go straight to the bay that owns them, rather than
 * to a dialog of their own — one place to answer "what is loaded". */
document.querySelectorAll('.roll-chip').forEach((chip) =>
  chip.addEventListener('click', () => { show('printer'); }));
$('printerChip').addEventListener('click', () => show('printer'));
$('statusChip').addEventListener('click', () => show('printer'));

/* ── History ────────────────────────────────────────────────────────── */
function renderHistory() {
  const list = $('historyList');
  list.innerHTML = '';
  if (!S.history.length) {
    list.append(el('p', 'lede', 'Nothing printed yet.'));
    return;
  }
  for (const entry of S.history) {
    const row = el('div', 'hrow');
    row.append(el('span', 'when', new Date(entry.at * 1000)
      .toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })));
    row.append(el('span', 'what', entry.title));
    const stock = stockById(entry.stock);
    row.append(el('span', 'meta',
      `${entry.copies}× · ${entry.side} · ${stock ? stock.name : entry.stock}`
      + (entry.template ? ` · ${entry.template}` : '')));
    row.append(el('span', 'spacer'));
    const again = el('button', 'btn tiny', 'Print again');
    /* The Printed tab's lede used to say this and nothing else. A sentence
     * that describes a button belongs on the button. */
    again.setAttribute('data-tip',
      'Prints exactly this label again — same words, same stock, same roll.');
    again.onclick = async () => {
      try {
        const data = await post(`/api/history/${entry.id}/reprint`, {});
        toast(`Printed ${data.printed} on the ${data.side} roll.`, 'good');
        await loadState(); renderHistory();
      } catch (error) { fail(error); }
    };
    const open = el('button', 'btn tiny', 'Open');
    open.setAttribute('data-tip',
      'Opens this label in the designer with every field already filled in.');
    open.onclick = () => { loadLabel(structuredClone(entry.label)); show('design'); };
    row.append(again, open);
    list.append(row);
  }
}

$('clearHistory').addEventListener('click', async () => {
  if (!confirm('Clear every row? Reprint goes away with them.')) return;
  try { await del('/api/history'); await loadState(); renderHistory(); }
  catch (error) { fail(error); }
});

/* ── Boot ───────────────────────────────────────────────────────────── */
(async function start() {
  try {
    await loadState();
    loadLabel(null);
    /* The disclosure is a phone's answer to a phone's problem. On a wide
     * screen the whole form fits beside the picture and always did, so it
     * opens once at boot — and only at boot, because a person who shut it
     * meant to shut it and a resize is not an instruction. */
    $('quickMore').open = matchMedia('(min-width: 900px)').matches;
    show(prefGet('bruhprint.view', 'quick'));
    syncBarHeight();
    $('quickText').focus();
  } catch (error) {
    toast(`BRUH Print could not load: ${error.message}`, 'bad');
  }
  /* Poll only for the things that change without us: a printer being
   * plugged in, and a roll changed from the Lovelace card. Slow, because
   * nothing here is time-critical and a panel that polls hard on a Pi is a
   * panel somebody notices. */
  setInterval(async () => {
    if (document.hidden) return;
    try { await loadState(); } catch { /* the toast on boot already said */ }
  }, 15000);
})();
