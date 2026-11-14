// Pull to refresh, Morph's own. The Home Assistant app's pull to refresh
// moves its whole web view, which showed its white background and its own
// scroll bar and slid the window; Morph's scroller never hands a drag on to
// the window (overscroll contained), and does it here instead: pull the page down past
// the top, the mark appears under the header and rounds into a circle as it
// is pulled; let go and its dot orbits while the page reloads.

import { markSvg, morphMark } from './polish.js';
import { haptic } from './haptics.js';

const PULL = 72;

export const PULL_CSS = `
.scroll{overscroll-behavior-y:contain}
.mpull{position:absolute;left:50%;top:calc(env(safe-area-inset-top, 0px) + 14px);z-index:5;display:flex;align-items:center;gap:8px;transform:translate(-50%,0);opacity:0;pointer-events:none;color:var(--muted);font:600 12px 'Manrope',sans-serif;transition:opacity .15s ease}
.mpull svg{color:var(--violet);transition:transform .2s cubic-bezier(.22,1,.36,1)}
.mpull.armed{color:var(--text)}.mpull.armed svg{transform:scale(1.12)}
`;

export function attachPull(panel) {
  const sc = panel.rootEl.querySelector('.scroll'); if (!sc) return;
  const ind = document.createElement('div'); ind.className = 'mpull'; ind.setAttribute('aria-hidden', 'true');
  ind.innerHTML = `${markSvg(20)}<span>Pull to refresh</span>`;
  const mk = ind.firstChild;
  panel.rootEl.appendChild(ind);
  const word = ind.lastChild;
  let armed = false; let touching = false; let going = false;
  sc.addEventListener('touchstart', () => { touching = true; }, { passive: true });
  sc.addEventListener('scroll', () => {
    if (going) return;
    const d = -sc.scrollTop;
    if (d <= 0) { if (ind.style.opacity !== '0') { ind.style.opacity = '0'; morphMark(mk, 0); } if (armed) { armed = false; ind.classList.remove('armed'); } return; }
    ind.style.opacity = String(Math.min(1, d / PULL));
    morphMark(mk, d / PULL);
    const now = d >= PULL && touching;
    if (now !== armed) { armed = now; ind.classList.toggle('armed', armed); word.textContent = armed ? 'Release to refresh' : 'Pull to refresh'; if (armed) haptic('medium'); }
  }, { passive: true });
  const end = () => {
    touching = false;
    if (!armed || going) return;
    going = true; ind.classList.add('go'); ind.style.opacity = '1'; word.textContent = 'Refreshing';
    haptic('success');
    setTimeout(() => location.reload(), 250);
  };
  sc.addEventListener('touchend', end, { passive: true });
  sc.addEventListener('touchcancel', () => { touching = false; armed = false; ind.classList.remove('armed'); }, { passive: true });
}
