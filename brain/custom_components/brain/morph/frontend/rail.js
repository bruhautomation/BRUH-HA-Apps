// The room rail: a narrow strip down the right edge of a touch screen that
// goes room to room under the finger.
//
// The owner: "before you scroll with the Morph scroll rail you should have
// to open it by very slightly dragging left first; add responsive tips
// that make it clear". A rail that took every touch on the right edge and
// jumped at once turned an ordinary scroll that began at the edge into a
// jump to some room. So the rail is opened, not touched:
//
//   * a vertical swipe on it is a scroll: the rail is `touch-action: pan-y`,
//     and more than PASS_PX of vertical movement before a pull lets the
//     browser have the gesture (it scrolls the page as anywhere else);
//   * a pull of OPEN_PX to the LEFT opens it (a medium haptic), and from
//     then on sliding up or down goes room to room until the finger lifts;
//   * the tips say what to do: resting on it (REST_MS) "Pull left to open
//     the rooms", while pulling "Keep pulling left" over a bar that fills,
//     and after a tap or a short pull the same words with "A little further
//     left, then slide up or down to a room" for HINT_MS.
//
// Design rule 1 (nothing floats over anything): the rail is a column of
// the page beside the content, inside the scroller, not over it, and every
// tip is drawn INSIDE the rail, as vertical words beside the finger: a tip
// that slid out over the tiles would be a floating label. Rule 13: the tip
// is text, never a title= tooltip. The leftward pull is an opening gesture,
// not a level change: §2's one grammar (slide sets a level) is about cards,
// and nothing in a card listens on the rail.

export const OPEN_PX = 10;
export const PASS_PX = 8;
export const REST_MS = 220;
export const HINT_MS = 2200;
// How far from the finger a tip starts.
const FINGER = 26;

const REST_WORDS = 'Pull left to open the rooms';
const PULL_WORDS = 'Keep pulling left';
const HINT_WORDS = 'A little further left, then slide up or down to a room';

// A medium tap of the phone, the way Home Assistant's own frontend asks
// for one (its companion apps listen for `haptic` on the window); a
// browser on its own gets a short vibration where it has one.
export function haptic(kind) {
  try { window.dispatchEvent(new CustomEvent('haptic', { detail: kind, bubbles: false })); } catch (e) { /* no window events */ }
  const inApp = !!(window.externalApp || (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.externalBus));
  if (!inApp && navigator.vibrate) { try { navigator.vibrate(kind === 'medium' ? 14 : 8); } catch (e) { /* not allowed */ } }
}

