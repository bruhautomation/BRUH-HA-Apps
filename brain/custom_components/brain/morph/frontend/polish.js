// Polish (house change, Oct 2026): the small motions that make Morph feel
// alive and say "Morph" — the mark that morphs, numbers that roll, a light
// where a finger lands, a glow when the house changes something by itself,
// and a background that drifts with the day. Each one carries information;
// none adds anything to the page at rest. All of it stands still under
// reduced motion.

// ------------------------------------------------------------------ the mark

// Morph's mark: a square whose bottom-right corner is rounded all the way
// into a circle's arc, with a dot at that circle's centre. Drawn here from
// four corner radii, so it can morph: all four at 8 is a circle.
const MARK_R = [1.2, 1.2, 8, 1.2];
const CIRCLE_R = [8, 8, 8, 8];
export const markPath = (r) => {
  const [a, b, c, d] = r;
  return `M4 ${4 + a}A${a} ${a} 0 0 1 ${4 + a} 4H${20 - b}A${b} ${b} 0 0 1 20 ${4 + b}V${20 - c}A${c} ${c} 0 0 1 ${20 - c} 20H${4 + d}A${d} ${d} 0 0 1 4 ${20 - d}Z`;
};
export const markSvg = (size = 18, cls = '') => `<svg class="mmark ${cls}" aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" style="flex-shrink:0"><path class="mm-p" pathLength="1" d="${markPath(MARK_R)}"/><circle class="mm-d" cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></svg>`;
// t = 0 is the mark, 1 a circle.
export function morphMark(svg, t) {
  if (!svg) return;
  const p = svg.querySelector('.mm-p'); if (!p) return;
  const k = Math.max(0, Math.min(1, t)); const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  p.setAttribute('d', markPath(MARK_R.map((r, i) => r + (CIRCLE_R[i] - r) * e)));
}

// ------------------------------------------------------------- rolling numbers

// After a redraw, a number that changed rolls like an odometer: only the
// number itself, only its digits that changed (matched from the right, so
// 9 → 10 rolls both and the unit stays put), each in its own little window
// so nothing overlaps the lines around it; up when it rose, down when it
// fell. Never while somebody is dragging, and never for a value that changed
// moments ago: a slide's preview updates many times a second (fixed after
// the first version churned and overlapped, Oct 2026).
const ROLL_SEL = '.nv > span, .big, .sval, .lgall b, .fbadge, .ib-n, .tnum';
const seen = new WeakMap(); // el -> { t: text, at: time }
const NUM = /-?\d+(?:[.,]\d+)?/;
const escH = (x) => x.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
export function rollDigits(root, busy) {
  if (!root || !root.querySelectorAll) return;
  const now = Date.now();
  root.querySelectorAll(ROLL_SEL).forEach((el) => {
    if (el.children.length && !el.querySelector('.rdw')) return; // only plain text values
    const txt = el.textContent;
    const prev = seen.get(el); seen.set(el, { t: txt, at: now });
    if (!prev || prev.t === txt) return;
    if (busy || now - prev.at < 1500 || el.closest('.drag,[data-pin]')) return;
    const ma = prev.t.match(NUM), mb = txt.match(NUM);
    if (!ma || !mb || ma[0] === mb[0]) return;
    // Only when the words around the number are unchanged ("40% · Soft" → "55% · Soft").
    const pre = txt.slice(0, mb.index), post = txt.slice(mb.index + mb[0].length);
    if (prev.t.slice(0, ma.index) !== pre || prev.t.slice(ma.index + ma[0].length) !== post) return;
    const A = ma[0], B = mb[0]; const up = parseFloat(B.replace(',', '.')) > parseFloat(A.replace(',', '.'));
    let k = 0;
    const digits = B.split('').map((ch, i) => {
      const j = A.length - (B.length - i); const old = j >= 0 ? A[j] : '';
      if (!/\d/.test(ch) || old === ch) return escH(ch);
      const d = Math.min(3, k++) * 30;
      return `<span class="rdw"><span class="rd ${up ? 'up' : 'down'}" style="animation-delay:${d}ms">${ch}</span></span>`;
    }).join('');
    el.innerHTML = `${escH(pre)}<span class="rdn">${digits}</span>${escH(post)}`;
    seen.set(el, { t: el.textContent, at: now });
    // Once rolled, back to plain text, so the number sits exactly on its line.
    setTimeout(() => { const n = el.querySelector('.rdn'); if (n && n.isConnected) n.replaceWith(document.createTextNode(n.textContent)); }, 600);
  });
}

// --------------------------------------------------------------- touch light

// A faint light spreading from where the finger landed, in the tile's colour,
// with the haptic tap.
export function touchLight(tile, x, y, color) {
  const box = tile && (tile.querySelector('.mtile') || tile); if (!box || x == null) return;
  const r = box.getBoundingClientRect();
  const s = document.createElement('span'); s.className = 'mtouch';
  const size = Math.max(r.width, r.height) * 2.2;
  s.style.cssText = `left:${x - r.left - size / 2}px;top:${y - r.top - size / 2}px;width:${size}px;height:${size}px;--tc:${color || 'var(--text)'}`;
  box.appendChild(s);
  setTimeout(() => s.remove(), 750);
}

