'use client';

import { useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { Crop } from '@/lib/database.types';
import { CropAvatar } from '@/components/crop-glyph';
import { cropIconColor } from '@/components/crop-icon';

interface VarietySlice {
  id: number;
  name: string;
  totalLb: number;
  value: number;
  picks?: number;
}
interface ByCrop {
  crop: Crop;
  totalLb: number;
  value: number;
  picks?: number;
  /** The crop's picks split by variety — only the ones that carry a variety. */
  varieties?: VarietySlice[];
}
interface Ev {
  date: string;
  value: number;
  lb: number;
  cropId: number | null;
  varietyId?: number | null;
}

const fmtMoney = (n: number) => '$' + n.toFixed(2);
const fmtLb = (n: number) => `${Math.round(n * 10) / 10} lb`;

const OTHER_COLOR = 'rgb(148 163 184)'; // slate-400 — picks with no crop recorded
const MUTED_BAR = 'rgb(203 213 225)'; // slate-300 — a deselected crop's bar

/** `#rrggbb` → HSL parts, or null for anything else. */
function hexToHsl(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255,
    g = ((n >> 8) & 255) / 255,
    b = (n & 255) / 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    d = max - min;
  const l = (max + min) / 2;
  if (d === 0) return [0, 0, l * 100];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h =
    max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s * 100, l * 100];
}

/** A distinct shade of `hex` for the nth crop sharing that color. Crop colors
 *  come from a fixed per-crop-type palette, so a garden with several crops of
 *  one type — or several the palette doesn't know (all generic green) — would
 *  otherwise stack bands nobody can tell apart. Nudging hue and lightness in
 *  alternating directions keeps a tomato red and a green herb green. */
function shadeVariant(hex: string, n: number): string {
  const hsl = hexToHsl(hex);
  if (!hsl || n <= 0) return hex;
  const [h, s, l] = hsl;
  const dir = n % 2 === 1 ? 1 : -1;
  const step = Math.ceil(n / 2);
  const h2 = (((h + dir * 15 * step) % 360) + 360) % 360;
  const l2 = Math.min(76, Math.max(24, l + dir * 11 * step));
  return `hsl(${h2.toFixed(0)} ${s.toFixed(0)}% ${l2.toFixed(0)}%)`;
}

/** Cumulative-series key for one variety's slice of a crop. Picks with no
 *  variety recorded share the crop's `none` slice. */
const varietyKey = (cropId: number, varietyId: number | null | undefined) =>
  `${cropId}:${varietyId ?? 'none'}`;

/** One color per crop, deduplicated so no two bands share a fill. */
function bandColors(names: string[]): string[] {
  const seen = new Map<string, number>();
  return names.map((name) => {
    const base = cropIconColor(name);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return shadeVariant(base, n);
  });
}

/** Season charts for the Harvest page — a cumulative value/weight trend plus a
 *  by-crop breakdown. Uses $ value when any crop is priced, otherwise pounds.
 *
 *  The two views are wired together. The bar list doubles as the trend's legend
 *  in "By crop" mode — tap a crop to select/deselect it. The cumulative figure
 *  (value and weight) reflects only the selected crops, so it changes as you
 *  toggle. Dragging across the trend sets a date and the bars report each crop's
 *  running total as of that date. Switching back to the total view re-selects
 *  every crop. */
