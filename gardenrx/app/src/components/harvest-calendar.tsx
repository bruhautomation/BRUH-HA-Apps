'use client';

import { useMemo } from 'react';
import type { Crop, Variety, CropGroup } from '@/lib/database.types';
import { VARIETY_CATALOG } from '@/lib/variety-catalog';
import { parseHarvestWindow, rangeMidpoint, type HarvestRange } from '@/lib/harvest-windows';
import { CalendarDays, ChevronDown } from 'lucide-react';

const MONTH_ABBR = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

interface Props {
  crops: Crop[];
  varieties: Variety[];
  cropGroups: CropGroup[];
}

interface VarietyRow {
  variety: Variety;
  crop: Crop;
  cropGroup: CropGroup | null;
  phrase: string;
  ranges: HarvestRange[];
}

export function HarvestCalendar({ crops, varieties, cropGroups }: Props) {
  const currentMonth = new Date().getMonth();

  // Build variety rows with parsed ranges
  const rows = useMemo<VarietyRow[]>(() => {
    const cropMap = new Map(crops.map((c) => [c.id, c]));
    const groupMap = new Map(cropGroups.map((g) => [g.id, g]));
    return varieties
      .map((variety) => {
        const profile = VARIETY_CATALOG[variety.name];
        if (!profile?.harvestWindow) return null;
        const crop = cropMap.get(variety.crop_id);
        if (!crop) return null;
        const ranges = parseHarvestWindow(profile.harvestWindow);
        if (ranges.length === 0) return null;
        return {
          variety,
          crop,
          cropGroup: crop.crop_group_id ? (groupMap.get(crop.crop_group_id) ?? null) : null,
          phrase: profile.harvestWindow,
          ranges,
        };
      })
      .filter((r): r is VarietyRow => r !== null);
  }, [crops, varieties, cropGroups]);

  // Group rows by crop, sorted by earliest range midpoint
  const groups = useMemo(() => {
    const byCrop = new Map<number, VarietyRow[]>();
    for (const r of rows) {
      if (!byCrop.has(r.crop.id)) byCrop.set(r.crop.id, []);
      byCrop.get(r.crop.id)!.push(r);
    }
    // Sort varieties within each crop by midpoint of first range
    for (const list of byCrop.values()) {
      list.sort((a, b) => rangeMidpoint(a.ranges[0]) - rangeMidpoint(b.ranges[0]));
    }
    // Sort crops by earliest midpoint
    return [...byCrop.entries()]
      .map(([_cropId, list]) => ({
        crop: list[0].crop,
        group: list[0].cropGroup,
        rows: list,
        earliest: Math.min(...list.flatMap((r) => r.ranges.map(rangeMidpoint))),
      }))
      .sort((a, b) => a.earliest - b.earliest);
  }, [rows]);

  if (rows.length === 0) return null;

  const totalVarieties = rows.length;
  const totalCrops = groups.length;

  return (
    <details
      className="group/cal rounded-xl bg-card ring-1 ring-black/[0.04] shadow-sm overflow-hidden mb-6"
      open
    >
      {/* Header / summary */}
      <summary className="flex items-center gap-3 px-4 py-3.5 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none hover:bg-parchment-50/40 transition-colors">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-emerald-50 ring-1 ring-emerald-200/50 shrink-0">
          <CalendarDays className="w-4 h-4 text-emerald-700" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-heading text-base font-semibold tracking-tight text-foreground">
            Expected Harvest Windows
          </p>
          <p className="text-[11px] text-muted-foreground/70">
            {totalVarieties} {totalVarieties === 1 ? 'variety' : 'varieties'} across {totalCrops}{' '}
            {totalCrops === 1 ? 'crop' : 'crops'}
          </p>
        </div>
        <ChevronDown className="w-4 h-4 text-muted-foreground/50 transition-transform group-open/cal:rotate-180" />
      </summary>

      {/* Calendar body */}
      <div className="border-t border-border/40 bg-gradient-to-br from-parchment-50/40 via-card to-card">
        {/* Month header */}
        <div className="sticky top-0 z-10 bg-card/95 backdrop-blur-sm border-b border-border/30 pt-2 pb-1.5">
          <div className="grid grid-cols-12 px-3">
            {MONTH_ABBR.map((m, i) => (
              <div
                key={m}
                className={`text-center text-[9px] font-medium tracking-wider uppercase transition-colors ${
                  i === currentMonth ? 'text-emerald-700 font-semibold' : 'text-muted-foreground/50'
                }`}
              >
                {m[0]}
              </div>
            ))}
          </div>
        </div>

        <div className="px-3 py-3 space-y-3 relative">
          {/* Vertical month gridlines behind rows */}
          <div className="pointer-events-none absolute inset-0 px-3 py-3">
            <div className="relative w-full h-full grid grid-cols-12">
              {MONTH_ABBR.map((_, i) => (
                <div
                  key={i}
                  className={`border-l border-dashed ${
                    i === 0
                      ? 'border-transparent'
                      : i === currentMonth
                        ? 'border-emerald-300/40'
                        : 'border-border/20'
                  }`}
                />
              ))}
            </div>
          </div>

          {/* Groups */}
          {groups.map((g) => (
            <CropSection key={g.crop.id} group={g} currentMonth={currentMonth} />
          ))}
        </div>
      </div>
    </details>
  );
}

