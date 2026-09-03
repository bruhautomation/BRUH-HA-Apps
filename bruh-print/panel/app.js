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
};

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
}

function fillPickers() {
  const options = (select, keep) => {
    const previous = keep ?? select.value;
    select.innerHTML = '';
    for (const stock of S.stocks) {
      const option = el('option', null, `${stock.name} — ${stock.label}`);
      option.value = stock.id;
      select.append(option);
    }
    if (previous && S.stocks.some((s) => s.id === previous)) select.value = previous;
    else select.value = S.settings.default_stock || (S.stocks[0] || {}).id || '';
  };
  options($('quickStock'), prefGet('bruhprint.stock', null));
  options($('designStock'), S.label ? S.label.stock : null);

  const fontSelect = $('quickFont');
  const keptFont = fontSelect.value || S.settings.default_font;
  fontSelect.innerHTML = '';
  for (const font of S.fonts) {
    const option = el('option', null, font.name);
    option.value = font.key;
    fontSelect.append(option);
  }
  if (S.fonts.some((f) => f.key === keptFont)) fontSelect.value = keptFont;

  if (!$('addBar').childElementCount) buildAddBar();
}

/* ── Quick ──────────────────────────────────────────────────────────── */
let quickTimer = 0;
let quickSeq = 0;
function quickPayload(printIt) {
  const rotate = $('quickRotate').value;
  return {
    text: $('quickText').value,
    stock: $('quickStock').value,
    font: $('quickFont').value,
    copies: Number($('quickCopies').value) || 1,
    side: $('quickSide').value,
    uppercase: $('quickUpper').checked,
    ...(rotate === '' ? {} : { rotate: Number(rotate) }),
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
['quickText', 'quickStock', 'quickFont', 'quickRotate', 'quickUpper']
  .forEach((id) => $(id).addEventListener('input', () => {
    if (id === 'quickStock') prefSet('bruhprint.stock', $('quickStock').value);
    debouncedQuick();
  }));

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
  return {
    stock: $('designStock').value || S.settings.default_stock,
    rotate: 0, name: '', invert: false, elements: [],
  };
}

function loadLabel(label) {
  S.label = label || blankLabel();
  S.selected = -1;
  $('designStock').value = S.label.stock;
  $('designRotate').value = String(S.label.rotate || 0);
  $('designName').value = S.label.name || '';
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

async function refreshPreview() {
  try {
    const response = await fetch(relative('/api/preview'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: S.label, scale: 2 }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `preview answered ${response.status}`);
    }
    const blob = await response.blob();
    const image = $('designPreview');
    const previous = image.src;
    image.src = URL.createObjectURL(blob);
    image.classList.add('on');
    if (previous.startsWith('blob:')) URL.revokeObjectURL(previous);
    image.onload = fitCanvas;
    notes($('designNotes'), JSON.parse(response.headers.get('X-Label-Notes') || '[]'));
  } catch (error) {
    notes($('designNotes'), [error.message]);
  }
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
  drawOverlay();
}

addEventListener('resize', () => { if (S.label) fitCanvas(); });

function drawOverlay() {
  const overlay = $('overlay');
  const image = $('designPreview');
  const box = image.getBoundingClientRect();
  const mm = canvasMm();
  const stock = stockById(S.label.stock);
  const margin = stock ? stock.margin_mm : 1;
  /* The overlay is positioned over the whole label PNG, but element
   * coordinates are measured from the DRAWABLE area's corner — the margin
   * is the printer's, not the designer's. Forgetting to add it back is a
   * millimetre of drift that only shows on the smallest labels. */
  const scaleX = box.width ? box.width / (mm.w + 2 * margin) : 4;
  const scaleY = box.height ? box.height / (mm.h + 2 * margin) : 4;

  overlay.innerHTML = '';
  S.label.elements.forEach((element, index) => {
    const box = el('div', 'el' + (index === S.selected ? ' sel' : ''));
    box.style.left = (margin + element.x_mm) * scaleX + 'px';
    box.style.top = (margin + element.y_mm) * scaleY + 'px';
    box.style.width = Math.max(6, element.w_mm * scaleX) + 'px';
    box.style.height = Math.max(6, element.h_mm * scaleY) + 'px';
    box.append(el('span', 'tag', describe(element)));
    const grip = el('span', 'grip');
    box.append(grip);
    dragging(box, grip, index, scaleX, scaleY, mm);
    overlay.append(box);
  });
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
    const element = S.label.elements[index];
    if (mode === 'move') {
      element.x_mm = clamp(origin.x_mm + dx / scaleX, 0, mm.w - element.w_mm);
      element.y_mm = clamp(origin.y_mm + dy / scaleY, 0, mm.h - element.h_mm);
    } else {
      element.w_mm = clamp(origin.w_mm + dx / scaleX, 1, mm.w - element.x_mm);
      element.h_mm = clamp(origin.h_mm + dy / scaleY, 1, mm.h - element.y_mm);
    }
    round(element);
    box.style.left = ((stockById(S.label.stock)?.margin_mm || 1) + element.x_mm) * scaleX + 'px';
    box.style.top = ((stockById(S.label.stock)?.margin_mm || 1) + element.y_mm) * scaleY + 'px';
    box.style.width = Math.max(6, element.w_mm * scaleX) + 'px';
    box.style.height = Math.max(6, element.h_mm * scaleY) + 'px';
  };

  const end = () => {
    if (!mode) return;
    mode = null;
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
function select(index) { S.selected = index; drawOverlay(); drawProps(); drawLayers(); }

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
  select(S.label.elements.length - 1);
  markDirty();
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

  const geometry = el('div', 'row');
  for (const [key, label] of [['x_mm', 'X'], ['y_mm', 'Y'], ['w_mm', 'W'], ['h_mm', 'H']]) {
    const field = el('label', 'field');
    field.append(el('span', null, `${label} (mm)`));
    const input = el('input');
    input.type = 'number'; input.step = '0.5'; input.value = element[key];
    input.oninput = () => {
      element[key] = Number(input.value) || 0;
      markDirty(); drawOverlay();
    };
    field.append(input);
    geometry.append(field);
  }
  holder.append(geometry);

  for (const [name, meta] of Object.entries(spec.fields)) {
    holder.append(propField(element, name, meta));
  }

  const row = el('div', 'actions');
  const duplicate = el('button', 'btn', 'Duplicate');
  duplicate.onclick = () => {
    const copy = structuredClone(element);
    copy.y_mm = Math.round((copy.y_mm + copy.h_mm + 1) * 10) / 10;
    S.label.elements.push(copy);
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
    input = el('select');
    for (const font of S.fonts) {
      const option = el('option', null, font.name);
      option.value = font.key;
      input.append(option);
    }
    input.value = element.props[name];
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
  markDirty(); drawOverlay();
});
$('designRotate').addEventListener('change', () => {
  S.label.rotate = Number($('designRotate').value);
  markDirty(); drawOverlay();
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
      label: S.label, copies, side: $('designSide').value, source: 'designer',
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
  nameInput.placeholder = 'Cryo vial';
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

  const sideField = el('label', 'field inline');
  sideField.append(el('span', null, 'Roll'));
  const side = el('select');
  for (const [value, label] of [['', 'Wherever it is'], ['left', 'Left'], ['right', 'Right']]) {
    const option = el('option', null, label); option.value = value; side.append(option);
  }
  sideField.append(side);

  const print = el('button', 'btn primary big', 'Print');
  print.onclick = async () => {
    print.disabled = true;
    try {
      const data = await post(`/api/template/${template.id}/print`, {
        fields: values(inputs), copies: Number(copies.value) || 1, side: side.value,
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

  row.append(copiesField, sideField, print, edit, remove);
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
    const use = el('button', 'btn tiny', S.printer?.key === printer.key ? 'In use' : 'Use this one');
    use.onclick = async () => {
      try { await post('/api/printer/select', { printer: printer.key }); await loadState(); renderPrinter(); }
      catch (error) { fail(error); }
    };
    const status = el('button', 'btn tiny', 'Check it');
    status.onclick = async () => {
      try { const data = await api('/api/printer/status'); toast(`${printer.name}: ${data.status}.`, data.status_ok ? 'good' : 'bad'); }
      catch (error) { fail(error); }
    };
    const ruler = el('button', 'btn tiny', 'Print the ruler');
    ruler.setAttribute('data-tip',
      'A label with millimetre ticks on both axes — the only way to check '
      + 'a stock is the way round the catalog thinks it is.');
    ruler.onclick = async () => {
      try { const data = await post('/api/printer/test', {}); toast(`Ruler printed on the ${data.side} roll.`, 'good'); }
      catch (error) { fail(error); }
    };
    foot.append(use, status, ruler);
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
    if (stock) {
      const full = stock.per_roll || roll.remaining || 1;
      const bar = el('div', 'bar');
      const fillEl = el('i');
      fillEl.style.width = clamp(roll.remaining / full * 100, 0, 100) + '%';
      bar.append(fillEl);
      bay.append(bar);
      bay.append(el('div', 'est',
        `About ${roll.remaining} left — an estimate, counted from prints. `
        + `Nothing on a LabelWriter reports the real level.`));
      const reset = el('button', 'btn tiny', 'New roll (reset the count)');
      reset.onclick = async () => {
        try { await post(`/api/roll/${roll.side}`, { stock: stock.id, remaining: stock.per_roll }); await loadState(); renderPrinter(); }
        catch (error) { fail(error); }
      };
      const foot = el('div', 'foot'); foot.append(reset);
      bay.append(foot);
    }
    bays.append(bay);
  }

  const table = $('stockTable');
  table.innerHTML = '';
  for (const stock of S.stocks) {
    const row = el('div', 'strow');
    row.append(el('span', 'nm', stock.name));
    row.append(el('span', 'dim', stock.label));
    if (stock.sku) row.append(el('span', 'sku', stock.sku));
    row.append(el('span', 'spacer'));
    const swap = el('button', 'btn tiny', 'Swap');
    swap.setAttribute('data-tip',
      'Exchange the two measurements. Press this if a label comes out '
      + 'rotated 90° with the text off the edge.');
    swap.onclick = async () => {
      try { await post(`/api/stock/${stock.id}/swap`, {}); await loadState(); renderPrinter(); toast('Swapped.', 'good'); }
      catch (error) { fail(error); }
    };
    const remove = el('button', 'btn tiny danger', stock.builtin ? 'Hide' : 'Delete');
    remove.onclick = async () => {
      try { await del(`/api/stock/${stock.id}`); await loadState(); renderPrinter(); }
      catch (error) { fail(error); }
    };
    row.append(swap, remove);
    table.append(row);
  }

  const settings = $('settings');
  settings.innerHTML = '';
  const toggles = [
    ['enforce_stock', 'Refuse a label whose stock is not in the roll',
      'On by default. Printing a 2.25" raster onto a 0.56" roll runs across '
      + 'the liner, once per copy.'],
    ['quick_uppercase', 'Quick labels are UPPERCASE', ''],
    ['quick_rotate_narrow', 'Turn text along the roll on tall, narrow stock',
      'A wrap-around cryo label reads along the tube, not across it.'],
  ];
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

$('addStock').addEventListener('click', async () => {
  try {
    await post('/api/stock', {
      name: $('newStockName').value,
      sku: $('newStockSku').value,
      across_in: Number($('newStockAcross').value),
      feed_in: Number($('newStockFeed').value),
      per_roll: Number($('newStockCount').value) || 0,
    });
    ['newStockName', 'newStockSku', 'newStockAcross', 'newStockFeed', 'newStockCount']
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
    again.onclick = async () => {
      try {
        const data = await post(`/api/history/${entry.id}/reprint`, {});
        toast(`Printed ${data.printed} on the ${data.side} roll.`, 'good');
        await loadState(); renderHistory();
      } catch (error) { fail(error); }
    };
    const open = el('button', 'btn tiny', 'Open');
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
    show(prefGet('bruhprint.view', 'quick'));
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
