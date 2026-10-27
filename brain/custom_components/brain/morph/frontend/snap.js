// snap.js — a picture of part of Morph, taken in the browser.
//
// A Tell is about what somebody is LOOKING at ("this is cut off", "the
// colours are wrong"), and the YAML only says what is configured. So the
// moment something is held, the panel photographs it and brAIn reads the
// picture before it reads anything else.
//
// There is no screenshot API a page may call without a permission prompt,
// so this draws the element itself: the subtree is cloned with every
// element's COMPUTED style written inline, shadow roots flattened (Morph's
// own panel is one, and so is every Lovelace card it hosts), canvases and
// images turned into data URLs, Morph's two fonts embedded, and the result
// rendered through an SVG <foreignObject> onto a canvas. Two halves:
//
// * `prepare(el)` is SYNCHRONOUS and must be called before the panel
//   re-renders — holding a card opens it, and the picture has to be of the
//   card as it was, not of the editor that replaced it.
// * `job.render()` is the slow half (images, fonts, rasterising), awaited
//   whenever.
//
// It never throws. What it cannot do is said (`error`), and `viewText`
// always gives the element's visible text, so brAIn is never told nothing.

const SKIP = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'TEMPLATE', 'NOSCRIPT', 'BASE']);
const MAX_NODES = 2500;
// The clone is synchronous, so it has a clock as well as a size: a whole
// dashboard of hosted Lovelace cards must not freeze a phone for seconds.
// What the budget cuts off is said in the picture's notes.
const CLONE_MS = 450;
const MAX_W = 1600;
const MAX_H = 3000;
const MAX_PIXELS = 3_200_000;
// The integration refuses a PNG past ~2.9 MB (Home Assistant's websocket
// takes 4 MB frames); base64 is a third larger than the bytes.
const MAX_DATA_URL = 3_800_000;
const FETCH_MS = 3000;
const INHERITED = new Set([
  'color', 'cursor', 'direction', 'font-family', 'font-feature-settings', 'font-kerning', 'font-size',
  'font-stretch', 'font-style', 'font-variant', 'font-variant-caps', 'font-variant-ligatures',
  'font-variant-numeric', 'font-variation-settings', 'font-weight', 'hyphens', 'letter-spacing',
  'line-height', 'list-style-image', 'list-style-position', 'list-style-type', 'orphans', 'quotes',
  'tab-size', 'text-align', 'text-align-last', 'text-indent', 'text-rendering', 'text-shadow',
  'text-transform', 'visibility', 'white-space', 'widows', 'word-break', 'word-spacing',
  'overflow-wrap', '-webkit-text-fill-color', '-webkit-font-smoothing', 'fill', 'fill-opacity',
  'fill-rule', 'stroke', 'stroke-dasharray', 'stroke-dashoffset', 'stroke-linecap', 'stroke-linejoin',
  'stroke-opacity', 'stroke-width', 'paint-order', 'border-collapse', 'caption-side', 'empty-cells',
  'text-wrap', 'white-space-collapse', 'color-scheme',
]);
// Motion is never part of a still: a transition caught mid-way draws the
// card at a moment nobody saw.
const DROP = /^(transition|animation|will-change|view-transition|content-visibility|-webkit-app-region)/;

let defaultsHost = null;
const defaults = new Map();

function defaultStyle(tag, ns) {
  const key = ns + ':' + tag;
  if (defaults.has(key)) return defaults.get(key);
  if (!defaultsHost) {
    defaultsHost = document.createElement('div');
    defaultsHost.setAttribute('aria-hidden', 'true');
    defaultsHost.style.cssText = 'position:fixed;left:-99999px;top:0;visibility:hidden;pointer-events:none;contain:strict;width:10px;height:10px';
    document.body.appendChild(defaultsHost);
  }
  let probe;
  try { probe = ns === 'svg' ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag); } catch (e) { probe = document.createElement('div'); }
  defaultsHost.appendChild(probe);
  const cs = getComputedStyle(probe);
  const out = {};
  for (let i = 0; i < cs.length; i++) out[cs[i]] = cs.getPropertyValue(cs[i]);
  defaultsHost.removeChild(probe);
  defaults.set(key, out);
  return out;
}