function CropSection({
  group,
  currentMonth,
}: {
  group: { crop: Crop; group: CropGroup | null; rows: VarietyRow[] };
  currentMonth: number;
}) {
  return (
    <div className="relative space-y-1.5">
      <div className="flex items-baseline gap-2 pb-0.5 mb-0.5">
        <p className="font-heading text-[13px] font-semibold text-foreground">{group.crop.name}</p>
        <p className="text-[10px] text-muted-foreground/50">
          {group.rows.length} {group.rows.length === 1 ? 'variety' : 'varieties'}
        </p>
      </div>
      {group.rows.map((r) => (
        <VarietyBar key={r.variety.id} row={r} currentMonth={currentMonth} />
      ))}
    </div>
  );
}

function VarietyBar({ row, currentMonth }: { row: VarietyRow; currentMonth: number }) {
  return (
    <div className="group/row">
      {/* Name + phrase on one line */}
      <div className="flex items-baseline gap-2 mb-0.5 px-0.5">
        <p className="text-[11px] text-foreground/80 truncate flex-1 min-w-0">{row.variety.name}</p>
        <p className="text-[9px] text-muted-foreground/60 font-mono truncate" title={row.phrase}>
          {row.phrase}
        </p>
      </div>

      {/* 12-col timeline */}
      <div className="relative h-2.5 rounded-full bg-muted/30">
        {row.ranges.map((range, i) => (
          <RangeBar key={i} range={range} isCurrent={isMonthInRange(currentMonth, range)} />
        ))}
      </div>
    </div>
  );
}

function RangeBar({ range, isCurrent }: { range: HarvestRange; isCurrent: boolean }) {
  // Convert months + fractions to 0-12 scale; handle wrap (e.g., Nov → Feb)
  const startFloat = range.startMonth + range.startFrac;
  let endFloat = range.endMonth + range.endFrac;
  if (endFloat < startFloat) endFloat += 12; // wrap

  // For wrap, render two segments
  if (endFloat > 12) {
    return (
      <>
        <Segment left={startFloat} right={12} isCurrent={isCurrent} wraps="right" />
        <Segment left={0} right={endFloat - 12} isCurrent={isCurrent} wraps="left" />
      </>
    );
  }
  return <Segment left={startFloat} right={endFloat} isCurrent={isCurrent} />;
}

function Segment({
  left,
  right,
  isCurrent,
  wraps,
}: {
  left: number;
  right: number;
  isCurrent: boolean;
  wraps?: 'left' | 'right';
}) {
  const leftPct = (left / 12) * 100;
  const widthPct = ((right - left) / 12) * 100;
  const rounded =
    wraps === 'right' ? 'rounded-l-full' : wraps === 'left' ? 'rounded-r-full' : 'rounded-full';
  return (
    <div
      className={`absolute top-0 bottom-0 ${rounded} ${
        isCurrent
          ? 'bg-gradient-to-r from-emerald-400 to-emerald-600 ring-1 ring-emerald-500/30 shadow-[0_0_0_1px_rgba(16,185,129,0.15),0_1px_3px_rgba(0,0,0,0.06)]'
          : 'bg-gradient-to-r from-emerald-300/70 to-emerald-500/80'
      }`}
      style={{ left: `${leftPct}%`, width: `${Math.max(widthPct, 2)}%` }}
    />
  );
}

function isMonthInRange(month: number, range: HarvestRange): boolean {
  if (range.startMonth <= range.endMonth) {
    return month >= range.startMonth && month <= range.endMonth;
  }
  // wrap
  return month >= range.startMonth || month <= range.endMonth;
}
