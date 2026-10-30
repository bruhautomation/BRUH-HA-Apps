// The room rail: a slim strip of notches down the right edge of a touch
// screen, one vertical notch per room, grouped by floor, that takes the page
// room to room under the finger.
//
// The owner, over a session on a phone (latest wins): keep "the scroll rail
// look like we had before with the vertical rectangles", "go back to the
// swipe left to open and then just scrolling and releasing normally. Keep
// the highlighting mechanism", and "make my thumb and the card line up".
// So it is one gesture:
//
//   * a vertical swipe on it is a scroll: the rail is `touch-action: pan-y`,
//     and more than PASS_PX of vertical movement before a pull lets the
//     browser have the gesture (it scrolls the page as anywhere else);
//   * a pull to the LEFT follows the finger (the rail widens with it), with
//     a ratchet tick at a third and two thirds of OPEN_PX and a heavy tap
//     when it opens. Open, the rail is the same notches, a little wider and
//     STILL (nothing leans, pops or scales), with the floor names beside it,
//     placed once when it opened;
//   * without lifting, up or down goes room to room (a selection tick per
//     room, a medium tap on a new floor). The room is ringed and lit in its
//     own colour on the page, the others dim, and the page glides so that
//     room's title sits level with the finger;
//   * lifting lands on that room and closes the rail (a light tap): the
//     others come back at once and the ring fades after FADE_MS. Nothing
//     stays open.
//
// The rooms and their order come from the engine's model (the dashboard's
// order), never from re-reading where the sections are while their layout
// springs move: a notch or a floor name that moved under the finger was the
// jumping the owner saw. Resting on the rail and a short pull say what to
// do, as vertical words inside the rail (rule 13: text, never a title=).

export const OPEN_PX = 14;
export const PASS_PX = 8;
export const REST_MS = 220;
export const HINT_MS = 2200;
export const FADE_MS = 900;
const CLOSED_W = 28;
const OPEN_W = 44;
const FLOOR_GAP = 14;
const EDGE = 10;
const MAX_SLOT = 34;
// How far from the finger a tip starts.
const FINGER = 26;
// The glide: a critically damped spring on the real frame time, split into
// small steps, so a dropped frame is a longer step, not slow motion.
const K = 230;
const C = 2 * Math.sqrt(K);
const SUB = 0.008;
const DT_CAP = 0.12;
// Where a room's title may meet the finger: never closer than this to the
// top or the bottom of the window, so it stays readable at the edges.
const TOP_ROOM = 12;
const BOTTOM_ROOM = 160;

const REST_WORDS = 'Pull left to open the rooms';
const PULL_WORDS = 'Keep pulling left';
const HINT_WORDS = 'A little further left, then slide up or down to a room';

const VIBRATE = { selection: 4, light: 8, medium: 14, heavy: 22 };

