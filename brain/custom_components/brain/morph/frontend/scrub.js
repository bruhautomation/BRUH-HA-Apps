// The room rail (house change, Oct 2026; rebuilt 29 Oct 2026).
//
// The household, 29 Oct 2026: "I kind of envision this morph scroll bar
// being opened with a left swipe, it stays open. You can swipe up and down to
// jump between cards; if you directly touch one of the cards or icons in the
// morph bar it goes to that spot and the morph bar closes. You can also swipe
// right to close the bar." And before it: the look of the brAIn 3.0 rail
// (floors named beside it), a pull that feels mechanical, with haptics, no
// left/right motion once it is open, labels that never jump, and "highlight
// the header for the active card … subtle and beautiful".
//
// Closed: a slim notched rail at the right edge, one notch per room, floors
// set apart, coloured only for state (amber a light on, rose a door open or
// something that needs you). The room in view is the bright notch. A finger
// on it that moves up or down is an ordinary scroll of the page.
//
// Opening: a pull to the left. The track follows the finger, ticks at a
// third and two thirds, and at ARM clunks open (a heavy haptic). The panel
// slides in once and then holds still.
//
// Open: the notches themselves, wider, with the floors named beside them,
// in the dashboard's own order (never re-sorted from where things happen to
// be on screen, which is what made the old labels jump). Nothing in it moves
// while it is open.
//   * Without lifting, sliding up or down goes room to room: a fine tick per
//     room, a heavy bump per floor, and the page glides there on a soft,
//     critically damped spring.
//   * Letting go lands on that room and closes the rail.
// Revised again the same day ("I wanted to keep the scroll bar look like we
// had before with the vertical rectangles. I don't need the card labels there
// … because you're highlighting the active card"): open, there is no column
// of names; the rail of notches itself widens and stays, the floors named
// beside it in fixed places, and the notches are what is slid along and
// tapped.
// And once more ("I don't like the staying open behavior … go back to the
// swipe left to open and then just scrolling and releasing normally. Keep the
// highlighting"): it is one gesture again. The swipe left opens it, the same
// finger slides up and down the notches, and letting go lands there and
// closes it. No tap targets, no swipe right: lifting the finger is closing.
// The room being gone to is lit in place on the page: a hairline ring and a
// soft inner glow in the room's own colour, its title and icon brought up,
// and the other rooms dimmed a little while the rail is open.
//
// It bends design rule 1 (nothing floats) while it is open, at the
// household's request.

import { haptic } from './haptics.js';

const SKIP = /^(__cases|__todo|__now|__new@)/;
const K = 230, ZETA = 1; // the page's glide to a room: soft, no overshoot
const HEAD = 30;       // the room's title sits this far below its top: that is what meets the thumb
const FLOOR_GAP = 12, ROOM_GAP = 3;
const ARM = 12;     // px of leftward pull that opens the rail
const SLOP = 8;     // px of up-or-down movement that makes it an ordinary scroll
const STRETCH = 0.3;
const TAP_PX = 8, TAP_MS = 350;
const CLOSE_PX = 36; // a swipe right this far closes it
const ROW_MAX = 34, ROW_MIN = 17, HEAD_K = 0.75; // row height; a floor heading is 3/4 of a row