// Only what differs: from the parent for an inherited property (so the
// clone inherits it just the same), from the tag's default otherwise. A
// full copy of ~350 properties per element is megabytes of SVG.
function inlineStyle(target, cs, parentCs, base, isRoot) {
  const parts = [];
  for (let i = 0; i < cs.length; i++) {
    const prop = cs[i];
    if (DROP.test(prop)) continue;
    const v = cs.getPropertyValue(prop);
    if (!v) continue;
    if (INHERITED.has(prop) && !isRoot) {
      if (parentCs && parentCs.getPropertyValue(prop) === v) continue;
    } else if (!INHERITED.has(prop) && base[prop] === v) continue;
    parts.push(`${prop}:${v}`);
  }
  target.setAttribute('style', parts.join(';'));
}

function isCustom(tag) { return tag.includes('-'); }

function pseudo(el, which, parentCs) {
  let cs;
  try { cs = getComputedStyle(el, which); } catch (e) { return null; }
  const content = cs && cs.getPropertyValue('content');
  if (!content || content === 'none' || content === 'normal') return null;
  const span = document.createElement('span');
  inlineStyle(span, cs, parentCs, defaultStyle('span', 'html'), false);
  const text = content.replace(/^["']|["']$/g, '');
  if (!/^(url|counter|attr)\(/.test(content)) span.textContent = text;
  return span;
}

function childrenOf(node) {
  // A shadow root replaces the light children; a <slot> stands for what
  // was assigned to it, or its own fallback when nothing was.
  if (node.shadowRoot) return Array.from(node.shadowRoot.childNodes);
  if (node.tagName === 'SLOT' && node.assignedNodes) {
    const assigned = node.assignedNodes({ flatten: true });
    if (assigned.length) return assigned;
  }
  return Array.from(node.childNodes);
}

function cloneTree(node, parentCs, state, isRoot) {
  if (node.nodeType === 3) return document.createTextNode(node.textContent);
  if (node.nodeType !== 1) return null;
  const tag = node.tagName.toUpperCase();
  if (SKIP.has(tag)) return null;
  if (node.hasAttribute && node.hasAttribute('data-tell')) return null; // the editor, not the card
  if (node.hasAttribute && node.hasAttribute('data-snap-skip')) return null; // Morph's own controls on it
  if (++state.n > MAX_NODES || performance.now() > state.deadline) { state.cut = true; return null; }
  const cs = getComputedStyle(node);
  if (cs.display === 'none') return null;
  const svg = node instanceof SVGElement;
  if (svg) {
    const out = document.createElementNS('http://www.w3.org/2000/svg', node.tagName);
    for (const a of Array.from(node.attributes)) {
      try { out.setAttribute(a.name, a.value); } catch (e) { /* an attribute the SVG namespace refuses */ }
    }
    inlineStyle(out, cs, parentCs, defaultStyle(node.tagName, 'svg'), isRoot);
    if (node.tagName.toLowerCase() === 'svg') {
      // An <svg> sized by CSS draws at 300×150 once that CSS is gone.
      const r = node.getBoundingClientRect();
      out.setAttribute('width', String(Math.round(r.width)));
      out.setAttribute('height', String(Math.round(r.height)));
    }
    for (const c of Array.from(node.childNodes)) {
      const k = cloneTree(c, cs, state, false);
      if (k) out.appendChild(k);
    }
    return out;
  }
  let out;
  if (tag === 'CANVAS') {
    out = document.createElement('img');
    try { out.src = node.toDataURL('image/png'); } catch (e) { state.notes.add('a chart could not be copied'); }
  } else if (tag === 'IMG') {
    out = document.createElement('img');
    const src = node.currentSrc || node.src || '';
    if (src) { out.setAttribute('src', src); state.images.push(out); }
  } else if (tag === 'VIDEO') {
    out = document.createElement('img');
    try {
      const c = document.createElement('canvas');
      c.width = node.videoWidth || node.clientWidth; c.height = node.videoHeight || node.clientHeight;
      c.getContext('2d').drawImage(node, 0, 0, c.width, c.height);
      out.src = c.toDataURL('image/jpeg', 0.8);
    } catch (e) { state.notes.add('a video frame could not be copied'); }
  } else if (tag === 'IFRAME') {
    out = document.createElement('div');
    out.textContent = '(embedded page — not captured)';
    state.notes.add('an embedded page is not in the picture');
  } else if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    out = document.createElement('div');
    const t = node.type;
    out.textContent = t === 'checkbox' || t === 'radio' ? (node.checked ? '☑' : '☐') : tag === 'SELECT' ? (node.selectedOptions && node.selectedOptions[0] ? node.selectedOptions[0].text : '') : (node.value || node.placeholder || '');
  } else {
    // A custom element is recreated as a plain box: creating `ha-card` in
    // this document would run its constructor, with side effects.
    out = document.createElement(isCustom(tag) || tag === 'SLOT' ? 'div' : node.tagName.toLowerCase());
  }
  const base = defaultStyle(out.tagName.toLowerCase(), 'html');
  inlineStyle(out, cs, parentCs, base, isRoot);
  if (tag === 'SLOT') out.style.display = cs.display === 'contents' ? 'contents' : out.style.display;
  const bg = cs.getPropertyValue('background-image');
  if (bg && bg.includes('url(') && !bg.includes('url("data:')) state.backgrounds.push(out);
  if (!['CANVAS', 'IMG', 'VIDEO', 'IFRAME', 'INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
    const before = pseudo(node, '::before', cs);
    if (before) out.appendChild(before);
    for (const c of childrenOf(node)) {
      const k = cloneTree(c, cs, state, false);
      if (k) out.appendChild(k);
    }
    const after = pseudo(node, '::after', cs);
    if (after) out.appendChild(after);
  }
  return out;
}

function visible(node, out, depth, seen = { n: 0 }) {
  if (depth > 60 || out.length > 400 || ++seen.n > 4000) return;
  if (node.nodeType === 3) { const t = node.textContent.replace(/\s+/g, ' ').trim(); if (t) out.push(t); return; }
  if (node.nodeType !== 1 || SKIP.has(node.tagName.toUpperCase())) return;
  if (node.hasAttribute('data-tell') || node.hasAttribute('data-snap-skip')) return;
  const cs = getComputedStyle(node);
  if (cs.display === 'none' || cs.visibility === 'hidden') return;
  if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') { if (node.value) out.push(node.value); return; }
  if (node.getAttribute && node.getAttribute('aria-label') && !node.textContent.trim()) out.push(`[${node.getAttribute('aria-label')}]`);
  for (const c of childrenOf(node)) visible(c, out, depth + 1, seen);
}

// The element's text as a person reads it, through every shadow root —
// sent beside the picture, and instead of it when there is none.
export function viewText(el) {
  try {
    const r = el.getBoundingClientRect();
    const words = [];
    visible(el, words, 0);
    return { w: Math.round(r.width), h: Math.round(r.height), text: words.join(' · ').slice(0, 1500) };
  } catch (e) {
    return { w: 0, h: 0, text: '' };
  }
}

function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), ms))]);
}

