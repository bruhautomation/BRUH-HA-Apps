// Morph's layout engine — ported from the MORPH UI prototype
// (docs/design/morph-ui.html), which is the reference for behaviour and
// motion. The rules it enforces are the design's §1 and §5:
//
//   * Every section, group label and tile is a SPRING (x, y, w, h;
//     K = 150, ζ = 0.82) driven by one requestAnimationFrame loop. Layout
//     only ever sets targets, so a change mid-flight bends instead of jerking.
//   * Columns: N = max(2, floor((W + G) / (205 + G))), G = 12 below 700px.
//   * Sections: masonry per floor, preferred width ±1, highest spot wins with
//     a penalty for blank space, then a stretch pass. Cached per column count
//     and order. When something opens, sections only move DOWN.
//   * Inside a section: things of one kind are gathered (first-appearance
//     order), a new kind starts a new row, same-size things spread evenly
//     (4 in a 3-wide room → 2 + 2), the last item grows up to its `grow`.
//   * Opening: the opened tile keeps its row and column and grows right (or
//     left at the row's end) and down; what it covers moves to the nearest
//     free place. Make room first, then grow: a growing section waits 130ms
//     and a growing tile 170ms; a tile travelling more than 30px dips to 12%
//     opacity on the way.
//   * A floor heading rides on its floor's highest section every frame.
//
// The DOM contract (built by morph-panel.js):
//   [data-board]                      the positioned container
//   [data-floor=<index>] > [data-flin] a floor heading
//   [data-sec=<id>] > [data-sec-head=<id>]
//   [data-gbg=<key>] [data-glab=<key>] group background and label
//   [data-tile=<id>] > … [data-tc=<id>] > [data-face=<id>]

