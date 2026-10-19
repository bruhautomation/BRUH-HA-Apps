/**
 * Parse free-form harvest-window phrases from the variety catalog into numeric
 * month ranges that can be rendered on a 12-month calendar.
 *
 * Handles: "Late October – November", "Mid – late October", "July",
 * "June through August", "April – October (day-neutral)",
 * "March through May, September through November" (multi-range),
 * "August – Frost".
 */

import { VARIETY_CATALOG } from '@/lib/variety-catalog';
import type { Variety } from '@/lib/database.types';

export interface HarvestRange {
  /** 0-indexed start month (0 = Jan) */
  startMonth: number;
  /** 0-1 fraction into the start month where the window begins */
  startFrac: number;
  /** 0-indexed end month */
  endMonth: number;
  /** 0-1 fraction into the end month where the window ends */
  endFrac: number;
}

const MONTHS = [
  'january',
  'february',
  'march',
  'april',
  'may',
  'june',
  'july',
  'august',
  'september',
  'october',
  'november',
  'december',
];

// Accept short forms too
const MONTH_ALIASES: Record<string, number> = {
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  jun: 5,
  jul: 6,
  aug: 7,
  sep: 8,
  sept: 8,
  oct: 9,
  nov: 10,
  dec: 11,
};

interface Qualifier {
  startFrac: number;
  endFrac: number;
}

const QUAL_EARLY: Qualifier = { startFrac: 0, endFrac: 0.34 };
const QUAL_MID: Qualifier = { startFrac: 0.33, endFrac: 0.67 };
const QUAL_LATE: Qualifier = { startFrac: 0.66, endFrac: 1 };
const QUAL_WHOLE: Qualifier = { startFrac: 0, endFrac: 1 };

function findQualifier(text: string): Qualifier | null {
  const t = text.toLowerCase();
  if (/\b(late|end of|end)\b/.test(t)) return QUAL_LATE;
  if (/\b(mid|middle of)\b/.test(t)) return QUAL_MID;
  if (/\b(early|beginning of|start of)\b/.test(t)) return QUAL_EARLY;
  return null;
}

function findMonth(text: string): number | null {
  const t = text.toLowerCase();
  for (let i = 0; i < MONTHS.length; i++) {
    if (t.includes(MONTHS[i])) return i;
  }
  for (const [alias, i] of Object.entries(MONTH_ALIASES)) {
    if (new RegExp(`\\b${alias}\\b`).test(t)) return i;
  }
  // "Frost" in NC ≈ early November
  if (/\bfrost\b/.test(t)) return 10;
  return null;
}

interface Token {
  month: number | null;
  qualifier: Qualifier | null;
}

function parseToken(s: string): Token {
  return { month: findMonth(s), qualifier: findQualifier(s) };
}

function parseClause(raw: string): HarvestRange | null {
  // Normalize separators to a single sentinel
  const sep = '\u0001';
  const normalized = raw
    .replace(/\bthrough\b/gi, sep)
    .replace(/[\u2013\u2014]/g, sep) // en/em dash
    .replace(/\s-\s/g, sep); // plain hyphen with spaces (avoid eating "Mid-October")

  const parts = normalized
    .split(sep)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;

  if (parts.length === 1) {
    const t = parseToken(parts[0]);
    if (t.month == null) return null;
    const q = t.qualifier ?? QUAL_WHOLE;
    return { startMonth: t.month, startFrac: q.startFrac, endMonth: t.month, endFrac: q.endFrac };
  }

  // Two-sided range: left side → start, right side → end.
  // Either side may omit the month name, inheriting from the other side.
  const a = parseToken(parts[0]);
  const b = parseToken(parts[parts.length - 1]);

  const startMonth = a.month ?? b.month;
  const endMonth = b.month ?? a.month;
  if (startMonth == null || endMonth == null) return null;

  const startQ = a.qualifier ?? QUAL_EARLY; // default: start of first month
  const endQ = b.qualifier ?? QUAL_LATE; // default: end of last month

  return {
    startMonth,
    startFrac: startQ.startFrac,
    endMonth,
    endFrac: endQ.endFrac,
  };
}

export function parseHarvestWindow(phrase: string): HarvestRange[] {
  if (!phrase) return [];
  // Strip parentheticals
  const cleaned = phrase.replace(/\([^)]*\)/g, '').trim();
  // Split into sub-clauses for multi-range windows ("... ; ..." or "A through B, C through D").
  // Lookahead allows either case so "march through may, september" splits correctly.
  const clauses = cleaned.split(/[;]|,\s*(?=[A-Za-z])/g);
  return clauses.map(parseClause).filter((r): r is HarvestRange => r !== null);
}

/** The peak month (closest to middle) of a range — useful for sorting. */
export function rangeMidpoint(r: HarvestRange): number {
  const start = r.startMonth + r.startFrac;
  const end = r.endMonth + r.endFrac;
  // If the range wraps (Nov → Feb), treat end as +12
  const e = end < start ? end + 12 : end;
  return (start + e) / 2;
}

/** Whether month `m` (0 = Jan) falls inside a harvest range, handling wrap (Nov → Feb). */
export function monthInHarvestRange(m: number, r: HarvestRange): boolean {
  return r.startMonth <= r.endMonth
    ? m >= r.startMonth && m <= r.endMonth
    : m >= r.startMonth || m <= r.endMonth;
}

/**
 * Whether a crop's fruit is *in season right now* — i.e. the current month falls
 * within any of its varieties' catalog harvest windows. `hasWindow` reports
 * whether we know a window at all; crops with none (e.g. ornamentals) are never
 * in season. Used to suppress pre-harvest-interval warnings out of season, when
 * there's nothing to harvest and a PHI is irrelevant.
 */
export function harvestSeason(
  cropId: number,
  varieties: Pick<Variety, 'name' | 'crop_id'>[],
  now: Date = new Date()
): { inSeason: boolean; hasWindow: boolean } {
  const m = now.getMonth();
  let hasWindow = false;
  for (const v of varieties) {
    if (v.crop_id !== cropId) continue;
    const phrase = VARIETY_CATALOG[v.name]?.harvestWindow;
    if (!phrase) continue;
    hasWindow = true;
    if (parseHarvestWindow(phrase).some((r) => monthInHarvestRange(m, r))) {
      return { inSeason: true, hasWindow: true };
    }
  }
  return { inSeason: false, hasWindow };
}