const dataUrls = new Map();
function toDataUrl(url) {
  if (!url || url.startsWith('data:')) return Promise.resolve(url);
  if (dataUrls.has(url)) return dataUrls.get(url);
  const p = withTimeout(fetch(url, { credentials: 'same-origin' }).then((r) => (r.ok ? r.blob() : null)).then((b) => b && new Promise((resolve) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => resolve(null);
    fr.readAsDataURL(b);
  })).catch(() => null), FETCH_MS);
  dataUrls.set(url, p);
  return p;
}

let fontCss = null;
// Morph's two fonts, as @font-face rules with the files inlined — an SVG
// drawn as an image may not fetch anything, so a font it has to load is a
// font it falls back from. Latin only: the other subsets are most of the
// download and none of a dashboard.
function fonts(url) {
  if (fontCss) return fontCss;
  fontCss = withTimeout((async () => {
    const css = await fetch(url).then((r) => (r.ok ? r.text() : '')).catch(() => '');
    const blocks = css.split('@font-face').slice(1).map((b) => '@font-face' + b.split('}')[0] + '}');
    const latin = blocks.filter((b) => /unicode-range:[^;]*U\+0000-00FF/i.test(b));
    const out = [];
    for (const b of latin.slice(0, 6)) {
      const m = b.match(/url\(([^)]+)\)/);
      if (!m) continue;
      const src = m[1].replace(/^['"]|['"]$/g, '');
      const data = await toDataUrl(src);
      if (data) out.push(b.replace(m[0], `url(${data})`));
    }
    return out.join('\n');
  })(), FETCH_MS * 2).then((x) => x || '');
  return fontCss;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('the browser would not draw the copy'));
    img.src = src;
  });
}