// A tap of the phone, the way Home Assistant's own frontend asks for one
// (its companion apps listen for `haptic` on the window); a browser on its
// own gets a short vibration where it has one.
export function haptic(kind) {
  try { window.dispatchEvent(new CustomEvent('haptic', { detail: kind, bubbles: false })); } catch (e) { /* no window events */ }
  const inApp = !!(window.externalApp || (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.externalBus));
  if (!inApp && navigator.vibrate) { try { navigator.vibrate(VIBRATE[kind] || 8); } catch (e) { /* not allowed */ } }
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class Rail {
  // host: the panel. It gives the engine (its model and scroller), the
  // colour and floor name of a room, and counts the jumps (`railJumps`).
  constructor(el, host) {
    this.el = el;
    this.host = host;
    this.g = null; // the gesture in progress
    this.mode = ''; // '' | rest | pull | open | hint
    this.tipY = 0;
    this.pct = 0;
    this.room = '';
    this.lay = null; // the notches, laid out from the model
    this.glide = null;
    el.innerHTML = '<div class="srpanel"><div class="srnotches"></div></div><div class="srfloors"></div><div class="srtip"></div>';
    this.panelEl = el.querySelector('.srpanel');
    this.notchEl = el.querySelector('.srnotches');
    this.floorEl = el.querySelector('.srfloors');
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

  reduce() { return this.host.engine ? this.host.engine.reduce() : false; }

  // The rooms in the dashboard's order, from the engine's model, without
  // the bands that are not rooms and the rooms that are not drawn.
  rooms() {
    const E = this.host.engine;
    const secs = (E && E.model && E.model.sections) || [];
    const root = this.host.shadowRoot;
    const els = {};
    root.querySelectorAll('[data-board] section[data-sec]').forEach((s) => { els[s.getAttribute('data-sec')] = s; });
    return secs.filter((s) => s.id && !String(s.id).startsWith('__')).map((s) => ({ id: s.id, floor: String(s.floorId == null ? '' : s.floorId), el: els[s.id] }))
      .filter((r) => r.el && r.el.offsetParent !== null && r.el.offsetHeight >= 24);
  }

  // Where each notch goes: the rooms evenly down the rail, a gap between
  // floors, the whole stack centred. Worked out from the model alone.
  layout() {
    const list = this.rooms();
    const H = this.el.clientHeight;
    const floors = [];
    list.forEach((r) => { if (!floors.length || floors[floors.length - 1].id !== r.floor) floors.push({ id: r.floor, rooms: [] }); floors[floors.length - 1].rooms.push(r); });
    const gaps = Math.max(0, floors.length - 1) * FLOOR_GAP;
    const slot = list.length ? Math.max(8, Math.min(MAX_SLOT, (H - 2 * EDGE - gaps) / list.length)) : 0;
    const total = slot * list.length + gaps;
    let y = Math.max(EDGE, (H - total) / 2);
    const notches = [];
    const heads = [];
    floors.forEach((F, fi) => {
      if (fi) y += FLOOR_GAP;
      heads.push({ id: F.id, y: y + slot / 2 });
      F.rooms.forEach((r) => { notches.push({ ...r, y: y + slot / 2, h: Math.max(5, Math.min(22, slot * 0.62)) }); y += slot; });
    });
    return { notches, heads, H, many: floors.length > 1, key: notches.map((n) => n.id + '@' + n.floor).join(',') + '|' + H };
  }

  // The notches. Closed, the room at the top of the screen is lit; open,
  // the room the finger is on. While open nothing is laid out again.
  paint() {
    const E = this.host.engine;
    const sc = E && E.scroller();
    if (!sc || !this.el.isConnected || !this.el.offsetHeight) return;
    if (this.mode !== 'open') {
      const lay = this.layout();
      if (!this.lay || this.lay.key !== lay.key) {
        this.lay = lay;
        this.notchEl.innerHTML = lay.notches.map((n) => `<i data-r="${esc(n.id)}" style="top:${Math.round(n.y - n.h / 2)}px;height:${Math.round(n.h)}px;background:${this.host.railColor(n.id)}"></i>`).join('');
      }
    }
    let cur = this.room;
    if (this.mode !== 'open') {
      const top = sc.getBoundingClientRect().top + 24;
      cur = '';
      (this.lay ? this.lay.notches : []).forEach((n) => { if (n.el.getBoundingClientRect().top <= top) cur = n.id; });
      if (!cur && this.lay && this.lay.notches.length) cur = this.lay.notches[0].id;
    }
    this.notchEl.querySelectorAll('i').forEach((i) => i.classList.toggle('on', i.getAttribute('data-r') === cur));
  }

  // The floor names beside the open rail, level with each floor's first
  // notch, placed once.
  placeFloors() {
    const lay = this.lay;
    if (!lay || !lay.many) { this.floorEl.innerHTML = ''; return; }
    this.floorEl.innerHTML = lay.heads.map((h) => { const t = this.host.railFloor(h.id); return t ? `<span data-floor-label style="top:${Math.round(h.y - 10)}px">${esc(t)}</span>` : ''; }).join('');
  }

  down(e) {
    if (e.button != null && e.button !== 0) return;
    e.stopPropagation(); // not a tap on the page behind it: the rail is its own
    clearTimeout(this.hintT);
    const r = this.el.getBoundingClientRect();
    this.g = { x0: e.clientX, y0: e.clientY, top: r.top, id: e.pointerId, moved: false, ticks: 0, y: e.clientY };
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
    g.y = e.clientY;
    if (this.mode === 'open') { this.scrub(e.clientY); return; }
    // Up or down before any pull: a scroll, and the browser's to make.
    if (this.mode !== 'pull' && dy > PASS_PX && dy > left) { this.pass(); return; }
    if (left > 2 || dy > 2) g.moved = true;
    if (left > 2) {
      this.mode = 'pull';
      this.pct = Math.min(1, left / OPEN_PX);
      this.tipY = e.clientY - g.top;
      // The ratchet: a tick at a third and at two thirds of the way.
      const ticks = Math.floor(this.pct * 3);
      if (ticks > g.ticks && ticks < 3) { g.ticks = ticks; haptic('selection'); }
      if (left >= OPEN_PX) { this.open(e); return; }
      this.draw();
    }
  }

  open(e) {
    this.mode = 'open';
    this.pct = 1;
    this.target = null;
    haptic('heavy');
    try { this.el.setPointerCapture(e.pointerId); } catch (err) { /* already captured */ }
    this.lay = this.layout();
    this.notchEl.innerHTML = this.lay.notches.map((n) => `<i data-r="${esc(n.id)}" style="top:${Math.round(n.y - n.h / 2)}px;height:${Math.round(n.h)}px;background:${this.host.railColor(n.id)}"></i>`).join('');
    this.placeFloors();
    this.host.rootEl.classList.add('railing');
    this.draw();
    this.scrub(e.clientY);
  }

  up() {
    const g = this.g; this.g = null;
    clearTimeout(this.restT);
    if (!g) return;
    if (this.mode === 'open') { this.land(); return; }
    // A tap, a rest or a pull that stopped short: say how it opens.
    this.mode = 'hint';
    this.pct = 0;
    this.draw();
    clearTimeout(this.hintT);
    this.hintT = setTimeout(() => { if (this.mode === 'hint') { this.mode = ''; this.draw(); } }, HINT_MS);
  }

  // The finger lifted on a room: the rail closes, the other rooms come back
  // at once, and the room's ring fades a moment later.
  land() {
    const id = this.room;
    this.mode = '';
    this.pct = 0;
    this.room = '';
    haptic('light');
    this.host.rootEl.classList.remove('railing');
    this.floorEl.innerHTML = '';
    this.draw();
    this.paint();
    clearTimeout(this.fadeT);
    const el = this.target && this.target.el;
    this.fadeT = setTimeout(() => { if (el && this.room !== id) el.classList.remove('railon'); }, FADE_MS);
  }

  // The browser took the gesture (a scroll): the rail lets go and says
  // nothing.
  pass() {
    if (this.mode === 'open') { this.g = null; this.land(); return; }
    this.g = null;
    clearTimeout(this.restT);
    if (this.mode !== 'hint') { this.mode = ''; this.pct = 0; this.draw(); }
  }

  // The notch nearest the finger is the room.
  scrub(clientY) {
    const lay = this.lay; if (!lay || !lay.notches.length) return;
    const y = clientY - this.el.getBoundingClientRect().top;
    let best = lay.notches[0], d = Infinity;
    lay.notches.forEach((n) => { const dd = Math.abs(n.y - y); if (dd < d) { d = dd; best = n; } });
    if (best.id !== this.room) {
      const prev = this.target;
      haptic(prev && prev.floor !== best.floor ? 'medium' : 'selection');
      this.room = best.id;
      this.host.railJumps = (this.host.railJumps || 0) + 1;
      clearTimeout(this.fadeT);
      this.host.shadowRoot.querySelectorAll('section.railon').forEach((s) => { if (s !== best.el) s.classList.remove('railon'); });
      best.el.style.setProperty('--rc', this.host.railColor(best.id));
      best.el.classList.add('railon');
      this.target = best;
      this.notchEl.querySelectorAll('i').forEach((i) => i.classList.toggle('on', i.getAttribute('data-r') === best.id));
    }
    this.go();
  }

  // Where the page must be for the room's title to sit level with the
  // finger (held off the window's edges). Read again every frame, so it
  // follows the finger within a room too.
  aim() {
    const E = this.host.engine; const sc = E.scroller();
    const t = this.target; if (!sc || !t || !t.el.isConnected) return null;
    const sr = sc.getBoundingClientRect();
    const er = t.el.getBoundingClientRect();
    const h2 = t.el.querySelector('.sechead h2') || t.el.querySelector('.sechead');
    const hr = h2 ? h2.getBoundingClientRect() : null;
    const title = hr && hr.height ? hr.top + hr.height / 2 - er.top : 31;
    const finger = (this.g ? this.g.y : this.lastY || sr.top + sc.clientHeight / 2) - sr.top;
    if (this.g) this.lastY = this.g.y;
    const top = Math.max(TOP_ROOM, Math.min(sc.clientHeight - BOTTOM_ROOM, finger - title));
    const max = Math.max(0, sc.scrollHeight - sc.clientHeight);
    return Math.max(0, Math.min(max, sc.scrollTop + (er.top - sr.top) - top));
  }

  go() {
    const E = this.host.engine;
    E.sc = null; // the engine's own scroll spring would pull the other way
    if (this.reduce()) { const t = this.aim(); if (t != null) E.scrollTo(t); return; }
    if (!this.glide) this.glide = { p: E.scrollY(), v: 0, last: performance.now(), until: 0 };
    if (this.glideF) return;
    const step = (now) => {
      this.glideF = 0;
      const s = this.glide; if (!s) return;
      E.sc = null;
      const t = this.aim();
      if (t == null) { this.glide = null; return; }
      // The page may have been moved under the glide (a layout, a scroll).
      if (Math.abs(E.scrollY() - s.p) > 2) s.p = E.scrollY();
      let dt = Math.min(DT_CAP, Math.max(0.001, (now - s.last) / 1000)); s.last = now;
      while (dt > 0) { const h = Math.min(SUB, dt); s.v += (-K * (s.p - t) - C * s.v) * h; s.p += s.v * h; dt -= h; }
      E.scrollTo(s.p);
      if (this.mode !== 'open' && Math.abs(s.p - t) < 0.5 && Math.abs(s.v) < 1) { E.scrollTo(t); this.glide = null; return; }
      if (this.mode !== 'open' && !s.until) s.until = now + 1500;
      if (s.until && now > s.until) { this.glide = null; return; }
      this.glideF = requestAnimationFrame(step);
    };
    this.glide.last = performance.now();
    this.glideF = requestAnimationFrame(step);
  }

  // The rail's width (it follows a pull), and the words inside it.
  draw() {
    const el = this.el;
    el.classList.toggle('open', this.mode === 'open');
    el.classList.toggle('engaged', !!this.mode);
    const w = this.mode === 'open' ? OPEN_W : this.mode === 'pull' ? CLOSED_W + (OPEN_W - CLOSED_W) * this.pct : CLOSED_W;
    this.panelEl.style.width = Math.round(w) + 'px';
    const words = this.mode === 'rest' ? [REST_WORDS]
      : this.mode === 'pull' ? [PULL_WORDS]
        : this.mode === 'hint' ? [REST_WORDS, HINT_WORDS] : [];
    const html = words.map((w2, i) => `<span class="${i ? 'srsub' : ''}">${esc(w2)}</span>`).join('');
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
  }
}