// --------------------------------------------------------- a change elsewhere

// One faint glow in the new state's colour when something changes that this
// page did not do (an automation, somebody else, a sensor).
export function pulseTile(tile, color) {
  const box = tile && (tile.querySelector('.mtile') || tile); if (!box) return;
  box.style.setProperty('--pc', color || 'var(--text)');
  box.classList.remove('mpulse'); void box.offsetWidth; box.classList.add('mpulse');
  setTimeout(() => box.classList.remove('mpulse'), 1500);
}
export function stateColor(eid, st) {
  if (!st) return 'var(--quiet)';
  const d = eid.split('.')[0]; const s = st.state; const dc = st.attributes.device_class;
  if (['unavailable', 'unknown'].includes(s)) return 'var(--quiet)';
  if (d === 'binary_sensor') return s === 'on' ? (['motion', 'occupancy', 'presence'].includes(dc) ? 'var(--amber)' : 'var(--rose)') : 'var(--quiet)';
  if (d === 'lock') return s === 'unlocked' ? 'var(--amber)' : 'var(--indigo)';
  if (d === 'cover') return s === 'open' || s === 'opening' ? 'var(--sky)' : 'var(--quiet)';
  if (d === 'fan' || d === 'climate') return s === 'off' ? 'var(--quiet)' : 'var(--sky)';
  if (d === 'media_player') return s === 'playing' ? 'var(--violet)' : 'var(--quiet)';
  if (d === 'alarm_control_panel') return /^armed/.test(s) ? 'var(--indigo)' : s === 'triggered' ? 'var(--rose)' : 'var(--quiet)';
  if (s === 'on') return d === 'light' ? 'var(--amber)' : 'var(--teal)';
  return 'var(--quiet)';
}

// ------------------------------------------------------------------ day drift


export const POLISH_CSS = `
/* the mark drawing itself in, and breathing while brAIn works */
.mmark.drawin .mm-p{stroke-dasharray:1;stroke-dashoffset:1;animation:mmdraw .8s cubic-bezier(.65,0,.35,1) .05s forwards}
.mmark.drawin .mm-d{opacity:0;transform-origin:12px 12px;transform:scale(.2);animation:mmdot .45s cubic-bezier(.22,1,.36,1) .7s forwards}
@keyframes mmdraw{to{stroke-dashoffset:0}}
@keyframes mmdot{to{opacity:1;transform:none}}
.mbusy .brand .mmark{animation:mmbreathe 1.8s ease-in-out infinite}
@keyframes mmbreathe{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.1);opacity:.7}}
@keyframes mmshimmer{from{background-position:-60% 0}to{background-position:160% 0}}
/* the mark orbiting while the page refreshes */
.mpull.go .mm-d{animation:mmorbit .9s linear infinite;transform-origin:12px 12px}
.mpull.go svg{animation:none!important}
@keyframes mmorbit{from{transform:rotate(0) translateX(4.2px) rotate(0)}to{transform:rotate(360deg) translateX(4.2px) rotate(-360deg)}}
/* rolling numbers: each changed digit rolls through its own window */
.rdn{font-variant-numeric:tabular-nums;white-space:nowrap}
.rdw{display:inline-block;overflow:hidden;height:1lh;vertical-align:bottom}
.rd{display:inline-block;animation:.45s cubic-bezier(.22,1,.36,1) both}
.rd.up{animation-name:rdup}.rd.down{animation-name:rddown}
@keyframes rdup{from{transform:translateY(100%)}to{transform:none}}
@keyframes rddown{from{transform:translateY(-100%)}to{transform:none}}
/* touch light */
.mtouch{position:absolute;border-radius:50%;pointer-events:none;z-index:0;background:radial-gradient(circle,color-mix(in oklab,var(--tc) 22%,transparent) 0,transparent 60%);transform:scale(.1);opacity:1;animation:mtouch .7s cubic-bezier(.22,1,.36,1) forwards}
@keyframes mtouch{to{transform:scale(1);opacity:0}}
/* a change made elsewhere */
.mpulse{animation:mpulse 1.4s ease-out}
@keyframes mpulse{0%{box-shadow:inset 0 0 0 1px transparent,0 0 0 0 transparent}22%{box-shadow:inset 0 0 0 1.5px color-mix(in oklab,var(--pc) 70%,transparent),0 0 18px color-mix(in oklab,var(--pc) 28%,transparent)}100%{box-shadow:inset 0 0 0 1px transparent,0 0 0 0 transparent}}
/* the scene ripple */
.mripple{animation:mripple .7s cubic-bezier(.22,1,.36,1) both}
@keyframes mripple{0%{filter:brightness(1)}35%{filter:brightness(1.35)}100%{filter:brightness(1)}}
/* day drift: a wash over the page background only */
/* page changes: the page rises in */
.mpagein{animation:mpagein .42s cubic-bezier(.22,1,.36,1) both}
@keyframes mpagein{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.mmark .mm-p,.mmark .mm-d,.mbusy .mmark,.rd,.mtouch,.mpulse,.mripple,.mpagein,.mpull.go .mm-d{animation:none!important;stroke-dashoffset:0!important;opacity:1}.mtouch{display:none}}
`;
