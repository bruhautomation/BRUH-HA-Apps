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
  printer: null, printers: [], assets: [], history: [],
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
    printer: data.printer, printers: data.printers, assets: data.assets,
    history: data.history,
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

function fillPickers() {
  const options = (select, keep) => {
    const previous = keep ?? select.value;
    const rows = loadedStocks();
    select.innerHTML = '';
    for (const stock of rows) {
      const option = el('option', null, `${stock.name} — ${stock.label}`);
      option.value = stock.id;
      select.append(option);
    }
    if (previous && rows.some((s) => s.id === previous)) select.value = previous;
    else if (rows.some((s) => s.id === S.settings.default_stock))
      select.value = S.settings.default_stock;
    else select.value = (rows[0] || {}).id || '';
  };
  options($('quickStock'), prefGet('bruhprint.stock', null));
  options($('designStock'), S.label ? S.label.stock : null);

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
  const line = $('quickMoreSummary');
  if (!line) return;
  const stock = stockById($('quickStock').value);
  const copies = Number($('quickCopies').value) || 1;
  let text = `Label, copies, font \u2014 ${stock ? stock.label : 'none picked'}`;
  if (copies > 1) text += ` \u00b7 ${copies} copies`;
  line.textContent = text;
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
  const id = $('designStock').value || S.settings.default_stock;
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
  $('designStock').value = S.label.stock;
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

/* Applied to the boxes already on screen rather than by rebuilding them:
 * this lands mid-drag, and rebuilding the overlay would take the element out
 * from under the finger holding it. */
function markProblems() {
  const bad = new Set((S.problems || []).map((p) => p.index));
  const boxes = $('overlay').querySelectorAll('.el');
  boxes.forEach((box, index) => box.classList.toggle('bad', bad.has(index)));
  const print = $('designPrint');
  const count = bad.size;
  /* Still enabled: the rule here is that a print is refused only when it
   * cannot be right, and a barcode that will not fit is a label with one
   * element missing — usually still the label somebody wanted. */
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

/* ── The drawable area, drawn ───────────────────────────────────────────
 *
 * The margin is the printer's, not yours: a LabelWriter's head does not
 * start at the liner's edge and its registration wanders as the roll
 * unwinds. Nothing on screen said so, so people put boxes flush to the edge
 * and then found the label had lost a letter. It is one dashed rectangle and
 * a tinted band, which is a thing you can aim at.
 *
 * `headDots` is the second half of the same honesty: a 2.25" stock on a
 * 672-dot head is three dot columns the printer physically cannot reach. */
const HEAD_DOTS = 672;
const HEAD_DPI = 300;

function headReach() {
  const dots = Number(S.printer?.dots) || HEAD_DOTS;
  const dpi = Number(S.printer?.dpi) || HEAD_DPI;
  return { inches: dots / dpi, dots, dpi };
}

/* Which edge of the DESIGN canvas is the sheet's clipped one. The renderer
 * turns the canvas by -rotate on its way to the sheet, so the sheet's
 * trailing across-edge arrives from a different side each quarter — and a
 * hatch on the wrong edge is worse than none, because it points at a part of
 * the label that prints perfectly. */
const CLIP_EDGE = { 0: 'right', 90: 'top', 180: 'left', 270: 'bottom' };

function drawOverlay() {
  const overlay = $('overlay');
  const image = $('designPreview');
  const frame = image.getBoundingClientRect();
  const mm = canvasMm();
  const stock = stockById(S.label.stock);
  const margin = stock ? stock.margin_mm : 2;
  /* The overlay is positioned over the whole label PNG, but element
   * coordinates are measured from the DRAWABLE area's corner — the margin
   * is the printer's, not the designer's. Forgetting to add it back is a
   * millimetre of drift that only shows on the smallest labels. */
  const scaleX = frame.width ? frame.width / (mm.w + 2 * margin) : 4;
  const scaleY = frame.height ? frame.height / (mm.h + 2 * margin) : 4;

  overlay.innerHTML = '';

  const band = el('div', 'marginband');
  band.style.borderWidth = `${margin * scaleY}px ${margin * scaleX}px`;
  overlay.append(band);

  const safe = el('div', 'safe');
  safe.style.left = margin * scaleX + 'px';
  safe.style.top = margin * scaleY + 'px';
  safe.style.width = mm.w * scaleX + 'px';
  safe.style.height = mm.h * scaleY + 'px';
  /* Deliberately no tooltip: it covers the whole label and takes no pointer,
   * so there is nothing to hover. The caption under the canvas says what it
   * is, and it says it without being asked. */
  overlay.append(safe);

  const reach = headReach();
  if (stock && stock.across_in > reach.inches + 0.001) {
    const lost = Math.round((stock.across_in - reach.inches) * reach.dpi);
    const strip = el('div', 'clipped ' + (CLIP_EDGE[S.label.rotate] || 'right'));
    strip.setAttribute('data-tip',
      `This stock is ${stock.across_in}" across and the head reaches `
      + `${reach.inches.toFixed(2)}" — the outer ${lost} dot columns are the `
      + 'printer\u2019s, not yours. Drawn wide enough to see; it is really '
      + 'about a hundredth of an inch.');
    overlay.append(strip);
  }

  const guides = el('div', 'guides');
  guides.id = 'guides';
  overlay.append(guides);

  S.label.elements.forEach((element, index) => {
    const box = el('div', 'el' + (index === S.selected ? ' sel' : ''));
    box.style.left = (margin + element.x_mm) * scaleX + 'px';
    box.style.top = (margin + element.y_mm) * scaleY + 'px';
    box.style.width = Math.max(6, element.w_mm * scaleX) + 'px';
    box.style.height = Math.max(6, element.h_mm * scaleY) + 'px';
    box.append(el('span', 'tag', describe(element)));
    const grip = el('span', 'grip');
    box.append(grip);
    dragging(box, grip, index, scaleX, scaleY, mm, margin);
    overlay.append(box);
  });
  markProblems();
}

function describe(element) {
  const props = element.props || {};
  if (element.type === 'text') return (props.text || 'Text').split('\n')[0].slice(0, 22);
  if (element.type === 'barcode') return '||| ' + (props.data || '').slice(0, 16);
  if (element.type === 'qr') return '▣ ' + (props.data || '').slice(0, 16);
  if (element.type === 'image') return props.asset || 'image';
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

function showGuide(axis, at, margin, scaleX, scaleY) {
  const guides = $('guides');
  if (!guides) return;
  const line = el('div', 'guide ' + axis);
  if (axis === 'x') line.style.left = (margin + at) * scaleX + 'px';
  else line.style.top = (margin + at) * scaleY + 'px';
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

function dragging(box, grip, index, scaleX, scaleY, mm, margin) {
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
          if (!hit.grid) showGuide('x', hit.at, margin, scaleX, scaleY);
        }
        const down = snap([y, y + element.h_mm / 2, y + element.h_mm],
                          snapTargets('y', index, mm), tolY);
        if (down) {
          y = clamp(y + down.delta, 0, mm.h - element.h_mm);
          if (!down.grid) showGuide('y', down.at, margin, scaleX, scaleY);
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
          if (!hit.grid) showGuide('x', hit.at, margin, scaleX, scaleY);
        }
        const down = snap([element.y_mm + h], snapTargets('y', index, mm), tolY);
        if (down) {
          h = clamp(h + down.delta, 1, mm.h - element.y_mm);
          if (!down.grid) showGuide('y', down.at, margin, scaleX, scaleY);
        }
      }
      element.w_mm = w;
      element.h_mm = h;
    }
    clampElement(element, mm);
    box.style.left = (margin + element.x_mm) * scaleX + 'px';
    box.style.top = (margin + element.y_mm) * scaleY + 'px';
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

/* Half a millimetre, which is about the smallest move worth making on a
 * label and small enough that holding the button is a fine adjustment. The
 * arrows exist because a thumb cannot place a box to half a millimetre and a
 * number field is a keyboard away on a phone. */
const NUDGE_MM = 0.5;

function alignTools(element, mm) {
  const holder = el('div', 'tools');

  const bar = el('div', 'toolrow');
  const put = (label, tip, run) => {
    const button = el('button', 'btn', label);
    button.type = 'button';
    button.setAttribute('data-tip', tip);
    button.onclick = () => {
      run();
      clampElement(element, mm);
      markDirty(); drawOverlay(); drawProps();
    };
    bar.append(button);
  };
  put('⇤', 'Against the left of the printable area',
      () => { element.x_mm = 0; });
  put('⇔', 'Centred across the label',
      () => { element.x_mm = (mm.w - element.w_mm) / 2; });
  put('⇥', 'Against the right of the printable area',
      () => { element.x_mm = mm.w - element.w_mm; });
  put('⤒', 'Against the top of the printable area',
      () => { element.y_mm = 0; });
  put('⇕', 'Centred down the label',
      () => { element.y_mm = (mm.h - element.h_mm) / 2; });
  put('⤓', 'Against the bottom of the printable area',
      () => { element.y_mm = mm.h - element.h_mm; });
  put('↔ Fill', 'As wide as the printable area',
      () => { element.x_mm = 0; element.w_mm = mm.w; });
  put('↕ Fill', 'As tall as the printable area',
      () => { element.y_mm = 0; element.h_mm = mm.h; });
  holder.append(bar);

  const nudges = el('div', 'toolrow');
  for (const [label, tip, dx, dy] of [
    ['←', 'Half a millimetre left', -NUDGE_MM, 0],
    ['→', 'Half a millimetre right', NUDGE_MM, 0],
    ['↑', 'Half a millimetre up', 0, -NUDGE_MM],
    ['↓', 'Half a millimetre down', 0, NUDGE_MM],
  ]) {
    const button = el('button', 'btn', label);
    button.type = 'button';
    button.setAttribute('data-tip', tip);
    button.onclick = () => {
      element.x_mm += dx;
      element.y_mm += dy;
      clampElement(element, mm);
      markDirty(); drawOverlay(); drawProps();
    };
    nudges.append(button);
  }
  /* Rotate lives here, with the align and nudge tools, because it acts on
   * the SELECTED box and so does every other control in this pane. It was
   * in the design bar, where it was permanently on screen and disabled for
   * most of what you can select — a control that spends its life greyed out
   * teaches people it is not for them. It keeps the id the design bar gave
   * it because that is the name every handler and test already uses. */
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
  nudges.append(rotate);
  holder.append(nudges);
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
  const geometry = el('div', 'row');
  for (const [key, label] of [['x_mm', 'X'], ['y_mm', 'Y'], ['w_mm', 'W'], ['h_mm', 'H']]) {
    const field = el('label', 'field');
    field.append(el('span', null, `${label} (mm)`));
    const input = el('input');
    input.type = 'number'; input.step = '0.5'; input.value = element[key];
    input.oninput = () => {
      /* Typed values are clamped the same way dragged ones are. Without it
       * the one route into the designer that could put a box off the label
       * was the keyboard — and the renderer clamps at print time, so the
       * only sign was a label that came out different from the screen. */
      element[key] = Number(input.value) || 0;
      clampElement(element, mm);
      input.value = element[key];
      markDirty(); drawOverlay();
    };
    field.append(input);
    geometry.append(field);
  }
  holder.append(geometry);

  holder.append(alignTools(element, mm));

  for (const [name, meta] of Object.entries(spec.fields)) {
    holder.append(propField(element, name, meta));
  }

  const row = el('div', 'actions');
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
  row.append(duplicate, remove);
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
  } else if (meta.type === 'asset') {
    input = el('select');
    const none = el('option', null, '— none —'); none.value = '';
    input.append(none);
    for (const asset of S.assets) {
      const option = el('option', null, asset.name);
      option.value = asset.name;
      input.append(option);
    }
    input.value = element.props[name] || '';
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

$('designStock').addEventListener('change', () => {
  S.label.stock = $('designStock').value;
  /* Changing the stock is choosing a different label, so the direction comes
   * with it — a tube wrap reads along the roll and an address label reads
   * across it, and carrying the old answer over is how you get a design laid
   * out sideways on a stock that never reads that way. */
  const stock = stockById(S.label.stock);
  if (stock) S.label.rotate = Number(stock.turn) || 0;
  updateTurnLines();
  markDirty(); drawOverlay(); drawProps();
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
    for (const key of ['text', 'data', 'asset']) {
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
    const ruler = el('button', 'btn tiny', 'Print the ruler');
    ruler.setAttribute('data-tip',
      'A label with millimetre ticks on both axes — the only way to check '
      + 'a stock is the way round the catalog thinks it is.');
    ruler.onclick = async () => {
      try { const data = await post('/api/printer/test', {}); toast(`Ruler printed on the ${data.side} roll.`, 'good'); }
      catch (error) { fail(error); }
    };
    /* The other half of "print one and look at it". The ruler answers which
     * measurement is which; this answers where the printing starts, which
     * the ruler structurally cannot — it is drawn inside the stock's margin,
     * so on a roll with a 5mm margin there is nothing within 5mm of the die
     * cut to measure against. Two questions, two labels. */
    const offset = el('button', 'btn tiny', 'Where the printing starts');
    offset.id = 'printOffset';
    offset.setAttribute('data-tip',
      'Print a label with a scale at its own corner, measure how far in the '
      + 'printing really begins, and tell BRUH Print to move it. Once per '
      + 'roll.');
    offset.onclick = () => offsetDialog();
    foot.append(use, status, ruler, offset, usb);
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
      const option = el('option', null, `${stock.name} — ${stock.label}`);
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
    /* A print offset is a correction somebody measured, so it says so on the
     * row: an offset nobody can see is an offset that gets blamed on the
     * renderer the next time a label looks wrong. */
    if (stock.offset_feed_mm || stock.offset_across_mm) {
      const moved = [];
      if (stock.offset_feed_mm)
        moved.push(`${stock.offset_feed_mm > 0 ? '+' : '\u2212'}`
          + `${Math.abs(stock.offset_feed_mm)}mm along`);
      if (stock.offset_across_mm)
        moved.push(`${stock.offset_across_mm > 0 ? '+' : '\u2212'}`
          + `${Math.abs(stock.offset_across_mm)}mm across`);
      const pill = el('span', 'pill moved', `printing moved ${moved.join(', ')}`);
      pill.setAttribute('data-tip',
        'Where this roll needs the printing put. Press "Where the printing '
        + 'starts" on the printer card above to measure or clear it.');
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

    const edit = el('button', 'btn tiny', 'Edit');
    edit.setAttribute('data-tip',
      'The two measurements, the margin and how many are on a roll. This is '
      + 'also where you say the two numbers are the wrong way round.');
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
    + 'Print the ruler above. Standard is what everything is tested against; '
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

/* Where the printing starts, measured rather than guessed.
 *
 * A number a person has to guess is a number they guess wrong, and the only
 * instrument that can answer this is a printed label: nothing in a container
 * can see where a print head laid its first dot. So this dialog is a label
 * and two boxes, and the label is the ruler for the boxes.
 *
 * The sign is spelled out in words in three places — the lede, each hint,
 * and the label on the calibration print itself — because nobody knows which
 * way "+" goes on a label printer, and a control that needs its convention
 * looked up is a control people set once, backwards, and never touch again.
 *
 * It is per stock because it is the die cut that decides it, and a Twin
 * Turbo with two rolls genuinely has two answers.
 */
function offsetDialog(stockId) {
  const rows = loadedStocks();
  const start = rows.find((row) => row.id === stockId)
    || rows.find((row) => row.id === S.settings.default_stock) || rows[0];
  if (!start) return toast('There is no label stock to calibrate.', 'bad');

  const body = $('modalBody');
  body.innerHTML = '';
  body.append(el('h2', null, 'Where the printing starts'));
  body.append(el('p', 'lede',
    'Print the calibration label. It has two thick lines meeting at the '
    + 'corner where the printing begins, and 1mm ticks along each of them.'));
  body.append(el('p', 'lede',
    'Hold it up. If there is a gap between the label\u2019s own edge and the '
    + 'thick line, that gap is how far in the printer is starting \u2014 '
    + 'type it below with a minus in front. If a thick line is missing '
    + 'because the printing started before the edge, count the ticks that '
    + 'did survive and type that as a plus.'));

  const pick = el('label', 'field');
  pick.append(el('span', null, 'Which roll'));
  const select = el('select');
  select.id = 'offsetStock';
  for (const row of rows) {
    const option = el('option', null, `${row.name} \u2014 ${row.label}`);
    option.value = row.id;
    select.append(option);
  }
  select.value = start.id;
  pick.append(select);
  body.append(pick);

  /* Signed, so no `min`. The server refuses anything past an inch with a
   * sentence rather than clamping it, because a clamp would print something
   * other than what this box says. */
  const fields = {};
  const field = (key, id, label, hint) => {
    const wrap = el('label', 'field');
    wrap.append(el('span', null, label));
    const input = el('input');
    input.type = 'number';
    input.step = '0.1';
    input.id = id;
    wrap.append(input);
    wrap.append(el('span', 'muted', hint));
    fields[key] = input;
    return wrap;
  };

  const boxes = el('div', 'row');
  boxes.append(field('feed', 'offsetFeed',
    'Move the printing along the roll (mm)',
    'Minus moves it back toward the edge that comes out of the printer '
    + 'first. Printing starting 4.7mm in is \u22124.7.'));
  boxes.append(field('across', 'offsetAcross',
    'Move the printing across the head (mm)',
    'Minus moves it toward the left-hand edge as the label comes out.'));
  body.append(boxes);

  const fill = () => {
    const row = rows.find((r) => r.id === select.value) || start;
    fields.feed.value = row.offset_feed_mm || 0;
    fields.across.value = row.offset_across_mm || 0;
  };
  fill();
  select.onchange = fill;

  const print = el('button', 'btn', 'Print the calibration label');
  print.id = 'offsetCalibrate';
  print.type = 'button';
  print.setAttribute('data-tip',
    'One label, drawn to the very edges of the sheet \u2014 the stock\u2019s '
    + 'margin is ignored, or there would be nothing near the die cut to '
    + 'measure against. Saved offsets are applied to it, so printing it '
    + 'again is how you check a correction worked.');
  print.onclick = async () => {
    try {
      const data = await post('/api/printer/calibrate', { stock: select.value });
      toast(`Calibration label printed on the ${data.side} roll.`, 'good');
    } catch (error) { fail(error); }
  };
  body.append(print);

  const actions = el('div', 'actions');
  const save = el('button', 'btn primary', 'Save');
  save.id = 'offsetSave';
  save.onclick = async () => {
    try {
      await post(`/api/stock/${select.value}/offset`, {
        offset_feed_mm: Number(fields.feed.value) || 0,
        offset_across_mm: Number(fields.across.value) || 0,
      });
      $('modal').close();
      await loadState(); renderPrinter(); fillPickers();
      toast('Saved. Print the calibration label again to check.', 'good');
    } catch (error) { fail(error); }
  };
  const cancel = el('button', 'btn', 'Cancel');
  cancel.onclick = () => $('modal').close();
  actions.append(save, cancel);
  body.append(actions);
  $('modal').showModal();
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
    + 'the roll is how far the paper travels for one label. Nothing can work '
    + 'out which is which for you \u2014 print the ruler and hold it against '
    + 'a real label.'));

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

  const name = el('label', 'field');
  name.append(el('span', null, 'Name'));
  const nameInput = el('input');
  nameInput.value = stock.name;
  name.append(nameInput);
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
      toast('Swapped. Print the ruler to check.', 'good');
    } catch (error) { fail(error); }
  };
  body.append(swap);

  const rest = el('div', 'row');
  rest.append(field('count', 'Labels per roll', stock.per_roll, '1'));
  body.append(rest);

  /* Where the printing starts is measured, not typed, so it is a button to
   * the dialog that prints the thing you measure with rather than two more
   * boxes here. Closing this one first: they share `#modal`. */
  const where = el('button', 'btn', 'Where the printing starts on this roll');
  where.type = 'button';
  where.setAttribute('data-tip',
    'Prints a label with a scale at its own corner, so you can see how far '
    + 'in the printer really begins and move it.');
  where.onclick = () => { $('modal').close(); offsetDialog(stock.id); };
  body.append(where);

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