export function HarvestCharts({ byCrop, events }: { byCrop: ByCrop[]; events: Ev[] }) {
  const [mode, setMode] = useState<'total' | 'byCrop'>('total');
  const [hidden, setHidden] = useState<Set<string>>(new Set()); // crops deselected from the trend
  const [active, setActive] = useState<number | null>(null); // scrubbed date index

  const useValue = events.some((e) => e.value > 0);
  const fmt = useValue ? fmtMoney : fmtLb;
  const metricEv = (e: Ev) => (useValue ? e.value : e.lb);
  const metricCrop = (c: ByCrop) => (useValue ? c.value : c.totalLb);

  const total = events.reduce((s, e) => s + metricEv(e), 0);
  if (events.length === 0 || total <= 0) return null;

  // ── cumulative over time (running total) ──
  const byDate = new Map<string, number>();
  for (const e of events) byDate.set(e.date, (byDate.get(e.date) ?? 0) + metricEv(e));
  const dates = [...byDate.keys()].sort();
  let cum = 0;
  const cumPoints = dates.map((d) => {
    cum += byDate.get(d)!;
    return cum;
  });
  const maxCum = cum || 1;
  const lastI = dates.length - 1;

  const W = 320,
    H = 90;
  const x = (i: number) => (dates.length <= 1 ? W : (i / (dates.length - 1)) * W);
  const y = (v: number) => H - (v / maxCum) * H;
  const linePts = cumPoints.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const linePath = `M ${linePts.join(' L ')}`;
  const areaPath = `M ${x(0).toFixed(1)},${H} L ${linePts.join(' L ')} L ${x(dates.length - 1).toFixed(1)},${H} Z`;
  const fmtTick = (key: string) =>
    new Date(`${key}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

  // ── by crop ──
  // Every crop that was picked gets its own row and its own band — nothing is
  // folded into a lump. A crop with no market price contributes nothing to the
  // value chart but still has weight, so it is kept rather than dropped (which
  // would quietly move its pounds into the crop-less tail).
  const crops = [...byCrop]
    .filter((c) => c.totalLb > 0 || c.value > 0)
    .sort((a, b) => metricCrop(b) - metricCrop(a) || b.totalLb - a.totalLb);
  const maxCrop = Math.max(1, ...crops.map(metricCrop));

  const metricWord = useValue ? 'value' : 'weight';

  // ── cumulative broken down by crop (stacked bands) ──
  // One band per crop, largest on the bottom, so the top of the stack traces
  // the very same total cumulative line. The only band that is not a crop is
  // the tail for picks recorded against no crop at all.
  const cropIds = new Set(crops.map((c) => c.crop.id));
  const colors = bandColors(crops.map((c) => c.crop.name));
  const bands: { key: string; name: string; color: string }[] = crops.map((c, i) => ({
    key: String(c.crop.id),
    name: c.crop.name,
    color: colors[i],
  }));
  const hasOther = events.some(
    (e) => (e.cropId == null || !cropIds.has(e.cropId)) && (e.value > 0 || e.lb > 0)
  );
  if (hasOther) bands.push({ key: 'other', name: 'Picks with no crop', color: OTHER_COLOR });

  // per-band, per-date increments for BOTH metrics → cumulative aligned to `dates`
  const bump = (inc: Map<string, Map<string, number>>, key: string, date: string, n: number) => {
    let m = inc.get(key);
    if (!m) {
      m = new Map();
      inc.set(key, m);
    }
    m.set(date, (m.get(date) ?? 0) + n);
  };
  const incVal = new Map<string, Map<string, number>>();
  const incLb = new Map<string, Map<string, number>>();
  // The same again, one level finer: a crop's picks split by variety, so the
  // sub-rows under a crop follow the scrubbed date exactly as its own row does.
  const incVarVal = new Map<string, Map<string, number>>();
  const incVarLb = new Map<string, Map<string, number>>();
  for (const e of events) {
    const crop = e.cropId != null && cropIds.has(e.cropId);
    const key = crop ? String(e.cropId) : 'other';
    bump(incVal, key, e.date, e.value);
    bump(incLb, key, e.date, e.lb);
    if (crop) {
      const vk = varietyKey(e.cropId!, e.varietyId);
      bump(incVarVal, vk, e.date, e.value);
      bump(incVarLb, vk, e.date, e.lb);
    }
  }
  const cumFrom = (inc: Map<string, Map<string, number>>, keys: string[]) =>
    new Map(
      keys.map((k) => {
        const m = inc.get(k) ?? new Map<string, number>();
        let a = 0;
        return [
          k,
          dates.map((d) => {
            a += m.get(d) ?? 0;
            return a;
          }),
        ] as const;
      })
    );
  const bandKeys = bands.map((b) => b.key);
  const bandCumVal = cumFrom(incVal, bandKeys);
  const bandCumLb = cumFrom(incLb, bandKeys);
  const bandCum = useValue ? bandCumVal : bandCumLb; // active metric, for the stack
  const varKeys = [...incVarVal.keys()];
  const varCumVal = cumFrom(incVarVal, varKeys);
  const varCumLb = cumFrom(incVarLb, varKeys);

  // Visible bands honor the legend toggles; never let the stack go fully empty.
  const visibleBands = bands.filter((b) => !hidden.has(b.key));
  const renderBands = visibleBands.length > 0 ? visibleBands : bands;

  // Each band sits on the running sum of the bands beneath it. Path = top edge
  // left→right, then the lower edge right→left, closed.
  const stackPaths = renderBands.map((b, j) => {
    const lower = dates.map((_, i) => {
      let s = 0;
      for (let k = 0; k < j; k++) s += bandCum.get(renderBands[k].key)![i];
      return s;
    });
    const upper = lower.map((v, i) => v + bandCum.get(b.key)![i]);
    const top = upper.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const bot = lower.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).reverse();
    return { ...b, d: `M ${top.join(' L ')} L ${bot.join(' L ')} Z` };
  });
  // Top edge of the visible stack — the line we keep drawn over the bands.
  const visibleTop = dates.map((_, i) =>
    renderBands.reduce((s, b) => s + bandCum.get(b.key)![i], 0)
  );
  const visTopPath = `M ${visibleTop.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' L ')}`;

  const showByCrop = mode === 'byCrop' && bands.length > 1;

  // Cumulative value + weight for the header — scoped to the selected crops in
  // By-crop mode, or everything in Total mode.
  const scopeBands = showByCrop ? renderBands : bands;
  const headVal = scopeBands.reduce((s, b) => s + bandCumVal.get(b.key)![lastI], 0);
  const headLb = scopeBands.reduce((s, b) => s + bandCumLb.get(b.key)![lastI], 0);
  const headPrimary = useValue ? fmtMoney(headVal) : fmtLb(headLb);
  const headSecondary = useValue ? fmtLb(headLb) : null;

  // ── scrub-to-inspect geometry (percentages of the chart box, so it survives
  // the non-uniform SVG scaling) ──
  const topSeries = showByCrop ? visibleTop : cumPoints;
  const act = active != null && active >= 0 && active < dates.length ? active : null;
  const leftPct = (i: number) => (dates.length <= 1 ? 100 : (i / (dates.length - 1)) * 100);
  const topPct = (v: number) => Math.max(0, Math.min(100, (1 - v / maxCum) * 100));
  const onScrub = (e: ReactPointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setActive(Math.round(f * (dates.length - 1)));
  };
  const endScrub = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== 'mouse') setActive(null);
  };

  /** A crop's variety breakdown, as of the scrubbed date (its own row uses the
   *  same index, so the parts always sum to the whole). It takes two varieties
   *  to make a breakdown: a crop logged without any — or one whose picks all
   *  name the same variety, whether or not some were left unassigned — is
   *  already fully described by its own row, so it gets nothing rather than
   *  rows repeating its own total. Where there are two or more, picks left
   *  without a variety are named as such and sort last, so the rows account for
   *  the crop rather than quietly falling short of it. */
  const varietyRows = (c: ByCrop) => {
    if (!c.varieties?.length) return [];
    const at = act ?? lastI;
    const read = (key: string) => ({
      key,
      value: varCumVal.get(key)?.[at] ?? 0,
      lb: varCumLb.get(key)?.[at] ?? 0,
    });
    const rows: { id: number | null; name: string; key: string; value: number; lb: number }[] =
      c.varieties
        .map((v) => ({
          id: v.id as number | null,
          name: v.name,
          ...read(varietyKey(c.crop.id, v.id)),
        }))
        .filter((r) => r.value > 0 || r.lb > 0)
        .sort((a, b) => (useValue ? b.value - a.value : b.lb - a.lb) || b.lb - a.lb);
    // One variety is not a breakdown. Anything the crop picked without a
    // variety belongs to that one variety by elimination, and both are already
    // in the crop's own total — so nothing is broken out and nothing is lost.
    if (rows.length <= 1) return [];
    const none = read(varietyKey(c.crop.id, null));
    if (none.value > 0 || none.lb > 0) rows.push({ id: null, name: 'No variety', ...none });
    return rows.map((r) => ({
      ...r,
      primary: useValue ? fmtMoney(r.value) : fmtLb(r.lb),
      secondary: useValue && r.lb > 0 ? fmtLb(r.lb) : null,
    }));
  };

  const toggleBand = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        return next;
      }
      if (bands.filter((b) => !prev.has(b.key)).length <= 1) return prev; // keep ≥1 selected
      next.add(key);
      return next;
    });
  };

  return (
    <section className="space-y-3">
      <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">Charts</p>

      {/* cumulative trend — running total, or broken down by crop */}
      {dates.length > 1 && (
        <div className="rounded-xl bg-card ring-1 ring-black/[0.05] shadow-sm p-3">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <div className="flex items-baseline gap-1.5 min-w-0">
              <span className="text-[11px] font-medium text-foreground/70 capitalize truncate">
                Cumulative {metricWord}
              </span>
              <span className="shrink-0 text-sm font-heading font-semibold text-emerald-700 tabular-nums">
                {headPrimary}
              </span>
              {headSecondary && (
                <span className="shrink-0 text-[11px] font-normal text-muted-foreground/60 tabular-nums">
                  · {headSecondary}
                </span>
              )}
            </div>
            {bands.length > 1 && (
              <div
                className="inline-flex shrink-0 items-center rounded-lg bg-muted/50 ring-1 ring-border/40 p-0.5"
                role="tablist"
                aria-label="Cumulative chart breakdown"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'total'}
                  onClick={() => {
                    setMode('total');
                    setHidden(new Set());
                  }}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-all ${
                    mode === 'total'
                      ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                  title="Show the running total across all crops"
                >
                  Total
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'byCrop'}
                  onClick={() => setMode('byCrop')}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-all ${
                    mode === 'byCrop'
                      ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                  title="Break the running total down by crop — legend & toggles are the bars below"
                >
                  By crop
                </button>
              </div>
            )}
          </div>

          {/* chart box — relative so the crosshair/readout can overlay it */}
          <div className="relative h-24 select-none">
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              className="h-24 w-full overflow-visible"
            >
              <defs>
                <linearGradient id="harvestArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgb(16 185 129)" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="rgb(16 185 129)" stopOpacity="0.02" />
                </linearGradient>
              </defs>
              {showByCrop ? (
                <>
                  {stackPaths.map((b) => (
                    <path
                      key={b.key}
                      d={b.d}
                      fill={b.color}
                      fillOpacity="0.82"
                      stroke="var(--card)"
                      strokeOpacity="0.55"
                      strokeWidth="0.75"
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                  {/* the running total of the selected crops, crisp over the bands */}
                  <path
                    d={visTopPath}
                    fill="none"
                    stroke="rgb(5 150 105)"
                    strokeWidth="2"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </>
              ) : (
                <>
                  <path d={areaPath} fill="url(#harvestArea)" />
                  <path
                    d={linePath}
                    fill="none"
                    stroke="rgb(5 150 105)"
                    strokeWidth="2"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </>
              )}
            </svg>

            {/* crosshair + marker + readout pill (visuals don't catch pointers) */}
            {act != null && (
              <>
                <div
                  className="pointer-events-none absolute top-0 bottom-0 w-px bg-foreground/20"
                  style={{ left: `${leftPct(act)}%` }}
                />
                <div
                  className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-600 ring-2 ring-card"
                  style={{ left: `${leftPct(act)}%`, top: `${topPct(topSeries[act])}%` }}
                />
                <div
                  className={`pointer-events-none absolute top-0.5 ${act > (dates.length - 1) / 2 ? 'left-0.5' : 'right-0.5'} flex items-baseline gap-1 whitespace-nowrap rounded-md bg-card/95 px-1.5 py-0.5 text-[9px] tabular-nums shadow-sm ring-1 ring-black/10`}
                >
                  <span className="font-medium text-foreground/80">{fmtTick(dates[act])}</span>
                  <span className="font-semibold text-emerald-700">{fmt(topSeries[act])}</span>
                </div>
              </>
            )}

            {/* transparent capture layer — hover (mouse) or drag (touch) to scrub */}
            <div
              className="absolute inset-0 cursor-crosshair"
              style={{ touchAction: 'none' }}
              onPointerDown={onScrub}
              onPointerMove={onScrub}
              onPointerLeave={() => setActive(null)}
              onPointerUp={endScrub}
              onPointerCancel={() => setActive(null)}
            />
          </div>

          {(() => {
            // Evenly spaced date ticks. x is linear in index, so equally spaced
            // indices line up with `justify-between`.
            const tickCount = Math.min(5, dates.length);
            const idxs = [
              ...new Set(
                Array.from({ length: tickCount }, (_, i) =>
                  Math.round((i * (dates.length - 1)) / Math.max(1, tickCount - 1))
                )
              ),
            ];
            return (
              <div className="mt-1 flex justify-between text-[9px] text-muted-foreground/60 tabular-nums">
                {idxs.map((idx) => (
                  <span key={idx}>{fmtTick(dates[idx])}</span>
                ))}
              </div>
            );
          })()}

          <p className="mt-1.5 text-[10px] text-muted-foreground/45">
            {showByCrop
              ? 'Drag to inspect a date · tap a crop below to select/deselect it'
              : 'Drag across to read the total on any date'}
          </p>
        </div>
      )}

      {/* by crop — bar list. Doubles as the trend's legend & controls in By-crop
          mode, and reports values "as of" the scrubbed date. */}
      <div className="rounded-xl bg-card ring-1 ring-black/[0.05] shadow-sm p-3.5">
        <div className="flex items-baseline justify-between mb-3 gap-2">
          <span className="text-[11px] font-medium text-foreground/70 capitalize truncate">
            {metricWord} by crop
            {act != null && (
              <span className="ml-1.5 font-normal text-muted-foreground/60 normal-case">
                as of {fmtTick(dates[act])}
              </span>
            )}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground/50">
            {crops.length} {crops.length === 1 ? 'crop' : 'crops'}
          </span>
        </div>
        <div className="space-y-2">
          {crops.map((c, ci) => {
            const key = String(c.crop.id);
            const color = colors[ci]; // same fill as this crop's band above
            const off = hidden.has(key);
            const asOfVal = act != null ? (bandCumVal.get(key)?.[act] ?? 0) : c.value;
            const asOfLb = act != null ? (bandCumLb.get(key)?.[act] ?? 0) : c.totalLb;
            const shownMetric = act != null ? (useValue ? asOfVal : asOfLb) : metricCrop(c);
            const w = Math.max(act != null ? 0 : 4, Math.round((shownMetric / maxCrop) * 100));
            const primary = useValue ? fmtMoney(asOfVal) : fmtLb(asOfLb);
            const secondary = useValue && asOfLb > 0 ? fmtLb(asOfLb) : null;
            const varieties = varietyRows(c);
            return (
              <div key={c.crop.id} className={off ? 'opacity-60' : ''}>
                <button
                  type="button"
                  onClick={showByCrop ? () => toggleBand(key) : undefined}
                  aria-pressed={showByCrop ? !off : undefined}
                  title={
                    showByCrop
                      ? off
                        ? `Select ${c.crop.name}`
                        : `Deselect ${c.crop.name}`
                      : undefined
                  }
                  className={`-mx-1.5 flex w-full items-center gap-2.5 rounded-lg px-1.5 py-1 text-left transition ${showByCrop ? 'cursor-pointer hover:bg-muted/40' : 'cursor-default'}`}
                >
                  <CropAvatar name={c.crop.name} size={28} className="shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[13px] font-medium truncate">
                        {c.crop.name}
                        {c.picks && act == null ? (
                          <span className="font-normal text-muted-foreground/55">
                            {' '}
                            · {c.picks} {c.picks === 1 ? 'pick' : 'picks'}
                          </span>
                        ) : null}
                      </span>
                      <span className="shrink-0 text-[13px] font-semibold tabular-nums tracking-tight">
                        {primary}
                        {secondary && (
                          <span className="ml-1.5 text-[11px] font-normal text-muted-foreground/60">
                            {secondary}
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted/40">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${w}%`, backgroundColor: off ? MUTED_BAR : color }}
                      />
                    </div>
                  </div>
                </button>

                {/* Varieties of this crop — a quiet breakdown that sums to the
                  row above it, shown only where picks carry a variety. */}
                {varieties.length > 0 && (
                  <ul
                    className="mt-1 ml-[38px] space-y-0.5 border-l pl-2"
                    style={{ borderColor: `color-mix(in srgb, ${color} 40%, transparent)` }}
                  >
                    {varieties.map((v) => (
                      <li
                        key={v.key}
                        className="flex items-baseline justify-between gap-2 text-[11px] leading-snug"
                      >
                        <span
                          className={`truncate ${v.id == null ? 'italic text-muted-foreground/45' : 'text-muted-foreground/75'}`}
                        >
                          {v.name}
                        </span>
                        <span className="shrink-0 tabular-nums text-muted-foreground/70">
                          {v.primary}
                          {v.secondary && (
                            <span className="ml-1 text-muted-foreground/45">{v.secondary}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}

          {/* Uncategorized band — picks logged against no crop. Every crop has
              its own row above, so this is the only thing left in the tail. */}
          {showByCrop && hasOther && (
            <div className="flex items-center gap-2.5 px-1.5 pt-0.5 text-[11px] text-muted-foreground/70">
              <span
                className="grid h-7 w-7 shrink-0 place-items-center rounded-[9px]"
                style={{ background: `color-mix(in srgb, ${OTHER_COLOR} 16%, transparent)` }}
              >
                <span
                  className="h-2.5 w-2.5 rounded-[3px]"
                  style={{ backgroundColor: OTHER_COLOR }}
                />
              </span>
              <span className="flex-1">Picks with no crop</span>
              <span className="tabular-nums font-medium text-foreground/70">
                {fmt(bandCum.get('other')?.[act ?? lastI] ?? 0)}
              </span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
