// A keyed DOM morph: make `el`'s children match `html` by changing only
// what differs, instead of replacing them.
//
// Morph redraws on every state change in the house, and `innerHTML` threw
// away every node each time: an animation restarted, a fan's blades jumped
// back to their start angle, a hovered button lost its hover, a <details>
// somebody opened closed again. This keeps every node whose place and kind
// did not change and edits it in place.
//
// Children are matched by key — `data-key`, `data-member`, `data-k`,
// `data-tile`, then `id` — and otherwise by position and tag. A few nodes
// are never touched from outside:
//   * a custom element (`-` in its tag) — its insides are its own (a hosted
//     Lovelace card, a house's card code);
//   * anything carrying `data-ll` or `data-morph-keep` — a slot something
//     else fills;
//   * the focused input, textarea or select — its value is the person's;
//   * a <details> keeps whether it is open.
// A spinning icon (`.spin`) whose duration changes keeps its angle: the
// animation is restarted at the phase it had reached, and (house change) it
// eases from the speed it was turning at to the new one.
// House changes: what a person is dragging (`.drag`) or has just set
// (`data-pin`, a time in ms until which it is left alone) is not redrawn
// under their finger; and two elements are only the same thing when their
// kind (first class) agrees too, so a closed strip is replaced by an opened
// group's rows rather than morphed into them.

const KEYS = ['data-key', 'data-member', 'data-k', 'data-tile', 'id'];

function keyOf(n) {
  if (n.nodeType !== 1) return null;
  for (const k of KEYS) { const v = n.getAttribute(k); if (v) return k + '=' + v; }
  return null;
}

function pinned(el) {
  if (el.classList && el.classList.contains('drag')) return true;
  const p = el.getAttribute && el.getAttribute('data-pin');
  return !!p && Number(p) > Date.now();
}

const kind = (n) => (n.getAttribute('class') || '').trim().split(/\s+/)[0];

const untouchable = (n) => n.nodeType === 1 && (n.tagName.includes('-') || n.hasAttribute('data-ll') || n.hasAttribute('data-morph-keep'));

function syncAttrs(from, to) {
  const keepOpen = from.tagName === 'DETAILS';
  for (const a of Array.from(from.attributes)) {
    if (keepOpen && a.name === 'open') continue;
    if (!to.hasAttribute(a.name)) from.removeAttribute(a.name);
  }
  for (const a of Array.from(to.attributes)) {
    if (keepOpen && a.name === 'open') continue;
    if (from.getAttribute(a.name) !== a.value) {
      if (a.name === 'style' && from.classList && from.classList.contains('spin')) keepPhase(from, a.value);
      else from.setAttribute(a.name, a.value);
    }
  }
}

// A spinning part whose speed changed: keep the angle it had reached, then
// ease the rate (house change).
function keepPhase(el, style) {
  let an = null, d0 = 0, t0 = null, rate0 = 1;
  try {
    an = el.getAnimations ? el.getAnimations()[0] : null;
    if (an) { d0 = Number(an.effect.getComputedTiming().duration) || 0; t0 = an.currentTime; rate0 = an.playbackRate || 1; }
  } catch (e) { an = null; }
  el.setAttribute('style', style);
  if (!an || !d0 || t0 == null) return;
  try {
    const an2 = el.getAnimations()[0]; if (!an2) return;
    const d1 = Number(an2.effect.getComputedTiming().duration) || 0;
    if (!d1 || Math.abs(d1 - d0) < 1) return;
    an2.currentTime = ((t0 % d0) / d0) * d1;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    // Start at the speed it was turning at and settle on the new one over
    // ~1.2 s; a change mid-way starts from wherever the last one had got to.
    const r0 = (d1 / d0) * rate0; const start = performance.now(); const span = 1200;
    const run = (el.__spinRun = (el.__spinRun || 0) + 1);
    an2.playbackRate = r0;
    const step = (now) => {
      const f = Math.min(1, (now - start) / span); const e = 1 - Math.pow(1 - f, 3);
      if (el.__spinRun !== run) return;
      try { an2.playbackRate = r0 + (1 - r0) * e; } catch (er) { return; }
      if (f < 1 && el.isConnected && el.__spinRun === run) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  } catch (e) { /* the browser cannot; the plain change stands */ }
}

function sameKind(a, b) {
  if (a.nodeType !== b.nodeType) return false;
  if (a.nodeType !== 1) return true;
  if (a.tagName !== b.tagName || keyOf(a) !== keyOf(b)) return false;
  const ka = kind(a), kb = kind(b);
  return !ka || !kb || ka === kb;
}

function morphNode(from, to, active) {
  if (from.nodeType === 3 || from.nodeType === 8) {
    if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue;
    return;
  }
  if (untouchable(from) || pinned(from)) return;
  if (from === active && /^(INPUT|TEXTAREA|SELECT)$/.test(from.tagName)) {
    // The person is typing here: attributes may move, the value may not.
    for (const a of Array.from(to.attributes)) if (a.name !== 'value' && from.getAttribute(a.name) !== a.value) from.setAttribute(a.name, a.value);
    return;
  }
  syncAttrs(from, to);
  if (from.tagName === 'TEXTAREA') { if (from.value !== to.value && from !== active) from.value = to.value; return; }
  if (from.tagName === 'INPUT' && from !== active) {
    if (from.value !== to.value) from.value = to.value;
    if (from.checked !== to.checked) from.checked = to.checked;
  }
  morphChildren(from, to, active);
}

function morphChildren(from, to, active) {
  const want = Array.from(to.childNodes);
  const have = Array.from(from.childNodes);
  const byKey = new Map();
  have.forEach((n) => { const k = keyOf(n); if (k) byKey.set(k, n); });
  const used = new Set();
  let cursor = from.firstChild;
  want.forEach((w) => {
    const k = keyOf(w);
    let match = null;
    if (k && byKey.has(k) && !used.has(byKey.get(k))) match = byKey.get(k);
    else if (!k) {
      // The next unkeyed node of the same kind, from where we are.
      let c = cursor;
      while (c && (used.has(c) || keyOf(c))) c = c.nextSibling;
      if (c && sameKind(c, w)) match = c;
    }
    if (match && match.nodeType === 1 && (match.tagName !== w.tagName || !sameKind(match, w))) match = null;
    if (match) {
      used.add(match);
      if (match !== cursor) from.insertBefore(match, cursor);
      else cursor = cursor.nextSibling;
      morphNode(match, w, active);
    } else {
      const fresh = document.importNode(w, true);
      from.insertBefore(fresh, cursor);
      used.add(fresh);
    }
  });
  Array.from(from.childNodes).forEach((n) => { if (!used.has(n)) n.remove(); });
}

// Make `el`'s children `html`. Returns false when nothing could be parsed.
export function morph(el, html, root) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html;
  const active = root && root.activeElement ? root.activeElement : (el.getRootNode && el.getRootNode().activeElement) || null;
  morphChildren(el, tpl.content, active);
  return true;
}
