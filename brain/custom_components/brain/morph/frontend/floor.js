// The 16px field floor (#677) for a card Morph did not draw. A hosted
// Lovelace card, a card brAIn built and a house's own card keep their own
// shadow roots, out of reach of Morph's styles, so the floor is handed to
// every open root in the card, again whenever a root changes (fields are
// made late).
import { FIELD_FLOOR } from './styles.js';

let _floorSheet;
const _floored = new WeakSet();
const _watched = new WeakSet();

export function floorFields(node, depth = 0) {
  if (!node || depth > 10 || typeof CSSStyleSheet === 'undefined') return;
  const root = node.shadowRoot;
  if (!root && node.querySelectorAll) { node.querySelectorAll('*').forEach((n) => { if (n.shadowRoot) floorFields(n, depth + 1); }); return; }
  if (!root || !('adoptedStyleSheets' in root)) return;
  if (!_floored.has(root)) {
    try {
      if (!_floorSheet) { _floorSheet = new CSSStyleSheet(); _floorSheet.replaceSync(FIELD_FLOOR); }
      root.adoptedStyleSheets = [...root.adoptedStyleSheets, _floorSheet];
      _floored.add(root);
    } catch (e) { /* a browser without constructable sheets keeps the card's own size */ }
  }
  if (!_watched.has(root) && typeof MutationObserver !== 'undefined') {
    _watched.add(root);
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; root.querySelectorAll('*').forEach((n) => { if (n.shadowRoot) floorFields(n, depth + 1); }); });
    }).observe(root, { childList: true, subtree: true });
  }
  root.querySelectorAll('*').forEach((n) => { if (n.shadowRoot) floorFields(n, depth + 1); });
}
