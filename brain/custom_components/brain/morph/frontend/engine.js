// Morph's layout engine — ported from the MORPH UI prototype
// (docs/design/morph-ui.html), which is the reference for behaviour and
// motion. The rules it enforces are the design's §1 and §5:
//
//   * Every section, group label and tile is a SPRING (x, y, w, h;
//     K = 150, ζ = 0.82) driven by one requestAnimationFrame loop. Layout
//     only ever sets targets, so a change mid-flight bends instead of jerking.
//   * A column is one compact tile (a light, switch, fan, blind),
//     N = floor((W + G) / (188 + G)); a bigger card spans whole columns (its
//     `span`, 1-4). Rows then stretch to fill their section, up to twice a
//     tile's own size, tiles of one kind sharing one width (Oct 2026). A name
//     that does not fit ends in an ellipsis.
//   * Sections are as wide as their content needs (its widest card, its
//     title and scene words on one line, and no more columns than add a row of tiles), up
//     to the section's `width` (Narrow 1, Medium 3, Wide 4, Widest 6
//     columns). They pack as masonry per floor in their order: each takes the
//     highest free spot at its own width; afterwards a section takes any
//     empty columns beside it that no other section uses (fill to the edge).
//     When something opens, its section may widen to give it room, and other
//     sections only move DOWN.
//   * Wide sections (4+ columns) flow their small groups side by side in
//     bands (2-3 columns each) instead of stacking them; scenes, big cards and
//     the group holding an opened tile stay full width (house change).
//   * Light groups alone on their row share it with the small group after
//     them (Comfort): that group stacks beside them and the light groups grow
//     as tall as it (household, Oct 2026).
//   * Inside a section: things of one kind are gathered (first-appearance
//     order), a new kind starts a new row, same-size things spread evenly
//     (4 in a 3-wide room → 2 + 2), the last item grows up to its `grow`.
//   * Opening: the opened tile keeps its row and column and grows right (or
//     left at the row's end) and down; what it covers moves to the nearest
//     free place. Make room first, then grow: a growing section waits 130ms
//     and a growing tile 170ms. Nothing fades or flashes on the way: tiles
//     only glide.
//   * A floor heading rides on its floor's highest section every frame. A
//     floor whose heading is off (`floorHead[f] === 0`, the Now band and a
//     one-floor dashboard) reserves nothing.
//   * A tile MOVED into another section (lifted into Now, sent home) keeps
//     where it is on screen: `moveTile` converts its spring to the new
//     section's frame, so it travels instead of jumping (vision §8: "a card
//     that teleports cannot be followed"). Nothing fades on the way.
//
// The DOM contract (built by morph-panel.js):
//   [data-board]                      the positioned container
//   [data-floor=<index>] > [data-flin] a floor heading
//   [data-sec=<id>] > [data-sec-head=<id>]
//   [data-gbg=<key>] [data-glab=<key>] group background and label
//   [data-tile=<id>] > … [data-tc=<id>] > [data-face=<id>]

// The layout springs are Morph's own (K = 150, ζ = 0.82); a change
// mid-flight bends from its current velocity instead of restarting.
const K = 150;
const C = 2 * 0.82 * Math.sqrt(K);
// How far a row of tiles may stretch to fill its section (x its own size).
const STRETCH = 2;
// How big is too big (household, Oct 2026): a compact tile's content (icon,
// name, value) is ~190px, so past 260px it is only empty space (on a wide
// screen it is exactly one column anyway); bigger cards fill their row, and
// the page itself stops at 1480px.
const TILE_MAX_PX = 260;
const ROOM_MAX = 4; // the widest a room of controls gets, in columns

export class Engine {
  constructor(root) {
    this.root = root;
    this.it = {};
    this.raf = 0;
    this.key = '';
    this.base = null;
    this.sc = null;
    this.tcw = {};
    this.originId = null;
    this.drag = null;
    this.floors = {};
    this.model = { sections: [] };
    this.openId = null;
    this.openMode = '';
    this.fadingId = null;
    this.onSettle = null;
    this.audit = null;
    this.floorHead = {};
    this.moves = {};
    this.lastLayoutKey = '';
    this.compensate = false;
    // Measuring is the expensive part of a layout (every face's height is a
    // forced reflow), and most state changes in the house change nothing on
    // the page. A layout re-measures only when the board's own markup changed
    // since the last one (or something asked for it); otherwise it re-uses
    // the heights it has. The engine's own writes (positions, widths) are
    // not changes.
    this._dirty = true;
    this._lastMeasure = 0;
    this._mo = null;
    // The first touch, scroll or key on the page: after it, sections never
    // move sideways by themselves (rule 9).
    this._touched = false;
    if (root && root.addEventListener) {
      const touch = () => { this._touched = true; this._lastTouch = performance.now(); };
      ['pointerdown', 'wheel', 'keydown'].forEach((ev) => root.addEventListener(ev, touch, { capture: true, passive: true }));
      // A picture that finishes loading changes its card's height without
      // changing any markup.
      root.addEventListener('load', () => { this._dirty = true; }, true);
    }
  }

  // Engine-owned elements whose inline style the engine writes every frame.
  static ownStyle(el) {
    return !!(el && el.hasAttribute && (el.hasAttribute('data-tile') || el.hasAttribute('data-sec') || el.hasAttribute('data-tc') || el.hasAttribute('data-board') || el.hasAttribute('data-gbg') || el.hasAttribute('data-glab') || el.hasAttribute('data-floor') || el.hasAttribute('data-flin')));
  }

  // A tile is about to be re-parented from section `from` to `to`: remember
  // where it is on the board, so layout() can start its spring there.
  moveTile(id, from) {
    const t = this.it['t:' + id]; const s = this.it['s:' + from];
    if (!t || !s) return;
    this.moves[id] = { ax: s.x + t.x, ay: s.y + t.y };
    this._dirty = true;
  }

  // Tiles change height without their markup changing (an image arriving, a
  // late custom card, a font): watch their faces and lay out again.
  watchSize(el) {
    if (!el || typeof ResizeObserver === 'undefined') return;
    this.sizeWatch([el]);
  }

  // Sizes that change with no markup change (a picture loading, a custom
  // card drawing inside its own shadow root, fonts) are seen by a resize
  // observer on every face, which asks for one more layout.
  sizeWatch(els) {
    if (!this._ro) {
      this._seen = new Set();
      this._ro = new ResizeObserver(() => {
        this._dirty = true;
        cancelAnimationFrame(this._roRaf);
        this._roRaf = requestAnimationFrame(() => this.layout(false, true));
      });
    }
    let fresh = false;
    els.forEach((el) => { if (el && !this._seen.has(el)) { this._seen.add(el); this._ro.observe(el); fresh = true; } });
    this._seen.forEach((el) => { if (!el.isConnected) { this._ro.unobserve(el); this._seen.delete(el); } });
    return fresh;
  }

  watch(boardEl) {
    if (this._mo && this._moEl === boardEl) return;
    if (this._mo) this._mo.disconnect();
    this._moEl = boardEl;
    this._mo = new MutationObserver((recs) => this.note(recs));
    this._mo.observe(boardEl, { childList: true, subtree: true, characterData: true, attributes: true });
    this._dirty = true;
  }

  note(recs) {
    if (this._dirty) return;
    for (const r of recs) {
      if (r.type === 'attributes' && (r.attributeName === 'style' || r.attributeName === 'data-tall') && Engine.ownStyle(r.target)) continue;
      this._dirty = true; return;
    }
  }

