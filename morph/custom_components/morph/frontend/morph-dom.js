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
// animation is restarted at the phase it had reached.

const KEYS = ['data-key', 'data-member', 'data-k', 'data-tile', 'id'];

function keyOf(n) {
  if (n.nodeType !== 1) return null;
  for (const k of KEYS) { const v = n.getAttribute(k); if (v) return k + '=' + v; }
  return null;
}

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

// A spinning part whose speed changed: keep the angle it had reached.
function keepPhase(el, style) {
  try {
    const anim = el.getAnimations ? el.getAnimations()[0] : null;
    const t = anim && anim.currentTime;
    el.setAttribute('style', style);
    if (t != null) { const a2 = el.getAnimations()[0]; if (a2) a2.currentTime = t; }
  } catch (e) {
    el.setAttribute('style', style);
  }
}

function sameKind(a, b) {
  return a.nodeType === b.nodeType && (a.nodeType !== 1 || (a.tagName === b.tagName && keyOf(a) === keyOf(b)));
}

function morphNode(from, to, active) {
  if (from.nodeType === 3 || from.nodeType === 8) {
    if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue;
    return;
  }
  if (untouchable(from)) return;
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
    if (match && match.nodeType === 1 && match.tagName !== w.tagName) match = null;
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