const K = 150;
const C = 2 * 0.82 * Math.sqrt(K);

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
  }

  reduce() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches || !!this.forceReduce; } catch (e) { return !!this.forceReduce; }
  }

  invalidate() { this.base = null; }

  layout(snap, quiet) {
    const r = this.root, M = this.model;
    if (!r || !M) return;
    const boardEl = r.querySelector('[data-board]');
    if (!boardEl) return;
    const W = boardEl.clientWidth;
    if (!W) return;
    const G = W < 700 ? 12 : 16, TG = 6, PAD = 10, GP = 0, GLH = 24, GGAP = 14;
    const N = Math.max(2, Math.floor((W + G) / (205 + G)));
    const u = (W - G * (N - 1)) / N;
    const px = (w) => w * u + (w - 1) * G;
    const cwOf = (w) => (px(w) - 2 * PAD - 2 * GP - TG * (w - 1)) / w;
    const grab = (a) => { const m = {}; r.querySelectorAll('[' + a + ']').forEach((el) => { m[el.getAttribute(a)] = el; }); return m; };
    const GB = grab('data-gbg'), TE = grab('data-tile'), SE = grab('data-sec'), HE = grab('data-sec-head'), TC = grab('data-tc'), FE = grab('data-face'), GL = grab('data-glab');
    const openId = this.openId;
    const fadingId = this.fadingId;
    let openSec = null, openIt = null;
    M.sections.forEach((s) => s.groups.forEach((g) => g.items.forEach((it) => { if (it.id === openId) { openSec = s; openIt = it; } })));
    const secOf = {};
    M.sections.forEach((s) => { secOf[s.id] = s; });

    const span = (it, w) => (it.full ? w : Math.min(w, it.span));
    const rowsOf = (g, w) => {
      const rows = []; let row = [], x = 0, runRows = 0;
      const push = (last) => {
        if (row.length) {
          const lone = row.length === 1 && runRows === 0 && last && (row[0].it.hk === 's' || /^x:/.test(row[0].it.hk || 'x:'));
          let left = w - x;
          for (let i = row.length - 1; i >= 0 && left > 0; i--) {
            const p = row[i];
            const add = Math.min(left, Math.max(0, Math.min(w, p.it.full || lone ? w : (p.it.grow || p.cs)) - p.cs));
            p.cs += add; left -= add;
          }
          let cx = 0; row.forEach((p) => { p.c = cx; cx += p.cs; });
          rows.push(row); runRows++;
        }
        row = []; x = 0;
      };
      const kinds = []; const by = {};
      g.items.forEach((it) => { const k = it.hk || 'x:' + it.id; if (!by[k]) { by[k] = []; kinds.push(k); } by[k].push(it); });
      kinds.forEach((k) => {
        runRows = 0; const its = by[k]; const sp = span(its[0], w);
        let per = Infinity;
        if (its.every((it) => span(it, w) === sp)) { const fit = Math.max(1, Math.floor(w / sp)); const rn = Math.ceil(its.length / fit); per = Math.ceil(its.length / rn); }
        its.forEach((it) => { const cs = span(it, w); if (x + cs > w || row.length >= per) push(false); row.push({ it: it, c: x, cs: cs }); x += cs; });
        push(true);
      });
      return rows;
    };
    const widthOf = (cs, w) => cs * cwOf(w) + (cs - 1) * TG;
    const openSpan = (g, w) => {
      let at = null;
      rowsOf(g, w).forEach((row) => row.forEach((p) => { if (p.it.id === openId) at = p; }));
      if (!at) return null;
      let need = Math.min(w, openIt.dir === 'down' ? Math.max(w - at.c, Math.min(w, 2)) : Math.max(at.cs, openIt.want || 2, 2));
      // Keep the column whenever there is room to grow right at all (two
      // columns or more); only a card the row ends against keeps its RIGHT
      // edge and grows left instead.
      const room = w - at.c;
      if (at.c + need > w && room >= Math.max(2, at.cs)) need = room;
      const c = at.c + need <= w ? at.c : Math.max(0, at.c + at.cs - need);
      return { c: c, cs: need };
    };

    const okey = M.sections.map((x) => x.id + ':' + x.w + ':' + x.floor + ':' + x.groups.map((g) => g.items.length).join('.')).join(',');
    const baseOK = this.base && this.base.N === N && this.base.okey === okey;
    const secW = (s) => (baseOK ? this.base.pos[s.id].w : Math.min(N, s.w));
    const hOf = {}, fH = {}, headH = {};
    const setW = (id, tw) => {
      const tc = TC[id]; if (!tc) return;
      const closing = !!(fadingId && fadingId === id && id !== openId);
      const v = closing && this.tcw[id] ? this.tcw[id] : Math.round(tw);
      if (this.tcw[id] !== v || tc.style.width !== v + 'px') tc.style.width = v + 'px';
      this.tcw[id] = v;
    };
    const measure = (wmap) => {
      M.sections.forEach((s) => {
        const w = wmap[s.id];
        s.groups.forEach((g) => {
          const os = s === openSec ? openSpan(g, w) : null;
          rowsOf(g, w).forEach((row) => row.forEach((p) => setW(p.it.id, widthOf(os && p.it.id === openId ? os.cs : p.cs, w))));
        });
      });
      M.sections.forEach((s) => {
        headH[s.id] = HE[s.id] ? HE[s.id].offsetHeight : 62;
        s.groups.forEach((g) => g.items.forEach((it) => {
          fH[it.id] = FE[it.id] ? FE[it.id].offsetHeight : 56;
          hOf[it.id] = it.id === openId && TC[it.id] ? TC[it.id].offsetHeight : fH[it.id];
        }));
      });
    };
    let wmap = {};
    M.sections.forEach((s) => { wmap[s.id] = secW(s); });
    measure(wmap);

    const flow = (s, w) => {
      let y = headH[s.id]; const tiles = {}, labs = {}, boxes = {}; const cw = cwOf(w); let blank = 0;
      s.groups.forEach((g) => {
        const top = y; y += GP;
        if (g.label) { labs[g.key] = { x: PAD + GP + 6, y: y + 2, w: px(w) - 2 * PAD - 2 * GP - 12, h: 20 }; y += GLH; }
        const pos = []; let ry = 0;
        rowsOf(g, w).forEach((row) => {
          let rh = 0, used = 0;
          row.forEach((p) => { used += p.cs; const h = fH[p.it.id] || 56; pos.push({ id: p.it.id, c: p.c, y: ry, cs: p.cs, base: span(p.it, w), h: h }); rh = Math.max(rh, h); });
          blank += (w - used) * cw * rh; ry += rh + TG;
        });
        const os = s === openSec ? openSpan(g, w) : null;
        let placed = pos;
        if (os) {
          const a = pos.find((p) => p.id === openId);
          placed = [{ id: openId, c: os.c, y: a.y, cs: os.cs, h: hOf[openId] }];
          const fits = (c, yy, cs, h) => c >= 0 && c + cs <= w && placed.every((q) => c + cs <= q.c || q.c + q.cs <= c || yy + h + TG <= q.y + 0.5 || q.y + q.h + TG <= yy + 0.5);
          pos.forEach((p) => {
            if (p.id === openId) return;
            if (fits(p.c, p.y, p.cs, p.h)) { placed.push(p); return; }
            const cs = p.base;
            const ys = [p.y].concat(placed.map((q) => q.y + q.h + TG)).filter((v) => v >= p.y - 0.5).sort((m, n) => m - n);
            let at = null;
            for (let i = 0; i < ys.length && !at; i++) {
              let best = -1, bd = 1e9;
              for (let c = 0; c + cs <= w; c++) { if (fits(c, ys[i], cs, p.h)) { if (c < bd) { bd = c; best = c; } } }
              if (best >= 0) at = { c: best, y: ys[i] };
            }
            if (!at) at = { c: 0, y: placed.reduce((m, q) => Math.max(m, q.y + q.h + TG), 0) };
            placed.push({ id: p.id, c: at.c, y: at.y, cs: cs, h: p.h });
          });
        }
        placed.forEach((p) => { tiles[p.id] = { x: PAD + GP + p.c * (cw + TG), y: y + p.y, w: widthOf(p.cs, w), h: p.id === openId ? hOf[openId] : p.h }; });
        y += placed.reduce((m, q) => Math.max(m, q.y + q.h), 0) + GP;
        boxes[g.key] = { x: PAD, y: top, w: px(w) - 2 * PAD, h: y - top };
        y += GGAP;
      });
      return { w: w, h: Math.ceil(y - GGAP + PAD), tiles: tiles, labs: labs, boxes: boxes, blank: blank };
    };

    if (!baseOK) {
      const pl = [];
      M.sections.forEach((s) => {
        const pref = Math.min(N, s.w); let best = null;
        for (let w = Math.max(Math.min(2, N), pref - 1); w <= Math.min(N, pref + 1); w++) {
          const fw = flow(s, w); const h = fw.h;
          for (let c = 0; c + w <= N; c++) {
            let y = 0;
            pl.forEach((p) => { if (p.f === s.floor && !(c + w <= p.c || p.c + p.w <= c)) y = Math.max(y, p.y + p.h + G); });
            const sc = y + Math.abs(w - pref) * 40 + fw.blank / u * 0.6 + c * 0.01;
            if (!best || sc < best.sc) best = { c: c, y: y, w: w, h: h, sc: sc };
          }
        }
        pl.push({ id: s.id, f: s.floor, c: best.c, y: best.y, w: best.w, h: best.h });
      });
      pl.forEach((p) => {
        for (let g = 0; g < N; g++) {
          if (p.w >= N) break;
          const f0 = flow(secOf[p.id], p.w), f1 = flow(secOf[p.id], p.w + 1); const nh = f1.h; const hh = Math.max(p.h, nh);
          if (nh > p.h - 8 && f1.blank - f0.blank > u * p.h * 0.4) break;
          const free = (c) => pl.every((q) => q === p || q.f !== p.f || c + p.w + 1 <= q.c || q.c + q.w <= c || p.y + hh + G <= q.y + 0.5 || q.y + q.h + G <= p.y + 0.5);
          if (p.c + p.w < N && free(p.c)) { p.w++; p.h = nh; } else if (p.c > 0 && free(p.c - 1)) { p.c--; p.w++; p.h = nh; } else break;
        }
      });
      const pos = {}; pl.forEach((p) => { pos[p.id] = { c: p.c, w: p.w, y: p.y }; });
      this.base = { N: N, pos: pos, okey: okey };
      const w2 = {}; let diff = false;
      M.sections.forEach((s) => { w2[s.id] = secW(s); if (w2[s.id] !== wmap[s.id]) diff = true; });
      if (diff) { wmap = w2; measure(wmap); }
    }

    const order = M.sections.slice().sort((a, b) => {
      const A = this.base.pos[a.id], B = this.base.pos[b.id];
      return (a.floor - b.floor) || (A.y - B.y) || ((b === openSec) - (a === openSec)) || (A.c - B.c);
    });
    const FH = W < 700 ? 76 : 72, FGAP = W < 700 ? 22 : 34;
    let fpos = {}; const FLH = {};
    r.querySelectorAll('[data-floor]').forEach((el) => { const inn = el.querySelector('[data-flin]'); FLH[el.getAttribute('data-floor')] = inn ? inn.offsetHeight + (W < 700 ? 14 : 16) + 6 : 0; });
    const fhOf = (f) => Math.max(FH, FLH[String(f)] || 0);
    const place = (oc, ow, hts) => {
      const pl = []; const fp = {}; let cursor = 0, curF = null, top = 0;
      const yAt = (c, w) => { let y = top; pl.forEach((p) => { if (p.f === curF && !(c + w <= p.c || p.c + p.w <= c)) y = Math.max(y, p.y + p.h + G); }); return y; };
      order.forEach((s) => {
        if (s.floor !== curF) { curF = s.floor; const fy = cursor + (pl.length ? FGAP : 0); fp[curF] = { x: 0, y: fy, w: W, h: fhOf(curF) }; top = fy + fhOf(curF); }
        const isO = s === openSec && oc != null;
        const w = isO ? ow : (s === openSec ? Math.min(N, this.base.pos[s.id].w) : wmap[s.id]);
        const c = isO ? oc : Math.max(0, Math.min(this.base.pos[s.id].c, N - w));
        const y = yAt(c, w);
        const h = hts(s, w); pl.push({ id: s.id, f: s.floor, c: c, y: y, w: w, h: h }); cursor = Math.max(cursor, y + h);
      });
      fpos = fp;
      return pl;
    };
    const flows = {};
    M.sections.forEach((s) => { flows[s.id] = flow(s, wmap[s.id]); });
    let pl;
    if (openSec) {
      const bpos = this.base.pos[openSec.id]; const bw = Math.min(N, bpos.w); const top = wmap[openSec.id];
      const hts = (s, w) => (s === openSec ? flow(s, w).h : flows[s.id].h);
      const ref = {}; place(null, null, hts).forEach((p) => { ref[p.id] = p; });
      let best = null;
      for (let w = bw; w <= top; w++) {
        for (let c = Math.max(0, bpos.c - (w - bw)); c <= Math.min(bpos.c, N - w); c++) {
          const cand = place(c, w, hts); let cost = (top - w) * 150;
          cand.forEach((p) => { if (p.id !== openSec.id) { const r0 = ref[p.id]; cost += Math.abs(p.y - r0.y) + Math.abs(p.c - r0.c) * (u + G); } });
          if (!best || cost < best.cost - 0.5) best = { cost: cost, c: c, w: w };
        }
      }
      if (best && best.w !== wmap[openSec.id]) { wmap[openSec.id] = best.w; measure(wmap); M.sections.forEach((s) => { flows[s.id] = flow(s, wmap[s.id]); }); }
      pl = place(best ? best.c : null, best ? best.w : null, (s) => flows[s.id].h);
    } else pl = place(null, null, (s) => flows[s.id].h);
    const H = pl.reduce((a, p) => Math.max(a, p.y + p.h), 0);
    const key = [openId, this.openMode, N, Math.round(W)].join('|'); const changed = key !== this.key; this.key = key;

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
      Object.keys(f.boxes).forEach((k) => { const el = GB[k]; if (el) this.spring('b:' + k, el, f.boxes[k], snap, dl(X + f.boxes[k].x, Y + f.boxes[k].y)); });
      Object.keys(f.labs).forEach((k) => { const el = GL[k]; if (el) this.spring('g:' + k, el, f.labs[k], snap, dl(X + f.labs[k].x, Y + f.labs[k].y)); });
      Object.keys(f.tiles).forEach((id) => {
        const t = f.tiles[id]; const te = TE[id]; if (!te) return;
        te.style.zIndex = id === openId ? '2' : '1';
        const to = this.it['t:' + id]; let td = 0;
        if (to && !quiet) { if (t.w > to.t.w + 1 || t.h > to.t.h + 1) td = 170; else if (t.y < to.t.y - 1 || (t.x < to.t.x - 1 && Math.abs(t.y - to.t.y) < 1)) td = 170; }
        if (to && !quiet && !snap && id !== openId && (Math.abs(t.y - to.t.y) > 30 || Math.abs(t.x - to.t.x) > 30) && te.animate && !this.reduce()) {
          try { te.animate([{ opacity: 1 }, { opacity: 0.12, offset: 0.35 }, { opacity: 1 }], { duration: 620, easing: 'ease-in-out' }); } catch (er) { /* WAAPI absent */ }
        }
        this.spring('t:' + id, te, t, snap, td);
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

    if (!quiet && !snap && changed && openSec) {
      const p = pl.find((q) => q.id === openSec.id); const t = flows[openSec.id].tiles[openId];
      if (p && t) {
        const sc = this.scroller();
        const vh = sc ? sc.clientHeight : (window.innerHeight || 900);
        const top = this.offsetTop(boardEl) + p.y + t.y; const bot = top + t.h; const sy = this.scrollY();
        let target = null;
        if (top < sy + 70) target = top - 90; else if (bot > sy + vh - 30) target = Math.min(top - 90, bot - vh + 40);
        if (target != null) this.sc = { p: sy, v: 0, t: Math.max(0, target) };
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
    this.sc = { p: this.scrollY(), v: 0, t: Math.max(0, this.offsetTop(el) - (pad || 140)) };
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
  overlaps() {
    const secs = Object.keys(this.it).filter((k) => k.startsWith('s:')).map((k) => this.it[k]);
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