// Synchronous: clone now, before the panel re-renders what was held.
export function prepare(el, opts = {}) {
  const view = viewText(el);
  let clone = null;
  const state = { n: 0, cut: false, images: [], backgrounds: [], notes: new Set(), deadline: performance.now() + (opts.cloneMs || CLONE_MS) };
  let error = '';
  let rect = { width: 0, height: 0 };
  try {
    rect = el.getBoundingClientRect();
    clone = cloneTree(el, null, state, true);
    if (!clone) error = 'there was nothing visible to draw';
  } catch (e) {
    error = `the card could not be copied (${(e && e.message) || e})`;
  }
  if (clone && clone.style) {
    // Where it sits on the page is not part of it.
    clone.style.margin = '0';
    clone.style.transform = 'none';
    clone.style.position = 'relative';
    clone.style.left = '0'; clone.style.top = '0';
    clone.style.width = `${rect.width}px`;
    if (opts.background) clone.style.backgroundColor = opts.background;
  }
  if (state.cut) state.notes.add('the picture stops partway: it was too big to copy whole');
  return {
    view,
    async render() {
      if (!clone) return { png: '', error, view, notes: [...state.notes] };
      try {
        await Promise.all([
          ...state.images.map(async (img) => {
            const data = await toDataUrl(img.getAttribute('src'));
            if (data) img.setAttribute('src', data);
            else { img.removeAttribute('src'); state.notes.add('an image could not be copied'); }
          }),
          ...state.backgrounds.map(async (n) => {
            const m = (n.style.backgroundImage || '').match(/url\("?([^")]+)"?\)/);
            const data = m && await toDataUrl(m[1]);
            if (data) n.style.backgroundImage = `url("${data}")`;
            else n.style.backgroundImage = 'none';
          }),
        ]);
        const fontRules = opts.fontsUrl ? await fonts(opts.fontsUrl) : '';
        const w = Math.max(1, Math.min(MAX_W, Math.ceil(rect.width)));
        const h = Math.max(1, Math.min(MAX_H, Math.ceil(rect.height)));
        if (rect.height > MAX_H) state.notes.add('only the top of it is in the picture');
        const wrap = document.createElement('div');
        wrap.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        wrap.style.cssText = `width:${w}px;height:${h}px;overflow:hidden`;
        if (fontRules) { const st = document.createElement('style'); st.textContent = fontRules; wrap.appendChild(st); }
        wrap.appendChild(clone);
        const xml = new XMLSerializer().serializeToString(wrap);
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><foreignObject x="0" y="0" width="100%" height="100%">${xml}</foreignObject></svg>`;
        const img = await loadImage('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg));
        let scale = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(MAX_PIXELS / (w * h)));
        for (let attempt = 0; attempt < 4; attempt++) {
          const c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(w * scale)); c.height = Math.max(1, Math.round(h * scale));
          const ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0, c.width, c.height);
          const png = c.toDataURL('image/png');
          if (png.length <= MAX_DATA_URL) return { png, w, h, error: '', view, notes: [...state.notes] };
          scale *= 0.7;
        }
        return { png: '', error: 'the picture was too large to send', view, notes: [...state.notes] };
      } catch (e) {
        return { png: '', error: `the browser would not draw it (${(e && e.message) || e})`, view, notes: [...state.notes] };
      }
    },
  };
}

// A short URL for showing a picture: the tell box re-renders every second
// or so while brAIn works, and a data URL would put megabytes into each
// rebuild of its HTML.
export function blobUrl(dataUrl) {
  try {
    const [head, body] = dataUrl.split(',', 2);
    const type = (head.match(/^data:([^;]+)/) || [])[1] || 'image/png';
    const bin = atob(body);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return URL.createObjectURL(new Blob([bytes], { type }));
  } catch (e) {
    return '';
  }
}