  // Something outside the markup changed what things measure (fonts, a
  // custom card that drew late): the next layout measures again.
  dirty() { this._dirty = true; }

  reduce() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches || !!this.forceReduce; } catch (e) { return !!this.forceReduce; }
  }

  invalidate() { this.base = null; this._dirty = true; }

  // The panel describes sizes in half-columns of the old grid (a section's
  // width x2, a card's span x2, a compact tile 1). The board's columns are
  // now one compact tile each: convert once per model.
  grid() {
    const src = this.model;
    if (this._gridOf === src && this._grid) return this._grid;
    const U = (hc) => Math.max(1, Math.ceil((hc || 2) / 2));
    const MAXW = { 1: 1, 2: 3, 3: 4, 4: 6 };
    const conv = (it) => (it.compact
      ? { ...it, span: 1, grow: 1, want: it.want >= 999 ? 999 : U(it.want) }
      : { ...it, span: U(it.span), grow: U(it.grow || it.span), want: it.want >= 999 ? 999 : U(it.want) });
    this._grid = { sections: src.sections.map((s) => ({ ...s, w: MAXW[U(s.w)] || U(s.w), groups: s.groups.map((g) => ({ ...g, items: g.items.map(conv) })) })) };
    this._gridOf = src;
    return this._grid;
  }

  layout(snap, quiet) {
    const r = this.root, M = this.grid();
    if (!r || !M) return;
    const boardEl = r.querySelector('[data-board]');
    if (!boardEl) return;
    this.watch(boardEl);
    if (this._mo) this.note(this._mo.takeRecords());
    const W = boardEl.clientWidth;
    if (!W) return;
    const G = W < 700 ? 12 : 16, TG = 6, PAD = 10, GP = 0, GLH = 24, GGAP = 14;
    // A phone gets two half-columns (one section column): sections and big
    // cards take both, so names and values have room to breathe; the page
    // lengthens, and cards fold (house change). The grid is twice as fine as
    // before (house change): sections and big cards span pairs of these
    // columns; compact tiles take one.
    const N = W < 480 ? 2 : Math.max(2, Math.floor((W + G) / (188 + G)));
    // A phone or a narrow window: every section takes the whole width.
    const narrow = N <= 3;
    const u = (W - G * (N - 1)) / N;
    const px = (w) => w * u + (w - 1) * G;
    const cwOf = (w) => (px(w) - 2 * PAD - 2 * GP - TG * (w - 1)) / w;
    // offsetHeight rounds DOWN, so a tile 20.3px tall lost its bottom
    // outline; the layout box is rounded up instead.
    // Heights round UP: offsetHeight rounds a fractional face (a chart's
    // 20.3px header line) down, and the tile's overflow then shaves off
    // the card's 1px bottom outline (house change). offsetHeight stays the
    // floor, so a tile scaled while held never measures short.
    const hgt = (el) => Math.max(el.offsetHeight, Math.ceil(el.getBoundingClientRect().height - 0.01));
    const grab = (a) => { const m = {}; r.querySelectorAll('[' + a + ']').forEach((el) => { m[el.getAttribute(a)] = el; }); return m; };
    const GB = grab('data-gbg'), TE = grab('data-tile'), SE = grab('data-sec'), HE = grab('data-sec-head'), TC = grab('data-tc'), FE = grab('data-face'), DE = grab('data-detail'), GL = grab('data-glab');
    const openId = this.openId;
    const fadingId = this.fadingId;
    let openSec = null, openIt = null;
    M.sections.forEach((s) => s.groups.forEach((g) => g.items.forEach((it) => { if (it.id === openId) { openSec = s; openIt = it; } })));
    const secOf = {};
    M.sections.forEach((s) => { secOf[s.id] = s; });

    // Every tile is its own span: a compact tile one column, a card its span,
    // a full card the section's width. Nothing is stretched (house change).
    const span = (it, w) => (it.full ? w : Math.min(w, it.span));
    const rowsOf = (g, w) => {
      const rows = []; let row = [], x = 0, runRows = 0;
      const push = (last) => {
        if (row.length) {
          // A tile takes the room it needs, not the whole row (house change):
          // leftover columns are shared out only until each tile reaches its
          // natural size (its `grow`, at most half again its span); whatever
          // is still left stays empty at the row's end. Several tiles in a
          // row still even out; a lone switch no longer spans the section.
          // A tile keeps its own size (house change): the section is sized to
          // its tiles, so there is nothing to stretch into.
          const used = Math.min(w, x);
          row.used = used;
          let cx = 0; row.forEach((p) => { p.c = cx; cx += p.cs; p.free = 0; });
          row[row.length - 1].free = Math.max(0, Math.floor(w - cx + 1e-6));
          rows.push(row); runRows++;
        }
        row = []; x = 0;
      };
      const kinds = []; const by = {};
      g.items.forEach((it) => { const k = it.hk || 'x:' + it.id; if (!by[k]) { by[k] = []; kinds.push(k); } by[k].push(it); });
      kinds.forEach((k) => {
        runRows = 0; const its = by[k]; const sp = span(its[0], w);
        let per = Infinity; const uni = its.every((it) => span(it, w) === sp);
        if (uni) { const fit = Math.max(1, Math.floor(w / sp)); const rn = Math.ceil(its.length / fit); per = Math.ceil(its.length / rn); }
        const start = rows.length;
        its.forEach((it) => { const cs = span(it, w); if (x + cs > w || row.length >= per) push(false); row.push({ it: it, c: x, cs: cs }); x += cs; });
        push(true);
        // Rows fill their section (household rule: "rows of tiles stretch to
        // fill their section"; Oct 2026). Tiles of one kind share one width,
        // so a short last row stays a clean grid; nothing grows past twice
        // its own size, so a lone switch never becomes a banner.
        const mine = rows.slice(start);
        const k0 = uni ? w / (Math.min(per, its.length) * sp) : 0;
        mine.forEach((rw) => {
          // Cards share their row to the section's edge (no 2x limit: the page
          // cap bounds them); controls stay one column (below).
          let kx = rw.some((p) => p.it.compact) ? Math.min(STRETCH, uni ? k0 : w / Math.max(1, rw.used)) : (uni ? k0 : w / Math.max(1, rw.used));
          // ...and never past what its content can use (household, Oct 2026):
          // a compact tile TILE_MAX_PX.
          // (Bigger cards fill their row: the page's own 1480px cap is what keeps
          // them from getting too wide, and a capped card only left a gap.)
          rw.forEach((p) => { if (!(p.it.compact || p.cs <= 1)) return; const now = widthOf(p.cs, w); if (now > 0) kx = Math.min(kx, Math.max(1, TILE_MAX_PX / now)); });
          // A compact tile is exactly one column, in every room, on every screen:
          // one tile size across the page reads as a calm grid (household, Oct 2026).
          if (rw.some((p) => p.it.compact)) kx = 1; // phone too: one rule
          if (!(kx > 1.001)) return;
          let cx = 0; rw.forEach((p) => { p.cs *= kx; p.c = cx; cx += p.cs; p.free = 0; });
          rw.used = Math.min(w, cx); rw[rw.length - 1].free = Math.max(0, w - cx);
        });
      });
      return rows;
    };
    const widthOf = (cs, w) => cs * cwOf(w) + (cs - 1) * TG;
    // Every control tile on a wide screen is one exact width: a tile's width in
    // a 2-column room, centered in its column slot, so rooms of any width show
    // identical tiles and only the gaps absorb the difference (household, Oct 2026).
    const CT = cwOf(2);
    const compactId = {}; M.sections.forEach((sx) => sx.groups.forEach((g) => g.items.forEach((it) => { if (it.compact) compactId[it.id] = true; })));
    const tileW = (id, cs, w) => (!narrow && compactId[id] && Math.abs(cs - 1) < 1e-6 && id !== openId ? Math.min(CT, cwOf(w)) : null);
    const openSpan = (g, w) => {
      let at = null;
      rowsOf(g, w).forEach((row) => row.forEach((p) => { if (p.it.id === openId) at = p; }));
      if (!at) return null;
      const slide = this.openMode === 'slide';
      // A slide sets a level; it opens nothing (rule 2). A small tile may take
      // the empty columns at the end of its own row while the finger is down,
      // so the level has room, but it never changes column or row and never
      // pushes a neighbour (rules 8 and 9).
      if (slide) return { c: at.c, cs: Math.max(at.cs, Math.min(Math.min(w, 2), at.free != null ? at.cs + at.free : at.cs)) };
      let need = Math.min(w, openIt.dir === 'down' ? Math.max(w - at.c, Math.min(w, 2)) : Math.max(at.cs, openIt.want || 2, 2));
      // Keep the column whenever there is room to grow right at all (two
      // columns or more); only a card the row ends against keeps its RIGHT
      // edge and grows left instead.
      const room = w - at.c;
      if (!slide && at.c + need > w && room >= Math.max(2, at.cs)) need = room;
      const c = at.c + need <= w ? at.c : Math.max(0, at.c + at.cs - need);
      return { c: c, cs: need };
    };

    // Bands (house change): a run of small groups in a wide section sits side
    // by side, so the section reads as a free-flowing board rather than one
    // column of rows. Depends only on structure and width, so measure() and
    // flow() always agree.
    // A room's light groups standing alone on their row, followed by a small
    // group of controls (Comfort: fans and blinds), share that row: the
    // follower stacks in the free columns and the light groups grow as tall as
    // it, so the room is a row shorter (household, Oct 2026: "it's OK if the
    // group light gets taller so the climate section can move up").
    const hasOpen = (s, g) => s === openSec && this.openMode !== 'slide' && g.items.some((it) => it.id === openId);
    const tallPair = (s, g, nx, w) => {
      if (!nx || hasOpen(s, g) || hasOpen(s, nx)) return false;
      const n = g.items.length, m = nx.items.length;
      if (!n || !m || n >= w) return false;
      if (!g.items.every((it) => it.soft && it.compact && !it.full && it.hk === 's')) return false;
      if (!nx.items.every((it) => it.compact && !it.full)) return false;
      return Math.ceil(m / (w - n)) <= 3;
    };
    const planOf = (s, w) => {
      const out = []; let run = [];
      const mspan = (g) => g.items.reduce((m, it) => Math.max(m, span(it, w)), 1);
      const small = (g) => g.items.length > 0 && g.items.length <= 2 && g.items.every((it) => !it.full) &&
        !(s === openSec && this.openMode !== 'slide' && g.items.some((it) => it.id === openId)) && mspan(g) * 2 <= w + 1;
      const flush = () => {
        // as many bands as the run's widest card allows, at most 3
        // A band must still hold two of its tiles per row (house change): on a
        // phone the groups stack and their tiles pair up instead of each group
        // getting a one-tile-wide column.
        const mw = run.reduce((m, g) => Math.max(m, mspan(g) * Math.min(2, g.items.length)), 1);
        let nb = Math.min(3, run.length, Math.floor(w / mw));
        // ...and those two tiles must be wide enough to read (house change): on
        // a narrow screen a 2-column band gives each tile ~95px, which cuts off
        // names and buttons, so fewer bands (or stacked groups) win.
        // (A column is a whole tile now, so every band is readable.)
        if (nb < 2) run.forEach((g) => out.push({ g: g, c0: 0, bw: w }));
        else {
          const wd = [], st = [], load = [];
          let x = 0;
          for (let i = 0; i < nb; i++) { wd.push(Math.floor(w / nb) + (i < w % nb ? 1 : 0)); st.push(x); x += wd[i]; load.push(0); }
          const parts = [];
          run.forEach((g) => {
            let b = 0; load.forEach((l, i) => { if (l < load[b]) b = i; });
            load[b] += Math.ceil(g.items.reduce((a, it) => a + Math.min(span(it, w), wd[b]), 0) / wd[b]) + (g.label ? 0.4 : 0);
            parts.push({ g: g, c0: st[b], bw: wd[b] });
          });
          out.push({ run: parts });
        }
        run = [];
      };
      for (let i = 0; i < s.groups.length; i++) {
        const g = s.groups[i], nx = s.groups[i + 1];
        if (tallPair(s, g, nx, w)) { flush(); const n = g.items.length; out.push({ run: [{ g: g, c0: 0, bw: n }, { g: nx, c0: n, bw: w - n }], tall: true }); i++; continue; }
        if (small(g)) run.push(g); else { flush(); out.push({ g: g, c0: 0, bw: w }); }
      }
      flush();
      return out;
    };
    const partsOf = (s, w) => { const a = []; planOf(s, w).forEach((e) => { if (e.run) e.run.forEach((p) => a.push(p)); else a.push(e); }); return a; };

    const okey = M.sections.map((x) => x.id + ':' + x.w + ':' + x.floor + ':' + x.groups.map((g) => g.items.map((it) => (it.span || 0) + (it.full ? 'f' : '') + (it.grow || 0) + (it.compact ? 'c' : '')).join('-')).join('.')).join(',');
    // The choreography (make room first, a travelling tile dipping out) is
    // for opening, closing and rearranging. A card whose content grew by
    // itself (a door's history unfolding, a chart arriving) or a state
    // change in the house moves things straight along, with no wait and no
    // dip, so nothing flashes while the page follows it (house change).
    // Nothing on the board changed size or shape since the last layout: the
    // springs already have these targets, so there is nothing to do. (A
    // re-measure still happens every 2 s, and always while the page settles.)
    if (this.sizeWatch([...Object.values(FE), ...Object.values(DE), ...Object.values(HE), ...Object.values(TC)])) this._dirty = true;
    const fkey = M.sections.filter((x) => x.folded).map((x) => x.id).join(',');
    const fullKey = [openId, this.openMode, Math.round(W), okey, fadingId || '', this.slideHeld ? 1 : 0, fkey].join('|');
    const tNow = performance.now();
    if (!snap && !this._dirty && !this.drag && !this.originId && fullKey === this._fullKey && this._born && tNow - this._born > 6000 && tNow - this._lastMeasure < 2000) return;
    this._fullKey = fullKey; this._dirty = false; this._lastMeasure = tNow;
    this._flowMemo = new Map();
    const shapeKey = [openId, this.openMode, N, Math.round(W), okey].join('|');
    if (!quiet) { if (shapeKey === this._shapeKey) quiet = true; this._shapeKey = shapeKey; }
    let baseOK = this.base && this.base.N === N && this.base.okey === okey;
    // Rooms that folded or unfolded by themselves re-pack the floor, but never
    // under somebody's hand: within a minute of a touch, sections keep their
    // columns and only move up or down.
    if (baseOK && this.base.fkey !== fkey && !openId && performance.now() - (this._lastTouch || -1e9) > 60000) baseOK = false;
    const secW = (s) => (baseOK ? this.base.pos[s.id].w : Math.min(N, s.w));
    const hOf = {}, fH = {}, headH = {}, headNat = {};
    // How wide a section's heading line is: its title, note and scene words
    // side by side (each of them never wraps by itself). Its chips (a door,
    // motion) may drop to a second line rather than widen the section.
    const natural = (he) => {
      let wd = 22 + 12; // the heading's own padding
      const line = he.querySelector('.secline');
      if (line) {
        const h2 = line.querySelector('h2'), meta = line.querySelector('.secmeta'), sc = line.querySelectorAll('.secscenes > *');
        if (h2) wd += h2.scrollWidth;
        if (meta && meta.textContent) wd += 12 + meta.scrollWidth;
        if (sc.length) { wd += 12 + 20; sc.forEach((b, i) => { wd += b.scrollWidth + (i ? 16 : 0); }); }
      }
      return wd;
    };
    const setW = (id, tw) => {
      const tc = TC[id]; if (!tc) return;
      const closing = !!(fadingId && fadingId === id && id !== openId);
      const v = closing && this.tcw[id] ? this.tcw[id] : Math.round(tw);
      if (this.tcw[id] !== v || tc.style.width !== v + 'px') tc.style.width = v + 'px';
      this.tcw[id] = v;
    };
    // A name that does not fit on one line first widens its tile to its
    // natural size (remembered for this screen width, so it never flips);
    // past that it ends in an ellipsis with the whole name in its title.
    // Strips stay one 56px row (household rule): no two-line strips.
    const fitNames = (rows) => {
      let grew = false;
      rows.forEach((ids) => ids.forEach((id) => {
        const f = FE[id]; if (!f) return;
        if (f.classList.contains('two')) f.classList.remove('two');
        // A name that does not fit ends in an ellipsis: tiles keep one size.
        if (id === openId) return;
      }));
      return grew;
    };
    const measure = (wmap) => {
      // A tile stretched beside its neighbours is measured at its own size.
      Object.values(TC).forEach((tc) => { if (tc.hasAttribute('data-tall')) { tc.removeAttribute('data-tall'); tc.style.height = ''; } });
      const rows = [];
      M.sections.forEach((s) => {
        const w = wmap[s.id];
        partsOf(s, w).forEach((pt) => {
          const g = pt.g, os = s === openSec ? openSpan(g, pt.bw) : null;
          rowsOf(g, pt.bw).forEach((row) => {
            row.forEach((p) => setW(p.it.id, tileW(p.it.id, p.cs, w) || widthOf(os && p.it.id === openId ? os.cs : p.cs, w)));
            const ids = row.map((p) => p.it.id).filter((id) => id !== openId);
            if (ids.length) rows.push(ids);
          });
        });
      });
      // A face stretched to its row's height last time is measured as it is on its own.
      Object.keys(FE).forEach((id) => { if (FE[id].style.getPropertyValue('--fh')) FE[id].style.removeProperty('--fh'); });
      if (openId) rows.push([openId]); // an open or widened tile is its own row
      if (fitNames(rows) && !wmap.__again) { wmap.__again = true; measure(wmap); delete wmap.__again; return; }
      this._flowMemo = new Map();
      M.sections.forEach((s) => {
        headH[s.id] = HE[s.id] ? hgt(HE[s.id]) : 62;
        headNat[s.id] = HE[s.id] ? natural(HE[s.id]) : 0;
        s.groups.forEach((g) => g.items.forEach((it) => {
          fH[it.id] = (FE[it.id] ? hgt(FE[it.id]) : 56) + (DE[it.id] ? hgt(DE[it.id]) : 0); // a detail card is part of the closed tile
          hOf[it.id] = it.id === openId && TC[it.id] ? hgt(TC[it.id]) : fH[it.id];
        }));
      });
    };
    let wmap = {};
    M.sections.forEach((s) => { wmap[s.id] = secW(s); });
    measure(wmap);
    // Placement is chosen from measured heights, and custom cards measure
    // short until they have drawn. Re-place once when the heights settle
    // (quantised, never while something is open) so the first guess does
    // not stick (house change).
    const hsig = () => M.sections.map((s) => s.groups.reduce((a, g) => a + g.items.reduce((b, it) => b + (fH[it.id] || 0), 0), 0)).map((v) => Math.round(v / 120)).join('.');
    // Only while the page is settling: later, a card growing (a camera opening,
    // a history unfolding) must never send sections to new columns or widths.
    if (!this._born) this._born = performance.now();
    if (baseOK && !openId && !this._touched && performance.now() - this._born < 6000 && this.base.hsig !== undefined && this.base.hsig !== hsig()) baseOK = false;

    // One layout asks for the same section at the same width many times (each
    // placement attempt, the grow pass): remember each answer until the
    // heights are measured again.
    const flow = (s, w) => {
      const mk = s.id + ':' + w;
      let hit = this._flowMemo.get(mk);
      if (!hit) { hit = flow0(s, w); this._flowMemo.set(mk, hit); }
      return hit;
    };
    const flow0 = (s, w) => {
      // A quiet room folded to its title line (Oct 2026): only the heading.
      if (s.folded) return { w: w, h: Math.ceil(headH[s.id] + 6), tiles: {}, labs: {}, boxes: {}, blank: 0 };
      let y = headH[s.id]; const tiles = {}, labs = {}, boxes = {}; const cw = cwOf(w); let blank = 0;
      const colX = (c) => PAD + GP + c * (cw + TG);
      const one = (pt, y0) => {
        const g = pt.g, bw = pt.bw, c0 = pt.c0;
        let py = y0; const top = py; py += GP;
        if (g.label) { labs[g.key] = { x: colX(c0) + 6, y: py + 2, w: bw * cw + (bw - 1) * TG - 2 * GP - 12, h: 20 }; py += GLH; }
        // Content-sized packing: a tile sits straight under whatever is
        // above it in ITS columns (a skyline), not under the tallest tile of
        // the row above, so a short tile never leaves a void beneath it.
        const pos = [];
        rowsOf(g, bw).forEach((row) => {
          let rh = 0;
          row.forEach((p) => {
            const h = fH[p.it.id] || 56; let yy = 0;
            pos.forEach((q) => { if (p.c < q.c + q.cs - 0.01 && q.c < p.c + p.cs - 0.01) yy = Math.max(yy, q.y + q.h + TG); });
            pos.push({ id: p.it.id, c: p.c, y: yy, cs: p.cs, base: p.cs, h: h }); rh = Math.max(rh, h);
          });
          blank += (bw - row.used) * cw * rh;
        });
        const os = s === openSec ? openSpan(g, bw) : null;
        let placed = pos;
        if (os) {
          const a = pos.find((p) => p.id === openId);
          placed = [{ id: openId, c: os.c, y: a.y, cs: os.cs, h: hOf[openId] }];
          const fits = (c, yy, cs, h) => c >= 0 && c + cs <= bw && placed.every((q) => c + cs <= q.c || q.c + q.cs <= c || yy + h + TG <= q.y + 0.5 || q.y + q.h + TG <= yy + 0.5);
          pos.forEach((p) => {
            if (p.id === openId) return;
            if (fits(p.c, p.y, p.cs, p.h)) { placed.push(p); return; }
            const cs = p.base;
            const ys = [p.y].concat(placed.map((q) => q.y + q.h + TG)).filter((v) => v >= p.y - 0.5).sort((m, n) => m - n);
            let at = null;
            for (let i = 0; i < ys.length && !at; i++) {
              let best = -1, bd = 1e9;
              // Stretched tiles sit on fractional columns: try the grid of
              // their own width and every placed tile's right edge.
              const cands = new Set([0]); for (let c = cs; c + cs <= bw + 1e-6; c += cs) cands.add(+c.toFixed(4)); placed.forEach((q) => cands.add(+(q.c + q.cs).toFixed(4)));
              [...cands].sort((m, n) => m - n).forEach((c) => { if (c + cs <= bw + 1e-6 && fits(c, ys[i], cs, p.h) && c < bd) { bd = c; best = c; } });
              if (best >= 0) at = { c: best, y: ys[i] };
            }
            if (!at) at = { c: 0, y: placed.reduce((m, q) => Math.max(m, q.y + q.h + TG), 0) };
            placed.push({ id: p.id, c: at.c, y: at.y, cs: cs, h: p.h });
          });
        }
        placed.forEach((p) => { const tw = tileW(p.id, p.cs, w); tiles[p.id] = { x: colX(c0 + p.c) + (tw ? (cw - tw) / 2 : 0), y: py + p.y, w: tw || widthOf(p.cs, w), h: p.id === openId ? hOf[openId] : p.h }; });
        py += placed.reduce((m, q) => Math.max(m, q.y + q.h), 0) + GP;
        boxes[g.key] = { x: PAD + c0 * (cw + TG), y: top, w: bw * cw + (bw - 1) * TG, h: py - top };
        return py;
      };
      planOf(s, w).forEach((e) => {
        if (e.run) {
          const by = {}; let end = y; e.run.forEach((pt) => { const k = pt.c0; const at = by[k] == null ? y : by[k] + GGAP; by[k] = one(pt, at); end = Math.max(end, by[k]); });
          // The light groups reach down to the bottom of the group beside them.
          if (e.tall) {
            const g = e.run[0].g, b = boxes[g.key];
            g.items.forEach((it) => { const t = tiles[it.id]; if (t && end - t.y > t.h + 0.5) { t.h = end - t.y; t.tall = true; } });
            if (b) b.h = Math.max(b.h, end - b.y);
          }
          y = end + GGAP;
        }
        else y = one(e, y) + GGAP;
      });
      return { w: w, h: Math.max(headH[s.id] || 0, Math.ceil(y - GGAP + PAD)), tiles: tiles, labs: labs, boxes: boxes, blank: blank };
    };

    if (!baseOK) {
      // Each section is as wide as its content needs, up to its own width:
      // at least its widest card and its title and scene words on one line, and no more
      // columns than still save a row (house change).
      // ONE WIDTH RULE (household, Oct 2026), replacing per-section widths,
      // spans and after-the-fact widening:
      //  * the page is N equal columns; one column is one tile;
      //  * a control (light, group, switch, fan, blind, lock, button, person)
      //    is exactly one column, always (its span is ignored);
      //  * a ROOM (a section of controls, perhaps with a 2-column control card
      //    such as the desk) is as wide as its widest group, at least 2 and at
      //    most ROOM_MAX columns; its scenes wrap under its title;
      //  * a PANEL (a section with a full-width card, a card of 3+ columns, or
      //    nothing but cards: charts, cameras, media, weather...) takes its
      //    YAML width as a share of six columns (1, 3, 4 or 6); its cards share
      //    their rows evenly to its edge;
      //  * brAIn's rows never decide a width;
      //  * nothing widens a section afterwards.
      const room = {};
      const fit = (s) => {
        if (narrow) return N;
        // brAIn's rows and Edit's add buttons take whatever width the section has;
        // they never decide it.
        const own = (it) => !/^(k:|kf:|td:|add@)/.test(it.id);
        const items = s.groups.flatMap((g) => g.items).filter(own);
        // A panel: a full-width card, a card of 3+ columns, or nothing but cards.
        // A panel is as wide as its own width says, as a share of a six-column
        // page (1 = one column, 2 = half, 3 = two thirds, 4 = full), so a card
        // with little in it is not stretched across half a wide screen
        // (household, Oct 2026: "cards fitting their contents in width").
        // ...but never narrower than its widest card showing right now, so a
        // card that appears in it (the oven in Now, while it runs) fits.
        if (items.length && (items.some((it) => it.full || (!it.compact && it.span >= 3)) || items.every((it) => !it.compact))) return s.w >= 6 ? N : Math.min(N, Math.max(1, Math.round(s.w * N / 6), ...items.map((it) => (it.compact ? 1 : it.span))));
        const cap = Math.min(N, ROOM_MAX);
        let w = 1;
        // The columns its rows actually use: tiles are spread evenly over as few
        // rows as fit (5 → 3 + 2), so a room is as wide as its longest row.
        s.groups.forEach((g) => {
          const n = g.items.filter(own).reduce((a, it) => a + (it.compact ? 1 : Math.min(cap, it.span)), 0);
          const rows = Math.max(1, Math.ceil(n / cap));
          w = Math.max(w, Math.ceil(n / rows), ...g.items.filter((it) => own(it) && !it.compact).map((it) => Math.min(cap, it.span)));
        });
        // At least 2 columns, so a room's title and scenes have room; the
        // scenes wrap under the title rather than widening the room further.
        w = Math.max(Math.min(2, cap), Math.min(cap, w));
        room[s.id] = true;
        return w;
      };
      // Packed per floor, in the sections' order: each takes the highest
      // free spot its width fits (the leftmost of equals), including a hole
      // a wider section left above itself.
      const pos = {};
      const fitW = {}; M.sections.forEach((s) => { fitW[s.id] = fit(s); });
      const pack = (list) => {
        const done = []; const out = {};
        list.forEach((s) => {
          const w = fitW[s.id]; const h = flow(s, w).h;
          const free = (c, y) => done.every((q) => c + w <= q.c || q.c + q.w <= c || y + h + G <= q.y + 0.5 || q.y + q.h + G <= y + 0.5);
          const ys = [0].concat(done.map((q) => q.y + q.h + G)).sort((a, b) => a - b);
          let at = null;
          for (let i = 0; i < ys.length && !at; i++) for (let c = 0; c + w <= N && !at; c++) if (free(c, ys[i])) at = { c: c, y: ys[i] };
          if (!at) at = { c: 0, y: done.reduce((m, q) => Math.max(m, q.y + q.h + G), 0) };
          done.push({ c: at.c, y: at.y, w: w, h: h });
          out[s.id] = { c: at.c, w: w, y: at.y };
        });
        return { out, H: done.reduce((m, q) => Math.max(m, q.y + q.h), 0) };
      };
      // ROOM ROWS (household, Oct 2026: "no rhyme or reason why some rooms
      // are bigger, some are smaller"). A floor made only of rooms reads like
      // lines of text instead of masonry: rooms keep their order, left to
      // right, in rows across the page; every room in a row is drawn as tall
      // as the row, so all of a row's rooms share one top and one bottom and
      // the next row starts on one line. Where the rows break is chosen for
      // the whole floor at once (least empty box and least empty page), and a
      // room is only given more columns when that saves it a row of tiles
      // (its Comfort group moving beside its lights), never just to fill
      // space (a room of tiles hugs its tiles).
      const rowIx = {}, rowMates = {};
      const rowsPack = (list) => {
        const hAt = (s, w) => flow(s, w).h;
        const sum = (a) => a.reduce((x, y) => x + y, 0);
        const rowFit = (seg, last) => {
          const ws = seg.map((s) => fitW[s.id]);
          const cost = () => {
            const hs = seg.map((s, k) => hAt(s, ws[k])); const H = Math.max(...hs); let c = 0;
            seg.forEach((s, k) => { if (!s.folded) c += (H - hs[k]) * ws[k]; });
            return c + (N - sum(ws)) * H * (last ? 0.15 : 0.5);
          };
          let cur = cost();
          for (;;) {
            let best = null;
            seg.forEach((s, k) => {
              if (s.folded) return;
              const h0 = hAt(s, ws[k]);
              for (let d = 1; sum(ws) + d <= N; d++) {
                if (hAt(s, ws[k] + d) >= h0 - 1) continue;
                ws[k] += d; const c = cost(); ws[k] -= d;
                if (!best || c < best.c) best = { k: k, d: d, c: c };
                break;
              }
            });
            if (!best || best.c >= cur - 1) break;
            ws[best.k] += best.d; cur = best.c;
          }
          return { ws: ws, c: cur };
        };
        const n = list.length; const dp = [{ c: 0 }];
        for (let j = 1; j <= n; j++) {
          dp[j] = null;
          for (let i = j - 1; i >= 0; i--) {
            const seg = list.slice(i, j);
            if (sum(seg.map((s) => fitW[s.id])) > N) break;
            const r = rowFit(seg, j === n); const c = dp[i].c + r.c;
            if (!dp[j] || c < dp[j].c) dp[j] = { c: c, i: i, ws: r.ws };
          }
        }
        const rows = []; for (let j = n; j > 0; j = dp[j].i) rows.unshift({ seg: list.slice(dp[j].i, j), ws: dp[j].ws });
        const out = {}; let y = 0;
        rows.forEach((r, ri) => {
          let c = 0, H = 0;
          r.seg.forEach((s, k) => { out[s.id] = { c: c, w: r.ws[k], y: y }; c += r.ws[k]; H = Math.max(H, hAt(s, r.ws[k])); rowIx[s.id] = ri; rowMates[s.id] = r.seg.map((q) => q.id); });
          y += H + G;
        });
        return { out, H: Math.max(0, y - G) };
      };
      const floorsOf = {}; M.sections.forEach((s) => { (floorsOf[s.floor] = floorsOf[s.floor] || []).push(s); });
      Object.keys(floorsOf).forEach((f) => {
        const list = floorsOf[f];
        if (!narrow && list.length > 1 && list.every((s) => room[s.id])) { Object.assign(pos, rowsPack(list).out); return; }
        // Sections keep dashboard.yaml's order: nothing on the page reorders
        // itself, not even to pack a floor shorter.
        Object.assign(pos, pack(list).out);
      });
      this.base = { N: N, pos: pos, okey: okey, fkey: fkey, rowIx: rowIx, rowMates: rowMates };
      const w2 = {}; let diff = false;
      M.sections.forEach((s) => { w2[s.id] = Math.min(N, pos[s.id].w); if (w2[s.id] !== wmap[s.id]) diff = true; });
      if (diff) { wmap = w2; measure(wmap); }
      this.base.hsig = hsig();
    }

    const order = M.sections.slice().sort((a, b) => {
      const A = this.base.pos[a.id], B = this.base.pos[b.id];
      return (a.floor - b.floor) || (A.y - B.y) || ((b === openSec) - (a === openSec)) || (A.c - B.c);
    });
    const FH = W < 700 ? 76 : 72, FGAP = W < 700 ? 22 : 34;
    let fpos = {}; const FLH = {};
    r.querySelectorAll('[data-floor]').forEach((el) => { const inn = el.querySelector('[data-flin]'); FLH[el.getAttribute('data-floor')] = inn ? hgt(inn) + (W < 700 ? 14 : 16) + 6 : 0; });
    // A floor drawn without a heading, or whose heading is off, takes no room (house change).
    const fhOf = (f) => (this.floorHead[String(f)] === 0 || !(String(f) in FLH) ? 0 : Math.max(FH, FLH[String(f)]));
    const stretch = {};
    const place = (oc, ow, hts) => {
      const pl = []; const fp = {}; let cursor = 0, curF = null, top = 0, rowEnd = [];
      const yAt = (c, w) => { let y = top; pl.forEach((p) => { if (p.f === curF && !(c + w <= p.c || p.c + p.w <= c)) y = Math.max(y, p.y + p.h + G); }); return y; };
      order.forEach((s) => {
        if (s.floor !== curF) { rowEnd = []; curF = s.floor; const fy = cursor + (pl.length ? FGAP : 0); fp[curF] = { x: 0, y: fy, w: W, h: fhOf(curF) }; top = fy + fhOf(curF); }
        const isO = s === openSec && oc != null;
        const w = isO ? ow : (s === openSec ? Math.min(N, this.base.pos[s.id].w) : wmap[s.id]);
        const c = isO ? oc : stretch[s.id] ? 0 : Math.max(0, Math.min(this.base.pos[s.id].c, N - w));
        const ri = (this.base.rowIx || {})[s.id];
        // A room row starts below the whole row before it (room rows, above).
        const y = ri == null ? yAt(c, w) : Math.max(yAt(c, w), ri > 0 && rowEnd[ri - 1] != null ? rowEnd[ri - 1] + G : top);
        let h = hts(s, w);
        // ...and every room in a row is as tall as the row, unless it is the
        // opened one or folded to its title (nothing stretches to an opened card).
        const mates = (this.base.rowMates || {})[s.id];
        // A section that is one custom card (the assistant's own card) keeps its own height: it draws no box, so stretching it only leaves a gap under it.
        const soloLv = !!(SE[s.id] && SE[s.id].classList.contains('solo-lv'));
        if (mates && s !== openSec && !s.folded && !soloLv) mates.forEach((id) => { const q = secOf[id]; if (q && q !== openSec && !q.folded) h = Math.max(h, hts(q, wmap[id])); });
        if (ri != null) rowEnd[ri] = Math.max(rowEnd[ri] == null ? 0 : rowEnd[ri], y + h);
        pl.push({ id: s.id, f: s.floor, c: c, y: y, w: w, h: h }); cursor = Math.max(cursor, y + h);
      });
      fpos = fp;
      return pl;
    };
    const flows = {};
    M.sections.forEach((s) => { flows[s.id] = flow(s, wmap[s.id]); });
    let pl;
    if (openSec) {
      const bpos = this.base.pos[openSec.id]; const bw = Math.min(N, bpos.w);
      // An opened card may widen its section to the room it wants (rule 9:
      // the neighbours make room first), never past the screen.
      const top = Math.min(N, Math.max(wmap[openSec.id], this.openMode === 'slide' ? 0 : Math.min(openIt.want >= 999 ? openSec.w : openIt.want, Math.max(openSec.w, 3))));
      const hts = (s, w) => (s === openSec ? flow(s, w).h : flows[s.id].h);
      const ref = {}; place(null, null, hts).forEach((p) => { ref[p.id] = p; });
      let best = null;
      for (let w = bw; w <= top; w++) {
        for (let c = Math.max(0, bpos.c - (w - bw)); c <= Math.min(bpos.c, N - w); c++) {
          const cand = place(c, w, hts); let cost = (top - w) * 5000; // room for the opened card comes first (rule 9)
          cand.forEach((p) => { if (p.id !== openSec.id) { const r0 = ref[p.id]; cost += Math.abs(p.y - r0.y) + Math.abs(p.c - r0.c) * (u + G); } });
          if (!best || cost < best.cost - 0.5) best = { cost: cost, c: c, w: w };
        }
      }
      if (best && best.w !== wmap[openSec.id]) { wmap[openSec.id] = best.w; measure(wmap); M.sections.forEach((s) => { flows[s.id] = flow(s, wmap[s.id]); }); }
      pl = place(best ? best.c : null, best ? best.w : null, (s) => flows[s.id].h);
    } else {
      pl = place(null, null, (s) => flows[s.id].h);
      // The widths chosen above were chosen from the heights the sections had THEN. Cards load, fonts arrive and a chart draws after that, and a section that was beside another when the choice was made can end up alone in its band with a dead strip at its side while the section below it spans the floor. A section with nothing beside it takes the whole floor, as it would have at the choice; stable, because a section the width of the floor can only have sections above and below it. Its place in the order does not change (it is alone in its band, so column 0 moves it past nothing).
      // A room in a floor of room rows is left as rowsPack sized it: there a room hugs its tiles and is given more columns only when that saves it a row (household rule), so a room alone on its row is not widened to fill space.
      const roomRow = this.base.rowIx || {};
      for (let pass = 0; pass < 3; pass++) {
        const alone = pl.filter((p) => p.w < N && roomRow[p.id] == null && pl.every((q) => q === p || q.f !== p.f || p.y + p.h + G <= q.y + 0.5 || q.y + q.h + G <= p.y + 0.5));
        if (!alone.length) break;
        // For this render only: the cached base layout is never written, so when the heights settle the sections go back beside each other.
        alone.forEach((p) => { wmap[p.id] = N; stretch[p.id] = 1; });
        measure(wmap);
        M.sections.forEach((s) => { flows[s.id] = flow(s, wmap[s.id]); });
        pl = place(null, null, (s) => flows[s.id].h);
      }
    }
    // A spring whose element has left the page is forgotten here, whether or
    // not it was moving: a resting one would otherwise keep its old place.
    Object.keys(this.it).forEach((k) => { if (k !== 'board' && !this.it[k].el.isConnected) delete this.it[k]; });
    const H = pl.reduce((a, p) => Math.max(a, p.y + p.h), 0);
    const key = [openId, this.openMode, N, Math.round(W)].join('|'); const changed = key !== this.key; this.key = key;

    // Scroll compensation (vision §4.4): a rearrangement the panel applied
    // at a quiet moment, with the page scrolled into the board, moves the
    // scroll by as much as the first section in view moves, so nothing the
    // eye is on moves. Only for a rearrangement (`compensate`, set by the
    // panel), never for an opening, which scrolls to what was opened.
    let comp = 0;
    if (this.compensate && !quiet && !snap && !openSec) {
      const view = this.scrollY() - this.offsetTop(boardEl);
      if (view > 40) {
        let best = null;
        pl.forEach((p) => { const so = this.it['s:' + p.id]; if (!so || !so.el.isConnected) return; if (so.t.y + so.t.h > view && (!best || so.t.y < best.oy)) best = { oy: so.t.y, ny: p.y }; });
        if (best) comp = best.ny - best.oy;
      }
    }
    if (!quiet) this.compensate = false;

    let ox = null, oy = 0;
    if (!quiet && this.originId && this.it['t:' + this.originId]) {
      const t = this.it['t:' + this.originId]; let sid = null;
      M.sections.forEach((s) => s.groups.forEach((g) => g.items.forEach((it) => { if (it.id === this.originId) sid = s.id; })));
      const so = this.it['s:' + sid]; if (so) { ox = so.x + t.x + t.w / 2; oy = so.y + t.y + t.h / 2; }
    }
    this.originId = null;
    const delay = (x, y) => (ox == null ? 0 : Math.min(140, Math.hypot(x - ox, y - oy) * 0.1));

    pl.forEach((p) => {
      const se = SE[p.id]; if (!se) return; const f = flows[p.id];
      const X = p.c * (u + G), Y = p.y;
      se.style.zIndex = this.drag && this.drag.id === p.id ? '5' : openSec && openSec.id === p.id ? '2' : '1';
      const so = this.it['s:' + p.id]; let sd = 0;
      if (so && !quiet) { if (px(p.w) > so.t.w + 1 || p.h > so.t.h + 1) sd = 130; else if (Y < so.t.y - 1) sd = 130; }
      this.spring('s:' + p.id, se, { x: X, y: Y, w: px(p.w), h: p.h }, snap, sd);
      const dl = (x, y) => (openSec && openSec.id === p.id ? delay(x, y) : 0);
      // A group's box and label travel with its tiles: the same "make room
      // first" wait a tile gets when it grows or moves up (house change).
      const follow = (key, t) => { const o = this.it[key]; return o && !quiet && (t.w > o.t.w + 1 || t.h > o.t.h + 1 || t.y < o.t.y - 1 || (t.x < o.t.x - 1 && Math.abs(t.y - o.t.y) < 1)) ? 60 : 0; };
      Object.keys(f.boxes).forEach((k) => { const el = GB[k]; if (el) this.spring('b:' + k, el, f.boxes[k], snap, Math.max(dl(X + f.boxes[k].x, Y + f.boxes[k].y), follow('b:' + k, f.boxes[k]))); });
      Object.keys(f.labs).forEach((k) => { const el = GL[k]; if (el) this.spring('g:' + k, el, f.labs[k], snap, Math.max(dl(X + f.labs[k].x, Y + f.labs[k].y), follow('g:' + k, f.labs[k]))); });
      Object.keys(f.tiles).forEach((id) => {
        const t = f.tiles[id]; const te = TE[id]; if (!te) return;
        if (t.tall && TC[id]) { TC[id].setAttribute('data-tall', ''); TC[id].style.height = Math.round(t.h) + 'px'; }
        te.style.zIndex = id === openId ? '2' : '1';
        // The row's height reaches the face, so a short neighbour's outline runs to the bottom of its tile rather than leaving a hole under it.
        if (FE[id] && id !== openId && fH[id] != null && t.h > fH[id] + 1) FE[id].style.setProperty('--fh', t.h + 'px');
        const to = this.it['t:' + id]; let td = 0;
        if (to && !quiet) { if (t.w > to.t.w + 1 || t.h > to.t.h + 1) td = 170; else if (t.y < to.t.y - 1 || (t.x < to.t.x - 1 && Math.abs(t.y - to.t.y) < 1)) td = 170; }
        this.spring('t:' + id, te, t, snap, td);
        // A tile that changed section starts from where it was on screen.
        const mv = this.moves[id]; const sp = this.it['s:' + p.id];
        if (mv && sp && !this.reduce()) {
          const o = this.it['t:' + id];
          o.x = mv.ax - sp.x; o.y = mv.ay - sp.y; o.live = true; o.at = performance.now() + 60; this.paint(o);
        }
        delete this.moves[id];
      });
    });
    pl.forEach((p) => { const f = flows[p.id]; Object.keys(f.tiles).forEach((id) => { if (id !== openId) setW(id, f.tiles[id].w); }); });
    this.floors = {};
    r.querySelectorAll('[data-floor]').forEach((el) => {
      const k = el.getAttribute('data-floor'); const f = fpos[k];
      if (f) { el.style.visibility = 'visible'; this.floors[k] = { el: el, h: f.h, w: W, ids: pl.filter((q) => String(q.f) === k).map((q) => q.id) }; } else el.style.visibility = 'hidden';
    });
    this.floorsPaint();
    this.spring('board', boardEl, { x: 0, y: 0, w: W, h: Math.ceil(H) }, snap, 0);
    this.lastPlacement = { pl: pl, flows: flows, u: u, G: G, W: W };
    // What this layout wrote is not a change to measure next time.
    if (this._mo) this._mo.takeRecords();

    if (Math.abs(comp) > 1) {
      const t = Math.max(0, this.scrollY() + comp);
      if (this.reduce()) this.scrollTo(t); else this.sc = { p: this.scrollY(), v: 0, t };
    }
    if (!quiet && !snap && changed && openSec && this.openMode !== 'slide') {
      const p = pl.find((q) => q.id === openSec.id); const t = flows[openSec.id].tiles[openId];
      if (p && t) {
        const sc = this.scroller();
        const vh = sc ? sc.clientHeight : (window.innerHeight || 900);
        const top = this.offsetTop(boardEl) + p.y + t.y; const bot = top + t.h; const sy = this.scrollY();
        let target = null;
        if (top < sy + 70) target = top - 90; else if (bot > sy + vh - 30) target = Math.min(top - 90, bot - vh + 40);
        if (target != null) { if (this.reduce()) this.scrollTo(Math.max(0, target)); else this.sc = { p: sy, v: 0, t: Math.max(0, target) }; }
      }
    }
    this.run();
  }

  // The panel scrolls inside HA's own layout, not the window.
  scroller() { return this.scrollEl || null; }
  scrollY() { const s = this.scroller(); return s ? s.scrollTop : window.scrollY; }
  scrollTo(y) { const s = this.scroller(); if (s) s.scrollTop = y; else window.scrollTo(0, y); }
  offsetTop(el) {
    const s = this.scroller();
    const r = el.getBoundingClientRect();
    if (s) return r.top - s.getBoundingClientRect().top + s.scrollTop;
    return r.top + window.scrollY;
  }

  scrollToEl(el, pad) {
    if (!el) return;
    const t = Math.max(0, this.offsetTop(el) - (pad || 140));
    if (this.reduce()) { this.scrollTo(t); return; }
    this.sc = { p: this.scrollY(), v: 0, t };
    this.run();
  }

  floorsPaint() {
    Object.keys(this.floors).forEach((k) => {
      const F = this.floors[k]; let m = Infinity;
      F.ids.forEach((id) => { const o = this.it['s:' + id]; if (o) m = Math.min(m, this.drag && this.drag.id === id ? o.t.y : o.y); });
      if (m === Infinity) return;
      F.el.style.transform = 'translate3d(0,' + (m - F.h).toFixed(2) + 'px,0)'; F.el.style.width = F.w + 'px'; F.el.style.height = F.h + 'px';
    });
  }

  spring(k, el, t, snap, delay) {
    let o = this.it[k];
    if (!o || o.el !== el) { o = this.it[k] = { el: el, x: t.x, y: t.y, w: t.w, h: t.h, vx: 0, vy: 0, vw: 0, vh: 0, t: t, at: 0, live: false, hOnly: k === 'board' }; snap = true; }
    const moved = Math.abs(o.t.x - t.x) + Math.abs(o.t.y - t.y) + Math.abs(o.t.w - t.w) + Math.abs(o.t.h - t.h) > 0.3;
    o.t = t;
    if (snap || this.reduce()) { o.x = t.x; o.y = t.y; o.w = t.w; o.h = t.h; o.vx = o.vy = o.vw = o.vh = 0; o.live = false; this.paint(o); return; }
    if (moved) { if (!o.live && delay) o.at = performance.now() + delay; o.live = true; }
  }

  paint(o) {
    const s = o.el.style;
    if (o.hOnly) { s.height = o.h.toFixed(1) + 'px'; return; }
    s.transform = 'translate3d(' + o.x.toFixed(2) + 'px,' + o.y.toFixed(2) + 'px,0)';
    s.width = o.w.toFixed(2) + 'px'; s.height = o.h.toFixed(2) + 'px';
  }

  run() {
    if (this.raf) return;
    let last = performance.now();
    const step = (now) => {
      const dt = Math.min(0.034, Math.max(0.001, (now - last) / 1000)); last = now; let busy = false;
      Object.keys(this.it).forEach((k) => {
        const o = this.it[k]; if (!o.live) return;
        if (!o.el.isConnected) { delete this.it[k]; return; }
        busy = true; if (o.at && now < o.at) return;
        if (this.drag && k === 's:' + this.drag.id) { o.x = this.drag.x; o.y = this.drag.y; o.vx = o.vy = 0; }
        let rest = true;
        ['x', 'y', 'w', 'h'].forEach((a) => {
          const va = 'v' + a; let p = o[a], v = o[va]; const tg = o.t[a];
          if (Math.abs(p - tg) < 0.15 && Math.abs(v) < 0.5) { o[a] = tg; o[va] = 0; return; }
          rest = false; const n = 3, h = dt / n;
          for (let i = 0; i < n; i++) { v += (-K * (p - tg) - C * v) * h; p += v * h; }
          o[a] = p; o[va] = v;
        });
        this.paint(o);
        if (rest) { o.live = false; o.at = 0; }
      });
      this.floorsPaint();
      if (this.sc && this.reduce()) { this.scrollTo(this.sc.t); this.sc = null; }
      if (this.sc) {
        const s = this.sc; const K2 = 110, C2 = 2 * Math.sqrt(K2); const n = 3, h = dt / n;
        for (let i = 0; i < n; i++) { s.v += (-K2 * (s.p - s.t) - C2 * s.v) * h; s.p += s.v * h; }
        this.scrollTo(s.p);
        if (Math.abs(s.p - s.t) < 0.5 && Math.abs(s.v) < 1) this.sc = null; else busy = true;
      }
      if (this.drag) busy = true;
      this.raf = busy ? requestAnimationFrame(step) : 0;
      if (!busy && this.onSettle) this.onSettle();
    };
    this.raf = requestAnimationFrame(step);
  }

  // The §5 acceptance test, run on the live page after things settle:
  // no two sections overlap, and no section overlaps a floor heading.
  // A failure is reported to the panel, which hands it to the devloop.
  //
  // Only sections that are in the model AND on the page are compared. A
  // spring outlives its element while it is at rest (run() drops only LIVE
  // springs whose element has gone), so leaving Edit left each "Add
  // section" ghost's spring behind where the ghost used to stand, and the
  // room that moved into that space was reported as overlapping nothing.
  overlaps() {
    const ids = new Set(((this.model && this.model.sections) || []).map((s) => 's:' + s.id));
    const secs = Object.keys(this.it).filter((k) => k.startsWith('s:') && ids.has(k) && this.it[k].el.isConnected).map((k) => this.it[k]);
    const out = [];
    for (let i = 0; i < secs.length; i++) {
      for (let j = i + 1; j < secs.length; j++) {
        const a = secs[i], b = secs[j];
        if (a.x + a.w - 1 > b.x && b.x + b.w - 1 > a.x && a.y + a.h - 1 > b.y && b.y + b.h - 1 > a.y) {
          out.push([a.el.getAttribute('data-sec'), b.el.getAttribute('data-sec')]);
        }
      }
    }
    return out;
  }
}