export class Rail {
  // host: the panel. It gives the scroller, the board's rooms, the colour
  // and title of a room, and counts the jumps (`railJumps`).
  constructor(el, host) {
    this.el = el;
    this.host = host;
    this.g = null; // the gesture in progress
    this.mode = ''; // '' | rest | pull | open | hint
    this.tipY = 0;
    this.pct = 0;
    this.room = '';
    el.innerHTML = '<div class="srline"></div><div class="srdots"></div><div class="srfill" data-rail-fill></div><div class="srtip"></div>';
    this.dotsEl = el.querySelector('.srdots');
    this.fillEl = el.querySelector('.srfill');
    this.tipEl = el.querySelector('.srtip');
    el.addEventListener('pointerdown', (e) => this.down(e));
    el.addEventListener('pointermove', (e) => this.move(e));
    el.addEventListener('pointerup', (e) => this.up(e));
    el.addEventListener('pointercancel', () => this.pass());
    el.addEventListener('lostpointercapture', () => { if (this.g) this.up(null); });
    // Once the pull is the rail's, the page must not scroll under it.
    el.addEventListener('touchmove', (e) => { if (this.mode === 'pull' || this.mode === 'open') e.preventDefault(); }, { passive: false });
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  rooms() {
    const sc = this.host.engine && this.host.engine.scroller();
    if (!sc) return [];
    const max = Math.max(1, sc.scrollHeight);
    return [...this.host.shadowRoot.querySelectorAll('[data-board] section[data-sec]')]
      .filter((s) => { const id = s.getAttribute('data-sec') || ''; return id && !id.startsWith('__') && s.offsetParent !== null; })
      .map((s) => { const top = this.host.engine.offsetTop(s); return { id: s.getAttribute('data-sec'), el: s, top, f: Math.min(1, top / max) }; })
      .sort((a, b) => a.top - b.top);
  }

  // The dots: one per room, where it sits on the page; the room at the
  // top of the screen is the larger one.
  paint() {
    const sc = this.host.engine && this.host.engine.scroller();
    if (!sc || !this.el.isConnected || !this.el.offsetHeight) return;
    const list = this.rooms();
    const at = sc.scrollTop + 24;
    let cur = '';
    list.forEach((r) => { if (r.top <= at) cur = r.id; });
    if (!cur && list.length) cur = list[0].id;
    const H = this.el.clientHeight;
    const html = list.map((r) => `<i data-r="${r.id}" class="${r.id === (this.mode === 'open' ? this.room : cur) ? 'on' : ''}" style="top:${Math.round(8 + r.f * (H - 16))}px;background:${this.host.railColor(r.id)}"></i>`).join('');
    if (this.dotsEl.__h !== html) { this.dotsEl.__h = html; this.dotsEl.innerHTML = html; }
  }

  down(e) {
    if (e.button != null && e.button !== 0) return;
    e.stopPropagation(); // not a tap on the page behind it: the rail is its own
    clearTimeout(this.hintT);
    const r = this.el.getBoundingClientRect();
    this.g = { x0: e.clientX, y0: e.clientY, top: r.top, id: e.pointerId, moved: false };
    this.tipY = e.clientY - r.top;
    this.mode = '';
    this.pct = 0;
    this.draw();
    clearTimeout(this.restT);
    this.restT = setTimeout(() => { if (this.g && !this.g.moved && !this.mode) { this.mode = 'rest'; this.draw(); } }, REST_MS);
  }

  move(e) {
    const g = this.g; if (!g || e.pointerId !== g.id) return;
    const left = g.x0 - e.clientX;
    const dy = Math.abs(e.clientY - g.y0);
    if (this.mode === 'open') { this.tipY = e.clientY - g.top; this.scrub(e.clientY - g.top); return; }
    // Up or down before any pull: a scroll, and the browser's to make.
    if (this.mode !== 'pull' && dy > PASS_PX && dy > left) { this.pass(); return; }
    if (left > 2 || dy > 2) g.moved = true;
    if (left > 2) {
      this.mode = 'pull';
      this.pct = Math.min(1, left / OPEN_PX);
      this.tipY = e.clientY - g.top;
      if (left >= OPEN_PX) {
        this.mode = 'open';
        haptic('medium');
        try { this.el.setPointerCapture(e.pointerId); } catch (err) { /* already captured */ }
        this.scrub(e.clientY - g.top);
        return;
      }
      this.draw();
    }
  }

  up() {
    const g = this.g; this.g = null;
    clearTimeout(this.restT);
    if (!g) return;
    if (this.mode === 'open') { this.mode = ''; this.room = ''; this.draw(); this.paint(); return; }
    // A tap, a rest or a pull that stopped short: say how it opens.
    this.mode = 'hint';
    this.draw();
    clearTimeout(this.hintT);
    this.hintT = setTimeout(() => { if (this.mode === 'hint') { this.mode = ''; this.draw(); } }, HINT_MS);
  }

  // The browser took the gesture (a scroll): the rail lets go and says
  // nothing.
  pass() {
    this.g = null;
    clearTimeout(this.restT);
    if (this.mode !== 'hint') { this.mode = ''; this.draw(); }
  }

  scrub(y) {
    const list = this.rooms(); if (!list.length) return;
    const H = this.el.clientHeight;
    let best = list[0], d = Infinity;
    list.forEach((r) => { const dd = Math.abs(8 + r.f * (H - 16) - y); if (dd < d) { d = dd; best = r; } });
    if (best.id !== this.room) {
      this.room = best.id;
      this.host.railJumps = (this.host.railJumps || 0) + 1;
      this.host.engine.sc = null; // a glide in progress would carry on past the room
      this.host.engine.scrollTo(Math.max(0, best.top - 12));
    }
    this.draw();
    this.paint();
  }

  // The tip and the bar, inside the rail, beside the finger.
  draw() {
    const el = this.el;
    el.classList.toggle('open', this.mode === 'open');
    el.classList.toggle('engaged', !!this.mode);
    const words = this.mode === 'rest' ? [REST_WORDS]
      : this.mode === 'pull' ? [PULL_WORDS]
        : this.mode === 'hint' ? [REST_WORDS, HINT_WORDS]
          : this.mode === 'open' ? [this.host.railTitle(this.room)] : [];
    const html = words.filter(Boolean).map((w, i) => `<span class="${i ? 'srsub' : ''}">${w.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))}</span>`).join('');
    if (this.tipEl.__h !== html) { this.tipEl.__h = html; this.tipEl.innerHTML = html; }
    this.tipEl.hidden = !html;
    const H = el.clientHeight;
    if (html) {
      const h = this.tipEl.offsetHeight;
      // Above the finger (a finger covers what is under it), or below it
      // where there is no room above.
      const above = this.tipY - FINGER - h;
      const top = above >= 6 ? above : this.tipY + FINGER;
      this.tipEl.style.top = Math.round(Math.max(6, Math.min(H - h - 6, top))) + 'px';
    }
    this.fillEl.hidden = this.mode !== 'pull';
    if (this.mode === 'pull') {
      this.fillEl.style.top = Math.round(Math.max(4, Math.min(H - 8, this.tipY - 2))) + 'px';
      this.fillEl.style.width = Math.max(2, Math.round(this.pct * (el.clientWidth - 4))) + 'px';
    }
  }
}
