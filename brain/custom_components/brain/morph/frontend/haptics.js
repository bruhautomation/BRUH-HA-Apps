// Haptics for the whole page (house change, Oct 2026: "I want the Taptic
// Engine really involved heavily in this UI"). The Home Assistant app on iOS
// and Android plays the frontend's own `haptic` event on the phone's motor;
// a phone browser that can vibrate does that instead; anything else ignores
// it. Kinds are Home Assistant's own:
//   selection  a fine detent: 2 % of a slide, 10° of the colour wheel, a room on the rail
//   light      a tap that did something (a toggle, a blind), every 10 % of a slide
//   medium     a card opening or closing in place
//   heavy      a big detent: a white on the colour track, a slide's ends, a floor on the rail
//   success / warning / failure  an answer: confirmed, asked first, refused
// Ticks closer together than the motor can play are dropped, so a fast
// slide feels like detents rather than a buzz.

const MS = { selection: 4, light: 8, medium: 12, heavy: 18, success: [8, 40, 8], warning: [12, 60, 12], failure: [20, 40, 20, 40, 20] };
const GAP = { selection: 22, light: 40, medium: 60, heavy: 60, success: 80, warning: 80, failure: 80 };
const RANK = { selection: 0, light: 1, medium: 2, heavy: 3, success: 3, warning: 3, failure: 3 };
let last = 0; let lastKind = 'selection';

export function haptic(kind) {
  const now = performance.now();
  // Only a weaker or equal tick is dropped; a big detent always plays.
  if (now - last < (GAP[kind] || 30) && (RANK[kind] || 0) <= (RANK[lastKind] || 0)) return;
  last = now; lastKind = kind;
  try { window.dispatchEvent(new CustomEvent('haptic', { detail: kind })); } catch (e) { /* fine */ }
  try { if (navigator.vibrate && !window.externalApp && !(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.externalBus)) navigator.vibrate(MS[kind] || 6); } catch (e) { /* fine */ }
}