export const SCRUB_CSS = `
.scroll{scrollbar-width:none}.scroll::-webkit-scrollbar{display:none}
/* iOS flashes its own scroll indicator when the page appears, whatever the CSS
   says: the scroller runs 18px past the right edge (padded back, so nothing
   moves) and the indicator is drawn where it is clipped away. */
[data-morph-root]{overflow:hidden}
.scroll{width:calc(100% + 18px)!important;padding-right:18px;box-sizing:border-box}
.mrail{position:absolute;top:calc(84px + env(safe-area-inset-top, 0px));bottom:calc(96px + env(safe-area-inset-bottom, 0px));right:0;width:30px;z-index:30;touch-action:none;cursor:w-resize;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent}
[data-morph-root]:has(input:focus, textarea:focus, .askin:not(:placeholder-shown)) .mrail{pointer-events:none}
.mrail-track{position:absolute;top:0;bottom:0;right:6px;width:3px;display:flex;flex-direction:column;opacity:.45;transform:translateX(var(--px,0px));transition:width .25s var(--ease),opacity .25s ease,transform .3s var(--ease)}
.mrail.shown .mrail-track{opacity:.9}
.mrail.pulling .mrail-track{transition:none;width:calc(3px + var(--pull,0) * 3px);opacity:calc(.45 + var(--pull,0) * .55)}
.mrail.open .mrail-track{opacity:1;width:9px;right:10px;transform:translateX(var(--cx,0px));transition:width .3s cubic-bezier(.22,1,.36,1),right .3s cubic-bezier(.22,1,.36,1),opacity .2s ease}
.mrail.open.closing .mrail-track{transition:none}
.mrail.open .mrail-seg{background:color-mix(in oklab,var(--text) 20%,transparent)}
.mrail.open .mrail-seg.st{background:color-mix(in oklab,var(--h) 60%,transparent)}
.mrail.open .mrail-seg.here{background:color-mix(in oklab,var(--text) 45%,transparent)}
.mrail.open .mrail-seg.cur{background:var(--rc,var(--text));box-shadow:0 0 10px color-mix(in oklab,var(--rc,var(--text)) 50%,transparent)}
.mrail-fls{position:absolute;inset:0;pointer-events:none}
.mrail-fl{position:absolute;right:26px;transform:translateY(-70%);padding:3px 6px;border-radius:6px;background:color-mix(in oklab,var(--bg) 82%,transparent);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);font:700 8.5px/1 'Manrope',sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--quiet);white-space:nowrap;opacity:0;transition:opacity .2s ease}
.mrail.open .mrail-fl{opacity:.85}
.mrail-seg{--h:var(--text);flex:1 1 0;min-height:2px;border-radius:2px;background:color-mix(in oklab,var(--text) 22%,transparent);transition:background-color .3s ease}
.mrail-seg.fl{margin-top:${FLOOR_GAP}px}.mrail-seg+.mrail-seg:not(.fl){margin-top:${ROOM_GAP}px}
.mrail-seg.st{background:color-mix(in oklab,var(--h) 70%,transparent)}
.mrail.pulling .mrail-seg{background:color-mix(in oklab,var(--text) calc(22% + var(--pull,0) * 20%),transparent)}
.mrail-glide{position:absolute;right:6px;width:3px;border-radius:2px;background:color-mix(in oklab,var(--gh,var(--text)) 85%,transparent);opacity:0;pointer-events:none;transition:top .38s cubic-bezier(.22,1,.36,1),height .38s cubic-bezier(.22,1,.36,1),opacity .3s ease,background-color .3s ease}
.mrail-glide.on{opacity:.45}.mrail.shown .mrail-glide.on{opacity:1}.mrail.open .mrail-glide,.mrail.pulling .mrail-glide{opacity:0}
/* The tip beside a finger resting on the closed rail. */
.mrail-tw{position:absolute;right:26px;top:0;pointer-events:none;will-change:transform}
.mrail-tip{display:flex;align-items:center;gap:8px;margin-top:-17px;padding:8px 12px 8px 10px;border-radius:12px;white-space:nowrap;font:600 12.5px/1.2 'Manrope',sans-serif;color:var(--text);background:color-mix(in oklab,var(--surface) 94%,transparent);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 0 0 1px var(--line2),0 10px 28px rgba(0,0,0,.3);opacity:0;visibility:hidden;transform:translateX(10px) scale(.96);transform-origin:100% 50%;transition:opacity .18s ease,transform .26s var(--ease),visibility 0s .26s}
.mrail-tip.on{opacity:1;visibility:visible;transform:none;transition:opacity .18s ease,transform .26s var(--ease)}
.mrail-tip .tp-ar{position:relative;width:22px;height:4px;border-radius:2px;background:color-mix(in oklab,var(--text) 16%,transparent);overflow:hidden;flex:none}
.mrail-tip .tp-ar::after{content:'';position:absolute;inset:0;border-radius:2px;background:var(--text);transform-origin:100% 50%;transform:scaleX(var(--pull,0))}
.mrail-tip .tp-ch{font:700 14px/1 'Manrope',sans-serif;color:var(--muted);flex:none}
.mrail-tip.nudge .tp-ch{animation:mrailnudge 1.1s var(--ease) infinite}
@keyframes mrailnudge{0%,100%{transform:none}45%{transform:translateX(-5px)}}
.mrail-tip .tp-sub{display:block;font-weight:500;font-size:11.5px;color:var(--muted);margin-top:2px}
.mrail.open .mrail-tw{visibility:hidden}
/* Open: the same notches, wider, held still; an invisible surface takes the finger. */
.mrail-pan{position:absolute;inset:0;display:none;touch-action:none;cursor:ns-resize}
.mrail.open{width:46px}

/* The room being gone to, lit in place on the page. Morph's engine sets an
   inline opacity on every room, so the dimming has to say !important; a room
   clips its own edges, so the ring is drawn inside it. */
[data-board] section.sec .secbg{transition:box-shadow .35s var(--ease)}
[data-board] section.sec .sechead h2{transition:color .3s ease}
[data-board] section.sec .sechead h2 .secic{transition:opacity .3s ease,color .3s ease}
[data-board].mrail-dim section.sec{transition:opacity .3s var(--ease)}
[data-board].mrail-dim section.sec:not(.mrail-tgt){opacity:.5!important}
[data-board] section.sec.mrail-tgt .secbg{box-shadow:inset 0 0 0 1.5px color-mix(in oklab,var(--rh,var(--text)) 55%,transparent),inset 0 0 42px -6px color-mix(in oklab,var(--rh,var(--text)) 26%,transparent)!important}
[data-board] section.sec.mrail-tgt .sechead h2{color:color-mix(in oklab,var(--rh,var(--text)) 28%,var(--text))}
[data-board] section.sec.mrail-tgt .sechead h2 .secic{opacity:1!important;color:var(--rh,var(--text))!important}
@media (prefers-reduced-motion:reduce){.mrail-track,.mrail-seg,.mrail-tip,.mrail-pan,.mrail-row,[data-board] section.sec,[data-board] section.sec .secbg{transition:none!important}.mrail-tip .tp-ch{animation:none!important}}
`;

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class Scrub {
  constructor(panel) {
    this.p = panel; this.rooms = []; this.sig = ''; this.isOpen = false; this.cur = -1;
    const el = (this.el = document.createElement('div'));
    el.className = 'mrail'; el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<div class="mrail-track"></div><i class="mrail-glide"></i><div class="mrail-tw"><div class="mrail-tip"><span class="tp-ch">‹</span><span class="tp-tx"></span><span class="tp-ar"></span></div></div><div class="mrail-fls"></div><div class="mrail-pan"></div>';
    this.track = el.children[0]; this.glide = el.children[1]; this.tw = el.children[2]; this.tip = this.tw.firstChild;
    this.fls = el.children[3]; this.pan = el.children[4];
    panel.rootEl.style.position = 'relative';
    panel.rootEl.appendChild(el);
    this.sc = panel.rootEl.querySelector('.scroll');
    // The closed rail: a pull left opens it, up or down scrolls the page.
    this.track.parentNode.addEventListener('pointerdown', (e) => { if (!this.isOpen) this.press(e); });
    el.addEventListener('pointermove', (e) => this.drag(e));
    el.addEventListener('pointerup', (e) => this.lift(e));
    el.addEventListener('pointercancel', (e) => this.lift(e, true));
    // The open column.
    this.pan.addEventListener('pointerdown', (e) => this.panDown(e));
    this.pan.addEventListener('pointermove', (e) => this.panMove(e));
    this.pan.addEventListener('pointerup', (e) => this.panUp(e));
    this.pan.addEventListener('pointercancel', (e) => this.panUp(e, true));
    // Morph's own press handling (hold, tap outside) never sees the rail.
    ['pointerdown', 'pointerup', 'click'].forEach((t) => el.addEventListener(t, (e) => e.stopPropagation()));
    // A touch anywhere else closes it.
    panel.rootEl.addEventListener('pointerdown', (e) => { if (this.isOpen && !el.contains(e.target)) this.close(); }, true);
    this.sc.addEventListener('scroll', () => this.onScroll(), { passive: true });
    // Held to the screen, not to Morph's frame (house change, 3 Nov 2026:
    // "the sections sliding some when scrolling … those section labels
    // should be fixed in place"). Inside brAIn's shell, scrolling down slides
    // the tab row away and Morph's frame grows upward by its height; a rail
    // pinned to the frame's top and bottom stretched with it, every notch
    // grew and the floor names (placed once) drifted off their notches. The
    // rail keeps the place and height it has with the header showing, and
    // its top is moved back by however far the frame has moved, in the same
    // frame (a ResizeObserver runs before paint), so nothing on it moves.
    this.pin(true);
    try { this._pinRO = new ResizeObserver(() => this.pin()); this._pinRO.observe(panel.rootEl); } catch (e) { /* the CSS place */ }
    window.addEventListener('resize', () => this.pin(true), { passive: true });
  }

  pin(reset) {
    const el = this.el; const root = this.p.rootEl;
    const rr = root.getBoundingClientRect();
    if (reset || this._base == null || window.innerWidth !== this._vw || window.innerHeight !== this._vh) {
      // The CSS place, measured as it is: inset from the frame's top and bottom.
      el.style.removeProperty('top'); el.style.removeProperty('height'); el.style.removeProperty('bottom');
      const er = el.getBoundingClientRect();
      if (!er.height) return;
      this._base = { top: er.top - rr.top, bottom: rr.bottom - er.bottom };
      this._vw = window.innerWidth; this._vh = window.innerHeight; this._maxTop = rr.top;
    }
    // With the header showing the frame is at its lowest; that is the rail's place.
    if (rr.top > this._maxTop) this._maxTop = rr.top;
    const top = this._maxTop + this._base.top;               // on the screen
    const h = Math.max(60, rr.bottom - this._base.bottom - top);
    const y = (top - rr.top).toFixed(1) + 'px'; const hh = h.toFixed(1) + 'px';
    if (el.style.top !== y) el.style.top = y;
    if (el.style.height !== hh) { el.style.height = hh; el.style.bottom = 'auto'; if (this.rooms.length) this.layout(); }
  }

  // ── The rooms ──────────────────────────────────────────────────────
  // In the dashboard's own order (floors, then rooms), never re-sorted by
  // where they happen to be on screen while the layout is moving.
  read() {
    const P = this.p;
    const els = new Map();
    P.rootEl.querySelectorAll('[data-board] [data-sec]').forEach((s) => els.set(s.getAttribute('data-sec'), s));
    const fls = (P._floorsOrdered || []).map((F) => F.fl.title);
    const model = (P.engine && P.engine.model && P.engine.model.sections) || [];
    const rooms = [];
    model.forEach((ms) => {
      const s = els.get(ms.id);
      if (!s || SKIP.test(ms.id) || s.offsetParent === null || s.offsetHeight < 40) return;
      const sec = P.sectionById ? P.sectionById(ms.id) : null;
      if (!sec) return;
      const st = this.state(sec, ms.id);
      let rc = '';
      try { rc = P.railColor ? P.railColor(ms.id) : ''; } catch (e) { /* plain */ }
      rooms.push({ id: ms.id, el: s, title: sec.title || '', icon: sec.icon || '', hue: st.hue, rc, floor: ms.floor || 0, floorTitle: fls[ms.floor || 0] || '' });
    });
    rooms.unshift({ id: '__top', el: null, top: true, title: 'Top', icon: 'mdi:arrow-collapse-up', hue: '', rc: '', floor: -99, floorTitle: '' });
    return rooms;
  }

  // A room's state: its notch colour.
  state(sec, id) {
    const P = this.p; const H = P.hass; if (!sec || !H) return { hue: '' };
    let ents = [];
    try { ents = P.sectionEntities(sec).slice(); } catch (e) { /* none */ }
    try { (P.headItems(sec) || []).forEach((h) => ents.push(h.entity)); } catch (e) { /* none */ }
    let lit = 0; let open = 0;
    ents.forEach((e) => {
      const st = H.states[e]; if (!st) return;
      const d = e.split('.')[0]; const dc = st.attributes.device_class;
      if (d === 'binary_sensor' && ['door', 'garage_door', 'window', 'opening'].includes(dc) && st.state === 'on') open += 1;
      if (d === 'cover' && dc === 'garage' && st.state === 'open') open += 1;
      if (d === 'light' && st.state === 'on' && !(st.attributes.entity_id || []).length && !/indicator|\bled\b/i.test(e + ' ' + (st.attributes.friendly_name || ''))) lit += 1;
    });
    let cases = 0;
    try { cases = (P.casesPlaced() || []).filter((k) => k._sec === id).length; } catch (e) { /* none */ }
    return { hue: open || cases ? 'var(--rose)' : lit ? 'var(--amber)' : '' };
  }

  // Morph's panel calls paint() on scroll and after a render.
  paint() { clearTimeout(this._paintT); this._paintT = setTimeout(() => this.refresh(), 160); }

  refresh() {
    const P = this.p;
    const hide = P.s.edit || P.s.thenAt;
    this.el.style.display = hide ? 'none' : '';
    if (hide) { if (this.isOpen) this.close(true); return; }
    const rooms = this.read();
    const sig = rooms.map((r) => r.id + ':' + r.floor).join('|');
    // The column is never rebuilt while it is open: it holds still.
    if (this.isOpen && sig === this.sig) { this.rooms.forEach((r, i) => { if (rooms[i]) { r.el = rooms[i].el; r.hue = rooms[i].hue; } }); this.paintState(); return; }
    this.rooms = rooms;
    if (sig !== this.sig) {
      this.sig = sig;
      this.track.innerHTML = rooms.map((r, i) => `<div class="mrail-seg${i && r.floor !== rooms[i - 1].floor ? ' fl' : ''}"></div>`).join('');
      [...this.track.children].forEach((seg, i) => { if (rooms[i] && rooms[i].rc) seg.style.setProperty('--rc', rooms[i].rc); });
      this.fls.innerHTML = rooms.map((r, i) => (r.floorTitle && (!i || r.floor !== rooms[i - 1].floor) ? `<span class="mrail-fl" data-i="${i}">${esc(r.floorTitle)}</span>` : '')).join('');
      this.layout();
    }
    this.paintState();
    this.onScroll(true);
  }

  paintState() {
    [...this.track.children].forEach((seg, i) => { const h = this.rooms[i] && this.rooms[i].hue; seg.classList.toggle('st', !!h); if (h) seg.style.setProperty('--h', h); else seg.style.removeProperty('--h'); });
  }

  // The floor names sit just above their first notch, placed once per
  // layout: nothing moves while the rail is open.
  layout() {
    const segs = this.track.children; const t0 = this.el.getBoundingClientRect().top;
    [...this.fls.children].forEach((f) => { const sg = segs[Number(f.dataset.i)]; if (sg) f.style.top = (sg.getBoundingClientRect().top - t0 - 1).toFixed(1) + 'px'; });
  }

  // The notch under a y on the screen; across a gap, the nearer one.
  rowAt(clientY) {
    const segs = [...this.track.children];
    for (let i = 0; i < segs.length; i++) {
      const r = segs[i].getBoundingClientRect();
      const next = segs[i + 1] && segs[i + 1].getBoundingClientRect();
      if (clientY < (next ? (r.bottom + next.top) / 2 : Infinity)) return i;
    }
    return segs.length - 1;
  }

  // The room in view: the bright notch while closed, the marked row while open.
  inView() {
    const line = this.sc.getBoundingClientRect().top + this.sc.clientHeight * 0.3;
    let k = 0; this.rooms.forEach((r, i) => { if (r.el && r.el.getBoundingClientRect().top <= line) k = i; });
    return k;
  }

  onScroll(quiet) {
    if (!this.rooms.length) return;
    const k = this.inView();
    if (this.isOpen) {
      if (k !== this._here) { this._here = k; [...this.track.children].forEach((sg, i) => sg.classList.toggle('here', i === k)); }
      return;
    }
    const seg = this.track.children[k];
    if (seg && seg.offsetHeight) {
      this.glide.style.top = (this.track.offsetTop + seg.offsetTop) + 'px'; this.glide.style.height = seg.offsetHeight + 'px';
      const h = this.rooms[k] && this.rooms[k].hue; if (h) this.glide.style.setProperty('--gh', h); else this.glide.style.removeProperty('--gh');
      this.glide.classList.add('on');
    }
    if (quiet === true) return;
    this.el.classList.add('shown');
    clearTimeout(this._hideT); this._hideT = setTimeout(() => this.el.classList.remove('shown'), 900);
  }

  // ── Closed: the pull that opens it ─────────────────────────────────
  press(e) {
    if (e.button != null && e.button !== 0) return;
    try { this.el.setPointerCapture(e.pointerId); } catch (er) { /* fine */ }
    cancelAnimationFrame(this._fling); this._fling = null;
    this.g = { x: e.clientX, y: e.clientY, mode: 'wait', lastY: e.clientY, lastT: performance.now(), v: 0, notch: 0 };
    this.placeTip(e.clientY);
    clearTimeout(this._tipT); clearTimeout(this._restT);
    this._restT = setTimeout(() => { if (this.g && this.g.mode === 'wait') this.showTip('Swipe left to open the rooms', true); }, 220);
  }

  drag(e) {
    const g = this.g; if (!g) return;
    e.preventDefault();
    // Open: the same finger goes room to room.
    if (g.mode === 'scrub') { this.thumbY = e.clientY; this.goTo(this.rowAt(e.clientY), false); return; }
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (g.mode === 'wait') {
      if (Math.abs(dy) > SLOP && Math.abs(dy) > Math.abs(dx) * 1.2) { g.mode = 'pass'; this.hideTip(); this.setPull(0); clearTimeout(this._restT); }
      else if (dx < -2) { g.mode = 'pull'; clearTimeout(this._restT); }
    }
    if (g.mode === 'pull') {
      const f = Math.max(0, Math.min(1, -dx / ARM));
      const notch = Math.floor(f * 3);
      if (notch > g.notch && notch < 3) haptic('selection');
      g.notch = Math.max(g.notch, notch);
      this.setPull(f, Math.min(-dx, ARM) + Math.max(0, -dx - ARM) * STRETCH);
      this.placeTip(e.clientY);
      this.showTip(f < 1 ? 'Keep swiping left' : 'Open', false);
      if (f >= 1) { g.mode = 'scrub'; this.thumbY = e.clientY; this.open(); this.goTo(this.rowAt(e.clientY), false); return; }
      if (Math.abs(dy) > SLOP * 2 && Math.abs(dy) > -dx * 2) { g.mode = 'pass'; this.hideTip(); this.setPull(0); }
    }
    if (g.mode === 'pass') {
      const now = performance.now(); const d = e.clientY - g.lastY;
      const dt = Math.max(1, now - g.lastT);
      g.v = 0.8 * (d / dt) + 0.2 * g.v; g.lastY = e.clientY; g.lastT = now;
      if (this.p.engine) this.p.engine.sc = null;
      this.sc.scrollTop -= d;
    }
  }

  lift(e, cancelled) {
    const g = this.g; this.g = null;
    clearTimeout(this._restT); this.setPull(0);
    if (!g) return;
    // Letting go lands on the room under the finger and closes the rail;
    // the glide finishes on its own.
    if (g.mode === 'scrub') { this.close(); return; }
    if (g.mode === 'pass') { if (!cancelled && performance.now() - g.lastT < 80) this.fling(-g.v * 16); return; }
    if (cancelled) { this.hideTip(); return; }
    this.placeTip(g.y);
    this.showTip(g.mode === 'pull' ? 'A little further left' : 'Swipe left to open the rooms', true, 'then slide to a room, or tap one');
    haptic('selection');
    this._tipT = setTimeout(() => this.hideTip(), 2200);
  }

  fling(v) {
    let last = performance.now();
    const step = (now) => {
      const dt = Math.min(32, now - last); last = now;
      v *= Math.pow(0.95, dt / 16.7);
      const before = this.sc.scrollTop; this.sc.scrollTop += v * dt / 16.7;
      if (Math.abs(v) < 0.3 || this.sc.scrollTop === before) { this._fling = null; return; }
      this._fling = requestAnimationFrame(step);
    };
    if (Math.abs(v) > 1) this._fling = requestAnimationFrame(step);
  }

  setPull(f, px = f * ARM) {
    this.el.style.setProperty('--pull', f.toFixed(3));
    this.el.style.setProperty('--px', (-px).toFixed(1) + 'px');
    this.el.classList.toggle('pulling', f > 0);
  }

  placeTip(clientY) {
    const er = this.el.getBoundingClientRect();
    this.tw.style.transform = `translate3d(0,${Math.max(24, Math.min(er.height - 24, clientY - er.top)).toFixed(1)}px,0)`;
  }

  showTip(text, nudge, sub) {
    clearTimeout(this._tipT);
    const tx = this.tip.querySelector('.tp-tx');
    const html = esc(text) + (sub ? `<span class="tp-sub">${esc(sub)}</span>` : '');
    if (tx.innerHTML !== html) tx.innerHTML = html;
    this.tip.classList.toggle('nudge', !!nudge);
    this.tip.classList.add('on');
  }

  hideTip() { clearTimeout(this._tipT); this.tip.classList.remove('on', 'nudge'); }

  // ── Open ───────────────────────────────────────────────────────────
  open() {
    this.hideTip(); this.setPull(0);
    this.refresh();
    if (this.rooms.length < 2) return;
    this.isOpen = true; this._here = -1;
    this.el.classList.add('open');
    this.el.style.setProperty('--cx', '0px');
    requestAnimationFrame(() => { this.layout(); this.onScroll(true); });
    haptic('heavy');
    this.cur = -1;
  }

  close(quiet) {
    if (!this.isOpen) return;
    this.isOpen = false; this.pg = null;
    this.el.classList.remove('open', 'closing');
    this.el.style.setProperty('--cx', '0px');
    [...this.track.children].forEach((sg) => sg.classList.remove('cur', 'here'));
    this.cur = -1;
    this.unlight();
    if (!quiet) haptic('light');
    this.onScroll(true);
  }

  panDown(e) {
    if (!this.isOpen) return;
    e.preventDefault();
    try { this.pan.setPointerCapture(e.pointerId); } catch (er) { /* fine */ }
    this.pg = { x: e.clientX, y: e.clientY, t: performance.now(), mode: 'wait', start: this.rowAt(e.clientY) };
  }

  panMove(e) {
    const g = this.pg; if (!g || !this.isOpen) return;
    e.preventDefault();
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (g.mode === 'wait') {
      if (dx > TAP_PX && dx > Math.abs(dy) * 1.2) { g.mode = 'shut'; this.el.classList.add('closing'); }
      else if (Math.abs(dy) > TAP_PX / 2) g.mode = 'sweep';
    }
    if (g.mode === 'shut') {
      // The panel follows the finger out; far enough, it is gone.
      this.el.style.setProperty('--cx', Math.min(24, Math.max(0, dx) * 0.5).toFixed(1) + 'px');
      return;
    }
    if (g.mode === 'sweep') this.goTo(this.rowAt(e.clientY), false);
  }

  panUp(e, cancelled) {
    const g = this.pg; this.pg = null; if (!g || !this.isOpen) return;
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (g.mode === 'shut') {
      this.el.classList.remove('closing');
      if (!cancelled && dx > CLOSE_PX) this.close();
      else this.el.style.setProperty('--cx', '0px');
      return;
    }
    if (cancelled) return;
    if (g.mode === 'wait' && Math.abs(dx) < TAP_PX && Math.abs(dy) < TAP_PX && performance.now() - g.t < TAP_MS * 2) {
      // A tap: go there, and close once the page is on its way.
      this.goTo(this.rowAt(e.clientY), true);
      setTimeout(() => this.close(true), 120);
      haptic('light');
    }
    // After a sweep it stays open, on the room it was left at.
  }

  goTo(k, tapped) {
    if (k == null || k < 0 || k >= this.rooms.length) return;
    if (k !== this.cur) {
      const prev = this.cur; this.cur = k;
      const room = this.rooms[k];
      // The first room is the open clunk itself; after that a tick per room, a bump per floor.
      if (!tapped && prev >= 0) haptic(this.rooms[prev].floor !== room.floor ? 'heavy' : 'selection');
      [...this.track.children].forEach((sg, i) => sg.classList.toggle('cur', i === k));
      this.light(room);
    }
    const room = this.rooms[k];
    this.targetEl = room.el; this.targetTop = !!room.top;
    this.spring();
  }

  // The room being gone to, lit in place; the rest dimmed while it is open.
  light(room) {
    clearTimeout(this._litT);
    const board = this.p.rootEl.querySelector('[data-board]');
    this.p.rootEl.querySelectorAll('section.sec.mrail-tgt').forEach((x) => { if (!room || x !== room.el) x.classList.remove('mrail-tgt'); });
    if (board) board.classList.toggle('mrail-dim', !!(room && room.el));
    if (!room || !room.el) return;
    if (room.rc) room.el.style.setProperty('--rh', room.rc); else room.el.style.removeProperty('--rh');
    room.el.classList.add('mrail-tgt');
  }

  // Closing: the others come back at once, the lit room fades a moment later.
  unlight() {
    const board = this.p.rootEl.querySelector('[data-board]');
    if (board) board.classList.remove('mrail-dim');
    clearTimeout(this._litT);
    this._litT = setTimeout(() => this.p.rootEl.querySelectorAll('section.sec.mrail-tgt').forEach((x) => x.classList.remove('mrail-tgt')), 900);
  }

  // ── The page's glide ───────────────────────────────────────────────
  // Read fresh each frame, so a room that resizes while the page moves is
  // still landed on exactly.
  targetY() {
    if (this.targetTop) return 0;
    const el = this.targetEl; if (!el || !el.isConnected) return this.pos;
    let cover = 0;
    this.sc.querySelectorAll('[data-region]').forEach((r) => { const c = getComputedStyle(r); if (c.position === 'sticky' && r.offsetHeight) cover = Math.max(cover, r.offsetHeight + (parseFloat(c.top) || 0)); });
    // The room's title lines up with the thumb (house change, 29 Oct 2026:
    // "the card isn't where my thumb is, it's staying at the top of the
    // window"), held a little in from the top and bottom of the window so the
    // room stays readable when the thumb is near an edge.
    const scTop = this.sc.getBoundingClientRect().top;
    let anchor = cover + 12;
    if (this.thumbY != null) anchor = Math.max(cover + 12, Math.min(this.sc.clientHeight - 160, this.thumbY - scTop - HEAD));
    const y = el.getBoundingClientRect().top - scTop + this.sc.scrollTop - anchor;
    return Math.max(0, Math.min(this.sc.scrollHeight - this.sc.clientHeight, y));
  }

  spring() {
    if (this._raf) return;
    this.pos = this.sc.scrollTop; this.vel = this.vel || 0;
    let last = performance.now();
    const reduce = this.p.engine && this.p.engine.reduce && this.p.engine.reduce();
    const step = (now) => {
      // Real time, in small steps: a dropped frame never slows the glide down.
      let dt = Math.min(0.12, (now - last) / 1000); last = now;
      const t = this.targetY();
      if (reduce) { this.pos = t; this.vel = 0; }
      else {
        const c = 2 * ZETA * Math.sqrt(K);
        while (dt > 0) { const h = Math.min(0.008, dt); dt -= h; this.vel += (K * (t - this.pos) - c * this.vel) * h; this.pos += this.vel * h; }
      }
      if (this.p.engine) this.p.engine.sc = null;
      this.sc.scrollTop = this.pos;
      if (Math.abs(t - this.pos) < 0.5 && Math.abs(this.vel) < 5) { this.sc.scrollTop = this.pos = t; this.vel = 0; this._raf = null; if (!this.isOpen) this.thumbY = null; return; }
      this._raf = requestAnimationFrame(step);
    };
    this._raf = requestAnimationFrame(step);
  }
}
